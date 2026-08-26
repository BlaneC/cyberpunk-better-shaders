# 07 — The visible pixels are shaded in COMPUTE (current source of truth)

Aug 25, late. Supersedes 06's "patch the CHS" conclusion.

## The unifying explanation

Audited end to end this session:

- The layer's substitution is **correct** (`sub.pCode/codeSize` forwarded;
  a HIT really does hand the driver our bytes).
- The new `pipe_stage` logging proved pipelines built from **swapped**
  reference and shadow raygens ARE traced live.
- An **unconditional payload write** (constant red radiance) in the CHS
  produced nothing — its pipelines never appear in the traced set.
- `trace_rays` attribution is also unreliable: traced handles show different
  raygens in `pipe_stage` vs `trace_rays` for the same handle (pipeline
  handle reuse; the rtpipe table is not cleared on destroy).

The only model consistent with all of it: **the RT passes produce samples
(visibility, reservoirs, reflection hits) — the visible image is shaded by
GLCompute resolve shaders.** 84 dumped whole-library compute modules carry
the full material stack: 1/π, Disney `0.107508637`, and the same
`gbuf>>5 == 1` skin gate. Tinting BRDF evals inside raygens only perturbs
sampling weights, which is why six sessions of "swapped and dispatched"
raygen patches changed nothing on screen.

## What was built

- `dev/patch_compute_brdf.py` — tints r,g,b of every `OpImageWrite` texel,
  gated on the module's own skin test; gate dominance computed (CFG from
  `patch_shadow_brdf`), refetch fallback, `--ungated` bisect flag. SPIR-V
  version auto-detected (compute libs are 1.3; RT modules are 1.4 — 1.4's
  interface rules reject 1.3 modules).
- `dev/patch_compute_perms.sh` — selects anchored libs (π+Disney bytes),
  patches, installs. **48/84 patched clean**; 36 lack the exact gate pattern
  (different encoding — acceptable for the control test).
- Fixed `Module` ident for hash-only OpStrings (`<hash>.dxil` — the old
  fallback regex needed two dots and returned `None`).

Installed: 48 compute swaps + existing raygen/CHS swaps. Caches cleared.

## Reading the launch

- **Skin red** → compute resolve is the visible surface. The class-hunt
  palette ports directly (same gate, dominance already proven at the writes).
- **No change** → check `grep '"swap":"HIT"' ~/callisto_swap.jsonl | grep dxil`;
  if served, re-dump with no `CALLISTO_DUMP_MATCH` and widen to the 36
  gate-variant modules.

## Layer bug to fix when convenient

`vkDestroyPipeline` does not clear the rtpipe table ⇒ reused handles make
`trace_rays` report a stale raygen. Every historical dispatch log must be
read with that in mind.

## CONFIRMED ON SCREEN (the hunt launch)

- Skin red (control), **hair YELLOW → hair's material class is 4**.
- Tint appeared only on sun-facing surfaces: the 48 `>>5`-gate modules are the
  sun/direct path. The other 36 read the SAME texel (same binding,
  registers[2]+4) but mask `& 31` (a different field) and never compute `>>5`
  — the local-light paths. `find_class_anchor_variant` +
  `acquire_class_shift` in `dev/patch_compute_hair.py` emit our own shift
  there, inheriting the fetch's dominance.

## Hair build shipped

`./dev/patch_compute_hair.sh --hair 4` → **68/84 modules**, 361 Kajiya-Kay
aniso sites, 39 sheen sites, all spirv-val clean. Remaining 16: 14 with no
material G-buffer read at all (sky/fog/volumetric-style passes) and 2 where
the class value dominates no GGX site. Knobs: `m_aniso/p_aniso/s_h/a_min/
k_sheen` via `--set`. Diffuse wrap still unported (scalar diffuse anchor).

## Settings gate (same pattern as the Callisto kernel toggle)

The hair build ships as a layer **overlay**, not as files in `swaps/`:

```
~/.local/lib/callisto/swaps.hair/   68 hair swaps
~/.local/lib/callisto/hair.disable  present = effect OFF
```

`load_swap` checks `swaps.<overlay>/` before `swaps/`; `overlay_init` reads
the flag once at layer load and logs
`{"ev":"overlay","name":"hair","enabled":0|1}`. Chain, mirroring `kernel`:

CET switch "Callisto hair anisotropy" (`init.lua`) → `hair=on|off` in
`brdf_params.txt` → `regen_and_clear.sh` at launch writes/removes
`hair.disable` → layer serves or skips the overlay. Applies next launch; no
re-patching. Overlay name is overridable with `CALLISTO_OVERLAY`.

Bonus: because hair lives in its own directory, `sync_install`'s
`rm -f swaps/*.spv` can never delete it.

## Is the original Callisto skin BRDF active?

**No — on two counts.** (1) The swaps installed for `rgs_reference_main` are
the *hunt* build (`1fba2d96…`, per 01-BLOCKER), not the tier-1 skin BRDF; the
tier-1 build is backed up at `~/.local/lib/callisto/swaps.prehunt/`. (2) Even
if restored, raygen swaps do not change visible shading (this document's whole
finding). Porting tier-1 c1 to the compute resolve is the remaining task —
`emit_c1_factor` needs a scalar-diffuse anchor there, same gap as the wrap.
The RED4ext SSS **kernel** swap is unaffected and still works: it patches the
kernel upload, not a shader.

## Tier-1 skin c1 ported to the resolve (rides in the hair overlay)

`find_c1_sites` + `build_skin_c1` in `dev/patch_compute_hair.py`: at every
Disney diffuse site, the shared scalar (`base × FD(NoL) × FD(NoV)`) is
multiplied by the reference tier-1 `c1`, gated on class 1. The compute site
hands over NoL/NoV directly — NoV identified by its `NMin(NMax(dot,1e-5),1)`
eps-clamp signature, NoL by the plain NClamp — so the reference's NoV
reconstruction is unnecessary. Same maths as `emit_c1_factor`, same knobs
(`rho_f/rho_r/n_f/m_f/n_r/m_r`). Installed: 68 modules, 149 c1 sites +
361 Kajiya sites, one overlay, one toggle. The `--with-tier1` flag mirrors
the reference patcher's.

## Hair depth pass + skinray option

- **Diffuse wrap ported.** `build_skin_c1` now emits skin c1 AND the hair
  wrap as ONE multiply per Disney scalar (reference `build_diffuse` pattern) —
  two passes rewriting the same scalar's uses would clobber each other.
  wrap = sat((NoL+w)/(1+w))/(1+w), spliced as wrap/NoL since NoL is already in
  the light weight, times `k_diff` (0.65) which darkens hair's diffuse so the
  strands read as grounded instead of floating. 149 wrap sites.
- **Punchier defaults** (the old raygen-era numbers were invisible):
  m_aniso 0.7→0.95, p_aniso 16→28, k_sheen 0.15→0.3, s_h 0.55→0.45,
  w_wrap 0.35, k_diff 0.65.
- **skinray option**: CET switch → `skinray=on|off` → regen_and_clear.sh
  copies/removes the pre-hunt tier-1 raygen build from `swaps.prehunt/`.
  Sampling-side only (eval-invisible) but empirically measurable. `swaps/`
  now holds ONLY those 2 tier-1 raygens + misc; all hunt-build raygen/CHS
  diagnostics removed so nothing perturbs sampling with tint math.
