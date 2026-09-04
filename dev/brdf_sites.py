#!/usr/bin/env python3
"""Structural detector for the compute resolvers' direct-light BRDF block.

Anchored on the GGX D term (the only `OpFDiv` by an `OpFMul ... %float_3.14159274`
in the module), it names, per module and never by id:

    alpha    the OpSelect whose class-1 arm is the skin roughness (108/cap)
    a2       alpha*alpha
    noh nov nol                       the three cosines the lobe evaluates
    vis      0.5 / (Smith sum)        the game's SUM-not-product Vis (28 sec 2)
    specD    D * NoL * Vis
    S        the scalar every F component multiplies at the lit block's tail
    F        [3] the Fresnel triple (the skin arm is 72's oil layer)
    lc       [3] the light colour triple
    diff     the diffuse BRDF scalar every diffuse channel multiplies
    phis     [6] the lit block's merge phis, spec first
    class1   the module's own `class == 1` predicate (from the alpha select)

Nothing here is a guess: every name is reached by following operands, and each
step asserts the shape it expects.  A module that does not match is reported,
not patched.
"""
import re, sys

DEF = re.compile(r'^\s*(%\w+) = (Op\w+)(?: (%\w+))?(.*)$')


def parse(src):
    """id -> dict(op, ty, args, line); plus line list."""
    D, lines = {}, src.splitlines()
    for i, ln in enumerate(lines):
        m = DEF.match(ln)
        if not m:
            continue
        rid, op, ty, rest = m.groups()
        args = re.findall(r'%\w+', rest or '')
        D[rid] = dict(op=op, ty=ty, args=args, line=i, text=ln.strip())
    return D, lines


def users(D):
    U = {}
    for rid, d in D.items():
        for a in d['args']:
            U.setdefault(a, []).append(rid)
    return U


class NoMatch(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise NoMatch(msg)


def is_op(D, i, op, n=None):
    d = D.get(i)
    return d is not None and d['op'] == op and (n is None or len(d['args']) == n)


def fmul_pair(D, i):
    d = D.get(i)
    if d is None or d['op'] != 'OpFMul' or len(d['args']) != 2:
        return None
    return d['args']


def other(pair, x):
    a, b = pair
    return b if a == x else (a if b == x else None)


def ext(D, i):
    """(instr, args) for an OpExtInst, else None."""
    d = D.get(i)
    if d is None or d['op'] != 'OpExtInst':
        return None
    m = re.match(r'^\s*%\w+ = OpExtInst %\w+ %\w+ (\w+)(.*)$', d['text'])
    return (m.group(1), re.findall(r'%\w+', m.group(2))) if m else None


def leaves(D, root, stop, depth=0):
    """Multiplicative leaves of an OpFMul tree (ids that are not OpFMul)."""
    if depth > 8 or root in stop:
        return [root]
    p = fmul_pair(D, root)
    if p is None:
        return [root]
    out = []
    for a in p:
        out += leaves(D, a, stop, depth + 1)
    return out


DISNEY = '%float_0_107508637'      # the Disney retro-reflection constant
INVPI = '%float_0_318309873'


def _up(D, U, x, limit=32):
    """Walk up a chain of single OpFMul consumers; return the last node."""
    top = x
    for _ in range(limit):
        ups = [v for v in U.get(top, []) if fmul_pair(D, v)]
        if len(ups) != 1:
            break
        top = ups[0]
    return top


def _chan3(D, U, x):
    """The three per-channel OpFMul consumers of `x`, or None."""
    us = [v for v in U.get(x, []) if fmul_pair(D, v)]
    if len(us) != 3:
        return None
    us.sort(key=lambda i: D[i]['line'])
    return us


def alpha_sites(D, U):
    """A: every GGX roughness select.  Anchor: a2 = alpha*alpha under the D
    term's `pi` divide, alpha an OpSelect whose predicate is the class test."""
    out = []
    for rid, d in D.items():
        if d['op'] != 'OpFDiv' or len(d['args']) != 2:
            continue
        den = D.get(d['args'][1])
        if not (den and den['op'] == 'OpFMul' and
                any(a.startswith('%float_3_14159') for a in den['args'])):
            continue
        a2 = d['args'][0]
        pr = fmul_pair(D, a2)
        if not (pr and pr[0] == pr[1]):
            continue
        al = pr[0]
        sel, scale = al, None
        if not is_op(D, al, 'OpSelect', 3):
            # a patched rung scales the shipped select: alpha = sel * (1 + k)
            q = fmul_pair(D, al)
            if not q:
                continue
            s2 = [x for x in q if is_op(D, x, 'OpSelect', 3)]
            if len(s2) != 1:
                continue
            sel, scale = s2[0], other(q, s2[0])
        out.append(dict(D=rid, a2=a2, alpha=al, sel=sel, scale=scale,
                        class1=D[sel]['args'][0], line=D[sel]['line']))
    out.sort(key=lambda s: s['line'])
    return out


def diffuse_sites(D, U):
    """B: every Disney diffuse BRDF scalar.  Anchor: `1/pi - R*0.1075`, walked
    up its single-consumer product chain to the node three channels multiply."""
    out, miss = [], []
    for rid, d in D.items():
        if d['op'] != 'OpFSub' or len(d['args']) != 2:
            continue
        if d['args'][0] != INVPI:
            continue
        pr = fmul_pair(D, d['args'][1])
        if not (pr and DISNEY in pr):
            continue
        diff = _up(D, U, rid)
        ch = _chan3(D, U, diff)
        if ch is None:
            miss.append((rid, 'the diffuse BRDF has %d product consumers, want 3'
                         % len([v for v in U.get(diff, []) if fmul_pair(D, v)])))
            continue
        out.append(dict(root=rid, diff=diff, chan=ch, line=D[diff]['line']))
    out.sort(key=lambda s: s['line'])
    return out, miss


def spec_sites(D, U):
    """C: every punctual GGX lobe tail.  Anchor: D*NoL*Vis walked down to the
    first node exactly three per-channel products multiply."""
    out, miss = [], []
    for a in alpha_sites(D, U):
        got = None
        for u in U.get(a['D'], []):
            p = fmul_pair(D, u)
            if not p:
                continue
            nol = other(p, a['D'])
            for v in U.get(u, []):
                q = fmul_pair(D, v)
                if not q:
                    continue
                dw = D.get(other(q, u))
                if dw and dw['op'] == 'OpFDiv' and \
                        dw['args'][0].startswith('%float_0_5') and \
                        is_op(D, dw['args'][1], 'OpFAdd', 2):
                    got = (v, nol, other(q, u))
        if not got:
            miss.append((a['D'], 'no D*NoL*Vis product'))
            continue
        specD, nol, vis = got
        cos = []
        for tm in D[D[vis]['args'][1]]['args']:
            p = fmul_pair(D, tm)
            sq = [x for x in (p or []) if (ext(D, x) or ('', ''))[0] == 'Sqrt']
            if not p or len(sq) != 1:
                cos = None
                break
            cos.append(other(p, sq[0]))
        if not cos or len(set(cos)) != 2 or nol not in cos:
            miss.append((a['D'], 'Vis is not the two-cosine Smith sum'))
            continue
        nov = cos[0] if cos[1] == nol else cos[1]
        best, seen, front = None, set(), [specD]
        while front:
            cur = front.pop()
            if cur in seen or len(seen) > 6000:
                continue
            seen.add(cur)
            for u in U.get(cur, []):
                front.append(u)
            ch = _chan3(D, U, cur)
            if ch and (best is None or D[cur]['line'] < D[best[0]]['line']):
                best = (cur, ch)
        if best is None:
            miss.append((a['D'], 'no scalar with three per-channel consumers'))
            continue
        out.append(dict(alpha=a['alpha'], a2=a['a2'], Dterm=a['D'],
                        class1=a['class1'], nol=nol, nov=nov, vis=vis,
                        specD=specD, S=best[0], chan=best[1],
                        line=D[best[0]]['line']))
    out.sort(key=lambda s: s['line'])
    return out, miss


def mnodes(D, root, depth=0):
    """Every node of an OpFMul tree, internal ones included."""
    out = {root}
    if depth > 12:
        return out
    p = fmul_pair(D, root)
    if p:
        for a in p:
            out |= mnodes(D, a, depth + 1)
    return out


def pair_lobes(D, U, dsite, ssites):
    """Match a diffuse site to the specular lobe of the same light, and name
    the Fresnel triple in the diffuse channels' own colour order.

    Each specular channel is `S * o`, with `o` either the Fresnel alone or
    `Fresnel * colour`.  The colour half is the one that also appears in a
    diffuse channel; the Fresnel half never does.  That is also the pairing:
    channel i of the diffuse site is the specular channel carrying the same
    colour.  Returns (ssite, F[3], lc[3]) or (None, None, None).
    """
    dm = [mnodes(D, c) for c in dsite['chan']]
    allm = set.union(*dm)
    for ss in sorted(ssites, key=lambda s: abs(s['line'] - dsite['line'])):
        bare = [other(fmul_pair(D, sc), ss['S']) for sc in ss['chan']]
        if not any(fmul_pair(D, o) for o in bare):
            # this lobe applies the light colour BELOW the per-channel split,
            # so there is no shared colour to pair on.  Both channel lists are
            # line-sorted and both are R,G,B, so the pairing is by order.
            if len(set(bare)) == 3:
                return ss, bare, [None, None, None]
            continue
        got, ok = {}, True
        for sc in ss['chan']:
            o = other(fmul_pair(D, sc), ss['S'])
            pr = fmul_pair(D, o)
            if pr is None:
                ok = False
                break
            ina, inb = pr[0] in allm, pr[1] in allm
            if ina == inb:
                ok = False
                break
            col = pr[0] if ina else pr[1]
            fre = pr[1] if ina else pr[0]
            hit = [i for i in range(3) if col in dm[i]]
            if len(hit) != 1 or hit[0] in got:
                ok = False
                break
            got[hit[0]] = (fre, col)
        if ok and len(got) == 3:
            F = [got[i][0] for i in range(3)]
            lc = [got[i][1] for i in range(3)]
            if len(set(F)) == 3:
                return ss, F, lc
    return None, None, None


def find_sites(src):
    D, lines = parse(src)
    U = users(D)
    dsites, dmiss = diffuse_sites(D, U)
    ssites, smiss = spec_sites(D, U)
    return dict(D=D, lines=lines, U=U), dict(
        alpha=alpha_sites(D, U), diffuse=dsites, spec=ssites,
        miss=dmiss + smiss)


if __name__ == '__main__':
    import collections
    tot = collections.Counter()
    paired = collections.Counter()
    for p in [a for a in sys.argv[1:] if not a.startswith('-')]:
        ctx, S = find_sites(open(p).read())
        D, U = ctx['D'], ctx['U']
        np_ = 0
        for ds in S['diffuse']:
            if pair_lobes(D, U, ds, S['spec'])[0]:
                np_ += 1
        tot['modules'] += 1
        tot['alpha'] += len(S['alpha'])
        tot['diffuse'] += len(S['diffuse'])
        tot['spec'] += len(S['spec'])
        tot['paired'] += np_
        for k in ('alpha', 'diffuse', 'spec'):
            if not len(S[k]):
                tot['MOD-NO-' + k] += 1
        if not np_:
            tot['MOD-NO-paired'] += 1
        if '-v' in sys.argv:
            print('%-18s alpha=%-3d diff=%-3d spec=%-3d paired=%-3d'
                  % (p.split('/')[-1][:16], len(S['alpha']), len(S['diffuse']),
                     len(S['spec']), np_))
    print(dict(tot))
