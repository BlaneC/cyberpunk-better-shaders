# 26 — Session record 2026-08-28: the shadow-ray bisect, and two confounds

What this session actually produced, what it disproved, and what is still open.
Written because three separate things went wrong here in ways that were only
distinguishable from launch provenance, not from the screen — and the shadow
patcher, which was innocent, absorbed the blame twice.

`25-SHADOW-FLICKER.md` §8–§9 carries the shadow argument in full. This file is
the session's ledger and the resume point.

---

## 0. State at the end of the session

| thing | state |
|---|---|
| `full` (global 28→12) | **works, confirmed on screen.** Closes the hairline seam; flat props still flicker on LOD transitions. The shipping default. |
| `split` (opacity split) | **falsified on screen.** Seam returned. |
| `ctrl` (ray B = flags 12, mask untouched) | **validated on screen.** The two-ray splice executes and reaches the consumer. |
| `m6`, `m112` | **both regress.** Explained by §3 — not a splice bug. |
| `m1`, `m118`, `m119` | built, installed, **never launched**. `m1` is staged. |
| PT tier-1 (`24`) | **NO REGRESSION.** Retracted 2026-08-28: hair is correct with `ptbounce` and `ptrefl` both on. §4.2 was a false alarm. |
| MS-GGX energy compensation (`23` T2.1) | **launched, CONFIRMED on screen.** Single-variable A/B, §7e. Now default-on. |
| The six numeric skin-BRDF sliders | **found inert.** Not fixed — see §5. |

Staged for the next launch: `shadowset=m1`, PT held at the last proven-good
state (`ptreg=on ptclamp=on ptbounce=off ptrefl=off`).
*(Both staging notes are void: §7d deleted `m1` with the other mask sets —
`full-shadow` shipped — and §4.3 retracted the "proven-good" PT constraint.
The §7e launches ran `rcb` with `ptrefl=on`. Defaults now: `ptreg` off;
`ptclamp`, `ptbounce`, `ptrefl`, `ptmsggx` on.)*

---

## 1. The opacity split, falsified

`25` §8 shipped a second shadow trace with `CullOpaqueKHR`, on the premise that
hair is alpha-tested (non-opaque) in the BLAS and could therefore be
discriminated from solid props by opacity alone.

The launch disproved it: the seam came back, while the layer log proved the
split set was the one loaded (10 swaps, 0 failed, byte sizes matching).

The premise was backwards. `17` §2 records the PT visibility ray using flags
`10 = NoOpaqueKHR | SkipClosestHitShader` — and `NoOpaqueKHR` **forces**
geometry non-opaque, which is only necessary because it is authored **opaque**.
A ray that forces a property tells you what the geometry is *not*.

**Opacity is dead as a discriminator here.** What survived is the mechanism:
`min(tA, tB)` over a single-float payload, exact, no control flow, ray A
untouched. `dev/patch_shadow_opacity.py` now takes `--ray-b-flags`,
`--ray-b-mask` and `--ray-b-tmin`, which turns it from one hypothesis into a
probe.

## 2. The variant matrix and the selector

Thirteen sets, all covering the same 18 modules (the build script asserts it),
parked in `$INSTALL_DIR/shadowcull.set/<name>/` at 134 MB total. The CET
boolean became a **name-based selector** (`shadowset=<name>`, legacy
`shadowsplit=on|off` still mapped for one migration launch), so the whole
bisect is walkable across relaunches with no rebuild.

| set | ray B |
|---|---|
| `full` | *(none — 28→12 in place)* |
| `ctrl` | flags 12, mask untouched |
| `m1` `m6` `m112` `m118` `m119` `m2` `m4` `m16` `m32` `m64` | flags 12, mask ANDed down |
| `split` | flags 76 (`CullOpaque`) |

The mask is emitted as `OpBitwiseAnd` against ray A's **own** mask operand, not
as a replacement, so ray B stays a strict subset of what ray A could have seen
whichever arm of the runtime `OpSelect` won.

## 3. The class-1 hole — why `m6` and `m112` both regressed

`ctrl` validating proved the splice runs. Both `m6` and `m112` regressing then
looked impossible: they partition ray A's mask, and one overlapping bit is
enough for a hit, so if `full` closes the seam one of them had to.

The premise was wrong. **The two trace families do not carry the same classes:**

| family | sites | mask operand | classes |
|---|---|---|---|
| `rgs_shadow_main` | 20 | `OpSelect(86, 38)` | {2,4,16,32,64} = **118** |
| `rgs_restirgi_*` | 8 | `OpSelect(87, 39)` | {1,2,4,16,32,64} = **119** |

`m6` ∪ `m112` = 118. That partitions everything the *shadow* traces can see and
misses **class 1 entirely** — a class only the *GI* traces carry. Both variants
dropped it; `ctrl` touches no mask and kept it. Every observation is consistent.

The bisect had been designed off one sampled module (`b80f16ff.rgs_shadow_main`)
whose mask was generalised to all 18 without checking. Enumerating all 28
patched sites takes seconds.

Three sets close the hole:

| set | ray B mask | isolates |
|---|---|---|
| `m1` | `& 1` | class 1 alone. **Zero** mask on all 20 shadow sites — ray B hits nothing there, so they stay exactly vanilla — and class 1 on the 8 GI sites. |
| `m118` | `& 118` | everything except class 1; the complement of `m1`. |
| `m119` | `& 119` | every class, both families. Should match `ctrl`; a second control. |

Reading the result:

- **`m1` closes it** → the occluder is GI-side class 1. Structural corollary:
  86/38 exclude bit 0, so the *direct* shadow traces never see that geometry at
  all, and the hairline seam is an indirect-lighting artifact rather than a
  direct-shadow one.
- **`m1` fails but `m118` works** → more than one occluder, split across
  classes, all needing unculling. This is the only scenario consistent with
  `m6` and `m112` both failing while their union works. Narrow by pairs.
- **only `m119` works** → occluders on both sides of the class-1 line.
- **none close it** → the mask is not the axis. Next lever is `--ray-b-tmin`
  (already implemented, needs a row in `VARIANTS`): hair cards sit at sub-mm
  spacing, so a raised tMin on ray B alone would skip a flat prop's coincident
  back face while still catching a hair card millimetres away.

## 4. The two confounds

### 4.1 An `m112` launch read as a `full` launch

A session was reported as "`full` still shows the seam". It was running `m112`.
`sync_settings.sh` had materialized `m112` at launch; the selector was moved to
"Uncull everything" *during* play and a save reloaded, which changes nothing —
the layer only substitutes SPIR-V at `vkCreateShaderModule`, i.e. at startup.

Provable from the layer log, and only from there: each parked set has distinct
per-file byte sizes, and the eight `rgs_restirgi_*` sizes are the discriminator
(the `rgs_shadow_main` sizes **collide** between `m6` and `m112`).

### 4.2 The PT tier-1 overlays regressed hair

Then "`full` doesn't fix hair the same way" — this time on a genuine clean
relaunch. Fingerprinting the served `swaps.shadowcull/` payload per launch:

| pids | payload | ptq | ptrefl |
|---|---|---|---|
| 1148450 → 1190018 (8 launches) | `a343a1500587` | **0** | **0** |
| 1205967, 1233620, 1240949 | `a343a1500587` | 15 | 3 |
| 1215461 / 1235331 / 1237336 | split / m6 / m112 | 15 | 3 |

Launch 1240949 — *after* `full` was rebuilt — served a **byte-identical**
payload to the eight launches from the era when the fix demonstrably worked.
That cleared the rebuild and the shadow patcher outright, and moved the suspicion
to the column on the right: those eight known-good launches are exactly the
eight with no PT overlays, which had landed earlier in this same session.

Confirmed by A/B: all four PT switches off → hair correct. Then **Launch A**
(`ptreg=on ptclamp=on ptbounce=off ptrefl=off`) → still correct, clearing both
*intensity* edits. The culprit is one of the two cullMask wideners — `ptbounce`
(T1.4, 1→255 on the bounce raygens) or `ptrefl` (the same on the three
reflection raygens). Both change *what geometry a ray can hit* near hair;
T1.4's own tooltip warns it can reveal "proxy geometry the mask was there to
hide". **Not yet resolved** — Launch B was staged but never reported.

### 4.3 Retraction: there was no PT regression

The hair fault in §4.2 does not reproduce. With `ptbounce` and `ptrefl` both
**on**, hair is correct. All four tier-1 edits ship clean.

What §4.2 actually caught was the shadow-set confusion of §7a -- launches
attributed to the wrong `shadowset` before the content-hash journal existed.
Every "suspect" line above is void, `ptreg`/`ptclamp`/`ptbounce`/`ptrefl` are
all cleared, and the "last proven-good state" was never a constraint.

Method note, again: two variables moved at once (PT overlays and shadow set)
with no per-launch fingerprint. The journal added in §7 is the fix.

## 5. Bugs found

| bug | state |
|---|---|
| **Pipeline caches evicted every launch.** The stamp hashes `stat -c '%n %s %Y'` over the served `.spv`; every parked-variant overlay re-copies each launch, and plain `cp -f` stamps a fresh mtime, so the hash never matched and every launch recompiled every shader. | **fixed** — `cp -pf` at all five materialization sites. Verified: same selection twice → "caches kept"; changed → "cleared". |
| **The six numeric skin-BRDF sliders are inert.** `rho_f`, `n_f`, `m_f`, `rho_r`, `n_r`, `m_r` are read by nothing. Their only consumer is `regen_and_clear.sh`, which is not in the Steam launch options (no `regen.log` has ever been written); `sync_settings.sh` does not parse those keys. Relaunching does not help. | **found, NOT fixed.** The panel now says so on the subcategory header and in each tooltip. Two options: fold the regen into `sync_settings.sh` (costs a patcher run when they change), or drop them and treat the baked values as fixed. **Design call, deferred.** |
| **`nativeSettings.removeSubcategory` corrupts tab key order** — it ends with `keys[i] = nil`, a hole rather than a `table.remove`, after which `#keys` is undefined and any indexed `table.insert` can silently orphan the tab. | **avoided.** A live "PENDING" banner was built on remove/re-add and backed out; `pcall` does not help because nothing throws. |

## 6. UI changes

- The shadow selector's **label** carries the running set — `Shadow-ray build
  [running: m112]` — not the tooltip. A tooltip you have to hover is not where
  anyone looks when the picture is wrong.
- Nine launch-gated widgets now say **"(next launch)"** in the label.
- `warnLine()` shouts when the selector and `status.want_shadowset` disagree at
  session *start*, which means the game was launched outside the Steam launch
  options and `sync_settings.sh` never ran.
- Unknown/unbuilt set names fall back to `full`, loudly, on stderr and in
  `status.txt` (`want_shadowset_req` vs `want_shadowset`).

## 7. Resume point

1. **Launch `m1`** (staged). Read the outcome per §3.
2. **Resolve the PT regression**: `ptbounce=on, ptrefl=off` with the shadow set
   held fixed. If hair goes wrong it is T1.4; if not it is `ptrefl`.
3. Keep the two bisects strictly sequential. Moving a PT switch and the shadow
   set in the same launch is what produced §4.

Discipline that actually worked, and should be kept: hold every other switch
fixed, one variable per launch, and confirm from the layer log which payload
was served before believing any observation.

## 7a. The collapse: `ctrl` was never launched

`m1`, `m118` and `m119` all came back vanilla. `m119` is the tell: every mask in
the module is a subset of 119 (`86&119=86`, `38&119=38`, `87&119=87`,
`39&119=39`), so **`m119` is a semantic no-op and should be bit-for-bit `ctrl`**.
Disassembling both confirms it — they differ by exactly four `OpBitwiseAnd`
instructions computing `mask & 119`, and nothing else. `ctrl` reportedly worked
and `m119` did not, which is impossible.

Checking the layer log settled it: **no launch has ever served `ctrl`'s
payload.** Its size signature is unique among the 15 sets and appears in zero of
the 27 shadowcull launches. The "control validated" result was not backed by a
run, and three more sets were built on top of it.

One hypothesis now covers every observation with no contradiction:

| observation | "ray B is inert at runtime" predicts |
|---|---|
| `full` works (17 launches) | ✓ it edits ray A **in place**; no second ray involved |
| `split` vanilla | ✓ |
| `m6` `m112` `m1` `m118` `m119` vanilla | ✓ |
| `ctrl` "validated" | never ran |

**The second trace is almost certainly doing nothing.** Everything in §1–§3 that
depends on ray B working is therefore unproven, including the class-1 argument.
§3's *enumeration* (the two families carry different classes, 118 vs 119) stands
on its own as a static fact; the *conclusion* drawn from `m6`/`m112` does not.

### Methodology failures that produced this

1. **The matrix was built before the mechanism was verified.** Ten sets, a
   selector, docs and six launches all rest on "ray B works". `ctrl` was
   designed as that gate and never enforced as one.
2. **A reported result was accepted without provenance** — the discipline this
   very file's §4 was written to install.
3. **The provenance method cannot resolve the variants it is used on.** Size
   fingerprinting distinguishes 7 classes of 15: in binary SPIR-V an
   `OpConstant` is the same size whatever its value, so `m1/m2/m4/m6/m16/m32`
   are mutually indistinguishable, as are `m118/m119`.
4. **No fixed readout** — "looks vanilla" by eye, across sessions, with no
   fixed camera or screenshot.
5. **Two bisects interleaved**, after §4 said not to.

### The pivot: bisect modules, not rays

`full` works, and it works by editing ray A in place — the one mechanism proven
on screen. So apply *that* edit to only part of the 18 modules:

| set | modules | asks |
|---|---|---|
| `full-shadow` | the 10 `rgs_shadow_main` | do the direct shadow rays alone close the seam? do they alone cause the flicker? |
| `full-gi` | the 8 `rgs_restirgi_*` | same question for the GI rays |

They partition `full` exactly (10 + 8 = 18, verified by `comm`), and each
module's bytes are **identical to `full`'s copy** of it — the only difference is
which modules are present in the overlay at all, and an absent module is served
by the game unpatched. If the seam and the flicker come from different families,
that split *is* the fix, with no second ray anywhere.

If they come from the same family, split that family again the same way.

### Provenance fix

`sync_settings.sh` now appends one line per launch to `~/callisto_launches.log`,
keyed on the **content** hash of what was actually served:

```
2026-08-28T13:46:54-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a \
    ptq=rc+skin ptrefl=off hair=off tier=1 cache=cleared payload=36d3ad55244a9861
```

Every future observation is attributable to an exact payload. Run `ctrl` once as
a post-mortem on whether the second ray works at all; if it is vanilla, delete
the ten `m*`/`ctrl`/`split` sets rather than leave them in the menu as loaded
footguns.

## 7b. The module bisect works — and the remaining flicker has a named cause

**`full-shadow` (the 10 `rgs_shadow_main` only): keeps the hair effect and
visibly reduces the pop/flicker.** Confirmed on screen 2026-08-28.

Since `full-shadow` ∪ `full-gi` = `full` exactly, and `full-shadow` alone keeps
the seam closed with *less* flicker than `full`, the GI-side unculling was
contributing flicker and nothing visible to the seam. **Drop it.** The direct
shadow rays are the whole mechanism.

Some flicker remains. Enumerating the 20 patched sites in that family by their
ray extent splits them cleanly in two:

| tMin | tMax | sites | what it is |
|---|---|---|---|
| `1e-6` | dynamic | **17** | bounded — the ray stops at the light |
| **`0`** | `FLT_MAX` | **3** | unbounded, **zero bias** — directional / sun |

Those three are the acne risk. With no bias whatsoever, **back-face culling is
the game's own self-intersection guard** on them: clear it and a surface can
shadow itself at t≈0. That is the textbook mechanism for a flat prop flashing
black, and it fires exactly when an LOD swap changes winding or introduces a
coincident face.

Three variants, all using the proven in-place edit:

| set | sites | asks |
|---|---|---|
| `full-shadow-nosun` | the 17 bounded | is the remaining flicker entirely the sun rays? |
| `full-shadow-bias` | all 20, sun tMin `0` → `0.001` | can the sun rays keep unculling if given a real 1 mm bias instead of the guard they lost? |
| `full-shadow-sun` | the 3 sun sites only | the complement, to confirm attribution |

Decision path: run `full-shadow-nosun` first. If the seam stays closed and the
flicker is gone, ship it — the sun rays were never needed. If the seam reopens,
the sun rays do matter and `full-shadow-bias` is the candidate that keeps them
while restoring a self-intersection guard. If 1 mm is not enough, raise
`--set-zero-tmin`; the flag is general.

`dev/patch_shadow_flags.py` gained `--tmin-sites {all,zero,nonzero}` and
`--set-zero-tmin T` for this.

## 7c. The sun-ray theory is falsified; the axis is geometry, not sites

`full-shadow-nosun` (the 17 bounded sites, sun rays left vanilla, launched
14:36:25, `sc_sha=2e679abe5acb0fb5`): **seam closed, flicker unchanged.**

So the 17 bounded sites are on their own necessary and sufficient for the seam,
and they are also where the flicker lives. The 3 zero-tMin sun rays are not the
acne source and are not needed for the seam. `full-shadow-bias` and
`full-shadow-sun` are moot; leave them in the menu but expect nothing.

**The ray-site axis is exhausted.** Every result so far says the same thing:
any subset of the direct shadow traces that closes the seam also brings the
flicker, because the edit is per-*ray* and a ray is all-or-nothing over
geometry. The 28 -> 12 flag change removes back-face culling for *everything*
the ray can reach.

The only remaining axis is **which geometry loses culling**, and the only lever
for that is the `CullMask`, which lives on the ray, not on the flags. So the
shipping shape must be two rays per site:

    tA = trace(flags 28, mask M)          everything, culled -- no flicker
    tB = trace(flags 12, mask M & hair)   hair only, unculled -- closes seam
    t  = min(tA, tB)

which is exactly the splice `patch_shadow_opacity.py` emits, and exactly the
mechanism that has never been shown to run. Every `m*` result to date is
uninterpretable for that reason (`§7a`).

### The positive control

`ctrl` was built neutral -- ray B a duplicate of ray A -- so "looks vanilla"
was consistent with both "the splice works" and "ray B is inert". It could
never have decided anything. `sctrl` fixes that by being *loud*:

| set | ray A | ray B | modules | must look like |
|---|---|---|---|---|
| `sctrl` | flags 28, mask M | flags 12, mask M | the 10 `rgs_shadow` | **exactly `full-shadow`** |

Ray 12's hit set is a strict superset of ray 28's, so `tB <= tA` always and
`min()` is always ray B. If `sctrl` closes the seam, the splice runs and the
mask bisect becomes valid. If `sctrl` looks vanilla, ray B does not execute,
and `ctrl` / `split` / all ten `m*` sets should be deleted rather than left as
menu footguns.

Verified structurally before launch, on `1ddeee1de7a88da0.rgs_shadow_main`:

    OpTraceRayKHR %49456 %uint_28 %4970 ... %49449 %17
    %49459 = OpLoad %float %49450
    OpTraceRayKHR %49456 %uint_12 %4970 ... %49449 %17
    %49460 = OpLoad %float %49450
    %49461 = OpFOrdLessThan %bool %49460 %49459
    %49462 = OpSelect %float %49461 %49460 %49459     <- min(tA, tB)
    %49463 = OpFOrdEqual %bool %49462 %float_3_40282347e_38

6 traces (3 sites x 2), same accel and same mask on both, both writing payload
`%17`, and the downstream `FLT_MAX` miss test consuming the combined value.

Gated on `sctrl` passing, `sm6` (mask &= 6, classes {2,4}) and `sm112`
(mask &= 112, classes {16,32,64}) partition the shadow family's 118 and find
which half carries the hair. Both are shadow-modules-only, so they are
like-for-like against `full-shadow` and against `sctrl`.

## 7d. `sctrl` came back vanilla -- the splice is dead, and we ship

Launched 14:47:56, `sc_sha=d507b2e5a234695b`. **Vanilla.**

A working splice could not produce that. Ray B is unculled with the same mask,
so its hit set is a strict superset of ray A's, `tB <= tA` always, and `min()`
is always ray B -- `sctrl` had to look exactly like `full-shadow`. It looked
like neither. The disassembly is correct (paired `OpTraceRayKHR` into the same
payload, `OpFOrdLessThan` + `OpSelect`, the `FLT_MAX` miss test consuming the
combined value, `spirv-val` clean), so the edit is right and **the second trace
simply does not execute**.

That retroactively voids every mask experiment: `ctrl`, `split`, `m1`, `m2`,
`m4`, `m6`, `m16`, `m32`, `m64`, `m112`, `m118`, `m119`, `sm6`, `sm112`. They
varied a ray that never ran. It also explains `m6`/`m112` "regressing" and
`m1`/`m118`/`m119` going vanilla: they were all the same non-event.

Why the second trace does not run was not chased. Plausible causes, untested:
the pipeline's `maxPipelineRayRecursionDepth`, a driver or vkd3d-proton
restriction on multiple `OpTraceRayKHR` from one invocation in this shader
stage, or the shader binding table indices being wrong for the second call.
Anyone picking this up should start by confirming the second trace at all --
write a constant into the payload from a miss shader and read it back -- rather
than by building more variants.

### Shipped

| | |
|---|---|
| default `shadowset` | **`full-shadow`** |
| what it is | flags `28 -> 12` in place on the 10 `rgs_shadow` modules |
| `sc_sha` | `57ef80ee1f72f54a` -- byte-identical to the 13:52:58 launch the user validated |
| known cost | reduced but non-zero flicker on flat props at LOD transitions |
| second option | `full` (all 18 modules); same seam fix, more flicker |

Everything else was removed from the menu, from `swaps.shadowcull.*`, and from
the parked `shadowcull.set/` (197M -> 21M). The recipes and their results stay
in the header of `dev/build_shadow_sets.sh` so the work is reproducible; the
patchers themselves are untouched. `sync_settings.sh` maps any retired name to
`full-shadow` with a notice, and `init.lua` normalises a stale `shadowset=` in
`brdf_params.txt` on load so the selector cannot disagree with what is served.

Verified after the prune: a clean rebuild reproduces both sets **bit-identically**
to the pre-prune copies, and two consecutive syncs of the same selection report
`cache=kept` (the `cp -pf` mtime fix still holds).

### Left open

- ~~The PT tier-1 regression.~~ **Closed, no defect.** All four tier-1 edits
  are clean on screen; see §4.3.
- **The six numeric skin-BRDF sliders are inert** (`§5`). The panel says so.
  Either fold `regen_and_clear.sh` into `sync_settings.sh` or drop them.
- **The residual flicker.** Not fixable on the ray-flag axis; needs either the
  second trace to work, or an entirely different lever.
- **MS-GGX arms A/B** (optional, low priority): the confirmed build patches
  both GGX arms together; `--arms punctual` / `--arms area` in
  `dev/patch_ms_ggx.py` rebuild the halves if anyone ever wants the split.

## 7e. Coda: the MS-GGX build launched and confirmed

The session's last build was tier 2's first item — diffuse metal energy
restoration (`23` T2.1, the commit "Diffuse metal energy restoration"). The
blocker story, the fit, and the splice mechanics are `dev/MS_GGX_NOTES.md`
§2's; the feature doc is `28-MS-GGX-ENERGY.md`. What belongs here is the
launch record, because it is the first A/B run under the §7 discipline
end-to-end.

Built 18:25–18:26 — `m` joins the ptq matrix, now 15 combos, with
`patch_ms_ggx.py` chained over the tier-1 output. Then five launches, every
journalled variable fixed except `m` (`shadowset=full-shadow`,
`sc_sha=57ef80ee1f72f54a`, `ptrefl=on`, `hair=off`, `tier=1` throughout):

| time | ptq | `m` |
|---|---|---|
| 18:39:37 | `rcb+skin` | off |
| 18:45:10 | `rcb+skin` | off |
| 18:47:16 | `rcb+skin` | off |
| **18:50:11** | **`rcbm+skin`** | **on** |
| 18:59:57 | `rcb+skin` | off |

(An 18:44:47 double sync — `rcb` then `rcbm` in the same second — staged the
m-combo but no launch consumed it: the swap log holds exactly one complete
rcbm-sized module set, twelve files at +2152 B each, against four complete
m-off sets.)

Verdict from screen: **it completely worked** — rough metal visibly gains the
predicted energy, and reverts exactly with `m` off. The default was flipped
on afterwards (`init.lua` ×2, `sync_settings.sh`). One variable per launch,
provenance read back before believing the observation — §7's discipline,
working.

## 8. Files touched

| file | change |
|---|---|
| `dev/patch_shadow_opacity.py` | `--ray-b-flags`, `--ray-b-mask` (as `OpBitwiseAnd`), `--ray-b-tmin`; docstring rewritten to lead with the falsification |
| `dev/build_shadow_sets.sh` | `VARIANTS` table, 13 sets, subset builds, coverage assertion against `full` |
| `dev/install_shadow_sets.sh` | parks whatever `swaps.shadowcull.*` exists; no edit needed to add a variant |
| `release/.../sync_settings.sh` | `shadowset=<name>` with validation and fallback; `cp -pf` at five sites; `want_shadowset_req` in status |
| `init.lua` (+ 2 mirrors) | `SHADOW_SETS` selector, running-set in the label, "(next launch)" labels, inert-slider warnings, stale-session warning |
| `handoff/25-SHADOW-FLICKER.md` | §8 marked falsified; §9 added (falsification, class-1 hole, variant table, results) |
| `handoff/24-PT-TIER1.md` | the hair regression, with the per-launch fingerprint table |
| `handoff/GOTCHAS.md` | 5 entries (see below) |
| `dev/patch_ms_ggx.py` (new) | the T2.1 energy-compensation splice: both GGX arms, per-channel F0, loud scalar-specular skips |
| `dev/build_ptq.sh` / `dev/install_ptq.sh` | `m` joins the matrix — 15 combos, MS-GGX chained over the tier-1 output |
| `dev/fit_ms_ggx.py` | the `E_ss` blocker resolved (wrong arm + doubled NoL); α-only fit against the lobe's own mirror limit |
| `dev/MS_GGX_NOTES.md` | the working notes: upload survey + the full MS-GGX derivation |
| `sync_settings.sh` / `init.lua` (+ mirrors) | the `ptmsggx` gate and CET switch; default flipped on after §7e |
| `handoff/28-MS-GGX-ENERGY.md` | the feature doc, carrying the A/B evidence |

## 9. Evidence index

- Per-launch provenance: `~/callisto_swap.jsonl` — `{"ev":"log_open","pid":N}`
  per process, `{"ev":"swap_load","file":…,"size":N}` per swap. **The only
  record of what was actually in the frame on a given day.** `brdf_params.txt`
  is the *request*, is rewritten by CET during play, and drifted twice this
  session without anyone meaning to.
- MS-GGX A/B: the 18:39–18:59 lines of `~/callisto_launches.log` and the
  +2152 B `swaps.ptq` size signatures in `~/callisto_swap.jsonl` (§7e,
  `28` §6).
- Mask enumeration: all 28 patched sites across 18 modules, §3.
- `full` structural check: 4 traces, all `%uint_12`, no added ray, no
  `OpBitwiseAnd` — vanilla is 4× `%uint_28`.
- New GOTCHAS: `cp -p` on materialized swaps; `NoOpaqueKHR` means the geometry
  is opaque; never generalise a cull mask from one sampled module; a
  launch-gated selector must show what is *running*; never land two independent
  visual features between two observations.
