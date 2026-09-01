# 77 — Skin-only sample count: BUILT + PARKED + DEPLOYED; served, unjudged

Written 2026-08-31, after the build. Prompt: *implement the skin-only
increased ray density from the handoff docs — better shadow contrast on faces
and skin.* That is `29` Part B4, the item `51` §2 ranked as "the real lever,
largest patcher change since AgX", gated on the G-U5 sentinel — which
**passed** (`56`). This document records what was actually built, the one
discovery that reshaped the plan, the honest risk ledger, and the A/B
runbook. **It is not working until an A/B says so.**

**Update, 2026-08-31 22:00.** Both rungs *were* served on screen the same
evening — `-spp4d` at 18:07 (`skin_sha=9186954230375089`) and `-spp4` at 18:10
(`c564a287c016d49f`), per `~/callisto_launches.log` — but **no verdict was
given on either**, and the session's attention moved to the terminator band
(`78`), whose `-lumn` rung is now the live selection. Served is not judged:
§6's runbook, and in particular the d-vs-full artifact attribution, is still
unrun. The spp rungs are also built on the *pre-`78`* base, so re-running them
against the new default means one rebuild:
`CALLISTO_SPP_BASE=gi-50b-bleed-oil-sheen-lumn ./dev/build_skin_spp.sh --install`.

Select with `skinspec=gi-50b-bleed-oil-sheen-spp4d` or `…-spp4` (CET page or
`brdf_params.txt`). Default untouched; the standing rung stays what it was.

---

## 0. Verdict up front

| claim | status |
|---|---|
| class-1 pixels path-trace `max(RayNumber, 4)` samples, everything else untouched | built, machine-checked, **unproven on screen** |
| non-skin pixels are behaviour-identical to the base rung | by construction (see §2/§3: `eff = orig` off skin; 1 iteration + exact `+0`/`×1.0` in the baked tier) |
| the `29` §B4 loop surgery was needed everywhere | **WRONG — see §1.** Needed in only 4 of 12 permutations |
| cost | unmeasured; `29` §B7's price stands: ~+60–90% on the PT pass in a face close-up. Photo-mode/cutscene feature until a frame-time look says otherwise |

## 1. The discovery that reshaped the build — the sample loop is ALIVE

`29` §B4 described the outer loop as "a dxil-spirv structurization artifact:
a loop skeleton that executes its body exactly once" and planned real phi
surgery to wire it. **That is true only for the four baked permutations
(`4103c886`, `996a3b16`, `d002cc05`, `d622fb9e` — exactly `29` §B3's
literal-bound list).** In the other six paintable permutations the engine's
own sample loop is intact and live in the shipping SPIR-V:

- the header phis carry the LCG state, two float + six half accumulators and
  a sample counter (`1271d381` served bytes, `%1623` header, `%1624` RNG phi,
  `%1643` counter);
- the latch compares the counter against **`cbv[188].y`** — the same cbuffer
  word whose `.z` is `29` §B3's runtime bounce bound. `.y` is `RayNumber`;
- and the part that makes the whole feature nearly free there: **every
  per-sample NEE/MIS weight inside the body divides by a fresh read of the
  same `cbv[188].y`** (six reads inside/after the loop: four `1/N` and
  `1/⌈N/2⌉` stratification weights split over even/odd samples, the loop
  bound, and the accumulation-mode divide). The sum over samples is
  normalized *per contribution*, not at the exit.

So per-pixel sample count in the dynamic six is not loop surgery at all: it
is "make every `cbv[188].y` read return a per-pixel value". RNG threading,
accumulator wiring, stratification and normalization are the engine's own
and follow automatically. dxil-spirv folded all of it away in the baked four
because their `RayNumber` compiled as a literal 1 — which is also why `29`
saw a degenerate skeleton and 3 naked merge phis there.

Corrections this lands on earlier documents:

- **`29` §B4** — right that the skeleton is degenerate and how to wire it;
  wrong that this is the whole job. The engine loop's existence in 8 of 12
  was not noticed (the disassembly cited was `d622fb9e`, a baked one, and
  `1271d381` was only quoted for its bounce bound).
- **`32`/README's "there is no per-material sampling in this engine today"**
  — still true as stated, but the stronger implication that `RayNumber`'s
  shader half might be dead is now bounded: the dynamic permutations consume
  `cbv[188].y` as a live loop bound. Whether the *CVar* reaches that cbuffer
  word is still the untested `29` item 2 (Ultra Plus's `0xDEADBEEF` claim).
- **`24` §2 / `29`'s "1 spp × 2 bounces"** — true for the baked four only.

## 2. The dynamic tier (6 modules: `1271d381`, `21a92f1a`, `25b54fc4`, `3d871a31`, `4270b745`, `852b31a8`)

Inserted once, in the block that owns the `rayN==0` skip gate (it dominates
the loop and the post-loop divide):

    isSkin = (gbuf1.y & ~31) == 32          ; 29 §B2's gate, cloned by id
    eff    = (isSkin && rayN != 0) ? max(rayN, 4) : rayN

then every `cbv[188].y` read **at or after the loop header** has its uses
rewritten to `eff` — in all six modules that is exactly 6 sites: 4
stratification weights, the latch bound, the accumulation-mode divide. The
two pre-header reads stay engine-wide on purpose: the `rayN==0` gate (PT
globally off must stay off for skin too) and the entry seed stride (keeps
non-skin RNG streams byte-identical).

`max(rayN,4)` rather than a bare 4: if the engine (or a future CVar test)
ever runs `RayNumber > 4`, skin must never get *fewer* samples than the rest.

The skin gate is the module's own post-loop class fetch **cloned by id**
(`55`'s discipline): chain instructions re-emitted with fresh ids, pixel
coords / descriptor array / push constants referenced verbatim. The existing
fetch could not be reused — it sits after the loop.

## 3. The baked tier (4 modules) — the actual `29` §B4 surgery

The outermost degenerate loop (continue block referenced exactly twice =
`29` §B4's detector, machine-checked to enclose all other degenerate
skeletons and the trace sites) is wired:

1. **The old merge block becomes the continue block.** This direction, not a
   new latch block, because every existing branch to the old merge comes
   from inside nested selection constructs — retargeting them to a new
   arbitrary block is illegal structured control flow, but a branch to the
   loop's continue target is a legal `continue` from any nesting depth.
2. Its 3 leading `OpPhi %half` (the per-sample radiance) are accumulated
   there; counter++ and a remixed seed follow; the terminator becomes
   `BranchConditional (ctr < N) header, new-merge` — the do-while back-edge.
3. The new merge starts with `avg = acc × OpSelect(isSkin, 0.25, 1.0)` and
   takes over the old merge's post-phi code; downstream uses of the old phi
   ids are rewritten to the averages (3 per module), downstream `OpPhi`
   incoming labels naming the old merge are repointed (6 per module).
4. Header gets 5 phis: counter, 3 accumulators, seed. The bounce-level RNG
   phi (the unique one feeding `OpIMul ×1664525`) has its from-header
   incoming rewired to the seed phi. `N = OpSelect(isSkin, 4, 1)`.
5. The dead `%12818`-style continue block is deleted.

Off skin: N=1, one iteration, `acc = 0 + x` and `avg = acc × 1.0` — both
exact in half — so non-skin output is bit-identical to the base rung.

**Deviation from `29` §B4 as written, recorded:** §B4 wanted the LCG state
threaded so each sample "continues the sequence". The body's exit-state LCG
value does not dominate the continue block in these modules (it dies in the
frontier-phi ladders), so the seed is instead **remixed per sample**
(`seed' = seed·747796405 + 2891336453`, deliberately a different LCG than
the module's own 1664525). The engine's live loop does thread it; the remix
gives an equally decorrelated, different stream. If skin noise ever looks
structured, suspect this first.

## 4. The honest risk ledger — read before interpreting the A/B

- **The baked four write storage-buffer records inside the loop body.** 22
  `Aligned` stores per module (ray/sample records at stride 32, plus two the
  dynamic family also has inside its own live loop). A taint walk from the
  RNG phi marks **14 of 22** as potentially sample-varying — the analysis is
  flow-insensitive and phi-coupled, so that is an upper bound, not a
  finding. After wiring, last-write-wins: whatever consumes those records
  sees the **last sample's** record instead of the only sample's. That is
  still "one valid sample's record" — the N=1 semantics — but it is the one
  mechanism this build changes without fully understanding. **This is the
  entire reason `-spp4d` exists**: skin-only artifacts (shimmer, ghosting,
  shadow-channel crawl) present in `-spp4` but absent in `-spp4d` convict
  the baked tier; nothing else separates them.
- **One extra live-out per baked module** (`%1715`-class: the primary-hit
  distance captured on the first trace, used post-loop in the demodulation
  divide). It now carries the last sample's value; the primary ray is
  computed before the loop and identical across samples, so in practice the
  value is sample-invariant. Noted, not feared.
- **The denoiser ceiling is untouched** — `29` §B7 in full. Extra samples
  cut variance *entering* NRD/RR; they do not buy skin a sharper filter or
  more internal resolution. Expect "shadow gradients on faces read cleaner /
  deeper, less blotch in eye sockets and under the jaw", not a step change.
  If the A/B shows nothing, that ceiling — not a dead splice — is the first
  suspect, and the serve audit + the `eff` reread in `dev/…/rgs.report.json`
  is how to tell them apart.
- **Warp cost.** GPU work is per-warp; a warp holding one skin pixel pays
  the loop. `29` §B7 prices a face close-up at ~+60–90% on the PT pass.
  Judge the look first, then decide if it is a photo-mode-only rung.

## 5. What was machine-checked (all of it before install)

Per module, in the patcher: unpatched roundtrip assembles + validates; the
patched module `spirv-val`s clean; trace-site count unchanged (this build
adds **iterations**, never trace sites — it does not even need `56`'s
injected-trace result, only `ptbounce`'s multiple-dynamic-traces shape).
Per rung, in `build_skin_spp.sh`: base refs cmp-identical to `ser.set/class`
(the `ref=12(pass-through)` contract); tier split re-derived by probe and
asserted 6+4; verbatim halves cmp-asserted; patched halves asserted to
differ; **emitted-code re-read from the output binaries** (`39` §3.4 — ids
renumber across assembly, so the re-read is structural): class-1 gate
present, `eff` select fed by `UMax` and compared by the sample latch with
≥6 uses (dyn); retargeted `OpLoopMerge`, accumulate-and-branch continue
block with the remix constant, N/invN selects (baked). MANIFEST provenance
carried verbatim and re-verified against the live install: `ser_sha
310513f3008cbde4`, `ptq_sha 55ed4e5c6884ab71` both match, so `sync`'s
`gi_refuse` accepts both rungs under the standing contract.

## 6. A/B runbook — settings contract FIRST (the `45` rule)

Required, stated before any launch, never inferred after:

    tier=on  skin=on  skinspec=<rung>  ser=class  shadowset=full-shadow
    ptreg=on ptclamp=on ptbounce=on ptmsggx=on      (the rcbm combo — ptreg
                                                     ON, the 56 §6 trap)
    PT Overdrive on; grade of DLSS/RR: match across halves and record it

Rungs, one variable per step, control = `gi-50b-bleed-oil-sheen` (the
standing base; its refs are byte-identical to these rungs' unpatched half):

1. `gi-50b-bleed-oil-sheen-spp4` vs base. Framing: a face filling ≥1/4 of
   frame, **hard shadow gradient across it** (nose shadow, eye sockets, a
   low sun or single interior light). The claim under test is *shadow
   contrast on skin* — a flat-lit face is a wasted launch.
2. Only if 1 shows something: `-spp4d` on the same framing. Equal to
   `-spp4` ⇒ the dynamic six carry the screen and the baked risk never ran;
   visibly weaker ⇒ the baked four own real coverage (they include
   `d622fb9e`, one of the two `24` §T1.4 known dispatchers — partial
   coverage on faces is a live possibility, and would show as patchy noise
   levels *within* skin).
3. RR state: one look with RR **off** at the winning rung is where the
   variance drop is most visible (the standing `43` M1 idea rides along
   free).

Pre-registered outcomes:

| observation | reading |
|---|---|
| skin shadow gradients cleaner/deeper, non-skin unchanged | the feature, working |
| no visible difference anywhere | denoiser ceiling (§4) or skin pixels not shaded by patched permutations — check `ab_launch_audit.py` before concluding |
| skin *brightness* shifts vs base | normalization bug — the per-pixel divide missed a consumer; kill the rung, file the site |
| skin-only shimmer/ghosting in `-spp4` absent in `-spp4d` | the baked record stores (§4) — park `-spp4`, keep `-spp4d` |
| patchy noise levels within one face | permutation coverage split — expected, informative, not a bug |
| frame-time unacceptable in close-ups | keep as photo-mode rung; do not tune N down below 4 first (a 2spp rung halves both the cost and the point) |

## 7. Files

- `dev/patch_skin_spp.py` — the patcher, both tiers, `--probe`/`--expect`,
  per-module JSON reports.
- `dev/build_skin_spp.sh` — build + verify + `--install`; base overridable
  (`CALLISTO_SPP_BASE`), N overridable (`CALLISTO_SPP`, guarded 2–16).
- Parked: `skin.set/gi-50b-bleed-oil-sheen-spp4{d,}/` (93 modules each);
  repo copies in `swaps.gi-50b-bleed-oil-sheen-spp4{d,}/`.
- `init.lua` — two selector rows; deployed via `make install` 18:00, cmp-verified.
- Working disasms: `dev/disasm/skinspp/`.

`29` §B6 (per-skin shadow rays in `rgs_shadow_main`) stays deferred — that
family was never retested after `sctrl` (`56` §4's scope limit) and the
shadow mask is denoised by a filter tuned for 1 spp. `29` items 1–2 (the
`CharacterLightBlockers` look; the `RayNumber`/`AdaptiveSampling` CVar
re-test) still cost minutes and are still unrun — item 2 just became more
interesting: §1 proves the shader half of `RayNumber` is live in six
permutations, so if the CVar writes `cbv[188].y`, a global spp slider may
already work in Overdrive.
