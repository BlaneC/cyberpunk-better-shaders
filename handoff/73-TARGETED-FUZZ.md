# 73 — The blown rim was the module's own Fresnel. Cancelled, at the rim only.

Written 2026-08-31 14:58 on the user's A/B of `72`'s build:

> *"The sheen is a bit too blown out. Losing the nicer deep red we'd get.
> Want it more targetted? Can we make that the case for both the bleed-sheen
> and bleed-oil-sheen"*

Read as: the two rungs carrying the **added** lobe — `gi-50-bleed-sheen2` and
`gi-50-bleed-oil-sheen`. (`gi-50-bleed-sheen` is the 58-era multiplicative
rung, which measures 1.00–1.05× and cannot blow out anything; `72` §1.)

Both are rebuilt **in place**, so the CET selection the user is already
A/B'ing does not move. The 72-era builds are parked byte-for-byte as
`…-wide` and are selectable, because "targeted vs wide" is now itself an A/B.

## 0. Verdict

| question | answer |
|---|---|
| what was blowing out | the **backlit silhouette**, and it was not the lobe — it was the module's own Schlick multiply downstream of the splice. `F` is 0.028 in the front-lit sheen band and **0.87** at a backlit rim: a 30× amplification of a term that has nothing to do with Fresnel. |
| why that ate the deep red | that rim is exactly where the terminator bleed's red lives. An achromatic lobe at 780% of the local diffuse there is a white edge painted over it. |
| was the model wrong? | No — `72` §7.1 named this as risk 1 and pre-registered the lever. The on-screen read matched the predicted failure at the predicted pixels, which is the first time this feature's model has been confirmed by a launch. |
| the fix | multiply the lobe by `w = 1 − β·(1−VoH)^5` at the splice, β=1: cancels the Schlick ramp the lobe never asked for. Plus `peach_max` 1.0 → 0.5. |
| does it cost the effect? | **No.** The front-lit band (VoH ≥ 0.8) is weighted **1.00×** — the cheek/jaw response is unchanged to 4 decimal places. Hemisphere median 1.45% → **1.45%**, p90 8.0% → **7.9%**, max **781% → 159%**. |
| is VoH a new unknown? | No. `VoH = (NoL+NoV)/(2·NoH)` is exact for a unit bisector, and all three are already at the site. |

**Which rung was actually on screen.** `status.txt` from that launch reads
`want_skinspec=gi-50-bleed-sheen2`, `want_skin=on`, not refused — so the
read is of the **fuzz alone**, over `gi-50-bleed`, with the oil not in it.
The blowout is attributable to the added lobe with no confound, and the oil
rung has still never been looked at. The live `brdf_params.txt` still selects
`gi-50-bleed-sheen2`, which now resolves to the rebuilt bytes: **no setting
has to change to see the fix, only a relaunch.**

## 1. What the user saw, in the model's own coordinates

`dev/fuzz_model.py --scan` on the 72-era constants puts the maximum at
**view 88°, light 88°, azimuth 190°** — light behind the head, view grazing,
i.e. a rim-lit silhouette — at **781% of the local diffuse** (absolute
0.0217, against ~0.05 for a lit face: a genuinely bright edge). The
front-lit band it was calibrated on peaks at 35%.

The ratio makes the mechanism unambiguous. The added term is
`k·min(raw,cap)·NoL·F` and the diffuse is `albedo/π·NoL`, so

    fuzz / diffuse = k · min(raw,cap) · F · π/albedo

— **`NoL` cancels**. The entire 35% → 781% swing across the face is `F`
(and the cap saturating `raw`). Nothing in the sheen lobe varies over that
range; the Fresnel does all of it.

## 2. The weight

At each site, after the cosines are saturated:

    VoH = clamp( (c0 + c1) / max(2·NoH, 1e-6), 0, 1 )
    w   = 1 − β·(1 − VoH)^5
    spec' = spec + select(class 1, k · min(lobe, cap) · w · cos_site, 0)

**VoH is exact, not estimated.** For a unit bisector `L + V = 2·(V·H)·H`;
dotting with `N` gives `NoL + NoV = 2·VoH·NoH`. Two consequences worth
stating: the expression is **symmetric in the two cosines**, so the
NoL/NoV labelling ambiguity `_fold_cosine` has to work around does not
exist here — it is exact at all 457 sites, the 56 cheap-Vis ones included;
and the numerator vanishes with the denominator, so the quotient stays
finite in the limit the `NMax` guard protects.

Net weight `F·(1−p5)` against `F` alone:

    VoH  |    p5      F     F*(1-p5)   ratio
    1.00 |  0.0000  0.028    0.0280    1.00x   <- front-lit sheen band:
    0.80 |  0.0003  0.028    0.0283    1.00x      UNTOUCHED
    0.70 |  0.0024  0.030    0.0303    1.00x
    0.50 |  0.0312  0.058    0.0566    0.97x
    0.30 |  0.1681  0.191    0.1592    0.83x
    0.10 |  0.5905  0.602    0.2465    0.41x   <- backlit rim: cut
    0.05 |  0.7738  0.780    0.1765    0.23x

The product peaks at **0.2465** (VoH ≈ 0.1) against **0.87** unweighted —
a 3.5× cut confined to the rim, and the peak is now *interior*: the effect
falls off on the last degrees of silhouette instead of running away there.
With the oil's reshaped Fresnel (exponent 4) the same weight gives 0.45×
at VoH 0.1 and 0.24× at 0.05, so **the fix works on both rungs**, which is
what was asked.

`peach_max` 1.0 → 0.5 is the second half. The cap binds only where
`D_charlie·V_neubelt > 0.5`, i.e. past ~80° of view; it takes the worst
pixel from 311% to 159% and leaves every cell of the front-lit table at or
below its 72-era value.

### What changed on the face, in full

`ADD vs diffuse, phi=0` (the front-lit band), 72-era → shipped:

    view |  L=10   L=30   L=50   L=70   L=85
      0  |   0.0     0.1     0.6     1.4     2.3      all identical
     30  |   0.3     1.0     2.0     3.5     4.8      all identical
     60  |   1.4     2.7     4.7     7.7    10.9      all identical
     80  |   2.6     4.3     7.3    13.5    27.0 -> 17.6
     88  |   3.1     5.0     8.5    17.7    35.2 -> 17.6

Three cells move, all of them past 80° of view. Everything the fuzz was
built to do is bit-for-bit the same response.

Hemisphere, `k=1.0`: median **1.45% → 1.45%**, p90 **8.0% → 7.9%**, max
**781% → 159%**, absolute worst-pixel add **0.0217 → 0.0088**.

## 3. Cost and wiring

10 instructions per site (β=1 needs no constant and no multiply — the
`_emit_defres` fast path), plus one `OpFMul` into the added term: 11 over
the 15-instruction lobe. From the shipped `03dc7a51279e7427.dxil.spv`:

    %840 = NMin %839 %float_0_5          <- lobe, capped (peach_max)
    %841 = OpFMul %840 %float_1          <- k_peach
    %842 = OpFAdd %685 %663              <- NoL + NoV
    %843 = OpFAdd %786 %786              <- 2*NoH
    %844 = NMax %843 %float_9_99e-07     <- division guard
    %845 = OpFDiv %842 %844              <- VoH, exact
    %846 = NClamp %845 %float_n0 %float_1
    %847 = OpFSub %float_1 %846
    %848 = OpFMul %847 %847
    %849 = OpFMul %848 %848
    %850 = OpFMul %849 %847              <- (1-VoH)^5
    %851 = OpFSub %float_1 %850          <- w
    %852 = OpFMul %841 %851              <- lobe * w
    %853 = OpFMul %852 %663              <- the site's OWN light cosine
    %854 = OpSelect %302 %853 %float_n0  <- class-1 gate
    %855 = OpFAdd %825 %854              <- into the site's own specular
    ...
    %858 = NMin %857 %float_100          <- the module's firefly clamp, downstream

`%663` is the same cosine the lobe's `V_neubelt` consumes and the same one
the site folds into `D` — the fold and the weight cannot disagree, and the
whole added term still dies at the site's own terminator and under its own
clamp. The two `NMax`/`NClamp` guards are division and domain guards on
values that are already 0 in the added term wherever they bite.

## 4. Build and verification

    peach coverage: 77 modules, 457 sites over 473 GGX sites,
                    16 skipped_shape, 0 skipped_dom, 0 skipped_dup
    mode add: 401 fold the site's own light cosine, 56 fold min(c0,c1),
              16 cosine(s) clamped
    defres 1.00: the Schlick ramp is cancelled at 457 of 457 sites

The last line is a **new gate**, not a printout: the build fails if the
modules disagree on β, or if any site takes the lobe without the weight.
A partial weight would leave the blown rim on part of the face while the
byte count moved anyway — the `42` rule applied to the new term.

`./dev/verify_gi_ladder.sh gi-50-bleed gi-50-bleed-oil gi-50-bleed-sheen2
gi-50-bleed-oil-sheen gi-50-bleed-sheen2-wide gi-50-bleed-oil-sheen-wide`
→ **ALL CHECKS PASS**: equal file lists, **0 of 16 raygens differ from
gi-50** in all six, 77/77 compute deltas on all 15 pairs, `gi_refuse`
provenance clean (this run against the live `swaps.ptq/`, since the game
has been launched since `72`). Both new builds differ from their parked
`-wide` twin in **77 of 77** compute modules.

Deployed 14:57 (`make release && make install`, backup
`20260831-145754`); the game's `init.lua` is byte-identical to the repo's.

## 5. What did NOT change

- `k_peach` stays **1.0**. The complaint was the peak, not the level, and
  the front-lit band was the one thing the 72-era rung got right. Dimming
  `k` would have cost the cheek sheen to fix a rim.
- `a_peach` stays 0.35; the lobe's shape is untouched.
- The oil is untouched — `gi-50-bleed-oil` is the same bytes as before, so
  the ladder's oil-only rung still isolates the oil.
- `--peach-mode mul` ignores `defres` entirely, so the 58-era rung stays
  reproducible.
- The class gate, the cosine fold, the saturation and the dup guard are all
  as `72` §2 left them.

## 6. The A/B

Settings, stated before the launch (the standing rule). Unchanged from
`72` §6 — and check `skin` first, since a control launch leaves it off:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50-bleed-oil-sheen   ser=class
    ptreg=on ptclamp=on ptbounce=on ptmsggx=on ptrefl=on

Game side: PT on, PT-in-photo-mode on, **RR off**, DLSS Balanced,
RayTracedLighting Psycho, 2560×1440.

Shoot **a backlit or rim-lit face** — that is the only geometry that
changed. A front-lit A/B against the 72-era build will show nothing, and
that is the prediction, not an excuse.

1. `gi-50-bleed-sheen2` (targeted — already selected) vs
   `gi-50-bleed-sheen2-wide` (the 72-era bytes just looked at), same camera.
   Pre-registered: the white edge on the backlit silhouette is ~2.5× dimmer
   and the bleed's red reads through it; the lit cheek is identical. Then
   `gi-50-bleed-oil-sheen` for the oil, which no launch has seen yet.
2. If the red is back but the fuzz is now *too* quiet on the rim,
   β is a dial, not a switch — `--set defres=0.5` is the half step.
3. If the red is still washed, the next lever is **not** more β (β=1
   already cancels the whole ramp): it is tinting the lobe warm, §7.

## 7. Risks and levers left

1. **β=1 is the end of this lever.** The remaining rim energy is the sheen
   lobe's own grazing ramp (`V_neubelt`), which is the physics of sheen —
   cutting it further means `peach_max` (a clip) or `k` (a global dim).
2. **The fuzz is still achromatic.** If the complaint after this launch is
   still "it desaturates the red", the honest fix is a warm tint, and that
   needs the per-channel splice `72` §8.5 prices — the scalar splice cannot
   express a hue.
3. The Schlick exponent is assumed to be 5 (vanilla) at the splice. Under
   the **oil**, the module's own exponent is 4, so `w` slightly over-cancels
   there (net 0.45× vs 0.41× at VoH 0.1 — a smaller cut than vanilla, in
   the direction that keeps the oil visible). Matching the oil's exponent
   is possible and not worth an instruction until a launch asks for it.
4. Two more selector entries now exist (`…-wide`). They are the A/B, not
   the ladder; when the rim question is settled, delete both.
5. Nothing is committed. The look claim is still unlaunched.

## 8. Files

| file | change |
|---|---|
| `dev/patch_subtype_probe.py` | `_emit_defres` (the weight, with the VoH identity derived in its docstring); `defres` knob, default **1.0**; `defres_sites` in the report; `peach_max` default 1.0 → **0.5**; the 72-era Fresnel claims in `build_peach`'s docstring corrected |
| `dev/build_gi_bleed_sheen.sh` | ships `--set peach_max=0.5 --set defres=1.0`; coverage gate fails on a β disagreement or a site without the weight |
| `dev/fuzz_model.py` | `defres` in `evaluate()`; §5 prints the net-weight table; `--defres` flag |
| `init.lua` (+ release copy, deployed) | v3 labels; the two `…-wide` entries |
| `swaps.gi.50-bleed-{sheen2,oil-sheen}` (+ `skin.set/`) | rebuilt targeted |
| `swaps.gi.50-bleed-{sheen2,oil-sheen}-wide` (+ `skin.set/`) | **new** — the 72-era bytes, parked |
