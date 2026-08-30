# 49 — The eyeball ladder: `real` vs `real-gloss` vs `off`

`CURRENT.md` "Still unlaunched" item 2, run 2026-08-30 evening. **The eye is
the instrument** (`47` §11). No radiometry in this document: the L1–L8 block
established that region choice moves the metric further than any knob does
(`46` §16.2), so a number here would only launder a preference into a
finding. Verdicts below are the user's, in the user's words where possible.

Procedure: `45` §0–§2 (serve verification before looking; one variable per
launch; same save, same time, same weather, same camera). `45` §3's E-queue
is superseded — these three rungs replace E3–E7.

## 0. Configuration

Frozen for the whole block, at the shipping default:

```
tier=1 kernel=detail skin=on shadowcull=on shadowset=full-shadow
ptreg=on ptclamp=on ptbounce=on ptrefl=on ptmsggx=on ser=off
```

The single variable is `skinspec`. **Caveat on the first rung:** the previous
launch (L8, `46` §18) ran `ptbounce=off`, so R1 moves *two* keys relative to
the last thing on screen — `ptbounce` off→on and `skinspec` off→real. Within
this ladder that is harmless: all three rungs, control included, carry
`ptbounce=on`, so the only difference *between the rows compared* is
`skinspec`. R3 (`off`) is the control and it is shot in this same block, not
reused from an earlier session — `46` §13's regime break is why.

**Graphics settings — frozen, not touched at any point in this block** (read
from `UserSettings.json` at 16:57, before R1):

| key | value | why it is what it is |
|---|---|---|
| `DLSS_D` (Ray Reconstruction) | **true — ON** | RR stays on for R1–R3. It is the configuration the game is actually played in, so the direction decision should be made there; and RR-off is `CURRENT.md` item 3's *deliberate* variable, so spending it here would confound two things at once. |
| `RayTracedPathTracing` | true | PT is the regime the whole mod lives in. |
| `RayTracedPathTracingForPhotoMode` | true | captures are PT, not the raster fallback. |
| `DLSS` | `Balanced` | upscaler quality; any change is a regime change. |
| `Resolution` | 2560x1440 | — |
| `RayTracedLighting` | `Psycho` | — |

`46` §13's regime break was an unlogged mid-session settings change, and two
earlier RR-off attempts silently ran with RR **on**. Hence: no graphics menu
during the block.

### 0.1 Settings are pinned by timestamp

**The game writes `UserSettings.json` on Apply, while it is running.** Proven
at R2: written 18:05:41, game launched 18:04:48 and still up afterwards. It is
not an exit-only flush, which is what the first version of this section
assumed and got wrong.

That makes pinning a comparison of mtimes, and `dev/ab_settings.py check`
does it:

| settings mtime vs captures | verdict |
|---|---|
| **before** the first capture | **PINNED** — the live file *is* the capture state; it is frozen into `UserSettings.atshoot.json` so a later Apply cannot take the proof away |
| **between** captures | **SUSPECT** — the set straddles a change; the tool names which scenes fall on which side |
| **after** the last capture | a change landed post-shoot; the live file is stale, so the tool falls back to `UserSettings.atshoot.json` / `.pre.json`, or says **UNPINNED** |

```bash
python3 dev/ab_settings.py show                        # current critical keys
python3 dev/ab_settings.py pre   a-b-testing/R3-off    # optional, pre-launch
bash a-b-testing/collect.sh R3-off S1 S2 S3            # calls `check`
```

The critical set: PT, PT-in-photo-mode, `DLSS_D`, DLSS quality + sharpness,
`RayTracedLighting`/reflections/sun/local shadows, resolution, texture
quality, FOV.

Procedure per rung: **state the required settings before the launch, read the
live file to confirm, shoot, then `check`.** Never reconstruct a rung's
settings from its pixels afterwards — captures are the expensive resource in
this project, and a timestamp settles in a second what forensics cannot
settle at all.

Pinning status: **R1 by argument** (`a-b-testing/R1-real/PINNING.md`),
**R2 PINNED by timestamp** (settings 18:05:41, first capture 18:06:49, 67s
clear). All three rungs ran **RR on**.

Scenes per `45` §2.4: **S1** direct sun on a face (one cheek lit, one
shaded, eyes visible) · **S2** bounce-lit face, no direct light · **S3**
grazing light, silhouette edge against dark.

## 1. What each rung changes (`44` §1, §3)

| rung | axes | what to look for |
|---|---|---|
| `real` | α ×1.3 (rougher) + coupling + micro-shadow + wet eyes | S1: broader, softer highlight; pores read instead of a sheen. S3: grazing skin *darker* (coupling gives back what the specular takes) and creases deepen (micro). Eyes: tighter, brighter catchlight. |
| `real-gloss` | α ×0.7 (glossier) + the same three | S1: tighter, brighter highlight — the wet/oily direction. Same S3 and eye behaviour as `real`. |
| `off` | tier-1 `c1` only (the control) | The shipping default. `46` §17: the mod brightens only the lit half of the face, from ~106 luminance up; S2 is expected to be near-vanilla (`42` does not close). |

The direction going in is `rough-1.3` (`CURRENT.md`), held on the user's
"detail filter" reaction and `33` §2's wet-plastic argument — **not** on
numbers. `real-gloss` is on the ladder to be given a fair look anyway.

Fall-back rungs, only if one axis offends and we need to know which:
`couple` (S3 darkening alone) · `micro` (crease darkening alone) ·
`eyes-wet` (catchlights alone). Kernel presets (`kernel=callisto` vs
`detail`) ride along at the end of the session if there is room.

## 2. Ledger

| rung | served? | S1 | S2 | S3 | verdict |
|---|---|---|---|---|---|
| R1 `real` | ✅ 17:44:38 | 2nd | 2nd | 2nd | *"real is decent"* |
| R2 `real-gloss` | ✅ 18:04:48 | **win** | **win** | **win** | **WINNER — *"real-gloss wins in every scene, it's no contest… the gloss brings it to the next level"*** |
| R3 `off` (control) | ✅ 18:16:46 | last | last | last | *"the off setting looks like plastic"* |

**Verdict: `skinspec=real-gloss`.** User's call, by eye, 2026-08-30 evening,
against a control shot in the same session with the camera pixel-identical and
the settings pinned. Unanimous across all three scenes, no single-axis
fallback needed — `couple`, `micro` and `eyes-wet` were not run separately and
do not need to be: nothing offended.

Scene: exterior daylight, two NPCs, one face centre-frame — the same save and
camera as `E1-shipping-default`/`E2a`/`E2b`, which makes those available as
informal orientation (they are *not* the control; R3 is).

R1 settings pinning is established by argument — see
`a-b-testing/R1-real/PINNING.md`. R2 and R3 are PINNED by timestamp. All three
ran RR on.

### 2.1 Validity of the three-way comparison (checked, not assumed)

| check | result |
|---|---|
| **camera** | **pixel-identical.** Best-fit shift of a static background patch, ±6px search, is `dx=0 dy=0` for `real` and `real-gloss` against `off`, in **all three scenes**. |
| **regime** | one regime. S1 non-skin grass fine-energy 22.85 / 22.76 / 22.84 (**0.4%** spread) and sky 1.402 / 1.403 / 1.388, both under the ~3% S1 non-skin floor (`46` §16.2). |
| **settings** | identical and pinned: RR on, PT on, PT-in-photo-mode on, DLSS Balanced, 2560x1440. |
| **serve** | 105 HITs and `last_resolve=77` on each; each rung's own `skin_sha`; 0 new `ser_reject`. |

So every on-screen difference between these nine images is attributable to
`skinspec` alone. That is the condition `46` §13 broke and `47` §11 asked for.

Comparison crops are regenerated by `dev/ab_montage.py` (control first):

```bash
A="off=a-b-testing/R3-off real=a-b-testing/R1-real real-gloss=a-b-testing/R2-real-gloss"
python3 dev/ab_montage.py <out> S1 S1.face $A
python3 dev/ab_montage.py <out> S1 S1.eyes $A
python3 dev/ab_montage.py <out> S3 S3.face $A
python3 dev/ab_montage.py <out> S2 S2.face $A
```

## 3. Serve audit

Pre-registered, from `~/.local/lib/callisto/skin.set/<rung>/*.spv | sha256sum`
and the L1-L8 serve signature (`a-b-testing/LAUNCHES.md`): every rung must
show `ptq=rcbm ser=off skin=on tier=1 cache=cleared`, **105 HITs**
(dxil x77 + rgs_reference_main x12 + reflection x3 + shadow x10), **0
`ser_reject`** -- and the rung's own `skin_sha`:

| rung | expected `skin_sha` |
|---|---|
| `real` | `a02593bdc2cbdc37` |
| `real-gloss` | `b0eb3becb777c287` |
| `off` | `0d0f3ee45ea0d538` |

A launch whose journal does not match its row is not looked at (`45` §2.3).

| launch | journal | HITs | notes |
|---|---|---|---|
| R1 `real` 17:44:38 | `ptq=rcbm ser=off skin=on skinspec=real skin_sha=a02593bdc2cbdc37 tier=1 cache=cleared` | **105** (4044−3939) | `last_resolve=77`; SER `enabled/already_enabled_feature_on`; 0 new `ser_reject` (the 15 in the file are historical, pre-`44`). Matches the pre-registered row exactly. |
| R2 `real-gloss` 18:04:48 | `ptq=rcbm ser=off skin=on skinspec=real-gloss skin_sha=b0eb3becb777c287 tier=1 cache=cleared` | **105** (4149−4044) | `last_resolve=77`; 0 new `ser_reject`. Matches the pre-registered row exactly. Settings **PINNED**: RR on, written 67s before the first capture. |
| R3 `off` 18:16:46 | `ptq=rcbm ser=off skin=on skinspec=off skin_sha=0d0f3ee45ea0d538 tier=1 cache=cleared` | **105** (4254−4149) | `last_resolve=77`; 0 new `ser_reject`. Matches the pre-registered row exactly. Settings **PINNED**: RR on, unchanged for 773s before the first capture. |

## 4. What this overturns

`CURRENT.md` carried **`rough-1.3`** as the direction, on the user's earlier
unprompted "detail filter" reaction plus `33` §2's wet-plastic argument, and
explicitly *not* on numbers (`46` §11.5). **The eye reversed it.** With all
four axes composed and a same-session control, `real-gloss` (α ×0.7) beat
`real` (α ×1.3) in every scene, and the word the user reached for to describe
the *unmodded* skin was the very one the roughness direction was supposed to
cure: **"plastic"**.

Two readings, and the evidence does not separate them:

1. The E2 single-axis call was made against a weaker comparison (E2a/E2b
   straddled the `46` §13 regime break; the E2a→E2b differential was the
   "only surviving quantitative separation" and `CURRENT.md` said not to
   spend launches defending it).
2. The direction genuinely flips once coupling + micro-shadowing are present —
   they remove energy at grazing, so the build can afford a tighter, brighter
   highlight without reading as wet plastic. The three shared axes are doing
   the work the roughness scale was being asked to do alone.

(2) is the more interesting claim and it is **untested**; `gloss-0.7` alone vs
`real-gloss` would decide it in one launch, if anyone cares. Nothing in the
ship decision waits on it.

## 5. Reach: where the mod actually lands

Mean |`off` − `real-gloss`| over the face, against a **non-skin control patch
in the same two frames** (which absorbs the PT sample noise between launches):

| scene | face | control | ratio |
|---|---|---|---|
| S1 direct sun | 4.649 | 1.119 | **4.15×** |
| S2 bounce-lit | 2.313 | 1.259 | 1.84× |
| S3 grazing | 1.628 | 0.853 | 1.91× |

The user's "wins in every scene" is honest as an impression, but the *reach*
is very uneven: S1 is unambiguous, S2 and S3 are under half that ratio.

This does **not** reopen `42`. S2 is an interior with strong local emitters,
so the skin there carries a real direct-light term that the painted modules do
reach — it is not the bounce-only case `42` is about. S3 is dim, and `46` §17
put the mod's switch-on at ~106 luminance, below which it does nothing. Both
readings are what the existing model predicts. **Item 1 (the static GI-writer
search) is untouched by tonight and remains the biggest visible win available.**
