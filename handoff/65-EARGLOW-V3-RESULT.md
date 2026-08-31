# 65 — Ear glow v3 on screen: the leaks are DEAD, and the gate is eating the feature

Written 2026-08-31, from three user launches (08:43 `earglow` k=0.22, 08:47
`earglow-hi` k=0.45, 08:53 `earglow` again). User verdict: strands + collar
fixed, "better than nothing", but the glow is "super super subtle" — one thin
line at the lower-behind of the ear, nose dark, and **hi mode looks the same
as normal**. That last observation is the diagnostic of the launch.

Captures: `a-b-testing/earglow-v3/S1-face-k22.png` (084433),
`S2-hi-k45.png` (084955, inside the hi window — the user's own un-captioned
A/B), `S3-ear-k22.png` (085505), `S4-fixproof-k22.png` (085855) +
`UserSettings.atshoot.json`. Serve verified for all three launches (0
rejects, manifests correct, k=0.22/0.45/0.22). Settings: the live file
was rewritten 08:53:03, INSIDE the shoot window — but the frozen snapshot
diffs key-for-key identical (0 keys) against `earglow-v2`'s 08:03 snapshot,
so the write was the game rewriting its own file at the third launch, and
all four captures ran under the contract stated in advance. Pinned in
substance; the mid-shoot mtime is recorded here so nobody trips on it.

## 0. Scorecard vs `64` §8's pre-registered table

| registered row | on screen |
|---|---|
| temple strands GONE ⇒ consistency gate | **CONFIRMED** (S4) — albedo is vacuous at leak pixels (`63` §1), so the attribution is forced |
| collar top edge GONE ⇒ same | **CONFIRMED** (S4) |
| V's forehead band | **NOT RE-STAGED** — unknown, carry forward |
| PASS row (backlit ears/noses glow) | **FAILS** — ear = one crease line (S2/S3), nose dark (S1) |
| ALL dead incl. staged ear ⇒ dump triples before touching ε | **NEAR-INVOKED** — not all dead, but the survivors are a sliver; the row's instruction (measure, don't tune) governs |

k-invariance (S2 vs S3, 2× k, same sliver): the missing glow is **gated
off, not dim**. No k tuning could recover it — `59` §6's "do not tune k"
is vindicated by the user's own rule-break.

## 1. WHERE the glow survives is the mechanism fingerprint

Survivor: the concave ear-head crease + concha bowl — the view-STABLE part.
Dead: helix rim, ear top, nose wings — the near-SILHOUETTE parts, i.e.
exactly where backlit transmission lives. The consistency gate compares two
points on (nearly) the same view ray, so |Δ| ≈ along-ray depth mismatch.
On a true positive that mismatch is sub-pixel-offset × surface slope:

    θ_px ≈ 95°/2560 ≈ 6.5e-4 rad; DLSS Balanced renders ~0.58× → ~1.1e-3 rad
    footprint at t=1.5 m ≈ 1.7 mm flat-on … × tan(grazing):
      70° → ~4.6 mm   |   80° → ~9.5 mm   |   85° → ~19 mm

ε = 5 mm therefore kills every portrait-range pixel steeper than ~70° — the
helix rim and nose wings live at 70–90°. The gate's false-kill rate is
**structurally anti-correlated with the effect**. A flat ε cannot be both
above this curve at rims and below strand standoff at slivers; tuning ε is
not a fix, it is choosing which failure to keep.

## 2. Second suspect, from `64` §5's own envelope: ALBEDO at 0.10

S3's ear is **tattooed** (dark bands on the helix). The albedo compare is
thickness-hit vs primary; a tattoo boundary on either side breaks it —
`64` §5 pre-declared exactly this failure ("tattoo boundaries fail closed
as patchy glow"). So the ear-top kill has TWO live suspects (grazing-ε,
tattoo-albedo) and this launch cannot separate them: both changed in v3.

## 3. The nose (S1) is partly a staging artifact

S1's face is front-lit (sun up-front-left). Transmission needs the sun
BEHIND the feature; on this framing most nose pixels fail `N·S≤0` **by
design**, and the vis-ray from Q may legitimately terminate inside the
face. The nose verdict needs a sun-behind-the-nose staging. Do not count
S1's dark nose as a v3 regression — v2 was never baselined on this framing
either.

## 4. Fix routes — and the registered protocol says MEASURE first

- **(P) Attribution probe — RECOMMENDED, one launch.** On pixels passing
  v2's gates, paint which v3 gate kills: RED = consistency only, GREEN =
  albedo only, YELLOW = both, BLUE = both pass. Selected via
  `brdf_params.txt` like `probe-both` — no CET registration, no init.lua.
  Single-hue readout (57's merge lesson respected). Table in `66`.
- **(v4a) One-sided slope-adaptive ε** (post-probe, if RED at rims): kill
  only when the re-trace hit is IN FRONT of the raster surface by more than
  ε_eff (leaks are always in front — the occluder the rasterizer didn't
  score); ε_eff scales with the engine's own slope-inflated footprint,
  already delivered per-hit in payload m1 bits 24–31 (`64` §6's byte — the
  thing that was useless as a mask is exactly a per-pixel ε). Cap TBD from
  the probe's Δ buckets.
- **(v4b) Albedo handling** (if GREEN at rims/tattoos): relax 0.10 where
  the consistency gate passes with margin, or drop the albedo term for
  ear-class geometry entirely and let consistency carry leaks. Depends on
  whether the V-band case (never re-verified) still needs 0.10.
- **Blind v4 (tune ε to 10–15 mm): REFUSED.** §1 shows no flat ε works;
  `64` §8's near-invoked row forbids it.

## 5. Confidence

| claim | confidence |
|---|---|
| leak kill is real and consistency-attributed | **certain** — S4 + vacuity argument |
| missing glow is gated, not dim | **certain** — k-invariance S2/S3 |
| grazing-footprint math explains the rim kill | **high** — survivor/dead map matches the tan curve; not pixel-proven |
| tattoo-albedo contributes at the ear top | **medium** — S3 tattoo visible; separable only by the probe |
| S1 nose is staging, not regression | **medium-high** — sun geometry read from shadows |
