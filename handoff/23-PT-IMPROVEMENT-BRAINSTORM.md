# 23 — PT improvement brainstorm: modern light transport, triaged by lever

> **Follow-up: `24-PT-TIER1.md`.** Tier 1 was implemented on 2026-08-28 —
> T1.1, T1.2 and T1.4 built and validated offline, T1.3 investigated and
> **killed** by its own step (a). Read `24` for what the modules actually
> turned out to contain; several assumptions below were refined by it.

Written 2026-08-28. Brainstorm and triage only — **nothing was built or
patched**. Prompt: *what shader wins / graphical improvements remain that Ultra
Plus does not cover, and what modern light-transport math could be slotted in
to make path tracing better?* Sources: the lever analysis (`17`), the Ultra
Plus CVar audit (`16`), glass (`20`), cloth (`22`), the ReSTIR dispatch
evidence (`04`, `15`), and `dev/MS_GGX_NOTES.md`.

**Verdict, one line: Ultra Plus is config-side only (`16`: it writes CVars and
nothing else), so the entire uncovered territory is exactly this project's
three proven levers — ray-parameter edits, `rgs_reference_main` splices, and
LUT authoring — and the highest-value new items are path regularization plus
an indirect-radiance clamp in the already-proven reference raygen, a
spatiotemporal blue-noise swap of the suspected sampler LUT, and `22`'s cloth
probe re-scoped into a combined class-census launch.**

---

## 1. The frame: what "not covered by Ultra Plus" means

Every Ultra Plus action audited so far is a CVar write (`16` §1). That divides
the world cleanly:

| reachable by | Ultra Plus can do it? | this project's track record |
|---|---|---|
| Engine CVars (hair BRDF weights, ray/bounce counts, scatter depth) | **yes — that is all it does** | `hair_engine.lua` panel (40 CVars) |
| Ray-level edits (flags, cull masks, tMin) | no | **shipped** — shadow-leak fix |
| Value/BRDF splices in `rgs_reference_main` | no | **shipped** — skin BRDF |
| LUT/upload authoring (`CopyTextureRegion` hook) | no | **shipped** — SSS kernel |
| BRDF splices in the 720p compute evaluators | no | **never once changed a pixel** (`10`, `17`) |

Every idea below is tagged with its lever. Ideas in the last row carry the
project's one unbeaten risk, and `22` §8 is the probe that settles it.

## 2. The ideas, tiered

### Tier 1 — proven surface, real modern light transport

**T1.1 Path regularization (Kaplanyan-style roughness floor on indirect
lobes).** Clamp `α' = max(α, f(bounce))` for non-primary paths — Blender's
"Filter Glossy", UE5's `r.PathTracing.Regularization`: caustic-like firefly
paths get blurred at the source and the denoiser receives smooth input.
Surface: `rgs_reference_main` (proven by the shipped skin patch). Anchors
*already mapped* in `dev/MS_GGX_NOTES.md`: `%5649` = perceptual roughness,
`%5655` = α = R², shared with the sampling branch. Cost: a few ALU. No LUT,
no gate, no tangent. No CVar can do this.

**T1.2 Indirect radiance clamp (firefly ceiling).** One `NMin` on accumulated
bounce radiance/throughput in the same module. The standard companion to
T1.1 — every production path tracer ships both. Gains further value under
ReSTIR mode (§3).

**T1.3 Spatiotemporal blue noise (Lever B, extended).** `0x1980af80`
(128×256 R16_UNORM, 85 dispatch binds) is still the suspected sampler-noise
LUT (`17` §4). Step (a): run the survey replay (`NGFXPROBE_SURVEY=1`, recipe
in `dev/MS_GGX_NOTES.md` §1) and check for a uniform histogram. Step (b): if
confirmed, author STBN via the existing `CopyTextureRegion` hook — Heitz &
Belcour 2019, *"distributing Monte Carlo error as blue noise in screen
space."* Optional follow-up splice: **Cranley–Patterson rotation per bounce**
(offset the noise fetch by a per-bounce constant) — the classic blue-noise-
in-path-tracing trick. Physically unreachable for a config mod.

**T1.4 Bounce-ray `cullMask 1 → 255`** — restated from `17` §3, still the
highest-value *identified-but-never-built* item: actual indirect light *from*
hair, which no CVar scatter-depth fakes. Same one-constant edit applies to
the three reflection raygens (`20` §5a).

### Tier 2 — proven mechanism, one identification step away

**T2.1 MS-GGX energy compensation (finish what was scoped).** Kulla-Conty /
Turquin compensation for the energy single-scatter GGX loses at high
roughness. Blocked on the E_ss normalization mystery (`dev/MS_GGX_NOTES.md`
§2: as-read Vis is 2–4× low — a misreading, not a discovery). Next step is
defined there: trace `%9946`/`%9016`/`%9007` to source, or a debug-UAV
readback under replay. Once E_ss resolves, prefer Fdez-Agüera's analytic
multiscatter fit (Filament's) — no directional-albedo LUT needed. Honest
caveat: if the Vis misreading resolves upward, the win shrinks.

**T2.2 Cloth sheen — superseded by `22`, re-scoped in §4 below.**

**T2.3 Thin-skin backlight transmission.** A Beer–Lambert distance-tinted
transmittance for skin-classified occluders (ears/nostrils/fingers against
the sun) — the transmission half of the character-rendering story the
Callisto talk tells. Harder than it sounds here: shadow rays run `SkipCHS`,
so this wants either a CHS enable or a distance heuristic in the shadow
raygen. Medium-hard, flagged honestly.

**T2.4 Identify the mystery float LUTs.** The upload survey
(`dev/MS_GGX_NOTES.md` §1) found 17× 32×32 and 1× 256×64 RGBA32F LUTs
("smooth low-magnitude RGB ramps"), deterministic across captures, never
identified. Any that turn out to be atmosphere / aerial-perspective /
exposure LUTs are *new LUT-authoring surface* on the exact mechanism that
shipped the SSS kernel. One offline identification pass (bind against the
dispatch log) unlocks this.

### Tier 3 — specced, awaiting a launch or a CVar panel

- **T3.1 Glass Phase 0.5 → Fresnel two-ray → dispersion** (`20` §5b/c):
  refracted repoint, then reflected+refracted with a built Fresnel, then
  3-eta dispersion or per-channel eta jitter. Gated on naming the buffer
  consumer (offline, no launch).
- **T3.2 Reflection CVar panel** (`RayTracing/Reflection` group, `20` §5a) —
  cheapest item anywhere, but CVar-side, so the *least* Ultra-Plus-distinct.
- **T3.3 AgX HDR splice re-exam** (`19` open item 1) — the highest-value
  *existing* item; not new.

### Explicitly not worth doing

- Random-walk / quantized-diffusion SSS in PT — the screen-space kernel
  covers SSS better per cost; random walk at PT sample counts is a noise
  generator.
- Caustics / photon passes — `20` §5d's verdict stands.
- Path guiding / a ReSTIR re-architecture — out of splice reach (but see §3
  for working *with* the ReSTIR that exists).
- Any further BRDF math in the 720p compute evaluators — pending `22`'s
  Phase 0 verdict (§4).

## 3. ReSTIR: what Ultra Plus's option turns on, and what it changes

Prompted by the user's question about Ultra Plus's hidden "ReSTIR" toggle.
Evidence is `04` (dispatch sets) and `15` (family B); the rendering
literature is Bitterli et al. 2020 (ReSTIR) and Ouyang et al. 2021 (ReSTIR GI).

**What it is.** Reference PT (`rgs_reference_main`) rolls independent bounce
directions per pixel — unbiased-ish, very noisy at 1 spp. ReSTIR GI traces
one candidate path per pixel, packs it into a **reservoir**, then reuses and
re-weights neighbours' reservoirs across time and space (resampled importance
sampling). One ray per pixel behaves like dozens for diffuse GI. The dump
matches the textbook pipeline: `R16G16_SINT` reservoir-index buffers +
`R16G16_SFLOAT` weights at 1280×720 (`15` family B);
`rgs_restirgi_initial_temporal` carries thin evals (1/π, no Disney);
`rgs_restirgi_spatial` has **no diffuse eval at all** — pure reservoir
resampling, which is the tell (`04` fact 4).

**The trade-offs.** Lower but *correlated* noise; bias shows as blotchy
clumps, bleed through thin geometry, ghosting under motion; convergence
plateaus at the bias floor. That profile — clean in stills, smeary in motion —
is exactly the kind of feature a studio ships behind a flag.

**What Ultra Plus's mode does (proven in `04`).** Vanilla Overdrive:
`rgs_reference_main` ×2 **+** `rgs_restirgi_spatiotemporal` ×2. UP "V4" mode:
**no `rgs_reference_main` at all** — shading runs through the
`rgs_shadow_main` family + `rgs_restirgi_spatial`. The toggle itself is a
hidden-engine-feature CVar flip, consistent with `16`.

**Three consequences for this project:**

1. **The proven splice surface goes dark in that mode.** The shipped skin
   BRDF, and T1.1/T1.2 above, target `rgs_reference_main` — which dispatches
   zero times under UP's ReSTIR mode. There, material shading lives in the
   `rgs_shadow_main` family (`04` §4: full shading, 23 reference-style
   triples, the `gbuf>>5==1` skin gate in `b80f16ff`). The anchor family for
   it exists (`05`, built) but has never been A/B-verified on screen. **Every
   splice plan from here must state which render mode it was scoped against.**
2. **The tier list reshuffles under ReSTIR.** Blue noise (T1.3) still
   applies — the initial candidate trace still consumes the RNG texture, and
   ReSTIR amplifies whatever spatial structure its input noise has. The
   radiance clamp (T1.2) becomes *more* valuable: reservoir weight spikes are
   ReSTIR's classic splotch source, and production ReSTIR clamps candidate
   radiance / caps weight W. Path regularization (T1.1) is partly redundant —
   spatial reuse already blurs indirect detail (that *is* its bias). And
   `15`'s warning stands: splicing a reservoir *update* is not the same
   operation as splicing a BRDF eval.
3. **The shadow-raygen anchor family needs its verification launch** before
   any new math is authored against the reference raygen — otherwise we
   polish a module that never runs in the user's actual play mode. This is
   step zero for T1.1/T1.2 in practice.

## 4. What `22` (cloth) confirms and changes

`22-CLOTH-BRDF-FEASIBILITY.md` was reviewed against this brainstorm. The
Burley renormalisation constant it reports (`0.107508637` = (1−1/1.51)/π) is
present in this repo's committed disassemblies (`chs_main`,
`rgs_reference_main`, `rgs_shadow_main`) — its BRDF read is consistent with
on-disk evidence. Its quoted Charlie/Neubelt forms are the correct published
ones. Per-point outcome:

**Confirmed.** The sheen idea (T2.2 in a earlier draft of this list) was
directionally right — and `22` §4's cost estimate (~15 instructions, NoH/NoV/
NoL/roughness all live at every GGX site, no tangent, no gate needed to be
*visible*) makes it the cheapest BRDF addition ever scoped here.

**Changed — the class gate cannot be assumed.** An earlier draft of this
brainstorm pitched "Charlie sheen gated on the cloth class, same mechanism as
the skin patch." `22` shows the cloth class ID is unreadable offline, class 2
is tested by zero of 3153 modules, and its own rim-category evidence (Skin /
Foliage / Weapon / **Standard** — no cloth) tilts toward clothing rendering
as Standard = class 0: possibly *indistinguishable from walls in the
G-buffer, forever ungateable*. The feature may have to ship keyed on a proxy
or not at all. That risk is now front-loaded into the probe design below.

**Re-scoped — the combined Phase 0.** Merge `22` §8's sheen probe with its
§5's class-rainbow: splice `if (class==k) sheen *= palette[k]` into the five
dispatch-proven evaluators. One screenshot then answers *both* "does a
compute BRDF splice paint a pixel?" (the question open since `10`) *and*
"which class is cloth, and is it readable at this site?" (the GOTCHAS-10-
correct form of the question). Strictly more information than either probe
alone, same cost.

**Added caution — mode-robustness.** `10` proved those five tile evaluators
execute, but per §3.1 the dispatch set depends on render mode. The GOTCHAS-1
sibling sweep for the probe must run against a dispatch log captured **in the
mode the user actually plays**, or the verdict is mode-scoped.

**Promoted — the G-buffer hair-direction lead.** `22` §2's side-finding
(`667c55bd59f5f145` doing an octahedral-style direction decode, plus
`EMM_SurfaceHairDirection` in the exe) directly attacks `11` §2 — the
constraint that forced structure-tensor tangent estimation, the leading
suspect in the 70-module hair null result (`19` D11). If the G-buffer carries
a real hair direction, the hair track re-opens with the *actual missing
input*. Offline disasm read, no launch. Ranked near the top of §5, not at the
bottom where `22` put it.

**Ship-phase requirement — energy conservation.** The resolvers hand back a
scalar diffuse/specular pair, so a shipped sheen needs an explicit diffuse
damp (`f_d *= (1 − k·max3(sheenColor))`, tuned constant k). Additive sheen
without it brightens every cloth pixel at grazing angles — a slow-burn global
error of exactly the class this project keeps catching late. Ignorable for
the probe; not for the feature.

**Doc hygiene.** README's "plain Lambert (albedo/π)" vs `22`'s proven Burley:
almost certainly both true (raygen vs compute paths), but the README should
eventually say which.

## 5. Merged open items, ranked

1. **RimEnhancement/Standard CVar A/B** (`22` §3) — free, live, zero risk.
   Check Ultra Plus overlap first (it touches character lighting).
2. **Combined Phase 0: class-weighted sheen rainbow** (§4) in the five
   dispatch-proven evaluators — settles the compute-splice question *and* the
   cloth-class question in one launch. Mode-checked per GOTCHAS 1 (§4).
3. **Hair-direction G-buffer lead** (§4) — offline disasm read of
   `667c55bd59f5f145`; potentially unblocks the real-tangent hair path.
4. **Shadow-raygen anchor verification** (§3.3) — one A/B launch under the
   user's actual play mode; gates T1.1/T1.2 siting.
5. **T1.1 + T1.2 (regularization + clamp)** in `rgs_reference_main` — the
   best modern-math-per-risk on a proven surface; anchors mapped.
6. **T1.3a (STBN survey run)** — offline, zero shader risk.
7. **T1.4 (cullMask 1→255)** — one constant; finally answers the hair-bounce
   question; same edit on the three reflection raygens.
8. **`0e5e5a6a78fdf1dd` rejection re-check** (`22` §2) — one command.
9. **T2.4 (mystery LUT identification)** — offline; potentially new
   LUT-authoring surface.
10. **T2.1 (MS-GGX)** — after its defined unblocking step.
11. **T3.x** — glass Phase 0.5 (after consumer named), reflection CVar panel,
    AgX HDR re-exam — per `20`/`19`, unchanged.

## Evidence index

- Lever frame and cullMask survey: `17-LEVERS.md`; shadow-leak fix in `00` §10.
- Ultra Plus is CVar-only: `16-ENGINE-HAIR-BRDF.md` §1–2.
- ReSTIR dispatch sets: `04-RESET-STATE.md` facts 2–4; reservoir buffers and
  family B: `15-RENDER-GRAPH.md`.
- MS-GGX anchors and the E_ss blocker: `dev/MS_GGX_NOTES.md`.
- Cloth census, sheen spec, Phase 0, rim CVars: `22-CLOTH-BRDF-FEASIBILITY.md`.
- Glass Phase 0.5 / dispersion / reflection CVar group:
  `20-GLASS-REFRACTION-FEASIBILITY.md` §5–6.
- Burley constant verified in-repo: `dev/disasm/chs/55f6172c71799e4d.chs_main.spvasm`,
  `dev/disasm/shadowflags/ab7f1822eeb0331b.rgs_reference_main.spvasm`,
  `dev/disasm/shadowflags/66d84088ef02f6cd.rgs_shadow_main.spvasm`.
- Claims marked inferred above (ReSTIR bias profile applied to this game,
  the cloth-as-Standard tilt, the hair-direction decode's semantics) are
  exactly that; everything attributed to a numbered doc is that doc's claim,
  not re-derived here.
