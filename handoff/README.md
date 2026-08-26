# CallistoSSS — handoff for external analysis

**Current status: shipping, all four effects confirmed on screen.** Hair
anisotropy (direct + GI), the tier-1 skin BRDF, the SSS kernel, and the hair
shadow-leak fix are live and independently toggleable from the CET tab.
**Read `00-ARCHITECTURE.md` first** — it consolidates everything below, several
of whose conclusions it supersedes.

Read in this order:

| file | what it covers |
|---|---|
| `00-ARCHITECTURE.md` | **START HERE** — what the mod is, how it works, current state, open items |
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
