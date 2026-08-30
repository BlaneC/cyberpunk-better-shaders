#!/usr/bin/env python3
"""G-U4 material sub-enum probe + A2 ungated sheen probe (handoff/40).

Two questions, one build, one install:

  G-U4  The G-buffer material byte splits twice. Every patcher in this repo
        reads only `word >> 5` (the 3-bit class) and throws away `word & 31`
        -- a populated 5-bit sub-enum that 67 modules switch on to pick
        per-subtype constants out of a CBV (38 sec 1.3, corrected by the
        tightened census in handoff/40 sec 2). Nobody knows what its values
        mean.
        Reading it costs exactly one OpBitwiseAnd on a byte the evaluators
        already fetch. This paints it.

  A2    An UNGATED Charlie sheen lobe at the existing GGX sites. Not a
        feature -- a mechanism probe. It removes hair's two confounds (the
        estimated tangent and the class gate) from the list of things that
        can explain a null result (22 sec 8). If it does not paint, the
        compute-BRDF track is cleanly dead.

Tiers
  --tier sub     paint palette[word & 31] into every image write, ungated
  --tier c1sub   the same paint, but only where (word >> 5) == 1 (skin)
  --tier cls     the existing 10-class palette (patch_compute_skin.build_hunt_
                 writes, imported not copied) -- the POSITIVE CONTROL: this
                 exact paint is what produced pics/panam_working_small.png
  --tier sheen   the ungated Charlie sheen, nothing else
  --tier both    sub + sheen in one module (38 sec 7's one-launch merge)

Nothing here is a feature. Every tier is a diagnostic and every one of them
is meant to look wrong.

Relationship to dev/patch_compute_skin.py: this file IMPORTS its class-gate
machinery (acquire_class_shift, find_class_anchor_variant, build_hunt_writes)
rather than copying it, and adds three things that did not exist --
acquire_material_word (the class machinery hands back `y >> 5`; the sub-enum
needs the byte BEFORE the shift), emit_material_word (the refetch chain minus
its final shift), and find_sheen_inputs (NoH / NoL / NoV / the Vis anchor at
a GGX site). patch_compute_skin.py is NOT modified.
"""
import argparse, json, math, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die, replace_all_uses
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import find_class_anchor_variant, build_hunt_writes


# ----------------------------------------------------------------- palette
# 16 hues, 22.5 deg apart, x 2 gains = 32 slots, one per sub-enum value.
#
# Why not 32 hues: nobody can read 32 hues off a tonemapped screenshot. Why
# not 8: the sub-enum is 5 bits and collapsing it loses the answer. So the
# palette is PRIORITISED BY EVIDENCE instead of being uniform --
#
#   * the 9 most-tested values (handoff/40 sec 2: 21, 25, 17, 30, 31, 12,
#     13, 14, 15) get the 8 cardinal 45-deg hues at high gain, plus
#     near-black. Those nine are the most different things this palette can
#     produce, and they are the nine values most likely to be on screen.
#     The census finds a TENTH tested value, 26, in exactly one Fragment
#     module and nowhere in compute; it keeps a dark slot rather than
#     displacing one of the nine. If 26 shows up on screen, that is a
#     finding in itself and the legend still names it.
#   * the other 22 values -- which no shader tests, but which the G-buffer
#     may still hold, because a shader only branches on what it needs -- get
#     the 8 remaining bright hues and then the dark ones. They are harder to
#     read, and that is the right trade: an unexpected value still lands on
#     its OWN colour and can be recovered by sampling the pixel, instead of
#     being swallowed by a catch-all.
#
# The paint is a MULTIPLY into the two lighting writes, not a replace, so the
# scene's own shapes survive and a region can be identified. Read hue first,
# then bright-vs-dark. For an exact value, sample the pixel in an editor and
# compare the R:G:B ratio against --legend.
HUE_NAMES = ("red", "orange-red", "amber", "yellow-green", "chartreuse",
             "green", "spring-green", "turquoise", "cyan", "azure", "blue",
             "blue-violet", "violet", "purple", "magenta", "crimson")

# the nine most-tested values, by module count descending (handoff/40 sec 2)
CENSUS9 = (21, 25, 17, 30, 31, 12, 13, 14, 15)
# the 8 cardinal hues (45 deg apart) + a near-black ninth
CENSUS_SLOTS = ((0, 'hi'), (8, 'hi'), (4, 'hi'), (12, 'hi'), (2, 'hi'),
                (10, 'hi'), (6, 'hi'), (14, 'hi'), (None, 'black'))


def _hue(i, floor=0.04):
    """HSV(i*22.5deg, 1, 1) with the two dark channels lifted off zero.

    A hard zero would make the tint a channel kill rather than a hue: the
    AgX chain maps 0 to 0 and the region reads as "no red at all" instead of
    "red-tinted", which is harder to tell from a shadow.
    """
    h = (i / 16.0) * 6.0
    k, f = int(h) % 6, h - int(h)
    q, t = 1.0 - f, f
    rgb = [(1, t, 0), (q, 1, 0), (0, 1, t), (0, q, 1), (t, 0, 1), (1, 0, q)][k]
    return tuple(round(floor + (1.0 - floor) * c, 4) for c in rgb)


def sub_palette(gain_hi=3.2, gain_lo=0.45, gain_black=0.05):
    """{value: (name, (r, g, b))} for all 32 sub-enum values."""
    pal, used = {}, set()
    for v, (hi, kind) in zip(CENSUS9, CENSUS_SLOTS):
        if kind == 'black':
            pal[v] = ("near-black", (gain_black, gain_black, gain_black))
        else:
            used.add((hi, 'hi'))
            pal[v] = ("bright " + HUE_NAMES[hi],
                      tuple(round(gain_hi * c, 4) for c in _hue(hi)))
    slots = [(i, 'hi') for i in range(16) if (i, 'hi') not in used]
    slots += [(i, 'lo') for i in range(16)]
    for v in (x for x in range(32) if x not in pal):
        i, g = slots.pop(0)
        gain = gain_hi if g == 'hi' else gain_lo
        pal[v] = (("bright " if g == 'hi' else "dark ") + HUE_NAMES[i],
                  tuple(round(gain * c, 4) for c in _hue(i)))
    assert len(pal) == 32
    return pal


# ------------------------------------------------- the material word itself
def acquire_material_word(mod):
    """The raw material byte, BEFORE the class shift.

    acquire_class_shift() (patch_compute_skin) hands back `y >> 5`; the
    sub-enum needs its operand. Two idioms, mirroring that function:

      1. the module computes its own `>> 5`  -> take the shift's operand
      2. the &31 / mask-compare families      -> find_class_anchor_variant
         already returns the extract, which IS the word

    Returns (word_id, insert_line, dom_id). The caller emits `word & 31`
    immediately after insert_line so the sub-enum inherits the extract's
    dominance -- the same policy acquire_class_shift uses for its own shift.
    """
    shift = None
    try:
        shift, _ = P.find_class_shift(mod)
    except SystemExit:
        pass
    if shift is not None:
        _, sdef = mod.find_def(shift)
        m = re.match(r'OpShiftRightLogical %uint (%\d+) %uint_5\s*$', sdef or '')
        if m:
            word = m.group(1)
            wline, _ = mod.find_def(word)
            if wline is not None:
                return word, wline, word
    eid, eline = find_class_anchor_variant(mod)
    return eid, eline, eid


def emit_material_word(mod, ctx, ins):
    """The class refetch chain, stopped one instruction early.

    patch_shadow_brdf.emit_class_value ends with `>> 5`; we need the byte it
    shifts. Everything above it is identical, so this is that function minus
    its last line. Kept here rather than added there because patch_shadow_brdf
    is shared by three shipping patchers and this is a diagnostic.
    """
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
    d, e, f, g, h = I(), I(), I(), I(), I()
    ins += [
        f"        {d} = OpAccessChain {ctx['ptrty']} {ctx['arr']} {slot}",
        f"        {e} = OpLoad {ctx['imgty']} {d}",
        f"        {f} = OpCompositeConstruct %v2uint {ctx['x']} {ctx['y']}",
        f"        {g} = OpImageFetch %v4uint {e} {f} Lod {ctx['lod']}",
        f"        {h} = OpCompositeExtract %uint {g} 1",
    ]
    return h


def build_sub_writes(mod, cfg, writes, palette, skin_only):
    """palette[word & 31] multiplied into every image write.

    Same shape as build_hunt_writes, one level finer: that one gates on
    `word >> 5` against up to ten classes, this one gates on `word & 31`
    against all thirty-two. The dominance / refetch policy is identical, and
    is the reason this cannot simply reuse that function -- the refetch has
    to stop before the shift.
    """
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one = C(1.0)
    word, ins_line, dom_id = acquire_material_word(mod)

    # Every uint constant is materialised ONCE, here. mod.uconst() has no
    # pending-declaration cache (GOTCHAS), so asking for %uint_21 twice
    # returns the same id AND a second declaration of it, and spirv-val then
    # rejects the module with "Id N is defined more than once". With 32
    # values and up to eight image writes that would fire every time.
    uids = {}
    for n in list(range(32)) + [31, 5, 1]:
        if n in uids:
            continue
        uid, ud = mod.uconst(n)
        if ud:
            consts.append(ud)
        uids[n] = uid

    # The module's own sub-enum, emitted once next to the material extract it
    # reads. Whether it is USED depends on dominance -- a write inside a
    # branch the fetch does not dominate has to refetch (below). If no write
    # uses it, its definition is not emitted at all: dead code that reads a
    # live id validates clean and looks exactly like a working splice, which
    # is the 08-DUAL-LOBE dead-sheen trap.
    sub = mod.new_id()
    gate_cls = mod.new_id() if skin_only else None
    cls_id = mod.new_id() if skin_only else None
    used_top = [False]

    tint = {v: [C(x) for x in palette[v][1]] for v in range(32)}
    ctx = None
    done, skipped, refetched = [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({"line": w['line'] + 1, "why": "texel not a v4 construct"})
            continue
        ins = []
        s_id, c_gate = sub, gate_cls
        if not cfg.dominates_line(dom_id, w['line']):
            # The module's own material fetch cannot reach this write --
            # reissue it here, exactly as build_hunt_writes does, but stop
            # before the shift so we still have the byte.
            if ctx is None:
                ctx = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line'])
                   for x in class_fetch_inputs(ctx)):
                skipped.append({"line": w['line'] + 1,
                                "why": "material word and refetch both fail"})
                continue
            wd = emit_material_word(mod, ctx, ins)
            s_id = mod.new_id()
            ins.append(f"        {s_id} = OpBitwiseAnd %uint {wd} {uids[31]}")
            if skin_only:
                cls, g = mod.new_id(), mod.new_id()
                ins += [
                    f"        {cls} = OpShiftRightLogical %uint {wd} {uids[5]}",
                    f"        {g} = OpIEqual %bool {cls} {uids[1]}",
                ]
                c_gate = g
            refetched.append(w['line'] + 1)
        else:
            used_top[0] = True
        gates = []
        for v in range(32):
            g = mod.new_id()
            ins.append(f"        {g} = OpIEqual %bool {s_id} {uids[v]}")
            gates.append((g, tint[v]))
        newc = []
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                s = mod.new_id()
                ins.append(f"        {s} = OpSelect %float {g} {rgb[ch]} {cur}")
                cur = s
            if c_gate is not None:
                s = mod.new_id()
                ins.append(f"        {s} = OpSelect %float {c_gate} {cur} {one}")
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
        die(f"{mod.name}: no image write reachable for the sub-enum paint")
    if used_top[0]:
        pre = [f"        {sub} = OpBitwiseAnd %uint {word} {uids[31]}"]
        if skin_only:
            pre += [
                f"        {cls_id} = OpShiftRightLogical %uint {word} {uids[5]}",
                f"        {gate_cls} = OpIEqual %bool {cls_id} {uids[1]}",
            ]
        edits.append((ins_line, pre))
    return consts, edits, {"writes": done, "skipped": skipped,
                           "refetched": refetched, "skin_only": bool(skin_only),
                           "word": word, "own_word_used": used_top[0]}


# ------------------------------------------------------------------ sheen
def _def(mod, i):
    return mod.find_def(i)[1] or ''


def find_sheen_inputs(mod, s):
    """(NoH, NoL, NoV, vis_id, spec_id) at one GGX site, or None.

    All four are already computed at every site -- 22 sec 4's load-bearing
    claim, re-derived here structurally rather than trusted:

      NoH   D = a2 / (pi * (NoH^2*(a2-1) + 1)^2). Walk a2-1 -> its FMul ->
            the square whose operand is NoH. (find_site_nh does the same walk
            but returns N and H COMPONENTS for a dot product; the sheen wants
            the scalar, and the scalar is already there.)

      NoL,  two Vis forms ship, both keyed on the site's own a2/alpha so a
      NoV   module with several sites cannot cross-wire them:
              S  height-correlated Smith  0.5 / (NoV*sqrt(NoL^2(1-a2)+a2)
                                                + NoL*sqrt(NoV^2(1-a2)+a2))
              H  the cheap approximation  0.25 / ((NoL+NoV)(1-alpha/2)+alpha)
            V_neubelt is symmetric in NoL and NoV, so which is which does not
            matter and is not guessed at.

      spec  the unique OpFMul that consumes the Vis. Measured: 464 of 464
            resolvable sites have exactly one. That product is where the
            sheen is added, because it is the last place the two lobes are
            still commensurable AND it is upstream of the modules' own
            NMin(x, 100) firefly clamp (GOTCHAS: scale before a clamp).
    """
    a2, alpha = s['a2'], s['alpha']
    lo = max(0, s['line'] - 140)
    am1 = None
    for j in range(lo, s['line']):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFAdd %float ' + re.escape(a2)
                     + r' %float_n1\s*$', mod.lines[j])
        if m:
            am1 = m.group(1)
            break
    if not am1:
        return None
    noh = None
    for j in range(lo, s['line']):
        m = re.match(r'\s*%\d+\s*=\s*OpFMul %float (%\d+) ' + re.escape(am1)
                     + r'\s*$', mod.lines[j])
        if m:
            mm = re.match(r'OpFMul %float (%\d+) \1\s*$', _def(mod, m.group(1)))
            if mm:
                noh = mm.group(1)
                break
    if not noh:
        return None

    vis = cosines = None
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFDiv %float %float_0_5 (%\d+)\s*$', ln)
        if m:
            ma = re.match(r'OpFAdd %float (%\d+) (%\d+)\s*$', _def(mod, m.group(2)))
            if not ma:
                continue
            got, ok = [], True
            for t in ma.groups():
                mt = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', _def(mod, t))
                if not mt:
                    ok = False
                    break
                sq = [o for o in mt.groups()
                      if re.match(r'OpExtInst %float %\w+ Sqrt (%\d+)', _def(mod, o))]
                nn = [o for o in mt.groups() if o not in sq]
                if len(sq) != 1 or len(nn) != 1:
                    ok = False
                    break
                arg = re.match(r'OpExtInst %float %\w+ Sqrt (%\d+)',
                               _def(mod, sq[0])).group(1)
                mf = re.match(r'OpFAdd %float (%\d+) (%\d+)\s*$', _def(mod, arg))
                if not mf or a2 not in mf.groups():
                    ok = False
                    break
                got.append(nn[0])
            if ok and len(got) == 2:
                vis, cosines = m.group(1), tuple(got)
                break
        m = re.match(r'\s*(%\d+)\s*=\s*OpFDiv %float %float_0_25 (%\d+)\s*$', ln)
        if m:
            ma = re.match(r'OpFAdd %float (%\d+) (%\d+)\s*$', _def(mod, m.group(2)))
            if not ma:
                continue
            hit = None
            for x, y in (ma.groups(), ma.groups()[::-1]):
                if y != alpha:
                    continue
                mx = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', _def(mod, x))
                if not mx:
                    continue
                for p, q in (mx.groups(), mx.groups()[::-1]):
                    mq = re.match(r'OpFSub %float %float_1 (%\d+)\s*$', _def(mod, q))
                    if not mq:
                        continue
                    mh = re.match(r'OpFMul %float (%\d+) %float_0_5\s*$',
                                  _def(mod, mq.group(1)))
                    if not mh or mh.group(1) != alpha:
                        continue
                    ms = re.match(r'OpFAdd %float (%\d+) (%\d+)\s*$', _def(mod, p))
                    if ms:
                        hit = ms.groups()
                        break
                if hit:
                    break
            if hit:
                vis, cosines = m.group(1), hit
                break
    if vis is None:
        return None
    cons = [j for j in uses_of(mod, vis)
            if re.match(r'\s*%\d+\s*=\s*OpFMul %float ', mod.lines[j])]
    if len(cons) != 1:
        return None
    spec = re.match(r'\s*(%\d+)', mod.lines[cons[0]]).group(1)
    return dict(noh=noh, nol=cosines[0], nov=cosines[1], vis=vis,
                spec=spec, spec_line=cons[0])


def build_sheen(mod, cfg, knobs):
    """Estevez & Kulla "Charlie" sheen + Neubelt visibility, added UNGATED.

        D_charlie(a, NoH) = (2 + 1/a) * (1 - NoH^2)^(1/(2a)) / (2*pi)
        V_neubelt(NoL,NoV) = 1 / (4 * (NoL + NoV - NoL*NoV))
        spec' = spec + k * D_charlie * V_neubelt

    Zeltner, Burley & Chiang (SIGGRAPH 2022) fit an LTC to a multiple-
    scattering sheen VOLUME and that is the better model, but its fit lives
    in a 3-parameter table -- a texture, i.e. a descriptor, i.e. U1, which is
    not built. The analytic Charlie lobe needs no resource and has the same
    grazing-widening behaviour that separates cloth from plastic, so it is
    what this probe splices. Stated here so nobody reads "LTC sheen" in the
    handoff and goes looking for a fit table in the module.

    (2 + 1/a)/(2*pi) and 1/(2a) are folded at build time, so the per-site
    cost is 16 instructions and one of them is the add itself.

    NO CLASS GATE, deliberately. That is the whole point (22 sec 8): an
    ungated lobe removes the gate from the list of things that can explain a
    null result. It is wrong as a feature and correct as a probe.
    """
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    if mod.glsl is None:
        die(f"{mod.name}: no GLSL.std.450 set -- cannot emit the sheen")
    gl = mod.glsl
    a = float(knobs['a_sheen'])
    k = float(knobs['k_sheen'])
    one = C(1.0)
    eps = C(1e-6)
    four = C(4.0)
    den_min = C(1e-4)
    inv2a = C(1.0 / (2.0 * a))
    pre = C(k * (2.0 + 1.0 / a) / (2.0 * math.pi))
    cap = C(float(knobs['sheen_max']))

    sites = P.find_ggx_sites(mod)
    rep = {"ggx_sites": len(sites), "sheen_sites": 0,
           "skipped_shape": [], "skipped_dom": []}
    for s in sites:
        f = find_sheen_inputs(mod, s)
        if not f:
            rep["skipped_shape"].append(s['line'] + 1)
            continue
        line = f['spec_line']
        bad = [x for x in (f['noh'], f['nol'], f['nov'])
               if not cfg.dominates_line(x, line)]
        if bad:
            rep["skipped_dom"].append({"line": line + 1, "ids": bad})
            continue
        I = mod.new_id
        t, u, um, lg, xe, dc = [I() for _ in range(6)]
        sm, pr, q, q4, qm, vn = [I() for _ in range(6)]
        sh, shk, shc, out = [I() for _ in range(4)]
        ins = [
            f"        {t} = OpFMul %float {f['noh']} {f['noh']}",
            f"        {u} = OpFSub %float {one} {t}",
            f"        {um} = OpExtInst %float {gl} NMax {u} {eps}",
            f"        {lg} = OpExtInst %float {gl} Log2 {um}",
            f"        {xe} = OpFMul %float {lg} {inv2a}",
            f"        {dc} = OpExtInst %float {gl} Exp2 {xe}",
            f"        {sm} = OpFAdd %float {f['nol']} {f['nov']}",
            f"        {pr} = OpFMul %float {f['nol']} {f['nov']}",
            f"        {q} = OpFSub %float {sm} {pr}",
            f"        {q4} = OpFMul %float {q} {four}",
            f"        {qm} = OpExtInst %float {gl} NMax {q4} {den_min}",
            f"        {vn} = OpFDiv %float {one} {qm}",
            f"        {sh} = OpFMul %float {dc} {vn}",
            f"        {shk} = OpFMul %float {sh} {pre}",
            # Bounded before it is added, not after: the modules that clamp
            # their specular do it downstream of this point, and the ones
            # that do not would carry an unbounded 1/eps into an fp16 store.
            f"        {shc} = OpExtInst %float {gl} NMin {shk} {cap}",
            f"        {out} = OpFAdd %float {f['spec']} {shc}",
        ]
        replace_all_uses(mod, f['spec'], out, line)
        edits.append((line, ins))
        rep["sheen_sites"] += 1
    if rep["sheen_sites"] == 0:
        die(f"{mod.name}: no GGX site could take the sheen "
            f"({len(sites)} sites, all declined)")
    return consts, edits, rep


# ------------------------------------------------------------------ driver
KNOBS = dict(k_sheen=8.0, a_sheen=0.35, sheen_max=25.0,
             gain_hi=3.2, gain_lo=0.45, gain_black=0.05)
TIERS = ('sub', 'c1sub', 'cls', 'sheen', 'both')


def process(path, outdir, tier, knobs, do_rt=True, hunt_classes=None):
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
    pal = sub_palette(knobs['gain_hi'], knobs['gain_lo'], knobs['gain_black'])

    # GOTCHAS 12: every read-only detector runs BEFORE any pass that rewrites
    # uses. find_image_writes walks back from the OpImageWrite to its
    # OpCompositeConstruct; the sheen's replace_all_uses would leave that walk
    # pointing at an id whose definition is still pending in `edits`, and it
    # would dead-end SILENTLY -- reporting "no write found" and emitting
    # nothing, which from the chair is identical to the feature not working.
    writes = find_image_writes(mod) if tier != 'sheen' else None

    consts, edits = [], []
    if tier == 'sheen':
        consts, edits, rep['sheen'] = build_sheen(mod, cfg, knobs)
    elif tier == 'cls':
        consts, edits, rep['hunt'] = build_hunt_writes(
            mod, cfg, writes, hunt_classes or P.HUNT_DEFAULT)
    else:
        if tier == 'both':
            cS, eS, rep['sheen'] = build_sheen(mod, cfg, knobs)
            consts += cS
            edits += eS
        cP, eP, rep['sub'] = build_sub_writes(
            mod, cfg, writes, pal, tier == "c1sub")
        consts += cP
        edits += eP

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
        os.unlink(spv_out)     # never leave a stale .spv for the installer
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def print_legend(knobs, fmt='text'):
    pal = sub_palette(knobs['gain_hi'], knobs['gain_lo'], knobs['gain_black'])
    if fmt == 'md':
        print("| sub-enum | tested? | appearance | RGB multiplier |")
        print("|---|---|---|---|")
        for v in range(32):
            name, rgb = pal[v]
            print("| **%d** | %s | %s | `%.2f, %.2f, %.2f` |"
                  % (v, "yes" if v in CENSUS9 else "-", name, *rgb))
    else:
        print("value  tested  appearance              R      G      B")
        for v in range(32):
            name, rgb = pal[v]
            print("%5d  %-6s  %-22s  %5.2f  %5.2f  %5.2f"
                  % (v, "yes" if v in CENSUS9 else "-", name, *rgb))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='*')
    ap.add_argument('--tier', default='sub', choices=TIERS)
    ap.add_argument('--outdir')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    ap.add_argument('--hunt-classes', default='')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--legend', action='store_true',
                    help='print the colour legend and exit')
    ap.add_argument('--legend-md', action='store_true')
    a = ap.parse_args()

    knobs = dict(KNOBS)
    for kv in a.set:
        k, v = kv.split('=')
        if k not in knobs:
            die(f"unknown knob {k}")
        knobs[k] = float(v)

    if a.legend or a.legend_md:
        print_legend(knobs, 'md' if a.legend_md else 'text')
        return
    if not a.modules or not a.outdir:
        die("need modules and --outdir (or --legend)")

    hunt = [int(x) for x in a.hunt_classes.split(',') if x.strip()] or None
    reports = [process(p, a.outdir, a.tier, knobs,
                       do_rt=not a.no_roundtrip_check, hunt_classes=hunt)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
