# CallistoSSS — handoff for external analysis

**Current status: shipping. AgX works; the hair BRDF is NOT visually
confirmed.** Confirmed on screen: the SSS kernel, the hair shadow-leak fix, the
skin BRDF, and the AgX tonemapper in **both display modes** — HDR 2026-08-27,
SDR 2026-08-28 — across all ten LUT-generator permutations, now running over
the game's authored per-area grading LUTs (`21-AGX-GRADE-AND-SDR.md`).
The hair anisotropy / dual-lobe package is confirmed only *statically*
(spirv-val, site counts, dead-id analysis) and confirmed to be **loaded** (70/70
resolve swaps, 2026-08-26); it has never been shown to change a pixel. Earlier
"confirmed" screenshots were contaminated: ray-bounce onto hair from Ultra Plus,
whose hair settings were not isolated, was read as this mod's effect. See
`09-SETTINGS-AUDIT.md` D11. The settings switches are **not** reliably
independently toggleable from the CET tab — see `09-SETTINGS-AUDIT.md` for what
each switch actually does and the plan to fix it.
The hair **shadow-leak fix** works and is confirmed on screen, but only in its
global `full` build, which costs an LOD-transition flicker on flat props; the
attempt to narrow it is mid-bisect (`26`). Tier 1 of the PT work is on screen
and **regressed hair** — narrowed to one of two switches, unresolved (`24`,
`26` §4.2).
**`19-STATUS.md` is the ledger** of what works, what was built but never run,
and what was withdrawn. **`26-SESSION-0828.md` is the current resume point.**
**Read `00-ARCHITECTURE.md` first** — it consolidates everything below, several
of whose conclusions it supersedes. Then read `10-DISPATCH-TRUTH.md`, which
corrects `00`'s coverage claims: they counted module *creation*, not dispatch,
and `15-RENDER-GRAPH.md`, which names the lighting buffers and their writers.
`16-ENGINE-HAIR-BRDF.md` then reframes the hair work entirely: the renderer
already exposes a three-lobe hair BRDF as engine CVars.

Read in this order:

| file | what it covers |
|---|---|
| `00-ARCHITECTURE.md` | **START HERE** — what the mod is, how it works, current state, open items |
| `26-SESSION-0828.md` | **NEWEST — read with `25`** — session record for 2026-08-28, and the document that **closes the shadow-ray track**. The narrowing landed: `full-shadow` (flags `28 -> 12` on the 10 `rgs_shadow` modules only) closes the hairline seam with less flicker than the original `full`, and now **ships as the default**. Everything else was deleted. The reason it could go no further is §7d: the **two-ray splice does not execute** — `sctrl`, a positive control whose second ray was unculled with the same mask, *had* to reproduce `full-shadow` and came back vanilla — which retroactively voids the opacity split and all twelve cull-mask bisects. Along the way: the class-1 hole (shadow traces carry mask 118, GI 119), two falsified theories (sun-ray self-intersection, opacity as a discriminator), and two confounds that cost the session — an `m112` launch read as a `full` launch, and the PT tier-1 overlays regressing hair. Also three bugs: pipeline caches were being evicted **every** launch (`cp -f` stamping fresh mtimes into the payload hash — fixed), the six numeric skin-BRDF sliders are **inert** (found, not fixed), and `nativeSettings.removeSubcategory` corrupts tab key order (avoided). Carries the resume point. |
| `25-SHADOW-FLICKER.md` | **superseded by `26` §7b-d, closed in §10** — the shadow-leak fix's LOD-flicker regression on flat props, and the two builds tried against it. Both §8's opacity split and §9's cull-mask bisect are **void**: they varied a second ray that never executes. The standing conclusion is §10 — ray flags are per-*ray*, so no subset of trace sites separates the hair from the flat props, and the residual flicker is not reachable on this axis. Still carries its corrections table: §4's "no occluder-material signal at trace time" was false, §6's GI toggle would not have fixed it (36 direct shadow traces vs 2 GI), §3's coverage claim contradicts `17` §2. |
| `24-PT-TIER1.md` | tier 1 of `23`, built. Bounce-ray `cullMask` 1→255 (the hair lever, and the headline), a per-segment indirect firefly clamp, and path regularization — all three spliced into the twelve `rgs_reference_main` permutations, plus the cullMask edit on the three reflection raygens; four CET switches. **On screen, and it REGRESSED HAIR** (2026-08-28): with all four on, the hair shadow-leak fix no longer looks right; with all four off it does. Narrowed by A/B to one of the two cullMask wideners — `ptbounce` or `ptrefl` — since `ptreg`+`ptclamp` together are clean. **Not yet resolved.** See `26` §4.2 for the per-launch payload fingerprints that isolated it. Also: T1.3 (blue noise) **killed** by its own step (a) — the only 128×256 R16_UNORM upload in the survey is 58% exact zeros, so no noise LUT exists to author into. And the engine's own `cb[85].z` firefly clamp, found dead in this mode and a CVar candidate. |
| `23-PT-IMPROVEMENT-BRAINSTORM.md` | brainstorm of PT improvements Ultra Plus cannot cover (it is CVar-only), triaged by the three proven levers: path regularization + indirect clamp in the reference raygen, STBN noise-LUT swap, the combined class-weighted sheen-rainbow Phase 0 (merges `22`'s two probes into one launch), the ReSTIR mode's consequences for splice siting, and the promoted G-buffer hair-direction lead. Ideas only — nothing built. |
| `22-CLOTH-BRDF-FEASIBILITY.md` | cloth feasibility (investigation only). Proven: **no cloth BRDF exists** — clothing is Standard, shaded as renormalised Burley + one GGX lobe; zero cloth CVars. A Charlie sheen lobe is the cheapest BRDF addition ever scoped (~15 instr, all inputs live) but the cloth class ID is unknown and may not exist as a gate. Side-findings: a G-buffer hair-direction decode that contradicts `11` §2, and one executing module whose rejection needs a re-check. |
| `21-AGX-GRADE-AND-SDR.md` | AgX over the game's authored per-area grade, and the SDR splice that was in the wrong place. The area LUTs now survive the tone-curve replacement (`--set grade=1`, the default). `--site sdr` spliced *above* the engine's own tone curve, which then tone-mapped AgX's output a second time — re-derived as `--site sdr2`, anchored on the runtime gates bracketing the curve, which covers all four corners of the SDR 2×2 lattice. Colour space proven from the Stephen Hill ACES fit pair. Confirmed on screen in both modes. **Supersedes `18`'s SDR section.** |
| `20-GLASS-REFRACTION-FEASIBILITY.md` | glass/refraction feasibility (investigation only, nothing built). Proven from the binaries: **no refraction exists anywhere** — no Refract instruction, no IOR constant, no transmission lobe, no CVar, no render node. Glass = raster blend + screen Distortion + a traced *mirror* reflection (`rgs_reflection_transparent_main`, executes live). Dispersion/caustics triaged: dispersion reachable only behind an authored refracted ray; real caustics out of scope. Contains the scoped Phase-0 marker spec (not built). **Reviewed and corrected 2026-08-28** — the verdict stands, but three details under it were wrong (no glass Fresnel exists; the ray origin's sign is wrong for transmission; the planned `F·reflected + (1−F)·refracted` composite would ghost) and the engine's `RayTracing/Reflection` CVar group had been missed. See its corrections log. |
| `GOTCHAS.md` | **read before starting anything new** — the method rules and the mechanical traps, each one paid for by a wasted session |
| `19-STATUS.md` | **the ledger** — every feature with its state *and its evidence*; what is built but never run (tint net, hunt net, rim-three Phase 0); every claim withdrawn or falsified, with where it was corrected; the recurring "patched one of N siblings" failure mode and the three rules it produced. |
| `18-AGX-FEASIBILITY.md` | AgX tonemapper, **WORKING in HDR and SDR** — but read `21` after it, which supersedes its SDR section and its "current state". The tonemap LUT is GPU-generated; **TEN** generator permutations exist (2 HDR + 8 SDR) — `dev/find_lut_gens.py` finds them all, `dev/build_agx.sh` builds them, `dev/install_agx.sh` installs them. Two bugs are written up because both are general: the HDR splice wrote Rec.709 into a slot holding **CIE XYZ** (pink/cyan neutrals), and the SDR splice first patched **one encode branch of seventeen**. Presets: neutral / punchy70 / **punchy70desat** (installed) / punchy / golden; `mix` is an A/B knob, not a strength knob. |
| `17-LEVERS.md` | **newest** — where Callisto still has reach (ray-level edits + LUT authoring, neither CVar-reachable); trace-ray flag/cull-mask survey; the bounce-ray `cullMask=1` lever; negative result on the 256×8 LUT. |
| `16-ENGINE-HAIR-BRDF.md` | **newest — read before any more hair shader work** — the engine ships a live-tunable R/TT/TRT hair BRDF as CVars (verified in the exe); Ultra Plus only flips them. New CallistoSSS panel exposes all 40, applying live. |
| `15-RENDER-GRAPH.md` | **newest — START AFTER 00** — the compute render graph, from offline capture replay: 6ac9's real inputs/outputs, the four lighting families and who writes them, 22 named unpatched indirect-light candidates. Withdraws `14` §4; corrects `13` §3–§4. |
| `14-PROVENANCE.md` | provenance hunt: capA facts + dead ends. **§2.4 ("replay segfaults") is WRONG and §4's plan is withdrawn — see `15`.** |
| `13-OWNER-NAMED.md` | bisection named `6ac9085c9bd4b7da`: the temporal resolve owns hair's per-pixel pixels; architecture (tile evaluators → resolve); interior-hair evaluator is a non-class-gated module |
| `12-FRESH-HUNT.md` | Phase 0 probe ran but was out of scope (inconclusive); dispatch-driven fresh hunt: third class idiom found & patched, 29-module net staged |
| `11-PROPER-HAIR.md` | what a real strand tangent would take: the G-buffer has none and no free channel; three delivery routes, tooling needed, and the probe that gates the decision |
| `10-DISPATCH-TRUTH.md` | **READ WITH 00** — what actually dispatches: 16 of 70 patched modules, only the coarse GI resolver directly; the anchor scan selects the wrong family; 4 executing modules unpatched |
| `09-SETTINGS-AUDIT.md` | why the settings page can't be trusted: 11 confirmed defects, root causes, phased plan, invariants |
| `08-DUAL-LOBE.md` | shifted dual-lobe hair (R+TRT); two latent spec-output bugs found & fixed |
| `07-COMPUTE-RESOLVE.md` | the visible pixels are shaded in compute; RT passes only produce samples |
| `06-PT-IS-THE-CHS.md` | live PT shades in the closest-hit shader, not the raygen; explains every null result |
| `05-SHADOW-ANCHORS.md` | the shadow-raygen anchor family (built); why the reference anchors really failed to port |
| `04-RESET-STATE.md` | full saga, proven facts, open contradictions, post-reset checklist (fact 4 corrected by 05) |
| `01-BLOCKER.md` | the null-result problem, all evidence, what is ruled out (resolution note on top) |
| `02-PROJECT.md` | what this mod is, how the injection works, what shipped |
| `03-HAIR-WORK.md` | the hair BRDF work that hit this blocker |
| `evidence-raygen-permutations.md` | generated table: 12 raygen permutations, 2 patched |
| `callisto_swap.sample.jsonl` | the HIT lines + one line per distinct raygen permutation |

Everything referenced lives in the repo at `CallistoSSS/`, branch `dispatch-truth`.
Deeper background: `dev/HAIR_HANDOFF.md`, `dev/MS_GGX_NOTES.md`,
`../analysis/BRDF_HANDOFF.md`, `../analysis/HANDOFF.md`.

## One-paragraph summary

CP2077 runs under Proton, so every shader reaches the driver as SPIR-V. A
Vulkan layer intercepts `vkCreateShaderModule` and substitutes patched modules
keyed by the DXIL identity that dxil-spirv preserves. A skin-BRDF patch
shipped and is visibly correct in A/B screenshots. The hair-class hunt that
followed never rendered, and a long instrumented chase (dispatch logging in
the layer, full-permutation patching, capture-replay correlation) established:
the hunt build is correct and attaches to the right modules — proven by
replay — but every live session, with and without the Ultra Plus PT mod,
dispatched only `rgs_shadow_main`-family pipelines, so the patched reference
integrator never ran. After the reset, one clean PT launch with dispatch
logging decides between the three remaining hypotheses (PT silently not
engaging, a game-build change, or an instrumentation hole). See
`04-RESET-STATE.md`.
