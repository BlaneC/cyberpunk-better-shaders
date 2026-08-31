# 40 — Material sub-enum probe (G-U4) + ungated sheen probe (A2)

Written 2026-08-30. Prompt: *build the first launch experiment — the material
sub-enum probe (gate G-U4 in `38-WILD-IDEAS.md`), merged with the ungated
cloth-sheen probe (idea A2), as two swap sets from one build script.*

---

## 0. Verdict first

> **`probe-both` LAUNCHED 2026-08-31 — the result is `57-SUBTYPE-DECODED.md`.**
> The §0 falsifier does **not** fire: the frame paints in several hues, so the
> sub-enum is readable from compute and `& 31` survives. **G-U4 opens, but the
> field is too coarse to build on**: chrome has no own subtype (A8 dies), skin
> does not split (question (c) answered *no*, so `c1sub` need not launch), and
> hair carries at least two subtypes. **A2/A3 sheen is still unanswered — the
> `both` merge confounded it** (`57` §4); `probe-sheen` remains the clean read.
> `sub`, `cls` and `c1sub` have still never been on screen alone.
>
> **Update 2026-08-31 00:47: `probe-sheen` ran alone (user launch, serve
> audit-verified, settings pinned) — the sheen RENDERS: white grazing rim on
> cloth, vegetation, skin. A2/A3 answered YES; `58` is the result doc.**

~~**Built, offline-verified, and never seen.**~~ Five swap rungs exist, all 386
patched modules assemble and validate at their own target env, and the paint
chain and the sheen chain have both been re-read out of the emitted SPIR-V and
re-evaluated numerically against their closed forms. A swap HIT is not
execution; each rung is unproven until a screenshot says otherwise.

| claim | confidence |
|---|---|
| The five rungs are byte-distinct, valid SPIR-V, and carry the intended instructions | **high** — 386/386 `spirv-val` clean at `spv1.3`; emitted `.spvasm` diffed line-by-line against vanilla; palette and sheen re-evaluated from the emitted instructions (§8) |
| `cls` is the exact paint that produced `pics/panam_working_small.png` | **high** — build-time assertion, byte-identical to `patch_compute_skin.py --tier hunt` on all 76 modules |
| `sub` and `cls` paint the *same 76 modules at the same 151 write lines* | **high** — measured from the build records (§8, E5) |
| The G-buffer sub-enum is a real 5-bit field of the same byte as the class | **high** — 81 modules derive both `>>5` and `&31` from one value (§2) |
| Class 2 is tested by no shader in the dump | **high** — whole-dump census, §2 |
| The paint will render | **unknown** — this is what the launch decides |
| The sheen will render | **unknown** — same |
| The sub-enum means "material subtype" | **unknown, and this is the question** — the census proves the field is *read*, not what it *means* |

**Falsifier**, stated up front: if `cls` paints the frame in flat class colours
and `sub` — same modules, same write lines, one extra `OpBitwiseAnd` per site —
comes back **visually vanilla**, the sub-enum *read* is broken (folded away, or
never reaching the select chain), and G-U4 is answered *no* on this route. Note
that a uniformly-zero field is **not** this outcome: value `0` paints bright
orange-red, so a constant field gives a uniform colour, not a vanilla frame —
that case is a different, and more interesting, result (§10). If **both** rungs
come back vanilla, the failure is the install/serving path, not the probe, and
nothing about G-U4 has been learned.

---

## 1. What exists

New files, all mine, no collisions:

| path | what |
|---|---|
| `dev/patch_subtype_probe.py` | the patcher: 5 tiers, palette, sheen |
| `dev/patch_subtype_probe.sh` | builds all 5 rungs; `--install` parks them; `--legend` / `--legend-md` |
| `dev/census_subenum.py` | the §2 census, one command over the raw dump (~1 s) |
| `swaps.probe.{sub,c1sub,cls,sheen,both}/` | the built rungs (git-ignored) |
| `handoff/40-SUBTYPE-PROBE.md` | this file |

`dev/patch_compute_skin.py` and `.sh` are **not modified**. The probe *imports*
their class machinery (`find_class_anchor_variant`, `build_hunt_writes`) rather
than copying it, plus `patch_skin_brdf` (`apply_edits`, `replace_all_uses`,
`find_ggx_sites`, `roundtrip_check`), `patch_shadow_brdf` (`CFG`,
`find_class_fetch`), `patch_chs_brdf` (`load_lenient`, `uses_of`) and
`patch_compute_brdf` (`find_image_writes`, `detect_target_env`). Three things
did not exist and had to be written:

* `acquire_material_word()` — the class machinery hands back `y >> 5`; the
  sub-enum needs the byte **before** the shift.
* `emit_material_word()` — the refetch chain, stopped one instruction short of
  the shift.
* `find_sheen_inputs()` — NoH / NoL / NoV / the Vis anchor at a GGX site.

`swap_layer.c` was read and never touched. Nothing named `*ser*` was touched.

### The five rungs

| rung | tier | what it does | why it exists |
|---|---|---|---|
| `sub` | `sub` | `palette[word & 31]` multiplied into every radiance write, **ungated** | **the experiment** (G-U4) |
| `cls` | `cls` | the existing 10-class palette on `word >> 5` | **positive control** — byte-identical to `--tier hunt`, the paint that is already known to render |
| `c1sub` | `c1sub` | the sub-enum paint, but only where `(word >> 5) == 1` | isolates question (c): does skin split? |
| `sheen` | `sheen` | ungated Charlie sheen at every GGX site | **A2** |
| `both` | `both` | `sub` + `sheen` in one module | `38` §7's one-launch merge |

### Coverage, measured

| rung | modules | paint writes | refetched | own word used | GGX sites | sheen spliced | declined |
|---|---|---|---|---|---|---|---|
| `sub` | 76 | 151 | 31 | 60 | — | — | 8 modules |
| `c1sub` | 76 | 151 | 31 | 60 | — | — | 8 |
| `cls` | 76 | 151 | n/r | — | — | — | 8 |
| `sheen` | 82 | — | — | — | 481 | **464** | 2 modules, 17 sites |
| `both` | 76 | 151 | 31 | 60 | 453 | 437 | 8 modules, 16 sites |

`n/r` = the imported hunt builder does not record a refetch count.

Reading the declines:

* The paint rungs cover **76 of the 84 anchored compute libs**. Seven decline
  with *"no material G-buffer read found (neither `>>5` nor `&31`)"* — they are
  not class-aware at all. The eighth, `ab0bc2fee876d489`, declines with *"no
  image write reachable for the sub-enum paint"*: it has no radiance image
  write to multiply into. That module is the single difference between the
  probe's 76 and the shipping skin overlay's 77.
* The sheen rung covers **82 of 84** — the two it declines
  (`3acf2ec0e9eb2693`, `d1a91e5e7152cdf7`) have no `1/pi` constant, so they
  carry no detectable GGX site at all. That is all 77 of the shipping skin set
  **plus five modules the skin overlay has never touched** (`57fa8971e5d4bbce`,
  `e47009fbdc79c311`, `ee2dda2c2440be84`, `f568c84d782802c0`,
  `f7a29100e09ef0d7`) — they have GGX sites but no class read, so a class-gated
  patch could never reach them. An ungated probe can. That is a small,
  unplanned bonus of A2's premise.
* All **ten dispatch-proven tile evaluators** of `10-DISPATCH-TRUTH.md`
  (`03dc7a51279e7427`, `0e5e5a6a78fdf1dd`, `20e6c7b3626ae0d6`,
  `2e73a32c35778d85`, `4d46848998312027`, `7ae88cd87950a898`,
  `81c13c37112d09df`, `99bb7c2698997b2a`, `9a3fa53c53a3a21b`,
  `d5166c0f1ea464b9`) are present in **every** rung. Verified by name.

---

## 2. The census, tightened — and a correction to `38` §1.3

`38` §1.3 lists the sub-enum values seen in GLCompute as `{0,16,17,21,25,30,31}`
and a class census of `{0:115, 1:531, 3:225, 4:328, 5:58}`. Those numbers were
sanity-checked before anything was built, because the whole probe rests on them.

**Method.** `python3 dev/census_subenum.py ~/callisto_dump` — a binary SPIR-V
word scan over all 3273 modules, about a second, no `spirv-dis` (and no
`grep -r`, which silently returns 0 for strings that are present — GOTCHAS). A module
counts as *testing the sub-enum* only when **one value feeds both `>> 5` and
`& 31`**; that pairing is what makes the low bits a sub-field of the material
byte rather than an unrelated mask. Values are collected from `OpIEqual`,
`OpINotEqual` **and `OpSwitch` literals** — the switch arm matters, see below.

**Results.**

| quantity | value |
|---|---|
| modules where one word feeds both `>>5` and `&31` | **81** (59 GLCompute, 12 Fragment, 10 RayGeneration) |
| of those, testing a specific sub-enum value | **67** |
| sub-enum values tested (modules each) | `12:8 13:8 14:8 15:8 17:13 21:64 25:62 26:1 30:8 31:10` |
| sub values tested **in GLCompute** | `{17, 21, 25}` only |
| sub values tested **in Fragment** | `{12,13,14,15,17,21,25,26,30,31}` |
| class values tested, whole dump (modules / sites) | `0: 69/123`, `1: 124/342`, `3: 99/172`, `4: 114/260`, `5: 58/86` |
| class 2, 6, 7 | **tested by zero modules, anywhere** |

Three corrections, all minor and none of which changes the plan:

1. **`0` and `16` are not sub-enum values.** They appear in `38` §1.3's list
   because `& 31` is applied to some *other* word in those modules. Under the
   one-word-feeds-both rule they vanish. *(confidence: high — the rule is
   mechanical and the scan is reproducible.)*
2. **There is a tenth value, `26`**, in exactly one Fragment module
   (`ddc88ec4cbd88ec4.dxil`) and nowhere in compute. It was found after the
   palette was fixed and keeps a dark slot rather than displacing one of the
   nine bright ones; the legend still names it, so if it appears it is readable.
3. The class census differs in magnitude from `38` §1.3 (counting method:
   modules vs comparison sites), but the load-bearing conclusion — **class 2 is
   never tested** — reproduces exactly.

**The finding that matters for reading the screenshot.** The compute evaluators
this probe patches only ever *branch* on `{17, 21, 25}`. That is what compute
needs, not what the G-buffer holds: a shader only tests what it must. So the
paint may legitimately show values compute never tests, and that is a result,
not a bug. Conversely, if the frame comes back showing only three colours, that
is also a result: it means the field really is near-ternary in practice.

---

## 3. Set 1 — what the sub-enum paint actually emits

Per radiance image write, inserted immediately above it:

```
%g_v  = OpIEqual %bool %sub %uint_v                 ; v = 0 .. 31   (32)
%s    = OpSelect %float %g_v %tint_v_ch %prev       ; 3 channels x 32 (96)
[c1sub only]  %s = OpSelect %float %isClass1 %s %float_1      (3)
%n_ch = OpFMul %float <original component> %s       ; 3 channels     (3)
%nt   = OpCompositeConstruct %v4float %n0 %n1 %n2 <original alpha>   (1)
```

and the write's texel operand is rewritten to `%nt`. 132 instructions per site
(135 for `c1sub`). The module-level `%sub = OpBitwiseAnd %uint %word %uint_31`
is emitted **once**, next to the module's own material extract.

Three things in there are deliberate and each one is a trap that has bitten this
repo before:

* **Multiply, not replace.** The scene's own shading survives, so a painted
  region is still recognisable as a jacket or a cheek. A replace would give a
  flat colour field that is easier to read and impossible to attribute.
* **The refetch.** 31 of the 151 write sites are in a block the module's own
  material fetch does not dominate. Those sites reissue the fetch locally
  (`emit_material_word`, i.e. `find_class_fetch`'s chain stopped before the
  shift). 60 of 76 modules had at least one site where the module's own word
  reached; 16 refetched everywhere.
* **No dead top-level instruction.** If *every* write in a module refetches,
  the module-level `& 31` is never consumed — and dead code that reads a live
  id validates perfectly clean and looks exactly like a working splice. That is
  the `08-DUAL-LOBE` dead-sheen trap. The pre-block is emitted only when
  `own_word_used` is true, and that flag is recorded per module in the build
  record.

Also honoured: every uint constant is materialised **once** (`mod.uconst()` has
no pending-declaration cache — GOTCHAS — and 32 values × up to 8 writes would
otherwise redeclare ids and fail validation), and `find_image_writes()` runs
**before** any `replace_all_uses` pass in the `both` tier (GOTCHAS 12:
detectors before rewriting emitters).

---

## 4. The colour legend — read the screenshot against this

**Encoding.** 16 hues 22.5° apart × 2 gains = 32 injective slots, one per
sub-enum value. 32 hues cannot be read off a tonemapped screenshot, and 8
buckets would throw away the answer, so the palette is **prioritised by
evidence** instead of being uniform:

* the **9 most-tested values** get the 8 *cardinal* hues (45° apart: red,
  chartreuse, cyan, violet, amber, blue, spring-green, magenta) at high gain,
  plus a near-black ninth. These are the most different things the palette can
  produce and the values most likely to be on screen.
* everything else gets the 8 *in-between* bright hues (0–7), then the 16 dark
  ones.

**Decode in three steps.**

1. **Bright and a pure primary/secondary?** → one of the nine measured values.
2. **Bright but an in-between hue** (orange-red, yellow-green, green,
   turquoise, azure, blue-violet, purple, crimson)? → a value in **0–7**, i.e.
   the low block, which no shader tests.
3. **Dark / desaturated?** → 8–11, 16, 18–20, 22–24, 26–29. For an exact value,
   sample the pixel in an image editor and match the **R:G:B ratio** below
   (absolute brightness varies with the scene; the ratio does not). Near-black
   that is *not* shadow-shaped is `15`.

Channels are floored at `0.04` before gain, on purpose: a hard zero reads as
"no red at all" through the AgX chain and is hard to tell from a shadow, where
a lifted floor reads as a *tint*.

Regenerate any time with `python3 dev/patch_subtype_probe.py --legend-md`.

| sub-enum | tested? | appearance | RGB multiplier |
|---|---|---|---|
| **0** | - | bright orange-red | `3.20, 1.28, 0.13` |
| **1** | - | bright yellow-green | `2.82, 3.20, 0.13` |
| **2** | - | bright green | `0.51, 3.20, 0.13` |
| **3** | - | bright turquoise | `0.13, 3.20, 2.05` |
| **4** | - | bright azure | `0.13, 2.05, 3.20` |
| **5** | - | bright blue-violet | `0.51, 0.13, 3.20` |
| **6** | - | bright purple | `2.82, 0.13, 3.20` |
| **7** | - | bright crimson | `3.20, 0.13, 1.28` |
| **8** | - | dark red | `0.45, 0.02, 0.02` |
| **9** | - | dark orange-red | `0.45, 0.18, 0.02` |
| **10** | - | dark amber | `0.45, 0.34, 0.02` |
| **11** | - | dark yellow-green | `0.40, 0.45, 0.02` |
| **12** | yes (F) | bright blue | `0.13, 0.90, 3.20` |
| **13** | yes (F) | bright spring-green | `0.13, 3.20, 0.90` |
| **14** | yes (F) | bright magenta | `3.20, 0.13, 2.43` |
| **15** | yes (F) | near-black | `0.05, 0.05, 0.05` |
| **16** | - | dark chartreuse | `0.23, 0.45, 0.02` |
| **17** | **yes (C)** | bright chartreuse | `1.66, 3.20, 0.13` |
| **18** | - | dark green | `0.07, 0.45, 0.02` |
| **19** | - | dark spring-green | `0.02, 0.45, 0.13` |
| **20** | - | dark turquoise | `0.02, 0.45, 0.29` |
| **21** | **yes (C)** | bright red | `3.20, 0.13, 0.13` |
| **22** | - | dark cyan | `0.02, 0.45, 0.45` |
| **23** | - | dark azure | `0.02, 0.29, 0.45` |
| **24** | - | dark blue | `0.02, 0.13, 0.45` |
| **25** | **yes (C)** | bright cyan | `0.13, 3.20, 3.20` |
| **26** | yes (F, 1 module) | dark blue-violet | `0.07, 0.02, 0.45` |
| **27** | - | dark violet | `0.23, 0.02, 0.45` |
| **28** | - | dark purple | `0.40, 0.02, 0.45` |
| **29** | - | dark magenta | `0.45, 0.02, 0.34` |
| **30** | yes (F) | bright violet | `1.66, 0.13, 3.20` |
| **31** | yes (F) | bright amber | `3.20, 2.43, 0.13` |

`(C)` = tested in compute as well as fragment; `(F)` = fragment only. **The
three `(C)` values — 17 chartreuse, 21 red, 25 cyan — are the ones the patched
modules themselves branch on**, so they are the highest-prior colours in the
frame. If the screen is mostly chartreuse/red/cyan, the field is doing exactly
what the compute shaders assume.

### The `cls` control legend (unchanged, from `patch_compute_skin`)

| class | colour | known |
|---|---|---|
| 1 | red | **skin** |
| 2 | green | *tested by no shader anywhere* |
| 3 | blue | |
| 4 | yellow | **hair** |
| 5 | magenta | |
| 6 | cyan | |
| 7 | orange | |
| 8, 13, 14 | violet, azure, lime | out of range for a 3-bit field; kept from the original hunt palette so `cls` stays byte-identical to it |

---

## 5. Set 2 — the ungated sheen probe (A2)

**What it is.** Estevez & Kulla "Charlie" sheen with Neubelt visibility, added
to the existing specular at every detected GGX site, **with no class gate**:

```
D_charlie(a, NoH)   = (2 + 1/a) * (1 - NoH^2)^(1/(2a)) / (2*pi)
V_neubelt(NoL, NoV) = 1 / (4 * (NoL + NoV - NoL*NoV))
spec' = spec + min(k * D_charlie * V_neubelt, cap)
```

`a = 0.35`, `k = 8.0`, `cap = 25.0`. `(2 + 1/a)/(2π)` and `1/(2a)` are folded at
build time, so a site costs **16 instructions**, one of which is the add.

**On the citation.** The brief names Zeltner, Burley & Chiang, *Practical
Multiple-Scattering Sheen Using Linearly Transformed Cosines* (SIGGRAPH 2022;
`tizian/ltc-sheen`). That is the better model and it is **not** what is spliced:
its fit lives in a 3-parameter table, i.e. a texture, i.e. a descriptor, i.e.
unlock **U1**, which is not built. The analytic Charlie lobe needs no resource
and has the same grazing-widening behaviour that separates cloth from plastic,
which is the only property this probe needs. Written down here so nobody reads
"LTC sheen" in a handoff and goes looking for a fit table in the module.

**Sizing — this is a diagnostic, not a look.** With the shipped knobs:

| NoH | NoL = NoV | added sheen |
|---|---|---|
| 0.99 | 0.90 | 0.006 |
| 0.90 | 0.70 | 0.16 |
| 0.70 | 0.50 | 0.79 |
| 0.30 | 0.30 | 2.65 |
| 0.10 | 0.10 | 8.02 |
| 0.00 | 0.05 | 15.86 |

Facing surfaces are essentially untouched; grazing silhouettes get a rim that is
several times the direct specular. Everything will look wrong. That is correct.

**Detection.** `find_sheen_inputs()` resolves NoH from the GGX **D** denominator
chain (`a2 - 1` → its `OpFMul` → the square) and the visibility term by two
site-keyed forms:

* **S** (height-correlated Smith): `OpFDiv 0.5 den`, with
  `den = NoV*sqrt(NoL²(1-a²)+a²) + NoL*sqrt(NoV²(1-a²)+a²)`
* **H** (the cheap form): `OpFDiv 0.25 den`, with
  `den = (NoL+NoV)*(1 - alpha/2) + alpha`

`spec` is the **unique** `OpFMul` consuming the Vis value — unique at 464/464
resolved sites, checked rather than assumed.

**Two detector bugs found and fixed during the build**, recorded because both
would have produced a plausible-looking build that measured nothing:

1. Anchoring the Vis on `find_ggx_sites`' `vd` collapsed coverage from 483 to
   56/481 — `vd` is "the first `OpFMul` consuming D", which is usually `D*NoL`,
   not `D*V`.
2. A non-site-local form-S detector searched the whole module for
   `OpFDiv 0.5 X` and **cross-wired multi-site modules**. Requiring each sqrt
   argument to be `OpFAdd(x, <this site's a2>)` fixed it. Final: 464/481 sites
   across 82 modules, **zero modules with no resolved site**.

**The 17 declines** are all shape declines (no site fails on dominance), one
site each in: `8609293ec4e6603f`, `d833f1776c01da9b`, `f10ec33383029699`,
`9a3fa53c53a3a21b`, `2a9ae2ee64269502`, `e55c289d0391bc16`, `7ae88cd87950a898`,
`99bb7c2698997b2a`, `fa7f49cc5acceb71`, `48d42444767a16b4`, `cf34f6a9263275f4`,
`42f0d5e99cfc5929`, `ba87088d5c78bff0`, `6671ffa6636bda22`, `be1e954d5223c782`,
`27004d6897ae1a80`, `f568c84d782802c0`. Every one of those modules keeps its
other sites, so no module is silently unpatched.

**One honest caveat on magnitude.** 464 sheen sites map to 365 distinct
`(NoH, NoL, NoV)` contexts (re-measured from the emitted SPIR-V, E7), so **99 sites add the sheen twice** to what is
effectively one light — dual-lobe evaluation sites sharing a light. The probe
is therefore up to 2× brighter than the table above in those places. For a
diagnostic sized to be unmistakable this is harmless; for anything that ever
becomes a feature it is a bug, and it is written down here so it is not
rediscovered.

---

## 6. Wiring: why the rungs ride the `skin` overlay

The brief allowed either the existing set-selection mechanism or two plain swap
directories with an env var. **Neither of the alternatives works**, so the rungs
ride `skin`:

* A new overlay name (`probe`) would need either an edit to `swap_layer.c`'s
  default list (`"ser,skin,shadowcull,ptq,ptrefl"` as of the SER work in `41`)
  — a file owned by another agent right now — or `CALLISTO_OVERLAYS` set in the
  Steam launch options, since an env var does not otherwise reach the game
  under Proton.
* And a separate `probe` overlay would be **worse than the skin.set route even
  if it were free**: overlays are first-file-wins and *coexist*. A `probe`
  overlay leading the list would shadow `skin` for the 76 ids it carries while
  `swaps.skin/` still served `ab0bc2fee876d489` — a silently mixed payload,
  half probe and half shipping build. Riding `skin.set` guarantees a single,
  whole, known payload for the launch.

So each rung is parked as **another level of the existing skin overlay**:

```
~/.local/lib/callisto/skin.set/probe-<rung>/     <- --install puts them here
brdf_params.txt:  skinspec=probe-<rung>
sync_settings.sh: cp skin.set/probe-<rung>/*.spv -> swaps.skin/
```

This is legitimate rather than a hack: the probe targets *exactly* the modules
the skin overlay already owns (both are selected by the same anchored scan on
`1/pi` + the Frostbite `0.107508637`), and `sync_settings.sh` validates a level
only with `-d skin.set/$want_skin`, so an arbitrary name works. Everything
downstream keeps working for free — the payload hash moves, so the pipeline
caches are evicted, and `~/callisto_launches.log` records the content hash
actually served.

**First-file-wins check (required by the brief).** No collision:

* `sync_settings.sh` does `rm -f swaps.skin/*.spv` before copying, so the probe
  **replaces** the skin overlay for that launch rather than layering on it.
  There is never a second file for the same module id.
* The probe rungs deliberately carry **no tier-1 c1 splice and no gloss**. A
  diagnostic must not have a second edit in it.
* Nothing else patches these GLCompute libs: `shadowcull`, `ptq`, `ptrefl` and
  the new `ser` overlay (`41`) are all **ray-tracing** stages, and the base
  `swaps/` holds only two reference raygens. Verified by listing the install
  directory. The probe and the SER build can therefore be served in the same
  launch without interfering — though for a clean read, don't.
* Consequence to expect: **the skin BRDF and the oily-skin gloss are OFF for
  the probe launch.** Faces will not look like the shipping build. That is
  intended and is why `cls` is in the set — it is the same *paint* the shipping
  A/B screenshot used, with the same absence of c1.

---

## 7. Exact build, install, launch, capture

### Build (no install; this is what has been run)

```bash
cd ~/Documents/'NVIDIA Nsight Graphics'/GraphicsCaptures/CallistoSSS
./dev/patch_subtype_probe.sh
```

Output, verbatim, from the run that produced the current tree:

```
swaps.probe.sub      76 modules
swaps.probe.c1sub    76 modules
swaps.probe.cls      76 modules
swaps.probe.sheen    82 modules
swaps.probe.both     76 modules
cls == patch_compute_skin.py --tier hunt ?  identical=76 differ_or_missing=0
```

The script asserts, and exits non-zero if either fails: (1) every rung differs
from every other rung — two rungs that came out byte-identical would make
flipping the selector compare nothing; (2) `cls` is byte-identical to
`patch_compute_skin.py --tier hunt` — if the control drifts, a null result on
`sub` stops being attributable.

`./dev/patch_subtype_probe.sh --legend` / `--legend-md` prints §4's table.
`--set k=v` forwards knobs (`k_sheen`, `a_sheen`, `sheen_max`, `gain_hi`,
`gain_lo`, `gain_black`).

### Install (opt-in — nothing was installed by me)

```bash
./dev/patch_subtype_probe.sh --install
```

parks the five rungs into `~/.local/lib/callisto/skin.set/probe-{sub,c1sub,cls,sheen,both}/`
with `cp -pf` (mtimes from the build, so an unchanged selection hashes the same
next launch and the pipeline caches survive — the `cp -p` gotcha).

**Order matters:** `dev/patch_compute_skin.sh --sets` does `rm -rf skin.set/`
on every run. Run the gloss ladder build **first**, the probe install
**second**; re-run `--install` after any ladder rebuild.

### Select a rung

Edit
`$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt`
and set:

```
skin=on
skinspec=probe-sub          # or probe-cls / probe-c1sub / probe-sheen / probe-both
```

Then launch **through the Steam launch options** so `sync_settings.sh` runs.

**Two CET caveats — expected, not faults:**

1. `init.lua:106` coerces any `skinspec` it does not recognise back to `off`
   and `onInit` rewrites `brdf_params.txt` (`init.lua:297–299`). The host script
   reads the file *before* the game starts, so the rung **is** served for that
   launch — but the file is reset afterwards. **Re-write the line before every
   probe launch.**
2. The settings page will show
   *"WARNING: this session is running skin gloss 'probe-sub', but the selector
   says 'off'."* That warning is the **confirmation that the probe was served**,
   not an error. `status.txt` will carry `want_skinspec=probe-sub` and
   `want_skinspec_req=probe-sub`.

### Confirm it was served before trusting the pixels

Two places, and they answer different questions.

* **In-session, "what did this launch ask for":** `status.txt`, next to
  `brdf_params.txt`, carries `want_skinspec_req=probe-<rung>` and
  `want_skinspec=probe-<rung>`. Note that its `last_resolve=` / `last_*` counts
  describe the **previous** launch — `sync_settings.sh` writes `status.txt`
  before the game starts and then deletes `last_run.json` — so do not read them
  as this session's HIT count.
* **After the session, "what was actually served":** `~/callisto_launches.log`
  gets one append-only line per launch, keyed on the **content hash** of
  `swaps.skin/`. Match `skin_sha` against the table below; this is the check
  that exists because a result was once credited to a set that had never been
  launched (`26` §7).

| rung | expected `skin_sha` |
|---|---|
| `probe-sub` | `a2490ac7921cd87f` |
| `probe-c1sub` | `09287eda2783b0b5` |
| `probe-cls` | `53722d3d833238ab` |
| `probe-sheen` | `5d24091dd8e9e93d` |
| `probe-both` | `69af98424a5e9c18` |

(Recompute any time: `cat swaps.probe.<rung>/*.spv | sha256sum | cut -c1-16`.)

`~/.local/lib/callisto/last_run.json` holds this session's per-overlay HIT
counts once the game exits. **A HIT is not execution** — it means the layer
handed the module over, not that the shader ran. Only the screenshot settles
that.

### Restore

Set `skinspec=off` (or use the CET selector). `skin.set/off` exists — it is the
tier-1 c1-only build, 77 modules — so the next launch copies it back over
`swaps.skin/` and the shipping behaviour returns. No rebuild is needed.

---

## 8. Verification — what was actually checked (evidence index)

| # | check | result |
|---|---|---|
| E1 | `spirv-val` at each module's **own** target env (`spv1.3`, from `detect_target_env`) | **386/386 clean** across all five rungs |
| E2 | Emitted `.spvasm` (id-preserving, from the patcher) diffed line-by-line against the vanilla `.spvasm`, all 386 modules | **no vanilla line is ever deleted**; modified vanilla lines = `sub` 151, `c1sub` 151, `cls` 151 (exactly one per radiance write), `sheen` 576, `both` 692 (the `spec` consumers rewritten by `replace_all_uses`). Everything else is pure insertion: +22543 / +23178 / +7277 / +8355 / +30402 lines |
| E3 | Hand-read the full diff for `4d46848998312027` (4 sheen sites) and `2e73a32c35778d85` (2 sites) | in `4d46`, 3 of 4 splices sit **immediately upstream** of that module's own `NMin(x, 100)` firefly clamp (patched lines 888/1269/1315 vs clamps at 892/1273/1318), as intended; the 4th site's specular is not clamped in vanilla either and is bounded only by the sheen's own `cap = 25`. `replace_all_uses` rewrote exactly the 3 consumers of that site's `spec` and left its def alone (`35` §6 practice: read the instructions, don't trust the exit code) |
| E4 | `cls` vs `patch_compute_skin.py --tier hunt` | identical=76, differ_or_missing=0 |
| E5 | `sub` / `c1sub` / `cls` / `both` module set and write-line set | **identical** — same 76 modules, same 151 lines |
| E6 | Palette select chain re-parsed **out of the emitted SPIR-V** and evaluated for all 32 inputs, all 3 channels, all 151 sites | **14496 evaluations, 0 mismatches** against `sub_palette()` |
| E7 | Sheen chain re-parsed from the emitted instructions and mirrored in Python at 8 probe points | **464 sites in 82 modules recovered; worst relative error 1.68e-07** vs closed-form Charlie x Neubelt |
| E8 | Dead-code audit (`own_word_used`) | pre-block emitted only where consumed; 16 modules refetch everywhere and correctly emit no module-level `& 31` |
| E9 | Rung pairwise difference assertion | every pair differs |
| E10 | Census reproducibility | `dev/census_subenum.py`, binary word scan over all 3273 modules, ~1 s; re-run today, reproduces §2 exactly |
| E11 | Rebuild reproducibility against the **current** tree (after the `39` translucency removal gutted `patch_compute_skin.py`) | all five tiers on `4d46848998312027` come out **byte-identical** to the shipped rungs; the `cls` control re-checked against `--tier hunt` today: identical=76, differ=0 |

**A note on why `spirv-dis` diffing was useless.** `spirv-as` renumbers every
id, so a round-trip disassembly diffs as thousands of lines. The diff that
matters is the patcher's own id-preserving `.spvasm` against the vanilla
`.spvasm` (E2). This is worth remembering; the first attempt at E2 produced a
diff that looked catastrophic and meant nothing.

---

## 9. Which scene to capture, and why

**One frame, one rung at a time, same camera.** Recommended order: `cls`
(control) → `sub` (experiment) → `sheen`. `c1sub` and `both` only if the first
three leave a question open.

**The scene.** A **daylight exterior with a companion NPC standing close**,
framed the same as `pics/panam_working_small.png`. That framing is not
aesthetic: `cls` is byte-identical to the paint that produced that screenshot,
so matching the frame makes the control directly comparable to an image that
already exists, and any difference is attributable to the build rather than to
the scene.

The frame must contain, in one shot:

* **bare skin** (face + hands/arms) — answers (c) via `sub` and `c1sub`;
* **hair** — the one non-skin class already known (`class 4`);
* **at least two visibly different fabrics** — denim and leather is the easy
  pair on most companions; a knit or printed cotton as a third is better,
  because the sheen probe's whole point is whether *fabric* separates from
  *plastic*;
* **one hard non-cloth reference** — car paint, painted metal, road surface —
  so "everything turned one colour" is distinguishable from "cloth turned one
  colour";
* **grazing silhouettes** — shoulders, sleeve edges, a shoulder bag strap. The
  sheen is a grazing effect; a head-on flat-lit shot will under-report it by
  more than an order of magnitude (§5's table).

Also take **one `skinspec=off` shot from the exact same spot** as the reference.
Note what that reference *is*: `off` serves the tier-1 c1 skin build, i.e. the
shipping look, not a vanilla frame. That is the right comparison anyway — it is
what the user sees every other launch — but do not describe it as "unpatched".
Without it, "looks normal" is not evidence of anything.

Avoid: night, heavy neon, rain, interiors with strong coloured practicals. The
paint is a multiply into radiance and a magenta light source will make a
chartreuse region unreadable.

---

## 10. What each outcome means

### `cls` (run this first — it is the gate on everything below)

| observation | meaning |
|---|---|
| flat class colours across the frame | the serving path works, the modules execute, the paint mechanism is live. Proceed. |
| **vanilla** | **stop.** The install/serving path is broken, or these modules are not executing this session. Nothing about G-U4 or A2 has been tested. Check `status.txt`'s `want_skinspec` and the `skin_sha` on this launch's line in `~/callisto_launches.log` (§7) before touching the patcher. |

### `sub`

| observation | meaning |
|---|---|
| several distinct hues, correlated with material regions | **G-U4 opens.** The sub-enum is readable in compute and carries per-material information. Decode the regions against §4 and you have the class/subtype ↔ material map the repo has never had. |
| mostly chartreuse / red / cyan (17 / 21 / 25) | the field is effectively ternary in practice — the compute shaders' `{17,21,25}` assumption is the whole story. G-U4 opens, but the field is coarser than hoped. |
| **one uniform colour everywhere** | the sub-enum is constant in this scene. Sample the pixel and read the value: if it is `0` (bright orange-red) the field is unpopulated *in the G-buffer as compute sees it*, even though 67 modules read it — which would mean the sub-enum is a **fragment-stage-only** field. That is a real, publishable finding and it kills G-U4 on the compute route. |
| **vanilla, while `cls` painted** | the sub-enum read itself is broken, or `& 31` is being folded away. `sub` differs from `cls` by exactly one `OpBitwiseAnd` per site and paints the same 151 lines, so this narrows to the read. Re-read `E6`; suspect an optimiser, not the patch. |

### `c1sub`

Run only if `sub` paints. Skin painting in **more than one colour** answers
question (c) *yes* — class 1 has sub-structure, and the skin BRDF could be
specialised per subtype (face vs body vs cyberware skin). One colour answers it
*no*, and that closes a whole line of speculation cheaply.

### `sheen`

| observation | meaning |
|---|---|
| grazing rim on clothing, strongest on fabric silhouettes | **A2 succeeds.** The compute-BRDF track is alive and reaches cloth. The class gate and hair's estimated tangent are the remaining suspects for earlier null results (`22` §8), not the mechanism. |
| rim on **everything** including car paint and road | the splice works but the GGX sites are shared across materials — expected for an ungated probe, and it still proves the mechanism. Gate it later; the finding stands. |
| **vanilla, while `cls` painted** | this is the important negative. A 16-instruction additive lobe at 464 sites in 82 modules, with no gate, produced no pixels — while a paint in the *same modules* did. That would mean the specular path in these evaluators does not reach the screen, and **the compute-BRDF track is cleanly dead**: no future gated cloth/hair BRDF work on this route can succeed. That is worth more than a positive. |

### What a null result rules out

A **`cls`-null** rules out nothing — it is an infrastructure failure and must be
fixed before any of this counts.

A **`sub`-null with `cls` painting** rules out reading material subtype from the
compute G-buffer fetch. It does **not** rule out the sub-enum being meaningful:
the Fragment stage tests ten values, so the field is real; it would only be
unreachable from where this repo can patch.

A **`sheen`-null with `cls` painting** is the strongest single result available
from this launch. It rules out **every future BRDF edit at the specular site in
the compute evaluators**, gated or not — cloth sheen, retro-reflection, the
hair dual-lobe revival, all of it. `22`'s feasibility question would be answered
*no* for good, and the remaining reach would be paint-only (which the class hunt
already demonstrated) plus the RT and LUT levers of `17`.

---

## 11. Built vs unproven — the split

**Built and verified offline (high confidence):**

* Five byte-distinct swap rungs, 386 modules, all valid at `spv1.3`.
* The paint reaches 76 of 84 anchored compute libs at 151 radiance writes,
  including all ten dispatch-proven evaluators.
* The sheen reaches 464 of 481 GGX sites in 82 modules, five of which the skin
  overlay has never been able to touch.
* `cls` is the known-rendering control, byte-for-byte.
* The emitted arithmetic matches its closed form to 1.7e-07 (sheen) and exactly
  (palette) — both re-derived from the emitted SPIR-V, not from the generator.
* The census in §2, reproducible from the raw dump in ~1 s.

**Not proven, and not claimed:**

* That any of it renders. **Nothing here has been on screen.** No rung has been
  installed, and the game has not been launched.
* That the sub-enum means "material subtype". The census proves it is *read*;
  meaning is exactly what the screenshot is for.
* That the sheen looks like cloth. It is sized to be unmistakable, not correct;
  §5's double-add on 99 sites is a known magnitude error, harmless for a probe.
* That the paint survives whatever the engine does downstream of these writes
  (temporal resolve, DLSS, the AgX chain). `cls` is in the set precisely
  because it is the one rung already known to survive that path.

**Not done, deliberately:** no commit (house rule), no install, no launch, no
edit to `swap_layer.c` or anything `*ser*`, no edit to `dev/patch_compute_skin.py`
or `.sh`.

---

## 12. Housekeeping

`.gitignore` gained `swaps.probe.*/` — the rungs are diagnostics, never
installed by a plain build, and like every other generated swap directory they
are not redistributed. The per-module build records (`.rep.<id>.json`) and
decline messages (`.err.<id>`) live inside those directories; zero-length
`.err.*` files are deleted by the build, so `ls swaps.probe.<rung>/.err.*` **is**
the decline list.

`dev/census_subenum.py` is new and is the only file here that is not a
diagnostic build artefact: it is the §2 census as one command, kept for the
same reason `37` ships `dev/validate_sampler_rng.py` — a census quoted in a
handoff and not reproducible in one line becomes folklore within two sessions.

Working tree only: **nothing was committed, nothing was installed, the game was
not launched.** `dev/patch_compute_skin.{py,sh}`, `swap_layer.c` and everything
`*ser*` were left to their owners; the modifications `git status` shows on those
paths predate this work.
