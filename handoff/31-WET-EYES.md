# 31 — Wetter eyes: the plan

Written 2026-08-29. Prompt: *add wetter eyes to this mod.*

**Verdict, one line: this is the cheapest visual feature left on the board.
The engine offers nothing (one boolean), but the material class the eye is
tagged with is already proven on screen, and the exact splice that produces
"wet" — the GGX roughness ceiling — is already written, already covers 77
modules, and is already parameterised by a gate id. v1 is a second gate
constant and one refactor.**

Nothing below has been on screen. Every claim is from the exe string table,
the disassembly, the patcher source, or `13`'s hunt screenshot. The ledger
rule (`19`, `28`) applies: until an A/B says otherwise this is an experiment
with a switch, defaulting off.

---

## 1. GOTCHAS 8 first: does the engine already do this?

Asked before writing anything, because `16` is the cautionary tale. Method is
`16` §1 / `27` §2: `strings` over the shipping exe (59,945,608 B, 2026-08-20),
then the neighbourhood of the CVar group in the string table (keys are
deduplicated, so the group must be read by layout).

**There is an `Editor/Characters/Eyes` CVar group. It has exactly one key:**

```
50379064 Editor/Characters/Eyes
50379088 UseAOOnEyes
```

and the full `cv*` shader-constant inventory (69 identifiers) contains **no
`cvEye*` of any kind** — the character constants are hair (41), skin (8), the
four rim families (13), RT (6). Word-boundary searches for `cornea`, `sclera`,
`iris`, `caruncle`, `tearline`, `tearfilm`, `eyeball`, `wetness` return **zero
hits** anywhere in the exe.

So the engine surface for eye *shading* is a single AO boolean. This is the
cloth situation (`22` §3), not the hair situation (`16`): the SPIR-V track is
not the hard way round, it is the only way round.

`UseAOOnEyes` is still worth having — it is live, free and changes how eyes
read (AO darkening on the eyeball). It is Phase 0 below.

## 2. The gate: eyes are material class 8, and it is already proven

`13` §1: the 29-module hunt net painted at the Panam framing and eyes came
back **violet, which is palette class 8** (`HUNT_PALETTE[8]`). The screenshot
is in the repo — `pics/panam_working_small.png` — and the eyes are
unambiguously violet against class-1 red skin and class-4 yellow hair. This is
on-screen evidence, not an inference from naming.

Two things about that gate that matter:

- **No shipping module tests class 8.** `20` §1 enumerated every `gbuf>>5 ==
  N` in the dump: `{0, 1, 3, 4, 5}`. That is irrelevant here — the patcher
  does not reuse the module's comparison, it emits its own against the class
  *value*, and `acquire_class_shift()` already recovers that value in all four
  G-buffer read idioms (including the 36 modules that only mask `& 31` and
  never shift). Class 8 costs one `OpIEqual`.
- **`ERenderMaterialType` has `RMT_Eye`** alongside Standard/Foliage/Hair/
  Cloth/Subsurface, so the asset system does tag eyes as their own material
  type. That corroborates the hunt; it does not by itself prove the G-buffer
  field is that enum (the observed numbering — skin 1, hair 4, foliage 5,
  eyes 8 — does not match the enum's declaration order, so the mapping is
  empirical, from the paint, and should stay that way).

**Re-confirm it anyway before building the ladder** (Phase 1). It is one
build and one launch, the evidence is a year-old screenshot from a different
module net, and every wrong-sibling failure in this repo started with a
reading nobody re-checked.

## 3. What "wet" is, and which lever reaches it

An eye reads wet because the tear film is a **smooth** dielectric: a tight,
bright, well-defined catchlight, plus a bright grazing rim at the limbus.
Vanilla shades it through the same single GGX lobe as everything else, with
the roughness the artist authored into the eye material.

| lever | reaches "wet"? | status |
|---|---|---|
| **GGX roughness ceiling** `alpha' = min(alpha, cap)` | **yes — this is the whole effect** | written: `build_skin_alpha_cap`, 77 modules |
| Schlick Fresnel reshape (`n_s`, `spec_gain`) | secondary — broadens the grazing rim | written: `build_skin_spec` |
| F0 raise | **no** | see below |
| Tier-1 c1 (diffuse Fresnel × retroreflection) | no — wrong term, and skin-specific | stays gated on class 1 |
| ~~Tier-4 transmission~~ | no | removed from the repo (`39`) |

`27` §9.2 established that the roughness cap is what actually produces gloss
and the Fresnel half only broadens the falloff. That finding transfers, and it
transfers *harder* here: skin is authored around roughness 0.40–0.60, so a cap
has to come a long way down to bite, whereas a cornea should sit near
0.05–0.10 and almost any authored eye roughness is above it.

**Do not raise F0.** A tear film is IOR ≈ 1.33 and a cornea ≈ 1.376, i.e.
F0 ≈ 0.020–0.025 — *below* the 0.04 dielectric default the shader already
uses. Wetness is smoothness, not reflectance. Raising F0 would be the
plausible-sounding edit that makes eyes look like chrome marbles, and it would
be attributed to "the wet eye feature works".

## 4. Where the code goes, and the one thing that will silently break it

Same surface as everything else that ships: the compute resolvers,
`dev/patch_compute_skin.py`, the `swaps.skin` overlay. Not a new overlay —
this splices the **same modules** as the gloss and the transmission, and the
layer serves the first file it finds for an id (GOTCHAS: first-file-wins), so
a second overlay would be dead with no error anywhere.

### 4.1 The collision, and why v1 must be one pass and not two

`build_skin_alpha_cap` ends with

```python
replace_all_uses(mod, alpha, sel, aline)
```

— it rewrites **every** use of the alpha id. Calling it a second time with an
eye gate on the same module does *not* produce two independent caps. By the
time the second call runs, the only surviving reference to `%alpha` is inside
the first call's own pending instruction, which is still sitting in `edits`
and not yet in `mod.lines`; the second `replace_all_uses` finds nothing to
rewrite and its select is dead. `spirv-val` passes, the build succeeds, the
module changes, and the eye half does nothing. That is the `08-DUAL-LOBE`
dead-sheen bug, which the docstring already names, plus GOTCHAS 12's
pending-id hazard in the same place.

So the pass is generalised, not duplicated:

```python
# build_class_alpha_cap(mod, cfg, dom_id, [(skin_gate, skin_cap),
#                                          (eye_gate,  eye_cap)])
inner = OpSelect(eye_gate,  NMin(alpha, eye_cap),  alpha)
outer = OpSelect(skin_gate, NMin(alpha, skin_cap), inner)
replace_all_uses(alpha -> outer)          # exactly one rewrite per alpha id
```

Nested selects, one rewrite, evaluated per pixel — the classes are mutually
exclusive so the order does not matter, but the *number of rewrites* does.

The same applies to `build_skin_spec`'s `replace_all_uses(mod, c['F'], …)` if
the Fresnel half is ever class-8'd (§6, v2).

### 4.2 The gate itself is one line

`process()` already emits the class gate as a single edit:

```python
skin_gate = OpIEqual %bool {shift} %uint_1
```

The eye gate is the same line with `mod.uconst(8)`, in the same edit tuple, so
it inherits the same dominance proof. Nothing else about the gate machinery
changes.

### 4.3 Identity must emit nothing

House rule, and the check that keeps every existing set byte-exact: with
`eye_alpha_max >= 1` (or without `--with-eyes`) the pass emits **no
instruction at all**, and the refactor of `build_skin_alpha_cap` into
`build_class_alpha_cap` must reproduce the parked ladder **77/77
byte-identical**. That single comparison is what proves the refactor did not
move the shipping gloss, and it is cheaper than any amount of reading.

## 5. The ladder, and the matrix cost problem

The knobs are `OpConstant`s baked at build time (`27` §9.1), so this is a
ladder of pre-built sets, not a slider. A slider would be `26` §5's inert-knob
trap for the third time.

Proposed rungs — `alpha_max` is `roughness²`:

| level | `eye_alpha_max` | roughness cap | what it is for |
|---|---|---|---|
| `off`     | —      | —    | the A/B control |
| `damp`    | 0.0225 | 0.15 | a hint; still a matte-ish eye |
| `wet`     | 0.0064 | 0.08 | the intended look — cornea-like |
| `glassy`  | 0.0016 | 0.04 | pushed |
| `extreme` | 0.0001 | 0.01 | **diagnostic**, expect shimmer, not a look |

### The cost, stated before it is paid

**Updated 2026-08-30:** the transmission axis is gone (`39`), so the matrix
this section was written against no longer exists. `skin.set/` is now **5
sets** — the gloss ladder alone — and crossing a 5-rung eye axis into it gives
25 sets, ~160 MB, ~31 min. Cheaper than the 130-set / ~830 MB / ~2.5 h figure
below, but the recommendation is unchanged and is now better supported: `39`
is the record of a matrix built out across three axes for a feature that had
never been confirmed on screen.

Recommendation, and it is GOTCHAS' own rule ("verify the mechanism before
building the matrix"):

1. **Phase 2 builds two sets, not a matrix** — the currently-served gloss/
   transmission combination with eyes `off` and with eyes `extreme`. ~13 MB,
   a few minutes, one A/B launch.
2. **Only after eyes visibly change**, build the axis, and cross it with the
   gloss axis (`<gloss>+e<eye>`, 5×4 = 20 new sets, ~130 MB).
3. **Fallback rule: drop the least-confirmed axis first.** An unbuilt
   combination must drop `skineye` and never `skinspec`, because falling back
   in a way that also moves the gloss makes the next A/B credit one feature
   with another's change. The composed-name machinery that enforced this for
   the transmission axis was removed with it (`39`), so a `skineye` axis has
   to re-add its own — one axis, one component, not three.

## 6. The phases

**Phase 0 — `UseAOOnEyes` in the CET panel. DONE 2026-08-29.** Added to
`skin_engine.lua` as the 18th knob, same pattern as the other feature gates:
snapshot vanilla at init, `pcall`'d, live, re-asserted on the 2 s tick. The
panel header now reads "Skin & eyes … N/18 CVars found", so a renamed or
wrongly-attributed key shows as a count rather than as a dead switch. Verified
by 5 stubbed checks inside the 35-check run in `32` §2.3 (registers, snapshots
the engine value, no write while the master is off, writes and re-asserts when
on, restores on disable) plus one for the loud-gap path (Eyes group absent →
17/18 in the header, knob still registers).

**Not yet observed.** Exit criterion is unchanged: the knob moves the picture,
or it is recorded as dead in PT — either result is worth having before the
splice exists to be blamed. Note the AO it gates may be a raster-path AO that
RT Overdrive does not consume, in which case "dead in PT" is the expected
answer and not a defect.

**Phase 1 — re-confirm class 8.** `--tier hunt --hunt-classes 8` (the Python
flag exists; the shell wrapper does not forward it yet — one line). One
launch, one close-up. Exit: eye pixels paint, and **nothing else does**. If a
second surface paints violet, the gate is broader than "eyes" and the rungs
have to be judged on that surface too.

**Phase 2 — the two-set mechanism check.** `build_class_alpha_cap`, the eye
gate, `--with-eyes`, and a build of exactly two sets (eye `off` / eye
`extreme`) on top of whatever gloss+trans is being served today. One relaunch
between them, one variable, fingerprinted from `~/callisto_launches.log`.
Exit: at `extreme` the eyes are unmistakably, wrongly glassy. If they are not,
**stop** — the question is then a gate or dispatch question, not a tuning one,
and nothing downstream is interpretable.

**Phase 3 — the ladder and the switch.** `ELEVELS` in
`dev/patch_compute_skin.sh`, `EYE_LEVELS` in `init.lua`, `skineye` in
`sync_settings.sh`, the composed set name and the fallback order from §5.
Per-axis difference assertions like the other two ladders (each rung differs
from `off` and from the rung below, or the build aborts). Default **off** —
this has never been on screen.

**Phase 4 (optional) — the Fresnel half.** A class-8 `n_s` for the limbal wet
rim, nested into `build_skin_spec` the same way §4.1 nests the cap. Only worth
building if Phase 3's cap alone leaves the rim reading dry, and only after the
cap is confirmed — two visual features between two observations is the
confound that cost `26` a session.

## 7. Out of reach, stated so nobody re-derives it

- **The tear meniscus / wet line where the lid meets the eyeball.** That is
  geometry and an authored material on the *eyelid*, which is skin. There is
  no eyelid class to gate on, and class-1 skin covers the whole face — capping
  roughness there is the gloss feature, not this one.
- **Corneal refraction / a parallax-shifted iris.** `20` proved there is no
  refraction anywhere in this renderer: no `Refract`, no IOR constant, no
  transmission lobe, no CVar. Not reachable at any effort.
- **A per-pixel wetness or thickness channel.** The G-buffer carries none and
  there is no free channel (`11` §2). This is the same wall the Tier-4
  transmission spent three proxies failing to get around (`39` §3.2) — read
  that before proposing a fourth.
- **Eye AO, beyond the boolean.** Phase 0 is the whole surface.

## 8. How each way this can silently fail is made loud

Every one of these looks identical from the chair ("the wet eye thing doesn't
work"), which is why each gets its own signal:

| failure | signal |
|---|---|
| second `replace_all_uses` clobbers the first (§4.1) | build asserts the eye rung differs from the gloss-only set of the same strength, per module |
| refactor moved the shipping gloss | 77/77 byte-identical against the parked ladder with eyes off |
| class 8 is not eyes, or not only eyes | Phase 1's single-class hunt, before any tuning |
| set never built / launch bypassed `sync_settings.sh` | the existing three warnings, extended to `skineye`; running level in the **selector label**, not a tooltip (GOTCHAS) |
| `init.lua` and `sync_settings.sh` disagree on the default | one grep for `skineye` across both files, in the same edit — this is the `skinspec` "one knob, two defaults" bug, and it produces a UI that lies about what is running |
| a result credited to the wrong rung | `skin_sha` in `~/callisto_launches.log` is the only trustworthy attribution; byte sizes cannot tell two `OpConstant` values apart |

**One predicted artifact, so it is not read as a bug in the splice:** the eye
is a small, strongly curved surface, and a near-mirror lobe on it produces a
catchlight one or two pixels across. That is exactly the input the temporal
resolve (`6ac9`, `13` §3) smears, and it is a firefly candidate. Expect
shimmer at `extreme` and possibly at `glassy`; that is the reason `wet` sits
at roughness 0.08 rather than 0.02, and the reason not to chase the cap
downward if the highlight looks unstable.

## 9. Files this touches

| file | change |
|---|---|
| `dev/patch_compute_skin.py` | eye gate in `process()`; `build_skin_alpha_cap` → `build_class_alpha_cap` (list of (gate, cap), one nested rewrite); `--with-eyes`; `eye_alpha_max` knob forced to identity without the flag |
| `dev/patch_skin_brdf.py` | the `eye_*` knob defaults in `KNOBS`/`VANILLA` |
| `dev/patch_compute_skin.sh` | `--eyes`, `ELEVELS`, the two-set mechanism build, then the crossed axis and its per-axis assertions; forward `--hunt-classes` |
| `release/game/red4ext/plugins/CallistoSSS/sync_settings.sh` | `skineye` key, composed set name, fallback order (§5.3), cache-stamp entry, `status.txt` keys |
| `init.lua` (× 3 copies) | `EYE_LEVELS`, the selector, the running-level label, the silent-no-op warnings |
| `skin_engine.lua` (× 3 copies) | Phase 0: `UseAOOnEyes` |
| `handoff/19-STATUS.md` | a ledger row, state "built, never run", when Phase 3 lands |
