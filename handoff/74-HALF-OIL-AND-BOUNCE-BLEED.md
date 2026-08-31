# 74 — Half oil, half fuzz, and the bleed reaches bounce light

Written 2026-08-31 on the user's A/B of `73`'s candidate (launch verified:
`status.txt` `want_skinspec=gi-50-bleed-oil-sheen`, `skin=on`, not refused —
so the read is of the targeted fuzz + the oil's FIRST time on screen):

> *"The gi-50-bleed-oil-sheen is literally perfect... except I need about
> half the amount of oil, and if there's any way to make baby hairs not as
> strong in dimmer lights? Seems like skin is becoming hazy and loses that
> rosy tint in dim lighting/indoors? Maybe just dial back both by 50% ish?
> ... Also can you make sure that bounce lighting is hitting the baby hair
> sheen/proper-bleed-skin-shader/oil aswell?"*

Three asks, three changes. Everything below is built, verified offline,
parked and deployed; nothing has been on screen.

## 0. Verdict

| question | answer |
|---|---|
| why does skin go hazy and lose the rosy tint indoors? | three achromatic/dim-light mechanisms stacking: (1) the oil's widened Fresnel (+52% F at 60° of view) is a grey grazing film under every indoor practical; (2) the fuzz is an achromatic add, and `fuzz/diffuse` is INDEPENDENT of light intensity (`NoL` cancels, §2 of `73`; radiance multiplies both) — so in a dim scene the same fractional add sits over a dimmer, rosier diffuse and desaturates it; (3) **the terminator bleed — the rosy depth — rides the DIRECT term only** (`46` §12, `53` §8.4), and indoors the direct share collapses, so the cue washes out exactly where the user reports it missing. |
| the fix for (1) and (2) | the user's own number: half. `real-gloss-bleed-oilh` (§1) and `k_peach` 1.0 → 0.5 (§2), both now the shipping defaults. |
| the fix for (3) | the bleed now rides bounce light: `gi-50b` = gi-50's raygens + the `53` closed form at the ReSTIR-GI **ST pair's own tail NoL** (§3). One variable vs gi-50: two files. |
| "make the baby hair more only at the edges of specular highlights"? | **already true by construction** — `D_charlie` is an inverted lobe: it is exactly 0 at the highlight centre (NoH=1) and peaks where GGX dies. The instinct is right and was built in from `72`; what the user is seeing in dim light is not highlight-adjacent fuzz but mechanism (2) above, which no shaping fixes — the splice is upstream of the light multiply and cannot know the light is dim. |
| does bounce light hit the oil and the fuzz too? | **No, and it cannot at this splice — and there is nothing for it to hit.** The GI diffuse raygens compute **no view vector** (Lambert needs none; proven structurally, `50` §3.1) and a specular lobe needs V and H, so neither oil nor fuzz can be expressed there. And the probe measured the GI **spec** family's share as **nil** on the test scenes (`50` §2) — bounce specular is not a thing this renderer gives skin to ride. Bounce DIFFUSE skin already carries c1 (`gi-50`, on screen since `50`) and now the bleed. This is the honest full extent of "bounce hits the skin shader". |

**Parked and selectable now** (deployed 15:57, `make install`, backup
`20260831-155741`; deployed `init.lua` cmp-verified against the repo):

| rung | what it is | A/B twin |
|---|---|---|
| **`gi-50-bleed-oil-sheen`** | **rebuilt IN PLACE**: half oil + half fuzz. The live `brdf_params.txt` already selects it — relaunch shows the fix, no setting change. | `gi-50-bleed-oil-sheen-hot` (the 73-era bytes, parked) |
| **`gi-50b-bleed-oil-sheen`** | the same compute half byte-for-byte + gi-50b raygens (bleed on bounce) — **the indoor-depth candidate** | `gi-50-bleed-oil-sheen` (2 files apart) |
| `gi-50b` | bounce bleed alone over real-gloss compute — attribution | `gi-50` |
| `gi-50-bleed-oil` / `gi-50-bleed-sheen2` | the attribution ladder, rebuilt in place at the new half levels | `gi-50-bleed` |

## 1. Half oil — `real-gloss-bleed-oilh`

`n_s` 0.60 → **0.55** (Fresnel exponent 4.0 → 4.5, halfway to vanilla's 5):
grazing F at 60° goes **+52% → +22%** over vanilla. `alpha_max` 0.16 →
**0.2025** (roughness cap 0.40 → 0.45): the ceiling now bites authored
roughness **> 0.538** instead of > 0.478 — half the reach into the authored
0.40–0.60 range — and at the 0.60 end its bite is **1.55×** vs full oil's
2.5×. A ceiling cannot be halved uniformly; this is half the reach and ~60%
of the magnitude, and it entirely releases the mid-rough skin the full cap
was flattening (the `33` §5 cost, now mostly gone). `spec_gain` stays 1.0.
All numbers print from `./dev/fuzz_model.py` §4 (the half column is new).

## 2. Half fuzz — `k_peach` default 0.5

Hemisphere at the shipping cap/defres: median **1.45% → 0.72%**, p90
**7.9% → 4.0%**, max **159% → 79%** of the local diffuse. Every cell of the
`73` §2 table halves — including the front-lit cheek band the user liked, so
this is pre-registered as a possible over-correction: if the bright-light
sheen is now too quiet, the residual complaint pattern is "cheeks lost it
outdoors but indoors is fixed", and the honest next lever is the **warm
tint** (`72` §8.5's per-channel splice, priced, not built), not k back up —
a warm fuzz stops desaturating the dim rosy diffuse at any k.
`--set k_peach=1.0` rebuilds the 73 level in one command.

## 3. The bounce bleed — `gi-50b`

### What it is

At the two spatiotemporal ReSTIR-GI diffuse raygens (`006ba4e3`, `038867e9`),
inside the existing gi-50 c1 splice at the tail shading triple
(`albedo_ch · 1/π · NoL` — the appearance site, `50` §3.3):

    w   = sat(1 − NoL/0.35)²          NoL = the SITE's own cosine, the same
    m_R = 1 + 0.336·k·w                     id the c1 factor consumes
    m_B = 1 − 0.101·k·w                k = 1.0, the compute bleed's amplitudes
    R-FMul ×= select(class1, m_R, 1);  B ×= select(class1, m_B, 1);  G untouched

Same closed form, same Jensen-derived 0.336:0.101 ratio, same band as `53` —
but NoL here is against the **reservoir's sample direction**, i.e. the warm
edge appears where *indirect* light grazes the skin: the soft terminators
that dominate an interior face. The splice sits upstream of the module's own
NaN guard, exactly as the c1 contract requires.

### Channel identity is proven, not assumed

The compute bleed's rule (`39`: never guess R/B) applied to the raygen tail:
`st_triple_channels` walks each triple member → its `albedo·(1/π)` product →
the albedo id → through the measured idioms (frontier/ladder OpPhi chains,
the diffuse-colour FSub — minuend only, the subtrahend roots at the
*metalness* fetch — the white-override OpSelect, the sRGB squaring decode)
to `OpCompositeExtract` components, and **dies** unless all three land on
{0,1,2} distinct of ONE `v4float` fetch. Both ST modules pass; the build
asserts it from the reports (`build_gi_rung.sh --bounce-bleed`), so a wrong
or unprovable channel can never ship as a guess.

### What the SP pair carries: nothing, on purpose

The spatial pair has no angle in scope (it re-weights radiance shaded
upstream, `50` §3.3), and the flat cosine-weighted expectation of the bleed
is E[m_R]=1.007, E[m_B]=0.998 — an order of magnitude below the S3
measurement floor. Emitting it would be an invisible variable. Documented
here instead (`patch_gi_c1.py` header).

## 4. Validation record (all ran, none inferred)

- **Inertness**: `--bleed 0` rebuilds all four raygen splices
  **byte-identical** to the parked gi-50 — the patcher edit cannot have
  moved the standing rung.
- **Emitted-math machine evaluation** (the `53` §4 discipline): the
  `%2582..%2611` chain re-parsed from the emitted `.spvasm` and executed at
  7 NoL points × gate {true,false}: exact match with the closed form, exact
  identity (1,1) with the gate false, all 28 cells.
- **Read in place**: R gets `×g×m_R`, G `×g` only, B `×g×m_B`; the bleed's
  `w` and the c1 factor consume the same NoL id; both select on the same
  class-1 bool; the module's inf/NaN guard and `radiance·W` multiply sit
  downstream. (`%2597–%2611` in the patched `006ba4e3`.)
- **One variable, asserted fatal in the build**: gi-50b vs parked gi-50 =
  exactly the 2 ST raygens differ (names checked), 0/16 others, 0/77
  compute. `gi-50b-bleed-oil-sheen` vs `gi-50-bleed-oil-sheen` = same 2
  files, compute halves byte-identical (77/77 cmp).
- **`verify_gi_ladder.sh` ALL PASS**, both bases: the seven gi-50-based
  rungs (0/16 raygen deltas, 21 pairwise compute deltas all 77/77,
  provenance OK) and, via the new `--gi gi-50b`, the two gi-50b rungs.
- **Ladder coverage identical to `73`**: 457 peach sites / 401+56 folds /
  16 clamped / defres at 457 of 457; bleed 150/23/0; c1 173. The knob
  values are the only change.
- **Sync smoke-run accepted both candidates**: `gi-50-bleed-oil-sheen` and
  `gi-50b-bleed-oil-sheen` both come back `want == req`, not refused, under
  the live `ser=class+hit` (in-skin mode); selection restored to
  `gi-50-bleed-oil-sheen` after the test.
- `spirv-val` clean everywhere (patcher-fatal + per-rung re-check).
- **Not verified: pixels.** Nothing here has been on screen.

## 5. The A/B runbook

Required settings, stated before the launch (standing rule). Unchanged from
`73` §6 — the live file already reads exactly this:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50-bleed-oil-sheen   ser=class+hit (class also fine)
    ptreg=on ptclamp=on ptbounce=on ptmsggx=on ptrefl=on

Game side: PT on, PT-in-photo-mode on, RR off, DLSS Balanced,
RayTracedLighting Psycho, 2560×1440.

1. **Relaunch as-is** — the selection already resolves to the rebuilt
   candidate. Judge the two complaints where they lived: a **dim interior
   face** (haze, rosy tint) and a **bright scene highlight** (oil amount).
   `gi-50-bleed-oil-sheen-hot` is the same-session twin if memory of last
   night is not enough.
2. **The bounce test**: switch to `gi-50b-bleed-oil-sheen`, same dim
   interior, same camera. Pre-registered: the warm red returns on the
   bounce-lit falloff side of an indoor face — the soft edge where the face
   turns away from the room's light; direct-sun scenes should barely move
   (the bounce share is small there). If the difference is invisible
   indoors, `gi-50b` vs `gi-50` is the clean attribution pair (no oil/fuzz
   in either).
3. Attribution if step 1 reads wrong in one direction only:
   `gi-50-bleed-oil` (half oil alone) and `gi-50-bleed-sheen2` (half fuzz
   alone), each one variable off `gi-50-bleed`.

Pre-registered failures, so the next lever is already chosen:
- indoor rosy depth still missing with gi-50b → the residual desaturant is
  the achromatic adds; next is the warm fuzz tint (`72` §8.5), not more
  bleed.
- cheek sheen now too quiet outdoors → `--set k_peach=0.75` splits the
  difference; do NOT raise the oil to compensate, they are separate axes.
- a hard-edged warm band on indoor faces → that is `53` §3's fixed
  band-width stylization showing on bounce light; the fix is a calibrated
  curvature input, not k.

## 6. Risks and what is not proven

1. **The bounce bleed's look is unlaunched.** The band constant (0.35) is
   the direct bleed's stylization; on reservoir-sampled indirect light the
   terminator is as sharp as ReSTIR's angular resolution, so expect a
   softer, wider warm zone than the direct bleed's — plausibly *good*
   (indirect terminators are physically soft), but unseen.
2. **Halving the fuzz halves the liked part too** (§2's over-correction
   row).
3. The `-hot` and `-wide` parked twins now make five look-alike selector
   entries. When the user settles the amount question, delete the losers
   (the `73` §7.4 rule; one `rm -rf` + three init.lua lines each).
4. gi-100 does not get a `b` twin — one bounce variable at a time.
5. Nothing is committed.

## 7. Files

| file | change |
|---|---|
| `dev/patch_gi_c1.py` | `--bleed` (default 0.0 = byte-inert); `_st_albedo_channel`, `st_triple_channels`; per-channel factors in `build_st`; `BLEED_*` constants + the SP-pair rationale |
| `dev/build_gi_rung.sh` | `--bounce-bleed` → builds/parks `gi-50b`; report assertions incl. chans {0,1,2}; the 2-raygen one-variable check vs parked gi-50 |
| `dev/build_gi_bleed_sheen.sh` | `--gi BASE` (default gi-50); **`k_peach` default 1.0 → 0.5**; MANIFEST rewrite generalised to the base's own manifest |
| `dev/patch_compute_skin.sh` | `real-gloss-bleed-oilh` LEVELS entry (n_s=0.55, alpha_max=0.2025) |
| `dev/verify_gi_ladder.sh` | `--gi BASE` for the raygen-identity check |
| `dev/fuzz_model.py` | §4 prints the half-oil column |
| `init.lua` (+ release copy, deployed) | v4 labels; `gi-50b`, `gi-50b-bleed-oil-sheen`, `…-oil-sheen-hot` entries |
| `skin.set/` | `real-gloss-bleed-oilh`, `gi-50b`, `gi-50b-bleed-oil-sheen`, `gi-50-bleed-oil-sheen-hot` new; `gi-50-bleed-oil`, `gi-50-bleed-sheen2`, `gi-50-bleed-oil-sheen` rebuilt in place |
