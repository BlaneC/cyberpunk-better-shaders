# 109 — Curvature-driven skin scattering (2026-09-03)

The ask: make the terminator diffusion band respond to **local surface
curvature** (Penner 2011, *pre-integrated skin shading*) instead of running on
one hard-coded width everywhere. 97 §3.4 flagged that width — `0.35` — as a
stylisation constant chosen *because curvature was not computable at the
splice site*. 99 then measured that it is: every compute resolver already binds
the depth target at `registers[1]+0` and the packed G-buffer normal at
`registers[1]+2`, and reconstructs a world-space **P** in metres from a matrix
at `cbv[registers[0]+12][69..72]`. Four extra texel fetches turn that into

```
    kappa = |N(x+1) - N(x)| / |P(x+1) - P(x)|          [1/m]
```

averaged over the x and y neighbours — Penner's
`length(fwidth(N)) / length(fwidth(P))`, written out by hand because this is
compute and there are no derivatives.

**Status: SHOT 2026-09-03 and KEPT — `curv` (g = 1) is the shipped default.
NOT COMMITTED.** Four rungs are in `~/.local/lib/callisto/skin.set/` (`curv`,
`curv-hi`, `curv-vis`, `curv-ctl`), plus the shipping stack
`…-glintdense-curv`, content sha `024998da26d84333` (§13). Every number in
§§1–12 is static: read off the shipped bytes by `dev/verify_curv.py`, or
computed in float32 by `dev/curv_model.py`. **The keep is a LIVE read-out —
no frame was captured, and `curv-vis`, the designated falsifier, was never
shot: zero of §8's seven visual rows were read as written (§13.2).**

**Read §0, then §13. §8 is still the instrument for the next frame.**

---

## 0. Verdict — read first

| claim | verdict | confidence |
|---|---|---|
| Curvature is computable at the resolver splice site with no new resource, no new binding, no branch | **yes** — depth image, normal image, both dispatch coordinates and all four matrix rows dominate the splice in **75 of 75** patchable modules | **certain** — `dev/cfg_dom.py` dominance-checked, 75/75, and `spirv-val --target-env vulkan1.4` is clean on 4 × 77 outputs |
| One hoisted estimator per module suffices (not one per site) | **yes, 75 of 75** — the hoist dominates every bleed site in its module | **certain** (gate 5: one anchor/knob tuple across the whole family, `curv_instructions` min = max = **144**) |
| The centre normal can be reused from the module's own decode | **yes, 75 of 75** — so only **4** taps are added, not 5 | **certain** |
| `s` reaches the band **width** and the **amplitude**, and nothing else | **yes, 142 of 142 sites** | **certain** — verifier walks `bq' = FDiv(bq, s)` and `bw' = FMul(bw, s)` and asserts `bw'` still has exactly its **3** shipped consumers |
| 78's luminance neutrality survives the change | **yes, exactly** — the third consumer of `bw` is 78's own hold term, so it rescales with the other two | **certain algebraically; measured 9.12e-08** worst relative Rec.709 error over 4 colours × 5 values of `s` × 7 NoL (`dev/curv_model.py`) |
| The specular is untouched | **yes** | **certain** — no GGX, Fresnel, roughness or `c1` instruction is read or written by this patch |
| Silhouettes fall back to the shipped constant rather than blowing up | **yes** — `s = select(|dPx|² < J² && |dPy|² < J², s_raw, 1.0)`, `J = 5 cm` | **certain in the bytes**; the *threshold* is a judgement call, see §9.2. `OpFOrdLessThan` is used so a NaN tap also falls back |
| The `c1` term gets a curvature-driven width too | **NO — it has no width or wrap parameter to scale.** §3.5 | **certain** — `c1 = (1+(ρ_f−1)α_f)(1+(ρ_r−1)α_r)` with `α = (1−NoL)^a · NoV^b`: power-law lobes over the whole hemisphere, not a band of finite width. Nothing declined silently |
| Coverage | **75 of 77 modules, 142 of 150 bleed sites.** The 8 unreached sites are named by hash in §5 | **certain** |
| It looks better on a face | **YES — SHOT 2026-09-03 and KEPT as the default.** Verbatim: *"tested the curvature based bleed effect and it looks incredible"* | **user verdict, LIVE read-out only** — no capture, no frame file, and the `curv-vis` falsifier was not shot. §13 |
| The estimator provably follows the geometry **on screen** | **NOT READ.** `curv-vis` never launched | — |

**The one-line result.** The 0.35 band is now a *per-pixel* band: `0.105` on a
flat chest, `0.29` on a forehead, `0.35` on a cheek (unchanged, by
construction), `0.70` on a nose wing, lip roll, jaw and ear rim — and exactly
`0.35` again on any pixel whose neighbour taps cross a silhouette. The whole
change is two extra instructions per site (`FDiv`, `FMul`) plus one 144-
instruction estimator per module.

---

## 1. What is being changed, precisely

97 §3.4's shipped terminator bleed, at each of its 150 sites:

```
    bq = NoL * (1/0.35)              <- the band WIDTH (as its reciprocal)
    t  = sat(1 - bq)
    w  = t * t                       <- the band AMPLITUDE
    m_R = 1 + k * 0.336 * w          Jensen 2001 skin1, d_R:d_G:d_B = 2.68:1:0.50
    m_B = 1 - k * 0.101 * w
    nsc = Y / (Y + beta*w*k*(0.2126*0.336*C_R - 0.0722*0.101*C_B))   <- 78's hold
```

`w` has exactly **three** consumers: the red multiplier, the blue multiplier,
and 78's luminance-hold denominator. That is the whole reason this patch is
two instructions:

```
    bq' = bq / s        widen the band by s          (W -> W * s)
    w'  = w  * s        and scale the red shift by s (amplitude -> amplitude * s)
```

Rescaling the single value `w` reaches all three consumers, so **78's hold sees
the same `w` the bleed does, for any `s`**. The neutrality is not re-derived,
it is inherited. `dev/curv_model.py` measures the residual at **9.12e-08**
relative Rec.709 luminance — i.e. float32 round-off, not a model error.
Under tinted light 78 §4's ±3–4% residual still applies, unchanged; `s` does
not make it better or worse.

The verifier asserts the 3-consumer count **at every site, before and after**,
so a future patch that adds a fourth consumer of `w` and forgets the hold will
fail gate 7 rather than quietly desaturating faces.

---

## 2. The estimator, instruction by instruction

Emitted once per module, at a hoist line computed as
`max(depth-chain leaves, normal image load, coordinate defs, centre-P def)`
(and asserted to dominate every bleed site, and never to land on a merge
instruction). This is the emitted block from `03dc7a51279e7427`, in program
order, with the module's own ids:

```
  ; --- neighbour coordinates: +1 texel in x, +1 texel in y ---------------
  %1385 = OpIAdd %uint %267 %uint_1                  ; px + 1   (%267 = dispatch x)
  %1386 = OpIAdd %uint %268 %uint_1                  ; py + 1   (%268 = dispatch y)

  ; --- resources and matrix rows, loaded ONCE and shared by both taps ----
  %1387 = OpAccessChain %_ptr_UniformConstant_48 %33 %220   ; registers[1]+0, depth
  %1388 = OpLoad %48 %1387
  %1389 = OpAccessChain %_ptr_Uniform_v4float %238 %uint_0 %uint_69
  %1390 = OpLoad %v4float %1389                             ; matrix row 69
  %1391 = OpCompositeExtract %float %1390 0                 ; ... rows 70, 71, 72
   ...                                                      ; 16 scalars total
  %1437 = OpAccessChain %_ptr_UniformConstant_48 %33 %211   ; registers[1]+2, normal
  %1438 = OpLoad %48 %1437

  ; --- tap 1: (px+1, py) ------------------------------------------------
  %1413 = OpCompositeConstruct %v2uint %1385 %268
  %1414 = OpImageFetch %v4float %1388 %1413 Lod %uint_0      ; depth
  %1415 = OpCompositeExtract %float %1414 0
  %1416 = OpConvertUToF %float %1385
  %1417 = OpConvertUToF %float %268
  %1418.. = FMul / Fma / Fma / FAdd  x4 rows                 ; matrix . (x, y, z, 1)
  %1434 = OpFDiv %float %1421 %1433                          ; perspective divide -> P
  %1439 = OpImageFetch %v4float %1438 %1413 Lod %uint_0      ; NORMAL, SAME coordinate
  %1440..%1445 = extract x,y,z; each + (-0.5)                ; A2B10G10R10_UNORM decode
  %1446 = OpCompositeConstruct %v3float ...
  %1447 = OpDot ; %1448 = InverseSqrt ; %1449..51 = FMul     ; normalize

  ; --- differences against the module's own centre P and centre N -------
  %1452..%1454 = OpFSub  (Pn - P)                            ; %551..%553 = centre P
  %1455..%1457 = OpFSub  (Nn - N)                            ; %325..%327 = centre N
  %1460 = OpDot  ; |dP|^2      %1461 = OpDot  ; |dN|^2

  ; --- tap 2: (px, py+1) -- identical shape, 39 instructions -------------
  %1462 = OpCompositeConstruct %v2uint %267 %1386
   ...
  %1509 = OpDot  ; |dP|^2      %1510 = OpDot  ; |dN|^2

  ; --- kappa ------------------------------------------------------------
  %1512 = OpExtInst NMax %1460 %1511          ; %1511 = 1e-12, the divide floor
  %1513 = OpFDiv %float %1461 %1512
  %1514 = OpExtInst Sqrt %1513                ; |dN|/|dP| on the x axis
  %1515..%1517 = the same on y
  %1518 = OpFAdd %1514 %1517
  %1519 = OpFMul %1518 %float_0_5             ; kappa = mean of the two axes

  ; --- kappa -> s -------------------------------------------------------
  %1521 = OpExtInst NClamp %1519 %float_0_5 %1520        ; clamp to [0.5, 40] /m
  %1522 = OpFMul %1521 %float_0_100000001                ; / kappa0 = 10 /m
  %1523 = OpFSub %1522 %float_1                          ; pivot at the cheek
  %1524 = OpFMul %1523 %float_1                          ; x gain  (1.0 / 2.0)
  %1525 = OpFAdd %float_1 %1524
  %1526 = OpExtInst NClamp %1525 %float_0_300000012 %float_2    ; s in [0.3, 2.0]

  ; --- the silhouette guard --------------------------------------------
  %1528 = OpFOrdLessThan %bool %1460 %1527    ; %1527 = 0.0025 = (5 cm)^2
  %1529 = OpFOrdLessThan %bool %1509 %1527
  %1530 = OpLogicalAnd %bool %1528 %1529
  %1531 = OpSelect %float %1530 %1526 %float_1          ; else: the SHIPPED constant
```

**144 instructions, identical in all 75 modules** (gate 5 asserts
min = max = 144). Design notes that are load-bearing:

- **The normal is fetched at the depth tap's own coordinate id**, not at a
  separately-constructed equal coordinate. The verifier compares the id, so
  the two can never drift apart under a future edit — `dN` and `dP` are always
  measured between the same two surface points.
- **The comparison is squared-length against a squared threshold**, so there is
  no `sqrt` in the guard and no chance of a sign error.
- **`OpFOrdLessThan`**, not `LessThanEqual` or an unordered form: a NaN tap
  (out-of-bounds fetch, degenerate matrix row) compares false and falls back to
  `s = 1`. The failure mode is "shipped look", never "screaming pixel".
- **`NMax(|dP|², 1e-12)`** floors the divide, so a genuinely coincident
  neighbour gives a large-but-finite kappa which the `[0.5, 40]` clamp then
  eats. There is no path to `inf`.
- **The centre `N` is the module's own decoded normal**, taken pre-phi where it
  dominates — 75 of 75. The centre `P` is the module's own reconstructed P —
  75 of 75, zero refetches. That is what holds the cost at 4 taps.

---

## 3. The mapping, and why this one

```
    s = clamp( 1 + g * ( clamp(kappa, 0.5, 40) / 10 - 1 ), 0.3, 2.0 )
```

### 3.1 The clamps are the physical statement

`kappa` is `1/r` in metres⁻¹. `[0.5, 40] /m` is a **2 m to 25 mm radius**
window. Below 0.5 /m the surface is flat enough that a wider band is
indistinguishable from a Lambert falloff; above 40 /m the feature is smaller
than a 720p texel at conversational distance (§9.1), so the estimator is
reading noise, not geometry, and clamping is the honest response.

### 3.2 `kappa0 = 10 /m` is the cheek, and the cheek is the control

A cheek is `r ≈ 100 mm`, i.e. `kappa = 10 /m`. Pivoting the mapping there means
**`s = 1` on a cheek at every gain**, so a cheek is an in-frame control: if the
cheek moves between `curv` and `curv-ctl`, something other than curvature is
driving the change. It also makes `g = 0` an exact algebraic identity
(`s == 1.0` for every kappa, checked in float32 for 8 values), which is what
makes `curv-ctl` byte-identical rather than merely close.

At `g = 1` the formula collapses to literally the brief's
`clamp(kappa / 10, 0.3, 2.0)`; `dev/curv_model.py` asserts that equality to
1e-6 over 10 values of kappa. The pivoted form is not a different model — it is
the same model written so the gain knob exists.

### 3.3 kappa → s → what you should see

Band `W = 0.35 · s`; "band deg" is `acos(1 − W)`, the angular width of the
terminator wrap; "peak R/G" is the red/green chromaticity ratio at `NoL = 0`,
i.e. the strongest tint the pixel can take (Jensen 2001 skin1).

| feature | r (mm) | kappa (/m) | s @ g=1 | band W | band (deg) | peak R/G | expected on screen |
|---|---|---|---|---|---|---|---|
| flat chest / back | 600 | 1.7 | **0.30** | 0.105 | 6.0 | 1.101 | terminator **tightens sharply**; the chest stops reading as waxy |
| forehead | 120 | 8.3 | **0.83** | 0.292 | 17.0 | 1.280 | slightly tighter than shipped; barely separable |
| **cheek (the pivot)** | 100 | 10.0 | **1.00** | 0.350 | 20.5 | 1.336 | **unchanged, by construction — the in-frame control** |
| jaw / chin | 50 | 20.0 | **2.00** | 0.700 | 44.4 | 1.672 | wider, redder wrap along the jawline |
| brow ridge | 30 | 33.3 | **2.00** | 0.700 | 44.4 | 1.672 | wider, redder |
| finger | 10 | 100 → 40 | **2.00** | 0.700 | 44.4 | 1.672 | saturated |
| nose wing | 8 | 125 → 40 | **2.00** | 0.700 | 44.4 | 1.672 | **the headline: a red-orange wrap around the nostril** |
| lip roll | 6 | 167 → 40 | **2.00** | 0.700 | 44.4 | 1.672 | lips warm and soften at the roll |
| ear helix rim | 3 | 333 → 40 | **2.00** | 0.700 | 44.4 | 1.672 | rim warms — note the ear also carries `earglow-cap6`, §10.3 |

At `g = 2` (`curv-hi`) the cheek is still `1.00`, the forehead drops to `0.67`
(W 0.233), the flat chest is already at the `0.30` floor, and everything from
the jaw up is already at the `2.00` ceiling. **So `curv-hi` differs from `curv`
only in the 8.3–20 /m band — foreheads, temples, upper cheeks.** That is a
narrow difference and it is stated here so it is not over-read on screen.

### 3.4 Why the amplitude scales too, and not only the width

Penner's pre-integration widens *and* deepens: a high-radius surface both wraps
light further past the terminator and transports more of it laterally, which is
what makes the red channel dominate. Scaling only `W` would widen a band of
fixed peak tint; scaling `w` as well makes the peak tint scale with the same
`s` — 1.10 → 1.34 → 1.67 in R/G across the range. The chromaticity excursion
table in `dev/curv_model.py` is the check that this stays inside Jensen's
ratios rather than inventing saturation.

### 3.5 The `c1` term is NOT scaled, and here is why

97 §3.2: `c1 = (1 + (ρ_f − 1)·α_f) · (1 + (ρ_r − 1)·α_r)` with
`α_f = (1 − NoL)^(5·r(n_f)) · NoV^(5·r(m_f))` and the retro lobe likewise.
Its parameters are two **exponents** and two **amplitudes**. There is no width
and no wrap: `α` is a power law over the whole hemisphere, not a band with an
edge. Scaling something in `c1` by `s` would mean *changing the retro-reflective
amplitude* `ρ_r` with curvature — which is a different physical claim from
Penner's (Penner drives the diffuse falloff, not the retro lobe), and one this
work has no evidence for. **173 `c1` sites in 77 modules are read and left
alone.** If a curvature-driven `ρ_r` is wanted it should be its own rung with
its own argument.

---

## 4. Gates — `./dev/build_curv.sh`

All numbers are the actual run output on the standing base
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`.

| # | gate | result |
|---|---|---|
| 0 | base provenance: MANIFEST present, 77 compute, 16 raygen, of which **12** `rgs_reference_main` and **4** `rgs_restirgi_*` | pass |
| 1 | offline model self-checks: `g=0 ⇒ s≡1`; `g=1 ⇒ clamp(kappa/10,0.3,2)`; luminance hold survives every `s` | **True / True / True** |
| 3 | round-trip neutrality: `spirv-dis → spirv-as` at each module's own version | **77 of 77 byte-identical** — this is what makes the control non-tautological |
| 5 | coverage, read from the patch reports, never from byte diffs | `curv`, `curv-hi`, `noguard`: **75 modules, 2 declined, 142 bleed sites, 144 instr/module, centre N reused 75, centre P refetched 0**. `vis`: **75 modules, 150 writes painted (30 refetched P / 120 reused), 0 skipped**. `ctl`: **77 modules emitted, 0 declined, 0 sites scaled** |
| 5 | one anchor/knob tuple across the family | matrix `cbv[reg0+12][69..72]`, depth `registers[1]+0`, normal `registers[1]+2` — **single-valued in all 75** |
| 5 | every `w` has exactly 3 consumers at every site | **142 of 142** |
| 6 | assemble: 93 modules per rung; **16 of 16 raygens `cmp`-identical to base**; **2 of 2 declined resolvers `cmp`-identical**; `spirv-val --target-env vulkan1.4` | clean on **4 × 93** modules |
| 6 | `curv`, `curv-hi`, `curv-vis`: exactly **75 of 77** compute modules differ | pass |
| 6 | `curv-ctl`: **0 of 93** modules differ from the base | pass |
| 6 | the rungs differ from each other and from the decoy: `curv↔hi`, `curv↔vis`, `hi↔vis`, `curv↔noguard` | **75 of 93 differ** in each pair |
| 7 | `dev/verify_curv.py` on the **shipped bytes** of `curv` and `curv-hi` | **ALL PASS** — 77 modules, 75 patched, 2 declined, **142 sites scaled** |
| 7 | non-vacuity: 10 decoys the verifier must reject | all 10 rejected, listed below |
| 8 | `curv-vis` is class-gated and cannot move a non-skin pixel | **150 of 150** writes gate on `(gbuf.y >> 5) == 1`, and every non-skin branch is **slice-identical** to the base module |

### 4.1 The rejection list (gate 7)

The verifier is only worth its output if it can fail. Each of these is run and
must exit non-zero:

```
  rejected: the unpatched base                  (1 of 1 bleed sites still unscaled)
  rejected: the gain-0 control
  rejected: the NO-SILHOUETTE-GUARD decoy       (built by patch_curv.py --no-guard)
  rejected: curv read as curv-hi                (gain is 1.0, expected 2)
  rejected: curv-hi read as curv
  rejected: a wrong kappa0                      (1/kappa0 is 0.1, expected 0.1667)
  rejected: a wrong silhouette threshold        (0.0025 != jump^2 = 0.0004)
  rejected: a wrong neighbour step              (taps are not (+2,0) and (0,+2))
  rejected: a wrong s clamp                     (clamp is [0.3, 2.0], expected [0.3, 3])
  rejected: curv read as unguarded
```

The verifier does **not** trust the patcher: it disassembles the parked `.spv`,
finds the bleed from its own two Jensen constants, walks
`w' → w → t → sat → 1−q → q → bq/s → NoL·(1/0.35)`, then walks `s` back through
the guard, the mapping, `kappa`, both `Dot`s, both `CompositeConstruct`s, and
out to the two texel fetches; asserts the two taps are `(+1,0)` and `(0,+1)`
**about a common centre** (by comparing the two coordinate constructs against
each other, so it never has to know what the centre is); and finally
*interprets* the six mapping instructions over an 11-point kappa sweep and
compares against `dev/curv_model.scale`.

---

## 5. Coverage

| | modules | sites |
|---|---|---|
| compute resolvers in the set | **77** | — |
| carry the terminator bleed | **77 of 77** | **150** |
| carry a `c1` / Disney-diffuse site | 77 of 77 | 173 (**untouched**, §3.5) |
| **curvature-scaled by this patch** | **75** | **142** |
| declined | **2** | **8** (5.3%) |

### 5.1 Every declined module, by hash

| hash | bleed sites left at 0.35 | reason |
|---|---|---|
| `ab0bc2fee876d489` | 2 | **Zero P-reconstruction chains.** 20 771 lines, 14 `OpImageFetch`, and not one depth→matrix→perspective-divide chain. There is no `|dP|` to measure and no matrix anchor to reuse, so kappa is not constructible without inventing a projection. Matches 99's independent 75-of-77 census |
| `99bb7c2698997b2a` | 6 | **The GI resolver.** Same null — zero P chains, 59 211 lines — and additionally 97 §1.5's finding that this module has no `V` at all. Its 6 bleed blocks stay at the shipped constant |

Both are declined **by name** in `patch_curv.KNOWN_DECLINE`, the patcher *dies*
rather than emitting anything for them, gate 5 asserts the decline set is
exactly those two (not a superset, not a subset), and gate 6 `cmp`-asserts
their bytes are the base's. A silently-skipped module cannot hide here.

### 5.2 Compute-only, asserted

All **12** `rgs_reference_main` and all **4** `rgs_restirgi_*` modules are
copied from the base and `cmp`-compared byte-for-byte in gate 6, for every one
of the four rungs. Patching a raygen would be a no-op anyway (97 §1.2: the
estimator divides the pdf back out), but "would be a no-op" is an argument and
`cmp` is a fact.

---

## 6. The rungs

| rung | what it is |
|---|---|
| **`curv`** | `g = 1`: literally `s = clamp(kappa/10, 0.3, 2.0)`. The feature |
| **`curv-hi`** | `g = 2`: same pivot at 10 /m, twice the contrast. Differs from `curv` **only** in 8–20 /m (foreheads, temples), §3.3 |
| **`curv-vis`** | The diagnostic. At all 150 radiance writes, on class-1 pixels only, the written texel becomes a ramp of `t = (s − 0.3)/(2.0 − 0.3)`: **blue = flat, green = mid, red = tight**, **white where the silhouette guard fired**, multiplied by the pixel's own clamped Rec.709 luminance (0.25–2.0) so it reads under any exposure without being confused with the shading. Non-skin is untouched and gate 8 proves it slice-by-slice |
| **`curv-ctl`** | `g = 0`. **93 of 93 modules byte-identical to the base.** The patcher detects nothing and emits nothing; the module is re-assembled from untouched disassembly, which gate 3 proves byte-neutral *first*, so this identity is not a tautology |

---

## 7. Settings contract — state this BEFORE the launch, not after

Per the A/B settings-sync rule: these are required, and a capture taken without
them does not test this work.

1. **`ser=class`** and **`shadowset=full-shadow`** — the standing base's own
   contract (`CURRENT.md`), unchanged by this work.
2. **Direct sun on a face.** 99 §10.8e established that the class-1 tint only
   reaches the screen in direct sun. This rung *is* the terminator; without a
   hard key light there is no terminator to widen. Ambient-lit interiors are
   void frames, not negative frames.
3. **Close-up.** §9.1: at 0.4 m the estimator floor is 3.4 /m against a cheek's
   10 /m; by 2 m it is 0.7 /m but the face is 100 px. Shoot a conversation-
   distance face, filling a decent part of frame.
4. **A non-skin control in frame** — a wall, a jacket, a car panel. Nothing in
   this patch touches non-skin, so anything that moves there falsifies the
   whole rung.
5. **Shoot `curv-vis` first.** It is the only rung a still frame can falsify
   (§8 row 1). If the ramp does not follow the geometry, every other row here
   is void.
6. Same camera, same time of day, same NPC for `curv` / `curv-hi` / `curv-ctl`.

---

## 8. Pre-registered interpretation — fill this in from the frames

| # | observation | reading |
|---|---|---|
| 1 | **`curv-vis`: does the ramp follow the geometry?** Nose wings, lip roll and ear rim **red**; cheeks and forehead **green/cyan**; chest and shoulders **blue** | **This is the gate.** If yes, the estimator works and rows 2–6 are live. **If the ramp is flat, uniformly noisy, or follows the *lighting* rather than the shape, kappa is not being measured and EVERY OTHER ROW IN THIS TABLE IS VOID** — including any "it looks nicer" verdict on `curv` |
| 1b | **`curv-vis`: white pixels** | White = the silhouette guard fired. Expect a **thin rim on the head's outline** and on the jaw against the neck. A *thick* white band, or white across flat cheek, means `J = 5 cm` is too tight for this shot distance — §9.2, and it makes rows 2–6 read as "half the face fell back to shipped" |
| 2 | `curv` vs `curv-ctl`: the **nose wings / nostril crease** warm and the wrap widens | The headline. This is the `s = 2.0` region and the largest available effect |
| 3 | `curv` vs `curv-ctl`: the **cheek is unchanged** | Expected by construction (`s = 1` at the pivot). If the cheek *does* move, something other than curvature is driving it — suspect the class gate or a second bleed site, and treat rows 2, 4, 5 as unexplained |
| 4 | `curv` vs `curv-ctl`: **chest / shoulders tighten**, less waxy | The `s = 0.3` floor. If the chest instead looks *harder* in a way that reads as a lighting error rather than a skin change, `S_MIN = 0.3` is too aggressive |
| 5 | `curv-hi` vs `curv`: the **forehead and temples** are the only region that should differ | §3.3. If `curv-hi` differs anywhere *else*, the mapping is not doing what §3 says |
| 6 | Non-skin (wall, jacket, car) is pixel-identical | Must hold. Anything else falsifies the class gate, and gate 8 says it cannot happen — so a violation means the gate is measuring the wrong thing |
| 7 | `curv-ctl` vs the base | Must be indistinguishable; they are the same 93 files. A visible difference means the selector is not loading what it says |
| — | **VOID ROW** | Any frame without direct sun on the face (§7.2) — a null there is a null about the light, not about curvature |
| — | **VOID ROW** | Any frame beyond ~5 m from the face (§9.1) — the estimator's noise floor is comparable to the signal and the guard starts firing on flat surfaces |
| — | **VOID ROW** | Any comparison where `ser` or `shadowset` differs between captures |

---

## 9. Cost, and the two numbers that bound it

### 9.1 Fetches and instructions

**4 extra texel fetches and 144 ALU instructions per pixel that reaches the
bleed's dominator, once per module invocation — never per light.** Measured on
the shipped bytes: the estimator lands inside conditional control flow in
**75 of 75** modules (median **14** selection constructs deep, min 3, max 18)
and inside a **loop body in 0 of 75**. So it is not hoisted to the function
entry and does not multiply by light count.

It is, however, **not class-gated**: the hoist has to dominate the bleed sites,
which sit inside the class-1 branch, so the estimator runs for every pixel that
reaches that shading region — a superset of skin. Sinking it into the class
branch is possible (the same dominance machinery would do it) and is the first
optimisation to make if this ever shows up in a frame time. It was not done
here because a single hoisted block is far easier to verify, and verifying it
was the point.

The two depth taps and two normal taps are `Lod 0` point fetches of targets the
module already has bound and already reads. No new descriptor, no new binding,
no sampler.

### 9.2 The estimator's noise floor — the real open risk

The normal G-buffer is `A2B10G10R10_UNORM_PACK32`: **10 bits per channel**. One
LSB of normal difference over one texel of surface is a kappa floor:

| distance | footprint (mm/texel) | kappa floor, 1 LSB | kappa floor, √3 LSB | cheek kappa |
|---|---|---|---|---|
| 0.4 m | 0.578 | 3.4 | 5.9 | 10.0 |
| 0.7 m | 1.012 | 1.9 | 3.3 | 10.0 |
| 1.0 m | 1.446 | 1.4 | 2.3 | 10.0 |
| 2.0 m | 2.892 | 0.7 | 1.2 | 10.0 |
| 5.0 m | 7.230 | 0.3 | 0.5 | 10.0 |

At 0.4 m the worst-case floor (5.9 /m) is **59% of a cheek's kappa** — the
mapping will be visibly noisy on flat skin at very close range, biased *upward*
(toward wider, redder). At 1 m and beyond it is under a quarter of the signal.
At 60° grazing the footprint doubles and the floor halves, so the noise is worst
exactly where the surface faces the camera. **A `--step 2` build halves the
floor** at the cost of blurring features under ~3 texels; that is the first knob
to turn if `curv-vis` comes back speckled on flat cheek.

The guard's 5 cm threshold sits **86×** above the on-surface footprint at 0.4 m,
**35×** at 1 m and **6.9×** at 5 m; it crosses the footprint at **35 m**, beyond
which every skin pixel falls back to `s = 1`. That is graceful degradation and
it is deliberate: skin at 35 m is a handful of 720p texels and carries no
terminator. An out-of-bounds tap at the screen edge reads depth 0 (reverse-Z far
plane), which puts P past the horizon and fires the guard too.

---

## 10. What is NOT done

1. **Not launched.** No frame has been looked at. §8 is pre-registered, empty.
2. **Nothing committed.** No `git commit`, no `make install`, no edit to
   `init.lua`, `swap_layer.c`, the `Makefile`, `CURRENT.md`, `GOTCHAS.md`, or
   any existing `dev/` script or handoff doc. §12 gives the `init.lua` lines to
   paste; it does not paste them.
3. **The GI side is untouched.** `99bb7c2698997b2a` keeps 6 bleed blocks at
   0.35, and the ReSTIR-GI raygens are out of scope for a compute-only rung
   (97 §1.5: no `V` there, and no P chain here). If the GI bleed should follow
   curvature it needs its own instrument and its own argument.
4. **`c1` is read and left alone**, 173 sites — §3.5.
5. **The specular is untouched.** Penner's paper also drives a curvature-
   dependent specular *occlusion*; that is a separate change and is not here.
6. **No hair (class 4) or eye (class 8) coupling.** The bleed is class-1 only,
   as shipped.
7. **`s` does not feed `earglow`.** The ear rim is the one place two curvature-
   adjacent features now overlap (`earglow-cap6`'s thickness floor and
   `s = 2.0` on the helix); they are independent multipliers on different terms
   and neither was retuned for the other. Watch the ear in §8 row 2 and treat a
   blown-out helix as an interaction, not as a curvature failure.
8. **`--step` is fixed at 1 in the parked rungs.** The 2-texel variant is
   supported by every script and gate but is not built or parked.

---

## 11. Files

New, and nothing else was touched:

| file | what |
|---|---|
| `dev/curv_model.py` | The float32 offline model: the mapping, the band, 78's hold residual, the chromaticity excursion, the screen-space noise floor and the guard's margin. Self-checking — exits non-zero if `g=0` is not an identity, if `g=1` is not the brief's formula, or if the luminance hold drifts |
| `dev/patch_curv.py` | The patcher. `--tier bleed \| vis`, `--gain`, `--kappa0`, `--kmin/--kmax`, `--smin/--smax`, `--jump`, `--step`, `--no-guard` (decoy only). Structural anchors throughout; no SSA id is hard-coded anywhere |
| `dev/verify_curv.py` | The independent read-back. Disassembles the shipped `.spv`, finds everything from the bleed's own constants, and interprets the mapping numerically against `curv_model` |
| `dev/build_curv.sh` | Provenance → model → round-trip → patch ×5 → coverage → assemble → verify + 10 rejections → `curv-vis` gate → MANIFESTs → `--install`. `--install` parks under **new names only** and refuses to overwrite a directory it did not create (it drops a `.built-by-build_curv` marker) |
| `handoff/109-CURVATURE-SKIN.md` | This document |

Parked: `~/.local/lib/callisto/skin.set/{curv, curv-hi, curv-vis, curv-ctl}`,
93 modules each, each with a `MANIFEST.txt` naming the base and the knobs.

---

## 12. `init.lua` entries to add

**This document does not edit `init.lua`.** Paste these four rows into
`SKIN_LEVELS` (the table opening at line 120), after the `carglint-ctl` row and
before the handoff/99 `hunt-wpos` block:

```lua
    -- handoff/109. Penner 2011 pre-integrated skin, built from the resolvers'
    -- own G-buffers: kappa = |dN|/|dP| over a +1-texel neighbour in x and y,
    -- mapped to s = clamp(1 + g*(clamp(kappa,0.5,40)/10 - 1), 0.3, 2.0), which
    -- scales BOTH the terminator band width and its amplitude at 142 of 150
    -- bleed sites in 75 of 77 compute modules. The cheek (kappa = 10 /m) is the
    -- pivot and does not move at any gain -- it is the in-frame control.
    -- 78's luminance hold rides the same value, so neutrality is exact (9e-8).
    -- Silhouettes (|dP| > 5 cm across a texel) fall back to the shipped 0.35.
    -- SHOOT -vis FIRST: it is the only rung a still can falsify. Nose wings,
    -- lips and ear rims must be RED, cheeks GREEN, chest BLUE, with white only
    -- on the head's outline. A flat or lighting-shaped ramp voids the family.
    -- READ 109 sec 0 AND ITS PRE-REGISTERED TABLE (sec 8) BEFORE A FRAME.
    -- Needs DIRECT SUN on a close-up face (99 sec 10.8e) and a non-skin control.
    { id = "curv-vis",  label = "PROBE: curvature kappa ramp on skin, blue=flat -> red=tight (109; SHOOT THIS FIRST -- flat ramp = family void)" },
    { id = "curv",      label = "  CURVATURE-DRIVEN skin scattering, g = 1 (nose/lips/ears wrap wider + redder, chest tightens, cheek unchanged)" },
    { id = "curv-hi",   label = "  curvature skin at g = 2 -- twice the contrast; differs from curv ONLY on foreheads/temples (109 sec 3.3)" },
    { id = "curv-ctl",  label = "  curvature CONTROL (g = 0) -- 93/93 BYTE-identical to the default; must be indistinguishable" },
```

Selection contract: `skinspec=curv | curv-hi | curv-vis | curv-ctl`, with
`ser=class` and `shadowset=full-shadow`.

---

## 13. SHOT 2026-09-03 and KEPT — `curv` (g = 1) is the shipped default

**The verdict, verbatim:**

> "tested the curvature based bleed effect and it looks incredible"

> "I'm just preferring using the default curv option"

`curv` (g = 1) is kept and promoted to the shipped default. `curv-hi` is
explicitly not preferred.

### 13.1 The read-out is LIVE-ONLY

**No frame was captured. There is no image file, no `a-b-testing/` entry, no
pixel measurement, and nothing below is derived from one.** The verdict is a
live on-screen preference reported in words. That is a real result — §0's last
row ("it looks better on a face") is now answered — but it is the *weakest*
kind of evidence this project accepts, and §8 was written precisely so a keep
could be stronger than this. It is recorded as what it is. **Nothing in this
section may be cited as a measurement.**

### 13.2 Which pre-registered rows fired, and which could not be read

| §8 row | status |
|---|---|
| **1 — `curv-vis`: does the kappa ramp follow the geometry?** | **NOT READ. `curv-vis` was never shot.** This was the designated falsifier: the one rung a still frame can void the family with. The keep therefore rests on the *look*, not on a confirmation that kappa is being measured correctly |
| 1b — white silhouette-guard pixels | **NOT READ** (needs `curv-vis`) |
| **2 — nose wings / nostril crease warm and widen** | **CONSISTENT, NOT ISOLATED.** "Looks incredible" is a whole-face verdict. No per-feature observation was reported, so row 2 is neither confirmed nor denied on its own terms |
| 3 — cheek unchanged | **NOT READ** — not reported either way |
| 4 — chest / shoulders tighten | **NOT READ** |
| **5 — `curv-hi` differs only on foreheads/temples** | **NOT READ as stated.** `curv-hi` was compared only as a preference ("I'm just preferring using the default curv option"), which says `curv-hi` was *seen and not preferred*; it does not say *where* the two differed. §3.3 predicted a narrow difference and that prediction is untested |
| 6 — non-skin pixel-identical | **NOT READ**, and it does not need to be: gate 8 proves it in the bytes (150 of 150 writes class-gated, non-skin branch slice-identical to base) |
| 7 — `curv-ctl` indistinguishable from base | **NOT READ.** `cmp` says 0 of 93 files differ, so a visible difference would be a selector bug, not a shader one |

**Net: zero of the seven visual rows were read as written.** One (row 2) is
consistent with the verdict; one (row 6) is settled statically instead; the
rest are open. The honest summary is that the *feature* was judged and kept,
while the *mechanism* was not verified on screen.

### 13.3 What was NOT judged, and stays parked

- **`curv-hi`** — seen, not preferred, not analysed. Stays parked as the
  untried higher-contrast rung, exactly as `earglow-cap4` stayed parked.
- **`curv-vis`** — never shot. It remains the instrument to reach for the
  moment anything about kappa is doubted (speckle on flat cheek, an ear that
  blows out, a distance-dependent shift). **Shoot it before changing a knob.**
- **`curv-ctl`** — never shot. It is 93/93 `cmp`-identical to the pre-curv
  default, so it is only useful as a selector self-test.
- **`--step 2`** — still not built.

### 13.4 The shipping stack

```
  name         gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv
  content sha  024998da26d84333          (the previous default was 3bb0aee03a1bfda8)
  built by     ./dev/build_curv.sh --stack --install
```

It is **not a rebuild**. It is byte-for-byte the `curv` rung, re-parked under
the long name the selector's stack convention uses, and gate 9 `cmp`-asserts
exactly that:

```
  16 of 16 raygens (12 rgs_reference_main + 4 rgs_restirgi_*) cmp-verbatim from the base
  77 of 77 compute modules cmp-identical to the parked curv rung
  93 of 93 modules cmp-identical to curv -- the stack IS curv
  ALL PASS  (verify_curv.py on the stack's own bytes: 75 patched, 142 sites scaled)
  content sha 024998da26d84333   (base was 3bb0aee03a1bfda8)
```

The content sha is computed the way every other stack computes it —
`cat *.spv | sha256sum | cut -c1-16` over the parked directory — and the same
command reproduces `3bb0aee03a1bfda8` on the old default, so the two numbers
are comparable. `--stack` lives in `dev/build_curv.sh`; no new script was
added. The stack's `MANIFEST.txt` carries the base's own `# src:` provenance
line with `compute=77(...+curv)`, the knob line, the verbatim verdict, and the
LIVE-ONLY caveat.

### 13.5 What the keep does NOT settle

1. **The §9.2 noise floor is untested.** At 0.4 m the worst-case kappa floor is
   5.9 /m against a cheek's 10 /m. The verdict came from an unrecorded distance
   with no `curv-vis` frame, so *nothing* is known about speckle on flat skin at
   very close range. If faces ever look noisy in close conversation framing,
   this is the first suspect and `--step 2` is the first fix.
2. **The ear-rim interaction with `earglow-cap6` is untested.** §10.7: the helix
   now carries both a 6 mm thickness floor and `s = 2.0`. They are independent
   multipliers on different terms, neither retuned for the other, and the verdict
   frame is not known to have contained an ear — let alone a backlit child's ear,
   which is the case `101` §18 built the cap for. **A blown-out helix on a child
   is an open risk this keep does not close.**
3. **Cost is unmeasured.** 4 extra Lod-0 taps and 144 ALU per pixel reaching the
   bleed's dominator, in 75 modules; not class-gated (§9.1). No frame time was
   taken before or after. "It looks incredible" says nothing about ms.
4. **The mapping constants are unvalidated on screen.** `kappa0 = 10 /m`,
   `[0.5, 40]`, `[0.3, 2.0]`, `J = 5 cm` are all reasoned (§3, §9.2), none are
   measured. A `curv-vis` frame would validate the first three; the fourth needs
   a silhouette-heavy shot.
5. **The `c1` term and the specular are still curvature-blind** (§3.5, §10.5).
   Keeping this rung does not endorse leaving them so — it simply did not test
   them.

### 13.6 `init.lua` — the SKIN_LEVELS line for the new default

**This document does not edit `init.lua`.** The stack row (put it next to the
other full-stack rows, near the current default at line ~345), plus the
default-`skinspec` change at line ~92:

```lua
    -- handoff/109. The default PLUS curvature-driven skin scattering at g = 1:
    -- kappa = |dN|/|dP| from 4 extra G-buffer taps drives the terminator band
    -- width AND its red amplitude per pixel (nose/lips/ears wider + redder,
    -- chest tighter, cheek the unmoved pivot). 78's luminance hold rides the
    -- same value, so the change is chromaticity + width only. 93/93 bytes are
    -- skin.set/curv; the 16 raygens are the old default's. content sha
    -- 024998da26d84333. SHOT 2026-09-03, LIVE read-out only, no capture:
    -- "tested the curvature based bleed effect and it looks incredible".
    { id = "gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv", label = "  + CURVATURE-DRIVEN skin scattering (109)  <-- DEFAULT" },
```

and the default assignment becomes

```lua
               skinspec = "gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv" }
```

(the previous default row keeps its entry, with its `<-- DEFAULT` marker moved
off it.)

### 13.7 `CURRENT.md` — the paragraph to paste

**This document does not edit `CURRENT.md`.** Suggested replacement for its
standing-selection paragraph:

> **2026-09-03 — THE STANDING SELECTION AND SHIPPED DEFAULT `skinspec` IS
> `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv`,
> content sha `024998da26d84333`** — the previous default (`3bb0aee03a1bfda8`)
> plus `109`'s **curvature-driven skin scattering** at g = 1. USER VERDICT,
> verbatim: *"tested the curvature based bleed effect and it looks incredible"*
> and *"I'm just preferring using the default curv option"*.
>
> - **Why.** 97 §3.4's terminator bleed ran one hard-coded diffusion band
>   (`0.35`) on every skin pixel — the same width on a nose wing and on a
>   forehead — because curvature was not computable at the splice site. 99
>   proved it is: four extra Lod-0 taps on the depth and normal G-buffers give
>   `kappa = |dN|/|dP|` in 1/m, and `s = clamp(kappa/10, 0.3, 2.0)` scales both
>   the band width and its red amplitude. A cheek (`kappa = 10 /m`) is the
>   pivot and does not move; nose, lips, jaw and ear rims widen to `0.70`; a
>   flat chest tightens to `0.105`. 78's luminance hold rides the same value,
>   so the change is chromaticity and width only — measured residual 9e-8.
> - **Cost.** 4 extra texel fetches + 144 ALU per pixel reaching the bleed's
>   dominator, in 75 of 77 compute modules. Not class-gated. **Unmeasured in
>   ms.**
> - **Static gates.** 142 of 150 bleed sites in 75 of 77 modules; 16 of 16
>   raygens and 2 of 2 declined resolvers `cmp`-verbatim; `spirv-val
>   --target-env vulkan1.4` clean on 93; `verify_curv.py` passes on the shipped
>   bytes and rejects 10 decoys including a no-silhouette-guard build.
> - **The caveat.** **LIVE read-out only — no frame was captured**, and
>   `curv-vis`, the rung designed to falsify the estimator, was never shot.
>   Zero of `109` §8's seven visual rows were read as written. `curv-hi` and
>   `curv-vis` stay parked. Open: the close-range noise floor (`109` §9.2), the
>   ear-rim interaction with `earglow-cap6` (`109` §13.5.2), and frame cost.
