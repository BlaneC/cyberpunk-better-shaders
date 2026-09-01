# 82 — The denoiser panel is now enableable (2026-09-01)

> **NOTHING HERE HAS BEEN ON SCREEN.** No launch, no `make install`, no
> commit. This document describes a config file and a Makefile line. Per
> `GOTCHAS`: built and installed are not *working* — only an on-screen A/B is,
> and none has been run. Every claim below about what a slider will do is a
> prediction from `detail_engine.lua`'s own header, not an observation.

## 0. Required game settings — set these BEFORE you launch

State them now so nobody infers them from a capture afterwards.

### 0.1 STOP — Ray Reconstruction is ON right now, and it makes this panel inert

Read live at 2026-09-01, file mtime `Sep 1 01:42` (i.e. *after* `79`'s
2026-08-31 22:41 read), from the Proton prefix:

```
/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/compatdata/1091500/pfx/drive_c/users/steamuser/AppData/Local/CD Projekt Red/Cyberpunk 2077/UserSettings.json
```

| setting | `79` §1 (2026-08-31 22:41) | **live now** | stock |
|---|---|---|---|
| **`DLSS_D`** (Ray Reconstruction) | `false` | **`true`** ← moved | `false` |
| `DLSS` | `Balanced` | **`Performance`** ← moved | — |
| `DLSS_NewSharpness` | `0.3000000119` | **`0.2000000029`** ← moved | `0.0` |
| `DLSS_BackendPreset` | `Transformer` | `Transformer` | — |
| `RayTracedPathTracing` | `true` | `true` | `false` |

**Three settings have moved since the baseline `79` documented, and one of
them is fatal to this test.** With `DLSS_D: true`, DLSS Ray Reconstruction
*replaces* NRD wholesale — every one of the 22 knobs in this panel is bypassed,
not broken, bypassed (`detail_engine.lua:21-30`). Launching in the current
state and reporting "the sliders did nothing" would be a null about Ray
Reconstruction, not about the denoiser.

This is `47` §5's L4a failure exactly: an arm published as RR-off whose
`UserSettings.json` read `DLSS_D: true` afterwards, which turned a result into
a third null. It has now happened twice.

**Turn Ray Reconstruction OFF in the graphics menu before launching**, and
decide deliberately whether to restore `DLSS: Balanced` — `Performance` at
1440p is a *bigger* face-sharpness variable than anything in this panel
(`43` §2 0d), so leaving it at Performance while judging a denoiser radius is
two variables in one launch.

### 0.2 The full required set

| setting | required value | why |
|---|---|---|
| **`DLSS_D` (Ray Reconstruction)** | **OFF / `false`** | **Load-bearing, and currently wrong.** See §0.1. Also the config every approved look was judged under (`79` §1). |
| `RayTracedPathTracing` | `true` | the standing config; currently correct |
| `DLSS` preset | **restore `Balanced`** | to match the `79` baseline. Changing the preset is its own experiment (`43` §2 0d) and must not ride along |
| `DLSS_NewSharpness` | leave wherever you set it, but **record it** | non-default either way (stock `0.0`). Do **not** also raise the panel's `DLSS_Sharpness` — that stacks two sharpeners |
| `brdf_params.txt` | unchanged (`skinspec=gi-50b-bleed-oil-sheen-deep-clothhi`, `kernel=spectral`, `refract=eta15`, `ser=class`) | this is a denoiser test on top of the standing rung, not a rung test |

Re-read the file before **and** after the launch block — reading it only
afterwards is how L4a got published:

```bash
grep -A3 '"name": "DLSS_D",' "/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/compatdata/1091500/pfx/drive_c/users/steamuser/AppData/Local/CD Projekt Red/Cyberpunk 2077/UserSettings.json"
```

(Note there is a second, stale `UserSettings.json` at
`~/.wine/drive_c/users/blane/…` with an Aug 21 mtime. It reads `DLSS_D: false`
and it is **not** the file the game uses. Do not grep that one.)

## 1. What was wrong

`detail_engine.txt` was absent from the live install, so `detail_engine.lua`'s
`load()` (`:242`) hit `if not f then return end` on every launch, `enabled`
stayed `false`, `M.apply()` returned immediately, and all 22 denoiser knobs sat
at whatever the engine had. The panel has existed since `33` and has never
done anything.

**It is not a regression and it is not a broken install target.** The four
engine panels each *write their own* `<name>_engine.txt` from `M.save()`, and
`M.save()` is only ever reached from a widget callback. Nothing in the repo,
in `make install`, or in `release/install.sh` has ever shipped one of these
files — grep for `engine.txt` in all three and you get nothing. The live
install proves the mechanism:

```
hair_engine.txt    2062 B   Aug 31 13:24     <- panel touched
pt_engine.txt       338 B   Aug 31 21:34     <- panel touched
skin_engine.txt    1105 B   Aug 31 21:07     <- panel touched
detail_engine.txt  ABSENT                    <- panel never opened
```

So the root cause is: **the file is runtime state, and no one has ever flipped
the panel's master switch.** Strictly, the panel was always one CET click away
from working. What was missing was the click, the documented stock values, and
anything that would make the state survive a fresh install.

Live install location (from `Makefile:14`, confirmed on disk):

```
/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/
```

## 2. What changed

**`detail_engine.txt` (new, repo root).** The seed. One active line —
`enabled=1` — plus all 22 knobs present as *commented* lines carrying stock
value, resolved CVar path, direction of travel and a suggested ladder.

**`Makefile`.** New `CET_LIVE` var; `install:` now seeds the file
**copy-if-absent**. It is deliberately kept out of `release/game/` so the
target's `cp -a release/game/.` can never reach it — these files are player
state in the same sense `brdf_params.txt` is, and clobbering one on every
deploy would throw away tuning mid-session. Delete the live file to re-seed.

### 2.1 Why every knob line is commented out

This is the part to argue with if you are going to argue with anything.

`detail_engine.lua:293-296` seeds every knob from the value the **engine**
reported at session start, and `load()` overrides only the keys the file names.
So a commented knob shows the live engine value and the 2 s re-assert writes
that same value back — an exact no-op. An *uncommented* knob **forces** its
number into the engine.

The stock numbers in the file are `dflt` from the lua's `DEFS` table.
**Nobody has ever read the running game's values back.** `79` §7's table is
labelled "live value" but that column *is* this same `DEFS` table, not a live
read, and the panel's found-count has never been read off the console either —
`CallistoSSS.log` in the live install is 0 bytes. Uncommenting a line whose
"stock" is an unverified guess is precisely `GOTCHAS`' *"One knob, two
defaults, in two files that never see each other"*: the UI reads stock while
the engine has been moved off it.

So the seed enables the panel and asserts nothing. Verified offline by
replaying the lua's exact `load()` pattern against the file: 46 lines contain
an `=`, **1** is consumed, `enabled=true`, zero knob overrides. Uncommenting
`RB_D_SpecPrepass` then produces exactly one override — also verified.

### 2.2 Three footguns in the file format, because the parser is unforgiving

`line:match("^([^=]+)=(.+)$")` at `:248`:

1. **No leading whitespace.** The key is everything before the first `=`,
   whitespace included, so `  RB_D_SpecPrepass=10` has key `"  RB_D_SpecPrepass"`,
   matches nothing, and is **silently ignored**. Uncomment by deleting `"# "`,
   never by replacing it with spaces.
2. **No trailing comments.** The value is everything after the first `=`, so
   `RB_D_SpecPrepass=10  # sharper` gives `tonumber(nil)` and the float knob
   goes **dead** (int knobs fall back to the lua default, bools read false).
3. **The file is rewritten, comments and all.** Every widget callback calls
   `M.save()`, which truncates and rewrites it as bare `key=value`. The first
   slider you move in CET deletes the documentation you are reading. **The
   repo copy is the reference; the live copy is state.** Once the panel has
   been used, the `cmp` in §3 will fail *by design*.

## 3. Exact commands

Deploy (from the repo root). **The game runs copies — this is mandatory
before reading any launch**:

```bash
cd "/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS"
make install
```

Expect the line `detail_engine.txt: SEEDED -- denoiser panel is now enabled (82)`.
If it says `already present, left alone`, the file exists and the seed was
correctly skipped.

Verify, before the first launch and before touching any slider:

```bash
cmp "/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS/detail_engine.lua" "/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/detail_engine.lua" && echo lua-in-sync
cmp "/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS/detail_engine.txt" "/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/detail_engine.txt" && echo txt-seeded
cmp "/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS/init.lua" "/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/init.lua" && echo cet-in-sync
```

`make install` was **not** run by the author (parallel agents were writing the
tree; a `cp -a` mid-write is how you get a half-deployed install).

## 4. In-game, in order

The panel is `Mods → CallistoSSS → Detail / denoiser (engine, applies live)`.
No relaunch is needed between steps — these are live CVars, unlike every
shader rung this project has ever tested.

**Step 0 — read the subcategory header before anything else.** It says
`… -- N/22 CVars found`. That number has never been recorded. **If it is not
22, say which knobs are missing before drawing any conclusion** — a knob whose
group attribution is wrong is a dead slider that looks identical to a slider
that does not matter, and its own tooltip will say `NOT FOUND`.

**Step 1 — click "Dump denoiser CVars to console".** It prints, per knob, the
resolved path and the **live vanilla value**. This is the missing measurement:
it either confirms `79` §7's stock table or corrects it. Paste it into this
doc. Everything after this is cheaper once it is done.

**Step 2 — click "Sharpest possible (diagnostic)"** (`detail_engine.lua:208`).
One click, the ceiling: `DenoisingRadius`, `RB_D_DiffusePrepass` and
`RB_D_SpecPrepass` to 0, atrous to 1, stabilization and history-fix to 0. It
answers *"is the denoiser what is softening faces?"* yes/no in one click,
before an evening goes into sliders. **It is a diagnostic, not a look** —
expect noise and shimmer, worst on a face in motion. Then
"Restore engine defaults" and walk *back down* from the ceiling.

**Step 3 — the one slider to move first: `RB_D_SpecPrepass`.**
ReBLUR/Direct `SpecularPrepassBlurRadius`, stock **20**, `detail_engine.lua:98`.

```
20 (stock)  ->  10  ->  5  ->  0
```

Why this one and not any of the other 21:

- It is a **specular** prepass, and the complaint is highlight softness on
  faces. The diffuse prepass costs noise far faster on skin.
- `detail_engine.lua:94` calls it *"an unconditional spatial average applied to
  the radiance before any edge-aware filtering gets a say"* — it is the one
  stage that blurs without asking about normals, depth or roughness.
- It is **`79`'s M1 mechanism on a runtime slider.** M1 was "the denoiser
  filters at vanilla-roughness radius while the mod has tightened the lobe",
  and it was falsified as *the* explanation for soft faces (`79` §3) but its
  premise survives as a real second-order over-blur. This slider tests the
  surviving premise directly, at zero build and zero launch cost, where M1's
  own fix routes are both blocked (`79` §6).

Watch a lit cheek or nose highlight, not the whole face. Stop one rung above
wherever the specular starts crawling frame-to-frame.

**Step 4 — only then**, `DenoisingRadius` 30 → 20 → 10 (`:87`), and
`RB_D_LobeAngle` 0.15 → 0.08 (`:108`, the literally roughness-guided one). If
the complaint is specifically *bounce* light being smoothed, the ceiling is
`SHARC_SceneScale` / `SHARC_Downscale`, not any blur radius — bounce radiance
is read out of a world-space hash and the cell size caps its detail however
many rays are spent. Those two cost performance; the rest do not.

## 5. What would make this "working"

Nothing here counts until an A/B says so, and this panel makes a clean one
unusually easy — the knobs are live, so a single launch can carry every rung
with no cache eviction and no reserve about what was served.

Pre-register the outcomes, per `55` §4:

- **Step 2's ceiling visibly sharpens the face** → the denoiser is a real term
  in "faces read soft", and Step 3's ladder is worth an evening.
- **Step 2's ceiling changes nothing** → check `DLSS_D` **first**, before
  concluding anything: it is `true` as of this writing (§0.1) and it has
  caught this project out twice. Then the found-count. Only if both are clean
  is it a real null, and then `79` §7(b) — the DLSS preset test, still unrun —
  is next. **Publish that null.** A null here is worth more than the six
  launches of numbers `46` §11 had to retract.
- **Sharpens but only with unacceptable shimmer** → that is the answer too:
  the detail is being traded for temporal stability, and `MaxAccum` /
  `RB_D_Stabilization` are where the trade is priced.

Take a pinned-frame control. `81` §10's honest caveat — "look-call, no
pinned-frame control" — applies double here, because a denoiser radius change
is exactly the kind of edit `46` §11.4's pore-scale relaunch floor
(+58.5% fine-texture energy between two **byte-identical** launches) will
happily impersonate.

## 6. State

- `detail_engine.txt` — new, repo root, seed. Not in `release/game/`.
- `Makefile` — `CET_LIVE` var; `install:` seeds copy-if-absent.
- **Recorded, and it is the most actionable thing in this document:** the live
  `UserSettings.json` has drifted off `79`'s baseline on three axes since
  2026-08-31 22:41 — `DLSS_D` `false`→`true`, `DLSS` `Balanced`→`Performance`,
  `DLSS_NewSharpness` `0.3`→`0.2` (§0.1). Any launch made from the current
  state tests Ray Reconstruction, not this panel.
- No shader, patcher, build script, rung, `init.lua` or `detail_engine.lua`
  change. No commit. No `make install`. No launch.
- **Not indexed.** `handoff/README.md` and `CURRENT.md` were left untouched
  on purpose — parallel agents were editing the tree and both files are
  append-shaped conflict magnets. Add the row for `82` by hand.
- The seed's stock numbers are duplicated from `detail_engine.lua`'s `DEFS`
  `dflt` fields. They are inert while commented, so divergence is doc rot
  rather than a live bug — but it is still two files that never see each
  other. `grep -n 'dflt' detail_engine.lua` is the one-command check.
