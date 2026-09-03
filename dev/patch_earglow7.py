#!/usr/bin/env python3
"""patch_earglow7.py <base.spvasm> --outdir DIR --model rates.json [...]

earglow7 -- the ear glow's TRANSMITTANCE, replaced with skin's.  handoff/111.

THE ASK, verbatim:

    "Mind tweaking the earglow to actually reduce the luminance of the sun and
     tweak the hue of the light based on the actual transmittance of skin?"
    "I need the default values we had before baked into
     gi-50b-...-earglow-cap6-glintdense-curv, but just with better
     transmittance"

So: NO cutoff, NO fade, the floor left where `101` sec 18 put it, the three
ray queries untouched, and every edit inside the TRANSFER.  110's v5/v6
families are not built on and not stacked -- this rung starts from the
standing default and rewrites what the light does on its way through flesh.

WHAT THE DEFAULT COMPUTES, read back out of its own .spv:

    t_eff = NMax(t_B, 6 mm)                         <- untouched here
    T_c   = 0.5*(exp(-t_eff/ld_c) + exp(-t_eff/(4 ld_c)))
    W     = k * SmoothStep(0, 0.35, -N.S)           <- k = 0.22
    add_c = NMin(T_c * W * sunRadiance_c, 100)

FOUR THINGS ARE WRONG WITH THAT AS RADIOMETRY, and dev/transmit_model.py
quantifies all four from published tissue optics (Prahl's haemoglobin table,
Jacques' skin fits).  The exit radiance of a diffusing slab lit from behind is

    L_c  =  S_c * cos(theta_entry) * T_c(d) / pi

  (i) `SmoothStep(0, 0.35, -N.S)` SATURATES AT 1 for every cos >= 0.35, so
      the sun's flux is taken at FULL STRENGTH over almost the whole pinna.
      The real factor is cos itself: 2.9x less at the knee, and less still
      below it.  This is the "reduce the luminance of the sun" half, and it
      is one operand repointed plus one NMax.
 (ii) ld = (3.67, 1.37, 0.68) mm are Jensen skin1's DIFFUSION LENGTHS at
      600/550/450 nm.  A renderer's R channel is 120 nm wide and skin's
      mu_eff falls fivefold across it, so what survives 6 mm of flesh is the
      660-700 nm tail, not "600 nm light".  Integrating the real spectrum
      over the real channel sensitivity gives an effective red ld of
      1.55 mm -- 2.4x shorter -- and that number is stable to +-2% across
      every plausible blood and melanin fraction.
(iii) the two lobes are pinned at ld and 4*ld, which is a smoothing choice,
      not a measurement.  Fitted freely they carry the spectral sharpening
      that makes the emergent light redder with depth.
 (iv) there is no per-channel amplitude, so green and blue are held at 26%
      and 8% of red at the floor (R/G 2.48).  The measured figure is R/G
      30-70.  THAT is the "too yellow", and the fix is exactly 110 sec 4's
      tint machinery carrying FITTED amplitudes instead of chosen ones.

THE EDIT, per module:

    k                 in-place rewrite   0.22 -> --k         (a normalisation:
                                                              see --model)
    six rate consts   in-place rewrites  1/ld, 1/(4 ld) -> the fitted a1, a2
    tint G, B         2 instructions     half_c * tint_c, operand repointed
    angular factor    1 instruction      w = NMax(-N.S, 0), operand repointed
                                         (the smoothstep is left in place and
                                          becomes dead code)

    +3 instructions, 7 constant rewrites, 0 declarations in the default rung.
    UNTOUCHED: all three ray queries, flags 545/517/517, tmin 1.5 mm, tmax
    18 mm, the +-0.1% bracket, the instance match, query C, the 6 mm floor,
    the firefly clamp, the write shape, and all 81 non-reference modules.

An in-place rewrite is only taken after patch_earglow5.rewrite_const() proves
the earglow sites are the constant's ONLY consumers.

    ./dev/build_earglow7.sh                      # all rungs + gates
    python3 dev/transmit_model.py --emit r.json  # the rates come from here
    python3 dev/patch_earglow7.py <in.spvasm> --outdir <dir> --model r.json

NOT EDITED BY THIS FILE, only imported: dev/patch_earglow5.py,
dev/patch_earglow.py, dev/patch_earglow_rq.py, dev/patch_rayq.py.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
import patch_earglow as E
from patch_earglow_rq import _ensure_line
from patch_rayq import _add_header
# find_glow re-finds 101 sec 16's block by SHAPE and asserts the shipped
# constants (k 0.22, tmax 18 mm, floor 6 mm, the six Jensen rates), so it is
# also this file's proof that the base is the untouched standing default.
from patch_earglow5 import (find_glow, rewrite_const, set_floor, f32, flit,
                            fval_of, close, uses_of, _fc, CAP6, K_OLD,
                            TMAX_OLD, LD_OLD, WIDE, FLAGS_B)

WRAP_KNEE = 0.349999994          # the shipped smoothstep's upper edge
DECOYS = ('flatk', 'flatrate', 'notint', 'tintswap', 'rateswap',
          'cosraw', 'cosdot', 'cosboth', 'wide4')
ANGULAR = ('cos', 'smoothstep')


def find_angular(mod, g, fs, fe):
    """The shipped weight's angular half, by shape:

        dot   = OpDot(N, S)          N = the module's own primary normal
        cos   = OpFNegate dot        so cos = -N.S, positive when backlit
        wrap  = SmoothStep(-0, 0.35, cos)
        w0    = OpFMul(k select, wrap)

    Everything is anchored on `find_glow`'s own `wrap` id, so no SSA name is
    assumed and a module that computed the envelope some other way dies here
    instead of being silently repointed onto the wrong value."""
    d = g['index']
    w = d.get(g['wrap'], (0, ''))[1]
    m = re.match(r'OpExtInst %float %\w+ SmoothStep (%\w+) (%\w+) (%\w+)$', w)
    if not m:
        die(f"{mod.name}: the wrap is not a 3-operand SmoothStep ({w!r})")
    lo, hi, cos = m.groups()
    if not close(fval_of(mod, lo) or 0.0, 0.0, 1e-6):
        die(f"{mod.name}: the wrap's lower edge is {fval_of(mod, lo)}, want 0")
    if not close(fval_of(mod, hi), WRAP_KNEE, 1e-5):
        die(f"{mod.name}: the wrap's knee is {fval_of(mod, hi)}, want "
            f"{WRAP_KNEE}")
    neg = d.get(cos, (0, ''))[1]
    nm = re.match(r'OpFNegate %float (%\w+)$', neg)
    if not nm:
        die(f"{mod.name}: the wrap's argument is not an OpFNegate ({neg!r}) "
            f"-- the sign of the cosine cannot be established")
    dot = nm.group(1)
    if not re.match(r'OpDot %float %\w+ %\w+$', d.get(dot, (0, ''))[1]):
        die(f"{mod.name}: {cos} negates {dot}, which is not an OpDot "
            f"({d.get(dot, (0, ''))[1]!r})")
    # the wrap must feed the shared weight and NOTHING else, or repointing it
    # would leave a second consumer reading the saturating envelope
    users = [i for i in uses_of(mod, g['wrap'], fs, fe)
             if i != d[g['wrap']][0]]
    if users != [d[g['w0']][0]]:
        die(f"{mod.name}: the wrap is read at lines {[i+1 for i in users]}, "
            f"want only the shared weight at {d[g['w0']][0]+1}")
    return dict(lo=lo, hi=hi, cos=cos, dot=dot)


def set_angular(mod, g, ang, mode, decoy, fs, fe, rep, consts):
    """Replace the saturating envelope with the entry-face Lambert factor.

    w = NMax(cos, 0).  The NMax is not decoration: the gate's backlit arm is
    computed from the module's own (possibly cone-jittered) sun vector, so a
    pixel can be accepted with cos a hair below zero, and a NEGATIVE weight
    would SUBTRACT light -- a dark rim exactly where the effect should fade
    in.  `--decoy cosraw` builds that and the verifier rejects it."""
    d = g['index']
    if mode == 'smoothstep' and not decoy:
        rep['angular'] = {'factor': 'SmoothStep(0, 0.35, -N.S)',
                          'source': 'the shipped default, untouched',
                          'instructions': 0}
        return
    glsl = E._glsl_set(mod)
    site = d[g['wrap']][0]
    ind = re.match(r'(\s*)', mod.lines[site]).group(1)
    src = ang['dot'] if decoy == 'cosdot' else ang['cos']
    ins, new = [], None
    if decoy == 'cosraw':
        new = src                                   # no clamp at all
    else:
        fzero = _ensure_line(mod, consts,
                             r'\s*(%\w+)\s*=\s*OpConstant %float 0\s*$',
                             lambda n: f"    {n} = OpConstant %float 0")
        new = mod.new_id()
        ins.append(f"{ind}{new} = OpExtInst %float {glsl} NMax {src} {fzero}")
    if decoy == 'cosboth':
        both = mod.new_id()
        ins.append(f"{ind}{both} = OpFMul %float {new} {g['wrap']}")
        new = both
    if ins:
        edits = [(site, ins)]
    else:
        edits = []
    wl = d[g['w0']][0]
    before = mod.lines[wl]
    mod.lines[wl] = re.sub(r'(?<![\w])' + re.escape(g['wrap']) + r'(?![\w])',
                           new, before)
    if mod.lines[wl] == before:
        die(f"{mod.name}: could not repoint the shared weight ({before!r})")
    rep['angular'] = {
        'factor': 'NMax(-N.S, 0)' if not decoy else f'DECOY {decoy}',
        'source': 'repointed off the saturating SmoothStep',
        'smoothstep_left_dead': decoy != 'cosboth',
        'instructions': len(ins)}
    return edits


def build(mod, rates, tint, k, floor, angular, decoy, fs, fe):
    g = find_glow(mod, fs, fe)
    ang = find_angular(mod, g, fs, fe)
    d = g['index']
    consts, edits = [], []
    rep = {'k': f32(k), 'floor_m': f32(floor), 'decoy': decoy,
           'angular_mode': angular, 'flags_b': FLAGS_B,
           'cutoff': None, 'fade': None,
           'query_touched': 'nothing',
           'tmax_m': fval_of(mod, g['tmax']),
           'ld_old_m': list(LD_OLD), 'wide_old': WIDE,
           'rates_1_per_m': [list(r) for r in rates],
           'ld_new_m': [[1.0 / r[0], 1.0 / r[1]] for r in rates],
           'tint': [f32(x) for x in tint]}

    # ---- the level: k is a NORMALISATION here, not a brightness knob ------
    if decoy != 'flatk':
        rewrite_const(mod, g['k_tok'], k, fs, fe, rep, 'k (normalisation)',
                      [d[g['ksel']][0]])
    rep['k_applied'] = decoy != 'flatk'

    # ---- the floor: untouched unless a -floor rung asks -------------------
    if not close(floor, CAP6, 1e-9):
        set_floor(mod, g, floor, fs, fe, rep, consts, None)
        rep['floor_source'] = 'repointed (new constant, 0 instructions)'
    else:
        rep['floor_source'] = 'untouched (101 sec 18)'

    # ---- the depth shape: six rates, all in place ------------------------
    if decoy != 'flatrate':
        order = [2, 1, 0] if decoy == 'rateswap' else [0, 1, 2]
        for c, ch in enumerate(g['chains']):
            a1, a2 = rates[order[c]]
            if decoy == 'wide4':
                a2 = a1 / WIDE          # the pinned lobe, kept on purpose
            for tok, val, lbl in ((ch['tok_narrow'], a1, 'narrow'),
                                  (ch['tok_wide'], a2, 'wide')):
                sites = [d[x][0] for x in d
                         if re.match(r'OpFMul %float ', d[x][1] or '')
                         and tok in (d[x][1] or '').split()]
                rewrite_const(mod, tok, val, fs, fe, rep,
                              f'rate chan {c} ({lbl} lobe)', sites)
    rep['rates_applied'] = decoy != 'flatrate'

    # ---- the hue: the fitted per-channel amplitude, as 110 sec 4's tint --
    tt = list(tint)
    if decoy == 'notint':
        tt = [1.0, 1.0, 1.0]
    elif decoy == 'tintswap':
        tt = [tint[2], tint[1], tint[0]]
    rep['tint_applied'] = [f32(x) for x in tt]
    for c, ch in enumerate(g['chains']):
        if f32(tt[c]) == 1.0:
            continue                    # red: the amplitude is folded into k
        ft = _fc(mod, consts, tt[c])
        ind = re.match(r'(\s*)', mod.lines[d[ch['half']][0]]).group(1)
        t = mod.new_id()
        edits.append((d[ch['half']][0],
                      [f"{ind}{t} = OpFMul %float {ch['half']} {ft}"]))
        ml = d[ch['mul_w']][0]
        mod.lines[ml] = re.sub(
            r'(?<![\w])' + re.escape(ch['half']) + r'(?![\w])', t,
            mod.lines[ml])

    # ---- the angular factor ---------------------------------------------
    edits += set_angular(mod, g, ang, angular, decoy, fs, fe, rep, consts) or []

    rep['added_instructions'] = sum(len(e[1]) for e in edits)
    rep['new_constants'] = len(consts)
    return consts, edits, rep


def load_model(path):
    m = json.load(open(path))
    rates = [tuple(r) for r in m['rates_1_per_m']]
    tint = list(m['tint'])
    if len(rates) != 3 or len(tint) != 3:
        die(f"{path}: want three rate pairs and three tints")
    if not close(tint[0], 1.0, 1e-9):
        die(f"{path}: tint[R] is {tint[0]}, want exactly 1 -- red's amplitude "
            f"belongs in k, or the normalisation is double-counted")
    for a1, a2 in rates:
        if not a1 > a2 > 0:
            die(f"{path}: rate pair ({a1}, {a2}) is not a1 > a2 > 0")
    return rates, tint, float(m['k']), m


def process(path, outdir, rates, tint, k, floor, angular, decoy, do_rt=True,
            control=False, model=None):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    if control:
        # THE CONTROL.  Nothing is emitted, so the bytes ARE the base's --
        # but the base is still asserted to be the one this rung claims.
        g = find_glow(mod, fs, fe)
        find_angular(mod, g, fs, fe)
        rep['earglow7'] = {'mode': 'control', 'emitted': 0,
                           'why': 'rates, tint, k, floor and angular all '
                                  'unchanged'}
    else:
        consts, edits, rep['earglow7'] = build(mod, rates, tint, k, floor,
                                               angular, decoy, fs, fe)
        rep['earglow7']['model'] = {kk: model[kk] for kk in
                                    ('layer_mode', 'f_mel', 'so2', 'f_blood',
                                     'fit_range_m', 'ref_m')} if model else None
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
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--model', help='dev/transmit_model.py --emit output: the '
                                    'fitted rates, tint and k')
    ap.add_argument('--k', type=float, default=None,
                    help="override the model's k")
    ap.add_argument('--tint', default=None, help='override as R,G,B')
    ap.add_argument('--rates', default=None,
                    help='override as a1,a2:a1,a2:a1,a2 in 1/m')
    ap.add_argument('--floor', type=float, default=CAP6,
                    help='101 sec 18 thickness floor in METRES (default '
                         '0.006 = untouched)')
    ap.add_argument('--angular', default='cos', choices=ANGULAR,
                    help='cos: w = NMax(-N.S, 0), the entry-face Lambert '
                         'factor. smoothstep: leave the shipped saturating '
                         'envelope alone.')
    ap.add_argument('--control', action='store_true',
                    help='emit the base unchanged, but still assert it is the '
                         'base this rung claims')
    ap.add_argument('--decoy', choices=DECOYS, default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow7.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()

    rates = tint = None
    k = a.k
    model = None
    if a.model:
        rates, tint, mk, model = load_model(a.model)
        if k is None:
            k = mk
    if a.rates:
        rates = [tuple(float(x) for x in p.split(','))
                 for p in a.rates.split(':')]
    if a.tint:
        tint = [float(x) for x in a.tint.split(',')]
    if not a.control and (rates is None or tint is None or k is None):
        die("need --model (or --rates/--tint/--k) unless --control")
    print(json.dumps(process(a.spvasm, a.outdir, rates, tint, k, a.floor,
                             a.angular, a.decoy,
                             do_rt=not a.no_roundtrip_check,
                             control=a.control, model=model)))


if __name__ == '__main__':
    main()
