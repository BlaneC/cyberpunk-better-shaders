# 100 — Car-paint GLINTS at the reference raygen (2026-09-02)

`94` §4.4's metallic-flake glints, built as **parked, selectable A/B rungs** in
`rgs_reference_main` now that `98` §15 proved the world offset they depend on.
Five rungs built, gated offline, proven on the driver by a dispatching
self-test, verified, installed and selectable. **SHOT 2026-09-03 and one rung
is KEPT** — §12. A sixth, stacked rung carries the kept knobs on top of the
incoming ear-glow default — §13. **Nothing is committed.**

**Read §0, then §9 — the pre-registered table — BEFORE looking at a frame.**
And read `94` §2.1 before expecting to see anything at all: this site does not
shade the primary hit.

---

## 0. Verdict — read first

**BASE NOTE, amended 2026-09-03 ~01:20, amended again 01:35.** §6's five rungs were built on
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`, which stopped being the
standing selection at 00:5x when `101` §17 shot and kept the ray-query ear glow.
They are deliberately **NOT** rebuilt — a rebuild would change every content sha
this document pre-registers as a serving proof — so **none of the five carries
the ear glow**, and a launch on any of them is an ear-glow regression as well as
whatever it is testing.

**The keep was served by STACKING instead (§13).**
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense`
(sha `e0de8b9d5a6716d0`) is a **sixth** rung — `earglow-rq3`'s bytes with
`carglint --nu0 600000` spliced into the same ten raygens — and it was the
standing selection and the shipped default `skinspec` from ~01:20 to 01:35 on
2026-09-03.

**AMENDED 01:35 — THE DEFAULT IS THE CAP6 SIBLING, NOT §13's RUNG.** `101` §18's
6 mm thickness floor was shot and kept, so the shipped default `skinspec` is
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`, sha
**`3bb0aee03a1bfda8`** — the same dense glints at the same knobs, stacked on
`earglow-cap6` instead of on `earglow-rq3`, built by
`dev/build_carglint_stack_cap6.sh`. **Nothing this document measures changes:**
the glint census on the cap6 base is identical to `carglint-dense`'s number for
number and `--k-glint 0` still reproduces the base 93/93. §13's rung stays parked
as the default-minus-the-cap A/B handle.

| claim | verdict | confidence |
|---|---|---|
| `94` §4.4's design is implementable at site A with the inputs it names | **yes — 5 of 6 available in-module** | **certain**, all five parsed instruction by instruction in all 10 patchable permutations |
| the world position `P_w = hit + cbv[..][56].xyz` is constructible here | **yes, 10 of 10** | **certain** — member 56 re-derived structurally by `patch_rayq._find_world_offset` (imported, not copied), the same derivation `98` §15 shot |
| `E[glint] = 1` exactly, i.e. this redistributes energy and adds none | **yes** | **certain** — the probability-side firefly clamp makes it exact by construction; measured statically at `E[g] = 0.9974 ± 0.0043` and **on the GPU** at `E[glint] = 0.99537 ± 0.01539` |
| the `k_glint = 0` control is a real null | **yes, 93 of 93 files byte-identical** | **certain** — `cmp` after a full `dis → patcher → as → val` round trip, and its content sha *equals the base rung's* |
| a driver reproduces the model | **the SCALE and DENSITY bit-exactly; `glint` to 5.7e-5 relative** | **measured**, §5 — and the divergence is understood, not tolerated |
| glints will be VISIBLE on a car in front of the camera | **NO — expect not to see them there** | **certain from the bytes**, `94` §2.1: this raygen shades bounces ≥ 1 only |
| the glints are welded to the world rather than crawling with the camera | **STILL UNSHOT** | `carglint-cell` was LAUNCHED (00:55:03, sha matches) and produced **no capture and no remark** — §12. `98` §15 is still the only evidence, and it was measured at a different splice |
| this should ship | **`carglint-dense` IS KEPT, AND IS NOW THE SHIPPED DEFAULT** | **user verdict 2026-09-03**, verbatim: *"carglint-dense looks incredible too. Lets keep that around and add it to our big giant shader option"*. Stacked onto the ear-glow rung as `…-fog-earglow-glintdense`, sha `e0de8b9d5a6716d0`, and made the standing selection and default `skinspec` at ~01:20 the same day (§13); **at 01:35 the default moved once more, to the CAP6 SIBLING `…-fog-earglow-cap6-glintdense` `3bb0aee03a1bfda8`** — the same glints on `101` §18's 6 mm floor, so the keep still ships and this document's census is unchanged. `94` §17's "may never ship" is superseded by the screen |
| the glints are DENSITY-ordered as the model says | **UNREPORTED** | §9.2's monotonic row did not fire: `carglint-sparse` was never launched, and nobody said whether dense was brighter or merely denser |
| stacking the glints onto `earglow-rq3` costs nothing | **yes** | §13 — the glint census is IDENTICAL to `carglint-dense`'s on the old base (60 sites, member 56 ×10, 18/18, 3170 instructions), `k_glint=0` reproduces `earglow-rq3` at 93/93 `cmp`, and `101`'s own verifier still passes on the output |

---

## 1. What was built

Five rungs, all under `~/.local/lib/callisto/skin.set/`, all selectable with
`skinspec=`. Every one is the standing default
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog` with **10 of its 93 modules**
replaced — the 10 patchable `rgs_reference_main` permutations. The other 83
files, and the two scalar-specular permutations `40c6faab52a13874` /
`ab7f1822eeb0331b`, are byte-identical to the base.

New files, all new — **no shared patcher was edited**:

| file | role |
|---|---|
| `dev/glint_model.py` | the model. One numpy statement of the exact fp32/uint32 arithmetic; the patcher, the verifier and the driver test all import it |
| `dev/patch_carglint.py` | the patcher. `emit_module_level` / `emit_arm` are the only place the arithmetic is emitted |
| `dev/verify_carglint.py` | 12 axes, re-derived from the **shipped** `.spv`, never from the patcher's report |
| `dev/build_carglint.sh` | gates 0–6 and the install |
| `dev/carglint_kernel.py` | generates a compute kernel **by calling the patcher's own emitters** |
| `dev/carglint_probe.c` | creates a device, two storage buffers, a compute pipeline; dispatches |
| `dev/carglint_selftest.sh` | routes that through the layer and compares against the model |

`dev/patch_rayq.py`, `dev/patch_ms_ggx.py`, `dev/patch_skin_brdf.py` and
`dev/patch_chs_brdf.py` are **imported** and unmodified.

---

## 2. The splice, instruction by instruction

One site, one module (`1271d3815051da17`), quoted from the patcher's output.
`53` instructions once per invocation, `44` per GGX arm × 6, `18` uses
rewritten, **317 instructions per module**.

### 2.1 Where it goes

The once-per-invocation half is emitted immediately after the **last** id it
consumes (`prim.dot`, `prim.rsqrt`, `t_segment`, metallic, roughness, the cbv
and the position triple) and asserted to be **above the first GGX block**. In
this module that is line 2445, inside block `%2165`, which dominates all six
lobes. Dominance is not argued — it is `spirv-val`'s own check, run on all 93
modules of all five rungs.

### 2.2 The once-per-invocation half (53 instructions)

    %12731 = OpFMul %float %1467 %1468        ; t_primary = dot(P,P) * rsqrt(dot(P,P))
    %12732 = OpFAdd %float %12731 %2200       ; dist = t_primary + t_segment (payload word 3)
    %12733 = OpAccessChain ... %1243 %uint_0 %uint_56   ; 98 sec 15's world offset
    %12734 = OpLoad %v4float %12733
    %12735..7 = OpCompositeExtract %float %12734 0/1/2
    %12739 = OpFMul %float %12732 %12738      ; r_fp = dist * pix_angle   (1.2e-3)
    %12741 = OpFMul %float %12739 %12740      ; ratio = r_fp / cell       (x 125)
    %12743 = NClamp %12741 %float_1 %12742    ; ratio in [1, 65536]
    %12744 = Log2  %12743
    %12745 = Ceil  %12744
    %12746 = Exp2  %12745
    %12748 = OpFMul %float %12747 %12746      ; s = cell * 2^ceil(log2 ratio)
    %12749 = OpFMul %float %12748 %12748      ; s^2
    ; three times, k = 0,1,2 -- OFFSET FIRST, 94 sec 3.3's own quoted order:
    %12750 = OpFAdd %float %12735 %1715       ; P_w[k] = offset[k] + hit[k]
    %12751 = OpFDiv %float %12750 %12748
    %12754 = NClamp %12751 -1e9 +1e9          ; totality: ConvertFToS is UB on NaN
    %12755 = Floor  %12754
    %12756 = OpConvertFToS %int %12755
    %12757 = OpBitcast %uint %12756
    %12770..2 = OpIMul %uint ... 2654435761 / 2246822519 / 3266489917
    %12773/4  = OpBitwiseXor                  ; hash_cell
    %12776 = OpFMul %float %12775 %12749      ; k_den = (nu0 * theta_bin^2) * s^2 = 60 * s^2
    ; 94 sec 17.2's gate: a RAMP on metallic, hard on roughness
    %12778 = OpFSub %float %2253 %12777       ; metallic - m_lo (0.55)
    %12780 = OpFMul %float %12778 %12779      ; / (m_hi - m_lo) = x 6.666668
    %12781 = NClamp %12780 %float_0 %float_1
    %12782..5                                 ; t*t*(3 - 2t)
    %12787 = OpFOrdLessThan %bool %1687 %12786 ; roughness < 0.35
    %12788 = OpSelect %float %12787 %12785 %float_0
    %12789 = OpFSub %float %float_40 %12732   ; fade: (40 m - dist)
    %12790 = OpFMul %float %12789 %float_0_100000001
    %12791 = NClamp %12790 %float_0 %float_1  ; w_fade, 1 -> 0 across 30..40 m
    %12792 = OpFMul %float %12788 %12791
    %12793 = OpFMul %float %float_1 %12792    ; kw = k_glint * w_gate * w_fade

### 2.3 The per-arm half (44 instructions × 6)

    ; angular bin, from THIS block's own half vector (the D chain's NoH dot)
    %12795 = OpFMul %float %7366 %12794       ; H.x / theta_bin (x 50)
    %12797 = NClamp %12795 -1024 +1024
    %12798 = Floor
    %12799 = OpConvertFToS %int
    %12800 = OpBitcast %uint                  ; ... x3
    %12811..3 = OpIMul %uint ... 668265263 / 374761393 / 461845907
    %12814/5  = OpBitwiseXor                  ; hash_bin
    %12816 = OpBitwiseXor %uint %12774 %12815 ; seed = cell ^ bin
    %12817..25 = pcg RXS-M-XS                 ; 747796405 / 2891336453 / 277803737
    %12826 = OpConvertUToF %float %12825
    %12828 = OpFMul %float %12826 %12827      ; u = out * 2^-32, in [0,1)
    %12829 = OpFMul %float %12776 %7390       ; nu = k_den * D
    %12830 = NMin %12829 %float_1             ; p = min(nu, 1)
    %12832 = NMax %12830 %12831               ; pc = max(p, 1/glint_max)  <- the FIREFLY CLAMP
    %12833 = OpFDiv %float %float_1 %12832    ; 1/pc
    %12834 = OpFOrdLessThan %bool %12828 %12832
    %12835 = OpSelect %float %12834 %12833 %float_0   ; g ~ Bernoulli(pc)/pc, E[g] = 1
    %12836 = OpFSub %float %12835 %float_1
    %12837 = OpFMul %float %12793 %12836
    %12838 = OpFAdd %float %12837 %float_1    ; glint = 1 + kw*(g - 1)
    %12839..41 = OpFMul %float %7409/10/11 %12838     ; the three spec channels

### 2.4 The rewrite

The three `spec_c` **definitions are left alone** and every downstream use is
redirected — `28`'s `emit_comp` discipline, so the rewrite is provably total:

    -  %7422 = OpFMul %float %7409 %7421      ; base: uses spec directly
    +  %7422 = OpFMul %float %12839 %7421     ; patched: uses spec * glint

18 uses across 6 blocks × 3 channels, in every module.

### 2.5 The firefly clamp, and why `E[glint] = 1` is exact

`pc = max(min(nu, 1), 1/glint_max)`, and `g = (u < pc) ? 1/pc : 0`.
`E[g] = pc · (1/pc) = 1` for **every** `pc > 0`, so the clamp costs no energy —
it trades a rare huge spike for a commoner small one. `g ≤ glint_max` follows
because `pc ≥ 1/glint_max`. The clamp is on the **probability**, not on `g`;
clamping `g` would have broken the mean, which is the whole point of `94` §4.3.
Verified statically (10⁵ samples) and on the GPU (65 536): `max(g) = 16.0`
exactly, never above.

---

## 3. Deviations from `94` §4.4

`94` §4.4 named five shader inputs. **Four are available in-module and are
read from the module's own bytes; one is not.**

| §4.4 input | status | what was done |
|---|---|---|
| `P_w` | AVAILABLE | trace-origin hit position + `cbv[..][56].xyz`, member re-derived structurally |
| `H` | AVAILABLE | per block, the `OpDot` feeding `NoH` inside that block's own `D` chain; of the dot's two v3 operands, the one that is **not** the shading normal. Each component asserted to be `rsqrt·u`, i.e. normalised |
| `D` | AVAILABLE | `patch_ms_ggx._read_vis` already returns it |
| `t_segment` | AVAILABLE | the `OpLoad` of payload word 3 |
| `t_primary` | AVAILABLE | one `OpFMul` on the module's own primary reconstruction |
| `pix_angle` | **NOT AVAILABLE — DEVIATION** | see below |

**Deviation 1 — `pix_angle` is a build constant, 1.2e-3 rad.** The raygen
never forms a pixel solid angle: it reconstructs a ray direction from the
launch id and normalises, and the derivative that would give the footprint is
not computed anywhere in the module. Reconstructing it would mean re-deriving
the projection from the CBV, which is a second structural claim this feature
does not need. **Consequence:** the footprint radius is exact in *distance*
and wrong by a constant factor if the FOV or the resolution changes. Since the
footprint only picks a **dyadic rung** — `s = cell·2^ceil(log2(r/cell))` — a
constant factor error of less than 2× cannot change the rung at all, and a
factor of 2 shifts it by exactly one rung, which reads as a different flake
size, never as an artifact. 1.2e-3 rad is 1440 rows over a ~60° vertical FOV.

**Deviation 2 — `t_primary + t_segment` is a path length, not a camera
distance.** §4.4 wrote the footprint as a function of "the distance". At a
bounce vertex the honest analogue of the pixel footprint is the *total* path
length, which is what is used. **Consequence:** a flake seen in a mirror at
5 m through a 20 m reflection uses the 25 m rung, i.e. coarser cells. That is
the physically right answer for a footprint that has spread over the whole
path, and it is also the only quantity available.

**Deviation 3 — the gate is `94` §17.2's RAMP, not §4.1's boolean.** §4.4 was
written against §4.1's `m ≥ m_min AND r < r_max`. §17.2 replaced the metallic
half with a smoothstep over `(0.55, 0.70)` because §16 bracketed the market
tarp inside `m ∈ [0.50, 0.70)` and a hard threshold there would pop. The
roughness half stays hard at `r < 0.35`. **Consequence:** the tarp sits on the
ramp rather than outside the gate, so it gets **partial** glints, not none.
`94` §17.1's probe frame is what should decide `m_lo`; until it is shot, 0.55
is a choice, not a measurement, and it is a *knob*, not a constant of nature.

**Deviation 4 — a distance fade `94` §4.4 did not ask for.** `w_fade` ramps
the glints out between 30 m and 40 m. Without it, distant cars get one flake
per several pixels and the result is aliasing, not sparkle. It is one
`OpFSub`/`OpFMul`/`NClamp` and it is a knob.

**Deviation 5 — the coat is NOT built.** `94` §17 killed the dielectric arm on
physics and left the coat unbuilt; `94` §4.4's glints multiply the **flake/base
lobe**, which is what is spliced here. There is no clearcoat in this document.

**Deviation 6 — three `NClamp` totality guards.** `OpConvertFToS` is undefined
in SPIR-V on NaN or out-of-range input, and this splice sits inside a path
loop where a degenerate ray could produce either. Every conversion is preceded
by an `NClamp` (`±1e9` for cells, `±1024` for bins, `[1, 65536]` for the
ladder). `NMin`/`NMax` return the non-NaN operand, so the guards are total.

---

## 4. The gates, with numbers

`./dev/build_carglint.sh`, all passing:

| gate | result |
|---|---|
| 0. base | `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`, 93 modules |
| 1. round-trip neutrality | **10 of 10** reference permutations `spirv-dis → spirv-as` byte-identical *before* any rewrite |
| 1b. named declines | `40c6faab52a13874`, `ab7f1822eeb0331b`: 6 SG sites, **0** GGX blocks — scalar specular, no F0 in the lobe, declined **by name** |
| 2. patch + assemble | 5 × 93 modules, `spirv-val --target-env vulkan1.4` clean; 10/10 differ between every pair of rungs |
| 3. coverage census | per glint rung: **10 modules, 60 GGX blocks, member 56 ×10, F0-chain metallic 18/18 ×10, 60 glint sites, 3170 instructions** — read from the reports, never from byte counts |
| 4. `k_glint = 0` is a real null | **93 of 93** `cmp`-identical to the base through `dis → patcher → as → val` |
| 5. verifier | 5 rungs OK; `E[g] = 0.9974 ± 0.0043` / `1.0003 ± 0.0025` / `0.9994 ± 0.0063`, `max(g) = 16.0`, adjacent-cell hash correlation `r = −0.0042` |
| 5b. non-vacuity | **12 rejections** (below) |
| 6. manifests + shas | §6 |

The verifier's 12 axes, each **failing** and never warning: the module is a
reference raygen; 6 GGX blocks; the world offset is member 56 of the cbv the
raygen traces from, **re-derived**, and is genuinely *added* to the position;
the ladder is `cell·exp2(ceil(log2 clamp(·)))`; the bin reads **that block's
own** `H`; the pcg constants are the model's; `k_den = NU0 · s²` with `NU0`
re-derived from the knobs; the gate is `select(r < R_MAX, smoothstep, 0)` with
metallic recovered **two independent ways** (payload byte and F0 chain) that
must agree 18/18; `glint = 1 + kw(g − 1)` with `g` an `OpSelect`; every spec
use rewritten; and a 10⁵-sample closed form asserting `E[g] = 1` within 4σ,
`g ≤ glint_max`, gate-false `glint` **bit-exactly 1.0**, and cell-hash
decorrelation.

**Non-vacuity — the verifier rejects, as required:** the unpatched base; the
`k_glint=0` control read as a rung; the feature read as the control; the glint
rung read as the diagnostic; the diagnostic read as a glint rung; `carglint`
read with the dense knobs; `carglint-dense` read with the defaults;
`carglint-sparse` read as dense; and four purpose-built **decoy builds** —
`camrel` (the world offset dropped, so every glint crawls), `nogate` (`w ≡ 1`,
`90` §0's vacuous-gate failure reproduced on purpose), `viewbin` (the angular
bin taken off `NoV` instead of `H`, so glints track the camera), and
`cell --decoy camrel`.

---

## 5. The driver self-test — and one real finding

`./dev/carglint_selftest.sh`: **20 checks, 20 passed, 0 failed**, on an
NVIDIA GeForce RTX 4070.

`dev/patch_rayq.sh`'s existing probe is **link-only** — it creates modules and
links a pipeline, it has no buffers and never dispatches — so it could not
answer this. A dispatching probe was written rather than declining. The kernel
is generated by **calling `patch_carglint.emit_module_level` / `emit_arm`**, so
there is no second copy of the arithmetic to drift; the module handed to
`vkCreateShaderModule` is a **placeholder that stores −1.0**, and the layer
swaps the real kernel in from `swaps.carglinttest/` — `patch_rayq.sh` case E's
route — so "the swap happened" is *measured* (`"swap":"HIT"`, and the
`CALLISTO_SWAP_DISABLE=1` run is checked to fail). Each of the five parked
rungs' real ~300 KB patched raygen is then handed to `vkCreateShaderModule`.

### 5.1 The finding: bit-exactness holds where it matters and NOT elsewhere

| quantity | driver vs `glint_model.py`, 65 536 samples |
|---|---|
| `dist`, `s`, `s²`, `k_den`, `nu`, `pc` | **BIT-IDENTICAL, 65536/65536** |
| gate-CLOSED samples (`kw = 0`) | **`glint` == 1.0 bit-exactly, 53572/53572** |
| `k_glint = 0` | **`glint` == 1.0 bit-exactly, 65536/65536** |
| `kw` | 5133 differ |
| `glint` | 2549 differ; **62987 bit-identical**; max relative difference **5.7e-5** |
| Bernoulli decision | flipped on **7–16 of 65536** (≤ 0.024 %) |
| `E[glint]` on the driver's own numbers | **0.99537 ± 0.01539 (4σ)**, `max = 16.0000` |

Two causes, both understood:

1. **The driver reassociates.** `(fade_end − dist) · inv_fade_span` is
   evaluated as `fma(−dist, inv_fade_span, 4.0)`. Not IEEE-safe, universally
   done by graphics compilers, and strictly *more* accurate — the disagreement
   lives entirely in the cancellation tail where the fade or the metallic ramp
   is within 1e-4 of zero, i.e. where the glint is invisible.
2. **`OpFDiv` is allowed 2.5 ULP in Vulkan.** `P_w / s` and `1 / pc` can land
   on either side of `u < pc` for a sample that sits within a few ulp of the
   threshold. 0.024 % of samples flip a flake on or off, which is
   statistically nothing.

**This document does not assert `glint` is bit-exact on a driver, because that
assertion would be false against a conforming implementation, and widening a
tolerance until a test passes is how a test stops meaning anything.** What is
asserted instead is exactly what matters: the **scale and density are
hardware-independent** (`s`, `k_den`, `pc` bit-exact — so the look does not
change between GPUs), **nothing outside the gate is touched** (bit-exact 1.0),
and the **energy claim holds on silicon** (`E[glint] = 1` within 4σ,
`max ≤ glint_max`).

Making `glint` bit-exact would take `NoContraction` decorations on every
mul/add pair. That was **not** done: it would change the shipped bytes and
every content sha to buy agreement in a region where the value is invisible.

The self-test's own non-vacuity: it rejects the unswapped placeholder, rejects
a `nu0 = 6e5` kernel read with the default knobs, **accepts** the same kernel
read as `nu0 = 6e5` (so it is not an always-fail), and rejects a
`cell = 0.016` ladder read as `cell = 0.008`.

---

## 6. The rungs

`sha` is the launch-log `skin_sha` — `sha256sum` of the concatenated served
`.spv`, first 16 hex. **Check it on the launch line before reading a pixel.**

| rung | sha | what changed, one variable at a time |
|---|---|---|
| `carglint-cell` | `edacb088d26d95e8` | **the diagnostic — SHOOT THIS FIRST.** `94` §6.3 step 4's `-glintcell`. No glints at all: the PRIMARY hit's 25 cm world cell hash painted as one of eight flat hues (red/orange/yellow/green/cyan/blue/magenta/white) at 25 radiance writes per module. 22 writes skipped as constant-zero or scalar-broadcast, by name |
| `carglint` | `0dede3be78b80879` | `94` §4.4 at its defaults: `cell` 8 mm, `nu0` 1.5e5, `theta_bin` 0.02, `glint_max` 16, `k_glint` 1, gate ramp (0.55, 0.70) × `r < 0.35`, fade 30→40 m |
| `carglint-dense` | `16533661e383511e` | **one knob**: `nu0` ×4 → 6e5. More flakes, each dimmer |
| `carglint-sparse` | `3a141c13dd8d3481` | **one knob**: `nu0` ÷4 → 3.75e4. Fewer flakes, each brighter |
| `carglint-ctl` | `4dc824ca77d95feb` | **the control**, `k_glint = 0`. Emits *nothing* — no constants, no instructions, no rewrite. Its sha **equals the base rung's**, which is the strongest form the null can take |

`dense` and `sparse` move `nu0` and only `nu0` — the flake count per steradian
per m². Cell size was deliberately *not* the varied axis, because changing
`cell` moves both the flake size and the density and would confound the read.

Deployed and verified: `93 of 93` files `cmp`-identical between
`swaps.<rung>/` and `~/.local/lib/callisto/skin.set/<rung>/` for all five;
`libVkLayer_callisto_spvswap.so` `cmp`-identical repo vs installed; the live
CET `init.lua` `cmp`-identical to the repo's.

---

## 7. Settings contract — stated BEFORE the launch, never inferred after

`94` §12's contract verbatim, with one line changed. This is the live
`brdf_params.txt`:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=carglint-cell
    ser=class  ptreg=on  ptclamp=on  ptbounce=on  ptmsggx=on  refract=eta15

and the identical file with `skinspec=` swapped for each other rung.
**`ser=class` and `shadowset=full-shadow` are the base's own contract and are
NOT optional for any rung carrying raygens** — `sync_settings.sh`'s
`gi_refuse` block enforces them, and every rung here carries raygens.

Game side, **matched across every half and recorded**: PT Overdrive on,
PT-in-photo-mode on, RR off, DLSS Balanced, RayTracedLighting Psycho,
2560×1440. **Frame generation must be stated** — `98` §13.4 has been open on
this for three shoots.

`40` §7's two CET caveats apply verbatim: rewrite `skinspec=` in
`brdf_params.txt` **after** CET loads, because CET resets it, and the
settings-page WARNING banner is the confirmation the rung was served.

Deploy first: `./dev/build_carglint.sh --install`, then `make install`, then
`cmp` the served bytes — **the game runs copies.** Done, §6.

---

## 8. The frame to shoot

**One camera position, pinned in photo mode, then a second at +2 m and
rotated. Daylight, sun glancing across the panel, no neon, no wet ground.**

It must contain all of:

- **a parked car, close**, one body panel facing the camera and one at
  **grazing** — the glancing panel is where a flake lobe is brightest;
- **a mirror-flat surface reflecting that car** — a shop window, a puddle-free
  polished façade — because `94` §2.1 means **this is where the glints will
  actually appear**;
- **chrome trim** in the same shot — the roughness ceiling should exclude it;
- **a market tarp** if one is reachable — `94` §16 bracketed it inside the
  ramp, so it is the pre-registered false positive;
- **dry road and a painted wall** — the false-positive census, in the *same*
  screenshot (`81` §5's rule);
- **V or an NPC with visible skin, in direct sun** — the class-1 control.
  `99` §10.8e: "skin not red" is only a void condition **in direct sun**; the
  `skin_sha` on the launch line plus §6's `cmp` are the primary serving proof.

Then the **identical** frame on `carglint-ctl` without moving the camera.

**Order: `carglint-cell` → `carglint` → `carglint-sparse` → `carglint-dense`
→ `carglint-ctl`.** If `-cell` fails, stop: everything after it is void.

---

## 9. Pre-registered interpretation table

**Written before any frame exists. Read it before the screen, and record which
row fired — including "none of these", which is a finding.**

### 9.1 `carglint-cell` — the falsifier

| observation | reading |
|---|---|
| flat hue patches **welded to the geometry** under a 2 m translation and a rotation | **PASS.** `P_w` is world at this splice site; `98` §15's offset holds in `rgs_reference_main`. Every other rung is now readable |
| patches **crawl / slide with the camera** | **VOID, and a headline finding.** The offset is wrong *here*, and `98` §15's result does not transfer across the splice. Every glint rung in this document is meaningless. Fix before reading anything else |
| patches **swim under rotation only**, stable under translation | the frame is rotating, not translating — this is `99` §7's guard failing. Re-shoot with a pure translation before concluding anything |
| the whole frame is **one hue** | the cell hash is degenerate — either `s` is enormous (a distance blow-up) or the position triple is constant. Offline bug, not a screen result |
| **no visible painting at all** | not served, or the reference raygen never dispatched. Check `skin_sha` on the launch line, then `98` §2 |
| **confetti at pixel scale** | 25 cm cells are being seen at a scale far below 25 cm, i.e. the ladder collapsed to its floor. Offline bug |

### 9.2 The glint rungs — density

| observation | reading |
|---|---|
| **sparse < default < dense** in flake count, monotonic | the density knob is live and `nu0` means what the model says |
| all three look the same | either the gate never opens on anything in frame (check `-cell` painted the car at all), or `D` at the sampled lobes is so small that `p` sits on the firefly clamp everywhere — in which case `nu0` needs to move by 100×, not 4× |
| dense is **brighter**, not denser | wrong. `E[glint] = 1` regardless of `nu0`; a brightness change means the energy claim is broken on screen and contradicts §5. Headline finding |
| sparse is visibly **darker** overall | same — a mean shift. `E[g] = 1` is exact in the bytes and measured on the GPU, so a real darkening would mean the gate is multiplying something it should not |

### 9.3 The glint rungs — where they appear

| observation | reading |
|---|---|
| sparkle **in reflections and on bounce-lit surfaces**, not on the directly-viewed panel | **EXPECTED.** `94` §2.1: this raygen shades bounces ≥ 1 only. This is the pre-registered normal result |
| sparkle **on the directly-viewed panel** | unexpected and interesting — it would mean the reference integrator does contribute to the primary pixel somewhere `94` §2.1 did not find. Worth chasing, not a defect |
| sparkle on **tarps** | expected, partially: §17.2's ramp puts a tarp at `m ∈ [0.50, 0.70)` part-way up. If it is objectionable, `m_lo` is the knob, and `94` §17.1's probe frame is what should set it |
| sparkle on **road, concrete, skin, foliage, glass** | **the gate is broken.** `m ≥ ramp` and `r < 0.35` should exclude all five. Headline finding |

### 9.4 Fireflies and motion

| observation | reading |
|---|---|
| glints **static on a still camera**, and **welded to the car** as the camera moves | **PASS.** The world cell and the world-frame `H` bin are both doing their job |
| glints **crawl** as the camera translates | the offset is wrong at this site — the same failure `-cell` tests for directly, seen through the feature. Trust `-cell`'s read over this one |
| glints **swim as the camera rotates but not as it translates** | the angular bin is tracking the view, not the light. That is the `viewbin` decoy's signature, and the verifier rejects it offline — so if it is seen, something other than these bytes is being served |
| **isolated blown-out pixels** that persist across frames | the firefly clamp is not doing its job. `g ≤ 16` is enforced in the bytes and measured on the GPU, so a spike above that means the multiply landed somewhere unintended |
| **temporal boiling** in reflections | expected to some degree — the *bounce* is stochastic, so the surface a flake is evaluated on changes frame to frame. Judge this on `-sparse`, where individual flakes are separable |

### 9.5 The control

| observation | reading |
|---|---|
| `carglint-ctl` **indistinguishable** from the standing `…-fog` default | **required.** It is byte-identical (§6) — the shas are equal |
| `carglint-ctl` **distinguishable** | **the layer is not serving what it claims, and every A/B in this repo inherits the doubt.** Stop and fix the serving path. This is the single most load-bearing row in the document |

### 9.6 Void conditions

- `skin_sha` on the launch line does not match §6 → **void**, wrong rung served.
- The settings-page WARNING banner absent → **void**, the request was not honoured.
- `ser=class` or `shadowset=full-shadow` not as stated → **void**.
- Skin in **direct sun** does not read red on `-cell` → void *for `-cell`*
  (`99` §10.8e: the class tint is a multiply on direct radiance, so it is
  invisible out of the sun; do not void a frame for shaded skin).

---

## 10. Cost

317 instructions per module: 53 once per invocation, 44 per lobe × 6. The
per-lobe half is 12 integer multiplies, 9 xors, 3 shifts, 2 transcendental-free
conversions and ~15 float ops. `94` §4.5 budgeted the glints at "well under a
percent"; nothing here contradicts that, but **no frame time has been
measured** and none is claimed.

---

## 11. What this does NOT say

- **Nothing has been on screen.** Every row of §9 is unfired.
- It does not say the glints look good, or that they should ship. `94` §17
  says they may never.
- It does not say the reference raygen dispatches in the shot frame — `98` is
  the document for that, and `04-RESET-STATE.md` is the history.
- It does not measure the world offset **at this splice site**; `98` §15
  measured it at a different one, in the same module family. `carglint-cell`
  is the only thing here that can close that gap.
- It does not touch the coat, the dielectric arm, or `94` §4.1's site C.
- The driver agreement in §5 is **this machine's driver**, one GPU, one
  vendor.

---

## 12. SHOT 2026-09-03 — `carglint-dense` is KEPT

**User verdict, verbatim:**

> "carglint-dense looks incredible too. Lets keep that around and add it to our
> big giant shader option"

Evidence and frames: `a-b-testing/carglint/RESULT.md`.

### 12.1 The launches

From `~/callisto_launches.log`, lines 189–193. All five carry
`shadowset=full-shadow`, `ser=class:in-skin`, `tier=on`, `ptq=rcbm`,
`ptrefl=on`, `refract=fres`, `cache=cleared` — the §7 contract as stated.
**Every `skin_sha` matches §6's table**, so the right bytes were served five
times over and §9.6's serving void conditions did not fire.

| # | time | `skinspec` | `skin_sha` | §6 match | capture |
|---|---|---|---|---|---|
| 189 | 00:55:03 | `carglint-cell` | `edacb088d26d95e8` | ✓ | **none** |
| 190 | 00:57:39 | `carglint` | `0dede3be78b80879` | ✓ | **none** |
| 191 | 00:58:39 | `carglint` | `0dede3be78b80879` | ✓ | **none** |
| 192 | 01:06:42 | `carglint-dense` | `16533661e383511e` | ✓ | `A-dense-010829.png` |
| 193 | 01:10:02 | `carglint-ctl` | `4dc824ca77d95feb` | ✓ | `B-ctl-011127.png` |

`carglint-sparse` was **never launched**. `carglint` was launched twice, one
minute apart — a relaunch, same sha.

### 12.2 The frames

Two, both 2560×1440, in `a-b-testing/carglint/`, attributed by timestamp
against the launch log — the only link available, since nothing in a PNG names
the rung.

**They are NOT an A/B pair and are not read as one here.** Different camera,
different car, different body colour (`A` copper on a lit forecourt, `B` black
with the camera moved and rotated). No difference between them is claimed or
used. They record that a frame was taken on those two rungs; nothing more.

### 12.3 Which §9 rows fired — and which did not

**Fired:**

- **§9.2 row 1 (density is live), partially, LIVE-ONLY.** The user preferred
  the dense rung and kept it, which requires that it was distinguishable. It
  does **not** establish the monotonic `sparse < default < dense` ordering the
  row actually asks for.
- **§9.5 row 1 (the control), LIVE-ONLY and as an ABSENCE.** `carglint-ctl` was
  launched and drew no remark. It is byte-identical to the base — its sha *is*
  the base's — so silence is consistent. **An absence is not a reported pass**
  and is not recorded as one (`99` §10.7's rule).
- **§9.6: no void condition fired.**

**Did NOT fire — unshot or unreported, NOT passed:**

- **§9.1, the entire `carglint-cell` table.** The rung §8 said to shoot *first*,
  and the only one that can falsify the whole family, was launched and produced
  no capture and no remark. **The world-offset crawl test at this splice site
  is still open.**
- **§9.2 rows 2–4.** `carglint-sparse` was never launched, so the density
  ladder is unmeasured; nobody said whether dense was *brighter* or merely
  *denser*, so the row that would have contradicted `E[glint] = 1` on screen
  is unread.
- **§9.3 in full** — where the glints appear, reflections versus the directly
  viewed panel. Unreported.
- **§9.4 in full** — static versus crawling under camera motion, fireflies,
  temporal boiling. Unreported.

**The honest summary: one rung was liked and kept on a live read-out. The
diagnostic that could falsify the family, the density ladder, and every
motion and firefly row remain open.** §9 stands exactly as pre-registered;
nothing in it has been rewritten to match what happened.

### 12.4 What KEPT changes

`carglint-dense` (`16533661e383511e`) is relabelled **KEPT** in the selector.
The other four rungs stay exactly as they are — `-cell` in particular is still
the thing to shoot, and §12.3 is the reason it matters more now, not less: a
kept feature resting on an unfalsified offset is a worse position than an
unkept one.

---

## 13. The STACK — `…-fog-earglow-glintdense`

The standing default is moving to `101`'s ear-glow rung. The five rungs of §6
were built on the **previous** base and therefore do not carry the glow, so
"keep the dense glints" cannot be served by any of them. This section is that
rung.

    gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense
    content sha e0de8b9d5a6716d0

**NOTE 2026-09-03 01:35 (added by `101`): this rung now has a CAP6 SIBLING, and
the sibling is the shipped default, not this one.** `101` §18's 6 mm thickness
floor was shot and kept, so the default `skinspec` is

    gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
    content sha 3bb0aee03a1bfda8

— the same glints at the same knobs (`--nu0 600000`), stacked on `earglow-cap6`
instead of on `earglow-rq3`. Nothing in this section changes: the census on the
cap6 base is **identical to `carglint-dense`'s number for number** (60 GGX
blocks, 60 glint sites, 3170 instructions, member 56 ×10, F0-metallic 18/18
×10), so the floor costs zero glint sites, and `--k-glint 0` on the cap6 base
reproduces `earglow-cap6` at 93/93 `cmp` exactly as gate 4 does here. It was
built by `dev/build_carglint_stack_cap6.sh`, which **generates a parameterised
instance of `dev/build_carglint_stack.sh` rather than editing or forking it**
(eight substitutions, each asserted to match exactly once) — so this file's
gates are the ones that ran, and a rename here breaks that build loudly. The
rung below stays parked as the default-minus-the-cap A/B handle.

Built by `dev/build_carglint_stack.sh` (new file). 93 modules: `earglow-rq3`'s
bytes with `dev/patch_carglint.py --nu0 600000` spliced into the same ten
`rgs_reference_main` permutations the glow already occupies.

### 13.1 Order — rq3 first, glints on top — and why

Three reasons, none of them convenience:

1. **The earglow bytes are the incoming default and are already shot and gated
   by their author.** Patching *on top* of them makes those exact bytes the
   input, so `--k-glint 0` must reproduce them at 93/93 `cmp` (gate 4) and
   anything that differs is provably mine, not a re-derivation artefact.
2. **carglint's anchors are structural, not positional.** The Schlick
   spherical-gaussian constant finds the lobes, the `D` chain finds `H`, the
   payload loads find metallic/roughness/`t_segment`, and the trace-origin rule
   finds member 56. The rq3 splice *adds* instructions and rewrites its own
   transfer; it does not move the GGX blocks, the position triple or the
   payload — so the finders still resolve. That is a claim, and gate 3 proves
   it by requiring the census to equal the old base's **number for number**.
3. **The converse order would mean re-running `101`'s patcher over
   glint-patched bytes.** That patcher and its gates are not mine to re-prove,
   and its author owns the default. Not my edit to make.

### 13.2 The gates

| gate | result |
|---|---|
| 0. base | `earglow-rq3`, sha `359060c26c8c7367`, 77 + 4 + 12 = 93 |
| 0b. lineage | `…-fog-earglow` is **93 of 93 `cmp`-identical** to `earglow-rq3`, same sha — so stacking on `earglow-rq3` stacks on the default's bytes |
| 1. round-trip | **10 of 10** earglow raygens `dis → as` byte-identical, so gate 4's null is real |
| 1b. declines | both scalar-specular permutations: 6 SG sites, **0** GGX blocks, declined **by name** on the earglow bytes too |
| 2. patch + assemble | 93 modules, `spirv-val --target-env vulkan1.4` clean |
| 3. census | **10 modules, 60 GGX blocks, member 56 ×10, F0 metallic 18/18 ×10, 60 glint sites, 18 uses rewritten, 3170 instructions — IDENTICAL to `swaps.carglint-dense` on the old base.** The rq3 splice costs zero glint sites |
| 4. the null | `--k-glint 0` on the earglow bytes is **93 of 93 `cmp`-identical to `earglow-rq3`** through `dis → patcher → as → val` |
| 5. file census | **exactly 10 of 93** differ from `earglow-rq3`; **exactly 10 of 93** differ from the old base; **10 of 10** differ from `swaps.carglint-dense`, so the glow really is carried |
| 6. `verify_carglint.py --nu0 600000` | **OK**: 93 modules, 10 patched, 60 glint sites, `E[g] = 1.0003 ± 0.0025`, `max(g) = 16.0`, hash `r = −0.0042` |
| 6. `verify_earglow_rq3.py --base <old base> --mode glow --wide 4.0 --wrap 0.35` | **ALL PASS** on the stacked output — 10 permutations, 25 painted writes, `A=517 B=545`, `match=InstanceId`. **The rq3 splice survived the glint rewrite untouched** |
| 6b. non-vacuity | **6 rejections**: the earglow base as a glint rung; the stacked rung read with the *default* knobs; the stacked rung read as the control; the old base as an ear-glow rung; `carglint-dense` (no glow) as an ear-glow rung; the stacked rung read at the *wrong* glow knobs (`--wide 2.0`) |
| 7. driver | the stacked raygens — the biggest modules in the family, carrying three ray queries **and** the glint splice — are accepted by `vkCreateShaderModule`; `dev/carglint_selftest.sh` **20 of 20**, now checking 6 real rungs |

### 13.3 Deployed — and it is now the SHIPPED DEFAULT

`93 of 93` `cmp`-identical between `swaps/` and
`~/.local/lib/callisto/skin.set/`; live CET `init.lua` == repo == `release/`.

A selector row was added, labelled CANDIDATE DEFAULT, and **the default
`skinspec` value was deliberately left alone by this document's author** —
`101`'s author owned that edit and made it.

**As of ~01:20 on 2026-09-03 this rung IS the standing selection and the shipped
default `skinspec`.** `init.lua`'s default value is
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense`, the
`<-- DEFAULT` marker moved off the `-earglow` row onto it, and `…-fog-earglow`
stays parked as the default-minus-glints A/B handle.

**The contract is unchanged and still not optional:** `ser=class` +
`shadowset=full-shadow`, `ser_sha=310513f3008cbde4`,
`ptq_sha=55ed4e5c6884ab71`. And per `101` §17.8, **a default change does not
rewrite the live `brdf_params.txt`** — that file is player state and may hold an
in-flight A/B selection, so check `skinspec=` and `skin_sha=` on the launch line
rather than assuming the default was served.

### 13.4 What the stack does NOT change

Every open row of §12.3 stays open. The stacked rung carries `carglint-dense`'s
arithmetic exactly, so it inherits `carglint-dense`'s unfalsified world offset
and its unread motion behaviour. **`carglint-cell` is still the frame to
shoot**, and shooting it now tests the stacked default as well, because the
cell hash it paints is built from the same `P_w`.
