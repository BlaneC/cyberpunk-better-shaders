# 67 — Probe on screen: BOTH v3 gates kill the ear, and the cons compare fails FLAT-ON at range

Written 2026-08-31, from the user's probe-earglow launch (09:29, serve
verified: skin_sha=2250eeae61e2e456, 0 rejects; settings pinned 08:53,
2808 s before first capture). Captures `a-b-testing/probe-earglow/`:
S1-night (093232), S2-nose-sun (093314), S3-panam-front (093402),
S4-panam-ear (093453). Hues read per `66` §2's rules — sampled 7×7 pixel
means, not eyeballed. The probe instrument itself behaved exactly as built
(night "chemlights" = the paint is deliberately NOT sun-scaled; the look
rungs are, so no chemlights in any look build).

## 0. Sampled evidence (RGB means, ratio R/G/B)

| site | RGB | read |
|---|---|---|
| S4 ear rim band ×2 | (104,47,**0.0**), (109,41,**0.0**) | **YELLOW** — B crushed to exact zero; cons AND albedo fail |
| S1 night face/nose/chest ×3 | (207,81,78) etc., G≈B | **RED** — cons fails ALONE, flat-on, ~2 m |
| S3 cleavage bottom | (192,66,132), B>G | **MAGENTA** — vis fails (torso blocks sun: CORRECT) |
| S2 far nostril / chest | warm, weak | magenta per user's read; sample coords partly missed |
| S4 neck mid-back | (213,173,135) neutral | **NO PAINT** — thin-hit correctly rejects thick geometry |
| S2 sunward nostril | user-reported **BLUE** | all gates pass at close range |

## 1. Filled attribution table (vs `66` §5)

| registered row | verdict |
|---|---|
| ear rim paints RED | **NO — YELLOW.** Both new gates are guilty at the target; v4 needs BOTH fixed |
| tattoo GREEN vs untattooed RED | not staged; moot — albedo fails on Panam's PLAIN ear rim, so 0.10 overreaches regardless (same-skin far-side compare, or hair draped behind the ear) |
| ear top MAGENTA | present as fringe at the hair seam — vis blocked by hair, physics-correct; ACCEPTED for v4 (hair-covered ear tops don't glow in life either) |
| slivers RED/YELLOW required | not re-staged this launch — carried, see §3 risk |
| nose paints NOTHING | **FALSIFIED, happily** — nose fires; sunward nostril is BLUE (v3 would glow there, attenuated); far nostril magenta = vis correctly refusing a through-the-nose path |
| BLUE at crease sanity | not resolvable by point sample; v3's on-screen crease glow already proves a pass-locus existed |

## 2. The finding that rewrites v4: cons fails FLAT-ON at ~2 m

`65` §1's grazing theory predicted angle-dependent kills. The night frame
falsifies it as the WHOLE story: a flat-on face at portrait range paints
RED — consistency alone failing where Δ should be ~1 mm of self-hit slide.
Every on-screen datum then fits ONE shape: **Δ carries a systematic
distance-scaled bias**, ballpark 3–5 mm/m —

    fails: flat face ~2 m (night), ear rim ~1.5–2 m (day, + albedo)
    passes: sunward nostril <~1 m (BLUE), v3's crease line (borderline range)

Candidate sources (offline read decides): the raster depth linearization
(cbv[59]) vs the projection the re-trace direction is built from; a jitter
term present in one path and not the other; the self-hit offset landing in
only one of the two compared points. The code names the sign and scale —
that read is MANDATORY before v4's constants are set (`64` §8's
dump-the-triples row, finally actionable).

**Corollary: v3's strand/collar kill may have been pure bias, not standoff
discrimination** — at 1.5–2 m the bias alone exceeds 5 mm, so EVERYTHING
died there, leaks and truth alike. The real leak-vs-truth separation at
portrait range is unmeasured until the bias is removed.

## 3. v4 spec (build; delegated)

1. **Offline first**: re-read the unprojection chain vs the re-trace
   construction in the deployed binary; identify the systematic term, its
   SIGN, and whether it is removable in-module (correct the compare) or
   only calibratable (fold into ε_eff).
2. **One-sided, distance-aware gate**: s = Δ·D̂ (leaks are always in
   front); kill only when s exceeds ε_eff = ε₀ + b·t (+ slope term
   a·t/max(|N·D̂|,c), capped) on the leak side — constants from the code
   read, sanity-checked against §2's pass/fail geometry.
3. **Albedo back to 0.25** — v2's value, under which every ear glowed. The
   V-band (still unverified) does not justify killing plain-skin ears; if
   it returns, it gets its own measured pass. Albedo is vacuous at leak
   pixels (`65` §0), so leaks stay dead via cons regardless.
4. Vis ray and thin-hit: UNCHANGED — the probe shows both doing correct
   physics (magenta cleavage/far-nostril, unpainted thick neck).
5. **Registered risk**: with the bias removed, strand/collar standoffs at
   portrait range may sit near ε_eff — the leak rows MUST be re-staged in
   the v4 launch; if they return, the separation is measured (not blind-
   iterated) via the probe's successor.

## 4. Confidence

| claim | confidence |
|---|---|
| ear kill is cons AND albedo jointly | **certain** — B=0.0 yellow, two sites |
| cons fails flat-on at range | **certain** — three night samples, G≈B red signature |
| distance-scaled bias explains all pass/fail loci | **high** — one parameter fits five observations; source not yet read |
| vis/thin gates physics-correct | **high** — magenta + no-paint land exactly where anatomy says |
| v2-level ear glow recoverable by v4 | **medium-high** — gates identified; constants pending the code read |
