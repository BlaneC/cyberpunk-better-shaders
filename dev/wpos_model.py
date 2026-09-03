#!/usr/bin/env python3
"""wpos_model -- an INDEPENDENT float32 model of the hunt-wpos pattern.

Written from handoff/99's description, not from patch_wpos.py's code, so that
`dev/verify_wpos.py`'s closed-form gate compares two separate implementations
(95 sec 7 G5 / 94 sec 10).  Everything is float32/uint32 exactly as the shader
computes it.
"""
import numpy as np

HASH_K = (np.uint32(73856093), np.uint32(19349663), np.uint32(83492791))
AVAL_M = np.uint32(668265261)
BIAS = np.float32(65536.0)


def _f32(x):
    return np.asarray(x, dtype=np.float32)


def pattern(P, cell=1.0, lo=0.15, hi=3.00, stripe=0.35, up=2,
            mode='hash', stripe_on=True):
    """P: (3, N) float array of surface positions -> (3, N) RGB multipliers."""
    P = _f32(P)
    inv = np.float32(np.float32(1.0) / np.float32(cell))
    lo = np.float32(lo)
    span = np.float32(np.float32(hi) - lo)
    t = _f32(P * inv)
    if mode == 'frac':
        f = _f32(t - np.floor(t))
        return _f32(span * f + lo)
    q = _f32(np.floor(t))
    n = (q + BIAS).astype(np.uint32)
    h = np.uint32(0)
    acc = None
    for k in range(3):
        m = (n[k] * HASH_K[k]).astype(np.uint32)
        acc = m if acc is None else np.bitwise_xor(acc, m).astype(np.uint32)
    h = acc
    h = np.bitwise_xor(h, np.right_shift(h, np.uint32(15))).astype(np.uint32)
    h = (h * AVAL_M).astype(np.uint32)
    h = np.bitwise_xor(h, np.right_shift(h, np.uint32(15))).astype(np.uint32)
    out = []
    for k in range(3):
        by = np.bitwise_and(np.right_shift(h, np.uint32(8 * k)),
                            np.uint32(255)).astype(np.uint32)
        tt = _f32(by.astype(np.float32) * np.float32(np.float32(1.0) / np.float32(255.0)))
        out.append(_f32(span * tt + lo))
    rgb = np.stack(out)
    if stripe_on:
        odd = np.bitwise_and(n[up], np.uint32(1))
        s = np.where(odd == 0, np.float32(1.0), np.float32(stripe)).astype(np.float32)
        rgb = _f32(rgb * s)
    return rgb


def gained(v, gain):
    """The patcher lerps every palette endpoint from 1.0 by `gain`.

    Done in Python float64 and rounded ONCE, exactly as patch_wpos.build's
    `g()` -> `mod.const()` does; rounding to float32 first would put the
    constant a ulp away and the byte-exact palette check would fail.
    """
    return np.float32(1.0 + float(gain) * (float(v) - 1.0))
