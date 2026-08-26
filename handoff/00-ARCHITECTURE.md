# CallistoSSS — architecture and current state

**Read this first.** `01`–`07` are the chronological investigation trail, each
correcting the one before it; several of their conclusions are superseded.
This document is the consolidated truth as of Aug 2026.

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
| Hair anisotropy | SPIR-V splice | compute resolve |

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

`./dev/patch_compute_hair.sh --hair 4` → **68 modules**, all `spirv-val` clean:

| splice | sites | effect |
|---|---|---|
| Kajiya-Kay aniso | 361 | highlight stretched along the strand |
| Roughness reshape | all α uses | sharper spec; rewrites sampling too, so MIS stays unbiased |
| Grazing sheen | 39 | rim glow on backlit hair |
| Hair diffuse wrap + `k_diff` | 149 | softened terminator, darker diffuse → hair reads grounded |
| Skin tier-1 `c1` | 149 | grazing-angle warmth on skin |

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
rho_f 1.35  rho_r 1.25  n_f/m_f/n_r/m_r 0.75    (skin c1)
```

Every knob has an identity value (`--vanilla` ⇒ bit-identical output).

---

## 5. Install layout and the settings gate

```
~/.local/lib/callisto/
  libVkLayer_callisto_spvswap.so
  swaps/            2 tier-1 reference raygens  (skinray option)
  swaps.hair/       68 compute resolve swaps    (the visible effects)
  swaps.prehunt/    pristine tier-1 backup
  hair.disable      present ⇒ hair overlay OFF
```

`load_swap` checks `swaps.<overlay>/` before `swaps/`; `overlay_init` reads
the flag once at load and logs `{"ev":"overlay","enabled":0|1}`. Toggle chain,
mirroring the existing kernel switch:

```
CET switch → brdf_params.txt → regen_and_clear.sh (launch) → flag file → layer
```

Toggles: **Callisto skin kernel**, **Callisto hair anisotropy**, **Callisto
skin raygen sampling**, **Callisto BRDF**. All apply next launch; none require
re-running the patcher. Because hair lives in its own directory,
`sync_install`'s `rm -f swaps/*.spv` can never delete it.

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

1. **Ambient/GI hair.** Paths without a per-light GGX eval are untouched, so
   fully backlit or shadowed hair changes least.
2. **The 16 unpatched resolve modules** (14 no material read, 2 no dominated
   GGX site).
3. **CET sliders for the hair knobs** — currently patcher-side only.
4. **The layer's stale rtpipe table** (§7) is still unfixed.
5. **Second specular lobe / true Marschner** — needs a real tangent; the
   structure-tensor estimate is a screen-space approximation.
