#!/usr/bin/env python3
"""bump_model -- the offline numeric model behind handoff/115 (albedo-derived
micro-normal on skin).  Nothing here touches SPIR-V; it is the arithmetic
`dev/patch_bump.py` emits, in float32, so every number quoted in 115 is
generated rather than asserted (the curv_model / band_model habit).

WHAT THE FEATURE IS
-------------------
Pores are not in the BVH and never will be (33, 38 sec 0d), so no ray budget
creates a pore micro-shadow.  But the skin ALBEDO already carries the pores:
the texture artist painted them dark.  This turns that darkening into
geometry the lighting can respond to -- a height field h = H * L(albedo),
darker = deeper -- and tilts the shading normal by its tangential gradient:

    N' = normalize( N - H * grad_t L )          grad_t = tangential part

with the gradient taken by one-sided finite differences over the G-buffer at
+1 texel in screen x and y, converted to world metres by the same dP the
curvature estimator (109) already measures:

    gx = L(x+1,y) - L(x,y)        gy = L(x,y+1) - L(x,y)        [luma]
    dPx = P(x+1,y) - P            dPy = P(x,y+1) - P            [m]
    grad = gx/|dPx|^2 * dPx + gy/|dPy|^2 * dPy                  [luma/m]

The diffuse N.L, the specular N.H / N.V and the c1 term all read the same N,
so a pore darkens on its lit side, brightens on its far side, and BREAKS UP
THE OIL HIGHLIGHT -- which is what a real pore does and what the shipped
albedo micro-shadowing (44 sec 3.4, a scalar darkening) cannot do.

THE THREE SAFEGUARDS, AND WHY EACH ONE EXISTS
---------------------------------------------
1. THE BAND (edge kill).  A lip line, an eyebrow, a beard shadow or eyeliner
   is an albedo EDGE, not a pore.  Feeding it to a bump map is the classic
   albedo-to-normal artifact (a painted stripe reads as a ridge).  Per axis:

        w(g) = 1 - smoothstep(T0, T1, |g|)        g' = g * w(g)

   so a per-texel luma step below T0 passes, one above T1 is ignored.  Pores
   after texture filtering are 0.01-0.05 per texel; a lip edge is 0.15-0.4.

2. THE TILT CLAMP.  |H * grad_t| is capped at DMAX (tan of the maximum tilt)
   so a thin texel at grazing view, or a texture seam, cannot flip the
   normal.  DMAX = 0.5 is 26.6 degrees.

3. THE SILHOUETTE GUARD, verbatim from 109: |dP| > JUMP across a texel means
   the neighbour is a different surface, and the pixel falls back to N.
   OpFOrdLessThan is false for NaN, so an out-of-bounds tap (Vulkan returns
   zeros -> depth 0 -> P on the near plane -> |dP| huge) also falls back.

H = 0 is exactly identity: the control rung emits nothing.
"""
import math
import sys

import numpy as np

f32 = np.float32

# --- the knobs (115 sec 3) ---------------------------------------------------
HEIGHT = 0.010       # m per unit luma: a 0.02 luma pore across 1 mm = 11.3 deg
T0 = 0.05            # band: per-texel |dL| below this is a pore
T1 = 0.12            # band: per-texel |dL| above this is an albedo edge
DMAX = 0.5           # tilt clamp, tan(26.6 deg)
JUMP = 0.05          # m, the 109 silhouette guard
EPS = 1e-12          # divide floor on |dP|^2 and |d|^2


def fs(x):
    return f32(x)


def luma(rgb_sqrt):
    """Rec.709 luminance of an A2B10G10R10 sqrt-encoded albedo texel."""
    r, g, b = (fs(c) for c in rgb_sqrt)
    return fs(0.2126) * r * r + fs(0.7152) * g * g + fs(0.0722) * b * b


def band(g, t0=T0, t1=T1):
    """g' = g * (1 - smoothstep(t0, t1, |g|)), float32, as emitted."""
    g = fs(g)
    u = np.clip((abs(g) - fs(t0)) * fs(1.0 / (t1 - t0)), fs(0), fs(1))
    w = fs(1) - u * u * (fs(3) - fs(2) * u)
    return fs(g * w)


def bump(N, gx, gy, dPx, dPy, height=HEIGHT, t0=T0, t1=T1, dmax=DMAX,
         jump=JUMP, guard=True, use_band=True):
    """The emitted chain.  Returns (N', tilt_tan, valid)."""
    N = np.asarray(N, f32)
    dPx = np.asarray(dPx, f32)
    dPy = np.asarray(dPy, f32)
    qx, qy = fs(dPx @ dPx), fs(dPy @ dPy)
    if use_band:
        gx, gy = band(gx, t0, t1), band(gy, t0, t1)
    ix = fs(gx) / max(qx, fs(EPS))
    iy = fs(gy) / max(qy, fs(EPS))
    grad = ix * dPx + iy * dPy
    t = grad - fs(grad @ N) * N
    d = t * fs(-height)
    m2 = fs(d @ d)
    sc = min(fs(1), fs(dmax) / math.sqrt(max(m2, fs(EPS))))
    d = d * fs(sc)
    v = N + d
    nb = v / fs(math.sqrt(v @ v))
    valid = bool(qx < jump * jump and qy < jump * jump) if guard else True
    return (nb if valid else N), fs(math.sqrt(d @ d)), valid


def tilt_deg(N, Nb):
    c = float(np.clip(np.asarray(N, f32) @ np.asarray(Nb, f32), -1, 1))
    return math.degrees(math.acos(c))


def pixel_footprint_m(distance_m, v_res=720, vfov_deg=55.0):
    """Metres per lighting texel at a given distance, 720p internal."""
    return 2.0 * distance_m * math.tan(math.radians(vfov_deg / 2)) / v_res


def quant_step_luma(L):
    """One LSB of the 10-bit sqrt encoding, in linear luma, at luma L."""
    s = math.sqrt(max(L, 1e-6))
    return 2.0 * s / 1023.0


def self_check():
    N = np.array([0, 0, 1], f32)
    ex, ey = np.array([1e-3, 0, 0], f32), np.array([0, 1e-3, 0], f32)
    # 1. H = 0 is identity
    nb, mag, ok = bump(N, 0.03, -0.02, ex, ey, height=0.0)
    assert np.array_equal(nb, N) and mag == 0, 'H=0 is not identity'
    # 2. a reference pore: 0.02 luma over 1 mm at H=10 mm -> tan = 0.2
    nb, mag, ok = bump(N, 0.02, 0.0, ex, ey)
    assert abs(mag - 0.2) < 1e-4, mag
    assert abs(tilt_deg(N, nb) - math.degrees(math.atan(0.2))) < 0.01
    # gx > 0 means +x is BRIGHTER, so the height field h = H*L rises toward
    # +x and the normal of that slope leans back toward -x: the darker side.
    assert nb[0] < 0, 'sign: the normal must lean toward the darker side'
    # 3. an albedo edge (0.3 per texel) is killed by the band
    nb, mag, ok = bump(N, 0.3, 0.0, ex, ey)
    assert mag == 0 and np.array_equal(nb, N), 'the band did not kill an edge'
    # 4. the clamp: 0.05 luma over 0.3 mm would be tan 1.67 -> capped at DMAX
    nb, mag, ok = bump(N, 0.049, 0.0, ex * fs(0.3), ey * fs(0.3))
    assert abs(mag - DMAX) < 1e-5, mag
    # 5. the guard: a 6 cm jump falls back to N
    nb, mag, ok = bump(N, 0.02, 0.0, ex * fs(60), ey)
    assert not ok and np.array_equal(nb, N)
    # 6. grazing: the same luma step across a 5x longer dPx tilts 5x less
    _, m1, _ = bump(N, 0.02, 0.0, ex, ey)
    _, m5, _ = bump(N, 0.02, 0.0, ex * fs(5), ey)
    assert abs(m1 / m5 - 5) < 1e-3
    # 7. tangential: a gradient with a component along N leaves |N'| = 1
    nb, _, _ = bump(np.array([0.6, 0, 0.8], f32), 0.02, 0.01, ex, ey)
    assert abs(float(nb @ nb) - 1) < 1e-5
    return True


def table():
    print('  reference pore: dL = 0.02 luma/texel, H = %.0f mm/luma, band [%.2f, %.2f], clamp %.2f'
          % (HEIGHT * 1e3, T0, T1, DMAX))
    print('  %-9s %-11s %-9s %-11s %-9s' % ('dist m', 'texel mm', 'tilt deg', 'LSB noise', 'noise deg'))
    for dist in (0.3, 0.5, 0.7, 1.0, 2.0, 4.0):
        fp = pixel_footprint_m(dist)
        N = np.array([0, 0, 1], f32)
        ex, ey = np.array([fp, 0, 0], f32), np.array([0, fp, 0], f32)
        nb, mag, _ = bump(N, 0.02, 0.0, ex, ey)
        q = quant_step_luma(0.45)
        nq, mq, _ = bump(N, q, 0.0, ex, ey)
        print('  %-9.2f %-11.2f %-9.2f %-11.4f %-9.2f'
              % (dist, fp * 1e3, tilt_deg(N, nb), q, tilt_deg(N, nq)))
    print('  band: per-texel |dL| 0.02 -> w %.3f, 0.05 -> %.3f, 0.085 -> %.3f, 0.12 -> %.3f, 0.30 -> %.3f'
          % tuple(float(band(g)) / g for g in (0.02, 0.05, 0.085, 0.12, 0.30)))


def main():
    self_check()
    table()
    print('  bump_model self-check: PASS')


if __name__ == '__main__':
    main()
