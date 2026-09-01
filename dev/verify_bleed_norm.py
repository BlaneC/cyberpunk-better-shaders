#!/usr/bin/env python3
"""78: prove the emitted luminance hold, from the ASSEMBLED TEXT of a rung.

The 53 discipline, one level up: not "the patcher says it emitted a hold" but
"the instructions in the shipped module, re-parsed and executed, hold the
luminance". For every bleed site in every *.spvasm of a rung dir this:

  1. finds the normalisation chain structurally (FDiv over an NMax'd luma),
  2. checks its EIGHT baked constants against k and beta,
  3. proves the channel wiring -- the R multiply lands on the fan-out whose
     colour is the R colour, and on no other (the 39 rule: never a guessed
     channel),
  4. INTERPRETS the emitted instructions at a grid of NoL x colour x gate and
     compares against the closed form, and
  5. asserts the point of the rung: Rec.709 luminance out == luminance in on
     the site's own diffuse-colour triple, and exact identity off skin.

Usage:  ./dev/verify_bleed_norm.py swaps.skin.real-gloss-bleedn-oilh [--k 1.0]
"""

import argparse, glob, itertools, math, os, re, sys

W709 = (0.2126, 0.7152, 0.0722)
BAND, KR, KB = 0.35, 0.336, 0.101


def f32(x):
    import struct
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


class Mod:
    def __init__(self, path):
        self.name = os.path.basename(path)
        self.defs, self.const = {}, {}
        for ln in open(path):
            m = re.match(r'\s*(%[\w$]+)\s*=\s*(.*?)\s*$', ln)
            if not m:
                continue
            rid, body = m.groups()
            self.defs[rid] = body
            mc = re.match(r'OpConstant %float (\S+)$', body)
            if mc:
                try:                       # nan/inf print as hex floats
                    self.const[rid] = float.fromhex(mc.group(1)) \
                        if mc.group(1).startswith('0x') else float(mc.group(1))
                except (ValueError, OverflowError):
                    pass
        self.uses = {}
        for rid, body in self.defs.items():
            for op in re.findall(r'%[\w$]+', body):
                self.uses.setdefault(op, []).append(rid)

    def op(self, rid):
        return self.defs.get(rid, '')

    def match(self, rid, pat):
        return re.match(pat + r'$', self.op(rid))


def ev(mod, rid, bind, memo):
    """Interpret one emitted value. Leaves must be bound; anything else is a
    structure the chain was not supposed to reach, and raises."""
    if rid in bind:
        return bind[rid]
    if rid in memo:
        return memo[rid]
    if rid in mod.const:
        return mod.const[rid]
    b = mod.op(rid)
    m = re.match(r'OpF(Mul|Add|Sub|Div) %float (%[\w$]+) (%[\w$]+)$', b)
    if m:
        o, a, c = m.group(1), ev(mod, m.group(2), bind, memo), \
                             ev(mod, m.group(3), bind, memo)
        v = {'Mul': a * c, 'Add': a + c, 'Sub': a - c,
             'Div': a / c if c else float('inf')}[o]
    else:
        m = re.match(r'OpExtInst %float %[\w$]+ (NClamp|NMax|NMin) '
                     r'(%[\w$]+) (%[\w$]+)(?: (%[\w$]+))?$', b)
        if m:
            g = m.groups()
            a = ev(mod, g[1], bind, memo)
            c = ev(mod, g[2], bind, memo)
            if g[0] == 'NClamp':
                v = min(max(a, c), ev(mod, g[3], bind, memo))
            elif g[0] == 'NMax':
                v = max(a, c)
            else:
                v = min(a, c)
        else:
            m = re.match(r'OpSelect %float (%[\w$]+) (%[\w$]+) (%[\w$]+)$', b)
            if not m:
                raise KeyError(f"{mod.name}: unevaluatable {rid} = {b!r}")
            v = ev(mod, m.group(2) if bind['#gate'] else m.group(3),
                   bind, memo)
    v = f32(v)
    memo[rid] = v
    return v


def tree(mod, rid, depth=4):
    """ids reachable from rid through FMul operands (the fan-out walk)."""
    out = {rid}
    if depth:
        m = mod.match(rid, r'OpFMul %float (%[\w$]+) (%[\w$]+)')
        if m:
            for o in m.groups():
                out |= tree(mod, o, depth - 1)
    return out


def sites(mod):
    """every normalisation chain, structurally identified."""
    for rid, body in mod.defs.items():
        m = re.match(r'OpFDiv %float (%[\w$]+) (%[\w$]+)$', body)
        if not m:
            continue
        num, den = m.groups()
        md = mod.match(den, r'OpExtInst %float %[\w$]+ NMax '
                            r'(%[\w$]+) (%[\w$]+)')
        if not md or md.group(2) not in mod.const:
            continue
        ma = mod.match(md.group(1), r'OpFAdd %float (%[\w$]+) (%[\w$]+)')
        if not ma or ma.group(1) != num:
            continue
        # num = ((Cr*wr + Cg*wg) + Cb*wb)
        m1 = mod.match(num, r'OpFAdd %float (%[\w$]+) (%[\w$]+)')
        if not m1:
            continue
        m2 = mod.match(m1.group(1), r'OpFAdd %float (%[\w$]+) (%[\w$]+)')
        if not m2:
            continue
        try:
            lum = [mod.match(x, r'OpFMul %float (%[\w$]+) (%[\w$]+)').groups()
                   for x in (m2.group(1), m2.group(2), m1.group(2))]
        except AttributeError:
            continue
        # delta = (Cr*aR - Cb*aB) * w
        md2 = mod.match(ma.group(2), r'OpFMul %float (%[\w$]+) (%[\w$]+)')
        if not md2:
            continue
        ms = mod.match(md2.group(1), r'OpFSub %float (%[\w$]+) (%[\w$]+)')
        if not ms:
            continue
        yield dict(s=rid, num=num, den=den, eps=mod.const[md.group(2)],
                   lum=lum, w=md2.group(2), sub=ms.groups())


def check(path, k, beta, verbose):
    mod, bad, n = Mod(path), [], 0
    for st in sites(mod):
        n += 1
        why = []
        # --- 2. the eight constants ---------------------------------------
        (Cr, wr), (Cg, wg), (Cb, wb) = st['lum']
        got = [mod.const.get(wr), mod.const.get(wg), mod.const.get(wb)]
        if [None if g is None else round(g, 7) for g in got] != \
                [round(f32(x), 7) for x in W709]:
            why.append(f"luma weights {got} != Rec.709")
        dr, db = st['sub']
        mr = mod.match(dr, r'OpFMul %float (%[\w$]+) (%[\w$]+)')
        mb = mod.match(db, r'OpFMul %float (%[\w$]+) (%[\w$]+)')
        if not mr or not mb:
            why.append("delta terms are not FMuls")
        else:
            if mr.group(1) != Cr or mb.group(1) != Cb:
                why.append("delta is not taken on the R and B colours")
            aR, aB = mod.const.get(mr.group(2)), mod.const.get(mb.group(2))
            for nm, g, want in (('aR', aR, beta * k * W709[0] * KR),
                                ('aB', aB, beta * k * W709[2] * KB)):
                if g is None or abs(g - f32(want)) > 1e-9:
                    why.append(f"{nm}={g} want {f32(want)}")
        # --- w = sat(1 - NoL/BAND)^2 --------------------------------------
        mw = mod.match(st['w'], r'OpFMul %float (%[\w$]+) (%[\w$]+)')
        if not mw or mw.group(1) != mw.group(2):
            why.append("w is not a square")
            NoL = None
        else:
            mc = mod.match(mw.group(1), r'OpExtInst %float %[\w$]+ NClamp '
                                        r'(%[\w$]+) (%[\w$]+) (%[\w$]+)')
            ms = mod.match(mc.group(1), r'OpFSub %float (%[\w$]+) (%[\w$]+)') \
                if mc else None
            mq = mod.match(ms.group(2), r'OpFMul %float (%[\w$]+) (%[\w$]+)') \
                if ms else None
            if not mq or abs(mod.const.get(mq.group(2), 0) - f32(1 / BAND)) > 1e-6:
                why.append("w's band constant is not 1/0.35")
                NoL = None
            else:
                NoL = mq.group(1)
        # --- 3. the three gated multipliers and their wiring --------------
        sel = {}
        for u in mod.uses.get(st['s'], []):
            m = mod.match(u, r'OpSelect %float (%[\w$]+) (%[\w$]+) (%[\w$]+)')
            if m and m.group(2) == st['s']:
                sel['G'] = (u, m.group(1))
            mm = mod.match(u, r'OpFMul %float (%[\w$]+) '
                                 + re.escape(st['s']))
            if mm:
                head = mod.op(mm.group(1))
                ch = 'R' if head.startswith('OpFAdd') else \
                     'B' if head.startswith('OpFSub') else None
                if ch:
                    for u2 in mod.uses.get(u, []):
                        m2 = mod.match(u2, r'OpSelect %float (%[\w$]+) '
                                           r'(%[\w$]+) (%[\w$]+)')
                        if m2 and m2.group(2) == u:
                            sel[ch] = (u2, m2.group(1))
        if sorted(sel) != ['B', 'G', 'R']:
            why.append(f"gated multipliers found: {sorted(sel)}")
        elif len({g for _, g in sel.values()}) != 1:
            why.append("the three channels are gated on DIFFERENT bools")
        cons = {}
        for ch, (sid, _) in sel.items():
            hits = [u for u in mod.uses.get(sid, [])
                    if mod.match(u, r'OpFMul %float (%[\w$]+) '
                                    + re.escape(sid))]
            if len(hits) != 1:
                why.append(f"{ch} multiplier has {len(hits)} consumers")
                continue
            cons[ch] = mod.match(hits[0], r'OpFMul %float (%[\w$]+) '
                                          + re.escape(sid)).group(1)
        if len(set(cons.values())) != len(cons):
            why.append("two channels rewrite the SAME fan-out id")
        for ch, colour in (('R', Cr), ('G', Cg), ('B', Cb)):
            if ch not in cons:
                continue
            t = tree(mod, cons[ch])
            others = {'R': Cr, 'G': Cg, 'B': Cb}
            if colour not in t:
                why.append(f"{ch} multiply does not land on the {ch} colour")
            for o, cid in others.items():
                if o != ch and cid in t:
                    why.append(f"{ch}'s fan-out also carries the {o} colour")
        # --- 4/5. execute it ----------------------------------------------
        if not why and NoL:
            gate = sel['R'][1]
            for nol, col in itertools.product(
                    (0.0, 0.02, 0.05, 0.1, 0.175, 0.25, 0.349, 0.35, 0.6, 1.0),
                    ((0.35, 0.20, 0.16), (0.9, 0.9, 0.9), (0.05, 0.02, 0.02),
                     (0.0, 0.0, 0.0), (0.6, 0.1, 0.05), (0.1, 0.2, 0.6))):
                for g in (True, False):
                    bind = {NoL: nol, Cr: col[0], Cg: col[1], Cb: col[2],
                            '#gate': g}
                    m = {c: ev(mod, sel[c][0], bind, {}) for c in 'RGB'}
                    w = max(0.0, min(1.0, 1 - nol / BAND)) ** 2
                    if not g:
                        if (m['R'], m['G'], m['B']) != (1.0, 1.0, 1.0):
                            why.append(f"gate false is not identity at {nol}")
                        continue
                    Y = sum(wi * ci for wi, ci in zip(W709, col))
                    d = w * (beta * k * W709[0] * KR * col[0]
                             - beta * k * W709[2] * KB * col[2])
                    s = Y / max(Y + d, st['eps'])
                    want = ((1 + k * KR * w) * s, s, (1 - k * KB * w) * s)
                    for c, wv in zip('RGB', want):
                        if abs(m[c] - wv) > 2e-6 * max(1.0, abs(wv)):
                            why.append(f"m_{c}({nol},{col})={m[c]:.9f} "
                                       f"closed form {wv:.9f}")
                    # the point of the rung, on the site's own triple
                    if Y > 0 and beta == 1.0:
                        yo = sum(wi * ci * m[c]
                                 for wi, ci, c in zip(W709, col, 'RGB'))
                        if abs(yo - Y) > 3e-6 * Y:
                            why.append(f"luminance moved {yo / Y - 1:+.3%} "
                                       f"at NoL={nol} colour={col}")
        if why:
            bad.append((st['s'], why[:3]))
    return n, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--k', type=float, default=1.0)
    ap.add_argument('--beta', type=float, default=1.0)
    ap.add_argument('--expect-sites', type=int, default=150)
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.rung, '*.spvasm')))
    if not files:
        sys.exit(f"no .spvasm in {a.rung} -- point this at a BUILD dir")
    tot, mods, bad = 0, 0, []
    for f in files:
        n, b = check(f, a.k, a.beta, a.verbose)
        tot += n
        mods += 1 if n else 0
        for sid, why in b:
            bad.append((os.path.basename(f)[:8], sid, why))
    print("  %s: %d luminance-hold sites over %d modules (%d files read)"
          % (os.path.basename(a.rung), tot, mods, len(files)))
    if bad:
        for m, sid, why in bad[:12]:
            print("    %s %s :: %s" % (m, sid, '; '.join(why)), file=sys.stderr)
        sys.exit("  FAILED: %d site(s) do not hold luminance" % len(bad))
    if tot != a.expect_sites:
        sys.exit("  FAILED: %d sites, expected %d" % (tot, a.expect_sites))
    print("  every site: constants exact, channel wiring proven, closed form "
          "matched at 120 (NoL x colour x gate) points, luminance held")


if __name__ == '__main__':
    main()
