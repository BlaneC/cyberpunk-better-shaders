# sentinel-b (rung B) -- 2026-08-31T00:05:39-05:00 -- CYAN ON GEOMETRY. G-U5 PASSES.

Serve verified: 12 rgs_reference_main + 4 rgs_restirgi + 77 dxil HITs,
**0 ms_empty_main** (correct for B -- none patched), 0 ser_reject, manifest
echo `sentinel-b ... ref=12(10 sentinel-clone + 2 pass-through)`.
Settings PINNED and proven by ab_settings.py (last written 4277s before the
first capture): PT on, RR off, DLSS Balanced, RT Psycho, 1440p.

Capture: S1.png (= CYAN.png as shot).

## The measurement

Paint colour is (0,10,10): R crushed, G == B. Natural blue sky is B > G > R.
Those two are separable, and they separate cleanly.

    region                RGB                    R/(GB avg)   painted?
    face, lit cheek       [ 36.8 159.6 161.4]      0.229      YES (G==B)
    face, shadow side     [ 39.8 176.3 174.8]      0.227      YES
    bush                  [ 61.6 169.0 162.8]      0.371      YES
    distant city          [ 51.1 112.6 113.0]      0.453      YES
    jacket                [ 90.4 166.0 166.1]      0.544      YES
    bare tree             [122.4 178.3 181.3]      0.681      partial
    sky (clear, upper L)  [ 87.9 135.8 157.8]      0.599      NO -- B>G by 22, blue signature intact
    cloud                 [167.5 187.8 186.7]      0.894      NO
    ground dirt (fg L)    [139.0 142.1 126.1]      1.036      NO
    ground dirt (fg R)    [152.0 150.4 133.4]      1.072      NO
    distant hills         [151.9 144.6 133.2]      1.094      NO

## Why this is a pass and not the disqualifying outcome

The predicate is `word0 != ARM`. word0 is armed to 0x5EA71E51 in the entry
block, which dominates everything. Paint therefore IMPLIES the payload was
written, which implies the injected static OpTraceRayKHR executed and the
pipeline's own unpatched CHS wrote to it.

55 sec 4 pre-registered "cyan everywhere incl. sky" as a readback defect /
payload aliasing => treat as build bug. **The sky is not painted.** Sky pixels
= primary ray misses = the injected clone (all operands verbatim) also misses
= rung B's unpatched ms_empty_main writes nothing = word0 stays ARM = no paint.
The internal control fired correctly. Aliasing is ruled out by observation,
not by argument.

## Consequences

1. **G-U5 PASSES.** Traced thickness (51 sec 7 step 3) is buildable. Skin is
   the most strongly painted surface in the frame (R/(GB) = 0.227, the lowest
   sampled) -- the exact sites the ear-glow term needs.
2. **Rung A's failure is localised to the miss path**, not the trace: A used
   cullMask 0 + a patched ms_empty_main handshake; B uses cullMask 255 + the
   unpatched CHS and works. Per 55 sec 4 this needs no follow-up unless a
   miss-WRITTEN term is ever required. Transmission needs CHS->payload (hit
   distance), which B just proved.
3. **GOTCHAS' flat claim "a second static OpTraceRayKHR does not execute" is
   OVERTURNED.** It was one sample (26 sec 7d, `sctrl`) in the shadow pipeline
   family with hand-picked SBT/payload indices. In the reference family, with
   every operand cloned by id from a live trace, a second static site executes.
   H3 (wrong SBT/params) was the real cause there; H2 (driver/vkd3d forbids
   multiple static sites) is DEAD.

## Open, and NOT gating the feature

Terrain (ground + distant hills) is unpainted while every other surface is
painted. Candidates: terrain is shaded by one of the 2 unpainted pass-through
permutations (40c6faab52a13874 / ab7f1822eeb0331b, the atomic pair), or its
radiance write is among the sites the patcher skipped (constant-zero
early-outs, scalar hit-distance writes). Cheap to answer offline from the
rgs.report.json skip lists + the rt_pipeline permutation list. Irrelevant to
ear-glow, which is class-1 skin only.
