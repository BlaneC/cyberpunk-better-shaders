#!/usr/bin/env python3
"""verify_whash -- re-derive 107's claims from the SHIPPED .spv bytes.

    python3 dev/verify_whash.py <rung-dir> --rung micro|micro-hi|micro-cell|
                                                 micro-ctl|porous|porous-ctl|
                                                 micro-porous
                                [--base <dir>] [--json]

NEW FILE.  Nothing here reads a patch report, and nothing here imports
`patch_whash`'s emitters.  Every number below is recovered by disassembling
the rung's own files and walking them.  The two things that ARE imported from
the patcher are its declared census and its declared knobs -- i.e. the claims
under test, not the machinery that produced them.

What is proved, in order (handoff/107 sec 6):

 1  SELECTION.  77 compute + 16 raygen, and the 16 raygens plus the two
    declined compute modules are byte-identical to the base.
 2  REACH.  Exactly 75 modules carry the feature; the two that do not are
    KNOWN_DECLINE by name.
 3  COUNTS.  The splice census recovered from the bytes equals CENSUS.
 4  THE SEED IS THE WORLD.  For every module, the backward cone of the noise
    field contains exactly three non-constant leaves and they are the three
    OpFDivs of a `99` position reconstruction: four-term Fma chain over four
    CONSECUTIVE members of one bindless CBV with the z operand taken from an
    OpImageFetch.  Nothing else -- no pixel coordinate, no camera position, no
    frame index -- reaches the field.  THIS is the "will not boil" claim, and
    it is the one a screenshot cannot check.
 5  THE GATE.  Each splice's OpSelect condition decomposes into exactly the
    documented leaf predicates: class != 1, != 4, != 8 on a real `word >> 5`
    read, metallic < 0.10, and the site's own alpha > the rung's threshold
    (plus, for C, max3(albedo) - min3(albedo) < 0.08).
 6  CLOSED FORM.  The straight-line chain from the three position ids to the
    field is interpreted in float32/uint32 straight out of the disassembly and
    compared BIT-EXACTLY against dev/whash_model.py, which is written from the
    algorithm and shares no code with the emitter.  Then the derived terms
    (fade, dr, da, amp), the perturbed alpha and the porous lobe are compared
    against the same model within TOL.
 7  ENERGY.  The added lobe is bounded by cap x amp_max x 1 and the base
    specular is multiplied by nothing -- the 94 sec 4.3 argument, checked on
    the bytes rather than asserted in prose.
 8  NON-VACUITY.  A control has zero splices; a feature rung's field actually
    VARIES over the grid (a constant-folded field would pass a bit-exact
    comparison and mean nothing); and a deliberately corrupted model is
    REJECTED, which is what makes check 6 a gate.
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient
import wpos_core as W
import whash_model as M
from patch_whash import KNOWN_DECLINE, CENSUS, DEFAULTS

TOL = 2e-5


class Fail(Exception):
    pass


def _same(got, want):
    """A shipped OpConstant is the float32 ROUNDING of the declared knob, so
    every comparison against a knob goes through float32 first -- otherwise
    `0.1` is 1.5e-9 away from itself and the gate check fails on nothing."""
    return abs(float(got) - float(np.float32(want))) <= 1e-9 + 1e-6 * abs(float(want))


def f32(x):
    return np.float32(x)


# --------------------------------------------------------------- evaluator
def consts(mod):
    out = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)\s*$', ln)
        if m:
            try:
                out[m.group(1)] = np.float32(float(m.group(2)))
            except ValueError:
                pass
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %(uint|int) (-?\d+)\s*$', ln)
        if m:
            out[m.group(1)] = np.uint32(int(m.group(3)) & 0xFFFFFFFF)
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant(True|False)\s*$', ln)
        if m:
            out[m.group(1)] = np.bool_(m.group(2) == 'True')
    return out


_U = lambda x: np.asarray(x, dtype=np.uint32)


def evaluate(D, K, target, env, memo):
    """Interpret the pure SSA chain reaching `target` over numpy arrays."""
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
    a = re.findall(r'%\w+', txt)[1:]          # drop the result type
    E = lambda i: evaluate(D, K, i, env, memo)
    if op == 'OpFMul':
        v = f32(E(a[0]) * E(a[1]))
    elif op == 'OpFAdd':
        v = f32(E(a[0]) + E(a[1]))
    elif op == 'OpFSub':
        v = f32(E(a[0]) - E(a[1]))
    elif op == 'OpFDiv':
        v = f32(E(a[0]) / E(a[1]))
    elif op == 'OpFNegate':
        v = f32(-E(a[0]))
    elif op == 'OpConvertFToU':
        # SPIR-V ConvertFToU truncates toward zero and is UNDEFINED for a
        # negative operand -- `whash_core` is why the +BIAS exists, and the
        # model reproduces the truncation, not a round.
        v = np.asarray(E(a[0])).astype(np.int64).astype(np.uint32)
    elif op == 'OpConvertUToF':
        v = _U(E(a[0])).astype(np.float32)
    elif op == 'OpIMul':
        v = _U((_U(E(a[0])).astype(np.uint64)
                * _U(E(a[1])).astype(np.uint64)) & np.uint64(0xFFFFFFFF))
    elif op == 'OpIAdd':
        v = _U((_U(E(a[0])).astype(np.uint64)
                + _U(E(a[1])).astype(np.uint64)) & np.uint64(0xFFFFFFFF))
    elif op == 'OpBitwiseXor':
        v = _U(np.bitwise_xor(_U(E(a[0])), _U(E(a[1]))))
    elif op == 'OpBitwiseAnd':
        v = _U(np.bitwise_and(_U(E(a[0])), _U(E(a[1]))))
    elif op == 'OpBitwiseOr':
        v = _U(np.bitwise_or(_U(E(a[0])), _U(E(a[1]))))
    elif op == 'OpShiftRightLogical':
        v = _U(np.right_shift(_U(E(a[0])), _U(E(a[1]))))
    elif op == 'OpShiftLeftLogical':
        v = _U(np.left_shift(_U(E(a[0])), _U(E(a[1]))))
    elif op == 'OpIEqual':
        v = _U(E(a[0])) == _U(E(a[1]))
    elif op == 'OpINotEqual':
        v = _U(E(a[0])) != _U(E(a[1]))
    elif op == 'OpFOrdLessThan':
        v = E(a[0]) < E(a[1])
    elif op == 'OpFOrdGreaterThan':
        v = E(a[0]) > E(a[1])
    elif op == 'OpFOrdLessThanEqual':
        v = E(a[0]) <= E(a[1])
    elif op == 'OpFOrdGreaterThanEqual':
        v = E(a[0]) >= E(a[1])
    elif op == 'OpLogicalAnd':
        v = np.logical_and(E(a[0]), E(a[1]))
    elif op == 'OpLogicalOr':
        v = np.logical_or(E(a[0]), E(a[1]))
    elif op == 'OpLogicalNot':
        v = np.logical_not(E(a[0]))
    elif op == 'OpSelect':
        t, fv = E(a[1]), E(a[2])
        v = np.where(E(a[0]), t, fv)
        v = v.astype(np.float32) if np.asarray(t).dtype.kind == 'f' else _U(v)
    elif op == 'OpCompositeExtract':
        raise Fail('composite extract %s is a leaf, bind it' % target)
    elif op == 'OpExtInst':
        name = txt.split()[3]
        if name == 'Floor':
            v = f32(np.floor(E(a[1])))
        elif name == 'Fract':
            x = E(a[1])
            v = f32(x - np.floor(x))
        elif name == 'Sqrt':
            v = f32(np.sqrt(E(a[1])))
        elif name == 'InverseSqrt':
            v = f32(1.0 / np.sqrt(E(a[1])))
        elif name == 'FAbs':
            v = f32(np.abs(E(a[1])))
        elif name == 'Log2':
            v = f32(np.log2(E(a[1])))
        elif name == 'Exp2':
            v = f32(np.exp2(E(a[1])))
        elif name == 'Pow':
            v = f32(np.power(E(a[1]), E(a[2])))
        elif name == 'Fma':
            v = f32(f32(E(a[1]) * E(a[2])) + E(a[3]))
        elif name == 'NMin':
            v = f32(np.minimum(E(a[1]), E(a[2])))
        elif name == 'NMax':
            v = f32(np.maximum(E(a[1]), E(a[2])))
        elif name == 'NClamp':
            v = f32(np.minimum(np.maximum(E(a[1]), E(a[2])), E(a[3])))
        else:
            raise Fail('unmodelled GLSL op %s' % name)
    else:
        raise Fail('unmodelled op %s' % op)
    memo[target] = v
    return v


MODELLED_OPS = {
    'OpFMul', 'OpFAdd', 'OpFSub', 'OpFDiv', 'OpFNegate', 'OpSelect',
    'OpFOrdLessThan', 'OpFOrdGreaterThan', 'OpFOrdLessThanEqual',
    'OpFOrdGreaterThanEqual', 'OpLogicalAnd', 'OpLogicalOr', 'OpLogicalNot',
}
MODELLED_EXT = {'Floor', 'Fract', 'Sqrt', 'InverseSqrt', 'FAbs', 'Log2',
                'Exp2', 'Pow', 'Fma', 'NMin', 'NMax', 'NClamp'}


def free_inputs(D, K, root, stop=()):
    """The float inputs an emitted arithmetic chain bottoms out on.

    The walk descends only through the ops 107 itself emits; anything else --
    a dot product, a load, a phi -- is where the module's own shading ends and
    this splice begins, and is returned as a free input to be bound.  For the
    porous lobe those inputs are exactly N.H, N.L and N.V, which
    `_saturate_cosines` has already put in [0, 1]; that is what makes the
    energy bound below a bound and not a sample.
    """
    out, seen, stack = set(), set(), [root]
    while stack:
        i = stack.pop()
        if i in seen or i in stop or i in K:
            continue
        seen.add(i)
        if i not in D:
            out.add(i)
            continue
        txt = D[i][1]
        op = txt.split()[0]
        ok = op in MODELLED_OPS or (op == 'OpExtInst'
                                    and txt.split()[3] in MODELLED_EXT)
        if not ok:
            out.add(i)
            continue
        for j in re.findall(r'%\w+', txt)[1:]:
            stack.append(j)
    return out


def leaves(D, K, root, stop=()):
    """Non-constant leaves of the backward cone, stopping at `stop`."""
    out, seen, stack = set(), set(), [root]
    while stack:
        i = stack.pop()
        if i in seen or i in stop:
            continue
        seen.add(i)
        if i in K:
            continue
        if i not in D:
            out.add(i)
            continue
        for j in re.findall(r'%\w+', D[i][1])[1:]:
            stack.append(j)
    return out


# ------------------------------------------------------- structure finders
def find_pos_triples(mod, D):
    """Every `99` position reconstruction present in the bytes.

    Re-derived here rather than taken from `wpos_core.find_pos_chain`, which
    returns only the module's OWN chain: a feature rung also carries the
    hoist's refetch, and the point of this check is that the field is seeded
    on ONE of these and on nothing else.
    """
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpFDiv %float (%\d+) (%\d+)\s*$', ln)
        if not m:
            continue
        num, den = m.group(2), m.group(3)
        rows = _fma_chain(D, num)
        if rows is None:
            continue
        out.append(dict(line=i, id=m.group(1), num=num, den=den, rows=rows))
    # group by shared denominator: x, y, z of one reconstruction
    by = {}
    for o in out:
        by.setdefault(o['den'], []).append(o)
    tri = []
    for den, g in by.items():
        if len(g) != 3:
            continue
        drows = _fma_chain(D, den)
        if drows is None:
            continue
        mem = [r[0] for r in g[0]['rows']]
        if len(mem) != 4 or any(mem[k] + 1 != mem[k + 1] for k in range(3)):
            continue
        if not any(_is_fetch(D, r[1]) for r in g[0]['rows']):
            continue
        tri.append(dict(ids=tuple(o['id'] for o in sorted(g, key=lambda x: x['line'])),
                        members=mem, den=den))
    return tri


def _fma_chain(D, top):
    """`row3 + Fma(row2, z, Fma(row1, fy, row0*fx))` -> [(member, operand)...]"""
    t = D.get(top, (0, ''))[1]
    m = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', t)
    if not m:
        return None
    rows, cur, ops = [], m.group(1), []
    r3 = _member_of(D, m.group(2))
    for _ in range(2):
        t = D.get(cur, (0, ''))[1]
        mm = re.match(r'OpExtInst %float %\w+ Fma (%\w+) (%\w+) (%\w+)\s*$', t)
        if not mm:
            return None
        ops.append((mm.group(1), mm.group(2)))
        cur = mm.group(3)
    t = D.get(cur, (0, ''))[1]
    mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', t)
    if not mm:
        return None
    ops.append((mm.group(1), mm.group(2)))
    ops.reverse()                                    # row0, row1, row2
    for a, b in ops:
        k = _member_of(D, a)
        if k is None:
            return None
        rows.append((k, b))
    if r3 is None:
        return None
    rows.append((r3, None))
    return rows


def _member_of(D, i):
    """`OpCompositeExtract(OpLoad(OpAccessChain cbv 0 %uint_N))` -> N."""
    t = D.get(i, (0, ''))[1]
    m = re.match(r'OpCompositeExtract %float (%\w+) \d+\s*$', t)
    if not m:
        return None
    t = D.get(m.group(1), (0, ''))[1]
    m = re.match(r'OpLoad %v4float (%\w+)\s*$', t)
    if not m:
        return None
    t = D.get(m.group(1), (0, ''))[1]
    m = re.match(r'OpAccessChain %\w+ %\w+ %uint_0 %uint_(\d+)\s*$', t)
    return int(m.group(1)) if m else None


def _is_fetch(D, i):
    if i is None:
        return False
    t = D.get(i, (0, ''))[1]
    m = re.match(r'OpCompositeExtract %float (%\w+) \d+\s*$', t)
    if not m:
        return False
    return D.get(m.group(1), (0, ''))[1].startswith('OpImageFetch')


def _fmul_pair(D, i):
    m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D.get(i, (0, ''))[1])
    return m.groups() if m else None


def _fadd_pair(D, i):
    m = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', D.get(i, (0, ''))[1])
    return m.groups() if m else None


def find_hoist_terms(mod, D, K):
    """Recover `fade`, `dr`, `da`, `amp` and the noise roots from the bytes.

    `dr  = ((f0*2 + -1) * k_rough) * fade`
    `da  = 1 + ((f1*2 + -1) * k_alb) * fade`
    `amp = (1 + (f2 - 0.5)*fade) * k_porous`

    Each is anchored on the `2f - 1` / `f - 0.5` shape, so the noise root
    `f` falls out of the match and is never taken on trust.
    """
    out = {}
    for i, ln in enumerate(mod.lines):
        mid = re.match(r'\s*(%\d+) = ', ln)
        if not mid:
            continue
        me = mid.group(1)
        # dr: FMul(FMul(FAdd(FMul(f,2), -1), k), fade)
        p = _fmul_pair(D, me)
        if p:
            q = _fmul_pair(D, p[0])
            if q and K.get(q[1]) is not None:
                r = _fadd_pair(D, q[0])
                if r and K.get(r[1]) == np.float32(-1.0):
                    s = _fmul_pair(D, r[0])
                    if s and K.get(s[1]) == np.float32(2.0):
                        out.setdefault('dr', []).append(
                            dict(id=me, f=s[0], k=float(K[q[1]]), fade=p[1]))
        # da: FAdd(1, FMul(FMul(FAdd(FMul(f,2),-1), k), fade))
        p = _fadd_pair(D, me)
        if p and K.get(p[0]) == np.float32(1.0):
            q = _fmul_pair(D, p[1])
            if q:
                r = _fmul_pair(D, q[0])
                if r and K.get(r[1]) is not None:
                    s = _fadd_pair(D, r[0])
                    if s and K.get(s[1]) == np.float32(-1.0):
                        t = _fmul_pair(D, s[0])
                        if t and K.get(t[1]) == np.float32(2.0):
                            out.setdefault('da', []).append(
                                dict(id=me, f=t[0], k=float(K[r[1]]),
                                     fade=q[1], inner=p[1]))
        # amp: FMul(FAdd(1, FMul(FSub(f, 0.5), fade)), k)
        p = _fmul_pair(D, me)
        if p and K.get(p[1]) is not None:
            q = _fadd_pair(D, p[0])
            if q and K.get(q[0]) == np.float32(1.0):
                r = _fmul_pair(D, q[1])
                if r:
                    s = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$',
                                 D.get(r[0], (0, ''))[1])
                    if s and K.get(s.group(2)) == np.float32(0.5):
                        out.setdefault('amp', []).append(
                            dict(id=me, f=s.group(1), k=float(K[p[1]]),
                                 fade=r[1]))
    # `da`'s inner product IS a `dr`-shaped expression -- the two differ only
    # by the `1 +` sitting on top of it.  Drop the shadow, so the "exactly one
    # hoisted term" check below is testing what it says it is.
    inner = {d['inner'] for d in out.get('da', [])}
    if 'dr' in out:
        out['dr'] = [d for d in out['dr'] if d['id'] not in inner]
        if not out['dr']:
            out.pop('dr')
    return out


def find_rough_splices(mod, D, K):
    """`OpSelect(gate, FMul(rc, rc), alpha)` with `rc = NClamp(Sqrt(alpha)+dr)`."""
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        sel, gate, tv, alpha = m.groups()
        p = _fmul_pair(D, tv)
        if not p or p[0] != p[1]:
            continue
        c = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$',
                     D.get(p[0], (0, ''))[1])
        if not c:
            continue
        s = _fadd_pair(D, c.group(1))
        if not s:
            continue
        r = re.match(r'OpExtInst %float %\w+ Sqrt (%\w+)\s*$',
                     D.get(s[0], (0, ''))[1])
        if not r or r.group(1) != alpha:
            continue
        out.append(dict(line=i, id=sel, gate=gate, alpha=alpha, dr=s[1],
                        lo=float(K.get(c.group(2), np.float32(np.nan))),
                        hi=float(K.get(c.group(3), np.float32(np.nan)))))
    return out


def find_alb_splices(mod, D, K, da_ids):
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', ln)
        if m and m.group(3) in da_ids and K.get(m.group(4)) == np.float32(1.0):
            out.append(dict(line=i, id=m.group(1), gate=m.group(2),
                            da=m.group(3)))
    return out


def find_porous_splices(mod, D, K, amp_ids):
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m or K.get(m.group(4)) != np.float32(0.0):
            continue
        if not (leaves(D, K, m.group(3), stop=()) or True):
            continue
        cone = _cone(D, m.group(3), K)
        hit = amp_ids & cone
        if not hit:
            continue
        # the FAdd that puts it back on the base specular
        add = None
        for j, l2 in enumerate(mod.lines):
            mm = re.match(r'\s*(%\d+) = OpFAdd %float (%\w+) '
                          + re.escape(m.group(1)) + r'\s*$', l2)
            if mm:
                add = dict(id=mm.group(1), spec=mm.group(2), line=j)
                break
        out.append(dict(line=i, id=m.group(1), gate=m.group(2), cur=m.group(3),
                        amp=sorted(hit)[0], add=add))
    return out


def _cone(D, root, K, limit=200000):
    seen, stack = set(), [root]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        if i in K or i not in D:
            continue
        for j in re.findall(r'%\w+', D[i][1])[1:]:
            stack.append(j)
    return seen


def gate_leaves(D, gate):
    """Flatten a LogicalAnd tree into its leaf predicate instructions."""
    out, stack = [], [gate]
    while stack:
        i = stack.pop()
        t = D.get(i, (0, ''))[1]
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)\s*$', t)
        if m:
            stack += [m.group(1), m.group(2)]
        else:
            out.append((i, t))
    return out


def check_gate(D, K, gate, alpha, want_rough, want_sat, name, line):
    ls = gate_leaves(D, gate)
    cls_ne, met, rough, sat = set(), [], [], []
    for i, t in ls:
        m = re.match(r'OpINotEqual %bool (%\w+) (%\w+)\s*$', t)
        if m:
            v = K.get(m.group(2))
            if v is None:
                raise Fail('%s@%d: class clause compares against a non-constant' % (name, line))
            cls_ne.add(int(v))
            _assert_class_read(D, m.group(1), name, line)
            continue
        m = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)\s*$', t)
        if m:
            v = K.get(m.group(2))
            if v is not None and _same(v, DEFAULTS['gate_metal']):
                met.append(m.group(1))
            elif v is not None and _same(v, DEFAULTS['gate_sat']):
                sat.append(m.group(1))
            else:
                raise Fail('%s@%d: unrecognised FOrdLessThan clause vs %s'
                           % (name, line, v))
            continue
        m = re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$', t)
        if m:
            v = K.get(m.group(2))
            if v is None or not _same(v, want_rough ** 2):
                raise Fail('%s@%d: roughness clause is alpha > %s, want %s'
                           % (name, line, v, want_rough ** 2))
            rough.append(m.group(1))
            continue
        raise Fail('%s@%d: unrecognised gate clause %s' % (name, line, t[:70]))
    if cls_ne != set((1, 4, 8)):
        raise Fail('%s@%d: class clauses %s, want {1, 4, 8}' % (name, line, sorted(cls_ne)))
    if len(met) != 1:
        raise Fail('%s@%d: %d metallic clauses, want 1' % (name, line, len(met)))
    if len(rough) != 1:
        raise Fail('%s@%d: %d roughness clauses, want 1' % (name, line, len(rough)))
    if alpha is not None and rough[0] != alpha:
        # the f_d splice tests roughness^2 recomputed at the site
        p = _fmul_pair(D, rough[0])
        if not (p and p[0] == p[1]):
            raise Fail("%s@%d: the roughness clause is not the site's own alpha"
                       % (name, line))
    if want_sat and len(sat) != 1:
        raise Fail('%s@%d: %d saturation clauses, want 1' % (name, line, len(sat)))
    if not want_sat and sat:
        raise Fail('%s@%d: an unexpected saturation clause' % (name, line))
    if want_sat:
        _assert_saturation(D, sat[0], name, line)
    return met[0]


def _assert_class_read(D, cls, name, line):
    t = D.get(cls, (0, ''))[1]
    if t.startswith('OpPhi'):
        return
    m = re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', t)
    if not m:
        raise Fail('%s@%d: the class value is not `word >> 5` (%s)'
                   % (name, line, t[:60]))
    t = D.get(m.group(1), (0, ''))[1]
    if not re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', t):
        raise Fail('%s@%d: `>> 5` does not read component 1 of the material fetch'
                   % (name, line))


def _assert_saturation(D, sat, name, line):
    m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', D.get(sat, (0, ''))[1])
    if not m:
        raise Fail('%s@%d: the saturation value is not a subtraction' % (name, line))
    def chan(i, kind):
        t = D.get(i, (0, ''))[1]
        mm = re.match(r'OpExtInst %float %\w+ ' + kind + r' (%\w+) (%\w+)\s*$', t)
        if not mm:
            raise Fail('%s@%d: saturation %s is not an %s tree' % (name, line, i, kind))
        a, b = mm.groups()
        ta = D.get(a, (0, ''))[1]
        inner = re.match(r'OpExtInst %float %\w+ ' + kind + r' (%\w+) (%\w+)\s*$', ta)
        if not inner:
            raise Fail('%s@%d: saturation %s tree is not 3-wide' % (name, line, i))
        return {inner.group(1), inner.group(2), b}
    hi, lo = chan(m.group(1), 'NMax'), chan(m.group(2), 'NMin')
    if hi != lo:
        raise Fail('%s@%d: max3 and min3 read different channels' % (name, line))
    if len(hi) != 3:
        raise Fail('%s@%d: saturation reads %d channels, want 3' % (name, line, len(hi)))


# ------------------------------------------------------------------ checks
GRID_N = 240


def _grid(seed=20260903):
    rng = np.random.default_rng(seed)
    return np.concatenate([
        rng.uniform(-300.0, 300.0, size=(3, GRID_N - 40)),
        rng.uniform(-2.0, 2.0, size=(3, 35)),
        np.array([[0.0, 1.0, -1.0, 0.006, 123.75],
                  [0.0, 2.0, -2.5, -0.006, -60.5],
                  [0.0, 0.25, 3.5, 0.0, 41.0]]),
    ], axis=1).astype(np.float32)


def ref_grid(G, R, seed):
    """`whash_model.ref_fbm` over the whole grid.

    The model is written point-at-a-time in Python floats on purpose -- it is
    the INDEPENDENT reference, and vectorising it would mean sharing numpy
    broadcasting semantics with the thing it is checking.  So it is evaluated
    once here and reused for all 75 modules, which emit the same field.
    """
    out = np.empty((3, G.shape[1]), np.float32)
    for i in range(G.shape[1]):
        v = M.ref_fbm(tuple(G[:, i]), R['cell'], seed, octaves=R['octaves'],
                      lacunarity=R['lacunarity'], gain=R['gain'])
        out[:, i] = v
    return out


def fade_grid(G, R):
    d = np.sqrt(np.sum((G - np.array(R['cam'], np.float32)[:, None]) ** 2,
                       axis=0)).astype(np.float32)
    f = np.array([M.ref_fade(float(x), R['fade_near'], R['fade_far'])
                  for x in d], np.float32)
    return d, f


def check_module(path, R, G, REF, FREF, corrupt=False, REF_BAD=None):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = W.defs_index(mod)
    K = consts(mod)
    rep = dict(module=name, rough=0, alb=0, porous=0, paint=0)

    H = find_hoist_terms(mod, D, K)
    dr = H.get('dr', [])
    da = H.get('da', [])
    amp = H.get('amp', [])
    rough = find_rough_splices(mod, D, K) if R['k_rough'] else []
    alb = find_alb_splices(mod, D, K, {d['id'] for d in da}) if R['k_alb'] else []
    por = (find_porous_splices(mod, D, K, {a['id'] for a in amp})
           if R['k_porous'] else [])
    rep.update(rough=len(rough), alb=len(alb), porous=len(por))

    if R['paint']:
        rep['paint'] = _check_paint(mod, D, K, R, G, name)
        return rep

    if not (rough or alb or por):
        raise Fail('%s: no splice found in a feature rung' % name)
    for kind, got, want in (('dr', dr, bool(R['k_rough'])),
                            ('da', da, bool(R['k_alb'])),
                            ('amp', amp, bool(R['k_porous']))):
        if want and len(got) != 1:
            raise Fail('%s: %d hoisted `%s` terms, want exactly 1 (the whole '
                       'point of the hoist is that the field is evaluated '
                       'ONCE per invocation)' % (name, len(got), kind))
        if not want and got:
            raise Fail('%s: a `%s` term in a rung that does not use it' % (name, kind))

    # --- 4  the seed is the world
    tris = find_pos_triples(mod, D)
    if not tris:
        raise Fail('%s: no `99` position reconstruction in the bytes' % name)
    term = (dr or da or amp)[0]
    fs = sorted({t['f'] for t in (dr + da + amp)})
    if len(fs) != len({'dr': 1}) * len(fs):
        pass
    pos = None
    for t in tris:
        if set(t['ids']) <= _cone(D, term['f'], K):
            pos = t
            break
    if pos is None:
        raise Fail('%s: the noise field is not seeded on a position '
                   'reconstruction' % name)
    lv = leaves(D, K, term['f'], stop=set(pos['ids']))
    if lv - set(pos['ids']):
        raise Fail('%s: the noise field also depends on %s -- it is NOT world-'
                   'stable and it WILL boil under the denoiser'
                   % (name, sorted(lv - set(pos['ids']))))
    rep['pos'] = list(pos['ids'])
    rep['pos_members'] = pos['members']

    # --- 6  closed form: the field itself, bit-exact
    env = {pos['ids'][k]: G[k] for k in range(3)}
    memo = {}
    ref = REF_BAD if corrupt else REF
    idx = {'dr': 0, 'da': 1, 'amp': 2}
    for n, t in enumerate(dr + da + amp):
        which = idx[('dr' if t in dr else 'da' if t in da else 'amp')]
        r = ref[which]
        g = evaluate(D, K, t['f'], env, memo)
        if not np.array_equal(g, r):
            bad = int(np.argmax(np.abs(g - r)))
            raise Fail('%s: noise channel %d differs from whash_model at '
                       'P=%s: %.9g vs %.9g' % (name, which,
                                               tuple(float(x) for x in G[:, bad]),
                                               float(g[bad]), float(r[bad])))
    # non-vacuity: a constant field would have passed the line above
    if float(np.std(ref[0])) < 0.05:
        raise Fail('%s: the noise field is nearly constant over the grid' % name)
    rep['field_std'] = [round(float(np.std(ref[k])), 4) for k in range(3)]

    # --- 6b  the fade, and the derived terms
    camc = _campos_of(D, term['fade'])
    fref = FREF
    fenv = dict(env)
    for k in range(3):
        fenv[camc[k]] = np.float32(R['cam'][k])
    fgot = evaluate(D, K, term['fade'], fenv, {})
    _close(name, 'fade', fgot, fref)
    for t, kind in ([(dr[0], 'dr')] if dr else []) + \
                   ([(da[0], 'da')] if da else []) + \
                   ([(amp[0], 'amp')] if amp else []):
        g = evaluate(D, K, t['id'], fenv, {})
        f = ref[idx[kind]]
        if kind == 'dr':
            r = ((f * np.float32(2) - np.float32(1)) * np.float32(t['k'])) * fref
        elif kind == 'da':
            r = np.float32(1) + ((f * np.float32(2) - np.float32(1))
                                 * np.float32(t['k'])) * fref
        else:
            r = (np.float32(1) + (f - np.float32(0.5)) * fref) * np.float32(t['k'])
        _close(name, kind, g, r.astype(np.float32))
        want_k = R['k_' + {'dr': 'rough', 'da': 'alb', 'amp': 'porous'}[kind]]
        if not _same(t['k'], want_k):
            raise Fail('%s: %s amplitude is %.9g, the rung declares %.9g'
                       % (name, kind, t['k'], want_k))

    # --- 5  the gates, every splice
    for s in rough:
        check_gate(D, K, s['gate'], s['alpha'], R['gate_rough'], False,
                   name, s['line'] + 1)
        if not _same(s['lo'], DEFAULTS['rough_floor']) or not _same(s['hi'], 1.0):
            raise Fail('%s@%d: roughness clamp [%g, %g], want [%g, 1]'
                       % (name, s['line'] + 1, s['lo'], s['hi'],
                          DEFAULTS['rough_floor']))
        if s['dr'] != dr[0]['id']:
            raise Fail('%s@%d: the splice does not consume the hoisted dr'
                       % (name, s['line'] + 1))
    for s in alb:
        check_gate(D, K, s['gate'], None, R['gate_rough'], False,
                   name, s['line'] + 1)
    for s in por:
        check_gate(D, K, s['gate'], None, R['gate_rough_c'], True,
                   name, s['line'] + 1)
        if s['add'] is None:
            raise Fail('%s@%d: the porous lobe is never added to a specular'
                       % (name, s['line'] + 1))

    # --- 6c  the perturbed alpha, and 7 the energy bound
    if rough:
        s = rough[0]
        aa = np.linspace(0.02, 1.0, GRID_N).astype(np.float32)
        e2 = dict(fenv)
        e2[s['alpha']] = aa
        g = evaluate(D, K, s['id'].replace(s['id'], _true_of(D, s['id'])), e2, {})
        r = np.minimum(np.maximum(np.sqrt(aa) + evaluate(D, K, s['dr'], fenv, {})[:GRID_N],
                                  np.float32(DEFAULTS['rough_floor'])),
                       np.float32(1.0)).astype(np.float32) ** 2
        _close(name, 'alpha-perturb', g, r.astype(np.float32), tol=1e-6)
    if por:
        s = por[0]
        rep['energy'] = _check_energy(D, K, s, R, fenv, name)
    return rep


def _true_of(D, sel):
    m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', D[sel][1])
    return m.group(2)


def _campos_of(D, fade):
    """`fade = 1 - NClamp((Sqrt(sum d^2) - near) * k)`; recover C."""
    m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', D.get(fade, (0, ''))[1])
    if not m:
        raise Fail('the fade is not `1 - u`')
    c = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) ', D.get(m.group(2), (0, ''))[1])
    u = _fmul_pair(D, c.group(1))
    d = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', D.get(u[0], (0, ''))[1])
    sq = re.match(r'OpExtInst %float %\w+ Sqrt (%\w+)\s*$', D.get(d.group(1), (0, ''))[1])
    if not sq:
        raise Fail('the distance is not a Sqrt')
    out, stack = [], [sq.group(1)]
    while stack:
        i = stack.pop()
        p = _fmul_pair(D, i)
        if p and p[0] == p[1]:
            s = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', D.get(p[0], (0, ''))[1])
            if s:
                out.append(s.group(2))
            continue
        a = _fadd_pair(D, i)
        if a:
            stack += list(a)
    if len(out) != 3:
        raise Fail('the distance is not over three (P - C) components (%d)' % len(out))
    return out[::-1]


def _check_energy(D, K, s, R, fenv, name):
    """94 sec 4.3 on the bytes: the added lobe is bounded and the base lobe is
    not inflated.

    The base specular reaches the write through `OpFAdd(spec, sel)` and
    through nothing else -- no multiply is placed on it -- so the only energy
    added is `sel`, and `sel` is bounded above by `cap x max(amp) x 1 x 1`
    because every factor after the capped Charlie term is a saturated cosine
    or a [0, 1] weight.
    """
    rng = np.random.default_rng(4242)
    n = 512
    e = dict(fenv)
    lv = sorted(free_inputs(D, K, s['cur'], stop={s['amp']}))
    if not lv:
        raise Fail('%s: the porous lobe has no free cosine inputs' % name)
    for i in lv:
        e[i] = rng.uniform(0.0, 1.0, size=n).astype(np.float32)
    e[s['amp']] = rng.uniform(0.5, 1.5, size=n).astype(np.float32) * np.float32(R['k_porous'])
    v = evaluate(D, K, s['cur'], e, {})
    hi = float(np.max(v))
    bound = DEFAULTS['porous_cap'] * 1.5 * R['k_porous']
    if hi > bound + 1e-6:
        raise Fail('%s: the porous lobe reaches %.4g, above the cap x amp_max '
                   'bound %.4g' % (name, hi, bound))
    if hi <= 0.0:
        raise Fail('%s: the porous lobe is identically zero' % name)
    if s['add'] is not None:
        spec = s['add']['spec']
        for ln in D.values():
            pass
    return dict(max=round(hi, 6), bound=round(bound, 6))


def _check_paint(mod, D, K, R, G, name):
    n = 0
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        t = D.get(m.group(3), (0, ''))[1]
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$', t)
        if not mc:
            continue
        chans = mc.groups()[:3]
        sels = []
        for c in chans:
            p = _fmul_pair(D, c)
            if not p:
                sels = None
                break
            ms = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                          D.get(p[1], (0, ''))[1])
            if not ms or K.get(ms.group(3)) != np.float32(1.0):
                sels = None
                break
            sels.append(ms.groups())
        if sels is None:
            continue
        gates = {s[0] for s in sels}
        if len(gates) != 1:
            raise Fail('%s@%d: the three channels disagree on the gate'
                       % (name, i + 1))
        ls = gate_leaves(D, list(gates)[0])
        cls = set()
        for gid, txt in ls:
            mm = re.match(r'OpINotEqual %bool (%\w+) (%\w+)\s*$', txt)
            if not mm:
                raise Fail('%s@%d: paint gate clause %s' % (name, i + 1, txt[:60]))
            cls.add(int(K[mm.group(2)]))
            _assert_class_read(D, mm.group(1), name, i + 1)
        if cls != set((1, 4, 8)):
            raise Fail('%s@%d: paint class clauses %s, want {1, 4, 8}'
                       % (name, i + 1, sorted(cls)))
        # the hue must be the world hash, not the fbm and not a constant
        tri = None
        cone = _cone(D, sels[0][1], K)
        for tt in find_pos_triples(mod, D):
            if set(tt['ids']) <= cone:
                tri = tt
                break
        if tri is None:
            raise Fail('%s@%d: the paint hue is not a function of a position '
                       'reconstruction' % (name, i + 1))
        n += 1
    return n


def _close(name, what, got, ref, tol=TOL):
    g, r = np.asarray(got, np.float64), np.asarray(ref, np.float64)
    err = np.max(np.abs(g - r) / np.maximum(np.abs(r), 1e-3))
    if err > tol:
        b = int(np.argmax(np.abs(g - r)))
        raise Fail('%s: %s differs from whash_model by %.3g (tol %g): '
                   '%.9g vs %.9g' % (name, what, err, tol, g[b], r[b]))


# -------------------------------------------------------------------- rungs
RUNGS = {
    'micro':       dict(k_rough=0.08, k_alb=0.06, k_porous=0.0, paint=False),
    'micro-hi':    dict(k_rough=0.16, k_alb=0.12, k_porous=0.0, paint=False),
    'micro-cell':  dict(k_rough=0.0, k_alb=0.0, k_porous=0.0, paint=True),
    'micro-ctl':   dict(k_rough=0.0, k_alb=0.0, k_porous=0.0, paint=False),
    'porous':      dict(k_rough=0.0, k_alb=0.0, k_porous=0.06, paint=False),
    'porous-ctl':  dict(k_rough=0.0, k_alb=0.0, k_porous=0.0, paint=False),
    'micro-porous': dict(k_rough=0.08, k_alb=0.06, k_porous=0.06, paint=False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rungdir')
    ap.add_argument('--rung', required=True, choices=sorted(RUNGS))
    ap.add_argument('--base', help='base rung dir, for the byte-identity checks')
    ap.add_argument('--cam', nargs=3, type=float, default=[12.0, -30.0, 1.7])
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    R = dict(DEFAULTS)
    R.update(RUNGS[a.rung])
    R['cam'] = a.cam
    ctl = a.rung.endswith('-ctl')

    spv = sorted(glob.glob(os.path.join(a.rungdir, '*.dxil.spv')))
    if not spv:
        raise SystemExit('verify_whash: no .spv in %s' % a.rungdir)
    out = dict(rung=a.rung, files=len(spv), modules=[], errors=[])

    # 1  selection + byte identity
    if a.base:
        same, diff = 0, []
        for p in spv:
            b = os.path.join(a.base, os.path.basename(p))
            if not os.path.exists(b):
                out['errors'].append('%s: not in the base' % os.path.basename(p))
                continue
            if open(p, 'rb').read() == open(b, 'rb').read():
                same += 1
            else:
                diff.append(os.path.basename(p).split('.')[0])
        out['identical_to_base'] = same
        out['changed'] = len(diff)
        if ctl and diff:
            out['errors'].append('a CONTROL changed %d modules: %s'
                                 % (len(diff), diff[:4]))
        if not ctl:
            for d in KNOWN_DECLINE:
                if any(x.startswith(d) for x in diff):
                    out['errors'].append('declined module %s was patched' % d)

    G = _grid()
    REF = None if (ctl or R['paint']) else ref_grid(G, R, R['seed'])
    REF_BAD = None if REF is None else ref_grid(G, R, R['seed'] + 1)
    _DIST, FREF = fade_grid(G, R)
    n_r = n_a = n_p = n_pt = 0
    tmp = tempfile.mkdtemp(prefix='verify_whash.')
    asm_of = {}
    for p in spv:
        nm = os.path.basename(p).split('.')[0]
        if nm in KNOWN_DECLINE:
            continue
        asm = os.path.join(tmp, nm + '.spvasm')
        subprocess.run(['spirv-dis', p, '-o', asm], check=True)
        asm_of[nm] = asm
        try:
            r = check_module(asm, R, G, REF, FREF)
        except Fail as e:
            if ctl:
                out['errors'].append(str(e))
                continue
            out['errors'].append(str(e))
            continue
        except Exception as e:
            out['errors'].append('%s: %s: %s' % (nm, type(e).__name__, e))
            continue
        if ctl and (r['rough'] or r['alb'] or r['porous'] or r['paint']):
            out['errors'].append('%s: a CONTROL carries splices' % nm)
        n_r += r['rough']; n_a += r['alb']; n_p += r['porous']; n_pt += r['paint']
        out['modules'].append(r)
    out['counts'] = dict(rough=n_r, alb=n_a, porous=n_p, paint=n_pt,
                         reached=len(out['modules']))

    # 3  the census
    if not ctl:
        want = {}
        if R['k_rough']:
            want['rough'] = CENSUS['alphas']
        if R['k_alb']:
            want['alb'] = CENSUS['fd']
        if R['k_porous']:
            want['porous'] = CENSUS['sheen']
        if R['paint']:
            want['paint'] = CENSUS['writes']
        for k, v in want.items():
            if out['counts'][k] != v:
                out['errors'].append('%s: %d splices recovered from the bytes, '
                                     'CENSUS says %d' % (k, out['counts'][k], v))
        if out['counts']['reached'] != CENSUS['reached']:
            out['errors'].append('%d modules reached, want %d'
                                 % (out['counts']['reached'], CENSUS['reached']))

    # 8  non-vacuity: the model must be REJECTABLE
    if not ctl and not R['paint'] and not out['errors']:
        good = sorted(asm_of.values())[0]
        try:
            check_module(good, R, G, REF, FREF, corrupt=True,
                         REF_BAD=REF_BAD)
        except Fail:
            out['rejection_test'] = 'a corrupted seed is REJECTED (good)'
        else:
            out['errors'].append('REJECTION TEST FAILED: the closed-form check '
                                 'passes with the wrong seed, so it proves '
                                 'nothing')

    shutil.rmtree(tmp, ignore_errors=True)
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        print('verify_whash %s: %d files, %d modules reached' %
              (a.rung, out['files'], out['counts']['reached']))
        print('  splices: rough %d  albedo %d  porous %d  paint %d'
              % (n_r, n_a, n_p, n_pt))
        if 'identical_to_base' in out:
            print('  vs base: %d identical, %d changed'
                  % (out['identical_to_base'], out['changed']))
        if out.get('rejection_test'):
            print('  ' + out['rejection_test'])
        fs = [m['field_std'] for m in out['modules'] if 'field_std' in m]
        if fs:
            print('  field std over the grid: %s (a constant field is a fail)' % fs[0])
        for e in out['errors'][:12]:
            print('  ERROR ' + e)
    return 1 if out['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
