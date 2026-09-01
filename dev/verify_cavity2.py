#!/usr/bin/env python3
"""Re-derive handoff/88's cone from the SHIPPED binaries.

39 sec 3.4 discipline: disassemble the emitted .spv and prove the structure
again from scratch. Ids are not comparable across the assemble/disassemble
round trip (40 sec 8), so everything here is structural or by resolved
constant VALUE. The patcher's own bookkeeping is never trusted.

  dev/verify_cavity2.py <rung_dir> <base_dir> --k K --tmax M --taps N \
      --theta DEG [--ramp on|off]
  dev/verify_cavity2.py --negative <base_dir>      # base carries none of it
"""
import argparse, glob, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAIL = []


def bad(mod, msg):
    FAIL.append(f"{mod}: {msg}")


def dis(path):
    r = subprocess.run(['spirv-dis', '--no-color', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"spirv-dis failed on {path}:\n{r.stderr}")
    return r.stdout.split('\n')


def index(lines):
    d = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d[m.group(1)] = (i, m.group(2))
    return d


def fval(d, tok):
    """Resolved value of a float constant id."""
    if tok not in d:
        return None
    m = re.match(r'OpConstant %float ([-\d.e+]+)$', d[tok][1])
    return float(m.group(1)) if m else None


def uval(d, tok):
    if tok not in d:
        m = re.match(r'%uint_(\d+)$', tok)
        return int(m.group(1)) if m else None
    m = re.match(r'OpConstant %uint (\d+)$', d[tok][1])
    return int(m.group(1)) if m else None


def close(a, b, rel=2e-6):
    return a is not None and b is not None and abs(a - b) <= rel * max(1.0, abs(b))


TRACE = re.compile(r'\s*OpTraceRayKHR (%\w+) (\S+) (\S+) (\S+) (\S+) (\S+) '
                   r'(%\w+) (\S+) (%\w+) (\S+) (%\w+)\s*$')


def traces(lines):
    return [(i, TRACE.match(l).groups()) for i, l in enumerate(lines)
            if TRACE.match(l)]


def verify_module(name, lines, base_lines, k, tmax, taps, theta, ramp,
                  lights=1, k_local=None, gate_kind='bounce'):
    d, bd = index(lines), index(base_lines)
    tr, btr = traces(lines), traces(base_lines)

    if len(tr) != len(btr) + taps * lights:
        bad(name, f"{len(tr)} traces, base has {len(btr)}, expected "
                  f"+{taps * lights}")
        return

    ours = [(i, o) for i, o in tr if uval(d, o[1]) == 16]
    if len(ours) != taps * lights:
        bad(name, f"{len(ours)} flags-16 traces, expected {taps * lights}")
        return

    # One cone per light, each with its OWN cullMask select, so the grouping is
    # structural rather than positional. The sun's cone is the one whose gate
    # tests a bool the module branches on; it is also always the first.
    groups = {}
    for i, o in ours:
        groups.setdefault(o[2], []).append((i, o))
    if len(groups) != lights:
        bad(name, f"{len(groups)} distinct cullMasks over the flags-16 "
                  f"traces, expected {lights} (one per light)")
        return
    ordered = sorted(groups.values(), key=lambda g: g[0][0])
    for gi, g in enumerate(ordered):
        if len(g) != taps:
            bad(name, f"cone {gi} has {len(g)} taps, expected {taps}")
            return
    for gi, g in enumerate(ordered):
        kind = 'sun' if gi == 0 else 'local'
        verify_cone(name, lines, d, tr, g,
                    k if kind == 'sun' else (k if k_local is None else k_local),
                    tmax, taps, theta, ramp, lights, kind, gate_kind)



UNIT_ONE = ('%half_0x1p_0', '%float_1')


def path_counter(lines, d, name):
    """Re-derive the PATH loop's bounce counter from the shipped bytes, the
    same way 89 does and with no help from the patcher: among counted loops
    `LessThan(x + 1, bound)` on a back edge whose body traces rays, the path
    loop is the one seeding exactly 3 fp phis with 1.0 (the RGB throughput);
    its counter is the unique uint phi at that header whose incomings are
    exactly {0, that loop's own IAdd}. Returns (counter, all_loop_counters)."""
    labels = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', l)
        if m:
            labels[m.group(1)] = i
    hot, every = [], set()
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', l)
        if not m:
            continue
        cond, t0, t1 = m.groups()
        cm = re.match(r'Op[SU]LessThan %bool (%\w+) (%\w+)$',
                      d.get(cond, (0, ''))[1])
        if not cm:
            continue
        inc = cm.group(1)
        if not re.match(r'OpIAdd %uint %\w+ %uint_1$', d.get(inc, (0, ''))[1]):
            continue
        for tgt in (t0, t1):
            hi = labels.get(tgt)
            if hi is None or hi >= i:
                continue
            if not any('OpTraceRayKHR' in lines[j] for j in range(hi, i)):
                continue
            ones, uphis = 0, []
            for j in range(hi + 1, len(lines)):
                if not re.match(r'\s*\S+\s*=\s*OpPhi ', lines[j]):
                    break
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(?:half|float) (.+?)\s*$',
                              lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(1).split()[0::2]):
                    ones += 1
                um = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+?)\s*$',
                              lines[j])
                if um:
                    uphis.append((um.group(1), um.group(2).split()[0::2]))
            for pid, vals in uphis:
                if '%uint_0' in vals:
                    every.add(pid)
            if ones == 3:
                hot.append([pid for pid, vals in uphis
                            if set(vals) == {'%uint_0', inc}])
            elif ones:
                bad(name, f"non-path loop {tgt} seeds {ones} phis with 1.0")
    if len(hot) != 1 or len(hot[0]) != 1:
        bad(name, f"path-loop counter not unique: {hot}")
        return None, every
    return hot[0][0], every


def verify_cone(name, lines, d, tr, ours, k, tmax, taps, theta, ramp,
                lights, kind, gate_kind='bounce'):
    """Verify ONE cone -- the sun's, or one local light's.

    `k` is ALREADY the strength for this cone's kind: the caller passes k for
    the sun and k_local for a local light (88 sec 5c).

    Everything up to the factor is identical between them by construction, so
    it is checked by the same code; only the lit-condition's shape and the
    site rewrite differ, and both are switched on `kind` rather than skipped.
    """
    # --- every tap shares one cullMask, origin, payload, tmin, tmax --------
    masks = {o[2] for _, o in ours}
    origins = {o[6] for _, o in ours}
    pays = {o[10] for _, o in ours}
    if len(masks) != 1 or len(origins) != 1 or len(pays) != 1:
        bad(name, f"{kind} cone: taps disagree: {len(masks)} masks, "
                  f"{len(origins)} origins, {len(pays)} payloads")
        return
    for _, o in ours:
        if not close(fval(d, o[7]), 1e-4):
            bad(name, f"tmin {o[7]} != 1e-4")
        if not close(fval(d, o[9]), tmax):
            bad(name, f"tmax {o[7]} resolves to {fval(d, o[9])}, want {tmax}")
        if uval(d, o[3]) != 1 or uval(d, o[4]) != 1 or uval(d, o[5]) != 0:
            bad(name, "SBT offset/stride/miss is not 1/1/0")

    # --- the gate: Select(AND(AND(class==1, bounce==0), sun_cond), 39, 0) --
    mask = masks.pop()
    m = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', d.get(mask, (0, ''))[1])
    if not m:
        bad(name, f"cullMask {mask} is not an OpSelect")
        return
    gate = m.group(1)
    if uval(d, m.group(2)) != 39 or uval(d, m.group(3)) != 0:
        bad(name, f"cullMask select is not (39, 0)")
    a2 = re.match(r'OpLogicalAnd %\w+ (%\w+) (%\w+)$', d.get(gate, (0, ''))[1])
    if not a2:
        bad(name, "gate is not a LogicalAnd")
        return
    a1 = re.match(r'OpLogicalAnd %\w+ (%\w+) (%\w+)$',
                  d.get(a2.group(1), (0, ''))[1])
    if not a1:
        bad(name, "gate's first operand is not a LogicalAnd")
        return
    # The third conjunct is the ENGINE's own "this light already lit this
    # pixel" decision, so the term can only ever subtract. Its shape differs
    # by light kind and both are pinned:
    #   sun   -- the bool the module's own sun block branches on
    #   local -- FOrdEqual(payload member 3, 10000), i.e. the shadow ray MISSED
    lit = a2.group(2)
    if kind == 'sun':
        if not any(re.match(r'\s*OpBranchConditional ' + re.escape(lit) + r' ',
                            l) for l in lines):
            bad(name, f"sun condition {lit} drives no OpBranchConditional")
    else:
        em_ = re.match(r'OpFOrdEqual %\w+ (%\w+) (%\w+)$', d.get(lit, (0, ''))[1])
        if not em_ or not close(fval(d, em_.group(2)), 10000.0):
            bad(name, f"local lit-condition {lit} is not `t == 10000`")
        else:
            ld_ = re.match(r'OpLoad %float (%\w+)$',
                           d.get(em_.group(1), (0, ''))[1])
            if not ld_ or not re.match(r'OpInBoundsAccessChain %\w+ %\w+ (%\w+)$',
                                       d.get(ld_.group(1), (0, ''))[1]):
                bad(name, "local lit-condition does not read a payload member")

    # class == 1, over the slot-5 material word
    cls = None
    for cand in (a1.group(1), a1.group(2)):
        cm = re.match(r'OpIEqual %\w+ (%\w+) (%\w+)$', d.get(cand, (0, ''))[1])
        if cm and uval(d, cm.group(2)) == 1:
            cls = cm.group(1)
    if cls is None:
        bad(name, "no `class == 1` conjunct in the gate")
    else:
        sh = re.match(r'OpShiftRightLogical %uint (%\w+) (%\w+)$',
                      d.get(cls, (0, ''))[1])
        if not sh or uval(d, sh.group(2)) != 5:
            bad(name, f"class word {cls} is not `word >> 5`")
        else:
            ex = re.match(r'OpCompositeExtract %uint (%\w+) 1$',
                          d.get(sh.group(1), (0, ''))[1])
            fe = re.match(r'OpImageFetch %v4uint (%\w+) %\w+ Lod %uint_0$',
                          d.get(ex.group(1), (0, ''))[1]) if ex else None
            if not fe:
                bad(name, "class word does not come from a v4uint image fetch")
            else:
                ld = re.match(r'OpLoad %\w+ (%\w+)$',
                              d.get(fe.group(1), (0, ''))[1])
                ac = re.match(r'OpAccessChain %_ptr_UniformConstant_\w+ %\w+ '
                              r'(%\w+)$', d.get(ld.group(1), (0, ''))[1]) if ld else None
                ia = re.match(r'OpIAdd %uint %\w+ (%\w+)$',
                              d.get(ac.group(1), (0, ''))[1]) if ac else None
                if not ia or uval(d, ia.group(1)) != 5:
                    bad(name, "class fetch is not bindless slot [reg+5]")

    # bounce == 0 -- AND it must be the PATH loop's counter, not the sample
    # loop's. Pre-89 this check only asked for `<something> == 0`, which is
    # exactly how the sample counter got through in 5 of 12 permutations.
    want, every = path_counter(lines, d, name)
    zero_eq = None
    for c in (a1.group(1), a1.group(2)):
        cm = re.match(r'OpIEqual %\w+ (%\w+) (%\w+)$', d.get(c, (0, ''))[1])
        if cm and uval(d, cm.group(2)) == 0:
            zero_eq = cm.group(1)
    if zero_eq is None:
        bad(name, "no `<counter> == 0` conjunct in the gate")
    elif gate_kind == 'bounce':
        if want is not None and zero_eq != want:
            bad(name, f"the gate tests {zero_eq} == 0, but the PATH loop's "
                      f"bounce counter is {want} -- this is the 89 sec 2 bug")
    elif zero_eq not in every:
        bad(name, f"the gate tests {zero_eq} == 0, which is not any counted "
                  f"ray-loop's zero-seeded counter")

    # --- origin is the NEE trace's own PRE-OFFSET addend triple ------------
    if kind == 'sun':
        nee = [(i, o) for i, o in tr if uval(d, o[1]) == 12
               and close(fval(d, o[9]), 10000.0)]
    else:
        # this cone's own light: the nearest preceding flags-12 mask-39 trace
        nee = [(i, o) for i, o in tr
               if uval(d, o[1]) == 12 and uval(d, o[2]) == 39
               and i < ours[0][0]]
        nee = nee[-1:]
    if len(nee) != 1:
        bad(name, f"{kind} cone: {len(nee)} NEE traces found, expected 1")
    else:
        oc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(origins.copy().pop() if origins else '', (0, ''))[1]
                      if origins else '')
        origin = list(ours[0][1])[6]
        oc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(origin, (0, ''))[1])
        nc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$',
                      d.get(nee[0][1][6], (0, ''))[1])
        if not oc or not nc:
            bad(name, "origin or NEE origin is not a v3float construct")
        else:
            for ci in range(3):
                add = re.match(r'OpFAdd %float (%\w+) (%\w+)$',
                               d.get(nc.group(ci + 1), (0, ''))[1])
                if not add or oc.group(ci + 1) not in (add.group(1),
                                                       add.group(2)):
                    bad(name, f"origin component {ci} is not the NEE origin's "
                              f"pre-offset addend")

    # --- tap 0 is Normalize(NEE direction); the rest are its rotations -----
    if nee and len(nee) == 1:
        nm = re.match(r'OpExtInst %v3float %\w+ Normalize (%\w+)$',
                      d.get(ours[0][1][8], (0, ''))[1])
        if not nm or nm.group(1) != nee[0][1][8]:
            bad(name, "tap 0 is not Normalize(the module's own NEE direction)")

    import math
    ct, st = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    if taps > 1:
        # the horizon tap: FSub(L*cos, T*sin) -- possibly behind a gate select
        def unsel(t):
            s = re.match(r'OpSelect %v3float %\w+ (%\w+) %\w+$',
                         d.get(t, (0, ''))[1])
            return s.group(1) if s else t
        h = re.match(r'OpFSub %v3float (%\w+) (%\w+)$',
                     d.get(unsel(ours[1][1][8]), (0, ''))[1])
        if not h:
            bad(name, "tap 1 is not an FSub (the horizon tap)")
        else:
            a = re.match(r'OpVectorTimesScalar %v3float %\w+ (%\w+)$',
                         d.get(h.group(1), (0, ''))[1])
            b = re.match(r'OpVectorTimesScalar %v3float %\w+ (%\w+)$',
                         d.get(h.group(2), (0, ''))[1])
            if not (a and b and close(fval(d, a.group(1)), ct)
                    and close(fval(d, b.group(1)), st)):
                bad(name, f"tap 1 is not L*cos({theta}) - T*sin({theta})")
        if taps == 4:
            for n, op in ((2, 'OpFAdd'), (3, 'OpFSub')):
                if not re.match(op + r' %v3float %\w+ %\w+$',
                                d.get(unsel(ours[n][1][8]), (0, ''))[1]):
                    bad(name, f"tap {n} is not an {op} (lateral)")

    # --- per tap: member-3 re-arm, two-sided validity, the ramp ------------
    pay = pays.pop()
    # With --all-lights the payload VARIABLE is shared across cones, so the
    # member-3 chain is taken from this cone's own first tap rather than by
    # searching the module: the OpLoad immediately after the trace.
    m3 = []
    ld0 = re.match(r'\s*%\w+ = OpLoad %float (%\w+)\s*$',
                   lines[ours[0][0] + 1] if ours[0][0] + 1 < len(lines) else '')
    if ld0:
        v = d.get(ld0.group(1), (0, ''))[1]
        cm_ = re.match(r'OpInBoundsAccessChain %\w+ ' + re.escape(pay)
                       + r' (%\w+)$', v)
        if cm_ and uval(d, cm_.group(1)) == 3:
            m3 = [ld0.group(1)]
    if len(m3) != 1:
        bad(name, f"{kind} cone: no member-3 access chain on {pay} after the "
                  f"first tap")
    else:
        arms = [i for i, l in enumerate(lines)
                if re.match(r'\s*OpStore ' + re.escape(m3[0]) + r' (%\w+)\s*$', l)]
        for i, l in enumerate(lines):
            sm = re.match(r'\s*OpStore ' + re.escape(m3[0]) + r' (%\w+)\s*$', l)
            if sm and not close(fval(d, sm.group(1)), 10000.0):
                bad(name, f"member-3 store at {i+1} is not 10000")
        if len(arms) != taps:
            bad(name, f"{len(arms)} member-3 pre-arms, expected {taps}")
        for (ti, _), a in zip(ours, sorted(arms)):
            if not a < ti:
                bad(name, "a tap's pre-arm does not precede its trace")

    # --- the factor: fac = 1 - k * Select(gate, NClamp(num/den,0,1), 0) ----
    facs = [i for i, (ln, v) in d.items()
            if re.match(r'OpFSub %float %float_1 (%\w+)$', v)
            and re.match(r'OpFMul %float (%\w+) (%\w+)$',
                         d.get(re.match(r'OpFSub %float %float_1 (%\w+)$',
                                        v).group(1), (0, ''))[1])]
    fac = None
    for cand in facs:
        km = re.match(r'OpFSub %float %float_1 (%\w+)$', d[cand][1])
        mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', d[km.group(1)][1])
        for a, b in ((mm.group(1), mm.group(2)), (mm.group(2), mm.group(1))):
            if close(fval(d, b), k):
                sm = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$',
                              d.get(a, (0, ''))[1])
                if sm and sm.group(1) == gate and fval(d, sm.group(3)) == 0.0:
                    fac = cand
                    occ = sm.group(2)
    if fac is None:
        bad(name, f"{kind} cone: no `fac = 1 - {k}*Select(gate, occ, 0)`")
        return

    cl = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)$',
                  d.get(occ, (0, ''))[1])
    if not cl or fval(d, cl.group(2)) != 0.0 or fval(d, cl.group(3)) != 1.0:
        bad(name, "occlusion is not NClamp(., 0, 1)")
    else:
        dv = re.match(r'OpFDiv %float (%\w+) (%\w+)$', d.get(cl.group(1), (0, ''))[1])
        if not dv:
            bad(name, "occlusion is not a weighted AVERAGE (no FDiv)")
        elif not re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$',
                          d.get(dv.group(2), (0, ''))[1]):
            bad(name, "the average's divisor is not NMax(den, eps)")

    # ramp present/absent as declared
    ramps = [i for i, (ln, v) in d.items()
             if re.match(r'OpFMul %float %\w+ (%\w+)$', v)
             and close(fval(d, re.match(r'OpFMul %float %\w+ (%\w+)$', v).group(1)),
                       1.0 / tmax)]
    if ramp and len(ramps) != taps * lights:
        bad(name, f"{len(ramps)} `t * (1/tmax)` ramps, expected "
                  f"{taps * lights}")
    if not ramp and ramps:
        bad(name, f"{len(ramps)} ramps emitted with --ramp off")


    if kind == 'sun':
        # --- exactly 3 sites, and each sun-radiance component still has 3 uses -
        uses = [i for i, l in enumerate(lines)
                if re.search(r'OpFMul %float \S+ ' + re.escape(fac) + r'\s*$', l)]
        if len(uses) != 3:
            bad(name, f"factor has {len(uses)} uses, expected 3")
        for u in uses:
            res = re.match(r'\s*(%\w+)\s*=', lines[u]).group(1)
            src = re.match(r'\s*%\w+ = OpFMul %float (%\w+) ', lines[u]).group(1)
            if not re.match(r'OpExtInst %float %\w+ NClamp ', d.get(src, (0, ''))[1]):
                bad(name, f"site at {u+1} does not scale an NClamp result")
            cons = [l for l in lines
                    if re.search(r'OpFMul %float ' + re.escape(res) + r' (%\w+)\s*$', l)]
            if len(cons) != 1:
                bad(name, f"site result {res} has {len(cons)} consumers, expected 1")
            else:
                rad = re.search(r'OpFMul %float ' + re.escape(res) + r' (%\w+)\s*$',
                                cons[0]).group(1)
                n = sum(1 for l in lines if re.search(r'(?<![\w])' + re.escape(rad)
                                                      + r'(?![\w])', l))
                if n != 4:      # its own def + 2 CompositeConstructs + our FMul
                    bad(name, f"sun radiance {rad} has {n} mentions, expected 4")



    else:
        # --- the local-light site: ONE FMul on the visibility SCALAR ----------
        # `vis` is Select(missed, 1, 0) and is multiplied into all three channels,
        # so a single rewrite reaches the whole light term. Assert exactly that:
        # the factor has one use, that use scales a Select(.,1,0), and the result
        # is consumed by exactly three FMuls -- the three radiance channels.
        uses = [i for i, l in enumerate(lines)
                if re.search(r'OpFMul %float \S+ ' + re.escape(fac) + r'\s*$', l)]
        if len(uses) != 1:
            bad(name, f"local factor has {len(uses)} uses, expected 1")
            return
        u = uses[0]
        res = re.match(r'\s*(%\w+)\s*=', lines[u]).group(1)
        src = re.match(r'\s*%\w+ = OpFMul %float (%\w+) ', lines[u]).group(1)
        sv = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', d.get(src, (0, ''))[1])
        if not sv or fval(d, sv.group(2)) != 1.0 or fval(d, sv.group(3)) != 0.0:
            bad(name, f"local site scales {src}, which is not Select(., 1, 0)")
        elif sv.group(1) != lit:
            bad(name, "the visibility scaled is not the one the gate tested")
        cons = [l for l in lines
                if re.search(r'OpFMul %float ' + re.escape(res) + r' (%\w+)\s*$', l)]
        if len(cons) != 3:
            bad(name, f"local site result {res} feeds {len(cons)} channels, "
                      f"expected 3")
        # and the ORIGINAL visibility must now be dead apart from our own FMul
        live = sum(1 for l in lines
                   if re.search(r'(?<![\w])' + re.escape(src) + r'(?![\w])', l))
        if live != 2:      # its own def + our FMul
            bad(name, f"original visibility {src} still has {live} mentions, "
                      f"expected 2 (its def + our FMul)")


def negative(base_dir):
    """The base must carry none of the splice.

    NOTE the trap: the engine forms its OWN `(word >> 5) == 1` skin compare,
    so a class-1 compare is NOT a signature of ours and testing for one makes
    this control fire on the unpatched base. The two things that are ours
    alone are the CullBackFacing (flags 16) trace and the cullMask written as
    Select(gate, 39, 0) -- the engine's own sun NEE writes Select(backlit, 0,
    39), the other way round.
    """
    n = 0
    for f in sorted(glob.glob(os.path.join(base_dir, '*.rgs_reference_main.spv'))):
        lines = dis(f)
        d = index(lines)
        t16 = [1 for _, o in traces(lines) if uval(d, o[1]) == 16]
        sel = [1 for _, (ln, v) in d.items()
               if re.match(r'OpSelect %uint %\w+ (%\w+) (%\w+)$', v)
               and uval(d, re.match(r'OpSelect %uint %\w+ (%\w+) (%\w+)$',
                                    v).group(1)) == 39
               and uval(d, re.match(r'OpSelect %uint %\w+ (%\w+) (%\w+)$',
                                    v).group(2)) == 0]
        if t16 or sel:
            bad(os.path.basename(f), f"NEGATIVE CONTROL: {len(t16)} flags-16 "
                                     f"traces, {len(sel)} Select(.,39,0) masks")
        n += 1
    print(f"  negative control: {n} base modules, "
          f"{'CLEAN' if not FAIL else 'DIRTY'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('base', nargs='?')
    ap.add_argument('--k', type=float)
    ap.add_argument('--tmax', type=float)
    ap.add_argument('--taps', type=int)
    ap.add_argument('--theta', type=float)
    ap.add_argument('--ramp', choices=('on', 'off'), default='on')
    ap.add_argument('--k-local', type=float, default=None,
                    help='expected strength at the local-light cones; '
                         'defaults to --k')
    ap.add_argument('--lights', type=int, default=1,
                    help='cones per module: 1 = sun only, 3 = --all-lights')
    ap.add_argument('--gate', choices=('bounce', 'sample'), default='bounce',
                    help='which loop counter the `== 0` conjunct must test')
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    if a.negative:
        negative(a.rung)
    else:
        n = 0
        for f in sorted(glob.glob(os.path.join(a.rung,
                                               '*.rgs_reference_main.spv'))):
            b = os.path.join(a.base, os.path.basename(f))
            if not os.path.exists(b):
                raise SystemExit(f"no base for {f}")
            verify_module(os.path.basename(f).split('.')[0], dis(f), dis(b),
                          a.k, a.tmax, a.taps, a.theta, a.ramp == 'on',
                          a.lights, a.k_local, a.gate)
            n += 1
        if n != 12:
            bad('rung', f"{n} reference modules verified, expected 12")
        print(f"  verify_cavity2: {n}/12 modules, "
              f"k={a.k} tmax={a.tmax} taps={a.taps} theta={a.theta} "
              f"lights={a.lights}"
              + (f" k_local={a.k_local}" if a.k_local is not None else "")
              + f" gate={a.gate}")
    if FAIL:
        print("VERIFY FAILED:\n  " + "\n  ".join(FAIL))
        sys.exit(1)
    print("  verify_cavity2: PASS")


if __name__ == '__main__':
    main()
