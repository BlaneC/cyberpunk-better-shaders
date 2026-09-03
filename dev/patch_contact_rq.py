#!/usr/bin/env python3
"""contact-rq: TRACED contact occlusion on skin, replacing 88's analytic cone.

handoff/102-CONTACT-RQ.md is the document. Read handoff/88 (the cone it
replaces), 90 sec 1 (find_path_counter), 98 sec 2.3 / 3.4 / 12.4 / 12.6 and
101 (the ray-query splice this clones) before touching this file.

WHAT THIS IS
------------
88 asked a VISIBILITY question -- "is there geometry within a few cm of this
skin pixel" -- and answered it ANALYTICALLY: two rays down a 12 deg cone
around the light direction L, cosine-weighted, distance-ramped. That is a
short-range directional AO on the light term, and 88 sec 2c says so in its own
words ("its selectivity is by grazing angle, not by concavity").

This file answers the same question by MEASURING it: K short ray queries in
the hemisphere about the surface normal N, tmax 10 cm, first hit is enough.
The estimator is a property of the SURFACE, not of any light, so it is traced
ONCE per pixel and reused at every site the cone darkened.

THE ONE VARIABLE
----------------
Everything else is held at the base's own values, by SSA id:

  * the darkening is  fac = 1 - k*o  at the SAME OpFMul the cone wrote, with
    the base's OWN k constant id (0.85) -- never a new constant;
  * the origin is the base cone's own trace origin operand (prehit), lifted
    by EPS along the normal;
  * the normal is the base cone's own OpCompositeConstruct of the harvested
    G-buffer normal;
  * the class gate is the base cone's own slot-5 `>>5` material word;
  * the per-light "the engine already called this pixel lit" bool is the base
    cone's own, per cone.

So `contact-rq` vs the base rung differs in the OCCLUSION ESTIMATOR and in
the path-loop counter (see REPLACE, NOT STACK and THE COUNTER below).

REPLACE, NOT STACK
------------------
The standing base ALREADY carries the cone (it is `...-cone2all-fog`). A
traced term added on top of it would double-count. So the cone is KILLED, two
independent ways, and both are asserted on the shipped bytes:

  1. Each cone's `occ` (the OpSelect(gate, avg, +0.0) that feeds
     `OpFMul occ k`) is DISCONNECTED: the FMul's first operand is rewritten to
     our own gated `o`. Afterwards the cone's `occ` id has exactly ONE mention
     in the whole module -- its own definition -- so nothing it computes can
     reach a radiance write.
  2. Each cone TAP ray is NEUTERED: the cullMask operand of every flags-16
     OpTraceRayKHR is rewritten to `%uint_0`. Mask 0 can intersect nothing, so
     the 6 dead rays per module cost a guaranteed near-free miss instead of a
     real traversal. The cost comparison is then honest.

THE RAY
-------
At a class-1 SKIN pixel on the PRIMARY path segment (90's find_path_counter,
NOT the legacy helper -- see below):

    origin    = <the cone's own trace origin> + N*EPS      (EPS = 0.1 mm)
    direction = K fixed cosine-weighted directions in the hemisphere about N,
                in an orthonormal basis built IN-MODULE from N by Duff et
                al.'s branch-free method (there is no tangent frame in this
                shader), the whole set rotated about N by a PIXEL-SEEDED
                angle (gl_LaunchID, hashed). 98 sec 12.6: no per-frame entropy
                reaches this chain and none is harvested here, so the rotation
                is per-pixel and FRAME-STABLE -- decorrelation without a
                jitter that the photo-mode accumulator would integrate.
    flags     = 517 = 0x001 Opaque | 0x004 TerminateOnFirstHit | 0x200
                SkipAABBs. The question is a BOOLEAN, so the first hit ends it.
                NO face culling: geometry 1 cm from a cheek may present either
                face, and culling one of them would answer a different
                question. (101's 545 = CullFrontFacing is the DECOY here.)
    tmin      = 0.001 m (1 mm) -- the self-hit guard. With no back-face cull
                there is no structural guard, so tmin is the only one.
    tmax      = 0.10 m (10 cm) -- 88's own reach question.
    o         = hits / K

USAGE
    python3 dev/patch_contact_rq.py <mod.spvasm> --outdir DIR --k 1 --rays 4 \
        [--mode dark|hit] [--decoy flags|tmax|counter|stack|basis]

    --k 0 emits NOTHING and writes the module back unchanged: the CONTROL
    rung, byte-identical to the base (build gate 1 proves the round trip is
    neutral). --k 1 is live and means "use the base cone's own k".

THE COUNTER
-----------
The standing base is `-cone2all-fog`, built BEFORE 90's gate fix, so its cone
gates on the SAMPLE counter in 5 of 12 permutations (90 sec 1). This build
gates on the PATH counter in 12 of 12 and reports, per module, whether the
base was one of the bad five. That is a second difference from the base rung
on those five and the document says so rather than hiding it.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
import patch_earglow as E
import cfg_dom
# 90 sec 1's FIXED path-loop counter, imported, never re-derived here.
# E.find_bounce_counter is the broken helper; it is called only so the report
# can record `legacy_helper_was_wrong`, and by --decoy counter.
from patch_cavity2 import find_path_counter
# 98's header inserter. patch_rayq.py is NOT edited by this file.
from patch_rayq import _add_header

# --- SPIR-V RayFlags (SPV_KHR_ray_query shares the ray-tracing enum) --------
#   0x001 OpaqueKHR                  0x010 CullBackFacingTrianglesKHR   (16)
#   0x002 NoOpaqueKHR                0x020 CullFrontFacingTrianglesKHR  (32)
#   0x004 TerminateOnFirstHitKHR     0x100 SkipTrianglesKHR
#   0x008 SkipClosestHitShaderKHR    0x200 SkipAABBsKHR
RF_OPAQUE     = 0x001
RF_TERMINATE  = 0x004
RF_CULL_FRONT = 0x020
RF_SKIP_AABBS = 0x200
FLAGS = RF_OPAQUE | RF_TERMINATE | RF_SKIP_AABBS              # 517
FLAGS_NAMES = 'OpaqueKHR|TerminateOnFirstHitKHR|SkipAABBsKHR'
# 101's word. Culling the front faces answers "how thick is the flesh", not
# "is anything near me", and the difference is invisible in a diff.
FLAGS_DECOY = RF_OPAQUE | RF_CULL_FRONT | RF_SKIP_AABBS       # 545

COMMITTED = 1               # RayQueryCommittedIntersectionKHR
GATE_MASK = 39              # the module's own NEE cullMask when lit (88/98)
CONE_FLAGS = 16             # the cone taps' literal ray-flag word
TMIN = 0.001                # 1 mm, the self-hit guard
TMAX = 0.10                 # 10 cm, 88's reach question
TMAX_DECOY = 0.018          # 101's T_SEG: a thickness probe, not a reach probe
EPS_N = 1e-4                # 0.1 mm origin lift along N
NEPS = 1e-6                 # degenerate-normal floor
HIT_SCALE = 3.2             # -hit grey ramp full-scale (66's probe magnitude)
PHI_INV = 0.6180339887498949

# 32-bit hash constants: Knuth's golden ratio, glibc's LCG multiplier, and
# Wang's finaliser. Pixel in, angle out; nothing per-frame is read.
H_A = 1103515245
H_B = 2654435761
H_C = 2246822519


def taps(n):
    """The fixed cosine-weighted direction set, in the local frame.

    u_j = (j + 0.5)/n stratifies the cosine-weighted hemisphere exactly:
    cos(theta) = sqrt(1 - u), sin(theta) = sqrt(u). The azimuth is the golden
    increment, which is what keeps a 4-tap set from lining up with a crease.
    Every component is a BUILD constant; the runtime cost is 3
    OpVectorTimesScalar + 2 OpFAdd per tap.
    """
    out = []
    for j in range(n):
        u = (j + 0.5) / n
        r = math.sqrt(u)
        cz = math.sqrt(1.0 - u)
        ph = 2.0 * math.pi * ((j * PHI_INV) % 1.0)
        out.append((r * math.cos(ph), r * math.sin(ph), cz))
    return out


def _uc(mod, consts, v):
    nid, decl = mod.uconst(v)
    if decl:
        consts.append(decl)
    return nid


def _fc(mod, consts, v):
    nid, decl = mod.const(v)
    if decl:
        consts.append(decl)
    return nid


def _ensure_line(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def _uses(mod, idtok):
    """Total mentions of an id, definition line included."""
    n = 0
    for ln in mod.lines:
        n += len(re.findall(re.escape(idtok) + r'(?![0-9A-Za-z_])', ln))
    return n


def find_launch_id(mod):
    """The gl_LaunchID input variable, by its BuiltIn decoration."""
    for ln in mod.lines:
        m = re.match(r'\s*OpDecorate (%\w+) BuiltIn LaunchIdKHR\s*$', ln)
        if m:
            v = m.group(1)
            l, cd = mod.find_def(v)
            if cd is None or 'OpVariable' not in cd or ' Input' not in cd:
                die(f"{mod.name}: {v} is decorated LaunchIdKHR but is not an "
                    f"Input OpVariable")
            return v
    die(f"{mod.name}: no BuiltIn LaunchIdKHR -- there is no pixel seed here")


def find_cones(mod, fs, fe):
    """88's cavity cones, re-derived from the BASE bytes.

    A cone is recognised by the two instructions that APPLY it, which is the
    only part of it this file touches:

        occ  = OpSelect %float <gate> <avg> %float_0     (the identity guard)
        occk = OpFMul   %float occ <k>                   (<k> an OpConstant)
        fac  = OpFSub   %float %float_1 occk

    and by its gate being exactly 88's:

        gate = OpLogicalAnd(OpLogicalAnd(IEqual(<cls>,1), IEqual(<ctr>,0)),
                            <lit>)
        cls  = OpShiftRightLogical %uint <material word> %uint_5   (88 sec 4)

    Nothing here re-uses patch_cavity2's detectors: if 88's emitted shape ever
    moves, this dies instead of patching the wrong instruction.
    """
    cones = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$',
                     mod.lines[i])
        if not m:
            continue
        occk, occ, kc = m.groups()
        kl, kd = mod.find_def(kc)
        if kd is None or not re.match(r'OpConstant %float ', kd):
            continue
        ol, od = mod.find_def(occ)
        g = re.match(r'OpSelect %float (%\w+) (%\w+) %float_0\s*$', od or '')
        if not g:
            continue
        gate, avg = g.groups()
        fac = None
        for j in range(i + 1, min(i + 3, fe)):
            f = re.match(r'\s*(%\w+) = OpFSub %float %float_1 '
                         + re.escape(occk) + r'\s*$', mod.lines[j])
            if f:
                fac = f.group(1)
                break
        if fac is None:
            continue
        _, gd = mod.find_def(gate)
        ga = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$', gd or '')
        if not ga:
            die(f"{mod.name}: cone gate {gate} is not an OpLogicalAnd")
        g1, lit = ga.groups()
        _, g1d = mod.find_def(g1)
        ga1 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$', g1d or '')
        if not ga1:
            die(f"{mod.name}: cone gate half {g1} is not an OpLogicalAnd")
        gsk, gb0 = ga1.groups()
        _, gskd = mod.find_def(gsk)
        s = re.match(r'OpIEqual %bool (%\w+) %uint_1\s*$', gskd or '')
        if not s:
            die(f"{mod.name}: cone class test {gsk} is not IEqual(x, 1)")
        cls = s.group(1)
        _, clsd = mod.find_def(cls)
        if not re.match(r'OpShiftRightLogical %uint %\w+ %uint_5\s*$',
                        clsd or ''):
            die(f"{mod.name}: class word {cls} is not a slot-5 `>>5` word "
                f"(88 sec 4) -- got {clsd}")
        _, gb0d = mod.find_def(gb0)
        c = re.match(r'OpIEqual %bool (%\w+) %uint_0\s*$', gb0d or '')
        if not c:
            die(f"{mod.name}: cone counter test {gb0} is not IEqual(x, 0)")
        _, litd = mod.find_def(lit)
        local = bool(re.match(r'OpFOrdEqual %bool %\w+ %float_10000\s*$',
                              litd or ''))
        cones.append(dict(occk_line=i, occk=occk, occ=occ, k=kc, fac=fac,
                          gate=gate, lit=lit, cls=cls, ctr=c.group(1),
                          local=local, avg=avg))
    if len(cones) != 3:
        die(f"{mod.name}: found {len(cones)} cavity cones, expected 3 "
            f"(1 sun + 2 local; the base must be a -cone2all* rung)")
    if len({c['k'] for c in cones}) != 1:
        die(f"{mod.name}: the three cones do not share one k constant: "
            f"{[c['k'] for c in cones]}")
    if len({c['cls'] for c in cones}) != 1:
        die(f"{mod.name}: the three cones do not share one class word")
    suns = [c for c in cones if not c['local']]
    if len(suns) != 1 or sum(c['local'] for c in cones) != 2:
        die(f"{mod.name}: expected exactly 1 sun cone and 2 local cones, got "
            f"{len(suns)} / {sum(c['local'] for c in cones)}")
    sun = suns[0]
    if sun['occk_line'] != min(c['occk_line'] for c in cones):
        die(f"{mod.name}: the sun cone is not the earliest -- 88's emission "
            f"order has moved")
    return sun, [c for c in cones if c['local']]


def find_cone_taps(mod, fs, fe):
    """Every flags-16 OpTraceRayKHR -- 88's taps and nothing else.

    The engine's own next-event traces carry flags 12 or a runtime word; 88's
    negative control measured ZERO flags-16 traces in the unpatched game
    shader, so this word selects the cone's rays and only the cone's rays.
    """
    pat = (r'\s*OpTraceRayKHR (%\w+) %uint_' + str(CONE_FLAGS)
           + r' (%\w+) (%\w+) (%\w+) (%\w+) (%\w+) (%\w+) (%\w+) (%\w+) '
             r'(%\w+)\s*$')
    out = []
    for i in range(fs, fe):
        m = re.match(pat, mod.lines[i])
        if m:
            out.append(dict(line=i, accel=m.group(1), mask=m.group(2),
                            org=m.group(6), dirid=m.group(8)))
    return out


def find_sun_geometry(mod, sun, tps):
    """The origin, the raw normal and the normalised light direction the SUN
    cone already built -- taken by SSA id, never rebuilt."""
    mine = [t for t in tps if t['mask'] == _mask_of(mod, sun['gate'])]
    if len(mine) < 1:
        die(f"{mod.name}: no flags-16 tap carries the sun cone's cull mask")
    if len({t['org'] for t in mine}) != 1 or len({t['accel'] for t in mine}) != 1:
        die(f"{mod.name}: the sun cone's taps do not share one origin/AS")
    org, accel = mine[0]['org'], mine[0]['accel']
    _, od = mod.find_def(org)
    if not re.match(r'OpCompositeConstruct %v3float ', od or ''):
        die(f"{mod.name}: the sun cone origin {org} is not a v3float "
            f"construct -- got {od}")
    # 88 emits several v3float selects on this gate: one is the
    # select-before-normalize that guards the harvested normal, the others are
    # the per-tap direction guards. Only the normal's feeds a Normalize, and
    # that is the discriminator -- asserted unique, never assumed.
    nsel = None
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpSelect %v3float '
                     + re.escape(sun['gate']) + r' (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        if not any(re.match(r'\s*%\w+ = OpExtInst %v3float %\w+ Normalize '
                            + re.escape(m.group(1)) + r'\s*$', l)
                   for l in mod.lines):
            continue
        if nsel is not None:
            die(f"{mod.name}: more than one normalized v3float select on the "
                f"sun cone gate -- the normal anchor is ambiguous")
        nsel = m
    if nsel is None:
        die(f"{mod.name}: no OpSelect %v3float on the sun cone gate -- 88's "
            f"select-before-normalize is gone, so there is no harvested normal")
    nraw, lv = nsel.group(2), nsel.group(3)
    _, nd = mod.find_def(nraw)
    if not re.match(r'OpCompositeConstruct %v3float ', nd or ''):
        die(f"{mod.name}: the harvested normal {nraw} is not a v3float "
            f"construct -- got {nd}")
    _, ld = mod.find_def(lv)
    if not re.match(r'OpExtInst %v3float %\w+ Normalize ', ld or ''):
        die(f"{mod.name}: the fallback direction {lv} is not a Normalize")
    return dict(org=org, accel=accel, nraw=nraw, lv=lv, taps=mine)


def _mask_of(mod, gate):
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+) = OpSelect %uint ' + re.escape(gate)
                     + r' %uint_' + str(GATE_MASK) + r' %uint_0\s*$', ln)
        if m:
            return m.group(1)
    return None


def build(mod, k, rays, mode='dark', decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, ALL of them, before any edit (GOTCHAS 12) -------------
    sun, locs = find_cones(mod, fs, fe)
    tps = find_cone_taps(mod, fs, fe)
    if len(tps) != 6:
        die(f"{mod.name}: {len(tps)} flags-16 cone taps, expected 6 "
            f"(2 per cone x 3 cones)")
    geo = find_sun_geometry(mod, sun, tps)
    lid = find_launch_id(mod)
    counter, phdr = find_path_counter(mod, fs, fe)
    legacy = None
    try:
        legacy = E.find_bounce_counter(mod, fs, fe, geo['taps'][0]['line'])
    except SystemExit:
        legacy = None
    if decoy == 'counter':
        if legacy is None:
            die(f"{mod.name}: --decoy counter needs the legacy helper")
        counter = legacy
    writes = find_image_writes(mod) if mode == 'hit' else []

    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$',
                        l) for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR -- SkipAABBsKHR "
            f"(0x200) would be illegal")

    flags = FLAGS_DECOY if decoy == 'flags' else FLAGS
    tmax = TMAX_DECOY if decoy == 'tmax' else TMAX
    rep = {"mode": mode, "k": k, "rays": rays, "ray_flags": flags,
           "ray_flags_names": FLAGS_NAMES, "tmin": TMIN, "tmax": tmax,
           "eps_n": EPS_N, "decoy": decoy, "gate_mask": GATE_MASK,
           "commit": "first (TerminateOnFirstHit)",
           "cone_k": sun['k'], "class_word": sun['cls'],
           "base_cone_counter": sun['ctr'], "path_counter": counter,
           "path_header": phdr, "legacy_counter": legacy,
           "legacy_helper_was_wrong": (legacy is not None and legacy != counter),
           "base_cone_gate_was_sample": sun['ctr'] != counter,
           "sun_cone_line": sun['occk_line'] + 1,
           "local_cone_lines": [c['occk_line'] + 1 for c in locs],
           "origin": geo['org'], "normal": geo['nraw'], "accel": geo['accel'],
           "launch_id": lid,
           "taps": [t['line'] + 1 for t in tps],
           "tap_dirs": taps(rays)}

    if k == 0.0:
        rep["emitted"] = 0
        rep["why"] = "k=0: identity control, no instructions"
        return [], [], rep

    # everything the estimator reads must dominate every site it feeds
    cnt_line, _ = mod.find_def(counter)
    cls_line, _ = mod.find_def(sun['cls'])
    for tag, dl in (("path counter", cnt_line), ("class word", cls_line)):
        if not cfg_dom.dominates(mod, fs, fe, dl, sun['occk_line']):
            die(f"{mod.name}: {tag} (line {dl+1}) does not dominate the "
                f"estimator at line {sun['occk_line']+1}")
    for c in locs:
        if not cfg_dom.dominates(mod, fs, fe, sun['occk_line'], c['occk_line']):
            die(f"{mod.name}: the estimator (line {sun['occk_line']+1}) does "
                f"not dominate the local cone at line {c['occk_line']+1}")

    # ---- types / constants ------------------------------------------------
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    ptrIU = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Input %uint\s*$',
        lambda n: f"    {n} = OpTypePointer Input %uint")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")

    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u8 = _uc(mod, consts, 8)
    umask = _uc(mod, consts, GATE_MASK)
    uflags = _uc(mod, consts, flags)
    uha, uhb, uhc = (_uc(mod, consts, H_A), _uc(mod, consts, H_B),
                     _uc(mod, consts, H_C))
    f0, f1 = '%float_0', '%float_1'
    fn1 = _fc(mod, consts, -1.0)
    feps = _fc(mod, consts, EPS_N)
    fneps = _fc(mod, consts, NEPS)
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, tmax)
    finvk = _fc(mod, consts, 1.0 / rays)
    f2pi24 = _fc(mod, consts, 2.0 * math.pi / 16777216.0)
    dirc = [[_fc(mod, consts, v) for v in d] for d in taps(rays)]
    if mode == 'hit':
        fscale = _fc(mod, consts, HIT_SCALE)

    # ---- entry block: the query object (+ the -hit latch), ONE edit --------
    eb_lab, eb_term = E.entry_block_span(mod, fs, fe)
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rq = mod.new_id()
    ind0 = '               '
    head = [f"{ind0}{rq} = OpVariable {ptr_rq} Function"]
    hv = None
    if mode == 'hit':
        hv = mod.new_id()
        head.append(f"{ind0}{hv} = OpVariable {ptrFF} Function")
        head.append(f"{ind0}OpStore {hv} {fn1}")
    edits.append((at, head))

    # ---- the estimator: one straight-line run, no branches ----------------
    ind = re.match(r'(\s*)', mod.lines[sun['occk_line']]).group(1)
    ins = []
    nid = mod.new_id

    def em(fmt):
        i = nid()
        ins.append(f"{ind}{i} = {fmt}")
        return i

    # gate: class-1 skin AND primary path segment. NOT per-light: contact
    # occlusion is a property of the surface, so it is measured once and the
    # per-light lit-condition is applied at each site instead.
    g_sk = em(f"OpIEqual {boolt} {sun['cls']} {u1}")
    g_p0 = em(f"OpIEqual {boolt} {counter} {u0}")
    g_cs = em(f"OpLogicalAnd {boolt} {g_sk} {g_p0}")
    # a degenerate G-buffer normal must never reach Normalize -> NaN -> an
    # undefined ray direction. 88's select-before-normalize, with a length
    # test in front of it because our gate is wider than 88's.
    nlen = em(f"OpExtInst %float {glsl} Length {geo['nraw']}")
    nok = em(f"OpFOrdGreaterThan {boolt} {nlen} {fneps}")
    gate = em(f"OpLogicalAnd {boolt} {g_cs} {nok}")
    msk = em(f"OpSelect %uint {gate} {umask} {u0}")
    nsel = em(f"OpSelect %v3float {gate} {geo['nraw']} {geo['lv']}")
    Nu = em(f"OpExtInst %v3float {glsl} Normalize {nsel}")

    # origin = the cone's own origin, lifted EPS along N
    ne = em(f"OpVectorTimesScalar %v3float {Nu} {feps}")
    org = em(f"OpFAdd %v3float {geo['org']} {ne}")

    # pixel-seeded rotation angle. gl_LaunchID only: frame-stable by
    # construction, and 98 sec 12.6's audit stays true (nothing per-frame).
    axc = em(f"OpAccessChain {ptrIU} {lid} {u0}")
    px = em(f"OpLoad %uint {axc}")
    ayc = em(f"OpAccessChain {ptrIU} {lid} {u1}")
    py = em(f"OpLoad %uint {ayc}")
    h1 = em(f"OpIMul %uint {px} {uha}")
    h2 = em(f"OpIMul %uint {py} {uhb}")
    h3 = em(f"OpBitwiseXor %uint {h1} {h2}")
    h4 = em(f"OpIMul %uint {h3} {uhc}")
    h5 = em(f"OpShiftRightLogical %uint {h4} {u8}")
    hf = em(f"OpConvertUToF %float {h5}")
    psi = em(f"OpFMul %float {hf} {f2pi24}")
    cps = em(f"OpExtInst %float {glsl} Cos {psi}")
    sps = em(f"OpExtInst %float {glsl} Sin {psi}")

    # orthonormal basis about N -- Duff et al. 2017, branch-free. sign+n.z is
    # never near zero by construction (it lands in [1,2] or [-2,-1]), which is
    # the whole point of the method over a cross-with-an-axis frame.
    nx = em(f"OpCompositeExtract %float {Nu} 0")
    ny = em(f"OpCompositeExtract %float {Nu} 1")
    nz = em(f"OpCompositeExtract %float {Nu} 2")
    if decoy == 'basis':
        # a fixed WORLD basis: still orthonormal, still unit directions, but
        # the hemisphere is no longer about N. Invisible in a diff.
        Tv = em(f"OpCompositeConstruct %v3float {f1} {f0} {f0}")
        Bv = em(f"OpCompositeConstruct %v3float {f0} {f1} {f0}")
    else:
        zp = em(f"OpFOrdGreaterThanEqual {boolt} {nz} {f0}")
        sgn = em(f"OpSelect %float {zp} {f1} {fn1}")
        den = em(f"OpFAdd %float {sgn} {nz}")
        a = em(f"OpFDiv %float {fn1} {den}")
        nxy = em(f"OpFMul %float {nx} {ny}")
        b = em(f"OpFMul %float {nxy} {a}")
        nxx = em(f"OpFMul %float {nx} {nx}")
        nxxa = em(f"OpFMul %float {nxx} {a}")
        t0a = em(f"OpFMul %float {sgn} {nxxa}")
        t0 = em(f"OpFAdd %float {f1} {t0a}")
        t1 = em(f"OpFMul %float {sgn} {b}")
        t2a = em(f"OpFMul %float {sgn} {nx}")
        t2 = em(f"OpFNegate %float {t2a}")
        Tv = em(f"OpCompositeConstruct %v3float {t0} {t1} {t2}")
        nyy = em(f"OpFMul %float {ny} {ny}")
        nyya = em(f"OpFMul %float {nyy} {a}")
        b1 = em(f"OpFAdd %float {sgn} {nyya}")
        b2 = em(f"OpFNegate %float {ny}")
        Bv = em(f"OpCompositeConstruct %v3float {b} {b1} {b2}")

    # rotate the BASIS once, not each direction: 4 ops instead of 2 per tap
    tc = em(f"OpVectorTimesScalar %v3float {Tv} {cps}")
    bs = em(f"OpVectorTimesScalar %v3float {Bv} {sps}")
    Tr = em(f"OpFAdd %v3float {tc} {bs}")
    ts = em(f"OpVectorTimesScalar %v3float {Tv} {sps}")
    bc = em(f"OpVectorTimesScalar %v3float {Bv} {cps}")
    Br = em(f"OpFSub %v3float {bc} {ts}")

    acc = None
    for j in range(rays):
        cx, cy, cz = dirc[j]
        d1 = em(f"OpVectorTimesScalar %v3float {Tr} {cx}")
        d2 = em(f"OpVectorTimesScalar %v3float {Br} {cy}")
        d3 = em(f"OpVectorTimesScalar %v3float {Nu} {cz}")
        d4 = em(f"OpFAdd %v3float {d1} {d2}")
        dj = em(f"OpFAdd %v3float {d4} {d3}")
        ins.append(f"{ind}OpRayQueryInitializeKHR {rq} {geo['accel']} "
                   f"{uflags} {msk} {org} {ftmin} {dj} {ftmax}")
        em(f"OpRayQueryProceedKHR {boolt} {rq}")
        ty = em(f"OpRayQueryGetIntersectionTypeKHR %uint {rq} {u1}")
        hj = em(f"OpINotEqual {boolt} {ty} {u0}")
        cj = em(f"OpSelect %float {hj} {f1} {f0}")
        acc = cj if acc is None else em(f"OpFAdd %float {acc} {cj}")
    occ = em(f"OpFMul %float {acc} {finvk}")

    if mode == 'hit':
        inv = em(f"OpFSub %float {f1} {occ}")
        gr = em(f"OpFMul %float {inv} {fscale}")
        pv = em(f"OpSelect %float {gate} {gr} {fn1}")
        ins.append(f"{ind}OpStore {hv} {pv}")

    # Per-cone application: the SAME OpFMul, the SAME k id, our o. The sun's
    # two instructions close the estimator run; each local light's are emitted
    # at ITS OWN site, because that light's lit-condition is defined there and
    # nowhere earlier (one of the two sits inside the light loop, 88 sec 5b).
    gi = em(f"OpLogicalAnd {boolt} {gate} {sun['lit']}")
    sun['ours'] = em(f"OpSelect %float {gi} {occ} {f0}")
    edits.append((sun['occk_line'] - 1, ins))
    for c in locs:
        lind = re.match(r'(\s*)', mod.lines[c['occk_line']]).group(1)
        g = nid(); o = nid()
        c['ours'] = o
        edits.append((c['occk_line'] - 1, [
            f"{lind}{g} = OpLogicalAnd {boolt} {gate} {c['lit']}",
            f"{lind}{o} = OpSelect %float {g} {occ} {f0}"]))
    rep["splice_instructions"] = len(ins)
    rep["rq_var"] = rq

    # ---- REPLACE: disconnect every cone's own occ -------------------------
    if decoy != 'stack':
        for c in [sun] + locs:
            old = mod.lines[c['occk_line']]
            new = re.sub(r'OpFMul %float ' + re.escape(c['occ']) + r' '
                         + re.escape(c['k']) + r'\s*$',
                         f"OpFMul %float {c['ours']} {c['k']}", old)
            if new == old:
                die(f"{mod.name}: occ rewrite did not take at line "
                    f"{c['occk_line']+1}")
            mod.lines[c['occk_line']] = new
        # ---- REPLACE: neuter every cone tap ray (mask 0 == free miss) -----
        for t in tps:
            old = mod.lines[t['line']]
            new = re.sub(r'(OpTraceRayKHR %\w+ %uint_' + str(CONE_FLAGS)
                         + r' )' + re.escape(t['mask']),
                         r'\g<1>' + u0, old)
            if new == old:
                die(f"{mod.name}: cone tap mask rewrite did not take at line "
                    f"{t['line']+1}")
            mod.lines[t['line']] = new
    rep["cones_replaced"] = 0 if decoy == 'stack' else 3
    rep["taps_neutered"] = 0 if decoy == 'stack' else len(tps)

    # ---- -hit: paint o as a flat grey ramp over the radiance writes -------
    added, skipped = [], []
    if mode == 'hit':
        for w in writes:
            if w['comps'] is None:
                die(f"{mod.name}: write at line {w['line']+1} has a "
                    f"non-construct texel -- refusing")
            c = w['comps']
            if all(_gi_zeroish(mod, x) for x in c[:3]):
                skipped.append({"line": w['line'] + 1, "why": "constant-zero"})
                continue
            if c[0] == c[1] == c[2]:
                skipped.append({"line": w['line'] + 1,
                                "why": "scalar-broadcast"})
                continue
            wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
            wi, newc = [], []
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {hv}")
            u = nid(); wi.append(f"{wind}{u} = OpFOrdGreaterThanEqual {boolt} "
                                 f"{l} {f0}")
            for ch in range(3):
                s = nid()
                wi.append(f"{wind}{s} = OpSelect %float {u} {l} {c[ch]}")
                newc.append(s)
            nt = nid()
            wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                      f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
            edits.append((w['line'] - 1, wi))
            mod.lines[w['line']] = re.sub(
                r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
                mod.lines[w['line']])
            added.append({"line": w['line'] + 1})
        if not added and mod.ident.split('.')[0] not in (
                '40c6faab52a13874', 'ab7f1822eeb0331b'):
            die(f"{mod.name}: -hit has no radiance write to paint")
    rep["writes_painted"], rep["writes_skipped"] = added, skipped
    return consts, edits, rep


def process(path, outdir, k, rays, mode='dark', decoy=None, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['contact_rq'] = build(mod, k, rays, mode, decoy)
    if k != 0.0:
        apply_edits(mod, consts, edits)
        _add_header(mod)
    # k == 0: nothing was emitted and nothing was rewritten, so the module is
    # written back exactly as disassembled -> byte-identical to the base.

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', spv_out],
                       capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--k', type=float, required=True,
                    help='0 = the byte-identity CONTROL (emit nothing); '
                         '1 = live, using the base cone\'s own k constant')
    ap.add_argument('--rays', type=int, default=4,
                    help='K, the number of contact queries per skin pixel')
    ap.add_argument('--mode', default='dark', choices=('dark', 'hit'),
                    help="dark = the darkening; hit = the flat grey occlusion "
                         "map, readable independently of the darkening")
    ap.add_argument('--decoy',
                    choices=('flags', 'tmax', 'counter', 'stack', 'basis'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_contact_rq.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if a.k not in (0.0, 1.0):
        ap.error('--k is a switch: 0 = control, 1 = live (the cone\'s own k)')
    if a.rays < 1 or a.rays > 32:
        ap.error('--rays out of range')
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.rays, a.mode, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
