#!/usr/bin/env python3
"""High-pass texture energy inside a per-scene skin mask, for N captures.

Why this exists: the roughness rungs move the skin MEAN by ~1.4% but the fine
texture energy by 60-76%. The user described `rough-1.3` as "turning details
back on ... like a detail filter" -- a texture claim that a mean cannot show
and tone bins only hint at. Score every rung on this as well.

  fine/mid/coarse = std of (img - gaussian(img, sigma)) inside the mask, for
                    sigma 1.0 / 2.5 / 6.0 px. `fine` is pore/freckle scale.
  rms%            = local RMS contrast, (img - boxmean9) / boxmean9, in percent.

Usage:
  dev/ab_texture.py --crop X0,Y0,X1,Y1 --mask masks/S1.npy LABEL=img.png ...   (label may contain "="; path is after the LAST "=")
The FIRST image is the reference the percentages are relative to.
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

REC709 = [0.2126, 0.7152, 0.0722]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", required=True)
    ap.add_argument("--mask", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("items", nargs="+", help="LABEL=path.png, reference first")
    g = ap.parse_args()
    X0, Y0, X1, Y1 = map(int, g.crop.split(","))
    m = np.load(g.mask)

    print("\n%s" % (g.label or "texture inside %s" % g.mask))
    print("  %-20s %8s %8s %8s %9s %10s"
          % ("", "fine", "mid", "coarse", "rms%", "fine vs ref"))
    ref = None
    for it in g.items:
        lab, path = it.rsplit("=", 1)   # labels may contain "=", e.g. skinspec=off
        img = np.asarray(Image.open(path).convert("RGB"), float)[Y0:Y1, X0:X1] @ REC709
        if m.shape != img.shape:
            raise SystemExit("mask %s is %s, crop is %s" % (g.mask, m.shape, img.shape))
        v = [ (img - ndi.gaussian_filter(img, s))[m].std() for s in (1.0, 2.5, 6.0) ]
        lm = ndi.uniform_filter(img, 9)
        rms = ((img - lm)[m] / np.maximum(lm[m], 1)).std() * 100
        if ref is None:
            ref = v[0]
        print("  %-20s %8.3f %8.3f %8.3f %9.3f %+9.1f%%"
              % (lab, v[0], v[1], v[2], rms, 100 * (v[0] / ref - 1)))


if __name__ == "__main__":
    main()
