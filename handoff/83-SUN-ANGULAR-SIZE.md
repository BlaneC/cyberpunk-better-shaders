# 83 — Sun angular diameter (`43` M3): the engine already ships the knob

Written 2026-09-01. **Audit only — nothing built, nothing installed, nothing
launched.** GOTCHAS 8 branch: the engine exposes this as a live CVar, so this
document is a *recipe*, not a splice design. The offline shader census that
the task reserved for the no-CVar case was **not run and is not needed**.

**AMENDED 2026-09-01 09:00, same day, still zero launches.** Two changes, both
from reading Ultra Plus's cron instead of trusting this document's first pass:
(1) §4's "overwrites every 60 s" was **wrong** — corrected throughout, see §4.1;
(2) Ultra Plus has now been **modified on this machine** to write 0.53, which
makes most of §5 obsolete. See §9. Everything else stands.

**SECOND AMENDMENT, 2026-09-01 ~09:20 — this knob is ON SCREEN.** 0.53 was
served and the user's verdict is *"0.53 looks better"*. First look this
document has ever had. An attempted 2.0 run the same session was **invalid**
and proved nothing. Both recorded in §10, with what they do and do not
license.

## 0. TL;DR

- The CVar is **`RayTracing/SunAngularSize`**, float, degrees. Single
  occurrence in the shipping exe.
- **`43` M3 is stale.** It says "`pt_engine.lua` lists no sun-disk CVar".
  It has listed one since `44` (`pt_engine.lua:136`), it is deployed, and the
  repo copy is byte-identical to the game's copy. M3 is not a build item; it
  is an **unrun A/B** (`45` E8, 0 launches).
- **Stock is 0.5°, which is already within 6% of the real sun's 0.53°.** The
  physically-correct edit is therefore *tiny* — and the interesting finding is
  the opposite one: up to 2026-09-01 the game was running a sun **1.5×–2.4×
  too small**, because Ultra Plus overwrote it with 0.225–0.35 — **on every
  in-game hour change**, not every 60 s (§4.1). As of §9 it writes 0.53.
- So M3's deliverable is not "make the sun bigger than stock". It is
  **"stop another mod shrinking it, and put the panel in charge"**.
- The panel's group attribution for this key is **probably wrong in order**:
  it tries `RayTracing/Diffuse` and `RayTracing/Reflection` before the
  top-level `RayTracing` group that the evidence points at. One-line fix in
  §5; not applied here (needs `make install` + a launch, both out of scope).

## 1. The exe audit (`16`'s method, `20`'s scope)

`bin/x64/Cyberpunk2077.exe`, 59,945,608 B, mtime 2026-08-20 22:49,
`md5 9add9693…`. `strings -n 4` → 776,879 lines.

Generous, case-insensitive sweep for the feature:

| pattern | hits | what they are |
|---|---|---|
| `AngularSize` | **1** | **`SunAngularSize`** — the target |
| `angular` | 52 | 51 are PhysX / vehicle / locomotion angular velocity |
| `SunSize` | 1 | `m_sunSize` — env/sky resource field, see §6 |
| `Softness` | 5 | `m_softness`, `m_shadowSoftnessMode`, `ELightShadowSoftnessMode`, `m_backReflectionCutoffSoftness`, `softness` — RTTI fields, **not CVars**, and local-light not sun |
| `ShadowAngle` | 4 | `m_shadowAngle`, `shadowAngle`, `enableShadowAngleControl`, `Components/ShadowAngleAreaLightShape` — per-light-component RTTI |
| `ShadowRadius` | 1 | `m_shadowRadius` — same family |
| `penumbra` / `AngularDiameter` / `SunAngle` / `SunDisk` / `SunDisc` / `LightAngle` / `DiskRadius` / `SolarAngle` / `SunRadius` / `SoftShadow` / `SolidAngle` | **0** | — |

Exact single-occurrence check (`grep -cx`, `16` §1's test):

```
SunAngularSize            1
SunVisibility             1
SunScatteringScale        1
LightSize                 1
RayTracing                1
RayTracing/LocalShadow    1
RayTracing/Diffuse        1
RayTracing/Reflection     1
```

`SunAngularSize` sits inside one contiguous RT-CVar key run alongside
`SunVisibility`, `SunScatteringScale`, `RoughnessThreshold`,
`EnableImportanceSampling`, `EmittanceScale`, `SkyRadianceScale` and the
group-path strings `RayTracing/LocalLight`, `RayTracing/Reflection`,
`RayTracing/Diffuse`. The key table deduplicates, so **layout alone cannot
name the owning group** — this is the same inference trap `pt_engine.lua`'s
header already warns about. §3 settles it from a second source.

## 2. What the knob does, and its units

Larger value → larger sun disc → **softer shadow terminators and wider
specular highlights**. Direction is confirmed independently by Ultra Plus's
`Engine.ApplySunDiffuse()`, whose stated intent is "sharp at midday to
diffuse at dawn and dusk" and whose table was 0.225 at midday, 0.35 at
dawn/dusk (`UltraPlus/lib/Variables.lua:111`). **That table has since been
flattened to 0.53 by §9**; the stock curve is preserved in a comment at the
same site, and the direction argument is unaffected — it rests on the mod
author's stated intent, not on the values still being there.

**Units: degrees of angular *diameter*, at ~90% confidence.** The evidence is
circumstantial and stated as such (GOTCHAS 9):

- stock 0.5 vs the real sun's 0.53° diameter — a 6% match is not a
  coincidence for a renderer that models a physical sky;
- if it were *radius*, stock would be a 1.0°-wide sun, ~1.9× physical, which
  is not a default an engine picks;
- if it were radians, stock would be a 28.6° sun and outdoor shadows would
  have no terminator at all.

*Falsifier, one launch, free:* set 0.5 → 1.06 and photograph the same hard
shadow edge. Penumbra width should scale **linearly** and land at exactly 2×.
If it lands at 4× or at 1×, the unit reading is wrong and this section is
void. Run it before quoting "0.53 is physically correct" anywhere.

## 3. Which group owns it — `RayTracing`, top level

Ultra Plus is installed in this game directory and is the second source:

- `UltraPlus/lib/Engine.lua:288` — `Cyberpunk.SetOption('RayTracing',
  'SunAngularSize', …)`, i.e. the **top-level** group, explicit in code.
- `UltraPlus/config/debug.ini:397` — `RayTracing/SunAngularSize = 0.5 ;
  name = Sun Shadow Angular | tooltip = Adjusts sharpness of shadows cast by
  sun`.
- `UltraPlus/config/modes.ini` — `RayTracing/SunAngularSize` in every mode
  block (`RT`, `PT16`, `PT20`, `PT21`, `Next`), never group-qualified.
- The same file *does* group-qualify its neighbours where they are qualified:
  `RayTracing/Diffuse/AdaptiveSampling`,
  `RayTracing/Reflection/AdaptiveSampling`,
  `RayTracing/Reference/EnableRIS`. So the flat form is a choice, not sloppiness.

**Cross-check that the ini values are engine defaults, not Ultra Plus taste:**
`debug.ini:400` gives `RayTracing/SunScatteringScale = 10.0`, and this
project's own live snapshot (`pt_engine.txt`, written by CET from the engine)
reads `SunScatteringScale=10.0000`. Two independent reads agree, so
`debug.ini` is a defaults list and **`SunAngularSize` stock = 0.5** carries the
same weight.

`SunVisibility` (stock 1.0 from our snapshot) is not in `debug.ini`; attribute
it to the same top-level group by adjacency only — inferred, unconfirmed.

## 4. The state this machine is actually in

`.../mods/CallistoSSS/pt_engine.txt`:

```
enabled=0
…
SunAngularSize=0.2500
SunVisibility=1.0000
SunScatteringScale=10.0000
```

- `enabled=0` → **the Callisto panel is not driving anything**. Its 2 s
  re-assert (`pt_engine.lua M.onUpdate`) is inert.
- Ultra Plus's 60 s cron (`UltraPlus/init.lua:427`) calls `ApplySunDiffuse()`
  **ungated by any setting** (only by `_paused`), and `UltraPlusConfig.ini`
  shows it live (`internal.mode = PT21`, file mtime 2026-09-01 01:17).
  **The cron ticks every 60 s but only *writes* on an in-game hour change —
  §4.1.**
- Therefore the live sun angular size in every session up to 2026-09-01 has
  been **0.225–0.35 depending on the in-game hour** — 42%–70% of stock, i.e. a
  sun disc between 1.5× and 2.4× smaller than the real one. Every outdoor face
  screenshot in `46`/`72`/`74`/`78` was taken under it. That conclusion is
  unchanged by §4.1: a per-hour write still covers every hour.
- **Trap:** Callisto's `vanilla[]` snapshot is taken at CET register time and
  it caught **0.25**, not 0.5. So *Restore engine defaults* restores Ultra
  Plus's value, not the engine's. Do not use that button as the A/B control
  for this knob; write 0.5 explicitly.

Per the A/B-settings-sync rule, any launch quoting this knob must **state
Ultra Plus's mode and whether Callisto's PT panel is on**, before the launch.

## 4.1 Correction: the cron writes per in-game *hour*, not every 60 s

This document's first pass said Ultra Plus "overwrites it every 60 s". That is
wrong, and it is the reason §5 concluded the panel takeover was compulsory.
`UltraPlus/lib/Engine.lua:273`:

```lua
function Engine.ApplySunDiffuse()
    local currentHour = Cyberpunk.GetHour()
    local hourUnchanged = currentHour == Var.sunAngularSizes.previousHour
    if hourUnchanged then return end            -- Engine.lua:277
    …
    Cyberpunk.SetOption('RayTracing', 'SunAngularSize', Var.sunAngularSizes[currentHour])
    Var.sunAngularSizes.previousHour = currentHour
```

The 60 s `Cron.Every` only *checks*. The write is gated on the hour changing,
so:

- A manual write (console, or the panel) **survives until the next in-game
  hour boundary** — a couple of real minutes at default time scale, not 60 s.
- With the world clock frozen — photo mode — the hour cannot roll, so a manual
  write should hold for the whole session. *Predicted, not measured:* it
  assumes `Cyberpunk.GetHour()` is frozen in photo mode too. One launch settles
  it; nothing in this document depends on it.
- `previousHour` initialises to `-1` (`Variables.lua`), which no real hour can
  equal, so the first cron tick after load always writes. There is a **window
  of up to 60 s at the mode's `modes.ini` value** at every launch. §9 closes it.

Consequence for §5: **the takeover switch is not the only way to hold a value,
and for a static photo-mode A/B it is not needed at all.** It remains required
for the *panel slider*, which is separately gated — see §5(a) step 3.

## 5. The recipe

**Physically correct: `RayTracing/SunAngularSize = 0.53`.** Stock 0.5 is
already 94% of that; the *visible* change comes from displacing Ultra Plus's
0.225–0.35, which is a 1.5×–2.4× widening of every outdoor penumbra.

**Superseded by §9 for the 0.53 case** — Ultra Plus now writes 0.53 itself, so
no route below is needed to *reach* physical. They stay here because the E8
ladder still needs 1.06 and 2.0, which nothing writes for you.

Three routes, in order of preference.

**(a) The CET panel — live, no relaunch, and it wins the fight.**
`Callisto SSS → Path-tracer sampling (engine, applies live)`:
1. Read the header: `N/15 CVars found`.
2. Hover *Sun angular size (deg)* and read the tooltip's first line — it
   prints the path that actually answered. **It must say `RayTracing/SunAngularSize`.**
   If it says `RayTracing/Diffuse/…`, the panel resolved a dead sibling and
   every drag is a no-op — apply the fix in (d) before believing anything.
3. Turn **Take over engine PT sampling** ON. Two independent reasons, and the
   first is the one that bites: the slider callback is
   `if enabled then setRaw(d, v) end` (`pt_engine.lua:407`) — **with the switch
   off the slider is inert**, it only rewrites `pt_engine.txt`. Second, the 2 s
   re-assert outranks Ultra Plus's per-hour write, which is what holds the
   value while the world clock runs. (It is *not* "the only way to hold" it —
   §4.1.)
   **Cost, and it is not free:** `M.apply()` loops **all 15 DEFS** and writes
   every one from `pt_engine.txt` every 2 s — currently `RayNumber=1`,
   `BounceNumber=0`, `SampleNumber=12`, `AdaptiveSampling=0`,
   `AmbientOcclusionRayNumber=0`, `EnableReferenceSER=1`, … So the switch also
   freezes 14 other PT CVars at whatever the file holds and takes them off
   Ultra Plus. (`AmbientOcclusionRayNumber=0` is below the DEF's own `min = 1`
   — a tell that these are captured engine reads, not chosen values; `apply()`
   writes `vals` raw, unclamped.) **Discipline: flip takeover ON *before* the
   control shot**, then move only the sun slider. The other 14 are then
   identical in both arms and cancel.
4. Set the slider. Step is `(5.0−0.0)/200 = 0.025`, so the reachable points
   near physical are **0.525** and **0.550**; exact 0.53 needs route (b).

**(b) Exact value, next launch.** Edit
`<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/pt_engine.txt`
with the game closed:

```
enabled=1
SunAngularSize=0.5300
```

`load()` runs at register and `if enabled then M.apply() end` applies it at
launch (`pt_engine.lua:311`). Note CET rewrites the file with `%.4f` on the
next knob touch, so treat this as a launch-time seed, not a lock.

**(c) One-shot from the CET console.** Per §4.1 this survives until the next
in-game hour boundary, and should survive indefinitely in photo mode — so for
a *static* A/B this is the cleanest route on the page: no takeover, and none of
step (a3)'s 14-CVar side effect:

```lua
GameOptions.SetFloat("RayTracing", "SunAngularSize", 0.53)
print(GameOptions.Get("RayTracing", "SunAngularSize"))
```

**(d) The one-line source fix — proposed, NOT applied.** `pt_engine.lua:136`
currently reads

```lua
  { key = "SunAngularSize", paths = { DIFF, REFL, RT, REF }, kind = "float",
```

and the resolver takes the **first** path that answers. §3's evidence says the
owner is `RT`, so `DIFF`/`REFL` are ahead of it for no reason. Change to

```lua
  { key = "SunAngularSize", paths = { RT, DIFF, REFL, REF }, kind = "float",
```

and the same for `SunVisibility` (139) and `SunScatteringScale` (142).
Not applied in this pass: it is a deployed-file change and would need
`make install` plus a launch to verify, both outside this task's scope.
It is cosmetic *if* `DIFF` correctly answers `nil` — but that is exactly the
assumption GOTCHAS 10 says not to make, and the tooltip in step (a2) is the
cheap check that settles it.

**Suggested ladder for `45` E8** (S1, same save, same hour, Ultra Plus mode
stated): `0.25` (today's de-facto) → `0.53` (physical) → `1.06` (2×, doubles
as the unit falsifier) → `2.0`. Expect softer terminators on the face and
wider eye/skin highlights; this composes with the `skinspec`/roughness rungs,
so freeze those.

## 6. Nearby surfaces, and what they are not

- **`RayTracing/LocalShadow/LightSize`** — the local-light counterpart
  (`LightSize` is adjacent to the `RayTracing/LocalShadow` group string). This
  is the knob for interior/neon penumbra softness and is **not** covered by
  anything in this repo. Cheapest untouched engine-side realism knob found in
  this audit; worth its own rung.
- **`m_sunSize`** — sits in the env/sky RTTI block next to `m_sunColor`,
  `m_moonColor`, `m_latitude`, `m_longitude`, `m_sunRotationOffset`,
  `Coordinates`, `ETimeOfYearSeason`. That is the **sky dome's drawn sun
  disc**, a `worldEnvironment` resource field, not a CVar and not the shadow
  cone. Changing it would move the painted sun and not the penumbra. Listed so
  nobody re-finds it and gets excited.
- **`/graphics/raytracing/RayTracedSunShadows`** — the video-options toggle.
  On/off, no size.
- `m_shadowAngle` / `m_shadowRadius` / `m_softness` / `m_shadowSoftnessMode` /
  `enableShadowAngleControl` — per-light-component RTTI properties, authored
  per light in the world, not reachable as CVars.

## 7. What was *not* done, deliberately

No shader census of `rgs_shadow_main` (13 modules) or the reference raygens.
The task reserved that for the no-CVar branch and the CVar exists. Recorded so
the next reader does not assume it was done and failed: **the question of
whether the sun is sampled as a cone in the shadow raygen is still open**, and
the CVar's existence is not proof that it reaches the *path-traced* shadow
path rather than only the RTXDI/RT-only one. §5's `0.25 → 1.06` sweep answers
that empirically in one launch and is strictly cheaper than the disassembly.

The shadow family is where `sctrl` died (`29` §B6); nothing here proposes
touching it.

## 8. Files touched

- **First pass (audit):** `handoff/83-SUN-ANGULAR-SIZE.md` (this file, new).
  Nothing else was modified. Scratch strings dump under the session scratchpad.
- **Amendment (§9):** two files inside **Ultra Plus**, in the game directory —
  outside this repo, outside `make install`. Listed in §9.

## 9. Ultra Plus modified to write 0.53 (2026-09-01 09:00)

Done at the user's request, replacing §5 for the physical value: rather than
fight the cron, the cron now serves the right number. **Not verified on screen
— zero launches. Offline edits only.**

Ultra Plus writes `SunAngularSize` from exactly two places (`grep -rn` over the
whole mod: `*.lua` + `*.ini`). Both are patched:

| file | site | before | after |
|---|---|---|---|
| `UltraPlus/lib/Variables.lua` | `sunAngularSizes[0..23]` | 0.225–0.35 curve | **all 24 hours `'0.53'`** |
| `UltraPlus/config/modes.ini` | `:284`, `[PT21]` block | `0.25` | **`0.53`** |

- The **`Variables.lua`** edit is the one that matters: `Engine.lua:288` reads
  that table, so the per-hour cron write is now 0.53 at every hour. The stock
  curve is preserved verbatim in a comment at the same site — reversion is one
  edit, or restore `Variables.lua.bak_callisto_20260901-090058`.
- The **`modes.ini`** edit only closes §4.1's up-to-60 s window at launch,
  where `Config.SetMode()` applies the mode block before the first cron tick.
  Only `[PT21]` was patched, because `UltraPlusConfig.ini` reads
  `internal.mode = PT21`. **The other six blocks still say 0.25** (`[Vanilla]`
  says 0.5) — switching modes reintroduces the launch window, though the cron
  still corrects to 0.53 within 60 s. Backup:
  `modes.ini.bak_callisto_20260901-090058`.
- Verified offline: `luac -p Variables.lua` OK; `modes.ini` diff vs backup is
  the single line 284 (the file is CRLF — preserved).
- **Consequences.** The panel takeover is no longer needed to reach or hold
  0.53, which removes §5(a3)'s 14-CVar confound from the default path. The
  time-of-day *variation* in sun softness is gone — that was Ultra Plus taste,
  not physics, but if a dusk shot later reads too hard, this is why.
- **Fragility:** an Ultra Plus update overwrites both files silently. If sun
  size ever reads wrong again, re-check these two sites first.
- **Still unrun:** the E8 ladder and, importantly, the **unit falsifier** —
  §2's "degrees of diameter" reading is still 90%-confidence circumstantial,
  and §7's question of whether the CVar reaches the path-traced shadow path at
  all is still open. 0.53 is now the standing value on faith. The `0.53 → 1.06`
  penumbra-doubling check is one launch and settles both.

## 10. First on-screen result, and one invalidated run (2026-09-01 09:00–09:20)

### 10.1 The 2.0 run: INVALID, no information

Reconstructed from `cyber_engine_tweaks/scripting.log`, not from a capture:

```
09:07:09  Mod UltraPlus loaded!            <- §9's patched table live, all hours 0.53
09:09:59  > SetFloat("RayTracing","SunAngularSize", 2.0)
09:09:59  2.000000                          <- the write LANDED, readback confirms
09:10:17  [GameSession] event = "End"
09:10:20  [GameSession] event = "Load"      <- save reloaded AFTER the set
09:10:30  PlayerReady                       <- scene observed here
```

The value was set and then the save was reloaded. Reported result: no visible
difference — **correct, and expected, because 2.0 was not on screen.** Two
clobbers are available and the log cannot separate them: the engine
re-applying graphics settings on session load, or §9's own cron (the reload
moves the in-game hour, `previousHour` survives in module state, so
`hourUnchanged` goes false and 0.53 is written within 60 s). Note the second
one means **§9's patch actively ate this test.**

*This is the `A/B settings sync` rule failing exactly as written: the state was
set before the observation but not held through it, and nobody checked.* The
cheap guard is a **readback immediately after the shot**, not before it.

**Nothing about §7 or §2 can be concluded from this run.** It is recorded only
so it is not re-counted as evidence that the CVar is dead.

### 10.2 The 0.53 result: LOOK-CONFIRMED, uncontrolled

Sessions: UltraPlus loaded 08:48:07 with the **stock** 0.225–0.35 curve, then
09:02:31 and 09:07:09 with §9's flattened **0.53**. Same afternoon, same save.
Verdict, user's own eye: **"0.53 looks better."**

- **Settings were not stated in advance** (mode presumed PT21 from
  `UltraPlusConfig.ini`; scene, hour and weather unrecorded). Per the project
  rule this is a *look* result and **no radiometric claim rides on it** — same
  standing as the A6/A7 kernel and bleed verdicts in `CURRENT.md`.
- **It is nonetheless the first evidence that the CVar reaches the screen at
  all.** If `SunAngularSize` were inert under PT21 — §7's live doubt — then
  0.53 and 0.225–0.35 would be indistinguishable. They were not. Weak, because
  uncontrolled; but it points the opposite way from §7's worry.
- **0.53 is now the standing default**, served by §9 with no user action.

### 10.3 What is still open

The **units falsifier is untouched** and is now the highest-value cheap run in
this document. §2's "degrees of angular diameter" is 90%-confidence
circumstantial, and *the entire claim that 0.53 is physically correct rests on
it*. 10.2 says the knob does something and that 0.53 is likeable; it says
nothing about what 0.53 *is*.

Protocol, corrected for 10.1's failure mode:

1. Load the save **first**; reach the spot; do not reload again.
2. Subject: a **long cast shadow on flat ground** (pole/railing, tip several
   metres from the caster). Penumbra width scales with caster distance, so a
   contact shadow barely moves. A face terminator is among the worst subjects.
3. Photo mode — per §4.1 the clock freezes, so the cron cannot fire mid-test.
4. Console `0.25` → shot. Console `2.0` → shot.
5. **Readback after each shot**, not before: `print(GameOptions.Get("RayTracing","SunAngularSize"))`.

Penumbra should scale linearly: 8× the value, 8× the tip softness. Anything
else voids §2. A confirmed-live null result answers §7 negative for PT21, and
the follow-up is the same sweep in Ultra Plus's `RT` mode to see whether it is
PT-specific or dead everywhere.

### 10.4 Bonus: §5(d)'s path-order worry is CLOSED

Across all 10 panel registrations in `scripting.log`:

```
Failed to find game option 'RayTracing/Diffuse/SunAngularSize'!
Failed to find game option 'RayTracing/Reflection/SunAngularSize'!
```

Both dead siblings return nil on every register, so the resolver falls through
to top-level `RayTracing`, which answers. §3's attribution is confirmed
empirically, **the proposed `pt_engine.lua:136` reorder is unnecessary** and
should not be applied. Only `SkipSamples` and `TileSize` fail to resolve at
all. §5(d) is closed, no code change.
