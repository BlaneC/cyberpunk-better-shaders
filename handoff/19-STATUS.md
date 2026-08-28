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
that session's record and the resume point.

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
| Hair BRDF / anisotropy net (70 modules) | **not confirmed** | loaded (70/70 swaps resolve) but **never shown to change a pixel** | `00`, `10`, README |
| **PT bounce-ray cullMask 1→255** (T1.4) | **launched; SUSPECT for a hair regression** | one of T1.4/`ptrefl` regressed hair on screen; `ptreg`+`ptclamp` cleared by A/B; not yet isolated | `24`, `26` §4.2 |
| **PT reflection cullMask** (`ptrefl`) | **launched; SUSPECT, same pair** | as above | `24`, `26` §4.2 |
| **PT indirect firefly clamp** (T1.2) | **launched, clean** | on screen in Launch A with hair correct | `26` §4.2 |
| **PT path regularization** (T1.1) | **launched, clean** | on screen in Launch A with hair correct | `26` §4.2 |
| Numeric skin-BRDF sliders (`rho_f`, `n_f`, …) | **INERT** | nothing reads them: their only consumer `regen_and_clear.sh` is not in the launch options and has never run; `sync_settings.sh` does not parse the keys | `26` §5 |

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
| Bounce-ray `cullMask=1` → `255` | **launched** — `swaps.ptq/` + `swaps.ptrefl/`, four CET switches | no longer stalled: it ran, and regressed hair (`26` §4.2) |
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
| `20`: "here the engine ships nothing" | **too broad** — true for transmission; false for reflection, where a `RayTracing/Reflection` CVar group exists and the reflection tmax is cbv-driven | `20` §3, §5a |

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
| `dev/build_ptq.sh` | the 7-combo `{reg,clamp,bounce}` matrix + the reflection overlay | yes |
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
6. **Launch the PT tier-1 build** (`24` §8) — built and validated offline,
   never dispatched. Two things to get: `swapped:1` on the ptq raygens, and an
   on-screen A/B of the cullMask widening at a framing where hair is a visible
   indirect contributor. This subsumes the old "bounce-ray `cullMask` lever"
   item (`17` §3), which is now code rather than a plan.
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
