# 21 — AgX over the authored grade, and the SDR splice that was in the wrong place

Written 2026-08-27/28. Supersedes `18-AGX-FEASIBILITY.md`'s
"### The SDR splice: `--site sdr`" section, which describes a splice that
built cleanly, installed, dispatched — and was **in the wrong place**.

Two things landed:

1. **AgX now consumes the game's authored per-area grade** instead of raw
   shaper output. The area LUTs (the reason a bar looks like that bar) survive.
2. **The SDR site was re-derived from the dispatch structure** (`--site sdr2`).
   The old `--site sdr` spliced *before* the game's own tone curve, so the
   engine tone-mapped AgX's output a second time — which is why SDR read dark
   while HDR read correct.

Both confirmed on screen by the user: HDR 2026-08-27 ("looks incredible"),
SDR 2026-08-28 ("decent on screen, serviceable"). Tuning is deferred.

---

## 1. What the LUT generator actually does

All ten permutations (2 HDR, 8 SDR — see `18`) share one skeleton. Read from
the dispatch, not from constants (GOTCHAS #1); the ids below are from
`065fcdcc`, but the shape is identical in the HDR pair:

```
shaper Exp2  (grid coords -> linear)                        %88 %89 %90
  -> basic grade (3-zone / gain / offset / gamma / contrast / hue / sat)
  -> [ area LUT stack 1, iff cbv[42].y == 1 ]      merge phis %368 %371 %374
  -> x cbv[42].z                 EXPOSURE                    %380 %381 %382
  -> [ / cbv[30].x ]             normalise                   %387 %388 %389
  -> THE TONE CURVE                                <-- replaced by AgX
  -> [ x cbv[30].x ]             denormalise                 %478 %479 %480
  -> [ area LUT stack 2, iff cbv[42].y == 0 ]
  -> display encode -> OpImageWrite
```

The two area-LUT stacks are the same authored grade applied on either side of
the tone curve; `cbv[42].y` is the compile-time-invisible, runtime-selected
switch that says which side. Whichever side runs, **the grade is upstream or
downstream of the curve but never absent** — so a tone curve replacement that
reads the shaper output directly throws it away.

### The `grade` knob

`dev/patch_agx.py --set grade=N` chooses AgX's input:

| grade | input | ids | meaning |
|---|---|---|---|
| 0 | shaper output | `%88 %89 %90` | the old behaviour: no area grade, no exposure |
| **1** (default) | post-exposure | `%387..%389` or `%380..%382` | **the authored look, exposed** |
| 2 | pre-exposure | `%368 %371 %374` | authored look, AgX does its own exposure |

`grade` is not a free switch. **"grade disabled reduces to the current
behaviour" is FALSE**: `x cbv[42].z` is unconditional, and AgX's `min_ev`/
`max_ev` define an *absolute* log2 window, so moving the input across that
multiply moves the whole image within the window. `grade=0` and `grade=2`
therefore emit an explicit `/ cbv[30].x` (`pre_div`) so they enter the same
normalised domain, and any switch between grade modes needs a re-tune of
`pre_gain`, not just a flag flip.

`grade != 0` also enables `clamp_in`: the graded value can be negative after a
3-zone lift or a hue rotation, and `log2` of a negative is a NaN that the LUT
would then bake in permanently.

## 2. Why `--site sdr` was wrong

`find_srgb_site` anchored on the first three values compared against the sRGB
piecewise threshold `0.0031308`. That looked like the display encode. It is
not: the **grade stacks contain sixteen per-LUT encode blocks of their own**,
and the first threshold compare in the module belongs to one of those, not to
the tail encode. `_resolve_phi` then correctly walked back to the common
source of the phi group — `%356..%358`, **the basic grade's output**, well
above the tone curve.

So the shipped SDR patch was:

```
shaper -> basic grade -> [AgX] -> area LUTs -> exposure -> the game's tone curve -> encode
```

AgX's [0,1] display-referred output was fed to the engine's own curve. Two
tone maps in series: dark, low contrast, and *not* obviously broken enough to
be caught by inspection — it dispatched, it changed pixels, it validated.

The `groups >= 3` guard that was supposed to catch exactly this ("am I on one
branch of N?") was satisfied by the three *stack-1 merge phis*, not by the
seventeen encode branches it was written to count. **A structural guard that
can be satisfied by the wrong structure is not a guard.**

## 3. `--site sdr2`: anchoring on the gate, not on a constant

`find_sdr_tonemap()` locates the curve by its position between two runtime
gates, which is the only trait common to all four lattice corners:

- **Exposure.** `_cbv_component(mod, 42, 2)` gives every id that is
  `cbv[42].z`. Exactly three `OpFMul %float` share one as an operand: those
  are the exposure multiplies. Their results are `exposed`; their other
  operands are `graded` (the stack-1 merge phis).
- **The stack-2 gate.** Exactly one `OpIEqual %bool <cbv[42].y> %uint_0`
  followed by `OpSelectionMerge`. The three `OpPhi %float` at that merge point
  are the tone curve's *output* — take the incoming edge labelled with the
  gate block.
- Everything between `exposed` and `out` is the tone curve, whatever shape it
  has.

### The 2×2 lattice

Two compile-time booleans split the eight SDR permutations. Anchoring on the
gate covers all four corners with one rule; anchoring on the curve could not
have:

| | permutations | what the curve is |
|---|---|---|
| matrices + `cbv[30]` | `065fcdcc`, `6040914437` | ACES fit, normalised |
| matrices, no `cbv[30]` | `8bbd5900`, `ef31e105` | ACES fit **or** Reinhard, chosen at **runtime** on `cbv[42].x`, merged at a phi |
| `cbv[30]`, no matrices | `7a858d59`, `e0e20375` | luminance-only curve on `max()` |
| neither | `1c9000b4`, `90fa8b3f` | **no curve at all** — exposure goes straight to the stack-2 gate |

The bottom-right corner is the interesting one: `out == lin`, the segment is
empty, and any detector that requires finding a curve fails there. The gate
anchor does not care.

### Colour space (GOTCHAS #5)

`18` proved the HDR site by finding the ACES AP1→XYZ matrix. The SDR modules
carry no such matrix, so there was nothing to identify — the old note "no
colour conversion at all, input is Rec.709 throughout" was an *assumption*.

Four of the eight permutations do carry a matrix pair, and it is the
**Stephen Hill ACES fit** (`ACESInputMat` / `ACESOutputMat` from `aces.hlsl`),
reproduced coefficient for coefficient:

```
ACES_INPUT  = 0.59719 0.35458 0.04823 / 0.07600 0.90834 0.01566 / 0.02840 0.13383 0.83777
ACES_OUTPUT = 1.60475 -0.53108 -0.07367 / -0.10208 1.10813 -0.00605 / -0.00327 -0.07276 1.07602
```

`ACESInputMat`'s domain is **Rec.709 linear by definition**. Finding it applied
to the value at the splice is what proves that value is Rec.709. They are a
matched pair, so the segment between them is Rec.709 in, Rec.709 out — the
splice replaces the whole pair and needs no space conversion, only `eotf=2.2`.

The patcher enforces this: every constant 3×3 in `[def(exposed) .. def(out)]`
must be `ACESInputMat` or `ACESOutputMat`, else it dies. For the four
permutations with no matrix at all, the proof is by exclusion — nothing in the
segment can change the space.

### Splicing *inside* the `cbv[30].x` pair

Where present, the module divides by `cbv[30].x` on the way in and multiplies
by it on the way out. The patcher detects the pair (all three `exposed`
consumed by `OpFDiv(_, S)` **and** all three `out` being `OpFMul` with `S`) and
peels it, so AgX replaces the curve *inside* the normalisation.

This matters because `cbv[30].x` is an unknown runtime scalar. Splice outside
the pair and AgX's output gets multiplied by it — a range error that
`pre_gain` **cannot** undo, because it is not constant. Splice inside and the
divide and multiply cancel: AgX keeps vanilla's range convention whatever the
scalar holds.

### The output clamp

`clamp_out=True` at this site only. AgX overshoots — `(4, 0.02, 0.02)` comes
out at `1.2928` under `punchy70` — and the vanilla curve clamped to [0,1]
*before* the denormalise multiply. Without the clamp, the overshoot is scaled
back up by `cbv[30].x` and blows out.

### Where the code is emitted

After the **last** of the values being replaced, not merely after the values
being read. Both are legal for the splice itself, but only this position:

- leaves the vanilla result in scope, which `mix` needs to cross-fade against
  (`half`/`quarter` failed `spirv-val` with "ID has not been defined" until
  this was fixed);
- lands *below* the runtime branch merge in `8bbd5900` / `ef31e105`, so one
  splice bypasses both the ACES and Reinhard branches.

Dominance is then checked explicitly, per rewritten use, via the CFG — never
assumed. The "no use above the splice" guard is on **uses**, not definitions,
because in the two flat permutations `out == lin` and the definition
legitimately precedes the splice.

## 4. Presets

`punchy70desat` (`power=1.24, sat=1.175`) is `punchy70` with the chroma pulled
back 7.5% and nothing else touched — the middle of the 5–10% the user asked
for. `sat` multiplies the distance from luma, so the number *is* the chroma
scale. Contrast (`power`) is deliberately left alone: desaturating by
softening the curve would flatten the image as well.

Chroma, from `dev/agx_model.py` (greys stay exactly 0.0000 at every setting):

| sat | sun (8,6,3) | red neon (4,.02,.02) |
|---|---|---|
| 1.27 — `punchy70` | 0.1729 | 1.1810 |
| 1.207 — `punchy70.sat95` (−5%) | 0.1645 | 1.1022 |
| **1.175 — `punchy70desat` (−7.5%)** | **0.1602** | **1.0630** |
| 1.143 — `punchy70.sat90` (−10%) | 0.1559 | 1.0244 |

`punchy70desat` is what is installed. Picking finally between the three is
deferred ("we can do tuning later").

## 5. Verification

- 14 variants × 10 permutations = **140 modules, `spirv-val` clean, 0
  failures**.
- The two **HDR** modules of `punchy70` are **byte-identical** to the copies
  installed before the SDR work began. The SDR change is provably a no-op for
  the HDR look the user approved.
- All 8 SDR permutations changed.
- Splice verified by inspection in all three shapes:
  - `065fcdcc` — AgX emitted after `%389 = %382 / %386`; `%478 = OpFMul %386
    %3626`; `%475/476/477` have **zero** remaining uses.
  - `90fa8b3f` (flat, no curve) — the stack-2 merge phi is now
    `%398 = OpPhi %float %3517 %3250 ...`.
  - `ef31e105` (two runtime curves) — `%520/521/522` have zero uses and the
    merge phi reads `%3626/3627/3628`, bypassing **both** branches.
- `grade=0/1/2` all build clean on all ten, with the expected inputs and
  instruction counts (110/113/116) consistent with `pre_div` and `clamp_in`.
- Reported per build: `colour_space_proof` and `normalisation`.

The dead-code checker reports "LEAK %380/%381/%382" on `1c9000b4` and
`90fa8b3f`. **False positive** — those lines are AgX's own
`OpExtInst NMax %380 %float_0` input clamps, and in those two permutations
`out == lin` because there is no curve.

## 6. Current state

```
./dev/build_agx.sh                   # 14 variants x 10 permutations
./dev/install_agx.sh punchy70desat   # installed
```

Variants: `neutral`, `punchy`, `punchy70`, `punchy70desat`, `golden`,
`punchy70.sat95`, `punchy70.sat90`, `punchy70.nograde`, `neutral.nograde`,
`punchy70.preexp`, `punchy70.hue`, `half`, `quarter`, `diag`. All are graded
(`grade=1`) in both display modes unless the name says `nograde`.

`--site auto` picks `ap1` for HDR and `sdr2` for SDR. `--site sdr` is retained
only so old invocations fail loudly rather than silently; **it is wrong, do
not use it.**

## 7. Open

- Final look pick between `punchy70desat` / `.sat95` / `.sat90` — deferred by
  the user.
- The HDR site has **not** been re-examined for the same class of error the
  SDR site had. It splices at the AP1 value and looks right on screen, but
  "looks right" is what `--site sdr` also had going for it. The gate-anchored
  method in §3 applies to the HDR pair too and would either confirm the site
  or move it.
- `grade=2` (AgX does its own exposure) is built and never run. It is the
  variant with headroom for a proper exposure knob, but it needs the re-tune
  described in §1.
