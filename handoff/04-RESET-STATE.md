# 04 — State before the reset (the "silliness", documented)

Written Aug 25, evening, at the user's request before resetting the game
setup. Purpose: lose nothing of what was learned, and have a sharp checklist
to run against the fresh install.

## TL;DR

The hair-class hunt (red skin control + 10-class colour coding) is built,
installed, `spirv-val` clean, and **proven to attach to the right modules** —
a capture replay showed the swap firing on the exact pipelines a
path-traced frame dispatches. Yet in four live launches (with and without
the Ultra Plus PT mod), the screen never changed, because the dispatched
pipeline set never included the modules we patch. The last session — vanilla
PT, Ultra Plus uninstalled, user 200 % sure PT was on — dispatched *only*
`rgs_shadow_main` pipes, fewer RT passes than any session before it.

## Established FACTS (each with evidence)

1. **The swap mechanism works end-to-end.** Replaying the Aug-23
   PT-confirmed Nsight capture (`GameThread_2026_08_23_22_24_36`) with the
   probe + swap layers: the captured frame issued 14 `vkCmdTraceRaysKHR` on
   10 pipelines; two of those pipelines' raygens were the exact
   `rgs_reference_main` modules we patch — `d622fb9e1dcb8cd0` dispatched at
   1280×720, `40c6faab52a13874` at 160×90 — and the swap fired on both
   (`"swap":"HIT"` in replay stderr; patched sizes 305620/332144 recorded
   for the dispatched pipelines' modules).
2. **In the capture (vanilla PT) the full RT dispatch set is:**
   `rgs_reference_main` ×2 + `rgs_shadow_main` ×5 +
   `rgs_shadow_transparent_main` + `rgs_reflection_transparent_main` +
   `rgs_restirgi_spatiotemporal` ×2. All named single-entry modules.
3. **Ultra Plus's "V4" PT mode does not use `rgs_reference_main`.** Live
   sessions with the mod dispatched only `rgs_shadow_main` family +
   `rgs_restirgi_spatial`. The mod shades through the ReSTIR GI chain and
   the shadow raygens. (This explained the first three null launches on its
   own — but the fourth launch was without the mod and behaved the same.)
4. **The shadow raygens carry full material shading** and are the patch
   surface for Ultra Plus mode: same skin class gate (`gbuf>>5 == 1`, 4
   sites in `b80f16ff`), albedo rgb triple, 1/π and Disney diffuse evals.
   `rgs_restirgi_spatiotemporal`/`initial_temporal` have thin evals (1/π, no
   Disney); `rgs_restirgi_spatial` has no diffuse eval at all (reservoir
   resampling only). ~~The current patcher anchors do NOT fit the shadow
   raygen (no reference-style "triples"); a new anchor family is mapped and
   feasible but not built.~~ **CORRECTED (Aug 25): the shadow raygens DO
   have reference-style triples — 23 of them in `b80f16ff`. The anchors fail
   for a different reason (the skin gate dominates 0 of them), and the
   anchor family is now built. See `05-SHADOW-ANCHORS.md`.**
5. **A layer `HIT` proves module creation, never dispatch.** The live game
   builds all 12 `rgs_reference_main` permutations into pipelines every
   session (15 `rt_pipeline` events, all `swapped:1`) and has never once
   dispatched one live. The layer now logs `rt_pipeline` (with raygen id +
   entry name) and `trace_rays` (dedup per dispatched pipeline), plus hooks
   `vkDestroyPipeline`, `vkCmdTraceRaysKHR/IndirectKHR/Indirect2KHR`.

## The silliness — what does not add up

- Vanilla PT live should look like the capture (reference + restirgi +
  reflection). The "vanilla" session dispatched **only 8 shadow-family
  pipes — not even ReSTIR** — strictly less RT activity than the Ultra Plus
  sessions it replaced.
- Same session had exactly **one** layer process (`log_open` ×1) where
  earlier sessions had six (the extra five were fossilize pre-cache
  replays; this time the shader cache was warm).
- Trace sets are eerily deterministic across sessions: `trace_rays` events
  always start at seq 379 and run to ~seq 388.
- The capture is from Aug 23, two days before the null launches. If the
  game patched itself in between, the PT implementation could differ from
  the capture despite identical reference-module hashes existing on disk.

## Hypotheses to test AFTER the reset (ranked)

- **H1 — PT silently not engaging live.** Setting shows on, but something
  vetoes it (DLSS off, mod remnants in `engine/config`, broken user
  settings). Test: fresh config, DLSS on, PT on, take a screenshot —
  vanilla PT has an unmistakable converging-grain look — then check the log
  for `rgs_reference_main` in `trace_rays`.
- **H2 — game build changed PT dispatch since Aug 23.** Test: note the
  exact game version post-reset; re-dump and `dev/scan_dump.py` the module
  set; compare against `analysis/evidence/capA_report.txt`.
- **H3 — instrumentation hole specific to the reference pass.** The capture
  replay proves `trace_rays` works for regular `vkCmdTraceRaysKHR`, but a
  live-only path could evade it (`vkCmdBindPipeline2KHR`, function pointers
  fetched through `vkGetInstanceProcAddr` before device creation, secondary
  command-buffer subtleties). Test: extend the layer to also log every RT
  pipeline *bind* (dedup) — if reference pipes bind but never trace, the
  hole is in the trace path; if they never bind, PT really isn't running
  them.

## Post-reset checklist (the clean run)

```bash
# state now: 12-permutation hairhunt build installed at
#   ~/.local/lib/callisto/swaps/   (hairhunt on all 12 reference permutations)
# layer with full instrumentation at ~/.local/lib/callisto/
: > ~/callisto_swap.jsonl
# in game: fresh config, DLSS = on, PT = on (Overdrive preset), then gameplay
# with a character in frame. screenshot for later comparison.
grep '"ev":"trace_rays"' ~/callisto_swap.jsonl     # want: rgs_reference_main, swapped:1
grep -c '"swap":"HIT"' ~/callisto_swap.jsonl       # swaps served
```

If `rgs_reference_main` appears with `swapped:1` and skin is still not red,
the gate/class assumption is next — run `./dev/patch_all_perms.sh
--forcetint` (ungated red, all triples) to split "gate wrong" from "not
executing".

## Tooling built during the hunt (don't rediscover)

- `swap_layer.c`: swap + dump (`CALLISTO_DUMP_DIR/MATCH`) + module→pipeline
  →dispatch tracking (`rt_pipeline`, `trace_rays` events with entry names).
- `dev/scan_dump.py`: ranks dumped modules by the reference-eval fingerprint
  (1/π sites, Disney anchor `0.107508637`, class gate, entry models).
- `dev/patch_all_perms.sh`: disassemble→patch→install→clear-caches for all
  dumped permutations; per-module fault isolation. Reproduces known builds
  byte-identically (smoke-tested).
- `dev/patch_skin_brdf.py`: patcher; hash-only OpStrings now get ident
  `<hash>.dxil` so swap filenames match the layer lookup.
- Capture-replay correlation recipe (probe logs `CreateShaderModule` size +
  `CreateRTPipeline` rgsmod + `CmdBindPipeline`/`CmdTraceRays`): replay
  command in `dev/MS_GGX_NOTES.md`; rgsmod logging added to
  `analysis/probe/probe_layer.c`.
- Fossilize caveat: Steam's shader pre-cache replay loads the layer in a
  separate process whose log goes to stderr; it *does* dump modules to
  `CALLISTO_DUMP_DIR` — a free module source that survives cache clears.

## The goal, unchanged

Find hair's G-buffer material class N (hunt tint), then evaluate the hair
BRDF tiers (`03-HAIR-WORK.md`). If the user returns to Ultra Plus: its
shading lives in `rgs_shadow_main` (direct) + `rgs_restirgi_*` (GI); the
shadow-raygen anchor work is the porting task, structure confirmed
portable, not yet implemented.
