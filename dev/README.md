> **2026-08-30:** the raygen-era instructions below (`regen_and_clear.sh`,
> `swaps/` as "the active swap set", the smoke-test tint) are historical.
> Today: overlays are built by `patch_compute_skin.sh`, `patch_shadow_flags.sh`,
> `build_ptq.sh`, `patch_ser.sh`, `build_agx.sh`; `sync_settings.sh` picks
> them per launch. See `handoff/CURRENT.md`. Retired scripts: `retired/`.

# CallistoSSS

RED4ext plugin that replaces Cyberpunk 2077's runtime-generated SSS_Blur
diffusion-kernel texture (32x8 R32G32B32A32_FLOAT) with a Callisto-reshaped
LUT. Background: `analysis/HANDOFF.md` §8.5–8.6.

- `main.cpp` — hooks `ID3D12GraphicsCommandList::CopyTextureRegion` (shared
  vtable, obtained via a throwaway device — works on vkd3d-proton), matches
  the vanilla kernel upload by 64-byte fingerprint, and overwrites the mapped
  upload bytes with `kernel.bin` before the copy records.
- `kernel.bin` — output of `analysis/scripts/author_callisto_kernel.py`
  (copy of `analysis/evidence/sss_kernel_callisto.bin`). Swappable without
  rebuilding.
- `build.sh` — mingw-w64 cross-build; regenerates `fingerprint.h` from the
  dumped vanilla texture.

Install: copy `CallistoSSS.dll` + `kernel.bin` to
`<game>/red4ext/plugins/CallistoSSS/`. The plugin writes `callisto.log`
there; expect "hook installed" at boot and one "fingerprint matched" line
when the engine uploads the kernel.

---

## SPIR-V swap layer (Callisto BRDF injection)

Second mod in this repo: `VK_LAYER_CALLISTO_spvswap`, a native-Linux Vulkan
layer that substitutes shader modules at `vkCreateShaderModule` — the vehicle
for the skin-BRDF patch (see `analysis/BRDF_HANDOFF.md`). Under Proton/
vkd3d-proton every shader reaches the driver as SPIR-V, so BRDF patches are
authored as text on the disasm and reassembled with `spirv-as`.

- `swap_layer.c` — the layer. Identifies each module by its embedded dxil
  identity `<libhash>.<entry>` (from the `OpString "...dxil"`; **the 16-hex
  library hash alone is NOT unique** — e.g. `d622fb9e1dcb8cd0` covers both
  `rgs_reference_main` and `ms_empty_main`), falls back to sha256(pCode).
  If `swaps/<libhash>.<entry>.spv` exists it is substituted; every module is
  logged as JSONL (hit or miss). Env: `CALLISTO_SWAP_DIR`, `CALLISTO_LOG`,
  `CALLISTO_SWAP_DISABLE=1`, `CALLISTO_SWAP_QUIET=1`.
- `VkLayer_callisto_spvswap.json` — manifest (relative library_path).
- `build_swap_layer.sh` — `gcc -shared -fPIC -ldl -lpthread`.
- `swaps/` — the active swap set, produced by
  `analysis/scripts/patch_skin_brdf.py` (currently the SMOKE TEST: skin
  diffuse tinted (2, 0.2, 0.2) at all six 1/pi eval sites of both
  `rgs_reference_main` raygen permutations; spirv-val clean).

Enable for the live game: the layer is installed as an IMPLICIT layer so it
loads inside the Steam Linux Runtime container (which cannot see this repo
path -- `VK_ADD_LAYER_PATH` pointing here does NOT work for the game):

- `~/.local/share/vulkan/implicit_layer.d/VkLayer_callisto_spvswap.json`
  (copy of `VkLayer_callisto_spvswap.implicit.json`, absolute `library_path`)
- `~/.local/lib/callisto/libVkLayer_callisto_spvswap.so` + `swaps/`
  (`regen_and_clear.sh` syncs both on every run; the layer finds its swap dir
  next to its own `.so` via `dladdr`)

Steam launch options then need no layer env vars at all:

```
"<this dir>/regen_and_clear.sh"; CALLISTO_LOG=$HOME/callisto_swap.jsonl %command%
```

Set `CALLISTO_LAYER_DISABLE=1` for a vanilla control run (the manifest's
`disable_environment`), or `CALLISTO_SWAP_DISABLE=1` to load the layer but
skip substitution.

`CALLISTO_LOG` must be a container-visible path (`$HOME/...`, not `/tmp` --
the game runs in pressure-vessel with a private `/tmp`). `regen_and_clear.sh`
rebuilds the swap set from `brdf_params.txt` in the CET mod folder (written by
the in-game nativeSettings sliders under "Callisto SSS"), syncs the kernel
on/off flag, and clears the pipeline caches, so settings apply on next launch.
Its log: `regen.log` next to the script.

Sanity check that the layer is visible: `vulkaninfo --summary | grep -i callisto`.

A/B analysis of before/after screenshots:
`python3 analysis/scripts/compare_brdf_ab.py before.png after.png --save-masks`

Offline test (no game needed, uses the capture): see the replay/probe cheat
sheet in `analysis/HANDOFF.md` §9 — chain with the probe layer
(`VK_LAYER_CALLISTO_spvswap:VK_LAYER_NGFXPROBE_probe`, `NGFXPROBE_STRIP_ALLOC=3`)
and grep the layer log for `"swap":"HIT"`.
