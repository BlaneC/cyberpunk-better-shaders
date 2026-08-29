#!/usr/bin/env python3
"""Callisto SKIN BRDF on the GLCompute resolve shaders.

This is the confirmed-visible surface: the compute resolvers are where the
shipped tier-1 skin c1 already proves itself on screen, and where the Tier-3
skin gloss lives (handoff/27-SKIN-SPECULAR.md).

Tiers:
  --tier skin       Callisto skin, gated on material class 1:
                      c1   tier-1 diffuse Fresnel x retroreflection at every
                           Disney-diffuse scalar (the shipping feature)
                      + --with-skinspec: the Tier-3 gloss --
                           F' = min(f0 + g*saturate(2-r)*(1-f0)*(1-VoH)^(5r), 1)
                           with r = 2(1-n_s), plus a GGX roughness ceiling
                           alpha' = min(alpha, alpha_max).
                      Identity at n_s=0.5, g=1, alpha_max>=1 -- and the
                      identity build emits NOTHING (byte-exact), because this
                      pow is Log2/Exp2 and would not be bit-equal to the
                      shader's own multiply chain.
  --tier hunt       10-class colour palette: identify a material class by eye.
  --tier tint       force one flat colour into every image write (smoke test).

HISTORY -- this file replaces dev/patch_compute_hair.py (deleted 2026-08-28).
That patcher carried the hair BRDF net (Kajiya-Kay anisotropy, shifted dual
R/TRT lobes, sheen, diffuse wrap, and the GI variants) alongside the skin
work, because the hair effects were the reason the compute surface was found
at all. The hair net was never shown to change a pixel in 70 modules of
trying (19-STATUS.md), while the skin tiers it shared a file with are the
features that ship -- so the hair half was removed and the skin half kept.

What that buys, beyond less code: the skin gloss used to ride the hair
overlay, which meant it could only be switched on together with an
unconfirmed hair BRDF, and `hair=off` silently disabled the shipping c1 too.
Skin now owns its own overlay (swaps.skin) and its own switch.

The pieces below are carried over verbatim from the hair patcher, where they
were verified: the class-gate machinery (find_class_anchor_variant /
acquire_class_shift, four G-buffer read idioms), find_c1_sites, build_skin_c1,
the Fresnel group finder and the Tier-3 splice. The roughness ceiling is the
one part that was rewritten: it used to compose into the hair pass's alpha
reshape, and is now standalone (build_skin_alpha_cap).
"""
import argparse, itertools, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import (apply_edits, roundtrip_check, die,
                             KNOBS, VANILLA, HUNT_PALETTE, HUNT_DEFAULT)
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG
from patch_compute_brdf import find_image_writes, detect_target_env


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
            # Two low-bit idioms anchor the same material fetch:
            #   & 31          -- the local-light family reads the sub-field
            #   & 4294967264  -- mask-compare idiom: (y & ~31) == K is exactly
            #                    (y >> 5) == K, the class test without a shift
            if any(re.match(r'\s*%\d+\s*=\s*OpBitwiseAnd %uint '
                            + re.escape(eid) + r' %uint_(?:31|4294967264)\s*$', l2)
                   for l2 in mod.lines):
                return eid, j
    # Fourth idiom: the class word arrives via a buffer OpLoad + OpBitcast,
    # not an OpImageFetch, so the fetch-anchored scan above never sees it.
    # Anchor directly on the mask-compare: any extract masked with ~31 IS a
    # class test; dxil-spirv may also have lifted it through an OpPhi.
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*%\d+\s*=\s*OpBitwiseAnd %uint (%\d+) %uint_4294967264\s*$', ln)
        if not m:
            continue
        ex = m.group(1)
        _, exd = mod.find_def(ex)
        # component 0 or 1: the material word rides .y in the fetch family
        # doc 11 read, but at least one class-gated module (8e5618efab94b955,
        # gate == 5<<5) masks component 0 of its own fetch.
        if not re.match(r'OpCompositeExtract %uint %\d+ [01]\s*$', exd or ''):
            mp = re.match(r'OpPhi %uint((?:\s+%\w+)+)\s*$', exd or '')
            if mp:
                for op in mp.group(1).split():
                    _, od = mod.find_def(op)
                    if re.match(r'OpCompositeExtract %uint %\d+ [01]\s*$', od or ''):
                        ex, exd = op, od
                        break
        if re.match(r'OpCompositeExtract %uint %\d+ [01]\s*$', exd or ''):
            eline, _ = mod.find_def(ex)
            return ex, eline
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


def build_skin_c1(mod, cfg, dom_id, skin_gate, knobs):
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
        ins.append(f"        {out} = OpFMul %float {s['scalar']} {fac}")
        replace_all_uses(mod, s['scalar'], out, s['line'])
        edits.append((s['line'], ins))
        rep["c1_sites"] += 1
    return consts, edits, rep


def find_spec_fresnel_groups(mod):
    """Every specular Schlick Fresnel in a resolve module, both shipped idioms.

    Verified on the dispatching evaluators before writing (2e73a32c35778d85,
    4d46848998312027, 9a3fa53c53a3a21b, 20e6c7b3626ae0d6):

      M (multiply chain, the common form):
          x    = OpFSub 1 VoH;  x2 = x*x;  x4 = x2*x2;  p = x4*x
          xp_c = OpFMul p X_c            (X_c = 1-f0_c, e.g. 0.96 - <albedoTerm>)
          F_c  = OpFAdd xp_c f0_c        (f0_c, e.g. <albedoTerm> + 0.04)
      S (spherical-gaussian fit, opposite algebra):
          q    = OpFMul (OpFSub -6.98316002 (VoH*5.55472994)) VoH
          p    = OpExtInst Exp2 q        (= (1-VoH)^5)
          om   = OpFSub 1 p
          fm_c = OpFMul om f0_c
          F_c  = OpFAdd fm_c p           (F = f0*(1-p) + p -- same Schlick)

    The Disney diffuse FD computes the same pow5 shape but assembles as
    FAdd(xp, 1): its "f0" is the constant 1.0, which no real specular F0 ever
    is (skin is 0.04 + albedo contribution). That pair is the discriminator
    -- groups whose f0 is the constant 1.0 are rejected. Without this guard
    the FD terms would be spliced as Fresnels and the sheen would land on the
    diffuse too.
    """
    defs = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*)$', ln)
        if m:
            defs[m.group(1)] = (i, m.group(2))
    mul = re.compile(r'OpFMul %float (%\w+) (%\w+)$')
    fadd = re.compile(r'OpFAdd %float (%\w+) (%\w+)$')
    groups, seen_f = [], set()

    def add_group(pow5, voh, chans):
        chans = [c for c in chans if c['F'] not in seen_f]
        if chans:
            seen_f.update(c['F'] for c in chans)
            groups.append(dict(pow5=pow5, voh=voh, chans=chans))

    # --- form M: p = x4*x on the FSub(1, t) base
    for x5, (i, d) in sorted(defs.items(), key=lambda kv: kv[1][0]):
        m = mul.match(d)
        if not m:
            continue
        x4, x = m.groups()
        m4 = mul.match(defs.get(x4, (0, ''))[1] or '')
        if not m4 or m4.group(1) != m4.group(2):
            continue
        m2 = mul.match(defs.get(m4.group(1), (0, ''))[1] or '')
        if not m2 or m2.group(1) != m2.group(2):
            continue
        if x not in (m2.group(1), m2.group(2)):
            continue
        ms = re.match(r'OpFSub %float %float_1 (%\w+)$',
                      defs.get(x, (0, ''))[1] or '')
        if not ms:
            continue
        chans = []
        for xp, (j, d2) in sorted(defs.items(), key=lambda kv: kv[1][0]):
            if j <= i:
                continue
            mx = mul.match(d2)
            if not mx or x5 not in mx.groups():
                continue
            xc = mx.group(2) if mx.group(1) == x5 else mx.group(1)
            for fc, (k, d3) in sorted(defs.items(), key=lambda kv: kv[1][0]):
                ma = fadd.match(d3)
                if k <= j or not ma or xp not in ma.groups():
                    continue
                f0 = ma.group(2) if ma.group(1) == xp else ma.group(1)
                if re.match(r'OpConstant %float 1(?:\.0)?\s*$',
                            defs.get(f0, (0, ''))[1] or ''):
                    break   # diffuse FD: f0 == 1 -- not a specular Fresnel
                chans.append(dict(F=fc, f0=f0, X=xc))
                break
        add_group(x5, ms.group(1), chans)

    # --- form S: SG-fit Exp2 with the f0*(1-p) + p algebra
    for p, (i, d) in sorted(defs.items(), key=lambda kv: kv[1][0]):
        me = re.match(r'OpExtInst %float %\w+ Exp2 (%\w+)$', d)
        if not me:
            continue
        mq = mul.match(defs.get(me.group(1), (0, ''))[1] or '')
        if not mq:
            continue
        a, b = mq.groups()
        if not re.match(r'OpFSub %float %float_n6_98316002 %\w+\s*$',
                        defs.get(a, (0, ''))[1] or ''):
            continue
        voh = b
        om = None
        for cand, (j, d2) in defs.items():
            if j > i and re.match(r'OpFSub %float %float_1 '
                                  + re.escape(p) + r'\s*$', d2):
                om = cand
                break
        if om is None:
            continue
        chans = []
        for fm, (j, d2) in sorted(defs.items(), key=lambda kv: kv[1][0]):
            if j <= i:
                continue
            mx = mul.match(d2)
            if not mx or om not in mx.groups():
                continue
            f0 = mx.group(2) if mx.group(1) == om else mx.group(1)
            for fc, (k, d3) in sorted(defs.items(), key=lambda kv: kv[1][0]):
                ma = fadd.match(d3)
                if k <= j or not ma or fm not in ma.groups() or p not in ma.groups():
                    continue
                if re.match(r'OpConstant %float 1(?:\.0)?\s*$',
                            defs.get(f0, (0, ''))[1] or ''):
                    continue
                chans.append(dict(F=fc, f0=f0, X=None))
                break
        add_group(p, voh, chans)

    groups.sort(key=lambda g: min(mod.find_def(c['F'])[0] for c in g['chans']))
    return groups


def skin_spec_active(knobs):
    """Tier-3 emission gate: identity knobs must emit NOTHING (bit-exact)."""
    return (abs(knobs.get("n_s", 0.5) - 0.5) > 1e-9
            or abs(knobs.get("spec_gain", 1.0) - 1.0) > 1e-9
            or knobs.get("alpha_max", 1.0) < 1.0)


def build_skin_spec(mod, cfg, dom_id, skin_gate, knobs):
    """Callisto Tier-3: skin-gated specular Fresnel reshape ("wet look").

        r     = 2(1 - n_s)
        F'    = f0 + g * saturate(2 - r) * (1 - f0) * (1 - VoH)^(5r)

    (callisto_brdf_over_lambert.md 3.2/5.5). Identity is n_s=0.5, g=1 -- but
    the identity build must emit NOTHING at all, not identity math: the pow
    here is Log2/Exp2 and is not bit-equal to the shader's own multiply
    chain, so --vanilla (and any build without --with-skinspec) stays
    byte-exact by skipping emission entirely (skin_spec_active gates it).

    The rewrite replaces every USE of each channel's Schlick F_c with
    select(skin_gate, F', F_c) -- the alpha-reshape pattern, not the
    spec-out pattern -- so it reaches every consumer regardless of how the
    module assembles F*D*Vis (2e73 multiplies a pre-clamped scalar by F_c;
    the 0170-style modules fold F_c into the per-channel outs), and it
    composes with the hair pass's per-out rewrite instead of fighting it:
    the two passes touch disjoint ids (F_c vs the vd-consumers), so the
    hair factor and the skin Fresnel multiply cleanly.

    Roughness ceiling (alpha_max) is NOT handled here -- it rides the hair
    pass's alpha reshape, which already rewrites every alpha use.
    """
    from patch_skin_brdf import replace_all_uses
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    gl = mod.glsl
    one, zero = C(1.0), C(0.0)
    eps = C(1e-4)
    n_s = knobs["n_s"]
    r = 2.0 * (1.0 - n_s)
    e5r = C(5.0 * r)
    c2mr = C(2.0 - r)
    g = C(knobs["spec_gain"])

    groups = find_spec_fresnel_groups(mod)
    rep = {"groups": len(groups), "chans": 0, "form_m": 0, "form_s": 0,
           "skipped_dom": [], "skipped_shape": 0}
    I = mod.new_id
    for grp in groups:
        chans = []
        for c in grp['chans']:
            fline, _ = mod.find_def(c['F'])
            if fline is None or not cfg.dominates_line(dom_id, fline):
                rep["skipped_dom"].append(c['F'])
                continue
            f0line, _ = mod.find_def(c['f0'])
            if f0line is None or f0line >= fline:
                rep["skipped_shape"] += 1
                continue
            chans.append((c, fline))
        if not chans:
            continue
        rep["form_s" if grp['chans'][0]['X'] is None else "form_m"] += 1

        # Shared per group: pr = (1-VoH)^(5r), amp = g * saturate(2-r).
        # Emitted with the FIRST channel's pins so every later channel (whose
        # F def sorts after) sees it defined -- everything the block reads
        # (voh) feeds pow5, which feeds xp, which feeds F, so it is live at
        # every rewrite point by construction.
        sv, b, bm, l, xe, pr, s2r, amp = [I() for _ in range(8)]
        shared = [
            f"        {sv} = OpExtInst %float {gl} NClamp {grp['voh']} {zero} {one}",
            f"        {b} = OpFSub %float {one} {sv}",
            f"        {bm} = OpExtInst %float {gl} NMax {b} {eps}",
            f"        {l} = OpExtInst %float {gl} Log2 {bm}",
            f"        {xe} = OpFMul %float {l} {e5r}",
            f"        {pr} = OpExtInst %float {gl} Exp2 {xe}",
            f"        {s2r} = OpExtInst %float {gl} NClamp {c2mr} {zero} {one}",
            f"        {amp} = OpFMul %float {s2r} {g}",
        ]
        first = True
        for c, fline in chans:
            X = c['X']
            pins = list(shared) if first else []
            first = False
            if X is None:
                xid = I()
                pins.append(f"        {xid} = OpFSub %float {one} {c['f0']}")
                X = xid
            t1, t2, fp, fc, sel = I(), I(), I(), I(), I()
            pins += [
                f"        {t1} = OpFMul %float {X} {pr}",
                f"        {t2} = OpFMul %float {t1} {amp}",
                f"        {fp} = OpFAdd %float {c['f0']} {t2}",
                # Fresnel reflectance is physically <= 1. Inert at the
                # spec_gain=1 default (F' peaks at exactly f0+(1-f0)=1), but
                # the knob is meant to be pushed -- "exaggerate first" -- and
                # g=2 would otherwise return 1.96, i.e. a grazing-angle
                # energy gain that reads as white fireflies on cheeks and
                # nose rather than gloss. fp >= f0 >= 0 already, so the
                # upper bound alone is enough.
                f"        {fc} = OpExtInst %float {gl} NMin {fp} {one}",
                f"        {sel} = OpSelect %float {skin_gate} {fc} {c['F']}",
            ]
            edits.append((fline, pins))
            replace_all_uses(mod, c['F'], sel, fline)
            rep["chans"] += 1
    return consts, edits, rep


def build_skin_alpha_cap(mod, cfg, dom_id, skin_gate, knobs):
    """Callisto Tier-3 roughness ceiling: alpha' = min(alpha, alpha_max) on skin.

    Skin's authored roughness maps sit around 0.4-0.6, and a GGX lobe that
    wide reads as a dull sheen rather than a wet highlight. Capping alpha is
    what actually produces the oily look -- the Fresnel reshape in
    build_skin_spec only broadens the falloff, and its saturate(2-r) amplitude
    term is clamped to 1 across the whole n_s > 0.5 direction, so with
    spec_gain at its 1.0 default this cap is the dominant lever.

    ALL uses of each alpha are rewritten, not just the eval's, so the
    evaluation and the importance-sampling branch agree -- otherwise MIS is
    biased. (In the hair patcher this rode that pass's own alpha reshape; a
    second replace_all_uses on the same id would have clobbered the first,
    which is the 08-DUAL-LOBE dead-sheen lesson.)

    Identity at alpha_max >= 1: emits nothing at all, keeping such builds
    byte-exact.
    """
    from patch_skin_brdf import replace_all_uses
    consts, edits = [], []
    rep = {"alphas": [], "skipped_dom": []}
    smax_v = knobs.get('alpha_max', 1.0)
    if smax_v >= 1.0 or skin_gate is None:
        rep['inactive'] = 'alpha_max >= 1 -- nothing emitted'
        return consts, edits, rep

    sites = P.find_ggx_sites(mod)
    if not sites:
        rep['inactive'] = 'no GGX sites'
        return consts, edits, rep

    smax, c = mod.const(smax_v)
    if c:
        consts.append(c)
    gl = mod.glsl
    I = mod.new_id
    for alpha in sorted({s['alpha'] for s in sites},
                        key=lambda a: mod.find_def(a)[0]):
        aline, _ = mod.find_def(alpha)
        if aline is None or not cfg.dominates_line(dom_id, aline):
            rep["skipped_dom"].append(alpha)
            continue
        mn, sel = I(), I()
        replace_all_uses(mod, alpha, sel, aline)
        edits.append((aline, [
            f"        {mn} = OpExtInst %float {gl} NMin {alpha} {smax}",
            f"        {sel} = OpSelect %float {skin_gate} {mn} {alpha}",
        ]))
        rep["alphas"].append({"alpha": alpha, "line": aline + 1, "sel": sel})
    return consts, edits, rep


def build_tint_writes(mod, cfg, writes, rgb):
    """Unconditional constant tint at every image write.

    The palette tier (build_hunt_writes) needs a material-class read so it can
    colour by class; that requirement is what made 149 of the 178 dispatched
    modules unpatchable (`15-RENDER-GRAPH.md` 3).  For a tile-classified
    permutation none of that is needed: the module is *dispatched* only for the
    tiles it owns, so an unconditional multiply on its output paints exactly
    those tiles and nothing else -- dispatch is the gate.

    No class fetch, no dominance test (constants dominate everything), so this
    tier patches any module that has a reconstructable v4float image write.
    """
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    tids = [C(x) for x in rgb]
    done, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({"line": w['line'] + 1,
                            "why": "texel not a v4 construct"})
            continue
        ins, newc = [], []
        for ch in range(3):
            n_ = mod.new_id()
            ins.append(f"        {n_} = OpFMul %float {w['comps'][ch]} "
                       f"{tids[ch]}")
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
        die(f"{mod.name}: no image write reachable for the tint")
    return consts, edits, {"tint": list(rgb), "writes": done,
                           "skipped": skipped}

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
    # acquire_class_shift (not find_class_shift): the &31 and mask-compare
    # variants have no `y >> 5` of their own; the fallback emits one after the
    # shared texel's extract and we splice it in here.
    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((ins_line, pre_ins))
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
        # Same fallback policy as build_skinmark: when the class value cannot
        # reach the write, refetch it there. Test dominance on the anchor id
        # (the module's own shift, or the extract in the fallback variants) --
        # the pending shift has no def in the module yet and would be treated
        # as always-dominating.
        if not cfg.dominates_line(dom_id, w['line']):
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


# =====================================================================
# Tier-4: skin transmission (ear/nose backlight).  handoff/29.
#
# WHY IT CANNOT GO WHERE THE OTHER SKIN PASSES GO.  c1 and the Tier-3 gloss
# splice inside the per-light lighting arm.  That whole arm -- in every
# evaluator inspected -- sits under a runtime gate of the form
#
#       %s   = NClamp(cbv.y + shadowMaskTexel, 0, 1)      ; the sun shadow
#       %g   = (dot(lightCol,lightCol) * %s) > 0
#       OpBranchConditional %g <lighting> <merge>
#
# so when the surface is shadowed the arm does not execute and its outputs
# phi in as zero.  A backlit ear IS shadowed at the front face -- that is
# what "the light is behind it" means -- so a transmission term spliced into
# the arm would be multiplied by zero at exactly the pixels it exists for.
# That is the single likeliest way this feature ships as a silent no-op and
# gets written off as "the splice does not work" (the handoff/27 7.5 failure
# class, one layer deeper).
#
# So Tier-4 splices at the LIGHT-GATE MERGE instead: the predecessor of the
# block holding the diffuse OpImageWrite, which is reached whether or not the
# light arm ran.  Everything it needs is either defined above the gate (the
# normal, the view vector, the albedo, the light colour, the shadow scalar,
# the material class) or re-emitted from the module's own uniform access
# chain (the light direction, which is loaded inside the gate).
#
# It also lands UPSTREAM of the module's own output scale and its NMin
# clamp, which is what GOTCHAS' "scale before a clamp, never after" asks for
# -- the term cannot push the fp16 store to inf.
#
# THE MATHS (Barre-Brisebois & Bouchard, GDC 2011, "Approximating
# Translucency" -- the form every shipping engine uses):
#
#       H     = normalize(L + N*distortion)
#       back  = saturate(-dot(V, H)) ^ power
#       mask  = lerp(1, 1-S,      shadow_w)      ; S = the sun shadow scalar
#             * lerp(1, blockMask, blocker_w)    ; the engine's light blocker
#       T     = back * thickness * mask
#       out_c += lightCol_c * lerp(1, albedo_c, albedo_w) * tint_c * T
#
# `mask` is the part that is not in the textbook and is the whole reason this
# can be more than a uniform wax glow:
#
#   (1-S) is "this pixel is in shadow", which is TRUE on a backlit ear and
#   FALSE on a sunlit forehead -- so it suppresses the term exactly where
#   the surface is directly lit and the effect would be wrong.
#
#   blockMask is the engine's own CharacterLightBlockers term, re-derived
#   here rather than read (the value the shader computes is inside the gate).
#   It is nonzero only when the character's own blocker volume says the sun
#   is on the far side, so it separates "in my own head's shadow" from "in a
#   building's shadow" -- which no purely local term can do.  Its product
#   with (1-S) is the closest thing to a thickness signal available without
#   binding the engine's skin back-depth target (handoff/29 A4 route 3).
#
# thickness is a build constant.  There is no per-pixel thickness at this
# site: GBuffer3.w is fully allocated (bit 7 a flag, bit 6 a skin-profile
# bit, bits 0-5 the light-blocker intensity), which is the skin case of
# handoff/11 2's "no free channel".
#
# IDENTITY: thickness = 0 emits nothing at all, so a Tier-4-off build is
# byte-identical to one built without the pass.

TRANS_CONE = "-0.258819044"      # cos(105 deg): the light-blocker cone
TRANS_RAMP = "-2.23071027"       # its 1/(1-cos) ramp


def _zero_const(tok):
    return tok in ("%float_0", "%float_n0", "%float_0_0")


def _is_const(tok):
    return tok.startswith("%float_") or tok.startswith("%uint_") or \
           tok.startswith("%int_")


def unwind_output_scrub(mod, cid, max_hops=12):
    """Unwind one written channel back toward its accumulator.

    Every evaluator ends the same way -- scale, NaN-scrub through a double
    negation, clamp:

        v = OpFMul acc S ; w = 0-v ; z = NMin(w,0) ; y = 0-z
        x = NMax(y,0)    ; c = NMin(x, 65000)

    Walks back through NMin/NMax-against-a-constant and FSub-from-zero and
    stops at the first instruction that is neither.  Written loosely on
    purpose: the clamp constants differ between permutations, and GOTCHAS 4
    says to anchor on the mode-independent half of a signature.
    """
    cur = cid
    for _ in range(max_hops):
        _, d = mod.find_def(cur)
        if not d:
            return cur
        m = re.match(r'OpExtInst %float %\w+ (NMin|NMax) (%\w+) (%\w+)\s*$', d)
        if m:
            a, b = m.group(2), m.group(3)
            if _is_const(a) and not _is_const(b):
                cur = b; continue
            if _is_const(b) and not _is_const(a):
                cur = a; continue
            return cur
        m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', d)
        if m and _zero_const(m.group(1)):
            cur = m.group(2); continue
        return cur
    return cur


def find_radiance_writes(mod):
    """Every OpImageWrite whose three colour channels scrub back to a shared
    accumulator triple.  Returns [dict(line, img, accs, scale)].

    The scale is identified as the operand the three channels' final FMul
    have in common -- it is the pass's own output multiplier, and being able
    to name it is what proves the three channels really are one triple and
    not three unrelated values.
    """
    out = []
    for w in find_image_writes(mod):
        if not w["comps"]:
            continue
        ends = [unwind_output_scrub(mod, c) for c in w["comps"][:3]]
        defs = [mod.find_def(e)[1] or "" for e in ends]
        muls = [re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d) for d in defs]
        accs, scale = None, None
        if all(muls):
            ops = [set(m.groups()) for m in muls]
            common = ops[0] & ops[1] & ops[2]
            if len(common) == 1:
                scale = next(iter(common))
                accs = [next(iter(o - {scale})) for o in ops]
        if accs is None:
            accs, scale = ends, None
        out.append(dict(line=w["line"], img=w["img"], accs=accs, scale=scale,
                        texel_line=w["texel_line"]))
    return out


def _back_reachable(mod, start, targets, max_nodes=4000):
    """Is any id in `targets` reachable walking definitions backwards?"""
    seen, stack = set(), list(start)
    while stack and len(seen) < max_nodes:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in targets:
            return True
        _, d = mod.find_def(cur)
        if not d or d.startswith("OpImage") or d.startswith("OpLoad"):
            continue
        stack += [t for t in re.findall(r'%\w+', d)
                  if t not in seen and not _is_const(t)]
    return False


def dot_operand_triples(mod, cos_id, unwrap):
    """From a clamped cosine, recover the two v3 operand component triples.

    `unwrap` walks off the clamp: 'nclamp' for NClamp(x,0,1), 'eps' for the
    NMin(NMax(x,1e-5),1) pair the NoV sites use.  Returns (a3, b3, dot_id, raw)
    where raw is the unclamped OpDot result -- the value that still carries
    the sign, i.e. the one that knows the light is BEHIND the surface.
    """
    cur = cos_id
    for _ in range(3):
        _, d = mod.find_def(cur)
        if not d:
            return None
        m = re.match(r'OpExtInst %float %\w+ (NClamp|NMin|NMax) (%\w+)', d)
        if m:
            cur = m.group(2); continue
        break
    _, d = mod.find_def(cur)
    m = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', d or "")
    if not m:
        return None
    trip = []
    for cid in m.groups():
        _, cd = mod.find_def(cid)
        cm = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      cd or "")
        if not cm:
            return None
        trip.append(tuple(cm.groups()))
    return trip[0], trip[1], cur


def vectors_from_c1_site(mod, site):
    """N, V and L as component triples, recovered from a c1 site's two dots.

    The site hands back NoL and NoV; each is a clamp over an OpDot over two
    OpCompositeConstructs.  The triple that appears in BOTH dots is the
    normal -- comparison is on the component ids, not the composite ids,
    because dxil-spirv rebuilds the vector at every use.
    """
    a = dot_operand_triples(mod, site["nol"], "nclamp")
    b = dot_operand_triples(mod, site["nov"], "eps")
    if not a or not b:
        return None
    (a0, a1, raw_nol), (b0, b1, _) = a, b
    for n in (a0, a1):
        for m in (b0, b1):
            if n == m:
                L = a1 if n == a0 else a0
                V = b1 if m == b0 else b0
                return dict(N=n, L=L, V=V, raw_nol=raw_nol)
    return None


def _flatten_product(mod, root, max_leaves=64):
    """Leaves of a chain of OpFMul, multiplicities kept.

    dxil-spirv associates the per-channel diffuse product differently in
    different permutations -- ((c*a)*NoL)*fd here, (c*a)*(fd*NoL) there, and
    the shadow folded into the colour in a third.  Matching a fixed nesting
    is what made the first cut of this detector miss 33 of 84 libs.  The
    factors themselves are the same set in every permutation, so flatten and
    compare sets: that is the mode-independent half of the signature
    (GOTCHAS 4).
    """
    out, stack = [], [root]
    while stack and len(out) < max_leaves:
        cur = stack.pop()
        _, d = mod.find_def(cur)
        m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d or "")
        if m:
            stack += list(m.groups())
        else:
            out.append(cur)
    return out


def _vec_source(mod, comps, want, max_nodes=1200):
    """Do these three scalars come from components 0,1,2 of one v4 value?

    `want` is 'uniform' (an OpLoad through an OpAccessChain -- a constant
    buffer slot) or 'image' (an OpImageFetch/Read/Sample -- a G-buffer
    texel).  This is both the identification AND the ordering check: leaf i
    must be component i of the SAME source, so a decomposition that
    recovered the channels out of order is rejected rather than silently
    tinting the term wrong.

    Every matching source is collected before deciding, never just the first
    one reached.  The diffuse albedo is basecolour*(1-metalness), so walking
    back from its red channel reaches component 0 of the basecolour texel
    AND component 0 of the metal/roughness texel; stopping at whichever the
    traversal happened to pop first made this disagree with the green and
    blue channels and reject a perfectly good albedo.  Intersecting the
    three channels' candidate sets is what picks the basecolour out.

    Returns the access-chain instruction text for 'uniform' (so the load can
    be reissued at a splice point) or the source id for 'image'.
    """
    per, texts = [], {}
    for i, c in enumerate(comps):
        found, seen, stack = set(), set(), [c]
        while stack and len(seen) < max_nodes:
            cur = stack.pop()
            if cur in seen or _is_const(cur):
                continue
            seen.add(cur)
            _, d = mod.find_def(cur)
            if not d:
                continue
            m = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', d)
            if m and int(m.group(2)) == i:
                src = m.group(1)
                _, sd = mod.find_def(src)
                sd = sd or ""
                if want == 'uniform':
                    lm = re.match(r'OpLoad %v4float (%\w+)\s*$', sd)
                    if lm:
                        _, ad = mod.find_def(lm.group(1))
                        if ad and ad.startswith("OpAccessChain"):
                            found.add(src)
                            texts[src] = ad
                elif sd.startswith("OpImage"):
                    found.add(src)
                    texts[src] = src
            stack += [t for t in re.findall(r'%\w+', d) if t not in seen]
        if not found:
            return None
        per.append(found)
    shared = per[0] & per[1] & per[2]
    return texts[sorted(shared)[0]] if len(shared) == 1 else None


def _pick_triple(mod, cands, want):
    """Choose one leaf per channel forming a v4 of the requested kind."""
    for combo in itertools.product(*cands):
        if len(set(combo)) != 3:
            continue
        src = _vec_source(mod, list(combo), want)
        if src:
            return list(combo), src
    return None, None


def _looks_like_shadow(mod, sid):
    """NClamp(bias + <a texel>, 0, 1) -- the sun shadow mask's signature.

    The bias comes from a constant buffer and the texel from the ray-traced
    shadow target, so the FAdd of a uniform and an image read under a 0..1
    clamp is the shape.  Only used to enrich the mask; a module where it is
    not found still gets a transmission term.
    """
    _, d = mod.find_def(sid)
    m = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 %float_1\s*$',
                 d or "")
    if not m:
        return False
    _, ad = mod.find_def(m.group(1))
    am = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', ad or "")
    if not am:
        return False
    for side in am.groups():
        seen, stack = set(), [side]
        while stack and len(seen) < 40:
            cur = stack.pop()
            if cur in seen or _is_const(cur):
                continue
            seen.add(cur)
            _, dd = mod.find_def(cur)
            if not dd:
                continue
            if dd.startswith("OpImage"):
                return True
            stack += re.findall(r'%\w+', dd)
    return False


def light_terms_from_c1_site(mod, site):
    """Split the per-channel diffuse product into light colour and albedo.

    The diffuse scalar is used exactly three times, once per channel.  Each
    use flattens to a set of factors; the intersection of the three is the
    shared part (NoL, the shadow, the scalar itself) and what is left over
    is per-channel -- the light colour and the surface albedo.  They are
    told apart by where they come from rather than by position: the colour
    is a constant-buffer load, the albedo a G-buffer texel.

    Returns dict(colour, colour_src, albedo, albedo_src, common, shadow).
    albedo may be None -- some permutations fold it in earlier -- in which
    case the albedo weight has nothing to apply and is dropped.
    """
    uses = [j for j in uses_of(mod, site["scalar"]) if "= OpFMul" in mod.lines[j]]
    if len(uses) != 3:
        return None
    chans = []
    for j in uses:
        lhs = re.match(r'\s*(%\w+)\s*=', mod.lines[j]).group(1)
        chans.append(set(_flatten_product(mod, lhs)))
    common = chans[0] & chans[1] & chans[2]
    uniq = [sorted(c - common) for c in chans]
    if not all(uniq):
        return None
    colour, csrc = _pick_triple(mod, uniq, 'uniform')
    if not colour:
        return None
    rest = [[x for x in u if x not in colour] for u in uniq]
    albedo, asrc = (None, None)
    if all(rest):
        albedo, asrc = _pick_triple(mod, rest, 'image')
    shadow = next((c for c in sorted(common) if _looks_like_shadow(mod, c)), None)
    return dict(colour=colour, colour_src=csrc, albedo=albedo,
                albedo_src=asrc, common=sorted(common), shadow=shadow)


def uniform_source_of(mod, comps):
    """The constant-buffer access chain three scalars come from, or None.

    Needed because the light direction is loaded inside the runtime light
    gate, so its ids do not dominate the splice point -- but the access
    chain's own operands are a module-scope variable and constants, so
    reissuing the load anywhere is always legal.
    """
    ad = _vec_source(mod, list(comps), 'uniform')
    return dict(access=ad, load_type='%v4float') if ad else None


def find_light_blocker(mod):
    """The engine's CharacterLightBlockers term, as inputs rather than as a
    value.

    Shape, from the class-1 arm of the clustered evaluators:

        d = OpDot   blockerDir  L
        a = OpFAdd  d           +cos(105)
        r = OpFMul  a           -1/(1-cos(105))
        k = NClamp  r  0 1                       <- "sun is behind me", 0..1
        m = OpFMul  k           blockerIntensity <- GBuffer3.w bits 0-5
        b = OpFSub  1           m                <- what the engine SUBTRACTS

    Anchored on the ramp constant, which is the mode-independent half of the
    signature (GOTCHAS 4): the direction and intensity ids differ between
    class arms and permutations, the constant does not.  The value `b` is
    computed inside the light gate and so does not dominate the splice
    point -- this returns the INPUTS, for recomputation, not `b`.

    Of the dot's two operands, the light direction is the one that traces
    back to a uniform load; the blocker direction is the one that does not,
    because it is decoded from a G-buffer texel.  A module with no light
    blockers is not an error -- the mask degrades to 1.
    """
    ramp = mod.fconst.get(P.f32(float(TRANS_RAMP)))
    if not ramp:
        return None
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) '
                     + re.escape(ramp) + r'\s*$', ln)
        if not m:
            continue
        ramp_id, add_id = m.group(1), m.group(2)
        _, ad = mod.find_def(add_id)
        am = re.match(r'OpFAdd %float (%\w+) %\w+\s*$', ad or "")
        if not am:
            continue
        _, dd = mod.find_def(am.group(1))
        dm = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', dd or "")
        if not dm:
            continue
        trips = []
        for cid in dm.groups():
            _, cd = mod.find_def(cid)
            cm = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                          cd or "")
            trips.append(tuple(cm.groups()) if cm else None)
        if not all(trips):
            continue
        gbuf = [t for t in trips if uniform_source_of(mod, t) is None]
        if len(gbuf) != 1:
            continue
        clamp_id = None
        for l2 in mod.lines:
            mm = re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ NClamp '
                          + re.escape(ramp_id) + r' %float_0 %float_1\s*$', l2)
            if mm:
                clamp_id = mm.group(1)
                break
        if not clamp_id:
            continue
        inten = None
        for l2 in mod.lines:
            mm = re.match(r'\s*%\w+\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$', l2)
            if mm and clamp_id in mm.groups():
                inten = [g for g in mm.groups() if g != clamp_id][0]
                break
        if not inten:
            continue
        return dict(dir=gbuf[0], intensity=inten, ramp=ramp, add=add_id)
    return None


def _pre_terminator(mod, blk):
    """The apply_edits position that lands a value just before the branch.

    A block's last instruction is its terminator, but a structured block
    puts OpSelectionMerge / OpLoopMerge immediately before it, and SPIR-V
    requires that pair to stay adjacent -- inserting between them is a
    validation error ("OpSelectionMerge must be the second-to-last
    instruction in its block"), which is exactly what 47 of the anchored
    libs did on the first cut of this pass.  apply_edits inserts AFTER the
    position it is given, so return the line before the first merge.
    """
    i = blk["end"]
    while i - 1 > blk["start"]:
        head = mod.lines[i - 1].strip().split(' ')[0]
        if head in ("OpSelectionMerge", "OpLoopMerge"):
            i -= 1
            continue
        break
    return i - 1


def _after_phis(mod, blk, floor_line):
    """Where a non-phi instruction may first be inserted in a block.

    SPIR-V requires every OpPhi to sit at the top of its block, so a value
    added into a phi's result has to be defined after ALL of them, not just
    after the phi it reads (GOTCHAS: "OpPhi must be at block top").  Also
    respects `floor_line` so the point is never above a definition we need.
    """
    i = blk["start"] + 1
    last = blk["start"]
    while i < len(mod.lines) and (blk["end"] is None or i < blk["end"]):
        body = mod.lines[i].split('=', 1)[-1].strip()
        if body.startswith("OpPhi") or body.startswith("OpLine") or \
           mod.lines[i].strip().startswith("OpLine"):
            last = i
            i += 1
            continue
        break
    return max(last, floor_line)


def find_transmission_site(mod, cfg):
    """Everything Tier-4 needs, or (None, reason).

    Returns the diffuse OpImageWrite, the inputs, and a list of TARGETS --
    the places the term has to be added so that every path that produces
    light gets it.  Nothing here emits; the survey and the patcher share the
    detector so the anchor is written once, which is what makes the sibling
    sweep (GOTCHAS 3) evidence about the patch rather than about a
    second, similar-looking piece of code.

    There are two shapes, and getting the difference wrong is how this pass
    would half-work:

      * The accumulators are OpPhis at the top of the write block.  The
        write block is then reached both from the lighting path AND from an
        early-out (failed depth test / sky), and on the early-out the phi
        operand is a literal zero.  Adding the term inside the write block
        would light up the sky.  So the term is spliced into each incoming
        block that actually carries light -- identified as the ones where
        the G-buffer inputs dominate, which the early-out path by
        construction does not.

      * The accumulators are ordinary values in the write block.  Then
        there is one path, and one target: just after the block's phis.
    """
    sites, _ = find_c1_sites(mod)
    if not sites:
        return None, "no c1 sites"
    writes = find_radiance_writes(mod)
    if not writes:
        return None, "no radiance image writes"

    # Which write is the diffuse one?  The one whose accumulators reach a
    # Disney diffuse scalar walking backwards.  Naming it this way rather
    # than by slot index is what keeps the pass off the specular target.
    scalars = {s["scalar"] for s in sites}
    diff = [w for w in writes if _back_reachable(mod, w["accs"], scalars)]
    if not diff:
        return None, f"no diffuse write among {len(writes)} radiance writes"
    if len(diff) > 1:
        return None, f"{len(diff)} writes reach a diffuse scalar -- ambiguous"
    w = diff[0]

    wb = cfg.block_of(w["line"])
    if wb is None:
        return None, "write is in no basic block"

    phi_defs = []
    for a in w["accs"]:
        dl, d = mod.find_def(a)
        phi_defs.append((dl, d or ""))
    as_phis = all(d.startswith("OpPhi") and cfg.block_of(dl) is wb
                  for dl, d in phi_defs)

    for site in sites:
        vec = vectors_from_c1_site(mod, site)
        if not vec:
            continue
        lt = light_terms_from_c1_site(mod, site)
        if not lt:
            continue
        src = uniform_source_of(mod, vec["L"])
        if not src:
            continue
        # Only what the term actually reads must dominate.  The albedo and
        # the sun-shadow mask are optional enrichments, so a module that
        # hides either still gets a term -- with that weight dropped rather
        # than the whole feature skipped.
        need = list(vec["N"]) + list(vec["V"]) + lt["colour"]
        opt = dict(albedo=lt["albedo"],
                   shadow=[lt["shadow"]] if lt["shadow"] else None)

        targets, uncovered = [], []
        if as_phis:
            for b in cfg.blocks:
                if b["end"] is None or b["label"] not in cfg.reachable:
                    continue
                if wb["label"] not in (b.get("succ") or []):
                    continue
                vals = [_phi_incoming(mod, a, b["label"]) for a in w["accs"]]
                if not all(vals):
                    continue
                if all(cfg.dominates_line(x, b["end"]) for x in need):
                    targets.append(dict(pred=b["label"],
                                        line=_pre_terminator(mod, b),
                                        accs=vals,
                                        phi_lines=[d[0] for d in phi_defs]))
                elif any(not _is_const(v) for v in vals):
                    # A light-carrying edge we cannot reach: worth saying so
                    # out loud rather than shipping a term that only appears
                    # on some pixels.
                    uncovered.append(b["label"])
        else:
            floor = max(dl for dl, _ in phi_defs if dl is not None)
            line = _after_phis(mod, wb, floor)
            if all(cfg.dominates_line(x, line) for x in need):
                targets.append(dict(pred=None, line=line, accs=w["accs"]))
        if not targets:
            continue

        line0 = targets[0]["line"]
        have = {k: v for k, v in opt.items()
                if v and all(cfg.dominates_line(x, t["line"])
                             for t in targets for x in v)}
        blk = find_light_blocker(mod)
        if blk and not all(cfg.dominates_line(x, t["line"])
                           for t in targets
                           for x in list(blk["dir"]) + [blk["intensity"]]):
            blk = None
        return dict(kind="phi" if as_phis else "write", block=wb["label"],
                    line=line0, write_line=w["line"], targets=targets,
                    uncovered=uncovered, vec=vec, light=lt, lsrc=src,
                    site=site, scale=w["scale"], blocker=blk,
                    has_albedo="albedo" in have, has_shadow="shadow" in have,
                    accs=w["accs"]), None
    return None, "no splice point where the inputs dominate"


def _succs(b):
    """Successor labels, already recorded by build_blocks()."""
    return b.get("succ") or []


def _insert_line(b):
    """The line to insert a definition at: the block's terminator.

    Inserting BEFORE the terminator puts the new instructions after every
    OpPhi -- SPIR-V requires phis at block top -- and after every other
    definition in the block, so anything defined in the block is available.
    """
    return b["end"]


def _phi_incoming(mod, phi_id, pred_label):
    """The value an OpPhi takes on the edge from `pred_label`, or None."""
    _, d = mod.find_def(phi_id)
    if not d or not d.startswith("OpPhi"):
        return None
    pairs = re.findall(r'(%\w+) (%\w+)', d[len("OpPhi %float"):])
    for val, lab in pairs:
        if lab == pred_label:
            return val
    return None


def _rewrite_phi_operand(mod, phi_line, pred_label, old, new):
    """Point one incoming edge of an OpPhi at a new value.

    Only the (value, label) pair for `pred_label` is touched.  The other
    edges -- the early-out that phis in a literal zero -- keep theirs, which
    is what stops the transmission term from being added to the sky.
    """
    ln = mod.lines[phi_line]
    pat = re.compile(r'(\s)' + re.escape(old) + r'(\s+)'
                     + re.escape(pred_label) + r'(\s|$)')
    out, n = pat.subn(r'\g<1>' + new + r'\g<2>' + pred_label + r'\g<3>', ln, count=1)
    if not n:
        die(f"{mod.name}: phi edge {pred_label} -> {old} not found @line "
            f"{phi_line + 1}")
    mod.lines[phi_line] = out


def build_skin_transmission(mod, cfg, dom_id, skin_gate, knobs):
    """Tier-4: add Barre-Brisebois translucency to the skin diffuse.

    See the block comment above TRANS_CONE for why this cannot splice where
    Tier-1 and Tier-3 do.  Emitted per light-carrying edge into the diffuse
    write's accumulator phis:

        L    = normalize(cbv sun direction)          ; reissued, see lsrc
        H    = normalize(L + N * distort)
        back = saturate(-dot(V, H)) ^ power
        mask = back * thick
             * lerp(1, saturate(-dot(N, L)), wback)   ; light is behind me
             * lerp(1, 1 - shadow,           wshadow) ; and I am in shadow
             * lerp(1, blockerMask,          wblock)  ; ...my own shadow
        T_c  = lightColour_c * lerp(1, albedo_c, walbedo) * tint_c * mask
        acc_c = acc_c * lerp(1, 1 - damp, skin) + select(skin, T_c, 0)

    The lerp weights are build constants, so they are folded here: weight 0
    drops the factor entirely and weight 1 uses the term directly.  That
    keeps the emitted code proportional to what is actually switched on, and
    makes "the knob is off" and "the instruction was never emitted" the same
    thing rather than two states that can disagree.

    saturate(-dot(N, L)) is recomputed rather than read.  The site's own raw
    N.L lives inside the light gate and does not dominate the splice point --
    the whole reason this pass exists is that the gate is closed exactly
    where the effect belongs.
    """
    from patch_skin_brdf import replace_all_uses
    thick = float(knobs.get('t_thick', 0.0))
    damp = float(knobs.get('t_damp', 0.0))
    if thick <= 0.0:
        return [], [], dict(inactive='t_thick=0 -- nothing emitted')
    if not any(ln.strip().startswith('%v3float =') or ' %v3float ' in ln
               for ln in mod.lines):
        return [], [], dict(skipped='module has no %v3float type')

    site, why = find_transmission_site(mod, cfg)
    if not site:
        return [], [], dict(skipped=why)
    if not cfg.dominates_line(dom_id, site['line']):
        return [], [], dict(skipped='class value does not dominate the splice')

    gl, consts = mod.glsl, []

    def C(v):
        i, d = mod.const(v)
        if d:
            consts.append(d)
        return i

    one, zero = C(1.0), C(0.0)
    eps = C(1e-6)
    c_thick, c_pow, c_dist = C(thick), C(knobs['t_power']), C(knobs['t_distort'])
    c_tint = [C(knobs['t_r']), C(knobs['t_g']), C(knobs['t_b'])]
    c_damp = C(1.0 - damp) if damp > 0.0 else None
    lt, vec = site['light'], site['vec']
    blocker = site['blocker']
    w_back = float(knobs['t_wback'])
    w_shad = float(knobs['t_wshadow']) if site['has_shadow'] else 0.0
    w_blk = float(knobs['t_wblock']) if blocker else 0.0
    w_alb = float(knobs['t_walbedo']) if site['has_albedo'] else 0.0

    def mix1(ins, x, w):
        """lerp(1, x, w), folded at build time; None means "factor is 1"."""
        if w <= 0.0:
            return None
        if w >= 1.0:
            return x
        d, m, r = mod.new_id(), mod.new_id(), mod.new_id()
        ins += [f"        {d} = OpFSub %float {x} {one}",
                f"        {m} = OpFMul %float {d} {C(w)}",
                f"        {r} = OpFAdd %float {one} {m}"]
        return r

    def mul(ins, acc, f):
        """Multiply, unless the factor is the identity.

        Same principle as the folded lerp weights: a knob left at its
        identity value emits no instruction at all, so "the knob is off" and
        "there is nothing there" cannot end up as two different states.
        """
        if f is None or f == one:
            return acc
        r = mod.new_id()
        ins.append(f"        {r} = OpFMul %float {acc} {f}")
        return r

    edits = []
    for tgt in site['targets']:
        I = mod.new_id
        ac, ld, lx, ly, lz, lv, ln_ = [I() for _ in range(7)]
        nv, vv, nd, hs, hn, dvh, ndvh, sat = [I() for _ in range(8)]
        be, lg, pm, bk = [I() for _ in range(4)]
        ins = [
            # The sun direction is loaded inside the light gate, so its ids
            # do not dominate here; the access chain's operands are module
            # scope, so reissuing the load is always legal.
            f"        {ac} = {site['lsrc']['access']}",
            f"        {ld} = OpLoad %v4float {ac}",
            f"        {lx} = OpCompositeExtract %float {ld} 0",
            f"        {ly} = OpCompositeExtract %float {ld} 1",
            f"        {lz} = OpCompositeExtract %float {ld} 2",
            f"        {lv} = OpCompositeConstruct %v3float {lx} {ly} {lz}",
            # the constant buffer holds .w = angular size, and the arm
            # renormalises the xyz itself, so do the same rather than assume
            f"        {ln_} = OpExtInst %v3float {gl} Normalize {lv}",
            f"        {nv} = OpCompositeConstruct %v3float "
            f"{vec['N'][0]} {vec['N'][1]} {vec['N'][2]}",
            f"        {vv} = OpCompositeConstruct %v3float "
            f"{vec['V'][0]} {vec['V'][1]} {vec['V'][2]}",
            f"        {nd} = OpVectorTimesScalar %v3float {nv} {c_dist}",
            f"        {hs} = OpFAdd %v3float {ln_} {nd}",
            f"        {hn} = OpExtInst %v3float {gl} Normalize {hs}",
            f"        {dvh} = OpDot %float {vv} {hn}",
            f"        {ndvh} = OpFNegate %float {dvh}",
            f"        {sat} = OpExtInst %float {gl} NClamp {ndvh} {zero} {one}",
            # pow() as exp2(p*log2(x)) with an eps floor -- the same idiom
            # Tier-1 uses, and the reason the base is clamped: log2(0) is -inf
            f"        {be} = OpExtInst %float {gl} NMax {sat} {eps}",
            f"        {lg} = OpExtInst %float {gl} Log2 {be}",
            f"        {pm} = OpFMul %float {lg} {c_pow}",
            f"        {bk} = OpExtInst %float {gl} Exp2 {pm}",
        ]
        t = mul(ins, bk, c_thick)

        if w_back > 0.0:
            rnl, nrl, bf = I(), I(), I()
            ins += [f"        {rnl} = OpDot %float {nv} {ln_}",
                    f"        {nrl} = OpFNegate %float {rnl}",
                    f"        {bf} = OpExtInst %float {gl} NClamp {nrl} "
                    f"{zero} {one}"]
            t = mul(ins, t, mix1(ins, bf, w_back))

        if w_shad > 0.0:
            inv = I()
            ins.append(f"        {inv} = OpFSub %float {one} {lt['shadow']}")
            t = mul(ins, t, mix1(ins, inv, w_shad))

        if w_blk > 0.0:
            bv, bd, ba, br, bc, bm = [I() for _ in range(6)]
            ins += [
                f"        {bv} = OpCompositeConstruct %v3float "
                f"{blocker['dir'][0]} {blocker['dir'][1]} {blocker['dir'][2]}",
                f"        {bd} = OpDot %float {bv} {ln_}",
                f"        {ba} = OpFAdd %float {bd} {C(-float(TRANS_CONE))}",
                f"        {br} = OpFMul %float {ba} {C(float(TRANS_RAMP))}",
                f"        {bc} = OpExtInst %float {gl} NClamp {br} {zero} {one}",
                f"        {bm} = OpFMul %float {bc} {blocker['intensity']}",
            ]
            t = mul(ins, t, mix1(ins, bm, w_blk))

        for c in range(3):
            p = I()
            ins.append(f"        {p} = OpFMul %float {lt['colour'][c]} {t}")
            if w_alb > 0.0:
                p = mul(ins, p, mix1(ins, lt['albedo'][c], w_alb))
            p = mul(ins, p, c_tint[c])
            g, out = I(), I()
            ins.append(f"        {g} = OpSelect %float {skin_gate} {p} {zero}"
                       if skin_gate is not None else
                       f"        {g} = OpFMul %float {p} {one}")
            base = tgt['accs'][c]
            if c_damp is not None and skin_gate is not None:
                dsel, dmul = I(), I()
                ins += [f"        {dsel} = OpSelect %float {skin_gate} "
                        f"{c_damp} {one}",
                        f"        {dmul} = OpFMul %float {base} {dsel}"]
                base = dmul
            ins.append(f"        {out} = OpFAdd %float {base} {g}")
            if tgt['pred'] is not None:
                _rewrite_phi_operand(mod, tgt['phi_lines'][c], tgt['pred'],
                                     tgt['accs'][c], out)
            else:
                replace_all_uses(mod, tgt['accs'][c], out, tgt['line'])
        edits.append((tgt['line'], ins))

    rep = dict(targets=len(site['targets']), block=site['block'],
               write_line=site['write_line'] + 1,
               albedo=bool(w_alb), shadow=bool(w_shad),
               blocker=bool(w_blk), blocker_present=bool(blocker),
               uncovered=site['uncovered'],
               params={k: knobs[k] for k in
                       ('t_thick', 't_power', 't_distort', 't_r', 't_g', 't_b',
                        't_wback', 't_wshadow', 't_wblock', 't_walbedo',
                        't_damp')})
    return consts, edits, rep


def process(path, outdir, tier, knobs, hunt_classes, do_rt=True,
            tint=None, with_skinspec=False, with_translucency=False):
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

    if tier == 'tint':
        writes = find_image_writes(mod)
        consts, edits, rep['tint'] = build_tint_writes(
            mod, cfg, writes, tint or (1.0, 0.25, 0.25))
    elif tier == 'hunt':
        writes = find_image_writes(mod)
        consts, edits, rep['hunt'] = build_hunt_writes(
            mod, cfg, writes, hunt_classes or HUNT_DEFAULT)
    elif tier == 'skin':
        # The skin class gate (class 1). Unlike the hair patcher there is no
        # second class to acquire, so the gate machinery runs once and the
        # module's own class value is reused by every pass below.
        shift, ins_line, pre_ins, consts, dom_id = acquire_class_shift(mod)
        u1, ud1 = mod.uconst(1)
        if ud1:
            consts.append(ud1)
        skin_gate = mod.new_id()
        # Inserted directly after the class value (the module's own IEqual, or
        # our own shift emitted after the shared texel's extract in the
        # &31-variant modules) so the gate inherits that line's dominance.
        edits = [(ins_line, pre_ins
                  + [f"        {skin_gate} = OpIEqual %bool {shift} {u1}"])]

        # Tier-4 transmission runs FIRST, and the order is load-bearing.
        #
        # Its detector identifies the diffuse image write by walking the write
        # backwards to a Disney diffuse scalar. build_skin_c1() rewrites every
        # use of that scalar to point at a NEW id whose defining instruction
        # is still sitting in `edits` and has not been spliced into mod.lines
        # yet -- so once c1 has run, the backwards walk dead-ends on an id
        # with no definition and the diffuse write cannot be found. The
        # failure is silent: the pass reports "no diffuse write" and emits
        # nothing, which from the chair is indistinguishable from the feature
        # not working.
        #
        # Running it first also protects its own output: the later passes use
        # replace_all_uses(), which only ever touches mod.lines, and Tier-4's
        # instructions live in `edits` until apply_edits() splices them in.
        #
        # Emission order does not change the dataflow either way -- c1 scales
        # the diffuse scalar inside the product chain that feeds the
        # accumulator, and Tier-4 adds to that accumulator afterwards.
        if with_translucency:
            cT, eT, rep['translucency'] = build_skin_transmission(
                mod, cfg, dom_id, skin_gate, knobs)
            consts += cT
            edits += eT

        c1, e1, rep['diffuse'] = build_skin_c1(mod, cfg, dom_id, skin_gate, knobs)
        consts += c1
        edits += e1

        # Tier-3 gloss. The roughness cap runs FIRST: it rewrites every use of
        # each alpha, while the Fresnel pass rewrites the Schlick F ids. The
        # two touch disjoint ids, so they compose rather than clobber.
        if with_skinspec and skin_spec_active(knobs):
            cA, eA, rep['alpha_cap'] = build_skin_alpha_cap(
                mod, cfg, dom_id, skin_gate, knobs)
            consts += cA
            edits += eA
            cS, eS, rep['skin_spec'] = build_skin_spec(
                mod, cfg, dom_id, skin_gate, knobs)
            consts += cS
            edits += eS
        elif with_skinspec:
            rep['skin_spec'] = {'inactive': 'identity knobs -- nothing emitted'}

        rep['params'] = {k: knobs[k] for k in
                         ('rho_f', 'rho_r', 'n_f', 'm_f', 'n_r', 'm_r',
                          'n_s', 'spec_gain', 'alpha_max')}
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--tier', default='skin', choices=('skin', 'hunt', 'tint'))
    ap.add_argument('--with-skinspec', action='store_true',
                    help='add the Callisto tier-3 skin gloss: Schlick Fresnel '
                         'reshape (n_s, spec_gain) + roughness ceiling '
                         '(alpha_max). Without this flag those knobs are '
                         'forced to identity and nothing is emitted, so the '
                         'build stays byte-exact against a c1-only build.')
    ap.add_argument('--with-translucency', action='store_true',
                    help='add the Callisto tier-4 skin transmission: light '
                         'through thin skin (ears, nose, nostrils) where the '
                         'sun is behind the surface. Without this flag '
                         't_thick is forced to 0 and nothing is emitted, so '
                         'the build stays byte-exact against a build from '
                         'before the pass existed.')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--vanilla', action='store_true',
                    help='identity params (regression)')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    ap.add_argument('--hunt-classes', default='',
                    help='comma-separated class ids for --tier hunt')
    ap.add_argument('--tint', default='',
                    help='r,g,b for --tier tint')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()

    knobs = dict(VANILLA if a.vanilla else KNOBS)
    if not a.vanilla and not a.with_translucency:
        # Same rule as Tier-3: the knob is inert without its flag, so a build
        # without it is byte-exact against a pre-Tier-4 one.
        knobs.update(t_thick=0.0, t_damp=0.0)
    if not a.vanilla and not a.with_skinspec:
        # Tier-3 knobs are inert without the flag: force identity so a plain
        # c1 build is byte-exact against a pre-Tier-3 one.
        knobs.update(n_s=0.5, spec_gain=1.0, alpha_max=1.0)
    for kv in a.set:
        k, v = kv.split('=')
        if k in knobs and k != 'tint':
            knobs[k] = float(v)
        else:
            die(f"unknown knob {k}")
    hunt = [int(x) for x in a.hunt_classes.split(',') if x.strip()] or None
    tint = None
    if a.tint:
        parts = [float(x) for x in a.tint.split(',')]
        if len(parts) != 3:
            die("--tint needs r,g,b")
        tint = tuple(parts)

    reports = [process(p, a.outdir, a.tier, knobs, hunt,
                       do_rt=not a.no_roundtrip_check,
                       tint=tint, with_skinspec=a.with_skinspec,
                       with_translucency=a.with_translucency)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
