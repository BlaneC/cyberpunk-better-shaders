# 92 — Converged-mode profile: the expensive rungs, gated on RayNumber — one rung, never launched (2026-09-01)

The brief: *the expensive parked rungs (`-b3` bounce floor, skin spp, `-cone4w`)
lost on screen because at 1 spp they add noise. Photo mode / reference
accumulation pays the variance separately (`89` §5b). Build ONE rung on the
standing selection where those extra costs are gated on the accumulation
state.*

**Nothing here is on screen. There is no verdict until a one-variable A/B says
so.** One rung, built and verified offline, **not parked, not installed, not
selectable yet** — §6 has the two commands that fix that.

---

## 0. State up front, including the two things that are wrong with it

Rung: **`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-conv`**, on the standing
selection `…-cone2all`. 93 modules. Built by `dev/build_conv.sh`, all gates
green.

**There is no accumulation flag in these bytes and this rung does not have
one.** §1 is the census that establishes that, and it is the honest headline:
the gate is the fallback the brief named, `cbv[188].y > 1` — *RayNumber raised
above 1* — which is a proxy for "this frame is being paid for with samples",
not for "the accumulator is running".

**Two consequences, and neither is small:**

- **Reference accumulation with `RayNumber` left at 1 does not arm this rung.**
  `EnableReferenceAccumulation` converges variance across *frames*; `RayNumber`
  buys samples *within* a frame. This gate only sees the second one. If the
  user's photo-mode habit is "pin the camera and let it accumulate", the gate
  is FALSE the whole time and this rung is the standing rung. **`RayNumber`
  must be raised explicitly** — §6 makes it a required setting, not a
  suggestion.
- **The skin half is a FLOOR of 4, so it is inert at `RayNumber >= 4.`**
  `77`'s edit is `eff = UMax(rayN, 4)` and it is reused unchanged. At
  `RayNumber = 2` skin gets 2× the samples of everything else; at 3, 1.33×; at
  4 and above, **nothing**. The useful A/B window is `RayNumber` = 2 or 3, or
  rebuild with `CALLISTO_CONV_SPP=8`. Say this before the launch, not after
  a null.

`-cone4w` was in the brief and is **not** in this rung. It is a different base
(`88`'s cone taps/angle, an axis `88` §2c already measured as ~1.5× the noise
floor), and folding a third variable into a rung that has never been on screen
would make the first A/B unreadable. `88` §2c's own reading is that the horizon
tap is the entire effect; the laterals are the cheap part to add later if this
rung pays.

## 1. What the gate reads — and the census that says nothing better exists

`rgs_reference_main` carries no debug names, so a cbuffer word is identified by
what the shader does with it, not by a symbol. Swept across all 12 permutations
of the standing base (`dev/patch_conv.py` header carries the same census):

| cbv[188] | uses | what it is |
|---|---|---|
| `.x` | **0 in 12/12** | never read by any permutation |
| `.y` | 8× (6 live-loop), 4× (2 SER), 0× (4 baked) | **`RayNumber`** — the sample loop's bound and every `1/N` weight (`77` §1) |
| `.z` | 4× | **`BounceNumber`** — the path loop's bound (`29` §B3, `89` §2) |
| `.w` | 1× | a float, `NMax/NMin` to [-1,1] then fed to a `Log2` — an exposure/bias term, not a flag |

Every *other* uint-valued cbv word this shader compares against 0 was read and
none of them is accumulation: `193.x/.w` force a roughness to 1 (a debug
override), `194.z` is a light-count loop bound, `198.x` ORs into a russian-
roulette probability, `78.x/.w`, `81.w`, `84.y`, `90.x`, `97.x`, `101.x`
likewise unnamed and unrelated. `32` §2's `SampleNumber` / `SkipSamples` /
`EnableReferenceAccumulation` have **no identifiable landing site here**. So:

    accum := ( bitcast(cbv[188]).y > 1 )

Stated as the brief required: **a clean accumulation flag does not exist, and
this is the `cbv[188].y > 1` fallback.**

One thing that argument does have going for it: word 188 is a **live uniform
read in all 12 permutations**, including the 4 that baked `.y` and `.z` away —
they still read `.w` at runtime. So the word is not stale in the baked family;
only the *folding* of two of its components is. That is an argument, not a
proof (§7).

## 2. The two gated costs

**Bounce floor** (`89`'s `-b3`), 12/12 permutations:

    bound' = UMax( bound, OpSelect(accum, 3, 0) )

`UMax(x, 0)` is the identity on any uint, so a gate-false frame runs the
engine's own bound bit for bit — the baked literal 2 where it was baked, the
`cbv[188].z` extract where the CVar wire is live. Still a floor and never a
cap: `BounceNumber` set above 3 still wins, which is why §6 pins it.

**Skin sample floor** (`77`'s `-spp4`), 10/12 permutations. `77`'s edit is
reused **unchanged**; the only difference is what feeds its skin predicate:

    77:    gate = isSkin
    here:  gate = isSkin && accum

That is implemented by wrapping `patch_skin_spp.clone_class_fetch`, the single
function both of `77`'s tiers take `isSkin` from, so the dyn tier's
`eff = (gate && rayN != 0) ? UMax(rayN,4) : rayN` and the baked tier's
`N = OpSelect(gate,4,1)` / `invN = OpSelect(gate,¼,1.0)` are `77`'s code with a
narrower gate and nothing else moved.

**Reach, and the 2 that are not covered.** The skin half is **10/12**: 6 dyn +
4 baked. `40c6faab` and `ab7f1822` — the SER permutations — carry **no `& ~31`
class mask at all** (they feed the class to `OpReorderThreadWithHintNV`
instead, `88` §1), so `77`'s skin gate cannot be built there. `77`'s own rung
leaves those two pass-through (`ref=12(6 spp4-dyn + 4 spp4-baked + 2
pass-through)`) and so does this one: **they get the gated bounce floor and no
skin bump.** That means the skin half is still a per-launch coin flip across
permutations, exactly the defect `89` §4 built the bounce patch to avoid.
`88` §1's mode-independent anchor (the bindless material fetch,
`table[root_const[1]+5]` component 1 `>>5`) would close it and is not used
here — it would be a second variable in a rung that has never been shot.

## 3. What "identical when the gate is false" claims, precisely

Two different claims and they must not be blurred:

- **Behavioural identity, at run time.** A gate-false frame produces the
  standing rung's pixels. `UMax(bound,0) == bound`; `eff == rayN`; in the baked
  tier `N == 1` (one iteration) and `invN == 1.0`, so `acc = 0 + x` and
  `avg = acc × 1.0`, both exact in half. Inherited caveat from `77` §3: `-0.0`
  becomes `+0.0` through that add. Not byte-identical output in that one case.
- **Byte identity, at build time.** `dev/patch_conv.py --off` runs **every**
  detector — the cbv base, the path loop, the tier probe, both insertion points
  and their dominance asserts — and emits nothing. That rebuild is
  **12/12 byte-identical to the base rung**, asserted by `cmp` in the build.

The shipped rung is **not** byte-identical to the base: the gate's own
instructions are in the binary. Anyone who claims otherwise has not read this
paragraph.

## 4. Verification

`dev/verify_conv.py` re-derives everything from the **shipped bytes**, with no
help from the patcher, and takes a `--gate {accum,none}` axis so it can be
shown non-vacuous rather than asserted to be. `90` §2 is the lesson it is
written against: that verifier accepted any `X == 0` as the cavity gate, which
is exactly how the wrong counter passed 5 times.

The gate is checked **to the root**, not as "some comparison against some
uint": the predicate must be `OpUGreaterThan(ext, 1)`, `ext` must be
`OpCompositeExtract %uint <bc> 1` (component 1, and the check names `.z` in the
failure message so a slip to `BounceNumber` cannot pass), `<bc>` an
`OpBitcast %v4uint` of an `OpLoad %v4float` of an `OpAccessChain … %uint_188`.
The path loop itself is re-found by `89`'s 3-unit-phi throughput
discriminator, the `UMax` inner operand is asserted to keep the base's **kind**
(a literal its value, a runtime extract its component), and the skin `eff` is
asserted to **be** the bound of a non-path counted loop, so a rung cannot carry
a select that nothing reads.

**Non-vacuity, run inside every build, two of the four against rungs already on
disk — the ungated originals of the two halves spliced here:**

| check | result |
|---|---|
| this rung under `--gate none` | **FAIL** (expected) |
| `89`'s ungated `-b3` under `--gate accum` | **FAIL** (expected) — "this rung is UNGATED" |
| `89`'s ungated `-b3` under `--gate none` | **PASS** (expected) |
| `77`'s ungated `-spp4` under `--gate accum` | **FAIL** (expected) — bare `OpIEqual`, wanted `LogicalAnd(isSkin, accum)` |
| `77`'s ungated `-spp4` under `--gate none` | **PASS** (expected) |

The build fails if any of those five comes out the other way.

Build gates in `dev/build_conv.sh`, all build-failing: base provenance `cmp`
93/93 against the parked standing rung; the **negative control**
(`verify_conv.py BASE BASE --n 0 --spp 0`, with the shape matchers deliberately
loosened so a negative control that only recognises the one value it was told
to look for is not what is being run); the `--off` byte-identity control 12/12;
a bound census asserting `89`'s 8-runtime/4-baked split and `77`'s
6-dyn/4-baked/2-SER split from the reports; coverage 12/12 gated bounce floors
and 10/12 gated skin floors with the SER pair asserted untouched; every report
asserted to name cbv word **188** component **1**; 81/81 verbatim `cmp`; 12/12
raygens asserted to differ from the base; trace-site count asserted unchanged
per module (this patch adds iterations and a loop bound, never a trace);
93/93 `spirv-val`; then the verifier and the five non-vacuity checks.

| gate | result |
|---|---|
| base provenance | 93/93 |
| negative control on the base | PASS |
| `--off` rebuild vs base | **12/12 byte-identical** |
| bound census | 8/12 runtime, 4/12 baked |
| tier census | 6 dyn, 4 baked, 2 SER |
| coverage | 12/12 bounce, 10/12 skin |
| verbatim halves | 81/81 |
| `spirv-val` | 93/93 |
| `verify_conv --gate accum` | PASS |
| non-vacuity (5 checks) | 5/5 as named |

## 5. Cost

**Gate false (1 spp gameplay): free, and say what "free" means.** No extra
ray, no extra loop iteration, no extra sample — the only added work is the
gate itself: one uniform load + compare before the sample loop (skin), and one
inside the path-loop latch, i.e. **once per path iteration, not once per
invocation**. Both are loop-invariant reads of a cbuffer line the shader
already touches, so a driver that hoists them costs nothing and one that does
not costs 2-3 scalar loads from a hot line. Not measured; if a 1 spp frame-time
delta ever shows up, this is the only place it can come from.

**Gate true**, against the *same* `RayNumber` on the control half:

| | multiplier | source |
|---|---|---|
| path loop, every pixel | 3 iterations vs the shipped 2 ⇒ **~+50% path work** | `89` §5 |
| skin pixels, sample loop | `max(R,4)/R` ⇒ **2× at R=2**, 1.33× at R=3, **1× at R≥4** | `77` §0 / `29` §B7 |
| a face close-up, R=2 | roughly **3×** the base PT pass (2 × 1.5), warp-granular | product of the two |

`29` §B7's price for `-spp4` alone in a face close-up was ~+60–90% on the PT
pass; that was measured against 1 spp, so it is the R=2 column above, not an
independent number to add. **Time it.** This is a photo-mode rung by
construction and there is no argument for it in gameplay — that is the whole
premise (`89` §5b).

## 6. The A/B — settings contract FIRST (the `45` rule)

Nothing is inferred from the capture afterwards. State all of it before the
launch.

**Serve it.** The rung is built but **not parked and not in the CET selector**,
because this session was scoped to new files only:

    ./dev/build_conv.sh --install          # parks skin.set/<rung>/
    # then, in brdf_params.txt with the game CLOSED:
    skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-conv

`sync_settings.sh` serves any name that has a parked `skin.set/<name>/`, so no
`init.lua` change is needed to *run* it. **But `init.lua:365` sanitises an
unknown `skinspec` to `off` and rewrites `brdf_params.txt` on the next panel
change — so do not touch the Callisto CET tab's selectors during the session**,
or add the row first (one line, after the `88` cone block in `SKIN_LEVELS`,
then `make install`):

    { id = "gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-conv", label = "  + CONVERGED PROFILE (photo mode only: bounce floor 3 + skin spp 4, gated on RayNumber>1)" },

**Deploy check (the memory rule, and `45`):** the game runs copies. After
`--install`, `cmp` the served `swaps.skin/` against
`skin.set/<rung>/` and read `status.txt`'s `want_skinspec` — do not read a
launch until it names this rung.

**Required game settings, both halves identical except the one variable:**

- **PT Overdrive on. PT-in-photo-mode ON.** Both edits live in
  `rgs_reference_main` only; without photo-mode PT the rung is inert and the
  launch measures nothing.
- **`RayNumber` = 2 AND `RayNumberScreenshot` = 2** in the `pt_engine.lua`
  panel. **This is the gate.** At 1 the two halves are the same picture *by
  construction*. (Which of the two CVars lands in `cbv[188].y` in photo mode is
  not established — `32` §2.1 — so set both. Read the panel's
  `N/12 CVars found` header first; an unresolved knob says so.)
- **`BounceNumber` / `BounceNumberScreenshot` at their defaults (2)** for the
  whole A/B. The edit is a `UMax`, so a CVar set above 3 silently wins and the
  halves stop being one variable apart.
- Ray Reconstruction **OFF**, DLSS **Balanced**, RayTracedLighting **Psycho**,
  **2560×1440**, photo mode, **camera pinned**, same frame both halves.
- `tier=on skin=on ser=class shadowset=full-shadow ptreg=on ptclamp=on
  ptbounce=on ptmsggx=on refract=fres` — the standing set (`91`).
- **Frame content:** a face filling ≥¼ of frame, with **both** a hard shadow
  gradient across it (the skin-spp claim, `77` §6) **and** visible indirect
  bounce light — a bright floor or a lit wall onto a shadowed cheek (the
  bounce-floor claim, `89` §0). A flat-lit face, or a face lit only by direct
  sun and sky, is a wasted launch for one half or the other.

**The one-variable pair:**

| | rung | everything else |
|---|---|---|
| control | `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all` | `RayNumber = 2` |
| test | `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-conv` | `RayNumber = 2` |

**And one free control worth taking in the same session:** the *test* rung at
`RayNumber = 1` must be indistinguishable from the *control* rung at
`RayNumber = 1`. That is the gate's own falsifier — if it is not
indistinguishable, the gate is not off in gameplay and the rung must not ship
regardless of how the photo-mode half reads. It costs one extra capture.

**Pre-registered outcomes:**

| observation | reading |
|---|---|
| shadowed skin reads deeper/cleaner **and** bounce-lit cheek gains indirect light | the profile, working — then split it: `-b3` alone vs `-spp4` alone at R=2 to see which half pays |
| noisier than the control at R=2 | `89` §5b's premise is wrong at R=2 as well; the floor is higher than 2 spp. Retest at R=4 with `CALLISTO_CONV_SPP=8` before concluding |
| no difference at all at R=2 | check `RayNumber` actually resolved (panel header, `32` §2.1) **before** blaming the splice; then §7's baked-permutation question |
| difference at R=1 | **the gate is broken.** Stop. §3 |
| skin *brightness* shifts | normalization bug in `77`'s dyn tier — kill the rung, file the site (`77` §6) |
| patchy noise levels *within* one face | expected: the skin half is 10/12, the SER pair is pass-through (§2) |

## 7. Open

- **Does the accumulation state exist in a cbuffer at all?** §1 says not in
  `rgs_reference_main`'s reachable words. The compute resolve or the
  accumulation pass itself may carry it, and a census there (not a launch)
  would replace this proxy with a real flag. Highest-value item here.
- **The baked 4.** They folded `RayNumber = 1` into their code; the gate reads
  the *runtime* word. If the engine compiles a different permutation when
  `RayNumber` changes, they are simply never dispatched while accumulating and
  the gate is false there — harmless. If they ARE dispatched, `77`'s wired loop
  runs and the gate is exactly right. Both are safe; which one happens is
  unproven. The `rt_pipeline`/`pipe_stage` records of the A/B launch settle it
  for free.
- **`RayNumber` vs `RayNumberScreenshot`** — which one reaches `cbv[188].y` in
  photo mode. `32` §2.1's resolver prints what it resolved; nobody has read it.
- **The skin half's 2 missing permutations** (§2). `88` §1's mode-independent
  material anchor closes it, at the cost of a second variable.
- **`-cone4w`**, deliberately excluded (§0). Add it only after this rung reads.
- **The `-b2`-style control was skipped again.** `89` §0 owes one shot of
  `-b2`; this rung inherits that debt and does not repay it.
- `make install` **not** run; `--install` **not** run; no `init.lua` row. §6.

## 8. Files

| file | what |
|---|---|
| `dev/patch_conv.py` | the patcher; the cbv census is in its header; `--off` is the byte-identity control; `--n` / `--spp` split the two halves |
| `dev/verify_conv.py` | shipped-bytes verifier; `--gate accum\|none` is the non-vacuity axis |
| `dev/build_conv.sh` | 1 rung + every gate in §4; `CALLISTO_CONV_N` / `CALLISTO_CONV_SPP`; `--install` parks |
| `swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cone2all-conv/` | the rung, 93 modules |
| `init.lua` | **not touched.** §6 has the row to add |
