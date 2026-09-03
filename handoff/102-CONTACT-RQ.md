# 102 — Traced contact occlusion: built, gated, driver-proven, parked. UNSHOT.

Written 2026-09-02. `88`/`90`'s cavity cone, rebuilt on `98`'s proven inline ray
query as the visibility question `88` §10.4 actually asked. Four rungs built,
ten offline gates green, 22/22 on the driver, parked, selectable, installed.
**Nothing has been on screen. Nothing committed.**

Everything below is either a measurement (§6 gates, §7 self-test) or a
prediction (§9). Each says which.

## 0. Verdict

**BASE NOTE (2026-09-03, added by `101`; amended ~01:20 by `100`; amended again
01:35 by `101`).** These rungs were built on
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`, which is no longer the
standing selection. The default moved **three times** the same day: to
`…-cone2all-fog-earglow` at 00:5x (`101` §17, the ray-query ear glow), then to
`…-cone2all-fog-earglow-glintdense` at ~01:20 (`100` §13, that rung plus the
car-paint glints), then to
**`…-cone2all-fog-earglow-cap6-glintdense` `3bb0aee03a1bfda8`** at 01:35 (`101`
§18's 6 mm ear-thickness floor under the same glints) — **the current shipped
default**. **Nothing here carries any of the three**, and these rungs are
deliberately **NOT** rebuilt, because a rebuild would change every content sha
this document pre-registers as a serving proof — so a launch on any of them is an
ear-glow *and* a glint regression as well as whatever it is testing. **Say that
before the shot.** Rebase after this document's own A/B is settled, not before.

`88` asked one question — *is there geometry within ~10 cm of this skin pixel* —
and answered it with an **analytic cone**: up to four shadow-style traces around
the NEE direction, cosine-weighted, ramped by distance. `88` §2c then measured
what that estimator really is: **the horizon tap is the entire effect** (the
laterals and the cone angle sit at ~1.5× the noise floor), the darkening falls
monotonically from −10.5 % at a shadow boundary to −1.1 % in the open, and
shadowed skin does not move at all. In its own words, that is a *terminator
softener selective by grazing angle, not by concavity* — which is not what `85`
set out to build. `88` §5c then found the second failure: the cone measures a
~12° slice around **one** direction and bills `k` of the whole term, so area
lights go far too dim.

Both failures are the same failure: **the cone is a directional probe standing
in for a hemispherical visibility integral.** This build stops standing in for
it. At the same site, with the same strength constant, it estimates

    o = (1/K) · Σ_j [ the hemisphere about N is blocked within 10 cm along d_j ]

with K short ray queries on a fixed cosine-weighted tap set. That is a real
(if coarsely sampled) ambient-visibility term: direction-symmetric, so a seam
darkens because it is a seam and not because the sun happens to graze it; and
**light-independent**, so it cannot be wrong by the source's solid angle, which
is exactly `88` §5c's disease.

The A/B is therefore **one variable**: `contact-rq` vs the standing
`-cone2allgf` rung is *analytic cone* vs *traced visibility*, same site, same
`k = 0.85`, same per-light lit gating. §2.4 records the one place that is not
strictly true and does not hide it.

**It is a multiply on DIRECT-lit skin, so it is invisible in shade.** `98` §12.4
measured that arithmetic once already: a multiplicative term scales a radiance
that is zero where the pixel is not lit. That is not a defect here — the cavity
term has always been a multiply on the direct term — but it dictates the frame
(§8) and the void rows (§9). Shoot it with the sun on the face or you will read
"no effect" off a pixel where no effect was possible.

## 1. What the cone approximated, and what the trace measures

| | `-cone2allgf` (`88`/`90`) | `contact-rq` (this) |
|---|---|---|
| question asked | is the NEE direction blocked | is the hemisphere about N blocked |
| directions | 2 taps, rotations of **L** (the light direction) | 4 (or 8) fixed cosine-weighted taps about **N** |
| frame | the light's | the **surface's** |
| mechanism | `OpTraceRayKHR`, flags 16 (`CullBackFacing`), payload | inline `OpRayQuery`, flags **517**, no payload |
| distance | tmax 15 mm, `saturate(1 − t/tmax)` ramp | tmax **100 mm**, boolean per tap |
| depends on the light | **yes** — a different `o` per light | **no** — one `o` per pixel |
| solid-angle bias (`88` §5c) | yes, by construction | not possible |
| grazing-angle bias (`88` §2c) | yes, that was the whole measured effect | no |
| cost | 2–6 `OpTraceRayKHR` per lit skin pixel | **K** ray queries per skin pixel, K ∈ {4, 8} |

The trace is not obviously *better*. It is obviously **a different estimator of
the thing the doc claimed to be estimating**, and that is what makes the shot
worth taking: `88` §2c is a measurement that the cone answers a different
question than its own text. If `contact-rq` darkens the same places *tighter*
(§9 row 5) the cone was a grazing-angle proxy and the trace is the term; if it
darkens *everything* the estimator is biased and §9 row 6 says so.

## 2. The splice, at one site

Emitted once per module, in the **sun cone's** instruction run (which
`dev/cfg_dom.py` proves dominates all three application sites in 12/12), then
applied at each cone's own line. 98 instructions at K=4, 142 at K=8, 102 in
`-hit`. Zero added control flow, zero added `OpTraceRayKHR`.

### 2.1 The gate

```
g_sk  = OpIEqual %bool <cls>  %uint_1        ; 88 §4: (material word >> 5) == 1, SKIN
g_p0  = OpIEqual %bool <ctr>  %uint_0        ; 90's find_path_counter: PRIMARY hit only
g_cs  = OpLogicalAnd g_sk g_p0
nlen  = OpExtInst Length <Nraw>
nok   = OpFOrdGreaterThan nlen %float_1em6   ; a degenerate normal cannot reach Normalize
gate  = OpLogicalAnd g_cs nok
```

`<ctr>` is **`find_path_counter`** (`90` §1) in 12 of 12 permutations. The
legacy `find_bounce_counter` returns the *sample* loop's phi on 5 of these 12
and the patcher reports `legacy_helper_was_wrong` per module so the claim is
re-derived, not asserted. §2.4 is the consequence.

Two things follow from the gate having no light term:
* `o` is a **surface** property, computed once and reused at all three sites;
* each cone's own `lit` condition is still ANDed in **at that cone's line**, so
  `88` §2c's empirical result — *shadowed skin does not move* — is preserved
  exactly, per light.

### 2.2 The rays

```
msk  = OpSelect %uint gate %uint_39 %uint_0  ; gate folded into the CULL MASK
nsel = OpSelect %v3float gate <Nraw> <Lv>    ; select BEFORE Normalize: no NaN can exist
Nu   = Normalize nsel
org  = <cone origin> + Nu · 1e-4             ; 0.1 mm along N, the self-hit offset
```

A false gate makes the cull mask 0, i.e. **a guaranteed free miss with no
branch**. Combined with `OpSelect(gate, o, +0.0)` at the application, a
non-skin / non-primary / degenerate pixel gets `fac = 1.0` exactly — bitwise
identity, not "approximately unchanged".

Per tap *j*:

```
d_j  = Tr·cx_j + Br·cy_j + Nu·cz_j
OpRayQueryInitializeKHR %rq <accel> %uint_517 msk org 0.001 d_j 0.10
OpRayQueryProceedKHR
ty   = OpRayQueryGetIntersectionTypeKHR %rq %uint_1       ; COMMITTED
hit  = OpINotEqual ty %uint_0
acc += OpSelect(hit, 1.0, 0.0)
occ  = acc · (1/K)
```

**517 = `Opaque | TerminateOnFirstHit | SkipAABBs`.** `Opaque` + `SkipAABBs`
means no any-hit and no intersection shader can run, so a single `Proceed` is
*provably* sufficient and the splice needs no loop — the same argument `98` §2.3
made, and the reason this is 98 straight-line instructions instead of a
traversal loop. **No face culling**: a contact question does not care which way
the blocker faces, and this is precisely where the flag word differs from
`101`'s 545 (`CullFrontFacing`, a *thickness* question). tmin 1 mm on top of the
0.1 mm origin push is the self-hit guard; tmax 0.10 m is the 10 cm of `88` §10.4.

`GetIntersectionTypeKHR` only — **no `GetIntersectionTKHR`.** The estimator is a
boolean per tap; committing a distance would be a second, unasked variable.

### 2.3 The tap set and its rotation

There is no tangent frame at this site, so one is built in-module by the
branch-free Duff et al. 2017 construction (`sign = copysign(1, N.z)`,
`a = −1/(sign + N.z)`, `b = N.x·N.y·a`), which is total: no branch, no
singularity, no normalisation. The taps are a fixed stratified cosine-weighted
set, `u_j = (j+0.5)/K`, `r = √u`, `cz = √(1−u)`, azimuth by the golden-ratio
increment — read back out of the shipped `.spv` by gate 8, not trusted:

```
K=4:  (+0.354, 0.000, 0.935) (−0.452, −0.414, 0.791) (+0.069, +0.788, 0.612) (+0.569, −0.742, 0.354)
K=8:  cos θ = 0.968 0.901 0.829 0.750 0.661 0.559 0.433 0.250
```

The set is rotated about N by one angle per pixel, hashed from
**`BuiltIn LaunchIdKHR`** (`x·1103515245 ⊕ y·2654435761`, ×2246822519, >>8,
scaled to 2π) and applied *once* to the basis (`Tr = T·cos + B·sin`,
`Br = B·cos − T·sin`), not per tap. This is the choice the brief asked to be
stated: **the rotation is pixel-seeded and frame-stable.** No PRNG value is
harvested, and no per-frame state enters the paint chain — `98` §12.6's rule.
The consequence is honest and worth stating: the estimator's ±0.008 (K=4)
quantisation is a **fixed spatial dither**, not temporal noise; it will not
scintillate, and the denoiser cannot average it away either.

### 2.4 The one place this is NOT a single-variable A/B

The standing base `-cone2all-fog` was built **before** `90`'s gate fix, so on
**5 of 12** permutations its cone gate reads the *sample* counter rather than the
path counter. Re-derived per module, those five are exactly `90` §1's list:

`1271d3815051da17` `25b54fc4a17688df` `40c6faab52a13874` `852b31a841b85b26` `ab7f1822eeb0331b`

`contact-rq` gates on the **path** counter in 12/12. So on whichever permutation
the frame actually runs, if it is one of those five, the A/B carries a second
difference (which path segments the term fires on). This is recorded rather than
hidden; the fix is to A/B against `-cone2allgf` (the gate-fixed rung), which is
what §8 specifies, and to read the `skin_sha` and the served permutation out of
the launch log before believing any pixel.

## 3. Replace, not stack — and how that is proven in the shipped bytes

The cone is **not left running underneath**. Two rewrites per cone:

1. the application `occk = OpFMul %float <occ> <k>` has its **first operand**
   redirected from the cone's combined occlusion to our gated `o`. The `k` id is
   *untouched* — `contact-rq` literally uses `88`'s own `%float_0_850000024`.
2. every one of the 6 `flags-16` `OpTraceRayKHR` cone taps has its **cull mask
   operand rewritten to `%uint_0`**, i.e. every cone ray is now a guaranteed
   miss.

3 cones replaced and 6 taps neutered per module × 12 = **36 / 72** per live rung.

`dev/verify_contact_rq.py` then proves it from the shipped `.spv`, two
independent ways, neither reading the patcher's report:

* **the cone's combine is dead** — `88`'s cosine-weighted combine is the unique
  `OpSelect(_, NClamp(OpFDiv …), +0.0)` in the module; the verifier requires it
  to have **exactly one** mention (its own definition) and no consumer. Its
  result now goes nowhere.
* **the cone's taps are dead** — all 6 flags-16 traces carry cull mask
  `%uint_0`, checked individually.

Anything less would leave the A/B reading *cone × trace*.

## 4. It multiplies. That is where it is visible, and where it is not.

`98` §12.4 measured that a multiply is invisible on unlit pixels and `99` §10.8e
paid for forgetting it. The cavity term is a multiply on **direct** radiance:
`fac = 1 − k·o`, `k = 0.85`. So it is visible exactly where the pixel is
DIRECT-lit and occluded — ear against head, under the collar, philtrum, under
the jaw, between fingers — and it is arithmetically incapable of doing anything
in shade. `101`'s ear glow is an **add** for the same reason in reverse; that
difference is the reason these two documents specify opposite frames.

## 5. The rungs

| rung | K | content sha | raygen-half sha | what it is |
|---|---|---|---|---|
| `contact-rq-ctl` | — | `4dc824ca77d95feb` | `1f09268e3d294697` | k=0 CONTROL, **byte-identical to the base**, digit for digit |
| `contact-rq-hit` | 4 | `aad716e7c28ecdec` | `d318038c8139e850` | DIAGNOSTIC: `o` painted flat as grey, **black = fully occluded**, white = open |
| `contact-rq` | 4 | `96bbf20d190ba2a2` | `22909d908d82d806` | the feature |
| `contact-rq-8` | 8 | `271cec37be77a215` | `2b2f456d4fda4760` | the quality axis, **K is the only variable** |

The base `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog` has content sha
`4dc824ca77d95feb` — the control's sha *is* the base's, after a full
`dis → patcher → as → val` round trip. Coverage is **12 of 12** reference
permutations, better than `101`'s 10/12, because the anchor is `88` §4's
mode-independent material fetch rather than a class compare (the SER
permutations reorder instead of comparing).

**Cost: K ray queries per class-1 skin pixel on the primary hit, per frame** —
4 for `contact-rq`, 8 for `contact-rq-8` — replacing 2–6 `OpTraceRayKHR` cone
taps. Non-skin, non-primary and degenerate-normal pixels issue their K queries
with cull mask 0, which is a traversal that terminates immediately; that cost is
real but small, and it buys a branch-free splice.

## 6. Offline gates — all green (measurement)

`./dev/build_contact_rq.sh`, 10 gates, ~1m30s, every one build-failing:

0. base identified from its `MANIFEST`.
1. **round-trip neutrality**: `spirv-dis → spirv-as` reproduces the base bytes
   on **12/12** before any rewrite. Without this the control proves nothing.
2. patch + assemble four rungs × 93 modules.
3. coverage census: 12/12 patched, 3 cones + 6 taps found and rewritten in each.
4. instruction census **on the shipped bytes**: 48/48/48 (K=4) and 96/96/96
   (K=8) Initialize/Proceed/Type triples, **0** committed-T getters, **0** added
   `OpTraceRayKHR`, **0** live cone taps; `-hit` paints 25 writes and skips 26 by
   name (constant-zero or scalar-broadcast).
5. **k=0 identity**: `contact-rq-ctl` is 93/93 `cmp`-identical to the base.
6. `verify_contact_rq.py` ALL PASS on `-hit`, `contact-rq`, `contact-rq-8`
   (13 check groups, re-derived from the shipped `.spv`: K, flags, tmin, tmax,
   the Duff basis, the path-counter operand, the class gate, the launch-id
   provenance, tap unit-length / hemisphere / distinctness, the cone-dead
   proof, the taps-neutered proof, 0 added traces) + `--negative` CLEAN on the
   base.
7. **non-vacuity: 16 rejections.** Five purpose-built decoy *builds*
   (`flags` → `101`'s 545, `tmax` → 18 mm, `counter` → the legacy sample
   counter, `stack` → the cone left live, `basis` → a broken frame), plus the
   base, the control, `-hit` read as the darkening rung and vice versa, K=4 read
   as K=8 and vice versa, `earglow-rq`, `earglow-rq-hit`, `hunt-rayq-p` (all
   three *are* ray queries in this raygen — and all three are the wrong
   question), and `-cone2allgf` (the A/B partner).
8. **closed-form estimator check (numpy)** against the tap coefficients read
   back out of the shipped `.spv` — a synthetic half-space wall parallel to the
   surface, `o` vs a continuous cosine-weighted integral:

   | wall | K=4 | K=8 | continuous |
   |---|---|---|---|
   | 1 cm | 0.4456 | 0.4424 | 0.4374 |
   | 5 cm | 0.1996 | 0.1970 | 0.1966 |
   | 9 cm | 0.0220 | 0.0172 | 0.0186 |
   | 11 cm | 0.0000 | 0.0000 | 0.0000 |

   max error 0.0082 (K=4), 0.0051 (K=8); **exactly 0 past tmax**, which is the
   part that matters — the term has a hard 10 cm horizon and nothing leaks past
   it. (Note the ~0.44 rather than 0.5 at 1 cm: cosine weighting means the taps
   near the horizon, which a nearby parallel wall does not block, carry real
   weight. This is the estimator being correct, not a bias.)
9. MANIFEST provenance (`src_ser`/`ser_sha`/`ptq_sha`) carried verbatim, so
   `sync_settings.sh` will not refuse.

## 7. Driver self-test — 22/22 (measurement)

`./dev/selftest_contact_rq.sh`, new file (`101`'s and `98`'s are untouched;
run all three). RTX 4070. `spirv-val` is not a driver: it never lowers four
`OpRayQueryInitializeKHR` in a row and has no opinion on a raygen that both
traces the engine's rays and runs ours.

* **A (6)** — the layer puts `VK_KHR_ray_query` on a `VkDevice` the application
  created **without asking for it** (vkd3d-proton never does); a synthetic
  raygen carrying the splice shape — flags 517, four Initialize/Proceed/Type
  triples, no T getter, the Duff basis, the launch-id hash and its Cos/Sin, the
  1/K average, every foldable operand made dynamic off the launch id so
  "compiles" cannot mean "dead-code-eliminated" — is accepted by
  `vkCreateShaderModule` **and links into a real RT pipeline**. Tap constants
  imported from `patch_contact_rq.taps(4)`, not retyped.
* **B (8)** — all four rungs' **real ~300 KB raygens**, served through the
  layer's first-file-wins overlay path from symlinks to `swaps.<rung>/` (never
  copies), 12/12 each at their shipped byte size, `swap:HIT result:0`.
* **C (5)** — `CALLISTO_RAYQ_DISABLE=1`: 12/12 `rayq_reject` with
  `action:next_overlay`, and all 12 land on the **next overlay**, not vanilla.
* **D (3)** — the k=0 control under the same guard has nothing to reject and is
  served anyway.

The painted-id set is derived by `cmp` against `-ctl`, not typed in, and the
script **asserts 12** (`101`'s asserts 10). The layer manifest is renamed
`VK_LAYER_CALLISTO_contacttest` because the loader dedupes implicit layers by
name and would otherwise bind the installed `.so`.

## 8. The shoot — READ THIS BEFORE LAUNCHING

**Settings, stated now, before any frame. Do not infer them from a capture
afterwards.**

| setting | value | why |
|---|---|---|
| `ser` | **`class`** | the rungs carry SER-permutation raygens |
| `shadowset` | **`full-shadow`** — NOT optional | any rung shipping raygens needs it |
| `ptq` | unchanged from the standing default | `ptq_sha` must match or `sync_settings.sh` refuses |
| RR | **OFF** | |
| path tracing | ON, reference/photo mode, camera **pinned** | the term only exists on the primary hit |
| frame generation | **state it** | `100` §7's lesson |
| sun | **HIGH — ears, neck and under-chin in DIRECT sun** | a multiply is invisible in shade (§4) |
| `skinspec` | one of the four rows added to `init.lua` | |

**Precondition, non-negotiable (`101` §10 row 0, `99` §10.8e):** before reading a
single colour, grep the launch log for `skin_sha` and confirm it equals the §5
sha for the rung you think you shot, and confirm the served
`rgs_reference_main` permutation. `101`'s entire capture was void for want of
this check.

**Order: shoot `contact-rq-hit` FIRST.** It is the only rung that can falsify the
mechanism, and every reading below is conditional on it.

**The frame** — one shot, all four rungs, camera identical:
a face in **direct sun**, with (a) an ear against the head, (b) a collar against
the neck, (c) a hand near the face, and (d) open forehead/cheek in the same
frame as an unoccluded reference. Then the identical frame on `-ctl`, and the
identical frame on `gi-50b-bleed-oil-sheen-deep-clothhi-cone2allgf`.

`98` §3.4's caveat applies and is pre-registered as row 4: a ray *query* reads
the TLAS, which at a moving object's silhouette can disagree with the raster
G-buffer the pixel was shaded from. Expect the disagreement at **movers**, not
on a pinned head.

## 9. Pre-registered interpretation table (prediction — written BEFORE the screen)

**Read `-hit` first. Rows 1–4 are read off `-hit` alone.**

| # | reading | what it means | what to do |
|---|---|---|---|
| 1 | `-hit` is **dark in ear crevices, under the collar, in the philtrum and under the jaw**, and **white on the forehead and open cheek** | the trace works, the origin is on the surface, tmin and tmax are right. This is the pass. | go to rows 5–8 |
| 2 | `-hit` is **black everywhere on skin** | tmin is too small relative to the geometry — every tap self-hits the surface it started on. (Or the 0.1 mm N-push lands inside a coincident shell.) | raise tmin to 5 mm and the push to 1 mm; one new rung, one variable |
| 3 | `-hit` is **white everywhere on skin, no hits at all** | either tmax is too short for this geometry, or the origin is not on the surface (the cone origin is not the point I think it is). **Compare directly with `101`'s `-hit` on the same head** — `101` uses the same origin. If `101`'s `-hit` shows structure and this does not, tmax/direction is the fault; if both are blank, the origin is wrong and both docs are affected. | do not touch `k`; diagnose the origin first |
| 4 | `-hit` shows **noise/flicker at the silhouettes of moving objects** but is stable on the pinned head | `98` §3.4, expected, not a bug — the query reads the TLAS and the pixel came from the raster G-buffer | record it; it does not affect the head reading |
| 5 | `contact-rq` darkens **the same places as `-cone2allgf` but tighter / more localised**, and the open forehead is unchanged | **the pass.** `88` §2c was right that the cone is a grazing-angle proxy; the trace is the term the doc always wanted | shoot the K axis (row 9), then tune `k` — not before |
| 6 | `contact-rq` darkens **everything, including the open forehead and cheek** | estimator bias: the hemisphere is finding the head itself (a curved surface occludes its own low-angle taps within 10 cm). This is the real risk of a 10 cm radius on a head-sized object. | cut tmax to 3 cm, or subtract the flat-plane baseline `o` — one new rung, one variable |
| 7 | `contact-rq` and `-cone2allgf` are **indistinguishable** | the cone was already a good enough visibility estimate at this scale, and 4 rays/pixel buys nothing | park the whole family; `88` §11's authored-AO census is the better lead |
| 8 | `contact-rq` looks **worse** — banded, blotchy, or dithered | K=4's ±0.008 fixed spatial dither (§2.3) is visible at k=0.85 | read `contact-rq-8` in the same frame before concluding anything |
| 9 | `contact-rq-8` is **visibly smoother than `contact-rq`** | K is the binding constraint; the term needs ≥ 8 rays | price it — time both, and read `88` §5c's warning about cost inside the light loop |
| 10 | `contact-rq-8` is **indistinguishable from `contact-rq`** | K=4 is enough; ship the cheap one | |
| 11 | **`contact-rq-ctl` is distinguishable from the standing default** | the layer is not serving what it claims, and **every A/B in this repo inherits the doubt**. This would be a headline finding, not a footnote. | stop; re-run §7's self-test and the deploy `cmp` before reading anything else |
| 12 | the log's `skin_sha` does not match §5, or names an unpatched permutation | **VOID.** No colour in the frame means anything. | re-launch |
| 13 | skin shows no effect **and the skin in frame is not in direct sun** | **VOID, not a null.** §4: a multiply cannot act on zero direct radiance. `99` §10.8e paid for this row once. | re-frame with the sun on the face |

## 10. Files

New, none shared and none edited:
`dev/patch_contact_rq.py`, `dev/verify_contact_rq.py`, `dev/build_contact_rq.sh`,
`dev/selftest_contact_rq.sh`.

Imported unmodified: `patch_skin_brdf` (`apply_edits`, `roundtrip_check`),
`patch_chs_brdf` (`load_lenient`), `patch_compute_brdf` (`find_image_writes`,
`detect_target_env`), `patch_subtype_probe` (`_gi_zeroish`), `patch_cavity2`
(**`find_path_counter`** — `90`'s detector, the only correct one),
`patch_earglow_rq`, `patch_rayq` (`_add_header`), `cfg_dom`.
`dev/patch_rayq.py`, `dev/patch_earglow_rq.py`, `dev/verify_earglow_rq.py`,
`dev/build_earglow_rq.sh` and `dev/selftest_earglow_rq.sh` were **read and not
edited**.

Four `init.lua` rows added (nothing else in that file touched).
Deployed: `make install`; 93/93 `cmp`-identical installed-vs-built on all four
rungs; live CET `init.lua` identical to the repo. **Nothing committed.**
