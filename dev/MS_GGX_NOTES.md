# Upload survey + MS-GGX energy compensation — working notes

Branch `ms-ggx-energy-comp`. Two pieces of work: a generalized texture-upload
survey (complete), and multi-scatter GGX energy compensation (spliced,
launched, and **confirmed on screen 2026-08-28** — the feature doc is
`handoff/28-MS-GGX-ENERGY.md`).

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

## 2. MS-GGX energy compensation — implemented, launched, confirmed

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

### The blocker — RESOLVED 2026-08-28

The blocker recorded here was **two independent misreadings**, both now fixed
in `dev/fit_ms_ggx.py`. Its old text is preserved below the fold for the
pattern; the conclusion is superseded.

#### (a) The block analysed above is the AREA-light arm, not the BRDF

`spv_0170` carries **two structurally identical GGX evaluators**, selected at
line 8557 by `%5654 = (flags & 2) == 0`:

| block | lines | selected when |
|---|---|---|
| `%12540` — **punctual** | 8558–8613 | `(flags & 2) == 0` |
| `%12539` — area / tube | 8623–9998 | otherwise |

Everything in §2 above (`%9980`, `%9986`, `%9948`, `%7576/78/80`) is the
**area** arm. Hypothesis 1 was right, and provably so — the area arm is a
textbook tube+sphere light evaluator:

- `%5407 ± %5404` are the two **endpoints of a tube light**; `%9037 =
  0.5·(cos_a + cos_b)` is the standard two-endpoint irradiance average.
- `%5402` is the **sphere radius**; `%9944 = sqrt(clamp(r²·…))` is sin(σ).
- `%9947 = (max(NoL,−s) + s)² / (4s)` is Frostbite's sphere-light **horizon
  falloff** (Lagarde & de Rousiers, *Moving Frostbite to PBR*).
- `%9007 = (α/α′)²` is **Karis's sphere-light specular normalization**, and
  `%9016 = clamp(radius·100, 0, 1)` fades it in — which is why the area arm's
  spec weight `%7581` is zero at zero radius.

So `%9948` is a sphere/tube *illuminance factor*, not a cosine, and `%7581`
carries area-light normalization. Neither belongs in a BRDF integral. The
punctual sibling has plain `%6767 = clamp(dot(N,L))`, plain `%6782 =
clamp(dot(N,V))`, and spec weight `1.0`. **That is the site to read.**

This is the fifth instance of `GOTCHAS #10` — a patch or a reading applied to
one of N structural siblings. Here the two arms share every formula verbatim,
so nothing about the disassembly looked wrong.

#### (b) Specular is never multiplied by NoL

At the consumption site (lines 8890–8912) the two lobes are assembled
asymmetrically:

```
diffuse   %5111 = (albedo/π) · lightColour · %7583      %7583 = NoL
specular  %5132 = lightColour · intensity · %7575 · %7581
                                                        %7581 = 1  (punctual)
```

`F·D·Vis` is therefore already the BRDF-**times-cosine** the shader renders;
the cosine is folded into the engine's `Vis`. The old `fit_ms_ggx.py` applied
another `NoL` in its integrand (`integrand = D * Vis * nol * …`), undercounting
by roughly ⟨NoL⟩. Between (a) and (b), the "2–4× too low" gap is fully
accounted for.

#### (c) The normalizer is exactly 0.5, analytically

As α → 0 the NDF collapses to `H = N`, so `L → mirror(V)` and `NoL → NoV`.
With `dω_L = 4·VoH·dω_H` and `∫ D(H)·NoH dω_H = 1`:

```
E_ss(α→0) = 4·NoV · Vis(NoL=NoV) = 4·NoV · 0.25/(2·NoV) = 0.5
```

**independent of NoV** — confirmed to 1.2e-5 by `--self-check`. (Evaluating the
limit at finite α biases it low at grazing NoV, because part of the lobe falls
below the horizon; that decays monotonically to 0.5 and is a truncation
artefact, not a property of the lobe.)

The engine's lobe therefore sits a uniform **factor of 2** below an
energy-conserving one at mirror roughness. Whether that 2× is a real deficit
absorbed into authored light intensities, or another factor upstream in
`%5650`/`%7604`, is **still unresolved — and no longer matters**, because
compensation is defined against the lobe's own mirror limit:

```
E_rel(α, NoV) = E_ss(α, NoV) / 0.5
comp          = 1 + strength · F0 · max(1/E_rel − 1, 0)
```

which is exactly 1.0 at α = 0 and at strength = 0 — the regression mode — and
is immune to any constant scale error in the lobe. That reframing is what
unblocks the feature; the absolute normalization never needed to be solved.

#### What E_rel actually looks like

`python3 dev/fit_ms_ggx.py`. Two *separate* deviations show up:

| α | NoV=1.0 | 0.75 | 0.50 | 0.25 | 0.10 |
|---|---|---|---|---|---|
| 0.05 | 1.010 | 0.999 | 0.977 | 0.907 | 0.715 |
| 0.25 | 1.040 | 0.971 | 0.855 | 0.666 | 0.512 |
| 0.50 | 0.936 | 0.858 | 0.768 | 0.671 | 0.611 |
| 1.00 | 0.575 | 0.620 | 0.673 | 0.736 | 0.778 |

1. **Roughness-driven loss** (the NoV=1 column, 1.04 → 0.58). This is the
   multiple-scattering energy GGX drops, and it is what compensation is for.
   Note the game loses about **half** what a correct GGX does (0.58 vs 0.31 at
   α=1): its sum-form `Vis` over-brightens at high roughness and partly
   self-compensates. **Splicing a textbook Lazarov/Karis fit here would roughly
   double-compensate** — §2's original instinct to integrate the game's own
   lobe was right, and it matters quantitatively.
2. **Grazing loss at low α** (0.72 at NoV=0.1, α=0.05, where a correct GGX
   holds 0.91). This is a different defect: the engine's `Vis` denominator is
   the **sum** of the two Smith-Schlick G1 denominators where a correct
   separable Smith uses their **product**, and the substitution is worst at
   grazing. Compensating it would re-light every grazing surface in the game.
   **Deliberately excluded** — the shipped fit is α-only.

#### The fit (ready to author)

α-only, evaluated at NoV = 1, every term carrying a factor of α so the result
is identically 0 at α = 0 by construction rather than by fit accuracy:

```
a    = roughness * roughness
loss = j0*a + j1*a^2 + j2*a^3 + j3*a^4
comp = 1 + strength * F0 * max(loss, 0)

j0 = -0.35581642
j1 =  0.66852058
j2 =  0.82793009
j3 = -0.40552339
```

max abs err **0.0064**, rms 0.0024 over α ∈ [0,1]. At α=1 the shortfall is
0.738 → **+66% specular on an F0=0.9 metal, +3% on an F0=0.04 dielectric**.
`max(loss, 0)` clamps the small negative dip near α=0.25 so compensation never
darkens below vanilla.

#### Authored 2026-08-28 — `dev/patch_ms_ggx.py`

Built 2026-08-28, validated offline, and **launched the same evening —
confirmed on screen** by a single-variable A/B (one launch with `m` on
against four with it off; `handoff/28-MS-GGX-ENERGY.md` §6). What exists:

| | |
|---|---|
| patcher | `dev/patch_ms_ggx.py` (`--strength`, `--arms`, `--report`) |
| build | `dev/build_ptq.sh` — `m` joins the tier-1 matrix, now 15 combos |
| install | `dev/install_ptq.sh` (unchanged mechanism, wider `COMBOS`) |
| gate | `sync_settings.sh` — `ptmsggx`, combo letter `m` (order `r,c,b,m`) |
| toggle | CET → Callisto SSS → Path tracing → "Rough-metal energy compensation" |
| default | **on** — flipped after the on-screen confirmation; shipped initially off pending it |

`m` cannot be its own overlay: it splices the same twelve `rgs_reference_main`
permutations as T1.1/T1.2/T1.4, and the layer serves the first file it finds
per id. `build_ptq.sh` chains `patch_ms_ggx.py` over `patch_pt_quality.py`'s
output inside each combo, so the two edits compose in one module.

**Coverage: 10 of 12 permutations.** `40c6faab52a13874` and `ab7f1822eeb0331b`
carry six Fresnel sites each that assemble a **monochrome** specular —
`p * Vis * D`, no `1-p` lerp, no F0 anywhere in the lobe. `comp` needs the
lobe's own F0; borrowing one of those modules' two unrelated `+0.04` triples
would be a positional guess of exactly the kind `GOTCHAS 10` is about. They are
skipped by name and the patcher reports `variant: scalar-specular`, so the gap
is loud rather than silent. Both **confirmed-live** permutations (`d622fb9e`,
`4270b745`) are the three-channel form and are patched.

`40c6faab` is also one of the two skinray permutations, so under
`ptmsggx=on skinray=on` it is absent from `swaps.ptq/` and the layer falls
through to `swaps/` — it keeps its skin BRDF patch and simply gets no energy
compensation. Nothing is un-patched.

Per module: 6 blocks (3 punctual + 3 area), 18 uses rewritten, `spirv-val`
clean. Cost is ~8 ALU shared per block plus 3 per channel.

**Answered by the launch (2026-08-28, `handoff/28-MS-GGX-ENERGY.md` §6):**

1. *Does it change a pixel?* **Yes** — rough metal under direct light visibly
   gains the predicted energy; smooth surfaces are untouched, as constructed.
2. *Is patching the area arm right?* The confirmed build patches **both**
   arms and read correct on screen. Not A/B'd arm-by-arm; `--arms punctual` /
   `--arms area` rebuild the halves if the split is ever wanted.
3. *Does the grazing exclusion read as inconsistent?* Nothing to see on
   screen; the exclusion stands.

#### Splice site (punctual arm)

Structural anchor: three consecutive `OpFMul` sharing second operand `%6817`
(`= Vis·D`), first operands the Schlick `F` outputs `%6814/%6815/%6816`,
results `%6818/%6819/%6820`. Per-channel because `F0` is per-channel. Roughness
`α = %5655` is already in scope.

**Open question before authoring:** whether to also patch the area arm
(`%9998` → `%7576/78/80`). Its `Vis` shares the same sum-form denominator, so
it loses energy the same way, but its inputs are illuminance factors rather
than cosines and the α-only fit does not depend on them — so the same
multiplier is very likely correct there too. Worth confirming rather than
assuming, given how this blocker arose.

---

<details>
<summary>Superseded blocker text (kept for the pattern)</summary>

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

</details>
