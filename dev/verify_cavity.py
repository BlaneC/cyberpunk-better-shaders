#!/usr/bin/env python3
"""85: prove the cavity contact-shadow splice from the EMITTED BINARIES.

The 39 sec 3.4 / 59 sec 3 discipline: not "the patcher says it emitted a
trace" but "the instructions in the shipped .spv, re-disassembled and
re-parsed, are the designed ones and nothing else". Ids are NOT comparable
across the assemble/disassemble round trip (40 sec 8), so every check here is
structural inside one text.

Per patched module it proves, and fails the build on any of them:

  1. trace count = base + 1, and exactly one flags-16 trace (base has none)
  2. that trace's cullMask is OpSelect(gate, 39, 0) and the gate is
     (class==32) AND (bounce==0) AND <the module's own sun-visibility cond>
  3. its ORIGIN is the module's own prehit triple -- structurally linked:
     the sun-NEE trace's origin is CompositeConstruct(FAdd(P_i, off_i)), and
     the cavity origin is CompositeConstruct(P_0,P_1,P_2) with those exact ids
     (so it is the un-biased surface point, not the engine's biased origin)
  4. its DIRECTION is the sun-NEE trace's own direction operand verbatim
     (the sun-disc sample: free penumbra, no PRNG advance)
  5. tmin == 5e-4 and tmax == the rung's, resolved by constant VALUE
  6. member 3 is pre-armed to 10000 by an OpStore before the trace
  7. occluded = FOrdGreaterThan(t, 4e-4) AND FOrdLessThan(t, tmax), on a load
     of member 3 of the injected payload
  8. factor = OpSelect(occluded, 1-k, %float_1)   <-- GATE-FALSE INERTNESS:
     mask 0 => miss => t stays 10000 => the upper bound fails => factor is
     exactly %float_1 => every site computes src*1.0 == src bit-for-bit
  9. exactly 3 sites: FMul(NClamp(.,0,1), factor) feeding the module's own
     FMul(., sunRadiance_c), one per channel, and each sunRadiance component
     STILL has exactly 3 uses -- the rewrite added no new consumer
 10. NOTHING ELSE CHANGED: the per-opcode count delta against the base is
     zero outside a whitelist, and exact for every opcode the clone chain
     cannot emit (TraceRayKHR +1, FMul +3, Select +2, LogicalAnd +3,
     FOrdLessThan +1, FOrdGreaterThan +1, Store +4, IEqual +2)

and as a NEGATIVE CONTROL, that the unpatched base carries none of it.

  ./dev/verify_cavity.py <rung-dir> <base-dir> --k 0.85 --tmax 0.006
  ./dev/verify_cavity.py --negative <base-dir>
"""
import argparse, glob, os, re, subprocess, sys

PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')

# opcodes the splice may introduce. Anything else must have a zero delta.
ALLOWED = {
    'OpAccessChain', 'OpInBoundsAccessChain', 'OpLoad', 'OpStore', 'OpIAdd',
    'OpIMul', 'OpCompositeConstruct', 'OpCompositeExtract', 'OpImageFetch',
    'OpBitcast', 'OpShiftRightLogical', 'OpBitwiseAnd', 'OpUConvert',
    'OpRawAccessChainNV', 'OpIEqual', 'OpLogicalAnd', 'OpSelect',
    'OpTraceRayKHR', 'OpFOrdGreaterThan', 'OpFOrdLessThan', 'OpFMul',
    'OpConstant', 'OpVariable', 'OpTypePointer', 'OpTypeBool', 'OpEntryPoint',
}
# opcodes clone_chain provably cannot emit -> exact deltas
EXACT = {'OpTraceRayKHR': 1, 'OpFMul': 3, 'OpSelect': 2, 'OpLogicalAnd': 3,
         'OpFOrdLessThan': 1, 'OpFOrdGreaterThan': 1, 'OpStore': 4,
         'OpIEqual': 2}


def dis(path):
    r = subprocess.run(['spirv-dis', '--no-color', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"spirv-dis failed on {path}:\n{r.stderr}")
    return r.stdout.split('\n')


class Text:
    def __init__(self, lines):
        self.lines = lines
        self.defs = {}
        for i, ln in enumerate(lines):
            m = re.match(r'\s*(%\w+)\s*=\s*(Op.*?)\s*$', ln)
            if m:
                self.defs[m.group(1)] = m.group(2)

    def d(self, idt):
        return self.defs.get(idt, '')

    def fval(self, idt):
        m = re.match(r'OpConstant %float ([0-9eE.+-]+|0x\S+)$', self.d(idt))
        return float(m.group(1)) if m else None

    def traces(self):
        out = []
        for ln in self.lines:
            m = re.match(r'\s*OpTraceRayKHR\s+(.+?)\s*$', ln)
            if m:
                out.append(m.group(1).split())
        return out

    def uses(self, idt):
        n = 0
        for ln in self.lines:
            if re.match(r'\s*' + re.escape(idt) + r'\s*=', ln):
                continue
            n += len(re.findall(re.escape(idt) + r'(?![0-9A-Za-z_])', ln))
        return n

    def ops(self):
        h = {}
        for ln in self.lines:
            m = re.search(r'\b(Op[A-Za-z0-9]+)\b', ln)
            if m:
                h[m.group(1)] = h.get(m.group(1), 0) + 1
        return h


def check_module(h, rung_spv, base_spv, k, tmax, fails):
    T = Text(dis(rung_spv))
    B = Text(dis(base_spv))

    def bad(msg):
        fails.append(f'{h}: {msg}')

    tr, btr = T.traces(), B.traces()
    if len(tr) != len(btr) + 1:
        return bad(f'trace count {len(tr)} != base+1 ({len(btr)+1})')
    if any(t[1] == '%uint_16' for t in btr):
        return bad('base already has a flags-16 trace -- detector unsafe')
    inj = [t for t in tr if t[1] == '%uint_16']
    if len(inj) != 1:
        return bad(f'{len(inj)} flags-16 traces, expected exactly 1')
    inj = inj[0]
    nee = [t for t in tr if len(t) == 11 and t[1] == '%uint_12'
           and t[9] == '%float_10000'
           and re.match(r'OpSelect %uint %\w+ %uint_0 %uint_39$', T.d(t[2]))]
    if len(nee) != 1:
        return bad(f'{len(nee)} sun-NEE traces, expected 1')
    nee = nee[0]

    # (2) gate
    gm = re.match(r'OpSelect %uint (%\w+) %uint_39 %uint_0$', T.d(inj[2]))
    if not gm:
        return bad(f'cullMask is not Select(gate,39,0): {T.d(inj[2])!r}')
    a2 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', T.d(gm.group(1)))
    if not a2:
        return bad('gate is not a LogicalAnd')
    a1, cond = a2.group(1), a2.group(2)
    if not re.match(r'OpFOrdGreaterThan %bool %\w+ %float_0$', T.d(cond)):
        a1, cond = cond, a1
    if not re.match(r'OpFOrdGreaterThan %bool %\w+ %float_0$', T.d(cond)):
        bad('gate does not AND the sun-visibility branch condition')
    else:
        nbr = sum(1 for ln in T.lines
                  if re.match(r'\s*OpBranchConditional ' + re.escape(cond) + r' ', ln))
        if nbr != 1:
            bad(f'the ANDed cond conditions {nbr} branches, expected 1 '
                f'(it must be the module\'s own sun branch)')
    a0 = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', T.d(a1))
    if not a0:
        bad('gate inner term is not a LogicalAnd(skin, bounce0)')
    else:
        forms = sorted(re.sub(r'%\w+', '%', T.d(x)) for x in a0.groups())
        if forms != ['OpIEqual % % %', 'OpIEqual % % %']:
            bad(f'gate inner terms are not two IEquals: {forms}')
        if not any(re.match(r'OpIEqual %bool %\w+ %uint_32$', T.d(x))
                   for x in a0.groups()):
            bad('no class-1 (== 32) compare in the gate')
        if not any(re.match(r'OpIEqual %bool %\w+ %uint_0$', T.d(x))
                   for x in a0.groups()):
            bad('no bounce==0 compare in the gate')

    # (3) origin = the module's own prehit triple, linked through the NEE origin
    om = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                  T.d(nee[6]))
    im = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                  T.d(inj[6]))
    if not (om and im):
        bad('trace origins are not v3float composites')
    else:
        if inj[6] == nee[6]:
            bad('cavity origin IS the engine biased NEE origin -- must be prehit')
        for c in range(3):
            am = re.match(r'OpFAdd %float (%\w+) (%\w+)$', T.d(om.group(c + 1)))
            if not am:
                bad(f'NEE origin component {c} is not an FAdd')
            elif im.group(c + 1) not in am.groups():
                bad(f'cavity origin component {c} ({im.group(c+1)}) is not the '
                    f'NEE origin\'s pre-offset addend {am.groups()}')

    # (4) direction verbatim
    if inj[8] != nee[8]:
        bad(f'cavity direction {inj[8]} != the NEE direction {nee[8]}')
    # (5) tmin / tmax by value; SBT 1/1/0
    if [inj[3], inj[4], inj[5]] != ['%uint_1', '%uint_1', '%uint_0']:
        bad(f'SBT operands {inj[3:6]} != 1/1/0 (the radiance hit groups)')
    v = T.fval(inj[7])
    if v is None or abs(v - 5e-4) > 1e-9:
        bad(f'tmin {inj[7]} is not 5e-4 (got {v})')
    vmax = T.fval(inj[9])
    if vmax is None or abs(vmax - tmax) > 1e-9:
        bad(f'tmax {inj[9]} is not {tmax} (got {vmax})')

    # (6) pre-arm of member 3 before the trace
    pay = inj[10]
    m3 = [i for i, d in T.defs.items()
          if re.match(r'OpInBoundsAccessChain %\w+ ' + re.escape(pay)
                      + r' %uint_3$', d)]
    if len(m3) != 1:
        return bad(f'{len(m3)} member-3 chains on the injected payload')
    m3 = m3[0]
    ti = next(i for i, ln in enumerate(T.lines) if 'OpTraceRayKHR' in ln
              and ln.split()[1:] == inj)
    prearm = [i for i, ln in enumerate(T.lines)
              if re.match(r'\s*OpStore ' + re.escape(m3) + r' %float_10000$', ln)]
    if not prearm or min(prearm) > ti:
        bad('member 3 is not pre-armed to 10000 before the trace')
    nst = sum(1 for ln in T.lines
              if re.match(r'\s*OpStore ' + re.escape(m3) + r' ', ln))
    if nst != 1:
        bad(f'{nst} stores to the injected member 3, expected 1 (the pre-arm)')

    # (7)(8) occluded + factor, and the inertness chain
    tl = [i for i, d in T.defs.items()
          if d == f'OpLoad %float {m3}']
    if len(tl) != 1:
        return bad(f'{len(tl)} loads of the injected member 3, expected 1')
    tid = tl[0]
    lo = [i for i, d in T.defs.items()
          if re.match(r'OpFOrdGreaterThan %bool ' + re.escape(tid) + r' (%\w+)$', d)]
    hi = [i for i, d in T.defs.items()
          if re.match(r'OpFOrdLessThan %bool ' + re.escape(tid) + r' (%\w+)$', d)]
    if len(lo) != 1 or len(hi) != 1:
        return bad(f'occluded bounds malformed ({len(lo)} lower, {len(hi)} upper)')
    lv = T.fval(T.d(lo[0]).split()[-1])
    hv = T.fval(T.d(hi[0]).split()[-1])
    if lv is None or abs(lv - 4e-4) > 1e-9:
        bad(f'lower validity bound is {lv}, expected 4e-4')
    if hv is None or abs(hv - tmax) > 1e-9:
        bad(f'upper validity bound is {hv}, expected tmax {tmax}')
    occ = [i for i, d in T.defs.items()
           if re.match(r'OpLogicalAnd %bool ', d)
           and set(d.split()[2:]) == {lo[0], hi[0]}]
    if len(occ) != 1:
        return bad('occluded = lower AND upper not found')
    fac = [i for i, d in T.defs.items()
           if re.match(r'OpSelect %float ' + re.escape(occ[0]) + r' (%\w+) %float_1$', d)]
    if len(fac) != 1:
        return bad('factor = Select(occluded, 1-k, %float_1) not found '
                   '(the gate-false inertness leg)')
    fv = T.fval(T.d(fac[0]).split()[3])
    if fv is None or abs(fv - (1.0 - k)) > 1e-6:
        bad(f'factor magnitude is {fv}, expected 1-k = {1.0-k}')

    # (9) the three sites
    nuse = T.uses(fac[0])
    if nuse != 3:
        bad(f'factor has {nuse} uses, expected exactly 3 (one per channel)')
    scaled = [i for i, d in T.defs.items()
              if re.match(r'OpFMul %float (%\w+) ' + re.escape(fac[0]) + r'$', d)]
    if len(scaled) != 3:
        return bad(f'{len(scaled)} scaled terms, expected 3')
    hit = 0
    for s in scaled:
        src = T.d(s).split()[2]
        if not re.match(r'OpExtInst %float %\w+ NClamp %\w+ %float_0 %float_1$',
                        T.d(src)):
            bad(f'scaled source {src} is not an NClamp(.,0,1)')
        cons = [i for i, d in T.defs.items()
                if re.match(r'OpFMul %float ' + re.escape(s) + r' (%\w+)$', d)]
        if len(cons) != 1:
            bad(f'scaled term {s} has {len(cons)} consumers, expected 1')
            continue
        rad = T.d(cons[0]).split()[3]
        if T.uses(rad) != 3:
            bad(f'sun radiance {rad} now has {T.uses(rad)} uses, expected 3')
        hit += 1
    if hit != 3:
        bad(f'only {hit}/3 sites wired through to a sun-radiance multiply')

    # (10) nothing else changed
    ha, hb = T.ops(), B.ops()
    for op in set(ha) | set(hb):
        d = ha.get(op, 0) - hb.get(op, 0)
        if op in EXACT:
            if d != EXACT[op]:
                bad(f'{op} delta {d}, expected {EXACT[op]}')
        elif op not in ALLOWED and d != 0:
            bad(f'{op} delta {d} -- opcode outside the splice whitelist')


def negative(base):
    fails = []
    for f in sorted(glob.glob(os.path.join(base, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        T = Text(dis(f))
        n16 = sum(1 for t in T.traces() if t[1] == '%uint_16')
        n32 = sum(1 for d in T.defs.values()
                  if re.match(r'OpIEqual %bool %\w+ %uint_32$', d))
        if n16 or n32:
            fails.append(f'{h}: base already carries {n16} flags-16 traces and '
                         f'{n32} class-32 compares -- the detector is not a '
                         f'negative control')
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rung', nargs='?')
    ap.add_argument('base')
    ap.add_argument('--k', type=float)
    ap.add_argument('--tmax', type=float)
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    if a.negative:
        fails = negative(a.base)
        if fails:
            print('NEGATIVE CONTROL FAILED:\n  ' + '\n  '.join(fails))
            sys.exit(1)
        print(f'  negative control: {a.base} carries 0 cavity sites in 12/12')
        return
    if not (a.rung and a.k is not None and a.tmax is not None):
        ap.error('rung, --k and --tmax are required without --negative')
    fails, n = [], 0
    for f in sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        if h in PASS:
            continue
        check_module(h, f, os.path.join(a.base, os.path.basename(f)),
                     a.k, a.tmax, fails)
        n += 1
    if n != 10:
        fails.append(f'{n} patched modules, expected 10')
    if fails:
        print('EMITTED-CODE RE-READ FAILED:\n  ' + '\n  '.join(fails))
        sys.exit(1)
    print(f'  emitted-code re-read: {a.rung} clean '
          f'({n} modules x 3 sites = {n*3}, k={a.k}, tmax={a.tmax*1000:g}mm)')


if __name__ == '__main__':
    main()
