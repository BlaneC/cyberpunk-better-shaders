# Upload survey + MS-GGX energy compensation — working notes

Branch `ms-ggx-energy-comp`. Two pieces of work: a generalized texture-upload
survey (complete), and multi-scatter GGX energy compensation (located, blocked
on verification — nothing spliced).

## 1. Upload survey — DONE

Generalizes the one-off SSS-kernel dump into a full inventory of CPU→image
uploads, so any runtime-generated LUT can be found and fingerprinted for the
`CopyTextureRegion` hook in `main.cpp`.

### Tooling
- `analysis/probe/probe_layer.c` — added env-gated survey mode. Default
  behaviour is unchanged (byte-identical output to previous runs); with
  `NGFXPROBE_SURVEY=1` the narrow kernel-LUT filter (`h<=16 && fmt in {97,109}`)
  widens to every upload, adding `ew/eh/bpp/trunc` and an `fnv` content hash.
  `NGFXPROBE_SURVEY_HEX` caps the hex payload (default 4096 B); the hash always
  covers the *full* payload so large uploads can still be diffed.
- `dev/survey_uploads.py` — summarizes one log, or diffs two for determinism.

Bug found and fixed while building this: the byte-per-pixel table was shifted
by 2 above VkFormat 69 (`R16_UNORM` is 70, not 72), so `R16_UNORM`, `R32_UINT`
and `R32G32B32A32_UINT` were sized wrongly. The two formats the original SSS
hunt used (97, 109) were correct by luck, which is why it never surfaced.

Note `log_open` uses `fopen(path, "a")` — **delete the log between runs** or
two replays concatenate into one file.

### Run
```
VK_ADD_LAYER_PATH=$PWD/analysis/probe VK_INSTANCE_LAYERS=VK_LAYER_NGFXPROBE_probe \
NGFXPROBE_STRIP_ALLOC=3 NGFXPROBE_SURVEY=1 \
NGFXPROBE_LOG=$PWD/analysis/evidence/survey/capA_survey.jsonl \
/opt/nvidia/.../host/linux-desktop-nomad-x64/ngfx-replay \
  --no-block-on-incompatibility --present-hidden -n 1 --quiet \
  --no-multithreaded-init GameThread_2026_08_23_22_24_36.ngfx-capture
# exit=1 is normal
python3 CallistoSSS/dev/survey_uploads.py <capA.jsonl> <capB.jsonl> --min-px=4096
```

### Results (capA: 691 destination images, 4170 uploads)
Validation: the survey independently rediscovered the known SSS kernel —
32×8 R32G32B32A32_SFLOAT, single upload, 4096 B, `fnv=90ed1e0d1410993f`, which
matches `fnv1a64(analysis/evidence/sss_kernel_texture.bin)` exactly.

Deterministic across both captures (i.e. safely fingerprintable), LUT-shaped:

| dims | format | count | note |
|---|---|---|---|
| 32×8 | R32G32B32A32_SFLOAT | 1 | the known SSS diffusion kernel |
| 32×32 | R32G32B32A32_SFLOAT | 17 | smooth low-magnitude RGB ramps, alpha=1 |
| 48×48 | R32G32B32A32_SFLOAT | 1 | |
| 256×64 | R32G32B32A32_SFLOAT | 1 | largest float LUT; leading texels all zero |
| 4×256 | R16G16B16A16_SFLOAT | 1 | |
| 1024×1024 | B10G11R11_UFLOAT | 2 | |
| 2048×2048 | R16_UINT | 2 | |

**Caveat that matters for interpretation:** an ngfx capture restores resource
contents by replaying them as uploads, so this inventory mixes genuine
engine-init CPU uploads with capture-restore traffic. The screen-resolution
entries (1280×720, 2560×1440) are certainly the latter. The survey narrows the
candidate set; confirming a given texture is uploaded by the *live* game still
requires the DLL's `CopyTextureRegion` logging.

No classic split-sum DFG/environment-BRDF LUT appeared, and no texture with an
obvious blue-noise signature was confirmed. Do not assume either exists.

## 2. MS-GGX energy compensation — located, NOT implemented

Goal: recover the energy single-scattering GGX loses at high roughness, via
`comp = 1 + strength * F0 * (1/E_ss - 1)`, applied to every material (no skin
gate). `strength=0` and `roughness=0` both give exactly 1.0 — the regression
mode, same discipline as Tier 1.

### The site is fully identified
In `dev/disasm/spv_0170.spvasm`, the GGX block above the first primary diffuse
triple (triples at lines 8883 / 9807 / 13891):

| id | meaning |
|---|---|
| `%5649` | perceptual roughness R, `NMin(%5648, 1)` (line 8547) |
| `%5655` | α = R² (line 8553) — the common α source, shared with the sampling branch |
| `%691/%693/%695` | F0 rgb = metallic term + 0.04 (lines 3266–3268) |
| `%9963` | clamped `dot(N,V)` |
| `%9948` | clamped `%9946` — the L-side cosine |
| `%9980` | GGX **D** = α²/(π·(NoH²(α²−1)+1)²) |
| `%9986` | **Vis** = 0.25/((`%9963`+`%9948`)·(1−α/2)+α) |
| `%9990` | Schlick pow5 via the spherical-gaussian fit (5.55472994 / −6.98316002) |
| `%9995..%9997` | **F** rgb |
| `%9998` | Vis·D |
| `%7576/%7578/%7580` | **F·D·Vis** — the three values to multiply |

Structural anchor for the patcher: three consecutive `OpFMul` sharing the same
second operand (`%9998`), whose first operands are the Schlick F outputs.
Splice point is per-channel because F0 is per-channel.

Downstream, specular takes weight `%7581` (`= %9016 * %9007`), *not* the
diffuse's `%7583` (`= NoL * %9006`), then light colour `%5650..%5652` and a
byte-encoded intensity `%7604`.

### Why it is not spliced yet — blocker
`comp` depends on `E_ss` in absolute terms (`1/E_ss`), so the lobe's
normalization must be right. Integrating the lobe exactly as read above
(`dev/fit_ms_ggx.py`) gives directional albedo far below any plausible value:

| α | E_ss as-read | correct Smith-correlated GGX |
|---|---|---|
| 0.25 | 0.407 | 0.916 |
| 0.50 | 0.287 | 0.688 |
| 1.00 | 0.137 | 0.307 |

Pointwise, `%9986` is a systematic **2–4× smaller** than correct
height-correlated Smith visibility (ratio 0.50 at NoV=NoL=1, falling to ~0.22
at mid angles). A shipped renderer does not discard 60–75% of its specular
energy, so this is a misreading, not a discovery. The integrator itself is
sound — GGX `D` normalizes to 1.0 under it.

Most likely explanations, in order:
1. `%9948` is not plain NoL. It is a phi out of a branch computing
   `sqrt(clamp(%5402²·…))` — area-light / light-radius handling — so it may be
   a solid-angle-modified cosine, which would break the reciprocal-lobe
   assumption the integral rests on.
2. Normalization is folded into `%7581 = %9016 * %9007` rather than living in
   the BRDF, making `F·D·Vis` only part of the lobe.
3. The denominator operands are not NoV/NoL in the sense assumed.

**Next step:** resolve which, by tracing `%9946`/`%9016`/`%9007` back to their
sources, or empirically — splice a debug swap that writes `D`, `Vis` and the
final spec into a scratch UAV and read it back under `ngfx-replay`, which is
how the SSS kernel layout was pinned down. Only once `E_ss` reproduces
offline should the compensation be authored.

Splicing a global multiplier on the current reading would risk a large
brightness error across every material in the game — the exact failure mode
this is meant to prevent.
