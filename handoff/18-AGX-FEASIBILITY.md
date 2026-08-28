# 18 — AgX tonemapper: feasibility, and the built patcher

Written 2026-08-27. Verdict: **feasible, and the best-posed target this project
has had.** One module, one write site, the exact input AgX wants, and a blast
radius that cannot touch lighting.

## 1. The tonemap LUT is generated, not uploaded

`strings` on the exe:

```
CRenderNode_GenerateTonemappingLUT
CRenderNode_ApplyBloomAndTonemapping
ColorGradingLutParams   ColorGrade   ColorGradeV2
```

So the RED4ext upload hook (`main.cpp:55`, the SSS-kernel mechanism) **cannot**
reach it — there is no CPU→GPU upload to intercept. It has to be a SPIR-V swap,
which is the layer's core competence.

## 2. The generator is `b174eb4af0fea652`

From `capA_prov.jsonl`, it is the only module that both samples a 32³ LUT and
writes a 3D image:

```
b174eb4af0fea652
   R 0x19b4d4d0  32x32x32 R32G32B32A32_SFLOAT usage=7   (authored grading LUT, uploaded)
   W 0x19b6d4c0  48x48x48 R16G16B16A16_SFLOAT usage=15  (generated tonemap+grade LUT)
```

`OpExecutionMode LocalSize 8 8 8` → 48³/8³ = 216 workgroups. 5919 lines,
976 `FMul`, 220 `Fma`, 194 `Log`, 119 `Exp`, 21 `OpDot` (≈7 colour matrices),
16 `OpImageSampleExplicitLod` (the authored grade), and **exactly one
`OpImageWrite`**. The constant pool is full of small fitted coefficients
(0.00214758, −0.00284131, 0.00307257 …) — an ACES-style rational/polynomial fit
plus colour-space matrices.

There are five more 48³ RGBA16F images (`0x19b6c0e0`, `0x19b6cad0`,
`0x19b6deb0`, `0x1c824ae0`, `0x1c8318c0`) — a ring, for blending between
grading setups.

## 3. Why this is a clean splice

**The input AgX needs is already computed, at the top of the entry block:**

```
%82,%83,%84   = float(gl_GlobalInvocationID.xyz)
%94           = cbv[41].y - 1                      // LUT size - 1  (= 47)
%95..%97      = gid / 47                           // normalised grid coord
%100          = cbv[41].w                          // shaper offset
%104          = cbv[41].z                          // shaper scale
%105..%107    = (t - offset) / scale
%109,%110,%111 = Exp2(...)                         // <-- LINEAR SCENE-REFERRED RGB
```

**The LUT is log2-shaped.** `%109/%110/%111` are linear HDR radiance for this
cell — exactly AgX's expected input domain, and exactly why a 48³ LUT can cover
the range at all.

**The output site is unambiguous:**

```
%3141 = OpCompositeConstruct %v3uint  %75 %78 %81          // raw grid id
%3142 = OpCompositeConstruct %v4float %3132 %3135 %3138 %float_0
        OpImageWrite %58 %3141 %3142
```

That is the exact shape `patch_compute_brdf.find_image_writes` already matches,
and replacing the components at an `OpImageWrite` is what
`build_tint_writes` / `build_hunt_writes` already do. `%109–%111` are defined in
the entry block, so they dominate the write trivially — no refetch, no
`acquire_class_shift`, none of the machinery that made the hair work fragile.

**We do not need to understand the other 5900 lines.** Read the input, write the
output, ignore the middle.

## 4. Scorecard

| criterion | assessment |
|---|---|
| modules to patch | **1** |
| splice sites | **1** |
| input available | yes — linear scene-referred RGB, pre-decoded |
| dominance | trivial (entry block → final block) |
| cost | 110,592 invocations per grading update. Negligible. |
| blast radius | display transform only; cannot affect lighting or geometry |
| null-result risk | **near zero** — a wrong tonemapper is unmissable |
| existing tooling | patcher already inserts constants + arithmetic and rewrites the texel |
| output precision | RGBA16F over a log2-shaped 48³ domain — adequate |

Contrast with the hair track: 70 modules, unproven sites, tile granularity,
half resolution, and two weeks without a confirmed pixel.

## 5. The implementation

Replace `%3132/%3135/%3138` with AgX of `%109/%110/%111`:

1. **inset matrix** — AgX rotated primaries (3 `OpDot`, or 9 Fma)
2. **log2 encode** — `(log2(max(x, 1e-10)) − (−12.47393)) / (4.026069 + 12.47393)`,
   clamped to [0,1]
3. **sigmoid** — the standard 7th-order fit, 7 `Fma` per channel
   (`−17.86x⁷ + 78.01x⁶ − 126.7x⁵ + 92.06x⁴ − 28.72x³ + 4.361x² − 0.1718x + 0.002857`)
4. **outset matrix** — inverse inset
5. optional **look** (punchy / golden): offset, slope, power, saturation
6. **output encode** — see risk 1

~80–120 SPIR-V instructions. A new `--tier agx` in `patch_compute_hair.py`
(or a small dedicated patcher), with `--set` knobs for the look parameters so it
is tunable the same way the BRDF knobs are.

## 6. Risks, and how each is settled

1. **Output encoding.** Does `ApplyBloomAndTonemapping` expect the LUT to hold
   display-encoded (≈2.2) or linear values? The generator's output chain is not
   trivially readable, and the apply pass is a **draw**, so it is invisible in
   the prov data (the probe scans at `vkCmdDispatch` only). *Settle it with a
   knob*: ship `--set agx_encode=0|1` and let one launch decide. Not a blocker.
2. **The authored grade is lost.** A full replacement discards CDPR's
   per-location colour grading (the 16 `OpImageSampleExplicitLod` of the 32³
   LUT). For a neutral filmic look that is usually *wanted*; if not, v2 samples
   the grade LUT and applies it inside AgX's log space.
3. **Live dispatch unconfirmed.** `b174eb4af0fea652` is dispatched in the
   capture; a live launch must show `"swapped":1` for it in
   `~/callisto_swap.jsonl`. Standard check.
4. **HDR output** may take a different path — untested, assume SDR.
5. **Exposure placement.** `%120 = %109 / cbv[5].w` shows exposure/eye-adaptation
   is folded into LUT generation, so AgX sits *after* exposure. That is the
   correct placement — no action needed, but worth knowing.

## 7. Also checked

- Six modules sample the other 32³ LUT (`0x1993bec0`, RGBA8): `050de025…`,
  `32faddb5…`, `47d4c8ed…`, `4ab8bbbb…`, `76a670a9…`, `af95e13a…`. All of them
  write the 160×92×128 froxel grids — they are **volumetric fog**, not colour
  grading. Not a tonemapping target.
- The 64³ RGBA16F (`0x158e15d0`, 99 binds at a shared slot) is likewise not a
  grade — it is sampled by essentially every lighting shader.


---

# BUILT (2026-08-27)

`dev/patch_agx.py`, `dev/install_agx.sh`, variants in `swaps.agx.*/`.
All five variants **spirv-val clean**. Not yet launched.

## Where it splices — and why not at the write

Feasibility (§3 above) proposed splicing at the single `OpImageWrite`. Reading
further changed that. The generator's tail is:

```
%3085 = OpFMul %float <m00> %3064        # 3x3 output primaries matrix,
%3086 = OpExtInst Fma  <m01> %3065 %3085 #   rows from CBV 21/22/23
%3087 = OpExtInst Fma  <m02> %3066 %3086
...rows 1,2...
%3094 = OpCompositeExtract %float <cbv> 2   # OUTPUT TRANSFORM MODE
%3095 = OpFOrdEqual %bool %3094 %float_0    # 0 -> clamp(0,1)   [SDR]
        ... == 1, == 2 ...
        == 3 -> PQ / ST.2084 encode         [HDR]
        == 4 -> ...
```

**The module handles SDR *and* HDR.** All five ST.2084 constants are present
exactly once — `0.159301758`, `18.8515625`, `0.8359375`, `18.6875`,
`78.84375` — reached under `mode == 3`.

So the default site is **`--site pre`**: replace `%3064/%3065/%3066`, the
inputs to the primaries matrix, leaving the matrix and the per-mode encode to
run on top of AgX. One patch is then correct in both SDR and HDR. Splicing at
the write (`--site write`, still available) would overwrite the PQ encode with
clamped SDR values — **broken in HDR**.

Because the game still applies its own encode at the `pre` site, the default
`eotf` is **2.2** (AgX hands back *linear* display-referred values). At
`--site write` the encode is bypassed, so `eotf=0` is required there and the
tool refuses the other combination.

## Verification done without launching

- Detection found exactly the predicted ids: shaper `%109/%110/%111`,
  transform inputs `%3064/%3065/%3066`, mode selector `%3094`.
- Rewrite confirmed surgical — only the 9 operand slots in the three matrix
  chains change; the matrix coefficients are untouched.
- The AgX constants were checked numerically against a Python reference:
  inset·outset = identity to 4 dp; **18% grey → 0.4967** (the canonical
  middle-grey check); 1.0 → 0.787, 4.0 → 0.934, 16.0 → 0.998 (smooth highlight
  roll-off, no clipping); and (4.0, 0.02, 0.02) → (1.0, 0.483, 0.483) — the AgX
  highlight-desaturation signature, an over-bright red going toward white
  instead of clipping to primary red.
- 6th-order sigmoid fit (`agxDefaultContrastApprox`: 15.5, −40.14, 31.96,
  −6.868, 0.4298, 0.1191, −0.00232). §5 above quoted the 7th-order variant;
  both circulate, the 6th-order one is the more widely validated.

## The game is NOT already using AgX

Asked and tested directly. None of the AgX fingerprints appear in the
generator's constant pool: no inset/outset coefficients (0.842479, 0.0784336,
1.196879, 1.151903, 1.151073), no log-range constants (12.47393, 4.026069),
and neither sigmoid coefficient set. (`0.1191` matches once in isolation —
coincidence, not the set.)

It is not textbook ACES either: `1.6410` and `0.14` are present but not the
Narkowicz fit (2.51/0.03/2.43/0.59) nor the AP1 matrix (0.59719/0.35458/
0.04823 …). It is CDPR's own fitted filmic curve — consistent with the mass of
bespoke small coefficients in the constant pool.

## Usage

```sh
python3 dev/patch_agx.py <gen>.spvasm --outdir swaps.agx.mine \
        --look punchy --set mix=0.6
./dev/install_agx.sh punchy        # or neutral | golden | half | quarter | off
```

`mix` is the A/B knob: 0 = vanilla, 1 = full AgX, and it lerps against the
*same* values it replaces, so intermediate settings are meaningful.

## Still needs one launch

1. **Confirm dispatch**: `"id":"b174eb4af0fea652.dxil"` with `"swapped":1` in
   `~/callisto_swap.jsonl`.
2. **Confirm `eotf`**: if the image looks washed out / crushed, the game's
   post-LUT encode differs from the assumption — try `--set eotf=0` at the
   `pre` site.
3. **The authored grade.** The generator samples the 32³ grading LUT
   (`0x19b4d4d0`) in the chain we bypass, so CDPR's per-location grading is
   replaced, not layered. Expected and usually wanted; `mix` dials it back.

---

# The SDR/HDR split (2026-08-27, from a live launch)

**Symptom:** with the patch installed, the user saw the effect **only in HDR
mode**. SDR looked vanilla.

**The dispatch log had already said so, and it was read correctly:** in the
gameplay process (`pid 1063775`, 7567 modules, 158 distinct compute
dispatches), `b174eb4af0fea652` produced `swap_load` + `module` (HIT, result 0)
+ `cpipe` — and **no dispatch event**. Every one of the 158 dispatches was
`swapped:0`. The module was loaded and given a pipeline, and never ran.

**Cause: the LUT generator has two permutations.** SDR dispatches one, HDR the
other. We had patched only the HDR one.

`dev/find_tonemap_gens.py` scans the dump by **structure**, not by constants
(`10` §3's rule) — `LocalSize 8 8 8`, exactly one v4float `OpImageWrite`, three
`Exp2` tainted from `gl_GlobalInvocationID`, and a ≥3-entry mode ladder. Over
2828 modules it returns exactly two, and nothing else:

```
id                  lines  modes  PQ consts    bytes
1d02efd8fe8014cc     5930      5          5   120980
b174eb4af0fea652     5919      5          5   120792
```

Near-identical, both carrying the full five-mode ladder and all five ST.2084
constants — so the SDR/HDR split is *not* the mode ladder inside the shader
(both have it); it is a compile-time permutation of something else, and the
game picks one at display-mode selection.

`1d02efd8fe8014cc` patches identically — same `%109/%110/%111` shaper, same
`%3064/%3065/%3066` transform inputs, same `%3094` mode selector, 87
instructions, spirv-val clean.

**Every variant now ships both modules**, and `dev/install_agx.sh` installs and
reports both; its `list` says `incomplete` if only one is present.

## Lesson, for the record

This is `10-DISPATCH-TRUTH.md` again, in a new costume: a swap HIT proved
creation, `cpipe` proved a pipeline was built, and neither proved execution.
The absence of a `swapped:1` dispatch was the correct signal and pointed
straight at "a sibling permutation runs instead" — the same failure that cost
this project weeks on the hair track. It cost one launch here because the
dispatch log was checked first.

The generalisable fix is the scanner: whenever a module is patched, sweep the
dump for structural siblings **before** launching.

---

## The colour-space bug (2026-08-27, from the pink/cyan screenshots)

**Symptom.** With `--site pre`, every neutral split by luminance: pink
highlights, cyan/teal shadows, blown saturation, red skin in sunlight.

**Why that symptom was the whole diagnosis.** AgX is neutral-preserving —
inset and outset both have rows summing to 1, and the sigmoid is per-channel
with identical parameters, so grey in *must* give grey out. A pipeline that
splits neutrals therefore cannot be failing inside AgX. It had to be the
splice site, and the only question was which end.

**What the tail actually is.** Not "a primaries matrix and a mode encode" —
it is a stock ACES output transform. Enumerating every constant 3x3 in the
module (all of them, not the ones I expected) identified each stage against
published matrices:

| ids | matrix | identified as |
|---|---|---|
| `%399..%401`   | `0.412391 0.357584 0.180481 / …` | **Rec.709 → XYZ (D65)** |
| `%856..%859`   | `1.451439 -0.236511 -0.214929 / …` | AP0 → AP1 |
| `%1040,…`      | `0.695452 0.140679 0.163869 / …` | AP1 → AP0 |
| `%2954,…`      | `1.641024 -0.324803 -0.236425 / …` | ACES RRT sat |
| **`%3032..%3034`** | `0.662454 0.134004 0.156188 / …` | **AP1 → XYZ (D60)**, to 8e-8 |
| `%3037,…`      | `0.987224 -0.006113 0.015953 / …` | D60 → D65 Bradford CAT |
| `%3172,…`      | `3.240969 -1.537383 -0.498611 / …` | XYZ → Rec.709 (SDR) |
| `%3232,…`      | `1.716511 -0.355642 -0.253346 / …` | XYZ → Rec.2020 (HDR) |

So **`%3064..%3066` hold CIE XYZ, not RGB.** `--site pre` wrote Rec.709 into
them, and the display matrix's large off-diagonals (`3.24, −1.54`, `−0.97,
1.88`) then expanded it. Mid-grey `0.2145` came out `(0.2583, 0.2035, 0.1949)`
in SDR and `(0.2375, 0.2072, 0.1968)` in HDR — pink on every neutral, with the
off-diagonals exploding saturation everywhere else. That is the screenshots,
exactly.

**The fix — `--site ap1`, now the default.** Splice one stage earlier, at
`%3032..%3034` in the ACEScg working space, and convert AgX's output
Rec.709 → AP1. The game's own AP1→XYZ, the conditional D60→D65 CAT, the CBV
display matrix, the paper-white divide and the per-mode encode then all run
untouched — which is what makes a single patch correct in SDR *and* HDR, the
thing `--site pre` was supposed to achieve and didn't.

`REC709_TO_AP1` is derived from this shader's *own* constants
(`inv(AP1→XYZ) @ inv(CAT) @ (Rec709→XYZ)`) so the round trip is exact
in-pipeline; it agrees with the canonical ACES matrix to 2.6e-6. Verified
offline end-to-end — grey 0.18/1.0/4.0 pushed through AgX → AP1 → XYZ → CAT →
Rec.2020 *and* → Rec.709 comes back neutral to 4 decimal places.

The LUT's **input** domain needed no change: the first matrix in the shader is
Rec.709 → XYZ fed straight from the shaper `Exp2`, so the grid decode is
Rec.709 linear — already AgX's native input space.

`--site pre` is kept only so the bug is reproducible; it is wrong.

### Lesson

`10-DISPATCH-TRUTH.md`'s sibling: **a splice site is a contract about a colour
space, and the contract is unwritten.** Naming the site "the inputs to the
primaries matrix" was a guess dressed as a finding — the structural detector
proved the *shape* (three matrix rows before a mode ladder) and I let that
stand in for proof of the *space*, which it never was. Enumerating every
constant matrix in the module and identifying each against published values
took one command and would have caught it before the launch.

### Reproducing

    ./dev/build_agx.sh              # all variants, both permutations
    ./dev/install_agx.sh neutral    # or punchy / golden / half / quarter

### Still open

- Only one permutation dispatches per run: the HDR log shows
  `b174eb4af0fea652 … "swapped":1,"groups":[6,6,6]` (6³ groups × 8³ = 48³ ✓)
  while `1d02efd8fe8014cc` gets `swap_load` + `module` HIT + `cpipe` and **no
  dispatch**. That confirms they are display-mode alternates, but it does not
  yet prove `1d02efd8fe8014cc` is the SDR one — that needs a dispatch line
  from an SDR run. If SDR shows no dispatch for *either* id, there is a third
  permutation that was not in the capture (the dump was taken in one display
  mode, so the scanner could only ever find the permutations present in it).

---

## The SDR permutations (2026-08-27, after HDR was confirmed working)

HDR looked right; SDR was still vanilla. The cause was the scanner, again.

**`find_tonemap_gens.py` required a float mode ladder** (`>=3 OpFOrdEqual`
against `%float_0..4`). That is an HDR-only trait. Relaxing the scan to the
mode-*independent* half of the signature — exactly one v4float `OpImageWrite`
plus three `gl_GlobalInvocationID`-tainted `Exp2` — turns up **ten**
permutations, not two (`dev/find_lut_gens.py`):

| | count | local | ladder | AP1→XYZ | PQ | lines |
|---|---|---|---|---|---|---|
| HDR | 2 | 8×8×8 | 5, float | yes | yes | ~5920 |
| SDR | 8 | 8×8×8 | 0 float / integer | **no** | no | ~3880–4010 |

The SDR eight are a different compilation, not a variant: **no colour-space
matrices anywhere**, and an **integer** encode ladder (`OpIEqual %413
%uint_0/1/2`, mode 1 = the sRGB OETF). Both traits made them invisible to a
detector written against the HDR pair.

### The SDR splice: `--site sdr` — **SUPERSEDED AND WRONG, see `21`**

Kept because the failure is instructive; do not follow it. The reasoning below
is sound about the *tail* of the module and wrong about where the splice
landed.

The intended site was the linear RGB entering the display encode, found via the
sRGB piecewise threshold (`0.0031308`): the values compared against it are by
definition linear display light. Input is Rec.709 throughout, so AgX needs no
space conversion here — only `eotf=2.2`, as at the AP1 site.

**The first attempt patched one branch of seventeen.** The values entering the
sRGB compare (`%462..%464`) are a phi in *one* encode branch; sixteen more
sibling branches phi from the same source and would have stayed vanilla.
`_resolve_phi` walks back to that common source (`%356..%358`), which the
detector then verifies is (a) the first incoming value of >=3 phi groups and
(b) defined before the first branch, so it dominates every consumer.

**And that common source is in the wrong place.** The grade stacks contain
sixteen per-LUT encode blocks of their own, so the first sRGB threshold in the
module is not the display encode at all — `%356..%358` is the *basic grade's
output*, above the area LUTs, the exposure, and the game's own tone curve. The
shipped patch therefore ran AgX and then let the engine tone-map its output a
second time. That is why SDR read dark while HDR read correct. The `groups >=
3` guard was satisfied by the three stack-1 merge phis rather than the
seventeen encode branches it was written to count.

The site was re-derived from the dispatch structure as `--site sdr2`, anchored
on the two runtime gates around the curve rather than on any constant. See
`21-AGX-GRADE-AND-SDR.md` §2–§3.

That is the *third* instance of the same error in this file — patch a thing,
find it was one of N siblings — and the fourth, `sdr` itself, is the variant
where the sweep succeeded and the *site* was still wrong. Worth stating as two
rules: **after locating a splice site, count how many places consume the same
value before believing one edit covers the pass**, and **a structural guard
that can be satisfied by the wrong structure is not a guard.**

`--site auto` (the default) picks `ap1` when the module contains the ACES
AP1→XYZ matrix and `sdr2` otherwise, so all ten build from one command.
### Presets

`punchy70` (`power=1.24, sat=1.27`) is 68% of the way from neutral to punchy —
verified at ~69% on both skin saturation (0.517 vs 0.370/0.582) and skin luma
(0.285 vs 0.360/0.257). `punchy70desat` (`sat=1.175`) is the same look with
7.5% less chroma, and is what is installed — see `21` §4 for the bracket.

**`mix` is an A/B knob, not a strength knob.** `half` reads bright, grey and
desaturated because it cross-fades AgX against the game's own tonemap, and
blending two different curves flattens contrast instead of softening the look.
To soften, scale the look parameters toward neutral (what `punchy70` does);
keep `mix` for proving a module is live.

Note that `power>1` plus `sat>1` can push saturated primaries above 1.0 and
clip in SDR (red neon: 1.42 at punchy, 1.26 at punchy70, 1.00 at neutral).
punchy70 clips noticeably less. At the SDR site the patcher clamps AgX's output
to [0,1] before the denormalise multiply, matching what vanilla did (`21` §3).

### Current state — superseded by `21`

    ./dev/build_agx.sh                   # 14 variants x 10 permutations, clean
    ./dev/install_agx.sh punchy70desat   # installed

Confirmed on screen in **both** display modes: HDR 2026-08-27, SDR 2026-08-28.
Since this document was written, AgX also consumes the game's authored
per-area grade rather than raw shaper output, and the SDR site moved from
`sdr` to `sdr2`. `21-AGX-GRADE-AND-SDR.md` is the current account of both.
