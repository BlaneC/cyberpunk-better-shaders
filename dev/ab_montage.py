#!/usr/bin/env python3
"""Cut labelled 1:1 side-by-side crops from A/B rung dirs, control first.

    dev/ab_montage.py <out-dir> <scene> <crop> <label>=<rung-dir> ...

<crop> is a named box from CROPS, or x0,y0,x1,y1. Crops are 1:1 (no resample)
unless the box is smaller than MIN_W, in which case it is point-upscaled so
pores/catchlights survive being looked at. The eye is the instrument
(handoff/47 section 11) -- this tool only makes the halves comparable.
"""
import sys, os
from PIL import Image, ImageDraw

# Boxes for the 2026-08-30 ladder framing (2560x1440, same save/camera).
CROPS = {
    "S1.face": (980, 420, 1380, 820),
    "S1.eyes": (1050, 520, 1330, 650),
    "S2.face": (980, 380, 1400, 800),
    "S3.face": (1020, 400, 1440, 820),
}
MIN_W = 560


def main():
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    out_dir, scene, crop = sys.argv[1], sys.argv[2], sys.argv[3]
    box = CROPS[crop] if crop in CROPS else tuple(int(v) for v in crop.split(","))
    panels = []
    for arg in sys.argv[4:]:
        label, d = arg.split("=", 1)
        im = Image.open(os.path.join(d, f"{scene}.png")).convert("RGB").crop(box)
        panels.append((label, im))

    w, h = panels[0][1].size
    scale = max(1, -(-MIN_W // w))
    if scale > 1:
        w, h = w * scale, h * scale
        panels = [(l, im.resize((w, h), Image.NEAREST)) for l, im in panels]

    pad, lab = 10, 28
    canvas = Image.new("RGB", (w * len(panels) + pad * (len(panels) - 1), h + lab),
                       (18, 18, 18))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        canvas.paste(im, (i * (w + pad), lab))
        d.text((i * (w + pad) + 6, 8), label, fill=(240, 240, 240))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{scene}_{crop.replace(',', '-')}.png")
    canvas.save(out)
    print(out)


if __name__ == "__main__":
    main()
