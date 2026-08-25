#!/usr/bin/env python3
"""Summarize CPU->image uploads from an NGFXPROBE_SURVEY=1 probe log.

Run the probe layer with NGFXPROBE_SURVEY=1 under ngfx-replay (see dev/README.md),
then point this at the resulting JSONL. Groups uploads by destination image and
reports the ones shaped like lookup tables -- small, float or 8-bit, uploaded
once from the CPU -- which are the candidates for a fingerprint rewrite through
the CopyTextureRegion hook in main.cpp.

Pass two logs to diff them: an upload whose content hash matches across two
independent captures is deterministic, and therefore safe to fingerprint.
"""
import json
import sys
from collections import defaultdict

# VkFormat values seen in practice; anything else prints as its raw number.
# Values are the Vulkan core enum -- note R16_UNORM starts at 70, not 72, which
# is the boundary the probe's byte-per-pixel table originally got wrong.
FORMATS = {
    9: "R8_UNORM", 13: "R8_UINT", 15: "R8_SRGB",
    16: "R8G8_UNORM", 20: "R8G8_UINT",
    23: "R8G8B8_UNORM", 30: "B8G8R8_UNORM",
    37: "R8G8B8A8_UNORM", 38: "R8G8B8A8_SNORM", 41: "R8G8B8A8_UINT",
    43: "R8G8B8A8_SRGB",
    44: "B8G8R8A8_UNORM", 50: "B8G8R8A8_SRGB",
    58: "A2R10G10B10_UNORM_PACK32", 64: "A2B10G10R10_UNORM_PACK32",
    68: "A2B10G10R10_UINT_PACK32",
    70: "R16_UNORM", 71: "R16_SNORM", 74: "R16_UINT", 76: "R16_SFLOAT",
    77: "R16G16_UNORM", 81: "R16G16_UINT", 83: "R16G16_SFLOAT",
    90: "R16G16B16_SFLOAT",
    91: "R16G16B16A16_UNORM", 95: "R16G16B16A16_UINT",
    97: "R16G16B16A16_SFLOAT",
    98: "R32_UINT", 99: "R32_SINT", 100: "R32_SFLOAT",
    101: "R32G32_UINT", 103: "R32G32_SFLOAT",
    104: "R32G32B32_UINT", 106: "R32G32B32_SFLOAT",
    107: "R32G32B32A32_UINT", 109: "R32G32B32A32_SFLOAT",
    122: "B10G11R11_UFLOAT_PACK32", 123: "E5B9G9R9_UFLOAT_PACK32",
    124: "D16_UNORM", 126: "D32_SFLOAT",
}


def fmt_name(f):
    return FORMATS.get(f, f"fmt{f}")


def load(path):
    """Return ({dst_image: [upload, ...]}, {image: create_info}).

    CreateImage carries mip count and usage flags, which separate streamed art
    assets (mipmapped, many uploads) from lookup tables (single mip, one
    upload) far more reliably than dimensions alone.
    """
    by_img = defaultdict(list)
    created = {}
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if '"ev":"CopyImgDump"' in line:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                by_img[e["dst"]].append(e)
            elif '"ev":"CreateImage"' in line:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                created[e["img"]] = e
    return by_img, created


# VK_IMAGE_USAGE_STORAGE_BIT -- a GPU-written image is not a CPU-authored LUT.
USAGE_STORAGE = 0x08


def is_lut_shaped(w, h, n_uploads, ci):
    """LUT heuristic: a single CPU upload into a single-mip, non-storage image.

    Mipmapped images are streamed art; storage images are GPU-written. What
    survives is the shape the SSS diffusion kernel had -- created once, filled
    once from the CPU, then only ever sampled.
    """
    if n_uploads != 1:
        return False
    if w * h > 262144:  # 512x512; grading/noise LUTs live well under this
        return False
    if ci is not None:
        if ci.get("mips", 1) > 1:
            return False
        if ci.get("layers", 1) > 1:
            return False
        if ci.get("usage", 0) & USAGE_STORAGE:
            return False
    return True


def summarize(by_img, created, label, min_px=0):
    rows = []
    for dst, evs in by_img.items():
        e0 = evs[0]
        w, h, fmt = e0["w"], e0["h"], e0["fmt"]
        ci = created.get(dst)
        total = sum(x.get("bytes", 0) for x in evs)
        hashes = {x.get("fnv", "") for x in evs}
        rows.append({
            "dst": dst, "w": w, "h": h, "fmt": fmt, "n": len(evs),
            "bytes": total, "fnv": e0.get("fnv", ""),
            "stable": len(hashes) == 1,
            "lut": is_lut_shaped(w, h, len(evs), ci),
            "mips": ci.get("mips", "?") if ci else "?",
            "usage": ci.get("usage", 0) if ci else 0,
            "hex": e0.get("hex", ""),
            "trunc": e0.get("trunc", 0),
        })
    rows.sort(key=lambda r: (not r["lut"], -(r["w"] * r["h"])))

    print(f"=== {label}: {len(rows)} distinct destination images, "
          f"{sum(r['n'] for r in rows)} uploads ===\n")

    luts = [r for r in rows if r["lut"] and r["w"] * r["h"] >= min_px]
    print(f"--- LUT-shaped candidates ({len(luts)} at >={min_px}px) ---")
    print(f"{'image':<12} {'dims':>12}  {'format':<26} {'bytes':>9} "
          f"{'mips':>4}  {'fnv1a64':<16}")
    for r in luts:
        print(f"{r['dst']:<12} {r['w']:>5}x{r['h']:<6}  {fmt_name(r['fmt']):<26} "
              f"{r['bytes']:>9} {str(r['mips']):>4}  {r['fnv']:<16}")

    rest = [r for r in rows if not r["lut"]]
    print(f"\n--- other uploads ({len(rest)}), by size ---")
    agg = defaultdict(lambda: [0, 0])
    for r in rest:
        k = (r["w"], r["h"], r["fmt"])
        agg[k][0] += 1
        agg[k][1] += r["bytes"]
    for (w, h, fmt), (n, b) in sorted(agg.items(), key=lambda kv: -kv[1][1])[:25]:
        print(f"{w:>5}x{h:<6} {fmt_name(fmt):<26} n={n:<5} {b:>12} B")
    return {r["dst"]: r for r in rows}


def diff(a, b):
    """Report which uploads are byte-identical across two captures."""
    print("\n=== determinism across captures ===")
    ha = defaultdict(list)
    for r in a.values():
        ha[(r["w"], r["h"], r["fmt"])].append(r)
    hb = defaultdict(list)
    for r in b.values():
        hb[(r["w"], r["h"], r["fmt"])].append(r)

    shared = sorted(set(ha) & set(hb))
    print(f"{'dims':>12} {'format':<26} {'A':>4} {'B':>4}  verdict")
    for k in shared:
        ra, rb = ha[k], hb[k]
        fa = {r["fnv"] for r in ra if r["fnv"]}
        fb = {r["fnv"] for r in rb if r["fnv"]}
        if fa and fa == fb:
            verdict = "DETERMINISTIC -- fingerprintable"
        elif fa & fb:
            verdict = f"partial ({len(fa & fb)}/{len(fa | fb)} hashes shared)"
        else:
            verdict = "varies between captures"
        w, h, fmt = k
        print(f"{w:>5}x{h:<6} {fmt_name(fmt):<26} {len(ra):>4} {len(rb):>4}  {verdict}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    # --min-px filters the candidate table; mip tails and 1x1 placeholders
    # otherwise bury the interesting rows.
    min_px = 0
    for a in sys.argv[1:]:
        if a.startswith("--min-px="):
            min_px = int(a.split("=", 1)[1])

    ua, ca = load(args[0])
    a = summarize(ua, ca, args[0].split("/")[-1], min_px)
    if len(args) > 1:
        ub, cb = load(args[1])
        b = summarize(ub, cb, args[1].split("/")[-1], min_px)
        diff(a, b)


if __name__ == "__main__":
    main()
