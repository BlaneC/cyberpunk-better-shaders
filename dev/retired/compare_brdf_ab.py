#!/usr/bin/env python3
"""
compare_brdf_ab.py -- frozen-camera A/B analysis for the Callisto skin BRDF.

Takes two screenshots of the SAME scene/pose/lighting (one with the shader
swaps active, one without) and quantifies what actually changed on skin.

The question this answers is not just "did it get redder" but "does the
change look like a BRDF or like a flat tint":

  * a flat tint (the old smoke test) multiplies every skin pixel by the same
    per-channel factor, so the gain is constant across brightness levels;
  * tier-1 c1 is angle-dependent -- retroreflection lifts front-lit (bright)
    skin and diffuse Fresnel lifts grazing/terminator (dim, high-gradient)
    skin -- so the gain must VARY with luminance and be near 1.0 nowhere in
    particular. A dead-flat gain curve means something is wrong.

It also uses non-skin pixels as a control: the skin gate should leave hair,
clothing and background alone, and any shift seen there is either scene
noise (the background is not perfectly static) or a gating bug.

Usage:
    python3 compare_brdf_ab.py NO_BSDF.png YES_BSDF_FIXED.png
    python3 compare_brdf_ab.py before.png after.png --outdir /tmp/ab \\
        --center-crop 0.55 --save-masks

Outputs a printed report, optional JSON (--json), and diagnostic PNGs
(mask overlay + amplified difference heatmap) so the skin mask can be
eyeballed rather than trusted blindly.
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


# ---------------------------------------------------------------- loading

def load_rgb(path):
    """Load a PNG as float32 RGB in [0,1], handling 8- and 16-bit files."""
    img = Image.open(path)
    if img.mode not in ("RGB", "RGBA", "I;16", "I"):
        img = img.convert("RGB")
    arr = np.asarray(img)
    if arr.ndim == 2:                      # grayscale
        arr = np.dstack([arr] * 3)
    if arr.shape[2] == 4:                  # drop alpha
        arr = arr[:, :, :3]
    maxval = 65535.0 if arr.dtype == np.uint16 else 255.0
    return arr.astype(np.float32) / maxval


def luminance(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# ---------------------------------------------------------------- masking

def skin_mask(rgb, center_crop):
    """
    Heuristic skin mask: warm hue (R > G > B with a real R-G gap), moderate
    saturation, not blown out or crushed. Restricted to a centered crop so
    the background (billboards, neon) cannot contribute.

    Deliberately conservative -- better to measure 200k confidently-skin
    pixels than 800k pixels half of which are jacket.
    """
    h, w, _ = rgb.shape
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    m = (
        (r > g) & (g > b)                  # warm ordering
        & ((r - g) > 0.045)                # real red gap, not gray
        & ((g - b) > 0.008)                # skin is not magenta
        & (sat > 0.10) & (sat < 0.70)      # not gray, not neon
        & (mx > 0.10) & (mx < 0.97)        # not crushed, not clipped
    )

    crop = np.zeros((h, w), dtype=bool)
    ch, cw = int(h * center_crop), int(w * center_crop)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    crop[y0:y0 + ch, x0:x0 + cw] = True
    return m & crop


def gradient_magnitude(lum):
    """Cheap Sobel-ish gradient; high values mark terminators and edges."""
    gy = np.zeros_like(lum)
    gx = np.zeros_like(lum)
    gy[1:-1, :] = lum[2:, :] - lum[:-2, :]
    gx[:, 1:-1] = lum[:, 2:] - lum[:, :-2]
    return np.sqrt(gx * gx + gy * gy)


# ---------------------------------------------------------------- analysis

def ratio_stats(before, after, mask, label):
    """Per-channel mean/gain plus warmth metrics over a mask."""
    if mask.sum() == 0:
        return None
    b = before[mask]
    a = after[mask]
    mb, ma = b.mean(axis=0), a.mean(axis=0)
    warm_b = mb[0] / max(mb[1] + mb[2], 1e-6)
    warm_a = ma[0] / max(ma[1] + ma[2], 1e-6)
    return {
        "label": label,
        "pixels": int(mask.sum()),
        "mean_before": [round(float(x), 5) for x in mb],
        "mean_after": [round(float(x), 5) for x in ma],
        "gain_rgb": [round(float(ma[i] / max(mb[i], 1e-6)), 4) for i in range(3)],
        "warmth_before": round(float(warm_b), 4),
        "warmth_after": round(float(warm_a), 4),
        "warmth_delta_pct": round(float((warm_a / max(warm_b, 1e-6) - 1) * 100), 2),
        "lum_before": round(float(luminance(b).mean()), 5),
        "lum_after": round(float(luminance(a).mean()), 5),
        "lum_gain": round(float(luminance(a).mean() / max(luminance(b).mean(), 1e-6)), 4),
    }


def bucket_by(values, before, after, mask, edges, name):
    """Gain per bucket of some driver quantity (luminance, gradient, ...)."""
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = mask & (values >= lo) & (values < hi)
        n = int(sel.sum())
        if n < 500:
            rows.append({name: f"{lo:.2f}-{hi:.2f}", "pixels": n, "gain": None})
            continue
        lb = luminance(before[sel]).mean()
        la = luminance(after[sel]).mean()
        mb, ma = before[sel].mean(axis=0), after[sel].mean(axis=0)
        rows.append({
            name: f"{lo:.2f}-{hi:.2f}",
            "pixels": n,
            "gain": round(float(la / max(lb, 1e-6)), 4),
            "gain_r": round(float(ma[0] / max(mb[0], 1e-6)), 4),
            "gain_b": round(float(ma[2] / max(mb[2], 1e-6)), 4),
        })
    return rows


def flatness(rows):
    """Spread of the per-bucket gain curve: ~0 means a uniform tint."""
    gains = [r["gain"] for r in rows if r["gain"] is not None]
    if len(gains) < 3:
        return None, gains
    return float(max(gains) - min(gains)), gains


# ---------------------------------------------------------------- outputs

def save_overlay(path, rgb, mask):
    """Green-tint the masked pixels so the mask can be verified by eye."""
    out = (rgb.copy() * 255).astype(np.uint8)
    out[mask] = (out[mask] * 0.35 + np.array([0, 200, 90]) * 0.65).astype(np.uint8)
    Image.fromarray(out).save(path)


def save_heatmap(path, before, after, amplify):
    """Signed luminance difference: red = brighter after, blue = dimmer."""
    d = (luminance(after) - luminance(before)) * amplify
    h, w = d.shape
    out = np.zeros((h, w, 3), dtype=np.float32)
    out[..., 0] = np.clip(d, 0, 1)
    out[..., 2] = np.clip(-d, 0, 1)
    out[..., 1] = np.clip(np.abs(d) * 0.25, 0, 1)
    Image.fromarray((out * 255).astype(np.uint8)).save(path)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before", help="screenshot WITHOUT the BRDF swaps")
    ap.add_argument("after", help="screenshot WITH the BRDF swaps")
    ap.add_argument("--center-crop", type=float, default=0.55,
                    help="fraction of frame (centered) that holds the character")
    ap.add_argument("--outdir", default=None, help="write diagnostic PNGs here")
    ap.add_argument("--save-masks", action="store_true",
                    help="write mask overlay + difference heatmap")
    ap.add_argument("--amplify", type=float, default=8.0,
                    help="difference heatmap amplification")
    ap.add_argument("--json", default=None, help="write the full report as JSON")
    args = ap.parse_args()

    before = load_rgb(args.before)
    after = load_rgb(args.after)

    if before.shape != after.shape:
        print(f"! size mismatch {before.shape} vs {after.shape}; cropping to overlap")
        h = min(before.shape[0], after.shape[0])
        w = min(before.shape[1], after.shape[1])
        before, after = before[:h, :w], after[:h, :w]

    lum_b = luminance(before)
    grad_b = gradient_magnitude(lum_b)

    skin = skin_mask(before, args.center_crop) & skin_mask(after, args.center_crop)
    nonskin = (~skin) & (lum_b > 0.03)

    # Pixels that barely moved are the best "static scene" reference; if the
    # whole frame shifted (exposure, HDR, time of day) skin numbers mean less.
    delta = np.abs(after - before).max(axis=2)
    static = nonskin & (delta < 0.02)

    report = {
        "before": os.path.abspath(args.before),
        "after": os.path.abspath(args.after),
        "resolution": [int(before.shape[1]), int(before.shape[0])],
        "frame_changed_pct": round(float((delta > 0.02).mean() * 100), 2),
        "regions": [],
    }

    for m, name in ((skin, "SKIN (gated, should change)"),
                    (nonskin, "NON-SKIN (control, should not)"),
                    (static, "STATIC non-skin (exposure reference)")):
        st = ratio_stats(before, after, m, name)
        if st:
            report["regions"].append(st)

    lum_edges = [0.0, 0.05, 0.10, 0.18, 0.30, 0.45, 0.65, 1.01]
    grad_edges = [0.0, 0.02, 0.05, 0.10, 0.20, 1.01]
    report["skin_gain_by_luminance"] = bucket_by(lum_b, before, after, skin,
                                                 lum_edges, "luminance")
    report["skin_gain_by_gradient"] = bucket_by(grad_b, before, after, skin,
                                                grad_edges, "gradient")
    spread, gains = flatness(report["skin_gain_by_luminance"])
    report["gain_spread_across_luminance"] = None if spread is None else round(spread, 4)

    # The single most trustworthy statistic here. Binning by BEFORE luminance
    # and comparing AFTER values makes noise alone produce a sloping gain curve
    # (regression to the mean), and photo mode never reproduces a scene
    # perfectly. Computing the SAME curve on non-skin pixels captures that
    # artifact plus any exposure drift, so the skin-minus-control difference
    # isolates what the skin gate actually did.
    ctrl_curve = bucket_by(lum_b, before, after, nonskin, lum_edges, "luminance")
    diffs = []
    for s, c in zip(report["skin_gain_by_luminance"], ctrl_curve):
        d = None if (s["gain"] is None or c["gain"] is None) else round(s["gain"] - c["gain"], 4)
        diffs.append({"luminance": s["luminance"], "skin": s["gain"],
                      "control": c["gain"], "excess": d})
    report["skin_minus_control_by_luminance"] = diffs

    # ---- print ----
    print(f"\nresolution {report['resolution'][0]}x{report['resolution'][1]}   "
          f"frame pixels changed >2%: {report['frame_changed_pct']}%\n")

    print(f"{'region':<34}{'px':>9}{'lum gain':>10}{'R gain':>9}"
          f"{'B gain':>9}{'warmth':>9}{'warmth Δ%':>11}")
    for st in report["regions"]:
        print(f"{st['label']:<34}{st['pixels']:>9}{st['lum_gain']:>10.3f}"
              f"{st['gain_rgb'][0]:>9.3f}{st['gain_rgb'][2]:>9.3f}"
              f"{st['warmth_after']:>9.3f}{st['warmth_delta_pct']:>10.2f}%")

    print("\nskin gain vs luminance  (angle-dependence test)")
    print(f"{'lum bucket':<16}{'px':>9}{'lum gain':>10}{'R gain':>9}{'B gain':>9}")
    for r in report["skin_gain_by_luminance"]:
        if r["gain"] is None:
            print(f"{r['luminance']:<16}{r['pixels']:>9}{'--':>10}")
        else:
            print(f"{r['luminance']:<16}{r['pixels']:>9}{r['gain']:>10.3f}"
                  f"{r['gain_r']:>9.3f}{r['gain_b']:>9.3f}")

    print("\nskin gain vs gradient  (terminator / grazing test)")
    print(f"{'grad bucket':<16}{'px':>9}{'lum gain':>10}{'R gain':>9}{'B gain':>9}")
    for r in report["skin_gain_by_gradient"]:
        if r["gain"] is None:
            print(f"{r['gradient']:<16}{r['pixels']:>9}{'--':>10}")
        else:
            print(f"{r['gradient']:<16}{r['pixels']:>9}{r['gain']:>10.3f}"
                  f"{r['gain_r']:>9.3f}{r['gain_b']:>9.3f}")

    print("\nskin vs non-skin control  (isolates the gate; noise cancels)")
    print(f"{'lum bucket':<16}{'skin':>9}{'control':>10}{'excess':>10}")
    for d in diffs:
        if d["excess"] is None:
            print(f"{d['luminance']:<16}{'--':>9}")
        else:
            print(f"{d['luminance']:<16}{d['skin']:>9.3f}{d['control']:>10.3f}"
                  f"{d['excess']:>+10.3f}")

    # ---- interpretation ----
    print("\ninterpretation")
    skin_st = next((r for r in report["regions"] if r["label"].startswith("SKIN")), None)
    ctrl_st = next((r for r in report["regions"] if r["label"].startswith("STATIC")), None)
    if skin_st is None:
        print("  ! no skin pixels matched -- adjust --center-crop or the mask thresholds")
        sys.exit(1)

    drift = abs(ctrl_st["lum_gain"] - 1.0) if ctrl_st else 0.0
    effect = abs(skin_st["lum_gain"] - 1.0)
    print(f"  static-scene drift {drift*100:.1f}%  vs  skin effect {effect*100:.1f}%")
    if effect < 0.01:
        print("  -> skin is essentially UNCHANGED: the swap probably did not load")
    elif drift > effect * 0.5:
        print("  -> scene drift rivals the skin effect; treat numbers as inconclusive")
    else:
        print("  -> skin moved well beyond scene drift: the swap is active")

    excess = [d["excess"] for d in diffs if d["excess"] is not None]
    if excess:
        span = max(excess) - min(excess)
        peak = max(abs(e) for e in excess)
        # A real gated effect is CONSISTENTLY SIGNED -- the c1 factor only ever
        # adds energy on skin. An excess curve that flips sign across buckets is
        # residual motion (hair, foliage, micro-pose) leaking through the mask,
        # not shading: sub-pixel edge mismatch pushes some bins up and others
        # down. Sign consistency is therefore checked BEFORE the spread.
        signs = {e > 0 for e in excess if abs(e) > 0.01}
        print(f"  skin-minus-control excess ranges {min(excess):+.3f} to {max(excess):+.3f}")
        if peak < 0.02:
            print("  -> skin behaves exactly like the control: NO skin-specific change")
        elif len(signs) > 1:
            print("  -> excess FLIPS SIGN across buckets: residual scene/pose motion,")
            print("     not a shading change. Re-shoot with a steadier A/B pair.")
        elif span < 0.02:
            print("  -> constant excess at every brightness: a flat tint, not an angular BRDF")
        else:
            print("  -> excess is consistently signed, varies with brightness, and is")
            print("     absent from the control: a skin-gated angle-dependent effect")

    print(f"  skin warmth (R/(G+B)) {skin_st['warmth_before']:.3f} -> "
          f"{skin_st['warmth_after']:.3f}  ({skin_st['warmth_delta_pct']:+.1f}%)")
    if skin_st["warmth_delta_pct"] > 25:
        print("  -> very strong red shift: check you are not still on the smoke tint")

    # ---- files ----
    if args.outdir or args.save_masks:
        outdir = args.outdir or os.path.dirname(os.path.abspath(args.after))
        os.makedirs(outdir, exist_ok=True)
        save_overlay(os.path.join(outdir, "ab_skin_mask.png"), before, skin)
        save_heatmap(os.path.join(outdir, "ab_diff_heatmap.png"),
                     before, after, args.amplify)
        print(f"\nwrote ab_skin_mask.png and ab_diff_heatmap.png to {outdir}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
