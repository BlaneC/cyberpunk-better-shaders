# 72 — The peach fuzz was invisible by construction. Rebuilt as a real lobe, plus an oil layer.

Written 2026-08-31 on the user's report that `gi-50-bleed-sheen` is
*"extremely subtle"* in their own A/B while vanilla skin *"looks super dry"*,
with two asks: add a **subtle oil layer on the characters**, and **review the
sheen shader's quality**. Nothing here has been on screen yet. Everything is
built, verified offline, parked and deployed; `72` is a *build* document, and
the only thing that can promote it is a launch.

## 0. Verdict

| question | answer |
|---|---|
| is `gi-50-bleed-sheen` weak because of a tuning miss? | **No — because of its FORM.** Measured: it scales the base specular by **1.0000–1.0466** over the whole face (§1). A ≤5% lift on a term that is itself ~0 at a rim is nothing, at any `k`. |
| can the multiplicative form be fixed by raising `k`? | Only by making the *highlights* hot — the factor multiplies where the GGX lobe already is, which is the one place fuzz should not be. Wrong lever. |
| what replaced it | the same Estevez–Kulla Charlie × Neubelt lobe, **ADDED** at the site's own `D·Vis` product, class-1 gated, carrying the site's own light cosine (§2). |
| does the new form have a defensible amplitude? | Yes — calibrated offline against the one on-screen sample (`58`'s `k=8` probe read as blown white). `dev/fuzz_model.py` reproduces both (§3). |
| the oil | the tier-3 wet-skin gloss (`27` Phase 2) switched on over the standing compute build, at the **subtle** end (§4). It was OFF in every `gi-*` rung — `G0` in the ladder is `n_s=0.5, spec_gain=1.0, alpha_max=1.0`, which emits nothing. |
| four bugs found in the shader while reviewing it | §2.2 — one of them (an unclamped cosine driving `V_neubelt` to its ceiling on backlit skin) is the `69` "lightbulb" failure mode waiting to happen. |

**Parked and selectable now** (deployed 14:17 via `make install`):

| rung | what it adds over `gi-50-bleed` | one variable vs |
|---|---|---|
| `gi-50-bleed-oil` | the oil only | `gi-50-bleed` |
| `gi-50-bleed-sheen2` | the fuzz lobe only | `gi-50-bleed` |
| **`gi-50-bleed-oil-sheen`** | **both — the candidate** | `-oil` and `-sheen2` |

`gi-50-bleed-sheen` (the 58-era rung) stays parked and stays in the CET list,
relabelled so nobody A/Bs it by accident.

## 1. Why the shipped sheen reads as nothing

`gi-50-bleed-sheen` computes, at every class-1 GGX site:

    factor = 1 + k · min(D_charlie(a, NoH) · V_neubelt(NoL, NoV), cap)
    spec' = spec · factor                       k = 0.15, a = 0.35, cap = 4

`dev/fuzz_model.py` evaluates that over the (view, light) hemisphere with the
shipped constants. The factor, on skin at authored roughness 0.5:

    view  |  L=10    L=30    L=50    L=70    L=85      (light on the viewer's
      0   | 1.0000  1.0006  1.0025  1.0059  1.0095      side — the sheen band)
     30   | 1.0014  1.0041  1.0086  1.0148  1.0203
     60   | 1.0060  1.0115  1.0200  1.0326  1.0466
     80   | 1.0109  1.0184  1.0311  1.0575  1.1151
     88   | 1.0132  1.0214  1.0364  1.0753  1.2423

Over the hemisphere the median lift is **0.56% of the local diffuse**, p90
**3%**; it only reaches 1.24× within ~2° of the silhouette *with the light
equally grazing*. The docstring that shipped with it claimed "at grazing
D·V ~ 2, so k=0.15 reads as a ~30% boost on the rim" — that is wrong by
roughly 30×, and it is the whole story of the A/B.

The structural reason, which no `k` fixes: **a multiplicative term cannot
create what the base lobe does not have.** Peach fuzz is precisely the
grazing energy GGX has none of. Multiplying gives you a slightly brighter
highlight (where fuzz should be invisible) and nothing at the rim (where it
should be the feature).

## 2. What the fuzz is now

### 2.1 The form

At each class-1 GGX site, spliced at the site's own `D·Vis` product:

    fuzz  = min(D_charlie(a, NoH) · V_neubelt(NoL, NoV) · (2+1/a)/2π, cap)
    spec' = spec + select(class 1, k · fuzz · cos_site, 0)

`--peach-mode add` (the default) is this; `--peach-mode mul` still rebuilds
the 58-era form, so that rung is reproducible.

Why an *added* lobe at this splice point is safe — the `38` 0d / `39` §3.3
tile-grid lesson, point by point:

- everything the module applies downstream of the splice applies to the fuzz
  too: Fresnel, light colour, shadow, and the module's own `NMin(x, 100)`
  firefly clamp. Unlit and shadowed skin stay black because **the light is
  zero**, not because the lobe is. This is the same splice the `58` probe
  used, and that probe painted lit surfaces only — no grid.
- `cos_site` is the light cosine **the site itself folds into `D`**
  (`_fold_cosine`), so the fuzz dies at exactly the terminator its base term
  dies at. Census: 401 of 457 sites are `vd = D·NoL, spec = vd·Vis`; the
  other 56 are the cheap-Vis form `vd = D·Vis, spec = vd`, which folds no
  cosine here and whose two cosines are unlabelled (V_neubelt is symmetric,
  so the shape cannot say which is `NoL`). Those fold `min(c0, c1)` — ≤ NoL
  whichever it is, conservative by construction, and it still dies at the
  terminator instead of holding full strength on backlit skin.
- class-1 gated: non-skin pixels are the parent rung's bytes, asserted by
  build.

### 2.2 Four defects found reviewing the shipped shader

1. **Unclamped cosines → maximum fuzz on backlit skin.** `V_neubelt` divides
   by `4(NoL + NoV − NoL·NoV)`. A census of both cosines at all 457 sites:
   457 are `NMin(NMax(x,1e-6),1)` and 337 are `NClamp(x,0,1)` — provably in
   [0,1] — but 104 are an `OpPhi` and **16 are a bare `OpDot`**. A bare dot
   goes negative wherever the shading normal faces away from the light; the
   denominator then goes negative, is caught by the `NMax(q, 1e-4)` floor,
   and the lobe evaluates at its **ceiling** exactly where the surface is
   backlit. Fixed: `_in_unit` proves saturation (resolving `OpPhi` operands
   recursively — all 104 phis pass) and a real `NClamp` is emitted only for
   the 16 that cannot be proven. In the multiplicative rung this was a
   ≤1.6× lift on a near-zero term; in an added lobe it would have been the
   `69` "lightbulb".
2. **No duplicate guard on the spliced product.** Two GGX sites resolving to
   one `D·Vis` product would make the second `replace_all_uses` a silent
   no-op (the `08-DUAL-LOBE` lesson) while still counting as coverage. The
   bleed pass has had a `dup` guard since `53`; the sheen had none. Added,
   reported, and measured: **0** duplicates today.
3. **The amplitude claim in the docstring was unmeasured** and wrong by ~30×
   (§1). Replaced with numbers the model prints, and the model is in the
   repo.
4. **~20 lines of the lobe were copy-pasted** between `build_sheen` and
   `build_peach`, so a fix to one would silently miss the other. Factored
   into `_emit_fuzz_lobe`, with the emission order preserved: rebuilt in
   `--peach-mode mul`, **2 of the 4 spot-checked modules come back
   byte-identical** to the parked 58-era rung, and the two that differ are
   exactly the modules holding an unprovable cosine (defect 1). That is the
   refactor's inertness proof and the fix's blast radius in one check.

### 2.3 Coverage (from the per-module reports, never a byte diff — the `42` rule)

    77 modules, 457 sites over 473 GGX sites, 16 skipped_shape,
    0 skipped_dom, 0 skipped_dup
    401 sites fold the site's own light cosine, 56 fold min(c0,c1),
    16 cosines clamped

Identical numbers for both parents, which is what makes "oil" and "fuzz"
separable in the ladder.

## 3. Calibration — where `k = 1.0` comes from

`k` is measured **at the splice point**, upstream of the module's own Fresnel
multiply. In the geometry this lobe lives in (light on the viewer's side,
both vectors grazing) the half vector sits between two nearly parallel
vectors, so `VoH ≈ 1` and **F sits at its floor, f0 ≈ 0.028, across the whole
sheen band**. The fuzz is attenuated ~36× by a term that has nothing to do
with it — which is why `k` of order 1 is right here and 0.1 is not.

At `k=1.0, a=0.35, cap=1.0`, the added lobe as a **fraction of the local
diffuse** (`./dev/fuzz_model.py`):

    view  |  L=10   L=30   L=50   L=70   L=85
      0   |  0.0%   0.1%   0.6%   1.4%   2.3%     head-on: no wash
     30   |  0.3%   1.0%   2.0%   3.5%   4.8%
     60   |  1.4%   2.7%   4.7%   7.7%  10.9%     cheek / jaw rim: the feature
     80   |  2.6%   4.3%   7.3%  13.5%  27.0%
     88   |  3.1%   5.0%   8.5%  17.7%  35.2%     last degree of silhouette

Anchors: the `58` probe (`k_sheen=8`, ungated, no cosine fold) reaches
**316%** of the local diffuse at view 80° / light 70° — that is the "blown
white" the user read on screen, and the model reproducing it is the reason to
trust the rest of the column. The 58-era rung sits at 0.0–1.5% over the same
face. This build sits between them, an order of magnitude below the probe.

Softer or louder is one command, no code change:

    ./dev/build_gi_bleed_sheen.sh --install --parent real-gloss-bleed-oil \
        --name gi-50-bleed-oil-sheen --set k_peach=0.5     # or 2.0

## 4. The oil

The tier-3 gloss (`27` Phase 2, `33` §2) has been in the tree since August and
**off in every `gi-*` rung**: the ladder's `G0` (`n_s=0.5, spec_gain=1.0,
alpha_max=1.0`) is the identity and emits nothing. So the oil is one
conceptual variable to switch on, not new code:

    real-gloss-bleed-oil = real-gloss-bleed + n_s=0.60, spec_gain=1.0, alpha_max=0.16

Everything else (`alpha_scale=0.7`, `dcouple`, `micro_k`, `eye_alpha_max`,
`bleed_k`) is held at the parent's values, so `gi-50-bleed` → `gi-50-bleed-oil`
moves the gloss and nothing else.

What each half does, from the model:

- **`alpha_max = 0.16`** (a roughness ceiling of 0.40) is the dominant lever.
  Authored skin sits at roughness 0.40–0.60; `alpha_scale=0.7` has already
  pulled that to 0.335–0.50, so this ceiling bites the rougher half only.
  In the mirror band it makes the highlight **1.20–1.28× brighter and
  tighter**; off the mirror it dims slightly (a tighter lobe concentrates).
  That is the wet look: a smaller, harder highlight, not a brighter face.
- **`n_s = 0.60`** widens the Fresnel falloff (exponent 5 → 4): **+52% F at
  60° of view, +31% at 75°, +9% at 85°**. It is the grazing half of "wet".

Started subtle deliberately: a *ceiling* flattens the authored pore/forehead
/cheek roughness variation above it (`33` §5), so it is the one knob on this
rung that can cost detail. `real-gloss-bleed-oil-x` (`n_s=0.70,
spec_gain=1.2, alpha_max=0.09` — the ladder's `medium`) is defined and one
command from parked if the A/B says "more":

    ./dev/patch_compute_skin.sh --only real-gloss-bleed-oil-x
    ./dev/build_gi_bleed_sheen.sh --install --parent real-gloss-bleed-oil-x \
        --name gi-50-bleed-oil2-sheen

## 5. What was verified, offline, before any launch

`./dev/verify_gi_ladder.sh` (new) — **all checks pass**:

- all five rungs carry the same 93 module file list;
- **0 of 16 raygens differ from `gi-50` in every rung** — the one-variable
  guarantee, half 1;
- every pair differs on 77 of 77 compute modules — no two rungs are the same
  build under two names;
- the provenance `sync_settings.sh`'s `gi_refuse` block re-checks at launch
  (`src_ser=ser.set/class`, `ser_sha`, `ptq_sha`) matches for all five;
  `ptq_sha` resolves to the parked **`rcbm/base`** combo, i.e. all four PT
  switches on. (Between launches `swaps.ptq/` is empty — it is materialised
  by `sync_settings.sh` — so the script falls back to matching the parked
  combos rather than reporting a false stale.)

Plus, from the builds themselves: every module `spirv-val` clean, coverage
asserted from reports, and the compute half asserted to differ from its
parent (the "the splice emitted nothing" trap).

**Not verified:** anything about how it looks. No launch, no pixels.

## 6. The A/B runbook

Required settings — state them **before** the launch, never infer them after
(the standing rule). The live `brdf_params.txt` right now reads `skin=off`,
`skinspec=earglow`, i.e. the other track's control; these rungs are dead
unless `skin=on`:

    tier=on
    kernel=spectral
    skin=on                      <-- currently OFF in the live file
    shadowcull=on
    shadowset=full-shadow        <-- gi_refuse refuses otherwise
    skinspec=gi-50-bleed-oil-sheen
    ptreg=on  ptclamp=on  ptbounce=on  ptmsggx=on   <-- the rcbm combo the
    ptrefl=on                                            rung was baked on
    ser=class                    <-- gi_refuse refuses ser=off

Game settings to pin for a comparable pair: PT on, PT-in-photo-mode on, **RR
off**, DLSS Balanced, RayTracedLighting Psycho, 2560×1440 — the same contract
as `58`/`63`.

Order, cheapest first:

1. `gi-50-bleed` (the standing rung) → `gi-50-bleed-oil-sheen`. If the
   difference is obvious and liked, stop; the ladder below only matters if it
   is not.
2. If it reads as "too much" or "wrong in one specific way", the two
   attribution rungs separate the causes in one more launch each:
   `gi-50-bleed-oil` (is it the gloss?) and `gi-50-bleed-sheen2` (is it the
   fuzz?).
3. Shoot the same camera each time; `a-b-testing/collect.sh` snapshots
   `UserSettings.json` into the rung dir, so RR state is a recorded fact.

What to look for, pre-registered so the read is not free-form:

| where | fuzz should | oil should |
|---|---|---|
| cheek / jaw / nose silhouette against a bright background | gain a soft light edge, strongest where the light grazes from the camera's side | — |
| forehead, cheekbone highlight | nothing | tighter, brighter, smaller highlight |
| face turned away from the light (terminator) | nothing (the cosine fold) | — |
| eyes, hair, clothing, chrome | **nothing at all** — class-1 gate | nothing |
| pore / skin texture in the lit half | — | may flatten where the ceiling bites; this is the oil's known cost |

A **failure** to pre-register too: if the fuzz only shows on the last degree
of silhouette and nothing on the cheeks, that is the Fresnel weighting in
§7.1, not a `k` problem — do not raise `k` for it.

## 7. Risks and what is not proven

1. **The fuzz inherits the base material's Fresnel** because it is spliced
   upstream of it. Across the sheen band `F` swings 0.028 → 0.87, so the lobe
   is ~30× stronger on the last degree of silhouette than on a cheek. The
   model's hemisphere max is **780% of the local diffuse** at
   view 88°/light 88°, though in absolute terms that is 0.022 against a lit
   face's ~0.05 — a fine bright edge, not a blowout. If the A/B says the
   effect is all edge and no cheek, the lever is a `(1 − pow5)` de-weighting
   at the splice (the term the site already computes), **not** `k`.
2. **56 sites fold `min(c0, c1)`**, which is ≤ the true `NoL`. Those sites
   are under-lit rather than over-lit — a conservative error, and they are
   12% of sites spread over 24 of 77 modules, every one of which also carries
   folded sites.
3. **The oil's ceiling flattens authored roughness variation** above it
   (`33` §5). That is the mechanism, not a bug, and it is why this rung
   starts at the ladder's `subtle` step.
4. **Oil and fuzz interact multiplicatively**, and not by accident: `n_s`
   widens the very Fresnel the fuzz is multiplied by, so the combined rung is
   slightly more than the sum. That is why `-oil` and `-sheen2` exist.
5. `--peach-mode mul` is **no longer byte-identical** to the parked 58-era
   rung in the 2 (of 4 checked) modules holding an unprovable cosine — the
   clamp fix reaches them. The parked rung's bytes are untouched.
6. Nothing is committed. Nothing has been on screen.

## 8. Levers left, in order of expected payoff

1. Launch it (§6).
2. `k_peach` 0.5 / 2.0 — one command, no code.
3. `(1 − pow5)` Fresnel de-weighting of the lobe, if §7.1 shows up on screen.
4. `real-gloss-bleed-oil-x` for a louder oil (§4).
5. A sheen **tint**: the splice point is scalar, so a warm fuzz would have to
   move to the three per-channel `outs`, which are downstream of the light
   multiply in at least one module family. Not free — do not start it without
   re-reading `_fold_cosine`'s census.

## 9. Confidence

| claim | confidence |
|---|---|
| the 58-era rung is ≤1.05× over the whole face | **certain** — arithmetic on the shipped constants, reproducible with `dev/fuzz_model.py` |
| the new rungs are one variable apart and will not be refused at launch | **certain** — `dev/verify_gi_ladder.sh` |
| the added lobe reaches the screen at all | **high** — same splice, same module family, same class gate as the `58` probe that did |
| it will look like peach fuzz | **unknown — that is the A/B** |
| the oil will read as "wet, not plastic" at this step | **medium** — the ladder's own `subtle` step, and `real-gloss` already won an eyeball A/B (`49`) |

## 10. Files

| file | change |
|---|---|
| `dev/patch_subtype_probe.py` | `--peach-mode add\|mul`; `_emit_fuzz_lobe`, `_saturate_cosines`, `_in_unit`/`_nonneg`, `_fold_cosine`; dup guard; new knob defaults |
| `dev/patch_compute_skin.sh` | `--only NAME` (build one rung, park it, touch nothing else in `skin.set/`); the two `real-gloss-bleed-oil*` levels |
| `dev/build_gi_bleed_sheen.sh` | `--parent` / `--name` / `--peach-mode` / `--set`; report includes fold + clamp + dup counts |
| `dev/build_gi_bleed.sh` | `--parent` / `--name` |
| `dev/fuzz_model.py` | **new** — reproduces every number in §1, §3, §4 |
| `dev/verify_gi_ladder.sh` | **new** — the §5 checks |
| `init.lua` (+ release copy, deployed) | three selector entries; the 58-era rung relabelled |

`--only` exists because `--sets` **`rm -rf`s every non-probe directory in
`skin.set/`** on every run — right when it rebuilds the whole ladder, fatal
when all you want is one more compute rung, because the composed rungs
(`gi-*`, `earglow`, `sentinel`) live there and are built by other scripts.
