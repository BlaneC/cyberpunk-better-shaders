# 39 — Backlit skin transmission: removed, and why the method was wrong

**Written 2026-08-30. This is a removal record and a postmortem.** The
Tier-4 backlit skin transmission — `skintrans`, plus its `skinthick`
anatomical-thickness variant — is **gone from this repo**: the SPIR-V pass,
the ladder tables, the CET switches, the `sync_settings.sh` keys, the parked
build sets, and the four handoff documents that carried it.

What it did on screen, in the user's words:

> *"the edges of geometry cast a blocky red glow straight through the face"*
>
> *"Theres still some glow straight through the face, and the neck has edges
> with clothing that make unrealistic glowing happen."*

Red-rimmed earlobes and jawlines, a wash across the forehead, and a visible
tile grid. At `medium`, not only at the `extreme` diagnostic rung.

---

## 1. The one-line verdict

**The approach was wrong, not the tuning.** Every knob added after the first
look was a proxy for a physical quantity the splice site cannot see, and
each one was defended by an offline check that could not have caught the
defect it was meant to fix. That is the failure worth remembering; the
feature itself is not.

---

## 2. What was actually built

Barre-Brisebois & Bouchard (GDC 2011) translucency, added to the skin
diffuse in the compute lighting resolvers, gated on material class 1:

```
H     = normalize(L + N*distortion)
back  = saturate(-dot(V, H)) ^ power
T     = back * thickness * mask
out  += lightCol * lerp(1, albedo, w) * tint * T
```

spliced at the light-gate merge (not inside the lighting arm — that arm sits
under the sun-shadow gate, so a term placed there is multiplied by zero
exactly where a backlit ear is). 77 modules, `spirv-val` clean, byte-identical
at `t_thick=0`, shipped as a 5×5 pre-built matrix crossed with the gloss
ladder, later a third `+k` axis. All of that machinery worked. None of it was
the problem.

---

## 3. Why the method sucked — four named mistakes

### 3.1 The term has no per-pixel shaping, and that was knowable before the build

`V` and `L` are both effectively constant across a face. The only spatial
variation in `back` is `0.35·N` projected onto `V` — a **wrap**, a slow
gradient over the whole backlit side, not a rim. And the `saturate(-N·L)`
mask is ON across the entire front of a backlit head, because that is what
"the light is behind me" *means* for every forward-facing pixel.

**A forehead scores as high as an ear.** `t_power` cannot fix that: it
sharpens a near-constant.

The original feasibility doc predicted this verbatim as the honest failure
mode of this exact route, and it was built anyway, because the *route* was
ranked cheapest rather than most likely to be right. Cheapest-first is
correct for a probe. It is not correct for something wired to a CET switch,
a five-rung ladder and a 25-set build matrix.

### 3.2 Thickness was never available, and three proxies in a row did not make it so

The feature needs one input the site does not have: **how thick is the skin
here**. What was tried, in order:

| proxy | what it actually measures | why it failed |
|---|---|---|
| `1 - sunShadow` | "this pixel is in shadow" | cannot tell my own head's shadow from a building's |
| `CharacterLightBlockers` | the engine's own blocker volume | present in only 40 of 84 libs; a coarse per-character volume, not per-pixel |
| `pow(1 - abs(N·V), t_rim)` | grazing **shading** angle | carries normal-mapped pore detail; turns away on the jaw and cheek exactly as on an ear; knows nothing about what is *next to* a pixel — so it could never address a clothing boundary |
| depth-ring openness (`t_open`) | screen-space silhouette openness | view-dependent; a face against a wall reads thick; needs a material-class tap to reject a collar behind the neck, and still fails at screen edges |

Each proxy was added *after* the previous one was seen to fail, and each was
a smaller correction to a term whose base shape (3.1) was already wrong.
**The user named this correctly at the time:** ~15 knobs approximating one
physical quantity is a symptom, not a design. That objection was recorded as
a finding and then not acted on.

### 3.3 The splice site was wrong for a term that ADDS light

Every earlier Callisto tier **multiplies** into an already-quantised signal,
so the compute evaluators' 8px tile quantisation is invisible. Tier-4 was the
first that **adds** new light — and against a flat tile grid, an added term
draws that grid as a step edge. Hence "blocky".

No knob in the feature reaches this. It is a property of the site: the
compute resolvers are the non-traced half of the frame, running at 720p and
tile-classified before a material-unaware upscale. **The defect had no fix
where the feature lived**, and that was known before the last two knobs were
added.

### 3.4 The verification proved the build, never the picture

The offline checks were thorough and all passed: 77/77 `spirv-val`, per-axis
byte-difference assertions, byte-identical `off` sets, reproducible rebuilds,
hand-read SPIR-V for the reverse-Z sign, a sibling sweep across all anchored
libs. Every one of them answers *"did the instructions I intended get
emitted"*.

**Not one of them could answer "does a forehead glow".** The gap between
"the splice reaches the screen" and "the splice is correct" was never
closed by a check, only by a launch — and between the first launch and the
removal, two more shaping terms and a whole third build axis were added on
the strength of offline evidence alone.

The rule this pays for is in `GOTCHAS`: **a structural detector proves a
site's shape, never what it means.** This is the largest instance of that
rule being violated in the repo's history — not by ignoring it, but by
adding checks that satisfied it in letter and left the actual question
unasked.

---

## 4. What was removed

| | |
|---|---|
| `dev/patch_compute_skin.py` | the entire Tier-4 block (~1120 lines): `find_transmission_site`, `build_skin_transmission`, the depth/material taps, the light-blocker finder, the phi-rewrite helpers, `--with-translucency` |
| `dev/patch_compute_skin.sh` | `TLEVELS`, `THICKLEVELS`, `THICK_GLOSS_LEVELS`, the `--trans` flag and the cross-product build loops |
| `dev/patch_skin_brdf.py` | all 19 `t_*` knobs |
| `dev/survey_translucency.py` | deleted — it existed only to sweep this detector |
| `init.lua` (+ release copy) | `skintrans` / `skinthick` defaults, `TRANS_LEVELS`, both CET widgets, `skintransNote` / `skinthickNote` / `THICK_GLOSS` |
| `sync_settings.sh` | the two keys, the composed `<gloss>+t<trans>[+k]` name resolution and its two fallback paths |
| build artifacts | 28 `swaps.skin.*+t*/` dirs (661 MB) and 28 parked `skin.set/*+t*/` |
| handoff | `30-SKIN-TRANSMISSION-BUILD.md`, `34-BACKLIT-ANATOMY.md`, `35-THICKNESS-ROUTES.md` deleted; `29`'s Part A replaced by a pointer here |

`skin.set/` now holds only the five gloss rungs, and the installed
`swaps.skin/` was re-materialised from `skin.set/off` so a launch that
bypasses `sync_settings.sh` cannot still serve a transmission build.

A stale `brdf_params.txt` may still carry `skintrans=` / `skinthick=` lines.
They are ignored — `sync_settings.sh` whitelists keys — and `init.lua`
overwrites the file on its next save.

## 5. What was deliberately KEPT

- **`GOTCHAS` 12** (a read-only detector must run before any pass that
  rewrites uses) and **13** (existence is not addressability). Both were
  paid for by this work and both are general. They now cite this document.
- **`29` Part B** (per-material ray budgeting) — a separate, live thread
  that `32`, `37` and `38` all build on. Untouched.
- **The engine's own `CharacterSubsurfaceTranslucency` CVar** in
  `skin_engine.lua`. That is the game's knob, not ours; `29` A1's finding
  that it never reaches the traced path still stands and is still worth a
  live A/B.
- **The Tier-3 gloss ladder** (`skinspec`). Different splice, different
  term, unaffected.

## 6. If it is ever attempted again

Do not re-derive the above. The two conditions that would make it worth
restarting, both currently unmet:

1. **A real thickness signal, not a proxy.** The engine's back-depth pass
   exists and runs in Overdrive, but its bindless heap index moved
   73203 → 503350 across two captures 29 seconds apart in one session, so
   it is not addressable offline. Reopening needs an engine-side binding
   (RED4ext descriptor injection), not a heap index.
2. **A different splice site.** Tier-4's defect 2 (§3.3) has no fix in the
   compute resolvers. Measuring thickness with a ray in the RT path is the
   principled route: its output is not tile-quantised, so the blockiness
   goes away as a side effect rather than being worked around. That is
   gated on the payload sentinel — `29` Part B's ranked item 4, still
   small, still no risk, still never run.

Until at least one of those holds, this feature has no honest route, and
the correct amount of it in this repo is none.
