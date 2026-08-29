#!/usr/bin/env python3
"""Fit the directional albedo of CP2077's *exact* specular lobe.

Energy compensation needs E_ss(NoV, roughness) -- the fraction of energy the
single-scattering microfacet lobe actually reflects. Published fits (Lazarov,
Karis) target the standard height-correlated Smith GGX; CP2077 ships a
different visibility approximation, so rather than borrow a fit, integrate the
game's own lobe.

READ THE PUNCTUAL BLOCK, NOT THE AREA BLOCK
-------------------------------------------
spv_0170 carries *two* structurally identical GGX evaluators, selected at
line 8557 by `%5654 = (flags & 2) == 0`:

    %12540  punctual   lines 8558-8613   <- this one
    %12539  area/tube  lines 8623-9998

They differ only in what is fed to the shared formulas. The area block's
"NoL" (`%9948`) is a sphere/tube *illuminance* factor -- `%5407 +/- %5404` are
the two endpoints of a tube light, `%5402` is the sphere radius, `%9944` is
sin(sigma), and `%9947 = (max(NoL,-s)+s)^2 / (4s)` is Frostbite's sphere-light
horizon falloff. Its spec weight `%7581 = %9016 * %9007` carries Karis's
sphere normalization `(alpha/alpha')^2`. None of that belongs in a BRDF
integral. An earlier revision of this script read the area block by mistake;
that is what produced the "2-4x too low" blocker recorded in MS_GGX_NOTES.md.

The punctual block, which is the BRDF proper:

    %6767  NoL  = clamp(dot(N, L), 0, 1)
    %6782  NoV  = clamp(dot(N, V), 1e-6, 1)
    %6786  NoH  %6790  VoH
    alpha = R*R                      (%5655 = %5649 * %5649)
    D     = a2 / (pi * (NoH^2*(a2-1) + 1)^2)                    (%6799)
    Vis   = 0.25 / ((NoV + NoL)*(1 - alpha/2) + alpha)          (%6805)
    spec  = F * D * Vis                                         (%6818..%6820)

SPECULAR IS NOT MULTIPLIED BY NoL
---------------------------------
At the consumption site (lines 8890-8912) diffuse and specular are assembled
asymmetrically:

    diffuse  %5111 = (albedo/pi) * lightColor * %7583     %7583 = NoL
    specular %5132 = lightColor  * intensity  * %7575 * %7581
                                                          %7581 = 1  (punctual)

So `F * D * Vis` is already the BRDF-times-cosine that the shader renders; the
cosine is folded into the engine's Vis. Integrating it against another NoL --
which this script previously did -- undercounts by a factor of ~<NoL>, and was
the second half of the blocker.

Note the Vis denominator is exactly the *sum* of the two Smith-Schlick G1
denominators, with k = alpha/2:

    (NoL*(1-k) + k) + (NoV*(1-k) + k)  ==  (NoL+NoV)*(1-alpha/2) + alpha

whereas a correct separable Smith uses their *product*. That substitution is
the source of both the constant factor below and the grazing error in §2.

THE NORMALIZER IS EXACTLY 0.5
-----------------------------
As alpha -> 0 the NDF collapses to H = N, so L -> mirror(V) and NoL -> NoV.
With dw_L = 4*VoH*dw_H and INT D(H)*NoH dw_H = 1, the integral tends to

    E_ss(a->0) = 4*NoV * Vis(NoL=NoV) = 4*NoV * 0.25/(2*NoV) = 0.5

independent of NoV -- confirmed numerically to 4 decimal places by
--self-check. The engine's lobe therefore sits a uniform factor of 2 below an
energy-conserving one at mirror roughness. Whether that 2x is a real deficit
absorbed into authored light intensities, or another factor upstream in
`%5650`/`%7604`, is *not resolved* and does not need to be: compensation is
defined relative to the lobe's own mirror limit,

    E_rel(a, NoV) = E_ss(a, NoV) / 0.5
    comp          = 1 + strength * F0 * max(1/E_rel - 1, 0)

which is exactly 1.0 at alpha=0 and at strength=0 -- the regression mode --
and is immune to any constant scale error in the lobe.

Run: python3 fit_ms_ggx.py              (fit + report error)
     python3 fit_ms_ggx.py --self-check (integrator validation)
     python3 fit_ms_ggx.py --dump-table
"""
import argparse

import numpy as np

# Importance-sample count. The estimator below draws H from the GGX NDF, so it
# is well conditioned at every roughness -- unlike the uniform hemisphere grid
# this script used to use, which missed the near-delta lobe at small alpha and
# off-axis NoV and produced spurious E_ss values there.
NSAMP = 1 << 16


def _hammersley(n):
    """Deterministic low-discrepancy 2D sequence (radical-inverse base 2)."""
    i = np.arange(n, dtype=np.uint64)
    b = i.copy()
    b = ((b << np.uint64(16)) | (b >> np.uint64(16))) & np.uint64(0xFFFFFFFF)
    b = ((b & np.uint64(0x55555555)) << np.uint64(1)) | ((b & np.uint64(0xAAAAAAAA)) >> np.uint64(1))
    b = ((b & np.uint64(0x33333333)) << np.uint64(2)) | ((b & np.uint64(0xCCCCCCCC)) >> np.uint64(2))
    b = ((b & np.uint64(0x0F0F0F0F)) << np.uint64(4)) | ((b & np.uint64(0xF0F0F0F0)) >> np.uint64(4))
    b = ((b & np.uint64(0x00FF00FF)) << np.uint64(8)) | ((b & np.uint64(0xFF00FF00)) >> np.uint64(8))
    return i.astype(np.float64) / n, b.astype(np.float64) * 2.3283064365386963e-10


def E_ss(nov, alpha, vis="shader", with_nol=False, nsamp=NSAMP):
    """Directional albedo of the lobe at view cosine `nov`, F = 1.

    E_ss = INT D(H) * Vis dw_L. Sampling H ~ D*NoH and using dw_L = 4*VoH*dw_H
    collapses the estimator to mean(Vis * 4*VoH / NoH).

    vis="shader"      the game's 0.25/((NoV+NoL)*(1-a/2)+a)
    vis="height_corr" textbook height-correlated Smith, for reference
    with_nol          apply an extra NoL; the shader does NOT (see module doc),
                      kept only so the old reading can be reproduced
    """
    nov = max(float(nov), 1e-4)
    alpha = float(alpha)
    a2 = alpha * alpha
    u1, u2 = _hammersley(nsamp)

    # GGX NDF sample in tangent space (N = +z).
    ct = np.sqrt((1.0 - u1) / (1.0 + (a2 - 1.0) * u1))
    st = np.sqrt(np.clip(1.0 - ct * ct, 0.0, 1.0))
    phi = 2.0 * np.pi * u2
    hx, hy, hz = st * np.cos(phi), st * np.sin(phi), ct

    vx, vz = np.sqrt(max(0.0, 1.0 - nov * nov)), nov
    voh = vx * hx + vz * hz
    # L = reflect(V, H)
    lz = 2.0 * voh * hz - vz
    nol = np.clip(lz, 0.0, 1.0)

    k = alpha / 2.0
    if vis == "shader":
        Vis = 0.25 / ((nov + nol) * (1.0 - k) + alpha)
    elif vis == "height_corr":
        gv = nol * np.sqrt(nov * nov * (1 - a2) + a2)
        gl = nov * np.sqrt(nol * nol * (1 - a2) + a2)
        Vis = 0.5 / np.maximum(gv + gl, 1e-9)
    else:
        raise ValueError(vis)

    w = Vis * 4.0 * np.maximum(voh, 0.0) / np.maximum(ct, 1e-9)
    if with_nol:
        w = w * nol
    # Directions below the horizon carry no light.
    return float(np.where(lz > 0.0, w, 0.0).mean())


# The lobe's own mirror-roughness limit; derived analytically in the module
# docstring and checked by --self-check.
E_MIRROR = 0.5

# Every basis term carries a factor of alpha, so the fit is identically 0 at
# alpha = 0 by construction -- comp == 1.0 there with no reliance on fit error.
ALPHA_BASIS = ("a", "a^2", "a^3", "a^4")

FIT_SRC = """\
    a    = roughness * roughness
    loss = j0*a + j1*a^2 + j2*a^3 + j3*a^4
    comp = 1 + strength * F0 * max(loss, 0)
"""


def _alpha_fit(al, target):
    A = np.stack([al, al ** 2, al ** 3, al ** 4], axis=1)
    coef, *_ = np.linalg.lstsq(A, target, rcond=None)
    return coef, A @ coef


def _self_check():
    print("=== integrator self-check ===")
    print("\nheight-correlated Smith GGX with NoL must -> 1.0 as alpha -> 0,")
    print("and reproduce the published directional albedo elsewhere:")
    for a in (1e-4, 0.05, 0.25, 0.5, 1.0):
        r = " ".join(f"{E_ss(m, a, 'height_corr', True):.4f}" for m in (1.0, 0.5))
        print(f"  alpha={a:<8} NoV=1.0/0.5: {r}")

    # alpha must be small enough that horizon clipping has died out: at
    # grazing NoV a finite alpha puts part of the lobe below the horizon,
    # which biases the limit low (0.4868 at NoV=0.02, alpha=1e-3). That is a
    # truncation artefact of evaluating a limit at finite alpha, not a
    # property of the lobe -- it decays monotonically to 0.5.
    print("\nthe game's lobe (no NoL) must -> 0.5 at every NoV as alpha -> 0:")
    mus = (1.0, 0.8, 0.5, 0.25, 0.1, 0.02)
    vals = [E_ss(m, 1e-6, "shader", False) for m in mus]
    for m, v in zip(mus, vals):
        print(f"  NoV={m:<5} E_ss={v:.6f}   (analytic 0.5)")
    worst = max(abs(v - E_MIRROR) for v in vals)
    print(f"\n  worst deviation from the analytic limit: {worst:.2e}")
    print("  PASS" if worst < 1e-3 else "  FAIL")

    print("\n  horizon-clipping decay, worst case NoV=0.02:")
    for a in (1e-3, 1e-4, 1e-5, 1e-6):
        print(f"    alpha={a:<7} E_ss={E_ss(0.02, a, 'shader', False):.6f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-table", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--n", type=int, default=33, help="fit grid resolution")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return

    al1 = np.linspace(0.0, 1.0, args.n)
    mus = (1.0, 0.75, 0.5, 0.25, 0.1)

    if args.dump_table:
        print("# alpha NoV E_ss E_rel")
        for a in al1:
            for m in mus:
                e = E_ss(m, max(a, 1e-5), "shader", False)
                print(f"{a:.4f} {m:.4f} {e:.6f} {e / E_MIRROR:.6f}")
        return

    print("=== E_rel of CP2077's punctual lobe (E_ss / 0.5) ===")
    print("1.0 == energy-conserving relative to its own mirror limit\n")
    print(f"{'alpha':>6} " + " ".join(f"{m:>8.2f}" for m in mus))
    for a in (0.05, 0.1, 0.25, 0.5, 0.75, 1.0):
        row = " ".join(f"{E_ss(m, a, 'shader', False) / E_MIRROR:>8.4f}" for m in mus)
        print(f"{a:>6.2f} {row}")

    print("\nfor contrast, correct height-correlated Smith GGX:")
    for a in (0.05, 0.25, 0.5, 1.0):
        row = " ".join(f"{E_ss(m, a, 'height_corr', True):>8.4f}" for m in mus)
        print(f"{a:>6.2f} {row}")

    print("""
Two separate deviations are visible, and only one of them is ours to fix:

  * roughness-driven loss at NoV=1 -- 1.04 at alpha=0.25 down to 0.58 at
    alpha=1. This is the multiple-scattering energy GGX drops, and it is what
    energy compensation is for. Note the game loses about HALF what a correct
    GGX does (0.58 vs 0.31 at alpha=1): its sum-form Vis over-brightens at
    high roughness and partly self-compensates. Splicing a textbook
    Lazarov/Karis fit here would roughly double-compensate.

  * grazing loss at low alpha -- 0.72 at NoV=0.1, alpha=0.05, where a correct
    GGX holds 0.91. That is the sum-vs-product Vis substitution being wrong at
    grazing angles, not multiple scattering. It is large, it is a different
    defect, and compensating it would re-light every grazing surface in the
    game. Excluded deliberately: the fit below is alpha-only.""")

    target = np.array([1.0 / (E_ss(1.0, max(a, 1e-5), "shader", False) / E_MIRROR) - 1.0
                       for a in al1])
    coef, pred = _alpha_fit(al1, target)

    print("\n=== fit: energy shortfall at NoV = 1, alpha-only ===")
    print(FIT_SRC)
    for i, c in enumerate(coef):
        print(f"  j{i} = {c: .8f}")
    print(f"\n  max abs err {np.abs(pred - target).max():.5f}"
          f"   rms {np.sqrt(((pred - target) ** 2).mean()):.5f}")
    print(f"  loss at alpha=1: {target[-1]:.4f}"
          f"  -> +{100 * target[-1] * 0.9:.0f}% spec on an F0=0.9 metal,"
          f" +{100 * target[-1] * 0.04:.0f}% on an F0=0.04 dielectric")
    print("\n  max(loss, 0) in the shader clamps the small negative dip near")
    print("  alpha=0.25, so compensation never darkens below vanilla.")


if __name__ == "__main__":
    main()
