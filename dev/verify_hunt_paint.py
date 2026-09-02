#!/usr/bin/env python3
"""Verify a SHIPPED hunt-paint rung from its bytes (handoff/94 sec 10).

Takes a rung directory (93 .spv), disassembles every compute module and
re-derives, from the disassembly alone, that:

  1. the selection is complete: 77 compute + 16 raygen modules;
  2. exactly 76 compute modules carry paint and the 77th is the named,
     expected decline (its only image write is an integer buffer);
  3. the painted-write count matches the census (151);
  4. at EVERY painted write the texel RGB is `orig * select-chain` and the
     chain is rooted at 1.0 -- so an unpainted pixel is bit-exact vanilla;
  5. the chain's gates are the real thing:
       * a CLASS read: OpIEqual against a `>> 5` of the material G-buffer,
         for classes 0, 1, 3, 4 and 5, with the class-1 (skin) tint present
         -- the on-screen control;
       * a METALLIC x ROUGHNESS gate: OpFOrdLessThan on component 0 and on
         the clamped component 1 (NMin(NMax(.y, 0.04), 1)) of a v4float
         G-buffer fetch, in six mutually exclusive buckets under class 0;
       * an unknown-class catch-all (OpLogicalNot of the OR of the five
         known class compares);
  6. the tint triples are exactly the documented legend, and every module
     agrees on the five threshold constants.

It is NOT vacuous: build_hunt_paint.sh proves it rejects (a) the unpatched
base, (b) the gain-0 control, and (c) a --no-buckets build that carries the
class gate but no metallic/roughness gate at all.

    python3 dev/verify_hunt_paint.py <rung-dir> [--census-writes 151]
"""
import argparse, glob, os, re, struct, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_hunt_paint as HP

FAIL = []


def f32(x):
    """Round to the float32 the assembler actually stored."""
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def f32t(rgb):
    return tuple(f32(x) for x in rgb)


def bad(m, why):
    FAIL.append((m, why))


class Asm:
    def __init__(self, text):
        self.lines = text.split('\n')
        self.defs = {}
        for ln in self.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', ln)
            if m:
                self.defs.setdefault(m.group(1), m.group(2))
        self.fconst = {}
        self.uconst = {}
        for i, d in self.defs.items():
            m = re.match(r'OpConstant %float (\S+)$', d)
            if m:
                v = m.group(1)
                self.fconst[i] = f32(float.fromhex(v) if v.startswith('0x')
                                     else float(v))
            m = re.match(r'OpConstant %uint (\d+)$', d)
            if m:
                self.uconst[i] = int(m.group(1))

    def d(self, i):
        return self.defs.get(i, '')


def chain(a, head, one_ids):
    """Unwind an OpSelect chain rooted at 1.0; returns [(gate, rgb_id), ...]."""
    out = []
    cur = head
    seen = 0
    while cur not in one_ids:
        m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', a.d(cur))
        if not m:
            return None
        g, t, prev = m.groups()
        out.append((g, t))
        cur = prev
        seen += 1
        if seen > 64:
            return None
    out.reverse()
    return out


def leaves(a, gate, acc, depth=0):
    """Flatten LogicalAnd/Or/Not down to the comparison instructions."""
    if depth > 24:
        return
    d = a.d(gate)
    m = re.match(r'OpLogical(?:And|Or) %bool (%\w+) (%\w+)$', d)
    if m:
        leaves(a, m.group(1), acc, depth + 1)
        leaves(a, m.group(2), acc, depth + 1)
        return
    m = re.match(r'OpLogicalNot %bool (%\w+)$', d)
    if m:
        acc.append(('not', m.group(1)))
        leaves(a, m.group(1), acc, depth + 1)
        return
    acc.append((d, gate))


def class_value(a, cid):
    """True if `cid` is a material class: `<gbuf word> >> 5`."""
    m = re.match(r'OpShiftRightLogical %uint (%\w+) (%\w+)$', a.d(cid))
    if not m or a.uconst.get(m.group(2)) != 5:
        return False
    ex = a.d(m.group(1))
    me = re.match(r'OpCompositeExtract %uint (%\w+) 1$', ex)
    if not me:
        return False
    return bool(re.match(r'OpImageFetch %v4uint ', a.d(me.group(1))))


def mr_roles(a):
    """metallic ids and roughness ids reachable in this module."""
    met, rough = set(), set()
    for i, d in a.defs.items():
        m = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$', d)
        if not m:
            continue
        if abs(a.fconst.get(m.group(2), 0.0) - 0.0399999991) > 1e-9:
            continue
        me = re.match(r'OpCompositeExtract %float (%\w+) 1$', a.d(m.group(1)))
        if not me or not re.match(r'OpImageFetch %v4float ', a.d(me.group(1))):
            continue
        fetch = me.group(1)
        rough.add(i)
        for j, dj in a.defs.items():
            mj = re.match(r'OpExtInst %float %\w+ NMin (%\w+) (%\w+)$', dj)
            if mj and mj.group(1) == i and a.fconst.get(mj.group(2)) == 1.0:
                rough.add(j)
            mx = re.match(r'OpCompositeExtract %float ' + re.escape(fetch) + r' 0$', dj)
            if mx:
                met.add(j)
    return met, rough


def verify_module(name, text, totals):
    a = Asm(text)
    one_ids = {i for i, v in a.fconst.items() if v == 1.0}
    met_ids, rough_ids = mr_roles(a)
    painted = 0
    seen_thresh = set()
    for i, ln in enumerate(a.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        texel = m.group(3)
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)$',
                      a.d(texel))
        if not mc:
            totals['int_writes'] += 1
            continue
        chans = []
        for ch in range(3):
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', a.d(mc.group(ch + 1)))
            if not mm:
                chans = None
                break
            c = chain(a, mm.group(2), one_ids)
            if c is None:
                chans = None
                break
            chans.append(c)
        if chans is None:
            totals['unpainted_writes'] += 1
            continue
        if len({len(c) for c in chans}) != 1:
            bad(name, 'the three channels have different select-chain lengths')
            continue
        gates = [c[0] for c in chans[0]]
        for c in chans:
            if [g for g, _ in c] != gates:
                bad(name, 'the three channels do not share their gates')
        triples = [tuple(a.fconst.get(c[k][1]) for c in chans)
                   for k in range(len(gates))]
        # --- classify each gate ---
        cls_seen, bucket_gates, unknown = {}, [], 0
        for g, tri in zip(gates, triples):
            d = a.d(g)
            mi = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', d)
            if mi and class_value(a, mi.group(1)):
                cls_seen[a.uconst.get(mi.group(2))] = tri
                continue
            acc = []
            leaves(a, g, acc)
            kinds = [x[0] for x in acc]
            if any(k.startswith('OpFOrdLessThan') for k in kinds):
                bucket_gates.append((g, tri, acc))
                continue
            if d.startswith('OpLogicalNot') and all(
                    re.match(r'OpIEqual %bool ', k) or k.startswith(('OpLogical', 'not'))
                    for k in kinds):
                unknown += 1
                continue
            bad(name, 'unclassifiable gate %s (%s)' % (g, d[:48]))
        for n, (_nm, rgb) in HP.CLASS_TINT.items():
            if n not in cls_seen:
                bad(name, 'no class-%d gate at write line %d' % (n, i + 1))
            elif cls_seen[n] != f32t(rgb):
                bad(name, 'class-%d tint is %s, legend says %s'
                    % (n, cls_seen[n], f32t(rgb)))
        if 1 not in cls_seen:
            bad(name, 'the SKIN control gate is missing')
        if unknown != 1:
            bad(name, 'expected one unknown-class catch-all, found %d' % unknown)
        if len(bucket_gates) != len(HP.BUCKETS):
            bad(name, '%d metallic/roughness buckets, want %d'
                % (len(bucket_gates), len(HP.BUCKETS)))
        want = {f32t(rgb) for _k, _n, rgb in HP.BUCKETS}
        got = {tri for _g, tri, _acc in bucket_gates}
        if got != want:
            bad(name, 'bucket tints %s != legend %s' % (sorted(got), sorted(want)))
        used_m = used_r = 0
        for _g, _tri, acc in bucket_gates:
            zero_cls = False
            for kind, gid in acc:
                ml = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)$', kind)
                if ml:
                    if ml.group(1) in met_ids:
                        used_m += 1
                    elif ml.group(1) in rough_ids:
                        used_r += 1
                    else:
                        bad(name, 'bucket compares %s, which is neither metallic '
                                  'nor roughness' % ml.group(1))
                    if ml.group(2) in a.fconst:
                        seen_thresh.add(a.fconst[ml.group(2)])
                    continue
                mi2 = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', kind)
                if mi2 and class_value(a, mi2.group(1)) and a.uconst.get(mi2.group(2)) == 0:
                    zero_cls = True
            if not zero_cls:
                bad(name, 'a metallic/roughness bucket is not gated on class 0')
        if not used_m:
            bad(name, 'no bucket reads METALLIC')
        if not used_r:
            bad(name, 'no bucket reads ROUGHNESS')
        painted += 1
    totals['writes'] += painted
    if painted:
        totals['modules'] += 1
        totals['thresh'].add(tuple(sorted(seen_thresh)))
    return painted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--census-writes', type=int, default=HP.CENSUS['writes'])
    ap.add_argument('--census-modules', type=int, default=HP.CENSUS['painted_modules'])
    a = ap.parse_args()
    comp = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    rgs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_*.spv')))
    print('%s: %d compute + %d raygen modules' % (a.rung, len(comp), len(rgs)))
    if len(comp) != HP.CENSUS['modules']:
        bad('selection', '%d compute modules, want %d' % (len(comp), HP.CENSUS['modules']))
    if len(rgs) != 16:
        bad('selection', '%d raygen modules, want 16' % len(rgs))
    totals = dict(modules=0, writes=0, int_writes=0, unpainted_writes=0, thresh=set())
    silent = []
    for f in comp:
        n = os.path.basename(f)[:-len('.dxil.spv')]
        r = subprocess.run(['spirv-dis', f], capture_output=True, text=True)
        if r.returncode != 0:
            bad(n, 'spirv-dis failed')
            continue
        if verify_module(n, r.stdout, totals) == 0:
            silent.append(n)
    print('  painted: %d modules, %d writes; %d integer writes, %d unpainted '
          'float writes' % (totals['modules'], totals['writes'],
                            totals['int_writes'], totals['unpainted_writes']))
    if set(silent) != HP.KNOWN_DECLINE:
        show = sorted(set(silent) ^ HP.KNOWN_DECLINE)
        bad('coverage', '%d module(s) disagree with the expected decline list '
            '%s: %s%s' % (len(show), sorted(HP.KNOWN_DECLINE), show[:6],
                          ' ...' if len(show) > 6 else ''))
    if totals['modules'] != a.census_modules:
        bad('coverage', '%d painted modules, census says %d'
            % (totals['modules'], a.census_modules))
    if totals['writes'] != a.census_writes:
        bad('coverage', '%d painted writes, census says %d'
            % (totals['writes'], a.census_writes))
    if totals['unpainted_writes']:
        bad('coverage', '%d float image writes carry no paint'
            % totals['unpainted_writes'])
    want_t = tuple(sorted({f32(v) for v in HP.THRESH.values()}))
    if (len(totals['thresh']) == 1 and sorted(totals['thresh'])[0]
            and sorted(totals['thresh'])[0] != want_t):
        print('  note: thresholds differ from the defaults %s' % (want_t,))
    if len(totals['thresh']) != 1:
        bad('knobs', 'modules disagree on the thresholds: %s' % sorted(totals['thresh']))
    else:
        print('  thresholds in the shipped bytes: %s'
              % (sorted(totals['thresh'])[0],))
    if FAIL:
        print('FAIL:')
        for m, why in FAIL[:20]:
            print('  %s :: %s' % (m, why))
        if len(FAIL) > 20:
            print('  ... and %d more' % (len(FAIL) - 20))
        sys.exit(1)
    print('  OK -- class gate + metallic/roughness gate present at all '
          '%d writes, legend matches' % totals['writes'])


if __name__ == '__main__':
    main()
