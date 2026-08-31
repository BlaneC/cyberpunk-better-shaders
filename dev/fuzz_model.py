#!/usr/bin/env python3
"""Offline model of the peach-fuzz / oil rung's specular maths (handoff/72, 73).

Reproduces every number quoted in 72 §1-§4 and 73 §2-§3. It evaluates exactly what the
spliced SPIR-V evaluates, in the same order, with the same constants:

    alpha = roughness^2 * alpha_scale        (min'd with alpha_max: the OIL)
    a2    = alpha^2
    base  = D_ggx(a2, NoH) * V_smith(a2, NoL, NoV) * NoL     <- the site's own
    raw   = D_charlie(a, NoH) * V_neubelt(NoL, NoV)
    w     = 1 - defres*(1-VoH)^5             <- 73: cancels the Schlick ramp
    add   = k * min(raw,cap) * NoL * w  spec' = spec + add    <- --peach-mode add
    mul   = 1 + k * min(raw, cap)       spec' = spec * mul    <- --peach-mode mul

and then applies the module's own Fresnel, which multiplies BOTH terms
downstream of the splice:

    F  = f0 + (1-f0) * (1-VoH)^5                             vanilla Schlick
    F' = f0 + g*saturate(2-r) * (1-f0) * (1-VoH)^(5r), r=2(1-n_s)   the OIL

The diffuse term at the same pixel (albedo/pi * NoL) is printed beside them,
because "is this visible" is a question about the fuzz against the DIFFUSE,
not against the specular it is spliced into.

    ./dev/fuzz_model.py               # the tables in 71 §2-§4
    ./dev/fuzz_model.py --scan        # + hemisphere summary
    ./dev/fuzz_model.py --k 2.0       # what a louder rung would do
    ./dev/fuzz_model.py --scan --defres 1.0 --cap 0.5    # what SHIPS (73)
    ./dev/fuzz_model.py --scan --defres 0.0 --cap 1.0    # the 72-era rung
                                                          the user called
                                                          "too blown out"

Geometry: N = +z, view azimuth 0. `phi` is the light's azimuth --

  phi=0    light on the VIEWER's side: both vectors near-tangent, the half
           vector near-tangent, NoH small. THE SHEEN BAND. Note VoH ~ 1 here
           (H sits between two nearly-parallel vectors), so the module's own
           Fresnel is at its FLOOR, f0 ~ 0.028, over this whole band -- the
           fuzz is attenuated ~36x by a term that has nothing to do with it.
           That is what `k` has to pay for, and why k of order 1 is the
           right magnitude at this splice point rather than 0.1.

  phi=180  light on the far side. tl=tv is then the mirror direction, NoH=1,
           where the GGX highlight lives and the Charlie lobe is exactly 0 --
           the fuzz cannot brighten a highlight, by construction.
"""
import argparse, math

F0_SKIN = 0.028          # skin f0 (IOR ~1.4); the class-1 gate keeps us here
ALBEDO = 0.25            # the reference diffuse the fuzz is judged against


def norm(v):
    l = math.sqrt(sum(x * x for x in v))
    return [x / l for x in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def evaluate(rough, tv, tl, phi, k=1.0, a=0.35, cap=1.0,
             ascale=0.7, amax=None, n_s=None, spec_gain=1.0, defres=0.0):
    """One (view, light) pair, angles in radians. None below either horizon."""
    alpha = (rough ** 2) * ascale
    if amax:
        alpha = min(alpha, amax)
    a2 = alpha * alpha
    N = [0.0, 0.0, 1.0]
    V = [math.sin(tv), 0.0, math.cos(tv)]
    L = [math.sin(tl) * math.cos(phi), math.sin(tl) * math.sin(phi), math.cos(tl)]
    H = norm([V[i] + L[i] for i in range(3)])
    NoV, NoL, NoH, VoH = dot(N, V), dot(N, L), dot(N, H), dot(V, H)
    if NoL <= 1e-4 or NoV <= 1e-4:
        return None
    D = a2 / (math.pi * ((NoH * NoH * (a2 - 1) + 1) ** 2))
    Vis = 0.5 / (NoL * math.sqrt(NoV * NoV * (1 - a2) + a2)
                 + NoV * math.sqrt(NoL * NoL * (1 - a2) + a2))
    raw = ((2 + 1 / a) * (max(1 - NoH * NoH, 0.0) ** (1 / (2 * a))) / (2 * math.pi)
           / (4 * (NoL + NoV - NoL * NoV)))
    if n_s is None:
        F = F0_SKIN + (1 - F0_SKIN) * ((1 - VoH) ** 5)
    else:
        r = 2.0 * (1.0 - n_s)
        F = min(F0_SKIN + spec_gain * min(max(2 - r, 0.0), 1.0)
                * (1 - F0_SKIN) * ((1 - VoH) ** (5 * r)), 1.0)
    # the TARGETED weight: w = 1 - beta*(1-VoH)^5, emitted at the splice from
    # the site's own cosines via the exact identity VoH = (NoL+NoV)/(2*NoH).
    p5 = (1 - VoH) ** 5
    w = 1.0 - defres * p5
    return dict(base=D * Vis * NoL, raw=raw, NoL=NoL, NoV=NoV, NoH=NoH, VoH=VoH,
                w=w, p5=p5,
                add=k * min(raw, cap) * NoL * w, mul=1 + k * min(raw, cap), F=F,
                diffuse=ALBEDO / math.pi * NoL)


VIEWS = (0, 30, 60, 80, 88)
LIGHTS = (10, 30, 50, 70, 85)


def grid(title, fn, R, **kw):
    print(title)
    print("  view |" + "".join("  L=%-3d" % d for d in LIGHTS))
    for tvd in VIEWS:
        row = "  %3d  |" % tvd
        for tld in LIGHTS:
            r = evaluate(R, math.radians(tvd), math.radians(tld),
                         math.radians(kw.get('phi', 0)),
                         **{x: y for x, y in kw.items() if x != 'phi'})
            row += "   --  " if not r else fn(r)
        print(row)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--rough', type=float, default=0.5)
    ap.add_argument('--k', type=float, default=1.0)
    ap.add_argument('--cap', type=float, default=1.0)
    ap.add_argument('--defres', type=float, default=0.0)
    a = ap.parse_args()
    R, K = a.rough, dict(k=a.k, cap=a.cap, defres=a.defres)
    print("authored roughness %.2f, alpha_scale 0.70, k_peach %.2f, peach_max %.2f, "
          "defres %.2f\n" % (R, a.k, a.cap, a.defres))

    print("=== 1. where the fuzz lands: added lobe / the site's own specular ===\n")
    for phi in (0, 180):
        grid("ADD, phi=%d" % phi, lambda r: " %5.2fx" % (r['add'] / r['base']),
             R, phi=phi, **K)

    print("=== 2. is it VISIBLE: (fuzz * Fresnel) as a %% of the local diffuse ===\n")
    for phi in (0, 180):
        grid("ADD vs diffuse, phi=%d" % phi,
             lambda r: " %5.1f%%" % (100 * r['add'] * r['F'] / r['diffuse']),
             R, phi=phi, **K)
    print("  (the 58-era probe -- k_sheen=8, ungated, no NoL fold -- reaches")
    print("   %.0f%% of the diffuse at view 80/light 70 phi 0, which is the"
          % (100 * min(8 * evaluate(R, math.radians(80), math.radians(70), 0)['raw'], 25.0)
             * evaluate(R, math.radians(80), math.radians(70), 0)['F']
             / evaluate(R, math.radians(80), math.radians(70), 0)['diffuse']))
    print("   \"blown white\" the user read on screen in handoff/58.)\n")

    print("=== 3. the 58-era MULTIPLICATIVE rung: the factor it scaled by ===\n")
    for phi in (0, 180):
        grid("MUL k=0.15 cap=4, phi=%d" % phi, lambda r: " %6.4f" % r['mul'],
             R, phi=phi, k=0.15, cap=4.0)

    print("=== 4. the OIL: what the roughness ceiling and the Fresnel reshape do ===\n")
    print("  mirror band (light elevation = view elevation, phi=180): the highlight")
    print("  full = amax .16 / n_s .60 (73's rung); HALF = amax .2025 / n_s .55")
    print("  (74: the user's on-screen call was ~half the oil)")
    print("  view |    base      oiled    ratio |     F      F_oil   ratio |  half:  base    F")
    for tvd in (10, 30, 45, 60, 75, 85):
        r0 = evaluate(R, math.radians(tvd), math.radians(tvd), math.pi)
        r1 = evaluate(R, math.radians(tvd), math.radians(tvd), math.pi,
                      amax=0.16, n_s=0.60)
        r2 = evaluate(R, math.radians(tvd), math.radians(tvd), math.pi,
                      amax=0.2025, n_s=0.55)
        print("  %3d  | %8.3f %9.3f %7.2fx | %6.3f %7.3f %6.2fx | %6.2fx %+5.1f%%"
              % (tvd, r0['base'], r1['base'], r1['base'] / r0['base'],
                 r0['F'], r1['F'], r1['F'] / r0['F'],
                 r2['base'] / r0['base'], 100 * (r2['F'] / r0['F'] - 1)))
    print("  (the half cap releases authored roughness < 0.538 entirely; at the")
    print("   authored 0.60 ceiling it is 1.55x vs full oil's 2.5x -- the cap is")
    print("   a ceiling, so 'half' means half the REACH and ~60% of the bite,")
    print("   not a uniform 0.5 factor)")
    print()
    print("  off-peak (phi=0, the sheen band): oiled base / base -- a tighter")
    print("  lobe concentrates energy at the mirror, so OFF the mirror it dims")
    print("  view |" + "".join("  L=%-3d" % d for d in LIGHTS))
    for tvd in VIEWS:
        row = "  %3d  |" % tvd
        for tld in LIGHTS:
            r0 = evaluate(R, math.radians(tvd), math.radians(tld), 0.0)
            r1 = evaluate(R, math.radians(tvd), math.radians(tld), 0.0, amax=0.16)
            row += "   --  " if not r0 else " %5.2fx" % (r1['base'] / r0['base'])
        print(row)
    print()
    print("  Fresnel with n_s=0.60 over vanilla Schlick, phi=180 grazing band:")
    for tvd in (60, 75, 85, 88):
        r0 = evaluate(R, math.radians(tvd), math.radians(tvd), math.pi)
        r1 = evaluate(R, math.radians(tvd), math.radians(tvd), math.pi, n_s=0.60)
        print("    view %2d: F %.3f -> %.3f  (%+.1f%%)"
              % (tvd, r0['F'], r1['F'], 100 * (r1['F'] / r0['F'] - 1)))
    print()

    print("=== 5. TARGETED: net Fresnel weight F*(1-beta*p5) vs F alone ===\n")
    print("  VoH is not a free parameter -- it is (NoL+NoV)/(2*NoH), exact, and")
    print("  all three are already at the site. p5=(1-VoH)^5 is the module's own")
    print("  Schlick ramp; multiplying the lobe by (1-beta*p5) cancels it.\n")
    print("   VoH |    p5      F     F*(1-p5)   ratio   (beta=1)")
    for voh in (1.0, 0.95, 0.9, 0.8, 0.7, 0.5, 0.3, 0.1, 0.05):
        p5 = (1 - voh) ** 5
        F = F0_SKIN + (1 - F0_SKIN) * p5
        print("  %.2f | %7.4f %6.3f %9.4f %7.2fx"
              % (voh, p5, F, F * (1 - p5), (F * (1 - p5)) / F))
    print()

    if a.scan:
        for label, kw in (("add", K), ("mul (k=0.15)", dict(k=0.15, cap=4.0))):
            vals, worst = [], (0.0, None)
            for tvd in range(0, 90, 2):
                for tld in range(0, 90, 2):
                    for phid in range(0, 360, 10):
                        r = evaluate(R, math.radians(tvd), math.radians(tld),
                                     math.radians(phid), **kw)
                        if not r or r['base'] <= 0:
                            continue
                        v = 100 * r['add'] * r['F'] / r['diffuse'] if label == 'add' \
                            else 100 * (r['mul'] - 1)
                        vals.append(v)
                        if v > worst[0]:
                            worst = (v, (tvd, tld, phid, r))
            vals.sort()
            tv, tl, ph, r = worst[1]
            print("%s, %% of the local diffuse over the hemisphere: median %.2f%%, "
                  "p90 %.1f%%, max %.1f%% (view %d, light %d, phi %d; "
                  "absolute add*F %.4f vs diffuse %.4f)"
                  % (label, vals[len(vals) // 2], vals[int(len(vals) * 0.9)],
                     worst[0], tv, tl, ph, r['add'] * r['F'], r['diffuse']))


if __name__ == '__main__':
    main()
