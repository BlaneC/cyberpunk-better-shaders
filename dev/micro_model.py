#!/usr/bin/env python3
"""The four micro-surface halves of handoff/117, in float32, exactly as the
patcher emits them.  `python3 dev/micro_model.py` runs the self-checks.

All four ride the SAME albedo height field 115 already built (h = H * L), so
nothing here needs a fetch the bump block does not already make.  115 read the
field's GRADIENT as a tilt; this reads its CURVATURE as a cavity, and then
spends that cavity three ways.

    lap   = 0.25*(L(x+1)+L(x-1)+L(y+1)+L(y-1)) - L0        [luma]  (5 taps)
    lap'  = lap * (1 - smoothstep(C0, C1, |lap|))          the SAME edge-kill
                                                           idea as 115 sec 2:
                                                           a lip line is not
                                                           a pore
    cav   = clamp(lap' / CREF, 0, 1)                       0 = flat, 1 = a
                                                           reference pore
    cav  *= (class == 1) && 109's silhouette guard

1. OCCLUSION (`occ`)          diffuse *= 1 - KOCC*cav
   A pit is shadowed by its own rim.  115 tilts the normal so a pore's two
   rims part in brightness; nothing yet DARKENS the pit itself.  The shipped
   micro-shadow (44 sec 3.4) is a 0.72%-at-most albedo term and is not this.

2. ROUGHNESS (`rough`)        alpha_skin *= 1 + KRGH*cav          (115 sec 6)
   Applied to the SKIN ARM of the shipped `OpSelect(class==1, ...)` only, so
   108/cap's clamp keeps its meaning and no other material moves.  This is
   what turns one oil highlight into skin: the pores scatter its edge.

3. TERMINATOR (`term`)        diffuse *= 1 + w - w^2,
                              w = clamp(NoL(N') / max(NoL(N), eps), 0, 1)
   Chiang et al. 2019.  Perturbing a shading normal puts NoL(N') below
   NoL(N) on the far side of every pore, and the published fix replaces the
   hard band with G(w) = -w^3 + w^2 + w.  Since the lobe already carries a
   factor NoL(N') = w * NoL(N), the multiplier needed is G(w)/w, which is
   1 at w = 1, 1.25 at w = 0.5, and never darkens.  This is the half 115 made
   load-bearing: it is the fix for the artifact 115 itself introduces.

4. SPECULAR OCCLUSION (`gtso`)  spec *= saturate(pow(NoV+ao, e) - 1 + ao),
                                e = exp2(-16*a2 - 1),  ao = 1 - KOCC*cav
   Jimenez et al. 2016.  38 A5 was parked as "needs a bent normal"; this form
   needs only AO, NoV and alpha, all three of which are now in the block.

5. LAYERING (`cons`)          diffuse *= 1 - Favg,  Favg = (F0+F1+F2)/3
   72's oil layer is a pure ADD: the coat's Fresnel multiplies the specular
   lobe and NOTHING removes that energy from the diffuse beneath it.  That is
   the textbook "wet plastic" failure and the reason the oil cannot be pushed.
   One multiply, physically mandated (OpenPBR sec "coat", Kulla-Conty).
"""
import numpy as np

f32 = np.float32
CREF = f32(0.02)      # luma curvature of a reference pore (115's dL step)
C0, C1 = f32(0.05), f32(0.12)      # the edge-kill band, verbatim 115 sec 2
KOCC = f32(0.35)      # deepest pore keeps 65% of its diffuse
KRGH = f32(0.50)      # deepest pore is 1.5x rougher
EPS = f32(1e-4)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), f32(0), f32(1)).astype(f32)
    return (t * t * (f32(3) - f32(2) * t)).astype(f32)


def cavity(l0, lxp, lxm, lyp, lym, band=True, cref=CREF, c0=C0, c1=C1):
    lap = (f32(0.25) * (f32(lxp) + f32(lxm) + f32(lyp) + f32(lym)) - f32(l0))
    lap = f32(lap)
    if band:
        lap = f32(lap * (f32(1) - smoothstep(c0, c1, abs(lap))))
    return f32(np.clip(lap / cref, f32(0), f32(1)))


def occ(cav, k=KOCC):
    return f32(f32(1) - f32(k) * f32(cav))


def rough(alpha, cav, k=KRGH):
    return f32(f32(alpha) * (f32(1) + f32(k) * f32(cav)))


def term(nol_bumped, nol_raw, eps=EPS):
    w = f32(np.clip(f32(nol_bumped) / max(f32(nol_raw), eps), f32(0), f32(1)))
    return f32(f32(1) + w - w * w)


def gtso(nov, ao, a2):
    e = f32(np.exp2(f32(-16) * f32(a2) - f32(1)))
    return f32(np.clip(f32(np.power(max(f32(nov) + f32(ao), f32(0)), e))
                       - f32(1) + f32(ao), f32(0), f32(1)))


def cons(f0, f1, f2):
    return f32(f32(1) - (f32(f0) + f32(f1) + f32(f2)) / f32(3))


def _checks():
    ok = []

    def chk(name, cond):
        ok.append((name, bool(cond)))

    # 1. a flat patch is the identity in every term
    c = cavity(0.3, 0.3, 0.3, 0.3, 0.3)
    chk('flat patch -> cav 0', c == 0)
    chk('cav 0 -> occ 1', occ(c) == 1)
    chk('cav 0 -> rough identity', rough(0.2025, c) == f32(0.2025))
    # 2. a pit (centre darker than its ring) is a positive cavity
    c = cavity(0.28, 0.30, 0.30, 0.30, 0.30)
    chk('a 0.02 pit -> cav 1', abs(c - 1) < 1e-6)
    chk('a pit darkens diffuse', occ(c) == f32(1) - KOCC)
    chk('a pit roughens skin', abs(rough(0.2, c) - f32(0.3)) < 1e-6)
    # 3. a bump (centre brighter) does NOT brighten: the term is clamped at 0
    chk('a mound -> cav 0', cavity(0.32, 0.30, 0.30, 0.30, 0.30) == 0)
    # 4. an ALBEDO EDGE, not a pore: killed by the band
    chk('a 0.3-luma edge is killed',
        cavity(0.0, 0.3, 0.3, 0.3, 0.3) < 0.05)
    # 5. the terminator factor: 1 at w=1, 1.25 at w=0.5, never < 1
    chk('term identity at w=1', abs(term(0.5, 0.5) - 1) < 1e-6)
    chk('term 1.25 at w=0.5', abs(term(0.25, 0.5) - 1.25) < 1e-6)
    chk('term never darkens',
        all(term(w * 0.8, 0.8) >= 1 - 1e-6 for w in np.linspace(0, 1, 33)))
    chk('term clamped above w=1', abs(term(0.9, 0.5) - 1) < 1e-6)
    # 6. GTSO: no occlusion -> no specular occlusion, at any roughness
    chk('gtso identity at ao=1',
        all(abs(gtso(nv, 1.0, a2) - 1) < 1e-5
            for nv in (0.05, 0.3, 0.9) for a2 in (0.0001, 0.04, 0.2)))
    chk('gtso occludes a rough grazing pixel',
        gtso(0.1, occ(1.0), 0.2) < 0.65)
    chk('gtso occludes a mirror less than a rough surface at the same AO',
        gtso(0.5, 0.65, 0.0001) > gtso(0.5, 0.65, 0.25))
    # 7. layering: a black coat is the identity, a full coat kills the diffuse
    chk('cons identity at F=0', cons(0, 0, 0) == 1)
    chk('cons kills diffuse at F=1', cons(1, 1, 1) == 0)
    chk('cons at the oil F0 (0.04) is a 4% removal',
        abs(cons(0.04, 0.04, 0.04) - 0.96) < 1e-6)
    return ok


if __name__ == '__main__':
    bad = 0
    for name, good in _checks():
        print('%-4s %s' % ('ok' if good else 'FAIL', name))
        bad += not good
    print('%d assertion(s) failed' % bad)
    raise SystemExit(1 if bad else 0)
