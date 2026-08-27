# 10 — Dispatch truth: what actually runs, and why the hair BRDF never showed

Supersedes the coverage claims in `00-ARCHITECTURE.md` §3 and the premise of
`07-COMPUTE-RESOLVE.md`. Written 2026-08-26 after five isolated null results on
the hair specular package.

**A swap HIT proves a module was created. It proves nothing about whether it
runs.** Every coverage number in this project before today was a creation
count. This document replaces them with dispatch counts, from two independent
sources that agree.

---

## 1. Method

Two sources, derived independently:

1. **Live** — the swap layer now hooks `vkCreateComputePipelines`,
   `vkCmdBindPipeline` (compute bind point), `vkCmdDispatch` and
   `vkCmdDispatchIndirect`, mapping each dispatch back to the module it was
   built from and logging the group counts. Deduped per pipeline.
2. **Captured** — `analysis/evidence/meta/capA_probe.jsonl` (an Nsight capture
   from 2026-08-23, replayed through the ngfxprobe layer) contains the frame's
   full command stream: 320 compute dispatches, 114 compute pipelines, 382
   shader modules. Modules are matched to their DXIL ids by FNV-1a-64 over the
   SPIR-V, cross-referenced with `capA_modules_named.json`.

The capture predates every hair change, so it is an uncontaminated control.
The two sources agree on every module named below.

---

## 2. What actually dispatches

Of the **70** patched modules, all 70 are built into compute pipelines, and:

| | count |
|---|---|
| dispatched at all (live run) | **16 of 70** |
| dispatched at all (captured frame) | **11 of 70** |
| dispatched **directly** | **1** — `99bb7c2698997b2a`, at `[40,45,1]` groups |
| dispatched indirectly (tile-classified) | the rest |
| never dispatched | **54 of 70** |

`99bb7c2698997b2a` is the **GI resolver**, and `[40,45,1]` groups at 8×8 is
~**320×360 pixels** — a coarse indirect-bounce grid, not a per-pixel pass. It
carries the bulk of the 81 GI splice sites.

**That is the cube.** The user reported the hunt palette painting "kind of a
cube in front of the hair, not pixel-perfect per strand, only in sunlight".
A 320×360 grid over a 1280×720+ image is exactly that shape, GI is strongest
in lit areas, and it was the only module of ours dispatching directly in
either source.

---

## 3. The anchor scan selects the wrong family

`dev/patch_compute_hair.sh` selects targets by scanning the dump for modules
containing both `1/π` (0.318309873) and `k` (0.107508637). In the captured
frame:

- **No full-resolution dispatch carries that anchor pair.** The passes running
  at `[160,90,1]` (~1280×720) and `[320,180,1]` (~2560×1440) are all
  unanchored, and are small (1.7–8.6 KB) — post-process shaped, not lighting.
- Only **10 distinct anchored modules dispatch at all**, out of 84 anchored.

So the constant-pair anchor selects a family that is largely *not the family
that executes*. Coverage was being measured against the wrong denominator all
along: "68 of 84 patched" was true and irrelevant.

---

## 4. The actionable finding

The real per-pixel lighting is the **indirect, tile-classified** dispatch set.
Nine anchored modules appear there in the captured frame. Cross-referencing
them against what the patcher produced:

| module | dispatches | patched? |
|---|---|---|
| `2e73a32c35778d85` | indirect ×2 | yes |
| `81c13c37112d09df` | indirect ×2 | yes |
| `20e6c7b3626ae0d6` | indirect ×2 | yes |
| `4d46848998312027` | indirect ×2 | yes |
| `9a3fa53c53a3a21b` | indirect ×2 | yes |
| **`0e5e5a6a78fdf1dd`** | indirect ×2 | **NO** |
| **`7ae88cd87950a898`** | indirect ×2 | **NO** |
| **`03dc7a51279e7427`** | indirect ×2 | **NO** |
| **`d5166c0f1ea464b9`** | indirect ×2 | **NO** |

**Four of the nine modules that actually execute were skipped by the
patcher** — every one of them failing on the same thing: the material-class
read could not be located (`no material G-buffer read found (neither >>5 nor
&31)` in the `--hair` build, `material-class shift not found` in `--hunt`).

And they are not missing the shift. Three of the four contain a
`OpShiftRightLogical … %uint_5`; they simply do not present it in the shape
`find_class_shift` / `acquire_class_shift` recognises. Structurally they are
the same kind of shader as the five that patched cleanly — 7 image reads, 2
image writes, comparable size:

```
                        >>5   &31   shr   and   read  write  lines
  UNPATCHED, running
  0e5e5a6a78fdf1dd        0     0     2     6      7      2    779
  7ae88cd87950a898        1     0     3     5      7      2   1108
  03dc7a51279e7427        1     0     3     5      7      2   1306
  d5166c0f1ea464b9        1     0     4     5      7      2   1082
  patched, running
  2e73a32c35778d85        1     0     5     6      7      2    975
  9a3fa53c53a3a21b        1     0     6     6      7      2   1982
```

This is the best remaining explanation for every null result: **the tile
permutations that shade hair are plausibly among the four we cannot patch**,
so the class gate in the modules we *did* patch never sees hair, and the only
thing that ever painted was the coarse GI pass.

It is a hypothesis, not a conclusion — what is *proven* is that four executing
modules are unpatched and that the anchor scan mis-selects the target family.

---

## 5. Next step

1. Read the class-read idiom in `d5166c0f1ea464b9` and `7ae88cd87950a898`
   (both have a `>>5` the patcher rejects) and find why detection fails —
   a third encoding, or a fetch the dominance check refuses.
2. Teach `acquire_class_shift` that idiom; re-run `--hunt` limited to those
   four and confirm which one paints hair per-pixel.
3. Only then re-run `--hair`. Tuning is meaningless until a module that
   actually shades hair carries the splice.

**Select targets by dispatch, not by constants.** The layer now logs it, so
the selector can be built from a real frame instead of a byte scan.

---

## 6. Corrections to earlier documents

- `00-ARCHITECTURE.md` §3: "**84 `GLCompute` libs** | lighting resolve → the
  image | **everything visible**" — wrong. Most of that set never dispatches;
  the visible full-res passes are not in it.
- `00-ARCHITECTURE.md` §4: "70 modules, 68 of 84 coverage" — a creation-time
  number. Dispatch coverage is 11–16 of 70, and 4 executing modules are
  unpatched.
- `07-COMPUTE-RESOLVE.md`: "the visible pixels are shaded in compute; RT passes
  only produce samples" — the first half holds, but *which* compute modules was
  never established. The ones this project patched are mostly inactive.
- Anything claiming the hair BRDF is confirmed on screen: see
  `09-SETTINGS-AUDIT.md` D11. It has never been visually confirmed in
  isolation, and the shots that suggested otherwise included Ultra Plus.
