#!/usr/bin/env python3
"""verify_rayq.py <rung-dir> [--field id|custom|prim|sbt|geom|xf|xfq|xfw]
                  [--site bounce|primary] [--commit first|closest] [--gain0]

Re-derives the hunt-rayq splice from the SHIPPED .spv bytes -- never from the
patcher's own reports, and never from a byte diff (42: "a byte diff is not
coverage"). Everything below is read back out of spirv-dis output.

What it proves, per patched rgs_reference_main permutation:

  1  the module declares OpCapability RayQueryKHR + OpExtension
     "SPV_KHR_ray_query", has exactly one OpTypeRayQueryKHR and exactly one
     Function-storage ray query variable, declared inside the entry block's
     leading OpVariable run;
  2  exactly one OpRayQueryInitializeKHR;
  3  its acceleration-structure operand is THE SAME ID as the acceleration
     structure of the module's own first OpTraceRayKHR -- not a lookalike, not
     a second AS, the same SSA id;
  4  its cull mask, ray origin and ray direction are likewise the same ids as
     that trace's;
  5  its ray flags are the constant 517 = OpaqueKHR | TerminateOnFirstHitKHR |
     SkipAABBsKHR (each named, each with a reason in patch_rayq.py);
  6  its tmin/tmax bracket the hit distance the trace just wrote:
     tmin = t*0.999, tmax = t*1.001 + 1e-4, with t loaded through an access
     chain on member 3 of THAT TRACE'S payload variable;
  7  exactly one OpRayQueryProceedKHR, one OpRayQueryGetIntersectionTypeKHR,
     one instance of the declared field's GETTER and ZERO of every other
     getter in FIELDS -- which is what makes each rung a decoy for every other
     one. The count is per getter, not per field name, because xf/xfq/xfw all
     read OpRayQueryGetIntersectionObjectToWorldKHR;
 7b  for a field whose getter is not a uint (the xf family), the fold down to
     the uint the latch takes is re-derived instruction by instruction, and
     since three fields share one getter it is the ONLY thing that separates
     them. Common to all three: the result type IS an OpTypeMatrix %v3float 4
     declared above the first OpFunction and below %v3float, the matrix is
     consumed exactly once, by the extraction of column 3 (the translation),
     and its x/y/z are each extracted exactly once. Then, per field:
       xf   each component is OpBitcast to uint with NOTHING in between and
            has no other consumer at all -- raw bits, which is what rejects a
            quantised or offset build read as `xf`;
       xfq  each component is multiplied by a float constant re-read from the
            bytes and required to be 100.0, OpConvertFToS'd to a type re-read
            from the bytes and required to be OpTypeInt 32 1 declared in the
            type section, then OpBitcast -- 1 cm buckets;
       xfw  each component is FIRST added to the matching component of
            94 sec 3.3's world offset, loaded through the module's own
            bindless CBV at the member derive_world_offset independently picks
            out of the shipped bytes (the member whose .xyz the module itself
            adds to the hit position that is the origin of its own NEE traces
            -- so `56` is a RESULT here, not an assumption), and then
            quantised exactly as xfq does;
     in every case the three uints are XOR-folded into the value the
     committed-arm OpSelect writes to the latch;
  8  the module's OpTraceRayKHR count is unchanged -- the probe adds a query,
     never a ray;
  9  the state variable is a Private uint stored 0 in the entry block (the
     identity-when-dead arm), and every painted texel is orig x a select chain
     ROOTED AT 1.0, so a pixel whose query never ran is bit-exact vanilla;
 10  the multiplier set of that chain equals the documented palette (or is all
     1.0 under --gain0).

Under `--site primary` checks 4 and 6 change, and they get STRICTER rather
than looser -- the direction operand must be the module's own primary view
ray, re-derived here by a SECOND, independent implementation of the
perspective-divide-then-normalize detector (a deliberate duplicate of
patch_rayq._find_primary_ray: if the two ever disagree, the build stops):

  4' the origin operand is the zero triple -- the camera's position in P's
     own space (94 sec 3.3) -- and is NOT the trace's origin;
  6' tmin/tmax bracket |P| = dot(P,P) * rsqrt(dot(P,P)) built from the
     module's OWN primary P ids, not from the payload.

Because 4/6 and 4'/6' are mutually exclusive, verifying a bounce rung as
`--site primary` (or the reverse) is itself a non-vacuity decoy, and
build_rayq.sh runs both.

Non-vacuity is proven by build_rayq.sh pointing this at four builds it must
REJECT: the unpatched base, the gain-0 control read as if it were a probe, a
--decoy ray build (origin/direction not the trace's), and a --decoy flags
build (ray flags 0).
"""
import argparse, glob, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_rayq import (PALETTE, NOHIT, RAY_FLAGS, FIELDS, GOLDEN, SITES,
                        COMMIT_FLAGS, MATRIX_FIELDS)

# The two permutations 55 sec 2 / 56 sec 3 identified as having no radiance
# write at all (their only image writes are constant-zero). They ship verbatim.
PASS_THROUGH = {'40c6faab52a13874', 'ab7f1822eeb0331b'}

TRACE_RE = re.compile(r'^\s*OpTraceRayKHR\s+(.+?)\s*$')
INIT_RE = re.compile(r'^\s*OpRayQueryInitializeKHR\s+(.+?)\s*$')


def f32s(x):
    """spirv-dis renders a float constant with '.' -> '_' and '-' -> 'n'."""
    return x


class Asm:
    def __init__(self, path):
        self.path = path
        self.lines = subprocess.run(['spirv-dis', path], capture_output=True,
                                    text=True, check=True).stdout.splitlines()
        self.defs = {}
        for i, ln in enumerate(self.lines):
            m = re.match(r'^\s*(%\w+)\s*=\s*(.*)$', ln)
            if m:
                self.defs.setdefault(m.group(1), (i, m.group(2)))

    def d(self, idtok):
        return self.defs.get(idtok, (None, None))[1]

    def dline(self, idtok):
        return self.defs.get(idtok, (None, None))[0]

    def count(self, needle):
        return sum(1 for l in self.lines if needle in l)


def fconst(a, idtok):
    """float value of an OpConstant %float id, or None."""
    d = a.d(idtok) or ''
    m = re.match(r'OpConstant %float (\S+)\s*$', d)
    return float(m.group(1)) if m else None


def uconst(a, idtok):
    d = a.d(idtok) or ''
    m = re.match(r'OpConstant %uint (\d+)\s*$', d)
    return int(m.group(1)) if m else None


def find_primary(a):
    """SECOND implementation of patch_rayq._find_primary_ray, on the shipped
    disassembly. Deliberately duplicated: a verifier that imported the
    patcher's detector could only prove the patcher agreed with itself."""
    out = []
    for i, ln in enumerate(a.lines):
        m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ InverseSqrt (%\w+)\s*$', ln)
        if not m:
            continue
        rsq, dot = m.groups()
        dd = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', a.d(dot) or '')
        if not dd:
            continue
        ca = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(dd.group(1)) or '')
        cb = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(dd.group(2)) or '')
        if not ca or not cb or ca.groups() != cb.groups():
            continue
        P = list(ca.groups())
        divs = [re.match(r'OpFDiv %float (%\w+) (%\w+)\s*$', a.d(x) or '') for x in P]
        if not all(divs) or len({d.group(2) for d in divs}) != 1:
            continue
        V = []
        for comp in P:
            hit = None
            for j in range(i + 1, min(i + 16, len(a.lines))):
                mm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$',
                              a.lines[j])
                if mm and {mm.group(2), mm.group(3)} == {rsq, comp}:
                    hit = mm.group(1)
                    break
            V.append(hit)
        if any(v is None for v in V):
            continue
        out.append({'P': P, 'dot': dot, 'rsqrt': rsq, 'V': V})
    return out


def derive_world_offset(a):
    """SECOND implementation of patch_rayq._find_world_offset, on the shipped
    disassembly, and deliberately duplicated for the same reason find_primary
    is: a verifier that imported the patcher's detector could only prove the
    patcher agreed with itself.

    `94` sec 3.3 names the world offset `cbv[104][56].xyz`. 104 is that dump's
    SSA id for the bindless-CBV access chain, not an index, and every
    permutation renumbers -- so the member is re-derived here from the shipped
    bytes by the property `94` reasoned from: it is the CB member whose .xyz is
    added component by component to the module's own path-vertex hit position,
    the v3 triple that is the ORIGIN operand of the module's own shadow/NEE
    OpTraceRayKHR sites. Returns a list of (cbv, member) pairs; the caller
    requires exactly one.
    """
    origins = set()
    for l in a.lines:
        if not TRACE_RE.match(l):
            continue
        ops = TRACE_RE.match(l).group(1).split()
        if len(ops) != 11:
            continue
        cc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(ops[6]) or '')
        if cc:
            origins.add(cc.groups())
    ex = {}
    for l in a.lines:
        m = re.match(r'\s*(%\w+) = OpCompositeExtract %float (%\w+) (\d+)\s*$', l)
        if not m:
            continue
        ld = re.match(r'OpLoad %v4float (%\w+)\s*$', a.d(m.group(2)) or '')
        if not ld:
            continue
        ac = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(ld.group(1)) or '')
        if not ac:
            continue
        if uconst(a, ac.group(3)) != 0:
            continue
        mem = uconst(a, ac.group(4))
        if mem is None:
            continue
        ex[m.group(1)] = (ac.group(2), mem, int(m.group(3)))
    per = {}
    for l in a.lines:
        m = re.match(r'\s*%\w+ = OpFAdd %float (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        for u, v in ((m.group(1), m.group(2)), (m.group(2), m.group(1))):
            if u in ex:
                cbv, mem, comp = ex[u]
                per.setdefault((cbv, mem), {}).setdefault(comp, set()).add(v)
    out = []
    for (cbv, mem), byc in per.items():
        if set(byc) != {0, 1, 2}:
            continue
        for trip in origins:
            if all(trip[k] in byc[k] for k in range(3)):
                out.append((cbv, mem))
    return sorted(set(out))


def check_world_offset(a, comps, fail):
    """`xfw`: each translation component must be added to the matching
    component of 94 sec 3.3's world offset, loaded through the module's OWN
    bindless CBV, at the member that derive_world_offset independently picks
    out of the shipped bytes. Returns the three sums, or None."""
    anchors = derive_world_offset(a)
    if len(anchors) != 1:
        fail(f"{len(anchors)} (bindless CBV, member) pairs whose .xyz is added "
             "component-wise to a trace-origin hit position, want exactly 1 "
             "(94 sec 3.3's world offset)")
        return None
    want_cbv, want_mem = anchors[0]
    sums = []
    for k, c in enumerate(comps):
        got = []
        for l in a.lines:
            m = re.match(r'\s*(%\w+) = OpFAdd %float (%\w+) (%\w+)\s*$', l)
            if not m:
                continue
            ops = {m.group(2), m.group(3)}
            if c not in ops:
                continue
            other = (ops - {c}).pop() if len(ops) == 2 else c
            e = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$',
                         a.d(other) or '')
            if not e or int(e.group(2)) != k:
                continue
            ld = re.match(r'OpLoad %v4float (%\w+)\s*$', a.d(e.group(1)) or '')
            if not ld:
                continue
            ac = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                          a.d(ld.group(1)) or '')
            if not ac:
                continue
            if ac.group(2) != want_cbv:
                fail(f"the offset is loaded from {ac.group(2)}, not the module's "
                     f"own world-offset CBV {want_cbv}")
                continue
            i0, i1 = uconst(a, ac.group(3)), uconst(a, ac.group(4))
            if i0 != 0 or i1 != want_mem:
                fail(f"the offset access chain indexes [{i0}][{i1}], the "
                     f"module's own world offset is member {want_mem} "
                     "(94 sec 3.3)")
                continue
            got.append(m.group(1))
        if len(got) != 1:
            fail(f"translation component {k} is added to the world offset "
                 f"{len(got)} times, want exactly 1")
            return None
        sums.append(got[0])
    # ...and the raw translation must have no OTHER consumer: exactly the add.
    for c in comps:
        used = [l for l in a.lines
                if re.match(r'\s*%\w+ = Op\w+ .*' + re.escape(c) + r'\b', l)]
        if len(used) != 1:
            fail(f"translation component {c} is consumed {len(used)} times, "
                 "want 1 (only the world-offset add)")
            return None
    return sums


def check_quantise(a, src, step, fail):
    """`xfq` / `xfw`: value * step -> OpConvertFToS to a 32-bit SIGNED int ->
    the OpBitcast that check 7b then folds. Every constant and every type is
    re-derived from the shipped bytes: the scale is read back and compared to
    `step`, and the integer type is required to be an OpTypeInt 32 1 declared
    in the type section. Returns the three converted values, or None."""
    out = []
    for c in src:
        muls = [m.groups() for l in a.lines
                for m in [re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', l)]
                if m and c in (m.group(2), m.group(3))]
        if len(muls) != 1:
            fail(f"{c} is multiplied by the quantisation scale {len(muls)} "
                 "times, want exactly 1")
            return None
        mid, x, y = muls[0]
        kid = y if x == c else x
        k = fconst(a, kid)
        if k is None or abs(k - step) > 1e-6:
            fail(f"quantisation scale is {k}, want {step} (1 cm buckets)")
            return None
        used = [l for l in a.lines
                if re.match(r'\s*%\w+ = Op\w+ .*' + re.escape(c) + r'\b', l)]
        if len(used) != 1:
            fail(f"{c} is consumed {len(used)} times, want 1 (only the scale)")
            return None
        cvs = [m.groups() for l in a.lines
               for m in [re.match(r'\s*(%\w+) = OpConvertFToS (%\w+) '
                                  + re.escape(mid) + r'\s*$', l)] if m]
        if len(cvs) != 1:
            fail(f"the scaled component {mid} is OpConvertFToS'd {len(cvs)} "
                 "times, want exactly 1 -- the quantisation is the rounding, "
                 "not the multiply")
            return None
        cid, ity = cvs[0]
        idef = (a.d(ity) or '').strip()
        if idef != 'OpTypeInt 32 1':
            fail(f"the quantised type {ity} is '{idef}', want 'OpTypeInt 32 1' "
                 "(the translation is signed and the sign must survive)")
            return None
        ffun = next((i for i, l in enumerate(a.lines)
                     if ' = OpFunction ' in l), len(a.lines))
        if a.dline(ity) is None or a.dline(ity) >= ffun:
            fail(f"{ity} is not declared above the first OpFunction")
            return None
        out.append(cid)
    return out


def check_module(path, field, gain0, bad, site='bounce', commit='first'):
    name = os.path.basename(path)
    a = Asm(path)

    def fail(msg):
        bad.append(f"{name}: {msg}")

    # ---- 1. capability / extension / the query object ---------------------
    if not any(re.match(r'\s*OpCapability RayQueryKHR\s*$', l) for l in a.lines):
        return fail("no OpCapability RayQueryKHR")
    if not any('OpExtension "SPV_KHR_ray_query"' in l for l in a.lines):
        fail('no OpExtension "SPV_KHR_ray_query"')
    rqts = [m.group(1) for l in a.lines
            for m in [re.match(r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$', l)] if m]
    if len(rqts) != 1:
        return fail(f"{len(rqts)} OpTypeRayQueryKHR, want 1")
    ptrs = [m.group(1) for l in a.lines
            for m in [re.match(r'\s*(%\w+)\s*=\s*OpTypePointer Function '
                               + re.escape(rqts[0]) + r'\s*$', l)] if m]
    if len(ptrs) != 1:
        return fail(f"{len(ptrs)} Function pointers to the ray query type, want 1")
    rqvars = [m.group(1) for l in a.lines
              for m in [re.match(r'\s*(%\w+)\s*=\s*OpVariable '
                                 + re.escape(ptrs[0]) + r' Function\s*$', l)] if m]
    if len(rqvars) != 1:
        return fail(f"{len(rqvars)} ray query variables, want 1")
    rq = rqvars[0]
    # it must sit inside the entry function's leading OpVariable run
    vline = a.dline(rq)
    j = vline - 1
    while j >= 0 and re.match(r'\s*%\w+ = OpVariable .* Function\s*$', a.lines[j]):
        j -= 1
    if not re.match(r'\s*%\w+ = OpLabel\s*$', a.lines[j]):
        fail("the ray query OpVariable is not in the entry block's leading "
             "OpVariable run")

    # ---- 2/3/4/5/6. the query itself, against the module's own trace -------
    traces = [TRACE_RE.match(l).group(1).split() for l in a.lines if TRACE_RE.match(l)]
    if not traces:
        return fail("no OpTraceRayKHR at all")
    t0 = traces[0]
    inits = [INIT_RE.match(l).group(1).split() for l in a.lines if INIT_RE.match(l)]
    if len(inits) != 1:
        return fail(f"{len(inits)} OpRayQueryInitializeKHR, want exactly 1")
    q = inits[0]
    if len(q) != 8:
        return fail(f"OpRayQueryInitializeKHR has {len(q)} operands, want 8")
    qrq, qas, qflags, qmask, qorig, qtmin, qdir, qtmax = q
    if qrq != rq:
        fail(f"the query is initialised on {qrq}, not the declared object {rq}")
    if qas != t0[0]:
        fail(f"acceleration structure is {qas}, the module's own trace uses {t0[0]}")
    if not (a.d(qas) or '').startswith('OpConvertUToAccelerationStructureKHR'):
        fail(f"{qas} is not an OpConvertUToAccelerationStructureKHR result")
    if qmask != t0[2]:
        fail(f"cull mask is {qmask}, the trace uses {t0[2]}")
    prim = None
    if site == 'bounce':
        if qorig != t0[6]:
            fail(f"ray origin is {qorig}, the trace uses {t0[6]}")
        if qdir != t0[8]:
            fail(f"ray direction is {qdir}, the trace uses {t0[8]}")
    else:
        found = find_primary(a)
        if len(found) != 1:
            return fail(f"{len(found)} primary-ray reconstructions found, want "
                        "exactly 1 (perspective divide -> normalize)")
        prim = found[0]
        # 4'a the direction IS the module's own primary view ray
        cc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(qdir) or '')
        if not cc:
            fail(f"ray direction {qdir} is not an OpCompositeConstruct %v3float")
        elif list(cc.groups()) != prim['V']:
            fail(f"ray direction is {list(cc.groups())}, the module's own "
                 f"primary view ray is {prim['V']}")
        if qdir == t0[8]:
            fail("ray direction is the BOUNCE ray's -- this is a bounce build "
                 "being read as a primary one")
        # 4'b the origin is the camera: the zero triple in P's own space
        oc = re.match(r'OpConstantComposite %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(qorig) or '')
        if not oc:
            fail(f"ray origin {qorig} is not an OpConstantComposite %v3float "
                 "(the camera sits at the origin of P's space, 94 sec 3.3)")
        elif any(fconst(a, c) is None or fconst(a, c) != 0.0 for c in oc.groups()):
            fail(f"ray origin components are {[fconst(a, c) for c in oc.groups()]},"
                 " want 0.0 (the module's own float zero; spirv-dis may render "
                 "it %float_n0, which is the same point)")
        if qorig == t0[6]:
            fail("ray origin is the BOUNCE ray's origin, not the camera")
    fl = uconst(a, qflags)
    want_flags, flag_names = COMMIT_FLAGS[commit]
    if fl != want_flags:
        fail(f"ray flags are {fl}, want {want_flags} ({flag_names}) "
             f"for commit={commit}")
    # Whatever the commit mode, ONE Proceed must be the whole traversal: that
    # is the zero-added-control-flow claim, and it is checked as a count, not
    # argued. A second Proceed would mean a loop was spliced in.
    npro = sum(1 for l in a.lines if 'OpRayQueryProceedKHR' in l)
    if npro != 1:
        fail(f"{npro} x OpRayQueryProceedKHR, want exactly 1 "
             "(more than one means a traversal LOOP was added)")
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in a.lines):
        fail("ray flag SkipAABBsKHR used without RayTraversalPrimitiveCullingKHR")

    # bounce : tmin = t*0.999 ; tmax = t*1.001 + 1e-4 ; t = load(payload[3])
    # primary: the same bracket, but t = |P| = dot(P,P) * rsqrt(dot(P,P)),
    #          built from the module's own primary P ids.
    m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', a.d(qtmin) or '')
    if not m:
        fail(f"tmin {qtmin} is not an OpFMul")
    else:
        tid, kid = m.groups()
        k = fconst(a, kid)
        if k is None or abs(k - 0.999) > 1e-6:
            fail(f"tmin scale is {k}, want 0.999")
        if site == 'bounce':
            ld = re.match(r'OpLoad %float (%\w+)\s*$', a.d(tid) or '')
            if not ld:
                fail(f"tmin's t ({tid}) is not an OpLoad")
            else:
                ac = re.match(r'OpInBoundsAccessChain %\w+ (%\w+) (%\w+)\s*$',
                              a.d(ld.group(1)) or '')
                if not ac:
                    fail("t is not loaded through an access chain")
                else:
                    pv, idx = ac.groups()
                    if pv != t0[10]:
                        fail(f"t is read from payload {pv}, the trace writes {t0[10]}")
                    if uconst(a, idx) != 3:
                        fail(f"t is member {uconst(a, idx)} of the payload, want 3 "
                             "(94 sec 2.2: word3 is the hit distance)")
        elif prim is not None:
            lm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', a.d(tid) or '')
            if not lm:
                fail(f"tmin's t ({tid}) is not |P| = dot * rsqrt")
            elif {lm.group(1), lm.group(2)} != {prim['dot'], prim['rsqrt']}:
                fail(f"t is built from {lm.groups()}, the module's own primary "
                     f"P gives dot={prim['dot']} rsqrt={prim['rsqrt']}")
            if re.match(r'OpLoad %float ', a.d(tid) or ''):
                fail("t is loaded from the payload -- this is a bounce build "
                     "being read as a primary one")
        add = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', a.d(qtmax) or '')
        if not add:
            fail(f"tmax {qtmax} is not an OpFAdd")
        else:
            mul, eps = add.groups()
            if fconst(a, eps) is None or abs(fconst(a, eps) - 1e-4) > 1e-9:
                fail(f"tmax epsilon is {fconst(a, eps)}, want 1e-4")
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', a.d(mul) or '')
            if not mm:
                fail("tmax is not t*k + eps")
            else:
                if mm.group(1) != tid:
                    fail("tmax uses a different t from tmin")
                kk = fconst(a, mm.group(2))
                if kk is None or abs(kk - 1.001) > 1e-6:
                    fail(f"tmax scale is {kk}, want 1.001")

    # ---- 7. the readback ops ----------------------------------------------
    if a.count('OpRayQueryProceedKHR') != 1:
        fail(f"{a.count('OpRayQueryProceedKHR')} OpRayQueryProceedKHR, want 1")
    if a.count('OpRayQueryGetIntersectionTypeKHR') != 1:
        fail("OpRayQueryGetIntersectionTypeKHR count != 1")
    want_getter = FIELDS[field][0]
    # Several FIELDS now SHARE a getter (xf / xfq / xfw are all
    # OpRayQueryGetIntersectionObjectToWorldKHR), so the count is taken per
    # distinct GETTER, not per field name. What separates fields that share a
    # getter is 7b, which re-derives the fold -- and it is the only thing that
    # does, which is why 7b is a hard check and not a description.
    for g in sorted({gg for gg, _doc in FIELDS.values()}):
        n = a.count(g)
        if g == want_getter and n != 1:
            fail(f"{n} x {g}, want 1")
        if g != want_getter and n != 0:
            fail(f"{n} x {g}, want 0 (this rung paints '{field}')")

    # ---- 7b. a non-uint getter must be folded the documented way ----------
    if field in MATRIX_FIELDS:
        spec = MATRIX_FIELDS[field]
        gets = [m.groups() for l in a.lines
                for m in [re.match(r'\s*(%\w+) = ' + re.escape(want_getter)
                                   + r' (%\w+) (%\w+) (%\w+)\s*$', l)] if m]
        if len(gets) != 1:
            fail(f"{len(gets)} readable {want_getter} instructions, want 1")
        else:
            gid, gty, grq, gix = gets[0]
            if grq != rq:
                fail(f"{want_getter} reads {grq}, not the query object {rq}")
            if uconst(a, gix) != 1:
                fail(f"{want_getter} intersection operand is {uconst(a, gix)}, "
                     "want 1 (the COMMITTED intersection)")
            tdef = a.d(gty) or ''
            if tdef.strip() != spec['type_decl']:
                fail(f"the getter's result type {gty} is '{tdef}', want "
                     f"'{spec['type_decl']}'")
            # the declaration must sit in the type section, not in a function
            tline = a.dline(gty)
            ffun = next((i for i, l in enumerate(a.lines)
                         if ' = OpFunction ' in l), len(a.lines))
            v3 = next((i for i, l in enumerate(a.lines)
                       if re.match(r'\s*%v3float = OpTypeVector %float 3\s*$', l)),
                      None)
            if tline is None or tline >= ffun:
                fail(f"{gty} is declared at line {tline}, not above the first "
                     f"OpFunction (line {ffun}) -- wrong section")
            elif v3 is None or tline <= v3:
                fail(f"{gty} is declared above the %v3float it is built from")
            # column N -> x,y,z
            cols = [m.group(1) for l in a.lines
                    for m in [re.match(r'\s*(%\w+) = OpCompositeExtract %v3float '
                                       + re.escape(gid) + r' (\d+)\s*$', l)]
                    if m and int(m.group(2)) == spec['column']]
            others = [l for l in a.lines
                      if re.match(r'\s*%\w+ = Op\w+ .*' + re.escape(gid) + r'\b', l)]
            if len(cols) != 1:
                fail(f"{len(cols)} extractions of column {spec['column']} from "
                     f"{gid}, want 1")
            elif len(others) != 1:
                fail(f"the matrix {gid} is consumed {len(others)} times, want 1 "
                     "(only the translation column)")
            else:
                col = cols[0]
                comps = []
                for k in range(3):
                    c = [m.group(1) for l in a.lines
                         for m in [re.match(r'\s*(%\w+) = OpCompositeExtract %float '
                                            + re.escape(col) + r' (\d+)\s*$', l)]
                         if m and int(m.group(2)) == k]
                    if len(c) != 1:
                        fail(f"{len(c)} extractions of component {k} of the "
                             "translation, want 1")
                        comps = []
                        break
                    comps.append(c[0])

                # ---- the fold, dial by dial. THIS is what separates xf from
                # xfq from xfw: all three carry the same getter, so the count
                # in check 7 cannot tell them apart and only the arithmetic
                # between the extraction and the OpBitcast can.
                src = comps
                if src and spec.get('offset'):
                    src = check_world_offset(a, src, fail)
                if src and spec.get('quantise'):
                    src = check_quantise(a, src, spec['quantise'], fail)
                elif src:
                    # RAW BITS: each component must go straight into the
                    # OpBitcast with nothing in between, and must have no
                    # other consumer at all -- which is what rejects a
                    # quantised or offset build read as `xf`.
                    for c in src:
                        used = [l for l in a.lines
                                if re.match(r'\s*%\w+ = Op\w+ .*'
                                            + re.escape(c) + r'\b', l)]
                        if len(used) != 1:
                            fail(f"translation component {c} is consumed "
                                 f"{len(used)} times, want 1 -- RAW BITS means "
                                 "no arithmetic between the extract and the "
                                 "OpBitcast")
                            src = None
                            break
                bits = []
                if src:
                    for c in src:
                        b = [m.group(1) for l in a.lines
                             for m in [re.match(r'\s*(%\w+) = OpBitcast %uint '
                                                + re.escape(c) + r'\s*$', l)] if m]
                        if len(b) != 1:
                            fail(f"{c} is not OpBitcast to uint exactly once "
                                 f"({len(b)} found) -- the '{field}' fold ends "
                                 "in three bitcasts and nothing else")
                            bits = []
                            break
                        bits.append(b[0])
                if len(bits) == 3:
                    x01 = [m.group(1) for l in a.lines
                           for m in [re.match(r'\s*(%\w+) = OpBitwiseXor %uint '
                                              r'(%\w+) (%\w+)\s*$', l)]
                           if m and {m.group(2), m.group(3)} == {bits[0], bits[1]}]
                    if len(x01) != 1:
                        fail("x and y bits are not XOR-folded exactly once")
                    else:
                        fold = [m.group(1) for l in a.lines
                                for m in [re.match(r'\s*(%\w+) = OpBitwiseXor %uint '
                                                   r'(%\w+) (%\w+)\s*$', l)]
                                if m and {m.group(2), m.group(3)} == {x01[0], bits[2]}]
                        if len(fold) != 1:
                            fail("z bits are not XOR-folded into the other two")
                        else:
                            # and the fold is what the committed arm latches
                            sel = [l for l in a.lines
                                   if re.match(r'\s*%\w+ = OpSelect %uint %\w+ '
                                               + re.escape(fold[0])
                                               + r' %uint_0\s*$', l)]
                            if len(sel) != 1:
                                fail(f"the folded value {fold[0]} is not the "
                                     "committed arm of the latch select")

    # ---- 8. no ray was added ----------------------------------------------
    # (build_rayq.sh compares against the base's own count; here we only
    #  assert nothing looks like a second injected trace site.)
    if len(traces) != 12:
        fail(f"{len(traces)} OpTraceRayKHR, the reference raygens all have 12")

    # ---- 9/10. the paint ---------------------------------------------------
    # the state variable: Private uint, stored 0 in the entry block
    privs = [m.group(1) for l in a.lines
             for m in [re.match(r'\s*(%\w+)\s*=\s*OpVariable %\w+ Private\s*$', l)] if m]
    if len(privs) != 2:
        fail(f"{len(privs)} Private variables, want 2 (state + id)")
    zero_stores = [l for l in a.lines
                   if re.match(r'\s*OpStore (%\w+) %uint_0\s*$', l)
                   and re.match(r'\s*OpStore (%\w+) %uint_0\s*$', l).group(1) in privs]
    if len(zero_stores) != 2:
        fail(f"{len(zero_stores)} entry-block zero stores to the Private "
             f"latch, want 2 (the identity-when-dead arm)")

    want_mults = set()
    for _n, rgb in PALETTE:
        for v in rgb:
            want_mults.add(round(1.0 + (0.0 if gain0 else 1.0) * (v - 1.0), 6))
    for v in NOHIT[site][1]:
        want_mults.add(round(1.0 + (0.0 if gain0 else 1.0) * (v - 1.0), 6))

    painted = 0
    for i, ln in enumerate(a.lines):
        m = re.match(r'\s*OpImageWrite %\w+ %\w+ (%\w+)\s*$', ln)
        if not m:
            continue
        tex = m.group(1)
        cc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      a.d(tex) or '')
        if not cc:
            continue
        chans = cc.groups()[:3]
        muls = [re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', a.d(c) or '')
                for c in chans]
        if not all(muls):
            continue                      # an untouched (constant-zero) write
        ok = True
        for mu in muls:
            cur = mu.group(2)
            depth = 0
            seen = []
            while True:
                s = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                             a.d(cur) or '')
                if not s:
                    break
                seen.append(s.group(2))
                cur = s.group(3)
                depth += 1
                if depth > 32:
                    break
            if depth != 9:
                ok = False
                bad.append(f"{name}: paint chain depth {depth}, want 9 "
                           "(8 hue buckets + the no-hit arm)")
                break
            root = fconst(a, cur)
            if root is None or abs(root - 1.0) > 1e-9:
                ok = False
                bad.append(f"{name}: paint chain is rooted at {root}, not 1.0 -- "
                           "a pixel whose query never ran would NOT be vanilla")
                break
            for sid in seen:
                v = fconst(a, sid)
                if v is None or round(abs(v), 6) not in want_mults:
                    ok = False
                    bad.append(f"{name}: paint multiplier {v} is not in the "
                               f"{'gain-0' if gain0 else 'documented'} palette")
                    break
            if not ok:
                break
        if ok:
            painted += 1
    if painted == 0:
        fail("no painted radiance write found")
    return painted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--field', default='id', choices=sorted(FIELDS))
    ap.add_argument('--site', default='bounce', choices=SITES,
                    help='which ray the query must clone')
    ap.add_argument('--gain0', action='store_true',
                    help='verify the CONTROL: every multiplier must be 1.0')
    ap.add_argument('--commit', default='first', choices=sorted(COMMIT_FLAGS),
                    help='which ray-flag constant the query must carry')
    a = ap.parse_args()

    refs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv')))
    if len(refs) != 12:
        sys.exit(f"verify_rayq: {len(refs)} rgs_reference_main in {a.rung}, want 12")
    bad, patched, writes = [], 0, 0
    for p in refs:
        h = os.path.basename(p).split('.')[0]
        has_rq = 'OpCapability RayQueryKHR' in subprocess.run(
            ['spirv-dis', p], capture_output=True, text=True).stdout
        if h in PASS_THROUGH:
            if has_rq:
                bad.append(f"{h}: is a documented pass-through but carries a ray query")
            continue
        if not has_rq:
            bad.append(f"{h}: no ray query -- this permutation must be patched")
            continue
        patched += 1
        n = check_module(p, a.field, a.gain0, bad, a.site, a.commit)
        writes += n or 0
    if patched != 10:
        bad.append(f"{patched} patched permutations, want 10 "
                   f"(12 minus the {len(PASS_THROUGH)} radiance-write-free ones)")
    if bad:
        for b in bad[:20]:
            sys.stderr.write("  REJECT " + b + "\n")
        sys.exit(1)
    print(f"  verify_rayq: {patched}/10 permutations, {writes} painted writes, "
          f"site={a.site}, field={a.field} ({FIELDS[a.field][1]}), "
          f"flags={COMMIT_FLAGS[a.commit][0]} ({a.commit}), "
          f"gain={'0' if a.gain0 else '1'} -- ALL PASS")


if __name__ == '__main__':
    main()
