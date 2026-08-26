# 05 — The shadow-raygen anchor family (built)

Written Aug 25 after the post-reset launch. Supersedes the "not built" note in
`04-RESET-STATE.md` fact 4, and corrects the reason the reference anchors did
not port.

## Why this exists

The post-reset launch dispatched the same set as every session before it:

```
seq 379-386: rgs_shadow_main ×6 (4 distinct), ms_shadow_main,
             rgs_restirgi_spatiotemporal ×1
15 rt_pipeline events built from rgs_reference_main, all swapped:1, none traced
```

`rgs_reference_main` has still never been dispatched in a live session. So the
patch surface was moved to what the game actually runs: the shadow raygens.

## What was actually wrong with porting the anchors

Fact 4 in `04-RESET-STATE.md` said the shadow raygen had "no reference-style
triples". **That is wrong.** The triples are there:

| module | 1/π FMuls | triples (runs of 3) | dispatched |
|---|---|---|---|
| `b80f16ff7123d653` | 188 | **23** | yes |
| `66d84088ef02f6cd` | 184 | **23** | yes |
| `ebd5818bce1a6f00` | 104 | **13** | yes |
| `7c0ac26de880cd54` | 28 | **3** | yes |

`find_triples()` finds them unchanged. Three real differences broke the port,
and the third is the one that matters:

1. **`classify_triples()` intersects the multiplicand leaves of every triple**
   to find the single albedo triple. The reference raygen has one shading
   context; `rgs_shadow_main` has many inlined ones (4 distinct albedo groups
   of 13/4/4/2 triples in `b80f16ff`), so the intersection is empty and it
   dies with "expected 3 shared albedo ids". Fixed by grouping triples by
   their multiplicand tuple; the channel is the position in the triple.

2. **The albedo operands are `OpPhi` values, not FMul chains**, so
   `resolve_leaf()` has nothing to walk. Nothing needs walking — the phi ids
   are the channels, already in r,g,b order.

3. **The decisive one: the game's own skin gate dominates NOTHING.** Computing
   reachability + dominators over the CFG:

   ```
   b80f16ff  gate %674 (blk %90430)  dominates  0 / 23 eval sites
   66d84088  gate       (blk %89372) dominates  0 / 23
   ebd5818b  gate       (blk %52369) dominates  0 / 13
   7c0ac26d  gate       (blk %14674) dominates  0 / 3
   ```

   The gate is only a branch condition (`OpBranchConditional %674 …`) inside a
   branch that has re-merged long before any eval site. The shifted class
   value and the G-buffer descriptor load do not dominate either. So the
   reference trick — insert an `OpIEqual` beside the game's own test and
   reference it at the eval sites — cannot work here at all; it would emit
   SPIR-V that fails validation on dominance.

   **What does dominate all sites is the pixel coordinate pair.** So the
   material class is *refetched* at each eval site from module-scope
   descriptors plus those coordinates. This is the same tactic, for the same
   reason, that `find_normal_gbuffer()`/`emit_nfetch()` already use in
   `patch_skin_brdf.py` to recompute NoV at the splice.

The refetched chain (all pieces detected structurally, ids differ per module):

```
%a = OpAccessChain <pcty> %registers <pcidx>   ) SRV slot from
%b = OpLoad %uint %a                           ) the push constants
%c = OpIAdd %uint %b <off>                     )
%d = OpAccessChain <ptrty> <descriptor-array> %c
%e = OpLoad <imgty> %d
%f = OpCompositeConstruct %v2uint <x> <y>      <- these dominate every site
%g = OpImageFetch %v4uint %e %f Lod <lod>
%h = OpCompositeExtract %uint %g 1
%i = OpShiftRightLogical %uint %h %uint_5      <- material class
```

## What was built

- `dev/patch_shadow_brdf.py` — the anchor family. Tiers `forcetint` (ungated,
  no class fetch, no gate) and `hairhunt` (per-class palette, gated on the
  refetched class). It builds the CFG and computes dominators itself, and
  **skips and reports** any site whose inputs do not dominate rather than
  emitting invalid SPIR-V. Nothing about dominance is assumed.
- `dev/patch_shadow_perms.sh` — disassemble → patch → install → clear caches
  for every dumped shadow raygen. Unlike `patch_all_perms.sh` it replaces only
  the shadow swaps, leaving any reference build installed, so both surfaces
  are covered whichever the game dispatches. Destinations are overridable
  (`CALLISTO_INSTALL_DIR`, `CALLISTO_SWAPS_DIR`, `CALLISTO_NO_CACHE_CLEAR=1`)
  so the pipeline can be exercised without touching the real install.

## Verification done (no game launch)

- All 4 dispatched modules patch `spirv-val` clean on both tiers, **with every
  eval site gated and zero skipped for dominance** (23/23, 23/23, 13/13, 3/3).
- 10 of 13 dumped shadow raygens patch clean. The other 3
  (`281c46c2`, `94e675a5`, `b88183eb`) contain no 1/π constant and no Disney
  anchor at all — they are visibility-only shadow traces with no shading, so
  there is nothing to patch. Reported as "skipped", which is expected.
- Every triple value has exactly one consumer and it is an `OpFMul`, so
  `replace_single_use()` ports unchanged (69/9/39/69 values checked).
- Swap filenames match the layer's lookup ident (`<hash>.rgs_shadow_main`).
- Regression: `patch_skin_brdf.py` still reproduces the known-good reference
  hunt build byte-identically (`1fba2d96b2bc4af3…`).

`rgs_restirgi_spatiotemporal` (also dispatched) has 14 1/π sites but **no
triples** — its evals are scalar, consistent with the "thin eval" note in fact
4. It needs its own anchor and is not covered here.

## Next

```bash
./dev/patch_shadow_perms.sh              # forcetint FIRST
: > ~/callisto_swap.jsonl
# launch, reach gameplay with a character in frame
grep '"ev":"trace_rays"' ~/callisto_swap.jsonl
```

- **Screen visibly red** → the shadow raygens are the live shading surface.
  Re-run with `--hairhunt`, confirm skin is red (the control), then read
  hair's class off the legend and go to `03-HAIR-WORK.md`.
- **No change** → the shadow raygens are not shading the view either. At that
  point neither integrator we can see is producing the image, and the dispatch
  log plus a fresh capture are the only things left to read.
