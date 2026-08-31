#!/usr/bin/env python3
# Regenerate every number quoted in handoff/50-GI-SPLICE.md (probe readout
# in section 2, gi-50 A/B in section 6). Run from anywhere; paths resolve
# relative to this file. Serve verification for the two launches is
# separate:  ./dev/ab_launch_audit.py N  over the layer journal.
#
# Method (50 section 2): linearize sRGB, per-pixel stats over hand-placed
# boxes, medians; always face minus an in-frame control, then treatment
# minus baseline -- never absolutes. Boxes are (x0,x1,y0,y1) in original
# 2560x1440 coords; probe/null and gi50/r2 boxes differ where the pose
# shifted between shots.
import os
import numpy as np
from PIL import Image

AB = os.path.dirname(os.path.abspath(__file__))


def lin(u):  # sRGB -> linear
    u = u / 255.0
    return np.where(u <= 0.04045, u / 12.92, ((u + 0.055) / 1.055) ** 2.4)


def crop_lin(img, box):
    x0, x1, y0, y1 = box
    return lin(np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.float64)[..., :3])


def med_lgr(img, box):
    a = crop_lin(img, box)
    R, G = a[..., 0].ravel(), a[..., 1].ravel()
    return np.median(np.log((G + 1e-6) / (R + 1e-6)))


def med_lnlum(img, box):
    a = crop_lin(img, box)
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    return np.median(np.log(lum.ravel() + 1e-6))


# ---------------- 1. probe-gi hue readout (50 section 2) ----------------
# probe = probe-gi captures (19:42-19:46, RR OFF -- bounded harmless),
# null = R3-off (18:18). Keep-mask drops crushed/clipped pixels.
PROBE_REG = {
 ("S2", "probe"): dict(face=(1037, 1318, 461, 806), hair=(1011, 1331, 243, 371),
                       jacket=(832, 1126, 1101, 1370), floor=(1600, 1984, 1178, 1382)),
 ("S2", "null"):  dict(face=(998, 1280, 461, 806), hair=(973, 1293, 243, 371),
                       jacket=(794, 1088, 1101, 1370), floor=(1600, 1984, 1178, 1382)),
 ("S3", "probe"): dict(face=(1126, 1421, 435, 845), hair=(1075, 1434, 115, 320),
                       jacket=(819, 1037, 1050, 1395), ground=(320, 768, 768, 1088)),
 ("S3", "null"):  dict(face=(1101, 1395, 435, 845), hair=(1050, 1408, 115, 320),
                       jacket=(794, 1011, 1050, 1395), ground=(320, 768, 768, 1088)),
 ("S1", "probe"): dict(face=(1050, 1331, 448, 819), hair=(1011, 1370, 166, 358),
                       jacket=(806, 1062, 1024, 1382), sand=(1600, 2240, 1088, 1344)),
 ("S1", "null"):  dict(face=(1050, 1331, 448, 819), hair=(1011, 1370, 166, 358),
                       jacket=(806, 1062, 1024, 1382), sand=(1600, 2240, 1088, 1344)),
}


def probe_stats(img, box):
    x0, x1, y0, y1 = box
    raw = np.asarray(img.crop((x0, y0, x1, y1)))[..., :3]
    a = lin(raw.astype(np.float64))
    keep = (raw.max(axis=2) >= 8) & (raw.max(axis=2) <= 250)
    a = a[keep]
    R, G, B = a[:, 0], a[:, 1], a[:, 2]
    s = R + G + B + 1e-9
    return (np.median(G / s), np.median(R / s), np.median(B / s),
            np.median(np.log((G + 1e-6) / (R + 1e-6))), keep.mean(), keep.sum())


def section_probe():
    print("############ 50 section 2: probe-gi hue readout ############")
    path = {"probe": AB + "/probe-gi/%s.png", "null": AB + "/R3-off/%s.png"}
    for scene in ("S2", "S3", "S1"):
        print("== %s ==" % scene)
        rows = {}
        for kind in ("probe", "null"):
            img = Image.open(path[kind] % scene)
            for name, box in PROBE_REG[(scene, kind)].items():
                g, r, b, lgr, kf, n = probe_stats(img, box)
                rows[(kind, name)] = lgr
                print("  %-5s %-7s gfrac=%.3f rfrac=%.3f bfrac=%.3f ln(G/R)=%+.3f  (n=%d keep=%.0f%%)"
                      % (kind, name, g, r, b, lgr, n, 100 * kf))
        for ctrl in [k for k in ("hair", "jacket", "floor", "ground", "sand")
                     if ("probe", k) in rows]:
            dp = rows[("probe", "face")] - rows[("probe", ctrl)]
            dn = rows[("null", "face")] - rows[("null", ctrl)]
            print("  D ln(G/R) face-minus-%-6s probe=%+.3f null=%+.3f  probe-null=%+.3f"
                  % (ctrl, dp, dn, dp - dn))
        print()

    print("== S2 face sub-regions (bounce-dominance gradient) ==")
    probe = Image.open(path["probe"] % "S2")
    null = Image.open(path["null"] % "S2")
    pb, nb = (1037, 1318, 461, 806), (998, 1280, 461, 806)
    for i, nm in enumerate(["forehead", "eyes", "cheeks/nose", "mouth/chin"]):
        py0 = pb[2] + (pb[3] - pb[2]) * i // 4
        py1 = pb[2] + (pb[3] - pb[2]) * (i + 1) // 4
        ny0 = nb[2] + (nb[3] - nb[2]) * i // 4
        ny1 = nb[2] + (nb[3] - nb[2]) * (i + 1) // 4
        p = med_lgr(probe, (pb[0], pb[1], py0, py1))
        n = med_lgr(null, (nb[0], nb[1], ny0, ny1))
        print("  %-12s probe=%+.3f null=%+.3f d=%+.3f" % (nm, p, n, p - n))
    pmx, nmx = (pb[0] + pb[1]) // 2, (nb[0] + nb[1]) // 2
    for nm, pxs, nxs in (("left-half", (pb[0], pmx), (nb[0], nmx)),
                         ("right-half", (pmx, pb[1]), (nmx, nb[1]))):
        p = med_lgr(probe, (pxs[0], pxs[1], pb[2], pb[3]))
        n = med_lgr(null, (nxs[0], nxs[1], nb[2], nb[3]))
        print("  %-12s probe=%+.3f null=%+.3f d=%+.3f" % (nm, p, n, p - n))
    p = med_lgr(probe, (1088, 1300, 900, 1050))   # chest: independent skin
    n = med_lgr(null, (1050, 1262, 900, 1050))    # patch below the necklace
    print("  %-12s probe=%+.3f null=%+.3f d=%+.3f" % ("chest", p, n, p - n))
    print()


# ---------------- 2. gi-50 vs R2-real-gloss (50 section 6) ----------------
# gi50 = gi-50 captures (20:22-20:26, RR ON held), r2 = R2-real-gloss
# (18:06, RR ON). Only S3 is a matched pair: its controls agree to
# <=0.008 ln. S2 (crowd drift) and S1 (sun drift) are disqualified --
# their rows are printed so the disqualification itself reproduces.
AB_REG = {
 ("S2", "gi50"): dict(face=(1011, 1306, 461, 832), hair=(986, 1331, 243, 384),
                      jacket=(819, 1152, 1101, 1382), floor=(1600, 1984, 1178, 1382)),
 ("S2", "r2"):   dict(face=(998, 1306, 422, 819), hair=(973, 1331, 218, 371),
                      jacket=(806, 1139, 1101, 1382), floor=(1600, 1984, 1178, 1382)),
 ("S3", "gi50"): dict(face=(1024, 1446, 358, 896), hair=(973, 1485, 77, 333),
                      jacket=(794, 1024, 998, 1395), ground=(192, 768, 704, 1152)),
 ("S3", "r2"):   dict(face=(1024, 1446, 358, 896), hair=(973, 1485, 77, 333),
                      jacket=(794, 1024, 998, 1395), ground=(192, 768, 704, 1152)),
 ("S1", "gi50"): dict(face=(1050, 1331, 448, 819), hair=(1011, 1370, 166, 358),
                      jacket=(806, 1062, 1024, 1382), sand=(1600, 2240, 1088, 1344)),
 ("S1", "r2"):   dict(face=(1050, 1331, 448, 819), hair=(1011, 1370, 166, 358),
                      jacket=(806, 1062, 1024, 1382), sand=(1600, 2240, 1088, 1344)),
}


def section_ab():
    print("############ 50 section 6: gi-50 vs R2-real-gloss ############")
    path = {"gi50": AB + "/gi-50/%s.png", "r2": AB + "/R2-real-gloss/%s.png"}
    for scene in ("S3", "S2", "S1"):
        print("== %s ==" % scene)
        rows = {}
        for kind in ("gi50", "r2"):
            img = Image.open(path[kind] % scene)
            for name, box in AB_REG[(scene, kind)].items():
                rows[(kind, name)] = (med_lnlum(img, box), med_lgr(img, box))
                print("  %-5s %-7s ln(lum)=%+.3f ln(G/R)=%+.3f"
                      % (kind, name, *rows[(kind, name)]))
        for ctrl in [k for k in ("hair", "jacket", "floor", "ground", "sand")
                     if ("gi50", k) in rows]:
            for mi, nm in ((0, "ln(lum)"), (1, "ln(G/R)")):
                dg = rows[("gi50", "face")][mi] - rows[("gi50", ctrl)][mi]
                dr = rows[("r2", "face")][mi] - rows[("r2", ctrl)][mi]
                print("  D %-7s face-minus-%-6s gi50=%+.3f r2=%+.3f  gi50-r2=%+.3f"
                      % (nm, ctrl, dg, dr, dg - dr))
        print()

    print("== S3 face 3x3 grid, ln(lum), (cell minus hair anchor), gi50-r2 ==")
    g = Image.open(path["gi50"] % "S3")
    r = Image.open(path["r2"] % "S3")
    hair = AB_REG[("S3", "gi50")]["hair"]
    ag, ar = med_lnlum(g, hair), med_lnlum(r, hair)
    print("  anchor(hair) gi50-r2 = %+.3f" % (ag - ar))
    fx0, fx1, fy0, fy1 = AB_REG[("S3", "gi50")]["face"]
    xs = np.linspace(fx0, fx1, 4).astype(int)
    ys = np.linspace(fy0, fy1, 4).astype(int)
    for j in range(3):
        row = []
        for i in range(3):
            dg = med_lnlum(g, (xs[i], xs[i + 1], ys[j], ys[j + 1])) - ag
            dr = med_lnlum(r, (xs[i], xs[i + 1], ys[j], ys[j + 1])) - ar
            row.append(dg - dr)
        print("  " + "  ".join("%+.3f" % v for v in row))


if __name__ == "__main__":
    section_probe()
    section_ab()
