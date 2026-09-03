#!/usr/bin/env python3
"""earglow-rq2 -- ear glow with an INSTANCE-MATCH gate. handoff/101 sec 12.

WHY THIS EXISTS (read handoff/101 sec 12 first).

`earglow-rq` was shot on 2026-09-02 and the user's verdict was:

    "Its the same edge case issue as before. The far side of the head is
     glowing at the hairline, underneath her clothes, wrong side of her ear.
     Side closest to the sun isnt glowing any brighter. Eyelid in shaded side
     of face is glowing"

`70` W1's central claim -- "aim the ray at the sun, cull front faces, and the
first backface within 18 mm IS the sun-side wall of flesh" -- is FALSE wherever
another mesh sits within 18 mm sunward of the skin. At the hairline, under a
collar and behind an eyelid that is ALWAYS true: hair cards lie on the scalp
(a two-sided card presents a backface at any distance above the 1.5 mm floor),
clothing has an inner surface, and the eyeball sits behind the lid. W1 did not
dissolve the consistency-gate problem; it MOVED it.

The fix here is one variable: reject a committed backface that belongs to a
DIFFERENT INSTANCE than the primary surface.

    query A   98's primary-surface query: the module's OWN view ray, a
              +/-0.1 % bracket around |P|, flags 517, committed InstanceId.
              This is the instance the PIXEL is on.
    query B   the sunward cull-front thickness query, unchanged from
              `earglow-rq`: flags 545, tmin 1.5 mm, tmax 18 mm, committed
              InstanceId and committed T.

    accept <=> A committed AND B committed AND A.InstanceId == B.InstanceId

No threshold, no depth comparison, no consistency band. Within ONE frame the
TLAS is one build, so the two queries in the same dispatch see the same
instance numbering -- `98` sec 13 measured that InstanceId is only unstable
ACROSS frames, and both queries here run in the same invocation.

THE ASSUMPTION, stated so the diagnostic can test it: head/ear/nose skin, hair,
clothing and eyeballs are SEPARATE TLAS instances in this engine. If hair
shares the body instance the gate cannot separate them and `-rq2-hit` will
paint blue at the hairline -- that is a real, pre-registered outcome
(handoff/101 sec 13), not a build failure.

THE DIAGNOSTIC PAINT IS SCALED BY THE SUN RADIANCE. `earglow-rq-hit` added a
bare 3.2 and was INVISIBLE in the shot (handoff/101 sec 12.3) while
`earglow-rq-hi`, which adds k*transfer*sunRadiance at the same pixels, was
obvious -- so 3.2 is far below this engine's radiance scale. It was never a
multiply-vs-add problem (the shipped bytes are an OpFAdd; see sec 12.3); it was
a UNITS problem. Here the flat paint is DIAG_RGB * sunRadiance, i.e. the same
units as the effect it is diagnosing.

  ./dev/build_earglow_rq2.sh          # all three rungs + gates
  python3 dev/patch_earglow_rq2.py <in.spvasm> --outdir <dir> --k 0.22 \
          [--mode hit] [--wide 4.0 --wrap 0.35] [--decoy nomatch|custom|invert]

NOT EDITED BY THIS FILE, only imported: dev/patch_rayq.py (query A's primary
reconstruction), dev/patch_earglow.py (the anchors), dev/patch_earglow_rq.py
(query B and the transfer), dev/patch_cavity2.py (90's path counter).
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

# --- query A: 98's primary-surface query, cloned instruction for instruction -
#   0x001 OpaqueKHR | 0x004 TerminateOnFirstHitKHR | 0x200 SkipAABBsKHR
# TerminateOnFirstHit is CORRECT here and wrong for query B: A asks "what did
# the camera ray land on", and inside a +/-0.1 % bracket around |P| any
# committed hit is that surface. B asks for the NEAREST backface, so it must
# let Proceed run to completion.
FLAGS_A = 0x001 | 0x004 | 0x200                     # 517
FLAGS_A_NAMES = 'OpaqueKHR|TerminateOnFirstHitKHR|SkipAABBsKHR'
BRACKET_LO, BRACKET_HI, BRACKET_EPS = 0.999, 1.001, 1.0e-4
COMMITTED = 1
GETTER_ID = 'OpRayQueryGetIntersectionInstanceIdKHR'
GETTER_CUSTOM = 'OpRayQueryGetIntersectionInstanceCustomIndexKHR'

# The -hit paint, in units of the SUN RADIANCE (see the module docstring).
# 0.32 is 1/10 of `earglow-rq-hit`'s bare 3.2 and lands ~1.6x the glow rung's
# own peak (k 0.22 * transfer ~0.9 = 0.198 * sunRadiance), i.e. the same order
# as the thing being diagnosed rather than three orders below it.
DIAG_HIT  = tuple(v / 10.0 for v in HIT_RGB)        # (0.0, 0.04, 0.32) BLUE
DIAG_MISS = tuple(v / 10.0 for v in MISS_RGB)       # (0.32, 0.0, 0.0)  RED


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

    getter = GETTER_CUSTOM if decoy == 'custom' else GETTER_ID
    rep = {"mode": mode, "k": k, "ld_m": LD_M, "tmin": TMIN, "tmax": TMAX,
           "ray_flags_b": FLAGS, "ray_flags_b_names": FLAGS_NAMES,
           "ray_flags_a": FLAGS_A, "ray_flags_a_names": FLAGS_A_NAMES,
           "bracket": [BRACKET_LO, BRACKET_HI, BRACKET_EPS],
           "commit_a": "first", "commit_b": "closest",
           "match_getter": getter, "match_op": (
               "OpINotEqual" if decoy == 'invert' else "OpIEqual"),
           "match_gate": decoy != 'nomatch',
           "decoy": decoy, "gate_mask": GATE_MASK,
           "nee_line": nee["line"] + 1, "accel": accel,
           "origin": nee["ops"][6], "direction": nee["ops"][8],
           "backlit": nee["backlit"], "sun_radiance": sunrad,
           "path_counter": counter, "path_header": phdr,
           "primary_line": prim['line'], "primary_V": prim['V'],
           "diag_scaled_by_sun_radiance": mode in ('hit', 'hitw'),
           "diag_wrap_gated": mode == 'hitw',
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
    # The wrap edge is shared: the glow rungs feather their transfer with it and
    # -hitw feathers its flat paint with the SAME constant, which is the whole
    # point of that rung (101 sec 15). It is allocated INSIDE each branch and in
    # the branch's original order on purpose -- _fc mints ids, so hoisting it
    # renumbers every later constant and the parked earglow-rq2 bytes stop
    # reproducing. Regression-checked in build gate 2.
    fwrap = None
    if mode in ('hit', 'hitw'):
        if mode == 'hitw':
            if not soft:
                die("--mode hitw needs --wrap: it is the glow rung's envelope, "
                    "and without it the map is -rq2-hit again")
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

    # ---- entry block: TWO query objects + 3 accumulators, ONE edit --------
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rqA, rqB = mod.new_id(), mod.new_id()
    gv = [mod.new_id() for _ in range(3)]
    ind0 = '               '
    edits.append((at, [f"{ind0}{rqA} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqB} = OpVariable {ptr_rq} Function"]
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

    # ---- THE ONE NEW VARIABLE: same instance? -------------------------------
    # An InstanceId read from a non-committed query is undefined, so the
    # equality is ANDed with BOTH commits and never stands alone.
    if decoy == 'nomatch':
        # `earglow-rq` behaviour, rebuilt through this patcher: no compare at
        # all. Exists only so build_earglow_rq2.sh can show the verifier
        # rejects it. Never installed.
        same = None
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {g_all} {hitB}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {g_all} {hitB}")
    else:
        eqop = 'OpINotEqual' if decoy == 'invert' else 'OpIEqual'
        same = nid(); ins.append(f"{ind}{same} = {eqop} {boolt} {idA} {idB}")
        both = nid(); ins.append(f"{ind}{both} = OpLogicalAnd {boolt} {hitA} {hitB}")
        match = nid(); ins.append(f"{ind}{match} = OpLogicalAnd {boolt} {both} {same}")
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {g_all} {match}")
        # "B committed, but on a FOREIGN instance" -- the red of the -hit map.
        nm = nid(); ins.append(f"{ind}{nm} = OpLogicalNot {boolt} {match}")
        gB = nid(); ins.append(f"{ind}{gB} = OpLogicalAnd {boolt} {g_all} {hitB}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gB} {nm}")
    rep["match_id"] = same
    rep["ok_id"] = ok

    def emit_wrap():
        # W3's envelope, emitted identically for the glow rungs and for -hitw.
        # ONE definition, so `earglow-rq2-hitw` cannot drift from the rung it
        # is supposed to be a map of (101 sec 15).
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

    if mode in ('hit', 'hitw'):
        # Flat, no transfer, ADDITIVE, and IN UNITS OF THE SUN RADIANCE so it
        # reads on lit skin too (101 sec 12.3). B misses -> nothing painted.
        # -hitw multiplies by the SAME wrap envelope the glow rung uses, so its
        # map is the glow's paintable set and not a superset of it (101 sec 14.3).
        wfac = emit_wrap() if mode == 'hitw' else None
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
        rep['earglow_rq2'] = {"mode": "control", "k": 0.0, "emitted": 0,
                              "why": "k=0 glow: identity, no instructions"}
    else:
        consts, edits, rep['earglow_rq2'] = build(mod, k, mode, soft, decoy)
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
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit', 'hitw'))
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--decoy', choices=('nomatch', 'custom', 'invert'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow_rq2.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if (a.wide is None) != (a.wrap is None):
        ap.error('--wide and --wrap must be given together')
    soft = (a.wide, a.wrap) if a.wide is not None else None
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.mode, soft, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
