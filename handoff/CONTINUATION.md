# Continuation prompt — hand to the next agent

You are continuing **CallistoSSS**, a Cyberpunk 2077 path-tracing shader mod
(Linux/Proton; SPIR-V module swapping via a Vulkan layer). The repo is
`/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS`
(git, branch `hair-brdf`; do NOT commit unless asked).

## Read first, in order

1. `handoff/README.md` — project index.
2. `handoff/13-OWNER-NAMED.md` — the architecture you need: tile-classified
   lighting evaluators (8px, blocky) write lighting buffers;
   **`6ac9085c9bd4b7da`, a temporal (TAA-style) resolve, owns every per-pixel
   final pixel incl. all hair** (proven on screen by class-gated palette
   paint).
3. `handoff/14-PROVENANCE.md` — **your task, with everything already tried
   and all dead ends marked.** Read it fully before writing any code.

## Your task

Implement descriptor provenance **in the swap layer** (NOT the probe layer —
it is bypassed for command-buffer traffic in the live game; `14` §3 explains
why), per the plan in `14` §4:

1. Add the listed hooks to `CallistoSSS/swap_layer.c` (reference
   implementation to copy from: `analysis/probe/probe_layer.c` — the
   `prov_*` functions, `va_to_cpu`, `cmd_state`, Slot maps).
2. Gate on a flag FILE (`~/.local/lib/callisto/prov.enable`), log `prov`
   events into the normal callisto log. Carry the dxil module id directly
   (the swap layer already has it).
3. One live launch at the Panam tourist-info spot (~1 min, hair on screen).
4. Analyze (`dev/prov_analyze.py`, adjusted to read ids directly):
   a. name `6ac9085c9bd4b7da`'s inputs/outputs (validate per `14` §4),
   b. list every module holding a **storage-image** handle to 6ac9's
      current-lighting input → the evaluator set.
5. Write `handoff/15-<NAME>.md` with the named evaluators, your evidence,
   and update `handoff/README.md`'s index. If the interior-hair evaluator
   falls out (expected: a tile-classified indirect dispatch, full-res, no
   class read — one of the 149 hunt failures), describe what a hair-BRDF
   splice there would need (it needs no class gate — dispatch IS the gate).

## Hard-won rules (violating these wastes days)

- **Select by dispatch, never by constants** (`10`). The `1/π + k` anchor
  scan mis-selects; the true owner `6ac9` has no 1/π at all.
- A swap HIT proves creation, not execution; `"swapped":1` in
  `~/callisto_swap.jsonl` dispatch events is the execution proof.
- The hunt palette is the ground-truth oracle: if a class-gated paint shows
  on screen, that write reaches the screen; blockiness tells you whether the
  writer is tile-classified (blocky) or per-pixel (clean).
- Do not retry the dead ends in `14` §2 (staged-descriptor heap
  reconstruction, replay augmentation, probe-layer live).
- Env vars don't reliably reach the game through Steam/Proton; use flag
  files and `CALLISTO_LOG`, which does.
- After changing installed swaps: clear
  `<game>/bin/x64/GLCache/*` and `steamapps/shadercache/1091500/*`, and
  truncate `~/callisto_swap.jsonl`.

## Builds / tooling

- Swap layer: see `build.sh` / `build_swap_layer.sh` in the repo.
- Patchers: `dev/patch_compute_hair.py` (hunt + hair tiers; class-idiom
  machinery already handles `>>5`, `&31`, mask-compare, OpPhi-lifted,
  OpBitcast shapes — `12` §3).
- `dev/bisect_hunt.sh` manages the 29-module hunt overlay halves.
- spirv-as / spirv-dis / spirv-val are on PATH.

## Done definition for this task

A handoff doc that names (a) 6ac9's input images with formats/sizes and
(b) the module id(s) writing its current-lighting buffer — with
`prov`-event evidence quoted — plus the analysis of what a splice in the
named evaluator requires.
