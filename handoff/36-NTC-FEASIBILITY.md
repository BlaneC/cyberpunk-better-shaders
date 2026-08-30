# 36 — Neural Texture Compression (RTX NTC) as a Cyberpunk mod: feasibility

Written 2026-08-29. Investigation only — nothing was built, patched or
launched. Sources: `NVIDIA-RTX/RTXNTC` @ v0.10.0-BETA and its
`RTXNTC-Library` submodule (cloned, read); `ntc_medium_size.pdf`
(Vaidyanathan et al., *Random-Access Neural Compression of Material
Textures*, 2023 — the paper this SDK implements); the 3273-module SPIR-V
dump in `~/callisto_dump/`; the RDAR index of
`HD Reworked Project.archive`; a `strings` CVar audit of
`Cyberpunk2077.exe` (`16`'s method, per GOTCHAS #8); and the local
hardware/toolchain.

**Verdict, one line: inference-on-sample is *architecturally reachable*
through this repo's existing vehicle — three independent things line up in
its favour, and none of the obvious blockers is the one that kills it — but
it is not *affordable*, and the thing that kills it is SIMD divergence,
which the paper itself lists as unsolved future work and which describes
Cyberpunk's entire G-buffer pass.**

**Second line, the one that matters more: nobody has measured how much VRAM
HD Reworked actually costs.** The whole prize is bounded by that number and
it is currently unknown. §10 G0 is a half-hour of work and it can end this
project before a line of code is written. Do it first.

---

## 1. The prize, sized

`HD Reworked Project.archive` (Balanced, v2.0), parsed straight from its
RDAR v12 index:

| | |
|---|---|
| format | RDAR version 12, index at `0x29a2f000`, 24204 B |
| files | **276** |
| segments | 545, of which 505 are `KARK` (Oodle Kraken) compressed |
| on disk | 698.5 MB |
| uncompressed payload | **970.2 MB** |
| largest files | 8 × 22.37 MB — that is 4096² BC7 with a full mip chain |
| median file | 2.80 MB |

276 files is a **small** set. This is not a "thousands of textures" problem;
it is a targeted environment-surface pack. The 21 depot paths recoverable
from the 40 uncompressed segments (`surfaces\s\graffiti\common__j_m.xbm`,
`road_devimanhend_a_d.xbm`, `valentinos_dec_v30_d.xbm`, …) confirm it:
decals, graffiti, roads, street surfaces, gang decals. The suffix
convention (`_d` diffuse, `_n` normal, `_r` rough, `_m` metal, `_a`, `_j`)
is intact and machine-readable, which matters in §8.

**970.2 MB is a disk figure, not a VRAM figure.** Cyberpunk streams
textures against a pool. The resident fraction at any moment is some
unknown share of that. The ceiling on any NTC win is therefore

    (resident share of 970.2 MB) − (the same textures as NTC latents)

and the first term is unmeasured. See G0.

### What the engine already offers (GOTCHAS #8)

Before designing anything, the exe was searched the way `16` should have
been. The engine does expose texture-memory levers:

- `PoolGPUTextures` — a named GPU texture pool.
- `m_textureMaxMipBias` / `m_textureMinMipBias`, with
  `gameuiTextureMaxMipBiasChangeEvent` / `…Min…` — live mip-bias plumbing
  wired to UI events.
- `TextureQuality` / `ConfigTextureQualityLevel` /
  `m_textureQualityPresetLocalizedName` — the quality preset ladder.
  Ultra Plus already drives this (`Cyberpunk.SetOption('/graphics/presets',
  'TextureQuality', …)` in `modules/setautoquality.lua`).
- `rendRenderTextureBlobStreamable`, `rendRenderTextureBlobMipMapInfo` —
  the streaming blob types.

So there is an engine-side answer to "HD Reworked costs too much VRAM":
lower `TextureQuality` or push a mip bias, and the streamer serves smaller
mips of the same textures. It is a *worse* answer than NTC — it throws away
the detail everywhere rather than storing it cheaply — but it costs nothing
and it exists today. It is the control that NTC has to beat, and G0 should
measure it alongside the baseline.

---

## 2. Position: hardware and toolchain

| | | verdict |
|---|---|---|
| GPU | RTX 4070, 12 GB, Ada | NTC's *recommended* tier for on-sample. OK |
| driver | 610.43.02, Vulkan 1.4.341 | ≥ 570 required for Vk CoopVec. OK |
| `VK_NV_cooperative_vector` | **present, revision 4** | OK |
| `VK_NV_cooperative_matrix2` | present | not needed |
| API path | DX12 → vkd3d-proton → Vulkan | **This is the good branch.** NTC's DX12 CoopVec route needs SM 6.10 / Agility SDK preview / Windows Developer Mode and NVIDIA say *do not ship*. The Vulkan route is shippable. Running under Proton puts us on the shippable one by accident |
| CUDA | nvcc 13.2 | SDK tested at 12.4; version risk, not a blocker. Compression needs CUDA and Turing+; a 4070 is fine |
| cmake | present | OK |
| dxc / slangc | **absent** | needed to compile the NTC inference shader. Installable |
| .NET 8 | **absent** (mono only) | WolvenKit CLI is .NET 8. Needed for §7 extraction |

Nothing here blocks. The Proton/Vulkan position is genuinely lucky: the DX12
half of NTC is the pre-release half.

---

## 3. What NTC actually asks a renderer for

From `docs/integration/InferenceOnSample.md` and
`RTXNTC-Library/include/libntc/shaders/`:

**The network** (`InferenceConstants.h`): 48 → 64 → 48 → 32 → 16, four
matmuls, int8 weights with per-column fp32 scales.
`48·64 + 64·48 + 48·32 + 32·16 = 8192` MACs per texel. Input is 14
supplemental channels (12 positional-encoding + mip twice) plus 2 × 16
latent features.

**Per-texel work** on top of the matmuls: **8 latent taps** — two neural
mips × four `Texture2DArray` array layers — each a bilinear `SampleLevel`
on a `A4R4G4B4_UNORM_PACK16` array, plus the weight `ByteAddressBuffer`
loads.

**The four inputs** the shader needs:

1. `NtcTextureSetConstants` — a small constant block per texture set.
2. Weights — a `ByteAddressBuffer` (nonzero offsets supported).
3. Latents — a `Texture2DArray`, `VK_FORMAT_A4R4G4B4_UNORM_PACK16`.
4. A bilinear/wrap `SamplerState`.

**The call**:

```
bool NtcSampleTextureSet(desc, latentTexture, latentSampler, weightsBuffer,
                         weightsOffset, int2 texel, int mipLevel,
                         bool convertToLinear, out float outputs[16]);
```

Note: **integer texel + explicit mip level**, not UV. And it returns *one
unfiltered texel* — filtering is the caller's problem (§6).

---

## 4. The hook surface — what this repo's layer can and cannot reach

This is the part that came out better than expected. Four findings.

### 4a. The bindless sample idiom is universal — 239/239

Scanned the first 800 `.dxil.spv` in `~/callisto_dump/`; 239 are Fragment
stage and contain `OpImageSampleImplicitLod`. **All 239** also declare
`OpTypePointer PushConstant` and `OpTypeRuntimeArray`. Zero exceptions.

The idiom, read out of `2c5f16304b811159.dxil.spv` (26 sample sites):

```
%443 = OpAccessChain %_ptr_Uniform_v4float %193 %uint_0 %uint_12   ; material CBV, member 12
%444 = OpLoad %v4float %443
%445 = OpBitcast %v4uint %444
%446 = OpCompositeExtract %uint %445 0                              ; relative descriptor index
%447 = OpIAdd %uint %446 %uint_0
%449 = OpAccessChain %_ptr_PushConstant_uint %registers %uint_31    ; SRV heap base (root const 31)
%451 = OpLoad %uint %449
%452 = OpIAdd %uint %451 %447                                       ; absolute bindless slot
%448 = OpAccessChain %_ptr_UniformConstant_11 %14 %452
%453 = OpLoad %11 %448
%454 = OpSampledImage %287 %453 %176
%455 = OpImageSampleImplicitLod %v4float %454 %456 None
```

Two consequences:

- A **structural detector** for "this is a material texture fetch" is
  writable, and it is the same *shape* in every fragment shader that
  samples. That is exactly the kind of site this repo already patches at
  scale (70 modules in the hair work).
- **The shader computes a per-texture identity at runtime** — `%452`, the
  absolute bindless slot. That is the hook for redirection: `if
  ntcSetId[%452] != 0 → inference, else → the original sample`.

Stage census (400-file sample of the 3273-module dump): 39% Vertex, 35%
Fragment, 22% Compute, ~4% RT. So the fragment population needing the patch
is on the order of 1000+ observed, and the true permutation count is larger
than the dump.

### 4b. `PhysicalStorageBufferAddresses` is already on — no descriptor surgery needed

The fragment shader declares:

```
OpCapability PhysicalStorageBufferAddresses
OpExtension  "SPV_KHR_physical_storage_buffer"
OpCapability RuntimeDescriptorArray
OpExtension  "SPV_EXT_descriptor_indexing"
OpExtension  "SPV_NV_raw_access_chains"
```

(SPIR-V 1.3, generator 30017 = dxil-spirv.)

This is the single most important finding in the document. It means the
whole NTC data path — weights, constants, the slot→set lookup table, and
(with §4c's caveat) the latents — can be reached from a **raw 64-bit device
address baked into the swapped module**, with:

- no new descriptor set,
- no `vkCreatePipelineLayout` interception,
- no `vkCmdBindDescriptorSets` interception,
- no touching vkd3d-proton's bindless heap at all.

The address is not known at build time, but it does not need to be: the
layer allocates its buffers at `vkCreateDevice` time and patches SPIR-V at
`vkCreateShaderModule` time, which is strictly later. The layer would move
from "serve a pre-built `.spv` from disk" to "patch the incoming module in
process, splicing today's device address as an `OpConstant`." That is a
real change to `swap_layer.c`'s character — it becomes a patcher, not a
file server — but it is ordinary work, not a research problem.

### 4c. The latent texture is the one thing BDA cannot reach

`NtcSampleLatentGrid` does `latentTexture.SampleLevel(...)` on a
`Texture2DArray`. You cannot name a texture by device address. Two ways
out:

- **Manual bilinear from a buffer.** Store the latents in a BDA-reachable
  buffer and hand-roll the filter: 8 grid taps × 4 texels = 32 16-bit loads
  + lerps per texel, replacing 8 hardware samples. `A4R4G4B4` unpacks in a
  few ALU ops. Costs real throughput; costs no plumbing. **This is the
  route to prototype**, because it keeps the layer's blast radius at zero.
- **Inject a descriptor.** Hook `vkCreateDescriptorSetLayout` /
  `vkCreatePipelineLayout` to append a set, and bind it. Cheaper at
  runtime, far more invasive, and it puts the layer in the path of every
  pipeline in the game.

### 4d. The slot→set table defeats GOTCHAS #13 (this is not the R3 dead end)

GOTCHAS #13 closed the back-depth route because a bindless index moved from
73203 to 503350 in 29 seconds and a **baked** constant would have indexed
whatever landed in that slot. That rule kills baked addresses; it does not
kill *live* ones.

The design here is a GPU-side array `ntcSetId[slot]`, maintained by the
layer from descriptor writes, read by the shader with the same `%452` the
game just computed. The index moving is exactly what the table absorbs.
GOTCHAS #13's three-part test — does it exist, does it run, **is its
address stable** — is answered "the address does not need to be stable,
because nothing is baked."

**But this is inference, not evidence.** The layer does not hook descriptor
writes today and it has never been demonstrated that the write stream is
observable and complete under vkd3d-proton (which may use
`VK_EXT_descriptor_buffer` or `vkUpdateDescriptorSetWithTemplate` rather
than plain `vkUpdateDescriptorSets`). G4 exists to prove it. State this at
the confidence it has: **plausible mechanism, unverified.**

### 4e. Enabling CoopVec from a layer

The layer can add `VK_NV_cooperative_vector` to `VkDeviceCreateInfo` and
`VkPhysicalDeviceCooperativeVectorFeaturesNV` to its `pNext` at
`vkCreateDevice`, and must correspondingly report the extension through
`vkEnumerateDeviceExtensionProperties`. Standard layer practice. The
swapped SPIR-V then declares `OpCapability CooperativeVectorNV` /
`OpExtension "SPV_NV_cooperative_vector"`.

Two unknowns worth naming rather than assuming:

- Game modules are **SPIR-V 1.3**. Whether `SPV_NV_cooperative_vector` is
  accepted against a 1.3 header by this driver is unverified. Bumping the
  header word is trivial if not.
- vkd3d-proton may re-query features after the layer's edit and behave
  oddly. Unverified.

**Fallback that needs none of this**: the DP4a path
(`Inference.hlsli`, `NTC_MLP_…` int8 dot products) runs on any SM6-class
GPU and needs only `OpCapability DotProductKHR` /
`DotProductInput4x8BitPackedKHR`, which NVIDIA supports. NVIDIA describe it
as "significantly slower… for functional validation," so it is the way to
*prove the pipeline*, not the way to ship. Good news for G-gate order.

### 4f. The path tracer is not blocked by derivatives (a worry that turned out false)

The obvious objection to NTC in a path tracer is that `NtcSampleTextureSet`
needs an explicit `mipLevel` and closest-hit shaders have no implicit
derivatives. Checked: **Cyberpunk's `chs_main_*` permutations already use
`OpImageSampleExplicitLod` exclusively** — 0 implicit, 2–6 explicit across
`0b190a1f53c31393.chs_main_{0..18}`. The engine already computes a ray-cone
or equivalent LOD and passes it in. That value is exactly NTC's
`mipLevel` argument.

So the PT path is *reachable*. It is not therefore *cheap* — §6.

---

## 5. The four routes

### R1 — Inference on sample. **The only route that saves VRAM.**

Latents stay compressed in VRAM (~2.5–5 bpp against BC7's 8) and every
material fetch decodes on the fly. Reachable per §4. Cost per §6. Bundling
problem per §8. **This is the study's subject and its verdict is §9.**

### R2 — Inference on load. **Does not solve the stated problem. Say so plainly.**

Decompress NTC → BCn at load time. The NTC README's own table is explicit:
NTC-on-Load has a 2.50 MB disk size and a **12.00 MB VRAM size** — identical
to plain BCn. It wins disk and PCIe traffic; VRAM is unchanged. HD
Reworked would go 698 MB → ~150 MB on disk and cost exactly what it costs
today in memory. If the goal is "put HD Reworked back without VRAM
concerns," R2 is not an answer to it.

(It is not *worthless* — it would let you ship the *full* HD Reworked
rather than Balanced at Balanced's download size. Different goal.)

### R3 — Inference on feedback. **Right shape, wrong engine.**

Sampler Feedback finds the visible tiles, decode only those into a sparse
tiled texture as BCn. This is the route that would give most of the VRAM
win **without touching a single material shader** — the game keeps sampling
ordinary BCn. It requires reserved/tiled resources and sampler feedback
wired into the streamer, which lives inside REDengine, not in any surface a
layer can reach. Also listed as broken on AMD in NVIDIA's own known issues.
**Closed for a mod**; reopens only if CDPR ships it.

### R4 — The control: no NTC at all.

Re-encode the 276 textures offline (BC7 at 2K instead of 4K, or BC1/BC5
where the channel budget allows), or drive `TextureQuality` / mip bias per
§1. Zero risk, hours of work, and it saves a similar order of VRAM by
throwing away the detail NTC would have kept. **R4 is the number R1 has to
beat, and G0 should measure it.**

---

## 6. The cost model — the paper's own numbers

Table 4 of `ntc_medium_size.pdf`, and §6.5.2. Full-screen quad, 3840×2160,
**RTX 4090**, Paving Stones (8 4k channels), **one texture set**:

| | ms |
|---|---|
| BC7, hardware trilinear | **0.49** |
| NTC 0.2 bpp | 1.15 |
| NTC 0.5 bpp | 1.46 |
| NTC 1.0 bpp | 1.33 |
| NTC 2.25 bpp | 1.92 |

So **2.3× to 3.9× the cost of BC7**, on the fastest consumer GPU that
exists, with zero divergence. Three riders from the paper, all of which
make it worse here:

1. **"We also implemented trilinear filtering for NTC by decompressing and
   filtering together eight texels and observed an 8× slowdown."** Trilinear
   is off the table. You must use Stochastic Texture Filtering — jitter the
   UV and the LOD, sample once, and let DLSS resolve the noise. Cyberpunk
   has DLSS, so the reconstruction exists; but STF changes the *look* of
   every surface it touches and the paper reports "minor specular
   flickering" even in a clean test scene.
2. **§5.2.1, SIMD divergence — this is the one that kills it.** Quoting:
   *"In this work, we have only evaluated performance for scenes with a
   single compressed texture-set… matrix acceleration requires uniform
   network weights across all SIMD lanes. This cannot be guaranteed since we
   use a separately trained network for each material texture-set… SIMD
   divergence can significantly impact performance and techniques like SER
   and TSU might be needed… we leave this for future work."*

   Every number in Table 4 is a single-material number. Cyberpunk's G-buffer
   pass is the opposite case by construction: a warp straddles many
   materials. The mitigation is to iterate the network over every unique
   texture-set in the warp — i.e. multiply the 8192-MAC cost by the number
   of distinct NTC sets a warp touches. And a mod gets a *second*
   divergence for free: NTC lanes and vanilla-BC7 lanes in the same warp,
   both paths executed.
3. Scaling to this machine. The 4070 has 5888 CUDA / 184 tensor cores
   against the 4090's 16384 / 512 — call it 2.8× less throughput at similar
   clocks. Taking the 0.5-bpp delta (1.46 − 0.49 = 0.97 ms at 4K):

   | scenario | est. added ms, full-screen, **no divergence** |
   |---|---|
   | 1440p native, 4070 | ~1.2 |
   | 1440p DLSS Quality (960p internal), 4070 | ~0.55 |

   Against a G-buffer pass that is a few ms total. And these are *floor*
   numbers: they assume one texture set on screen, hardware-sampled latents
   (§4c would replace 8 hardware taps with 32 manual loads), and no warp
   divergence. The real figure is unknown and could plausibly be several
   times this. **Nobody has measured NTC-on-sample in a real multi-material
   deferred pass. The paper says so itself.**

For the path-traced modes the multiplier is worse again: material fetches
happen per hit, per bounce, and closest-hit warps are *maximally* divergent
by nature — that is precisely the case NVIDIA say needs Shader Execution
Reordering.

---

## 7. The offline pipeline (the easy half)

Tractable, and worth stating because it is the part that *isn't* the
problem:

1. **Extract** the 276 `.xbm` from the archive. Segments are Oodle Kraken
   (`KARK`); needs WolvenKit CLI (.NET 8 — install) or an Oodle binding.
   Output: BC7 blobs + headers.
2. **Decode** BC7 → PNG/EXR per mip.
3. **Group** into texture sets (§8 — the hard part).
4. **Compress** with `ntc-cli`, `-p <psnr>` adaptive mode targeting ~40 dB
   (the SDK calls 35–40 dB sufficient, 50 dB perceptually lossless). Note
   adaptive is ~5× slower because it does several full runs. 276 textures ×
   a few minutes each on a 4070 = an overnight job, not a research project.
5. **Pack** the `.ntc` files into a sidecar the layer loads at
   `vkCreateDevice`.
6. **Neutralise the originals** — otherwise you pay for BC7 *and* latents
   and the VRAM goes *up*. The elegant version: ship the mod archive with
   the 276 depot paths present but carrying **1×1 stub textures** of a
   recognisable magic pattern. The engine loads nothing; the layer
   content-hashes the upload, recognises the stub, and binds the
   corresponding NTC set to that descriptor slot. This also solves
   identification (§4d) without a hash-to-path oracle. It has an obvious
   failure mode — if the NTC path does not run, those surfaces are 1×1 —
   which is arguably a feature during bring-up.

---

## 8. The bundling problem — the deepest structural issue

NTC's advertised ratio comes from compressing **correlated channels of one
material together**: albedo+normal+rough+metal+AO in one set, 9–10 channels
at ~5 bpp against ~24 bpp of BCn. Compress each texture as its own 3-channel
set and you are asking a neural codec to beat BC7 at BC7's own game on
uncorrelated data — the win drops from ~5× to maybe 1.5–2×, and 970 MB
goes to perhaps 500–650 MB instead of ~200 MB.

To bundle, you must know which textures form a material. Two obstacles:

- **In-shader**, the three fetches of one material read their descriptor
  indices from the *same* `BindlessCBV` at *different* member offsets
  (`[0][12]`, `[0][13]`, …). So the grouping is structurally visible — a
  patcher could detect "these sites share a CBV and differ only in member
  index" and hoist **one** `NtcSampleTextureSet` call for all of them. That
  is the right design and it is also the only way the perf math works, since
  it turns N inferences per material into one. But the CBV member layout
  varies per permutation and this is a substantially harder patcher than
  §4a's.
- **Offline, and worse: HD Reworked replaces only a subset of each
  material's textures.** Its 276 files are mostly `_d` and `_m`. Their `_n`
  and `_r` siblings stay vanilla, in the 61 GB base archives, quite possibly
  at a different resolution. To build a real bundle you must extract the
  vanilla siblings too, re-encode *them* into the NTC set, and redirect
  their fetches as well. **The scope silently expands from "276 textures"
  to "every material that touches any of those 276 textures," including
  vanilla data the mod never intended to change.** Mip-count and resolution
  mismatches between an HD 4K albedo and a vanilla 2K normal have to be
  reconciled inside a single latent grid.

This is the finding that makes R1 much larger than it first looks, and it
is independent of every performance question.

---

## 9. What kills it, ranked

1. **SIMD divergence in a multi-material deferred pass** (§6.2). Unsolved
   in the literature, structurally guaranteed here, unmeasurable without
   building most of the thing. This is the one.
2. **Bundling drags in the vanilla base game** (§8). Either accept ~2× not
   ~5×, or expand scope by an order of magnitude.
3. **Cost floor even in the best case** (§6.3): ~0.5–1.2 ms added at
   full-screen coverage on this GPU, before divergence, to save a few
   hundred MB — on a card that has 12 GB and a frame budget of ~16 ms.
4. **Loss of hardware anisotropic filtering** on road and street surfaces,
   which are exactly the grazing-angle, high-anisotropy cases where STF's
   noise is most visible and DLSS's resolve is most stressed.
5. **Permutation count**: 1000+ observed fragment shaders, more unobserved,
   each needing a patch that is far heavier than any splice this repo has
   shipped (an 8192-MAC network with 8 latent taps, versus one `OpFMul`).
6. **Execution risk, per precedent.** GOTCHAS records that a second
   `OpTraceRayKHR` spliced into a raygen **disassembles correctly, passes
   `spirv-val`, is served, and does not execute** under this vkd3d-proton.
   No fragment-stage splice has ever been proven to execute in this repo
   either — AgX went into compute. Assume nothing.

**None of these is the blocker people would predict.** Descriptor reach
(§4b), material identity (§4a), address stability (§4d), PT LOD (§4f) and
CoopVec availability (§2) all came out *in favour*. The project dies on
throughput and scope, not on plumbing.

---

## 10. Gates — in order, each with its falsifier

Per GOTCHAS "verify the mechanism before building the matrix": every gate
below has a step whose failure invalidates everything after it. Run them in
this order and stop at the first failure.

**G0 — Measure the prize. No code. Do this before anything else.**
Install HD Reworked; capture VRAM at three fixed save points (a dense
street, an interior, a vista) with `nvidia-smi` sampling plus the Nsight
capture already in this repo's workflow. Repeat without the mod. Repeat
with the mod and `TextureQuality` one notch down. Three numbers.
*Falsifier: if the delta is small, or if lowering TextureQuality recovers
it at acceptable cost, R4 wins and this document is closed.* Half an hour.

**G1 — Prove a fragment-stage splice executes at all.**
Take one `chs`/fragment module known to be dispatched, splice a visible
tint, launch, look. This repo has proven execution in Compute and RT
stages, never in Fragment. *Falsifier: no pixel change → the whole vehicle
is wrong for this feature.* Build a control that must be **visible** — a
neutral control proves nothing (GOTCHAS).

**G2 — Prove BDA injection.**
Layer allocates a buffer, writes a magic value, bakes the device address
into a swapped fragment module as an `OpConstant`, shader reads it and
tints on match. *Falsifier: no tint, or device lost.* This is the load
bearing assumption of §4b.

**G3 — Prove the math runs. DP4a first, CoopVec second.**
Splice a full 48→64→48→32→16 int8 network with constant weights into one
fragment shader and output a known vector as colour. DP4a path first — it
needs no device-creation changes and isolates "does the arithmetic run"
from "does the extension enable." Only then repeat with
`VK_NV_cooperative_vector` enabled from the layer. *Falsifier for the
second half: pipeline creation failure → ship-quality perf is off the
table, and given §6 that probably ends it.*

**G4 — Prove the slot→set table.**
Hook the descriptor write path; log slot churn for one stub texture over a
30-minute session with area transitions. *Falsifier: writes not observable
(descriptor buffers / update templates), or the mapping cannot be kept
current → §4d's answer to GOTCHAS #13 collapses and R1 is closed.*

**G5 — One texture, end to end.** One road surface, one NTC set, one
material, on screen, correct.

**G6 — Measure divergence.** Only now is the §6.2 question answerable.
Instrument a real street scene. *Falsifier: anything much above the §6.3
floor.* Expect this to be where it dies.

G0 through G4 are all diagnostics. Nothing before G5 produces a feature,
and that is deliberate — this is a project where four cheap gates can save
a month.

---

## 11. Confidence

| claim | confidence | basis |
|---|---|---|
| 276 files, 970.2 MB uncompressed | **certain** | RDAR index parsed directly |
| The bindless sample idiom is universal in Fragment | **high** | 239/239 measured over an 800-module sample |
| Fragment shaders declare `PhysicalStorageBufferAddresses` | **certain** | read from disassembly |
| CHS uses explicit LOD | **high** | 19 permutations of one CHS family checked; not swept across all RT modules |
| A layer can enable `VK_NV_cooperative_vector` under vkd3d-proton | **inferred** — standard layer practice, never tested here | G3 |
| Descriptor writes are observable and the slot→set table is maintainable | **inferred, unverified** | G4. This is the weakest load-bearing claim |
| NTC-on-sample is 2.3–3.9× BC7 for one set on a 4090 | **certain** | paper Table 4 |
| The 1440p/4070 estimates in §6.3 | **estimate** — linear scaling on pixel count and core count. Not measured |
| Divergence makes it much worse in a deferred pass | **high, unquantified** | paper §5.2.1 states the mechanism and declines to measure it |
| R2 saves no VRAM | **certain** | NVIDIA's own table |
| The bundling scope explosion (§8) | **high** | suffix histogram of recoverable paths is `_d`-dominated; the full inventory is behind Kraken and unread |

Two things this document did **not** do and a successor should: decompress
the Kraken segments to get the **complete** 276-path inventory with per-file
resolution and suffix (the grouping in §8 rests on 21 recoverable paths out
of 276), and sweep `OpImageSampleExplicitLod` across *all* RT modules rather
than one CHS family.

---

## 12. Recommendation

**Do G0. Then almost certainly do R4.**

The engineering here is more reachable than it looks — that is the real
surprise of the investigation, and §4 is worth keeping regardless of what
happens to NTC, because "a fragment shader can be handed arbitrary data by
device address and already computes a per-material identity" is a general
capability this repo does not currently use and could use for other
features.

But NTC-on-sample is a technique whose published performance envelope is a
single material filling the screen, and the thing being proposed is the
diametric opposite: a few hundred materials scattered across a deferred
pass on a GPU 2.8× slower than the one in the table, to reclaim a few
hundred megabytes on a 12 GB card. The paper's authors flagged exactly this
gap and left it as future work. Betting a month against it is not a good
trade until G0 says the prize is bigger than it currently looks.

If the answer to G0 is "HD Reworked costs 1.5 GB and the game OOMs in
Dogtown," the calculus changes and G1–G4 are worth the four sessions.

---

## Evidence index

| # | claim | where |
|---|---|---|
| E1 | RDAR v12, 276 files, 545 segments, 698.5 MB → 970.2 MB | `dev/` scratch parser over `HD Reworked Project.archive` header at `0x29a2f000` |
| E2 | 8 files at 22.37 MB = 4096² BC7 + mips | per-file segment sum |
| E3 | Kraken segments, 40/545 uncompressed, `KARK` magic | first-segment hexdump |
| E4 | depot paths + `_d/_n/_r/_m/_a/_j` convention | `strings -n 8` over uncompressed segments (21 paths) |
| E5 | engine texture-memory CVars | `strings -n 5 bin/x64/Cyberpunk2077.exe` |
| E6 | 239/239 Fragment sample idiom | scan of first 800 `~/callisto_dump/*.dxil.spv` |
| E7 | the sample-site disassembly | `2c5f16304b811159.dxil.spv` lines ~886–902 |
| E8 | fragment capabilities incl. BDA | same module, `OpCapability` block |
| E9 | CHS explicit-LOD only | `0b190a1f53c31393.chs_main_{0..18}.spv` |
| E10 | stage census | 400-module sample of 3273 |
| E11 | MLP 48/64/48/32/16, 8 latent taps, A4R4G4B4 | `RTXNTC-Library/include/libntc/shaders/InferenceConstants.h`, `InferenceCoopVec.hlsli`, `Inference.hlsli` |
| E12 | Table 4 perf, 8× trilinear, §5.2.1 divergence | `ntc_medium_size.pdf` §6.5.2, §5.2.1, §5.3 |
| E13 | NTC-on-Load VRAM = BCn VRAM | `RTXNTC/README.md` compression-rate table |
| E14 | DX12 LinAlg is do-not-ship; Vulkan CoopVec is shippable | `RTXNTC/README.md` warning block |
| E15 | `VK_NV_cooperative_vector` rev 4, driver 610.43.02 | `vulkaninfo`, `nvidia-smi` |
