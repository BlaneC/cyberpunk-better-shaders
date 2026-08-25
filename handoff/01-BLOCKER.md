# The blocker: swap HITs, nothing renders

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
1. Rebuild the layer (dump support was just added) and dump every permutation:
   ```bash
   cd CallistoSSS && ./build_swap_layer.sh
   cp libVkLayer_callisto_spvswap.so ~/.local/lib/callisto/
   mkdir -p ~/callisto_dump
   # add to launch options: CALLISTO_DUMP_DIR=$HOME/callisto_dump \
   #                        CALLISTO_DUMP_MATCH=rgs_reference_main
   ```
   Launch, reach gameplay, quit. `~/callisto_dump/` now holds the live SPIR-V
   for every permutation.
2. Disassemble and patch them all — the patcher is fully structural, so it
   should handle any permutation without per-module constants:
   ```bash
   for f in ~/callisto_dump/*.rgs_reference_main.spv; do
       spirv-dis "$f" -o "${f%.spv}.spvasm"; done
   python3 dev/patch_skin_brdf.py ~/callisto_dump/*.spvasm \
       --tier forcetint --outdir swaps
   ```
3. Install, clear caches, relaunch. If the screen goes red, this was it.

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
