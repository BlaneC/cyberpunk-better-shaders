#!/usr/bin/env python3
"""Re-derive every claim handoff/117 makes, from the SHIPPED bytes.

Takes the disassembly of a shipped `micro` rung and nothing else: no report,
no base, no id from the patcher.  For each half it re-finds the structure the
patcher says it emitted and asserts the wiring, then counts.  A rung that has
lost a safeguard (the Laplacian's edge-kill band, the silhouette guard, the
class gate on the cavity) fails here even though it assembles and validates,
which is what makes the decoy rungs of gate 8 meaningful.

    python3 dev/verify_micro.py <rung>/*.spvasm --halves occ,rough,term,gtso,cons
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brdf_sites as BS
import patch_bump as BP
import micro_model as MM

HALVES = ('occ', 'rough', 'term', 'gtso', 'cons')


def fail(msg):
    raise AssertionError(msg)


def cf(x):
    """The float value of a %float_... constant token, or None."""
    m = re.match(r'^%float_(n?)([0-9_]+(?:e(?:n?)[0-9]+)?)$', x or '')
    if not m:
        return None
    s = m.group(2).replace('_', '.').replace('en', 'e-').replace('e', 'e')
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if m.group(1) else v


def near(x, want, tol=1e-5):
    v = cf(x)
    return v is not None and abs(v - want) <= tol * max(1.0, abs(want))


def cavity_chain(D, U, knobs):
    """The single guarded cavity value, re-derived.  Returns (cav, cav0, gate)."""
    hits = []
    for rid, d in D.items():
        # cav0 = NClamp(lap' * (1/cref), 0, 1)
        e = BS.ext(D, rid)
        if not e or e[0] != 'NClamp' or len(e[1]) != 3:
            continue
        if not (near(e[1][1], 0.0) and near(e[1][2], 1.0)):
            continue
        p = BS.fmul_pair(D, e[1][0])
        if not p:
            continue
        sc = [x for x in p if near(x, 1.0 / knobs['cref'])]
        if len(sc) != 1:
            continue
        lap = BS.other(p, sc[0])
        # the edge-kill band: lap' = lap * (1 - u^2(3-2u))
        bp = BS.fmul_pair(D, lap)
        if not bp:
            continue
        wt = [x for x in bp if BS.is_op(D, x, 'OpFSub', 2) and
              near(D[x]['args'][0], 1.0)]
        if len(wt) != 1:
            continue
        poly = D[wt[0]]['args'][1]
        pp = BS.fmul_pair(D, poly)
        if not pp:
            continue
        raw = BS.other(bp, wt[0])
        # raw = 0.25*(4 taps) - centre
        if not BS.is_op(D, raw, 'OpFSub', 2):
            continue
        q = BS.fmul_pair(D, D[raw]['args'][0])
        if not (q and any(near(x, 0.25) for x in q)):
            continue
        s4 = [x for x in q if not near(x, 0.25)]
        if len(s4) != 1 or not BS.is_op(D, s4[0], 'OpFAdd', 2):
            continue
        hits.append((rid, lap, raw))
    if len(hits) != 1:
        fail('want exactly one banded cavity chain, found %d' % len(hits))
    cav0 = hits[0][0]
    sel = [u for u in U.get(cav0, []) if BS.is_op(D, u, 'OpSelect', 3) and
           near(D[u]['args'][2], 0.0)]
    if len(sel) != 1:
        fail('the cavity is not gated by exactly one OpSelect(gate, cav, 0.0)')
    return sel[0], cav0, D[sel[0]]['args'][0]


def check_gate(D, U, gate, guard):
    """The cavity's gate is `class == 1` AND, when the guard is on, 109's
    two silhouette comparisons."""
    d = D.get(gate)
    if d is None:
        fail('the cavity gate is not an instruction')
    if guard:
        if d['op'] != 'OpLogicalAnd':
            fail('the cavity gate is %s, not an AND of the guard and the class'
                 % d['op'])
        parts = list(d['args'])
    else:
        parts = [gate]
    eq = [x for x in parts if BS.is_op(D, x, 'OpIEqual', 2)]
    if len(eq) != 1:
        fail('the cavity gate carries %d class tests, want 1' % len(eq))
    if guard:
        g = [x for x in parts if x not in eq]
        if len(g) != 1 or not BS.is_op(D, g[0], 'OpLogicalAnd', 2):
            fail('the guard half of the cavity gate is not 109s two comparisons')
        for x in D[g[0]]['args']:
            if not BS.is_op(D, x, 'OpFOrdLessThan', 2):
                fail('the guard is not a pair of OpFOrdLessThan')


def check_rough(D, U, cav, knobs, sites):
    """alpha = sel * (1 + KRGH*cav), on the shipped class-1 select itself."""
    n, seen = 0, set()
    for a in sites['alpha']:
        if a['sel'] in seen:
            continue
        seen.add(a['sel'])
        if a['scale'] is None:
            continue
        g = a['scale']
        if not (BS.is_op(D, g, 'OpFAdd', 2) and
                any(near(x, 1.0) for x in D[g]['args'])):
            continue
        k = [x for x in D[g]['args'] if not near(x, 1.0)]
        p = BS.fmul_pair(D, k[0]) if k else None
        if not (p and cav in p and any(near(x, knobs['krgh']) for x in p)):
            continue
        # nothing may read the shipped select except this scaling
        us = [u for u in U.get(a['sel'], []) if u != a['alpha']]
        if us:
            fail('the roughness select %s still has %d unscaled reader(s)'
                 % (a['sel'], len(us)))
        n += 1
    return n


def check_gtso(D, U, knobs, sites):
    n = 0
    for ss in sites['spec']:
        # the detector re-finds the PATCHED tail, `S_base * SO`; the ladder is
        # in its own definition, not below it.
        pp = BS.fmul_pair(D, ss['S'])
        for so in (pp or []):
            e = BS.ext(D, so)
            if not e or e[0] != 'NClamp':
                continue
            s1 = e[1][0]
            if not BS.is_op(D, s1, 'OpFAdd', 2):
                continue
            ok = False
            for c in D[s1]['args']:
                if not (BS.is_op(D, c, 'OpFSub', 2) and near(D[c]['args'][1], 1.0)):
                    continue
                pw = BS.ext(D, D[c]['args'][0])
                if not pw or pw[0] != 'Exp2':
                    continue
                mm = BS.fmul_pair(D, pw[1][0])
                if not mm:
                    continue
                lg = [x for x in mm if (BS.ext(D, x) or ('',))[0] == 'Log2']
                ex = [x for x in mm if (BS.ext(D, x) or ('',))[0] == 'Exp2']
                if len(lg) != 1 or len(ex) != 1:
                    continue
                inner = BS.ext(D, ex[0])[1][0]
                if not BS.is_op(D, inner, 'OpFSub', 2) or \
                        not near(D[inner]['args'][1], 1.0):
                    continue
                q = BS.fmul_pair(D, D[inner]['args'][0])
                if q and any(near(x, -16.0) for x in q):
                    ok = True
            if not ok:
                continue
            n += 1
            break
    return n


def check_diffuse(D, U, cav, knobs, sites, halves):
    """occ and term ride one product on the diffuse BRDF; cons rides each of
    the three channel products with its OWN Fresnel component."""
    n_occ = n_term = n_cons = 0
    for ds in sites['diffuse']:
        # likewise the diffuse BRDF the detector returns is `BRDF * factors`
        dp = BS.fmul_pair(D, ds['diff'])
        for f in (dp or []):
            fac = set(BS.mnodes(D, f))
            if 'occ' in halves:
                for x in fac:
                    if BS.is_op(D, x, 'OpFSub', 2) and near(D[x]['args'][0], 1.0):
                        q = BS.fmul_pair(D, D[x]['args'][1])
                        if q and cav in q and any(near(y, knobs['kocc'])
                                                  for y in q):
                            n_occ += 1
                            break
            if 'term' in halves:
                for x in fac:
                    # 1 + w - w*w
                    if not BS.is_op(D, x, 'OpFSub', 2):
                        continue
                    ww = BS.fmul_pair(D, D[x]['args'][1])
                    a0 = D[x]['args'][0]
                    if ww and ww[0] == ww[1] and BS.is_op(D, a0, 'OpFAdd', 2) \
                            and ww[0] in D[a0]['args'] \
                            and any(near(y, 1.0) for y in D[a0]['args']):
                        e = BS.ext(D, ww[0])
                        if e and e[0] == 'NClamp' and \
                                D.get(e[1][0], {}).get('op') == 'OpFDiv':
                            n_term += 1
                            break
        if 'cons' in halves:
            for ch in ds['chan']:
                for u in U.get(ch, []):
                    p = BS.fmul_pair(D, u)
                    if not p:
                        continue
                    s = BS.other(p, ch)
                    if BS.is_op(D, s, 'OpSelect', 3) and near(D[s]['args'][2], 1.0):
                        kd = D[s]['args'][1]
                        if BS.is_op(D, kd, 'OpFSub', 2) and near(D[kd]['args'][0], 1.0):
                            n_cons += 1
                            break
    return n_occ, n_term, n_cons


def verify(path, halves, knobs, guard=True):
    src = open(path).read()
    ctx, sites = BS.find_sites(src)
    D, U = ctx['D'], ctx['U']
    out = dict(module=os.path.basename(path),
               census=dict(alpha=len({a['sel'] for a in sites['alpha']}),
                           diffuse=len(sites['diffuse']),
                           spec=len(sites['spec'])))
    cav = None
    try:
        cav, cav0, gate = cavity_chain(D, U, knobs)
        out['cavity'] = cav
    except AssertionError:
        if {'occ', 'rough', 'gtso'} & set(halves):
            raise
    if cav is not None and ({'occ', 'rough', 'gtso'} & set(halves)):
        check_gate(D, U, gate, guard)
    # EVERY half is looked for, always: a rung that ships a half it does not
    # declare must fail here, or "read as another rung" proves nothing.
    n_occ, n_term, n_cons = check_diffuse(D, U, cav, knobs, sites, set(HALVES))
    out['applied'] = dict(rough=check_rough(D, U, cav, knobs, sites),
                          gtso=check_gtso(D, U, knobs, sites),
                          occ=n_occ, term=n_term, cons=n_cons)
    for h, want in (('rough', out['census']['alpha']),
                    ('occ', len(sites['diffuse'])),
                    ('gtso', len(sites['spec'])),
                    ('cons', 3 * len(sites['diffuse']))):
        if h in halves and out['applied'][h] != want:
            fail('%s: %s verified at %d of %d sites'
                 % (out['module'], h, out['applied'][h], want))
    if 'term' in halves and out['applied']['term'] == 0 and sites['diffuse']:
        fail('%s: term verified at no site' % out['module'])
    for h in HALVES:
        if h not in halves and out['applied'][h]:
            fail('%s: %s is OFF in this rung but verified at %d sites'
                 % (out['module'], h, out['applied'][h]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--halves', default=','.join(HALVES))
    ap.add_argument('--cref', type=float, default=float(MM.CREF))
    ap.add_argument('--kocc', type=float, default=float(MM.KOCC))
    ap.add_argument('--krgh', type=float, default=float(MM.KRGH))
    ap.add_argument('--no-guard', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    halves = {x for x in a.halves.split(',') if x}
    bad = set(halves) - set(HALVES)
    if bad:
        print('unknown half(s): %s' % ','.join(sorted(bad)), file=sys.stderr)
        return 2
    knobs = dict(cref=a.cref, kocc=a.kocc, krgh=a.krgh)
    paths, tmp, ndecl = [], None, 0
    for m in a.modules:
        if os.path.isdir(m):
            tmp = tmp or tempfile.mkdtemp(prefix='verify_micro.')
            for f in sorted(glob.glob(os.path.join(m, '*.dxil.spv'))):
                if os.path.basename(f)[:16] in BP.KNOWN_DECLINE:
                    ndecl += 1
                    continue
                o = os.path.join(tmp, os.path.basename(f) + '.spvasm')
                subprocess.run(['spirv-dis', '--no-color', f, '-o', o],
                               check=True, capture_output=True)
                paths.append(o)
        else:
            paths.append(m)
    if not paths:
        print('no modules', file=sys.stderr)
        return 2
    rows, errs = [], []
    for p in paths:
        try:
            rows.append(verify(p, halves, knobs, guard=not a.no_guard))
        except AssertionError as e:
            errs.append('%s: %s' % (os.path.basename(p), e))
    tot = dict(modules=len(rows), errors=len(errs), declined=ndecl)
    for k in HALVES:
        tot[k] = sum(r['applied'][k] for r in rows)
    for k in ('alpha', 'diffuse', 'spec'):
        tot[k] = sum(r['census'][k] for r in rows)
    if not a.quiet:
        print(json.dumps(tot, indent=1))
    for e in errs[:20]:
        print('FAIL ' + e, file=sys.stderr)
    return 1 if errs else 0


if __name__ == '__main__':
    raise SystemExit(main())
