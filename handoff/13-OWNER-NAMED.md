# 13 — The owner is named: `6ac9085c9bd4b7da`, the temporal resolve

> **CORRECTED 2026-08-27 by `15-RENDER-GRAPH.md`.** 6ac9 runs at 2560×1440
> (post-upscale), gates on the 720p depth-stencil, and is a motion-direction
> smear, not a reprojecting temporal resolve — §3 and the §4 diagram are wrong
> in the middle. §5's hypothesis is falsified for direct light: all nine
> writers of the direct-lighting buffer were already in the 29-module net.
> The bisection results in §1–§2 stand.

Written 2026-08-27, after the 29-module hunt net (`12`) painted and a 6-round
bisection named the module that owns hair's visible pixels at the Panam scene.

---

## 1. The hunt painted (PANAM_OUTSIDE_WORKING.png)

The 29-module net painted at the Panam tourist-info scene — the same scene
where the rim-three hunt painted nothing (`12` §1):

- **hair — yellow (class 4), pixel-perfect**, following the strands exactly
- skin — class-1 red (so bright it clipped to white; dimmer on halves that
  removed some skin painters)
- eyes — violet (class 8)
- palm trees — magenta (class 5)

The class numbering holds per-pixel across materials; the reconstruction
(`material.y >> 5`, emitted by the patcher's fallback) is correct.

## 2. Bisection log (`dev/bisect_hunt.sh`)

| round | installed | result |
|---|---|---|
| 1 | all 29 | everything paints (baseline) |
| 2 | A = idx 0–14 (15) | hair still paints → owner in A |
| 3 | idx 0–7 (8) | **edges only, blocky** (rim-family remnant) → full-hair owner in 8–14 |
| 4 | idx 8–9 (`4a8e…`, `4d46…`) | hair paints **only at skin-boundary tiles**, blocky |
| 5 | idx 10–11 (`5d7d…`, `6ac9…`) | full pixel-perfect hair back, identical to baseline |
| 6 | `5d7d…` alone | **nothing at all** (log: HIT + `swapped:1` — valid null) |

⇒ **`6ac9085c9bd4b7da` owns hair's full, per-pixel paint.** Confirmed by the
round-6 log: `5d7d` dispatched swapped and painted nothing, `6ac9` dispatched
vanilla in the same launch.

Side findings:

- `4a8efc3f674e9c35` / `4d46848998312027` own **skin–hair boundary tiles**
  (hair paints only where it borders skin, 8px blocks) — mixed-material tile
  permutations.
- The rim three (`03dc…` in idx 0–7) paint only blocky sunlit edges at this
  scene — consistent with `11` §1 (sunlit-rim scope).
- Trees and eyes are painted by modules in idx 8–11 as well — but with
  `5d7d`+`6ac9` both present; given round 6, most plausibly **6ac9 paints
  them too** (it owns every per-pixel surface).

## 3. What `6ac9085c9bd4b7da` IS

Read of `dev/disasm/compute/6ac9085c9bd4b7da.dxil.spvasm` (350 lines, 3 fetches
+ 1 filtered sample, 2 writes, **no 1/π, no BRDF constants** — invisible to
the `1/π + k` anchor scan, exactly as `10` warned):

- `%135` fetch `v4uint` = material word; its own gate is `(y & 31) == 17`
  (sub-class 17 → writes **black** and exits).
- `%159` fetch = **velocity buffer** (2D vector, magnitude ×8 clamp).
- `%179` = **history**, sampled at the reprojected UV (current − velocity).
- `%196` fetch = **current-frame input** (rgb).
- A 5-tap cross filter (±0.2, ±0.4 motion-scaled offsets, ×0.2 weights) =
  neighborhood clamp on the current frame; then two lerps by confidence
  (`%194`, motion/alpha-derived `%259`).

**It is the temporal (TAA-style) resolve for the frame**: velocity +
history + neighborhood filter, blended per-pixel. It owns the final pixels
of every opaque surface — which is why its palette paint was pixel-perfect
while every lighting evaluator paints blocky.

## 4. The architecture this establishes

```
tile-classified lighting evaluators  (8px tiles, blocky)
  rim three  = >>5 sun family (boundary/sun tiles)
  4a8e/4d46  = mixed-material boundary tiles
  &31 family = local-light (never painted — see below)
        │  lighting buffer(s)
        ▼
6ac9085c9bd4b7da  — temporal resolve, per-pixel, owns the frame
        │
        ▼  screen
```

Two injection points, with different ceilings:

- **`6ac9`'s write** — per-pixel, class-4 gate proven on screen (the hunt
  WAS Phase 0 for this site: multiplicative modulation of hair pixels is
  visible and exact). **But no G-buffer here** (no normals/depth/roughness)
  — a real BRDF cannot be evaluated. Ceiling: colour/exposure shaping.
- **The evaluators** — have the G-buffer (the rim three read depth, albedo,
  normal, misc, material — `11` §2) but write at 8px tile granularity, and
  their splice sites for hair are unproven (rim three: spec_add null +
  the `%937`-phi discard, `12` §1).

## 5. The interior-hair evaluator is still at large

No patched module painted *interior* hair lighting. Per the architecture,
the module that computes interior-hair lighting writes a buffer `6ac9`
samples — its palette paint would have flowed to screen. It didn't, so it is
**not class-gated**: it is one of the **149 "no class read" failures**.
That is expected, not bad luck: a tile-classified per-class permutation
learns its class from *which pipeline was dispatched*, not from a class
read — it never needs the material word.

**Next step: buffer provenance, from capA (offline, no game launches).**
`6ac9` is in capA (`analysis/evidence/capA_modules_named.json`). Identify the
images behind its `%54`/`%59`/`%63` bindings (velocity / current lighting /
history), then find which dispatched compute modules **write** the
current-lighting image. Those writers are the evaluator set; the interior-hair
one is among them. Then the `--hair` tier targets *that* module — with the
class gate taken from the tile's dispatch identity, not a shader-side read.

Also worth noting for later: `6ac9`'s sub-class-17 black-write path. If hair
ever falls into sub-class 17 it is zeroed at the resolve — a possible
"missing hair" failure mode worth remembering.

## 6. State

- `~/.local/lib/callisto/swaps.hair/` = **the rim-three spec_add=8 probe**
  (Phase 0, real run — see below). The 29-module hunt net is backed up at
  `swaps.hair.bak_huntall29_20260827/`.
- **Phase 0 rerun staged**: the rim three paint blocky sunlit hair only in
  the 22:34 V-scene. The Panam null was scope, not mechanism. The valid gate:
  V in direct sun at the 22:34 spot, probe ON vs CET-toggle OFF. Blowout at
  the rim = lobe-level splice sites feed hair's output → real hair BRDF on
  the sun family is viable. No change = the `%937`-phi discard (§1 of `12`)
  is confirmed and the splice must move to the write or to 6ac9.
- `dev/bisect_hunt.sh` — A/B/all/list/range LO HI.
- Hunt build artifacts + per-module reports: `swaps.huntall/`.
- Patcher changes from `12` §3 are what made 6ac9 reachable (the &31
  fallback in `build_hunt_writes` via `acquire_class_shift`).
