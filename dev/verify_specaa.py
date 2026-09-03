#!/usr/bin/env python3
"""verify_specaa -- re-derive the specular-AA claim from the SHIPPED bytes.

    python3 dev/verify_specaa.py <rung-dir> [--mode feature|vis|none]
            [--kappa 0.5] [--sigma2-max 0.18] [--metal-min 0.3]
            [--pix-angle 0.001311] [--foot0 0.010] [--foot1 0.050]

Nothing here reads a build report or a patcher's JSON.  Every rung file is
disassembled and the following are re-derived (handoff/108 sec 6.1):

 1. the selection is complete: 77 compute + 16 raygen;
 2. exactly 75 compute modules carry the splice and the other two are the two
    declined BY HASH -- and the declines are checked to be the hashes
    patch_specaa.KNOWN_DECLINE names, not merely "two of them";
 3. COVERAGE.  Every alpha the splice widened is re-found from the SHIPPED
    bytes by its own anchor -- a2 = alpha*alpha feeding D = a2/(x*pi), WITHOUT
    the line windows patch_skin_brdf.find_ggx_sites uses, so the check survives
    a second pass inserting instructions between D and its consumers.  Every
    specaa select must BE such an alpha (no splice outside a GGX D term), the
    count must be exactly the census 303, and the 343 - 303 = 40 D terms the
    repo's shared detector does not report are asserted as a KNOWN gap rather
    than glossed (handoff/108 sec 9);
 4. THE REWRITE IS TOTAL.  The pre-splice alpha id survives in exactly two
    places -- the `alpha*alpha` of the widening and the else-arm of the select.
    Any other surviving use is an evaluation/sampling disagreement (the
    08-DUAL-LOBE bias) and fails;
 5. SHAPE.  sigma2 = NClamp(v*kappa*w, 0, s2max) with v the sum of two squared
    normal differences taken from three OpImageFetches on ONE image at
    (x,y), (x+1,y) and (x,y+1), and w the distance ramp over |P - C|;
 6. PROVENANCE.  The gate reads the metallic operand of the module's own
    F0 = lerp(0.04, albedo, metallic) triple; P comes from the module's own
    reconstruction chain (registers[0]+12 view CBV, registers[1]+0 depth), both
    re-derived here from the bytes;
 7. CONSTANTS to the float32 bit, and CLOSED FORM: the emitted chain is
    INTERPRETED out of the disassembly over a grid of G-buffer texels and
    positions and compared against the model in this file;
 8. NON-VACUITY.  --mode none asserts the opposite: zero splices anywhere.  The
    build runs the verifier both ways -- on the base and on the byte-identical
    control it must pass only with --mode none and FAIL without it, and the
    feature rungs must FAIL --mode none and fail on the wrong knob values.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient, uses_of
import wpos_core as W
from patch_cfres import defs_index, find_f0_metal_triples, forward_closure
from patch_specaa import KNOWN_DECLINE, CENSUS

TOL = 2e-5


class Fail(Exception):
    pass


def f32(x):
    return np.float32(x)


def consts(mod):
    out = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)', ln)
        if m:
            try:
                out[m.group(1)] = f32(float(m.group(2)))
            except ValueError:
                pass
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %uint (\d+)', ln)
        if m:
            out[m.group(1)] = np.uint32(int(m.group(2)))
    return out


def evaluate(D, K, target, env, memo):
    """Interpret the pure SSA chain reaching `target`, in float32."""
    if target in env:
        return env[target]
    if target in K:
        return K[target]
    if target in memo:
        return memo[target]
    if target not in D:
        raise Fail('evaluator hit an unbound leaf %s' % target)
    txt = D[target][1]
    op = txt.split()[0]
    a = re.findall(r'%\w+', txt)[1:]
    E = lambda i: evaluate(D, K, i, env, memo)
    if op == 'OpFMul':
        v = f32(E(a[0]) * E(a[1]))
    elif op == 'OpFAdd':
        v = f32(E(a[0]) + E(a[1]))
    elif op == 'OpFSub':
        v = f32(E(a[0]) - E(a[1]))
    elif op == 'OpFDiv':
        v = f32(E(a[0]) / E(a[1]))
    elif op == 'OpCompositeConstruct':
        v = tuple(E(x) for x in a)
    elif op == 'OpDot':
        x, y = E(a[0]), E(a[1])
        s = f32(0.0)
        for i in range(len(x)):
            s = f32(s + f32(x[i] * y[i]))
        v = s
    elif op == 'OpFOrdEqual':
        v = bool(E(a[0]) == E(a[1]))
    elif op == 'OpFOrdGreaterThan':
        v = bool(E(a[0]) > E(a[1]))
    elif op == 'OpLogicalAnd':
        v = bool(E(a[0]) and E(a[1]))
    elif op == 'OpLogicalOr':
        v = bool(E(a[0]) or E(a[1]))
    elif op == 'OpSelect':
        v = E(a[1]) if E(a[0]) else E(a[2])
    elif op == 'OpExtInst':
        name = txt.split()[3]
        if name == 'NClamp':
            v = f32(np.minimum(np.maximum(E(a[1]), E(a[2])), E(a[3])))
        elif name == 'InverseSqrt':
            v = f32(1.0 / np.sqrt(E(a[1])))
        elif name == 'Sqrt':
            v = f32(np.sqrt(E(a[1])))
        elif name == 'NMax':
            v = f32(np.maximum(E(a[1]), E(a[2])))
        elif name == 'NMin':
            v = f32(np.minimum(E(a[1]), E(a[2])))
        else:
            raise Fail('unmodelled GLSL op %s' % name)
    else:
        raise Fail('unmodelled op %s' % op)
    memo[target] = v
    return v


# ------------------------------------------------------------------- model
def sigma2_model(tex, pc, bias, want):
    """sigma2 from three raw G-buffer texels and the camera-relative P.

    Written from handoff/108 sec 2's formula, not from the emitter: the shapes
    the verifier walks and this function share nothing but the algebra.
    """
    b = f32(bias)

    def nrm(t):
        d = [f32(f32(t[k]) + b) for k in range(3)]
        s = f32(0.0)
        for k in range(3):
            s = f32(s + f32(d[k] * d[k]))
        r = f32(1.0 / np.sqrt(s))
        return [f32(r * d[k]) for k in range(3)]

    n = [nrm(t) for t in tex]

    def d2(i):
        d = [f32(n[i][k] - n[0][k]) for k in range(3)]
        s = f32(0.0)
        for k in range(3):
            s = f32(s + f32(d[k] * d[k]))
        return s

    v = f32(d2(1) + d2(2))
    if all(f32(x) == f32(0.0) for x in tex[1]) or \
       all(f32(x) == f32(0.0) for x in tex[2]):
        v = f32(0.0)
    s = f32(0.0)
    for k in range(3):
        s = f32(s + f32(f32(pc[k]) * f32(pc[k])))
    dist = f32(np.sqrt(s))
    foot = f32(dist * f32(want['pix_angle']))
    w = f32(np.minimum(np.maximum(
        f32(f32(foot - f32(want['foot0'])) * f32(want['inv_span'])), 0.0), 1.0))
    s2 = f32(f32(v * f32(want['kappa'])) * w)
    return f32(np.minimum(np.maximum(s2, 0.0), f32(want['sigma2_max'])))


# ------------------------------------------------------------- shape walks
def _m(D, i, pat):
    return re.match(pat, D.get(i, (0, ''))[1])


def find_ggx_d_alphas(mod, D):
    """Every alpha whose square is the numerator of a GGX D term.

    patch_skin_brdf.find_ggx_sites is the repo's direct-light GGX detector and
    the patcher uses it, but it searches for the Vis*D product and the
    per-channel outputs inside 80- and 160-LINE WINDOWS.  A second pass that
    inserts instructions between D and its consumers -- which is exactly what
    the specaa-cfres stack does -- pushes those consumers out of the window and
    the detector goes quiet.  A verifier that used it would then read a stacked
    rung as uncovered and pass a broken one that happened to shrink.  So the
    verifier anchors on the part of the shape that no insertion can move:

        D = OpFDiv(a2, OpFMul(x, pi)),  a2 = OpFMul(alpha, alpha)
    """
    pi = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float 3.14159274\b', ln)
        if m:
            pi = m.group(1)
            break
    if pi is None:
        raise Fail('%s: no 1/pi... no pi constant' % mod.name)
    out = set()
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFDiv %float (%\d+) (%\d+)\s*$', ln)
        if not m:
            continue
        _d, a2, den = m.groups()
        dn = D.get(den, (0, ''))[1]
        if not re.match(r'OpFMul %float %\d+ ' + re.escape(pi) + r'\s*$', dn):
            continue
        am = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', D.get(a2, (0, ''))[1])
        if am and am.group(1) == am.group(2):
            out.add(am.group(1))
    return out


def walk_tap(name, D, gl, n3):
    """Three FMul(rs, d_k) back to one OpImageFetch.  Returns (fetch, coord,
    img, lod, bias, [raw extract ids])."""
    rs = None
    ds = []
    for x in n3:
        mm = _m(D, x, r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mm:
            raise Fail('%s: normal component %s is not an FMul' % (name, x))
        if rs is None:
            rs = mm.group(1)
        elif rs != mm.group(1):
            raise Fail('%s: the three normal components do not share one '
                       'InverseSqrt' % name)
        ds.append(mm.group(2))
    mi = _m(D, rs, r'OpExtInst %float ' + re.escape(gl) + r' InverseSqrt (%\w+)\s*$')
    if not mi:
        raise Fail('%s: %s is not an InverseSqrt' % (name, rs))
    md = _m(D, mi.group(1), r'OpDot %float (%\w+) (%\w+)\s*$')
    if not md or md.group(1) != md.group(2):
        raise Fail('%s: the normalisation is not a self-dot' % name)
    mv = _m(D, md.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$')
    if not mv or list(mv.groups()) != ds:
        raise Fail('%s: the self-dot is not over the decoded components' % name)
    raw, bias, fetch = [], None, None
    for d in ds:
        ma = _m(D, d, r'OpFAdd %float (%\w+) (%float_\w+)\s*$')
        if not ma:
            raise Fail('%s: decode %s is not `texel + bias`' % (name, d))
        if bias is None:
            bias = ma.group(2)
        elif bias != ma.group(2):
            raise Fail('%s: the three decodes use different biases' % name)
        me = _m(D, ma.group(1), r'OpCompositeExtract %float (%\w+) (\d)\s*$')
        if not me:
            raise Fail('%s: %s is not a texel component' % (name, ma.group(1)))
        if fetch is None:
            fetch = me.group(1)
        elif fetch != me.group(1):
            raise Fail('%s: the three components come from different fetches'
                       % name)
        raw.append(ma.group(1))
    mf = _m(D, fetch, r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$')
    if not mf:
        raise Fail('%s: %s is not an OpImageFetch' % (name, fetch))
    return dict(fetch=fetch, img=mf.group(1), coord=mf.group(2),
                lod=mf.group(3), bias=bias, raw=raw)


def walk_sigma2(name, D, K, gl, sig, want):
    """The whole estimator, from sigma2 back to the three taps and P - C."""
    mc = _m(D, sig, r'OpExtInst %float ' + re.escape(gl)
            + r' NClamp (%\w+) (%\w+) (%\w+)\s*$')
    if not mc:
        raise Fail('%s: sigma2 %s is not an NClamp' % (name, sig))
    if K.get(mc.group(2)) != f32(0.0):
        raise Fail('%s: sigma2 floor is not 0' % name)
    if mc.group(3) not in K or \
       float(K[mc.group(3)]) != float(f32(want['sigma2_max'])):
        raise Fail('%s: sigma2 ceiling is %s, want %g'
                   % (name, K.get(mc.group(3)), want['sigma2_max']))
    m2 = _m(D, mc.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m2:
        raise Fail('%s: sigma2 is not scaled by the ramp' % name)
    m1 = _m(D, m2.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m1:
        raise Fail('%s: the variance is not scaled by kappa' % name)
    kid = m1.group(2)
    if kid not in K or float(K[kid]) != float(f32(want['kappa'])):
        raise Fail('%s: kappa is %s, want %g' % (name, K.get(kid), want['kappa']))
    # ---- the ramp
    wc = _m(D, m2.group(2), r'OpExtInst %float ' + re.escape(gl)
            + r' NClamp (%\w+) (%\w+) (%\w+)\s*$')
    if not wc:
        raise Fail('%s: the distance ramp is not clamped' % name)
    wr = _m(D, wc.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not wr or wr.group(2) not in K or \
       abs(float(K[wr.group(2)]) - float(f32(want['inv_span']))) > 1e-6:
        raise Fail('%s: ramp span is %s, want 1/(foot1-foot0) = %.9g'
                   % (name, K.get(wr.group(2)) if wr else None,
                      want['inv_span']))
    fm = _m(D, wr.group(1), r'OpFSub %float (%\w+) (%\w+)\s*$')
    if not fm or fm.group(2) not in K or \
       float(K[fm.group(2)]) != float(f32(want['foot0'])):
        raise Fail('%s: ramp origin is %s, want %g'
                   % (name, K.get(fm.group(2)) if fm else None, want['foot0']))
    ft = _m(D, fm.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not ft or ft.group(2) not in K or \
       float(K[ft.group(2)]) != float(f32(want['pix_angle'])):
        raise Fail('%s: pixel angle is %s, want %g'
                   % (name, K.get(ft.group(2)) if ft else None,
                      want['pix_angle']))
    ds = _m(D, ft.group(1), r'OpExtInst %float ' + re.escape(gl) + r' Sqrt (%\w+)\s*$')
    if not ds:
        raise Fail('%s: the distance is not a Sqrt' % name)
    dd = _m(D, ds.group(1), r'OpDot %float (%\w+) (%\w+)\s*$')
    if not dd or dd.group(1) != dd.group(2):
        raise Fail('%s: the distance is not a self-dot' % name)
    pv = _m(D, dd.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$')
    if not pv:
        raise Fail('%s: the distance vector is not a v3 construct' % name)
    pc = list(pv.groups())
    for c in pc:
        if not _m(D, c, r'OpFSub %float (%\w+) (%\w+)\s*$'):
            raise Fail('%s: %s is not P - C' % (name, c))
    # ---- the variance
    vs = _m(D, m1.group(1), r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$')
    if not vs or K.get(vs.group(2)) != f32(0.0):
        raise Fail('%s: the out-of-bounds guard is missing' % name)
    va = _m(D, vs.group(3), r'OpFAdd %float (%\w+) (%\w+)\s*$')
    if not va:
        raise Fail('%s: the variance is not dx2 + dy2' % name)
    taps, diffs = None, []
    for did in va.groups():
        dm = _m(D, did, r'OpDot %float (%\w+) (%\w+)\s*$')
        if not dm or dm.group(1) != dm.group(2):
            raise Fail('%s: %s is not a squared normal difference' % (name, did))
        cm = _m(D, dm.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$')
        if not cm:
            raise Fail('%s: %s is not a v3 difference' % (name, did))
        nb, n0 = [], []
        for x in cm.groups():
            sm = _m(D, x, r'OpFSub %float (%\w+) (%\w+)\s*$')
            if not sm:
                raise Fail('%s: %s is not a subtraction' % (name, x))
            nb.append(sm.group(1))
            n0.append(sm.group(2))
        diffs.append((nb, n0))
    c0 = walk_tap(name, D, gl, diffs[0][1])
    if diffs[0][1] != diffs[1][1]:
        raise Fail('%s: the two differences use different centre normals' % name)
    t1 = walk_tap(name, D, gl, diffs[0][0])
    t2 = walk_tap(name, D, gl, diffs[1][0])
    for t in (t1, t2):
        if t['img'] != c0['img'] or t['lod'] != c0['lod'] or \
           t['bias'] != c0['bias']:
            raise Fail('%s: a neighbour tap reads a different image/lod/bias'
                       % name)
    # the coordinates: centre (x, y), then (x+1, y) and (x, y+1) in some order
    def coord(t):
        cm = _m(D, t['coord'], r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$')
        if not cm:
            raise Fail('%s: tap coordinate is not a v2uint construct' % name)
        return cm.groups()

    cx, cy = coord(c0)

    def plus1(a, b):
        mm = _m(D, a, r'OpIAdd %uint ' + re.escape(b) + r' (%\w+)\s*$')
        return bool(mm and K.get(mm.group(1)) == np.uint32(1))

    got = {coord(t1), coord(t2)}
    if not any(x == cy and plus1(a, cx) for (a, x) in got):
        raise Fail('%s: no (x+1, y) neighbour tap' % name)
    if not any(a == cx and plus1(x, cy) for (a, x) in got):
        raise Fail('%s: no (x, y+1) neighbour tap' % name)
    # the out-of-bounds guard must test the two NEIGHBOUR texels, all-zero
    oz = _m(D, vs.group(1), r'OpLogicalOr %bool (%\w+) (%\w+)\s*$')
    if not oz:
        raise Fail('%s: the guard is not an OpLogicalOr of two taps' % name)
    guarded = set()
    for z in oz.groups():
        a2 = _m(D, z, r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$')
        a1 = _m(D, a2.group(1), r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$') if a2 else None
        if not a1:
            raise Fail('%s: the guard is not a 3-way AND' % name)
        eqs = [a1.group(1), a1.group(2), a2.group(2)]
        comps = []
        for e in eqs:
            me = _m(D, e, r'OpFOrdEqual %bool (%\w+) (%\w+)\s*$')
            if not me or K.get(me.group(2)) != f32(0.0):
                raise Fail('%s: the guard is not a texel == 0 test' % name)
            comps.append(me.group(1))
        guarded.add(tuple(comps))
    if guarded != {tuple(t1['raw']), tuple(t2['raw'])}:
        raise Fail('%s: the guard does not test the two neighbour taps' % name)
    return dict(taps=[c0, t1, t2], pc=pc, bias=float(K[c0['bias']]))


# ------------------------------------------------------------------ module
def check_module(path, want, mode):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = defs_index(mod)
    K = consts(mod)
    gl = mod.glsl
    rep = dict(module=name, alphas=0, ggx_all=0, writes=0, worst=0.0,
               estimators=0)

    splices = {}
    for sel, (line, txt) in D.items():
        ms = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', txt)
        if not ms:
            continue
        gt, ap, alpha = ms.groups()
        msq = _m(D, ap, r'OpExtInst %float ' + re.escape(gl) + r' Sqrt (%\w+)\s*$')
        if not msq:
            continue
        madd = _m(D, msq.group(1), r'OpFAdd %float (%\w+) (%\w+)\s*$')
        if not madd:
            continue
        maa = _m(D, madd.group(1), r'OpFMul %float ' + re.escape(alpha) + r' '
                 + re.escape(alpha) + r'\s*$')
        if not maa:
            continue
        splices[sel] = dict(gate=gt, alpha=alpha, aa=madd.group(1),
                            sig=madd.group(2), line=line)

    paints = []
    for i, ln in enumerate(mod.lines):
        mw = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not mw:
            continue
        mt = _m(D, mw.group(3), r'OpCompositeConstruct %v4float (%\w+) (%\w+) '
                r'(%\w+) (%\w+)\s*$')
        if not mt:
            continue
        chans = mt.groups()[:3]
        sels = [_m(D, c, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$') for c in chans]
        if not all(sels):
            continue
        grey = {s.group(2) for s in sels}
        gates = {s.group(1) for s in sels}
        if len(grey) != 1 or len(gates) != 1:
            continue
        mg = _m(D, grey.pop(), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mg:
            continue
        inv = mg.group(2)
        if inv not in K or abs(float(K[inv])
                               - float(f32(1.0 / want['sigma2_max']))) > 1e-6:
            continue
        paints.append(dict(line=i, gate=gates.pop(), sig=mg.group(1)))

    if mode == 'none':
        if splices or paints:
            raise Fail('%s: %d alpha splices and %d sigma2 paints in a rung '
                       'that must carry none' % (name, len(splices), len(paints)))
        return rep
    if mode == 'feature' and paints:
        raise Fail('%s: the feature rung must not paint image writes' % name)
    if mode == 'vis' and splices:
        raise Fail('%s: the vis rung must not touch alpha' % name)
    if mode == 'feature' and not splices:
        return rep
    if mode == 'vis' and not paints:
        return rep

    # ---- provenance: the module's own metallic and position chain --------
    trips = find_f0_metal_triples(mod, D)
    metals = set()
    for t in trips:
        metals |= forward_closure(D, [t['metal']], zero_only=True)
    if not metals:
        raise Fail('%s: no F0 = lerp(0.04, albedo, metallic) triple' % name)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        raise Fail('%s: spliced but no position reconstruction' % name)
    if ctx['cbv_slot'] != (0, 12) or ctx['img_slot'] != (1, 0):
        raise Fail('%s: position chain reads the wrong slots %s %s'
                   % (name, ctx['cbv_slot'], ctx['img_slot']))

    def check_gate(gate, met_from_fetch):
        mg = _m(D, gate, r'OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$')
        if not mg:
            raise Fail('%s: gate %s is not OpFOrdGreaterThan' % (name, gate))
        met, mmin = mg.groups()
        if mmin not in K or float(K[mmin]) != float(f32(want['metal_min'])):
            raise Fail('%s: metal threshold is %s, want %g'
                       % (name, K.get(mmin), want['metal_min']))
        if met_from_fetch:
            me = _m(D, met, r'OpCompositeExtract %float (%\w+) (\d)\s*$')
            if not me or not D.get(me.group(1), (0, ''))[1].startswith(
                    'OpImageFetch %v4float'):
                raise Fail('%s: the vis gate is not a re-issued G-buffer read'
                           % name)
        elif met not in metals:
            raise Fail('%s: gate reads %s, not the module\'s own F0-lerp '
                       'metallic' % (name, met))
        return met

    todo = ([(s['sig'], s['gate'], False) for s in splices.values()] if mode == 'feature'
            else [(p['sig'], p['gate'], True) for p in paints])
    sigs = {}
    for sig, gate, from_fetch in todo:
        check_gate(gate, from_fetch)
        if sig not in sigs:
            sigs[sig] = walk_sigma2(name, D, K, gl, sig, want)
    rep['estimators'] = len(sigs)

    if mode == 'feature':
        # ---- COVERAGE: every splice IS a GGX D-term alpha ----------------
        ggx_all = find_ggx_d_alphas(mod, D)
        rep['ggx_all'] = len(ggx_all)
        extra = sorted(set(splices) - ggx_all)
        if extra:
            raise Fail('%s: %d alpha selects are not a GGX D term: %s'
                       % (name, len(extra), extra[:4]))
        rep['alphas'] = len(splices)
        # ---- THE REWRITE IS TOTAL ---------------------------------------
        for sel, s in splices.items():
            u = [l for l in uses_of(mod, s['alpha'])
                 if l not in (mod.find_def(s['aa'])[0], s['line'])]
            if u:
                raise Fail('%s: pre-splice alpha %s still used at lines %s'
                           % (name, s['alpha'], [x + 1 for x in u[:4]]))
    else:
        rep['writes'] = len(paints)

    # ---- CLOSED FORM ------------------------------------------------------
    rng = np.random.default_rng(abs(hash(name)) & 0xffff)
    for sig, w in sigs.items():
        env_ids = [t['raw'] for t in w['taps']]
        for trial in range(12):
            if trial == 0:
                tex = [[0.5, 0.5, 1.0]] * 3            # flat wall
            elif trial == 1:
                tex = [[0.5, 0.5, 1.0], [0.0, 0.0, 0.0], [0.5, 0.5, 1.0]]
            elif trial == 2:
                tex = [[0.5, 0.5, 1.0], [0.5, 0.5, 1.0], [0.0, 0.0, 0.0]]
            else:
                tex = rng.uniform(0.0, 1.0, (3, 3)).tolist()
            pos = ([0.0, 0.0, 0.0] if trial == 3 else
                   rng.uniform(-60.0, 60.0, 3).tolist())
            env = {}
            for ti in range(3):
                for k in range(3):
                    env[env_ids[ti][k]] = f32(tex[ti][k])
            for k in range(3):
                env[w['pc'][k]] = f32(pos[k])
            got = float(evaluate(D, K, sig, env, {}))
            ref = float(sigma2_model(tex, pos, w['bias'], want))
            err = abs(got - ref) / max(1.0, abs(ref))
            rep['worst'] = max(rep['worst'], err)
            if err > TOL:
                raise Fail('%s: sigma2 closed form off by %.3g '
                           '(%.7g vs %.7g) at tex=%s pos=%s'
                           % (name, err, got, ref, tex, pos))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--mode', choices=('feature', 'vis', 'none'),
                    default='feature')
    ap.add_argument('--kappa', type=float, default=0.5)
    ap.add_argument('--sigma2-max', type=float, default=0.18)
    ap.add_argument('--metal-min', type=float, default=0.3)
    ap.add_argument('--pix-angle', type=float, default=0.001311)
    ap.add_argument('--foot0', type=float, default=0.010)
    ap.add_argument('--foot1', type=float, default=0.050)
    a = ap.parse_args()
    want = dict(kappa=a.kappa, sigma2_max=a.sigma2_max, metal_min=a.metal_min,
                pix_angle=a.pix_angle, foot0=a.foot0, foot1=a.foot1,
                inv_span=1.0 / (a.foot1 - a.foot0))

    comp = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    rgs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_*.spv')))
    if len(comp) != 77 or len(rgs) != 16:
        raise SystemExit('FAIL: %d compute + %d raygen, want 77 + 16'
                         % (len(comp), len(rgs)))
    hit, tot = [], dict(alphas=0, ggx_all=0, writes=0, estimators=0)
    worst = 0.0
    with tempfile.TemporaryDirectory() as td:
        for f in comp:
            n = os.path.basename(f)[:-9]
            asm = os.path.join(td, n + '.spvasm')
            subprocess.run(['spirv-dis', f, '-o', asm], check=True)
            try:
                rep = check_module(asm, want, a.mode)
            except Fail as e:
                raise SystemExit('FAIL: %s' % e)
            if rep['alphas'] or rep['writes']:
                hit.append(n)
                for k in tot:
                    tot[k] += rep[k]
                worst = max(worst, rep['worst'])
    if a.mode == 'none':
        if hit:
            raise SystemExit('FAIL: %d modules carry a splice with --mode none'
                             % len(hit))
        print('verify_specaa OK (--mode none): 77 compute + 16 raygen, '
              '0 spliced')
        return
    declined = {os.path.basename(f)[:-9] for f in comp} - set(hit)
    if declined != set(KNOWN_DECLINE):
        raise SystemExit('FAIL: declines are %s, expected %s'
                         % (sorted(declined), sorted(KNOWN_DECLINE)))
    if len(hit) != CENSUS['modules']:
        raise SystemExit('FAIL: %d spliced modules, census says %d'
                         % (len(hit), CENSUS['modules']))
    if a.mode == 'feature':
        if tot['alphas'] != CENSUS['alphas'] or \
           tot['ggx_all'] != CENSUS['ggx_d_alphas']:
            raise SystemExit('FAIL: %d widened of %d GGX D-term alphas, '
                             'census says %d of %d'
                             % (tot['alphas'], tot['ggx_all'],
                                CENSUS['alphas'], CENSUS['ggx_d_alphas']))
        print('verify_specaa OK: %d modules, %d widened of %d GGX D-term '
              'alphas (%d KNOWN gap, sec 9), %d estimators, kappa=%g s2max=%g '
              'metal_min=%g ramp=%g..%g m; worst closed-form rel err %.3g '
              '(tol %g)'
              % (len(hit), tot['alphas'], tot['ggx_all'],
                 tot['ggx_all'] - tot['alphas'], tot['estimators'],
                 want['kappa'], want['sigma2_max'], want['metal_min'],
                 want['foot0'], want['foot1'], worst, TOL))
    else:
        if tot['writes'] != CENSUS['writes']:
            raise SystemExit('FAIL: %d painted writes, census says %d'
                             % (tot['writes'], CENSUS['writes']))
        print('verify_specaa OK (vis): %d modules, %d painted writes, '
              '%d estimators; worst closed-form rel err %.3g (tol %g)'
              % (len(hit), tot['writes'], tot['estimators'], worst, TOL))


if __name__ == '__main__':
    main()
