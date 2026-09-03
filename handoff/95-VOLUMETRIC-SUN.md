# 95 — Participating media on the sun shadow ray (2026-09-01)

The ask: multiply the sun NEE contribution by a Beer–Lambert transmittance
`T = exp(−σ·∫ρ ds)` along the shadow ray, with an analytic exponential
height-fog density, for PT-consistent light shafts and aerial perspective.

**Status: built, verified, not installed, not committed, not launched.** Six
rungs on the live standing selection (§8), every constant re-derived from the
shipped bytes (§7), zero rays added. **Read §0 before anything else** — two of
the three stated goals are unreachable from this splice site, and saying so is
the first job of this document. The design was written first and accepted with
that correction; §7–§10 are what the build actually measured, including the
places the first draft was wrong.
---

## 0. What this can and cannot do — read first

The splice multiplies the **direct sun term at a surface**. It adds no volume
integration along any camera ray. Three consequences, stated before the maths:

1. **No light shafts. Ever, from this site.** A shaft is in-scattered light
   arriving from *empty air* along the camera ray. A multiply on a surface
   term cannot put radiance where there is no surface. Under `53`'s
   multiplicative-only constraint no splice in this family can add it — the
   in-scattering half is exactly the half we may not write.
2. **No distance-based aerial perspective either, and this is the
   non-obvious one.** τ along the shadow ray is a function of the shading
   point's *height* and the *sun elevation* only. Two points at the same
   height, one 2 m from the camera and one 500 m away, get the **identical**
   T. There is no near/far gradient in this term by construction. Distance
   aerial perspective comes from the camera-ray integral — the same half (1)
   forbids. A `-fogv` view-segment rung is sketched in §9 and is deliberately
   **not** the ship candidate.
3. **What it does deliver, and it is worth having:** direct sunlight
   correctly attenuated and reddened as a function of sun elevation and of
   the shading point's height above the haze reference — a low sun goes warm
   and dim through the boundary layer, a rooftop is cleaner than the street,
   and the effect is applied **at every bounce**, so indirect sunlight is
   attenuated by the same physics as direct. Zero rays, zero PRNG draws, zero
   added variance. That is the whole feature; the title of this doc
   over-promises and the rungs will be judged on (3).

---

## 1. Census — is the geometry in scope? Yes, 12/12

Measured on the standing base's 12 `rgs_reference_main` permutations by
running the repo's own detectors read-only
(`E.find_nee_trace`, `E.find_origin_offset`, `E.find_sun_radiance`,
`C2.find_path_counter`; scratch probe, not committed).

| what | where it comes from | present |
|---|---|---|
| **P — the shading point at the current bounce** | the sun-NEE trace's **own origin operand**, `nee.ops[6]`, an `OpCompositeConstruct %v3float` of three loop-carried floats | **12/12** |
| **L — the sun direction** | the sun-NEE trace's **own direction operand**, `nee.ops[8]`, likewise a `CompositeConstruct`, and **already unit** (`FMul(x, InverseSqrt(dot(v,v)))` immediately upstream — no `Normalize` needed, unlike `88`) | **12/12** |
| **C — the camera world position** | `cbv[<same base as slot 77>][56].xyz` | **12/12** |
| the three sun sites | `find_sun_sites`: `OpFMul(NClamp(BRDF,0,1), sunRadiance_c)`, one per channel, radiance component asserted to have exactly 3 uses | **36/36** |
| path counter (needed only to *assert we do not use it*) | `C2.find_path_counter` (`90`'s structural fix) | **12/12** |

Per-module ids, for the patcher's report and for anyone re-deriving this:

| module | NEE line | origin ctor | dir ctor | slot-56 chains | path ctr |
|---|---|---|---|---|---|
| 1271d3815051da17 | 2998 | %2121 | %2122 | 6 | %896 |
| 21a92f1a77eb4c22 | 3389 | %2529 | %2530 | 8 | %1130 |
| 25b54fc4a17688df | 2998 | %2114 | %2115 | 6 | %896 |
| 3d871a3170bc5815 | 3442 | %2687 | %2688 | 8 | %1133 |
| 40c6faab52a13874 | 4739 | %2364 | %2365 | 10 | %1098 |
| 4103c8860c3909e4 | 3030 | %2109 | %2110 | 8 | %581 |
| 4270b745d11a5e8a | 3389 | %2522 | %2523 | 8 | %1123 |
| 852b31a841b85b26 | 3051 | %2279 | %2280 | 6 | %896 |
| 996a3b16253c3e7f | 3022 | %2099 | %2100 | 8 | %581 |
| ab7f1822eeb0331b | 4886 | %2506 | %2507 | 10 | %1204 |
| d002cc05eb940591 | 3576 | %2690 | %2691 | 10 | %740 |
| d622fb9e1dcb8cd0 | 3568 | %2571 | %2572 | 10 | %740 |

### 1a. Use the NEE's own origin, NOT `85`/`88`'s `prehit`

`85` and `88` deliberately took the **un-biased primary hit** `prehit`,
because their term is a millimetre-scale contact shadow and the engine's own
mm origin lift is the thing they exist to defeat. **That choice is wrong
here.** `prehit` is the *primary* hit — at bounce ≥ 1 it is the wrong point
entirely — and this term must run at every bounce. The trace's own origin
operand is the current bounce's point, carries an offset of at most 0.1 m
along N (`85` §1), and fog scale heights are ~10³ m, so the bias is nine
orders below the signal. It is also *simpler*: one `CompositeConstruct`,
already asserted 12/12 as the first line of `find_origin_offset`.

### 1b. The position is **camera-relative**, and slot 56 is the camera

`find_raster_position`'s docstring already says camera-relative; it is
confirmed structurally three ways in `d622fb9e1dcb8cd0`:

* `%361-363 = normalize(P_raster)` is used as **the view direction** in the
  engine's own `P − c1·D·(…)` origin pull-back. Normalising a position to get
  a direction is only valid with the camera at the origin.
* `%551–553 = cbv[56].xyz + P` is then quantised on a power-of-two lattice
  and packed into a 64-bit key (`%598–%613`) — a **world-space hash grid**.
  A grid key must be in world space, so `cbv[56].xyz + P` is world space and
  `cbv[56].xyz` is the camera's world position (or a stable world rebase
  origin; §8 F3 covers the difference).
* `%1512–1516 = P + 2000·D + cbv[56].xyz` — a far/sky probe point, same shape.

So **world height `h = P[u] + C[u]`**, and the term needs one extra
`OpAccessChain`+`OpLoad` on a cbv base that is defined in the entry block.

### 1c. The up axis is **index 2 (Z-up)** — high confidence, flagged anyway

Two independent structural signals plus the engine convention:

* the engine's own self-hit offset multiplies the whole normal-push term by
  `OpSelect(N[2] > 0, 1, 0)` — *push along the normal only on upward-facing
  surfaces*, the standard ground-plane acne trick. Meaningless unless 2 is up.
* the env/sky octahedral encode folds on component 2.
* REDengine 4 is Z-up (teleport / `GetWorldPosition` convention).

Not proven from a runtime value, so it ships as a build flag `--up {0,1,2}`
default 2, and §8 F1 is the one-frame falsifier.

**World units are metres**, already established by `85`/`88` (tmax `0.006` =
6 mm, the engine's own offset floor `0.005` = 5 mm at face range).

**MEASURED 2026-09-02 — both claims in this section are now confirmed on screen:
`99` §10.8** read `frac(P)` off a wall and found the vertical sawtooth in the
**blue** channel (component 2, so **Z-up**, and +Z) with a period of 512.5 px
against V's 945 px extent = a **1.00 m cell**. `--up 2` and metres are no longer
structural assumptions.

---

## 2. Engine fog parameters: **not readable. Three hardcoded knobs, and the doc says so.**

GOTCHAS 8 answered properly, both halves:

* **CET / CVars.** `pt_engine.lua`, `detail_engine.lua`, `skin_engine.lua`,
  `hair_engine.lua`, `init.lua` and `09-SETTINGS-AUDIT.md` contain **no** fog
  key. The nearest is `RayTracing/*/SunScatteringScale` (`pt_engine.lua:142`),
  which is a scalar multiplier on a scattering term, not a density/height.
* **The exe.** `strings` over `Cyberpunk2077.exe` finds the parameters —
  `m_fogHeight`, `m_fogHeightFalloff`, `m_fogHeightMaxCut`,
  `m_simpleFogDensity`, `m_simpleFogColor`, `m_volDistantFogOpacity`,
  `DistantFogAreaSettings` — but they are **Environment/Weather `.env`
  fields**, not CVars: the only `Rendering/VolFog/*` and `Rendering/Debug/*`
  strings are debug toggles and texture previews. There is **no**
  `RayTracing/Fog` group.
* **The shader.** The reference raygen binds four constant buffers
  (`%104`-equivalent ~204 v4 slots, plus three small ones); all `OpName`s are
  stripped by the DXIL→SPIR-V path, so no slot can be *named* as fog without
  a runtime read, and GOTCHAS 13 (existence ≠ addressability) plus the
  probe's compute-only descriptor logging make that read unavailable. Guessing
  a slot is exactly the `18` pink-neutral failure.

**Decision: hardcode.** Three documented knobs — `d0` (extinction at the
reference height, per metre), `H` (scale height, metres), `y0` (reference
world height, metres) — plus the spectral exponent `p`. See §3 for the
degeneracy that collapses `d0` and `y0` into one shipped constant.

---

## 3. The maths, and the one design decision that keeps it honest

Density along the shadow ray `P + s·L`, with `u` the up axis:

    rho(s) = d0 · exp( −( h + s·L_u − y0 ) / H ),   h = P[u] + C[u]

Closed form to infinity (the sun ray's tmax is `10000`, i.e. unbounded):

    tau_abs = sigma · d0 · H / L_u · exp( −(h − y0)/H )        for L_u > 0

**But shipping `tau_abs` double-counts.** The engine's sun radiance is
authored to look right under an atmosphere the artist has already implied.
An absolute vertical optical depth of even 0.4 dims *noon* by a third, which
would read as "the mod turned the sun down", not as fog. So the rung ships
the **airmass-excess form** — the slant column *minus the zenith column the
engine already baked in*:

    col   = exp( −(h − y0)/H )                  ; normalised column at height h
    lu    = max( L_u, LU_MIN )                  ; LU_MIN = 0.02  (~1.15 deg)
    am    = max( 1/lu − 1 , 0 )                 ; airmass EXCESS over zenith
    tau_c = min( A_c · col · am , TAU_MAX )     ; TAU_MAX = 30
    T_c   = exp( −tau_c )                       ; <= 1 exactly; = 1 at zenith sun
    site_c := site_c · T_c

`A = d0·H·exp(y0/H)` — **`d0` and `y0` are not independent**; for a fixed
build they collapse to a single constant. The shader carries **two** scalars
per channel (`A_c`, and `B = −log2(e)/H` folded into the exponent), not three.
`y0` survives only as documentation: it is the height at which `A` *is* the
vertical optical depth. Set it by reading the player's world Z once from the
CET console at the A/B location; no shader work, no guess.

`T = 1.0` exactly at zenith sun and `T ≤ 1` everywhere, so `53`'s
multiplicative-only constraint holds by construction and no pixel is ever
brightened.

Emitted, `Exp2`/`Log2` only (the modules carry no `Exp`; the `log2(e)` factors
fold into the build constants at zero instruction cost):

    h    = FAdd( P_u , C_u )
    e    = NClamp( FMul(B, FSub(h, y0)) , −EXP_LIM , EXP_LIM )
    col  = Exp2( e )
    lu   = NMax( L_u , LU_MIN )
    am   = NMax( FSub( FDiv(1.0, lu), 1.0 ) , 0.0 )
    q    = FMul( col , am )
    tau_c= NMin( FMul( A2_c , q ) , TAU_MAX2 )      ; A2 = A·log2(e), pre-scaled
    T_c  = Exp2( FNegate tau_c )
    out_c' = FMul( out_c , T_c )                    ; replace_all_uses(out_c)

≈ 16 instructions per module (neutral) / ≈ 20 (per-channel). **Zero
`OpTraceRayKHR` added** — asserted, §7.

### 3a. Numbers at the shipped default (A = 0.25, H = 120 m, h = y0)

At `h = y0` the column term is exactly 1, so this row is a pure function of
`A` and the airmass excess — `H` does not enter it. `H` sets only the
*gradient* with height, which is why §8's ladder moves `A` and holds `H`.

| sun elevation | 90° | 60° | 45° | 30° | 20° | 10° | 5° |
|---|---|---|---|---|---|---|---|
| airmass excess | 0 | 0.155 | 0.414 | 1.00 | 1.92 | 4.76 | 10.5 |
| `T_g` | 1.000 | 0.962 | 0.902 | 0.779 | 0.618 | 0.304 | 0.073 |

---

## 4. The tint: **per-channel σ, weak exponent — three lines**

1. The physically correct sign is **beam reddening**: what the haze removes is
   scattered out, so the surviving direct beam loses blue first, which is the
   entire visual reason a low sun reads as sun and not as a grey dimmer. A
   neutral `T` throws that away for one saved multiply.
2. But this is *ground-level urban haze*, which is Mie-dominated
   (σ ∝ λ^−0…λ^−1), **not** Rayleigh (λ^−4); shipping the Rayleigh exponent
   would tint hard and wrongly, so the exponent is a knob shipped at **p = 1**
   with p = 4 kept only as a deliberately-too-much diagnostic rung.
3. It stays inside `53`: every channel's `T_c ≤ 1`, so the "warming" is purely
   blue losing more than red — nothing is ever brightened, and the blue we
   remove is *not* re-added anywhere (that would be in-scattering, §0).

`A_c = A · (550/λ_c)^p`, λ = 610/550/465 nm. At p = 1:
`A_r/A_g/A_b = 0.902 / 1.000 / 1.183`. At the shipped A = 0.25 and 20°
elevation that is `T = (0.648, 0.618, 0.566)`, R/B = 1.15; at 10°,
`(0.342, 0.304, 0.245)`, R/B = 1.40 — warm, not orange. p = 4 at 20° gives
R/B = 1.71, visibly wrong, which is what would make it a diagnostic; it stays
a `--p` knob and is **not** built as a rung, because the axis that actually
needs an on-screen control is p = 1 versus **neutral**, and that is `-fogn`
(§8a). If `-fog` and `-fogn` are indistinguishable, the per-channel σ is not
earning its three extra `Exp2`s.

---

## 5. The splice site, and why it composes

Same three sites as `85`/`88` — `find_sun_sites`' `OpFMul(NClamp(BRDF,0,1),
sunRadiance_c)`, 3 per module, 36/36 — but the multiply lands on the **result**
`%out`, via `replace_all_uses(%out)`, not on the BRDF operand. Two reasons:

* **It composes with the standing rung.** The live selection
  `…-clothhi-cone2all` has already rewritten that FMul's *operand* to the
  cavity's `%new`, so `find_sun_sites`' `NClamp` assertion would die on the
  patched base. Multiplying the result is strictly downstream of any prior
  edit and needs no change to the inherited assertion — the detector's
  radiance-has-exactly-3-uses check (2 composites + 1 FMul) is unchanged by
  `88`, verified.
* **It respects "scale before a clamp, never after"** trivially: `T ≤ 1`, so
  the edit can only *reduce* a value that was already bounded. No fp16 store
  can be pushed to `inf` by a factor in `[0,1]`.

The radiance triple's 3-use assertion also means the sun's own
"is the radiance non-zero" branch test is untouched: `T → 0` dims the term but
does **not** flip a branch, so divergence and the LCG chain are bit-identical
to base. The A/B stays one variable **at the pixel**.

Reach: `rgs_reference_main` only — reference / photo-mode PT. All 77 compute
and all 4 ReSTIR-GI modules byte-identical, `cmp`-asserted. Gameplay untouched.
Judge it in photo mode or not at all.

---

## 6. Why this is **ungated on bounce** — the opposite of `88`

`88`/`90` gate the cavity cone on `path_counter == 0`. This term is
deliberately gated on **nothing**, and the difference is not a preference:

* **`88`'s term is a correction to a primary-hit-only artefact.** The
  reference raygen re-finds the primary hit from the *raster depth buffer*
  (`85` §1), which is mm-wrong on a face slope, and the engine then lifts its
  own sun-ray origin mm off the surface. Both errors exist **only at the
  primary hit** — at bounce ≥ 1 the point comes from a real traced
  intersection with no depth-buffer error. Running the AO cheat there would
  darken geometry the path tracer already resolved correctly.
* **And it compounds.** `90` §1 measured exactly that: in the 5 permutations
  where the gate accidentally tested the *sample* counter, a one-hit darkening
  ran at every bounce and area lights went "way too dim" (`88` §5c). A cheat
  applied N times is N times wrong.
* **Beer–Lambert is not a cheat and does not compound wrongly.** Every shadow
  ray from every bounce travels through the same atmosphere; `T` at bounce k
  is the true transmittance of *that* ray. The product over a path is exactly
  what the physical path integral computes. Gating at bounce 0 would
  systematically **over**-estimate indirect sunlight — the error would grow
  with bounce depth, which is the wrong direction.

The verifier therefore asserts the *absence* of a counter test in the `T`
chain (§7 axis 4), which is a positive gate, not an omission.

---

## 7. Gates — all build-failing, all re-derived from the SHIPPED bytes

| # | gate | as-built result |
|---|---|---|
| G1 | **`--a 0` emits nothing**; rebuild byte-identical to the base in 12/12. The control. | PASS, and run **twice** — once in `abs` mode and once in `cam` mode, because the height chain differs between them and only one of the two would have caught a stray constant. 12/12 byte-identical both times. |
| G2 | Coverage 36/36 rewritten sites (3 × 12), each the result of `FMul(x, rad_c)`, every prior use of `%out` redirected, the new FMul's own operand excluded. | PASS 36/36 on all six rungs |
| G3 | **Zero rays added**: `OpTraceRayKHR` count per module identical to base. | PASS 12/12 on all six rungs. 28 instructions per module at p=1, 20 at p=0 (channels sharing a constant share the whole chain). |
| G4 | **No bounce gate**: the `T` def-chain contains no comparison against `find_path_counter`'s phi (nor `find_bounce_counter`'s). | PASS — and strengthened after the first draft. The original check listed the counter ids by hand, which a gate spliced elsewhere would have slipped past. It is now a **transitive closure** of the emitted term, bounded by three declared leaves (`P_up`, `L_up`, `cbv_base`), asserting both counters absent; measured closure 35–45 ids against a **cap of 400**, above which the verifier declares its own proof vacuous and fails. |
| G5 | **Closed-form check** (`dev/volsun_model.py`): constants read back out of the shipped asm, evaluated against an independently-written float64 closed form over an (h, elevation) grid. | PASS. Worst relative error **3.44e-06 … 6.03e-06** over 60600 points, tol 2e-5. Note the tolerance was raised from `91`'s 1e-6: the emitted chain is float32 with two `Exp2` hops, and 1e-6 is below its own arithmetic floor — a tolerance the code cannot meet is not a gate, it is a lie. |
| G6 | **Non-vacuity** on each axis — each perturbed claim must FAIL. | PASS 10/10, §8c |
| G7 | **Bounds from the bytes**: `NMax(L_u, LU_MIN)` with `LU_MIN > 0`; `NMax(am, 0)`; `NMin(tau, TAU_MAX)`; `A_c > 0`; the `Exp2` argument negative-definite — i.e. `T ≤ 1` *proven from the emitted constants*, so `53` holds mechanically. | PASS 36/36 per rung |
| G8 | **Dominance** (`dev/cfg_dom.py`): the NEE origin ctor, the direction ctor and the cbv base each dominate all three sun sites. | PASS 12/12. Note the fix: an early draft asserted the cbv base was defined in the *entry block*. It is not — the entry block is the tiny `OpVariable` prologue terminated by `OpBranch`, and the bindless chains live in the block after it. Dominance is now computed, never assumed (GOTCHAS #12). |
| G9 | 81/81 non-reference modules verbatim; 93/93 `spirv-val`; base provenance re-checked against the parked standing rung; rung-to-rung deltas exactly 12 reference / 0 other. | PASS on all six rungs |

New files (none shared, per the brief): `dev/patch_volsun.py`,
`dev/verify_volsun.py`, `dev/volsun_model.py`, `dev/build_volsun.sh`.
`init.lua`, `pt_engine.lua`, `brdf_params`, `Makefile` and every existing rung:
**untouched**. `make install` was not run; nothing is parked; nothing committed.

---

## 8. Built — the ladder, the numbers, the evidence

Base: **`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all`**, the LIVE standing
selection, so fog-vs-no-fog is one variable against what the user is actually
looking at. Provenance asserted 93/93 against the parked copy before anything
was patched.

### 8a. The rungs, one variable per step

| rung | A | H | y0 | p | up | height ref | the single variable |
|---|---|---|---|---|---|---|---|
| `…-fog` | 0.25 | 120 m | 20 m | 1 | 2 | absolute | **the ship candidate** |
| `…-foghi` | 0.50 | 120 m | 20 m | 1 | 2 | absolute | STRENGTH alone |
| `…-fogx` | 1.00 | 120 m | 20 m | 1 | 2 | absolute | STRENGTH, the "is it working" diagnostic (`33`) |
| `…-fogn` | 0.25 | 120 m | 20 m | **0** | 2 | absolute | the TINT axis alone — neutral `T` |
| `…-fogcam` | 0.25 | 120 m | 20 m | 1 | 2 | **camera** | the HEIGHT REFERENCE axis (F3) |
| `…-fogy` | 0.25 | 120 m | 20 m | 1 | **1** | absolute | the UP AXIS falsifier (F1) — **never ship** |

**Why H = 120 m and not the design draft's 1000 m.** With the airmass-excess
form, `H` is the *only* thing that sets the street-to-rooftop gradient: `A`
scales everything and cancels out of the ratio, and `y0` is degenerate with
`A` entirely (§3). At H = 1000 m a 50 m climb changes the optical depth by
5%, which is invisible — the term would have read as a pure sun-brightness
slider and F4 would have been unfalsifiable. H = 120 m is deliberately
tighter than a real atmosphere's ~8 km scale height; the justification is
that this is modelling *ground-level urban haze in a canyon city*, not the
whole air column, and the whole-column part is what the artist already baked
in and what §3's excess form subtracts back out.

### 8b. Expected transmittance, `T` at **y = 0 m** and **y = 50 m** (R/G/B)

Absolute world height, Z-up, `y0 = 20 m`, `H = 120 m`. Zenith sun is `T = 1.000`
exactly on every rung — that is the point of the excess form, and it is the
row to check first if a frame looks dim at noon.

| rung | elev | T at y = 0 m | T at y = 50 m | G ratio | R/B at y=0 |
|---|---|---|---|---|---|
| `-fog` (A=0.25, p=1) | 45° | 0.896 / 0.885 / 0.865 | 0.930 / 0.923 / 0.909 | 1.04× | 1.03 |
| | 30° | 0.766 / 0.744 / 0.705 | 0.839 / 0.823 / 0.794 | 1.11× | 1.09 |
| | 20° | 0.599 / 0.567 / 0.511 | 0.713 / 0.688 / 0.642 | **1.21×** | 1.17 |
| | 10° | 0.282 / 0.245 / 0.190 | 0.434 / 0.396 / 0.334 | **1.61×** | 1.48 |
| | 5° | 0.061 / 0.045 / 0.026 | 0.159 / 0.130 / 0.090 | 2.87× | 2.39 |
| `-foghi` (A=0.50, p=1) | 45° | 0.802 / 0.783 / 0.749 | 0.865 / 0.851 / 0.826 | 1.09× | 1.07 |
| | 20° | 0.359 / 0.321 / 0.261 | 0.509 / 0.473 / 0.412 | **1.47×** | 1.38 |
| | 10° | 0.079 / 0.060 / 0.036 | 0.188 / 0.157 / 0.112 | 2.61× | 2.20 |
| `-fogx` (A=1.00, p=1) | 45° | 0.643 / 0.613 / 0.561 | 0.748 / 0.724 / 0.683 | 1.18× | 1.15 |
| | 20° | 0.129 / 0.103 / 0.068 | 0.259 / 0.224 / 0.170 | 2.17× | 1.89 |
| | 10° | 0.006 / 0.004 / 0.001 | 0.035 / 0.025 / 0.012 | 6.79× | 4.86 |
| `-fogn` (A=0.25, p=0) | 20° | 0.567 / 0.567 / 0.567 | 0.688 / 0.688 / 0.688 | 1.21× | **1.00** |
| | 10° | 0.245 / 0.245 / 0.245 | 0.396 / 0.396 / 0.396 | 1.61× | **1.00** |

Read the ship rung's 20° row as the design target: street sun at ~0.6 with a
`+21%` lift 50 m up and a `1.17` red/blue ratio. That is a visible but not
absurd delta — it is roughly a third of a stop of height gradient, which a
V1/V3 pair can resolve and which no one would mistake for a bug. `-fogx` at
10° is ×0.006 at street level and is a diagnostic only: it exists to prove the
term is live, not to be looked at.

`-fogn` is the *tint* control, not a strength control: its G column is
identical to `-fog`'s to three decimals at every elevation, and only R and B
move. If `-fog` and `-fogn` are indistinguishable on screen, the per-channel
σ is not earning its place and the ship candidate should become `-fogn`.

### 8c. Non-vacuity — ten false claims, ten rejections

`dev/build_volsun.sh` fails the build if the verifier *accepts* any of these.
A verifier that cannot fail proves nothing (GOTCHAS #12).

| false claim about the shipped bytes | rejected |
|---|---|
| `-fog` is A = 0.50 | yes |
| `-fog` is p = 0 — **the tint axis** | yes |
| `-fog` is H = 1000 m — the gradient | yes |
| `-fog` is y0 = 0 m | yes |
| `-fog` is up = 1 — **the `--up` flag** | yes |
| `-fog` is camera-relative | yes |
| `-fogn` is p = 1 — **the tint axis, other direction** | yes |
| `-fogy` is up = 2 — **the `--up` flag, other direction** | yes |
| `-fogcam` is absolute-height | yes |
| `-fog` is unpatched (`--negative`) | yes |
| a deliberately bounce-gated throwaway is ungated | yes — the closure walk refuses the shape at the `am` `NMax` hop |

Two of these were real bugs the matrix caught, not decoration. The
`abs`-vs-`cam` walk originally keyed on "the height term is an `OpFAdd`",
which is true of *both* modes (the NEE origin component is itself an `FAdd` of
`prehit + t·D` in every permutation), so `-fogcam` verified as `abs`. It now
keys on the shape — an operand that is `OpCompositeExtract` of an
`OpLoad %v4float` — and a malformed `abs` build reads back as `cam` and is
caught by the caller rather than passing silently.

### 8d. Deployment status

Six directories in the repo, 93 modules each, **not installed and not parked**
(`build_volsun.sh --install` was not run, per the brief). Note for whoever
deploys: there is **no `init.lua` selector row** for these rungs, and
`init.lua:288` coerces an unknown `skinspec` to `off` — so a naive park-and-
launch is a **silent no-op**, not an error. Adding the rows needs `make
install`, which is forbidden here and which would additionally carry `82`,
`84` and `90`'s undeployed changes onto the screen along with this one. That
is a deploy decision, not a build decision, and it is left to the coordinator.

---

## 9. Not done, deferred, and honestly labelled

* **`-fogv`, the view-segment rung.** `T_total = T(P→sun) · T(prev hit→P)`
  would add a genuine near/far gradient; the segment length `t` and the
  direction `D` are both harvested 12/12 by `find_origin_offset`, and the
  closed form over a finite segment is as easy. It is **not** the ship
  candidate because applying it to the sun term alone — while GI, sky, local
  and emissive travel the same segment un-attenuated — makes the sun
  disproportionately dim, which is a new artefact, not a fix. Reaching the
  other terms is a much larger splice and is where this should go next if
  §0(3) reads well.
* **Local lights are not attenuated.** Deliberate: they are metres away.
* **In-scattering is unreachable** and this doc does not pretend otherwise
  (§0). If shafts are the actual want, the target is the engine's own
  `VolumetricFog` render node, not this raygen — a different document.
* **The up axis is not proven from a runtime value** (§1c), only from two
  structural signals and the engine convention. `-fogy` is built precisely
  because that is not good enough, and it settles it in one frame (§10).
* **Nothing installed, nothing parked, nothing committed, zero launches.**

---

## 10. The A/B — pair, frame, settings, falsifier

### The pair

**`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all`  (A, base)
vs
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`  (B, ship candidate).**

One variable: the sun NEE term is multiplied by `T ≤ 1`. Everything else in
both halves is the standing selection, byte-for-byte (81/81 non-reference
modules cmp-identical; only the 12 `rgs_reference_main` differ).

Run `-fogx` **first**, as a single frame, if there is any doubt the term is
live at all — at 10° sun it is ×0.006 at street level and cannot be missed.
Then throw it away; it is not a look candidate.

### The frame

**V1 — the long sightline at low sun.** Exterior, elevated vantage, several
hundred metres of visible depth, **sun pinned at 10–20° elevation**, weather
pinned clear, photo mode, camera pinned, both halves the same frame.

Pre-registered prediction: sunlit surfaces **darken and warm**, with a mild
*vertical* gradient (~+21% on the green channel per 50 m of height at 20°,
§8b) and, per §0(2), **no near/far gradient at all**. If a near/far gradient
appears, something other than this term moved.

**V2 — the interior null.** A room lit by practicals and GI only, no sun NEE
contribution. Every rung must be **indistinguishable from base**. This is the
on-screen identity control and the one that catches "the multiply landed on
the wrong term".

**V3 — the height sweep, same session, free.** V1's frame with the photo-mode
camera raised ~100 m. `-fog` must visibly thin; `-fogcam` must not. One pair
settles F1 and F3 together.

### Required settings — stated now, before the launch (`45`; never inferred from the capture afterwards)

PT Overdrive **on**; **PT-in-photo-mode ON** (this term exists only in the
reference PT — with it off the A/B is a null against itself); **Ray
Reconstruction OFF**, grepped from the *Proton-prefix* `UserSettings.json`
immediately before the launch, because `DLSS_D` has been observed moving
unprompted; DLSS Balanced; RayTracedLighting Psycho; 2560×1440; photo mode
with the camera pinned and both halves on the same frame;
`RayTracing/SunAngularSize = 0.53` (`83`); `BounceNumber` and
`BounceNumberScreenshot` at their defaults; **weather pinned to clear and time
of day pinned** — new for this feature, see F2; `ser=class`,
`shadowset=full-shadow`, `ptreg=on` (the base rung's own contract, re-checked
by `sync_settings.sh`'s `gi_refuse`). Standing rule (`88` §1/§2b): grep the
run's `trace_rays` log for `rgs_reference_main` — a logged trace naming an
**unpatched** module voids the capture; a missing line proves nothing.

Deploy check first (`memory`): the game runs *copies*. `cmp` the parked bytes
against the repo dirs before reading any launch, and remember §8d — these
rungs have no `init.lua` row yet, so an unknown `skinspec` silently becomes
`off` and you will be A/B-ing base against base.

### Remaining confounds

| # | risk | observation | reading |
|---|---|---|---|
| F2 | double-count with the engine's own volumetric fog | in foggy weather the frame goes far darker than §8b predicts | the engine composites its own fog; pin weather clear, treat foggy weather as out of scope |
| F3 | slot 56 is a rebase origin, not the camera | fog density steps discontinuously while travelling far across the map | `y0` becomes location-dependent; fall back to `-fogcam`, which needs no absolute height |
| F4 | "it's just a sun-brightness slider" | V1 reads as a uniform dim with no height or elevation structure | at fixed elevation on flat ground §0(2) predicts exactly that; the discriminating shots are **V3's height sweep** and a time-of-day sweep, not a rung ladder |
| F5 | the artist's baseline already contains it | 45° reads too dim even at A = 0.25 | the airmass-excess form is the mitigation; lower `A`, do **not** switch to the absolute form |
| F6 | crushed shadows at very low sun | at 5° the sun term is ×0.045 and the frame is sky+GI only | correct behaviour; if it reads as broken, raise `LU_MIN` |

### F1 — the one-frame `--up` falsifier

**`…-fog` vs `…-fogy`, one frame each, V1's camera.**

`-fogy` is byte-identical to `-fog` except that the height is read from world
component **1 instead of 2**. The up axis is the one input to this whole term
that is argued structurally rather than measured (§1c), so it gets its own
falsifier rather than a footnote.

* If **Z-up (index 2) is right**: `-fog` attenuates by *height* — the gradient
  runs from the street to the rooftops and is invariant as the camera pans.
  `-fogy` will instead attenuate by a *horizontal* coordinate: the frame
  develops a gradient along one compass direction, buildings at the same
  height are lit differently depending on where they stand, and climbing 100 m
  (V3) changes nothing. That is unmistakable in a single frame.
* If **`-fogy` is the one that looks like height fog**, the axis assumption is
  wrong: rebuild everything with `--up 1` and re-run this A/B before reading
  any other rung. Every number in §8b survives — only the component index
  changes.

`-fogy` is a falsifier and nothing else. It is **not** a look candidate and
must never be parked as one.
