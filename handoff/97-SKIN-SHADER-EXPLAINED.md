# 97 — The skin shader, end to end, for someone who has never seen this repo

Written 2026-09-02. This is the **onboarding** document: how Cyberpunk's path
tracer works, how we got inside it, what maths we injected, where that maths
comes from, and why the game did not already do it.

It is deliberately *not* a status document. `CURRENT.md` is what is live today;
`19-STATUS.md` is the ledger of what is proven versus merely built; `GOTCHAS.md`
is the list of rules this project paid for. This document is the **explanation**
underneath all three. Where it states something we measured, it says so. Where
it states something we *inferred*, it says that too — that distinction is the
single most expensive lesson in this repo.

**On the name.** You may have heard this called the "biomechanical skin shader."
Nothing in it is biomechanical. It is a **biophysically-motivated skin BRDF**:
a surface reflectance model whose free parameters are pinned to measured optics
of real skin (per-channel diffusion mean free paths from Jensen's 2001
measurements) and whose lobe shapes come from a published production shader (the
Callisto Protocol character BRDF, SIGGRAPH 2023). Call it the *Callisto skin
BRDF* and everyone will know what you mean.

---

# Part I — How the picture gets made

## 1.1 A draw call, and why a path tracer barely has any

The mental model most people carry is: the CPU says *"draw these triangles with
this shader,"* the GPU rasterizes them, a pixel shader runs per pixel, colour
comes out. That is a **draw call**, and it is how the *raster* half of Cyberpunk
still works.

Path tracing does not work like that. In RT Overdrive the frame is roughly:

```
  1. RASTER PREPASS  -> the G-buffer      (draw calls, ~thousands)
  2. RT PASSES       -> samples           (vkCmdTraceRaysKHR, ~a dozen)
  3. COMPUTE RESOLVE -> radiance          (vkCmdDispatch, ~84 shaders)
  4. DENOISE + RR    -> a clean image
  5. UPSCALE (DLSS)  -> 720p becomes 1440p
  6. TONEMAP/GRADE   -> the pixels you see
```

Step 1 still rasterizes the world, but it does not shade it. It writes a
**G-buffer**: a handful of screen-sized textures holding, per pixel, the surface
albedo, a packed normal, roughness, metalness, and — the one that matters most
to us — a **material class byte**.

Steps 2–3 are the part worth internalizing, because getting them backwards cost
this project six sessions.

## 1.2 The two jobs of a BRDF, and why only one of them is visible

A BRDF (bidirectional reflectance distribution function) answers: *given light
arriving from direction L and an eye at direction V, what fraction bounces
toward the eye?* In a path tracer it is used in **two completely different
roles**:

**Role A — sampling.** The ray-generation shaders (`rgs_reference_main`,
`rgs_restirgi_*`, `rgs_shadow_main`) use the BRDF as a *probability
distribution*. "Where should I aim the next ray?" They pick directions where the
BRDF is large, because those matter most. Their output is not colour — it is
**samples**: hit points, reservoirs, visibility bits.

**Role B — evaluation.** Somewhere later, radiance is computed:

```
    L_out = BRDF(V, L) x light x visibility / pdf
```

That number becomes a pixel.

Here is the trap. Monte Carlo integration divides by `pdf` — the probability the
sampler assigned to the direction it chose — **specifically so that the choice
of sampling distribution cancels out of the converged image**. That is the whole
point of importance sampling: it changes *noise*, not *answer*.

So if you patch the BRDF in a raygen, you change the sampler. The estimator then
divides your change back out. **The image does not move.** It gets slightly more
or less noisy, and nothing else.

> This is `07-COMPUTE-RESOLVE.md` §"The unifying explanation," and it is the
> single most important fact in this repo. Six sessions of provably-installed,
> provably-dispatched, `spirv-val`-clean raygen patches produced *zero* visible
> change. It was never a bug. The renderer was correct; we were editing the half
> of the equation that is designed to cancel.

## 1.3 Where the pixel is actually decided

The visible shading lives in **84 whole-library `GLCompute` modules** — the
lighting *resolvers*. They carry the full material stack:

- `0.318309873` — float32 of `1/π`, the Lambert/diffuse normalisation.
- `0.107508637` — the direct/analytic-light diffuse constant. It is **exactly**
  `(1/π)·(1 − 1/1.51) = 0.10750863705545247`, i.e. Frostbite's energy
  renormalisation of Burley (Disney) diffuse, folded at compile time (§3.1).
  The repo has always called it "the Disney constant"; that names the *model*
  correctly and the *constant* wrongly.
- `gbuf.y >> 5` — the material-class gate.

They read the G-buffer, read the samples the RT passes produced, evaluate the
BRDF for real, and `OpImageWrite` the result. **That write is the pixel.**

The RT passes feed them. Nothing else in the frame decides colour.

A structural detail that matters later: `06-PT-IS-THE-CHS.md` shows that the two
"PT proper" raygens (`fd1d0f0c…`, `c6bce844…`) contain *zero* shading — no
`1/π`, no diffuse constant. They are thin tracers. There is exactly one
closest-hit shader with a BRDF in it (`55f6172c….chs_main`) and its pipelines
never appear in the traced set. Live PT does not shade in a hit shader here
either.

## 1.4 The two gate encodings (and why the effect first appeared only in sunlight)

The 84 resolvers do not all read the class the same way:

- **48 modules** compute `gbuf.y >> 5` themselves — these are the **sun / direct
  light** paths.
- **36 modules** read *the same texel at the same binding* (`registers[2]+4`)
  but only mask `& 31`, never shifting — these are the **local-light** paths.
  The class bits are in the fetched word; those shaders simply do not use them.

The first working build patched only the 48. The symptom on screen was
unmistakable and completely baffling at the time: **the effect appeared only on
sun-facing surfaces.** The fix is that the patcher emits *its own* `>> 5` after
those modules' existing fetch, inheriting the fetch's dominance. Coverage went
48 → 68 → (after the hair BRDF was removed and the patcher simplified) **77**.

A third idiom turned up later in `12-FRESH-HUNT.md`:

```
%217 = OpBitwiseAnd %uint %193 %uint_4294967264   ; (y & ~31)
%219 = OpIEqual     %bool  %217 %uint_128         ; == 4<<5  <=>  (y>>5)==4
```

Ten modules compare against a pre-shifted constant instead of shifting. Same
question, third spelling. This is why every detector in this repo is
**structural** — it looks for the *shape* of a computation, not for a byte
pattern or an ID.

## 1.5 What the resolver actually knows

This constrains everything that follows. At a splice site in a direct-light
resolver we have:

| available | notes |
|---|---|
| `NoL` | the light cosine, the site's own, identified by its `NClamp` shape |
| `NoV` | the view cosine, identified by its `NMin(NMax(dot,1e-5),1)` eps-clamp |
| `NoH`, `VoH` | at the GGX sites |
| albedo r/g/b | as `albedo·(1−metal)`, channel identity **proven** by walking back to the `OpCompositeExtract` component index, never assumed from operand order |
| roughness → `alpha` | every use rewritable, so eval and sampling stay consistent |
| material class | `>>5`: **1 = skin, 4 = hair, 8 = eyes** |
| material sub-enum | `& 31`, populated, readable — but measured too coarse to split skin (`57`) |

And what we do **not** have, each of which killed a proposed feature:

- **No tangent frame.** The hit payload is 16 bytes and fully accounted for
  (albedo+metallic, octahedral normal + roughness, two floats). The raygen
  contains zero cross products. A hair tangent had to be *estimated* from a
  screen-space structure tensor, and its confidence gate collapsed every hair
  lobe to identity — which is why the hair BRDF was eventually deleted.
- **No view vector in the GI resolvers.** Lambert does not need one, so none is
  computed. Proven structurally in `50` §3.1. This is why bounce-lit skin can
  carry a diffuse term but *cannot* carry the oil or the fuzz: both need `V`.
- **No usable thickness / back-depth.** The engine's back-depth target exists
  and runs, but in a bindless heap its index moved from 73203 to 503350 across
  two captures **29 seconds apart in the same session** (`GOTCHAS` 13). A baked
  constant there would have multiplied whatever resource landed in the slot.
  Existence is not addressability.
- **Resolution.** Lighting is computed at **1280×720**, tile-classified, then
  denoised, velocity-smeared and upscaled to 1440p. Nothing you do in a
  resolver can be sharper than that.

---

# Part II — How we got inside a shipping renderer with no source

## 2.1 The crack: Proton turns DXIL into SPIR-V

Cyberpunk is a Windows D3D12 game. Under Steam Play it runs through Proton, and
**vkd3d-proton translates every D3D12 shader to SPIR-V before the driver sees
it.** Crucially, `dxil-spirv` preserves the original DXIL identity in an
`OpString` inside the translated module:

```
    "<16-hex-library-hash>.<mangled-entry>.dxil"
```

So every shader in the game arrives at the Vulkan driver as (a) editable
SPIR-V and (b) *labelled*.

This is the entire reason the mod exists, and the entire reason it is
**Linux-only**. On native Windows the shaders stay DXIL and this door does not
exist.

## 2.2 The layer

`swap_layer.c` builds `VK_LAYER_CALLISTO_spvswap`, installed as an **implicit**
Vulkan layer under `$HOME` (the Steam Linux Runtime container cannot see repo
paths, so `VK_ADD_LAYER_PATH` does not reach the game). For every
`vkCreateShaderModule` it:

1. scans `pCode` for the embedded DXIL identity,
2. computes `sha256(pCode)` as a secondary key,
3. substitutes `swaps/<libhash>.<entry>.spv` if that file exists,
4. logs one JSONL line per module — hit or miss.

That log is how we discovered the live game's shader inventory in the first
place. It also carries the dispatch hooks: `vkCreateRayTracingPipelinesKHR`
logs which raygen each RT pipeline is built from, and `vkCmdTraceRays*KHR` logs
which raygen actually traces.

**Gotcha that bit early:** the 16-hex hash is a DXIL *library* hash and is **not
unique** — `d622fb9e1dcb8cd0` covers both `rgs_reference_main` and
`ms_empty_main`. Identity must always be `libhash.entry`.

Overlays layer on top: `swaps.skin/`, `swaps.shadowcull/`, `swaps.ptq/` etc. are
checked before the base `swaps/`, **first file wins**. That is a feature (a
whole skin build is one directory you can swap atomically) and a trap (a stale
overlay silently shadows a new one, which is why the retired `hair` name was
*removed* from the layer's overlay list rather than kept alongside `skin`).

## 2.3 Patching: text on disassembly, structural anchors, never IDs

`CALLISTO_DUMP_DIR` dumps every incoming module. Those get `spirv-dis`'d into
`dev/disasm/`. The patchers (`dev/patch_compute_skin.py`, `patch_gi_c1.py`, …)
are **text-level**: they read the disassembly, locate anchors *structurally*,
splice in new instructions, reassemble with `spirv-as`, and validate with
`spirv-val`.

Nothing is decompiled. Nothing is recompiled from HLSL. There is no source.

"Structurally" means, concretely, things like:

- The diffuse eval site is *"a run of three consecutive `OpFMul` against the
  `1/π` constant, whose multiplicands resolve to one `v4` albedo fetch with
  components {0,1,2} distinct."*
- `NoV` is *"the value with an `NMin(NMax(dot, 1e-5), 1)` clamp signature."*
- The skin gate is *"an `OpIEqual` against 1 of a right-shift-by-5 of a
  component of the material fetch"* — or its `& ~31 == 128` spelling, or its
  phi-lifted variant.

This is what lets one patcher handle 77 modules and 12 shader permutations it
has never individually inspected, and it is what makes the mod survive shader
permutations that differ only in constant-folded settings.

## 2.4 The hunt: finding out that class 1 is skin

We knew there was a material class byte. We did not know what the values meant.
The technique (`07`, `12`) is brutally simple and works:

1. Build a patcher tier that, gated on `class == N`, **multiplies the module's
   output write by a loud colour** — a different hue per class.
2. Install, clear the shader caches, launch, look at the screen.
3. Read the answer off a face.

Skin came out red. Hair came out **yellow** → hair is class 4. Later probes
extended this to the sub-enum (`40`, `57`), to which raygen family writes
bounce-lit skin (`50`: the ReSTIR-GI *diffuse spatiotemporal* pair, found by
painting each family a different hue and measuring `ln(G/R)` on the face against
in-frame controls), and most recently to a metalness/roughness bucket palette
that turned out to be a general **material classifier** with a car-paint bucket
in it (`94`).

The class palette is the highest-information-per-launch tool in the repo.

## 2.5 The things that look like proof and are not

`GOTCHAS.md` opens with these because each of them cost a session:

- **A swap HIT is not execution.** `{"swap":"HIT"}` means the module was
  *created* and substituted. Proof of execution is a `dispatch` line with
  `swapped:1`. 70 modules were "confirmed loaded" for weeks while 54 of them
  never ran.
- **A byte diff is not coverage.** A module can be "patched" with zero sites.
  Builds now assert site counts from the patcher's own JSON reports.
- **A switch position is a request, not evidence.** The CET selector says what
  you *asked* for. What was *served* is proven by `cmp` against the bytes in
  the served directory and by the launch journal's content hashes. This has
  bitten the project three separate times — most recently on 2026-09-01, where
  a whole evening's impression of the GI chain turned out to have been formed
  on a launch that served `skinspec=off`.
- **Select by dispatch, never by constants.** Picking modules because they
  contain a plausible constant has produced a wrong family every single time.

## 2.6 The verification discipline

Every skin build carries, before it is allowed near a screen:

| check | what it proves |
|---|---|
| `spirv-val` on every module | the SPIR-V is legal |
| **identity build is byte-identical** | at `ρ=1` / `k=0` the patcher emits *nothing*; a knob at identity cannot have moved the standing rung |
| closed-form machine evaluation | the emitted `.spvasm` chain is re-parsed and *executed* in Python at N angles, against the algebra it is supposed to implement, with the gate both true and false |
| coverage asserted from reports | site counts, `skipped_dom`, `skipped_shape`, `skipped_dup` — never inferred from a byte diff |
| ladder difference assertions | each rung must differ from `off` *and* from the rung below it; two identical rungs under different names would let the selector appear to work while comparing nothing |
| `cmp` of the served directory | the game runs *copies*; what is on disk in the repo is not what ran |

That list is why this project's claims are trustworthy where they are, and it is
also why so many of its documents say **"built, validated, parked, never on
screen"** — which is a real state, and the ledger keeps it separate from
"works."

---

# Part III — The maths, where it comes from, and why it reads as skin

## 3.1 What vanilla does

Two diffuse models in one frame, both measured:

- **Path-traced bounces: plain Lambert.** `albedo/π`, cosine-sampled,
  `pdf = NoL/π`, proven by exact `throughput *= albedo` cancellation. For
  **all** materials. No skin lobe. No hair lobe.
- **Direct / analytic lights: Burley (Disney) diffuse, energy-renormalised the
  Frostbite way**, anchored on `0.107508637`:

```
    FD90 = 0.5 + 2·roughness·VoH²
    fd   = (1/π)·lerp(1, 1/1.51, roughness) · FD(NoL) · FD(NoV)
         = (1/π − 0.107508637·roughness) · FD(NoL) · FD(NoV)      <- folded
```

  The folded constant is `(1/π)(1 − 1/1.51)` to every printed digit, which
  identifies it: Lagarde & de Rousiers, *Moving Frostbite to PBR* (2014) §4.4 —
  the fix for Burley diffuse reflecting up to ~21% too much at high roughness.
  Worth knowing, because it means the direct path already carries a *retro*
  term: the mod's `c1` composes on top of one, it does not introduce the first.

Specular is a **single isotropic GGX lobe**, `F0 = 0.04`, roughness straight
from the character's authored roughness maps.

That is the entire skin model in the path tracer. This is why faces read dry,
matte and slightly gravelly, especially front-lit: real skin is not Lambertian
and its most recognisable cues are exactly the ones a Lambert term cannot
produce.

**Important caveat, stated up front:** the game *does* have a skin model — the
screen-space subsurface-scattering blur, which still runs in PT mode. See §3.8.
What it lacks is a skin **BRDF**.

## 3.2 The Callisto `c1` term — the founding idea

**Source:** Jorge Jimenez, Glauco Longhi, Miguel Petersen et al., *"The
Character Rendering Art of 'The Callisto Protocol'"*, SIGGRAPH 2023 *Advances in
Real-Time Rendering in Games*.

Callisto's character BRDF wraps its diffuse term in a multiplier built from two
angular lobes:

```
    r(x)  = 2(1 − x)                     a "sharpness" reparameterisation
    α_f   = (1 − NoL)^(5·r(n_f)) · NoV^(5·r(m_f))    "the FRESNEL lobe" )  names
    α_r   = (1 − NoV)^(5·r(n_r)) · NoL^(5·r(m_r))    "the RETRO lobe"   )  as the
                                                                       )  repo
                                                                       )  spells
                                                                       )  them
    c1    = lerp(1, ρ_f, α_f) · lerp(1, ρ_r, α_r)
          = (1 + (ρ_f − 1)·α_f) · (1 + (ρ_r − 1)·α_r)
    diffuse' = diffuse · c1
```

**Read the shapes off the algebra before trusting any name.** The two lobes are
exact `L ↔ V` transposes of each other, and each peaks at *one grazing cosine
and one head-on cosine*:

| lobe | peaks when | i.e. on a face | knob |
|---|---|---|---|
| `α_f` | `NoL → 0`, `NoV → 1` | the surface you look straight at, lit from the side — **the terminator** | `ρ_f` |
| `α_r` | `NoV → 0`, `NoL → 1` | the silhouette of a face lit from the front — **the rim** | `ρ_r` |

Neither peaks at `L ≈ V`, so **neither is retroreflection in the literal
"light back toward the source" sense**, whatever they are called. What they are
is the two halves of a *rough-dielectric* diffuse response, split so each can be
tuned separately:

**`α_f` — the grazing-light half.** Skin is a rough dielectric over a scattering
medium, not an opaque diffuser. Light arriving near-tangentially takes a long,
shallow path through the surface layer, and a rough boundary scatters much of it
back out toward a head-on viewer. Lambert's flat cosine has none of this, which
is why vanilla skin dies abruptly into its terminator. Raising `ρ_f` gives soft,
fleshy falloff instead.

**`α_r` — the grazing-view half.** Look *along* a surface and your line of sight
passes through much more of the scattering layer per unit projected area, so a
front-lit face brightens toward its own silhouette. This is the "subtle
front-lit glow that makes skin look alive" the shipped README describes, and it
is the half that survives in the current build (§3.5).

> **Naming warning, because the repo is inconsistent.** `patch_skin_brdf.py` and
> the shipped README call `ρ_f` "diffuse Fresnel" and `ρ_r` "retroreflection";
> `78` §0 calls `ρ_f` *"a retroreflection term"*. `78` is loose there — its point
> was only that `ρ_f` brightens grazing light, which the table above confirms.
> **Go by the cosines, not the label.** The always-safe sentence: `ρ_f` is the
> grazing-**light** lobe, `ρ_r` is the grazing-**view** lobe.

**Defaults as originally shipped:** `ρ_f = 1.35`, `ρ_r = 1.25`,
`n = m = 0.75` → exponent `5·r(0.75) = 2.5`.

**The identity property, which is the built-in regression test:** at
`ρ_f = ρ_r = 1`, `c1 ≡ 1.0` exactly. The `--vanilla` build is therefore
*bit-identical* to the game's own module. Every refactor since has been gated on
that.

### How it is emitted

`pow` is not a SPIR-V instruction, so each lobe becomes `Exp2(Log2(x)·e)` with
`NMax(x, ε)` guards (a `Log2(0)` would be `-inf` and the product `NaN`). ~28
instructions per site, all in one basic block, then:

```
    %g  = OpSelect %float <skin_gate> %c1 %float_1
```

— the whole factor collapses to a literal `1.0` on every non-skin pixel, so
non-skin renders bit-identically to vanilla. Then **one**
`replace_all_uses(scalar → scalar·g)` on the site's shared Disney scalar, which
reaches all three colour channels through the site's own fan-out multiplies.

Coverage in the shipping build: **173 `c1` sites across 77 modules.**

## 3.3 Bounce-lit skin (`gi-50`)

For a long time the skin BRDF was **direct-light only** — indoors, in shade, on
any face lit mostly by bounce, none of it was there. `42-BOUNCE-LIGHT-GATE.md`
found the class gate reaching **0 of the 218 splice lines in `99bb7c26…`** — the
GI resolver it was measured on — because the patcher had anchored on a `y >> 5`
that dominates nothing, while the value the shader itself uses arrives through
an `OpPhi` (218/218). One module, measured; the fix is a fixpoint walk that
finds the phi-lifted class.

The fix took one probe launch (`50`). Each raygen family was painted a different
hue, class-1-gated; a face in the Afterlife bar (bounce-dominated) moved
**red** by −0.32…−0.35 in `ln(G/R)` against three in-frame controls, with every
face sub-region agreeing and the shift scaling with how bounce-dominated the
region was. That names the **ReSTIR-GI diffuse spatiotemporal pair** as the
bounce-lit skin writer.

The splice there is the **NoL half only**:

```
    c1_l = (1 + (ρ_f−1)(1−NoL)^2.5) · (1 + (ρ_r−1)·NoL^2.5)
```

because — proven structurally, not assumed — **those shaders compute no view
vector at all.** Lambert does not need one. The `strength` knob scales both
rhos toward 1 (`gi-50` = 1.175 / 1.125), because mixed-light skin already gets
the full compute `c1` on its direct term.

The A/B result was the first unambiguous eye-preference win of the project:
*"I like these pics better… they're sharper and they have a bit more…
correctness to them? It feels like there's more complexity in the shading of the
face."* And the numbers corroborate on the one scene whose lighting was
stationary across the pair: +1.2–1.8% face luminance, achromatic, and
**structured** — forehead at the noise floor, jaw and chin +1.8…+4.4%, i.e.
largest exactly where the GI-diffuse share is highest. That gradient *is* the
mechanism, and it is literally what the user perceived.

## 3.4 The terminator colour bleed

**Source of the physics:** Jensen et al. 2001, *"A Practical Model for
Subsurface Light Transport"* — the `skin1` measured parameter set. Per-channel
diffusion mean free paths via `σ_tr = √(3σ_a σ_t′)` give

```
    d_R : d_G : d_B  =  2.68 : 1 : 0.50
```

Red light travels roughly 2.7× further through skin than green; blue barely
travels at all. So at the **terminator** — the band where direct light dies —
the last light to survive is red. Real skin warms into its own shadow. This is
the cue "pre-integrated skin shading" reproduces with a lookup table; we
reproduce it directly:

```
    w   = saturate(1 − NoL/0.35)²        the band, NoL ∈ [0, 0.35)
    m_R = 1 + k·0.336·w
    m_G = 1
    m_B = 1 − k·0.101·w
```

The amplitudes are the *differences* against green,
`(d_R−d_G) : (d_G−d_B) = 1.68 : 0.504 = 0.336 : 0.101` at the chosen scale. One
knob (`bleed_k`) scales both; the ratio is baked, because it is physics.

Three deliberate design constraints, each of which is a lesson elsewhere in the
repo:

- **Multiplicative only.** Where the diffuse term is zero — unlit, shadowed,
  backfacing — the product is zero. No added light, so the 720p lighting tile
  grid cannot appear. By construction, not by tuning.
- **Channel identity is proven, never assumed.** `find_bleed_targets` walks each
  fan-out multiply back through every albedo decode idiom found in the dump —
  the sRGB squaring decode, literal-scaled FMul/FAdd, a material-guard `OpPhi`,
  a white-override `OpSelect`, a uint `ConvertUToF` — and **fails the site**
  unless all three land on distinct components {0,1,2} of one `v4` fetch.
  Census: 150 of 173 sites eligible, 0 walk failures on the shipped set.
- **The 0.35 band width is a stylization constant and the doc says so out
  loud.** Physically the band scales with `curvature × d`. Curvature from raw
  720p reverse-Z depth taps cannot be calibrated without projection constants
  that no detector can name across 77 permutations, and an uncalibrated
  curvature knob is exactly the proxy trap that killed the Tier-4 translucency
  work. Consequence to expect: the bleed is as wide on a cheek as on a nose
  wing, when physically the cheek's should be narrower.

## 3.5 The luminance fix, and why "deep" won

The user's own diagnosis, and it was correct:

> *"Make the bleed luminance-neutral. Right now `m_R = 1 + 0.336·w` adds energy
> at the terminator. Renormalizing to hold luminance gives you the rosy 'alive'
> quality without lifting the very band you want deep."*

Measured (`78`, `dev/band_model.py`): with `m_G = 1`, the triple is a net
Rec.709 **add** of +6.4%·k·w on grey and **+10.4% on a rosy skin colour**,
peaking precisely at the band floor. Normalised at the lit cheek, the whole
shipped stack was holding the terminator **1.247× above vanilla** on the direct
path — brightening exactly the shadow the user wanted deep.

Two fixes, one variable each:

**`-lumn` (bleed_norm=1):** scale the *whole* triple by the pixel's own
luminance ratio

```
    s = Y / (Y + β·w·k·(0.2126·0.336·C_R − 0.0722·0.101·C_B)),  Y = Rec.709(C)
```

R:G:B ratios are untouched, so hue and saturation are **bit-for-bit** the
approved look; only the scale moves. Band 1.247 → 1.130. Verdict on screen:
*"Looks 10x better."*

**`-deep` (additionally `ρ_f → 1.0`):** the *other* half of the lift is `c1`'s
diffuse-Fresnel lobe, which by design brightens grazing light — and the
terminator is grazing light. Pulling `ρ_f` to identity takes the direct band to
**0.988** and the bounce band to **0.889**, i.e. at or below vanilla depth.
Verdict: *"Deepest band is actually the best skin shader right now over lumn."*

Say the consequence plainly, because "band 0.889" undersells it: with `ρ_f = 1`
the bounce-path factor is `c1 = 1 + 0.125·NoL^2.5`, which at the band is a **net
darkening of about 11% against vanilla** — the rung does not merely stop lifting
the terminator, it pushes it below where the game had it. That is what the user
picked, on screen, against the half-step. Worth knowing before anyone "restores"
`ρ_f` on the theory that identity must be wrong.

**Be honest about what this means.** The standing rung runs the Callisto `c1`
with its **diffuse-Fresnel half switched off**. What ships as "the Callisto skin
BRDF" today is the *retroreflection* lobe (`ρ_r = 1.25` direct, 1.125 bounce)
plus everything in §§3.4–3.7. The founding idea survives at half strength,
because the other half fought the look the user actually wanted. That is a real
result, arrived at by measurement, and it is the sort of thing a paper's
defaults cannot tell you.

## 3.6 The oil (Callisto "Tier 3")

Real skin has a thin, slightly wet, slightly oily top layer. Vanilla renders it
as one GGX lobe at `F0 = 0.04` with authored roughness ~0.40–0.60, which is
matte plastic.

Before building anything, the engine was checked (`GOTCHAS` rule 8). The exe
carries **eight** skin CVars — `cvSkin_SpecularTint_*`, `cvSkinFresnel`,
`cvSkinSpecular`, `cvSkinConstOffset`, `cvCharacterFresnel`, ambient mix — and
they were exposed as a live CET panel (`skin_engine.lua`) and pushed to
extremes on screen. **Result: no gloss, by construction.** The rim family is an
additive `N·V` edge glow with no azimuthal light response — it brightens
silhouettes and cannot gloss a front-facing surface — and the tint CVars only
recolour. No skin CVar scales `F0` or reshapes the lobe. That closed the engine
route and licensed the splice.

The splice, at every skin-gated specular Fresnel:

```
    r      = 2(1 − n_s)
    F'     = min( f0 + g·saturate(2−r)·(1−f0)·(1−VoH)^(5r), 1 )
    alpha' = min( alpha · alpha_scale, alpha_max )
```

Identity at `n_s = 0.5, g = 1, alpha_max ≥ 1` — and at identity the pass emits
*nothing*, because this `pow` is `Log2/Exp2` and would not be bit-equal to the
shader's own multiply chain.

Four things worth knowing:

- **`alpha_max` does nearly all the work.** `saturate(2−r)` clamps to 1 for
  every `n_s > 0.5`, so the Fresnel half only broadens the falloff. The
  roughness *ceiling* is the lever.
- **The `min(…, 1)` is not decoration.** Fresnel reflectance is physically ≤ 1;
  `g = 2` returns 1.96 at grazing, which reads as white fireflies on cheeks and
  nose, not as gloss. Since the house method is "exaggerate first," the
  unclamped form would have been found by pushing the knob and misread as the
  splice not working.
- **The detector rejects any Fresnel group whose `f0` is the constant 1.0.**
  That is the Disney diffuse `FD`, which computes the same pow5 shape. Without
  that guard the gloss would have been spliced onto the diffuse term too. It is
  the load-bearing line in the pass.
- **`alpha_scale` exists because a ceiling flattens variation.** Capping
  roughness makes every skin pixel the same roughness above the cap, which
  destroys the authored pore/oil variation. `alpha_scale` multiplies instead,
  *keeping* the variation.

**Half oil.** Full oil went on screen and the verdict was *"literally perfect…
except I need about half the amount of oil."* Halving is not a scalar here: a
ceiling cannot be halved uniformly. `n_s 0.60 → 0.55` (Fresnel exponent 4.0 →
4.5, grazing `F` at 60° from +52% to +22% over vanilla) and
`alpha_max 0.16 → 0.2025` (cap 0.40 → 0.45, so it bites authored roughness
> 0.538 instead of > 0.478) gives **half the reach and ~60% of the magnitude**,
and releases the mid-rough skin the full cap was flattening.

## 3.7 The peach fuzz (vellus hair)

**Source:** Estevez & Kulla's *Charlie* sheen distribution (Sony Imageworks) with
Neubelt–Pettineo's visibility term — the standard cloth/sheen pairing.

Faces are covered in vellus hair. At grazing angles it catches light in a way a
GGX lobe has no energy for at all. The first attempt was **multiplicative**:

```
    factor = 1 + k·min(D_charlie·V_neubelt, cap)
```

and it read as nothing. `dev/fuzz_model.py` measured it over the hemisphere:
median lift **0.56% of local diffuse**, and it only reaches 1.24× within ~2° of
the silhouette. The shipped docstring had claimed a "~30% boost on the rim" — it
was wrong by roughly 30×.

The structural reason no `k` fixes it, now `GOTCHAS`: **a multiplicative term
cannot create energy the base lobe does not have.** Peach fuzz *is* precisely
the grazing energy GGX has none of. Multiplying brightens the highlight (where
fuzz should be invisible) and does nothing at the rim (where it is the whole
feature).

Rebuilt as an **added lobe** at the site's own `D·Vis` product:

```
    D_charlie(a, NoH)  = (2 + 1/a)·(1 − NoH²)^(1/2a) / 2π
    V_neubelt(NoL,NoV) = 1 / (4·(NoL + NoV − NoL·NoV))

    fuzz  = min( D_charlie · V_neubelt, cap )          <- cap BEFORE k
    spec' = spec + select(class 1, k · fuzz · w · cos_site, 0)
    w     = 1 − β·(1 − VoH)^5                          <- the `defres` weight
```

`(2 + 1/a)/2π` is `D_charlie`'s own normalisation and is folded into the
build-time constant `pre` — do not write it twice, as the patcher's own
docstring does. The cap is applied to `D·V` *before* `k`, deliberately: the
modules that clamp their specular do it downstream of this point, and the ones
that do not would carry an unbounded `1/ε` into an fp16 store.

Why an *added* term here is safe, point by point — this is the tile-grid lesson
applied:

- Everything downstream of the splice applies to the fuzz too: Fresnel, light
  colour, shadow, and the module's own firefly clamp. **Unlit skin stays black
  because the light is zero**, not because the lobe is. That is the safety.
- The same fact is also the *cost*, and it is why `w` exists. In the sheen band
  the light and view vectors are nearly parallel, so `VoH ≈ 1` and the module's
  own Schlick Fresnel sits at its **floor** (`f0 ≈ 0.028`) across exactly the
  band the fuzz is for — a ~36× attenuation by a term that has nothing to do
  with vellus hair. `w = 1 − β(1−VoH)^5` cancels that ramp back out. Without it,
  `k` has to absorb a 36× and the honest magnitude looks absurd; with it, `k` of
  order 1 is the right scale at this splice point.
- `cos_site` is the light cosine the site itself folds into `D`, so the fuzz
  dies at exactly the terminator its base term dies at.
- `D_charlie` is an *inverted* lobe: exactly 0 at `NoH = 1`. The fuzz cannot
  brighten a highlight, by construction.

Reviewing the old code found four defects, one of them serious: `V_neubelt`
divides by `4(NoL + NoV − NoL·NoV)`, and a census of 457 sites found **16 with a
bare `OpDot`** cosine. A bare dot goes negative on backlit surfaces, the
denominator goes negative, the `NMax` floor catches it, and the lobe evaluates
at its **ceiling** exactly where the surface is backlit. Harmless in the
multiplicative form; in an added lobe it is a face turning into a lightbulb.
Fixed by proving saturation structurally (recursively through `OpPhi` operands —
all 104 phis pass) and emitting a real `NClamp` only for the 16 that cannot be
proven.

**Half fuzz.** The user's on-screen report was that indoor skin *"is becoming
hazy and loses that rosy tint."* `74` §0 traced that to **three** achromatic
mechanisms stacking, not one — and it is worth carrying all three, because two
of them were fixed by different levers:

1. **The oil's widened Fresnel** is a grey grazing film under every indoor
   practical (+52% `F` at 60° of view). Fixed by the half oil, §3.6.
2. **The fuzz is an achromatic add**, and `fuzz/diffuse` is **independent of
   light intensity** — `NoL` cancels and radiance multiplies both — so in a dim
   scene the same fractional add sits over a dimmer, rosier diffuse and
   desaturates it. The splice is upstream of the light multiply and *cannot know
   the light is dim*, so no shaping fixes this. Fixed by `k_peach` 1.0 → 0.5.
3. **The terminator bleed — the rosy depth itself — rode the direct term only**,
   and indoors the direct share collapses, so the cue washed out exactly where
   it was missed. Fixed structurally, by putting the bleed on the bounce path
   (`gi-50b`, §3.4), not by tuning.

Pre-registered at the time as a possible over-correction: if bright-light sheen
is now too quiet, the honest next lever is a **warm tint** on the fuzz (priced,
not built), not `k` back up — a warm fuzz stops desaturating the rosy diffuse at
any `k`.

## 3.8 The other realism axes

| knob | maths | why |
|---|---|---|
| `alpha_scale` | `alpha ×= s` | rougher/glossier while **keeping** the authored variation the cap flattens |
| `dcouple` | `diffuse ×= (1−s(1−NoL)^5)(1−s(1−NoV)^5)` | normalised Ashikhmin–Shirley diffuse/specular energy coupling: grazing skin darkens instead of glowing, because the energy went into the specular lobe |
| `micro_k` | `diffuse ×= sat(1 − (1−NoL)²·k·(1−lum(albedo)))` | albedo-driven micro-shadowing: dark, porous skin self-shadows at grazing light; a pale smooth patch does not |
| `eye_alpha_max` | class-**8** alpha ceiling | wet/glassy eyes — a different class, same mechanism |

All identity when absent, so every pre-existing rung rebuilds byte-exact.

## 3.9 The SSS kernel — a completely different mechanism

Everything above is a shader splice. The subsurface blur is **not shader code**.

Cyberpunk's `SSS_Blur` pass reads a **runtime-generated 32×8 float texture** — a
diffusion kernel LUT holding, per sub-kernel, per tap, a weight and an offset. A
RED4ext plugin (`main.cpp` → `CallistoSSS.dll`) hooks
`ID3D12GraphicsCommandList::CopyTextureRegion`, recognises the vanilla upload by
a 64-byte content fingerprint, and overwrites the staging bytes before the copy
records.

The shader computes `out = Σ(w·c) / Σ(w)`, so only weight **ratios** matter.
`dev/author_callisto_kernel.py` therefore reshapes weights and leaves the engine's
own tap offsets alone — or it does now:

> **The mod's own worst bug lived here.** `OFFSET_SCALE` shipped at **10.0** — a
> ten-times-wider subsurface blur than the engine authored. An SSS kernel is a
> spatial blur over diffuse lighting on skin, so at 10× radius every pore-scale
> and small-feature lighting variation on a face is averaged away before anyone
> sees it. *That* was the "faces read soft / it's all smoothed over" complaint,
> and it was this mod's own default. `33` found it; `detail` (vanilla radius, no
> centre softening, only the red-channel tail kept) is the default now and is the
> confirmed preset.

The `spectral` preset is built from the same Jensen `skin1` physics as the
terminator bleed — green byte-identical to vanilla, red widened and blue
tightened by the measured `d` ratios — and deliberately shares its chromatic
story with §3.4. **It is look-confirmed:** the user A/B'd `kernel=spectral` and
the terminator bleed by eye the same night and kept both (*"A/B tested myself and
these are the shit… skin shader looks great too"*). That was their own session
with settings unrecorded, so no radiometric claim rides on it — it is an eye
keep, which is the bar this project uses for look decisions. The other three
presets (`balanced`, `callisto`, `vanilla`) have never been on screen.

## 3.10 The shipped stack, decoded

The standing selection is named
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`. That name is a build recipe.
The skin half:

| token | what it is | § |
|---|---|---|
| `gi-50b` | Callisto `c1` on **bounce-lit** skin at strength 0.5, plus the terminator bleed on the bounce path | 3.3, 3.4 |
| `bleed` | terminator colour bleed on the direct path | 3.4 |
| `oil` | Tier-3 Fresnel reshape + roughness ceiling, **half** strength | 3.6 |
| `sheen` | the added Charlie/Neubelt fuzz lobe, **half** strength | 3.7 |
| `deep` | luminance-neutral bleed **and** `ρ_f → 1` — the deepest terminator | 3.5 |
| `clothhi`, `cone2all`, `fog` | *not skin* — cloth sheen, cavity cone shadowing, height fog | — |

Riding underneath, always on: `alpha_scale = 0.7`, `dcouple = 1.0`,
`micro_k = 1.0`, `eye_alpha_max = 0.0064`, and the `detail` SSS kernel.

Cost: a few dozen ALU instructions on class-1 pixels only, no new texture
fetches, no new rays, no loops, no new resources. Roughly 10+2 instructions per
bled site (~14% on top of the `c1` block).

---

# Part IV — Where any of this sits in path tracing

A physically complete skin model is a **BSSRDF** — light enters at one point and
leaves at another, and you have to integrate over the surface. Nobody does that
in a real-time path tracer. The production shortcut everyone uses instead is a
three-layer stack:

1. **A BRDF for the surface** — the specular lobe (thin oily layer) plus a
   diffuse term standing in for light that went in and came straight back out.
   *This is what §3.2, §3.6 and §3.7 modify.* It is where all the angular cues
   live: grazing brightness, retroreflection, sheen, wetness.
2. **A screen-space diffusion blur for the near-field transport** — the light
   that went in, bounced around a few millimetres of dermis, and came out
   somewhere nearby. *This is the SSS kernel of §3.8.* It is why skin does not
   look like painted plaster.
3. **A colour cue for what the blur cannot reach** — the terminator, where the
   angular falloff should be chromatic because the mean free path is chromatic.
   *This is §3.4*, and it is the "pre-integrated skin shading" trick done as
   maths instead of as a lookup table.

Cyberpunk ships **layer 2 only**. It has a real screen-space SSS pass, with a
real diffusion kernel, running even in RT Overdrive. It has no layer 1 and no
layer 3. That is precisely the gap this mod fills, and it explains the shape of
the result: the mod does not make skin *softer* (layer 2 already does that, and
we spent a session undoing our own 10× over-application of it) — it makes skin
*directionally* correct, which is what "alive" turns out to mean.

Path tracing changes one thing about this and it matters: the mod's terms have
to be **cheap, warp-coherent and unbiased**. `alpha` rewrites touch *every* use
of the roughness so evaluation and importance sampling agree and MIS stays
unbiased. Every term is gated to `OpSelect` a literal `1.0` on non-skin, so
divergence within a warp is one select, not a branch. Nothing adds a ray.

---

# Part V — Why the developers did not do this

Split into what the repo **measured** and what is honest **inference**.

### Measured

1. **The architecture is a single shared eval path.** The material `OpSwitch`
   cases in the resolvers are *only parameter-record loaders* — every material
   class merges into one common evaluation. There is one diffuse model and one
   GGX lobe for the whole world. Adding a per-class lobe means adding divergence
   to the hottest shader in the frame, on every platform, for one material.
2. **They did ship a skin solution — just not a BRDF.** The screen-space SSS
   blur is real, tuned, and runs in PT mode. From a shipping renderer's point of
   view skin was *solved*, in the pass where solving it was cheapest.
3. **They did reach for the grazing cue, and it cannot gloss skin.** Measured:
   the exe carries `Editor/Characters/RimEnhancement/Skin` with
   `FresnelCoefficient`, `SpecularCoefficient`, `ConstOffsetCoefficient`, plus
   `GlobalCharacterFresnel` (string-table audit, `27` §2) — and pushed to
   extremes on screen, **none of it produces a glossy top layer on a face**
   (`27` §4). No skin CVar scales `F0` or reshapes the lobe. The *intent* is in
   the binary; the capability is not.
   *Inferred* from the CVar names, not measured: that the rim family is an
   additive `N·V` edge glow with no azimuthal light response (`22` §3). Note the
   counter-observation — `11` §1 found the rim pass paints only **sunlit** rims,
   i.e. it is direct-light-driven and does respond to the light somehow. The
   safe claim is the measured one: it brightens silhouettes and cannot gloss a
   front-facing surface.
4. **Everything downstream destroys the detail anyway.** Lighting is computed at
   **1280×720**, tile-classified (a measured 40×23 `R32_UINT` list, i.e. 32×32
   tiles), denoised, velocity-smeared, and upscaled to 1440p. Investment in
   per-pixel skin subtlety inside a resolver is partially thrown away three
   passes later. That is a rational reason not to spend there.
### Public fact, not a repo measurement

5. **PT is a mode, not the renderer.** RT Overdrive is an option layered onto a
   deferred renderer that has to ship on consoles without it. Anything skin-
   specific in the PT path is a feature exactly one hardware tier can see, and
   it has to be authored, QA'd and maintained alongside a raster path that
   already looks correct.

### Inference (labelled as such)

6. **Scale.** Callisto Protocol is a corridor horror game with a handful of
   characters on screen and a hero close-up budget. Cyberpunk is an open world
   with crowds. Per-character shading cost is not comparable, and neither is the
   authoring cost of a second BRDF that every character asset must be validated
   against.
7. **Timing.** The Callisto talk is SIGGRAPH 2023; RT Overdrive shipped in April
   2023. The specific published formulation postdates the work.
8. **They would never do it this way.** The injection vector is *"Proton
   translates DXIL to SPIR-V and preserves the identity string."* That door only
   exists for Linux users running a Windows game through a translation layer. A
   first-party implementation would be a shader source change with all the
   platform, QA and console-parity obligations that implies.

**And the honest counterweight:** this mod gets to ignore everything a shipping
renderer cannot. It targets one game version, one API path, one OS, one GPU
vendor, one lighting mode, and one material class. It is allowed to look wrong
on a material it never tested — and it *has*, repeatedly. If CDPR shipped this
and it turned one NPC's face into a lightbulb in one interior, that is a patch.
Here it is a Tuesday.

---

# Part VI — How anything got decided

## 6.0 The loop, concretely

Everything in Part III was produced by repeating this. There is no hot reload;
a pipeline cache pins a shader module, so **the caches must be evicted or the
layer never even sees the module.**

```
  1. edit knobs            ./dev/patch_compute_skin.sh --sets            (rebuild
                           or --only <rung>                          + park sets)
  2. deploy                make install                       (repo -> live install)
  3. PROVE the deploy      cmp the live files against the repo — the game runs
                           COPIES; what is in the repo is not what will run
  4. select the rung       CET selector, or edit brdf_params.txt (CRLF! CET
                           rewrites this file at quit — edit line-ending-tolerantly)
  5. launch                sync_settings.sh materialises the named set into
                           swaps.skin/, evicts the shader caches on change, and
                           writes the launch journal
  6. PROVE the serve       ./dev/ab_launch_audit.py — before looking at a pixel:
                           status.txt `req == want`, the served dir's content hash
                           == the parked rung's, layer HIT counts, 0 refusals
  7. shoot the A/B         fixed framing, one variable, both halves in ONE session
                           if the scene's light is not stationary
  8. write it down         a numbered handoff doc; update 19-STATUS and CURRENT
```

Steps 3 and 6 are not ceremony. Skipping 6 is how an entire evening's impression
of the GI chain was formed on a launch that was serving `skinspec=off`.

## 6.1 The rules behind it

The method, because it is as much of the value here as the maths:

- **Sliders that cannot exist are not offered.** `n_s`, `alpha_max`, `ρ_f` are
  `OpConstant`s baked into patched SPIR-V. Nothing reads them at runtime. A CET
  slider bound to them would move a number in a text file and change nothing on
  screen — which is a real failure already on the books, six inert sliders that
  cost a whole A/B session. So strength is a **ladder of pre-built sets**
  selected at launch, and the tooltip says so.
- **One variable per observation.** Never land two independent visual features
  between two observations. Rungs are built in pairs from the same source in the
  same run, and the build **asserts** the pair has equal coverage and different
  bytes, so a selector can never appear to work while comparing nothing.
- **Diagnostic rungs are labelled as diagnostics.** `extreme`, `bleed-x` exist to
  answer *"is this reaching the screen at all"* unambiguously. They are expected
  to look like wet plastic. They are not look candidates.
- **Pre-register the failure.** Before a launch, write down what a negative
  result would look like. `-deep`'s pre-registered failure was *"reads flat/dead
  → `ρ_f` was doing look-work, keep `-lumn` and stop."* It did not fire, so the
  keep is a real keep and not a rationalisation.
- **Silent no-ops are made loud.** Every way `skinspec` can quietly do nothing —
  no set parked, overlay disabled, launch bypassed the settings script, unknown
  rung name coerced to `off` — surfaces as a warning line, a `status.txt` key,
  and an `[INERT: …]` tag in the switch label. From the chair every one of them
  looks identical to "the feature doesn't work."
- **The A/B is the only promotion.** *Built*, *loaded* and *swapped* are not
  *working*. Documents that say "built, validated, parked, never on screen" mean
  exactly that, and the ledger keeps them apart.

---

# Citations

**The BRDF**
- Jorge Jimenez & Miguel Petersen — *"The Rendering of The Callisto Protocol"*,
  SIGGRAPH 2023, *Advances in Real-Time Rendering in Games*.
  <https://advances.realtimerendering.com/s2023/> — the `c1` two-lobe diffuse
  modulation (§3.2), the Tier-3 specular Fresnel reshape and skin roughness
  clamp (§3.6), and the `c2` smooth-terminator idea the SSS kernel's
  `center_soften` knob approximates.
  > **Citation correction.** The shipped `README.md`, `docs/NEXUS_DESCRIPTION.txt`
  > and `02-PROJECT.md` cite this as *"The Character Rendering Art of 'The
  > Callisto Protocol'"* by "Jimenez, Longhi, Petersen et al.", SIGGRAPH 2023.
  > That conflates **two different talks**: the SIGGRAPH 2023 Advances talk above
  > (Jimenez & Petersen), and a separate **GDC 2023** session titled *"The
  > Character Rendering Art of 'The Callisto Protocol'"* (GDC Vault 1029339).
  > The maths here is the SIGGRAPH one. Fix the shipped credits before the next
  > release.

**The physics**
- Jensen, Marschner, Levoy & Hanrahan — *"A Practical Model for Subsurface Light
  Transport"*, SIGGRAPH 2001. The `skin1` measured parameter set; per-channel
  diffusion mean free paths `d_R:d_G:d_B = 2.68:1:0.50` drive both the
  terminator bleed amplitudes (§3.4) and the `spectral` SSS kernel (§3.8).
- Burley — the normalized diffusion / Christensen–Burley profile, used as the
  reparameterisation from `σ_tr` to a searchlight profile in the spectral kernel.
- Penner & Borshukov — *"Pre-Integrated Skin Shading"* (GPU Pro 2, 2011). The
  chromatic-terminator idea §3.4 implements. We do it as closed-form maths on
  `NoL` rather than as their curvature-indexed lookup table, because curvature
  is not recoverable here (§3.4's band-width note).
- Lagarde & de Rousiers — *"Moving Frostbite to PBR"* (SIGGRAPH 2014 course)
  §4.4. Identifies the game's own `0.107508637` as `(1/π)(1 − 1/1.51)`, the
  energy renormalisation of Burley diffuse (§3.1).

**The lobes**
- Estevez & Kulla (Sony Imageworks) — *"Production Friendly Microfacet Sheen
  BRDF"*, the *Charlie* distribution; with Neubelt & Pettineo's visibility term
  (*The Order: 1886*), the vellus-hair lobe of §3.7.
- Zeltner, Burley & Chiang — *"Practical Multiple-Scattering Sheen Using
  Linearly Transformed Cosines"* (SIGGRAPH 2022). **The better model, and
  deliberately not used:** its fit lives in a 3-parameter table, i.e. a texture,
  i.e. a descriptor we cannot inject. The analytic Charlie lobe needs no
  resource and has the same grazing-widening behaviour. Recorded so nobody reads
  "LTC sheen" in the handoff and goes hunting for a fit table in the module.
- Ashikhmin & Shirley — the diffuse/specular energy coupling form used by
  `dcouple` (§3.8).
- Burley/Disney — the retro-reflective diffuse model the game itself already
  uses on analytic lights (the `0.107508637` anchor).

**The mechanism**
- vkd3d-proton / dxil-spirv — the DXIL→SPIR-V translation that makes
  substitution possible and preserves module identity.
- SPIRV-Tools (`spirv-as` / `spirv-dis` / `spirv-val`) — patch authoring and
  validation.
- RED4ext.SDK (MIT) — the plugin SDK for the kernel-upload hook.

---

# Where to look in the repo

| you want | read |
|---|---|
| what is live **today** | `handoff/CURRENT.md` |
| what is proven vs merely built | `handoff/19-STATUS.md` |
| rules that cost us sessions | `handoff/GOTCHAS.md` |
| why the raygen was the wrong surface | `handoff/06`, `handoff/07` |
| the compute-resolve architecture | `handoff/00-ARCHITECTURE.md` §2–3 |
| the render graph from capture provenance | `handoff/15-RENDER-GRAPH.md` |
| skin specular / engine CVar audit / Tier-3 | `handoff/27-SKIN-SPECULAR.md` |
| bounce-lit skin | `handoff/42`, `handoff/50` |
| the terminator bleed and its energy fix | `handoff/53`, `handoff/78` |
| oil + fuzz, and the four defects found reviewing them | `handoff/72`, `handoff/74` |
| the SSS kernel and the 10× radius bug | `handoff/33`, `handoff/52` |
| the A/B protocol | `handoff/45-AB-PROTOCOL.md` |
| **the skin patcher** | `dev/patch_compute_skin.py` (`build_skin_c1`, `build_skin_spec`, `build_skin_alpha_cap`, `find_c1_sites`, `find_bleed_targets`) |
| the fuzz/sheen lobe itself | `dev/patch_subtype_probe.py` (`_emit_fuzz_lobe`, `_emit_defres`, `build_peach`, `build_sheen`) — it lives with the probe tiers, not with the skin patcher |
| the GI patcher | `dev/patch_gi_c1.py` |
| the rung ladder, in one place | `dev/patch_compute_skin.sh` (`LEVELS`) |
| the SSS kernel author | `dev/author_callisto_kernel.py` |
| offline models that reproduce every quoted number | `dev/fuzz_model.py`, `dev/band_model.py` |
| the layer | `swap_layer.c` |
