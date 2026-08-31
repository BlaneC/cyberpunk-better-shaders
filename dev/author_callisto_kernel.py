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
#   spectral per-channel diffusion falloff from measured skin optics (Jensen
#            2001 skin1 -> Burley).  Vanilla blur radius (offsets untouched),
#            green byte-identical to vanilla, red widened and blue tightened
#            by the physical d ratios 2.688 : 1 : 0.4996.  handoff/52.
#
# A/B note: the kernel is uploaded once at boot by the RED4ext plugin, so a
# preset change needs a relaunch, not a reload.  The CET "Callisto skin
# kernel" switch turns the whole swap off, which is the vanilla control.
PRESETS = {
    'detail':   dict(tail=(1.60, 1.05, 1.00), mid=0.10, soften=0.00, offset=1.0),
    'balanced': dict(tail=(2.00, 1.08, 1.00), mid=0.18, soften=0.15, offset=2.0),
    'callisto': dict(tail=(2.50, 1.10, 1.00), mid=0.25, soften=0.35, offset=10.0),
    'vanilla':  dict(tail=(1.00, 1.00, 1.00), mid=0.00, soften=0.00, offset=1.0),
    # `spectral` ignores the tail/mid/soften knobs entirely -- it is a
    # different construction (see the SPECTRAL block below).  Offset scale is
    # pinned at 1.0 and is not overridable for it.
    'spectral': dict(tail=(1.00, 1.00, 1.00), mid=0.00, soften=0.00, offset=1.0,
                     mode='spectral'),
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

# ---- spectral preset (A6, handoff/52) ---------------------------------
#
# The four presets above all share ONE radial shape and tint it per channel
# (tail_widen).  `spectral` instead gives each channel its own diffusion
# falloff, taken from measured skin optics.
#
#   Jensen, Marschner, Levoy, Hanrahan 2001, "A Practical Model for
#   Subsurface Light Transport", skin1 sample, per mm:
#       sigma'_s = (0.74, 0.88, 1.01)      sigma_a = (0.032, 0.17, 0.48)
#   classical diffusion:  sigma'_t = sigma_a + sigma'_s
#                         sigma_tr = sqrt(3 * sigma_a * sigma'_t)
#                         ld = 1/sigma_tr = (3.67, 1.37, 0.68) mm
#   Christensen & Burley 2015 normalized diffusion:
#       R(r) = (exp(-r/d) + exp(-r/(3d))) / (8 pi d r),  d = ld / s,
#       s = 3.5  (their dmfp fit s = 3.5 + 100*(A-0.33)^4 is near-constant
#       over skin albedos, so it is used as a constant here).
#
# ONLY THE RATIOS ARE PHYSICS: d_R : d_G : d_B = 2.688 : 1 : 0.4996.  The mm
# per engine offset unit is unknown, so the absolute scale is ANCHORED: d_G
# is fitted to each sub-kernel's own vanilla GREEN weights, which makes green
# come out byte-identical to vanilla and pins the perceived blur radius to
# the engine's.  Offsets (.a) are never touched.  This preset therefore
# CANNOT re-enter the 10x-radius trap documented above: it moves no tap.
SPECTRAL_SIGMA_S_PRIME = (0.74, 0.88, 1.01)   # reduced scattering, per mm
SPECTRAL_SIGMA_A       = (0.032, 0.17, 0.48)  # absorption, per mm
SPECTRAL_BURLEY_S      = 3.5                  # dmfp -> d shaping constant
SPECTRAL_DISC_FRAC     = 0.5                  # centre disc radius = frac*r_1


def spectral_optics():
    """-> (ld_mm, d_mm, d_ratio_to_green) per channel, from the constants."""
    import math
    ld = [1.0 / math.sqrt(3.0 * sa * (sa + ssp))
          for sa, ssp in zip(SPECTRAL_SIGMA_A, SPECTRAL_SIGMA_S_PRIME)]
    d = [x / SPECTRAL_BURLEY_S for x in ld]
    return ld, d, [x / d[1] for x in d]


def burley_R(r, d):
    """Burley normalized diffusion profile; r > 0 (singular at r = 0)."""
    import math
    return (math.exp(-r / d) + math.exp(-r / (3.0 * d))) / (8.0 * math.pi * d * r)


def burley_disc(rc, d):
    """Fraction of R's total energy inside the disc r < rc.

    integral_0^rc R(r) 2 pi r dr = 1/4 [(1-e^-rc/d) + 3(1-e^-rc/3d)];
    -> 1 as rc -> inf, which is how R(0)'s singularity is disposed of: the
    centre group is never evaluated pointwise, only integrated.
    """
    import math
    return 0.25 * ((1.0 - math.exp(-rc / d)) + 3.0 * (1.0 - math.exp(-rc / (3.0 * d))))


def annulus_widths(r):
    """Midpoint widths dr_i for an ascending radius list (the quadrature the
    authored kernel appears to use: w ~ R(r) * r * dr, see handoff/52 §2)."""
    n = len(r)
    out = []
    for i in range(n):
        lo = (r[i] + r[i - 1]) / 2.0 if i > 0 else r[i] / 2.0
        hi = ((r[i] + r[i + 1]) / 2.0 if i < n - 1
              else r[i] + (r[i] - r[i - 1]) / 2.0 if n > 1 else r[i] * 1.5)
        out.append(hi - lo)
    return out


def fit_dg(r, w, envelope='annulus'):
    """Fit d in  w_i = A * R(r_i; d) * J_i  to one channel's own weights.

    J_i = r_i*dr_i ('annulus', the one the data supports -- see --inspect)
    or dr_i ('line', a 1-D separable blur).  Log space, A profiled out
    analytically (it is the weighted mean residual), weighted by w_i/sum(w)
    so the fit follows where the energy actually is rather than the 1e-20
    far tail.  Golden-section on ln d -- deterministic, no scipy.
    """
    import math
    dr = annulus_widths(r)
    use = [i for i in range(len(r)) if w[i] > 0.0]
    lw = [math.log(w[i]) for i in use]
    lj = [math.log(r[i] * dr[i] if envelope == 'annulus' else dr[i])
          for i in use]
    tot = sum(w[i] for i in use)
    om = [w[i] / tot for i in use]

    def cost(ld_):
        d = math.exp(ld_)
        e = [lw[k] - math.log(burley_R(r[i], d)) - lj[k]
             for k, i in enumerate(use)]
        mu = sum(o * v for o, v in zip(om, e))
        return sum(o * (v - mu) ** 2 for o, v in zip(om, e))

    lo, hi = math.log(min(r) / 100.0), math.log(max(r) * 100.0)
    g = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d_ = b - g * (b - a), a + g * (b - a)
    fc, fd = cost(c), cost(d_)
    for _ in range(200):
        if fc < fd:
            b, d_, fd = d_, c, fc
            c = b - g * (b - a); fc = cost(c)
        else:
            a, c, fc = c, d_, fd
            d_ = a + g * (b - a); fd = cost(d_)
    dbest = math.exp((a + b) / 2.0)
    return dbest, math.sqrt(cost(math.log(dbest)))


def spectral_row(row, journal=None):
    """Reshape one row's .rgb from per-channel diffusion physics.

    Per sub-kernel, per channel:
      1. d_G fitted to THIS block's vanilla green (fit_dg above);
         d_R, d_B = d_G * the physics ratios.
      2. Empirical envelope from green -- E_i = w_G(r_i)/R(r_i; d_G) off
         centre, E_0 = sum(w_G centre)/burley_disc(rc, d_G) for the centre
         group (rc = r_1/2).  The envelope carries whatever windowing and
         tap-density compensation the engine baked in, and it is channel
         independent because the offsets are shared.
      3. w_c = E_i * R(r_i; d_c) off centre;  the ZERO-OFFSET CENTRE GROUP
         IS LEFT EXACTLY AS VANILLA (handoff/52 §3): it holds 64-76% of a
         channel's weight while a Burley disc of the same radius at the
         fitted d holds 4-8%, so it is an authored centre-preservation
         spike, not a disc integral of the profile, and re-deriving it from
         one would move most of the kernel's energy off the centre tap --
         the exact move handoff/33 §1 blames for the soft faces.  It also
         disposes of R(0): the profile is never evaluated at r = 0.
      4. One scale per channel over the off-centre taps so their sum equals
         vanilla's; centre + off-centre sums therefore both match vanilla.
         Green is byte-identical to vanilla by construction.
    """
    import math
    CENTER_EPS = 1e-6
    out = [px[:] for px in row]
    _, _, ratio = spectral_optics()
    for base, taps in SUBKERNELS:
        offs = [row[base + i][3] for i in range(taps)]
        ctr = [i for i in range(taps) if offs[i] <= CENTER_EPS]
        off = [i for i in range(taps) if offs[i] > CENTER_EPS]
        if not off:
            continue
        r = [offs[i] for i in off]
        wg = [row[base + i][1] for i in off]
        dG, rms = fit_dg(r, wg)
        d = [ratio[0] * dG, dG, ratio[2] * dG]
        rc = SPECTRAL_DISC_FRAC * r[0]
        E = [wg[k] / burley_R(r[k], dG) for k in range(len(off))]
        cfrac, dfrac = [], burley_disc(rc, dG)
        for c in range(3):
            old = [row[base + i][c] for i in range(taps)]
            new = old[:]                      # centre group stays as vanilla
            for k, i in enumerate(off):
                new[i] = E[k] * burley_R(r[k], d[c])
            s_old = sum(old[i] for i in off)
            s_new = sum(new[i] for i in off)
            if s_new > 0 and s_old > 0:
                for i in off:
                    new[i] *= s_old / s_new
            tot = sum(old)
            cfrac.append(sum(old[i] for i in ctr) / tot if tot > 0 else 0.0)
            for i in range(taps):
                out[base + i][c] = new[i]
        if journal is not None:
            journal.append(dict(base=base, taps=taps, d_green=dG,
                                d=[d[0], d[1], d[2]], fit_rms_log=rms,
                                n_fit=len(off),
                                centre_group_weight_frac=cfrac,
                                centre_disc_r=rc,
                                burley_disc_frac_at_d_green=dfrac,
                                mm_per_offset_unit=(spectral_optics()[1][1] / dG)))
    return out


def load(path):
    raw = open(path, 'rb').read()
    vals = struct.unpack('<' + 'f' * (4 * W * H), raw[:16 * W * H])
    return [[list(vals[4 * (y * W + x):4 * (y * W + x) + 4]) for x in range(W)]
            for y in range(H)]

def store(tex, path_bin, path_json, extra=None):
    flat = [v for row in tex for px in row for v in px]
    open(path_bin, 'wb').write(struct.pack('<' + 'f' * len(flat), *flat))
    meta = {'width': W, 'height': H, 'format': 'R32G32B32A32_SFLOAT',
            'layout': 'rows 0..2 profiles; x=0..14 15-tap, x=15..23 9-tap, '
                      'x=24..29 6-tap; .rgb weights .a offset; rows 3..7 zero',
            'knobs': {'tail_widen': TAIL_WIDEN, 'mid_lift': MID_LIFT,
                      'center_soften': CENTER_SOFTEN,
                      'offset_scale': OFFSET_SCALE, 'used_taps': USED_TAPS}}
    if extra:
        meta.update(extra)
    meta['texels'] = tex
    json.dump(meta, open(path_json, 'w'), indent=1)

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

def fit_d_ratio(r, wx, wy):
    """Fit (d_x, d_y) from the CHANNEL RATIO wx/wy alone.

    Any envelope (tap density, windowing, quadrature) is shared by the
    channels because the offsets are shared, so it cancels out of the ratio.
    This is therefore an envelope-FREE estimate, independent of fit_dg's
    annulus assumption -- the two are cross-checked in --inspect.
    Coordinate descent of the same golden-section used above.
    """
    import math
    # Drop the deep tail: float32 keeps values down to 1e-23 here, they carry
    # no energy, and unweighted log-space fitting would let them dominate.
    fx, fy = 1e-6 * max(wx), 1e-6 * max(wy)
    use = [i for i in range(len(r)) if wx[i] > fx and wy[i] > fy]
    if len(use) < 3:
        return None, None, float('nan'), 0
    lr = [math.log(wx[i] / wy[i]) for i in use]

    def cost(dx, dy):
        s = 0.0
        for k, i in enumerate(use):
            m = (math.log(burley_R(r[i], dx)) - math.log(burley_R(r[i], dy)))
            s += (lr[k] - m) ** 2
        return s / len(use)

    def golden(f, lo, hi):
        g = (math.sqrt(5.0) - 1.0) / 2.0
        a, b = lo, hi
        c, d = b - g * (b - a), a + g * (b - a)
        fc, fd = f(c), f(d)
        for _ in range(120):
            if fc < fd:
                b, d, fd = d, c, fc
                c = b - g * (b - a); fc = f(c)
            else:
                a, c, fc = c, d, fd
                d = a + g * (b - a); fd = f(d)
        return (a + b) / 2.0

    lo, hi = math.log(min(r) / 200.0), math.log(max(r) * 200.0)
    dx = dy = math.exp((lo + hi) / 2.0)
    for _ in range(60):
        dx = math.exp(golden(lambda t: cost(math.exp(t), dy), lo, hi))
        dy = math.exp(golden(lambda t: cost(dx, math.exp(t)), lo, hi))
    return dx, dy, math.sqrt(cost(dx, dy)), len(use)


def inspect(tex):
    """Print the vanilla-kernel evidence handoff/52 §2 is built on."""
    import math
    CENTER_EPS = 1e-6
    print('=== 1. how much of each channel is re-authored per row ===')
    print('  (taps out of N that differ between row 0 and rows 1,2)')
    print('  block     R      G      B      offset')
    for base, taps in SUBKERNELS:
        cells = []
        for c in (0, 1, 2, 3):
            n = sum(1 for i in range(taps)
                    if any(tex[y][base + i][c] != tex[0][base + i][c]
                           for y in range(1, VALID_ROWS)))
            cells.append('%2d/%-2d' % (n, taps))
        print('  base%-3d  %s  %s  %s  %s' % (base, *cells))
    print('\n=== 2. centre group (offset 0) share of channel weight, percent ===')
    print('  block        R     G     B    taps at offset 0')
    for y in range(VALID_ROWS):
        for base, taps in SUBKERNELS:
            ctr = [i for i in range(taps) if tex[y][base + i][3] <= CENTER_EPS]
            f = []
            for c in range(3):
                t = sum(tex[y][base + i][c] for i in range(taps))
                f.append(100.0 * sum(tex[y][base + i][c] for i in ctr) / t if t else 0)
            print('  row%d base%-3d %5.1f %5.1f %5.1f    %d'
                  % (y, base, f[0], f[1], f[2], len(ctr)))
    print('\n=== 3. envelope test: w = A*R(r;d)*J, log-space rms ===')
    print('  (annulus J = r*dr  vs  line J = dr)')
    print('  block        R annul/line   G annul/line   B annul/line')
    win = loss = tie = 0
    for y in range(VALID_ROWS):
        for base, taps in SUBKERNELS:
            offs = [tex[y][base + i][3] for i in range(taps)]
            off = [i for i in range(taps) if offs[i] > CENTER_EPS]
            r = [offs[i] for i in off]
            cells = []
            for c in range(3):
                w = [tex[y][base + i][c] for i in off]
                if sum(1 for v in w if v > 0) < 3:
                    cells.append('    n/a     '); continue
                a = fit_dg(r, w, 'annulus')[1]
                b = fit_dg(r, w, 'line')[1]
                if a < 0.95 * b: win += 1
                elif b < 0.95 * a: loss += 1
                else: tie += 1
                cells.append('%.3f/%.3f' % (a, b))
            print('  row%d base%-3d %s' % (y, base, '   '.join(cells)))
    print('  annulus wins %d, loses %d, ties %d' % (win, loss, tie))
    print('\n=== 4. vanilla\'s OWN d ratios, envelope-free (channel ratios) ===')
    print('  physics target: d_R/d_G = 2.688, d_B/d_G = 0.4996')
    print('  block        d_R/d_G  d_B/d_G   d_G(ratio fit)  d_G(green fit)'
          '  delta   n(R,B)')
    for y in range(VALID_ROWS):
        for base, taps in SUBKERNELS:
            offs = [tex[y][base + i][3] for i in range(taps)]
            off = [i for i in range(taps) if offs[i] > CENTER_EPS]
            r = [offs[i] for i in off]
            w = [[tex[y][base + i][c] for i in off] for c in range(3)]
            dR, dG1, _, nR = fit_d_ratio(r, w[0], w[1])
            dB, dG2, _, nB = fit_d_ratio(r, w[2], w[1])
            dGf = fit_dg(r, w[1])[0]
            if dR is None or dB is None:
                print('  row%d base%-3d   (too few usable taps)' % (y, base)); continue
            dGr = (dG1 + dG2) / 2.0
            print('  row%d base%-3d %8.3f %8.3f   %.4e     %.4e   %+6.1f%%   %d,%d'
                  % (y, base, dR / dG1, dB / dG2, dGr, dGf,
                     100.0 * (dGr - dGf) / dGf, nR, nB))


def validate(old_tex, _new, path_bin, offsets_locked=False):
    """Print the checks handoff/52 requires; return True if all passed.

    Everything is re-read from the written .bin, so the numbers are the
    float32 the engine will actually see, not the float64 that built them.
    """
    ok = True
    n = os.path.getsize(path_bin)
    new_tex = load(path_bin)
    print('\nvalidation')
    print('  size %d bytes %s' % (n, 'OK' if n == 4096 else 'FAIL'))
    ok &= (n == 4096)
    z = all(v == 0.0 for y in range(VALID_ROWS, H)
            for px in new_tex[y] for v in px)
    print('  rows %d..%d all zero %s' % (VALID_ROWS, H - 1, 'OK' if z else 'FAIL'))
    ok &= z
    same = all(new_tex[y][x][3] == old_tex[y][x][3]
               for y in range(H) for x in range(W))
    tag = 'OK' if same else ('FAIL' if offsets_locked else 'changed (by design)')
    print('  .a offsets identical to vanilla: %s' % tag)
    ok &= (same or not offsets_locked)
    worst = 0.0
    for y in range(VALID_ROWS):
        for base, taps in SUBKERNELS:
            for c in range(3):
                a_ = sum(old_tex[y][base + i][c] for i in range(taps))
                b_ = sum(new_tex[y][base + i][c] for i in range(taps))
                if a_ > 0:
                    worst = max(worst, abs(b_ - a_) / a_)
    print('  per-channel per-sub-kernel weight sums vs vanilla: worst '
          'relative error %.3e %s' % (worst, 'OK' if worst < 1e-6 else 'FAIL'))
    ok &= (worst < 1e-6)
    print('  ALL CHECKS %s' % ('PASSED' if ok else 'FAILED'))
    return ok


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
    ap.add_argument('--inspect', action='store_true',
                    help='print the vanilla-kernel measurements handoff/52 '
                         'is built on, write nothing, and exit')
    a = ap.parse_args()
    if a.inspect:
        inspect(load(SRC))
        return
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
    mode = PRESETS[a.preset].get('mode', 'shape')
    tex = load(SRC)
    extra = None
    if mode == 'spectral':
        if a.offset_scale is not None or a.center_soften is not None:
            ap.error('--offset-scale/--center-soften do not apply to '
                     '--preset spectral (it reshapes weights only)')
        ld, dmm, ratio = spectral_optics()
        print(f"preset={a.preset}  sigma'_s={SPECTRAL_SIGMA_S_PRIME} "
              f"sigma_a={SPECTRAL_SIGMA_A} s={SPECTRAL_BURLEY_S}")
        print('  ld_mm  = (%.4f, %.4f, %.4f)' % tuple(ld))
        print('  d_mm   = (%.4f, %.4f, %.4f)' % tuple(dmm))
        print('  d ratio to green = (%.4f, %.4f, %.4f)' % tuple(ratio))
        journal = []
        new = [spectral_row(tex[y], journal) if y < VALID_ROWS
               else [px[:] for px in tex[y]] for y in range(H)]
        print('\n  green anchor fits (per row, per sub-kernel):')
        print('   row base  n   d_green      d_red       d_blue      '
              'fit rms(log)  mm/offset-unit  centreW%(R,G,B)  Burley disc%')
        for y in range(VALID_ROWS):
            for j in journal[y * len(SUBKERNELS):(y + 1) * len(SUBKERNELS)]:
                print('   %3d %4d %3d  %.4e  %.4e  %.4e  %8.4f      %9.4g'
                      '   %2.0f/%2.0f/%2.0f          %5.1f'
                      % (y, j['base'], j['n_fit'], j['d_green'], j['d'][0],
                         j['d'][2], j['fit_rms_log'], j['mm_per_offset_unit'],
                         100 * j['centre_group_weight_frac'][0],
                         100 * j['centre_group_weight_frac'][1],
                         100 * j['centre_group_weight_frac'][2],
                         100 * j['burley_disc_frac_at_d_green']))
        extra = {'spectral': {
            'knobs_note': 'the tail_widen/mid_lift/center_soften/offset_scale '
                          'knobs recorded above are INERT for this preset -- '
                          'it is a different construction, described here',
            'source': 'Jensen/Marschner/Levoy/Hanrahan 2001, skin1 sample',
            'sigma_s_prime_per_mm': list(SPECTRAL_SIGMA_S_PRIME),
            'sigma_a_per_mm': list(SPECTRAL_SIGMA_A),
            'sigma_tr_per_mm': [1.0 / x for x in ld],
            'ld_mm': ld, 'burley_s': SPECTRAL_BURLEY_S,
            'burley_s_note': 'Christensen-Burley 2015 dmfp fit '
                             's = 3.5 + 100*(A-0.33)^4 is near-constant over '
                             'skin albedos; held constant, not solved per '
                             'channel -- it cancels out of the d ratios and '
                             'the absolute scale is anchored, not physical',
            'd_mm': dmm, 'd_ratio_to_green': ratio,
            'anchor': 'd_green fitted per (row, sub-kernel) to that block\'s '
                      'own vanilla GREEN weights, model w = A*R(r;d)*r*dr, '
                      'log space, weighted by w; green therefore comes out '
                      'byte-identical to vanilla and the perceived blur '
                      'radius is the engine\'s',
            'construction': 'ratio-reshape off the green envelope: '
                            'E_i = w_vanilla_green(r_i)/R(r_i;d_green), then '
                            'w_c(r_i) = E_i * R(r_i;d_c) for the OFF-CENTRE '
                            'taps only; the zero-offset centre group is left '
                            'exactly as vanilla (it is an authored '
                            'centre-preservation spike, not a disc integral: '
                            'see centre_group_weight_frac vs '
                            'burley_disc_frac_at_d_green per block), which '
                            'also means R(0) is never evaluated; one scale '
                            'per channel over the off-centre taps restores '
                            'vanilla\'s sums',
            'centre_disc_radius_frac_of_first_tap': SPECTRAL_DISC_FRAC,
            'centre_disc_note': 'the disc integral is computed and reported '
                                'as evidence only -- it is NOT applied',
            'offsets': 'untouched -- byte-identical to vanilla',
            'blocks': journal}}
    else:
        print(f"preset={a.preset}  tail={TAIL_WIDEN} mid={MID_LIFT} "
              f"soften={CENTER_SOFTEN} offset_scale={OFFSET_SCALE}")
        new = [reshape_row(tex[y]) if y < VALID_ROWS else [px[:] for px in tex[y]]
               for y in range(H)]
    store(new, DST_BIN, DST_JSON, extra)
    validate(tex, new, DST_BIN, offsets_locked=(mode == 'spectral'))
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
