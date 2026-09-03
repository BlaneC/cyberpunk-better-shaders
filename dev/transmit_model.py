#!/usr/bin/env python3
"""transmit_model.py -- the ear glow's transfer, derived from skin optics.

handoff/111.  OFFLINE MODEL ONLY: it touches no SPIR-V and no swap.  It answers
one question -- *what should the three exponential rates in the shipped ear
glow actually be?* -- from published tissue optics instead of from a tint knob.

WHAT THE SHIPPED SHADER COMPUTES (read back out of the default's .spv,
`swaps.gi-...-earglow-cap6-glintdense-curv`, module 1271d3815051da17):

    t_eff  = NMax(chord_along_sun, 6 mm)              <- 101 sec 18's floor
    T_c    = 0.5*(exp(-t_eff*a1_c) + exp(-t_eff*a2_c))
    W      = k * SmoothStep(0, 0.35, -N.S)            <- k = 0.22
    add_c  = NMin(T_c * W * sunRadiance_c, 100)

with a1 = 1/ld and a2 = 1/(4*ld), ld = (3.67, 1.37, 0.68) mm.  Those ld are
Jensen 2001's `skin1` DIFFUSION LENGTHS 1/mu_eff evaluated at three single
wavelengths (600/550/450 nm).  Two things are wrong with using them as the
per-CHANNEL rates of a broadband renderer, and both push the same way:

  1. A camera's R channel is ~120 nm wide and skin's mu_eff falls by a factor
     of five across it (the "optical window" opens past 600 nm).  Light that
     survives 6 mm of flesh is therefore not "600 nm light attenuated by
     mu_eff(600)" -- it is overwhelmingly the 660-700 nm tail.  Integrating
     the real spectrum over the real channel sensitivity makes the emergent
     light REDDER than the single-wavelength model at every depth, and makes
     the red channel's own decay FLATTEN with depth (spectral sharpening).
     One exponential cannot do that; the shipped shape, being a SUM of two,
     can -- but only if the second rate is fitted instead of pinned at a1/4.

  2. Single-wavelength mu_eff at 550/450 nm is far too transmissive.  Whole
     blood absorbs ~280 cm-1 at 550 nm, so green light does not cross 6 mm of
     perfused flesh at all; the shipped model gives it 26% of the red's level
     there (R/G = 2.48) and that desaturated orange IS the "too yellow" and
     the "lightbulb" in the 110 sec 0 verdict.

THE MODEL
---------
Layered symmetric slab, total thickness d, mirrored about the mid-plane:

    epidermis   60 um    melanin filter, BEER (60 um < one transport mfp)
    dermis     500 um    f_blood = 0.03, diffusion
    core     d - 1.12 mm f_blood = 0.002, diffusion   <- cartilage/fat/bone
    dermis     500 um
    epidermis   60 um

  mu_a,baseline = 7.84e8 * nm^-3.255                       [cm-1]  Jacques 98
  mu_a,mel      = 6.6e11 * nm^-3.33                        [cm-1]  Jacques 98
  mu_a,blood    = 2.303 * e(nm) * 150 / 64500              [cm-1]  Prahl (data
                  with e from dev/data/hb_prahl.txt, SO2-mixed)     vendored)
  mu_a,layer    = f_b*mu_a,blood + (1-f_b)*mu_a,baseline
  mu_s'         = 2e12*nm^-4 + 2e5*nm^-1.5                 [cm-1]  Jacques 98
  mu_eff        = sqrt(3*mu_a*(mu_a + mu_s'))

  T(nm, d)      = exp(-mu_a,epi*t_epi)^2 * PROD_i exp(-mu_eff,i * t_i)

WHAT THE MODEL IS NOT.  The layer product drops inter-layer diffuse
reflection and both refractive-index boundaries, so its ABSOLUTE level is a
lower bound and its prefactor is not trustworthy.  That is deliberate and it
costs nothing: the shipped shader has exactly one amplitude, `k`, and this
file's whole output is the SHAPE (per-channel rates) plus a `k` renormalised
so that the RED channel at a chosen reference depth lands exactly where the
shipped default the user approved already has it.  Level is held by fiat;
chromaticity and depth-shape come from the physics.

  python3 dev/transmit_model.py                     # the tables
  python3 dev/transmit_model.py --emit rates.json   # what patch_earglow7 reads
"""
import argparse, json, os, sys
import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
HB = os.path.join(HERE, 'data', 'hb_prahl.txt')

# --- the shipped transfer, for every comparison in this file ---------------
LD_SHIPPED = (0.00367, 0.00137, 0.00068)      # m
WIDE_SHIPPED = 4.0
K_SHIPPED = 0.22
FLOOR_SHIPPED = 0.006                          # m, 101 sec 18
TMAX = 0.018                                   # m, query B's tmax
W709 = np.array([0.2126, 0.7152, 0.0722])

# --- layer geometry (metres) ----------------------------------------------
T_EPI = 60e-6
T_DERM = 500e-6
FB_DERM = 0.03
FB_CORE = 0.002
F_MEL = 0.05
SO2 = 0.75              # capillary-bed mix; arterial 0.98, venous 0.6


def cmf(nm):
    """CIE 1931 2-deg xbar/ybar/zbar, the multi-lobe piecewise-Gaussian fit of
    Wyman, Sloan & Shirley, JCGT 2(2) 2013.  Max abs error ~0.01 on functions
    that peak near 1; the self-check in main() prints the E and D65 white
    points it implies, which is what actually matters here."""
    def g(x, mu, s1, s2):
        s = np.where(x < mu, s1, s2)
        return np.exp(-0.5 * ((x - mu) / s) ** 2)
    x = (1.056 * g(nm, 599.8, 37.9, 31.0)
         + 0.362 * g(nm, 442.0, 16.0, 26.7)
         - 0.065 * g(nm, 501.1, 20.4, 26.2))
    y = (0.821 * g(nm, 568.8, 46.9, 40.5)
         + 0.286 * g(nm, 530.9, 16.3, 31.1))
    z = (1.217 * g(nm, 437.0, 11.8, 36.0)
         + 0.681 * g(nm, 459.0, 26.0, 13.8))
    return np.stack([x, y, z])


XYZ2RGB = np.array([[3.2406, -1.5372, -0.4986],
                    [-0.9689, 1.8758, 0.0415],
                    [0.0557, -0.2040, 1.0570]])


def load_hb():
    lam, hbo2, hb = [], [], []
    with open(HB) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            a, b, c = line.split()
            lam.append(float(a)); hbo2.append(float(b)); hb.append(float(c))
    return np.array(lam), np.array(hbo2), np.array(hb)


def optics(nm, so2=SO2):
    """mu_a of whole blood, of bloodless skin, of melanosome interior, and
    mu_s' of dermis -- all cm-1, on the wavelength grid `nm`."""
    lam, e_o, e_d = load_hb()
    eo = np.interp(nm, lam, e_o)
    ed = np.interp(nm, lam, e_d)
    mua_blood = 2.303 * (so2 * eo + (1 - so2) * ed) * 150.0 / 64500.0
    mua_base = 7.84e8 * nm ** -3.255
    mua_mel = 6.6e11 * nm ** -3.33
    musp = 2e12 * nm ** -4.0 + 2e5 * nm ** -1.5
    return mua_blood, mua_base, mua_mel, musp


def layers(d, mode='fixed'):
    """(thickness_m, f_blood) per diffusing layer, and the epidermal path.

    mode='fixed'   the skin is 60 um + 500 um per side and the CORE takes the
                   rest.  Right when d is a real THICKNESS: a thicker part of
                   the head is thicker in cartilage/fat/bone, not in dermis.
    mode='scaled'  every layer keeps its share of d.  Right when d is an
                   oblique CHORD through a thin slab, where the blood-rich
                   dermis is crossed at the same obliquity as the core.

    The shader feeds the chord, so the truth is between the two: `fixed`
    under-counts blood at grazing incidence, `scaled` over-counts it in thick
    flesh.  main() fits both and prints the bracket."""
    if mode == 'scaled':
        share = T_EPI / (T_EPI + T_DERM)      # composition of a 1.12 mm slab
        return 0.5 * d * share, [(d * (1 - share), FB_DERM)]
    epi = min(T_EPI, 0.25 * d)
    rest = 0.5 * d - epi
    derm = min(T_DERM, rest)
    core = max(0.0, rest - derm)
    return epi, [(2 * derm, FB_DERM), (2 * core, FB_CORE)]


def transmit(nm, d, f_mel=F_MEL, so2=SO2, mode='fixed', pre=None,
             fb=(FB_DERM, FB_CORE)):
    """T(nm, d), dimensionless, for one thickness d in metres."""
    mua_blood, mua_base, mua_mel, musp = pre if pre else optics(nm, so2)
    epi, dif = layers(d, mode)
    dif = [(t, fb[i] if i < len(fb) else f) for i, (t, f) in enumerate(dif)]
    mua_epi = f_mel * mua_mel + (1 - f_mel) * mua_base
    tau = mua_epi * (2 * epi * 100.0)                    # cm
    for t, fb in dif:
        if t <= 0:
            continue
        mua = fb * mua_blood + (1 - fb) * mua_base
        mueff = np.sqrt(3.0 * mua * (mua + musp))
        tau = tau + mueff * (t * 100.0)
    return np.exp(-tau)


def bands(cm):
    """POSITIVE per-channel spectral sensitivities, s_c(nm) >= 0.

    The exact answer -- project the filtered spectrum through the CMFs into
    linear Rec.709 -- is not usable here: a filter that passes only 620 nm+
    has NEGATIVE Rec.709 green and blue, because deep red is outside the sRGB
    gamut.  True, and useless as a per-channel multiplier, which is the only
    thing the shader can apply.  So the channels are treated the way a
    renderer implicitly treats them: three positive spectral bands, taken as
    the positive part of the sRGB colour-matching rows and normalised to unit
    area.  A non-absorbing slab then gives T_c == 1 in all three, and every
    T_c stays in [0, 1] at every thickness.  `--exact` prints the gamut
    projection alongside, negatives and all, as the cross-check."""
    s = XYZ2RGB @ cm
    s = np.maximum(s, 0.0)
    return s / s.sum(axis=1, keepdims=True)


def to_rgb(nm, spec, sens):
    """Band-averaged transmittance: sum(s_c * T) / sum(s_c), s_c normalised."""
    return (sens * spec).sum(axis=1)


def to_rgb_exact(nm, spec, cm):
    """The gamut projection, for the cross-check only. Goes negative."""
    return (XYZ2RGB @ (cm * spec).sum(axis=1)) / (XYZ2RGB @ cm.sum(axis=1))


def shipped(d, ld=LD_SHIPPED, wide=WIDE_SHIPPED):
    return np.array([0.5 * (np.exp(-d / l) + np.exp(-d / (wide * l)))
                     for l in ld])


def two_lobe(d, a1, a2):
    return 0.5 * (np.exp(-a1 * d) + np.exp(-a2 * d))


AMAX = 3.0e4      # 1/m: ld = 33 um, dead inside query B's own 1.5 mm tmin
AMIN = 1.0e1


def fit_channel(dm, tc, floor=1e-30):
    """Fit  A * 0.5*(exp(-a1 d) + exp(-a2 d))  to tc(d) in LOG space.

    THREE parameters, not two, and the third one is the whole reason the v5
    tint exists.  The shipped shape is pinned at T(0) = 1, which is correct
    physics, but the real per-channel curve leaves 1 almost immediately (a
    fast component in the blood-rich dermis) and then decays slowly (the
    surviving long-wavelength tail).  Over the range the shader can actually
    evaluate -- query B's tmin 1.5 mm to its tmax 18 mm -- that shape needs a
    per-channel AMPLITUDE as well as two rates.  Two lobes can fake an
    amplitude between 0.5 and 1 by killing one of them, and no further: green
    needs ~0.15.  So A comes out of the fit and is emitted as the TINT, whose
    red entry is folded into k.  The rates are bounded because a1 = inf is not
    a shader constant; at AMAX the fast lobe is already dead at 1.5 mm.

    LOG space, because the curve spans four decades over that range and a
    linear fit would only ever match the first millimetre."""
    y = np.log(np.maximum(tc, floor))

    def resid(p):
        A, a1, a2 = np.exp(p)
        f = A * 0.5 * (np.exp(-a1 * dm) + np.exp(-a2 * dm))
        return np.log(np.maximum(f, floor)) - y

    lo = np.log([1e-3, AMIN, AMIN])
    hi = np.log([4.0, AMAX, AMAX])
    best, bcost = None, np.inf
    for gA in (1.0, 0.5, 0.2, 0.05):
        for g1 in (AMAX, 3e3, 1e3):
            for g2 in (2e3, 8e2, 4e2):
                p0 = np.clip(np.log([gA, g1, g2]), lo + 1e-9, hi - 1e-9)
                r = least_squares(resid, p0, bounds=(lo, hi), max_nfev=4000)
                if r.cost < bcost:
                    bcost, best = r.cost, r
    A, a1, a2 = np.exp(best.x)
    if a2 > a1:
        a1, a2 = a2, a1
    return (A, a1, a2, bcost)


def three_lobe(d, A, a1, a2):
    return A * 0.5 * (np.exp(-a1 * d) + np.exp(-a2 * d))


def report_bands(nm, sens):
    out = []
    for c in range(3):
        w = sens[c]
        cen = float((nm * w).sum() / w.sum())
        nz = nm[w > 0.002 * w.max()]
        out.append((cen, float(nz.min()), float(nz.max())))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f-mel', type=float, default=F_MEL)
    ap.add_argument('--fb-derm', type=float, default=FB_DERM)
    ap.add_argument('--fb-core', type=float, default=FB_CORE)
    ap.add_argument('--so2', type=float, default=SO2)
    ap.add_argument('--mode', choices=('fixed', 'scaled'), default='fixed')
    ap.add_argument('--ref', type=float, default=FLOOR_SHIPPED,
                    help='reference depth (m) at which RED is held to the '
                         'shipped default. Default: the 6 mm floor.')
    ap.add_argument('--fit-lo', type=float, default=None,
                    help='low end of the fit range (m). Default: --ref, i.e. '
                         'the floor -- no shorter t_eff is ever evaluated')
    ap.add_argument('--fit-hi', type=float, default=0.018,
                    help="query B's tmax")
    ap.add_argument('--no-sensitivity', action='store_true',
                    help='skip the parameter sweep (it is 12 more fits and '
                         'the build only needs it printed once)')
    ap.add_argument('--exact', action='store_true',
                    help='also print the sRGB gamut projection (goes negative)')
    ap.add_argument('--emit')
    a = ap.parse_args()
    if a.fit_lo is None:
        a.fit_lo = a.ref

    nm = np.arange(380.0, 781.0, 1.0)
    cm = cmf(nm)
    sens = bands(cm)
    pre = optics(nm, a.so2)

    # ---- self-check: the white points this CMF fit implies ---------------
    XYZe = cm.sum(axis=1)
    xe = XYZe / XYZe.sum()
    bb = 3.7418e-16 / (nm * 1e-9) ** 5 / (np.exp(1.4388e-2 /
                                                 (nm * 1e-9 * 6504)) - 1)
    XYZd = (cm * bb).sum(axis=1)
    xd = XYZd / XYZd.sum()
    print(f"CMF self-check   E white point x,y = {xe[0]:.4f} {xe[1]:.4f} "
          f"(exact 0.3333 0.3333)")
    print(f"                 6504 K blackbody = {xd[0]:.4f} {xd[1]:.4f} "
          f"(D65 is 0.3127 0.3290)")
    print("CHANNEL BANDS    centroid / support (nm), positive sRGB rows, "
          "unit area")
    for c, (cen, lo, hi) in zip('RGB', report_bands(nm, sens)):
        print(f"     {c}           {cen:6.1f}   {lo:.0f} - {hi:.0f}")

    grid = np.concatenate([np.arange(0.0005, 0.0061, 0.0005),
                           np.arange(0.007, 0.0181, 0.001)])

    fb = (a.fb_derm, a.fb_core)

    def curve(mode, f_mel=None, fbv=None):
        T = np.array([to_rgb(nm, transmit(nm, d, a.f_mel if f_mel is None
                                          else f_mel, a.so2, mode, pre,
                                          fbv or fb), sens)
                      for d in grid]).T
        return np.clip(T, 1e-30, 1.0)

    Tc = curve(a.mode)

    print(f"\nSPECTRAL TRANSMITTANCE, layer mode '{a.mode}' "
          f"(f_mel={a.f_mel}, SO2={a.so2}, f_blood {fb[0]}/{fb[1]})")
    print("   d/mm       T_R       T_G       T_B     R/G      R/B      Y709")
    for i, d in enumerate(grid):
        r, g, b = Tc[:, i]
        print(f"  {d*1e3:6.2f}  {r:.3e} {g:.3e} {b:.3e} {r/g:8.1f} "
              f"{r/b:8.1f}  {float(W709 @ Tc[:, i]):.3e}")
    if a.exact:
        print("  cross-check, sRGB gamut projection (negative = out of gamut)")
        for d in (0.0015, 0.003, 0.006, 0.012):
            e = to_rgb_exact(nm, transmit(nm, d, a.f_mel, a.so2, a.mode, pre),
                             cm)
            print(f"  {d*1e3:6.2f}  {e[0]:+.3e} {e[1]:+.3e} {e[2]:+.3e}")

    m = (grid >= a.fit_lo) & (grid <= a.fit_hi)
    print(f"\nTWO-LOBE FIT  0.5*(exp(-a1 d) + exp(-a2 d))   over "
          f"[{a.fit_lo*1e3:.1f}, {a.fit_hi*1e3:.1f}] mm  "
          f"(the floor .. query B's tmax)")
    print("  mode     ch       A     tint     a1 [1/m]   a2 [1/m]  ld1/mm "
          "ld2/mm  logRMS")
    fits = {}
    for mode in ('fixed', 'scaled'):
        T = Tc if mode == a.mode else curve(mode)
        fits[mode] = [fit_channel(grid[m], T[c][m]) for c in range(3)]
        AR = fits[mode][0][0]
        for c, (A, a1, a2, cost) in zip('RGB', fits[mode]):
            n = int(m.sum())
            star = '*' if mode == a.mode else ' '
            print(f" {star}{mode:8s} {c}  {A:7.4f} {A/AR:7.4f} {a1:10.1f} "
                  f"{a2:9.1f}  {1e3/a1:6.3f} {1e3/a2:6.3f}  "
                  f"{np.sqrt(2*cost/n):.4f}")
    fit = fits[a.mode]

    def T_fit(d):
        return np.array([three_lobe(d, A, a1, a2) for A, a1, a2, _ in fit])

    print("\nSHIPPED vs FITTED, transfer only (no k, no sun, no wrap).")
    print("   d/mm    T_R ship   T_R fit     x      R/G ship  R/G fit   "
          "Y ship    Y fit      Yx")
    for d in (0.002, 0.003, 0.004, 0.006, 0.008, 0.012, 0.018):
        sp, f = shipped(d), T_fit(d)
        print(f"  {d*1e3:5.1f}  {sp[0]:.4e} {f[0]:.4e} {f[0]/sp[0]:6.3f}  "
              f"{sp[0]/sp[1]:9.2f} {f[0]/f[1]:8.1f}  {W709@sp:.3e} "
              f"{W709@f:.3e} {(W709@f)/(W709@sp):6.3f}")

    # ---- the normalisation ------------------------------------------------
    fref, sref = T_fit(a.ref), shipped(FLOOR_SHIPPED)
    kfit = K_SHIPPED * sref[0] / fref[0]
    # The SHADER's k is not kfit.  kfit scales the model's T_c, which carries
    # the fitted amplitude A_c; the shader's transfer is the bare
    # 0.5*(exp+exp) with A_c/A_R applied as the tint, so red's own amplitude
    # has to be folded into k or the whole term comes out 1/A_R too bright.
    # verify_earglow7.py check 9 recomputes the peak from the shipped
    # constants and is what caught this.
    k_shader = kfit * fit[0][0]
    print(f"\nNORMALISATION.  The rung's brightest RED -- at its floor, "
          f"d = {a.ref*1e3:.1f} mm -- is held to the\n  shipped default's "
          f"brightest red, which is at ITS floor of "
          f"{FLOOR_SHIPPED*1e3:.0f} mm.  So the peak red does not\n  move, "
          f"whatever the floor is, and k absorbs the model's prefactor:")
    print(f"  shipped k*T_R {K_SHIPPED*sref[0]:.6f}   fitted T_R "
          f"{fref[0]:.6e}   =>  k' = {kfit:.4f}")
    print(f"  the SHADER's k = k' * A_R = {kfit:.4f} * {fit[0][0]:.4f} = "
          f"{k_shader:.4f}   (A_R is red's fitted amplitude; the tint carries "
          f"only A_c/A_R)")
    print(f"  k'*T there : R {kfit*fref[0]:.6f} G {kfit*fref[1]:.6f} "
          f"B {kfit*fref[2]:.6f}")
    print(f"  shipped    : R {K_SHIPPED*sref[0]:.6f} "
          f"G {K_SHIPPED*sref[1]:.6f} B {K_SHIPPED*sref[2]:.6f}")
    print(f"  Rec.709 luminance of the term there: "
          f"{(W709@(kfit*fref))/(W709@(K_SHIPPED*sref)):.3f}x the default")
    print(f"  as a fraction of a WHITE sun's own luminance: "
          f"{float(W709@(kfit*fref)):.4f} vs the default's "
          f"{float(W709@(K_SHIPPED*sref)):.4f}")

    print("\nTHE TERM WITH k' APPLIED, against the shipped default.  Both\n"
          "columns are FRACTIONS OF THE SUN'S OWN RADIANCE, per channel, at\n"
          "cos = 1; multiply by the angular factor for a real pixel.")
    print("   d/mm    R new     R ship    G new     G ship     Y new     "
          "Y ship   Ynew/Yship")
    for d in (0.0015, 0.002, 0.003, 0.006, 0.008, 0.010, 0.012, 0.018):
        sp = K_SHIPPED * shipped(d)
        f = kfit * T_fit(d)
        print(f"  {d*1e3:5.1f}  {f[0]:.3e} {sp[0]:.3e} {f[1]:.3e} "
              f"{sp[1]:.3e}  {W709@f:.3e} {W709@sp:.3e} "
              f"{(W709@f)/(W709@sp):8.3f}")

    # ---- how much of this the model's free parameters can move -----------
    if a.no_sensitivity:
        print("\nSENSITIVITY: skipped (--no-sensitivity)")
    else:
      print("\nSENSITIVITY.  The fit re-run against the model's two least\n"
            "constrained parameters.  'tint' is the fitted per-channel\n"
            "amplitude relative to red -- what the shader actually carries.")
      print("  f_blood  f_mel   ld_R2/mm  tint_G   tint_B   R/G @floor  "
            "R/G @12mm")
      for fbd in (0.01, 0.02, 0.03, 0.05):
          for fm in (0.02, 0.05, 0.10):
              T = curve(a.mode, fm, (fbd, a.fb_core))
              ff = [fit_channel(grid[m], T[c][m]) for c in range(3)]
              tG, tB = ff[1][0] / ff[0][0], ff[2][0] / ff[0][0]

              def q(d):
                  v = np.array([three_lobe(d, A, x, y) for A, x, y, _ in ff])
                  return v[0] / max(v[1], 1e-30)
              print(f"   {fbd:5.3f}   {fm:4.2f}   {1e3/ff[0][2]:7.3f}  "
                    f"{tG:.5f}  {tB:.5f}   {q(a.ref):9.1f}  {q(0.012):9.1f}")

    # ---- the cosine, i.e. the entry-face Lambert factor ------------------
    print("\nANGULAR FACTOR.  The shipped weight is SmoothStep(0, 0.35, c),\n"
          "c = -N.S, which SATURATES AT 1 for every c >= 0.35.  The flux that\n"
          "actually enters the slab is proportional to c itself.")
    print("     c    smoothstep    cos    cos/ss   chord of a 3 mm slab")
    for c in (0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9, 1.0):
        t = min(max(c / 0.35, 0.0), 1.0)
        ss = t * t * (3 - 2 * t)
        print(f"  {c:5.2f}   {ss:9.4f} {c:7.3f}  {c/ss:7.3f}   "
              f"{3.0/max(c,1e-3):8.2f} mm")

    if a.emit:
        out = {"model": "transmit_model.py", "layer_mode": a.mode,
               "f_mel": a.f_mel, "so2": a.so2,
               "f_blood": [a.fb_derm, a.fb_core],
               "layers_m": {"epi": T_EPI, "derm": T_DERM},
               "fit_range_m": [a.fit_lo, a.fit_hi], "ref_m": a.ref,
               "rates_1_per_m": [[f[1], f[2]] for f in fit],
               "ld_m": [[1.0 / f[1], 1.0 / f[2]] for f in fit],
               "amplitude": [f[0] for f in fit],
               "tint": [f[0] / fit[0][0] for f in fit],
               "rates_scaled_1_per_m": [[f[1], f[2]]
                                        for f in fits['scaled']],
               "tint_scaled": [f[0] / fits['scaled'][0][0]
                               for f in fits['scaled']],
               "k": k_shader,
               "k_on_model_T": kfit,
               "shipped": {"ld_m": list(LD_SHIPPED), "wide": WIDE_SHIPPED,
                           "k": K_SHIPPED, "floor_m": FLOOR_SHIPPED},
               "T_at_ref": list(fref), "T_ref_shipped": list(sref)}
        with open(a.emit, 'w') as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {a.emit}")


if __name__ == '__main__':
    main()
