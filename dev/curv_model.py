#!/usr/bin/env python3
"""curv_model -- the offline numeric model behind handoff/109 (curvature-driven
skin scattering).  Nothing here touches SPIR-V; it is the arithmetic the
patcher emits, in float32, so every number quoted in 109 is generated rather
than asserted (the dev/band_model.py + dev/fuzz_model.py habit).

WHAT THE FEATURE IS
-------------------
Pre-integrated skin shading (Penner, SIGGRAPH 2011 "Pre-Integrated Skin
Shading") makes the width of the diffuse falloff and the size of the
terminator's red shift depend on the surface curvature 1/r: a nose wing, an
ear rim, a lip or a finger scatters wider and redder than a cheek or a
forehead, because the same few millimetres of dermal transport subtend a much
larger angle on a tight surface.

The shipped terminator bleed (97 sec 3.4, dev/patch_compute_skin.py) is

    w   = saturate(1 - NoL / W)^2 ,  W = 0.35  (a FIXED stylisation constant)
    m_R = 1 + k*0.336*w   m_G = 1   m_B = 1 - k*0.101*w
    then 78's luminance hold scales the whole triple by
    nsc = Y / max(Y + w*k*(0.2126*0.336*C_R - 0.0722*0.101*C_B), eps)

and 97 sec 3.4 says out loud why W is a constant: *"physically the band scales
with curvature * d"*, and curvature was not computable.  handoff/99 changed
that -- P is reconstructed in-module, in METRES (99 sec 10.8) -- so curvature
in physical 1/m is now a few dozen instructions away.

THE ESTIMATOR (Penner's length(fwidth(N))/length(fwidth(P)), by hand)
--------------------------------------------------------------------
Compute has no fwidth, so the neighbour taps are explicit:

    kappa_x = |N(x+1,y) - N(x,y)| / |P(x+1,y) - P(x,y)|      [1/m]
    kappa_y = |N(x,y+1) - N(x,y)| / |P(x,y+1) - P(x,y)|
    kappa   = (kappa_x + kappa_y) / 2
    kappa_c = clamp(kappa, KAPPA_MIN, KAPPA_MAX)             [0.5, 40] 1/m
    s       = clamp(1 + g*(kappa_c/KAPPA0 - 1), S_MIN, S_MAX)

THE MAPPING, AND WHY IT IS WRITTEN THIS WAY
-------------------------------------------
`s` is a *pivoted contrast* form, not a bare ratio, for three reasons:

  1. **g = 0 is exactly identity.**  s == 1 for every pixel, so the control
     rung emits nothing and rebuilds byte-for-byte -- the same discipline that
     makes `c1` at rho=1 bit-identical to vanilla (97 sec 3.2).
  2. **g = 1 is exactly the brief's `clamp(kappa/10, 0.3, 2.0)`.**  The pivot
     form collapses to it: 1 + 1*(k/10 - 1) = k/10.
  3. **KAPPA0 = 10 /m is a 10 cm radius -- a cheek.**  So the shipped
     stylisation constant W = 0.35 is preserved EXACTLY on the surface it was
     tuned on, and only tighter or flatter geometry moves.  `curv-hi` (g = 2)
     then doubles the excursion about that same fixed point instead of
     doubling the whole scale, which keeps the A/B one-variable: the cheek is
     the in-frame control in both rungs.

`s` then does two things to the band, and only two:

    W    -> W * s          the band gets wider in NoL   (patcher: bq /= s)
    w    -> w * s          the amplitude scales          (patcher: bw *= s)

Both are applied by rescaling ONE existing value each, so 78's luminance hold
-- which consumes the same `w` -- rescales with them and stays algebraically
exact.  See `luminance_hold_residual()`: for ANY s the held triple's luminance
error on its own basis is 0 to float32 rounding.  Consequence, stated as
strongly as it deserves: **under neutral light the curvature rung cannot
change any pixel's luminance at all.  It is a pure chromaticity + band-width
edit.**  Under tinted light it inherits 78 sec 4's residual (-2.9%..+4.3% at
the band floor) and that residual scales with s.

SILHOUETTE FALLBACK
-------------------
A depth discontinuity (a face against a wall, a hair strand over a cheek, the
screen edge where the +1 tap is out of bounds) makes |dP| enormous and kappa
meaningless.  The guard is on |dP|^2, compared against JUMP^2 = (5 cm)^2, with
OpFOrdLessThan so a NaN answers FALSE and falls back.  Fallback is s = 1.0 --
i.e. **exactly the shipped constant**, never 0 and never unclamped.

WHAT THE NUMBERS ARE WORTH
--------------------------
The normal G-buffer at `registers[1]+2` is A2B10G10R10_UNORM at 1280x720
(38 sec 1.1 table; 96 sec 5 decodes it as N*0.5+0.5).  10 bits gives an
angular quantisation of ~0.11 deg, so |dN| has a one-LSB floor near 0.002.
`noise_floor()` turns that into a kappa floor per pixel footprint.  It is
BELOW a cheek's kappa at close range but not by a large factor -- read the
table before believing any fine kappa distinction.

Run:  python3 dev/curv_model.py
"""
import math
import struct
import sys


def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


# ------------------------------------------------------------------ knobs
KAPPA0    = 10.0      # 1/m -- the pivot: a 10 cm radius, i.e. a cheek
KAPPA_MIN = 0.5       # 1/m -- a 2 m radius; flatter than any body part
KAPPA_MAX = 40.0      # 1/m -- a 25 mm radius; tighter is capped, see 109 sec 3
S_MIN     = 0.3
S_MAX     = 2.0
JUMP      = 0.05      # m -- neighbour |dP| above this is a silhouette
BAND_W    = 0.35      # the shipped stylisation constant (97 sec 3.4)
BLEED_K   = 1.0       # the shipped bleed_k
A_R, A_B  = 0.336, 0.101      # Jensen skin1 mfp differences (97 sec 3.4)
WR, WG, WB = 0.2126, 0.7152, 0.0722


def kappa_of_radius(r_m):
    return 1.0 / r_m


def scale(kappa, g=1.0, kappa0=KAPPA0, smin=S_MIN, smax=S_MAX,
          kmin=KAPPA_MIN, kmax=KAPPA_MAX):
    """The emitted mapping, in float32, instruction for instruction."""
    kc = f32(min(max(f32(kappa), kmin), kmax))
    q = f32(kc * f32(1.0 / kappa0))
    q = f32(q - 1.0)
    q = f32(q * g)
    q = f32(1.0 + q)
    return f32(min(max(q, smin), smax))


def band_w(nol, s=1.0, width=BAND_W):
    """The bleed's own w, with the width widened by s."""
    q = f32(nol * f32(f32(1.0 / width) / s))
    t = f32(min(max(f32(1.0 - q), 0.0), 1.0))
    return f32(t * t)


def band_edge_degrees(width):
    """How many degrees of arc from the terminator the band spans."""
    w = min(max(width, 0.0), 1.0)
    return 90.0 - math.degrees(math.acos(w))


def bleed_triple(nol, colour, s=1.0, k=BLEED_K, norm=1.0, width=BAND_W):
    """(m_R, m_G, m_B) exactly as the patched instructions compute them.

    `s` enters twice, and only twice: the band width (inside band_w) and the
    amplitude weight `ws`.  The luminance hold consumes the SAME `ws`, which
    is why the hold survives untouched.
    """
    w = band_w(nol, s, width)
    ws = f32(w * s)
    Cr, Cg, Cb = (f32(c) for c in colour)
    mR = f32(1.0 + f32(ws * f32(k * A_R)))
    mB = f32(1.0 - f32(ws * f32(k * A_B)))
    mG = 1.0
    if norm > 0.0:
        Y = f32(f32(f32(Cr * WR) + f32(Cg * WG)) + f32(Cb * WB))
        d = f32(f32(Cr * f32(norm * WR * A_R * k)) - f32(Cb * f32(norm * WB * A_B * k)))
        den = f32(max(f32(Y + f32(d * ws)), 9.99999975e-06))
        nsc = f32(Y / den)
        mR, mG, mB = f32(mR * nsc), f32(nsc), f32(mB * nsc)
    return mR, mG, mB


def luminance_hold_residual(colour, s, nol, k=BLEED_K, width=BAND_W):
    """Relative Rec.709 luminance error of the held triple on its own basis."""
    Cr, Cg, Cb = colour
    mR, mG, mB = bleed_triple(nol, colour, s=s, k=k, norm=1.0, width=width)
    Y0 = Cr * WR + Cg * WG + Cb * WB
    Y1 = Cr * mR * WR + Cg * mG * WG + Cb * mB * WB
    return (Y1 - Y0) / Y0 if Y0 else 0.0


def pixel_footprint_m(distance_m, v_res=720, vfov_deg=55.0, cos_slope=1.0):
    """Metres of surface per lighting texel at `distance_m`.

    Lighting is resolved at 1280x720 before DLSS (97 sec 1.5), so this is the
    footprint that actually feeds the estimator, not the display resolution.
    """
    return 2.0 * distance_m * math.tan(math.radians(vfov_deg) / 2.0) / v_res / max(cos_slope, 1e-3)


def noise_floor(footprint_m, bits=10, per_channel=True):
    """The kappa a perfectly flat surface reads because of normal quantisation.

    A2B10G10R10_UNORM: one LSB is 1/(2^bits - 1) on the [0,1] fetch, and the
    decode is normalize(fetch - 0.5), so the [-0.5, 0.5] raw half-range maps to
    a unit vector -- an LSB is 2/(2^bits - 1) in unit-normal units.  One
    channel ticking is the typical case; all three is the worst case.
    """
    lsb = 2.0 / (2 ** bits - 1)
    dn = lsb if per_channel else lsb * math.sqrt(3.0)
    return dn / footprint_m


ANATOMY = [
    # (name, radius in metres, note)
    ('flat chest / back',  0.60, 'flatter than the estimator floor'),
    ('forehead',           0.12, 'the flattest part of a face'),
    ('cheek  (the pivot)', 0.10, 'KAPPA0 is defined here'),
    ('jaw / chin',         0.05, ''),
    ('brow ridge',         0.03, ''),
    ('finger',             0.010, ''),
    ('nose wing',          0.008, ''),
    ('lip roll',           0.006, ''),
    ('ear helix rim',      0.003, 'tightest skin on a body'),
]


def _table(g):
    print()
    print('  kappa -> s  (g = %.1f, KAPPA0 = %.0f /m, clamps kappa [%.1f, %.0f], '
          's [%.1f, %.1f])' % (g, KAPPA0, KAPPA_MIN, KAPPA_MAX, S_MIN, S_MAX))
    print('  %-20s %7s %8s %8s %6s %8s %9s %8s' %
          ('feature', 'r (mm)', 'kappa', 'clamped', 's', 'band W', 'band deg',
           'peak R/G'))
    for name, r, note in ANATOMY:
        k = kappa_of_radius(r)
        kc = min(max(k, KAPPA_MIN), KAPPA_MAX)
        s = scale(k, g)
        W = BAND_W * s
        mR, mG, mB = bleed_triple(0.0, (0.62, 0.42, 0.36), s=s)
        print('  %-20s %7.0f %8.1f %8.1f %6.2f %8.3f %9.1f %8.4f' %
              (name, r * 1000, k, kc, s, W, band_edge_degrees(W), mR / mG))


def main():
    print('=' * 78)
    print('curv_model -- handoff/109, curvature-driven skin scattering')
    print('=' * 78)

    for g in (0.0, 1.0, 2.0):
        _table(g)

    print()
    print('  luminance hold under s (78 sec 2), skin colour (0.62,0.42,0.36),')
    print('  relative Rec.709 error on the diffuse basis:')
    print('  %8s %14s %14s %14s' % ('s', 'NoL=0.00', 'NoL=0.15', 'NoL=0.30'))
    for s in (0.3, 0.5, 1.0, 1.5, 2.0):
        row = [luminance_hold_residual((0.62, 0.42, 0.36), s, n)
               for n in (0.0, 0.15, 0.30)]
        print('  %8.2f %13.2e %13.2e %13.2e' % (s, *row))
    worst = max(abs(luminance_hold_residual(c, s, n))
                for c in ((1, 1, 1), (0.62, 0.42, 0.36), (0.9, 0.2, 0.1),
                          (0.05, 0.05, 0.05))
                for s in (0.3, 0.7, 1.0, 1.4, 2.0)
                for n in (0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7))
    print('  worst |relative luminance error| over 4 colours x 5 s x 7 NoL: %.2e'
          % worst)

    print()
    print('  chromaticity excursion at the band floor (NoL = 0), R/G and B/G')
    print('  -- these ratios are what `s` actually moves:')
    print('  %8s %10s %10s' % ('s', 'R/G', 'B/G'))
    for s in (0.3, 1.0, 2.0):
        mR, mG, mB = bleed_triple(0.0, (0.62, 0.42, 0.36), s=s)
        print('  %8.2f %10.4f %10.4f' % (s, mR / mG, mB / mG))

    print()
    print('  screen-space resolution of the estimator (1280x720 lighting, 55 deg vfov)')
    print('  %10s %12s %14s %14s %12s' %
          ('distance', 'footprint', 'kappa floor', 'kappa floor', 'cheek kappa'))
    print('  %10s %12s %14s %14s %12s' %
          ('(m)', '(mm/texel)', '1 LSB', 'sqrt(3) LSB', '(1/m)'))
    for d in (0.4, 0.7, 1.0, 2.0, 5.0, 10.0):
        fp = pixel_footprint_m(d)
        print('  %10.1f %12.3f %14.1f %14.1f %12.1f' %
              (d, fp * 1000, noise_floor(fp), noise_floor(fp, per_channel=False),
               10.0))

    print()
    print('  the same, at 60 deg grazing (footprint stretches by 1/cos):')
    for d in (0.7, 1.0):
        fp = pixel_footprint_m(d, cos_slope=0.5)
        print('    d = %.1f m: %.3f mm/texel, kappa floor %.1f /m'
              % (d, fp * 1000, noise_floor(fp)))

    print()
    print('  silhouette guard: JUMP = %.0f cm.  A neighbour tap is rejected when'
          % (JUMP * 100))
    print('  |dP| exceeds it.  Ratio of JUMP to the on-surface footprint:')
    for d in (0.4, 1.0, 5.0, 20.0, 50.0):
        fp = pixel_footprint_m(d)
        print('    d = %5.1f m: footprint %7.3f mm, guard fires at %6.1fx the '
              'footprint' % (d, fp * 1000, JUMP / fp))
    d_break = JUMP / (2.0 * math.tan(math.radians(55.0) / 2.0) / 720)
    print()
    print('  -> the guard sits ~86x above the step at arm\'s length and ~7x at 5 m,')
    print('     so it separates silhouettes from surfaces everywhere a face is')
    print('     legible.  It crosses the footprint at %.0f m: beyond that EVERY'
          % d_break)
    print('     skin pixel falls back to s = 1, i.e. to the shipped constant.')
    print('     That is a graceful degradation and it is deliberate -- skin at')
    print('     %.0f m is a handful of 720p texels and carries no terminator.'
          % d_break)
    print('     An out-of-bounds tap at the screen edge reads depth 0 (reverse-Z')
    print('     far plane), which puts P past the horizon and fires the guard too.')
    print()
    ok_ident = all(scale(k, 0.0) == 1.0 for k in
                   (0.0, 0.1, 0.5, 1.0, 7.3, 10.0, 40.0, 1e6))
    ok_brief = all(abs(scale(k, 1.0)
                       - min(max(min(max(k, KAPPA_MIN), KAPPA_MAX) / 10.0,
                                 S_MIN), S_MAX)) < 1e-6
                   for k in (0.2, 0.5, 1.0, 3.0, 7.0, 10.0, 13.0, 25.0, 40.0, 500.0))
    ok_lum = worst < 1e-6
    print('  identity check: g = 0 gives s == 1.0 for every kappa:', ok_ident)
    print('  brief check: g = 1 reproduces clamp(kappa/10, 0.3, 2.0):', ok_brief)
    print('  luminance check: the hold survives every s:', ok_lum)
    if not (ok_ident and ok_brief and ok_lum):
        sys.exit('curv_model: a self-check FAILED')


if __name__ == '__main__':
    main()
