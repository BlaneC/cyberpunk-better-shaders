# 29 — Face translucency (ear/nose backlight) and per-material ray budget: feasibility

Written 2026-08-29. Prompt: *(a) a better face BRDF where ears and nose get
some redness with light passing through — engine SSS and subsurface
translucency are enabled and do not do it; (b) stretch goal: can we spend more
rays only on skin — higher-fidelity shadows and less vague GI across faces?*

**Investigation only. Nothing was built, nothing was patched, nothing is on
screen.** Everything below is read off the shipping exe's string table, the
committed disassemblies in `dev/disasm/`, and `~/callisto_swap.jsonl`.

**Verdict, one line: (a) is a GO and it is the best-shaped feature this
project has scoped since the SSS kernel — the exact splice site is a live,
dispatch-proven, already class-1-gated skin arm with N, V, L, sun colour and
the sun shadow mask all in scope, and the only missing input is thickness,
for which three ranked substitutes exist; (b) is a QUALIFIED GO with one
mechanism that must be proven before anything is built — the per-material
gate exists at ray level, the bounce count is a one-`OpSelect` edit, and the
sample count is real but non-trivial loop surgery whose viability rests on a
finding (`GOTCHAS`: "a second `OpTraceRayKHR` does not execute") that this
document argues is narrower than it reads.**

---

# Part A — ear/nose translucency

## A1. Engine-first (GOTCHAS 8): the feature exists, and it is raster-side

`strings -n 5` over the shipping exe (59,945,608 B, 2026-08-20), the `16` §1
method. The engine ships a complete skin-translucency subsystem:

| string | what it is |
|---|---|
| `Developer/FeatureToggles/CharacterSubsurfaceTranslucency` | the feature gate (already exposed by `skin_engine.lua`) |
| `Developer/FeatureToggles/CharacterSubsurfaceScattering` | its sibling |
| `CharacterSubsurfaceStochastic` | **a third gate, not previously known** — not in `27` §2's table |
| `CRenderNode_RenderSkinBackDepthForTranslucency` | a render node that draws **skin back-face depth** |
| `renderstage_skin_translucency` | a render *stage*, listed among `renderstage_gbuffer_*`, `renderstage_lighting`, `renderstage_hair_*` |
| `EMM_SurfaceTranslucency` | a debug view, sitting among the G-buffer channel views (`EMM_SurfaceAlbedo`, `EMM_SurfaceRoughness`, `EMM_SurfaceHairDirection`, …) |

Read together, that is the textbook thin-surface translucency pipeline:
render the back faces of the head to a depth target, subtract from front
depth, get per-pixel thickness, feed a transmission lobe. It is what would
make an ear glow.

`22` §3 reported "`Translucency`: zero hits, word-boundary exact" over the
same exe. Both are true — `\bTranslucency\b` does not match inside
`CharacterSubsurfaceTranslucency`. **The `22` §3 negative result is about
cloth and must not be carried over to skin**; it is the single most likely
way this document's premise gets contradicted by someone re-reading `22`.

**Why it does not reach the user's face.** `renderstage_skin_translucency`
is a *raster* stage, and the transmission it feeds is consumed by the raster
lighting path. The evidence that it is absent from the traced path is direct:
the cone constant that gates the character back-light logic
(`-0.258819044` = cos 105°) appears **10 times** in the compute lighting
evaluator `4d46848998312027` and **zero times** in `rgs_reference_main`,
`rgs_shadow_main` and `rgs_restirgi_initial_temporal`. Character-specific
back-light handling exists only on the compute side.

The honest statement: the toggle is on, the back-depth node probably still
runs, and nothing in the path the user's pixels take reads a transmission
term. That is consistent with the report ("enabled, does nothing for ears
and nose") and it is why a mod-side term is warranted rather than redundant.

## A2. The splice site, decoded — this is the find

`dev/disasm/compute/4d46848998312027.dxil.spvasm`, 1737 lines. Per the exe's
own shader-object names, this family is
`m_shaderLightsComputeGlobalOnly_Clustered_LightBlockers_` — **clustered
deferred lighting, global (sun/sky) light only, with light blockers**. There
is no loop in the module: one light.

**It dispatches in the user's actual PT session.** From
`~/callisto_swap.jsonl` for the `skin=on skinspec=strong` launches
(`~/callisto_launches.log`, 2026-08-29T00:14:53): all four evaluators
`2e73a32c35778d85`, `4d46848998312027`, `9a3fa53c53a3a21b`,
`20e6c7b3626ae0d6` show **8 `{"ev":"dispatch"}` events each**. That is
GOTCHAS 2 satisfied — execution, not a swap HIT. `swaps.skin` served 77
modules in the same launch.

What the module reads (`:300–400`):

| id | what |
|---|---|
| `%176` ← image `%89` | base colour; `%204/%205/%206` = its square = albedo |
| `%182` ← image `%84` | normal, `rgb − 0.5` decode → `%217/%218/%219` |
| `%188` ← image `%79` | `%190` metalness, `%191` roughness → `%222`, `%193` = packed byte |
| `%194` ← image `%57` (`v4uint`) | material word; `%196` = component 1; **`%203 = %196 >> 5` = material class** |
| `%425` ← image `%69` | light-blocker **direction** (`2x−1` decode) → `%488/%489/%490` |
| `%561` ← image `%74` | **the RT sun shadow mask**, `%563` |

`%193 × 255 → %226` is fully allocated: bit 7 a flag, bit 6 a skin-profile
bit, bits 0–5 a 6-bit `[0,1]` value (`× 1/63`) that becomes the light-blocker
**intensity** `%491`. **There is no spare G-buffer channel here and no
thickness channel** — which independently confirms `11` §2's "no free
channel", now for the skin case.

Then, at `:685`:

```
OpSwitch %203 %1564   0 %1556   3 %1548   1 %1540   4 %1532
                      ^standard  ^?        ^SKIN     ^hair
```

**The skin arm is `%1540`, lines 1061–1306.** Inside it, everything a
transmission lobe needs is already a named value:

| value | ids | line |
|---|---|---|
| N (world normal) | `%319 %321 %323` | 526–528 |
| V (view dir) | `%553 %554 %555` | ~650 |
| L (sun dir, normalized) | `%963 %964 %965` | 1123–1125 |
| sun colour × intensity | `%968 %969 %970` | 1128–1130 |
| **sun shadow mask** | `%568` (from `%563`) | 670 |
| N·L **unclamped** | `%978` | 1138 |
| N·L clamped | `%981` | 1139 |
| N·V | `%1000` | 1160 |
| albedo × (1−metal) | `%339 %340 %341` | 512–514 |
| Disney diffuse scalar (the shipped `c1` site) | `%1029` | 1188 |
| diffuse out, per channel | `%1131 %1134 %1137` | 1290–1296 |
| light-blocker attenuation | `%618` | 1088 |
| final diffuse × blocker | `%233 %238 %243` | 1306–1308 |

Plus, gated on `%352 = (class == 1)` at `:544`, a **per-character skin
profile**: `%414` is a 3-bit index assembled from GBuffer2.w (2 bits) and
GBuffer3.w bit 6 (1 bit), and `%416 = cbv99[%414 + 4]` yields
`%421/%422/%423`. Read against how they are consumed
(`%971 = roughness × %421`, `%974 = roughness × %422`, `%977 = clamp(%423)`),
they are **two roughness scales and a lobe mix** — skin runs a *dual-lobe*
GGX specular that `27` never noticed, with the second lobe added at
`%1119–%1127` weighted by `%977`. Two consequences:

- `27` §7's Tier-3 gloss lands on **both** lobes' Fresnels (both go through
  `find_spec_fresnel_groups`), which is probably fine but was not a
  considered design decision. Worth knowing.
- **There is an existing 8-entry per-character cbuffer table indexed by a
  G-buffer-packed profile id.** That is the natural home for a per-character
  transmission colour, and it is where the game itself would have put one.
  We cannot write the cbuffer, but we *can* branch on `%414`.

## A3. The light blocker is actively fighting the effect

`%488/%489/%490` is a per-pixel blocker direction and `%491` a per-pixel
blocker intensity. At `:1067–1088`:

```
%614 = dot(blockerDir, L)
if  %614 < -0.258819044:                     # sun more than 105° off the blocker axis
      %645 = clamp((%614 + 0.2588) × -2.23071027, 0, 1)
      %646 = %645 × %491                     # ramp × intensity
      %619 = 1 − %646                        # attenuation
      %621 = (%619 <= 0.001)                 # fully blocked → skip the light entirely
%618 = phi(1, %619)
```

This is `Developer/FeatureToggles/CharacterLightBlockers` / `cvLightBlockerInfluence`.
It exists **to stop light leaking through characters from behind** — i.e. it
is precisely the mechanism that suppresses the look being asked for. Two
things follow, and they point in opposite directions:

1. **A free experiment, tonight, zero code.** `CharacterLightBlockers` is a
   `Developer/FeatureToggles` key and `skin_engine.lua` already registers
   feature gates from that group. Turning it off is a live CVar write. It
   will not *create* transmission — nothing computes one — but it will show
   how much backlight the engine is currently subtracting from ears and
   nostrils, and that is the honest baseline any transmission term should be
   judged against. Do this before anything is built.
2. **`1 − %618` is a free, per-pixel, character-shaped "the sun is behind
   this surface" mask.** The engine computes it already and currently only
   ever subtracts with it. It is not thickness — it is coarse and authored
   for occlusion, not transmission — but it is a real signal that separates
   "sun behind the head" from "sun behind a wall", which no purely local term
   can do.

## A4. The one missing input is thickness. Four routes, ranked.

Everything else is live. Ranked by (effect quality ÷ risk):

**R1 — constant thickness × a local thinness proxy. Recommended for v1.**
Ships entirely inside the skin arm, pure ALU, no new descriptors, no new
buffers, no provenance work. Thickness ≈ `k` (a build constant, laddered like
`skinspec`), optionally shaped by `saturate(−N·L)` (which uses the
**unclamped** `%978`, already present) so the term only appears where the
surface actually faces away from the sun. Ears and nostrils dominate visually
because they are the parts you *see* while the sun is behind them — the
falloff comes from the `pow(saturate(V·−L), p)` view term, not from thickness.
**Honest failure mode:** a backlit cheek or forehead also glows, and at high
`k` the whole silhouette reads as wax. This is the term's known weakness and
the reason the ladder must start subtle.

**R2 — R1 modulated by `1 − %618`** (the light blocker, §A3). Same cost, one
extra multiply, and it removes the "glows when the sun is behind a wall"
error class. Prefer this over bare R1 if the blocker signal turns out to be
non-degenerate on faces — which the §A3 CVar experiment answers for free.
Risk: `%491` is 6-bit and possibly authored at low spatial frequency, so it
may be flat across a whole head and contribute nothing.

**R3 — the engine's own back-depth target.** `CRenderNode_RenderSkinBackDepthForTranslucency`
produces exactly the buffer this wants. The evaluator reads images through
the bindless heaps (`heap14[pc1 + N]`, `heap18[pc1 + 6]`, per `15` §1), so a
fifth fetch is structurally trivial — *if* the target's heap offset from the
push-constant base is known and stable. That is a provenance question and it
is answerable **offline**, with no game launch, by the replay recipe in `15`
§0 plus `dev/prov_map.py`. Note `GOTCHAS`' standing caveat: the prov log
covers compute dispatches, and this *is* a compute dispatch, so the method
applies. This is the physically correct route and the only one that will
make a nostril brighter than a cheek. It is also the only one that can fail
outright (the stage may not run in RT Overdrive at all, in which case the
image exists but holds stale or cleared data — a `GOTCHAS 5` contract
violation waiting to happen, and it must be checked, not assumed).

**R4 — author thickness into a texture.** Rejected. `20` §5d's reasoning
applies: it is a per-character asset job in a different toolchain
(WolvenKit), which is `22` §6's argument, and it is not this project's lever.

## A5. The maths, and exactly where it goes

Barré-Brisebois & Bouchard (GDC 2011) "Approximating Translucency", the form
every shipping engine uses:

```
H  = normalize(L + N · distortion)          # L pushed into the surface
T  = pow(saturate(dot(V, -H)), power) · scale
Lt = T · thickness · tint · sunColour
```

All of `L`, `N`, `V` are live (§A2). `tint` is a build constant — a warm
`(1.0, 0.30, 0.15)`-ish red is the point of the request; the per-character
profile index `%414` is available if it should ever vary per character.

**Where it lands matters more than the maths, and this is the trap.**

The whole skin arm sits under `%647 = %568 > 0` (`:1096`) — *the sun shadow
mask*. An ear lit from behind is, at the front face, **shadowed**: `%568 = 0`
and the arm is skipped entirely. **A transmission term spliced inside `%1546`
would be multiplied by zero exactly where it is supposed to appear.** That
is the single highest-probability way this feature ships as a silent no-op
and gets written off as "the splice doesn't work" (`27` §7.5's failure class,
one layer deeper).

So the term must be added at or after the `%1547` phi merge — concretely,
alongside `%233 / %238 / %243` at `:1306–1308`, where the diffuse has already
been multiplied by `%618`. Adding after `%618` also means transmission
bypasses the light blocker, which is what §A3 argues for.

Consequence to state up front: **the transmission lobe is unshadowed.**
Without a back-face shadow query it will appear wherever the sun direction is
behind the surface, including when the *whole character* is in shade. `1 −
%618` (R2) is the only mitigation available at this site; a correct fix needs
a shadow ray, which is Part B's territory and inherits Part B's blocker.

**Energy.** `23` §4's ship-phase requirement applies verbatim: an additive
lobe with no compensating damp brightens every backlit skin pixel. Damp the
diffuse by `(1 − k·max3(tint))` in the same edit, or the feature is a
slow-burn global exposure error of exactly the class this project keeps
catching late.

**Strength is a ladder, not a slider** — `27` §9 settled this and it applies
unchanged: `thickness`, `power`, `distortion` and `tint` are `OpConstant`s,
nothing reads them at runtime, and a CET slider bound to them would be the
inert-slider bug (`26` §5) for the third time. Build
`off / subtle / medium / strong / extreme` rungs into `skin.set/` and let
`sync_settings.sh` pick one, exactly as `skinspec` does today.

## A6. Cost, coverage, and the verification plan

Cost: ~25 ALU inside a branch that only skin pixels take, in a module that
already runs. Negligible.

Coverage: the same 77 modules `dev/patch_compute_skin.py` patches — but the
class-1 **lighting arm** (`OpSwitch %203 … 1 %1540`) is a different anchor
from the class gate the patcher uses today (`acquire_class_shift` +
`OpIEqual %shift %uint_1`). **GOTCHAS 3 applies and is not optional here**:
enumerate the switch across all 84 anchored libs and report how many carry a
class-1 arm, how many carry the light-blocker cone, and how many carry
neither, *before* writing the emitter. The four evaluators inspected here are
a sample, not the schema (`GOTCHAS`: "do not generalise from one sampled
module").

Verification, in order:

1. `CharacterLightBlockers` off, live, fixed face framing, sun behind the
   head. Free, answers §A3. *(No build.)*
2. Offline: the sibling sweep above; `spirv-val`; byte-identical output with
   the feature off; the `--sets` ladder asserting each rung differs from the
   one below (`27` §9.4).
3. One launch, `extreme` rung, the `27` §7.5 warning lines in place, fixed
   framing. `extreme` exists to answer "does it reach the screen", not to
   look good.
4. Come down the ladder.

---

# Part B — spending more rays on skin

## B1. Engine-first, again: what the CVars already offer

New from this session's exe pass, none of it previously in the handoff:

| group / key | note |
|---|---|
| `RayTracing/Reference/RayNumber` | **samples per pixel for the reference path tracer** |
| `RayTracing/Reference/BounceNumber` | bounce depth for the same |
| `RayTracing/Reference/{RayNumberScreenshot, BounceNumberScreenshot}` | a separate, higher budget for screenshots |
| `RayTracing/ReferenceScreenshot`, `EnableReferenceAccumulation` | an accumulation mode |
| `RayTracing/{Diffuse,Reflection}/AdaptiveSampling`, `AdaptiveSamplingRatio`, `TileSize` | **an existing tile-based adaptive sampler** |
| `RayTracing/AmbientOcclusionRayNumber` | RTAO |

Ultra Plus knows about `RayTracing/Reference/{Ray,Bounce}Number` and sets
both to `-559038737` = `0xDEADBEEF` in `config/debug.ini` — its author's
sentinel for "found it, does not appear to work". That is a claim, not a
finding, and it is worth 10 minutes to re-test properly, because §B3 shows
the shader half of it *is* real.

`AdaptiveSampling` is the interesting one: the engine already has machinery
for spending rays unevenly across the screen. It is variance/tile-driven, not
material-driven, so it will not "highlight faces" — but a face in a shadow
gradient is a high-variance tile, so it partially does the right thing for
free, and it is a CVar. **Test it before building anything** (GOTCHAS 8).
Caveat: those two keys live under `Diffuse`/`Reflection`, which are the
RT-not-PT groups; whether they touch RT Overdrive at all is unknown.

## B2. The per-material gate at ray level: available, proven

The enabling fact, and it was not previously written down:
**`rgs_reference_main` already fetches the G-buffer material word and tests a
class.** In `d622fb9e1dcb8cd0` (`:14337–14352`):

```
%1756 = OpImageFetch %v4uint <heap[registers[1] + 5]> …
%1758 = OpCompositeExtract %uint %1756 1
%1788 = OpBitwiseAnd %uint %1758 %uint_4294967264      # & ~31
%1790 = OpIEqual %bool %1788 %uint_160                 # class 5
```

Same packing as the compute side (`%203 = %196 >> 5`), same component. A skin
gate in the raygen is `%1788 == 32`, and it costs nothing extra because the
fetch is already there. The `rgs_shadow_main` family carries the `>>5` shift
in 12 of 13 permutations (only `b88183eb` lacks it), so the gate is available
there too.

**Per-material ray budgeting is therefore mechanically possible.** What
remains is where to spend, and whether the spend executes.

## B3. Bounce count — the cheap lever, and why it is the wrong one

The path loop's bound, swept across all 12 `rgs_reference_main` permutations:

| form | permutations |
|---|---|
| `OpSLessThan %741 %uint_2` — **a baked literal** | `4103c886`, `996a3b16`, `d002cc05`, `d622fb9e` |
| `OpULessThan %897 %2813` where `%2813 = bitcast(cbv99[188]).z` — **runtime** | the other 8 |

So `BounceNumber` **is** live in two-thirds of the permutations, and
constant-folded to 2 in the rest. Making it material-dependent is one of the
smallest edits this project has ever scoped:

```
bound' = OpSelect(isSkin, bound + 2, bound)
```

one `OpSelect`, one `OpIAdd`, reusing the gate from §B2. `spirv-val`-safe,
byte-exact when off.

**But it is the wrong lever for the complaint.** More bounces adds indirect
*depth* — a fourth-bounce contribution that is dim and already nearly
converged. It does not reduce variance, and "low res and vague across faces"
is a variance-and-filter problem, not a truncation problem. Build it if you
want it (it is nearly free, and 3–4 bounces on skin is defensible for
multi-bounce interreflection inside an eye socket), but do not expect it to
answer the ask. Rank it below §B4.

## B4. Sample count — the real lever, and the loop that is already there

`d622fb9e1dcb8cd0` has **two** nested loop constructs:

- inner, header `%12277`, latch `%12786`: the bounce loop, bound 2 (§B3)
- outer, header `%12276`, merge `%12807`, continue `%12818`

and the outer one is **degenerate**: `%12818` (`:14305`) contains only
`OpBranch %12276`, and **nothing in the module branches to `%12818`** —
`grep` finds the label exactly twice, at its own definition and in the
`OpLoopMerge`. It is a dxil-spirv structurization artifact: a loop skeleton
that executes its body exactly once.

That skeleton is a sample loop with the back-edge missing. Wiring it:

1. add a conditional `%12803 → %12818` edge with a sample counter;
2. add phis in `%12276` for the three `%half` radiance accumulators and the
   RNG state;
3. divide by N at `%12807`, where an output scale (`%514`) already exists to
   fold into.

**The RNG comes for free, and this is the part that makes it worth doing.**
The module uses a plain LCG, `x = x·1664525 + 1013904223` (`:1983–1995`), and
its state `%704` is *already* a loop-carried phi
(`%704 = OpPhi %uint %167 %12276 %705 %12786`). Threading it through the
outer header means each sample continues the sequence rather than repeating
it. No seed surgery, no blue-noise LUT — which matters, because `24` §4
killed the blue-noise route and this sidesteps needing it.

Gated on §B2's skin test, this is *exactly* "more rays only on faces".

Honest scope: this is real SPIR-V surgery, not a constant edit. Multi-block
phi insertion across a merge, in twelve permutations, in a module where
dxil-spirv has already produced `frontier_phi_*` ladders. Call it the largest
single patcher change since the AgX work.

## B5. The blocker, and why it is narrower than it reads

`GOTCHAS` currently says, flatly:

> A second `OpTraceRayKHR` spliced into a raygen shader does not execute in
> this game under vkd3d-proton.

Proven by `sctrl` (`26` §7d) and it retroactively voided fourteen shadow-ray
sets. Taken at face value it kills Part B.

**It should not be taken at face value, for one specific reason: the
reference raygen's existing trace already executes twice per invocation.**
The bounce loop runs to bound 2 (§B3) around a single `OpTraceRayKHR` site,
and the `ptbounce` cullMask edit on that trace is on screen and shipping
(`19` §1, `26` §4.3). So *multiple dynamic traces per invocation demonstrably
work in this game*. What `sctrl` falsified is a second **static** trace
**site**, in `rgs_shadow_main`, in a shader whose payload and SBT indices
were being reused by hand.

A sample loop reuses one static site and adds iterations — the same shape
that already works. That is a reason for optimism, not a proof.

**So: run the sentinel first, exactly as `26` §7d itself prescribes.** Write
a constant into the payload from the miss shader, read it back after the
second iteration, and write it somewhere visible. The rule this project paid
a session to learn (`GOTCHAS`: "Verify the mechanism before building the
matrix"; "If a plan has a step whose failure invalidates every later step,
run that step first") applies with full force. Nothing in §B4 gets built
before that launch comes back positive.

## B6. Shadow fidelity on faces

The face's sun shadow arrives at the lighting evaluator as `%563`, a mask
fetched from image `%74` (§A2) and written by the `rgs_shadow_main` family.
"Higher-fidelity shadow across their geometry" means more shadow rays per
pixel with jittered light-area sampling — softer, correctly-penumbral
contact shadow around the nose and eye sockets.

Feasible in principle: `rgs_shadow_main` carries the class shift (§B2), so
the gate is there. But this is the *worst* place to spend the risk budget:

- it is the exact family where `sctrl` failed;
- unlike the reference raygen, its shadow traces are **not** already in a
  loop, so there is no existing skeleton and no evidence of repeated tracing;
- the shadow mask is denoised by NRD's `SIGMA_ShadowTranslucency` chain (the
  `SIGMA_*` strings in the exe), so extra samples land in a filter tuned for
  1 spp input and much of the gain is spatially blurred back out.

Defer. If §B5's sentinel passes in the reference raygen, re-scope this after.

## B7. Two costs, stated plainly

**Frame time.** GPU work is per-warp, not per-pixel. A 32-thread warp holding
one skin pixel pays the whole loop. Faces are spatially coherent so
divergence is modest, but in a close-up dialogue framing a face can be 20–30%
of the screen, and 4 spp on skin is then roughly +60–90% on the PT pass. This
is a photo-mode / cutscene feature far more comfortably than a gameplay one,
and the ladder should say so.

**The denoiser is the real ceiling, and extra samples do not move it.** The
"low res and vague" the user is describing is produced downstream of the
integrator: PT runs at 1280×720 internal (`15` §1) and is reconstructed to
1440p, then NRD/DLSS-RR applies a spatial filter with no material awareness.
Extra samples on skin enter the same history and get the same radius. They
will reduce noise and let more of the true signal survive — they will not
give faces a sharper filter than the wall behind them. Expect a real but
partial improvement, and do not promise a step change. If the actual
complaint is *softness* rather than *noise*, the lever is the denoiser or the
internal resolution, and neither is in this project's reach.

---

## Ranked plan

| # | item | cost | risk | gates |
|---|---|---|---|---|
| 1 | `CharacterLightBlockers` off, live CVar, fixed face framing, sun behind head | minutes | none | — |
| 2 | `RayTracing/Reference/{Ray,Bounce}Number` + `Diffuse/AdaptiveSampling`: re-test Ultra Plus's `0xDEADBEEF` verdict | minutes | none | — |
| 3 | **Translucency R1/R2 in the skin arm `%1540`**, spliced at `%233/%238/%243`, ladder of five rungs | medium | low | the §A6 sibling sweep |
| 4 | Second-trace **sentinel** in `rgs_reference_main` — payload written by the miss shader, read after iteration 2 | small | none | nothing in Part B builds before this |
| 5 | Skin bounce count `OpSelect(isSkin, n+2, n)` | tiny | low | 4 |
| 6 | **Skin sample loop** — wire the degenerate outer loop `%12276`/`%12818` | large | medium | 4 |
| 7 | Translucency R3 — name the back-depth target's heap offset by offline replay (`15` §0) | medium | can fail outright | offline, no launch |
| 8 | Per-skin shadow-ray count in `rgs_shadow_main` | large | high | 4, and 6 landing clean |

Items 1, 2 and 7 need no game launch or need no build. Item 3 is the one that
answers the question that was actually asked.

## Corrections and additions to earlier documents

- **`27` §2's skin CVar table is incomplete**: `CharacterSubsurfaceStochastic`
  is a third `Developer/FeatureToggles` key and is not listed there.
- **`27` did not notice that skin runs a dual-lobe GGX specular** driven by
  an 8-entry per-character profile table at `cbv99[%414 + 4]`, indexed by
  bits packed across GBuffer2.w and GBuffer3.w bit 6. The Tier-3 gloss lands
  on both lobes.
- **`22` §3's "`Translucency`: zero hits"** is a word-boundary artifact and
  must not be read as "the engine has no translucency". It does; see §A1.
- **`GOTCHAS`' "a second `OpTraceRayKHR` does not execute"** is stated more
  broadly than the evidence supports. The reference raygen's bounce loop
  executes its single trace site twice per invocation, and the `ptbounce`
  edit on it ships. The falsified thing is a second *static* trace site in
  `rgs_shadow_main`. §B5 argues the distinction; it does not remove the
  requirement to prove it.
- **`24` §2's "nested-loop path tracer"** is right about the shape and worth
  sharpening: the outer loop is degenerate — its continue block has no
  predecessor — so the integrator is 1 spp × 2 bounces, and the outer loop is
  an unused skeleton.

## Evidence index

- Exe strings: `Cyberpunk2077.exe`, 59,945,608 B, 2026-08-20, `strings -n 5`.
- Lighting evaluator: `dev/disasm/compute/4d46848998312027.dxil.spvasm`
  (class switch `:685`, skin arm `:1061–1306`, skin profile `:546–560`,
  light blocker `:1067–1088`, sun shadow mask `:664–670`).
- Reference raygen: `dev/disasm/live/d622fb9e1dcb8cd0.rgs_reference_main.spvasm`
  (outer loop `:1812`/`:14305`, bounce bound `:14287`, LCG `:1983–1995`,
  material class fetch `:14337–14352`); dynamic bound in
  `dev/disasm/live/1271d3815051da17.rgs_reference_main.spvasm:13795–13799`.
- Dispatch proof: `~/callisto_swap.jsonl` (four evaluators × 8 dispatch
  events); launch attribution `~/callisto_launches.log`, 2026-08-29T00:14:53.
- Ultra Plus CVar claims:
  `<game>/bin/x64/plugins/cyber_engine_tweaks/mods/UltraPlus/config/debug.ini:223–224`.
