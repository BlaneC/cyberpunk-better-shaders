# 90 — The cavity cone on the `-b3` base, and the gate fix — 4 rungs, never launched (2026-09-01)

The ask: *"I want the cavity term added to b3 basically."* That is rung 1 and 2
below. On the way there, `89` §2 turned up a defect in the cone's gate that had
been live through every cavity A/B so far, so the same rebuild fixes it and
ships the control that measures the fix. **Nothing here is on screen.**

## 0. State, and the settings contract

⚠ **THE `-b3` BASE WAS REVERTED AFTER THIS DOC'S FIRST DRAFT.** `89` §0: three
bounces at 1 spp reads as SUPER NOISY, so the bounce floor is out and the live
selection is back to `gi-50b-bleed-oil-sheen-deep-clothhi`. The GATE FIX is
orthogonal to that and still wanted, so it was rebuilt on the plain standing
rung as well. **Shoot the `gf` rungs (§0b). The four `-b3-*` rungs stay parked
but are NOT the ladder any more** — they only become interesting again in the
one configuration `89` §5b names (raised `RayNumber` or reference accumulation,
photo mode, pinned camera).

### 0b. The rungs that matter — on the PLAIN standing base

| rung | scope | gate | k_local |
|---|---|---|---|
| `…-clothhi-cone2gf` | sun | **fixed** | — |
| `…-clothhi-cone2allgf` | all | **fixed** | 0.85 |
| `…-clothhi-cone2all35gf` | all | **fixed** | 0.35 |

**The gate A/B is free here.** `88`'s already-parked `-cone2` and `-cone2all`
are the OLD-gate builds of these exact rungs, so `-cone2allgf` vs `-cone2all`
is one variable — the gate — with both halves already on disk. No `-sg` control
rung was needed on this base.

Built by `dev/build_cavity4.sh`, same gates as §3, all green, parked.

### 0c. The `-b3` rungs (parked, not the ladder)

Built, verified, four rungs, parked, selector rows added. Zero launches.

| rung | scope | gate | k_local | what it isolates |
|---|---|---|---|---|
| `…-b3-cone2` | sun | **fixed** | — | the ask: `-b3` + the sun cavity cone |
| `…-b3-cone2all` | all | **fixed** | 0.85 | + SCOPE, the 2 local-light NEE sites |
| `…-b3-cone2allsg` | all | **old** | 0.85 | **control only.** The pre-`89` sample gate. Do not ship. |
| `…-b3-cone2all35` | all | **fixed** | 0.35 | the fallback if the gate fix alone does not settle area lights |

Settings, stated **before** the launch (`45`): PT Overdrive on, PT-in-photo-mode
ON, Ray Reconstruction OFF, DLSS Balanced, RT Lighting Psycho, 2560×1440, photo
mode, camera pinned. **`BounceNumber` / `BounceNumberScreenshot` at their
defaults (2)** — the base carries `89`'s floor and it is a `UMax`, so a raised
CVar silently overrides it.

## 1. The gate defect, and why it matters more than it sounds

`88`'s cone gates on `class 1 AND <counter> == 0 AND lit`. The `<counter>` came
from `E.find_bounce_counter`, whose documented tie-break is *"Outermost
(earliest header) wins"*. `89` §2 established that the outermost counted loop in
`rgs_reference_main` is the **sample** loop, not the path loop.

Swept per permutation on the standing base — it is **not** uniform:

    gate tested the PATH counter (correct)   7/12   21a92f1a, 3d871a31,
                                                    4103c886, 4270b745,
                                                    996a3b16, d002cc05,
                                                    d622fb9e
    gate tested the SAMPLE counter (wrong)   5/12   1271d381, 25b54fc4,
                                                    40c6faab, 852b31a8,
                                                    ab7f1822

With `RayNumber = 1` (the default) `sample == 0` is always true, so in those 5
the cavity darkening ran at **every bounce** instead of only the primary hit;
in the other 7 it behaved as documented. Which one you got was decided by which
permutation the launch dispatched — a coin flip per run (`88` §1), **inside a
term that was being A/B'd**. Any cavity reading that failed to reproduce is
explained by this, and `88` §5c's area-light over-darkening is the leading
casualty: in the bad 5 a one-hit darkening compounded over every bounce, and on
the `-b3` base that is now three of them.

**The fix.** `find_path_counter` in `dev/patch_cavity2.py` locates the path loop
structurally — among counted loops `LessThan(x + 1, bound)` on a back edge whose
body traces rays, the path loop is the one whose header seeds exactly **3 fp
phis with 1.0**, the RGB throughput (the sample loop seeds its accumulators with
0 and is asserted to seed none). Its counter is the unique `OpPhi %uint` at that
header whose incomings are exactly `{0, that loop's own IAdd}`. Unique in 12/12.
`E.find_bounce_counter` is still called every build, purely so the report can
record `legacy_helper_was_wrong` per module.

`--gate sample` reproduces the old behaviour and exists only to build
`-b3-cone2allsg`.

## 2. The verifier was vacuous on this axis, and now is not

`verify_cavity2.py` used to assert only that *some* `X == 0` appeared in the
gate. That is exactly how the sample counter passed 5 times. It now re-derives
the path counter from the **shipped bytes** by the same throughput
discriminator and requires the tested operand to **be** it.

Shown non-vacuous, not asserted to be:

    old -cone2 rung, --gate bounce  -> FAILS, naming exactly the 5 bad modules
    old -cone2 rung, --gate sample  -> PASSES

## 3. What did not change

Same cone: k=0.85, tmax 6 mm, 2 taps (L + horizon), θ=12°, cosine-weighted
average, weight floor 0.05, distance ramp, tmin 0.1 mm, flags 16, mask 39.
Same 12/12 reach, same identity-when-dead (`OpSelect(gate, occ, +0.0)` ⇒ factor
exactly 1.0). Reach is still `rgs_reference_main` only; 77 compute + 4 ReSTIR-GI
are byte-identical to the base and `cmp`-asserted.

Gates, all build-failing (`dev/build_cavity3.sh`): base provenance 93/93 against
the parked `-b3`; negative control; **k=0 identity control run with
`--all-lights`, 12/12 byte-identical**; 36/36 sun sites × 4 rungs and 24/24
local sites on the three all-lights rungs; `85`'s two pass-through modules
asserted patched; 81/81 verbatim; 93/93 `spirv-val` × 4; `verify_cavity2.py`
per rung with the matching `--gate`. Green on all four.

## 4. The ladder — read §0 first, this is the `-b3` version and is PARKED

The live ladder is `-cone2gf` / `-cone2allgf` / `-cone2all35gf` on the plain
base; substitute those names below and drop step 1's `-b3` reference. Step 3
becomes `-cone2allgf` vs `88`'s existing `-cone2all`.

1. **`-b3-cone2` vs `-b3`.** Does the sun cavity still read as a win now that
   the gate is honest and the base bounces three times? This is the ask.
2. **`-b3-cone2all` vs `-b3-cone2`.** SCOPE. Shoot it in an interior or under
   neon, never in daylight, and **time it** — one local site is inside the light
   loop, so its cost scales with visible light count.
3. **`-b3-cone2all` vs `-b3-cone2allsg`.** The gate, alone. One frame holding a
   big area light. If `-sg` is the dim one, `88` §5c's over-darkening was
   substantially this bug and the solid-angle work may not be needed.
4. **`-b3-cone2all35`** only if step 3 leaves area lights still too dim.

## 5. Files

| file | what |
|---|---|
| `dev/patch_cavity2.py` | `find_path_counter`, `--gate {bounce,sample}`; report gains `path_counter`, `sample_counter`, `legacy_helper_was_wrong` |
| `dev/verify_cavity2.py` | `path_counter` re-derivation, `--gate`; the gate check is no longer vacuous |
| `dev/build_cavity3.sh` | 4 rungs on the `-b3` base; `--install` parks |
| `init.lua` | 4 selector rows after the `89` block |

## 6. Open

- Everything in `88` §11 (the authored-AO census) and `88` §3 (the oil lobe) is
  untouched and still the better bet if the cone keeps disappointing.
- **`79`'s ear glow uses the same broken helper** and was not rebuilt here.
  Same 5/12 exposure, same fix available.
- `88`'s nine `-clothhi` cone rungs are now superseded but still parked and
  still listed in the selector. They carry the old gate; leave them for
  reference or clear them, but do not A/B against them.
- `make install` still not run.
