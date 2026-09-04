#!/usr/bin/env python3
"""oilhi -- 72's coat re-tuned now that 117's `cons` takes the energy out.

handoff/118.

72 shipped a Schlick reshape on the skin-gated Fresnel:

    F' = min( f0 + (1 - f0) * g * (1 - VoH)^p , 1 )        p = 5r, g = spec_gain
    r  = 2(1 - n_s)                                        amp = g * sat(2 - r)

and `oilh` (74, the half-strength read the user asked for) set n_s = 0.55,
spec_gain = 1.0 -> p = 4.5, amp = sat(1.1) * 1.0 = 1.0.  The `sat(2-r)` term
is CLAMPED TO 1 for every n_s >= 0.5, i.e. for the whole oil direction, so it
has never moved anything: the shipped coat is plain Schlick with the exponent
slackened from 5 to 4.5, and `spec_gain` alone is the amplitude.

That coat was tuned against a BRDF where the reflected energy was a pure ADD:
the diffuse lobe kept all of its light and the coat's share was piled on top.
117's `cons` now multiplies the diffuse by (1 - F) per channel, so the same
F is simultaneously louder in the highlight and darker in the body.  The coat
is therefore weaker than it was tuned to be, and this is the correction.

Two independent levers, one rung each so a verdict can be attributed:

    oilhi     p 4.5 -> 4.0     the ladder's own next step (n_s 0.55 -> 0.60).
                              Widens the grazing rim; identity at facing.
    oilhi-g   g 1.0 -> 1.25    lifts F proportionally at every angle off
                              normal; the NMin at 1 still caps it.
    oilhi2    both             the louder candidate, not a diagnostic.

Neither lever can move a pixel whose VoH is 1: (1-VoH)^p = 0 there for every
p > 0, so F = f0 exactly, on every rung.  Facing skin is byte-identical in
its shading value and the A/B is purely a grazing-band read.

The THIRD oil lever, the GGX roughness ceiling alpha_max = 0.2025, is NOT
touched here -- it is the dominant lever (patch_compute_skin.sh), it lives in
a different pass, and moving it at the same time would make the rung two
variables.  It is also now entangled with 117's `rough`, which scales alpha
UP by (1 + 0.5*cav) AFTER the cap, so a pore can already exceed the ceiling.
See handoff/118 sec 6.
"""
import struct, sys

F32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]

EPS = 1e-4
P_SHIP, G_SHIP = 4.5, 1.0          # the shipped default's two constants
RUNGS = {                          # name -> (p, g)
    'oil-ctl':  (4.5, 1.0),
    'oilhi':    (4.0, 1.0),
    'oilhi-g':  (4.5, 1.25),
    'oilhi2':   (4.0, 1.25),
}
F0_SKIN = 0.04                     # dielectric skin; the shipped f0 is authored


def ns_to_p(n_s):
    """patch_compute_skin's own mapping, reproduced so the rungs stay on the
    shipped ladder rather than inventing a parallel one."""
    r = 2.0 * (1.0 - n_s)
    return 5.0 * r, r


def amp(g, r):
    """g * saturate(2 - r) -- the clamp is why sat() has never mattered."""
    return F32(g * min(max(2.0 - r, 0.0), 1.0))


def fresnel(voh, f0=F0_SKIN, p=P_SHIP, g=G_SHIP):
    b = F32(max(F32(1.0 - voh), EPS))
    pw = F32(b ** p)
    return F32(min(F32(f0 + F32(F32(F32(1.0 - f0) * pw) * g)), 1.0))


def diffuse_mult(voh, f0=F0_SKIN, p=P_SHIP, g=G_SHIP):
    """117's `cons`: what the diffuse keeps once the coat has taken its share."""
    return F32(1.0 - fresnel(voh, f0, p, g))


def check():
    ok, bad = 0, []

    def T(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            bad.append(name)

    # 1. the shipped rung IS the shipped constants
    p, r = ns_to_p(0.55)
    T('n_s=0.55 -> p=4.5', abs(p - 4.5) < 1e-6)
    T('n_s=0.60 -> p=4.0', abs(ns_to_p(0.60)[0] - 4.0) < 1e-6)
    # 2. sat(2-r) is inert over the whole oil direction
    T('sat(2-r)==1 for every n_s in [0.5,1]',
      all(abs(amp(1.0, ns_to_p(n / 100.0)[1]) - 1.0) < 1e-9
          for n in range(50, 101)))
    T('the shipped amplitude is exactly 1.0', abs(amp(G_SHIP, r) - 1.0) < 1e-9)
    # 3. facing skin cannot move on any rung
    T('F(VoH=1) == f0 on every rung',
      all(abs(fresnel(1.0, F0_SKIN, *v) - F0_SKIN) < 1e-7
          for v in RUNGS.values()))
    # 4. the control is the default, exactly
    T('oil-ctl == shipped', RUNGS['oil-ctl'] == (P_SHIP, G_SHIP))
    # 5. F is bounded and never darkens the highlight
    grid = [i / 200.0 for i in range(201)]
    T('F in [f0, 1] everywhere on every rung',
      all(F0_SKIN - 1e-6 <= fresnel(v, F0_SKIN, *k) <= 1.0 + 1e-6
          for k in RUNGS.values() for v in grid))
    T('every rung is >= the shipped coat',
      all(fresnel(v, F0_SKIN, *k) >= fresnel(v) - 1e-7
          for k in RUNGS.values() for v in grid))
    # 6. F is monotone decreasing in VoH (a rim, not a band)
    for nm, k in RUNGS.items():
        s = [fresnel(v, F0_SKIN, *k) for v in grid]
        T('%s monotone in VoH' % nm,
          all(s[i] >= s[i + 1] - 1e-7 for i in range(len(s) - 1)))
    # 7. the clamp actually catches a pushed gain
    T('g=2 is clamped at grazing', abs(fresnel(0.0, F0_SKIN, 4.5, 2.0) - 1.0) < 1e-6)
    # 8. cons pairs exactly: what the coat takes, the diffuse loses
    for nm, k in RUNGS.items():
        T('%s cons pairs' % nm,
          all(abs(diffuse_mult(v, F0_SKIN, *k)
                  + fresnel(v, F0_SKIN, *k) - 1.0) < 1e-6 for v in grid))
    # 9. the magnitudes the two levers are chosen for: comparable at 60 deg
    b = fresnel(0.5)
    e = fresnel(0.5, F0_SKIN, *RUNGS['oilhi'])
    gg = fresnel(0.5, F0_SKIN, *RUNGS['oilhi-g'])
    T('oilhi lifts 60deg F by 15-30%', 1.15 < e / b < 1.30)
    T('oilhi-g lifts 60deg F by 5-20%', 1.05 < gg / b < 1.20)
    T('the two levers are within 1.5x of each other',
      max(e, gg) / min(e, gg) < 1.5)
    # 10. and the body darkening stays small enough to be a look, not a bug
    # 11.5% at 60 deg on the loudest rung.  Stated as a range, not a
    # ceiling: `cons` is SUPPOSED to bite here, and a rung that removed
    # nothing would be the failure.
    d = diffuse_mult(0.5, F0_SKIN, *RUNGS['oilhi2'])
    T('oilhi2 removes 5-15%% of the diffuse at 60 deg (%.1f%%)' % (100 * (1 - d)),
      0.85 < d < 0.95)

    for nm in bad:
        print('FAIL  %s' % nm)
    print('%d checks, %d failed' % (ok + len(bad), len(bad)))
    return 1 if bad else 0


def table():
    hdr = ['VoH', 'deg'] + list(RUNGS)
    print('  '.join('%9s' % h for h in hdr))
    for voh in (1.0, 0.9, 0.75, 0.5, 0.2588, 0.1):
        import math
        row = ['%9.4f' % voh, '%9.1f' % math.degrees(math.acos(voh))]
        row += ['%9.4f' % fresnel(voh, F0_SKIN, *RUNGS[n]) for n in RUNGS]
        print('  '.join(row))


if __name__ == '__main__':
    if '--table' in sys.argv:
        table()
    sys.exit(check())
