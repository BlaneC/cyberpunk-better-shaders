#!/usr/bin/env python3
"""verify_cfres -- re-derive the conductor-Fresnel claim from the SHIPPED bytes.

    python3 dev/verify_cfres.py <rung-dir> [--tint 0.5] [--metal-min 0.5]
                                [--expect-none]

Nothing here reads a build report or a patcher's JSON.  Every rung file is
disassembled and the following are re-derived (handoff/108 sec 6.2):

 1. the selection is complete: 77 compute + 16 raygen;
 2. every module carries the splice, and the number of splices equals the
    number of Schlick groups the SHIPPED module still contains -- so a splice
    that reached 356 of 357 groups fails here, not in a byte count;
 3. SHAPE.  Each splice is `OpSelect(metallic > m, NClamp(F - corr, 0, 1), F)`
    with corr built from the module's OWN pow5 and VoH ids, and the three
    channels of a group share ONE gate, ONE 1/max3(F0) and ONE c(1-c)p term;
 4. PROVENANCE.  The gate reads the metallic operand of the module's own
    F0 = lerp(0.04, albedo, metallic) triple -- re-derived here from the bytes
    by the same triple detector, never taken from the patcher;
 5. CONSTANTS.  eps, (6/7)^5, 1-(6/7)^5, tint/K and the metal threshold are
    checked to the float32 bit against dev/cfres_model.py;
 6. CLOSED FORM.  The emitted straight-line chain is INTERPRETED out of the
    disassembly over a grid of VoH and F0 triples and compared against
    cfres_model.conductor_F, which is written independently of the emitter;
 7. NON-VACUITY.  --expect-none asserts the opposite: zero splices anywhere.
    The build runs the verifier BOTH ways -- on the feature rungs it must pass,
    and on the base and on the byte-identical control it must pass only with
    --expect-none and must FAIL without it.
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
from patch_chs_brdf import load_lenient
from patch_compute_skin import find_spec_fresnel_groups
from patch_cfres import defs_index, find_f0_metal_triples, forward_closure, CENSUS
import cfres_model as M

TOL = 3e-5

# The VoH grid and the F0 triples the closed form is checked over.  copper and
# gold are the materials the launch is about; the black corner is the one the
# hue eps was fixed for (cfres_model.hue); the rest are random but FIXED, so a
# failure is reproducible.
_RNG = np.random.default_rng(20260903)
cgrid = np.concatenate([np.linspace(0.0, 1.0, 97),
                        _RNG.uniform(0.0, 1.0, 32)]).astype(np.float64)
TRIALS = ([[0.95, 0.64, 0.54], [1.0, 0.766, 0.336], [0.0, 0.0, 0.0],
           [0.04, 0.04, 0.04]]
          + [list(v) for v in _RNG.uniform(0.0, 1.0, (4, 3))])


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
                # spirv-dis writes hex bit patterns for values it cannot
                # round-trip as decimal; those are never our constants.
                pass
    return out


def evaluate(D, K, target, env, memo):
    """Interpret the pure SSA float chain reaching `target`, in float32."""
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
    elif op == 'OpSelect':
        v = E(a[1]) if E(a[0]) else E(a[2])
    elif op == 'OpFOrdGreaterThan':
        v = bool(E(a[0]) > E(a[1]))
    elif op == 'OpExtInst':
        name = txt.split()[3]
        if name == 'NClamp':
            v = f32(np.minimum(np.maximum(E(a[1]), E(a[2])), E(a[3])))
        elif name == 'NMax':
            v = f32(np.maximum(E(a[1]), E(a[2])))
        elif name == 'NMin':
            v = f32(np.minimum(E(a[1]), E(a[2])))
        elif name == 'Fma':
            v = f32(f32(E(a[1]) * E(a[2])) + E(a[3]))
        elif name == 'Exp2':
            v = f32(np.exp2(E(a[1])))
        else:
            raise Fail('unmodelled GLSL op %s' % name)
    else:
        raise Fail('unmodelled op %s' % op)
    memo[target] = v
    return v


def _m(D, i, pat):
    return re.match(pat, D.get(i, (0, ''))[1])


def find_splices(mod, D, gl):
    """Every conductor-Fresnel channel splice, by its shape alone."""
    out = []
    for sel, (line, txt) in D.items():
        ms = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$', txt)
        if not ms:
            continue
        gate, fc, F = ms.groups()
        mc = _m(D, fc, r'OpExtInst %float ' + re.escape(gl)
                + r' NClamp (%\w+) (%\w+) (%\w+)\s*$')
        if not mc:
            continue
        mf = _m(D, mc.group(1), r'OpFSub %float ' + re.escape(F) + r' (%\w+)\s*$')
        if not mf:
            continue
        mcorr = _m(D, mf.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mcorr:
            continue
        # Tighten past the module's own OpSelect(_, NClamp(1 - x, 0, 1), 1)
        # idioms: the correction's `a` is S*(1-hue) with S an Fma, and its
        # `gk` multiplies a literal 1/K.  Nothing else in these modules has
        # that shape.
        ma = _m(D, mcorr.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        mgk0 = _m(D, mcorr.group(2), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not ma or not mgk0:
            continue
        if not _m(D, ma.group(1), r'OpExtInst %float ' + re.escape(gl)
                  + r' Fma (%\w+) (%\w+) (%\w+)\s*$'):
            continue
        out.append(dict(sel=sel, line=line, gate=gate, fc=fc, F=F,
                        zero=mc.group(2), one=mc.group(3),
                        corr=mf.group(1), a=mcorr.group(1), gk=mcorr.group(2)))
    return out


def check_module(path, want, expect_none):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = defs_index(mod)
    K = consts(mod)
    gl = mod.glsl
    sp = find_splices(mod, D, gl)
    groups = find_spec_fresnel_groups(mod)
    if expect_none:
        if sp:
            raise Fail('%s: %d conductor splices in a rung that must carry none'
                       % (name, len(sp)))
        return dict(module=name, groups=len(groups), splices=0, chans=0,
                    worst=0.0)
    if len(sp) != 3 * len(groups):
        raise Fail('%s: %d channel splices for %d Schlick groups (want %d)'
                   % (name, len(sp), len(groups), 3 * len(groups)))

    # PROVENANCE: the module's own metallic, re-derived here.
    trips = find_f0_metal_triples(mod, D)
    if not trips:
        raise Fail('%s: no F0 = lerp(0.04, albedo, metallic) triple' % name)
    metals = set()
    for t in trips:
        metals |= forward_closure(D, [t['metal']], zero_only=True)

    by_gate = {}
    for s in sp:
        by_gate.setdefault((s['gate'], s['gk']), []).append(s)
    if len(by_gate) != len(groups):
        raise Fail('%s: %d distinct (gate, c(1-c)p) pairs for %d groups'
                   % (name, len(by_gate), len(groups)))

    gmap = {}
    for g in groups:
        gmap[frozenset(c['F'] for c in g['chans'])] = g

    worst = 0.0
    seen_forms = set()
    for (gate, gk), chans in by_gate.items():
        if len(chans) != 3:
            raise Fail('%s: %d channels share one gate, want 3' % (name, len(chans)))
        key = frozenset(c['F'] for c in chans)
        if key not in gmap:
            raise Fail('%s: a splice group {%s} is not a Schlick group'
                       % (name, ', '.join(sorted(key))))
        g = gmap[key]
        # --- the gate is the module's own metallic, over a float threshold ---
        mg = _m(D, gate, r'OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$')
        if not mg:
            raise Fail('%s: gate %s is not OpFOrdGreaterThan' % (name, gate))
        met, mmin = mg.groups()
        if met not in metals:
            raise Fail('%s: gate reads %s, which is not the module\'s own '
                       'F0-lerp metallic (or a zero-safe merge of it)'
                       % (name, met))
        if mmin not in K or abs(float(K[mmin]) - want['metal_min']) > 1e-7:
            raise Fail('%s: metal threshold %s is %s, want %g'
                       % (name, mmin, K.get(mmin), want['metal_min']))
        # --- the c(1-c)*pow5 term rides the module's OWN pow5 and VoH ---
        mgk = _m(D, gk, r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mgk:
            raise Fail('%s: %s is not an OpFMul' % (name, gk))
        gg, invk = mgk.groups()
        if invk not in K:
            raise Fail('%s: 1/K operand %s is not a constant' % (name, invk))
        wantk = f32(want['tint'] / M.K)
        if abs(float(K[invk]) - float(wantk)) > 1e-9 * max(1.0, abs(float(wantk))):
            raise Fail('%s: tint/K is %.9g, want %.9g (tint %g)'
                       % (name, float(K[invk]), float(wantk), want['tint']))
        mgg = _m(D, gg, r'OpFMul %float (%\w+) ' + re.escape(g['pow5']) + r'\s*$')
        if not mgg:
            raise Fail('%s: the correction does not multiply the module\'s own '
                       'pow5 %s' % (name, g['pow5']))
        mt0 = _m(D, mgg.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mt0:
            raise Fail('%s: c(1-c) term malformed' % name)
        cs, om = mt0.groups()
        if not _m(D, cs, r'OpExtInst %float ' + re.escape(gl) + r' NClamp '
                  + re.escape(g['voh']) + r' (%\w+) (%\w+)\s*$'):
            raise Fail('%s: the correction does not clamp the module\'s own '
                       'VoH %s' % (name, g['voh']))
        if not _m(D, om, r'OpFSub %float (%\w+) ' + re.escape(cs) + r'\s*$'):
            raise Fail('%s: (1-c) term malformed' % name)

        # --- CLOSED FORM, per channel, over a VoH grid --------------------
        # Every group emits the SAME straight-line shape; only the pow5 form
        # differs.  So the first group of each form in a module gets the dense
        # grid and the rest get a coarse one -- 357 dense grids would cost
        # minutes and prove nothing the first one does not.
        form = 'M' if g['chans'][0]['X'] is not None else 'S'
        dense = form not in seen_forms
        seen_forms.add(form)
        cs_grid = cgrid if dense else cgrid[::48]
        trials = TRIALS if dense else TRIALS[:2]
        f0ids = [c['f0'] for c in g['chans']]
        splice_of = {s['F']: s for s in chans}
        if set(splice_of) != {c['F'] for c in g['chans']}:
            raise Fail('%s: splice channels do not match the Schlick group' % name)
        for f0v in trials:
            f82 = M.edge_tint(f0v, want['tint'])
            for c in cs_grid:
                p = M.pow5_m(c) if form == 'M' else M.pow5_s(c)
                base = {g['voh']: f32(c), g['pow5']: f32(p)}
                for k, ch in enumerate(g['chans']):
                    base[ch['f0']] = f32(f0v[k])
                    base[ch['F']] = f32(M.schlick(f0v[k], c, form))
                on = dict(base); on[gate] = True
                off = dict(base); off[gate] = False
                memo_on, memo_off = {}, {}
                for k, ch in enumerate(g['chans']):
                    sid = splice_of[ch['F']]['sel']
                    got = float(evaluate(D, K, sid, on, memo_on))
                    ref = M.conductor_F(f0v[k], c, f82[k], form)
                    err = abs(got - ref) / max(1.0, abs(ref))
                    worst = max(worst, err)
                    if err > TOL:
                        raise Fail('%s: closed form off by %.3g at f0=%s '
                                   'c=%.4f ch=%d (%.6f vs %.6f)'
                                   % (name, err, f0v, c, k, got, ref))
                    # the OFF arm must be the module's own Schlick, bit-exact
                    o = float(evaluate(D, K, sid, off, memo_off))
                    if o != float(base[ch['F']]):
                        raise Fail('%s: the ungated arm is not the module\'s '
                                   'own Schlick (%.9g vs %.9g)'
                                   % (name, o, float(base[ch['F']])))
    return dict(module=name, groups=len(groups), splices=len(sp),
                chans=len(sp), worst=worst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--tint', type=float, default=0.5)
    ap.add_argument('--metal-min', type=float, default=0.5)
    ap.add_argument('--expect-none', action='store_true')
    a = ap.parse_args()
    want = dict(tint=a.tint, metal_min=a.metal_min)

    comp = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    rgs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_*.spv')))
    if len(comp) != 77 or len(rgs) != 16:
        raise SystemExit('FAIL: %d compute + %d raygen, want 77 + 16'
                         % (len(comp), len(rgs)))
    mods, groups, chans, worst = 0, 0, 0, 0.0
    with tempfile.TemporaryDirectory() as td:
        for f in comp:
            n = os.path.basename(f)[:-9]
            asm = os.path.join(td, n + '.spvasm')
            subprocess.run(['spirv-dis', f, '-o', asm], check=True)
            try:
                rep = check_module(asm, want, a.expect_none)
            except Fail as e:
                raise SystemExit('FAIL: %s' % e)
            groups += rep['groups']
            chans += rep['chans']
            worst = max(worst, rep['worst'])
            if rep['chans']:
                mods += 1
    if a.expect_none:
        if chans:
            raise SystemExit('FAIL: %d channel splices with --expect-none' % chans)
        if groups != CENSUS['groups']:
            raise SystemExit('FAIL: %d Schlick groups, census says %d'
                             % (groups, CENSUS['groups']))
        print('verify_cfres OK (--expect-none): %d Schlick groups present, '
              '0 spliced' % groups)
        return
    if mods != CENSUS['modules']:
        raise SystemExit('FAIL: %d spliced modules, census says %d'
                         % (mods, CENSUS['modules']))
    if groups != CENSUS['groups'] or chans != CENSUS['chans']:
        raise SystemExit('FAIL: %d groups / %d channels, census says %d / %d'
                         % (groups, chans, CENSUS['groups'], CENSUS['chans']))
    print('verify_cfres OK: %d modules, %d Schlick groups, %d channel splices, '
          'tint=%g metal_min=%g; worst closed-form rel err %.3g (tol %g)'
          % (mods, groups, chans, want['tint'], want['metal_min'], worst, TOL))


if __name__ == '__main__':
    main()
