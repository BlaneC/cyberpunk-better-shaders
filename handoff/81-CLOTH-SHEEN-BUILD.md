# 81 — Cloth sheen (A2) built: two rungs off `-deep`, rough-dielectric gate, never launched (2026-08-31)

Feasibility, gate evidence and the two dead options: `80`. This doc is what
was built, what it measures offline, and how to A/B it.

## 0. State

**Built, verified, parked, deployed to the selector. Zero launches, no
verdict, no commit.** The rungs are default-off; the live selection is still
`gi-50b-bleed-oil-sheen-deep`.

| rung | what it is |
|---|---|
| `gi-50b-bleed-oil-sheen-deep-cloth` | the candidate, `k = 0.5` |
| `gi-50b-bleed-oil-sheen-deep-clothhi` | the louder half of the A/B, `k = 1.0` |

Both are the standing base **plus one variable**: a Charlie×Neubelt sheen
added at the 457 direct-light compute BRDF sites on rough dielectrics, with
the diffuse renormalised. The 16 raygens are **byte-identical to `gi-50bnd`**
(verified, 0/16 differ) — nothing about bounce light changed, and nothing
about skin changed.

## 1. Base — read this before rebuilding

The task brief named the base `gi-50b-bleed-oil-sheen-lumn`. **The standing
rung is `-deep`**, not `-lumn`: `78` §5.1 and `CURRENT.md` record `-deep`
winning on screen at 22:28 (*"Deepest band is actually the best skin shader
right now over lumn"*), the live `brdf_params.txt` selects `-deep`, and the
last logged launch served `skin_sha=f8f2890ebcd48252` = `-deep`. Only the
newest commit *message* still says `-lumn`. **Built off `-deep`.** To rebase
on `-lumn` instead: §7.

## 2. The gate (see `80` §2 for why)

```
gate  = (class != 1) && (class != 4) && (max3(F0) < 0.09)
wr    = saturate((alpha - 0.10) * 5.0)
sheen = k * D_charlie(a = 0.25) * V_neubelt * defres * wr,  clamped to 0.5
f_d  *= 1 - k * 0.0072 * wr
```

- class 1 = skin (already has its own fuzz from `72`/`73`), class 4 = hair —
  both excluded off the **same class word** the skin gate reads.
- `max3(F0) < 0.09` excludes every metal, glass, clearcoat and polished
  plastic.
- `wr` fades out smooth surfaces. `alpha` is the site's own alpha, provably
  equal to authored roughness² on any gate-true pixel.
- `defres` is the `74`-era weight `1 − β(1 − VoH)^5` that cancels the module's
  own Schlick ramp, via the exact identity `VoH = (NoL + NoV)/(2·NoH)`.
- **Concrete, plaster, wood and dirt get the lobe too.** By design, bounded.
  This is the thing the A/B has to look at (§5).

## 3. Calibration — `dev/cloth_model.py`

Sheen as **% of local diffuse**, dielectric `F0 = 0.04`, albedo 0.25,
authored roughness 0.70:

| k | head-on (v0, L50) | 45° (v45, L70) | grazing (v80, L70) | silhouette (v88, L85) | diffuse damp |
|---|---|---|---|---|---|
| 0.25 | 0.10% | 1.88% | 5.72% | 6.28% | 0.998 |
| **0.50** (`-cloth`) | **0.19%** | **3.76%** | **11.45%** | **12.57%** | **0.996** |
| 0.75 | 0.29% | 5.64% | 17.17% | 18.85% | 0.995 |
| **1.00** (`-clothhi`) | **0.38%** | **7.52%** | **22.89%** | **25.13%** | **0.993** |
| 2.00 | 0.77% | 15.04% | 45.79% | 50.27% | 0.986 |

Roughness ramp `wr` by material: glass 0.00, clearcoat 0.00, plastic 0.00,
leather 0.30, coated nylon 0.75, cotton/denim 1.00, wool 1.00, concrete 1.00.

**Anchored against the approved peach fuzz** (the `72` calibration anchors, as
the brief asked). Hemisphere distribution at k = 0.5 — median 0.64%, p90 5.7%,
max 80.1% — versus the shipped, on-screen-approved skin fuzz — median 0.72%,
p90 4.0%, max 79%. Statistically the same band, so k = 0.5 is "the level the
user already accepted on a face", not a guess. `-clothhi` at k = 1.0 doubles
it deliberately so the A/B has a loud half.

Directional albedo `Ê1 = 0.0072` (hemisphere mean); per-view `E1` spans
0.0013 (head-on) to 0.0232 (80°), so the worst residual energy error after the
flat damp is +0.80%.

Reproduce: `./dev/cloth_model.py --calibrate`, `--scan`, `--k 0.5 --rough 0.7`.

## 4. Verification — every number

Build (`dev/build_gi_bleed_sheen.sh`, k = 0.5), coverage gate is **fail-hard**:

    mods 77, peach_sites 457, cloth_sites 457, cloth_damp_sites 173,
    cloth_fd_sites 173, ggx_sites 473, defres_sites 457,
    skipped_shape 16, skipped_dom 0, skipped_dup 0,
    skipped_cloth 0, skipped_damp 0
    cloth k=0.500: 457 of 457 sites carry the cloth lobe (0 declined),
    diffuse damp at 173 of 173 Burley sites (0 declined)

| check | result |
|---|---|
| `spirv-val` on every patched module, both rungs | **0 failures** (93 modules each) |
| **gate-false byte-inertness** — rebuild at `k_cloth = 0` | **0 of 77 compute modules differ from the parked `-deep`** |
| raygens vs `gi-50bnd` | **0 of 16 differ** (bounce path untouched) |
| compute vs parent `real-gloss-bleedn-oilh-deep` | **77 of 77 differ** (the payload is there) |
| `dev/verify_cloth_sheen.py` on **shipped bytes**, `-cloth` | 457 cloth sites, 173 damp chains, **8696 points**, ALL CHECKS PASS |
| same, `-clothhi` | 457 / 173 / 8696, ALL CHECKS PASS |
| gate-false path inside the verifier | **exact float32 identity** at every sampled point |
| gate class values decoded off one class word | `[1, 4]`, single `OpShiftRightLogical` |
| all 7 emitted constants vs the model | exact (float32) |
| negative control: verifier on `-deep` | 0 sites, 2 coverage failures — as intended |
| `dev/verify_bleed_norm.py`, both rungs | 150 luminance-hold sites / 77 modules, constants exact, closed form matched at 120 points each |
| `dev/verify_gi_ladder.sh` (base, `--gi gi-50b`, `gi-50bn`, `gi-50bnd`) | **ALL CHECKS PASS**, `gi_refuse` provenance `src_ser=ser.set/class` OK for both new rungs |
| `make check` | ok |

Re-run the shipped-bytes verifier (note the `--k`; it defaults to 0.5, so
running it bare against `-clothhi` reports 459 bogus constant failures):

    ./dev/verify_cloth_sheen.py ~/.local/lib/callisto/skin.set/gi-50b-bleed-oil-sheen-deep-cloth
    ./dev/verify_cloth_sheen.py ~/.local/lib/callisto/skin.set/gi-50b-bleed-oil-sheen-deep-clothhi --k 1.0

The verifier re-parses the **shipped `.spv`**, not build intermediates: it
disassembles from `skin.set/`, finds the gate structurally (from
`OpLogicalAnd(not_skin_not_hair, OpFOrdLessThan(max3(F0), thr))`), peels the
term chain, and compares against a float32-exact closed form on an 8-point
NoV/NoL/NoH grid per site.

**Deployed:** `make install` at 23:38:50 (backup
`.callisto_backup/20260831-233850`), deployed `init.lua` **cmp-identical** to
the repo copy and carrying both new rows. The shader payload was already
parked by `--install` into `~/.local/lib/callisto/skin.set/`; only the CET
dropdown rows needed the Lua. `make install` does **not** touch
`brdf_params.txt`, swaps or caches.

## 5. A/B runbook — settings contract FIRST (the `45` rule)

Required, stated before the launch, never inferred after. This is the live
file with **one line changed**:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50b-bleed-oil-sheen-deep-cloth
    ser=class  ptreg=on  ptclamp=on  ptbounce=on  ptmsggx=on  refract=eta15

Game side, match across both halves and record it: **PT Overdrive on,
PT-in-photo-mode on, RR off, DLSS Balanced, RayTracedLighting Psycho,
2560×1440** (this is the state `79` verified for the 22:28 launch).

**Scene — this is the part that decides whether the launch is worth anything.**
`58` §5's gap was shooting the effect without a control surface in frame. Do
not repeat it:

- A **garment silhouette against a bright background** — jacket shoulders,
  a sleeve fold, a coat back, rim-lit. Grazing angles are where the lobe lives;
  a flat-on chest shot is a wasted launch.
- **A hard non-cloth reference in the same frame**: a painted wall, bare
  concrete, car paint, and road. These are the false positives `80` §2.3
  admits to. If they read wrong, the gate is wrong, and that must be visible
  in the *same* screenshot, not remembered from another one.
- **Pin the camera** (photo mode, do not move between halves) and shoot the
  identical frame on `-deep` as the control.

Ladder, one variable per step:

1. `-cloth` vs `-deep`, same camera. The claim: cloth silhouettes gain a soft
   grazing rim; everything else is unchanged.
2. Only if 1 is ambiguous: `-clothhi`, same camera. Doubling k should double
   the rim. If `-clothhi` is also invisible, the sites are wrong, not the
   amplitude.

## 6. Pre-registered outcomes

| observation | reading |
|---|---|
| cloth silhouettes gain a soft rim, walls/concrete unchanged to the eye | the feature, working — keep `-cloth`, test `-clothhi` for taste |
| **the wall / concrete / road glows at grazing** | **the gate is wrong** — this is the known false positive. Fix: raise `cloth_a0` (start 0.10 → 0.20) or lower `cloth_f0max`; do not just lower k, that hides cloth too |
| **nothing anywhere, at either k** | wrong sites — the direct compute path is not what shades that garment. Check `ab_launch_audit.py` for hit profile before concluding; if the profile matches `-deep`'s 77/10/15/3/4 the bytes ran and the answer is "these sites don't own cloth" |
| skin looks different | **bug** — skin is class 1 and is gated out; a skin delta means the class read is wrong. Kill the rung |
| metal/glass/chrome picks up a rim | **bug** — `max3(F0) < 0.09` failed; kill the rung and file the site |
| cloth reads chalky/washed rather than sheened | k too high, or the ramp is admitting too-smooth fabric — try `--k-cloth 0.25` |
| overall scene dims | the damp is over-applied — it should be 0.4% and invisible; a visible dim means `Ê1` is wired wrong |
| `-clothhi` looks identical to `-cloth` | the lobe is being clamped by `cloth_max=0.5` far more than modelled — re-run `cloth_model.py --scan` against the observed roughness |

## 7. Rebuild / retune

    ./dev/build_gi_bleed_sheen.sh --k-cloth 0.5 --install      # the candidate
    ./dev/build_gi_bleed_sheen.sh --k-cloth 1.0 --install      # the loud half

Knobs (`dev/patch_subtype_probe.py` KNOBS): `k_cloth` (0 = byte-inert),
`a_cloth` 0.25, `cloth_max` 0.5, `cloth_defres` 1.0, `cloth_a0` 0.10,
`cloth_a1` 0.30, `cloth_f0max` 0.09, `cloth_E` 0.0072, `cloth_damp` 1.0.

To rebase on `-lumn` instead of `-deep` (§1), point the build's base at the
`-lumn` rung and rebuild both; the patcher is base-agnostic.

## 8. Files

- `dev/patch_subtype_probe.py` — extended, not rewritten: `find_f0_triples`,
  `lift_f0_phis` (the `OpPhi` fixpoint that takes F0 coverage 376 → 457),
  `find_diffuse_scalars`, `_emit_ramp`, and the cloth emission inside
  `build_peach`.
- `dev/build_gi_bleed_sheen.sh` — coverage gate extended; build **fails**
  unless cloth sites == 457 and damp chains == 173, and unless every module
  agrees on `k_cloth` and the damp constant.
- `dev/cloth_model.py` — offline amplitude model (`--scan`, `--calibrate`,
  `--k`, `--rough`).
- `dev/verify_cloth_sheen.py` — shipped-bytes verifier, gate decode + closed
  form + census.
- Parked: `skin.set/gi-50b-bleed-oil-sheen-deep-cloth{,hi}/` (93 modules
  each); repo copies in `swaps.gi.50b-bleed-oil-sheen-deep-cloth{,hi}/`.
- `init.lua` — two selector rows, deployed via `make install`.

## 9. Unsure / not done

- **The cloth class is still unknown** (`80` §2.1). The gate is a physical
  proxy, not an identity. It will paint rough non-cloth dielectrics.
- **`Ê1 = 0.0072` is a hemisphere mean of the model, not of the shader.** The
  shader applies it flat × `wr`; per-view spread is 0.0013–0.0232. Residual
  energy error ≤ +0.80%, direction-dependent. Not worth a per-view E1 fit
  before the look is proven.
- **`sync_settings.sh` was deliberately not smoke-run** — it appends to
  `~/callisto_launches.log` (polluting the evidence trail) and mutates the live
  `swaps.skin/`. `skinspec` is a pure directory lookup into `skin.set/<name>/`
  with no hardcoded rung list, so the new names resolve by existing; and
  `verify_gi_ladder.sh`'s `gi_refuse` section re-checks the same provenance and
  passed for both. First launch is still the first real test of the plumbing.
- **Why no new `clothsheen=` key.** The cloth sheen splices into the **same 77
  compute module ids** as the skin overlay, and the layer serves the first file
  it finds for an id — so it cannot be an independent overlay dir stacked on
  top. It has to be a pre-built combined set, which is exactly what `skinspec`
  is. New key = new failure mode for zero gain.
- Nothing here has been on screen. Every number above is offline.

## 10. Verdict (2026-09-01) — LAUNCHED, KEPT, `-clothhi` is the default

The user ran both rungs over repeatable scenes, including the architecture
frames §8 asked for: *"I can see the difference if I'm looking closely enough
in some repeatable scenes... it just feels like everything looks better...
I've tried some repeated architecture scenes too but I SWEAR its better. I
prefer clothhi. clothhi is now my new defacto. It just feels better for like
every material somehow."*

Reading it against §8's pre-registered outcomes:

- **"Every material somehow" is the proxy gate working as designed**, not a
  leak — §2's gate paints all rough dielectrics, bounded, so a diffuse
  everywhere-better impression with no single locus is the predicted
  signature of a win. The two failure rows did NOT fire: no wall glow /
  chalky concrete reported (gate not too loose), and the effect was visible
  (sites not wrong).
- **k=1.0 beat k=0.5** — the calibration band (matched to the approved peach
  fuzz) was conservative by about half.
- Honest caveats: look-call, no pinned-frame control shot, serve not
  audit-verified (`./dev/ab_launch_audit.py` re-derives it from the layer
  journal if ever needed), settings not re-pinned for these looks.

§9's "Nothing here has been on screen" is superseded by this section.
