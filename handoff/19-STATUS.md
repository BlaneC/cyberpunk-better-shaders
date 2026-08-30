# 19 — Status ledger: what works, what doesn't, what was built but never run

Written 2026-08-27, at the end of the session that restored offline capture
replay, reframed the hair track around engine CVars, and landed AgX. Updated
2026-08-28: AgX is confirmed on screen in both display modes, and now runs over
the game's authored per-area grade (`21`); and tier 1 of the PT brainstorm is
built but unrun (`24`). Updated again at the end of 2026-08-28 — tier 1 **has**
now run and regressed hair, the opacity-split shadow ray was **falsified** on
screen, and the shadow-ray narrowing is mid-bisect. Updated once more at the
close of 2026-08-28: the narrowing **finished**. `full-shadow` (the direct
shadow rays only) ships as the default; the two-ray splice was proven not to
execute and all 19 experimental sets were deleted. `26-SESSION-0828.md` is
that session's record and the resume point. The MS-GGX energy compensation
(T2.1) launched the same evening and is **confirmed on screen** — the ledger
row below — and now ships default-on (`28-MS-GGX-ENERGY.md`). Updated
2026-08-29: the SSS blur radius was found to be **10x the engine's** and fixed
(`33`); the Tier-3 gloss default was found to flatten all skin roughness and
flipped off (`33`). Updated **2026-08-30: Tier-4 backlit skin transmission was
REMOVED from the repo entirely** — it was seen on screen, it was wrong, three
thickness proxies in a row failed to save it, and the method rather than the
tuning was the problem. `39-TRANSLUCENCY-REMOVED.md` is the postmortem and the
only row it now has here. Also **2026-08-30: the whole skin BRDF turned out to
be direct-light only** — the class gate reached 0 of 218 splice lines in the
two GI resolvers, so bounce-lit skin had never carried the gloss, the
roughness cap, or the shipping tier-1 `c1`. Fixed, and the build now asserts
coverage instead of inferring it from a byte diff (`42-BOUNCE-LIGHT-GATE.md`).

This file is the **ledger**, not the argument. Each row points at the document
that carries the evidence. Where a claim is weaker than it sounds, the
confidence column says so — the recurring cost in this project has been
treating "built", "loaded" or "swapped" as "working".

---

## 1. Features

| feature | state | confidence | where |
|---|---|---|---|
| SSS diffusion kernel (LUT via RED4ext upload hook) | **ships, works** | visually confirmed on screen | `02`, `00` |
| Hair shadow-leak fix (ray flags) | **ships, works** | visually confirmed on screen | `00`, `17` §2 |
| ↳ narrowed to the direct shadow rays (`full-shadow`, now the default) | **ships, works** | on screen; the GI half added flicker and no seam contribution | `26` §7b |
| ↳ its LOD-flicker regression on flat props | **reduced, not fixed; axis exhausted** | ray flags are per-ray, so no site subset separates hair from flat props; the two-ray splice that could use the cull mask **does not execute** (`sctrl`, a positive control, came back vanilla) | `26` §7c-d |
| Skin BRDF patch | **ships, works** | A/B screenshots | `02`, `03` |
| **AgX tonemapper (HDR)** | **ships, works** | confirmed on screen by the user, 2026-08-27 | `18`, `21` |
| **AgX tonemapper (SDR)** | **ships, works** | confirmed on screen by the user, 2026-08-28 ("decent, serviceable") | `21` |
| **AgX over the authored per-area grade** | **ships, works** | on screen in both modes; the area LUTs survive the tone curve replacement | `21` |
| Engine hair CVar panel (`hair_engine.lua`, 40 CVars) | deployed, applies live | panel works; its *visual* effect never A/B'd against a controlled scene | `16` |
| **Engine skin specular/sheen CVar panel** (`skin_engine.lua`, 17 CVars) | deployed, default off | panel verified against stubs; **A/B'd 2026-08-28 — no gloss possible from this surface** (rim = edge glow, tint = recolor; no skin CVar touches the GGX lobe's F0/roughness). CVar track closed for the glossy ask; Tier-3 splice is the go (`27` §4) | `27` |
| **Callisto Tier-3 skin gloss** (`skinspec`, the oily/wet skin splice) | **built + wired, NEVER LAUNCHED** | 284 Fresnel groups / 852 channels across 74 modules, `spirv-val` clean, byte-exact when off, parked as an A/B pair against an identical hair BRDF, CET **strength ladder** (off/subtle/medium/strong/extreme, default strong) + three silent-no-op warnings. Strength is launch-gated by design: the knobs are OpConstants, so a live slider is impossible (`27` §9). Zero evidence it changes a pixel | `27` §7, §9 |
| ~~Hair BRDF / anisotropy net (70 modules)~~ | **REMOVED 2026-08-28** | never shown to change a pixel in 70 modules of trying; deleted with `dev/patch_compute_hair.py`. The skin tiers it shared a file with became `dev/patch_compute_skin.py`, which patches **more** modules (77 vs 74) because the hair tangent anchor no longer gates them | `27` §8 |
| **PT bounce-ray cullMask 1→255** (T1.4) | **ships, works** | the suspected hair regression was retracted: hair is correct with it on | `26` §4.3 |
| **PT reflection cullMask** (`ptrefl`) | **ships, works** | as above | `26` §4.3 |
| **PT indirect firefly clamp** (T1.2) | **launched, clean** | on screen in Launch A with hair correct | `26` §4.2 |
| **PT path regularization** (T1.1) | **launched, clean** | on screen in Launch A with hair correct | `26` §4.2 |
| **MS-GGX energy compensation** (T2.1) | **ships, works** | confirmed on screen by the user, 2026-08-28 ("completely worked"): single-variable A/B — one launch with `m` on against four with it off, same shadow set and `ptrefl` throughout (`28` §6); default flipped on after the confirmation | `28` |
| SSS diffusion kernel — **blur radius was 10x the engine's** | **FIXED 2026-08-29** | `OFFSET_SCALE=10.0` measured on the shipped `kernel.bin`; now a preset ladder with `detail` (engine radius) as the default, `vanilla` verified byte-identical to the engine's upload | `33` §1 |
| Tier-3 gloss default — **flattened all skin roughness** | **FIXED 2026-08-29 (default → off)** | every rung's `alpha_max` clamps authored alpha 0.16–0.36 to one constant; the served `medium` gave 0.09 flat everywhere. Ladder kept, opt-in | `33` §2 |
| The whole skin BRDF was **direct-light only** | **FIXED 2026-08-30, not yet on screen** | the class-1 gate reached **0 of 218** splice lines in the two GI resolvers — including `99bb7c2698997b2a`, the one module `10` proved dispatches directly. Not the gloss, not the roughness cap, not the shipping tier-1 `c1`: the module's own `y >> 5` sits inside the bounds-guarded block that fetched it, so it dominates nothing below the merge. Anchor lifted onto the class phi the shader itself tests. Coverage 157 → 173 c1 sites, 879 → 1071 gloss channels, 343 → 408 alpha caps, **0 skipped**; exactly 2 modules changed vs the previous build, in all 5 rungs | `42` |
| The `--sets` byte-diff assertions **cannot see coverage** | **FIXED 2026-08-30 (build now aborts)** | a module with every site skipped still validates, still differs from the baseline (the knob OpConstants are emitted regardless — 48 bytes on `99bb`), and still counts as patched. `27` §8.3's "all 77 get the gloss" was read off exactly that delta. The build now asserts `skipped_dom == 0` from the per-module reports | `42` §3, §4.1 |
| **Engine detail/denoiser panel** (`detail_engine.lua`, 22 CVars) | **deployed, default off, never A/B'd** | 16 stubbed checks incl. duplicate keys across ReBLUR/Direct vs /Indirect; may be entirely bypassed if DLSS Ray Reconstruction is on — that is the first thing to check, not a defect | `33` §3 |
| ~~**Callisto Tier-4 backlit skin transmission**~~ (`skintrans`, `skinthick`) | **REMOVED 2026-08-30 — built, observed, wrong, and the method was the problem** | Barre-Brisebois translucency in the compute evaluators' diffuse accumulator, class-1 gated. Observed: a face-wide red wash with a blocky tile grid, glow crossing the face, clothing edges on the neck lighting up — at `medium`, not only at `extreme`. **Two stacked defects, neither fixable where it lived:** the term has no per-pixel shaping (`V` and `L` are near-constant over a face, so a forehead scores as high as an ear — `29` A4 predicted this verbatim), and it is the first tier that *adds* light onto `15` §2's 8px-quantised path instead of multiplying into it. Three thickness proxies were added in sequence and each failed; the offline verification was thorough and could not have caught either defect. Gone: the pass, the ladders, the CET switches, the `sync_settings.sh` keys, 56 sets (661 MB), and docs `30`/`34`/`35`. **Kept:** `GOTCHAS` 12 and 13, `29` Part B, the engine's own `CharacterSubsurfaceTranslucency` CVar | `39` |
| Traced thickness — the principled route, if the feature is ever restarted | **NOT STARTED, gated** | would measure thickness with a ray instead of proxying it, and its output is not tile-quantised, so it fixes the tile-grid defect as a side effect rather than working around it. This is one of the two conditions `39` §6 sets on restarting at all. Gated on `29` ranked item 4, the payload sentinel — **small, no risk, never run** | `39` §6 |
| Real per-pixel skin thickness (`29` A4 R3, the engine's back-depth target) | **ATTEMPTED IN FULL, CLOSED NEGATIVE** | the pass is **found** (depth-only 1280x720, uniquely `clear=1.0` for reverse-Z, 25 indexed draws) and **does run in Overdrive**, which settles a standing `GOTCHAS 5` worry affirmatively. It is still unusable: the bindless heap index moved 73203 -> 503350 across two captures **29 seconds apart in one session**. Not deferred — reopening needs an engine-side binding, not a heap index | `29` A4, `39` §6, `GOTCHAS` 13 |
| Roughness *scale* (vs the cap) — the real "rougher faces" knob | **SCOPED, not built** | same site and same single rewrite as `build_skin_alpha_cap`; `k>1` goes past vanilla, which the cap can never do | `33` §2, §5 |
| **Engine PT sampling panel** (`pt_engine.lua`, 12 RT CVars) | **deployed, default off, NEVER A/B'd** | 35 stubbed checks; path attribution resolved at runtime against a candidate list, so a wrong guess is a knob that reports itself dead. Zero evidence any of these CVars moves a pixel — Ultra Plus's author marked `RayNumber`/`BounceNumber` dead, which is a claim; `29` §B3 shows the bounce bound is a live runtime cbv value in 8 of 12 permutations | `32` |
| **`UseAOOnEyes`** (eye AO, in the skin panel) | **deployed, default off, never observed** | the entire engine-side eye-shading surface is this one boolean — no `cvEye*` constant exists | `31` §1, `32` §5 |
| Per-material sample counts (skin/eyes/hair) | **NOT STARTED — gated on a sentinel launch** | the degenerate outer loop `%12276`/`%12818` is a sample-loop skeleton, and the class gate is already fetched in `rgs_reference_main`; nothing may be built on it until a payload sentinel proves a looped trace executes | `29` §B4-B5, `32` §4 |
| Wetter eyes (class-8 roughness ceiling) | **PLANNED, not built** | eyes are class 8, proven on screen by the hunt paint (`pics/panam_working_small.png`); the splice is the existing gloss machinery retargeted, and the load-bearing constraint is that a second `replace_all_uses` on the same alpha id does not stack | `31` |
| **Shader Execution Reordering is absent under vkd3d-proton** | **MEASURED, splice validated offline, NEVER LAUNCHED** | 0 of 3273 dumped modules declare `SPV_*_shader_invocation_reorder`, while the exe ships `cvRayTracingEnableReferenceSER` and this driver reports `REORDER_MODE_REORDER_EXT`. The splice is 3 instructions / +60 bytes, `spirv-val` clean at vk1.3 **and** vk1.4, keyed on the class the raygen already fetches. Pure perf — it cannot change a pixel, so frame time is the only honest proof | `38` §0b, §1.5 |
| **The material byte carries a 5-bit sub-enum** (`word & 31`) | **MEASURED, unexploited** | tested in **68 modules** with values `{0,16,17,21,25,30,31}` (plus `{12,13,14,15}` in fragment `667c…`, which routes seven of them to one arm and picks per-subtype constants out of a CBV). `4d46` fetches the byte and consumes only `>>5` — reading the subtype costs **one `OpBitwiseAnd`**. This is the cloth gate `22` §5 called unreadable offline, and it is the one "unlock" that needs nothing built first | `38` §1.3, U4 |
| **G-buffer slot `registers[1]+3` (R8_UINT 1280×720) is skipped by the whole lighting family** | **MEASURED; contents unknown** | 9 of 9 family-A evaluators and both GI resolvers read `{0,1,2,4,5}` and skip `+3`. No compute writer; `usage=279` includes COLOR_ATTACHMENT, so a raster pass produces it. Addressed *relative to a push-constant base*, so GOTCHAS 13 does not bite. **Not yet a free channel** — 105 of 220 other compute modules use that offset off the same base | `38` §1.1, U3 |
| **The G-buffer carries two 10:10:10:2 channels, one decoded as a unit direction** | **MEASURED; identity unconfirmed** | `4d46` decodes `+2` as `(x−0.5)` normalised and scales **both** alphas by 3 — two 2-bit tags. The exe names `EMM_SurfaceHairDirection`, `EMM_SurfaceHairID`, `EMM_SurfaceTranslucency`, `EMM_SurfaceObjectID`, and views `GBuffer0A`/`GBuffer1A` separately. `11` §2's "no tangent, no free channel" was about the packed material word, not the descriptor table | `38` §1.2, B1 |
| **BDA is universal, not fragment-only** | **MEASURED** | 3225 of 3273 modules declare `SPV_KHR_physical_storage_buffer` — compute resolvers and RT raygens included. `36` §4b's baked-device-address route is available everywhere, not just in Fragment | `38` §1.4 |
| Descriptor injection (U1), the fragment stage (U2), a tensor-core pass of our own (D1) | **SCOPED, not built** | U1 would give the repo its first genuinely new sampled texture; U2 has never been shown to execute at all (`36` G1) and Tier B plus half of Tier C hang off it; D1 dodges `36` §9.1's divergence by using one warp-uniform network on one class | `38` §2, §6 |
| ~~Numeric skin-BRDF sliders (`rho_f`, `n_f`, …)~~ | **REMOVED 2026-08-30** | were inert: their only consumer `regen_and_clear.sh` never ran. Sliders, keys and the script are gone | `26` §5, `43` |
| ~~`skinray` (tier-1 raygen sampling)~~ | **REMOVED 2026-08-30** | sampling-only by the mod's own thesis (`00` §2), so it could never change a pixel; it cost the `skin/` half of the ptq matrix and a SER trap | `43` |
| `tier` master switch | **FIXED 2026-08-30** | off used to leave the skin and shadow overlays serving; it now forces every overlay off so "master off" is the bit-exact vanilla baseline it claimed to be | `43` |

The two features that are genuinely irreplaceable — the ones no CVar can
reach — are the hair shadow-leak fix and the SSS diffusion kernel. That
conclusion is `17`'s, and `16` is why it matters: the renderer already ships a
live-tunable three-lobe hair BRDF, so most of the hair *shading* work has an
engine-side equivalent and the mod's leverage is at the ray level and in LUT
authoring.

## 2. Built but never run

Nothing here is broken. Nothing here has been executed either, and that
distinction is the whole point of `10-DISPATCH-TRUTH.md`.

| thing | what it is | why it stalled |
|---|---|---|
| Tint net — `swaps.tintall/` (15 spv) | unconditional-tint patch over the 22 indirect-light candidates; `dev/build_tintnet.sh`, bisect via `dev/bisect_tint.sh` | needs a launch; superseded in priority by AgX | 
| Hunt net — `swaps.huntall/` (29 spv) | the dispatch-driven fresh hunt net | `12` |
| rim-three Phase 0 | the `spec_add` probe at the proven 22:34 direct-sun framing | both prior attempts were shot at the Panam scene, out of scope; carried forward unrun since `12` |
| Bounce-ray `cullMask=1` → `255` | **launched, clean** — `swaps.ptq/` + `swaps.ptrefl/`, four CET switches | ran, and the reported hair regression was retracted (`26` §4.3) |
| Shadow-ray variants `m1`, `m118`, `m119` | the three sets that close the class-1 hole | `m1` staged; needs one launch each (`26` §3) |
| Blue-noise LUT | **killed** — the only 128x256 R16_UNORM upload in the survey is 58% exact zeros, i.e. not noise | investigated, not built (`24` §4) |

## 3. What this session established

1. **Offline capture replay works** — `NGFXPROBE_STRIP_ALLOC=3`, which was
   sitting in this repo's own `analysis/HANDOFF.md` §8.6 the whole time. 2920
   provenance events with no game launch. This killed `14` §2.4 and made `14`
   §4's entire plan unnecessary. (`15`)
2. **The compute render graph is named** — 6ac9's real slots, and the four
   lighting families with their writers. (`15`)
3. **The engine already ships a three-lobe hair BRDF as CVars**, verified in
   the exe; Ultra Plus only flips them. This reframes the hair track. (`16`)
4. **AgX works**, in HDR confirmed and SDR built, across all ten LUT-generator
   permutations. (`18`)
5. *(2026-08-28)* **AgX consumes the game's authored per-area grade**, and the
   **SDR splice was in the wrong place** — above the engine's own tone curve,
   which then ran on AgX's output. Re-derived as `--site sdr2`, anchored on the
   runtime gates that bracket the curve, which covers all four corners of the
   SDR 2x2 lattice including the one with no curve at all and the one that
   picks between two curves at runtime. (`21`)

## 4. What did not work, and what was withdrawn

Kept deliberately — several of these were *confidently asserted* before being
falsified, and the pattern is more useful than the individual errors.

| claim | verdict | corrected in |
|---|---|---|
| "`ngfx-replay` segfaults, replay is a dead end" (`14` §2.4) | **false** — one env var fixed it | `15` |
| `13` §5's hypothesis for direct light | falsified by the render graph | `15` |
| "The engine's hair BRDF is Marschner-style" | **retracted** — inferred from R/TT/TRT naming, never read from shader code | `16` §6 |
| "`GlobalLight/ScatterDepth` is most of the bounce effect" | **retracted** — "GlobalLight" is Ultra Plus's author's label; in CDPR naming it is normally the sun | `16` §6 |
| "`PT_HairProfile` is path-tracing" | **withdrawn** — `PT_` is ParameterType (cf. `PT_Scalar`, `PT_SkinProfile`) | `16` §6 |
| AgX `--site pre` | **wrong** — wrote Rec.709 into a slot holding CIE XYZ | `18` |
| `find_tonemap_gens.py`'s float mode ladder | **too narrow** — an HDR-only trait; hid all 8 SDR permutations | `18` |
| AgX `mix` as a strength knob | **wrong model** — it cross-fades two different curves and flattens contrast; scale the look params instead | `18` |
| AgX `--site sdr` | **wrong** — spliced above the game's tone curve, which then tone-mapped AgX's output a second time; the "one of N branches" guard was satisfied by three unrelated phis | `21` |
| "the SDR modules do no colour conversion, input is Rec.709 throughout" | **was an assumption**, now proven: four of the eight carry the Stephen Hill ACES fit pair, whose domain is Rec.709 by definition | `21` |
| "AgX with `grade` disabled reduces to the current behaviour" | **false** — the exposure multiply is unconditional and `min_ev`/`max_ev` is an absolute log window, so any grade-mode switch needs a re-tune | `21` |
| `20`: "the reflection-vs-transmission weight already exists" | **wrong** — that Schlick `F0` is the *hit surface's*, unpacked from the CHS payload; the glass module has no interface Fresnel | `20` §1 |
| `20`: "an epsilon-pulled origin … everything a refracted ray needs" | **wrong sign** — the origin sits outside the surface; a transmitted ray fired from it self-hits the glass | `20` §1, §5b |
| `20`: blend `F·reflected + (1−F)·refracted` | **wrong model for that buffer** — its alpha is the gate *depth*, not a weight, and if the consumer adds, the maths ghosts instead of refracting | `20` §5b |
| `MS_GGX_NOTES` §2: "the as-read lobe discards 60-75% of its specular energy" | **false — a misreading, as suspected** — the block read was the *area/tube* arm, not the punctual BRDF, and the integrand carried an extra `NoL` the shader never applies. `E_ss(α→0) = 0.5` exactly | `dev/MS_GGX_NOTES.md` §2 |
| `MS_GGX_NOTES` §2: "`comp` needs `1/E_ss` in absolute terms, so the normalization must be right" | **wrong framing** — normalizing against the lobe's own α→0 limit cancels any constant scale error; the absolute never needed solving | `dev/MS_GGX_NOTES.md` §2(c) |
| `20`: "here the engine ships nothing" | **too broad** — true for transmission; false for reflection, where a `RayTracing/Reflection` CVar group exists and the reflection tmax is cbv-driven | `20` §3, §5a |
| Idea 6: "the 2 bounces correlate, so rotate the noise per bounce" | **false premise** — the loop-carried LCG phi the idea cites as its *enabler* is exactly what already decorrelates them; measured bounce-to-bounce correlation 0.0033 worst case vs a 0.00104 noise floor | `37` §2 |
| Idea 6: "Cranley–Patterson rotation is the modern-math win that survived the blue-noise death" | **a no-op here** — CP randomizes a low-discrepancy point set; there is none in any of the 12 permutations, and `frac(u+c)` on a plain LCG is a measure-preserving bijection | `37` §3 |
| `27` §8.3: "the two GI resolvers … are also covered now — faces lit only by bounce light previously got no gloss; now they do" | **false, and inverted** — they differed by **48 bytes of unused OpConstants**; 0 of 218 splice lines were reached until `42`. The hair patcher's early return was the only thing that ever *handled* those two, and deleting it is what dropped them | `42` §3 |
| Idea 6: "blue-noise error for zero new resources" | **inverted dependency** — the blue-noise-ness comes from the *mask* (killed by `24` §4), not the rotation; and even with a mask the per-pixel seed hash destroys it, so it also needs the seed *deleted*, not offset | `37` §4 |

## 5. The recurring failure mode

Three times in this session, a patch was applied to **one of N structural
siblings** and believed complete:

1. `b174eb4af0fea652` was patched; the **HDR** permutation. SDR ran a sibling.
2. The relaxed scan then found **eight more** SDR permutations, invisible to a
   detector written against the HDR pair's traits.
3. The SDR splice initially landed on **one encode branch of seventeen**, all
   of which phi from a common source.

A fourth followed on 2026-08-28, and it is the worst of the set because the
sibling sweep *succeeded*: the common source those seventeen branches phi from
was itself in the wrong place in the pass. Hence GOTCHAS #10 — **a structural
guard that can be satisfied by the wrong structure is not a guard**, and shape
is not position.

Each was caught cheaply — the first by the dispatch log, the second and third
in offline verification before a launch. The generalised rules, both now in
`18`:

> **Before believing a patch covers a pass, sweep the dump for structural
> siblings — and count how many places consume the value you spliced at.**

> **Write detectors against the mode-independent half of a signature.** A
> permutation compiled for known settings has the variable half folded away.

And a third, from the colour bug:

> **A splice site is a contract about a colour space, and the contract is
> unwritten.** A structural detector proves the *shape* of a site, never its
> *space*. Enumerating every constant matrix in a module and identifying each
> against published values costs one command.

## 6. Tooling added this session

| script | purpose | run? |
|---|---|---|
| `dev/prov_map.py` | render-graph builder over a provenance log; **its docstring carries the working replay recipe** | yes |
| `dev/prov_analyze.py`, `dev/provenance_6ac9.py` | provenance readback / slot analysis | yes |
| `dev/patch_agx.py` | the AgX patcher; sites `auto`/`ap1`/**`sdr2`**/`sdr` (legacy, wrong)/`pre`/`write`; `--set grade=0/1/2` | yes |
| `dev/agx_model.py` | Python mirror of the emitted math; used to prove neutrality and to pick the saturation bracket offline | yes |
| `dev/find_lut_gens.py` | **relaxed** LUT-generator scan — finds all 10 permutations | yes |
| `dev/find_tonemap_gens.py` | the original, narrower scan — finds only the HDR 2; kept as the worked example of an over-fitted detector | yes |
| `dev/build_agx.sh` | builds 14 variants × 10 permutations | yes |
| `dev/install_agx.sh` | install / remove / list; warns when a display mode's permutation is missing | yes |
| `dev/build_tintnet.sh`, `dev/bisect_tint.sh`, `dev/bisect_hunt.sh` | tint-net build + bisection | **no** |
| `hair_engine.lua` | CET panel over 40 engine hair CVars | deployed |
| `dev/patch_pt_quality.py` | the three tier-1 PT splices; `--report` prints anchor coverage per module | yes (offline) |
| `dev/patch_ms_ggx.py` | the T2.1 energy-compensation splice (both GGX arms, per-channel F0); `--report` prints arm classification and the scalar-specular skips | yes (offline) |
| `dev/patch_compute_skin.py` / `.sh` | the skin BRDF patcher (tier-1 c1 + Tier-3 gloss + hunt/tint diagnostics); `--sets` builds the overlay twice and parks the A/B pair | yes |
| `dev/build_ptq.sh` | the 15-combo `{reg,clamp,bounce,msggx}` matrix + the reflection overlay; chains `patch_ms_ggx.py` over the tier-1 output | yes |
| `dev/install_ptq.sh` | install / remove / status for the matrix | yes |
| `dev/patch_shadow_opacity.py` | the opacity-split shadow ray (`28` + `76`, min-combined) | yes (offline) |
| `dev/build_shadow_sets.sh`, `dev/install_shadow_sets.sh` | both shadowcull builds, parked for the CET switch | yes |

## 7. Open items, ranked

1. **Re-examine the HDR splice for the error the SDR splice had.** It looks
   right on screen — so did `--site sdr`. The gate-anchored method in `21` §3
   applies to the HDR pair and would either confirm the site or move it. This
   is the highest-value AgX item left.
2. **Final look pick** between `punchy70desat` / `.sat95` / `.sat90`, deferred
   by the user ("we can do tuning later"). `21` §4 has the chroma numbers.
3. **Reflection CVars before reflection splices** (`20` §5a) — a CET panel
   over the `RayTracing/Reflection` group, the `hair_engine.lua` pattern: no
   shader risk, applies live, and it is the engine-side answer to "better
   reflections". Cheapest item on this list.
4. **Name the consumer of the transparent-reflection buffer** (`20`, open
   item 1) — offline, no launch, and it sets the ceiling on whether any
   authored refraction can look like refraction rather than a ghosted overlay.
5. **Decide the hair track.** `16` says the engine already does the shading.
   The honest question is whether the 70-module net is worth any further
   effort, or whether the CVar panel plus the shadow-leak fix is the product.
 6. **Launch the PT tier-1 build** (`24` §8) — ~~built and validated offline,
    never dispatched~~ **done 2026-08-28**: on screen and clean, the suspected
    hair regression retracted (`26` §4.2–4.3); the MS-GGX confirmation launch
    (`28` §6) is the template A/B. The old "bounce-ray `cullMask` lever"
    item (`17` §3) this subsumed is code that ships.
6a. **Launch the opacity-split shadow build** (`25` §8) — two things to check
   in one session: the hairline seam is still closed, and cardboard/ground
   clutter no longer flashes black on LOD transitions. The switch flips
   between the two builds in-game, so it is one launch, not two.
6b. **Hunt `cb[85].z` in the exe** (`24` §5) — the engine's own max-luminance
   firefly clamp, gated off in this mode. If it is a CVar, it may replace the
   T1.2 splice outright; either way it is the calibration reference for it.
7. **The tint-net bisection**, if the interior-hair evaluator still matters
   after (5).
8. **rim-three Phase 0** at the 22:34 framing — cheap, and it has been carried
   unrun across three documents.
9. **Glass Phase 0 / 0.5** (`20` §5b, §6) — one patch, one launch, one
   screenshot; worth doing only after (4).
