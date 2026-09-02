# 96 — New material classes from the G-buffer fill: MILESTONE 1, static only

Written 2026-09-01. **Nothing built, nothing installed, nothing committed, no
launch, no `make install`, no shared file edited.** This is the offline gate
report for the question: *can we patch the G-buffer fill FRAGMENT shaders of a
chosen material template to write a dead class value (2, 6 or 7) into the
material byte, so PT-side evaluators gate a new BRDF on it?*

Method: binary SPIR-V census over all **3290** modules in `~/callisto_dump`
(no `spirv-dis` in the census path — GOTCHAS: `grep` over the dump silently
returns 0 for strings that are present), plus targeted `spirv-dis` reads of 8
modules, plus `analysis/evidence/meta/capA_prov.jsonl` (compute provenance,
via `dev/prov_map.py`) and `analysis/evidence/meta/capA_gfx.jsonl` (the raster
half, via `dev/gfx_map.py`). Scratch scripts are in this session's scratchpad;
nothing was added to `dev/`.

---

## 0. Verdict first

| question | answer | confidence |
|---|---|---|
| Are class values 2, 6, 7 really dead in the readers? | **Yes — 0 of 130 readers compare against them, anywhere, in any stage.** No array indexing, no arithmetic, no range compare. | **high** — whole-dump census, §2 |
| Do 2/6/7 therefore fall to the class-0 path? | **NO. This is the finding that reshapes the plan.** In **54 GLCompute modules** the class `OpSwitch`'s default label **is the selection-merge block**, and the merge phis take **constant 0.0** on that edge. A dead class does not render as class 0 there — it renders **black**. | **high** — measured, §2.2 |
| Where are they safe? | **All 24 switch-carrying raygens and all 27 no-`case 0` compute modules**: their switches have no `case 0`, so class 0 already *is* the default arm and 2/6/7 are bit-identical to class 0. The 11 compare-only reference raygens lose only the class-0 MS energy term. | **high**, §2.2 |
| Is the material byte written by the G-buffer fill fragment shaders? | **No — FALSIFIED.** The 4 G-buffer render targets are decoded end to end in §1 and none of them carries it. The material byte lives in a **separate 1280×720 `R8G8B8A8_UNORM` colour attachment** that no compute module writes and that **no rendering scope in `capA_gfx.jsonl` writes either**. Its producer is not identified. | **high** on the falsification, §1.3; **the writer is an open item**, §1.5 |
| So is the feature blocked? | **The dead-class route is blocked at step 1 and would be expensive even unblocked** (54 modules must be co-patched or the material goes black). **But the feature does not need it** — §4 gives two cheaper channels that are open today. | — |
| Cheapest correct route for car paint | **Synthesise the class PT-side**: `class' = (class==0 && metallic>=0.5 && roughness<=0.35) ? 6 : class`, spliced one instruction after the existing `>>5`, in the modules `81`/`94` already patch. Zero fragment work, zero new attachment, and the gate is `94` §4.1's gate verbatim. | **high** §4.1 |
| Second channel, if a *persistent* identity is wanted | **The 5-bit sub-enum under class 0**, which has **21 unused values** and which `80` §2.1 established no shader tests under class 0. That is the free per-pixel identity channel — but it still needs the same unfound fragment write site. | medium §4.2 |

**One-line summary.** The dead classes are genuinely dead in the *comparisons*
and genuinely **not** dead in the *control flow*: `default == merge` everywhere,
and in 54 compute evaluators the merge phis are zeroed, so a class the shader
does not know about is not "class 0", it is "no light". Separately, the premise
of the brief — that a G-buffer fill fragment shader packs and writes the
material byte — is false as stated: those shaders write albedo, normal,
metal/rough/normal-hi/translucency and velocity, and the material byte comes
from a fourth image nobody in this dump can be shown to write.

---

## 1. The G-buffer fill fragment shaders, decoded

### 1.1 The population

Whole-dump stage census (3290 modules, up from `79` §6's 3273):

```
Vertex 1182   Fragment 1304   GLCompute 675   Miss 57
RayGeneration 43   ClosestHit 24   AnyHit 5
```

Fragment modules by output signature (`OpVariable ... Output` + `Location`):

```
503  loc0 only                      (post/UI/decal single-target)
262  loc0,1,2                       G-buffer fill, no velocity
187  loc0,1,2,3                     G-buffer fill + velocity
 75  loc0,loc0                      (dual-source blend)
 71  loc0,loc2      50  loc0,1      65  no output at all (depth/alpha-only)
```

**463 fragment modules write locations 0, 1 and 2** — that is the G-buffer fill
family, and it is the only fragment family that can matter here. 248 of them
carry the `|128` translucency-flag pack described below; 144 contain at least
one loop.

### 1.2 The four targets, decoded against the compute read side

Writer read out of `012f4475373618ea` (Fragment, 3 targets, 444 lines
disassembled — the smallest clean member of the family):

```
%286/%287/%288 = Sqrt(albedo.rgb)          -> SV_Target   .xyz     (loc 0)
%284           = cbv[.][0].y * 0.333333     -> SV_Target   .w
%301/%302/%303 = N*0.5 + 0.5                -> SV_Target_1 .xyz     (loc 1)
%float_0                                    -> SV_Target_1 .w
%float_0                                    -> SV_Target_2 .x       (loc 2)
%260 = cbv[.][16].x                         -> SV_Target_2 .y
%float_0_333333343                          -> SV_Target_2 .z
%319 = (uint(sqrt(sat(x*0.1))*127) | 128) * (1/255)   -> SV_Target_2 .w
```

Reader, `4d46848998312027` (GLCompute, the direct-lighting evaluator
`38` §1.1 already decoded), same four channels:

| target | attachment format (capA `gfx` scope 39/60) | writer stores | reader decodes |
|---|---|---|---|
| loc 0 | `A2B10G10R10_UNORM` 1280×720 | `sqrt(albedo)`, `.w = k/3` | `%204–%206 = c*c` (square = the sqrt's inverse), `%377 = a*3` → 2-bit enum |
| loc 1 | `A2B10G10R10_UNORM` 1280×720 | `N*0.5+0.5`, `.w = 0` | `%207–%209 = c-0.5`, normalise; `%379 = a*3` |
| loc 2 | **`R8G8B8A8_UNORM` 1280×720** | `(x, y, z, w)` as above | `%190` **metallic** (`%372 = %190 < 0.1` — the skin gate `94` §4.1 quotes); `%191` **roughness** (`%220 = NMax(%191, 0.04)`); `%192*255 → %376`, `%381 = %376 << 2`, `%382 = %381 \| uint(gbuf1.a*3)` = **the 10-bit octahedral normal hi-bits** of `94` §1.3's class-3 decode; `%193*255 → %226`, `%227 = %226 & 128`, `%304 = %226 & 63` = **translucency flag + 6-bit value** |
| loc 3 | `R16G16B16A16_SFLOAT` | `(cur/w − prev/w)*0.5, *−0.5, *1000, 1.0` — **velocity**, 187/187 modules write `.w = 1.0` | (motion vectors) |

Every channel is accounted for. **There is no material byte in the G-buffer
fill output.**

### 1.3 Where the material byte actually is, and how it is read

The material byte is component **1 of a `v4uint` image fetch**, in 130 modules,
and it is *the same shape everywhere*:

```
%233 = OpImageFetch %v4uint %58 %234 Lod %uint_0      ; 667c55bd (Fragment)
%235 = OpCompositeExtract %uint %233 1
%246 = OpShiftRightLogical %uint %235 %uint_5         ; class,   3 bits
%247 = OpBitwiseAnd        %uint %235 %uint_31        ; subtype, 5 bits

%194 = OpImageFetch %v4uint %57 %195 Lod %uint_0      ; 4d46 (GLCompute)
%196 = OpCompositeExtract %uint %194 1
%203 = OpShiftRightLogical %uint %196 %uint_5

%439 = OpImageFetch %v4uint %438 %440 Lod %uint_0     ; 1271d381 rgs_reference_main
%441 = OpCompositeExtract %uint %439 1
%442 = OpShiftRightLogical %uint %441 %uint_5
```

This **confirms `38` §1.3's read side exactly**, and extends it: the packing is
`byte = class<<5 | subtype`, and **only component 1 of that image is ever
read** — in 130/130 modules, no other component of the material fetch is
extracted at all.

The image itself, resolved through `dev/prov_map.py` on `capA_prov.jsonl`:

- compute reaches it at **`registers[2] + 4` = heap 83534** (`4d46`),
  `= 0x1c855880`, **1280×720 `R8G8B8A8_UNORM`, `usage = 23`**
  (`TRANSFER_SRC|DST|SAMPLED|COLOR_ATTACHMENT` — **no `STORAGE` bit**);
- the reference raygen reaches it at **`registers[1] + 5`** in *its* root
  signature (`%434–%438` in `1271d381`);
- `prov_map --image 0x1c855880` → **writers: (none)**, readers: 9 compute
  modules. No `STORAGE` usage bit means no compute shader *can* write it.

So it is a **raster-produced colour attachment**, distinct from the G-buffer's
own `R8G8B8A8_UNORM` (`registers[1]+4` = heap 83529 = `0x1c843b00`, the
metal/rough target of §1.2). The byte is written as a UNORM8, i.e. the writer
stores `float = materialByte/255` and the readers view the same memory through
an integer image.

### 1.4 Three falsifications, so nobody re-runs them

- **No fragment module composes the byte.** `OpShiftLeftLogical` by 5 occurs in
  **293 RayGeneration and 184 GLCompute** instructions and in **zero Fragment**
  instructions across the whole dump. The class is never assembled in a
  fragment shader.
- **No fragment module writes it as a literal.** Scanning every store of a
  float constant into a fragment output for values `k/255` with a plausible
  `(class, subtype)` decode returns only `85` (= `.z`, the normal hi-bits,
  343 modules) and `255` (= alpha 1.0). Nothing that decodes to a live class.
- **No fragment module passes it through from a CBV into a plausible slot.**
  Of the 463 G-buffer-fill modules, the only raw-CBV-component stores are
  `loc2.comp0` (28 modules) and `loc2.comp1` (22) — i.e. constant metalness and
  constant roughness, which §1.2 already names. Single-output fragment modules
  with the shape "`.y` from a CBV, other channels constant" — the shape a
  material-ID-only pass would have — number **0**.

### 1.5 The open item, stated plainly

**The producer of the material-ID image is not identified.** In
`capA_gfx.jsonl` the G-buffer pass is 15 rendering scopes at 1280×720 with
attachments `{A2B10G10R10, A2B10G10R10, R8G8B8A8_UNORM}` (+`R16G16B16A16_SFLOAT`
in 3 of them) and **964 draws**; that pass writes `0x4e2ff120`, the metal/rough
target. The only other 1280×720 `R8G8B8A8_UNORM usage=23` images in that log
are `0x4e310ea0` (one full-screen `CLEAR`+1-draw scope) and `0x4b65ba60`
(**never an attachment in any logged scope**). So either the probe log is
incomplete for this frame, or the pass runs outside the hooked command buffers.

**Cheapest way to close it, offline, no game launch:** the probe layer has *no*
`vkCreateGraphicsPipelines` hook, so `gfxDraw` records a `pipe` handle that can
never be joined to a fragment module. Add that one hook (mirror
`xCreateRayTracingPipelinesKHR`'s `pipe_stage` record for
`VK_SHADER_STAGE_FRAGMENT_BIT`), re-run the `ngfx-replay` command in
`dev/prov_map.py`'s docstring, and the writer names itself. That is the gate
for **any** version of this feature that needs a G-buffer write — including
U3's `R8_UINT` slot (which, note, is `usage = 279`; bit `0x100` is
`FRAGMENT_SHADING_RATE_ATTACHMENT`, so §1.1's "+3" is a **VRS map**, not a free
channel — correct `38` §1.1/U3 on that point).

---

## 2. The reader census — what 2, 6 and 7 actually do

Detector (binary, whole dump, ~4 s): a module qualifies if it contains
`OpCompositeExtract %uint <OpImageFetch %v4uint …> 1` feeding an
`OpShiftRightLogical … 5`. That is the mode-independent anchor (GOTCHAS 4) and
it does not depend on any positional guess (GOTCHAS 10).

```
modules reading the material byte and deriving the class : 130
   GLCompute 83   RayGeneration 35   Fragment 12   ClosestHit 0   Miss 0   AnyHit 0
of those, also deriving the 5-bit sub-enum               :  78
```

### 2.1 Nothing tests 2, 6 or 7 — and nothing indexes on the class

| use of the class value | count |
|---|---|
| `OpIEqual` / `OpINotEqual` against a literal | literals seen: `==0` (15 modules), `==1` (95), `==3` (15), `!=3` (1), `==4` (53), `!=4` (8), `==5` (10), `!=5` (2) |
| `OpSwitch` selector | 236 switch sites in 113 modules; case literals only ever drawn from `{0,1,3,4,5}` |
| `OpULessThan` / `UGreaterThan` / … (range compare) | **0** |
| `OpAccessChain` index (array lookup) | **0** |
| `OpIAdd` / `OpIMul` (arithmetic) | **0** |
| `OpReorderThreadWithHintNV` | **0** in the dump — the dump declares no SER anywhere (`38` §0b). `88`'s "the SER permutations feed the class to `OpReorderThreadWithHintNV`" describes *patched* builds, not dumped ones. |

So a value of 2, 6 or 7 is never matched by a comparison and never escapes into
an index. That half of the brief's premise holds.

### 2.2 But "default" is not "the class-0 path" — the table

**Every one of the 236 class switches has `default == the OpSelectionMerge
label`.** There is no shared "unknown material" arm anywhere; the default edge
jumps straight to the merge. What happens at 2/6/7 therefore depends entirely
on whether `case 0` exists and on what the merge phis take on that edge:

| structure | switch sites | modules | what class 2/6/7 does | safe? |
|---|---|---|---|---|
| switch has **no `case 0`** (e.g. cases `{1,3,4}`, `{1,4}`, `{3,4}`) | 144 (98 compute, 38 raygen, 8 fragment) | — | takes the default edge, **which is exactly the edge class 0 takes**; bit-identical to class 0 | **YES** |
| switch has `case 0`, merge phis take **constant 0.0** on the default edge | 54 | **54 GLCompute** (22 of them carry the `5.55472994` SG-Fresnel BRDF constant, i.e. they are lighting evaluators) | the whole switch body is skipped and every phi it feeds becomes **0.0** — for `4d46` that is six floats (an RGB diffuse + RGB specular accumulation). **The surface goes black for that lighting group.** | **NO — hard hazard** |
| switch has `case 0`, merge phis take **live values** on the default edge | 42 | GLCompute (overlaps the row above; a module can carry both kinds) | pass-through: the class-specific work is skipped, the pre-switch value survives | yes |
| switch has `case 0`, mixed constants + one zero | 8 | 8 Fragment | one channel zeroed, two constants; fragment-stage only | needs a look before use |
| **compare-only**, no switch (`==0`, `==1`) | — | **11 RayGeneration** (incl. all `rgs_reference_main` permutations) + 2 GLCompute + 4 Fragment | every test is false, so: not skin (`%449 = class==1`, with `metallic<0.1`), not hair (`%1051 = %851==4`), **and not class 0 at `%564`** — which gates the fitted multi-scatter energy polynomial at `%12373` (`3.82901`, `−11.0303`, `16.9099`, `4.11117983`, `−1.37886`, …). A dead class therefore **loses the class-0 energy term** in the reference raygen. Small, but it is a real difference and it must be pre-registered as such. | mostly, with that caveat |

Module-level roll-up:

```
54 GLCompute   carry at least one ZERO-on-default class switch   <- the hazard set
27 GLCompute   only no-case-0 switches                            safe
24 RayGeneration only no-case-0 switches                          safe
11 RayGeneration compare-only (the reference/ReSTIR raygens)      safe except the %564 term
 8 Fragment    mixed-default switches                             inspect before use
 4 Fragment / 2 GLCompute  compare-only                           safe
```

The 54-module hazard set (first names, for the patcher):
`03dc7a51…, 05511714f20081b4, 0ac15b47…, 0fb477db…, 187aa01f…, 1aeaf592…,
1b4736f6…, 20e6c7b3…, 4d46848998312027, 7ae88cd87950a898, 9a3fa53c…,
d5166c0f…` (full list reproducible from the §2 detector).

**Consequence for the brief.** "Write a dead class and PT-side evaluators gate
on it" is not a fragment-only change. It is a fragment change **plus** a
co-patch of 54 compute modules, or the material renders black under direct
light. `81` already patches 457 sites in that family, so the co-patch is known
work — but it must be costed, not assumed.

### 2.3 Class 3 — the known hazard, quantified

`94` §1.3 is confirmed: class 3 is the 10-bit octahedral normal-decode switch,
and it is tested by 15 modules with `==3` plus every `{1,3,4}` switch. Nothing
we write as 2/6/7 can reach it. **It is a hazard only in the other direction**:
if a material template's authored class happens to be 3 (smooth normals), then
overwriting it with 6 would destroy that pixel's normal precision. Any
class-overwrite build must therefore read the class it is replacing, and refuse
to overwrite 3 — which is another argument for §4.1's PT-side synthesis, where
the original class is still in a register.

---

## 3. Car-paint fragment modules — candidates and confidence

### 3.1 Is there a capture with a car in frame? **No, and none can be shown.**

Two `.ngfx-capture` files exist in `GraphicsCaptures/`
(`GameThread_2026_08_23_22_24_36`, `…_22_25_05`, 4.2 GB each). Neither carries
object debug names: `capA_objects.json` and `capA_functions.txt` contain **zero
matches** for `vehicle|carpaint|quadra|archer|thorton|villefort|mizutani|
herrera|makigai|delamain`. `57` §5 records the only probe frame ever shot as
*"One scene, four characters, daylight exterior… no car paint, no road"*, and
`94` §5 states plainly that nobody has ever pointed a material probe at a car.
**Nothing offline can name a car-paint module.**

### 3.2 Structural candidates, and how weak they are

OpNames are stripped, so the only handles are shape. Over the 463 G-buffer-fill
modules, texture-sample counts and loop counts cluster hard:

| family | modules | samples | loops | reading |
|---|---|---|---|---|
| A | 4 (`70d1c413…`, `a009f54c…`, `cee0146f…`, `7cb69b24…`) | **300–301** | 0 | fully unrolled mega-blend; terrain or a 20-layer material |
| B | 6 (`b50689f3…`, `9eaa835b…`, `84763b9a…`, `1531eaee…`, `5b7dbe73…`, `462f9cee…`, `525df422…`, `354defe0…`) | 66–67 | **2** | **the multilayered candidate** — a mask sample plus a per-layer loop is exactly `multilayered.mt`'s shape, which is what vehicle body paint is authored in |
| C | ~8 (`c1358a70…`, `f2e98fa5…`, `a4b6fe56…`, `4ad6e8a3…`, `429fd8cf…`, `3b5e2cf1…`, `fd91e5b3…`, `6c442f7b…`) | 47 | 3 | second multilayer tier |
| bulk | 187 modules | 5–10 | 0 | ordinary single-layer PBR |

The pairing inside each family (`…outs=[0,1,2,3]` vs `…outs=[0,1,2]`) is the
with-velocity / without-velocity permutation of one shader, which is a useful
integrity check for any patcher: **family B is 6 modules in 3 pairs.**

**Confidence that family B is car paint: low.** `multilayered` is also used for
walls, signage, weapons and clothing. The honest statement is that family B is
the *smallest nameable family whose shape matches a multi-layer metal-flake
material*, and that only a launch can confirm it. This is why §5's rung B
exists.

---

## 4. Two channels that are open today, and the probe

### 4.1 The route that needs no fragment write at all — recommended

The class does not have to come from the G-buffer. Every reader computes it as
`cls = byte >> 5` and every reader that matters also has metallic and roughness
in scope at that point (§1.2 shows they are `+4.x` and `+4.y` of the same
G-buffer, fetched a few instructions away; `94` §3.2 shows metallic and
roughness are site-locally recoverable in the raygen too). So:

```
cls' = OpSelect( class==0 && metallic >= 0.50 && roughness <= 0.35, 6, cls )
```

spliced **immediately after the existing `OpShiftRightLogical … 5`**, with
`replace_all_uses(cls -> cls')` — one `replace_all_uses` per class id, per
`31` §4.1's rule.

Why this is strictly better than the fragment write:

- **It cannot black anything out.** We choose which readers see the 6, so the
  54-module hazard set of §2.2 simply is not patched, and those modules keep
  seeing class 0.
- **It cannot destroy class 3.** The gate tests `class==0` first, so a
  smooth-normal material keeps its decode.
- **It is one instruction pair at a site this repo already patches**, in the
  same modules `81` and `94` name, and it costs one launch.
- It reproduces `94` §4.1's gate exactly — `m>=0.5 && r<=0.35`, with the same
  known false positives (chrome, polished signage, mirror cyberware) and the
  same honest caveat that `m_min`/`r_max` are guesses until a probe measures
  them.

Its limit, stated: the synthesised class is **not persistent**. It cannot be
seen by a shader we do not patch, it cannot survive into a denoiser guide, and
it can only express identities recoverable from `(class, metallic, roughness)`.
For car paint that is enough. For "a genuinely new material identity authored
per template", it is not — and that is what §4.2 is for.

### 4.2 The persistent channel is the sub-enum, not a dead class

If a *persistent* per-pixel identity is wanted, the right field is the **5-bit
sub-enum**, not the 3-bit class:

- values tested anywhere in the dump: `{12,13,14,15,17,21,25,26,30,31}` — so
  **21 of 32 values are unused**;
- `80` §2.1 established that **no shader tests any subtype under class 0**, so
  writing a subtype into a class-0 material byte is inert to every existing
  reader **while leaving the class — and therefore all 236 switches — exactly
  where it was**. No black surfaces, no class-3 damage;
- 78 of the 130 readers already derive `& 31`, so reading it back costs
  nothing new (`38` §1.3, `57`).

This is the channel the brief was reaching for. It has the same blocker: it
needs the write site of §1.5. **Re-verify `80` §2.1 before building on it** —
this document did not re-derive it, and a single ungated `sub == 21` test would
sink it.

### 4.3 The G-U2 probe — the smallest fragment patch that proves execution

`36` gate G1 / `38` gate G-U2 has never been run: **1304 fragment modules are
dumped and zero have ever been swapped** (`79` §6, re-measured here). The probe
below answers it and nothing else, which is the point.

**Rung `fragtint` — the gate.** In all **463** G-buffer-fill modules, multiply
the three values stored to `loc0.xyz` by a constant:

```
; 012f4475373618ea, the nameable exemplar (444 lines, one basic block of stores)
%286 = OpExtInst %float %103 Sqrt %251      ; existing
%N0  = OpFMul %float %286 %k_r              ; inserted, k = (1.15, 0.85, 0.85)
       OpStore %321 %N0                     ; rewritten (was OpStore %321 %286)
```

- Site rule: for each module, the three `OpStore` whose pointer is
  `OpAccessChain %_ptr_Output_float %<Output var at Location 0> %uint_{0,1,2}`.
  **3 rewrites per module or the module is declined by name** — a module count
  that differs from the ladder's is a finding (GOTCHAS).
- The tint is **multiplicative on albedo before the sqrt-encode**, so it is a
  pure albedo shift: it cannot introduce a NaN, cannot change alpha, cannot
  change the normal, and cannot change the material target. Choose it warm and
  strong (+15%/−15%/−15%) so it is unmistakable on a screenshot, per GOTCHAS'
  "build a control that must be **visible**".
- **Control: `k = 1.0` must rebuild byte-identical to vanilla, 463/463.** That
  is the only step that tests the identification.
- `spirv-val` at `vulkan1.3` on all 463.

Outcomes:

| what the frame shows | reading |
|---|---|
| the world is warm-tinted (sky/UI/particles unaffected — they are not in the 463) | **G-U2 PASSES.** Fragment splices execute. Everything in `38` Tier B unblocks. |
| nothing changes, and the layer log shows 463 `"swap":"HIT"` | fragment modules are created but the pipelines using them are not the ones drawing — check §5's log fields before concluding anything |
| nothing changes and the log shows few or no HITs | the id key is wrong for fragment modules (they dump as `<hash>.dxil.spv`, so the swap file must be `<hash>.dxil.spv`); fix the naming, not the patch |
| the game fails to start / black screen | pipeline creation rejected the module — §5 |

**Rung `fragtint-mlx` — the identification, same launch is not possible, second
launch.** The same tint restricted to family B's 6 modules (§3.2), tinted a
different hue. If family B is car paint, the car changes colour and nothing
else does. A null here is **not** informative unless `fragtint` passed first —
which is exactly why the two rungs are ordered and not merged.

**The class-6 round trip cannot be built yet.** The brief's second rung —
"additionally write class 6, plus a PT-side paint that fires on class 6, so one
launch proves both the fragment write and the round trip" — requires the write
site of §1.5, which this milestone falsified in the G-buffer fill and did not
find elsewhere. Saying otherwise would be inventing a site. **The equivalent
one-launch round-trip proof that *is* buildable today is §4.1's PT-side
synthesis plus a magenta paint on `cls' == 6`** — it proves the gate, the
metallic/roughness thresholds and the new-class dispatch in one frame, and it
leaves only "does the identity persist across shaders" for the fragment work
later.

---

## 5. Cost and risk: fragment swaps under vkd3d-proton

### 5.1 What the layer hooks today

From `swap_layer.c` (1489 lines):

| hook | present | what it does |
|---|---|---|
| `vkCreateShaderModule` | **yes**, `xCreateShaderModule` :1060 | **stage-agnostic.** It scans the incoming SPIR-V for the DXIL id (`scan_dxil_id`), then `load_swap(id)` → `<overlay>/<id>.spv`, falling back to `sha256-<hex>.spv`. It has no idea whether the module is a fragment shader, and no code path excludes one. **A fragment swap will be served today, unmodified.** |
| `vkCreateRayTracingPipelinesKHR` | yes :1194 | logs `pipe_stage` per stage and the raygen↔pipeline table used by `trace_rays` |
| `vkCreateComputePipelines` | yes | logs module↔pipeline |
| **`vkCreateGraphicsPipelines`** | **NO** | not in `g_dev_procs`, not in `xGetDeviceProcAddr`. **This is the single most important operational fact in this section.** |

Consequences of the missing graphics hook:

1. **A fragment swap that makes pipeline creation fail is invisible.** For RT,
   the layer refuses a SER-declaring module *because* it knows the failure would
   otherwise surface as "black screen with no obvious cause" (`swap_layer.c`
   :1133). For graphics there is no such safety net and no log line: vkd3d-proton
   will get a `VK_ERROR_*` from `vkCreateGraphicsPipelines` and the draw will be
   dropped or the device lost, with nothing in `callisto_swap.jsonl` naming the
   module.
2. **"Loaded" cannot be upgraded to "bound".** The RT track can say *this
   raygen is in this pipeline* and, via `trace_rays`, *this pipeline was
   dispatched*. For fragment there is neither. A `fragtint` null therefore has
   one fewer escape hatch closed than `56` had, and the doc for it must say so.
3. Adding the hook is small and is the same edit §1.5 needs. **Do it before the
   probe if the budget allows; it converts a null result from ambiguous to
   diagnostic.**

### 5.2 Failure modes to expect, ranked

| failure | why it bites fragment specifically | mitigation |
|---|---|---|
| **Interface mismatch** — a rewritten module changes the set of `Input`/`Output` variables or their `Location` decorations | graphics pipelines validate the VS→FS interface; RT and compute have no such stage linkage, so this class of failure has never been seen in this repo | the `fragtint` patch adds only `OpFMul` and rewrites `OpStore` operands. **It must not add, remove or re-decorate any `OpVariable`.** Assert `Input`/`Output` variable count and every `Location` unchanged, per module, from the emitted bytes |
| **Pipeline cache mismatch** | vkd3d-proton hands a `VkPipelineCache`; a changed module changes the hash and forces a recompile of every PSO using it. 463 modules × their PSO permutations is a real stutter, and GOTCHAS ("Materializing a swap set with plain `cp` evicts the shader cache every launch") already documents this class of pain | expect a long first-frame hitch on the probe launch; do not read it as a bug. Deploy via `make install`, then `cmp` (GOTCHAS) |
| **`spirv-val` clean, driver rejects** | dxil-spirv emits SPIR-V 1.3 with `SPV_NV_raw_access_chains` and `SPV_EXT_descriptor_indexing`; a hand-spliced instruction that is legal in isolation can still trip the graphics-specific validation rules the RT path never exercises | `spirv-val --target-env vulkan1.3` on 463/463 **and** read back the emitted instructions by hand for the exemplar (`39` §3.4: reading back what was emitted proves the build, never the picture) |
| **Helper-invocation / demote interaction** | several G-buffer-fill modules carry `OpDemoteToHelperInvocation` (e.g. `6530c807e3f7b676`) | the tint is downstream of every demote and touches no derivative; nothing to do, but do not splice *above* a demote in a later rung |
| **Early-Z / `OpExecutionMode`** | untouched by this patch | assert `OpExecutionMode` list unchanged |

### 5.3 What to check in the layer log

`~/callisto_swap.jsonl` (and `status.txt`), before reading any pixel:

- `"ev":"overlay"` + `"ev":"overlay_manifest"` — the rung is actually mounted;
- `"ev":"swap_load","file":"…/<hash>.dxil.spv"` — **463 of these**, one per
  patched module; a short count names the modules that were never created this
  session, which is a finding, not a failure;
- `"ev":"module", … "swap":"HIT","result":0` — served and accepted by
  `vkCreateShaderModule`. `"swap":"hit_failed"` with a non-zero `result` is the
  module being rejected at creation and is the first thing to look for;
- `"ev":"swap_bad"` — magic/size guard tripped, i.e. the patcher wrote a broken
  file;
- **absence of any `pipe_stage` record for fragment is expected**, not a
  symptom — there is no graphics hook (§5.1).

### 5.4 Cost

`fragtint` is 3 `OpFMul` + 3 rewritten store operands per module, ~12 words of
SPIR-V. Zero measurable ALU cost. The real cost is the **PSO recompile storm**
of §5.2 and the fact that 463 modules is the largest swap set this repo has ever
mounted (the current record is 93 in the cavity ladder). Build it as a normal
overlay so it can be dropped without touching the standing profile.

---

## 6. What this document did NOT establish

- The **writer of the material-ID image** (§1.5). Everything that needs a
  persistent new identity is blocked on it.
- Whether **`80` §2.1 still holds** (no subtype tested under class 0) at 3290
  modules. §4.2 rests on it and did not re-derive it.
- Whether family B (§3.2) is car paint. **Low confidence, one launch away.**
- Whether the 8 mixed-default **Fragment** readers of §2.2 matter — they were
  counted, not read.
- Any **frame-time** number. `45` §E9 is the protocol; nothing here was timed.

## 7. Recommended order

1. **Add the `vkCreateGraphicsPipelines` hook** (offline, no launch). It closes
   §1.5 and makes every later fragment result readable.
2. **§4.1's PT-side class synthesis + a class-6 paint** — one launch, proves
   the new-class dispatch and measures `m_min`/`r_max` on a real car. This is
   the cheapest thing on the list and it does not depend on 1.
3. **`fragtint`** — one launch, answers G-U2 for the repo.
4. Only then, if a persistent identity is still wanted, §4.2 at the write site
   that step 1 named.
