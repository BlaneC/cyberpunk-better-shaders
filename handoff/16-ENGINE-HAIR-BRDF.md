# 16 — The engine already has the hair BRDF

Written 2026-08-27, from a read of Ultra Plus v9.2.2 (`~/Downloads/Cyberpunk
Ultra Plus v9.2.2 …`) prompted by the observation that installing it "enables
bounce lighting on hair".

**It does not add a hair shader. It flips engine CVars.** Cyberpunk exposes
CVars naming three hair lobes — `R`, `TT`, `TRT` — plus a multiple-scattering
term, per-light-category weights, per-lobe alpha shifts and a TRT exponent, all
live-tunable, and a `UseReferenceImplementation` switch.

**Scope of that claim, precisely.** What is *confirmed* is that these CVar names
exist in the shipping exe and that Ultra Plus's only hair action is writing
them. That the shader behind them is Marschner is an **inference from the
naming** — `R`/`TT`/`TRT` are the standard Marschner lobe names and an
alpha shift is the Marschner cuticle tilt — **not** something read out of
shader code. No shader implementing it has been identified. Treat "the engine
has a three-lobe hair model" as strongly indicated; treat "it is Marschner" as
a label, not a finding.

---

## 1. Verification (not taking Ultra Plus's word for it)

Every name below is present in the shipping executable
(`bin/x64/Cyberpunk2077.exe`, 59.9 MB, 2026-08-20):

```
$ strings -n 6 Cyberpunk2077.exe | grep -cx UseReferenceImplementation      1
$ strings -n 6 Cyberpunk2077.exe | grep -cx AAAA_HACK_hairModifiedLocal…    1
$ strings -n 6 Cyberpunk2077.exe | grep -cx TRT_Params                      1
$ strings -n 6 Cyberpunk2077.exe | grep -cx AlphaShifts                     1
```

The CVar-name block in the binary reads, contiguously:

```
UseReferenceImplementation   AdditionalAreaRoughness   AlbedoMultiplier
Editor/Characters/Hair       SpecularRandom_Min        ContactShadowClamp
UseLocalContactShadowsOnHair UseGlobalContactShadowsOnHair
DebugSwitch2  Editor/Characters/Hair/Debug  DebugSwitch1  SpecularRandom_Max
MultiScatter  Editor/Characters/Hair/LocalLight
              Editor/Characters/Hair/EnvProbe
              Editor/Characters/Hair/GlobalLight
ScatterDepth  Mask_Intensity  ShadowFactorExp  DiffuseScatterFactor
Editor/Characters/Hair/MultiScatter   Editor/Characters/Hair/TRT_Params
EXP_SCALE     Editor/Characters/Hair/AlphaShifts
              Editor/Characters/Hair/Specular
HACK_Factor1  Editor/Characters/Hair/HACKS  HACK_Factor0  EXP_BIAS
AAAA_HACK_hairModifiedLocalLightIntensity  HACK_Factor3  HACK_Factor2
```

Ultra Plus reaches them through CET's `GameOptions.SetFloat/SetBool`
(`lib/Cyberpunk.lua:133-148`), driven from `config/hair.ini` by
`Engine.ApplyHairAdjustments()` (`lib/Engine.lua:238`). Nothing else.

## 2. The full surface

| CVar | Ultra Plus `[Enabled]` (PT) | notes |
|---|---|---|
| `Hair/UseReferenceImplementation` | **true** | false in every non-PT preset |
| `Hair/AlbedoMultiplier` | 0.16 | vanilla 1.0 — the big one |
| `Hair/RoughnessFactor` | 3.0 | vanilla 1.0 |
| `Hair/AdditionalAreaRoughness` | 0.3 | |
| `Hair/SpecularRandom_Min` / `_Max` | −0.17 / 0.17 | per-strand jitter |
| `Hair/UseGlobalContactShadowsOnHair` | true | |
| `Hair/UseLocalContactShadowsOnHair` | *never set* | exists in exe |
| `Hair/ContactShadowClamp` | *never set* | exists in exe |
| `Hair/Specular/Wrap`, `/Mask_Intensity` | 1.0, 1.0 | |
| `Hair/MultiScatter/Wrap`, `/Mask_Intensity` | 0.3, 0.3 | |
| `Hair/MultiScatter/ShadowFactorExp` | 0.37 (debug.ini only) | |
| `Hair/MultiScatter/DiffuseScatterFactor` | 0.0 (only in `[Raster]`) | |
| `Hair/{LocalLight,EnvProbe,GlobalLight}/R` | 0.9 / 0.4 / 0.5 | primary highlight |
| `…/TT` | 0.005 (debug.ini only) | **third lobe — no PT preset sets it** |
| `…/TRT` | 0.8 / 0.4 / 0.84 | the coloured secondary glint |
| `…/MultiScatter` | 0.7 / 0.0 / 0.39 | |
| `…/ScatterDepth` | 1.0 / 0.5 / 5.0 | |
| `Hair/AlphaShifts/R`, `/TT`, `/TRT` | −0.083, 1.0 (debug.ini), −0.1 | lobe shift along the strand |
| `Hair/TRT_Params/EXP_SCALE`, `/EXP_BIAS` | 3.5, 0.825 | |
| `Hair/HACKS/AAAA_HACK_hairModifiedLocalLightIntensity` | false | true in every non-PT preset |
| `Hair/HACKS/HACK_Factor0..3` | 66, 95, 213, 450 (debug.ini) | undocumented |

**On "bounce lighting on hair" — do not read these as GI controls.** The
`; name = Hair GI (Global Light) …` / `Hair DI (Local Light) …` labels in the
table are **Ultra Plus's author's**, not the engine's. In CDPR naming "global
light" is normally the sun/moon directional, so `GlobalLight/ScatterDepth`
(which Ultra Plus's PT preset pushes 1.25 → **5.0**, its single largest change)
is most likely *sun* scatter-through-hair depth — a direct-light term, not a
bounce term.

These CVars weight how hair **responds** to three categories of incoming
light. They do not create bounce rays and are not evidence about whether path
-traced bounce rays strike hair. That is a separate question — see §6.

Ultra Plus's PT preset never sets `TT`, `ShadowFactorExp`,
`DiffuseScatterFactor`, `ContactShadowClamp`, `UseLocalContactShadowsOnHair`
or the `HACK_Factor`s — they sit in `config/debug.ini`, behind its Debug tab.

## 3. What this means for the SPIR-V hair track

Blunt version: **for tuning the hair look, the SPIR-V track was the hard way
round.** The engine exposes, as live CVars, essentially every parameter
`08-DUAL-LOBE.md` set out to splice — a shifted dual lobe (R + TRT, with the
alpha shifts), multiple scattering, per-light-path weights, roughness reshape —
and it applies them inside a shader that *does* have the strand tangent,
because it runs where the hair material does. That is precisely what `11` §2
established the deferred compute evaluators can never have.

What the SPIR-V track still uniquely offers:

- Anything the CVars do not expose (a *different* BRDF, not a retune).
- The hair **shadow-leak fix** (`00` §10) — a ray-flag change, unreachable
  from any CVar, and still the project's most solid visible win.
- The **skin** SSS kernel and BRDF, which are unaffected by any of this.

What it does **not** offer that was assumed: a route to better hair than the
engine's own reference implementation, at half resolution, without a tangent.

## 4. Implemented: the CallistoSSS engine-hair panel

`hair_engine.lua` (new) + `init.lua` (wired), deployed to
`release/game/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/` and to the
live game install. Adds a **"Hair BRDF (engine, applies live)"** subcategory to
the existing Callisto tab exposing all 40 CVars above, including the ones Ultra
Plus's PT preset leaves alone.

Design notes:

- **Applies live.** Unlike every other Callisto knob (which gates a SPIR-V swap
  and needs a relaunch plus a cache clear), these are engine settings: the
  slider moves and the frame changes. This is a far tighter loop than anything
  the project has had.
- **Default OFF.** The master switch must be turned on before anything is
  written, so installing this changes nothing until asked.
- **Vanilla is snapshotted, not hard-coded.** On init the panel reads the live
  value of every CVar *before* writing any, so "Restore engine defaults"
  restores what this install actually shipped rather than numbers copied out of
  someone's preset.
- **Re-asserts every 2 s** (`onUpdate`), because the engine resets these across
  loads and fast travel. While the master switch is on it will therefore
  override Ultra Plus's hair preset; turn one of the two off to hand back
  control. Ultra Plus is **not** currently installed in this game dir.
- Every `GameOptions` call is `pcall`'d, so a CVar renamed by a future game
  patch degrades to one dead knob rather than a broken tab.

## 5. Open questions (each needs one launch)

1. **Does `UseReferenceImplementation` change the dispatched module set?** If it
   selects a different shader permutation, the dispatch log will show new DXIL
   ids appear and others vanish — which would also mean Callisto's hair swaps
   target the *non*-reference path and silently stop applying when it is on.
   Test: toggle it, diff `~/callisto_swap.jsonl` dispatch ids across the two
   launches. **This is the one to run first** — it decides whether the two
   tracks can coexist at all.
2. Do Callisto's hair swaps and the engine BRDF double-apply (two specular
   models stacked)? Turn `Callisto hair BRDF` off while tuning the engine
   panel until this is known.
3. What do `HACK_Factor0..3` (66/95/213/450) and `Hair/Debug/DebugSwitch1..2`
   do? Undocumented, large, and suspiciously like screen-space or LOD
   thresholds.

## 6. Does the path tracer bounce off hair? (separate question)

Not the same question as §1–§4, and worth keeping apart.

**Confirmed:** hair geometry is in the acceleration structure. This project
proved it on screen — hair casts sharp shadows, and the shadow-leak fix
(`00` §10) worked by changing *ray* culling flags on hair cards. That is proof
for **shadow rays** specifically. Bounce rays are traced against the same TLAS,
so bounce rays hitting hair is near-certain, but the on-screen proof here
covers shadow rays.

**Newly established, offline, and it constrains where any hair BRDF can live:**
none of the 19 closest-hit permutations in `dev/disasm/chs/` contains a single
`Exp` or `Pow` instruction (max `OpDot` count is 10, in `chs_main_15`). **No
CHS evaluates a specular lobe at all.** That is exactly what
`07-COMPUTE-RESOLVE.md` concluded from the other direction: the RT passes
produce samples and the compute passes shade.

So whatever shader consumes the `R`/`TT`/`TRT` CVars is a **compute** shader —
one of the family A/B/C/D evaluators of `15-RENDER-GRAPH.md`, the same modules
this project already patches. The engine's hair model and Callisto's splice
target are the same code. That also sharpens §5 Q1: if
`UseReferenceImplementation` selects a different *compute* permutation, the
dispatch log will show it directly.

**Corrections to earlier readings in this session, recorded so they do not
propagate:**

- `PT_HairProfile` in the exe is **not** a path-tracing feature. `PT_` there is
  *ParameterType*: its enum neighbours are `PT_Scalar`, `PT_Vector`, `PT_Cube`,
  `PT_TextureArray`, `PT_SkinProfile`, `PT_FoliageProfile`. It is a material
  parameter type. Withdrawn.
- `EMM_SurfaceHairDirection` and `EMM_SurfaceHairID` **do** stand, and matter.
  `EMM_` is the engine's debug-view enum — neighbours are `EMM_Depth`,
  `EMM_VelocityBuffer`, `EMM_GBuffer0A`, `EMM_GBuffer1A`, `EMM_GBuffer1RGB`,
  `EMM_SurfaceNormalsWorldSpace`, `EMM_SurfaceMaterialID`. The engine ships a
  debug visualisation of **surface hair direction**, sitting among G-buffer
  channel views. That is a direct challenge to `11` §2's "No tangent. No UVs…
  and no free channel to put one in", which was read off five fetches in
  *three* modules. It does not prove the direction is stored in the G-buffer —
  it could be derived in the debug pass — but it is the strongest lead yet that
  a strand direction is available somewhere, and it is cheap to test: enable
  that debug view and look.
- `RMT_Hair` exists in `ERenderMaterialType` alongside `RMT_Standard`,
  `RMT_Subsurface`, `RMT_Eye`, `RMT_Cloth`, `RMT_Foliage`. Hair is a
  first-class render material type, consistent with the hunt's class 4.

## 7. The shader-side constant table, and which Callisto features it subsumes

The exe also carries the **shader constant names** the CVars bind to — 71
`cv*` identifiers. They do not survive into the SPIR-V (dxil-spirv strips
them; `dev/disasm/compute/*.spvasm` has 25 `OpName`s and none is a `cv*`), but
the exe list is a complete inventory of what the character shaders are
parameterised on:

- **Hair — 41 constants.** `cvHairR_{Local,Global,EnvProbe}`,
  `cvHairTT_*`, `cvHairTRT_*`, `cvHairScatter_{Local,Global,EnvProbe,Wrap,
  ShadowFactorExp,DiffuseScatterFactor}`, `cvHairScatterDepth_*`,
  `cvHairAlphaShift_{R,TT,TRT}`, `cvHair_TRT_EXP{SCALE,BIAS}`,
  `cvHairSpec_{Wrap,MaskIntensity}`, `cvHairAlbedoMultiplier`,
  `cvHairRoughnessFactor`, `cvHair_AdditionalAreaRoughness`,
  `cvHair_SpecRandom{Min,Max}`, `cvHair_use{Global,Local}ContactShadows`,
  `cvHair_contactShadowsClamp`, `cvHair_debugSwitch{1,2}`,
  `cvHACK_hairFactor0..3`, `cvHACK_hairModifiedLocalLightIntensity`,
  **`cvHair_useReferenceImpl`**.
- **Skin — 8.** `cvSkinFresnel`, `cvSkinSpecular`, `cvSkinConstOffset`,
  `cvSkin_SpecularTint_{R,G,B,Weight}`, `cvSkin_Allow AmbientMix`,
  `cvSkin_Ambient{Intensity,Mix}Factor`.
- **Rim families — 13.** `cvCharacterFresnel`, and
  `cv{Standard,Weapon,Foliage}{Fresnel,Specular,ConstOffset}`.
- **RT — 6.** `cvPathTracing`, `cvRayTracingEnableNRD`,
  `cvRayTracingEnableReferenceSER`, `cvLightBlockerInfluence`,
  `cvRoughnessFactor_{Bias,Scale}`.

### `useReferenceImpl` is an in-shader branch, not a permutation

`cvHair_useReferenceImpl` being a **shader constant** means
`UseReferenceImplementation` is read inside the hair shader and branched on at
runtime — it does not select a different compiled permutation. **That resolves
§5 Q1 offline**: toggling it will not change which DXIL modules dispatch, so
Callisto's swaps keep applying either way and the two tracks can coexist.
(A constant could in principle be paired with a permutation as well; the live
dispatch-log diff still settles it cheaply, but the prior is now strongly
against.)

### The "rim three" have a name

`cvCharacterFresnel` / `cvStandardFresnel` / `cvStandardSpecular` /
`cvStandardConstOffset` bind to `Editor/Characters/RimEnhancement/*` and
`…/RimEnhancement_RayTracing/*`, gated by
`Developer/FeatureToggles/CharacterRimEnhancement`. The three modules chased
through `11`, `12` and `13` are the **CharacterRimEnhancement** pass. That
explains their entire observed behaviour in one line: they paint only sunlit
rims because painting sunlit rims is what the feature does. `11` §1's
"scope: the sunlit rim only" was correct and could have been read off the CVar
surface in minutes.

### Which Callisto features are now redundant

| Callisto feature | Engine equivalent | Verdict |
|---|---|---|
| **Hair shadow-leak fix** (shadow-ray flags 28→12) | **None.** No backface/culling constant exists for shadow rays among the 71. The only hair-shadow CVars are *contact* shadows (`cvHair_use{Global,Local}ContactShadows`, `cvHair_contactShadowsClamp`) — screen-space ray-marched, a different mechanism entirely. | **Keep — genuinely unique** |
| **SSS diffusion kernel** (32×8 RGBA32F LUT) | **None.** No diffusion-profile constant. `SkinProfile`/`CSkinProfile`/`m_skinProfile` are asset class names, not settable. `cvSkin_*` are specular tint and ambient mix. | **Keep — genuinely unique** |
| Skin retroreflection (`rho_r`, `n_r`, `m_r`) | None found | Keep |
| Skin diffuse Fresnel (`rho_f`, `n_f`, `m_f`) | **Partial.** `cvSkinFresnel` + `cvCharacterFresnel` + `RimEnhancement_RayTracing/{RoughnessFactor_Bias,Scale,LightBlockerInfluence}` target the same look by different math (Callisto: Disney diffuse Fresnel; engine: additive rim specular). | **A/B before maintaining** |
| **Hair BRDF** (aniso + shifted dual lobe) | **Fully subsumed, and exceeded** — the engine has three lobes to Callisto's two, per-light-category weights, alpha shifts and scatter depth, applied where the tangent exists. Callisto's has never changed a pixel. | **Demote** |

So: two of the five are irreplaceable, one is worth an A/B, and the hair BRDF —
the feature that consumed most of the project's effort — is the one the engine
already does better.
