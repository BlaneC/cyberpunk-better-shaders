#!/usr/bin/env python3
"""hunt-wpos: paint the resolvers' own surface position P on screen, so the
SPACE it lives in can be read off one frame (handoff/99).

WHY THIS EXISTS
---------------
Every direct-light resolver computes NoV, so a view vector exists, so a
surface position exists.  `dev/hunt_wpos.py` finds it in 75 of the 77 compute
modules of the standing rung, always the same shape and always the same CBV
members:

    P = (cbv[reg0+12][69..72] . (pixel.x, pixel.y, depth, 1)) / w
    V = normalize(cbv[reg0+12][0].xyz - P)

and 308 of 308 dot-shaped 1e-5-clamped NoV sites in those modules are built
from that P.  What the bytes CANNOT say is which space it is: **every one of
the 1413 consumers of P in the whole set is a subtraction** -- the camera
position (75 triples) and the light-list positions (132 triples) -- and a
difference of positions is invariant to translating the space.  There is no
world-space hash, no reservoir store, no `P + cbv[k]` anywhere: 0 of 75
modules add anything to P.  So this probe measures it instead.

THE PAIR
--------
  hunt-wpos       the pattern on P as the module computes it.
  hunt-wpos-cam   the pattern on `P - C`, C = the camera position the module
                  already loads to build V.  CAMERA-RELATIVE BY CONSTRUCTION.

If P is world space, `-wpos` is welded to the world and `-cam` slides with the
camera.  If P is camera-relative, then C must be identically zero for V to be
correct, and the two rungs are pixel-identical.  That is the whole experiment
and it is decidable from two screenshots.

  hunt-wpos-frac  RGB = frac(P / cell) -- reads the UP AXIS and the UNITS off
                  a single frame: on flat ground the up channel is constant
                  across the whole road while the other two run sawtooth
                  stripes whose period measures the cell size.
  hunt-wpos-ctl   --gain 0: emits nothing, rebuilds byte-identical.

PATTERN (class 0 only; classes 1/3/4/5 keep 94's hunt palette VERBATIM, so
skin is red and hair yellow and the void condition of 94 sec 15 is the same
test in this frame too):

  hash mode   q = floor(P/cell); h = spatial hash of q; RGB multiplier from
              three bytes of h, times a `stripe` dim factor on odd cells of
              the up axis, so a wall shows 1 m horizontal banding and the
              ground does not -- the up axis reads off the screenshot.
  frac mode   RGB multiplier = lo + (hi-lo) * frac(P/cell) per axis.

The paint is a MULTIPLY on the radiance texel, exactly as `94`'s hunt-paint,
so the frame stays recognisable (40 sec 3).

Usage:
    python3 dev/patch_wpos.py <mod.spvasm> --outdir DIR [--gain 1.0]
        [--mode hash|frac] [--space world|cam] [--cell 1.0] [--up 2]
        [--no-stripe]
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
from patch_hunt_paint import CLASS_TINT, UNKNOWN_TINT
import wpos_core as W

# Declines, BY NAME.  A decline anywhere else is a coverage failure.
#   ab0bc2fee876d489 -- its one OpImageWrite has an OpBitcast %v4int texel:
#                       an integer buffer, not radiance (94 sec 9.2).
#   99bb7c2698997b2a -- the big GI resolver.  It computes no view vector
#                       (97 sec 1.5) and hunt_wpos finds no position chain in
#                       it, so there is no P to paint.  Its one radiance write
#                       is left vanilla.
KNOWN_DECLINE = {'ab0bc2fee876d489', '99bb7c2698997b2a'}

# Census of the standing base (gi-50b-...-cone2all-fog, whose 77 compute
# modules are byte-identical to -cone2all).  build_wpos.sh fails on any drift.
CENSUS = dict(modules=77, painted_modules=75, writes=150,
              top_level=120, refetched=30)

DEFAULTS = dict(cell=1.0, lo=0.15, hi=3.00, stripe=0.35, up=2)

# Teschner et al. spatial hash multipliers, then an xorshift avalanche.
HASH_K = (73856093, 19349663, 83492791)
AVAL_M = 668265261            # 0x27d4eb2d
BIAS = 65536.0                # so ConvertFToU sees a non-negative float


def build_wpos_writes(mod, cfg, writes, gain, knobs, mode, space):
    consts, edits = [], []
    uc = {}

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def U(n):
        key = ('u', int(n))
        if key in uc:
            return uc[key]
        nid, c = mod.uconst(n)
        if c:
            consts.append(c)
        uc[key] = nid
        return nid

    uc['decls'] = consts            # emit_world_pos appends its uints here

    def g(x):
        """gain lerps each endpoint from vanilla (1.0) toward the palette."""
        return 1.0 + gain * (x - 1.0)

    lo, hi = g(knobs['lo']), g(knobs['hi'])
    stripe = g(knobs['stripe'])
    one = C(1.0)
    c_lo, c_span = C(lo), C(hi - lo)
    c_stripe = C(stripe)
    c_inv = C(1.0 / knobs['cell'])
    c_bias = C(BIAS)
    c_255 = C(1.0 / 255.0)
    cls_ids = {n: U(n) for n in list(CLASS_TINT) + [0]}
    cls_rgb = {n: [C(g(x)) for x in CLASS_TINT[n][1]] for n in CLASS_TINT}
    unk_rgb = [C(g(x)) for x in UNKNOWN_TINT[1]]

    ctx = W.find_pos_chain(mod)
    if ctx is None:
        die(f"{mod.name}: no P = M.(x,y,depth,1)/w reconstruction")
    cam = W.find_campos(mod, ctx)
    if cam is None:
        die(f"{mod.name}: no camera position (C - P) triple")
    leaves = W.pos_leaves(ctx)

    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((ins_line, pre_ins))
    cf = None
    glsl = mod.glsl
    done, refetched, skipped = [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float construct'})
            continue
        ins = []
        cls = shift
        p_top = all(cfg.dominates_line(i, w['line']) for i in ctx['p'])
        c_top = cfg.dominates_line(dom_id, w['line'])
        if not c_top:
            if cf is None:
                cf = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line']) for x in class_fetch_inputs(cf)):
                skipped.append({'line': w['line'] + 1, 'why': 'class refetch inputs do not dominate'})
                continue
            cls = emit_class_value(mod, cf, ins)
        if not p_top:
            if any(not cfg.dominates_line(x, w['line']) for x in leaves):
                skipped.append({'line': w['line'] + 1, 'why': 'position refetch inputs do not dominate'})
                continue
        if space == 'cam' and not p_top \
           and any(not cfg.dominates_line(x, w['line']) for x in [ctx['cbv']]):
            skipped.append({'line': w['line'] + 1, 'why': 'cbv base does not dominate'})
            continue
        pos = W.emit_world_pos(mod, cfg, ctx, w['line'], ins, uc=uc,
                               relative_to_camera=(space == 'cam'), cam=cam)
        if not p_top:
            refetched.append(w['line'] + 1)

        I = mod.new_id

        def E(op, ty, *a):
            i = I()
            ins.append(f"        {i} = {op} {ty} " + ' '.join(a))
            return i

        # ---- the pattern, in the module's own float32 -----------------
        cell = [E('OpFMul', '%float', pos[k], c_inv) for k in range(3)]
        if mode == 'frac':
            t = [E('OpExtInst', '%float', glsl, 'Fract', cell[k]) for k in range(3)]
            rgb = [E('OpExtInst', '%float', glsl, 'Fma', c_span, t[k], c_lo)
                   for k in range(3)]
        else:
            q = [E('OpExtInst', '%float', glsl, 'Floor', cell[k]) for k in range(3)]
            qb = [E('OpFAdd', '%float', q[k], c_bias) for k in range(3)]
            n = [E('OpConvertFToU', '%uint', qb[k]) for k in range(3)]
            mul = [E('OpIMul', '%uint', n[k], U(HASH_K[k])) for k in range(3)]
            x1 = E('OpBitwiseXor', '%uint', mul[0], mul[1])
            h = E('OpBitwiseXor', '%uint', x1, mul[2])
            s1 = E('OpShiftRightLogical', '%uint', h, U(15))
            h1 = E('OpBitwiseXor', '%uint', h, s1)
            h2 = E('OpIMul', '%uint', h1, U(AVAL_M))
            s2 = E('OpShiftRightLogical', '%uint', h2, U(15))
            h3 = E('OpBitwiseXor', '%uint', h2, s2)
            rgb = []
            for k in range(3):
                sh = h3 if k == 0 else E('OpShiftRightLogical', '%uint', h3, U(8 * k))
                by = E('OpBitwiseAnd', '%uint', sh, U(255))
                bf = E('OpConvertUToF', '%float', by)
                t = E('OpFMul', '%float', bf, c_255)
                rgb.append(E('OpExtInst', '%float', glsl, 'Fma', c_span, t, c_lo))
            if knobs['stripe_on']:
                odd = E('OpBitwiseAnd', '%uint', n[knobs['up']], U(1))
                even = I()
                ins.append(f"        {even} = OpIEqual %bool {odd} {U(0)}")
                sel = I()
                ins.append(f"        {sel} = OpSelect %float {even} {one} {c_stripe}")
                rgb = [E('OpFMul', '%float', rgb[k], sel) for k in range(3)]

        # ---- the gates: class 0 gets the pattern, 94's palette otherwise
        def N(op, *a):
            i = I()
            ins.append(f"        {i} = {op} %bool " + ' '.join(a))
            return i

        gate = {n: N('OpIEqual', cls, cls_ids[n]) for n in [0] + list(CLASS_TINT)}
        known = gate[0]
        for n in CLASS_TINT:
            known = N('OpLogicalOr', known, gate[n])
        g_unk = N('OpLogicalNot', known)

        gates = [(gate[0], rgb)]
        for n in sorted(CLASS_TINT):
            gates.append((gate[n], cls_rgb[n]))
        gates.append((g_unk, unk_rgb))

        newc = []
        for ch in range(3):
            cur = one
            for gt, col in gates:
                s = I()
                ins.append(f"        {s} = OpSelect %float {gt} {col[ch]} {cur}")
                cur = s
            newc.append(E('OpFMul', '%float', w['comps'][ch], cur))
        nt = I()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                      r'\g<1>' + nt, mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die(f"{mod.name}: no radiance image write reachable for the paint")
    return consts, edits, {
        'gain': gain, 'mode': mode, 'space': space, 'knobs': dict(knobs),
        'endpoints': {'lo': lo, 'hi': hi, 'stripe': stripe},
        'p': list(ctx['p']), 'matrix': {'cbv': ctx['cbv'], 'members': ctx['mat']},
        'cbv_slot': ctx['cbv_slot'], 'depth_slot': ctx['img_slot'],
        'campos_member': cam['member'], 'class_anchor': dom_id,
        'writes': done, 'refetched': refetched, 'skipped': skipped}


def process(path, outdir, gain, knobs, mode, space, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    if gain == 0.0:
        # THE CONTROL. Nothing emitted, nothing rewritten -- the module is
        # re-assembled from the untouched disassembly, which build_wpos.sh
        # proves is byte-neutral on all 77 base modules FIRST.
        rep['wpos'] = {'gain': 0.0, 'control': True, 'writes': [],
                       'refetched': [], 'skipped': []}
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    writes = find_image_writes(mod)
    consts, edits, rep['wpos'] = build_wpos_writes(
        mod, cfg, writes, gain, knobs, mode, space)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--gain', type=float, default=1.0,
                    help='0 = the byte-identical control (emits nothing)')
    ap.add_argument('--mode', choices=('hash', 'frac'), default='hash')
    ap.add_argument('--space', choices=('world', 'cam'), default='world',
                    help="'cam' paints P - C, camera-relative BY CONSTRUCTION")
    ap.add_argument('--cell', type=float, default=DEFAULTS['cell'])
    ap.add_argument('--up', type=int, choices=(0, 1, 2), default=DEFAULTS['up'])
    ap.add_argument('--no-stripe', action='store_true',
                    help='drop the up-axis banding -- the decoy the verifier '
                         'must reject')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    knobs = dict(DEFAULTS)
    knobs.update(cell=a.cell, up=a.up, stripe_on=not a.no_stripe)
    if a.cell <= 0:
        die('--cell must be > 0')
    reps = [process(p, a.outdir, a.gain, knobs, a.mode, a.space,
                    do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
