#!/usr/bin/env python3
"""80: prove the emitted CLOTH sheen, from the ASSEMBLED TEXT of a parked rung.

The same discipline as dev/verify_bleed_norm.py (53 §4, 78 §3): not "the
patcher reported 457 sites" but "the instructions in the shipped .spv,
disassembled, re-parsed and EXECUTED, compute the lobe the model says".

For every cloth site in every compute module of a rung it:

  1. finds the chain structurally, from its GATE -- an OpLogicalAnd of
     (not class==1 && not class==4) with a dielectric test on max3(F0) --
     never by line number and never by trusting the build report;
  2. checks the baked constants against the knobs (k_cloth, a_cloth via
     1/(2a) and (2+1/a)/2pi, cloth_max, cloth_f0max, and the ramp's
     a0 / 1/(a1-a0));
  3. proves the gate reads the SAME class shift both gates read, and that
     the site's own light cosine (the peach fold) multiplies the term;
  4. INTERPRETS the emitted instructions over a grid of (NoH, NoL, NoV,
     alpha) x gate and compares against the closed form;
  5. asserts GATE FALSE IS EXACT IDENTITY: the added term is bit-zero and the
     site's specular comes out equal to its input, and the diffuse damp
     factor is exactly 1.0;
  6. does the same for the diffuse damp chain, and asserts the census counts
     (457 sheen sites, 173 Burley sites) or fails.

    ./dev/verify_cloth_sheen.py gi-50b-bleed-oil-sheen-deep-cloth --k 0.5
    ./dev/verify_cloth_sheen.py <a parked rung name or a directory> [--k K]
"""
import argparse, math, os, re, subprocess, sys, tempfile, glob, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_bleed_norm import Mod, f32


def ev(mod, rid, bind, gates, memo):
    """Interpret one emitted value; `gates` binds each OpSelect condition id."""
    if rid in bind:
        return bind[rid]
    if rid in memo:
        return memo[rid]
    if rid in mod.const:
        return mod.const[rid]
    b = mod.op(rid)
    m = re.match(r'OpF(Mul|Add|Sub|Div) %float (%[\w$]+) (%[\w$]+)$', b)
    if m:
        o = m.group(1)
        a = ev(mod, m.group(2), bind, gates, memo)
        c = ev(mod, m.group(3), bind, gates, memo)
        v = {'Mul': a * c, 'Add': a + c, 'Sub': a - c,
             'Div': (a / c if c else float('inf'))}[o]
    else:
        m = re.match(r'OpExtInst %float %[\w$]+ (NClamp|NMax|NMin|Log2|Exp2) '
                     r'(%[\w$]+)(?: (%[\w$]+))?(?: (%[\w$]+))?$', b)
        if m:
            g = m.groups()
            a = ev(mod, g[1], bind, gates, memo)
            if g[0] == 'Log2':
                v = math.log2(a) if a > 0 else float('-inf')
            elif g[0] == 'Exp2':
                v = 2.0 ** a
            else:
                c = ev(mod, g[2], bind, gates, memo)
                v = (min(max(a, c), ev(mod, g[3], bind, gates, memo))
                     if g[0] == 'NClamp' else
                     (max(a, c) if g[0] == 'NMax' else min(a, c)))
        else:
            m = re.match(r'OpSelect %float (%[\w$]+) (%[\w$]+) (%[\w$]+)$', b)
            if not m:
                raise KeyError(f"{mod.name}: unevaluatable {rid} = {b!r}")
            cond = m.group(1)
            if cond not in gates:
                raise KeyError(f"{mod.name}: unbound select condition {cond}")
            v = ev(mod, m.group(2) if gates[cond] else m.group(3),
                   bind, gates, memo)
    v = f32(v)
    memo[rid] = v
    return v


def _c(mod, rid):
    return mod.const.get(rid)


def cloth_sites(mod):
    """Every emitted cloth chain, found from its gate outward."""
    for gid, body in mod.defs.items():
        m = re.match(r'OpLogicalAnd %bool (%[\w$]+) (%[\w$]+)$', body)
        if not m:
            continue
        nsnh = diel = None
        for a, b in (m.groups(), m.groups()[::-1]):
            if re.match(r'OpFOrdLessThan %bool ', mod.op(b) or ''):
                nsnh, diel = a, b
                break
        if diel is None:
            continue
        md = re.match(r'OpFOrdLessThan %bool (%[\w$]+) (%[\w$]+)$', mod.op(diel))
        f0max_id, thr = md.groups()
        if thr not in mod.const:
            continue
        # max3(F0)
        m2 = re.match(r'OpExtInst %float %[\w$]+ NMax (%[\w$]+) (%[\w$]+)$',
                      mod.op(f0max_id) or '')
        if not m2:
            continue
        m1 = re.match(r'OpExtInst %float %[\w$]+ NMax (%[\w$]+) (%[\w$]+)$',
                      mod.op(m2.group(1)) or '')
        if not m1:
            continue
        f0 = (m1.group(1), m1.group(2), m2.group(2))
        # not-skin && not-hair
        mn = re.match(r'OpLogicalAnd %bool (%[\w$]+) (%[\w$]+)$',
                      mod.op(nsnh) or '')
        if not mn:
            continue
        eqs = []
        for x in mn.groups():
            mx = re.match(r'OpLogicalNot %bool (%[\w$]+)$', mod.op(x) or '')
            if not mx:
                break
            me = re.match(r'OpIEqual %bool (%[\w$]+) (%[\w$]+)$',
                          mod.op(mx.group(1)) or '')
            if not me:
                break
            eqs.append(me.groups())
        if len(eqs) != 2:
            continue
        # the OpSelect this gate drives, and the FAdd that consumes it
        sel = [u for u in mod.uses.get(gid, [])
               if re.match(r'OpSelect %float ' + re.escape(gid), mod.op(u) or '')]
        if len(sel) != 1:
            continue
        sel = sel[0]
        ms = re.match(r'OpSelect %float %[\w$]+ (%[\w$]+) (%[\w$]+)$', mod.op(sel))
        term, off = ms.groups()
        add = [u for u in mod.uses.get(sel, [])
               if re.match(r'OpFAdd %float ', mod.op(u) or '')]
        if len(add) != 1:
            continue
        ma = re.match(r'OpFAdd %float (%[\w$]+) (%[\w$]+)$', mod.op(add[0]))
        base = [x for x in ma.groups() if x != sel]
        if len(base) != 1:
            continue
        yield dict(gate=gid, f0=f0, thr=mod.const[thr], eqs=eqs, sel=sel,
                   term=term, off=off, add=add[0], base=base[0], nsnh=nsnh)


def walk_term(mod, term):
    """term = (((lobe*k)*w)*wr)*fold -- peel it and name every factor.

    Three peels leave `cur` at the (lobe * k_cloth) product; the reversed
    chain is then [w, wr, fold], the shipped shape (cloth_defres = 1, so the
    Schlick-cancelling w is always present -- a build with cloth_defres = 0
    would have one factor fewer and is deliberately not accepted here).
    """
    chain = []
    cur = term
    for _ in range(3):
        m = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(cur) or '')
        if not m:
            return None
        chain.append(m.group(2))
        cur = m.group(1)
    chain.reverse()                       # [w, wr, fold] outermost-last
    return dict(kmul=cur, factors=chain)


def damp_sites(mod, dampk):
    """fac = 1 - select(nsnh, wr*dampk, 0); fd' = fd * fac."""
    for rid, body in mod.defs.items():
        m = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)$', body)
        if not m or _c(mod, m.group(1)) != 1.0:
            continue
        ms = re.match(r'OpSelect %float (%[\w$]+) (%[\w$]+) (%[\w$]+)$',
                      mod.op(m.group(2)) or '')
        if not ms:
            continue
        mm = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$',
                      mod.op(ms.group(2)) or '')
        if not mm or _c(mod, mm.group(2)) is None:
            continue
        if abs(_c(mod, mm.group(2)) - f32(dampk)) > 1e-9:
            continue
        use = [u for u in mod.uses.get(rid, [])
               if re.match(r'OpFMul %float ', mod.op(u) or '')]
        if len(use) != 1:
            continue
        mu = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(use[0]))
        fd = [x for x in mu.groups() if x != rid]
        yield dict(fac=rid, sel=ms.group(1), wr=mm.group(1),
                   zero=ms.group(3), out=use[0], fd=fd[0])


GRID = [(0.02, 0.10, 0.15, 0.49), (0.30, 0.40, 0.20, 0.49),
        (0.70, 0.60, 0.55, 0.25), (0.95, 0.90, 0.85, 0.09),
        (0.10, 0.05, 0.99, 0.72), (0.55, 0.99, 0.05, 0.16),
        (1.00, 1.00, 1.00, 0.36), (0.001, 0.30, 0.30, 0.04)]


def closed(noh, c0, c1, alpha, k, a, cap, a0, rspan, eps=1e-6, den_min=1e-4):
    u = f32(max(f32(1.0 - f32(noh * noh)), eps))
    dc = f32(2.0 ** f32(f32(math.log2(u)) * f32(1.0 / (2.0 * a))))
    q = f32(max(f32(f32(f32(c0 + c1) - f32(c0 * c1)) * 4.0), den_min))
    lobe = f32(min(f32(f32(f32(dc * f32(1.0 / q))) * f32((2.0 + 1.0 / a) / (2 * math.pi))), cap))
    voh = f32(min(max(f32(f32(c0 + c1) / f32(max(f32(noh + noh), eps))), 0.0), 1.0))
    om = f32(1.0 - voh)
    w = f32(1.0 - f32(f32(f32(om * om) * f32(om * om)) * om))
    wr = f32(min(max(f32(f32(alpha - a0) * rspan), 0.0), 1.0))
    return lobe, w, wr, f32(f32(f32(f32(lobe * k) * w) * wr))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--k', type=float, default=0.5)
    ap.add_argument('--a', type=float, default=0.25)
    ap.add_argument('--cap', type=float, default=0.5)
    ap.add_argument('--f0max', type=float, default=0.09)
    ap.add_argument('--a0', type=float, default=0.10)
    ap.add_argument('--a1', type=float, default=0.30)
    ap.add_argument('--E', type=float, default=0.0072)
    ap.add_argument('--damp', type=float, default=1.0)
    ap.add_argument('--sites', type=int, default=457)
    ap.add_argument('--fd', type=int, default=173)
    ap.add_argument('--tol', type=float, default=2e-5)
    o = ap.parse_args()

    d = o.rung
    if not os.path.isdir(d):
        d = os.path.join(os.environ.get('CALLISTO_INSTALL_DIR',
                                        os.path.expanduser('~/.local/lib/callisto')),
                         'skin.set', o.rung)
    spvs = sorted(glob.glob(os.path.join(d, '*.dxil.spv')))
    if not spvs:
        sys.exit(f"no *.dxil.spv in {d}")
    dampk = o.k * o.E * o.damp
    rspan = 1.0 / (o.a1 - o.a0)
    nsite = nfd = npt = 0
    bad = []
    tmp = tempfile.mkdtemp(prefix='clothver.')
    for spv in spvs:
        asm = os.path.join(tmp, os.path.basename(spv) + '.spvasm')
        subprocess.run(['spirv-dis', spv, '-o', asm], check=True)
        mod = Mod(asm)
        shifts = set()
        for s in cloth_sites(mod):
            # --- structure -------------------------------------------------
            vals = sorted(_c2 for _c2 in
                          (int(mod.defs.get(e[1], 'OpConstant %uint -1').split()[-1])
                           if re.match(r'OpConstant %uint \d+$', mod.defs.get(e[1], ''))
                           else -1 for e in s['eqs']))
            if vals != [1, 4]:
                bad.append((mod.name, s['gate'], f'gate classes {vals}, want [1, 4]'))
                continue
            if len({e[0] for e in s['eqs']}) != 1:
                bad.append((mod.name, s['gate'], 'the two class tests read different words'))
                continue
            shifts.add(s['eqs'][0][0])
            if abs(s['thr'] - f32(o.f0max)) > 1e-7:
                bad.append((mod.name, s['gate'], f"f0max {s['thr']} != {o.f0max}"))
                continue
            if mod.const.get(s['off']) != 0.0:
                bad.append((mod.name, s['gate'], 'gate-false arm is not the zero constant'))
                continue
            w = walk_term(mod, s['term'])
            if not w:
                bad.append((mod.name, s['gate'], 'term is not the 4-factor chain'))
                continue
            mk = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(w['kmul']))
            if not mk or abs((mod.const.get(mk.group(2)) or -1) - f32(o.k)) > 1e-7:
                bad.append((mod.name, s['gate'], 'k_cloth constant missing/wrong'))
                continue
            lobe_id = mk.group(1)
            ml = re.match(r'OpExtInst %float %[\w$]+ NMin (%[\w$]+) (%[\w$]+)$',
                          mod.op(lobe_id) or '')
            if not ml or abs((mod.const.get(ml.group(2)) or -1) - f32(o.cap)) > 1e-7:
                bad.append((mod.name, s['gate'], 'cloth_max cap missing/wrong'))
                continue
            # leaves: noh from (1 - noh*noh); c0,c1 from (c0+c1); alpha from ramp
            pre = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(ml.group(1)))
            sh = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(pre.group(1)))
            dcx = re.match(r'OpExtInst %float %[\w$]+ Exp2 (%[\w$]+)$', mod.op(sh.group(1)))
            xe = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(dcx.group(1)))
            if abs((mod.const.get(xe.group(2)) or -1) - f32(1.0 / (2 * o.a))) > 1e-6:
                bad.append((mod.name, s['gate'], '1/(2a) constant wrong'))
                continue
            if abs((mod.const.get(pre.group(2)) or -1)
                   - f32((2 + 1 / o.a) / (2 * math.pi))) > 1e-6:
                bad.append((mod.name, s['gate'], '(2+1/a)/2pi constant wrong'))
                continue
            lg = re.match(r'OpExtInst %float %[\w$]+ Log2 (%[\w$]+)$', mod.op(xe.group(1)))
            um = re.match(r'OpExtInst %float %[\w$]+ NMax (%[\w$]+) (%[\w$]+)$',
                          mod.op(lg.group(1)))
            usub = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)$', mod.op(um.group(1)))
            t2 = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(usub.group(2)))
            noh = t2.group(1)
            vn = re.match(r'OpFDiv %float (%[\w$]+) (%[\w$]+)$', mod.op(sh.group(2)))
            qm = re.match(r'OpExtInst %float %[\w$]+ NMax (%[\w$]+) (%[\w$]+)$',
                          mod.op(vn.group(2)))
            q4 = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(qm.group(1)))
            qs = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)$', mod.op(q4.group(1)))
            sm = re.match(r'OpFAdd %float (%[\w$]+) (%[\w$]+)$', mod.op(qs.group(1)))
            c0, c1 = sm.groups()
            wr_id = w['factors'][1]
            mr = re.match(r'OpExtInst %float %[\w$]+ NClamp (%[\w$]+) '
                          r'(%[\w$]+) (%[\w$]+)$', mod.op(wr_id) or '')
            if not mr:
                bad.append((mod.name, s['gate'], 'ramp is not an NClamp'))
                continue
            mru = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(mr.group(1)))
            if abs((mod.const.get(mru.group(2)) or -1) - f32(rspan)) > 1e-5:
                bad.append((mod.name, s['gate'], '1/(a1-a0) constant wrong'))
                continue
            mrs = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)$', mod.op(mru.group(1)))
            if abs((mod.const.get(mrs.group(2)) or -1) - f32(o.a0)) > 1e-6:
                bad.append((mod.name, s['gate'], 'a0 constant wrong'))
                continue
            alpha, fold = mrs.group(1), w['factors'][2]
            # --- numeric ---------------------------------------------------
            for (nh, x0, x1, al) in GRID:
                # `fold` is the SITE'S OWN light cosine, so at 401 of the 457
                # sites it is literally c0 or c1 -- bind it with setdefault
                # and read every leaf back out, or the harness would test a
                # closed form the shader was never asked to compute.
                bind = {}
                for key, val in ((noh, nh), (c0, x0), (c1, x1), (alpha, al)):
                    bind.setdefault(key, val)
                bind.setdefault(fold, 0.5)
                bind.setdefault(s['base'], 3.0)
                nh, x0, x1, al = bind[noh], bind[c0], bind[c1], bind[alpha]
                fo, ba = bind[fold], bind[s['base']]
                for g in (True, False):
                    gates = {s['gate']: g, s['nsnh']: g}
                    memo = {}
                    try:
                        got = ev(mod, s['add'], bind, gates, memo)
                    except KeyError as e:
                        bad.append((mod.name, s['gate'], f'eval: {e}'))
                        break
                    npt += 1
                    if not g:
                        if got != ba:
                            bad.append((mod.name, s['gate'],
                                        f'gate FALSE is not identity: {got!r}'))
                        continue
                    _, _, _, want = closed(nh, x0, x1, al, o.k, o.a, o.cap,
                                           o.a0, rspan)
                    want = f32(want * fo)
                    if abs(got - ba - want) > max(o.tol, o.tol * abs(want)):
                        bad.append((mod.name, s['gate'],
                                    f'at ({nh},{x0},{x1},{al}): emitted '
                                    f'{got - ba:.8g} vs closed {want:.8g}'))
            nsite += 1
        if len(shifts) > 1:
            bad.append((mod.name, '-', f'{len(shifts)} distinct class words gate the lobe'))
        for ds in damp_sites(mod, dampk):
            for al in (0.04, 0.16, 0.36, 0.81):
                r = math.sqrt(al)
                bind = {ds['fd']: 7.0}
                # bind the roughness leaf: wr = clamp((r*r - a0)*rspan)
                mr = re.match(r'OpExtInst %float %[\w$]+ NClamp (%[\w$]+) '
                              r'(%[\w$]+) (%[\w$]+)$', mod.op(ds['wr']))
                mu = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(mr.group(1)))
                msu = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)$', mod.op(mu.group(1)))
                msq = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)$', mod.op(msu.group(1)))
                if not msq or msq.group(1) != msq.group(2):
                    bad.append((mod.name, ds['fac'], 'damp ramp is not rough*rough'))
                    break
                bind[msq.group(1)] = r
                for g in (True, False):
                    memo = {}
                    got = ev(mod, ds['out'], bind, {ds['sel']: g}, memo)
                    npt += 1
                    if not g:
                        if got != 7.0:
                            bad.append((mod.name, ds['fac'],
                                        f'damp gate FALSE not identity: {got!r}'))
                        continue
                    wr = f32(min(max(f32(f32(f32(r * r) - o.a0) * rspan), 0.0), 1.0))
                    want = f32(7.0 * f32(1.0 - f32(wr * dampk)))
                    if abs(got - want) > 1e-6:
                        bad.append((mod.name, ds['fac'],
                                    f'damp at alpha {al}: {got!r} vs {want!r}'))
            nfd += 1

    print(f"rung {os.path.basename(d)}: {len(spvs)} compute modules")
    print(f"  cloth sites found and executed : {nsite}  (want {o.sites})")
    print(f"  diffuse damp chains            : {nfd}  (want {o.fd})")
    print(f"  points evaluated               : {npt}")
    print(f"  constants checked per site     : k_cloth={o.k} a_cloth={o.a} "
          f"cap={o.cap} f0max={o.f0max} a0={o.a0} 1/(a1-a0)={rspan:.6g} "
          f"damp_k={dampk:.6g}")
    if nsite != o.sites:
        bad.append(('coverage', '-', f'{nsite} cloth sites, want {o.sites}'))
    if nfd != o.fd:
        bad.append(('coverage', '-', f'{nfd} damp chains, want {o.fd}'))
    if bad:
        for b in bad[:15]:
            print("  FAIL %s %s :: %s" % b)
        print(f"  {len(bad)} failure(s)")
        sys.exit(1)
    print("  ALL CHECKS PASS")


if __name__ == '__main__':
    main()
