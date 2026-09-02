#!/usr/bin/env python3
"""hunt-paint: one-frame material probe for the car-paint gate (handoff/94).

94 sec 1 established that the 3-bit material class has only FIVE populated
values in the whole 3290-module dump -- 0 (default/Standard), 1 (skin), 3 (a
10-bit octahedral normal DECODE switch, not a shading family), 4 (hair),
5 (vegetation) -- and that no clearcoat lobe exists anywhere in the renderer.
So vehicle body paint is not a class and not a subtype: it is class 0 with a
metallic/roughness signature, and the gate the coat must use is
`metallic x roughness`, not a class compare.

This patcher paints that hypothesis onto one frame. At every radiance
OpImageWrite in the 77 compute (resolve) modules -- the family that OWNS the
primary hit's direct light (94 sec 2, site C) -- the texel RGB is multiplied
by a tint chosen by:

  * the material class, for the four populated non-zero classes; skin (1) is
    RED, which is the SAME colour the known-good class hunt used
    (patch_skin_brdf.HUNT_PALETTE), so V's face/hands are a BUILT-IN CONTROL:
    if skin is not red, the probe did not run and no other read-out counts.
  * for class 0, a metallic x roughness BUCKET. The bucket the car body
    lands in is the answer: it names the (m, r) window the coat must gate on.

Any class outside {0,1,3,4,5} paints BLACK -- an unmissable hole, and a
headline finding, because the census says it cannot happen.

Colour legend (--gain 1.0):

  class 1  skin          red      (3.00, 0.15, 0.15)   <- CONTROL
  class 3  normal-decode blue     (0.15, 0.15, 3.00)
  class 4  hair          yellow   (3.00, 3.00, 0.15)
  class 5  vegetation    magenta  (3.00, 0.15, 3.00)
  class 2/6/7            black    (0.00, 0.00, 0.00)   <- cannot happen
  class 0, m <  m_lo, r >= r_hi   VANILLA (1,1,1)      rough dielectric
  class 0, m <  m_lo, r <  r_hi   teal     (0.15, 1.60, 1.60)  smooth dielectric
  class 0, m_lo <= m < m_hi       grey     (2.40, 2.40, 2.40)  semi-metal band
  class 0, m >= m_hi, r <  r_lo   cyan     (0.15, 3.00, 3.00)  mirror metal
  class 0, m >= m_hi, r_lo<=r<r_mid green  (0.15, 3.00, 0.15)  <- PAINT CANDIDATE
  class 0, m >= m_hi, r >= r_mid  orange   (3.00, 1.20, 0.15)  rough metal

Thresholds are OpConstants baked at build time (--set m_lo=... etc) so a
follow-up launch can bisect the window without touching this file.

CONTROL BUILD: --gain 0 emits NO constants, NO instructions and NO rewrite.
The module is written back out from the unmodified disassembly, and
spirv-dis -> spirv-as is byte-neutral on all 77 base modules (asserted by
build_hunt_paint.sh --control), so the gain-0 rung is `cmp`-identical to the
base. That is the non-tautological form of "F=0 must be byte-identical".

Anchors (measured over all 77 modules of
gi-50b-bleed-oil-sheen-deep-clothhi-cone2all):
  * class word: patch_compute_skin.acquire_class_shift  -- 77/77
  * metallic/roughness: the v4float G-buffer fetch whose .y feeds
    NMax(_, 0.0399999991) -- metallic = .x, roughness = NMin(NMax(.y,.04),1).
    77/77, and .x is the value the module's own skin gate compares against
    0.1 in 74 of them.
  * radiance writes: 151 over 76 modules; ab0bc2fee876d489 has ONE image
    write and its texel is an OpBitcast %v4int -- an integer buffer, not
    radiance -- so that module declines BY NAME and is copied verbatim.
  * of the 151 writes, 120 are dominated by the module's own class value and
    m/r fetch; the other 31 get a site-local REFETCH of both (same idiom as
    patch_compute_skin.build_hunt_writes / patch_shadow_brdf.emit_class_value).

Usage:
    python3 dev/patch_hunt_paint.py <mod.spvasm> --outdir DIR [--gain 1.0]
                                    [--set m_lo=0.1 ...] [--no-buckets]
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

# The module that legitimately has no radiance write. Named, not counted: a
# decline that is not on this list is a coverage failure (GOTCHAS: assert the
# site count, never the file hash).
KNOWN_DECLINE = {'ab0bc2fee876d489'}

# Census of the standing base. build_hunt_paint.sh fails if the build does
# not reproduce these exactly.
CENSUS = dict(modules=77, painted_modules=76, writes=151,
              top_level=120, refetched=31)

THRESH = dict(m_lo=0.10, m_hi=0.50, r_lo=0.12, r_mid=0.30, r_hi=0.35)

# name -> rgb at gain 1. Class tints are HUNT_PALETTE verbatim for 1/3/4/5 so
# the skin control is literally the known-good paint.
CLASS_TINT = {1: ('red', (3.0, 0.15, 0.15)),
              3: ('blue', (0.15, 0.15, 3.0)),
              4: ('yellow', (3.0, 3.0, 0.15)),
              5: ('magenta', (3.0, 0.15, 3.0))}
UNKNOWN_TINT = ('black', (0.0, 0.0, 0.0))
BUCKETS = [
    # key,        name,     rgb,                    meaning
    ('diel_rough', 'vanilla', (1.0, 1.0, 1.0)),
    ('diel_smooth', 'teal', (0.15, 1.60, 1.60)),
    ('semi', 'grey', (2.40, 2.40, 2.40)),
    ('metal_mirror', 'cyan', (0.15, 3.00, 3.00)),
    ('metal_paint', 'green', (0.15, 3.00, 0.15)),
    ('metal_rough', 'orange', (3.00, 1.20, 0.15)),
]


def _glsl_ext(mod):
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpExtInstImport "GLSL\.std\.450"', ln)
        if m:
            return m.group(1)
    die(f"{mod.name}: no GLSL.std.450 import")


def find_mr_fetch(mod):
    """The metallic/roughness G-buffer read, with everything a refetch needs.

    Anchored on the roughness FLOOR the renderer applies everywhere:
        %r0 = OpCompositeExtract %float %fetch 1
        %r1 = OpExtInst %float %glsl NMax %r0 %float_0_0399999991
        %r  = OpExtInst %float %glsl NMin %r1 %float_1
    metallic is component 0 of the SAME fetch (cross-checked against the
    module's own skin gate `m < 0.1` where it has one).
    """
    ext = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\d+)\s*=\s*OpCompositeExtract %float (%\d+) (\d)\s*$', ln)
        if m:
            ext.setdefault((m.group(2), int(m.group(3))), m.group(1))
    nmax = re.compile(r'\s*(%\d+)\s*=\s*OpExtInst %float (%\w+) NMax (%\d+) '
                      r'%float_0_0399999991\s*$')
    for i, ln in enumerate(mod.lines):
        m = nmax.match(ln)
        if not m:
            continue
        nmax_id, glsl, raw = m.groups()
        fid = next((f for (f, c), e in ext.items() if e == raw and c == 1), None)
        if fid is None:
            continue                       # a re-clamp of an already-clamped r
        fline, fed = mod.find_def(fid)
        mf = re.match(r'OpImageFetch %v4float (%\d+) (%\d+) Lod (%\w+)\s*$', fed or '')
        if not mf:
            continue
        img, coord, lod = mf.groups()
        _, imgd = mod.find_def(img)
        mi = re.match(r'OpLoad (%\w+) (%\d+)\s*$', imgd or '')
        if not mi:
            continue
        imgty, acc = mi.groups()
        _, accd = mod.find_def(acc)
        ma = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', accd or '')
        if not ma:
            continue
        ptrty, arr, slot = ma.groups()
        _, cd = mod.find_def(coord)
        mc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$', cd or '')
        if not mc:
            continue
        met = ext.get((fid, 0))
        if met is None:
            continue
        # the clamped roughness the shading actually uses
        rough = None
        for l2 in mod.lines:
            m2 = re.match(r'\s*(%\d+)\s*=\s*OpExtInst %float %\w+ NMin '
                          + re.escape(nmax_id) + r' %float_1\s*$', l2)
            if m2:
                rough = m2.group(1)
                break
        if rough is None:
            rough = nmax_id
        ctx = dict(imgty=imgty, ptrty=ptrty, arr=arr, lod=lod, glsl=glsl,
                   x=mc.group(1), y=mc.group(2), line=fline, slot=slot,
                   slot_chain=None, fetch=fid, met=met, rough=rough)
        _, sd = mod.find_def(slot)
        ms = re.match(r'OpIAdd %uint (%\d+) (%\w+)\s*$', sd or '')
        if ms:
            base, off = ms.groups()
            _, bd = mod.find_def(base)
            mb = re.match(r'OpLoad %uint (%\d+)\s*$', bd or '')
            if mb:
                _, pd = mod.find_def(mb.group(1))
                mp = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', pd or '')
                if mp:
                    ctx['slot_chain'] = dict(pcty=mp.group(1), regs=mp.group(2),
                                             pcidx=mp.group(3), off=off)
        return ctx
    die(f"{mod.name}: metallic/roughness G-buffer fetch (NMax(.y, 0.04)) not found")


def mr_fetch_inputs(ctx):
    ids = [ctx['arr'], ctx['lod'], ctx['x'], ctx['y'], ctx['glsl']]
    if ctx['slot_chain']:
        s = ctx['slot_chain']
        ids += [s['regs'], s['pcidx'], s['off']]
    else:
        ids.append(ctx['slot'])
    return [i for i in ids if i.startswith('%')]


def emit_mr_value(mod, ctx, ins, f04, f1):
    """Append a site-local metallic/roughness refetch; return (met, rough)."""
    I = mod.new_id
    if ctx['slot_chain']:
        sc = ctx['slot_chain']
        a, b, slot = I(), I(), I()
        ins += [
            f"        {a} = OpAccessChain {sc['pcty']} {sc['regs']} {sc['pcidx']}",
            f"        {b} = OpLoad %uint {a}",
            f"        {slot} = OpIAdd %uint {b} {sc['off']}",
        ]
    else:
        slot = ctx['slot']
    d, e, f, g, met, r0, r1, r2 = (I() for _ in range(8))
    ins += [
        f"        {d} = OpAccessChain {ctx['ptrty']} {ctx['arr']} {slot}",
        f"        {e} = OpLoad {ctx['imgty']} {d}",
        f"        {f} = OpCompositeConstruct %v2uint {ctx['x']} {ctx['y']}",
        f"        {g} = OpImageFetch %v4float {e} {f} Lod {ctx['lod']}",
        f"        {met} = OpCompositeExtract %float {g} 0",
        f"        {r0} = OpCompositeExtract %float {g} 1",
        f"        {r1} = OpExtInst %float {ctx['glsl']} NMax {r0} {f04}",
        f"        {r2} = OpExtInst %float {ctx['glsl']} NMin {r1} {f1}",
    ]
    return met, r2


def build_paint_writes(mod, cfg, writes, gain, thresh, buckets_on):
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def U(n):
        nid, c = mod.uconst(n)
        if c:
            consts.append(c)
        return nid

    def mix(rgb):
        # gain lerps each channel from vanilla toward the palette entry, so
        # gain 0 is the identity (and is short-circuited before we get here).
        return tuple(1.0 + gain * (x - 1.0) for x in rgb)

    one = C(1.0)
    f04, f1 = C(0.0399999991), C(1.0)
    th = {k: C(thresh[k]) for k in ('m_lo', 'm_hi', 'r_lo', 'r_mid', 'r_hi')}
    cls_ids = {n: U(n) for n in list(CLASS_TINT) + [0]}
    cls_rgb = {n: [C(x) for x in mix(CLASS_TINT[n][1])] for n in CLASS_TINT}
    unk_rgb = [C(x) for x in mix(UNKNOWN_TINT[1])]
    bkt_rgb = {k: [C(x) for x in mix(rgb)] for k, _n, rgb in BUCKETS}

    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((ins_line, pre_ins))
    mr = find_mr_fetch(mod)
    cf = None
    legend = []
    done, refetched, skipped = [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float construct'})
            continue
        ins = []
        cls, met, rough = shift, mr['met'], mr['rough']
        top = (cfg.dominates_line(dom_id, w['line'])
               and cfg.dominates_line(mr['met'], w['line'])
               and cfg.dominates_line(mr['rough'], w['line']))
        if not top:
            if cf is None:
                cf = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line']) for x in class_fetch_inputs(cf)) \
               or any(not cfg.dominates_line(x, w['line']) for x in mr_fetch_inputs(mr)):
                skipped.append({'line': w['line'] + 1, 'why': 'refetch inputs do not dominate'})
                continue
            cls = emit_class_value(mod, cf, ins)
            met, rough = emit_mr_value(mod, mr, ins, f04, f1)
            refetched.append(w['line'] + 1)

        def N(op, *a):
            i = mod.new_id()
            ins.append(f"        {i} = {op} %bool " + ' '.join(a))
            return i

        g = {n: N('OpIEqual', cls, cls_ids[n]) for n in [0] + list(CLASS_TINT)}
        known = g[0]
        for n in CLASS_TINT:
            known = N('OpLogicalOr', known, g[n])
        g_unk = N('OpLogicalNot', known)

        # last gate in the list wins the OpSelect chain, so order is:
        # buckets (class 0) -> class tints -> unknown-class black.
        gates = []
        if buckets_on:
            m_lo = N('OpFOrdLessThan', met, th['m_lo'])
            m_hi = N('OpFOrdLessThan', met, th['m_hi'])
            r_lo = N('OpFOrdLessThan', rough, th['r_lo'])
            r_mid = N('OpFOrdLessThan', rough, th['r_mid'])
            r_hi = N('OpFOrdLessThan', rough, th['r_hi'])
            n_mlo = N('OpLogicalNot', m_lo)
            n_mhi = N('OpLogicalNot', m_hi)
            n_rlo = N('OpLogicalNot', r_lo)
            n_rmid = N('OpLogicalNot', r_mid)
            n_rhi = N('OpLogicalNot', r_hi)
            def AND(*xs):
                cur = xs[0]
                for x in xs[1:]:
                    cur = N('OpLogicalAnd', cur, x)
                return cur
            gates += [
                (AND(g[0], m_lo, n_rhi), bkt_rgb['diel_rough']),
                (AND(g[0], m_lo, r_hi), bkt_rgb['diel_smooth']),
                (AND(g[0], n_mlo, m_hi), bkt_rgb['semi']),
                (AND(g[0], n_mhi, r_lo), bkt_rgb['metal_mirror']),
                (AND(g[0], n_mhi, n_rlo, r_mid), bkt_rgb['metal_paint']),
                (AND(g[0], n_mhi, n_rmid), bkt_rgb['metal_rough']),
            ]
        for n in sorted(CLASS_TINT):
            gates.append((g[n], cls_rgb[n]))
        gates.append((g_unk, unk_rgb))

        newc = []
        for ch in range(3):
            cur = one
            for gate, rgb in gates:
                s = mod.new_id()
                ins.append(f"        {s} = OpSelect %float {gate} {rgb[ch]} {cur}")
                cur = s
            n_ = mod.new_id()
            ins.append(f"        {n_} = OpFMul %float {w['comps'][ch]} {cur}")
            newc.append(n_)
        nt = mod.new_id()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                      r'\g<1>' + nt, mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die(f"{mod.name}: no radiance image write reachable for the paint")
    for n in sorted(CLASS_TINT):
        legend.append({'class': n, 'colour': CLASS_TINT[n][0]})
    for k, nm, _rgb in BUCKETS:
        legend.append({'bucket': k, 'colour': nm})
    return consts, edits, {
        'gain': gain, 'thresholds': dict(thresh), 'buckets': bool(buckets_on),
        'legend': legend, 'class_anchor': dom_id,
        'mr_fetch': {'fetch': mr['fetch'], 'metallic': mr['met'],
                     'roughness': mr['rough'], 'line': mr['line'] + 1},
        'writes': done, 'refetched': refetched, 'skipped': skipped}


def process(path, outdir, gain, thresh, buckets_on, do_rt=True):
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
        # THE CONTROL. Nothing is emitted, nothing is rewritten: the module is
        # re-assembled from the untouched disassembly, which is byte-neutral.
        rep['paint'] = {'gain': 0.0, 'control': True, 'writes': [],
                        'refetched': [], 'skipped': []}
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    writes = find_image_writes(mod)
    consts, edits, rep['paint'] = build_paint_writes(
        mod, cfg, writes, gain, thresh, buckets_on)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--gain', type=float, default=1.0,
                    help='0 = the byte-identical control (emits nothing)')
    ap.add_argument('--no-buckets', action='store_true',
                    help='class colours only -- the deliberately mis-gated '
                         'build used to prove verify_hunt_paint.py is not vacuous')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    thresh = dict(THRESH)
    for kv in a.set:
        k, v = kv.split('=', 1)
        if k not in thresh:
            die(f"unknown knob {k} (have {sorted(thresh)})")
        thresh[k] = float(v)
    if not (thresh['m_lo'] <= thresh['m_hi']):
        die("m_lo must be <= m_hi")
    if not (thresh['r_lo'] <= thresh['r_mid'] <= thresh['r_hi']):
        die("need r_lo <= r_mid <= r_hi")
    reps = [process(p, a.outdir, a.gain, thresh, not a.no_buckets,
                    do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
