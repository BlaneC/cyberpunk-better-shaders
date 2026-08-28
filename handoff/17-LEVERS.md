# 17 — Where Callisto still has leverage, and what to try next

Written 2026-08-27 after `16` established that the engine's own CVars dominate
hair-BRDF tuning. If the BRDF-math-in-compute track is dead, what is left?

## 1. The leverage analysis

Callisto has three kinds of reach. Only two are worth using.

| reach | proven? | CVar-reachable? | verdict |
|---|---|---|---|
| **Ray-level edits** in RT shaders (flags, cull masks, tMin) | **yes** — the shadow-leak fix | **no** — nothing in the 71 `cv*` constants touches ray parameters | **use this** |
| **LUT / upload authoring** via the RED4ext hook | **yes** — the SSS kernel | **no** — no diffusion-profile CVar exists | **use this** |
| BRDF math spliced into compute evaluators | **never once changed a pixel** | **yes, extensively** (`16` §2) | abandon |

Both proven wins are in the first two rows. Neither is a shading-math splice.
That is not a coincidence: the evaluators are 720p, tile-classified and
tangent-less (`15`, `11` §2), while ray parameters and LUT contents are exact,
global, and invisible to the settings system.

## 2. Trace-ray survey (offline, from `~/callisto_dump`)

`OpTraceRayKHR %accel %flags %cullMask %sbtOffset …` across the RT stages:

| stage | flags | cullMask | sbtOff |
|---|---|---|---|
| `rgs_reference_main` — **bounce/primary** | dynamic (`%1407`) | **`%uint_1`** | 1 |
| `rgs_reference_main` — visibility | `10` = NonOpaque\|SkipCHS | **`%uint_255`** | 0 |
| `rgs_reference_main` — occlusion | `12` = TerminateFirst\|SkipCHS | `39` / dynamic | 1 |
| `rgs_shadow_main` | **`28`** = …\|CullBackFacing | dynamic | 0 |
| `rgs_diffuse_main`, `rgs_importance_main` | `16` = CullBackFacing | dynamic | 0 |

Two readings:

- The reference path's **visibility ray is already correct**: `ForceNonOpaque`
  (so anyhit runs and hair alpha-tests) with `cullMask = 255` (sees every
  instance). Hair shadows in the PT path already alpha-test per strand.
- The **bounce ray traces with `cullMask = 1`** while the visibility ray uses
  `255`. Whatever instances are not in mask bit 0 contribute nothing to
  indirect light — they are lit but never *bounce*.

`28 → 12` on `rgs_shadow_main` is the shipped fix (`00` §10).

## 3. Lever A — the bounce-ray cull mask (do this first)

> **Built 2026-08-28** as `24-PT-TIER1.md` T1.4 — twelve `rgs_reference_main`
> permutations plus the three reflection raygens, behind two CET switches.
> Still never launched, so everything below still describes an open question.

**The single most direct test of "do path-traced bounce rays hit hair".**
Patch `rgs_reference_main`'s bounce trace from `cullMask = %uint_1` to
`%uint_255`, matching its own visibility ray. One constant. Fully reversible.
`dev/patch_shadow_flags.py` already does exactly this class of edit, and
`rgs_reference_main` is already the module family the `tier`/`skinray` overlay
patches, so the install path exists.

What it cannot tell you from the shader alone: whether hair instances already
set mask bit 0. That lives in the TLAS instance descriptors. Widening the mask
answers it empirically — if indirect light on hair changes, hair was masked
out; if nothing changes, it was already included and the question is closed.

Risk, stated: a wider mask lets bounce rays hit instances deliberately excluded
(proxies, fake-light geometry, decals). Expect a perf cost and possibly wrong
light from proxy meshes. This is a diagnostic first, a feature only if it looks
right.

## 4. Lever B — the sampling-noise texture

> **Killed 2026-08-28** (`24` §4). The survey's only 128x256 R16_UNORM upload
> is 58% exact zeros over the 1/16 of it that was captured — heavily
> structured, not noise. There is no blue-noise LUT to author into, so the
> mechanism below has nothing to attach to. Read on for the reasoning; the
> conclusion is superseded.

`0x1980af80`, **128×256 R16_UNORM**, SAMPLED-only, **85 dispatch binds** — by
far the most-bound small texture in the capture, and the right shape and format
for the sampler's noise/dither source. Replacing it with a proper
spatiotemporal blue-noise sequence is a well-understood, global reduction in
path-tracer noise, and it is exactly the SSS kernel's mechanism: the RED4ext
hook (`main.cpp:55`) already intercepts an upload matched on
`Width/Height/Format` and substitutes bytes.

Not yet confirmed to *be* noise — the probe's narrow dump mode did not capture
its contents. Confirm first by re-running the replay with `NGFXPROBE_SURVEY=1`
(dumps every CPU→image upload) and checking the histogram is uniform.

## 5. Checked and negative — the 256×8 profile LUT

Worth recording so nobody re-derives it. The capture uploads **two** RGBA32F
profile LUTs from the same staging buffer, seq 1650163 and 1650165:

- `0x1c7d75c0` **32×8** — the known SSS diffusion kernel. Rows 0–2 valid, 3–7
  zero. **Bound by 3 modules**: `3e02d1116b61abbe`, `41b859089d708a2d`,
  `ed2abae23f81a4d5`. (`3e02` is also the sole compute reader of family A's
  `0x1c854e90` output — `15` §2.) This is what Callisto replaces.
- `0x1c7d7fb0` **256×8** — the *same three profiles at 8× tap resolution*
  (rows 0–2 well-formed and monotone with the same alpha ramp; rows 3–7 are
  uninitialised staging garbage, e.g. −5.6e34). **Bound by zero modules.**

`main.cpp:55` matches `Width == 32 && Height == 8` only, so the 256-tap LUT is
untouched — but it is also unused at these settings, so extending the hook to
it would change nothing. Revisit only if a future capture shows a module
binding it.

## 6. Not worth doing

- Competing with the engine hair BRDF (`16`).
- Any further palette/tint hunting *for hair specifically* — `15` §2 showed
  family A is fully covered and the interior-hair question is now a 15-module
  bisection (`15` §7) that only matters if you still intend to splice there.
- Tangent delivery through the G-buffer (`11` Route 1) — the engine's own hair
  shader already has the tangent; building a parallel path to hand one to a
  720p evaluator buys a worse version of what a CVar already drives.
