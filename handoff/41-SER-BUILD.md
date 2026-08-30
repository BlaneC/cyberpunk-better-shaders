# 41 — Shader Execution Reordering: the restoration patch (A1 / G-A1)

Written 2026-08-30. Prompt: *build idea **A1** of `38-WILD-IDEAS.md` — put
`OpReorderThreadWithHintNV` back into the PT reference raygen, properly: all
twelve permutations, a defensible hint site, a layer that enables the device
extension, and offline verification you actually read back.*

---

**Verdict: built, validated offline, and unproven in the only way that
matters.** Forty-eight patched modules (four hint variants × twelve raygen
permutations) assemble and pass `spirv-val` at both `vulkan1.3` and
`vulkan1.4`; the layer now enables `VK_NV_ray_tracing_invocation_reorder` on
the `VkDevice` and that path is proven end-to-end against the real driver
without launching the game. **None of that is evidence that a single thread
gets reordered.** `OpReorderThreadWithHintNV` is a hint: it cannot change a
pixel, so there is no A/B screenshot that can confirm it, and the driver
accepts and links the modules whether or not the hint does anything. The only
honest measurement is a frame-time delta (§10). Treat everything below as
"the mechanism is in place", not "the optimisation works".

Two findings here contradict the brief's premises and are the reason this
document exists rather than a one-line "done": **§6** (the layer's capability
constant was wrong and its guard was silently dead) and **§7** (this driver
does *not* reject SER modules when the extension is disabled, so "the game
still runs" proves nothing).

---

## 1. Why SER is absent, re-checked

Confidence: **certain** — all four re-measured for this document, not
inherited from `38`.

| claim | measurement |
|---|---|
| the game asks for SER | `cvRayTracingEnableReferenceSER` is a string in the exe (`38` §A1) |
| no shipped module has it | `cd ~/callisto_dump && grep -la SPV_NV_shader_invocation_reorder *.spv \| wc -l` → **0** of **3273** |
| the driver has it | `vulkaninfo`: `VK_NV_…` and `VK_EXT_ray_tracing_invocation_reorder` rev 1, `rayTracingInvocationReorder = true`, `ReorderingHint = RAY_TRACING_INVOCATION_REORDER_MODE_REORDER_EXT` |
| there are twelve raygens | `ls ~/callisto_dump/*.rgs_reference_main.spv \| wc -l` → **12** |

Machine: RTX 4070, driver `610.43.2.0`. The gap is vkd3d-proton: it does not
translate the NVAPI SER intrinsic, so the DXIL arrives with the reorder gone.
We patch SPIR-V *below* vkd3d-proton, which is why this is reachable at all.

> **Census discipline** (`GOTCHAS`): `grep -r` over `~/callisto_dump` returns 0
> for strings that are present. Every count above used `grep -la <str> *.spv |
> wc -l` from inside the directory. A zero from `grep -r` looks exactly like a
> finding and is not one.

## 2. What was built

| path | what it is |
|---|---|
| `dev/patch_ser.py` | the splice. spvasm in, spvasm out, `spirv-as`, `spirv-val` ×2, readback diff |
| `dev/patch_ser.sh` | driver: builds the four-rung ladder, installs, `--status`, `--report`, `--selftest` |
| `swaps.ser.set/{class,byte,hit,class+hit}/` | 12 modules each + `MANIFEST.txt` + `build.json` |
| `swaps.ser/` | the materialised live rung (currently `class`) |
| `swap_layer.c` | `vkCreateDevice` interception, the reject guard, manifest logging |

Nothing is installed. `~/.local/lib/callisto/{swaps.ser,ser.set}` are both
empty — `./dev/patch_ser.sh --status` says so. §10 is the install.

`swaps.ser/` and `swaps.ser.set/` are not in `.gitignore` by name, but the
global `*.spv` rule covers their contents. `MANIFEST.txt` / `build.json` are
not covered; that is a one-line fix in a file this work does not own.

## 3. Where the hint goes, and why — measured, not asserted

Confidence: **high** on the measurements, **deliberately undecided** on which
rung wins. This is the part of A1 that is a judgement call, so the reasoning is
here in full rather than compressed to a choice.

A reorder hint only pays if it runs **before** divergent work and **after** the
value that predicts the divergence. So: rank every branch in the raygen by how
much code it guards, and ask which ones actually diverge across a warp.

Read off `d622fb9e1dcb8cd0` (14901 lines disassembled), regions by guarded line
count, with what each one tests:

| span | site | condition | divergent? |
|---:|---|---|---|
| 13452 | `merge@1447` | `OpImageFetch(gbuf, pixel).x == 0` | **yes** — the sky / no-geometry test |
| 13093 | `merge@1804` | `cbv[200].w == 0` | no — uniform CBV read |
| **12177** | **`merge@2294`** | **payload `t == 10000`** | **yes — the bounce ray hit/miss** |
| 11004 | `merge@3450` | payload `t` ∧ RNG threshold | yes, but nested inside `2294` |
| 10538 | `merge@3762` | `cbv[97].x == 0` | no — uniform CBV read |

And the class value the brief's prototype keyed on:

```
:1688  %1558 = OpImageFetch %v4uint %1556 %1557 Lod %uint_0
:1689  %1559 = OpCompositeExtract %uint %1558 1
:1690  %1560 = OpShiftRightLogical %uint %1559 %uint_5      <- the class
:1696  %1566 = OpIEqual %bool %1560 %uint_1
:1702  OpSelectionMerge %1572 None                          <- guards 62 lines
```

**Two candidate sites, and the numbers do not agree with the prototype.**

- **Site A — after the class fetch (`:1690`).** This is where `38` §1.5's
  validated three-instruction splice went. The class is directly tested at two
  sites and gates **62 lines**, ~0.4% of the shader. It is also *already
  inside* `merge@1447`, so the sky invocations have branched away before it —
  the reorder cannot sort out the threads that are about to exit, which is the
  single biggest coherence win available. Cheap, early, small live state.
- **Site B — after the bounce trace (`:2293`).** Hit/miss gates **12177 of
  14901 lines = 81.7%** of the shader. This is where the warp actually splits.
  But it sits inside the bounce loop, so it executes once per bounce per
  sample, and the loop's entire live state has to cross the reorder — against
  NVIDIA's own guidance to reorder where live state is small.

Neither dominates on paper, which is why this shipped as a **ladder rather
than a choice**: `class` is site A (the prototype, reproduced exactly),
`hit` is site B, `class+hit` is both. The frame-time run picks the winner.
Anyone who tells you which one wins without launching is guessing.

**Trace-site selection.** The module has six `OpTraceRayKHR`. Five are
occlusion queries — flags `12` (`TerminateOnFirstHit|SkipClosestHit`) or `10`
— and every one of them feeds a **branchless `OpSelect`**, so there is no
divergence to sort. Only `:2290` (flags a phi of `{16, 1040}`, i.e. a real
closest-hit trace) is followed by a genuine `OpSelectionMerge`. The detector
encodes exactly that, and its three guards are:

1. ray flags must not contain `SkipClosestHitShaderKHR` (`0x08`);
2. the compare's RHS must be **the trace's own `tMax` operand**, not the
   literal `10000` (they coincide here, but keying on the operand is what
   makes it a miss test rather than a coincidence);
3. the next line must be `OpSelectionMerge`.

Guard 1 keys on **flags, not `cullMask`** on purpose: the ptq patches rewrite
the mask `1 → 255`, so a cullMask-keyed detector would break the moment SER is
layered on ptq — which is the only configuration anyone will run.

## 4. The hint payload

`OpReorderThreadWithHintNV <hint:uint> <bits:uint>` — second operand is the
number of significant bits. Four rungs:

| rung | payload | bits | extra instructions | +bytes |
|---|---|---|---|---|
| `class` | material class, `%1559 >> 5` | 3 | none — the value already exists | **+60** |
| `byte` | `%1559 & 0xFF` = `class<<5 \| sub-enum` | 8 | one `OpBitwiseAnd` | +80 |
| `hit` | bounce hit/miss | 1 | one `OpSelect` | +84 |
| `class+hit` | both sites | 3 and 1 | both | +96 |

Rejected, with reasons: the **SBT / hit-group index** would be the ideal
payload, but reaching it needs a `HitObject`, which needs the trace
restructured into `OpHitObjectTraceRayNV` + `OpHitObjectExecuteShaderNV` —
and `GOTCHAS` records that a second `OpTraceRayKHR` spliced into a raygen
**does not execute** under vkd3d-proton, so that restructuring is not a safe
bet. The **payload members** (RGBA8 albedo, 12:12 octahedral normal) are
continuous values, not identities; hashing them into buckets sorts threads by
something that is not what the divergent branch tests.

## 5. The layer

Confidence: **high** — every path below is exercised by `--selftest` (§9).

`vkCreateDevice` interception (`swap_layer.c`, `ser_enable_setup`):

- queries `vkEnumerateDeviceExtensionProperties` and only acts if
  `VK_NV_ray_tracing_invocation_reorder` is really present;
- **gates on `VK_KHR_ray_tracing_pipeline`** being in the app's own list —
  SER depends on it, and adding SER to a non-RT device is invalid;
- appends the name to a **`malloc`'d copy** of `ppEnabledExtensionNames`; the
  caller's array is never written;
- **prepends** `VkPhysicalDeviceRayTracingInvocationReorderFeaturesNV{
  .rayTracingInvocationReorder = VK_TRUE }` to `pNext`, preserving the rest of
  the chain — vkd3d-proton's `VkPhysicalDeviceFeatures2` and the loader's own
  `VkLayerDeviceCreateInfo` node both survive. The chain is walked first and
  nothing is added if that sType is already there (a duplicate is invalid
  usage);
- **no-ops completely** when the extension is absent or `CALLISTO_SER_DISABLE=1`;
- if `vkCreateDevice` fails with our modified struct, it **retries with the
  caller's original** and logs `action:"fallback"` — a device that would have
  been created without us is still created.

Every outcome is one JSONL line with a reason token, so a failure is
diagnosable from the log alone:
`env_disabled`, `no_enum_fn`, `bad_ext_array`, `already_enabled`,
`no_ray_tracing_pipeline`, `enum_failed`, `oom`, `unsupported`,
`feature_already_chained`, `enabled`.

Also added: `{"ev":"rt_pipeline_failed",...}` (that return was silent before,
which is exactly the failure this patch could cause), and
`{"ev":"overlay_manifest",...}` echoing line 1 of each overlay's `MANIFEST.txt`
so the log says *which rung was served*.

**Is a `vkEnumerateDeviceExtensionProperties` interception also needed? No —
and it would be actively harmful.** Three reasons, and the question is
answered in-code as well as here:

1. The ICD already advertises the extension. We are not inventing support; we
   are enabling support the driver has and the app did not ask for. There is
   nothing to add to the list.
2. The layer's exported `vkEnumerateDeviceExtensionProperties` is only ever
   called by the loader with *our own layer name*, for which the correct
   answer is an empty list — the current behaviour.
3. Our `vkGetInstanceProcAddr` never hands out that symbol, so application
   queries fall straight through to the driver. Intercepting it would mean the
   app could observe an extension list that differs from what it asked for,
   for no gain.

**The reject guard.** A swap that declares the capability is only served if
`d->ser` is set for that device; otherwise the layer logs
`{"ev":"ser_reject",...}` and lets the vanilla module through. `d->ser` is 0
for an untracked device, which is the right default. This makes the worst case
of a mismatched `swaps.ser/` "SER did nothing" — A1's expected failure mode
anyway — rather than a black screen with no cause.

## 6. Finding: the capability constant was wrong, and nothing offline could catch it

Confidence: **certain** — found by the self-test, fixed, re-tested.

`ShaderInvocationReorderNV` is a **SPIR-V** enumerant, not a Vulkan one. There
is no header to include and no compiler error if you get it wrong. The first
version of `spv_declares_ser()` used **5345**. The real value is **5383** —
read out of an assembled module rather than off a spec table:

```
$ spirv-as --target-env spv1.4 ser.spvasm -o ser.spv     # declares the capability
$ # dump the OpCapability run: 4479 (RayTracingKHR), 5383 (ShaderInvocationReorderNV)
```

With 5345, `spv_declares_ser()` never matched, so the entire reject guard was
**silently dead** — the layer would have happily served a SER module to a
device without the extension. It compiled, it ran, every offline check still
passed, and the log looked correct. Only running the layer against a real
driver with a module that declares the capability exposed it.

That is the whole argument for `--selftest` existing. Keep it working.

## 7. Finding: this driver accepts SER modules with the extension *disabled*

Confidence: **certain**, measured three ways. **This contradicts the brief's
premise** that a module declaring `SPV_NV_shader_invocation_reorder` "will be
rejected at `vkCreateShaderModule`/pipeline creation" without the extension.

On driver `610.43.2.0`, with the SER extension **not** enabled on the device:

```
vkCreateShaderModule(raygen declaring ShaderInvocationReorderNV) -> VK_SUCCESS
vkCreateRayTracingPipelinesKHR                                   -> VK_SUCCESS
```

Measured with the layer active-but-SER-disabled, with the layer fully
disabled, and against a **real 296,480-byte patched game raygen** — all three
succeed. No validation layer is installed on this machine
(`/usr/share/vulkan/explicit_layer.d/` has only Intel nullhw and the MESA
overlay), so no VUID fires either.

**Why the layer's enable still matters.** Per spec the extension is required;
without it the behaviour of the instruction is undefined and the driver may
legitimately treat it as a no-op. So this finding does not make the enable
redundant — it makes it *unverifiable from the game's behaviour*. The
dangerous consequence is operational:

> **An un-updated layer looks exactly like success.** If you install
> `swaps.ser/` but forget to reinstall `libVkLayer_callisto_spvswap.so`, the
> game will start, render correctly, log 12 HITs — and reorder nothing. There
> is no error anywhere. `--selftest` and the `{"ev":"ser","action":"enabled"}`
> log line are the only things that distinguish the two cases.

`dev/patch_ser.sh --install` prints this warning; the install banner used to
claim the opposite and has been corrected.

## 8. How A1 composes with the existing raygen patches

Confidence: **high**. This is the trap most likely to waste a launch.

`swaps/1271d3815051da17.rgs_reference_main.spv` already exists, and overlays
are **first-file-wins** — every overlay outranks base `swaps/`. So a raygen
carrying both a Callisto splice and the SER splice must be **one file**, not
two. `swaps.ser/` cannot be built from the vanilla dump and stacked on top:
that would silently un-patch the PT tier-1, MS-GGX and skinray splices, with
no error anywhere.

The build therefore resolves its source in this order, and **refuses** rather
than guessing:

1. `--from DIR` — explicit;
2. `$INSTALL_DIR/swaps.ptq/` — *what is actually being served*, the default;
3. `$MOD_DIR/swaps.ptq.matrix/<combo>/{base,skin}` — base is all twelve, skin
   overrides the two skinray permutations, matching what `sync_settings.sh`
   materialises at launch;
4. the vanilla dump — **only** with an explicit `--from-vanilla`, otherwise a
   refusal that explains the un-patching hazard.

`ser` is listed **first** in `CALLISTO_OVERLAYS` (now
`"ser,skin,shadowcull,ptq,ptrefl"`), so its twelve files win over `swaps.ptq/`.
That ordering is itself the trap: it is correct only because `swaps.ser/` was
*built from* `swaps.ptq/` and is a strict superset. The source content hash is
recorded in `MANIFEST.txt` and echoed to the log as `overlay_manifest`.

### Both gaps this left are now closed in `sync_settings.sh`

The version of this document written at build time left two holes and said so.
They are worth restating because they were **silent in opposite directions**,
and because the first one was worse than "rebuild after a ptq rebuild" implies.

**1. A stale `swaps.ser/` did not merely go stale — it silently disabled the PT
quality selector.** The 16-cell ptq matrix exists so that changing a PT setting
is a *file copy and never a patcher run* (`sync_settings.sh` materialises
`ptq/$combo/base` into `swaps.ptq/`; its own header says "never needs a patcher
re-run"). `swaps.ser/` collides with **12 of 12** ids in *every* cell — verified
with `comm -12` — and leads the overlay list, so it outranks all sixteen. A PT
toggle would therefore change `swaps.ptq/` on disk and change nothing that
reached the driver. Worse, it would **look applied**: the cache stamp hashes
`swaps.ptq/*.spv`, which genuinely changed, so the caches clear, every shader
recompiles, and the launch banner says "settings changed". Full cost, no effect.

**2. `swaps.ser/` was not in the cache stamp**, so a SER rebuild alone did not
move the stamp, the pipeline caches were kept, the old pipelines were reused,
and SER appeared to do nothing — the "silent no-op in a different costume" that
`sync_settings.sh`'s own I5 comment exists to prevent.

The fix is a guard placed immediately after the ptq materialisation block. It
recomputes the content sha over the just-materialised `swaps.ptq/` using the
same glob and order as `dev/patch_ser.sh:389–403`, compares it against the
`src_sha=` field in `swaps.ser/MANIFEST.txt`, and writes `ser.disable` on any
mismatch (the flag-file idiom the layer already honours, per `ptq.disable`).
`swaps.ser/*.spv` is now hashed into the stamp payload and `ser=$ser_state`
into the `want` string, which closes gap 2. `--from-vanilla` sets are handled
separately: they outrank base `swaps/` too, so they are enabled only when
`ptq` and `skinray` are both off.

**Why it disables rather than warns.** The failure modes are wildly asymmetric.
Losing SER costs a scheduling hint that **cannot change a pixel**. A stale SER
silently overrides the PT quality selection, which can. When one direction is
harmless and the other is invisible and wrong, the safe direction is the
default — not a comment asking the next reader to be careful.

Verified both ways: the guard reproduces the manifest's
`src_sha=033e4dd08aa3589c` exactly against the installed `swaps.ptq/`, and all
eight other matrix cells checked hash differently, so any PT toggle fires it.

## 9. Verification record

Offline, all 48 modules:

- assembled with `spirv-as --target-env spv1.4` (detected per module, not
  assumed — RT modules are SPIR-V 1.4, compute libs are 1.3);
- `spirv-val --target-env vulkan1.3` **and** `--target-env vulkan1.4`, clean;
- a `.spv` is **unlinked** if validation fails, so no stale artefact survives a
  failed build (`GOTCHAS`);
- **read back** with `spirv-dis` and diffed against the source, per `35` §6.
  Because `spirv-as` renumbers ids after an insertion, the diff normalises
  `%\d+ → %#` and then requires **zero removed lines**, the capability present,
  and exactly the expected reorder count.

Independent by-hand readback, `class` on `d622fb9e1dcb8cd0`, done outside the
patcher:

```
$ diff <(spirv-dis --no-color swaps.ptq/…d622fb9e….spv | sed 's/%[0-9]\+/%#/g') \
       <(spirv-dis --no-color swaps.ser/…d622fb9e….spv | sed 's/%[0-9]\+/%#/g')
24a25
>                OpCapability ShaderInvocationReorderNV
28a30
>                OpExtension "SPV_NV_shader_invocation_reorder"
1690a1693
>                OpReorderThreadWithHintNV %# %uint_3
```

308368 → 308428 bytes, **+60**. Exactly `38` §1.5's three-line diff, on a
different permutation and on top of the ptq patches. Nothing else moved.

**Anchor coverage: 12/12.** Both detectors match all twelve permutations on
the vanilla dump *and* on the ptq-patched set. Class site is unique in every
module; the hit detector correctly rejects all five occlusion traces. The
patcher `die()`s if either detector finds ≠ 1 site — it does not skip
silently, per the house rule.

**Layer, against the real driver** — `./dev/patch_ser.sh --selftest`, 11/11:

```
case A -- SER enabled, swaps.ser/ serves a reordering module
  PASS  layer enabled the device extension          {"ev":"ser","action":"enabled"}
  PASS  the reordering module was served (HIT)
  PASS  RT pipeline reports the swap (swapped:1)
  PASS  no ser_reject / no rt_pipeline_failed
case B -- CALLISTO_SER_DISABLE=1: the guard must refuse
  PASS  skipped, reason env_disabled
  PASS  ser_reject fired; vanilla served (swapped:0); probe still exits 0
case C -- a real patched raygen (296480 B) accepted by vkCreateShaderModule
```

> **Loader trap, recorded because it cost an hour.** The layer is installed as
> an *implicit* layer and the loader **dedupes by layer name**. `VK_ADD_LAYER_PATH`
> pointed at a fresh build still binds the **installed** `.so`, and
> `CALLISTO_LAYER_DISABLE=1` does not prevent it. The self-test's manifest
> therefore names its copy `VK_LAYER_CALLISTO_sertest`. Without that rename the
> test silently measures the old binary — which is how the 5345 bug survived
> the first three runs.

`swap_layer.c` compiles with **1** warning, identical to `git show
HEAD:swap_layer.c` (the pre-existing `-Wformat-truncation` in `overlay_init`).
No new warnings.

## 10. Running it

Build (needs `swaps.ptq/` installed, or pass `--from`):

```bash
cd "$CALLISTO"                       # the repo root
./dev/patch_ser.sh                   # builds all four rungs, materialises `class`
./dev/patch_ser.sh --status          # confirm 12 modules per rung
./dev/patch_ser.sh --selftest        # confirm the layer really enables the extension
```

Install — **both halves, the layer is not optional (§7)**:

```bash
./build_swap_layer.sh
cp -f libVkLayer_callisto_spvswap.so ~/.local/lib/callisto/
./dev/patch_ser.sh --install                    # writes ser.disable: SER starts OFF
```

The A/B control is **not a second build**. Skipping `swaps.ser/` makes
`swaps.ptq/` serve the very same modules **minus the reorder instruction**.
Single variable, nothing to drift.

> **Updated — do not `rm ser.disable` by hand.** `sync_settings.sh` now owns
> that flag and rewrites it on every launch from a `ser=` key, so a manual
> removal is silently undone before the game starts. It also hashes
> `swaps.ser/` into the cache stamp, so the manual cache clear between halves
> is no longer needed either. Both changes are §8.
>
> Select the half — and the rung — in `brdf_params.txt`:
>
> ```
> ser=off          # control half
> ser=class        # or byte / hit / class+hit
> ```
>
> `--install` parks all four rungs in `ser.set/`, so switching between them is
> a copy at launch, not a rebuild. `ser` is forced off whenever `tier=off`,
> when the requested rung is missing, or when the staleness check fires — it
> can only ever force **off**, never on, so the installed-disabled state stays
> the control until you ask for a rung.

**In `~/callisto_swap.jsonl`, in this order:**

| line | meaning | if missing |
|---|---|---|
| `{"ev":"ser","action":"enabled","reason":"enabled",…}` | the extension is on the device | **stop.** Read `reason`. An old `.so` logs nothing at all |
| `{"ev":"overlay_manifest","name":"ser","line":"ser variant=…"}` | which rung is served, and its `src_sha` | overlay not found, empty, or forced off by the §8 guard — check the `[CallistoSSS] ser …` line on stdout |
| 12 × `{"ev":"module",…"swap":"HIT"}` on `rgs_reference_main` | the modules were substituted | id mismatch — rebuild from the served ptq set |
| **no** `{"ev":"ser_reject",…}` | | the extension was not enabled but SER modules were served |
| **no** `{"ev":"rt_pipeline_failed",…}` | | the splice broke pipeline creation |

**Measuring the delta.** SER is a coherence optimisation: it does nothing where
the warp is already coherent. Measure where material divergence is highest.

- **Scene:** a dense street crowd at night — Jig-Jig Street / Westbrook, or
  Tom's Diner exterior. Many distinct materials (skin, cloth, metal, glass,
  emissive signage) in one screenful is the whole point. A corridor or a
  daytime rooftop will show nothing and is not a null result.
- **Setting:** Path Tracing **on** (this raygen is the PT reference
  integrator; without PT it never dispatches — `04-RESET-STATE.md` is the
  cautionary tale). Fixed resolution, fixed DLSS mode, fixed time of day.
  Stand still; do not walk the A/B.
- **Counter:** GPU frame time, not FPS — the effect is a few percent and FPS
  hides it. Steam's overlay (frametime graph) or MangoHud `gpu_load,frametime`.
  Take a 60-second stationary sample per half, compare medians.
- **Expected size:** single-digit percent at best. NVIDIA's own SER numbers on
  CP2077 come from a *native* implementation with hit-object reordering, not a
  three-instruction hint splice. **A null result is the most likely outcome**
  and is a perfectly good one — record it and move on.
- Run all four rungs before concluding anything. `class` and `hit` reorder at
  opposite ends of the shader (§3) and can easily differ in sign.

## 11. What would falsify this

- **The splice is a no-op.** No frame-time difference on any rung in a
  high-divergence scene. Most likely single outcome. Would mean: the hint
  payload does not predict the divergence the hardware cares about, or the
  driver drops a bare `OpReorderThreadWithHintNV` without a `HitObject`.
- **The hint site is wrong, not the idea.** `class` null but `hit` positive
  (or the reverse) falsifies §3's inability to choose, in a useful direction.
- **SER makes it slower.** Real and plausible for `hit`: reordering inside the
  bounce loop with the loop's whole live state across it can cost more than the
  coherence buys. Falsifies site B specifically, not A1.
- **The extension never gets enabled.** `{"ev":"ser","action":"skipped"}` with
  any reason token, or no `ser` line at all — the latter means the installed
  `.so` is stale (§7). Falsifies §5.
- **The modules are not served.** Fewer than 12 HITs on `rgs_reference_main`,
  or an `overlay_manifest` `src_sha` that does not match the current
  `swaps.ptq/`. Falsifies §8 — a stale set built against a different combo.
- **Pipeline creation fails.** `{"ev":"rt_pipeline_failed",…}`. Would falsify
  §7's finding and mean the driver does enforce the extension after all — in
  which case check the `ser` line first.

## 12. Built vs. unproven

**Built and verified offline** — confidence *certain*:

- 48 modules (4 rungs × 12 permutations), `spirv-val`-clean at `vulkan1.3` and
  `vulkan1.4`, readback-diffed, `class` reproducing `38` §1.5 exactly at +60 B.
- Both detectors sweep 12/12 on vanilla *and* on ptq-patched input; the patcher
  fails loudly on any permutation it cannot anchor.
- Composition is safe by construction: built from the served set, refuses to
  build from vanilla without an explicit flag, provenance hash in the log.

**Built and verified against the real driver** — confidence *high*:

- The layer enables `VK_NV_ray_tracing_invocation_reorder` on a device whose
  app did not ask for it (`--selftest` case A).
- The reject guard fires and degrades to vanilla when it cannot (case B).
- A real 296 KB patched raygen is accepted by `vkCreateShaderModule` (case C).

**Unproven — and not provable without a launch:**

- That any thread is reordered. **A swap HIT is not execution, and a
  successful pipeline creation is not a reorder** — §7 shows the driver builds
  these pipelines with the extension off, so "it loads" carries no information.
- That the hint improves frame time, on any rung, in any scene.
- Which rung wins. §3 argues both sides and deliberately does not pick.
- That the twelve permutations behave identically at runtime. All twelve are
  genuinely distinct (12 distinct output hashes, 10 distinct class-anchor line
  numbers spanning `:1632`–`:1816`), all twelve are patched, and none has been
  executed.
- Interaction with the pipeline cache across an A/B. `sync_settings.sh` does
  not hash `swaps.ser/`; the manual `rm -rf` in §10 is the mitigation and it
  has not been exercised.

**Not done, on purpose:** nothing was installed, nothing was launched, nothing
was committed.
