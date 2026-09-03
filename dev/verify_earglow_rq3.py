#!/usr/bin/env python3
"""verify_earglow_rq3.py <rung-dir> --base <base-dir> --mode glow|hit
                         [--k K] [--wide W] --wrap R
   verify_earglow_rq3.py --negative <base-dir>

Re-derives the earglow-rq3 splice from the SHIPPED .spv bytes -- never from the
patcher's reports, never from a byte diff (42: "a byte diff is not coverage"),
and never by importing either patcher's detectors. The generic re-derivations
this file shares with verify_earglow_rq.py (the path-loop counter, the sun-NEE
trace, constant resolution) are imported from THAT verifier, which implements
them independently of the patchers; query A's primary-ray reconstruction is
re-derived HERE, a second time, rather than imported from dev/patch_rayq.py.

Proven per patched rgs_reference_main permutation:

  1  RayQueryKHR capability + extension; ONE OpTypeRayQueryKHR; exactly THREE
     Function-storage ray query variables, all inside the entry block's
     leading OpVariable run;
  2  the module's own sun-NEE trace is re-found (flags 12 / tmax 10000 /
     OpSelect(cond,0,39) mask) and is unique;
  3  exactly THREE OpRayQueryInitializeKHR, on the three declared objects,
     sharing ONE cull mask -- OpSelect(gate, 39, 0) -- so all three are gated
     identically and a non-skin pixel pays three guaranteed misses and no
     branch. A and C both carry flags 517 and are told apart by their origins,
     not by their flags: A starts at the ZERO triple, C at a computed point;
  4  query B (the thickness query) is byte-for-byte 101 sec 2: flags 545
     (Opaque|CullFrontFacing|SkipAABBs, checked bit by bit), tmin 0.0015,
     tmax 0.018, and origin/direction/AS are the NEE trace's OWN SSA ids;
  5  query A (the primary-surface query, 98 sec 5) is 98's: flags 517
     (Opaque|TerminateOnFirstHit|SkipAABBs), origin the ZERO triple, direction
     the module's own normalized view ray, and the t bracket is
     [|P|*0.999, |P|*1.001 + 1e-4] where |P| = dot(P,P)*rsqrt(dot(P,P)) built
     from the ONE perspective-divide-then-normalize this file re-finds;
  6  the gate is (class-1 skin AND the trace's own backlit condition) AND
     (path counter == 0), with the counter re-derived by 90's throughput
     discriminator -- what rejects a build made with 79's legacy helper;
  7  exactly THREE Proceed, TWO committed InstanceId getters (A and B), ONE
     committed T getter (query B's), and ZERO of the ten other getters;
  7b THE ONE NEW VARIABLE OF rq3: query C, sun visibility from the exit point.
     Its origin is re-derived as OpFAdd(P, OpVectorTimesScalar(S, OpFAdd(t,
     PUSH))) with P and S the NEE trace's own operands and t the GUARDED
     committed t; its flags are 517 with NO culling bit; its tmin is the 1 mm
     constant; and its tmax is the module's OWN sun shadow-ray tmax operand,
     so C reaches exactly as far as the engine's own sun visibility test;
  8  THE ONE NEW VARIABLE: an OpIEqual %bool whose two operands are exactly
     the two InstanceId getter results -- not OpINotEqual (the inverted
     decoy), and not read from InstanceCustomIndex (the wrong-field decoy);
  8b the accept is the AND of the instance compare and C's MISS: an
     OpLogicalNot over C's committed-type test, reached from the paint's
     condition. `--decoy invert` (accept the occluded ones) and `--decoy noc`
     (C traced but never consulted) are rejected here;
  9  the paint is DOMINATED by that compare and by C's miss: the boolean feeding the k select
     (glow) or the blue select (hit) reaches the equality id through
     OpLogicalAnd/OpLogicalNot only, and also reaches BOTH commit tests --
     an InstanceId read from a non-committed query is undefined;
 10  the NaN guard on t (OpSelect(committedB, t, tmax)) with exactly one
     consumer of the raw t;
 11  glow: 6 Exp / 1 SmoothStep / 1 Dot added, the six 1/ld and 1/(wide*ld)
     rates resolved per channel, and the transfer consuming the GUARDED t;
     hit: no transfer at all, and each of the three flat paints multiplied by
     the module's own SUN RADIANCE component before the clamp (101 sec 12.3:
     a bare constant is invisible in this engine's radiance units);
 12  every rewritten OpImageWrite texel is OpCompositeConstruct of three
     OpFAdd(component, OpLoad(accumulator)) -- an ADD, and alpha untouched;
 13  the OpTraceRayKHR count is unchanged from the base: this rung adds
     queries, never rays.

--negative asserts the base carries none of it.
"""
import argparse, glob, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
import verify_earglow_rq2 as V2
from verify_earglow_rq import (dis, index, fval, uval, close, count,
                               path_counter, nee_trace, bad,
                               GETTERS_OTHER, LD_M, PASS_THROUGH)

FLOOR = False           # set by --floor; see the transfer check
FLAGS_B = 545
FLAGS_A = 517
BRACKET = (0.999, 1.001, 1.0e-4)
GET_ID = 'OpRayQueryGetIntersectionInstanceIdKHR'
# InstanceId is now EXPECTED, so it comes off the forbidden list; everything
# else stays forbidden, InstanceCustomIndex included -- that is the decoy.
GETTERS_FORBIDDEN = tuple(g for g in GETTERS_OTHER if g != GET_ID)


def primary_ray(lines, d, name):
    """98 / 94 sec 3.3's primary view-ray reconstruction, re-derived here.

    Shape: three OpFDiv sharing ONE denominator (the perspective divide) ->
    two OpCompositeConstruct of the same triple -> OpDot -> InverseSqrt ->
    three OpFMul(rsqrt, component). Must be UNIQUE in the module; a module
    with two would make "the primary ray" a positional guess.

    Written from the SPIR-V, not imported from dev/patch_rayq.py, so that this
    file agreeing with the patcher is evidence rather than tautology.
    """
    found = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ InverseSqrt (%\w+)\s*$', l)
        if not m:
            continue
        rsq, dot = m.groups()
        dm = re.match(r'OpDot %float (%\w+) (%\w+)$', d.get(dot, (0, ''))[1])
        if not dm:
            continue
        ca = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(dm.group(1), (0, ''))[1])
        cb = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(dm.group(2), (0, ''))[1])
        if not ca or not cb or ca.groups() != cb.groups():
            continue
        P = list(ca.groups())
        divs = [re.match(r'OpFDiv %float (%\w+) (%\w+)$', d.get(p, (0, ''))[1])
                for p in P]
        if not all(divs) or len({x.group(2) for x in divs}) != 1:
            continue
        V3 = []
        for comp in P:
            hit = None
            for j in range(i + 1, min(i + 16, len(lines))):
                mm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', lines[j])
                if mm and {mm.group(2), mm.group(3)} == {rsq, comp}:
                    hit = mm.group(1)
                    break
            V3.append(hit)
        if any(v is None for v in V3):
            continue
        found.append({'dot': dot, 'rsqrt': rsq, 'V': V3})
    if len(found) != 1:
        bad(name, f"{len(found)} primary-ray reconstructions (perspective "
                  f"divide -> normalize), want exactly 1")
        return None
    return found[0]


def reaches(d, start, target, ops=('OpLogicalAnd', 'OpLogicalNot'), depth=12):
    """Is `target` in the transitive boolean closure of `start`, following only
    OpLogicalAnd / OpLogicalNot? Used to prove the paint is DOMINATED by the
    instance compare -- a select that merely exists somewhere in the module
    proves nothing about what actually gates the radiance."""
    seen, stack = set(), [(start, 0)]
    while stack:
        cur, k = stack.pop()
        if cur == target:
            return True
        if cur in seen or k > depth:
            continue
        seen.add(cur)
        body = d.get(cur, (0, ''))[1]
        m = re.match(r'(Op\w+) %bool (.+)$', body)
        if not m or m.group(1) not in ops:
            continue
        for a in m.group(2).split():
            stack.append((a, k + 1))
    return False


def check_module(path, base_path, mode, k, wide, wrap):
    name = os.path.basename(path)
    lines = dis(path)
    d = index(lines)
    base = dis(base_path)

    # ---- 1. capability, extension, TWO query objects ----------------------
    if not any(re.match(r'\s*OpCapability RayQueryKHR\s*$', l) for l in lines):
        return bad(name, "no OpCapability RayQueryKHR")
    if not any('OpExtension "SPV_KHR_ray_query"' in l for l in lines):
        bad(name, 'no OpExtension "SPV_KHR_ray_query"')
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in lines):
        bad(name, "SkipAABBsKHR (0x200) used without "
                  "RayTraversalPrimitiveCullingKHR")
    rqts = [m.group(1) for l in lines
            for m in [re.match(r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$', l)] if m]
    if len(rqts) != 1:
        return bad(name, f"{len(rqts)} OpTypeRayQueryKHR, want 1")
    ptrs = [m.group(1) for l in lines
            for m in [re.match(r'\s*(%\w+)\s*=\s*OpTypePointer Function '
                               + re.escape(rqts[0]) + r'\s*$', l)] if m]
    if len(ptrs) != 1:
        return bad(name, f"{len(ptrs)} Function pointers to the query type, want 1")
    rqv = [m.group(1) for l in lines
           for m in [re.match(r'\s*(%\w+)\s*=\s*OpVariable '
                              + re.escape(ptrs[0]) + r' Function\s*$', l)] if m]
    if len(rqv) != 3:
        return bad(name, f"{len(rqv)} ray query variables, want exactly 3 "
                         f"(A = primary surface, B = sunward thickness, "
                         f"C = sun visibility from the exit point)")
    for v in rqv:
        j = d[v][0] - 1
        while j >= 0 and re.match(r'\s*%\w+ = OpVariable .* Function\s*$', lines[j]):
            j -= 1
        if not re.match(r'\s*%\w+ = OpLabel\s*$', lines[j]):
            bad(name, f"ray query variable {v} is not in the entry block's "
                      f"leading OpVariable run")

    # ---- 2. the module's own sun-NEE trace --------------------------------
    nee, backlit = nee_trace(lines, d, name)
    if nee is None:
        return

    # ---- 3. exactly two queries, one shared gate --------------------------
    inits = [re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l).group(1).split()
             for l in lines if re.match(r'\s*OpRayQueryInitializeKHR\s', l)]
    if len(inits) != 3:
        return bad(name, f"{len(inits)} OpRayQueryInitializeKHR, want exactly 3")
    for q in inits:
        if len(q) != 8:
            return bad(name, f"OpRayQueryInitializeKHR has {len(q)} operands, want 8")
    byflags = {}
    for q in inits:
        byflags.setdefault(uval(d, q[2]), []).append(q)
    if sorted(byflags) != [FLAGS_A, FLAGS_B] or len(byflags[FLAGS_A]) != 2 \
            or len(byflags[FLAGS_B]) != 1:
        return bad(name, f"query flag words are "
                         f"{ {k: len(v) for k, v in byflags.items()} }, want two "
                         f"{FLAGS_A} (A and C) and one {FLAGS_B} (B)")
    qB = byflags[FLAGS_B][0]
    # A and C share flags, so tell them apart by ORIGIN, not by flags: A starts
    # at the camera (the zero triple), C at a computed exit point.
    zeros = [q for q in byflags[FLAGS_A]
             if re.match(r'OpConstantComposite %v3float', d.get(q[4], (0, ''))[1])
             and all(fval(d, x) == 0.0 for x in
                     d.get(q[4], (0, ''))[1].split()[2:5])]
    if len(zeros) != 1:
        return bad(name, f"{len(zeros)} of the two 517 queries start at the "
                         f"zero triple, want exactly 1 (query A)")
    qA = zeros[0]
    qC = [q for q in byflags[FLAGS_A] if q is not qA][0]
    if {qA[0], qB[0], qC[0]} != set(rqv):
        bad(name, "the three queries do not run on the three declared objects")
    if not (qA[3] == qB[3] == qC[3]):
        bad(name, f"the three queries use different cull masks ({qA[3]}, "
                  f"{qB[3]}, {qC[3]}) -- they must share ONE gate")
    if qA[1] != nee[0] or qB[1] != nee[0] or qC[1] != nee[0]:
        bad(name, "a query uses an acceleration structure that is not the "
                  "sun-NEE trace's own")

    # ---- 4. query B: 101 sec 2, unchanged ---------------------------------
    fl = uval(d, qB[2])
    if fl & 0x20 == 0:
        bad(name, f"query B flags {fl}: CullFrontFacingTrianglesKHR (0x20) NOT set")
    if fl & 0x10:
        bad(name, f"query B flags {fl}: CullBackFacingTrianglesKHR (0x10) set "
                  f"-- that is v4's reversed segment, not 70 W1")
    if fl & 0x04:
        bad(name, f"query B flags {fl}: TerminateOnFirstHitKHR (0x04) set -- "
                  f"the committed hit must be the CLOSEST backface")
    if fl & 0x01 == 0 or fl & 0x200 == 0:
        bad(name, f"query B flags {fl}: Opaque and SkipAABBs are what make ONE "
                  f"Proceed sufficient")
    if qB[4] != nee[6]:
        bad(name, f"query B origin {qB[4]} is not the sun-NEE trace's own "
                  f"{nee[6]} (98 sec 15: no world offset belongs here)")
    if qB[6] != nee[8]:
        bad(name, f"query B direction {qB[6]} is not the trace's own S ({nee[8]})")
    if not close(fval(d, qB[5]), 0.0015):
        bad(name, f"query B tmin resolves to {fval(d, qB[5])}, want 0.0015")
    if not close(fval(d, qB[7]), 0.018):
        bad(name, f"query B tmax resolves to {fval(d, qB[7])}, want 0.018")

    # ---- 5. query A: 98's primary-surface query ---------------------------
    fa = uval(d, qA[2])
    if fa & 0x04 == 0:
        bad(name, f"query A flags {fa}: TerminateOnFirstHitKHR (0x04) NOT set "
                  f"-- inside a +/-0.1% bracket any committed hit IS the "
                  f"primary surface, and terminating is the cheap answer")
    if fa & 0x30:
        bad(name, f"query A flags {fa}: a face-culling bit is set -- query A "
                  f"must see the surface the camera ray landed on, whatever "
                  f"its winding")
    prim = primary_ray(lines, d, name)
    if prim is not None:
        zm = re.match(r'OpConstantComposite %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(qA[4], (0, ''))[1])
        if not zm or not all(fval(d, x) == 0.0 for x in zm.groups()):
            bad(name, f"query A origin {qA[4]} is not the zero triple -- the "
                      f"camera is at the origin of P's space (94 sec 3.3)")
        dm = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(qA[6], (0, ''))[1])
        if not dm or list(dm.groups()) != prim['V']:
            bad(name, f"query A direction {qA[6]} is not the module's own "
                      f"normalized view ray {prim['V']}")
        tm = None
        for l in lines:
            m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
            if m and {m.group(2), m.group(3)} == {prim['dot'], prim['rsqrt']}:
                tm = m.group(1)
        if tm is None:
            bad(name, "|P| = dot(P,P) * rsqrt(dot(P,P)) is not computed")
        else:
            lo = re.match(r'OpFMul %float (%\w+) (%\w+)$', d.get(qA[5], (0, ''))[1])
            if not lo or tm not in lo.groups() or not any(
                    close(fval(d, x), BRACKET[0]) for x in lo.groups()):
                bad(name, f"query A tmin {qA[5]} is not |P| * {BRACKET[0]}")
            ad = re.match(r'OpFAdd %float (%\w+) (%\w+)$', d.get(qA[7], (0, ''))[1])
            if not ad:
                bad(name, f"query A tmax {qA[7]} is not an OpFAdd (|P|*"
                          f"{BRACKET[1]} + {BRACKET[2]})")
            else:
                eps = [x for x in ad.groups() if close(fval(d, x), BRACKET[2], 1e-3)]
                hi = [x for x in ad.groups()
                      if re.match(r'OpFMul %float ', d.get(x, (0, ''))[1])]
                if not eps or not hi:
                    bad(name, f"query A tmax is not |P|*{BRACKET[1]} + {BRACKET[2]}")
                else:
                    hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', d[hi[0]][1])
                    if tm not in hm.groups() or not any(
                            close(fval(d, x), BRACKET[1]) for x in hm.groups()):
                        bad(name, f"query A tmax upper term is not |P| * {BRACKET[1]}")

    # ---- 6. the gate, operand by operand (101 sec 2) ----------------------
    ms = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', d.get(qB[3], (0, ''))[1])
    if not ms:
        return bad(name, f"cull mask {qB[3]} is not an OpSelect %uint")
    gate, on, off = ms.groups()
    if uval(d, on) != 39 or uval(d, off) != 0:
        bad(name, f"cull mask select arms are ({uval(d, on)}, {uval(d, off)}), "
                  f"want (39, 0)")
    ga = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(gate, (0, ''))[1])
    if not ga:
        return bad(name, f"gate {gate} is not an OpLogicalAnd")
    g_a1, g_p0 = ga.groups()
    pc_want = path_counter(lines, d, name)
    pm = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(g_p0, (0, ''))[1])
    if not pm:
        bad(name, f"the third gate term {g_p0} is not an OpIEqual")
    else:
        ctr, zero = pm.groups()
        if uval(d, zero) != 0:
            bad(name, f"path-counter compare is against {uval(d, zero)}, want 0")
        if pc_want is not None and ctr != pc_want:
            bad(name, f"the gate tests {ctr}, but the PATH loop's counter is "
                      f"{pc_want} (90 sec 1)")
    ga2 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(g_a1, (0, ''))[1])
    if not ga2:
        return bad(name, f"the skin/backlit term {g_a1} is not an OpLogicalAnd")
    g_skin, g_bl = ga2.groups()
    if g_bl != backlit:
        bad(name, f"the backlit operand is {g_bl}, not the trace's own {backlit}")
    sm = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(g_skin, (0, ''))[1])
    if not sm:
        bad(name, f"the class term {g_skin} is not an OpIEqual")
    else:
        andid, cls = sm.groups()
        if uval(d, cls) != 32:
            bad(name, f"class compare is against {uval(d, cls)}, want 32 (skin)")
        am = re.match(r'OpBitwiseAnd %uint (%\w+) (%\w+)$', d.get(andid, (0, ''))[1])
        if not am or uval(d, am.group(2)) != 0xFFFFFFE0:
            bad(name, "the class word is not `fetch.y & 0xFFFFFFE0`")

    # ---- 7. three Proceeds, two InstanceIds, one T, nothing else ---------
    npro = count(lines, 'OpRayQueryProceedKHR')
    if npro != 3:
        bad(name, f"{npro} x OpRayQueryProceedKHR, want exactly 3 (one per "
                  f"query; more means a traversal LOOP was spliced in)")
    ity = [m.group(1) for l in lines for m in
           [re.match(r'\s*(%\w+)\s*=\s*OpRayQueryGetIntersectionTypeKHR %uint '
                     r'(%\w+) (%\w+)\s*$', l)] if m and uval(d, m.group(3)) == 1]
    if len(ity) != 3:
        bad(name, f"{len(ity)} committed GetIntersectionTypeKHR, want 3")
    ids = [(m.group(1), m.group(2)) for l in lines for m in
           [re.match(r'\s*(%\w+)\s*=\s*' + GET_ID + r' %uint (%\w+) (%\w+)\s*$', l)]
           if m and uval(d, m.group(3)) == 1]
    if len(ids) != 2:
        bad(name, f"{len(ids)} committed {GET_ID}, want exactly 2 -- the "
                  f"instance match needs one per query and nothing else")
    elif {q for _, q in ids} != {qA[0], qB[0]}:
        bad(name, "the two InstanceId reads are not one on query A and one on "
                  "query B (query C's identity is irrelevant: it answers only "
                  "'is ANYTHING in the way')")
    tg = [m.group(1) for l in lines for m in
          [re.match(r'\s*(%\w+)\s*=\s*OpRayQueryGetIntersectionTKHR %float '
                    r'(%\w+) (%\w+)\s*$', l)] if m and uval(d, m.group(3)) == 1]
    if len(tg) != 1:
        bad(name, f"{len(tg)} committed OpRayQueryGetIntersectionTKHR, want 1")
    elif len(inits) == 3 and tg and qB[0] != \
            re.match(r'\s*%\w+\s*=\s*OpRayQueryGetIntersectionTKHR %float (%\w+)',
                     lines[d[tg[0]][0]]).group(1):
        bad(name, "the T getter reads query A, not the thickness query B")
    for g in GETTERS_FORBIDDEN:
        n = count(lines, g)
        if n:
            bad(name, f"{n} x {g} -- this rung reads InstanceId and t, nothing "
                      f"else (InstanceCustomIndex is the wrong-field decoy)")

    # ---- 8. the instance compare (101 sec 12, unchanged) -----------------
    same = None
    if len(ids) == 2:
        a, b = ids[0][0], ids[1][0]
        eqs = [m.group(1) for l in lines for m in
               [re.match(r'\s*(%\w+)\s*=\s*OpIEqual %bool (%\w+) (%\w+)\s*$', l)]
               if m and {m.group(2), m.group(3)} == {a, b}]
        neq = [m.group(1) for l in lines for m in
               [re.match(r'\s*(%\w+)\s*=\s*OpINotEqual %bool (%\w+) (%\w+)\s*$', l)]
               if m and {m.group(2), m.group(3)} == {a, b}]
        if neq:
            bad(name, "the two InstanceIds are compared with OpINotEqual -- "
                      "the gate is INVERTED (it would accept exactly the "
                      "foreign meshes it exists to reject)")
        if len(eqs) != 1:
            bad(name, f"{len(eqs)} OpIEqual over the two committed InstanceIds, "
                      f"want exactly 1 -- without it this is `earglow-rq`")
        else:
            same = eqs[0]

    # ---- 9. the guard, and 10/11 the paint --------------------------------
    tu = None
    hitb = {}
    for t in ity:
        h = [m.group(1) for l in lines for m in
             [re.match(r'\s*(%\w+)\s*=\s*OpINotEqual %bool ' + re.escape(t)
                       + r' (%\w+)\s*$', l)] if m and uval(d, m.group(2)) == 0]
        if len(h) == 1:
            hitb[t] = h[0]
    if len(hitb) != 3:
        bad(name, f"{len(hitb)} committed-vs-0 tests, want one per query")
    if len(tg) == 1:
        sel = [m.group(1) for l in lines for m in
               [re.match(r'\s*(%\w+)\s*=\s*OpSelect %float (%\w+) '
                         + re.escape(tg[0]) + r' (%\w+)\s*$', l)]
               if m and close(fval(d, m.group(3)), 0.018)]
        if len(sel) != 1:
            bad(name, "t is not guarded: want exactly one "
                      "OpSelect(committedB, t, tmax) before any arithmetic")
        else:
            tu = sel[0]
        tref = re.compile(r'(?<!\w)' + re.escape(tg[0]) + r'(?!\w)')
        users = [l for l in lines if tref.search(l)
                 and not l.strip().startswith(tg[0] + ' =')]
        if len(users) != 1:
            bad(name, f"the raw t has {len(users)} consumers, want exactly 1")

    # ---- 7b. QUERY C: sun visibility from the exit point (101 sec 15.5) ---
    # C is the one new variable of rq3. Everything about it is re-derived from
    # the shipped bytes and checked against the module's OWN sun shadow ray.
    flC = uval(d, qC[2])
    if flC != FLAGS_A:
        bad(name, f"query C flags {flC}, want {FLAGS_A} "
                  f"(Opaque|TerminateOnFirstHit|SkipAABBs)")
    if flC & 0x30:
        bad(name, f"query C flags {flC}: a CULL bit is set -- C asks whether "
                  f"ANYTHING occludes the sun, and winding is irrelevant to that")
    tminC = fval(d, qC[5])
    if tminC is None or not close(tminC, 0.001):
        bad(name, f"query C tmin is {tminC}, want the 1 mm slack constant")
    if qC[7] != nee[9]:
        bad(name, f"query C tmax {qC[7]} is not the module's OWN sun shadow-ray "
                  f"tmax {nee[9]} -- C must reach as far as the engine's own "
                  f"sun visibility test")
    if qC[6] != nee[8]:
        bad(name, f"query C direction {qC[6]} is not the sun-NEE trace's own "
                  f"{nee[8]}")
    # origin = OpFAdd(P, OpVectorTimesScalar(S, OpFAdd(t_guarded, PUSH)))
    om = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', d.get(qC[4], (0, ''))[1])
    if not om:
        bad(name, f"query C origin {qC[4]} is not an OpFAdd %v3float -- it must "
                  f"be P + (t + push)*S")
    else:
        base_p = [x for x in om.groups() if x == nee[6]]
        scaled = [x for x in om.groups() if x != nee[6]]
        if not base_p:
            bad(name, f"query C origin does not add to the NEE trace's own P "
                      f"({nee[6]})")
        vm = re.match(r'OpVectorTimesScalar %v3float (%\w+) (%\w+)$',
                      d.get(scaled[0], (0, ''))[1]) if scaled else None
        if not vm:
            bad(name, "query C's origin offset is not OpVectorTimesScalar(S, t)")
        else:
            if vm.group(1) != nee[8]:
                bad(name, f"query C's origin is offset along {vm.group(1)}, not "
                          f"the sun direction {nee[8]}")
            pm2 = re.match(r'OpFAdd %float (%\w+) (%\w+)$',
                           d.get(vm.group(2), (0, ''))[1])
            if not pm2:
                bad(name, "query C's offset distance is not OpFAdd(t, push)")
            else:
                if tu is not None and tu not in pm2.groups():
                    bad(name, f"query C's offset uses {pm2.groups()}, not the "
                              f"GUARDED committed t {tu}")
                pushv = [fval(d, x) for x in pm2.groups()
                         if fval(d, x) is not None]
                if not pushv or not close(pushv[0], 0.001):
                    bad(name, f"query C's push past the backface is {pushv}, "
                              f"want 1 mm -- without it C's first hit is the "
                              f"wall it just left")

    # ---- 8b. the accept is (same instance) AND (C MISSED) -----------------
    tyq = {}
    for l in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpRayQueryGetIntersectionTypeKHR %uint '
                     r'(%\w+) (%\w+)\s*$', l)
        if m and uval(d, m.group(3)) == 1:
            tyq[m.group(1)] = m.group(2)
    tyC = [t for t, q in tyq.items() if q == qC[0]]
    visC = hitC = None
    if len(tyC) != 1:
        bad(name, f"{len(tyC)} committed type reads on query C, want 1")
    elif tyC[0] not in hitb:
        bad(name, "query C's committed type is never compared against 0")
    else:
        hitC = hitb[tyC[0]]
        nots = [m.group(1) for l in lines for m in
                [re.match(r'\s*(%\w+)\s*=\s*OpLogicalNot %bool '
                          + re.escape(hitC) + r'\s*$', l)] if m]
        if len(nots) < 1:
            bad(name, "query C's commit test is never NEGATED -- rq3 accepts a "
                      "MISS (the exit point sees the sun); accepting the hit is "
                      "the `invert` decoy and is exactly backwards")
        else:
            visC = nots[0]

    if count(lines, 'OpTraceRayKHR') != count(base, 'OpTraceRayKHR'):
        bad(name, "OpTraceRayKHR count differs from the base -- this rung adds "
                  "QUERIES, never rays")

    n_exp = count(lines, 'Exp ') - count(base, 'Exp ')
    n_ss = count(lines, 'SmoothStep ') - count(base, 'SmoothStep ')
    n_dot = count(lines, 'OpDot %float ') - count(base, 'OpDot %float ')
    fl_all = {t: fval(d, t) for t in d if fval(d, t) is not None}
    okid = None
    if mode == 'glow':
        want_exp = 6 if wide else 3
        if n_exp != want_exp:
            bad(name, f"{n_exp} added Exp, want {want_exp}")
        if n_ss != (1 if wrap else 0):
            bad(name, f"{n_ss} added SmoothStep, want {1 if wrap else 0}")
        if n_dot != (1 if wrap else 0):
            bad(name, f"{n_dot} added OpDot, want {1 if wrap else 0}")
        for c, ld in enumerate(LD_M):
            if not any(close(v, 1.0 / ld, 1e-4) for v in fl_all.values()):
                bad(name, f"no constant resolving to 1/ld (channel {c})")
            if wide and not any(close(v, 1.0 / (wide * ld), 1e-4)
                                for v in fl_all.values()):
                bad(name, f"no constant resolving to 1/({wide}*ld) (channel {c})")
        if wrap and not any(close(v, wrap) for v in fl_all.values()):
            bad(name, f"no constant resolving to the wrap edge {wrap}")
        ksel = [m for l in lines for m in
                [re.match(r'\s*(%\w+)\s*=\s*OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)]
                if m and close(fval(d, m.group(3)), k) and fval(d, m.group(4)) == 0.0]
        if len(ksel) != 1:
            bad(name, f"{len(ksel)} OpSelect(_, {k}, 0.0) k-selects, want 1")
        else:
            okid = ksel[0].group(2)
        if tu is not None:
            # --floor: 101 sec 18's thickness floor puts exactly ONE
            # OpExtInst NMax between the guarded t and the transfer, so the
            # FMuls read t_eff instead of t. The hop is allowed only when it
            # is ASKED for, and only through that one opcode on that one
            # value -- everything else about this check is unchanged, and
            # verify_earglow_cap.py is what proves the floor itself. Without
            # the flag the strict form stands, which is why an uncapped rung
            # cannot be verified as capped or the reverse.
            src = tu
            if FLOOR:
                hop = [m for l in lines for m in
                       [re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ NMax '
                                 + re.escape(tu) + r' %\w+\s*$', l)] if m]
                if len(hop) != 1:
                    bad(name, f"--floor: {len(hop)} NMax on the guarded t, want 1")
                else:
                    src = hop[0].group(1)
            n = sum(1 for l in lines
                    if re.match(r'\s*%\w+\s*=\s*OpFMul %float ' + re.escape(src)
                                + r' %\w+\s*$', l))
            if n != want_exp:
                bad(name, f"{n} FMuls consume the "
                          f"{'floored' if FLOOR else 'guarded'} t, "
                          f"want {want_exp}")
    else:
        # rq3 has ONE diagnostic mode and it always carries the wrap: the
        # flat paint is multiplied by the glow rung's own wrap envelope first.
        want_ss = 1   # rq3's -hit ALWAYS carries the glow's wrap (101 sec 14.3)
        if n_exp or n_ss != want_ss or n_dot != want_ss:
            bad(name, f"--mode {mode} wants 0 Exp / {want_ss} SmoothStep / "
                      f"{want_ss} OpDot, got {n_exp} / {n_ss} / {n_dot}")
        if True:
            # Read the edge off the ADDED SmoothStep's own operand. Checking
            # only that a constant equal to `wrap` exists somewhere is vacuous:
            # 0.5 (the -hi edge) is already in every shipped module.
            if not wrap:
                bad(name, "--mode hit needs --wrap to check against")
            else:
                edges = [m.group(2) for l in lines for m in
                         [re.match(r'\s*%\w+\s*=\s*OpExtInst %float %\w+ '
                                   r'SmoothStep (%\w+) (%\w+) (%\w+)\s*$', l)]
                         if m and m.group(1) in d and fval(d, m.group(1)) == 0.0]
                got = [fval(d, e) for e in edges]
                if not any(v is not None and close(v, wrap) for v in got):
                    bad(name, f"the added SmoothStep's edge is {got}, not the "
                              f"glow rung's wrap {wrap} -- the diagnostic "
                              f"must use the GLOW rung's envelope")
        for v in (0.32, 0.04):
            if not any(close(x, v) for x in fl_all.values()):
                bad(name, f"the flat diagnostic constant {v} is absent -- the "
                          f"-hit paint is DIAG_RGB * sunRadiance (101 sec 12.3)")
        if any(close(x, 3.2) for x in fl_all.values()):
            bad(name, "a bare 3.2 is present: that is `earglow-rq-hit`'s "
                      "unscaled paint, which 101 sec 12.3 measured as invisible")
        sels = [m for l in lines for m in
                [re.match(r'\s*(%\w+)\s*=\s*OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)]
                if m]
        # the BLUE accept path is the only select whose true arm is 0.04 (the
        # G channel of DIAG_HIT); 0.32 appears twice (blue's B, red's R) and
        # would not identify it.
        acc = [m for m in sels if close(fval(d, m.group(3)), 0.04)]
        red = [m for m in sels if close(fval(d, m.group(3)), 0.32)]
        if len(acc) != 1:
            bad(name, f"{len(acc)} OpSelect(_, 0.04, _), want exactly 1 (the "
                      f"blue accept path's G channel)")
        else:
            okid = acc[0].group(2)
        if len(red) != 2:
            bad(name, f"{len(red)} flat 0.32 selects, want 2 (blue B, red R)")
        # every flat paint must be scaled by a SUN RADIANCE component before
        # the clamp: 101 sec 12.3 measured that a bare constant is invisible
        # in this engine's radiance units. Shape, re-derived here:
        # OpCompositeExtract %float (OpLoad %v4float ..) c, c = 0,1,2 of ONE
        # load -- not a constant, and not three unrelated values.
        # The diagnostic inserts one multiply (by the wrap) between the select
        # and the radiance scale, so walk FMul products up to that depth. The
        # wrap ids are collected so the next check can prove all three paints
        # went through the same SmoothStep.
        ssid = [re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ SmoothStep ', l)
                for l in lines]
        ssid = {m.group(1) for m in ssid if m} - {
            m.group(1) for m in
            [re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ SmoothStep ', l)
             for l in base] if m}
        scaled, wrapped = {}, set()

        def _fmul_from(src):
            out = []
            for l in lines:
                fm = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$', l)
                if fm and fm.group(2) == src:
                    out.append((fm.group(1), fm.group(3)))
            return out

        for m in sels:
            cur = m.group(1)
            if True:
                # step 1 MUST be the wrap. Following anything else here is how
                # an unrelated `.w` extract two multiplies downstream got
                # mistaken for the radiance scale.
                nxt = [(r, o) for r, o in _fmul_from(cur) if o in ssid]
                if not nxt:
                    continue
                wrapped.add(cur)
                cur = nxt[0][0]
            for _, other in _fmul_from(cur):
                ex = re.match(r'OpCompositeExtract %float (%\w+) (\d)$',
                              d.get(other, (0, ''))[1])
                if ex and re.match(r'OpLoad %v4float ', d.get(ex.group(1), (0, ''))[1]):
                    scaled.setdefault(ex.group(1), set()).add(int(ex.group(2)))
        if len(wrapped) != 3:
            bad(name, f"{len(wrapped)} of the 3 flat paints are multiplied by "
                      f"the added SmoothStep -- the diagnostic must map "
                      f"the GLOW's paintable set (101 sec 14.3)")
        if len(scaled) != 1 or list(scaled.values())[0] != {0, 1, 2}:
            bad(name, f"the flat paint is not scaled by the three components "
                      f"of ONE sun-radiance load (got {scaled}) -- an unscaled "
                      f"diagnostic cannot be read on lit skin (101 sec 12.3)")
        nmin_now = sum(1 for l in lines
                       if re.match(r'\s*%\w+\s*=\s*OpExtInst %float %\w+ NMin ', l))
        nmin_base = sum(1 for l in base
                        if re.match(r'\s*%\w+\s*=\s*OpExtInst %float %\w+ NMin ', l))
        if nmin_now - nmin_base != 3:
            bad(name, f"{nmin_now - nmin_base} added NMin clamps, want 3 "
                      f"(one per channel)")

    # ---- 9b. the paint is DOMINATED by the instance compare ---------------
    if okid is not None and same is not None:
        if not reaches(d, okid, same):
            bad(name, f"the paint's condition {okid} does not reach the "
                      f"instance compare {same} through OpLogicalAnd/Not -- "
                      f"the match gate is present but does not gate anything")
        for t, h in hitb.items():
            if not reaches(d, okid, h):
                bad(name, f"the paint's condition {okid} does not reach the "
                          f"commit test {h} -- an InstanceId read from a "
                          f"non-committed query is UNDEFINED")
        if not reaches(d, okid, gate):
            bad(name, f"the paint's condition {okid} does not reach the "
                      f"skin/backlit/path gate {gate}")
    if okid is not None and visC is not None:
        # rq3's whole claim. `--decoy noc` traces C and never consults it; this
        # is the check that fails it.
        if not reaches(d, okid, visC):
            bad(name, f"the paint's condition {okid} does not reach query C's "
                      f"MISS {visC} -- the exit point's sunlight is never "
                      f"tested, which is `earglow-rq2` (101 sec 15.4)")
        if hitC is not None and reaches(d, okid, hitC,
                                        ops=('OpLogicalAnd',)):
            bad(name, f"the paint's condition {okid} reaches query C's HIT "
                      f"{hitC} through OpLogicalAnd only -- the accept is "
                      f"INVERTED (it would light exactly the occluded pixels)")

    # ---- 12. the writes are ADDS -----------------------------------------
    nw = 0
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        cc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)$',
                      d.get(m.group(3), (0, ''))[1])
        if not cc:
            continue
        adds = 0
        for ch in range(3):
            am = re.match(r'OpFAdd %float (%\w+) (%\w+)$',
                          d.get(cc.group(ch + 1), (0, ''))[1])
            if am and any(re.match(r'OpLoad %float %\w+$', d.get(x, (0, ''))[1])
                          for x in am.groups()):
                adds += 1
        if adds == 3:
            nw += 1
        elif adds:
            bad(name, f"a rewritten write at line {i+1} adds only {adds} of 3 "
                      f"channels")
    if nw == 0:
        bad(name, "no radiance write carries the accumulated term")
    return nw


def negative(base_dir):
    n = 0
    for p in sorted(glob.glob(os.path.join(base_dir, '*.rgs_reference_main.spv'))):
        lines = dis(p)
        for needle in ('OpRayQueryInitializeKHR', 'OpCapability RayQueryKHR',
                       GET_ID):
            if any(needle in l for l in lines):
                bad(os.path.basename(p), f"the BASE already carries {needle}")
        n += 1
    print(f"negative control: {n} base reference modules carry no ray query")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--negative')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--k', type=float, default=0.22)
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--floor', action='store_true',
                    help="allow ONE OpExtInst NMax between the guarded t and "
                         "the transfer (101 sec 18's thickness floor). The "
                         "floor's own value is NOT checked here -- that is "
                         "verify_earglow_cap.py's job.")
    a = ap.parse_args()
    globals()['FLOOR'] = a.floor
    if a.negative:
        negative(a.negative)
    else:
        if not a.rung or not a.base:
            ap.error('need <rung-dir> --base <base-dir>')
        n = tot = 0
        for p in sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv'))):
            ident = os.path.basename(p).split('.')[0]
            if ident in PASS_THROUGH:
                continue
            b = os.path.join(a.base, os.path.basename(p))
            if not os.path.exists(b):
                bad(os.path.basename(p), "no base counterpart")
                continue
            r = check_module(p, b, a.mode, a.k, a.wide, a.wrap)
            n += 1
            tot += r or 0
        print(f"verify_earglow_rq3: {n} permutations, {tot} painted writes, "
              f"mode={a.mode}, A=517 B=545, match=InstanceId")
    if V.FAIL:
        for f in V.FAIL:
            print("  FAIL " + f)
        raise SystemExit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
