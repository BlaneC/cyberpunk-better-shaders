# 69 — V4 on screen: nose WINS, leaks RETURN (registered), and the look problem changes species

Written 2026-08-31, from the user's earglow k=0.22 launch (10:52, serve
verified sha=7424dcfde39de965, 0 rejects; settings pinned, 7935 s).
Captures `a-b-testing/earglow-v4/S{1-nose,2-leaks,3-ear}.png`
(= 105348/105604/105928). User: "Looks pretty good, subtle nose light up is
cool… but… Panam's neck seam at her clothes and hair strands are lit up
again… the illumination only comes from specific corners behind the ear…
like there's just a lightbulb tucked into one spot… BUT OVERALL ITS SO DARN
CLOSE."

## 0. Scorecard vs `68`'s table

| row | on screen |
|---|---|
| nose glows sun-side | **PASS** — "subtle nose light up is cool" (S1) |
| ear coverage up vs v3 | **PASS** — concha/crease region now solidly lit (S3); the one-sided gate did recover true positives |
| strands/collar RETURN | **FIRED** (S2 — hairline strands, collar seam). Registered outcome: v4 is the FIRST honest leak test (v3 killed these partly by the bias); standoffs at this range sit under ε_eff. Named successor applies: the s-band probe, no blind tightening |
| everything dead / sign error | did not fire |
| rim still dark | **partially fired** — see §1; but the dominant complaint is new |

## 1. The new finding: the look failure is now the TRANSFER, not the gates

S3: glow concentrates where thin-hit finds small t AND vis clears — the
concha corner — and cuts off hard everywhere else (hair-shadowed shell via
vis; rim entry points landing in hair; tattoo bands dark). Two structural
causes, both in-module math, neither a gate bug:

1. **Raw per-channel Beer–Lambert is too steep.** ld = 0.68–3.67 mm turns a
   2–3 mm thickness difference into a 3–20× brightness swing — thin spots
   become bulbs. Real tissue diffuses laterally several mm, flattening
   exactly these gradients.
2. **Binary gates make binary borders.** backlit and vis are booleans; the
   glow snaps on/off at their boundaries instead of feathering.

What is NOT fixable in-module: hair-occluded shell stays dark (vis is
doing correct physics — probe magenta), and there is no lateral pixel-space
blur available. A soft transfer + smooth envelopes reads as diffusion to
the eye regardless; a full dipole it will not be.

## 2. Two tracks proposed (BUILDS NOT YET DELEGATED — user asked for a take)

- **Track L (leaks): the s-band probe** (`68`'s named successor, reuses the
  paint machinery): paint sign/magnitude buckets of s/ε_eff at v2-gate
  pixels. Readout: do leak-s and true-s separate ANYWHERE? If yes → final
  calibration. If no → threshold-only is cornered; the honest residual
  options are (i) accept faint radiance-scaled sliver leaks, (ii) tighten
  only the flat-side term (ε₀+b·t) — strands over low-slope skin die while
  high-slope rims keep their allowance — the probe measures whether that
  split suffices.
- **Track D (diffusion look): transfer + envelope rungs.** (1) Replace raw
  exp with a diffusion-style profile (widened/sum-of-two exponentials per
  channel, tuned so t∈[1,6] mm spans ~2–3× not ~20×); (2) multiply by a
  smooth backlit wrap (smoothstep on −N·S) and optionally a forward-phase
  term on D̂·S so gate borders feather. Ship as an A/B ladder over the
  three registered ids: `earglow` = v4 control, `-lo` = mild soft, `-hi` =
  strong soft, all k=0.22 — one launch decides by eye.

## 3. Confidence

| claim | confidence |
|---|---|
| leak return is standoff<ε_eff, not a regression bug | **high** — registered outcome; gate verified in binary pre-launch |
| bulb look is transfer steepness + binary borders | **high** — S3 geometry matches; mechanism needs no new ingredient |
| soft transfer + wrap kills the bulb read | **medium-high** — standard technique; exact curves need the A/B |
| leak separation exists at some threshold | **unknown — the s-band probe measures it** |
