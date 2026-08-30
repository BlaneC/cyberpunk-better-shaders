#!/usr/bin/env python3
"""A/B two capture PNGs from handoff/45's protocol.

The per-pixel noise between two separate launches is large (sd ~6/255 over a
raw rectangle) because path-tracing sampling, the denoiser's temporal history
and wandering background NPCs all differ. Region means over a rectangle are
therefore dominated by things that are not the BRDF. This script:

  1. checks the two frames are actually aligned (photo mode should give 0,0);
  2. segments SKIN by connected-component growth from seed points, using the
     BASELINE image only so the mask cannot be biased by the effect measured;
  3. reports the delta on skin and on non-skin controls, which is the empirical
     null -- a skin delta inside the spread of the controls means nothing;
  4. bins skin by distance to the silhouette. Grazing-angle terms (the tier-1
     c1 Fresnel, dcouple, micro-shadowing) must be strongest at the EDGE. A
     flat or reversed gradient means the term is not reaching these pixels.

Usage:
  dev/ab_compare.py BASE.png TEST.png [--crop X0,Y0,X1,Y1] [--seeds y,x;y,x]
                    [--out DIR] [--label TEXT]
"""
import argparse, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

REC709 = [0.2126, 0.7152, 0.0722]


def load(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float64)


def align(la, lb, r=4):
    best = None
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            sa = la[10 + dy:(-10 + dy) or None, 10 + dx:(-10 + dx) or None]
            v = ((sa - lb[10:-10, 10:-10]) ** 2).mean()
            if best is None or v < best[0]:
                best = (v, dy, dx)
    return best


def skin_mask(a, seeds, gradpct=72, lo=0.62, hi=1.45, box=None):
    """Connected-component skin from the BASELINE frame only."""
    la = a @ REC709
    sm = ndi.gaussian_filter(la, 1.2)
    grad = np.hypot(ndi.sobel(sm, 1), ndi.sobel(sm, 0))
    sv = np.array([la[y, x] for y, x in seeds])
    cand = (la > sv.min() * lo) & (la < sv.max() * hi)
    cand &= grad < np.percentile(grad, gradpct)
    cand = ndi.binary_opening(cand, np.ones((3, 3)))
    lab, _ = ndi.label(cand)
    keep = {lab[y, x] for y, x in seeds} - {0}
    if not keep:
        sys.exit("no skin component under the seeds -- pass --seeds for this scene")
    m = np.isin(lab, list(keep))
    m = ndi.binary_fill_holes(ndi.binary_closing(m, np.ones((5, 5))))
    m = ndi.binary_erosion(m, np.ones((5, 5)))        # off the hair/silhouette edge
    if box is not None:                               # dim scenes need a spatial bound
        bx = np.zeros_like(m)
        bx[box[1]:box[3], box[0]:box[2]] = True
        m &= bx
    return m


def row(name, d, dl, m):
    n = int(m.sum())
    if n < 500:
        return
    print("  %-22s n=%7d  dR%+7.3f dG%+7.3f dB%+7.3f  dLum%+7.3f  sd%6.2f"
          % (name, n, *d[m].mean(axis=0), dl[m].mean(), dl[m].std()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("test")
    ap.add_argument("--crop", default="1000,380,1400,880")
    ap.add_argument("--seeds", default="70,175;265,88;262,240;300,168")
    ap.add_argument("--out"); ap.add_argument("--label", default="")
    ap.add_argument("--gradpct", type=float, default=72)
    ap.add_argument("--lo", type=float, default=0.62)
    ap.add_argument("--hi", type=float, default=1.45)
    ap.add_argument("--mask", help="load a saved per-scene mask (.npy) instead of deriving one")
    ap.add_argument("--savemask", help="write the derived mask to this .npy")
    ap.add_argument("--box", help="x0,y0,x1,y1 in CROP coords to bound the mask")
    ap.add_argument("--tone", action="store_true",
                    help="bin the delta by BASELINE tone. A BRDF change redistributes "
                         "energy; the mean hides it. Always look at this before "
                         "calling a rung null.")
    g = ap.parse_args()
    X0, Y0, X1, Y1 = map(int, g.crop.split(","))
    seeds = [tuple(map(int, s.split(","))) for s in g.seeds.split(";")]

    A, B = load(g.base), load(g.test)
    if A.shape != B.shape:
        sys.exit("frames differ in size: %s vs %s" % (A.shape, B.shape))
    a, b = A[Y0:Y1, X0:X1], B[Y0:Y1, X0:X1]

    v, dy, dx = align(a @ REC709, b @ REC709)
    print("\n%s\n%s" % (g.label or "%s -> %s" % (g.base, g.test), "=" * 72))
    print("  alignment best shift dy=%d dx=%d (SSD %.2f)%s"
          % (dy, dx, v, "" if abs(dy) <= 1 and abs(dx) <= 1
             else "   <-- NOT ALIGNED, camera moved"))

    if g.mask:
        m = np.load(g.mask)
        if m.shape != a.shape[:2]:
            sys.exit("mask %s is %s, crop is %s" % (g.mask, m.shape, a.shape[:2]))
        print("  skin mask %d px (%.1f%% of crop)  [loaded %s]\n"
              % (m.sum(), 100 * m.mean(), g.mask))
    else:
        box = tuple(map(int, g.box.split(","))) if g.box else None
        m = skin_mask(a, seeds, g.gradpct, g.lo, g.hi, box)
        print("  skin mask %d px (%.1f%% of crop)\n" % (m.sum(), 100 * m.mean()))
    if g.savemask:
        np.save(g.savemask, m)
        print("  saved mask -> %s\n" % g.savemask)
    d, dl = b - a, (b - a) @ REC709
    row("SKIN (segmented)", d, dl, m)

    print("\n  controls (the empirical null -- skin must beat these):")
    dF, dlF = B - A, (B - A) @ REC709
    h, w = A.shape[:2]
    for nm, (x0, x1, y0, y1) in {
        "ceiling":  (int(.27*w), int(.74*w), int(.03*h), int(.18*h)),
        "floor R":  (int(.64*w), int(.92*w), int(.87*h), int(.99*h)),
        "wall L":   (int(.05*w), int(.18*w), int(.61*h), int(.84*h)),
    }.items():
        mm = np.zeros(A.shape[:2], bool); mm[y0:y1, x0:x1] = True
        row("CTRL " + nm, dF, dlF, mm)

    print("\n  grazing test -- a Fresnel/occlusion term peaks at the EDGE:")
    dist = ndi.distance_transform_edt(m)
    print("  %-14s %8s %9s %8s" % ("dist-to-edge", "n", "dLum", "sd"))
    for lo, hi in [(0, 4), (4, 8), (8, 14), (14, 22), (22, 35), (35, 10**6)]:
        mm = m & (dist >= lo) & (dist < hi)
        if mm.sum() < 300:
            continue
        print("  %-14s %8d %+9.3f %8.2f"
              % ("%d-%d px" % (lo, hi), mm.sum(), dl[mm].mean(), dl[mm].std()))

    if g.tone:
        la, lb = a @ REC709, b @ REC709
        base = la[m].mean()
        print("\n  binned by BASELINE tone (skin mean %.1f):" % base)
        print("  %-20s %8s %10s %10s" % ("baseline lum", "n", "dLum", "rel %"))
        qs = np.percentile(la[m], [0, 10, 25, 50, 75, 90, 97, 100])
        for lo, hi in zip(qs[:-1], qs[1:]):
            sel = m & (la >= lo) & (la < hi)
            if sel.sum() < 400:
                continue
            bb = la[sel].mean(); dd = (lb[sel] - la[sel]).mean()
            print("  %7.1f-%-12.1f %8d %+10.3f %+9.2f%%"
                  % (lo, hi, sel.sum(), dd, 100 * dd / bb))

    if g.out:
        import os
        os.makedirs(g.out, exist_ok=True)
        Image.fromarray((np.clip(a / 255 * 3, 0, 1) ** (1 / 2.2) * 255
                         * (0.3 + 0.7 * m[..., None])).astype(np.uint8)
                        ).save(os.path.join(g.out, "mask.png"))
        amp = 12.0
        hm = np.zeros((*dl.shape, 3))
        hm[..., 0] = np.clip(dl * amp, 0, 255)
        hm[..., 2] = np.clip(-dl * amp, 0, 255)
        hm[..., 1] = np.clip(np.abs(dl) * amp * .3, 0, 255)
        Image.fromarray(hm.astype(np.uint8)).save(os.path.join(g.out, "diff_heat.png"))
        print("\n  wrote mask.png + diff_heat.png (red = test brighter) to %s" % g.out)


if __name__ == "__main__":
    main()
