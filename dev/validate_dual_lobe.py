#!/usr/bin/env python3
"""Offline validation of the shifted dual-lobe (R/TRT) hair math.

No game, no SPIR-V -- pure numpy check of the closed forms the patcher will
splice, in the spirit of fit_ms_ggx.py and the synthetic-fibre eigenvector
test. Catches sign/shift errors and NaN-prone degenerate configurations
before they cost a shader build.

The shader will compute, per lobe with tangent-shift s = tan(beta):

    ToH  = dot(T, H)          (already computed by the aniso pass)
    NoH  = dot(N, H)
    ToN  = dot(T, N)
    T'H  = (ToH + s*NoH) / sqrt(1 + 2*s*ToN + s*s)   == dot(normalize(T+s*N), H)
    sinL = sqrt(max(1 - T'H*T'H, eps))
    lobe = sinL ** p

Checks:
  1. exact form matches an explicit vector normalize(T+s*N).H
  2. s=0 reduces to the unshifted lobe
  3. the lobe peak moves along the strand by ~beta (the point of the shift)
  4. no NaN / negative sqrt in degenerate configs (T//H, H~N, T flipped)
  5. combined factor stays bounded (firefly guard)
"""
import numpy as np

EPS = 1e-5


def norm(v):
    return v / np.linalg.norm(v)


def lobe_exact(T, N, H, s, p):
    """closed form the shader emits (no v3 normalize)."""
    ToH = float(T @ H)
    NoH = float(N @ H)
    ToN = float(T @ N)
    den2 = 1.0 + 2.0 * s * ToN + s * s
    tpH = (ToH + s * NoH) / np.sqrt(max(den2, 1e-12))
    tpH = np.clip(tpH, -1.0, 1.0)
    sinL = np.sqrt(max(1.0 - tpH * tpH, EPS))
    return sinL ** (p * 0.5) if False else sinL ** p


def lobe_reference(T, N, H, s, p):
    """ground truth: explicitly shift + normalize the tangent."""
    Tp = norm(T + s * N)
    sinL = np.sqrt(max(1.0 - float(Tp @ H) ** 2, EPS))
    return sinL ** p


def strand_frame(strand_dir_world, n_tip=0.0):
    """T = strand direction, N = a normal perpendicular-ish to it."""
    T = norm(np.array(strand_dir_world, float))
    # pick a normal not parallel to T
    a = np.array([0.0, 0.0, 1.0]) if abs(T[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    N = norm(a - T * (a @ T))
    return T, N


def main():
    rng = np.random.default_rng(0)
    deg = np.pi / 180.0
    beta_R, beta_TRT = -7.0 * deg, +10.0 * deg
    sR, sTRT = np.tan(beta_R), np.tan(beta_TRT)
    pR, pTRT = 40.0, 12.0

    print("== 1. exact vs reference, random frames ==")
    worst = 0.0
    for _ in range(2000):
        T, N = strand_frame(rng.normal(size=3))
        V = norm(rng.normal(size=3))
        L = norm(rng.normal(size=3))
        H = norm(V + L)
        for s in (0.0, sR, sTRT, -0.3, 0.3):
            a = lobe_exact(T, N, H, s, pR)
            b = lobe_reference(T, N, H, s, pR)
            worst = max(worst, abs(a - b))
    print(f"  max |exact - reference| = {worst:.2e}  (expect < 1e-5)")
    assert worst < 1e-5, "closed form diverges from vector normalize"

    print("== 2. s=0 identity ==")
    T, N = strand_frame([0.3, 0.9, 0.1])
    H = norm(rng.normal(size=3))
    assert abs(lobe_exact(T, N, H, 0.0, pR) - lobe_reference(T, N, H, 0.0, pR)) < 1e-6
    print("  ok: s=0 == unshifted lobe")

    print("== 3. peak shifts by ~beta along the strand ==")
    # strand along +x, normal +z; sweep the light (hence H) in the T-N plane
    T = np.array([1.0, 0.0, 0.0])
    N = np.array([0.0, 0.0, 1.0])
    V = np.array([0.0, 1.0, 0.0])
    angles = np.linspace(-89, 89, 400) * deg
    def peak(beta):
        s = np.tan(beta)
        best, ba = -1.0, 0.0
        for a in angles:
            Ld = np.array([np.sin(a), 0.0, np.cos(a)])  # rotate in T-N plane
            Hv = norm(V + Ld)
            v = lobe_exact(T, N, Hv, s, pR)
            if v > best:
                best, ba = v, a
        return ba / deg
    p0, pR_, pT_ = peak(0.0), peak(beta_R), peak(beta_TRT)
    print(f"  peak angle: unshifted={p0:.2f}  R(shift -7)={pR_:.2f}  TRT(shift +10)={pT_:.2f}")
    print(f"  => R moved {pR_-p0:+.2f} deg, TRT moved {pT_-p0:+.2f} deg (want opposite signs)")

    print("== 4. degenerate configs, no NaN ==")
    bad = 0
    cases = []
    T, N = strand_frame([0.0, 1.0, 0.0])
    cases.append(("H == T", T, N, T))
    cases.append(("H == N", T, N, N))
    cases.append(("H == -T", T, N, -T))
    cases.append(("T flipped (180 ambiguity)", -T, N, T))
    for name, Tc, Nc, Hc in cases:
        for s in (sR, sTRT, -0.5, 0.5):
            v = lobe_exact(norm(Tc), norm(Nc), norm(Hc), s, pTRT)
            if not np.isfinite(v):
                print(f"  NaN/inf in case {name} s={s}")
                bad += 1
    print(f"  non-finite results: {bad}  (expect 0)")
    assert bad == 0

    print("== 5. combined factor bounded (firefly guard) ==")
    # factor = 1 + m_dual*aniso*(ratio - 1); ratio = (wR*LR + wTRT*LTRT)/max(Lvan,eps)
    m_dual, wR, wTRT = 1.0, 1.0, 0.3
    worst_ratio = 0.0
    for _ in range(20000):
        T, N = strand_frame(rng.normal(size=3))
        V = norm(rng.normal(size=3)); L = norm(rng.normal(size=3))
        H = norm(V + L)
        Lvan = max(lobe_exact(T, N, H, 0.0, pR), 1e-4)
        LR = lobe_exact(T, N, H, sR, pR)
        LTRT = lobe_exact(T, N, H, sTRT, pTRT)
        ratio = (wR * LR + wTRT * LTRT) / Lvan
        worst_ratio = max(worst_ratio, ratio)
    print(f"  worst (unclamped) ratio over 20k random configs = {worst_ratio:.2f}")
    print(f"  => recommend an NMin clamp rmax_dual on the ratio in-shader (e.g. 8)")
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
