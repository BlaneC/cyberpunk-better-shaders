# 37 — Sampling decorrelation with the existing LCG: feasibility

Written 2026-08-29. Prompt: *Idea 6 — `24` §4 killed the blue-noise LUT, but
`29` B4 found the LCG state is already a loop-carried phi. So you can do
Cranley–Patterson / Perrier per-bounce rotation (Heitz & Belcour, "distributing
Monte Carlo error as blue noise") for zero new resources — offset the noise by
a per-bounce/per-sample constant so the 2 bounces and the future sample loop
decorrelate instead of correlating.*

**Verdict: no. Do not build it.** Three independent findings, each sufficient
on its own to kill it, and all three measured rather than argued. The idea's
*premises* are correct — the LCG state really is a loop-carried phi, it really
would cost zero new resources, and `24` §4 really did kill the LUT. What does
not survive is the step from those premises to a win.

Evidence is reproducible: `dev/validate_sampler_rng.py` is a bit-exact model of
the shader's seed hash and LCG, and every number below comes out of it.

---

## 1. What the sampler actually is

Read off `dev/disasm/live/d622fb9e1dcb8cd0.rgs_reference_main.spvasm`, not
from the earlier docs' summaries.

**Seed** (`:1395–1429`) — per-pixel *and* per-frame:

```
%140 = cbv[78].y + LaunchID.x            ; per-frame offset + pixel x
%149 = uint(float(%140) + cbv[58].x * float(LaunchID.y))   ; linear pixel index
%155 = cbv[63].x * 10                    ; per-frame word
%161 = ((%149 >> 1) ^ %155) * 1103515245
%163 = ((%155 >> 1) ^ %149) * 1103515245
%167 = (%161 ^ (%163 >> 3)) * 1103515245 ; the seed
```

**Generator** (`:1983–1995`) — Numerical Recipes LCG, three draws per group:

```
%916 = %704 * 1664525 ; %918 = %916 + 1013904223
%920 = %918 & 0x00FFFFFF ; %923 = float(%920) * 2^-24     ; u1 -> lobe select
… %927 …                 ; %930                           ; u2 -\ hemisphere
… %932 …                 ; %935                           ; u3 -/ sample
```

**State** (`:1826`) — `%704 = OpPhi %uint %167 %12276 %705 %12786`.

One correction to `29` §B4's wording: that phi is in `%12277`, the **bounce**
loop header, not the outer `%12276`. B4's plan is unaffected — it already says
a *new* phi is needed in the outer header — but the distinction is exactly what
this document turns on.

Structure across the family: all 12 `rgs_reference_main` permutations carry the
LCG, at 9–11 sites each (`&0xFFFFFF` 9–12, the `2^-24` scale 9–12). The seed is
single-use in every permutation — def plus exactly one use, the phi. No Sobol,
Halton, Owen or golden-ratio sequence appears anywhere in the family.

## 2. Finding one — the bounces are already decorrelated

This is the fatal one, and it follows from the phi that the idea cites as its
enabler.

`%704` advances through the loop body and `%705` carries the advanced state to
the next iteration. Bounce 0 consumes states `s₁…s_k`; bounce 1 starts at
`s_{k+1}`. The two bounces never draw the same numbers. The body runs 3
guaranteed advances and up to 7 more depending on branch, so `k ∈ [3,10]`;
measured over a full 1280×720 frame:

| k | corr(u1) | corr(u2) | corr(u3) |
|---|---|---|---|
| 3 | +0.001551 | +0.000776 | +0.000464 |
| 5 | +0.003283 | +0.000418 | +0.000389 |
| 7 | +0.000116 | −0.000965 | −0.001195 |
| 10 | +0.000060 | +0.000322 | −0.000054 |

Noise floor for 921,600 samples is `1/√N = 0.001042`. Worst observed |corr|
across all `k ∈ [3,10]` and all three draws is **0.0033**, ~3σ — consistent
with white noise, and with no `k` systematically worse than another.

**There is no bounce-to-bounce correlation to remove.** The premise that "the 2
bounces correlate" describes a sampler that reuses a sample index across
bounces. This one does not; the phi the idea correctly identified is precisely
what prevents it.

## 3. Finding two — Cranley–Patterson is a no-op on white noise

Cranley–Patterson rotation randomizes a **deterministic low-discrepancy point
set** — `u' = frac(u + c)` on a Sobol or lattice sequence preserves discrepancy
while making the estimate unbiased and independently replicable. That is what
it is for.

Applied to a pseudo-random uniform, `frac(u + c)` is a measure-preserving
bijection of `[0,1)` onto itself. The output is the same distribution, with the
same variance and the same independence structure. Measured:

| c | mean | var | corr(b0,b1) |
|---|---|---|---|
| 0.000000 | 0.499958 | 0.083273 | +0.001551 |
| 0.100000 | 0.500060 | 0.083275 | −0.000341 |
| 0.500000 | 0.499841 | 0.083400 | +0.000369 |
| 0.618034 | 0.499709 | 0.083371 | +0.000302 |

Per-bounce rotation (`c=0` on bounce 0, `c=0.5` on bounce 1) gives
corr = −0.0013. All of it is the noise floor. §2 and §3 compound: there is
nothing to fix, *and* the proposed tool cannot fix anything.

There is no low-discrepancy sequence in these modules for CP to act on
(§1). CP rotation without QMC underneath is arithmetic that costs an `OpFAdd`
and an `OpFract` per draw and changes no pixel.

## 4. Finding three — blue-noise error needs the resource `24` §4 killed

This is the part the idea gets backwards, and it is worth stating precisely
because the citation is real and the technique is real.

Heitz & Belcour 2019 does not distribute error as blue noise by rotating with a
*constant*. It works by giving each pixel an offset (or a permutation) drawn
from a **spatially blue-noise-distributed mask**, so that the *error across
pixels* becomes high-frequency and either reads better raw or survives a
spatial filter better. The blue-noise-ness of the result comes from the mask,
not from the rotation.

Radially-averaged power spectrum of the per-pixel error of a one-sample
estimator of a monotone integrand, 256×256. `HF/LF ≫ 1` is blue:

| configuration | var | LF | HF | HF/LF |
|---|---|---|---|---|
| shipped (white per-pixel LCG) | 0.0549 | 0.99 | 1.01 | **1.02** |
| shipped + CP constant `c=0.5` ← **Idea 6** | 0.0559 | 0.98 | 1.02 | **1.05** |
| shared base + blue per-pixel offset | 0.0556 | 0.08 | 1.92 | **23.31** |
| white LCG + blue per-pixel offset | 0.0556 | 1.03 | 1.00 | **0.97** |

(The blue mask used is validated in-place at HF/LF ≈ 59,000, mean 0.5000,
var 0.08333, so row 3 is not an artefact of a weak mask.)

Two things fall out, and the second is the non-obvious one:

1. **Row 1 vs row 2** — the proposed edit leaves the error spectrum white.
   1.02 → 1.05 is nothing. The variance is unchanged to three digits.
2. **Row 4 vs row 3** — even if the blue mask *did* exist, bolting it onto the
   current sampler still gives white error (0.97). The per-pixel LCG seed
   (`%167`, a hash of pixel index and frame) independently re-randomizes every
   pixel, which destroys the mask's spatial structure. Getting row 3 requires
   **replacing** the per-pixel seed with a shared base — deleting the hash at
   `:1395–1429` — not offsetting downstream of it.

So the honest dependency graph is the inverse of the idea's: CP rotation is the
part that is free and worthless; the blue mask is the part that is valuable and
was killed by `24` §4; and a *third* requirement — surrendering the per-pixel
seed across all 12 permutations — was not previously identified anywhere in the
handoff. That third item would also be a substantial regression risk on its
own: a shared base with a broken mask is a fully correlated frame.

## 5. Finding four (checked, also negative) — the low-24-bit mask

While in here, the one adjacent zero-resource change worth testing: the shader
takes the **low** 24 bits (`& 0xFFFFFF`), and low LCG bits are the classic weak
half — bit 0 has period 2, bit 1 period 4, bit 2 period 8, bit 3 period 16
(verified). The textbook fix is `>> 8`.

It is not warranted here. The shader uses two *consecutive* draws as its 2D
hemisphere sample, which is the worst case for LCG lattice structure, so that
is the right thing to measure — χ²/dof of consecutive pairs within one stream:

| bins | shipped `s & 0xFFFFFF` | high bits `s >> 8` |
|---|---|---|
| 16² | 1.0115 | 1.1216 |
| 64² | 0.9207 | 0.9977 |
| 256² | 0.9400 | 0.9894 |

Both sit at 1.0 within noise and neither is systematically better. The
short-period bits are real but weigh under `2^-20` in `u`, which is far below
anything a direction vector resolves. **No change recommended** — recorded so
the next person does not re-derive it.

## 6. What this means for `29` §B4 / `32` §4

The sample loop is unaffected by this verdict, in both directions:

- **It does not need CP rotation.** B4 already states the RNG comes free
  because the state is a loop-carried phi; §2 above confirms that mechanism
  empirically. Threading `%704` through a new outer-header phi gives each
  sample a fresh, uncorrelated segment of the stream. The idea's "it composes
  with B4" is true but empty — B4 already has the property CP was offered to
  provide.
- **It gains nothing from it.** Adding a per-sample constant to an
  already-advancing stream is the same no-op as §3.

So `32` §4's ladder is unchanged. The gate is still the §B5 sentinel launch,
and nothing here moves it forward or back.

## 7. If the blue-noise route is ever reopened

Not recommended, but the requirements are now known, which they were not
before. It needs all three:

1. a spatially blue-noise mask available in the raygen — `24` §4 established
   there is no such upload to hijack, so this means *adding* a resource, which
   the swap layer cannot do (it substitutes SPIR-V in `vkCreateShaderModule`;
   it does not create descriptors). An in-shader analytic blue-noise hash is
   the only route that does not need a binding, and those are substantially
   worse than a mask;
2. replacing the per-pixel seed hash with a shared base, across 12
   permutations (§4, row 4);
3. and a reason to believe the gain survives the denoiser — `29` §B7 and
   `32` §3 both say NRD/DLSS-RR applies a material-unaware spatial filter to a
   1280×720 integrator output. Blue-noise error is *specifically* the error a
   spatial filter removes best, which is the argument for it; it is also
   already being removed, which caps the visible gain.

Item 1 alone is a GOTCHAS §13 problem — existence is not addressability — and
it fails at existence.

## 8. Files

| file | what |
|---|---|
| `dev/validate_sampler_rng.py` | new; bit-exact seed+LCG model, the four tests above |
| `handoff/37-SAMPLING-DECORRELATION.md` | this document |

No shader, patcher, layer or Lua change. Nothing was built.

## 9. Evidence index

- Reference raygen: `dev/disasm/live/d622fb9e1dcb8cd0.rgs_reference_main.spvasm`
  — seed hash `:1395–1429`, LCG `:1983–1995`, state phi `:1826`,
  bounce loop header `%12277`, outer degenerate loop `%12276`/`%12818`.
- Family survey: all 12 `*.rgs_reference_main.spvasm` in `dev/disasm/live/`
  — LCG sites 9–11, `&0xFFFFFF` 9–12, `2^-24` scale 9–12, seed single-use 12/12,
  low-discrepancy sequences 0/12.
- All statistics: `python3 dev/validate_sampler_rng.py`.

## 10. For GOTCHAS

Proposed addition, in the spirit of §8 (*ask whether the engine already
exposes it*):

> **Before importing a sampling technique, check which of its preconditions
> this renderer actually meets.** Cranley–Patterson randomizes a *low-discrepancy
> point set*; on a plain LCG it is a measure-preserving bijection and provably
> changes nothing. Heitz & Belcour's blue-noise error distribution comes from a
> *blue-noise mask*, not from the rotation, and it additionally requires
> surrendering the per-pixel seed — a white per-pixel seed destroys the mask's
> spatial structure downstream. A named technique from a real paper can still be
> a no-op here; the cheap check is to model the shader's RNG in forty lines of
> numpy and measure, which is what `dev/validate_sampler_rng.py` does.
