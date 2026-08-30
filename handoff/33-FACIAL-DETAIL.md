# 33 — Why faces read soft, and the two mod defaults that were causing it

Written 2026-08-29. Prompt: *faces read soft; I need them to look like real
people. I hoped more PT samples would give microshadows from pores. The
shading just isn't that detailed — the bounce lighting adds so much, but it's
very smoothed over. Should I crank DLSS sharpness?* Then: *make em look
rougher.*

**Verdict, one line: the softness was not a sample-count problem and was
largely self-inflicted — this mod shipped an SSS blur at TEN TIMES the
engine's own radius, and a "gloss" default that clamps every skin pixel to one
constant roughness. Both are fixed. What remains is the denoiser, now exposed
as a panel.**

The premise in the prompt is worth correcting first, because it is the reason
the obvious lever was the wrong one: **path samples cannot produce pore
microshadows.** Pores are not in the BVH — the face mesh has no pore geometry.
They exist only in the normal and roughness maps. More samples reduce Monte
Carlo *noise*; they cannot create occlusion from geometry that does not exist.
Everything that makes pores read is (a) the normal/roughness map surviving
into the shading, and (b) nothing averaging it away afterwards. Both of the
bugs below are in category (b).

---

## 1. Smoking gun 1 — the SSS kernel was blurring at 10× the engine's radius

`dev/author_callisto_kernel.py` carried, as a module constant:

```python
OFFSET_SCALE = 10.0   # scales nonzero tap offsets (blur radius)
```

An SSS diffusion kernel is a **spatial blur over the diffuse lighting on
skin**. The engine authored its tap offsets; this multiplied every one of them
by ten. Measured on the shipped `kernel.bin`, row 0, sub-kernel 0:

| tap | engine | shipped |
|---|---|---|
| 3 | 0.00001 | 0.00008 |
| 4 | 0.00003 | 0.00033 |
| 5 | 0.00007 | 0.00073 |

`CENTER_SOFTEN = 0.35` compounded it, moving 35% of the centre tap's weight
out into its neighbours — less of each pixel's own lighting, more of the
surrounding skin's. At that radius every pore-scale and small-feature lighting
variation on a face is averaged away before it is ever seen. That is the
"faces read soft / the shading just isn't detailed / it's all smoothed over"
complaint, and it was the mod's own default, running (`kernel=on`) on every
launch in `~/callisto_launches.log`.

`19`'s ledger has the SSS kernel as "ships, works — visually confirmed on
screen". That is not withdrawn: it *does* change the picture and it was seen
to. What was never checked is the direction, against the thing the user
actually wanted.

### Fixed: the kernel is now a preset, and the default is the sharp one

`--preset {detail,balanced,callisto,vanilla}`, built into `dev/kernels/`:

| preset | radius | centre soften | what it is |
|---|---|---|---|
| **`detail`** | **1.0 (engine's own)** | 0.00 | **the new default** — vanilla blur radius, red-channel tail kept, so skin still gets the warm bleed that reads as flesh without the smear that costs the texture |
| `balanced` | 2.0 | 0.15 | the Callisto character with some detail back |
| `callisto` | 10.0 | 0.35 | the original shipped shape, kept so the change is reversible and A/B-able, **not** because it is recommended |
| `vanilla` | 1.0 | 0.00 | identity — **byte-identical to the engine's own upload**, verified by `cmp`, so it is a true control |

Installed to the live plugin; the previous kernel is parked as
`kernel.bin.bak_callisto10x` in both the repo and the game folder. The kernel
is uploaded once at boot by the RED4ext plugin, so a preset change needs a
relaunch, not a reload; the CET "Callisto skin kernel" switch is the off
control.

## 2. Smoking gun 2 — the gloss default clamps the whole face to one roughness

Tier-3's `alpha_max` is a roughness **ceiling**: `alpha' = min(alpha,
alpha_max)`. Authored skin in this game sits at roughness 0.40–0.60, i.e.
alpha 0.16–0.36 (`27` §9.2 says so itself). Against the shipping rungs:

| rung | `alpha_max` | roughness cap | effect on alpha 0.16–0.36 |
|---|---|---|---|
| subtle | 0.1600 | 0.400 | clamps nearly everything |
| medium | 0.0900 | 0.300 | **clamps everything → one constant** |
| strong (was default) | 0.0450 | 0.212 | **clamps everything → one constant** |
| extreme | 0.0200 | 0.141 | **clamps everything → one constant** |

The user's last four launches were served `skinspec=medium`. `min(0.16…0.36,
0.09) = 0.09` for **every skin pixel on the screen**. All authored roughness
variation — pores, creases, the oily T-zone against matte cheeks — is gone
from the specular lobe, which is precisely where skin micro-detail reads.

`27` §9.2 identified the cap as "the whole story" for making skin look wet and
was right about that. What it did not say is that a ceiling low enough to be
visible is necessarily low enough to be *uniform*, and uniform is the opposite
of what a face needs.

### Fixed: default flipped to `off`, in both files that hold it

`init.lua` and `sync_settings.sh` both carried a `skinspec` default, and `26`
§5 / GOTCHAS ("one knob, two defaults, in two files that never see each
other") is the standing rule. Both are now `off`, in the same edit, and the
live `brdf_params.txt` was set to `off` as well (backed up as
`brdf_params.txt.bak_pre_rough`). The ladder is kept — it is opt-in now.

**The proper fix, not yet built:** replace the ceiling with a *scale*,
`alpha' = saturate(alpha · k)`, which moves the whole roughness distribution
without collapsing it. `k < 1` glosses while preserving variation; `k > 1` is
literally "make faces rougher". One knob, same site, same `replace_all_uses`
rewrite that `build_skin_alpha_cap` already does — and it must be the *same*
pass, not a second one, for the reason in `31` §4.1.

## 3. What is left: the denoiser, and it is now a panel

The remaining softness is downstream of the integrator, and the exe turns out
to expose the whole of it — none of it previously known to this project:

```
Editor/Denoising/NRD                      DenoisingRadius, MaxAccumulatedFrameNum,
                                          DisocclusionThreshold, HistoryReset
Editor/Denoising/ReBLUR{,/Direct,/Indirect,/AmbientOcclusion}
                                          DiffusePrepassBlurRadius, SpecularPrepassBlurRadius,
                                          HistoryFixStrength, StabilizationStrength,
                                          LobeAngleFraction, RoughnessFraction, AntiFirefly, …
Editor/Denoising/ReLAX/{Direct,Indirect}/{Common,Diffuse,Specular}
                                          AtrousIterationNum, PhiLuminance, PrepassBlurRadius,
                                          MinLuminanceWeight, VarianceBoost, …
Editor/SHARC                              DownscaleFactor, SceneScale, Bounces
DLSS                                      BackendPreset, OverrideSharpness, Sharpness
```

Two of these deserve naming individually:

- **The prepass blur radii** are an unconditional spatial average applied to
  radiance *before* any edge-aware filtering gets a say. They are the most
  direct "stop smearing my face" knob in the engine.
- **SHARC** is a world-space hash radiance cache. Indirect light is *read out
  of hash cells*, so the cell size is a hard ceiling on how much spatial
  detail bounce lighting can carry no matter how many rays are spent. "The
  bounce lighting adds so much, but it's very smoothed over" is a literal
  description of a radiance cache, and `DownscaleFactor`/`SceneScale` are its
  resolution.

Built: `detail_engine.lua`, 22 knobs, live, master off, vanilla snapshotted,
2 s re-assert, plus a **"Sharpest possible (diagnostic)"** button that zeroes
every blur radius and drops every a-trous iteration to 1 in one click — the
`extreme`-rung idea from the shader ladders, so "is the denoiser what is
softening faces?" gets a yes/no before anyone spends an evening on sliders.

**The caveat that decides whether half of it does anything:** in RT Overdrive
the game normally denoises with **DLSS Ray Reconstruction** (`DLSSD`), which
replaces NRD wholesale. If RR is on, every NRD knob is bypassed — not broken,
bypassed. The found-count proves the CVars *exist*; it cannot prove they are
in the frame. First A/B is therefore: RR off in the graphics menu, confirm the
knobs move the picture, then decide which denoiser to live with. RR generally
preserves more detail than ReBLUR at equal cost, so the honest outcome may be
"keep RR, and the win was upstream in §1 and §2".

Same deduplicated-key problem as `32` §2.1, with one new wrinkle:
`DiffusePrepassBlurRadius` genuinely exists in both ReBLUR/Direct and
ReBLUR/Indirect, so knobs that must address a specific group carry a single
explicit path and a unique `name`, while the value table is keyed on that name
rather than the CVar key. 16 stubbed checks, including one asserting the two
duplicates keep separate values and resolve to their own groups.

## 4. The sharpening question, answered

*Should I just crank DLSS sharpness?* No, not as the fix. Sharpening does not
restore detail a blur removed — it raises local contrast on whatever survived,
including the edges of the smooth patches. On skin that reads as crunch before
it reads as pores, and it sharpens the noise too. `OverrideSharpness` /
`Sharpness` are in the panel because it is the knob everyone reaches for and
it should at least be measurable, with that caveat in its own tooltip. Fix the
blur first; sharpen last, if at all.

*Is it that I can't go full resolution?* Partly, and it is real: PT runs at
1280×720 internally (`15` §1) and is reconstructed to 1440p, so there is a
genuine resolution floor under the lighting. **No PT internal-resolution CVar
exists** — searched: the only `ResolutionScale` in the exe belongs to
`Rendering/SpeedTree` (billboards). Moving DLSS from Balanced toward Quality
raises the *reconstruction* input and the user already observed it helping,
which is consistent. But §1 and §2 were throwing away detail *below* that
floor, which is why they were worth finding first.

## 5. What to do next, in order

1. **Relaunch and look at a face.** Two variables moved together — the kernel
   and `skinspec` — which normally violates "never land two independent visual
   features between two observations" (GOTCHAS). It is deliberate here: both
   are *removals* of a known smear, and the question is whether faces are
   sharper at all, not which one did it. Attribute afterwards if it matters —
   the CET switch and the kernel presets separate them cleanly.
2. **`detail_engine` → "Sharpest possible"**, with Ray Reconstruction off.
   Yes/no on whether the denoiser is the remaining softness.
3. **SHARC `DownscaleFactor` / `SceneScale` down**, for the bounce-light half
   specifically.
4. **Then** the roughness *scale* (§2) — the real "make em rougher" knob, and
   the one that can go past vanilla rather than only back to it.
5. Microshadowing (`saturate(NoL + 2·AO² − 1)`, the Naughty Dog trick) is the
   correct technique for "micro lighting contrast over small parts of the
   face" and needs no rays — but it needs an AO/cavity signal in the compute
   evaluators, and a first look found **no AO input** among
   `4d46848998312027`'s 7 fetches. Feasibility pass required before promising
   it.

## 6. Files

| file | change |
|---|---|
| `dev/author_callisto_kernel.py` | `PRESETS`, `--preset/--out/--offset-scale/--center-soften`; the 10× default documented and replaced |
| `dev/kernels/kernel.{detail,balanced,callisto,vanilla}.bin` | built, parked |
| `kernel.bin` + live plugin copy | now the `detail` preset; old one kept as `.bak_callisto10x` |
| `init.lua`, `sync_settings.sh` | `skinspec` default `strong`/`strong` → `off`/`off` |
| live `brdf_params.txt` | `skinspec=off` (backup `.bak_pre_rough`) |
| `detail_engine.lua` (new, × 3 copies) | the denoiser/SHARC/sharpness panel |
| `init.lua` (× 3 copies) | defensive require, register, `onUpdate` |
