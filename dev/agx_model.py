#!/usr/bin/env python3
"""
agx_model.py -- a Python mirror of what patch_agx.py emits, for checking a
look offline instead of spending a launch on it.

It imports the constants and DEFAULTS from patch_agx, so the two cannot drift:
if the emitted maths changes, change `agx()` here to match.

    ./dev/agx_model.py                       # ladder for the default knobs
    ./dev/agx_model.py --look punchy70 --set pre_gain=0.5 --set hue_restore=0.6

`pre_gain` is the knob that matters after handoff/20: `grade=1` feeds AgX the
graded colour times the game's own cbv[42].z exposure, whose runtime value we
cannot read offline.  Sweep pre_gain here to see how far the look moves for a
given exposure before deciding what to build.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_agx import (AGX_IN, AGX_OUT, SIGMOID, REC709_TO_AP1, LUMA,
                       DEFAULTS, LOOKS)


def _mv(m, v):
    return [sum(m[r][c] * v[c] for c in range(3)) for r in range(3)]


def _luma(v):
    return sum(LUMA[i] * v[i] for i in range(3))


def agx(lin, k, clamp_in=True, post=None):
    """The same order of operations as build_agx()."""
    if clamp_in:
        lin = [max(c, 0.0) for c in lin]
    if k['pre_gain'] != 1.0:
        lin = [c * k['pre_gain'] for c in lin]
    v = _mv(AGX_IN, lin)

    lo, hi = k['min_ev'], k['max_ev']
    import math
    enc = [(min(max(math.log2(max(c, 1e-10)), lo), hi) - lo) / (hi - lo)
           for c in v]

    sig = []
    for x in enc:
        acc = SIGMOID[0]
        for co in SIGMOID[1:]:
            acc = acc * x + co
        sig.append(acc)

    slopes = (k['slope_r'], k['slope_g'], k['slope_b'])
    neutral_gain = all(s == 1.0 for s in slopes) and k['offset'] == 0.0
    if not neutral_gain or k['power'] != 1.0:
        tmp = []
        for c, s in zip(sig, slopes):
            x = c if neutral_gain else c * s + k['offset']
            x = max(x, 0.0)
            if k['power'] != 1.0:
                x = x ** k['power']
            tmp.append(x)
        sig = tmp
    if k['sat'] != 1.0:
        l = _luma(sig)
        sig = [(c - l) * k['sat'] + l for c in sig]

    if k['hue_restore'] > 0.0:
        lv = max(_luma(v), 1e-6)
        ls = _luma(sig)
        w = min(max(k['hue_restore'] * ls * ls, 0.0), 1.0)
        sig = [c + (min(max(ls * ci / lv, 0.0), 1.0) - c) * w
               for c, ci in zip(sig, v)]

    out = _mv(AGX_OUT, sig)
    if k['eotf'] > 0.0:
        out = [max(c, 0.0) ** k['eotf'] for c in out]
    else:
        out = [min(max(c, 0.0), 1.0) for c in out]
    tints = (k['tint_r'], k['tint_g'], k['tint_b'])
    if any(t != 1.0 for t in tints):
        out = [c * t for c, t in zip(out, tints)]
    if post is not None:
        out = _mv(post, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--look', choices=sorted(LOOKS), default='none')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    ap.add_argument('--ap1', action='store_true',
                    help='also apply the Rec.709 -> AP1 post matrix (--site ap1)')
    a = ap.parse_args()
    k = dict(DEFAULTS); k.update(LOOKS[a.look])
    for kv in a.set:
        key, _, val = kv.partition('=')
        k[key] = float(val)
    post = REC709_TO_AP1 if a.ap1 else None

    print(f"look={a.look} " + " ".join(f"{x}={k[x]}" for x in
          ('power', 'sat', 'pre_gain', 'hue_restore', 'eotf')))
    print(f"{'input':>22}  ->  output")
    cases = [(0.0, 0.0, 0.0), (0.05, 0.05, 0.05), (0.18, 0.18, 0.18),
             (1.0, 1.0, 1.0), (4.0, 4.0, 4.0), (16.0, 16.0, 16.0),
             (4.0, 0.02, 0.02), (8.0, 6.0, 3.0), (12.0, 9.0, 4.0)]
    for c in cases:
        o = agx(list(c), k, post=post)
        chroma = max(o) - min(o)
        print("  (%6.2f,%6.2f,%6.2f)  ->  (%6.4f,%6.4f,%6.4f)  chroma %.4f"
              % (c + tuple(o) + (chroma,)))


if __name__ == '__main__':
    main()
