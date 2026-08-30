#!/usr/bin/env python3
"""
author_callisto_kernel.py -- author a Callisto-inspired replacement for the
CP2077 SSS_Blur kernel LUT (Image_94111, 32x8 R32G32B32A32_SFLOAT).

Input : analysis/evidence/sss_kernel_texture.bin (4096 B, dumped by probe layer)
Output: analysis/evidence/sss_kernel_callisto.bin (+ .json + printed diff)

Design notes
------------
The engine shader computes out = sum(w*c)/sum(w) per channel, so only weight
RATIOS matter. We therefore keep the engine's tap OFFSETS (.a) untouched and
reshape only the weights (.rgb), preserving per-channel total weight (energy)
so overall brightness is unchanged.

Callisto mapping (analysis/callisto_brdf_over_lambert.md): the Callisto BRDF is
a surface BRDF (c1 diffuse-fresnel/retroreflection, c2 smooth terminator,
Proxima diffuse). It has no explicit subsurface profile, so we translate its
three visual traits into spatial-kernel reshapes (documented approximations):

  c1 Diffuse Fresnel (grazing boost)  -> widen the far tail per channel
       (knob: tail_widen[r,g,b])
  c1 Retroreflection (front-lit glow) -> lift mid-radius weights
       (knob: mid_lift, applied over 15%-60% of each kernel's offset range)
  c2 Smooth Terminator                -> soften the center gradient by blending
       the center weight toward the average of the first off-center taps
       (knob: center_soften)

Rows 0..2 keep their relative differences; rows 3..7 stay zero; the engine's
sub-kernel packing (x=0:15 taps, x=15:9 taps, x=24:6 taps) is preserved.
"""

import json, os, struct, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_HERE, 'sss_kernel_texture.bin')
DST_BIN = os.path.join(_HERE, 'sss_kernel_callisto.bin')
DST_JSON = os.path.join(_HERE, 'sss_kernel_callisto.json')

W, H = 32, 8
SUBKERNELS = [(0, 15), (15, 9), (24, 6)]   # (baseX, tapCount)
VALID_ROWS = 3

# ---- Callisto knobs ---------------------------------------------------
#
# OFFSET_SCALE IS THE ONE THAT MATTERS FOR FACIAL DETAIL, and the original
# value here was 10.0 -- a TEN TIMES wider subsurface blur than the engine
# authored.  An SSS kernel is a spatial blur over the diffuse lighting on
# skin, so at 10x radius every pore-scale and small-feature lighting
# variation on a face is averaged away before it is ever seen.  That is the
# "faces read soft / the shading just isn't detailed / it's all smoothed
# over" complaint, and it was this mod's own default (handoff/33 section 2).
#
# CENTER_SOFTEN compounds it: it moves weight OUT of the centre tap and into
# the off-centre taps, which is the same direction -- less of the pixel's own
# lighting, more of its neighbours'.
#
# Presets, selected with --preset (default: `detail`):
#
#   detail   the sharp one.  Vanilla blur RADIUS, no centre softening, and
#            only the red-channel tail kept from the Callisto reshape -- so
#            skin still gets the warm bleed that reads as flesh, without the
#            smear that costs the texture.  THIS IS THE DEFAULT NOW.
#   balanced 2x radius, mild softening: the Callisto character with some of
#            the detail cost back.
#   callisto the original shipped shape (10x radius).  Kept so the change is
#            reversible and A/B-able, NOT because it is recommended.
#   vanilla  identity -- reshapes nothing, for a true control.  With this the
#            swapped LUT is byte-identical to the engine's own upload.
#
# A/B note: the kernel is uploaded once at boot by the RED4ext plugin, so a
# preset change needs a relaunch, not a reload.  The CET "Callisto skin
# kernel" switch turns the whole swap off, which is the vanilla control.
PRESETS = {
    'detail':   dict(tail=(1.60, 1.05, 1.00), mid=0.10, soften=0.00, offset=1.0),
    'balanced': dict(tail=(2.00, 1.08, 1.00), mid=0.18, soften=0.15, offset=2.0),
    'callisto': dict(tail=(2.50, 1.10, 1.00), mid=0.25, soften=0.35, offset=10.0),
    'vanilla':  dict(tail=(1.00, 1.00, 1.00), mid=0.00, soften=0.00, offset=1.0),
}
_P = PRESETS['detail']
TAIL_WIDEN = _P['tail']           # per-channel: c1 diffuse-fresnel analog
MID_LIFT = _P['mid']              # c1 retroreflection analog
CENTER_SOFTEN = _P['soften']      # c2 smooth-terminator analog
OFFSET_SCALE = _P['offset']       # scales nonzero tap offsets (BLUR RADIUS)
# Runtime CB observed baseX=0 tapCount=6: the game reads only the first
# USED_TAPS of the 15-tap kernel. Normalize the radius axis to that window
# so tail/mid shaping lands on taps that are actually sampled.
USED_TAPS = {0: 6}                # subkernel baseX -> runtime tap window
# -----------------------------------------------------------------------

def load(path):
    raw = open(path, 'rb').read()
    vals = struct.unpack('<' + 'f' * (4 * W * H), raw[:16 * W * H])
    return [[list(vals[4 * (y * W + x):4 * (y * W + x) + 4]) for x in range(W)]
            for y in range(H)]

def store(tex, path_bin, path_json):
    flat = [v for row in tex for px in row for v in px]
    open(path_bin, 'wb').write(struct.pack('<' + 'f' * len(flat), *flat))
    json.dump({'width': W, 'height': H, 'format': 'R32G32B32A32_SFLOAT',
               'layout': 'rows 0..2 profiles; x=0..14 15-tap, x=15..23 9-tap, '
                         'x=24..29 6-tap; .rgb weights .a offset; rows 3..7 zero',
               'knobs': {'tail_widen': TAIL_WIDEN, 'mid_lift': MID_LIFT,
                         'center_soften': CENTER_SOFTEN,
                         'offset_scale': OFFSET_SCALE, 'used_taps': USED_TAPS},
               'texels': tex}, open(path_json, 'w'), indent=1)

def reshape_row(row):
    """row: list of 32 [r,g,b,a]; returns reshaped copy.

    Multiplicative (never interpolates) so the engine's degenerate center
    group (taps with offset ~0, incl. the red '1.0 spike') keeps its exact
    internal structure. Center group = taps with offset <= CENTER_EPS.
    """
    import math
    CENTER_EPS = 1e-6
    out = [px[:] for px in row]
    for base, taps in SUBKERNELS:
        offs = [row[base + i][3] for i in range(taps)]
        used = USED_TAPS.get(base, taps)
        omax = max(offs[:used]) or 1.0
        for c in range(3):
            w = [row[base + i][c] for i in range(taps)]
            nw = w[:]
            tw = TAIL_WIDEN[c]
            for i in range(taps):
                if offs[i] <= CENTER_EPS:
                    continue
                x = min(offs[i] / omax, 1.0)
                # 1) tail widen: quadratic ramp-in boost over the tail
                s = max(0.0, (x - 0.2) / 0.8)
                nw[i] *= 1.0 + (tw - 1.0) * s * s
                # 2) mid lift: gaussian bump centred at 0.35 of range
                g = math.exp(-0.5 * ((x - 0.35) / 0.15) ** 2)
                nw[i] *= 1.0 + MID_LIFT * g
            # 3) center soften: shift a fraction of center-group total into
            #    the first off-center taps (keeps group structure ratios)
            cg = [i for i in range(taps) if offs[i] <= CENTER_EPS]
            oc = [i for i in range(taps) if offs[i] > CENTER_EPS]
            if cg and oc and CENTER_SOFTEN > 0:
                csum = sum(nw[i] for i in cg)
                shift = CENTER_SOFTEN * csum
                scale = (csum - shift) / csum if csum > 0 else 1.0
                for i in cg:
                    nw[i] *= scale
                osum = sum(nw[i] for i in oc[:3])
                for i in oc[:3]:
                    nw[i] += shift * (nw[i] / osum if osum > 0 else 1.0 / len(oc[:3]))
            # 4) renormalize to original channel sum (energy preserving)
            s_old, s_new = sum(w), sum(nw)
            if s_new > 0 and s_old > 0:
                nw = [v * s_old / s_new for v in nw]
            for i in range(taps):
                out[base + i][c] = nw[i]
        if OFFSET_SCALE != 1.0:
            for i in range(taps):
                if offs[i] > CENTER_EPS:
                    out[base + i][3] = offs[i] * OFFSET_SCALE
    return out

def main():
    global TAIL_WIDEN, MID_LIFT, CENTER_SOFTEN, OFFSET_SCALE, DST_BIN, DST_JSON
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--preset', default='detail', choices=sorted(PRESETS),
                    help='named knob set (default: detail -- vanilla blur '
                         'radius, no centre softening)')
    ap.add_argument('--out', help='output .bin path (default: %s)' % DST_BIN)
    ap.add_argument('--offset-scale', type=float,
                    help='override the blur RADIUS multiplier; 1.0 is what '
                         'the engine authored')
    ap.add_argument('--center-soften', type=float,
                    help='override the centre-tap bleed (0 keeps the pixel\'s '
                         'own lighting)')
    a = ap.parse_args()
    P = PRESETS[a.preset]
    TAIL_WIDEN, MID_LIFT = P['tail'], P['mid']
    CENTER_SOFTEN, OFFSET_SCALE = P['soften'], P['offset']
    if a.offset_scale is not None:
        OFFSET_SCALE = a.offset_scale
    if a.center_soften is not None:
        CENTER_SOFTEN = a.center_soften
    if a.out:
        DST_BIN = a.out
        DST_JSON = os.path.splitext(a.out)[0] + '.json'
    print(f"preset={a.preset}  tail={TAIL_WIDEN} mid={MID_LIFT} "
          f"soften={CENTER_SOFTEN} offset_scale={OFFSET_SCALE}")
    tex = load(SRC)
    new = [reshape_row(tex[y]) if y < VALID_ROWS else [px[:] for px in tex[y]]
           for y in range(H)]
    store(new, DST_BIN, DST_JSON)
    # report
    print('wrote', DST_BIN, 'and', DST_JSON)
    for base, taps in SUBKERNELS:
        print(f'\nsub-kernel baseX={base} taps={taps} (row 0):')
        print('  tap  off       | wR old -> new | wG old -> new | wB old -> new')
        for i in range(taps):
            o = tex[0][base + i][3]
            wr = f"{tex[0][base+i][0]:.5f}->{new[0][base+i][0]:.5f}"
            wg = f"{tex[0][base+i][1]:.5f}->{new[0][base+i][1]:.5f}"
            wb = f"{tex[0][base+i][2]:.5f}->{new[0][base+i][2]:.5f}"
            print(f'  {i:3d}  {o:.6f} | {wr:>13} | {wg:>13} | {wb:>13}')

if __name__ == '__main__':
    main()
