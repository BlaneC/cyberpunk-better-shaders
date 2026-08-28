# CallistoSSS — architecture and current state

**Read this first.** `01`–`07` are the chronological investigation trail, each
correcting the one before it; several of their conclusions are superseded.
This document is the consolidated truth as of Aug 2026 for the **hair/skin**
work. Two later documents override parts of it: `16-ENGINE-HAIR-BRDF.md`
(the engine already ships a live-tunable three-lobe hair BRDF as CVars) and
`19-STATUS.md` (the ledger of what is confirmed on screen versus merely built).
The tonemapper track is separate and lives in `18-AGX-FEASIBILITY.md`, with
`21-AGX-GRADE-AND-SDR.md` superseding its SDR half.

---

## 1. What the mod is

Cyberpunk 2077 under Proton reaches the driver as SPIR-V (vkd3d-proton
translates DXIL, and dxil-spirv preserves the original DXIL identity in an
`OpString`). A Vulkan layer intercepts `vkCreateShaderModule` and substitutes
patched modules keyed by that identity. Nothing is decompiled or recompiled
from source: the shipped SPIR-V is disassembled, spliced at structurally
located anchors, reassembled, and validated.

Three effects ship today:

| effect | mechanism | surface |
|---|---|---|
| SSS diffusion kernel | RED4ext plugin patches the kernel upload | engine data |
| Skin BRDF (tier-1 `c1`) | SPIR-V splice | compute resolve (+ optional raygen) |
| Hair anisotropy (direct + GI) | SPIR-V splice | compute resolve |
| Hair shadow leak fix | SPIR-V splice (ray flags) | shadow/GI raygens |

All four are confirmed visible on screen and independently toggleable from
the CET settings tab.

---

## 2. The insight that took seven sessions

**A renderer uses a BRDF in two different roles, and only one of them decides
what you see.**

- **Sampling** (raygen / hit shaders): the BRDF is a probability distribution
  used to choose bounce directions and light candidates. Its output is
  *samples* — reservoirs, visibility, reflection hits.
- **Evaluation** (compute resolve): radiance is computed as
  `BRDF(v, l) × light × visibility / pdf`. This is the number that becomes a
  pixel.

The Monte Carlo estimator divides by the sampling pdf **specifically so the
choice of sampling distribution cancels out of the converged image**. Patching
the raygen BRDF therefore changes the term the estimator is designed to
cancel: it alters noise, not appearance.

That is why six sessions of provably-installed, provably-dispatched raygen
patches produced *zero* visible change. It was never a bug. The renderer was
working correctly and we were editing the wrong half of the equation.

**Where the visible shading lives:** 84 dumped whole-library `GLCompute`
modules carry the full material stack — 1/π, the Disney retro constant
`0.107508637`, and the `gbuf>>5` material-class gate. The RT passes feed them
samples.

---

## 3. Surface map

| stage | what it does | patchable effect |
|---|---|---|
| `rgs_reference_main` | PT sampling (12 permutations) | sampling only |
| `rgs_shadow_main` | shadow/visibility sampling | sampling only |
| `rgs_restirgi_*` | ReSTIR GI reservoirs | sampling only |
| thin `<hash>.dxil` raygens | PT tracers, **no shading at all** | none |
| `55f6172c….chs_main` | the one hit shader with a BRDF | sampling only |
| **84 `GLCompute` libs** | **lighting resolve → the image** | **everything visible** |

Material classes (from the hunt): **1 = skin**, **4 = hair**.

Two gate encodings exist in the resolve set, and the difference is
load-bearing:

- **48 modules** compute `gbuf.y >> 5` themselves → the **sun / direct** path.
- **36 modules** read the *same texel* at the *same binding*
  (`registers[2]+4`) but only mask `& 31`, never computing the class → the
  **local-light** paths. The class bits are present in the fetched word; those
  shaders simply don't use them, so the patcher emits its own `>> 5` after
  their existing fetch.

Symptom that revealed this: the effect appeared **only on sun-facing
surfaces**. Handling both encodings took coverage 48 → **68 of 84**. The
remaining 16: 14 have no material G-buffer read at all (sky/fog/volumetric
passes), 2 have no GGX site the class value dominates.

---

## 4. What ships (current build)

`./dev/patch_compute_hair.sh --hair 4` → **70 modules**, all `spirv-val` clean:

| splice | sites | effect |
|---|---|---|
| Kajiya-Kay aniso | 361 direct + 81 GI | highlight stretched along the strand |
| **Shifted dual lobe (R + TRT)** | 361 direct + 81 GI | **Marschner-flavoured sharp white R + wide tinted TRT highlights, shifted along the strand — see `08-DUAL-LOBE.md`** |
| **TRT transmission tint** | 361 direct + 81 GI | **constant RGB (`trt_r/g/b`); per-pixel albedo not recoverable in these modules** |
| Roughness reshape | all α uses | sharper spec; rewrites sampling too, so MIS stays unbiased |
| Grazing sheen | 39 | rim glow on backlit hair — **actually live as of `08` (was dead code, see below)** |
| Hair diffuse wrap + `k_diff` | 149 | softened terminator, darker diffuse → hair reads grounded |
| Skin tier-1 `c1` | 149 | grazing-angle warmth on skin |

> **`08-DUAL-LOBE.md` follow-up (Aug 26):** the structure tensor + tangent is
> now **hoisted** — emitted once per module (the `hoist_pos` pattern already
> used by the GI path) instead of re-emitted at each of the ~14 spec sites,
> cutting ~5 normal fetches per site. Achieved on all 68 direct modules.

> **Bug fixes (`08-DUAL-LOBE.md`, Aug 26):** the spec-output splice path had
> two latent bugs, both proven by dead-code analysis, both now fixed by a
> single combined pass (`build_hair_spec_lobes`) with per-out-at-def
> anchoring: (A) the grazing sheen was **dead code** — the aniso pass consumed
> every use of `s['outs']` before the sheen pass rewrote them; (B) `last_out`
> anchoring missed out-consumers defined *before* `last_out` on interleaved
> modules, so aniso reached only some channels. GI path fixed the same way.

**The strand tangent has no geometric source** — the hit payload is 16 bytes
with every bit accounted for. It is *estimated*: on a cylindrical fibre the
normal rotates fast across the strand and stays constant along it, so the
minor eigenvector of the structure tensor of the screen-space normal field is
the strand direction, and `(λ1−λ2)/(λ1+λ2)` is the confidence, which scales
the effect so non-fibre pixels fall back to vanilla. A synthetic-fibre test
caught a real bug here: the single-row eigenvector form degenerates to a zero
vector when the strand aligns with a screen axis (90°-wrong tangent at angle
0); both row forms are now computed and the longer one chosen branchlessly.

Skin `c1` and hair wrap are emitted as **one combined multiply** per Disney
scalar. Two independent passes rewriting the same scalar's uses clobber each
other — the reference `build_diffuse` learned this first.

### Knobs (`--set k=v`)

```
m_aniso 0.95   aniso strength      p_aniso 28    highlight tightness
s_h     0.45   roughness scale     a_min   0.04  roughness floor
k_sheen 0.30   grazing sheen       w_wrap  0.35  diffuse wrap width
k_diff  0.65   hair diffuse scale (lower = more depth/grounding)
m_dual 1.0     dual-lobe strength  beta_R -7 / beta_TRT 10  (deg)
p_R 28 / p_TRT 10   wR 1.0 / wTRT 0.3    trt_r/g/b 1/0.85/0.55
rho_f 1.35  rho_r 1.25  n_f/m_f/n_r/m_r 0.75    (skin c1)
```

Every knob has an identity value (`--vanilla` ⇒ bit-identical output).

---

## 5. Install layout and the settings gate

```
~/.local/lib/callisto/
  libVkLayer_callisto_spvswap.so
  swaps/            2 tier-1 reference raygens  (skinray option)
  swaps.hair/       70 compute resolve swaps    (the visible effects; 68 direct + 2 GI)
  swaps.prehunt/    pristine tier-1 backup
  hair.disable      present ⇒ hair overlay OFF
```

`load_swap` checks `swaps.<overlay>/` before `swaps/`; `overlay_init` reads
the flag once at load and logs `{"ev":"overlay","enabled":0|1}`. Toggle chain,
mirroring the existing kernel switch:

```
CET switch → brdf_params.txt → regen_and_clear.sh (launch) → flag file → layer
```

Toggles: **Callisto skin kernel**, **Callisto hair BRDF**, **Callisto
skin raygen sampling**, **Callisto BRDF**. All apply next launch; none require
re-running the patcher. Because hair lives in its own directory,
`sync_install`'s `rm -f swaps/*.spv` can never delete it. With every toggle
off (hair + shadowcull + skinray + kernel + tier), `load_swap` finds nothing
and the layer passes through — **bit-exact vanilla**, the A/B baseline.

`swaps/` deliberately holds *only* the two tier-1 raygens. Leftover hunt-build
raygens are eval-invisible but still perturb sampling with diagnostic tint
math.

---

## 6. Tooling

| tool | purpose |
|---|---|
| `swap_layer.c` | swap + dump + dispatch/pipeline logging + overlay |
| `dev/patch_compute_hair.py` | **the shipping patcher** — hair, skin c1, wrap |
| `dev/patch_compute_brdf.py` | compute-resolve skin marker (the diagnostic that cracked it) |
| `dev/patch_skin_brdf.py` | reference-raygen patcher; still the source of the shared BRDF builders |
| `dev/patch_shadow_brdf.py` | shadow-raygen anchors; **CFG + dominator analysis** reused everywhere |
| `dev/patch_chs_brdf.py` | hit-shader anchors; lenient module loader |
| `dev/scan_dump.py` | rank dumped modules by BRDF fingerprint |
| `dev/patch_agx.py` | **AgX tonemapper** — splices into the LUT *generator*; sites `auto`/`ap1`/`sdr2` (`sdr` is legacy and wrong); `--set grade=` keeps the authored area LUTs |
| `dev/find_lut_gens.py` | finds all **10** tonemap-LUT generator permutations (2 HDR + 8 SDR) |
| `dev/build_agx.sh` / `dev/install_agx.sh` | build the 14 variants × 10 permutations; install/remove/list |
| `dev/prov_map.py` | render graph from **offline** capture replay — its docstring carries the recipe |

### Layer instrumentation worth knowing

- `{"ev":"module",…,"swap":"HIT"}` — module created *and* substituted.
- `{"ev":"rt_pipeline"/"pipe_stage"}` — full pipeline composition. `pipe_stage`
  was added because `trace_rays` can only ever name a pipeline's **raygen**;
  hit shaders reached through the SBT are invisible to it. Joining these is
  what proved swapped raygens *were* dispatched and still changed nothing.

---

## 7. Bugs found the hard way

- **`trace_rays` attribution is unreliable.** `vkDestroyPipeline` never clears
  the rtpipe table, so reused handles report a *stale* raygen. Every
  historical dispatch log in `01`–`06` must be read with this in mind; it
  produced conclusions we acted on for multiple sessions.
- **`Module` ident regex required two dots**, so hash-only OpStrings
  (`<hash>.dxil` — every compute lib) returned `ident=None` and would have
  been silently unswappable.
- **Compute libs are SPIR-V 1.3, RT modules 1.4.** 1.4 tightened entry-point
  interface rules and rejects the 1.3 modules; target env is auto-detected
  per module.
- **Dominance is never assumed.** The game's own skin gate dominates *zero*
  eval sites in the shadow raygens. Patchers compute reachability and
  dominators and either refetch the class at the splice or skip and report.
- **A failed `spirv-val` left a stale `.spv`** for the installer to pick up.
- **`ls <glob> | wc -l` under `nullglob`** counts the whole working directory.
- **Splice ordering**: a Schlick `pow5` defined *after* the splice point
  produces an undefined-id validation error; those sites drop to no-sheen.

---

## 8. Open items

1. ~~Ambient/GI hair.~~ **Done — §9.** Both indirect resolvers patched.
2. **The 14 unpatched resolve modules** (no material G-buffer read at all —
   sky/fog/volumetric passes; nothing to gate on).
3. **CET sliders for the hair knobs** — currently patcher-side only. The
   toggles exist; the continuous knobs (`m_aniso`, `p_aniso`, `k_diff`, …)
   still require re-running the patcher.
4. **The layer's stale rtpipe table** (§7) is still unfixed. Harmless now that
   `pipe_stage` exists, but `trace_rays` output remains untrustworthy.
5. ~~Second specular lobe / true Marschner~~ — **Done (shifted dual-lobe,
   `08-DUAL-LOBE.md`).** R + TRT lobes shifted along the estimated tangent,
   validated offline, tensor hoisted, TRT glint tinted with a constant RGB
   (`trt_r/g/b`). Remaining ceiling: a *geometric* tangent (the estimate is
   screen-space) and a **per-pixel** TRT albedo tint (the constant is a
   stand-in — the compute resolvers don't expose the diffuse albedo).
6. **Dial back the exaggerated defaults.** Current values were set for visual
   confirmation, not taste: `m_aniso=1.8, p_aniso=24, k_sheen=0.5, s_h=0.40,
   w_wrap=0.45, k_diff=0.45`. Suggested shipping values: `m_aniso≈0.9`,
   `k_diff≈0.65`, `k_sheen≈0.3`.

---

## 9. GI/indirect hair (added after §8 item 1)

Two modules are shaped unlike the rest — `99bb7c2698997b2a` (52,765 lines,
62 GGX, 19 inputs) and `ab0bc2fee876d489` (18,633 lines, 20 GGX). Direct
resolvers write **two** buffers (diffuse+specular lighting) and read ~6
inputs; these write **one** and read many. That is an indirect/GI resolve,
and it explains why backlit and shadowed hair barely changed.

Both failed the normal path because their own class gate dominates **0** eval
sites — but the class is refetchable at **100%** of them. `build_hair_gi`
takes the hoisted path:

- **Class gate and structure tensor are emitted ONCE**, at the deepest block
  dominating every site (`hoist_pos`), and shared. Per-site emission would
  have cost ~5 normal fetches x 62 per pixel; the tangent is per-pixel and
  does not vary per site, so hoisting is both cheaper and equivalent.
- **Alpha reshape is skipped** on this path: alpha definitions can precede the
  hoist point, and rewriting them against a non-dominating gate is invalid.
- Two gotchas: `hoist_pos` must insert *above* any `OpSelectionMerge`
  (it must stay immediately before its branch), and the GI resolvers decode
  normals as `(n-0.5)` while the direct ones use `n*2-1` —
  `find_normal_gbuffer_any` accepts either (the tensor is indifferent, since
  it consumes neighbour differences).

Result: **70 modules**, 361 direct + **81 GI** aniso sites. GI uses a wider,
boosted lobe (`p_aniso_gi=10`, `gi_boost=1.6`) — a tight lobe across many
indirect samples reads as noise.

Current defaults are deliberately **exaggerated** for visibility:
`m_aniso=1.8, p_aniso=24, k_sheen=0.5, s_h=0.40, w_wrap=0.45, k_diff=0.45`.
Dial back toward `m_aniso 0.9 / k_diff 0.65` once the effect is confirmed.

---

## 10. Hair shadow leak fix (`shadowcull` overlay) — CONFIRMED FIXED

**Status: confirmed on screen, Aug 26 2026.** The overlit gap at the hairline
seam is gone. One constant per trace call.

**Symptom:** dangling hair casts correct sharp shadows on the face, but there
is an overlit gap right at the hairline seam — worst in *direct* light, not GI.

**Not** missing geometry (the sharp shadows prove hair is in the BVH) and
**not** ray bias (`tMin` is 1e-6). The cause is the shadow ray flags:

```
28 = TerminateOnFirstHit | SkipClosestHitShader | CullBackFacingTriangles
```

Hair is card geometry — thin, single-layer, double-sided quads. A card whose
winding faces away from the light is invisible to the shadow ray and occludes
nothing. In a thick clump enough cards face the light that the shadow reads;
at the sparse, near-edge-on seam it does not, and light pours through.

**Fix:** clear `0x10`, `28 → 12`. Not exotic: the game already traces the
majority of its shadow rays with flags 12 (52 sites vs 28), so the renderer
is known to work this way. 18 modules, 25 more skipped (no culling shadow
ray), 0 failures.

**Why this is visible when raygen BRDF edits were not** (§2): the estimator is
`BRDF × light × visibility / pdf`. `/pdf` cancels the *sampling distribution*;
**visibility is a factor of the integrand and is not cancelled.** Shadow-ray
parameters in a raygen therefore do change the image. The §2 lesson is about
sampling distributions specifically — it does not make raygens off-limits.

Scope note: ray flags are per-trace-call and cannot know the occluder will be
hair, so this is global to shadow rays. Back-face culling is often on to
suppress self-shadow acne, hence the toggle. Watch for acne on closed meshes
and a small any-hit perf cost.

**Layer now supports multiple overlays** (`CALLISTO_OVERLAYS`, default
`hair,shadowcull`), each with its own `<name>.disable` flag, checked in order
before base `swaps/`. Verified toggling independently.

Considered and rejected: screen-space contact shadows. Against soft GI, a
sharp screen-space term reads as an edge that does not belong — better to fix
visibility at the source than composite an approximation over it. That
judgement was vindicated: the real cause was a one-bit flag, and no
screen-space approximation was needed. **Generalisable lesson: when occlusion
looks wrong, interrogate what the shadow ray is allowed to hit before
reaching for a screen-space term to paint the darkness back on.**

Also rejected (§9 draft): weighting occlusion toward GI. Direct observation
contradicted it — the leak was worst in *direct* light. The symptom
description ("sharp shadows work, but there's a gap at the seam") is what
localised the bug; a density- or AO-based approximation would have masked it
without ever finding the cause.
