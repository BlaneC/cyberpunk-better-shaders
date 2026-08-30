#!/usr/bin/env python3
"""Demonstrate the regression-to-the-mean bias in ab_compare.py's --tone bins.

This is a DIAGNOSTIC. It deliberately does NOT change ab_compare.py, whose
--tone output is what handoff/46 quotes. Its purpose is to let a reviewer
reproduce the bias and judge how much of each --tone conclusion survives.

The bias: --tone assigns pixels to bins using the BASELINE image's own
luminance, then reports (test - baseline) per bin. The baseline's per-pixel
noise therefore drives bin assignment, and the difference is anti-correlated
with it -- pixels that landed in a low bin partly because they were noisily
dark show a spuriously POSITIVE delta, and the top bin a spuriously NEGATIVE
one. Binning by the TEST image instead flips the artefact. Neither is right.

Binning by a SMOOTHED baseline decorrelates assignment from the per-pixel
noise (tone is low-frequency, PT/denoiser noise is high-frequency) while
preserving the lit/shadow structure the bins are meant to separate. Where the
smoothed rows agree with the raw row, the finding is real; where they do not,
the raw row is an artefact.

Usage:
  dev/ab_bias_check.py BASE.png TEST.png --crop X0,Y0,X1,Y1 --mask M.npy
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

REC709 = [0.2126, 0.7152, 0.0722]


def bins(binvar, a, b, m, label, nb=6):
    q = np.percentile(binvar[m], np.linspace(0, 100, nb + 1))
    out = []
    for lo, hi in zip(q[:-1], q[1:]):
        sel = m & (binvar >= lo) & (binvar < hi)
        if sel.sum() < 400:
            out.append(float("nan")); continue
        out.append(100 * (b[sel] - a[sel]).mean() / a[sel].mean())
    print("  %-36s " % label + " ".join("%+7.2f%%" % v for v in out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("test")
    ap.add_argument("--crop", required=True); ap.add_argument("--mask", required=True)
    ap.add_argument("--bins", type=int, default=6)
    g = ap.parse_args()
    X0, Y0, X1, Y1 = map(int, g.crop.split(","))
    m = np.load(g.mask)
    def cr(p):
        return np.asarray(Image.open(p).convert("RGB"), float)[Y0:Y1, X0:X1] @ REC709
    a, b = cr(g.base), cr(g.test)

    print("\n%s -> %s" % (g.base, g.test))
    print("  %-36s " % "bin variable"
          + " ".join("%8s" % ("q%d" % i) for i in range(1, g.bins + 1)))
    bins(a, a, b, m, "raw BASELINE  <-- what --tone uses", g.bins)
    bins(b, a, b, m, "raw TEST      <-- flips the artefact", g.bins)
    for s in (4, 8, 16, 32):
        bins(ndi.gaussian_filter(a, s), a, b, m, "smoothed baseline, sigma=%-2d" % s, g.bins)


if __name__ == "__main__":
    main()
