#!/usr/bin/env python3
"""Closed form for handoff/95's sun-shadow transmittance, and the float32
emulation of the exact instruction sequence the patcher emits.

Two functions, deliberately written independently of each other:

  ideal(...)   the physics, in float64: airmass excess over zenith times the
               normalised exponential column at the shading point's height.
  emitted(...) the same number computed the way the SHADER computes it --
               Exp2/Log2 only, the NClamp on the column exponent, the NMax on
               the elevation cosine, the NMin on tau, every intermediate
               rounded to float32.

verify_volsun.py recovers the constants from the SHIPPED bytes, feeds them to
BOTH, and reports the worst relative error over a grid.  If the two ever
disagree by more than the float32 floor the build fails: that is the check
that the emitted instruction ORDER means what the doc says it means, not just
that the constants are the right numbers.
"""
import math, struct

LOG2E = 1.4426950408889634
LAMBDA = (610.0, 550.0, 465.0)


def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def channel_scales(a, p):
    return tuple(a * (LAMBDA[1] / L) ** p for L in LAMBDA)


def ideal(a_c, H, y0, h, cos_elev):
    """T_c for one channel. `cos_elev` is L . up, i.e. sin(sun elevation)."""
    col = math.exp(-(h - y0) / H)
    lu = max(cos_elev, 0.0)
    if lu <= 0.0:
        return 0.0
    am = max(1.0 / lu - 1.0, 0.0)
    return math.exp(-a_c * col * am)


def emitted(a2_c, B, y0, lu_min, tau_max2, exp_lim, h, cos_elev):
    """The shader's own sequence, float32 at every step.

    a2_c = A_c*log2(e);  B = -log2(e)/H;  tau_max2 = TAU_MAX*log2(e).
    """
    hy = f32(f32(h) - f32(y0))
    e0 = f32(hy * f32(B))
    e = f32(min(max(e0, f32(-exp_lim)), f32(exp_lim)))
    col = f32(2.0 ** e)
    lu = f32(max(f32(cos_elev), f32(lu_min)))
    inv = f32(1.0 / lu)
    am = f32(max(f32(inv - 1.0), 0.0))
    q = f32(col * am)
    t0 = f32(q * f32(a2_c))
    t1 = f32(min(t0, f32(tau_max2)))
    return f32(2.0 ** f32(-t1))


def grid(a, H, y0, p, lu_min=0.02, tau_max=30.0, exp_lim=40.0,
         heights=None, elevs=None):
    """The comparison grid: worst relative error between ideal and emitted.

    Elevations start at LU_MIN so the two forms are compared where they are
    both defined; below that the shader clamps by design and the ideal form
    diverges, which is the clamp doing its job rather than an error.
    """
    if heights is None:
        heights = [y0 + d for d in range(-200, 801, 10)]
    if elevs is None:
        elevs = [lu_min + i * (1.0 - lu_min) / 199.0 for i in range(200)]
    ac = channel_scales(a, p)
    worst, at = 0.0, None
    for c in range(3):
        a2 = ac[c] * LOG2E
        for h in heights:
            for mu in elevs:
                want = ideal(ac[c], H, y0, h, mu)
                got = emitted(a2, -LOG2E / H, y0, lu_min, tau_max * LOG2E,
                              exp_lim, h, mu)
                if want < 1e-9 and got < 1e-9:      # both in the tau-clamp tail
                    continue
                rel = abs(got - want) / max(want, 1e-12)
                if rel > worst:
                    worst, at = rel, (c, h, mu, want, got)
    return worst, at, len(heights) * len(elevs) * 3


if __name__ == '__main__':
    import argparse, json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--a', type=float, default=0.25)
    ap.add_argument('--h', dest='H', type=float, default=120.0)
    ap.add_argument('--y0', type=float, default=20.0)
    ap.add_argument('--p', type=float, default=1.0)
    ap.add_argument('--table', action='store_true',
                    help='print T at y0 and y0+50 m over a sun-elevation sweep')
    a = ap.parse_args()
    w, at, n = grid(a.a, a.H, a.y0, a.p)
    print(json.dumps({"a": a.a, "H": a.H, "y0": a.y0, "p": a.p,
                      "points": n, "worst_rel_err": w, "at": at}))
    if a.table:
        ac = channel_scales(a.a, a.p)
        print(f"  elev |   T(y={a.y0:g} m) R/G/B    |   T(y={a.y0+50:g} m) R/G/B  | G ratio")
        for deg in (60, 45, 30, 20, 15, 10, 5):
            mu = math.sin(math.radians(deg))
            lo = [ideal(ac[c], a.H, a.y0, a.y0, mu) for c in range(3)]
            hi = [ideal(ac[c], a.H, a.y0, a.y0 + 50.0, mu) for c in range(3)]
            print(f"  {deg:4d} | {lo[0]:.3f} {lo[1]:.3f} {lo[2]:.3f} "
                  f"| {hi[0]:.3f} {hi[1]:.3f} {hi[2]:.3f} | {hi[1]/lo[1]:.2f}x")
