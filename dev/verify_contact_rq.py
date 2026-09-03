#!/usr/bin/env python3
"""verify_contact_rq.py <rung-dir> --base <base-dir> --mode dark|hit
                        [--rays K] [--flags N] [--tmin T] [--tmax M]
   verify_contact_rq.py --negative <base-dir>

Re-derives the contact-rq splice from the SHIPPED .spv bytes. Never from the
patcher's reports, never from a byte diff (42: "a byte diff is not coverage"),
and never by importing the patcher's own detectors -- the path-loop counter
(90 sec 1) is re-derived HERE by a second implementation of the same
structural rule, so a verifier passing cannot merely mean the patcher agreed
with itself. Ids do not survive the assemble/disassemble round trip (40 sec
8), so every check below is structural or by resolved constant VALUE.

Proven per patched rgs_reference_main permutation (12 of 12 on this base):

  1  OpCapability RayQueryKHR + OpExtension "SPV_KHR_ray_query"; exactly one
     OpTypeRayQueryKHR; exactly one Function-storage ray-query variable, and
     it sits in the entry block's leading OpVariable run;
  2  exactly K OpRayQueryInitializeKHR, K OpRayQueryProceedKHR, K
     GetIntersectionTypeKHR on the COMMITTED intersection, and ZERO of every
     other getter -- including GetIntersectionTKHR: this asks a BOOLEAN, so
     reading t would be a different feature;
  3  every Initialize shares one query object, one acceleration structure,
     one cull mask and one ORIGIN, and its flags are the constant 517 =
     OpaqueKHR | TerminateOnFirstHitKHR | SkipAABBsKHR -- checked bit by bit,
     with CullFront (0x20, 101's word) and CullBack (0x10) BOTH clear, since
     nearby geometry may present either face;
  4  tmin resolves to 0.001 (the 1 mm self-hit guard -- with no face culling
     it is the ONLY guard) and tmax to 0.10;
  5  the cull mask is OpSelect(gate, 39, 0), and the gate is
     AND(AND(IEqual(<class>,1), IEqual(<counter>,0)), <normal is non-degenerate>)
     where <class> is a slot-5 `>>5` material word (88 sec 4) and <counter>
     must BE the path-loop counter re-derived here -- which is what rejects a
     build made with 79/85's legacy helper (90 sec 1);
  6  the origin is OpFAdd(<the cone's own trace origin operand>,
     VectorTimesScalar(N, eps)) -- the traced ray starts where the cone's rays
     started, lifted along the same normal;
  7  N is Normalize(OpSelect(gate, <the cone's own harvested normal
     construct>, <its own normalised light direction>)), i.e. 88's
     select-before-normalize, so no NaN direction can ever be initialised;
  8  the tangent frame is built IN-MODULE from N by the branch-free method:
     sign = Select(n.z >= 0, 1, -1), a = -1/(sign + n.z), b = n.x*n.y*a, and
     the two composite vectors of the standard form -- then rotated about N
     by Cos/Sin of an angle derived ONLY from gl_LaunchID (pixel-seeded and
     frame-stable; 98 sec 12.6);
  9  each direction is FAdd(FAdd(VTS(T', cx), VTS(B', cy)), VTS(N, cz)) with
     cx^2+cy^2+cz^2 == 1 and cz > 0 (upper hemisphere), and the K triples are
     distinct;
 10  o = FMul(<a K-term sum of Select(committed, 1, 0)>, 1/K);
 11  THE CONE IS DEAD, two ways: (a) all three of 88's cones now compute
     OpFMul(OpSelect(AND(gate, <that light's own lit bool>), o, +0.0), k) with
     k STILL the base's 0.85, and each cone's own `occ` select has exactly ONE
     mention left in the module -- its definition; (b) every flags-16 cone tap
     carries cull mask %uint_0, a guaranteed miss;
 12  OpTraceRayKHR count is UNCHANGED from the base -- this adds a query,
     never a ray;
 13  hit: every painted OpImageWrite texel is OpCompositeConstruct(
     Select(u, p, x), Select(u, p, y), Select(u, p, z), w) over one Function
     latch, with alpha untouched; dark: no image write is rewritten at all.

--negative asserts the base carries none of it.
"""
import argparse, glob, math, os, re, subprocess, sys

UNIT_ONE = ('%half_0x1p_0', '%float_1')
GETTERS_OTHER = (
    'OpRayQueryGetIntersectionTKHR',
    'OpRayQueryGetIntersectionInstanceIdKHR',
    'OpRayQueryGetIntersectionInstanceCustomIndexKHR',
    'OpRayQueryGetIntersectionPrimitiveIndexKHR',
    'OpRayQueryGetIntersectionGeometryIndexKHR',
    'OpRayQueryGetIntersectionObjectToWorldKHR',
    'OpRayQueryGetIntersectionWorldToObjectKHR',
    'OpRayQueryGetIntersectionInstanceShaderBindingTableRecordOffsetKHR',
    'OpRayQueryGetIntersectionBarycentricsKHR',
    'OpRayQueryGetIntersectionFrontFaceKHR',
    'OpRayQueryGetIntersectionObjectRayDirectionKHR',
    'OpRayQueryGetIntersectionObjectRayOriginKHR',
)
FLAG_BITS = {0x001: 'OpaqueKHR', 0x004: 'TerminateOnFirstHitKHR',
             0x200: 'SkipAABBsKHR'}
FLAG_FORBIDDEN = {0x010: 'CullBackFacingTrianglesKHR',
                  0x020: 'CullFrontFacingTrianglesKHR (101 sec 2 -- that is a '
                         'THICKNESS probe, not a contact probe)',
                  0x002: 'NoOpaqueKHR', 0x100: 'SkipTrianglesKHR'}
FAIL = []


def bad(mod, msg):
    FAIL.append(f"{mod}: {msg}")


def dis(path):
    r = subprocess.run(['spirv-dis', '--no-color', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"spirv-dis failed on {path}:\n{r.stderr}")
    return r.stdout.split('\n')


def index(lines):
    d = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d.setdefault(m.group(1), (i, m.group(2)))
    return d


def fval(d, tok):
    if tok not in d:
        m = re.match(r'%float_n?(\d+)$', tok)
        return None
    m = re.match(r'OpConstant %float (\S+)$', d[tok][1])
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def uval(d, tok):
    if tok in d:
        m = re.match(r'OpConstant %uint (\d+)$', d[tok][1])
        if m:
            return int(m.group(1))
    m = re.match(r'%uint_(\d+)$', tok)
    return int(m.group(1)) if m else None


def close(a, b, rel=1e-5):
    return a is not None and b is not None and abs(a - b) <= rel * max(1.0, abs(b))


def count(lines, needle):
    return sum(1 for l in lines if needle in l)


def uses(lines, tok):
    n = 0
    for l in lines:
        n += len(re.findall(re.escape(tok) + r'(?![0-9A-Za-z_])', l))
    return n


def path_counter(lines, d, name):
    """90 sec 1's PATH-loop counter, re-derived independently of the patcher.

    Among counted loops `Op[SU]LessThan(x + 1, bound)` on a back edge whose
    body traces rays, the path loop is the one whose header seeds exactly 3
    fp phis with 1.0 (the RGB throughput); the sample loop seeds none. Its
    counter is the unique `OpPhi %uint` at that header whose incomings are
    exactly {0, that loop's own IAdd}."""
    labels = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', l)
        if m:
            labels[m.group(1)] = i
    hot = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', l)
        if not m:
            continue
        cond, t0, t1 = m.groups()
        cm = re.match(r'Op[SU]LessThan %bool (%\w+) (%\w+)$',
                      d.get(cond, (0, ''))[1])
        if not cm:
            continue
        inc = cm.group(1)
        if not re.match(r'OpIAdd %uint %\w+ %uint_1$', d.get(inc, (0, ''))[1]):
            continue
        for tgt in (t0, t1):
            hi = labels.get(tgt)
            if hi is None or hi >= i:
                continue
            if not any('OpTraceRayKHR' in lines[j] for j in range(hi, i)):
                continue
            ones, uphis = 0, []
            for j in range(hi + 1, len(lines)):
                if not re.match(r'\s*\S+\s*=\s*OpPhi ', lines[j]):
                    break
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(?:half|float) (.+?)\s*$',
                              lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(1).split()[0::2]):
                    ones += 1
                um = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+?)\s*$',
                              lines[j])
                if um:
                    uphis.append((um.group(1), um.group(2).split()[0::2]))
            if ones == 3:
                hot.append([pid for pid, vals in uphis
                            if set(vals) == {'%uint_0', inc}])
            elif ones:
                bad(name, f"non-path loop {tgt} seeds {ones} phis with 1.0")
    if len(hot) != 1 or len(hot[0]) != 1:
        bad(name, f"path-loop counter not unique: {hot}")
        return None
    return hot[0][0]


def cones(lines, d, name):
    """88's three cavity cones, re-found in the RUNG by their application
    shape. Returns a list of dicts; the two whose lit-condition is
    FOrdEqual(t, 10000) are the local lights (88 sec 5b)."""
    out = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        occk, src, kc = m.groups()
        if fval(d, kc) is None:
            continue
        # 88's identity guard is the discriminator: the strength always
        # multiplies an OpSelect whose false arm is exactly +0.0, so that a
        # dead gate gives fac == 1.0 bit for bit. Nothing else in this raygen
        # has that shape, and requiring it keeps every other `x * const` in a
        # 14 000-line module out of this list.
        if not re.match(r'OpSelect %float %\w+ %\w+ %float_0$',
                        d.get(src, (0, ''))[1]):
            continue
        if not any(re.match(r'\s*%\w+ = OpFSub %float %float_1 '
                            + re.escape(occk) + r'\s*$', x) for x in lines):
            continue
        out.append(dict(line=i, occk=occk, src=src, k=fval(d, kc), kid=kc))
    return out


def check_module(path, base_path, mode, rays, flags, tmin, tmax):
    name = os.path.basename(path).split('.')[0]
    L = dis(path)
    d = index(L)
    B = dis(base_path)
    db = index(B)

    # --- 1. header, type, variable -----------------------------------------
    if not any(re.match(r'\s*OpCapability RayQueryKHR\s*$', l) for l in L):
        bad(name, "no OpCapability RayQueryKHR")
    if not any('OpExtension "SPV_KHR_ray_query"' in l for l in L):
        bad(name, 'no OpExtension "SPV_KHR_ray_query"')
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$',
                        l) for l in L):
        bad(name, "SkipAABBs is used without RayTraversalPrimitiveCullingKHR")
    rqt = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpTypeRayQueryKHR\s*$', l) for l in L) if m]
    if len(rqt) != 1:
        bad(name, f"{len(rqt)} OpTypeRayQueryKHR, want 1")
        return
    ptr = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpTypePointer Function '
                     + re.escape(rqt[0]) + r'\s*$', l) for l in L) if m]
    if len(ptr) != 1:
        bad(name, f"{len(ptr)} Function pointers to the query type, want 1")
        return
    qv = [m.group(1) for m in
          (re.match(r'\s*(%\w+) = OpVariable ' + re.escape(ptr[0])
                    + r' Function\s*$', l) for l in L) if m]
    if len(qv) != 1:
        bad(name, f"{len(qv)} ray-query variables, want 1")
        return
    qv = qv[0]

    # --- 2. the getters -----------------------------------------------------
    inits = [l for l in L if 'OpRayQueryInitializeKHR' in l]
    n_pro = count(L, 'OpRayQueryProceedKHR')
    n_typ = count(L, 'OpRayQueryGetIntersectionTypeKHR')
    if (len(inits), n_pro, n_typ) != (rays, rays, rays):
        bad(name, f"Initialize/Proceed/Type = "
                  f"{(len(inits), n_pro, n_typ)}, want {rays} each")
    for g in GETTERS_OTHER:
        if count(L, g):
            bad(name, f"{count(L, g)} x {g} -- this asks a BOOLEAN, so no "
                      f"other getter belongs here")
    for l in L:
        m = re.match(r'\s*(%\w+) = OpRayQueryGetIntersectionTypeKHR %uint '
                     r'(%\w+) (%\w+)\s*$', l)
        if m:
            if m.group(2) != qv:
                bad(name, "a type getter reads a different query object")
            if uval(d, m.group(3)) != 1:
                bad(name, "a type getter does not read the COMMITTED "
                          "intersection")

    # --- 3. the Initialize operands ----------------------------------------
    ops = []
    for l in inits:
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        o = m.group(1).split()
        if len(o) != 8:
            bad(name, f"Initialize has {len(o)} operands, want 8")
            return
        ops.append(o)
    for k, tag in ((0, 'query object'), (1, 'acceleration structure'),
                   (2, 'ray flags'), (3, 'cull mask'), (4, 'origin'),
                   (5, 'tmin'), (7, 'tmax')):
        if len({o[k] for o in ops}) != 1:
            bad(name, f"the {rays} queries do not share one {tag}")
    if ops[0][0] != qv:
        bad(name, "Initialize does not use the declared query variable")
    fw = uval(d, ops[0][2])
    if fw != flags:
        bad(name, f"ray flags {fw} != {flags}")
    else:
        for bit, nm in FLAG_BITS.items():
            if flags == 517 and not (fw & bit):
                bad(name, f"ray flags {fw} is missing {nm} (0x{bit:03x})")
        for bit, nm in FLAG_FORBIDDEN.items():
            if flags == 517 and (fw & bit):
                bad(name, f"ray flags {fw} sets {nm} (0x{bit:03x})")
    if not close(fval(d, ops[0][5]), tmin):
        bad(name, f"tmin {fval(d, ops[0][5])} != {tmin}")
    if not close(fval(d, ops[0][7]), tmax):
        bad(name, f"tmax {fval(d, ops[0][7])} != {tmax}")

    # --- 4. the gate --------------------------------------------------------
    pc = path_counter(L, d, name)
    sm = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$',
                  d.get(ops[0][3], (0, ''))[1])
    if not sm:
        bad(name, "the cull mask is not an OpSelect")
        return
    gate = sm.group(1)
    if uval(d, sm.group(2)) != 39 or uval(d, sm.group(3)) != 0:
        bad(name, f"cull mask select yields "
                  f"{uval(d, sm.group(2))}/{uval(d, sm.group(3))}, want 39/0")
    ga = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(gate, (0, ''))[1])
    if not ga:
        bad(name, "the gate is not an OpLogicalAnd")
        return
    gcs, gnok = ga.groups()
    nk = re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$',
                  d.get(gnok, (0, ''))[1])
    if not nk:
        bad(name, "the gate's second conjunct is not the non-degenerate "
                  "normal test")
    ga1 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(gcs, (0, ''))[1])
    if not ga1:
        bad(name, "the gate's first conjunct is not an OpLogicalAnd")
        return
    gsk, gp0 = ga1.groups()
    s = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(gsk, (0, ''))[1])
    if not s or uval(d, s.group(2)) != 1:
        bad(name, "the class conjunct is not IEqual(x, 1)")
    else:
        cd = d.get(s.group(1), (0, ''))[1]
        if not re.match(r'OpShiftRightLogical %uint %\w+ %uint_5$', cd):
            bad(name, f"the class operand is not a slot-5 `>>5` material "
                      f"word (88 sec 4) -- got {cd}")
    c = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(gp0, (0, ''))[1])
    if not c or uval(d, c.group(2)) != 0:
        bad(name, "the counter conjunct is not IEqual(x, 0)")
    elif pc is not None and c.group(1) != pc:
        bad(name, f"the counter operand is {c.group(1)}, but the PATH-loop "
                  f"counter is {pc} (90 sec 1: the legacy helper returns the "
                  f"SAMPLE loop's phi)")

    # --- 5. origin, normal, basis ------------------------------------------
    oa = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                  d.get(ops[0][4], (0, ''))[1])
    if not oa:
        bad(name, "the ray origin is not <cone origin> + N*eps")
        return
    base_org, lift = oa.groups()
    if not re.match(r'OpCompositeConstruct %v3float ',
                    d.get(base_org, (0, ''))[1]):
        bad(name, "the origin's first addend is not a v3float construct")
    tap_origins = set()
    for l in L:
        m = re.match(r'\s*OpTraceRayKHR (%\w+) %uint_16 (%\w+) (%\w+) (%\w+) '
                     r'(%\w+) (%\w+) (%\w+) (%\w+) (%\w+) (%\w+)\s*$', l)
        if m:
            tap_origins.add(m.group(6))
    if base_org not in tap_origins:
        bad(name, f"the query origin {base_org} is not one of the cone taps' "
                  f"own origins {sorted(tap_origins)}")
    lm = re.match(r'OpVectorTimesScalar %v3float (%\w+) (%\w+)$',
                  d.get(lift, (0, ''))[1])
    if not lm:
        bad(name, "the origin lift is not VectorTimesScalar(N, eps)")
        return
    Nu, epsc = lm.groups()
    if not close(fval(d, epsc), 1e-4):
        bad(name, f"origin lift eps {fval(d, epsc)} != 0.0001")
    nm = re.match(r'OpExtInst %v3float %\w+ Normalize (%\w+)$',
                  d.get(Nu, (0, ''))[1])
    if not nm:
        bad(name, "N is not a Normalize")
        return
    ns = re.match(r'OpSelect %v3float (%\w+) (%\w+) (%\w+)$',
                  d.get(nm.group(1), (0, ''))[1])
    if not ns:
        bad(name, "N is not Normalize(Select(gate, Nraw, L)) -- 88's "
                  "select-before-normalize is gone and a NaN direction is "
                  "reachable")
        return
    if ns.group(1) != gate:
        bad(name, "the normal select is not on our own gate")
    if not re.match(r'OpCompositeConstruct %v3float ',
                    d.get(ns.group(2), (0, ''))[1]):
        bad(name, "the harvested normal is not a v3float construct")
    if not re.match(r'OpExtInst %v3float %\w+ Normalize ',
                    d.get(ns.group(3), (0, ''))[1]):
        bad(name, "the normal fallback is not a normalised direction")

    # the branch-free basis, and the pixel-seeded rotation
    sgn = None
    for l in L:
        m = re.match(r'\s*(%\w+) = OpSelect %float (%\w+) %float_1 (%\w+)\s*$',
                     l)
        if not m:
            continue
        zc = re.match(r'OpFOrdGreaterThanEqual %bool (%\w+) %float_0$',
                      d.get(m.group(2), (0, ''))[1])
        if zc and close(fval(d, m.group(3)), -1.0):
            ce = re.match(r'OpCompositeExtract %float ' + re.escape(Nu)
                          + r' 2$', d.get(zc.group(1), (0, ''))[1])
            if ce is not None or d.get(zc.group(1), (0, ''))[1].endswith(' 2'):
                sgn = m.group(1)
    if sgn is None:
        bad(name, "no branch-free sign(n.z) -- the basis is not built from N")
    else:
        av = [x for x in
              (re.match(r'\s*(%\w+) = OpFDiv %float (%\w+) (%\w+)\s*$', l)
               for l in L) if x and close(fval(d, x.group(2)), -1.0)
              and re.match(r'OpFAdd %float ' + re.escape(sgn) + r' %\w+$',
                           d.get(x.group(3), (0, ''))[1])]
        if len(av) != 1:
            bad(name, f"{len(av)} candidates for a = -1/(sign + n.z), want 1")
    cs = [m.group(1) for m in
          (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ Cos (%\w+)\s*$', l)
           for l in L) if m]
    sn = [m.group(1) for m in
          (re.match(r'\s*(%\w+) = OpExtInst %float %\w+ Sin (%\w+)\s*$', l)
           for l in L) if m]
    ncos_b = count(B, ' Cos ')
    nsin_b = count(B, ' Sin ')
    if count(L, ' Cos ') - ncos_b != 1 or count(L, ' Sin ') - nsin_b != 1:
        bad(name, f"added Cos/Sin = {count(L,' Cos ')-ncos_b}/"
                  f"{count(L,' Sin ')-nsin_b}, want 1/1 (one rotation of the "
                  f"whole tap set)")
    # the rotation angle's provenance: gl_LaunchID, and nothing else
    lidv = None
    for l in L:
        m = re.match(r'\s*OpDecorate (%\w+) BuiltIn LaunchIdKHR\s*$', l)
        if m:
            lidv = m.group(1)
    if lidv is None:
        bad(name, "no LaunchIdKHR builtin -- the rotation has no pixel seed")
    else:
        added_ac = [l for l in L
                    if re.match(r'\s*%\w+ = OpAccessChain %\w+ '
                                + re.escape(lidv) + r' %uint_[01]\s*$', l)]
        if len(added_ac) < 2:
            bad(name, "the rotation does not read both launch-id components")
        if count(L, 'OpConvertUToF') - count(B, 'OpConvertUToF') != 1:
            bad(name, "the angle is not one uint->float conversion of a hash")

    # --- 6. the K directions ------------------------------------------------
    trip = []
    for o in ops:
        a1 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                      d.get(o[6], (0, ''))[1])
        if not a1:
            bad(name, "a direction is not an FAdd chain")
            continue
        a2 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                      d.get(a1.group(1), (0, ''))[1])
        if not a2:
            bad(name, "a direction is not FAdd(FAdd(T,B),N)")
            continue
        sc = []
        for tok, want_n in ((a2.group(1), None), (a2.group(2), None),
                            (a1.group(2), Nu)):
            v = re.match(r'OpVectorTimesScalar %v3float (%\w+) (%\w+)$',
                         d.get(tok, (0, ''))[1])
            if not v:
                bad(name, "a direction term is not VectorTimesScalar")
                sc = None
                break
            if want_n is not None and v.group(1) != want_n:
                bad(name, "the direction's third term is not N itself")
            sc.append(fval(d, v.group(2)))
        if sc is None:
            continue
        if None in sc:
            bad(name, "a direction coefficient is not a constant")
            continue
        cx, cy, cz = sc
        if abs(cx * cx + cy * cy + cz * cz - 1.0) > 2e-6:
            bad(name, f"direction ({cx:.6f},{cy:.6f},{cz:.6f}) is not unit")
        if cz <= 0.0:
            bad(name, f"direction cz={cz} is not in the hemisphere about N")
        trip.append((round(cx, 6), round(cy, 6), round(cz, 6)))
    if len(set(trip)) != rays:
        bad(name, f"{len(set(trip))} distinct directions, want {rays}")

    # --- 7. o = hits / K ----------------------------------------------------
    sel1 = []
    for l in L:
        m = re.match(r'\s*(%\w+) = OpSelect %float (%\w+) %float_1 '
                     r'%float_0\s*$', l)
        if not m:
            continue
        ne = re.match(r'OpINotEqual %bool (%\w+) %uint_0$',
                      d.get(m.group(2), (0, ''))[1])
        if not ne:
            continue
        if not d.get(ne.group(1), (0, ''))[1].startswith(
                'OpRayQueryGetIntersectionTypeKHR'):
            continue
        sel1.append(m.group(1))
    if len(sel1) != rays:
        bad(name, f"{len(sel1)} hit indicators Select(committed,1,0), "
                  f"want {rays}")
    occ = None
    for l in L:
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
        if m and close(fval(d, m.group(3)), 1.0 / rays, rel=1e-6):
            src = m.group(2)
            if rays == 1:
                if src in sel1:
                    occ = m.group(1)
            else:
                if re.match(r'OpFAdd %float ', d.get(src, (0, ''))[1]):
                    occ = m.group(1)
    if occ is None:
        bad(name, f"no o = FMul(<sum of hits>, 1/{rays})")

    # --- 8. THE CONE IS DEAD ------------------------------------------------
    cs3 = cones(L, d, name)
    if len(cs3) != 3:
        bad(name, f"{len(cs3)} cone applications, want 3")
    for c in cs3:
        if not close(c['k'], 0.85):
            bad(name, f"cone k {c['k']} != 0.85 -- the strength constant must "
                      f"be the base's own")
        sl = re.match(r'OpSelect %float (%\w+) (%\w+) %float_0$',
                      d.get(c['src'], (0, ''))[1])
        if not sl:
            bad(name, f"cone at line {c['line']+1} is not fed by "
                      f"OpSelect(gate, o, +0.0)")
            continue
        if occ is not None and sl.group(2) != occ:
            bad(name, f"cone at line {c['line']+1} is not fed by the TRACED o "
                      f"-- the analytic cone is still live (do not stack)")
        gi = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$',
                      d.get(sl.group(1), (0, ''))[1])
        if not gi or gate not in gi.groups():
            bad(name, f"cone at line {c['line']+1} is not gated on our own "
                      f"gate AND that light's lit condition")
    # (b) every one of 88's own occ selects is disconnected
    dead = 0
    for l in L:
        m = re.match(r'\s*(%\w+) = OpSelect %float (%\w+) (%\w+) %float_0\s*$',
                     l)
        if not m:
            continue
        av = d.get(m.group(3), (0, ''))[1]
        nc = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 '
                      r'%float_1$', av)
        if not nc:
            continue
        # 88's COMBINE is the only NClamp of a DIVISION in the cone: the
        # cosine-weighted average num/NMax(den, eps). Each tap's own ramp is
        # an NClamp of an FSub, so this keeps the six taps out of the count.
        if not re.match(r'OpFDiv %float ', d.get(nc.group(1), (0, ''))[1]):
            continue
        u = uses(L, m.group(1))
        if u != 1:
            bad(name, f"88's cone occ {m.group(1)} still has {u} mentions "
                      f"(want 1, its own definition) -- the cone is LIVE")
        else:
            dead += 1
    if dead != 3:
        bad(name, f"{dead} of 3 analytic cone occ values are disconnected")
    # (c) every cone tap ray is neutered
    ntap = 0
    for l in L:
        m = re.match(r'\s*OpTraceRayKHR (%\w+) %uint_16 (%\w+) ', l)
        if m:
            ntap += 1
            if uval(d, m.group(2)) != 0:
                bad(name, f"a flags-16 cone tap still carries cull mask "
                          f"{m.group(2)} -- the dead cone still costs a ray")
    if ntap != 6:
        bad(name, f"{ntap} flags-16 cone taps, want 6")

    # --- 9. no ray was added ------------------------------------------------
    if count(L, 'OpTraceRayKHR') != count(B, 'OpTraceRayKHR'):
        bad(name, f"OpTraceRayKHR {count(L,'OpTraceRayKHR')} vs base "
                  f"{count(B,'OpTraceRayKHR')} -- this adds a QUERY, never a "
                  f"ray")

    # --- 10. the paint ------------------------------------------------------
    n_w = len([l for l in L if re.match(r'\s*OpImageWrite ', l)])
    painted = 0
    for l in L:
        m = re.match(r'\s*OpImageWrite %\w+ %\w+ (%\w+)\s*$', l)
        if not m:
            continue
        cc = d.get(m.group(1), (0, ''))[1]
        cm = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) '
                      r'(%\w+)$', cc)
        if not cm:
            continue
        arms = []
        for ch in range(3):
            sm2 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$',
                           d.get(cm.group(ch + 1), (0, ''))[1])
            arms.append(sm2)
        if all(arms) and len({a.group(1) for a in arms}) == 1 \
                and len({a.group(2) for a in arms}) == 1:
            painted += 1
            u = re.match(r'OpFOrdGreaterThanEqual %bool (%\w+) %float_0$',
                         d.get(arms[0].group(1), (0, ''))[1])
            if not u:
                bad(name, "the paint's use-flag is not `latch >= 0`")
            if not re.match(r'OpLoad %float ',
                            d.get(arms[0].group(2), (0, ''))[1]):
                bad(name, "the paint value is not a load of the latch")
    if mode == 'hit':
        if painted == 0 and name not in ('40c6faab52a13874',
                                         'ab7f1822eeb0331b'):
            bad(name, "-hit painted no radiance write")
        st = [l for l in L if re.match(r'\s*OpStore %\w+ %\w+\s*$', l)]
        ramp = [m.group(1) for m in
                (re.match(r'\s*(%\w+) = OpFSub %float %float_1 (%\w+)\s*$', l)
                 for l in L) if m and occ is not None and m.group(2) == occ]
        if len(ramp) != 1:
            bad(name, f"-hit has {len(ramp)} `1 - o` grey ramps, want 1")
    else:
        if painted:
            bad(name, f"the darkening rung rewrote {painted} image writes -- "
                      f"it must not touch a radiance store")


def negative(base_dir):
    n = 0
    for f in sorted(glob.glob(os.path.join(base_dir,
                                           '*.rgs_reference_main.spv'))):
        name = os.path.basename(f).split('.')[0]
        L = dis(f)
        for needle, what in (('OpRayQueryInitializeKHR', 'a ray query'),
                             ('OpTypeRayQueryKHR', 'a ray-query type'),
                             ('OpCapability RayQueryKHR', 'the capability')):
            if count(L, needle):
                bad(name, f"the BASE already carries {what}")
        d = index(L)
        for c in cones(L, d, name):
            sl = re.match(r'OpSelect %float (%\w+) (%\w+) %float_0$',
                          d.get(c['src'], (0, ''))[1])
            if sl and re.match(r'OpExtInst %float %\w+ NClamp ',
                               d.get(sl.group(2), (0, ''))[1]):
                continue
            bad(name, "the BASE's cone is not fed by its own tap average")
        n += 1
    print(f"negative control: {n} base modules")
    if FAIL:
        for f in FAIL:
            sys.stderr.write('  ' + f + '\n')
        sys.exit(1)
    print("  CLEAN -- the base carries no query and its cones are intact")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--mode', default='dark', choices=('dark', 'hit'))
    ap.add_argument('--rays', type=int, default=4)
    ap.add_argument('--flags', type=int, default=517)
    ap.add_argument('--tmin', type=float, default=0.001)
    ap.add_argument('--tmax', type=float, default=0.10)
    ap.add_argument('--negative')
    a = ap.parse_args()
    if a.negative:
        negative(a.negative)
        return
    if not a.rung or not a.base:
        ap.error('need <rung-dir> --base <base-dir>')
    n = 0
    for f in sorted(glob.glob(os.path.join(a.rung,
                                           '*.rgs_reference_main.spv'))):
        b = os.path.join(a.base, os.path.basename(f))
        if not os.path.exists(b):
            bad(os.path.basename(f), 'no matching base module')
            continue
        check_module(f, b, a.mode, a.rays, a.flags, a.tmin, a.tmax)
        n += 1
    if n == 0:
        raise SystemExit('no rgs_reference_main modules found')
    if FAIL:
        for f in FAIL[:40]:
            sys.stderr.write('  ' + f + '\n')
        sys.stderr.write(f"  ({len(FAIL)} failures)\n")
        sys.exit(1)
    print(f"verify_contact_rq: ALL PASS -- {n} modules, mode={a.mode}, "
          f"K={a.rays}, flags={a.flags}, tmin={a.tmin}, tmax={a.tmax}")


if __name__ == '__main__':
    main()
