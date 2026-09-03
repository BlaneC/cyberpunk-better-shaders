#!/usr/bin/env python3
"""cfres -- REAL CONDUCTOR FRESNEL at the compute resolvers' direct-light
Schlick sites (handoff/108 sec 3).

    python3 dev/patch_cfres.py <mod.spvasm> --outdir DIR
            [--tint 0.5] [--metal-min 0.5] [--no-roundtrip-check]

WHAT IS WRONG WITH WHAT SHIPS
-----------------------------
Every direct-light resolver evaluates one Schlick Fresnel per specular lobe:

    form M   p = (1 - VoH)^5                          F_c = f0_c + (1-f0_c)*p
    form S   p = exp2((-6.98316002 - 5.55472994*VoH)*VoH)   F_c = f0_c*(1-p) + p

Both send EVERY channel to 1.0 as VoH -> 0, so copper, gold and chrome are the
same white at the silhouette.  Real conductors do not do that at the angles
that matter: they dip below Schlick around 80 deg, and they dip by DIFFERENT
amounts per channel.

WHAT IS SPLICED
---------------
Lazanyi & Szirmay-Kalos (2005) in Hoffman's F82-tint parameterisation
("Fresnel Equations Considered Harmful", MAM 2019), per channel:

    F'(c) = clamp( F_c - a_c * c * (1 - c)^6 , 0, 1 )        c = VoH
    a_c   = S_c * (1 - f82_c) / K
    S_c   = f0_c + (1 - f0_c) * (6/7)^5          Schlick at the F82 angle
    K     = (1/7) * (6/7)^6 = 0.05664904         max of c(1-c)^6, at c = 1/7
    f82_c = lerp(1, hue_c, tint)                 the EDGE TINT
    hue_c = (f0_c + 1e-4) / (max3(f0) + 1e-4)

then `replace_all_uses(F_c -> select(metallic > metal_min, F', F_c))`, which is
`patch_compute_skin.build_skin_spec`'s rewrite shape for its reason: it reaches
every consumer regardless of how the module assembles F*Vis*D, and it composes
with the parent rung's own class-1 Fresnel reshape instead of fighting it (the
two touch disjoint ids, and on a class-1 pixel the metal gate is false anyway).

dev/cfres_model.py is the closed form, the exact-conductor reference table and
the energy gate.  Read its "THE EDGE TINT" section before calling the mapping a
fit: it is ART DIRECTION.  The measured truth is that gold/copper/silver have a
true F82/Schlick ratio of 0.97-1.00 and the metals with a real Lazanyi dip
(iron 0.77, aluminium 0.88-0.93) dip ACHROMATICALLY -- and F0 alone cannot
predict either, which is exactly why Gulbrandsen and Hoffman keep the edge tint
as a free parameter.

WHY THIS IS NOT UPSTREAM OF FRESNEL
-----------------------------------
GOTCHAS, "splicing upstream of Fresnel means Fresnel weights your term too":
this splice IS the Fresnel.  It rewrites the uses of F_c, so the module's own
F*Vis*D assembly is untouched in shape and nothing is weighted twice.  The
correction carries a factor of c and a factor of (1-c), so it vanishes at both
VoH endpoints and cannot move normal-incidence colour.

ANCHORING (GOTCHAS 5 and 10)
----------------------------
* The Schlick groups come from `patch_compute_skin.find_spec_fresnel_groups`,
  IMPORTED, not copied -- one derivation of the two idioms in the repo.  It
  already rejects the Disney FD chain (whose "f0" is the constant 1.0).
* `metallic` is NOT guessed positionally.  Every group's own f0_c ids are
  matched, through OpPhi/OpSelect forwarding, against the module's own
  `F0 = lerp(0.04, albedo, metallic)` triples, and the group is patched only
  when all three channels resolve to ONE metallic id.  Measured on the
  standing base: 357 of 357 groups link, 0 ambiguous, 0 unresolved.
* The metallic a module COMPUTES is not always the one that DOMINATES the
  Schlick site: two modules fetch the material in a guarded block, so below
  the merge only the phi is live.  `dominating_metal` walks forward through
  merges whose other operands are a literal zero -- zero is not a metal, so a
  pixel that skipped the fetch gates OFF.  This is `80` sec 2.4's `lift_f0_phis`
  argument, and GOTCHAS' "the value a shader tests is not always the value the
  shader computed", applied to the gate.  64 of 357 groups need the lift; all
  64 are in the two modules `99` declines.
* Emission follows build_skin_spec's placement: the shared block at the FIRST
  channel's F line, the per-channel tail at each channel's own F line.  Checked
  on the standing base and asserted here per group: all three F defs live in
  ONE basic block, and every f0 / voh / pow5 the block reads is defined before
  the first F.

--tint 0 emits NOTHING -- no constants, no instructions, no rewrite -- so the
control rung is BYTE-IDENTICAL to the base (`27` sec 8.3 is the cautionary
tale about 48 bytes of unconsumed OpConstant).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die, replace_all_uses
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG
from patch_compute_brdf import detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import find_spec_fresnel_groups
import cfres_model as M

# The F0 = lerp(0.04, albedo, metallic) idiom, as `80` sec 2.4 reads it.
F0_LERP_C = '%float_0_0399999991'
F0_LERP_NC = '%float_n0_0399999991'

# Census of the standing base gi-50b-...-earglow-cap6-glintdense.  The build
# fails on any drift (GOTCHAS: "a byte diff is not coverage").
CENSUS = dict(modules=77, groups=357, chans=1071, form_m=301, form_s=56,
              metal_lifted=64)

# No module is declined by name.  Both of `99`'s KNOWN_DECLINE modules --
# ab0bc2fee876d489 (the v4uint reservoir pass, `46` sec 12) and
# 99bb7c2698997b2a (the big GI resolver) -- ARE patched here, on purpose: this
# feature needs no surface position, their Fresnel groups link exactly like
# every other module's, and a resolver whose Fresnel moved while the reservoir
# pass's target function did not would make ReSTIR reuse disagree with the
# shading it is reusing.
KNOWN_DECLINE = set()


def _def(mod, D, i):
    return D.get(i, (None, ''))[1]


def defs_index(mod):
    d = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*)$', ln)
        if m:
            d.setdefault(m.group(1), (i, m.group(2).strip()))
    return d


def find_f0_metal_triples(mod, D):
    """Every `F0 = lerp(0.04, albedo, metallic)` triple WITH its metallic id.

    Same shape `patch_subtype_probe.find_f0_triples` reads (the two 0.04
    constants of opposite sign, three consecutive channels sharing one
    metallic) -- re-derived here rather than imported because that function
    returns only the F0 channels and drops the metallic operand this gate
    needs.  The returned metallic is the operand the MODULE ITSELF multiplied,
    so the gate and the F0 it gates on are the same computation.
    """
    per = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpFAdd %float (%\d+) '
                     + re.escape(F0_LERP_C) + r'\s*$', ln)
        if not m:
            continue
        f0, y = m.groups()
        mm = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', _def(mod, D, y))
        if not mm:
            continue
        for z, mt in (mm.groups(), mm.groups()[::-1]):
            if re.match(r'OpFAdd %float (%\d+) ' + re.escape(F0_LERP_NC)
                        + r'\s*$', _def(mod, D, z)):
                per[i] = (f0, mt)
                break
    out, keys, i = [], sorted(per), 0
    while i < len(keys):
        a = keys[i]
        if (a + 1 in per and a + 2 in per
                and per[a][1] == per[a + 1][1] == per[a + 2][1]):
            out.append(dict(line=a + 2, f0=(per[a][0], per[a + 1][0],
                                            per[a + 2][0]), metal=per[a][1]))
            i += 3
            while i < len(keys) and keys[i] <= a + 2:
                i += 1
            continue
        i += 1
    return out


ZERO_TOKS = ('%float_0', '%float_n0')


def forward_closure(D, seeds, zero_only=False):
    """Ids reachable from `seeds` by walking OpPhi / OpSelect FORWARD.

    `80` sec 2.4 needed the same widening in the other direction: a module can
    compute F0 once in a guarded block and hand it to later sites through a
    phi at the merge, so the id a Schlick site multiplies is not always the id
    the lerp produced.  GOTCHAS, "the value a shader tests is not always the
    value the shader computed", is this exact failure with the arrow reversed:
    below the merge the raw value dominates nothing and the phi dominates
    everything.

    `zero_only=True` widens ONLY through merges whose other operands are a
    literal zero.  That is the guard `80` sec 2.4 states for the gate: zero is
    not a metal, so a pixel that took the path where the fetch was skipped
    reads 0 and gates OFF.  Without it a phi could mix in an unrelated float
    and the gate would fire on something that is not the metallic byte.
    """
    out = set(seeds)
    changed = True
    while changed:
        changed = False
        for i, (_l, t) in D.items():
            if i in out:
                continue
            m = re.match(r'OpPhi %float (.*)$', t)
            if m:
                ops = [o for o in m.group(1).split() if o.startswith('%')][::2]
                hit = any(o in out for o in ops)
                if hit and zero_only:
                    hit = all(o in out or o in ZERO_TOKS for o in ops)
                if hit:
                    out.add(i)
                    changed = True
                    continue
            m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', t)
            if m:
                ops = [m.group(2), m.group(3)]
                hit = any(o in out for o in ops)
                if hit and zero_only:
                    hit = all(o in out or o in ZERO_TOKS for o in ops)
                if hit:
                    out.add(i)
                    changed = True
    return out


def dominating_metal(mod, D, cfg, met, line):
    """The dominating FORM of `met` at `line`, or None.

    The raw id when it dominates; otherwise the zero-safe forwarded merge
    nearest above the site.  Both are the same value wherever the material
    fetch happened, and 0 elsewhere -- see forward_closure's `zero_only`.
    """
    if cfg.dominates_line(met, line) and D[met][0] < line:
        return met, False
    cand = [i for i in forward_closure(D, [met], zero_only=True)
            if D[i][0] < line and cfg.dominates_line(i, line)]
    if not cand:
        return None, False
    return max(cand, key=lambda i: D[i][0]), True


def link_groups_to_metal(mod, D, groups, trips):
    """{group index -> metallic id}, or None where the link is not single-valued."""
    per_chan = []
    for c in range(3):
        m = {}
        for t in trips:
            for i in forward_closure(D, [t['f0'][c]]):
                m.setdefault(i, set()).add(t['metal'])
        per_chan.append(m)
    out = {}
    for gi, g in enumerate(groups):
        mets = set()
        ok = len(g['chans']) == 3
        if ok:
            for c, ch in enumerate(g['chans']):
                hit = per_chan[c].get(ch['f0'])
                if not hit:
                    ok = False
                    break
                mets |= hit
        out[gi] = (list(mets)[0] if (ok and len(mets) == 1) else None)
    return out


def build_cfres(mod, cfg, knobs):
    """Emit the conductor Fresnel at every linked Schlick group."""
    consts, edits = [], []
    D = defs_index(mod)

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    gl = mod.glsl
    I = mod.new_id
    tint = knobs['tint']
    zero, one = C(0.0), C(1.0)
    eps = C(M.F0_EPS)
    invk = C(tint / M.K)                 # the tint folded into 1/K
    q = C(M.Q)                           # (6/7)^5
    omq = C(1.0 - M.Q)
    mmin = C(knobs['metal_min'])

    groups = find_spec_fresnel_groups(mod)
    trips = find_f0_metal_triples(mod, D)
    link = link_groups_to_metal(mod, D, groups, trips)

    rep = dict(tint=tint, metal_min=knobs['metal_min'], groups=0, chans=0,
               form_m=0, form_s=0, triples=len(trips),
               metal_ids=sorted({m for m in link.values() if m}),
               metal_lifted=0,
               seen_groups=len(groups), skipped_link=[], skipped_dom=[],
               skipped_block=[], skipped_shape=[])

    for gi, g in enumerate(groups):
        chans = g['chans']
        first_line = min(mod.find_def(c['F'])[0] for c in chans)
        met = link[gi]
        if met is None:
            rep['skipped_link'].append(g['pow5'])
            continue
        if len(chans) != 3:
            rep['skipped_shape'].append(g['pow5'])
            continue
        # every F of the group in ONE basic block: the shared block is emitted
        # with the first channel and read by the other two.
        blocks = {id(cfg.block_of(mod.find_def(c['F'])[0])) for c in chans}
        if len(blocks) != 1:
            rep['skipped_block'].append(g['pow5'])
            continue
        met, lifted = dominating_metal(mod, D, cfg, met, first_line)
        if met is None:
            rep['skipped_dom'].append(g['pow5'])
            continue
        if lifted:
            rep['metal_lifted'] += 1
        reads = [met, g['voh'], g['pow5']] + [c['f0'] for c in chans]
        if any(not cfg.dominates_line(r, first_line) for r in reads):
            rep['skipped_dom'].append(g['pow5'])
            continue
        if any(mod.find_def(r)[0] is not None
               and mod.find_def(r)[0] >= first_line for r in reads):
            rep['skipped_dom'].append(g['pow5'])
            continue

        # ---- shared, at the first channel's F line ----------------------
        cs, om, t0, gg, gk = I(), I(), I(), I(), I()
        m1, m2, den, inv, gate = I(), I(), I(), I(), I()
        shared = [
            f"        {cs} = OpExtInst %float {gl} NClamp {g['voh']} {zero} {one}",
            f"        {om} = OpFSub %float {one} {cs}",
            f"        {t0} = OpFMul %float {cs} {om}",
            f"        {gg} = OpFMul %float {t0} {g['pow5']}",
            f"        {gk} = OpFMul %float {gg} {invk}",
            f"        {m1} = OpExtInst %float {gl} NMax {chans[0]['f0']} {chans[1]['f0']}",
            f"        {m2} = OpExtInst %float {gl} NMax {m1} {chans[2]['f0']}",
            f"        {den} = OpFAdd %float {m2} {eps}",
            f"        {inv} = OpFDiv %float {one} {den}",
            f"        {gate} = OpFOrdGreaterThan %bool {met} {mmin}",
        ]
        rep['form_s' if chans[0]['X'] is None else 'form_m'] += 1
        first = True
        for c in chans:
            fline, _ = mod.find_def(c['F'])
            pins = list(shared) if first else []
            first = False
            nu, h, u, S, a, corr, fp, fc, sel = (I() for _ in range(9))
            pins += [
                f"        {nu} = OpFAdd %float {c['f0']} {eps}",
                f"        {h} = OpFMul %float {nu} {inv}",
                f"        {u} = OpFSub %float {one} {h}",
                f"        {S} = OpExtInst %float {gl} Fma {c['f0']} {omq} {q}",
                f"        {a} = OpFMul %float {S} {u}",
                f"        {corr} = OpFMul %float {a} {gk}",
                f"        {fp} = OpFSub %float {c['F']} {corr}",
                # Physically F <= Schlick <= 1 here (a >= 0 and c(1-c)^6 >= 0),
                # so only the floor can bite -- and dev/cfres_model.py --gate
                # measures exactly when: never below -7.7e-4 at tint 0.5,
                # -0.13 at tint 1.0 on the most saturated channels.  NClamp
                # costs one instruction and removes the question.
                f"        {fc} = OpExtInst %float {gl} NClamp {fp} {zero} {one}",
                f"        {sel} = OpSelect %float {gate} {fc} {c['F']}",
            ]
            edits.append((fline, pins))
            replace_all_uses(mod, c['F'], sel, fline)
            rep['chans'] += 1
        rep['groups'] += 1
    if rep['groups'] == 0:
        die(f"{mod.name}: no conductor Fresnel site spliced")
    return consts, edits, rep


def process(path, outdir, knobs, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    if knobs['tint'] == 0.0:
        # THE CONTROL.  Nothing emitted, nothing rewritten; the module is
        # re-assembled from the untouched disassembly, which the build proves
        # is byte-neutral on all 77 base modules FIRST.
        rep['cfres'] = dict(tint=0.0, control=True, groups=0, chans=0,
                            form_m=0, form_s=0, skipped_link=[],
                            skipped_dom=[], skipped_block=[], skipped_shape=[])
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    consts, edits, rep['cfres'] = build_cfres(mod, cfg, knobs)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--tint', type=float, default=0.5,
                    help='edge-tint strength; 0 = the byte-identical control')
    ap.add_argument('--metal-min', type=float, default=0.5,
                    help='metallic gate; below it the module keeps Schlick')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if not (0.0 <= a.tint <= 1.0):
        die('--tint must be in [0, 1]')
    knobs = dict(tint=a.tint, metal_min=a.metal_min)
    reps = [process(p, a.outdir, knobs, do_rt=not a.no_roundtrip_check)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
