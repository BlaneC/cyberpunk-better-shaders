# 88 — The 85 capture was void, and the cone that replaces it: 12/12 coverage, cosine-weighted taps, a distance ramp (2026-09-01)

`85` shipped a skin-gated contact-shadow ray and three rungs were launched
this morning. **One of those captures provably contained no cavity code at
all.** This doc says how that happened, what the launches actually measured,
and what was built in response. **Nothing here is on screen. There is no
verdict until a one-variable A/B at the standing base says so.**

## 0. State, and the settings contract — read before launching

**Built, verified, four rungs parked in `skin.set/`, selector rows added to
`init.lua`. `make install` has NOT run.** The live selection is still
`gi-50b-bleed-oil-sheen-deep-clothhi-cavityhi` — i.e. one of `85`'s rungs, and
on the permutation that actually dispatched it is a **no-op**.

| rung | taps | θ | what it isolates |
|---|---|---|---|
| `…-cone1` | 1 | — | **the floor.** 12/12 coverage + the ramp + tmin 0.1 mm, no cone. This is `85`'s `-cavity` done correctly |
| `…-cone2` | 2 | 12° | **+ the horizon tap.** The cheap rung, and the one that measured as doing all the work (§2c) |
| `…-cone2w` | 2 | 25° | **the angle, isolated.** Added 2026-09-01 to disambiguate a `-cone4w` preference — same cost as `-cone2` |
| `…-cone2all` | 2 | 12° | **the SCOPE axis.** `-cone2` plus the two local-light NEE sites. Its A/B partner is `-cone2`, never `-cone1`. **Shot: area lights far too dim** (§5c) |
| `…-cone2all20/35/50` | 2 | 12° | **`k_local` alone**, 0.20 / 0.35 / 0.50. The sun stays at 0.85 in all three (§5c) |
| `…-cone4` | 4 | 12° | + the two lateral taps |
| `…-cone4w` | 4 | 25° | both axes at once, which is why it cannot be attributed alone |

All nine: k = 0.85 **at the sun**, tmax = 6 mm, ramp on.

⚠ **`make install` is required and it is not free.** Without the selector rows
`init.lua:288` coerces an unknown `skinspec` to `off`, which is a silent
no-op rather than an error. But the working tree also carries **`84`'s
env-bleed rows, `85`'s three rows and the `82` `detail_engine.txt` seed step
in the `Makefile`**, none of which has ever been deployed. `make install` will
carry all of it. Decide that deliberately; do not let it ride along.

Required game settings, stated **before** the launch and never inferred from
the capture afterwards (the `45` rule):

- **PT Overdrive on**, **PT-in-photo-mode ON**. This term exists only in the
  reference path tracer (§5). Without photo-mode PT the rungs are inert.
- **Ray Reconstruction OFF.** Grep the Proton-prefix `UserSettings.json`
  immediately before the launch — `CURRENT.md` records `DLSS_D` moving
  between `true` and `false` unprompted.
- DLSS **Balanced**, RayTracedLighting **Psycho**, **2560×1440**.
- **`RayTracing/SunAngularSize` is now 0.53**, changed at 09:00:58 today. No
  capture from before that is a valid control for one after it (§2.3).
- Photo mode, **camera pinned**, both halves the same frame.

`brdf_params.txt`, the live file with **one line changed**:

    skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-cone2

`ser=class`, `shadowset=full-shadow` and `ptreg=on` are the base rung's own
contract; the MANIFEST carries `src_ser`, `ser_sha=310513f3008cbde4` and
`ptq_sha=55ed4e5c6884ab71` verbatim, so `sync_settings.sh`'s `gi_refuse`
block re-checks and refuses on mismatch exactly as it does for `-clothhi`.

---

## 1. The 09:16 capture is void — the shader that rendered it was unpatched

`85` §11 listed this as an open risk in its own "Unsure" section. It fired on
the first day.

`85` patched **10 of 12** `rgs_reference_main` permutations and shipped
`40c6faab52a13874` and `ab7f1822eeb0331b` byte-verbatim, because its detector
could not find a class test in them. From `~/callisto_swap.jsonl`, per run,
matching each `log_open` to its own `overlay_manifest` and its own
`trace_rays`:

| run | `skinspec` served | reference raygen **dispatched** | patched? |
|---|---|---|---|
| … | `-deep` | `d002cc05eb940591` | — |
| … | `-clothhi` (the base capture) | `d622fb9e1dcb8cd0` | — |
| 885971 | `-cavity` (6 mm) | **none logged** | — |
| 893313 | `-cavityd` (15 mm) | `21a92f1a77eb4c22` | **yes** |
| 903253 | `-cavityhi` (k=1.0) | `40c6faab52a13874` | **NO — pass-through** |

Confirmed on the parked bytes: in
`skin.set/…-cavityhi`, `40c6faab52a13874.rgs_reference_main.spv` is
byte-identical to the base. **The "k = 1.0, full occlusion" screenshot is the
base image.** That is why it measures as base, and it is why "k = 1.0 looked
weaker than k = 0.85" — there was no k.

Two further things this table says:

- The `-cavity` (6 mm) run logged **no** `rgs_reference_main` dispatch at all.
  **Do not read that as "the reference PT did not run" — see the correction in
  §2b.** The `-cone2` and `-cone4` runs also logged no reference dispatch, and
  their images are unmistakably not the `-cone1` image. A missing
  `trace_rays` line is a logging gap, not an absence of dispatch. The `-cavity`
  capture is simply unattributed: we cannot say which permutation drew it.
- **The permutation changes between runs.** Five consecutive runs dispatched
  five different reference raygens. Coverage of 10/12 therefore is not "83% of
  the time it works" — it is a coin flip per launch, re-flipped whenever a
  setting moves.

**Protocol consequence, and it is not optional.** Before any look-verdict on a
reference-PT rung, grep the run for its `rgs_reference_main` `trace_rays` line
and, **if one is present**, confirm the named module is in the patched set.
One of this morning's four captures fails that check outright (`-cavityhi`);
two more are unattributed. See §2b for why absence is not failure.

---

## 2. What the launches did measure

### 2.1 The lip seam moved. The term is real.

Vertical luminance scan, 20 px wide, through the lip seam at x = 1230–1250,
8-bit, from the four PNGs:

| row | base | `-cavity` 6 mm | `-cavityd` 15 mm | `-cavityhi` (void) |
|---|---|---|---|---|
| 770–794 (lip surface) | 124 · 104 · 103 · 102 | 123 · 103 · 102 · 102 | 124 · 103 · 101 · 101 | 127 · 105 · 103 · 102 |
| **798 (the seam)** | **85** | **79** | **78** | 81 |
| 802–830 (lower lip) | 85 · 126 · 131 | 85 · 126 · 130 | 84 · 127 · 130 | 84 · 123 · 130 |

Every row except the seam moves by ≤ 2, which is the frame-to-frame noise
floor. The seam moves **−6 / −7**. So **`85` F1 is answered: the lip seam
carries real BVH geometry and the ray finds it.**

### 2.2 But the occluded FRACTION is what limits it, not k

−7 % against a k = 0.85 ceiling of −85 % means roughly one sample in twelve
is finding an occluder. And nothing else moved at all:

| region | base | `-cavity` | `-cavityd` (15 mm) |
|---|---|---|---|
| philtrum (under-nose) | 133.0 | 132.6 | **134.6** |
| under-jaw | 116.8 | 116.0 | **118.8** |
| eyelid hot streak | 112.0 | 110.9 | 117.3 |

At 15 mm the nose overhangs the philtrum by 8–15 mm and should have darkened
it. It did not. **Raising k was never going to fix this**, which is why `85`'s
step 3 — the k axis — was the wrong next rung, and why this doc does not
change k at all.

### 2.3 A confound that poisons the whole set

`RayTracing/SunAngularSize` went 0.25 → 0.53 at **09:00:58**, between the base
capture (08:56) and every cavity capture (09:03 onward), and a further
sun-size test was shot at 09:10, *between* `-cavityd` and `-cavityhi`. Blurred
difference maps of every pair, including sun-vs-sun, show the same magnitude
of change and the red/green edge fringing of a sub-pixel misregistration, so
no pair in this set is a clean A/B. The seam number above survives only
because it is a localised −7 against a ±2 floor at one row; nothing weaker
than that should be read out of these captures.

**This also answers the "noisier in shadowed areas" observation, and the
answer is that it is not this term.** The splice executes *only* inside the
block the engine reaches when its own NEE ray called the pixel **lit**
(`85` §3, unchanged here), so it cannot add variance to a shadowed pixel. A
2.1× wider sun across the same boundary can, and did.

---

## 2b. Correction to §1 — a missing `trace_rays` line proves nothing

The 10:31–10:38 cone ladder falsified the negative half of §1's rule on the
same day it was written.

| capture | reference raygen logged |
|---|---|
| `-cone1` 10:31:23 | `d002cc05eb940591` (patched) |
| `-cone2` 10:33:50 | **none** |
| `-cone4` 10:36:06 | **none** |
| `-cone4w` 10:38:13 | `ab7f1822eeb0331b` (patched — a `88`-only module; under `85` this run would have been void) |

`-cone2` and `-cone4` logged no reference dispatch, yet they differ from
`-cone1` by mean |Δ| 7.05 and 7.22 of 255 across the face, with 66 % of pixels
past the ±2 noise floor. **The shaders demonstrably ran.**

Cause: `log_open` fires **per Vulkan process**, not per launch, and the
overwhelming majority of records carry **zero** `trace_rays` of any kind — of
the last 14 `log_open`s, 11 logged none at all and only one named a reference
raygen. Whatever gates that channel, it is not "did the pipeline dispatch".
`swap_layer.c`'s per-handle dedup (`:624`, `:745`) is not the limiter; the
records are simply absent.

**What survives, and it is still worth running:**

- A logged reference trace naming an **unpatched** module → **capture void.**
  This is how `-cavityhi` was caught, and it holds.
- A logged reference trace naming a **patched** module → confirmed.
- **No line → no information.** Fall back to the `overlay_manifest` for what
  was *served*, and to the pixels for whether it *ran*.

---

## 2c. The cone ladder measured — the horizon tap is the entire effect

Four captures, same pinned S1 frame, 10:31–10:38, `-cone1/2/4/4w` on
`-clothhi`. Non-skin controls flat (sky_topright −0.39, terrain_right +0.06,
hair +0.13), so no exposure drift. `-cone1` sits +2 to +4.5 above the 08:56
base, so **`base(85 am)` is not a control for this set** — read the ladder
internally only.

Pairwise mean |Δ| over the face crop:

| pair | mean \|Δ\| | pair | mean \|Δ\| |
|---|---|---|---|
| cone1→cone2 | **7.047** | cone2→cone4 | 2.692 |
| cone1→cone4 | **7.222** | cone2→cone4w | 2.572 |
| cone1→cone4w | **7.330** | cone4→cone4w | 1.891 |

`-cone1` is tap 0 alone, and tap 0 **is** `L` — so `-cone1` is `85`'s term
with `88`'s tmin and ramp. Every visible gain arrives with the second tap
(`-cone2`). The two lateral taps and the 12°→25° widening move the image by
about a quarter of that, close to the noise. **`-cone2` buys the whole effect
at half the ray budget of `-cone4w`.**

### Where the darkening lands

Binned by `-cone1` luminance over the face crop (`cone2 − cone1`):

| L bin | median Δ | relative |
|---|---|---|
| 0–60 (shadowed) | −0.3 to −0.9 | **≈0 %** |
| 60–80 | −4.77 | −5.2 % |
| 80–100 | −6.35 | −6.7 % |
| 120–160 | −3.9 to −3.3 | −3.8 → −2.9 % |
| 180–255 | −2.5 | −3.5 % mean, **−1.2 % median** |

Shadowed skin does not move — the lit-only gate holds, empirically. The
bright-skin bins have a mean four times their median: a small set of pixels
moves hard (the seams) while most bright skin barely moves. That is the shape
we wanted.

Binned instead by **distance to the nearest shadowed pixel** (`L < 55`), over
lit skin only:

| distance (px) | median Δ | relative |
|---|---|---|
| 0–3 | −11.7 | **−10.5 %** |
| 3–6 | −6.4 | −5.2 % |
| 6–10 | −5.5 | −4.2 % |
| 15–25 | −4.7 | −3.3 % |
| 40–60 | −3.9 | −2.5 % |
| 60+ | −1.8 | **−1.1 %** |

Monotone falloff from −10.5 % at the shadow boundary to −1.1 % in the open.
**This resolves the "flat lit cheek moved −8.8" worry**: any ROI within ~15 px
of a shadow reads −3.5 % to −10 %, and the earlier cheek box was one. Far from
any boundary the term costs about 1 % — negligible.

### The philtrum crease — the feature the user actually picked out

The user singled out the line under the nose in `-cone4w`. It is not a
`-cone4w` feature. Box `(1140,680)-(1320,780)` (nose base, septum ring,
philtrum), luminance vs `-cone1`:

| rung | box mean Δ | crease line (darkest 15 %) | lit skin (top 40 %) | contrast |
|---|---|---|---|---|
| cone1 | — | 67.79 | 168.22 | 100.43 |
| cone2 | **−8.06** | 63.75 | 157.78 | **94.04** |
| cone4 | −7.56 | 63.97 | 158.20 | 94.23 |
| cone4w | −7.42 | 64.22 | 158.19 | **93.97** |

All three post-horizon rungs land within 0.3 of each other on crease contrast,
and `-cone2` is fractionally the darkest of them. The crease is bought by the
horizon tap; the lateral taps and the wider angle do not touch it.

### Noise floor — measure the ladder against this, not against zero

Shadowed skin (`L < 55`) cannot execute the splice, so any delta there is pure
run-to-run denoiser variance. Over the face crop:

| pair | mean \|Δ\| on shadowed skin | mean \|Δ\| face-wide |
|---|---|---|
| cone1→cone2 | 3.92 | 7.05 |
| cone2→cone4w | **1.42** | 2.57 |
| cone4→cone4w | **1.22** | 1.89 |

`cone4`→`cone4w` is 1.55× its own noise floor. `cone2`→`cone4w` is 1.8×.
`cone1`→`cone2` is 1.8× a *much larger* floor and 7.05 in absolute terms. The
lateral taps and the widening are not resolvable in a single capture pair.

### `-cone2w` — built 2026-09-01, and it is the rung that settles this

`-cone2w` = 2 taps at θ = 25° (`0.85,0.006,2,25`). The 10:3x ladder confounded
two axes: `-cone4w` differs from `-cone2` in **both** the lateral taps and the
angle, so a stated `-cone4w` preference cannot be attributed. `-cone2w` isolates
the angle at `-cone2`'s ray cost.

Confirmed on the shipped bytes (`ab7f1822eeb0331b`, and 12/12 alike):

| rung | flags-16 traces | cos θ / sin θ constants |
|---|---|---|
| cone2 | 2 | `0.978147626` / `0.207911685` (12°) |
| **cone2w** | **2** | **`0.906307817` / `0.422618270` (25°)** |
| cone4 | 4 | 12° |
| cone4w | 4 | 25° |

`cone2w` differs from **both** `cone2` and `cone4w` in all 12 reference
modules. If `-cone2w` reads as `-cone4w`, the lateral taps are dead weight and
`-cone2w` ships. If it reads as `-cone2`, the angle is dead weight and
`-cone2` ships. Either way one of the two cheap rungs wins.

### Why it lands there, from the emitted code

The horizon weight is `cos(A+θ)` (`%4426` in `ab7f1822eeb0331b`), floored at
`WMIN` — `%4442 = %4426 >= 0.05`, `%4443 = Select(·, %4426, 0)`. So the
weight can never go negative, and past `A > 90° − θ` the horizon tap drops out
of **both** numerator and denominator, leaving tap 0 alone. Between those
limits the tap rides at up to ~78° off the normal, which is exactly where a
6 mm reach grazes local curvature. The term is therefore a **terminator
softener / contact shadow**, and its selectivity is by *grazing angle*, not by
concavity. Worth saying plainly, because it is not what `85` claimed to build.

---

## 3. The eyelid seam and the lip highlights are not occlusion, and no tmax fixes them

The bright streak on the upper lid measures **RGB(252, 244, 234)** at its
peak — the sun's own colour, not skin albedo — over a hard-edged blob of about
20 × 12 px. A light-coloured, near-saturating, sharply bounded highlight on a
**convex** surface is a low-roughness specular lobe, almost certainly the oil
/ coat layer in the standing stack. An occlusion deficit reads diffuse and
soft, and it cannot appear on a convexity: there is nothing above the lid to
occlude.

The same reading applies to the bright wash on the lower lip, where the
vermillion is the smoothest skin on the face and is the stack's most exposed
false-positive site.

**What this build does and does not do about it.** The factor multiplies the
sun term *after* the shader's own `NClamp(diffuse·NoL + spec, 0, 1)`, so it
scales the specular too — meaning speculars **inside a crease** darken for
free. A highlight on a lit convexity is untouched by construction. That is a
separate rung against the oil lobe, and the cheapest first move is a
discriminator, not a build: serve `-clothhi` against a no-oil rung on one
pinned frame. If the streak moves it is ours; if it does not, it is the
engine's eye-wetness geometry and `31-WET-EYES.md` is the file. **Not done
here, and it should not be bundled into this ladder.**

---

## 4. Coverage: the detector was anchored on the wrong half

`85`'s `find_class_fetch` (inherited from `patch_earglow.py`) requires

    OpBitwiseAnd %uint <x> %uint_4294967264      ; & ~31
    OpIEqual %bool <that> %uint_160              ; == class 5

and dies if it is absent. In `40c6faab52a13874` and `ab7f1822eeb0331b` there
is no such compare — 0 occurrences of the mask constant in either. This is
**GOTCHAS #4** exactly: a detector written against the *mode-dependent* half
of a signature, and `find_lut_gens.py` vs `find_tonemap_gens.py` is the
worked example the file already carries.

The material word is in all twelve. Those two are the **SER** permutations,
and they consume the class as a reordering hint instead of comparing it:

```
%1656 = OpIAdd %uint <root_const[1]> %uint_5     ; the bindless MATERIAL slot
%1657 = OpAccessChain %_ptr_UniformConstant_936 %10 %1656
%1660 = OpImageFetch %v4uint %1658 %1659 Lod %uint_0
%1661 = OpCompositeExtract %uint %1660 1         ; the material word
%1662 = OpShiftRightLogical %uint %1661 %uint_5  ; == the class
        OpReorderThreadWithHintNV %1662 %uint_3  ; <-- not a compare
```

So the anchor moves to the mode-independent half: **the bindless material
fetch `table[root_const[1] + 5]`, component 1, `>> 5`.** Found exactly once in
**12/12**. `(word >> 5) == 1` is the same predicate as `85`'s
`(word & 0xFFFFFFE0) == 32`.

**Two independent checks tie the new anchor to the gate that was on screen.**

1. *Same texel.* Where the module does form the legacy compare (10 of 12), it
   is asserted to read the **same coordinate operands** as ours. It does, in
   all ten. The compiler emits the slot-5 fetch twice — once before the bounce
   loop, once inside it — and never CSEs them; `85` cloned the inner copy,
   this anchors the outer. Same texture, same texel, same value.
2. *Dominance.* `dev/cfg_dom.py` (new) builds the block graph and the
   dominator tree and proves the class word **already dominates the splice in
   12/12**. So `85`'s 20-instruction clone-by-text was never needed, and the
   build now dies rather than guessing if that ever stops being true.

`spirv-val` is the backstop under all of this: it enforces SSA dominance, so a
wrong answer fails the build rather than reaching the screen.

---

## 5. Mechanism — the emitted code

Reach is unchanged from `85` §2: `rgs_reference_main` **only**, the
reference / photo-mode path tracer. All 77 compute and all 4 ReSTIR-GI modules
are byte-identical to base and cmp-asserted so. Gameplay is untouched.

101 instructions, uniform across all 12 modules, spliced immediately before
the `OpSelectionMerge` guarding the module's own sun block — i.e. **inside**
the region the engine reaches only when its own NEE ray reported the pixel
LIT.

```
; --- gate ------------------------------------------------------------------
%skin = OpIEqual %bool %classword %uint_1        ; sec 4: the >>5 anchor, 12/12
%b0   = OpIEqual %bool %bounce_phi %uint_0
%gate = OpLogicalAnd (OpLogicalAnd %skin %b0) %sun_cond
%mask = OpSelect %uint %gate %uint_39 %uint_0    ; 0 == provably-missing ray

; --- the tap basis ---------------------------------------------------------
%L    = Normalize(<the module's own NEE sun-disc direction, verbatim>)
%Nsel = OpSelect %v3float %gate %N %L            ; SELECT BEFORE NORMALIZE
%N    = Normalize(%Nsel)                         ; so a false gate cannot
%cosA = OpDot %L %N                              ; feed NaN to OpTraceRayKHR
%P    = %N - %L*%cosA
%sinA = Length(%P)
%T    = %P * (1 / NMax(%sinA, 1e-6))             ; == 0 when L || N
%B    = Cross(%L, %T)                            ; unit by construction; == 0
                                                 ; when T is -- NO Normalize,
                                                 ; so no NaN direction ever
; --- the taps: cos/sin of theta are build constants ------------------------
tap0 = %L                                    w0 = cosA
tap1 = %L*cosT - %T*sinT   ; TOWARD the horizon   w1 = cosA*cosT - sinA*sinT
tap2 = %L*cosT + %B*sinT   ; lateral              w2 = cosA*cosT
tap3 = %L*cosT - %B*sinT   ; lateral              w3 = cosA*cosT

; --- per tap ---------------------------------------------------------------
w_i   = OpSelect %float (w_i >= 0.05) w_i 0.0    ; drops taps below the horizon
        OpStore payload.3 %float_10000           ; re-armed before EVERY tap
        OpTraceRayKHR %as %uint_16 %mask 1 1 0 %prehit %f_1en04 tap_i %f_tmax
                            ^CullBackFacing              ^tmin 0.1mm
t_i   = OpLoad %float payload.3
occ_i = OpSelect %float (t_i > 5e-5 AND t_i < tmax)
                        NClamp(1 - t_i*(1/tmax), 0, 1)   ; <-- the ramp
                        %float_0
num  += w_i * occ_i ;  den += w_i

; --- combine: a cosine-weighted AVERAGE, not a min -------------------------
%occ  = OpSelect %float %gate NClamp(num / NMax(den, 1e-6), 0, 1) %float_0
%fac  = OpFSub %float %float_1 (OpFMul %occ %k)

; --- application: 3 sites, one per channel, innermost ----------------------
%new  = OpFMul %float %NClamp(diffuse*NoL + spec, 0, 1) %fac
%out  = OpFMul %float %new %sunRadiance_c        ; one operand token rewritten
```

### Why these choices

**Centred on L, tilted toward the horizon.** At a 0.53° disc a 1–2 mm seam
wall subtends almost nothing from L itself — that is the −7 % of §2.2. The
same wall subtends a large angle from a **grazing** direction, so the tap
rotated toward the tangent plane is the one that finds it. Taps tilted the
other way, up off the surface, are wasted rays and are not emitted. Calling
this what it is: **short-range directional AO on the sun term, not a soft
shadow.** It is the right cheat at a 0.53° source, and it is a cheat.

**Averaged, not min-combined.** A min over taps re-binarizes the result per
pixel, over-darkens, and hangs a contact halo on every silhouette. The
cosine weight `max(dot(tap, N), 0)` falls out of the same geometry the taps do
and naturally zeroes any tap that has swung below the horizon; the analytic
form `cos(α ± θ)` costs two multiplies instead of four dot products.

**The ramp.** `85`'s factor was binary — a hit at 5.9 mm darkened exactly as
much as one at 0.1 mm. `occ = saturate(1 − t/tmax)` makes the term read as
depth and cuts per-sample variance, which is the honest answer to "it gets
noisier" even though §2.3 says this term was not the source of what was seen.

**tmin 0.5 mm → 0.1 mm.** `85` argued 0.5 mm from a worst-case float position
error of ~1 µm — a 500× margin, while donating a third of a 1.5 mm seam to the
tmin. 0.1 mm keeps 100×. At the weight floor (0.05, ≈ 2.9° above the surface)
the grazing re-hit distance is ~1 µm / 0.05 = 20 µm, still 5× under tmin. The
structural guard is unchanged and is the real one: **CullBackFacingTriangles**
means the only way to re-hit your own triangle is from underneath, which is
culled before any hit shader runs.

**Still no PRNG draw.** The taps are deterministic rotations of the engine's
own NEE direction in a basis built from the harvested primary-hit normal.
Nothing is sampled, so the module's LCG chain is untouched and every
downstream sample's noise stays bit-identical to base. The A/B remains one
variable **at the pixel**, not just at the build.

### Identity when dead — stronger than `85`'s, not weaker

Each tap's `t` is pre-armed to 10000 and `occ_i` is 0 unless
`5e-5 < t < tmax`, so a false gate gives `num = 0` by all four of `85`'s
paths. On top of that the combined occlusion passes through
`OpSelect(gate, …, %float_0)`, so **no upstream NaN can reach the factor** —
and then `fac = 1 − k·0 = 1.0` exactly, making every rewritten site compute
`src * 1.0 == src` bit-for-bit. The gate also drives `cullMask` (39 or 0) and
each tap direction falls back to `L` when it is false, so a garbage G-buffer
normal on a non-skin pixel can never produce a NaN ray direction.

---

## 5b. `-cone2all` — the same cone on every direct light

`88` §11 said the term was sun-only by construction and that extending it was
possible but unmeasured. `-cone2all` is that extension, built so the question
can be answered by looking at the screen instead of by argument.

### What "all lights" turned out to mean

The reference raygen has **four** shadow rays with cullMask 39. One is the
sun's (its mask is a computed `OpSelect` on the backlit bool, which is the
discriminator the detector uses). The other three are literal-mask-39 and read
a **64-byte light struct array** through `OpRawAccessChainNV` — point, spot and
area lights. Two of those three carry a shading shape that is *cleaner than the
sun's*:

    OpTraceRayKHR as %uint_12 %uint_39 %uint_1 %uint_1 %uint_0 org tmin dir tmax pay
    t   = OpLoad %float <InBoundsAccessChain pay %uint_3>
    e   = OpFOrdEqual %bool t %float_10000        ; miss => visible
    v   = OpSelect %float e %float_1 %float_0
    _   = OpFMul %float v r0                      ; x3, the light's radiance

`v` is one scalar multiplied into all three channels, so **one** rewrite
reaches the whole light term — against three for the sun. `find_local_sites`
requires `v` to have exactly three uses, so that is proved rather than assumed
(GOTCHAS 3).

The **third** literal-mask-39 trace is deliberately not patched. Its visibility
does not scale anything; it drives an `OpBranchConditional` into a large region
that also carries a light-**type** enum switch (`type == 1`, `type == 2`) and a
frontier ladder — it reads as next-event *selection*, not shading, and it is
not a construct to splice into on a guess. The detector counts both:
`LOCAL_TRACE_CANDIDATES = 3` and `LOCAL_SITES_EXPECTED = 2`, and the build dies
if either moves. **So `-cone2all` is "all lights that shade by a visibility
scalar", which is not provably "all lights".** Say it that way when reading the
capture.

### What is emitted

Three cones per module instead of one — the sun's plus one per local site —
each built by the same `emit_cone`, so the only differences are the
acceleration structure, the NEE direction, and the light's own lit-condition.
The origin does not differ: it is `prehit`, a property of the surface hit, not
of the light. Confirmed on the shipped bytes:

| rung | flags-16 traces / module | total across 12 |
|---|---|---|
| cone2 | 2 | 24 |
| **cone2all** | **6** | **72** |

The gate's third conjunct is per light — for the sun the bool its own block
branches on, for a local light `t == 10000` on that light's shadow payload — so
the term can still only ever *subtract* from light the engine had already
decided to add.

### Where the cost is

One of the two local sites is **inside the light loop** (asm 5427–5774). Its
added rays therefore scale with the **visible light count**, not with a
constant: 2 rays × (1 sun + 1 resolved light + N looped lights). Outdoors at
midday that is close to `-cone2`. In an interior with a dozen practicals it is
not. **This is the only rung in `88` that can plausibly cost something**, and
measuring that is the entire point of building it.

### New gates

- k = 0 identity control now runs **with `--all-lights`**, so it covers all
  five rewrites per module, not three. Still 12/12 byte-identical.
- Site coverage asserts 36/36 sun sites **and 24/24 local sites**.
- Everything a cone reads — class word, bounce counter, `prehit`, normal — is
  `cfg_dom`-proved to dominate **each local splice**, which the sun result does
  not imply: one of them sits inside a loop the sun splice is not in.
- `verify_cavity2.py --lights 3` groups the flags-16 traces by cullMask,
  requires exactly three groups of `taps`, and re-runs the whole per-cone
  verification on each. The local site check is its own: the factor has exactly
  one use, that use scales a `Select(., 1, 0)`, the result feeds exactly three
  channels, and the original visibility is left with exactly two mentions —
  its own definition and our multiply.

### A/B

`-cone2all` vs `-cone2`, **in a scene with practicals** — an interior, or a
night exterior under neon. Outdoors in daylight the two rungs are near enough
to identical that the capture will say nothing. Two things to read:

1. **Does skin under a practical gain the crease definition the sun rung
   gained?** If the answer is no, the extension is dead and `-cone2` ships.
2. **What does it cost?** Screenshots cannot tell you this — the reference PT
   accumulates, so it shows as slower convergence, not framerate. That needs a
   stopwatch on the same frame, twice.

Local lights in this engine are area-sampled and soft, so the hard-terminator
seam class the sun rung fixes largely does not arise under them. The honest
prior is that this rung loses. It is built so that prior can be falsified.

---

## 5c. `k_local` — the area-light over-darkening, and why it is a solid-angle error

`-cone2all` was shot and the verdict is split: **concentrated sources look
markedly better** — the user's words were that faces read better on the street
and in rooms with few light sources, and that there is a surprising amount of
that in this game — but **area lights go WAY too dim**.

> ⚠ **A SECOND CANDIDATE CAUSE, FOUND IN `89` §2 AND NOT YET RULED OUT.**
> This term's `bounce == 0` gate is not a bounce gate. `find_bounce_counter`
> documents its tie-break as *"outermost wins"*, and the outermost counted loop
> in `rgs_reference_main` is the **sample** loop (`cbv[188].y`), not the path
> loop (`cbv[188].z`, identified by its 3 fp phis seeded to 1.0 — the RGB
> throughput). So the gate reads `sample == 0` — in **5 of the 12**
> permutations; the other 7 got the right counter by luck (`90` §1). In those 5,
> with `RayNumber = 1` (the default), it is **always true** — and the cavity term therefore runs at **every
> bounce**, not just the primary hit. A darkening meant for one hit, applied
> once per bounce, compounds; that is a plausible source of "WAY too dim" all
> by itself, and it is not addressed by any `k_local` rung below. It predicts
> the term gets *weaker* as `RayNumber` rises, which is a CET-panel test with
> no rebuild — **do that before shooting the `k_local` ladder.** The
> solid-angle diagnosis below stands on its own reasoning and is not retracted;
> the two can both be true.

### Diagnosis

The cone measures "what fraction of a ~12° cone around **one** direction is
blocked within 6 mm", and then removes `k` of the **whole** light term. For the
sun that is honest: the disc subtends 0.53°, so the cone covers the entire
source. An area light subtends tens of degrees, so the cone samples only a
slice of it while the factor bills the whole thing. The error scales with the
source's solid angle.

It compounds: §2c already measured that this term is strongest at **grazing
incidence** (−10.5 % at a shadow boundary against −1.1 % in the open), and
local lights in a room illuminate a face from many directions, so a much larger
fraction of their energy arrives grazing than the sun's does.

Checked and **not** the cause: all three NEE traces in the raygen share the
identical origin triple, so `prehit` is the correct origin at the local sites
too. This is not an origin bug.

### The options, and what was rejected

Consulted, ranked, and the two cheap-looking ones were killed:

- **cos A rolloff on `k` for local lights** — rejected. It removes the effect
  exactly where it earns its keep. The result would be a term that does nothing
  visible.
- **Energy-redistributing `fac = (1 − k·occ)/(1 − k·occ_bar)`** — rejected. It
  is no longer occlusion, it is local contrast enhancement: it pushes
  unoccluded convex skin *above* the engine's physically-lit level, per light,
  and that stacks across lights. `occ_bar` is also scene-dependent, so the mean
  is only preserved where the scene happens to match the constant. It hides the
  shape error in the mean rather than fixing it.
- **Scale `k` by the source's angular size** — correct, and the eventual
  answer, but it needs a radius field out of a 64-byte light struct whose only
  float members are at offsets 0/16/32 (position, radiance, direction); 12, 28,
  44 and 60 are packed uints. Misreading it gives per-light-type garbage —
  spots dimming, panels not — which reads as flicker across light types and is
  miserable to debug in SPIR-V. Not worth it before the diagnosis is proven.
  Its refinement is worth writing down now, because it is not obvious: a real
  occluder 1–2 mm off the skin **does** shadow most of even a large panel, so
  the right form is not a flat `min(1, Ω_cone/Ω_src)` but a blend that keeps
  full strength at contact, e.g. `k·mix(sa_ratio, 1, saturate(1 − t/2 mm))`.
  The 6 mm ramp already does a crude version of this.
- **A separate `k_local`** — built. Not because it is the answer, but because
  it is the diagnostic.

### What was built

`--k-local` at the two local-light sites only; the sun keeps `--k`. Three rungs
move it alone: `-cone2all20/35/50` at 0.20 / 0.35 / 0.50, against
`-cone2all`'s 0.85. Everything else — taps, θ, tmax, the ramp, the gate — is
identical across all four, so **the sun rung's verdict is not re-opened by
any of them.**

Verification followed: `verify_cavity2.py --k-local` checks the sun cone
against `k` and each local cone against `k_local`, both pinned by resolved
constant value, so a swap of the two constants fails the build.

### What the ladder is for

This is a **mechanism test**, not a tuning exercise, and it has two outcomes:

- Some `k_local` brings area lights back to plausible while small concentrated
  sources stay convincing → **the solid-angle diagnosis is proven**, and the
  angular-size form above is justified before anyone decodes the struct.
- **No** `k_local` serves both a bare bulb at 3 m and a ceiling panel at 0.5 m
  → the **shape** is wrong, not the scale, and the angular-size form becomes
  mandatory rather than optional.

The second outcome is the more likely one and is worth just as much. Shoot a
frame that contains both kinds of source at once, or the ladder cannot
distinguish them.

---

## 6. Composition against the standing skin stack

Unchanged from `85` §5 and re-asserted by the build: the standing stack shares
no instruction and no module with this. Oil, half fuzz, cloth sheen,
real-gloss and `-deep` live in the 77 compute resolvers; c1 and the terminator
bleed live in the 4 ReSTIR-GI raygens. All 81 are cmp-asserted byte-identical.

---

## 7. Verification — every gate, all build-failing

`./dev/build_cavity2.sh` aborts on any of these. Run 2026-09-01, all green:

| gate | result |
|---|---|
| base provenance: repo dir == parked `skin.set/…-clothhi` | **93/93 byte-identical** |
| **negative control** on the unpatched base | **CLEAN, 12/12** — 0 flags-16 traces, 0 `Select(·,39,0)` masks |
| site coverage, per rung | **12/12 modules × 3 sites = 36/36**, uniformly 101 instructions each |
| **the 2 modules `85` could not reach are now patched** | asserted per rung, all 4 |
| class word dominates the splice | **12/12** (`dev/cfg_dom.py`), asserted per module |
| legacy anchor reads the **same texel** | **10/10** of the modules that have one |
| `spirv-val`, per rung | **93/93 clean × 4** |
| **k = 0 rebuild byte-identical to base** | **12/12 identical** |
| verbatim halves, cmp-asserted | **81/81** (77 dxil + 4 ReSTIR-GI) per rung |
| one-variable property | each rung differs from base in **exactly 12/93**; rung-to-rung deltas are **12 modules, 0 compute/ReSTIR-GI** |
| `dev/verify_cavity2.py` on the **shipped bytes** | **PASS × 4** |
| verifier **non-vacuity** | rejects wrong k, wrong tmax, wrong taps, wrong θ, wrong ramp — all five |
| `dev/verify_bleed_norm.py` on the standing compute rungs | **PASS ×2** (150 hold sites / 77 modules each) |
| `dev/verify_gi_ladder.sh` | **PASS** (the `72` ladder, parked rungs untouched) |
| MANIFEST provenance | `src_ser` / `ser_sha` / `ptq_sha` carried verbatim, asserted present |
| `make check` (lua + bash lint) | ok |

`dev/verify_cavity2.py` re-disassembles the **shipped** binary and re-derives
everything structurally or by resolved constant **value** (ids are not
comparable across the round trip, `40` §8). Per module it proves: trace count
= base + taps; exactly `taps` flags-16 traces; one shared cullMask, origin and
payload across them; SBT 1/1/0; tmin and tmax by value; the gate is
`AND(AND(class==1 over a slot-5 `>>5` word, bounce==0), sun_cond)` with the
sun condition cross-checked by finding the `OpBranchConditional` it drives;
the origin is the NEE origin's own pre-offset addend triple; tap 0 is
`Normalize(the module's own NEE direction)`; the horizon tap is
`L·cos θ − T·sin θ` with both constants checked by value; one member-3 pre-arm
per tap, each preceding its trace, and no store of anything but 10000; the
two-sided validity test; the ramp constant `1/tmax`; the combine is a
**division** (an average, not a min) by `NMax(den, ε)`; the gate-select to
`+0.0`; `fac = 1 − k·occ` with k by value; and exactly 3 sites of the form
`FMul(FMul(NClamp, fac), radC)` with each sun-radiance component still at
exactly 4 mentions module-wide.

---

## 8. A/B runbook

    ./dev/build_cavity2.sh --install   # DONE -- all 5 parked in skin.set/
    make install                       # NOT DONE -- see the sec 0 warning

Then pick the rung in `brdf_params.txt` or the CET panel.

**Scene.** A close-up face, **front-lit by the sun**, photo mode, camera
pinned, frame settled. The frame must contain at once the **creases** (lip
seam, eyelid crease, nostril) and the **modelled overhangs** (nose over
philtrum, jaw over neck, ear bowl). Shoot the same frame for every rung.

**Before reading any capture: grep the run's `trace_rays` for
`rgs_reference_main`, and if a module is named, confirm it is one of the 12.**
The rule is one-directional (§2b): a logged trace naming an **unpatched**
module voids the capture outright. A logged trace naming a patched one
confirms it. **No line at all proves nothing** — most `log_open` records carry
zero `trace_rays` of any kind, so silence is a logging gap. With this build all
12 are patched, so the check can now only ever come back clean; keep running it
against the manifest anyway, to catch a stale overlay.

Ladder, one variable per step:

1. `-cone1` vs `-clothhi`. Claim: the lip seam darkens **more than `85`'s
   −7**, from coverage + ramp + tmin alone. This is also the rung that proves
   `85`'s result was real on the permutation that now always runs.
2. `-cone2` vs `-cone1`. **The main question.** Claim: creases and the
   *modelled overhangs* both darken, because the horizon tap sees walls that L
   cannot. If §2.2's flat philtrum moves here, the design is right.
3. `-cone4` vs `-cone2`. Claim: smoother, less directional. If it is
   indistinguishable, keep `-cone2` — it is half the rays.
4. `-cone4w` vs `-cone4`. θ 12° → 25°. Wider = more occlusion but less like a
   shadow and more like AO; this is where it will start to look wrong first.
5. **`-cone2w` vs `-cone2` vs `-cone4w`, shot back-to-back in one session.**
   The disambiguating rung (§2c). Steps 1–4 were already shot on 2026-09-01
   and 3–4 came back at ~1.5× their own noise floor, so **do not** re-litigate
   them from a single capture pair; shoot this triple instead. `-cone2w`
   reading as `-cone4w` retires the lateral taps; `-cone2w` reading as
   `-cone2` retires the angle.

6. **`-cone2all` vs `-cone2`, in an interior or under neon** (§5b). The
   SCOPE axis. Daylight exteriors cannot answer it — the two rungs barely
   differ there. Also time it: the cost is inside the light loop, so it scales
   with the visible light count and a screenshot cannot show it. **Already
   shot: concentrated sources win, area lights go far too dim** (§5c).
7. **`-cone2all20` vs `35` vs `50` vs `-cone2all`** (§5c), in a frame holding
   **both** a concentrated source and an area light. Not a tuning pass — read
   it as: does ANY `k_local` serve both? If none does, the shape is wrong
   rather than the scale, and the angular-size form becomes mandatory.

**Measure against the noise floor, not against zero (§2c).** Shadowed skin
(`L < 55`) cannot execute the splice, so `mean |Δ|` there *is* the floor for
that capture pair — it ran 1.2–1.4 on the 10:3x set. A face-wide `mean |Δ|`
under ~2× its own floor is not a result.

---

## 9. Pre-registered confounds and falsifiers

`85`'s F1 (no BVH geometry) is **retired** — §2.1 answered it. F4 (double with
the engine's own shadow) and F6 (sample count) carry over unchanged and are
still structurally sound. The new ones:

| # | confound / falsifier | observation | reading, and what to do |
|---|---|---|---|
| **G1** | **the eyeball behind the lid** | the whole upper lid greys out, not just the crease | the horizon tap can hit the eyeball, which sits < 6 mm behind the lid; the same story for teeth behind lips. Somewhat physical, reads wrong. Check whether the eye/teeth instances are in cullMask 39 before touching θ; the cheap step is `-cone2` → `-cone1` |
| **G2** | **eyelash cards** | dark ribbons around the eye rim | the taps carry **no** opaque-force flag (flags 16 only), so alpha-tested lashes still alpha-test. If ribbons appear anyway the any-hit is not running on SBT 1/1/0 and that is a finding, not a knob |
| **G3** | banding | 3–5 discrete grey levels on a smooth crease | the tap count quantises the average. The ramp is meant to smooth this; if it has not, that is evidence the ramp is not reaching, so check `-cone1` first |
| **G4** | anisotropy / swimming | darkening that shifts direction across the face or under animation | the basis is built from L and N in their own plane, so it is uniquely determined and should **not** swim. If it does, the harvested normal is wrong — a `find_origin_offset` problem, not a cone problem |
| **G5** | acne | fine dark speckle on flat lit skin, scaling with grazing angle | tmin dropped 5×. Raise `TMIN` to 1.5e-4 and rebuild. **Do not lower k** — that hides the feature too. Built-in suppressor: the term scales a value ∝ NoL, so grazing acne multiplies something already near zero |
| **G6** | cost | frame time | 4 traces per lit skin pixel per bounce-0 sample at ≤ 6 mm. `-cone2` is half of that and `-cone1` a quarter. Photo-mode priced |
| **G7** | the specular streaks (§3) | eyelid / lip highlights unchanged at every rung | **expected, and pre-registered.** They are not occlusion. Do not respond by raising k or θ |

---

## 10. Files

- `dev/cfg_dom.py` — **new.** Block graph + Cooper-Harvey-Kennedy dominators
  over a disassembly. Exists so a value that is already in scope is used
  as-is and cloning is the fallback rather than the only strategy.
- `dev/patch_cavity2.py` — **new.** The patcher. `find_class_word` (the
  slot-5 anchor, 12/12) and `cross_check_legacy` (same-texel assertion
  against `85`'s anchor). Reuses `patch_cavity.find_sun_branch` and
  `find_sun_sites` rather than forking them. All detectors run before any
  rewrite (GOTCHAS #12).
- `dev/verify_cavity2.py` — **new.** The shipped-bytes verifier of §7, plus
  `--negative` and `--lights N` (§5b): it groups the flags-16 traces by
  cullMask and verifies each cone separately.
- `dev/build_cavity2.sh` — **new.** Six rungs and every gate in §7. The
  rung spec gained a fifth field, `sun|all` (§5b).
- `swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cone{1,2,2w,2all,4,4w}/` — 93
  modules each, **parked** in `skin.set/`.
- `init.lua` — six selector rows added after `85`'s three. **Not deployed.**
- `dev/patch_cavity.py`, `dev/build_cavity.sh`, `85`'s three rungs —
  **untouched**, so `85` stays reproducible.

---

## 11. Unsure / not done

- **THE TERM IS SUN-ONLY, BY CONSTRUCTION.** Confirmed structurally in
  `ab7f1822eeb0331b` (12/12 alike). The splice sits beside the engine's own
  directional NEE, whose light comes from **fixed uniform slots** — `%1317[0][5]`
  is the direction (dotted with N to form the backfacing test the gate reuses)
  and `%1317[0][6]` the radiance. No induction variable indexes either. The
  module's **other three** mask-39 shadow rays read a **64-byte light struct
  array** by `OpRawAccessChainNV` (one of them inside a loop at asm 5427–5774,
  two resolved singly), i.e. the local point / spot / area lights — and the
  splice is in none of them. Under a practical light, or in shade, `-cone2`
  is a no-op.
- **SUPERSEDED 2026-09-01: the extension was built** as `-cone2all` (§5b),
  covering the 2 of 3 local-light NEE sites that shade through a visibility
  scalar. The third is still not patched and the reason is in §5b. The
  paragraph below is kept because its cost argument is unchanged and is what
  the A/B has to falsify.
- **Extending it to local lights is possible and was not done.** `L` is
  available there as `normalize(lightpos − P)`, so the cone geometry is
  unchanged, and the class-1 / bounce-0 gate transfers verbatim. Three
  reasons it was not: (a) one of the three sites is **inside the light loop**,
  so the cost is 2 rays × light count, not 2 rays — in a Night City interior
  that is a different order of expense from the sun rung; (b) the artefact
  the user actually reported is a **hard sun terminator** on skin, and local
  lights in this engine are area-sampled and soft, so the seam class largely
  does not arise; (c) it would be three more splice sites × 12 permutations
  with no measurement behind it. Revisit only if a seam is *seen* under a
  practical.
- **Never launched. No verdict. Not committed, not deployed.**
- **`make install` has not run**, and it will carry `84`'s and `82`'s
  undeployed changes with it (§0).
- **The specular streaks are not addressed** (§3) and deliberately not
  bundled. The next cheap move there is a discriminator launch, not a build.
- **§2's numbers rest on confounded captures** (§2.3). The seam result is
  believable because it is localised and large against the floor; nothing
  smaller from that set should be.
- **Fable's unexplored suggestion, and it may be the best idea in this
  document:** the material G-buffer this build now anchors on may itself
  carry an **authored AO / micro-cavity channel** for the raster path. If it
  does, a texture-driven cavity factor is zero rays, zero noise, artist-
  authored, and fits the same innermost-multiplier constraint exactly.
  Deciding it is a census of the slot-5 texel's other components, not a
  launch. **Not done. Do this before spending four rays per sample.**
- The `-cavity` run that logged no reference dispatch (§1) is unexplained.
- The engine's own sun-ray origin lift and the depth-buffer-derived primary
  hit (`85` §1) are both unchanged; the origin is still `prehit`. Fable's
  suggestion of pushing the origin ~0.1–0.2 mm *into* the surface along −N was
  **not** taken — it changes the value the verifier cross-checks structurally
  against the NEE origin, and the tmin drop already recovers most of what it
  would buy. It stays on the table if G5 does not fire.
