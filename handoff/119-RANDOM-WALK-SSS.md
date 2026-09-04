# 119 — Random-walk subsurface: the design, and the two things that kill the cheap version

**Status: DESIGNED AND FEASIBILITY-GATED. NO PATCHER. Nothing is built and
nothing is installed.** `dev/walk_model.py` exists, self-checks (12
assertions), and its job was to decide whether to write the patcher. It says
*not the one that was scoped*, and this document is why.

## 0. The premise correction

The ask was to replace "the ray-traced SSS that's running right now."
**There isn't one.** What is running:

| | what it is | rays |
|---|---|---|
| the game's own skin SSS | a **screen-space** `SSS_Blur` diffusion pass, whose 32×8 kernel LUT `CallistoSSS.dll` already hijacks at `CopyTextureRegion` | none |
| `bleed` / `deep` (`97` §3.4) | Jensen `skin1` per-channel terminator colour bleed, pure ALU in the resolvers | none |
| `earglow-ll` (`111`, `113`) | thickness probe + light visibility, raygen-side | **3 inline ray queries per backlit light** |

So `earglow` is the only ray-traced subsurface transport in the build, and it
is not a scattering solve: it is a closed-form two-exponential transmittance
through **one** thickness probe. That is the thing a walk would replace, and
everything below is written against that reading.

## 1. The design, and its two blocking unknowns — both now closed

Chiang et al. 2016. At a skin hit, enter the medium, sample a free flight,
ray-query whether that flight left the manifold; if it did, that is the exit
point and the existing query C evaluates the light there; if it did not,
scatter and repeat.

**Unknown 1 — is there a per-frame random source?** *Yes.* `37` §1 read the
raygens' sampler off the disassembly: a per-pixel **and per-frame** seed
feeding a Numerical Recipes LCG, `s' = s·1664525 + 1013904223`,
`u = (s' & 0xFFFFFF)·2⁻²⁴`, present in all 12 `rgs_reference_main`
permutations at 9–11 sites. A walk can **clone** the chain (never consume the
game's own draws, or every other shading decision moves) for zero new
resources, and per-frame variation is exactly what lets the accumulator and
DLSS-RR integrate the estimator — which is what "amortized" has to mean if it
is not to need new storage.

**Unknown 2 — how many steps does skin need?** This is the one that decided
the outcome. `105` proved **six live ray query objects** in one raygen and no
more; A and C are already spent, so an unrolled walk gets **K ≤ 4**. There is
no loop, because no raygen splice in this project has ever added control flow.

## 2. Finding one — `111` is not a transmittance, so no walk can match it

The medium has to be calibrated against something. The only skin transport
model in this project that has ever been **read on screen and kept** is
`111` §2.3:

```
T_c(t) = 0.5·(e^{−a1_c·t} + e^{−a2_c·t}) · tint_c
tint = (1.0000, 0.0194, 0.0846)
```

At `t = 0` this is `tint`. **It transmits 1.9% of green through zero
thickness.** No homogeneous medium can do that — a real transmittance is 1 at
zero thickness — so the shipped ear glow's *colour* comes from a multiplicative
tint, not from transport. That is a legitimate art choice and it looks good;
it is simply not something a physically-based walk can reproduce.

The fit measures the damage. Fitting `(A_c, ld_c)` per channel over
0.5–8 mm (`calibrate_fast`, 60k walks per evaluation):

```
  R  A=0.890  ld=0.500 mm  rms(log T)=0.302
  G  A=0.190  ld=0.200 mm  rms(log T)=1.979     <-- factor of 7
  B  A=0.365  ld=0.160 mm  rms(log T)=1.602     <-- factor of 5

   L(mm)  walk (fitted)             111 closed form
     1.0   0.4864 0.2767 0.1730     0.4733 0.0094 0.0162
     3.0   0.1673 0.0164 0.0039     0.1097 0.0023 0.0006
     6.0   0.0157 0.0002 0.0000     0.0132 0.0003 0.0000
```

Red fits well. Green and blue cannot be fitted at all. **A walk will not
reproduce the shipped ear glow's hue**, and a rung that swapped one for the
other would read as a colour change, not as better transport.

For the record, the *other* skin parameterization in this repo is worse: the
Chiang inversion from Jensen `skin1`'s diffuse reflectance — the same
measurement `97` §3.4's `bleed` is built on — transmits **0.73 / 0.50 / 0.26**
through a 3 mm ear where `111` gives 0.11 / 0.0023 / 0.0006. The two
"skin" models in this project **disagree by a factor of 800 in green**. They
answer different questions (diffuse reflectance vs. directly transmitted
light) and neither is wrong, but nothing had ever put them side by side.

## 3. Finding two — K ≤ 4 inverts the hue

On the calibrated medium, `chiang()` gives

```
  alpha   = (0.9959, 0.5947, 0.8212)
  sigma_t = (1926.1, 1659.8, 2851.5) /m      mfp = (0.52, 0.60, 0.35) mm
```

Red is **nearly conservative** (α = 0.996): it barely absorbs, so it crosses
an ear by scattering tens of times. Green absorbs fast and dies within a few
events. A truncated walk throws away every path still inside the medium at
step K, and that penalty falls almost entirely on red — the channel the ear
glow *is*:

```
  fraction of converged energy kept, 3 mm ear
    K=1   R  1.4%   G 40.2%   B  5.3%
    K=2   R  2.6%   G 59.0%   B  8.8%
    K=3   R  4.1%   G 72.8%   B 14.5%
    K=4   R  6.0%   G 82.4%   B 20.4%     <-- the unrolled ceiling
    K=6   R 11.1%   G 93.3%   B 31.2%
```

At K = 4 the walk keeps 6% of the red and 82% of the green. That is not a
dim glow — **it is a hue inversion**: a backlit ear would go from red to a
sickly green-grey. `walk_model.check()` asserts this failure deliberately
(`K4_KEEP[0] < 0.15`, `K4_KEEP[1] > 5·K4_KEEP[0]`) so the file gates on the
negative result rather than quietly permitting a build.

**The unrolled K ≤ 4 design is dead.** Writing the patcher would have produced
something that gated cleanly, verified from shipped bytes, installed, and
looked wrong on screen for a reason no A/B could have attributed.

## 4. What this makes of "amortized"

The word was doing more work than it looked like. Red needs on the order of
20–30 scattering events. Three ways to get them:

1. **A real loop in the raygen**, one ray query object reused. `105`'s
   ceiling is on *simultaneously live* objects, so a loop is not bound by it
   and K = 30 is affordable in registers. The cost is control flow, which no
   splice in this project has ever added to a raygen — a genuine new risk
   class (`103` §7.1's hole is exactly about what has and has not been
   link-tested), not a blocker.
2. **Amortize across frames** — 1–2 steps per frame, walk state (position,
   direction, throughput, step count) persisted per pixel and continued next
   frame. This is what `116`'s scratch is for, and it converts a 30-step walk
   into 30 frames × 1 step at the existing query budget. It needs `116`
   §12.4's payload contract — value + **validity key** + **shader-owned
   epoch** — which is named there as required and **has never been built**.
   A walk resumed against a stale key is the pink trail of `116` §12.2 with
   radiance in it.
3. **Both**: a short loop per frame, continued across frames.

Route 2 is the one the ask named, and the model has now shown it is not a
nicety — it is the enabling mechanism. That reorders the board: `116` §12.4
is no longer groundwork for a nice-to-have, it is the prerequisite for this.

## 5. What I would build, in order

1. **`116` §12.4's payload contract**, as a probe, not a feature: a 3-word
   per-pixel record written by a resolver and read by a raygen, painted by
   whether the record is fresh / valid / stale. Nothing else in the tree can
   proceed to a temporal feature without it, and it is `116`'s own named
   next step.
2. **A single-frame walk with a loop** (route 1), red-only, `earglow`'s gates
   and query C verbatim, shot against `earglow-ll` on the same backlit ear.
   This is the first thing that could show the geometry win — light entering
   the cheek and leaving at the ear rim, which a slab probe cannot do — and
   it is falsifiable on its own.
3. **The tint question**, decided on screen before either: is the shipped ear
   glow's colour wanted, or was it a stand-in for transport that never
   existed? §2 says a walk cannot give both. That is a look call, not an
   engineering one.

## 6. Files

- `dev/walk_model.py` — the estimator, the shader's own LCG, the Chiang
  inversion, the slab reduction (3-D, by direction cosine — a ±1 projection
  over-transmits and was the first bug), the calibration, and 12 self-checks
  including the two falsifications. `--report` prints §3's table;
  `calibrate_fast()` reproduces §2's fit (~10 min).

Nothing else. No patcher, no verifier, no build script, no rung.

## 7. Honest summary

The feature is not impossible and the research is sound. What is dead is the
version that fits inside the proven query budget with no new machinery. The
real build is two builds, the first of which (`116` §12.4) is already written
down as necessary in another document, and it should not start until the
tint question in §5.3 has an answer.
