#!/usr/bin/env python3
"""Cavity contact shadow v2: a cosine-weighted micro-occlusion CONE.

handoff/88. Supersedes patch_cavity.py (handoff/85), which shipped one ray
along the sun-disc direction and measured +7% darkening at the lip seam and
nothing at all on the modelled overhangs. Three changes, each with its own
reason:

1. COVERAGE 10/12 -> 12/12.  85's detector anchored on the module's own
   `(word & ~31) == 160` class compare. Two permutations -- the SER ones,
   which carry OpReorderThreadWithHintNV -- never form that compare, so 85
   shipped them byte-verbatim. On 2026-09-01 09:16 the game dispatched
   40c6faab52a13874 and the "k=1.0" capture contained no cavity code at all.
   The material word is in all twelve; those two just consume it as a
   reorder hint. So the anchor moves to the mode-independent half
   (GOTCHAS 4): the bindless MATERIAL G-buffer fetch,
   `table[root_const[1] + 5]`, extract 1, `>> 5` == the class. Verified
   present exactly once in 12/12, and -- via dev/cfg_dom.py -- verified to
   DOMINATE the splice in 12/12, so the 20-instruction clone 85 emitted per
   module is not needed either. `(word >> 5) == 1` is the same predicate as
   85's `(word & 0xFFFFFFE0) == 32`.

2. THE CONE.  85 traced along L, the sun-disc sample. At a 0.53 deg disc a
   1 mm seam wall subtends almost nothing from L, which is exactly the
   7%-of-a-possible-85% that was measured. The occluded FRACTION was the
   limit, never k. So this traces up to four rays: L itself, one tilted
   toward the tangent plane (the HORIZON tap -- a seam wall subtends a large
   angle from a grazing direction, and this tap does most of the work), and
   two lateral. The taps are combined as a cosine-weighted AVERAGE, not a
   min: a min re-binarizes per pixel, over-darkens, and hangs a contact halo
   on every silhouette. Each tap is weighted by max(dot(tap, N), 0), which
   naturally kills any tap that has swung below the horizon.

   Basis: T = normalize(N - L*(N.L)) is the in-plane direction from L toward
   N, so -T is "toward the horizon"; B = cross(L, T) is unit by construction
   and is exactly zero when T is (no Normalize on B, so L parallel N cannot
   make a NaN direction). Weights are analytic -- w = cos(alpha +/- theta)
   from cosA and sinA -- rather than four more dot products.

   This is short-range directional AO on the sun term, not a soft shadow.
   Saying so plainly: it is the right cheat at a 0.53 deg source, and it is
   a cheat.

3. THE RAMP.  85's factor was binary: a hit at 5.9 mm darkened exactly as
   much as one at 0.1 mm. Here occ_i = saturate(1 - t_i/tmax), so the term
   reads as depth and the per-sample variance drops -- which is where the
   user's "noisier in shadow" complaint actually lands.

Also: TMIN 0.5 mm -> 0.1 mm. 85 argued 0.5 mm from a worst-case float
position error of ~1 um, i.e. a 500x margin, while donating a third of a
1.5 mm seam to the tmin. 0.1 mm still leaves 100x, and the structural guard
is unchanged and is the real one: CullBackFacingTriangles means the only way
to re-hit your own triangle is from underneath, which is culled before any
hit shader runs. At the weight floor (0.05, i.e. ~2.9 deg above the surface)
the grazing re-hit distance is ~1um/0.05 = 20 um, still 5x under tmin.

IDENTITY WHEN DEAD is stronger than 85's, not weaker. Every tap's t is
pre-armed to 10000 and occ_i = 0 unless TLOW < t < tmax, so a false gate
gives num = 0. On top of that the combined occlusion is passed through
    occ = OpSelect(gate, NClamp(num/max(den,1e-6), 0, 1), 0.0)
so no upstream NaN can reach the factor, and
    fac = 1 - k*0 = 1.0
exactly, making every rewritten site compute src*1.0 == src bit-for-bit.
The gate also feeds cullMask (39 or 0) and the tap directions fall back to
L when it is false, so a garbage G-buffer normal on a non-skin pixel can
never produce a NaN ray direction.

NO PRNG DRAW is preserved. The taps are deterministic rotations of the
engine's own NEE direction in a basis built from the harvested primary-hit
normal. Nothing is sampled, so the module's LCG chain is untouched and every
downstream sample's noise stays bit-identical to the base.

  ./dev/patch_cavity2.py <in.spvasm> --k 0.85 --tmax 0.006 --taps 4 \
      --theta 12 --outdir DIR
  --k 0 emits NOTHING (all detectors still run): the byte-identity control.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
import cfg_dom
from patch_cavity import find_sun_branch, find_sun_sites
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

TMIN = 1e-4     # 0.1 mm -- see the docstring's two-failure-mode argument
TLOW = 5e-5     # lower validity bound, below tmin: a miss that wrote 0 fails closed
CULL = 16       # CullBackFacingTrianglesKHR
MASK = 39       # the engine's own sun-shadow cullMask (enumerated, all 12)
WMIN = 0.05     # cosine-weight floor: drops taps at/below the horizon
EPS  = 1e-6     # divisor guard
LOCAL_TRACE_CANDIDATES = 3   # literal-mask-39 traces per reference raygen
LOCAL_SITES_EXPECTED   = 2   # ...of which carry the vis-scalar shading shape


def find_class_word(mod, fs, fe):
    """The material class, anchored on the MODE-INDEPENDENT half (GOTCHAS 4).

    The bindless G-buffer material fetch is table[root_const[1] + 5]; its
    component 1 is the material word and `word >> 5` is the class. All twelve
    permutations build exactly this; ten of them go on to compare it against
    160, the two SER ones feed it to OpReorderThreadWithHintNV instead -- and
    it was that compare, not the fetch, that 85 anchored on.

    Returns (class_word_id, fetch_id, shift_line). Dies unless there is
    exactly one, so a differing permutation is a finding, not a guess.
    """
    hits = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpShiftRightLogical %uint (%\w+) '
                     r'%uint_5\s*$', mod.lines[i])
        if not m:
            continue
        _, ed = mod.find_def(m.group(2))
        em = re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', ed or '')
        if not em:
            continue
        _, fd = mod.find_def(em.group(1))
        fm = re.match(r'OpImageFetch %v4uint (%\w+) %\w+ Lod %uint_0\s*$',
                      fd or '')
        if not fm:
            continue
        _, imd = mod.find_def(fm.group(1))
        lm = re.match(r'OpLoad %\w+ (%\w+)\s*$', imd or '')
        if not lm:
            continue
        _, acd = mod.find_def(lm.group(1))
        am = re.match(r'OpAccessChain %_ptr_UniformConstant_\w+ %\w+ (%\w+)\s*$',
                      acd or '')
        if not am:
            continue
        _, ixd = mod.find_def(am.group(1))
        ixm = re.match(r'OpIAdd %uint (%\w+) %uint_5\s*$', ixd or '')
        if not ixm:
            continue
        _, bd = mod.find_def(ixm.group(1))
        bm = re.match(r'OpLoad %uint (%\w+)\s*$', bd or '')
        if not bm:
            continue
        _, pcd = mod.find_def(bm.group(1))
        if not re.match(r'OpAccessChain %_ptr_PushConstant_uint %\w+ %uint_1\s*$',
                        pcd or ''):
            continue
        hits.append((m.group(1), em.group(1), i))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} bindless-slot-5 class words, expected 1")
    return hits[0]


def _fetch_coord(mod, fetch_id):
    _, d = mod.find_def(fetch_id)
    m = re.match(r'OpImageFetch %v4uint %\w+ (%\w+) Lod %uint_0\s*$', d or '')
    if not m:
        die(f"{mod.name}: {fetch_id} is not a v4uint Lod-0 image fetch: {d}")
    # The coordinate CONSTRUCT is duplicated alongside the fetch, so its id
    # differs between the two copies; its operands do not. Compare those.
    _, cd = mod.find_def(m.group(1))
    cm = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$', cd or '')
    if not cm:
        die(f"{mod.name}: fetch coord {m.group(1)} is not a v2uint "
            f"construct: {cd}")
    return (cm.group(1), cm.group(2))


def cross_check_legacy(mod, fs, fe, fetch_id):
    """Where the module DOES form 85's `& ~31 == 160` compare, it must be
    reading the SAME TEXEL we anchored on.

    It is a different instruction: the compiler emits the slot-5 fetch twice
    -- once before the bounce loop, once inside it -- and never CSEs them, so
    85 cloned the inner one and this anchors the outer. They are the same
    fetch of the same texture at the same coordinate id, which is what this
    asserts. Ten of twelve exercise it; the two SER permutations form no
    compare and return None.

    This is the only thing tying the new anchor to the gate that was on
    screen, so it asserts equality of the coordinate rather than merely that
    both read slot 5."""
    try:
        legacy = E.find_class_fetch(mod, fs, fe)
    except SystemExit:
        return None
    ours, theirs = _fetch_coord(mod, fetch_id), _fetch_coord(mod, legacy)
    if ours != theirs:
        die(f"{mod.name}: legacy class fetch {legacy} reads texel {theirs}, "
            f"slot-5 anchor {fetch_id} reads {ours}")
    return legacy


UNIT_ONE = ('%half_0x1p_0', '%float_1')


def find_path_counter(mod, fs, fe):
    """The BOUNCE counter -- the path loop's own, not the sample loop's.

    `rgs_reference_main` nests two counted loops that both contain the sun
    NEE, and `E.find_bounce_counter` documents its tie-break as "outermost
    wins", which is the SAMPLE loop. It returns the wrong phi in 5 of the 12
    permutations (89 sec 2), so the gate was `sample == 0` there and the term
    ran at every bounce. This finds the path loop instead, structurally:

      * among counted loops `Op[SU]LessThan(x + 1, bound)` on a back edge
        whose body traces rays, the PATH loop is the one whose header seeds
        exactly 3 fp phis with 1.0 -- the RGB throughput, multiplied down each
        iteration. The sample loop seeds its accumulators with 0 and must seed
        NONE, which is asserted, not assumed;
      * exactly one such loop may exist;
      * its counter is the unique `OpPhi %uint` at that header whose two
        incoming values are exactly {0, <the IAdd from that loop's own exit
        test>} -- interior re-merge phis fail this, header siblings seeded
        from 0 but latched from something else fail it too.

    Verified unique in 12/12 on the standing base.
    """
    labels = {}
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', mod.lines[i])
        if m:
            labels[m.group(1)] = i
    hot, cold = [], []
    for i in range(fs, fe):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)',
                     mod.lines[i])
        if not m:
            continue
        cond, t0, t1 = m.groups()
        _, cd = mod.find_def(cond)
        cm = re.match(r'Op[SU]LessThan %bool (%\w+) (%\w+)\s*$', cd or '')
        if not cm:
            continue
        inc = cm.group(1)
        _, ad = mod.find_def(inc)
        if not re.match(r'OpIAdd %uint %\w+ %uint_1\s*$', ad or ''):
            continue
        for tgt in (t0, t1):
            hi = labels.get(tgt)
            if hi is None or hi >= i:
                continue
            if not any('OpTraceRayKHR' in mod.lines[j] for j in range(hi, i)):
                continue
            ones, uphis = 0, []
            for j in range(hi + 1, fe):
                if not re.match(r'\s*\S+\s*=\s*OpPhi ', mod.lines[j]):
                    break
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(?:half|float) (.+?)\s*$',
                              mod.lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(1).split()[0::2]):
                    ones += 1
                um = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+?)\s*$',
                              mod.lines[j])
                if um:
                    uphis.append((um.group(1), um.group(2).split()[0::2]))
            (hot if ones == 3 else cold).append((tgt, ones, inc, uphis))
    if len(hot) != 1:
        die(f"{mod.name}: {len(hot)} throughput-seeded path loops, expected 1 "
            f"(candidates {[(h[0], h[1]) for h in hot + cold]})")
    for c in cold:
        if c[1] != 0:
            die(f"{mod.name}: non-path loop {c[0]} seeds {c[1]} phis with 1.0 "
                f"-- the throughput discriminator is not clean")
    hdr, _, inc, uphis = hot[0]
    ctr = [pid for pid, vals in uphis if set(vals) == {'%uint_0', inc}]
    if len(ctr) != 1:
        die(f"{mod.name}: {len(ctr)} bounce-counter phis at path header {hdr} "
            f"with incomings {{0, {inc}}}, expected 1")
    return ctr[0], hdr


def find_local_sites(mod, fs, fe, nee):
    """The engine's LOCAL-LIGHT next-event shadow rays, and their visibility
    scalar.

    The sun is not the only direct-lighting path in this raygen. Point / spot /
    area lights are shaded from a 64-byte light struct array read by
    OpRawAccessChainNV, and each has its own shadow ray with a LITERAL
    cullMask of 39 (the sun's mask is a computed OpSelect on the backlit bool,
    which is what keeps this detector off it).

    The shape, asserted whole -- any deviation is a finding, not a guess:

        OpTraceRayKHR as %uint_12 %uint_39 %uint_1 %uint_1 %uint_0 \
                      org tmin dir tmax pay
        t = OpLoad %float <OpInBoundsAccessChain . pay %uint_3>
        e = OpFOrdEqual %bool t %float_10000        (miss => visible)
        v = OpSelect %float e %float_1 %float_0
        _ = OpFMul %float v r0                      (x3, the light's radiance)

    `v` is a SINGLE scalar multiplied into all three channels, which makes
    this a cleaner splice than the sun's: one FMul on `v` reaches the whole
    light term. `v` is required to have exactly three uses, so that is
    provable rather than hoped for (GOTCHAS 3).

    Returns a list of dicts. Dies unless the module has exactly
    LOCAL_TRACE_CANDIDATES literal-mask-39 traces of which exactly
    LOCAL_SITES_EXPECTED carry this shape -- see 88 sec 5b for what the
    remaining one is and why it is deliberately NOT patched.
    """
    cand, out = [], []
    pat = (r'\s*OpTraceRayKHR (%\w+) %uint_12 %uint_39 %uint_1 %uint_1 '
           r'%uint_0 (%\w+) (%\w+) (%\w+) (%\w+) (%\w+)\s*$')
    for i in range(fs, fe):
        m = re.match(pat, mod.lines[i])
        if not m:
            continue
        accel, org, tmin, dirid, tmaxid, pay = m.groups()
        cand.append(i)
        if i == nee["line"]:
            die(f"{mod.name}: the sun NEE at line {i+1} matched the "
                f"local-light trace pattern -- the mask discriminator is gone")

        # t = OpLoad %float <member-3 chain on THIS trace's payload>
        nxt = [j for j in range(i + 1, min(i + 8, fe))]
        tm = None
        for j in nxt:
            g = re.match(r'\s*(%\w+)\s*=\s*OpLoad %float (%\w+)\s*$',
                         mod.lines[j])
            if g:
                tm = g
                break
        if not tm:
            continue
        _, cd = mod.find_def(tm.group(2))
        if not re.match(r'OpInBoundsAccessChain %\w+ ' + re.escape(pay)
                        + r' %uint_3\s*$', cd or ''):
            continue
        t = tm.group(1)

        eq = None
        for j in range(i + 1, min(i + 10, fe)):
            g = re.match(r'\s*(%\w+)\s*=\s*OpFOrdEqual %\w+ '
                         + re.escape(t) + r' %float_10000\s*$', mod.lines[j])
            if g:
                eq = g.group(1)
                break
        if eq is None:
            continue
        vis = None
        for j in range(i + 1, min(i + 12, fe)):
            g = re.match(r'\s*(%\w+)\s*=\s*OpSelect %float '
                         + re.escape(eq) + r' %float_1 %float_0\s*$',
                         mod.lines[j])
            if g:
                vis = g.group(1)
                break
        if vis is None:
            continue

        muls = []
        for j in range(fs, fe):
            g = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float '
                         + re.escape(vis) + r' (%\w+)\s*$', mod.lines[j])
            if g:
                muls.append((j, g.group(1), g.group(2)))
        if len(muls) != 3:
            die(f"{mod.name}: local-light site at line {i+1}: visibility "
                f"{vis} feeds {len(muls)} FMuls, expected exactly 3")
        uses = 0
        for ln in mod.lines:
            if re.match(r'\s*' + re.escape(vis) + r'\s*=', ln):
                continue
            uses += len(re.findall(re.escape(vis) + r'(?![0-9A-Za-z_])', ln))
        if uses != 3:
            die(f"{mod.name}: local-light site at line {i+1}: visibility "
                f"{vis} has {uses} uses, expected exactly 3 (the FMuls)")
        out.append({"trace_line": i, "accel": accel, "org": org,
                    "dir": dirid, "pay": pay, "eq": eq, "vis": vis,
                    "muls": muls, "first_mul": min(m[0] for m in muls)})

    if len(cand) != LOCAL_TRACE_CANDIDATES:
        die(f"{mod.name}: {len(cand)} literal-mask-39 traces, expected "
            f"{LOCAL_TRACE_CANDIDATES} (lines "
            f"{[c+1 for c in cand]})")
    if len(out) != LOCAL_SITES_EXPECTED:
        die(f"{mod.name}: {len(out)} local-light shading sites of the known "
            f"shape, expected {LOCAL_SITES_EXPECTED}")
    return out


def build(mod, k, tmax, taps, theta_deg, ramp, all_lights=False,
          k_local=None, gate='bounce'):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()          # the memo is keyed on id(mod)
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)
    ptrS, _ = E._payload_ptr_and_struct(mod, 'RayPayloadKHR')

    # ---- detectors: ALL of them, before any edit (GOTCHAS 12) -------------
    nee = E.find_nee_trace(mod, fs, fe)
    sb = find_sun_branch(mod, nee, fs, fe)
    sites = find_sun_sites(mod, fs, fe, sb)
    # 89 sec 2: E.find_bounce_counter returns the SAMPLE counter in 5 of the
    # 12 permutations. Both are found every build so the report can say
    # whether this module was one of them; `gate` selects which is used.
    path_ctr, path_hdr = find_path_counter(mod, fs, fe)
    samp_ctr = E.find_bounce_counter(mod, fs, fe, nee["line"])
    counter = path_ctr if gate == 'bounce' else samp_ctr
    cls_word, cls_fetch, cls_line = find_class_word(mod, fs, fe)
    legacy = cross_check_legacy(mod, fs, fe, cls_fetch)
    offctor = E.find_origin_offset(mod, nee)
    splice = sb["sel_line"]
    locals_ = find_local_sites(mod, fs, fe, nee) if all_lights else []
    # k_local defaults to k, i.e. the pre-existing behaviour. 88 sec 5c: the
    # sun subtends 0.5deg so a 12deg cone covers it and full k is honest; an
    # area light subtends tens of degrees, so removing k of the WHOLE term
    # over-darkens in proportion to the source's angular size.
    if k_local is None:
        k_local = k

    # the class word must already be in scope -- if it is not, this build has
    # no business guessing (85's clone path is the fallback, and 12/12 have
    # never needed it).
    if not cfg_dom.dominates(mod, fs, fe, cls_line, splice):
        die(f"{mod.name}: class word {cls_word} (line {cls_line+1}) does not "
            f"dominate the splice (line {splice+1})")

    # Everything the cone reads must ALSO dominate every local-light splice.
    # The local sites sit deeper in the CFG (one is inside the light loop), so
    # this is not implied by the sun result and is checked, not assumed.
    cnt_line, _ = mod.find_def(counter)
    for ls in locals_:
        use = ls["first_mul"]
        need = [("class word", cls_line), ("bounce counter", cnt_line)]
        for tag, ids in (("prehit", offctor["prehit"]),
                         ("normal", offctor["normal"])):
            for c in ids:
                dl, _ = mod.find_def(c)
                if dl is None:
                    die(f"{mod.name}: {tag} component {c} has no definition")
                need.append((f"{tag} {c}", dl))
        for tag, dl in need:
            if not cfg_dom.dominates(mod, fs, fe, dl, use):
                die(f"{mod.name}: {tag} (line {dl+1}) does not dominate the "
                    f"local-light splice at line {use+1}")

    rep = {"k": k, "tmax": tmax, "taps": taps, "theta_deg": theta_deg,
           "ramp": ramp, "tmin": TMIN, "tlow": TLOW, "wmin": WMIN,
           "cull_flags": CULL, "cullmask": MASK, "all_lights": all_lights,
           "k_local": k_local,
           "nee_line": nee["line"] + 1, "backlit": nee["backlit"],
           "sun_cond": sb["cond"], "sun_radiance": sb["rad"],
           "counter_phi": counter, "gate": gate,
           "path_counter": path_ctr, "path_header": path_hdr,
           "sample_counter": samp_ctr,
           "legacy_helper_was_wrong": samp_ctr != path_ctr,
           "class_word": cls_word,
           "class_fetch": cls_fetch, "class_line": cls_line + 1,
           "class_dominates_splice": True, "legacy_class_fetch": legacy,
           "prehit": offctor["prehit"], "normal": offctor["normal"],
           "offset_cbv_slot": offctor["slot"],
           "sites": [{"line": s["line"] + 1, "res": s["res"],
                      "src": s["src"], "rad": s["rad"]} for s in sites],
           "n_sites": len(sites),
           "local_sites": [{"trace_line": l["trace_line"] + 1,
                            "vis": l["vis"], "dir": l["dir"],
                            "muls": [m[0] + 1 for m in l["muls"]]}
                           for l in locals_],
           "n_local_sites": len(locals_)}
    if len(sites) != 3:
        die(f"{mod.name}: {len(sites)} sun sites, expected 3")
    if taps not in (1, 2, 4):
        die(f"{mod.name}: taps must be 1, 2 or 4")

    if k == 0.0:
        rep["emitted"] = "nothing (k=0 identity control)"
        return [], [], rep

    # ---- constants --------------------------------------------------------
    ptrPF = E._ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %float\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %float")
    ptrPU = E._ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %uint\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %uint")
    boolt = E._ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
        lambda n: f"    {n} = OpTypeBool")
    u0 = E._uc(mod, consts, 0)
    u1 = E._uc(mod, consts, 1)
    u2 = E._uc(mod, consts, 2)
    u3 = E._uc(mod, consts, 3)
    ucull = E._uc(mod, consts, CULL)
    umask = E._uc(mod, consts, MASK)
    f0, f1, f10000 = '%float_0', '%float_1', '%float_10000'
    for tok in (f0, f1, f10000):
        if not any(re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant %float ',
                            ln) for ln in mod.lines):
            die(f"{mod.name}: expected constant {tok} is absent")
    ftmin = E._fc(mod, consts, TMIN)
    ftlow = E._fc(mod, consts, TLOW)
    ftmax = E._fc(mod, consts, tmax)
    finvmax = E._fc(mod, consts, 1.0 / tmax)
    fk = E._fc(mod, consts, k)
    fkl = E._fc(mod, consts, k_local) if k_local != k else fk
    feps = E._fc(mod, consts, EPS)
    fwmin = E._fc(mod, consts, WMIN)
    th = math.radians(theta_deg)
    fcos = E._fc(mod, consts, math.cos(th))
    fsin = E._fc(mod, consts, math.sin(th))

    spay = mod.new_id()
    consts.append(f"    {spay} = OpVariable {ptrS} RayPayloadKHR")
    mod.lines[eline] = mod.lines[eline].rstrip() + ' ' + spay

    ind = '               '
    nid = mod.new_id

    def emit_cone(accel, Lop, lit_cond, kconst):
        """One light's cone. `lit_cond` is that light's own "the engine already
        called this pixel lit" bool, so the term can only ever subtract from
        light the engine had already decided to add.

        Returns (instruction list, fac). Identical construction for the sun
        and for every local light -- only the acceleration structure, the NEE
        direction and the lit-condition differ, and the origin does not,
        because the origin is a property of the surface hit, not of the light.
        """
        ins = []

        def em(fmt):
            i = nid()
            ins.append(f"{ind}{i} = {fmt.format(i=i)}")
            return i

        # gate: class-1 skin AND bounce 0 AND the engine's own "pixel is lit"
        g_skin = em(f"OpIEqual {boolt} {cls_word} {u1}")
        g_b0 = em(f"OpIEqual {boolt} {counter} {u0}")
        g_a1 = em(f"OpLogicalAnd {boolt} {g_skin} {g_b0}")
        gate = em(f"OpLogicalAnd {boolt} {g_a1} {lit_cond}")
        g_msk = em(f"OpSelect %uint {gate} {umask} {u0}")

        # origin = prehit, the un-biased traced surface point
        org = em("OpCompositeConstruct %v3float " + ' '.join(offctor["prehit"]))

        # the tap basis
        Lv = em(f"OpExtInst %v3float {glsl} Normalize {Lop}")
        dirs = [Lv]
        weights = [None]
        if taps > 1:
            Nraw = em("OpCompositeConstruct %v3float "
                      + ' '.join(offctor["normal"]))
            # select BEFORE normalize: a false gate must not feed a zero/NaN
            # vector to Normalize, and then a NaN direction to OpTraceRayKHR.
            Nsel = em(f"OpSelect %v3float {gate} {Nraw} {Lv}")
            Nv = em(f"OpExtInst %v3float {glsl} Normalize {Nsel}")
            cosA = em(f"OpDot %float {Lv} {Nv}")
            LcA = em(f"OpVectorTimesScalar %v3float {Lv} {cosA}")
            Pv = em(f"OpFSub %v3float {Nv} {LcA}")
            sinA = em(f"OpExtInst %float {glsl} Length {Pv}")
            sinS = em(f"OpExtInst %float {glsl} NMax {sinA} {feps}")
            rs = em(f"OpFDiv %float {f1} {sinS}")
            Tv = em(f"OpVectorTimesScalar %v3float {Pv} {rs}")   # 0 when L||N
            # B = cross(L, T): unit by construction, exactly 0 when T is -- so
            # no Normalize, so no NaN direction in the degenerate case.
            Bv = em(f"OpExtInst %v3float {glsl} Cross {Lv} {Tv}")
            LcT = em(f"OpVectorTimesScalar %v3float {Lv} {fcos}")
            TsT = em(f"OpVectorTimesScalar %v3float {Tv} {fsin}")
            # tap 1: tilted TOWARD the tangent plane -- the horizon tap
            dirs.append(em(f"OpFSub %v3float {LcT} {TsT}"))
            cosAT = em(f"OpFMul %float {cosA} {fcos}")
            sinAT = em(f"OpFMul %float {sinA} {fsin}")
            w1 = em(f"OpFSub %float {cosAT} {sinAT}")   # cos(alpha + theta)
            weights[0] = cosA
            weights.append(w1)
            if taps == 4:
                BsT = em(f"OpVectorTimesScalar %v3float {Bv} {fsin}")
                dirs.append(em(f"OpFAdd %v3float {LcT} {BsT}"))
                dirs.append(em(f"OpFSub %v3float {LcT} {BsT}"))
                weights.append(cosAT)      # cos(alpha)*cos(theta)
                weights.append(cosAT)
        else:
            weights[0] = f1                # single tap: unweighted

        # pre-arm the payload once; member 3 is re-armed before each tap
        m0c = em(f"OpInBoundsAccessChain {ptrPU} {spay} {u0}")
        m1c = em(f"OpInBoundsAccessChain {ptrPU} {spay} {u1}")
        m2c = em(f"OpInBoundsAccessChain {ptrPF} {spay} {u2}")
        m3c = em(f"OpInBoundsAccessChain {ptrPF} {spay} {u3}")
        ins.append(f"{ind}OpStore {m0c} {u0}")
        ins.append(f"{ind}OpStore {m1c} {u0}")
        ins.append(f"{ind}OpStore {m2c} {f0}")

        num, den = None, None
        for n, (d, w) in enumerate(zip(dirs, weights)):
            # weight floor: kills any tap at or below the horizon
            if w is f1:
                wf = f1
            else:
                ok = em(f"OpFOrdGreaterThanEqual {boolt} {w} {fwmin}")
                wf = em(f"OpSelect %float {ok} {w} {f0}")
            # direction guard: a false gate falls back to the engine's own L
            dg = d if (taps == 1 or n == 0) else em(
                f"OpSelect %v3float {gate} {d} {Lv}")
            ins.append(f"{ind}OpStore {m3c} {f10000}")
            ins.append(f"{ind}OpTraceRayKHR {accel} {ucull} {g_msk} "
                       f"{u1} {u1} {u0} {org} {ftmin} {dg} {ftmax} {spay}")
            t = em(f"OpLoad %float {m3c}")
            lo = em(f"OpFOrdGreaterThan {boolt} {t} {ftlow}")
            hi = em(f"OpFOrdLessThan {boolt} {t} {ftmax}")
            val = em(f"OpLogicalAnd {boolt} {lo} {hi}")
            if ramp:
                rr = em(f"OpFMul %float {t} {finvmax}")
                r1 = em(f"OpFSub %float {f1} {rr}")
                hit = em(f"OpExtInst %float {glsl} NClamp {r1} {f0} {f1}")
            else:
                hit = f1
            occ_i = em(f"OpSelect %float {val} {hit} {f0}")
            wo = em(f"OpFMul %float {wf} {occ_i}")
            num = wo if num is None else em(f"OpFAdd %float {num} {wo}")
            den = wf if den is None else em(f"OpFAdd %float {den} {wf}")

        # combine: cosine-weighted AVERAGE, then the gate-select
        denS = em(f"OpExtInst %float {glsl} NMax {den} {feps}")
        occr = em(f"OpFDiv %float {num} {denS}")
        occc = em(f"OpExtInst %float {glsl} NClamp {occr} {f0} {f1}")
        # the identity guard: gate false => occ is EXACTLY +0.0, whatever the
        # G-buffer normal held, so fac is exactly 1.0 and every site is
        # bit-stable
        occ = em(f"OpSelect %float {gate} {occc} {f0}")
        occk = em(f"OpFMul %float {occ} {kconst}")
        fac = em(f"OpFSub %float {f1} {occk}")
        return ins, fac, dirs

    # ---- the sun ----------------------------------------------------------
    ins, fac, dirs = emit_cone(nee['ops'][0], nee['ops'][8], sb['cond'], fk)
    edits.append((splice - 1, ins))

    # The multiply is emitted immediately BEFORE each site (the site's NClamp
    # source is defined inside the sun block, after the splice), and `fac` is
    # defined at the splice, which dominates the whole selection region.
    for s in sites:
        sline, _ = mod.find_def(s["src"])
        if not (splice < sline < s["line"]):
            die(f"{mod.name}: NClamp source {s['src']} at line {sline+1} is "
                f"not between the splice ({splice+1}) and its site "
                f"({s['line']+1})")
        nf = nid()
        s["new_src"] = nf
        edits.append((s["line"] - 1,
                      [f"{ind}{nf} = OpFMul %float {s['src']} {fac}"]))

    for s in sites:
        old = mod.lines[s["line"]]
        new = re.sub(r'OpFMul %float ' + re.escape(s["src"]) + r' '
                     + re.escape(s["rad"]) + r'\s*$',
                     f"OpFMul %float {s['new_src']} {s['rad']}", old)
        if new == old:
            die(f"{mod.name}: operand rewrite did not take at line {s['line']+1}")
        mod.lines[s["line"]] = new

    # ---- the local lights -------------------------------------------------
    # One FMul on the visibility SCALAR reaches all three channels, so unlike
    # the sun there is one rewrite per light, not three. The cone is inserted
    # immediately before the first channel multiply, in the same basic block
    # as the visibility select, so `fac` trivially dominates its use.
    for ls in locals_:
        lins, lfac, _ = emit_cone(ls["accel"], ls["dir"], ls["eq"], fkl)
        nv = nid()
        ls["new_vis"] = nv
        lins.append(f"{ind}{nv} = OpFMul %float {ls['vis']} {lfac}")
        edits.append((ls["first_mul"] - 1, lins))
        for line, res, rad in ls["muls"]:
            old = mod.lines[line]
            new = re.sub(r'OpFMul %float ' + re.escape(ls["vis"]) + r' '
                         + re.escape(rad) + r'\s*$',
                         f"OpFMul %float {nv} {rad}", old)
            if new == old:
                die(f"{mod.name}: local-light operand rewrite did not take at "
                    f"line {line+1}")
            mod.lines[line] = new

    rep["payload_var"] = spay
    rep["splice_before_line"] = splice + 1
    rep["factor_id"] = fac
    rep["tap_dirs"] = dirs
    rep["emitted"] = len(ins)
    for s, r in zip(sites, rep["sites"]):
        r["new_src"] = s["new_src"]
    for l, r in zip(locals_, rep["local_sites"]):
        r["new_vis"] = l["new_vis"]
    return consts, edits, rep


def process(path, outdir, k, tmax, taps, theta, ramp, all_lights=False,
            k_local=None, gate='bounce'):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['cavity2'] = build(mod, k, tmax, taps, theta, ramp,
                                          all_lights, k_local, gate)
    apply_edits(mod, consts, edits)
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv_out], capture_output=True, text=True)
    if v.returncode != 0:
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--k', type=float, required=True)
    ap.add_argument('--tmax', type=float, required=True)
    ap.add_argument('--taps', type=int, default=4)
    ap.add_argument('--theta', type=float, default=12.0)
    ap.add_argument('--ramp', choices=('on', 'off'), default='on')
    ap.add_argument('--k-local', type=float, default=None,
                    help='occlusion strength at the LOCAL-light sites; '
                         'defaults to --k. 88 sec 5c: an area light subtends '
                         'tens of degrees, so removing k of the whole term '
                         'over-darkens by the source solid angle')
    ap.add_argument('--all-lights', action='store_true',
                    help='also splice the local point/spot/area light NEE '
                         'sites, not just the sun (88 sec 5b)')
    ap.add_argument('--gate', choices=('bounce', 'sample'), default='bounce',
                    help="which loop counter the `== 0` conjunct tests. "
                         "`bounce` is the PATH loop (correct). `sample` "
                         "reproduces the pre-89 behaviour, which was the "
                         "sample loop in 5 of 12 permutations -- kept only "
                         "as the A/B control that isolates the gate fix.")
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    if not 0.0 <= a.k <= 1.0:
        ap.error('--k must be in [0,1]')
    if a.k != 0.0 and not TMIN * 4 <= a.tmax <= 0.05:
        ap.error('--tmax must be between 4*tmin and 50mm')
    if not 0.0 < a.theta < 60.0:
        ap.error('--theta must be in (0,60) degrees')
    if a.k_local is not None:
        if not 0.0 <= a.k_local <= 1.0:
            ap.error('--k-local must be in [0,1]')
        if not a.all_lights:
            ap.error('--k-local is meaningless without --all-lights')
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.tmax, a.taps,
                             a.theta, a.ramp == 'on', a.all_lights,
                             a.k_local, a.gate)))


if __name__ == '__main__':
    main()
