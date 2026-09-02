# CallistoSSS — current state (2026-09-01 22:30, after the hunt-paint read-out)

One page. Everything here points at the document with the evidence. The rule
this project keeps relearning: *built*, *loaded* and *swapped* are not
*working* — only an on-screen A/B is.

**Newest first (2026-08-30 23:57 → 2026-08-31 01:46, five launches; then the
2026-08-31 14:17 oil+fuzz build, its first look, the 14:57 rebuild, its
launch, the 15:57 half-oil + bounce-bleed rebuild, the 18:00 skin-spp build,
the 20:57 terminator-band build and its 21:04 / 22:00 / 22:28 launches; then
the 2026-08-31 late read-only pass that falsified `43` M1, zero launches):**

**2026-09-01 six-agent offline session — docs `82`-`87`, zero launches, offline-verified
only. Read the doc before serving anything.**

**2026-09-01 22:30 — `94`'s `hunt-paint` IS SHOT and the car-paint gate is
REAL: cars read green. One unanticipated false positive — market tarp roofs
read green too.** USER VERDICT: *"Lots of cars have the green on them and
we're separating materials way better … The green is also getting picked up by
some market tarp roofs … Thats probably the worst offender."*

- **Unblocked:** `94` §4.1's clearcoat at site C, gate `m ≥ 0.5 ∧ r < 0.35`,
  plus the flake glints on the same predicate. `m_min`/`r_max` were guesses
  the build was told to label as guesses; they are now measured and the
  measurement agrees. Paint is `class 0, m ≥ 0.50, r ∈ [0.12, 0.30)` — the
  first row of §12.3's pre-registered table.
- **The bigger result, which the probe was not built to find:** the buckets
  separate Night City's materials cleanly and consistently. This is a
  **material classifier that happens to have a car-paint bucket**, and the
  other five buckets (chrome, rough metal, smooth dielectric, the semi-metal
  band) are candidates for their own treatments. Recorded in `94` §14.1, not
  designed anywhere yet.
- **The false-positive census is one problem, not a grab-bag.** Window
  gratings, road-edge light grilles and AC units also read green — and all of
  them are *painted metal*, so the coat is the correct model for them and the
  user wants them included (*"I wouldn't mind if they randomly got materialed
  the same way it might look cool"*). The gate is selecting **smooth metal
  with a coat on it**, which is exactly what §4.1 set out to find. **Only the
  tarp is a problem** (*"Overall just the tarp would be a problem"*) — and it
  is the only non-metal in the set, which is a clue in itself: a woven polymer
  sheet has no business at `m ≥ 0.5`. Even there, a *coat* on a plastic tarp
  is arguably correct while *flake glints* on one are unambiguously wrong, so
  the two halves — already separately gated — should ship on different
  predicates.
- **Two bisect rungs built and parked**, one knob each, to find whether the
  tarp is separable at all: `hunt-paint-r20` (`r_mid` 0.30 → 0.20, "is the
  tarp rougher?") and `hunt-paint-m70` (`m_hi` 0.50 → 0.70, "is the tarp less
  metallic?"). One frame each, holding a car and a tarp roof together.
  Thresholds re-derived from the shipped bytes by the verifier; all three
  non-vacuity decoys rejected. Selector rows added, `make install` run.
- **What the read-out did NOT report** (`94` §15, so silence is not mistaken
  for a pass): skin red / hair yellow (the void condition), the car window
  teal not green (the "kills the read-out" row), road vs body, chrome cyan,
  black anywhere, and `hunt-paint-ctl` vs the standing rung — the cheapest and
  most load-bearing control in the repo, still unshot. No screenshot was
  archived, so this is an eyeball read-out: enough to unblock §4.1, not enough
  for those five.

**2026-09-01 22:05 — ON SCREEN AND KEPT. `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`
is the standing selection and the user's stated default.** USER VERDICT
2026-09-01: *"Fog looks great!"* … *"gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
is my new default"*.

- **Served, proven from the run, not from the switch.** Launch line
  `2026-09-01T22:05:18-05:00 … skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
  skin_sha=4dc824ca77d95feb ser=class:in-skin cache=cleared payload=d76c5b9811008e50`.
  The served `swaps.skin/` is byte-identical to the parked rung (93 files,
  `4dc824ca77d95feb`; reference raygens `1f09268e…`, which is **not** the base
  `-cone2all`'s `fcfe0b9f…`). The journal shows **all 12**
  `rgs_reference_main` permutations loaded from `swaps.skin/` and bound into
  RT pipelines with `swapped: 1`, so `88` §1's dispatch lottery cannot matter
  here — every permutation the game could pick carried the term. Layer hits:
  resolve 77, raygen 15, refl 3, **gi 4** (0 in the previous run, because the
  previous run had no GI overlay at all), failed 0.
- **What the verdict does NOT attribute, stated plainly.** That launch moved
  **two** things against its predecessor: `skinspec` went `off` → the whole GI
  chain (`-cone2all`, `-clothhi` cloth sheen, luma-neutral bleed, cavity cone)
  **and** the fog term arrived. And the fog multiply lives only in
  `rgs_reference_main` — reference / photo-mode PT — while no `trace_rays`
  line in the run names a reference raygen (one-directional rule, `88` §2b: a
  missing line voids nothing and proves nothing). So this is a keep of the
  **rung**, not a measurement of the fog term. `-cone2all` vs `-cone2all-fog`
  remains the one-variable pair, both halves parked, if attribution is ever
  wanted; `95` §10's V1/V2/V3 frames are unshot.
- **The ladder is unshot too:** `-foghi` (strength), `-fogn` (the tint axis —
  if it is indistinguishable from `-fog`, the per-channel σ is not earning its
  three extra `Exp2`s), `-fogcam` (F3), `-fogy` (the up-axis falsifier, F1).
  The up axis is still argued structurally, never measured.

- **The record correction that matters more than the deploy.** The 21:33–21:43
  launch ran `skinspec=off`: `status.txt` read `want_skinspec_req=off` and the
  served `swaps.skin/` hashed `0d0f3ee45ea0d538`, i.e. `skin.set/off` byte for
  byte — 77 compute modules, **no raygens**. The reference raygens it served
  came from `swaps.ptq` (`55ed4e5c…`), which is neither the fog rung
  (`1f09268e…`) nor even the standing base `-cone2all` (`fcfe0b9f…`). **So the
  whole GI chain — `-cone2all`, `-clothhi`, the cloth sheen, the luma-neutral
  bleed, the cavity cone — has not been on screen in that session at all**, and
  any impression formed from it is not evidence about any of them. `refract=fres`
  and `ser=class` were live; the skin/GI half was not. This is the third time
  the project has been bitten by "a switch position is a request, not evidence"
  (`09` I6); it is why the check is `cmp` against the served bytes and never
  the settings page.
- **What was deployed at 22:00.** `./dev/build_volsun.sh --install` parked all
  six `95` rungs (93 modules each, gates re-run green: 36/36 sites, 0 rays
  added, closed form 3.4e-06 – 6.0e-06 worst rel err, `--a 0` byte-identical
  12/12). `./dev/build_hunt_paint.sh --install` parked `hunt-paint` and
  `hunt-paint-ctl`. `init.lua` gained selector rows for all eight — without a
  row `init.lua:288` coerces an unknown `skinspec` to `off`, which is a
  **silent no-op**, not an error, and is exactly how a park-and-launch turns
  into base-vs-base. `make install` carried **only** that `init.lua` change:
  the live CET Lua was already identical to `HEAD`, so `82`/`84`/`90`'s
  "undeployed changes" caveat is now stale — they went out at 15:20.
- **Shipped defaults changed:** `skinspec` `off` →
  `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`, and `ser` `off` →
  `class` because it must be: the rung ships 12 `rgs_reference_main` + 4
  `rgs_restirgi_*`, and `sync_settings.sh`'s `gi_refuse` empties the whole
  overlay when `ser=off` is requested with a raygen-bearing rung. The live
  `brdf_params.txt` was set to the fog rung (backup:
  `brdf_params.txt.bak_prefog`). All three `gi_refuse` provenance gates were
  dry-run against the parked rung and pass: `ser_sha=310513f3008cbde4` matches
  `ser.set/class`, `ptq_sha=55ed4e5c6884ab71` matches the served `swaps.ptq`,
  `shadowset=full-shadow`.
- **What is owed.** Attribution (above), the four unshot ladder rungs, and
  `94`'s `hunt-paint` probe — parked, selectable, never launched.

**2026-09-01 later, `91` — ONE LAUNCH AND ONE KEEP: `refract=fres` is on screen
and is the standing glass look. `76`'s Phase 0.5 refraction is retired as
falsified.** This is the only thing from 2026-09-01 that is on screen; every
other doc from that day is still offline-only.

- **`91` — GLASS: `refract=fres` IS ON SCREEN AND KEPT. The `76` refraction is
  retired.** USER VERDICT 2026-09-01: *"the fres is much better. Looks awesome.
  Thats the new defact look."* Installed to `refract.set/` at 15:21, selected in
  `brdf_params.txt`, sha `cb868ff35daff75b`.
  **What it replaced, and why.** A user screenshot (13:39, from the 13:10:37
  `refract=eta15` launch) showed a doubled Judy; the ghost measured **dx ≈ +270
  px on an 810 px frame** and was **non-rigid**, i.e. a bend. Three defects: a
  flat 4 mm car window's two interfaces **cancel** (residual 1.3 mm at 45°,
  invisible) while `76`'s single-interface model deviates **16.9°**;
  `patch_refract.py` rewrote all 19 uses of the mirror direction *including the
  env cubemap*, so **the reflection was deleted at every angle**, with no
  Fresnel anywhere in it; and the bent copy landed over an untouched raster
  see-through — the "warp or ghost" question `76` §0 left for a screenshot.
  **It ghosts.** The bent look `76` liked and that ghost are the same pixels.
  **What `fres` is:** the vanilla mirror weighted by exact dielectric F(θ)
  (.040 head-on → .613 at 85°) — on a flat pane the raster see-through already
  IS the correct transmitted image, so the whole physically-real
  angle-dependent effect is the reflection ramping to a mirror.
  **Still open, and cheap:** neither diagnostic was shot, so `20` open item 1
  (does the consumer add or replace?) **stays open** — `fres-null` is installed
  and costs one launch. The F² double-apply question (`fres-flat`) is
  unresolved but now unlikely, since a downstream Fresnel would have made the
  reflections near-invisible and they came back. **`86`'s absorption is dead as
  built** — its `d` is the refracted segment length, which no longer exists.
  **The CET selector still lists only `off/eta15/eta20` and now misreports the
  live look**; trust `status.txt` `want_refract`. Shipped default is still
  `refract=off`. `make install` deliberately NOT run — only `refract.set/`
  was written, so 82/84/90's undeployed CET changes stayed out of the launch.

- **STANDING SELECTION: `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all`.** The
  all-lights cavity cone is the live rung as of 2026-09-01. It carries the
  OLD gate (`90` §1: the sample counter in 5 of 12 permutations), which is a
  known defect kept deliberately for now because it is what was judged good on
  screen. `-cone2allgf` is the same rung with the gate fixed and is parked,
  unshot; `-cone2allgf` vs `-cone2all` is the one-variable A/B that retires it.
  ⚠ Area lights at `k_local = 0.85` were previously called WAY too dim (`88`
  §5c) — that verdict was reached on the same coin-flip gate and has not been
  re-read since.

- **`90` — THE CAVITY GATE WAS A COIN FLIP. Fixed, and rebuilt on the PLAIN
  base after `-b3` was reverted.** Shoot `-cone2gf`, `-cone2allgf`,
  `-cone2all35gf`. **The gate A/B is free:** `88`'s parked `-cone2all` IS the
  old-gate build, so `-cone2allgf` vs `-cone2all` is one variable. The four
  `-b3-*` cone rungs stay parked but are not the ladder.
- **`90` detail — the defect.**
  4 rungs built, verified, parked, zero launches. `88`'s cone gated on
  `<counter> == 0` using `find_bounce_counter`, which returns the SAMPLE
  counter — but only in **5 of 12** permutations (correct in the other 7). In
  those 5, with `RayNumber = 1`, the cavity darkening ran at **every bounce**
  instead of the primary hit, decided at random per launch. That explains
  cavity readings that would not reproduce, and is the leading suspect for
  `88` §5c's area-light over-darkening. Fixed by finding the path loop
  structurally (3 fp phis seeded to 1.0 = the RGB throughput). The verifier
  was vacuous on this axis and now catches exactly those 5 in the old rung.
  Rungs: `-b3-cone2` (the ask), `-b3-cone2all`, `-b3-cone2allsg` (**control
  only, do not ship**), `-b3-cone2all35`. **`79`'s ear glow has the same bug
  and was not rebuilt.** `88`'s nine old cone rungs are superseded — do not
  A/B against them.

- **THE `bounce == 0` GATE IS ACTUALLY `sample == 0` (`89` §2).** Found while
  answering "could this be a bounce override?" (it could not — nothing in the
  stack touches a loop bound). `rgs_reference_main` has **two** nested counted
  loops that both contain the sun NEE: an outer **sample** loop (`cbv[188].y`)
  and an inner **path** loop (`cbv[188].z`, identified by its 3 fp phis seeded
  to 1.0 — the RGB throughput; the 4 baked permutations fold that bound to 2,
  `BounceNumber`'s default). `find_bounce_counter` picks the outermost, i.e.
  the sample counter — so **`88`'s cavity gate and `79`'s ear glow run at every
  bounce**, not just the primary hit. Live candidate cause of `88` §5c's
  area-light over-darkening, and testable in the CET panel with no rebuild
  (both terms should weaken as `RayNumber` rises). Not fixed yet.
- **`89` BOUNCE FLOOR — SHOT TWICE, REVERTED. `-b3` reads as SUPER NOISY.**
  First look was a clear win (and the CET CVar route produced no visible change
  at all, which confirmed the 8/12 census on screen). Second look: three
  bounces at **1 spp** is visibly noisier, and that swamps the indirect light
  it buys. `89` §5 said extra bounces are "not a noise fix"; the doc now owns
  that this was insufficient — an extra bounce is an extra stochastic path
  segment, so it is a noise SOURCE, not merely noise-neutral. Live selection is
  back to `gi-50b-bleed-oil-sheen-deep-clothhi`. Rungs stay parked: `89` §5b
  records the one configuration where the floor would pay — **raised
  `RayNumber` or reference accumulation on, photo mode, pinned camera**, where
  the variance is paid for separately. Do not re-test at 1 spp.
- **`89` build detail — 3 rungs built, verified, PARKED.**
  `bound' = UMax(bound, N)` in 12/12 reference permutations; a floor, never a
  cap. The census settles `pt_engine.lua`'s open question: **`BounceNumber`'s
  wire is live** into 8 of 12 (try the panel first — it is free), but the other
  4 baked the bound and the dispatched permutation changes per launch, so the
  CVar alone is a coin flip per run. `-b2` is the control and must look
  identical to `-clothhi`. Pin the CVar at its default for the A/B, and pick a
  frame with visible indirect bounce light.

- **`85`'S 09:16 CAPTURE WAS VOID, AND `88` REPLACES THE TERM.** The
  `-cavityhi` "full occlusion" screenshot was rendered by
  `40c6faab52a13874`, one of the two reference permutations `85` shipped
  **byte-verbatim** — that capture contains no cavity code and is the base
  image. Proven from `callisto_swap.jsonl` (per-run `overlay_manifest` +
  `trace_rays`) and by `cmp` against the parked base. The `-cavity` 6 mm run
  logged **no** reference dispatch at all. What the launches DID measure:
  the lip seam darkened **−6/−7 of 255** at both tmax rungs against a ±2
  noise floor, so `85` F1 is answered — crease geometry is real and the ray
  finds it — but the philtrum and under-jaw did **not** move at 15 mm, so the
  limit is the occluded FRACTION, never k. All four captures are confounded
  by `SunAngularSize` 0.25→0.53 at 09:00:58. The eyelid streak measures
  RGB(252,244,234) — a specular lobe on a convexity, not occlusion, and no
  tmax or k touches it. **`88` is built, verified and PARKED**: four rungs
  `-cone{1,2,4,4w}` on `-clothhi`, **12/12 coverage** (the anchor moves to
  the bindless material fetch `table[reg[1]+5] >> 5`, which all twelve carry
  and which `dev/cfg_dom.py` proves already dominates the splice), a
  cosine-weighted tap cone tilted toward the horizon, a distance ramp, and
  tmin 0.5→0.1 mm. k=0 rebuild byte-identical 12/12; verifier non-vacuous on
  all five axes. **`make install` has NOT run and will carry `84`'s and
  `82`'s undeployed changes with it.** Read `88` §0 before serving anything.
  **Standing rule (`88` §1, corrected in §2b): before any reference-PT
  look-verdict, grep the run's `trace_rays` for `rgs_reference_main` — a
  logged trace naming an UNPATCHED module voids the capture; a MISSING line
  proves nothing.** The 10:3x `-cone2`/`-cone4` runs logged no reference
  dispatch and still differ from `-cone1` by mean |Δ| 7 of 255; `log_open`
  fires per Vulkan process and most records carry zero `trace_rays` at all.
  **`88` A/B IS DONE (§2c).** Four rungs shot on the pinned S1 frame:
  `-cone1` (= tap 0 = `L` = `85`'s term with `88`'s tmin+ramp) → `-cone2`
  moves the face by mean |Δ| **7.05**; `-cone2`→`-cone4`→`-cone4w` move it by
  2.69 / 1.89. **The horizon tap is the whole effect; the lateral taps and the
  wider angle are near-noise.** `-cone4w` is the user's stated preference —
  specifically the crease under the nose — but that crease measures identical
  across cone2/cone4/cone4w (contrast 94.04 / 94.23 / 93.97 against cone1's
  100.43), so it is the horizon tap's, not `-cone4w`'s. **`-cone2w` (2 taps,
  θ=25°) and `-cone2all` were built and parked 2026-09-01** — `-cone2all` is
  `-cone2` with the SCOPE axis moved (`88` §5b): the same cone additionally
  spliced at the **2 of 3 local-light NEE sites** that shade through a
  visibility scalar, 6 flags-16 traces/module against `-cone2`'s 2. The third
  local site drives a branch into a light-type switch rather than scaling
  anything and is NOT patched, so this is "all lights that shade by a
  visibility scalar", not provably all lights. **One of the two IS INSIDE THE
  LIGHT LOOP, so its ray count scales with the visible light count** — A/B it
  against `-cone2` in an INTERIOR or under neon, not in daylight, and time it,
  because the reference PT accumulates and a screenshot cannot show cost. **`-cone2all` IS SHOT AND THE VERDICT IS SPLIT** (`88` §5c):
  concentrated sources win — faces read better on the street and in rooms with
  few light sources, and there is a lot of that in this game — but **area
  lights go WAY too dim**. Diagnosed as a SOLID-ANGLE error, not a bug: the
  cone measures a ~12° slice around one direction and then bills `k` of the
  WHOLE light term. The sun subtends 0.53° so the cone covers it; an area light
  subtends tens of degrees. It compounds with §2c's grazing concentration,
  because room lights hit a face from many more grazing directions than the sun
  does. NOT an origin bug — all three NEE traces share the identical origin
  triple, so `prehit` is right at the local sites too. **Built in response:
  `--k-local`, and rungs `-cone2all{20,35,50}` (k_local 0.20/0.35/0.50) that
  move the local strength ALONE — the sun stays at 0.85, so the sun verdict is
  not re-opened.** Rejected on consult: a cosA rolloff (kills the effect
  exactly where it earns its keep) and an energy-redistributing
  `(1−k·occ)/(1−k·occ_bar)` (contrast enhancement, not occlusion; pushes
  unoccluded skin above the engine's lit level, stacks across lights,
  scene-dependent constant). The correct fix is to scale `k` by the source's
  ANGULAR SIZE, blended so contact keeps full strength —
  `k·mix(sa_ratio, 1, saturate(1−t/2mm))` — but that needs a radius out of a
  64-byte light struct whose only floats are at offsets 0/16/32; misreading it
  gives per-light-type flicker. **The ladder is a MECHANISM TEST, not tuning:
  shoot a frame holding BOTH a concentrated source and an area light. If some
  k_local serves both, the diagnosis is proven and the angular-size form is
  justified. If none does, the SHAPE is wrong rather than the scale and that
  form becomes mandatory.**
  `-cone2w` to break the confound: `-cone4w`
  differs from `-cone2` in the laterals AND the angle at once. Shoot
  `-cone2w` / `-cone2` / `-cone4w` back-to-back in one session (`88` §8 step
  5) and one of the two cheap rungs ships. **Noise floor: shadowed skin
  (`L<55`) cannot execute the splice, so mean |Δ| there is the floor — it ran
  1.2–1.4 on the 10:3x set, against face-wide 1.89 for cone4→cone4w.** Shadowed skin does not
  move (lit-gate holds empirically); darkening falls monotonically from
  −10.5 % at the shadow boundary to −1.1 % in the open, so the term is a
  **terminator softener / contact shadow selective by grazing angle**, not by
  concavity. The eyelid/lip speculars are still untouched (§3).
- **BUILT, PARKED, AWAITING A/B:** `84` env chroma bleed (`-envbleed`/`-envbleedhi`
  on `-clothhi`; luma-held widening at the 4 restirgi diffuse finals; q=0
  byte-identical 93/93) · `86` glass absorption (`refract=eta15-absorb{,hi,p}`;
  soda-lime hue, miss bit-exact; control is `eta15`, NOT `off`; CET selector
  does not list the new levels) · `85` cavity contact shadow (`-cavity{,d,hi}`;
  **repo-only, not parked** — `./dev/build_cavity.sh --install` then
  `make install`; photo-mode reach; F1 no-op falsifier is THE experiment).
  All three carry full verification tables; standing verifiers re-run green.
- **SETTINGS-ONLY LEVERS, UNRUN:** `82` denoiser panel (seeded
  `detail_engine.txt`, `make install` serves it; RR must be OFF or the panel
  is bypassed) · `83` sun size (`RayTracing/SunAngularSize` — Ultra Plus wrote
  0.225-0.35, so the sun has been 1.5-2.4x too small in every outdoor shot to
  date; `vanilla[]` snapshot is poisoned at 0.25, do not use "restore
  defaults" as the control).
- **ON SCREEN, KEPT (2026-09-01 09:20, `83` §9-§10): the sun is now 0.53.**
  Ultra Plus is patched to write it — `Variables.lua`'s `sunAngularSizes`
  flattened across all 24 hours, `modes.ini:284` (`[PT21]`, the live mode)
  0.25 -> 0.53; both backed up as `*.bak_callisto_20260901-090058`, stock curve
  kept in a comment. Served, looked at, **user verdict "0.53 looks better"** vs
  the old 0.225-0.35 curve. *Uncontrolled* — settings not stated in advance,
  scene/hour unrecorded, so it stands as a LOOK result like A6/A7 and **no
  radiometric claim rides on it**. It is still the first evidence the CVar
  reaches the PT image at all, which points against `83` §7's doubt.
  **Every outdoor shot from here on is under a 1.5-2.4x wider sun than every
  shot in `46`/`72`/`74`/`78` — those are NOT valid controls for each other.**
  Two corrections came with it: the cron writes **per in-game hour**, not every
  60 s, so the PT-panel takeover was never required to hold a value (it IS
  required to make the panel's own slider do anything, and it drags 14 other PT
  CVars with it — `83` §4.1, §5a3); and the `pt_engine.lua:136` path reorder is
  **unnecessary, do not apply it** — DIFF/REFL provably return nil on all 10
  registers (`83` §10.4).
- **UNITS STILL UNPROVEN (`83` §10.3):** a 2.0 run was attempted and is
  **INVALID** — set, then the save was reloaded, so 2.0 was never on screen
  (`83` §10.1; the §9 patch may itself have eaten it). "0.53 is physically
  correct" therefore still rests on `83` §2's 90%-confidence circumstantial
  units reading. The `0.25 -> 2.0` photo-mode sweep on a **long cast shadow**,
  with readback *after* each shot, remains one launch and settles both the
  units and §7's does-it-reach-PT question.
- **DEAD, CLOSED:** `87` tinted translucent shadows — the shadow chain is
  scalar end-to-end (payload one float 13/13, AHS collapses alpha to a
  boolean, evaluators read `.x`); `29` §B6's SIGMA-translucency claim is
  withdrawn. Per-material coloured transmission is unreachable in this
  pipeline (`86` proved the refraction side has no material fetch either).
- **CONFLICT TO RESOLVE BEFORE ANY LAUNCH:** `UserSettings.json` read
  `DLSS_D: true` at 01:42 and `false` at 02:31 — it is moving. Grep the
  Proton-prefix copy (the `~/.wine` one is stale) immediately before every
  A/B; the standing look was judged with RR OFF.
- `init.lua` gained 5 selector rows (84's two, 85's three); `Makefile` gained
  the `82` seed step. None of it is installed — `make install` has NOT run.

- **CLOTH SHEEN (A2): ON SCREEN, KEPT — `-clothhi` (k=1.0) is the user's
  new default selection (2026-09-01, `81` §10).** User ran both rungs over
  repeatable scenes including architecture: *"I SWEAR its better… It just
  feels better for like every material somehow"*, prefers `-clothhi`. The
  "every material" read is the pre-registered signature of the proxy gate
  (rough dielectrics painted, bounded), not evidence of a leak — no wall-glow
  or chalky-concrete failure reported. Honest caveats: verdict is a
  look-call — no pinned-frame control, serve not audit-verified
  (`./dev/ab_launch_audit.py` if it ever matters), settings not re-pinned.
  Build record follows. A Charlie×Neubelt lobe added at all **457** direct
  compute BRDF sites on **rough dielectrics**, off the standing
  `gi-50b-bleed-oil-sheen-deep`, with the Burley diffuse renormalised at
  **173/173** sites. The cloth *class* is still unreadable offline and `22` was
  right about that — the census kills it outright: **no shader tests any
  subtype under class 0**, and the three sub values that are tested
  (17/21/25) feed **light-channel flags**, not material identities
  (`05511714f20081b4:1110`). So the gate is a physical proxy, not an identity:
  `class != 1 && class != 4 && max3(F0) < 0.09`, times a roughness ramp
  `sat((alpha − 0.10)·5)`. That excludes skin (it already has its own fuzz),
  hair, every metal, and all glass/clearcoat/polished plastic — and
  **deliberately still paints concrete, plaster, wood and road**, bounded, as
  the grazing retroreflection they physically have. **That false positive is
  the thing the A/B must look at**, so the launch requires a hard non-cloth
  reference in the same frame (the `58` §5 gap). Bounce sheen is **closed as
  impossible**: the GI diffuse raygens compute no view vector (`74` §0,
  `50` §3.1) and a Charlie D needs one — the 16 raygens are byte-identical to
  `gi-50bnd`. Verification, all on **shipped bytes**: 457/457 + 173/173
  coverage or the build fails, `spirv-val` clean on 93 modules × 2 rungs,
  **gate-false is byte-inert** (a `k_cloth=0` rebuild differs from `-deep` in
  0 of 77 modules), 8696 points machine-checked against a float32-exact closed
  form per rung, gate-false exact identity, negative control finds 0 sites on
  `-deep`, and `verify_bleed_norm` + `verify_gi_ladder` still ALL PASS.
  Calibrated against the *approved* peach fuzz: at k=0.5 the hemisphere is
  median 0.64% / p90 5.7% of local diffuse vs the shipped fuzz's 0.72% / 4.0%
  — the same band the user already accepted on a face. **Note the base:** the
  task named `-lumn`, but `-deep` won at 22:28 (`78` §5.1) and is the live
  selection, so both rungs sit on `-deep`; only the newest commit *message*
  still says `-lumn`. `make install` ran (selector rows only, `brdf_params.txt`
  untouched); nothing has been on screen.
- **`43` M1 — "the denoiser sees vanilla roughness", rated there as "probably
  the most important item" — is FALSIFIED. Nothing built, nothing undone
  (`79`).** The user's read (*"Ray reconstruction definitely makes things
  blurrier in screenshots"*) is real but is not evidence for M1, on three
  counts. **(1)** RR was never in the pipeline for any of it: `DLSS_D: false`,
  verified in `UserSettings.json` at 22:41 against a 22:28 launch, so the oil,
  the half-fuzz, `-lumn` and the `-deep` band were all judged with RR out.
  **(2)** The falsifier in `43` §3 / `51` §6 does not discriminate — it swaps
  RR for NRD and both read G-buffer roughness (`IN_NORMAL_ROUGHNESS` is a
  required NRD input), so either outcome fits M1 being false. **(3)** The
  differential that *does* discriminate already ran with RR **on**: E2a→E2b,
  13:36 / 13:50 on 2026-08-30, both pre-dating any RR toggle attempt — top-3%
  highlight **+3.23%** on a flat face with flat controls (`46` §11.3, "the
  only quantitative S1 result standing"), plus the unprompted *"like a detail
  filter"*. The resolve-side roughness edit reaches the screen through RR;
  M1 says it cannot. The premise survives (the denoiser does filter at
  vanilla-roughness radius) but is second-order, and both fixes are blocked:
  route (a) is moot with RR off, route (b) needs G-U2 — **1290 fragment
  modules dumped, zero ever swapped** (`dev/census_stage.py`), and it would
  double-apply against the shipping `alpha_scale=0.7` + `alpha_max=0.2025`.
  **What to do instead, both cheaper:** (a) the denoiser panel has *never been
  enabled* — `detail_engine.txt` is absent from the live install, so ReBLUR
  runs at stock radii and the direct `SpecularPrepassBlurRadius` (20) is
  literally M1's mechanism on a runtime slider, zero launches
  (`detail_engine.lua:98`, one-click ceiling at `:208`); (b) the **DLSS preset
  test**, still unrun, which `43` §2's own 0d calls "the single cheapest
  face-sharpness lever in the whole document". Also corrected: `32` §3's "no
  material awareness" claim was wrong. Also recorded: the live install reads
  **`refract=eta15`**, closing the `76` "which level was on screen" item.
- **The mod itself was holding the terminator band UP, the bleed was the larger
  half, and the DEEPEST rung won. `gi-50b-bleed-oil-sheen-deep` is ON SCREEN,
  KEPT, and is the standing skin rung and the live selection (`78` §5.1).**
  Both rungs were served: `-lumn` at 21:04 / 22:00 (`skin_sha=a3139d629e26d902`)
  — *"Looks 10x better. Using the lumn version now as the default."* — then
  **`-deep` at 22:28** (`skin_sha=f8f2890ebcd48252`, `req == want`, layer
  `last_failed=0`, same 77/10/15/3/4 hit profile). User verdict: *"Deepest band
  is actually the best skin shader right now over lumn."* **This is the
  cleanest band A/B in the sequence**: the launch immediately before it served
  `-lumn`, and the only other logged differences were `ser` (`class+hit` →
  `class`) and `cache` — neither of which can move a pixel (`41`: the reorder
  hint "cannot change a pixel"), so the back-to-back pair moved **one**
  look-variable. `-lumn`'s own win was the weaker read (the launch before it
  was `-spp4`, two variables; the one-variable twin was three hours earlier at
  17:17 / 17:20 — `78` §5.0). Still a verdict, not a measurement: no capture
  pair, camera not pinned, and the one pre-registered confound — `-deep` dims
  bounce-lit skin ~2% *uniformly* via the SP flat factor — is untested, and
  **the scene was not recorded**, so whether a bounce-dominated interior was
  even in shot is unknown.
  The user's read — *"the increased rays is the wrong lever for more
  contrasted shadows on the face"*, then *"make the bleed luminance-neutral;
  m_R = 1 + 0.336·w adds energy at the terminator"* — is correct and larger
  than it looks. Measured (`dev/band_model.py`, falloff normalised at the lit
  cheek so vanilla ≡ 1.000): the stack holds the band floor at **1.247 on
  directly-lit skin** and 1.153 on bounce-lit, of which the bleed's `m_G = 1`
  energy add is **+10.4% on skin chroma** and c1's grazing-light lobe
  (`rho_f`) is the rest. **`…-lumn`** scales the whole triple by the pixel's
  OWN Rec.709 luma ratio — R:G:B, hence hue and saturation, bit-for-bit the
  approved look; only the scale moves — taking the direct floor to 1.130 and
  the bounce floor to 1.044 (0.14 stops back on each). **`…-deep`** also pulls
  `rho_f` to identity in both halves: direct 0.988, bounce 0.889 (0.34/0.38
  stops back) — that one INVERTS the lift rather than cancelling it, and it
  dims bounce-lit skin ~2% overall via the SP flat factor (1.078 → 1.056), the
  single pre-registered confound. A grey renormalisation was rejected with a
  number: it leaves 40% of the lift because skin is chromatic. Verification:
  both patcher edits **byte-inert** against every parked base (0/77 compute,
  0/16 raygens); a new `dev/verify_bleed_norm.py` re-parses the SHIPPED bytes,
  proves the channel wiring and **executes** the emitted hold at 18 000 points
  per rung — closed form matched, luminance held < 3e-6, gate-false exact
  identity; 150/150 bled sites carry the hold or the build fails;
  `verify_gi_ladder` ALL PASS on both new bases; `gi_refuse` provenance
  identical to the standing candidate. Both A/Bs ran
  (`gi-50b-bleed-oil-sheen` → `-lumn` → `-deep`) and each rung beat the one
  below it. **Now open: `-deep` in a bounce-dominated interior** — the SP flat
  factor confound lives there, and the half-step back (`--rho-f 1.09` /
  `1.17`, two commands, `78` §5.2 item 3) is the lever if it reads flat.
  Approximation written out loud:
  the hold's basis is the albedo triple, so a strongly tinted light leaves a
  bounded ±3–4% residual (`78` §4 has the table and the route to exactness).

- **Skin-only sample count (`29` B4, the post-sentinel "real lever"): BUILT
  + PARKED + DEPLOYED 18:00; both rungs SERVED ON SCREEN 18:07 / 18:10 with
  NO VERDICT GIVEN, and the live selection has since moved off them (`77`).**
  (Launch log: `-spp4d` `skin_sha=9186954230375089`, `-spp4`
  `c564a287c016d49f`. Served is not judged — the d-vs-full artifact
  attribution below is still unrun.) Class-1 pixels path-trace
  `max(RayNumber,4)` spp in the reference raygens; everything else is
  bit-identical to the base. The build discovered what `29` §B4 did not
  know: **the engine's own sample loop is ALIVE in the 6 runtime-bound
  permutations** — header phis carry RNG/accumulators/counter, the latch
  bound is `cbv[188].y` (RayNumber), and every per-sample MIS weight
  divides by a fresh read of it — so there the whole feature is "rewrite
  every RayNumber read to `OpSelect(isSkin, max(N,4), N)`" (6 sites per
  module) and RNG threading + normalization come from the engine. Only the
  4 baked permutations (`29` §B3's literal-bound list) got the real §B4
  surgery: old merge → continue block (existing branches become legal
  continues), 3 half accumulators + counter + remixed seed, conditional
  back-edge, average at the new merge. Two rungs, one variable:
  `skinspec=gi-50b-bleed-oil-sheen-spp4d` (dynamic 6 only, low risk) and
  `…-spp4` (all 10 — carries the baked tier's residual risk: 14 in-loop
  record stores inside the RNG taint cone now run N× with last-write-wins;
  the d-vs-full A/B exists to convict exactly that). All spirv-val clean,
  emitted-code re-read clean, provenance verified against the live install
  (sync accepts both). **Photo-mode priced: ~+60–90% PT cost in face
  close-ups (`29` §B7). Denoiser ceiling caveat stands — expect cleaner
  shadow gradients on faces, not a step change.** A/B runbook + settings
  contract + pre-registered outcomes: `77` §6. Shoot a face with a hard
  shadow gradient; a flat-lit face is a wasted launch.
- **Glass refraction Phase 0.5 (D3, `20` §5b / `51` §4): BUILT, DEPLOYED
  17:15, LAUNCHED, USER VERDICT KEEP — "looks incredible" (`76`).** The transparent-reflection raygen's mirror
  direction repointed to Snell's law (no TIR branch needed, η<1), origin
  sign fixed to P+ε·D, all 19 downstream uses rewritten; ladder
  off/eta15/eta20 parked in refract.set/, served THROUGH swaps.ptrefl/ via
  new `refract=` key + CET selector (default off). Machine-checked 500/500
  vs reference refract, spirv-val clean, sync paths sandbox-tested. The `20`
  consumer question stays open — it gates v1's two-ray combine, not this.
  A/B ran (PT Overdrive, ptrefl=on, window/glassware oblique); the user
  called it incredible and had it committed. **Still unrecorded: which level
  was on screen (eta20 vs eta15) and the warp-vs-ghost per-pixel call of
  `76` §3.** Default stays `refract=off` — opt-in via the CET selector.
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
§13 → §12 for the evidence behind it. The L-queue is done (L1–L8); the
real L4 (RR off, two launches) was never run and is now **retired unrun** —
`79` shows no surviving decision rides on it.**
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
| **`skinspec=gi-50b-bleed-oil-sheen-deep`** — **the best skin rung there is right now** (live selection moved to `-deep-clothhi`, 2026-09-01). `-lumn`'s luma-holding bleed *plus* c1's grazing-light lobe (`rho_f`) pulled to identity, in the compute half AND the bounce half. Takes the terminator band to **0.988 direct / 0.889 bounce** (vanilla ≡ 1.000) — it inverts the mod's own lift rather than merely cancelling it. **On screen 2026-08-31 22:28, kept over `-lumn`**: *"Deepest band is actually the best skin shader right now over lumn."* One look-variable against the launch before it (`78` §5.1). Untested confound: ~2% uniform dim on bounce-lit skin. Needs `ser=class…` (in-skin) + `shadowset=full-shadow`. Shipped default stays `off`. | `skinspec=gi-50b-bleed-oil-sheen-deep` | `78` §5.1 |
| **`skinspec=gi-50b-bleed-oil-sheen-deep-clothhi`** — cloth sheen (A2) at k=1.0 on the `-deep` stack: Charlie×Neubelt added at all 457 direct compute BRDF sites on rough dielectrics (proxy gate: not skin, not hair, `max3(F0) < 0.09`, roughness ramp), Burley diffuse renormalised 173/173; bounce closed (no view vector in the GI diffuse raygens). **On screen 2026-09-01, KEPT as the user's default**: *"It just feels better for like every material somehow"* — the every-material read is the proxy gate by design. `-cloth` (k=0.5) parked as the quiet half. Look-call: no pinned control, serve not audit-verified. Needs `ser=class…` + `shadowset=full-shadow`. | `skinspec=gi-50b-bleed-oil-sheen-deep-clothhi` | `80`, `81` |
| **`skinspec=gi-50b-bleed-oil-sheen-lumn`** — the same stack with only the bleed's energy add removed (each pixel's own Rec.709 luminance held; hue/saturation bit-identical), c1's lobe left in. 0.14 stops of band lift back on each path. **On screen 21:04 / 22:00, kept** (*"Looks 10x better"*), then **superseded by `-deep` at 22:28**. Keep it as the half-step back if `-deep` ever reads too deep. | `skinspec=gi-50b-bleed-oil-sheen-lumn` | `78` §5.0 |
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
| ~~**Terminator band depth, the deep rung**~~ (`78`) — **PROVEN ON SCREEN 22:28, moved to the table above.** What is left of it in this queue is the *interior* case: `-deep` dims bounce-lit skin ~2% uniformly via the SP flat factor (1.078 → 1.056), and it was judged on a sun terminator. Half-step exists (`--rho-f 1.09` / `1.17`) if a dim interior reads flat | `skinspec=gi-50b-bleed-oil-sheen-deep` | `78` §5.2 |
| **Skin-only sample count** (`29` B4) — class-1 pixels get `max(RayNumber,4)` spp in the reference raygens, non-skin bit-identical. `-spp4d` = the engine's own live sample loop retargeted (6 runtime-bound raygens, low risk); `-spp4` = plus the 4 constant-folded ones rewired (record-store residual risk — d-vs-full is the attribution A/B). Photo-mode priced (~+60–90% PT in close-ups). **Both served on screen 18:07/18:10 with no verdict; both sit on the pre-`78` base, which is now two rungs stale** (`CALLISTO_SPP_BASE=gi-50b-bleed-oil-sheen-deep ./dev/build_skin_spp.sh --install` is the one command to rebase them on the standing rung) | `skinspec=gi-50b-bleed-oil-sheen-spp4d` / `…-spp4` | `77` |
| Peach fuzz, 58-era **multiplicative** form — measures 1.00–1.05× on the face; superseded, kept only for reproducibility | `skinspec=gi-50-bleed-sheen` | `58`, `72` §1 |
| SSS kernel presets `balanced` / `callisto` / `vanilla` (tooling check) | `kernel=` | `44`, `33` §1 |
| Sun visibility / scattering (live CVars) — **size is DONE and on screen at 0.53** (`83` §10.2), the other two never tested | PT panel, or Ultra Plus | `44`, `43` M3, `83` §9 §10 |
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
3. ~~**One RR-off look** (old E10 / `43` M1, by eye, at the winning rung)~~
   **CLOSED 2026-08-31 — M1 FALSIFIED, nothing to launch (`79`).** The test
   never discriminated (it swaps RR for NRD; both read G-buffer roughness),
   and the differential that does discriminate already ran with RR **on**:
   E2a→E2b moves the top-3% highlight **+3.23%** on a flat face (`46` §11.3),
   so the resolve-side roughness edit reaches the screen through RR. Also
   moot in practice: `DLSS_D: false` has been the standing config throughout,
   so every look approved 2026-08-31 was already judged with RR out.
   **Replacement, in order:** (a) enable the `detail_engine` denoiser panel —
   `detail_engine.txt` is absent from the live install, so ReBLUR runs at
   stock radii and the direct `SpecularPrepassBlurRadius` (20) is M1's own
   mechanism on a live slider, no launch; (b) the DLSS preset test at item 4,
   which `79` §7 promotes above everything else on this queue.
4. Whenever convenient: E8 sun size — **look-settled at 0.53 and served by
   default (`83` §10.2); all that is left is the `0.25 -> 2.0` units falsifier,
   which one earlier attempt fumbled (`83` §10.1, §10.3)** · E11 probe legend
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
