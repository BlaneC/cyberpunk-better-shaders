# 93 — The solid-angle fix is NOT buildable from this raygen: the local-light NEE has no source-size term, and the one 1/pdf it does carry is a light-*selection* weight (2026-09-01)

**STOP verdict. Nothing was built, nothing was patched, nothing was installed,
nothing was launched, no shared file was touched.** This doc is the census the
task pre-authorised as the stopping point, plus the correction it forces on
`88` §5c and the one A/B that *is* still buildable and unshot.

The ask was: implement `88` §5c's named fix,
`k · mix(sa_ratio, 1, saturate(1 − t/2 mm))`, on the working hypothesis that
the local-light NEE already computes a light-sample pdf whose reciprocal is
proportional to the source solid angle and is already in scope at the two
spliced sites. **The hypothesis is half true and the half that is true is
useless:** one of the two spliced sites carries a genuine `1/pdf`, the other
carries none, and the one that exists is a discrete RIS **light-selection**
weight in units of 1/luminance with no angular content whatsoever. Deriving
`sa_ratio` from it would be numerology, which is the register-guess the task
forbade.

---

## 0. What was surveyed, and how uniformly

Reference module for every id in this doc: **`ab7f1822eeb0331b`**, disassembly
`dev/disasm/cavity4_12/ab7f1822eeb0331b.spvasm` (the base `-clothhi` bytes as
dumped by `dev/build_cavity4.sh`). Every structural claim below was re-run
across **all 12** `rgs_reference_main` permutations by driving
`patch_cavity2.find_local_sites` and back-slicing each site's radiance operand;
the results are uniform 12/12 unless stated. The three literal-mask-39 traces
per module are at lines **5664**, **6167** (the two `-cone2all` splices) and
**12047** (the one `88` §5b deliberately does not patch).

| module | site A trace | site A `vis` | site B trace | site B `vis` | site B RIS weight `W` |
|---|---|---|---|---|---|
| 1271d3815051da17 | 3639 | `%3406` | 4159 | `%3833` | `%3568 = %3558 / %3563` |
| 21a92f1a77eb4c22 | 4030 | `%3760` | 4550 | `%4187` | `%3922 = %3912 / %3917` |
| 25b54fc4a17688df | 3639 | `%3406` | 4159 | `%3833` | `%3568 = %3558 / %3563` |
| 3d871a3170bc5815 | 4083 | `%3813` | 4603 | `%4240` | `%3975 = %3965 / %3970` |
| 40c6faab52a13874 | 5497 | `%4942` | 6000 | `%5346` | `%5104 = %5094 / %5099` |
| 4103c8860c3909e4 | 3677 | `%3432` | 4200 | `%3862` | `%3594 = %3584 / %3589` |
| 4270b745d11a5e8a | 4030 | `%3760` | 4550 | `%4187` | `%3922 = %3912 / %3917` |
| 852b31a841b85b26 | 3692 | `%3459` | 4212 | `%3886` | `%3621 = %3611 / %3616` |
| 996a3b16253c3e7f | 3669 | `%3424` | 4192 | `%3854` | `%3586 = %3576 / %3581` |
| **ab7f1822eeb0331b** | **5664** | `%5103` | **6167** | `%5507` | **`%5265 = %5255 / %5260`** |
| d002cc05eb940591 | 4226 | `%3922` | 4749 | `%4352` | `%4084 = %4074 / %4079` |
| d622fb9e1dcb8cd0 | 4218 | `%3914` | 4741 | `%4344` | `%4076 = %4066 / %4071` |

Site A has **no** `1/pdf` in **12/12**. Site B has one in **12/12**. Both sites
carry the same analytic falloff chain in 12/12. The 64-byte and 132-byte struct
layouts are byte-identical across all twelve (18 `%uint_64` strides, 13
`%uint_132` strides each).

---

## 1. Site A — the light-loop NEE (`ab7f1822`, trace at line 5664). There is no pdf here at all.

This site iterates the visible light list; every light is shaded, none is
sampled. There is no probability anywhere in it.

### The 64-byte light struct, decoded

Read through `OpRawAccessChainNV … %uint_64 %4784 <offset>`, base `%4788`
(SSBO `registers[1] + 7`), index `%4784` from the light-index list
(`registers[2] + 7`, stride 4).

| offset | id | type | what it is | evidence |
|---|---|---|---|---|
| 0 | `%4789` | `v3float` | **world position** | `%4817-%4822` = `pos − prehit − cbv[56].xyz`, then `dot` with itself → `d²` |
| 12 | `%4790` | packed `half2` | **lo `%4828` = attenuation range R**; **hi `%4831` = unidentified** | R has two independent uses: `%4843 = d/R` feeding `%4877 = max(1−d/R,0)`, and `%4867 = 1/R` feeding the `(d/R)⁴` window. `%4831` has **exactly one** use in the whole module |
| 16 | `%4791` | `v3float` | **radiance / colour** | `%4792-4794`, multiplied by the atten and the BRDF; this is what the cavity factor ends up scaling |
| 28 | `%4795` | `uint` bitfield | flags | bit0 `%4865` selects windowed-1/d² vs linear falloff; bit1 `%5058` gates the shadow ray; bit3 `%4963` and bit4 `%4976` are the diffuse / specular enables; bits 16+ `%4802 & %4723` is the category/cull mask. **Bits 2 and 5–15 unread.** No type enum |
| 32 | `%4796` | `v3float` | **spot axis** | `%4889 = dot(axis, −L)` |
| 44 | `%4800` | packed `half2` | **spot cone scale `%4880` / bias `%4883`** | `%4892 = saturate(dot(axis,−L)·scale + bias)` — the standard scale/bias cone. An omni light is scale 0, bias 1 |
| 60 | `%4801` | `uint` bitfield | per-light diffuse / specular multipliers | `(>>16)&255 · 0.01` → `%4971`; `(>>24) · 0.01` → `%4975`. **Low 16 bits unread** |

**This corrects `88` §5c**, which said "the only float members are at offsets
0/16/32; 12, 28, 44 and 60 are packed uints". Offsets **12 and 44 are packed
`half2` floats and the shader itself unpacks them** (`UnpackHalf2x16`), so the
"misreading a packed uint" hazard `88` used to defer the work is smaller than
it looked. The hazard that actually blocks the work is different and is in §1.2.

### 1.1 What the site computes, end to end

```
%4826 = NMax(d², 1e-6)                       ; d² to the light CENTRE
%4842 = Sqrt(%4826)                          ; d
%4844-%4846 = (P_light − prehit − cbv[56]) / d   ; L, unit, to the CENTRE
%4871 = NClamp((d²/R²)², 0, 1)
%4873 = (1 − %4871)²                         ; the UE4-style range window
%4875 = %4873 / NMax(d², 1e-4)               ; windowed inverse-square
%4877 = NMax(1 − d/R, 0)                     ; the linear alternative
%4878 = Select(flags&1, %4875, %4877)        ; DISTANCE ATTENUATION
%4892 = NClamp(dot(spotAxis, −L)·scale + bias, 0, 1)   ; SPOT CONE
%4893 = %4892 · %4878
%5023 = %4893 · radiance.r · %5019           ; %5019 is the BRDF (diff+spec)
%5054 = Select(luma(term) > 0.04·luma(accum), 1, 0)    ; a significance cull
%5055 = %5054 · %5023                        ; <-- the cavity factor's operand
  ...
%5100 = (%4844,%4845,%4846)                  ; SHADOW RAY DIRECTION == L exactly
%5088 = NMax(0, d·(0.85 − 0.075·S + 0.15·S·√ξ))        ; tmax, S = cbv[91].x
OpTraceRayKHR %5098 %uint_12 %uint_39 1 1 0 prehit 1e-6 %5100 %5088 %25
%5103 = Select(t == 10000, 1, 0)             ; the visibility scalar we splice
```

**There is no pdf, no `1/pdf`, no area term and no cos-over-distance² sampling
Jacobian.** `%4878` is an irradiance falloff, not a sampling density: it is
`1/d²` for a *point*, and a point has zero solid angle by construction. It is
the same number for a bare 5 cm bulb and a 2 m ceiling panel at the same
distance. It carries no information about source extent, so no `sa_ratio` can
be recovered from it.

**The ray direction is the exact centre direction with no jitter** (`%5100` is
built verbatim from `%4844-%4846`), so there is no disc/rect sample offset to
back out a radius from either. The only stochastic element is a random
*shortening of tmax*, and its scale `S` is §1.3's global CVar.

### 1.2 `%4831` is the only candidate, and it is exactly the guess the task forbids

Offset 12's **high** half, `%4831`, has **one** use in 14 949 lines:

```
%4832 = OpFAdd %float %4831 %4828        ; %4831 + R
%4833 = OpFMul %float %4832 %4832
%4834 = OpFOrdGreaterThan %bool %4826 %4833   ; cull if d² > (%4831 + R)²
```

i.e. it is a distance **added to the influence radius to form a cull radius**.
That is precisely how a *source extent* enters a cull in many renderers — and
also precisely how a fade margin, a shadow-extension, or a bounding-sphere pad
does. **One use is not an identification.** With no second, semantically
different consumer to cross-check against, adopting it as a radius would be
`88` §5c's "misreading it gives per-light-type garbage" failure in its exact
predicted form, and `GOTCHAS` #5 ("a structural detector proves a site's shape,
never what it holds") names it. **Not taken. Not guessed.**

The identical field pair appears in the reservoir loop's own copy of the struct
(`%5189` = R, `%5192` = the unknown, cull at `%5195`), so a decision about
`%4831` would settle both sites at once — which is why §5 names the one
experiment that would settle it.

### 1.3 The only "size" in scope is global, so it cannot separate a bulb from a panel

`cbv[91].x` — `%5074` at site A, `%5478` at site B, `%uint_0 %uint_91` on
`%1300`, **exactly 3 uses per module in 12/12** (the two spliced sites plus the
unpatched third trace). It scales the shadow ray's random tmax shortening:

    tmax = max(0, d · (0.85 − 0.075·S + 0.15·S·√ξ))

This is a penumbra hack, and `S` is almost certainly
`RayTracing/LocalShadow/LightSize`, the CVar `83` recorded as a "bonus surface".
It is a **single global scalar**: it has the same value for every light in the
frame, so it distinguishes nothing. It is not a per-source solid angle and
cannot stand in for one.

---

## 2. Site B — the reservoir-resolved NEE (`ab7f1822`, trace at line 6167). There IS a 1/pdf, and it is the wrong quantity.

This site is fed by a **weighted reservoir sampling (RIS) loop** over the light
list, at asm 5744–5900. Per candidate it forms

```
%5221 = the same Select(flags&1, windowed 1/d², max(1−d/R,0))  ; distance atten
%5235 = NClamp(dot(spotAxis,−L)·scale + bias, 0, 1)            ; spot cone
%5236 = %5235 · %5221                                          ; atten
%5237-%5239 = %5236 · radiance.rgb
%5242 = dot(that, (0.2126,0.7152,0.0722))    ; p_hat, the TARGET FUNCTION
%5243 = %5242 + wsum                          ; running weight sum
%5249 = %5242 / %5243
%5250 = ξ < %5249  ->  replace the reservoir  ; textbook streaming WRS
```

and on the exit block:

```
%5255 = wsum (final)
%5260 = p_hat of the SELECTED candidate
%5257-%5259 = L of the selected candidate, unit
%5261 = %5236 of the selected candidate
%5265 = OpFDiv %float %5255 %5260             ; <-- W, the RIS weight == 1/pdf
%5434 = %5265 · %5261                         ; W · atten
%5436 = %5434 · radiance.r · %5431            ; · BRDF
%5459 = %5458 · %5436                         ; <-- the cavity factor's operand
```

`%5265` **is** a `1/pdf`, and the estimator around it is correct RIS. It is
also, unambiguously, **the wrong kind of pdf for this task**:

1. **It is discrete, over lights, not continuous over directions.** The
   reservoir chooses *which light* to shade, from a candidate list. Its density
   is over a finite index set. A solid angle cannot be read out of a discrete
   selection probability — there is no measure-space relationship between them.
2. **Its units are 1/luminance, not steradians.** `p_hat` is the unnormalised
   target function `luma(atten · radiance)`. `W = wsum/p_hat` therefore carries
   dimension 1/`p_hat`. Any `Ω_cone / W` would be a unit error, not an
   approximation.
3. **It depends on the competition, not on the source.** `wsum` is the sum of
   every candidate's `p_hat` in this pixel's stream. Move a second lamp into
   the room and `W` changes for a light whose size did not. Two pixels looking
   at the *same* panel get different `W`. A term derived from it would flicker
   per pixel and per frame — the exact failure mode `88` §5c refused the struct
   decode to avoid, arrived at by a different road.
4. **The source-extent information was never in the loop to begin with.** Every
   candidate is evaluated as a point (`%5203` = `d`, `%5205-%5207` = the unit
   centre direction). The reservoir cannot carry a solid angle it never had.

### 2.1 One flagged observation, not acted on

`%5270 = Sqrt(NMax(dot(L,L), 1e-6))` where `L = %5257-%5259` is the **already
normalised** stored direction, so `%5270 ≈ 1.0`. Site B's shadow ray tmax is
therefore `≈ 0.85 m` **irrespective of how far the light actually is** (site A,
by contrast, scales tmax by the true `d = %4842`). This is either an engine
quirk or an upstream normalisation the reservoir did not intend; it is uniform
in 12/12. It is recorded because it changes what the cavity cone is composing
against at site B, and because anyone reading `-cone2all`'s local behaviour
should know one of its two sites tests visibility over a fixed ~0.85 m. **Not
investigated further, not touched.**

---

## 3. "Per light type" — there is only one type at the spliced sites

The task asked for the light-type switch. It exists, and it is **not** at either
spliced site.

- **At sites A and B (64-byte struct):** there is **no type enum**. The taxonomy
  is expressed entirely by data — offset 44's `(scale, bias)` half2 is `(0, 1)`
  for an omni point light and a real cone otherwise; offset 28 bit 0 picks the
  falloff curve. So "point vs spot" is a continuum of the *same* shading code
  path, and **"area light" is not a type these two sites can even express** —
  every light they shade is a point with an optional cone. That is itself the
  cleanest possible statement of `88` §5c's defect: the engine bills these
  lights as points, the cone measures them as points, and the *only* thing that
  makes a ceiling panel behave like an area source is that it is a different
  light array entirely (below).
- **At the third, unpatched mask-39 trace (line 12047):** the type enum is
  `%5915 = Select(i < cbv[88].y, 0, Select(i < cbv[88].y + cbv[92].z, 1, 2))`,
  tested `== 1` / `== 2` at lines 6635, 6819, 7082/7083, 10464/10465,
  12062/12063. **Type 0** reads a **132-byte** analytic-light struct
  (`registers[2] + 16`, fields at 0, 16, 28, 32, 44, 48, 60, 68, 72, 80, 96,
  128 — note the three extra `v3float`s at 48/80/96 and the two bare floats at
  68/128 that the 64-byte struct does not have). **Type 1** reads a **128-byte**
  struct at `registers[5] + 12` with `v3float`s at 0/16/32/48/64/80 and
  `v2float`s at 96/104/112 — that shape is **vertices plus UVs, i.e. an
  emissive triangle**. **Type 2** is a third class not decoded here.
- **This is where a real solid angle lives.** An emissive triangle has an area
  and a sampling Jacobian; a 132-byte analytic light has three unexplained
  `v3float`s that are the right shape for extent vectors. Both are behind the
  trace `88` §5b refused to splice on the grounds that its visibility "does not
  scale anything; it drives an `OpBranchConditional` into a large region". That
  judgement is unchanged and is reinforced: this is next-event *selection*, and
  it is a much larger construct than the two shading sites.

---

## 4. Consequence: the k_local ladder is not a stopgap, it is the ceiling

`88` §5c framed `-cone2all{20,35,50}` as "the diagnostic, not the answer", with
the angular-size form as the eventual correct fix. **On the evidence above the
angular-size form is not implementable at the two spliced sites at any price**,
because the sites do not know their sources' sizes and neither does anything
that dominates them. So the ordering flips:

- A constant `k_local` **is** the best available approximation at these two
  sites, and `88` §5c's own mechanism test is now also the decision procedure
  for whether these sites are salvageable at all.
- If no `k_local` serves both a concentrated source and an area light, the
  conclusion is no longer "the angular-size form becomes mandatory". It is
  **"these two sites cannot be fixed"**, and the choice narrows to: (a) revert
  to sun-only (`-cone2gf`) and keep the win `88` §5c already measured on
  concentrated sources; or (b) settle `%4831` by experiment (§5) before
  spending anything further.
- `88` §11's authored-AO census is untouched by all of this and is still the
  better bet.

### The numbers, so the ladder is read against something

| source | approximate Ω | `sa_ratio = Ω_cone / Ω_src` |
|---|---|---|
| the cone itself, θ = 12° half-angle | **0.1373 sr** | 1 by definition |
| sun disc, 0.53° | 6.72e-05 sr | clamped to 1 — the cone covers the sun **2000×** over |
| 5 cm bulb at 3 m | ~2.8e-04 sr | clamped to 1 |
| 30 cm fixture at 3 m | ~0.010 sr | clamped to 1 |
| 1 m panel at 2 m | ~0.25 sr | **0.55** |
| 1 m panel at 0.5 m | ~4.0 sr | **0.034** |

That is a **16×** spread across the two panel rows alone, and both are "an area
light" to a viewer. It is the quantitative reason `88` §5c predicted no single
`k_local` would serve both, and it is unchanged by this doc — it just now has
no in-shader route to a per-light answer.

---

## 5. The one experiment that would unblock the real fix

Not built here, and it is a build, not a launch-only test. `%4831` is
identifiable with **one** debug rung and **one** frame, with no shading change:

> Emit, at site A only, `radiance := vec3(saturate(%4831), saturate(%4831/R),
> 0)` under the existing class-1 / path-0 gate — a paint, in `56`'s idiom, with
> the same identity-when-dead structure (`OpSelect(gate, …, original)`), so a
> false gate is bit-identical to base.

Read the frame: if `%4831` is a **source radius**, small practicals paint near
black and big ceiling panels paint visibly red, and the value is stable per
fixture. If it is a fade margin or a bounding pad it will track `R` instead
(the green channel goes flat) or be constant across fixtures of obviously
different sizes. That is a one-variable answer to the only open question in the
whole solid-angle track, and it costs one rung and one screenshot.

**Only after that comes back positive** is `k · mix(sa_ratio, 1, saturate(1 −
t/2 mm))` worth building — and even then it reaches **site A only**. Site B's
light identity is consumed by the reservoir and its struct fields are not
re-read on the resolve path (site B reads only offsets 16, 28 and 60 —
confirmed 12/12), so site B would need the radius **carried through the
reservoir**, which means adding a phi to a loop the cavity work has so far only
read from. Say that out loud before anyone scopes it as "the same edit twice".

---

## 6. The A/B that is buildable today, and is unshot

Nothing new was built, so this is the standing ladder, not a new one. It is
listed because the task asked for the pair, the frame and the settings, and
because §4 makes step 2 the decision point rather than a tuning pass.

**The pair — one variable, both halves already on disk and already parked:**

| | rung | differs by |
|---|---|---|
| **A/B 1 (the gate, free)** | `…-clothhi-cone2allgf` vs `88`'s `…-clothhi-cone2all` | **the gate only** — `90` §1's path-vs-sample counter fix. `88`'s rung IS the old-gate build of the new one |
| **A/B 2 (k_local, the decision point)** | `…-clothhi-cone2all35gf` vs `…-clothhi-cone2allgf` | **`k_local` 0.85 → 0.35 only.** Sun held at 0.85 in both; taps, θ, tmax, ramp and gate identical |

Both `gf` rungs are `dev/build_cavity4.sh`'s output on the **fixed** gate
(`90` §0b), i.e. the `-cone2allgf` logic, on the plain standing base
`gi-50b-bleed-oil-sheen-deep-clothhi`. `88`'s `-cone2all20/35/50` carry the
**old** gate and must not be mixed into this ladder.

**The frame.** One frame, camera pinned, photo mode, that holds **at once**:

- a **concentrated** source (a bare bulb, a spot, a small practical) lighting
  skin, and
- an **area** source (a lit ceiling panel, a large sign, a window bounce)
  lighting the same face,
- plus a **non-skin control patch** (wall, hair, cloth) in frame — the splice
  cannot execute there, so its frame-to-frame `mean |Δ|` **is** the noise floor
  for that pair. Read nothing under 2× it (`88` §2c).

An interior, or a night exterior under neon. **Daylight exteriors cannot answer
this** — the local sites barely fire. **Time it**: site A is inside the light
loop, so cost scales with visible light count and a screenshot cannot show it.

**Required settings, stated before the launch and never inferred from the
capture afterwards (`45`, and the A/B-settings-sync rule):**

- **PT Overdrive ON**, **PT-in-photo-mode ON** — the term is
  `rgs_reference_main` only; without photo-mode PT every rung is inert.
- **Ray Reconstruction OFF.** Grep the Proton-prefix `UserSettings.json` for
  `DLSS_D` immediately before the launch — `CURRENT.md` records it moving
  unprompted.
- DLSS **Balanced**, RayTracedLighting **Psycho**, **2560×1440**.
- `BounceNumber` / `BounceNumberScreenshot` at their defaults — the gate fix is
  about *which* bounce runs the term, so a changed bounce count makes the halves
  two variables apart.
- **`RayTracing/LocalShadow/LightSize` must not move between halves.** §1.3
  shows it is live in all three local shadow rays; `83` records Ultra Plus
  cronning sun-side values, so pin and re-check this one.
- `RayTracing/SunAngularSize` unchanged across the pair (`88` §2.3 poisoned a
  whole set on this).
- `ser=class`, `shadowset=full-shadow`, `ptreg=on`; `brdf_params.txt` one line
  changed per half.
- `make install` has **not** run and will carry `82`/`84`/`90`'s undeployed
  changes when it does. Decide that deliberately.
- Before reading any capture: grep the run's `trace_rays` for
  `rgs_reference_main`; a named **unpatched** module voids it. All 12 are
  patched in these rungs, so this can now only come back clean — keep running
  it to catch a stale overlay (`88` §2b).

---

## 7. Files

**Created:** this file, and nothing else.

**Deliberately NOT created:** `dev/build_cavity_sa.sh` and the `-cone2all-sa` /
forced-`sa_ratio`-1 control `swaps.*` dirs. They were authorised, and they are
not written, because every version of them would have to name a register as
"the solid angle" that this survey shows is not one. `88` §5c's own words —
"misreading it gives per-light-type garbage … which reads as flicker across
light types and is miserable to debug in SPIR-V" — describe the build that was
avoided.

**Not edited:** `init.lua`, `pt_engine.lua`, `brdf_params.txt`, `Makefile`, any
existing rung, any patcher, any verifier. **Not installed. Not committed. Not
launched.**

**Reproduce the survey:** disassemble the base with `dev/build_cavity4.sh`'s own
step (`spirv-dis` into `dev/disasm/cavity4_12/`), then drive
`patch_cavity2.find_local_sites` per module and back-slice each site's first
`vis` FMul operand. The two markers used for the 12/12 uniformity table are:
the analytic falloff (`UnpackHalf2x16` plus the `%float_9_99999975en05`
denominator guard) and the RIS weight (an `OpFDiv %float` whose **both**
operands are `OpPhi %float` at the reservoir's exit block).

---

## 8. Corrections this doc makes to earlier files

| doc | claim | correction |
|---|---|---|
| `88` §5c | "the radius lives in a 64-byte light struct whose only floats are at offsets 0/16/32; 12, 28, 44 and 60 are packed uints" | offsets **12 and 44 are packed `half2` floats** and the shader unpacks them itself. 28 and 60 are bitfields. The blocker is not packing, it is that **no field in the struct is confirmable as a source size** — offset 12's high half is the only candidate and it has exactly one use |
| `88` §5c | "the correct fix is `k·mix(sa_ratio,1,…)` … not worth it before the diagnosis is proven" | it is not merely un-prioritised, it is **not implementable at these two sites**: neither site has a source-extent input, and the reservoir site does not even re-read the struct. §5 gives the one experiment that could change this |
| `88` §5b | the third mask-39 trace "carries a light-type enum switch (`type == 1`, `type == 2`)" | confirmed and expanded: type 0 = 132-byte analytic struct, type 1 = **128-byte emissive triangle** (v3 vertices at 0/16/32/48/64/80 + v2 UVs at 96/104/112), type 2 undecoded. This is the only place in the raygen where a genuine area source exists as data |
| the task's hypothesis | "the local-light NEE already computes a light-sample pdf … 1/pdf is proportional to the source solid angle" | **falsified.** Site A has no pdf (12/12). Site B has one (12/12) and it is a discrete light-**selection** RIS weight `wsum/p_hat` in units of 1/luminance, dependent on the other lights in the frame, containing no angular information |

## 9. Unsure / not done

- `%4831` (64-byte struct, offset 12 high half) is **unidentified**. §5 is the
  experiment. Everything in the solid-angle track hangs on it.
- Offset 60's low 16 bits and offset 28's bits 2 and 5–15 are unread by this
  shader and undecoded here.
- Type 2 in the third trace's switch is not decoded.
- §2.1's fixed ~0.85 m tmax at site B is observed, uniform 12/12, and
  unexplained.
- The RIS candidate loop's own struct copy (`%5156`/`%5157`/`%5158`/`%5162`/
  `%5163`/`%5167`) was verified to read the **same seven offsets** as site A but
  was not independently field-by-field cross-checked; the `%4831`-equivalent
  there is `%5192`, with the same single cull use.
- No verifier work was done, because there is no new axis to be non-vacuous on.
- **Nothing here has been on a screen.**

---

# ADDENDUM — the probe from §5 is BUILT (3 diagnostic rungs, parked nowhere, never launched)

Added after the §0–§9 stop verdict, on instruction. §5 named one experiment as
the only thing that could unblock the solid-angle track; this is that
experiment, built. **Still nothing on screen. Still not installed, not parked,
not committed, not launched. No shared file was edited.**

## 10. What was built

`dev/build_cavity_probe.sh` — three rungs on the **`-cone2allgf` base**
(`90` §0b's FIXED-gate all-lights rung on the plain standing base), plus a
`--gain 0` byte-identity control.

| rung | mode | knobs | what it asks |
|---|---|---|---|
| `…-cone2allgf-probeu` | `u` | rscale 20, uscale 0.5 | **the decisive rung.** Is offset-12's high half a source radius? |
| `…-cone2allgf-probeu10` | `u` | rscale 20, **uscale 0.05** | **one variable: `uscale` only.** Separates "U is small but real" from "U is zero" |
| `…-cone2allgf-probe44` | `44` | sscale 2 | **the decode control** (§10.3), plus the offset-44 half2 read `93` §1 left undecoded |

### 10.1 The edit — three operand rewrites, and why it repaints the light's colour

The paint replaces the **local light's own radiance triple** — the three
`OpCompositeExtract`s of the stride-64 **offset-16** load at site A — and
nothing else. Each of those extracts has **exactly one use** in the module
(asserted, dies otherwise, 12/12), so the whole edit is three operand rewrites
plus one straight-line block.

The alternative — overwriting the *shaded output* — was rejected and the reason
matters for how the capture reads: site A is **inside the light loop**, so an
output paint would make every visible light add a flat constant into the same
accumulator and an N-lamp frame would read as a saturated sum of N colours.
Repainting the light's **colour** instead leaves the engine's own
`1/d² · spot · BRDF · visibility` weighting completely intact. The frame still
looks like a lit frame, the nearest lamp still dominates its own neighbourhood,
and — the load-bearing consequence — **the probe is read by hue and by channel
ratio, both of which are invariant to that common weighting, and therefore also
invariant to the base rung's cavity factor.** Building on `-cone2allgf` costs
the read nothing.

Emitted, verbatim from `ab7f1822eeb0331b` (12/12 identical in shape):

```
%14262 = OpExtInst %v2float %1 UnpackHalf2x16 %4858       ; offset-12 word
%14263 = OpCompositeExtract %float %14262 0               ; R = range   (KNOWN)
%14264 = OpShiftRightLogical %uint %4858 %uint_16
%14265 = OpExtInst %v2float %1 UnpackHalf2x16 %14264
%14266 = OpCompositeExtract %float %14265 0               ; U = THE UNKNOWN
%14267 = OpExtInst %float %1 NMax %14263 %float_9_99999975en05
%14268 = OpFDiv %float %14266 %14267                      ; U / max(R, 1e-4)
%14269 = OpExtInst %float %1 NClamp %14268 %float_0 %float_1   ; BLUE
%14270 = OpFMul %float %14263 %float_0_0500000007         ; R / 20
%14271 = OpExtInst %float %1 NClamp %14270 %float_0 %float_1   ; RED
%14272 = OpFMul %float %14266 %float_2                    ; U / 0.5
%14273 = OpExtInst %float %1 NClamp %14272 %float_0 %float_1   ; GREEN
%14274 = OpIEqual %bool %1673 %uint_1                     ; class 1 == skin
%14275 = OpIEqual %bool %2388 %uint_0                     ; PATH counter == 0
%14276 = OpLogicalAnd %bool %14274 %14275
%14277 = OpSelect %float %14276 %14271 %4860              ; false operand is
%14278 = OpSelect %float %14276 %14273 %4861              ; THE ORIGINAL ID
%14279 = OpSelect %float %14276 %14269 %4862
```

**Identity when dead is exact, not approximate**: the false operand of every
`OpSelect` *is* the original extract, so a false gate makes the site compute
the base value bit-for-bit. There is no arithmetic on the dead path, no
epsilon, and no NaN route — `NMax(R, 1e-4)` is the only divisor and it is
floored before the divide.

**The gate is `90`'s FIXED gate.** `find_path_counter` (structural: the counted
ray-tracing loop whose header seeds exactly 3 fp phis with 1.0 — the RGB
throughput) supplies the counter; `E.find_bounce_counter` is still called so the
report records `legacy_helper_was_wrong` per module, and it is `true` on
`ab7f1822eeb0331b` exactly as `90` §1's 5/12 table says.

### 10.2 The channels

| ch | mode `u` | mode `44` |
|---|---|---|
| **R** | `saturate(range / 20 m)` — offset 12 **low**. The **known** field, and the sanity channel | `saturate(spot_scale / 2)` — offset 44 low |
| **G** | `saturate(U / uscale)` — offset 12 **high**. The question, monotonic | `saturate(spot_bias)` — offset 44 high |
| **B** | `saturate(U / max(range, 1e-4))` — **the scale-free ratio**, the channel that actually decides it | same as mode `u` |

### 10.3 `probe44` is a control, not a bonus

Mode `44` decodes the *other* packed half2 with the *same* `UnpackHalf2x16`
idiom, and its expected result is known in advance from `93` §1: an **omni**
point light has `(scale, bias) = (0, 1)` — black red, full green — while a
**spot** has a non-zero scale and a bias below 1. So:

> **If `probe44` does not split the frame's lamps cleanly into "green-only" and
> "red+green", the half2 decode idiom is being misread, and `probeu`'s G and B
> channels are not trustworthy either.** Shoot `probe44` first, or at least read
> it before believing anything in `probeu`.

That is the cheap falsifier this build has that §5's sketch did not.

---

## 11. How to read it — the value ranges that decide it

Only **hue and channel ratio within one lit patch** are quantitative; absolute
level is not, because the engine's `1/d²`, the BRDF, the visibility and the
tonemapper all still multiply the paint. Compare **fixture to fixture in the
same frame**, and the same patch **rung to rung**.

Expected values if `U` **is** a source radius: a bare bulb ≈ 0.02–0.05 m, a
ceiling panel ≈ 0.5–1.0 m; ranges `R` ≈ 4–20 m. So `U/R` runs ~0.004 for the
bulb and ~0.10 for the panel — **a 25× spread**, and that is the signal.

| what the frame shows | reading | what to do |
|---|---|---|
| **R channel flat or black on every lamp** | the decode is wrong at the root | **stop.** Do not read G or B. Report the frame; the offset-12 low half is not the range and `93` §1 is wrong |
| `probe44`: omni lamps green-only, spots red+green | the half2 idiom is right | proceed to `probeu` |
| `probe44`: no such split | the half2 idiom is wrong | **stop.** `probeu` is uninterpretable |
| **`probeu` G near-black on small practicals, saturated on big panels; B visibly different between them** | **`U` IS A SOURCE RADIUS** | the solid-angle fix is unblocked **at site A only** — build `k·mix(sa_ratio, 1, saturate(1 − t/2 mm))` there, and read §12's warning about site B first |
| **`probeu` B the same value on every lamp**, large or small, near or far | `U ∝ R` — a cull/fade margin | **the track is dead.** No `sa_ratio` exists. Fall back to `-cone2gf` (sun-only) or `88` §11's authored-AO census |
| **G black at uscale 0.5 AND at 0.05, B black too, on every lamp** | `U ≈ 0` — the field is unused in this scene | **the track is dead**, same fallback |
| G black at 0.5 but clearly **graded** at 0.05 | `U` is centimetre-scale and real | radius-like: read B fixture-to-fixture to confirm the spread |
| G identical on lamps of obviously different physical size | `U` does not encode size | track dead |

**Two things that will confound the read if not controlled for.** (i) A skin
patch lit by *two* lamps shows a weighted blend of two paints — read patches
where one lamp clearly dominates, i.e. close to it. (ii) In daylight the sun
dominates and nothing local reaches skin, so **nothing paints**; that is not a
null result, it is the wrong frame.

---

## 12. The A/B — frame and settings

There is no "A/B pair" in the look sense here: these are **diagnostic paints
read against each other and against known expectations**, never against a look.
Three captures of **one** pinned frame: `probe44`, then `probeu`, then
`probeu10`.

**The frame.** An **interior, or a night exterior under neon**, photo mode,
camera pinned, frame settled, containing **at once**:

- **class-1 skin** filling a usable area — a face and/or hands. Nothing else in
  the frame paints, by construction, so skin is the entire instrument;
- a **small concentrated practical** (bare bulb, desk lamp, small spot) close
  enough to dominate one skin patch;
- a **large area source** (lit ceiling panel, big sign, backlit wall)
  dominating a *different* skin patch;
- both patches visible in the same shot, so the fixture-to-fixture comparison is
  within one exposure.

This is the same frame `88` §5c's mechanism test asks for, which is deliberate:
one frame serves both the probe and the `-cone2all35gf` vs `-cone2allgf`
ladder in §6.

**Required settings — stated before the launch, never inferred from the capture
afterwards (`45`, and the A/B-settings-sync rule):**

- **PT Overdrive ON**, **PT-in-photo-mode ON** — `rgs_reference_main` only;
  without photo-mode PT the rungs are inert and the frame is base.
- **Ray Reconstruction OFF.** Grep the Proton-prefix `UserSettings.json` for
  `DLSS_D` immediately before the launch.
- DLSS **Balanced**, RayTracedLighting **Psycho**, **2560×1440**.
- `BounceNumber` / `BounceNumberScreenshot` at their defaults — the paint is
  gated on `path_counter == 0` and a changed bounce count changes what fraction
  of the pixel is painted.
- **`RayTracing/LocalShadow/LightSize` pinned** across all three captures
  (`93` §1.3: it is live in all three local shadow rays).
- `RayTracing/SunAngularSize` unchanged across the set.
- `ser=class`, `shadowset=full-shadow`, `ptreg=on`.
- **Auto-exposure**: if the paint is bright enough to move it, the frame's
  exposure differs between rungs. Read hue and ratios, never absolute level —
  and keep a non-skin patch in frame as the exposure witness.
- Before reading any capture: grep the run's `trace_rays` for
  `rgs_reference_main`; a named **unpatched** module voids it (`88` §2b). All 12
  are patched here, so it can only come back clean — run it anyway to catch a
  stale overlay.

**Serving them.** `./dev/build_cavity_probe.sh --install` parks the three rungs
in `skin.set/`. It was **deliberately not run**, and neither was `make install`.
Note that `init.lua:288` coerces an unknown `skinspec` to `off` — a silent
no-op, not an error — so **these rungs are not selectable until someone adds
selector rows to `init.lua`, which is a shared file and was deliberately not
edited here.** Whoever picks this up owns that decision, along with the fact
that `make install` will carry `82`/`84`/`90`'s undeployed changes with it.

**⚠ These are diagnostic rungs. They destroy local-light colour on skin by
design. Never ship one and never judge a look from one.** The `README.txt` in
each rung says so.

---

## 13. Gates — all build-failing, all green 2026-09-01

`./dev/build_cavity_probe.sh` aborts on any of these.

| gate | result |
|---|---|
| base provenance: repo dir == parked `skin.set/…-cone2allgf` | **93/93 byte-identical** |
| **negative control** on the unpatched base | **CLEAN 12/12** — no paint select on any radiance extract |
| **`--gain 0` rebuild byte-identical to base** | **12/12 identical** (all detectors still run) |
| site coverage, per rung | **12/12 modules, 1 site × 3 operand rewrites** |
| every reference module differs from base, per rung | **12/12** |
| verbatim halves, cmp-asserted | **81/81** (77 dxil + 4 ReSTIR-GI) per rung |
| `spirv-val`, per rung | **93/93 clean × 3** |
| one-variable property | each rung differs from base in **exactly 12/93**; `probeu` vs `probeu10` and `probeu` vs `probe44` are **12/93**, i.e. 0 compute / 0 ReSTIR-GI |
| `dev/verify_cavity_probe.py` on the **shipped bytes** | **PASS × 3** |
| standing rungs untouched | `verify_bleed_norm.py` **PASS ×2**, `verify_gi_ladder.sh` **PASS** |
| MANIFEST provenance | `src_ser` / `ser_sha` / `ptq_sha` asserted present |

### 13.1 The verifier, and its non-vacuity

`dev/verify_cavity_probe.py` re-disassembles the **shipped** `.spv`, re-derives
the site, the class word and the **path** counter structurally (ids are not
comparable across the round trip, `40` §8), and checks every knob by **resolved
constant value**. Per module it proves: the paint site is the unique stride-64
struct read that carries offsets 12, 16 and 44 on one `(base, index)` and whose
radiance extracts reach a mask-39 visibility multiply **without crossing an
`OpPhi`** (that last clause is what separates site A from the RIS *candidate*
loop, which reads the same fields — see §2); exactly three `OpSelect %float`
over **one** gate, whose false operands are exactly those three extracts; each
original extract left with **exactly one** remaining use, ours; the gate is
`AND(class==1, path_counter==0)` against the **re-derived** counter; and each
channel's arithmetic and provenance — R and G traced back through
`UnpackHalf2x16` to the offset-12 (or offset-44) raw load, B as
`saturate(U / NMax(R, 1e-4))`, every scale constant by value.

**Shown non-vacuous, not asserted to be.** The build script runs these and dies
if any is *accepted*:

    probeu10 checked with uscale 0.5   -> REJECTED   (wrong uscale)
    probeu   checked with rscale 2     -> REJECTED   (wrong rscale)
    probeu   checked as mode 44        -> REJECTED   (wrong field painted)
    probe44  checked as mode u         -> REJECTED   (wrong field painted)
    probe44  checked with sscale 0.5   -> REJECTED   (wrong sscale)
    the unpatched base, positive check -> REJECTED   (no paint present)
    probeu   under --negative          -> REJECTED   (paint present)

The `mode u` ↔ `mode 44` rejections are the important pair: they are what makes
the verifier non-vacuous **on the axis this whole build exists to settle** —
*which struct field reached the screen*. A verifier that only checked "three
selects over a gate" would have passed a paint of the wrong offset, which is
exactly the failure `93` §1.2 refuses to risk.

## 14. Files added by the addendum

- `dev/patch_cavity_probe.py` — **new.** The paint patcher: `find_paint_site`
  (the phi-refusing reachability discriminator), `--mode u|44`, `--gain 0` as
  the identity control.
- `dev/verify_cavity_probe.py` — **new.** The shipped-bytes verifier of §13.1,
  with `--negative`.
- `dev/build_cavity_probe.sh` — **new.** Three rungs, every gate in §13, the
  non-vacuity suite, `--install` (**not run**).
- `swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cone2allgf-probe{u,u10,44}/` — 93
  modules each, in the repo, **not parked**.

Nothing else was created, and **nothing existing was modified** — not
`init.lua`, not `pt_engine.lua`, not `brdf_params.txt`, not the `Makefile`, not
`patch_cavity2.py`, not `verify_cavity2.py`, not `build_cavity4.sh`, not any
existing rung. `make install` not run, nothing parked, nothing committed,
nothing launched.
