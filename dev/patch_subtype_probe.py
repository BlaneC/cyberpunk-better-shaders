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
  --tier peach   the ONE exception to "nothing here is a feature": the
                 class-1-gated peach fuzz A2/A3 unlocked (handoff/58).
                 --peach-mode add is the sheen LOBE (default); mul is the
                 58-era multiplicative form, kept for reproduction.
  --tier both    sub + sheen in one module (38 sec 7's one-launch merge)
  --tier gi      handoff/48 sec 8: per-FAMILY hue paint at the RAYGEN
                 radiance writes (reference green, restirgi-diffuse red,
                 restirgi-specular blue), class-1 gated. Raygen modules
                 only -- driven by dev/build_probe_gi.sh, not by the
                 compute wrapper.

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


def _nonneg(mod, i, depth=4):
    """True when %i is provably >= 0 from its definition alone.

    Read-only and deliberately conservative: anything it cannot prove comes
    back False and the caller emits a clamp. Four shapes cover every cosine
    the 77 compute modules actually build -- NClamp(x, 0, 1), NMax(x, eps),
    NMin of such, a square, and an OpPhi of any of those.
    """
    if depth < 0:
        return False
    d = _def(mod, i)
    m = re.match(r'OpExtInst %float %\w+ NClamp (%\S+) (%\S+) (%\S+)\s*$', d)
    if m:
        lo = _gi_float_const(mod, m.group(2))
        return lo is not None and lo >= 0.0
    m = re.match(r'OpExtInst %float %\w+ NMax (%\S+) (%\S+)\s*$', d)
    if m:                                       # max(x, c>=0) >= 0
        for t in m.groups():
            v = _gi_float_const(mod, t)
            if v is not None and v >= 0.0:
                return True
            if v is None and _nonneg(mod, t, depth - 1):
                return True
        return False
    m = re.match(r'OpExtInst %float %\w+ NMin (%\S+) (%\S+)\s*$', d)
    if m:                                       # min(a, b) >= 0 needs both
        for t in m.groups():
            v = _gi_float_const(mod, t)
            if not ((v is not None and v >= 0.0)
                    or (v is None and _nonneg(mod, t, depth - 1))):
                return False
        return True
    m = re.match(r'OpFMul %float (%\S+) (%\S+)\s*$', d)
    if m and m.group(1) == m.group(2):
        return True                             # a square
    m = re.match(r'OpPhi %float (.*)$', d)
    if m:
        ops = [v for v, _b in re.findall(r'(%\S+) (%\S+)', m.group(1))]
        return bool(ops) and all(_nonneg(mod, v, depth - 1) for v in ops)
    v = _gi_float_const(mod, i)
    return v is not None and v >= 0.0


def _in_unit(mod, i, depth=4):
    """True when %i is provably a SATURATED cosine, i.e. in [0, 1].

    Census over the 77 anchored compute modules (457 sheen-shaped sites, two
    cosines each): 457 are NMin(NMax(x, 1e-6), 1) and 337 are NClamp(x, 0, 1)
    -- provably saturated. The remaining 120 are an OpPhi (104) or a bare
    OpDot (16). A bare dot is NOT saturated: N.L goes negative on any pixel
    whose shading normal faces away from the light, and V_neubelt's
    denominator (NoL + NoV - NoL*NoV) then goes NEGATIVE, is caught by the
    NMax(q, 1e-4) floor, and the lobe evaluates at its CEILING exactly where
    the surface is backlit. That is the "lightbulb behind the ear" failure
    (handoff/69 sec 1) waiting to happen, so those sites get a real clamp.
    """
    if depth < 0:
        return False
    d = _def(mod, i)
    m = re.match(r'OpExtInst %float %\w+ NClamp (%\S+) (%\S+) (%\S+)\s*$', d)
    if m:
        lo = _gi_float_const(mod, m.group(2))
        hi = _gi_float_const(mod, m.group(3))
        return (lo is not None and hi is not None and lo >= 0.0 and hi <= 1.0)
    m = re.match(r'OpExtInst %float %\w+ NMin (%\S+) (%\S+)\s*$', d)
    if m:
        capped = False
        for t in m.groups():
            v = _gi_float_const(mod, t)
            if (v is not None and v <= 1.0) or (v is None
                                                and _in_unit(mod, t, depth - 1)):
                capped = True
        return capped and _nonneg(mod, i, depth)
    m = re.match(r'OpPhi %float (.*)$', d)
    if m:
        ops = [v for v, _b in re.findall(r'(%\S+) (%\S+)', m.group(1))]
        return bool(ops) and all(_in_unit(mod, v, depth - 1) for v in ops)
    v = _gi_float_const(mod, i)
    return v is not None and 0.0 <= v <= 1.0


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
            matter to the lobe and is not guessed at. Where the DIFFERENCE
            matters -- folding the site's own light cosine into an additive
            lobe -- _fold_cosine reads it off the D chain instead of guessing.

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


def _fold_cosine(mod, site, f):
    """The cosine the SITE ITSELF folds into D before Vis (i.e. its NoL), or
    None when it folds none.

    Census over the 77 anchored compute modules (457 sheen-shaped sites):

        401   vd = D * NoL   and   spec = vd * Vis
         56   vd = D * Vis   and   spec = vd        (the cheap-Vis form)

    An additive lobe must carry the same cosine the site carries, or it does
    not vanish where the site's own specular vanishes. Folding NoL into the
    first family puts the fuzz on the same terminator as the GGX lobe it
    rides. The second family folds no cosine HERE (it is applied downstream,
    outside this splice's reach), and the two cosines it does have are not
    labelled -- V_neubelt is symmetric, so nothing in the shape says which is
    NoL. The caller then folds min(c0, c1), which is <= NoL whichever one it
    is: conservative by construction, and it still dies at the terminator
    rather than holding the fuzz at full strength on backlit skin the way an
    unfolded lobe would (24 of 77 modules, 56 of 457 sites).
    """
    m = re.match(r'OpFMul %float (%\S+) (%\S+)\s*$', _def(mod, site['vd']))
    if not m:
        return None
    other = m.group(1) if m.group(2) == site['d'] else m.group(2)
    return other if other in (f['nol'], f['nov']) else None


def _emit_fuzz_lobe(mod, gl, ins, noh, c0, c1, k):
    """Estevez & Kulla "Charlie" D x Neubelt V at one site, capped.

        D_charlie(a, NoH) = (2 + 1/a) * (1 - NoH^2)^(1/(2a)) / (2*pi)
        V_neubelt(NoL,NoV) = 1 / (4 * (NoL + NoV - NoL*NoV))

    Appends its instructions to `ins` and returns the capped lobe id. `k` is
    the caller's dict of interned constant ids: one, eps, four, den_min,
    inv2a, pre, cap -- where pre folds (2 + 1/a)/(2*pi) (and, for the
    ungated probe, the gain) at build time, so the per-site cost is 15
    instructions.

    Zeltner, Burley & Chiang (SIGGRAPH 2022) fit an LTC to a multiple-
    scattering sheen VOLUME and that is the better model, but its fit lives
    in a 3-parameter table -- a texture, i.e. a descriptor, i.e. U1, which is
    not built. The analytic Charlie lobe needs no resource and has the same
    grazing-widening behaviour that separates cloth from plastic, so it is
    what ships. Stated here so nobody reads "LTC sheen" in the handoff and
    goes looking for a fit table in the module.

    The cosines must already be saturated -- the caller clamps the ones
    _in_unit cannot prove. The NMax(q, den_min) floor below is then a
    division guard on a genuinely small denominator, not a sign fixup.
    """
    I = mod.new_id
    t, u, um, lg, xe, dc = [I() for _ in range(6)]
    sm, pr, q, q4, qm, vn = [I() for _ in range(6)]
    sh, sn, shc = I(), I(), I()
    ins += [
        f"        {t} = OpFMul %float {noh} {noh}",
        f"        {u} = OpFSub %float {k['one']} {t}",
        f"        {um} = OpExtInst %float {gl} NMax {u} {k['eps']}",
        f"        {lg} = OpExtInst %float {gl} Log2 {um}",
        f"        {xe} = OpFMul %float {lg} {k['inv2a']}",
        f"        {dc} = OpExtInst %float {gl} Exp2 {xe}",
        f"        {sm} = OpFAdd %float {c0} {c1}",
        f"        {pr} = OpFMul %float {c0} {c1}",
        f"        {q} = OpFSub %float {sm} {pr}",
        f"        {q4} = OpFMul %float {q} {k['four']}",
        f"        {qm} = OpExtInst %float {gl} NMax {q4} {k['den_min']}",
        f"        {vn} = OpFDiv %float {k['one']} {qm}",
        f"        {sh} = OpFMul %float {dc} {vn}",
        f"        {sn} = OpFMul %float {sh} {k['pre']}",
        # Bounded before it reaches the base term, not after: the modules that
        # clamp their specular do it downstream of this point, and the ones
        # that do not would carry an unbounded 1/eps into an fp16 store.
        f"        {shc} = OpExtInst %float {gl} NMin {sn} {k['cap']}",
    ]
    return shc


def _emit_defres(mod, gl, ins, noh, c0, c1, k, zero, beta_id):
    """The TARGETED weight w = 1 - beta*(1-VoH)^5, from the site's own values.

    Why it exists. The lobe is spliced UPSTREAM of the module's own Schlick
    multiply, so F(VoH) weights it: ~0.028 in the front-lit sheen band (VoH
    ~ 1) and up to ~0.87 on a BACKLIT silhouette (VoH ~ 0.05), a 30x swing
    that has nothing to do with sheen. That swing is what put a blown white
    edge on the rim -- exactly the pixels where the terminator bleed's deep
    red lives -- while the cheek band the fuzz is FOR sat at a few percent.
    Multiplying by (1 - p5) cancels the Schlick ramp: the net weight
    F*(1-p5) is 1.00x of F where VoH >= 0.8 (the sheen band is untouched),
    0.41x at VoH 0.1 and 0.23x at 0.05. Peak net weight 0.2465 at VoH ~ 0.1
    against 0.87 unweighted -- a 3.5x cut confined to the rim.

    VoH is not read from the module and is not a new unknown: for a unit
    bisector, L + V = 2*VoH*H, so dotting with N gives EXACTLY

        VoH = (NoL + NoV) / (2 * NoH)

    and all three are already at the site. The expression is SYMMETRIC in the
    two cosines, so the NoL/NoV labelling ambiguity that _fold_cosine has to
    work around does not exist here -- it is exact at all 457 sites, the 56
    cheap-Vis ones included.

    Guards: NMax(2*NoH, eps) is a division guard (NoL+NoV = 2*VoH*NoH
    vanishes with NoH, so the quotient stays finite in the limit), and the
    NClamp keeps VoH in [0,1] where a negative or stale NoH would otherwise
    steer the power. Both regions are ones where the site's own folded
    cosine is already 0, so the whole added term is 0 there regardless.
    """
    I = mod.new_id
    sm, nh2, nhm, voh, vs = [I() for _ in range(5)]
    om, o2, o4, p5 = [I() for _ in range(4)]
    ins += [
        f"        {sm} = OpFAdd %float {c0} {c1}",
        f"        {nh2} = OpFAdd %float {noh} {noh}",
        f"        {nhm} = OpExtInst %float {gl} NMax {nh2} {k['eps']}",
        f"        {voh} = OpFDiv %float {sm} {nhm}",
        f"        {vs} = OpExtInst %float {gl} NClamp {voh} {zero} {k['one']}",
        f"        {om} = OpFSub %float {k['one']} {vs}",
        f"        {o2} = OpFMul %float {om} {om}",
        f"        {o4} = OpFMul %float {o2} {o2}",
        f"        {p5} = OpFMul %float {o4} {om}",
    ]
    if beta_id is None:                     # beta == 1: no constant, no FMul
        pb = p5
    else:
        pb = I()
        ins.append(f"        {pb} = OpFMul %float {p5} {beta_id}")
    w = I()
    ins.append(f"        {w} = OpFSub %float {k['one']} {pb}")
    return w


def _saturate_cosines(mod, gl, ins, one, zero, f):
    """(c0, c1, n_clamped) -- the site's two cosines, provably in [0, 1].

    Emits an NClamp only where _in_unit cannot prove saturation, so a module
    whose cosines are already clamped assembles byte-for-byte as before.
    """
    out, n = [], 0
    for cid in (f['nol'], f['nov']):
        if _in_unit(mod, cid):
            out.append(cid)
            continue
        cl = mod.new_id()
        ins.append(f"        {cl} = OpExtInst %float {gl} NClamp {cid} {zero} {one}")
        out.append(cl)
        n += 1
    return out[0], out[1], n


def build_sheen(mod, cfg, knobs):
    """The ungated probe: Charlie sheen ADDED at every GGX site.

        spec' = spec + min(k * D_charlie * V_neubelt, cap)

    NO CLASS GATE, deliberately. That is the whole point (22 sec 8): an
    ungated lobe removes the gate from the list of things that can explain a
    null result. It is wrong as a feature and correct as a probe -- and it
    passed on screen (handoff/58: white grazing sheen on cloth, vegetation
    and skin), which is what made the gated feature in build_peach a build
    rather than a gate.
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
    K = dict(one=C(1.0), eps=C(1e-6), four=C(4.0), den_min=C(1e-4),
             inv2a=C(1.0 / (2.0 * a)),
             pre=C(k * (2.0 + 1.0 / a) / (2.0 * math.pi)),
             cap=C(float(knobs['sheen_max'])))
    zero = C(0.0)

    sites = P.find_ggx_sites(mod)
    rep = {"ggx_sites": len(sites), "sheen_sites": 0, "clamped": 0,
           "skipped_shape": [], "skipped_dom": [], "skipped_dup": []}
    seen = set()
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
        if f['spec'] in seen:
            # Two sites resolving to ONE product: the second edit would be a
            # silent no-op (the 08-DUAL-LOBE lesson) while still counting as
            # coverage. Census says zero; report it rather than trust it.
            rep["skipped_dup"].append(line + 1)
            continue
        seen.add(f['spec'])
        ins = []
        c0, c1, nc = _saturate_cosines(mod, gl, ins, K['one'], zero, f)
        rep["clamped"] += nc
        lobe = _emit_fuzz_lobe(mod, gl, ins, f['noh'], c0, c1, K)
        out = mod.new_id()
        ins.append(f"        {out} = OpFAdd %float {f['spec']} {lobe}")
        replace_all_uses(mod, f['spec'], out, line)
        edits.append((line, ins))
        rep["sheen_sites"] += 1
    if rep["sheen_sites"] == 0:
        die(f"{mod.name}: no GGX site could take the sheen "
            f"({len(sites)} sites, all declined)")
    return consts, edits, rep


# ------------------------------------------------- cloth sheen (handoff/80)
# The A2 rung. Everything below is READ-ONLY detection plus one emitter; it
# runs inside build_peach so the two lobes share one splice per site and one
# replace_all_uses (the 08-DUAL-LOBE rule).
#
# The gate, and why it is what it is. `22` §5 hoped for a cloth class; `80`
# §2 shows there is no cloth-exclusive gate readable offline -- the class
# byte's 3-bit field names {0,1,3,4,5} and nothing on screen has ever named
# which one clothing is, and the 5-bit sub-enum's only compute consumers are
# LIGHT-CHANNEL flags ({12,13,14,15,21,30,31} -> 512, {25} -> 1024), not
# material identities. So this ships the honest gate instead of a guessed
# one: every ROUGH DIELECTRIC that is not skin and not hair.
#
#   not skin   class != 1   -- skin has its own fuzz lobe (A3); double-dipping
#                             it would be a second achromatic add on the one
#                             surface the project has already tuned.
#   not hair   class != 4   -- hair's BRDF was removed (39) and a sheen on a
#                             strand is the anisotropic term that 22 §4b says
#                             cannot be built here.
#   dielectric max3(F0) < f0max -- F0 = lerp(0.04, albedo, metallic) is at the
#                             site (find_f0_triples). Metals sit at their
#                             albedo (>= 0.2 for every real conductor); a
#                             dielectric sits at 0.04. This is the metallic
#                             test, read off the value the site itself uses.
#   rough      wr = sat((alpha - a0)/(a1 - a0)) -- a RAMP, not a cut, on the
#                             site's own alpha. Glass, clearcoat and polished
#                             plastic get zero; leather 0.3; fabric and
#                             concrete 1.0.
#
# What that gate does NOT do, said out loud: it does not separate cloth from
# concrete, plaster, wood or dirt. Those get the lobe too, bounded, as a
# grazing retroreflection they physically have and single-scatter GGX does
# not model. dev/cloth_model.py prints the amount.
F0_LERP_C = '%float_0_0399999991'
F0_LERP_NC = '%float_n0_0399999991'
BURLEY_C = '%float_0_107508637'
INV_PI_C = '%float_0_318309873'
ZERO_TOKS = ('%float_0', '%float_n0')


def find_f0_triples(mod):
    """Every F0 = lerp(0.04, albedo, metallic) triple, as (line, (r,g,b)).

    The idiom, verbatim from the shipping evaluators (03dc7a51:526-534):

        %330 = OpFAdd  albedo_r  -0.04
        %334 = OpFMul  %330      metallic
        %337 = OpFAdd  %334      +0.04        <- F0_r

    three consecutive channels sharing ONE metallic id. The two 0.04
    constants of opposite sign are what make the shape unambiguous -- no
    other term in these modules pairs them.

    A triple is returned at the line of its LAST channel, because that is the
    first line at which all three ids exist.
    """
    per = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpFAdd %float (%\d+) '
                     + re.escape(F0_LERP_C) + r'\s*$', ln)
        if not m:
            continue
        f0, y = m.groups()
        mm = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', _def(mod, y) or '')
        if not mm:
            continue
        for z, mt in (mm.groups(), mm.groups()[::-1]):
            ma = re.match(r'OpFAdd %float (%\d+) ' + re.escape(F0_LERP_NC)
                          + r'\s*$', _def(mod, z) or '')
            if ma:
                per[i] = (f0, mt)
                break
    out, i = [], 0
    keys = sorted(per)
    while i < len(keys):
        a = keys[i]
        if (a + 1 in per and a + 2 in per
                and per[a][1] == per[a + 1][1] == per[a + 2][1]):
            out.append((a + 2, (per[a][0], per[a + 1][0], per[a + 2][0])))
            i += 3
            while i < len(keys) and keys[i] <= a + 2:
                i += 1
            continue
        i += 1
    return out


def lift_f0_phis(mod, trips):
    """F0 triples reached through guarded OpPhis, added to `trips`.

    The 52765-line GI evaluator computes its F0 once inside a guarded block
    and every later site reads it through a phi at the merge (`%4146 = OpPhi
    %float_0 ... %4053 ...`) -- so the raw triple does NOT dominate 61 of the
    457 sites while the phi does. Same fixpoint walk find_gi_class uses for
    the raygen class: a phi joins the set when EVERY operand is already in it
    or is a literal zero. Zero is not a metal (F0 = 0 fails no dielectric
    test), so widening through it cannot let a metal in.

    With this, 457 of 457 sites carry a dominating F0 triple. Without it,
    376.
    """
    sets = [set(), set(), set()]
    for _, t in trips:
        for c in range(3):
            sets[c].add(t[c])
    phis = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpPhi %float (.*)$', ln)
        if m:
            ops = [o for o in m.group(2).split() if o.startswith('%')][::2]
            phis[m.group(1)] = (i, ops)
    added = {c: {} for c in range(3)}
    changed = True
    while changed:
        changed = False
        for pid, (i, ops) in phis.items():
            for c in range(3):
                if pid in sets[c] or not ops:
                    continue
                if all(o in sets[c] or o in ZERO_TOKS for o in ops):
                    sets[c].add(pid)
                    added[c][i] = pid
                    changed = True
    out = list(trips)
    for i, pid in added[0].items():
        if (i + 1) in added[1] and (i + 2) in added[2]:
            out.append((i + 2, (pid, added[1][i + 1], added[2][i + 2])))
    return out


def find_diffuse_scalars(mod):
    """The Burley diffuse scalar f_d at every diffuse site, + its roughness.

        %692 = OpFMul rough 0.107508637
        %694 = OpFSub 0.318309873 %692        <- (1/pi - rough*k), unique
        %696 = OpFMul %694 FD(NoL)
        %697 = OpFMul %696 FD(NoV)            <- f_d

    Each hop must have exactly ONE FMul consumer, so a shape that fans out is
    skipped rather than guessed at. Census over the shipped 77: 173 sites,
    which is exactly the c1 count patch_compute_skin reports -- the same
    diffuse sites, found by a different anchor.

    Returned at f_d's own line; the caller damps it there, UPSTREAM of the
    class-1 c1 factor the parent rung already multiplied onto it (that
    factor's replace_all_uses has already run in the parent's bytes, so this
    is the second and last rewrite of the value, not a competing one).
    """
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpFSub %float ' + re.escape(INV_PI_C)
                     + r' (%\d+)\s*$', ln)
        if not m:
            continue
        pre, y = m.groups()
        mm = re.match(r'OpFMul %float (%\S+) (%\S+)\s*$', _def(mod, y) or '')
        if not mm or BURLEY_C not in mm.groups():
            continue
        rough = [o for o in mm.groups() if o != BURLEY_C][0]
        cur, line = pre, i
        ok = True
        for _ in range(2):
            cons = [j for j in uses_of(mod, cur)
                    if re.match(r'\s*%\d+ = OpFMul %float ', mod.lines[j])]
            if len(cons) != 1:
                ok = False
                break
            line = cons[0]
            cur = re.match(r'\s*(%\d+)', mod.lines[line]).group(1)
        if ok:
            out.append(dict(fd=cur, line=line, rough=rough))
    return out


def _emit_ramp(mod, gl, ins, alpha, k):
    """wr = sat((alpha - a0) * inv_span) -- the roughness ramp, in ALPHA.

    alpha is the site's own value, i.e. authored_roughness^2 on any pixel
    this gate lets through: the only thing that reshapes alpha in these
    modules is the class-1 skin cap, and class 1 is gated out.
    """
    I = mod.new_id
    t, u, wr = I(), I(), I()
    ins += [
        f"        {t} = OpFSub %float {alpha} {k['ra0']}",
        f"        {u} = OpFMul %float {t} {k['rspan']}",
        f"        {wr} = OpExtInst %float {gl} NClamp {u} {k['zero']} {k['one']}",
    ]
    return wr


def build_peach(mod, cfg, knobs, mode='add'):
    """Class-1-gated peach fuzz (A3) -- a real sheen LOBE on skin.

        fuzz  = min(D_charlie(a, NoH) * V_neubelt(NoL, NoV) * (2+1/a)/2pi, cap)
        add:  spec' = spec + select(class 1, k * fuzz * cos_site, 0)
        mul:  spec' = spec * select(class 1, 1 + k * fuzz,        1)

    where cos_site is the light cosine the SITE ITSELF folds into D
    (_fold_cosine), or min(NoL, NoV) where it folds none.

    `add` is the feature; `mul` is the 58-era form, kept because the rung
    built from it is on screen and A/B'd (handoff/58, 51 sec 10).

    Why the form changed. Multiplying is bounded by the term it multiplies,
    and at a silhouette -- no mirror alignment -- that term is nearly zero,
    so 1 + k*fuzz brightens nothing. dev/fuzz_model.py evaluates the 58-era
    constants over the (view, light) hemisphere: the factor is 1.0000-1.0466
    across the whole face and reaches 1.24 only within ~2 deg of the
    silhouette with the light equally grazing. Peach fuzz is exactly the
    thing the base lobe does NOT have, so it has to arrive as its own lobe,
    added. The user's read of that rung -- "extremely subtle" -- is what the
    arithmetic says it must be; it was not a tuning miss.

    What keeps `add` honest (the 38 0d / 39 sec 3.3 tile-grid lesson):

      * it is spliced at the site's OWN D*Vis product, so everything the
        module multiplies downstream -- Fresnel, light colour, shadow, the
        NMin(x, 100) firefly clamp -- lands on the fuzz too. Nothing is
        painted into an unlit pixel: shadowed and unlit skin stay black
        because the LIGHT is zero, not because the lobe is.
      * the Fresnel multiply downstream weights it toward a RIM rather
        than a wash for free -- but only the front-lit half of that is
        wanted. On a BACKLIT silhouette F reaches ~0.87, a ~30x swing
        over the f0 floor the sheen band sits at, and that is what put a
        blown white edge over the terminator bleed's red on screen. The
        `defres` knob cancels that share of the ramp (_emit_defres); at
        defres=1 the front-lit band is unchanged and the rim peak drops
        2.5x.
      * it carries the site's own light cosine (_fold_cosine), so it dies at
        the terminator with the term it rides.
      * the cosines are saturated first (_in_unit), so a backfacing shading
        normal cannot drive V_neubelt to its ceiling -- the "lightbulb"
        failure mode of handoff/69 sec 1.
      * it is class-1 gated, so non-skin pixels are the parent rung's bytes.

    Magnitude. `k` is measured AT THE SPLICE POINT, which is upstream of the
    module's own Fresnel multiply -- and in the geometry where this lobe
    lives (light on the viewer's side, both vectors grazing) the half vector
    sits between two nearly parallel vectors, so VoH ~ 1 and F is at its
    FLOOR, f0 ~ 0.028. The fuzz is therefore attenuated ~36x by a term that
    has nothing to do with it, which is why k of order 1 is the right
    magnitude here and 0.1 is not. dev/fuzz_model.py evaluates all of this
    offline; at k=1.0 the added lobe is, as a fraction of the LOCAL DIFFUSE:

        head-on            0.0 - 2%      (invisible: no wash)
        cheek / jaw rim    5 - 17%       (the feature)
        backlit silhouette 159%          (at the shipped defres=1, peach_max
                                          =0.5; it was 781% at the 72-era
                                          defres=0, cap=1, and THAT is what
                                          the user's A/B called blown out)

    against the 58-era multiplicative rung's 0.0-1.5% over the same face --
    which is what "extremely subtle" measured to.

    Not energy-compensated (no (1 - F_sheen) on the base): at this amplitude
    the error is far below the dither.
    """
    from patch_compute_skin import acquire_class_shift
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    if mod.glsl is None:
        die(f"{mod.name}: no GLSL.std.450 set -- cannot emit the peach fuzz")
    if mode not in ('add', 'mul'):
        die(f"unknown peach mode {mode}")
    gl = mod.glsl
    a = float(knobs['a_peach'])
    k = float(knobs['k_peach'])
    K = dict(cap=C(float(knobs['peach_max'])), one=C(1.0), eps=C(1e-6),
             four=C(4.0), den_min=C(1e-4), inv2a=C(1.0 / (2.0 * a)),
             pre=C((2.0 + 1.0 / a) / (2.0 * math.pi)))
    kc = C(k)
    zero = C(0.0)
    beta = float(knobs.get('defres', 0.0))
    if not 0.0 <= beta <= 1.0:
        die(f"defres must be in [0, 1], got {beta}")
    # mode mul is the 58-era rung's reproduction: it takes no weight, so that
    # build stays byte-comparable. beta == 1 needs no constant (see _emit_defres).
    beta_on = mode == 'add' and beta > 0.0
    beta_id = C(beta) if beta_on and beta != 1.0 else None

    # Class gate (class 1 = skin), lifted onto a dominating phi where needed.
    # Detected before any emission: find_ggx_sites / find_sheen_inputs are
    # read-only, and replace_all_uses below rewrites mod.lines in place.
    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod, cfg)
    consts.extend(pre_consts)
    u1, ud = mod.uconst(1)
    if ud:
        consts.append(ud)
    skin_gate = mod.new_id()
    gate_ins = [f"        {skin_gate} = OpIEqual %bool {shift} {u1}"]

    # ---- the cloth lobe (A2, handoff/80). k_cloth = 0 emits NOTHING, so a
    # rung built without it is byte-identical to the parent peach rung -- the
    # inertness proof the build re-checks with cmp.
    kcl = float(knobs.get('k_cloth', 0.0))
    cloth_on = mode == 'add' and kcl > 0.0
    KC = ncl = None
    if cloth_on:
        acl = float(knobs['a_cloth'])
        a0 = float(knobs['cloth_a0'])
        a1 = float(knobs['cloth_a1'])
        if not a1 > a0:
            die(f"cloth_a1 ({a1}) must exceed cloth_a0 ({a0})")
        cbeta = float(knobs.get('cloth_defres', 1.0))
        if not 0.0 <= cbeta <= 1.0:
            die(f"cloth_defres must be in [0, 1], got {cbeta}")
        KC = dict(K)
        KC.update(cap=C(float(knobs['cloth_max'])),
                  inv2a=C(1.0 / (2.0 * acl)),
                  pre=C((2.0 + 1.0 / acl) / (2.0 * math.pi)),
                  ra0=C(a0), rspan=C(1.0 / (a1 - a0)), zero=zero)
        kcl_id = C(kcl)
        f0max_id = C(float(knobs['cloth_f0max']))
        cbeta_id = C(cbeta) if cbeta not in (0.0, 1.0) else None
        u4, u4d = mod.uconst(4)
        if u4d:
            consts.append(u4d)
        hair_gate, not_skin, not_hair, ns_nh = (mod.new_id() for _ in range(4))
        gate_ins += [
            f"        {hair_gate} = OpIEqual %bool {shift} {u4}",
            f"        {not_skin} = OpLogicalNot %bool {skin_gate}",
            f"        {not_hair} = OpLogicalNot %bool {hair_gate}",
            f"        {ns_nh} = OpLogicalAnd %bool {not_skin} {not_hair}",
        ]
        # Read-only detection, ALL of it before the first replace_all_uses
        # below (GOTCHAS 12): every walk here follows definitions backwards.
        f0cands = lift_f0_phis(mod, find_f0_triples(mod))
        fdsites = find_diffuse_scalars(mod)
        # the damp constant: k * E1_hat * cloth_damp, one number, no LUT.
        # dev/cloth_model.py computes E1_hat and prints the per-view spread
        # this constant collapses (handoff/80 §3).
        damp_k = kcl * float(knobs['cloth_E']) * float(knobs.get('cloth_damp', 1.0))
        damp_id = C(damp_k) if damp_k > 0.0 else None
    edits.append((ins_line, pre_ins + gate_ins))

    sites = P.find_ggx_sites(mod)
    rep = {"ggx_sites": len(sites), "peach_sites": 0, "mode": mode,
           "defres": beta if beta_on else 0.0, "defres_sites": 0,
           "folded": 0, "folded_min": 0, "clamped": 0,
           "k_cloth": kcl if cloth_on else 0.0, "cloth_sites": 0,
           "cloth_damp_k": damp_k if cloth_on else 0.0,
           "cloth_damp_sites": 0, "cloth_fd_sites": len(fdsites) if cloth_on else 0,
           "skipped_shape": [], "skipped_dom": [], "skipped_dup": [],
           "skipped_cloth": [], "skipped_damp": []}
    seen = set()
    for s in sites:
        f = find_sheen_inputs(mod, s)
        if not f:
            rep["skipped_shape"].append(s['line'] + 1)
            continue
        line = f['spec_line']
        fold = _fold_cosine(mod, s, f) if mode == 'add' else None
        bad = [x for x in (f['noh'], f['nol'], f['nov'], dom_id)
               if not cfg.dominates_line(x, line)]
        if bad:
            rep["skipped_dom"].append({"line": line + 1, "ids": bad})
            continue
        if f['spec'] in seen:
            rep["skipped_dup"].append(line + 1)
            continue
        seen.add(f['spec'])
        I = mod.new_id
        ins = []
        c0, c1, nc = _saturate_cosines(mod, gl, ins, K['one'], zero, f)
        rep["clamped"] += nc
        if mode == 'add':
            if fold is not None:
                # reuse the clamped id when this cosine is the one that was
                # clamped, so the fold and the lobe cannot disagree
                fold = c0 if fold == f['nol'] else c1
                rep["folded"] += 1
            else:
                fold = mod.new_id()
                ins.append(f"        {fold} = OpExtInst %float {gl} NMin {c0} {c1}")
                rep["folded_min"] += 1
        lobe = _emit_fuzz_lobe(mod, gl, ins, f['noh'], c0, c1, K)
        if mode == 'mul':
            fac, f1, g, m = I(), I(), I(), I()
            ins += [
                f"        {fac} = OpFMul %float {lobe} {kc}",
                f"        {f1} = OpFAdd %float {K['one']} {fac}",
                f"        {g} = OpSelect %float {skin_gate} {f1} {K['one']}",
                f"        {m} = OpFMul %float {f['spec']} {g}",
            ]
        else:
            ex = I()
            ins.append(f"        {ex} = OpFMul %float {lobe} {kc}")
            if beta_on:
                w = _emit_defres(mod, gl, ins, f['noh'], c0, c1, K, zero, beta_id)
                exw = I()
                ins.append(f"        {exw} = OpFMul %float {ex} {w}")
                ex = exw
                rep["defres_sites"] += 1
            exf = I()
            ins.append(f"        {exf} = OpFMul %float {ex} {fold}")
            ex = exf
            g, m = I(), I()
            ins += [
                f"        {g} = OpSelect %float {skin_gate} {ex} {zero}",
                f"        {m} = OpFAdd %float {f['spec']} {g}",
            ]
            if cloth_on:
                # F0 triple dominating THIS splice, else the site declines --
                # a metal cannot be excluded without one, and an ungated
                # metal would take the lobe through F ~ albedo (a ~25x
                # amplification of a term that is not Fresnel's business).
                f0 = None
                for _, t in f0cands:
                    if all(cfg.dominates_line(x, line) for x in t):
                        f0 = t
                if f0 is None or not cfg.dominates_line(s['alpha'], line):
                    rep["skipped_cloth"].append(line + 1)
                else:
                    lc = _emit_fuzz_lobe(mod, gl, ins, f['noh'], c0, c1, KC)
                    wc = _emit_defres(mod, gl, ins, f['noh'], c0, c1, KC,
                                      zero, cbeta_id) if cbeta > 0.0 else None
                    wr = _emit_ramp(mod, gl, ins, s['alpha'], KC)
                    mx1, mx2, diel, gate = I(), I(), I(), I()
                    ins += [
                        f"        {mx1} = OpExtInst %float {gl} NMax {f0[0]} {f0[1]}",
                        f"        {mx2} = OpExtInst %float {gl} NMax {mx1} {f0[2]}",
                        f"        {diel} = OpFOrdLessThan %bool {mx2} {f0max_id}",
                        f"        {gate} = OpLogicalAnd %bool {ns_nh} {diel}",
                    ]
                    cur = I()
                    ins.append(f"        {cur} = OpFMul %float {lc} {kcl_id}")
                    if wc is not None:
                        nx = I()
                        ins.append(f"        {nx} = OpFMul %float {cur} {wc}")
                        cur = nx
                    for mul in (wr, fold):
                        nx = I()
                        ins.append(f"        {nx} = OpFMul %float {cur} {mul}")
                        cur = nx
                    gsel, m2 = I(), I()
                    ins += [
                        f"        {gsel} = OpSelect %float {gate} {cur} {zero}",
                        f"        {m2} = OpFAdd %float {m} {gsel}",
                    ]
                    m = m2
                    rep["cloth_sites"] += 1
        replace_all_uses(mod, f['spec'], m, line)
        edits.append((line, ins))
        rep["peach_sites"] += 1
    if rep["peach_sites"] == 0:
        die(f"{mod.name}: no GGX site could take the peach fuzz "
            f"({len(sites)} sites, all declined)")

    # ---- the diffuse damp (23 §4's ship requirement) -----------------------
    #   f_d *= 1 - select(notskin && nothair, k*E1*wr, 0)
    # No dielectric test here on purpose: a metal's diffuse COLOUR is
    # albedo*(1-metallic) = 0, so damping a metal's f_d scales zero and the
    # two extra instructions of an F0 read would buy nothing.
    if cloth_on and damp_id is not None:
        dseen = set()
        for d in fdsites:
            # two Burley chains converging on ONE scalar would make the second
            # replace_all_uses a silent no-op while still counting as coverage
            # (the 08-DUAL-LOBE lesson). Census says zero; assert it anyway.
            if d['fd'] in dseen:
                rep["skipped_damp"].append(d['line'] + 1)
                continue
            dseen.add(d['fd'])
            if not (cfg.dominates_line(d['rough'], d['line'])
                    and cfg.dominates_line(dom_id, d['line'])):
                rep["skipped_damp"].append(d['line'] + 1)
                continue
            I = mod.new_id
            ins = []
            al = I()
            ins.append(f"        {al} = OpFMul %float {d['rough']} {d['rough']}")
            wr = _emit_ramp(mod, gl, ins, al, KC)
            amt, sel, fac, nfd = I(), I(), I(), I()
            ins += [
                f"        {amt} = OpFMul %float {wr} {damp_id}",
                f"        {sel} = OpSelect %float {ns_nh} {amt} {zero}",
                f"        {fac} = OpFSub %float {KC['one']} {sel}",
                f"        {nfd} = OpFMul %float {d['fd']} {fac}",
            ]
            replace_all_uses(mod, d['fd'], nfd, d['line'])
            edits.append((d['line'], ins))
            rep["cloth_damp_sites"] += 1
    return consts, edits, rep


# ------------------------------------------------- probe-gi (handoff/48 §8)
# Hue-coded, class-1-gated paint at the RAYGEN radiance writes, one colour
# per FAMILY, to name the writer of bounce-lit skin in one launch:
#
#   rgs_reference_main            x12  green  x(0.30, 3.00, 0.30)
#   rgs_restirgi_* diffuse        x4   red    x(3.00, 0.30, 0.30)
#   rgs_restirgi_* specular       x4   blue   x(0.30, 0.30, 3.00)
#
# The compute probe is OFF in this rung -- the launch is only about raygens.
#
# Structure, measured offline 2026-08-30 (handoff/50), where it corrects 48:
#
#   * 48 §4 says the restirgi class shift "dominates the image write". It
#     does NOT, in any of the 8: dxil-spirv guards the G-buffer fetch and
#     the write reads through 1-2 levels of guarded-fetch OpPhi (the GOTCHAS
#     "value a shader tests is not the value it computed" trap, again). The
#     dominating form is the phi; every operand is the class or %uint_0, and
#     0 is not skin, so gating on it is safe. find_gi_class walks phis to a
#     fixpoint and each write is gated on a form PROVEN to dominate it.
#
#   * 48 §4's "the specular variants write YCoCg" is a half-truth that would
#     have broken the paint: in each restirgi family of 4, two permutations
#     write plain RGB (single arm, NMin/NMax fp16-clamped) and two carry
#     BOTH encodings and pick at runtime from a CBV word -- an RGB arm and a
#     YCoCg dot-product arm merged by phis at the write. A channel multiply
#     at such a write would tint one encoding and corrupt the other. Both
#     arms consume one guarded RGB triple (e.g. %1433/34/35 in 038867e9),
#     so the paint goes THERE, upstream of the encode split: multiply the
#     triple, replace its downstream uses, and both arms carry the hue.
#     The shape is DETECTED per write, never assumed from the family.
#
#   * Two rgs_reference_main permutations (40c6faab, ab7f1822) write NO
#     image radiance at all: they accumulate fixed-point (x10000) radiance
#     through OpAtomicIAdd into an SSBO at registers[5]+9, and their only
#     image writes are constant-zero early-outs. Painting an unread atomic
#     contract is the GOTCHAS rule-5 trap; both had 0 dispatches in every
#     journal to date. They ship in the rung as UNPAINTED passthroughs of
#     the SER source so the serve stays uniform. If the launch journal shows
#     either one dispatching, a green null on the S2 face is NOT
#     interpretable as "reference does not write it".
GI_TINTS = {
    'reference':   (0.30, 3.00, 0.30),
    'gi-diffuse':  (3.00, 0.30, 0.30),
    'gi-specular': (0.30, 0.30, 3.00),
}
GI_FAMILY = {}
for _h in ('d622fb9e1dcb8cd0', 'd002cc05eb940591', '4270b745d11a5e8a',
           '40c6faab52a13874', '3d871a3170bc5815', '25b54fc4a17688df',
           '996a3b16253c3e7f', '852b31a841b85b26', '4103c8860c3909e4',
           '21a92f1a77eb4c22', '1271d3815051da17', 'ab7f1822eeb0331b'):
    GI_FAMILY[_h] = 'reference'
for _h in ('006ba4e3c8c05205', '038867e9a3bf0626', '5e1e98e44d854712',
           'fc60b8a0b56529b8'):
    GI_FAMILY[_h] = 'gi-diffuse'
for _h in ('1ca55ed0fc70d56f', 'a3b07b0f4f4f79b8', '174dee89ec119981',
           '9d117caf3ef46c59'):
    GI_FAMILY[_h] = 'gi-specular'
GI_PASSTHROUGH = ('40c6faab52a13874', 'ab7f1822eeb0331b')

FP16_MAX = 65504.0
YCC_ROLES = {'Y': (0.25, 0.5, 0.25), 'Co': (0.5, 0.0, -0.5),
             'Cg': (-0.25, 0.5, -0.25)}


def find_gi_class(mod, family):
    """(class_value, dominating_forms, how) for the paint gate.

    reference: the IEqual-consumed `gbuf.y >> 5` (find_class_shift; 48 §5's
    %439). restirgi: the shift consumed by the module's single material-class
    OpSwitch (cases 1=skin and 4=hair) -- these modules also test NEIGHBOUR
    pixels' classes through IEqual, so the switch, not the first IEqual, is
    what names the primary surface. The returned set is the shift plus every
    OpPhi %uint whose operands are all in the set or %uint_0 (guarded-fetch
    merges), to a fixpoint; the caller picks whichever form dominates a
    given site.
    """
    if family == 'reference':
        shift, _ = P.find_class_shift(mod)
        how = 'ieq-shift'
    else:
        hits = []
        for ln in mod.lines:
            m = re.match(r'\s*OpSwitch (%\d+) %\d+((?: \d+ %\d+)+)\s*$', ln)
            if not m:
                continue
            if not {'1', '4'} <= set(re.findall(r'(\d+)(?= %)', m.group(2))):
                continue
            sid = m.group(1)
            _, sd = mod.find_def(sid)
            m2 = re.match(r'OpShiftRightLogical %uint (%\d+) %uint_5\s*$',
                          sd or '')
            if not m2:
                continue
            _, ed = mod.find_def(m2.group(1))
            m3 = re.match(r'OpCompositeExtract %uint (%\d+) 1\s*$', ed or '')
            if not m3:
                continue
            _, fd = mod.find_def(m3.group(1))
            if not (fd and fd.startswith('OpImageFetch %v4uint')):
                continue
            hits.append(sid)
        if len(hits) != 1:
            die(f"{mod.name}: expected exactly one material-class OpSwitch "
                f"(cases 1 and 4 on a fetched >>5), found {len(hits)}")
        shift, how = hits[0], 'class-switch'
    vals = {shift}
    changed = True
    while changed:
        changed = False
        for ln in mod.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+)$', ln)
            if not m or m.group(1) in vals:
                continue
            ops = [v for v, _b in re.findall(r'(%\w+) (%\w+)', m.group(2))]
            if ops and all(v in vals or v == '%uint_0' for v in ops):
                vals.add(m.group(1))
                changed = True
    return shift, vals, how


def _gi_float_const(mod, tok):
    _, d = mod.find_def(tok)
    m = re.match(r'OpConstant %float (\S+)\s*$', d or '')
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _gi_vec3(mod, vid):
    """(v0, v1, v2) floats if vid is a 3-vector of float constants."""
    _, d = mod.find_def(vid)
    m = re.match(r'Op(?:CompositeConstruct|ConstantComposite) %v3float '
                 r'(%\S+) (%\S+) (%\S+)\s*$', d or '')
    if not m:
        return None
    vals = [_gi_float_const(mod, t) for t in m.groups()]
    return None if None in vals else tuple(vals)


def _gi_leaves(mod, cid, depth=4):
    """Resolve cid through float OpPhis: (dot_ids, plain_ids). Constant
    leaves are dropped (a zero arm is not evidence of anything)."""
    dots, plains = [], []
    _, d = mod.find_def(cid)
    if d is None:
        plains.append(cid)
        return dots, plains
    if d.startswith('OpDot %float'):
        dots.append(cid)
    elif d.startswith('OpPhi %float') and depth > 0:
        ops = [v for v, _b in re.findall(r'(%\w+) (%\w+)',
                                         d[len('OpPhi %float'):])]
        for v in ops:
            if _gi_float_const(mod, v) is not None:
                continue
            sub = _gi_leaves(mod, v, depth - 1)
            dots += sub[0]
            plains += sub[1]
    elif d.startswith('OpConstant '):
        pass
    else:
        plains.append(cid)
    return dots, plains


def _gi_dot_parts(mod, dot_id):
    """(role, triple) for one encode dot: which YCoCg row its constant
    vector is, and the 3 value ids the other operand constructs."""
    _, d = mod.find_def(dot_id)
    m = re.match(r'OpDot %float (%\S+) (%\S+)\s*$', d or '')
    if not m:
        return None, None
    role = triple = None
    for vid in m.groups():
        vec = _gi_vec3(mod, vid)
        if vec is not None:
            for rname, ref in YCC_ROLES.items():
                if all(abs(a - b) < 1e-4 for a, b in zip(vec, ref)):
                    role = rname
            continue
        _, cd = mod.find_def(vid)
        mc = re.match(r'OpCompositeConstruct %v3float (%\S+) (%\S+) (%\S+)\s*$',
                      cd or '')
        if mc:
            triple = mc.groups()
    return role, triple


def _gi_zeroish(mod, comp):
    return comp == '%float_0' or _gi_float_const(mod, comp) == 0.0


def build_gi_paint(mod, cfg, writes):
    """The per-family hue multiply, gated on material class 1, at every
    radiance write. Constant-zero early-out writes and scalar-broadcast
    hit-distance writes are skipped and reported; everything else either
    paints or DIES -- an unpaintable radiance write would make the launch
    read as a family null, which is worse than no build."""
    h = (mod.ident or '').split('.')[0]
    family = GI_FAMILY.get(h)
    if family is None:
        die(f"{mod.name}: {h} is not a probe-gi target module")
    if h in GI_PASSTHROUGH:
        die(f"{mod.name}: atomic-SSBO accumulator permutation -- ship the "
            f"source unpainted (the wrapper does); painting its atomic "
            f"contract is not built")
    tint = GI_TINTS[family]

    glsl = mod.glsl
    if glsl is None:
        for ln in mod.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpExtInstImport "GLSL.std.450"', ln)
            if m:
                glsl = m.group(1)
                break
    if glsl is None:
        die(f"{mod.name}: no GLSL.std.450 import -- cannot emit clamps")

    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one = C(1.0)
    fmax, fmin = C(FP16_MAX), C(-FP16_MAX)
    tids = [C(x) for x in tint]
    uid1, ud = mod.uconst(1)
    if ud:
        consts.append(ud)

    shift, cands, how = find_gi_class(mod, family)
    rep = {"family": family, "tint": list(tint), "class_how": how,
           "class_value": shift, "painted": [], "skipped_zero": [],
           "skipped_scalar": [], "skipped_dom": []}
    I = mod.new_id

    def clamp(ins, x):
        a, b = I(), I()
        ins.append(f"        {a} = OpExtInst %float {glsl} NMax {x} {fmin}")
        ins.append(f"        {b} = OpExtInst %float {glsl} NMin {a} {fmax}")
        return b

    def gate_for(line, what):
        ok = sorted(x for x in cands if cfg.dominates_line(x, line))
        if not ok:
            rep["skipped_dom"].append(line + 1)
            die(f"{mod.name}: no class form dominates {what} at line "
                f"{line + 1} -- the paint cannot be gated there")
        g = I()
        return ok[0], g, f"        {g} = OpIEqual %bool {ok[0]} {uid1}"

    # Classify every write BEFORE any emission: the dual-arm paint rewrites
    # uses in place (replace_all_uses), and a detector that walks defs after
    # that would dead-end silently (GOTCHAS rule 12).
    plans = []
    for w in writes:
        if w['comps'] is None:
            die(f"{mod.name}: image write at line {w['line'] + 1} has a "
                f"non-construct texel -- unrecognized, refusing")
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            rep["skipped_zero"].append(w['line'] + 1)
            continue
        if c[0] == c[1] == c[2]:
            rep["skipped_scalar"].append(w['line'] + 1)
            continue
        leaves = [_gi_leaves(mod, x) for x in c[:3]]
        dots = [d for dd, _p in leaves for d in dd]
        if not dots:
            plans.append(('rgb', w, None))
            continue
        # At least one runtime-selected encode arm. Paint every SOURCE the
        # arms read: the YCoCg encode's input triple, plus each plain arm's
        # leaf values, each bound to the channel its comp position implies.
        # (The arms are sibling NaN-guard/clamp copies of one base radiance;
        # the ancestry check below dies if that ever stops being true, since
        # nested targets would tint twice.)
        roles, triples = set(), set()
        for d in dots:
            role, triple = _gi_dot_parts(mod, d)
            if role is None or triple is None:
                die(f"{mod.name}: encode dot {d} at write line "
                    f"{w['line'] + 1} has no recognizable YCoCg row vector "
                    f"or no value triple -- refusing")
            roles.add(role)
            triples.add(triple)
        if roles != {'Y', 'Co', 'Cg'} or len(triples) != 1:
            die(f"{mod.name}: write at line {w['line'] + 1}: encode dots "
                f"give roles {sorted(roles)} over {len(triples)} distinct "
                f"triples -- not one YCoCg encode, refusing")
        triple = triples.pop()
        targets = {}          # id -> channel

        def bind(tid, ch, wline):
            if targets.get(tid, ch) != ch:
                die(f"{mod.name}: write at line {wline + 1}: {tid} feeds "
                    f"two different colour channels -- refusing")
            targets[tid] = ch
        for ch2, tid in enumerate(triple):
            bind(tid, ch2, w['line'])
        for ch2, (_dd, pp) in enumerate(leaves):
            for tid in pp:
                bind(tid, ch2, w['line'])
        plans.append(('dual', w, targets))

    # id -> def line, computed once (find_def is a linear scan; the ancestry
    # walk below would be quadratic through it on a 75k-line module)
    def_line = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=', ln)
        if m:
            def_line[m.group(1)] = i
    painted_ids, painted_results = {}, set()
    for kind, w, kind_targets in plans:
        if kind == 'rgb':
            c = w['comps']
            ins = []
            cand, g, gline = gate_for(w['line'], "the radiance write")
            ins.append(gline)
            newc = []
            for ch in range(3):
                s, n = I(), I()
                ins.append(f"        {s} = OpSelect %float {g} {tids[ch]} {one}")
                ins.append(f"        {n} = OpFMul %float {c[ch]} {s}")
                newc.append(clamp(ins, n))
            nt = I()
            ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                       f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
            edits.append((w['line'] - 1, ins))
            mod.lines[w['line']] = re.sub(
                r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
                mod.lines[w['line']])
            rep["painted"].append({"line": w['line'] + 1, "kind": "rgb",
                                   "gate_on": cand})
        else:
            done = []
            for tid, ch in sorted(kind_targets.items()):
                if tid in painted_ids:
                    if painted_ids[tid] != ch:
                        die(f"{mod.name}: {tid} painted for channel "
                            f"{painted_ids[tid]} by an earlier write, now "
                            f"wanted for channel {ch} -- refusing")
                    continue
                # No target may derive from another: replace_all_uses on the
                # ancestor would already tint this one, and painting it again
                # would square the tint.
                seen, queue = set(), [tid]
                while queue:
                    x = queue.pop()
                    dl = def_line.get(x)
                    if dl is None:
                        continue
                    for ref in re.findall(r'%\w+', mod.lines[dl])[1:]:
                        if ref in seen:
                            continue
                        seen.add(ref)
                        if (ref in kind_targets and ref != tid) or \
                           ref in painted_ids or ref in painted_results:
                            die(f"{mod.name}: paint target {tid} derives "
                                f"from paint target {ref} -- nested targets "
                                f"would tint twice, refusing")
                        if len(seen) < 400:
                            queue.append(ref)
                at = def_line.get(tid)
                if at is None:
                    die(f"{mod.name}: paint target {tid} has no definition")
                ins = []
                cand, g, gline = gate_for(at, f"paint target {tid}")
                ins.append(gline)
                s, n = I(), I()
                ins.append(f"        {s} = OpSelect %float {g} {tids[ch]} {one}")
                ins.append(f"        {n} = OpFMul %float {tid} {s}")
                p = clamp(ins, n)
                edits.append((at, ins))
                uses = replace_all_uses(mod, tid, p, at)
                painted_ids[tid] = ch
                painted_results.add(p)
                done.append({"id": tid, "channel": ch, "at_line": at + 1,
                             "uses_rewritten": uses, "gate_on": cand})
            rep["painted"].append({"line": w['line'] + 1, "kind": "dual-arm",
                                   "targets": done})

    if not rep["painted"]:
        die(f"{mod.name}: no radiance write painted "
            f"({len(rep['skipped_zero'])} zero, "
            f"{len(rep['skipped_scalar'])} scalar writes skipped)")
    return consts, edits, rep


# ------------------------------------------------------------------ driver
KNOBS = dict(k_sheen=8.0, a_sheen=0.35, sheen_max=25.0,
             gain_hi=3.2, gain_lo=0.45, gain_black=0.05,
             # peach: k_peach scales the ADDED lobe in --peach-mode add
             # (5-17% of the local diffuse on a cheek rim -- dev/fuzz_model.py
             # prints the table), and the multiplicative amplitude in mode
             # mul, where the 58-era rung used 0.15. peach_max caps D*V before
             # k: a division guard, and it only binds past ~85 deg of view.
             # defres in [0,1] cancels that share of the module's own Schlick
             # ramp on the ADDED lobe (0 = the wide 72-era rung, 1 = targeted:
             # the front-lit band unchanged, the backlit rim cut 2.5x).
             k_peach=1.0, a_peach=0.35, peach_max=0.5, defres=1.0,
             # cloth (A2, handoff/80): k_cloth = 0 is byte-inert -- nothing
             # is emitted at all, so a rung built without it cmp-matches its
             # parent. k_cloth 0.5 puts the lobe at 11-13% of the local
             # diffuse at a grazing view and 0.2% head-on; 1.0 doubles it.
             # a_cloth is the Charlie roughness (tighter than the skin fuzz's
             # 0.35: fabric's grazing bloom is narrower than a face's).
             # cloth_a0/a1 are the ROUGHNESS RAMP in alpha (= authored
             # roughness squared): 0.10 -> 0.30 is authored 0.32 -> 0.55, so
             # glass and clearcoat get zero and fabric/concrete get all of it.
             # cloth_f0max is the dielectric test on max3(F0); every metal
             # sits at its albedo, >= 0.2. cloth_E is E1_hat from
             # dev/cloth_model.py -- the cosine-weighted directional albedo
             # of the capped, ramped, Schlick-cancelled lobe at k=1, which is
             # what the diffuse damp removes. cloth_damp = 0 turns the damp
             # off without touching the lobe.
             k_cloth=0.0, a_cloth=0.25, cloth_max=0.5, cloth_defres=1.0,
             cloth_a0=0.10, cloth_a1=0.30, cloth_f0max=0.09,
             cloth_E=0.0072, cloth_damp=1.0)
TIERS = ('sub', 'c1sub', 'cls', 'sheen', 'both', 'gi', 'peach')


def process(path, outdir, tier, knobs, do_rt=True, hunt_classes=None,
            peach_mode='add'):
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
    writes = find_image_writes(mod) if tier not in ('sheen', 'peach') else None

    consts, edits = [], []
    if tier == 'sheen':
        consts, edits, rep['sheen'] = build_sheen(mod, cfg, knobs)
    elif tier == 'peach':
        consts, edits, rep['peach'] = build_peach(mod, cfg, knobs, peach_mode)
    elif tier == 'gi':
        consts, edits, rep['gi'] = build_gi_paint(mod, cfg, writes)
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
    ap.add_argument('--peach-mode', default='add', choices=('add', 'mul'),
                    help='--tier peach: add the sheen lobe (default) or the '
                         '58-era multiplicative form')
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
                       do_rt=not a.no_roundtrip_check, hunt_classes=hunt,
                       peach_mode=a.peach_mode)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
