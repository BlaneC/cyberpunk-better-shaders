# 114 — Ideas board (2026-09-04)

The answer to *"anything else we haven't built? brainstorm from recent
research; fake a higher-resolution path trace on faces; micro detail"*,
written down so it stops living in one chat. Nothing here is built except
where a doc number says so. Ranking is payoff over feasibility **on the
machinery this repo has already proven** — a splice family that has never
executed here (the fragment stage, `96` §4.3) makes an idea expensive no
matter how good the paper is.

Standing constraint on everything below (`112` §12, `113` §1, memory
`pt-local-light-site`): under PT the raygens shade local lights themselves;
a compute-resolver feature shows **only in direct sun**. Anything that must
work at night under a neon has to go in the raygen.

## 1. Scoped in the ledger, never built or never shot

| Item | Doc | State | Why it is still here |
|---|---|---|---|
| Specular AA + conductor Fresnel | `108` | built, unshot, three rungs stale | the only feature that touches the whole city (every GGX alpha in 75/77, every Schlick in 77/77); rebuild on the current default, add provenance, shoot on sunlit metal at 20 m+ |
| Thin-surface translucency (curtains, tents) | `105` | built, never served (manifest lacked provenance) | premise rated low confidence by its own doc |
| Contact shadows via ray query | `102` | built on a stale base, unshot | |
| Skin-only sample count | `77` | served twice, no verdict, stale | the ledger's "real lever for vague faces"; 60–90 % more PT time in close-ups, photo-mode |
| Traced concavity / object-space glints / world-hash pack | `104` `106` `107` | half-built, rate-limit truncated, untracked scripts | |
| Denoiser + SHARC cell size panel | `82` | settings only, never run | zero shader risk; needs Ray Reconstruction off |
| DLSS preset test | `43` | never run | the single cheapest face-sharpness lever in the ledger |
| Bounce-light ear glow (route b) | `111` §13 | designed | `113` covered local lights; what is left is overcast and shade, diminishing |
| Car paint via a synthesized class | `96` §4.1 | designed | real payoff on vehicles; a new build |
| Grazing-angle specular occlusion | `38` A5 | blocked | needs a bent-normal input |
| Neural skin lobe (ALU) / DP4a-CoopVec net | `38` C1, D1 | designed | DP4a probe first |
| Untried rungs of shipped features | | parked | earglow7 sub-floor hue gradient, earglow-cap4, carglint-cell, carglint-sparse, contact-rq |

## 2. "Fake a higher-resolution path trace on faces"

The ceiling first: primary hits come from the raster G-buffer at the DLSS
internal resolution and the raygens run one thread per internal pixel. You
cannot add pixels to a face. You can make each pixel carry more
information. Five levers, cheapest first.

1. **DLSS preset override.** DLSS 4's transformer presets reconstruct skin
   texture far better than the CNN presets. On Proton it is a launch-option
   override through dxvk-nvapi, so it fits the existing launch line. Zero
   shader work. Run first.
2. **Skin-gated negative mip bias.** The engine ships live mip-bias
   plumbing (`36` §1). Sharper albedo and normal fetches on faces; DLSS eats
   the aliasing. Global via CVar today; per-class needs the fragment stage.
3. **Skin-only supersampling** = `77` rebased. Converges shading noise the
   denoiser otherwise blurs away with the detail. Photo-mode cost.
4. **Bypass the SHARC cache on skin.** Bounce light on faces is read out of
   world-space hash cells, which is why it reads as smoothed over. Gate the
   cache lookup off for class 1 in the raygen and take the full path. One
   gate in a proven module; nobody has scoped it.
5. **Tighten ReSTIR-GI spatial reuse on skin.** Spatial reuse averages
   neighbours' samples and smears lighting across pores and creases. A
   class-gated smaller reuse radius keeps face lighting local. Same splice
   family as `gi-50`.

## 3. Micro detail

Pores are not in the BVH (`33`, `38` §0d), so no ray budget creates them.

- **Albedo-derived bump.** → **BUILT as `115`, SHOT 2026-09-04, KEPT, THE
  DEFAULT** (*"IT LOOKS INCREDIBLE"*). Compute side. The roughness half and
  the raygen port are `115` §10.
- **World-hash micro-normal.** The glint machinery (`94`) already hashes
  world position stably. A high-frequency world-space noise on the skin
  normal gives a micro-structure that does not swim. Cheaper than the bump
  route, not tied to the actual pore map. Worth a rung as the "synthetic"
  arm of the same A/B.
- **Stochastic texture filtering at the G-buffer fill** (Pharr & Wronski
  2024). One jittered tap per pixel instead of trilinear; the accumulator
  or DLSS reconstructs sharper texture than the hardware filter. The real
  "sharper faces" research result — and it needs the fragment-stage splice
  that has never been proven to execute here. Run the G-U2 tint probe (`96`
  §4.3) first; it unblocks this, pores at the fill and per-class mip bias
  at once.

## 4. New ideas from recent research, ranked

1. **Random-walk subsurface for the sun term** (Chiang 2016 / Wrenninge
   2017 style). Random walks need only "am I inside the manifold", which
   inline ray queries answer; `105` proved six live queries in one raygen.
   Four exponential steps inside the skin, then `101`'s query-C sun
   visibility at the exit point. Subsurface that respects geometry: the
   nose shadow bleeds correctly, no screen-space halo. The ear glow
   generalised into real SSS. Big build, photo-mode cost, raygen side so it
   works under any light.
2. **Bounded VNDF sampling** (Eto & Tokuyoshi 2023). A better GGX sample
   distribution in the raygens: less variance on wet skin and metal at the
   same sample count. Shows only as less noise in motion. Small splice.
3. **Hanika's geometric shadow-terminator fix.** The shipped terminator
   work (`78`, `97`, `109`) is a colour bleed. The geometric fix offsets the
   shadow-ray origin so smooth-normal meshes stop showing the faceted
   terminator on jaws and cheeks. Cheap, orthogonal to everything shipped.
4. **Eye caustic.** Class 8 has its own gate. A sunlit iris shows a bright
   crescent opposite the light from corneal refraction; a term on the far
   side of the eye's N·L fakes it in a handful of instructions.
5. **Halation at the tone-map stage.** Post-process compute modules are
   swappable (the AgX rungs prove it). Red-biased bloom around highlights
   is the most recognisable film cue and touches every frame. Needs the
   bloom pass, not the per-pixel tonemap.
6. **Layered car paint, position-free Monte Carlo** (Guo 2018). Stochastic
   clear coat over a metallic flake base. `94`'s car-paint gate is real and
   shot; its physics conclusion killed the dielectric arm, so this is a
   rebuild of the coat, not a stack.
7. **CoopVec skin BRDF** (`38` D1). Collapse Burley + dual-lobe GGX +
   transmission into one class-gated network. No training-over-assets
   problem. DP4a probe first.

## 5. The order I would take

1. `115` is shot and kept. Next launch: `bump-vis`, `bump-hi`, the DLSS
   preset test and the `82` denoiser panel — four read-outs for one cycle.
2. Rebuild `108` on the current default with provenance; shoot on metal.
3. `115` §10.3, the raygen port of the bump, so faces have pores at night.
4. Random-walk SSS as the next large build.
