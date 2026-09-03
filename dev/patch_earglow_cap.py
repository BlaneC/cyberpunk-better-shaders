#!/usr/bin/env python3
"""earglow-cap -- a THICKNESS FLOOR in the ear-glow transfer (handoff/101 sec 18).

The user, on the shipped default (`...-cone2all-fog-earglow`), verbatim:

    "Also if the intensity gets more intense as geometry gets thinner, we might
     want to cap that at a certain point. Childrens ears GLOW. They emit alot of
     light which doesnt look correct. Everything else looks great"

That is a correct reading of the transfer. W3 is

    T(t) = 0.5 * (exp(-t/ld) + exp(-t/(wide*ld)))     ld = (3.67, 1.37, 0.68) mm

which is monotone DECREASING in t, so the glow is monotone INCREASING as the
flesh gets thinner, and query B's tmin is 1.5 mm -- so a child's ear, thinner
than an adult's everywhere, sits high on the curve and can only ever be
brighter. T(1.5)/T(3) is 1.25x / 1.59x / 1.99x per channel; the hue moves too
(R/G 1.43 at 1.5 mm against 1.82 at 3 mm), so a thin ear is not just brighter,
it is PINKER. Nothing in the shader caps it.

THE ONE VARIABLE: a floor on t, INSIDE THE TRANSFER, NOT IN THE RAY.

    t_eff = NMax(t_B, t_cap)      then evaluate T at t_eff

Anything thinner than t_cap glows exactly like t_cap. There is no
discontinuity anywhere: t_eff is continuous in t, and T is continuous, so the
composition is; at t = t_cap the two branches meet by construction, and above
t_cap nothing whatsoever changes. Adult ears (4-8 mm) are untouched by cap3
and cap4 BY CONSTRUCTION, not by tuning -- which is what makes the frame in
sec 18 a real discriminator.

WHY max ON t AND NOT min ON T. T is monotone decreasing, so
min(T(t), T(t_cap)) == T(max(t, t_cap)) exactly -- the two are the same
function. The max form costs ONE OpExtInst NMax evaluated once and shared by
all six exponentials; the min form costs three NMins (one per channel, after
the lobes are combined) plus three per-channel constants. One instruction
against three, and the constant is a physical thickness in metres rather than
three magic transmittances that would have to be re-derived every time `wide`
or `ld` moved.

WHY NMax AND NOT FMax. GLSL450 NMax returns the non-NaN operand when one
operand is NaN; FMax's NaN behaviour is undefined. t comes from
OpRayQueryGetIntersectionTKHR on a COMMITTED intersection, so a NaN is not
expected -- but NMax turns "not expected" into "cannot": a NaN t yields t_cap,
the Exp chain stays finite, and no NaN can reach the radiance write. Identical
cost. Same reasoning as 100 sec 3's NClamp totality guards.

WHERE THE CAP IS *NOT* APPLIED. Query C -- the sun-visibility query added in
sec 16 -- starts at P + (t_B + 1 mm)*S and must keep the TRUE t_B: capping it
would move the origin of the visibility ray, i.e. ask a different geometric
question. The cap is a TRANSFER change and nothing else. `--decoy capray`
builds the version that gets this wrong so verify_earglow_cap.py can be shown
to reject it.

HOW IT IS BUILT. This file adds no arithmetic of its own. It calls
patch_earglow_rq3.build() -- the SHIPPED patcher of the current default rung,
unmodified and not copied -- and then performs one asserted transformation on
the instruction list it returns:

  1. find the unique OpRayQueryGetIntersectionTKHR (query B's committed t),
  2. find its unique guard OpSelect(hitB, t, tmax),
  3. assert the guard's consumers are EXACTLY: one OpFAdd (query C's push) and
     the 6 (or 3) OpFMul that start the Exp chains -- anything else and the
     module is refused rather than half-capped,
  4. insert  %t_eff = OpExtInst %glsl NMax %t_guarded %t_cap  after the guard,
  5. repoint ONLY the transfer's OpFMuls at %t_eff.

`--cap 0` emits nothing at all and must reproduce the default rung byte for
byte; build_earglow_cap.sh makes that a gate. k is NOT touched (70/71: 0.22).

  ./dev/patch_earglow_cap.py <in.spvasm> --outdir D --k 0.22 --cap 0.003 \
      --wide 4.0 --wrap 0.35
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
from patch_rayq import _add_header
from patch_earglow_rq import _fc
import patch_earglow as E
import patch_earglow_rq3 as R3

DECOYS = ('capray', 'capmin', 'nocap')


def _res(line):
    m = re.match(r'\s*(%\w+)\s*=\s*Op', line)
    return m.group(1) if m else None


def apply_cap(mod, consts, edits, cap, decoy=None):
    """The whole of this build's contribution. Returns the report dict."""
    glsl = E._glsl_set(mod)

    # 1. the splice edit -- the one carrying query B's committed-T getter
    cand = [e for e in edits
            if any('OpRayQueryGetIntersectionTKHR' in l for l in e[1])]
    if len(cand) != 1:
        die(f"{mod.name}: expected exactly 1 splice edit carrying the "
            f"committed-T getter, found {len(cand)}")
    pos, ins = cand[0]

    tget = [i for i, l in enumerate(ins)
            if 'OpRayQueryGetIntersectionTKHR' in l]
    if len(tget) != 1:
        die(f"{mod.name}: {len(tget)} committed-T getters in the splice, want 1")
    tq = _res(ins[tget[0]])

    # 2. the guard: OpSelect(hitB, t, tmax). Located by its operand, never by
    #    position, so a patcher reorder cannot silently cap the wrong value.
    gsel = [i for i, l in enumerate(ins)
            if re.match(rf'\s*%\w+ = OpSelect %float %\w+ {tq} %\w+\s*$', l)]
    if len(gsel) != 1:
        die(f"{mod.name}: {len(gsel)} guards OpSelect(_, {tq}, _), want 1")
    gi = gsel[0]
    tu = _res(ins[gi])

    # 3. every consumer of the guarded t, classified. Nothing unclassified is
    #    tolerated: a half-capped transfer is worse than no cap.
    push, fmuls, other = [], [], []
    for i, l in enumerate(ins):
        if i == gi:
            continue
        # operands only: the result id is ops[0], and a line that merely
        # DEFINES something is not a consumer.
        # operands only: on a line that DEFINES a result the first token is
        # that result, not a use. On a line with no result (OpStore,
        # OpRayQueryInitializeKHR) every token is a use, so drop nothing --
        # dropping unconditionally would hide a first-operand consumer.
        toks = re.findall(r'%\w+', l)
        ops = toks[1:] if _res(l) else toks
        if tu not in ops:
            continue
        if re.match(rf'\s*%\w+ = OpFAdd %float {tu} %\w+\s*$', l):
            push.append(i)
        elif re.match(rf'\s*%\w+ = OpFMul %float {tu} %\w+\s*$', l):
            fmuls.append(i)
        else:
            other.append((i, l.strip()))
    if other:
        die(f"{mod.name}: unclassified consumer of the guarded t: {other[:3]}")
    if len(push) != 1:
        die(f"{mod.name}: {len(push)} pushes off the guarded t, want exactly 1 "
            f"(query C's origin)")
    if len(fmuls) not in (3, 6):
        die(f"{mod.name}: {len(fmuls)} transfer FMuls off the guarded t, "
            f"want 3 (single lobe) or 6 (dual lobe)")

    # each FMul must be the head of a  FMul -> FNegate -> Exp  chain
    for i in fmuls:
        r = _res(ins[i])
        neg = [j for j, l in enumerate(ins)
               if re.match(rf'\s*%\w+ = OpFNegate %float {r}\s*$', l)]
        if len(neg) != 1:
            die(f"{mod.name}: transfer FMul {r} does not feed exactly one "
                f"OpFNegate")
        nr = _res(ins[neg[0]])
        exp = [j for j, l in enumerate(ins)
               if re.match(rf'\s*%\w+ = OpExtInst %float %\w+ Exp {nr}\s*$', l)]
        if len(exp) != 1:
            die(f"{mod.name}: the negate of {r} does not feed exactly one Exp")

    if decoy == 'nocap':
        # The cap constant is emitted and the NMax is emitted, but nothing is
        # repointed -- i.e. the DEFAULT rung with dead code. Proves the
        # verifier checks the DATA FLOW and not the presence of an opcode.
        pass

    ind = re.match(r'(\s*)', ins[gi]).group(1)
    fcap = _fc(mod, consts, float(cap))
    teff = mod.new_id()
    op = 'NMin' if decoy == 'capmin' else 'NMax'
    ins.insert(gi + 1, f"{ind}{teff} = OpExtInst %float {glsl} {op} {tu} {fcap}")

    # 4. repoint. Indices below shift by one because of the insert above.
    def bump(xs):
        return [x + 1 if x > gi else x for x in xs]
    fmuls, push = bump(fmuls), bump(push)
    if decoy != 'nocap':
        for i in fmuls:
            ins[i] = re.sub(rf'(OpFMul %float ){tu}( )', rf'\g<1>{teff}\g<2>',
                            ins[i])
    if decoy == 'capray':
        # WRONG ON PURPOSE: the cap moves query C's origin too, i.e. the
        # visibility ray now starts somewhere the geometry is not.
        i = push[0]
        ins[i] = re.sub(rf'(OpFAdd %float ){tu}( )', rf'\g<1>{teff}\g<2>',
                        ins[i])

    return dict(cap_m=float(cap), op=op, t_guarded=tu, t_eff=teff,
                cap_const=fcap, capped_fmuls=len(fmuls),
                push_untouched=(decoy != 'capray'), decoy=decoy)


def build(mod, k, cap, mode='glow', soft=None, decoy=None):
    # The cap decoys are decoys of THIS build's one variable, so rq3 is always
    # asked for the honest rung underneath -- a cap decoy must fail on the cap
    # and not because the rq3 half was sabotaged too.
    consts, edits, rep = R3.build(mod, k, mode, soft, None)
    if cap:
        rep['earglow_cap'] = apply_cap(mod, consts, edits, cap, decoy)
    else:
        rep['earglow_cap'] = dict(cap_m=0.0, op=None,
                                  why='cap 0: the default rung, unmodified')
    return consts, edits, rep


def process(path, outdir, k, cap, mode='glow', soft=None, decoy=None,
            do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    if mode == 'glow' and k == 0.0 and decoy is None:
        rep['earglow_rq3'] = {"mode": "control", "k": 0.0, "emitted": 0,
                              "why": "k=0 glow: identity, no instructions"}
        rep['earglow_cap'] = dict(cap_m=0.0, op=None, why='control')
    else:
        consts, edits, r = build(mod, k, cap, mode, soft, decoy)
        rep['earglow_rq3'] = r
        rep['earglow_cap'] = r.pop('earglow_cap')
        apply_edits(mod, consts, edits)
        _add_header(mod)

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', spv_out],
                       capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--k', type=float, required=True)
    ap.add_argument('--cap', type=float, required=True,
                    help='thickness floor in METRES (0 = the default rung)')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--decoy', choices=DECOYS, default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow_cap.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if (a.wide is None) != (a.wrap is None):
        ap.error('--wide and --wrap must be given together')
    soft = (a.wide, a.wrap) if a.wide is not None else None
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.cap, a.mode, soft,
                             a.decoy, do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
