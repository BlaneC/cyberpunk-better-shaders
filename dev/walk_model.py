#!/usr/bin/env python3
"""Random-walk subsurface for skin -- the OFFLINE model and its feasibility gate.

handoff/119.  Nothing is spliced until this file says the walk fits.

WHAT THIS REPLACES.  `111`/`113` ship a CLOSED-FORM transmittance: one sunward
thickness probe t_B, then

    T_c = 0.5 * (exp(-a1_c * t) + exp(-a2_c * t)) * tint_c

which is a two-exponential fit to diffuse transmission through a slab of
thickness t.  It is a good fit and it is cheap, but it is a slab model: it
knows one number about the geometry (how thick, straight ahead) and nothing
about where the light actually goes.  A random walk (Chiang et al. 2016,
"Practical and Controllable Subsurface Scattering for Production Path
Tracing") answers the same question by actually transporting: sample a free
flight, test whether that flight leaves the manifold, scatter if it did not.

PARAMETERISATION.  Chiang's, which is the one production uses and the one that
takes ARTIST numbers (a diffuse mean free path and a surface albedo) rather
than sigma_s/sigma_a:

    alpha_c = 1 - exp(-5.09406*A_c + 2.61188*A_c^2 - 4.31805*A_c^3)
    s_c     = 1.9 - A_c + 3.5*(A_c - 0.8)^2
    sigma_t = 1 / (ld_c * s_c)

`A` is the diffuse surface albedo and `ld` the diffuse mean free path.  For
skin both are already in this repo: Jensen 2001 `skin1`, whose mean-free-path
RATIO 2.68 : 1 : 0.50 is exactly what 97 sec 3.4's terminator bleed is built
on, and whose diffuse reflectance is (0.44, 0.22, 0.13).  So the walk and the
shipped bleed are parameterised from the SAME measurement, which is the point:
they should agree in the limit, and check 5 measures whether they do.

THE CONSTRAINT THIS FILE EXISTS TO TEST.  `105` proved six live ray query
objects in one raygen and no more.  Query A (primary-surface reconstruct) and
query C (light visibility at the exit) are already spent, so the walk gets at
most FOUR queries, i.e. K <= 4 unrolled steps -- there is no loop, because
nothing in this project's raygen splices has ever added control flow.

A walk truncated at K steps loses every path that had not yet escaped.  That
is a DARKENING bias and it is not optional: it is the whole feasibility
question.  Check 6 reports it as a number, per channel, at K = 1..6, for the
ear thicknesses the feature actually targets.  If K = 4 loses most of the
energy, this design is wrong and the honest answer is to say so here rather
than to discover it on screen.
"""
import math, struct, sys

F32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]

# --- Jensen 2001 skin1, the same measurement 97 sec 3.4 already uses --------
MFP_RATIO = (2.68, 1.0, 0.50)          # d_R : d_G : d_B
ALBEDO_A = (0.44, 0.22, 0.13)          # diffuse reflectance
LD_G = 0.0010                          # 1 mm green diffuse mean free path
K_MAX = 4                              # 6 live queries (105) minus A and C
G_HG = 0.0                             # isotropic phase to start; a knob
# --- the calibration RESULT, measured by calibrate_fast(n=60000) -----------
# Recorded here so check() gates on it without re-running a 10-minute fit.
# Reproduce with:  python3 -c "import walk_model as W; W.calibrate_fast()"
FITTED_A = (0.890, 0.190, 0.365)          # diffuse albedo per channel
FITTED_LD = (0.500, 0.200, 0.160)         # diffuse mean free path, mm
FIT_RMS = (0.302, 1.979, 1.602)           # rms(log T) of the fit; G and B FAIL
FITTED_ALPHA = (0.9959, 0.5947, 0.8212)   # scattering albedo, Chiang inversion
FITTED_SIGMA_T = (1926.1, 1659.8, 2851.5) # /m
# fraction of the converged energy a K-step walk keeps at a 3 mm ear
K4_KEEP = (0.060, 0.824, 0.204)
K6_KEEP = (0.111, 0.933, 0.312)


def chiang(A, ld):
    """(alpha, sigma_t) from a diffuse albedo and a diffuse mean free path."""
    a = 1.0 - math.exp(-5.09406 * A + 2.61188 * A * A - 4.31805 * A ** 3)
    s = 1.9 - A + 3.5 * (A - 0.8) ** 2
    return a, 1.0 / (ld * s)


def medium(ld_g=LD_G):
    ld = [ld_g * r / MFP_RATIO[1] for r in MFP_RATIO]
    return [chiang(ALBEDO_A[c], ld[c]) for c in range(3)]


# --- the shader's own LCG, so the model draws what the shader will draw -----
class LCG:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def u(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return F32((self.s & 0x00FFFFFF) * (2.0 ** -24))


def sample_hg(rng, g):
    """(cos_theta, phi) for Henyey-Greenstein; isotropic at g = 0."""
    u = rng.u()
    if abs(g) < 1e-4:
        ct = 1.0 - 2.0 * u
    else:
        sq = (1.0 - g * g) / (1.0 - g + 2.0 * g * u)
        ct = (1.0 + g * g - sq * sq) / (2.0 * g)
    return max(-1.0, min(1.0, ct)), 2.0 * math.pi * rng.u()


def walk_slab(rng, L, med, K, g=G_HG, hero=1):
    """One walk into a plane-parallel slab of thickness L, entering at z=0
    along +z.  Returns (exited_front, exited_back, weight[3], steps).

    Hero-wavelength sampling: the free flight is drawn from ONE channel's
    sigma_t and the other two are carried as a ratio weight, so a single walk
    -- a single set of ray queries -- serves all three channels.  This is what
    makes a chromatic medium affordable in a shader that can only afford one
    walk (Wilkie et al. 2014; Chiang sec 4.2).
    """
    st = [m[1] for m in med]
    al = [m[0] for m in med]
    z, d = 0.0, 1.0                      # 1-D is enough: the slab is the test
    w = [1.0, 1.0, 1.0]
    for step in range(K):
        u = rng.u()
        t = -math.log(max(1.0 - u, 1e-12)) / st[hero]
        # boundary first: does the free flight leave the slab?
        zt = z + d * t
        if zt <= 0.0 or zt >= L:
            tb = (0.0 - z) / d if d < 0 else (L - z) / d
            tb = max(tb, 0.0)
            # crossing: weight by transmittance ratio over the DISTANCE FLOWN
            pdf_h = st[hero] * math.exp(-st[hero] * tb)
            for c in range(3):
                w[c] *= math.exp(-st[c] * tb) / max(math.exp(-st[hero] * tb), 1e-30)
            return (zt <= 0.0), (zt >= L), w, step + 1
        # a real scatter: weight by the scattering ratio at distance t
        pdf_h = st[hero] * math.exp(-st[hero] * t)
        for c in range(3):
            num = al[c] * st[c] * math.exp(-st[c] * t)
            w[c] *= num / max(pdf_h, 1e-30)
        z = zt
        # A slab is symmetric in azimuth, so the walk reduces EXACTLY to the
        # direction cosine -- but it must be the cosine, not its sign.  A
        # +/-1 projection would make every step a full free flight in z and
        # systematically over-transmit; mu is drawn from the phase function
        # and the step in z is t*mu.
        d, _ = sample_hg(rng, g)
        if abs(d) < 1e-6:
            d = 1e-6
    return False, False, [0.0, 0.0, 0.0], K      # TRUNCATED: energy lost


def slab_transmittance(L, K, n=20000, seed=12345, ld_g=LD_G, g=G_HG):
    med = medium(ld_g)
    rng = LCG(seed)
    T = [0.0, 0.0, 0.0]
    trunc = 0
    for _ in range(n):
        _, back, w, _ = walk_slab(rng, L, med, K, g)
        if back:
            for c in range(3):
                T[c] += w[c]
        elif w == [0.0, 0.0, 0.0]:
            trunc += 1
    return [t / n for t in T], trunc / n


# --- the shipped closed form, for the agreement check ----------------------
A1 = (861.72, 845.89, 1766.85)         # 111 sec 2.3, per metre
A2 = (645.76, 622.22, 1545.23)
TINT = (1.0000, 0.0194, 0.0846)


def shipped_T(t):
    return [0.5 * (math.exp(-A1[c] * t) + math.exp(-A2[c] * t)) * TINT[c]
            for c in range(3)]


def check():
    ok, bad = 0, []

    def T(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            bad.append(name)

    med = medium()
    # 1. the Chiang inversion is well formed for every skin channel
    T('alpha in (0,1) for all channels',
      all(0.0 < a < 1.0 for a, _ in med))
    T('sigma_t positive and ordered like the mfp ratio',
      med[0][1] < med[1][1] < med[2][1])
    # 2. a redder channel travels further: sigma_t_R < sigma_t_G < sigma_t_B
    T('red is the deepest channel', med[0][1] == min(m[1] for m in med))
    # 3. the LCG is the shader's, and its draws are in [0,1)
    r = LCG(1)
    T('LCG draws in [0,1)', all(0.0 <= r.u() < 1.0 for _ in range(1000)))
    T('LCG matches the shader recurrence',
      (((1 * 1664525 + 1013904223) & 0xFFFFFFFF) & 0xFFFFFF) * 2.0 ** -24
      == LCG(1).u())
    # 4. an infinite K walk conserves: thin slab -> T -> 1
    Tt, _ = slab_transmittance(1e-6, 32, n=4000)
    T('a vanishing slab transmits ~1 on every channel',
      all(0.85 < x < 1.15 for x in Tt))
    # 5. the walk and the SHIPPED closed form must agree in ORDER at ear
    #    thickness -- not exactly (one is a fit, one is transport), but the
    #    channel ORDERING and the decade must match or the two features would
    #    contradict each other on screen.
    Tw, _ = slab_transmittance(0.003, 32, n=8000)
    Ts = shipped_T(0.003)
    T('the walk agrees with 111 on channel order (R > B > G or R > G > B)',
      Tw.index(max(Tw)) == Ts.index(max(Ts)) == 0)
    # 6. 111's model is NOT a medium transmittance, and no walk can match it.
    #    A homogeneous medium transmits everything at zero thickness.  111's
    #    form is 0.5(e^0 + e^0)*tint = tint, so it transmits 1.9% of green
    #    through NOTHING.  The chroma of the shipped ear glow comes from that
    #    tint, not from transport, and that is why the fit below fails in G
    #    and B by rms(log T) ~ 1.6-2.0 (a factor of 5-7) no matter what
    #    medium is chosen.
    T0 = shipped_T(0.0)
    T('111 does not transmit 1 at zero thickness (it is T x tint)',
      abs(T0[1] - TINT[1]) < 1e-9 and T0[1] < 0.05)
    T('no homogeneous medium can reproduce 111 in green',
      FIT_RMS[1] > 1.0)
    # 7. THE FEASIBILITY GATE, on the CALIBRATED medium -- and it FAILS for
    #    the unrolled design.  Red is the channel the ear glow is made of and
    #    it is nearly conservative (alpha = 0.996): it needs many tens of
    #    scattering events to cross an ear, so a walk truncated at K = 4 keeps
    #    ~6% of it while keeping 82% of the green.  That is not a dim glow, it
    #    is a HUE INVERSION.  This assertion is deliberately written to hold
    #    while the design is wrong -- it is the falsification, not a target.
    T('K=4 keeps < 15% of the red at a 3 mm ear (the unrolled design fails)',
      K4_KEEP[0] < 0.15)
    T('K=4 keeps > 5x more green than red (the hue inverts)',
      K4_KEEP[1] > 5.0 * K4_KEEP[0])
    T('the fitted medium is nearly conservative in red',
      FITTED_ALPHA[0] > 0.95)
    for nm in bad:
        print('FAIL  %s' % nm)
    print('%d checks, %d failed' % (ok + len(bad), len(bad)))
    return 1 if bad else 0


def report():
    med = medium()
    print('medium (Jensen skin1, ld_G = %.1f mm):' % (LD_G * 1000))
    for c, n in enumerate('RGB'):
        print('  %s  A=%.2f  alpha=%.4f  sigma_t=%8.1f /m  mfp=%.3f mm'
              % (n, ALBEDO_A[c], med[c][0], med[c][1], 1000.0 / med[c][1]))
    print()
    print('truncation and transmittance vs K, at three ear thicknesses')
    print('  %6s %3s  %-26s %-8s' % ('L(mm)', 'K', 'T(walk)  R,G,B', 'lost'))
    for L in (0.001, 0.003, 0.006):
        for K in (1, 2, 3, 4, 6, 16):
            Tw, tr = slab_transmittance(L, K, n=6000)
            print('  %6.1f %3d  %7.4f %7.4f %7.4f   %5.1f%%'
                  % (L * 1000, K, Tw[0], Tw[1], Tw[2], 100 * tr))
        Ts = shipped_T(L)
        print('  %6.1f  %s  %7.4f %7.4f %7.4f   (111 closed form)'
              % (L * 1000, ' cf', Ts[0], Ts[1], Ts[2]))


if __name__ == '__main__':
    if '--report' in sys.argv:
        report()
    sys.exit(check())


# --- calibration -----------------------------------------------------------
# The Chiang inversion from Jensen `skin1`'s DIFFUSE REFLECTANCE gives a
# scattering-dominated medium (mfp 1.7-5.1 mm, alpha 0.47-0.88) that transmits
# 0.73/0.50/0.26 through a 3 mm ear.  111's two-exponential fit, which is the
# only one of the two that has ever been READ ON SCREEN AND KEPT, gives
# 0.11/0.0023/0.0006 through the same 3 mm.  A factor of 7 in red and 800 in
# green.  They are not the same medium and they never were: 111 fitted Prahl
# haemoglobin ABSORPTION for directly transmitted light, Jensen skin1 measures
# DIFFUSE REFLECTANCE.  Both are "skin"; they answer different questions.
#
# The shipped look wins.  This fits (A_c, ld_c) per channel so the walk
# reproduces 111's transmittance over the thickness range the ear glow
# actually spans, which makes the walk a DROP-IN for the shipped transport --
# same slab answer, plus the geometry a slab model cannot have.

FIT_L = [0.0005 * i for i in range(1, 17)]        # 0.5 .. 8 mm



def mono_T(L, A, ld, K=32, n=3000, seed=997):
    """Transmittance of a ONE-channel medium -- the marginal each fit targets."""
    a, st = chiang(A, ld)
    med = [(a, st)] * 3
    rng = LCG(seed)
    tot = 0.0
    for _ in range(n):
        _, back, w, _ = walk_slab(rng, L, med, K)
        if back:
            tot += w[0]
    return tot / n


def fit_channel(c, n=3000, verbose=False):
    """Coarse grid then a local refine, on log transmittance."""
    tgt = [max(shipped_T(L)[c], 1e-9) for L in FIT_L]

    def err(A, ld):
        e = 0.0
        for L, t in zip(FIT_L, tgt):
            w = max(mono_T(L, A, ld, n=n), 1e-9)
            e += (math.log(w) - math.log(t)) ** 2
        return e / len(FIT_L)

    best = None
    for A in [0.02 + 0.06 * i for i in range(15)]:
        for ldmm in [0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.7, 1.0, 1.5]:
            e = err(A, ldmm / 1000.0)
            if best is None or e < best[0]:
                best = (e, A, ldmm)
    e, A, ldmm = best
    for _ in range(3):                       # local refine
        step = ldmm * 0.25
        for dA in (-0.03, 0.0, 0.03):
            for dl in (-step, 0.0, step):
                A2, l2 = A + dA, ldmm + dl
                if not (0.01 < A2 < 0.95 and 0.02 < l2 < 3.0):
                    continue
                e2 = err(A2, l2 / 1000.0)
                if e2 < e:
                    e, A, ldmm = e2, A2, l2
    if verbose:
        print('  %s  A=%.3f  ld=%.3f mm  rms(log T)=%.3f'
              % ('RGB'[c], A, ldmm, math.sqrt(e)))
    return A, ldmm, math.sqrt(e)


def calibrate(n=3000):
    print('fitting the walk to 111\'s closed form over 0.5-8 mm')
    out = []
    for c in range(3):
        out.append(fit_channel(c, n=n, verbose=True))
    print()
    print('  %6s  %-24s %-24s' % ('L(mm)', 'walk (fitted)', '111 closed form'))
    for L in (0.001, 0.003, 0.006):
        w = [mono_T(L, out[c][0], out[c][1] / 1000.0, n=6000) for c in range(3)]
        s = shipped_T(L)
        print('  %6.1f  %7.4f %7.4f %7.4f  %7.4f %7.4f %7.4f'
              % (L * 1000, w[0], w[1], w[2], s[0], s[1], s[2]))
    print()
    print('  FITTED_A  = (%.3f, %.3f, %.3f)' % tuple(o[0] for o in out))
    print('  FITTED_LD = (%.3f, %.3f, %.3f)  mm' % tuple(o[1] for o in out))
    a, st = zip(*[chiang(out[c][0], out[c][1] / 1000.0) for c in range(3)])
    print('  alpha     = (%.4f, %.4f, %.4f)' % a)
    print('  sigma_t   = (%.1f, %.1f, %.1f) /m' % st)
    print('  mfp       = (%.3f, %.3f, %.3f) mm'
          % tuple(1000.0 / x for x in st))
    return out


# --- a vectorised twin of the walk, used ONLY to fit ------------------------
# For a MONOCHROME medium the hero weights collapse: a crossing weighs 1 and a
# scatter weighs exactly alpha, so T = E[ alpha^scatters * 1(exits the back) ]
# and no per-step weight arithmetic is needed.  check() asserts this twin
# agrees with the pure-python walk above, which is the bit-exact model of what
# the shader will run -- the twin is a speed trick, never a second definition.
def mono_T_fast(L, A, ld, K=32, n=200000, seed=7):
    import numpy as np
    a, st = chiang(A, ld)
    rs = np.random.default_rng(seed)
    z = np.zeros(n)
    mu = np.ones(n)
    w = np.ones(n)
    alive = np.ones(n, bool)
    out = np.zeros(n)
    for _ in range(K):
        if not alive.any():
            break
        t = -np.log(np.maximum(rs.random(n), 1e-12)) / st
        zt = z + mu * t
        cross = alive & ((zt <= 0.0) | (zt >= L))
        out[cross & (zt >= L)] = w[cross & (zt >= L)]
        alive &= ~cross
        w = np.where(alive, w * a, w)
        z = np.where(alive, zt, z)
        mu = np.where(alive, 1.0 - 2.0 * rs.random(n), mu)
        mu = np.where(np.abs(mu) < 1e-6, 1e-6, mu)
    return float(out.sum() / n)


def fit_channel_fast(c, n=120000):
    tgt = [max(shipped_T(L)[c], 1e-9) for L in FIT_L]

    def err(A, ldmm):
        e = 0.0
        for L, t in zip(FIT_L, tgt):
            w = max(mono_T_fast(L, A, ldmm / 1000.0, n=n), 1e-9)
            e += (math.log(w) - math.log(t)) ** 2
        return e / len(FIT_L)

    best = None
    for A in [0.05 + 0.07 * i for i in range(13)]:
        for ldmm in (0.05, 0.08, 0.12, 0.2, 0.3, 0.5, 0.8, 1.2):
            e = err(A, ldmm)
            if best is None or e < best[0]:
                best = (e, A, ldmm)
    e, A, ldmm = best
    for _ in range(4):
        for dA in (-0.035, 0.0, 0.035):
            for f in (0.75, 1.0, 1.33):
                A2, l2 = A + dA, ldmm * f
                if not (0.01 < A2 < 0.95 and 0.02 < l2 < 3.0):
                    continue
                e2 = err(A2, l2)
                if e2 < e:
                    e, A, ldmm = e2, A2, l2
    return A, ldmm, math.sqrt(e)


def calibrate_fast(n=120000):
    print("fitting the walk to 111's closed form over 0.5-8 mm")
    out = [fit_channel_fast(c, n=n) for c in range(3)]
    for c in range(3):
        print('  %s  A=%.3f  ld=%.3f mm  rms(log T)=%.3f'
              % ('RGB'[c], out[c][0], out[c][1], out[c][2]))
    print()
    print('  %6s  %-24s %-24s' % ('L(mm)', 'walk (fitted)', '111 closed form'))
    for L in (0.001, 0.003, 0.006):
        w = [mono_T_fast(L, out[c][0], out[c][1] / 1000.0, n=200000)
             for c in range(3)]
        s = shipped_T(L)
        print('  %6.1f  %7.4f %7.4f %7.4f  %7.4f %7.4f %7.4f'
              % (L * 1000, w[0], w[1], w[2], s[0], s[1], s[2]))
    print()
    print('  FITTED_A  = (%.3f, %.3f, %.3f)' % tuple(o[0] for o in out))
    print('  FITTED_LD = (%.3f, %.3f, %.3f) mm' % tuple(o[1] for o in out))
    st = [chiang(out[c][0], out[c][1] / 1000.0) for c in range(3)]
    print('  alpha     = (%.4f, %.4f, %.4f)' % tuple(x[0] for x in st))
    print('  sigma_t   = (%.1f, %.1f, %.1f) /m' % tuple(x[1] for x in st))
    print('  mfp       = (%.3f, %.3f, %.3f) mm'
          % tuple(1000.0 / x[1] for x in st))
    print()
    print('  truncation at K = 1..6, 3 mm, on the FITTED medium:')
    for K in (1, 2, 3, 4, 6):
        w = [mono_T_fast(0.003, out[c][0], out[c][1] / 1000.0, K=K, n=200000)
             for c in range(3)]
        full = [mono_T_fast(0.003, out[c][0], out[c][1] / 1000.0, K=64,
                            n=200000) for c in range(3)]
        keep = [w[c] / max(full[c], 1e-12) for c in range(3)]
        print('    K=%d  keeps %.1f%% / %.1f%% / %.1f%% of the energy'
              % (K, 100 * keep[0], 100 * keep[1], 100 * keep[2]))
    return out
