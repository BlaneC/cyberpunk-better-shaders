#!/usr/bin/env python3
"""verify_bump -- read the albedo-bump rung back off the SHIPPED BYTES.

handoff/115 sec 6.  This does not trust the patcher's report: it disassembles
each `.spv` that will actually be served, finds the three class-gated
normal selects structurally, walks the whole chain from those selects back
to the three albedo texel fetches and the two depth taps, checks every baked
constant against the rung's knobs, proves the pre-bump normal has no
consumer left outside the bump block (other than the curvature estimator's
own centre reads, which MUST keep the raw normal), and then interprets the
read-back constants through `dev/bump_model.bump` against the knobs.

`build_bump.sh` proves it is non-vacuous by feeding it the base, the
control, a guard-less decoy, a band-less decoy and five wrong-knob readings,
each of which it must REJECT.

The chain it insists on, bottom up:

    N''_k = OpSelect (valid && class==1) N'_k N_k      k = 0,1,2
    N'_k  = v_k * InverseSqrt(Dot(v, v))     v_k = N_k + d_k * sc
    sc    = NMin(DMAX * InverseSqrt(NMax(Dot(d, d), eps)), 1)
    d_k   = (grad_k - Dot(grad, N) * N_k) * (-H)
    grad_k= ix * dPx_k + iy * dPy_k
    ix    = gx' / NMax(Dot(dPx, dPx), eps)             iy likewise
    gx'   = gx * (1 - smoothstep(T0, T1, |gx|))        [band]  or gx
    gx    = L(x+1, y) - L(x, y)                        gy likewise
    L     = 0.2126 r^2 + 0.7152 g^2 + 0.0722 b^2       one albedo fetch each
    dPx_k = P(x+1, y)_k - P_k                          one depth fetch each
    valid = Dot(dPx,dPx) < J^2 && Dot(dPy,dPy) < J^2   [guard]
    tap coords: (x+step, y) and (x, y+step) about the centre (x, y), and the
    albedo tap and the depth tap of one axis read the SAME coordinate id.

Usage:
    python3 dev/verify_bump.py <dir-of-spv> [--height 0.010] [--t0 0.05]
        [--t1 0.12] [--dmax 0.5] [--jump 0.05] [--step 1] [--no-guard]
        [--no-band]
"""
import argparse, glob, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import wpos_core as W
import bump_model as BM
from patch_chs_brdf import load_lenient
from patch_bump import KNOWN_DECLINE, CENSUS, REC709
from verify_curv import Chain, fconst, uconst, img_src, near

FAIL = []


def bad(mod, why):
    FAIL.append('%s :: %s' % (mod, why))


def pair(C, idt, op, pred):
    """Operands of a binary `op` at idt, with the one satisfying `pred`
    second.  None if not that op or neither operand satisfies it."""
    mm = C.m(idt, op + r' %float (%\w+) (%\w+)')
    if not mm:
        return None
    a, b = mm.groups()
    if pred(b):
        return a, b
    if pred(a):
        return b, a
    return None


def find_selects(mod, C, D):
    out = []
    for idt, (ln, txt) in D.items():
        m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', txt.strip())
        if not m:
            continue
        cond, a, b = m.groups()
        ie, valid = None, None
        if C.m(cond, r'OpIEqual %bool %\w+ %uint_1'):
            ie = cond
        else:
            la = C.m(cond, r'OpLogicalAnd %bool (%\w+) (%\w+)')
            if la:
                for x, y in (la.groups(), la.groups()[::-1]):
                    if C.m(x, r'OpIEqual %bool %\w+ %uint_1'):
                        ie, valid = x, y
                        break
        if ie is None:
            continue
        pr = pair(C, a, 'OpFMul', lambda i: bool(C.ext(i, 'InverseSqrt')))
        if not pr:
            continue
        v, rr = pr
        fa = C.m(v, r'OpFAdd %float (%\w+) (%\w+)')
        if not fa or b not in fa.groups():
            continue
        dq = fa.group(1) if fa.group(2) == b else fa.group(2)
        out.append(dict(id=idt, cond=cond, ie=ie, valid=valid, nb=a, n=b,
                        rr=rr, v=v, dq=dq))
    return out


def slice_ids(D, roots, stop):
    seen, stack = set(), list(roots)
    while stack:
        i = stack.pop()
        if i in seen or i in stop or i not in D:
            continue
        seen.add(i)
        for o in re.findall(r'%\w+', D[i][1]):
            stack.append(o)
    return seen


def check_module(path, knobs):
    mod, _ = load_lenient(path)
    D = W.defs_index(mod)
    name = mod.dxil or os.path.basename(path)
    C = Chain(mod, D)
    sels = find_selects(mod, C, D)

    if name in KNOWN_DECLINE:
        if sels:
            bad(name, 'declined module carries a bumped normal')
        return dict(declined=True)
    if len(sels) != 3:
        bad(name, '%d gated normal selects, want exactly 3' % len(sels))
        return None
    if len({s['cond'] for s in sels}) != 1 or len({s['rr'] for s in sels}) != 1:
        bad(name, 'the three selects do not share one gate and one normalise')
        return None
    nset = {s['n'] for s in sels}
    if len(nset) != 3:
        bad(name, 'the three selects fall back to the same normal component')
        return None
    # order the triple by the v3 construct of N the block builds
    vn = [i for i, (_l, t) in D.items()
          if re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$', t)
          and set(t.split()[2:]) == nset]
    if len(vn) != 1:
        bad(name, '%d v3 constructs of N in the block, want 1' % len(vn))
        return None
    order = D[vn[0]][1].split()[2:]
    sels.sort(key=lambda s: order.index(s['n']))
    n = [s['n'] for s in sels]
    s0 = sels[0]

    # ---- 1. the gate --------------------------------------------------------
    if knobs['guard']:
        if s0['valid'] is None:
            bad(name, 'the gate is bare class==1 -- the silhouette guard is missing')
            return None
    else:
        if s0['valid'] is not None:
            bad(name, 'the gate carries a guard but --no-guard was asserted')
            return None

    # ---- 2. N' = normalize(N + d') ----------------------------------------
    rr = s0['rr']
    isq = C.ext(rr, 'InverseSqrt')
    l2 = isq.group(1).strip()
    dd = C.m(l2, r'OpDot %float (%\w+) (%\w+)')
    if not dd or dd.group(1) != dd.group(2):
        bad(name, 'the normalise is not InverseSqrt(Dot(v, v))')
        return None
    cc = C.m(dd.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    if not cc or list(cc.groups()) != [s['v'] for s in sels]:
        bad(name, 'the normalised vector is not (N + d) in the select order')
        return None
    scs, ds = set(), []
    for s in sels:
        pr = C.m(s['dq'], r'OpFMul %float (%\w+) (%\w+)')
        if not pr:
            bad(name, 'd\' is not a product')
            return None
        ds.append(pr.group(1))
        scs.add(pr.group(2))
    if len(scs) != 1:
        bad(name, 'the three components are clamped by different scales')
        return None
    sc = scs.pop()
    nm = C.ext(sc, 'NMin')
    if not nm:
        bad(name, 'the tilt clamp is not an NMin')
        return None
    sc0, one = nm.group(1).split()
    if fconst(mod, one) != 1.0:
        sc0, one = one, sc0
    if fconst(mod, one) != 1.0:
        bad(name, 'the tilt clamp does not pivot at 1.0')
    pr = pair(C, sc0, 'OpFMul', lambda i: fconst(mod, i) is not None)
    if not pr:
        bad(name, 'no DMAX multiply')
        return None
    r, dmaxid = pr
    if not near(fconst(mod, dmaxid), knobs['dmax']):
        bad(name, 'DMAX is %s, expected %g' % (fconst(mod, dmaxid), knobs['dmax']))
    isq2 = C.ext(r, 'InverseSqrt')
    if not isq2:
        bad(name, '|d| is not an InverseSqrt')
        return None
    nx = C.ext(isq2.group(1).strip(), 'NMax')
    if not nx:
        bad(name, '|d|^2 is not floored')
        return None
    m2, eps_id = nx.group(1).split()
    dd2 = C.m(m2, r'OpDot %float (%\w+) (%\w+)')
    if not dd2 or dd2.group(1) != dd2.group(2):
        bad(name, '|d|^2 is not Dot(d, d)')
        return None
    cd = C.m(dd2.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    if not cd or list(cd.groups()) != ds:
        bad(name, 'the clamped vector is not d in the select order')
        return None

    # ---- 3. d = -H * (grad - (grad.N) N) ----------------------------------
    grads, gns, hs = [], set(), []
    for k, d in enumerate(ds):
        pr = pair(C, d, 'OpFMul', lambda i: fconst(mod, i) is not None)
        if not pr:
            bad(name, 'd_%d is not scaled by a constant' % k)
            return None
        t, h = pr
        hs.append(fconst(mod, h))
        fs = C.m(t, r'OpFSub %float (%\w+) (%\w+)')
        if not fs:
            bad(name, 'tangential projection %d is not a subtraction' % k)
            return None
        g, along = fs.groups()
        pr = pair(C, along, 'OpFMul', lambda i: i == n[k])
        if not pr:
            bad(name, 'the along-N term %d does not multiply N_%d' % (k, k))
            return None
        gns.add(pr[0])
        grads.append(g)
    if len(set(hs)) != 1 or not near(-hs[0], knobs['height'], 1e-6):
        bad(name, '-H is %s, expected %g' % (hs, -knobs['height']))
    if len(gns) != 1:
        bad(name, 'three different grad.N dots')
        return None
    gn = gns.pop()
    dg = C.m(gn, r'OpDot %float (%\w+) (%\w+)')
    if not dg or vn[0] not in dg.groups():
        bad(name, 'grad.N does not dot against the N construct')
        return None
    vg = dg.group(1) if dg.group(2) == vn[0] else dg.group(2)
    cg = C.m(vg, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    if not cg or list(cg.groups()) != grads:
        bad(name, 'the gradient vector is not grad in the select order')
        return None

    # ---- 4. grad = ix dPx + iy dPy ----------------------------------------
    ixs, iys, dpx, dpy = set(), set(), [], []
    for k, g in enumerate(grads):
        fa = C.m(g, r'OpFAdd %float (%\w+) (%\w+)')
        if not fa:
            bad(name, 'grad_%d is not a sum of two axis terms' % k)
            return None
        terms = []
        for tm in fa.groups():
            mm = C.m(tm, r'OpFMul %float (%\w+) (%\w+)')
            if not mm:
                bad(name, 'grad_%d axis term is not a product' % k)
                return None
            terms.append(mm.groups())
        ixs.add(terms[0][0]); iys.add(terms[1][0])
        dpx.append(terms[0][1]); dpy.append(terms[1][1])
    if len(ixs) != 1 or len(iys) != 1:
        bad(name, 'the axis scalars are not shared across the components')
        return None
    ix, iy = ixs.pop(), iys.pop()

    axes, qs, gs, tapco = [], [], [], []
    for ax, (i_, dp) in enumerate(((ix, dpx), (iy, dpy))):
        dv = C.m(i_, r'OpFDiv %float (%\w+) (%\w+)')
        if not dv:
            bad(name, 'axis %d scalar is not g / |dP|^2' % ax)
            return None
        gp, den = dv.groups()
        nx = C.ext(den, 'NMax')
        if not nx:
            bad(name, 'axis %d |dP|^2 is not floored' % ax)
            return None
        q, e2 = nx.group(1).split()
        if e2 != eps_id:
            bad(name, 'axis %d uses a different eps than the clamp' % ax)
        dq_ = C.m(q, r'OpDot %float (%\w+) (%\w+)')
        if not dq_ or dq_.group(1) != dq_.group(2):
            bad(name, 'axis %d |dP|^2 is not Dot(dP, dP)' % ax)
            return None
        cp = C.m(dq_.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
        if not cp or list(cp.groups()) != dp:
            bad(name, 'axis %d |dP|^2 is not over the dP used by grad' % ax)
            return None
        qs.append(q)
        gs.append(gp)
        axes.append(dp)

    # ---- 5. the depth taps --------------------------------------------------
    dimgs, centres, lods = set(), [], set()
    for ax, dp in enumerate(axes):
        cen, nb = [], []
        for k in range(3):
            fs = C.m(dp[k], r'OpFSub %float (%\w+) (%\w+)')
            if not fs:
                bad(name, 'dP axis %d component %d is not a subtraction' % (ax, k))
                return None
            nb.append(fs.group(1)); cen.append(fs.group(2))
        centres.append(tuple(cen))
        fn = C.fetches(nb[0])
        fc = C.fetches(cen[0])
        if len(fn) != 1 or len(fc) != 1:
            bad(name, 'axis %d: %d/%d depth fetches under neighbour/centre P'
                % (ax, len(fn), len(fc)))
            return None
        dimgs.add(img_src(C, fn[0][0])); dimgs.add(img_src(C, fc[0][0]))
        lods.add(fn[0][2]); lods.add(fc[0][2])
        tapco.append(fn[0][1])
        cc0 = C.m(fc[0][1], r'OpCompositeConstruct %v2uint (%\w+) (%\w+)')
        if not cc0:
            bad(name, 'the centre P coordinate is not a v2uint construct')
            return None
        centres[-1] = (tuple(cen), cc0.groups())
    if len({c[0] for c in centres}) != 1 or len({c[1] for c in centres}) != 1:
        bad(name, 'the two axes are differenced against different centres')
        return None
    cx, cy = centres[0][1]
    if len(dimgs) != 1:
        bad(name, 'the depth taps read %d images' % len(dimgs))
        return None
    dimg = dimgs.pop()

    def off(a, b):
        ia = C.m(a, r'OpIAdd %uint (%\w+) (%\w+)')
        if not ia:
            return None
        p1, p2 = ia.groups()
        if p1 == b and uconst(mod, p2) is not None:
            return uconst(mod, p2)
        if p2 == b and uconst(mod, p1) is not None:
            return uconst(mod, p1)
        return None

    tapxy = []
    for ax, co in enumerate(tapco):
        cc = C.m(co, r'OpCompositeConstruct %v2uint (%\w+) (%\w+)')
        if not cc:
            bad(name, 'axis %d tap coordinate is not a v2uint construct' % ax)
            return None
        tapxy.append(cc.groups())
    (a0, b0), (a1, b1) = tapxy
    if not (off(a0, cx) == knobs['step'] and b0 == cy
            and a1 == cx and off(b1, cy) == knobs['step']):
        bad(name, 'the taps are not (x+%d, y) and (x, y+%d) about the centre'
            % (knobs['step'], knobs['step']))

    # ---- 6. the band and the luma differences -------------------------------
    gl = []
    for ax, gp in enumerate(gs):
        if knobs['band']:
            pr = C.m(gp, r'OpFMul %float (%\w+) (%\w+)')
            if not pr:
                bad(name, 'axis %d: no edge-kill band (g is not g*w)' % ax)
                return None
            g, w = pr.groups()
            fs = C.m(w, r'OpFSub %float (%\w+) (%\w+)')
            if not fs or fconst(mod, fs.group(1)) != 1.0:
                bad(name, 'axis %d: band weight is not 1 - smoothstep' % ax)
                return None
            poly = C.m(fs.group(2), r'OpFMul %float (%\w+) (%\w+)')
            if not poly:
                bad(name, 'axis %d: band polynomial missing' % ax)
                return None
            uu, th = poly.groups()
            u2 = C.m(uu, r'OpFMul %float (%\w+) (%\w+)')
            if not u2 or u2.group(1) != u2.group(2):
                bad(name, 'axis %d: band is not u*u*(3-2u)' % ax)
                return None
            u = u2.group(1)
            t3 = C.m(th, r'OpFSub %float (%\w+) (%\w+)')
            if not t3 or fconst(mod, t3.group(1)) != 3.0:
                bad(name, 'axis %d: band is not (3 - 2u)' % ax)
                return None
            tw = C.m(t3.group(2), r'OpFMul %float (%\w+) (%\w+)')
            two = [x for x in tw.groups() if x != u] if tw else []
            if not tw or u not in tw.groups() or not two \
               or fconst(mod, two[0]) != 2.0:
                bad(name, 'axis %d: band is not 2u' % ax)
                return None
            cl = C.ext(u, 'NClamp')
            if not cl:
                bad(name, 'axis %d: band u is not saturated' % ax)
                return None
            u1, lo, hi = cl.group(1).split()
            if fconst(mod, lo) != 0.0 or fconst(mod, hi) != 1.0:
                bad(name, 'axis %d: band saturate is not [0, 1]' % ax)
            pr = pair(C, u1, 'OpFMul', lambda i: fconst(mod, i) is not None)
            if not pr:
                bad(name, 'axis %d: band has no 1/(T1-T0) scale' % ax)
                return None
            u0, inv = pr
            if not near(fconst(mod, inv), 1.0 / (knobs['t1'] - knobs['t0']), 1e-5):
                bad(name, 'axis %d: 1/(T1-T0) is %s, expected %g'
                    % (ax, fconst(mod, inv), 1.0 / (knobs['t1'] - knobs['t0'])))
            fs0 = C.m(u0, r'OpFSub %float (%\w+) (%\w+)')
            if not fs0 or not near(fconst(mod, fs0.group(2)), knobs['t0']):
                bad(name, 'axis %d: T0 is not %g' % (ax, knobs['t0']))
                return None
            ab = C.ext(fs0.group(1), 'FAbs')
            if not ab or ab.group(1).strip() != g:
                bad(name, 'axis %d: the band does not gate on |g| of the same g' % ax)
                return None
            band_t0 = fconst(mod, fs0.group(2))
            band_t1 = band_t0 + 1.0 / fconst(mod, inv)
        else:
            g = gp
            band_t0 = band_t1 = None
            if C.m(gp, r'OpFMul %float (%\w+) (%\w+)'):
                bad(name, 'axis %d: g is banded but --no-band was asserted' % ax)
                return None
        gd = C.m(g, r'OpFSub %float (%\w+) (%\w+)')
        if not gd:
            bad(name, 'axis %d: g is not L(neighbour) - L(centre)' % ax)
            return None
        gl.append(gd.groups())
    if gl[0][1] != gl[1][1]:
        bad(name, 'the two luma differences use different centres')

    # ---- 7. the three luma taps ---------------------------------------------
    aimgs, alods, acos = set(), set(), []
    for L in (gl[0][1], gl[0][0], gl[1][0]):
        fa = C.m(L, r'OpFAdd %float (%\w+) (%\w+)')
        if not fa:
            bad(name, 'luma is not a sum')
            return None
        fa2 = C.m(fa.group(1), r'OpFAdd %float (%\w+) (%\w+)')
        if not fa2:
            bad(name, 'luma is not a three-term sum')
            return None
        terms = [fa2.group(1), fa2.group(2), fa.group(2)]
        fetch, chans = set(), {}
        for tm in terms:
            pr = pair(C, tm, 'OpFMul', lambda i: fconst(mod, i) is not None)
            if not pr:
                bad(name, 'luma term is not weight * channel')
                return None
            sq, wt = pr
            s2 = C.m(sq, r'OpFMul %float (%\w+) (%\w+)')
            if not s2 or s2.group(1) != s2.group(2):
                bad(name, 'luma channel is not squared (the sqrt decode)')
                return None
            ex = C.m(s2.group(1), r'OpCompositeExtract %float (%\w+) (\d)')
            if not ex:
                bad(name, 'luma channel is not a fetch component')
                return None
            fetch.add(ex.group(1))
            chans[int(ex.group(2))] = fconst(mod, wt)
        if len(fetch) != 1:
            bad(name, 'one luma reads %d fetches' % len(fetch))
            return None
        if sorted(chans) != [0, 1, 2] or any(not near(chans[k], REC709[k])
                                             for k in range(3)):
            bad(name, 'luma weights are %s, not Rec.709' % chans)
        f = fetch.pop()
        mf = C.m(f, r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)')
        if not mf:
            bad(name, 'the albedo tap is not a v4float fetch')
            return None
        aimgs.add(img_src(C, mf.group(1)))
        alods.add(mf.group(3))
        acos.append(mf.group(2))
    if len(aimgs) != 1 or len(alods) != 1:
        bad(name, 'the albedo taps read %d images at %d LODs' % (len(aimgs), len(alods)))
        return None
    aimg = aimgs.pop()
    if aimg == dimg:
        bad(name, 'albedo and depth are the same image -- a slot is wrong')
    if acos[1] != tapco[0] or acos[2] != tapco[1]:
        bad(name, 'an albedo tap and its depth tap read different coordinate ids')
    c0 = C.m(acos[0], r'OpCompositeConstruct %v2uint (%\w+) (%\w+)')
    if not c0 or c0.groups() != (cx, cy):
        bad(name, 'the centre albedo tap is not at the centre P coordinate')

    # ---- 8. the guard -------------------------------------------------------
    jump_read = None
    if knobs['guard']:
        la = C.m(s0['valid'], r'OpLogicalAnd %bool (%\w+) (%\w+)')
        if not la:
            bad(name, 'guard is not a LogicalAnd of two tests')
            return None
        tested = set()
        for b in la.groups():
            lt = C.m(b, r'OpFOrdLessThan %bool (%\w+) (%\w+)')
            if not lt:
                bad(name, 'guard test is not OpFOrdLessThan (NaN must fall back)')
                return None
            tested.add(lt.group(1))
            j2 = fconst(mod, lt.group(2))
            if not near(j2, knobs['jump'] ** 2):
                bad(name, 'guard threshold %s != jump^2 = %g' % (j2, knobs['jump'] ** 2))
            jump_read = j2
        if tested != set(qs):
            bad(name, 'the guard tests are not on the same |dP|^2 the gradient divides by')

    # ---- 9. no consumer of the pre-bump normal survives ----------------------
    inside = slice_ids(D, [s['id'] for s in sels], set(n))
    taps, live = [], []
    for k in range(3):
        tok = re.compile(r'(?<![%\w])' + re.escape(n[k]) + r'(?![\w])')
        t_k = 0
        for j, ln in enumerate(mod.lines):
            if not tok.search(ln):
                continue
            md = re.match(r'\s*(%\w+)\s*=', ln)
            if md and md.group(1) == n[k]:
                continue
            if md and md.group(1) in inside:
                continue
            if re.match(r'\s*%\w+\s*=\s*OpFSub %float (%\w+) ' + re.escape(n[k])
                        + r'\s*$', ln):
                t_k += 1            # the curvature estimator's centre read
                continue
            bad(name, 'a consumer of the pre-bump normal survives: %s' % ln.strip())
            return None
        taps.append(t_k)
        tk = re.compile(r'(?<![%\w])' + re.escape(sels[k]['id']) + r'(?![\w])')
        live.append(sum(1 for j, ln in enumerate(mod.lines) if tk.search(ln)
                        and not re.match(r'\s*' + re.escape(sels[k]['id']) + r'\s*=', ln)))
    if len(set(taps)) != 1 or taps[0] not in (0, 2):
        bad(name, 'curvature centre reads of the raw normal are %s, want 0 or 2 each' % taps)
    if min(live) < 1:
        bad(name, 'a bumped normal component has no consumer')

    # ---- 10. interpret the read-back constants through the model -----------
    H = -hs[0]
    dmax = fconst(mod, dmaxid)
    jump = jump_read ** 0.5 if jump_read is not None else knobs['jump']
    N = np.array([0.3, 0.1, 0.949], np.float32); N /= np.sqrt(N @ N)
    ex, ey = np.array([1e-3, 2e-4, 0], np.float32), np.array([-1e-4, 1.1e-3, 1e-4], np.float32)
    for gx, gy in ((0.02, -0.01), (0.049, 0.0), (0.0, 0.3), (0.11, 0.06)):
        want = BM.bump(N, gx, gy, ex, ey, knobs['height'], knobs['t0'], knobs['t1'],
                       knobs['dmax'], knobs['jump'], knobs['guard'], knobs['band'])
        got = BM.bump(N, gx, gy, ex, ey, H,
                      band_t0 if knobs['band'] else knobs['t0'],
                      band_t1 if knobs['band'] else knobs['t1'],
                      dmax, jump, knobs['guard'], knobs['band'])
        if np.max(np.abs(want[0] - got[0])) > 1e-5:
            bad(name, 'read-back constants disagree with the model at g=(%g,%g)' % (gx, gy))
            break
    return dict(declined=False, taps=taps[0], live=live)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--height', type=float, default=BM.HEIGHT)
    ap.add_argument('--t0', type=float, default=BM.T0)
    ap.add_argument('--t1', type=float, default=BM.T1)
    ap.add_argument('--dmax', type=float, default=BM.DMAX)
    ap.add_argument('--jump', type=float, default=BM.JUMP)
    ap.add_argument('--step', type=int, default=1)
    ap.add_argument('--no-guard', action='store_true')
    ap.add_argument('--no-band', action='store_true')
    a = ap.parse_args()
    knobs = dict(height=a.height, t0=a.t0, t1=a.t1, dmax=a.dmax, jump=a.jump,
                 step=a.step, guard=not a.no_guard, band=not a.no_band)
    files = sorted(glob.glob(os.path.join(a.dir, '*.dxil.spv')))
    if not files:
        sys.exit('verify_bump: no *.dxil.spv in ' + a.dir)
    tmp = tempfile.mkdtemp(prefix='verify_bump.')
    n_patched = n_declined = n_raw = n_phi = 0
    for f in files:
        asm = os.path.join(tmp, os.path.basename(f) + '.spvasm')
        r = subprocess.run(['spirv-dis', f, '-o', asm], capture_output=True, text=True)
        if r.returncode != 0:
            bad(os.path.basename(f), 'spirv-dis failed')
            continue
        res = check_module(asm, knobs)
        if res is None:
            continue
        if res['declined']:
            n_declined += 1
        else:
            n_patched += 1
            if res['taps'] == 2:
                n_raw += 1
            else:
                n_phi += 1
    print('  modules            : %d' % len(files))
    print('  patched            : %d  (census %d)' % (n_patched, CENSUS['patched_modules']))
    print('  declined by name   : %d  (%s)' % (n_declined, ', '.join(sorted(KNOWN_DECLINE))))
    print('  shading-normal phi : %d  (census %d);  raw decode: %d  (census %d)'
          % (n_phi, CENSUS['phi_modules'], n_raw, CENSUS['raw_modules']))
    if len(files) != CENSUS['modules']:
        bad('SET', '%d modules, census %d' % (len(files), CENSUS['modules']))
    if n_patched != CENSUS['patched_modules']:
        bad('SET', '%d patched, census %d' % (n_patched, CENSUS['patched_modules']))
    if n_declined != len(KNOWN_DECLINE):
        bad('SET', '%d declined, expected %d' % (n_declined, len(KNOWN_DECLINE)))
    if (n_phi, n_raw) != (CENSUS['phi_modules'], CENSUS['raw_modules']):
        bad('SET', 'phi/raw split %d/%d, census %d/%d'
            % (n_phi, n_raw, CENSUS['phi_modules'], CENSUS['raw_modules']))
    if FAIL:
        for x in FAIL[:20]:
            sys.stderr.write('  FAIL  %s\n' % x)
        sys.stderr.write('  %d failures\n' % len(FAIL))
        sys.exit(1)
    print('  ALL PASS')


if __name__ == '__main__':
    main()
