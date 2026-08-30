# 38 — Wild ideas after 37: the unlock table

> **2026-08-30 (44):** §1.2's `+2` fetch is the **shading normal** (`+1` is
> albedo) — B1/M7 have no material channel to read. The "vkd3d-proton does
> not deliver SER" line is half right: it enables the extension and never
> emits the instruction, and the layer's handling of that was the bug that
> un-patched ptq on every SER launch. See `44` §2.1, §2.4. The low-hanging
> items (M2–M6) are built; `45` runs them.

Written 2026-08-29. Investigation only — nothing was built, patched or launched.
Sources: the 3273-module dump in `~/callisto_dump/`; the 406-file disassembly
set in `dev/disasm/`; `analysis/evidence/meta/capA_prov.jsonl` via
`dev/prov_map.py`; a `strings` audit of `Cyberpunk2077.exe` (`16`'s method, per
GOTCHAS #8); `vulkaninfo` and `nvidia-smi` on this machine; and the 2024–2026
literature. One SPIR-V splice was assembled and validated offline; it was not
installed and not launched.

**Verdict, one line: three of the walls this project has been building around
are lower than the docs say, and the lowest of them — a five-bit material
sub-enum sitting in a register the evaluators already load and throw away —
was never noticed at all.**

**Second line: the cheapest item on this list is not a look feature. The game
asks for Shader Execution Reordering, vkd3d-proton silently does not deliver
it, this driver supports it, and putting it back is three instructions that
cannot change a pixel.**

This document is organised **unlocks first, ideas second**. That ordering is
deliberate: written the other way it is twenty ideas that all die in the same
four places, which is how `20`, `22`, `29`, `31`, `36` and `39` each
independently rediscovered the same input problem.

---

## 0. The four questions, answered

### 0a. Tensor cores under Proton — they are in use, and we are privileged

They are absolutely being used. DLSS Super Resolution, Ray Reconstruction and
Frame Generation all run on tensor cores through `nvngx` under Proton, and the
Vulkan DLSS path has shipped for years. Nothing on this machine is missing:

| | measured |
|---|---|
| GPU / driver | RTX 4070, 12282 MiB, **610.43.02** |
| `VK_NV_cooperative_vector` | present, **revision 4** |
| `VK_NV_cooperative_matrix` / `_matrix2` | present |
| `VK_KHR_cooperative_matrix` | present, revision 2 |
| `VK_EXT_shader_float8` | present |
| `VK_EXT_ray_tracing_invocation_reorder` | **present**, `ReorderingHint = REORDER_MODE_REORDER_EXT` |
| `VK_NV_ray_tracing_invocation_reorder` | present |

What is *not* available is the **game's own shaders** reaching them.
vkd3d-proton does not translate NVIDIA's DXIL cooperative-vector / WMMA
intrinsics — 3.0 added AGS WMMA over `VK_KHR_cooperative_matrix` specifically
to support FSR4, and those paths are AMD-shaped with implementation-defined
matrix layouts. D3D12 Cooperative Vectors is preview-only on Windows in any
case, and NVIDIA's own RTXNTC README says do not ship it.

**Callisto's layer sits below vkd3d-proton, at Vulkan, where all of the above
is live.** So this mod can use tensor cores in shaders the game itself cannot
reach. That is the same accident `36` §2 noticed from the other direction: the
Proton position puts us on NVIDIA's *shippable* branch by luck. Nobody needs to
fix a driver. See D1.

### 0b. Shader Execution Reordering — the game does not get it here

Cyberpunk uses the DXR `HitObject`/SER path on Windows. vkd3d-proton issue
#2420 tracks NVAPI shader intrinsics and SER is not implemented; upstream
weighed building it on `SPV_NV_shader_invocation_reorder` and chose to wait for
the EXT.

Measured, both sides:

- The exe ships **`cvRayTracingEnableReferenceSER`** and `EnableReferenceSER`
  (already surfaced in `pt_engine.lua`, `32`).
- **0 of 3273** dumped modules declare `SPV_*_shader_invocation_reorder`.

So the CVar is inert on Linux. The driver supports real reordering. We patch
SPIR-V. See A1 — and note that A1 is the only entry in this document that
*cannot* change a pixel, which makes it the only one whose failure mode is
"nothing happened" rather than "something looks wrong."

### 0c. Lossless texture compression — there is none, and that is the answer

No GPU-sampleable texture format is lossless. Every BCn block format is lossy,
and NTC is lossy by construction (`36`). Lossless compression only buys **disk
and PCIe**, where REDengine already runs Oodle Kraken on 505 of 545 segments
(`36` §1) — there is nothing left on that axis.

The honest levers, in order:

1. **`36` gate G0 is still unrun.** Nobody has measured what HD Reworked
   actually costs in VRAM. The whole prize is bounded by a number that does not
   exist yet. Half an hour of `nvidia-smi` at three fixed save points.
2. **`TextureQuality` / `m_textureMaxMipBias`** (`36` §1) — free, exists today,
   worse-looking, and it is the control anything else must beat.
3. **Selective BC1 → BC7 re-encode** of specific vanilla textures. This is the
   inverse trade — it *spends* VRAM to buy quality — and it is worth naming
   because on a 12 GB card with an unmeasured budget it may be the better
   direction. It also needs the same WolvenKit toolchain `36` §7 costs out.
4. **NTC** only if (1) says the prize is large. Verdict unchanged from `36`:
   dies on SIMD divergence in a multi-material deferred pass, which the paper
   itself lists as unsolved future work.

### 0d. Why faces cannot get sharper inside a compute resolver

This is `15` §1 and `39` §3.3 restated as a design rule, because it is the single
most load-bearing constraint on this whole list.

The lighting resolves at **1280×720**. It is tile-classified (the tile list is
a **40×23 R32_UINT** image, i.e. **32×32 pixel tiles** — measured this session,
§1.1). `6ac9085c9bd4b7da` then upscales to 2560×1440 **and** smears along
velocity with four motion-direction taps. The material class the evaluators
gate on is read from a 720p buffer and point-scaled.

Therefore: **nothing spliced into a compute resolver can be sharper than a
720p, tile-quantised, motion-smeared signal.** A *multiplicative* edit inherits
quantisation the pixel already carries and is invisible; an *additive* edit
introduces it and shows a tile grid. That is exactly what was observed of the
Tier-4 transmission — blocky at `medium` as well as `extreme` — and it is one
of the two defects that got that feature removed (`39` §3.3).

The corollary is the important part: **the only stage where face shading
resolution can actually be raised is the G-buffer fill** — see U2 and B5.

---

## 1. What was measured this session

### 1.1 The G-buffer descriptor table, decoded

From `dev/prov_map.py --module 4d46848998312027` against `capA_prov.jsonl`,
cross-read with `dev/disasm/compute/4d46848998312027.dxil.spvasm`:

| offset from `registers[1]` | heap idx (capA) | format | size | read by the evaluator? |
|---|---|---|---|---|
| `+0` | 83525 | `D32_SFLOAT` | 1280×720 | yes — front depth |
| `+1` | 83526 | `A2B10G10R10_UNORM_PACK32` | 1280×720 | yes |
| `+2` | 83527 | `A2B10G10R10_UNORM_PACK32` | 1280×720 | yes |
| **`+3`** | **83528** | **`R8_UINT`** | **1280×720** | **NO** |
| `+4` | 83529 | `R8G8B8A8_UNORM` | 1280×720 | yes |
| `+5` | 83530 | `R8G8_UNORM` | 1280×720 | yes |
| `+6` | 83531 | `R32_UINT` | **40×23** | yes — the **32×32 tile light list** |

The material word is a separate `v4uint` fetch at `registers[2]+4`
(`%194`/`%196` in that module).

**The `+3` skip is uniform, not incidental.** Offsets used off `registers[1]`:

```
family A (direct lighting, 9 modules)   {0,1,2,4,5}   +3 UNREAD in 9 of 9
GI resolvers 99bb…, ab0b…               {0,1,2,4,(5),7}  +3 UNREAD in both
```

Two caveats, stated because they bound the claim:

- **105 of 220** compute modules that load `registers[1]` *do* use offset `+3`.
  The base points at different tables in different modules, so this is not
  proof they read *this* image — but the channel is plainly consumed
  somewhere, and it should not be described as dead.
- `usage = 279` includes `COLOR_ATTACHMENT`, and **no compute module writes
  it**, so a graphics pass produces it. Per GOTCHAS, a compute-only prov log
  cannot name a raster writer, so "no compute writer" is the strongest
  available statement.

**Why this survives GOTCHAS #13.** The address is an *offset from a
push-constant base the shader loads at runtime*, exactly like the five fetches
around it. Nothing is baked. The bindless index churn that killed `29` A4 R3
(73203 → 503350 in 29 seconds) does not apply.

### 1.2 Two 10:10:10:**2** channels, both tags live

`4d46` decodes `+2` as `(x − 0.5)` per component, `InverseSqrt(dot)`,
normalise → a **unit vector** (`%207`–`%219`). It decodes `+1`'s components by
squaring them (`%204`–`%206`), which is the cheap sRGB→linear approximation, so
`+1` reads as a colour. And it multiplies **both** alphas by 3 (`%377` from
`+1`, `%366`/`%379` from `+2`) — i.e. both `A2` fields are **2-bit enums**
decoded to `{0,1,2,3}`.

That is precisely the shape `22` §2's unchased side-finding needs: fragment
module `667c55bd59f5f145` decodes a direction and "picks the dominant axis from
a 2-bit index". A 10:10:10:2 channel *is* an octahedral-or-similar direction
plus a 2-bit axis index.

The engine corroborates. `EMM_GBuffer0A`, `EMM_GBuffer1A` and `EMM_GBuffer1RGB`
are three **separate** debug views — the alphas are addressed independently
because they carry independent meaning. And the surface debug views name what
the G-buffer is supposed to hold:

```
EMM_SurfaceAlbedo          EMM_SurfaceBaseColor       EMM_SurfaceEmissive
EMM_SurfaceHairDirection   EMM_SurfaceHairID          EMM_SurfaceMaterialID
EMM_SurfaceMetalness       EMM_SurfaceRoughness       EMM_SurfaceSpecularity
EMM_SurfaceNormalsViewSpace  EMM_SurfaceNormalsWorldSpace
EMM_SurfaceObjectID        EMM_SurfaceTranslucency    EMM_SurfaceLightBlockerIntensity
EMM_SurfaceCacheID         EMM_SurfaceCacheResolution
```

`SurfaceHairDirection`, `SurfaceHairID`, `SurfaceTranslucency` and
`SurfaceObjectID` are all named. `11` §2's "no tangent, no free channel" was a
statement about the *packed material word*. It was never a statement about the
descriptor table, and it is now contradicted by the enum the engine ships.

### 1.3 The material byte splits **twice** — the finding that was not scoped

In `667c55bd59f5f145` (Fragment, 2 render targets), from one fetch of the
material image:

```
%235 = OpCompositeExtract %uint %233 1     ; the material byte
%246 = OpShiftRightLogical %uint %235 %uint_5    ; class      (3 bits)
%247 = OpBitwiseAnd        %uint %235 %uint_31   ; SUB-ENUM   (5 bits)
```

`%247` is not a leftover. It is switched on:

```
OpSwitch %247 %1362  12 %1361  13 %1361  14 %1361  15 %1361
                     21 %1361  30 %1361  31 %1361  25 %1360
```

— seven subtypes routed to a shared arm (which then further branches on
`class == 1`) and `25` to its own arm that loads a full RGB out of CBV member
5. Elsewhere `%247 == 17`, `== 21`, `== 30`. So the sub-enum selects
**per-subtype constants out of a constant buffer**: it is a material identity,
not a flag word.

Census over the 406-file disassembly set:

```
CLASS   (word >> 5)  values tested: {0:115, 1:531, 3:225, 4:328, 5:58}   in 111 modules
SUBTYPE (word & 31)  values tested: {0:1, 16:5, 17:21, 21:76, 25:78, 30:4, 31:4}  in 68 modules
```

Class 2 is still never tested (`22` §5 holds at 406 files as it did at 3153).

> **SUPERSEDED — corrected by `40-SUBTYPE-PROBE.md` §2, reproduce with
> `dev/census_subenum.py` (~1 s over all 3273 modules).** The loose scan above
> counts any `& 31` in a module that also does a `>> 5`; it does not require
> them to be the *same word*, and two of its values are artefacts of that.
> Under the strict rule — one word feeding both — the real census is:
>
> ```
> one word feeds both >>5 and &31 : 81  {GLCompute 59, Fragment 12, RayGeneration 10}
> of those, testing a sub-enum    : 67
> value -> #modules : {12:8, 13:8, 14:8, 15:8, 17:13, 21:64, 25:62, 26:1, 30:8, 31:10}
> by stage : Fragment [12,13,14,15,17,21,25,26,30,31]   GLCompute [17,21,25]
> ```
>
> Three corrections that matter. **`0` and `16` are not sub-enum values** — they
> are `& 31` applied to a different word. There is a **tenth value, `26`**, in
> exactly one Fragment module (`ddc88ec4cbd88ec4`). And the stage split is the
> important one: **compute only ever branches on `{17, 21, 25}`**, while Fragment
> tests all ten. So the field is richer than the stage we can currently patch
> makes use of — which raises the value of G-U2, and means a compute-side probe
> can only decode the three values compute itself distinguishes unless the
> paint reads the raw byte rather than the branch.

**And the evaluators already have it.** `4d46` fetches `%196` — the whole byte
— and uses only `%203 = %196 >> 5`. Across `dev/disasm/compute/`, 83 of 240
modules do the `>> 5` and **86 do an `& 31`**. Reading the subtype at a splice
site that already gates on class costs **one `OpBitwiseAnd`**.

This reframes the user's question "how do we get more material classes into the
shaders". There are already 8 classes × 32 subtypes of addressable identity in
a register the evaluators load and discard. See U4.

### 1.4 BDA is universal, not fragment-only

`36` §4b measured `PhysicalStorageBufferAddresses` on fragment shaders.
Measured across the whole dump: **3225 of 3273** modules declare
`SPV_KHR_physical_storage_buffer`. Compute resolvers and RT raygens included.
Any patched shader in this game can dereference a 64-bit pointer baked in at
`vkCreateShaderModule` time — which is strictly after `vkCreateDevice`, so the
layer knows the address.

### 1.5 The SER splice validates

Applied to `1271d3815051da17.rgs_reference_main`, keyed on the class value the
raygen already computes at `%442`:

```
23a24  > OpCapability ShaderInvocationReorderNV
27a29  > OpExtension "SPV_NV_shader_invocation_reorder"
1644a1647 > OpReorderThreadWithHintNV %442 %uint_3
```

`spirv-as --target-env spv1.4` assembles; `spirv-val` is clean at **both**
`vulkan1.3` and `vulkan1.4`. Diff against vanilla is exactly those three
instructions, +60 bytes. `%uint_3` already exists in the module. The emitted
instruction was read back by hand, not trusted from an exit code — though note
`39` §3.4: reading back what was emitted proves the build, never the picture.

Not proof of execution — GOTCHAS is unambiguous that a swap HIT is not
execution, and that a spliced second `OpTraceRayKHR` validates and then does
nothing. The honest proof for A1 is a frame-time delta, not a screenshot.

---

## 2. The unlocks

### U1 — inject a real descriptor (`inferred, unverified`)

RED4ext already owns an `ID3D12Device` — `main.cpp` obtains one from a
throwaway dummy device to reach the shared command-list vtable. It can
therefore `CreateShaderResourceView` for **our own** resource into a high,
game-unused slot of the game's SRV heap, and a patched shader reads it with the
bindless idiom `36` §4a characterised (239/239 fragment modules, one universal
shape).

This is the general "add a new hardware-filtered sampled texture" mechanism the
repo has always said it does not have. It supersedes `36` §4c (latents
unreachable by device address), revives the blue-noise mask killed in `24` §4,
and is the prerequisite for every LUT-shaped idea in Tier C.

Risks to name rather than assume: heap bounds and whether vkd3d-proton's
descriptor-heap mapping tolerates a foreign write; whether the game reclaims
the slot; and the ordering against `vkUpdateDescriptorSetWithTemplate` /
`VK_EXT_descriptor_buffer`, which is `36` gate G4's unresolved question in a
different coat.

**U1-BDA — the weaker sibling, and the cheapest thing in this document.**
The layer allocates a buffer at `vkCreateDevice`, bakes its address as an
`OpConstant` at `vkCreateShaderModule` (§1.4). Buffers only — no hardware
filtering, no `Texture2DArray` — but **zero descriptor surgery** and it works
in compute and RT as well as fragment. This is `36` gate G2, still unrun.

**U1b — game state → shader.** RED4ext can read what the renderer cannot:
which NPC this is, weather, wetness, time of day, quest state. Publishing that
into the U1-BDA buffer each frame makes **per-character material parameters**
possible for the first time. `29` §A found an 8-entry per-character skin
profile table in `cbv99`; U1b is how we would ever author against it.

### U2 — the fragment / G-buffer-fill stage (`never attempted`)

~1000+ observed fragment modules, never once patched, and **no fragment splice
has ever been proven to execute in this repo** (`36` gate G1 — compute and RT,
yes; fragment, never tested).

This is where UVs, tangents (`MST_Tangent_3F`, `MST_Binormal_3F` are vertex
streams), derivatives, material textures and the *authoring of the packed
material word itself* all live. Every input the last fifteen documents went
looking for and could not find in the deferred resolvers is present here.

G1 is, on the evidence of this document, **the highest-leverage unrun
experiment in the repo**: Tier B and half of Tier C hang off it, and it is one
tint and one launch.

### U3 — the skipped `R8_UINT` slot (§1.1)

If a G-buffer fragment shader writes it (U2), the nine skin evaluators already
bind it at a runtime-relative offset. That is a free per-pixel channel for
thickness, curvature, a sheen mask, vellus density, or extra identity bits —
and it retires `29` A4 and the whole thickness-proxy problem that `39` §3.2
records in one move. The open question is what it currently holds; `EMM_SurfaceTranslucency`,
`EMM_SurfaceLightBlockerIntensity` and `EMM_SurfaceHairID` are the candidates
its width and residency fit.

### U4 — the 5-bit sub-enum (§1.3) — **no unlock required, it is already there**

One `OpBitwiseAnd` at a site the evaluators already have. This is the only
"unlock" on the list that needs nothing built first, which is why it is
promoted above U2 in the gate order.

What it buys, concretely:

- **The cloth gate `22` §5 said could not be read offline.** A subtype hunt
  paint names all 32 values in one screenshot, by the same method that
  established hair = 4.
- **Sub-class targeting inside class 1.** Face versus body versus a specific
  character's skin, if the engine authors it that way — which would give
  the removed Tier-4 transmission the per-pixel shaping it structurally lacked
  (`39` §3.1), without a depth proxy, without a ring tap, and without fifteen
  knobs. It is the only route that addresses that defect at its cause.
- **The eyes work (`31`) generalises** from one class-8 gate to a class ×
  subtype lattice.

### U5 — the payload sentinel (`gated since 29`)

Unchanged and still unrun. `29` §B, `32` §4 and `39` §6's traced-thickness
route are all blocked on one
small launch that writes a sentinel into an RT payload from a miss shader and
reads it back. Named here only so that no Tier D entry appears cheaper than it
is.

---

## 3. Tier A — buildable on today's proven surface, no unlock

### A1 — Restore Shader Execution Reordering  *(verified offline, §1.5)*

Splice `OpReorderThreadWithHintNV <class> 3` into the 12 `rgs_reference_main`
permutations, keyed on the class the raygen already fetches (`29` §B1), and
plausibly into the shadow and ReSTIR raygens too. The layer adds
`VK_NV_ray_tracing_invocation_reorder` to `VkDeviceCreateInfo` and reports it
through `vkEnumerateDeviceExtensionProperties` — standard layer practice,
`36` §4e describes the same move for CoopVec.

Pure perf. It **cannot** change a pixel; a wrongly-keyed hint is a no-op, not a
bug. Published SER gains run to ~2× on divergent path tracers and Khronos
report up to 47% on a glTF path tracer. Spend it on samples, bounces, or the
resolution `0d` says is the real ceiling.

*What kills it:* the layer's device-creation edit not taking; vkd3d-proton
re-querying features; or the hint being uninformative because material class is
the wrong coherence key (in which case try the CHS/SBT index or the hit
instance). Frame time is the only honest measurement — a screenshot proves
nothing here.

*Second-order idea:* if reordering works, a coherence key built from **class ×
subtype** (U4) is strictly more informative than class alone, at one extra
`OpBitwiseAnd`.

### A2 — Charlie / LTC sheen for cloth

Zeltner, Burley & Chiang, *Practical Multiple-Scattering Sheen Using Linearly
Transformed Cosines* (SIGGRAPH 2022 Talks) — an LTC lobe fitted to a
volumetric sheen layer of fibre-like particles with an SGGX microflake phase
function, with a reference implementation at `tizian/ltc-sheen`. It is a
3-parameter analytic fit: **no texture, no tangent, no new resource.**

`22` §4 already scoped the splice: ~15–25 instructions at the existing GGX
sites, in evaluators `10` proved dispatch. Every input it wants — `NoH`, `NoV`,
`NoL`, roughness — is already computed at every site.

Its real value is diagnostic. An **ungated** sheen paints every non-skin
non-hair pixel, which is wrong as a feature and perfect as a probe: it removes
the class gate and the estimated tangent — hair's two confounds — from the list
of things that can explain a null result. Merge it with the U4 subtype rainbow
and one launch answers three questions: does a compute BRDF splice paint, which
class is cloth, and what are the 32 subtypes.

*What kills it:* nothing new. If it does not paint, the compute-BRDF track is
finally and cleanly dead, and that is a result worth one launch.

### A3 — Vellus / peach-fuzz sheen on skin

The same lobe, gated to class 1 (or better, a class-1 subtype from U4). This is
what the removed transmission's rim proxy was actually reaching for: real faces have a
forward-scattering fuzz layer that reads as a soft grazing rim under backlight,
and it is a *specular* phenomenon with a genuine angular basis — unlike
`pow(1 − |N·V|, t_rim)`, which was a shading-normal term wearing a
silhouette's clothes (`39` §3.2).

*What kills it:* it is still additive at 720p/8px tiles, so `0d` applies. It
must be sized as a modulation of an existing highlight, not as a new wash.
`39` is the cautionary precedent and the reason this is A3 and not A1.

### A4 — Specular antialiasing from screen-space normal variance

Kaplanyan-style filtering of normal distributions / Tokuyoshi's variance
approach: widen `alpha` by the local normal variance. This is the
deferred-legal answer to the user's "more realistic light transfer across lots
of micro features" — it is literally the statement that sub-pixel normal
detail should broaden the specular lobe rather than alias.

Mechanically it is cheap here because the machinery exists: the structure
tensor written for the hair tangent already computes neighbour normal
differences, and the rewrite target is the same single `alpha` site as
`build_skin_alpha_cap`.

*What kills it:* `31` §4.1's rule — only one `replace_all_uses` per alpha id,
or the second pass is a silent no-op that passes `spirv-val`. It must fold into
the existing nested-select pass, not add another.

### A5 — Grazing-angle specular occlusion / horizon fading

The user's "better shallow angle performance". Two separate things worth
distinguishing:

- **Energy** at grazing — already shipped as MS-GGX (`28`), confirmed on
  screen. Done.
- **Occlusion** at grazing — light leaking into directions the surface cannot
  see. Horizon fading against the shading normal plus a cone-angle occlusion
  term is the standard fix.

*What kills it:* there is no AO or cavity input among the evaluator's fetches
(`33` §4 looked and did not find one), so the occlusion cone has to be built
from the RT sun-shadow mask, which is a different quantity. Bent normals would
be the right input and there is no channel for them — unless U3 turns out to be
one.

### A6 — Re-author `kernel.bin` from a biophysical / spectral skin profile

The one channel with zero risk and a shipped precedent. `33` §1 already turned
the SSS kernel into a preset ladder with a byte-identical `vanilla` rung,
after finding the shipped radius was 10× the engine's.

The idea: stop fitting Burley and derive the diffusion profile from a
two-parameter biophysical skin model (melanin / haemoglobin), the direction of
*Spectral Subsurface Scattering from RGB via Biophysical Skin Inversion*
(arXiv 2606.27604, June 2026). The chromatic falloff of real skin is not a
Burley profile with a red tint; the red channel's mean free path is set by
haemoglobin absorption and the profile shape differs per channel.

*What kills it:* nothing technical — it is a 32×8 RGBA32F upload we already
own, authored offline in Python. It is a look decision, and it should ship as a
new rung on the existing ladder, not as a default flip.

### A7 — Pre-integrated skin from depth-derived curvature

Penner & Borshukov's pre-integrated skin shading, with curvature estimated from
depth derivatives rather than from a baked curvature map. Drives the terminator
wrap and the shadow-edge colour bleed analytically.

The reason this is on the list and the removed Tier-4 transmission is not: it is
**multiplicative**. It modulates the diffuse term the pixel already has, so per
`0d` it inherits the quantisation instead of introducing it. That is the whole
difference between an effect that reads as skin and one that reads as a tile
grid.

*What kills it:* curvature from a 720p depth buffer is noisy on a face, and
noisy curvature is a noisy terminator. It needs the same confidence weighting
the hair tangent estimate uses — `(λ1−λ2)/(λ1+λ2)` collapsing the effect to
zero where the estimate is unreliable — which is a pattern this repo has
already written once and got right.

### A8 — Thin-film iridescence on chrome cyberware

Belcour & Barla's *A Practical Extension to Microfacet Theory for the
Modeling of Varying Iridescence* — an analytic airy-reflectance term, ~20
instructions, no texture. Gated on high metallic, which is free: `F0 =
lerp(0.04, albedo, metallic)` is computed at all 15 Schlick sites (`22` §1), so
the metallic value is in a register.

Extremely on-theme for this game, and it is the kind of effect that reads at a
distance because it is view-dependent hue rotation rather than a brightness
change.

*What kills it:* no per-pixel film thickness, so a constant reads as a global
oil slick on every metal in the world. It wants a subtype gate (U4) or a
thickness driven by something — `SurfaceObjectID` hashed to a per-object
thickness would be a cheap and characterful hack if that channel is reachable.

---

## 4. Tier B — needs U2, U3 or U4

### B1 — A *geometric* hair tangent

`22` §2's side-finding plus §1.2's measurement plus `EMM_SurfaceHairDirection`
and `EMM_SurfaceHairID` in the enum. If one of the two 10:10:10:2 channels
carries the strand direction with the 2-bit alpha as its axis index, then:

- the screen-space structure tensor is retired, and with it the estimate's two
  known failure modes (`00` §4: axis-aligned degeneracy, non-fibre fallback);
- `08`'s shifted dual-lobe R+TRT becomes a *real* Marschner-flavoured model
  rather than one built on an inferred tangent;
- the per-pixel TRT albedo tint that `00` §8 item 5 lists as the remaining
  ceiling becomes reachable if `SurfaceHairID` is a real channel;
- and `19`'s retirement of the hair track ("never shown to change a pixel in 70
  modules of trying") deserves re-examination — the *input* was wrong, which is
  a different failure from the *mechanism* being wrong.

Note carefully what this does and does not reopen. It reopens the input. It
does not by itself answer `16`: the engine already ships a live-tunable
three-lobe hair BRDF as 41 CVars, and GOTCHAS #8 exists because that was
discovered late. Any hair work must state what it does that `hair_engine.lua`
cannot.

*What kills it:* the channel being view-space-only, or being written only by
the hair G-buffer pass and undefined elsewhere, or the 2-bit tag meaning
something else entirely. One disassembly read settles it.

### B2 — Write the free channel (U3 + U2)

Thickness authored where thickness is knowable — the G-buffer fill, which has
UVs and can sample an authored map — and read where it is needed. This reopens the one
thickness route `39` §3.2 rejected as a different toolchain — author it into a
texture — by making it tractable through U1 instead of WolvenKit, and it
removes the reason fifteen proxy knobs existed.

*What kills it:* the slot already holding something load-bearing (§1.1's 105
modules), or the G-buffer pass not being patchable (U2/G1).

### B3 — More material classes, two ways

- **Free, today:** read the existing 5-bit subtype (U4). Eight-plus populated
  identities per class, already authored by CDPR, one `OpBitwiseAnd`.
- **Authored, needs U2:** write a different class or subtype from the fragment
  stage. **Class 2 is tested by zero of 406 modules** — it is a genuinely free
  identity. Give cloth its own class, then gate A2 on it.

The first is the one to do. The second is the one that sounds wilder and is
strictly worse, because writing a class the engine's own shaders do not expect
risks every unpatched consumer of that byte.

### B4 — Screen-space ray-marched thickness

March the depth buffer toward the light and stop at the class change, instead
of the removed feature's ring taps counting neighbours that lie behind
(`39` §3.2). Strictly better —
it measures a distance rather than scoring an openness — needs no new
resources, and unlike R6 it needs no sentinel launch.

*What kills it:* it is still a screen-space proxy and still tile-quantised per
`0d`; and it costs N depth taps per pixel where R5 costs a ring. If U3 lands,
this is superseded by B2 and should not be built.

### B5 — Pore-scale detail at the G-buffer fill

The only place face shading resolution can actually be raised (`0d`). Parallax
occlusion or relief mapping for pores, detail normals, micro-roughness — all
authored at full material resolution with real derivatives, then consumed by
the deferred path as ordinary G-buffer content.

This is what "improve shadow and shading resolution on faces" actually means
mechanically, and it is worth stating that it is a **texture and G-buffer**
problem, not a lighting problem. No amount of path-tracing samples creates a
pore microshadow, because pores are not in the BVH — `33` established that and
it remains true.

---

## 5. Tier C — needs U1

### C1 — A neural BRDF baked into a texture

The user's Idea 2, and it is correct. NeuBRDF (Dou et al., *Real-Time Neural
BRDF with Spherically Distributed Primitives*, CVPR 2024, arXiv 2310.08332) and
NVIDIA's *Real-Time Neural Appearance Models* (TOG 2024, arXiv 2305.02678) both
reduce to the same modding insight: **a small MLP over 2–4 scalar features is a
neural field, and a neural field sampled with hardware trilinear filtering is a
LUT.** Inference becomes one `OpImageSample` plus a few FMAs.

One refinement worth writing down, because it changes the dependency:

> For **2–3 input dimensions, bake the MLP into ALU and skip the texture
> entirely.** A polynomial or small analytic fit over `(θh, θd, α)` costs a
> dozen instructions, needs no descriptor, and works today. A texture only
> earns its keep at **4D+** — which is exactly where you land once thickness or
> a subtype index becomes an input.

So C1 splits: the 3D case is Tier A in disguise, and only the 4D case needs U1.
The honest framing is that "neural" here is a *fitting* technique for authoring
a lobe, not a runtime architecture — which is the same thing the LTC sheen in
A2 is, twenty years earlier.

Related and lower-risk: *Real-Time Neural Materials with Block-Compressed
Features* (Nader et al. 2024) is the same trick in reverse — a decoder shader
plus learned BC-format feature textures. If a decoder can be spliced, an
authored feature texture can carry a neural material.

### C2 — A real spatiotemporal blue-noise mask

`37` killed the rotation ideas and, in doing so, named exactly what the
technique needs: Heitz & Belcour's blue-noise error distribution comes from
**the mask**, and it additionally requires **deleting the per-pixel seed hash**
`%167`, which currently re-randomises each pixel and destroys any spatial
structure. `24` §4 killed the only candidate resource (58% exact zeros — not
noise).

U1 supplies the mask. `37` §4 supplies the seed surgery. Both halves now exist;
neither did when `37` was written.

*What kills it:* `37`'s own rule — model the RNG in numpy and measure the
result before writing a patcher. `dev/validate_sampler_rng.py` is already the
tool.

### C3 — NTC

Verdict unchanged from `36`. U1 fixes §4c (the latent `Texture2DArray` being
unreachable by device address) and nothing else. §6.2's SIMD divergence in a
multi-material deferred pass is still the thing that kills it, still unsolved
in the literature, still structurally guaranteed here. **Do G0 first.**

### C4 — Authored per-character thickness / vellus / curvature maps

`29` A4 R4 without WolvenKit: our own textures, injected through U1, sampled by
UV at the G-buffer fill (U2), written into U3, read by the evaluators. That is
four unlocks stacked, which is why it is last in this tier and not first — but
it is also the only route on the whole list that ends with *per-character
authored skin* rather than a proxy.

---

## 6. Tier D — the genuinely wild

### D1 — A tensor-core neural pass of our own

Not NTC. The insight is structural: **`36` §9.1's killer is divergence caused
by per-material networks, and a class-gated single network has none.** One
CoopVec MLP, warp-uniform weights, evaluated only on class-1 pixels (or a
subtype), is the exact case the paper's Table 4 measures and the exact case
Cyberpunk's G-buffer pass is not.

Plausible payloads, in increasing order of ambition: a learned skin BRDF
(collapsing the whole Burley + dual-lobe GGX + transmission stack into one
network); a learned SSS profile conditioned on curvature and thickness; a
learned denoiser for one buffer.

Bring-up order is `36` G3's, and it is good: **DP4a first** — int8 dot products
via `OpCapability DotProductKHR` / `DotProductInput4x8BitPackedKHR`, which needs
no device-creation change and isolates "does the arithmetic run" from "does the
extension enable" — then CoopVec.

*What kills it:* the cost. `36` §6 sizes NTC's 8192-MAC network at 2.3–3.9× BC7
on a 4090; a smaller network on skin pixels only is a fraction of a fraction of
that, but it is not free, and the honest answer is that nobody has measured a
CoopVec splice under vkd3d-proton at all. Also `36` §9.6: no fragment-stage
splice has ever been proven to execute here, and no CoopVec splice has been
proven anywhere. Assume nothing.

*Why it is still the best neural idea on the list:* it needs no offline
training pipeline over game assets, no bundling problem (`36` §8), no new
sampled texture, and no VRAM argument. It is one class, one network, one gate.

### D2 — Glints

Deliot & Belcour's real-time glints via distributed binomial laws on
anisotropic grids (2023); Kneiphof & Klein, *Real-Time Image-based Lighting of
Glints* (CGF 2025), which replaces the spatio-angular search with a counting
model over binomial approximations; and *Position-Normal Manifold for Efficient
Glint Rendering on High-Resolution Normal Maps* (arXiv 2505.08985).

Wet asphalt, sequins, car paint, chrome cyberware, rain-lit streets — this is a
Cyberpunk-shaped effect if ever there was one, and it is the correct answer to
"realistic light transfer across lots of micro features" when the micro
features are *discrete* rather than statistical (A4 handles the statistical
case).

*What kills it:* glints need UVs and derivatives → U2. A screen-space
approximation from normal derivatives is possible and would be a different,
worse effect. And glints are the highest-frequency signal imaginable, aimed
straight at `0d`'s motion-smeared upscale.

### D3 — Real glass refraction

`20` Phase 0.5, unchanged: `ee6d252e090adc74.rgs_reflection_transparent_main`
already reconstructs P and V from depth and normal and traces a mirror ray.
Repoint that direction to a refracted one, with the origin sign corrected —
`20` §1's `P − D·ε` sits *outside* the surface and a transmitted ray fired from
it self-hits.

*What kills it:* `20` open item 1, still open — nobody has named the consumer
of that buffer, and per GOTCHAS #11 the compositing mode sets the ceiling. If
the buffer is added over an already alpha-blended glass pixel, the same maths
produces a ghosted double image rather than refraction. **Name the consumer
before writing the splice.** It is offline work and needs no launch.

### D4 — Per-material sample counts

`29` §B5's degenerate outer loop `%12276`/`%12818`, whose continue block has no
predecessor — a dxil-spirv structurisation artifact that is a sample-loop
skeleton. The class gate is already fetched. Wiring the back-edge is the
feature.

*What kills it:* U5. Nothing here may be built before a payload sentinel proves
a looped trace executes, and that has been true and unactioned for three
documents.

### D5 — Neural woven fabric

*Real-time Neural Woven Fabric Rendering* (arXiv 2406.17782) baked to a LUT.
The honest note: `22` established there is no weave *data* in this renderer to
condition on — cloth is Standard, with one isotropic GGX lobe and a roughness
map. A woven model with no weave parameters is A2 with more steps. Listed for
completeness and ranked last on purpose.

### D6 — Denoiser and surface-cache tuning

`33` §3 built `detail_engine.lua` over 22 CVars — `Editor/Denoising/NRD`,
`ReBLUR/*`, `ReLAX/*`, and `Editor/SHARC`, the world-space hash radiance cache
whose cell size bounds bounce-light detail. Never A/B'd. The first thing to
check is not a defect: if DLSS Ray Reconstruction is on, it replaces NRD
wholesale and every NRD knob is bypassed. `EMM_SurfaceCacheID` and
`EMM_SurfaceCacheResolution` in §1.2's enum are the debug views for the SHARC
side.

Zero shader risk, applies live, and it is the cheapest thing in Tier D by an
order of magnitude.

---

## 7. Gates, in dependency order

Per GOTCHAS "verify the mechanism before building the matrix". Each gate's
failure invalidates what follows it.

| gate | question | cost | falsifier |
|---|---|---|---|
| **G-U4** | What do subtypes `{12,13,14,15,17,21,25,26,30,31}` mean? (compute branches on only `{17,21,25}`) | one hunt paint, one launch | they are not material identities → B3 and the A2 gate collapse to `22` §5's status quo |
| **G-A1** | Does the SER splice *execute*? | one build, one launch, frame time | no measurable delta → A1 dies, nothing else is affected |
| **G-U2** | Does a fragment splice execute at all? (`36` G1) | one tint, one launch | no pixel change → **Tier B and half of Tier C die** |
| **G-U3** | What writes the `R8_UINT`, and what does it hold? | offline: name the raster writer | it is load-bearing → U3 dies, B2 dies, B4 survives |
| **G-B1** | Is the hair direction readable at an evaluator splice site? | offline disassembly read | not present or view-space-only → B1 dies |
| **G-U1BDA** | Can a shader read a layer-allocated buffer by baked address? (`36` G2) | one splice, one launch | no → U1 is the only route to Tier C, at much higher risk |
| **G-U1** | Can we write an SRV into the game's heap and have it survive? | RED4ext work | no → Tier C dies except C1's 3D case |
| **G-U5** | Does a looped trace execute? (`29`, `32`, `39` §6) | payload sentinel, one launch | no → D4 dies, R6 dies |
| **G-D1** | Does DP4a arithmetic run in a spliced module? then CoopVec | `36` G3 | pipeline creation failure → D1 dies |

**Recommended order: G-U4, then G-A1, then G-U2.** The first is free and
reframes three documents. The second cannot break anything. The third decides
the fate of more of this list than any other single experiment.

Note that G-U4 and A2 can be **one launch**: an ungated sheen plus a subtype
rainbow answers "does a compute splice paint", "which class is cloth" and "what
are the subtypes" simultaneously. That merge is `22` §7's proposal and it
survives everything in this document.

---

## 8. Do not re-litigate

Restated so no successor re-derives them. Each points at its evidence.

| closed | why | where |
|---|---|---|
| Refraction as a material property | 0 `Refract`/`Reflect` extinsts in 3005 modules; no IOR, no dielectric CVar | `20` |
| Cloth anisotropy via the structure tensor | sub-texel weave → the tensor returns noise and the confidence term correctly collapses it to zero; it fails *quietly* | `22` §4c |
| Cranley–Patterson rotation / per-bounce decorrelation | no low-discrepancy sequence exists to rotate; bounces are already decorrelated at the noise floor | `37` |
| The engine's skin back-depth target | exists and runs; heap index moved 73203 → 503350 in 29 seconds | `39` §6, GOTCHAS #13 |
| A **second static** `OpTraceRayKHR` in a raygen | validates, is served, does not execute (`sctrl`, a positive control, came back vanilla) | `26` §7d |
| NTC-on-load as a VRAM answer | NVIDIA's own table: NTC-on-load VRAM = BCn VRAM | `36` R2 |
| Screen-space contact shadows for the hairline | the cause was a one-bit ray flag; no screen-space term was needed | `00` §10 |
| The hair BRDF *as previously built* | never shown to move a pixel in 70 modules | `19`, `27` §8 |

The last row is the one to read carefully. **B1 reopens the input, not the
verdict.** A geometric tangent is a reason to re-ask the question; it is not
evidence that the answer changed, and `16` still says the engine ships 41 hair
CVars that do the shading.

---

## 9. Confidence

| claim | confidence | basis |
|---|---|---|
| 0 of 3273 modules declare SER; the exe ships `cvRayTracingEnableReferenceSER` | **certain** | measured both sides this session |
| The SER splice assembles and validates at vk1.3 and vk1.4 | **certain** | `spirv-as` + `spirv-val`, diff read by hand |
| SER *executes* and buys frame time here | **unverified** | G-A1. GOTCHAS: a validated splice is not an executed one |
| 3225/3273 modules declare `PhysicalStorageBufferAddresses` | **certain** | measured |
| The G-buffer table at `registers[1]+0..+6`, formats and sizes | **certain** | prov log ∩ disassembly |
| `+3` (R8_UINT) is unread by 9/9 family-A and both GI resolvers | **certain** | offset census over the disassembly |
| `+3` is a *free* channel | **not established** — 105/220 other modules use that offset off the same base | G-U3 |
| The material byte carries a populated 5-bit subtype, tested in **67 of 81** modules that read it | **certain** | `dev/census_subenum.py`, whole 3273-module dump; supersedes this doc's own 406-file figure of 68 |
| The subtype is reachable at the evaluator splice site for one `OpBitwiseAnd` | **high** | the byte is already fetched; only `>>5` is consumed |
| What the subtypes *mean* | **unknown** | G-U4 |
| One of `+1`/`+2` carries `EMM_SurfaceHairDirection` | **plausible, unverified** — the shape and the enum both fit | G-B1 |
| Tensor cores reachable from a Vulkan layer under vkd3d-proton | **inferred** — standard layer practice, never tested here | `36` G3 / G-D1 |
| U1 (SRV injection into the game's heap) | **inferred, unverified** — this is the weakest load-bearing claim in the document | G-U1 |
| Class 2 is never tested | **certain** at 406 modules; `22` measured the same at 3153 | census |
| A fragment splice executes | **never tested in this repo** | G-U2 |

---

## Evidence index

| # | claim | how to reproduce |
|---|---|---|
| E1 | 0/3273 SER, 3225/3273 BDA | `cd ~/callisto_dump && grep -la invocation_reorder *.spv \| wc -l`; same for `physical_storage_buffer`. **Use `-la` from inside the directory — `grep -r` over the dump returns 0 for strings that are present** |
| E2 | driver extension set | `vulkaninfo \| grep -iE 'invocation_reorder\|cooperative'` |
| E3 | the G-buffer table | `python3 dev/prov_map.py analysis/evidence/meta/capA_prov.jsonl --module 4d46848998312027` (run from `GraphicsCaptures/`) |
| E4 | `+3` has no compute writer, 22 modules in its heap neighbourhood | `dev/prov_map.py … --image 0x1c850e10` |
| E5 | the `+3` skip across families | offset census over `dev/disasm/compute/*.spvasm`, matching `OpAccessChain … %registers %uint_1` → `OpLoad` → `OpIAdd … %uint_N` |
| E6 | two 10:10:10:2 channels, one decoded as a unit direction | `dev/disasm/compute/4d46848998312027.dxil.spvasm:335–373`, ids `%176`–`%219`, `%366`/`%377`/`%379` |
| E7 | the class/subtype split and its switch | `spirv-dis ~/callisto_dump/667c55bd59f5f145.dxil.spv`, ids `%235`/`%246`/`%247`, `OpSwitch` at the `%1361`/`%1360` arms |
| E8 | enum census | regex census over `dev/disasm/**/*.spvasm` for `OpIEqual`/`OpSwitch` on `>>5` and `&31` results |
| E9 | `EMM_*` surface debug views, `RMT_*`, `cvRayTracingEnableReferenceSER` | `strings -n 5 <exe> \| grep '^EMM_\|^RMT_\|ReferenceSER'` |
| E10 | the SER splice | `spirv-as --target-env spv1.4`, `spirv-val --target-env vulkan1.4`, diff vs vanilla = 3 instructions / +60 bytes |
