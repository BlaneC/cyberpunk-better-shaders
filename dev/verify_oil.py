#!/usr/bin/env python3
"""Re-derive an oilhi rung's claims from the SHIPPED BYTES alone.

handoff/118 sec 5.  Takes the base (the shipped default) and a rung, both as
directories of .spv, disassembles them itself, and refuses to trust anything
the patcher said.  Checks, per rung:

  1. every module still matches the 72 coat's chain, and the group census is
     IDENTICAL to the base's -- module for module, not just in total.  A patch
     that broke or created a group fails here.
  2. every group in the rung carries exactly the DECLARED (P, G, C), and every
     group agrees with every other -- one coat per build, no stragglers.
  3. the base's own groups carry (4.5, 1.0, 1.1), so the deltas mean what the
     rung says they mean.
  4. the function-body OPCODE MULTISET is bit-identical to the base's, module
     for module.  This is the no-op proof: an operand rewrite cannot change
     which instructions exist, and this catches an insertion, a deletion or a
     changed opcode without depending on ids (spirv-as renumbers).
  5. the module declares at most 2 more float constants than the base.
  6. and the rung differs from the base in the modules it should: 0 for the
     control, all 77 for a rung that moves a constant every module carries.

Every check runs on every rung whether or not the rung declares the knob, so
"read a rung as another rung" fails instead of passing vacuously.
"""
import argparse, collections, glob, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_oil as PO
import brdf_sites as BS
import oil_model as OM

DEF = re.compile(r'^\s*(%\w+) = (Op\w+)')
CONST = re.compile(r'^\s*%\w+ = OpConstant %float ')


def dis(path):
    r = subprocess.run(['spirv-dis', '--no-color', path],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('spirv-dis failed on %s:\n%s' % (path, r.stderr))
    return r.stdout


class M:
    """the minimum of Module that find_oil_groups touches"""
    def __init__(self, name, src):
        self.name = name
        self.lines = src.splitlines()

    def find_def(self, idtok):
        pat = re.compile(r'^\s*' + re.escape(idtok) + r'\s*=\s*(.*)$')
        for i, ln in enumerate(self.lines):
            m = pat.match(ln)
            if m:
                return i, m.group(1)
        return None, None


def fval(D, mod, idtok):
    d = D.get(idtok)
    t = d['text'] if d else ('%s = %s' % (idtok, mod.find_def(idtok)[1] or ''))
    if 'OpConstant %float' not in t:
        return None
    return float(t.split('OpConstant %float')[1].strip())


def opcodes(mod):
    """multiset of opcodes in the function bodies (constants excluded)."""
    c = collections.Counter()
    body = False
    for ln in mod.lines:
        if ' OpFunction ' in ln:
            body = True
        if not body:
            continue
        m = DEF.match(ln)
        if m and not CONST.match(ln):
            c[m.group(2)] += 1
        elif not m:
            s = ln.strip().split(' ')[0]
            if s.startswith('Op'):
                c[s] += 1
    return c


def nconst(mod):
    return sum(1 for ln in mod.lines if CONST.match(ln))


def scan(path):
    mod = M(os.path.basename(path), dis(path))
    groups, declined, D = PO.find_oil_groups(mod)
    vals = [(fval(D, mod, g['P']), fval(D, mod, g['G']), fval(D, mod, g['C']))
            for g in groups]
    return mod, groups, vals


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rung', help='directory of the rung .spv')
    ap.add_argument('--base', required=True, help='directory of the base .spv')
    ap.add_argument('-p', type=float, required=True, help='declared exponent')
    ap.add_argument('-g', type=float, required=True, help='declared gain')
    ap.add_argument('--c2mr', type=float, default=1.10000002,
                    help='declared 2-r (the inert constant)')
    ap.add_argument('--expect-differing', type=int, default=None,
                    help='how many modules must differ from the base by bytes')
    a = ap.parse_args()

    bad, tot_g, tot_c, differing = [], 0, 0, 0
    files = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    if not files:
        raise SystemExit('no *.dxil.spv in %s' % a.rung)
    for f in files:
        n = os.path.basename(f)
        bf = os.path.join(a.base, n)
        if not os.path.exists(bf):
            bad.append('%s: not in the base' % n)
            continue
        bmod, bg, bv = scan(bf)
        rmod, rg, rv = scan(f)
        # 1. census identical, module for module
        if len(bg) != len(rg):
            bad.append('%s: %d groups, base has %d' % (n, len(rg), len(bg)))
            continue
        if not rg:
            bad.append('%s: no 72 coat found at all' % n)
            continue
        tot_g += len(rg)
        tot_c += sum(len(g['chans']) for g in rg)
        # 3. the base is the build this rung claims to be built on
        for (p0, g0, c0) in bv:
            if p0 is None or abs(p0 - OM.P_SHIP) > 1e-5 or \
               abs(g0 - OM.G_SHIP) > 1e-5 or abs(c0 - 1.10000002) > 1e-5:
                bad.append('%s: base coat is %r, not the shipped (4.5,1.0,1.1)'
                           % (n, (p0, g0, c0)))
                break
        # 2. every group carries the DECLARED values, and they all agree
        for (p1, g1, c1) in rv:
            if p1 is None or abs(p1 - a.p) > 1e-5:
                bad.append('%s: exponent %r, declared %r' % (n, p1, a.p))
                break
            if g1 is None or abs(g1 - a.g) > 1e-5:
                bad.append('%s: gain %r, declared %r' % (n, g1, a.g))
                break
            if c1 is None or abs(c1 - a.c2mr) > 1e-5:
                bad.append('%s: 2-r %r, declared %r' % (n, c1, a.c2mr))
                break
        if len(set(rv)) != 1:
            bad.append('%s: %d different coats in one module' % (n, len(set(rv))))
        # 4. the no-op proof
        ob, orr = opcodes(bmod), opcodes(rmod)
        if ob != orr:
            d = {k: (ob.get(k, 0), orr.get(k, 0))
                 for k in set(ob) | set(orr) if ob.get(k) != orr.get(k)}
            bad.append('%s: opcode multiset moved: %r' % (n, d))
        # 5. at most two new float constants
        dc = nconst(rmod) - nconst(bmod)
        if not 0 <= dc <= 2:
            bad.append('%s: %+d float constants' % (n, dc))
        # 6.
        if open(f, 'rb').read() != open(bf, 'rb').read():
            differing += 1

    if a.expect_differing is not None and differing != a.expect_differing:
        bad.append('%d modules differ from the base, expected %d'
                   % (differing, a.expect_differing))
    print('  modules %d  groups %d  channels %d  differing-from-base %d'
          % (len(files), tot_g, tot_c, differing))
    print('  declared: exponent %.4f  gain %.4f  2-r %.4f' % (a.p, a.g, a.c2mr))
    for b in bad[:20]:
        print('  FAIL %s' % b)
    if bad:
        print('  %d failures' % len(bad))
        return 1
    print('  OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
