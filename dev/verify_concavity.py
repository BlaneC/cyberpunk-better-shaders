#!/usr/bin/env python3
"""verify_concavity.py <rung-dir> --base <base-dir> --family fold|crevice
                       [--mode dark|hit] [--rays K] [--flags N]
                       [--tmin T] [--tmax M] [--painted N]
   verify_concavity.py --negative <base-dir> --family fold|crevice

Re-derives the 104 splice from the SHIPPED .spv bytes. Never from the
patcher's reports, never from a byte diff (42: "a byte diff is not coverage"),
and the path-loop counter (90 sec 1) is re-derived HERE by a second
implementation of the same structural rule, so a pass cannot merely mean the
patcher agreed with itself. Ids do not survive assemble/disassemble (40 sec 8),
so every check is structural or by resolved constant VALUE.

THE BASE ALREADY CONTAINS RAY QUERIES. The standing selection carries 101's
earglow-rq3 (three queries) on 10 of 12 permutations, so nothing here may
assert an ABSOLUTE query count: every count is asserted as base + K, and our
own queries are identified as the unique group sharing ONE query object whose
tmax resolves to this family's reach.

Proven per patched rgs_reference_main permutation (12 of 12):

  1  RayQueryKHR capability + SPV_KHR_ray_query extension; exactly one
     OpTypeRayQueryKHR and one Function pointer to it; the Function ray-query
     VARIABLE count is base + 1;
  2  Initialize / Proceed / GetIntersectionType are each base + K, and ZERO
     getters of any other kind were ADDED -- including GetIntersectionTKHR:
     this asks a BOOLEAN, and 101's glow (which does read t) must be
     untouched, so its own count must be unchanged, not zero;
  3  our K queries share one object, one AS, one cull mask, one origin, one
     tmin and one tmax; flags are the constant 517 = Opaque |
     TerminateOnFirstHit | SkipAABBs checked bit by bit, with CullFront
     (0x20 -- 101's THICKNESS word) and CullBack (0x10) BOTH clear; tmin
     0.001 and tmax this family's reach;
  4  the cull mask is OpSelect(gate, 39, 0) and the gate is
       AND(AND(AND(AND(cls != 1, cls != 4), counter == 0), <material>), <N ok>)
     with <class> a slot-5 `>>5` word (88 sec 4) and <counter> the PATH-loop
     counter re-derived here (90 sec 1), and <material> per family:
       fold    : max3(F0) < 0.09        (80/81's dielectric clause)
       crevice : rough > 0.60 AND metallic < 0.10
     where F0 and metallic come from ONE lerp(0.04, albedo, metallic) triple
     and rough is the module's own NMin(NMax(r, 0.04), 1);
  5  origin = FAdd(<a cone tap's own origin>, VTS(N, 1e-4)), and
     N = Normalize(Select(gate, <the cone's harvested normal>, <its L>));
  6  the branch-free (Duff et al.) basis built from N, rotated by Cos/Sin of
     an angle derived ONLY from gl_LaunchID (+1 Cos, +1 Sin, +1 ConvertUToF
     over the base -- frame-stable, 98 sec 12.6);
  7  K unit directions in the hemisphere about N, all distinct;
  8  o = FMul(<sum of K Select(committed,1,0)>, 1/K), and the family's own
     weight: fold multiplies o by NClamp((rough*rough - 0.10)*5, 0, 1) --
     81's ramp on alpha, verbatim -- crevice does not weight o at all;
  9  THE ANALYTIC CONE IS STILL ALIVE, which is the opposite of what 102
     proves: all three of 88's cones still compute FMul(<their own
     cosine-weighted combine>, 0.85), all six flags-16 tap rays still carry a
     NON-ZERO cull mask, and OpTraceRayKHR is unchanged from the base. Our
     gate is class != 1 and the cone's is class == 1, so nothing double-counts
     and nothing was deleted;
 10  the application: exactly 3 OpSelect(AND(gate, <that light's lit bool>),
     o_eff, +0.0) -- one per cone -- each feeding one factor chain per
     DISTINCT channel strength (1 for fold, 3 for crevice) of the form
     FMul(node, FSub(1, FMul(oc, K_c))), with K_c equal by VALUE to
     1 - tint_c*(1 - 0.85); each cone's three per-channel consumers read the
     factor for their own channel, and the CHANNEL ORDER is proved
     structurally by a common vector whose components 0/1/2 are reached from
     consumers 0/1/2 (the light-colour load);
 11  hit: every painted OpImageWrite texel is CompositeConstruct(Select(u,p,x),
     Select(u,p,y), Select(u,p,z), w) over one Function latch, alpha
     untouched; dark: no image write is rewritten at all.

--negative asserts the base carries none of it.
"""
import argparse, glob, math, os, re, subprocess, sys

UNIT_ONE = ('%half_0x1p_0', '%float_1')
GETTERS_OTHER = (
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

K_STRENGTH = 0.85
CLOTH_F0MAX = 0.09
CLOTH_A0 = 0.10
CLOTH_RAMP = 5.0
CREV_RMIN = 0.60
CREV_METMAX = 0.10
DIRT_TINT = (0.55, 0.45, 0.35)
FAM_TMAX = {'fold': 0.10, 'crevice': 0.05}
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


def consumers(lines, tok, skip):
    out = []
    for i, l in enumerate(lines):
        if i == skip:
            continue
        if re.search(re.escape(tok) + r'(?![0-9A-Za-z_])', l):
            out.append(i)
    return out


def channel_k(family):
    if family == 'fold':
        return (K_STRENGTH,) * 3
    return tuple(1.0 - t * (1.0 - K_STRENGTH) for t in DIRT_TINT)


def path_counter(lines, d, name):
    """90 sec 1's PATH-loop counter, re-derived independently of the patcher.

    Among counted loops `Op[SU]LessThan(x + 1, bound)` on a back edge whose
    body traces rays, the path loop is the one whose header seeds exactly 3
    fp phis with 1.0 (the RGB throughput); the sample loop seeds none."""
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


def cones(lines, d):
    """88's three cavity cones, re-found by their FULL application shape:
    FMul(OpSelect(gate, NClamp(FDiv(num, den), 0, 1), +0.0), <const k>)
    feeding FSub(1, that). The +0.0 false arm is 88's identity guard, and the
    clamped QUOTIENT is 88's own cosine-weighted combine -- 104's own factor
    deliberately mirrors the outer algebra (Select-then-FMul-then-FSub) and is
    excluded HERE, by the inner NClamp(FDiv), so that a build which fed our
    traced o into a cone's own strength multiply (102's REPLACE, --decoy kill)
    finds ZERO cones and fails, instead of finding ours and passing."""
    out = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        occk, src, kc = m.groups()
        if fval(d, kc) is None:
            continue
        sl = re.match(r'OpSelect %float (%\w+) (%\w+) %float_0$',
                      d.get(src, (0, ''))[1])
        if not sl:
            continue
        nc = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 '
                      r'%float_1$', d.get(sl.group(2), (0, ''))[1])
        if not nc or not re.match(r'OpFDiv %float ',
                                  d.get(nc.group(1), (0, ''))[1]):
            continue
        fac = None
        for x in lines:
            fm = re.match(r'\s*(%\w+) = OpFSub %float %float_1 '
                          + re.escape(occk) + r'\s*$', x)
            if fm:
                fac = fm.group(1)
        if fac is None:
            continue
        out.append(dict(line=i, occk=occk, src=src, k=fval(d, kc), fac=fac,
                        combine=sl.group(2)))
    return out


def f0_triple_of(d, ids):
    """(f0r, f0g, f0b) -> the shared metallic id, or None. 80 sec 2.4's
    idiom: F0_c = FAdd(FMul(FAdd(albedo_c, -0.04), metallic), +0.04)."""
    mets = set()
    for t in ids:
        a = re.match(r'OpFAdd %float (%\w+) %float_0_0399999991$',
                     d.get(t, (0, ''))[1])
        if not a:
            return None
        mm = re.match(r'OpFMul %float (%\w+) (%\w+)$',
                      d.get(a.group(1), (0, ''))[1])
        if not mm:
            return None
        got = None
        for z, mt in (mm.groups(), mm.groups()[::-1]):
            if re.match(r'OpFAdd %float %\w+ %float_n0_0399999991$',
                        d.get(z, (0, ''))[1]):
                got = mt
                break
        if got is None:
            return None
        mets.add(got)
    return mets.pop() if len(mets) == 1 else None


def clamped_rough(d, tok):
    """tok must be NMin(NMax(x, 0.04), 1) -- the module's own roughness."""
    mn = re.match(r'OpExtInst %float %\w+ NMin (%\w+) %float_1$',
                  d.get(tok, (0, ''))[1])
    if not mn:
        return None
    mx = re.match(r'OpExtInst %float %\w+ NMax (%\w+) %float_0_0399999991$',
                  d.get(mn.group(1), (0, ''))[1])
    return mx.group(1) if mx else None


def upstream_extracts(d, tok, depth=8):
    """{vector id: {component indices reachable}} within `depth` operand hops
    upstream of tok. Used only to prove CHANNEL ORDER."""
    seen, frontier, out = set(), [tok], {}
    for _ in range(depth):
        nxt = []
        for t in frontier:
            if t in seen or t not in d:
                continue
            seen.add(t)
            dd = d[t][1]
            m = re.match(r'OpCompositeExtract %float (%\w+) ([012])$', dd)
            if m:
                out.setdefault(m.group(1), set()).add(int(m.group(2)))
            nxt.extend(re.findall(r'%\w+', dd)[1:])
        frontier = nxt
    return out


def check_module(path, base_path, family, mode, rays, flags, tmin, tmax):
    name = os.path.basename(path).split('.')[0]
    L, B = dis(path), dis(base_path)
    d, db = index(L), index(B)
    kch = channel_k(family)
    korder = []
    for v in kch:
        if not any(close(v, w, 1e-6) for w in korder):
            korder.append(v)

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
    qvs = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = OpVariable ' + re.escape(ptr[0])
                     + r' Function\s*$', l) for l in L) if m]
    nb_var = 0
    brqt = [m.group(1) for m in
            (re.match(r'\s*(%\w+) = OpTypeRayQueryKHR\s*$', l) for l in B) if m]
    if brqt:
        bptr = [m.group(1) for m in
                (re.match(r'\s*(%\w+) = OpTypePointer Function '
                          + re.escape(brqt[0]) + r'\s*$', l) for l in B) if m]
        if bptr:
            nb_var = len([1 for l in B
                          if re.match(r'\s*%\w+ = OpVariable '
                                      + re.escape(bptr[0]) + r' Function\s*$',
                                      l)])
    if len(qvs) != nb_var + 1:
        bad(name, f"{len(qvs)} ray-query variables, base has {nb_var} -- this "
                  f"splice declares exactly one more")

    # --- 2. counts are BASE + K, never absolute ----------------------------
    n_i, n_p = count(L, 'OpRayQueryInitializeKHR'), count(L, 'OpRayQueryProceedKHR')
    n_t = count(L, 'OpRayQueryGetIntersectionTypeKHR')
    b_i, b_p = count(B, 'OpRayQueryInitializeKHR'), count(B, 'OpRayQueryProceedKHR')
    b_t = count(B, 'OpRayQueryGetIntersectionTypeKHR')
    if (n_i - b_i, n_p - b_p, n_t - b_t) != (rays, rays, rays):
        bad(name, f"added Initialize/Proceed/Type = "
                  f"{(n_i-b_i, n_p-b_p, n_t-b_t)}, want {rays} each")
    if count(L, 'OpRayQueryGetIntersectionTKHR') != \
            count(B, 'OpRayQueryGetIntersectionTKHR'):
        bad(name, "the committed-T getter count changed -- this asks a "
                  "BOOLEAN, and 101's glow (which reads t) must be untouched")
    for g in GETTERS_OTHER:
        if count(L, g) != count(B, g):
            bad(name, f"{g} count changed")

    # --- 3. OUR queries: the group sharing one object at this family's reach
    groups = {}
    for l in L:
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        if not m:
            continue
        o = m.group(1).split()
        if len(o) != 8:
            bad(name, f"Initialize has {len(o)} operands, want 8")
            return
        groups.setdefault(o[0], []).append(o)
    mine = [(q, ops) for q, ops in groups.items()
            if len(ops) == rays and all(close(fval(d, x[7]), tmax)
                                        for x in ops)]
    if len(mine) != 1:
        bad(name, f"{len(mine)} query objects issue exactly {rays} queries at "
                  f"tmax {tmax} -- our group is not identifiable")
        return
    qv, ops = mine[0]
    if qv not in qvs:
        bad(name, "our queries do not use a declared Function ray-query var")
    for k, tag in ((1, 'acceleration structure'), (2, 'ray flags'),
                   (3, 'cull mask'), (4, 'origin'), (5, 'tmin'), (7, 'tmax')):
        if len({o[k] for o in ops}) != 1:
            bad(name, f"the {rays} queries do not share one {tag}")
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
    for l in L:
        m = re.match(r'\s*(%\w+) = OpRayQueryGetIntersectionTypeKHR %uint '
                     + re.escape(qv) + r' (%\w+)\s*$', l)
        if m and uval(d, m.group(2)) != 1:
            bad(name, "a type getter does not read the COMMITTED intersection")

    # --- 4. the gate --------------------------------------------------------
    pc = path_counter(L, d, name)
    sm = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$',
                  d.get(ops[0][3], (0, ''))[1])
    if not sm:
        bad(name, "the cull mask is not an OpSelect")
        return
    gate = sm.group(1)
    if uval(d, sm.group(2)) != 39 or uval(d, sm.group(3)) != 0:
        bad(name, f"cull mask select yields {uval(d, sm.group(2))}/"
                  f"{uval(d, sm.group(3))}, want 39/0")

    def andpair(tok, what):
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$',
                     d.get(tok, (0, ''))[1])
        if not m:
            bad(name, f"{what} is not an OpLogicalAnd")
        return m.groups() if m else (None, None)

    g_cm, g_nok = andpair(gate, "the gate")
    if g_nok and not re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$',
                              d.get(g_nok, (0, ''))[1]):
        bad(name, "the gate's last conjunct is not the non-degenerate normal "
                  "test")
    g_cp, g_mat = andpair(g_cm, "the gate's first conjunct")
    g_cls, g_p0 = andpair(g_cp, "the class+counter conjunct")
    # class != 1 AND class != 4, off ONE `>>5` word
    ne1, ne4 = andpair(g_cls, "the class conjunct")
    clsw = set()
    for t, want in ((ne1, 1), (ne4, 4)):
        m = re.match(r'OpINotEqual %bool (%\w+) (%\w+)$', d.get(t, (0, ''))[1])
        if not m or uval(d, m.group(2)) != want:
            bad(name, f"the class conjunct is not INotEqual(x, {want}) -- "
                      f"80 sec 2.3 excludes class 1 (skin) and class 4 (hair)")
            continue
        cd = d.get(m.group(1), (0, ''))[1]
        if not re.match(r'OpShiftRightLogical %uint %\w+ %uint_5$', cd):
            bad(name, f"the class operand is not a slot-5 `>>5` material word "
                      f"(88 sec 4) -- got {cd}")
        clsw.add(m.group(1))
    if len(clsw) > 1:
        bad(name, "the two class tests read DIFFERENT material words")
    c = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(g_p0, (0, ''))[1])
    if not c or uval(d, c.group(2)) != 0:
        bad(name, "the counter conjunct is not IEqual(x, 0)")
    elif pc is not None and c.group(1) != pc:
        bad(name, f"the counter operand is {c.group(1)}, but the PATH-loop "
                  f"counter is {pc} (90 sec 1)")

    # --- 4b. the family's material clause -----------------------------------
    rough = met = None
    if family == 'fold':
        lt = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)$',
                      d.get(g_mat, (0, ''))[1])
        if not lt or not close(fval(d, lt.group(2)), CLOTH_F0MAX):
            bad(name, f"the fold material clause is not max3(F0) < "
                      f"{CLOTH_F0MAX} (80/81's dielectric clause)")
        else:
            m3 = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$',
                          d.get(lt.group(1), (0, ''))[1])
            m01 = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$',
                           d.get(m3.group(1), (0, ''))[1]) if m3 else None
            if not m01:
                bad(name, "max3(F0) is not NMax(NMax(r, g), b)")
            else:
                trio = (m01.group(1), m01.group(2), m3.group(2))
                met = f0_triple_of(d, trio)
                if met is None:
                    bad(name, "the three F0 operands are not one "
                              "lerp(0.04, albedo, metallic) triple sharing "
                              "ONE metallic")
    else:
        a1, a2 = andpair(g_mat, "the crevice material clause")
        gt = re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$',
                      d.get(a1, (0, ''))[1])
        lt = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)$',
                      d.get(a2, (0, ''))[1])
        if not gt or not close(fval(d, gt.group(2)), CREV_RMIN):
            bad(name, f"the crevice roughness clause is not rough > "
                      f"{CREV_RMIN}")
        else:
            rough = gt.group(1)
            if clamped_rough(d, rough) is None:
                bad(name, "the roughness operand is not the module's own "
                          "NMin(NMax(r, 0.04), 1)")
        if not lt or not close(fval(d, lt.group(2)), CREV_METMAX):
            bad(name, f"the crevice metallic clause is not metallic < "
                      f"{CREV_METMAX}")
        else:
            met = lt.group(1)
            # the metallic must be THE metallic: the one an F0 lerp triple uses
            trip = None
            for i, l in enumerate(L):
                mm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
                if mm and met in (mm.group(2), mm.group(3)):
                    other = mm.group(3) if mm.group(2) == met else mm.group(2)
                    if re.match(r'OpFAdd %float %\w+ %float_n0_0399999991$',
                                d.get(other, (0, ''))[1]):
                        trip = mm.group(1)
                        break
            if trip is None:
                bad(name, "the metallic tested is not the lerp weight of an "
                          "F0 = lerp(0.04, albedo, metallic) triple")

    # --- 5. origin, normal --------------------------------------------------
    oa = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                  d.get(ops[0][4], (0, ''))[1])
    if not oa:
        bad(name, "the ray origin is not <cone origin> + N*eps")
        return
    base_org, lift = oa.groups()
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

    # --- 6. the basis and the pixel-seeded rotation -------------------------
    sgn = None
    for l in L:
        m = re.match(r'\s*(%\w+) = OpSelect %float (%\w+) %float_1 (%\w+)\s*$',
                     l)
        if not m:
            continue
        zc = re.match(r'OpFOrdGreaterThanEqual %bool (%\w+) %float_0$',
                      d.get(m.group(2), (0, ''))[1])
        if zc and close(fval(d, m.group(3)), -1.0):
            if d.get(zc.group(1), (0, ''))[1] == f'OpCompositeExtract %float {Nu} 2':
                sgn = m.group(1)
    if sgn is None:
        bad(name, "no branch-free sign(n.z) off OUR N -- the basis is not "
                  "built from the surface normal")
    else:
        av = [x for x in
              (re.match(r'\s*(%\w+) = OpFDiv %float (%\w+) (%\w+)\s*$', l)
               for l in L) if x and close(fval(d, x.group(2)), -1.0)
              and re.match(r'OpFAdd %float ' + re.escape(sgn) + r' %\w+$',
                           d.get(x.group(3), (0, ''))[1])]
        if len(av) != 1:
            bad(name, f"{len(av)} candidates for a = -1/(sign + n.z), want 1")
    if count(L, ' Cos ') - count(B, ' Cos ') != 1 or \
            count(L, ' Sin ') - count(B, ' Sin ') != 1:
        bad(name, f"added Cos/Sin = {count(L,' Cos ')-count(B,' Cos ')}/"
                  f"{count(L,' Sin ')-count(B,' Sin ')}, want 1/1")
    lidv = None
    for l in L:
        m = re.match(r'\s*OpDecorate (%\w+) BuiltIn LaunchIdKHR\s*$', l)
        if m:
            lidv = m.group(1)
    if lidv is None:
        bad(name, "no LaunchIdKHR builtin -- the rotation has no pixel seed")
    else:
        ac = [l for l in L
              if re.match(r'\s*%\w+ = OpAccessChain %\w+ ' + re.escape(lidv)
                          + r' %uint_[01]\s*$', l)]
        bac = [l for l in B
               if re.match(r'\s*%\w+ = OpAccessChain %\w+ ' + re.escape(lidv)
                           + r' %uint_[01]\s*$', l)]
        if len(ac) - len(bac) != 2:
            bad(name, "the rotation does not add exactly two launch-id reads")
        if count(L, 'OpConvertUToF') - count(B, 'OpConvertUToF') != 1:
            bad(name, "the angle is not one uint->float conversion of a hash")

    # --- 7. the K directions ------------------------------------------------
    trip = []
    for o in ops:
        a1 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                      d.get(o[6], (0, ''))[1])
        a2 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$',
                      d.get(a1.group(1), (0, ''))[1]) if a1 else None
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
        if sc is None or None in sc:
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

    # --- 8. o = hits / K, and the family's weight ---------------------------
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
        g = d.get(ne.group(1), (0, ''))[1]
        if g.startswith('OpRayQueryGetIntersectionTypeKHR %uint ' + qv):
            sel1.append(m.group(1))
    if len(sel1) != rays:
        bad(name, f"{len(sel1)} hit indicators Select(committed,1,0) on our "
                  f"query object, want {rays}")
    occ = None
    for l in L:
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
        if m and close(fval(d, m.group(3)), 1.0 / rays, rel=1e-6):
            src = m.group(2)
            if (rays == 1 and src in sel1) or \
                    (rays > 1 and re.match(r'OpFAdd %float ',
                                           d.get(src, (0, ''))[1])):
                occ = m.group(1)
    if occ is None:
        bad(name, f"no o = FMul(<sum of hits>, 1/{rays})")
        return
    o_eff = occ
    if family == 'fold':
        cand = []
        for l in L:
            m = re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(occ)
                         + r' (%\w+)\s*$', l)
            if m:
                cand.append(m.groups())
        if len(cand) != 1:
            bad(name, f"{len(cand)} weights applied to o, want exactly 1 "
                      f"(81's roughness ramp)")
        else:
            o_eff, wr = cand[0]
            nc = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 '
                          r'%float_1$', d.get(wr, (0, ''))[1])
            mu = re.match(r'OpFMul %float (%\w+) (%\w+)$',
                          d.get(nc.group(1), (0, ''))[1]) if nc else None
            if not mu or not close(fval(d, mu.group(2)), CLOTH_RAMP):
                bad(name, f"the fold weight is not NClamp((alpha - a0) * "
                          f"{CLOTH_RAMP}, 0, 1) -- 81's ramp")
            else:
                su = re.match(r'OpFSub %float (%\w+) (%\w+)$',
                              d.get(mu.group(1), (0, ''))[1])
                if not su or not close(fval(d, su.group(2)), CLOTH_A0):
                    bad(name, f"the fold ramp does not start at alpha = "
                              f"{CLOTH_A0}")
                else:
                    sq = re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                  d.get(su.group(1), (0, ''))[1])
                    if not sq or sq.group(1) != sq.group(2):
                        bad(name, "alpha is not roughness*roughness")
                    elif clamped_rough(d, sq.group(1)) is None:
                        bad(name, "the fold ramp does not square the module's "
                                  "own NMin(NMax(r, 0.04), 1) roughness")
                    else:
                        rough = sq.group(1)
    else:
        for l in L:
            if re.match(r'\s*%\w+ = OpFMul %float ' + re.escape(occ)
                        + r' (%\w+)\s*$', l):
                m = re.match(r'\s*%\w+ = OpFMul %float %\w+ (%\w+)\s*$', l)
                if fval(d, m.group(1)) is None:
                    bad(name, "the crevice family must not weight o")

    # --- 9. THE ANALYTIC CONE IS STILL ALIVE (the opposite of 102) ---------
    cs3 = cones(L, d)
    if len(cs3) != 3:
        bad(name, f"{len(cs3)} LIVE analytic cone applications, want 3 -- 88's "
                  f"cone must survive intact here (this is not 102: our gate "
                  f"is class != 1, DISJOINT from the cone's, so replacing it "
                  f"silently deletes the shipped skin cavity term)")
    for c in cs3:
        if not close(c['k'], K_STRENGTH):
            bad(name, f"cone k {c['k']} != {K_STRENGTH}")
    # and OUR traced o must never be what a cone's strength multiplies
    for mine in {occ, o_eff}:
        for l in L:
            m = re.match(r'\s*%\w+ = OpFMul %float ' + re.escape(mine)
                         + r' (%\w+)\s*$', l)
            if m and close(fval(d, m.group(1)), K_STRENGTH):
                bad(name, "our traced o feeds a multiply by the cone's own "
                          "k = 0.85 -- that is 102's REPLACE")
    ntap = 0
    for l in L:
        m = re.match(r'\s*OpTraceRayKHR (%\w+) %uint_16 (%\w+) ', l)
        if m:
            ntap += 1
            if uval(d, m.group(2)) == 0:
                bad(name, "a flags-16 cone tap was neutered to cull mask 0 -- "
                          "the analytic cone must keep its own rays")
    if ntap != 6:
        bad(name, f"{ntap} flags-16 cone taps, want 6")
    if count(L, 'OpTraceRayKHR') != count(B, 'OpTraceRayKHR'):
        bad(name, f"OpTraceRayKHR {count(L,'OpTraceRayKHR')} vs base "
                  f"{count(B,'OpTraceRayKHR')} -- this adds a QUERY, never a "
                  f"ray")

    # --- 10. the application, per cone, per channel ------------------------
    ocs = []
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\w+) = OpSelect %float (%\w+) ' + re.escape(o_eff)
                     + r' %float_0\s*$', l)
        if not m:
            continue
        ga = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$',
                      d.get(m.group(2), (0, ''))[1])
        if not ga or gate not in ga.groups():
            bad(name, f"the application at line {i+1} is not gated on our "
                      f"gate AND that light's own lit condition")
            continue
        ocs.append(m.group(1))
    if len(ocs) != 3:
        bad(name, f"{len(ocs)} per-cone applications of o, want 3 (1 sun + 2 "
                  f"local lights)")
    cone_facs = {c['fac'] for c in cs3}
    for oc in ocs:
        chain = {}
        for l in L:
            m = re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(oc)
                         + r' (%\w+)\s*$', l)
            if not m:
                continue
            kv = fval(d, m.group(2))
            if kv is None:
                bad(name, "a strength operand is not a constant")
                continue
            f = None
            for x in L:
                fm = re.match(r'\s*(%\w+) = OpFSub %float %float_1 '
                              + re.escape(m.group(1)) + r'\s*$', x)
                if fm:
                    f = fm.group(1)
            if f is None:
                bad(name, f"K*o at {m.group(1)} does not feed 1 - K*o")
                continue
            prod = []
            for x in L:
                pm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) '
                              + re.escape(f) + r'\s*$', x)
                if pm:
                    prod.append(pm.groups())
            if len(prod) != 1:
                bad(name, f"{len(prod)} nodes scaled by the factor {f}, want 1")
                continue
            chain[round(kv, 6)] = (prod[0][0], prod[0][1])
        if len(chain) != len(korder):
            bad(name, f"{len(chain)} distinct channel strengths on one cone, "
                      f"want {len(korder)} ({'achromatic' if len(korder)==1 else 'tinted'})")
            continue
        for kv in korder:
            if not any(close(kv, x, 1e-5) for x in chain):
                bad(name, f"channel strength {kv:.6f} is missing -- the tint "
                          f"is not {DIRT_TINT}")
        nodes = {v[1] for v in chain.values()}
        if len(nodes) != 1:
            bad(name, "one cone's channel factors scale different nodes")
            continue
        node = nodes.pop()
        if node not in cone_facs:
            # the local-light shape: the node is the ONE consumer of a fac
            src = d.get(node, (0, ''))[1]
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', src)
            if not mm or not (set(mm.groups()) & cone_facs):
                bad(name, f"our factor scales {node}, which is neither a "
                          f"cone's fac nor the single consumer of one")
                continue
        # the three per-channel consumers, and the CHANNEL ORDER
        cons = []
        for i, l in enumerate(L):
            for kv, (sch, _n) in chain.items():
                m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)
                if m and sch in (m.group(2), m.group(3)) and \
                        m.group(1) not in [v[0] for v in chain.values()]:
                    other = m.group(3) if m.group(2) == sch else m.group(2)
                    cons.append((i, kv, other))
        cons.sort()
        if len(cons) != 3:
            bad(name, f"{len(cons)} per-channel consumers read our factors, "
                      f"want 3")
            continue
        for ch in range(3):
            if not close(cons[ch][1], kch[ch], 1e-5):
                bad(name, f"channel {ch} uses strength {cons[ch][1]:.6f}, "
                          f"want {kch[ch]:.6f} -- the tint is mis-ordered")
        # channel order proof: a common vector whose components 0/1/2 are
        # reachable upstream of consumers 0/1/2 (the light-colour load)
        sets = [upstream_extracts(d, cons[ch][2]) for ch in range(3)]
        common = set(sets[0]) & set(sets[1]) & set(sets[2])
        if not any(all(i in sets[i].get(V, set()) for i in range(3))
                   for V in common):
            bad(name, "no vector has components 0/1/2 reachable from channel "
                      "consumers 0/1/2 -- the R/G/B order is unproven")

    # --- 11. the paint ------------------------------------------------------
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
        arms = [re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$',
                         d.get(cm.group(ch + 1), (0, ''))[1])
                for ch in range(3)]
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
        ramp = [x for x in
                (re.match(r'\s*(%\w+) = OpFSub %float %float_1 (%\w+)\s*$', l)
                 for l in L) if x and x.group(2) == o_eff]
        if len(ramp) != 1:
            bad(name, f"-hit has {len(ramp)} `1 - o` grey ramps, want 1")
    else:
        if painted:
            bad(name, f"the darkening rung rewrote {painted} image writes -- "
                      f"it must not touch a radiance store")
    return painted


def negative(base_dir, family):
    n = 0
    tmax = FAM_TMAX[family]
    for f in sorted(glob.glob(os.path.join(base_dir,
                                           '*.rgs_reference_main.spv'))):
        name = os.path.basename(f).split('.')[0]
        L = dis(f)
        d = index(L)
        groups = {}
        for l in L:
            m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
            if m:
                o = m.group(1).split()
                groups.setdefault(o[0], []).append(o)
        for q, ops in groups.items():
            if all(close(fval(d, x[7]), tmax) for x in ops):
                bad(name, f"the BASE already issues queries at tmax {tmax}")
        cs = cones(L, d)
        if len(cs) != 3:
            bad(name, f"the BASE has {len(cs)} analytic cone applications, "
                      f"want 3 -- there is nothing here to preserve")
        for l in L:
            if re.match(r'\s*%\w+ = OpINotEqual %bool %\w+ %uint_4\s*$', l):
                bad(name, "the BASE already tests class != 4")
        n += 1
    print(f"negative control ({family}): {n} base modules")
    if FAIL:
        for f in FAIL:
            sys.stderr.write('  ' + f + '\n')
        sys.exit(1)
    print("  CLEAN -- the base carries no concavity query and its cones are "
          "intact")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--family', required=True, choices=sorted(FAM_TMAX))
    ap.add_argument('--mode', default='dark', choices=('dark', 'hit'))
    ap.add_argument('--rays', type=int, default=4)
    ap.add_argument('--flags', type=int, default=517)
    ap.add_argument('--tmin', type=float, default=0.001)
    ap.add_argument('--tmax', type=float, default=None)
    ap.add_argument('--painted', type=int, default=None,
                    help='assert this many painted radiance writes over the '
                         'whole set (-hit only)')
    ap.add_argument('--negative')
    a = ap.parse_args()
    tmax = a.tmax if a.tmax is not None else FAM_TMAX[a.family]
    if a.negative:
        negative(a.negative, a.family)
        return
    if not a.rung or not a.base:
        ap.error('need <rung-dir> --base <base-dir>')
    n = tot = 0
    for f in sorted(glob.glob(os.path.join(a.rung,
                                           '*.rgs_reference_main.spv'))):
        b = os.path.join(a.base, os.path.basename(f))
        if not os.path.exists(b):
            bad(os.path.basename(f), 'no matching base module')
            continue
        p = check_module(f, b, a.family, a.mode, a.rays, a.flags, a.tmin, tmax)
        tot += p or 0
        n += 1
    if n == 0:
        raise SystemExit('no rgs_reference_main modules found')
    if a.painted is not None and tot != a.painted:
        bad('-', f'{tot} painted radiance writes over the set, want '
                 f'{a.painted}')
    if FAIL:
        for f in FAIL[:40]:
            sys.stderr.write('  ' + f + '\n')
        sys.stderr.write(f"  ({len(FAIL)} failures)\n")
        sys.exit(1)
    print(f"verify_concavity: ALL PASS -- {n} modules, family={a.family}, "
          f"mode={a.mode}, K={a.rays}, flags={a.flags}, tmin={a.tmin}, "
          f"tmax={tmax}, painted={tot}")


if __name__ == '__main__':
    main()
