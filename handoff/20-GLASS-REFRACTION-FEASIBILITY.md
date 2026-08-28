# 20 — Glass / refraction / dispersion / caustics: feasibility

Written 2026-08-27. Investigation only — nothing was built or patched. Three
parallel audits: (1) a binary word-scan of all 3005 dumped SPIR-V modules plus
full disassembly reads of every transparent RT stage; (2) a `strings -n 6`
CVar/enum audit of the exe, mirroring `16`'s method; (3) the live dispatch
truth from `~/callisto_swap.jsonl` (pid 1097541 segment, PT confirmed on).

**Verdict, one line: true refraction does not exist in this build — not as a
shader, not as a CVar, not as a render node — so nothing can be *tuned*; but
the transparent-reflection raygen is a real, executing, per-glass-pixel pass
with a surface normal, a view vector, a Fresnel and an existing traced ray,
which makes it the one honest place to *author* a bent ray.**

**Reviewed 2026-08-28** — every claim below was re-checked against the
binaries by a second pass. The one-line verdict survives; three load-bearing
details under it did not, and are corrected in place (§1 Fresnel, §1/§5b ray
origin, §5b composite), plus one under-researched area (§3/§5a, the engine's
reflection CVar group). Corrections are marked **[corr 08-28]** where they
land and listed in the corrections log before the evidence index.

---

## 1. What the path tracer does with glass today (proven from the binaries)

**No module refracts anything.** Across all 3005 modules:

- **Zero** GLSL.std.450 `Refract` extinsts (and zero `Reflect`/`FaceForward` —
  reflection is hand-rolled dot/mul/sub).
- **Zero** IOR constants in any optics context. `1.52`/`1.333`/`2.42` appear
  nowhere; `1.33` appears in 16 modules, all Fragment-stage, each audited to a
  non-optics use (dither thresholds, AA widths); the `1.4/1.45/1.5` trio is UI
  screen-door dither; every `1.5`/`0.75` in every RT/shading module audits to
  lobe phases, LOD fades or generic scales.
- **Every ray direction in the dump is accounted for**: mirror reflect
  (reflection passes), −light dir (shadow passes), straight +Z (a light-volume
  probe), G-buffer/view vectors (reference raygen). No eta ratio, no
  `k = 1 − eta²(1−cos²)` discriminant anywhere.
- The closest-hit population has **no transmission lobe**: the 19
  `chs_main_*` permutations contain no `Exp`/`Pow` (confirming `16` §6); the
  big shading CHS (`55f6172c71799e4d.chs_main`, 172816 B) is Lambert + one
  isotropic GGX with `F0 = lerp(0.04, albedo, metallic)` — no second specular
  lobe, no `(1−F)·T` term, no thickness input.

**The glass model is: raster alpha-blend + screen-space Distortion + a traced
mirror reflection on transparent-classified pixels.** The "see through the
window but also see a reflection" the user observed is exactly this — and the
reflection half is path-traced, which is why it looked promising.

### `ee6d252e090adc74.rgs_reflection_transparent_main` — the glass pass

62436 B, one `OpImageWrite`, disasm at
`dev/disasm/shadowflags/ee6d252e090adc74.rgs_reflection_transparent_main.spvasm`
(3084 lines). Per pixel it:

- Runs **only where a transparent-gate texture says so** (`OpImageFetch` of
  `registers[2]+14`, `.x`; pass proceeds iff `0 < x < 1 && depth <= x`) —
  i.e. it is already gated to glass/transparent pixels.
- Reads depth (`registers[1]+1`) and the surface normal (`registers[5]`),
  reconstructs the camera-relative world position `P` and normalizes the view
  ray `D`. **[corr 08-28]** The traced origin (`:507-511`, fed to the trace as
  `%265`) is `P − D·ε·(1 + 9·fade)` — pulled back *toward the camera along the
  view ray*, onto the **outside** face of the glass. That sign is correct for
  a reflection and wrong for anything transmitted; see §5b.
- Hand-rolls `R = V − 2·dot(N,V)·N`, then **trace #1**: flags `16`
  (CullBackFacing), **cullMask `1`**, sbtOffset/stride 1, tmin 1e-7,
  tmax cbv-driven. On miss → env cubemap with a horizon fade. On hit → decodes
  the CHS packed payload `{RGBA8, octahedral normal, byte, distance}` and
  re-projects to screen for an **SSR fallback** with edge fade and a
  depth-consistency test.
- **[corr 08-28]** A Schlick term with `F0 = max(byte, 0.04)` — but that byte
  is **the reflected hit surface's**, not the glass's: `%643 ← %392 ←
  %390 = OpShiftRightLogical %358 24` (`:627-632`, `:932`) unpacks the top
  byte of the **CHS payload** and scales by 1/255. It is the hit point's
  specular F0, consumed by the direct-light loop that shades the hit. **There
  is no glass-interface Fresnel in this module.** An earlier draft of this
  document claimed the reflection-vs-transmission weight already existed; it
  does not, and §5b's cost estimate now carries it (cheap — the glass `N·V`
  dot is already computed at `:512`).
- A **Beer–Lambert absorption** block (`(1−2^−x)/x`, `Exp2(−x)`, ln2 and
  series-fallback constants) — colour attenuation of a through-medium term,
  not a bent ray. Closest thing to "refraction" in the dump, and it is
  absorption only.
- A direct-light loop (glass specular highlights), two sun shadow rays
  (flags `0x0C`, cullMask `7` / dynamic `0|7`), and a +Z volume-marking probe
  (flags `0x0A`, cullMask `255`).
- Writes one texel (`:3081-3082`): `RGB · 1/64` (`:3067`) clamped to
  ±65504 (fp16 range, `:3073`), and **alpha = the gate texel itself** —
  `%270` phis to `%142`, the transparent-layer depth read at `:424`, or to 0
  when the pixel fails the gate. **[corr 08-28]** So alpha is a *depth*, not a
  coverage or blend weight: this buffer hands the consumer no weight we
  control. **Its downstream consumer is still not named** — no doc identifies
  which compute/fragment pass composites it, and §5b now turns on that
  question rather than merely noting it.

### The opaque reflection siblings **[corr 08-28]**

The first draft scoped only the *transparent* name. The dump also holds
**two** `rgs_reflection_opaque_main` permutations
(`3b4479f977eba11a`, `463d8f7af99ad92b`) — RT reflections on everything that
is not glass. Both have the same three-trace shape as the transparent pass and
both trace their reflection ray with **flags 16, cullMask 1**. Nothing in
this document's refraction argument changes, but if the goal is "better
reflections" generally rather than "glass", that is the module family, and
the `cullMask` lever below applies to it identically.

Note also that the transparent raygen being *singular* while its opaque twin
ships two permutations is the AgX trap in miniature (`18`, GOTCHAS 3): the
dump is one display mode and one settings set. Re-run the sweep after any
change to reflection quality settings before believing "there is only one".

### The other transparent stage

`94e675a5f27e1c3b.rgs_shadow_transparent_main` (5644 B): one trace along the
light direction, flags `0` (CHS+AHS run), **cullMask `0x24` (36)**; the CHS
returns hit distance, the pass writes a transmittance ramp. "Transparent"
here means the anyhit shaders alpha-test and the CHS reports where the first
transparent surface is — shadowing through glass, not bending.

### Any-hit / closest-hit inventory

- 4 `ahs_main` + 1 `ahs_light_volume_main`: alpha-test via barycentric vertex
  alpha + up to 3 bindless texture alpha samples, `OpIgnoreIntersectionKHR` on
  fail. No `OpTerminateRayKHR` anywhere in the dump.
- `chs_main_1..18` write exactly the packed payload the transparent-reflection
  raygen decodes (verified field-for-field) — that hit-group family belongs to
  this pipeline.
- **Material classes** tested anywhere (`gbuf>>5 == N`): **{0, 1, 3, 4, 5}**
  only. 1 = skin, 4 = hair. No glass class is branched on in any module, and
  the exe's `ERenderMaterialType` has no glass member (`RMT_Standard,
  RMT_Foliage, RMT_Hair, RMT_Eye, RMT_Cloth, RMT_Subsurface` — that's all).
  Glass exists only as material *templates* (`glass_onesided`,
  `glass_flat_twosided`, `frosted_glass`) — asset names, not shader branches.

## 2. Are transparent surfaces in the BVH, and what can rays hit?

- **Alpha-tested (non-opaque) geometry is in the AS** — the AHS population and
  the hair shadow-leak fix prove it for hair; the transparent-shadow pass
  (flags 0, AHS+CHS active) proves it for whatever its `cullMask=0x24` admits.
- The transparent **reflection** ray traces with **cullMask = 1**: what a
  glass reflection can *see* is restricted to mask-bit-0 instances — the same
  restriction as the reference bounce ray (`17` §2). The reference visibility
  ray uses `255`; the transparent shadow ray uses `36`.
- **Which mask bits glassware itself sets is unknown and engine-side** (TLAS
  instance descriptors; the layer hooks no AS builds). For the reflection pass
  this doesn't matter — it starts *from* the glass surface found via the
  raster G-buffer gate, not by hitting glass with a ray. **[corr 08-28]** It
  matters more than the first draft allowed for a *transmitted* ray: fired
  inward from an origin that sits outside the surface (§1), such a ray meets
  the glass front face from the outside, where it is **front**-facing and so
  survives `CullBackFacing`. If glassware is in mask bit 0, a naive refracted
  trace returns the glass itself at `t ≈ ε`. The fix is to push the origin
  through the surface (`P + D·ε`) rather than to hope about mask bits.
- Exe-side OMM/instance knobs exist (`AllowOpacityMicroMaps`,
  `SkipTransparentMeshes` near `RayTracing/Collector`, `DoCull_RayTracedObjects`)
  — bools that could change what's in the AS, untested.

## 3. The engine side (exe CVar audit, `16`'s method)

Searched the full `strings -n 6` surface of the shipping exe (59.9 MB,
2026-08-20):

- **Nothing to find.** `transmis` 0 hits, `caustic` 0, `dispersion` 0,
  word-boundary `ior` 0, `Beer` 0, `Dielectric` 0, `Conductor` 0,
  `REFRACTION` 0. No `cvGlass*`/`cvRefract*`/`cvTransmis*` shader constant
  (the 70 `cv*` are exactly `16`'s inventory). No `RMT_Glass`. No
  `CRenderNode_ScreenSpaceRefractions` — refraction-style effects exist only
  as **screen Distortion** (`CRenderNode_*Distortion`, `EMM_MaskDistortion`,
  `Developer/FeatureToggles` `Distortion`), the heat-haze/underwater system.
- What does exist, all verified single-occurrence CVar-path layout:
  `Rendering/FrostedGlass` → `GlassAAQuality`, `GlassBlurQuality`;
  `RayTracing` → `EnableTransparentReflection`;
  `RayTracing/Multilayer` → `TransparentReflectionEnvironmentBlendFactor`;
  console var `disableRayTracedTransparentReflection`. The PT knob surface
  (`RayNumber`, `BounceNumber`, `RoughnessOverride`, scales…) contains nothing
  transmission-related.
- **[corr 08-28]** For *transmission* that list is complete, but the first
  draft read it as the whole reflection surface too, and it is not. There is a
  `RayTracing/Reflection` CVar group, and these names are each
  single-occurrence in the exe: **`EnableHalfResolutionTracing`,
  `TracingRadiusReflections`, `RoughnessThreshold`, `RoughnessOverride`,
  `RayNormalOffset`, `RayViewOffset`** — plus `EnableMirrorMaterialReflection`
  and `EnforceScreenSpaceReflectionsUberQuality` elsewhere. Group attribution
  is by the same single-occurrence layout argument `16` used and should be
  confirmed the same way before any is trusted. Consistent with this, the
  reflection ray's **tmax is cbv-driven** (`%254`, `:530`), so "reflections do
  not reach far enough" is probably a CVar and not a splice at all. GOTCHAS 8
  applies to the reflection half of this investigation exactly as it did to
  hair.

Contrast with hair (`16`): there the engine shipped a full BRDF as CVars and
the plan changed to use them. **For transmission the engine ships nothing —
there is no engine-side shortcut, and anything that bends light must be
built.** For *reflection* the opposite is true: the group above is a real
engine surface and should be exhausted before any reflection splice.

## 4. Where glass pixels are shaded (dispatch truth)

- The transparent-reflection pipeline **executes live**: traced in the most
  recent session (seq 5022, `pipe_stage` attribution, PT unambiguously on).
  The transparent-shadow raygen sits in a traced two-raygen pipeline (which
  SBT entry fired is not logged).
- The pass runs per-glass-pixel in **an RT raygen** and writes a colour
  buffer; consistent with `00`/`07`, the final visible composite happens in
  compute. So: glass *reflection* is authored in the raygen; glass *pixels*
  reach the screen through the same compute/graphics composite chain as
  everything else (consumer unnamed, §6).
- One **attribution gap, stated plainly**: every ahs/chs stage in the log sits
  in 4 pipelines whose raygen the layer failed to name (`rgs:""`), and none of
  those 4 was recorded as traced. Given the payload-format pairing (§1) the
  hit groups must run for the reflection pipe; the log simply can't attribute
  them. `trace_rays` remains the unreliable path (GOTCHAS); this is an
  instrumentation hole, not a negative finding.

## 5. The four buckets

**(a) Refraction that already exists and can be tuned — NONE.**
No refraction system exists at any level we can observe: no shader math, no
CVar, no render node, no material type.

What *can* be tuned today, none of which bends light: the RT
transparent-reflection (`EnableTransparentReflection`,
`TransparentReflectionEnvironmentBlendFactor`), frosted-glass AA/blur quality,
the screen-space Distortion feature toggle — and **[corr 08-28]** the
`RayTracing/Reflection` group of §3 (`TracingRadiusReflections`,
`RoughnessThreshold`, `RoughnessOverride`, `EnableHalfResolutionTracing`,
`RayNormalOffset`, `RayViewOffset`). If the ask is "better reflections", that
group plus a CET panel over it — the `hair_engine.lua` pattern, no shader
risk, live-applying — is the first thing to try, and the `cullMask 1 → 255`
edit on the reflection traces of all three raygens (one opaque pair, one
transparent; same class as the shipped shadow-flags fix, `17` §3) is the
second.

**(b) IOR / thin-vs-solid change we can splice — REACHABLE as an *added*
refracted term; "true refraction" is gated on a question we have not answered.**
There is no transmission lobe to retune, so this means *adding* a transmitted
direction where none exists. The one honest site is
`rgs_reflection_transparent_main`: it runs per glass pixel with N, V, tmax
wiring, a CHS payload decoder, an env-map miss path and an SSR fallback —
most of what a refracted ray needs. **[corr 08-28]** Two items the first draft
counted as ready are not:

- **the origin has the wrong sign** (§1): it sits outside the surface, so a
  transmitted ray must be re-based at `P + D·ε`, not reuse `%265`; and
- **there is no glass Fresnel** (§1) — `F` has to be built from the `N·V` at
  `:512`. Cheap, but not free.

**The composite is the real gate.** The buffer's alpha is the gate *depth*
(§1), so this pass hands the consumer no weight, and the consumer is unnamed.
The straight-through view of the world is produced by the raster alpha-blend,
which this module cannot reach. If the consumer *adds* this buffer — the
likely case — then writing `F·reflected + (1−F)·refracted` (with `1−F ≈ 0.96`
head-on) would delete the reflection and lay a second, offset copy of the
background over the one the raster pass already drew: **ghosting, not
warping**. Only if the consumer *replaces or lerps* per pixel can this become
refraction rather than an overlay. **Name the consumer before scoping this**
(open item 1); it needs no launch.

What that leaves as honestly reachable without the consumer answer: an
*additive* refracted term — a bent, glass-tinted contribution laid over the
existing see-through, which can read as a lensing sparkle but will not
magnify the background the way real refraction does.

**Phase 0.5 — repoint the existing ray before adding one.** The cheapest
possible test of the whole idea is a *value* splice, the exact class this repo
has shipped: replace the mirror direction `%242/%243/%244` (fed to the trace
as `%266`, `:517-538`) with a refracted direction built from N (`%131-133`),
D (`%201-203`) and a constant-folded eta, and push the origin to `P + D·ε`.
No second trace, no payload work, no new control flow; the existing CHS
decode, SSR fallback and env miss are reused wholesale. One screenshot then
answers three things at once: whether the buffer reaches glass pixels, whether
the origin self-hits, and whether a bent ray through a curved normal field
actually reads as warping. Only if that is encouraging does the two-ray
version below earn its cost.

**v1 with a second trace**, if Phase 0.5 passes: trace along the refracted
direction (`eta = 1/1.5`, thin-surface single bend), keep the reflection, and
combine them by whatever the consumer turns out to support. Mechanics the
first draft did not state:

- **No new payload variable is needed.** Four `RayPayloadKHR` variables of
  identical type already exist (`%55`–`%58`, `:189-193`) and are all in the
  `OpEntryPoint` interface list (`:29`). If a fifth is ever added it **must**
  be registered there — SPIR-V 1.4 requires every referenced global in the
  interface, and omitting it is a validation failure, not a runtime bug.
- **Ordering.** `%57`'s contents are consumed across the whole tail after the
  reflection trace at `:539`, so a second trace has to run *before* it, not
  after.
- **Miss handling must stay branch-free.** Every patcher here inserts
  straight-line code with dominance checks; none creates basic blocks. Use
  `OpSelect` on the `distance == tmax` test the shader already computes at
  `:540-541`.
- Cost: two rays per glass pixel, on a pass that may already be traced at half
  resolution (`EnableHalfResolutionTracing`, §3).

Remaining risks, unchanged: single interface only (one bend, no exit
refraction); the refracted ray sees only `cullMask=1` instances unless widened
— more visually severe than for a reflection, since it stands in for the view
*through* the glass; and everything above assumes the pass runs on the object
in question, which is what Phase 0 tests.

**(c) Wavelength-dependent dispersion — REACHABLE only behind (b).**
Three etas → three directions. The payload returns one RGB per trace, so true
dispersion wants 3 traces (or a per-channel eta jitter in one trace for a
noisier, cheaper look). Per-glass-pixel cost triples. Meaningless until (b)
exists; not blocked on anything else.

**(d) Real caustics — NOT REACHABLE by this mechanism.**
Caustics need light→glass→surface paths; this renderer traces camera-side
only, the CHS set has no transmission lobe to carry a light path through
glass even if a photon were sent, and no photon/forward pass exists in the
dump. A faked caustic (projected animated texture, decal, or a distortion-map
trick) is an asset/graphics-side mod, outside the swap layer's demonstrated
reach. Stated plainly so this doesn't get re-litigated: **caustics are out of
scope for SPIR-V splicing as this project is constituted.**

## 6. Phase 0 — the smallest diagnostic (NOT built; spec only)

**Question it answers:** can we reach glass pixels' RT contribution at all —
does the transparent-reflection pass run on the bar-glassware object, and does
a swap of its raygen land on screen?

**The marker.** `ee6d252e090adc74.rgs_reflection_transparent_main`, its single
`OpImageWrite` (disasm `:3082`): multiply the RGB by a loud constant (e.g.
`(8, 0.1, 0.1)`) and leave alpha untouched. Same shape as the repo's existing
`build_tint_writes`/`build_hunt_writes` tiers; the module is SPIR-V 1.4 (RT),
which the patchers already auto-detect. **[corr 08-28]** Two details:

- **Splice before the clamp, not after.** Multiply `%278/%280/%281`
  (`:3067-3069`) rather than `%286/%288/%289` (`:3073-3075`), so the existing
  `NMin ±65504` still bounds the result; an 8× applied after the clamp can
  push an fp16 store to `inf`.
- **Leaving alpha alone is not optional.** It is the transparent-layer *depth*
  (§1), not a coverage flag, and the consumer plausibly tests it.

**[corr 08-28] If a launch is being spent anyway, spend it on Phase 0.5**
(§5b) — the direction repoint. It is the same one-module, offline-validated
patch and the same single screenshot, it still answers everything the marker
answers (does the pass reach these pixels, does a swap land on screen), and it
additionally shows whether a bent ray reads as warping and whether the origin
self-hits. The tint marker remains the right choice only if a red sheen is
easier to adjudicate than a bent image in the scene you have.

**Sibling sweep.** Exactly **one** `rgs_reflection_transparent_main` exists in
all 3005 dumped modules (re-confirmed 2026-08-28), and the live log shows
exactly one such pipeline. But the dump is one display mode and one settings
set, and the *opaque* reflection raygen ships two permutations (§1) — so treat
the singleton as provisional, and re-scan after any reflection-settings change
before believing a patch covers the pass.

**Offline proof (before any launch).** `spirv-val` the variant; replay capA
with the swap installed (`NGFXPROBE_STRIP_ALLOC=3`, recipe in
`dev/prov_map.py`'s docstring) — the capture dispatched this pass (`04` fact
2), so the replay must show a swap HIT on its pipeline.

**Controlled scene.** Any interior bar with the glassware object (the user has
one in mind) or a large window at night, PT on. One screenshot plus a
toggle-off control.

**Pass/fail from one screenshot:**
- **PASS** — glass surfaces (windows, the bar glass) carry a red reflection
  sheen while the rest of the frame is untouched. Proves: the pass runs on
  those pixels, the gate classifies the object as transparent, and the swap
  reaches the screen. Unlocks scoping (b).
- **FAIL (no red anywhere)** — check `~/callisto_swap.jsonl` for the pipeline
  being created and traced (`pipe_stage`, not `trace_rays`). If traced and
  still no red: the object is not routed through this pass (not
  transparent-classified in the gate texture), and the reachable surface for
  glass is the raster/blend + Distortion path instead — a different (graphics)
  toolchain this project has not built (`11` §5).

**What Phase 0 does not prove:** that we can reach the *see-through* half of
the glass pixel. That half is raster alpha-blend + Distortion; it has no RT
stage and no named compute module yet.

## Open items this surfaces (in order) **[corr 08-28: reordered]**

1. **Name the consumer** of the transparent-reflection output buffer. This is
   now first: §5b's whole ceiling depends on whether that buffer is added,
   lerped or replaced, and answering it needs **no launch**. Two caveats the
   first draft did not know:
   - `dev/prov_map.py` cannot see this buffer as written. Its report loop
     iterates images that have *compute* writers, and the probe records
     descriptor bindings for compute dispatches only — `capA_prov.jsonl` holds
     2920 events over **114 compute modules**, and this raygen is not one of
     them (`prov_map.py --module ee6d252e090adc74` returns nothing).
   - What it *can* do offline, today, on the existing capA: list the images
     **read by compute with no compute writer** — the RT/raster-output class,
     90 of them in capA. That is the candidate set for the reflection buffer;
     narrowing it wants either RT-side binding capture (item 3) or a format /
     size / reader-set argument.
2. **Run Phase 0**, and prefer **Phase 0.5** (§5b) if the goal is to learn
   whether refraction is worth pursuing rather than merely whether the pass is
   reachable — same cost, strictly more information.
3. **Attribution hole**: 4 anonymous (`rgs:""`) pipelines hold every ahs/chs
   stage; worth one layer tweak if (b) is green-lit, since (b) needs the hit
   groups' execution to be provable. Extending the same tweak to log RT
   descriptor bindings is what closes item 1 properly.
4. **Mask-bit question** for glassware instances — now also relevant to (b)
   itself, not just to future bounce rays (§2).

## Corrections log — 2026-08-28 review

Every item was re-derived from the binaries; the marks in the body point at
the same disassembly lines.

| claim as first written | verdict | where |
|---|---|---|
| "the reflection-vs-transmission weight already exists" (`F0 = max(byte,0.04)`) | **wrong** — that byte is the *hit surface's* F0 out of the CHS payload; no glass Fresnel exists in the module | §1 |
| "an epsilon-pulled origin … everything a refracted ray needs" | **wrong sign** — the origin sits *outside* the surface; a transmitted ray needs `P + D·ε` or it self-hits the glass | §1, §2, §5b |
| "blend `F·reflected + (1−F)·refracted`" | **wrong model for this buffer** — alpha is the gate *depth*, not a weight; if the consumer adds, this ghosts instead of refracting | §5b |
| "the engine ships nothing" | **too broad** — true for transmission, false for reflection: a `RayTracing/Reflection` CVar group exists and tmax is cbv-driven | §3, §5a |
| scope: only `rgs_reflection_transparent_main` examined | **gap** — two `rgs_reflection_opaque_main` permutations carry the same `cullMask=1` lever | §1 |
| "`prov_map.py` over a bar-scene capture answers the consumer question" | **overstated** — the probe logs compute bindings only; the raygen is absent from the prov log regardless of scene | open item 1 |
| "zero `Refract`/`Reflect` extinsts in 3005 modules" | **confirmed** by an independent full-dump disassembly sweep | §1 |
| the four traces' flags/cullMasks, the single `OpImageWrite`, `F0` floor, Beer–Lambert constants, the gate test, the exe's zero hits for transmission terms | **confirmed** | §1, §3 |

## Evidence index

- SPIR-V scan + disasm reads: scratch under `/tmp/opencode/glass_scan/`
  (`scan_results.json`, per-module `.spvasm`); repo disasms reused from
  `dev/disasm/{chs,compute,live,shadow,shadowflags}/`.
- Exe audit: scratch under `/tmp/opencode/glass_cvar/` (`strings.txt`,
  `cvar_paths.txt`, `cv_all.txt`, `emm_all.txt`); exe path per
  `dev/install_agx.sh:16`.
- Dispatch truth: `~/callisto_swap.jsonl`, pid 1097541 segment; traced
  transparent-reflection pipe at seq 5022 (`pipe_stage` attribution).
- Claims marked "inferred" above (buffer-consumer routing, gate-texture
  semantics, hit-group pipeline attribution) are exactly that; everything in
  §1's first four bullets is proven from the binary instruction streams.
- 2026-08-28 re-verification: full-dump sweep for
  `GLSL.std.450 Refract|Reflect|FaceForward` over all 3005 `.spv` (0 hits);
  id-level reads of `dev/disasm/shadowflags/ee6d252e090adc74.…spvasm` for the
  origin, Fresnel, gate and image-write claims; `strings -n 6` of the
  2026-08-20 exe for the CVar group; `prov_map.py` over
  `analysis/evidence/meta/capA_prov.jsonl` for the coverage limits in open
  item 1.
