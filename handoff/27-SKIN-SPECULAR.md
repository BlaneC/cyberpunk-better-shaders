# 27 — Skin specular sheen: feasibility, and the engine-CVar panel (Phase 1)

Written 2026-08-28. Prompt: *a more obvious specular sheen on skin, especially
faces — can our custom BRDF do that, where should the code live, does CET
already expose it, does our BRDF override any skin settings?*

**Verdict, one line: the ask splits cleanly into an engine half that already
exists (8 skin CVars, now exposed as a live panel) and a mod half that was
scoped in the original plan and never built (Callisto Tier 3, the specular
Fresnel sheen term — `../analysis/BRDF_HANDOFF.md` §3). The engine half
shipped as `skin_engine.lua` and was then A/B'd to a dead end (§4); the mod
half — Phase 2 — is now BUILT AND WIRED, and has never been on screen.**

Phase 1 is deployed and closed: the CVars cannot gloss skin, by construction
(§4). Phase 2 is the splice that can, and §7 is its record. The resume point
is now a single launch: build the sets, turn the switch on, look at a face.

---

## 1. Answers to the questions that were asked

- **Can our custom BRDF do it?** Not the part that ships. The shipped skin
  BRDF is Tier-1 `c1` only (diffuse Fresnel × retroreflection, 153 sites at
  the Disney-diffuse scalars in the compute resolvers). Sheen is Tier 3:
  `F = f0 + t(2−r(n_s))·(1−f0)·(1−VoH)^{5·r(n_s)}` plus a skin roughness
  clamp `α′ = min(α, 0.45²)`. Never attempted (no `n_s`/spec knob exists in
  any patcher). All inputs are live at the GGX sites.
- **Where would the code live?** In the compute resolvers
  (`dev/patch_compute_hair.py`, riding the `swaps.hair` overlay) — the same
  surface the shipped `c1` proves on screen. NOT in the raygen
  (`patch_skin_brdf.py`): raygen BRDF edits are eval-invisible (`07` §2, the
  `skinray` toggle's own description says so). A new pass must fold into the
  same build — never a second overlay on the same modules (GOTCHAS:
  first-file-wins).
- **Does CET already expose it?** Yes, engine-side — see §2. Eight skin CVars
  exist in the exe, none of them previously exposed by anything (Ultra Plus
  does not touch them; verified against `16` §2's audit of its presets).
- **Does our BRDF override any CET skin settings?** No. `c1` multiplies the
  diffuse term only and writes no engine CVars (only `hair_engine.lua` writes
  CVars, hair only). Engine skin CVars scale the specular lobe; our term
  modulates diffuse — they compose multiplicatively. The one overlap is
  look-level: `cvSkinFresnel`/`cvCharacterFresnel`/RimEnhancement target the
  same grazing response as our `rho_f` by different math (`16` §7: "A/B
  before maintaining").

## 2. Phase 0 — the engine surface, verified (offline)

`strings -n 6` over the shipping exe (59,945,608 B, 2026-08-20), the `16` §1
method. Both the CVar paths and the `cv*` shader constants they bind
(`16` §7) are present:

| path | keys | binds |
|---|---|---|
| `Editor/Characters/Skin` | `SubsurfaceSpecularTint_{R,G,B}`, `SubsurfaceSpecularTintWeight`, `AllowSkinAmbientMix`, `SkinAmbient{Intensity,Mix}_Factor` | `cvSkin_SpecularTint_*`, `cvSkin_AllowAmbientMix`, `cvSkin_Ambient*` |
| `Editor/Characters/RimEnhancement/Skin` | `FresnelCoefficient`, `SpecularCoefficient`, `ConstOffsetCoefficient` — **unprefixed**; every other category carries `Foliage_/Weapon_/Standard_` prefixes | `cvSkinFresnel`, `cvSkinSpecular`, `cvSkinConstOffset` |
| `Editor/Characters/RimEnhancement` | `GlobalCharacterFresnel` | `cvCharacterFresnel` |
| `Editor/Characters/RimEnhancement_RayTracing/Skin` | `RoughnessFactor_Bias`, `RoughnessFactor_Scale`, `LightBlockerInfluence` | `cvRoughnessFactor_{Bias,Scale}`, `cvLightBlockerInfluence` |
| `Developer/FeatureToggles` | `CharacterRimEnhancement`, `CharacterSubsurface{Translucency,Scattering}` | feature gates |

The rim family is the engine's grazing-angle additive specular — a
"poor-man's sheen" (`22` §3): driven by `N·V` with no azimuthal light
response, so it reads as an edge glow that ignores where the light is,
rather than a directional highlight. The `Editor/Characters/Skin` group is
the specular *tint* half. Neither is a Callisto-shaped Fresnel curve — that
is Phase 2's ceiling.

**One attribution caveat, stated.** The three RT keys sit next to the
`…/RimEnhancement_RayTracing/Skin` path in the string table, but the key
strings are deduplicated, so whether they belong to RT/Skin alone or are
shared across the four RT categories is inferred from layout (`22` §3 made
the opposite guess, attributing them to RT/Standard). The panel registers
them under RT/Skin and every `GameOptions` call is `pcall`'d, so a wrong
attribution degrades to one dead slider — and the subcategory header counts
how many CVars were actually found, so the gap is loud rather than silent.

## 3. Phase 1 — what was built

`skin_engine.lua` (+ wired into `init.lua`, both mirrored to `release/` and
the live install). The `hair_engine.lua` pattern exactly:

- 17 knobs (7 rim/sheen, 4 specular tint, 3 ambient, 3 feature gates),
  **master switch default OFF** — installing this changes nothing until
  asked.
- **Vanilla is snapshotted at init**, never hard-coded: enabling the panel
  with untouched sliders writes back what the game shipped (verified).
- **Applies live** — no relaunch, no cache clear, unlike every other
  Callisto knob.
- **Re-asserts every 2 s** (`onUpdate`), because the engine resets CVars
  across loads/fast travel and other mods reapply presets on the same
  events. While on, it overrides any other mod writing these CVars.
- Header carries `N/17 CVars found`; absent CVars are named on the CET
  console.
- Persistence in `skin_engine.txt` (CET-sandboxed, next to
  `hair_engine.txt`).

Verified against a stubbed `nativeSettings`/`GameOptions` (14 checks, all
passing): snapshot correctness, no-op enable, live write while enabled, no
write while disabled, disable restores the snapshot, save/load round-trip,
re-register re-applies a saved-on state, the 2 s re-assert repairs engine
drift, and the loud-gap count with one deliberately absent CVar.

`luac -p` clean on both Lua files; all three copies (repo, `release/`, live
install) byte-identical.

## 4. Resume point — the A/B this panel exists to answer

One session, no relaunches needed:

1. Fixed face framing in RT Overdrive (a close-up in daylight; the rim pass
   is direct-light-driven — `11` §1, `16` §7).
2. Master switch on. One knob at a time, **exaggerate first** (e.g.
   Rim:SpecularCoefficient to 4, tint weight to 1): the question is *which*
   knobs act in PT mode at all. The hair CVars are consumed by the same
   compute evaluators we patch (`16` §6), so the prior is that these do too,
   but it is a prior, not a finding.
3. Whatever acts, dial to taste; "Restore engine defaults" is the control.
4. Record which knobs were dead in PT — that list is the input to Phase 2.

### Result (2026-08-28, user session): no gloss — by construction

The user pushed the whole surface to extremes (rim Fresnel/Specular 4/4,
ConstOffset 1, GlobalCharacterFresnel 4, RT rim roughness bias −0.5 / scale
0, tint 0.35 grey at weight 1, ambient mix on at 2). Verdict, reported from
screen: **none of it produces an oily/glossy top layer on faces.**

That is the expected outcome of the math, not a failure to apply:

- The rim family is an additive `N·V`-driven edge glow (`22` §3) — it
  brightens silhouettes; it cannot gloss a front-facing surface.
- The tint CVars recolor the specular; at 0.35 grey they *dim* it.
- The visible face specular is the resolvers' single GGX lobe
  (`F0 = 0.04`, roughness from the character's roughness maps), and **no
  skin CVar scales F0 or reshapes that lobe** — the 8 `cvSkin*` constants
  are the entire skin surface, re-verified against the exe string table.

**Conclusion: the CVar track is closed for the glossy ask. Phase 2 (the
Callisto Tier-3 splice) is a go** — it is the only in-scope route to
skin-gated gloss (the alternatives: global roughness side effects, or
per-character roughness-map edits in WolvenKit — `22` §6's asset-route
argument, different toolchain, per-character labour).

Housekeeping noted: `skin_engine.txt` persists `enabled=1` with the extreme
values and re-asserts every 2 s. Restore defaults + master off before any
future A/B, or this panel will contaminate the observation.

## 5. Gotchas that applied and were followed

- **GOTCHAS 8** (engine-first): the whole point of Phase 1; asked and
  answered before any patcher was written.
- **Loud gaps over silent ones**: found-count in the header, missing CVars
  on the console, the RT attribution caveat in the header comment and the
  knob tooltip.
- **Snapshot, don't hard-code**: vanilla values come from the live engine at
  init (`16` §4's design note for the hair panel).
- **One writer per file** (`09` I1): `skin_engine.txt` is this panel's file;
  nothing else reads or writes it. `brdf_params.txt` untouched — this panel
  is not launch-gated and does not belong in that schema.

## 6. Files

| file | change |
|---|---|
| `skin_engine.lua` (new, × 3 copies) | the panel |
| `init.lua` (× 3 copies) | defensive require, register after the hair panel, `onUpdate` hook |
| `/tmp/opencode/skin_panel_test.lua` (scratch) | 14-check stubbed verification |


---

## 7 — Phase 2: the Tier-3 splice, built and wired

Written 2026-08-28, after §4 closed the CVar track. **Built, validated
offline, wired to a switch, and NEVER LAUNCHED** — the ledger row that
`19-STATUS.md` reserves for exactly this state. Nothing below is evidence
about pixels.

### 7.1 The math

At every specular Schlick Fresnel in the compute resolvers, gated on the skin
class:

```
r  = 2(1 - n_s)
F' = min( f0 + g·saturate(2-r)·(1-f0)·(1-VoH)^(5r),  1 )
alpha' = min(alpha, alpha_max)          # rides the hair pass's alpha reshape
```

Identity at `n_s=0.5, g=1, alpha_max>=1`. Defaults `n_s=0.65` (exponent
5 → 3.5, so the highlight builds earlier off-normal) and `alpha_max=0.2025`
(roughness 0.45 squared).

Two things worth knowing before tuning:

- **`alpha_max` is doing nearly all the work.** `saturate(2-r)` clamps to 1
  for every `n_s > 0.5`, i.e. across the whole wet direction, so with
  `spec_gain` at its 1.0 default the Fresnel half contributes only the
  exponent broadening. Tune the roughness ceiling first.
- **The `min(…, 1)` is not decoration.** Fresnel reflectance is physically
  ≤ 1 and `g > 1` breaks that: `spec_gain=2` returns 1.96 at grazing, a
  ~2× energy gain that reads as white fireflies on cheeks and nose rather
  than as gloss. Since the house A/B method is "exaggerate first", the
  unclamped form would have been found by pushing the knob and misread as
  the splice not working.

### 7.2 Where it lands, and why not elsewhere

The compute resolvers, riding the `swaps.hair` overlay — the surface the
shipped `c1` already proves on screen. Not the raygen: those edits are
eval-invisible (`07` §2).

`find_spec_fresnel_groups` matches both shipped idioms — the multiply chain
`x4·x` and the spherical-gaussian `Exp2` fit — and **rejects any group whose
`f0` is the constant 1.0**. That is the Disney diffuse `FD`, which computes
the same pow5 shape; without the guard the sheen would have been spliced onto
the diffuse term as well. It is the load-bearing line in the pass.

GI resolvers are skipped in v1 (direct-light evaluators carry face gloss), so
**a face lit only by bounce light gets none** — interiors and shade are where
to expect this to look absent rather than broken.

### 7.3 Offline verification

Across all 84 anchored compute libs (73–74 patch; the other 10 fail on the
pre-existing hair anchors, identically with and without the flag):

| check | result |
|---|---|
| `spirv-val` | clean on every patched module, both sets |
| coverage | 284 Fresnel groups / 852 channels, zero `skipped_dom`, zero `skipped_shape` |
| build without `--with-skinspec` | **byte-identical** to the pre-Tier-3 patcher |
| `--sets` pair, module lists | identical (asserted by the build, or it aborts) |
| `--sets` pair, bytes | 72 modules differ, 2 identical — exactly the two GI resolvers |

The identity build emits *nothing* rather than identity math, because this
pow is Log2/Exp2 and would not be bit-equal to the shader's own multiply
chain. That is what keeps `--vanilla` and every non-Tier-3 build byte-exact.

### 7.4 The switch, and why it is a parked pair

The gloss is spliced into the **same modules** as the hair BRDF, so it cannot
be a second overlay — the layer serves the first file it finds for an id
(GOTCHAS: first-file-wins). Building only the gloss variant would weld two
independent visual features to one switch, which is the confound GOTCHAS
warns about and which cost `26` a session.

So `dev/patch_compute_hair.sh --hair N --sets` builds the hair overlay
**twice from the same source in the same run** — once plain, once with the
splice — and parks both in `hair.set/{off,on}/`. `sync_settings.sh` reads
`skinspec` and materializes one into `swaps.hair/`, exactly as `shadowset`
picks a shadowcull build. Both sets carry an identical hair BRDF, so the
switch moves the skin math and nothing else.

The build asserts the pair is worth A/B-ing: equal module coverage, and at
least one module actually differing. It aborts rather than parking a pair
that would silently compare nothing.

### 7.5 The failure modes it admits to

`skinspec` has three ways to be a silent no-op, all of which look identical
from the chair ("the oily skin thing doesn't work"). Each is now loud:

| state | where it surfaces |
|---|---|
| no `hair.set/` parked | terminal, `want_skinspec=fixed` in `status.txt`, `[INERT: …]` in the switch label, and a warning line |
| `hair=off` | warning line — the shared overlay is disabled, so the gloss is too |
| launch bypassed `sync_settings.sh` | warning line comparing the served set against the switch (the `25` §9 trap) |

`hair_sha` now joins the launch journal, so a launch can be attributed to a
set by content hash rather than by file size — `26` §7 is the reason that
matters.

### 7.6 Resume point — the launch this exists for

`hair=off` in the live params today, and **the gloss needs it on**.

1. `./dev/patch_compute_hair.sh --hair <N> --sets` (rebuilds the hair overlay
   from current defaults — see the caveat below).
2. CET: Callisto hair BRDF **on**, "Oily / wet skin highlight" **off**.
   Launch. Fixed close-up face framing in daylight, RT Overdrive.
3. Same framing, switch **on**, relaunch. One variable.
4. Confirm the switch label reads `[this launch is serving: on]` before
   believing anything — that is the whole point of §7.5.
5. If it is too subtle, `--set alpha_max=0.12` before touching `spec_gain`
   (§7.1), and re-park.

**Caveat on step 1:** the live `swaps.hair/` (2026-08-27, 70 modules) is not
a current-default build — a fresh one patches 74 and differs on 11 of the 59
shared modules. Rebuilding therefore changes the hair look as well as adding
the switch. Either accept that and re-baseline hair in the same session, or
reproduce the old knobs with `--set` so the pair isolates the skin change
only.

### 7.7 Files

| file | change |
|---|---|
| `dev/patch_compute_hair.py` | `find_spec_fresnel_groups`, `build_skin_spec`, `skin_spec_active`; `alpha_max` composed into the hair alpha reshape; `--with-skinspec` |
| `dev/patch_compute_hair.sh` | `--with-skinspec`, `--sets` (builds + parks the pair, asserts coverage and delta) |
| `release/.../sync_settings.sh` | `skinspec` key, set selection into `swaps.hair/`, cache-stamp entry, `hair_sha` in the journal, two `status.txt` keys |
| `init.lua` (× 3 copies) | the `skinspec` switch in the skin section, `skinspecNote()`, three warning lines |
| `.gitignore` | the generated `swaps.hair.{off,on}/` pair |


---

## 8 — The hair BRDF removal, and what skin gained by it

2026-08-28, at the user's call: *"We're not really doing anything with the
hair BRDF. Can we just remove that feature?"*

The hair BRDF net is gone. `dev/patch_compute_hair.py` and its driver are
deleted; `dev/patch_compute_skin.py` (836 lines, down from 1506) carries the
skin work forward. **Kept, deliberately:** the hair shadow-leak fix, which is
confirmed on screen and is a different patcher and overlay entirely, and
`hair_engine.lua`, the engine CVar panel.

### 8.1 Why it was entangled at all

The compute surface was found *because* of hair, so the skin tiers grew
inside the hair patcher. Two consequences, both now fixed:

- The shipped tier-1 c1 rode `swaps.hair/`, so **`hair=off` silently
  disabled a confirmed feature** along with the unconfirmed one. That was the
  live state of this install when the removal started.
- The Tier-3 gloss could only be switched on together with the hair net, so
  every face you judged the gloss on also had unconfirmed hair shading in it.

Skin now owns `swaps.skin/` and its own `skin` switch.

### 8.2 What was carried over, and what was rewritten

Carried verbatim (they were verified where they stood): the class-gate
machinery (`find_class_anchor_variant` / `acquire_class_shift`, all four
G-buffer read idioms), `find_c1_sites`, `build_skin_c1`,
`find_spec_fresnel_groups`, `build_skin_spec`, and the hunt/tint diagnostics
— those identify *any* material class, so they are not hair-specific and
stayed.

Rewritten: **the roughness ceiling**. `alpha_max` used to compose into the
hair pass's alpha reshape; it is now `build_skin_alpha_cap`, standalone. It
still rewrites *every* use of each alpha, not just the eval's, so evaluation
and importance sampling agree and MIS stays unbiased.

Dropped: `build_hair_spec_lobes` (aniso + shifted dual R/TRT lobes + sheen),
`build_hair_wrap`, `build_hair_gi`, the structure-tensor tangent estimator
and its confidence remap.

### 8.3 Coverage went UP

| | hair patcher | skin patcher |
|---|---|---|
| modules patched | 74 | **77** |
| modules failing | 10 | **7** |
| tier-1 c1 sites | 153 | **156** |
| Tier-3 Fresnel groups / channels | 284 / 852 | **354 / 870** |
| modules getting the gloss | 72 (GI resolvers excluded) | **77 (all)** |
| `spirv-val` | clean | clean |

Three modules that the hair patcher rejected with *"normal G-buffer fetch
(rgb-0.5 decode) not found"* now patch: that anchor existed only to estimate
a hair tangent, and skin never needed it. The two GI resolvers that Tier-3
used to skip are also covered now — the hair patcher took an early-return
path for them, so **faces lit only by bounce light previously got no gloss;
now they do.**

### 8.4 The overlay rename, and the trap avoided

`swaps.hair` → `swaps.skin`, which means `swap_layer.c`'s overlay list
changed and the layer was rebuilt. The name `hair` was **removed** from the
list rather than kept alongside: overlays are first-file-wins, so a leftover
`swaps.hair/` from an older install would have shadowed the new skin modules
for the same shader ids and silently served the retired build. Dropping the
name makes any stale directory inert.

The dead artifacts (`swaps.hair/`, `hair.set/`, `hair.disable`) were removed
from the install; the user's own `swaps.hair.bak_*` / `.tuned_*` snapshots
were left alone.

### 8.5 Verification

- 77/77 `spirv-val` clean, both sets, and the `off`/`on` pair asserted equal
  in coverage and non-identical in bytes by the build itself.
- Rebuilding the `off` set is byte-reproducible (77/77 identical).
- CET layer: 9 stubbed checks — the hair switch is gone, the skin switch and
  gloss switch behave, the shadow-leak fix survived, `hair=` is no longer
  written to the params file, and all three silent-no-op warnings still fire
  against the renamed keys.
- `sync_settings.sh`: sandboxed A/B/A across the real 77-module sets returns
  to the identical content hash, `skin=off` gates the overlay, caches evict
  on change and are kept when unchanged.

### 8.6 Migration note for an existing install

`brdf_params.txt` may still carry a `hair=` line; it is simply no longer
parsed, and `init.lua` drops it the next time it writes the file. `skin`
defaults to **on**, so the tier-1 c1 that `hair=off` had been suppressing
comes back on the next launch — expect skin to change even with the gloss
switch off, and note that is the shipping feature returning, not the gloss.


---

## 9 — Strength: why it is a ladder and not a slider

2026-08-29, asked as *"make it very obviously oily to start, or add my own
slider to tune it"*.

### 9.1 A slider is not possible here, and pretending otherwise has a cost

`n_s`, `spec_gain` and `alpha_max` are emitted as `OpConstant`s into the
patched SPIR-V. Nothing reads them at runtime; there is no uniform, no push
constant, no CVar. A CET slider bound to them would move a number in
`brdf_params.txt` and change nothing on screen — which is precisely the
inert-slider failure already on the books (`26` §5: six numeric skin-BRDF
sliders whose only consumer was a script not in the launch options, found
only after a whole A/B session was shot with them).

So strength is a **ladder of pre-built sets**, selected at launch, reusing
the `shadowset` machinery that already works: `--sets` builds one overlay per
level, parks them in `skin.set/<level>/`, and `sync_settings.sh` materializes
the named one into `swaps.skin/`.

### 9.2 The ladder, and why `alpha_max` is the whole story

| level | `n_s` | `spec_gain` | `alpha_max` | roughness cap | Fresnel exp |
|---|---|---|---|---|---|
| off | — | — | — | — | c1 only, the A/B control |
| subtle | 0.60 | 1.0 | 0.1600 | 0.40 | 4.0 |
| medium | 0.70 | 1.2 | 0.0900 | 0.30 | 3.0 |
| **strong** | 0.80 | 1.5 | 0.0450 | 0.21 | 2.0 |
| extreme | 0.90 | 2.0 | 0.0200 | 0.14 | 1.0 |

**`strong` is the default.** The feature is opt-in, but once opted into it
should be visible; a default nobody can see is indistinguishable from a
default that does not work.

The important number is the roughness cap. Authored skin roughness in this
game sits around **0.40–0.60**, and `alpha_max` is a *ceiling* — so the
previously shipped 0.2025 (cap 0.45) barely bit at all, which is the most
likely reason the first build would have read as "nothing happened". Every
rung below 0.40 is doing real work; above it, almost none.

The Fresnel half only broadens the falloff. Its `saturate(2-r)` amplitude
term is clamped to 1 across this entire direction (`§7.1`), so `spec_gain` is
the only amplitude lever, and `F'` is clamped to 1 regardless because Fresnel
reflectance cannot exceed unity.

`extreme` is a **diagnostic rung**, not a look: it answers "is the splice
reaching the screen at all" unambiguously, and is expected to read as wet
plastic. Reach for it when the answer is in doubt, then come back down.

### 9.3 Off-ladder values

`--set` overrides any rung, so a custom strength is one command and a
relaunch:

```
./dev/patch_compute_skin.sh --sets --set alpha_max=0.06
```

The CET tooltip says this, because the alternative is someone hunting for a
slider that cannot exist.

### 9.4 What the build asserts about the ladder

Beyond the equal-coverage check every set already had, `--sets` now asserts
each rung differs **from the baseline and from the rung below it**. Two
identical rungs under different names would let the selector appear to work
while comparing nothing — the same class of silent no-op as the inert
sliders, and the check that would catch a knob that turned out not to reach
the shader.

The unpatched-module roundtrip check now runs once for the whole ladder
rather than once per rung: same disassembly every time, so repeating it
multiplied build time for no extra signal.

### 9.5 Verification

Nine stubbed CET checks: five levels offered, `strong` by default and
persisted, the label admits it is launch-gated and names the rebuild escape
hatch, `extreme` and `off` round-trip, legacy `skinspec=on` migrates to
`strong`, an unknown level falls back to `off` rather than to a wrong
strength, a level mismatch between selector and served set warns (not just
on-vs-off), and the running level appears in the label.
