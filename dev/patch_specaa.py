#!/usr/bin/env python3
"""specaa -- SPECULAR ANTI-ALIASING FROM THE PIXEL FOOTPRINT at the compute
resolvers' direct-light GGX sites (handoff/108 sec 2).

    python3 dev/patch_specaa.py <mod.spvasm> --outdir DIR
            [--kappa 0.5] [--sigma2-max 0.18] [--metal-min 0.3]
            [--pix-angle 0.001311] [--foot0 0.010] [--foot1 0.050]
            [--mode feature|vis] [--no-roundtrip-check]

WHAT IS WRONG WITH WHAT SHIPS
-----------------------------
A metal handrail at 30 m occupies a fraction of a pixel per bump.  The
resolver evaluates ONE GGX lobe at ONE normal per pixel, so the sub-pixel
normal distribution -- which is the whole reason the surface twinkles -- is
sampled once and aliased.  The path tracer's accumulation hides this while the
camera is still and turns it into crawling fireflies the moment it moves.

WHAT IS SPLICED
---------------
Kaplanyan et al. 2016 / Tokuyoshi & Kaplanyan 2019, filtering in alpha space:

    N0 = normalize(gbuf(x  , y  ).rgb - 0.5)      the module's OWN decode
    Nx = normalize(gbuf(x+1, y  ).rgb - 0.5)
    Ny = normalize(gbuf(x  , y+1).rgb - 0.5)
    v  = |Nx - N0|^2 + |Ny - N0|^2                screen-space normal variance
    w  = clamp((dist*pix_angle - foot0)/(foot1 - foot0), 0, 1)     see BELOW
    s2 = clamp(v * kappa * w, 0, sigma2_max)
    alpha' = sqrt(alpha^2 + s2)                   the Kaplanyan widening
    alpha'' = select(metallic > metal_min, alpha', alpha)

then `replace_all_uses(alpha -> alpha'')` -- `81`'s discipline, and
`patch_compute_skin.build_skin_alpha_cap`'s rewrite shape for its reason: a2 =
alpha*alpha, the Smith Vis term and the importance-sampling branch all read the
same id, and rewriting only the D term biases MIS (the 08-DUAL-LOBE lesson).

WHY A DISTANCE RAMP (this is the part the textbook leaves out)
--------------------------------------------------------------
The screen-space estimate cannot tell sub-pixel roughness from macroscopic
curvature: a coffee mug 40 cm from the camera has a large |dN/dx| and is NOT
aliasing -- its highlight is genuinely a smooth sweep, and widening alpha there
just makes near metal look sandblasted.  What separates the two cases is how
much WORLD AREA one texel covers.  `99` hands us P in metres and the camera
position, so:

    foot = |P - C| * pix_angle          metres subtended by one lighting texel

and the widening ramps in between foot0 = 1 cm (about 7.6 m out) and
foot1 = 5 cm (about 38 m out).  Below foot0 the splice is exactly identity --
sqrt(alpha^2 + 0) -- so near surfaces are untouched, which is the brief's
requirement and also the only way the A/B can be read: if near metal changes,
the ramp is wrong.

`pix_angle` is a BUILD CONSTANT, not a fetch.  The resolvers never load the
projection's vertical FOV in a form this pass can anchor on, and dev/glint_
model.py already sets the precedent of pinning it: 2*tan(vfov/2)/720 = 0.001311
rad/texel for the default 80 deg horizontal FOV at 16:9 and the 1280x720
lighting resolution.  A player on a different FOV slider gets a ramp that moves
by the FOV ratio and nothing else -- the feature degrades in scale, not in kind.

GATE: metallic > 0.3, DIELECTRICS DEFERRED
------------------------------------------
Three reasons, in order of weight.  (1) A dielectric's specular is a 0.04 F0
lobe under a diffuse term that dominates the pixel, so the same alpha widening
moves a much smaller fraction of the radiance and cannot be read in an A/B.
(2) The standing base ALREADY reshapes alpha on class-1 (skin) pixels --
build_skin_alpha_cap's ceiling is what produces the oily look -- and a second
uncoordinated widening on the same ids would fight a shipped feature rather
than test a new one.  (3) Rough dielectrics are being patched in parallel by
the world-hash pass (`107`); two passes widening the same alpha would make
neither rung readable.

ANCHORING (GOTCHAS 5 and 10)
----------------------------
* The G-buffer normal is found by its DECODE, not by its slot: an
  `OpImageFetch %v4float` whose components 0/1/2 each feed an
  `OpFAdd %float _ <bias>`, which feed a v3 construct, a self-dot, an
  InverseSqrt and three FMuls.  Exactly ONE fetch per module matches in 75 of
  77; the two that do not are declined BY HASH (see KNOWN_DECLINE) because
  picking one of 8 by position is precisely the guess GOTCHAS 10 forbids.
* The neighbour coordinate is `coord + 1`, and `coord` is a genuine linear
  image coordinate even though it is assembled from a tile list:
  x = (tile_x << 4) | (gid.x & 15) has its low four bits free, so the OR is an
  add and +1 crosses a tile boundary correctly.
* `metallic` is the operand of the module's OWN F0 = lerp(0.04, albedo,
  metallic) triple (patch_cfres.find_f0_metal_triples, imported), so the gate
  and the F0 it gates on are the same computation.  All 75 kept modules have
  exactly one such triple and its metallic dominates every alpha site.
* OUT OF BOUNDS: Vulkan returns zero for an out-of-bounds image load, so the
  right-most column and bottom row would decode (-0.5,-0.5,-0.5) and read as
  maximum variance.  The all-zero texel is detected exactly (three OpFOrdEqual
  and two OpLogicalAnd per neighbour) and drops the tap to v = 0.  A texel that
  is genuinely all-zero decodes to a diagonal normal and losing it costs
  nothing.
* NaN: an all-0.5 texel decodes to the zero vector, InverseSqrt(0) = inf and
  the normal comes out NaN.  The final NClamp absorbs it -- GLSL NMin/NMax
  return the non-NaN operand, so NClamp(NaN, 0, s2max) = 0 and alpha' = alpha.
  That is why the clamp is NClamp and not a hand-rolled min/max pair.

--kappa 0 emits NOTHING -- no constants, no instructions, no rewrite -- so the
control rung is BYTE-IDENTICAL to the base (`27` sec 8.3 is the cautionary tale
about 48 bytes of unconsumed OpConstant).

--mode vis is a DIAGNOSTIC, not a feature: it leaves alpha alone and replaces
the RGB of every image write with grey = s2/s2max on gated pixels, so the
picture shows exactly which pixels the feature reaches and how hard.  It needs
s2 and the gate at the WRITE, where neither the module's normal decode nor its
metallic is live any more, so both are re-issued there from leaves that do
dominate -- the same refetch discipline as emit_class_value and emit_world_pos.
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
from patch_compute_brdf import detect_target_env, find_image_writes
import patch_skin_brdf as P
import patch_compute_skin as CS
import wpos_core as W
from patch_cfres import defs_index, find_f0_metal_triples

# Declined BY HASH, with the measurement that declines them.  Both are the
# modules `99` also declines, for the same underlying reason -- they are the
# two resolvers that do not carry a single canonical G-buffer read.
KNOWN_DECLINE = {
    '99bb7c2698997b2a': '8 normal-decode chains and no position chain -- '
                        'picking one of 8 by position is GOTCHAS 10',
    'ab0bc2fee876d489': '4 normal-decode chains and no position chain (the '
                        'v4uint reservoir pass, `46` sec 12)',
}

# Census of the standing base gi-50b-...-earglow-cap6-glintdense, over the 75
# kept modules.  The build fails on any drift ("a byte diff is not coverage").
CENSUS = dict(modules=75, alphas=303, sites=351, writes=150,
              # Every `D = a^2/(x*pi)` alpha in the 75, found WITHOUT the line
              # windows patch_skin_brdf.find_ggx_sites uses.  303 of these 343
              # are the direct-light sites that detector reports; the other 40
              # are D terms whose `outs` chain sits outside its 160-line window
              # (handoff/108 sec 9).  The gap is asserted, not glossed.
              ggx_d_alphas=343)

# 2*tan(40 deg)/720, the default-FOV 720p lighting texel.  See the docstring.
PIX_ANGLE = 0.001311


def line_dominates(cfg, dline, uline):
    """Block-level dominance for a line that has no id yet.

    CFG.dominates_line needs an id it can look up; an instruction this pass is
    about to INSERT has none, so the same test is made on its insertion line.
    """
    db, ub = cfg.block_of(dline), cfg.block_of(uline)
    if db is None or ub is None:
        return False
    if db['label'] not in cfg.reachable or ub['label'] not in cfg.reachable:
        return False
    if db['label'] == ub['label']:
        return dline < uline
    return db['label'] in cfg.dom.get(ub['label'], set())


# --------------------------------------------------------------- anchoring
def find_normal_chains(mod, D):
    """Every G-buffer normal DECODE chain, found by its shape.

    fetch -> extract 0/1/2 -> +bias -> v3 construct -> self dot -> InverseSqrt
    -> three FMuls.  The bias constant is read off the module rather than
    assumed: `-0.5` is what these modules use, but the pass never types it.
    """
    out = []
    ext = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpCompositeExtract %float (%\w+) (\d)\s*$', ln)
        if m:
            ext.setdefault(m.group(2), {})[int(m.group(3))] = m.group(1)
    adds = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpFAdd %float (%\w+) (%float_\w+)\s*$', ln)
        if m:
            adds.setdefault((m.group(2), m.group(3)), []).append(m.group(1))
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$',
                     ln)
        if not m:
            continue
        fid, img, coord, lod = m.groups()
        e = ext.get(fid, {})
        if not all(k in e for k in (0, 1, 2)):
            continue
        biases = {b for (src, b) in adds if src in (e[0], e[1], e[2])}
        for bias in sorted(biases):
            dec = []
            for k in (0, 1, 2):
                got = adds.get((e[k], bias))
                dec.append(got[0] if got else None)
            if any(d is None for d in dec):
                continue
            want = 'OpCompositeConstruct %v3float ' + ' '.join(dec)
            cons = [a for a, (_l, t) in D.items() if t == want]
            if not cons:
                continue
            dots = []
            for a, (_l, t) in D.items():
                dm = re.match(r'OpDot %float (%\w+) (%\w+)$', t)
                if dm and set(dm.groups()) <= set(cons):
                    dots.append(a)
            if not dots:
                continue
            isq = [a for a, (_l, t) in D.items()
                   if any(t == f'OpExtInst %float {mod.glsl} InverseSqrt {d}'
                          for d in dots)]
            if not isq:
                continue
            muls = 0
            for a, (_l, t) in D.items():
                mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', t)
                if mm and set(mm.groups()) & set(isq) and set(mm.groups()) & set(dec):
                    muls += 1
            if muls < 3:
                continue
            cm = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)$',
                          D.get(coord, (None, ''))[1])
            if not cm:
                continue
            out.append(dict(line=i, fetch=fid, img=img, lod=lod, bias=bias,
                            cx=cm.group(1), cy=cm.group(2)))
    return out


def find_metal_fetch(mod, D, met):
    """The G-buffer read `metallic` is an extract of, for the vis refetch."""
    m = re.match(r'OpCompositeExtract %float (%\w+) (\d)$', D.get(met, (None, ''))[1])
    if not m:
        return None
    fid, comp = m.groups()
    fm = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)$',
                  D.get(fid, (None, ''))[1])
    if not fm:
        return None
    img, coord, lod = fm.groups()
    cm = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)$',
                  D.get(coord, (None, ''))[1])
    if not cm:
        return None
    return dict(img=img, lod=lod, comp=int(comp), cx=cm.group(1), cy=cm.group(2))


# ---------------------------------------------------------------- emission
def emit_normal(mod, ins, ch, cx, cy):
    """One G-buffer normal tap at (cx, cy).  Returns (normal, raw texel rgb).

    The instruction order is the module's own: construct, fetch, three
    extracts, three biased adds, one v3, one self-dot, InverseSqrt, three
    FMuls with the reciprocal FIRST -- so the verifier reads one shape.
    """
    I = mod.new_id
    co, f = I(), I()
    ins += [f"        {co} = OpCompositeConstruct %v2uint {cx} {cy}",
            f"        {f} = OpImageFetch %v4float {ch['img']} {co} Lod {ch['lod']}"]
    e = []
    for k in range(3):
        t = I()
        ins.append(f"        {t} = OpCompositeExtract %float {f} {k}")
        e.append(t)
    d = []
    for k in range(3):
        t = I()
        ins.append(f"        {t} = OpFAdd %float {e[k]} {ch['bias']}")
        d.append(t)
    v, dt, rs = I(), I(), I()
    ins += [f"        {v} = OpCompositeConstruct %v3float {d[0]} {d[1]} {d[2]}",
            f"        {dt} = OpDot %float {v} {v}",
            f"        {rs} = OpExtInst %float {mod.glsl} InverseSqrt {dt}"]
    n = []
    for k in range(3):
        t = I()
        ins.append(f"        {t} = OpFMul %float {rs} {d[k]}")
        n.append(t)
    return n, e


def emit_sigma2(mod, ins, ch, ctx, cam, dom, site_line, knobs, C, U, uc):
    """The whole footprint estimator at `site_line`.  Returns the sigma2 id."""
    I = mod.new_id
    gl = mod.glsl
    zero, one = C(0.0), C(1.0)
    cx1, cy1 = I(), I()
    ins += [f"        {cx1} = OpIAdd %uint {ch['cx']} {U(1)}",
            f"        {cy1} = OpIAdd %uint {ch['cy']} {U(1)}"]
    n0, _e0 = emit_normal(mod, ins, ch, ch['cx'], ch['cy'])
    nx, ex = emit_normal(mod, ins, ch, cx1, ch['cy'])
    ny, ey = emit_normal(mod, ins, ch, ch['cx'], cy1)

    def diff2(nb, n0):
        nonlocal ins
        d = []
        for k in range(3):
            t = I()
            ins.append(f"        {t} = OpFSub %float {nb[k]} {n0[k]}")
            d.append(t)
        v, dt = I(), I()
        ins += [f"        {v} = OpCompositeConstruct %v3float {d[0]} {d[1]} {d[2]}",
                f"        {dt} = OpDot %float {v} {v}"]
        return dt

    dx2, dy2 = diff2(nx, n0), diff2(ny, n0)
    vraw = I()
    ins.append(f"        {vraw} = OpFAdd %float {dx2} {dy2}")

    # Out-of-bounds taps read back as an all-zero texel (Vulkan guarantees zero
    # for an out-of-bounds image load); drop them rather than read them as
    # maximum variance along the last column and row.
    def zerotest(e):
        nonlocal ins
        b = []
        for k in range(3):
            t = I()
            ins.append(f"        {t} = OpFOrdEqual %bool {e[k]} {zero}")
            b.append(t)
        a1, a2 = I(), I()
        ins += [f"        {a1} = OpLogicalAnd %bool {b[0]} {b[1]}",
                f"        {a2} = OpLogicalAnd %bool {a1} {b[2]}"]
        return a2

    oob, vsafe = I(), I()
    zx, zy = zerotest(ex), zerotest(ey)
    ins += [f"        {oob} = OpLogicalOr %bool {zx} {zy}",
            f"        {vsafe} = OpSelect %float {oob} {zero} {vraw}"]

    # The distance ramp.  P is in metres (99 sec 0); C is the camera the module
    # itself loads to build V, so |P - C| needs no world offset (99 sec 3).
    px, py, pz = W.emit_world_pos(mod, dom, ctx, site_line, ins, uc=uc,
                                  relative_to_camera=True, cam=cam)
    pv, d2, dist, foot, fm, wr, wc = (I() for _ in range(7))
    ins += [f"        {pv} = OpCompositeConstruct %v3float {px} {py} {pz}",
            f"        {d2} = OpDot %float {pv} {pv}",
            f"        {dist} = OpExtInst %float {gl} Sqrt {d2}",
            f"        {foot} = OpFMul %float {dist} {C(knobs['pix_angle'])}",
            f"        {fm} = OpFSub %float {foot} {C(knobs['foot0'])}",
            f"        {wr} = OpFMul %float {fm} {C(knobs['inv_span'])}",
            f"        {wc} = OpExtInst %float {gl} NClamp {wr} {zero} {one}"]
    # GOTCHAS: scale BEFORE the clamp -- sigma2_max is a ceiling on the
    # widening that ships, not on the raw variance.
    s1, s2, sig = I(), I(), I()
    ins += [f"        {s1} = OpFMul %float {vsafe} {C(knobs['kappa'])}",
            f"        {s2} = OpFMul %float {s1} {wc}",
            f"        {sig} = OpExtInst %float {gl} NClamp {s2} {zero} "
            f"{C(knobs['sigma2_max'])}"]
    return sig


def _prologue(mod, cfg, knobs):
    """Everything both modes need, or die with the reason."""
    D = defs_index(mod)
    chains = find_normal_chains(mod, D)
    if len(chains) != 1:
        die(f"{mod.name}: {len(chains)} G-buffer normal decode chains, "
            f"expected exactly 1 -- this module must be declined by hash")
    ch = chains[0]
    trips = find_f0_metal_triples(mod, D)
    mets = sorted({t['metal'] for t in trips})
    if len(mets) != 1:
        die(f"{mod.name}: {len(mets)} distinct metallic ids from "
            f"{len(trips)} F0 triples, expected exactly 1")
    ctx = W.find_pos_chain(mod)
    if not ctx:
        die(f"{mod.name}: no position chain -- no distance ramp is possible")
    cam = W.find_campos(mod, ctx)
    if not cam:
        die(f"{mod.name}: no camera position")
    return D, ch, mets[0], ctx, cam


def build_specaa(mod, cfg, knobs):
    """Widen alpha at every GGX site.  One estimator per dominating block."""
    consts, edits = [], []
    D, ch, met, ctx, cam = _prologue(mod, cfg, knobs)
    dom = W.Dom(mod)
    uc = {'decls': []}

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def U(n):
        key = ('u', int(n))
        if key not in uc:
            nid, decl = mod.uconst(n)
            uc[key] = nid
            if decl:
                uc['decls'].append(decl)
        return uc[key]

    gl = mod.glsl
    I = mod.new_id
    mmin = C(knobs['metal_min'])
    sites = P.find_ggx_sites(mod)
    alphas = sorted({s['alpha'] for s in sites},
                    key=lambda a: mod.find_def(a)[0])
    cones = {a: W.cone(D, a) for a in alphas}
    rep = dict(mode='feature', sites=len(sites), alphas=0,
               seen_alphas=len(alphas), estimators=0, metal=met,
               normal_fetch=ch['fetch'], bias=ch['bias'],
               alpha_chained=sum(1 for a in alphas
                                 if any(b != a and b in cones[a] for b in alphas)),
               skipped_dom=[], skipped_leaf=[])
    leaves = [ch['img'], ch['lod'], ch['cx'], ch['cy']] + list(W.pos_leaves(ctx))
    shared = []                       # (insert_line, sigma2_id) already emitted
    pending = {}                      # insert_line -> ins list
    for alpha in alphas:
        aline, _ = mod.find_def(alpha)
        bad = [x for x in leaves if not dom.dominates_line(x, aline)]
        if bad:
            rep['skipped_leaf'].append({'alpha': alpha, 'leaves': bad})
            continue
        if not cfg.dominates_line(met, aline):
            rep['skipped_dom'].append(alpha)
            continue
        sig = None
        for sl, sid in shared:
            if line_dominates(cfg, sl, aline):
                sig = sid
                break
        ins = pending.setdefault(aline, [])
        if sig is None:
            sig = emit_sigma2(mod, ins, ch, ctx, cam, dom, aline, knobs,
                              C, U, uc)
            shared.append((aline, sig))
            rep['estimators'] += 1
        aa, sm, ap, gt, sel = (I() for _ in range(5))
        ins += [f"        {aa} = OpFMul %float {alpha} {alpha}",
                f"        {sm} = OpFAdd %float {aa} {sig}",
                f"        {ap} = OpExtInst %float {gl} Sqrt {sm}",
                f"        {gt} = OpFOrdGreaterThan %bool {met} {mmin}",
                f"        {sel} = OpSelect %float {gt} {ap} {alpha}"]
        replace_all_uses(mod, alpha, sel, aline)
        rep['alphas'] += 1
    if rep['alphas'] == 0:
        die(f"{mod.name}: no GGX alpha widened")
    edits += sorted(pending.items())
    consts += uc['decls']
    return consts, edits, rep


def build_specaa_vis(mod, cfg, knobs):
    """Paint sigma2 as a grey ramp on gated pixels.  Alpha is NOT touched."""
    consts, edits = [], []
    D, ch, met, ctx, cam = _prologue(mod, cfg, knobs)
    mf = find_metal_fetch(mod, D, met)
    if mf is None:
        die(f"{mod.name}: metallic {met} is not an extract of an image fetch "
            f"-- the vis gate cannot be re-issued at the writes")
    dom = W.Dom(mod)
    uc = {'decls': []}

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def U(n):
        key = ('u', int(n))
        if key not in uc:
            nid, decl = mod.uconst(n)
            uc[key] = nid
            if decl:
                uc['decls'].append(decl)
        return uc[key]

    I = mod.new_id
    mmin = C(knobs['metal_min'])
    inv_s2 = C(1.0 / knobs['sigma2_max'])
    writes = find_image_writes(mod)
    rep = dict(mode='vis', writes=0, estimators=0, seen_writes=len(writes),
               metal=met, normal_fetch=ch['fetch'], skipped=[])
    leaves = ([ch['img'], ch['lod'], ch['cx'], ch['cy'], mf['img'], mf['lod'],
               mf['cx'], mf['cy']] + list(W.pos_leaves(ctx)))
    for w in writes:
        L = w['line']
        if w['comps'] is None:
            rep['skipped'].append({'line': L + 1, 'why': 'texel not a v4 construct'})
            continue
        bad = [x for x in leaves if not dom.dominates_line(x, L)]
        if bad:
            rep['skipped'].append({'line': L + 1, 'why': f'leaves {bad}'})
            continue
        ins = []
        sig = emit_sigma2(mod, ins, ch, ctx, cam, dom, L, knobs, C, U, uc)
        co, f, m0, gt, grey = (I() for _ in range(5))
        ins += [f"        {co} = OpCompositeConstruct %v2uint {mf['cx']} {mf['cy']}",
                f"        {f} = OpImageFetch %v4float {mf['img']} {co} Lod {mf['lod']}",
                f"        {m0} = OpCompositeExtract %float {f} {mf['comp']}",
                f"        {gt} = OpFOrdGreaterThan %bool {m0} {mmin}",
                f"        {grey} = OpFMul %float {sig} {inv_s2}"]
        newc = []
        for k in range(3):
            n = I()
            ins.append(f"        {n} = OpSelect %float {gt} {grey} {w['comps'][k]}")
            newc.append(n)
        nt = I()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        edits.append((L - 1, ins))
        mod.lines[L] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                              r'\g<1>' + nt, mod.lines[L])
        rep['writes'] += 1
        rep['estimators'] += 1
    if rep['writes'] == 0:
        die(f"{mod.name}: no image write could carry the sigma2 ramp")
    consts += uc['decls']
    return consts, edits, rep


def process(path, outdir, knobs, mode, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    if knobs['kappa'] == 0.0:
        # THE CONTROL.  Nothing emitted, nothing rewritten.
        rep['specaa'] = dict(mode='control', kappa=0.0, control=True,
                             alphas=0, sites=0, estimators=0, writes=0,
                             skipped_dom=[], skipped_leaf=[], skipped=[])
        return CS._emit(mod, outdir, target_env, rep)
    if mod.ident in KNOWN_DECLINE:
        die(f"{mod.name}: declined by hash -- {KNOWN_DECLINE[mod.ident]}")
    cfg = CFG(mod)
    build = build_specaa_vis if mode == 'vis' else build_specaa
    consts, edits, rep['specaa'] = build(mod, cfg, knobs)
    rep['specaa'].update(kappa=knobs['kappa'], metal_min=knobs['metal_min'],
                         sigma2_max=knobs['sigma2_max'],
                         pix_angle=knobs['pix_angle'],
                         foot0=knobs['foot0'], foot1=knobs['foot1'])
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--mode', default='feature', choices=('feature', 'vis'))
    ap.add_argument('--kappa', type=float, default=0.5,
                    help='kernel constant; 0 = the byte-identical control')
    ap.add_argument('--sigma2-max', type=float, default=0.18)
    ap.add_argument('--metal-min', type=float, default=0.3)
    ap.add_argument('--pix-angle', type=float, default=PIX_ANGLE)
    ap.add_argument('--foot0', type=float, default=0.010)
    ap.add_argument('--foot1', type=float, default=0.050)
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if a.kappa < 0.0:
        die('--kappa must be >= 0')
    if a.foot1 <= a.foot0:
        die('--foot1 must exceed --foot0')
    knobs = dict(kappa=a.kappa, sigma2_max=a.sigma2_max,
                 metal_min=a.metal_min, pix_angle=a.pix_angle,
                 foot0=a.foot0, foot1=a.foot1,
                 inv_span=1.0 / (a.foot1 - a.foot0))
    reps = [process(p, a.outdir, knobs, a.mode,
                    do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
