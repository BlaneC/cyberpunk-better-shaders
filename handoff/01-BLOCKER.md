# The blocker: swap HITs, nothing renders

**STATUS (Aug 25, late): superseded — read `04-RESET-STATE.md`.** A capture
replay proved the swap attaches to exactly the pipelines a PT frame
dispatches (both reference permutations, swap HIT, traced at 1280×720 and
160×90), so the build was always correctly targeted. But a subsequent live
launch with Ultra Plus uninstalled and PT confirmed on STILL dispatched only
`rgs_shadow_main` pipes — fewer RT passes than any session before it. The
question is now: why does live PT not behave like the capture's PT (three
hypotheses: PT silently not engaging, a game-build change since Aug 23, or
an instrumentation hole specific to the reference pass). Everything below is
the diagnostic trail.

## 1. Symptom

A diagnostic swap tints ten G-buffer material classes ten distinct colours at
the path tracer's diffuse eval sites. Expected: skin turns red (class 1 is
known), hair turns whatever colour names its class.

Observed, on a fresh launch with a fresh log: **no visible change anywhere on
screen. Skin is not red. Hair is unchanged.** The layer reports the swap was
served.

Skin is the control. Its gate instruction is byte-identical in form to the
game's own skin test, so if skin does not tint, the failure is upstream of
anything hair-specific and no reading of hair is meaningful.

## 2. What is PROVEN, with evidence

**The correct build is installed.**
```
sha256  ~/.local/lib/callisto/swaps/d622fb9e1dcb8cd0.rgs_reference_main.spv
        1fba2d96b2bc4af395cf692671bac714474467ed6dce1c6a13655b0c2e2724e5
        == CallistoSSS/swaps/ (the hunt build)   [matches]
```
`swaps/hunt_report.json` is present; the pre-hunt tier-1 swaps were backed up
to `~/.local/lib/callisto/swaps.prehunt/` and are 64 bytes smaller, i.e. a
different, earlier build. Not a stale-file problem.

**The layer served it.** From `~/callisto_swap.jsonl`, 12 HITs across launches:
```json
{"ev":"module","size":303048,"id":"d622fb9e1dcb8cd0.rgs_reference_main",
 "sha256":"eeb5a3ce…","swap":"HIT","result":0}
{"ev":"module","size":329572,"id":"40c6faab52a13874.rgs_reference_main",
 "sha256":"d8d135c3…","swap":"HIT","result":0}
```
`result:0` = `VK_SUCCESS`, so the driver accepted the substituted module.
(`size`/`sha256` describe the *incoming vanilla* module, not our replacement —
the log cannot tell you which swap file was used. Check the files on disk.)

**The emitted SPIR-V is correct.** In
`swaps/d622fb9e1dcb8cd0.rgs_reference_main.spvasm`:

Gates, inserted immediately after the game's own skin test so they inherit its
dominance — note `%12826` is *identical in form* to the engine's `%446`:
```
%446   = OpIEqual %bool %439 %uint_1      <- the game's own skin test
%12826 = OpIEqual %bool %439 %uint_1      <- ours, class 1 (control)
%12828 = OpIEqual %bool %439 %uint_2      … through %uint_14
```
Per-channel select chain and the multiply, wired into the real consumer:
```
%12870 = OpFMul %float %7591 %12847       <- tinted r
%7595  = OpFMul %float %7594 %12870       <- engine consumes the tinted value
```
`spirv-val` clean on both modules. Applied at all three eval copies.

**Delivery path is right.** Layer is implicit at
`~/.local/share/vulkan/implicit_layer.d/VkLayer_callisto_spvswap.json` →
`~/.local/lib/callisto/libVkLayer_callisto_spvswap.so`, which finds `swaps/`
next to itself via `dladdr`. Launch options run only `sync_settings.sh`, which
touches the SSS-kernel flag and never rebuilds swaps.

**The mechanism has worked before.** The shipped skin patch (tier 1) produced
visible, correct A/B differences — see `analysis/FINAL_BEFORE.png` /
`FINAL_AFTER.png`. So layer, hashing, gating and cache-clearing were all
functional at some point.

## 3. Ruled out

- Stale or wrong swap files on disk — hashes checked.
- Layer not loading — HITs present.
- Driver rejecting the module — `result:0`.
- Invalid SPIR-V — `spirv-val` clean.
- Patch logic wrong — assembly inspected line by line, wiring confirmed.
- Launch options overwriting swaps — `sync_settings.sh` read; it does not.
- Pipeline cache serving an old pipeline — caches cleared each run, and a
  cached pipeline would not produce a fresh `HIT`.

## 4. LEADING HYPOTHESIS: the wrong permutation is patched

The live game creates **12 distinct `rgs_reference_main` modules**, each a
different DXIL library hash. Only **2** are patched — the two that happened to
be captured in the two `.ngfx-capture` files this project was reverse
engineered from. See `evidence-raygen-permutations.md` for the full table.

**A `HIT` proves a module was CREATED, not that it was DISPATCHED.** The layer
hooks `vkCreateShaderModule`, which runs at pipeline-build time. The game can
build many raytracing pipeline permutations (feature/quality combinations) and
dispatch only one. If the dispatched raygen is one of the 10 unpatched ones,
every observation so far is explained exactly: HITs fire, the code is perfect,
and nothing renders differently.

Suggestive detail: three permutations are created 6 times while the rest are
created 3 times — `996a3b16253c3e7f` (293748 bytes, **never patched**) and the
two we do patch. It groups with ours and is unpatched.

### How to confirm and fix

**STATUS (Aug 25, evening): CLOSED — see the resolution note at the top of
this file.** The hash-only whole-library theory below was a misread of one
odd session (8 hash-only raygen ids, never reproduced — a one-off
pipeline-build/menu state, not the PT integrator). The capture replay proved
the PT frame dispatches the two named reference permutations, and the live
sessions were all hybrid RT.

1. ~~Rebuild the layer~~ — DONE, and it now does far more than dump. As well
   as `CALLISTO_DUMP_DIR`/`CALLISTO_DUMP_MATCH`, the layer records every
   module's identity and hooks `vkCreateRayTracingPipelinesKHR`,
   `vkCmdBindPipeline` and `vkCmdTraceRays*KHR`. Two new log events:
   ```
   {"ev":"rt_pipeline","rgs":"<id>","swapped":0|1}   pipeline built from this raygen
   {"ev":"trace_rays","rgs":"<id>","swapped":0|1}    this raygen is DISPATCHED
   ```
   `trace_rays` fires once per distinct pipeline that actually traces rays —
   it is the ground truth this whole diagnosis was missing. Installed at
   `~/.local/lib/callisto/libVkLayer_callisto_spvswap.so`.
2. ~~Dump + patch all permutations~~ — scripted as `dev/patch_all_perms.sh`
   (disassembles every dump, patches each independently so one structural
   failure cannot block the rest, installs, clears caches). Smoke-tested on
   the two capture-derived modules: reproduces the known hunt builds
   byte-identically (`1fba2d96…` / `7e052a77…`).
   Remaining manual steps: `mkdir -p ~/callisto_dump`, add
   `CALLISTO_DUMP_DIR=$HOME/callisto_dump CALLISTO_DUMP_MATCH=rgs_reference_main`
   to the launch options, launch, reach gameplay, quit, then:
   ```bash
   ./dev/patch_all_perms.sh            # or --forcetint for the null-bisect
   grep '"ev":"trace_rays"' ~/callisto_swap.jsonl
   ```
3. Relaunch. If the dispatched rgs shows `swapped:1` and skin is red, read
   hair's class off the legend and this was it. If `trace_rays` names a
   permutation that failed to patch, that module needs anchor work. If no
   `trace_rays` lines appear at all, see §5 — the raygen is not executing.

## 5. Second hypothesis: this raygen is not running at all

If path tracing is disabled (or the scene/mode uses a different renderer), all
12 permutations get built and none dispatched. Cheap to separate — an ungated
build that tints **everything** with no class test:
```bash
./dev/bisect_null.sh          # NOT YET RUN — this is the untested step
```
- screen red → raygen runs; problem is the gate or the class value
- unchanged → this raygen is not executing; check Settings → Graphics →
  Ray Tracing → **Path Tracing**

Combined with §4: if `bisect_null.sh` on the 2 patched permutations shows
nothing, but the same forcetint applied to **all 12 dumped** permutations does,
that confirms §4 conclusively.

## 6. Third hypothesis: the material-flag gate

At each eval site the whole diffuse term is gated on material flag `0x800`:
```
%7592 = OpBitwiseAnd %uint %5401 %uint_2048
%7593 = OpINotEqual %bool %7592 %uint_0
%7594 = OpSelect %float %7593 %float_1 %float_0
%7595 = OpFMul %float %7594 %12870        <- our tint, then zeroed if flag clear
```
If the flag is clear, the diffuse contribution is zero and no tint of ours can
show. This cannot explain skin going untinted (tier-1 visibly worked on skin,
so skin has the flag), but it becomes the prime suspect for **hair
specifically** if forcetint works and hair alone stays untinted. Flags `0x200`
and `0x2000` are documented as still unidentified in
`analysis/BRDF_HANDOFF.md`.

## 7. Suggested order

1. `./dev/bisect_null.sh` — the one untested cheap step. Separates §4/§5 from
   "the gate is wrong".
2. Dump all permutations (§4) and forcetint every one. This is the highest
   value action and directly tests the leading hypothesis.
3. Only once something visibly renders, return to the class hunt.

## 8. Restoring the working state at any time

```bash
./dev/hunt_hair_class.sh --restore    # exact pre-hunt tier-1 skin build back
```
