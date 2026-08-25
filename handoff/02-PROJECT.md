# Project context

## What this is

**CallistoSSS** — a Cyberpunk 2077 skin-rendering mod for Linux/Proton, by
blane. It ports the Callisto Protocol (SIGGRAPH 2023) character BRDF onto
CP2077's path tracer. Reverse engineered entirely from two 4 GB Nsight Graphics
captures; no source, no symbols, no Nsight GUI.

Repo: `CallistoSSS/` (own git repo). Working branch: **`hair-brdf`**.

## Two injection mechanisms

### 1. SPIR-V hot-swap via a Vulkan layer — the one that matters here
`swap_layer.c` → `VK_LAYER_CALLISTO_spvswap`, installed as an **implicit**
layer under `$HOME` (the Steam Linux Runtime container cannot see repo paths,
so `VK_ADD_LAYER_PATH` does not work for the game).

Under Proton, vkd3d-proton translates all DXIL/DXR to SPIR-V before the driver
sees it. The layer hooks `vkCreateShaderModule`, identifies each module by the
`OpString "<libhash>.?<mangled-entry>.dxil"` that dxil-spirv preserves, and
substitutes `swaps/<libhash>.<entry>.spv` when present. sha256 fallback.
Every module is logged as JSONL.

Critical gotcha: the 16-hex hash is a DXIL **library** hash and is not unique —
`d622fb9e1dcb8cd0` covers both `rgs_reference_main` and `ms_empty_main`.
Identity must be `libhash.entry`.

Env: `CALLISTO_SWAP_DIR`, `CALLISTO_LOG`, `CALLISTO_SWAP_DISABLE`,
`CALLISTO_SWAP_QUIET`, and (new, added while diagnosing this blocker)
`CALLISTO_DUMP_DIR` / `CALLISTO_DUMP_MATCH` to dump incoming SPIR-V.

**Patches are authored as text on `spirv-dis` output**, spliced by
`dev/patch_skin_brdf.py`, reassembled with `spirv-as`, validated with
`spirv-val`. Anchors are found **structurally**, never by hardcoded IDs — this
matters, because it means the patcher should work on shader permutations it
has never seen.

Iteration loop: edit knobs → rerun patcher → **clear `<game>/bin/x64/GLCache`
and `steamapps/shadercache/1091500`** (pipeline caches pin the module) →
relaunch. Hot reload is impossible.

### 2. RED4ext D3D12 texture-upload interception
`main.cpp` → `CallistoSSS.dll`. Hooks `CopyTextureRegion` via the shared vkd3d
vtable, matches the vanilla SSS diffusion-kernel upload by a 64-byte content
fingerprint, and overwrites the staging bytes with `kernel.bin`. Verdict from
A/B: **visually near-invisible; that lever is saturated.**

## Key reverse-engineering findings

- CP2077's path-traced diffuse is plain Lambert (albedo/π, cosine sampling,
  pdf = NoL/π) for **all** materials — proven by exact `throughput *= albedo`
  cancellation. No skin lobe, no hair lobe.
- Direct/analytic lights use **Disney diffuse** (anchor constant
  `0.107508637`), not Lambert. Two diffuse models in one frame.
- The material `OpSwitch` cases are **only parameter-record loaders**; every
  material class merges into one shared eval path.
- Skin gate: G-buffer material class bits[9:5] == 1, i.e.
  `OpIEqual(OpShiftRightLogical(gbuf.y, 5), 1)`.
- Hit payload is 16 bytes, fully accounted for: albedo rgb + metallic in
  member 0; octahedral normal (12+12 bits) + roughness (8 bits) in member 1;
  two floats after. **No tangent, and no spare bits for one.**
- The raygen contains **zero cross products**, so no tangent frame is built
  anywhere.
- A screen-space **normal G-buffer** is readable at SRV `registers[1] + 2`,
  and pixel coordinates are live across the whole shader.

## What shipped and works

Tier 1: `c1 = lerp(1, ρ_f, α_f)·lerp(1, ρ_r, α_r)` (diffuse Fresnel ×
retroreflection) spliced at the three primary 1/π diffuse eval sites,
skin-gated. Defaults ρ_f=1.35, ρ_r=1.25. At ρ=1 it multiplies by exactly 1.0 →
bit-identical to vanilla, which is the built-in regression test.

Visible and correct: `analysis/FINAL_BEFORE.png` vs `FINAL_AFTER.png`.

**Tier-1 output is byte-identical across every refactor since** (sha256
`921f95fc…` / `84b17a86…`) — verified after each change as a regression gate.

## Tooling built recently

- `dev/survey_uploads.py` + survey mode in `analysis/probe/probe_layer.c` —
  inventories every CPU→image upload from an ngfx replay, with content hashes
  for cross-capture determinism. Rediscovered the known SSS kernel
  independently, which validates it.
- `dev/fit_ms_ggx.py` — integrates the game's specular lobe. **Found a blocker
  and stopped:** the lobe as read reflects 2–4× less energy than a correct GGX
  lobe, so multi-scatter energy compensation was not spliced. `%9948` is an
  area-light-modified cosine, not a plain NoL. See `dev/MS_GGX_NOTES.md`.
- Hair tiers — see `03-HAIR-WORK.md`.

## Environment

- Game: `/mnt/f4333173-.../SteamLibrary/steamapps/common/Cyberpunk 2077`
- Shader cache: `.../steamapps/shadercache/1091500`
- Layer install: `~/.local/lib/callisto/` (+ `swaps/`, `swaps.prehunt/`)
- Layer manifest: `~/.local/share/vulkan/implicit_layer.d/`
- Log: `~/callisto_swap.jsonl` (**appends** — truncate between sessions)
- Nsight: `/opt/nvidia/nsight-graphics-for-linux/…-2026.3.1.0/`
- Launch options run `sync_settings.sh` (SSS-kernel flag only) plus
  `WINEDLLOVERRIDES`, `CALLISTO_LOG`, `PROTON_ENABLE_WAYLAND=1`,
  `PROTON_ENABLE_HDR=1`, `DXVK_HDR=1`.
