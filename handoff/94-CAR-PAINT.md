# 94 — Car paint (clearcoat + metallic flake glints): MILESTONE 1, static only

Written 2026-09-01. **Nothing built, nothing installed, nothing committed, no
launch.** This is the gate report the brief stopped at: (1) does vehicle paint
carry a material class or subtype, (2) the exact splice site in the reference
raygen with ids, (3) the design, sized and costed, with the control plan.

---

## 0. Verdict first

| question | answer | confidence |
|---|---|---|
| Is vehicle paint a distinct material **class**? | **No. The class field cannot express it.** | **high** — whole-dump census, §1 |
| Is it a distinct **subtype**? | **Unknown, and untested — nobody has ever put a car in a probe frame.** Reachable in compute, unreachable at the raygen site. | **high** on reachability, **unknown** on the answer |
| Is it "Standard with metallic > 0"? | **That is the only hypothesis the reachable data supports**, and it is a hypothesis, not a finding | — |
| Is there a clearcoat / second specular lobe anywhere in this renderer? | **No.** One isotropic GGX lobe, one Schlick SG Fresnel, per site, everywhere | **high** |
| Is there a usable splice site in the reference raygen? | **Yes — 6 blocks × 10 of 12 permutations, 60/60 resolved**, §3 | **high** — measured, §3.4 |
| Does that site shade the **primary** hit? | **NO — and this is the finding that reshapes the feature.** §2 | **high** |

**One-line summary.** The class gate does not exist and cannot exist — the
3-bit field has five populated values in 3290 modules and none of them is a
paint family — so the gate must be `metallic × roughness`, exactly as the brief
anticipated; and the probe that settles it is one launch of a new
`hunt-paint` rung (§5) shot at a parked car. The splice site asked for is
found and pinned to ids (§3), but it evaluates **NEE at bounces ≥ 1**, not the
primary surface, so a coat spliced there changes light *inside* reflections and
not the paint the user is looking at. The primary hit's specular is elsewhere:
its direct half in the 457 compute BRDF sites `81` already patches, its
environment-reflection half in this raygen's BSDF-weight block (§2.3). Read §2
before costing anything.

---

## 1. The class/subtype question, answered

### 1.1 The whole-dump census — five class values, none of them paint

`python3 dev/census_subenum.py ~/callisto_dump`, reproduced today over 3290
modules (`40` §2's numbers hold exactly):

```
one word feeds both >>5 and &31 : 81  {GLCompute 59, Fragment 12, RayGeneration 10}
class values tested, whole dump : {0: 69, 1: 124, 3: 99, 4: 114, 5: 58}  modules
sub values tested               : {12:8, 13:8, 14:8, 15:8, 17:13, 21:64, 25:62, 26:1, 30:8, 31:10}
sub by stage                    : Fragment [12,13,14,15,17,21,25,26,30,31]   GLCompute [17,21,25]
class 2, 6, 7                   : tested by ZERO modules, anywhere
```

Per-module breakdown (new scan, same method, kept in the scratch of this
session — reproduce by adding a per-module print to `census_subenum.py`):

```
 46 GLCompute cls=[0,1,3,4,5]      12 RayGen cls=[1,4]       8 Fragment cls=[0,1,3,4,5]
 18 GLCompute cls=[1,3,4]          12 RayGen cls=[1,3,4]     3 Fragment cls=[3,5]
  9 GLCompute cls=[0,1,3,4]         6 RayGen cls=[0,1]       1 Fragment cls=[3,4,5]
  8 GLCompute cls=[1,4]             4 RayGen cls=[1]
  1 GLCompute cls=[1,3]             1 RayGen cls=[3]        (94e675a5.rgs_shadow_main)
```

**Five values is the whole vocabulary.** There is no sixth thing the field
could be hiding — 2, 6 and 7 are dead in every stage.

### 1.2 What the five values are

| class | identity | evidence |
|---|---|---|
| **0** | default / "Standard" | no palette entry in `HUNT_PALETTE`, so it renders vanilla under the class paint — and in `a-b-testing/L2-probe-cls/S1.png` **cloth, sand, buildings, road and the distant vehicles are all unpainted** |
| **1** | **skin** | proven, `27`/`42`; red in the same capture |
| **3** | **a normal-encoding flag, not a shading family** | §1.3 |
| **4** | **hair** | proven, `54`/`57`; yellow in the same capture |
| **5** | **vegetation** | **new here** — every bush and tree in `L2-probe-cls/S1.png` is magenta, and magenta is `HUNT_PALETTE[5]`. Nothing else in that frame is |

### 1.3 Class 3 is a normal-precision flag — read this before hoping it is paint

In every module that branches on it, class 3 does exactly one thing: it decodes
the G-buffer normal from a **10-bit octahedral** pair instead of the ordinary
8-bit `xyz-0.5` form. `05511714f20081b4.dxil` (a class-aware compute
evaluator), block `%2600`:

```
%418 = %416 * 255 ; %420 = uint(%418)      ; gbuf1.z  -> 8 bits
%424 = uint(%417 * 3)                       ; 2 more bits from another target
%427 = %420 << 2 ; %428 = %427 | %424       ; 10 bits
%433 = %428 * 0.00195503421                 ; = 2/1023
... octahedral decode -> %281/%284/%287
```

`94e675a5f27e1c3b.rgs_shadow_main` — the one raygen that tests **only** class 3
— carries the identical block and nothing else (`%273 = %250 == 3`, one use).

So class 3 says *"this pixel's normal is stored at high precision"*. That is a
property smooth mirror-like surfaces get, and car paint is plausibly among
them — **but so are glass, chrome, polished floors and water**, and no BRDF
anywhere branches on it. It is a decode switch, not a material identity. It is
still worth reading off the probe frame (§5): if a car body comes back **blue**
under `probe-cls`, that is a usable if imprecise gate, and it costs nothing to
look.

### 1.4 The subtype: reachable in compute, absent at the raygen, never tested on a car

- `57` proved the 5-bit sub-enum **is** readable from the compute G-buffer
  fetch and that `& 31` survives the optimiser. G-U4 is open.
- `57` §5 lists the limits of the only frame that has ever been shot with it,
  and the last line is literally: *"One scene, four characters, daylight
  exterior. No cloth-heavy interior, **no car paint, no road**."* The question
  this brief asks has never been put to the instrument that could answer it.
- `80` §2.1 established that **no shader tests any subtype under class 0**. So
  even if car paint has its own subtype value, nothing in the renderer treats
  it differently — which is consistent with the absence of a clearcoat lobe and
  is why this feature has to be *added*, not *unlocked*.
- **At the reference raygen splice site the subtype is not merely unread, it is
  not present.** §2.2: the payload is four words and carries no material byte
  at all.

### 1.5 There is no clearcoat anywhere

Searched: no second `OpFDiv %float %float_0_25 …` Vis chain paired with a
second `D` at any site (the MS-GGX detector would have found it — it finds
exactly 6 SG-Fresnel sites per raygen and 3 alphas, i.e. three lighting groups
× two arms, `28` §5); no `EMM_*` clearcoat string in the exe (85 `EMM_` names
dumped, §1.6); no second Fresnel constant pair. **The renderer has one
isotropic GGX lobe per site.** Whatever car paint looks like today, it is one
lobe with a roughness map.

### 1.6 What the exe does and does not carry

`strings` over `Cyberpunk2077.exe` (125 022 strings): the debug-view enum
`EMM_Surface{MaterialID,ObjectID,BaseColor,Albedo,Specularity,Metalness,
Roughness,Emissive,Translucency,NormalsWorldSpace,NormalsViewSpace,
HairDirection,HairID,LightBlockerIntensity}` is there — which names the
G-buffer channels and confirms `MaterialID` is a debuggable field — but **no
material-class enum, no `clearcoat`, no `CarPaint`, no `EMM_Surface*Coat`**.
The class↔material mapping is not in the exe's reflection data; it is in the
`.archive` material definitions, which this repo has no reader for. GOTCHAS 8
("ask whether the engine already exposes it") is discharged: it does not.

**Conclusion for (1).** The gate does not exist as a class. State that plainly.
It may exist as a subtype and that is one launch away. The gate the feature
should be *designed* against is metallic × roughness (§4.1), because that gate
works at every site including the ones where no material byte exists at all.

---

## 2. Where the specular actually is — the architectural finding

This is the part that changes the shape of the feature, so it leads the
build section rather than hiding in a caveat.

### 2.1 The reference raygen does NOT shade the primary hit's direct light

`d622fb9e1dcb8cd0.rgs_reference_main` (one of the two confirmed-live
permutations, `28` §6). The path loop's header phis at `%12277` carry the
**current** surface, seeded from the primary G-buffer:

```
%683 = OpPhi %uint  %439 %12276  %uint_0 %12786   ; material CLASS  (primary only!)
%684/%686/%688 = OpPhi  %518..%520 / %685..%689   ; diffuse albedo  = base*(1-metallic)
%690/%692/%694 = OpPhi  %528..%530 / %691..%695   ; F0 = 0.04 + metallic*(base-0.04)
%696           = OpPhi  %513 / %697               ; roughness
%698/%700/%702 = OpPhi  %217..%219 / %699..%703   ; shading normal N
```

Those phis are consumed **only** in lines 1847–2280 — lobe selection, BSDF
importance sampling, russian roulette — and then the ray is traced
(`OpTraceRayKHR` at :2282). Everything after that, including **all six GGX
evaluators**, reads the *payload* surface (`%699/%701/%703` for N,
`%691/%693/%695` for F0, `%697` for roughness) unpacked at block `%12288`.

So iteration *i* samples a direction at surface *i*, traces, lands on surface
*i+1*, and does next-event estimation **there**. The primary surface never gets
an `F·D·Vis` product in this shader. Its direct lighting is RTXDI/ReSTIR-DI in
the compute tile evaluators — which is exactly why every skin, cloth and sheen
result in this repo lives in those 77 modules.

**Consequence.** A clearcoat spliced at the six blocks changes the direct
lighting of surfaces *seen in a reflection*, and the second-bounce lighting of
the paint itself. It does **not** put a clearcoat highlight on the car.

### 2.2 The payload carries no material byte

`%100` is `OpTypeStruct { uint, uint, float, float }`:

```
word0 : baseColor.rgb in bytes 0..2 (x 1/255), METALLIC in byte 3
word1 : octahedral normal in 12+12 bits, ROUGHNESS in byte 3
word2 : a scalar (x 0.1, clamped 0..1)
word3 : t   (10000.0 = miss)
```

No class, no subtype, no object id, no UV, no barycentrics. `%683` is phi'd to
`0` on every bounce past the first. **Any class-based gate is structurally
impossible at this site** — which, for once, makes the "the class gate does not
exist" answer moot rather than fatal: metallic and roughness are both right
there, per-bounce, exact.

### 2.3 The three sites, ranked for this feature

| | site | what it owns | class in scope? | metallic in scope? |
|---|---|---|---|---|
| **A** | the 6 GGX blocks in `rgs_reference_main` (§3) | NEE at bounces ≥ 1 | no | **yes** (`%1314`) |
| **B** | the primary BSDF weight, same raygen, `%12282`: `%1189/%1190/%1191 = F0 + (1-F0)(1-VoH)^5` over the phi F0 `%690/%692/%694` | **the environment/sky reflection in the paint** — the single biggest visual component of car paint | **yes** (`%683`, primary class) | yes, via the F0 phi |
| **C** | the 457 direct compute BRDF sites of `81` | **the sun / neon highlight on the paint**, i.e. where glints are visible | yes | yes (`%239`-analogue, the same byte the skin gate reads) |

**Recommendation, stated now so the build is not mis-scoped:** the feature the
user will see is **C for the glints and the coat highlight, B for the coat's
reflection weight**, with **A** as the physically-consistent completion. The
brief asked for A; A is delivered in §3 with ids, and the honest note is that A
alone will read as a null on a parked car.

---

## 3. Site A — the splice, with ids

### 3.1 The anchor (reused verbatim from `28`)

`dev/patch_ms_ggx.py`'s `find_ggx_blocks` + `_read_vis` already locate exactly
this. The anchor is the Schlick spherical-gaussian Fresnel constant pair
`5.55472994` / `-6.98316002`, which is mode-independent (GOTCHAS 4):

```
%p    = Exp2( (-6.98316002 - 5.55472994*VoH) * VoH )
%om   = 1 - %p
%F_c  = %om*F0_c + %p                       c = r,g,b
%visd = Vis * D
%spec_c = %F_c * %visd                      <- the three ids to rewrite
Vis   = 0.25 / ((NoV + NoL)*(1 - alpha/2) + alpha)
D     = alpha^2 / (pi * (NoH^2*(alpha^2-1) + 1)^2)
```

### 3.2 Everything the brief asked for is in scope, measured

`d622fb9e1dcb8cd0.rgs_reference_main` — the six blocks, extracted from the
disassembly by walking the D and Vis chains (script in this session's
scratchpad; it is ~40 lines and belongs in `dev/patch_car_paint.py`):

| line | arm | alpha | Vis·D | NoV | NoL | VoH | spec triple |
|---|---|---|---|---|---|---|---|
| 8603 | punctual | `%5655` | `%6817` | `%6782` | `%6767` | `%6790` | `%6818 %6819 %6820` |
| 8861 | area | `%5655` | `%9998` | `%9963` | `%9948` | `%9971` | `%7576 %7578 %7580` |
| 9527 | punctual | `%5721` | `%6980` | `%6945` | `%6930` | `%6953` | `%6981 %6982 %6983` |
| 9785 | area | `%5721` | `%10282` | `%10247` | `%10232` | `%10255` | `%8560 %8562 %8564` |
| 13611 | punctual | `%5344` | `%5517` | `%5479` | `%5464` | `%5487` | `%5518 %5519 %5520` |
| 13869 | area | `%5344` | `%8730` | `%8695` | `%8680` | `%8703` | `%5761 %5763 %5765` |

Module-level, shared by all six (defined in `%12288`, the payload unpack, which
dominates every block by the same argument that `%699` does — every block
already uses `%699`):

| quantity | id | how it is obtained |
|---|---|---|
| **N** (shading normal) | `%699 %701 %703` | payload word1 octahedral decode |
| **V** (view direction) | `%3033 %3034 %3035` | `= -D`, `%3033 = OpFSub %float_n0 %733` |
| **D** (ray direction) | `%733 %735 %737` | `normalize(P - P_prev)` |
| **H** (half vector) | per block, e.g. `%6775 %6776 %6777` | `normalize(L - D)`; recovered as the second operand of the `OpDot` feeding NoH |
| **roughness** | `%697` | `NMin(NMax(payload_r, 0.04), 1)` — *authored*, before `ptreg` regularisation |
| **alpha** | `%5655 / %5721 / %5344` | per lighting group, **includes `ptreg`'s regularisation** — do not gate on this |
| **metallic** | `%1314` | `NClamp(byte3(word0)/255, 0, 1)` |
| **F0** | `%691 %693 %695` | `0.04 + metallic*(baseColor - 0.04)` |
| **diffuse albedo** | `%685 %687 %689` (used at `%12541` as `(1-metallic)*base`) | |
| **world position** | `%727 %729 %731` **+ `cbv[104][56].xyz`** | §3.3 |

### 3.3 World position — and it is camera-relative, which matters

`%727/%729/%731` is the hit position and is the origin operand of all three
NEE shadow traces (`%4149`, `%4550`, `%5101`, all
`OpCompositeConstruct %v3float %727 %729 %731`). **It is camera-relative**: the
primary reconstruction normalises it and uses the result as the view ray
(`%361..%363 = normalize(%354..%356)`), which is only valid with the camera at
the origin of that space. A glint hash on it would translate with the camera
every frame — glints crawling across parked paint at walking speed.

**The fix is already in the shader.** `cbv[104][56].xyz` is added to the hit
position at `%1419/%1420/%1421` and the result is stored into a 32-byte SSBO
record at offset 0 — the ReSTIR-GI reservoir, which is reused across frames and
therefore *must* be frame-stable world space:

```
%1414 = OpAccessChain %_ptr_Uniform_v4float %104 %uint_0 %uint_56
%1419 = OpFAdd %float %1416 %727                        ; + %1420, %1421
%1868 = OpRawAccessChainNV ... %uint_32 %1861 %uint_0
        OpStore %1868 (%1419,%1420,%1421) Aligned 16    ; reservoir sample position
```

Corroborated at `%3797 = %1356 - %3160` (`-(P + cb56)`), where the result is
added to a light-struct position read from a storage buffer.

So **`P_world = (%727,%729,%731) + cbv[104][56].xyz`**, 1 access chain + 1 load
+ 3 extracts + 3 adds, once per module invocation. All 12 permutations use
`cbv[104][56]` (6–10 uses each), so the anchor is universal.

> **PROVEN ON SCREEN 2026-09-02 — see `98` §15 and §7 below.** The paragraph
> below is left as it was written, before the test.
>
> This is a **contract about a space** (GOTCHAS 5) and it is *inferred from two
> consumers*, not proven. The build must assert that the same CB member is the
> one added to the reservoir store, and the launch verifier is behavioural:
> under `hunt-glintcell` (§6) the cells must stay welded to the paint while the
> camera translates. If they crawl, the offset is wrong and the feature stops
> there.

### 3.4 Coverage — 10 of 12 permutations, 60/60 blocks

| permutation | blocks | VoH/NoH/NoV/NoL/N/H resolved | metallic recovered from the F0 chain |
|---|---|---|---|
| `1271d381 21a92f1a 25b54fc4 3d871a31 4103c886 4270b745 852b31a8 996a3b16 d002cc05 d622fb9e` | 6 each | **6/6 each, 60/60 total** | **18/18 each** (3 channels × 6 blocks), one id per module |
| `40c6faab52a13874`, `ab7f1822eeb0331b` | **0** | — | — |

The two misses are `28`'s known **scalar-specular** permutations (`p·Vis·D`, no
`1-p` lerp, no F0 in the lobe). They must be **declined by name and reported**,
never silently skipped, and the ladder's module count must therefore be 10, not
12 — `GOTCHAS`: *a module count that differs from the ladder's is a finding.*

**Metallic is recoverable site-locally**, which is the robustness property that
makes the gate cheap and unguessable: from each block's own F0 id, walk two
instructions back —

```
F0_c   = OpFAdd (OpFMul %metallic (OpFAdd %base_c -0.04)) +0.04
```

— and the metallic operand is the one whose sibling is `base_c - 0.04`. This
resolves **18/18 in all ten patchable permutations and yields a single id per
module**. No positional guess (GOTCHAS 10), no separate detector.

---

## 4. The design

### 4.1 The gate

```
coat_gate = (metallic >= m_min) && (rough <= r_max)
            [ && class != 1 && class != 4   -- only where a class exists ]
m_min = 0.50      rough = %697 (authored, pre-ptreg)      r_max = 0.35
```

One boolean, computed **once per module invocation** from two module-level
scalars. Three properties earn it:

- **It is available at every site**, including the payload site where no class
  exists (§2.2). A class gate could not be built here at all.
- **It excludes skin, hair and vegetation for free** — all three are
  non-metallic; skin's own gate in this very shader is `metallic < 0.1`
  (`%447 = %428 < 0.1`), so `m >= 0.5` cannot collide with it.
- **`rough <= r_max` is what separates paint from rough metal.** Without it the
  term lands on every rusted prop, girder and pipe in Night City. This is
  `80`'s proxy-gate lesson applied before the fact rather than after.

It **will** also fire on chrome, polished metal signage, and mirror-finish
cyberware. That is a known false-positive set, it is bounded (a coat on chrome
is a mild Fresnel-weighted whitening; glints on chrome are wrong but subtle),
and it is what the probe frame has to contain so the A/B can see it — `81` §5's
rule.

`m_min` and `r_max` are the two numbers the probe (§5) measures. **They are
guesses until it runs.** Say so in the build.

### 4.2 The coat

Exactly `91`'s dielectric Fresnel, on **VoH** rather than `|dot(D,N)|`:

```
c   = clamp(VoH, 0, 1)                  ; VoH is already NClamp(...,0,1) at the site
g   = sqrt(1 - (1 - c^2)/n^2)           ; n = 1.5   (TIR impossible, g >= 0.745)
rs  = (c - n*g)/(c + n*g)
rp  = (n*c - g)/(n*c + g)
F_h = (rs^2 + rp^2)/2                   ; 20 instructions
```

`91` §2's proof that no denominator vanishes carries over unchanged (`n > 1`
entering the denser medium; bound `sqrt(1-1/n^2) = 0.7454`, which its build
*measures* over 6000 samples). The `abs()` guard `91` needed is unnecessary
here — VoH arrives pre-clamped — but the clamp is kept so a denormal normal
cannot put a NaN in the sqrt. A `-schlick` rung is built alongside, as `91` did,
because Schlick is up to 4 points high at 80–85°, exactly the band a coat
exists for, and 20 vs 8 instructions is a real difference at 6 sites.

Coat lobe, colourless, its own near-mirror roughness:

```
a_c   = coat_rough^2                     ; coat_rough = 0.06  ->  a_c = 0.0036
D_c   = a_c^2 / (pi * (NoH^2*(a_c^2-1) + 1)^2)
Vis_c = 0.25 / ((NoV + NoL)*(1 - a_c/2) + a_c)      ; the module's own Vis form
coat  = k_coat * F_h * D_c * Vis_c                  ; same value in all 3 channels
```

### 4.3 Energy conservation — the whole argument

Per arm, per channel:

```
spec_c' = spec_c * (1 - F_h) * glint  +  coat
```

and, once per module invocation, on the diffuse:

```
F_v      = F_dielectric(NoV, n=1.5)                 ; NoV = clamp(dot(N,V),0,1), one dot
diffuse *= (1 - F_v)
```

- `spec_c * (1 - F_h)` is exact reciprocity for the base lobe under the coat:
  what the coat reflects at the half-vector is exactly what does not reach the
  base layer.
- The diffuse damp uses **`F(NoV)`, not `F(VoH)`**, deliberately: VoH is
  per-arm, NoV is per-hit, and the coat's diffuse attenuation is a
  view-direction quantity. The textbook two-sided form is `(1-F(NoV))(1-F(NoL))`;
  we ship the one-sided version and own the residual — at grazing *light* the
  diffuse is over-bright by up to `F(NoL)`, bounded by the `NoL` the lobe is
  already multiplied by, so the worst-case error is a few percent of a term
  that is itself `(1 - metallic) ≤ 0.5` under the gate.
- `glint` has **`E[glint] = 1` exactly** (§4.4), so the split is energy-neutral
  in expectation with no fudge factor and no renormalisation constant. This is
  the property `72`'s dead sheen rung did not have, and it is the reason the
  glint is a *factor on the base lobe* rather than an added lobe: a glint is a
  redistribution of the base metal's energy across the pixel footprint, not new
  energy.
- **The coat itself is added, and the composite is therefore slightly over
  unity where `k_coat > 1`.** `k_coat = 1.0` is the energy-correct value and is
  the shipping default; the louder rung is labelled as not physical, exactly as
  `91` labelled `fres75`.

### 4.4 The glints

Deliot & Belcour 2023's counting model, reduced to the cheapest member of the
family — one Bernoulli flake per (space cell × angular bin) — because
everything more expensive needs a footprint derivative this shader does not
have. Written down as a reduction, not passed off as the paper.

```
P_w  = (%727,%729,%731) + cbv[104][56].xyz                  ; world, frame-stable (3.3)
r    = pix_angle * (t_primary + t_segment)                  ; footprint radius, metres
s    = cell * exp2(ceil(log2(max(1, r/cell))))              ; dyadic LOD ladder
ci   = floor(P_w / s)                                       ; 3 ints
di   = floor(H * q),  q = 1/theta_bin                       ; 3 ints, world-frame angular bin
u    = pcg_mix(ci, di) * 2^-32                              ; in [0,1)

nu   = nu0 * D * omega_bin * s*s                            ; expected flakes in this bin
p    = min(nu, 1)
pc   = max(p, 1/glint_max)                                  ; <-- the firefly clamp
g    = (u < pc) ? 1/pc : 0                                  ; E[g] = 1 EXACTLY, g <= glint_max
glint = mix(1, g, k_glint * w_fade)                         ; E[glint] = 1 for any k, w
```

Why each line is the way it is:

- **`di` from the world half-vector, not from a tangent-space slope.** There is
  no tangent frame (no UVs, `38` D2's blocker). Quantising the unit world `H`
  directly gives an angular bin of ~`theta_bin` radians that is view-frame
  independent, which is the property that actually matters — a glint must not
  move when the camera moves, only when the *light* or the *surface* does. The
  bins are mildly anisotropic near the axis poles; that is invisible and is
  cheaper than building a frame.
- **`pc = max(p, 1/glint_max)` is the clamp, and it does not break the mean.**
  Standard practice clamps `g` after the fact and quietly loses energy;
  clamping the *probability* instead keeps `E[g] = 1` identically for every
  `pc ∈ (0,1]` while bounding the peak at `glint_max`. `glint_max = 16` is the
  shipping default. **This is the answer to "glints must not become
  fireflies"**, and it is exact rather than tuned.
- **`nu` grows with the footprint, so `p → 1` and `g → 1` at distance**,
  automatically. That is the LOD behaviour `38` §0d demands: at 1 spp under
  DLSS a sub-pixel sparkle is a temporal alias generator, so the model has to
  converge to the smooth GGX lobe before the flakes go sub-pixel. `w_fade`
  additionally hard-fades the term out past a distance knob.
- **No PRNG, no frame counter, no entropy problem.** The hash is a pure
  function of world position and half vector; the same pixel on the same
  surface under the same light gives the same value every frame. This is
  exactly the property `91` §5 could not obtain for its stochastic two-lobe
  combine, and it is why glints are buildable here and that was not.
- **Motion smear (`38` §0d) is a real and unresolved cost.** The resolve is
  720p, tile-classified and motion-smeared to 1440p. A glint field is the
  highest-frequency signal imaginable and will be softened by the upscale. The
  design's answer is *not* to fight it: `cell` defaults to 8 mm, well above the
  720p pixel footprint at conversational distance, so the flakes are
  multi-pixel blobs that survive the resolve. Sub-millimetre "real" flake size
  is a knob, and it is expected to look like noise. **Pre-register that.**

### 4.5 Cost

Per module invocation (once): gate 4 ops, world position 8, `F_v` + diffuse
damp 24. Per arm (×6): exact Fresnel 20, `D_c` 8, `Vis_c` 6, coat combine 4,
hash ~22 integer + cell/bin ~14 float, glint combine 8 ⇒ **~82 ops × 6 ≈ 500
ALU per shaded hit**, plus 36 module-level. Against `28`, which added ~11 ops
per block over the same 6 blocks and cost nothing measurable, this is roughly
**8× the MS-GGX delta** and is not free.

It is also gated: everything except the 4-op gate test sits behind
`coat_gate`, so on the 99% of the frame that is not metal the cost is the gate.
Divergence within a wave is the real risk, not the ALU.

**Do not assert the cost — measure it.** `45` §E9's protocol: frozen PT
switches, same save, same camera, 60 s standing still, average frame time,
`ser`/`ptq` combo pinned. A delta under ~3% is noise.

---

## 5. The probe — one launch, `hunt-paint`

**Nobody has ever pointed a material probe at a car.** That is the whole
missing datum, and it is one launch.

### 5.1 The rung

A new tier in `dev/patch_subtype_probe.py` (which already owns the 76-module /
151-radiance-write paint machinery and the class read), painting a **joint
(class, metallic, roughness) code** so one frame answers both halves:

| condition | colour | what it means |
|---|---|---|
| `class == 1` | red | **built-in control** — skin must be red or the launch is void |
| `class == 3` | blue | high-precision-normal materials (§1.3) |
| `class == 4` | yellow | hair |
| `class == 5` | magenta | vegetation |
| `class == 0 && m < 0.10 && r > 0.35` | **unpainted** | the bulk of the world; keeps the frame readable |
| `class == 0 && m < 0.10 && r <= 0.35` | dark azure | smooth dielectric — glass, plastic |
| `class == 0 && 0.10 <= m < 0.50` | white | the semi-metal band |
| `class == 0 && m >= 0.50 && r <= 0.15` | **cyan** | mirror metal / chrome |
| `class == 0 && m >= 0.50 && 0.15 < r <= 0.35` | **green** | **the car-paint candidate window** |
| `class == 0 && m >= 0.50 && r > 0.35` | orange | rough metal |

Colours are disjoint from `HUNT_PALETTE`'s class colours so the two readouts
cannot be confused. The paint is a **multiply**, as `40` §3 requires, so a
painted region is still recognisable as a car.

Costs: one new tier in an existing patcher, no new overlay (it rides
`skin.set/hunt-paint` exactly as `40` §6 argues the probes must), no edit to
any shared file.

### 5.2 The frame — this is what decides whether the launch is worth anything

One shot, daylight, no neon, containing **all** of:

- **a parked car, close, with a body panel turned toward the camera** and a
  second panel at grazing;
- **the road surface** beside it;
- **a painted wall or a metal shutter** — the false-positive census, in the
  same frame (`81` §5);
- **an NPC with visible skin and hair** — the control. Skin red, hair yellow,
  or the capture is void;
- **a car window** — glass should read dark azure, not green.

`40` §7's two CET caveats apply verbatim: rewrite `skinspec=hunt-paint` in
`brdf_params.txt` before the launch (CET resets it), and the settings-page
WARNING is the confirmation the rung was served. Verify `skin_sha` on the
launch line before reading a pixel.

### 5.3 Pre-registered outcomes

| the car body reads | meaning | next |
|---|---|---|
| **green** | the gate exists and is `m >= 0.5, r ∈ (0.15, 0.35]` | build §4 as written |
| **cyan** | paint is smoother than assumed | lower `r_max` to 0.15; check chrome does not collide |
| **orange** | paint is metallic but rough | `r_max` up to ~0.5; the coat is then doing more work than the base and the clearcoat premise is stronger, not weaker |
| **white** (0.1 ≤ m < 0.5) | paint is a *layered* material with partial metalness | `m_min` down to 0.15; the diffuse damp (§4.3) stops being negligible and must move to the two-sided form |
| **unpainted** (m < 0.1, r > 0.35) | **the metallic premise is wrong.** Paint is a rough dielectric | the feature as designed is dead; the surviving gate would be `class == 3 && r <= 0.35`, i.e. §1.3's normal-precision flag, and that is a much weaker gate. Report it, do not build around it |
| **blue** (class 3) | there *is* a class-ish gate | use `class == 3 && m/r window`; strictly better than either alone |
| **road reads the same colour as the body** | the gate cannot separate paint from asphalt | wet asphalt genuinely is a smooth dielectric, so this is likely partly true; decide whether that is a bug or a feature (`38` D2 lists wet asphalt as a *wanted* target) |
| **skin is not red** | the launch is void | `40` §10's `cls`-null row — infrastructure, not a result |

---

## 6. Control builds and the verifier

### 6.1 Byte-identity, the way `91` did it

- `--k-coat 0 --k-glint 0` ⇒ the patcher emits **no constants, no body, no
  rewrites**, and the rebuild is `cmp`-identical to the base ptq module. Not
  "computes the identity" — *identical bytes*. `28`'s `--strength 0` is only
  numerically identical, and `27` §8.3 / `42` is the cautionary tale about
  48 bytes of unconsumed `OpConstant` passing every check for two years.
- `--k-coat 0` alone ⇒ identical to a glint-only rung; `--k-glint 0` alone ⇒
  identical to a coat-only rung. Three identities, all `cmp`.
- **Assert the site count, not the file hash** (GOTCHAS): 6 blocks × 10
  modules = **60 coat sites and 60 glint sites or the build dies**; the two
  scalar-specular permutations decline **by name** with a printed reason; any
  non-empty `skipped_dom` is fatal.

### 6.2 Verifier axes — all on the shipped `.spv`, none on build intermediates

Modelled on `dev/verify_cloth_sheen.py`, which re-disassembles from the parked
set and re-derives everything:

1. **Fresnel closed form** — peel the emitted chain, evaluate against an
   independently written float32 reference over ≥6000 VoH samples including
   exact 0, exact 1 and both normal orientations. `91` got 4.67e-07; hold that.
2. **No vanishing denominator** — measure `min|denom|` over the sample against
   the proven bound `sqrt(1-1/n^2) = 0.7454`, as `91` §4 row 9 does.
3. **`D_c` and `Vis_c`** — same treatment, on an (NoH, NoV, NoL) grid.
4. **Energy split** — assert `spec' = spec*(1-F_h)*glint + coat` structurally,
   i.e. that the rewritten consumer chain has exactly that shape, and that
   `replace_all_uses` rewrote **every** downstream use of each `spec_c` and left
   its definition alone (`40` §8 E3's practice).
5. **`E[glint] = 1`** — Monte-Carlo the emitted hash + Bernoulli over ≥10^6
   `(cell, bin)` draws at several `nu`, and check the mean to <0.5%. Also check
   the *hard bound*: `max(glint) <= glint_max` over the same sample.
6. **Hash quality** — the emitted PCG mix mirrored in Python, bit-exact on
   10^5 inputs; plus a spectral check that adjacent cells decorrelate (a hash
   that correlates along an axis gives visible stripes on a car door).
7. **Gate decode** — re-derive `metallic` and `rough` from the shipped bytes by
   the F0-chain walk (§3.4) and assert they are the ids the gate tests. This is
   the check that would have caught `88`'s vacuous `== 0` gate (`90` §0), so
   it must be shown **non-vacuous**: point it at an un-gated rebuild and it
   must FAIL.
8. **World-position contract** — assert the CB member the patcher adds is the
   *same* member that the module's own reservoir store adds (`%1419` chain),
   by id, or die. §3.3's inference becomes a build-time assertion.
9. **Gate-false bit-exactness** — evaluate the whole emitted chain with the
   gate false and require **exact float32 identity** with the base at every
   sampled point (`81` did this; it is stronger than "looks the same").
10. **`spirv-val`** at each module's own target env, plus the negative control:
    the verifier run against the unpatched base must report **0 sites and fail
    its coverage assertions**.
11. **Provenance** — base ptq combo sha recorded and re-checked, standing rungs
    (`fres`, `-clothhi`, the ptq base) asserted byte-unchanged.

### 6.3 The A/B ladder

`45` §2, one variable per launch, settings contract stated **before** the
launch and never inferred after (the `ab-settings-sync` rule).

1. `hunt-paint` — §5. **Nothing below is built until this reports.**
2. `-coat` vs base, pinned camera, the §5.2 frame. Claim: paint gains an
   angle-ramping white reflection; the base metal darkens by `(1-F)` at
   grazing; skin/cloth/hair/vegetation are **pixel-identical**.
3. `-coatglint` vs `-coat` — one variable, the glints.
4. `-glintcell` (a diagnostic that paints the cell index as a colour, glints
   off) — **the world-stability test**: translate the camera and the cells must
   stay welded to the paint. This is the only check that can falsify §3.3, and
   it is cheap. **Run it before believing any glint verdict.**
5. `-coatschlick`, `-glinthi`, `-glintfine` for taste, only after 2–4 settle.

### 6.4 Deployment constraints (not done, recorded)

The feature patches the same twelve `rgs_reference_main` ids as `ptq`, so
**it cannot be its own overlay** — first-file-wins means the second one is dead
with no error (GOTCHAS). It has to be either a new combo letter chained into
`build_ptq.sh` (the `m`/MS-GGX pattern, `28` §1) or a parked `carpaint.set/`
built on top of the selected ptq combo. Both touch shared files, which this
milestone is forbidden to do; the decision is the build's first question.

---

## 7. What is claimed, and at what confidence

| claim | confidence | how |
|---|---|---|
| The class field has 5 populated values and none is a paint family | **certain** | `dev/census_subenum.py` over 3290 modules, reproduced today |
| Class 5 is vegetation | **high** | `a-b-testing/L2-probe-cls/S1.png`, magenta on every plant and nothing else |
| Class 3 is a normal-precision decode switch | **high** | identical 10-bit octahedral block in a compute evaluator and in the one raygen that tests only class 3; no BRDF branches on it |
| No clearcoat lobe exists anywhere | **high** | 6 SG-Fresnel sites, 3 alphas, 2 arms per raygen; no second Vis chain; no exe string |
| The reference raygen does not shade the primary hit's direct light | **high** | the material phis feed only the BSDF-sampling region; all six GGX blocks read the post-trace payload ids |
| The payload carries no material class | **certain** | 4-member struct, every access chain indexes 0..3 |
| 60/60 blocks resolve N/V/H/NoH/NoV/NoL/VoH; metallic 18/18 per module | **certain** | measured, §3.4 |
| `cbv[104][56].xyz + P` is frame-stable world space | **PROVEN ON SCREEN** (2026-09-02; was "inferred, not proven") | `98` §15: `hunt-rayq-pxfw` adds this exact CB member — re-derived structurally as member **56** in 10/10 permutations by the trace-origin rule, never by index — to a ray query's `ObjectToWorld[3]`, and static geometry goes flat and stable under camera motion, while the otherwise-identical `hunt-rayq-pxfq` without the offset stays unstable. The TLAS is built in **camera-relative** space and this member is the camera offset. The two original consumers (reservoir store, light vector) agreed; a third, independent quantity now agrees too, on screen |
| Vehicle paint is `class 0` with `metallic ≥ 0.5, roughness ≤ 0.35` | **hypothesis** | this is what §5 measures. Do not build past `hunt-paint` on it |
| Any of this renders | **unknown** | nothing has been built |

## 8. Not done, deliberately

No files created outside this one. `init.lua`, `pt_engine.lua`,
`brdf_params.txt`, the `Makefile` and every existing rung were not touched;
`make install` was not run; nothing was committed; the game was not launched.
`dev/patch_ms_ggx.py` was executed **read-only** (`--report`) and
`dev/census_subenum.py` read-only over the dump.

---

# MILESTONE 2 — `hunt-paint` built (2026-09-01). Not installed, not launched.

## 9. What was built, and how it differs from §5

§5 sketched the probe as a new **tier inside `dev/patch_subtype_probe.py`**.
That would have been a shared-file edit, which the brief forbids, so the
machinery was **re-derived in a new file** that imports the existing patchers
and edits none of them. Three new files, nothing else touched:

| file | what it is |
|---|---|
| `dev/patch_hunt_paint.py` | the patcher. Class tint + metallic×roughness bucket at every radiance `OpImageWrite` of a compute module |
| `dev/build_hunt_paint.sh` | builds `swaps.huntpaint` (probe) and `swaps.huntpaint.ctl` (gain-0 control), both 93 modules, with the coverage census and the three non-vacuity proofs |
| `dev/verify_hunt_paint.py` | re-derives the whole gate from the **shipped `.spv`**, not from the build's own reports |

Everything runs green today:

```
2. round-trip neutrality (dis -> as == base bytes): 77 of 77
4. probe : 76 modules patched, 1 declined, 151 writes (31 refetched), 0 skipped
   control: 77 modules emitted, 0 declined, 0 writes painted
5. probe  : 76 of 77 compute modules differ from the base
   control: 0 of 93 modules differ from the base
6. verifier OK; rejects the base, the control, and a --no-buckets decoy
```

### 9.1 Site — the family that owns the primary hit

§2 established that the reference raygen does **not** shade the primary hit's
direct light; the 77 compute (resolve) modules do (site C). The probe is
therefore spliced **only** there. The 16 raygens are copied byte-verbatim from
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all` and `cmp`-asserted, so the rung
is one variable against the standing selection by construction.

### 9.2 Anchors, measured over all 77 modules of the standing base

| anchor | how it is found | coverage |
|---|---|---|
| material class | `patch_compute_skin.acquire_class_shift` — the module's own `word >> 5`, or one emitted after the shared texel extract | **77 / 77** |
| metallic / roughness | the `v4float` G-buffer fetch whose `.y` feeds `NMax(_, 0.0399999991)`; metallic = `.x`, roughness = `NMin(NMax(.y, .04), 1)` | **77 / 77**; `.x` is also the value the module's own skin gate compares to `0.1` in **74** of them |
| radiance writes | `patch_compute_brdf.find_image_writes`, texel = `OpCompositeConstruct %v4float` | **151 writes over 76 modules** |
| dominance | the class value and the m/r pair reach the write directly | **120 / 151**; the other **31** get a site-local refetch of *both* (same idiom as `emit_class_value`) |

**One named decline.** `ab0bc2fee876d489` has exactly one `OpImageWrite` and
its texel is an `OpBitcast %v4int` — an integer buffer, not radiance. It is
copied verbatim and is the *only* permitted decline; a decline anywhere else
fails the build by name. (`GOTCHAS`: assert the site count, never the file
hash.)

## 10. The verifier, and why it is not vacuous

`dev/verify_hunt_paint.py <rung-dir>` disassembles the shipped `.spv` and
re-derives, from the bytes alone:

1. the selection is complete — 77 compute + 16 raygen;
2. exactly 76 modules carry paint; the 77th is the named decline;
3. 151 painted writes, no unpainted float write left over;
4. at every painted write the texel RGB is `orig × chain`, and the chain is
   **rooted at 1.0** — so any pixel that matches no gate is bit-exact vanilla;
5. the gates are real, not decorative:
   - a **class** read: `OpIEqual` against a value proven to be
     `OpShiftRightLogical(OpCompositeExtract(OpImageFetch %v4uint, 1), 5)`,
     for classes 0/1/3/4/5, with the class-1 (skin) tint present;
   - a **metallic × roughness** gate: six mutually exclusive buckets, each
     `OpLogicalAnd`ed with `class == 0`, each comparing an id that the
     verifier independently traced to component 0 (metallic) or to
     `NMin(NMax(comp 1, 0.04), 1)` (roughness) of a `v4float` fetch;
   - one unknown-class catch-all;
6. the tint triples equal the documented legend to the float32 bit, and all
   76 modules agree on the five threshold constants.

The build proves it is non-vacuous by making it **fail** three times:

| pointed at | rejected because |
|---|---|
| the unpatched base | 0 painted modules / 0 painted writes / 151 float writes carry no paint |
| the gain-0 control | identical to the above — the control really is the base |
| a `--no-buckets` decoy (full class gate, full 151-write coverage, **no m/r gate**) | `0 metallic/roughness buckets, want 6`; `no bucket reads METALLIC` |

The third is the one that matters: a verifier that only counted writes would
pass the decoy.

## 11. The control — byte-identical, and not by tautology

`--gain 0` makes the patcher emit **no constants, no instructions and no
rewrite**; the module is re-assembled from the untouched disassembly. That is
only meaningful because **step 2 of the build first proves `spirv-dis →
spirv-as` reproduces all 77 base modules byte for byte**. So the control has
been through the whole pipeline — disassembler, the patcher's loader,
assembler, `spirv-val` — and still `cmp`s equal on **93 of 93 files**. It is a
real null, not a `cp`.

Selecting `hunt-paint-ctl` must be indistinguishable from selecting
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all`. If it is not, the layer is not
serving what it claims and no read-out from the probe is admissible.

## 12. The launch — settings contract FIRST (the `45` rule)

**Required, stated before the launch, never inferred from the capture
afterwards.** This is the live `brdf_params.txt` with **one line changed**:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=hunt-paint
    ser=class  ptreg=on  ptclamp=on  ptbounce=on  ptmsggx=on  refract=eta15

and, for the control half, the identical file with `skinspec=hunt-paint-ctl`.
`ser=class` and `shadowset=full-shadow` are the base's contract and are
**not** optional — `sync_settings.sh`'s `gi_refuse` block enforces them.

Game side, match across both halves and record it: **PT Overdrive on,
PT-in-photo-mode on, RR off, DLSS Balanced, RayTracedLighting Psycho,
2560×1440** (the state `79` verified).

`40` §7's two CET caveats apply verbatim: rewrite `skinspec=` in
`brdf_params.txt` **after** CET loads (CET resets it), and the settings-page
WARNING banner is the confirmation the rung was served. **Check `skin_sha` on
the launch line before reading a single pixel.**

Deploy first: `./dev/build_hunt_paint.sh --install`, then `make install`, then
`cmp` the served bytes — the game runs *copies*.

### 12.1 The frame to shoot

**One shot. Daylight, no neon, no wet ground, camera pinned in photo mode.**
It must contain **all** of:

- **a parked car, close**, with **one body panel facing the camera and one at
  grazing** — the whole point;
- **a car window** in the same panel run — glass must read *teal*, not green;
- **chrome or a bare-metal trim strip** — must read *cyan*;
- **dry road** beside the car, and **a painted wall or concrete** — the
  false-positive census, in the *same* screenshot (`81` §5's rule);
- **V, or an NPC, with visible skin and hair** — the control. If skin is not
  red and hair not yellow, the capture is void and nothing else in it counts.

Then shoot the **identical** frame on `hunt-paint-ctl` without moving the
camera. That half must be pixel-indistinguishable from the standing selection.

### 12.2 Colour legend (as built, `--gain 1.0`)

This **supersedes §5.1**: `r_lo` moved 0.15 → 0.12, and the hues were
re-picked so no bucket collides with a class tint.

| gate | colour | RGB multiplier | meaning |
|---|---|---|---|
| `class == 1` | **red** | 3.00, 0.15, 0.15 | skin — **the control** |
| `class == 3` | **blue** | 0.15, 0.15, 3.00 | the 10-bit-normal decode flag (§1.3) |
| `class == 4` | **yellow** | 3.00, 3.00, 0.15 | hair |
| `class == 5` | **magenta** | 3.00, 0.15, 3.00 | vegetation |
| class 2 / 6 / 7 | **black** | 0, 0, 0 | *cannot happen* — the census says these are unpopulated. A black hole in the frame is a headline finding |
| `c0, m < 0.10, r ≥ 0.35` | **untinted** | 1, 1, 1 | rough dielectric — most of the world; keeps the frame readable |
| `c0, m < 0.10, r < 0.35` | **teal** | 0.15, 1.60, 1.60 | smooth dielectric — glass, polished plastic |
| `c0, 0.10 ≤ m < 0.50` | **grey/white** | 2.40, 2.40, 2.40 | the semi-metal transition band |
| `c0, m ≥ 0.50, r < 0.12` | **cyan** | 0.15, 3.00, 3.00 | mirror metal — chrome |
| `c0, m ≥ 0.50, 0.12 ≤ r < 0.30` | **green** | 0.15, 3.00, 0.15 | **the car-paint candidate window** |
| `c0, m ≥ 0.50, r ≥ 0.30` | **orange** | 3.00, 1.20, 0.15 | rough / dirty metal |

Class gates win over buckets, and the unknown-class black wins over
everything. The paint is a **multiply**, so a tinted region is still
recognisable as a car (`40` §3).

Thresholds are `OpConstant`s baked at build time. To bisect the window without
touching a line of code:

    ./dev/build_hunt_paint.sh --install --set r_mid=0.25 --set m_hi=0.35

### 12.3 Decision table — which read-out unblocks what

The coat (§4.1) and the glints (§4.2) are gated on **different** answers, so
the table names the site each result unblocks.

| the car body panel reads | verdict | unblocks |
|---|---|---|
| **green** | the hypothesis holds: paint is `class 0, m ≥ 0.5, r ∈ [0.12, 0.30)` | **Build §4.1's coat at site C** (the 457 compute BRDF sites), gate `m ≥ 0.5 ∧ r < 0.35`. Glints unblocked too, gated on the same predicate |
| **cyan** (r < 0.12) | paint is smoother than modelled | coat at site C with `r_mid` → 0.12; **glints are at risk** — a near-mirror base makes a flake glint indistinguishable from the coat highlight. Ship the coat first, glints as a separate rung |
| **orange** (r ≥ 0.30) | metallic but rough | coat at site C with the window widened to `r < 0.5`. The coat now does *more* work than the base lobe, which strengthens the premise. Glints unblocked; raise the flake density knob |
| **grey** (0.1 ≤ m < 0.5) | paint is a layered material with partial metalness | coat at site C with `m_lo` → 0.15, **and** §4.3's diffuse damp stops being negligible: it must move to the two-sided form before the rung is worth looking at |
| **untinted** (m < 0.1, r ≥ 0.35) | **the metallic premise is dead.** Paint is a rough dielectric and is indistinguishable from concrete on `(m, r)` | **Kills the feature as designed.** Do not build a gate around it. Report the null; the only surviving lead is `class == 3 ∧ r < 0.35`, which is a much weaker gate and is a separate investigation |
| **blue** (class 3) | there *is* a class-ish handle | strictly the best case: gate on `class == 3 ∧ m/r window`. Coat **and** glints unblocked at site C with a cheaper, sharper predicate |
| **black** anywhere | a class outside `{0,1,3,4,5}` exists | stop and re-run the census; §1 is wrong and every downstream conclusion inherits the error |
| **the road reads the same colour as the body** | `(m, r)` cannot separate paint from asphalt | partly expected — `38` D2 *wants* wet asphalt. Decide it explicitly; if unacceptable, the coat needs a second discriminator and site C alone will not provide one |
| **the car window is green, not teal** | glass is being read as metal | the m/r anchor is picking up the wrong texel. **Kills the read-out**, not the hypothesis — fix the anchor and re-shoot |
| **skin is not red, or hair not yellow** | the rung was not served, or the class read is broken | **void.** Infrastructure, not a result (`40` §10's `cls`-null row). Check `skin_sha` and the WARNING banner |
| **`hunt-paint-ctl` differs from the standing selection** | the layer is not serving what it claims | **void, and worse** — every A/B in this repo inherits the doubt. Stop and fix the layer |

### 12.4 Cost

Per painted write: ~14 boolean ops + 30 `OpSelect` + 3 `OpFMul`, plus 8
instructions of refetch at 31 of the 151 sites. It is a diagnostic; it is not
meant to ship and is not on the ladder.

## 13. Still not done

`make install` was not run, nothing was committed, the game was not launched,
and `--install` was not passed — `swaps.huntpaint` and `swaps.huntpaint.ctl`
exist in the repo, nothing is parked in `skin.set/`. No shared file was
touched: `init.lua`, `pt_engine.lua`, `brdf_params.txt`, the `Makefile`,
`dev/patch_subtype_probe.py`, `dev/patch_compute_skin.py` and every existing
rung are unchanged (`git status` shows only the three new `dev/` files, the
two `swaps.huntpaint*` directories and this doc).

---

# MILESTONE 3 — `hunt-paint` IS SHOT. The gate is real; one unanticipated false positive (2026-09-01)

## 14. The read-out

**USER VERDICT 2026-09-01:** *"The capture is working very close to as
intended. Lots of cars have the green on them and we're separating materials
way better. The green is also getting picked up by some market tarp roofs
which may be a problem. Could be picking up that plastic tarp look as the car
paint too. Thats probably the worst offender. But everything else would be
awesome if they had specific better BRDF/BSDF's applied they seem pretty
materially consistent."*

Served the same way the fog rung was, and checked the same way: the launch
line names `skinspec=hunt-paint`, and `swaps.skin/` is `cmp`-equal to
`skin.set/hunt-paint`. §5's whole premise — *nobody has ever pointed a
material probe at a car* — is now retired.

### 14.1 What it settles

**Car paint is `class 0, m ≥ 0.50, r ∈ [0.12, 0.30)`** — the first row of
§12.3's decision table, the one the design was written for. That row's
consequence stands unchanged: **build §4.1's coat at site C**, gate
`m ≥ 0.5 ∧ r < 0.35`, and the glints are unblocked on the same predicate.
`m_min` and `r_max` were guesses in §4.1 and the build was told to say so;
they are now measured, and the measurement agrees with the guess.

The second half of the read-out matters as much and was **not** what the probe
was built to answer: the buckets *as a taxonomy* separate Night City's
materials cleanly and consistently. That is a reusable result. The gate is not
a car-paint gate; it is a **material classifier that happens to have a
car-paint bucket**, and the other five buckets are candidates for their own
treatments (chrome and mirror metal, rough metal, smooth dielectric, the
semi-metal band). That is a much larger programme than `94` and is recorded
here, not designed here.

### 14.2 The false-positive census — one problem, and it is not the metals

Everything else the window caught is **painted or smooth metal**, and the user
called all of it acceptable or wanted:

| what else reads green | is it a false positive? |
|---|---|
| metal gratings in windows | **no.** A window grating is painted steel. `m ≥ 0.5` with `r ∈ [0.12, 0.30)` is what painted steel *is*, and a clearcoat is the correct model for it |
| the grating inside road-edge light housings | same, and the coat's Fresnel is what makes a grille read as metal rather than as a texture |
| AC units, and some other metals | same. USER: *"I wouldn't mind if they randomly got materialed the same way it might look cool"* |
| chrome, polished signage, mirror cyberware (§4.1's pre-registered set) | bounded, as §4.1 argued — a mild Fresnel whitening |
| **market tarp roofs** | **YES — the only one.** USER: *"Overall just the tarp would be a problem"* |

That census is the useful shape of the result: the gate is not over-firing on
a grab-bag, it is selecting **smooth metal with a coat on it**, which is
exactly the material class §4.1 set out to find. Painted steel props landing in
it is the gate working, not leaking.

### 14.2a The one that is a problem

**Market tarp roofs read green.** **Tarps were not on §4.1's list**, and they are
worse than everything that was: they are large, matte-looking and overhead, so
a wrong specular on them reads as a bug rather than as a sheen. They are also
the only entry in §14.2 that is not metal — which is itself a clue. A woven
polymer sheet has no business at `m ≥ 0.5`; either the tarp material is
authored with a high metalness it does not physically have, or it shares a
template with something that does. That is worth one grep of the material
library if the bisect (§14.3) fails, because a mis-authored source would mean
no `(m, r)` threshold can ever separate it cleanly.

Two things are true at once and the design should exploit the split:

- **A clearcoat on a plastic tarp is not obviously wrong.** A tarp genuinely
  *is* a smooth polymer sheet over a woven base — the same layered
  construction the coat models. If the coat alone ships, a tarp gaining a
  Fresnel-weighted sheen is arguably a fix, not an artefact.
- **Metallic flake glints on a tarp are unambiguously wrong.** Nothing in a
  tarp glitters. §4.4's glints are the half that must not fire here.

So the coat and the glints, which §12.3 already treats as separately gated,
should ship on **different** predicates: the coat on the measured window, the
glints on whatever narrower window §14.3 can find — and if it finds none, the
glints stay unbuilt rather than firing on tarps.

### 14.3 Two rungs, built, to find out whether the tarp is separable at all

The thresholds are build-time `OpConstant`s precisely so this costs a launch
and not a patcher edit (§9). Two hypotheses, one knob each, both parked:

| rung | knob | hypothesis it tests |
|---|---|---|
| `hunt-paint-r20` | `r_mid` 0.30 → **0.20** | tarps are **rougher** than car paint. Green narrows to `r ∈ [0.12, 0.20)`; anything above turns **orange** |
| `hunt-paint-m70` | `m_hi` 0.50 → **0.70** | tarps are **less metallic** than car paint. Green needs `m ≥ 0.70`; anything below turns **grey** |

**One frame each, the same frame, holding a car and a tarp roof together.**

| what happens | reading |
|---|---|
| tarp turns orange (or grey), **car stays green** | separable. Move that threshold in §4.1's gate and the false positive is gone for both coat and glints |
| **both** turn, together | the two materials overlap on that axis; that knob cannot separate them |
| neither turns | both sit deeper inside the window than the new threshold; bisect again |

If both axes fail, `(m, r)` cannot separate tarp from paint at site C and
that is a real limit, not a tuning problem — the honest response is §14.2's
split (ship the coat, hold the glints), **not** a threshold that half-works.
`96` §4.2's 5-bit sub-enum would be the discriminator, and it is blocked on
the unfound fragment write site.

## 15. What the read-out did NOT report, and what that costs

Recorded so nobody later mistakes silence for a pass. §12.3 pre-registered
five checks that this read-out does not explicitly answer:

- **skin red / hair yellow** — the void condition. Almost certainly fine (a
  broken class read would not have produced a coherent material separation),
  but *almost* is not the standard this table was written to.
- **the car window teal, not green** — the "kills the read-out" row.
- **the road vs the body** — `38` D2 *wants* wet asphalt, so this needs to be
  decided explicitly rather than discovered later.
- **chrome cyan**, and **black anywhere** (which would falsify `§1`'s census
  and `96` §2 with it).
- **`hunt-paint-ctl` vs the standing rung** — unshot. It is the cheapest and
  most load-bearing control in the repo: 93 of 93 modules byte-identical, so
  if it looks different the layer is not serving what it claims and *every*
  A/B here inherits the doubt.

No screenshot was archived, so this is an eyeball read-out and not a pixel
measurement. That is enough to unblock §4.1 — the signal ("lots of cars",
"separating way better") is far above any plausible reading error — and it is
**not** enough for the four rows above, which are exactly the ones a glance
would miss.

---

# MILESTONE 4 — the bisect read-out, and the reading of it that the first pass got wrong (2026-09-01)

## 16. What the two bisect rungs measured

**USER READ-OUT:** *"[r20] makes more other tarps turn green. m70 the tarp
turns blindingly reflective. I'd say keep the old hunt-paint but do the coat
clear coat idea would be the move. skin was red and hair yellow. Lots of cars
did have teal. Some cars were teal and then blending into green. Others were
clearly green. Some dark blue (maybe because they were black to begin with?).
Car windows maybe had a teal hue. They were very clear. The odd dark blue car
that was kinda rare."*

### 16.1 §15's five unreported checks — four now answered, and they pass

| check | answer | consequence |
|---|---|---|
| skin red, hair yellow | **yes** | `§12.3`'s void row does **not** fire. The class read is sound and the rung was served. `14`'s read-out is admissible |
| car window teal, not green | **yes** ("maybe had a teal hue. They were very clear") | the "kills the read-out" row does **not** fire. The m/r anchor is reading the right texel |
| black anywhere | **not seen** | `§1`'s five-value census survives, and `96` §2 with it |
| road vs body | still unreported | `38` D2's wet-asphalt question stays open |
| `hunt-paint-ctl` vs the standing rung | still unshot | the most load-bearing control in the repo, still owed |

### 16.2 The tarp is now bracketed — on BOTH axes

Neither rung was read as a success, and the first of those readings is right
while the second is **wrong**, in a way that matters:

- **`hunt-paint-r20` (`r_mid` 0.30 → 0.20): the tarp stayed green.** Narrowing
  the window can only ever *shrink* the green set, so "more other tarps turn
  green" is more tarps in frame, not the gate widening. The measurement is
  therefore **tarp roughness < 0.20** — and since the cars were not reported as
  changing either, car paint is also below 0.20. **The roughness axis cannot
  separate them.** That hypothesis is dead and the rung did its job.

- **`hunt-paint-m70` (`m_hi` 0.50 → 0.70): "the tarp turns blindingly
  reflective" is the tarp LEAVING the paint bucket.** It did not become
  reflective. Under `m_hi = 0.70` a pixel with `m ∈ [0.10, 0.70)` falls into
  the **semi-metal band**, whose diagnostic tint is `grey = (2.40, 2.40,
  2.40)` — a **2.4× multiply**, which on a daylit tarp is exactly a blown-out
  white. That is the probe's paint, not the material's specular. **So the
  tarp's metalness is `m ∈ [0.50, 0.70)`** — it was captured at `m_hi = 0.50`
  and excluded at `0.70`.

Tarp, measured on both axes: **`m ∈ [0.50, 0.70)`, `r ∈ [0.12, 0.20)`**. A
woven polymer sheet at half-metalness is authoring, not physics (§14.2a).

### 16.3 The one question that decides whether the tarp is solved

**Under `hunt-paint-m70`, did the car bodies stay green?**

- **If yes** — cars are `m ≥ 0.70`, tarps are below it, and the two are
  **separable on the metallic axis**. `§4.1`'s gate ships with `m_min = 0.70`
  instead of `0.50`, the tarp is excluded from the coat *and* the glints, and
  no split is needed. This is the good outcome and it is one frame away.
- **If no** — cars went grey too, `m ∈ [0.50, 0.70)` holds both materials,
  `(m, r)` cannot separate them at site C, and `§14.2a`'s split stands: ship
  the coat, hold the glints.

Nothing downstream should be built until this is read, because it selects the
constant in the gate.

### 16.4 Car paint is not one material — and this reshapes §4.1's gate

The most consequential line in the read-out is the one that was not about
tarps: **"Lots of cars did have teal. Some cars were teal and then blending
into green. Others were clearly green. Some dark blue."**

Three populations, all cars:

| reads | bucket | what it means |
|---|---|---|
| **green** | `class 0, m ≥ 0.50, r ∈ [0.12, 0.30)` | the metallic-flake paint §4 was designed for |
| **teal** | `class 0, m < 0.10, r < 0.35` | **smooth DIELECTRIC paint.** Non-metallic body colour under a gloss — which is what a solid non-metallic automotive finish physically is |
| **dark blue** | **class 3** | not "the car was black": blue is the class-3 tint, and class tints take priority over the m/r buckets in the patcher, so a class-3 car never shows its bucket at all. `§1.3` predicted exactly this and called it "a usable if imprecise gate" — it is the high-precision normal decode, which the glossiest bodies get |

The teal→green blend across a single body is the m/r pair crossing the
thresholds over a panel — a paint authored with varying metalness, which is
what a flake layer over a base coat looks like when it is baked into a texture.

**Consequence for §4.1, stated as a fork, not resolved here:** a gate of
`m ≥ m_min` coats the green cars and **misses every teal one**. Widening it to
include the teal bucket would also catch **the car windows** (measured teal in
§16.1) and every other smooth dielectric in the city. So either

1. **ship the coat on the metallic bucket only** — correct on the cars it
   reaches, absent on the rest, no new false positives; or
2. **build a two-armed gate** — metallic arm as designed, plus a dielectric arm
   that needs a second discriminator to exclude glass. `96` §4.2's sub-enum is
   the natural one and is blocked; class 3 is available today but is a
   *decode* flag, not a material identity, and glass has it too.

(1) is the shippable one and is what `§4.2`'s coat already models. (2) is a
separate document.

### 16.5 Standing decision, recorded

USER: *"keep the old hunt-paint but do the coat clear coat idea would be the
move."* The probe stays at its original thresholds (`m_hi = 0.50`,
`r_mid = 0.30`), which are the ones §14.1 measured and the ones §4.1 was
written against — **pending §16.3**, which can still move `m_min` to 0.70 at
no cost, since it is one `OpConstant`.

---

## 17. Consult, 2026-09-01 — the dielectric arm is killed on physics, and the gate becomes a ramp

A second model was consulted on §16.4's fork and on the build plan. Its
conclusions are adopted; the ones that overturn something are marked.

### 17.1 The teal cars must NOT be coated — and the reason is not gating convenience

**OVERTURNS §16.4's framing.** §16.4 treated the teal (dielectric-paint) cars
as a population the metallic gate regrettably misses, with the dielectric arm
"a separate document". That is too generous to the idea. A solid dielectric
car finish is pigment under an `n ≈ 1.5` binder, and **the engine already
renders it that way**: `m < 0.10` gives `F0 = 0.04`, which *is* the n = 1.5
dielectric Fresnel, applied by Schlick at the compute sites and again at the
raygen bounce weight. The teal cars are already clearcoated. Adding §4.2's
coat on top is an **index-matched interface** — physically it reflects
nothing, and in the shader it would simply double the Fresnel (8% at normal
incidence, far worse at grazing).

So the dielectric arm is not a missing feature, it is a **double-count**, and
`96` §4.2's sub-enum is not needed to unblock it. The only deviation from a
true coat on those cars is that the lobe uses the authored roughness rather
than a coat's ~0.05, which is a roughness question, not a layering one.

The metallic cars are the ones genuinely missing a coat: at `m ≥ 0.5` the
single lobe carries the metal's *coloured* F0 and there is no colourless
dielectric layer above it. That is where the added lobe is new physics, and it
is the whole justification for the build.

**Also recorded, so it is not re-derived later:** a glass-vs-dielectric-paint
discriminator *does* exist at the site — base colour / diffuse albedo
(`%685 %687 %689`, §3.2); glass is authored near-black, paint is not. It fails
on black paint and on dark tint, and §17.1 makes it moot. **Do not build it.**

### 17.2 The gate becomes a ramp, not a boolean

**AMENDS §4.1.** The teal→green blend across a single body (§16.4) is
metalness varying over a panel. A hard `m ≥ m_min` therefore draws a **visible
edge in the coat highlight mid-body** — an artefact the boolean gate creates
by itself. Replace it with a ramp on the metallic axis:

```
w     = smoothstep(m_lo, m_hi, m) * (r <= r_max)
spec' = spec*(1 - w*F_h) + w*coat
diff' = diff*(1 - w*F_v)
```

Identity at `w = 0`, so `53`'s multiplicative-only rule and the
gate-false-is-bit-identical rule both still hold; about 4 extra ops.

### 17.3 Do not park two `m_min` coat builds — read the probe instead

**OVERTURNS the plan in §16.3's last line.** Deciding `m_min` from a *coat*
A/B means eyeballing a subtle Fresnel sheen; deciding it from the *probe* is
reading a saturated diagnostic tint. `hunt-paint-m70` is already built and
parked. One frame, car and tarp together, answers it. `hunt-paint-m60` is
built too, because authored metalness is 8-bit and a tarp is likely at a round
value, so the bracket `[0.50, 0.70)` is worth one bisect before the constant
is chosen. Then **one** coat build with the decided number:
ramp `(0.55, 0.70)` if the cars are `≥ 0.70`, and if car and tarp genuinely
share `[0.50, 0.70)`, accept the tarp on the coat per §14.2a.

### 17.4 What the coat will and will not look like — pre-registered

The 77 compute evaluators own **direct light only**. The environment/sky
reflection — which §2.3 already names as the single biggest visual component
of car paint — lives at the raygen bounce weight (site B) and **this build
does not touch it**. What ships is sharper, whiter sun and neon highlights on
metallic cars, *not* a showroom finish. Pre-registered so that "it looks the
same in overcast" is logged as the expected reach of site C and not as a
failure of the coat.

"Wet car" versus "clearcoated car" is n = 1.33 versus n = 1.5 and is not a
risk worth designing around.

### 17.5 Kill list, adopted

| killed | why |
|---|---|
| the dielectric/teal arm, and any glass discriminator | §17.1 — it is a double-count, not a gap |
| two parked `m_min` coat builds | §17.3 — the probe decides it more cheaply and more reliably |
| a `-schlick` coat rung | a 4-point Fresnel difference at 85° on a highlight is not visible. Spend the rung on `coat_rough` instead |
| `coat_rough = 0.06` as the sole default | `D_c` peaks at `1/(π·a_c²) ≈ 24 500` against ~630 for the base lobe at r = 0.15 — a highlight ~3× brighter and 40× narrower, on a sampled sun at 1 spp under a denoiser. **That is the firefly path.** Park 0.06 against 0.12 as the A/B |
| glints holding the coat hostage | held back anyway, and there is a second reason: the flake hash is world-locked in 8 mm cells, so on a *moving* car the sparkle slides over the body. They may never ship |

**Kept:** exact unpolarized Fresnel at the six sites, the `(1 - F_h)`
reciprocity and `(1 - F_v)` diffuse damp, `k_coat = 1.0` default. §4.3's
energy argument is sound as written.
