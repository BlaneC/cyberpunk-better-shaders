#!/usr/bin/env python3
"""84: prove the emitted environment chroma bleed, from the SHIPPED BYTES.

The 53/78 discipline applied to the GI raygens: not "the patcher reported a
splice" but "the instructions in the shipped .spv, re-disassembled, re-parsed
and EXECUTED, widen chroma and hold Rec.709 luminance".

Per module it:

  1. finds the gate structurally -- OpLogicalAnd(class != 1, class != 4) with
     BOTH tests hanging off ONE class value (never two decodes that can drift
     apart), and exactly three OpSelects on it;
  2. identifies each select's channel from the module's OWN downstream
     structure, not from the emission order: for a plain-RGB write, its
     position in the write's texel; for a YCoCg write, its position in the
     encode's v3 source, where the Co row (0.5, 0, -0.5) is asymmetric in R
     and B and therefore pins them (the 39 rule -- a channel is proven or the
     check fails);
  3. cross-checks that binding against the luminance weight the operator
     multiplies that same value by (0.2126 must land on the channel the write
     calls R), so a transposed emission cannot pass;
  4. checks every baked constant against the model in float32;
  5. INTERPRETS the emitted instruction graph at a grid of colours x gate
     states, in float32 and in float64, and compares against the closed form;
  6. asserts the point of the rung: sum_c w_c*out_c == Y (luminance held),
     the gain stays inside [0, GMAX] so the clamp provably never binds on a
     non-negative colour, and gate-false is BIT-EXACT identity.

Usage:
    ./dev/verify_env_chroma.py ~/.local/lib/callisto/skin.set/<rung> --q 0.35
    ./dev/verify_env_chroma.py <the base rung> --q 0.35 --expect-sites 0
"""

import argparse, glob, math, os, re, struct, subprocess, sys, tempfile

W709 = (0.2126, 0.7152, 0.0722)
GMAX, EPS = 16.0, 1e-30
YCC = {'Y': (0.25, 0.5, 0.25), 'Co': (0.5, 0.0, -0.5),
       'Cg': (-0.25, 0.5, -0.25)}


def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def bits(x):
    return struct.pack('<f', float(x))


class Mod:
    def __init__(self, path):
        self.name = os.path.basename(path)
        self.defs, self.fc, self.uc = {}, {}, {}
        for ln in open(path, errors='replace'):
            m = re.match(r'\s*(%[\w$]+)\s*=\s*(.*?)\s*$', ln)
            if not m:
                continue
            rid, body = m.groups()
            self.defs[rid] = body
            mc = re.match(r'OpConstant %float (\S+)$', body)
            if mc:
                try:
                    # spirv-dis prints an f32 constant as rounded decimal
                    # text; parsing it as f64 gives a number ~1e-9 off the
                    # value the GPU holds, which is 100x the error this file
                    # is trying to measure. Round back to f32.
                    self.fc[rid] = f32(float.fromhex(mc.group(1))
                                       if mc.group(1).startswith('0x')
                                       else float(mc.group(1)))
                except (ValueError, OverflowError):
                    pass
            mu = re.match(r'OpConstant %uint (\d+)$', body)
            if mu:
                self.uc[rid] = int(mu.group(1))
        self.uses = {}
        for rid, body in self.defs.items():
            for op in re.findall(r'%[\w$]+', body):
                self.uses.setdefault(op, []).append(rid)

    def op(self, rid):
        return self.defs.get(rid, '')

    def vec3(self, rid):
        m = re.match(r'OpCompositeConstruct %v3float (%\S+) (%\S+) (%\S+)$',
                     self.op(rid))
        if not m:
            return None
        v = [self.fc.get(x) for x in m.groups()]
        return None if any(x is None for x in v) else tuple(v)

    def v3_ids(self, rid):
        m = re.match(r'OpCompositeConstruct %v3float (%\S+) (%\S+) (%\S+)$',
                     self.op(rid))
        return list(m.groups()) if m else None


def ev(mod, rid, bind, memo, F):
    """Interpret one emitted value. F rounds every result (float32 or f64).
    A leaf the chain was not supposed to reach raises, so an unrecognized
    structure can never be mistaken for agreement."""
    if rid in bind:
        return bind[rid]
    if rid in memo:
        return memo[rid]
    if rid in mod.fc:
        return F(mod.fc[rid])
    b = mod.op(rid)
    m = re.match(r'OpF(Mul|Add|Sub|Div) %float (%[\w$]+) (%[\w$]+)$', b)
    if m:
        a = ev(mod, m.group(2), bind, memo, F)
        c = ev(mod, m.group(3), bind, memo, F)
        v = F({'Mul': lambda: a * c, 'Add': lambda: a + c,
               'Sub': lambda: a - c,
               'Div': lambda: (a / c) if c != 0 else math.inf}[m.group(1)]())
    else:
        m = re.match(r'OpExtInst %float %[\w$]+ (NClamp|NMax|NMin) '
                     r'(%[\w$]+) (%[\w$]+)(?: (%[\w$]+))?$', b)
        if m:
            o = m.group(1)
            a = ev(mod, m.group(2), bind, memo, F)
            c = ev(mod, m.group(3), bind, memo, F)
            if o == 'NMax':
                v = max(a, c)
            elif o == 'NMin':
                v = min(a, c)
            else:
                d = ev(mod, m.group(4), bind, memo, F)
                v = min(max(a, c), d)
            v = F(v)
        else:
            m = re.match(r'OpSelect %float (%[\w$]+) (%[\w$]+) (%[\w$]+)$', b)
            if m:
                g = bind.get(m.group(1))
                if g is None:
                    raise KeyError(f"unbound bool {m.group(1)}")
                v = ev(mod, m.group(2 if g else 3), bind, memo, F)
            else:
                raise KeyError(f"{mod.name}: cannot interpret {rid} = {b}")
    memo[rid] = v
    return v


def closed_form(C, q, F):
    """out_c = C_c * clamp(g_c/max(n,eps), 0, GMAX),
       g_c = (1-q) + q*C_c/max(Y,eps), n = sum w_c*r_c*g_c.

    Every CONSTANT is float32 whatever F is -- that is what the module holds.
    F is the arithmetic precision, so F=float isolates structure (does the
    emitted graph compute this expression at all) from rounding, and F=f32
    is the hardware-representative pass."""
    # the two knob constants are what the PATCHER bakes: f32(q) and
    # f32(1-q), each rounded from the nominal value, never derived from the
    # other (1 - f32(0.35) != f32(0.65), and that 5e-8 is exactly the size of
    # error a sloppy model would blame on the shader)
    omq = F(f32(1.0 - q))
    q = F(f32(q))
    w = [F(f32(x)) for x in W709]
    Y = F(F(F(C[0] * w[0]) + F(C[1] * w[1])) + F(C[2] * w[2]))
    ym = max(Y, F(f32(EPS)))
    iy = F(F(1.0) / ym)
    r = [F(C[c] * iy) for c in range(3)]
    g = [F(omq + F(r[c] * q)) for c in range(3)]
    p = [F(r[c] * g[c]) for c in range(3)]
    n = F(F(F(p[0] * w[0]) + F(p[1] * w[1])) + F(p[2] * w[2]))
    nm = max(n, F(f32(EPS)))
    s = F(F(1.0) / nm)
    out = []
    for c in range(3):
        h = min(max(F(g[c] * s), F(0.0)), F(f32(GMAX)))
        out.append(F(min(max(F(C[c] * h), F(f32(-65504.0))),
                         F(f32(65504.0)))))
    return out, Y, n


def find_gate(mod):
    """(class_value, gate_id) for the one class != 1 && class != 4 gate."""
    hits = []
    for rid, body in mod.defs.items():
        m = re.match(r'OpLogicalAnd %bool (%[\w$]+) (%[\w$]+)$', body)
        if not m:
            continue
        vals, srcs = {}, set()
        ok = True
        for b in m.groups():
            mm = re.match(r'OpINotEqual %bool (%[\w$]+) (%[\w$]+)$', mod.op(b))
            if not mm:
                ok = False
                break
            u = mod.uc.get(mm.group(2))
            if u is None:
                ok = False
                break
            vals[u] = mm.group(1)
            srcs.add(mm.group(1))
        if ok and set(vals) == {1, 4}:
            hits.append((rid, srcs))
    if len(hits) != 1:
        return None, None, "%d class!=1&&!=4 gates" % len(hits)
    rid, srcs = hits[0]
    if len(srcs) != 1:
        return None, None, ("the two class tests read %d different values %s "
                            "-- one decode or nothing" % (len(srcs), sorted(srcs)))
    return srcs.pop(), rid, None


def channels_from_write(mod, sels):
    """{select id: channel}, read off the module's OWN write structure."""
    sset = set(sels)
    # plain-RGB write: the three selects are components 0..2 of a v4 texel
    for rid, body in mod.defs.items():
        m = re.match(r'OpCompositeConstruct %v4float (%\S+) (%\S+) (%\S+) '
                     r'(%\S+)$', body)
        if m and set(m.groups()[:3]) == sset:
            return {m.group(i + 1): i for i in range(3)}, 'rgb'
    # YCoCg write: the selects are the v3 source of the encode dots, and the
    # Co row (0.5, 0, -0.5) is what tells R from B.
    roles, order = set(), None
    for rid, body in mod.defs.items():
        ids = mod.v3_ids(rid)
        if ids is None or set(ids) != sset:
            continue
        # dxil-spirv rebuilds the source vector once per encode row, so the
        # three roles are spread over three identical v3 constructs -- union
        # them, and require the operand ORDER to agree across all of them.
        if order is None:
            order = ids
        elif order != ids:
            return None, None
        for u in mod.uses.get(rid, []):
            m = re.match(r'OpDot %float (%\S+) (%\S+)$', mod.op(u))
            if not m:
                continue
            for other in m.groups():
                v = mod.vec3(other)
                if v is None:
                    continue
                for rn, ref in YCC.items():
                    if all(abs(a - b) < 1e-4 for a, b in zip(v, ref)):
                        roles.add(rn)
    if order is not None and roles == {'Y', 'Co', 'Cg'}:
        return {order[i]: i for i in range(3)}, 'ycocg'
    return None, None


def verify_module(path, q, npts, verbose):
    mod = Mod(path)
    cls, gate, why = find_gate(mod)
    if gate is None:
        return dict(name=mod.name, sites=0, why=why)
    sels = [rid for rid, b in mod.defs.items()
            if re.match(r'OpSelect %float ' + re.escape(gate) + r' ', b)]
    fails = []
    if len(sels) != 3:
        return dict(name=mod.name, sites=0,
                    why="%d OpSelects on the gate, want 3" % len(sels))
    chan_by_sel, shape = channels_from_write(mod, sels)
    if chan_by_sel is None:
        return dict(name=mod.name, sites=0,
                    why="the three gated selects are not the write's colour "
                        "channels (neither texel nor YCoCg source)")
    src, out = {}, {}
    for se in sels:
        m = re.match(r'OpSelect %float \S+ (%[\w$]+) (%[\w$]+)$', mod.op(se))
        ch = chan_by_sel[se]
        # out[ch] is the SELECT itself: the gate-false leg has to be exercised
        # through the instruction that implements it, not assumed.
        out[ch], src[ch] = se, m.group(2)
    if len(set(src.values())) != 3:
        fails.append("the three gate-false operands are not distinct")

    # (3) the luminance weight must land on the channel the WRITE calls
    # R/G/B. If the operator ever got transposed against the encode, the
    # luminance would still be "held" -- of the wrong triple -- and only this
    # check would notice.
    for ch in range(3):
        want = f32(W709[ch])
        hit = False
        for u in mod.uses.get(src[ch], []):
            if not re.match(r'OpFMul %float ', mod.op(u)):
                continue
            for x in re.findall(r'%[\w$]+', mod.op(u)):
                if x in mod.fc and f32(mod.fc[x]) == want:
                    hit = True
        if not hit:
            fails.append("channel %d (%s): no luma multiply by %.4f -- the "
                         "operator's channel order disagrees with the write's"
                         % (ch, src[ch], W709[ch]))

    # (4) constants
    used = set()
    stack = [out[c] for c in range(3)]
    seen = set()
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        if x in mod.fc:
            used.add(f32(mod.fc[x]))
            continue
        for o in re.findall(r'%[\w$]+', mod.op(x)):
            stack.append(o)
    want = {f32(v) for v in (W709 + (q, 1.0 - q, GMAX, EPS, 0.0, 1.0,
                                     65504.0, -65504.0))}
    missing = sorted(want - used)
    if missing:
        fails.append("constants missing from the emitted chain: %s" % missing)

    # (5)+(6) execute
    rng = _rng(1234 + hash(mod.name) % 9973)
    pts = _points(rng, npts)
    maxlum = maxrel = 0.0
    maxgain = 0.0
    ident = 0
    for C in pts:
        C32 = [f32(x) for x in C]
        for F, tol in ((f32, 2e-6), (float, 1e-12)):
            bind = {gate: True}
            for ch in range(3):
                bind[src[ch]] = F(C32[ch])
            memo = {}
            got = [ev(mod, out[ch], bind, memo, F) for ch in range(3)]
            exp, Y, n = closed_form([F(x) for x in C32], F(q), F)
            for ch in range(3):
                d = abs(got[ch] - exp[ch])
                rel = d / max(abs(exp[ch]), 1e-30)
                maxrel = max(maxrel, rel)
                if rel > tol:
                    fails.append("channel %d: emitted %.9g vs closed form "
                                 "%.9g at C=%s" % (ch, got[ch], exp[ch], C32))
            if F is f32:
                Yo = sum(f32(got[c] * f32(W709[c])) for c in range(3))
                if Y > 0:
                    maxlum = max(maxlum, abs(Yo - Y) / Y)
                for ch in range(3):
                    if C32[ch] > 0:
                        maxgain = max(maxgain, got[ch] / C32[ch])
        # gate false: BIT-exact identity
        bind = {gate: False}
        for ch in range(3):
            bind[src[ch]] = C32[ch]
        memo = {}
        for ch in range(3):
            v = ev(mod, out[ch], bind, memo, f32)
            if bits(v) != bits(C32[ch]):
                fails.append("gate-false is not bit-identity on channel %d"
                             % ch)
            else:
                ident += 1
    if maxgain > GMAX:
        fails.append("per-channel gain %.4f exceeded GMAX %.1f -- the clamp "
                     "binds on a non-negative colour and the hold is not "
                     "exact there" % (maxgain, GMAX))
    return dict(name=mod.name, sites=1, shape=shape, cls=cls, gate=gate,
                points=len(pts) * 2, ident=ident, maxlum=maxlum,
                maxrel=maxrel, maxgain=maxgain, fails=fails)


def _rng(seed):
    import random
    return random.Random(seed)


def _points(rng, n):
    """A colour set that covers what the buffer actually holds: many decades
    of magnitude, every saturation from grey to a single channel, plus the
    edge cases (black, exactly grey, pure channels, the fp16 ceiling)."""
    pts = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5),
           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
           (1.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 0.0, 1.0),
           (65504.0, 65504.0, 65504.0), (65504.0, 0.0, 0.0),
           (1e-6, 2e-6, 3e-6), (3e4, 1.0, 1e-3)]
    while len(pts) < n:
        mag = 10.0 ** rng.uniform(-4.0, 3.0)
        v = [rng.random() ** rng.choice([0.5, 1.0, 3.0]) for _ in range(3)]
        if rng.random() < 0.15:
            v[rng.randrange(3)] = 0.0
        pts.append(tuple(mag * x for x in v))
    return pts[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--q', type=float, required=True)
    ap.add_argument('--points', type=int, default=3000,
                    help='colours per site (x2 gate states)')
    ap.add_argument('--expect-sites', type=int, default=4)
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.rung, '*.rgs_restirgi_*.spv')))
    if not files:
        sys.exit("no rgs_restirgi_*.spv in %s" % a.rung)
    tmp = tempfile.mkdtemp(prefix='envchk.')
    rows, total_sites, total_pts, fails = [], 0, 0, []
    shapes = {}
    for f in files:
        asm = os.path.join(tmp, os.path.basename(f) + '.spvasm')
        subprocess.run(['spirv-dis', f, '-o', asm], check=True)
        r = verify_module(asm, a.q, a.points, a.verbose)
        rows.append(r)
        total_sites += r['sites']
        if r['sites']:
            shapes[r['shape']] = shapes.get(r['shape'], 0) + 1
            total_pts += r['points']
            fails += ["%s: %s" % (r['name'][:16], x) for x in r['fails']]
            print("  %-16s %-5s site ok, gate on %s, %d points, "
                  "luma err %.2e, closed-form err %.2e, max gain %.3f"
                  % (r['name'][:16], r['shape'], r['cls'], r['points'],
                     r['maxlum'], r['maxrel'], r['maxgain']))
        else:
            print("  %-16s NO SITE (%s)" % (r['name'][:16], r['why']))

    print("  census: %d sites over %d modules, shapes %s, %d evaluated "
          "points, %d gate-false identity checks"
          % (total_sites, len(files), shapes or '{}', total_pts,
             sum(r.get('ident', 0) for r in rows)))
    ok = True
    if total_sites != a.expect_sites:
        print("  COVERAGE FAIL: %d sites, expected %d"
              % (total_sites, a.expect_sites))
        ok = False
    if a.expect_sites and shapes != {'rgb': 2, 'ycocg': 2}:
        print("  COVERAGE FAIL: shapes %s, census says 2 rgb + 2 ycocg" % shapes)
        ok = False
    maxlum = max([r.get('maxlum', 0.0) for r in rows] or [0.0])
    if a.expect_sites and maxlum >= 1e-5:
        print("  LUMINANCE FAIL: max relative error %.3e >= 1e-5" % maxlum)
        ok = False
    for x in fails:
        print("  FAIL: %s" % x)
        ok = False
    print("ALL CHECKS PASS" if ok else "CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
