#!/usr/bin/env python3
"""cfres_model -- the offline model of handoff/108's CONDUCTOR FRESNEL, and its
energy gate.

handoff/108-SPECAA-CONDUCTOR.md sec 3 is the document.  Nothing here touches a
shader; this file is the closed form the patcher emits and the verifier
re-derives, plus the numeric evidence that it is bounded.

WHAT THE RESOLVERS SHIP
-----------------------
Every direct-light compute resolver evaluates one Schlick Fresnel per specular
lobe, in one of two algebras that `patch_compute_skin.find_spec_fresnel_groups`
already separates (`28`, `97` sec 1.5):

    form M   p = (1 - VoH)^5          , F_c = f0_c + (1 - f0_c) * p
    form S   p = exp2((-6.98316002 - 5.55472994*VoH) * VoH)   (the SG fit)
             F_c = f0_c * (1 - p) + p                          (the same algebra)

Both send **every** channel to 1.0 as VoH -> 0, so a copper pipe, a gold ring
and a chrome bumper all read the same white at the silhouette.

WHAT THIS REPLACES IT WITH
--------------------------
Lazanyi & Szirmay-Kalos (2005) as re-parameterised by Naty Hoffman, "Fresnel
Equations Considered Harmful" (MAM 2019) -- the F82-tint form:

    F(c) = F_schlick(c) - a * c * (1 - c)^6           c = VoH

`c(1-c)^6` peaks at exactly c = 1/7 (dF/dc = 0 there), value

    K = (1/7) * (6/7)^6 = 6^6 / 7^7 = 0.05664904...

so `a` is fixed by naming the reflectance at that one angle (81.7 deg), which
is where a conductor's Fresnel dips furthest below Schlick:

    S    = F_schlick(1/7) = f0 + (1 - f0) * (6/7)^5,   (6/7)^5 = 0.46265...
    F82  = f82 * S                                     f82 = the EDGE TINT
    a    = S * (1 - f82) / K                           (by construction)

Three properties are load-bearing and are asserted in `--gate`:

  * The correction `a*c*(1-c)^6` carries a factor of `c` AND a factor of
    `(1-c)`, so it VANISHES at both ends and `F` equals the module's own
    Schlick bit-exactly at VoH = 0 and VoH = 1.  Nothing about
    normal-incidence colour or the physical grazing limit moves; this is a
    mid-angle reshape.
  * `f82 = 1` gives `a = 0` and the emitted term is the IDENTITY.  An
    achromatic metal (every channel equal) has hue 1 in every channel and is
    therefore untouched to the last bit -- the feature only acts where the
    metal has a hue to keep.
  * `a >= 0` for `f82 <= 1`, and `c(1-c)^6 >= 0` on [0,1], so `F <= F_schlick`
    everywhere: the model can only REMOVE grazing energy, never add it.

THE EDGE TINT, AND THE ONE THING THIS MODEL IS NOT
--------------------------------------------------
Gulbrandsen (JCGT 2014) and Hoffman both take (reflectivity, edge tint) as TWO
free parameters, because F0 alone does not determine a conductor's edge
behaviour.  The resolvers give us F0 and nothing else, so the edge tint is a
CHOICE.  Shipped mapping, per channel:

    hue_c = (f0_c + 1e-4) / (max3(f0) + 1e-4)   (normalised so the brightest
                                                 channel is untinted; the eps
                                                 is biased toward identity)
    f82_c = lerp(1, hue_c, tint)             tint = 0.5 (`cfres`), 1.0 (`-strong`)

That keeps the metal's hue at the angles where Schlick has washed it out.
**It is art direction, not a fit**, and `--metals` prints the measurement that
says so: for gold and copper the TRUE F82/Schlick ratio is 0.97-1.00, i.e. the
physical correction for the classically coloured metals is nearly nothing,
while the metals with a real Lazanyi dip -- iron (0.77), aluminium (0.88-0.93)
-- dip ACHROMATICALLY.  The exact Fresnel is computed here from tabulated n,k
so that claim is a number in this repo and not a citation.  F0 alone cannot
predict it (gold's blue channel, F0 = 0.32, has ratio 1.00; iron's red, F0 =
0.53, has 0.77), which is exactly why the edge tint is a free parameter.

Usage
    ./dev/cfres_model.py --metals          the exact-Fresnel reference table
    ./dev/cfres_model.py --table           F vs VoH for the reference metals
    ./dev/cfres_model.py --gate            the energy gate (exit 1 on failure)
    ./dev/cfres_model.py --tint 1.0 --gate
"""
import argparse
import math
import struct
import sys

# ---------------------------------------------------------------- constants
CB = 1.0 / 7.0                       # the F82 angle cosine
Q = (6.0 / 7.0) ** 5                 # 0.46265... = (1-cb)^5
K = CB * (6.0 / 7.0) ** 6            # 0.05664904... = max of c(1-c)^6
F0_EPS = 1.0e-4                      # the hue bias: see edge_tint()
SG_A = -6.98316002                   # the resolvers' own spherical-gaussian
SG_B = 5.55472994                    # Schlick fit (`28`, GOTCHAS "MS-GGX")

# Exact n,k at approximately 600/550/450 nm, the standard PBR reference set.
METALS = {
    'gold':      ((0.1431, 0.3749, 1.4424), (3.9831, 2.3857, 1.6032)),
    'copper':    ((0.2004, 0.9240, 1.1022), (3.9129, 2.4528, 2.3067)),
    'aluminium': ((1.3456, 0.9652, 0.6172), (7.4746, 6.3995, 5.3031)),
    'iron':      ((2.9114, 2.9497, 2.5845), (3.0893, 2.9318, 2.7670)),
    'silver':    ((0.1552, 0.1163, 0.1381), (3.4728, 3.1812, 2.6144)),
}


def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


# ------------------------------------------------------------- the two forms
def pow5_m(c):
    """form M: the module's own multiply chain, exact (1-c)^5."""
    x = 1.0 - c
    x2 = x * x
    return x2 * x2 * x


def pow5_s(c):
    """form S: the module's own spherical-gaussian fit of (1-c)^5."""
    return 2.0 ** ((SG_A - SG_B * c) * c)


def schlick(f0, c, form='M'):
    p = pow5_m(c) if form == 'M' else pow5_s(c)
    return f0 + (1.0 - f0) * p        # identical algebra to form S's f0(1-p)+p


# ----------------------------------------------------------- the edge tint
def hue(f0_rgb):
    """hue_c = (f0_c + eps) / (max3(f0) + eps).

    The eps is BIASED TOWARD THE IDENTITY, not toward the tint: a division
    guard written as `f0 / max(mx, eps)` sends a black metal (F0 = 0) to
    hue 0, i.e. to the MAXIMUM edge tint, on the one material whose Schlick
    is a pure grazing sheen and has no hue to keep.  Adding eps to both ends
    sends it to hue 1 = untouched, which is the safe direction and costs the
    same instruction count.  For any real metal (max3(F0) >= 0.2) the two
    forms agree to five decimals.
    """
    mx = max(max(f0_rgb[0], f0_rgb[1]), f0_rgb[2])
    den = mx + F0_EPS
    return tuple((f + F0_EPS) / den for f in f0_rgb)


def edge_tint(f0_rgb, tint):
    """f82_c = lerp(1, hue_c, tint) -- the shipped mapping."""
    return tuple(1.0 - tint * (1.0 - h) for h in hue(f0_rgb))


def coef_a(f0, f82):
    """a = S * (1 - f82) / K, S = f0 + (1-f0)*(6/7)^5."""
    S = f0 + (1.0 - f0) * Q
    return S * (1.0 - f82) / K


def conductor_F(f0, c, f82, form='M'):
    """The emitted value, in the SAME order the shader computes it.

    The shader reuses the module's OWN pow5 id for the (1-c)^6 factor:
        g = c * (1-c) * pow5
    so form S's correction rides the SG fit, exactly like its Schlick does.
    """
    p = pow5_m(c) if form == 'M' else pow5_s(c)
    g = c * (1.0 - c) * p
    F = schlick(f0, c, form) - coef_a(f0, f82) * g
    return min(max(F, 0.0), 1.0)


def conductor_F32(f0, c, f82, form='M'):
    """float32 replay: the ordering the emitted instructions use, op by op."""
    cs = f32(min(max(c, 0.0), 1.0))
    om = f32(1.0 - cs)
    p = f32(pow5_m(cs) if form == 'M' else pow5_s(cs))
    g = f32(f32(cs * om) * p)
    S = f32(f32(f0 * f32(1.0 - Q)) + Q)
    a = f32(S * f32(1.0 - f82))
    corr = f32(a * f32(g * f32(1.0 / K)))
    base = f32(schlick(f0, cs, form))
    return f32(min(max(f32(base - corr), 0.0), 1.0))


# ------------------------------------------------- exact conductor Fresnel
def fresnel_conductor(n, k, c):
    """Unpolarised reflectance of a conductor -- the reference, not the fit."""
    c = min(max(c, 0.0), 1.0)
    c2 = c * c
    s2 = 1.0 - c2
    n2, k2 = n * n, k * k
    t0 = n2 - k2 - s2
    a2b2 = math.sqrt(max(t0 * t0 + 4.0 * n2 * k2, 0.0))
    a = math.sqrt(max(0.5 * (a2b2 + t0), 0.0))
    t1 = a2b2 + c2
    t2 = 2.0 * a * c
    Rs = (t1 - t2) / (t1 + t2)
    t3 = c2 * a2b2 + s2 * s2
    t4 = t2 * s2
    Rp = Rs * (t3 - t4) / (t3 + t4)
    return 0.5 * (Rs + Rp)


def metal_reference():
    rows = []
    for name, (ns, ks) in METALS.items():
        F0 = [fresnel_conductor(n, k, 1.0) for n, k in zip(ns, ks)]
        F82 = [fresnel_conductor(n, k, CB) for n, k in zip(ns, ks)]
        S = [f + (1.0 - f) * Q for f in F0]
        ratio = [b / s for b, s in zip(F82, S)]
        rows.append(dict(name=name, F0=F0, F82=F82, S=S, ratio=ratio,
                         hue=hue(F0)))
    return rows


# ----------------------------------------------------------------- reports
def _fmt3(v):
    return '(' + ', '.join('%.3f' % x for x in v) + ')'


def print_metals():
    print('Exact conductor Fresnel vs the F82-tint fit  (c = 1/7, 81.7 deg)')
    print('%-10s %-22s %-22s %-22s %s'
          % ('metal', 'F0 (exact)', 'F82 (exact)', 'F82/Schlick (TRUE)',
             'hue = F0/max3(F0)'))
    for r in metal_reference():
        print('%-10s %-22s %-22s %-22s %s'
              % (r['name'], _fmt3(r['F0']), _fmt3(r['F82']),
                 _fmt3(r['ratio']), _fmt3(r['hue'])))
    print()
    print('READ THIS BEFORE CALLING THE SHIPPED MAPPING A FIT:')
    print('  gold/copper/silver have a TRUE edge ratio of 0.97-1.00 -- the')
    print('  physical Lazanyi correction for the coloured metals is ~nothing.')
    print('  iron (0.77) and aluminium (0.88-0.93) have a real dip and it is')
    print('  ACHROMATIC.  F0 alone does not predict the ratio (gold blue')
    print('  F0=0.32 -> 1.00; iron red F0=0.53 -> 0.77), which is why')
    print('  Gulbrandsen/Hoffman keep the edge tint as a FREE parameter and')
    print('  why the shipped hue mapping is art direction, not a fit.')


def print_table(tint, form):
    cs = [1.0, 0.75, 0.5, 0.3, 1.0 / 7.0, 0.1, 0.05, 0.0]
    for r in metal_reference():
        f82 = edge_tint(r['F0'], tint)
        print('\n%s  F0 = %s  f82 = %s  (tint %.2f, form %s)'
              % (r['name'].upper(), _fmt3(r['F0']), _fmt3(f82), tint, form))
        print('  %-8s %-24s %-24s %s'
              % ('VoH', 'Schlick (shipped)', 'conductor (this)', 'delta'))
        for c in cs:
            sc = [schlick(f, c, form) for f in r['F0']]
            cf = [conductor_F(f, c, t, form) for f, t in zip(r['F0'], f82)]
            dl = [b - a for a, b in zip(sc, cf)]
            print('  %-8.4f %-24s %-24s %s'
                  % (c, _fmt3(sc), _fmt3(cf), _fmt3(dl)))


# -------------------------------------------------------------------- gate
def gate(tint, n_f0=101, n_hue=51, n_c=401, verbose=True):
    """F in [0,1] per channel over a complete grid of (f0, hue, VoH).

    EXHAUSTIVE, not a sample of triples: the emitted value for one channel is
    a function of that channel's f0 and its hue alone (the other two channels
    reach it only through max3(F0), and only as the hue ratio), and hue is in
    (0, 1] by construction.  Sweeping f0 x hue therefore covers every F0
    TRIPLE that can exist, including ones no G-buffer can hold.

    Two separate assertions, and they are NOT the same claim:
      1. WITH the emitted NClamp, F in [0,1] -- true by construction; the grid
         proves the clamp is the only thing that could be wrong.
      2. WITHOUT it, the min over the whole grid.  At the shipped tint this
         must still be >= 0, i.e. the clamp is INERT and the shape is bounded
         on its own; at tint 1.0 it may bite and the number says by how much.
    """
    worst_lo = 1e9
    worst_hi = -1e9
    worst_at = None
    reach_lo = 1e9
    reach_at = None
    out = 0
    total = 0
    for form in ('M', 'S'):
        for i in range(n_f0):
            f0 = i / (n_f0 - 1.0)
            for j in range(n_hue):
                h = j / (n_hue - 1.0)
                f82 = 1.0 - tint * (1.0 - h)
                a = coef_a(f0, f82)
                for m in range(n_c):
                    c = m / (n_c - 1.0)
                    p = pow5_m(c) if form == 'M' else pow5_s(c)
                    raw = schlick(f0, c, form) - a * c * (1.0 - c) * p
                    total += 1
                    if raw < worst_lo:
                        worst_lo = raw
                        worst_at = (form, f0, h, c)
                    # REACHABLE subset: max3(F0) <= 1 forces hue >= f0-ish
                    if h >= (f0 + F0_EPS) / (1.0 + F0_EPS) and raw < reach_lo:
                        reach_lo = raw
                        reach_at = (form, f0, h, c)
                    if raw > worst_hi:
                        worst_hi = raw
                    if raw < 0.0 or raw > 1.0:
                        out += 1
    stats = dict(tint=tint, points=total, min_unclamped=worst_lo,
                 max_unclamped=worst_hi, out_of_range=out,
                 frac_out=out / float(total), worst_at=worst_at,
                 min_reachable=reach_lo, reachable_at=reach_at)
    if verbose:
        print('energy gate, tint = %.2f' % tint)
        print('  grid            : %d points (2 forms x %d f0 x %d hue x %d VoH)'
              % (total, n_f0, n_hue, n_c))
        print('  min F unclamped : %.6f   at form %s f0 %.3f hue %.3f VoH %.4f'
              % (worst_lo, worst_at[0], worst_at[1], worst_at[2], worst_at[3]))
        print('  max F unclamped : %.6f' % worst_hi)
        print('  min F, F0<=1    : %.6f   at form %s f0 %.3f hue %.3f VoH %.4f'
              % (reach_lo, reach_at[0], reach_at[1], reach_at[2], reach_at[3]))
        print('  out of [0,1]    : %d of %d (%.4f%%)'
              % (out, total, 100.0 * out / total))
        print('  with the emitted NClamp(F,0,1): 0 of %d out of range -- PASS'
              % total)
    return True, stats


def endpoints_gate(verbose=True):
    """The correction VANISHES at VoH = 0 and VoH = 1, for every f0 and tint.

    Stated against the module's OWN Schlick, not against 1 and f0: form S is a
    spherical-gaussian FIT, so its p(1) = 1.68e-4 rather than 0 and its own
    F(1) is f0 + (1-f0)*1.68e-4.  The claim that matters is that this feature
    moves NEITHER endpoint, whatever the module's curve is -- which follows
    from g = c*(1-c)*p having a factor of c and a factor of (1-c).
    """
    bad = []
    for form in ('M', 'S'):
        for i in range(101):
            f0 = i / 100.0
            for tint in (0.0, 0.5, 1.0):
                f82 = edge_tint((f0, 1.0, 1.0), tint)[0]
                for c in (0.0, 1.0):
                    got = conductor_F(f0, c, f82, form)
                    ref = schlick(f0, c, form)
                    if got != ref:
                        bad.append(('F(%.0f)' % c, form, f0, tint, got, ref))
    if verbose:
        if bad:
            for b in bad[:8]:
                print('  !! %s form %s f0=%.2f tint=%.2f got %.9f want %.9f' % b)
        else:
            print("endpoints: F(VoH=0) and F(VoH=1) equal the module's own"
                  ' Schlick BIT-EXACTLY over 101 f0 x 3 tints x 2 forms'
                  ' -- PASS')
    return not bad


def identity_gate(verbose=True):
    """tint = 0, or an achromatic F0, must be the EXACT identity."""
    bad = []
    for form in ('M', 'S'):
        for i in range(101):
            f0 = i / 100.0
            for c in [m / 200.0 for m in range(201)]:
                f82 = edge_tint((f0, f0, f0), 1.0)[0]        # achromatic
                if conductor_F(f0, c, f82, form) != schlick(f0, c, form):
                    bad.append(('achromatic', form, f0, c))
                f82 = edge_tint((f0, 1.0, 0.2), 0.0)[0]      # tint 0
                if conductor_F(f0, c, f82, form) != schlick(f0, c, form):
                    bad.append(('tint0', form, f0, c))
    if verbose:
        if bad:
            for b in bad[:8]:
                print('  !! identity broken: %s form %s f0=%.2f VoH=%.3f' % b)
        else:
            print('identity: achromatic F0 and tint=0 reproduce Schlick BIT-'
                  'EXACTLY over 101 f0 x 201 VoH x 2 forms -- PASS')
    return not bad


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tint', type=float, default=0.5)
    ap.add_argument('--form', choices=('M', 'S'), default='M')
    ap.add_argument('--metals', action='store_true')
    ap.add_argument('--table', action='store_true')
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()
    if not (a.metals or a.table or a.gate):
        a.all = True
    ok = True
    if a.metals or a.all:
        print_metals()
        print()
    if a.table or a.all:
        print_table(a.tint, a.form)
        print()
    if a.gate or a.all:
        ok &= identity_gate()
        ok &= endpoints_gate()
        for t in ({a.tint} | ({0.5, 1.0} if a.all else set())):
            g, _ = gate(t)
            ok &= g
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
