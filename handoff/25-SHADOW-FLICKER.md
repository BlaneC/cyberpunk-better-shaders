# 25 — Shadow-leak fix regression: LOD-transition flicker on flat geometry

Written 2026-08-28. Prompt: *the hair shadow-leak fix (the `shadowcull`
overlay) makes flat surfaces flicker black for an instant during LOD
transitions — "especially apparent on cardboard and flat garbage objects on
the ground" — then the material stabilizes. Is there a way to gate the toggle
only on hair, or to fix the flicker?* This document records the diagnosis,
the investigation, and the plan. **Nothing has been implemented yet** — it is
a handoff, not a changelog.

> **Superseded in part, 2026-08-28.** Renumbered 24 -> 25 (the PT tier-1 work
> took 24). Three claims below were checked against the shaders and the live
> trace log and **do not hold**; the fix that shipped instead is §8. Read the
> corrections before acting on §4-§7.

---

## 0. Corrections (2026-08-28)

| § | claim | verdict |
|---|---|---|
| §4 Q1 | "no occluder-material signal at trace time" | **false.** `CullOpaqueKHR` (0x40) / `CullNoOpaqueKHR` (0x80) are exactly that, evaluated per hit. The shadow rays set neither, and flags 28 sets no Force(Non)Opaque either, so geometry participates by its **authored** opacity. This is what §8 is built on. |
| §6 | `shadowgi=off` will fix the flicker | **unlikely.** `trace_rays` in `~/callisto_swap.jsonl`: 36 direct `rgs_shadow_main` traces vs **2** `rgs_restirgi_spatiotemporal`, and zero `rgs_restirgi_spatial`. Sunlit ground clutter is the direct family by two orders of magnitude. Kept as a diagnostic, not built as the fix. |
| §3 | "every other `rgs_*` family was skipped: its rays already lack the cull bit" | **false**, and contradicts `17` §2 in this repo. `rgs_diffuse_main`, `rgs_importance_main` and `281c46c2.rgs_shadow_main` use bare flags `16`; `94e675a5.rgs_shadow_main` uses `OpSelect(28, 16)`. They were skipped because the patcher requires the `0x0C` bits, not because the cull bit is absent. They stay skipped for a *better* reason (see §8). |
| §7 | reject a raised tMin because "a bias big enough for cardboard would skip hair cards" | **right answer, wrong argument.** tMin is `9.99999997e-07`, so there is real headroom; and hair occluding skin is centimetres away, not coincident. What a global raise would actually break is hair *self*-shadowing (sub-mm strand spacing). Demoted to a graded fallback (§8, Phase 3), not a dead end. |
| §2 | the flicker mechanism | **still untested.** "The whole material goes black" is uniform, which fits *coexisting LOD shells occluding* better than acne, which is speckled. §8 does not depend on which it is. |

## 8. The opacity-split shadow ray — **FALSIFIED**, see §9

> **Read §9 before §8.** The idea below was built, shipped, launched and
> disproved on 2026-08-28. It is kept in full because the *mechanism* (a second
> trace, min-combined, reusing ray A's payload) is sound and is now the vehicle
> for the bisect in §9 — only the discriminator it chose was wrong.


Instead of unculling everything, trace twice and take the nearer hit:

```
ray A   flags 28 = TerminateFirst | SkipCHS | CullBackFacing    (VANILLA)
ray B   flags 76 = TerminateFirst | SkipCHS | CullOpaque        (NEW)
t = min(tA, tB)
```

- **opaque geometry** — only ray A sees it, back faces culled: bit-for-bit
  vanilla, so it cannot produce the LOD flicker whatever the mechanism is.
- **non-opaque geometry** (hair, alpha cards) — ray B sees it with no
  back-face culling, so a card occludes whichever way it is wound. The
  hairline seam stays closed.

The combine needs no control flow. The payload is `OpTypeStruct { float }`
holding the hit distance and a miss leaves `FLT_MAX`, the identity for `min` —
verified across all 13 `rgs_shadow_main` modules: one member, and every access
chain on a payload variable indexes `%uint_0`. So ray B reuses ray A's payload
variable, and no new `RayPayloadKHR` global (and therefore no `OpEntryPoint`
interface edit) is needed. Emitted as `OpFOrdLessThan` + `OpSelect` rather than
GLSL `NMin`, so the splice carries no extended-instruction dependency:

```
        OpTraceRayKHR %accel %uint_28 %335 ... %130      ; unchanged
%1894 = OpLoad %float %1881                              ; unchanged
        OpTraceRayKHR %accel %uint_76 %335 ... %130      ; NEW
%94369 = OpLoad %float %1881                             ; NEW
%94370 = OpFOrdLessThan %bool %94369 %1894               ; NEW
%94371 = OpSelect %float %94370 %94369 %1894             ; NEW
%1268  = OpFOrdEqual %bool %94371 %float_3_40282347e_38  ; rewritten operand
```

**Scope.** Only unambiguous occlusion rays: flags must be a *constant* with
`0x0C` and `0x10`. That is 28 sites across 18 modules — exactly the set
`patch_shadow_flags.py` already owns, so the two builds are like-for-like and
an A/B attributes the edit, not the coverage. The flags-16 modules stay out
for a reason §3 missed: flags 16 lacks `SkipClosestHitShader`, so those rays
run the closest-hit shader and their payload carries *shading*, not a
distance. Min-combining it would be nonsense. `94e675a5` is excluded on the
same ground — one arm of its `OpSelect` is a shading ray.

**Honest limits.** Alpha-tested clutter (trash sheets, foliage, chain-link) is
non-opaque too, so ray B still sees its back faces: if the flickering "flat
garbage" turns out to be alpha-tested rather than solid, this narrows the
problem instead of closing it. And it costs one extra shadow ray per site,
unconditionally — gating ray B on "ray A missed" would halve that in shadowed
regions but needs a real CFG edit.

**Toggle.** Originally a boolean `shadowsplit`, now the `shadowset` selector
described in §9 — `split` is one of its entries. `sync_settings.sh` still maps
the legacy `shadowsplit=on|off` to `split|full` for one migration launch.

| file | what |
|---|---|
| `dev/patch_shadow_opacity.py` | the splice, with the payload-shape proof and the skip reasons |
| `dev/build_shadow_sets.sh` | builds every set and asserts they cover the same ids |
| `dev/install_shadow_sets.sh` | parks them; `status`, `remove` |
| `sync_settings.sh` | `shadowset`, `want_shadowset` in the stamp and status |
| `init.lua` (+ mirror) | the selector, and a warning when no sets are installed |

**Launched, and disproved.** Offline it was clean — 28 sites found,
`spirv-val` clean on all 18 modules, the switch exercised through the real
`sync_settings.sh` in both directions. On screen the seam came back. See §9.

**Still queued** if the split leaves alpha-tested clutter flickering:
Phase 3 = a raised tMin on ray B alone (it can carry its own, so only
alpha-tested geometry pays for it). Phase 4 = §7's Stage 2, per-instance
`CULL_DISABLE`, which remains the principled endgame.

---

## 1. The regression

`00-ARCHITECTURE.md` §10 shipped the hair shadow-leak fix: shadow rays stop
culling back-facing triangles (`28 → 12`), so thin double-sided hair cards
occlude from either side. It is the project's single most solid visible win
(`19-STATUS.md` §1), and the mechanism is `dev/patch_shadow_flags.py` +
`dev/patch_shadow_flags.sh`, installed as the `shadowcull` overlay.

The regression it introduces, reported by the user:

> When textures change LOD, the whole material goes black for an instant,
> then stabilizes. Flickery image going through the city; worst on cardboard
> and flat garbage on the ground.

Attribution is already confirmed by the user: the flicker tracks the
`shadowcull` toggle.

---

## 2. Mechanism

Clearing `CullBackFacingTriangles` is a **global** change to shadow/visibility
rays. A shadow ray fired from a thin surface (cardboard, flat garbage — thin
single-layer meshes) now hits the **back face of its own geometry**, which the
flag used to cull. Two things make it flicker rather than read as a constant
self-shadow:

- Thin/flat meshes have their front and back faces nearly coincident, so the
  back-face self-hit is right at the acne threshold — sensitive to the
  smallest LOD change.
- During a mesh LOD switch the shadow-cast geometry and the rasterized
  geometry briefly disagree (a card collapses to a plane, or two LODs coexist
  in the TLAS), so the self-hit appears/disappears for a frame → "black for an
  instant, then stabilizes."

The hair fix is a **direct-light** effect (the hairline seam is "worst in
direct light, not GI", `00` §10). The GI visibility rays got the same flag
change purely because the patcher swept every back-face-culling shadow ray it
found — not because the hair fix needed them.

---

## 3. What the `shadowcull` overlay actually touches

`dev/patch_shadow_flags.py` matches every `OpTraceRayKHR` whose flags carry
`TerminateOnFirstHit | SkipClosestHitShader | CullBackFacingTriangles`
(`0x0C | 0x10`) and clears `0x10`. Built against `~/callisto_dump`, this
yields **18 modules**:

| family | count | modules |
|---|---|---|
| `rgs_shadow_main` | 10 | `b80f16ff`(4) `66d84088`(3) `1ddeee1d`(3) `ebd5818b`(2) `b2164534`(2) `7c0ac26d`(2) `ef3cbee1`(1) `cdceb472`(1) `7db46e82`(1) `1e54e372`(1) |
| `rgs_restirgi_spatiotemporal` | 4 | `038867e9` `1ca55ed0` `006ba4e3` `a3b07b0f` (1 each) |
| `rgs_restirgi_spatial` | 4 | `5e1e98e4` `9d117caf` `174dee89` `fc60b8a0` (1 each) |

Every other `rgs_*` family (`rgs_reference_main`, `rgs_importance_main`,
`rgs_diffuse_main`, `rgs_reflection_*`) was **skipped**: its shadow/visibility
rays already lack the cull bit (the reference path's own occlusion ray already
uses flags `12`, per `17-LEVERS.md` §2).

**Which of these actually dispatch** (vanilla RT Overdrive, the user's mode) —
`04-RESET-STATE.md` fact 2:

```
rgs_reference_main ×2 + rgs_shadow_main ×5 + rgs_shadow_transparent_main
+ rgs_reflection_transparent_main + rgs_restirgi_spatiotemporal ×2
```

So in the user's play mode the active half of the overlay is **5 direct
`rgs_shadow_main` modules + 2 GI `rgs_restirgi_spatiotemporal` modules**. The
4 `rgs_restirgi_spatial` modules only dispatch under Ultra Plus's ReSTIR mode
(`23` §3). The direct-sun shadow on ground clutter comes from `rgs_shadow_main`;
the GI ambient visibility from `rgs_restirgi_spatiotemporal`. Both families can
self-shadow thin objects, so both are candidate flicker sources.

---

## 4. The two questions the user asked

### Q1 — gate the toggle on hair only?

**No, not with ray flags.** The flags are a per-`OpTraceRayKHR` constant and
there is no occluder-material signal at trace time — and the *origin* surface's
material is no help either (the hairline gap is about the hair-card *occluder*,
while the ray originates on skin). `patch_shadow_flags.py`'s own docstring
states this; it remains true.

The only material-correct mechanism is the **per-instance
`VK_GEOMETRY_INSTANCE_TRIANGLE_CULL_DISABLE_BIT`** set at acceleration-structure
build time — which would make hair's triangles double-sided for *all* rays
without touching the global shadow-ray flags. That is a different, larger
feature (see §7, Stage 2), and it needs hair-instance identification, which
does not exist yet.

### Q2 — fix the flicker?

Yes, two real levers:

- **Lever A — engine CVars** (live, zero shader risk). Stabilize the
  shadow-cast geometry so it stops LOD-popping against the raster mesh.
- **Lever B — scope narrowing** (shader-side, next-launch). Drop the GI
  modules from the overlay, keeping only the direct shadow family that the
  hair fix actually needs.

---

## 5. Lever A — the CET knob surface (Ultra Plus is the reference)

Per GOTCHAS #8, the engine CVar surface was searched before writing any
shader code. Ultra Plus v9.2.2 (`~/Downloads/Cyberpunk Ultra Plus v9.2.2 …`)
writes these, all live via CET and all verified present in the shipping
`Cyberpunk2077.exe`:

| CVar path | Ultra Plus value | what it does |
|---|---|---|
| `RayTracing/ForceShadowLODBiasUsage` | `true` (debug.ini) | force a fixed shadow LOD bias |
| `RayTracing/ForceShadowLODBiasValue` | `1` (debug.ini) | the fixed LOD bias value |
| `RayTracing/ForceShadowLODBiasUseMax` | *(exists in exe)* | companion flag |
| `/graphics/advanced/ShadowMeshQuality` | `2` (top preset) | full-quality shadow meshes (int, `GameOptions.SetInt`) |
| `Editor/RTXDI/EmissiveShadowRayOffset` | `0.01`–`0.015` | shadow-ray bias for emissive triangle lights |
| `Editor/RTXDI/ShadowFadeFraction` | `0.05`–`0.1` | shadow fade distance |
| `RayTracing/LocalShadow/ContactShadowRange` | `0.4`–`1.5` | local-shadow contact range |
| `Editor/Characters/Hair/UseGlobalContactShadowsOnHair` | `true` | already in `hair_engine.lua` |

`ForceShadowLODBias*` directly attacks the LOD-transition trigger of the
flicker. The strings block in the exe places them under `RayTracing/TLAS`,
but the runtime path Ultra Plus writes is the bare `RayTracing/…` form above —
use that.

Note the hair CVar audit already proved **there is no back-face/culling
constant among the 71 `cv*` shader constants** (`16-ENGINE-HAIR-BRDF.md` §7),
so this flicker cannot be fixed with a shadow-ray flag CVar — only by
stabilizing geometry (the LOD knobs) or biasing rays (`EmissiveShadowRayOffset`).

CET API details: `GameOptions.SetBool/SetInt/SetFloat(category, item, value)`
exist (Ultra Plus `lib/Cyberpunk.lua:133-147`); `ShadowMeshQuality` is an int
under `/graphics/advanced`.

---

## 6. Lever B — scope narrowing, and the toggle design

The hairline fix is direct-light, so the 8 `rgs_restirgi_*` modules contribute
flicker risk but nothing to the fix. The user asked for a **toggle**: choose
between "shadows only" (direct family) and "shadows + GI" (current full
overlay).

Chosen design — no layer rebuild, no new overlay name, uses the existing
served-dir + flag-file mechanics:

- `swaps.shadowcull/` remains the **served** overlay (it is in the compiled
  `CALLISTO_OVERLAYS` default `"hair,shadowcull"`).
- The GI modules park in a sibling **`swaps.shadowcull.gi/`** dir, which is
  *not* served (its name is not in the overlay list).
- At launch, `sync_settings.sh` moves the `*rgs_restirgi_*.spv` files between
  the served dir and the parking dir based on a new `shadowgi=on|off` param:
  - `shadowgi=on` (default, current behavior): GI modules live in
    `swaps.shadowcull/`.
  - `shadowgi=off`: GI modules are parked in `swaps.shadowcull.gi/`, leaving
    only the 10 direct `rgs_shadow_main` modules served.

This is safe with the cache gate: `sync_settings.sh` already hashes
`swaps.shadowcull/*.spv` into the cache stamp (`sync_settings.sh:152`), so
moving files in/out changes the payload hash and forces a cache clear. The
parking dir is not hashed and not served.

The `shadowcull.disable` master flag is unchanged and composes: master
`off` disables the whole overlay; `shadowgi` only decides the direct-vs-GI
content when it is on.

---

## 7. Plan (staged — the user chose "both, staged")

### Stage 1 — quick stopgap (ship now)

1. **`shadowgi` toggle** (§6):
   - `init.lua`: add a `shadowgi` switch (default `on`) writing
     `shadowgi=on/off` to `brdf_params.txt`, next to the existing
     "Hair shadow leak fix" switch.
   - `sync_settings.sh`: read `shadowgi`; park/unpark the GI modules in
     `$INSTALL_DIR/swaps.shadowcull{,.gi}/` accordingly; add `shadowgi` to the
     `want=` stamp string.
   - `regen_and_clear.sh`: mirror the same park/unpark for the dev path.
2. **CET shadow-stabilization panel** (§5): a new `shadow_stability.lua`
   (the `hair_engine.lua` pattern — snapshot vanilla, master switch, re-assert
   on a 2 s timer) exposing `ForceShadowLODBias*`, `ShadowMeshQuality`,
   `EmissiveShadowRayOffset`, `ShadowFadeFraction`. Wired into `init.lua` via
   the same defensive `require` used for `hair_engine`.
3. **Verify**: hairline seam still closed; cardboard/ground flicker gone
   (with `shadowgi=off`, with the CET knobs, and with both). If `shadowgi=off`
   alone does not remove the flicker, the direct `rgs_shadow_main` family is
   the source and the CET LOD-bias knobs are the fix.

### Stage 2 — principled gate on hair (follow-up, do not ship before it is proven)

Per-instance `VK_GEOMETRY_INSTANCE_TRIANGLE_CULL_DISABLE_BIT` at
acceleration-structure build:

1. Add `vkCmdBuildAccelerationStructuresKHR` / `vkBuildAccelerationStructuresKHR`
   hooks to `swap_layer.c` and parse the `VkAccelerationStructureInstanceKHR`
   arrays.
2. **Identify hair instances** — the hard, unproven part. Candidate signals to
   survey offline: `instanceCustomIndex` ranges, SBT-record grouping,
   `mask`, or a hair BLAS identifiable by double-sided geometry. GOTCHAS #1/#8:
   identify by what actually executes / by what the engine exposes, never by a
   plausible constant.
3. Deliverable is a **findings doc + offline probe**, not a shipped feature,
   until hair-instance identification is proven rather than inferred.

### Rejected

- **Screen-space contact shadows as the primary fix** — rejected in
  `00-ARCHITECTURE.md` §10 (sharp screen-space edge against soft GI); the flag
  fix was vindicated, but the flicker is a *new* cost of that fix, so this is
  re-opened only as a hair-specific complement (`UseGlobalContactShadowsOnHair`),
  not a replacement.
- **A shadow-ray bias / larger `tMin` to hide the self-hit** — the tension is
  real: hair cards are thin, so a bias large enough to skip the coincident
  back face of cardboard would also skip hair cards and reopen the hairline
  gap. Not attempted; the LOD-bias knobs are the lower-risk lever for the same
  symptom.

---

## 9. Falsification, and the bisect that replaces it (2026-08-28)

### What happened

The split build launched correctly — the layer log proves it: `swap_load` for
the split-set byte sizes (2291076 / 1364464 / 1340088 / 2266432), 10 swaps
applied, 0 failed. And the hairline seam **came back**, looking as it did
before any fix.

### Why it was wrong

§8 claimed hair is alpha-tested — non-opaque in the acceleration structure —
citing `17` §2's record that the PT visibility ray uses flags
`10 = NoOpaqueKHR | SkipClosestHitShader`.

That is evidence of the **opposite**. `NoOpaqueKHR` *forces* geometry
non-opaque so that any-hit runs; a ray only needs to force that if the geometry
is opaque by default. The shadow rays (flags 28) force neither, so they see
hair as **authored**, and the launch says authored is opaque. Ray B, culling
opaque geometry, therefore saw nothing at the hairline and contributed nothing.

**Opacity is not a usable discriminator here.** Anything built on "hair is the
non-opaque geometry" is dead.

### What survives

The two-ray splice itself. `min(tA, tB)` over a single-float payload is exact,
needs no control flow, and `dev/patch_shadow_opacity.py` now takes
`--ray-b-flags`, `--ray-b-mask` and `--ray-b-tmin`, so ray B can be aimed at
any slice of the world without touching ray A. That turns the mechanism into a
probe.

### The lever the bisect uses

All 10 `rgs_shadow_main` modules choose their cull mask at runtime:

```
%335 = OpSelect %uint %334 %uint_86 %uint_38
```

`38` = bits {1,2,5}, `86` = bits {1,2,4,6}; the union is bits {1,2,4,5,6} = 118.
The global 28→12 build closes the seam **with these masks unchanged**, so the
occluder that matters is inside those five bits. Five candidates, and a
two-step bisect finds it.

Ray B's mask is emitted as `OpBitwiseAnd` of ray A's own mask with the
constant, never as a replacement — ray B stays a strict subset of what ray A
could have seen, whichever arm of the select won at runtime.

### The variants, and how to walk them

`dev/build_shadow_sets.sh` builds ten sets, all covering the same 18 modules
(the build script asserts that), and `dev/install_shadow_sets.sh` parks them in
`$INSTALL_DIR/shadowcull.set/<name>/` (~103 MB total). The CET page's
**Hair → Shadow-ray build** selector names one; `sync_settings.sh` materializes
it into `swaps.shadowcull/` at launch and evicts the pipeline caches when it
changes. No rebuild per step — the whole bisect is walkable from the settings
menu across relaunches.

| set | ray B | asks |
|---|---|---|
| `full` | *(none — 28→12 in place)* | the working build. Seam closed, flat props flicker. **The default.** |
| `ctrl` | flags 12, mask untouched | **plumbing control.** Ray 12's hit set is a superset of ray 28's, so `min()` is always ray B and this is logically `full` for a binary shadow test. If the seam does **not** close here, the splice is broken and every row below is meaningless. Run this first. |
| `m6` | flags 12, mask &= 6 | is the occluder in bits {1,2}? |
| `m112` | flags 12, mask &= 112 | is it in bits {4,5,6}? |
| `m2` `m4` `m16` `m32` `m64` | flags 12, mask &= one bit | isolate, inside whichever half won |
| `split` | flags 76 | §8, kept for the record |

The target is the set where the hairline seam is **closed** *and* flat props are
**steady**. `ctrl` is expected to close the seam and flicker (it is `full`); a
good `m*` closes the seam without the flicker.

If **every** `m*` flickers as badly as `full`, the mask is not the axis and the
next lever is `--ray-b-tmin`: hair cards sit at sub-millimetre spacing, so a
ray B with a raised tMin skips the coincident back face of a flat prop while
still hitting a hair card a few millimetres away. That flag already exists;
only the variant list needs a row.

### Cost

One extra shadow ray per site on every set except `full`. `full` is unchanged
in cost from the shipped build.

### Results so far

| set | launched | seam | flicker | notes |
|---|---|---|---|---|
| `full` | yes (many) | **closed** | present | the reference. Rebuilt 2026-08-28; verified structurally identical — 4 traces, all `%uint_12`, no added rays. |
| `split` | yes | open | — | falsified, above. |
| `m6` | yes, one launch | not reported | not reported | ran at 10:4x on 2026-08-28; no observation recorded. |
| `m112` | yes | **open** | — | provisional: suggests the occluder is not in mask bits {4,5,6}. |
| `ctrl` | **not yet** | — | — | **run this before trusting any `m*` result.** |

`m112`'s negative is only meaningful if the splice works, and that is exactly
what `ctrl` establishes. Until `ctrl` is seen to close the seam, a negative
`m*` is indistinguishable from a broken second ray. Run `ctrl` first.

### The class-1 hole: why `m6` and `m112` both regressed (2026-08-28)

`ctrl` validated on launch — the two-ray splice works at runtime. Both `m6` and
`m112` regressed. That looked impossible, because they partition ray A's mask,
and one overlapping bit is enough for a hit — so if `full` closes the seam, one
of them had to.

The premise was wrong. **The two trace families do not carry the same classes:**

| family | sites | mask operand | classes |
|---|---|---|---|
| `rgs_shadow_main` | 20 | `OpSelect(86, 38)` | {2,4,16,32,64} = **118** |
| `rgs_restirgi_*` | 8 | `OpSelect(87, 39)` | {1,2,4,16,32,64} = **119** |

`m6` ∪ `m112` = 118. That partitions everything the *shadow* traces can see and
misses **class 1 entirely** — a class only the *GI* traces carry. Both variants
dropped it, so both behaved like vanilla at the hairline while `ctrl`, which
touches no mask, kept it.

The bisect was built off one sampled module (`b80f16ff.rgs_shadow_main`) and its
mask generalised to all 18 without checking. Enumerating all 28 patched sites
takes seconds and would have caught it before any launch.

Three sets added:

| set | ray B mask | isolates |
|---|---|---|
| `m1` | `& 1` | class 1 only. Zero mask on all 20 shadow sites (ray B hits nothing there), class 1 on the 8 GI sites — so this tests "the GI traces, class 1" alone. |
| `m118` | `& 118` | everything except class 1; the complement of `m1`. |
| `m119` | `& 119` | every class, both families. Should match `ctrl`; a second control. |

If `m1` closes the seam, the hairline occluder is GI-side class 1 — which also
means the direct shadow traces never see it at all (86/38 exclude bit 0), and
the seam is an indirect-lighting phenomenon rather than a direct-shadow one.

### The trap this walked into

The `m112` launch was read as a `full` launch. The selector had been moved to
"Uncull everything" *during* the session and a save reloaded, which changes
nothing — `sync_settings.sh` runs only in the Steam launch options, and the
layer only substitutes SPIR-V at `vkCreateShaderModule`, i.e. at startup.

Proof of what actually ran is in the layer log: the parked sets have distinct
per-file byte sizes, and the eight `rgs_restirgi_*` sizes are the
discriminator (the `rgs_shadow_main` sizes collide between `m6` and `m112`).
The selector's label now carries `[running: <set>]` so the two can never be
confused again. See GOTCHAS.

---

## Evidence index

- Fix and scope: `00-ARCHITECTURE.md` §10; `dev/patch_shadow_flags.py` docstring.
- Dispatch facts: `04-RESET-STATE.md` fact 2; ReSTIR mode split `23` §3.
- Ray-flag survey: `17-LEVERS.md` §2.
- No culling CVar exists: `16-ENGINE-HAIR-BRDF.md` §7.
- Ultra Plus CVar reference values: `~/Downloads/Cyberpunk Ultra Plus v9.2.2 …`
  `config/debug.ini`, `config/graphics.ini`, `config/modes.ini`,
  `lib/Cyberpunk.lua`; exe string block for `RayTracing/TLAS/ForceShadowLODBias*`.
- Launch sync + cache stamp: `release/game/red4ext/plugins/CallistoSSS/sync_settings.sh`
  (`shadowcull` flag, then the `shadowset` materialization block; payload hash
  further down).
- Variant matrix: `dev/build_shadow_sets.sh` `VARIANTS`; the CET selector's
  `SHADOW_SETS` in `init.lua` must list the same ids.
- Falsification evidence: `~/callisto_swap.jsonl`, pid 1215461 — `swap_load`
  sizes match the split set, 10 swaps, 0 failed.
- CET panel pattern to reuse: `hair_engine.lua`.

---

## 10. Closed, 2026-08-28

The narrowing is finished and the answer is negative on the flicker.

`full-shadow` (flags `28 -> 12` on the 10 `rgs_shadow` modules only) closes the
seam and reduces the flicker; it **ships as the default**. The GI half (`full-gi`)
added flicker and nothing visible to the seam, so the original `full` is kept
only as a second option.

The residual flicker cannot be reached on this axis. Ray flags are per-*ray*, so
unculling any trace unculls everything that trace can see -- there is no subset
of sites that separates the hair from the flat props. The only lever that selects
geometry is the `CullMask`, and using it requires a second ray, which **does not
execute** in this shader stage (`26` §7d, proven by the `sctrl` positive control).

§8's opacity split and §9's class bisect are both void for that reason: they varied
a ray that never ran. All 19 experimental sets were deleted; their recipes and
results survive in the header of `dev/build_shadow_sets.sh`.
