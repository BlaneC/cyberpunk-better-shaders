#!/usr/bin/env python3
"""verify_thinglow.py <rung-dir> --base <base-dir> --mode glow|hit
                      [--k K] [--ld LD]
   verify_thinglow.py --negative <base-dir>
   verify_thinglow.py --control <ctl-dir> --base <base-dir>

Re-derives the THIN-TRANSLUCENCY splice (handoff/105) from the SHIPPED .spv
bytes.  Never from patch_thinglow.py's report, never from a byte diff
(GOTCHAS 42: "a byte diff is not coverage"), and never by importing the
patcher's detectors -- the generic re-derivations (path counter, sun-NEE
trace, constant resolution, the primary-ray reconstruction) are imported from
verify_earglow_rq.py / verify_earglow_rq3.py, which wrote them independently
of every patcher, and everything specific to 105 is re-derived here.

WHY THIS FILE EXISTS AT ALL.  verify_earglow_rq3.py cannot be run on a
thinglow rung: its check 1 demands EXACTLY THREE ray query variables and a
stacked rung has six.  That verifier must not be edited (it is 101's shipped
gate), so the "the ear glow survived" obligation is discharged here instead,
by check 14 -- which is strictly stronger than re-running 101's file would
have been, because it proves the ear glow's own term still reaches the pixel
THROUGH this rung's adds.

Proven per patched rgs_reference_main permutation:

  1  RayQueryKHR capability + extension; ONE OpTypeRayQueryKHR; exactly SIX
     Function-storage ray query variables (101's three + this rung's three),
     all inside the entry block's leading OpVariable run, plus THREE new
     Function %float accumulators, each initialised to NEGATIVE zero;
  2  the module's own sun-NEE trace is re-found (flags 12 / tmax 10000 /
     OpSelect(cond,0,39) mask) and is unique;
  3  exactly SIX OpRayQueryInitializeKHR on the six declared objects.  The
     two triples are told apart by query B's t range -- 101 traces
     [0.0015, 0.018], this rung [0.0003, 0.025) -- never by position;
  4  this rung's three Initialize share ONE cull mask, OpSelect(gate, 39, 0),
     which is NOT 101's: a shut gate costs three guaranteed misses and adds
     no control flow at all;
  5  query B: flags 545 (Opaque|CullFrontFacingTriangles|SkipAABBs, checked
     bit by bit), tmin 0.0003 (0.3 mm), tmax 0.025 (25 mm), and origin /
     direction / acceleration structure are the NEE trace's OWN SSA ids;
  6  query A: flags 517 (Opaque|TerminateOnFirstHit|SkipAABBs), origin the
     ZERO triple, direction the module's own normalized view ray, t bracket
     [|P|*0.999, |P|*1.001 + 1e-4];
  7  query C: flags 517, origin OpFAdd(P, OpVectorTimesScalar(S, t+1mm)) on
     the GUARDED t, tmin 0.001, and tmax the module's OWN sun shadow-ray
     tmax operand, so C reaches exactly as far as the engine's own sun
     visibility test;
  8  the SEVEN-term gate, every term re-derived: class != 1 (skin, so the ear
     glow keeps it), class != 4 (hair), class != 8 (vacuous, see 105 sec 4.3),
     metallic < 0.1, roughness > 0.5, the trace's own backlit condition, and
     path counter == 0.  All seven reach the cull mask's condition through
     OpLogicalAnd only;
  9  getter census: SIX Proceed, FOUR committed InstanceId, TWO committed T,
     SIX committed Type, and ZERO of the ten other getters;
 10  the instance match is OpIEqual over THIS rung's two InstanceId results
     (not OpINotEqual, not InstanceCustomIndex), the accept ANDs it with
     OpLogicalNot over C's committed test, and the paint is DOMINATED by
     both -- an InstanceId or a T read from a non-committed query is
     undefined;
 11  the NaN guard OpSelect(committedB, t, tmax) with exactly one consumer of
     the raw t;
 12  glow: exactly ONE added Exp, at rate 1/ld; three albedo squares; the k
     select's false arm is NEGATIVE zero (105 sec 7: +0.0 does not preserve
     the sign of a -0.0 accumulator); an NMin clamp at 100; and the transfer
     consumes the GUARDED t.
     hit: NO Exp and no albedo at all, the ramp is NClamp((t-tmin)*span,0,1),
     and each of the three paints is multiplied by the sun radiance (101
     sec 12.3: a diagnostic fixed in absolute radiance is unreadable);
 13  every painted radiance write is an ADD of the three accumulators, with
     the alpha channel passed through untouched;
 14  EAR GLOW INTACT.  (a) all eight of 101/102's own constants survive;
     (b) the added-query delta is exactly 3/3/2/1 -> 6/6/4/2; (c) at every
     painted write the value this rung adds to is ITSELF an
     OpFAdd(x, OpLoad(E)) on one of three distinct earglow accumulators, so
     101's term is still in the pixel; (d) each of those three accumulators
     is stored a value derived from an OpExtInst Exp (101's transfer); and
     (e) with --base, the base's whole disassembly is an ordered
     SUBSEQUENCE of the rung's under id-renumbering -- zero deleted, zero
     reordered and zero altered instructions, insertions only.
"""
import argparse, difflib, glob, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
from verify_earglow_rq import (dis, index, fval, uval, close, count,
                               path_counter, nee_trace, PASS_THROUGH,
                               GETTERS_OTHER)
from verify_earglow_rq3 import GET_ID, reaches, primary_ray

bad = V.bad

# ---- what 105 ships ------------------------------------------------------
TMIN, TMAX = 0.0003, 0.025
LD_DEF = 0.002
M_MAX, R_MIN = 0.1, 0.5
PUSH, TMIN_C = 0.001, 0.001
MASK, CLAMP, DIAG = 39, 100.0, 0.32
BRACKET = (0.999, 1.001, 1e-4)
CLASSES = (1, 4, 8)
# 101's query B range, used ONLY to tell the two triples apart.
EG_TMIN, EG_TMAX = 0.0015, 0.018
# 101 sec 5 / 102's constants.  If any one of these is gone, the ear glow is
# gone, whatever else the module still does.
EARGLOW_CONSTS = (272.479553, 68.1198883, 729.927002, 182.48175,
                  1470.58826, 367.647064, 0.219999999, 0.00600000005)
FLAG_BITS = {1: 'Opaque', 2: 'NoOpaque', 4: 'TerminateOnFirstHit',
             8: 'SkipClosestHitShader', 16: 'CullBackFacingTriangles',
             32: 'CullFrontFacingTriangles', 64: 'CullOpaque',
             128: 'CullNoOpaque', 256: 'SkipTriangles', 512: 'SkipAABBs'}
FLAGS_A = 1 | 4 | 512          # 517
FLAGS_B = 1 | 32 | 512         # 545
TYPE_GET = 'OpRayQueryGetIntersectionTypeKHR'
T_GET = 'OpRayQueryGetIntersectionTKHR'


def bits(v):
    return '|'.join(n for b, n in sorted(FLAG_BITS.items()) if v & b) or 'None'


def body(d, tok):
    return d.get(tok, (0, ''))[1]


def fv(d, tok, want, rel=1e-5):
    return close(fval(d, tok), want, rel)


def negzero(d, tok):
    """Bit-exact NEGATIVE zero.  `%float_0` is +0.0 and would NOT preserve the
    sign of a -0.0 accumulator, which is what makes the skin pixels bit
    identical (105 sec 7)."""
    return re.match(r'OpConstant %float -0$', body(d, tok)) is not None


def poszero(d, tok):
    return re.match(r'OpConstant %float 0$', body(d, tok)) is not None


def users(lines, tok):
    n = 0
    for l in lines:
        ops = l.split()
        n += sum(1 for o in ops[2:] if o == tok) if '=' in l else \
             sum(1 for o in ops[1:] if o == tok)
    return n


# ---- check 14e: the base is an ordered subsequence of the rung ------------
NUM = re.compile(r'%\d+')


def subsequence(base_path, rung_path, name):
    """spirv-as numbers ids by order of first appearance, so INSERTING a
    constant renumbers every id declared after it.  A raw textual diff is
    therefore all noise.  Normalising `%<digits>` away leaves the opcode, the
    operand arity, every literal and every friendly-named constant -- and
    under that normalisation nothing this rung does may delete, reorder or
    alter a single base instruction."""
    a = [NUM.sub('%#', l.strip()) for l in dis(base_path)
         if l.strip() and not l.startswith(';')]
    b = [NUM.sub('%#', l.strip()) for l in dis(rung_path)
         if l.strip() and not l.startswith(';')]
    ins = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == 'insert':
            ins += j2 - j1
        elif tag != 'equal':
            bad(name, f"14e: the base is NOT a subsequence of the rung -- "
                      f"a '{tag}' block at base line {i1+1} "
                      f"({a[i1:i2][:1]} -> {b[j1:j2][:1]})")
            return None
    return ins


# ---- the material gate's four reads --------------------------------------
def material_site(lines, d, name):
    """Re-found here, NOT imported: the module's own primary material decode.
    Anchor = the skin decision the reference raygens carry (96 sec 2.1) --
    an OpIEqual(class, 1) ANDed with an OpFOrdLessThan(metallic, 0.1) -- plus
    the roughness clamp NMax(.,0.04) -> NMin(.,1) and the three
    OpSelect(res, 1.0, a*a) albedo selects.  We only need the CONSTANTS the
    rung's gate compares against to exist and be unique; the cloned chain
    itself is checked structurally by check 8."""
    hits = []
    for l in lines:
        m = re.match(r'\s*(%\w+) = OpIEqual %bool (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        if uval(d, m.group(3)) != 1 and uval(d, m.group(2)) != 1:
            continue
        hits.append(m.group(1))
    if not hits:
        bad(name, "no class==1 test -- this is not a reference raygen")
    return hits


def check_module(path, base_path, mode, k, ld):
    name = os.path.basename(path)
    lines = dis(path)
    d = index(lines)

    # ---- 1. declarations --------------------------------------------------
    for cap in ('OpCapability RayQueryKHR',
                'OpExtension "SPV_KHR_ray_query"'):
        if not any(cap in l for l in lines):
            bad(name, f"1: missing {cap}")
    rqt = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpTypeRayQueryKHR\s*$', l) for l in lines) if m]
    if len(rqt) != 1:
        bad(name, f"1: {len(rqt)} OpTypeRayQueryKHR, want 1")
        return None
    ptr = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpTypePointer Function ' + re.escape(rqt[0])
                     + r'\s*$', l) for l in lines) if m]
    rqv = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpVariable (%\w+) Function\s*$', l)
            for l in lines) if m and m.group(2) in ptr]
    if len(rqv) != 6:
        bad(name, f"1: {len(rqv)} ray query variables, want exactly 6 "
                  f"(101's three, stacked with this rung's three)")
        return None

    # ---- 2. the module's own sun NEE trace --------------------------------
    ops, backlit = nee_trace(lines, d, name)
    if ops is None:
        return None
    P, S, tmax_c = ops[6], ops[8], ops[9]

    # ---- 3. six Initialize, split by query B's t range --------------------
    inits = []
    for l in lines:
        m = re.match(r'\s*OpRayQueryInitializeKHR (%\w+) (%\w+) (%\w+) (%\w+) '
                     r'(%\w+) (%\w+) (%\w+) (%\w+)\s*$', l)
        if m:
            inits.append(list(m.groups()))
    if len(inits) != 6:
        bad(name, f"3: {len(inits)} OpRayQueryInitializeKHR, want 6")
        return None
    if {i[0] for i in inits} != set(rqv):
        bad(name, "3: the six Initialize do not target the six declared "
                  "query objects one for one")
        return None
    mine = [i for i in inits if fv(d, i[5], TMIN) or fv(d, i[7], TMAX)
            or fv(d, i[5], TMIN_C)]
    theirs = [i for i in inits if i not in mine]
    B = [i for i in inits if fv(d, i[5], TMIN) and fv(d, i[7], TMAX)]
    egB = [i for i in inits if fv(d, i[5], EG_TMIN) and fv(d, i[7], EG_TMAX)]
    if len(B) != 1:
        bad(name, f"3: {len(B)} thickness queries with t in "
                  f"[{TMIN}, {TMAX}], want exactly 1")
        return None
    if len(egB) != 1:
        bad(name, f"3: {len(egB)} of 101's thickness queries "
                  f"(t in [{EG_TMIN}, {EG_TMAX}]) survive, want exactly 1")
    B = B[0]

    # ---- 4. one shared cull mask, and it is not 101's ---------------------
    msk = B[3]
    sm = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', body(d, msk))
    if not sm or uval(d, sm.group(2)) != MASK or uval(d, sm.group(3)) != 0:
        bad(name, f"4: this rung's cull mask is {body(d, msk)!r}, want "
                  f"OpSelect(gate, {MASK}, 0)")
        return None
    gate_cond = sm.group(1)
    mine = [i for i in inits if i[3] == msk]
    if len(mine) != 3:
        bad(name, f"4: {len(mine)} Initialize share this rung's cull mask, "
                  f"want exactly 3 (A, B, C)")
        return None
    if egB[0][3] == msk:
        bad(name, "4: 101's thickness query shares THIS rung's gate -- the "
                  "ear glow would inherit the thin-surface gate")
    A = [i for i in mine if i[4] not in (P,) and i is not B
         and re.match(r'OpConstantComposite %v3float', body(d, i[4]))]
    C = [i for i in mine if i is not B and i not in A]
    if len(A) != 1 or len(C) != 1:
        bad(name, f"4: cannot split this rung's triple into A/B/C "
                  f"({len(A)} A, {len(C)} C)")
        return None
    A, C = A[0], C[0]

    # ---- 5. query B --------------------------------------------------------
    fb = uval(d, B[2])
    if fb != FLAGS_B:
        bad(name, f"5: query B flags {fb} ({bits(fb or 0)}), want {FLAGS_B} "
                  f"({bits(FLAGS_B)})")
    else:
        for b in (1, 32, 512):
            if not fb & b:
                bad(name, f"5: query B is missing the {FLAG_BITS[b]} bit")
        if fb & 16:
            bad(name, "5: query B culls BACK faces -- it would read the "
                      "distance to the front wall, not the thickness")
    if B[4] != P or B[6] != S:
        bad(name, "5: query B does not use the sun trace's own origin and "
                  "direction")
    if B[1] != ops[0]:
        bad(name, "5: query B uses a different acceleration structure than "
                  "the module's own sun trace")
    if not fv(d, B[5], TMIN):
        bad(name, f"5: query B tmin {fval(d, B[5])}, want {TMIN}")
    if not fv(d, B[7], TMAX):
        bad(name, f"5: query B tmax {fval(d, B[7])}, want {TMAX}")

    # ---- 6. query A --------------------------------------------------------
    fa = uval(d, A[2])
    if fa != FLAGS_A:
        bad(name, f"6: query A flags {fa} ({bits(fa or 0)}), want {FLAGS_A} "
                  f"({bits(FLAGS_A)})")
    if not re.match(r'OpConstantComposite %v3float (%\w+) \1 \1$'.replace(
            r'\1', r'%\w+'), body(d, A[4])) or \
            not all(poszero(d, x) or negzero(d, x)
                    for x in body(d, A[4]).split()[2:5]):
        bad(name, f"6: query A origin {body(d, A[4])!r} is not the zero triple")
    prim = primary_ray(lines, d, name)
    if prim is None:
        return None
    dirA = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                    body(d, A[6]))
    if not dirA or list(dirA.groups()) != prim['V']:
        bad(name, "6: query A's direction is not the module's own normalized "
                  "view ray")
    tA = [i for i, l in enumerate(lines)
          if re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(prim['dot'])
                      + ' ' + re.escape(prim['rsqrt']) + r'\s*$', l)]
    lo = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, A[5]))
    hi = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(d, A[7]))
    if not lo or not fv(d, lo.group(2), BRACKET[0]):
        bad(name, f"6: query A tmin is not |P| * {BRACKET[0]}")
    if not hi or not fv(d, hi.group(2), BRACKET[2], rel=1e-3):
        bad(name, f"6: query A tmax does not add the {BRACKET[2]} epsilon")
    else:
        hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, hi.group(1)))
        if not hm or not fv(d, hm.group(2), BRACKET[1]):
            bad(name, f"6: query A tmax is not |P| * {BRACKET[1]} + eps")
        elif not lo or hm.group(1) != lo.group(1):
            bad(name, "6: query A's two bracket ends are built from "
                      "different |P|")
        elif not tA:
            bad(name, "6: |P| is not dot(P,P) * rsqrt(dot(P,P))")

    # ---- 7. query C --------------------------------------------------------
    fc = uval(d, C[2])
    if fc != FLAGS_A:
        bad(name, f"7: query C flags {fc} ({bits(fc or 0)}), want {FLAGS_A}")
    if fc and fc & (16 | 32):
        bad(name, "7: query C culls faces -- a visibility ray must not")
    org = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', body(d, C[4]))
    if not org or P not in org.groups():
        bad(name, "7: query C does not start at the trace's own P plus an "
                  "offset")
        return None
    off = [x for x in org.groups() if x != P][0]
    vm = re.match(r'OpVectorTimesScalar %v3float (%\w+) (%\w+)$', body(d, off))
    if not vm or vm.group(1) != S:
        bad(name, "7: query C's offset is not along the sun direction")
        return None
    tp = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(d, vm.group(2)))
    if not tp or not fv(d, tp.group(2), PUSH):
        bad(name, f"7: query C's exit point is not t + {PUSH} m")
    if C[6] != S:
        bad(name, "7: query C is not traced along the sun direction")
    if not fv(d, C[5], TMIN_C):
        bad(name, f"7: query C tmin {fval(d, C[5])}, want {TMIN_C}")
    if C[7] != tmax_c:
        bad(name, "7: query C's tmax is not the module's OWN sun shadow-ray "
                  "tmax -- it would disagree with the engine about the sun")

    # ---- 8. the seven-term gate -------------------------------------------
    terms, stack, seen = [], [gate_cond], set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', body(d, cur))
        if m:
            stack += list(m.groups())
        else:
            terms.append(cur)
    if len(terms) != 7:
        bad(name, f"8: {len(terms)} gate terms under the cull mask, want 7 "
                  f"(class != 1/4/8, metallic < {M_MAX}, roughness > {R_MIN}, "
                  f"backlit, path == 0)")
    got = {}
    for t in terms:
        b = body(d, t)
        m = re.match(r'OpINotEqual %bool (%\w+) (%\w+)$', b)
        if m:
            for x in m.groups():
                if uval(d, x) in CLASSES:
                    got.setdefault('cls', set()).add(uval(d, x))
            continue
        m = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)$', b)
        if m and fv(d, m.group(2), M_MAX):
            got['metal'] = t
            continue
        m = re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$', b)
        if m and fv(d, m.group(2), R_MIN):
            got['rough'] = t
            continue
        m = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', b)
        if m and (uval(d, m.group(2)) == 0 or uval(d, m.group(1)) == 0):
            got['path'] = t
            continue
        if t == backlit:
            got['backlit'] = t
    if got.get('cls') != set(CLASSES):
        bad(name, f"8: the class exclusions are {sorted(got.get('cls', ()))}, "
                  f"want {list(CLASSES)} -- class 1 missing would paint over "
                  f"the ear glow")
    for kk, why in (('metal', f'metallic < {M_MAX}'),
                    ('rough', f'roughness > {R_MIN}'),
                    ('backlit', "the trace's own backlit test"),
                    ('path', 'path counter == 0')):
        if kk not in got:
            bad(name, f"8: the gate has no {why} term")
    ctr = path_counter(lines, d, name)
    if ctr and 'path' in got:
        pm = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', body(d, got['path']))
        if pm and ctr not in pm.groups():
            bad(name, "8: the path term does not test the re-derived path "
                      "loop counter")
    if not material_site(lines, d, name):
        pass

    # ---- 9. the getter census ---------------------------------------------
    for gname, want in ((f'{TYPE_GET} %uint', 6), (f'{GET_ID} %uint', 4),
                        (f'{T_GET} %float', 2),
                        ('OpRayQueryProceedKHR', 6)):
        n = count(lines, gname)
        if n != want:
            bad(name, f"9: {n} {gname.split()[0]}, want {want}")
    for g in GETTERS_OTHER:
        if g != GET_ID and count(lines, g):
            bad(name, f"9: forbidden getter {g}")

    # ---- 10. the instance match and the accept ----------------------------
    def getter(op, q):
        return [m.group(1) for m in
                (re.match(r'\s*(%\w+) = ' + op + r' %\w+ (%\w+) (%\w+)\s*$', l)
                 for l in lines) if m and m.group(2) == q
                and uval(d, m.group(3)) == 1]
    idA, idB = getter(GET_ID, A[0]), getter(GET_ID, B[0])
    if len(idA) != 1 or len(idB) != 1:
        bad(name, "10: this rung's A and B do not each have exactly one "
                  "committed InstanceId read")
        return None
    same = [m.group(1) for m in
            (re.match(r'\s*(%\w+) = OpIEqual %bool (%\w+) (%\w+)\s*$', l)
             for l in lines)
            if m and {m.group(2), m.group(3)} == {idA[0], idB[0]}]
    if len(same) != 1:
        bad(name, "10: the instance match is not an OpIEqual over this rung's "
                  "two InstanceId results (inverted or wrong-field build?)")
        return None
    tyC = getter(TYPE_GET, C[0])
    if len(tyC) != 1:
        bad(name, "10: query C has no committed-type test")
        return None
    hitC = [m.group(1) for m in
            (re.match(r'\s*(%\w+) = OpINotEqual %bool (%\w+) (%\w+)\s*$', l)
             for l in lines) if m and tyC[0] in m.groups()]
    notC = [m.group(1) for m in
            (re.match(r'\s*(%\w+) = OpLogicalNot %bool (%\w+)\s*$', l)
             for l in lines) if m and m.group(2) in hitC]
    if not notC:
        bad(name, "10: C's hit is never NEGATED -- this build would light "
                  "exactly the pixels the sun cannot see")
        return None

    # ---- 11 / 12. the transfer --------------------------------------------
    tq = getter(T_GET, B[0])
    if len(tq) != 1:
        bad(name, "11: query B has no committed T read")
        return None
    guard = [m.group(1) for m in
             (re.match(r'\s*(%\w+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)
              for l in lines) if m and m.group(3) == tq[0]]
    if len(guard) != 1:
        bad(name, f"11: {len(guard)} NaN guards on query B's t, want 1 "
                  f"(T on a missed query is UNDEFINED)")
        return None
    gm = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', body(d, guard[0]))
    if not fv(d, gm.group(3), TMAX):
        bad(name, f"11: the NaN guard's miss arm is {fval(d, gm.group(3))}, "
                  f"want tmax {TMAX}")
    if users(lines, tq[0]) != 1:
        bad(name, f"11: the RAW t has {users(lines, tq[0])} consumers, want 1 "
                  f"(only the guard may read it)")
    tu = guard[0]

    # The ACCEPT is identified from the PAINT side -- the condition of the
    # selects that actually decide the radiance -- and only then checked for
    # dominance.  Picking it from the boolean side would also match `rej`
    # (the -hit rung's red arm), which reaches the same three ids through an
    # extra OpLogicalNot and decides nothing about the accepted pixels.
    fsel = [m for m in
            (re.match(r'\s*(%\w+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)
             for l in lines) if m]
    if mode == 'glow':
        cand = [m.group(2) for m in fsel if negzero(d, m.group(4))
                and fval(d, m.group(3)) is not None]
    else:
        cand = [m.group(2) for m in fsel
                if re.match(r'OpSelect %float ', body(d, m.group(4)))]
    cand = [c for c in set(cand)
            if reaches(d, c, same[0]) and reaches(d, c, notC[0])
            and reaches(d, c, gate_cond)]
    if len(cand) != 1:
        bad(name, f"10: {len(cand)} accept conditions dominate the paint and "
                  f"reach the instance match, C's miss AND the seven-term "
                  f"gate, want exactly 1")
        return None
    ok = cand[0]
    if not reaches(d, ok, notC[0], ops=('OpLogicalAnd',)):
        bad(name, "10: C's miss reaches the accept only through an extra "
                  "negation -- this build lights the OCCLUDED pixels")

    nexp = ntr = 0
    if mode == 'glow':
        sel = [m.group(1) for m in
               (re.match(r'\s*(%\w+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)
                for l in lines) if m and m.group(2) == ok]
        if len(sel) != 1:
            bad(name, f"12: {len(sel)} k selects on the accept, want 1")
        else:
            km = re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, sel[0]))
            if k == 0.0:
                if not (negzero(d, km.group(1)) or fv(d, km.group(1), 0.0)):
                    bad(name, "12: k=0 rung does not select zero")
            elif not fv(d, km.group(1), k):
                bad(name, f"12: k is {fval(d, km.group(1))}, want {k}")
            if not negzero(d, km.group(2)):
                bad(name, "12: the k select's FALSE arm is not NEGATIVE zero "
                          "-- a +0.0 add does not preserve a -0.0 accumulator "
                          "and the ear glow would stop being bit identical")
        exps = [m for m in
                (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ Exp (%\w+)\s*$', l)
                 for l in lines) if m]
        for m in exps:
            neg = re.match(r'OpFNegate %float (%\w+)$', body(d, m.group(2)))
            if not neg:
                continue
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, neg.group(1)))
            if mm and tu in mm.groups():
                other = [x for x in mm.groups() if x != tu][0]
                if fv(d, other, 1.0 / ld, rel=1e-4):
                    nexp += 1
                else:
                    bad(name, f"12: the transfer rate is {fval(d, other)}, "
                              f"want 1/ld = {1.0/ld}")
        if nexp != 1:
            bad(name, f"12: {nexp} Exp consume the guarded t at rate 1/ld, "
                      f"want exactly 1 (ld is a SCALAR: one Exp, three albedo "
                      f"multiplies)")
        # The albedo tint, re-derived from the TRANSFER outward rather than
        # by counting squares in the module (the base has plenty of its own).
        # exp(-t/ld) is multiplied by the k select to give kw, and kw must be
        # consumed by exactly THREE OpFMul, each against an OpFMul(x, x) --
        # the module's own squared base colour.  `--decoy noalbedo` multiplies
        # kw straight into the sun radiance and dies here.
        expid = [m.group(1) for m in
                 (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ Exp (%\w+)\s*$', l)
                  for l in lines) if m and
                 re.match(r'OpFNegate %float (%\w+)$', body(d, m.group(2)))
                 and tu in re.findall(r'%\w+', body(
                     d, re.match(r'OpFNegate %float (%\w+)$',
                                 body(d, m.group(2))).group(1)))]
        kw = [m.group(1) for m in
              (re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
               for l in lines)
              if m and set(m.groups()[1:]) & set(expid)
              and set(m.groups()[1:]) & set(sel)]
        ntr = 0
        if len(kw) != 1:
            bad(name, f"12: {len(kw)} products of the k select and exp(-t/ld), "
                      f"want 1")
        else:
            cons = [m for m in
                    (re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
                     for l in lines) if m and kw[0] in m.groups()[1:]]
            for m in cons:
                other = [x for x in m.groups()[1:] if x != kw[0]]
                o = other[0] if other else kw[0]
                sm2 = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, o))
                if sm2 and sm2.group(1) == sm2.group(2):
                    ntr += 1
            if ntr != 3:
                bad(name, f"12: {ntr} of {len(cons)} consumers of "
                          f"k*exp(-t/ld) multiply a SQUARED albedo channel, "
                          f"want 3 -- without it every tarp glows white")
    else:
        for l in lines:
            m = re.match(r'\s*%\w+ = OpExtInst %float %\w+ Exp (%\w+)\s*$', l)
            if m:
                neg = re.match(r'OpFNegate %float (%\w+)$', body(d, m.group(1)))
                mm = neg and re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                      body(d, neg.group(1)))
                if mm and tu in mm.groups():
                    bad(name, "12: the -hit diagnostic carries a transfer")
        cl = [m for m in
              (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NClamp (%\w+) '
                        r'(%\w+) (%\w+)\s*$', l) for l in lines) if m]
        ramp = None
        for m in cl:
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, m.group(2)))
            if not mm:
                continue
            sub = re.match(r'OpFSub %float (%\w+) (%\w+)$', body(d, mm.group(1)))
            if sub and sub.group(1) == tu and fv(d, sub.group(2), TMIN):
                if not fv(d, mm.group(2), 1.0 / (TMAX - TMIN), rel=1e-4):
                    bad(name, f"12: the ramp span is {fval(d, mm.group(2))}, "
                              f"want 1/(tmax-tmin) = {1.0/(TMAX-TMIN)}")
                ramp = m.group(1)
        if ramp is None:
            bad(name, "12: no NClamp((t - tmin) * span, 0, 1) thickness ramp")
        ntr = sum(1 for l in lines
                  if re.match(r'\s*%\w+ = OpExtInst %float %\w+ NMin ', l))

    nmin = [m for m in
            (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NMin (%\w+) (%\w+)\s*$', l)
             for l in lines) if m and fv(d, m.group(3), CLAMP)]
    if len(nmin) < 3:
        bad(name, f"12: {len(nmin)} NMin clamps at {CLAMP}, want 3 -- one "
                  f"fireflied thin surface poisons the accumulator")

    # ---- 13 / 14. the writes ----------------------------------------------
    acc, eg_acc, nw = set(), set(), 0
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        cc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) '
                      r'(%\w+)$', body(d, m.group(3)))
        if not cc:
            continue
        mineadd, egadd = [], []
        for ch in range(3):
            am = re.match(r'OpFAdd %float (%\w+) (%\w+)$',
                          body(d, cc.group(ch + 1)))
            if not am:
                continue
            ld_ = [x for x in am.groups()
                   if re.match(r'OpLoad %float %\w+$', body(d, x))]
            if not ld_:
                continue
            mineadd.append(body(d, ld_[0]).split()[-1])
            inner = [x for x in am.groups() if x not in ld_][0]
            im = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(d, inner))
            if im:
                for x in im.groups():
                    if re.match(r'OpLoad %float %\w+$', body(d, x)):
                        egadd.append(body(d, x).split()[-1])
        if len(mineadd) == 3:
            nw += 1
            acc.update(mineadd)
            eg_acc.update(egadd)
            if len(egadd) != 3:
                bad(name, f"14c: the write at line {i+1} adds this rung's "
                          f"term to a value that is NOT the ear glow's own "
                          f"add -- 101's term has been displaced")
        elif mineadd:
            bad(name, f"13: the write at line {i+1} adds only "
                      f"{len(mineadd)} of 3 channels")
    if nw == 0:
        bad(name, "13: no radiance write carries this rung's term")
    if len(acc) != 3:
        bad(name, f"13: {len(acc)} accumulators across the painted writes, "
                  f"want exactly 3")
    for a_ in acc:
        st = [l for l in lines
              if re.match(r'\s*OpStore ' + re.escape(a_) + r' (%\w+)\s*$', l)]
        if not any(negzero(d, l.split()[-1]) for l in st):
            bad(name, f"13: accumulator {a_} is not initialised to NEGATIVE "
                      f"zero (105 sec 7)")

    # ---- 14. ear glow intact ----------------------------------------------
    have = {c: False for c in EARGLOW_CONSTS}
    for l in lines:
        m = re.match(r'\s*%\w+ = OpConstant %float (\S+)$', l)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        for c in EARGLOW_CONSTS:
            if close(v, c, 1e-6):
                have[c] = True
    missing = [c for c, ok_ in have.items() if not ok_]
    if missing:
        bad(name, f"14a: 101/102 constants gone from the shipped bytes: "
                  f"{missing}")
    if len(eg_acc) != 3:
        bad(name, f"14c: {len(eg_acc)} distinct ear-glow accumulators under "
                  f"the painted writes, want 3")
    if eg_acc & acc:
        bad(name, f"14c: this rung reuses 101's accumulator(s) {eg_acc & acc}")
    for a_ in eg_acc:
        srcs = [l.split()[-1] for l in lines
                if re.match(r'\s*OpStore ' + re.escape(a_) + r' (%\w+)\s*$', l)]
        if not any(reaches(d, s, s, ops=()) for s in srcs):
            pass
        deep, found = list(srcs), False
        seenv = set()
        while deep and not found:
            cur = deep.pop()
            if cur in seenv:
                continue
            seenv.add(cur)
            b = body(d, cur)
            if re.match(r'OpExtInst %float %\w+ Exp ', b):
                found = True
                break
            deep += re.findall(r'%\w+', b)[1:]
        if not found:
            bad(name, f"14d: ear-glow accumulator {a_} is never fed by an "
                      f"OpExtInst Exp -- 101's transfer is gone")

    ins = None
    if base_path:
        bl = dis(base_path)
        bd = index(bl)
        for gname, want in ((f'{TYPE_GET} %uint', 3), (f'{GET_ID} %uint', 2),
                            (f'{T_GET} %float', 1),
                            ('OpRayQueryProceedKHR', 3),
                            ('OpRayQueryInitializeKHR', 3)):
            n = count(bl, gname)
            if n != want:
                bad(name, f"14b: the BASE has {n} {gname.split()[0]}, want "
                          f"{want} -- this is not the earglow base")
        ins = subsequence(base_path, path, name)
    return {'writes': nw, 'inserted': ins, 'exp': nexp, 'sq': ntr}


def negative(base_dir):
    n = 0
    for p in sorted(glob.glob(os.path.join(base_dir, '*.rgs_reference_main.spv'))):
        name = os.path.basename(p)
        if name.split('.')[0] in PASS_THROUGH:
            continue
        lines = dis(p)
        d = index(lines)
        if count(lines, 'OpRayQueryInitializeKHR') != 3:
            bad(name, "negative: the base does not carry exactly 101's three "
                      "ray queries")
        for l in lines:
            m = re.match(r'\s*%\w+ = OpConstant %float (\S+)$', l)
            if not m:
                continue
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if close(v, TMAX, 1e-6) or close(v, TMIN, 1e-6):
                bad(name, f"negative: the BASE already carries this rung's "
                          f"t range constant {v}")
        n += 1
    print(f"negative control: {n} base reference modules carry 101's three "
          f"queries and none of 105's")


def control(ctl_dir, base_dir):
    n = 0
    for p in sorted(glob.glob(os.path.join(ctl_dir, '*.rgs_reference_main.spv'))):
        name = os.path.basename(p)
        b = os.path.join(base_dir, name)
        if not os.path.exists(b):
            bad(name, "control: no base counterpart")
            continue
        if open(p, 'rb').read() != open(b, 'rb').read():
            bad(name, "control: NOT byte identical to the base")
        n += 1
    print(f"control: {n} modules compared byte for byte against the base")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--negative')
    ap.add_argument('--control')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--k', type=float, default=0.5)
    ap.add_argument('--ld', type=float, default=LD_DEF)
    a = ap.parse_args()
    if a.negative:
        negative(a.negative)
    elif a.control:
        if not a.base:
            ap.error('--control needs --base')
        control(a.control, a.base)
    else:
        if not a.rung:
            ap.error('need <rung-dir>')
        n = tot = ins = 0
        for p in sorted(glob.glob(os.path.join(a.rung,
                                               '*.rgs_reference_main.spv'))):
            ident = os.path.basename(p).split('.')[0]
            if ident in PASS_THROUGH:
                continue
            b = os.path.join(a.base, os.path.basename(p)) if a.base else None
            if b and not os.path.exists(b):
                bad(os.path.basename(p), "no base counterpart")
                continue
            r = check_module(p, b, a.mode, a.k, a.ld)
            n += 1
            if r:
                tot += r['writes']
                ins += r['inserted'] or 0
        print(f"verify_thinglow: {n} permutations, {tot} painted writes, "
              f"{ins} inserted lines, mode={a.mode}, k={a.k}, ld={a.ld} m, "
              f"A=517 B=545 C=517, gate=7 terms, match=InstanceId")
    if V.FAIL:
        for f in V.FAIL:
            print("  FAIL " + f)
        raise SystemExit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
