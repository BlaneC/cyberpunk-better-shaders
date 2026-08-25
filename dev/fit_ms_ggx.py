#!/usr/bin/env python3
"""Fit the directional albedo of CP2077's *exact* specular lobe.

Energy compensation needs E_ss(NoV, roughness) -- the fraction of energy the
single-scattering microfacet lobe actually reflects. Published fits (Lazarov,
Karis) target the standard height-correlated Smith GGX; CP2077 ships a
different visibility approximation, and its A+B sum happens to collapse to a
NoV-independent line, which over-boosts at high roughness. So rather than
borrow a fit, integrate the game's own lobe.

The lobe, read directly from spv_0170 (the GGX block above the first diffuse
eval site, ~line 8842):

    alpha = R*R                       (%5655 = %5649 * %5649)
    D     = a2 / (pi * (NoH^2*(a2-1) + 1)^2)
    Vis   = 0.25 / ((NoV + NoL)*(1 - alpha/2) + alpha)
    spec  = F * D * Vis

E_ss is that with F=1, integrated against NoL over the hemisphere. The
compensation term spliced into the shader is then

    comp = 1 + strength * F0 * (1/E_ss - 1)

which is exactly 1.0 at R=0 (E_ss=1) and at strength=0 -- the regression mode.

Run: python3 fit_ms_ggx.py            (fit + report error)
     python3 fit_ms_ggx.py --dump-table
"""
import argparse

import numpy as np

# Integration resolution. The lobe is smooth in both parameters, so a modest
# grid converges; NT is the driver since the specular peak is narrow at low
# roughness.
NT, NP = 512, 256


def E_ss(mu_v, alpha):
    """Directional albedo of the game's lobe at view cosine mu_v.

    mu_v, alpha broadcast against each other; returns the same shape.
    """
    mu_v = np.asarray(mu_v, dtype=np.float64)
    alpha = np.asarray(alpha, dtype=np.float64)
    a2 = alpha * alpha

    # L sample grid over the hemisphere.
    th = (np.arange(NT) + 0.5) * (np.pi / 2) / NT
    ph = (np.arange(NP) + 0.5) * (2 * np.pi) / NP
    dth = (np.pi / 2) / NT
    dph = (2 * np.pi) / NP

    st, ct = np.sin(th), np.cos(th)
    # index layout: (theta, phi, <broadcast dims>)
    sh = (NT, NP) + (1,) * mu_v.ndim
    lx = (st[:, None] * np.cos(ph)[None, :]).reshape(sh)
    ly = (st[:, None] * np.sin(ph)[None, :]).reshape(sh)
    lz = np.broadcast_to(ct.reshape((NT, 1) + (1,) * mu_v.ndim), sh)

    sv = np.sqrt(np.clip(1.0 - mu_v * mu_v, 0.0, 1.0))
    # V = (sv, 0, mu_v)
    hx, hy, hz = lx + sv, ly, lz + mu_v
    hn = np.sqrt(hx * hx + hy * hy + hz * hz)
    hn = np.where(hn > 1e-12, hn, 1e-12)
    noh = np.clip(hz / hn, 0.0, 1.0)

    nol = np.clip(lz, 0.0, 1.0)
    nov = np.clip(mu_v, 1e-5, 1.0)

    denom = noh * noh * (a2 - 1.0) + 1.0
    D = a2 / (np.pi * denom * denom)
    Vis = 0.25 / ((nov + nol) * (1.0 - alpha / 2.0) + alpha)

    integrand = D * Vis * nol * st.reshape((NT, 1) + (1,) * mu_v.ndim)
    return integrand.sum(axis=(0, 1)) * dth * dph


def d_normalization(alpha):
    """Integrate GGX D against NoH over the hemisphere; must come out 1.0."""
    a2 = alpha * alpha
    th = (np.arange(NT) + 0.5) * (np.pi / 2) / NT
    dth, dph = (np.pi / 2) / NT, (2 * np.pi) / NP
    st, ct = np.sin(th), np.cos(th)
    den = ct * ct * (a2 - 1.0) + 1.0
    D = a2 / (np.pi * den * den)
    # phi-independent, so one phi row times NP columns
    return (D * ct * st).sum() * dth * dph * NP


def E_ref(mu_v, alpha):
    """Directional albedo of textbook height-correlated Smith GGX, F=1."""
    a2 = alpha * alpha
    th = (np.arange(NT) + 0.5) * (np.pi / 2) / NT
    ph = (np.arange(NP) + 0.5) * (2 * np.pi) / NP
    dth, dph = (np.pi / 2) / NT, (2 * np.pi) / NP
    st, ct = np.sin(th), np.cos(th)
    lx = st[:, None] * np.cos(ph)[None, :]
    ly = st[:, None] * np.sin(ph)[None, :]
    lz = np.broadcast_to(ct[:, None], (NT, NP))
    sv = np.sqrt(max(0.0, 1.0 - mu_v * mu_v))
    hx, hy, hz = lx + sv, ly, lz + mu_v
    hn = np.maximum(np.sqrt(hx * hx + hy * hy + hz * hz), 1e-12)
    noh = np.clip(hz / hn, 0.0, 1.0)
    nol = np.clip(lz, 0.0, 1.0)
    nov = max(mu_v, 1e-5)
    den = noh * noh * (a2 - 1.0) + 1.0
    D = a2 / (np.pi * den * den)
    gv = nol * np.sqrt(nov * nov * (1 - a2) + a2)
    gl = nov * np.sqrt(nol * nol * (1 - a2) + a2)
    V = 0.5 / np.maximum(gv + gl, 1e-9)
    return (D * V * nol * st[:, None]).sum() * dth * dph


def fit(mu, al, E):
    """Least-squares fit of E_ss on a separable-ish polynomial basis.

    Terms were chosen by inspecting residuals: energy loss grows roughly with
    alpha and is worst at grazing angles, so the basis mixes powers of alpha
    with (1-mu). Kept small because every term becomes spliced SPIR-V.
    """
    m, a = mu.ravel(), al.ravel()
    om = 1.0 - m
    basis = [
        np.ones_like(a), a, a * a, a * a * a,
        om, om * om,
        a * om, a * a * om, a * om * om, a * a * om * om,
    ]
    A = np.stack(basis, axis=1)
    coef, *_ = np.linalg.lstsq(A, E.ravel(), rcond=None)
    pred = (A @ coef).reshape(E.shape)
    return coef, pred


BASIS_SRC = """\
    om  = 1 - NoV
    Ess = c0 + c1*a + c2*a^2 + c3*a^3
        + c4*om + c5*om^2
        + c6*a*om + c7*a^2*om + c8*a*om^2 + c9*a^2*om^2
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-table", action="store_true")
    ap.add_argument("--n", type=int, default=32, help="fit grid resolution")
    ap.add_argument("--force-fit", action="store_true",
                    help="emit a fit anyway; for experimentation only")
    args = ap.parse_args()

    mu1 = np.linspace(0.02, 1.0, args.n)
    al1 = np.linspace(0.0, 1.0, args.n)
    mu, al = np.meshgrid(mu1, al1, indexing="ij")
    E = E_ss(mu, al)

    if args.dump_table:
        print("# NoV alpha E_ss")
        for i in range(0, args.n, max(1, args.n // 8)):
            for j in range(0, args.n, max(1, args.n // 8)):
                print(f"{mu[i, j]:.4f} {al[i, j]:.4f} {E[i, j]:.6f}")
        return

    print("=== integrated E_ss of CP2077's lobe as read from spv_0170 ===")
    print(f"grid {args.n}x{args.n}, integration {NT}x{NP}")

    # Integrator self-check: GGX D must integrate to 1 against NoH. If this
    # drifts from 1.0 the discrepancy below is the integrator's fault, not the
    # lobe reading's.
    print(f"\nintegrator self-check, GGX D normalization (must be ~1.0):")
    for a_ in (0.2, 0.5, 1.0):
        print(f"  alpha={a_:.2f}: {d_normalization(a_):.5f}")

    print("\n=== BLOCKER: as-read lobe vs correct Smith-correlated GGX ===")
    print(f"{'alpha':>6} {'NoV':>6} {'as-read':>9} {'correct':>9} {'ratio':>7}")
    for a_ in (0.25, 0.5, 1.0):
        for m_ in (1.0, 0.5):
            got = float(E_ss(np.array(m_), np.array(a_)))
            ref = float(E_ref(m_, a_))
            print(f"{a_:>6.2f} {m_:>6.2f} {got:>9.4f} {ref:>9.4f} {got / ref:>7.3f}")
    print("""
The as-read lobe reflects a fraction of the energy a correct GGX lobe does.
A shipped renderer does not discard 60-75% of its specular energy, so the
reading is wrong -- most likely %9948 is not a plain NoL (it is a phi out of
an area-light branch), or normalization lives in the %7581 weight rather than
in F*D*Vis. See dev/MS_GGX_NOTES.md section 2.

Energy compensation needs 1/E_ss in ABSOLUTE terms, so no fit is emitted until
E_ss reproduces offline. Rerun with --force-fit only for experimentation.""")

    if not args.force_fit:
        return
    coef, pred = fit(mu, al, E)
    err = pred - E
    print("\n=== experimental fit (NOT for splicing) ===")
    print(BASIS_SRC)
    for i, c in enumerate(coef):
        print(f"  c{i} = {c: .8f}")
    print(f"\nmax abs err {np.abs(err).max():.5f}   rms {np.sqrt((err**2).mean()):.5f}")
    print(f"min fitted E_ss {pred.min():.4f}")


if __name__ == "__main__":
    main()
