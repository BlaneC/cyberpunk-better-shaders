# CallistoSSS — handoff for external analysis

**Current status: shipping; the hair BRDF is NOT visually confirmed.** The
SSS kernel and the hair shadow-leak fix are confirmed on screen. The hair
anisotropy / dual-lobe package is confirmed only *statically* (spirv-val, site
counts, dead-id analysis) and confirmed to be **loaded** (70/70 resolve swaps,
2026-08-26); it has never been shown to change a pixel. Earlier "confirmed"
screenshots were contaminated: ray-bounce onto hair from Ultra Plus, whose hair
settings were not isolated, was read as this mod's effect. See
`09-SETTINGS-AUDIT.md` D11. They are **not** reliably independently toggleable
from the CET tab — see `09-SETTINGS-AUDIT.md` for what each switch actually
does and the plan to fix it.
**Read `00-ARCHITECTURE.md` first** — it consolidates everything below, several
of whose conclusions it supersedes. Then read `10-DISPATCH-TRUTH.md`, which
corrects `00`'s coverage claims: they counted module *creation*, not dispatch.

Read in this order:

| file | what it covers |
|---|---|
| `00-ARCHITECTURE.md` | **START HERE** — what the mod is, how it works, current state, open items |
| `10-DISPATCH-TRUTH.md` | **newest, READ WITH 00** — what actually dispatches: 16 of 70 patched modules, only the coarse GI resolver directly; the anchor scan selects the wrong family; 4 executing modules unpatched |
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

Everything referenced lives in the repo at `CallistoSSS/`, branch `hair-brdf`.
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
