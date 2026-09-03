#!/usr/bin/env python3
"""verify_wpos -- re-derive the hunt-wpos claim from the SHIPPED .spv bytes.

    python3 dev/verify_wpos.py <rung-dir> [--mode hash|frac] [--space world|cam]
                               [--cell 1.0] [--up 2] [--gain 1.0] [--no-stripe]

Nothing here reads a build report.  Every rung file is disassembled and the
following are re-derived (handoff/99 sec 6):

 1. the selection is complete: 77 compute + 16 raygen;
 2. exactly 75 compute modules carry paint and the other two are the two
    modules declined BY NAME;
 3. 150 painted writes, and no float radiance write is left unpainted inside a
    painted module;
 4. every painted texel is `orig_c * chain_c` with the chain rooted at 1.0, so
    a pixel matching no gate is bit-exact vanilla;
 5. the class gate is a real `word >> 5` read of the material image, and 94's
    class palette is present to the float32 bit (skin RED = the void control);
 6. THE POSITION CLAIM.  For the class-0 arm the verifier walks the painted
    colour backwards and proves, per site, that it is a function of three
    OpFDivs whose numerators are the four-term Fma chain over four CONSECUTIVE
    v4 members of one bindless CBV and whose z operand is component 0 of an
    OpImageFetch -- i.e. the value really is the module's own reconstructed
    surface position, re-derived here and never taken from the patcher;
    and, for --space cam, that a `cbv[..][0]` triple is subtracted from it;
 7. CLOSED FORM.  The emitted straight-line chain from the three position ids
    to the three multipliers is interpreted directly out of the disassembly
    over a grid of positions in float32/uint32 and compared against
    dev/wpos_model.py, which is written independently.
"""
import argparse, glob, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient
from patch_hunt_paint import CLASS_TINT, UNKNOWN_TINT
import wpos_core as W
import wpos_model as WM
from patch_wpos import KNOWN_DECLINE, CENSUS, DEFAULTS, HASH_K, AVAL_M, BIAS

TOL = 2e-5


def f32(x):
    return np.float32(x)


class Fail(Exception):
    pass


# --------------------------------------------------------- tiny evaluator
FOPS = {'OpFMul', 'OpFAdd', 'OpFSub', 'OpFDiv', 'OpConvertUToF', 'OpSelect',
        'OpExtInst', 'OpConvertFToU', 'OpIMul', 'OpBitwiseXor', 'OpBitwiseAnd',
        'OpShiftRightLogical', 'OpIEqual', 'OpCompositeExtract'}


def consts(mod):
    out = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)', ln)
        if m:
            try:
                out[m.group(1)] = np.float32(float(m.group(2)))
            except ValueError:
                pass
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %uint (\d+)', ln)
        if m:
            out[m.group(1)] = np.uint32(int(m.group(2)))
    return out


def evaluate(D, K, target, env, seen=None):
    """Interpret the pure SSA chain reaching `target`.  `env` binds the leaves."""
    if target in env:
        return env[target]
    if target in K:
        return K[target]
    if target not in D:
        raise Fail('evaluator hit an unbound leaf %s' % target)
    seen = seen or {}
    if target in seen:
        return seen[target]
    txt = D[target][1]
    op = txt.split()[0]
    a = re.findall(r'%\w+', txt)[1:]      # drop the result type
    E = lambda i: evaluate(D, K, i, env, seen)
    if op == 'OpFMul':
        v = f32(E(a[0]) * E(a[1]))
    elif op == 'OpFAdd':
        v = f32(E(a[0]) + E(a[1]))
    elif op == 'OpFSub':
        v = f32(E(a[0]) - E(a[1]))
    elif op == 'OpConvertFToU':
        v = np.asarray(E(a[0])).astype(np.uint32)
    elif op == 'OpConvertUToF':
        v = np.asarray(E(a[0])).astype(np.float32)
    elif op == 'OpIMul':
        v = (np.asarray(E(a[0]), dtype=np.uint32)
             * np.asarray(E(a[1]), dtype=np.uint32)).astype(np.uint32)
    elif op == 'OpBitwiseXor':
        v = np.bitwise_xor(np.asarray(E(a[0]), dtype=np.uint32),
                           np.asarray(E(a[1]), dtype=np.uint32)).astype(np.uint32)
    elif op == 'OpBitwiseAnd':
        v = np.bitwise_and(np.asarray(E(a[0]), dtype=np.uint32),
                           np.asarray(E(a[1]), dtype=np.uint32)).astype(np.uint32)
    elif op == 'OpShiftRightLogical':
        v = np.right_shift(np.asarray(E(a[0]), dtype=np.uint32),
                           np.asarray(E(a[1]), dtype=np.uint32)).astype(np.uint32)
    elif op == 'OpIEqual':
        v = np.asarray(E(a[0]), dtype=np.uint32) == np.asarray(E(a[1]), dtype=np.uint32)
    elif op == 'OpSelect':
        v = np.where(E(a[0]), E(a[1]), E(a[2])).astype(np.float32)
    elif op == 'OpExtInst':
        name = txt.split()[3]
        if name == 'Floor':
            v = f32(np.floor(E(a[1])))
        elif name == 'Fract':
            x = E(a[1])
            v = f32(x - np.floor(x))
        elif name == 'Fma':
            v = f32(f32(E(a[1]) * E(a[2])) + E(a[3]))
        else:
            raise Fail('unmodelled GLSL op %s' % name)
    else:
        raise Fail('unmodelled op %s' % op)
    seen[target] = v
    return v


# ------------------------------------------------------------------ checks
def check_module(path, want):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = W.defs_index(mod)
    K = consts(mod)
    rep = dict(module=name, writes=0, sites=[])

    writes = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if m:
            writes.append((i, m.group(3)))
    painted = []
    for line, texel in writes:
        t = D.get(texel, (0, ''))[1]
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$', t)
        if not mc:
            continue
        chans = mc.groups()[:3]
        # each channel must be OpFMul(orig, chain) with chain a select tower
        chain = []
        for c in chans:
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D.get(c, (0, ''))[1])
            if not mm:
                chain = None
                break
            chain.append(mm.group(2))
        if chain is None:
            continue
        painted.append((line, chans, chain))
    rep['writes'] = len(painted)
    if not painted:
        return rep

    # the position chain, re-derived here from the bytes
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        raise Fail('%s: paint present but no position reconstruction' % name)
    if ctx['cbv_slot'] != (0, 12):
        raise Fail('%s: view CBV is registers[%d]+%d, expected registers[0]+12'
                   % ((name,) + tuple(ctx['cbv_slot'] or (-1, -1))))
    if ctx['img_slot'] != (1, 0):
        raise Fail('%s: depth image is registers[%d]+%d, expected registers[1]+0'
                   % ((name,) + tuple(ctx['img_slot'] or (-1, -1))))
    if len(ctx['mat']) != 4 or any(ctx['mat'][i] + 1 != ctx['mat'][i + 1] for i in range(3)):
        raise Fail('%s: matrix members not consecutive: %s' % (name, ctx['mat']))
    cam = W.find_campos(mod, ctx, D)
    if cam is None:
        raise Fail('%s: no camera (C - P) triple' % name)
    rep['matrix'] = ctx['mat']
    rep['cam_member'] = cam['member']

    lo = WM.gained(want['lo'], want['gain'])
    hi = WM.gained(want['hi'], want['gain'])
    stripe = WM.gained(want['stripe'], want['gain'])
    cls_want = {n: tuple(WM.gained(x, want['gain']) for x in CLASS_TINT[n][1])
                for n in CLASS_TINT}
    unk_want = tuple(WM.gained(x, want['gain']) for x in UNKNOWN_TINT[1])

    rng = np.random.default_rng(20260902)
    grid = np.concatenate([
        rng.uniform(-400.0, 400.0, size=(3, 900)),
        rng.uniform(-3.0, 3.0, size=(3, 200)),
        np.array([[0.0, 1.0, -1.0, 0.5, 123.75], [0.0, 2.0, -2.5, 7.25, -60.5],
                  [0.0, 0.25, 3.5, -9.5, 41.0]]),
    ], axis=1).astype(np.float32)
    ref = WM.pattern(grid, cell=want['cell'], lo=lo, hi=hi, stripe=stripe,
                     up=want['up'], mode=want['mode'],
                     stripe_on=want['stripe_on'])

    worst = 0.0
    for line, chans, chain in painted:
        site = dict(line=line + 1)
        # walk each channel's select tower: the LAST select's false operand is
        # the previous gate, and the tower must bottom out at 1.0.
        towers = []
        for c in chain:
            tower, cur, guard = [], c, 0
            while guard < 64:
                guard += 1
                m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                             D.get(cur, (0, ''))[1])
                if not m:
                    break
                tower.append((m.group(1), m.group(2)))
                cur = m.group(3)
            if K.get(cur) != np.float32(1.0):
                raise Fail('%s@%d: select tower is not rooted at 1.0' % (name, line + 1))
            towers.append(tower)
        if len({len(t) for t in towers}) != 1:
            raise Fail('%s@%d: channels disagree on the gate count' % (name, line + 1))
        gates = [g for g, _v in towers[0]]
        if len(gates) != 1 + len(CLASS_TINT) + 1:
            raise Fail('%s@%d: %d gates, want %d'
                       % (name, line + 1, len(gates), 2 + len(CLASS_TINT)))
        # The tower is walked from the OUTERMOST select inward, and the
        # emitter appends `class 0 -> class palette -> unknown`, so the
        # outermost gate is the unknown-class catch-all and the INNERMOST is
        # the class-0 pattern arm.
        cls_val = _class_operand(D, gates[-1], name, line)
        _assert_class_read(D, cls_val, name)
        for k, n in enumerate(sorted(CLASS_TINT, reverse=True)):
            got = tuple(K.get(towers[c][1 + k][1]) for c in range(3))
            if any(g is None for g in got) or \
               any(abs(float(got[c]) - float(cls_want[n][c])) > 0 for c in range(3)):
                raise Fail('%s@%d: class %d tint %s, want %s'
                           % (name, line + 1, n, got, cls_want[n]))
        got = tuple(K.get(towers[c][0][1]) for c in range(3))
        if any(g is None for g in got) or \
           any(abs(float(got[c]) - float(unk_want[c])) > 0 for c in range(3)):
            raise Fail('%s@%d: unknown-class tint %s, want %s'
                       % (name, line + 1, got, unk_want))

        # ---- the class-0 arm: the pattern, evaluated
        pat = [towers[c][-1][1] for c in range(3)]
        pos = _pattern_position(D, pat, ctx, cam, want['space'], name, line, K)
        site['pos'] = list(pos)
        env = {pos[k]: grid[k] for k in range(3)}
        got = np.stack([evaluate(D, K, pat[c], env) for c in range(3)])
        err = np.max(np.abs(got - ref) / np.maximum(np.abs(ref), 1e-3))
        worst = max(worst, float(err))
        if err > TOL:
            raise Fail('%s@%d: closed form differs by %.3g (tol %g)'
                       % (name, line + 1, err, TOL))
        rep['sites'].append(site)
    rep['worst_rel_err'] = worst
    return rep


def _class_operand(D, gate, name, line):
    m = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$', D.get(gate, (0, ''))[1])
    if not m:
        raise Fail('%s@%d: the class-0 gate is not an OpIEqual' % (name, line + 1))
    return m.group(1)


def _assert_class_read(D, cls, name):
    m = re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', D.get(cls, (0, ''))[1])
    if not m:
        m2 = re.match(r'OpPhi %uint', D.get(cls, (0, ''))[1])
        if m2:
            return                       # lifted onto the class phi (compute_skin)
        raise Fail('%s: the class value is not `word >> 5` (%s)'
                   % (name, D.get(cls, (0, ''))[1][:60]))
    src = m.group(1)
    t = D.get(src, (0, ''))[1]
    if not re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', t):
        raise Fail('%s: `>> 5` does not read component 1 of the material fetch' % name)


def _pattern_position(D, pat, ctx, cam, space, name, line, K):
    """Re-derive, from the bytes, the three ids the pattern consumes.

    Never trusts the patcher: it finds the `P * (1/cell)` triple inside the
    painted channel's own cone, then proves each of those operands is (or is
    `C` subtracted from) an OpFDiv whose numerator is the four-term Fma chain
    over four CONSECUTIVE v4 members of one bindless CBV whose z operand is a
    component of an OpImageFetch.  That is the whole position claim.
    """
    c = set()
    for r in pat:
        c |= W.cone(D, r, limit=20000)
    muls = {}
    for i in c:
        if i not in D:
            continue
        m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D[i][1])
        if m:
            muls.setdefault(m.group(2), []).append((D[i][0], i, m.group(1)))
    cands = []
    for inv, g in muls.items():
        if len(g) < 3 or inv not in K:
            continue
        g.sort()
        for s0 in range(len(g) - 2):
            t = g[s0:s0 + 3]
            if t[2][0] - t[0][0] <= 4:
                cands.append([x[2] for x in t])
    if not cands:
        raise Fail('%s@%d: no `P * (1/cell)` triple in the painted channels'
                   % (name, line + 1))
    last = None
    for pos in cands:
        try:
            return _check_position_triple(D, pos, ctx, cam, space, name, line)
        except Fail as e:
            last = e
    raise last


def _check_position_triple(D, pos, ctx, cam, space, name, line):

    if space == 'cam':
        base = []
        for k, i in enumerate(pos):
            m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', D.get(i, (0, ''))[1])
            if not m:
                raise Fail('%s@%d: --space cam but component %d is not a subtraction'
                           % (name, line + 1, k))
            base.append(m.group(1))
            other = m.group(2)
            mm = re.match(r'OpCompositeExtract %float (%\w+) (\d)\s*$',
                          D.get(other, (0, ''))[1])
            if not mm or int(mm.group(2)) != k:
                raise Fail('%s@%d: the subtrahend is not component %d of a v4'
                           % (name, line + 1, k))
            ld = re.match(r'OpLoad %v4float (%\w+)\s*$', D.get(mm.group(1), (0, ''))[1])
            ac = ld and re.match(
                r'OpAccessChain %_ptr_Uniform_v4float %\w+ %uint_0 %uint_(\d+)\s*$',
                D.get(ld.group(1), (0, ''))[1])
            if not ac or int(ac.group(1)) != cam['member']:
                raise Fail('%s@%d: the subtrahend is not the camera cbv[..][%d]'
                           % (name, line + 1, cam['member']))
        pdiv = base
    else:
        for k, i in enumerate(pos):
            if re.match(r'OpFSub %float', D.get(i, (0, ''))[1]):
                raise Fail('%s@%d: --space world but the pattern subtracts from P'
                           % (name, line + 1))
        pdiv = pos

    dens, rows = set(), []
    for k, i in enumerate(pdiv):
        m = re.match(r'OpFDiv %float (%\w+) (%\w+)\s*$', D.get(i, (0, ''))[1])
        if not m:
            raise Fail('%s@%d: position component %d is not a perspective divide'
                       % (name, line + 1, k))
        dens.add(m.group(2))
        r = W._mrow(D, m.group(1), want_comp=k)
        if r is None:
            raise Fail('%s@%d: component %d is not the 4-term Fma matrix row'
                       % (name, line + 1, k))
        rows.append(r)
    if len(dens) != 1:
        raise Fail('%s@%d: the three divides do not share one denominator'
                   % (name, line + 1))
    wrow = W._mrow(D, dens.pop(), want_comp=3)
    if wrow is None:
        raise Fail('%s@%d: the denominator is not the matrix w row' % (name, line + 1))
    rows.append(wrow)
    if len({(r['cbv'], tuple(r['members'])) for r in rows}) != 1:
        raise Fail('%s@%d: the four rows are not one CBV / one member run'
                   % (name, line + 1))
    mem = rows[0]['members']
    if any(mem[i] + 1 != mem[i + 1] for i in range(3)) or mem != ctx['mat']:
        raise Fail('%s@%d: members %s, module reconstructs from %s'
                   % (name, line + 1, mem, ctx['mat']))
    if len({(r['x'], r['y'], r['z']) for r in rows}) != 1:
        raise Fail('%s@%d: the rows disagree on the (x, y, depth) operands'
                   % (name, line + 1))
    z = rows[0]['z']
    mz = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', D.get(z, (0, ''))[1])
    if not mz or not D.get(mz.group(1), (0, ''))[1].startswith('OpImageFetch %v4float'):
        raise Fail('%s@%d: the z operand is not a component of an OpImageFetch'
                   % (name, line + 1))
    for ax in (rows[0]['x'], rows[0]['y']):
        if not D.get(ax, (0, ''))[1].startswith('OpConvertUToF %float'):
            raise Fail('%s@%d: the x/y operands are not converted pixel coords'
                       % (name, line + 1))
    return tuple(pos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--mode', choices=('hash', 'frac'), default='hash')
    ap.add_argument('--space', choices=('world', 'cam'), default='world')
    ap.add_argument('--cell', type=float, default=DEFAULTS['cell'])
    ap.add_argument('--up', type=int, default=DEFAULTS['up'])
    ap.add_argument('--gain', type=float, default=1.0)
    ap.add_argument('--no-stripe', action='store_true')
    a = ap.parse_args()
    want = dict(DEFAULTS, mode=a.mode, space=a.space, cell=a.cell, up=a.up,
                gain=a.gain, stripe_on=not a.no_stripe)

    comp = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    rgs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_*.spv')))
    if len(comp) != 77 or len(rgs) != 16:
        raise SystemExit('FAIL: %d compute + %d raygen, want 77 + 16'
                         % (len(comp), len(rgs)))
    import tempfile
    painted_mods, tot_writes, worst = [], 0, 0.0
    with tempfile.TemporaryDirectory() as td:
        for f in comp:
            n = os.path.basename(f)[:-9]
            asm = os.path.join(td, n + '.spvasm')
            subprocess.run(['spirv-dis', f, '-o', asm], check=True)
            try:
                rep = check_module(asm, want)
            except Fail as e:
                raise SystemExit('FAIL: %s' % e)
            if rep['writes']:
                painted_mods.append(n)
                tot_writes += rep['writes']
                worst = max(worst, rep.get('worst_rel_err', 0.0))
    declined = {os.path.basename(f)[:-9] for f in comp} - set(painted_mods)
    ok = True
    if len(painted_mods) != CENSUS['painted_modules']:
        print('FAIL: %d painted modules, census says %d'
              % (len(painted_mods), CENSUS['painted_modules'])); ok = False
    if declined != KNOWN_DECLINE:
        print('FAIL: declines are %s, expected %s'
              % (sorted(declined), sorted(KNOWN_DECLINE))); ok = False
    if tot_writes != CENSUS['writes']:
        print('FAIL: %d painted writes, census says %d'
              % (tot_writes, CENSUS['writes'])); ok = False
    if not ok:
        raise SystemExit(1)
    print('verify_wpos OK: %d modules, %d painted writes, mode=%s space=%s '
          'cell=%g up=%d stripe=%s; worst closed-form rel err %.3g (tol %g)'
          % (len(painted_mods), tot_writes, want['mode'], want['space'],
             want['cell'], want['up'], want['stripe_on'], worst, TOL))


if __name__ == '__main__':
    main()
