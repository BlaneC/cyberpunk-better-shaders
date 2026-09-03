# 105 — Backlit translucency for every thin surface. `101`'s ear-glow query, generalised off skin and onto curtains, tents, tarps, plastic sheeting, paper and thin cloth. **BUILT, GATED, PARKED, UNSHOT.**

Written 2026-09-03. Four rungs, ten offline gates green, sixteen decoys
rejected, driver self-test **25 of 25** on an RTX 4070 with **six live ray
query objects in one raygen**. **Nothing has been on screen. Nothing
committed. `make install` not run.**

This rung **stacks**. It is built on the standing default
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`
(content `3bb0aee03a1bfda8`), which already carries `101`'s ear glow, its 6 mm
floor and `100`'s dense glints, and it adds three more ray queries to the same
ten `rgs_reference_main`. The `-ctl` rung reproduces that base at **93 of 93
`cmp`** and its content sha comes back `3bb0aee03a1bfda8` — the same string
`CURRENT.md` records for the default.

---

## 0. Verdict

| question | answer | confidence |
|---|---|---|
| Does `101`'s construction generalise off skin? | **Yes, mechanically — it never contained anything skin-specific.** Sunward ray, cull front faces, first backface at `t` = thickness, same-instance test, sun-visible exit point. Only the *gate* and the *band* were skin | **high** — the splice is `101` §2 with two constants changed, re-derived by `dev/verify_thinglow.py` from the shipped bytes |
| Is the ear glow still bit-identical on skin pixels? | **Yes, by construction and asserted three ways.** The gate's first term is `class != 1`; the k select's false arm is `-0.0`; the accumulators start at `-0.0`; `x + (-0.0) == x` bit-exactly for every finite `x` | **high** on the argument, **high** on the structural proof (§7, gate 6 check 14), **not yet measured on screen** |
| Will a curtain / tent / plastic sheet glow? | **Unknown. This is the whole shot.** The premise is `101`'s: the BLAS carries interior backfaces and a curtain is a closed-enough manifold sunward | **low** — `101` proved it for *heads*. A single-sided curtain quad has **no** backface at 0.3–25 mm and is a guaranteed miss |
| Will a **market tarp** glow? | **NO — and this is a FALSE NEGATIVE this build ships with.** `94` §14.2a measured market tarps at **metallic ≥ 0.5**; the gate demands `< 0.1` | **high** — measured in `94`, not inferred here. **The frame contract therefore demands a curtain or plastic sheet, not a tarp** |
| Will backlit foliage glow? | **Yes, and the `t` it reads is wrong.** Class 5 is not excluded and alpha-tested cards are mis-committed by the `Opaque` flag bit (§6) | **high** — `98` §2.3 is explicit. Pre-registered as the known false positive |
| Does the driver compile six live ray query objects? | **Yes.** RT pipeline links on an RTX 4070 with 6 Initialize / 6 Proceed / 4 InstanceId / 2 committed T in one raygen | **high** — `dev/selftest_thinglow.sh` case A, on the device |
| Is `k = 0.5`, `ld = 2 mm` right? | **No idea. Both are guesses.** `ld` is a single scalar standing in for cloth, paper, PVC and skinless plastic | **none** — that is what `-hi` is for |
| Is the cost acceptable? | **+3 rays per pixel at path 0 only, +2 732 bytes per module (+0.9 %), zero added control flow** | **high** offline; **unmeasured** in frame time |

**The falsifier is `thinglow-hit` and it must be shot in the same frame.** If
it paints nothing, either the gate never opens or thin geometry carries no
interior backface, and the whole rung is black for a reason no amount of `k`
will fix.

---

## 1. What was inherited and what changed

`101` §2's construction, unchanged:

* **query A** — the module's own primary view ray, flags **517**
  (`Opaque | TerminateOnFirstHit | SkipAABBs`), origin the zero triple,
  `t ∈ [|P|·0.999, |P|·1.001 + 1e-4]`. Answers *"what instance is this pixel?"*
* **query B** — sunward from the shaded point, flags **545**
  (`Opaque | CullFrontFacingTriangles | SkipAABBs`), origin and direction the
  module's **own** sun-NEE trace operands. Culling front faces means the first
  visible triangle is the sun-side wall seen from inside: `t` **is** the
  thickness.
* **query C** — sun visibility from the exit point `P + (t_B + 1 mm)·S`, flags
  517, `tmin` 1 mm, and `tmax` the module's **own** sun shadow-ray `tmax`, so C
  and the engine agree about the sun. `101` §12 added this because a geometric
  test was standing in for a lighting test.
* **accept** ⇔ gate ∧ A committed ∧ B committed ∧ `A.InstanceId == B.InstanceId`
  ∧ C **missed**.

Two constants and one gate changed:

| | `101` (ear glow) | this rung |
|---|---|---|
| B's `tmin` | 1.5 mm (thinnest real ear ≈ 2 mm) | **0.3 mm** — paper, plastic sheeting and a single layer of cloth are thinner than an ear |
| B's `tmax` | 18 mm | **25 mm** — a folded curtain or a stacked tent panel, not a doorway |
| gate | `class == 1` ∧ backlit ∧ `path == 0` | **`class != 1/4/8` ∧ `metallic < 0.1` ∧ `roughness > 0.5` ∧ backlit ∧ `path == 0`** (§3) |
| transfer | six `Exp`, three Jensen lobes, wrap smoothstep, 6 mm floor | **one `Exp`**, scalar `ld`, **× the module's own squared base colour** (§5) |

The two are told apart *by their bands*, never by position: `dev/verify_thinglow.py`
check 3 partitions the six Initialize by B's `t` range and fails if either
triple is missing.

---

## 2. The splice, instruction by instruction

112 instructions, straight line, spliced immediately after the module's own
sun-NEE `OpTraceRayKHR` — between that trace and `101`'s own block. It
references nothing that block defines and defines nothing it consumes.

```
  # --- clone the material reads (41 ops, 3 OpImageFetch) -------------------
  %cls  ← clone_chain(the module's own class read)          push const → heap → LaunchID
  %met  ← clone_chain(the module's own metallic read)
  %rgh  ← clone_chain(the module's own roughness read)
  %alb0..2 ← clone_chain(the module's own base-colour channels)

  # --- the gate: 7 terms, folded into the CULL MASK (no branch) -----------
  %t1 = OpINotEqual %bool %cls %uint_1          # skin: the ear glow keeps it
  %t2 = OpINotEqual %bool %cls %uint_4          # hair
  %t3 = OpINotEqual %bool %cls %uint_8          # eyes -- VACUOUS, see 4.3
  %t4 = OpFOrdLessThan    %bool %met %float_0_1
  %t5 = OpFOrdGreaterThan %bool %rgh %float_0_5
  %t6 = <the trace's OWN backlit condition>     # N.S <= 0, not re-derived
  %t7 = OpIEqual %bool %counter %uint_0         # primary bounce only
  %g  = OpLogicalAnd ... (six ANDs)
  %m  = OpSelect %uint %g %uint_39 %uint_0      # cull mask 39, or 0 = free miss

  # --- query A: which instance is this pixel? -----------------------------
  %tA  = OpFMul %float <dot(P,P)> <rsqrt(dot(P,P))>          # |P|
  %dA  = OpCompositeConstruct %v3float <the module's own normalized view ray>
  %lo  = OpFMul %float %tA %float_0_999
  %hi  = OpFAdd %float (OpFMul %float %tA %float_1_001) %float_1e_4
       OpRayQueryInitializeKHR %qA %as %uint_517 %m %v3zero %lo %dA %hi
  %pA  = OpRayQueryProceedKHR ; %tyA = ...TypeKHR %qA %uint_1
  %hA  = OpINotEqual %bool %tyA %uint_0 ; %idA = ...InstanceIdKHR %qA %uint_1

  # --- query B: the thickness ---------------------------------------------
       OpRayQueryInitializeKHR %qB %as %uint_545 %m <P> %float_0_0003 <S> %float_0_025
  %pB  = Proceed ; %tyB = Type ; %hB = INotEqual ; %tB = ...TKHR %qB %uint_1
  %tu  = OpSelect %float %hB %tB %float_0_025    # NaN guard: T on a miss is UNDEFINED
  %idB = ...InstanceIdKHR %qB %uint_1

  # --- the instance match --------------------------------------------------
  %sm  = OpIEqual %bool %idA %idB
  %bo  = OpLogicalAnd %bool %hA %hB
  %mt  = OpLogicalAnd %bool %bo %sm

  # --- query C: can the exit point see the sun? ---------------------------
  %tp  = OpFAdd %float %tu %float_0_001
  %of  = OpVectorTimesScalar %v3float <S> %tp
  %og  = OpFAdd %v3float <P> %of
       OpRayQueryInitializeKHR %qC %as %uint_517 %m %og %float_0_001 <S> <the module's own sun tmax>
  %pC  = Proceed ; %tyC = Type ; %hC = INotEqual ; %vC = OpLogicalNot %bool %hC
  %ok  = OpLogicalAnd %bool (OpLogicalAnd %bool %g %mt) %vC

  # --- the transfer: ONE Exp, three albedo multiplies ---------------------
  %kg  = OpSelect %float %ok %float_0_5 %float_n0      # NEGATIVE zero, see 7
  %e1  = OpFMul %float %tu %float_500                  # 1/ld
  %e2  = OpFNegate %float %e1
  %tr  = OpExtInst %float %glsl Exp %e2
  %kw  = OpFMul %float %kg %tr
  for c in 0..2:
    %sq = OpFMul %float %alb[c] %alb[c]                # the module's own linearise
    %m1 = OpFMul %float %kw %sq
    %m2 = OpFMul %float %m1 <the module's own sunRadiance[c]>
    %m3 = OpExtInst %float %glsl NMin %m2 %float_100   # firefly clamp
    OpStore %acc[c] (OpFAdd (OpLoad %acc[c]) %m3)
```

and at each painted radiance write (25 across the ten permutations):

```
  %l  = OpLoad %float %acc[c]
  %a  = OpFAdd %float <the EAR GLOW's own add for channel c> %l
  %nt = OpCompositeConstruct %v4float %a0 %a1 %a2 <alpha, untouched>
        OpImageWrite %img %coord %nt          # only this operand is repointed
```

**The only base instruction this rung mutates is the `OpImageWrite`'s texel
operand, 25 times.** Everything else is insertion — proven, not claimed, by
gate 6 check 14e (§7).

### 2.1 Why the material reads are cloned and not referenced

The module's own class / metallic / roughness / base-colour reads sit at line
~1725; the splice lands at ~3125, inside a different block of a 15 000-line
structured CFG with three nested loops. Asserting dominance across that would
be a claim. `clone_chain` re-derives all four back to push constants, the
descriptor heap and `gl_LaunchID` instead — **41 ops, 3 added `OpImageFetch`**
(class+material, base colour), all sharing one coordinate construct. Correct
by construction, at the cost of three texture reads per invocation.
(`GOTCHAS`: dominance is never assumed.)

---

## 3. The gate

Seven terms, ANDed, folded into the **cull mask** — `OpSelect(gate, 39, 0)`.
A shut gate therefore costs **three guaranteed misses and zero branches**;
there is no added control flow anywhere in this rung.

| term | why | what it kills |
|---|---|---|
| `class != 1` | **skin belongs to `101`** | the entire ear glow's domain — this is what makes §7 true |
| `class != 4` | hair is `101` §2's original false positive | strand cards |
| `class != 8` | **vacuous — class 8 does not exist** (§4.3) | nothing |
| `metallic < 0.1` | thin translucent things are dielectrics | chain-link, gratings, railings, car bodies (`94`: m ≥ 0.5) — **and market tarps, which is a FALSE NEGATIVE** |
| `roughness > 0.5` | a translucent sheet is diffuse-ish | glass, polished plastic, wet surfaces, screens |
| the trace's **own** backlit condition | reuses the module's `N·S ≤ 0`, not a re-derivation | every front-lit pixel |
| `path counter == 0` | primary bounce only | 5 of 6 path vertices, and the cost with them |

**Class 5 (vegetation) is NOT excluded.** Backlit leaves *should* glow — that
is a real effect — but the `t` the query reads on an alpha-tested foliage card
is the **gap between two cards**, not a leaf thickness (§6). Pre-registered as
the known false positive, not as a feature.

---

## 4. Where class, metallic, roughness and albedo come from

### 4.1 The anchor
`96` §2.1 established that the reference raygens are **compare-only** on the
material class: they carry `class == 1` ANDed with `metallic < 0.1` (skin) and
`class == 4` (hair), and nothing else. `dev/patch_thinglow.py::find_material_site`
anchors on exactly that decision plus the roughness clamp
(`NMax(·, 0.04) → NMin(·, 1)`) and the three `OpSelect(res, 1.0, a·a)`
base-colour selects, and **refuses to build unless the site is unique**.

### 4.2 The census that says the anchor is right
Probed across all twelve permutations: **exactly 1 site in each of the ten
paintable ones, and 0 in `40c6faab52a13874` and `ab7f1822eeb0331b`** — which
reproduces `build_earglow_rq3.sh`'s `PASS` list from a completely different
signature. Two independent detectors agreeing on the same 10-of-12 split is
the strongest evidence available offline that the site is the right one.

### 4.3 Class 8 is vacuous and the term ships anyway
`94` §1.1's whole-dump census over 3 290 modules found the class vocabulary is
**exactly {0, 1, 3, 4, 5}**, and `96` §2.1 confirms nothing anywhere tests 2, 6
or 7. **There is no class 8 and there are no "eyes" in this vocabulary.** The
brief asked for the term; it is emitted, it costs one `OpINotEqual` and one
`OpLogicalAnd`, it will never be false, and the patcher reports
`class8_vacuous: true` so nobody later reads it as evidence that eyes were
handled. Removing it would be one line and would change no pixel.

---

## 5. The transfer, closed form

Single exponential per channel, scalar mean free path — so **one `Exp`**, and
all the colour comes from the albedo:

```
add_c = k · exp(−t / ld) · albedo_c² · sunRadiance_c,   clamped by NMin(·, 100)
ld = 2 mm  ⇒  rate 500 /m      (read back from the shipped .spv by gate 8)
```

`albedo_c²` is the module's **own** squared base colour — the same `a·a`
linearisation the module applies to itself — so a red tarp glows red and a
white sheet glows white without a second decode.

| t (mm) | T = exp(−t/2 mm) | k·T (`thinglow`, k=0.5) | k·T (`thinglow-hi`, k=1.0) | × a=0.8 (a²=0.64), k=0.5 |
|---|---|---|---|---|
| 0.3 | 0.860708 | 0.430354 | 0.860708 | 0.275427 |
| 1.0 | 0.606531 | 0.303265 | 0.606531 | 0.194090 |
| 2.0 | 0.367879 | 0.183940 | 0.367879 | 0.117721 |
| 3.0 | 0.223130 | 0.111565 | 0.223130 | 0.071402 |
| 5.0 | 0.082085 | 0.041042 | 0.082085 | 0.026267 |
| 8.0 | 0.018316 | 0.009158 | 0.018316 | 0.005861 |
| 12.0 | 0.002479 | 0.001239 | 0.002479 | 0.000793 |
| 25.0 | 0.0000037 | 0.0000019 | 0.0000037 | 0.0000012 |

Gate 8 re-reads the rate constant **out of the shipped bytes** and checks the
shape it implies: `T(0.3 mm)` in [0.40, 0.99], `T(25 mm) ≤ 1e-4` (so the `tmax`
cut is not a visible step), `T(1 mm)/T(3 mm)` in [2, 4], and monotone decrease.

**Honest reading of this table:** a single-layer sheet (0.3–1 mm) receives
0.27–0.19 × sun radiance at `k = 0.5`, which is a *lot*. If the shot comes back
blown out, the fix is `k`, and `thinglow-hi` is the wrong direction — that rung
exists for the opposite outcome.

---

## 6. THE ALPHA-TEST DECISION: `Opaque` is KEPT, and here is what it costs

`98` §2.3 is the hazard: flags 517/545 carry the `Opaque` bit, so the traversal
**commits alpha-tested geometry at the quad, not at the cut-out**. Cards,
leaves, chain-link and fence textures are mis-committed.

**The brief's option — "flags without `Opaque` so any-hit runs" — does not
exist.** A Vulkan **ray query never executes an any-hit shader**; that is the
defining difference between `OpRayQuery*` and `OpTraceRayKHR`. Dropping
`Opaque` only hands non-opaque candidates *back to the shader*, which must then
do one of three things:

1. confirm them all → behaviourally identical to `Opaque`, with a `Proceed`
   loop added for nothing;
2. reject them all → **deletes exactly the surfaces this feature exists for**
   (alpha-cut curtains, netting, torn plastic, leaf cards);
3. run a real alpha test → needs the hit's barycentrics, the primitive's UVs
   and the material's opacity texture. **None of the three is reachable at the
   raygen splice site**, and `94` §2.2 already established the payload does not
   even carry a material byte.

And every one of them replaces a straight-line splice with a
`while (OpRayQueryProceedKHR)` loop **inside a 15 000-line structured CFG with
three nested loops** — the exact splice `98` §2.3 called "a much larger
splice", and the exact shape `GOTCHAS` says never to bolt into a CFG this
document has not mapped.

**Decision: keep `Opaque`. Pre-register the false positive.**

**The cost, stated so it cannot be discovered as a surprise:**

| what | consequence |
|---|---|
| foliage cards (class 5, **not** gated out) | backlit leaves glow, and the `t` measured is the **card-to-card gap**, not a leaf thickness. Expect the wrong *shape* of gradient, not merely the wrong brightness |
| chain-link, gratings, railings | **killed by `metallic < 0.1`** (`94` §14.2: m ≥ 0.5). Not a problem |
| alpha-cut curtain / net panels | glow, and the thickness read is the quad's — which for a single-panel curtain means **no backface at all within 25 mm** and a miss. Silent, not wrong |
| decals, posters on walls | primary surface is the wall; A and B disagree on instance ⇒ rejected |

If the shot shows foliage as the dominant artifact, the one-line fix is a
`class != 5` term in the gate (a sixth `OpINotEqual`, `~2` instructions), and
that is a cheaper experiment than an any-hit loop.

---

## 7. Why the ear glow is bit-identical on skin — and how it is proven

**The argument.** The gate's first term is `class != 1`. On a skin pixel the
gate is false, so:

* the cull mask is `0` ⇒ all three queries miss ⇒ `%ok` is false;
* `%kg = OpSelect(%ok, k, -0.0)` yields **negative zero**;
* every operation between `%kg` and the accumulator is either an `OpFMul` by a
  finite factor or `NMin(·, +100)`, and `-0.0 · x = ∓0.0`, `NMin(-0.0, 100) = -0.0`;
* the accumulators are initialised to `-0.0`, so each store is `-0.0 + -0.0 = -0.0`;
* the write is `OpFAdd(<the ear glow's own value>, -0.0)`, and
  **`x + (-0.0) == x` bit-exactly for every finite `x`, including `x = -0.0`.**

`+0.0` would **not** do this: `(-0.0) + (+0.0) = +0.0`, which flips the sign bit
of a `-0.0` accumulator. Hence `NMin` rather than `NClamp` (whose `NMax(-0.0, +0.0)`
can destroy the sign), and hence a dedicated `_negzero()` helper in the
patcher: `Module.fconst` is a dict keyed by a Python float, where `-0.0 == 0.0`
hashes equal, so `mod.const(-0.0)` can silently hand back `%float_0`. That bug
would have been invisible in every gate except this one.

**The proof.** `dev/verify_earglow_rq3.py` **cannot be used** on a stacked
rung: its check 1 demands *exactly three* ray query variables and this rung has
six, and the brief forbids editing it. It fails all ten permutations with
`6 ray query variables, want exactly 3`. So the obligation is discharged by
`dev/verify_thinglow.py` check 14, which is strictly stronger:

| | what it proves |
|---|---|
| 14a | all eight of `101`/`102`'s own constants (the six Jensen rates, `k = 0.22`, the 6 mm floor) survive in the shipped bytes |
| 14b | the base really was the ear-glow stack: 3 Initialize / 3 Proceed / 2 InstanceId / 1 committed-T, and the rung is 6/6/4/2 |
| 14c | at **every** painted write, the value this rung adds to is itself `OpFAdd(x, OpLoad(E_c))` on one of **three distinct** ear-glow accumulators, disjoint from this rung's three. `101`'s term is still in the pixel, not displaced |
| 14d | each of those three accumulators is fed by a value derived from an `OpExtInst Exp` — `101`'s transfer is still wired up |
| 14e | **the base's entire disassembly is an ordered subsequence of the rung's.** Zero deleted, zero reordered, zero altered instructions — insertions only |

14e needs a word. `spirv-as` numbers ids by **order of first appearance**, so
inserting one constant renumbers every id declared after it and a raw textual
diff is 100 % noise. Normalising `%<digits>` away leaves the opcode, the
operand arity, every literal and every friendly-named constant. Under that
normalisation, across all twelve permutations, `difflib` reports **67 `equal`
and 55 `insert` blocks and zero `delete` / zero `replace`** — and the two
pass-through permutations report a single `equal` block, i.e. byte-identical.

**What this does NOT prove:** that the ear glow *renders* the same. Nothing
here has been on screen. The claim is bit-identity of the shader's skin path,
which is a property of the bytes, and it is proven at that level.

---

## 8. Gates, with numbers

`./dev/build_thinglow.sh` — ten gates, all offline, all green:

| # | gate | result |
|---|---|---|
| 0 | base provenance 77 compute + 4 `rgs_restirgi_*` + 12 `rgs_reference_main`, **and the base carries the ear glow** | 93 modules; **10 of 10 paintable permutations at 3/3/2/1 ray-query ops and all 8 ear-glow constants** |
| 1 | round-trip neutrality `spirv-dis \| spirv-as` == base bytes | 10 of 10 |
| 2 | patch + assemble, `spirv-val --target-env vulkan1.4`, 81 non-reference modules `cmp`-verbatim, 2 pass-throughs `cmp`-verbatim | 4 rungs × 93, clean; 10 of 10 differ between every pair of live rungs |
| 3 | coverage census from the patcher reports against a WANT table stated independently | **25 painted writes, 22 benign skips**, identical per rung — *byte for byte the census `101` §6 records for `earglow-rq`* |
| 4 | instruction census on the SHIPPED bytes | live: **60 Initialize, 60 Proceed, 40 committed InstanceId, 20 committed-T**; ctl: 30/30/20/10; **0 added `OpTraceRayKHR`** in all four |
| 5 | identity | `thinglow-ctl` **93 of 93 byte-identical** to the base (content `3bb0aee03a1bfda8`, the sha `CURRENT.md` records); live rungs differ on exactly **10 of 93** |
| 6 | `dev/verify_thinglow.py` re-derives all 14 check groups from the shipped bytes | **ALL PASS** ×3 (1 425 / 1 435 inserted lines), plus `--negative` on the base and `--control` on the ctl |
| 7 | non-vacuity: **sixteen** decoys that MUST be rejected | 16 rejected |
| 8 | closed-form transfer against the rate constant read back from the `.spv` | §5, rate 500.0 /m ⇒ ld 2.00 mm |
| 9 | MANIFEST provenance, `--install` parks under NEW names only | 4 written |

The eight `--decoy` builds, each a deliberately wrong shader:

| decoy | what it breaks | why the verifier must catch it |
|---|---|---|
| `noc` | C traced but never consulted | a curtain with a wall behind it still glows — this is `101` §12's whole bug |
| `cullfront` | C culls front faces | it would miss the occluder it exists to find |
| `invert` | accept when C **hits** | lights exactly the shadowed cloth |
| `noskin` | drops `class != 1` | **would paint over the ear glow** — the single most important decoy in this file |
| `nometal` | drops `metallic < 0.1` | chain-link and car paint join in |
| `norough` | drops `roughness > 0.5` | glass and polished plastic join in |
| `noalbedo` | drops the albedo tint | every tarp glows white |
| `wideband` | `tmax` ×4 (100 mm) | a wall reads as a thin surface |

plus eight cross-reads: the unpatched base as a rung, the ctl as a rung,
`thinglow` read as `-hit`, `-hit` read as the glow rung, `-hi` read with
`thinglow`'s `k`, `thinglow` read with a 1 mm `ld`, the ear-glow base read as a
thinglow rung (3 queries, not 6), and the ctl read as byte-different.

### 8.1 The driver self-test — `./dev/selftest_thinglow.sh`, **25 of 25**

No game. Runs the real layer against the real ICD.

```
thinglow layer self-test  (probe extracted from selftest_earglow_rq.sh, 105 lines)
10 painted ids: 1271d3815051da17 21a92f1a77eb4c22 25b54fc4a17688df 3d871a3170bc5815
                4103c8860c3909e4 4270b745d11a5e8a 852b31a841b85b26 996a3b16253c3e7f
                d002cc05eb940591 d622fb9e1dcb8cd0

case A -- SIX live ray query objects, four InstanceId getters, two committed T
  PASS  the synthetic module is the stacked shape (6/6/4/2/2, got 6/6/4/2/2)
  PASS  ...and carries both transfers (2 OpExtInst Exp, got 2)
    device: NVIDIA GeForce RTX 4070  ray query advertised by ICD: yes
    device created with 3 extensions requested by the app
    vkCreateShaderModule(tg.spv, 3404 B) -> 0
  PASS  probe exits 0
  PASS  layer enabled VK_KHR_ray_query
  PASS  synthetic six-query module accepted
  PASS  ...and its RT PIPELINE links (the driver lowered ALL SIX queries)
  PASS  no rayq_reject
  PASS  no rt_pipeline_failed

case B -- every rung's real raygens, served by the overlay, on the driver
  PASS  thinglow-ctl: probe exits 0, no served module refused
  PASS  thinglow-ctl: 10 of 10 real raygens served at their shipped size and accepted (got 10)
  PASS  thinglow-hit: probe exits 0, no served module refused
  PASS  thinglow-hit: 10 of 10 real raygens served at their shipped size and accepted (got 10)
  PASS  thinglow: probe exits 0, no served module refused
  PASS  thinglow: 10 of 10 real raygens served at their shipped size and accepted (got 10)
  PASS  thinglow-hi: probe exits 0, no served module refused
  PASS  thinglow-hi: 10 of 10 real raygens served at their shipped size and accepted (got 10)

case C -- CALLISTO_RAYQ_DISABLE=1: reject thinglow, fall through to swaps.tgfb/
  PASS  probe still exits 0 (degrades, does not break)
  PASS  layer skipped ray query, reason env_disabled
  PASS  all 10 painted raygens rejected with action next_overlay (got 10)
  PASS  and all 10 fell through to the NEXT OVERLAY, not to vanilla (got 10)
  PASS  no PAINTED module went vanilla (MISS count is 0, the synthetic only)

case D -- the k=0 control under the same guard: it is the standing default
  PASS  probe exits 0
  PASS  the control is rejected too, 10 of 10 (got 10) -- it carries 101's queries
  PASS  ...and it does: 3 OpRayQueryInitializeKHR in the control (got 3)
  PASS  ...against 6 in the live rung (got 6): the stack is real

=== 25 passed, 0 failed
```

**Case D is deliberately the opposite of `101`'s case D and that is the point.**
`101`'s control was the pre-ear-glow base and carried no query at all, so it
asserted *zero* rejects. This family's control is byte-identical to the
**standing default**, which carries `101`'s three queries — so it must be
rejected under `CALLISTO_RAYQ_DISABLE=1` exactly like the live rungs.
**There is no ray-query-free control in this family any more.** If ray query
ever becomes unavailable, the fall-back is not "the default without thinglow";
it is vanilla.

---

## 9. Rungs, and the SETTINGS CONTRACT — state it BEFORE the launch

| rung | what it is |
|---|---|
| `thinglow-hit` | **DIAGNOSTIC, shoot this first and in the same frame.** Paints the committed thickness as a ramp on gated pixels, independent of the transfer: **BLUE at 0.3 mm → GREEN at 25 mm**, **RED** where B committed a same-instance wall but C found the exit point occluded. No transfer, no albedo, no `k`; scaled by the sun radiance (`101` §12.3 — a paint fixed in absolute radiance is unreadable next to a lit surface) |
| `thinglow` | `k = 0.5`, `ld = 2 mm` |
| `thinglow-hi` | `k = 1.0`, `ld = 2 mm` — the **only** variable between it and `thinglow` is `k` |
| `thinglow-ctl` | `k = 0`, **byte-identical to the standing default**. The A/B control |

**Required game settings, stated here and not to be inferred from the capture
afterwards:**

* `ser = class`
* `shadowset = full-shadow`
* `ptq` unchanged from the standing contract
* **Russian roulette OFF**
* **Photo mode / reference path-tracer reach — let it converge.** The gate is
  `path == 0`, so this rung only ever paints the primary bounce; a noisy
  1-spp read is not a read.
* The **sun LOW and BEHIND** a curtain, tent panel, umbrella or plastic sheet,
  with the camera on the **shaded** side.
* **A curtain or plastic sheet, NOT a market tarp.** `94` §14.2a measured market
  tarps at `metallic ≥ 0.5`; the gate rejects them. A frame containing only a
  tarp will read as a total miss and would be misinterpreted as the premise
  failing.
* **A FACE in the same frame** as the skin control — the ear glow must look
  identical to the `-ctl` shot.
* `thinglow-hit` and `thinglow` in the **same frame**, same camera.

Deploy: the game runs **copies**. `cmp` the parked sets or `make install`
before reading a launch — a launch log against stale bytes is not evidence.

---

## 10. Pre-registered interpretation table

Fill these in **after** the shot; every row that no frame answers stays VOID.

| # | observation | reading |
|---|---|---|
| 1 | `-hit` paints **nothing** anywhere | either the gate never opens or thin geometry carries no interior backface. **The rung is dead**; §12's next step is a `class` census on a curtain, not a `k` change |
| 2 | `-hit` paints **BLUE** on curtains/sheets | the premise holds, thickness reads 0.3–3 mm. **Go**. |
| 3 | `-hit` paints **GREEN** on curtains | thickness reads 12–25 mm — the query is finding a *different panel*, not the far wall. `tmax` is too wide; retry at 8 mm |
| 4 | `-hit` paints **RED** on curtains | B commits but the exit point is occluded. Either the curtain is doubled, or the sun direction is wrong for the frame |
| 5 | `-hit` paints on **foliage** and little else | §6's known false positive is the dominant term. Add `class != 5` |
| 6 | `thinglow` glows on curtains, ear glow **visibly unchanged** | **SHOT.** §7's bit-identity confirmed on screen |
| 7 | `thinglow` glows on curtains, ear glow **changed** | §7 is wrong somewhere the bytes do not show. Stop; do not ship |
| 8 | `thinglow` blows out (white sheets clip) | `k = 0.5` too high; the ladder needs a **`-lo`** rung, and `-hi` is the wrong direction |
| 9 | glow appears but is **untinted** (everything white) | the albedo clone is reading the wrong channel — `noalbedo` shipped by accident. Gate 7 says it did not, so this would falsify gate 7 |
| 10 | a **hard step** at the terminator on a folded curtain | expected — there is no wrap smoothstep (§12). One-instruction fix named there |
| 11 | frame time regresses > 5 % | the three added queries at path 0 are not free after all; measure with `-ctl` in the same session |

**VOID** — every row. Nothing has been on screen.

---

## 11. Cost

* **+3 ray queries per pixel, at path vertex 0 only** (the `path == 0` term).
  On a shut gate the cull mask is `0`, so all three are guaranteed misses.
* **Zero added control flow.** No branch, no loop, no new block — the gate is a
  cull mask, not an `if`.
* **+3 `OpImageFetch`** per invocation, from the cloned material chain (§2.1).
* **+2 732 bytes** per patched module (311 756 → 314 488 on
  `1271d3815051da17`), **+0.9 %**; 139–146 disassembly lines.
* **6 live ray query objects** in one raygen. The RT pipeline links on an
  RTX 4070 (§8.1 case A). Register pressure is **not** measured.

---

## 12. What is NOT done

* **No wrap / terminator smoothstep.** `101` had `smoothstep(0, wrap, −N·S)`;
  the brief specified the transfer exactly and it does not include one, so a
  folded curtain can show a hard step where `N·S` crosses zero. The fix is
  `101`'s own one instruction and is pre-registered as row 10.
* **No thickness floor.** `101` §18's `NMax(t, t_cap)` exists because thin ears
  blew out; the same transfer, monotone in `1/t`, is now aimed at *paper*, whose
  `t` can be 0.3 mm. If row 8 fires, the floor is the fix, not `k`.
* **No `class != 5`.** Backlit foliage will glow with a card-gap thickness (§6).
* **`ld` is one scalar for cloth, paper, PVC and plastic.** A per-channel `ld`
  would give the red-shift that makes `101`'s ear glow look like flesh; here
  all the colour is albedo and the transmittance is grey.
* **Nothing shot.** No frame, no launch, no `make install`, no commit.
* **Class 8 excluded for nothing** (§4.3).
* **The market tarp is a false negative** (§0) and it was `94` §14.2a's headline
  false positive — the one surface most likely to be reached for as the test
  case is the one surface this gate rejects.

---

## 13. Files

| file | what |
|---|---|
| `dev/patch_thinglow.py` | the patcher. Structural detectors only, no hard-coded SSA ids; refuses to build on a base that is not the ear-glow stack; 8 `--decoy` modes |
| `dev/verify_thinglow.py` | re-derives all 14 check groups from the shipped `.spv`; `--negative`, `--control`; **check 14 is the ear-glow-intact proof** (§7) |
| `dev/build_thinglow.sh` | ten gates, four rungs, sixteen decoys; `--install` parks under NEW names only and refuses to overwrite a directory it did not create |
| `dev/selftest_thinglow.sh` | the driver half; 25 checks, no game; the VkDevice probe is **extracted read-only** from `dev/selftest_earglow_rq.sh` so the two cannot drift |
| `swaps.thinglow{,-hit,-hi,-ctl}/` | 93 modules each, 10 patched (0 for `-ctl`) |

Content shas (`cat` of all 93 `.spv` in name order):

| set | content | raygen half |
|---|---|---|
| `thinglow-hit` | `778947d01c6bb05c` | `315f338d5f5a5a4f` |
| `thinglow` | `3a2209ddf962d635` | `f245703021c10aa8` |
| `thinglow-hi` | `c9c469512e4a5bdf` | `7f2400f33aea1f00` |
| `thinglow-ctl` | `3bb0aee03a1bfda8` | `20d5c23ea50e339e` |
| (base) | `3bb0aee03a1bfda8` | `20d5c23ea50e339e` |

**Nothing existing was edited.** `init.lua`, `swap_layer.c`, the `Makefile`,
`CURRENT.md`, `GOTCHAS.md` and every existing `dev/` script and handoff
document are untouched; the two verifiers and the earglow self-test are
imported / read only.

---

## 14. `init.lua` entries to add

**This document does not edit `init.lua`.** Add these four entries to
`SKIN_LEVELS`, after the `earglow-cap6` block (around line 531) and before the
`102` contact-rq block, exactly as written:

```lua
    -- 105: BACKLIT THIN-SURFACE TRANSLUCENCY. 101's ear-glow construction with
    -- the skin gate INVERTED: class != 1/4/8, metallic < 0.1, roughness > 0.5,
    -- backlit, primary bounce only. Sunward query B now runs 0.3 -> 25 mm
    -- (an ear is 1.5 -> 18 mm), and the transfer is ONE exponential at
    -- ld = 2 mm times the module's own squared base colour, so a red tarp
    -- glows red. STACKED on the default: these carry 101's three ray queries
    -- AND 105's three, six live query objects per raygen (driver-proven,
    -- selftest 25/25). The ear glow is BIT-IDENTICAL on skin -- the gate's
    -- first term is class != 1 and the k select's false arm is NEGATIVE zero.
    -- The CONTROL is thinglow-ctl, byte-identical to the DEFAULT above.
    -- KNOWN FALSE NEGATIVE: market tarps read metallic >= 0.5 (94 sec 14.2a)
    -- and this gate REJECTS them. Shoot a CURTAIN or plastic sheet.
    -- KNOWN FALSE POSITIVE: alpha-tested foliage cards (class 5, not gated)
    -- read the card GAP as thickness -- handoff/105 sec 6 keeps the Opaque
    -- ray flag deliberately, because a ray query never runs an any-hit shader.
    -- BACKLIT frame required, with a FACE in it as the skin control.
    -- Read handoff/105 sec 9 and shoot thinglow-hit in the SAME frame.
    { id = "thinglow-hit", label = "DIAGNOSTIC: thin translucency -- BLUE = 0.3 mm same-instance wall sunward, GREEN = 25 mm, RED = it cannot see the sun" },
    { id = "thinglow",     label = "Backlit thin translucency (curtains/tents/sheets/paper, k=0.5, ld=2 mm) -- STACKS on the DEFAULT, ear glow unchanged" },
    { id = "thinglow-hi",  label = "Backlit thin translucency HI (k=1.0, same ld=2 mm) -- the ONLY variable vs thinglow is k" },
    { id = "thinglow-ctl", label = "CONTROL for thinglow -- byte-identical to the DEFAULT stack above" },
```

Park them first: `./dev/build_thinglow.sh --install`.
