# 101 — Ear glow on the ray query. `rq3` (instance match + sun-visible exit point) SHOT BACKLIT and **KEPT** — it **was** the shipped default from 00:38 to ~01:20 on 2026-09-03, and is now carried inside the one that superseded it. `rq2` bled through the shaded front; `rq3` fixed it.

**STATUS 2026-09-03 00:5x — SHOT, KEPT, SHIPPED.** `earglow-rq3` was served at
00:38:40 (`skin_sha 359060c26c8c7367`, pre-registered) and the user's verdict is
*"THE EFFECT IS PERFECT. earglow-rq3 is the defacto."* It is parked a second
time under its lineage name
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow`, re-derived rather
than copied and 93/93 `cmp`-identical.

**SUPERSEDED AS THE DEFAULT, NOT AS AN EFFECT (2026-09-03 ~01:20).** The shipped
`skinspec` moved on to `gi-50b-…-cone2all-fog-earglow-glintdense`, which
**contains this rung byte for byte**: 83 of its 93 files are `earglow-rq3`'s
unchanged, and the other 10 `rgs_reference_main` carry *both* this document's
three ray queries and `100` §4.4's car-paint glints. `100` §13 is the stack and
its gates; the proof that the glow survived is that `dev/verify_earglow_rq3.py`
still passes on the stacked bytes and that `--k-glint 0` on them reproduces
`earglow-rq3` at 93/93 `cmp`. `…-fog-earglow` stays parked as the
default-minus-glints A/B handle. **§17 has the launch lines, the deploy `cmp`s and the honest caveat:
the glow rung itself was never captured, so the keep is a LIVE-ONLY read-out,
and the one frame that exists is a `-rq3-hit` diagnostic in which the ear is
behind hair — the fourth frame in this document taken before its own frame
condition was checked.**

**AND THE FLOOR IS NOW THE DEFAULT (2026-09-03 01:26).** `cap3` and `cap6` were
shot (01:24:07 `b3c690d79eb0a36d`, 01:25:56 `2b2a31c414e366b9`, both shas
pre-registered) and the user chose **`cap6`** by name — *"Get a subagent to use
earglow-cap6 as the default."* The shipped `skinspec` is therefore now
`gi-50b-…-cone2all-fog-earglow-cap6-glintdense` (`3bb0aee03a1bfda8`): the 6 mm
floor AND `100`'s dense glints, built on the `earglow-cap6` bytes by a new
wrapper (`dev/build_carglint_stack_cap6.sh`) that parameterises `100`'s stack
build without editing or forking it. **No frames again, `cap4` never shot, and
none of §18.6's six pre-registered rows can be read from a launch log** — §18.8
says exactly what the log does and does not establish. §18.9 has the gates.

**AND ONE MORE VARIABLE, UNSHOT.** The user then reported that thin ears are too
bright (*"Childrens ears GLOW"*), which is a correct reading of a transfer that
is monotone in 1/t with no ceiling but query B's 1.5 mm `tmin`. **§18** builds
the fix as three parked rungs — `earglow-cap3` / `cap4` / `cap6`, a thickness
FLOOR `t_eff = NMax(t, t_cap)` in the TRANSFER and not in the ray — nine gates
green, twelve decoys rejected, selftest 52/52 (was 50), and the `-earglow` rung is the
cap-0 control **proven** by rebuilding at `--cap 0` and getting its bytes back.
(The cap rungs are built on `-earglow`, not on the `-glintdense` stack that
superseded it, so a cap A/B is also a glints-off A/B — state it before the shot.)
**§18.8: `cap3` and `cap6` were then SHOT (01:24:07 / 01:25:56, both shas
pre-registered) and the user chose `cap6` by name — live-only again, no frames,
`cap4` never shot, and none of §18.6's six rows can be read from a launch log.
§18.9: the shipped default is now the CAP6 STACK
`gi-50b-…-cone2all-fog-earglow-cap6-glintdense` (`3bb0aee03a1bfda8`) — the floor
plus `100`'s dense glints — built by a new wrapper that parameterises `100`'s
stack build without editing or forking it, with both earglow verifiers passing
on the output and the glint census identical to `carglint-dense`'s.**

Written 2026-09-02. `70`'s W1+W3 on top of `98`'s proven ray-query mechanism.
Four rungs built, gated offline, proven on the driver by a self-test, parked,
selectable, installed. **Nothing has been on screen. Nothing committed.**

**Still UNSHOT as of 2026-09-02 22:2x.** A shot was attributed to this document
and the frames turned out to be `99`'s `hunt-wpos-frac`. The launch log carries
**zero** `earglow-rq` entries. §10 records the void, its two pre-registration
defects, and the deploy re-check (all four rungs `cmp`-clean, all three live
ones re-verified from the *installed* bytes). §11 pre-registers three
discriminators and says why they are **not** built.

Everything below is either a measurement (offline gate, driver self-test) or a
prediction (§7, §11). Each one says which.

## 0. Verdict

The ear-glow feature failed four times (`63`–`69`) for one reason, and it was
never the transfer curve: the ray it traced could not tell flesh from a hair
card, so a **consistency gate** was bolted on to suppress the false positives,
and that gate killed the true positives too (`69` §1). `70` W1 dissolves the
problem instead of filtering it — **aim the ray at the sun and cull FRONT
faces**. On a backlit surface the sun is on the other side of the flesh, so the
ray starts inside the manifold and the first visible triangle is the sun-side
wall **seen from inside**: a backface at exactly `t = the sun-path flesh
thickness`. That is the quantity the feature always wanted. The consistency
gate is **not weakened in this build — it is absent**, and so is every
threshold it needed.

What makes it buildable now and not in `69` is `98`: an inline `OpRayQuery` in
the reference raygen is proven — spliced, validated, compiled by the driver,
served through the layer, and **on screen**. So the ray is cheap (one query,
one `Proceed`, zero added `OpTraceRayKHR`) and no new mechanism is at risk.

**The one thing that is NOT proven is the premise.** W1 assumes the BLAS
carries interior backfaces. If the engine strips them, every query misses and
the whole rung is black. That falsifier is §4, and it is why `earglow-rq-hit`
exists and must be shot in the same frame.

## 1. Why the consistency gate is gone

> **CORRECTION (§12.4, written after the shot). This section is wrong.** The
> gate did not go away; it moved. The table below rejects a thin card *in front
> of the camera* and says nothing about a **foreign mesh sunward of the skin** —
> hair cards lying on the scalp, the inside of clothing, the eyeball behind an
> eyelid — which is the case that actually occurs on a head, and which is what
> the `-rq` shot produced. Read §12 before believing anything below. The fix
> (§12.5) restores a rejection test, but an **identity** one (does the committed
> backface belong to the same TLAS instance as the primary surface?) rather than
> `63`–`69`'s tuned consistency threshold.

v1–v4 traced a **reversed segment**: origin `P + 2cm·S`, direction `−S`, cull
BACK, and treated any front face inside the segment as "the far side of the
flesh". That reading is materially blind (`70` W1), so it fires on:

- a hair strand or collar card in front of the face,
- a sliver pixel whose primary hit is the face *behind* a strand,
- stacked strands faking a 2–8 mm gap.

Flip the ray and each of those dies **by construction**, not by threshold:

| leak class | what kills it in W1 |
|---|---|
| strand/collar card as the primary surface | its own backface sits at ~0.2–0.5 mm; the **min-t floor of 1.5 mm** rejects it (thinnest real ear ≈ 2 mm) |
| primary is the face behind a strand | sunward from the cheek is a whole head of flesh; no backface within **18 mm** ⇒ miss |
| strand stacks faking a gap | a stack is not a closed flesh manifold; the sunward ray leaves it and finds no backface in range |

No gate. No consistency term. No `T_VALID` band. The `dev/patch_earglow.py`
anchors are reused (they find the sun NEE trace, `N`, `P`, the class-1 fetch);
**its trace is not.**

## 2. The splice, instruction by instruction

One site, permutation `1271d3815051da17`, read back from the shipped
`swaps.earglow-rq/1271d3815051da17.rgs_reference_main.spv`. Ten permutations
carry 25 sites between them; they are all this shape.

Module header, two lines added:

```
OpCapability RayQueryKHR
OpExtension "SPV_KHR_ray_query"
```

`RayTraversalPrimitiveCullingKHR` is **already present** in all twelve
permutations (it is what `SkipAABBs` needs); the patcher asserts it and refuses
to add it, so a permutation that ever lacked it fails the build rather than
silently getting a capability the base never declared.

Function entry, four variables and three stores added:

```
%1252 = OpVariable %_ptr_Function_1230 Function     ; the ray query object
%1253 = OpVariable %_ptr_Function_float Function    ; R accumulator
%1254 = OpVariable %_ptr_Function_float Function    ; G
%1255 = OpVariable %_ptr_Function_float Function    ; B
        OpStore %1253 %float_n0                     ; -0, so k=0 and "no site
        OpStore %1254 %float_n0                     ; hit" are the same value
        OpStore %1255 %float_n0
```

The splice sits **immediately after the sun NEE `OpTraceRayKHR`** (`%2829`
= the TLAS, `%2830` = the hit position `P`, `%2831` = the normalised sun
direction `S`) and reuses all three of that trace's own SSA ids. Nothing is
recomputed and nothing is offset: `98` §15 measured that hit positions and the
TLAS live in the **same camera-relative space**, so a ray traced from `P` needs
no world offset. The verifier asserts the operands are literally those ids.

The gate — three existing booleans, ANDed:

```
%2851 = OpImageFetch %v4uint %2836 %2850 Lod %uint_0   ; the class G-buffer
%2852 = OpCompositeExtract %uint %2851 1
%2853 = OpBitwiseAnd %uint %2852 %uint_4294967264      ; & 0xFFFFFFE0
%2854 = OpIEqual %bool %2853 %uint_32                  ; class 1 == SKIN
%2855 = OpIEqual %bool %1743 %uint_0                   ; PATH counter == 0
%2856 = OpLogicalAnd %bool %2854 %2740                 ; %2740 = N.S <= 0 (backlit)
%2857 = OpLogicalAnd %bool %2856 %2855
%2858 = OpSelect %uint %2857 %uint_39 %uint_0          ; cull mask, 0 == free miss
```

`%1743` is found by `90` §find_path_counter (the counted loop whose header
seeds exactly three fp phis with 1.0 — the RGB throughput). **`79`'s
`dev/patch_earglow.py` used the legacy `find_bounce_counter`, which returns the
SAMPLE loop's phi.** The build prints the difference: the legacy helper would
have been wrong on **3 of these 10 permutations** (`1271d3815051da17`,
`25b54fc4a17688df`, `852b31a841b85b26`) — exactly the three `90` §1 predicted —
so on those the term would have been added on every bounce of every sample.
Gate 7 builds that mistake as a decoy and the verifier rejects it.

Gating through the **cull mask** rather than a branch is deliberate: mask 0 can
hit nothing, so a non-skin pixel pays a guaranteed near-free miss and the
control flow of the raygen is unchanged.

The query — one initialize, one proceed, committed-closest:

```
        OpRayQueryInitializeKHR %1252 %2829 %uint_545 %2858 %2830
                                %float_0_00150000001 %2831 %float_0_0179999992
%2859 = OpRayQueryProceedKHR %bool %1252
%2860 = OpRayQueryGetIntersectionTypeKHR %uint %1252 %uint_1     ; 1 == committed
%2861 = OpINotEqual %bool %2860 %uint_0                          ; committed anything?
%2862 = OpRayQueryGetIntersectionTKHR %float %1252 %uint_1       ; == thickness
%2863 = OpSelect %float %2861 %2862 %float_0_0179999992          ; miss guard
```

- **545 = 0x001 | 0x020 | 0x200** = `Opaque | CullFrontFacingTriangles |
  SkipAABBs`. `CullFrontFacingTriangles` is **0x20 = 32**;
  `CullBackFacingTriangles` is 0x10 = 16 and is what v4's reversed segment
  wanted. Getting these two backwards inverts the entire feature and is
  otherwise invisible, so gate 7 builds 529 (`CullBACK`) as a decoy.
- **`TerminateOnFirstHit` (0x04) is deliberately CLEAR.** The nearest backface
  is the near wall of the flesh, and that is the wanted answer, so `Proceed`
  runs traversal to completion and the **committed-closest** intersection is
  read. `TerminateOnFirstHit` would commit an arbitrary backface — a thickness
  reading through the far side of the head.
- `Opaque` + `SkipAABBs` are what make **one `Proceed` sufficient** (`98`
  §2.3): opaque removes alpha-test candidates, `SkipAABBs` removes AABB
  candidates, so traversal cannot come back asking the shader to resolve one.
  Zero added control flow.
- `tmin = 0.0015` m (1.5 mm, `TH_FLOOR`) is the strand-backface floor of §1.
  `tmax = 0.018` m (18 mm, `T_SEG`) is the thickest ear/nostril worth reading;
  gate 7 builds `tmax = 0.10` (reads through a whole head) as a decoy.
- `%2863` is the **miss guard**. `OpRayQueryGetIntersectionTKHR` on a
  non-committed query is undefined, and one NaN reaching a radiance
  accumulator poisons a pixel for the rest of the frame. The verifier asserts
  the raw `t` (`%2862`) has **exactly one consumer** and it is this select.

The transfer (`70` W3) — wrap envelope, then a two-lobe Beer–Lambert per
channel, then the add:

```
%2864 = OpLogicalAnd %bool %2857 %2861                 ; gate AND committed
%2865 = OpSelect %float %2864 %float_0_219999999 %float_n0    ; k = 0.22, else -0
%2869 = OpCompositeConstruct %v3float %1706 %1708 %1710       ; N (the trace's own)
%2870 = OpCompositeConstruct %v3float %2866 %2867 %2868       ; S (from %2831)
%2871 = OpDot %float %2869 %2870
%2872 = OpFNegate %float %2871                                ; -N.S
%2873 = OpExtInst %float %1 SmoothStep %float_n0 %float_0_349999994 %2872
%2874 = OpFMul %float %2865 %2873                             ; kw = k * wrap
; --- red, and G/B identically with their own two rates ---
%2875 = OpFMul %float %2863 %float_272_479553      ; t * 1/ld          (ld = 3.67 mm)
%2876 = OpFNegate %float %2875
%2877 = OpExtInst %float %1 Exp %2876
%2878 = OpFMul %float %2863 %float_68_1198883      ; t * 1/(4*ld)  the wide lobe
%2879 = OpFNegate %float %2878
%2880 = OpExtInst %float %1 Exp %2879
%2881 = OpFAdd %float %2877 %2880
%2882 = OpFMul %float %2881 %float_0_5             ; the two lobes, evenly weighted
%2883 = OpFMul %float %2882 %2874                  ; x kw
%2884 = OpFMul %float %2883 %2720                  ; x sun radiance R (cbv[..][6].x)
%2885 = OpExtInst %float %1 NMin %2884 %float_100  ; the CLAMP, as everywhere else
%2886 = OpLoad %float %1253
%2887 = OpFAdd %float %2886 %2885
        OpStore %1253 %2887
```

and at the radiance write, ~9800 instructions later:

```
%12816 = OpLoad %float %1253
%12817 = OpFAdd %float %12762 %12816
%12818 = OpLoad %float %1254
%12819 = OpFAdd %float %12763 %12818
%12820 = OpLoad %float %1255
%12821 = OpFAdd %float %12764 %12820
%12822 = OpCompositeConstruct %v4float %12817 %12819 %12821 %12807
         OpImageWrite %12813 %12814 %12822
```

Alpha is passed through untouched. The verifier asserts **every** rewritten
texel is an `OpCompositeConstruct` of exactly three `OpFAdd(component,
OpLoad(accumulator))` — a rung that multiplied one channel by accident would
fail rather than ship.

## 3. It ADDS. It does not multiply.

> **CORRECTION (§12.3).** True, and not enough. `-hit` adds a bare `3.2` in
> absolute radiance, which is invisible next to a sun-lit surface whatever the
> operator is. Arguing the operator and never the magnitude is why the `-hit`
> frame was unreadable. `earglow-rq2-hit` scales its paint by the same sun
> radiance the feature scales by.

`98` §12.4 is the reason and it is a measurement, not taste: the `hunt-rayq`
paint is an `OpFMul` on the radiance stores, and the first shoot showed it is
**invisible on sunlit surfaces** — a multiply on a bright pixel is swamped, and
a multiply on a black pixel is still black. Ear glow lives on skin that is
**facing away from the sun** — i.e. dark. `0 × anything = 0`. A multiplicative
term is not a weak version of this feature; it is no feature.

An add is also what `69` already read on screen at this exact site ("subtle
nose light up is cool") before the consistency gate suppressed it, so the site
is known to reach the frame.

Cost of the choice: an add is not energy-conserving and cannot be. `k = 0.22`
with the `NMin 100` clamp is the whole of the discipline, and **`k` is not
tunable** — `70`/`71` fixed it and the `-hi` rung changes the transfer SHAPE
(`wide` 4→6, `wrap` 0.35→0.5), never the strength.

## 4. The falsifier, pre-registered

**W1 requires the BLAS to contain interior backfaces.** Nothing in `98`
measured that. If CP2077 strips them (or authors heads as open shells), the
sunward query commits nothing at any pixel and:

> `earglow-rq` is black everywhere, and is indistinguishable from
> `earglow-rq-ctl`.

That failure is silent and would otherwise be mistaken for "the gate is too
tight" or "k is too low" — the two mistakes this track has already made twice.
So the miss/hit map is made readable **independently of the transfer**:

`earglow-rq-hit` runs the identical query with the identical flags, tmin, tmax
and gate, and then paints a **flat** colour with **no transfer at all**:

- **BLUE (0, 0.4, 3.2)** — gate passed AND the query committed a backface
  within 18 mm.
- **RED (3.2, 0, 0)** — gate passed and the query committed **nothing**.

Non-skin, non-backlit and non-primary-bounce pixels are untouched. So the
diagnostic separates "no backfaces exist" (all red) from "backfaces exist and
the transfer is wrong" (blue in the right places, no glow on `earglow-rq`)
before a single constant is questioned. **Shoot it in the same frame.**

If the map is all red: **stop.** Do not tune. `70` W1's fallback is v4
machinery plus the s-band probe of `69` §2, and it is a different brief.

## 5. The transfer, and what it is worth

Jensen skin1 per-channel mean free paths, carried verbatim from `71` /
`dev/patch_earglow.py` `LD_M`:

```
ld = (3.67, 1.37, 0.68) mm   ->   1/ld = (272.479553, 729.927002, 1470.58826) /m
```

Two lobes per channel, evenly weighted: rate `1/ld` and rate `1/(wide·ld)`.
`wide = 4` for `earglow-rq`, `6` for `-hi`. The point of the second lobe is to
**flatten the curve**: a single exponential turns 1 mm of thickness error into
a 3.9× brightness error, which is how v1 produced hot spots on 3 mm of nothing.

Closed-form, computed in gate 8 from the rate constants **read back out of the
shipped `.spv`** (not from the patcher's inputs), `× k = 0.22`:

| t (mm) | R | G | B | R/G |
|---|---|---|---|---|
| 1 | 0.18652 | 0.14467 | 0.10144 | 1.29 |
| 2 | 0.15977 | 0.10191 | 0.05854 | 1.57 |
| 4 | 0.12075 | 0.05895 | 0.02558 | 2.05 |
| 8 | 0.07622 | 0.02587 | 0.00581 | 2.95 |
| 18 | 0.03309 | 0.00412 | 0.00015 | 8.03 |

Red span over t ∈ [1, 6] mm: **1.97×** (a raw single lobe would be 3.91×).
`-hi` spans **1.80×** and is redder late (R/G 4.01 at 18 mm vs 8.03). Thin
flesh reads pale-warm, thick flesh reads deep red — the lightbulb.

## 6. Gates, and the rungs

Nine offline gates, all green, plus a driver self-test. `./dev/build_earglow_rq.sh`:

| # | gate | result |
|---|---|---|
| 0 | base provenance: 77 compute + 4 `rgs_restirgi_*` + 12 `rgs_reference_main` | 93 modules |
| 1 | round-trip neutrality: `spirv-dis \| spirv-as` == base bytes | 10 of 10 |
| 2 | patch + assemble, `spirv-val --target-env vulkan1.4`, and the 81 non-reference modules cmp-verbatim | 4 rungs × 93, clean |
| 3 | coverage census from the patcher reports against a WANT table | 25 painted writes, 22 benign skips, per rung |
| 4 | instruction census on the SHIPPED bytes | 10 Initialize, 10 Proceed, 10 committed-T getters, **0 added `OpTraceRayKHR`** |
| 5 | k=0 identity | `-ctl` **93 of 93 byte-identical** to the base; live rungs differ on exactly **10 of 93** |
| 6 | `dev/verify_earglow_rq.py` re-derives everything from the shipped bytes | ALL PASS ×3, plus a negative control on the 12 base modules |
| 7 | non-vacuity: ten decoys that MUST be rejected | 10 rejected |
| 8 | closed-form numpy transfer check against the rate constants in the `.spv` | §5 |
| 9 | MANIFEST provenance (`src_ser`/`ser_sha`/`ptq_sha`) carried verbatim | 4 written |

The ten gate-7 decoys: flags 529 (`CullBACK`), `tmax` 0.10, the legacy bounce
counter, the unpatched base read as a rung, the k=0 control read as a rung,
`earglow-rq` read as `-hit`, `-hit` read as the glow rung, `-hi` read with
`-rq`'s transfer, flags 517 (`98`'s probe word), and `98`'s `hunt-rayq-p` —
a real ray query, but the wrong one.

The verifier is independent of the patcher: it re-derives the sun NEE trace
(flags 12, tmax 10000, `OpSelect(cond, 0, 39)` mask) and the path counter with
its **own** copy of `90`'s throughput discriminator, then asserts flags == 545
bit by bit with a reason per bit, tmin/tmax, that origin and direction are the
NEE trace's own ids, one Initialize / one Proceed / **one** committed-T getter
and **zero** of the other eleven getters, the miss guard's single consumer, an
unchanged trace count, the transfer census (6 `Exp`, 1 `SmoothStep`, 1 `Dot`
added; both rate constants resolved per channel), that the `k` select is gated
on the same boolean as the cull mask, and the shape of every rewritten write.

**Driver self-test** (`./dev/selftest_earglow_rq.sh`, RTX 4070): **22 passed, 0
failed.** spirv-val is not a driver. This one creates a real `VkDevice` that
never asks for `VK_KHR_ray_query`, confirms the layer adds it, compiles a
synthetic raygen carrying the exact splice shape (flags 545, committed type +
committed T, the miss guard, the smoothstep and all six `Exp`) **into an RT
pipeline**, and then serves all four rungs' **real ~300 KB raygens** —
10 ids × 4 rungs, each checked at its shipped byte size — through the layer's
own first-file-wins overlay path to `vkCreateShaderModule`. It also proves the
reject guard: with `CALLISTO_RAYQ_DISABLE=1` all ten painted modules are
rejected with `action:next_overlay` and fall through to the **next overlay**,
not to vanilla, while the `-ctl` rung (which declares no ray query) is served
untouched under the same guard.

### rungs

Base for all four: `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`
(content `4dc824ca77d95feb`, raygen-half `1f09268e3d294697`).

| rung | what it is | content sha | raygen-half |
|---|---|---|---|
| `earglow-rq-ctl` | k=0. The patcher emits **nothing**; gate 1 makes assembly byte-neutral, so this IS the base | `4dc824ca77d95feb` | `1f09268e3d294697` |
| `earglow-rq-hit` | the §4 diagnostic: flat BLUE on commit, RED on miss, no transfer | `737f37a613022455` | `8136e538f91d3ffa` |
| `earglow-rq` | W1+W3, k=0.22, wide 4.0, wrap 0.35 | `2130f9f0b69c8527` | `2fbdfecae8b38e31` |
| `earglow-rq-hi` | same k, softer transfer: wide 6.0, wrap 0.5 | `90fa5762820c82ac` | `10b7874cbe43ab47` |

`-ctl`'s sha is the base's sha, digit for digit. That is the control: it is not
"close to" the base, it is the base, and any difference seen against it on
screen is a lie about something else.

All four parked in `~/.local/lib/callisto/skin.set/`, selectable from the CET
page as `skinspec`. **No default was changed** — the standing default is still
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`.

## 7. The shoot — READ THIS BEFORE LAUNCHING

> **CORRECTION (§12.4, written after the shot). This section never said the
> frame must be BACKLIT, and it must.** The wrap term is
> `smoothstep(0, wrap, −N·L)`: it is exactly zero on skin that faces the sun.
> In a front-lit frame every pixel this feature can paint is on the side of the
> head away from the camera, so the ear's *back* glows and its sun side does
> not — both of which the `-rq` shot produced and both of which are the design
> working. The feature cannot be judged in a front-lit frame. §13.1 states the
> frame contract for `rq2` and it is not optional.

### settings contract (state it, do not reconstruct it afterwards)

- `ser = class` and `shadowset = full-shadow` — **required**. The splice site
  is the sun NEE trace; a shadow set that removes it removes the feature.
- `ptq` unchanged from whatever the parked rungs were built against (the
  MANIFEST carries `ptq_sha`; `sync_settings.sh` disables the overlay on a
  mismatch rather than serving a stale one).
- **RR off.** Ray reconstruction re-renders the frame from its own inputs.
- Path tracing on, photo mode, camera still (the accumulator converges).
- **Sun LOW and BEHIND the character.** No sun behind the head ⇒ no backlit
  skin ⇒ `N·S <= 0` never fires ⇒ nothing to see, and that is not a result.

### the frame

Character backlit, **ears and nose against a darker background** (a doorway, a
shaded wall, sky is acceptable if the ear silhouette is readable). Head roughly
side-on so an ear is between the camera and the sun. Fingers in frame if
convenient — they are the second-best thin-skin test.

**Shoot the same frame four times**: `earglow-rq-ctl`, `earglow-rq-hit`,
`earglow-rq`, `earglow-rq-hi`. `-hit` and `earglow-rq` in the SAME frame is not
optional; §4 cannot be read otherwise.

### pre-registered interpretation table

Written before any launch. Do not edit it afterwards — add a revision section.

**`earglow-rq-hit`, read FIRST:**

| what the screen shows | what it means | what to do |
|---|---|---|
| blue on ears, nose, fingers only | backfaces are in the BLAS and thickness is readable. The premise holds | read `earglow-rq` |
| **nothing painted anywhere** (no blue, no red) | the gate never passed: not skin-classed, not backlit, or the counter operand is wrong. Not yet the falsifier | check the sun is behind the head; if it is, the class or counter gate is the suspect, not W1 |
| **red everywhere the gate passes, no blue at all** | **THE FALSIFIER FIRED.** Interior backfaces are stripped from the BLAS | **STOP.** Do not tune k, tmin, tmax or the transfer. `70` W1's fallback (v4 + `69` §2's s-band probe) is a different brief |
| blue on ALL skin, cheeks and forehead included | tmax is too large, tmin too small, or the ray is not leaving the surface (origin/normal wrong) | re-read §2's operands against the shipped bytes; suspect `tmax` first |
| blue on hair cards | the min-t floor is too low, or hair is class-1 in this build | raise `TH_FLOOR`; check `96` for the hair class |
| blue in a thin rim exactly on the silhouette | correct and expected — the silhouette IS where flesh is thin | read `earglow-rq` |
| red on ears, blue on the cheek | the ray is inverted (`CullBACK`) — but gate 7 rejects 529, so this would mean the shipped bytes are not the built bytes | re-run `cmp` on the installed set |

**`earglow-rq`, read SECOND:**

| what the screen shows | what it means | what to do |
|---|---|---|
| warm glow on ears and nose only, brightest where thin | **the feature works.** First true positive since v1 | A/B `-hi`; keep the ladder, do not touch k |
| glows on everything backlit and skin-classed | the wrap envelope is too wide or thickness is not discriminating | compare against `-hit`: if `-hit` was also all-blue, it is tmax, not the transfer |
| **no glow, though `-hit` painted blue in the right places** | the query is right and the transfer or the add is wrong — the ONLY case where the constants are the suspect | check `k`, the `NMin 100` clamp, and that the accumulator actually reaches the write |
| glow but grey/white, not warm | the per-channel rates are not per-channel (one rate used for three) | verifier gate 6 should have caught this; re-run it on the installed set |
| glow on hair, collar, or the ear's shadow on the neck | leak. Log which; it is a class-gate result, not a W1 result | |
| **`-ctl` differs from the standing default in any way** | the install is not what was built | `cmp` the parked set against `swaps.earglow-rq-ctl/`; nothing else in this doc is readable until it matches |
| `-hi` indistinguishable from `earglow-rq` | the transfer shape is not the lever at this k | record it; the ladder collapses to one rung |
| everything black, all four rungs | not a rung result — PT is not engaging, or the overlay is disabled | check the layer log for `overlay` and `swap:HIT` before reading anything |

## 8. What is deliberately NOT in this build

- **W2 (jittered entry) is not built.** `70` W2 wants a per-frame-varying value
  to jitter the query origin so the photo-mode accumulator integrates the
  diffusion aperture for free. `98` §12.6 audited the module's hash chain and
  found **no per-frame entropy reaches the paint chain** — the PRNG state the
  raygen uses at this point is seeded from the pixel, not the frame. Harvesting
  one is a separate hunt with its own falsifier; inventing one here would have
  shipped a jitter that is constant across frames, which is a bias, not a
  sample. Not built, and this is why.
- **No albedo gate (v2) and no sun-visibility ray (v5).** The brief is one
  query, one `Proceed`. The known bias this leaves: **backlit skin that is in
  shadow will still glow** (a hat brim, hair over an ear). If §7 row "glow on
  the ear's shadow" fires, that is this, and it is a second ray to fix — not a
  threshold.
- **No default flip.** Four optional rungs. The standing selection is
  unchanged.
  **AMENDED 2026-09-03 (§17): this held for the `rq`/`rq2` rungs and no longer
  holds for `rq3`. The user judged `earglow-rq3` on screen and asked for it as
  the default, so it IS the default now, under the lineage name
  `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow`. The rule the
  original line encodes — an agent does not flip a default on its own — is
  intact: the flip was requested.**

## 9. Files

| file | what it is |
|---|---|
| `dev/patch_earglow_rq.py` | the patcher. Imports its anchors from `dev/patch_earglow.py` and `find_path_counter` from `dev/patch_cavity2.py`; edits neither, nor `dev/patch_rayq.py` |
| `dev/verify_earglow_rq.py` | the verifier. Re-derives from shipped bytes; 11 check groups; `--negative` |
| `dev/build_earglow_rq.sh` | the four rungs, nine gates, `--install` |
| `dev/selftest_earglow_rq.sh` | the driver half. **34 checks** through the real layer (was 22): all seven rungs' real raygens, plus case E — two live ray query objects, two `InstanceId` getters and the `OpIEqual`, compiled into an RT pipeline |
| `dev/patch_earglow_rq2.py` | the `rq2` patcher (§12.5). Imports `_find_primary_ray`/`_add_header` from `dev/patch_rayq.py`, the anchors from `dev/patch_earglow.py`, `find_path_counter` from `dev/patch_cavity2.py` and the shared constants from `dev/patch_earglow_rq.py`; **edits none of them**. `--decoy nomatch|custom|invert` builds the non-vacuity decoys |
| `dev/verify_earglow_rq2.py` | the `rq2` verifier. Re-derives **both** queries from shipped bytes, the ±0.1 % bracket, the equality on the two `InstanceId` getters, and that the transfer is **dominated** by that compare; 13 check groups; `--negative` |
| `dev/build_earglow_rq2.sh` | the four `rq2` rungs (`-hit`, `-hitw`, `-rq2`, `-hi`), nine gates, `--install`. The control is `earglow-rq-ctl` and is asserted, never rebuilt |
| `dev/patch_earglow_rq3.py` | the `rq3` patcher (§16). Imports queries A and B and the diagnostic units from `dev/patch_earglow_rq2.py` and edits nothing it imports. `--decoy noc\|cullfront\|invert` |
| `dev/verify_earglow_rq3.py` | the `rq3` verifier. Re-derives all three queries, C's origin as `P + (t+push)·S`, C's flags/mask/tmin/tmax against the module's own sun shadow ray, and that the accept is the AND of the instance compare and C's **miss** |
| `dev/build_earglow_rq3.sh` | the three `rq3` rungs, nine gates, eleven decoys, `--install` |

---

## 10. The shot — IT DID NOT HAPPEN. Capture VOID.

Written 2026-09-02 22:2x, after the frames named as "the shot" were measured.

**Verdict: no earglow rung has ever been served.** `101` is still UNSHOT, and
§7 is still entirely unread. The two frames handed over as the shot are
`hunt-wpos-frac` — `99`'s world-position probe, another track's rung shot in
the same hour. Both are copied to `a-b-testing/earglow-rq/` with `RESULT.md`,
labelled for what they are, so that this mistake is not repeated from the
folder name.

### 10.1 The user's verdicts, verbatim

> "The earglow seems to be missing. Only mid body is blue"

> "Red everywhere"

Both are true of the frames the user was looking at. **Neither is evidence
about this feature**, because the shader that painted those pixels is not in
this document. Recorded here in full because they are the reason a diagnosis
was nearly written on the wrong pixels.

### 10.2 Four independent proofs that the rung was not served

| # | proof | reading |
|---|---|---|
| 1 | **launch log** | `grep -c earglow-rq ~/callisto_launches.log` = **0** of 181 lines. The only `earglow` lines are the v1–v4 track, 2026-08-31. Last entry: `2026-09-02T22:06:48 skinspec=hunt-wpos-frac skin_sha=19161b2acdd5d01f cache=kept`. Both frames (22:08:13, 22:09:17) fall inside that session |
| 2 | **the installed set** | `~/.local/lib/callisto/swaps.skin/MANIFEST` line 1 begins `hunt-wpos-frac …`, mtime 22:06. `last_run.json` (mtime 22:07, pid 3575494, overlays skin/shadowcull/ptq/ptrefl) is the process that took both frames |
| 3 | **the pixels** | both frames carry `99`'s 1 m `frac(P)` RGB checkerboard across the whole ground plane and magenta vegetation to the horizon. Every earglow write is gated class-1 skin AND backlit AND PATH counter 0; **no earglow rung can paint a road or a bush** |
| 4 | **absence of the signature** | all 32 frames from 2026-09-02 scanned for a flat saturated blue/red pair confined to skin. **None has it.** The only frame with any blue mass (`200044`, blue 2.86 %, red 15.6 %) is a `hunt-rayq` probe from `98`'s track — full-scene rainbow, checked by eye |

### 10.3 The measurements

2560×1440, RGB, red-dominant `R>60 ∧ R>2.2G ∧ R>2.2B`, blue-dominant
`B>60 ∧ B>2.2R ∧ B>1.8G`:

| frame | red-dom | blue-dom | mean of the "blue" pixels | frame mean RGB |
|---|---|---|---|---|
| `photomode_02092026_220813.png` | **7.412 %** (273 242 px) | **0.025 %** (927 px) | (45.6, 67.9, 107.6) | (133.1, 114.0, 110.0) |
| `photomode_02092026_220917.png` | **3.229 %** (119 035 px) | **0.069 %** (2 542 px) | (41.1, 67.1, 105.0) | (146.4, 131.0, 128.6) |

`-hit` paints flat **BLUE (0, 0.4, 3.2)** and flat **RED (3.2, 0, 0)**. A
tonemapped (0, 0.4, 3.2) is a saturated blue with **R ≈ 0**; the blue pixels
here average **R = 45.6, G = 67.9** and are scattered singletons — sky and cyan
floor tiles. The red-dominant mass has a bounding box spanning the **full**
frame (y[40,1439] x[0,2559]) including ground and vegetation, which the class
gate forbids. Per-region crops of ears / nose / fingers / neck / torso were
**not** taken and must not be: measuring a region of the wrong shader's output
would manufacture a number that looks like a result.

The one question that *could* have been answered from these frames — "is the
blue region skin or clothing-over-skin" — is also void: in frame B the torso
that reads blue is a **shirt and vest**, and it reads blue because `frac(P)`'s
third channel lands there, not because a backface was committed at 18 mm.

### 10.4 Which §7 row fired

**None. No row can fire.** §7's first table is written entirely as *"what the
screen shows"* → *"what it means"*, and every row silently presupposes that the
screen is showing `earglow-rq-hit`. On these frames the antecedent of every row
is false. In particular the falsifier row (**"red everywhere the gate passes,
no blue at all"**) did **not** fire: it was never tested.

### 10.5 The pre-registration defect

This is a defect in §7, recorded as such and not as a surprise.

**Defect 1 — §7 has no serving-proof precondition.** Ten rows tell the reader
what a colour means; none tells the reader to prove *which shader painted it*
before reading a colour. The proof was available and cheap (the launch log's
`skin_sha`, the installed `MANIFEST`, a `cmp`), and it is what caught this.
`99` §10.8e learned the mirror of this defect on the same day — a colour row
that fired for reasons outside the rung — and reached the same conclusion:
**the primary serving proof is the launch log's `skin_sha` plus the deploy
`cmp`, never a colour.** §7 gets a row 0, below, and §11 carries it.

> **§7 row 0 (added 2026-09-02).** Before reading any colour: `grep` the launch
> log for the rung's `skin_sha` (`-hit` `737f37a613022455`, `-rq`
> `2130f9f0b69c8527`, `-hi` `90fa5762820c82ac`, `-ctl` `4dc824ca77d95feb`) at a
> timestamp *preceding* the frame's mtime, and `cmp` the installed
> `swaps.skin` against the parked rung. If either fails, the capture is
> **void** — not a result, not a weak result, and not a reason to tune.

**Defect 2 — §7's frame spec was not enforceable after the fact.** "Sun LOW and
BEHIND the character" is stated, but nothing in the shot record captures the
sun's bearing, so a frontally lit frame (which both of these are: bright desert
noon, faces lit) is indistinguishable from a correctly framed one in the
archive. §11 requires the shot record to name the pose.

### 10.6 The five hypotheses, and what the frames rule in or out

The hypotheses put to this session — (a) head backfaces absent while clothing
backfaces exist, (b) wrong sun sign, (c) wrong origin/space, (d) tmax too
short, (e) class gate excludes head skin — are weighed here against the pixels.

| # | hypothesis | what these frames rule in | what they rule out |
|---|---|---|---|
| a | head not a closed manifold; the blue torso is a clothing inner surface | **nothing** | **nothing** |
| b | S is not the sunward vector | **nothing** | **nothing** |
| c | origin offset applied when `98` §15 says none should be | **nothing** — but this one is already settled **statically**: `dev/verify_earglow_rq.py` asserts the query's origin operand is literally the sun NEE trace's own `%2830`, and it **passes on the installed bytes**. No offset exists to be wrong | — |
| d | 18 mm < ear/nose thickness, or tmin 1.5 mm rejects a thin far wall | **nothing** | **nothing** |
| e | face is a different material class from body skin | **nothing** | **nothing** |

Four of the five are **untouched** by any measurement in existence. That is the
honest state, and it is why §11 does not build discriminators yet.

### 10.7 Deploy check (clean — the rungs are shootable today)

| rung | repo vs parked | content sha | `101` §6 says |
|---|---|---|---|
| `earglow-rq-ctl` | **0 diffs** | `4dc824ca77d95feb` | `4dc824ca77d95feb` ✓ |
| `earglow-rq-hit` | **0 diffs** | `737f37a613022455` | `737f37a613022455` ✓ |
| `earglow-rq` | **0 diffs** | `2130f9f0b69c8527` | `2130f9f0b69c8527` ✓ |
| `earglow-rq-hi` | **0 diffs** | `90fa5762820c82ac` | `90fa5762820c82ac` ✓ |

`ptq_sha` on all four parked sets is `55ed4e5c6884ab71`, equal to the currently
installed set's, so `sync_settings.sh` will **not** refuse them on a
mismatch — the rungs were not silently skipped. Live CET `init.lua` ==
repo `init.lua` == `release/game/…/init.lua`, and all four selector rows
(`init.lua` 414–417) are present.

`dev/verify_earglow_rq.py` re-run against the **installed** bytes, not the
build outputs:

```
-hit   : 10 permutations, 25 painted writes, mode=hit,  flags=545, tmin=0.0015, tmax=0.018 -> ALL PASS
-rq    : 10 permutations, 25 painted writes, mode=glow, flags=545, tmin=0.0015, tmax=0.018 -> ALL PASS
-hi    : 10 permutations, 25 painted writes, mode=glow, flags=545, tmin=0.0015, tmax=0.018 -> ALL PASS
negative control (12 base reference modules carry no ray query)              -> ALL PASS
```

Nothing is wrong with the build. The only thing missing is a launch.

---

## 11. Pre-registration — the three discriminators (NOT BUILT, and why)

Three diagnostics were specified this session to separate the causes of an
all-red `-hit` map. **They are deliberately not built.** §10.6 is the reason:
an all-red `-hit` map **has not been observed**. Building three rungs to
discriminate between five explanations of a failure nobody has seen inverts
this track's own discipline — §4 says *"shoot `-hit` first"* and §7 says
*"STOP, do not tune"* — and it would put three more rows in a selector that
already carries four unshot ones. `70` W1's whole point was to stop bolting
mechanism onto an unmeasured premise.

What follows is the full pre-registration, so that the build is a short job the
moment `-hit` is on screen and red. **Do not edit this table after a launch —
add a revision section.**

### 11.0 Precondition (§7 row 0, restated — this gates everything below)

`-hit` shot under §7's settings contract, its `skin_sha` `737f37a613022455`
present in `~/callisto_launches.log` at a timestamp **before** the frame's
mtime, the installed `swaps.skin` `cmp`-clean against the parked rung, and the
shot record naming the sun bearing and the pose. **Absent any of these the
capture is void** and nothing below is buildable.

### 11.1 The three rungs

Each is `earglow-rq-hit` with **one** operand changed, flat paint, no transfer,
same splice, same gate, same `k`-free hit map. `-hit` baseline: flags **545**
(`Opaque|CullFrontFacing|SkipAABBs`), tmin **0.0015**, tmax **0.018**,
direction **`%2831` = S**, origin **`%2830` = P**.

| rung | the one change | the question it answers | scale check |
|---|---|---|---|
| `earglow-rq-hit-far` | `tmax` 0.018 → **0.10 m**, cull-front kept | are there **any** backfaces within 10 cm sunward of head skin? | head ≈ 15 cm wide, nose ≈ 3 cm — 10 cm cannot miss a closed head |
| `earglow-rq-hit-nocull` | flags 545 → **517** (`Opaque|SkipAABBs`, no culling), tmax kept 0.018 | does **anything at all** sit within 18 mm sunward? | if this commits where cull-front missed, the wall exists but is wound **front-facing** — inverted normals — and the fix is cull-**back** or no cull |
| `earglow-rq-hit-back` | direction **−S** with flags → **529** (cull-**BACK**) , tmax kept 0.018 | is the sunward S the right vector at all? v1–v4's reversed segment as a cross-check | if this paints ears while `-hit` did not, S's **sign** is the suspect |

**Structural caveat on `-hit-back`, recorded before it is built.** The other two
are genuinely one-constant edits and the "exactly one constant or one operand
differs per module vs `-hit`" rule is provable byte-for-byte on them. `-hit-back`
is **not**: negating a `v3float` direction requires an added `OpFNegate`, so it
is *two* changes (flags 545→529 **and** direction `%2831`→`OpFNegate %2831`) plus
one added instruction. It must be gated as a two-change rung with both changes
enumerated, or the identity gate will be quietly weakened to pass it. Do not
pretend it is a one-operand diff.

Note also that flags **517** and **529** are already `dev/build_earglow_rq.sh`
gate-7 **decoys** — deliberately built and rejected. Turning either into a
shipping rung means the decoy for that value must be re-pointed (e.g. 513) or
gate 7 will reject the real rung. This is a trap and it is written down here.

### 11.2 Gates (identical in kind to §6, extended by parameters only)

`dev/verify_earglow_rq.py` already takes `--flags`, `--tmin`, `--tmax` and
`--mode hit`, so **no new verifier code path is needed**:

```
python3 dev/verify_earglow_rq.py <rung> --base <ctl> --mode hit --flags 545 --tmax 0.10
python3 dev/verify_earglow_rq.py <rung> --base <ctl> --mode hit --flags 517
python3 dev/verify_earglow_rq.py <rung> --base <ctl> --mode hit --flags 529   # + the -S assertion, which IS new
```

The patcher does need a new front end (`dev/patch_earglow_rq.py` is not to be
edited): a `dev/patch_earglow_rq_diag.py` that imports it and parameterises
flags / tmax / direction. Everything else stands: `spirv-val --target-env
vulkan1.4`, k=0 identity against `-ctl`, the 81 non-reference modules
cmp-verbatim, the byte-level one-operand proof vs `-hit`, re-pointed decoys,
`dev/selftest_earglow_rq.sh` through the real layer, `make install`, `cmp`
installed vs outputs and live CET `init.lua` vs repo, and selector rows.

### 11.3 Settings contract

Identical to §7, restated so this section is readable alone: `ser = class`,
`shadowset = full-shadow`, `ptq` matching the parked `ptq_sha`, **RR off**,
path tracing on, photo mode, camera still, and **sun LOW and BEHIND the
character** with an ear between camera and sun. **State it before the launch;
never reconstruct it from the capture.**

### 11.4 skin_sha per rung

Filled in at build time, **before** any launch, and checked against the launch
log afterwards:

| rung | content sha |
|---|---|
| `earglow-rq-hit-far` | *(to be filled at build)* |
| `earglow-rq-hit-nocull` | *(to be filled at build)* |
| `earglow-rq-hit-back` | *(to be filled at build)* |

### 11.5 The pre-registered outcome table

Same frame as the `-hit` shot, all three rungs plus `-hit` itself:

| far (10 cm) | nocull (18 mm) | back (−S, 18 mm) | conclusion | action |
|---|---|---|---|---|
| paints head | paints head | — | **tmax was the problem.** Backfaces exist; 18 mm is shorter than the sun-path thickness at the pixels that matter | rebuild the glow rung with a larger `tmax` and re-derive §5's transfer table for the new range |
| misses head | misses head | **paints ears** | **S's sign is wrong.** The sunward vector is not sunward at the splice | re-derive `S` at the splice against the NEE trace's own operand; do not touch tmax or the gate |
| misses head | misses head | misses head, **torso stays blue** | **head backfaces are absent.** W1 is dead for the head; the BLAS carries closed manifolds for clothing and not for the head mesh | **STOP.** `70` W1 has no fallback for the head. Fall back to `69` §2 **Track D** — a different brief |
| — | **paints head where `-hit` did not** | — | **inverted winding.** The far wall exists and is wound front-facing | ship cull-**back** (529) or no-cull (517) as the glow rung's flags; the transfer is untouched |
| **paints everything** | **paints everything** | **paints everything** | **tmin.** The 1.5 mm floor is not rejecting the surface's own near geometry, or the origin sits below it | raise `TH_FLOOR`; re-check the origin operand |

Rows are exclusive on the first match, read top to bottom. Any outcome not in
this table is a **new** pre-registration defect and gets recorded as one, the
way §10.5 records the two found today.

---

## 12. The shot — SHOT, and it LEAKS. W1's central claim is false.

Two frames, one session, no settings drift between them:

| frame | rung | launch log | `skin_sha` | file |
|---|---|---|---|---|
| A | `earglow-rq-hit` | 22:44:45 | `737f37a613022455` | `a-b-testing/earglow-rq/A-hit-224607.png` |
| B | **`earglow-rq-hi`** | 22:49:01 | `90fa5762820c82ac` | `a-b-testing/earglow-rq/B-hi-225122.png` |

Record it plainly: **B is the `-hi` rung, not `-rq`.** The middle rung of the
ladder was never put on screen. Everything below is `-hi` (wide 6.0, wrap 0.5)
against `-hit`, and `-rq`'s own transfer is *softer*, not different in kind.

The user's verdict, verbatim:

> Its the same edge case issue as before. The far side of the head is glowing
> at the hairline, underneath her clothes, wrong side of her ear. Side closest
> to the sun isnt glowing any brighter. Eyelid in shaded side of face is glowing

### 12.1 the frames are comparable

Both frames measured at full resolution (2560×1440, sRGB PNG), each region
aligned independently on the **blue** channel — the glow's blue contribution is
~8× smaller than its red (§5), so blue is the closest thing to an unpainted
channel the frame has. Residuals after alignment are 2–8 counts on skin, with
shifts of `dy 0, dx +1..+4`; a pose difference of ~3 px between two separate
photo-mode sessions is exactly that size.

Three non-skin controls give the between-frame exposure difference:

| control | B/A gain, R G B |
|---|---|
| desert ground | 1.011 1.011 1.011 |
| sky | 1.027 1.025 1.026 |
| jacket fabric (lit cloth) | 1.021 1.017 1.018 |

Achromatic and ≤3 %. On skin at level 100 that is worth **+2 counts**. Every
number below is 5–40× that, so the deltas are the rung.

### 12.2 where the query committed — the measurement

`Δ = B(−hi) − A(−hit)`, mean over the box, sRGB counts:

| region | A (R G B) | B (R G B) | Δ (R G B) | ΔR/ΔG | ΔR/ΔB |
|---|---|---|---|---|---|
| **lower eyelid, SHADED side** | 72.7 49.0 34.4 | 124.1 69.3 37.1 | **+51.4 +20.2 +2.7** | 2.54 | 18.9 |
| **cheek, shaded** | 101.6 65.4 49.7 | 144.9 85.9 53.5 | **+43.3 +20.5 +3.7** | 2.11 | 11.6 |
| **temple, far side** | 93.3 66.1 50.3 | 136.3 95.0 59.0 | **+43.0 +29.0 +8.7** | 1.48 | 4.9 |
| lower eyelid, lit side | 117.9 75.1 52.4 | 158.7 93.3 55.6 | +40.8 +18.1 +3.2 | 2.25 | 12.7 |
| **scalp/hair boundary, far side** | 44.3 37.2 16.6 | 83.0 59.0 23.4 | **+38.7 +21.9 +6.8** | 1.77 | 5.7 |
| chin | 129.4 79.5 49.6 | 149.2 90.6 51.5 | +19.8 +11.1 +1.9 | 1.79 | 10.4 |
| nose tip | 113.7 69.3 46.1 | 130.1 77.4 46.7 | +16.3 +8.1 +0.6 | 2.02 | 26.1 |
| cheek, SUNLIT | 204.8 157.8 123.2 | 220.6 169.4 128.9 | +15.8 +11.6 +5.7 | 1.36 | 2.8 |
| **neck, under the jaw/collar** | 142.7 84.1 48.0 | 157.9 94.2 49.6 | **+15.2 +10.1 +1.7** | 1.51 | 9.2 |
| **ear, FAR side (the back of it)** | 108.4 60.9 40.3 | 123.6 73.6 43.9 | **+15.2 +12.7 +3.5** | 1.20 | 4.3 |
| forehead centre (lit) | 162.7 111.2 83.3 | 177.5 118.9 84.0 | +14.8 +7.6 +0.7 | 1.94 | 21.1 |
| upper lip / philtrum | 121.8 74.5 60.1 | 134.3 79.4 60.4 | +12.5 +4.9 +0.3 | 2.56 | 41.7 |
| **ear, SUN side** | 170.0 114.5 80.0 | 176.6 121.0 82.9 | **+6.6 +6.4 +2.9** | 1.02 | 2.3 |
| chest, inside the open jacket | 160.2 110.6 79.7 | 161.1 115.6 81.8 | +0.9 +5.0 +2.1 | 0.18 | 0.4 |

(The forehead hairline box wants an alignment beyond the ±20 px search — hair
moved between sessions — so its Δ of +76.7 is quoted only for its sign. The
scalp/hair boundary box, residual 7.8 at zero vertical shift, is the number.)

Four things fall straight out of that table and all four are bad:

1. **The ear is nearly the weakest region on the head.** +15.2 R on its far
   side, +6.6 R on its sun side, against +51.4 at a shaded eyelid and +43.3 on
   a shaded cheek. The feature is named for the one place it barely fires.
2. **The sun side is not brighter than the far side.** The ear's sun side gains
   less than its back (+6.6 vs +15.2), and the sun-side gain is chromatically
   flat (ΔR/ΔB 2.3) where the shaded gains are strongly red (ΔR/ΔB 9–26). The
   user saw this and named it: *"Side closest to the sun isnt glowing any
   brighter."*
3. **The gate opened on things that are not thin flesh** — the shaded eyelid,
   the neck under the jaw and collar, the scalp under hair.
4. **Lit skin gained too** (+14.8 forehead, +15.8 sunlit cheek), roughly a
   third of the shaded gains and without their sharp structure. Two candidates,
   not separated by this capture: the denoiser/ReSTIR spatial filter smearing a
   very strong shaded-side term across the face, and second-bounce GI picking
   the added radiance up. It is **not** exposure (§12.1) and it is **not** a
   3 px pose shift (that is worth ~2 counts, not 15).

Where the query committed, stated as the frame shows it: **on essentially the
whole sun-averted side of the head**, hardest at the lower eyelids, the shaded
cheek and temple, the scalp/hair boundary and the neck inside the collar; and
barely on the ear.

### 12.3 the `-hit` diagnostic could not have been read, and that is my defect

`-hit` was shot first and showed nothing, and §3's claim that the diagnostic
**adds** is correct — the shipped bytes are an `OpFAdd`:

```
%2860 = OpSelect %float %2859 %float_3_20000005 %float_n0
%2861 = OpSelect %float %2857 %float_n0 %2860
%2862 = OpLoad %float %1246
%2863 = OpFAdd %float %2862 %2861
        OpStore %1246 %2863
```

So it is not `98` §12.4's multiply-on-lit-skin failure. It is the **units**
failure standing next to it, and it is worse because §3 argued the operator
question and never asked the magnitude question:

- `-hit` adds a bare **3.2** to the radiance accumulator.
- `-hi` adds `k · T(t) · wrap · S`, whose peak is `0.198 · S` with `S` the sun
  radiance at that pixel.
- `-hi` moved shaded skin by 40–50 sRGB counts. For `-hit`'s flat 3.2 to be
  equally visible you would need `0.198 · S ≈ 3.2`, i.e. **S ≈ 16**. Daylight
  sun radiance in this path tracer is orders above that.

A diagnostic whose paint is fixed in absolute radiance is unreadable against a
sun-lit surface *whatever* operator it uses. **Rule for every hit map from here:
scale the paint by the same radiance the feature scales by.** `earglow-rq2-hit`
does exactly this (`DIAG_RGB × sunRadiance`, then the same `NMin` clamp), and
`build_earglow_rq2.sh` gate 3 fails the build if the flag saying so is absent.

### 12.4 the diagnosis: W1's central claim is false, and the gate did not vanish

The gate did **what it says on the tin**. It opens only on skin facing away
from the sun. In a front-lit frame, the skin facing away from the sun is: the
far hairline, the skin under the collar, the back of the ear, and a shaded
eyelid. On exactly those pixels the sunward ray committed a backface within
18 mm — and that backface **is not the far wall of flesh**:

| where it fired | what the first sunward backface actually was |
|---|---|
| scalp / hairline | **hair cards lying on the scalp** — a card 1–3 mm off the skin presents a backface at 1.5–18 mm as readily as an earlobe |
| neck and chest under the collar | the **inner surface of the clothing** — the jacket and shirt are closed shells and their inside is a backface a few mm from the skin |
| shaded eyelid | the **eyeball** behind it — sclera at ~2–4 mm, and it is a closed sphere |
| shaded cheek | the **oral cavity / teeth** shell behind ~10 mm of cheek |
| the ear (weakly, correctly) | the actual far wall of the pinna |

> **W1's central claim — "the first backface within 18 mm sunward is the
> sun-side wall of flesh" — is false wherever another mesh sits within 18 mm
> sunward of the skin.** Hair cards, the inside of clothing and the eyeball all
> satisfy the geometric test and none of them is flesh.

That is the same class of false positive `63`–`69` fought, arriving through a
different door. **The consistency gate was removed for exactly this class of
false positive, and W1 did not dissolve it; it moved it.** §1's table is wrong
on its own terms: the min-t floor and the 18 mm ceiling reject a *thin card in
front of the camera*, and neither of them says anything about a *foreign mesh
sunward of the skin*, which is the case that actually occurs on a head.

Two of the user's four observations are, however, **the design working**, and
saying otherwise would be dishonest:

- **"wrong side of her ear"** — the back of the ear glowing *is* W1. Sunward
  from the back of the pinna is 2–4 mm of flesh and then air; that is the
  thinnest sun path on the head and the transfer is supposed to be brightest
  there. On a front-lit head the ear's back faces away from the sun and its
  front faces the camera, so the glow lands where the user cannot accept it.
- **"side closest to the sun isnt glowing any brighter"** — also the design.
  The wrap term is `smoothstep(0, wrap, −N·L)`: it is **zero** wherever the
  surface faces the sun. Sun-facing skin is lit directly and gets no transmission
  term at all, by construction.

Both of those stop being complaints in a **backlit** frame, where the sun is
behind the head and the sun-averted skin *is* the skin pointing at the camera.
§7 never said so. It does now (see the correction note there): **this feature
cannot be judged in a front-lit frame.**

### 12.5 the fix, and the one variable it changes

Keep W1's ray exactly as it is. Add an **instance-match** gate:

- **Query A** — `98`'s primary-surface query, re-derived here rather than
  imported: origin `(0,0,0)` (the TLAS is camera-relative, `98` §15), direction
  the module's own reconstructed view ray, flags **517**
  (`Opaque | TerminateOnFirstHit | SkipAABBs`), `tmax = |P|·1.001 + 1e-4`, and
  the committed hit accepted only inside the ±0.1 % bracket `t ≥ |P|·0.999`.
  Read `OpRayQueryGetIntersectionInstanceIdKHR`. This is the **primary
  surface's** instance — the thing the pixel actually is.
- **Query B** — the sunward cull-front thickness query, unchanged: flags 545,
  `tmin` 1.5 mm, `tmax` 18 mm, committed closest, `T` for the transfer, and now
  also its `InstanceId`.
- **Accept iff `A` committed AND `B` committed AND `A.InstanceId == B.InstanceId`.**

No threshold, no depth comparison, no tuning knob. **The assumption, stated so
the diagnostic can kill it: the body's skin is one TLAS instance, and hair,
clothing and eyes are others.** If that is false — if hair shares the body
instance — `-rq2-hit` will paint the hairline blue and the design is dead in
this form; §13 says what would separate it. Reading query A also answers a
second question for free: **if A misses, the pixel is sky and is not skin.**

`98` §13 is what makes this legal: `InstanceId` is stable *within* one frame
and only unstable *across* frames. Both queries run in the same invocation.

Cost: one extra ray query. Both queries share the same `OpSelect(gate, 39, 0)`
cull mask, so a non-skin pixel pays two **free misses** (mask 0) and no branch
— zero added control flow, same as §2.

### 12.6 what is now known that was not

1. Backfaces **do** exist within 18 mm sunward of a great deal of head skin —
   §11's "the BLAS carries no closed head manifold" branch is refuted.
2. `T` is being read and the Beer–Lambert transfer is running: the shaded-skin
   gains are strongly red (ΔR/ΔG 1.8–2.6, ΔR/ΔB 9–26), which is the dual-lobe
   signature of §5 at `t ≈ 4–8 mm`, not a flat tint.
3. The layer, the overlay, the gate, the wrap and the write site are all
   correct. **Only the identity of the committed surface was never checked.**

---

## 13. `rq2` — PRE-REGISTERED before the screen. Read this, then launch.

Written and committed to the repo **before** any `rq2` frame exists. If the
outcome is not in the table, it is a new pre-registration defect and gets
recorded as one, the way §10.5, §12.3 and §14.3 record the four found so far.

> **SUPERSEDED BY §16.** `earglow-rq2` was shot backlit at 23:46:49 (§15) and
> the ears and noses PASSED — this table's first row. What it also showed is a
> different defect (the glow bleeds through the shaded front of the face), so
> the live pre-registration is now §16's, for `earglow-rq3`. This table stands
> as the record of what `rq2` was judged against.
>
> **STILL UN-SHOT AS WRITTEN, and it was overdue (§14).** `earglow-rq2-hit` was put on screen
> at 23:34:12 — in the **front-lit** pose of §12, not the frame below. That
> makes **three front-lit frames shot against a contract that says backlit**
> (§10, §12, §14). §14 reads what that frame could tell us; it cannot decide
> this table. **The next frame must have the sun BEHIND the head, low, with the
> ear exposed** — this character's sun-averted ear is partly under hair, so the
> pose has to clear it, and a shot where hair covers the pinna is void for the
> same reason a front-lit one is.

### 13.1 the frame — this is not optional any more

§12.4: a front-lit head puts every pixel this feature can paint on the side
away from the camera. The `-rq` shot was un-judgeable for that reason before
the leak was even reached.

- **BACKLIT.** Sun **low and BEHIND the head**, camera on the **sun side** of
  the ear, so the pinna is between the camera and the sun.
- Confirm the frame is backlit *before* shooting: the hair should carry a rim,
  the face should be in its own shadow, and the ear should already read warm on
  the **control**.
- Photo mode, no depth of field, no colour grade change between rungs.
- Both rungs from **one session**, same pose, same time of day, same weather.

### 13.2 settings contract — state it, do not reconstruct it afterwards

- `ser = class`, `shadowset = full-shadow` — required; the splice site is the
  sun NEE trace.
- `ptq` unchanged from what the rungs were built against (MANIFEST carries it).
- Russian roulette **OFF**.
- Same `skinspec` ladder position for every frame; no other rung swapped in
  between.
- `earglow-rq-ctl` is the control and is byte-identical to the standing
  default, so a control frame is also a frame of the shipped image.

### 13.3 shoot order

1. `earglow-rq2-hit` — **first**, and read it before anything else.
2. `earglow-rq2` — the same frame, k = 0.22.
3. `earglow-rq-ctl` — the control, if anything at all is ambiguous.
4. `earglow-rq2-hi` only if `-rq2` reads as too weak.

`earglow-rq2-hit` paints, additively and scaled by the sun radiance so it is
readable on lit skin:

| paint | meaning |
|---|---|
| **BLUE** | query B committed a backface within 18 mm **and it is the same instance as the primary surface** — accepted |
| **RED** | query B committed, but on a **different instance** — rejected (hair, clothing, an eyeball) |
| nothing | query B missed, or the gate is shut (sun-facing skin, non-skin pixel, sky) |

### 13.4 the interpretation table

Rows are exclusive, read top to bottom, first match wins.

| `-rq2-hit` shows | conclusion | action |
|---|---|---|
| **BLUE on the ear rim and the nose, and nowhere else** | **PASS.** The instance-match gate does what §12.5 claims | go to `-rq2`; the glow must land in the same places and nowhere else |
| **RED at the hairline, under the collar and on the eyelid**, blue on the ear rim | **PASS, and the diagnosis of §12.4 is confirmed on screen.** The gate is rejecting foreign meshes exactly where the `-rq` leak was | go to `-rq2` |
| **BLUE at the hairline** (or under the collar, or on the eyelid) | **the assumption in §12.5 is false**: hair/clothing/eyes share the body's TLAS instance. Instance identity cannot separate them | do **not** tune. Build the `InstanceCustomIndex` read (`98` proved the field is populated) and, if that is also shared, the `GeometryIndex` — the separation then has to be *within* the instance |
| **nothing anywhere on the head** | **query A is failing**, not query B — `-rq` proved B commits. Either the ±0.1 % bracket rejects the primary hit, or the view-ray reconstruction is wrong in this permutation | re-shoot `98`'s `hunt-rayq-p` in the same frame; if it paints, the bracket is the fault, and it is the only number to touch |
| **RED everywhere, including the ear rim** | the two queries never agree — most likely they are hitting **different instances of the same body** (a separate head/face instance from the body), which is a real possibility this build does not test | record it; the fix is a per-frame instance-set, not a compare, and that is a different brief |
| **BLUE on the whole head including thick regions** | the 18 mm ceiling is not doing its job; `t` is not being read from query B | re-derive the committed-`T` operand |

Then, and only then, `earglow-rq2`:

| `-rq2` shows | conclusion | action |
|---|---|---|
| glow on the **ear rim and nose only**, brightening as the sun goes lower behind the head | **PASS.** Ship it as an optional rung; do not flip the default | park it, record `k = 0.22` untouched (`70`/`71`), and offer `-rq2-hi` as the A/B |
| glow in the right places but **too weak to see** | the transfer, not the gate | `-rq2-hi` is already built and parked for exactly this; it is one selector row away |
| glow in the right places but **too strong / waxy** | k, which is the one number `70`/`71` forbid tuning without a new brief | record it and stop; do not tune k inside this brief |
| glow where `-rq2-hit` painted **red** | the gate is not dominating the transfer — a build defect, not a design one | `verify_earglow_rq2.py`'s domination check should have caught it; that check is then vacuous and is the first thing to fix |

### 13.5 what a pass does not prove

A pass proves the *committed surface* is the same instance as the primary
surface. It does not prove that surface is the far wall of **flesh** — a closed
mesh could still be some other part of the same instance (an interior tooth
shell, say, if teeth are merged into the body). If `-rq2` passes but the glow
still appears somewhere anatomically impossible, that is the remaining hole and
it needs geometry-level identity, not instance-level.

---

## 14. `rq2-hit` shot — in the WRONG FRAME. Red is the fix working; no blue is expected.

**Read this first: the frame is front-lit, and §13.1 required a backlit one.**
`photomode_02092026_234004.png` is the *same pose as §12* — sun front-left, the
camera on the sun side of the face — not the sun-behind-the-head frame this
diagnostic was pre-registered against. That is now **three front-lit frames
shot against a contract that says backlit** (§10's void pair, §12's `-hit`/`-hi`
pair, and this one). Nothing below overturns §13; the pre-registration stands
untouched and still needs its frame.

| frame | rung | launch log | `skin_sha` | file |
|---|---|---|---|---|
| D | `earglow-rq2-hit` | 23:34:12 | `9cdea033376b82ad` | `a-b-testing/earglow-rq/D-rq2hit-234004.png` |
| E | derived | — | — | `E-rq2hit-classmap.png` (red/blue classification over a desaturated D) |

User verdict, verbatim: *"Red and blue still on the wrong side of face?"*

### 14.1 the pair is pixel-registered — this is the cleanest measurement yet

D aligns to §12's `A` (`earglow-rq-hit`, whose paint was measured in §12.3 to be
invisible, making it a de-facto control) at **`dy 0, dx 0`**, residual 2.8 on the
face and 0.7 on the desert. Exposure gains D/A: ground **1.000 1.000 1.001**,
sky 1.002 0.998 0.997, jacket 1.007 1.002 1.001. The desert-ground control's
mean Δ is `[-0.0 +0.0 +0.0]`. **Everything measured on skin below is the rung
and nothing else** — no pose term, no exposure term, unlike the §12 pair.

### 14.2 the classifier, and why an absolute threshold was the wrong tool

The coordinator's absolute red threshold caught warm sunlit skin. The paints are
known exactly — `(0.32, 0, 0)·S` and `(0, 0.04, 0.32)·S` — so classify by
**signature**, not by level:

- RED: `ΔR > 10` and `|ΔG| < 0.25·ΔR` and `|ΔB| < 0.25·ΔR`.
- BLUE: `ΔB > 10`, `ΔG > 0`, `4 < ΔB/ΔG < 20` (the paint's ratio is 8), `|ΔR| < 0.25·ΔB`.

Non-vacuity: run the same classifier on §12's `-hi` glow (`B − A`), which is
*warm* but is a Beer–Lambert transfer, not flat paint — it matches red on 1.4 %
of the box against this frame's 35 %; and on `A − A` it matches **0**.

Head + upper-torso box (707 000 px):

| | strict signature | loose (`Δ>6`, 3× separation) |
|---|---|---|
| RED | **248 813 px, 35.2 %** | 290 855 px, 41.1 % |
| BLUE | **9 px, 0.0013 %** | 292 px, 0.04 % |

The 292 loose "blue" pixels are mostly not paint: the largest cluster (39 px
beside the nose) has `ΔB/ΔG = 1.57` and `ΔR = +33`, which is a specular/nose-ring
difference, not the 1 : 8 signature. Under the strict test only **9 pixels**
survive, in 8 components of ≤2 px — and every one of them sits at
`y 709–733, x 1173–1243`: the **nostril wall / septum**. See §14.4.

### 14.3 where the red is

Mean `Δ = D − A` per region, and the fraction of the box the loose red test
claims:

| region | Δ (R G B) | red % |
|---|---|---|
| hairline band, far side | **+124.1 +17.1 +7.7** | 99.7 |
| lower eyelid crease, shaded | +61.6 +5.9 +0.0 | 97.1 |
| cheek, shaded | +58.7 +4.2 −1.3 | 100.0 |
| temple, far side | +57.2 +3.8 −3.8 | 79.0 |
| lower eyelid crease, lit | +52.0 +4.5 −1.6 | 99.3 |
| neck under jaw/collar | +25.7 +2.3 −1.5 | 99.6 |
| neck, right side | +25.7 +6.2 +4.2 | 74.8 |
| upper lip | +24.3 +3.0 +2.0 | 78.4 |
| ear, far side | +21.0 +6.6 +6.2 | 58.8 |
| cheek, sunlit | +20.8 +0.7 −0.7 | 95.5 |
| nose tip | +19.6 +4.0 +2.4 | 68.8 |
| nostril wall / septum | +18.5 +6.6 +9.8 | 40.0 |
| ear, sun side | +16.7 +2.6 +0.9 | 77.3 |
| hairline band, sun side | +12.3 +1.2 −0.2 | 74.0 |
| chest inside the open jacket | +9.3 +1.2 −0.4 | 61.5 |
| CONTROL desert ground | −0.0 +0.0 +0.0 | 0.0 |

**Reading 1 — the §12 diagnosis is confirmed on screen.** Red means *query B
committed a backface within 18 mm and it belongs to a different instance than
the primary surface*. It is heaviest exactly where §12 said the `-rq` leak was:
the far hairline band (+124 R, 99.7 % of the box), the temple, the shaded eyelid
crease, under the jaw and collar, the right side of the neck. Those are hair
cards on the scalp, the eyeball behind the lid, the inside of the clothing and
the mouth interior — named in §12.4 as predictions, and now painted red by a
build that was written before the frame existed. **The instance-match gate is
rejecting them.** In `-rq` those same pixels glowed.

Two honest qualifications:

1. **My "sunlit cheek" label was wrong** — see §14.6. That box is *bright*
   (204 R) but it is not sun-facing: the gate is a hard `N·L ≤ 0` step and the
   frame shows it. Of the face's skin pixels **33.9 % are unpainted**, and the
   unpainted 50 px cells sit in a column at `x 1430–1480` — the character's
   left temple and cheek edge, the surfaces actually turned toward the sun,
   at **0.0 % red**. The terminator is in the map. What *is* true is that the
   diagnostic's gate is `class-1 skin AND backlit AND path counter 0` and is
   **not** multiplied by W3's `smoothstep(0, wrap, −N·L)`, so it paints the whole
   backlit hemisphere at full strength where the glow rung feathers the first
   few degrees past the terminator. The map is therefore a modest superset, not
   a different set. It should have been said in §13.3's legend; it is the fourth
   pre-registration defect in this document, and `earglow-rq2-hitw` (§15) is the
   one-variable fix.
2. The **magnitude** ordering of red is mostly the tone curve, not the gate: the
   same linear `0.32·S` add produces a far larger sRGB step on a dark pixel than
   on a bright one. Do not read "+124 at the hairline vs +17 at the sun-side ear"
   as "the gate is 7× more confident there".

### 14.4 no blue is EXPECTED in this frame — it is not a failure of the match gate

Nine pixels of blue on a head is, for practical purposes, none. That is the
correct outcome for a **front-lit** frame and it does not indict the instance
compare:

In front lighting the sun-averted skin is the skin on the far side of the head.
From those points the sunward direction runs **along** the ear and **into** the
skull — the sun path is the long axis of the head, not a 2–4 mm crossing. There
is no same-instance backface within 18 mm, so query B either misses (nothing
painted) or commits on hair/clothing/eye (red). **The 18 mm cap is doing exactly
its job.** The only lighting in which the sun path *across* an ear rim or a
nostril wall is short is **backlit**: sun behind the head, the ray entering the
thin part of the pinna and exiting its far side a few millimetres later.

The nine blue pixels are consistent with that and are the one prediction this
frame could confirm: they are all at the **nostril wall / septum**, the single
place on a front-lit face where a same-instance surface sits within 18 mm
sunward — the far side of the nostril's own wall.

**The alternative this frame cannot exclude.** No blue is also what you would
see if the ear mesh is **not closed on its medial side** — if the pinna merges
into the head with no interior backface at all. In that case a backlit frame
gives no blue on the ear either, and only the nose/nostril wall would ever pass
the gate. The two hypotheses — *"wrong lighting"* and *"the ear is not a closed
manifold"* — make **different predictions in a backlit frame**, which is exactly
what §13's table already discriminates:

| backlit `-rq2-hit` shows | which hypothesis |
|---|---|
| blue on the ear rim and nose | wrong lighting; the design is sound (§13.4 row 1 or 2) |
| red/nothing on the ear, blue only at the nose | the ear is not closed on its medial side; W1 can only ever paint the nose, and that is a different brief |

**§13 is unchanged and still un-shot.** The next frame decides it.

### 14.5 the sign of **S**, settled from the bytes — it is NOT mirrored

The question: does query B's direction operand point *to* the sun, or is it the
light's travel direction (sun → surface), which would make every §12/§14 reading
the mirror image of what it claims? Answered by reading the shipped module, not
the frame. In `swaps.earglow-rq2/1271d3815051da17.rgs_reference_main.spv`:

```
; the module's own sun NEE shadow ray
OpTraceRayKHR %2833 %907 %2827 %911 %911 %904 %2834 %1013 %2835 %1014 %20
;             accel flags mask  sbt  sbt  miss  ORIGIN tmin  DIR  tmax payload
; the spliced query B
OpRayQueryInitializeKHR %1256 %2833 %1232 %2862 %2834 %1234 %2835 %1235
;                       rq    accel flags mask  ORIGIN tmin  DIR  tmax
```

- `%907 = OpConstant 12` = `TerminateOnFirstHit | SkipClosestHitShader`. With
  `tmin 1e-6`, `tmax 10000` and a boolean cull mask, that is a **shadow ray**.
- Query B's origin is **`%2834`** and its direction is **`%2835`** — the *same
  SSA values*, not a negation, not a reconstruction. `%2835` is
  `normalize(%2813..%2815)`, the cone-sampled light vector the shadow ray uses.
- A shadow ray is traced from the surface **toward the light**. Therefore
  **`+S` is the to-sun direction and hypothesis (a), the mirror, is refuted.**
  §12 and §14 stand as written.

The gate is the module's own too: `%2743 = OpDot(N, L)`,
`%2744 = OpFOrdLessThanEqual(%2743, 0)`, and the module itself writes
`%2827 = OpSelect(%2744, 0, 39)` — it zeroes its **own** shadow-ray cull mask
when `%2744` is true. So `%2744` means exactly "this surface faces away from the
light", `dev/patch_earglow.py` names it correctly, and the splice's gate
`%2861 = class1 && %2744 && counter==0` cannot be open on sun-facing skin.

**The lit-cheek verdict (question b): the red there IS the paint, and the box was
mislabelled.** The paint is a binary, pure-red, per-pixel add; a warm shift is
smooth and raises all three channels. Measured on `D − A`:

| box | ΔG/ΔR | ΔB/ΔR | \|ΔR\|<3 | ΔR in 3..10 | ΔR>10 |
|---|---|---|---|---|---|
| bright cheek (ch. left) | **+0.034** | −0.036 | 0.0 % | 1.6 % | **98.4 %** |
| shaded cheek | +0.072 | −0.021 | 0.0 % | 0.0 % | **100.0 %** |
| CONTROL desert ground | — | — | **99.5 %** | 0.2 % | 0.0 % |

and the same test on §12's `-hi` **glow** over the same boxes gives
`ΔG/ΔR +0.95 / +0.48`, `ΔB/ΔR +0.72 / +0.10`, with 25 % of pixels in the
intermediate band — a smooth warm shift, exactly what the paint is not. The
bright cheek is bright from sky and bounce; its normal is still turned away from
a low front-left sun, so the gate is open there and the paint is real.

### 14.6 what is now known that was not

1. Query A commits: if it missed everywhere, `ok` and `rej` would both be false
   and the frame would be blank. 35 % of the head/torso box is red, so the
   primary query, the ±0.1 % bracket and the instance getters all work on the
   real modules at runtime — not just under `spirv-val` and the selftest.
2. The two InstanceIds **disagree** on the great majority of sun-averted skin,
   which is the positive form of §12.4: the committed sunward backface really is
   a foreign mesh there.
3. The diagnostic's paint is now readable on lit skin (§12.3's units fix works):
   it reads at +12 to +124 sRGB counts on skin whose level runs 44–205.

---

## 15. `earglow-rq2-hitw`, and the FIRST BACKLIT SHOT — the ears pass, and the glow bleeds through the front of the face.

### 15.1 `earglow-rq2-hitw` — the diagnostic with the glow's own gate

§14.3's fourth pre-registration defect: `-rq2-hit` is gated on
`class-1 AND backlit AND counter 0` but its flat paint is **not** multiplied by
W3's wrap, so it paints the whole backlit hemisphere while the glow rung feathers
the first few degrees past the terminator. `earglow-rq2-hitw` multiplies the same
flat paint by the **same** `smoothstep(0, 0.35, −N·L)` the `earglow-rq2` rung uses
— one variable, nothing else moved. The wrap is emitted by **one** function in
`dev/patch_earglow_rq2.py` used by both branches, so the diagnostic cannot drift
from the rung it is a map of.

`--mode hitw` is a *mode of the existing verifier*, not a second code path: the
hit-mode checks all still run, plus (i) exactly 1 added `SmoothStep` and 1 added
`OpDot`, (ii) the edge read off **the added SmoothStep's own operand** — checking
merely that a constant `0.35` exists is vacuous, since `0.5` (the `-hi` edge) is
already in every shipped module — and (iii) all three flat paints pass through
that SmoothStep before the sun-radiance scale.

Gate 2 also re-derives `earglow-rq2` and `-rq2-hit` and `cmp`s them against the
parked bytes: hoisting the wrap constant renumbered every later id and silently
changed the shipped `earglow-rq2` on the first attempt. The constant is now
allocated inside each branch in that branch's original order, and the regression
is a build gate.

| rung | content sha | raygen-half |
|---|---|---|
| `earglow-rq2-hitw` | `071875186eeceb6b` | `8afd99d597e4f4dd` |
| `earglow-rq2-hit` (unchanged) | `9cdea033376b82ad` | `b11c0a3d1f435b47` |
| `earglow-rq2` (unchanged) | `c62e024e8725ad21` | `f6323e4f87429529` |
| `earglow-rq2-hi` (unchanged) | `f1bf913060c72c77` | `26210cdb92392035` |

Nine gates green, **14 decoys** rejected (the four new ones: `-rq2-hit` read as
`-hitw`, `-hitw` read as the unwrapped `-hit`, `-hitw` read with the `-hi` edge,
and the wrap-constant vacuity above). Selftest **36/36** (was 34).

### 15.2 the first backlit frame

| frame | rung | launch log | `skin_sha` | file |
|---|---|---|---|---|
| F | `earglow-rq2` | 23:46:49 | `c62e024e8725ad21` | `a-b-testing/earglow-rq/F-rq2-backlit-235113.png` |

**This is a 1254×940 desktop screenshot, not a photo-mode capture**, and it is a
different character from §12/§14. There is **no same-pose control frame**, so
everything below is a single-frame reading: chromaticity against adjacent
unaffected skin *inside the same frame*, not a Δ. It is the first frame that
satisfies §13.1 — sun low behind the head, camera on the shaded face.

User verdict, verbatim:

> shows the effect still bleeding through the front of faces. Faces in shadow
> still get the effect. Otherwise the ears and noses look great. But the sun rays
> are triggering the effect on the wrong side of the face in some contexts.

Measured, RGB means and ratios (glow regions first, then unaffected skin in the
same shadow):

| region | R | G | B | R/G | G/B |
|---|---|---|---|---|---|
| nose bridge / inner canthi (GLOW) | 107.8 | 58.5 | 27.5 | **1.84** | **2.13** |
| left inner canthus (GLOW) | 71.5 | 34.4 | 0.7 | **2.08** | **51.1** |
| lower lip (GLOW) | 68.5 | 41.5 | 19.2 | **1.65** | **2.16** |
| nose tip / nostril wings | 106.4 | 77.7 | 64.6 | 1.37 | 1.20 |
| cheek, shadowed (adjacent) | 92.9 | 60.2 | 42.6 | 1.54 | 1.41 |
| forehead, shadowed | 83.6 | 66.1 | 52.3 | 1.27 | 1.26 |
| chin, shadowed | 57.4 | 44.5 | 29.8 | 1.29 | 1.49 |
| neck, shadowed | 62.2 | 48.2 | 32.8 | 1.29 | 1.47 |
| sunlit ground (background) | 137.8 | 128.9 | 119.2 | 1.07 | 1.08 |

Shadowed skin sits at `R/G ≈ 1.27–1.54`, `G/B ≈ 1.26–1.49`. The glow regions run
`R/G 1.65–2.08` with `G/B` from 2.1 to **51** — blue almost completely absorbed
at the inner canthus. §5's transfer table gives `R/G` 2.05 at `t = 4 mm` and 2.95
at 8 mm, so the glowing pixels are the Beer–Lambert term at a few millimetres,
not a tint.

### 15.3 §13's pass row, honestly recorded

**The ears and noses pass.** That is §13.4's first row — the mechanism does what
`70` W1 said it would, in the lighting `70` W1 requires. The instance-match gate
of §12.5 is doing its job: none of §12's hair-card, collar or eyeball leaks are
in this frame. That much is settled and should not be re-litigated.

The **S-sign** question is closed twice over: §14.5 proved from the bytes that
query B reuses the shadow ray's own direction operand, and this frame proves it
on screen — the sun is *behind* the head and the glow appears on the
**camera-facing, shaded** side. Had the direction been the light's travel vector,
the ray from camera-facing skin would leave into air and nothing could commit.

### 15.4 the diagnosis: the ENTRY point is never tested for sunlight

The glow bleeds through the shaded **front** of the face — the inner eye corners
and upper nose bridge, and the lower lip. Those are not thin flesh. Sunward from
that skin the ray goes *back into the head* and commits a same-instance backface
within 18 mm:

| where it bleeds | the same-instance wall the sunward ray commits |
|---|---|
| inner canthus / nose bridge | the **eye-socket surface behind the inner canthus** |
| upper nose bridge, nostril wings | the **nasal cavity / nostril walls** |
| lower lip | the **inner lip surface of the mouth cavity** |

Every one of them is the same mesh, and every one of them is a few millimetres
away, so the instance gate and the 18 mm cap both pass them. **But the sun never
reaches them: they are interior surfaces.** The build measures a thickness and
assumes the far end of it is lit.

> `70` W1 said this explicitly — *"the vis ray from the exit point still has to
> reach the sun"* — and `101` never built it. Query B answers *"is there a
> same-instance wall within 18 mm along S?"*. It does not answer *"is that wall
> in sunlight?"*, and without the second answer a nasal cavity is
> indistinguishable from an ear rim.

The same missing test explains the second half of the verdict, **"faces in shadow
still get the effect"**: if a wall, a vehicle or another character stands between
the exit point and the sun, nothing in this build notices. The exit point's
visibility of the sun is never queried, so a fully shadowed head transmits as
brightly as a sunlit one.

This is not a new class of error. It is the *third* time the same shape of
mistake has been made in this document, and it is worth naming: **a geometric
test was substituted for a lighting test.**

1. `63`–`69`: "a surface within 2 cm behind me" substituted for "flesh".
2. `101` §12: "a backface within 18 mm sunward" substituted for "the far wall of
   flesh" — fixed by the instance compare.
3. `101` §15: "a same-instance wall within 18 mm sunward" substituted for
   "**a lit** far wall" — the fix is §15.5.

### 15.5 the fix: query C, sun visibility from the exit point

One variable from `rq2`. Keep queries A and B exactly as they are, and add:

- **Query C** — origin `P + (t_B + push)·S`, i.e. the committed exit point
  pushed a further ~1 mm *along* S so it starts in air past the backface;
  direction `S` (the same `%2835`); `tmin` ~1 mm; `tmax` the module's own sun
  shadow-ray `tmax` where one is readable (`%1014 = 10000`), else 100 m; flags
  **517** (`Opaque | TerminateOnFirstHit | SkipAABBs`) — **no culling**, because
  any geometry at all occludes the sun; cull mask **re-derived from the module's
  own sun shadow ray** so C sees exactly the occluders the sun does.
- **Accept iff `B` commits same-instance AND `C` MISSES.**

A rejected pixel costs three queries and no branch: all three share the
`OpSelect(gate, 39, 0)` mask, so a shut gate is three free misses.

`earglow-rq3` is that build. §16 pre-registers its shoot.

---

## 16. `earglow-rq3` — built, gated, parked. PRE-REGISTERED before the screen.

Written before any `rq3` frame exists.

### 16.1 what was built

Three queries, one added variable over `rq2`:

| | flags | origin | direction | tmin | tmax | read |
|---|---|---|---|---|---|---|
| A | 517 | zero triple (camera) | the module's view ray | \|P\|·0.999 | \|P\|·1.001 + 1e-4 | InstanceId |
| B | 545 | the NEE trace's own `P` | the NEE trace's own `S` | 1.5 mm | 18 mm | InstanceId, committed `T` |
| **C** | **517** | **`P + (t_B + 1 mm)·S`** | the same `S` | 1 mm | **the module's own sun shadow-ray tmax (10000)** | commit only |

`accept ⇔ A committed ∧ B committed ∧ A.InstanceId == B.InstanceId ∧ C MISSED.`

C's cull mask is the shared `OpSelect(gate, 39, 0)`. The patcher **asserts**, per
module, that the module's own sun shadow-ray mask is `OpSelect(backlit, 0, 39)` —
arms `[0, 39]` — so 39 is literally the sun's own occluder set and C sees exactly
what the sun sees. A module with a different mask fails the build rather than
silently testing a different set of occluders.

C carries **no culling bit**: any geometry at all occludes the sun, and winding
is irrelevant to that question. The 1 mm push is what puts C's origin in air past
the backface B just committed; without it C's first hit is that same wall.

Cost: three queries, **no branch**. All three share the one gate mask, so a
non-skin or sun-facing pixel pays three free misses.

| rung | content sha | raygen-half |
|---|---|---|
| `earglow-rq3-hit` | `eed4c2ca8f71f5d3` | `609a822302ab12ec` |
| `earglow-rq3` | `359060c26c8c7367` | `9852b0bbf6417842` |
| `earglow-rq3-hi` | `c4b61c01e1b73990` | `9ed134997c15dc0f` |

Control stays `earglow-rq-ctl` (byte-identical to the base). Nine gates green;
census demands 30 Initialize / 30 Proceed / **20** InstanceId / 10 committed-T /
0 added traces per rung — C's identity is deliberately never read, because C
answers only *"is anything in the way"*. Eleven decoys rejected, including
`--decoy noc` (C traced but never consulted — i.e. `rq2`), `--decoy cullfront`
(C would miss the very occluder it exists to find) and `--decoy invert` (accept
when C **hits**: it would light exactly the occluded pixels). `earglow-rq2` read
as an `rq3` rung is rejected on all 10 permutations. Selftest **42/42** (was 36);
the synthetic raygen now carries all three live query objects and its RT pipeline
links on the 4070.

`earglow-rq3-hit` carries the glow's **full** gate, wrap included — §14.3's
defect is not repeated:

| paint | meaning |
|---|---|
| **BLUE** | B committed a same-instance wall within 18 mm **and C missed**: the exit point can see the sun. Real transmission. |
| **RED** | B committed a same-instance wall **but C hit**: an interior surface (eye socket, nasal cavity, inner lip) or a genuine occluder between the exit point and the sun. |
| nothing | B missed, the wall was a foreign instance, or the gate is shut. |

### 16.2 the frame

**The same backlit frame as §15** — sun low behind the head, camera on the shaded
face, the ear clear of hair. `-rq3-hit` first, `-rq3` in the same frame. The
settings contract of §13.2 is unchanged. And add one shot this time: **a face
standing in the shadow of something** (a wall, a vehicle, another character), in
the same frame or the next, because half the verdict §15 answers is about that.

### 16.3 the interpretation table

Rows exclusive, first match wins.

| `-rq3-hit` shows | conclusion | action |
|---|---|---|
| **BLUE on the ear rim, the nostril wings and the lip edge where the sun actually reaches behind them; RED at the inner eye corners, the nose bridge and the mouth interior** | **PASS.** C is separating lit exit points from interior walls exactly as §15.4 predicts | go to `-rq3` |
| blue still at the **inner eye corners** | C is starting **inside the head**: either the 1 mm push does not clear the backface, or `tmin` swallows it | raise the push (it is the only number to touch) and re-shoot; do not touch B |
| the **ear rim is now RED** | C is hitting something from the ear's exit point. Two cases and they are not the same: the ear's **own far side** (push too small — fix as above), or **hair cards behind the ear** (a real occluder, in which case red is CORRECT and the ear is genuinely shadowed) | shoot the same head with the ear clear of hair before touching anything |
| **nothing anywhere** | C always hits: the mask is wrong for C, or `tmax` is, or the origin is inside geometry | re-derive C's mask against the module's own shadow ray — the build asserts arms `[0, 39]`, so a failure here means the *sun's* mask is not the occluder set |
| RED **everywhere including the ear rim in open sun** | the push is going the wrong way along S, or `S` is not the to-sun direction — but §14.5 settled that from the bytes, so treat this as a new defect | record it as a pre-registration defect and stop |

Then `-rq3`:

| `-rq3` shows | conclusion | action |
|---|---|---|
| glow on **ears and noses only**, and **a face in another object's shadow shows nothing** | **PASS.** Both halves of §15's verdict are answered | park it as the optional rung; k stays 0.22 (`70`/`71`); offer `-rq3-hi` as the A/B |
| ears and noses right, but a shadowed face **still glows** | C is not seeing the occluder — a mask or `tmax` problem, not a design one | compare against `-rq3-hit`'s red on that face; if it is blue there, C's ray is not reaching the occluder |
| the glow is **gone everywhere**, including ear rims in open sun | C is over-rejecting | `-rq3-hit` says which: all-red means C hits, nothing means the gate shut |
| right places, too weak | the transfer | `-rq3-hi` is parked for exactly this |

### 16.4 what a `rq3` pass would still not prove

C tests the exit point's visibility along **one** sampled sun direction, the same
cone sample the module's own shadow ray uses. It says nothing about partial
occlusion, and it does not make the transfer physically calibrated. It closes
*"is the far wall lit"*, and that is all it closes.

---

## 17. SHOT 2026-09-03 — `rq3` is KEPT and **was** the shipped default

**Amended 2026-09-03 ~01:20:** `earglow-rq3` was the shipped default from
**00:38 to ~01:20**. It was superseded by
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense`
(`100` §13), which **contains it byte for byte** — the 83 unpatched files are
identical and the 10 patched `rgs_reference_main` carry both splices. Nothing
below is retracted; the rung is still kept and still shipping, inside the stack.

### 17.1 the launches, from the log

```
2026-09-03T00:35:14-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73
  skin=on skinspec=earglow-rq3-hit skin_sha=eed4c2ca8f71f5d3 tier=on cache=cleared
  payload=bab62bc94428c1c5
2026-09-03T00:38:40-05:00 … skinspec=earglow-rq3 skin_sha=359060c26c8c7367
  tier=on cache=cleared payload=66cb3a045e17bd0a
```

Both `skin_sha` values are the §16.1 shas, pre-registered before either launch,
so row 0's serving proof is satisfied for both rungs: the bytes on screen were
the bytes in this document. `ser=class:in-skin` and `shadowset=full-shadow` are
the contract §13.2 requires, and they held.

### 17.2 the verdict

The user, verbatim:

> **THE EFFECT IS PERFECT. earglow-rq3 is the defacto. Please add that to that
> super scuffed amalgamation of effects.**

KEPT. §16.3's `-rq3` pass row — *"glow on ears and noses only"* — is the row the
user's sentence answers.

### 17.3 the frames — and what is NOT measured

One capture exists in the whole window:
`photomode_03092026_003639.png` (00:36:39), archived as
`a-b-testing/earglow-rq/G-rq3hit-003639.png`. Its timestamp falls **between**
the 00:35:14 `-rq3-hit` launch and the 00:38:40 `-rq3` launch, so it is a
**`-rq3-hit` diagnostic frame**. **There is no `-rq3` frame.**

So, stated plainly and not smoothed: **the "PERFECT" verdict is a LIVE-ONLY
read-out.** Nothing in `a-b-testing/` measures the glow rung itself, no control
frame was taken beside it, and the second half of §16.2's frame spec — a face
standing in another object's shadow, which is half of what §15 asked `rq3` to
fix — was never shot. The keep is the user's and it is recorded as theirs; what
this document can prove about the glow rung on screen is that it was **served**
(§17.1), not what it looked like.

### 17.4 what the `-hit` frame measures

Measured at full res (2560×1440). The scene is a low-sun desert, so an absolute
hue test is worthless — 35 616 pixels pass `R−G > 60` across the terrain alone.
At `R−G > 120` the entire painted set collapses onto the head: **4 448 px, bbox
x 1231–1471, y 366–871**, i.e. the classifier is measuring the paint and not the
sunset.

| region (box) | `R−G > 120` | `B−G > 10` | max `R−G` |
|---|---|---|---|
| inner canthi | 2 429 | 0 | 160 |
| nose bridge | 2 039 | 0 | 157 |
| hairline / forehead | 391 | 0 | 166 |
| lower lip | 65 | 0 | 147 |
| open cheek | 0 | 0 | 64 |
| ear / jaw / shoulder | 0 | 42 (all background sand, `rgb ≈ 72,94,105`) | 98 |

**BLUE on the head: none.** Whole-frame, `B − max(R,G) > 25` finds 4 pixels, all
at y 29–32 in the sky. Inside the head box `max(B−G) = 21` and every cell at
`B−G > 5` sits at x ≥ 1472, off the face on the sand.

### 17.5 which §16.3 row fired

**None of the five, as written.** That is the honest answer and it is recorded
as a pre-registration miss, not massaged into a pass:

- Row 1 (PASS) needs **both** halves — blue on the ear rim/nostril wings/lip
  edge **and** red at the inner eye corners, nose bridge and mouth interior.
  The frame delivers the **red half exactly** and **zero** blue.
- Row 2 (blue at the inner canthi) — no; those are the reddest pixels in the
  frame.
- Row 3 (ear rim RED) — no; the ear region carries no paint at all.
- Row 4 (nothing anywhere) — no; 4 448 painted pixels.
- Row 5 (red everywhere including an ear rim in open sun) — no; the open cheek
  is unpainted (0 px at `R−G > 120`, `max R−G` 64 against 160 on the canthi).

**Why the blue half is unobservable here: the frame is wrong again — the fourth
time.** §16.2 required the ear clear of hair. In this pose the head is turned,
the near ear sits at the left edge behind hair strands, and the crop at
x 930–1090 y 580–800 is jaw, hair and sand — there is no exposed sun-reachable
thin rim in the frame for C to accept. This is a frame defect, not a build
defect, and it is the same defect as §12, §13 and §14: **the shot was taken
before the frame condition was checked.**

### 17.6 what the `-hit` frame DOES establish

The red set is, region for region, **§15's measured bleed set**: inner eye
corners, nose bridge, lower lip — plus the hairline. Those are precisely the
pixels `rq2` lit and should not have. Under `rq3` they are painted RED, and RED
means *B committed a same-instance wall and **C hit***, i.e. **query C is
rejecting exactly the pixels §15.4 said it must.** That is a real, measured
result about the new variable, and it is consistent with — though it does not by
itself prove — the user's live verdict on the glow rung.

What it does **not** establish: that C accepts a genuinely lit thin rim. Only
blue on an exposed ear does that, and no frame in this repo shows it.

### 17.7 the rung, under its lineage name

The kept shader is parked twice under two names that are **provably the same
bytes**:

| name | content sha | raygen-half |
|---|---|---|
| `earglow-rq3` | `359060c26c8c7367` | `9852b0bbf6417842` |
| `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow` | `359060c26c8c7367` | `9852b0bbf6417842` |

The lineage name was **not copied**. `dev/build_earglow_rq3.sh` gained a
`--lineage NAME` option that adds the name as a **fourth full rung** — the same
`--k 0.22 --wide 4.0 --wrap 0.35` arguments, re-derived from the base bytes
through `spirv-dis → patcher → spirv-as`, through every one of the nine gates
(round-trip neutrality, `spirv-val` vulkan1.4 on all 93, the coverage census with
its own `WANT` entry spelled out rather than aliased, the instruction census
3/3/2/1 per module, 10-of-93 identity against the base, `verify_earglow_rq3.py`
on the shipped bytes, the decoys, the closed-form transfer, the MANIFEST).
A new gate **2b** then demands **93 of 93 `cmp`-identical to `swaps.earglow-rq3`**
— which is the proof that the lineage name and the rung name are one shader and
not two shaders that happen to look alike. `earglow-rq3` stays parked under its
own name as the A/B handle.

### 17.8 the deploy

- `init.lua` default `skinspec` → `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow`,
  with the reason in the comment. The `<-- DEFAULT` marker moved off the `-fog`
  row onto the new one, and the `-fog` row now reads *"the previous default; the
  base of everything below"*.
- `ser` stays `class` and `shadowset` stays `full-shadow` — **not optional.**
  The rung ships 12 `rgs_reference_main` + 4 `rgs_restirgi_*`, so
  `sync_settings.sh`'s `gi_refuse` empties the whole overlay if either is wrong.
  All three provenance gates dry-run against the parked rung and **pass**:
  `src_ser="ser.set/class"` with `ser_sha=310513f3008cbde4` == the live
  `ser.set/class` raygen sha, `ptq_sha=55ed4e5c6884ab71` == the live
  `swaps.ptq` raygen sha, `shadowset=full-shadow` with `rgs_restirgi_*` present.
- `make release` + `make install`. `cmp`: repo `init.lua` == `release/` copy ==
  live CET `init.lua`; parked rung == build output on all 93 modules.
- **The live `brdf_params.txt` was deliberately NOT touched**, and this differs
  from how `95`'s fog rung was made default (`0928124` set it). At the moment of
  this deploy the file read `skinspec=carglint`, written at 00:57:31 and launched
  at 00:57:39 — the car-paint agent's A/B, with the game **running**. That file
  is player state and it currently holds someone else's in-flight selection.
  Consequence, stated rather than hidden: **the next launch serves `carglint`,
  not the new default.** The default takes effect for a fresh `brdf_params.txt`
  or when the rung is picked in the panel — where it was then the row marked
  `<-- DEFAULT`. **That marker has since moved again**, onto
  `…-fog-earglow-glintdense` (`100` §13); this bullet's *point* is unchanged and
  applies to that change too — **a default change does not rewrite the live
  `brdf_params.txt`.**

### 17.9 for whoever builds next

**Amended 2026-09-03 ~01:20.** The standing base is now
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense`, which is
this rung plus `100`'s glints.

`100` **has** since rebased: its `carglint-dense` knobs were shot, kept, and
stacked onto `-earglow` as that new default (`100` §13). Its five original
rungs are untouched and still sit on the pre-glow base, so their
pre-registered shas still match — the stack is a **sixth** rung, not a rebuild.

`102`'s contact rungs are still on
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog` — the *previous* base — so
**they do not carry the ear glow**, and a launch on any of them is an ear-glow
regression as well as whatever it is testing. They are deliberately **not**
rebuilt: rebuilding them would change their content shas, and every
pre-registered sha in `102` is a serving proof that would stop matching. Rebase
them when their own A/B is settled, not before.

---

## 18. The thickness floor — `earglow-cap3/4/6`. BUILT, GATED, PARKED, UNSHOT.

Written before any `cap` frame exists.

### 18.1 the complaint

The user, on the then-shipped default (`…-fog-earglow`), verbatim:

> **Also if the intensity gets more intense as geometry gets thinner, we might
> want to cap that at a certain point. Childrens ears GLOW. They emit alot of
> light which doesnt look correct. Everything else looks great**

It is a correct reading of the shader. W3's transfer

```
T(t) = 0.5 * ( exp(-t/ld) + exp(-t/(4*ld)) )      ld = (3.67, 1.37, 0.68) mm
```

is monotone **decreasing** in `t`, so the glow is monotone **increasing** as the
flesh thins, and the only ceiling in the whole build is query B's `tmin` at
**1.5 mm**. A child's head is not a scaled adult's in the engine's meshes, but
its ears are thinner everywhere, so they sit high on the curve by construction
and can only ever be brighter than an adult's. Nothing caps them.

Two things move together, and only one of them was complained about:

| t (mm) | `k·T` R | G | B | R/G | G/B |
|---|---|---|---|---|---|
| **1.5** (`tmin`) | 0.17241 | 0.12046 | 0.07549 | 1.43 | 1.60 |
| 2.0 | 0.15977 | 0.10191 | 0.05854 | 1.57 | 1.74 |
| 3.0 | 0.13824 | 0.07594 | 0.03784 | 1.82 | 2.01 |
| 4.0 | 0.12075 | 0.05895 | 0.02558 | 2.05 | 2.30 |
| 6.0 | 0.09454 | 0.03818 | 0.01213 | 2.48 | 3.15 |
| 8.0 | 0.07622 | 0.02587 | 0.00581 | 2.95 | 4.45 |

A thin ear is not only **brighter**, it is **less red** (R/G 1.43 at 1.5 mm
against 2.05 at 4 mm) — thin flesh passes green and blue that thick flesh eats.
So "children's ears glow" is partly a **hue** report as well as a brightness
one, and a floor fixes both at once, because it fixes `t`.

### 18.2 the fix — one variable

```
t_eff = NMax(t_B, t_cap)          then evaluate T at t_eff
```

- **In the TRANSFER, not in the RAY.** Query C's origin is still
  `P + (t_B + 1 mm)·S` with the **raw** `t_B`. Capping that would move the
  sun-visibility ray's start point, i.e. quietly ask a different geometric
  question. `--decoy capray` builds that mistake and the verifier kills it.
- **No discontinuity.** `t_eff` is continuous in `t` and `T` is continuous, so
  the composition is; at `t = t_cap` the two regimes meet by construction, and
  for `t > t_cap` **nothing changes at all** — the gate proves the capped and
  uncapped transfers agree bit for bit above the floor. Adult ears are
  untouched by *construction*, not by tuning, which is exactly what makes
  §18.5's frame a discriminator instead of a taste test.
- **`max` on `t`, not `min` on `T`.** `T` is monotone decreasing, so
  `min(T(t), T(t_cap)) ≡ T(max(t, t_cap))` — the same function. The `max` form
  costs **one** `OpExtInst NMax`, evaluated once and shared by all six
  exponentials; the `min` form costs three `NMin`s (one per channel, after the
  lobes combine) plus three per-channel constants that would have to be
  re-derived every time `wide` or `ld` moved. One instruction against three,
  and the constant that ships is a **physical thickness in metres** rather than
  three magic transmittances.
- **`NMax`, not `FMax`.** GLSL450 `NMax` returns the non-NaN operand when one
  is NaN; `FMax`'s NaN behaviour is undefined. `t` comes from
  `OpRayQueryGetIntersectionTKHR` on a *committed* intersection so a NaN is not
  expected — `NMax` turns "not expected" into "cannot": a NaN `t` yields
  `t_cap`, the `Exp` chain stays finite, and no NaN can reach a radiance write.
  Identical cost. Same reasoning as `100` §3's `NClamp` totality guards.
- **`k` is NOT touched.** 0.22, from `70`/`71`, as it has been in every rung in
  this document. The floor is a floor, not a dimmer.

### 18.3 what each cap removes at the thinnest flesh

`T(1.5 mm) / T(t_cap)` — how much the floor takes off an ear that is at the
`tmin` limit, per channel:

| cap | R | G | B | mean |
|---|---|---|---|---|
| **3 mm** | **1.25×** | **1.59×** | **1.99×** | 1.61× |
| **4 mm** | **1.43×** | **2.04×** | **2.95×** | 2.14× |
| **6 mm** | **1.82×** | **3.15×** | **6.22×** | 3.73× |

And at 2 mm: cap3 1.16/1.34/1.55×, cap4 1.32/1.73/2.29×, cap6 1.69/2.67/4.82×.

Read the columns, not just the means: **the floor takes far more blue and green
than red**, so a capped thin ear does not merely dim — it lands on the *hue* of
flesh `t_cap` thick, which is the whole point. It also means **cap6 will visibly
change adult ears** (it lifts the floor above a 4 mm ear entirely: the 4 mm row
of §18.1 is replaced by the 6 mm row, a 1.28× drop in red), and that is why cap6
is in the ladder as a bracket and is *not* expected to ship.

### 18.4 what was built, and what proves it

Three rungs on `gi-50b-…-cone2all-fog-earglow` — which is `earglow-rq3`, and
which was the shipped default from 00:38 to ~01:20 on 2026-09-03 — differing
from it in exactly one `OpExtInst` and one constant. **They are NOT built on the
`-glintdense` stack that is now the default**, so selecting any of them also
turns the car-paint glints off; say so before the shot:

| rung | floor | content sha | raygen-half |
|---|---|---|---|
| `earglow-cap3` | 3 mm | `b3c690d79eb0a36d` | `69b5b1e682b271e3` |
| `earglow-cap4` | 4 mm | `883eb9f58c2ca9b9` | `c4df72aa93c7de0b` |
| `earglow-cap6` | 6 mm | `2b2a31c414e366b9` | `f7f2bc7fada8bab4` |

**There is no `-cap0` rung and there must not be: `…-fog-earglow` IS the
cap-0 control**, and gate 2b proves that rather than asserting it — the same
patcher run with `--cap 0` emits nothing and reproduces
`swaps.gi-50b-…-fog-earglow` **10 of 10 byte-identical**. That is what makes the
floor the one variable of this A/B: not "the diff is small", but "the diff is
*empty* when the floor is off".

The patcher **adds no arithmetic of its own**. `dev/patch_earglow_cap.py` calls
`patch_earglow_rq3.build()` — the shipped patcher of the current default,
imported unmodified and not copied — and performs one asserted transformation on
the instruction list it returns: find the unique committed-T getter, find its
unique `OpSelect` guard, **classify every consumer of that guard and refuse the
module if any is unaccounted for**, insert the `NMax`, and repoint only the six
`FMul → FNegate → Exp` chain heads. A half-capped transfer is impossible by
construction; the build dies instead.

Nine gates green: round-trip neutrality 10/10 before any rewrite, `spirv-val`
vulkan1.4 on 3 × 93, the cap-0 null above, 10-of-10 differing between every pair
of rungs and against the default, a coverage census from the reports (floor
value, `NMax` not `NMin`, 6 capped chains, query C's push untouched, `k` still
0.22), an instruction census on the shipped bytes demanding
**(3 Initialize, 3 Proceed, 2 InstanceId, 1 committed-T, 0 added traces, exactly
1 ADDED `NMax`) per module** — the added `NMax` counted against the *uncapped
default*, not against vanilla, because every shipped permutation already carries
`NMax`es of its own and counting those would be measuring the engine —
10-of-93 identity against the base, `dev/verify_earglow_cap.py` on the shipped
`.spv`, **twelve non-vacuity rejections**, and a closed-form check that reads
*both* the transfer rates *and* the floor back out of the `.spv` and asserts the
transfer is flat below the floor and **bit-identical above it**.

The verifier's first half runs `verify_earglow_rq3.py` against the same
directory, so the rq3 rung underneath must still verify in full — a cap that
broke the rung fails here rather than being excused. That required one
**additive, opt-in** change to `verify_earglow_rq3.py`: `--floor` allows exactly
one `NMax` hop between the guarded `t` and the transfer. Without the flag the
strict form stands, which is why `cap3` read as a plain rq3 rung is rejected
**and** the uncapped default read with `--floor` is rejected. Both are in the
decoy list, along with the default read as cap3, cap3 read as cap4, cap4/cap6
read as cap3, the control, the base, `earglow-rq2`, and three purpose-built
decoy **builds** — `capray` (the floor applied to query C's ray), `capmin`
(`NMin`, a ceiling on thickness, i.e. the exact opposite), `nocap` (the `NMax`
emitted but left unwired) — each of which is additionally asserted to be
rejected **for its own reason**, not incidentally.

Driver half: `dev/selftest_earglow_rq.sh` is now **50/50** on an RTX 4070 (was
42), the three cap rungs and the default rung each serving their 10 real
raygens through the layer at shipped size and being accepted. They are appended
to the rung list only if built, so the file still runs at 42 in a checkout
without them.

Files, all new, no shared patcher edited: `dev/patch_earglow_cap.py`,
`dev/verify_earglow_cap.py`, `dev/build_earglow_cap.sh`.

### 18.5 the frame, pre-registered

**One frame, and it must contain a CHILD and an ADULT at once.** Backlit — sun
low and behind the heads, camera on the sun side — and **both ears clear of
hair**, which is the condition §16.2 asked for and four frames in a row have
failed. Same settings contract as §13.2 (`ser=class`, `shadowset=full-shadow`,
RR off, photo mode, weather clear). Shoot the **default rung first** in that
frame — it is the control and it is the thing being complained about — then
`cap3`, `cap4`, `cap6` without moving the camera.

### 18.6 the interpretation table

Rows exclusive, first match wins.

| what the caps show | conclusion | action |
|---|---|---|
| **the child's ears stop out-glowing the adult's ear rims at `cap3`, and the adult's ear rims are indistinguishable from the default** | **PASS, and the smallest cap that does it wins.** The complaint was thinness and 3 mm is enough | ship `cap3` as the default's replacement; keep `cap4`/`cap6` parked |
| the child is still too bright at `cap3` but is right at `cap4`, adults still unchanged | same conclusion, the floor is just deeper | ship `cap4`; `cap3` stays as the gentler A/B |
| the child looks right only at `cap6`, **and adult ear rims are visibly dimmer there** | the cap is doing the job by dimming *everything*, which is a `k` change wearing a floor's clothes | **do not ship `cap6`.** Report it and stop: `k` is not to be tuned (`70`/`71`), so this outcome is a finding, not a licence |
| adult ear rims are visibly dimmer at `cap3` or `cap4` | impossible by construction — the transfer is bit-identical above the floor — so the difference is **not** the floor | treat it as a serving or frame defect: check `skin_sha` in the launch log, and re-shoot with the camera pinned. If it survives that, it is a real defect in this build and it is a headline finding |
| **no visible change on the child at any of the three caps** | the child's sun-path thickness is **above 6 mm**, so the brightness is not coming from thinness at all | the three caps are a **bracket**: this rules the thickness explanation out. The remaining candidates are W3's **wrap** envelope (a rim-angle term, not a thickness term) and `k`. The named discriminator is `earglow-rq3-hi` — same `k`, wider wrap and softer transfer: if the child moves under it while adults do not, it is the wrap |
| the child changes between two caps but the adult also changes at the *same* cap | the two heads' ears are the same thickness in the mesh and the difference on screen is not thickness | the complaint cannot be fixed in the transfer at all; it is the wrap or the mesh, and this document should stop and say so |

### 18.7 what a cap frame still would not prove

The caps read `t_B` — the *sun-path* thickness — and nothing else. If a child's
ear is brighter because it is more often **backlit at a grazing angle** (the
wrap term, `smoothstep(0, 0.35, −N·S)`) rather than because it is thinner, every
row above still fires the same way, and the last row is the one that catches it.
The frame also cannot separate "the mesh is thin" from "the BLAS's interior
backface is where the patcher assumes" — that premise is §4's and remains
unproven for children specifically, since every frame in this document so far
has been of an adult.

### 18.8 SHOT 2026-09-03 — `cap6` KEPT, and it is the default

```
2026-09-03T01:24:07-05:00 … skinspec=earglow-cap3 skin_sha=b3c690d79eb0a36d
  ser=class:in-skin shadowset=full-shadow ptq=rcbm cache=cleared payload=5d9a67816b2fa8c4
2026-09-03T01:25:56-05:00 … skinspec=earglow-cap6 skin_sha=2b2a31c414e366b9
  ser=class:in-skin shadowset=full-shadow ptq=rcbm cache=cleared payload=67c33fca23d21ccc
```

Both shas are §18.4's, pre-registered before either launch, so both rungs are
proven **served**. The user's decision, verbatim:

> **Get a subagent to use earglow-cap6 as the default.**

**`earglow-cap4` WAS NEVER SHOT.** The launch log carries `cap3` and `cap6` and
nothing between them. So the ladder was read as a two-point bracket, not as
three, and **`cap4` is superseded without ever having had a reading** — it stays
parked, and if the 6 mm floor later proves too deep on adults, `cap4` is the
untried middle and not a discarded one.

**No frames.** The only captures in the window are 01:08:29 and 01:11:27, both
*before* the 01:24 `cap3` launch — they belong to `100`'s glint launches. **So
this verdict, like §17's, is LIVE-ONLY**, and the frame §18.5 pre-registered — a
child and an adult in one backlit shot, default rung first as the control — was
not taken.

**Which §18.6 rows can be read: none of the six.** Every row is a comparison
between the child, the adult and the control *in one frame*, and no frame
exists. What the log establishes is only that both rungs reached the driver and
that the user, having seen them, chose the deeper floor. Two consequences are
worth stating rather than leaving implied:

- choosing **cap6** over **cap3** means 3 mm was not enough to settle the
  complaint — which is §18.6's second row's territory, but the row that follows
  it warns that cap6 **also dims adult ear rims** (it replaces the 4 mm row of
  §18.1 with the 6 mm row: 1.28× down in red). That trade was accepted on
  screen, not measured. It is exactly the outcome §18.3 said would need
  watching, and `cap4` is parked for the day someone wants the middle.
- nothing here tests §18.6's last row — whether the brightness was thickness at
  all. `cap6` visibly changing the look is evidence that it *was* (a floor that
  bites means `t < 6 mm` on those pixels), but "visibly" is the user's eye and
  not a measurement.

### 18.9 the shipped default is the CAP6 STACK

The default that `cap6` had to join already carried `100`'s dense car-paint
glints, so the new default carries both:

| | content sha |
|---|---|
| previous default `…-cone2all-fog-earglow-glintdense` | `e0de8b9d5a6716d0` |
| **new default `…-cone2all-fog-earglow-cap6-glintdense`** | **`3bb0aee03a1bfda8`** |
| the floor alone, `earglow-cap6` | `2b2a31c414e366b9` |

Built by **`dev/build_carglint_stack_cap6.sh`**, a new file. `100`'s
`dev/build_carglint_stack.sh` does **not** take its base or output name as a
parameter (`EGBASE` / `EGLIN` / `RUNG` / `WORK` are plain assignments) and it
belongs to another agent who was running it at the time, so it was **neither
edited in place nor forked**: the new script generates a parameterised instance
of it under eight substitutions, **each asserted to match exactly once** (so an
upstream rename breaks the build loudly instead of quietly building the wrong
thing), runs that instance, and then adds the gates a floored base needs.

All of `100`'s gates green on the cap6 base: round-trip 10/10 before any
rewrite, `spirv-val` vulkan1.4 ×93, the glint census **identical to
`carglint-dense`'s number for number** (10 modules, 60 GGX blocks, 60 glint
sites, 3170 instructions, member 56 ×10, F0-metallic 18/18 ×10 — so neither the
rq3 splice nor the floor costs a single glint site), **`--k-glint 0` on the cap6
base reproduces `earglow-cap6` at 93/93 `cmp`**, 10-of-93 differing from
`earglow-cap6` and from the old base, 10-of-10 differing from `carglint-dense`,
`verify_carglint.py --nu0 600000` OK (`E[g] = 1.0003 ± 0.0025`, `max 16.0`), and
six of its own non-vacuity rejections.

The gates this wrapper adds, and why each exists:

- `verify_earglow_rq3.py … --floor` **ALL PASS** on the stacked bytes — the
  glow splice survives the glint rewrite. `--floor` is required because the
  floor puts one `NMax` between the guarded `t` and the transfer; it is passed
  to the wrong-knobs decoy too, or that decoy would fail for the floor instead
  of for the knobs it exists to test.
- `verify_earglow_cap.py --cap 0.006` **ALL PASS** — 60 capped chains, query
  C's push still raw.
- **10 of 93 differ from the previous default stack** — the floor is the only
  thing that moved.
- four rejections that pin the one variable from both sides: the cap6 stack read
  **without** `--floor` (so the floor is really there), the cap6 stack read as
  `cap3`, the **previous default stack read as a cap6 rung** (so the floor is
  really absent there), and `earglow-cap6` read as a glint rung (so the glints
  are really here).

Driver: `dev/selftest_earglow_rq.sh` **52/52** on the RTX 4070 (was 50) — the
stacked raygens, the largest this family produces, served through the layer at
shipped size and accepted 10/10. Deployed: `init.lua`'s default `skinspec`,
`make install`, `cmp` repo == `release/` == the live CET copy, parked == built
93/93, layer byte-identical in all three places. Contract unchanged and still
**not optional**: `ser=class`, `shadowset=full-shadow`, `ser_sha=310513f3008cbde4`,
`ptq_sha=55ed4e5c6884ab71` — all three `gi_refuse` gates dry-run green against
the parked stack.
