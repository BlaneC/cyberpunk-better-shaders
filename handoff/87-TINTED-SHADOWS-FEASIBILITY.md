# 87 — Coloured translucent shadows (a red visor tinting the shadow on the face): feasibility (2026-09-01)

**Audit only. Nothing was built, nothing was patched, no patcher was run, no
launch. Nothing is on screen and nothing about this document changes what is
served.** Everything below is read off the shipping exe's string table, the
dumped SPIR-V in `~/callisto_dump`, the committed disassemblies in
`dev/disasm/`, and the last launch in `~/callisto_swap.jsonl`.

## 0. Verdict — **rung (iii): DEAD**, and not for the reason the brief guessed

The task offered three rungs. The answer is (iii) — **scalar end to end** —
but the failure is *not* "transparent geometry is skipped by ray flags". It is
not skipped. A shadow ray reaches an alpha-tested visor, an any-hit shader runs
on it and samples its alpha map. What kills the feature is that **every stage
of the chain after that point carries exactly one number**, and the two places
where a second number would have to be created are host-side resource and
denoiser-instance decisions that a `vkCreateShaderModule` swap layer cannot
reach at all.

Three decisive facts, each with bytes:

1. **The engine instantiates the SCALAR SIGMA, and the exe strings prove
   nothing.** `SIGMA_SHADOW_TRANSLUCENCY` is in the exe — and so is the entire
   NRD catalogue: **17** all-caps denoiser identifiers including
   `REBLUR_DIFFUSE_SH`, `REBLUR_DIFFUSE_SPECULAR_OCCLUSION`, `RELAX_*` and
   `SPECULAR_DELTA_MV`, and **36** `IN_*`/`OUT_*` resource names including
   `IN_DIFF_SH0` and `OUT_DELTA_MV`. That is NRD's static name table, linked
   whole. `29` §B6 read the string as evidence of the chain that runs; that
   claim does not survive this pass (§5).
2. **The producer writes a two-channel NRD `IN_SHADOWDATA`, not a four-channel
   `IN_SHADOW_TRANSLUCENCY`** (§2.3), and **the running denoiser is
   `SIGMA_Shadow_ClassifyTiles` reading one image and two components** (§3).
3. **The shadow ray payload is `OpTypeStruct { float }` in all 13
   permutations, the any-hit stores nothing into it, and the miss shader writes
   a single sentinel** (§2.2). There is no channel for a colour to ride home in,
   and widening the payload means editing shaders in a pipeline *library* the
   layer cannot even attribute.

The one encouraging fact, recorded so it is not lost: **the consumer already
multiplies the scalar shadow into three colour channels at four sites**
(§4.2). If a per-channel shadow ever existed, splicing it in is three
instructions per site. Nothing produces one.

---

## 1. Engine surface first (`GOTCHAS` 8)

`Cyberpunk2077.exe`, 59,945,608 B, 2026-08-20, `strings -n 5` → 177,049 lines.
Method as `16`/`20` §3.

### 1.1 What is there, and why it is worthless as evidence

| pattern | hits | reading |
|---|---|---|
| `SIGMA` | 26 | both variants' full pass lists: `SIGMA_Shadow_{ClassifyTiles,SmoothTiles,Blur,PostBlur,TemporalStabilization,SplitScreen}.cs` **and** `SIGMA_ShadowTranslucency_*.cs`, plus the ids `SIGMA_SHADOW` and `SIGMA_SHADOW_TRANSLUCENCY` |
| `^(REBLUR\|RELAX\|SIGMA\|SPECULAR)_[A-Z_]+$` | **17** | the whole NRD `Denoiser` enum, including SH and directional-occlusion variants this game certainly does not run |
| `^(IN\|OUT)_` | **36** | the whole NRD `ResourceType` enum: `IN_SHADOWDATA`, `IN_SHADOW_TRANSLUCENCY`, `OUT_SHADOW_TRANSLUCENCY`, and also `IN_DIFF_SH0/SH1`, `OUT_DELTA_MV`, `OUT_VALIDATION` |
| `Translucen` | 17 | 8 are NRD's table; the rest are `29` §A1's **raster** skin subsystem (`renderstage_skin_translucency`, `CRenderNode_RenderSkinBackDepthForTranslucency`, `EMM_SurfaceTranslucency`, `CharacterSubsurfaceTranslucency`) |

**A library that ships a name table gives you every name.** `GOTCHAS` 1 in its
purest form: the string is a constant, not a dispatch. §3 answers the question
the string cannot.

### 1.2 The CVar audit: there is no knob, and the negative is structured

- `Editor/Denoising/` has exactly these subgroups: `NRD`, `ReBLUR`,
  `ReBLUR/AmbientOcclusion`, `ReBLUR/Direct`, `ReBLUR/Indirect`,
  `ReLAX/Direct/{Common,Diffuse,Specular}`,
  `ReLAX/Indirect/{Common,Diffuse,Specular}`.
  **There is no `Editor/Denoising/SIGMA` group at all.** The shadow denoiser
  is not tunable from the console, let alone switchable between variants.
- `ShadowColor` → one hit, `m_shadowColor`, at `:152708`, wedged between
  `m_fontSize` (`:152707`) and `engine\ink\fonts\arial.inkfontfamily`
  (`:152709`), under `Ink Typography`. **UI text drop-shadow.** Not a lighting
  term. Whoever greps this next: stop there.
- Zero hits, case-insensitive: `penumbra`, `softshadow`, `coloredshadow`,
  `shadowtint`/`tintshadow`, `transmittance`, `shadowalpha`, `alphashadow`.
- `CRenderNode_MarkTransparentShadow` exists — a **raster** node. The RT
  analogue is `rgs_shadow_transparent_main`, and it is scalar (§2.4).
- The `Shadow*` CVar surface is the LOD/bias/quality set `25` §5 already
  inventoried (`ForceShadowLODBias*`, `ShadowMeshQuality`,
  `EmissiveShadowRayOffset`, `ShadowFadeFraction`, `RayTracing/LocalShadow/*`).
  Nothing colour-valued.

**Engine-side answer: nothing. There is no CVar path to this feature.**

---

## 2. Shadow raygen census (read-only, dumped bytes)

### 2.1 The family

`~/callisto_dump` (3,290 files) carries **13 `rgs_shadow_main` + 1
`rgs_shadow_transparent_main`**. Disassemblies for the 13 are committed in
`dev/disasm/shadow/`; the transparent one was disassembled to scratch for this
pass and is 317 lines.

Twelve of the thirteen trace. `b88183eb6b485ef9` traces nothing, declares no
payload, and ends by packing a 24-byte reservoir record through
`OpRawAccessChainNV` (`:1240-1250`) — an RTXDI reservoir writer wearing the
family's name. (Consistent with `05`, which found no Disney anchor in it, and
with `29` §B2, which found no `>>5` in it.)

Live in the most recent launch — five shadow pipelines traced, by
`pipe_stage` + `trace_rays` join over `~/callisto_swap.jsonl` (last
`log_open`, seq 5207-7793): **`94e675a5` (whose pipeline carries both
`rgs_shadow_main` and `rgs_shadow_transparent_main`), `b2164534`,
`1ddeee1d`, `cdceb472`, `ebd5818b`**, alongside 4 `rgs_restirgi_spatiotemporal`,
4 `rgs_reference_main` and 1 `rgs_reflection_transparent_main`.

### 2.2 The payload is one float, and nothing on the hit path widens it

| module | payload | trace flags | cullMask |
|---|---|---|---|
| 11 of 13 | `%_ = OpTypeStruct %float` | `%uint_28` | `OpSelect(86, 38)` |
| `281c46c2` | `%_ = OpTypeStruct %float` | `%uint_16` | `OpSelect(8, …)` |
| `94e675a5` `rgs_shadow_main` | `%_ = OpTypeStruct %float` | `OpSelect(28, 16)` | `OpSelect(84, 36)` |
| `94e675a5` `rgs_shadow_transparent_main` | `%_ = OpTypeStruct %float` | `%uint_0` | `%uint_36` |
| `b88183eb` | *(none)* | *(no trace)* | — |

Every `OpInBoundsAccessChain` on a payload variable indexes `%uint_0`, in all
of them — the same proof `25` §8 ran, re-run today and still true.

**The hit shaders.** The layer logs only `pStages`, not `pLibraryInfo`, so the
shadow pipelines' log rows show `rgen` + `miss` and no hit groups; the hit
groups live in separate pipeline-library objects that the log shows with no
raygen. Attribution therefore comes from the **payload type**, which must match
across a pipeline. Four such libraries exist, and exactly one has the shadow
payload:

- `510c9f5a3d958624.{ahs_main, chs_main}` — `%_ = OpTypeStruct %float`. **This
  is the shadow hit group.**
- `37a0cf548031f3b9`, `55f6172c71799e4d` — `{ %v3float, %float, %uint }` (the
  PT/reference payload).
- `0b190a1f53c31393` — `{ %uint, %uint, %float, %float }`.

`510c9f5a.ahs_main` (568 lines) is a **binary alpha test**:

```
%324/%356/%371/%393/%408 = OpImageSampleExplicitLod …   ; up to 3 alpha maps, multiplied
%376 = OpFConvert %float %218                            ; threshold, a half from the material
%377 = OpFOrdLessThan %bool %373 %376
%378 = OpSelect %float %377 %float_0 %float_1
%186 = OpFOrdGreaterThan %bool %378 %float_0
…
%430: OpStore %41 %43 ; OpIgnoreIntersectionKHR          ; reject
%431: OpStore %41 %43 ; OpReturn                         ; accept
```

and **`%43 = OpLoad %float %41` at `:197`** — it loads the payload and writes
the same value back in *both* arms. The any-hit contributes a boolean and
nothing else. It has the visor's alpha in a register and throws it away.

`510c9f5a.chs_main` (124 lines) stores `%39 = OpLoad %float %38` where `%38` is
decorated `BuiltIn RayTmaxKHR` (`:60`): the payload receives the hit
**distance**, full stop. The miss shaders write one sentinel —
`94e675a5.ms_shadow_main` stores `%float_10000`, `b80f16ff.ms_shadow_main`
stores `%float_3.40282347e+38`.

So: transparent geometry is **not** skipped. It is seen, alpha-tested, and
collapsed to occluded/not-occluded at the hit.

### 2.3 What the raygen writes: NRD's *scalar* front-end pack

`dev/disasm/shadow/94e675a5f27e1c3b.rgs_shadow_main.spvasm`, the two output
arms:

```
:689  %489 = OpFMul %float %238 %float_0_125          ; viewZ * NRD_FP16_VIEWZ_SCALE
:691  %491 = OpExtInst NMax %489 %float_n65504
:693  %493 = OpExtInst NMin %491 %float_65504         ; NRD_PackViewZ
…
:697  %542 = OpCompositeConstruct %v4float %float_0 %493 %float_0 %493   ; early-out arm
:766  %628 = OpCompositeConstruct %v4float %621 %493 %621 %493
:768        OpImageWrite %626 %627 %628
```

`%621` is the penumbra hit distance, or `%float_65504` when nothing occluded.
The `(a, b, a, b)` shape is **DXC's duplicate-fill for a two-component UAV** —
a `RWTexture2D<float2>` store emits four operands. This is
`NRD_FrontEnd_PackShadow`'s **two-argument** result: `IN_SHADOWDATA`.

The translucency overload of the same NRD function produces a *second*,
four-channel output (`x` = shadow, `yzw` = translucency) into a *second*
resource. **No module in the family writes one.** The other writes in the
family are `(a,b,a,a)` splats at other heap slots (`ef3cbee1:54641`,
`ebd5818b:61998`, `1ddeee1d:63109`) or ReSTIR radiance/reservoir targets
(`1ddeee1d:63060/63068`, `cdceb472:8351`, `b2164534:29166`, which writes
`OpBitcast %v4int` into an integer image — the shape `46` §12 warns about).

### 2.4 The transparent shadow pass is scalar too

`rgs_shadow_transparent_main` is the closest thing the engine has to the asked
feature, and it is worth stating exactly what it does, because it looks like a
lead and is not:

```
:280        OpStore %192 %float_0                     ; payload := 0
:292        OpTraceRayKHR %205 %uint_0 %uint_36 %uint_0 %uint_1 %uint_0 %207 %float_0 %208 %197 %42
:294  %210 = OpFAdd %float %209 %float_n200
:298  %215 = OpFMul %float %214 %210
:299  %216 = OpExtInst NClamp %215 %float_0 %float_1
:310  %228 = OpCompositeConstruct %v4float %216 %216 %216 %216
:311        OpImageWrite %226 %227 %228
```

Flags `0` — so the closest-hit *does* run and returns `RayTmax`. Origin is
`P + L·200` firing back along `-L` (a from-the-light trace), `tMax =
cbv[73].x + 200`. The output image is `%25 = OpTypeImage %float 2D 0 1 0 2` —
a **2D array**, sliced by `%220 = bitcast(cbv[63]).x` (a light index) — and the
value is a **scalar splatted four ways**, DXC's fill for a one-component
target. One number per light per pixel. The engine models "how much light gets
past the transparent thing", never "what colour".

---

## 3. The denoiser that actually runs: `SIGMA_SHADOW`, proven by dispatch

Selected by dispatch (`GOTCHAS` 1), not by name. Joining `trace_rays` to the
dispatches that follow it in the last launch (seq 7793 → 7810), the shadow
trace is followed by `77bf9400390b5790` `[7,4,1]`, `0149eafeb16699e5`
`[107,60,1]`, `e5daef173304114a` `[7,4,1]`, then a run of `[107,60,1]` and
`[214,120,1]` passes.

**`0149eafeb16699e5` is NRD `SIGMA_Shadow_ClassifyTiles`.** The identification
is byte-level, not by name:

```
:150  %75 = OpImageFetch %v4float %41 %77 Lod %uint_0   ; ×8 per thread, LocalSize 8 4 1 → 256 texels = one 16×16 tile
:152  %78 = OpCompositeExtract %float %75 0             ; hitDist
:153  %79 = OpCompositeExtract %float %75 1             ; packed viewZ
:154  %81 = OpExtInst FAbs %79
:155  %82 = OpFMul %float %81 %float_8                  ; ÷ NRD_FP16_VIEWZ_SCALE (0.125)
:161  %93 = OpFOrdEqual %bool %78 %float_65504          ; NRD_FP16_MAX = "no occluder"
…
:326  %326 = OpAtomicIAdd …  %328 = OpAtomicUMax …      ; 16-bit lit/shadow counters + max blur radius
:406  %346 = OpCompositeConstruct %v4float %339 %344 %339 %339
:407        OpImageWrite %35 %345 %346
```

`0.125` and `65504` are NRD's `NRD_FP16_VIEWZ_SCALE` and `NRD_FP16_MAX`, and
they are the same two constants the raygen packed with in §2.3 — producer and
consumer agree, which is what makes this the right pass and not a lookalike
(`GOTCHAS` "a reading can land on the wrong sibling").

Dispatch `[107, 60, 1]` = 107×60 tiles of 16×16 = **1712×960**, the render
resolution. `77bf9400390b5790` `[7,4,1]` (LocalSize 16×16 = 112×64 threads)
clears that 107×60 tile texture; `e5daef173304114a` `[7,4,1]` is
**`SIGMA_Shadow_SmoothTiles`** — LDS `%_arr_float_uint_648` = 18×18×2, a 3×3
`exp2`-weighted filter of the two-channel tile texture, writing
`v4float(%237,%237,%237,%237)`.

**The decisive negative: `ClassifyTiles` reads ONE image.** `%41`, eight
fetches, components `0` and `1`. NRD's translucency build of the same shader
additionally samples `IN_SHADOW_TRANSLUCENCY`. It does not.

Downstream, `8d7429d974f4afc6` and `b436c12f6d901bb7` (`[107,60,1]`, LocalSize
16×16) both write `v4float(sqrt(x), sqrt(x), sqrt(x), sqrt(x))` — scalar
splats (`:359`/`:1715`, `:341`/`:1593`). The whole chain is scalar.

---

## 4. Consumer census

### 4.1 The mask is read as `.x`, in all five evaluators

`29` §A2's anchor, swept for siblings (`GOTCHAS` 3). All five compute lighting
evaluators load the same bindless slot `heap19[registers[1] + 5]` into `%74`
(type `%16 = OpTypeImage %float 2D 0 0 0 1 Unknown`), fetch it **once**, and
take component **0** only:

| module | fetch | extract | uses of the fetch |
|---|---|---|---|
| `4d46848998312027` | `:664` | `%563 = …%561 0` | 2 |
| `2e73a32c35778d85` | `:639` | `%537 = …%535 0` | 2 |
| `7ae88cd87950a898` | `:558` | `%455 = …%453 0` | 2 |
| `81c13c37112d09df` | `:658` | `%551 = …%549 0` | 2 |
| `9a3fa53c53a3a21b` | `:673` | `%575 = …%573 0` | 2 |

"Uses = 2" is the fetch's own definition plus the extract. **Nothing anywhere
reads `.y`, `.z` or `.w` of the shadow mask.**

### 4.2 …and it is immediately multiplied into three colour channels

In `4d46848998312027`:

```
:669  %567 = OpFAdd %float %566 %563          ; cbv99[0].y + shadow
:670  %568 = OpExtInst NClamp %567 0 1
:790  %721 = OpFMul %float %568 %558          ; sun.r
:791  %722 = OpFMul %float %568 %559          ; sun.g
:792  %723 = OpFMul %float %568 %560          ; sun.b
```

and the same triple again at `:963-965`, `:1114-1116`, `:1625-1629`, plus
`%1416 = 1 − %568` (`:1587`) and `%1435 = %568 · %1159` (`:1606`).

**This is the good news and it is the only good news.** The consumer side of a
coloured shadow is a 3-instruction-per-site splice into a shape that is
already `scalar × colour`, at four sites in each of five modules, with the
class gate from `29` §B2 available. It costs nothing to keep in mind. There is
simply no per-channel value to put there.

---

## 5. Correction to `29` §B6

> "the shadow mask is denoised by NRD's `SIGMA_ShadowTranslucency` chain (the
> `SIGMA_*` strings in the exe)"

**Withdrawn.** The string is present because NRD's whole enum-name table is
linked (§1.1); the chain that dispatches is the scalar `SIGMA_SHADOW` (§3).
The rest of §B6 — that the shadow family is the worst place to spend risk
budget, and that extra samples land in a filter tuned for 1 spp — is unaffected
and this pass reinforces it.

---

## 6. Why it is dead, in one paragraph

A coloured translucent shadow needs a colour created at the occluder, carried
back to the raygen, written to a four-channel target, preserved through the
denoiser, and multiplied per-channel at the light. This renderer breaks it at
four of those five. The occluder's alpha *is* sampled — `510c9f5a.ahs_main` has
it in `%373` — and is immediately thresholded to a boolean. The payload is
`OpTypeStruct { float }`, and widening it means editing an any-hit and a
closest-hit that live in a pipeline **library** whose linkage the layer cannot
even observe, with a payload-size mismatch across stages being undefined
behaviour rather than a validation error. The raygen writes
`NRD_FrontEnd_PackShadow`'s two-channel `IN_SHADOWDATA`; a translucency build
needs a *second, four-channel resource* that does not exist and that no shader
edit can allocate. The denoiser instance is chosen host-side by an
`nrd::Denoiser` enum value — a C++ call, not a shader — and `ClassifyTiles`,
`SmoothTiles` and both blur passes are compiled for the scalar variant. And
the output would have to change format from a one-channel target to four. Three
of those are engine-side allocation and instantiation decisions. This is
`GOTCHAS` 13 one step worse than the back-depth case: there, the resource
existed and only its address was unstable; here **the resource does not exist**,
and the only thing that reopens this is an engine-side change. Closed, not
deferred. Do not re-chase it from the `SIGMA_ShadowTranslucency` string — that
string is a name in a table, and §1.1 is the proof.

---

## 7. What *is* in reach, and what would reopen this

Neither is the asked feature. Recorded so the next reader does not mistake one
for the other.

- **Cosmetic per-channel shadow tint (reachable, not occluder-derived).**
  Replace `%568` with three per-channel values derived from the same scalar at
  the four `sun.rgb` sites of §4.2 — e.g. `pow(s, k_r/k_g/k_b)`, or a lerp
  toward a constant tint as `s → 0`. Cheap, `spirv-val`-safe, identity when
  the knobs are 1, and gateable on material class 1 so only skin gets it. It
  gives *warm/cool shadows on faces*; it can never give *a red shadow because
  the thing casting it is red*, because the shader has no idea what cast it.
  It also runs in the **compute** evaluators, not in the shadow raygen family
  — so it is outside the territory where `sctrl` died, and it needs no second
  trace. If the underlying want is "faces look flat and grey in shadow", this
  is the honest cheap answer and it should be scoped as its own document.
- **What would reopen the real feature:** an engine-side switch to
  `SIGMA_SHADOW_TRANSLUCENCY` — which means CDPR, or a mod that replaces the
  render graph, not a SPIR-V swap. Nothing this project can do.

## 8. If someone approves a build anyway — the first step is NOT a patcher

Per `GOTCHAS` "verify the mechanism before building the matrix", and because
§6 says three of the five required changes are host-side, the first build step
would be a **falsification test, not a feature**: write a constant non-grey
`v4float` from the `94e675a5.rgs_shadow_main` output arm (`:766`, one
`OpCompositeConstruct` operand swap, byte-reversible) and see whether anything
downstream is even capable of carrying a second channel. If the picture is
unchanged in hue, the target is 1- or 2-channel and §6 is confirmed on screen
in one launch. That is a one-line edit to one module in the family where
`sctrl` died — it adds **no trace, no payload change and no control flow**, so
it does not re-enter `56` §4's untested territory. Nothing else should be built
before that comes back.

## 9. Evidence index

- Exe: `Cyberpunk2077.exe`, 59,945,608 B, 2026-08-20, `strings -n 5`,
  177,049 lines. Scratch: `strings5.txt` (`$SCRATCH`).
- Shadow family: `~/callisto_dump/*.rgs_shadow*.spv` (14 modules);
  disassemblies `dev/disasm/shadow/` (13, committed) + a scratch disassembly
  of `94e675a5f27e1c3b.rgs_shadow_transparent_main`.
- Hit groups: `~/callisto_dump/510c9f5a3d958624.{ahs_main,chs_main}.spv`,
  `94e675a5f27e1c3b.ms_shadow_main.spv`, `b80f16ff7123d653.ms_shadow_main.spv`.
- Denoiser: `~/callisto_dump/{0149eafeb16699e5,e5daef173304114a,
  77bf9400390b5790,8d7429d974f4afc6,b436c12f6d901bb7}.dxil.spv`.
- Consumers: `dev/disasm/compute/{4d46848998312027,2e73a32c35778d85,
  7ae88cd87950a898,81c13c37112d09df,9a3fa53c53a3a21b}.dxil.spvasm`.
- Dispatch truth: `~/callisto_swap.jsonl`, last `log_open`, `pipe_stage` +
  `trace_rays` + `dispatch` joined on `pipe`/`seq` (seq 5207-5231, 7793-7810).
