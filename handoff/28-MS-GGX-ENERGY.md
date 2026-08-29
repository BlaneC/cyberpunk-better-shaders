# 28 — Diffuse metal energy restoration (MS-GGX energy compensation, `23` T2.1)

The first tier-2 item from the PT brainstorm, and the first feature in a while
to go blocker → build → launch → **confirmed on screen** with nothing going
wrong in between. Rough metal in Cyberpunk renders darker than it should
because the path tracer's GGX lobe only counts light that bounces off *one*
microfacet; this multiplies the lobe by a compensation term that puts the lost
energy back. It is the commit titled "Diffuse metal energy restoration"
(2026-08-28), switch `ptmsggx`, combo letter `m`.

**Confirmed on screen 2026-08-28** by a single-variable A/B — one launch with
`m` on against four with `m` off, everything else held fixed (§6). The user's
verdict: "It completely worked." Default flipped **on** after that
confirmation.

The full derivation, the E_ss blocker saga, and the fit diagnostics live in
`dev/MS_GGX_NOTES.md` §2. This file is the handoff-level record.

---

## 1. What shipped

| | |
|---|---|
| patcher | `dev/patch_ms_ggx.py` (`--strength`, `--arms {punctual,area,both}`, `--report`) |
| build | `dev/build_ptq.sh` — `m` joins the tier-1 matrix, now 15 combos; `MSG=1.0` is the compile-time strength |
| install | `dev/install_ptq.sh` (mechanism unchanged, `COMBOS` widened) |
| gate | `sync_settings.sh` — `ptmsggx`, combo letter `m` (order `r,c,b,m`) |
| toggle | CET → Callisto SSS → Path tracing → "Rough-metal energy compensation" |
| default | **on** (flipped after confirmation; shipped 2026-08-28 initially off pending the on-screen check) |

`m` cannot be its own overlay: it splices the same twelve `rgs_reference_main`
permutations as T1.1/T1.2/T1.4, and the layer serves the first file it finds
per id. `build_ptq.sh` therefore chains `patch_ms_ggx.py` over
`patch_pt_quality.py`'s output inside each combo, so the two edits compose in
one module.

## 2. The defect

Single-scattering GGX discards every light path that reflects off a second
microfacet before leaving the surface. At high roughness that is most of the
energy, so rough metal comes out dark and matte — it reads as a *diffuse*
surface with a faint sheen. Measured on the game's own lobe (directional
albedo relative to the lobe's own mirror limit, `dev/fit_ms_ggx.py`):

| α | NoV=1.0 | 0.75 | 0.50 | 0.25 | 0.10 |
|---|---|---|---|---|---|
| 0.05 | 1.010 | 0.999 | 0.977 | 0.907 | 0.715 |
| 0.25 | 1.040 | 0.971 | 0.855 | 0.666 | 0.512 |
| 0.50 | 0.936 | 0.858 | 0.768 | 0.671 | 0.611 |
| 1.00 | 0.575 | 0.620 | 0.673 | 0.736 | 0.778 |

The NoV=1 column is the roughness-driven loss this feature compensates: at
α=1 the lobe returns 0.575 of its mirror-limit energy — a shortfall of
`1/0.575 − 1 = 0.738`, i.e. **+66% missing specular on an F0=0.9 metal** and
+3% on an F0=0.04 dielectric.

## 3. The compensation — measured, not borrowed

```
a    = roughness * roughness
loss = j0*a + j1*a^2 + j2*a^3 + j3*a^4
comp = 1 + strength * F0 * max(loss, 0)

j0 = -0.35581642, j1 = 0.66852058, j2 = 0.82793009, j3 = -0.40552339
```

max abs err 0.0064, rms 0.0024 over α ∈ [0,1]. Three properties are
load-bearing:

- **It is fit to *this game's* lobe, not to a correct GGX.** The engine's
  `Vis` uses the *sum* of the two Smith-Schlick G1 denominators where a
  correct separable Smith uses their *product*, which over-brightens at high
  roughness and accidentally recovers about half the multiple-scatter loss
  already (0.575 vs a correct GGX's ~0.31 at α=1). A textbook
  Lazarov/Karis fit spliced here would roughly **double-compensate** and blow
  out every rough metal in the game.
- **Every term carries a factor of α**, so `loss(0)` is identically 0 by
  construction and smooth surfaces are mathematically untouched, whatever the
  fit error. `max(loss, 0)` clamps the small negative dip near α=0.25 so
  compensation never darkens below vanilla.
- **It is normalized against the lobe's own α→0 limit, which is exactly 0.5**
  analytically (independent of NoV; confirmed to 1.2e-5 by `--self-check`).
  That choice makes any constant scale error in the lobe cancel exactly — the
  reframing that unblocked the feature after weeks of chasing the absolute
  normalization (`GOTCHAS`: "absolute normalization is often avoidable").

At `--strength 0` every coefficient is exactly 0.0 and the splice is the
identity — the same regression discipline as tier 1.

## 4. What it deliberately does NOT fix

The same sum-vs-product substitution also costs up to 28% at **grazing**
angles (the 0.715 at NoV=0.1, α=0.05 in §2's table, where a correct GGX holds
0.91). That error is *larger* than the roughness one, but it is a different
defect: compensating it would re-light every grazing surface in the game. The
fit is α-only, evaluated at NoV=1, on purpose. The switch's tooltip says so.

## 5. The splice

Anchor: the Schlick spherical-gaussian Fresnel fit (constants `5.55472994` /
`−6.98316002`, mode-independent — GOTCHAS 4), whose three `F·(Vis·D)`
products share one `Vis·D` operand. Splice point is per-channel because F0 is
per-channel; F0 is read out of the module's own `%om · F0_c` multiplies, and
α is read off the Vis chain's trailing `+ α` and cross-checked against its
`(1 − α/2)` factor — a block where the two readings disagree is not this lobe
and is skipped.

The raygen carries **two structurally identical GGX evaluators**, selected by
`(flags & 2) == 0` — punctual and area/tube. Reading the wrong one is what
produced the E_ss blocker (the area arm's "NoL" is a sphere/tube illuminance
factor and its spec weight carries Karis's `(α/α′)²` normalization). Both are
classified by exactly that test and **both are patched**: the compensation is
a function of α only, so it does not depend on what fills the NoL slot — and
Cyberpunk is full of tube and sphere lights, so patching only the punctual arm
would brighten rough metal under a spotlight but not under a neon strip.
`--arms` exists so the two halves can still be A/B'd offline.

Per module: 6 blocks (3 punctual + 3 area), 18 uses rewritten, ~8 ALU shared
per block plus 3 per channel, **+2152 bytes** on every patched module.

**Coverage: 10 of 12 permutations.** `40c6faab52a13874` and
`ab7f1822eeb0331b` assemble a *monochrome* specular (`p · Vis · D`, no `1−p`
lerp, no F0 anywhere in the lobe). `comp` needs the lobe's own F0; borrowing
one of those modules' two unrelated `+0.04` triples would be a positional
guess of exactly the kind GOTCHAS 10 is about. They are skipped by name and
the patcher reports `variant: scalar-specular`, so the gap is loud rather
than silent. `40c6faab` is also one of the two skinray permutations, so under
`ptmsggx=on skinray=on` it is absent from `swaps.ptq/` and the layer falls
through to `swaps/` — it keeps its skin BRDF patch and simply gets no energy
compensation. Nothing is un-patched. Both **confirmed-live** permutations
(`d622fb9e`, `4270b745`) are the three-channel form and are patched.

## 6. Verification

Offline (2026-08-28, before any launch): `spirv-val` clean on every patched
module, unpatched inputs round-trip first, anchor coverage reported per
module, materialization exercised through the real `sync_settings.sh`.

**On screen, 2026-08-28.** The launch journal (`~/callisto_launches.log`),
every line with `shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptrefl=on
hair=off tier=1`:

```
18:39:37  ptq=rcb+skin   payload=168c487eeef47bf4     m off
18:44:47  ptq=rcb+skin   payload=4a229a1b8dafbd97   \
18:44:47  ptq=rcbm+skin  payload=2002c25fb989fcd6   / same-second re-sync; no launch behind it
18:45:10  ptq=rcb+skin   payload=4a229a1b8dafbd97     m off
18:47:16  ptq=rcb+skin   payload=168c487eeef47bf4     m off
18:50:11  ptq=rcbm+skin  payload=af7ef6dee985bd81     m on  <- the confirmation launch
18:59:57  ptq=rcb+skin   payload=168c487eeef47bf4     m off
```

One variable moved, with per-launch provenance — the discipline `26` §7 asks
for. The payload stamp hashes mtimes as well as content, so it is not
content-stable across re-materializations; the content evidence is in the
swap log (`~/callisto_swap.jsonl`): of the 60 retained `swaps.ptq` load
events (5 launches × 12 modules), **exactly 12 carry the `+2152 B` msggx size
signature** — one complete module set, matching the 18:50:11 launch — and the
other 48 are byte-size-identical to the m-off build. Both live permutations
were served patched: `d622fb9e` from the skin base (306216 → 308368) and
`4270b745` from vanilla (304244 → 306396). Raygen execution has no
`{"ev":"dispatch"}` proof (dispatch logging covers compute only), so the
on-screen A/B is the execution evidence — and it is decisive: **rough metal
visibly gains the predicted energy with `m` on and reverts exactly with it
off.** User verdict, 2026-08-28: "It completely worked."

The three questions `dev/MS_GGX_NOTES.md` left open for a launch, answered:

1. *Does it change a pixel?* Yes — visibly, on rough metal under direct
   light; smooth surfaces are untouched by construction.
2. *Is patching the area arm right?* The confirmed build patches both arms
   and read correct on screen. The arms were not A/B'd individually;
   `--arms punctual` / `--arms area` rebuild the halves if anyone wants to.
3. *Does excluding the grazing error read as inconsistent?* No — nothing to
   see on screen; the exclusion stands as designed.

## 7. Knobs and limits

- `strength` is **compile-time** (`MSG=1.0` in `dev/build_ptq.sh`); there is
  no runtime slider, like `REG` and `CLAMP`. Changing it means rebuilding the
  matrix and re-installing.
- The two scalar-specular permutations can never be reached by this anchor —
  patching them would need a different splice that synthesizes an F0, which
  is not planned.
- The grazing-angle sum-vs-product error (§4) remains unfixed everywhere in
  the game, patched modules included.
