# 22 — Cloth / fabric BRDF: feasibility

Written 2026-08-28. Investigation only — nothing was built or patched. Three
audits, all offline: (1) a material-class census over **all 3153** dumped
SPIR-V modules, disassembled in full rather than sampled; (2) a `strings -n 5`
CVar/enum audit of the shipping exe, mirroring `16`'s method; (3) a read of
the standard shading path out of the tile evaluators that `10` proved actually
execute.

**Verdict, one line: there is no cloth BRDF in this renderer to improve.
Clothing is shaded by the same standard path as a plastic crate —
renormalised Burley diffuse plus one isotropic height-correlated GGX lobe with
`F0 = lerp(0.04, albedo, metallic)` — and the renderer special-cases exactly
two materials, skin and hair. So this is the *glass* situation (`20`), not the
*hair* situation (`16`): nothing to tune, everything to author.**

The good news, and it is real: a sheen lobe is by a wide margin the **cheapest
BRDF addition this project has ever scoped.** It needs no tangent, no new
G-buffer channel, and no class gate to be *visible* — every input it wants
(`NoH`, `NoV`, `NoL`, roughness) is already computed at every splice site.
The entire risk is the one this project has never beaten: whether a BRDF
splice into the compute evaluators changes a pixel at all (`10`, `19`).

That inverts the usual order. **A cloth sheen is the best available test of
the compute-splice mechanism itself**, better than any hair probe, because it
removes both confounds hair carried — the estimated tangent and the class
gate. If it paints, the mechanism works and the hair verdict in `19` deserves
re-opening. If it does not, the compute-BRDF track is finally, cleanly dead.

---

## 1. What actually shades clothing today (proven from the binaries)

Read out of `42f0d5e99cfc5929` (a 6348-line resolver, `:1190-1230`); the same
shape appears in every executing evaluator listed in §2.

**Diffuse — renormalised Burley (Frostbite/Filament form), not plain Lambert:**

```
FD(x)  = 1 + pow5(1-x) * (F90 - 1)
f_d    = (1/π - rough * 0.107508637) * FD(NoL) * FD(NoV)
```

`0.107508637` is not a mystery constant: it is `(1 - 1/1.51)/π`, the
Frostbite energy renormalisation folded into `1/π`. The user's read of
"maybe still some lamberty stuff" is close to right — it is Lambert with a
Burley retroreflective rim, and nothing else.

**Specular — one isotropic GGX lobe, height-correlated Smith:**

```
a2  = rough^4                                            (:1207-1208)
D   = a2 / (π * (NoH²(a2-1) + 1)²)                       (:1209-1216)
V   = 0.5 / (NoV*sqrt(NoL²(1-a2)+a2) + NoL*sqrt(NoV²(1-a2)+a2))
                                                         (:1217-1230)
F   = Schlick, F0 = lerp(0.04, albedo, metallic)         (15 sites)
```

That is a textbook dielectric microfacet BRDF. **One lobe. No sheen, no fuzz,
no second specular, no anisotropy, no transmission.** A satin jacket, a
painted wall and a plastic crate get identical math; the only thing that
separates them is the roughness and normal maps.

**This is exactly why clothing reads "plasticy but it works."** A single
smooth GGX lobe over a dielectric F0 *is* the look of moulded plastic. It
works on Cyberpunk's wardrobe because so much of that wardrobe genuinely is
synthetic — vinyl, latex, coated nylon, techwear shells. It fails on the
things that are not: wool, felt, velvet, brushed cotton, suede, denim nap.

## 2. The material-class census (all 3153 modules)

Every module in `~/callisto_dump` was disassembled and scanned for the class
test in all four idioms the patchers know (`gbuf.y >> 5 == K`, and the
mask-compare `(y & ~31) == K<<5`, via fetch or via phi).

| stage | modules |
|---|---|
| Fragment | 1219 |
| Vertex | 1130 |
| GLCompute | 675 |
| MissKHR | 57 |
| RayGenerationKHR | 43 |
| ClosestHitKHR | 24 |
| AnyHitKHR | 5 |

Classes tested **anywhere in the dump**: `{0, 1, 3, 4, 5}`. Class **2 is never
tested by any of the 3153 modules.** Known from the hunt: **1 = skin,
4 = hair**. `ERenderMaterialType` has six members, and the field is three bits
(`y >> 5`), so the six map onto 0–5 with two to spare.

Narrowing to where the visible radiance is computed:

| GLCompute modules ≥ 5000 lines | count | classes tested |
|---|---|---|
| carry the BRDF | 15 | **`{1, 4}`** (11) or **`{1}`** (4) |
| no class test at all | 9 | — (the tonemap/LUT family, `18`) |

**Not one large lighting module branches on any class other than skin and
hair.** And in the nine tile evaluators that `10` proved actually dispatch:

| module | lines | classes | Burley const | writes |
|---|---|---|---|---|
| `2e73a32c35778d85` | 975 | 1, 4 | yes | 2 |
| `81c13c37112d09df` | 1356 | 1, 4 | yes | 2 |
| `20e6c7b3626ae0d6` | 1198 | 1, 4 | yes | 2 |
| `4d46848998312027` | 1737 | 1, 4 | yes | 2 |
| `9a3fa53c53a3a21b` | 1982 | 1, 4 | yes | 2 |
| `0e5e5a6a78fdf1dd` | 779 | **4** | yes | 2 |
| `7ae88cd87950a898` | 1108 | **4** | yes | 2 |
| `03dc7a51279e7427` | 1306 | **4** | yes | 2 |
| `d5166c0f1ea464b9` | 1082 | **4** | yes | 2 |
| `99bb7c2698997b2a` (GI) | 52765 | 1 | yes | 1 |

Every one carries the full Burley + GGX stack. **Cloth pixels flow through the
un-gated default path in these exact modules** — which is the whole finding:
the code that would have to change is code we already reach.

**Two side-findings, recorded because they are not about cloth and would
otherwise be lost:**

- **`0e5e5a6a78fdf1dd` — the one still-unpatched executing module (`ba79030`
  covered the other three) — does carry a class-4 test**, at `:337-338`, in
  the mask form: `%217 = %193 & ~31; %219 = (%217 == 128)`, where
  `%193 = OpCompositeExtract %uint %191 1`. That is component 1 of a v4uint —
  which is precisely the shape `find_class_anchor_variant`'s fourth idiom
  already recognises. Its exclusion is therefore worth **one re-check of why
  the existing path rejects it**, not a new idiom. (Confidence: the shape
  matches; the actual failure was not reproduced.)
- **The G-buffer appears to carry a hair direction after all.** Fragment
  module `667c55bd59f5f145` branches on all five classes, and its class-4 arm
  (`:487-530`) decodes `2x-1`, reconstructs the third component as
  `sqrt(1 - dot(v,v))`, and picks the dominant axis from a 2-bit index — an
  octahedral-style *direction* decode, not a normal. Together with
  `EMM_SurfaceHairDirection` sitting among the G-buffer channel views
  (`16` §6), this is a second, independent challenge to `11` §2's "no tangent,
  no free channel." Not chased here.

## 3. The engine side: cloth gets nothing

Full `strings -n 5` over the shipping exe (59.9 MB, 2026-08-20), 177049 lines.

**Zero hits, word-boundary exact:** `Sheen`, `sheen`, `Velvet`, `velvet`,
`Ashikhmin`, `cvCloth`, `ClothProfile`, `Translucency`, `Tangent`,
`ThinFilm`, `Iridescence`. `Charlie` has exactly one hit and it is a
text-to-speech voice name (`audiottsvoicesFemale` block). There is no
`Editor/Characters/Cloth` CVar group.

Everything cloth-named in the exe is **physics or inventory**, not shading:
`NvCloth_SimulateChunk`, `SkinnedClothComponent`, `physicsclothPhaseConfig`,
`meshRawClothData`, `gameClothingSet`, `RandomizeClothing`. The single
rendering-side hit is `RMT_Cloth`, one member of `ERenderMaterialType`
alongside `RMT_Standard`, `RMT_Foliage`, `RMT_Hair`, `RMT_Eye`,
`RMT_Subsurface`.

So cloth is a **material type** the asset system knows about, and *not* a
shading branch anyone wrote. Set against the rest of the shader-constant
surface:

| material | engine CVars | Callisto has reach? |
|---|---|---|
| Hair | **41** (`cvHair*`, three lobes, alpha shifts, scatter depth) | subsumed by CVars (`16`) |
| Skin | 8 (`cvSkin*`, specular tint, ambient mix) | partly unique (SSS kernel) |
| Rim families | 13 (`cvCharacter/Standard/Weapon/Foliage` × 3) | see below |
| RT | 6 | `17` |
| **Cloth** | **0** | **whatever we build, or nothing** |

`GOTCHAS 8` says ask whether the engine already exposes it before writing a
patcher. Asked, and answered: it does not. For cloth the SPIR-V track is not
the hard way round — it is the only way round.

### The one engine lever that does touch clothing

`Developer/FeatureToggles/CharacterRimEnhancement` gates a rim pass whose
coefficients are split by category — and the categories are **Skin, Foliage,
Weapon, Standard**. There is no cloth category, which independently
corroborates §2: clothing is Standard. Each of these is single-occurrence in
the exe (`16`'s attribution method; group membership is inferred from the
single-occurrence layout and should be confirmed the same way before trusting
it):

```
Editor/Characters/RimEnhancement            GlobalCharacterFresnel
Editor/Characters/RimEnhancement/Standard   Standard_FresnelCoefficient
                                            Standard_SpecularCoefficient
                                            Standard_ConstOffsetCoefficient
Editor/Characters/RimEnhancement_RayTracing/Standard
                                            RoughnessFactor_Bias
                                            RoughnessFactor_Scale
                                            LightBlockerInfluence
```

**A grazing-angle Fresnel rim on the standard character material is a
poor-man's sheen** — sheen is, at bottom, a grazing-angle effect. It is not
the real thing: it is driven by `N·V` alone, with no `N·L` azimuthal falloff,
so it will read as a uniform edge glow that ignores where the light is, rather
than a directional bloom that walks around the garment as the light moves.
`11` §1 already observed this pass "paints only sunlit rims," and `16` §7
explained why: painting sunlit rims is what the feature does.

But it is **live-tunable, zero shader risk, and needs no launch to iterate**,
which is exactly the `hair_engine.lua` pattern. It is the correct first move,
and it should be A/B'd before any splice is written, because if it gets 60% of
the look then the splice is not worth the dispatch fight.

## 4. What a real cloth BRDF would be, and what it costs

The user's question — *material shader or BSDF?* — has a two-part answer, and
the split is the whole practical story.

### (a) The BSDF half: a sheen lobe. Small, well-understood, additive.

The standard model is Estevez & Kulla's "Charlie" sheen (Sony Imageworks,
2017), which is what UE, Filament and glTF's `KHR_materials_sheen` all use:

```
D_charlie(a, NoH) = (2 + 1/a) * pow(1 - NoH², 1/(2a)) / (2π)
V_neubelt(NoV,NoL) = 1 / (4 * (NoL + NoV - NoL*NoV))
f_sheen           = sheenColor * D_charlie * V_neubelt
```

The physical story: fabric is not a rough surface, it is a *forest of fibres
standing off* a surface. Light at grazing incidence hits the sides of the
fibres and scatters forward, so cloth gets bright at silhouettes in a way no
microfacet distribution can reproduce — GGX's lobe *narrows* toward grazing,
sheen's *widens*. That is the entire perceptual difference between "cloth" and
"plastic that happens to be rough."

**Cost, and this is the load-bearing number: ~15 SPIR-V instructions per
site.** `NoH`, `NoV`, `NoL` and roughness are all live at every GGX site in
these modules — `D` at `:1209-1216` already holds `NoH`, and the Smith `V` at
`:1217-1230` already holds both `NoL` and `NoV`. **Nothing new has to be
fetched, derived, estimated or delivered.** Contrast the hair work, which
spent the entire project estimating a tangent from a screen-space structure
tensor because the payload had no room for one (`11`).

Energy conservation wants `f = f_sheen + (1 - max3(sheenColor)·E(NoV))·(f_d +
f_s)`, where `E` is the sheen directional albedo — normally a small LUT. The
resolvers hand back a scalar diffuse/specular pair, not a layered stack, so
that would have to be a constant-factor approximation. Stated as a known
inaccuracy rather than discovered later.

The **diffuse** side also wants a small forward-scatter wrap, and that costs
nothing new: `build_diffuse`'s `w_wrap` machinery from the hair work is
directly reusable, gated differently.

### (b) The anisotropy half: out of scope, and for a familiar reason.

Woven fabric is anisotropic along the warp and weft, which is why satin has a
directional band and denim has a grain. That needs a tangent, and it hits the
same wall as hair (`11` §2) — worse, in fact. Callisto's screen-space
structure-tensor estimate works on hair *because* the normal rotates fast
across a strand and slowly along it, giving the tensor an eigenvector to lock
onto. A weave is sub-texel at any normal viewing distance; there is no
coherent normal field to differentiate, so the tensor returns noise and the
confidence term `(λ1−λ2)/(λ1+λ2)` correctly collapses the effect to zero.

**Do not attempt cloth anisotropy through the structure tensor.** It will not
fail loudly; it will produce a plausible-looking near-no-op, which is worse.

### (c) What this cannot fix

Sheen makes cloth read as *fibrous*. It does not add weave detail, does not
add fuzz silhouettes, and will not turn a garment whose roughness map is flat
into wool. Those live in §6.

## 5. The gate problem: which class is cloth?

Six `ERenderMaterialType` members, classes `{0,1,3,4,5}` tested, class 2 never
tested, `1 = skin` and `4 = hair` known. Cloth is one of `{0, 2, 3, 5}`.

**The mapping cannot be read offline.** The class is not a folded constant in
the G-buffer-fill fragment shaders — it arrives from a material constant
buffer. The scan for a folded class ID found exactly one candidate pattern
(40 fragment shaders OR-ing `128`), and reading one of them
(`02a3115467a2c3ba:830-847`) shows it is a 6-bit value packed with a flag bit
in a *different* channel, not the material ID. Negative result, recorded so it
is not re-derived.

Two cheap ways to measure it, both one launch:

1. **`EMM_SurfaceMaterialID`.** The engine ships a G-buffer material-ID debug
   view (`EEnvManagerModifier` enum, alongside `EMM_SurfaceRoughness`,
   `EMM_SurfaceMetalness`, `EMM_SurfaceHairDirection`). Enable it, look at a
   jacket, read the value. The selection CVar is most likely `DebugMode`
   (single-occurrence, sitting in the `RayTracing`/`Editor/RTXDI` block) —
   **that attribution is unconfirmed** and is the one thing to check first.
2. **A class-rainbow probe.** Splice `if (class == k) out *= palette[k]` for
   all six k into a resolver *proven to dispatch*, and read the classes off
   one screenshot. This repo already has the tier machinery
   (`build_tint_writes` / `build_hunt_writes`), and it is the same method that
   established hair = 4.

Note per `GOTCHAS 10` that (2) proves more than (1): it proves the class is
readable *at the splice site we intend to use*, which is the thing that
actually matters. (1) only proves the engine knows.

**And the diagnostic does not need the answer.** An un-gated sheen paints
every non-skin non-hair pixel — walls, cars, crates and clothing alike. That
is wrong as a *feature* and perfect as a *probe*: it removes the class gate
from the list of things that can explain a null result.

## 6. The asset route — "editing the clothing textures themselves"

Confirmed from the exe: clothing uses the **multilayered material system**.
`cloth_mov_multilayered`, `CMaterialParameterMultilayerSetup`,
`CMaterialParameterMultilayerMask`, `cooked_mlsetup`, `CustomMlSetup`,
`.customMultilayers`, `engine\materials\internal\multilayered_baked.mt`.

Each layer carries its own roughness, metalness, normal strength, microblend
and tiling. **That changes the BRDF's inputs, not the BRDF.** With only one
specular lobe available, every scrap of fabric character in this game has to
be faked in those maps — which is both why CDPR's cloth reads as convincing
plastic and why so much of the "plasticy" impression is fixable there:
roughness authored too low and too uniform, microblend detail absent or
tiled out at distance, metalness non-zero where it should be flat.

It is a **different toolchain** — WolvenKit, `.archive` packaging — that this
project has not built and that has nothing to do with the swap layer.

The honest comparison, since it is the real decision:

| | sheen splice | mlsetup editing |
|---|---|---|
| scope | every fabric surface in the game, at once | one garment at a time |
| ceiling | one degree better everywhere | *correct*, for that garment |
| cost | one patcher, unknown dispatch risk | per-garment art labour, ~1000 garments |
| toolchain | this repo | WolvenKit |
| risk | may change nothing at all (`10`) | none; it is authoring |

They are complementary, not competing. If the goal is "the game's clothing
looks better," the sheen lobe is the only move that scales.

## 7. The four buckets

**(a) Cloth BRDF that exists and can be tuned — NONE.** No sheen math, no
cloth CVar, no cloth shading branch, no cloth render node. There is nothing to
retune; there is a lobe to add.

**(b) A sheen lobe spliced into the compute evaluators — REACHABLE, and it is
the cheapest BRDF work this project has scoped.** No tangent, no new G-buffer
data, no payload change, ~15 instructions, all inputs live at the site,
targets already patchable. Gated entirely on one unproven thing: whether a
compute BRDF splice changes a pixel (§8).

**(c) Cloth anisotropy (warp/weft) — NOT REACHABLE.** Needs a tangent the
G-buffer does not deliver for cloth, and the structure-tensor estimate that
carried hair does not transfer to a sub-texel weave (§4b). Out of scope, and
stated plainly so it is not re-litigated.

**(d) Weave detail, fuzz silhouettes, per-garment character — NOT this
mechanism.** Asset-side (§6). Real, valuable, and a different mod.

## 8. Phase 0 — the smallest diagnostic (NOT built; spec only)

**Question it answers:** does a BRDF term spliced into the compute evaluators
change a pixel — at all, anywhere? This is `19`'s open item 3 in its cheapest
possible form, and cloth is a better vehicle for it than hair.

**The probe.** Add an un-gated, deliberately exaggerated Charlie sheen at the
specular sites of the **five patchable modules proven to dispatch**
(`2e73a32c35778d85`, `81c13c37112d09df`, `20e6c7b3626ae0d6`,
`4d46848998312027`, `9a3fa53c53a3a21b`) — selected by dispatch, per
`GOTCHAS 1`, not by constant scan, which `10` §3 showed picks the wrong
family. `sheenColor = (1,1,1)`, `sheenRoughness = 0.3`, weight ~4× taste.

**Sweep for siblings first** (`GOTCHAS 3`): the dump is one display mode and
one settings set. Re-run the dispatch-driven selector before believing the
list of five.

**Offline proof before any launch** (`GOTCHAS 6`): `spirv-val` every variant;
mirror the emitted math in Python and confirm the identity parameterisation is
bit-exact; replay capA with the swaps installed and confirm swap HITs on the
pipelines these five build into.

**Pass/fail from one screenshot** (any exterior daylight framing with a person
in frame, plus a toggle-off control):

- **PASS** — a grazing white bloom appears on every non-skin non-hair surface.
  Ugly, and decisive: the mechanism works, the target selection works, and
  §7(b) becomes a real feature — gate it on the cloth class from §5, dial the
  weight down, and ship. It also re-opens `19`'s hair verdict, because it
  would mean the hair null result was about the tangent or the gate, not the
  splice.
- **FAIL** — nothing changes. Then the compute-BRDF track is dead for cloth
  the same way it is dead for hair, and it dies *cleanly* this time: with no
  tangent estimate and no class gate in the way, there is no third explanation
  left. Record it and stop; `17`'s conclusion (ray-level edits and LUT
  authoring are the mod's real leverage) stands unamended.

Either outcome is worth the launch. That is unusual here and is the strongest
argument for running it.

## 9. Open items, in order

1. **A/B the `RimEnhancement/Standard` CVars** (§3). No shader risk, applies
   live, and it may satisfy the ask outright. Confirm the group attribution
   first, `16`'s way. Cheapest thing on this list by a wide margin.
2. **Run Phase 0** (§8). One patcher run, one launch, one screenshot — and it
   settles a question that has been open since `10`.
3. **Resolve the cloth class ID** (§5) — only needed once Phase 0 passes.
4. **Re-check why `0e5e5a6a78fdf1dd` is still unpatched** (§2). Its class-4
   test is in a shape the existing fourth idiom should already accept.
5. The G-buffer hair-direction lead (§2) — nothing to do with cloth, but it
   contradicts `11` §2 and someone should look before more hair work.

## Evidence index

- **Full-dump disassembly and class census**: all 3153 `~/callisto_dump/*.spv`
  disassembled with `spirv-dis`; scan covers all four class-test idioms.
  Scratch under the session scratchpad (`cloth/dis/`, `cloth/byclass.json`).
- **Standard BRDF read**: `42f0d5e99cfc5929`, `:1190-1230` (Burley + GGX D +
  height-correlated Smith V); Schlick `F0 = 0.04` at 15 sites.
- **Executing-evaluator table** (§2): module list from `10` §4; classes,
  line counts and Burley-constant presence re-derived here from the dump.
- **Exe audit**: `strings -n 5` over
  `<game>/bin/x64/Cyberpunk2077.exe` (59945608 B, 2026-08-20), 177049 lines;
  scratch `cloth/strings.txt`. CVar-path and enum blocks read in situ.
- **Negative result on folded class IDs**: `02a3115467a2c3ba:830-847`.
- Claims marked inferred above — `DebugMode` as the debug-view selector,
  RimEnhancement group membership, and the reading of `0e5e5a6a78fdf1dd`'s
  rejection — are exactly that. Everything in §1, §2 and §3 is read directly
  off instruction streams and string tables.
