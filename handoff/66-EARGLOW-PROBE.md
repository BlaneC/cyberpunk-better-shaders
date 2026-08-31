# 66 — Ear-glow gate-attribution probe: built and parked

Written 2026-08-31. `65` left two inseparable suspects for the rim/ear-top
kill (flat-ε grazing vs tattoo-albedo) and its §1 tan-curve shows no flat ε
can work — so this is a **probe, not a v4**: one launch that paints WHICH v3
gate kills each pixel. Parked at `~/.local/lib/callisto/skin.set/probe-earglow`
(93 modules; d622fb9e sha256 prefix `bb5702337d39d803`). Nothing committed;
the standing look rungs (`earglow{,-lo,-hi}` = v3) are untouched — verified
byte-identical after the patcher change (§4).

## 1. What it measures — v3's gates, made independent

The v3 chain gates each term behind the previous one (consistency blocks the
thickness trace; cons+albedo block the vis ray), so a launch can't attribute.
Probe mode (same patcher, `--probe`) restructures:

- thickness trace fires on **class ∧ backlit ∧ bounce0** (not ∧ cons);
- vis ray fires on **that ∧ thin-hit** (not ∧ cons ∧ sim);
- consistency and albedo are computed but gate nothing — they're read out.

Per pixel with class ∧ backlit ∧ bounce0 ∧ thin-hit (m3 < 0.0179), ONE hue by
priority, additive over the radiance write (replacing the Beer-Lambert glow;
no k anywhere):

| hue | RGB add | meaning |
|---|---|---|
| MAGENTA | (3.2, 0, 3.2) | sun-vis ray FAILS (separates hair-overhang blocking from everything else) |
| YELLOW | (3.2, 3.2, 0) | vis passes; consistency AND albedo fail |
| RED | (3.2, 0, 0) | consistency fails only |
| GREEN | (0, 3.2, 0) | albedo fails only |
| BLUE | (0, 0.4, 3.2) | all pass — where v3 glows today (sanity) |
| *no paint* | — | pre-v3 gates never fired — itself a registered readout (nose row) |

Hues are mutually exclusive and exhaustive within the painted set by
construction (¬vis; then the four cons×sim combos).

## 2. Palette: the degeneracy check FAILED the spec'd values; floors dropped

Per `57` §5's lesson the palette was checked through AgX (standard minimal
fit: inset matrix → log2 [−12.47, 4.03] → sigmoid → outset) over the honest
painted-pixel background domain (backlit skin, camera side: shadow 0.05 →
GI-lit 0.8 → rim-spill 1.2). The spec'd 0.1 dead-channel floors only fed
AgX's ~8% inset crosstalk; and at bright test backgrounds that can't occur on
painted pixels (sun-facing skin fails backlit, sky fails class) every additive
palette collapses — restricting to the true domain is load-bearing, and is
why "adjust constants" suffices. **Final palette: dead channels exact 0.0**
(also keeps no-paint = +0.0 additive identity); dominants 3.2, blue keeps the
0.4 green guard. Worst-case post-AgX discriminant-ratio gaps on the domain:
magenta↔red 0.16, yellow↔green 0.14, yellow↔red 0.14, magenta↔blue 0.14
(0.2–0.4 in the realistic shadow/GI range). Reading rules: judge **hue, not
brightness**; on brightly spill-lit pixels the pairs compress — sample pixel
values in the capture rather than eyeballing; slivers are 1–2 px pre-denoise,
so zoom the capture (denoiser/DLSS smear is expected, any red/yellow presence
at a sliver is the readout).

## 3. Selection and staging (the probe path, `40` §7)

- Hand-edit `$GAME_DIR/.../mods/CallistoSSS/brdf_params.txt`:
  `skinspec=probe-earglow` — **before every probe launch** (init.lua coerces
  unknown names back to `off` afterwards; the settings-page WARNING is the
  confirmation it was served, not an error). NO init.lua change, NO CET
  registration. Contract unchanged: ser=class, shadowset=full-shadow,
  standing PT switches, **ptreg ON** (rcbm; `55` §5) — MANIFEST provenance is
  gi-50-bleed's verbatim so sync's refusal paths hold.
- Staging asks: (1) the `65` S2/S3 backlit-ear framing (V's tattooed ear AND
  ideally Panam's untattooed one, same sun); (2) the S4 strand/collar
  framing; (3) a sun-BEHIND-the-nose framing (65 §3 — S1's front-lit nose
  verdict is void). Settings stated in advance, same contract as every
  earglow launch.

## 4. Build and validation record

`dev/patch_earglow.py --probe` (new mode; palette + priority logic in
`PROBE_PALETTE`) driven by `dev/build_probe_earglow.sh`. Same splice, same
detectors, same two traces; only the two mask conditions and the payoff
change. Validation:

- 93 modules spirv-val clean; verbatim halves cmp'd; emitted re-read clean
  and baseline-aware: traces base+2, one flags-16 tmax-0.018, flags-12
  base+1 with tmax 10000 on the injected payload, exactly 2 cullMask
  selects, albedo 0.10 = base+3, consistency 2.5e-5 = base+1, Dot = base+2,
  **Exp unchanged from base** (no glow term leaked), LogicalNot = base+3,
  float-selects = base+18 (3 splice + 15 palette), palette constants
  present, FAdd-composed writes.
- Hand-read d622fb9e diff (7 hunks, 260 lines): thickness mask selects on
  g_a2 (`%12994` on `%12986`), vis mask on g_a2∧vd (`%13129` on `%13128`),
  cons `%12992`/sim `%13054`/vis `%13133` feed the five hue booleans
  (`%13137/40/42/44/46`), and all three channel select-chains match the
  palette matrix exactly. Nothing else touched.
- **Glow-path regression check**: after the patcher edit, all three v3 rungs
  rebuilt byte-identical to their parked binaries.
- Parked == built cmp-verbatim (93 + MANIFEST).

## 5. Pre-registered table — fill from the launch

| observation | attribution |
|---|---|
| ear helix rim/top paints RED | flat-ε grazing kill → v4a (one-sided adaptive ε) |
| tattooed ear (V) GREEN/YELLOW where untattooed (Panam) RED | albedo 0.10 kills tattooed skin → v4b |
| ear top MAGENTA | vis-ray blocked (hair overhang) — not ε, not albedo; vis policy decision |
| strand/collar slivers RED or YELLOW | required — consistency sees the leaks; ANY BLUE on a sliver ⇒ v3 attribution wrong, STOP |
| backlit nose wings paint NOTHING | pre-v3 gates never fire there — nose needs its own diagnosis |
| BLUE at ear crease | sanity — must match v3's survivor |

## 6. v4 pricing (offline reads; no second build in this pass)

**(v4a) One-sided slope-adaptive consistency.** Kill only when the re-traced
primary is IN FRONT of the raster surface by more than ε_eff: s = Δ·D̂ with
Δ = prehit − praster (already emitted) and D̂ the bounce-0 direction (loop
phi init, in scope); leak ⟺ s < −ε_eff (the occluder the rasterizer didn't
score is always nearer the camera). Behind-side mismatches survive
unconditionally — that alone removes roughly half the true-positive kills.

- **The footprint byte is NOT metrically decodable in-module — verified.**
  b = m1 bits 24–31 = FToU((1+slope·t)·510·φ) where φ is a **per-material
  texture sample** (`heap[registers[8]+matIdx]`, Lod 1, channel r; 0.0 when
  matIdx = 0xFFFF) — `chs_main_15` `:1276–1291`, pack `:1751–1754`. The
  receiving raygen has no material index, no UV, and no binding for that
  heap; m2 does not deliver φ separately (m2 = `%1490`, a ~6-term product of
  radiance scale × max-RGB, `:1700–1708`); and the raygen's own use decodes
  b/255 into a clamped **dimensionless** [0.25, 1] scalar (d622fb9e
  `:2610–2620`). No metric length exists to recover.
- **Fallback, fully addressable (priced route):** ε_eff = ε₀ + a·t_prim /
  max(|N·D̂|, c), capped. N = the primary hit's oct normal, which the module
  itself decodes (`%1703/%1705/%1707`, `:2606–2608`); t_prim = the radiance
  payload hitT (m3); a ≈ θ_px ≈ 1.1e-3 rad (65 §1's DLSS-Balanced figure —
  constant, or cbv-derived later). This reproduces the tan curve by
  construction: ~2, ~5, ~10, ~19 mm at 0°/70°/80°/85°.
- **Cap, from standoff geometry:** the leak's along-ray separation is the
  strand standoff over the same cosine, so the standoff/footprint ratio
  (≈5–30 mm vs 1.7 mm at portrait range, ≥3×) holds at every angle —
  ε_eff ≈ 1.5–2× footprint keeps margin everywhere; cap ~15 mm for
  θ→90° pathology. Honest residual: strands lying ON the skin (standoff
  ~1–2 mm) sit below ε_eff at any angle and could re-leak; `65`'s killed
  slivers were overhanging strands, so this is a registered risk, not a
  observed regression.
- **Cost:** ~6 instructions at the existing splice (one dot, one select or
  max for ε_eff, one compare replacing the FOrdLessThan); zero new fetches,
  zero new traces, no slot work. Same validation bar as v3.

**(v4b) Albedo handling.** If GREEN/YELLOW at tattoos: either (i) relax —
accept when consistency passes with margin (s > −ε_eff/2 ⇒ skip the albedo
test; ~2 ops), or (ii) drop the albedo term entirely and let consistency
carry the leaks (delete sim from the ok chain; leaks stay dead per `65` §0's
forced attribution — albedo was vacuous at leak pixels anyway). The V-band
case (`63`, never re-staged) is the only argument for keeping it; if the
probe's strand/collar rows come back RED-only and the band stays unverified,
(ii) is the cheaper and cleaner v4 companion.

## 7. Confidence

| claim | confidence |
|---|---|
| probe hues attribute the gates faithfully | **high** — same codepath as v3 with gates un-nested; hand-read |
| palette survives AgX on painted pixels | **medium-high** — numerical check on the honest bg domain; the fit is the standard approximation, not the game's exact LUT |
| footprint byte undecodable in-module | **certain** — encode+use both read; φ is CHS-side per-material |
| N·V fallback addressable | **high** — all values module-own, same dominance region as the unpack |
