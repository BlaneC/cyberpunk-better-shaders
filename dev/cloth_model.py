#!/usr/bin/env python3
"""Offline model of the CLOTH sheen rung's maths (handoff/80, 81).

Same method and the same discipline as dev/fuzz_model.py (72 §3, 73 §2): it
evaluates exactly what the spliced SPIR-V evaluates, in the same order, with
the same constants, and it judges the lobe against the LOCAL DIFFUSE rather
than against the specular it is spliced into -- "is this visible" is a
question about the diffuse.

What differs from the peach fuzz, and why the peach calibration does not
transfer unchanged:

  * f0 is 0.04 (a dielectric), not skin's 0.028 -- the module's own Fresnel,
    which multiplies the lobe downstream of the splice, sits 1.43x higher
    across the whole front-lit sheen band.
  * there is no alpha_scale and no oil: those are class-1 edits. Cloth runs
    at the authored roughness, which for fabric is 0.5-0.9, so the base GGX
    lobe is much flatter and the sheen is a bigger share of it.
  * a ROUGHNESS RAMP gates the lobe on the site's own alpha, so smooth
    dielectrics (glass, clearcoat, polished plastic) get nothing and the
    lobe is only at full strength on genuinely rough ones.
  * a DIFFUSE DAMP rides with it: f_d *= 1 - k*E1*wr, where E1 is the
    cosine-weighted directional albedo of the capped, weighted lobe at k=1,
    computed here (23 §4's ship requirement, 22 §4's "constant-factor
    approximation" -- stated as a known inaccuracy, and it is §4 below).

    ./dev/cloth_model.py                 # the shipped rung's tables
    ./dev/cloth_model.py --k 1.0         # the -clothhi rung
    ./dev/cloth_model.py --scan          # + hemisphere summary and E1
    ./dev/cloth_model.py --calibrate     # what k puts grazing where we want

Geometry is fuzz_model.py's: N=+z, view azimuth 0, phi = the light's azimuth.
phi=0 is the sheen band (light on the viewer's side); phi=180 is the mirror
direction, where D_charlie is exactly 0 by construction.
"""
import argparse, math

F0_DIELECTRIC = 0.04     # lerp(0.04, albedo, metallic) with metallic = 0
ALBEDO = 0.25            # the reference diffuse the sheen is judged against
A_CLOTH = 0.25           # Charlie lobe roughness
CAP = 0.5                # cloth_max: ceiling on D_charlie*V_neubelt
DEFRES = 1.0             # beta: cancel the module's Schlick ramp on the lobe
A0, A1 = 0.10, 0.30      # roughness ramp, in ALPHA (= authored roughness^2)


def norm(v):
    l = math.sqrt(sum(x * x for x in v))
    return [x / l for x in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def ramp(rough, a0=A0, a1=A1):
    """wr = sat((alpha - a0)/(a1 - a0)), alpha = rough^2.

    Emitted at the site from the site's OWN alpha -- which on a gate-true
    (non-skin) pixel is exactly the authored roughness squared, because the
    only thing that reshapes alpha in these modules is the class-1-gated
    skin cap.
    """
    return min(max((rough * rough - a0) / (a1 - a0), 0.0), 1.0)


def evaluate(rough, tv, tl, phi, k=0.5, a=A_CLOTH, cap=CAP, defres=DEFRES,
             a0=A0, a1=A1, albedo=ALBEDO):
    """One (view, light) pair, angles in radians. None below either horizon."""
    alpha = rough ** 2
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
    p5 = (1 - VoH) ** 5
    w = 1.0 - defres * p5
    wr = ramp(rough, a0, a1)
    F = F0_DIELECTRIC + (1 - F0_DIELECTRIC) * p5
    add = k * min(raw, cap) * w * wr * NoL
    return dict(base=D * Vis * NoL, raw=raw, NoL=NoL, NoV=NoV, NoH=NoH, VoH=VoH,
                w=w, wr=wr, p5=p5, F=F, add=add, lit=add * F,
                diffuse=albedo / math.pi * NoL)


def E1(rough, nv_deg, a=A_CLOTH, cap=CAP, defres=DEFRES, a0=A0, a1=A1, n=64):
    """Directional albedo of the LIT added term at k=1: int f_sheen*F*NoL dw.

    This is what the layered form f = f_sheen + (1 - E)*(f_d + f_s) wants for
    the damp. The integrand is the term the SPIR-V actually adds (capped,
    ramped, Schlick-cancelled) times the module's own Fresnel, because that
    product is what leaves the surface.
    """
    tv = math.radians(nv_deg)
    tot = 0.0
    for i in range(n):
        tl = (i + 0.5) / n * (math.pi / 2)
        for j in range(2 * n):
            ph = (j + 0.5) / (2 * n) * 2 * math.pi
            r = evaluate(rough, tv, tl, ph, k=1.0, a=a, cap=cap, defres=defres,
                         a0=a0, a1=a1)
            if not r:
                continue
            # add already carries NoL; dw = sin(tl) dtl dph
            tot += r['add'] * r['F'] * math.sin(tl)
    return tot * (math.pi / 2 / n) * (2 * math.pi / (2 * n))


def E1_hat(rough, **kw):
    """Cosine-weighted average of E1 over view directions -- the ONE constant
    the shader bakes (it cannot afford a NoV-dependent LUT)."""
    num = den = 0.0
    for d in range(2, 90, 4):
        t = math.radians(d)
        wgt = math.cos(t) * math.sin(t)
        num += E1(rough, d, n=24, **kw) * wgt
        den += wgt
    return num / den


VIEWS = (0, 30, 45, 60, 80, 88)
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
    ap.add_argument('--calibrate', action='store_true')
    ap.add_argument('--rough', type=float, default=0.7,
                    help='authored roughness (fabric: 0.5-0.9)')
    ap.add_argument('--k', type=float, default=0.5)
    ap.add_argument('--a', type=float, default=A_CLOTH)
    ap.add_argument('--cap', type=float, default=CAP)
    ap.add_argument('--defres', type=float, default=DEFRES)
    ap.add_argument('--albedo', type=float, default=ALBEDO)
    o = ap.parse_args()
    R = o.rough
    K = dict(k=o.k, a=o.a, cap=o.cap, defres=o.defres, albedo=o.albedo)
    print("authored roughness %.2f (alpha %.3f, ramp wr=%.2f), k_cloth %.2f, "
          "a_cloth %.2f, cloth_max %.2f, defres %.2f, f0 %.3f\n"
          % (R, R * R, ramp(R, A0, A1), o.k, o.a, o.cap, o.defres, F0_DIELECTRIC))

    print("=== 1. the roughness ramp: which materials the gate lets through ===\n")
    print("  authored |  alpha  |  wr    | typical material")
    for rr, what in ((0.05, 'glass, polished chrome'), (0.20, 'car clearcoat'),
                     (0.30, 'moulded plastic'), (0.32, 'ramp foot (alpha=0.10)'),
                     (0.40, 'leather, vinyl'), (0.50, 'coated nylon'),
                     (0.55, 'ramp top (alpha=0.30)'), (0.70, 'cotton, denim'),
                     (0.85, 'wool, concrete')):
        print("    %.2f   |  %.3f  |  %.2f  | %s" % (rr, rr * rr, ramp(rr), what))
    print()

    print("=== 2. is it VISIBLE: (lobe * ramp * Fresnel) as a %% of local diffuse ===\n")
    for phi in (0, 180):
        grid("phi=%d" % phi,
             lambda r: " %5.1f%%" % (100 * r['lit'] / r['diffuse']), R, phi=phi, **K)
    print("  Calibration anchors, both from handoff/72 §3 and both measured:")
    print("    the 58 probe (k=8, ungated, no cosine fold) = 316%% of the local")
    print("      diffuse -> the user read it as BLOWN WHITE on screen;")
    print("    the shipped peach fuzz = 5-17%% on a cheek rim -> the user read")
    print("      it as 'incredible ~99%% of the time' (75).")
    print("  So the target band for 'visible, not white' is 10-30%% at grazing.\n")

    print("=== 3. added lobe / the site's own GGX specular ===\n")
    grid("phi=0", lambda r: " %5.2fx" % (r['add'] / r['base']), R, phi=0, **K)

    print("=== 4. the diffuse damp (23 §4's ship requirement) ===\n")
    print("  E1(NoV) = directional albedo of the LIT added term at k=1.")
    print("  The shader bakes ONE constant (no LUT), so the error is the")
    print("  spread of this column -- stated, not hidden.\n")
    print("  view | E1 (k=1) | damp at k=%.2f" % o.k)
    for d in (0, 30, 45, 60, 80):
        e = E1(R, d, a=o.a, cap=o.cap, defres=o.defres, n=32)
        print("  %3d  |  %.4f  |   %.4f" % (d, e, 1 - o.k * e * ramp(R)))
    eh = E1_hat(R, a=o.a, cap=o.cap, defres=o.defres)
    print("\n  E1_hat (cosine-weighted over view) = %.4f" % eh)
    print("  shipped damp at k=%.2f, wr=1: f_d *= %.4f  (%.1f%% of the diffuse)"
          % (o.k, 1 - o.k * eh, 100 * o.k * eh))
    print("  worst per-view error of the constant: %+.2f%% of the diffuse"
          % (100 * o.k * max(abs(E1(R, d, a=o.a, cap=o.cap, defres=o.defres, n=32) - eh)
                             for d in (0, 30, 45, 60, 80))))
    print()

    if o.calibrate:
        print("=== 5. calibration: k vs the grazing / head-on response ===\n")
        print("   k   | head-on(v0,L50) | 45deg(v45,L70) | grazing(v80,L70) | "
              "silhouette(v88,L85) | damp")
        for k in (0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0):
            kk = dict(K); kk['k'] = k
            def pc(tvd, tld):
                r = evaluate(R, math.radians(tvd), math.radians(tld), 0.0, **kk)
                return 100 * r['lit'] / r['diffuse'] if r else float('nan')
            print("  %.2f |     %6.2f%%      |    %6.2f%%     |     %6.2f%%       |"
                  "      %6.2f%%        | %.3f"
                  % (k, pc(0, 50), pc(45, 70), pc(80, 70), pc(88, 85),
                     1 - k * E1_hat(R, a=o.a, cap=o.cap, defres=o.defres)))
        print()

    if o.scan:
        vals, worst = [], (0.0, None)
        for tvd in range(0, 90, 2):
            for tld in range(0, 90, 2):
                for phid in range(0, 360, 10):
                    r = evaluate(R, math.radians(tvd), math.radians(tld),
                                 math.radians(phid), **K)
                    if not r or r['base'] <= 0:
                        continue
                    v = 100 * r['lit'] / r['diffuse']
                    vals.append(v)
                    if v > worst[0]:
                        worst = (v, (tvd, tld, phid, r))
        vals.sort()
        tv, tl, ph, r = worst[1]
        print("hemisphere, %% of the local diffuse: median %.2f%%, p90 %.1f%%, "
              "max %.1f%% (view %d, light %d, phi %d; absolute %.4f vs diffuse "
              "%.4f)" % (vals[len(vals) // 2], vals[int(len(vals) * 0.9)],
                         worst[0], tv, tl, ph, r['lit'], r['diffuse']))
        for rr in (0.35, 0.5, 0.7, 0.9):
            vv = []
            for tvd in range(0, 90, 4):
                for tld in range(0, 90, 4):
                    for phid in range(0, 360, 20):
                        r = evaluate(rr, math.radians(tvd), math.radians(tld),
                                     math.radians(phid), **K)
                        if r and r['base'] > 0:
                            vv.append(100 * r['lit'] / r['diffuse'])
            vv.sort()
            print("  authored roughness %.2f (wr %.2f): median %.2f%%, max %.1f%%"
                  % (rr, ramp(rr), vv[len(vv) // 2], vv[-1]))


if __name__ == '__main__':
    main()
