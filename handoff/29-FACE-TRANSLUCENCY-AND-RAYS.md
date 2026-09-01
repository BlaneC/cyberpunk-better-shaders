# 29 — Face translucency (ear/nose backlight) and per-material ray budget: feasibility

Written 2026-08-29. Prompt: *(a) a better face BRDF where ears and nose get
some redness with light passing through — engine SSS and subsurface
translucency are enabled and do not do it; (b) stretch goal: can we spend more
rays only on skin — higher-fidelity shadows and less vague GI across faces?*

**Investigation only. Nothing was built, nothing was patched, nothing is on
screen.** Everything below is read off the shipping exe's string table, the
committed disassemblies in `dev/disasm/`, and `~/callisto_swap.jsonl`.

**Verdict as written, one line: (a) is a GO and it is the best-shaped feature
this project has scoped since the SSS kernel — the exact splice site is a
live, dispatch-proven, already class-1-gated skin arm with N, V, L, sun colour
and the sun shadow mask all in scope, and the only missing input is thickness,
for which three ranked substitutes exist; (b) is a QUALIFIED GO with one
mechanism that must be proven before anything is built — the per-material
gate exists at ray level, the bounce count is a one-`OpSelect` edit, and the
sample count is real but non-trivial loop surgery whose viability rests on a
finding (`GOTCHAS`: "a second `OpTraceRayKHR` does not execute") that this
document argues is narrower than it reads.**

**(a) WAS WRONG.** It was built, it looked bad, three thickness proxies in a
row failed to save it, and it was removed 2026-08-30 — see
`39-TRANSLUCENCY-REMOVED.md`. The "only missing input is thickness" framing
above is the mistake in one clause: thickness was not *missing*, it was
*unavailable at that site*, and a feature whose one required input cannot be
obtained is not a go at any cost. Part B is unaffected and still open.

---

# Part A — ear/nose translucency — BUILT, BAD, AND REMOVED

**This half of the document has been removed. See `39-TRANSLUCENCY-REMOVED.md`.**

Part A was a go, was built, was seen on screen, and was wrong: a
face-wide red wash with a blocky tile grid, glow crossing the face, and
clothing edges on the neck lighting up. Two further shaping terms and a third
build axis were added trying to rescue it. All of it was removed 2026-08-30.

`39` carries the postmortem — the four named mistakes, chief among them that
**this document itself predicted the failure mode** (the term has no per-pixel
shaping; a forehead scores as high as an ear) and the route was taken anyway
because it was ranked cheapest. It also carries the two conditions under which
restarting would be honest, so that none of the analysis below is re-derived
from scratch.

What survives from Part A and is still true, kept because Part B and later
documents cite it:

- **A1** — the engine ships a complete raster-side skin-translucency
  subsystem (`renderstage_skin_translucency`,
  `CRenderNode_RenderSkinBackDepthForTranslucency`, `EMM_SurfaceTranslucency`,
  `CharacterSubsurfaceTranslucency`) and **none of it reaches the traced
  path**. That is why faces go flat against a low sun, and the live-CVar A/B
  in A3 (`CharacterLightBlockers` off) is still free and still unrun.
- **A2** — the compute lighting evaluators read **seven** images, and
  `heap19[pc1+0]` is the front depth (corrected in the course of the build).
- The **dual-lobe skin specular** driven by an 8-entry per-character profile
  table at `cbv99[%414 + 4]`, indexed by bits packed across GBuffer2.w and
  GBuffer3.w bit 6. Not previously documented anywhere; the Tier-3 gloss
  lands on both lobes.
- **A4 R3** — the engine's skin back-depth pass **is found** (depth-only,
  1280x720, uniquely `clear=1.0` for reverse-Z, 25 indexed draws) and **does
  run in Overdrive**, which settles a standing `GOTCHAS 5` worry
  affirmatively. It is still unusable: the bindless heap index moved
  73203 → 503350 across two captures **29 seconds apart in one session**.
  That is now `GOTCHAS` 13 — *existence is not addressability*.

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
| ~~3~~ | ~~**Translucency R1/R2 in the skin arm `%1540`**, ladder of five rungs~~ **BUILT, BAD, REMOVED 2026-08-30 (`39`)** | — | — | — |
| 4 | Second-trace **sentinel** in `rgs_reference_main` — payload written by the miss shader, read after iteration 2 | small | none | nothing in Part B builds before this |
| 5 | Skin bounce count `OpSelect(isSkin, n+2, n)` | tiny | low | 4 |
| 6 | **Skin sample loop** — wire the degenerate outer loop `%12276`/`%12818` | large | medium | 4 |
| ~~7~~ | ~~Translucency R3 — name the back-depth target's heap offset by offline replay~~ **DONE, and it failed outright: the index is not stable (`39` §6)** | — | — | — |
| 8 | Per-skin shadow-ray count in `rgs_shadow_main` | large | high | 4, and 6 landing clean |

Items 1 and 2 need no game launch or need no build, and both are still unrun.

**Update 2026-08-30:** items 3 and 7 are closed. Item 3 was built, observed,
patched twice and then **removed entirely** (`39`) — it is the cautionary
entry in this table, not a completed one. Item 7 is closed negative. Items
1, 2, 4, 5, 6, 8 are untouched, and **item 4 (the payload sentinel) is now
the gate on the only honest way back to item 3** as well as on all of Part B.

**Update 2026-08-31:** item 4 PASSED (`56`). Item 6 is **BUILT, parked,
unlaunched** (`77`) — and §B4's premise was half wrong in a good way: the
degenerate skeleton is the *constant-folded remnant* of an engine sample
loop that is **still alive in the 8 runtime-bound permutations**, bounded by
`cbv[188].y` (`RayNumber`) with per-sample 1/N MIS weights in the body. So
6 of the 10 paintable modules needed only a per-pixel rewrite of every
`cbv[188].y` read; the §B4 phi surgery was performed on the baked 4 alone.
Item 5 (the bounce bump) remains unbuilt — `77` did not touch bounce depth.
Items 1, 2, 8 still stand as written; item 2 gained relevance (`77` §1: the
shader half of `RayNumber` is provably live in the dynamic permutations).

## Corrections and additions to earlier documents

- **`27` §2's skin CVar table is incomplete**: `CharacterSubsurfaceStochastic`
  is a third `Developer/FeatureToggles` key and is not listed there.
- **`27` did not notice that skin runs a dual-lobe GGX specular** driven by
  an 8-entry per-character profile table at `cbv99[%414 + 4]`, indexed by
  bits packed across GBuffer2.w and GBuffer3.w bit 6. The Tier-3 gloss lands
  on both lobes.
- **`22` §3's "`Translucency`: zero hits"** is a word-boundary artifact and
  must not be read as "the engine has no translucency". It does; see §A1
  and `39` §5.
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
