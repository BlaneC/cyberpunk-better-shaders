#!/usr/bin/env python3
"""
patch_compute_hair.py -- the hair tiers, ported to the GLCompute resolve
shaders (the confirmed visible shading surface, handoff/07 + the white-skin
confirmation launch).

Tiers:
  hairhunt          10-class palette tint at every image write. One launch
                    identifies hair's material class by colour (skin=1=red is
                    the control -- it is the same gate that just turned skin
                    white). No BRDF change.
  hair --hair-class N
                    The actual hair shading, gated on class N:
                      * Kajiya-Kay anisotropic lobe from the structure-tensor
                        tangent (light runs down the strand). The tangent is
                        estimated from the screen-space normal G-buffer
                        exactly as dev/HAIR_HANDOFF.md designed it.
                      * roughness reshape (s_h, a_min) rewriting ALL alpha
                        uses so sampling and eval agree,
                      * grazing sheen on the spec outputs.
                    Diffuse wrap is NOT ported yet: the compute resolve has
                    scalar diffuse (no r,g,b triples), so the wrap needs its
                    own anchor -- tracked in handoff/07.

Anchor-reuse notes (all verified on 3 modules before writing this):
  * find_ggx_sites, find_site_nh, build_hairaniso, build_hair_spec,
    find_class_shift port from patch_skin_brdf UNCHANGED -- the compute
    modules use the same dxil-spirv idioms. The class shift dominates every
    GGX site and alpha line (checked: 11/11, 11/11, 9/9), so a hair gate
    IEqual inserted right after it inherits dominance like the reference
    patcher's did.
  * The normal G-buffer here decodes as n*2-1 instead of (n-0.5): the finder
    below anchors on that. The structure tensor is UNAFFECTED -- it uses
    neighbour DIFFERENCES, and (v-0.5) is parallel to (2v-1), so
    emit_aniso/emit_nfetch (including the axis-aligned eigenvector fix that a
    synthetic-fibre test caught) are reused as-is by handing them an
    identically-shaped ctx dict.
  * Compute modules are SPIR-V 1.3 (target env auto-detected); idents are
    hash-only "<hash>.dxil".

Usage:
  python3 dev/patch_compute_hair.py <asm> --tier hairhunt --outdir swaps/
  python3 dev/patch_compute_hair.py <asm> --tier hair --hair-class N --outdir swaps/
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import (apply_edits, roundtrip_check, die,
                             HUNT_PALETTE, HUNT_DEFAULT, KNOBS, VANILLA)
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG
from patch_compute_brdf import find_image_writes, detect_target_env


def find_normal_gbuffer_compute(mod):
    """The screen-space normal fetch, compute-resolve encoding.

    Anchor: ImageFetch %v4float whose first three extracted components each
    feed `OpFMul %float c %float_2` and whose products feed
    `OpFAdd %float p %float_n1` -- the unorm n*2-1 decode. The descriptor
    chain (registers[<idx>] + <off> into a bindless image array) and the
    pixel-coordinate ids are read off the found instructions; the returned
    dict has the exact shape patch_skin_brdf.find_normal_gbuffer returns, so
    emit_nfetch/emit_aniso consume it unchanged.
    """
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpImageFetch %v4float (%\d+) (%\d+)'
                     r' Lod (%\w+)\s*$', ln)
        if not m:
            continue
        fid, img, coord, lod = m.groups()
        exts = []
        for j in range(i + 1, min(i + 8, len(mod.lines))):
            mm = re.match(r'\s*(%\d+)\s*=\s*OpCompositeExtract %float '
                          + re.escape(fid) + r' (\d)\s*$', mod.lines[j])
            if mm and int(mm.group(2)) < 3:
                exts.append(mm.group(1))
        if len(exts) < 3:
            continue
        hits = 0
        for e in exts[:3]:
            mul = None
            for j, l2 in enumerate(mod.lines):
                mm = re.match(r'\s*(%\d+)\s*=\s*OpFMul %float '
                              + re.escape(e) + r' %float_2\s*$', l2)
                if mm:
                    mul = mm.group(1)
                    break
            if not mul:
                continue
            if any(re.match(r'\s*%\d+\s*=\s*OpFAdd %float '
                            + re.escape(mul) + r' %float_n1\s*$', l3)
                   for l3 in mod.lines):
                hits += 1
        if hits < 3:
            continue
        _, imgd = mod.find_def(img)
        mi = re.match(r'OpLoad (%\w+) (%\d+)\s*$', imgd or '')
        if not mi:
            continue
        imgty, ac = mi.groups()
        _, acd = mod.find_def(ac)
        ma = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', acd or '')
        if not ma:
            continue
        ptrty, arr, slot = ma.groups()
        _, sd = mod.find_def(slot)
        ms = re.match(r'OpIAdd %uint (%\d+) (%\w+)\s*$', sd or '')
        if not ms:
            continue
        _, bd = mod.find_def(ms.group(1))
        mb = re.match(r'OpLoad %uint (%\d+)\s*$', bd or '')
        if not mb:
            continue
        _, pcd = mod.find_def(mb.group(1))
        mp = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', pcd or '')
        if not mp:
            continue
        _, cd = mod.find_def(coord)
        mc = re.match(r'OpCompositeConstruct %v2uint (%\d+) (%\d+)\s*$', cd or '')
        if not mc:
            continue
        return dict(imgty=imgty, ptrty=ptrty, arr=arr, off=ms.group(2),
                    pcty=mp.group(1), regs=mp.group(2), idx=mp.group(3),
                    lod=lod, x=mc.group(1), y=mc.group(2), line=i)
    die(f"{mod.name}: normal G-buffer fetch (n*2-1 decode) not found")


def find_normal_gbuffer_any(mod):
    """Normal G-buffer, either encoding. The direct resolvers decode n*2-1;
    the GI resolvers use the reference (n-0.5) form. The structure tensor is
    indifferent -- it consumes neighbour DIFFERENCES, and (2v-1) is just a
    scaled (v-0.5), so the eigenvectors are identical either way."""
    try:
        return find_normal_gbuffer_compute(mod)
    except SystemExit:
        return P.find_normal_gbuffer(mod)


def find_class_anchor_variant(mod):
    """The material G-buffer read in modules that never compute `y >> 5`.

    36 of the 84 resolve modules (the local-light / non-sun paths -- exactly
    the ones the white-skin launch showed as uncovered) read the SAME texel at
    the SAME binding (registers[2]+4, verified identical across variants) but
    only mask its low bits: `extract(fetch, 1) & 31`. The class field in bits
    5+ is still present in the fetched word; these modules just do not use it.
    Anchor on that fetch and return the extract id + its line so the caller
    can emit its own `>> 5` right after it, inheriting the fetch's dominance.
    """
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpImageFetch %v4uint %\d+ %\d+ Lod', ln)
        if not m:
            continue
        fid = m.group(1)
        for j in range(i + 1, min(i + 10, len(mod.lines))):
            me = re.match(r'\s*(%\d+)\s*=\s*OpCompositeExtract %uint '
                          + re.escape(fid) + r' 1\s*$', mod.lines[j])
            if not me:
                continue
            eid = me.group(1)
            if any(re.match(r'\s*%\d+\s*=\s*OpBitwiseAnd %uint '
                            + re.escape(eid) + r' %uint_31\s*$', l2)
                   for l2 in mod.lines):
                return eid, j
    die(f"{mod.name}: no material G-buffer read found (neither >>5 nor &31)")


def acquire_class_shift(mod):
    """The `y >> 5` material class value and the line to insert gates after.

    Prefers the module's own shift (find_class_shift); in the &31-only variant
    modules, emits our own shift from the shared texel. Returns
    (shift_id, insert_line, extra_instructions, extra_consts).
    """
    try:
        shift, ieq_line = P.find_class_shift(mod)
        return shift, ieq_line, [], [], shift
    except SystemExit:
        pass
    eid, eline = find_class_anchor_variant(mod)
    u5, ud = mod.uconst(5)
    shift = mod.new_id()
    ins = [f"        {shift} = OpShiftRightLogical %uint {eid} {u5}"]
    # dominance must be tested on an id that exists in the module TODAY --
    # the extract the new shift reads -- not on the pending new id (which
    # find_def cannot see and would be treated as module-scope, i.e. always
    # dominating).
    return shift, eline, ins, ([ud] if ud else []), eid


def find_c1_sites(mod):
    """Each Disney diffuse eval in a resolve module, with its NoL and NoV.

    Structure at every site (ids differ, shape verified):

        base   = OpFSub 1/pi (rough * 0.107508637)      <- find_disney_bases
        s1     = OpFMul base FD_a
        scalar = OpFMul s1   FD_b                       <- shared diffuse scalar
        FD_*   = OpFAdd (pow5(1-cos) * FD90term) 1

    walking each FD chain down to its `OpFSub %float_1 <cos>` leaf yields the
    two cosines. NoV is the one built as NMin(NMax(dot, 1e-5), 1) -- the same
    eps-clamp signature the reference module used -- and NoL is the plain
    NClamp'd dot. Sites where the two cannot be told apart are skipped.
    """
    from patch_chs_brdf import find_disney_bases, uses_of
    eps = '%float_9_99999975en06'

    def fd_cosine(fd):
        seen, stack = set(), [fd]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            _, d = mod.find_def(cur)
            if not d:
                continue
            m = re.match(r'OpFSub %float %float_1 (%\d+)\s*$', d)
            if m:
                return m.group(1)
            m = re.match(r'OpF(?:Mul|Add) %float (%\w+) (%\w+)', d)
            if m:
                stack += [x for x in m.groups() if x.startswith('%')]
        return None

    def is_nov(cos):
        _, d = mod.find_def(cos)
        m = re.match(r'OpExtInst %float %\w+ NMin (%\d+) %float_1\s*$', d or '')
        if not m:
            return False
        _, d2 = mod.find_def(m.group(1))
        return bool(re.match(r'OpExtInst %float %\w+ NMax %\d+ '
                             + re.escape(eps), d2 or ''))

    sites, skipped = [], []
    for b in find_disney_bases(mod):
        site = None
        u1 = [j for j in uses_of(mod, b['base']) if '= OpFMul' in mod.lines[j]]
        if len(u1) == 1:
            m1 = re.match(r'\s*(%\d+)\s*=\s*OpFMul %float (%\w+) (%\w+)',
                          mod.lines[u1[0]])
            s1 = m1.group(1)
            fd_a = m1.group(3) if m1.group(2) == b['base'] else m1.group(2)
            u2 = [j for j in uses_of(mod, s1) if '= OpFMul' in mod.lines[j]]
            if len(u2) == 1:
                m2 = re.match(r'\s*(%\d+)\s*=\s*OpFMul %float (%\w+) (%\w+)',
                              mod.lines[u2[0]])
                scalar = m2.group(1)
                fd_b = m2.group(3) if m2.group(2) == s1 else m2.group(2)
                ca, cb = fd_cosine(fd_a), fd_cosine(fd_b)
                if ca and cb:
                    if is_nov(cb) and not is_nov(ca):
                        site = dict(scalar=scalar, line=u2[0], nol=ca, nov=cb)
                    elif is_nov(ca) and not is_nov(cb):
                        site = dict(scalar=scalar, line=u2[0], nol=cb, nov=ca)
        if site:
            sites.append(site)
        else:
            skipped.append(b['line'] + 1)
    return sites, skipped


def build_skin_c1(mod, cfg, dom_id, skin_gate, knobs, hair_gate=None):
    """Tier-1 c1 at every Disney diffuse site, gated on skin (class 1).

    Same maths as patch_skin_brdf.emit_c1_factor -- Log2/Exp2 pow with eps
    clamps, c1 = (1+(rho_f-1)a_f)(1+(rho_r-1)a_r) -- but the compute site
    hands us NoL and NoV directly, so the reference's NoV reconstruction is
    unnecessary. The factor multiplies the shared diffuse scalar, reaching
    all three channels through the site's own per-channel FMuls.
    """
    from patch_skin_brdf import replace_all_uses, EPS
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one, eps = C(1.0), C(EPS)
    e_ef = C(10.0 * (1.0 - knobs["n_f"]))
    e_tf = C(10.0 * (1.0 - knobs["m_f"]))
    e_er = C(10.0 * (1.0 - knobs["n_r"]))
    e_tr = C(10.0 * (1.0 - knobs["m_r"]))
    rf, rr = C(knobs["rho_f"]), C(knobs["rho_r"])
    gl = mod.glsl
    sites, skipped = find_c1_sites(mod)
    rep = {"c1_sites": 0, "skipped_shape": skipped, "skipped_dom": []}
    for s in sites:
        if not cfg.dominates_line(dom_id, s['line']):
            rep["skipped_dom"].append(s['line'] + 1)
            continue
        I = mod.new_id
        onl, onv, b1, b2, b3, b4 = [I() for _ in range(6)]
        l1, l2, l3, l4 = [I() for _ in range(4)]
        x1, x2, x3, x4, p1, p2, p3, p4 = [I() for _ in range(8)]
        af, ar, df, dr, tf, tr, cf, cr, c1, g, out = [I() for _ in range(11)]
        ins = [
            f"        {onl} = OpFSub %float {one} {s['nol']}",
            f"        {onv} = OpFSub %float {one} {s['nov']}",
            f"        {b1} = OpExtInst %float {gl} NMax {onl} {eps}",
            f"        {b2} = OpExtInst %float {gl} NMax {onv} {eps}",
            f"        {b3} = OpExtInst %float {gl} NMax {s['nol']} {eps}",
            f"        {b4} = OpExtInst %float {gl} NMax {s['nov']} {eps}",
            f"        {l1} = OpExtInst %float {gl} Log2 {b1}",
            f"        {l2} = OpExtInst %float {gl} Log2 {b2}",
            f"        {l3} = OpExtInst %float {gl} Log2 {b3}",
            f"        {l4} = OpExtInst %float {gl} Log2 {b4}",
            f"        {x1} = OpFMul %float {l1} {e_ef}",
            f"        {x2} = OpFMul %float {l4} {e_tf}",
            f"        {x3} = OpExtInst %float {gl} Exp2 {x1}",
            f"        {x4} = OpExtInst %float {gl} Exp2 {x2}",
            f"        {af} = OpFMul %float {x3} {x4}",
            f"        {p1} = OpFMul %float {l2} {e_er}",
            f"        {p2} = OpFMul %float {l3} {e_tr}",
            f"        {p3} = OpExtInst %float {gl} Exp2 {p1}",
            f"        {p4} = OpExtInst %float {gl} Exp2 {p2}",
            f"        {ar} = OpFMul %float {p3} {p4}",
            f"        {df} = OpFSub %float {rf} {one}",
            f"        {dr} = OpFSub %float {rr} {one}",
            f"        {tf} = OpFMul %float {df} {af}",
            f"        {tr} = OpFMul %float {dr} {ar}",
            f"        {cf} = OpFAdd %float {one} {tf}",
            f"        {cr} = OpFAdd %float {one} {tr}",
            f"        {c1} = OpFMul %float {cf} {cr}",
            (f"        {g} = OpSelect %float {skin_gate} {c1} {one}"
             if skin_gate is not None else
             f"        {g} = OpFMul %float {one} {one}"),
        ]
        fac = g
        if hair_gate is not None:
            # hair wrap + depth, combined into the same multiply so the two
            # tiers never fight over the scalar's uses (reference
            # build_diffuse learned this the hard way)
            w = knobs["w_wrap"]
            wk, inv = C(w), C(1.0 / (1.0 + w))
            e3, rmax = C(1e-3), C(knobs["r_max"])
            kd = C(knobs.get("k_diff", 1.0))
            w1,w2,w3,w4,w5,w6,w7,w8,hg,comb = [I() for _ in range(10)]
            ins += [
                f"        {w1} = OpFAdd %float {s['nol']} {wk}",
                f"        {w2} = OpFMul %float {w1} {inv}",
                f"        {w3} = OpExtInst %float {gl} NClamp {w2} {C(0.0)} {one}",
                f"        {w4} = OpFMul %float {w3} {inv}",
                f"        {w5} = OpExtInst %float {gl} NMax {s['nol']} {e3}",
                f"        {w6} = OpFDiv %float {w4} {w5}",
                f"        {w7} = OpExtInst %float {gl} NMin {w6} {rmax}",
                f"        {w8} = OpFMul %float {w7} {kd}",
                f"        {hg} = OpSelect %float {hair_gate} {w8} {one}",
                f"        {comb} = OpFMul %float {g} {hg}",
            ]
            fac = comb
            rep["wrap_sites"] = rep.get("wrap_sites", 0) + 1
        ins.append(f"        {out} = OpFMul %float {s['scalar']} {fac}")
        replace_all_uses(mod, s['scalar'], out, s['line'])
        edits.append((s['line'], ins))
        rep["c1_sites"] += 1
    return consts, edits, rep


def build_hair_wrap(mod, cfg, dom_id, hair_gate, knobs):
    """Energy-normalized diffuse wrap + depth scale for hair, at the same
    Disney scalar sites find_c1_sites locates. Spliced as wrap/NoL (NoL is
    already folded into the light weight) times k_diff -- a global hair
    diffuse scale below 1 that deepens shadow terms so hair stops floating.
    Identity at w_wrap=0, k_diff=1."""
    from patch_skin_brdf import replace_all_uses
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    one, zero = C(1.0), C(0.0)
    w = knobs["w_wrap"]
    wk, inv = C(w), C(1.0 / (1.0 + w))
    e3, rmax, kd = C(1e-3), C(knobs["r_max"]), C(knobs.get("k_diff", 1.0))
    gl = mod.glsl
    sites, skipped = find_c1_sites(mod)
    rep = {"wrap_sites": 0, "skipped": len(skipped)}
    for st in sites:
        if not cfg.dominates_line(dom_id, st['line']):
            continue
        I = mod.new_id
        s1,s2,s3,s4,s5,s6,s7,s8,g,out = [I() for _ in range(10)]
        ins = [
            f"        {s1} = OpFAdd %float {st['nol']} {wk}",
            f"        {s2} = OpFMul %float {s1} {inv}",
            f"        {s3} = OpExtInst %float {gl} NClamp {s2} {zero} {one}",
            f"        {s4} = OpFMul %float {s3} {inv}",
            f"        {s5} = OpExtInst %float {gl} NMax {st['nol']} {e3}",
            f"        {s6} = OpFDiv %float {s4} {s5}",
            f"        {s7} = OpExtInst %float {gl} NMin {s6} {rmax}",
            f"        {s8} = OpFMul %float {s7} {kd}",
            f"        {g} = OpSelect %float {hair_gate} {s8} {one}",
            f"        {out} = OpFMul %float {st['scalar']} {g}",
        ]
        replace_all_uses(mod, st['scalar'], out, st['line'])
        edits.append((st['line'], ins))
        rep["wrap_sites"] += 1
    return consts, edits, rep


def hoist_pos(mod, cfg, site_lines):
    """Insertion point inside the deepest block dominating every site.

    The GI resolvers evaluate the BRDF 62 times per pixel. Re-emitting the
    structure tensor at each site would cost ~5 normal fetches x 62 -- a real
    frame-time regression -- and the tangent is a per-PIXEL quantity anyway:
    it does not vary per light or per site. So the tensor AND the class gate
    are emitted once here and reused. Returns an apply_edits pos (it inserts
    at pos+1) or None."""
    blocks = [cfg.block_of(l) for l in site_lines]
    if any(b is None for b in blocks):
        return None
    doms = [cfg.dom.get(b['label'], set()) for b in blocks]
    common = set.intersection(*doms) if doms else set()
    if not common:
        return None
    starts = {b['label']: b['start'] for b in cfg.blocks}
    best = max(common, key=lambda l: starts.get(l, -1))
    blk = next((b for b in cfg.blocks if b['label'] == best), None)
    if not blk or blk['end'] is None:
        return None
    # OpSelectionMerge/OpLoopMerge must stay immediately before the block's
    # branch, so the insertion point is above any merge instruction, not just
    # above the terminator.
    t = blk['end']
    while t - 1 >= blk['start'] and re.match(r'\s*Op(Selection|Loop)Merge',
                                             mod.lines[t - 1]):
        t -= 1
    pos = min(t - 1, min(site_lines) - 1)
    return pos if pos >= blk['start'] else None


def build_hair_gi(mod, cfg, sites, hair_class, knobs):
    """Anisotropy for the GI/indirect resolvers, where the module's own class
    gate dominates NO eval site (0/62 and 0/20 measured). The class is
    refetched and the tensor computed ONCE at a common dominator, then shared
    by every site -- see hoist_pos. Alpha reshape is deliberately skipped
    here: alpha definitions can precede the hoist point, and rewriting them
    against a gate that does not dominate them would be invalid."""
    from patch_shadow_brdf import find_class_fetch, class_fetch_inputs, \
                                  emit_class_value
    from patch_skin_brdf import replace_all_uses
    consts = []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    usable = [s for s in sites if P.find_site_nh(mod, s)]
    if not usable:
        die(f"{mod.name}: GI path found no site with N/H")
    pos = hoist_pos(mod, cfg, [s['line'] for s in usable])
    if pos is None:
        die(f"{mod.name}: no common dominator to hoist the tangent to")
    nctx = find_normal_gbuffer_any(mod)
    cctx = find_class_fetch(mod)
    need = class_fetch_inputs(cctx) + [nctx['x'], nctx['y'], nctx['arr']]
    bad = [x for x in need if not cfg.dominates_line(x, pos)]
    if bad:
        die(f"{mod.name}: hoist point cannot see {bad}")
    one, eps2 = C(1.0), C(1e-4)
    gl = mod.glsl
    mkn = C(knobs["m_aniso"] * knobs.get("gi_boost", 1.0))
    pex = C(knobs.get("p_aniso_gi", knobs["p_aniso"]) * 0.5)
    # GI dual-lobe knobs (wider, TRT-weighted); m_dual_gi<0 follows m_dual.
    import math
    mdg = knobs["m_dual"] if knobs.get("m_dual_gi", -1.0) < 0 else knobs["m_dual_gi"]
    md = C(mdg)
    sR = math.tan(math.radians(knobs["beta_R"]))
    sTRT = math.tan(math.radians(knobs["beta_TRT"]))
    pexRg = C(knobs.get("p_R_gi", knobs["p_R"]) * 0.5)
    pexTg = C(knobs.get("p_TRT_gi", knobs["p_TRT"]) * 0.5)
    wRc = C(knobs["wR"])
    # GI TRT weight, tinted by the transmission colour's luminance (GI sites
    # are scalar, so a per-channel tint is not possible here).
    trt_lum = 0.299 * knobs["trt_r"] + 0.587 * knobs["trt_g"] \
              + 0.114 * knobs["trt_b"]
    wTc = C(knobs.get("wTRT_gi", knobs["wTRT"]) * trt_lum)
    uid, ud = mod.uconst(hair_class)
    if ud: consts.append(ud)
    hins = []
    cls = emit_class_value(mod, cctx, hins)
    gate = mod.new_id()
    hins.append(f"        {gate} = OpIEqual %bool {cls} {uid}")
    tins, res = P.emit_aniso(mod, nctx, C, want_tangent=True)
    hins += tins
    T, aniso = res["T"], res["aniso"]
    edits = [(pos, hins)]
    n = 0
    skipped_late = []
    for st in usable:
        nh = P.find_site_nh(mod, st)
        I = mod.new_id
        outs = st['outs']
        first_out = min(mod.find_def(o)[0] for o in outs)
        # The factor block references nh (N,H) and the hoisted T/aniso. It must
        # sit before the FIRST out; nh ids must be defined there. (Per-out-at-
        # def anchoring, same fix as build_hair_spec_lobes -- last_out anchoring
        # left dead multiplies where GI out-consumers precede last_out.)
        need = list(nh['n']) + list(nh['h'])
        late = [d for d in need
                if mod.find_def(d)[0] is None or mod.find_def(d)[0] >= first_out]
        if late:
            skipped_late.append(st['line'] + 1)
            continue
        m1,m2,m3,a1,toh,t2,f_,fm,lg,ex,sv,sm1,ma,term,fac,sel = [I() for _ in range(16)]
        ins = [
            f"        {m1} = OpFMul %float {T[0]} {nh['h'][0]}",
            f"        {m2} = OpFMul %float {T[1]} {nh['h'][1]}",
            f"        {m3} = OpFMul %float {T[2]} {nh['h'][2]}",
            f"        {a1} = OpFAdd %float {m1} {m2}",
            f"        {toh} = OpFAdd %float {a1} {m3}",
            f"        {t2} = OpFMul %float {toh} {toh}",
            f"        {f_} = OpFSub %float {one} {t2}",
            f"        {fm} = OpExtInst %float {gl} NMax {f_} {eps2}",
            f"        {lg} = OpExtInst %float {gl} Log2 {fm}",
            f"        {ex} = OpFMul %float {lg} {pex}",
            f"        {sv} = OpExtInst %float {gl} Exp2 {ex}",
            f"        {sm1} = OpFSub %float {sv} {one}",
            f"        {ma} = OpFMul %float {mkn} {aniso}",
            f"        {term} = OpFMul %float {ma} {sm1}",
            f"        {fac} = OpFAdd %float {one} {term}",
        ]
        combined = fac
        # shifted dual lobes in GI (needs NoH + ToN at this site; N varies per
        # site, H per sample). Wider lobes than direct -- tight lobes across
        # many indirect samples read as noise.
        if mdg != 0.0:
            def d3(u, v):
                r1, r2, r3, s1, s2 = I(), I(), I(), I(), I()
                ins.extend([
                    f"        {r1} = OpFMul %float {u[0]} {v[0]}",
                    f"        {r2} = OpFMul %float {u[1]} {v[1]}",
                    f"        {r3} = OpFMul %float {u[2]} {v[2]}",
                    f"        {s1} = OpFAdd %float {r1} {r2}",
                    f"        {s2} = OpFAdd %float {s1} {r3}",
                ])
                return s2
            noh = d3(nh['n'], nh['h'])
            ton = d3(T, nh['n'])
            lobe_terms = []
            for s_, pexL, wL in ((sR, pexRg, wRc), (sTRT, pexTg, wTc)):
                cbase = C(1.0 + s_ * s_); cslope = C(2.0 * s_); cs = C(s_)
                b1, den2, inv, nu1, num, tpH = I(), I(), I(), I(), I(), I()
                q2, qm, qc, ql, qe, lob, wlob = I(), I(), I(), I(), I(), I(), I()
                ins += [
                    f"        {b1} = OpFMul %float {cslope} {ton}",
                    f"        {den2} = OpFAdd %float {cbase} {b1}",
                    f"        {inv} = OpExtInst %float {gl} InverseSqrt {den2}",
                    f"        {nu1} = OpFMul %float {cs} {noh}",
                    f"        {num} = OpFAdd %float {toh} {nu1}",
                    f"        {tpH} = OpFMul %float {num} {inv}",
                    f"        {q2} = OpFMul %float {tpH} {tpH}",
                    f"        {qm} = OpFSub %float {one} {q2}",
                    f"        {qc} = OpExtInst %float {gl} NMax {qm} {eps2}",
                    f"        {ql} = OpExtInst %float {gl} Log2 {qc}",
                    f"        {qe} = OpFMul %float {ql} {pexL}",
                    f"        {lob} = OpExtInst %float {gl} Exp2 {qe}",
                    f"        {wlob} = OpFMul %float {lob} {wL}",
                ]
                lobe_terms.append(wlob)
            ds, dm, dm2, df, cc = I(), I(), I(), I(), I()
            ins += [
                f"        {ds} = OpFAdd %float {lobe_terms[0]} {lobe_terms[1]}",
                f"        {dm} = OpFMul %float {md} {aniso}",
                f"        {dm2} = OpFMul %float {dm} {ds}",
                f"        {df} = OpFAdd %float {one} {dm2}",
                f"        {cc} = OpFMul %float {combined} {df}",
            ]
            combined = cc
        ins.append(f"        {sel} = OpSelect %float {gate} {combined} {one}")
        edits.append((first_out - 1, ins))
        for o in outs:
            odef = mod.find_def(o)[0]
            nid = I()
            edits.append((odef, [f"        {nid} = OpFMul %float {o} {sel}"]))
            replace_all_uses(mod, o, nid, odef)
        n += 1
    return consts, edits, {"gi_sites": n, "hoist_line": pos + 1,
                           "dual_gi": mdg != 0.0,
                           "skipped_late": skipped_late,
                           "skipped_no_nh": len(sites) - len(usable)}


def build_hair_spec_lobes(mod, cfg, dom_id, sites, gate, knobs):
    """Combined spec-lobe pass: alpha reshape + Kajiya aniso + shifted dual
    (R/TRT) lobes + sheen, applied as ONE robust per-out rewrite.

    Supersedes the split build_hairaniso + build_hair_spec for two reasons,
    both confirmed by dead-code analysis on the shipped swaps:

      * The split passes each called replace_all_uses on the SAME s['outs'].
        The aniso pass consumed them first, so the sheen pass found no uses
        left and every sheen OpSelect was silently dead. One combined pass
        computing (sheen_base) x (aniso_fac x dual_fac) has no such clobber.
      * Anchoring each rewrite at `last_out` missed out-consumers defined
        BEFORE last_out (modules that interleave out/consumer, e.g.
        out1->use, out2->use, out3->use). Anchoring each out's rewrite at its
        OWN def line (replace_all_uses after odef) catches every consumer
        regardless of layout -- this also fixes aniso applying to only some
        channels on those modules.

    The factor (aniso x dual) and the sheen `add` are computed once, in a
    block inserted immediately before the FIRST out's def, so every per-out
    multiply (inserted right after each out's def) sees them defined.

    Dual lobe (validate_dual_lobe.py): per lobe with tangent shift s=tan(beta),
        tpH  = (ToH + s*NoH) / sqrt(1 + 2*s*ToN + s^2)   == dot(norm(T+s*N), H)
        lobe = (1 - tpH^2)^(p/2)                          (Kajiya sin(T',H)^p)
        dual_fac = 1 + m_dual*aniso*(wR*L_R + wTRT*L_TRT)  (bounded additive
                   boost, ~[1, 1+m_dual*(wR+wTRT)] -- no ratio, no firefly div)
    Identity: m_aniso=0 AND m_dual=0 => combined factor == 1; k_sheen=0 =>
    sheen not emitted at all; so non-hair pixels and --vanilla are bit-exact.
    """
    from patch_skin_brdf import replace_all_uses, find_site_nh, emit_aniso
    import math
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    gl = mod.glsl
    one, zero = C(1.0), C(0.0)
    eps2 = C(1e-4)
    rep = {"alphas": [], "lobe_sites": 0, "sheen_sites": 0,
           "skipped_no_nh": 0, "skipped_no_pow5": 0, "skipped_late": []}

    s_h, a_min = C(knobs["s_h"]), C(knobs["a_min"])
    k_sheen_v = knobs["k_sheen"]
    k_sh = C(k_sheen_v)
    m_aniso_v = knobs["m_aniso"]
    mkn, pex = C(m_aniso_v), C(knobs["p_aniso"] * 0.5)
    m_dual_v = knobs["m_dual"]
    md = C(m_dual_v)
    sR = math.tan(math.radians(knobs["beta_R"]))
    sTRT = math.tan(math.radians(knobs["beta_TRT"]))
    pexR, pexT = C(knobs["p_R"] * 0.5), C(knobs["p_TRT"] * 0.5)
    wRc, wTc = C(knobs["wR"]), C(knobs["wTRT"])
    trt = [C(knobs["trt_r"]), C(knobs["trt_g"]), C(knobs["trt_b"])]
    trt_lum = C(0.299 * knobs["trt_r"] + 0.587 * knobs["trt_g"]
                + 0.114 * knobs["trt_b"])

    I = mod.new_id

    def dot3(u, v, ins):
        t1, t2, t3, s1, s2 = I(), I(), I(), I(), I()
        ins += [
            f"        {t1} = OpFMul %float {u[0]} {v[0]}",
            f"        {t2} = OpFMul %float {u[1]} {v[1]}",
            f"        {t3} = OpFMul %float {u[2]} {v[2]}",
            f"        {s1} = OpFAdd %float {t1} {t2}",
            f"        {s2} = OpFAdd %float {s1} {t3}",
        ]
        return s2

    # --- alpha reshape (2a): one per distinct alpha source, ALL uses rewritten
    # so the eval and the sampling branch agree (MIS stays unbiased).
    for alpha in sorted({s['alpha'] for s in sites},
                        key=lambda a: mod.find_def(a)[0]):
        aline, _ = mod.find_def(alpha)
        sc, cl, sel = I(), I(), I()
        replace_all_uses(mod, alpha, sel, aline)
        edits.append((aline, [
            f"        {sc} = OpFMul %float {alpha} {s_h}",
            f"        {cl} = OpExtInst %float {gl} NClamp {sc} {a_min} {one}",
            f"        {sel} = OpSelect %float {gate} {cl} {alpha}",
        ]))
        rep["alphas"].append({"alpha": alpha, "line": aline + 1, "sel": sel})

    ctx = find_normal_gbuffer_any(mod)

    usable = []
    for s in sites:
        nh = find_site_nh(mod, s)
        if not nh:
            rep["skipped_no_nh"] += 1
            continue
        outs = s['outs']
        first_out = min(mod.find_def(o)[0] for o in outs)
        # every id the factor block references must be defined before first_out
        need = list(nh['n']) + list(nh['h']) + [s['alpha'], s['vd']]
        pow5_ok = False
        if k_sheen_v != 0.0 and s['pow5']:
            pline, _ = mod.find_def(s['pow5'])
            pow5_ok = pline is not None and pline < first_out
        late = [d for d in need
                if mod.find_def(d)[0] is None or mod.find_def(d)[0] >= first_out]
        if late:
            rep["skipped_late"].append({"site": s['line'] + 1,
                                        "late": {d: mod.find_def(d)[0] for d in late}})
            continue
        do_sheen = (k_sheen_v != 0.0) and pow5_ok
        if k_sheen_v != 0.0 and not pow5_ok:
            rep["skipped_no_pow5"] += 1
        usable.append((s, nh, first_out, do_sheen))

    # Hoist the structure tensor + tangent to a common dominator. It is a
    # per-PIXEL quantity (the normal-field neighbourhood) -- identical across
    # every site -- so computing it once instead of re-emitting at each of the
    # ~14 spec sites per module saves ~5 normal fetches per site (the GI path
    # already does this). Falls back to per-site emission where no common
    # dominator sees the fetch inputs.
    T = aniso = None
    if usable:
        pos = hoist_pos(mod, cfg, [u[0]['line'] for u in usable])
        if pos is not None:
            ids = [ctx[k] for k in ('x', 'y', 'arr', 'regs', 'off', 'idx', 'lod')]
            if all(cfg.dominates_line(i, pos) for i in ids):
                tins, res = emit_aniso(mod, ctx, C, want_tangent=True)
                T, aniso = res["T"], res["aniso"]
                edits.append((pos, tins))
    hoisted = T is not None
    rep["hoisted"] = hoisted

    for s, nh, first_out, do_sheen in usable:
        outs = s['outs']
        ins = []
        if not hoisted:
            tins, res = emit_aniso(mod, ctx, C, want_tangent=True)
            T, aniso = res["T"], res["aniso"]
            ins = list(tins)
        ToH = dot3(T, nh['h'], ins)
        NoH = dot3(nh['n'], nh['h'], ins)
        ToN = dot3(T, nh['n'], ins)

        # Kajiya aniso factor: fac = 1 + m_aniso*aniso*(sin(T,H)^p_aniso - 1)
        t2, f_, fm, lg, ex, sv = I(), I(), I(), I(), I(), I()
        sm1, ma, term, fac = I(), I(), I(), I()
        ins += [
            f"        {t2} = OpFMul %float {ToH} {ToH}",
            f"        {f_} = OpFSub %float {one} {t2}",
            f"        {fm} = OpExtInst %float {gl} NMax {f_} {eps2}",
            f"        {lg} = OpExtInst %float {gl} Log2 {fm}",
            f"        {ex} = OpFMul %float {lg} {pex}",
            f"        {sv} = OpExtInst %float {gl} Exp2 {ex}",
            f"        {sm1} = OpFSub %float {sv} {one}",
            f"        {ma} = OpFMul %float {mkn} {aniso}",
            f"        {term} = OpFMul %float {ma} {sm1}",
            f"        {fac} = OpFAdd %float {one} {term}",
        ]
        combined = fac

        # shifted dual lobes (R + TRT), split so the TRT glint can be tinted
        # per channel. combined_white is the white (aniso + R-only) factor;
        # trt_gain is the scalar TRT boost the tint multiplies:
        #   factor_c = combined_white + trt_gain * tint[c]
        combined_white = combined
        trt_gain = None
        if m_dual_v != 0.0:
            lobes = []
            for s_, pexL in ((sR, pexR), (sTRT, pexT)):
                cbase = C(1.0 + s_ * s_)
                cslope = C(2.0 * s_)
                cs = C(s_)
                a1, den2, inv = I(), I(), I()
                num1, num, tpH = I(), I(), I()
                q2, qm, qc, ql, qe, lob = I(), I(), I(), I(), I(), I()
                ins += [
                    f"        {a1} = OpFMul %float {cslope} {ToN}",
                    f"        {den2} = OpFAdd %float {cbase} {a1}",
                    f"        {inv} = OpExtInst %float {gl} InverseSqrt {den2}",
                    f"        {num1} = OpFMul %float {cs} {NoH}",
                    f"        {num} = OpFAdd %float {ToH} {num1}",
                    f"        {tpH} = OpFMul %float {num} {inv}",
                    f"        {q2} = OpFMul %float {tpH} {tpH}",
                    f"        {qm} = OpFSub %float {one} {q2}",
                    f"        {qc} = OpExtInst %float {gl} NMax {qm} {eps2}",
                    f"        {ql} = OpExtInst %float {gl} Log2 {qc}",
                    f"        {qe} = OpFMul %float {ql} {pexL}",
                    f"        {lob} = OpExtInst %float {gl} Exp2 {qe}",
                ]
                lobes.append(lob)
            lR, lT = lobes[0], lobes[1]
            rgain, wgain, cw = I(), I(), I()
            cw1, cw2, tg, cwa, cwb = I(), I(), I(), I(), I()
            ins += [
                f"        {rgain} = OpFMul %float {wRc} {lR}",
                f"        {wgain} = OpFMul %float {wTc} {lT}",
                f"        {cw} = OpFMul %float {md} {aniso}",
                f"        {cw1} = OpFMul %float {cw} {rgain}",
                f"        {cw2} = OpFMul %float {cw} {wgain}",
                f"        {tg} = OpFMul %float {combined} {cw2}",
                f"        {cwa} = OpFMul %float {combined} {cw1}",
                f"        {cwb} = OpFAdd %float {combined} {cwa}",
            ]
            trt_gain = tg
            combined_white = cwb

        # sheen `add`, computed once beside the factor (only when k_sheen>0 and
        # a usable pow5 exists before first_out). add = (gate ? pow5*k_sheen:0)*vd
        add = None
        if do_sheen:
            sh, ssel, add = I(), I(), I()
            ins += [
                f"        {sh} = OpFMul %float {s['pow5']} {k_sh}",
                f"        {ssel} = OpSelect %float {gate} {sh} {zero}",
                f"        {add} = OpFMul %float {ssel} {s['vd']}",
            ]

        # factor block goes immediately before the FIRST out's def so every
        # per-out rewrite below sees sel/add defined.
        edits.append((first_out - 1, ins))

        # --- per-out rewrite, each anchored at its OWN def line, with the TRT
        # tint applied per channel (3-out sites: r/g/b; scalar sites: luminance)
        nt = len(outs)
        chans = trt if nt == 3 else [trt_lum] * nt
        for k, o in enumerate(outs):
            odef = mod.find_def(o)[0]
            pins = []
            base = o
            if do_sheen:
                a, b, c = I(), I(), I()
                pins += [
                    f"        {a} = OpFAdd %float {o} {add}",
                    f"        {b} = OpExtInst %float {gl} NMin {a} {s['vd']}",
                    f"        {c} = OpSelect %float {gate} {b} {o}",
                ]
                base = c
            fac_c = combined_white
            if trt_gain is not None:
                ft, fa = I(), I()
                pins += [
                    f"        {ft} = OpFMul %float {trt_gain} {chans[k]}",
                    f"        {fa} = OpFAdd %float {combined_white} {ft}",
                ]
                fac_c = fa
            sc, n = I(), I()
            pins += [
                f"        {sc} = OpSelect %float {gate} {fac_c} {one}",
                f"        {n} = OpFMul %float {base} {sc}",
            ]
            edits.append((odef, pins))
            replace_all_uses(mod, o, n, odef)
        rep["lobe_sites"] += 1
        if do_sheen:
            rep["sheen_sites"] += 1
    return consts, edits, rep


def build_hunt_writes(mod, cfg, writes, classes):
    """Palette tint per material class at every image write (gate refetched
    only if the module's own gate does not dominate -- same policy as
    patch_compute_brdf.build_skinmark, but with the full palette)."""
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one = C(1.0)
    shift, _ = P.find_class_shift(mod)
    palette, legend = [], []
    for n in classes:
        if n not in HUNT_PALETTE:
            die(f"class {n} has no palette entry")
        name, rgb = HUNT_PALETTE[n]
        uid, ud = mod.uconst(n)
        if ud:
            consts.append(ud)
        palette.append((uid, [C(x) for x in rgb]))
        legend.append({"class": n, "colour": name})
    from patch_shadow_brdf import find_class_fetch, class_fetch_inputs, \
                                  emit_class_value
    ctx = None
    done, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append(w['line'] + 1)
            continue
        ins = []
        cls = shift
        # Same fallback policy as build_skinmark: when the module's own class
        # value cannot reach the write, refetch it there.
        if not cfg.dominates_line(shift, w['line']):
            if ctx is None:
                ctx = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line'])
                   for x in class_fetch_inputs(ctx)):
                skipped.append(w['line'] + 1)
                continue
            cls = emit_class_value(mod, ctx, ins)
        gates = []
        for uid, rgb in palette:
            g = mod.new_id()
            ins.append(f"        {g} = OpIEqual %bool {cls} {uid}")
            gates.append((g, rgb))
        newc = []
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                s = mod.new_id()
                ins.append(f"        {s} = OpSelect %float {g} {rgb[ch]} {cur}")
                cur = s
            n_ = mod.new_id()
            ins.append(f"        {n_} = OpFMul %float {w['comps'][ch]} {cur}")
            newc.append(n_)
        nt = mod.new_id()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die(f"{mod.name}: no image write reachable for the hunt")
    return consts, edits, {"legend": legend, "writes": done, "skipped": skipped}


def process(path, outdir, tier, knobs, hair_class, hunt_classes, do_rt=True,
            with_tier1=False):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    cfg = CFG(mod)
    rep = dict(module=mod.name, ident=mod.ident, tier=tier)
    if problems:
        rep['module_warnings'] = problems

    if tier == 'hairhunt':
        writes = find_image_writes(mod)
        consts, edits, rep['hunt'] = build_hunt_writes(
            mod, cfg, writes, hunt_classes or HUNT_DEFAULT)
    elif tier == 'hair':
        if hair_class is None:
            die("--hair-class N required (run --tier hairhunt first)")
        shift, ins_line, pre_ins, consts, dom_id = acquire_class_shift(mod)
        uid, ud = mod.uconst(hair_class)
        gate = mod.new_id()
        if ud:
            consts.append(ud)
        gate_ins = pre_ins + [f"        {gate} = OpIEqual %bool {shift} {uid}"]
        skin_gate = None
        if with_tier1:
            u1, ud1 = mod.uconst(1)
            if ud1:
                consts.append(ud1)
            skin_gate = mod.new_id()
            gate_ins.append(f"        {skin_gate} = OpIEqual %bool {shift} {u1}")
        # Inserted directly after the class value (the module's own IEqual, or
        # our own shift emitted after the shared texel's extract in the
        # &31-variant modules) so the gates inherit that line's dominance.
        edits = [(ins_line, gate_ins)]
        sites = P.find_ggx_sites(mod)
        if not sites:
            die(f"{mod.name}: no GGX sites")
        # Sites the gate cannot reach are skipped, not fatal -- a couple of
        # modules keep one GGX eval outside the material-classified path.
        und = [s['line'] + 1 for s in sites
               if not cfg.dominates_line(dom_id, s['line'])]
        dominated = [s for s in sites if cfg.dominates_line(dom_id, s['line'])]
        if not dominated:
            # GI/indirect resolvers: the class gate reaches no eval site, but
            # the class is refetchable at all of them. Hoisted path.
            cG, eG, rep['gi'] = build_hair_gi(mod, cfg, sites, hair_class, knobs)
            apply_edits(mod, consts + cG, edits + eG)
            return _emit(mod, outdir, target_env, rep)
        sites = dominated
        rep.update(hair_class=hair_class, gate=gate, ggx_sites=len(sites),
                   ungated_sites=und)
        # Combined spec-lobe pass (alpha reshape + aniso + shifted dual lobes
        # + sheen) in ONE robust per-out-at-def rewrite. Replaces the old
        # split build_hairaniso + build_hair_spec, which clobbered each other
        # (sheen was dead) and missed interleaved out-consumers.
        cS, eS, rep['lobes'] = build_hair_spec_lobes(
            mod, cfg, dom_id, sites, gate, knobs)
        consts += cS
        edits += eS
        c3, e3, rep['diffuse'] = build_skin_c1(
            mod, cfg, dom_id, skin_gate, knobs, hair_gate=gate)
        consts += c3
        edits += e3
        rep['params'] = {k: knobs[k] for k in
                         ('s_h', 'a_min', 'k_sheen', 'm_aniso', 'p_aniso',
                          'm_dual', 'beta_R', 'beta_TRT', 'p_R', 'p_TRT',
                          'wR', 'wTRT', 'trt_r', 'trt_g', 'trt_b')}
    else:
        die(f"unknown tier {tier}")

    apply_edits(mod, consts, edits)
    return _emit(mod, outdir, target_env, rep)


def _emit(mod, outdir, target_env, rep):
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv_out], capture_output=True, text=True)
    rep['spirv_val'] = 'clean' if v.returncode == 0 else 'FAIL'
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        # Remove the invalid output: a failed module must not leave a stale
        # .spv behind for the install step to pick up.
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--tier', choices=['hairhunt', 'hair'], required=True)
    ap.add_argument('--hair-class', type=int, default=None, metavar='N')
    ap.add_argument('--classes', default=None)
    ap.add_argument('--with-tier1', action='store_true',
                    help='also apply the Callisto tier-1 skin c1 (class 1) at '
                         'the Disney diffuse sites, like the reference '
                         "patcher's --with-tier1")
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--vanilla', action='store_true',
                    help='identity params (regression)')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    a = ap.parse_args()

    knobs = dict(VANILLA if a.vanilla else KNOBS)
    if not a.vanilla:
        # compute-resolve hair defaults: stronger and deeper than the raygen
        # era's timid numbers -- the user could barely see 0.7/16.
        knobs.update(m_aniso=1.8, p_aniso=24.0, k_sheen=0.5, s_h=0.40,
                     w_wrap=0.45, k_diff=0.45,
                     # GI lobe: wider (many samples -> a tight lobe reads as
                     # noise) but boosted, since ambient is where hair reads
                     # most ungrounded.
                     gi_boost=1.6, p_aniso_gi=10.0,
                     # shifted dual-lobe (R + TRT) ON by default; m_dual=0
                     # (--set m_dual=0, or --vanilla) is the identity.
                     m_dual=1.0)
    for kv in a.set:
        k, v = kv.split('=')
        if k in knobs and k != 'tint':
            knobs[k] = float(v)
        else:
            die(f"unknown knob {k}")
    hunt = [int(x) for x in a.classes.split(',')] if a.classes else None

    reports = [process(p, a.outdir, a.tier, knobs, a.hair_class, hunt,
                       do_rt=not a.no_roundtrip_check,
                       with_tier1=a.with_tier1) for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
