# 108 — Specular AA from the pixel footprint, and real conductor Fresnel. Built, gated, parked-ready. UNSHOT.

Written 2026-09-03. Two **independent** metal-quality features spliced at the
77 compute resolvers' direct-light GGX and Schlick sites, on the standing base
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`
(content sha `3bb0aee03a1bfda8`, `CURRENT.md`'s contract `ser=class` +
`shadowset=full-shadow`). Eight rungs built, both controls **byte-identical**,
every offline gate green, both verifiers proven non-vacuous, and both pass on
the stacked rung — which is the non-interference proof.

**Nothing has been on screen. Nothing is installed. Nothing is committed.**
`init.lua` was **not** edited; §12 has the exact rows to add.

Everything below is a measurement (§2–§6, §9) or a prediction (§8). Each says
which.

## 0. Verdict

| # | claim | evidence | confidence |
|---|---|---|---|
| 1 | The specular-AA splice reaches **75 of 77** compute modules and **303** GGX alpha ids, and every use of each alpha is rewritten | §6 gate 4 and 6; the verifier re-derives it from the shipped bytes and proves the pre-splice alpha survives in exactly two places | **high — measured** |
| 2 | The conductor-Fresnel splice reaches **77 of 77** modules, **357** Schlick groups, **1071** channels — every Schlick group in the set | §6 gate 4; verifier gate 2 ties the splice count to the group count found in the *same* shipped bytes | **high — measured** |
| 3 | The metal gate is provenance-exact: it reads the operand of the module's own `F0 = lerp(0.04, albedo, metallic)`, never a positional guess | §3.4; 357/357 groups link to exactly one metallic, 0 ambiguous | **high — measured** |
| 4 | Both controls are byte-identical to the base | §6 gate 5: 0 of 93 modules differ; both content shas **are** `3bb0aee03a1bfda8` | **high — measured** |
| 5 | The two features do not interfere | §6 gate 6b: both verifiers pass on `specaa-cfres`, and each feature is invisible to the other's verifier (§6c) | **high — measured** |
| 6 | The emitted arithmetic is the arithmetic the model says | §6 gate 7: worst closed-form relative error **0** (specaa) and **7.96e-08** (cfres) against independently written references | **high — measured** |
| 7 | Conductor F stays in [0,1] for every channel and every VoH | §3.5: 4 131 102-point sweep; 1.56 % of raw points go out of range at tint 1.0, **0** after the emitted `NClamp` | **high — measured** |
| 8 | The edge-tint mapping is **art direction, not a fit** | §3.3: measured true F82/Schlick ratios are 0.97–1.00 for gold/copper/silver and the metals that *do* dip (iron 0.77) dip **achromatically** | **high — measured, and it is the headline honesty finding** |
| 9 | specaa will visibly calm distant metal without touching near metal | §8 rows 1–3 | **low — prediction, unshot** |
| 10 | cfres will be visible on gold and copper and invisible on chrome/aluminium | §3.2's delta table says the effect is ~0 where `hue ≈ 1` | **medium — arithmetic is measured, the screen is not** |
| 11 | 40 further GGX `D` terms in the same modules are **not** widened | §9; the repo's shared `find_ggx_sites` does not report them and this build did not edit it | **high — measured, and stated as a gap, not hidden** |

## 1. What ships now, and what is wrong with it

### 1.1 One normal per pixel

Each resolver evaluates one GGX lobe from one G-buffer normal. A metal handrail
at 30 m puts many bumps inside one lighting texel; the shader samples one of
them. That is aliasing by construction: the accumulation buffer hides it while
the camera is still and turns it into crawling fireflies the moment it moves.
Nothing in the base filters roughness by footprint.

### 1.2 Every metal goes white at the silhouette

Every direct-light resolver evaluates one Schlick Fresnel per specular lobe, in
one of exactly two idioms (`28`; the census in §3.4 re-measures both):

```
form M   x = 1 - VoH ; p = (x*x)*(x*x)*x            F_c = f0_c + (1-f0_c)*p
form S   p = exp2((-6.98316002 - 5.55472994*VoH)*VoH)   F_c = f0_c*(1-p) + p
```

Both send **every channel to exactly 1.0** as `VoH -> 0`. Copper, gold, chrome
and painted steel are therefore the *same white* at the rim. Real conductors do
not do that: they dip below Schlick around 80°, and by different amounts per
channel. This is the single most-cited failure of Schlick-for-metals
(Hoffman, *Fresnel Equations Considered Harmful*, MAM 2019).

The two features are independent: one rewrites `alpha`, the other rewrites the
uses of `F`. They touch disjoint ids. §6 gate 6b proves it in the bytes.

## 2. Feature 1 — specular AA from the pixel footprint (`dev/patch_specaa.py`)

### 2.1 The formula

Kaplanyan et al. 2016 / Tokuyoshi & Kaplanyan 2019, filtering **in alpha space**:

```
N0 = normalize(gbuf(x  , y  ).rgb + bias)      the module's OWN decode
Nx = normalize(gbuf(x+1, y  ).rgb + bias)
Ny = normalize(gbuf(x  , y+1).rgb + bias)
v  = |Nx - N0|^2 + |Ny - N0|^2                 screen-space normal variance
w  = clamp((|P - C|*pix_angle - foot0) / (foot1 - foot0), 0, 1)
s2 = clamp(v * kappa * w, 0, sigma2_max)
alpha'  = sqrt(alpha^2 + s2)
alpha'' = select(metallic > 0.3, alpha', alpha)
```

then `replace_all_uses(alpha -> alpha'')`, which is `81`'s discipline and
`patch_compute_skin.build_skin_alpha_cap`'s rewrite shape, for its reason:
`a2 = alpha*alpha`, the Smith `Vis` term and the importance-sampling branch all
read the same id. Rewriting only the `D` term biases MIS — the 08-DUAL-LOBE
lesson. §6 gate 6 proves the rewrite is total in the shipped bytes.

### 2.2 The distance ramp — the part the textbook leaves out

The screen-space estimate **cannot tell sub-pixel roughness from macroscopic
curvature**. A coffee mug 40 cm from the camera has a large `|dN/dx|` and is not
aliasing; its highlight is genuinely a smooth sweep, and widening alpha there
just makes near metal look sandblasted. What separates the two cases is how much
world area one texel covers. `99` hands us `P` in metres and the camera position
`C`, so:

```
foot = |P - C| * pix_angle          metres subtended by one lighting texel
```

and the widening ramps in from `foot0 = 0.010 m` (≈ 7.6 m out) to `foot1 =
0.050 m` (≈ 38 m out). **Below `foot0` the splice is exactly identity** —
`sqrt(alpha^2 + 0)` — which is the brief's requirement and the only way the A/B
can be read: *if near metal changes, the ramp is wrong* (§8 row 4).

`pix_angle = 0.001311 rad/texel` is a **BUILD CONSTANT, not a fetch**. The
resolvers never load the projection's vertical FOV in a form this pass can
anchor on; `100` / `dev/glint_model.py` already set the precedent of pinning it.
The value is `2*tan(40°)/720` for the default 80° horizontal FOV at 16:9 and the
1280×720 lighting resolution. A player on a different FOV slider gets a ramp
scaled by the FOV ratio — the feature degrades in scale, not in kind. Stated
here so nobody discovers it from a capture.

### 2.3 The splice, instruction by instruction

Emitted once per dominating block (**205 estimators for 303 alphas** — the pass
reuses an estimator whose insertion block dominates the next alpha), then five
instructions per alpha at that alpha's own definition line. Real excerpt from
`03dc7a51279e7427`, id-for-id:

```
 %1385 = OpIAdd %uint %267 %uint_1                 ; x+1   (%267/%268 are the
 %1386 = OpIAdd %uint %268 %uint_1                 ; y+1    module's own coord)

 %1387 = OpCompositeConstruct %v2uint %267 %268    ; ---- centre tap
 %1388 = OpImageFetch %v4float %213 %1387 Lod %uint_0
 %1389..%1391 = OpCompositeExtract %float %1388 0/1/2
 %1392..%1394 = OpFAdd %float %1389.. %float_n0_5  ; the module's OWN bias
 %1395 = OpCompositeConstruct %v3float %1392 %1393 %1394
 %1396 = OpDot %float %1395 %1395
 %1397 = OpExtInst %float %1 InverseSqrt %1396
 %1398..%1400 = OpFMul %float %1397 %1392..        ; N0
 %1401..%1414   ---- the (x+1, y) tap, same 14 instructions           -> Nx
 %1415..%1428   ---- the (x, y+1) tap, same 14 instructions           -> Ny

 %1429..%1431 = OpFSub %float Nx_k N0_k
 %1432 = OpCompositeConstruct %v3float %1429 %1430 %1431
 %1433 = OpDot %float %1432 %1432                  ; |dN/dx|^2
 %1434..%1438  ---- the same for dN/dy                                 ; |dN/dy|^2
 %1439 = OpFAdd %float %1433 %1438                 ; v

 %1442..%1446   ---- (x+1,y) texel == 0 ?  3 OpFOrdEqual + 2 OpLogicalAnd
 %1447..%1451   ---- (x,y+1) texel == 0 ?
 %1440 = OpLogicalOr  %bool %1446 %1451
 %1441 = OpSelect %float %1440 %float_n0 %1439     ; drop an out-of-bounds tap

 %1452..%1454 = OpFSub %float P_k C_k              ; the module's OWN P and C
 %1455 = OpCompositeConstruct %v3float %1452 %1453 %1454
 %1456 = OpDot %float %1455 %1455
 %1457 = OpExtInst %float %1 Sqrt %1456            ; |P - C|
 %1458 = OpFMul %float %1457 <pix_angle>
 %1459 = OpFSub %float %1458 <foot0>
 %1460 = OpFMul %float %1459 <1/(foot1-foot0)>
 %1461 = OpExtInst %float %1 NClamp %1460 0 1      ; w

 %1465 = OpFMul %float %1441 %float_0_5            ; * kappa   \ SCALE BEFORE
 %1466 = OpFMul %float %1465 %1461                 ; * w       / THE CLAMP
 %1467 = OpExtInst %float %1 NClamp %1466 0 <s2max>; sigma2

 %1469 = OpFMul %float %819 %819                   ; ---- per alpha (5 ops)
 %1470 = OpFAdd %float %1469 %1467
 %1471 = OpExtInst %float %1 Sqrt %1470            ; alpha'
 %1472 = OpFOrdGreaterThan %bool %295 %float_0_300000012
 %1473 = OpSelect %float %1472 %1471 %819
 %820  = OpFMul %float %1473 %1473                 ; the module's own a2, now
                                                   ; reading the widened alpha
```

**81 instructions per estimator, 5 per alpha** (measured: 18 192 added
instructions over 75 modules, median 184 per module, min 89, max 443).

### 2.4 Anchoring (GOTCHAS 5 and 10)

* **The normal is found by its DECODE, not its slot.** An `OpImageFetch
  %v4float` whose components 0/1/2 each feed `OpFAdd %float _ <bias>`, which
  feed a v3 construct, a self-dot, an `InverseSqrt` and three `OpFMul`s.
  Exactly **one** fetch matches in **75 of 77** modules. The `bias` constant is
  read off the module, never typed.
* **The neighbour coordinate is genuinely `coord + 1`.** The coord is assembled
  from a *tile list* — `x = (tile_x << 4) | (gid.x & 15)` — which looks like a
  swizzle and is not: the low four bits of the left operand are zero, so the OR
  is an add and `+1` crosses a tile boundary correctly. This was checked before
  it was used; a wrong read here would have sampled a random tile.
* **`metallic` is not guessed.** It is the operand of the module's own
  `F0 = lerp(0.04, albedo, metallic)` triple (`80` §2.4's idiom, re-derived by
  `patch_cfres.find_f0_metal_triples`). All 75 kept modules have exactly one
  such triple and it dominates every alpha site — 0 lifts needed, 0 failures.
* **Out of bounds.** Vulkan returns zero for an out-of-bounds image load, so the
  last column and row would decode to `(-0.5,-0.5,-0.5)` and read as maximum
  variance. The all-zero texel is detected exactly (3 `OpFOrdEqual` + 2
  `OpLogicalAnd` per neighbour) and the tap is dropped. A texel that is
  genuinely all-zero decodes to a diagonal normal; losing it costs nothing.
* **NaN.** An all-`0.5` texel decodes to the zero vector, `InverseSqrt(0) = inf`
  and the normal is NaN. The final `NClamp` absorbs it — GLSL `NMin`/`NMax`
  return the non-NaN operand, so `NClamp(NaN, 0, s2max) = 0` and
  `alpha' = alpha`. That is *why* the clamp is `NClamp` and not a hand-rolled
  min/max pair. No extra instruction was needed for it.

### 2.5 Why metal only, and why 0.3

Three reasons, in order of weight.

1. A dielectric's specular is a 0.04-F0 lobe sitting under a diffuse term that
   dominates the pixel. The same widening moves a far smaller fraction of the
   radiance and **cannot be read in an A/B** — the shot would be a null with no
   information in it.
2. The standing base **already reshapes alpha on class-1 (skin) pixels**:
   `build_skin_alpha_cap`'s ceiling is what produces the oily look. A second,
   uncoordinated widening on those same ids would fight a shipped feature
   instead of testing a new one.
3. Rough dielectrics are being patched in parallel by the world-hash pass
   (`107`). Two passes widening the same alpha would make neither rung readable.

`0.3` and not `0.5`: painted metal and dirty metal author `metallic` below 0.5
routinely (`94` found car paint is three materials), and those are exactly the
surfaces that twinkle. The Fresnel feature uses **0.5** because its claim is
about *conductors* specifically; the two gates differ on purpose and each is a
separate knob.

## 3. Feature 2 — real conductor Fresnel (`dev/patch_cfres.py`, `dev/cfres_model.py`)

### 3.1 The model and its derivation

Lazányi & Szirmay-Kalos (2005) add one term to Schlick so the curve can dip
below it in the mid-grazing band:

```
F(c) = Schlick(f0, c) - a * c * (1 - c)^6
```

The correction carries a factor of `c` **and** a factor of `(1-c)^6`, so it
vanishes at both endpoints: `F(0) = 1` and `F(1) = f0` are untouched. Hoffman
(MAM 2019) parameterises `a` by the reflectance at the *maximum* of the
correction rather than leaving it free. That maximum is at

```
d/dc [ c (1-c)^6 ] = 0   =>   c_B = 1/7   (81.79°),   K = (1/7)(6/7)^6 = 0.05664904
```

Pin the value at that angle to `f82` and solve:

```
a = (Schlick(f0, 1/7) - f82) / K = S * (1 - f82) / K,   S = f0 + (1-f0)*(6/7)^5
```

with `(6/7)^5 = Q = 0.46265`. The shipped edge tint is

```
hue_c = (f0_c + 1e-4) / (max3(f0) + 1e-4)
f82_c = lerp(1, hue_c, tint)
```

so `tint = 0` is **exactly** Schlick and `tint = 1` pins the F82 reflectance to
the F0 hue itself. The `1e-4` is **biased toward the identity**: written the
obvious way, `f0 / max(mx, eps)` sends a black metal (`F0 = 0`) to hue 0, i.e.
to *maximum* tint, on the one material that has no hue to keep. Adding the eps
to both ends sends it to hue 1 = untouched, for the same instruction count. For
any real metal (`max3(F0) >= 0.2`) the two forms agree to five decimals.

### 3.2 What it does to the metals that matter (measurement, form M, tint 0.5)

`python3 dev/cfres_model.py --table`, delta = conductor − shipped Schlick:

| VoH | gold Δ | copper Δ | aluminium Δ |
|---|---|---|---|
| 1.000 | (0.000, 0.000, 0.000) | (0.000, 0.000, 0.000) | (0.000, 0.000, 0.000) |
| 0.500 | (0.000, −0.010, −0.029) | (0.000, −0.019, −0.022) | (−0.001, −0.000, 0.000) |
| 0.300 | (0.000, −0.047, −0.132) | (0.000, −0.087, −0.100) | (−0.002, −0.002, 0.000) |
| 0.143 | (0.000, −0.076, −0.212) | (0.000, −0.139, −0.161) | (−0.004, −0.003, 0.000) |
| 0.100 | (0.000, −0.071, −0.199) | (0.000, −0.130, −0.151) | — |
| 0.050 | (0.000, −0.049, −0.137) | (0.000, −0.090, −0.104) | — |
| 0.000 | (0.000, 0.000, 0.000) | (0.000, 0.000, 0.000) | (0.000, 0.000, 0.000) |

Read this before shooting: **the red channel never moves** (it is the max of the
F0 triple, so `hue_r = 1`), the effect is *entirely* in the other two channels,
it peaks around VoH ≈ 0.14 (81.8°), and it is ~0 on an achromatic metal.
Aluminium moves by 0.004. **Chrome will look identical and that is correct.**

### 3.3 The honesty finding — this mapping is art direction, not a fit

`python3 dev/cfres_model.py --metals` computes the exact unpolarised conductor
Fresnel from tabulated n,k and compares the true F82 against Schlick at the same
angle:

| metal | F0 (exact) | F82/Schlick, TRUE | hue = F0/max3(F0) |
|---|---|---|---|
| gold | (0.967, 0.802, 0.324) | **(0.984, 0.998, 1.003)** | (1.000, 0.830, 0.335) |
| copper | (0.952, 0.620, 0.547) | **(0.978, 0.968, 0.967)** | (1.000, 0.651, 0.575) |
| silver | (0.954, 0.959, 0.932) | **(0.985, 0.991, 0.996)** | (0.994, 1.000, 0.972) |
| aluminium | (0.912, 0.914, 0.920) | **(0.883, 0.904, 0.932)** | (0.992, 0.994, 1.000) |
| iron | (0.531, 0.512, 0.496) | **(0.766, 0.765, 0.798)** | (1.000, 0.964, 0.933) |

So: the coloured metals' *physical* Lazányi correction is **almost nothing**
(0.97–1.00), and the metals that genuinely dip — iron 0.77, aluminium 0.88–0.93
— dip **achromatically**. F0 alone does not predict the ratio (gold's blue
`F0 = 0.32` maps to a true ratio of 1.00; iron's red `F0 = 0.53` maps to 0.77).
That is exactly why Gulbrandsen (JCGT 2014) and Hoffman keep the edge tint as a
**free artistic parameter**, and it is why this rung is honest about being one:
`cfres` makes coloured metal *hold its hue at the rim*, which is a look, not a
physics correction. Anyone reading a screenshot as "now it's physically correct"
is reading it wrong. `cfres-strong` (tint 1.0) is the same look, harder.

### 3.4 The splice, instruction by instruction

Per group, at the FIRST channel's `F` definition (shared block):

```
cs   = NClamp(VoH, 0, 1)                 ; the module's own VoH
om   = 1 - cs
t0   = cs * om
gg   = t0 * pow5                         ; the module's OWN pow5 id -- form S
gk   = gg * (tint/K)                     ; rides the SG fit, like its Schlick
m1   = NMax(f0_r, f0_g) ; m2 = NMax(m1, f0_b)
den  = m2 + 1e-4 ; inv = 1 / den
gate = OpFOrdGreaterThan(metallic, 0.5)
```

then at each channel's own `F` line (9 instructions):

```
nu   = f0_c + 1e-4 ; h = nu * inv ; u = 1 - h        ; u = tint's (1 - hue)
S    = Fma(f0_c, 1-Q, Q)                             ; Schlick at the F82 angle
a    = S * u ; corr = a * gk
fp   = F_c - corr
fc   = NClamp(fp, 0, 1)
sel  = OpSelect(gate, fc, F_c)   +  replace_all_uses(F_c -> sel)
```

**10 + 3×9 = 37 instructions per group** (measured: 13 440 added over 77
modules, 12.5 per channel).

Anchoring:

* Groups come from `patch_compute_skin.find_spec_fresnel_groups`, **imported,
  not copied** — one derivation of the two idioms in the repo. It already
  rejects the Disney FD chain, whose "f0" is the constant 1.0.
* `metallic` is matched, through OpPhi/OpSelect forwarding, against the module's
  own F0-lerp triples. **357 of 357 groups link to exactly one metallic; 0
  ambiguous, 0 unresolved.**
* **The value a shader tests is not always the value it computed** (GOTCHAS).
  Two modules fetch the material inside a guarded block, so below the merge only
  a phi is live and the raw metallic dominates nothing. `dominating_metal` walks
  forward through merges **whose other operands are a literal zero** — zero is
  not a metal, so a pixel that skipped the fetch gates OFF. This is `80` §2.4's
  `lift_f0_phis` argument applied to the gate. **64 of 357 groups need the
  lift**, all 64 in those two modules; without it the pass reached 0 sites in
  both and *died* rather than guessing.
* The shared block is emitted at the **first** channel's F line, not the last. A
  late anchor is a silent zero-coverage splice here: the parent rung's own
  class-1 Fresnel reshape already inserts an `OpSelect` immediately after each F
  def, so anchoring below them would leave those consumers reading the
  un-corrected value. Checked per group: all three F defs live in one basic
  block and every `f0`/`voh`/`pow5` read is defined before the first F.

### 3.5 Energy — the gate, with numbers

`python3 dev/cfres_model.py --gate`, over 2 forms × 101 `f0` × 51 `hue` × 401
`VoH` = **4 131 102 points**. The sweep is exhaustive, not sampled: per-channel
`F` depends on the F0 triple only through `hue`.

| | tint 0.50 | tint 1.00 |
|---|---|---|
| min F, unclamped | **−0.000774** (form S, f0 0.000, hue 0.000, VoH 0.480) | **−0.126765** (form M, f0 0.000, hue 0.000, VoH 0.2625) |
| min F, restricted to reachable triples (`max3(F0) ≤ 1`) | −0.000014 | −0.119876 |
| max F, unclamped | 1.000000 | 1.000000 |
| points outside [0,1] | 132 (0.0032 %) | 64 306 (1.5566 %) |
| **with the emitted `NClamp(F,0,1)`** | **0 out of range — PASS** | **0 out of range — PASS** |

Two more gates, both bit-exact rather than tolerance-based:

* **identity**: achromatic F0, or `tint = 0`, reproduces the module's own
  Schlick **bit-exactly** over 101 f0 × 201 VoH × 2 forms — PASS.
* **endpoints**: `F(VoH=0)` and `F(VoH=1)` equal the module's own Schlick
  **bit-exactly** over 101 f0 × 3 tints × 2 forms — PASS. Note the claim is
  against *the module's* Schlick, not against `f0`: form S's SG fit gives
  `p(1) = 1.68e-4`, so `F(1) = f0 + (1-f0)*1.68e-4` and asserting `F(1) == f0`
  would have been asserting the wrong thing. That mistake was made and fixed.

**Never upstream of Fresnel.** GOTCHAS warns that splicing upstream of Fresnel
means Fresnel weights your term too. This splice **is** the Fresnel: it rewrites
the uses of `F_c`, so the module's own `F*Vis*D` assembly is untouched in shape
and nothing is weighted twice.

## 4. Coverage

| | modules | sites | detail |
|---|---|---|---|
| `specaa` | **75 of 77** | **303** alpha ids over **351** GGX sites, 205 estimators | 40 further D-term alphas not reached — §9 |
| `cfres` | **77 of 77** | **357** Schlick groups, **1071** channels (301 form-M, 56 form-S) | 64 groups need the phi lift |
| raygen | 0 of 16 | — | all 16 ship **byte-verbatim**, `cmp`-asserted per rung |

Declined by hash, with the measurement that declines them — **both** are the
modules `99` also declines, for the same underlying reason (they are the two
resolvers that do not carry a single canonical G-buffer read):

| module | normal-decode chains | position chain | verdict |
|---|---|---|---|
| `99bb7c2698997b2a` | **8** | none | declined for `specaa`; picking 1 of 8 by position is exactly GOTCHAS 10. **Patched by `cfres`** (48 groups). |
| `ab0bc2fee876d489` | **4** | none | the v4uint reservoir pass (`46` §12); same verdict. **Patched by `cfres`** (16 groups). |

Those two are deliberately **kept** for `cfres`: it needs no surface position,
their Fresnel groups link exactly like every other module's, and a resolver
whose Fresnel moved while the reservoir pass's target function did not would
make ReSTIR reuse disagree with the shading it is reusing.

## 5. The rungs

| rung | knobs | content sha | raygen-half sha | what it is |
|---|---|---|---|---|
| `specaa-ctl` | kappa 0 | `3bb0aee03a1bfda8` | `4117e4da31532843` | CONTROL, **byte-identical to the base**, digit for digit |
| `specaa` | kappa 0.5 | `71504237037272fa` | `4117e4da31532843` | the feature |
| `specaa-hi` | kappa 1.0 | `bd2af75ec643a12f` | `4117e4da31532843` | the kernel doubled — the strength axis, one variable |
| `specaa-vis` | kappa 0.5 | `bcd6201ba6a303a0` | `4117e4da31532843` | DIAGNOSTIC: `sigma2/0.18` painted grey on gated pixels, **alpha untouched**. Meant to look wrong. |
| `cfres-ctl` | tint 0 | `3bb0aee03a1bfda8` | `4117e4da31532843` | CONTROL, **byte-identical to the base** |
| `cfres` | tint 0.5 | `c5c1a0ed65e1bb6f` | `4117e4da31532843` | the feature |
| `cfres-strong` | tint 1.0 | `506275126f88d2cf` | `4117e4da31532843` | edge tint fully saturated — the strength axis |
| `specaa-cfres` | both | `b3e7aa854378ab76` | `4117e4da31532843` | THE STACK. Both verifiers pass on these bytes. |

The base's content sha is `3bb0aee03a1bfda8`; **both control shas are the
base's**, after a full `dis → patcher → as → val` round trip. The raygen half
is identical in all eight, which is what "compute-only" means here.

## 6. Offline gates — all green (measurement)

`./dev/build_specaa_cfres.sh`, ~4 min, every gate build-failing.

0. **base provenance** — 77 compute + 16 raygen, `MANIFEST` present, content sha
   printed.
1. disassembly of all 77.
2. **round-trip neutrality** — `spirv-dis → spirv-as` reproduces the base bytes
   on **77 of 77** at each module's own SPIR-V version, *before* any rewrite.
   Without this the controls prove nothing.
2b. **`dev/cfres_model.py` gates** — §3.5's identity, endpoints and energy
   sweeps, at both shipped tints.
3. patch 8 rungs × 77 modules; the stack is `cfres` over `specaa`'s **own**
   output, with the two specaa-declined modules taken from the base
   disassembly so `cfres` still reaches all 77.
4. **coverage from the JSON reports, never from byte counts** (`27` §8.3: 48
   bytes of unconsumed `OpConstant` is a byte diff and zero coverage):

```
  specaa       : 75 modules, 2 declined, 303 alphas, 351 GGX sites, 205 estimators
  specaa-hi    : 75 modules, 2 declined, 303 alphas, 351 GGX sites, 205 estimators
  specaa-vis   : 75 modules, 2 declined, 150 writes
  specaa-ctl   : 77 modules, 0 declined, 0 alphas
  cfres        : 77 modules, 0 declined, 357 groups, 1071 channels (301 M, 56 S, 64 lifts)
  cfres-strong : 77 modules, 0 declined, 357 groups, 1071 channels
  specaa-cfres : 77 modules, 0 declined, 357 groups, 1071 channels
  cfres-ctl    : 77 modules, 0 declined, 0 groups, 0 channels
```

   with every `skipped_*` list asserted **empty** and every knob asserted
   single-valued across the 77.
5. **assemble + `spirv-val --target-env vulkan1.4` on all 93 × 8**, the 16
   raygens `cmp`-asserted against the base per rung, and the difference counts:

```
  specaa / specaa-hi / specaa-vis : 75 of 77 compute modules differ
  cfres / cfres-strong / specaa-cfres : 77 of 77 differ
  specaa-ctl / cfres-ctl : 0 of 93 differ
  specaa vs specaa-hi 75 | specaa vs cfres 77 | cfres vs cfres-strong 77
  specaa vs specaa-cfres 77 | cfres vs specaa-cfres 75
```

   — no two rungs are byte-identical, so no rung is a silent no-op.
6. **the verifiers, on the shipped bytes**, re-deriving everything from
   disassembly and reading no build report:

```
  verify_specaa OK: 75 modules, 303 widened of 343 GGX D-term alphas (40 KNOWN
      gap), 205 estimators, kappa=0.5 s2max=0.18 metal_min=0.3 ramp=0.01..0.05 m;
      worst closed-form rel err 0 (tol 2e-05)
  verify_specaa OK: ... kappa=1 ...                       worst rel err 0
  verify_specaa OK (vis): 75 modules, 150 painted writes  worst rel err 0
  verify_specaa OK (--mode none): 77 compute + 16 raygen, 0 spliced
  verify_cfres OK: 77 modules, 357 Schlick groups, 1071 channel splices,
      tint=0.5 metal_min=0.5; worst closed-form rel err 7.96e-08 (tol 3e-05)
  verify_cfres OK: ... tint=1 ...                         worst rel err 1.03e-07
  verify_cfres OK (--expect-none): 357 Schlick groups present, 0 spliced
```

6b. **NON-INTERFERENCE** — both verifiers pass on `specaa-cfres` at full
    strength, so neither splice damaged the other's shape, provenance or
    arithmetic.
6c. **each feature is invisible to the other's verifier** — `verify_specaa
    --mode none` passes on `cfres`, `verify_cfres --expect-none` passes on
    `specaa`. The two really are disjoint rewrites.
6d. **rejections — 18 of them, every one required to FAIL**: the unpatched base
    under each verifier; each control read as its feature; each feature read as
    "none"; `specaa` read at the `-hi` kernel and `specaa-hi` at the base
    kernel; `specaa` read as `vis` and `specaa-vis` read as the feature;
    `specaa` at a wrong `sigma2_max`, a wrong metal gate and a wrong ramp;
    `cfres` read at the strong tint and `cfres-strong` at the base tint;
    `cfres` at a wrong metal gate; and the **stack** read at both wrong knobs.

The verifiers' own claims, for the record — they are the reason the numbers
above mean anything:

* `verify_specaa` proves **the rewrite is total**: for each splice, the
  pre-splice alpha id survives in exactly two places, the `alpha*alpha` of the
  widening and the else-arm of the select. Any other surviving use would be an
  eval/sampling disagreement and fails the gate.
* It anchors coverage on `D = a2/(x*pi)` with **no line windows** (§9 says why),
  re-derives `P` from the module's own chain (`registers[0]+12` view CBV,
  `registers[1]+0` depth) and the metallic from the module's own F0 triple, and
  then **interprets the emitted straight-line chain out of the disassembly** over
  a grid of G-buffer texels and positions, comparing against a model written in
  the verifier. Worst error **0** — bit-exact.
* `verify_cfres` ties the splice count to the number of Schlick groups found in
  the *same* shipped bytes, so 356 of 357 fails; checks every constant to the
  float32 bit; and interprets the chain against `cfres_model.conductor_F` over a
  VoH grid at eight F0 triples including copper, gold and the black corner. It
  also asserts the **ungated arm is the module's own Schlick bit-exactly**, so a
  non-metal pixel is unchanged by construction, not approximately.

## 7. The shoot — READ THIS BEFORE LAUNCHING

**Settings, stated now, before any frame. Do not infer them from a capture
afterwards.**

| setting | value | why |
|---|---|---|
| `ser` | **`class`** | the base's contract; the rungs carry its raygens verbatim |
| `shadowset` | **`full-shadow`** — not optional | any rung shipping raygens needs it |
| `ptq` | unchanged from the standing default | `ptq_sha` must match `55ed4e5c6884ab71` or `sync_settings.sh` refuses |
| RR | **OFF** | |
| path tracing | **ON**, reference/photo mode | these are the compute resolvers |
| camera | **pinned for the still pair, then a slow pan for specaa** | see below |
| frame generation | **state it** (`100` §7's lesson) | |
| resolution | **state it** — the ramp is calibrated for a 1280×720 lighting buffer at 80° FOV (§2.2) | |
| FOV slider | **state it** | `pix_angle` is a build constant |
| `skinspec` | one of the eight rows in §12 | |

**Precondition, non-negotiable** (`101` §10 row 0, `99` §10.8e): before reading
a single colour, grep the launch log for `skin_sha` and confirm it equals the
§5 sha for the rung you think you shot, and confirm the served
`rgs_reference_main` permutation. An entire capture has already been voided for
want of this check.

**The frame — one camera, all rungs.** It must contain, simultaneously:

1. **a distant rough-metal surface** — a fire escape, a chain-link fence, a
   railing or an AC unit at **25–60 m**. This is where `specaa` acts.
2. **a close copper or gold surface** — a brass door plate, gold trim, a copper
   pipe **under 3 m**, filling enough pixels to read a hue. This is where
   `cfres` acts, and it is *also* the control for `specaa`: at 3 m the ramp
   weight is 0, so **`specaa` must not change it at all**.
3. **a skin control** — a face in the same frame. Neither feature gates on skin;
   if skin moves, something is wrong with the selection, not with the feature.

**Order.** Shoot `specaa-vis` **FIRST**. It is the only rung that can falsify
the mechanism, and every `specaa` reading below is conditional on it. Then the
still pair `specaa-ctl` / `specaa`, then a **slow pan** on the same pair (the
aliasing this feature targets is temporal — a still frame may show nothing even
when the feature is working). Then `cfres-ctl` / `cfres` on the same still
camera, then `cfres-strong`, then the stack.

## 8. Pre-registered interpretation table (prediction — written BEFORE the screen)

**Rows 1–3 are read off `specaa-vis` alone.**

| # | reading | what it means | what to do |
|---|---|---|---|
| 1 | `specaa-vis` is **grey/white on the distant fence and railings, black on the near copper, black on skin and on all dielectrics** | the estimator, the ramp and the gate all work. This is the pass. | go to rows 4–8 |
| 2 | `specaa-vis` is **black everywhere** | either no metal in frame (re-frame), or the ramp never opens — check the FOV and the lighting resolution against §2.2 before touching anything | re-shoot with a known-metal object at 40 m |
| 3 | `specaa-vis` is **white on near metal too** | the distance ramp is inverted or `P` is not in metres for this build. **This would also invalidate `99`'s reading**, so it is a headline, not a tweak | stop; re-run `dev/hunt_wpos.py` before any other conclusion |
| 4 | on the **pan**, `specaa` shows **less crawling on the distant fence** and the near copper is **pixel-identical** to `specaa-ctl` | **the pass.** | shoot `specaa-hi` for the strength axis |
| 5 | the near copper **changed** between `specaa` and `specaa-ctl` | the ramp is not doing its job — foot0 is too small for this FOV/resolution, or `P` is camera-relative in the wrong sense | raise `foot0`; one new rung, one variable |
| 6 | distant metal is **blurred/washed rather than calmed** — the highlight is gone, not steadied | `sigma2_max = 0.18` is too generous at this distance; the widening has swallowed the lobe | drop to 0.06 and rebuild; do **not** change kappa at the same time |
| 7 | `specaa` and `specaa-ctl` are **indistinguishable on the pan** | either the accumulation buffer is already doing this job (likely in reference mode with a slow pan), or 0.5 is too weak | read `specaa-hi` in the same pan before concluding; if that is also null, the feature belongs in a real-time preset, not reference mode |
| 8 | `specaa-hi` is **visibly better than `specaa`** | strength-limited; the axis is real | price it, then pick a kappa |
| 9 | on the still pair, `cfres` makes the **copper/gold rim hold its colour** where `cfres-ctl` goes white, and chrome/aluminium/steel are **unchanged** | **the pass**, and it matches §3.2's arithmetic exactly | read `cfres-strong` for taste, then decide which ships |
| 10 | `cfres` changes **chrome or aluminium** | impossible from §3.2's numbers (Δ ≤ 0.004) unless the gate is reading something other than `metallic` — treat as a bug | re-read §3.4's provenance claim and the `verify_cfres` gate output |
| 11 | `cfres` changes **dielectrics** — plastic, paint, skin | the metal gate is not gating. Also a bug, not a taste question | stop and diagnose the gate |
| 12 | `cfres-strong` looks **dirty / muddy** on gold at grazing angles | expected at tint 1.0: §3.5 shows 1.56 % of the raw sweep goes negative and is clamped to 0, and clamped-to-zero is a *black* rim | ship `cfres` at 0.5; `-strong` is the bracket, not the candidate |
| 13 | **either control is distinguishable from the standing base** | the layer is not serving what it claims, and **every A/B in this repo inherits the doubt**. Headline finding. | stop; re-run the deploy `cmp` before reading any other colour |
| 14 | the log's `skin_sha` does not match §5, or names an unpatched permutation | **VOID.** No colour in the frame means anything. | re-launch |
| 15 | "no effect" and **the frame has no metal above `metallic` 0.3 / 0.5 in it** | **VOID, not a null.** Both features gate on metal; a frame without metal cannot show them | re-frame per §7 |
| 16 | "no effect" for `specaa` read from a **still** frame only | **VOID, not a null.** Specular aliasing is temporal; a converged still is the one condition under which the feature is expected to be invisible | re-shoot the pan |
| 17 | `specaa-cfres` shows something **neither** single rung shows | the two do interact on screen despite §6b's byte proof — most likely through the shared metal gate on a pixel whose `metallic` sits between 0.3 and 0.5 | record it; it is a real finding about the gate split, not about either feature |

## 9. What is NOT done — and one measured gap

* **40 GGX `D` terms are not widened.** Anchoring window-free on
  `D = a2/(x*pi)` finds **343** distinct alpha ids in the 75 kept modules; the
  repo's shared `patch_skin_brdf.find_ggx_sites` — which `81` used and which
  this pass uses — reports **303** of them. The other 40 are skipped by that
  detector because its `Vis*D` and per-channel-output searches run inside 80-
  and 160-line **windows**, and those consumers sit further away. The brief
  forbade editing existing `dev/` scripts, so the detector was left alone and
  the gap is **asserted** by the verifier (303 of 343, exactly) rather than
  papered over. Closing it means either a window-free detector in a new file or
  a fix to the shared one — a separate change with its own A/B, because it would
  move the census.
* **Dielectrics get no specular AA.** §2.5. Deliberate, and coordinated with
  `107`.
* **No conductor Fresnel below `metallic` 0.5**, and the two features use
  *different* metal thresholds (0.3 / 0.5) on purpose. Row 17 pre-registers what
  that can look like.
* **`pix_angle` is a build constant.** §2.2. A FOV or lighting-resolution change
  rescales the ramp.
* **The edge tint is not a fit.** §3.3. It cannot be, from F0 alone.
* **The 40-instruction estimator is per dominating block, not per pixel.** 205
  estimators for 303 alphas means up to 8 estimators in one module — each is 3
  image fetches. See §10.
* **No raygen module is touched**, so the reference and ReSTIR passes keep
  vanilla Schlick and vanilla alpha. `cfres` covers all 77 compute modules
  partly for this reason; `specaa` cannot (§4).
* **Not launched, not installed, not committed.** No `make install` was run.

## 10. Cost

* `specaa`: **81 instructions + 3 `OpImageFetch` per estimator**, 5 instructions
  per alpha. 205 estimators over 75 modules — median 184 added instructions per
  module, max 443. The three taps are same-tile G-buffer reads that the module
  has already touched this pixel, so they should be L1 hits; the honest number
  to watch is the **fetch count**, up to 24 extra fetches in the worst module.
* `cfres`: **37 instructions per Schlick group**, no fetches, no control flow,
  no new capabilities. 12.5 instructions per channel; 13 440 over 77 modules.
* Neither feature adds a branch, a loop, an `OpTraceRayKHR`, a ray query or a
  descriptor.
* Both gates are `OpSelect`, so a non-metal pixel executes the same instructions
  and keeps a bit-exact vanilla result.

## 11. Files

New, none shared and none edited:
`dev/patch_specaa.py`, `dev/patch_cfres.py`, `dev/verify_specaa.py`,
`dev/verify_cfres.py`, `dev/cfres_model.py`, `dev/build_specaa_cfres.sh`,
`handoff/108-SPECAA-CONDUCTOR.md`.

Imported read-only, never modified: `patch_skin_brdf` (`Module`, `apply_edits`,
`roundtrip_check`, `replace_all_uses`, `find_ggx_sites`), `patch_chs_brdf`
(`load_lenient`, `uses_of`), `patch_shadow_brdf` (`CFG`), `patch_compute_brdf`
(`detect_target_env`, `find_image_writes`), `patch_compute_skin`
(`find_spec_fresnel_groups`, `_emit`), `wpos_core` (`find_pos_chain`,
`find_campos`, `pos_leaves`, `emit_world_pos`, `Dom`, `cone`).

Read and not edited: `handoff/CURRENT.md`, `handoff/GOTCHAS.md`,
`handoff/97`, `handoff/99`, `handoff/28`, `handoff/80`, `handoff/81`,
`dev/patch_ms_ggx.py`, `dev/patch_compute_skin.py`, `dev/wpos_core.py`,
`dev/build_wpos.sh`, `dev/build_contact_rq.sh`.

**`init.lua`, `swap_layer.c`, the `Makefile`, `CURRENT.md`, `GOTCHAS.md` and
every existing `dev/` script and handoff doc were NOT touched.**

## 12. `init.lua` entries to add (this build did not edit that file)

Add these eight rows to `SKIN_LEVELS`, after the `contact-rq` block and before
the `sentinel` rows. Park the rungs first with
`./dev/build_specaa_cfres.sh --install`.

```lua
    -- 108: SPECULAR AA FROM THE PIXEL FOOTPRINT + REAL CONDUCTOR FRESNEL.
    -- Two INDEPENDENT compute-only features; the raygens are the default's
    -- bytes in all eight. Read handoff/108 sec 7 BEFORE launching: the frame
    -- must hold distant rough metal (25-60 m), close copper or gold (<3 m)
    -- and a face, and specaa must be read off a PAN, not a still.
    -- Shoot specaa-vis FIRST.
    { id = "specaa-ctl",   label = "Spec-AA CONTROL (kappa=0; byte-identical to the DEFAULT)" },
    { id = "specaa-vis",   label = "DIAGNOSTIC: pixel-footprint normal variance -- GREY = widened, BLACK = untouched. Alpha unchanged; meant to look wrong" },
    { id = "specaa",       label = "SPEC-AA on metal (metallic>0.3): alpha widened by normal variance, ramped in from ~7.6 m to ~38 m" },
    { id = "specaa-hi",    label = "SPEC-AA, kernel doubled (kappa=1.0) -- the strength axis, one variable" },
    { id = "cfres-ctl",    label = "Conductor-Fresnel CONTROL (tint=0; byte-identical to the DEFAULT)" },
    { id = "cfres",        label = "REAL CONDUCTOR FRESNEL on metal (metallic>0.5): copper and gold keep their hue at the rim instead of going white" },
    { id = "cfres-strong", label = "Conductor Fresnel, edge tint fully saturated (tint=1.0) -- the bracket, not the candidate (108 sec 8 row 12)" },
    { id = "specaa-cfres", label = "THE STACK: spec-AA + conductor Fresnel together (both verifiers pass on these bytes)" },
```

All eight need `ser=class` + `shadowset=full-shadow`, the base's contract.
