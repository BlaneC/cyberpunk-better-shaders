# 91 — Glass Fresnel: the reflection was deleted, and the bend was never real

Written 2026-09-01. Falsifies the physics of `76` (Phase 0.5, KEPT on screen
2026-08-31) from a user screenshot, and replaces it with a Fresnel-weighted
mirror. Built, verified offline, installed, launched, **ON SCREEN.**

## USER VERDICT 2026-09-01: KEEP — "the fres is much better. Looks awesome. Thats the new defact look."

`refract=fres` (`cb868ff35daff75b`) is the standing selection. Adjudicated PASS
against §6's first pre-registered outcome. **Recorded from the user's words, not
from a capture read by this session** — no screenshot of the `fres` frame was
read here, and the per-pixel "no doubled copy at any angle" claim in §6 was not
independently re-examined.

**What was NOT run, and what therefore stays open.** The user went straight to
the feature rung. **Neither diagnostic was shot**, so:

- **`20` open item 1 (does the consumer add or replace?) is STILL OPEN.** §3's
  claim that this ladder answers it cheaply is unredeemed. `fres-null` is
  installed and costs one launch whenever someone wants it.
- **The F² double-apply question (§3, `fres-flat`) is unresolved but now
  unlikely.** If the consumer applied its own Fresnel, `fres` would render F²
  — reflections near-invisible except at grazing. The user reports the
  reflections are back and the look is good, which is **evidence against** a
  severe downstream Fresnel. It is not proof: a mild one would still be
  double-applied and would read as "slightly too dark head-on", which is not a
  thing an unaided eye separates from correct glass. `fres-flat` remains the
  probe if anyone ever wants certainty.
- The `fres` vs `fres-schlick` and `fres` vs `fres75` comparisons were not run.
  Both are parked and installed.

Everything in §0-§5 below was written before the launch and is unchanged by it;
it remains an offline argument about bytes and arithmetic, now with one
on-screen verdict on top.

---

## 0. What the screenshot showed, and what it falsifies

User capture `photomode_01092026_133916-judy-refraction.png`, from the
2026-09-01T13:10:37 launch (`refract=eta15`, `tier=on`, `ptrefl=on`, RT
Overdrive). Judy in a car; a second, smaller, non-mirrored copy of her sits to
frame-right, inside the window glass.

Measured (normalised cross-correlation of a face patch against the ghost
region, luma, scale-swept): best match **dx ≈ +270 px on an 810 px frame —
34% of frame width — at scale 0.88, NCC 0.48**. Other body patches land
+170…+270 with inconsistent scale, i.e. the displacement field is
**non-rigid**. A rigid ghost would be a reflection; a non-rigid one is a bend.
Attribution is strong but **not A/B-proven** — no `refract=off` frame from that
camera exists. `fres-null` (§3) settles it as a side effect.

Three separate defects, and only the first was suspected:

**(i) The bend is 17–25° where physics says ~0.** A car side window is a flat
pane ~4 mm thick. Both interfaces cancel: the exit ray is *parallel* to the
entry ray. The only residual is a lateral offset.

| θ | 30° | 45° | 60° | 75° |
|---|---|---|---|---|
| thin-slab lateral offset, 4 mm, n=1.5 | 0.78 mm | 1.32 mm | 2.05 mm | 2.99 mm |
| `76` single-interface deviation | 10.5° | 16.9° | 24.7° | 34.9° |

**Correct flat-pane refraction is invisible.** Sub-millimetre. So the visible
displacement is not "too strong" — it is a category error, and lowering η only
shrinks a duplicate that should not exist. At η→1 you have rebuilt `off`.

**(ii) The reflection was deleted at every angle.** `patch_refract.py` rewrites
**all 19** downstream uses of the mirror direction `%242-244` to the refracted
direction — *including the env-miss cubemap lookup* `%296-298`, so the sky and
streetlight reflections went with it. `grep -i fresnel dev/patch_refract.py`
returns one comment about float-glass transmittance and nothing else. `76` §0
says it in words: Phase 0.5 "**replaces** the traced direction wholesale."
The user's report — *"there's no reflection anymore in the glass"* — is
literally true and is a property of the patch, not of the scene.

**(iii) The bent copy is laid over an untouched raster see-through.** `76` §0
predicted exactly this and named the screenshot as the test: *"the raster
alpha-blend see-through underneath is untouched, so the bent view is laid over
the straight one — 'does it warp or ghost' is precisely the question the launch
answers."* **It ghosts.** That question is now closed.

**The trap to state plainly, because it will otherwise be re-litigated:** the
bent look the user liked in `76` and the doubled ghost they dislike in `90`'s
successor launch are *the same pixels*. Under an adding consumer there is no
version of a second traced background copy that bends without doubling. A
"milder η" rung is a milder ghost, not a fix.

## 1. Is a physics-abiding reflection + refraction possible? Yes — and the
## answer is that the refraction must not be traced at all

Vanilla glass is **raster alpha-blend see-through + screen-space Distortion +
this pass's traced mirror reflection** (`20` §1). The see-through is drawn by
the raster layer, which this module cannot reach (`86` §0: no material fetch of
any kind; `20` §5b: "the straight-through view of the world is produced by the
raster alpha-blend, which this module cannot reach").

For a flat pane that raster see-through **already is the physically correct
transmitted image** — zero net bend, per the table above. What it lacks is the
`(1−F)` dimming. What this pass lacks is the `F` weight on the reflection.

So the whole physically-real angle-dependent effect on flat glass is the
**reflection ramping to a mirror**, and it is reachable:

| θ | 0° | 30° | 45° | 60° | 70° | 75° | 80° | 85° | 89° |
|---|---|---|---|---|---|---|---|---|---|
| F exact, n=1.5 | .040 | .042 | .050 | .089 | .171 | .253 | .388 | .613 | .904 |
| Schlick F₀=.04 | .040 | .040 | .042 | .070 | .158 | .255 | .410 | .648 | .919 |

That is "reflection takes a stronger seat as we go off angle", stated as a
number. Below ~60° the pane is ≥91% see-through; past ~75° reflection takes
over hard.

**Under an adding consumer, no traced transmission can avoid duplicating the
raster copy.** That is arithmetic, not an implementation limit. The things a
traced transmission could add that raster lacks — Beer–Lambert tint in thick
glass, rough-transmission blur, glass-behind-glass — all still arrive *on top
of* the raster copy, so they all ghost. The one theoretical escape, writing
negative radiance to cancel the raster term (the buffer is signed fp16,
±65504), is a denoiser and clamp landmine. **It is not an option**, recorded
here so nobody gets clever about it later.

### Two honest limits of what is built

1. **It is not energy-conserving and cannot be.** The composite becomes
   `F·reflection + 1.0·transmission`, because the raster transmission is
   unreachable and stays undimmed. Slightly over unity at grazing. Correct
   reflection lobe stapled onto an undimmed see-through — say that rather than
   claiming physical glass.
2. **"Refraction is invisible" is a flat-pane claim, not a glass claim.**
   Bottles, tumblers, curved storefronts and windshield rake do bend visibly.
   This module has no thickness or curvature input and cannot tell them apart.
   Modelling the pane is the right call on a pass that mostly runs on windows,
   and it is a *choice*, not a derivation. If visible bend on flat glass is
   wanted as a stylisation, the engine already owns the correct knob for it —
   the screen-space Distortion feature, which warps the *single* transmission
   copy instead of adding a second one. That is a different mod surface.

## 2. Mechanism

`dev/patch_glass_fresnel.py`. Text splice on the **committed ptrefl spvasm**,
not on a `76` rung — the patcher refuses any source carrying Phase 0.5's
`%float_refr_eta` marker, because Fresnel weights the *mirror* term and on a
refracted rung the weight means nothing. So these rungs revert the bend by
construction: they never contain it.

**The input.** `%235 = OpDot %float %236 %237` at `:512` — the module's own
`dot(D,N)`, where `D = normalize(P)` is camera-relative (`%193-195` → `%201-203`)
and therefore points **toward** the surface, and `N` is the glass normal.
`cos θᵢ = |%235|`.

**`|dot|`, not `clamp(−dot, 0, 1)`.** Normal-mapped glass hands back wrong-sign
cosines; clamping a negative to 0 yields `F = 1`, a full mirror on a pixel at
near-normal incidence — bright rim artifacts. `abs()` folds a flipped normal
onto the equivalent front-facing angle. The outer clamp to 1 guards `|dot| > 1`
from a denormalised normal, which would otherwise put a NaN in the sqrt.

**The math**, exact unpolarized dielectric Fresnel (20 instructions):

    c  = clamp(|dot(D,N)|, 0, 1)        ; cos θᵢ
    g  = sqrt(1 − (1−c²)/n²)            ; cos θₜ
    rs = (c − n·g)/(c + n·g)
    rp = (n·c − g)/(n·c + g)
    F  = (rs² + rp²)/2
    M  = 1 + strength·(F − 1)           ; lerp(1, F, strength)

**No branch is needed and no denominator can vanish.** Entering a denser medium
makes TIR impossible: `1 − (1−c²)/n² ≥ 1 − 1/n² > 0`, so `g ≥ sqrt(1−1/n²)` and
the denominators are bounded below by `sqrt(n²−1)` and `sqrt(1−1/n²)` — 1.118
and 0.745 at n=1.5. The build asserts that bound numerically over 6000 samples
rather than trusting the algebra; it measures **0.7454**, the bound exactly.

**Schlick is built alongside, not instead.** It is up to 4 points high at
80–85° — precisely the band this feature exists to get right — and 4 points on
a term that then goes through ×1/64, compositing, denoise and tonemap may well
be invisible. Exact costs 20 instructions against Schlick's 8. The splice risk
that would normally argue for Schlick is bought off by the self-check, so both
ship and the comparison is available rather than argued about.

**The site** is `86` §2's, unchanged and re-used: the radiance triple exists as
a single named value in exactly one place — the phis `%273/%275/%277` at the
top of block `%2827`, merging the env-miss arm (`%2826`) with the hit arm after
aerial-perspective fog (`%2825`). `%235` is defined at `:512`, on the gate-pass
path that is the only way into `%2827`, so it dominates the site; the build
asserts the ordering. Both are upstream of the module's own ±65504 clamp at
`%2830` (GOTCHAS: *scale before a clamp*). All **6** downstream uses on **4**
lines — the volume-probe magnitude `%710` and the three
`frontier_phi_2_5_ladder*` phis at `%2829` — are rewritten or the build dies.

**Alpha is untouched in every rung.** It is the transparent-gate *depth*
(`20` §1), not a coverage flag, and the consumer plausibly tests it. Check 4
greps the `OpImageWrite` composite in every built rung.

**Id space.** 2850–2874, chosen to sit *below* `patch_refract.py`'s 2900–2918
and `patch_refract_absorb.py`'s 3000+, so the three patchers stay composable
(apply absorb last — its `maxid >= 3000` guard fires otherwise).

## 3. The two diagnostics, and why `null` alone is not enough

Two independent unknowns gate whether `fres` will look right, and they need
different probes.

**`fres-null` — radiance := 0.** Answers `20` open item 1, open since August:
does the consumer **add** or **replace**? If glass keeps its see-through, the
consumer adds and our term is an overlay. If glass goes black, it replaces.

*Weaker than it looks.* The `76` ghost is already evidence for **adds** — a
replacing consumer would show one bent copy, not two side by side. Run it to
confirm, but the prior should be heavily on adds, which also means the
stochastic two-lobe combine (§5) is probably moot before anyone builds it.

**`fres-flat` — radiance := 8.0 constant.** Answers the unknown `null`
**cannot** see: **does the consumer apply its own Fresnel?** A raygen that
writes raw mirror radiance with no `F` is exactly what an engine does when the
BRDF weight lives in the composite pass, which has N and V in the G-buffer. If
it already multiplies by F, then `fres` double-applies to **F²** — reflections
crushed to near-invisible except at grazing, subtly wrong and very hard to
diagnose after the fact.

**Read it as:** feed the pass a constant, then look at whether the composited
glass reflection *still varies with viewing angle*. Angle dependence that we
did not write ⇒ downstream Fresnel ⇒ **do not ship `fres`**; the correct action
is then a plain revert of `76` and nothing more.

**Run `fres-flat` before believing `fres`.** It is the cheaper mistake to make
in that order.

## 4. Verification — all of it on the shipped bytes

`./dev/build_glass_fresnel.sh` fails the build on any row below.

| # | check | result |
|---|---|---|
| 1 | **knob-0 rebuild byte-identical to plain ptrefl** | **PASS** — `cmp` equal. At `strength=0` the patcher emits *no* constants, *no* body, *no* rewrites |
| 2 | **negative control**: patcher run on `swaps.refract.eta15` | **refuses** — anchors on the absence of `%float_refr_eta`, so it cannot weight a bent ray |
| 3 | all 5 rungs differ from plain ptrefl and from each other | `cmp` all pairs |
| 4 | **alpha untouched** — `%295 = (…, %270)` intact | **PASS** in every rung |
| 5 | **standing rungs untouched** — `off ac2cd8f7d550fe93`, `eta15 8c88926a273ae541`, `eta20 c96eaef809c8a734` | byte-identical to the shas `76` §2 recorded |
| 6 | `spirv-as --target-env spv1.4` + `spirv-val` | clean, 5 rungs + the knob-0 rebuild |
| 7 | **closed-form execution check, 6000 points/rung**, emitted text interpreted against an independently written float32 reference | worst relative error **4.67e-07** (exact), **4.18e-07** (schlick), **3.08e-07** (strength 0.75) |
| 8 | sample covers both normal orientations, exact grazing and exact normal incidence, radiance over 6 decades incl. 0 and negatives; build dies if no grazing sample is drawn | enforced |
| 9 | **no denominator can vanish** — min\|denom\| over the sample vs the proven bound `sqrt(1−1/n²)` | **0.7454**, the bound exactly |
| 10 | site coverage | anchors 6×1, **6 uses rewritten on 4 lines** (asserted `== 6` or the build dies) |
| 11 | dominance: `dot(D,N)` defined before the radiance phis | asserted |
| 12 | hand-read of the emitted diff | done: 2 constants + 23 instructions + 4 rewritten lines read correctly against §2 |

Not checked, and not checkable offline: whether any of it reaches a pixel.

### Built, installed to `refract.set/` 2026-09-01 15:21

| level | sha16 | what |
|---|---|---|
| `fres` | `cb868ff35daff75b` | exact unpolarized Fresnel, n=1.5 — **LIVE, the standing selection** |
| `fres-schlick` | `646ad1ab3012347e` | Schlick F₀=0.04 — the comparison |
| `fres75` | `731bd3487b3c6286` | `lerp(1, F, 0.75)` — softer, if F reads as "the reflection vanished" |
| `fres-null` | `ab192a7be9817097` | **DIAGNOSTIC** radiance := 0 |
| `fres-flat` | `116a5283a85dfb98` | **DIAGNOSTIC** radiance := 8.0 |

## 5. What was considered and killed

**Stochastic two-lobe (`F·refl + (1−F)·refr` by one ray).** Draw ξ, trace the
mirror if ξ<F else the transmitted direction, weight 1.0 either way. Unbiased,
one ray, pure `OpSelect` on 3 direction + 3 origin components. **Dead three
times over:**

- **No frame-varying entropy.** The module has `LaunchIdKHR` (`%90/%92`) but no
  confirmed frame counter. A pixel-coordinate hash is the *same pattern every
  frame*, so a temporally-dominated denoiser converges to the dithered image,
  not the mean — a static two-image checkerboard that crawls under camera
  motion. Not risky, *unimplementable*, until a frame counter or TAA jitter is
  found in the CBs.
- **Its transmitted lobe would be wrong anyway.** The obvious spec uses `76`'s
  single-bend Snell direction — the exact error §0(i) falsifies. For a thin
  pane the correct transmission lobe is **D unchanged, origin pushed through**,
  which deletes the Snell math entirely.
- **It pollutes hit distance.** Reflection denoisers key blur radius and
  reprojection off hit distance and virtual position assuming a *mirror* lobe.
  Interleaving transmission hits — different distances, different motion — into
  that stream smears. Changing the ray origin also changes what the alpha depth
  means to the consumer.

Do not build it unless a frame counter exists **and** `fres-null` surprises us
by reporting *replace*.

## 6. A/B protocol — settings first, diagnostics before the feature

**Required game settings, stated up front (`45`, memory rule) — state them
again in the message that reports the result:**

- Path tracing: **RT Overdrive ON**
- `tier=on`, `ptrefl=on` (the rung rides the ptrefl overlay; sync refuses as
  `off:needs-ptrefl` if either is off, and the picture is then vanilla glass)
- Ray Reconstruction: record its state (`DLSS_D` in `UserSettings.json`)
  before and after — `79` exists because nobody did
- **Move the camera and let it settle before reading any frame.** A frozen
  photomode shot can show stale accumulated reflection and fake a null result.

**Scene:** a car window or shopfront with the camera swinging from near-normal
to grazing across one continuous move — the effect *is* the angle sweep, so a
single fixed angle adjudicates nothing. The `76` bar glassware is a poor test:
it is curved, which is the one case §1 limit 2 admits this does not model.

**Order matters. Run the diagnostics first.**

1. **`refract=fres-flat`** → is there angle-dependent variation in the glass
   reflection under constant input? **Yes ⇒ stop.** Downstream owns the Fresnel
   and `fres` would square it; the correct action is `refract=off` and nothing
   more. **No ⇒ continue.**
2. **`refract=fres-null`** → does the glass keep its see-through (adds) or go
   black (replaces)? Expect adds. **Replaces ⇒ stop and re-scope**, §5's
   two-lobe combine becomes correct and necessary and this whole ladder is the
   wrong shape.
3. **`refract=fres`** vs **`refract=off`** — the feature, one variable.

Pre-registered outcomes for step 3:

- **PASS** — near-normal glass reads as see-through with only a faint sheen,
  and the reflection builds smoothly to a near-mirror as the camera goes
  oblique. No doubled copy of anything, anywhere, at any angle. Then compare
  `fres` against `fres-schlick` (expect no visible difference; if there is one
  it is at 80–85° and `fres` is the correct one) and against `fres75`.
- **"THE REFLECTION VANISHED"** — head-on F is 0.04, a 25× dimming versus
  today. If that reads as broken rather than as glass, `fres75` is the rung
  (M = 0.28 head-on, 0.71 at 85°). This is a *look* verdict, and `fres75` is
  honestly labelled as not physical.
- **NO CHANGE** — check `status.txt` `want_refract`/`req_refract` and the
  journal MANIFEST echo first. Served and traced but identical ⇒ the consumer
  is not using this buffer the way `20` §1 assumes.
- **Glass got brighter at grazing** — expected and predicted (§1 limit 1). The
  composite is `F·refl + 1.0·trans` and cannot be made to sum to one from here.

## 7. Serve and install — exact commands

**Do not run `make install` from this document without checking who else is
mid-deploy** (parallel-agent race; this session deliberately did not run it,
and did not commit).

```bash
# 1. deploy the repo (only if the installed tree is stale -- 45 §1 cmp first)
make install

# 2. park the five rungs beside the existing refract ladder
./dev/build_glass_fresnel.sh --install    # -> ~/.local/lib/callisto/refract.set/

# 3. select one. sync_settings.sh's refract block takes ANY refract.set/<level>
#    by name (it only special-cases "off"), so no CET/init.lua change is needed:
sed -i 's/^refract=.*/refract=fres-flat/' \
  "<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt"
```

The CET selector still lists only `off/eta15/eta20`; it will read *"Glass
refraction experiment: …"* while `brdf_params.txt` says `fres-flat`. **That is
the `27` §8 / "one knob, two defaults" trap in miniature** — trust
`status.txt`'s `want_refract`/`req_refract` and the journal MANIFEST echo
(`ptrefl refract=fres … sha=cb86…`), not the selector, until someone adds the
levels to `init.lua`.

Confirm the serve before believing anything:

```bash
grep -E 'want_refract|req_refract|last_refl' ~/.local/lib/callisto/status.txt
sha256sum ~/.local/lib/callisto/swaps.ptrefl/ee6d252e090adc74.*.spv | cut -c1-16
tail -5 ~/callisto_launches.log
```

Rebuild without installing: `./dev/build_glass_fresnel.sh` (no flag).

## 8. Consequences for the standing docs

- **`76` is RETIRED.** Its KEEP verdict stands as a record of what the user said
  on 2026-08-31, not as a physics claim; §0 falsifies the model behind it and
  `fres` beat it on screen on 2026-09-01. `76` §3's "warp vs ghost" question is
  answered: **ghost**. `eta15`/`eta20` stay parked and installed as A/B history;
  **do not select them as a look.**
- **`86` (Beer–Lambert absorption) is DEAD AS BUILT and needs re-siting.** Its
  `d` is `%267`, the *refracted* ray's hit distance, which exists only on a
  Phase 0.5 rung — and its patcher hard-refuses any source without the
  `%float_refr_eta` marker, so it cannot even be built on `fres`. The hue work
  in `86` §1 (soda-lime σ ratio, the luma-held rail) is still good; the site is
  not. Re-siting it onto the mirror term would mean tinting a *reflection* by
  path length, which is not what the brief wanted — the honest read is that
  coloured transmission is unreachable from this module for the same reason
  §1 gives for refraction: the transmitted image belongs to the raster layer.
- **`20` open item 1 (name the consumer) is STILL OPEN.** This ladder was built
  to answer it cheaply and then the diagnostics were not shot. `fres-null` and
  `fres-flat` are installed; either is one launch. See the verdict block.
- **The CET selector is now wrong in a way that matters.** It lists only
  `off/eta15/eta20` while the standing selection is `fres`, so the panel will
  misreport the live look. `init.lua` was deliberately not touched here. Adding
  the five levels to the selector is the obvious follow-up, and until then
  `status.txt`'s `want_refract` and the journal MANIFEST echo are the only
  truthful sources (`27` §8, "one knob, two defaults").
- **The shipped default is still `refract=off`** (`sync_settings.sh`). `fres` is
  the *de facto* look via `brdf_params.txt`, not the shipped one. Promoting it
  to the default is a one-line change nobody has asked for yet.
