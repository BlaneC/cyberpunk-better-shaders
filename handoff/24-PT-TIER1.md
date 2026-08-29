# 24 — Tier 1 of the PT brainstorm: built, and what got filtered out

Written 2026-08-28, implementing `23-PT-IMPROVEMENT-BRAINSTORM.md` §1 under
the standing instruction to build the tier-1 ideas **that make sense**. Three
of the four were built and validated; the fourth was investigated and killed by
its own step (a), which is the outcome its plan asked for.

Nothing here has been on screen yet. Everything below is offline-verified
(anchor coverage across every permutation, `spirv-val` clean, materialization
tested through the real `sync_settings.sh`) and nothing below is confirmed to
change a pixel. `10-DISPATCH-TRUTH.md` is the reason that sentence exists.

---

## 1. What shipped

| id | idea | state | toggle |
|---|---|---|---|
| T1.4 | bounce-ray `cullMask` 1 → 255 in `rgs_reference_main` | built, validated | **Bounce rays see hair** |
| T1.4b | the same on the 3 reflection raygens | built, validated | **Bounce rays see hair (reflections)** |
| T1.2 | per-segment indirect radiance ceiling | built, validated | **Firefly clamp (indirect)** |
| T1.1 | path regularization (indirect roughness floor) | built, validated | **Path regularization** (default off) |
| T1.3 | spatiotemporal blue noise | **not built — step (a) came back negative** | — |

All four switches live in the CET page under **Path tracing (RT Overdrive)**
and apply on the next launch.

## 2. The surface, and why it is the right one

`23` §3.1 demands that every splice plan name the render mode it was scoped
against. This one was scoped against the mode in the user's current
`~/callisto_swap.jsonl`: `d622fb9e1dcb8cd0.rgs_reference_main` (×2) and
`4270b745d11a5e8a.rgs_reference_main` (×1) dispatch and trace rays, alongside
the `rgs_shadow_main` family and `rgs_restirgi_initial_temporal` /
`_spatiotemporal`. `rgs_restirgi_spatial` is absent, so this is **not** the
Ultra Plus V4 mode. No reflection raygen appears at all — which is why T1.4b
is a separate switch that can be inert while T1.4 works, and why the settings
page says so rather than pretending.

This matters because `00` §2 and `06` say raygen BRDF edits are eval-invisible.
That reading came from `04` fact 5: those modules were **not dispatching**, so
the null results were non-dispatch, not non-effect. In the current mode they
do dispatch, and the module writes the pass's two radiance images itself
(`OpImageWrite` at `registers[5]` and `registers[5]+1`). Everything below acts
on values that reach those writes.

`rgs_reference_main` turns out to carry a full nested-loop path tracer, not the
thin tracer `06` describes. Its structure, read off `d622fb9e1dcb8cd0`:

```
%12276  preheader
%12277  loop header
          %740 = OpPhi %uint %uint_0 <pre> %741 <latch>    bounce index
          %712/%715/%717 = OpPhi %half %half_0 <pre> ...   radiance accumulator
   2282   OpTraceRayKHR ... cullMask %uint_1 ...           <- T1.4
   2610   NMax(rough, 0.04) -> NMin(_, 1.0) -> alpha=R*R   <- T1.1
%12786  latch
          %3241 = OpFMul %half <Li> <throughput>           <- T1.2
           %714 = OpFAdd %half %3241 %1697
           %741 = OpIAdd %uint %1706 %uint_1
```

**The loop is indirect-only, and that is load-bearing.** The first instruction
group of the body is the trace, so every roughness read and every accumulate
below it describes a surface a ray *found*; the primary surface comes from the
G-buffer and its three roughness sites (1686 / 1721 / 1724) sit above the
header. So T1.1 and T1.2 need no bounce-depth gate: "inside the loop" already
means "not primary", which removes a whole class of gating bugs. The in-loop
test is *header dominates the block AND the loop-merge block does not* —
dominance by the header alone is not enough, because the counter phi dominates
the post-loop tail as well.

## 3. The three edits

### T1.4 — cullMask 1 → 255 (the one that was asked for)

The bounce ray traces with `cullMask = 1` while the module's own visibility ray
at line 3788 already uses `255`. Instance classes outside mask bit 0 — hair
among them, per `17` §2 — are lit but never bounce. This is the same class of
edit as the shipped shadow-leak fix, and the same reason it can work where a
BRDF edit could not: in `BRDF × light × visibility / pdf`, a *sampling* change
cancels against the pdf, a *visibility* change does not.

Only the shading trace is touched. The patcher requires the cullMask to be the
literal 1 **and** the flags to never contain `SkipClosestHitShader` — the
occlusion traces (3568 / 4199 / 4719 / 10622, flags 12, masks 39/dynamic) are
left alone. The bounce trace's flags are an `OpSelect` between 1040 and 16, so
the flag resolver follows one level of `OpSelect`/`OpPhi` rather than giving up.

Exactly **one** such trace exists in each of the 12 `rgs_reference_main`
permutations and in each of the 3 reflection raygens. 15/15.

Honest failure mode, and it is in the switch's own description: a wider mask
can also let bounce rays hit proxy/impostor geometry the mask existed to hide.
This is a diagnostic as much as a feature.

### T1.2 — per-segment indirect radiance ceiling

`NMin` on each segment's `throughput × Li` before it lands in the fp16
accumulator — UE's `MaxPathIntensity` applied per segment. Clamping the
*product* rather than `Li` also catches an fp16 overflow to `inf`, and it sits
upstream of the module's own output scale, so GOTCHAS' *scale before a clamp*
holds by construction.

The knob is in **output** units. The accumulator runs pre-multiplied by 64 (the
output stage is `L × 0.015625`; fp16 has no precision to spare near zero), so
the emitted half constant is `C × scale`, with the scale read off the constant
in the `OpFMul` that feeds the module's own ±65504 clamp pair. Ten of the
twelve permutations yield exactly 64.0 that way; `40c6faab52a13874` and
`ab7f1822eeb0331b` have no such output stage and fall back to 64.

Shipped at **C = 16** output units → half `512`. fp16 saturates the accumulator
at 1023 output units, so this is a firefly ceiling, not an exposure control.

The clamp is spliced next to the *contribution's* definition, not next to the
`OpFAdd`: the accumulates often sit in a phi run, and a non-phi instruction
spliced into one is invalid SPIR-V.

Sibling sweep (GOTCHAS §3): the accumulate is not a single site. Following the
phi closure of the accumulator finds 6–18 `OpFAdd %half` sites per module
(3 channels × 2–6 sites), including the `%12787` sibling block that a
line-local patch would have missed. All of them are clamped.

### T1.1 — path regularization

`R' = max(R, 0.25)` on the perceptual roughness of every in-loop vertex,
rewritten through `replace_all_uses` so the **sampling** branch and the
**eval** branch read the same value. Regularizing only the eval would leave the
pdf describing a different lobe than `f`, which is worse than doing nothing.
Kaplanyan & Dachsbacher 2013; Blender's *Filter Glossy*, UE5's
`r.PathTracing.Regularization`.

The anchor is the module's own clamp `NMax(x, 0.04) → NMin(_, 1.0)` whose
square is `alpha` — the mode-independent half of the signature (GOTCHAS §4).
4–5 in-loop sites per module; the pre-loop primary sites are excluded by the
in-loop test, not by a heuristic.

Default **off**: unlike the other three this is a deliberate look trade
(softer reflections-of-reflections for less caustic noise), not a cleanup.

## 4. T1.3 — investigated, and negative

`23` scoped T1.3 as *(a) confirm the 128×256 R16_UNORM texture with 85 dispatch
binds is the sampler-noise LUT, then (b) author STBN into it through the
existing `CopyTextureRegion` hook*. Step (a) was run and came back **no**.

`analysis/evidence/survey/capA_survey.jsonl` (1.9 M events) contains exactly
**one** 128×256 CPU→image upload, seq 1513900, `fmt=70` (R16_UNORM), 65536 B.
Of its first 4096 captured bytes (2048 texels — the capture is truncated):

```
exact zeros : 1194 / 2048   (58%)
first 24    : all zero
top-nibble  : [1355, 76, 53, 91, 88, 73, 77, 71, 53, 20, 14, 13, 13, 13, 11, 27]
```

A blue-noise or STBN mask is by construction near-uniform over the full range
with essentially no exact zeros. This is the opposite. Authoring STBN into it
would be precisely the GOTCHAS §5 failure — writing a pattern into a buffer
whose contract is something else entirely.

Two honest caveats. The capture is truncated to 1/16 of the image, so this
describes the first ~16 rows. And the handle in the survey (`0x1781e7c0`) is
not the `0x1980af80` that `23` names — those come from different runs and
handles do not cross-reference. What the survey does establish is that in a
full run there is exactly one upload of that shape and format, so if
`0x1980af80` is uploaded at all, this is it.

**Verdict:** no blue-noise target exists to author into. Not built. If this is
revisited, the next step is not authoring — it is finding whether the sampler
noise is *generated* in-shader (a hash) rather than sampled, in which case the
lever is a Cranley–Patterson rotation spliced at the generator, and there is no
LUT anywhere.

## 5. Bonus finding: the engine already has a firefly clamp, and it is a CVar

`d622fb9e1dcb8cd0` lines 14318–14396 carry the engine's own max-luminance
ceiling, gated on `cb[85].z > 0`:

```
%1564 = cb[85].z > 0                       ; the gate
%1774 = max(dot(albedo * L, Rec709), 0.001)
%1988 = cb[85].z / %1774
%1989 = clamp(%1988, 0, 1)                 ; scale the output colour down
```
with a material-class-160 variant using `cb[85].z * 0.03`.

Per GOTCHAS §8 (*ask whether the engine already exposes it*), this is a CVar
candidate worth hunting in the exe the way `16` hunted the hair BRDF: if it is
reachable, the whole T1.2 splice may be replaceable by a setting — and either
way `cb[85].z` is the right calibration reference for the shipped ceiling of
16. Off by default in this mode (the branch is dead unless something writes
cb[85].z), which is why fireflies survive to be worth clamping.

## 6. Mechanism: why this is a matrix and not three overlays

Three independent toggles all splice the **same** twelve modules, and
`load_swap()` serves the first overlay that has a file for an id — so as three
overlays, two of them would be silently dead. And every overlay outranks the
base `swaps/` dir, which is where `skinray` installs its own patched reference
raygens, so a vanilla-based ptq module would silently un-patch skinray.

So: `dev/build_ptq.sh` pre-builds the 7 non-empty `{r,c,b}` combinations, each
with `base/` (12 modules from vanilla) and `skin/` (the 2 permutations skinray
ships, patched on top of the skin build). `sync_settings.sh` copies the selected
combo's `base/` into the single `swaps.ptq/` overlay, then `skin/` over it when
`skinray=on`. No patcher runs on the player's machine; a toggle only moves
pre-built files. The reflection raygens are nobody else's, so they ship as an
ordinary independent overlay (`swaps.ptrefl/` + `ptrefl.disable`).

Both lessons are now in `GOTCHAS.md`.

## 7. Files

| file | what |
|---|---|
| `dev/patch_pt_quality.py` | the three splices, CFG/dominance-guarded, `--report` mode |
| `dev/build_ptq.sh` | builds the 7-combo matrix + `swaps.ptrefl/` |
| `dev/install_ptq.sh` | installs the matrix to `$INSTALL_DIR/ptq/`; `remove`, `status` |
| `swap_layer.c` | default overlays now `hair,shadowcull,ptq,ptrefl`; new `refl` hit bucket |
| `release/game/red4ext/plugins/CallistoSSS/sync_settings.sh` | reads `ptreg`/`ptclamp`/`ptbounce`/`ptrefl`, materializes `swaps.ptq/`, extends the cache stamp and `status.txt` |
| `init.lua` (+ CET mirror) | the four switches, the `refl` count, two new warning lines |
| `handoff/GOTCHAS.md` | the three overlay-resolution gotchas |

## 8. Verification so far, and what is still owed

Done offline:

- anchor coverage across all 15 modules: 1 shading trace each; path loop found
  in 12/12 reference raygens; 4–5 roughness sites and 6–18 accumulates each
- all 7 combos × 14 modules + 3 reflection modules assemble and pass
  `spirv-val`; the unpatched inputs round-trip first
- materialization tested through the real `sync_settings.sh`: all-off →
  `swaps.ptq/` empty + `ptq.disable` + `ptrefl.disable`; `skinray=on` → the two
  skin-based variants land on top; `skinray=off` → the vanilla-based ones do

Still owed, and none of it can be done offline:

1. **Dispatch proof.** `{"ev":"dispatch",...,"swapped":1}` for the ptq raygens.
   A HIT is not execution.
2. **On-screen A/B for T1.4** at a framing where hair is a visible indirect
   contributor — a lit interior, hair against a bright wall. This is the whole
   point; everything else is variance reduction.
3. **Whether T1.4 costs frames.** A 255 mask means more closest-hit invocations.
4. **Whether the clamp at 16 is right**, calibrated against `cb[85].z`.
5. **`4270b745d11a5e8a` dispatches live but ships no skin patch** — worth
   knowing whether it should, independently of this work.

---

## Regression: the tier-1 PT edits change hair (2026-08-28)

Confirmed by A/B on 2026-08-28. With all four switches off and `shadowset=full`,
the hair shadow-leak fix looks correct again; with them on, it does not.

The evidence that isolated it is in the layer log. Fingerprinting the served
`swaps.shadowcull/` payload per launch:

| pids | shadowcull payload | ptq | ptrefl |
|---|---|---|---|
| 1148450 → 1190018 (8 launches) | `a343a1500587` | **0** | **0** |
| 1205967, 1233620, 1240949 | `a343a1500587` | 15 | 3 |
| 1215461 / 1235331 / 1237336 | split / m6 / m112 | 15 | 3 |

The eight launches where the fix demonstrably worked are exactly the eight with
no PT overlays. Launch 1240949 — after `full` was rebuilt — served a
**byte-identical** payload to those eight, which clears the rebuild and the
shadow patcher entirely.

**RETRACTED 2026-08-28 — no regression; hair is correct with both on. See `26` §4.3. The rest of this section is void.**

**Suspects, in order.** `ptbounce` (T1.4, cullMask 1→255 on the bounce raygens)
and `ptrefl` (the same widening on the three reflection raygens) change *what
geometry a ray can hit* near hair — T1.4's own tooltip warns it can reveal
"proxy geometry the mask was there to hide". `ptreg` and `ptclamp` only scale
or clamp a contribution that was already computed, so they can dim or soften
hair but should not move an edge.

Hence the split: test `ptreg`+`ptclamp` together first. If hair is still
correct, both are innocent and the culprit is one of the two mask wideners —
three launches worst case instead of four.

**Not yet known which one.** Do not re-enable these by default until it is.
