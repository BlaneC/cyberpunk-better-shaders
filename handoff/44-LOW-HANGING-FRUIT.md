# 44 — Low-hanging fruit: the realism knobs, the SER bug that un-patched PT, and what the handoffs got wrong

Written 2026-08-30 (afternoon), one session. Brief: *implement every
low-hanging item from `38`/`43` as an optional feature, holistically — how
they combine into realistic materials in path-tracing mode — and set up the
A/B run-through for the next model (`45`).* Nothing here has been on screen.
Every rung below is **built, validated offline, parked, and deployed**; the
first pixel is `45` E1.

## 0. TL;DR

- **Four skin realism axes** in the compute-resolver patcher, all skin-gated,
  all identity-by-default, composable in one build: roughness **scale**
  (`alpha_scale`, `43` M2), **eye** roughness cap (`eye_alpha_max`, `43` M6),
  diffuse/specular **energy coupling** (`dcouple`, `43` M4), albedo-driven
  **micro-shadowing** (`micro_k`, `43` M5). The skin ladder went from 5 rungs
  to **14** (§1); the CET selector is now *Skin build*.
- **Sun angular size** (`43` M3) plus `SunVisibility`/`SunScatteringScale`
  in the PT engine panel — live, no relaunch.
- **SSS kernel presets** from the CET tab: `off | detail | balanced |
  callisto | vanilla` (was a boolean; the four kernels ship in `kernels/`).
- **SER can now be selected from CET** (`init.lua` dropped the key), and the
  layer no longer **un-patches the whole PT stack** whenever the app enables
  the extension itself — which it does, every launch (§2.1).
- `make install` exists. The game had been running a `sync_settings.sh` and
  `init.lua` two commits stale (§2.3).
- Corrections to `38`: material-fetch `+2` is the **shading normal**, `+1`
  is albedo, there is no hair-direction channel (§2.4); the "vkd3d-proton
  does not deliver SER" claim is half right (§2.1).

## 1. What was built

| feature | knob / key | rung(s) | where |
|---|---|---|---|
| roughness scale, keeps authored variation | `alpha_scale` | `rough-1.3`, `rough-1.6`, `gloss-0.7` | `patch_compute_skin.py::build_skin_alpha_cap` |
| wet / glassy eyes (class 8 alpha ceiling) | `eye_alpha_max` | `eyes-wet` 0.0064, `eyes-glassy` 0.0016 | same pass, `eye_gate` emitted in `process()` |
| diffuse/specular energy coupling | `dcouple` | `couple` (s = 1.0) | `build_skin_c1` (rides the c1 select) |
| albedo micro-shadowing | `micro_k` | `micro` (k = 1.0) | `build_skin_c1` + `find_diffuse_colour` |
| the combined candidates | all four | `real` (×1.3), `real-gloss` (×0.7) | `patch_compute_skin.sh` `LEVELS` |
| sun disc size / visibility / scattering | CVars | live | `pt_engine.lua` DEFS |
| SSS kernel preset selector | `kernel=` | off/detail/balanced/callisto/vanilla | `init.lua`, `sync_settings.sh`, `kernels/` |
| SER rung selector | `ser=` | off/class/byte/hit/class+hit | `init.lua` (`SWITCHES` + selector) |
| layer: app-enabled SER counts as enabled; SER reject falls through to the next overlay | — | — | `swap_layer.c` `ser_enable_setup`, `load_swap` |
| deploy target with backups | `make install` | — | `Makefile` |

The ladder as parked in `~/.local/lib/callisto/skin.set/` (every rung
carries the identical tier-1 `c1`; `off` is the control):

| rung | parent | gloss knobs | realism knobs |
|---|---|---|---|
| `subtle` … `extreme` | chain | the original `27` ladder, unchanged bytes | — |
| `rough-1.3` / `rough-1.6` | off / rough-1.3 | identity | `alpha_scale` 1.3 / 1.6 |
| `gloss-0.7` | off | identity | `alpha_scale` 0.7 |
| `couple` | off | identity | `dcouple` 1.0 |
| `micro` | off | identity | `micro_k` 1.0 |
| `eyes-wet` / `eyes-glassy` | off / eyes-wet | identity | `eye_alpha_max` 0.0064 / 0.0016 |
| `real` | rough-1.3 | identity | 1.3 + couple + micro + eyes-wet |
| `real-gloss` | gloss-0.7 | identity | 0.7 + couple + micro + eyes-wet |

Coverage (from the build's per-module reports, not byte diffs — `42`):
| rung | modules | c1 sites | Fresnel channels | α ids rewritten | coupling sites | micro sites | micro skipped |
|---|---|---|---|---|---|---|---|
| `off` | 77 | 173 | 0 | 0 | 0 | 0 | 0 |
| `subtle` | 77 | 173 | 1071 | 408 | 0 | 0 | 0 |
| `medium` | 77 | 173 | 1071 | 408 | 0 | 0 | 0 |
| `strong` | 77 | 173 | 1071 | 408 | 0 | 0 | 0 |
| `extreme` | 77 | 173 | 1071 | 408 | 0 | 0 | 0 |
| `rough-1.3` | 77 | 173 | 0 | 408 | 0 | 0 | 0 |
| `rough-1.6` | 77 | 173 | 0 | 408 | 0 | 0 | 0 |
| `gloss-0.7` | 77 | 173 | 0 | 408 | 0 | 0 | 0 |
| `couple` | 77 | 173 | 0 | 0 | 173 | 0 | 0 |
| `micro` | 77 | 173 | 0 | 0 | 0 | 150 | 23 |
| `eyes-wet` | 77 | 173 | 0 | 408 | 0 | 0 | 0 |
| `eyes-glassy` | 77 | 173 | 0 | 408 | 0 | 0 | 0 |
| `real` | 77 | 173 | 0 | 408 | 173 | 150 | 23 |
| `real-gloss` | 77 | 173 | 0 | 408 | 173 | 150 | 23 |

All 14 rungs: 77/77 modules, 0 `skipped_dom` anywhere, 2 gates lifted onto a class phi (`42`); every rung differs from `off` **and** from its parent on 77/77 modules; `spirv-val` clean. The 23 micro skips are the 17 modules listed in the build log (`99bb7c26` 6/12, the rest 1–3 sites each). The five original rungs rebuild with identical coverage to `42`; `medium` was additionally proven byte-identical to the previous install before the rebuild.

## 2. Findings and corrections — the roast section

### 2.1 The SER "restoration" was silently un-patching the PT stack

`~/callisto_swap.jsonl` on every launch since `41` shipped:

```
{"ev":"ser","action":"skipped","reason":"already_enabled","app_exts":71}
```

vkd3d-proton **already enables** `VK_NV_ray_tracing_invocation_reorder`
(it just never emits `OpReorderThreadWithHintNV`). The layer's
`ser_enable_setup()` returned 0 with that reason, the caller recorded
`d->ser = 0`, and `xCreateShaderModule` then `ser_reject`ed every SER
module — 15 rejects in the probe launches — **and served the vanilla
module**, not the next overlay. So on any `ser=class` launch, `swaps.ser/`
outranked `swaps.ptq/` *and* was refused, and the twelve reference raygens
went **vanilla**: no tier-1 mask widening, no MS-GGX, no firefly clamp. The
launch journal confirms it — the 10:24 and 10:27 launches ran `ser=class`,
so the `probe-both` screenshot was taken over vanilla raygens (the probe's
paint is in the compute resolvers, so its *reading* stands; the PT stack
behind it does not).

`41` §7 measured that the driver accepts SER modules without the extension
and called the enable "belt-and-braces". It never noticed the belt was
strangling the braces: the *reject guard it was so proud of* was the bug.
`38`'s "vkd3d-proton silently does not deliver SER" is half right: it
delivers the extension and not the instruction.

Fix (`swap_layer.c`): every `already_enabled*` reason now sets `ser_on`
after a successful `vkCreateDevice`, with the app's feature-struct state
logged (`already_enabled_feature_on|off|no_feature_struct`); and
`load_swap()` skips a SER-declaring candidate **and keeps searching** the
remaining overlays, logging `"action":"next_overlay"`. The post-search reject
is kept as a dead last line of defence. `./dev/patch_ser.sh --selftest`:
11/11 against the real driver.

### 2.2 SER could not be selected from CET at all

`init.lua`'s `SWITCHES` did not contain `ser`, so `saveParams()` rewrote
`brdf_params.txt` without it on every change. `41` documented "pick the half
in brdf_params.txt" as if the file were hand-edited; the CET tab erased the
edit the next time any switch moved. Added the key and a selector.

### 2.3 The game was running stale code

The game-side `sync_settings.sh` differed from the repo copy by 95 lines
(still had `skinray`) and `init.lua` predated `80b0fce`. There was no
deploy target — `release/install.sh` is the *end-user* installer and nobody
ran it during development. `make install` now: `release` + `layer`, backs
up the CET and red4ext dirs to `<game>/.callisto_backup/<stamp>/`, copies
`release/game/.` over, and puts the `.so` in `~/.local/lib/callisto/`.
Deployed 2026-08-30 11:31; `cmp` clean.

### 2.4 `38` §1.2 / B1 / M7: `+2` is the shading normal, not "unknown"

`4d46848998312027` lines 330–380: the `+1` fetch is squared into linear
albedo; the `+2` fetch is `(x − 0.5)` normalised and feeds
`OpCompositeConstruct %v3float` — **the N in every NoL/NoV dot**. So there is
no spare texel carrying hair direction or anything else; G-B1 is **negative**
for `+1`/`+2`, and `43` M7 (hair direction from a material channel) has no
input to read. `38` speculated about "+2 as a second material word"; it is
the normal, and the module computes with it on every pixel.

### 2.5 `--sets --set K=V` never overrode a rung

`build_into` put the command-line `--set`s *before* the rung's own, and
argparse keeps the last assignment — so the documented
`--sets --set alpha_max=0.06` silently did nothing on every rung that named
`alpha_max`. Order swapped.

### 2.6 `--sets` deleted the probe rungs

`rm -rf skin.set/` at park time wiped `probe-*` (owned by
`patch_subtype_probe.sh --install`) while the CET selector kept offering
them. Now only non-`probe-*` dirs are removed.

### 2.7 `--with-skinspec` defaults are not identity

`KNOBS` has `n_s=0.65, alpha_max=0.2025`; a `LEVELS` entry naming only its
own knob would have carried the default gloss too. Every rung now spells out
`n_s=0.5,spec_gain=1.0,alpha_max=1.0` (the `G0` prefix) when it means no
gloss. This is the same trap as `GOTCHAS` "one knob, two defaults".

### 2.8 Micro-shadowing cannot reach 23 of 173 sites

The albedo detector (§3.4) walks the c1 scalar's three-way fan-out to the
per-channel `albedo·(1−metal)` triple. In 17 modules some sites multiply by
light·shadow only — albedo was folded in upstream, out of reach. Those sites
keep `c1` and coupling and skip micro; the build prints the per-module
`found/total` list and does **not** abort, because the skip is structural,
not a gate failure. The dispatching GI resolver `99bb7c26` gets 6 of 12.
This is a coverage gap, not a bug, and it is loud (per `GOTCHAS`).

### 2.9 The probe screenshot, read (never written up)

`Screenshot From 2026-08-30 10-30-07.png` (repo root) is the `probe-both`
launch. Multiple region-correlated hues: terrain/mountains orange, wood and
concrete yellow-amber, Panam's jacket saturated red, skin salmon/orange-red,
the chair turquoise, foliage green, hair near-black, sky unpainted. Per `40`
§10 that is **"G-U4 opens"**: `word & 31` carries a per-material value that
the compute resolvers *could* branch on. The **sheen** half is unreadable
from this image (the paint dominates). Naming the values needs a pixel
sample against `./dev/patch_subtype_probe.sh --legend`; `45` E11.

### 2.10 Smaller things

- The `kernel` "vanilla" preset is a *re-authored* copy of the engine
  kernel, not the engine's data; `off` is the true control (the selector
  says so).
- `patch_ser.sh`'s matrix source label says "(base+skin)" while copying
  `base` only. Cosmetic; left.
- `41`'s standing risk ("a ptq rebuild without a SER rebuild silently drops
  the splices") was real and had already happened: the parked `ser.set`
  was built on `ptq/rcbm/**skin**` while the new sync serves `rcbm/base`.
  Rebuilt with `--from ~/.local/lib/callisto/ptq/rcbm/base`;
  `src_sha=55ed4e5c6884ab71` equals the served set.
- The CET kernel switch had no `[running:]` readback; it has one now.

## 3. Design notes — why these four, and why they compose

The through-line: vanilla skin reads soft/plastic for three independent
reasons, and the existing ladder attacked the wrong one. (a) The authored
roughness maps are wide-ish (0.4–0.6) and the *cap* flattened them to one
value — killing the pore/T-zone variation that makes skin read as skin
(`33` §2). (b) The Disney diffuse in these resolvers is not energy-coupled
to the specular, so grazing skin glows instead of darkening. (c) There is
no occlusion term at the micro scale, so dark, porous skin never
self-shadows. Eyes are a fourth, separate problem: the cornea is authored
with skin-like roughness. Each axis is one knob, each is skin- or eye-gated,
and none rewrites the same id as another, so any subset composes in one
build.

### 3.1 `alpha_scale` — roughness scale (M2)
`α' = min(α·k, 1)` on skin, then the existing cap if any. α = roughness²,
so ×1.3 is roughness ×1.14 (0.5 → 0.57), ×0.7 is ×0.84 (0.5 → 0.42). The
distribution moves; its shape survives. Rewrites **all** uses of each α (eval
and importance-sampling) so MIS stays unbiased, in the **same single
`replace_all_uses`** as the cap and the eye cap — the pass now emits one
nested select per α:
`select(skin, min(min(α·k,1), α_max), select(eye, min(α, α_eye), α))`,
each factor present only when its knob is live.

### 3.2 `eye_alpha_max` — wet eyes (M6)
Class 8 per `31` §5, whose ladder (`damp 0.0225 / wet 0.0064 / glassy
0.0016 / extreme 0.0001`) was written for the raygen tier and never built
anywhere. `wet` and `glassy` are parked. The eye gate is one more `OpIEqual`
on the same shift the skin gate uses, so it inherits `42`'s phi lift.

### 3.3 `dcouple` — energy coupling (M4)
Normalised Ashikhmin–Shirley coupling in the f0-independent form:
`diffuse *= (1 − s·(1−NoL)⁵)(1 − s·(1−NoV)⁵)`. The `(1−NoL)⁵` is
`Exp2(5·Log2(1−NoL))` reusing the `Log2` ids `c1` already computes, so it
costs 10 instructions per site. It rides `c1`'s select as one more factor,
which is what keeps the site at exactly one `replace_all_uses`.

### 3.4 `micro_k` — albedo micro-shadowing (M5)
`diffuse *= sat(1 − (1−NoL)²·k·(1 − lum(D)))`, `D` = the site's linear
`albedo·(1−metal)` triple, `lum` = Rec.709. The triple is found by
`find_diffuse_colour`: follow the c1 scalar through single FMul/FAdd
consumers until it fans out three ways, expand each branch's operand tree
four deep through FMul, and take the first depth at which all three are
distinct `OpFSub(X, OpFMul(X, M))` ids (optionally behind the material
guard's `OpPhi(%float_0, D)`) that dominate the site. Detection runs for
every site **before** any emission (`GOTCHAS` 12 — the rewrite changes the
use lists the detector reads).

### 3.5 What is *not* holistic yet
The oily rungs and the realism rungs are separate branches of the ladder on
purpose (attribution first). Once `45` E2–E5 pick values, a rung combining
`alpha_scale` with a *mild* `n_s` reshape is one `LEVELS` line. The authoring
items (`43` A3/A5/A8), the NRD-vs-RR control (M1) and the DLSS preset test
are launch-protocol items, not builds, and are in `45`.

## 4. Verification record

- Refactor inertness: the `medium` rung rebuilt with the new patcher is
  **byte-identical on 77/77 modules** to the installed one (before the
  ladder rebuild), and the rebuilt ladder's five original rungs report the
  same coverage as `42` (173 c1, 1071 channels, 408 alphas, 0 skipped).
- Smoke on `4d46…`, `99bb…` (phi-lifted), `27004d…` with all four knobs:
  `spirv-val` clean; alpha reshape 4/49/4 with `cap+scale+eye`; coupling on
  every c1 site; micro 2/2, 6/12, 1/2.
- Layer: `make layer` clean (pre-existing snprintf warnings), `--selftest`
  11/11.
- `make check` clean; deployed and `cmp`-verified (§2.3).
- SER ladder rebuilt on `ptq/rcbm/base`; manifest sha = served sha.

## 5. Files touched

`dev/patch_skin_brdf.py` (KNOBS/VANILLA), `dev/patch_compute_skin.py`
(`find_diffuse_colour`, `build_skin_c1`, `build_skin_alpha_cap`, gates,
`process`, `main`), `dev/patch_compute_skin.sh` (LEVELS format, arg order,
coverage report, probe-safe park), `swap_layer.c`, `init.lua`,
`pt_engine.lua`, `release/game/red4ext/plugins/CallistoSSS/sync_settings.sh`,
`Makefile`, `release/game/red4ext/plugins/CallistoSSS/kernels/`, this file,
`45`, `CURRENT.md`, `GOTCHAS.md`, `19`, `README.md` (handoff index), notes
in `38` and `43`. Nothing committed (GOTCHAS rule).
