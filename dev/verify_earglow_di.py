#!/usr/bin/env python3
"""verify_earglow_di -- re-derive the local-light ear glow claim from the
SHIPPED .spv bytes. handoff/112.

    python3 dev/verify_earglow_di.py <rung-dir> --base <base-dir> \
            --model <transmit_model.json> --mode glow|hit [--k-scale S]
    python3 dev/verify_earglow_di.py --negative <dir>     # no marker, no ray query

Nothing here reads a build report and nothing here trusts
dev/patch_earglow_di.py's site finder: every claim below is re-derived from
the bytes, starting at the ray-query Initialize instructions and walking
OUTWARD to the light record, the engine's own gate, the position chain and
the diffuse write.

  * marker / sentinel / slot / TLAS address: verify_bda's own binary and
    structural halves, imported (`103`).
  * every module either carries the marker and the splice, or is
    BYTE-IDENTICAL to the base module of the same name.
  * per site (one per Initialize with flags 545 = query B):
      - queries A, B, C in ONE block, each Initialize -> Proceed -> committed
        reads on its OWN query variable, all three on the slot TLAS and the
        SAME cull mask; A flags 517 from the camera along (P-C)/|P-C| with
        the |d| +- max(0.1 %, 5 mm) bracket; B flags 545, tmin 1.5 mm, tmax
        18 mm from the CAMERA-RELATIVE P (verify_wpos's own position test);
        C flags 517 from P - C + (t + 1 mm) L, tmin 1 mm, tmax
        select(directional, 100, max(dist - t - 1 mm, 1 mm)).
      - L = normalize(select(flags & 128, -dir, lightPos - P)) where pos,
        dir, flags are the offset-0 / 16 / 44 loads of ONE stride-128 light
        record and P is the module's own reconstruction.
      - the mask is select(class == 1 AND magic AND atten > 0, 255, 0), and
        `atten` is a factor of the product the engine's OWN `> 0` branch
        (the one that ends this very block) tests, and the one factor whose
        cone contains the record's colour load.
      - accept = A hit AND B hit AND A.id == B.id AND NOT C hit.
      - glow: the three stores are the `111` v7 transfer at the model's
        rates, tints, floor 6 mm, clamp 100, k x k-scale, times atten and
        the record's colour, selected on accept.
      - hit: the flat diagnostic paint, selected on accept / A.id==B.id /
        magic, on class-1 only.
  * exactly ONE image write adds the three accumulators, and it is the
    write the Disney diffuse (c1) term reaches.
  * no OpTraceRayKHR count changes.

WHAT A PASS DOES NOT MEAN: that the layer armed the slot, that the pipeline
links in the game, or that the queries hit anything. Those are
dev/selftest_bda.sh, `bda-probe` / `bda-rq-probe` on screen, and the screen.
"""
import argparse, collections, glob, os, re, subprocess, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient
import wpos_core as W
from verify_wpos import _check_position_triple, consts
from verify_bda import (Fail, check_marker, binary_marker, slot_pointer,
                        slot_word, only, want_f, fconst)
from patch_bda import MAGIC, W_MAGIC, W_LO, W_HI, DECLINE_ALL, DECLINE_RQ
from patch_compute_skin import find_c1_sites
from patch_earglow7 import load_model
import patch_earglow_di as G

RQ_OPS = ('OpRayQueryInitializeKHR', 'OpRayQueryProceedKHR',
          'OpRayQueryGetIntersectionTypeKHR', 'OpConvertUToAccelerationStructureKHR')


def uconsts(mod):
    out = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %uint (\d+)\s*$', ln)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def want_u(KU, i, v, name, what):
    if KU.get(i) != v:
        raise Fail('%s: %s is %s, want %d' % (name, what, KU.get(i), v))


def rx(D, i, pat, name, what):
    m = re.match(pat, D.get(i, (0, ''))[1])
    if not m:
        raise Fail('%s: %s is not `%s` (%r)' % (name, what, pat, D.get(i, (0, ''))[1][:80]))
    return m


def cone(D, root, limit=4000):
    seen, st = set(), [root]
    while st and len(seen) < limit:
        y = st.pop()
        if y in seen or y not in D:
            continue
        seen.add(y)
        st.extend(re.findall(r'%\w+', D[y][1])[1:] if D[y][1].startswith('OpExtInst')
                  else re.findall(r'%\w+', D[y][1]))
    return seen


def flatten_mul(D, x, out):
    m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D.get(x, (0, ''))[1])
    if m:
        flatten_mul(D, m.group(1), out)
        flatten_mul(D, m.group(2), out)
    else:
        out.append(x)


def block_of(mod, line):
    for k in range(line, -1, -1):
        if re.match(r'\s*%\w+\s*=\s*OpLabel\s*$', mod.lines[k]):
            return k
    raise Fail('no block start above line %d' % (line + 1))


def block_end(mod, line):
    for k in range(line, len(mod.lines)):
        if re.match(r'\s*Op(Branch|BranchConditional|Switch|Return|ReturnValue|Kill|Unreachable)\b',
                    mod.lines[k].strip()):
            return k
    raise Fail('no terminator below line %d' % (line + 1))


def light_record(mod, D, KU, ld_id, name):
    """(base, idx, offset) of the stride-128 chain a v3/uint load reads."""
    m = rx(D, ld_id, r'OpLoad %\w+ (%\w+) Aligned \d+\s*$', name, 'record load')
    c = rx(D, m.group(1), r'OpRawAccessChainNV %_ptr_StorageBuffer_\w+ (%\w+) (%\w+) (%\w+) (%\w+)\b',
           name, 'light record chain')
    if KU.get(c.group(2)) != G.LIGHT_STRIDE:
        raise Fail('%s: record stride is %s, want %d' % (name, KU.get(c.group(2)), G.LIGHT_STRIDE))
    return c.group(1), c.group(3), KU.get(c.group(4))


def extract3(D, ids, name, what):
    """Three CompositeExtract of the same v3 load, components 0,1,2 -> load id."""
    lds = set()
    for k, i in enumerate(ids):
        m = rx(D, i, r'OpCompositeExtract %float (%\w+) (\d)\s*$', name, what)
        if int(m.group(2)) != k:
            raise Fail('%s: %s component %d is extract %s' % (name, what, k, m.group(2)))
        lds.add(m.group(1))
    if len(lds) != 1:
        raise Fail('%s: %s extracts from %d loads' % (name, what, len(lds)))
    return lds.pop()


def check_query(mod, D, KU, K, ini_line, rq, acc, name, what):
    """Initialize -> Proceed -> committed-type read in one block; returns
    (operands, hit_id, type_id, block_end)."""
    a = mod.lines[ini_line].split()[1:]
    if a[0] != rq:
        raise Fail('%s: %s uses query %s, want %s' % (name, what, a[0], rq))
    if a[1] != acc:
        raise Fail('%s: %s is not on the slot TLAS' % (name, what))
    end = block_end(mod, ini_line)
    pro = ty = None
    for i in range(ini_line + 1, end):
        t = mod.lines[i].strip()
        if re.search(r'= OpRayQueryProceedKHR %bool ' + re.escape(rq) + r'\s*$', t):
            pro = i
        m = re.match(r'(%\w+) = OpRayQueryGetIntersectionTypeKHR %uint ' + re.escape(rq) + r' (%\w+)\s*$', t)
        if m and ty is None:
            ty = (i, m.group(1), m.group(2))
        if re.match(r'OpRayQueryInitializeKHR ' + re.escape(rq) + r'\b', t):
            raise Fail('%s: %s re-initialised before its committed read' % (name, what))
    if pro is None or ty is None or not (ini_line < pro < ty[0]):
        raise Fail('%s: %s lacks Initialize -> Proceed -> committed-type in one block' % (name, what))
    want_u(KU, ty[2], 1, name, what + ' intersection kind (want COMMITTED)')
    hits = [i for i, (_, t) in D.items()
            if re.match(r'OpINotEqual %bool ' + re.escape(ty[1]) + r' (%\w+)\s*$', t)
            and KU.get(re.match(r'OpINotEqual %bool %\w+ (%\w+)\s*$', t).group(1)) == 0]
    if len(hits) != 1:
        raise Fail('%s: %s committed type is tested != 0 %d times' % (name, what, len(hits)))
    return a, hits[0], end


def getter(mod, D, op, rq, KU, name, what, lo, hi):
    """The ONE committed getter `op` on `rq` inside lines [lo, hi)."""
    g = []
    for i in range(lo, hi):
        m = re.match(r'\s*(%\w+)\s*=\s*' + op + r' %\w+ ' + re.escape(rq) + r' (%\w+)\s*$', mod.lines[i])
        if m:
            g.append(m.groups())
    if len(g) != 1:
        raise Fail('%s: %d x %s on %s in the block, want 1' % (name, len(g), what, rq))
    want_u(KU, g[0][1], 1, name, what + ' kind')
    return g[0][0]


def check_module(path, spv, base_spv, mode, model, kscale):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    src = '\n'.join(mod.lines)
    bm = binary_marker(spv)
    identical = open(spv, 'rb').read() == open(base_spv, 'rb').read()
    if not bm['markers']:
        if not identical:
            raise Fail('%s: no marker but NOT byte-identical to the base' % name)
        if any(op in src for op in RQ_OPS):
            raise Fail('%s: unmarked module carries ray-query work' % name)
        return dict(module=name, patched=False, declined=name in (DECLINE_ALL | DECLINE_RQ))
    if name in DECLINE_ALL or name in DECLINE_RQ:
        raise Fail('%s: a module declined by name carries the marker' % name)
    check_marker(spv, name, expect_marker=True)
    D = W.defs_index(mod)
    K = consts(mod)
    KU = uconsts(mod)
    for cap in ('OpCapability RayQueryKHR', 'OpCapability RayTraversalPrimitiveCullingKHR',
                'OpExtension "SPV_KHR_ray_query"'):
        if cap not in src:
            raise Fail('%s: missing %s' % (name, cap))
    ptr = slot_pointer(mod, D, name)
    w0 = slot_word(D, ptr, W_MAGIC, name)
    mag = [i for i, (_, t) in D.items() if re.match(r'OpConstant %uint ' + str(MAGIC) + r'\s*$', t)]
    if len(mag) != 1:
        raise Fail('%s: %d magic constants' % (name, len(mag)))
    ok = only(D, r'OpIEqual %bool ' + re.escape(w0) + ' ' + re.escape(mag[0]) + r'\s*$',
              name, 'magic comparison')[0]
    wlo, whi = slot_word(D, ptr, W_LO, name), slot_word(D, ptr, W_HI, name)
    av = only(D, r'OpCompositeConstruct %v2uint ' + re.escape(wlo) + ' ' + re.escape(whi) + r'\s*$',
              name, 'TLAS address vector')[0]
    acc = only(D, r'OpConvertUToAccelerationStructureKHR %\w+ ' + re.escape(av) + r'\s*$',
               name, 'AS conversion')[0]
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        raise Fail('%s: no position reconstruction' % name)
    cam = W.find_campos(mod, ctx, D)
    if cam is None or cam['member'] != 0:
        raise Fail('%s: camera position is not cbv member 0' % name)
    try:
        nd = G.find_pixel_normal(mod, D, ctx)
    except SystemExit:
        raise Fail('%s: no unique normal decode at the pixel coordinate' % name)
    rates, tint, k0, _ = model
    k = k0 * kscale

    inits = [i for i, ln in enumerate(mod.lines) if ln.strip().startswith('OpRayQueryInitializeKHR ')]
    bsites = [i for i in inits if KU.get(mod.lines[i].split()[3]) == G.FLAGS_B]
    if not bsites or len(inits) != 3 * len(bsites):
        raise Fail('%s: %d Initialize over %d B-sites, want 3 per site' % (name, len(inits), len(bsites)))
    if src.count('OpRayQueryProceedKHR') != len(inits):
        raise Fail('%s: Proceed count != Initialize count' % name)
    if src.count('OpRayQueryGetIntersectionTKHR') != len(bsites):
        raise Fail('%s: t is read %d times over %d sites' % (name, src.count('OpRayQueryGetIntersectionTKHR'), len(bsites)))

    gv = None
    for bi in bsites:
        here = '%s@%d' % (name, bi + 1)
        bs = block_of(mod, bi)
        a_lines = [i for i in inits if bs < i < bi]
        c_lines = [i for i in inits if bi < i < block_end(mod, bi)]
        if len(a_lines) != 1 or len(c_lines) != 1:
            raise Fail('%s: A/C Initialize in the block: %d/%d, want 1/1' % (here, len(a_lines), len(c_lines)))
        ai, ci = a_lines[0], c_lines[0]
        rqA, rqB, rqC = (mod.lines[x].split()[1] for x in (ai, bi, ci))
        if len({rqA, rqB, rqC}) != 3:
            raise Fail('%s: the three queries share a variable' % here)
        A, hitA, _ = check_query(mod, D, KU, K, ai, rqA, acc, here, 'query A')
        B, hitB, _ = check_query(mod, D, KU, K, bi, rqB, acc, here, 'query B')
        Cq, hitC, end = check_query(mod, D, KU, K, ci, rqC, acc, here, 'query C')
        want_u(KU, A[2], G.FLAGS_A, here, 'A flags'); want_u(KU, B[2], G.FLAGS_B, here, 'B flags')
        want_u(KU, Cq[2], G.FLAGS_C, here, 'C flags')
        if not (A[3] == B[3] == Cq[3]):
            raise Fail('%s: the three queries use different masks' % here)
        mask = A[3]
        # ---- B: origin = P - C, tmin/tmax, direction L ----
        org = rx(D, B[4], r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'B origin')
        _check_position_triple(D, list(org.groups()), ctx, cam, 'cam', name, bi)
        pos = list(org.groups())
        want_f(K, B[5], G.TMIN_B, here, 'B tmin'); want_f(K, B[7], G.TMAX_B, here, 'B tmax')
        Lv = B[6]
        lm = rx(D, Lv, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'L vector')
        Lc = list(lm.groups())
        raw, invs = [], set()
        for c in range(3):
            m = rx(D, Lc[c], r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'L component')
            raw.append(m.group(1)); invs.add(m.group(2))
        if len(invs) != 1:
            raise Fail('%s: L components scaled by different factors' % here)
        m = rx(D, invs.pop(), r'OpFDiv %float (%\w+) (%\w+)\s*$', here, '1/|L|')
        want_f(K, m.group(1), 1.0, here, 'the numerator of 1/|L|')
        dist = m.group(2)
        m = rx(D, dist, r'OpExtInst %float %\w+ Sqrt (%\w+)\s*$', here, '|L|')
        m = rx(D, m.group(1), r'OpDot %float (%\w+) (%\w+)\s*$', here, 'L.L')
        if m.group(1) != m.group(2):
            raise Fail('%s: |L| is not sqrt(dot(raw, raw))' % here)
        m = rx(D, m.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'raw L vector')
        if list(m.groups()) != raw:
            raise Fail('%s: raw L vector is not the select triple' % here)
        isdirs, negs, subs = set(), [], []
        for c in range(3):
            m = rx(D, raw[c], r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'raw L select')
            isdirs.add(m.group(1)); negs.append(m.group(2)); subs.append(m.group(3))
        if len(isdirs) != 1:
            raise Fail('%s: the direction selects disagree on the flag' % here)
        isdir = isdirs.pop()
        m = rx(D, isdir, r'OpINotEqual %bool (%\w+) (%\w+)\s*$', here, 'directional test')
        want_u(KU, m.group(2), 0, here, 'directional test rhs')
        m = rx(D, m.group(1), r'OpBitwiseAnd %uint (%\w+) (%\w+)\s*$', here, 'directional bit')
        want_u(KU, m.group(2), G.DIRECTIONAL_BIT, here, 'directional bit')
        flags_ld = m.group(1)
        rec_f = light_record(mod, D, KU, flags_ld, here)
        dirs = [rx(D, n, r'OpFNegate %float (%\w+)\s*$', here, '-dir').group(1) for n in negs]
        rec_d = light_record(mod, D, KU, extract3(D, dirs, here, 'dir'), here)
        posx = []
        for c in range(3):
            m = rx(D, subs[c], r'OpFSub %float (%\w+) (%\w+)\s*$', here, 'lightPos - P')
            if m.group(2) != ctx['p'][c]:
                raise Fail('%s: lightPos - P subtracts %s, not the module P' % (here, m.group(2)))
            posx.append(m.group(1))
        rec_p = light_record(mod, D, KU, extract3(D, posx, here, 'lightPos'), here)
        if not (rec_p[:2] == rec_d[:2] == rec_f[:2]):
            raise Fail('%s: pos/dir/flags read different light records' % here)
        if (rec_p[2], rec_d[2], rec_f[2]) != (G.OFF_POS, G.OFF_DIR, G.OFF_FLAGS):
            raise Fail('%s: record offsets %s' % (here, (rec_p[2], rec_d[2], rec_f[2])))
        # ---- A: from the camera along P-C with the bracket ----
        am = rx(D, A[4], r'OpConstantComposite %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'A origin')
        for x in am.groups():
            want_f(K, x, 0.0, here, 'A origin component')
        tmn = rx(D, A[5], r'OpFSub %float (%\w+) (%\w+)\s*$', here, 'A tmin')
        tmx = rx(D, A[7], r'OpFAdd %float (%\w+) (%\w+)\s*$', here, 'A tmax')
        if tmn.groups() != tmx.groups():
            raise Fail('%s: A bracket is not |d| -/+ the same width' % here)
        dl, wA = tmn.groups()
        m = rx(D, wA, r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)\s*$', here, 'A bracket width')
        want_f(K, m.group(2), G.BRACKET_MIN, here, 'A bracket floor')
        m = rx(D, m.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'A relative bracket')
        if m.group(1) != dl:
            raise Fail('%s: A bracket is not relative to |d|' % here)
        want_f(K, m.group(2), G.BRACKET_REL, here, 'A bracket fraction')
        m = rx(D, dl, r'OpExtInst %float %\w+ Sqrt (%\w+)\s*$', here, '|d|')
        m = rx(D, m.group(1), r'OpDot %float (%\w+) (%\w+)\s*$', here, 'd.d')
        if m.group(1) != m.group(2) or m.group(1) != B[4]:
            raise Fail('%s: |d| is not |P - C| over the B origin' % here)
        dm = rx(D, A[6], r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'A direction')
        for c in range(3):
            m = rx(D, dm.group(c + 1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'A direction component')
            if m.group(1) != pos[c]:
                raise Fail('%s: A direction is not (P - C) scaled' % here)
            mm = rx(D, m.group(2), r'OpFDiv %float (%\w+) (%\w+)\s*$', here, '1/|d|')
            if mm.group(2) != dl:
                raise Fail('%s: A direction is not divided by |d|' % here)
        # ---- t, instance match, C ----
        tget = getter(mod, D, 'OpRayQueryGetIntersectionTKHR', rqB, KU, here, 'B committed t', bs, end)
        tsel = only(D, r'OpSelect %float ' + re.escape(hitB) + ' ' + re.escape(tget) + r' (%\w+)\s*$',
                    here, 'guarded t')
        want_f(K, tsel[1][0], G.TMAX_B, here, 'the miss t')
        t = tsel[0]
        idA = getter(mod, D, 'OpRayQueryGetIntersectionInstanceIdKHR', rqA, KU, here, 'A instance', bs, end)
        idB = getter(mod, D, 'OpRayQueryGetIntersectionInstanceIdKHR', rqB, KU, here, 'B instance', bs, end)
        same = only(D, r'OpIEqual %bool ' + re.escape(idA) + ' ' + re.escape(idB) + r'\s*$',
                    here, 'instance match')[0]
        tp = only(D, r'OpFAdd %float ' + re.escape(t) + r' (%\w+)\s*$', here, 't + push')
        want_f(K, tp[1][0], G.PUSH, here, 'push')
        tp = tp[0]
        co = rx(D, Cq[4], r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'C origin')
        for c in range(3):
            m = rx(D, co.group(c + 1), r'OpFAdd %float (%\w+) (%\w+)\s*$', here, 'C origin component')
            if m.group(1) != pos[c]:
                raise Fail('%s: C origin is not P - C + ...' % here)
            mm = rx(D, m.group(2), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'C origin step')
            if (mm.group(1), mm.group(2)) != (Lc[c], tp):
                raise Fail('%s: C origin step is not L (t + push)' % here)
        if Cq[6] != Lv:
            raise Fail('%s: C direction is not L' % here)
        want_f(K, Cq[5], G.TMIN_C, here, 'C tmin')
        m = rx(D, Cq[7], r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'C tmax')
        if m.group(1) != isdir:
            raise Fail('%s: C tmax is not selected on the directional flag' % here)
        want_f(K, m.group(2), G.TMAX_C_DIRECTIONAL, here, 'C directional tmax')
        mm = rx(D, m.group(3), r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)\s*$', here, 'C tmax floor')
        want_f(K, mm.group(2), G.TMIN_C, here, 'C tmax floor')
        mm = rx(D, mm.group(1), r'OpFSub %float (%\w+) (%\w+)\s*$', here, 'C reach')
        if (mm.group(1), mm.group(2)) != (dist, tp):
            raise Fail('%s: C reach is not dist - (t + push)' % here)
        # ---- accept ----
        visC = only(D, r'OpLogicalNot %bool ' + re.escape(hitC) + r'\s*$', here, 'C miss')[0]
        ab = only(D, r'OpLogicalAnd %bool ' + re.escape(hitA) + ' ' + re.escape(hitB) + r'\s*$',
                  here, 'A and B')[0]
        abi = only(D, r'OpLogicalAnd %bool ' + re.escape(ab) + ' ' + re.escape(same) + r'\s*$',
                   here, 'A and B and same instance')[0]
        accept = only(D, r'OpLogicalAnd %bool ' + re.escape(abi) + ' ' + re.escape(visC) + r'\s*$',
                      here, 'accept')[0]
        # ---- the mask: class == 1 AND magic AND atten > 0 ----
        m = rx(D, mask, r'OpSelect %uint (%\w+) (%\w+) (%\w+)\s*$', here, 'mask')
        want_u(KU, m.group(2), G.MASK, here, 'open mask'); want_u(KU, m.group(3), 0, here, 'shut mask')
        m = rx(D, m.group(1), r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$', here, 'gate')
        g_att = rx(D, m.group(2), r'OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$', here, 'atten > 0')
        want_f(K, g_att.group(2), 0.0, here, 'atten > 0 rhs')
        atten = g_att.group(1)
        m = rx(D, m.group(1), r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$', here, 'class AND magic')
        if m.group(2) != ok:
            raise Fail('%s: the gate does not test the magic' % here)
        g_cls = m.group(1)
        ge = rx(D, g_cls, r'OpIEqual %bool (%\w+) (%\w+)\s*$', here, 'class == 1')
        want_u(KU, ge.group(2), 1, here, 'class value')
        cls = ge.group(1)
        if not re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', D.get(cls, (0, ''))[1]):
            ph = re.match(r'OpPhi %uint (.*)$', D.get(cls, (0, ''))[1])
            srcs = re.findall(r'%\w+', ph.group(1)) if ph else []
            if not any(re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', D.get(s, (0, ''))[1])
                       for s in srcs):
                raise Fail('%s: the class is not a `word >> 5`' % here)
        # the engine's own gate ends this block and tests a product with atten in it
        term = mod.lines[end].strip()
        mb = re.match(r'OpBranchConditional (%\w+) (%\w+) (%\w+)\s*$', term)
        if not mb or not mod.lines[end - 1].strip().startswith('OpSelectionMerge '):
            raise Fail('%s: the splice block does not end in the engine\'s selection branch' % here)
        eg = rx(D, mb.group(1), r'OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$', here, "the engine's gate")
        want_f(K, eg.group(2), 0.0, here, "the engine's gate rhs")
        fac = []
        flatten_mul(D, eg.group(1), fac)
        if atten not in fac or len(fac) < 2:
            raise Fail("%s: atten is not a factor of the engine's `vis * atten > 0` product (%d factors)"
                       % (here, len(fac)))
        # colour: the record's offset-32 load, and the ONE colour-dependent factor
        stores = []
        for i in range(bi, end):
            m = re.match(r'\s*OpStore (%\w+) (%\w+)\s*$', mod.lines[i])
            if m:
                stores.append(m.groups())
        if len(stores) != 3:
            raise Fail('%s: %d accumulator stores in the block, want 3' % (here, len(stores)))
        vars3 = [s[0] for s in stores]
        if gv is None:
            gv = vars3
        elif gv != vars3:
            raise Fail('%s: sites store to different accumulators' % here)
        cols = []
        for c, (v, val) in enumerate(stores):
            m = rx(D, val, r'OpFAdd %float (%\w+) (%\w+)\s*$', here, 'accumulate')
            ld = rx(D, m.group(1), r'OpLoad %float (%\w+)\s*$', here, 'accumulator load')
            if ld.group(1) != v:
                raise Fail('%s: channel %d accumulates into a different variable' % (here, c))
            term_id = m.group(2)
            if mode == 'hit':
                s = rx(D, term_id, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'class paint gate')
                if s.group(1) != g_cls:
                    raise Fail('%s: the paint is not gated on class == 1' % here)
                want_f(K, s.group(3), 0.0, here, 'non-skin paint')
                s = rx(D, s.group(2), r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'magic paint')
                if s.group(1) != ok:
                    raise Fail('%s: the paint is not selected on the magic' % here)
                want_f(K, s.group(3), G.DIAG_RED[c], here, 'the magic-wrong colour')
                s = rx(D, s.group(2), r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'accept paint')
                if s.group(1) != accept:
                    raise Fail('%s: the paint is not selected on accept' % here)
                want_f(K, s.group(2), G.DIAG_BLUE[c], here, 'the accept colour')
                s = rx(D, s.group(3), r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'reject paint')
                if s.group(1) != abi:
                    raise Fail('%s: the reject paint is not selected on A/B/same' % here)
                want_f(K, s.group(2), G.DIAG_AMBER[c], here, 'the reject colour')
                want_f(K, s.group(3), 0.0, here, 'the nothing colour')
                continue
            s = rx(D, term_id, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', here, 'accept select')
            if s.group(1) != accept:
                raise Fail('%s: channel %d is not selected on accept' % (here, c))
            want_f(K, s.group(3), 0.0, here, 'the rejected add')
            m = rx(D, s.group(2), r'OpExtInst %float %\w+ NMin (%\w+) (%\w+)\s*$', here, 'clamp')
            want_f(K, m.group(2), G.CLAMP, here, 'clamp')
            m = rx(D, m.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'x colour')
            cols.append(m.group(2))
            m = rx(D, m.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'T x (W k atten)')
            T, wa = m.groups()
            wm = rx(D, wa, r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'W k x atten')
            if wm.group(2) != atten:
                raise Fail('%s: the wrap is not multiplied by atten' % here)
            wm = rx(D, wm.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'W x k')
            want_f(K, wm.group(2), k, here, 'k')
            wm = rx(D, wm.group(1), r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)\s*$', here, 'wrap')
            want_f(K, wm.group(2), 0.0, here, 'wrap floor')
            wm = rx(D, wm.group(1), r'OpFNegate %float (%\w+)\s*$', here, '-N.L')
            wm = rx(D, wm.group(1), r'OpDot %float (%\w+) (%\w+)\s*$', here, 'N.L')
            if wm.group(2) != Lv:
                raise Fail('%s: N.L is not against L' % here)
            nv = rx(D, wm.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', here, 'N')
            if list(nv.groups()) != list(nd['n']):
                raise Fail('%s: N is not the module\'s own decoded normal' % here)
            if c:
                m = rx(D, T, r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'tint')
                want_f(K, m.group(2), tint[c], here, 'tint[%d]' % c)
                T = m.group(1)
            m = rx(D, T, r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'half')
            want_f(K, m.group(2), 0.5, here, 'the two-lobe half')
            m = rx(D, m.group(1), r'OpFAdd %float (%\w+) (%\w+)\s*$', here, 'lobe sum')
            got = []
            for lobe in m.groups():
                e = rx(D, lobe, r'OpExtInst %float %\w+ Exp (%\w+)\s*$', here, 'lobe')
                e = rx(D, e.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$', here, 'rate x -t')
                tn = rx(D, e.group(1), r'OpFNegate %float (%\w+)\s*$', here, '-t_eff')
                fl = rx(D, tn.group(1), r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)\s*$', here, 'floor')
                if fl.group(1) != t:
                    raise Fail('%s: the floor is not on the guarded t' % here)
                want_f(K, fl.group(2), G.FLOOR, here, 'floor')
                got.append(fconst(K, e.group(2)))
            want = [float(np.float32(x)) for x in rates[c]]
            if [float(np.float32(x)) for x in got] != want:
                raise Fail('%s: channel %d rates %s, want %s' % (here, c, got, want))
        if mode == 'glow':
            rec_c = light_record(mod, D, KU, extract3(D, cols, here, 'colour'), here)
            if rec_c[:2] != rec_p[:2] or rec_c[2] != G.OFF_COL:
                raise Fail('%s: the colour is not offset 32 of the same record' % here)
            col_ld = extract3(D, cols, here, 'colour')
            dep = [f for f in fac if col_ld in cone(D, f)]
            if dep != [atten]:
                raise Fail('%s: the colour-dependent factor set is %s, not [atten]' % (here, dep))

    # ---- the write ----
    adds = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        tm = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$', D.get(m.group(3), (0, ''))[1])
        if not tm:
            continue
        lds = []
        for c in range(3):
            fa = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', D.get(tm.group(c + 1), (0, ''))[1])
            ld = fa and re.match(r'OpLoad %float (%\w+)\s*$', D.get(fa.group(2), (0, ''))[1])
            lds.append(ld.group(1) if ld else None)
        if any(lds):
            if lds != gv:
                raise Fail('%s@%d: a write adds something other than the three accumulators' % (name, i + 1))
            adds.append(i)
    if len(adds) != 1:
        raise Fail('%s: %d writes add the term, want 1' % (name, len(adds)))
    # ... and it is the DIFFUSE output: the write the Disney c1 term reaches
    c1, _ = find_c1_sites(mod)
    uses = collections.defaultdict(set)
    for k_, (_, t) in D.items():
        for o in re.findall(r'%\w+', t):
            uses[o].add(k_)
    seen = {s['scalar'] for s in c1}
    st = list(seen)
    while st:
        x = st.pop()
        for y in uses[x]:
            if y not in seen:
                seen.add(y)
                st.append(y)
    reach = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if m:
            tm = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$', D.get(m.group(3), (0, ''))[1])
            if tm and any(x in seen for x in tm.groups()[:3]):
                reach.append(i)
    if reach != adds:
        raise Fail('%s: the term is added at write line %s but the diffuse term reaches %s'
                   % (name, [a + 1 for a in adds], [r + 1 for r in reach]))
    return dict(module=name, patched=True, declined=False, sites=len(bsites), write=adds[0] + 1)


def dis(spv):
    return subprocess.run(['spirv-dis', '--no-color', spv], capture_output=True, text=True, check=True).stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--base')
    ap.add_argument('--model')
    ap.add_argument('--mode', choices=('glow', 'hit'), default='glow')
    ap.add_argument('--k-scale', type=float, default=1.0)
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, '*.dxil.spv')))
    if len(files) != 77:
        print('%s: %d compute modules, want 77' % (a.dir, len(files)), file=sys.stderr)
        sys.exit(1)
    bad = []
    if a.negative:
        for f in files:
            m = binary_marker(f)
            src = dis(f)
            if m['markers'] or m['n_lo'] or m['n_hi'] or any(op in src for op in RQ_OPS):
                bad.append('%s: carries the marker or ray-query work' % os.path.basename(f))
        if bad:
            print('\n'.join(bad), file=sys.stderr); sys.exit(1)
        print('  %s: 77 modules, no marker, no sentinel, no ray query' % a.dir)
        return
    if not (a.base and a.model):
        print('--base and --model are required', file=sys.stderr); sys.exit(1)
    model = load_model(a.model)
    patched = sites = declined = 0
    for f in files:
        n = os.path.basename(f)
        bf = os.path.join(a.base, n)
        if not os.path.isfile(bf):
            bad.append('%s: no base module' % n); continue
        with tempfile.NamedTemporaryFile('w', suffix='.spvasm', delete=False) as t:
            t.write(dis(f)); p = t.name
        try:
            r = check_module(p, f, bf, a.mode, model, a.k_scale)
            if r['patched']:
                patched += 1; sites += r['sites']
            elif r['declined']:
                declined += 1
        except Fail as e:
            bad.append(str(e))
        finally:
            os.unlink(p)
        # the raygens must not carry the marker
    for f in glob.glob(os.path.join(a.dir, '*.rgs_*.spv')):
        if binary_marker(f)['markers']:
            bad.append('%s: a RAYGEN carries the marker' % os.path.basename(f))
    if bad:
        for b in bad[:12]:
            print('    ' + b, file=sys.stderr)
        sys.exit(1)
    if patched == 0:
        print('  %s: NO module carries the splice' % a.dir, file=sys.stderr)
        sys.exit(1)
    print('  %s (--mode %s, k x %g): %d modules spliced, %d sites, %d declined by name, '
          '%d byte-identical to the base' % (a.dir, a.mode, a.k_scale, patched, sites,
                                             declined, 77 - patched))


if __name__ == '__main__':
    main()
