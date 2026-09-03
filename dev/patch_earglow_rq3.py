#!/usr/bin/env python3
"""earglow-rq3 -- ear glow with a SUN-VISIBILITY test on the exit point.
handoff/101 sec 15.

WHY THIS EXISTS (read handoff/101 sec 15 first).

`earglow-rq2` was shot BACKLIT on 2026-09-02 (23:46:49) and the verdict was:

    "shows the effect still bleeding through the front of faces. Faces in
     shadow still get the effect. Otherwise the ears and noses look great.
     But the sun rays are triggering the effect on the wrong side of the face
     in some contexts."

The ears and noses passing is `101` sec 13's PASS row: the instance-match gate
works. What is left is a different mistake, and it is the third of its shape in
this document -- A GEOMETRIC TEST SUBSTITUTED FOR A LIGHTING TEST:

    query B answers "is there a same-instance wall within 18 mm along S?"
    it does NOT answer "is that wall IN SUNLIGHT?"

Sunward from the shaded FRONT of a face the ray goes back INTO the head and
commits a same-instance backface a few millimetres away -- the eye socket
behind the inner canthus, the nasal cavity wall, the inner surface of the lip.
Same mesh, thin, and never lit: they are interior surfaces. The same omission
is why a face standing in the shadow of a wall still glows: nothing tests
whether the exit point can see the sun. `70` W1 said this in as many words --
"the vis ray from the exit point still has to reach the sun" -- and `101` never
built it.

    query A   98's primary-surface query (flags 517, +/-0.1 % bracket on |P|),
              committed InstanceId: the instance the PIXEL is on.
    query B   the sunward cull-front thickness query (flags 545, tmin 1.5 mm,
              tmax 18 mm), committed InstanceId and committed T.
    query C   NEW. Sun visibility FROM THE EXIT POINT:
                origin    P + (t_B + PUSH)*S   -- past the backface, in air
                direction S                    -- the module's own sun vector
                tmin      TMIN_C (1 mm)
                tmax      the module's OWN sun shadow-ray tmax operand
                flags     517 Opaque|TerminateOnFirstHit|SkipAABBs -- NO
                          culling: any geometry at all occludes the sun
                mask      the gate mask, whose non-zero arm is asserted equal
                          to the module's own sun shadow-ray cull mask, so C
                          sees exactly the occluders the sun does

    accept <=> A committed AND B committed AND A.InstanceId == B.InstanceId
               AND C MISSED

A rejected pixel costs three queries and no branch: all three share the one
OpSelect(gate, 39, 0) cull mask, so a shut gate is three free misses.

THE DIAGNOSTIC (-rq3-hit) CARRIES THE GLOW'S FULL GATE, wrap included
(`101` sec 14.3's defect, fixed in sec 15.1): its map is the glow's paintable
set, not a superset of it.

    BLUE  B commits same-instance AND C misses  -- accepted, real transmission
    RED   B commits same-instance BUT C hits    -- an interior wall, or a real
                                                   occluder between the exit
                                                   point and the sun
    nothing                                     -- B missed, a foreign
                                                   instance, or the gate is shut

  ./dev/build_earglow_rq3.sh          # all three rungs + gates
  python3 dev/patch_earglow_rq3.py <in.spvasm> --outdir <dir> --k 0.22 \
          --wrap 0.35 [--wide 4.0] [--mode hit] [--decoy noc|cullfront|invert]

NOT EDITED BY THIS FILE, only imported: dev/patch_rayq.py, dev/patch_earglow.py,
dev/patch_earglow_rq.py, dev/patch_earglow_rq2.py, dev/patch_cavity2.py.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
import patch_earglow as E
from patch_earglow import (find_nee_trace, find_sun_radiance, find_class_fetch,
                           find_origin_offset, clone_chain, entry_block_span,
                           LD_M, CLAMP)
from patch_cavity2 import find_path_counter
# query A verbatim from 98: the primary-ray reconstruction detector and the
# header inserter. patch_rayq.py is NOT edited by this file.
from patch_rayq import _find_primary_ray, _add_header
# query B and the transfer, verbatim from 101 sec 2. patch_earglow_rq.py is
# NOT edited by this file.
from patch_earglow_rq import (_uc, _fc, _ensure_line, FLAGS, FLAGS_NAMES,
                              GATE_MASK, TMIN, TMAX, HIT_RGB, MISS_RGB)
# queries A and B and the diagnostic units, verbatim from 101 sec 12.
# patch_earglow_rq2.py is NOT edited by this file.
from patch_earglow_rq2 import (FLAGS_A, FLAGS_A_NAMES, BRACKET_LO, BRACKET_HI,
                               BRACKET_EPS, GETTER_ID, GETTER_CUSTOM,
                               DIAG_HIT, DIAG_MISS)

# --- query C: sun visibility from the exit point ---------------------------
# Same flags as A (517) for a different reason: C asks only "is ANYTHING in the
# way", so the first hit is enough and nothing may be culled by winding.
FLAGS_C = FLAGS_A                                   # 517
FLAGS_C_NAMES = FLAGS_A_NAMES
PUSH = 0.001        # 1 mm further along S, so C starts in AIR past the wall
TMIN_C = 0.001      # 1 mm: C's own origin is already pushed, this is slack

def uval(mod, ident):
    line, body = mod.find_def(ident)
    m = re.match(r'OpConstant %\w+ (\d+)$', body or '')
    return int(m.group(1)) if m else None


def fval_of(mod, ident):
    line, body = mod.find_def(ident)
    m = re.match(r'OpConstant %\w+ ([-+0-9.eE]+)$', body or '')
    return float(m.group(1)) if m else None


def build(mod, k, mode='glow', soft=None, decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, ALL of them, before any edit (GOTCHAS 12) -------------
    writes = find_image_writes(mod)
    nee = find_nee_trace(mod, fs, fe)
    sunrad = find_sun_radiance(mod, nee["line"])
    fetch_root = find_class_fetch(mod, fs, fe)
    offctor = find_origin_offset(mod, nee)
    counter, phdr = find_path_counter(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)           # 98's query A anchor
    if prim['line'] > nee["line"]:
        die(f"{mod.name}: the primary reconstruction (line {prim['line']}) is "
            f"below the splice site (line {nee['line']+1}) -- query A's ids "
            f"would not dominate")
    eb_lab, eb_term = entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability -- "
            f"ray flag SkipAABBsKHR (0x200) would be illegal")
    accel = nee["ops"][0]
    aline, _ = mod.find_def(accel)
    if aline is None or aline > nee["line"]:
        die(f"{mod.name}: acceleration structure {accel} has no definition "
            f"above the sun-NEE trace")

    # Query C must see the occluders the SUN sees, so its cull mask has to be
    # the module's own sun shadow-ray mask. That mask is
    # OpSelect(backlit, 0, N) -- zero when the module skips the shadow ray --
    # so the value that matters is the NON-ZERO arm N, and the splice's own
    # OpSelect(gate, GATE_MASK, 0) has to agree with it. Asserted, never
    # assumed: a module whose shadow ray uses a different mask would give C a
    # different set of occluders than the sun and the test would be a lie.
    mline, mbody = mod.find_def(nee["ops"][2])
    msel = re.match(r'OpSelect %\w+ (%\w+) (%\w+) (%\w+)$', mbody or '')
    if not msel:
        die(f"{mod.name}: the sun shadow ray's cull mask {nee['ops'][2]} is not "
            f"an OpSelect -- cannot re-derive the sun's occluder set")
    marms = [uval(mod, msel.group(2)), uval(mod, msel.group(3))]
    if sorted(x for x in marms if x is not None) != [0, GATE_MASK]:
        die(f"{mod.name}: the sun shadow ray's cull mask arms are {marms}, "
            f"want [0, {GATE_MASK}] -- query C would not see the sun's "
            f"occluder set")
    # C's tmax is the module's own sun shadow-ray tmax operand, so C reaches
    # exactly as far as the engine's own sun visibility test does.
    tmax_c = nee["ops"][9]
    if uval(mod, tmax_c) is None and fval_of(mod, tmax_c) is None:
        die(f"{mod.name}: the sun shadow ray's tmax {tmax_c} is not a constant "
            f"-- refusing to reuse an operand I cannot report")

    getter = GETTER_ID
    rep = {"mode": mode, "k": k, "ld_m": LD_M, "tmin": TMIN, "tmax": TMAX,
           "ray_flags_b": FLAGS, "ray_flags_b_names": FLAGS_NAMES,
           "ray_flags_a": FLAGS_A, "ray_flags_a_names": FLAGS_A_NAMES,
           "bracket": [BRACKET_LO, BRACKET_HI, BRACKET_EPS],
           "commit_a": "first", "commit_b": "closest",
           "match_getter": getter, "match_op": (
               "OpINotEqual" if decoy == 'invert' else "OpIEqual"),
           "match_gate": True,
           "ray_flags_c": FLAGS_C, "ray_flags_c_names": FLAGS_C_NAMES,
           "push_c": PUSH, "tmin_c": TMIN_C, "tmax_c": tmax_c,
           "tmax_c_value": (uval(mod, tmax_c) if uval(mod, tmax_c) is not None
                            else fval_of(mod, tmax_c)),
           "sun_mask_arms": marms, "vis_gate": decoy != 'noc',
           "vis_flags_cull_front": decoy == 'cullfront',
           "vis_inverted": decoy == 'invert',
           "decoy": decoy, "gate_mask": GATE_MASK,
           "nee_line": nee["line"] + 1, "accel": accel,
           "origin": nee["ops"][6], "direction": nee["ops"][8],
           "backlit": nee["backlit"], "sun_radiance": sunrad,
           "path_counter": counter, "path_header": phdr,
           "primary_line": prim['line'], "primary_V": prim['V'],
           "diag_scaled_by_sun_radiance": mode == 'hit',
           "diag_wrap_gated": mode == 'hit',
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
    uflags_b = _uc(mod, consts, FLAGS)
    uflags_a = _uc(mod, consts, FLAGS_A)
    f0 = _fc(mod, consts, 0.0)
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, TMAX)
    flo = _fc(mod, consts, BRACKET_LO)
    fhi = _fc(mod, consts, BRACKET_HI)
    feps = _fc(mod, consts, BRACKET_EPS)
    v3zero = _ensure_line(
        mod, consts,
        r'\s*(%\w+)\s*=\s*OpConstantComposite %v3float '
        + re.escape(f0) + r' ' + re.escape(f0) + r' ' + re.escape(f0) + r'\s*$',
        lambda n: f"    {n} = OpConstantComposite %v3float {f0} {f0} {f0}")
    fclamp = _fc(mod, consts, CLAMP)
    # FLAGS_C == FLAGS_A (517) for the live rungs, and _uc scans mod.lines only
    # -- it cannot see a constant still pending in `consts`, so asking for 517
    # twice mints the id twice and spirv-val rejects the module. Reuse it.
    uflags_c = (_uc(mod, consts, 0x10 | FLAGS_C) if decoy == 'cullfront'
                else uflags_a)
    fpush = _fc(mod, consts, PUSH)
    ftmin_c = _fc(mod, consts, TMIN_C)
    # The wrap edge is shared: the glow rungs feather their transfer with it and
    # -rq3-hit feathers its flat paint with the SAME constant, so the diagnostic
    # maps the glow's paintable set and not a superset of it (101 sec 14.3).
    fwrap = None
    if mode == 'hit':
        if True:
            if not soft:
                die("--mode hit needs --wrap: rq3's diagnostic carries the GLOW'S "
                    "FULL GATE, wrap included (101 sec 14.3)")
            fwrap = _fc(mod, consts, soft[1])
        hitc = [(_fc(mod, consts, v) if v != 0.0 else f0) for v in DIAG_HIT]
        misc = [(_fc(mod, consts, v) if v != 0.0 else f0) for v in DIAG_MISS]
    else:
        fk = _fc(mod, consts, k)
        finv = [_fc(mod, consts, 1.0 / ld) for ld in LD_M]
        if soft:
            finv2 = [_fc(mod, consts, 1.0 / (soft[0] * ld)) for ld in LD_M]
            fwrap = _fc(mod, consts, soft[1])
            fhalf = _fc(mod, consts, 0.5)

    # ---- entry block: THREE query objects + 3 accumulators, ONE edit ------
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rqA, rqB, rqC = mod.new_id(), mod.new_id(), mod.new_id()
    gv = [mod.new_id() for _ in range(3)]
    ind0 = '               '
    edits.append((at, [f"{ind0}{rqA} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqB} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqC} = OpVariable {ptr_rq} Function"]
                  + [f"{ind0}{g} = OpVariable {ptrFF} Function" for g in gv]
                  + [f"{ind0}OpStore {g} {f0}" for g in gv]))

    # ---- the splice: straight-line, immediately after the sun-NEE trace ----
    ops, ind = nee["ops"], nee["ind"]
    ins = []
    nid = mod.new_id

    # gate: class-1 skin AND backlit AND primary path segment. Unchanged from
    # 101 sec 2 -- the instance match is added BELOW it, not instead of it.
    cloned = []
    fetch_here = clone_chain(mod, fetch_root, safe, {}, cloned, fs)
    for cid, body in cloned:
        ins.append(f"{ind}{cid} = {body}")
    g_ext = nid(); ins.append(f"{ind}{g_ext} = OpCompositeExtract %uint {fetch_here} 1")
    g_and = nid(); ins.append(f"{ind}{g_and} = OpBitwiseAnd %uint {g_ext} %uint_4294967264")
    g_skin = nid(); ins.append(f"{ind}{g_skin} = OpIEqual {boolt} {g_and} {u32}")
    g_p0 = nid(); ins.append(f"{ind}{g_p0} = OpIEqual {boolt} {counter} {u0}")
    g_a1 = nid(); ins.append(f"{ind}{g_a1} = OpLogicalAnd {boolt} {g_skin} {nee['backlit']}")
    g_all = nid(); ins.append(f"{ind}{g_all} = OpLogicalAnd {boolt} {g_a1} {g_p0}")
    g_msk = nid(); ins.append(f"{ind}{g_msk} = OpSelect %uint {g_all} {umask} {u0}")

    # ---- query A: 98's primary-surface query --------------------------------
    # camera at the origin of P's space (94 sec 3.3), direction = the module's
    # own normalized view ray, t = |P| = dot(P,P) * rsqrt(dot(P,P)) -- one
    # instruction, no new constant, entirely the module's own ids.
    tA = nid(); ins.append(f"{ind}{tA} = OpFMul %float {prim['dot']} {prim['rsqrt']}")
    dA = nid(); ins.append(f"{ind}{dA} = OpCompositeConstruct %v3float "
                           f"{prim['V'][0]} {prim['V'][1]} {prim['V'][2]}")
    aLo = nid(); ins.append(f"{ind}{aLo} = OpFMul %float {tA} {flo}")
    aH0 = nid(); ins.append(f"{ind}{aH0} = OpFMul %float {tA} {fhi}")
    aHi = nid(); ins.append(f"{ind}{aHi} = OpFAdd %float {aH0} {feps}")
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqA} {accel} {uflags_a} {g_msk} "
               f"{v3zero} {aLo} {dA} {aHi}")
    proA = nid(); ins.append(f"{ind}{proA} = OpRayQueryProceedKHR {boolt} {rqA}")
    ityA = nid(); ins.append(f"{ind}{ityA} = OpRayQueryGetIntersectionTypeKHR %uint {rqA} {u1}")
    hitA = nid(); ins.append(f"{ind}{hitA} = OpINotEqual {boolt} {ityA} {u0}")
    idA = nid(); ins.append(f"{ind}{idA} = {getter} %uint {rqA} {u1}")

    # ---- query B: the sunward cull-front thickness query (101 sec 2) --------
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqB} {accel} {uflags_b} {g_msk} "
               f"{ops[6]} {ftmin} {ops[8]} {ftmax}")
    proB = nid(); ins.append(f"{ind}{proB} = OpRayQueryProceedKHR {boolt} {rqB}")
    ityB = nid(); ins.append(f"{ind}{ityB} = OpRayQueryGetIntersectionTypeKHR %uint {rqB} {u1}")
    hitB = nid(); ins.append(f"{ind}{hitB} = OpINotEqual {boolt} {ityB} {u0}")
    tqB = nid(); ins.append(f"{ind}{tqB} = OpRayQueryGetIntersectionTKHR %float {rqB} {u1}")
    tu = nid(); ins.append(f"{ind}{tu} = OpSelect %float {hitB} {tqB} {ftmax}")
    idB = nid(); ins.append(f"{ind}{idB} = {getter} %uint {rqB} {u1}")

    # ---- the instance match, unchanged from 101 sec 12 ---------------------
    # An InstanceId read from a non-committed query is undefined, so the
    # equality is ANDed with BOTH commits and never stands alone.
    same = nid(); ins.append(f"{ind}{same} = OpIEqual {boolt} {idA} {idB}")
    both = nid(); ins.append(f"{ind}{both} = OpLogicalAnd {boolt} {hitA} {hitB}")
    match = nid(); ins.append(f"{ind}{match} = OpLogicalAnd {boolt} {both} {same}")

    # ---- THE ONE NEW VARIABLE: query C, sun visibility from the exit point --
    # origin = P + (t_B + PUSH)*S. `tu` is the GUARDED t (tmax when B missed),
    # so the origin is always finite; when B missed the whole term is gated off
    # below anyway. PUSH puts the start in AIR past the committed backface --
    # without it C's first hit is the wall it just left.
    tp = nid(); ins.append(f"{ind}{tp} = OpFAdd %float {tu} {fpush}")
    off = nid(); ins.append(f"{ind}{off} = OpVectorTimesScalar %v3float {ops[8]} {tp}")
    org = nid(); ins.append(f"{ind}{org} = OpFAdd %v3float {ops[6]} {off}")
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqC} {accel} {uflags_c} {g_msk} "
               f"{org} {ftmin_c} {ops[8]} {tmax_c}")
    proC = nid(); ins.append(f"{ind}{proC} = OpRayQueryProceedKHR {boolt} {rqC}")
    ityC = nid(); ins.append(f"{ind}{ityC} = OpRayQueryGetIntersectionTypeKHR %uint {rqC} {u1}")
    hitC = nid(); ins.append(f"{ind}{hitC} = OpINotEqual {boolt} {ityC} {u0}")
    if decoy == 'invert':
        # accept exactly what must be rejected: the OCCLUDED exit points
        visC = hitC
    else:
        visC = nid(); ins.append(f"{ind}{visC} = OpLogicalNot {boolt} {hitC}")

    if decoy == 'noc':
        # `earglow-rq2` behaviour rebuilt through this patcher: C is traced but
        # never consulted. Exists only so build_earglow_rq3.sh can show the
        # verifier rejects it. Never installed.
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {g_all} {match}")
        gm = nid(); ins.append(f"{ind}{gm} = OpLogicalAnd {boolt} {g_all} {match}")
        nv = nid(); ins.append(f"{ind}{nv} = OpLogicalNot {boolt} {match}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gm} {nv}")
    else:
        gm = nid(); ins.append(f"{ind}{gm} = OpLogicalAnd {boolt} {g_all} {match}")
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {gm} {visC}")
        # RED: a same-instance wall that CANNOT see the sun -- an interior
        # surface (eye socket, nasal cavity, inner lip) or a real occluder.
        nv = nid(); ins.append(f"{ind}{nv} = OpLogicalNot {boolt} {visC}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gm} {nv}")
    rep["vis_id"] = visC
    rep["match_id"] = same
    rep["ok_id"] = ok

    def emit_wrap():
        # W3's envelope, emitted identically for the glow rungs and for -hit.
        # ONE definition, so the diagnostic cannot drift from the rung it is
        # supposed to be a map of (101 sec 14.3).
        s_c = []
        for c in range(3):
            de = nid(); ins.append(f"{ind}{de} = OpCompositeExtract %float {ops[8]} {c}")
            s_c.append(de)
        nvp = nid(); ins.append(f"{ind}{nvp} = OpCompositeConstruct %v3float {' '.join(offctor['normal'])}")
        svp = nid(); ins.append(f"{ind}{svp} = OpCompositeConstruct %v3float {' '.join(s_c)}")
        nds = nid(); ins.append(f"{ind}{nds} = OpDot %float {nvp} {svp}")
        bnd = nid(); ins.append(f"{ind}{bnd} = OpFNegate %float {nds}")
        w = nid(); ins.append(f"{ind}{w} = OpExtInst %float {glsl} SmoothStep {f0} {fwrap} {bnd}")
        return w

    if mode == 'hit':
        # Flat, no transfer, ADDITIVE, and IN UNITS OF THE SUN RADIANCE so it
        # reads on lit skin too (101 sec 12.3). B misses -> nothing painted.
        # rq3's -hit multiplies by the SAME wrap envelope the glow rung uses.
        wfac = emit_wrap()
        for c in range(3):
            s0 = nid(); ins.append(f"{ind}{s0} = OpSelect %float {rej} {misc[c]} {f0}")
            s1 = nid(); ins.append(f"{ind}{s1} = OpSelect %float {ok} {hitc[c]} {s0}")
            if wfac is not None:
                sw = nid(); ins.append(f"{ind}{sw} = OpFMul %float {s1} {wfac}")
                s1 = sw
            s2 = nid(); ins.append(f"{ind}{s2} = OpFMul %float {s1} {sunrad[c]}")
            s3 = nid(); ins.append(f"{ind}{s3} = OpExtInst %float {glsl} NMin {s2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {s3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    else:
        kg = nid(); ins.append(f"{ind}{kg} = OpSelect %float {ok} {fk} {f0}")
        if soft:
            wrp = emit_wrap()
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
    rep["rq_vars"] = [rqA, rqB]
    rep["accum_vars"] = gv

    # ---- ADD the accumulated term at every radiance write ------------------
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
    if mode == 'glow' and k == 0.0 and decoy is None:
        # THE CONTROL is `earglow-rq-ctl` and it is unchanged (handoff/101
        # sec 6): nothing is emitted, so the output is the base bytes.
        rep['earglow_rq3'] = {"mode": "control", "k": 0.0, "emitted": 0,
                              "why": "k=0 glow: identity, no instructions"}
    else:
        consts, edits, rep['earglow_rq3'] = build(mod, k, mode, soft, decoy)
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
    ap.add_argument('--k', type=float, required=True)
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--decoy', choices=('noc', 'cullfront', 'invert'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow_rq3.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if (a.wide is None) != (a.wrap is None):
        ap.error('--wide and --wrap must be given together')
    soft = (a.wide, a.wrap) if a.wide is not None else None
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.mode, soft, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
