# 62 — Ear glow V2: built, validated, parked. Sun-visibility ray + albedo gate; NOT working until the screen says so.

Written 2026-08-31, worker fork, offline only. This is the (a)+(b‴) build
approved after `61` killed route (b)-as-specified. Everything here is
**built and validated, nothing is proven on screen**. Parked over the same
rung names (`skin.set/earglow{,-lo,-hi}`), so the existing `init.lua`
registration covers them — no config changes, nothing committed. Standing
selector stays `gi-50-bleed`.

## 0. What changed vs v1 (`59`), and only this

Two new validity terms AND-ed into the k select. Same three k rungs
(0.10 / 0.22 / 0.45), same gates, same constants, same Beer-Lambert, same
accumulator/write mechanics — the v1 splice is byte-recognisable in the
diff with the new logic threaded through it.

1. **(a) Sun-visibility ray from the entry point Q.** Q = thicknessOrigin +
   hitT·(−S) — the flesh's sun-side entry surface. An NEE-shaped trace:
   literal flags 12 (terminate-on-first-hit + skip-CHS: no CHS runs, so
   payload ABI is irrelevant — `61`'s finding cannot bite it), direction S,
   tmin/tmax the engine's own (1e-6 / 10000), missIndex 0, SBT (1,1,0),
   payload all-members-zeroed exactly as the engine pre-arms its own NEE
   (d622fb9e input `:3566-3574`). Visible ⟺ member 3 == 10000 after — the
   identical ms_empty handshake the engine's NEE uses. cullMask =
   `Select(gate ∧ thin ∧ similar, 39, 0)`: the ray is a near-free
   guaranteed miss unless it can change the answer. (A mask-0 miss reads
   "visible", but every such lane is already dead through the same AND at
   the k select — identity holds.)
2. **(b‴) Albedo-similarity gate.** The reference CHS family round-trips
   the hit's RGBA8 albedo in payload member 0 (`61` §2 codec). The
   thickness hit's albedo and the pixel's own (fresh chain+load on the
   radiance payload variable — module-scope, no dominance question) are
   unpacked with the module's own 1/255 codec and compared per RGB
   channel: all three |diffs| < **0.25**. **This is a thresholded
   heuristic, stated as such**: another character's skin passes
   (geometrically rare — needs a second head within 18 mm sun-side);
   skin-adjacent skin-toned material (leather collar dyed like the
   wearer) can pass; very dark skin against dark cloth may fail closed
   (glow lost where it was legitimate). The 0.25 came from the RGBA8
   quantisation scale, not from tuning on screen; if the A/B says the
   threshold is the problem, that is a REBUILD decision, not a knob.

**Self-hit policy at Q — mirrored, not invented.** The engine's NEE origin
is not P: it is P + `c0·N·clamp(0.005·√t,.005,.1)·[N.z>0] −
c1·D·(1+9·clamp(t/1000,0,1))` with c0/c1 from cbv[77].xy (input disasm
`:2626-2666`). The splice applies that exact construction at Q, with the
module's own cloned cbv chain (slot 77 in all 10 permutations, per-module
detected not assumed), N = the thickness hit's own decoded oct-normal
(payload member 1, the module's 12+12 codec), D = −S, t = thickness hitT.
Both terms push off the surface toward the sun for our geometry. The
patcher WALKS each module's own construction and dies on any shape
deviation (`find_origin_offset`); all 10 matched.

## 1. Failure modes land on identity, per term

| condition | mechanism | result |
|---|---|---|
| gates closed (non-skin / lit / bounce>0) | thickness mask 0 → miss → m3=10000 | thin=false → dead (v1 behaviour) |
| thickness miss / no-write | pre-arm m3=10000, m0=0 | thin=false AND albedo far → dead twice over |
| albedo differs (prop hit) | any channel diff ≥ 0.25 | similar=false → vis ray mask 0, k select dead |
| sun blocked at Q | vis ray hits: flags 12 → nothing writes payload → m3 stays 0 ≠ 10000 | visible=false → dead |
| vis ray fired with mask 0 (lane already dead) | miss writes m3=10000 ("visible") | harmless — same AND is false at the k select |

## 2. Evidence index

- Reference CHS payload codec + no-identity finding: `61` §2-§3 (the basis
  for (b‴) reading member 0 and for (a) not needing any CHS).
- Engine NEE pre-arm zeroing all four members: input disasm
  `dev/disasm/earglow/d622fb9e…spvasm:3566-3574`; handshake ==10000
  `:3583-3585`.
- Engine origin-offset construction: `:2626-2666`; cbv slot 77 chain
  `:2629`.
- Pixel-albedo liveness: radiance trace `:2290` (payload %22, inside the
  bounce loop, before the NEE at `:3583`); every store through any %22
  access chain is at or before `:2290` — asserted per module by
  `find_radiance_trace`, not by hand. The bounce==0 gate makes the read
  the bounce-0 CHS pack by construction.
- The emitted v2 splice, hand-read in full (d622fb9e id-preserving diff,
  263 lines, nothing outside the design): thickness trace flags 16 tmax
  0.018; 3 albedo compares vs %float_0_25; oct decode; cloned cbv[77]
  load; offset math; vis trace `flags %uint_12, mask Select(…,39,0),
  tmax %float_10000, payload = injected var`; `==10000` visible; triple
  AND into `Select(ok, k, 0)`; v1 Beer-Lambert and FAdd-composed writes
  unchanged, alpha preserved.

## 3. Validation (same bar as v1, all passed)

- 3 rungs × 93 modules; 77 dxil + 4 restirgi + 2 atomic refs cmp-verbatim;
  10 patched refs cmp-differ; spirv-val clean ×279.
- Emitted-code re-read from OUTPUT binaries, per module: trace count =
  base+2; exactly 1 flags-16 trace, tmax 0.018; flags-12 count = base+1;
  the new flags-12 trace has tmax 10000 AND the injected payload (cannot
  false-positive on the engine's NEE — different payload variable);
  exactly 2 `Select(…,39,0)` masks; exactly 3 albedo compares vs 0.25;
  `FOrdEqual ==10000` count = base+1; class-32 compare; 3 Exp; 1/ld and k
  constants; FAdd-composed writes.
- Per-module reports: uniform across all 10 — offset cbv slot 77,
  radiance payload found (%21 or %22 by module), 209-instruction splice,
  20+6 cloned ops.
- Parked = built verified by cmp across all 3×93; MANIFEST line 1 carries
  gi-50-bleed provenance verbatim (gi_refuse contract intact:
  ser=class, shadowset=full-shadow, ptreg ON / rcbm).
- d622fb9e sha256 (k=0.22): `fb8b753e727c280d…`.

## 4. Cost

Thickness ray: unchanged from v1 (mask-0 miss unless skin ∧ backlit ∧
bounce 0). Visibility ray: fires only on gated thin-skin pixels that also
passed the albedo gate; flags 12, no CHS, miss-or-terminate-first — price
it as ONE extra NEE-equivalent on the small set of pixels that can glow.
Straight-line splice, no new control flow anywhere.

## 5. PRE-REGISTERED interpretation table — read BEFORE the launch

Each of `60`'s five artifacts maps to exactly one gate, so a partial
failure is still diagnostic:

| on screen | verdict |
|---|---|
| necklace/collar/under-clothing glow GONE | (b‴) did its job (albedo differs; note the sun often DOES see the bead — (a) alone would not have killed these) |
| hair-seam and eye-corner glow GONE | (b‴) (dark albedo), often (a) too |
| occluded-ear glow GONE | (a) did its job (head blocks the sun from Q) |
| lit-skin crevice speckle GONE | (a) (crevice shadows Q) |
| backlit ears/noses against open sun STILL GLOW red, frame otherwise == gi-50-bleed | **PASS** — this is the feature |
| cheek-near-nose / brow same-instance crevice glow SURVIVES | **expected residue, not failure** — same albedo, sun visible at entry, thickness reads the crossing distance; defect 2/3 remnants are (b′)/(d) territory if the eye objects |
| ALL glow gone, including a staged backlit ear against open sky | (a)'s handshake or origin construction broken in the wild — do NOT tune, re-read the build (the ear's own Q must see the sun) |
| glow unchanged from v1 (props still glow) | gates not folded — build bug, `ab_launch_audit.py` then re-read the emitted diff |
| glow on non-skin, tile grid, or any `39`-class artifact | not this build's failure class — audit serve before touching anything |
| dark-skinned character loses legitimate ear glow | (b‴)'s documented fail-closed misclassification — a threshold/representation decision for the user, not a tuning knob |

A/B protocol unchanged (`45`): settings stated before launch, audit before
pixels, one variable = gi-50-bleed vs earglow rung.

## 6. What is still unproven (launch-only)

- Both new terms execute in the wild (the mechanism class is `56`/`60`-
  proven for this site+family, but the visibility ray is a SECOND injected
  trace per lane — untested count).
- Whether mirrored-offset Q actually clears self-intersection at 2 cm
  scale on real geometry (the engine's scheme at the engine's scales, our
  first use at ours).
- The albedo threshold's real-world separation (skin-vs-prop measured
  packs, not [0,1] theory).
- The look.

## 7. Registration

None needed: rung names unchanged, `init.lua` SKIN_LEVELS entries from
`59` §7 already cover `earglow-lo/earglow/earglow-hi`; `sync_settings.sh`
and `Makefile` untouched; parking IS deployment (sync reads
`~/.local/lib/callisto/skin.set` directly). Nothing committed.
