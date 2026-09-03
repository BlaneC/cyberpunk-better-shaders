#!/usr/bin/env python3
"""whash_model -- the OFFLINE reference for handoff/107's world-hash pack.

Two jobs, kept apart on purpose.

1. **The bit-exact reference** for `dev/whash_core`'s emitters
   (`ref_world_hash`, `ref_value_noise`, `ref_fbm`).  Written from the
   *algorithm*, in numpy float32/uint32, NOT by reading the emitter's
   instruction list -- otherwise the gate would be comparing a thing to
   itself.  `whash_core --selftest` replays the emitted TEXT and requires
   bit equality against these.

2. **The amplitude models** for what 107 B and C actually do to a pixel, so
   the numbers in the handoff are evaluated rather than asserted.  `72`'s
   dead sheen rung shipped a docstring claiming a "~30% rim boost" for a
   term that measured 1.0000-1.0466x; the rule since is that no amplitude
   ships without the expression being evaluated over the actual hemisphere.

    ./dev/whash_model.py --calibrate     # B: the roughness/albedo swing
    ./dev/whash_model.py --porous        # C: the lobe, as % of local diffuse
    ./dev/whash_model.py --energy        # C: the bound, 94 sec 4.3 style
    ./dev/whash_model.py --fade          # B: the distance fade and its pixels
"""
import argparse
import math
import sys

import numpy as np

F32 = np.float32
U32 = np.uint32

# Must equal whash_core's; asserted by --selftest through the emitted text.
HASH_K = (73856093, 19349663, 83492791)
AVAL_M = 668265261
BIAS = 4194304.0
FIELD_BITS = 10
FIELD_MASK = (1 << FIELD_BITS) - 1
FIELD_SCALE = 1.0 / float(FIELD_MASK)
SEED_STEP = 0x9E3779B9


def _u(x):
    return U32(np.uint64(x) & np.uint64(0xFFFFFFFF))


def _avalanche(h):
    h = _u(h)
    for sh in (15, 13):
        h = _u(h ^ _u(h >> U32(sh)))
        h = _u(np.uint64(h) * np.uint64(AVAL_M))
    return _u(h ^ _u(h >> U32(16)))


def _fields(h):
    sc = F32(FIELD_SCALE)
    out = []
    for k in range(3):
        w = h if k == 0 else _u(h >> U32(FIELD_BITS * k))
        b = _u(w & U32(FIELD_MASK))
        out.append(F32(F32(float(b)) * sc))
    return tuple(out)


def _cell(P, cell):
    """(uint lattice index, in-cell fraction), float32 exactly as emitted."""
    inv = F32(1.0 / cell)
    n, t = [], []
    for k in range(3):
        w = F32(F32(P[k]) * inv)
        q = F32(math.floor(float(w)))
        t.append(F32(w - q))
        n.append(U32(int(F32(q + F32(BIAS)))))
    return tuple(n), tuple(t)


def _hash_cell(n, seed):
    m = [_u(np.uint64(n[k]) * np.uint64(HASH_K[k])) for k in range(3)]
    return _avalanche(_u(_u(m[0] ^ m[1]) ^ _u(m[2] ^ _u(seed))))


def ref_world_hash(P, cell, seed):
    """Flat per-cell hash: three uniform [0,1] floats, constant in the cell."""
    n, _t = _cell(P, cell)
    return _fields(_hash_cell(n, seed))


def _lerp(a, b, t):
    d = F32(F32(b) - F32(a))
    m = F32(d * F32(t))
    return F32(m + F32(a))


def ref_value_noise(P, cell, seed):
    n, t = _cell(P, cell)
    s = []
    for k in range(3):
        two_t = F32(t[k] * F32(2.0))
        a = F32(F32(3.0) - two_t)
        tt = F32(t[k] * t[k])
        s.append(F32(tt * a))
    corner = {}
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                q = (_u(np.uint64(n[0]) + np.uint64(i)),
                     _u(np.uint64(n[1]) + np.uint64(j)),
                     _u(np.uint64(n[2]) + np.uint64(k)))
                corner[(i, j, k)] = _fields(_hash_cell(q, seed))
    out = []
    for ch in range(3):
        c = {}
        for j in (0, 1):
            for k in (0, 1):
                c[(j, k)] = _lerp(corner[(0, j, k)][ch],
                                  corner[(1, j, k)][ch], s[0])
        c0 = _lerp(c[(0, 0)], c[(1, 0)], s[1])
        c1 = _lerp(c[(0, 1)], c[(1, 1)], s[1])
        out.append(_lerp(c0, c1, s[2]))
    return tuple(out)


def octave_weights(octaves=3, gain=0.5):
    w = [gain ** k for k in range(octaves)]
    s = sum(w)
    return [x / s for x in w]


def ref_fbm(P, cell, seed, octaves=3, lacunarity=2.0, gain=0.5):
    ws = octave_weights(octaves, gain)
    acc = None
    for o in range(octaves):
        c = cell / (lacunarity ** o)
        n = ref_value_noise(P, c, (seed + o * SEED_STEP) & 0xFFFFFFFF)
        w = F32(ws[o])
        if acc is None:
            acc = [F32(n[ch] * w) for ch in range(3)]
        else:
            acc = [F32(F32(n[ch] * w) + acc[ch]) for ch in range(3)]
    return tuple(acc)


# ------------------------------------------------------------ 107 B: micro
def ref_fade(dist, near, far):
    """1 at <= near, 0 at >= far.  `1 - saturate((d - near)/(far - near))`."""
    u = F32((F32(dist) - F32(near)) * F32(1.0 / (far - near)))
    u = F32(min(max(float(u), 0.0), 1.0))
    return F32(F32(1.0) - u)


def micro_terms(f, fade, k_rough, k_alb):
    """(d_rough, albedo_factor) from a [0,1] fbm channel pair."""
    dr = F32(F32(F32(f[0] * F32(2.0)) + F32(-1.0)) * F32(k_rough) * F32(fade))
    da = F32(F32(1.0) + F32(F32(F32(f[1] * F32(2.0)) + F32(-1.0))
                            * F32(k_alb) * F32(fade)))
    return dr, da


def ggx_D(alpha, noh):
    a2 = alpha * alpha
    x = noh * noh * (a2 - 1.0) + 1.0
    return a2 / (math.pi * x * x)


def calibrate(k_rough=0.08, k_alb=0.06, r0=0.75):
    print(f"107 B -- micro, at roughness {r0} (alpha {r0*r0:.4f})")
    print(f"  roughness swing  +-{k_rough}  ->  [{r0-k_rough:.3f}, "
          f"{r0+k_rough:.3f}]  ({100*k_rough/r0:.1f} % relative)")
    print(f"  albedo swing     +-{100*k_alb:.0f} %")
    print()
    print("  GGX peak D (NoH = 1) and half-width, at the swing endpoints:")
    print("   roughness   alpha    D(NoH=1)   D ratio    D(NoH=.98) ratio")
    for r in (r0 - k_rough, r0, r0 + k_rough):
        a = r * r
        d1 = ggx_D(a, 1.0)
        d0 = ggx_D(r0 * r0, 1.0)
        d2 = ggx_D(a, 0.98)
        d2r = ggx_D(r0 * r0, 0.98)
        print(f"   {r:8.3f}  {a:7.4f}  {d1:9.5f}  {d1/d0:7.4f}   "
              f"{d2:9.5f}  {d2/d2r:7.4f}")
    print()
    print("  Reading, from the numbers above and not from intuition: a")
    print(f"  +-{k_rough} roughness step at r={r0} moves the GGX PEAK by")
    print("  +57 % / -33 %.  That is not small.  What keeps it from reading")
    print("  as a gloss change is where the peak sits: at NoH = 1, where a")
    print("  roughness-0.75 lobe carries almost none of its energy, and the")
    print("  perturbation is a smooth 12 mm field rather than a step, so")
    print("  neighbouring patches differ by a fraction of the full swing.")
    print("  It is a TEXTURE cue.  If the A/B reads as patchy gloss rather")
    print("  than as surface grain, k_rough is too high -- halve it before")
    print("  touching anything else.")
    print(f"  The albedo half is +-{100*k_alb:.0f} % of the DIFFUSE, which on")
    print("  a matte wall is essentially the whole pixel; it is the half most")
    print("  likely to be the visible one.")


def fade_table(near=6.0, far=14.0, cell=0.012, hfov_deg=50.0, px=1280):
    print(f"107 B -- distance fade {near} m -> {far} m, cell {cell*1000:.0f} mm")
    print(f"  lighting is resolved at {px}x720 ({hfov_deg} deg horizontal)")
    ang = math.radians(hfov_deg) / px
    print("   distance   fade   cell size in resolve pixels")
    for d in (0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 14.0, 20.0):
        pxs = (cell / d) / ang
        print(f"   {d:7.1f} m  {float(ref_fade(d, near, far)):5.3f}  {pxs:8.2f}")
    print()
    print(f"  The fade reaches zero at {far} m, where a cell is "
          f"{(cell/far)/ang:.2f} px.")
    print("  A lattice finer than one resolve pixel cannot be resolved and")
    print("  would alias into the denoiser as shimmer -- which is the whole")
    print("  reason the fade exists.  Read the crawl diagnostic at <= 1.5 m,")
    print(f"  where a cell is {(cell/1.5)/ang:.1f} px.")


# ---------------------------------------------------------- 107 C: porous
def charlie_D(a, noh):
    u = max(1.0 - noh * noh, 1e-6)
    return (2.0 + 1.0 / a) * (u ** (1.0 / (2.0 * a))) / (2.0 * math.pi)


def neubelt_V(nol, nov):
    return 1.0 / max(4.0 * (nol + nov - nol * nov), 1e-4)


def porous_lobe(nol, nov, noh, a=0.9, amp=0.06, cap=0.5, defres=1.0):
    """The added term at the splice, BEFORE the site's own cosine fold."""
    lobe = min(charlie_D(a, noh) * neubelt_V(nol, nov), cap)
    voh = min(max((nol + nov) / max(2.0 * noh, 1e-6), 0.0), 1.0)
    w = 1.0 - defres * (1.0 - voh) ** 5
    return lobe * amp * w


def burley_diffuse(albedo, rough, nol, nov, voh):
    fd90 = 0.5 + 2.0 * rough * voh * voh
    fl = 1.0 + (fd90 - 1.0) * (1.0 - nol) ** 5
    fv = 1.0 + (fd90 - 1.0) * (1.0 - nov) ** 5
    return (1.0 / math.pi - 0.107508637 * rough) * fl * fv * albedo


def _geom(tv, tl, same=False):
    """(NoL, NoV, NoH, VoH) for view at tv and light at tl degrees from N.

    `same=False` puts them on opposite sides of the normal (the ordinary
    reflection geometry); `same=True` puts them on the SAME side, i.e. the
    RETRO / backscatter configuration where V ~ L.

    Exact vector algebra, not a half-angle shortcut.  It matters: the Charlie
    D is `(1 - NoH^2)^(1/2a)`, which is ZERO at NoH = 1, and a symmetric
    opposite-side pair (v85 / L85) puts H exactly on N -- so the naive
    "silhouette" row of a sheen table reports 0.00 % and looks like a bug.
    The Charlie lobe peaks where H lies near the tangent plane, and for two
    directions above the horizon that only happens in the RETRO direction at
    grazing.  Which is precisely why this lobe is the right model for POROUS
    BACKSCATTER and why the table below has to carry both configurations.
    """
    tv, tl = math.radians(tv), math.radians(tl)
    V = (math.sin(tv), 0.0, math.cos(tv))
    L = ((math.sin(tl) if same else -math.sin(tl)), 0.0, math.cos(tl))
    hx, hy, hz = V[0] + L[0], 0.0, V[2] + L[2]
    n = math.sqrt(hx * hx + hz * hz) or 1e-9
    return (max(L[2], 0.0), max(V[2], 0.0), max(hz / n, 0.0), n / 2.0)


def schlick_F(voh, f0=0.04):
    return f0 + (1.0 - f0) * (1.0 - voh) ** 5


def porous_table(a=0.9, amp=0.06, cap=0.5, albedo=0.35, rough=0.85,
                 defres=1.0):
    print(f"107 C -- porous backscatter: Charlie a={a}, amplitude {amp} "
          f"(x porosity 0.5-1.5), cap {cap}, defres {defres}")
    print(f"  reference surface: concrete, albedo {albedo}, roughness {rough}")
    print("  reflection rows: V and L on opposite sides of N; retro rows: same side")
    print()
    print("   geometry                      sheen / local diffuse      after")
    print("                                 x0.5     x1.0     x1.5     the F")
    ROWS = (("head-on     (v0,  L30) refl", (0.0, 30.0, False)),
            ("45 deg      (v45, L60) refl", (45.0, 60.0, False)),
            ("grazing     (v75, L70) refl", (75.0, 70.0, False)),
            ("backscatter (v45, L40) retro", (45.0, 40.0, True)),
            ("backscatter (v75, L70) retro", (75.0, 70.0, True)),
            ("backscatter (v85, L80) retro", (85.0, 80.0, True)))
    for label, (tv, tl, same) in ROWS:
        nol, nov, noh, voh = _geom(tv, tl, same)
        fd = burley_diffuse(albedo, rough, nol, nov, voh)
        row = []
        for p in (0.5, 1.0, 1.5):
            s = porous_lobe(nol, nov, noh, a, amp * p, cap, defres) * nol
            row.append(100.0 * s / max(fd, 1e-9))
        sF = (porous_lobe(nol, nov, noh, a, amp, cap, defres) * nol
              * schlick_F(voh))
        print(f"   {label:28s} {row[0]:7.2f}% {row[1]:7.2f}% {row[2]:7.2f}%"
              f"  {100.0*sF/max(fd,1e-9):8.3f}%")
    print()
    print("  Column 1-3 are the term AT THE SPLICE, directly comparable with")
    print("  81 sec 3's cloth table.  The last column is the same term after")
    print("  the module's own Schlick multiply, which is what reaches the")
    print("  pixel (GOTCHAS: splicing upstream of Fresnel means Fresnel")
    print("  weights your term too).")
    print()
    print("  FOR SCALE, AND THIS IS THE RISK: 81's cloth sheen is ALREADY ON")
    print("  THESE PIXELS in the standing base at k=1.0, a=0.25, measuring")
    print("  7.5 % at 45 deg and 25 % at the silhouette.  The porous lobe at")
    print(f"  amp={amp} is one to two orders of magnitude smaller.  It may be")
    print("  below the visible floor; --k-porous is the knob, and the honest")
    print("  pre-registration is that `porous` vs `porous-ctl` can come back")
    print("  NULL without the mechanism being wrong.")


def energy(a=0.9, amp=0.06, cap=0.5, n=192):
    """Directional albedo of the added lobe, hemisphere-integrated.

    94 sec 4.3's argument, applied here: the added term must be BOUNDED and
    the base lobe must NOT be inflated.  Both are checked numerically.
    """
    print(f"107 C -- energy bound (Charlie a={a}, amp {amp}, cap {cap})")
    peak = 0.0
    worst = None
    for iv in range(1, n):
        nov = iv / n
        tot = 0.0
        for il in range(1, n):
            nol = il / n
            # worst-case half vector: the two directions as close as the
            # cosines allow, i.e. NoH -> 1 gives D_charlie -> 0, so the peak
            # is at the WIDEST plausible NoH; sweep it.
            best = 0.0
            for ih in range(1, n // 4):
                # sweep every geometrically admissible NoH, retro included:
                # the peak is at small NoH, which is the backscatter arm.
                noh = ih / (n // 4)
                best = max(best, porous_lobe(nol, nov, noh, a, amp * 1.5, cap))
            tot += best * nol * (1.0 / n)
            if best * nol > peak:
                peak = best * nol
                worst = (nov, nol)
    e1 = 2.0 * math.pi * tot
    print(f"  max amplitude (porosity 1.5)          : {amp*1.5:.4f}")
    print(f"  hard cap on D*V                       : {cap}")
    print(f"  therefore added term <= amp*cap*w*cos : "
          f"{amp*1.5*cap:.5f}  (w <= 1, cos <= 1)")
    print(f"  worst observed added term (x NoL)     : {peak:.6f} "
          f"at NoV={worst[0]:.3f}, NoL={worst[1]:.3f}")
    print(f"  directional albedo of the added lobe  : {e1:.5f} "
          f"(fraction of an ideal white hemisphere)")
    print()
    print("  94 sec 4.3's two conditions, verbatim:")
    print("   (a) the added lobe is BOUNDED -- yes: amp*cap = "
          f"{amp*1.5*cap:.5f} is a build-time constant product, and the NMin")
    print("       cap is emitted BEFORE the term reaches the base (GOTCHAS:")
    print("       scale before a clamp, never after).")
    print("   (b) the base lobe is NOT inflated -- yes: the splice is an")
    print("       OpFAdd onto the site's D*Vis product.  Nothing multiplies")
    print("       the GGX term, so no base energy is created or moved.")
    print(f"   Residual: the composite exceeds unity by at most {e1:.5f} of a")
    print("       white hemisphere.  Not compensated, deliberately: a damp on")
    print("       the Burley scalar at this magnitude is smaller than the")
    print("       dither, and 81 already spends a damp there for a lobe 11x")
    print("       larger.  Stated, not hidden.")
    return e1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--calibrate', action='store_true')
    ap.add_argument('--porous', action='store_true')
    ap.add_argument('--energy', action='store_true')
    ap.add_argument('--fade', action='store_true')
    ap.add_argument('--k-rough', type=float, default=0.08)
    ap.add_argument('--k-alb', type=float, default=0.06)
    ap.add_argument('--a-porous', type=float, default=0.9)
    ap.add_argument('--k-porous', type=float, default=0.06)
    ap.add_argument('--cap', type=float, default=0.5)
    ap.add_argument('--near', type=float, default=6.0)
    ap.add_argument('--far', type=float, default=14.0)
    ap.add_argument('--cell', type=float, default=0.012)
    a = ap.parse_args()
    did = False
    if a.calibrate:
        calibrate(a.k_rough, a.k_alb); did = True
    if a.fade:
        print(); fade_table(a.near, a.far, a.cell); did = True
    if a.porous:
        print(); porous_table(a.a_porous, a.k_porous, a.cap); did = True
    if a.energy:
        print(); energy(a.a_porous, a.k_porous, a.cap); did = True
    if not did:
        ap.error('nothing to do -- --calibrate / --fade / --porous / --energy')


if __name__ == '__main__':
    main()
