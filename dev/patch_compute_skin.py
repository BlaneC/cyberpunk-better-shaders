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


def splice_lines(mod):
    """Every line this patcher would splice at, across all three passes.

    Used only to SCORE a class-gate anchor (lift_class_gate). The three
    finders are pure, so calling them here and again in the build passes
    costs time and nothing else.
    """
    lines = [s['line'] for s in find_c1_sites(mod)[0]]
    for g in find_spec_fresnel_groups(mod):
        for c in g['chans']:
            fl, _ = mod.find_def(c['F'])
            if fl is not None:
                lines.append(fl)
    for s in P.find_ggx_sites(mod):
        if s['alpha_line'] is not None:
            lines.append(s['alpha_line'])
    return lines


def find_class_phis(mod, seed):
    """The OpPhi %uint ids that forward `seed`'s class value across a merge.

    dxil-spirv guards the material fetch behind a bounds test and merges the
    class out of it:  `%329 = OpPhi %uint %uint_0 <skipped> %330 <fetched>`.
    Below that merge the SHIFT (%330) dominates nothing, while the phi
    dominates everything -- and the shader's own class tests read the phi, not
    the shift (99bb7c2698997b2a: `%5297 = OpIEqual %bool %329 %uint_1`).

    Every operand must be a known class value or a uint constant. A phi that
    mixed in an unrelated uint would give a gate firing on something that is
    not the material class, which is the silent-wrong-pixel failure this
    repo's gates exist to avoid.
    """
    known, out = {seed}, []
    pat = re.compile(r'\s*(%\d+)\s*=\s*OpPhi %uint((?:\s+%\w+)+)\s*$')
    changed = True
    while changed:
        changed = False
        for i, ln in enumerate(mod.lines):
            m = pat.match(ln)
            if not m or m.group(1) in known:
                continue
            vals = m.group(2).split()[0::2]
            if not any(v in known for v in vals):
                continue
            if not all(v in known or re.match(r'%uint_\d+$', v) for v in vals):
                continue
            known.add(m.group(1))
            out.append((m.group(1), i))
            changed = True
    return out


def lift_class_gate(mod, cfg, acquired):
    """Move the gate anchor onto a class value that reaches the splice sites.

    The anchor find_class_shift returns is the module's own `y >> 5`, and in
    the two GI resolvers that shift sits INSIDE the bounds-guarded block that
    fetched it -- so it dominates none of the shading below the merge, every
    site is rejected as skipped_dom, and the module is patched with zero
    sites while still being counted as "patched" and while its bytes still
    differ (the constants are emitted regardless). That is how
    99bb7c2698997b2a -- the one module handoff/10 proved dispatches DIRECTLY,
    the coarse indirect-bounce resolve -- shipped with 144 Fresnel channels,
    62 alphas and 12 c1 sites all silently skipped: the whole skin BRDF was
    direct-light-only.

    Only a STRICT improvement replaces the anchor, so every module whose own
    shift already dominates keeps its old anchor line byte-for-byte (the
    69220ed5e0ca675f lesson in find_class_shift: moving a working anchor
    broke it).
    """
    shift, ins_line, pre_ins, consts, dom_id = acquired
    if mod.find_def(dom_id)[0] is None:
        return acquired          # pending id (variant path): no phi can name it
    sites = splice_lines(mod)
    if not sites:
        return acquired
    best_n = sum(1 for ln in sites if cfg.dominates_line(dom_id, ln))
    if best_n == len(sites):
        return acquired
    best = None
    for pid, pline in find_class_phis(mod, dom_id):
        n = sum(1 for ln in sites if cfg.dominates_line(pid, ln))
        if n > best_n:
            best_n, best = n, (pid, pline)
    if best is None:
        return acquired
    pid, pline = best
    # OpPhi must stay first in its block, so the gate goes after the last one.
    j = pline
    while (j + 1 < len(mod.lines)
           and re.match(r'\s*%\d+\s*=\s*OpPhi\b', mod.lines[j + 1])):
        j += 1
    return pid, j, [], consts, pid


def acquire_class_shift(mod, cfg=None):
    """The `y >> 5` material class value and the line to insert gates after.

    Prefers the module's own shift (find_class_shift); in the &31-only variant
    modules, emits our own shift from the shared texel. With `cfg`, the result
    is then lifted onto the phi that carries the class past its guard when the
    shift itself does not reach the splice sites (lift_class_gate). Returns
    (shift_id, insert_line, extra_instructions, extra_consts, dominance_id).
    """
    try:
        shift, ieq_line = P.find_class_shift(mod)
        acquired = (shift, ieq_line, [], [], shift)
    except SystemExit:
        eid, eline = find_class_anchor_variant(mod)
        u5, ud = mod.uconst(5)
        shift = mod.new_id()
        ins = [f"        {shift} = OpShiftRightLogical %uint {eid} {u5}"]
        # dominance must be tested on an id that exists in the module TODAY --
        # the extract the new shift reads -- not on the pending new id (which
        # find_def cannot see and would be treated as module-scope, i.e. always
        # dominating).
        acquired = (shift, eline, ins, ([ud] if ud else []), eid)
    return acquired if cfg is None else lift_class_gate(mod, cfg, acquired)


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


def _fmul_consumers(mod, idt, ops=('OpFMul',)):
    """(result, other_operand) for every FMul/FAdd that reads idt."""
    from patch_chs_brdf import uses_of
    out = []
    for j in uses_of(mod, idt):
        m = re.match(r'\s*(%\d+)\s*=\s*(OpFMul|OpFAdd) %float (%\w+) (%\w+)',
                     mod.lines[j])
        if m and m.group(2) in ops:
            out.append((m.group(1), m.group(4) if m.group(3) == idt
                        else m.group(3)))
    return out


def _is_diffuse_colour(mod, idt):
    """albedo*(1-metal) as dxil-spirv emits it: OpFSub(X, OpFMul(X, M)),
    optionally behind the material-fetch guard's OpPhi(%float_0, D)."""
    _, d = mod.find_def(idt)
    mp = re.match(r'OpPhi %float((?:\s+%\w+)+)\s*$', d or '')
    if mp:
        vals = [v for v in mp.group(1).split()[0::2] if v != '%float_0']
        if len(set(vals)) != 1:
            return False
        _, d = mod.find_def(vals[0])
    m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', d or '')
    if not m:
        return False
    X, Y = m.groups()
    _, dy = mod.find_def(Y)
    my = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', dy or '')
    return bool(my and X in my.groups())


def find_diffuse_colour(mod, cfg, site):
    """The per-channel diffuse colour (albedo*(1-metal)) a c1 site feeds.

    The shared scalar fans out three ways (one FMul per channel, sometimes
    after one or two single-consumer FMul/FAdd hops); each branch multiplies
    a chain that contains the channel's diffuse colour. Walk the three
    operand trees in lock-step and take the first depth at which all three
    are distinct _is_diffuse_colour ids that dominate the site. None when
    the site's fan-out multiplies by light*shadow only (25 of 181 sites in
    the 2026-08-30 census: albedo is folded in upstream, out of reach) --
    the caller reports and skips, never guesses. Pure: rewrites nothing, so
    it is safe to run before any pass splices (GOTCHAS 12).
    """
    cur = site['scalar']
    cons = None
    for _ in range(4):
        c3 = _fmul_consumers(mod, cur)
        if len(c3) == 3:
            cons = c3
            break
        c1 = _fmul_consumers(mod, cur, ('OpFMul', 'OpFAdd'))
        if len(c1) != 1:
            break
        cur = c1[0][0]
    if not cons:
        return None

    def expand(idt, depth):
        out = [idt]
        if depth:
            _, d = mod.find_def(idt)
            m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d or '')
            if m:
                for op in m.groups():
                    out += expand(op, depth - 1)
        return out
    trees = [expand(c[1], 4) for c in cons]
    for k in range(min(len(t) for t in trees)):
        trip = [t[k] for t in trees]
        if len(set(trip)) == 3 and all(_is_diffuse_colour(mod, x) for x in trip) \
                and all(cfg.dominates_line(x, site['line']) for x in trip):
            return trip
    return None


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
    # 44 M4/M5. Both ride the c1 select so every site still gets exactly ONE
    # replace_all_uses on its scalar (a second call on the same id is a
    # silent dead no-op -- the 08-DUAL-LOBE lesson). Identity (0) emits
    # nothing, keeping the shipping rungs byte-exact.
    dcouple = knobs.get("dcouple", 0.0)
    micro_k = knobs.get("micro_k", 0.0)
    if dcouple > 0.0:
        five, sc = C(5.0), C(dcouple)
        rep["dcouple_sites"] = 0
    if micro_k > 0.0:
        # Detect BEFORE emitting anything: the detector reads the module's
        # own use lists, which the replace_all_uses below rewrites.
        albedo = {s['line']: find_diffuse_colour(mod, cfg, s) for s in sites}
        zero, two = C(0.0), C(2.0)
        mk = C(micro_k)
        wr, wg, wb = C(0.2126), C(0.7152), C(0.0722)
        rep["micro_sites"], rep["micro_skipped"] = 0, []
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
        if dcouple > 0.0:
            # Normalised Ashikhmin-Shirley coupling, f0-independent form:
            # (1 - s(1-NoL)^5)(1 - s(1-NoV)^5). (1-NoL)^5 = Exp2(5*l1), and
            # l1/l2 already exist above for c1.
            q1, q2, p5l, p5v, sl, sv, fl, fv, cp, gd = [I() for _ in range(10)]
            ins += [
                f"        {q1} = OpFMul %float {l1} {five}",
                f"        {q2} = OpFMul %float {l2} {five}",
                f"        {p5l} = OpExtInst %float {gl} Exp2 {q1}",
                f"        {p5v} = OpExtInst %float {gl} Exp2 {q2}",
                f"        {sl} = OpFMul %float {p5l} {sc}",
                f"        {sv} = OpFMul %float {p5v} {sc}",
                f"        {fl} = OpFSub %float {one} {sl}",
                f"        {fv} = OpFSub %float {one} {sv}",
                f"        {cp} = OpFMul %float {fl} {fv}",
                f"        {gd} = OpSelect %float {skin_gate} {cp} {one}",
            ]
            m2 = I()
            ins.append(f"        {m2} = OpFMul %float {fac} {gd}")
            fac = m2
            rep["dcouple_sites"] += 1
        if micro_k > 0.0:
            trip = albedo.get(s['line'])
            if trip is None:
                rep["micro_skipped"].append(s['line'] + 1)
            else:
                # sat(1 - (1-NoL)^2 * k * (1 - lum(albedo))): dark, porous
                # skin self-shadows at grazing light; a pale, smooth patch
                # does not. lum = Rec.709 weights on the linear diffuse
                # colour (already albedo*(1-metal); metal is 0 on skin).
                Dr, Dg, Db = trip
                lr, lg, lb, la, lum, lc, dk, sq, t1, t2, ms, cl, gm, m3 = \
                    [I() for _ in range(14)]
                ins += [
                    f"        {lr} = OpFMul %float {Dr} {wr}",
                    f"        {lg} = OpFMul %float {Dg} {wg}",
                    f"        {lb} = OpFMul %float {Db} {wb}",
                    f"        {la} = OpFAdd %float {lr} {lg}",
                    f"        {lum} = OpFAdd %float {la} {lb}",
                    f"        {lc} = OpExtInst %float {gl} NClamp {lum} {zero} {one}",
                    f"        {dk} = OpFSub %float {one} {lc}",
                    f"        {sq} = OpFMul %float {onl} {onl}",
                    f"        {t1} = OpFMul %float {sq} {mk}",
                    f"        {t2} = OpFMul %float {t1} {dk}",
                    f"        {ms} = OpFSub %float {one} {t2}",
                    f"        {cl} = OpExtInst %float {gl} NClamp {ms} {zero} {one}",
                    f"        {gm} = OpSelect %float {skin_gate} {cl} {one}",
                    f"        {m3} = OpFMul %float {fac} {gm}",
                ]
                fac = m3
                rep["micro_sites"] += 1
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


def skin_fresnel_active(knobs):
    """Tier-3 Fresnel emission gate: identity knobs must emit NOTHING."""
    return (abs(knobs.get("n_s", 0.5) - 0.5) > 1e-9
            or abs(knobs.get("spec_gain", 1.0) - 1.0) > 1e-9)


def alpha_reshape_active(knobs):
    """Any of the three alpha edits (skin cap, skin scale, eye cap) live?"""
    return (knobs.get("alpha_max", 1.0) < 1.0
            or abs(knobs.get("alpha_scale", 1.0) - 1.0) > 1e-9
            or knobs.get("eye_alpha_max", 1.0) < 1.0)


def skin_spec_active(knobs):
    """Tier-3 emission gate (kept for callers): Fresnel OR alpha reshape."""
    return skin_fresnel_active(knobs) or alpha_reshape_active(knobs)


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


def build_skin_alpha_cap(mod, cfg, dom_id, skin_gate, knobs, eye_gate=None):
    """Per-class GGX alpha reshape, ONE nested select per alpha id:

        a_skin = min(min(alpha*alpha_scale, 1), alpha_max)   (class 1)
        a_eye  = min(alpha, eye_alpha_max)                    (class 8)
        alpha' = select(skin, a_skin, select(eye, a_eye, alpha))

    Each factor is emitted only when its knob is non-identity, and in the
    original cap-only case the instruction sequence and id order are exactly
    what this pass emitted before 44 (verified: the five shipping rungs
    rebuild byte-identical), so the refactor is provably inert.

    Why a cap at all: skin's authored roughness sits around 0.4-0.6 and a
    GGX lobe that wide reads as a dull sheen, not a wet highlight -- the cap
    is what produces the oily look, the Fresnel reshape only widens the
    falloff. Why a SCALE as well (33 s5, 43 M2): the cap flattens every skin
    pixel above the ceiling to one roughness, killing the authored pore /
    forehead / cheek variation; a multiplier moves the whole distribution
    while keeping it. Eyes (31 s5, 43 M6): a cornea is a wet glass surface
    the authored maps never get below ~0.3 roughness; a class-8 ceiling is
    the whole "wet eyes" feature.

    ALL uses of each alpha are rewritten so the evaluation and the
    importance-sampling branch agree (else MIS is biased). A second
    replace_all_uses on the same id would silently no-op -- the 08-DUAL-LOBE
    lesson -- which is exactly why the three edits share one select chain.
    """
    from patch_skin_brdf import replace_all_uses
    consts, edits = [], []
    rep = {"alphas": [], "skipped_dom": []}
    smax_v = knobs.get('alpha_max', 1.0)
    scale_v = knobs.get('alpha_scale', 1.0)
    emax_v = knobs.get('eye_alpha_max', 1.0)
    do_cap = smax_v < 1.0 and skin_gate is not None
    do_scale = abs(scale_v - 1.0) > 1e-9 and skin_gate is not None
    do_eye = emax_v < 1.0 and eye_gate is not None
    if not (do_cap or do_scale or do_eye):
        rep['inactive'] = 'identity alpha knobs -- nothing emitted'
        return consts, edits, rep

    sites = P.find_ggx_sites(mod)
    if not sites:
        rep['inactive'] = 'no GGX sites'
        return consts, edits, rep

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid
    # Constant declaration order is part of the byte-exactness contract:
    # the legacy cap declared smax first.
    smax = C(smax_v) if do_cap else None
    scale = C(scale_v) if do_scale else None
    one = C(1.0) if do_scale else None
    emax = C(emax_v) if do_eye else None
    gl = mod.glsl
    I = mod.new_id
    rep.update(cap=do_cap, scale=do_scale, eye=do_eye)
    for alpha in sorted({s['alpha'] for s in sites},
                        key=lambda a: mod.find_def(a)[0]):
        aline, _ = mod.find_def(alpha)
        if aline is None or not cfg.dominates_line(dom_id, aline):
            rep["skipped_dom"].append(alpha)
            continue
        ins = []
        a_skin = alpha
        if do_scale:
            sm, mn1 = I(), I()
            ins += [f"        {sm} = OpFMul %float {alpha} {scale}",
                    f"        {mn1} = OpExtInst %float {gl} NMin {sm} {one}"]
            a_skin = mn1
        if do_cap:
            mn = I()
            ins.append(f"        {mn} = OpExtInst %float {gl} NMin {a_skin} {smax}")
            a_skin = mn
        a_else = alpha
        if do_eye:
            me, se = I(), I()
            ins += [f"        {me} = OpExtInst %float {gl} NMin {alpha} {emax}",
                    f"        {se} = OpSelect %float {eye_gate} {me} {alpha}"]
            a_else = se
        if a_skin is not alpha:
            sel = I()
            ins.append(f"        {sel} = OpSelect %float {skin_gate} {a_skin} {a_else}")
        else:
            sel = a_else
        replace_all_uses(mod, alpha, sel, aline)
        edits.append((aline, ins))
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


def process(path, outdir, tier, knobs, hunt_classes, do_rt=True,
            tint=None, with_skinspec=False):
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
        shift, ins_line, pre_ins, consts, dom_id = acquire_class_shift(mod, cfg)
        rep['class_gate'] = {'anchor': dom_id, 'line': ins_line + 1,
                             'def': (mod.find_def(dom_id)[1] or '')[:48]}
        u1, ud1 = mod.uconst(1)
        if ud1:
            consts.append(ud1)
        skin_gate = mod.new_id()
        # Inserted directly after the class value (the module's own IEqual, or
        # our own shift emitted after the shared texel's extract in the
        # &31-variant modules) so the gate inherits that line's dominance.
        gate_ins = [f"        {skin_gate} = OpIEqual %bool {shift} {u1}"]
        eye_gate = None
        if knobs.get('eye_alpha_max', 1.0) < 1.0:
            # Class 8 = eyes (31 s5). Same shift, same dominance, one more
            # compare. Only emitted when the eye cap is live (byte-exactness).
            u8, ud8 = mod.uconst(8)
            if ud8:
                consts.append(ud8)
            eye_gate = mod.new_id()
            gate_ins.append(f"        {eye_gate} = OpIEqual %bool {shift} {u8}")
        edits = [(ins_line, pre_ins + gate_ins)]

        c1, e1, rep['diffuse'] = build_skin_c1(mod, cfg, dom_id, skin_gate, knobs)
        consts += c1
        edits += e1

        # Tier-3 gloss. The alpha reshape runs FIRST: it rewrites every use
        # of each alpha, while the Fresnel pass rewrites the Schlick F ids.
        # The two touch disjoint ids, so they compose rather than clobber.
        # (44: the two are gated independently -- a scale-only or eye-only
        # rung emits no Fresnel code at all.)
        if with_skinspec and alpha_reshape_active(knobs):
            cA, eA, rep['alpha_cap'] = build_skin_alpha_cap(
                mod, cfg, dom_id, skin_gate, knobs, eye_gate)
            consts += cA
            edits += eA
        if with_skinspec and skin_fresnel_active(knobs):
            cS, eS, rep['skin_spec'] = build_skin_spec(
                mod, cfg, dom_id, skin_gate, knobs)
            consts += cS
            edits += eS
        elif with_skinspec:
            rep['skin_spec'] = {'inactive': 'identity knobs -- nothing emitted'}

        rep['params'] = {k: knobs[k] for k in
                         ('rho_f', 'rho_r', 'n_f', 'm_f', 'n_r', 'm_r',
                          'n_s', 'spec_gain', 'alpha_max', 'alpha_scale',
                          'eye_alpha_max', 'dcouple', 'micro_k')}
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
    if not a.vanilla and not a.with_skinspec:
        # Tier-3 knobs are inert without the flag: force identity so a plain
        # c1 build is byte-exact against a pre-Tier-3 one.
        knobs.update(n_s=0.5, spec_gain=1.0, alpha_max=1.0,
                     alpha_scale=1.0, eye_alpha_max=1.0)
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
                       tint=tint, with_skinspec=a.with_skinspec)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
