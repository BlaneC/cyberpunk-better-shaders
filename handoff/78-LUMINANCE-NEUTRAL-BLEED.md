# 78 — The terminator band, deeper: the bleed holds luminance

> **OUTCOME (2026-08-31 22:28): the DEEPEST rung won.**
> `gi-50b-bleed-oil-sheen-deep` beat `-lumn` on screen and is the standing
> skin rung and the live selection. Verdict, verbatim: *"Deepest band is
> actually the best skin shader right now over lumn."* Evidence in §5.1.

Written 2026-08-31 evening, on the user's read that **the extra rays are the
wrong lever for face-shadow contrast** (`77`'s spp rungs raise sample count,
not contrast) and their diagnosis of the right one:

> *"Make the bleed luminance-neutral. Right now m_R = 1 + 0.336·w adds energy
> at the terminator. Renormalizing to hold luminance (boost R, drop G/B
> proportionally) gives you the rosy 'alive' quality without lifting the very
> band you want deep."*

The diagnosis is correct, and it is bigger than it looks: on directly-lit skin
the stack holds the terminator band **+24.7% above vanilla**, and the bleed is
about half of that. Built, verified offline, parked and deployed 20:57.

**BOTH RUNGS WENT ON SCREEN, AND THE DEEPER ONE WON.** `-lumn` launched 21:04
and 22:00 — *"Looks 10x better. Using the lumn version now as the default."*
Then `-deep` launched 22:28 the same evening and beat it:

> *"Deepest band is actually the best skin shader right now over lumn."*

**`gi-50b-bleed-oil-sheen-deep` is the standing rung and the live selection**
(`brdf_params.txt`; `status.txt` `req == want`; layer `last_failed=0` — §5.1).
`-lumn` is superseded, and survives as the documented half-step back.

That result confirms §1's model in the direction it predicted *and* past the
point it predicted. The hold alone (`-lumn`, band floor 1.247 → 1.130) was
enough to earn "10x better"; taking the rest — c1's grazing-light lobe — is
what the user actually wanted, and it lands at **0.988 direct / 0.889 bounce**,
i.e. at or *below* vanilla band depth. The pre-registered failure for this rung
was *"reads flat/dead → `rho_f` was doing look-work, keep `-lumn` and stop"*.
It did not fire.

## 0. Verdict

| question | answer |
|---|---|
| did it work on screen? | **Yes — and the deeper rung won.** `-lumn` kept at 21:04/22:00 (*"Looks 10x better"*), then **`-deep` beat it at 22:28** (*"Deepest band is actually the best skin shader right now over lumn"*) and is the live selection. All three launches verified serving the requested rung unrefused, `last_failed=0` (§5.0, §5.1). |
| does the bleed add energy at the terminator? | **Yes, and it is the single largest term doing so.** `m_G = 1` leaves the `53` triple a net Rec.709 add of **+6.4%·k·w on grey, +10.4% on a rosy skin colour** — peaking exactly at the band floor. |
| how much is the band lifted, all told? | normalised at the lit cheek (so vanilla ≡ 1.000): **direct path 1.247 at the floor, 1.155 where the band reads** (NoL≈0.1, NoV 0.7); **bounce path 1.153 / 1.062**. `./dev/band_model.py` prints every cell. |
| what does the hold remove? | direct **1.247 → 1.130**, bounce **1.153 → 1.044**. Hue and saturation are *bit-for-bit* the look the user already approved — the R:G:B ratios are untouched, only the scale moves. |
| what is the other half? | **c1's grazing-LIGHT lobe** (`rho_f`): 1.35 direct / 1.175 bounce. It is a retroreflection term that by design brightens grazing light. Pulling it to identity takes the direct band to **0.988** and the bounce band to **0.889**. |
| is a grey renormalisation enough? | **No.** Dividing the triple by its own luma is neutral only on grey; skin is chromatic and it leaves ~40% of the lift (deep end +8.4% instead of +4.4% on the bounce path). The rungs hold the *pixel's own* luminance instead. |
| will this deliver "contrasted shadows on the face"? | Partly, and in known amounts. On the direct path the hold alone takes back **0.14 stops** at the band floor (0.08 where the band reads); the hold plus `rho_f` takes back **0.34 stops** (0.23). Bounce path: 0.14 and 0.38. What none of it touches: the SSS kernel blur (the structural softener, a live `kernel=` selector, no build), the additive fuzz, and the GI fill indoors. |

## 1. The measurement that motivated the build

`./dev/band_model.py`, normalised at the lit cheek — vanilla is 1.000 at every
row by construction, so every number above 1.0 is the mod holding the shadow
falloff brighter than vanilla would:

    DIRECT path (compute resolvers, NoV=0.70)
      NoL     standing   -lumn     -deep
      0.000   1.247      1.130     0.988
      0.100   1.155      1.097     0.988      <- where the band reads
      0.250   1.066      1.057     0.988
      0.350   1.037      1.037     0.989      <- band edge, bleed = 1
      1.000   1.000      1.000     1.000

    BOUNCE path (ReSTIR-GI ST pair, no view vector)
      NoL     standing   -lumn     -deep
      0.000   1.153      1.044     0.889
      0.100   1.062      1.009     0.889
      0.350   0.950      0.950     0.897
      1.000   1.000      1.000     1.000

Two things to read off it. First, **the direct path is where the lift lives** —
the compute c1 carries the full `rho_f=1.35` *and* a `NoV^2.5` factor, so a
sun terminator on a face is a much bigger offender than an indoor bounce
terminator. Second, `-deep` does not merely cancel the lift on the bounce
path, it **inverts** it to −11%: with `rho_f = 1`, `c1_bounce = 1 + 0.125·NoL^2.5`
still lifts the LIT end, so the band sits 1/1.125 below it. That is a contrast
increase, which is the point — but it is a bigger swing than "neutral", and
§5 pre-registers what to do if it reads as too much.

In absolute terms the bleed's add is small — it peaks at **+0.54% of the
fully-lit diffuse level** around NoL≈0.117 — because the term it multiplies is
itself dying. The lift is a *local* one, and local contrast in the falloff is
exactly what the eye reads as shadow depth.

## 2. What the hold is

Same closed form as `53`/`74`, one factor added:

    w   = sat(1 − NoL/0.35)²
    m_R = (1 + 0.336k·w)·s      m_G = s      m_B = (1 − 0.101k·w)·s
    s   = Y / max(Y + β·w·k·(0.2126·0.336·C_R − 0.0722·0.101·C_B), ε)
    Y   = 0.2126·C_R + 0.7152·C_G + 0.0722·C_B

`β` is the knob (`bleed_norm` / `--bleed-norm`), identity at 0. `s` multiplies
all three channels, so **R:G:B is unchanged** — the hue and saturation of the
approved look survive exactly; only the scale moves. At β=1 the triple's
luminance on its own basis is held to zero error (verified, §3).

**Why not the cheaper grey renormalisation** (divide by the multiplier's own
luma, 1 + 0.0641k·w): it is exact only for a grey pixel. On skin chroma it
under-corrects by 40% — bounce band 1.084 instead of 1.044. The per-pixel form
costs one `OpFDiv` and a dot product more, and needs no assumption about what
colour skin is.

**The denominator cannot vanish.** For any non-negative colour the add is
bounded by `0.101·k·β·Y` in magnitude, so `den ≥ (1 − 0.101kβ)·Y ≥ 0.9Y` at
k=β=1; the `NMax` guard covers only `Y == 0` exactly (a black albedo, whose
diffuse term is zero anyway, and `s = 0` there scales zero by zero).

**Where it is emitted.** The luma basis is the site's own **channel-identified
diffuse colour triple**, not the fan-out consumers, for a structural reason:
only the colour triple is *proven to dominate* the splice point (the same
`cfg.dominates_line` check `find_bleed_targets` already made). The shared
scalar cancels out of a ratio, so the two bases are equivalent — see §4 for the
one place they are not.

Cost: **+16 instructions per bled site** (12 → 28), one `OpFDiv` among them.
No new fetches, no new resources, no branches.

## 3. What was built, and the verification record

Two candidates, each ONE variable off the rung below it, both halves moved
together (the bleed lives in the compute modules *and*, since `74`, in the
ReSTIR-GI ST pair):

| rung | = | vs its twin |
|---|---|---|
| `gi-50b-bleed-oil-sheen` | the standing candidate (`74`) | — |
| **`gi-50b-bleed-oil-sheen-lumn`** | + the luminance hold, β=1, in both halves | 2 ST raygens + 77 compute |
| **`gi-50b-bleed-oil-sheen-deep`** | + `rho_f → 1.0` in both halves | 4 raygens + 77 compute |

Intermediates parked and selectable for attribution: `real-gloss-bleedn-oilh`,
`real-gloss-bleedn-oilh-deep` (compute halves), `gi-50bn`, `gi-50bnd` (raygen
bases).

Everything below ran; nothing is inferred.

- **The patcher edits are byte-inert.** `real-gloss-bleed-oilh` rebuilt with
  the edited `patch_compute_skin.py`: **0 of 77** modules differ from the
  parked shipping rung. `gi-50`, `gi-100` and `gi-50b` rebuilt with the edited
  `patch_gi_c1.py`: **0 of 16 raygens** differ, each. The standing look cannot
  have moved.
- **Emitted-math machine evaluation, on the SHIPPED bytes** —
  `dev/verify_bleed_norm.py` re-parses the assembled text, finds every
  normalisation chain structurally, checks its eight baked constants, proves
  the channel wiring (the R multiply lands on the fan-out carrying the R
  colour and no other), then **interprets the instructions** at 10 NoL × 6
  colours × 2 gate states per site. Result on the post-peach compute half of
  both candidates: **150 sites over 77 modules, 18 000 evaluated points each,
  all matching the closed form; luminance held to < 3e-6 relative; gate false
  = exact (1, 1, 1)**. Same on both ST raygens of `gi-50bn` and `gi-50bnd`.
- **Coverage from reports, never byte diffs** (the `42` rule): 173 c1 / 150
  bleed / 23 skipped / 0 dup, and **150 of 150 bled sites carry the hold** —
  a site that took the bleed but not the hold now FAILS the build, because
  the byte count would not have said so. Peach ladder unchanged: 457 sites,
  401+56 folds, 16 clamped, defres 457/457.
- **One-variable assertions, fatal in the build**: `gi-50bn` vs parked
  `gi-50b` = exactly the 2 ST raygens, 0/77 compute; `gi-50bnd` vs `gi-50bn` =
  4 raygens (the ST pair *and* the SP pair, because their flat factor is E[c1]
  and must not disagree with the ST pair about what c1 is), 0/77 compute. At
  the assembled level: standing → `-lumn` = 2 raygens + 77 compute;
  `-lumn` → `-deep` = 4 + 77.
- **`verify_gi_ladder.sh --gi gi-50bn` and `--gi gi-50bnd`: ALL CHECKS PASS**
  (file lists equal, 0/16 raygen deltas within each base, 77/77 compute
  deltas, provenance OK).
- **`gi_refuse` provenance re-checked by hand against the live install**:
  both new rungs carry `src_ser=ser.set/class`, `ser_sha=310513f3008cbde4`,
  `ptq_sha=55ed4e5c6884ab71` — identical to the standing candidate's and to
  what the install currently hashes. Same contract: **`ser=class` +
  `shadowset=full-shadow`**.
- `spirv-val` clean on all 93 modules of both rungs (patcher-fatal, then
  re-checked per rung). `make check` passes. Deployed with `make install`
  (backup `20260831-205725`); the deployed `init.lua` is `cmp`-identical to
  the repo's.
- **Not verified: pixels.**

## 4. The approximation, written out loud

The hold's basis is the triple **at the splice**. Downstream of it, per-channel
factors still multiply: the direct site's **light colour** (`%721/%722/%723` =
a common intensity × a per-channel colour) and, in the raygen, the
reservoir's **radiance**. Neither is in scope at a point that dominates the
splice, so the luminance held is that of `albedo × (1−metal)`, not of the
final lit pixel. Consequence, exactly:

    light               luminance at the band floor, -lumn   (unheld)
    white   (1, 1, 1)          −0.00%                        (+10.41%)
    tungsten(1, .75, .5)       +2.37%                        (+13.03%)
    sodium  (1, .6, .25)       +4.29%                        (+15.15%)
    cool    (.5, .75, 1)       −2.85%                        (+7.26%)

So: exact under neutral light, and a bounded ±3–4% residual under a strongly
tinted one — against +10 to +15% unheld. The route to exactness is named and
NOT built: the per-channel light colour is reachable as the *cofactor* of the
albedo in each fan-out FMul (`%810 = %721 × %339`), which would make the basis
the true product at +3 instructions — but it needs a new detector with its own
proof obligation (identify the sibling operand per channel, and skip rather
than guess), and it buys at most 4%. If a warm-lit interior face still reads
lifted after the launch, that is the lever, not `k`.

## 5. What ran, what it proved, and what is still open

### 5.0 The launch record (2026-08-31)

From `~/callisto_launches.log` (what sync served) and the CET `status.txt`
(what the layer then reported). The evening's whole trace, in order:

| time | `skinspec=` served | `skin_sha` | note |
|---|---|---|---|
| 17:17 | `gi-50b-bleed-oil-sheen` | `8264b306c10e8bf3` | the standing candidate — the one-variable twin |
| 17:20 | `gi-50b-bleed-oil-sheen` | `8264b306c10e8bf3` | same rung, `refract=off → eta20` (the `76` A/B) |
| 18:07 | `…-spp4d` | `9186954230375089` | `77`'s low-risk rung, **served on screen, no verdict given** |
| 18:10 | `…-spp4` | `c564a287c016d49f` | `77`'s full rung, **served on screen, no verdict given** |
| **21:04** | **`…-lumn`** | `a3139d629e26d902` | this build's first look; `ser=class:in-skin` |
| **22:00** | **`…-lumn`** | `a3139d629e26d902` | same skin payload, `ser=class+hit:in-skin` |
| 22:07 | `…-lumn` | `a3139d629e26d902` | same rung again after the commit; `payload=063f302e61d99dc8` |
| 22:26 | `…-lumn` | `a3139d629e26d902` | same rung, `cache=kept` |
| **22:28** | **`…-deep`** | `f8f2890ebcd48252` | **the depth rung — §5.1, and it wins** |

Verified for the 22:00 launch (`status.txt`): `want_skinspec_req` ==
`want_skinspec` == `gi-50b-bleed-oil-sheen-lumn` (**requested rung served, not
refused**), `want_shadowset=full-shadow`, `want_ser=class+hit:in-skin`,
`want_kernel=spectral`, `want_refract=eta15`, `want_ptq=rcbm`,
`cache=cleared`, `last_layer=loaded`,
`last_overlays=skin+shadowcull+ptq+ptrefl`, `last_resolve=77`,
`last_raygen=15`, `last_gi=4`, `last_shadow=10`, `last_refl=3`,
**`last_failed=0`**. Settings in force, stated as the house rule requires:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50b-bleed-oil-sheen-lumn   ser=class+hit   ptreg=on
    ptclamp=on ptbounce=on ptmsggx=on ptrefl=on   refract=eta15

Game side, unchanged from `74`/`76`: PT on, PT-in-photo-mode on, RR off, DLSS
Balanced, RayTracedLighting Psycho, 2560×1440.

**Verdict:** *"Looks 10x better. Using the lumn version now as the default."*
Kept, and `-lumn` is the live selection.

**What the trace does and does not prove.** The rung that was served is
certain — `skin_sha=a3139d629e26d902` on both `-lumn` launches, distinct from
the standing candidate's `8264b306c10e8bf3`, and `req == want` means sync did
not silently substitute. What is *not* a clean single-variable read is the
comparison: the launch immediately before `-lumn` was `-spp4` (18:10), so the
back-to-back pair moved two things (sample count *and* the hold). The true
one-variable twin, `gi-50b-bleed-oil-sheen`, was on screen at 17:17/17:20 —
three hours earlier, different scene. So "10x better" is a cross-launch
judgement, not an instant flip. It is a verdict, not a measurement; the
measurement is §1, and §1 is what predicted the direction. Two things follow:
the 4 spp underneath was NOT part of the win (it was in the *previous* rung
and is absent from this one), and if a same-session flip is ever wanted it is
one selector change with no rebuild.

**If the 4 spp is wanted under the new default**, it is one command —
`CALLISTO_SPP_BASE=gi-50b-bleed-oil-sheen-lumn ./dev/build_skin_spp.sh --install`
— and that build has still NOT been run.

### 5.1 The depth rung on screen — `-deep` wins

**Launched 2026-08-31 22:28:54.** From `~/callisto_launches.log`:

    skinspec=gi-50b-bleed-oil-sheen-deep  skin_sha=f8f2890ebcd48252
    shadowset=full-shadow  sc_sha=57ef80ee1f72f54a  ptq=rcbm
    ser=class:in-skin  ptrefl=on  refract=eta15  tier=on
    cache=cleared  payload=ff2f4a92c9d52487

`status.txt` for that sync: `want_skinspec_req` == `want_skinspec` ==
`gi-50b-bleed-oil-sheen-deep` — **the requested rung was served, not refused**
(the `ser=class` + `full-shadow` precondition the GI rungs carry was met).
The layer's own `last_run.json`, written 22:29, reports `layer=loaded`,
`overlays=[skin, shadowcull, ptq, ptrefl]`, hits **resolve 77 / shadow 10 /
raygen 15 / refl 3 / gi 4, failed 0** — the same hit profile as both `-lumn`
launches, so the identical set of modules carried the deeper payload.

Settings in force, stated as the house rule requires (`brdf_params.txt` as it
stands now, unchanged since the launch):

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50b-bleed-oil-sheen-deep   ser=class   ptreg=on
    ptclamp=on ptbounce=on ptmsggx=on ptrefl=on   refract=eta15

Game-side settings were **not re-stated before this launch** and are assumed
unchanged from `74`/`76` (PT on, PT-in-photo-mode on, RR off, DLSS Balanced,
RayTracedLighting Psycho, 2560×1440). That is an assumption, not a record —
the house rule wants them pinned *before* the launch, and this one was judged
before the rule was applied.

**Verdict:** *"Deepest band is actually the best skin shader right now over
lumn."* `-deep` is kept and is the live selection.

**What this A/B proves — and it is the cleanest one in the whole band
sequence.** The launch immediately before it (22:26) served `-lumn`, and the
two differ in exactly three logged fields: `skinspec`/`skin_sha`, `ser`
(`class+hit` → `class`), and `cache` (`kept` → `cleared`). Neither of the
latter two can move a pixel: `41` establishes that
`OpReorderThreadWithHintNV` is a *hint* — "it cannot change a pixel" — and
clearing the shader cache changes compile time, not output. **So the only
look-affecting variable across a back-to-back pair was the skin payload.**
That is strictly better evidence than `-lumn`'s own win, which crossed `-spp4`
and therefore moved two things (§5.0). It also matches the 21:04 `-lumn`
launch field-for-field, `ser` included.

**What it does not prove.** It is a verdict, not a measurement — no capture
pair was taken, so no `ab_compare` numbers back it, and the camera was not
pinned across the two launches (a back-to-back pair is not a pixel-matched
one). And the single pre-registered confound was **neither confirmed nor
ruled out**: `-deep` dims bounce-lit skin ~2% overall via the SP flat factor
(1.078 → 1.056), which is uniform rather than band-shaped. The scene was not
recorded, so it is not even known whether a bounce-dominated interior was in
shot. If a dim interior later reads flat, that factor — not the band — is the
first suspect, and the half-step in §5.2 item 3 is the lever.

### 5.2 What is still open

1. ~~**The band pair.** `gi-50b-bleed-oil-sheen` → `-lumn`.~~ **DONE, 21:04 /
   22:00 — kept.** The pre-registered success condition (rosy edge keeps its
   colour, stops glowing; falloff deeper in its darkest third) was not
   scored cell by cell; the user's read was a whole-image one. No hue change
   was reported, which is the pre-registered failure that would have meant
   the wrong thing was on screen.
2. ~~**The depth rung.** `-deep`, same camera.~~ **DONE, 22:28 — kept, and it
   beat `-lumn` (§5.1).** The pre-registered prediction (direct band to vanilla
   shape 0.988, bounce band 11% below it) is what the user read as *"the best
   skin shader right now"*. Still unscored: the ~2% uniform dim on bounce-lit
   skin — see §5.1's last paragraph, and item 3 is its lever.
3. **If `-deep` ever reads as too much** — most likely in a bounce-dominated
   interior, where the SP flat factor bites and the §5.1 launch gives no
   evidence either way (the scene was not recorded) — the half-step is
   two commands, both
   rebuilding `gi-50bnd` and its compute half in place:
   `./dev/build_gi_rung.sh --flat-front --rho-f 1.09 --install` and
   `./dev/patch_compute_skin.sh --only real-gloss-bleedn-oilh-deep --set rho_f=1.17`,
   then re-assemble with `build_gi_bleed_sheen.sh`. Do NOT compensate by
   raising `k`.
4. ~~**If neither reads as "more contrasted"**~~ — moot for the sun
   terminator: both rungs read as more contrasted and the deeper one won. Kept
   as the route for any *other* scene that still reads flat; the remaining
   levers, in order
   of size: the **SSS kernel** (a blur that transports light across the
   terminator — `kernel=` is live, no build), the **additive fuzz** (up to 79%
   of local diffuse at grazing view, `33`/`74`), and the **GI fill** itself.
   The bleed and c1 are then exonerated by measurement, not opinion.

Pre-registered failures:
- Band still lifted on a **warm-lit interior** face → the light-colour basis
  of §4, not more β.
- Skin reads **greyer** in the band → that would be the *hold* over-scaling a
  chromatic pixel; §4's table bounds it at 3%, so suspect the fuzz first.
- ~~`-deep` reads flat/dead → `rho_f` is a real retroreflection term and it was
  doing look-work; keep `-lumn` and stop.~~ **Did not fire.** `rho_f` at
  identity read as better, not deader, so the grazing-light lobe was *costing*
  look-work at the terminator rather than adding it. Note this remains untested
  on a bounce-dominated interior, where `rho_f`'s share is larger (1.175 vs
  1.35) but the SP flat factor also bites.

## 6. Files

| file | change |
|---|---|
| `dev/patch_skin_brdf.py` | `bleed_norm` knob (identity 0.0, in KNOBS + VANILLA) |
| `dev/patch_compute_skin.py` | `find_bleed_targets` also returns each channel's diffuse-colour id; the hold's emission in `build_skin_c1`; G spliced only under the hold; dup guard extended to all three channels; `bleed_norm` in the report |
| `dev/patch_compute_skin.sh` | `real-gloss-bleedn-oilh` + `-deep` LEVELS entries; coverage print and a fatal gate on hold-sites ≠ bled-sites |
| `dev/patch_gi_c1.py` | `--bleed-norm` (β) and `--rho-f`; the hold on the ST triple; `cbar` follows `rho_f` so the SP pair cannot disagree about c1 |
| `dev/build_gi_rung.sh` | `--luma-neutral` → `gi-50bn`, `--flat-front [--rho-f V]` → `gi-50bnd`; per-rung one-variable base (50b vs 50, 50bn vs 50b, 50bnd vs 50bn, the last expecting 4 raygens) |
| `dev/verify_bleed_norm.py` | **new** — re-parses a built rung and executes the emitted hold; the `53` §4 discipline as a runnable check |
| `dev/band_model.py` | **new** — every number in §1 and §4 |
| `init.lua` (+ release copy, deployed) | the two selector entries; STANDING moved to `-deep` after the 22:28 verdict, `-lumn` relabelled as the half-step |
| `skin.set/` | `real-gloss-bleedn-oilh`, `-deep`, `gi-50bn`, `gi-50bnd`, `gi-50b-bleed-oil-sheen-lumn`, `gi-50b-bleed-oil-sheen-deep` |

Committed and pushed at the user's request after the 22:00 verdict. **The
22:28 `-deep` result (§5.1) and the selector relabel landed after that commit
and are uncommitted.** No rebuild was needed for it — `-deep` was already
built, parked and deployed at 20:57; only the selection moved.

The *shipped* default is unchanged and stays `skinspec=off`
(`sync_settings.sh`) — "default" here means the user's live `brdf_params.txt`
selection plus the selector label, per the project's default-off rule.
