#!/usr/bin/env python3
"""earglow-rq: thin-skin sun transmission (ear/nose glow) on a RAY QUERY.

handoff/101-EARGLOW-RQ.md is the document. Read handoff/70 sec W1 + W3, 71,
and handoff/98 sec 2 / 15 before touching this file.

WHAT THIS IS
------------
70's W1 ("aim the ray the other way") and W3 ("soft transfer + wrap
envelope), rebuilt on the ray-query mechanism 98 proved end to end. The
feature is unchanged from 71's v5 in intent -- measure the SUN-PATH FLESH
THICKNESS at a backlit skin pixel and add a per-channel Beer-Lambert
transmission term -- and changed in exactly one mechanism: the measurement is
an INLINE RAY QUERY instead of an injected OpTraceRayKHR + payload round trip.

Why the query is the better instrument here, in three lines:

  * tmin is a REAL PARAMETER. v5 could only trace from 0 and reject a card's
    own backface AFTERWARDS with a `t > 1.5mm` compare, which still paid for
    the traversal and still depended on the payload coming back. The query
    takes the 1.5 mm floor as `tmin`, so a strand/collar backface at 0.2-0.5mm
    is never even a candidate (70 W1's rejection, moved from a compare into
    traversal).
  * `t` comes back as a VALUE, not through a payload ABI:
    OpRayQueryGetIntersectionTKHR on the committed intersection. No pre-arm,
    no 10000.0 miss sentinel, no CHS handshake, no assumption about what the
    engine's own closest-hit shader writes into a struct we do not own.
  * ONE query, ONE Proceed, ZERO added control flow (98 sec 2.3's argument,
    unchanged: RayFlagsOpaque removes the alpha-test candidate and SkipAABBs
    removes the procedural one, so no candidate can ever require shader
    intervention and the first Proceed runs traversal to completion).

THE RAY
-------
At the module's own sun-NEE trace, for a pixel that is class-1 SKIN and
BACKLIT and on the PRIMARY path segment:

    origin    = the sun-NEE trace's own origin operand VERBATIM (ops[6]:
                P + the engine's own self-hit offset). 98 sec 15 proved this
                raygen's hit positions and its TLAS are in the SAME
                camera-relative space, so the query needs NO offset applied
                to the origin -- adding 94 sec 3.3's world offset here would
                be a bug, not a correction.
    direction = the sun-NEE trace's own direction operand VERBATIM (ops[8] =
                S, the module's cone-jittered unit sun direction)
    flags     = 545 = 0x001 Opaque | 0x020 CullFrontFacingTriangles
                    | 0x200 SkipAABBs
                NO TerminateOnFirstHit (0x004): the NEAREST backface is the
                far wall of the flesh, so traversal must run to completion
                and the COMMITTED intersection is the closest one.
    tmin      = 0.0015 m  (71's TH_FLOOR, unchanged -- the min-t floor)
    tmax      = 0.018  m  (71's T_SEG, unchanged)
    t         = OpRayQueryGetIntersectionTKHR(rq, Committed)
              = the sun-path flesh thickness

The entering front face is culled, so inside a closed backlit flesh manifold
the first visible surface is the sun-side wall seen FROM WITHIN -- a BACKFACE
at exactly the thickness. A MISS inside 18 mm means "not thin" and is no
glow. Every leak class 70 sec W1 lists dies by geometry, so v3's consistency
gate and v4's distance-aware gate are not here, and neither is v5's albedo
gate or its second (sun-visibility) ray: the gate list this build is held to
is ONE query and ONE Proceed, and a visibility ray would be a second one.
That omission is a KNOWN, RECORDED BIAS -- hair-shadowed backlit skin will
glow here where v5 correctly killed it (69's probe magenta) -- not an
oversight. See handoff/101 sec 4.

THE FALSIFIER (pre-registered, 70 sec W1)
-----------------------------------------
If the engine strips interior backfaces from its BLASes, or builds instances
with facing-cull disabled, EVERYTHING STAYS DARK. 98's +-0.1% primary-surface
query proved FRONT-face hits only; backface availability is UNPROVEN and is
this rung's main risk. `--mode hit` builds the diagnostic that reads the
miss/hit map independently of the transfer: flat BLUE where the sunward query
commits anything inside [1.5, 18] mm, flat RED where the gate passed and it
committed nothing. Blue somewhere => backfaces exist. Red everywhere on
backlit skin => the falsifier fired, stop.

THE TRANSFER (W3, 71 sec 2 -- constants unchanged, k NOT tuned)
---------------------------------------------------------------
    ld       = (3.67, 1.37, 0.68) mm    Jensen skin1, as 52/53/71
    transfer = 0.5 * (exp(-t/ld) + exp(-t/(WIDE*ld)))   per channel
    wrap     = smoothstep(0, WRAP, -N.S)  on the module's own primary normal
    term     = k * wrap * transfer(t) * sunRadiance,  clamped at 100
    k        = 0.22 on every rung. "Do not tune k" (70/71) stands: the ladder
               is DESIGN (WIDE/WRAP), not strength.

The term is ADDED to the radiance write, never multiplied. 98 sec 12.4 is the
reason it has to be: that document's paint is an OpFMul on this raygen's
radiance stores, and a multiply can only rescale light that is already there
-- on the SHADOWED side of a backlit head there is nearly none, so a multiply
is invisible exactly where this feature lives. An add injects radiance, and
the same add at the same site is the one 69 read on screen ("subtle nose
light up is cool"), which is the strongest evidence available that this site
reaches the frame at all.

USAGE
    python3 dev/patch_earglow_rq.py <mod.spvasm> --outdir DIR --k 0.22 \
        [--wide 4.0 --wrap 0.35] [--mode glow|hit] [--decoy flags|tmax|counter]

    --k 0 with --mode glow emits NOTHING and writes the module back unchanged.
    That is the CONTROL rung: because the dis -> as round trip is byte-neutral
    on all 10 paintable permutations (build_earglow_rq.sh gate 1), the output
    is byte-identical to the base, so `earglow-rq-ctl` is the standing
    selection served through this rung's own name.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
# The earglow ANCHORS -- reused, never re-derived: the sun-NEE trace and its
# backlit condition, the sun radiance triple, the class-1 material fetch, the
# engine's own self-hit offset walk (which is where N comes from), and the
# physics constants. patch_earglow.py itself is NOT edited by this file.
import patch_earglow as E
from patch_earglow import (find_nee_trace, find_sun_radiance, find_class_fetch,
                           find_origin_offset, clone_chain, entry_block_span,
                           LD_M, T_SEG, TH_FLOOR, CLAMP)
# 90 sec 1's FIXED path-loop counter. E.find_bounce_counter is the broken
# helper 79's ear glow used (wrong in 5 of 12 permutations); it is called here
# only so the report can record `legacy_helper_was_wrong` per module, and by
# --decoy counter, which exists to prove the verifier catches it.
from patch_cavity2 import find_path_counter
# 98's header inserter: OpCapability / OpExtension live above OpMemoryModel,
# which apply_edits cannot reach. patch_rayq.py is NOT edited by this file.
from patch_rayq import _add_header

# --- SPIR-V RayFlags, each bit checked against the SPIR-V registry ----------
# (SPV_KHR_ray_tracing / SPV_KHR_ray_query share one RayFlags enum)
#   0x001 OpaqueKHR                    0x010 CullBackFacingTrianglesKHR   (16)
#   0x002 NoOpaqueKHR                  0x020 CullFrontFacingTrianglesKHR  (32)
#   0x004 TerminateOnFirstHitKHR       0x040 CullOpaqueKHR
#   0x008 SkipClosestHitShaderKHR      0x080 CullNoOpaqueKHR
#   0x100 SkipTrianglesKHR             0x200 SkipAABBsKHR
RF_OPAQUE      = 0x001
RF_TERMINATE   = 0x004
RF_CULL_BACK   = 0x010          # 16 -- what v4's reversed segment wanted
RF_CULL_FRONT  = 0x020          # 32 -- W1: keep only the far wall's BACKFACE
RF_SKIP_AABBS  = 0x200
FLAGS = RF_OPAQUE | RF_CULL_FRONT | RF_SKIP_AABBS          # 545
FLAGS_NAMES = 'OpaqueKHR|CullFrontFacingTrianglesKHR|SkipAABBsKHR'
# The decoy: one enum apart, the exact mistake that would measure the ray's
# ENTRY face instead of its exit and read ~0 thickness everywhere.
FLAGS_DECOY = RF_OPAQUE | RF_CULL_BACK | RF_SKIP_AABBS     # 529
COMMITTED = 1                   # RayQueryCommittedIntersectionKHR
GATE_MASK = 39                  # the value the module's own NEE cullMask
                                # select yields when the pixel is lit; the
                                # narrow mask its own radiance traces use
                                # (98 sec 12.6a), so shadow-only proxies and
                                # LOD shells cannot supply a false backface
TMIN = TH_FLOOR                 # 0.0015 m -- 71's min-t floor, now a tmin
TMAX = T_SEG                    # 0.018  m
TMAX_DECOY = 0.10               # the "wrong tmax" decoy: 10 cm reads through
                                # a whole head and calls it thin

# --mode hit: the falsifier's instrument. Flat, no transfer, additive, so the
# map is readable independently of the transfer shape. Values are 66's
# probe-palette magnitudes verbatim (chosen numerically there against AgX
# inset crosstalk); dead channels are exact 0.0.
HIT_RGB  = (0.0, 0.4, 3.2)      # BLUE  -- gate passed AND the query committed
MISS_RGB = (3.2, 0.0, 0.0)      # RED   -- gate passed and it committed NOTHING


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


def build(mod, k, mode='glow', soft=None, decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, ALL of them, before any edit (GOTCHAS 12) -------------
    writes = find_image_writes(mod)
    nee = find_nee_trace(mod, fs, fe)              # anchor: S, P, backlit, 39
    sunrad = find_sun_radiance(mod, nee["line"])   # anchor: sun RGB
    fetch_root = find_class_fetch(mod, fs, fe)     # anchor: class-1 skin
    offctor = find_origin_offset(mod, nee)         # anchor: N (for the wrap)
    counter, phdr = find_path_counter(mod, fs, fe)  # 90: the PATH loop
    legacy = None
    try:
        legacy = E.find_bounce_counter(mod, fs, fe, nee["line"])
    except SystemExit:
        legacy = None
    if decoy == 'counter':
        if legacy is None:
            die(f"{mod.name}: --decoy counter needs the legacy helper to "
                f"resolve, and it did not")
        counter = legacy
    eb_lab, eb_term = entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))

    # SkipAABBs is illegal without it, and it is not ours to add silently.
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability -- "
            f"ray flag SkipAABBsKHR (0x200) would be illegal")
    accel = nee["ops"][0]
    aline, _ = mod.find_def(accel)
    if aline is None or aline > nee["line"]:
        die(f"{mod.name}: acceleration structure {accel} has no definition "
            f"above the sun-NEE trace")

    rep = {"mode": mode, "k": k, "ld_m": LD_M, "tmin": TMIN,
           "tmax": TMAX_DECOY if decoy == 'tmax' else TMAX,
           "ray_flags": FLAGS_DECOY if decoy == 'flags' else FLAGS,
           "ray_flags_names": FLAGS_NAMES, "commit": "closest",
           "decoy": decoy, "gate_mask": GATE_MASK,
           "nee_line": nee["line"] + 1, "accel": accel,
           "origin": nee["ops"][6], "direction": nee["ops"][8],
           "backlit": nee["backlit"], "sun_radiance": sunrad,
           "path_counter": counter, "path_header": phdr,
           "legacy_counter": legacy,
           "legacy_helper_was_wrong": (legacy is not None and legacy != counter),
           "soft": {"wide": soft[0], "wrap": soft[1]} if soft else None}

    # ---- types / constants ------------------------------------------------
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")

    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u32 = _uc(mod, consts, 32)
    umask = _uc(mod, consts, GATE_MASK)
    uflags = _uc(mod, consts, FLAGS_DECOY if decoy == 'flags' else FLAGS)
    f0 = _fc(mod, consts, 0.0)
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, TMAX_DECOY if decoy == 'tmax' else TMAX)
    if mode == 'hit':
        hitc = [(_fc(mod, consts, v) if v != 0.0 else f0) for v in HIT_RGB]
        misc = [(_fc(mod, consts, v) if v != 0.0 else f0) for v in MISS_RGB]
    else:
        fk = _fc(mod, consts, k)
        fclamp = _fc(mod, consts, CLAMP)
        finv = [_fc(mod, consts, 1.0 / ld) for ld in LD_M]
        if soft:
            finv2 = [_fc(mod, consts, 1.0 / (soft[0] * ld)) for ld in LD_M]
            fwrap = _fc(mod, consts, soft[1])
            fhalf = _fc(mod, consts, 0.5)

    # ---- entry block: the query object + 3 glow accumulators, ONE edit ----
    # All Function OpVariables must be the leading instructions of the first
    # block, so they go at the end of that run; the stores follow in the same
    # edit so apply_edits cannot reorder them against each other.
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rq = mod.new_id()
    gv = [mod.new_id() for _ in range(3)]
    ind0 = '               '
    edits.append((at, [f"{ind0}{rq} = OpVariable {ptr_rq} Function"]
                  + [f"{ind0}{g} = OpVariable {ptrFF} Function" for g in gv]
                  + [f"{ind0}OpStore {g} {f0}" for g in gv]))

    # ---- the splice: straight-line, immediately after the sun-NEE trace ----
    ops, ind = nee["ops"], nee["ind"]
    ins = []
    nid = mod.new_id

    # gate 1/3: class-1 skin. Clone of the module's OWN material fetch chain.
    cloned = []
    fetch_here = clone_chain(mod, fetch_root, safe, {}, cloned, fs)
    for cid, body in cloned:
        ins.append(f"{ind}{cid} = {body}")
    g_ext = nid(); ins.append(f"{ind}{g_ext} = OpCompositeExtract %uint {fetch_here} 1")
    g_and = nid(); ins.append(f"{ind}{g_and} = OpBitwiseAnd %uint {g_ext} %uint_4294967264")
    g_skin = nid(); ins.append(f"{ind}{g_skin} = OpIEqual {boolt} {g_and} {u32}")
    # gate 2/3: backlit -- the condition of the module's own
    # OpSelect(cond, 0, 39) NEE cullMask idiom (cond true <=> N.S <= 0).
    # gate 3/3: the PRIMARY path segment -- 90's find_path_counter, not the
    # sample loop's phi the legacy helper returns in 5 of 12 permutations.
    g_p0 = nid(); ins.append(f"{ind}{g_p0} = OpIEqual {boolt} {counter} {u0}")
    g_a1 = nid(); ins.append(f"{ind}{g_a1} = OpLogicalAnd {boolt} {g_skin} {nee['backlit']}")
    g_all = nid(); ins.append(f"{ind}{g_all} = OpLogicalAnd {boolt} {g_a1} {g_p0}")
    # Folded into the cull mask, exactly as 55's costing wants it: mask 0 is a
    # guaranteed near-free miss, and it costs no branch, so the splice adds
    # ZERO control flow.
    g_msk = nid(); ins.append(f"{ind}{g_msk} = OpSelect %uint {g_all} {umask} {u0}")

    # the query: origin and direction are the sun-NEE trace's own operands, by
    # SSA id, never reconstructed (55's clone-by-id discipline).
    ins.append(f"{ind}OpRayQueryInitializeKHR {rq} {accel} {uflags} {g_msk} "
               f"{ops[6]} {ftmin} {ops[8]} {ftmax}")
    pro = nid(); ins.append(f"{ind}{pro} = OpRayQueryProceedKHR {boolt} {rq}")
    ity = nid(); ins.append(f"{ind}{ity} = OpRayQueryGetIntersectionTypeKHR %uint {rq} {u1}")
    hit = nid(); ins.append(f"{ind}{hit} = OpINotEqual {boolt} {ity} {u0}")
    tq = nid(); ins.append(f"{ind}{tq} = OpRayQueryGetIntersectionTKHR %float {rq} {u1}")
    # t is UNDEFINED when nothing was committed, so it is never allowed to
    # reach arithmetic: substitute tmax, which is finite and transmits ~0.
    # (A NaN multiplied by a zero gate is still a NaN, and a NaN in the
    # radiance write would poison the accumulator for the whole frame.)
    tu = nid(); ins.append(f"{ind}{tu} = OpSelect %float {hit} {tq} {ftmax}")
    ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {g_all} {hit}")

    if mode == 'hit':
        # The falsifier's instrument: flat paint, no transfer, so a hit map
        # can be read without any claim about the transfer being right.
        nh = nid(); ins.append(f"{ind}{nh} = OpLogicalNot {boolt} {hit}")
        miss = nid(); ins.append(f"{ind}{miss} = OpLogicalAnd {boolt} {g_all} {nh}")
        for c in range(3):
            s0 = nid(); ins.append(f"{ind}{s0} = OpSelect %float {miss} {misc[c]} {f0}")
            s1 = nid(); ins.append(f"{ind}{s1} = OpSelect %float {ok} {hitc[c]} {s0}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {s1}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    else:
        kg = nid(); ins.append(f"{ind}{kg} = OpSelect %float {ok} {fk} {f0}")
        if soft:
            # W3 wrap: feather the backlit border. N is the module's own
            # primary-hit normal, harvested by find_origin_offset from the
            # engine's own self-hit offset construction; S is the NEE trace's
            # own direction operand.
            s_c = []
            for c in range(3):
                de = nid(); ins.append(f"{ind}{de} = OpCompositeExtract %float {ops[8]} {c}")
                s_c.append(de)
            nvp = nid(); ins.append(f"{ind}{nvp} = OpCompositeConstruct %v3float {' '.join(offctor['normal'])}")
            svp = nid(); ins.append(f"{ind}{svp} = OpCompositeConstruct %v3float {' '.join(s_c)}")
            nds = nid(); ins.append(f"{ind}{nds} = OpDot %float {nvp} {svp}")
            bnd = nid(); ins.append(f"{ind}{bnd} = OpFNegate %float {nds}")
            wrp = nid(); ins.append(f"{ind}{wrp} = OpExtInst %float {glsl} SmoothStep {f0} {fwrap} {bnd}")
            kw = nid(); ins.append(f"{ind}{kw} = OpFMul %float {kg} {wrp}")
        else:
            kw = kg
        for c in range(3):
            e1 = nid(); ins.append(f"{ind}{e1} = OpFMul %float {tu} {finv[c]}")
            e2 = nid(); ins.append(f"{ind}{e2} = OpFNegate %float {e1}")
            e3 = nid(); ins.append(f"{ind}{e3} = OpExtInst %float {glsl} Exp {e2}")
            if soft:
                e4 = nid(); ins.append(f"{ind}{e4} = OpFMul %float {tu} {finv2[c]}")
                e5 = nid(); ins.append(f"{ind}{e5} = OpFNegate %float {e4}")
                e6 = nid(); ins.append(f"{ind}{e6} = OpExtInst %float {glsl} Exp {e5}")
                e7 = nid(); ins.append(f"{ind}{e7} = OpFAdd %float {e3} {e6}")
                tr = nid(); ins.append(f"{ind}{tr} = OpFMul %float {e7} {fhalf}")
            else:
                tr = e3
            m1 = nid(); ins.append(f"{ind}{m1} = OpFMul %float {tr} {kw}")
            m2 = nid(); ins.append(f"{ind}{m2} = OpFMul %float {m1} {sunrad[c]}")
            m3 = nid(); ins.append(f"{ind}{m3} = OpExtInst %float {glsl} NMin {m2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {m3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    edits.append((nee["line"], ins))
    rep["splice_instructions"] = len(ins)
    rep["cloned_fetch_ops"] = len(cloned)
    rep["rq_var"] = rq
    rep["accum_vars"] = gv

    # ---- ADD the accumulated term at every radiance write ------------------
    # An ADD, not a multiply. 98 sec 12.4: a multiply can only rescale light
    # that is already in this raygen's store, and on the shadowed side of a
    # backlit head there is nearly none.
    added, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            die(f"{mod.name}: write at line {w['line']+1} has a non-construct "
                f"texel -- refusing")
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({"line": w['line'] + 1, "why": "constant-zero"})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({"line": w['line'] + 1, "why": "scalar-broadcast"})
            continue
        wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        wi, newc = [], []
        for ch in range(3):
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {gv[ch]}")
            a = nid(); wi.append(f"{wind}{a} = OpFAdd %float {c[ch]} {l}")
            newc.append(a)
        nt = nid()
        wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                  f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((w['line'] - 1, wi))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        added.append({"line": w['line'] + 1})
    if not added:
        die(f"{mod.name}: no radiance write to add the term at")
    rep["writes_added"], rep["writes_skipped"] = added, skipped

    # SPIR-V >= 1.4 wants every referenced global on the interface list. The
    # two accumulator sets are Function storage and the query object is too,
    # so nothing new goes on the interface here -- asserted rather than
    # assumed, because getting it wrong is a spirv-val failure at build time.
    return consts, edits, rep


def process(path, outdir, k, mode='glow', soft=None, decoy=None, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    identity = (mode == 'glow' and k == 0.0 and decoy is None)
    if identity:
        # THE CONTROL. Nothing is emitted: the module is written back exactly
        # as it was disassembled, so the assembled output is byte-identical to
        # the base (build gate 1 proves the round trip is neutral). A control
        # that is the base bytes cannot be a tautology about the splice -- it
        # is a statement about the SELECTOR and the layer.
        rep['earglow_rq'] = {"mode": "control", "k": 0.0,
                             "emitted": 0,
                             "why": "k=0 glow: identity, no instructions"}
    else:
        consts, edits, rep['earglow_rq'] = build(mod, k, mode, soft, decoy)
        apply_edits(mod, consts, edits)
        _add_header(mod)

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    # SPV_KHR_ray_query in a SPIR-V 1.4 module: vulkan1.4 is the env that
    # admits both.
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
                    help='transmission strength (sunRadiance multiplier). '
                         '0 with --mode glow = the byte-identity CONTROL.')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'),
                    help="glow = W1+W3 transmission; hit = the falsifier's "
                         "flat hit/miss diagnostic, no transfer")
    ap.add_argument('--wide', type=float,
                    help='W3 soft transfer: second-lobe widening factor')
    ap.add_argument('--wrap', type=float,
                    help='W3 wrap: smoothstep upper edge on -N.S')
    ap.add_argument('--decoy', choices=('flags', 'tmax', 'counter'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow_rq.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if (a.wide is None) != (a.wrap is None):
        ap.error('--wide and --wrap must be given together')
    soft = (a.wide, a.wrap) if a.wide is not None else None
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.mode, soft, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
