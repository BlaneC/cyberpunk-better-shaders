# 32 — Path-tracer sampling: the engine panel, and the per-material question

Written 2026-08-29. Prompt: *the biggest thing about making faces better is
getting higher-frequency information out of the path tracing where it counts —
add a selector for even higher sample counts just on skin/eyes/hair. I think
there's already increased samples on skin?*

**Verdict, three lines.** There is **no per-material sampling in this engine
today** — nothing spends more rays on skin than on a wall, and the belief that
something does is the one thing in the prompt that is wrong. What *does* exist
is a set of **global** sampling CVars that have never been properly tested,
and those are now a live CET panel (`pt_engine.lua`, built this session, `§2`).
The per-material version is real, is `29` §B4, and is **gated on a sentinel
launch that has not happened** — nothing gets built on it until it does.

---

## 1. "Is there already increased sampling on skin?" — no

Checked against the exe string table and the disassembly, not from memory.
Three things exist and none of them is material-driven:

| what | driven by | material-aware? |
|---|---|---|
| `RayTracing/Reference/RayNumber` | a global spp budget | **no** |
| `…/AdaptiveSampling` + `AdaptiveSamplingRatio` + `TileSize` | screen-space **tile variance** | **no** |
| `CharacterSubsurfaceStochastic` (`29`'s correction to `27` §2) | the SSS blur's sampling, not the integrator's | it is skin-only, but it is not path samples |

`AdaptiveSampling` is the one that *looks* like the answer and is not: it
spends unevenly across the screen by variance, so a face in a shadow gradient
does attract extra samples as a side effect, but it cannot be told "faces".
Worth testing precisely because that side effect is free.

The one genuinely material-aware fact, and it is the enabler for §4 rather
than a feature that exists: **`rgs_reference_main` already fetches the
G-buffer material word and tests a class** (`29` §B2 — `d622fb9e1dcb8cd0`
`:14337–14352`, `(y & ~31) == 160`, i.e. class 5). A skin gate at ray level
costs nothing extra because the fetch is already there. Nothing currently
*uses* it to vary a sample count.

## 2. What was built: `pt_engine.lua`

The engine-first step (GOTCHAS 8), and `29`'s ranked item 2 — the one costed
at "minutes, no risk" and carried unrun. Twelve CVars, the `hair_engine` /
`skin_engine` pattern exactly: master switch default **off**, vanilla
snapshotted from the live engine at init (never hard-coded), applies **live**,
re-asserts every 2 s, own persistence file (`pt_engine.txt`, one writer per
file — `09` I1).

Knobs: `RayNumber`, `BounceNumber`, the `…Screenshot` pair, `SampleNumber` /
`SkipSamples` / `EnableReferenceAccumulation`, the three `AdaptiveSampling*`
keys, `AmbientOcclusionRayNumber`, `EnableReferenceSER`.

### 2.1 The design problem, and the fix

The exe's string table **deduplicates CVar keys**. `RayNumber` appears exactly
once, while `RayTracing/{Reference,Diffuse,Reflection,LocalLight}` could each
own one, so *which group owns which key cannot be read from the table* — it is
an inference from layout. That exact inference has already been made and got
it wrong once (`22` §3 vs `27` §2, on the RT rim keys).

So each knob carries a **list of candidate paths** and resolves at register
time to the first one the engine actually answers on. The resolved path is
printed into the knob's own description; the header counts how many resolved;
unresolved keys are named on the console; and a "Dump RayTracing CVars to
console" button prints what resolved plus whatever `GameOptions.List` will
admit to. A wrong guess degrades to **one dead knob that says it is dead** —
never to a silently inert slider, which is `26` §5's trap (six numeric skin
sliders nothing read, found only after a whole A/B session was shot with them).

### 2.2 What the panel is for

Ultra Plus's author found `RayNumber`/`BounceNumber` and wrote `0xDEADBEEF`
(`-559038737`) into both in `config/debug.ini` — that author's sentinel for
"found it, does not appear to work". **That is a claim, not a finding**, and
`29` §B3 shows the shader half of it *is* real: the path loop's bound is
`bitcast(cbv99[188]).z` at runtime in **8 of the 12** `rgs_reference_main`
permutations (constant-folded to a literal 2 in the other 4). So
`BounceNumber` has a live wire into two-thirds of the permutations. The panel
exists to settle it either way.

### 2.3 Verification

35 stubbed checks, all passing (`lua5.4`, fake `GameOptions` + `nativeSettings`):
path resolution falls through to a later candidate, an unresolvable key is
marked NOT FOUND, snapshot reads the engine rather than the default table, no
writes while disabled, writes while enabled, ints written via `SetInt` with
fallbacks to `Set` then `SetFloat`, the 2 s re-assert repairs drift, disable
restores every snapshot, save/load round-trips ints as ints, a saved "on"
re-applies at register time, `addRangeInt`/`addButton` absent both degrade,
and 0/12-resolved writes nothing at all. `luac -p` clean; all three copies
(repo, `release/`, live install) byte-identical.

## 3. The two costs, restated because they set expectations

**Frame time.** Samples per pixel is linear in path-tracing cost. 2 spp is
about 2× the PT pass. This is a photo-mode and cutscene knob; the engine's own
authors thought so too, which is why the `…Screenshot` variants exist.

**The denoiser is the ceiling, and samples do not move it** (`29` §B7). PT
runs at 1280×720 internally (`15` §1), is reconstructed to 1440p, and
NRD/DLSS-RR then applies a spatial filter. Extra samples on skin enter the
same history and get a radius set by the *G-buffer* material, not by how many
samples were spent. If faces read as *soft*, the lever is the denoiser or the
internal resolution; if they read as *grainy*, this helps. Worth being precise
about which one the complaint actually is — the answer changes what to build
next.

> **CORRECTED 2026-08-31 (`79` §5).** This paragraph said the filter has **no
> material awareness** and that "neither is in this project's reach". Both
> were wrong. NRD takes packed normal+roughness as a **required** input
> (`IN_NORMAL_ROUGHNESS`) and its specular radius scales with roughness —
> which is why `detail_engine.lua` can expose `LobeAngleFraction` at all. And
> the denoiser **is** in reach: `33` built the 22-knob panel over
> `Editor/Denoising/{NRD,ReBLUR,ReLAX}`, and those knobs are live whenever RR
> is off, which is the standing config. The surviving half of the claim is the
> one that matters: *samples* do not move the radius, so `29` §B7's ceiling
> still stands. `43` §3 M1 states the premise correctly; see `79` for why M1
> is nonetheless not the reason anything reads soft.

## 4. The per-material selector: what it takes, and the step that gates it

`29` §B4. The route is not "add a trace" — it is to **wire a loop that is
already there**. `d622fb9e1dcb8cd0` has an outer loop construct (header
`%12276`, merge `%12807`, continue `%12818`) that is **degenerate**: `%12818`
contains only `OpBranch %12276`, and nothing in the module branches to it. It
is a dxil-spirv structurization artifact — a sample-loop skeleton with the
back-edge missing, executing its body exactly once.

Wiring it: a conditional edge into `%12818` with a sample counter, phis in
`%12276` for the three `%half` radiance accumulators and the RNG state, and a
divide by N at `%12807` where an output scale (`%514`) already exists to fold
into. **The RNG comes free** — the LCG state `%704` is *already* a
loop-carried phi, so samples decorrelate without seed surgery and without the
blue-noise LUT that `24` §4 killed. Gated on §1's class test, that is exactly
"more rays only on faces".

**Nothing gets built on it before the sentinel.** GOTCHAS states flatly that a
second `OpTraceRayKHR` spliced into a raygen does not execute in this game,
proven by `sctrl` (`26` §7d). `29` §B5 argues that rule is stated more broadly
than its evidence supports — the bounce loop already traces twice per
invocation and the `ptbounce` edit on that trace ships and is on screen, so
multiple *dynamic* traces demonstrably work; what `sctrl` falsified was a
second *static* trace site in a different shader family. A sample loop reuses
one static site and adds iterations, which is the shape that already works.
**That is a reason for optimism, not a proof**, and this repo has already paid
a full session for building a matrix on an unverified mechanism.

So the order is fixed:

| # | step | cost | gates |
|---|---|---|---|
| 1 | **`pt_engine.lua` A/B** — does any global knob move the picture? | one launch | — |
| 2 | **Sentinel**: miss shader writes a constant into the payload, read back after iteration 2, write somewhere visible | small build + one launch | — |
| 3 | Skin bounce count, `OpSelect(isSkin, n+2, n)` — one `OpSelect`, one `OpIAdd`, byte-exact when off | tiny | 2 |
| 4 | **Skin sample loop** — wire `%12276`/`%12818` across 12 permutations | large; the biggest patcher change since AgX | 2 |
| 5 | Per-skin shadow-ray count in `rgs_shadow_main` | large, high risk | 2, and 4 landing clean |

Step 3 is nearly free but is **the wrong lever for the complaint** (`29` §B3):
more bounces add indirect depth that is dim and nearly converged, not
variance reduction. Build it because it is cheap, not because it answers this.

Note on hair: the prompt asked for skin/eyes/hair. The gate is the same
mechanism for all three (class 1 / 8 / 4), so once the loop exists the class
list is a build knob. Eyes are class 8 (`31` §2).

## 5. Files

| file | change |
|---|---|
| `pt_engine.lua` (new, × 3 copies) | the panel |
| `init.lua` (× 3 copies) | defensive require, register after the skin panel, `onUpdate` hook |
| `skin_engine.lua` (× 3 copies) | `UseAOOnEyes` — `31`'s Phase 0, see that doc |

**Housekeeping found while doing this:** the live install's `init.lua` was
stale (2026-08-29 00:06, one commit behind) and **`skin_engine.lua` was not
deployed there at all** — the skin CVar panel `27` §3 describes as "deployed"
was not in the game folder. All four Lua files are now byte-identical across
repo, `release/` and the live install. Worth a glance before any A/B: the
`27` §4 session's knobs persist in `skin_engine.txt`, and that file will
re-assert extreme values every 2 s if it was left enabled.
