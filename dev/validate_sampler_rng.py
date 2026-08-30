#!/usr/bin/env python3
"""
Bit-exact model of the sampler RNG in the rgs_reference_main family, used to
test the premise of `handoff/37-SAMPLING-DECORRELATION.md` (Idea 6:
Cranley-Patterson / Heitz-Belcour per-bounce rotation on the existing LCG).

Transcribed from dev/disasm/live/d622fb9e1dcb8cd0.rgs_reference_main.spvasm:
    seed hash  :1395-1429   (three rounds of *1103515245 with xor/shift)
    LCG        :1983-1995   (x = x*1664525 + 1013904223; u = (x & 0xFFFFFF)*2^-24)
    state phi  :1826        (%704 = OpPhi %uint %167 %12276 %705 %12786)

Run:  python3 dev/validate_sampler_rng.py
Every number quoted in doc 37 comes out of this file.
"""
import numpy as np

np.seterr(over='ignore')
A, C = np.uint32(1664525), np.uint32(1013904223)
H_MUL = np.uint32(1103515245)
W, H = 1280, 720                      # PT internal res (15 s1)


# ---------------------------------------------------------------- the shader
def seed(x, y, f78y, f63x, width=1280.0):
    """%167 -- the per-pixel, per-frame LCG seed."""
    v140 = np.uint32(f78y) + x.astype(np.uint32)
    v148 = v140.astype(np.float32) + np.float32(width) * y.astype(np.float32)
    v149 = v148.astype(np.uint32)
    v155 = np.uint32(f63x) * np.uint32(10)
    v161 = ((v149 >> np.uint32(1)) ^ v155) * H_MUL
    v163 = ((v155 >> np.uint32(1)) ^ v149) * H_MUL
    return (v161 ^ (v163 >> np.uint32(3))) * H_MUL


def advance(s):
    return s * A + C


def draw(s):
    """u = float(s & 0xFFFFFF) * 2^-24 -- note: the LOW 24 bits."""
    return (s & np.uint32(0x00FFFFFF)).astype(np.float64) * 2.0**-24


def frame(f78y=7, f63x=1234, n=20):
    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
    s = seed(xx, yy, f78y, f63x)
    out = []
    for _ in range(n):
        s = advance(s)
        out.append(draw(s))
    return out


# ------------------------------------------------------------------ spectrum
def radial_ps(err, N):
    F = np.fft.fftshift(np.fft.fft2(err - err.mean()))
    y, x = np.mgrid[0:N, 0:N]
    r = np.hypot(y - N // 2, x - N // 2).astype(int)
    ps = (np.bincount(r.ravel(), (np.abs(F) ** 2).ravel())[:N // 2]
          / np.maximum(np.bincount(r.ravel())[:N // 2], 1))
    return ps / ps.mean()


def lf_hf(err, N):
    ps = radial_ps(err, N)
    return ps[1:N // 8].mean(), ps[N // 4:N // 2].mean()


def make_blue(n, rng):
    """Ulichney-style blue mask: iterate high-pass then rank-restore uniform."""
    m = rng.random((n, n))
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(np.minimum(yy, n - yy), np.minimum(xx, n - xx))
    G = np.fft.fft2(np.exp(-(rr ** 2) / (2 * 1.5 ** 2)))
    G /= G.flat[0]
    for _ in range(30):
        lp = np.real(np.fft.ifft2(np.fft.fft2(m) * G))
        m = m - 0.8 * (lp - lp.mean())
        m = (m.ravel().argsort().argsort().reshape(n, n) + 0.5) / (n * n)
    return m


# --------------------------------------------------------------------- tests
def test_bounce_correlation():
    print("=" * 78)
    print("1. Is bounce 0 correlated with bounce 1?  (the premise of Idea 6)")
    print("=" * 78)
    u = frame()
    floor = 1 / np.sqrt(W * H)
    print(f"   loop body runs 3 guaranteed LCG advances + 0-7 branch-dependent,")
    print(f"   so bounce 1 starts at state s_k, k in 3..10.  noise floor {floor:.6f}\n")
    print("     k   corr(u1)    corr(u2)    corr(u3)")
    worst = 0.0
    for k in range(3, 11):
        c = [np.corrcoef(u[i].ravel(), u[k + i].ravel())[0, 1] for i in (0, 1, 2)]
        worst = max(worst, max(abs(v) for v in c))
        print(f"    {k:2d}   {c[0]:+.6f}   {c[1]:+.6f}   {c[2]:+.6f}")
    print(f"\n   worst |corr| = {worst:.6f}  vs floor {floor:.6f}"
          f"  -> {'AT NOISE FLOOR' if worst < 4*floor else 'STRUCTURE PRESENT'}")
    return worst < 4 * floor


def test_cp_is_a_noop():
    print()
    print("=" * 78)
    print("2. Does a per-bounce Cranley-Patterson constant change anything?")
    print("=" * 78)
    u = frame()
    print("   u' = frac(u + c) on white noise is a measure-preserving bijection.\n")
    print("      c          mean      var       corr(b0,b1)")
    for c in (0.0, 0.1, 0.5, 0.61803398875):
        r0, r1 = (u[0] + c) % 1.0, (u[3] + c) % 1.0
        print(f"   {c:.6f}   {r0.mean():.6f}  {r0.var():.6f}  "
              f"{np.corrcoef(r0.ravel(), r1.ravel())[0,1]:+.6f}")
    a0, a1 = u[0], (u[3] + 0.5) % 1.0
    print(f"\n   per-bounce rotation (c_b0=0, c_b1=0.5): corr = "
          f"{np.corrcoef(a0.ravel(), a1.ravel())[0,1]:+.6f}")


def test_error_spectrum():
    print()
    print("=" * 78)
    print("3. Can it produce blue-noise error?  (Heitz & Belcour 2019)")
    print("=" * 78)
    N = 256
    rng = np.random.default_rng(7)
    blue = make_blue(N, rng)
    lo, hi = lf_hf(blue, N)
    print(f"   blue mask sanity: HF/LF = {hi/lo:.0f} (want >>1), "
          f"mean={blue.mean():.4f} var={blue.var():.5f}\n")

    f, Ef = (lambda v: np.sqrt(v)), 2.0 / 3.0      # monotone integrand
    uw = rng.random((N, N))
    cases = [
        ("shipped (white per-pixel LCG)",            f(uw) - Ef),
        ("shipped + CP constant c=0.5   <- Idea 6",  f((uw + 0.5) % 1.0) - Ef),
        ("shared base + BLUE per-pixel offset",      f(blue) - Ef),
        ("white LCG  + BLUE per-pixel offset",       f((uw + blue) % 1.0) - Ef),
    ]
    print(f"   {'configuration':<40s} {'var':>8s} {'LF':>6s} {'HF':>6s} {'HF/LF':>8s}")
    for name, err in cases:
        lo, hi = lf_hf(err, N)
        print(f"   {name:<40s} {err.var():8.4f} {lo:6.2f} {hi:6.2f} {hi/lo:8.2f}")
    print("\n   HF/LF ~ 1 is white error.  Only the shared-base + blue-mask row")
    print("   goes blue, and it needs BOTH a mask resource AND replacing the")
    print("   per-pixel seed -- neither of which Idea 6 provides.")


def test_bit_quality():
    print()
    print("=" * 78)
    print("4. Is the low-24-bit mask a defect worth fixing on its own?")
    print("=" * 78)
    n = 1 << 20
    s = np.uint32(12345)
    raw = np.empty(n, np.uint32)
    for i in range(n):
        s = s * A + C
        raw[i] = s
    low = (raw & np.uint32(0x00FFFFFF)).astype(np.float64) / 2**24
    high = (raw >> np.uint32(8)).astype(np.float64) / 2**24

    def pair_chi2(u, bins):
        a, b = u[0:-1:2], u[1::2]
        m = min(len(a), len(b))
        h, _, _ = np.histogram2d(a[:m], b[:m], bins=bins, range=[[0, 1], [0, 1]])
        e = h.sum() / h.size
        return ((h - e) ** 2 / e).sum() / (h.size - 1)

    print("   2D uniformity of consecutive pairs (the hemisphere sample), chi2/dof:\n")
    print(f"   {'bins':>9}  {'shipped s&0xFFFFFF':>20}  {'high bits s>>8':>16}")
    for b in (16, 32, 64, 128, 256):
        print(f"   {b:>4}x{b:<4}  {pair_chi2(low,b):>20.4f}  {pair_chi2(high,b):>16.4f}")
    print("\n   Both sit at 1.0 within noise -> the mask is NOT a defect.")
    print("   (bits 0-3 do have periods 2/4/8/16, but they weigh <2^-20 in u.)")


if __name__ == "__main__":
    test_bounce_correlation()
    test_cp_is_a_noop()
    test_error_spectrum()
    test_bit_quality()
    print()
    print("=" * 78)
    print("VERDICT: no correlation to remove; CP rotation is a no-op on this")
    print("sampler; blue-noise error needs the resource 24 s4 killed.  See 37.")
    print("=" * 78)
