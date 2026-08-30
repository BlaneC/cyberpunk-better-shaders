# 45 — A/B launch protocol: walking the user through the realism stack

> **2026-08-30 late evening (`47` §11):** §3's E-queue is superseded — the
> collapsed queue lives in `CURRENT.md`. §0–§2 (serve verification, capture
> discipline, one variable per launch) remain permanent procedure; §4 and §6
> remain valid reference. Radiometric measurement is now reserved for
> disputed claims, under `GOTCHAS`' rules (replicated baseline both sides,
> non-skin control, floor before conclusion).

Written 2026-08-30 for **the next model**, who will sit with the user across a
series of game launches. It assumes you have read `CURRENT.md` and `44`.
Everything below is a *procedure*; the reasoning behind each feature is in
`44` §3 and the documents it cites. The one rule that outranks this file is
`GOTCHAS`: **built, loaded and swapped are not working. Only an on-screen A/B
is, and for SER only a frame-time delta is.**

## 0. How a launch works (read once)

1. The user sets switches on the **CET tab** (`Mods → CallistoSSS`) or you
   edit `<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt`
   directly (one `key=value` per line; the key set is `init.lua`'s
   `SWITCHES`). Nothing applies until the next launch.
2. The Steam launch options run `sync_settings.sh` **before** the game. It
   reads `brdf_params.txt`, materialises every overlay under
   `~/.local/lib/callisto/swaps.<name>/`, writes `kernel.bin` from the chosen
   preset, evicts the pipeline caches if the payload changed, appends a line
   to `~/callisto_launches.log`, and writes `status.txt` next to
   `brdf_params.txt`.
3. The Vulkan layer serves the swaps and logs every module decision to
   `~/callisto_swap.jsonl` (`CALLISTO_LOG` in the launch options).
4. At the *next* CET load the tab reads `status.txt` and prints
   `[running: X]` in each selector's label plus WARNING/NOTE lines at the top.
   Those lines are the only place the UI admits what was actually served.

The three files to check after **every** launch, in this order:

| file | what it proves | the line to look for |
|---|---|---|
| `~/callisto_launches.log` (last line) | what sync *asked* the layer to serve | `skinspec=<rung> skin_sha=… ser=<rung or off:reason> ptq=<combo> cache=cleared/kept` |
| `status.txt` | same, parsed for CET, plus last launch's hit counts | `want_skinspec=`, `want_ser=`, `want_kernel=`, `last_resolve=` (compute swaps applied) |
| `~/callisto_swap.jsonl` | what the layer *did* | `"ev":"ser","action":"enabled"`; count of `"swap":"HIT"`; **any** `ser_reject` or `rt_pipeline_failed` is a stop |

Useful one-liners:

```bash
tail -1 ~/callisto_launches.log
grep -c '"swap":"HIT"' ~/callisto_swap.jsonl            # rises every launch (file appends)
grep -o '"ev":"ser","action":"[a-z]*","reason":"[a-z_]*"' ~/callisto_swap.jsonl | tail -1
grep -c ser_reject ~/callisto_swap.jsonl                 # must NOT increase after 44
grep -c 'rgs_reference_main.*"swap":"HIT"' ~/callisto_swap.jsonl   # 12 per launch when ptq serves
```

## 1. Pre-flight (once, before the first launch)

Run from the repo root. Every line must come back clean.

```bash
make check                                    # Lua + shell syntax
ls ~/.local/lib/callisto/skin.set/            # 14 rungs: off subtle medium strong extreme
                                              #   rough-1.3 rough-1.6 gloss-0.7 couple micro
                                              #   eyes-wet eyes-glassy real real-gloss (+ probe-*)
ls ~/.local/lib/callisto/ser.set/             # byte class class+hit hit
head -1 ~/.local/lib/callisto/ser.set/class/MANIFEST.txt
cat ~/.local/lib/callisto/ptq/rcbm/base/*.rgs_reference_main.spv | sha256sum | cut -c1-16
                                              # must equal the manifest's src_sha (else ser reads off:stale)
ls "<game>/red4ext/plugins/CallistoSSS/kernels/"   # kernel.{detail,balanced,callisto,vanilla}.bin
cmp init.lua "<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/init.lua" && echo cet-in-sync
cmp release/game/red4ext/plugins/CallistoSSS/sync_settings.sh "<game>/red4ext/plugins/CallistoSSS/sync_settings.sh" && echo sync-in-sync
```

If either `cmp` fails: `make install` (backs up, then deploys; see `44` §2.3).
If the skin ladder is missing a rung: `./dev/patch_compute_skin.sh --sets`
(~5 min, clears caches). If SER is stale: `./dev/patch_ser.sh --install --from
~/.local/lib/callisto/ptq/rcbm/base` — **`rcbm` is the ptq combo for the PT
switches all on, `ptreg=on`; if the user changes any PT switch during the SER
experiments the combo letter set changes and SER goes `off:stale`. Freeze the
PT switches for the whole SER block.**

The live `brdf_params.txt` was normalised on 2026-08-30 to:
`tier=1 kernel=detail skin=on shadowcull=on shadowset=full-shadow skinspec=off
ptreg=on ptclamp=on ptbounce=on ptrefl=on ptmsggx=on ser=off`. That is the
**shipping default** and experiment E1's configuration.

## 2. The launch loop (every experiment)

1. Set exactly **one** thing relative to the previous launch. Say out loud
   which key changed and to what.
2. Launch through Steam (never the exe — sync would not run, and the CET tab
   will warn about it on the next load).
3. Before looking at anything: run the three checks in §0. If the journal's
   `skinspec=`/`ser=`/`kernel` is not what was asked, **stop** and fix the
   pipeline; a screenshot from a mis-served launch is worse than none
   (`26` §7 attribution lesson).
4. Load the **same save**, same time of day, same weather; photo mode, same
   camera. Three scenes, in this priority:
   - **S1 — direct sun on a face**: exterior, daylight, the companion NPC
     (Panam/Judy) turned so one cheek is lit and the other is in shade,
     eyes visible. Framing like `pics/panam_working_small.png`.
   - **S2 — bounce-lit face**: interior or shadow, no direct light on the
     skin. This is the `42` scene: every launch before 2026-08-30 served
     vanilla skin here.
   - **S3 — grazing light**: the face at ~80° to the light, silhouette edge
     against a dark background. Coupling and micro-shadowing live here.
5. Name every capture `<date>_<experiment>_<rung>_<scene>.png` and drop it in
   `a-b-testing/<experiment>/` (the convention `46` established; supersedes
   the `pics/` line this doc shipped with). Write one ledger row (§5) *before* the next launch.

Photo-mode caveat: some PT settings (`RayNumberScreenshot` etc. in the PT
panel) only apply in photo mode; keep them fixed across the block.

## 3. Experiment order

> **2026-08-30 evening: E0–E2 are DONE** (`46`) and the order below is
> superseded for the next four launches by `46` §9.4: **L1 A-B-A repeat →
> L2 probe-cls in S2 → L3 ptclamp=off → L4 RR-off**, then E3→E5, the E0
> re-shoot on the current character, E6. Read `46` §9 before launching.

The order is deliberate: each block establishes the reference the next one is
compared against, and the cheap live-CVar experiments come after the relaunch
ones so the user is not context-switching. Where a step says *decide*, the
decision is the user's; your job is to make the two halves comparable and to
say what each outcome means.

### E0 — bit-exact baseline (1 launch)
`tier=off kernel=off`. Everything else irrelevant (master forces it off).
Capture S1, S2, S3. Verify the journal says `tier=off` and the swap log shows
**zero** HITs for this pid. This is the reference for every later
comparison; do not skip it, and do not reuse an old one — the sun position
in the save must match.

### E1 — shipping default (1 launch) — *this is also the `42` launch*
`tier=1 kernel=detail skin=on skinspec=off` (the normalised file). Compare S2
against E0: the tier-1 `c1` (a mild diffuse-Fresnel brightening at grazing
plus retro-reflection) should now be visible on bounce-lit skin for the first
time. If S2 is pixel-identical to E0 while S1 differs, `42`'s fix did not
reach the dispatching resolver — check `status.txt`'s `last_resolve` (must be
77) and open an investigation before going further.

### E2 — roughness direction (2 launches)
`skinspec=rough-1.3`, then `skinspec=gloss-0.7`. Compare each S1 against E1.
Question: *which way is vanilla wrong?* Rougher = matte, broader highlight,
pores read; glossier = tighter, brighter highlight. Both keep the authored
variation (the oily ladder does not). **Decide** the direction; if rougher,
optionally `rough-1.6` to find the ceiling. This picks between `real` and
`real-gloss` in E6.

### E3 — energy coupling (1 launch)
`skinspec=couple`. Compare S3 (and S1's shaded cheek) against E1. Expected:
grazing skin gets **darker** — the diffuse gives back the energy the specular
takes. If nothing moves at all, the effect is smaller than the tonemapper
resolves at s=1; that is a real answer (drop it from `real` rebuilds).

### E4 — micro-shadowing (1 launch)
`skinspec=micro`. Compare S3 and S1 against E1, on the **darkest-skinned**
NPC available as well — the effect scales with (1 − luminance), so a very
pale face is a near-null by design. Expected: creases/pore regions darken as
the light goes grazing; direct-lit skin unchanged. Known coverage gap: 25 of
181 diffuse sites have no reachable albedo and keep only `c1` (`44` §2.8).

### E5 — eyes (1–2 launches)
`skinspec=eyes-wet`. Compare the eyes in S1 against E1. This touches
material class 8 only (`31` §5). Expected: a tighter, brighter catchlight.
If null, `eyes-glassy` (cap 0.04) is the diagnostic: if *that* is null too,
the eye material is not class 8 in the compute resolvers and `31`'s class
attribution is wrong — record it, it is the more valuable result.

### E6 — the combined candidate (1–2 launches)
`skinspec=real` (rougher ×1.3 + coupling + micro + wet eyes) or `real-gloss`
per E2. Compare all three scenes against E1 **and** E0. This is the
"holistic" check: the four axes were built to compose, so the question is
whether the sum reads as *a person* rather than as four effects. If one axis
dominates unpleasantly, the single-axis rungs from E2–E5 say which.

### E7 — SSS kernel presets (2 launches, kernel is engine data)
Keep `skinspec` at the E6 winner. `kernel=callisto` then `kernel=off`.
Compare S1's shaded cheek and the nose/ear translucency. `detail` (default)
keeps the tightest core; `callisto` has the widest red tail. `vanilla` is a
tooling check only: it should be indistinguishable from `off`; if it is
not, `dev/author_callisto_kernel.py`'s radius model is wrong (`33` §1).

### E8 — sun angular size (0 launches — live CVar)
PT engine panel → *Sun angular size*. The resolver tells you which CVar
group answered (`[group]` in the label); if none did, the three names from
`43` M3 are not live CVars in this build and the row is dead — say so. Sweep
0.5 → 1.5 → 3.0 in S1: shadow terminators soften and every highlight widens.
This composes with E2's roughness choice (a wider sun makes glossier skin
look rougher); note the pairing the user prefers.

### E9 — SER (2 launches, **frame time, not a screenshot**)
Freeze every PT switch. `ser=off` then `ser=class`; same save, same camera,
stand still 60 s each, read the average frame time (Steam overlay or the
game's own). Before reading anything, confirm in the swap log:
`"ev":"ser","action":"enabled"` **or** `"skipped","reason":"already_enabled_*"`
(both mean SER is on the device — `44` §2.1), 12 `rgs_reference_main` HITs,
and **zero** `ser_reject`. `already_enabled_feature_off` is a caveat to
record, not a stop. A delta under ~3% is noise; then try `hit`, which gates
81.7% of the shader (`41`). No delta on any rung = vkd3d-proton/driver is
not honouring the instruction; that closes `41`.

### E10 — the denoiser control (`43` M1, 1–2 launches)
Ray Reconstruction on vs off (game settings). Every skin result above was
observed through RR; the NRD-era CVars in the engine panels are dead while
it is on. Repeat E6's S1 with RR off to see how much of the "soft skin"
complaint is the denoiser, not the BRDF. Also the DLSS preset test from
`43` if the user wants it — it is a game setting, not this mod.

### E11 — the sub-enum probe, second look (optional)
The `probe-both` launch already happened (2026-08-30 10:27) and the
screenshot is in the repo root; `44` §2.9 has the reading. What remains is
pixel-sampling that image against `./dev/patch_subtype_probe.sh --legend`
to name the values. No relaunch needed unless the user wants `sheen` alone.

## 4. What each outcome means (decision table)

| observation | meaning | next |
|---|---|---|
| E1 S2 == E0 S2, S1 differs | GI resolver still un-gated | investigate `42`; nothing else is trustworthy on bounce-lit skin |
| E2 both directions look worse | the *cap* was not the problem; the authored maps are | authoring (`43` A3/A5), out of scope for shaders |
| E3 null | coupling too small to see through RR | drop from `real`; rebuild via `LEVELS` |
| E4 null on a dark face | albedo detector found the wrong triple | check the `micro_sites` count in the build log for the dispatching module (`99bb…`: 6 of 12) |
| E5 `eyes-glassy` null | eyes are not class 8 here | `31` §5 is wrong for compute; record, move on |
| E6 reads as "plastic" | roughness axis wrong way | swap `real`↔`real-gloss` |
| E7 `vanilla` ≠ `off` | kernel tooling wrong | `33` §1 before trusting `detail` |
| E9 delta on `hit` only | class hint too narrow (0.4% of lines, `41`) | ship `hit`, keep `class` as control |
| E9 no delta anywhere | SER not honoured under vkd3d-proton | close `41`; leave `ser=off` |

## 5. Ledger row template (append to `19-STATUS.md` §1 or a new `46`)

```
| <feature> (<rung>) | <ships / off / removed> | <what was seen, scene, vs which baseline, date> | `44`, pic `pics/<file>` |
```

One row per rung *observed*, never per rung built. If a rung was launched and
nothing could be concluded (wrong save, mis-served), say that in the row —
an absent row will be read as "never tried".

## 6. Troubleshooting

- **Label says `[running: fixed]` or `INERT`** — no `skin.set/` parked;
  rebuild the ladder.
- **`ser=off:stale`** — ptq changed under SER (a PT switch moved). Freeze the
  switches or rebuild with `--from …/ptq/<combo>/base`.
- **`ser_reject` in the log after 2026-08-30** — should be impossible with
  the 44 layer; if seen, the `.so` in `~/.local/lib/callisto/` is stale
  (`make install` copies it; check its mtime).
- **Selector says X, status says Y** — the launch bypassed Steam launch
  options, or the file was edited after launch. Relaunch.
- **"Nothing changed"** between two rungs — check the journal's `skin_sha`
  differs between the two launches and `cache=cleared` on the second. If the
  shas are equal, the rung was not served. If different and the picture is
  identical, that *is* the result: the knob does not reach a visible pixel
  under these settings (see `GOTCHAS` on byte diffs vs coverage).
- **Game does not start** after a layer change — `./dev/patch_ser.sh
  --selftest` (11 cases against the real driver) before blaming a swap.
