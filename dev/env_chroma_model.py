#!/usr/bin/env python3
"""84: offline amplitude model for the ENVIRONMENT chroma bleed.

The same operator dev/patch_gi_env.py emits, in numpy, so the ladder can be
calibrated without building anything:

    Y     = w . C                     (Rec.709)
    r_c   = C_c / Y
    g_c   = (1-q) + q*r_c
    n     = sum_j w_j*r_j*g_j
    out_c = C_c * g_c / n             (luminance held exactly)

Reported per scene: saturation (max-min)/max before and after, the chroma
gain, the |luma error|, and the per-channel gain. Then the worst-case
per-channel amplification over 200k random colours -- the number that has to
stay under the shader's GMAX = 16 clamp, and that the shipped-bytes verifier
(dev/verify_env_chroma.py) independently re-measures on the real modules.

    ./dev/env_chroma_model.py                 # the ladder plus 0.25 / 0.5 / 1.0
    ./dev/env_chroma_model.py --q 0.35 0.7
"""
import argparse
import numpy as np

W = np.array([0.2126, 0.7152, 0.0722])

# albedo x incoming radiance chroma -- the product is what the write triple
# carries, which is the whole point of the site (see 84 sec 1).
CASES = {
    'magenta neon on concrete': ([0.20, 0.19, 0.18], [1.00, 0.15, 0.60]),
    'cyan neon on concrete':    ([0.20, 0.19, 0.18], [0.20, 0.85, 1.00]),
    'sodium street on asphalt': ([0.10, 0.10, 0.10], [1.00, 0.70, 0.40]),
    'white bounce on red wall': ([0.35, 0.09, 0.08], [1.00, 1.00, 1.00]),
    'near-neutral daylight':    ([0.25, 0.25, 0.25], [1.00, 0.98, 1.05]),
}


def env(C, q):
    C = np.asarray(C, float)
    Y = float(W @ C)
    u = C * ((1.0 - q) * Y + q * C)      # C*g_c, up to the Y that cancels
    return u * (Y / max(float(W @ u), 1e-12)), Y


def sat(C):
    C = np.asarray(C, float)
    m = C.max()
    return 0.0 if m <= 0 else (m - C.min()) / m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--q', type=float, nargs='+',
                    default=[0.25, 0.35, 0.50, 0.70, 1.00])
    ap.add_argument('--points', type=int, default=200000)
    a = ap.parse_args()

    for q in a.q:
        print("q=%.2f" % q)
        for name, (alb, rad) in CASES.items():
            C = np.array(alb) * np.array(rad)
            o, Y = env(C, q)
            s0, s1 = sat(C), sat(o)
            print("   %-26s sat %.3f -> %.3f  (x%.2f)  lumaerr %.2e  ch gain %s"
                  % (name, s0, s1, (s1 / s0 if s0 > 0 else 1.0),
                     abs(float(W @ o) - Y) / Y,
                     np.round(o / np.maximum(C, 1e-12), 3)))

    rng = np.random.default_rng(0)
    for q in a.q:
        C = rng.random((a.points, 3)) ** 3
        Y = C @ W
        u = C * (((1 - q) * Y)[:, None] + q * C)
        o = u * (Y / np.maximum(u @ W, 1e-30))[:, None]
        print("q=%.2f  max per-channel gain %.4f   max luma rel err %.2e"
              % (q, (o / np.maximum(C, 1e-30)).max(),
                 np.abs((o @ W) - Y).max() / Y.max()))


if __name__ == '__main__':
    main()
