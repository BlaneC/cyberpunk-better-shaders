# 52 — Spectral SSS kernel: per-channel falloff from measured skin optics

`--preset spectral` is built, validated and parked. **Nothing here has been on
screen.** No launch, no `make install`, no commit — offline Python against the
vanilla LUT dump only. The A/B (`kernel=spectral` vs `kernel=detail`, one
variable) is the next session's job, and until it runs this is a file, not a
feature.

One line: **green comes out byte-identical to vanilla, red gets a tighter core
and a longer tail, blue gets tighter everywhere, and no tap moves.** The 10×
radius trap (`33` §1) cannot be re-entered by construction — the `.a` offsets
are byte-identical to the engine's own and the centre-tap share of every
channel is preserved exactly.

Reproduce, both commands, ~1 s each:

```
python3 dev/author_callisto_kernel.py --inspect          # §2's measurements
python3 dev/author_callisto_kernel.py --preset spectral \
        --out dev/kernels/kernel.spectral.bin            # §4's validation
```

## 1. What shipped

| file | what |
|---|---|
| `dev/author_callisto_kernel.py` | `spectral` preset (new construction, not new knobs), `--inspect` evidence mode, `validate()` on every write |
| `dev/kernels/kernel.spectral.bin` | 4096 B |
| `dev/kernels/kernel.spectral.json` | texels + the coefficients, `ld`, `d`, per-block anchor fits, mm/offset-unit, and the construction in prose |

The four existing `.bin` files are untouched and **still regenerate
byte-identically** from the edited script (`cmp` on all four, plus `vanilla`
== the engine dump). `init.lua`, `sync_settings.sh`, `Makefile` untouched —
§7 has the diff for the main session.

## 2. What the vanilla kernel actually is — five measurements

Confidence: **high**, all re-measured for this document from
`dev/sss_kernel_texture.bin`, all reproducible with `--inspect`.

**2.1 The layout in the generator header holds, and the offsets are
quadratic.** Rows 0..2 carry data, 3..7 are zero, x=30..31 are zero,
sub-kernels at (0,15) (15,9) (24,6). Within a sub-kernel the tap offsets are
`r_n = k·n²` to the last bit (row 0 sub 0: `k = 8.138e-6 = 1/122880`, taps at
1,4,9,…,144 k). Taps **0,1,2** of sub-kernel 0 and tap 0 of the other two sit
at offset **exactly 0.0**. Under the documented model (offset = sample
distance) those all sample the same texel, so only their **sum** matters —
which disposes of the "red 1.0 spike" the old header worried about: it is not
a spike, it is one term of a centre total.

**2.2 The centre group is most of the kernel.** Share of each channel's
sub-kernel weight sitting at offset 0:

| block | R | G | B |
|---|---|---|---|
| row0 base0 | 71.3 | 50.3 | 50.3 |
| row1 base0 | 80.5 | 75.8 | 75.2 |
| row2 base0 | 80.5 | 75.2 | 74.7 |
| row1 base15 | 6.6 | 13.3 | 15.3 |
| row1 base24 | 15.6 | 28.5 | 32.0 |

This number *is* the "how much of the pixel's own lighting survives" quantity
that `33` §1 blames for soft faces. `spectral` does not touch it (§3.3).

**2.3 The weights are a profile times a quadrature, and the quadrature looks
like an annulus.** Fitting `w_i = A·R(r_i;d)·J_i` with Burley's `R`, the
annulus envelope `J = r·dr` beats the 1-D line envelope `J = dr` in **18 of
27** (block × channel) fits — and in **every** red fit by 3–5× (rms 0.09–0.16
vs 0.38–0.59). The 9 losses are all in the narrow blocks (row 0's green/blue,
the 6-tap sub-kernel), where only 3–6 taps are usable and the two
envelopes are not separable. Read
that as: the LUT is a 2-D disc kernel with tap-density compensation baked in,
not a 1-D separable line. **The construction does not depend on this** — a
shared envelope cancels out of a ratio-reshape (§3.2) — it matters only for
the anchor fit.

**2.4 Vanilla already has per-channel widths, and they are far less separated
than skin optics.** Fitting `d` from the *channel ratios* `w_R/w_G`, `w_B/w_G`
is envelope-free (the offsets are shared, so any `J` cancels):

| block | vanilla `d_R/d_G` | vanilla `d_B/d_G` |
|---|---|---|
| row1 base0 | 1.76 | 0.81 |
| row1 base15 | 1.74 | 0.82 |
| row2 base0 | 1.92 | 0.73 |
| row2 base24 | 1.79 | 0.79 |
| row0 base0 | 4.34 | 0.61 |
| **physics (§3.1)** | **2.69** | **0.50** |

So the brief's premise needs a correction: **"one shape for all channels with
a tint" describes this mod's presets, not the engine's kernel.** The engine
authored three different shapes. They are just not the measured ones — rows
1/2 under-separate red and badly under-separate blue.

**2.5 Red is not authored per row.** Between row 0 and rows 1/2:

```
block     R      G      B      offset
base0     1/15  15/15  15/15  12/15
base15    0/9    9/9    9/9    8/9
base24    0/6    6/6    6/6    5/6
```

Every green and blue weight is re-authored per row and every non-zero offset
changes, but the red weights are **bit-identical across all three rows** (the
one exception is tap 0 of sub-kernel 0). Since the radii differ per row, that
means red's *physical* profile differs per row by accident, and at least two
of the three rows have a red channel inconsistent with their own green. This
is the single strongest argument for the preset: `spectral` derives red from
each row's own green, so each row becomes internally consistent.

**2.6 (inherited, not re-verified here) the engine normalizes per channel.**
The generator header states `out = Σ(w·c)/Σ(w)` per channel. If so, the
per-channel *sums* have no visual effect whatsoever — the kernel's apparent
"tint" is not a tint, only the per-channel blur *width* is real, and
"energy preservation" is bookkeeping that keeps the file diffable. Everything
below preserves the sums anyway.

## 3. The math actually used

### 3.1 Optics — as briefed, no changes

Jensen/Marschner/Levoy/Hanrahan 2001, skin1, per mm: `σ′s = (0.74, 0.88,
1.01)`, `σa = (0.032, 0.17, 0.48)`. `σ′t = σa + σ′s`, `σtr = √(3·σa·σ′t)`,
`ld = 1/σtr = (3.6733, 1.3665, 0.6827) mm`. Burley `d = ld/s` with `s = 3.5`
held **constant** (Christensen–Burley's `s = 3.5 + 100(A−0.33)⁴` is
near-constant over skin albedos; it cancels out of the ratios anyway, and the
absolute scale is anchored, not physical): `d = (1.0495, 0.3904, 0.1951) mm`,
**`d_R : d_G : d_B = 2.6880 : 1 : 0.4996`**. Those three numbers are the only
physics in the file.

### 3.2 Anchor and construction

`d_G` is fitted **per (row, sub-kernel)** to that block's own vanilla green
weights — model `w = A·R(r;d)·r·dr`, log space, `A` profiled out, residuals
weighted by `w/Σw` so the fit follows the energy and not the 1e-23 tail;
golden-section on `ln d`, deterministic, no scipy. Then `d_R = 2.688·d_G`,
`d_B = 0.4996·d_G` for that block.

```
row base  n   d_green      d_red       d_blue     fit rms(log)  mm/offset-unit
  0    0  12  9.3258e-06  2.5068e-05  4.6590e-06    0.2319       4.187e+04
  0   15   8  9.5096e-06  2.5562e-05  4.7508e-06    0.2034       4.106e+04
  0   24   5  1.2300e-05  3.3064e-05  6.1450e-06    0.0288       3.174e+04
  1    0  12  4.3738e-05  1.1757e-04  2.1851e-05    0.1931            8927
  1   15   8  4.2373e-05  1.1390e-04  2.1169e-05    0.1783            9214
  1   24   5  4.0793e-05  1.0965e-04  2.0379e-05    0.2030            9571
  2    0  12  2.6233e-05  7.0514e-05  1.3105e-05    0.2015       1.488e+04
  2   15   8  2.5664e-05  6.8986e-05  1.2821e-05    0.1724       1.521e+04
  2   24   5  2.4789e-05  6.6634e-05  1.2384e-05    0.2060       1.575e+04
```

The mm/offset-unit column is bookkeeping only and is **not** a claim about the
engine's units — the runtime scales these offsets by a material/CB width
factor nobody here has read. The three rows imply three different scales,
which is consistent with them being three authored SSS widths.

Then the ratio-reshape the brief recommends, off the **green** envelope:

```
E_i   = w_vanilla_green(r_i) / R(r_i; d_G)      (off-centre taps)
w_c,i = E_i · R(r_i; d_c)                        (per channel)
scale each channel so Σ(off-centre) equals vanilla's
```

`E_i` carries whatever windowing and tap-density compensation the engine
baked in, and it is channel-independent because the offsets are shared. Green
is byte-identical to vanilla by construction (its ratio is ≡1). **Verified:
all 256 green words and all 256 alpha words are bit-identical to vanilla; 75
red and 75 blue texels changed = the 25 off-centre taps × 3 rows.**

Not chosen: `w_new_c = w_vanilla_c · R(d_c)/R(d_G)`, the brief's literal
formula. Vanilla's red is already 1.7–4.3× wider than its green (§2.4), so
multiplying it *again* by the physics ratio compounds two spectral spreads
and lands red at an effective `d_R/d_G` near 4.5–11. That is the widening
direction this project has already been burned by. Basing every channel on
green makes the physics ratio the *whole* answer instead of an addition to an
existing one.

### 3.3 Where I left the brief — two places, both measured

**(a) The centre group is left exactly as vanilla; the disc integral is
computed as evidence and not applied.** Brief item 6 asks for `R(0)` to be
resolved by integrating `R` over a small disc. I built that version first.
The disc integral is clean — `∫₀^rc R·2πr dr = ¼[(1−e^{−rc/d}) +
3(1−e^{−rc/3d})]`, which is what makes Burley normalized — but the premise
fails on measurement: with `rc = r₁/2`, a Burley disc at the fitted `d_G`
holds **5–44%** of the profile's energy, while the kernel's centre group holds
**50–86%** (§2.2, and both numbers print per block in the generator). The
centre group is therefore *not* a disc integral of the profile; it is an
authored centre-preservation term. Re-deriving it from the profile does what
you would expect:

| row1 base0 | centre share R/G/B | mean radius R (all taps) | mean radius R (first 6) |
|---|---|---|---|
| vanilla | 80.5 / 75.8 / 75.2 | 42.8 | 5.50 |
| disc-integral variant (rejected) | **50.4** / 75.8 / 85.5 | **205.6** (×4.8) | 12.47 |
| shipped `spectral` | 80.5 / 75.8 / 75.2 | 80.7 (×1.9) | 3.76 |

Moving 30 points of red off the centre tap is exactly the move `33` §1 blames
for the soft faces, justified by a model the data says does not describe the
centre group. So: **off-centre taps only, `R(0)` never evaluated, centre group
byte-identical per channel.** The disc integral stays in the code (it decides
nothing) purely so `--preset spectral` prints the 50–86 vs 5–44 comparison
that killed it.

**(b) Normalization is applied over the off-centre taps, not the whole
sub-kernel.** Brief item 7 asks for vanilla's per-channel per-sub-kernel sums.
Because the centre group is untouched, scaling the off-centre block to
vanilla's off-centre sum preserves the total sum **and** the centre share.
Strictly stronger than what was asked; the item-7 check passes to 2.1e-08.
This differs from `detail`/`balanced`/`callisto`, which renormalize the whole
sub-kernel and so shave 1–8 points off the centre share as a side effect (see
the `detail` rows in §5's centre table) — `spectral` is the only preset that
does not.

## 4. Validation — all pass

Printed by the generator on every write (`validate()`, re-read from the
written `.bin`, so these are the float32 the engine sees):

```
  size 4096 bytes OK
  rows 3..7 all zero OK
  .a offsets identical to vanilla: OK
  per-channel per-sub-kernel weight sums vs vanilla: worst relative error 2.069e-08 OK
  ALL CHECKS PASSED
```

Independent byte-level re-check, outside the generator:

| check | result |
|---|---|
| file size | 4096 |
| `.a` words vs vanilla | 256/256 bit-identical |
| green words vs vanilla | 256/256 bit-identical |
| red / blue texels changed | 75 / 75 (= 25 off-centre taps × 3 rows) |
| rows 3..7, and x=30..31 | all zero |
| NaN / Inf / negative weights | none |
| per-channel per-sub-kernel sums | all 27 within 1e-6 relative |
| off-centre profile `w/(r·dr)` monotone non-increasing | yes, all 27 (vanilla likewise) |
| `detail`/`balanced`/`callisto`/`vanilla` regenerate | byte-identical to committed |
| `vanilla` vs engine dump | byte-identical |

The monotonicity row matters: `spectral`'s raw red *weights* rise and fall
across the taps, which looks alarming in a table — but that is the `r·dr`
quadrature, not the profile. The underlying profile is monotone at every tap,
so there is no ring to worry about. Vanilla's red weights do the same thing.

## 5. Comparison table

Row 1, sub-kernel `baseX=0` (the block whose first 6 taps the runtime CB was
observed reading). Weights as **% of that channel's sub-kernel sum** — the
only form that means anything, since the engine normalizes per channel.

**R** (`callisto`'s taps sit at 10× the listed offsets)

| tap | offset | vanilla | detail | callisto | spectral |
|---|---|---|---|---|---|
| 0 | 0 | 39.824 | 36.485 | 21.056 | 39.824 |
| 1 | 0 | 39.824 | 36.485 | 21.056 | 39.824 |
| 2 | 0 | 0.880 | 0.806 | 0.465 | 0.880 |
| 3 | 0.000009 | 1.754 | 1.652 | 4.103 | 1.335 |
| 4 | 0.000038 | 3.342 | 3.498 | 10.034 | 2.679 |
| 5 | 0.000085 | 4.095 | 6.003 | 22.377 | 2.494 |
| 6 | 0.000152 | 3.403 | 4.988 | 6.920 | 1.883 |
| 7 | 0.000237 | 2.187 | 3.206 | 4.448 | 1.644 |
| 8 | 0.000342 | 1.487 | 2.180 | 3.024 | 1.608 |
| 9 | 0.000465 | 1.066 | 1.563 | 2.168 | 1.612 |
| 10 | 0.000608 | 0.783 | 1.148 | 1.593 | 1.517 |
| 11 | 0.000769 | 0.582 | 0.853 | 1.183 | 1.303 |
| 12 | 0.000949 | 0.415 | 0.609 | 0.844 | 1.205 |
| 13 | 0.001149 | 0.277 | 0.406 | 0.563 | 1.387 |
| 14 | 0.001367 | 0.081 | 0.118 | 0.164 | 0.805 |

**G**

| tap | offset | vanilla | detail | callisto | spectral |
|---|---|---|---|---|---|
| 0 | 0 | 50.782 | 50.088 | 31.998 | 50.782 |
| 1 | 0 | 22.608 | 22.299 | 14.246 | 22.608 |
| 2 | 0 | 2.438 | 2.404 | 1.536 | 2.438 |
| 3 | 0.000009 | 4.796 | 4.864 | 11.588 | 4.796 |
| 4 | 0.000038 | 7.575 | 8.122 | 20.797 | 7.575 |
| 5 | 0.000085 | 5.117 | 5.300 | 12.707 | 5.117 |
| 6 | 0.000152 | 2.759 | 2.857 | 2.942 | 2.759 |
| 7 | 0.000237 | 1.688 | 1.749 | 1.800 | 1.688 |
| 8 | 0.000342 | 1.080 | 1.119 | 1.152 | 1.080 |
| 9 | 0.000465 | 0.637 | 0.660 | 0.680 | 0.637 |
| 10 | 0.000608 | 0.315 | 0.326 | 0.336 | 0.315 |
| 11 | 0.000769 | 0.127 | 0.132 | 0.136 | 0.127 |
| 12 | 0.000949 | 0.050 | 0.052 | 0.053 | 0.050 |
| 13 | 0.001149 | 0.022 | 0.023 | 0.024 | 0.022 |
| 14 | 0.001367 | 0.005 | 0.005 | 0.005 | 0.005 |

**B**

| tap | offset | vanilla | detail | callisto | spectral |
|---|---|---|---|---|---|
| 0 | 0 | 52.508 | 52.065 | 33.420 | 52.508 |
| 1 | 0 | 19.757 | 19.590 | 12.575 | 19.757 |
| 2 | 0 | 2.963 | 2.938 | 1.886 | 2.963 |
| 3 | 0.000009 | 5.793 | 5.905 | 13.663 | 8.375 |
| 4 | 0.000038 | 8.375 | 8.986 | 22.241 | 9.558 |
| 5 | 0.000085 | 4.762 | 4.722 | 10.494 | 4.506 |
| 6 | 0.000152 | 2.587 | 2.565 | 2.533 | 1.592 |
| 7 | 0.000237 | 1.552 | 1.539 | 1.520 | 0.538 |
| 8 | 0.000342 | 0.931 | 0.923 | 0.912 | 0.158 |
| 9 | 0.000465 | 0.475 | 0.471 | 0.465 | 0.037 |
| 10 | 0.000608 | 0.189 | 0.188 | 0.186 | 0.006 |
| 11 | 0.000769 | 0.068 | 0.067 | 0.066 | 0.001 |
| 12 | 0.000949 | 0.027 | 0.027 | 0.027 | 0.000 |
| 13 | 0.001149 | 0.011 | 0.011 | 0.011 | 0.000 |
| 14 | 0.001367 | 0.002 | 0.002 | 0.002 | 0.000 |

Weighted mean radius `r̄ = Σ(w·r)/Σ(w)`, ×1e6 offset units, sub-kernel 0:

| block | window | preset | R | G | B | R/G | B/G |
|---|---|---|---|---|---|---|---|
| row1 | all 15 | vanilla | 42.80 | 26.25 | 22.88 | 1.63 | 0.87 |
| row1 | all 15 | detail | 62.12 | 27.28 | 22.97 | 2.28 | 0.84 |
| row1 | all 15 | callisto | 1003.19 | 396.29 | 334.82 | 2.53 | 0.84 |
| row1 | all 15 | **spectral** | 80.65 | 26.25 | 12.73 | **3.07** | **0.48** |
| row1 | first 6 | vanilla | 5.50 | 8.26 | 8.28 | 0.67 | 1.00 |
| row1 | first 6 | detail | 7.79 | 8.68 | 8.50 | 0.90 | 0.98 |
| row1 | first 6 | callisto | 294.87 | 213.80 | 198.47 | 1.38 | 0.93 |
| row1 | first 6 | **spectral** | 3.76 | 8.26 | 8.47 | **0.46** | 1.03 |
| row2 | all 15 | vanilla | 30.57 | 16.16 | 13.44 | 1.89 | 0.83 |
| row2 | all 15 | **spectral** | 58.85 | 16.16 | 7.83 | 3.64 | 0.48 |
| row0 | all 15 | vanilla | 54.01 | 12.15 | 8.51 | 4.44 | 0.70 |
| row0 | all 15 | **spectral** | 49.42 | 12.15 | 6.26 | 4.07 | 0.52 |

`B/G` lands on 0.48–0.52 in every block, i.e. on the physical 0.4996.
`R/G` overshoots 2.69 because a mean-radius ratio is not a `d` ratio — the
centre spike and the tap truncation both bend it — the *construction* sets
the `d` ratio exactly. Note row 0: `spectral` makes red **narrower** than
vanilla, which is §2.5 being repaired (row 0's green is narrow, so its
physically-consistent red is narrow too; vanilla's red there was copied from
another row).

Centre share, sub-kernel 0, showing that only `spectral` preserves it:

| block | vanilla R/G/B | detail | callisto | spectral |
|---|---|---|---|---|
| row1 base0 | 80.5 / 75.8 / 75.2 | 73.8 / 74.8 / 74.6 | 42.6 / 47.8 / 47.9 | **80.5 / 75.8 / 75.2** |

## 6. What to expect on screen, and the A/B

Blunt: **this may read as a small change, and there is one measured reason to
expect that.** The generator's `USED_TAPS = {0: 6}` records a runtime CB
observed with `baseX=0, tapCount=6` — if that is what the game does, it reads
taps 0–5 of sub-kernel 0 and nothing else, and inside that window `spectral`
*tightens* red's core (r̄ 5.50 → 3.76) while green is identical and blue moves
2%. Red's long tail — the visible part of the physics — lives in taps 8–14,
which that CB never reads. If instead the full 15 taps are sampled (other
material profiles, other quality levels, other sub-kernels), red's mean radius
roughly doubles and blue's halves. I could not settle which, offline: the
`USED_TAPS` claim exists only as a comment in the generator with no supporting
document, and I did not verify it.

So the honest prediction is directional, not quantitative: **skin gradients
should warm at the terminator and desaturate less in the blue; texture and
pore detail should be untouched, because green is bit-identical and the centre
share is preserved.** If the A/B shows *less* detail than `detail`, something
in this construction is wrong and the numbers above are where to look.

A/B protocol (`45`): `kernel=spectral` vs `kernel=detail`, one variable,
settings stated before launch, both sides in one session. `detail` is the
right control, not `off`/`vanilla` — it is the current default and the only
comparison that answers "is the physics better than the hand-tuned tail".

**Deploy check first** (house rule; the game runs copies): `make release` then
`make install`, then `cmp dev/kernels/kernel.spectral.bin
"$GAME_DIR/red4ext/plugins/CallistoSSS/kernels/kernel.spectral.bin"` before
reading anything on screen. `sync_settings.sh` copies the chosen preset over
`kernel.bin` at boot, so also confirm the launch journal says
`kernel=spectral` and not the `detail` fallback.

## 7. Registration diff for the main session

**`init.lua`, `KERNEL_PRESETS` (line ~106) — append, do not insert:**

```lua
 local KERNEL_PRESETS = {
     { id = "off",      label = "Off -- engine kernel (A/B control)" },
     { id = "detail",   label = "Detail -- tight core, most pore definition (default)" },
     { id = "balanced", label = "Balanced -- between detail and callisto" },
     { id = "callisto", label = "Callisto -- wide red tail, softest" },
     { id = "vanilla",  label = "Vanilla (re-authored) -- should match Off; a tooling check" },
+    { id = "spectral", label = "Spectral -- per-channel biophysical falloff (Jensen skin1)" },
 }
```

Append, because `KERNEL_PRESETS[2]` is hard-coded twice as the fallback
(lines ~409 and ~411) and must stay `detail`. Nothing else in `init.lua`
needs to change: line 163 already coerces an unknown id back to `detail`, and
`KERNEL_LABELS`/`KERNEL_INDEX` are built from the table.

Optional, same file, the selector tooltip (line ~405), one sentence before
"Engine data, not a shader":

```lua
 .. "indistinguishable from Off -- if it is not, the tooling is wrong. "
+.. "Spectral gives each channel its own measured diffusion width (red "
+.. "widest, blue tightest) at the engine's own blur radius. "
 .. "Engine data, not a shader: unaffected by the MASTER switch. "
```

**`release/game/red4ext/plugins/CallistoSSS/sync_settings.sh` — no change
needed.** Its kernel block resolves the preset **by filename**
(`ksrc="$PLUGIN_DIR/kernels/kernel.$kernel.bin"`, with a `detail` fallback if
the file is missing), so `kernel=spectral` works the moment the `.bin` is
deployed. The only thing stale is the comment on line ~58 listing
`(detail | balanced | callisto | vanilla)`; cosmetic, update it or don't.

**`Makefile` — no change needed.** `KERNELS := $(wildcard
dev/kernels/kernel.*.bin)` already picks the new file up, and `make release`
copies it into `$(R4E_DST)/kernels/`.

## 8. Confidence

| claim | confidence | basis |
|---|---|---|
| 4096 B, rows 3..7 zero, offsets/green bit-identical to vanilla, sums preserved | **certain** | byte-level checks, §4, two independent implementations |
| the four existing presets are unchanged | **certain** | `cmp` on all four |
| the `d` ratios 2.688 : 1 : 0.4996 follow from the cited coefficients | **certain** | arithmetic, printed by the tool |
| vanilla's centre group is not a disc integral of its own profile (50–86% vs 5–44%) | **high** | §2.2/§3.3, measured per block |
| vanilla's own `d` ratios are 1.7–1.9 / 0.73–0.82 in rows 1–2, i.e. under-separated vs physics | **high** | envelope-free ratio fit, `--inspect` §4; two estimators, same ordering |
| red is bit-identical across rows while offsets and G/B are not | **certain** | `--inspect` §1 |
| the annulus (`r·dr`) quadrature | **medium** | 18 of 27 fits, decisive only for red; the construction does not depend on it |
| the absolute anchor `d_G` | **medium** | the green fit and the envelope-free ratio fit differ by 37–62% in rows 1–2 and disagree badly in row 0. A ±25% error on `d_G` moves red's `R/G` from 3.07 to 2.17–4.75 (all taps). Direction robust, magnitude not |
| the engine normalizes per channel, so sums are cosmetic | **medium** | inherited from the generator header; not re-verified against the shader here |
| centre taps sample the same texel (their split is cosmetic) | **medium** | follows from their offsets being exactly 0.0 under the documented model; not verified in the shader |
| `USED_TAPS = {0: 6}` — the runtime reads only 6 taps | **low** | a code comment with no supporting document; it changes the *predicted* look materially (§6) |
| that `spectral` looks better than `detail` | **unknown** | never been on screen. That is the next session's only job here |
