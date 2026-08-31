# CallistoSSS — current state (2026-08-31, after the four-launch gate night)

One page. Everything here points at the document with the evidence. The rule
this project keeps relearning: *built*, *loaded* and *swapped* are not
*working* — only an on-screen A/B is.

**Newest first (2026-08-30 23:57 → 2026-08-31 01:46, five launches; then the
2026-08-31 14:17 oil+fuzz build, its first look, the 14:57 rebuild, its
launch, and the 15:57 half-oil + bounce-bleed rebuild):**

- **USER VERDICT ON THE STACK: KEEP IT. Fuzz "incredible like 99 percent
  of the time" — the sun-only gate was requested, PROVEN feasible, then
  withdrawn and parked (`75`).** The indoor complaint (16:32 screenshot,
  verified served `gi-50b-bleed-oil-sheen`) prompted "make the fuzz
  sun-only"; the discriminator was established by census — unlooped GGX
  sites read an exclusive bindless-cbuffer slot 5 (the sun direction) in
  75/76 U-bearing modules, looped light-list sites never do — and then the
  user reversed: keep as-is. Nothing to undo (investigation was
  read-only). Discriminator + exceptions (`ab0bc2fe` 0 U sites,
  `99bb7c26` unprovable) + build sketch recorded in `75` so it's a
  one-session build if ever wanted. Everything below committed + pushed
  at the user's request.
- **73's candidate WINS with two dials and one structural gap — half oil,
  half fuzz, and the BLEED NOW RIDES BOUNCE LIGHT. Built + parked + deployed
  15:57, unlaunched (`74`).** User on `gi-50-bleed-oil-sheen` (launch
  verified via status.txt; the oil's first time on screen): *"literally
  perfect... except I need about half the amount of oil"*, baby hairs too
  strong in dim light, *"skin is becoming hazy and loses that rosy tint in
  dim lighting/indoors"*, and — the user's own diagnosis, correct — *"make
  sure that bounce lighting is hitting the baby hair sheen/proper-bleed-
  skin-shader/oil aswell"*. It wasn't hitting ANY of them: bleed/oil/fuzz
  all ride the compute modules' direct-light term. The indoor haze is three
  achromatic mechanisms stacking (`74` §0), and the rosy-tint loss is the
  bleed diluting exactly where bounce dominates. Changes: (1) half oil =
  `real-gloss-bleed-oilh` (n_s 0.55 → grazing F +22% not +52%; cap 0.45 →
  bites only authored roughness >0.538 at 1.55× not 2.5×); (2) fuzz
  `k_peach` 1.0 → **0.5**, the new default (hemisphere median 0.72%, max
  79% of local diffuse); (3) **`gi-50b`** = gi-50's raygens + the `53`
  closed form at the ST pair's own tail NoL — the terminator bleed on
  bounce light, channel identity walked to the albedo fetch and asserted
  {0,1,2} (die-on-guess), emitted math machine-evaluated 28/28, `--bleed 0`
  byte-inert vs parked gi-50. Oil and fuzz CANNOT ride bounce and there is
  nothing to ride: no view vector exists in the diffuse raygens (`50` §3)
  and the GI spec family's share is nil (`50` §2) — documented, closed.
  Rungs rebuilt IN PLACE (candidate + both attribution rungs at half
  levels); 73-era candidate parked as `…-oil-sheen-hot`;
  **`gi-50b-bleed-oil-sheen` is the indoor-depth candidate** — 2 raygen
  files from the rebuilt candidate, compute byte-identical.
  `verify_gi_ladder` ALL PASS both bases; sync accepted both candidates;
  live selection unchanged, so a relaunch shows the halving with no setting
  change. A/B runbook + pre-registered failures: `74` §5. **Shoot a DIM
  INTERIOR face for the gi-50b pair — direct sun is predicted to not move.**
- **The blown rim was the module's own FRESNEL, not the lobe — cancelled at
  the rim only; both added-lobe rungs rebuilt in place (`73`).** First
  on-screen read of `72`'s build: *"a bit too blown out. Losing the nicer
  deep red"*. `72` §7.1 had pre-registered exactly this, at exactly these
  pixels — the splice sits upstream of the module's Schlick multiply, and F
  runs 0.028 in the front-lit sheen band to **0.87 on a backlit rim**, a 30×
  amplification of a term that has nothing to do with Fresnel, painted white
  over the pixels where the terminator bleed's red lives. (`NoL` cancels out
  of fuzz/diffuse, so that swing is *all* Fresnel — the mechanism is not a
  guess.) Fix: multiply the lobe by `w = 1 − (1−VoH)^5` at the splice, where
  **`VoH = (NoL+NoV)/(2·NoH)` is exact** (unit bisector) and symmetric in the
  two cosines, so it holds at all 457 sites including the 56 unlabelled
  cheap-Vis ones; plus `peach_max` 1.0 → 0.5. Net weight is **1.00× wherever
  VoH ≥ 0.8** — the cheek/jaw response is unchanged to 4 decimals; hemisphere
  median 1.45% → 1.45%, p90 8.0% → 7.9%, **max 781% → 159%** of the local
  diffuse (worst-pixel add 0.0217 → 0.0088). Works on the oil rung too
  (0.45×/0.24× at VoH 0.1/0.05 under its reshaped Fresnel). `k_peach` stays
  1.0 deliberately: the complaint was the peak, not the level. New build gate
  — β must agree across modules and **457 of 457** sites must carry the
  weight, or the build fails. `gi-50-bleed-sheen2` and `gi-50-bleed-oil-sheen`
  rebuilt **in place** (same selector ids); the 72-era bytes parked and
  selectable as `…-wide` because targeted-vs-wide is now the A/B. verify →
  ALL PASS on six rungs. **Shoot a BACKLIT face — a front-lit A/B will show
  nothing, and that is the prediction.**
- **Peach fuzz was invisible BY CONSTRUCTION; rebuilt as a real lobe, and an
  OIL layer added — BUILT + PARKED + DEPLOYED, unlaunched (`72`).** The user's
  A/B call on `gi-50-bleed-sheen` (*"extremely subtle"*, vanilla skin *"looks
  super dry"*) is exactly what its arithmetic predicts: the 58-era rung is
  **multiplicative**, and measures **1.0000–1.0466×** over the whole face
  (1.24× only within ~2° of silhouette). No `k` fixes that — a factor cannot
  create the grazing energy GGX has none of. Rebuilt as the same Charlie ×
  Neubelt lobe **ADDED** at the site's own `D·Vis`, class-1 gated, carrying
  the site's **own** light cosine so it dies at the terminator (401 sites fold
  the true `NoL`; 56 cheap-Vis sites fold `min(c0,c1)`, conservative). Code
  review found four defects, one real: **16 bare `OpDot` cosines** drove
  `V_neubelt` to its ceiling on backlit skin — the `69` "lightbulb" waiting to
  happen; now clamped, and only where `_in_unit` cannot prove saturation (all
  104 `OpPhi`s pass). Amplitude calibrated offline against the one on-screen
  anchor — `58`'s `k=8` probe computes to 316% of local diffuse ("blown
  white"); shipping `k=1.0` gives 0–2% head-on, 5–17% on a cheek rim, 35–53%
  on the last degree of silhouette (`dev/fuzz_model.py` prints all of it).
  The **oil** is the tier-3 gloss that has been inert in every `gi-*` rung
  (`G0` is the identity): `n_s=0.60, alpha_max=0.16` → mirror-band highlight
  1.20–1.28× tighter/brighter, grazing F +52% at 60°. Three new rungs form a
  one-variable ladder off `gi-50-bleed`: **`gi-50-bleed-oil`**,
  **`gi-50-bleed-sheen2`**, **`gi-50-bleed-oil-sheen`** (the candidate).
  `./dev/verify_gi_ladder.sh` → ALL PASS (16/16 raygens byte-identical to
  `gi-50` in every rung, 77/77 compute deltas pairwise, `gi_refuse`
  provenance clean). **Live `brdf_params.txt` has `skin=off` — these are dead
  until it is `on`**; full required-settings block in `72` §6. Nothing on
  screen yet; do not promote any of it without a launch.
- **Ear glow v5 BUILT and PARKED, unlaunched — the ray is FLIPPED (`70` W1,
  build `71`).** The reversed segment — v1's founding assumption and the
  material blindness every gate generation patched — is replaced by a
  sunward trace from the module's own NEE origin/direction VERBATIM,
  CullFront (32), tmax 18mm: the first hit is the flesh's far wall seen
  from inside, a backface at t = the TRUE sun-path thickness. Leak classes
  die by geometry (card backface < 1.5mm floor; face-behind-strand finds
  no backface through the head); **the consistency gate exits the design**.
  Albedo (0.25) + vis ray kept. W3 rides along: `-lo` = W1 + raw
  Beer–Lambert (isolates the flip), `earglow` = dual-exp transfer (red
  ~2× over 1–6mm, not ~20×) + smoothstep backlit wrap 0.35, `-hi` =
  wider lobe + wrap 0.5. All k=0.22 — the ladder is design, not strength.
  Pre-registered falsifier: all-dark = BVH strips interior backfaces →
  revert v4 (git) + s-band probe. Probe semantics under a REBUILD are now
  v5 (RED = floor, not cons); the parked probe rung is still v3's. `71`
  §5 is the outcome table. W2 (jittered entry) not built. One launch,
  contract unchanged (ser=class, shadowset=full-shadow, ptreg ON).
- **Ear glow: nose + coverage WIN (v4), sliver leaks RETURN + "lightbulb"
  transfer look; two tracks proposed — `60`→`69`.** `earglow-hi`
  (user-run, 01:46, serve + settings verified): glow under clothing, at the
  hair seam, in eye corners, on lit skin, on occluded ears. Three
  structural defects — the thickness ray is material-blind, local
  thickness ≠ sun-path transmission, and the backlit gate opens in
  shading-normal crevices on lit faces. NOT the polarity bug (verified in
  the deployed binary) and NOT `39`'s two defects — both stayed dead. The
  mechanism half is a win: an injected trace at a NEW site with overridden
  operands executes and round-trips CHS hit distance, closing `56`'s
  scope limit for this family. Routes priced in `60` §5; the (b) read is
  DONE — (b)-as-specified is dead (`61`: the reference CHS carries no
  identity; the instance-writing CHS is live-PT's). V2 = (a)+(b‴) (`62`)
  **LAUNCHED 08:01 and it mostly WINS (`63`)** — user: *"AGONIZINGLY
  CLOSE… OTHERWISE IT LOOKS PERFECT"*; five artifact classes down to
  three, all pixel↔primary boundary leaks (hair strands, collar top edge,
  fringe-over-forehead — `63` §1 has the unifying mechanism). V3 LAUNCHED
  08:43/08:47/08:53 (`64` built it, `65` scores it): **leaks DEAD** (strands,
  collar — consistency gate, attribution forced), but the gate **eats the
  feature** — glow survives only at the concave ear crease; helix rim, ear
  top, nose all gated off. k-invariance (user's own hi run) proves gated-
  not-dim. Two suspects, inseparable this launch: flat ε=5mm vs grazing
  footprint (kills rims structurally, `65` §1 math), and albedo 0.10 vs
  tattoo/texture (`64` §5's own envelope; S3's ear is tattooed). NEXT =
  attribution probe LAUNCHED 09:29 and it ANSWERED (`67`): the ear kill
  is cons AND albedo jointly (yellow, B=0.0); the cons compare fails
  FLAT-ON at ~2 m (night red) ⇒ distance-scaled bias ~3–5 mm/m, grazing
  theory demoted; vis + thin-hit physics-correct (magenta cleavage,
  unpainted thick neck); nose FIRES (sunward nostril blue). v4 BUILT and
  LAUNCHED 10:52 (`68` build, `69` result): offline bias read found the
  error is LATERAL registration, removed by projecting onto the view ray —
  one-sided distance-aware ε, albedo back to 0.25. On screen: nose WINS,
  ear coverage up, but strand/collar leaks RETURN (registered row — v4 is
  the first honest leak test) and the look failure changed species:
  single-tap Beer–Lambert + binary gates pool glow into a "lightbulb
  behind the ear" (`69` §1). Proposed, NOT yet delegated (`69` §2):
  Track L = s-band probe (measures leak-vs-truth separation), Track D =
  diffusion transfer + wrap-envelope A/B ladder. **No blind ε tuning**
  (`64` §8 row invoked). **Do not tune k.** Selector stays `gi-50-bleed`
  between looks.
- **G-U5 PASSES — `56`.** A new static `OpTraceRayKHR` spliced into a raygen
  **executes** and round-trips a payload written by the pipeline's own CHS.
  **Traced-thickness ear glow (`51` §7 step 3) is unblocked** — that is now a
  *build*, not a gate. `GOTCHAS`' flat "a second trace does not execute" is
  **overturned** (it was one sample in the shadow family with hand-picked SBT
  indices; H2 dead, H3 was the cause). Two limits: the **miss** leg is not
  established (rung A dark), and only the **reference raygen** family was
  tested.
- **G-U4 opens but is coarse — `57`.** The sub-enum is readable from compute,
  but **chrome has no subtype ⇒ A8 is DEAD**; **skin does not split ⇒ question
  (c) answered *no*** and `c1sub` need not launch; hair carries ≥2 subtypes,
  corroborating `54`. A2/A3 was confounded by the `both` merge — then
  **answered YES by `probe-sheen` an hour later (next bullet)**.
- **A2/A3 answers YES — `58`.** The user ran `probe-sheen` alone (00:47,
  serve audit-verified, settings pinned): white grazing sheen on clothing,
  vegetation and skin — the pre-registered "rim on everything" row. The
  specular-site family is alive, `40` §10's doomsday null is dead, and
  **A3 peach fuzz is now a build** (class-1 gate + `0d` bounds, one
  variable at the standing base). The ear-glow build landed the same night
  (`59`) — and **failed on screen an hour later (see the bullet above)**.
- Doc fixes applied the same night: `55` §5 said `ptreg` **off**, which would
  have refused the rung (`gi-stale-ptq`) — it is `ptreg` **on** (`56` §6).

**Next model: read `47-PROCESS-TRACE.md` first — it is the whole 2026-08-30
afternoon in one document (eight launches, what was decided and why, what was
withdrawn, and the eight places it is weakest). Then `46` §18 → §17 → §14 →
§13 → §12 for the evidence behind it. The L-queue is done (L1–L8); only the
real L4 (RR off, two launches) is unrun.**
`46` §1–§10 is the older record of six launches, peer-reviewed in §9 and then
**largely overturned by §11–§18**. Do not believe any figure in §5 or §6.2
without reading §13 first — they straddle a renderer regime break. §11 is
itself partly withdrawn.
`44` is what was built and what was wrong before. This page plus those files
resumes the work with zero prior context.

## Ships and is confirmed on screen

| feature | switch | doc |
|---|---|---|
| SSS diffusion kernel, `detail` preset (engine radius; shipped one was 10×) | `kernel=detail` (selector since 44) | `33` §1 |
| Skin BRDF tier-1 `c1` in the compute resolvers — **confirmed on screen, but on directly-lit skin only** (`46` §14: +1.8% above ~106 lum, nothing below; `46` §12/L2: the class gate passes, but the painted modules write the direct-light term only). Bounce-lit skin reached separately by `gi-50` below — `42` **closes**. | `skin` | `02`, `03`, `46` §12, §14 |
| **`skinspec=gi-50`** — real-gloss + class-gated `c1` on the ReSTIR-GI diffuse raygens. **Standing rung, decided on screen 2026-08-30 night** (`50` §6): user prefers it over `R2-real-gloss` (*"more complexity in the shading of the face"*); S3 corroborates (+1.2..1.8% face lum vs three matched controls, achromatic, structured toward the bounce-lit lower face). Needs `ser=class` (in-skin) + `shadowset=full-shadow`; sync refuses otherwise. | `skinspec=gi-50` | `50` |
| Hair shadow-leak fix, direct shadow rays only | `shadowcull` / `full-shadow` | `26` §7 |
| PT: bounce cull mask 1→255, reflection mask, firefly clamp | `ptbounce`, `ptrefl`, `ptclamp` | `26` §4 |
| MS-GGX rough-metal energy compensation | `ptmsggx` | `28` |
| AgX tonemapper, HDR and SDR, over the authored area LUTs | `dev/install_agx.sh` | `21` |

## Ships, default off, unproven — the A/B queue (`45`)

| feature | rung(s) | doc |
|---|---|---|
| Skin **realism** axes: roughness scale, energy coupling, micro-shadowing, wet eyes; combined as `real` / `real-gloss` | `skinspec=` 9 new rungs | `44` §1, §3 |
| Oily/wet skin gloss ladder (roughness *ceiling*, flattens variation) | `skinspec=subtle…extreme` | `33` §2 |
| Peach fuzz (added Charlie×Neubelt lobe, class-1 gated, **Schlick ramp cancelled**, now at **half strength**) and the **half** oil layer, as a one-variable ladder off the standing `gi-50-bleed`. The 73-era full-strength candidate won its A/B modulo "half the oil / too hazy in dim light" and is parked as `-hot` | `skinspec=gi-50-bleed-oil` / `-sheen2` / `-oil-sheen` (+ `…-hot` = 73 levels, `…-wide` = the 72-era rim) | `72`, `73`, `74` |
| **Terminator bleed on BOUNCE light** — the `53` closed form at the ReSTIR-GI ST pair's own tail NoL, so the rosy terminator cue survives indoors where bounce dominates. `gi-50b` = bounce bleed alone (attribution); `gi-50b-bleed-oil-sheen` = **the indoor-depth candidate**, 2 raygen files from `gi-50-bleed-oil-sheen` | `skinspec=gi-50b` / `gi-50b-bleed-oil-sheen` | `74` |
| Peach fuzz, 58-era **multiplicative** form — measures 1.00–1.05× on the face; superseded, kept only for reproducibility | `skinspec=gi-50-bleed-sheen` | `58`, `72` §1 |
| SSS kernel presets `balanced` / `callisto` / `vanilla` (tooling check) | `kernel=` | `44`, `33` §1 |
| Sun angular size / visibility / scattering (live CVars) | PT panel | `44`, `43` M3 |
| SER restoration — now selectable from CET, and no longer un-patches ptq | `ser=class…` | `41`, `44` §2.1 |
| Path regularization (`ptreg`) | on in the user's file | `24` |
| Engine CVar panels (hair 40, skin 17, PT 15, detail 22) | live | `16`, `27`, `32`, `33` §3 |

## Measured — 14 launches, 2026-08-30 (`46` §11–§18; decision trace in `47`)

- **The ledger's headline numbers are gone.** A **renderer regime break** at
  ~13:30 (`46` §13) moved static geometry +12–19% in fine energy and stayed
  there, so every E1-baselined figure in §5 straddles it: the "+35/+48%
  texture" rungs, the "−16% default stack", the S3 regression. Re-measured
  inside one regime with a **non-skin control**, all three are inside the
  floor. §11's own "58% noise floor / Ray Reconstruction resolves different
  pores" was the same mistake one level up and is withdrawn (`47` §2, §4).
- **What replaced them.** With vanilla replicated on both sides (`46` §17):
  the mod brightens **only the lit half of the face**, switching on at ~106
  luminance, and costs **no** S1 skin texture. Two instruments agree on the
  threshold — the class probe measured ~116 (`46` §12/L2) from paint, the
  radiometric pass ~106 from tone bins.
- **`42` does not close.** `skinspec=probe-cls` painted 25.8% of S1 skin and
  **0.0%** of S2 skin. The class gate passes; the painted modules write the
  **direct-light term only**, so bounce-lit radiance comes from a writer
  outside the 77 anchored modules. §6.1 hypothesis (b) confirmed, (a) dead.
  The phi-lift commit did not achieve its goal. ~~Next step is a static
  search~~ **Done that night: the writer is not a compute module at all —
  it is the ReSTIR-GI diffuse raygen pair (`48`/`50`), and `42` closes via
  `gi-50` (confirmed table above).**
- **Material classes confirmed on screen:** skin 1, hair 4 (eyelashes
  included), plants 5, **eyes 8** (sun-clipped catchlights only — 30 px above
  the null's max, blue ×2.82 against the palette's ×3.0).
- **The one replicated effect of the day is `ptbounce`** and its sign is
  positive (`46` §18): −9.9% scene-wide fine energy in dim light, 7.3× the
  within-cluster spread, no overlap, one switch spanning the whole gap. That
  is **GI convergence, not detail loss** — the metric scores an improvement
  as a loss. User's unprompted verdict: *"I like PT bounce… the effect is
  super subtle."* It stays on, and it closes the
  `42`/§6.2 thread: the §6.2 skin-texture claim (regime artefact), the
  `ptclamp` mechanism it spawned, and `ptreg` all died — the last two by
  pre-registered predictions that failed.
- **Metric floors, measured** (same config, two launches): S3 non-skin
  **0.3%**, S1 non-skin **~3%**, S1 skin **~6%**, S3 skin **~9%**. All
  S3-**skin** figures are withdrawn on that basis (`46` §16.2). Region choice
  matters more than metric choice.
- **`46` §12 (static, no launch)**: `ab0bc2fe` — named in §9 as one of "the two
  GI resolvers" — writes an **integer sample-index buffer, not colour**. 76 of
  the 77 anchored modules write `v4float`; it writes `v4uint`. So there is one
  colour-writing resolver, not two, the tier-1 `c1` spliced into it cannot
  brighten a pixel, and §6.1's "an unanchored module shades this scene" is now
  the favourite.
- **Direction: `real-gloss` — decided on screen 2026-08-30 evening (`49`).**
  Three launches, one variable, camera pixel-identical, settings pinned,
  control shot in the same session: `real-gloss` beat `real` and `off` in all
  three scenes. User: *"no contest… the off setting looks like plastic."*
  This **overturns** the old `rough-1.3` direction (`46` §11.5), which was held
  on an earlier reaction and the `33` §2 argument, not on numbers — the E2a→E2b
  differential it rested on straddled the regime break. See `49` §4.

## Still unlaunched

Collapsed by the peer review (`47` §11): the radiometric-ledger phase is
over — the eye is the instrument for direction, probes and the serve audit
for reach. In order of look-payoff:

1. ~~**GI-writer probe + splice**~~ **DONE 2026-08-30 night (`50`).** The
   probe named **ReSTIR-GI diffuse** as the bounce-lit skin writer (`50`
   §2); the Site A splice launched and **won the A/B** — `gi-50` is the
   standing rung (see the confirmed table; `50` §6 for the S3 numbers and
   the two disqualified scenes: S2 crowd drift, S1 sun drift — a
   cross-session pair only lighting-matches under stationary light).
   Three `48` §9 claims died on the way (no NoV in scope, NoL not at the
   write, spatial≠spatiotemporal shape) — `50` §3 before touching those
   modules again. Left parked: `gi-100` (one look if the user wants it
   louder), reference-green Site B (only after an observation demands
   it), the spec family (nil share).
2. ~~**One eyeball ladder session**~~ **DONE 2026-08-30 (`49`)** — `real-gloss`
   wins, unanimous, no single-axis fallback needed. Kernel presets still to
   ride along.
3. **One RR-off look** (old E10 / `43` M1, by eye, at the winning rung):
   does the roughness axis sharpen with the denoiser out? Confirm
   `DLSS_D: false` in the `collect.sh` snapshot **before** shooting. The
   two-launch RR *floor* is dropped — no decision still rides on S1/S3
   radiometry.
4. Whenever convenient: E8 sun size (live, no launch) · E11 probe legend
   decode (offline, `44` §2.9).
5. **The look plan is `51`** (2026-08-30 night): A6 spectral kernel (`52`)
   and A7 terminator bleed (`53`) — **user A/B'd both by eye the same night
   and both win** (*"A/B tested myself and these are the shit… skin shader
   looks great too"*, later *"incredible"*; user's own session, settings unrecorded — no
   radiometric claims ride on it). `kernel=spectral` and the bleed family
   are look-confirmed rungs. Same night: **G-U3 answered negative** (`54` —
   the R8_UINT is the light-channel mask, U3/B2 retired) and the **G-U5
   sentinel is built, parked, registered and deployed** (`55`; two rungs,
   interpretation pre-registered). ~~Next: two launches — `probe-both`, then
   `sentinel`~~ **ALL THREE RAN 2026-08-30/31 — see the "newest first" block at
   the top of this page: `56` (G-U5 passes, traced thickness unblocked) and
   `57` (G-U4 coarse, A8 dead; sheen answered YES an hour later by
   user-run `probe-sheen` — `58`).** Order was `sentinel`
   → `sentinel-b` → `probe-both`; run the CET-selector rungs before the
   hand-edited one again. The runbook that planned them is **`51` §9**.
   D3 / M1 resume from `51` §4/§6.
   **E9 SER frame-time: closed by the user 2026-08-30** (*"noticeably faster
   by feel… that's enough"*). **The probe-gi launch (19:36) is the first to
   actually serve a SER splice** — `ser=class:in-skin` (the hints ride the
   skin rung's raygen files; `50` §1), zero rejects. `41`'s serve path is
   proven; its perf claim is still unmeasured. `ser=class` is now standing
   config per the user.

`collect.sh` now snapshots `UserSettings.json` into each rung dir, so RR
state and regime breaks are recorded facts from here on, not inferences.

## Removed (do not rebuild without reading why)

Hair BRDF (`19`, `27` §8) · Tier-4 backlit transmission (`39`) · `skinray`
and the numeric sliders (`43`) · the two-ray shadow splice (`26` §7d) ·
`38`'s "+2 material channel" idea (`44` §2.4: it is the shading normal) ·
**A8 thin-film iridescence on chrome (`57` §3.1: chrome has no subtype, so it
cannot be gated; the ObjectID-hash fallback is noise-per-object per `43`)** ·
**question (c), per-subtype skin BRDF (`57` §3.2: class 1 does not split)**.

Note the two-ray shadow splice above stays removed, but the *reason* has
changed: not "a second trace cannot execute" (overturned, `56` §4) but
`sctrl`'s hand-picked SBT indices (H3). A rebuild would have to clone operands
by id the way `55` does — and no current feature wants it.

## Where things are

- `init.lua` + `*_engine.lua` (root) are the source; `make release` copies
  them into `release/`; **`make install` deploys to the game with a backup**
  (the game ran stale copies until 2026-08-30 — `44` §2.3). `make layer`
  rebuilds the Vulkan layer.
- `sync_settings.sh` runs from the Steam launch options and materialises
  every overlay (+ `kernel.bin` from `kernels/`); the CET page reads back
  `status.txt` from the previous launch.
- Skin ladder: `./dev/patch_compute_skin.sh --sets` (14 rungs, ~5 min).
  SER ladder: `./dev/patch_ser.sh --install --from ~/.local/lib/callisto/ptq/rcbm/base`.
- `dev/` — shipping patchers; `dev/retired/` — the ones that are done.
- Ideas and their gates: `38`, reviewed in `43`, low-hanging half built in `44`.
- A/B captures live in `a-b-testing/<rung>/S*.png`; `a-b-testing/reproduce.sh`
  regenerates every figure quoted in `46`/`47` (`reproduce_50.py`: `50`); `./dev/ab_launch_audit.py N`
  re-derives what each launch actually served from the layer journal.
