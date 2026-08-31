# 76 — Glass refraction Phase 0.5: built, launched, KEPT

Written 2026-08-31. Implements `51` §4 / `20` §5b's Phase 0.5 — the D3 "real
glass refraction" idea from `38`. Built, deployed, and **on screen**.

## USER VERDICT 2026-08-31: KEEP — "the refraction feature looks incredible."
Adjudicated PASS against §3: the user viewed it and asked for it to be
committed. Recorded from the user's words, not from a capture read by this
session — no ghosting/no-change branch was reported, and the per-pixel
warp-vs-ghost evidence in §3 was not independently re-examined here. Which
level was on screen (eta20 vs eta15) is NOT established; the shipped default
stays `refract=off`, so nothing changes for anyone who does not opt in.

## 0. The gate, and why the build did not wait for it

`51` §4 orders the offline consumer-naming read first (open item 1 of `20`:
which pass composites `rgs_reflection_transparent_main`'s output, and does it
add, lerp or replace). **That item is still open** — `20` established the
probe logs compute bindings only, so it needs the layer tweak of `20` open
item 3 or a reader-set argument over ~90 candidate images.

It gates the **v1 two-ray combine** (`F·refl + (1−F)·refr` ghosts if the
consumer adds). It does not gate Phase 0.5, which **replaces** the traced
direction wholesale: the consumer composites exactly one traced term either
way, same alpha, same magnitude scale — whatever it did with the mirror image
it now does with the bent one. `20` §6 [corr 08-28] says explicitly: if a
launch is being spent, spend it on Phase 0.5. That is what is parked here.
The one confound to keep in mind reading the screenshot: the raster
alpha-blend see-through underneath is untouched, so the bent view is laid
over the straight one — "does it warp or ghost" is precisely the question
the launch answers, per pixel, for free.

## 1. What was built

`dev/patch_refract.py` — text splice on the **committed ptrefl spvasm**
(`swaps.ptrefl/ee6d252e090adc74.rgs_reflection_transparent_main.spvasm`,
which differs from vanilla only in the reflection trace's cullMask 1→255;
the widened mask is *wanted* for a transmitted ray, `20` §5b). All
straight-line, no new blocks, no new globals (SPIR-V 1.4 interface list
untouched), ids 2900+ against a vanilla bound of 2832:

- **Refracted direction** from the module's own `dot(D,N)` (`%235`), D
  (`%201-203`), N (`%131-133`): `T = η·D − (η·dot(D,N) + √k)·N`,
  `k = 1 − η²(1−dot²)`. η = 1/n < 1 so **k ≥ 1−η² > 0: TIR is impossible
  and no branch is needed** — the `OpSelect` machinery `20` §5b budgeted
  for the two-ray version is not required in Phase 0.5.
- **Origin sign fixed** (`20` §1 corr): `P + ε·(1+9·fade)·D` (through the
  surface) instead of vanilla's `P − …` (outside it, self-hits). Built by
  flipping the existing FSub to FAdd on the same `%227/%229/%231` ε terms.
- **All 19 downstream uses** of the mirror direction (`%242-244`) and origin
  (`%232-234`) rewritten to the new ids: the trace (`%265/%266`), the
  env-miss cubemap lookup (`%296-298`), the horizon fade (`%327`), hit
  reconstruction (`%394-399`), SSR reprojection (`%407/409/411`,
  `%437-439`), and the volume-probe origin (`%706`). Defs left in place
  (dead), no vanilla line deleted. Anchors are instruction-shape regexes
  with die-on-guess; the rewrite count is asserted ==19.

Validation per build: 500-sample fp32 evaluation of the **emitted text**
against reference Snell (|T|=1, head-on D→D) — the `74`-style machine check;
`spirv-as --target-env spv1.4` + `spirv-val` clean; full diff vs source is
exactly 2 constants + 19 insertions + 19 rewrites.

## 2. The ladder and how it is served

`dev/build_refract.sh [--install]` parks three rungs (repo:
`swaps.refract.<level>/`, installed: `refract.set/<level>/`):

| level | file | sha16 |
|---|---|---|
| off | byte-identical plain-ptrefl raygen (A/B control) | ac2cd8f7d550fe93 |
| eta15 | n=1.5 — physical window glass | 8c88926a273ae541 |
| eta20 | n=2.0 — double bend, for finding the effect | c96eaef809c8a734 |

**The rung rides `swaps.ptrefl/`** — that overlay owns the module id
(first-file-wins, `swap_layer.c`), so a separate overlay would need a layer
change and could go stale-shadowed. `sync_settings.sh` key `refract=`
(default off) materializes the level INTO installed `swaps.ptrefl/`
(off restores; materialize-always per the `43` stale-rung rule), refuses
loudly as `off:needs-ptrefl` / `off:rung-missing` / `off:no-such-level`, puts
the level's MANIFEST first line where the layer echoes it into the journal,
carries `refract=` in the cache stamp and journal line, and reports
`want_refract`/`req_refract` in status.txt. CET: selector "Glass refraction
experiment" in the PT panel + two warn lines (request≠state; selected but 0
refl swaps served). Sandbox-tested all five sync paths (serve eta20/eta15,
restore off, both refusals) against a fake HOME; `make check` clean.

Deployed 2026-08-31 17:15: `make install` + `build_refract.sh --install`;
installed ptrefl file cmp-verified against repo before any of this.

## 3. A/B protocol (one launch, eyeball)

Settings to state before the launch (`45`, memory rule): **PT Overdrive on,
tier=on, ptrefl=on, refract=eta20** first. Scene: a large window at night or
the bar glassware, camera oblique to the pane (head-on the bend is zero by
construction — grazing angles are where it shows).

- **PASS (warps):** the through-glass view shifts/warps vs the off control,
  strongest at grazing angles and through curved glass; no doubled edges.
  Then judge eta15 for look. Unlocks scoping v1 (second ray + Fresnel
  weight) — which NEEDS the consumer answer (§0) before it is built.
- **GHOSTS (doubled image, offset copy):** the consumer adds the buffer over
  the blended see-through. D3's ceiling is `20` §5b's "additive lensing
  sparkle" — record and stop.
- **NO CHANGE:** check status.txt `last_refl` count and the journal manifest
  echo (`ptrefl refract=eta20 sha=c96e…`). Served + traced but identical ⇒
  the transparent pass doesn't run on that object/render mode (`20` §6 FAIL
  branch) — try the other scene before concluding.
- **Reflection gone from glass while on:** expected, not a failure — Phase
  0.5 trades the mirror term for the bent term by design.

Predicted risks, pre-registered: the bent ray sees cullMask-255 instances
including proxy geometry (`ptbounce`'s known trade); interiors behind
windows may be unlit/absent in the BVH at any distance (tmax is cbv-driven,
`20` §3); the ε push-through may still self-hit on double-pane assets
(would read as black/garbage glass — report, don't tune blind).
