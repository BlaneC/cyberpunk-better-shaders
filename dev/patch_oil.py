#!/usr/bin/env python3
"""oilhi -- retune 72's skin coat on top of the shipped default.

handoff/118.  The smallest patcher in the tree: it adds no instructions and
no control flow.  72's Fresnel reshape is already spliced into every compute
resolver; its shape is fixed and its STRENGTH is two baked OpConstants:

    sv  = NClamp(VoH, 0, 1)
    b   = 1 - sv
    bm  = NMax(b, 1e-4)
    l   = Log2(bm)
    xe  = l * P             <-- P = 5r, the exponent          (shipped 4.5)
    pr  = Exp2(xe)                 = (1-VoH)^P
    s2r = NClamp(C, 0, 1)   <-- C = 2 - r                     (shipped 1.1)
    amp = s2r * G           <-- G = spec_gain, the amplitude  (shipped 1.0)
    ---- per channel c in {R,G,B} ----
    t1  = X_c * pr                 X_c = 1 - f0_c
    t2  = t1 * amp
    fp  = f0_c + t2
    fc  = NMin(fp, 1)
    F'  = select(skin, fc, F_c)

C only ever reaches the shader through NClamp(C, 0, 1), and every oil rung on
the ladder has C = 2 - 2(1 - n_s) >= 1 for n_s >= 0.5, so `sat(2-r)` has been
pinned at 1.0 for the entire life of the feature and G alone is the amplitude.
`--c2mr` exists to SHOOT that claim (the `oil-inert` decoy): move C anywhere in
[1, 2] and the bytes change while the screen must not.

This patcher rewrites operands of instructions that are already there.  It
never inserts, never deletes, never touches a use outside the two lines it
names, and with the shipped values it is a byte-exact no-op -- which is the
`oil-ctl` rung and the control the A/B rests on.

NOTHING is found by name or by id.  A group is only a group if the whole
chain above matches, the three channels agree on one `amp`, and all three
`OpSelect`s agree on one gate.  A module that does not match is reported and
left alone, never guessed at.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
import patch_compute_skin as CS
import brdf_sites as BS
import oil_model as OM


class NoGroup(Exception):
    pass


def _need(c, m):
    if not c:
        raise NoGroup(m)


def find_oil_groups(mod):
    """Every 72 Fresnel reshape in the module, anchored on its Exp2."""
    src = '\n'.join(mod.lines)
    D, _ = BS.parse(src)
    U = BS.users(D)
    groups, declined = [], []
    for rid, d in sorted(D.items(), key=lambda kv: kv[1]['line']):
        e = BS.ext(D, rid)
        if not e or e[0] != 'Exp2':
            continue
        try:
            groups.append(_group(D, U, rid, e[1][0]))
        except NoGroup as ex:
            declined.append('%s: %s' % (rid, ex))
    return groups, declined, D


def _group(D, U, pr, xe):
    # ---- the power: xe = l * P, l = Log2(NMax(1 - NClamp(voh,0,1), eps))
    q = BS.fmul_pair(D, xe)
    _need(q, 'Exp2 arg is not an OpFMul')
    ls = [x for x in q if (BS.ext(D, x) or ('', ))[0] == 'Log2']
    _need(len(ls) == 1, 'no unique Log2 under the exponent')
    l = ls[0]
    P = BS.other(q, l)
    bm = BS.ext(D, l)[1][0]
    em = BS.ext(D, bm)
    _need(em and em[0] == 'NMax' and len(em[1]) == 2, 'Log2 arg is not an NMax')
    b = em[1][0]
    _need(BS.is_op(D, b, 'OpFSub', 2), 'NMax arg is not an OpFSub')
    sv = D[b]['args'][1]
    sm = BS.ext(D, sv)
    _need(sm and sm[0] == 'NClamp', '1 - x where x is not an NClamp')
    voh = sm[1][0]

    # ---- the three channels, which must agree on one amp
    t1s = [u for u in U.get(pr, []) if BS.fmul_pair(D, u)]
    _need(len(t1s) == 3, 'the power feeds %d products, not 3' % len(t1s))
    amps, t2s = set(), []
    for t1 in t1s:
        up = [u for u in U.get(t1, []) if BS.fmul_pair(D, u)]
        _need(len(up) == 1, 'a channel product has %d consumers' % len(up))
        t2s.append(up[0])
        amps.add(BS.other(BS.fmul_pair(D, up[0]), t1))
    _need(len(amps) == 1, 'the three channels do not share one amplitude')
    amp = amps.pop()

    # ---- the amplitude: amp = NClamp(C, 0, 1) * G
    qa = BS.fmul_pair(D, amp)
    _need(qa, 'the amplitude is not an OpFMul')
    ss = [x for x in qa if (BS.ext(D, x) or ('', ))[0] == 'NClamp']
    _need(len(ss) == 1, 'no unique NClamp in the amplitude')
    s2r = ss[0]
    G = BS.other(qa, s2r)
    C = BS.ext(D, s2r)[1][0]

    # ---- the tail: f0 + t2 -> NMin(.,1) -> select(gate, ., F), one gate
    gates, chans = set(), []
    for t2 in t2s:
        ad = [u for u in U.get(t2, []) if BS.is_op(D, u, 'OpFAdd', 2)]
        _need(len(ad) == 1, 'a channel sum has %d consumers' % len(ad))
        fp = ad[0]
        nm = [u for u in U.get(fp, [])
              if (BS.ext(D, u) or ('', ))[0] == 'NMin']
        _need(len(nm) == 1, 'no unique NMin over a channel')
        fc = nm[0]
        se = [u for u in U.get(fc, []) if BS.is_op(D, u, 'OpSelect', 3)]
        _need(len(se) == 1, 'no unique OpSelect over a channel')
        gates.add(D[se[0]]['args'][0])
        chans.append(dict(t1=None, t2=t2, fp=fp, fc=fc, sel=se[0]))
    _need(len(gates) == 1, 'the three channels do not share one gate')

    return dict(pr=pr, xe=xe, P=P, amp=amp, G=G, s2r=s2r, C=C, voh=voh,
                gate=gates.pop(), chans=chans,
                p_line=D[xe]['line'], g_line=D[amp]['line'],
                c_line=D[s2r]['line'], line=D[pr]['line'])


def _swap(mod, line, old, new):
    """Replace ONE operand token on ONE line.  Never a global rewrite."""
    ln = mod.lines[line]
    head, _, rest = ln.partition('=')
    toks = rest.split()
    hits = [i for i, t in enumerate(toks) if t == old]
    if len(hits) != 1:
        die('operand %s appears %d times on `%s`' % (old, len(hits), ln.strip()))
    toks[hits[0]] = new
    mod.lines[line] = head + '= ' + ' '.join(toks)


def build_oil(mod, knobs):
    groups, declined, D = find_oil_groups(mod)
    rep = dict(groups=len(groups), declined=declined, chans=0,
               p_written=0, g_written=0, c_written=0, shipped=[])
    if not groups:
        return [], [], rep
    consts = []

    def K(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def fval(idtok):
        d = D.get(idtok)
        if d is None:
            _, t = mod.find_def(idtok)
            d = dict(text='%s = %s' % (idtok, t or ''))
        t = d['text']
        return float(t.split('OpConstant %float')[1].strip()) \
            if 'OpConstant %float' in t else None

    for g in groups:
        rep['chans'] += len(g['chans'])
        p0, g0, c0 = fval(g['P']), fval(g['G']), fval(g['C'])
        rep['shipped'].append(dict(p=p0, g=g0, c=c0))
        # The shipped values are asserted, not assumed: a base whose coat is
        # not (4.5, 1.0, 1.1) is a different build and this rung's arithmetic
        # would silently mean something else.
        if knobs['assert_base']:
            for nm, got, want in (('P', p0, OM.P_SHIP), ('G', g0, OM.G_SHIP),
                                  ('C', c0, 1.10000002)):
                if got is None or abs(got - want) > 1e-5:
                    die('%s: coat %s is %r, expected %r -- wrong base'
                        % (mod.name, nm, got, want))
        for key, cur, idtok, line, ctr in (
                ('p', p0, g['P'], g['p_line'], 'p_written'),
                ('g', g0, g['G'], g['g_line'], 'g_written'),
                ('c', c0, g['C'], g['c_line'], 'c_written')):
            want = knobs[key]
            if want is None or (cur is not None and abs(cur - want) < 1e-9):
                continue
            _swap(mod, line, idtok, K(want))
            rep[ctr] += 1
    return consts, [], rep


def process(path, outdir, knobs, do_rt=True):
    target_env = detect_target_env(path)
    mod, problems = load_lenient(path)
    if not mod.ident:
        die('%s: no dxil identity' % os.path.basename(path))
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, dxil=mod.dxil)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['oil'] = build_oil(mod, knobs)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('-p', type=float, default=None,
                    help='the Schlick exponent 5r (shipped 4.5)')
    ap.add_argument('-g', type=float, default=None,
                    help='spec_gain, the amplitude (shipped 1.0)')
    ap.add_argument('--c2mr', type=float, default=None,
                    help='DECOY: 2-r, which NClamp(.,0,1) pins at 1 for every '
                         'oil rung -- moving it inside [1,2] must not move a '
                         'pixel')
    ap.add_argument('--rung', choices=sorted(OM.RUNGS),
                    help='name a rung instead of spelling -p/-g')
    ap.add_argument('--no-assert-base', action='store_true',
                    help='do not require the base to carry the shipped coat')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    p, gg = a.p, a.g
    if a.rung:
        if p is not None or gg is not None:
            die('--rung and -p/-g are exclusive')
        p, gg = OM.RUNGS[a.rung]
    if p is not None and not (0.5 <= p <= 8.0):
        die('exponent out of range')
    if gg is not None and not (0.25 <= gg <= 3.0):
        die('gain out of range')
    if a.c2mr is not None and not (0.0 <= a.c2mr <= 2.0):
        die('c2mr out of range')
    knobs = dict(p=p, g=gg, c=a.c2mr, assert_base=not a.no_assert_base)
    reps = [process(x, a.outdir, knobs, do_rt=not a.no_roundtrip_check)
            for x in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
