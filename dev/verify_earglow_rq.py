#!/usr/bin/env python3
"""verify_earglow_rq.py <rung-dir> --base <base-dir> --mode glow|hit
                        [--k K] [--wide W] [--wrap R]
                        [--flags N] [--tmin T] [--tmax M]
   verify_earglow_rq.py --negative <base-dir>

Re-derives the earglow-rq splice from the SHIPPED .spv bytes. Never from the
patcher's reports, never from a byte diff (42: "a byte diff is not coverage"),
and never by importing the patcher's own detectors -- the path-loop counter
(90 sec 1) is re-derived HERE, by a second implementation of the same
structural rule, so that a verifier passing cannot merely mean the patcher
agreed with itself. Ids do not survive the assemble/disassemble round trip
(40 sec 8), so every check below is structural or by resolved constant VALUE.

Proven per patched rgs_reference_main permutation:

  1  OpCapability RayQueryKHR + OpExtension "SPV_KHR_ray_query"; exactly one
     OpTypeRayQueryKHR; exactly one Function-storage ray query variable, and
     it sits inside the entry block's leading OpVariable run;
  2  the module's own SUN-NEE trace is re-found independently (flags 12, tmax
     10000, cull mask defined by OpSelect(cond, 0, 39)) and is unique;
  3  exactly one OpRayQueryInitializeKHR, and its acceleration structure,
     ray ORIGIN and ray DIRECTION are THE SAME SSA IDS as that trace's -- the
     query re-uses the engine's own offset hit position and its own
     cone-jittered sun direction, it does not reconstruct them;
  4  its ray flags are the constant 545 = OpaqueKHR |
     CullFrontFacingTrianglesKHR | SkipAABBsKHR, with CullBACK (0x10) NOT set
     and TerminateOnFirstHit (0x04) NOT set -- the second is what makes the
     COMMITTED intersection the CLOSEST one, i.e. the far wall rather than an
     arbitrary backface in range;
  5  tmin resolves to 0.0015 (71's min-t floor, now a traversal parameter) and
     tmax to 0.018;
  6  the cull mask is OpSelect(gate, 39, 0) and the gate is exactly
     (class-1 skin AND the trace's own backlit condition) AND (path counter
     == 0). The class operand is re-walked to an OpImageFetch through
     `& 0xFFFFFFE0 == 32`; the backlit operand must BE the condition of that
     trace's own cull-mask select; and the counter operand must BE the path
     loop's counter as re-derived here (90's throughput discriminator), which
     is what rejects a build made with the legacy helper;
  7  exactly one OpRayQueryProceedKHR (no traversal loop was spliced in), one
     GetIntersectionTypeKHR on the COMMITTED intersection, one
     GetIntersectionTKHR on the COMMITTED intersection, and ZERO of every
     other ray-query getter;
  8  t never reaches arithmetic unguarded: the value the transfer consumes is
     OpSelect(committed, t, tmax);
  9  OpTraceRayKHR count is UNCHANGED from the base -- this adds a query,
     never a ray;
 10  glow: the transfer is the dual-lobe Beer-Lambert with per-channel 1/ld
     and 1/(WIDE*ld) constants resolved against ld = (3.67, 1.37, 0.68) mm,
     one SmoothStep on -(N.S) with the declared WRAP edge, one added OpDot,
     and a k select whose true arm resolves to K;
     hit: no Exp and no SmoothStep are added at all, and the paint is the two
     flat palette triples;
 11  the term is ADDED: every rewritten OpImageWrite's texel is an
     OpCompositeConstruct whose x/y/z are each OpFAdd(<the module's own
     component>, OpLoad(<one of our three Function accumulators>)) -- and the
     accumulators are zero-stored in the entry block. A multiply here would
     be 98's paint, which cannot make light on a shadowed surface (98 12.4).

--negative asserts the base carries none of it.
"""
import argparse, glob, math, os, re, subprocess, sys

PASS_THROUGH = {'40c6faab52a13874', 'ab7f1822eeb0331b'}
LD_M = (0.00367, 0.00137, 0.00068)
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
        # spirv-dis renders inf / nan / denormals in C99 hex form; those are
        # never one of our constants, so they resolve to None rather than
        # aborting the sweep.
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


def path_counter(lines, d, name):
    """90 sec 1's PATH-loop counter, re-derived independently of the patcher.

    Among counted loops `Op[SU]LessThan(x + 1, bound)` on a back edge whose
    body traces rays, the path loop is the one whose header seeds exactly 3
    fp phis with 1.0 (the RGB throughput); the sample loop seeds none. Its
    counter is the unique `OpPhi %uint` at that header whose incomings are
    exactly {0, that loop's own IAdd}. Unique in 12/12 on this base."""
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
        cm = re.match(r'Op[SU]LessThan %bool (%\w+) (%\w+)$', d.get(cond, (0, ''))[1])
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
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(?:half|float) (.+?)\s*$', lines[j])
                if pm and any(v in UNIT_ONE for v in pm.group(1).split()[0::2]):
                    ones += 1
                um = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+?)\s*$', lines[j])
                if um:
                    uphis.append((um.group(1), um.group(2).split()[0::2]))
            if ones == 3:
                hot.append([pid for pid, vals in uphis
                            if set(vals) == {'%uint_0', inc}])
            elif ones:
                bad(name, f"non-path loop {tgt} seeds {ones} phis with 1.0 -- "
                          f"the throughput discriminator is not clean")
    if len(hot) != 1 or len(hot[0]) != 1:
        bad(name, f"path-loop counter not unique: {hot}")
        return None
    return hot[0][0]


def nee_trace(lines, d, name):
    """The module's own sun-NEE trace, re-found by shape: flags 12, tmax
    10000, cull mask defined by OpSelect(cond, 0, 39). Unique per module."""
    hits = []
    for l in lines:
        m = re.match(r'\s*OpTraceRayKHR\s+(.+?)\s*$', l)
        if not m:
            continue
        ops = m.group(1).split()
        if len(ops) == 11 and ops[1] == '%uint_12' and ops[9] == '%float_10000':
            sm = re.match(r'OpSelect %uint (%\w+) %uint_0 %uint_39$',
                          d.get(ops[2], (0, ''))[1])
            if sm:
                hits.append((ops, sm.group(1)))
    if len(hits) != 1:
        bad(name, f"{len(hits)} sun-NEE traces (flags 12 / tmax 10000 / "
                  f"Select(cond,0,39) mask), want exactly 1")
        return None, None
    return hits[0]


def check_module(path, base_path, mode, k, wide, wrap, flags, tmin, tmax):
    name = os.path.basename(path)
    lines = dis(path)
    d = index(lines)
    base = dis(base_path)
    bd = index(base)

    # ---- 1. capability, extension, the query object -----------------------
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
    if len(rqv) != 1:
        return bad(name, f"{len(rqv)} ray query variables, want 1")
    j = d[rqv[0]][0] - 1
    while j >= 0 and re.match(r'\s*%\w+ = OpVariable .* Function\s*$', lines[j]):
        j -= 1
    if not re.match(r'\s*%\w+ = OpLabel\s*$', lines[j]):
        bad(name, "the ray query OpVariable is not in the entry block's "
                  "leading OpVariable run")

    # ---- 2. the module's own sun-NEE trace, re-found here ------------------
    nee, backlit = nee_trace(lines, d, name)
    if nee is None:
        return

    # ---- 3/4/5. the query, against that trace's own operands ---------------
    inits = [re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l).group(1).split()
             for l in lines if re.match(r'\s*OpRayQueryInitializeKHR\s', l)]
    if len(inits) != 1:
        return bad(name, f"{len(inits)} OpRayQueryInitializeKHR, want exactly 1")
    q = inits[0]
    if len(q) != 8:
        return bad(name, f"OpRayQueryInitializeKHR has {len(q)} operands, want 8")
    qrq, qas, qflags, qmask, qorig, qtmin, qdir, qtmax = q
    if qrq != rqv[0]:
        bad(name, f"the query runs on {qrq}, not the declared object {rqv[0]}")
    if qas != nee[0]:
        bad(name, f"acceleration structure {qas} is not the sun-NEE trace's {nee[0]}")
    if not d.get(qas, (0, ''))[1].startswith('OpConvertUToAccelerationStructureKHR'):
        bad(name, f"{qas} is not an OpConvertUToAccelerationStructureKHR result")
    if qorig != nee[6]:
        bad(name, f"ray origin {qorig} is not the sun-NEE trace's own {nee[6]} "
                  f"-- the query must trace from the ENGINE'S OWN offset hit "
                  f"position (98 sec 15: no world offset belongs here)")
    if qdir != nee[8]:
        bad(name, f"ray direction {qdir} is not the sun-NEE trace's own S "
                  f"({nee[8]})")
    fl = uval(d, qflags)
    if fl != flags:
        bad(name, f"ray flags are {fl}, want {flags}")
    if fl is not None:
        if fl & 0x20 == 0:
            bad(name, f"flags {fl}: CullFrontFacingTrianglesKHR (0x20) is NOT "
                      f"set -- the ray would keep the ENTRY face, not the far "
                      f"wall's backface (70 W1)")
        if fl & 0x10:
            bad(name, f"flags {fl}: CullBackFacingTrianglesKHR (0x10) is set -- "
                      f"that is v4's reversed segment, not W1")
        if fl & 0x04:
            bad(name, f"flags {fl}: TerminateOnFirstHitKHR (0x04) is set -- the "
                      f"committed hit must be the CLOSEST backface")
        if fl & 0x01 == 0:
            bad(name, f"flags {fl}: OpaqueKHR (0x01) is not set -- a candidate "
                      f"could then require shader intervention and one Proceed "
                      f"would not be enough")
        if fl & 0x200 == 0:
            bad(name, f"flags {fl}: SkipAABBsKHR (0x200) is not set")
    if not close(fval(d, qtmin), tmin):
        bad(name, f"tmin resolves to {fval(d, qtmin)}, want {tmin} "
                  f"(71's min-t floor)")
    if not close(fval(d, qtmax), tmax):
        bad(name, f"tmax resolves to {fval(d, qtmax)}, want {tmax}")

    # ---- 6. the gate, operand by operand ----------------------------------
    ms = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', d.get(qmask, (0, ''))[1])
    if not ms:
        return bad(name, f"cull mask {qmask} is not an OpSelect %uint")
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
                      f"{pc_want} (90 sec 1: the legacy helper returns the "
                      f"SAMPLE loop's phi in 5 of 12 permutations)")
    ga2 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(g_a1, (0, ''))[1])
    if not ga2:
        return bad(name, f"the skin/backlit term {g_a1} is not an OpLogicalAnd")
    g_skin, g_bl = ga2.groups()
    if g_bl != backlit:
        bad(name, f"the backlit operand is {g_bl}, but the sun-NEE trace's own "
                  f"cull-mask condition is {backlit}")
    sm = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d.get(g_skin, (0, ''))[1])
    if not sm:
        bad(name, f"the class term {g_skin} is not an OpIEqual")
    else:
        andid, cls = sm.groups()
        if uval(d, cls) != 32:
            bad(name, f"class compare is against {uval(d, cls)}, want 32 "
                      f"(class 1 = skin)")
        am = re.match(r'OpBitwiseAnd %uint (%\w+) (%\w+)$', d.get(andid, (0, ''))[1])
        if not am:
            bad(name, f"class source {andid} is not an OpBitwiseAnd")
        elif uval(d, am.group(2)) != 0xFFFFFFE0:
            bad(name, f"class mask is {uval(d, am.group(2))}, want 4294967264")
        else:
            em = re.match(r'OpCompositeExtract %uint (%\w+) 1$',
                          d.get(am.group(1), (0, ''))[1])
            if not em:
                bad(name, f"class word is not an OpCompositeExtract .. 1")
            elif not d.get(em.group(1), (0, ''))[1].startswith('OpImageFetch'):
                bad(name, f"the class word does not come from an OpImageFetch "
                          f"(got {d.get(em.group(1), (0, ''))[1][:40]})")

    # ---- 7. one Proceed, the T getter, and nothing else -------------------
    npro = count(lines, 'OpRayQueryProceedKHR')
    if npro != 1:
        bad(name, f"{npro} x OpRayQueryProceedKHR, want exactly 1 (more than "
                  f"one means a traversal LOOP was spliced in)")
    ity = [m.group(1) for l in lines for m in
           [re.match(r'\s*(%\w+)\s*=\s*OpRayQueryGetIntersectionTypeKHR %uint '
                     r'%\w+ (%\w+)\s*$', l)] if m and uval(d, m.group(2)) == 1]
    if len(ity) != 1:
        bad(name, f"{len(ity)} committed GetIntersectionTypeKHR, want 1")
    tg = [m.group(1) for l in lines for m in
          [re.match(r'\s*(%\w+)\s*=\s*OpRayQueryGetIntersectionTKHR %float '
                    r'%\w+ (%\w+)\s*$', l)] if m and uval(d, m.group(2)) == 1]
    if len(tg) != 1:
        bad(name, f"{len(tg)} committed OpRayQueryGetIntersectionTKHR, want 1 "
                  f"-- t IS the measurement")
    for g in GETTERS_OTHER:
        n = count(lines, g)
        if n:
            bad(name, f"{n} x {g} -- this rung reads t and nothing else")

    # ---- 8. the NaN guard --------------------------------------------------
    tu = None
    if len(tg) == 1 and len(ity) == 1:
        hitb = [m.group(1) for l in lines for m in
                [re.match(r'\s*(%\w+)\s*=\s*OpINotEqual %bool '
                          + re.escape(ity[0]) + r' (%\w+)\s*$', l)]
                if m and uval(d, m.group(2)) == 0]
        if len(hitb) != 1:
            bad(name, f"{len(hitb)} committed-vs-0 tests on the intersection "
                      f"type, want 1")
        else:
            sel = [m.group(1) for l in lines for m in
                   [re.match(r'\s*(%\w+)\s*=\s*OpSelect %float '
                             + re.escape(hitb[0]) + r' ' + re.escape(tg[0])
                             + r' (%\w+)\s*$', l)] if m
                   and close(fval(d, m.group(2)), tmax)]
            if len(sel) != 1:
                bad(name, "t is not guarded: want exactly one "
                          "OpSelect(committed, t, tmax) before any arithmetic "
                          "-- t is UNDEFINED on a miss and a NaN would poison "
                          "the radiance write")
            else:
                tu = sel[0]
            # and the raw t must have no other consumer
            # NB: \b does not work against a leading '%' -- both sides are
            # non-word characters there, so the boundary never matches and the
            # check would silently pass on everything.
            tref = re.compile(r'(?<!\w)' + re.escape(tg[0]) + r'(?!\w)')
            users = [l for l in lines if tref.search(l)
                     and not l.strip().startswith(tg[0] + ' =')]
            if len(users) != 1:
                bad(name, f"the raw t has {len(users)} consumers, want exactly "
                          f"1 (the guard select)")

    # ---- 9. no ray was added ----------------------------------------------
    if count(lines, 'OpTraceRayKHR') != count(base, 'OpTraceRayKHR'):
        bad(name, f"OpTraceRayKHR count {count(lines, 'OpTraceRayKHR')} != base "
                  f"{count(base, 'OpTraceRayKHR')} -- this rung adds a QUERY, "
                  f"never a ray")

    # ---- 10. the transfer / the diagnostic --------------------------------
    n_exp = count(lines, 'Exp ') - count(base, 'Exp ')
    n_ss = (count(lines, 'SmoothStep ') - count(base, 'SmoothStep '))
    n_dot = count(lines, 'OpDot %float ') - count(base, 'OpDot %float ')
    if mode == 'glow':
        want_exp = 6 if wide else 3
        if n_exp != want_exp:
            bad(name, f"{n_exp} added Exp, want {want_exp}")
        if n_ss != (1 if wrap else 0):
            bad(name, f"{n_ss} added SmoothStep, want {1 if wrap else 0}")
        if n_dot != (1 if wrap else 0):
            bad(name, f"{n_dot} added OpDot, want {1 if wrap else 0}")
        fl_all = {t: fval(d, t) for t in d if fval(d, t) is not None}
        for c, ld in enumerate(LD_M):
            if not any(close(v, 1.0 / ld, 1e-4) for v in fl_all.values()):
                bad(name, f"no constant resolving to 1/ld = {1.0/ld:.4f} "
                          f"(channel {c})")
            if wide and not any(close(v, 1.0 / (wide * ld), 1e-4)
                                for v in fl_all.values()):
                bad(name, f"no constant resolving to 1/({wide}*ld) = "
                          f"{1.0/(wide*ld):.4f} (channel {c})")
        if wrap and not any(close(v, wrap) for v in fl_all.values()):
            bad(name, f"no constant resolving to the wrap edge {wrap}")
        # the k select: OpSelect(gate AND committed, k, 0)
        ksel = []
        for l in lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', l)
            if m and close(fval(d, m.group(3)), k) and fval(d, m.group(4)) == 0.0:
                ksel.append(m)
        if len(ksel) != 1:
            bad(name, f"{len(ksel)} OpSelect(_, {k}, 0.0) k-selects, want 1")
        else:
            okid = ksel[0].group(2)
            om = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', d.get(okid, (0, ''))[1])
            if not om:
                bad(name, f"the k select's condition {okid} is not an OpLogicalAnd")
            elif gate not in om.groups():
                bad(name, f"the k select is not gated on the same gate as the "
                          f"cull mask ({gate})")
        # the transfer must consume the GUARDED t, not the raw one
        if tu is not None:
            n = sum(1 for l in lines
                    if re.match(r'\s*%\w+\s*=\s*OpFMul %float ' + re.escape(tu)
                                + r' %\w+\s*$', l))
            if n != want_exp:
                bad(name, f"{n} FMuls consume the guarded t, want {want_exp}")
    else:
        if n_exp or n_ss:
            bad(name, f"--mode hit must add NO transfer: {n_exp} Exp, "
                      f"{n_ss} SmoothStep")
        fl_all = {t: fval(d, t) for t in d if fval(d, t) is not None}
        for v in (3.2, 0.4):
            if not any(close(x, v) for x in fl_all.values()):
                bad(name, f"the flat diagnostic palette constant {v} is absent")
        nsel = sum(1 for l in lines
                   if re.match(r'\s*%\w+\s*=\s*OpSelect %float ', l))
        # 7 = the t guard (OpSelect(committed, t, tmax)) + 2 per channel
        # (committed -> BLUE, gated-but-missed -> RED).
        if nsel - sum(1 for l in base
                      if re.match(r'\s*%\w+\s*=\s*OpSelect %float ', l)) != 7:
            bad(name, "want exactly 7 added float selects (the t guard, plus "
                      "2 per channel: committed, and gated-but-missed)")

    # ---- 11. the term is ADDED, at the module's own radiance writes -------
    accs = []
    for l in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpVariable (%\w+) Function\s*$', l)
        if m and re.match(r'OpTypePointer Function %float$',
                          d.get(m.group(2), (0, ''))[1]):
            accs.append(m.group(1))
    accs = [a for a in accs if any(re.match(r'\s*OpStore ' + re.escape(a)
                                            + r' (%\w+)\s*$', l) for l in lines)]
    if len(accs) != 3:
        bad(name, f"{len(accs)} zero-stored Function float accumulators, want 3")
    painted = 0
    for l in lines:
        m = re.match(r'\s*OpImageWrite %\w+ %\w+ (%\w+)\s*$', l)
        if not m:
            continue
        cc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)$',
                      d.get(m.group(1), (0, ''))[1])
        if not cc:
            continue
        adds = 0
        for ch in range(3):
            am = re.match(r'OpFAdd %float (%\w+) (%\w+)$',
                          d.get(cc.group(ch + 1), (0, ''))[1])
            if not am:
                continue
            ld_ = [x for x in am.groups()
                   if re.match(r'OpLoad %float (%\w+)$', d.get(x, (0, ''))[1])
                   and re.match(r'OpLoad %float (%\w+)$',
                                d.get(x, (0, ''))[1]).group(1) in accs]
            if ld_:
                adds += 1
        if adds == 3:
            painted += 1
        elif adds:
            bad(name, f"a radiance write adds the term on only {adds} of 3 channels")
    if painted < 1:
        bad(name, "no radiance write ADDS the term -- an OpFMul paint (98's) "
                  "cannot make light on a shadowed surface (98 sec 12.4)")
    return painted


def negative(base_dir):
    n = 0
    for f in sorted(glob.glob(os.path.join(base_dir, '*.rgs_reference_main.spv'))):
        lines = dis(f)
        nm = os.path.basename(f)
        for needle in ('OpCapability RayQueryKHR', 'OpRayQueryInitializeKHR',
                       'OpRayQueryGetIntersectionTKHR'):
            if any(needle in l for l in lines):
                bad(nm, f"the BASE already carries {needle}")
        n += 1
    print(f"negative control: {n} base reference modules carry no ray query")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--negative')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--k', type=float, default=0.22)
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--flags', type=int, default=545)
    ap.add_argument('--tmin', type=float, default=0.0015)
    ap.add_argument('--tmax', type=float, default=0.018)
    a = ap.parse_args()

    if a.negative:
        negative(a.negative)
    else:
        if not (a.rung and a.base):
            ap.error('need <rung-dir> and --base <base-dir>')
        mods, writes = 0, 0
        for f in sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv'))):
            h = os.path.basename(f).split('.')[0]
            b = os.path.join(a.base, os.path.basename(f))
            if h in PASS_THROUGH:
                if subprocess.run(['cmp', '-s', f, b]).returncode != 0:
                    bad(os.path.basename(f), "pass-through differs from the base")
                continue
            n = check_module(f, b, a.mode, a.k, a.wide, a.wrap,
                             a.flags, a.tmin, a.tmax)
            mods += 1
            writes += (n or 0)
        if mods != 10:
            FAIL.append(f"{mods} patched permutations verified, want 10")
        print(f"verify_earglow_rq: {mods} permutations, {writes} painted writes, "
              f"mode={a.mode}, flags={a.flags}, tmin={a.tmin}, tmax={a.tmax}")
    if FAIL:
        print("FAILED:")
        for f in FAIL[:24]:
            print("  " + f)
        sys.exit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
