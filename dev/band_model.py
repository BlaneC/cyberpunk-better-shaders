#!/usr/bin/env python3
"""78: what the mod does to the SHADOW FALLOFF, in numbers.

Every figure quoted in handoff/78 prints here. The question it answers is not
"is the bleed pretty" but "how far above vanilla does the mod hold the
terminator band", which is the thing a deeper shadow needs back.

The shape being modelled, per pixel, is the multiplier the stack applies to
the diffuse term -- c1 (the tier-1 factor) times the bleed's per-channel
triple -- as a function of NoL. It is reported NORMALISED AT THE LIT CHEEK
(NoL = 1), because that is what the eye compares: vanilla is then 1.000
everywhere by construction, and any number above 1.0 is the mod holding the
band brighter than vanilla would.

    ./dev/band_model.py            # the tables in handoff/78
    ./dev/band_model.py --nov 0.5  # the direct path at a different view angle
"""

import argparse

W709 = (0.2126, 0.7152, 0.0722)
KR, KB, BAND = 0.336, 0.101, 0.35
SKIN = (0.35, 0.20, 0.16)      # a rosy linear skin diffuse colour
EXPO = 2.5

# the two c1s: the compute resolvers carry the full KNOBS pair and have NoV in
# scope; the ReSTIR-GI ST pair runs at --strength 0.5 and has no view vector
# (50 s3.1), so its factor is the NoL half alone.
C1_DIRECT = (1.35, 1.25)
C1_BOUNCE = (1.175, 1.125)


def w_of(nol):
    return max(0.0, min(1.0, 1.0 - nol / BAND)) ** 2


def bleed(nol, k=1.0, colour=SKIN, norm=0.0):
    """the emitted triple, as (m_R, m_G, m_B)."""
    w = w_of(nol)
    m = [1 + KR * k * w, 1.0, 1 - KB * k * w]
    if norm > 0.0:
        Y = sum(wi * ci for wi, ci in zip(W709, colour))
        d = w * norm * k * (W709[0] * KR * colour[0] - W709[2] * KB * colour[2])
        s = Y / max(Y + d, 1e-5)
        m = [x * s for x in m]
    return m


def luma_gain(nol, k=1.0, colour=SKIN, norm=0.0):
    m = bleed(nol, k, colour, norm)
    y0 = sum(wi * ci for wi, ci in zip(W709, colour))
    y1 = sum(wi * ci * mi for wi, ci, mi in zip(W709, colour, m))
    return y1 / y0


def c1(nol, nov, rhos, view=True):
    rf, rr = rhos
    af = (1 - nol) ** EXPO * (nov ** EXPO if view else 1.0)
    ar = ((1 - nov) ** EXPO if view else 1.0) * nol ** EXPO
    return (1 + (rf - 1) * af) * (1 + (rr - 1) * ar)


def profile(nol, nov, rhos, view, norm, colour=SKIN):
    return c1(nol, nov, rhos, view) * luma_gain(nol, colour=colour, norm=norm)


def table(name, nov, rhos, view, rungs):
    print("\n%s (normalised at the lit cheek; vanilla == 1.000)" % name)
    print("  NoL   " + "".join("%-11s" % r[0] for r in rungs))
    for nol in (0.0, 0.05, 0.10, 0.175, 0.25, 0.35, 0.5, 0.75, 1.0):
        row = "  %-6.3f" % nol
        for _, norm, rf in rungs:
            rh = (rf, rhos[1]) if rf else rhos
            base = profile(1.0, nov, rh, view, norm)
            row += "%-11.3f" % (profile(nol, nov, rh, view, norm) / base)
        print(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nov', type=float, default=0.7,
                    help='view cosine for the direct path (default 0.7)')
    a = ap.parse_args()
    rungs = [("standing", 0.0, None), ("-lumn", 1.0, None), ("-deep", 1.0, 1.0)]

    print("the bleed's own luminance gain, k=1 (what -lumn removes)")
    print("  NoL      w      grey      skin     add as %% of FULL-LIT diffuse")
    for nol in (0.0, 0.05, 0.10, 0.117, 0.175, 0.25, 0.35):
        g = luma_gain(nol, colour=(1, 1, 1)) - 1
        s = luma_gain(nol) - 1
        print("  %-8.3f %-6.3f %+-9.1f%% %+-8.1f%% %+.2f%%"
              % (nol, w_of(nol), 100 * g, 100 * s, 100 * s * nol))

    table("DIRECT path (compute resolvers, NoV=%.2f)" % a.nov,
          a.nov, C1_DIRECT, True, rungs)
    table("BOUNCE path (ReSTIR-GI ST pair, no view vector)",
          a.nov, C1_BOUNCE, False, rungs)

    print("\nresidual of the hold under a TINTED light (the basis is the")
    print("albedo triple; the light/radiance colour multiplies downstream)")
    print("  light            luminance at the band floor, -lumn")
    for nm, L in (("white   (1,1,1)", (1.0, 1.0, 1.0)),
                  ("tungsten(1,.75,.5)", (1.0, 0.75, 0.5)),
                  ("sodium  (1,.6,.25)", (1.0, 0.6, 0.25)),
                  ("cool    (.5,.75,1)", (0.5, 0.75, 1.0))):
        T = tuple(a_ * l for a_, l in zip(SKIN, L))
        m = bleed(0.0, colour=SKIN, norm=1.0)      # s from the albedo basis
        y0 = sum(wi * ti for wi, ti in zip(W709, T))
        y1 = sum(wi * ti * mi for wi, ti, mi in zip(W709, T, m))
        print("  %-18s %+.2f%%   (unheld: %+.2f%%)"
              % (nm, 100 * (y1 / y0 - 1),
                 100 * (sum(wi * ti * mi for wi, ti, mi
                            in zip(W709, T, bleed(0.0, colour=SKIN))) / y0 - 1)))


if __name__ == '__main__':
    main()
