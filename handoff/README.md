# CallistoSSS — handoff for external analysis

**The question:** shader swaps are confirmed loaded and served (`"swap":"HIT"`),
`spirv-val` is clean, the emitted code is verifiably correct — and **nothing at
all changes on screen**, including a control case that is guaranteed correct by
construction.

Read in this order:

| file | what it covers |
|---|---|
| `01-BLOCKER.md` | the null-result problem, all evidence, what is ruled out, leading hypothesis |
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
keyed by the DXIL identity that dxil-spirv preserves. This worked: a
skin-BRDF patch shipped and is visibly correct in A/B screenshots. Recent work
added hair tiers, which need to know hair's G-buffer material class, so a
diagnostic build was made that tints ten candidate classes ten different
colours — including class 1 (skin), which is already known and therefore acts
as a control. In game: the layer reports HIT on both patched modules, and
**not one pixel changes**, skin included. The control failing means the test
never reached the screen at all, so no conclusion about hair is available yet.

**Leading hypothesis (strong, not yet confirmed):** the live game builds **12
distinct `rgs_reference_main` permutations**; only the 2 that happened to
appear in the Nsight captures are patched. A `HIT` proves a module was
*created*, never that it was *dispatched*. The game is very likely dispatching
one of the 10 unpatched permutations. See `01-BLOCKER.md` §4.
