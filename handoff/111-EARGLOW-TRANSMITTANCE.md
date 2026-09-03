# 111 — Ear glow v7: the transfer replaced with **measured skin transmittance**, and the sun actually attenuated. BUILT, GATED, INSTALLED, SERVED, **SHIPPED AS THE DEFAULT**.

Written 2026-09-03. Five rungs on the standing default
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv`
(content `024998da26d84333`). **Eleven offline gates green, nine decoys and
three cross-reads rejected, installed.**

> **§0.0 — OUTCOME (2026-09-03 ~17:35). `earglow7` is the shipped default.**
> After §0.1's manifest fix the re-run sync served it for real
> (`status.txt`: `want_skinspec_req=earglow7` → `want_skinspec=earglow7`,
> `want_ser=class:in-skin`, `swaps.skin/` = `skin.set/earglow7` 93/93), the
> user saw it and said *"earglow-7 ended up being incredible. Add that to the
> default effects I run."* `init.lua`'s `DEFAULTS.skinspec` is now the string
> `earglow7` — a rung id, because `sync_settings.sh` resolves `skinspec` to
> `skin.set/<name>` and `swaps.earglow7/` already carries the entire stack
> (the 16 v7 raygens plus `109`'s 77 curv compute modules). `make install`
> done; repo == `release/` == live CET == live `skin.set/earglow7` == live
> `swaps.skin/`, and the layer is byte-identical in all three places.
> `earglow7-ctl` is the previous default byte for byte and stays parked as the
> A/B control; `-ss`, `-hue1` and `-floor2` stay parked untried.
>
> **The read-out was LIVE only** — no frame was captured, so **none of §16's
> pre-registered rows have been read**, and §7's warning stands unresolved on
> screen: the shipped R/G 45 at the floor is above the 29 the model gives, so
> `-hue1` may still be the more *correct* rung. The user preferred 45 on sight,
> which is the standard this project ships on; §16 is owed, not void.

> **§0.1 first.** The 17:00 launch of `earglow7` and `earglow7-ctl` showed
> **no ear glow at all — not even the control's.** That was not the shaders.
> The launch-time sync **refused the rung and served nothing skin-side**,
> and the same defect has silently killed every raygen-bearing rung built
> since `109`, including all of `110`. Read it before reading any screen.

> **110 is superseded, not extended.** v5's cutoff/fade and v6's ladder are
> **not** in these bytes. The user's second message closed that line:
> *"if there is new modifications adding limits to the depth of transmittance
> and stuff like that, that all didnt work."* So query B's `tmax` is the
> shipped 18 mm, the floor is 101 §18's 6 mm, there is no cutoff and no fade,
> and gates 0/4/6 assert all four of those against the base.

## 0.1 The 17:00 launch: the rung was REFUSED, and so was everything in `110`

**Evidence, in order.** `status.txt` from the 17:00:02 launch:
`want_skinspec_req=earglow7` → `want_skinspec=off:gi-no-manifest`,
`want_ser=class`. The layer journal for that run: `swaps.skin/` served **zero**
files (`last_resolve` 77 is the *previous* run's number; this run's skin loads
were 0), the twelve `rgs_reference_main` ids came from **`swaps.ser/`**, which
is `ptq/rcbm/base` + SER hints built 2026-08-30 — **before the ear glow
existed.** `swaps.skin/` was empty on disk at 17:00:02.

**Mechanism.** `sync_settings.sh` calls a skin rung that ships `rgs_*` files a
*raygen-bearing rung* and, because such a rung owns ids that `ser` (above it)
and `ptq` (below it) also serve, it verifies provenance **every launch**: the
rung's `MANIFEST.txt` must carry `src_ser="…" ser_sha=… ptq_sha=…`, the shas
must match what is installed, and `ser` must not be `off`. Any failure →
`gi_refuse`: `swaps.skin/` is wiped, `skinspec` reads `off:gi-*`, and `ser`
is materialised over the top. My gate 10 wrote a fresh manifest that grepped
for those keys as *line prefixes*; in the base's manifest they live inside
the `# src:` line, so nothing matched, the manifest had no provenance, and
the rung was refused with no on-screen error.

**The same defect is in `110` and `105`.** `skin.set/earglow5`, `earglow6`
and `thinglow` ship no `src_ser`/`ser_sha`/`ptq_sha` either (`grep -c` = 0 in
all three). The journal has **no** `overlay_manifest` line naming any of
them. So `110` §14's "the v5 shot erased the effect" was **not** the 8 mm
cutoff — it was this refusal, and the v6 ladder was built on a misdiagnosis.
Those builds are not fixed here (not asked); the fix is the same three
tokens.

**Fix, gated.** Gate 10 now carries the base's whole manifest body through
(`build_curv.sh`'s stack pattern) so the `# src:` line — and its three
tokens — survive verbatim. **Gate 11 replays `sync_settings.sh`'s guard
against `$INSTALL_DIR`**: tokens present in all five rungs, `ser.set/class`
sha = `310513f3008cbde4`, `ptq/rcbm/base` sha = `55ed4e5c6884ab71`. Then the
game-dir `sync_settings.sh` was run exactly as the launch runs it:
`skinspec=earglow7`, `ser=class:in-skin`, `swaps.skin/` = 93 files, 16
raygens, **0 mismatches** against `skin.set/earglow7/`, `swaps.ser/` empty,
`ser.disable` present. That is the state the next launch inherits.

**What was ruled out, with what.** (i) The uncommitted `103` layer: it was
already the installed layer during the last run that *did* serve the glow
(journal run with `bda` events and `ser=0`, skin refmain 15). (ii) The sets:
`earglow7-ctl` is byte-identical to the curv default, whose 16 raygens are
byte-identical to `-cap6-glintdense`'s; `-glintdense` (no cap6) differs from
those only in the 6 mm floor on the 10 paintable raygens, compute identical.
(iii) The ear-vs-skin tissue question is moot for this launch — nothing was
served — and §7.3 answers it for the next one: the model's core already sits
at 0.2% blood, i.e. cartilage-like, so it *is* the in-betweener.

**Settings contract addition (§12): `ser` must be `class`,** not `off`. A
raygen-bearing rung is refused under `ser=off` (`gi-needs-ser`) because its
raygens carry the SER splices themselves.

## 0. The asks, verbatim

> "Mind tweaking the earglow to actually reduce the luminance of the sun and
> tweak the hue of the light based on the actual transmittance of skin? Think
> its possible to do with bounce light aswell?"

> "I need the default values we had before baked into
> `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv`,
> but just with better transmittance"

Three deliverables, and one of them is a question:

| ask | answer | where |
|---|---|---|
| "actually reduce the luminance of the sun" | the wrap's `SmoothStep(0, 0.35, -N·S)` **saturated at 1** over almost the whole pinna, so the entry-face Lambert factor was thrown away. Now `max(-N·S, 0)`. Up to **2.86× less** flux at the knee, more below it | §1.1, §3 |
| "hue … based on the actual transmittance of skin" | six lobe rates and two amplitudes **fitted to a layered skin slab** (Prahl haemoglobin + Jacques' skin fits, integrated over the sRGB bands). R/G at the floor **2.48 → 45** | §2, §4 |
| "the default values we had before … just with better transmittance" | red at the floor is held **bit-comparable to the default's 0.094542**. `k` is a normalisation, not a brightness knob | §5 |
| "possible with bounce light aswell?" | **yes, and it is the bigger win — but not in these bytes.** The transfer is source-agnostic; what is missing is a backside irradiance value. Three routes, one recommendation | §13 |

## 1. What was actually wrong

The shipped term is `k · 0.5(e^{-t/ld} + e^{-t/4ld}) · wrap · sunRadiance_c`,
clamped at 100. It already multiplies per-channel sun radiance — so the fix
was never "add the sun", it was **stop lying about how much of it gets in and
what comes out the other side**. Four defects, all in the same six lines:

### 1.1 The angular factor was a switch, not a cosine
`SmoothStep(0, 0.35, -N·S)` reaches 1 at `-N·S = 0.35` (70° off the normal)
and stays there. Everything from 70° to head-on gets **the same** flux.
Physically the entering irradiance is `S·cos θ`:

| `-N·S` | shipped weight | `cos` | cos/ss | chord of a 3 mm slab |
|---|---|---|---|---|
| 0.05 | 0.055 | 0.050 | 0.90× | 60.0 mm |
| 0.10 | 0.198 | 0.100 | **0.50×** | 30.0 mm |
| 0.20 | 0.606 | 0.200 | **0.33×** | 15.0 mm |
| 0.35 | 1.000 | 0.350 | **0.35×** | 8.6 mm |
| 0.70 | 1.000 | 0.700 | 0.70× | 4.3 mm |
| 1.00 | 1.000 | 1.000 | 1.00× | 3.0 mm |

The worst error is exactly where a backlit ear lives — grazing, `-N·S` 0.1–0.4
— and it is the "lightbulb" complaint's other half, the one 110 answered by
turning `k` down globally instead.

### 1.2 Jensen's `skin1` diffusion lengths are single-wavelength
`ld = (3.67, 1.37, 0.68) mm` are Jensen 2001's `skin1` values. A *renderer's*
red channel is a 300 nm-wide band centred at 601 nm (§2.2), not a
monochromatic 650 nm line, and its short-wavelength side is absorbed hard by
haemoglobin. Fitting the band gives an effective `ld_R` of **1.55 mm** —
**2.4× shorter**. That single number is why the shipped glow reaches through a
nose bridge: at 12 mm the shipped transfer still passes 0.24 of its peak.

### 1.3 The wide lobe was pinned at exactly 4·ld
Nothing measures that. Fitted, the second lobe is **1.33× ld₁ in red**
(1.160 → 1.549 mm), not 4×. The pinned 4× is what put a long, flat,
almost-undecaying tail under the whole term.

### 1.4 There was no per-channel amplitude at all
Only the rate differed per channel, so at the 6 mm floor the shipped R/G is
**2.48** — a warm cream. A 6 mm chord of real skin transmits R/G ≈ **29**. That
is the "too yellow … should be coloured more red" complaint, and it is not a
tint-knob problem, it is a *missing term*: broadband channels differ in
amplitude as well as in rate.

## 2. The model — `dev/transmit_model.py` (479 lines, offline, touches no SPIR-V)

### 2.1 Inputs, and their provenance
- **Haemoglobin.** `dev/data/hb_prahl.txt`, vendored: Prahl's compilation
  (omlc.org), Gratzer/Kollias, 250–1000 nm at 2 nm, molar extinction for HbO₂
  and Hb. `μ_a = 2.303 · ε · 150/64500` cm⁻¹ at 150 g/L, SO₂ = 0.75.
- **Everything else, Jacques 2013 "Optical properties of biological tissues:
  a review":** baseline `7.84e8 · λ^-3.255`, melanosome
  `6.6e11 · λ^-3.33`, reduced scattering `2e12 · λ^-4 + 2e5 · λ^-1.5`.
- **Geometry.** Per side: 60 µm epidermis at `f_mel` = 0.05, 500 µm dermis at
  `f_blood` = 0.02; the remaining core at 0.002. Beer–Lambert through the
  epidermis (it barely scatters at these thicknesses), diffusion
  `exp(-μ_eff x)` with `μ_eff = sqrt(3 μ_a (μ_a + μ_s'))` through the rest.
- **`--layer-mode scaled`** (fixed *composition* at every depth) is printed as
  the alternative and is **not** used: it makes blue 2.3× stronger and green
  5× weaker, which is a different-looking ear, and the fixed-skin-over-varying
  -core picture is the right one for a pinna.

### 2.2 Channels
Exact projection through the CIE CMFs into linear Rec.709 gives **negative**
green and blue for a deep-red filter (deep red is outside the sRGB gamut) —
true, and useless as a per-channel multiplier. So the channels are the
**positive part of the sRGB colour-matching rows, normalised to unit area**: a
non-absorbing slab then gives `T_c = 1` in all three and every `T_c` stays in
[0,1]. `--exact` prints the gamut projection alongside as the cross-check.

| ch | centroid | support |
|---|---|---|
| R | 601.2 nm | 400–706 nm |
| G | 540.7 nm | 468–607 nm |
| B | 451.8 nm | 380–514 nm |

CMF self-check: equal-energy white lands at x,y = 0.3331/0.3336 (exact
0.3333), a 6504 K blackbody at 0.3135/0.3237 (D65 is 0.3127/0.3290).

### 2.3 The fit
`A_c · 0.5(e^{-a₁d} + e^{-a₂d})`, log-space `least_squares`, 36 starts, rates
bounded to [10, 3e4] m⁻¹, fitted **over each rung's own [floor, 18 mm]** —
the range that actually renders. Three free parameters per channel, because
two (the shipped form, `A` pinned to 1) drives `a₁ → ∞`.

| ch | A | tint = A_c/A_R | a₁ (1/m) | a₂ (1/m) | ld₁ | ld₂ | log RMS |
|---|---|---|---|---|---|---|---|
| R | 0.5385 | 1.0000 | 861.72 | 645.76 | 1.160 mm | 1.549 mm | 0.018 |
| G | 0.0104 | 0.0194 | 845.89 | 622.22 | 1.182 mm | 1.607 mm | **0.225** |
| B | 0.0456 | 0.0846 | 1766.85 | 1545.23 | 0.566 mm | 0.647 mm | 0.053 |

**Green's fit is the weak one and it lands in the hue — read §7.2 before
believing the R/G figure.**

## 3. What moved in the shader

Six lines, one splice site, per raygen. Instruction census on the shipped
bytes, base → rung (gate 5): `+1 NMax, +1 OpExtInst, +2 OpFMul, +2 OpConstant`
= **+3 instructions, 7 constant rewrites, 2 new declarations**.

```
 %2973 = OpSelect %float %2970 %float_7_14967108 %float_n0   ; k, IN-PLACE (was 0.22)
 %2980 = OpFNegate %float %2979                              ; cos = -N.S
 %2981 = OpExtInst %float %1 SmoothStep %float_n0 %float_0_349999994 %2980  ; DEAD
 %2982 = OpExtInst %float %1 NMax %2980 %float_0             ; NEW: max(cos, 0)
 %2983 = OpFMul %float %2973 %2982                           ; W = k * cos   (repointed)
 %2984 = OpFMul %float %2957 %float_861_720276               ; t_eff * a1_R, IN-PLACE
 ...
 %3005 = OpFMul %float %3004 %float_0_0193633325             ; NEW: green's tint
 %3006 = OpFMul %float %3005 %2983
```

- `%2957` is the guarded thickness, `NMax(t, 0.006)` — **untouched** in every
  rung but `-floor2`.
- The rate constants are **in-place rewrites**, licensed by `rewrite_const`
  proving exclusivity first. `spirv-dis` renames them from their new values,
  so `%float_861_720276` *is* the constant that used to be `272.479553`.
- The `SmoothStep` is left in place as dead code: removing it would mean
  renumbering, and dead code costs nothing after the driver's DCE. Gate 8
  asserts the weight no longer reads it.
- **The clamp is `max(cos, 0)`, not the raw dot.** The gate's backlit arm can
  hand the transfer a cone-jittered sun vector, and an unclamped cosine there
  would *subtract* light. Decoys `cosraw`/`cosdot`/`cosboth` exist to prove
  the verifier can tell the three apart.
- Red carries **no** tint instruction (its tint is exactly 1 by construction);
  gate 7 asserts that, and decoy `notint` proves the check bites.

## 4. Nothing about the ray queries changed

Three inline queries, same flags, same order, same getters, same counts, same
`tmin`/`tmax`, same instance match, same sun-visibility test:

| | flags | tmin | tmax | purpose |
|---|---|---|---|---|
| A | 517 | — | — | primary reconstruct |
| B | **545** (cull-front) | 1.5 mm | **18 mm** | sunward thickness `t` |
| C | 517 | — | — | sun visible from the exit point |

Gate 0 asserts 3 `OpRayQueryInitializeKHR` / 3 `Proceed` / 2 `GetInstanceId` /
1 `GetT` on all ten paintable raygens **before** patching; gate 6 asserts the
same after. This is what licenses skipping the driver self-test (§9).

## 5. The normalisation, and why `k = 7.1497` is not a brightness knob

The user approved the default's brightness. So the rung's **brightest red** —
the value at its floor — is pinned to the default's brightest red:

```
shipped k·T_R(6 mm) = 0.094542      fitted T_R(6 mm) = 7.1209e-03
  =>  k' = 13.2768
  the SHADER's k = k' · A_R = 13.2768 · 0.5385 = 7.1497
```

`A_R` has to be folded into `k` because the shader's transfer is the **bare**
`0.5(e+e)` with only `A_c/A_R` carried as the tint. Miss that and the whole
term ships `1/A_R` = 1.86× too bright. Gate 8 recomputes the peak from the
constants it reads out of the `.spv` and requires 0.094542 ± 0.05%; it is what
caught the error.

Consequence: **red is unchanged at the floor in every rung**, whatever the
floor is, and what moves is hue and depth-shape only. Rec.709 luminance of the
term at the floor falls to **0.447×** the default — and that is *before* the
cosine, which takes another 0.33–0.50× off a grazing pinna.

## 6. The numbers, read back out of the shipped `.spv` (gate 9)

`earglow7`, fractions of the sun's own radiance per channel, at `cos = 1`:

| t | R | G | B | R/G | Y709 | Y vs default | R vs default |
|---|---|---|---|---|---|---|---|
| ≤6 mm | 9.454e-02 | 2.088e-03 | 3.599e-05 | 45.3 | 2.160e-02 | **0.447×** | **1.000×** |
| 8 mm | 2.403e-02 | 5.566e-04 | 1.514e-06 | 43.2 | 5.506e-03 | 0.157× | 0.315× |
| 12 mm | 1.657e-03 | 4.229e-05 | 2.865e-09 | 39.2 | 3.825e-04 | **0.019×** | 0.031× |
| 18 mm | 3.266e-05 | 9.634e-07 | 2.566e-13 | 33.9 | 7.632e-06 | 0.001× | 0.001× |

The nose bridge dies **on the exponential**, with no cutoff and no fade: 12 mm
of tissue now passes 1.9% of the luminance it used to. That is 110 §3's target
hit by physics instead of by a `tmax` edge.

`earglow7-floor2` (the only rung with a hue gradient, §7.1):

| t | R | G | B | R/G | Y vs default |
|---|---|---|---|---|---|
| 2 mm | 9.454e-02 | 6.528e-03 | 1.718e-03 | **14.5** | 0.516× |
| 4 mm | 2.170e-02 | 1.243e-03 | 6.113e-05 | 17.5 | 0.114× |
| 8 mm | 1.326e-03 | 5.461e-05 | 9.387e-08 | 24.3 | 0.009× |
| 12 mm | 9.063e-05 | 2.701e-06 | 1.622e-10 | 33.6 | 0.001× |

## 7. The blunt part

### 7.1 The hue gradient the user asked for lives **below** the 6 mm floor
101 §18's `NMax(t, 6 mm)` flattens every chord under 6 mm to one value, so
`earglow7` has **R/G 45.3 → 33.9 across its entire live range** — nearly
constant. Past the floor both R and G survive only via their long-wavelength
edges, so the ratio barely moves. *"Really shallow depth transmission should
still be coloured more red"* (110 §0) is **still unanswerable at floor 6**;
`earglow7-floor2` is the rung that answers it (14.5 → 33.6, and peak red still
0.094542). It is optional because 101 §18 chose 6 mm to stop a child's ear
blowing out, and that trade has never been re-shot.

### 7.2 Green's two-lobe fit is 1.6× off, and the error is *the hue*
Fitted vs the model it was fitted to, `f_blood` = 0.02:

| t | true R/G | shipped-constant R/G | fit err R | fit err G |
|---|---|---|---|---|
| 2 mm | 6.4 | 49.6 | 0.93× | **0.12×** |
| 4 mm | 15.2 | 47.4 | 0.95× | **0.31×** |
| 6 mm | **29.2** | **45.3** | 0.97× | 0.63× |
| 8 mm | 43.7 | 43.2 | 1.00× | 1.01× |
| 12 mm | 49.2 | 39.2 | 1.02× | 1.28× |
| 18 mm | 25.5 | 33.9 | 0.97× | 0.73× |

Red tracks to ±5% everywhere. Green cannot: a two-exponential sum has no way
to follow a curve that steep, and the residual shows up as **~1.55× too much
red at the floor** (45 shipped vs 29 physical). Two honest readings of that:
the direction is unambiguous (both are ~12–18× the default's 2.48), and
**`earglow7-hue1` (R/G 35.1) is closer to the physics at 6 mm than the default
rung is** — it is not merely "less red", it may be the more correct rung. If
`earglow7` reads as neon on screen, `-hue1` is the first thing to try, and the
model says that is the *right* reason to prefer it, not a concession.

### 7.3 Things this does not fix
- `t` is a **sun-path chord**, not a thickness (110 §14: a 3 mm pinna reads
  8.8 mm at 70°). The transfer is now correct *for the chord it is given*; the
  chord is still the wrong number to feed a slab model at grazing angles, and
  the cosine change partially compensates by accident, not by design.
- No Fresnel at either face (≈4% + 4%), no exit-face `cos`, no phase function:
  the diffusion factor `1/π` and those terms are all inside `k`, which is
  pinned to the old brightness anyway. **`k` is therefore not a physical
  quantity** and the doc should not pretend otherwise.
- Blue is essentially zero past the floor (3.6e-05 at 6 mm, i.e. R/B 2627 vs
  the physical 2433). If a screen read shows a **cyan** fringe somewhere, it is
  not from this term.
- Single skin type: `f_mel` = 0.05 is pale. §8's sweep says melanin barely
  moves the ratio (±4%), so this is less of a hole than it looks, but it has
  not been shot on a dark-skinned NPC.

## 8. Sensitivity — the honest bracket

The fit re-run over the two least-constrained inputs. `ld_R2` is the wide
lobe's length; `tint` is what the shader carries.

| f_blood | f_mel | ld_R2 | tint_G | tint_B | R/G @floor | R/G @12 mm |
|---|---|---|---|---|---|---|
| 0.010 | 0.02 | 1.539 mm | 0.0311 | 0.1497 | 34.1 | 35.8 |
| 0.010 | 0.05 | 1.542 mm | 0.0293 | 0.1279 | **35.1** | 35.8 |
| 0.010 | 0.10 | 1.546 mm | 0.0266 | 0.0985 | 36.8 | 35.6 |
| 0.020 | 0.05 | 1.549 mm | 0.0194 | 0.0846 | **45.3** | 39.2 |
| 0.030 | 0.05 | 1.554 mm | 0.0145 | 0.0592 | 53.9 | 41.6 |
| 0.050 | 0.05 | 1.562 mm | 0.0099 | 0.0318 | 67.6 | 44.6 |

**The rate is the robust part and the tint is not.** `ld_R2` moves 1.5% over a
5× range of dermal blood; the tints move ~3×. So §1.2's shorter red — the
thing that kills the nose bridge — is safe, and the hue is a **choice inside a
bracket**, which is exactly why `-hue1` exists as an A/B rung and not as a
second guess baked into one build.

## 9. Gates

Eleven, all offline, `dev/build_earglow7.sh`:

| # | gate | what it proves |
|---|---|---|
| 0 | base provenance | 77/4/12 modules, 10 paintable refs, 3/3/2/1 query census, and **all nine shipped constants present** (`0.22`, `0.018`, `0.006`, the six rates, the `0.35` knee) — i.e. the base is the untouched default and has not been through 110 |
| 1 | round-trip | `spirv-dis` → `spirv-as` byte-identical on 10/10, so a byte diff means the patch and nothing else |
| 2 | model | three JSONs emitted; `k`, tint ordering, `a₁ > a₂`, and `a₂ ≠ a₁/4` asserted |
| 3 | patch + assemble | 93 modules per rung, `spirv-val --target-env vulkan1.4` clean on all 465, live rungs differ from the base, the control does not |
| 4 | coverage | all 10 modules agree on instruction count, rewrite count, `k` and tint; `query_touched == nothing`; **cutoff `None`, fade `None`, `tmax` 18 mm** |
| 5 | instruction census | op-by-op delta vs the base on the **shipped bytes**: `{NMax 1, OpExtInst 1, OpFMul 2, OpConstant 2}`, identical across modules |
| 6 | identity | 81 non-raygen modules and both pass-through raygens byte-identical; `--control` asserts all 93 |
| 7 | verifier | `verify_earglow7.py` on the shipped `.spv`, 10 checks (§10) |
| 8 | non-vacuity | 10/10 base modules rejected, **9 decoys rejected each by its intended check**, 3 cross-reads between rungs rejected |
| 9 | closed-form | the transfer re-derived from constants **read out of the `.spv`** by an independent reader, and peak red asserted at 0.094542 |
| 10 | MANIFEST | the base's manifest body carried through, so `src_ser`/`ser_sha`/`ptq_sha` survive; content sha per rung |
| 11 | launch contract | **replays `sync_settings.sh`'s raygen-bearing-rung guard** against `$INSTALL_DIR`: tokens in all five rungs, `ser.set/class` and `ptq/rcbm/base` shas match. §0.1 |

Decoys, each rejected by the named check: `flatk` (9), `flatrate` (6),
`notint` (7), `tintswap` (7), `rateswap` (6), `cosraw` (8), `cosdot` (8),
`cosboth` (8), `wide4` (6).

## 10. `verify_earglow7.py` — the ten checks

1. Query census and flags 517/545/517, `tmin` 1.5 mm, `tmax` **still 18 mm**.
2. **No cutoff, no fade**: no `SmoothStep` anywhere on a thickness value.
3. The floor `NMax` on the guarded `t` equals `--floor`.
4. The accept still reaches the instance `OpIEqual` and query C's
   `OpLogicalNot`; the false arm is still negative zero.
5. **Channel identity from the sun-radiance `OpCompositeExtract` index**, not
   from the rates. 110's "narrow rate increases R→G→B" tie-break is *actively
   wrong* here: fitted red and green are within 2% and **red's is larger**.
6. The six rates equal the model's, the wide lobe is not `a₁/4`, and the
   narrow rate is not the shipped `1/ld`.
7. The tint is the fitted amplitude and **red carries none**.
8. The angular factor is `NMax(FNegate(Dot), 0)` and the `SmoothStep` is dead
   (or, under `--angular smoothstep`, the weight reads the `SmoothStep` and it
   has exactly one consumer).
9. `k` matches, and the closed-form peak red recomputed from the shipped
   constants is within 0.5% of 0.094542.
10. Subsequence check with the expected inserted-instruction count.

## 11. No driver self-test, and what licenses skipping it

Nothing about traversal changed — same three query objects, same flags, same
getters, same counts, same `tmin`/`tmax`, asserted before and after by gates
0/4/6. `dev/selftest_earglow_rq.sh`'s case A/E claims already cover these
bytes. What changed is arithmetic on values the queries already returned, and
arithmetic is what gates 5/7/9 read straight out of the `.spv`.

## 12. SETTINGS CONTRACT — state this **before** the launch, not after

The ear glow lives in the **path-traced reference raygens**. It cannot appear
without:

- **Path tracing ON** (`RT: Overdrive`). RT-without-PT does not run these
  modules.
- **Direct sunlight on the far side of the head.** Query C requires the exit
  point to see the sun; in shade the term is **exactly zero** (this is §13's
  whole motivation).
- **The same NPC, the same head angle, the same time of day** across rungs.
  `earglow7-ctl` is byte-identical to the standing default, so shoot it in the
  **same** session as the "before".
- **`ser=class` on the CET page.** §0.1: under `ser=off` the rung is refused
  as `gi-needs-ser` and nothing skin-side is served.
- **After the launch, read `status.txt` before reading the screen:**
  `want_skinspec=earglow7` (not `off:gi-*`) and `want_ser=class:in-skin`.
- **DLSS/FSR frame generation off**, or the A/B is a comparison of two
  different reconstructions.
- Everything else at whatever the previous default was shot with; only the
  `skinspec` selection changes.

Frame to shoot: backlit head, sun near grazing, with an **ear**, the **nose
bridge** and a **nostril** all in one shot. Then the same frame on a child NPC
for `-floor2`.

## 13. Bounce light — the answer

**The transfer is already source-agnostic.** `T_c(t)` is one multiply against
whatever radiance you hand it; nothing in §3 knows the light came from the sun.
So "possible with bounce light" is not a transfer question at all, it is an
**irradiance-availability** question, and right now the answer is that the
raygen has exactly one backside irradiance value — the sun — and no other.

That is worth fixing for a reason bigger than the original ask: **the term is
exactly zero whenever query C fails.** Overcast, shade, interiors, a head lit
by a neon sign — every one of those is a case where real ears glow and this
effect renders nothing. Sun-only translucency is arguably the largest
remaining error in the term, larger than anything §1 fixed.

Three routes, in cost order:

| route | what it needs | cost | verdict |
|---|---|---|---|
| **(a) one extra shaded ray from the entry point along `-N`** | a real `OpTraceRayKHR` with a payload, not an inline query — inline queries return **geometry only**, no radiance. The v1 patcher (`patch_earglow.py`) already proved payload-radiance retrieval works at this splice site | 1 ray/skin pixel, and it is a *shaded* ray, so it is the expensive kind | **the recommendation**, but as its own handoff. It is the only route that gets the real thing: incident radiance from the actual far side |
| **(b) the ReSTIR-GI resolvers** | an indirect radiance triple already exists there, and 103 Stage 2c proved a **compute-side inline ray query** works, so thickness is obtainable. But a compute resolver has the *near* side's normal and would have to approximate the far side with it | near-zero extra rays; reuses reservoirs | **the cheap 80%**. Wrong in principle, probably right on screen, and it is the only route that runs in the compute half where the bleed/curvature terms already live |
| **(c) a transmissive BSDF lobe** | `patch_refract_absorb` territory: make skin's BSDF actually transmit, so *every* light path carries it | invasive; changes the material everywhere, including where it looks fine now | **no**, not as the next step |

Do **not** attempt (a) or (b) in the same build as this one. §1's four fixes
are a hue-and-falloff change with red pinned; adding a light source on top
makes the A/B unreadable. Shoot §12's frame first, get a verdict on the
transfer, *then* pick a route.

Two things to carry into that work:
- **The gate is `find_path_counter`, not `find_bounce_counter`** — checked. So
  there is no per-bounce compounding to unwind first.
- If (b) is chosen, the same `A_c`/`a₁`/`a₂` constants apply unchanged: they
  describe the *slab*, not the light.

## 14. What is NOT done

- **Nothing on screen that means anything.** The 17:00 launch served no
  skin-side module (§0.1); zero of §16's rows have been read.
- `110`'s and `105`'s manifests still lack the provenance tokens and will be
  refused the same way until rebuilt with them. `--install` was run, so the
  rungs are live in `~/.local/lib/callisto/skin.set/`, and `init.lua` lists
  them; nothing is committed.
- The bounce-light routes in §13 are analysis, not code.
- `-floor2` has not been checked against a child NPC, which is the entire
  reason 101 §18 put the floor at 6 mm.
- `--layer-mode scaled` and `--exact` are printed and unused.
- No dark-skinned NPC read (§7.3).
- `earglow7-ss` exists only to isolate the cosine; if `earglow7` wins outright,
  `-ss` can be deleted.

## 15. Files

| file | lines | role |
|---|---|---|
| `dev/data/hb_prahl.txt` | 382 | vendored haemoglobin extinction, with provenance header |
| `dev/transmit_model.py` | 479 | the model; `--emit` writes the JSON the patcher reads |
| `dev/patch_earglow7.py` | 377 | the patcher; imports `patch_earglow5`'s primitives, edits nothing else |
| `dev/verify_earglow7.py` | 433 | independent verifier, 10 checks, `--negative` / `--control` / `--expect` |
| `dev/build_earglow7.sh` | ~520 | the eleven gates, `--install` |

Rungs and content shas:

| rung | content sha | what it is |
|---|---|---|
| `earglow7-ctl` | `024998da26d84333` | **= the standing default, byte for byte.** The "before" |
| `earglow7` | `1d28a6adae300c9b` | the pick: fitted rates + fitted tint + `max(cos,0)`, floor 6 |
| `earglow7-ss` | `ab80503dc86dd86b` | angular axis: the old saturating `SmoothStep` kept |
| `earglow7-hue1` | `728b63de50c2a6a5` | colour axis: `f_blood` 0.01 → R/G 35.1 (and §7.2 says this may be the *more* correct rung) |
| `earglow7-floor2` | `a7a1c328bc56f1b7` | depth axis: floor 2 mm, the only rung with a hue gradient |

## 16. Pre-registered interpretation

Write the verdict against these **before** looking, or the read is worthless.

| what you see | what it means | what to do |
|---|---|---|
| `earglow7` reads as a dim red rim where the default read as a warm lightbulb | both fixes landed | keep it; take §13 next |
| still too bright | the cosine is not enough and `k` is genuinely too high | `k` is one in-place rewrite; the *level* is now decoupled from the *hue*, so a new rung is minutes |
| too red / neon | §7.2's green residual, exactly as predicted | `earglow7-hue1`. If that is still too red, the two-lobe form is the limit and a third lobe is the fix |
| no change from `-ctl` | the selector or the install, not the shaders — gate 9 read these numbers out of the shipped bytes | `cmp` the installed set against `swaps.earglow7/`; re-read the deploy check |
| `earglow7-ss` indistinguishable from `earglow7` | the pinna never grazes in this frame | reshoot with a more grazing sun; the cosine's whole effect is at `-N·S` < 0.4 |
| the nose bridge still glows | the chord, not the transfer (§7.3) — 12 mm now passes 1.9% of the old luminance, so if it is still visible the chord is short, meaning the geometry is thinner there than assumed | measure it with `earglow-rq3-hit` before touching the transfer again |
| `-floor2` blows out a child's ear | 101 §18 was right | drop `-floor2`, and accept that "shallow = redder" is unavailable |
