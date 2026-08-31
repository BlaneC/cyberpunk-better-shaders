# CallistoSSS — current state (2026-08-30 night, after the gi-50 A/B)

One page. Everything here points at the document with the evidence. The rule
this project keeps relearning: *built*, *loaded* and *swapped* are not
*working* — only an on-screen A/B is.

**Next model: read `47-PROCESS-TRACE.md` first — it is the whole 2026-08-30
afternoon in one document (eight launches, what was decided and why, what was
withdrawn, and the eight places it is weakest). Then `46` §18 → §17 → §14 →
§13 → §12 for the evidence behind it. The L-queue is done (L1–L8); only the
real L4 (RR off, two launches) is unrun.**
`46` §1–§10 is the older record of six launches, peer-reviewed in §9 and then
**largely overturned by §11–§18**. Do not believe any figure in §5 or §6.2
without reading §13 first — they straddle a renderer regime break. §11 is
itself partly withdrawn.
`44` is what was built and what was wrong before. This page plus those files
resumes the work with zero prior context.

## Ships and is confirmed on screen

| feature | switch | doc |
|---|---|---|
| SSS diffusion kernel, `detail` preset (engine radius; shipped one was 10×) | `kernel=detail` (selector since 44) | `33` §1 |
| Skin BRDF tier-1 `c1` in the compute resolvers — **confirmed on screen, but on directly-lit skin only** (`46` §14: +1.8% above ~106 lum, nothing below; `46` §12/L2: the class gate passes, but the painted modules write the direct-light term only). Bounce-lit skin reached separately by `gi-50` below — `42` **closes**. | `skin` | `02`, `03`, `46` §12, §14 |
| **`skinspec=gi-50`** — real-gloss + class-gated `c1` on the ReSTIR-GI diffuse raygens. **Standing rung, decided on screen 2026-08-30 night** (`50` §6): user prefers it over `R2-real-gloss` (*"more complexity in the shading of the face"*); S3 corroborates (+1.2..1.8% face lum vs three matched controls, achromatic, structured toward the bounce-lit lower face). Needs `ser=class` (in-skin) + `shadowset=full-shadow`; sync refuses otherwise. | `skinspec=gi-50` | `50` |
| Hair shadow-leak fix, direct shadow rays only | `shadowcull` / `full-shadow` | `26` §7 |
| PT: bounce cull mask 1→255, reflection mask, firefly clamp | `ptbounce`, `ptrefl`, `ptclamp` | `26` §4 |
| MS-GGX rough-metal energy compensation | `ptmsggx` | `28` |
| AgX tonemapper, HDR and SDR, over the authored area LUTs | `dev/install_agx.sh` | `21` |

## Ships, default off, unproven — the A/B queue (`45`)

| feature | rung(s) | doc |
|---|---|---|
| Skin **realism** axes: roughness scale, energy coupling, micro-shadowing, wet eyes; combined as `real` / `real-gloss` | `skinspec=` 9 new rungs | `44` §1, §3 |
| Oily/wet skin gloss ladder (roughness *ceiling*, flattens variation) | `skinspec=subtle…extreme` | `33` §2 |
| SSS kernel presets `balanced` / `callisto` / `vanilla` (tooling check) | `kernel=` | `44`, `33` §1 |
| Sun angular size / visibility / scattering (live CVars) | PT panel | `44`, `43` M3 |
| SER restoration — now selectable from CET, and no longer un-patches ptq | `ser=class…` | `41`, `44` §2.1 |
| Path regularization (`ptreg`) | on in the user's file | `24` |
| Engine CVar panels (hair 40, skin 17, PT 15, detail 22) | live | `16`, `27`, `32`, `33` §3 |

## Measured — 14 launches, 2026-08-30 (`46` §11–§18; decision trace in `47`)

- **The ledger's headline numbers are gone.** A **renderer regime break** at
  ~13:30 (`46` §13) moved static geometry +12–19% in fine energy and stayed
  there, so every E1-baselined figure in §5 straddles it: the "+35/+48%
  texture" rungs, the "−16% default stack", the S3 regression. Re-measured
  inside one regime with a **non-skin control**, all three are inside the
  floor. §11's own "58% noise floor / Ray Reconstruction resolves different
  pores" was the same mistake one level up and is withdrawn (`47` §2, §4).
- **What replaced them.** With vanilla replicated on both sides (`46` §17):
  the mod brightens **only the lit half of the face**, switching on at ~106
  luminance, and costs **no** S1 skin texture. Two instruments agree on the
  threshold — the class probe measured ~116 (`46` §12/L2) from paint, the
  radiometric pass ~106 from tone bins.
- **`42` does not close.** `skinspec=probe-cls` painted 25.8% of S1 skin and
  **0.0%** of S2 skin. The class gate passes; the painted modules write the
  **direct-light term only**, so bounce-lit radiance comes from a writer
  outside the 77 anchored modules. §6.1 hypothesis (b) confirmed, (a) dead.
  The phi-lift commit did not achieve its goal. ~~Next step is a static
  search~~ **Done that night: the writer is not a compute module at all —
  it is the ReSTIR-GI diffuse raygen pair (`48`/`50`), and `42` closes via
  `gi-50` (confirmed table above).**
- **Material classes confirmed on screen:** skin 1, hair 4 (eyelashes
  included), plants 5, **eyes 8** (sun-clipped catchlights only — 30 px above
  the null's max, blue ×2.82 against the palette's ×3.0).
- **The one replicated effect of the day is `ptbounce`** and its sign is
  positive (`46` §18): −9.9% scene-wide fine energy in dim light, 7.3× the
  within-cluster spread, no overlap, one switch spanning the whole gap. That
  is **GI convergence, not detail loss** — the metric scores an improvement
  as a loss. User's unprompted verdict: *"I like PT bounce… the effect is
  super subtle."* It stays on, and it closes the
  `42`/§6.2 thread: the §6.2 skin-texture claim (regime artefact), the
  `ptclamp` mechanism it spawned, and `ptreg` all died — the last two by
  pre-registered predictions that failed.
- **Metric floors, measured** (same config, two launches): S3 non-skin
  **0.3%**, S1 non-skin **~3%**, S1 skin **~6%**, S3 skin **~9%**. All
  S3-**skin** figures are withdrawn on that basis (`46` §16.2). Region choice
  matters more than metric choice.
- **`46` §12 (static, no launch)**: `ab0bc2fe` — named in §9 as one of "the two
  GI resolvers" — writes an **integer sample-index buffer, not colour**. 76 of
  the 77 anchored modules write `v4float`; it writes `v4uint`. So there is one
  colour-writing resolver, not two, the tier-1 `c1` spliced into it cannot
  brighten a pixel, and §6.1's "an unanchored module shades this scene" is now
  the favourite.
- **Direction: `real-gloss` — decided on screen 2026-08-30 evening (`49`).**
  Three launches, one variable, camera pixel-identical, settings pinned,
  control shot in the same session: `real-gloss` beat `real` and `off` in all
  three scenes. User: *"no contest… the off setting looks like plastic."*
  This **overturns** the old `rough-1.3` direction (`46` §11.5), which was held
  on an earlier reaction and the `33` §2 argument, not on numbers — the E2a→E2b
  differential it rested on straddled the regime break. See `49` §4.

## Still unlaunched

Collapsed by the peer review (`47` §11): the radiometric-ledger phase is
over — the eye is the instrument for direction, probes and the serve audit
for reach. In order of look-payoff:

1. ~~**GI-writer probe + splice**~~ **DONE 2026-08-30 night (`50`).** The
   probe named **ReSTIR-GI diffuse** as the bounce-lit skin writer (`50`
   §2); the Site A splice launched and **won the A/B** — `gi-50` is the
   standing rung (see the confirmed table; `50` §6 for the S3 numbers and
   the two disqualified scenes: S2 crowd drift, S1 sun drift — a
   cross-session pair only lighting-matches under stationary light).
   Three `48` §9 claims died on the way (no NoV in scope, NoL not at the
   write, spatial≠spatiotemporal shape) — `50` §3 before touching those
   modules again. Left parked: `gi-100` (one look if the user wants it
   louder), reference-green Site B (only after an observation demands
   it), the spec family (nil share).
2. ~~**One eyeball ladder session**~~ **DONE 2026-08-30 (`49`)** — `real-gloss`
   wins, unanimous, no single-axis fallback needed. Kernel presets still to
   ride along.
3. **One RR-off look** (old E10 / `43` M1, by eye, at the winning rung):
   does the roughness axis sharpen with the denoiser out? Confirm
   `DLSS_D: false` in the `collect.sh` snapshot **before** shooting. The
   two-launch RR *floor* is dropped — no decision still rides on S1/S3
   radiometry.
4. Whenever convenient: E8 sun size (live, no launch) · E11 probe legend
   decode (offline, `44` §2.9).
5. **The look plan is `51`** (2026-08-30 night): A6 spectral kernel (`52`)
   and A7 terminator bleed (`53`) are **built, validated, parked, registered
   in `init.lua` — never on screen**. Next look session: `kernel=spectral`
   vs `detail`, then `gi-50-bleed` vs `gi-50` (`53` §8; `make install`
   first). D3 / A8 / M1 and the ear-glow route resume from `51` §4–§7.
   **E9 SER frame-time: closed by the user 2026-08-30** (*"noticeably faster
   by feel… that's enough"*). **The probe-gi launch (19:36) is the first to
   actually serve a SER splice** — `ser=class:in-skin` (the hints ride the
   skin rung's raygen files; `50` §1), zero rejects. `41`'s serve path is
   proven; its perf claim is still unmeasured. `ser=class` is now standing
   config per the user.

`collect.sh` now snapshots `UserSettings.json` into each rung dir, so RR
state and regime breaks are recorded facts from here on, not inferences.

## Removed (do not rebuild without reading why)

Hair BRDF (`19`, `27` §8) · Tier-4 backlit transmission (`39`) · `skinray`
and the numeric sliders (`43`) · the two-ray shadow splice (`26` §7d) ·
`38`'s "+2 material channel" idea (`44` §2.4: it is the shading normal).

## Where things are

- `init.lua` + `*_engine.lua` (root) are the source; `make release` copies
  them into `release/`; **`make install` deploys to the game with a backup**
  (the game ran stale copies until 2026-08-30 — `44` §2.3). `make layer`
  rebuilds the Vulkan layer.
- `sync_settings.sh` runs from the Steam launch options and materialises
  every overlay (+ `kernel.bin` from `kernels/`); the CET page reads back
  `status.txt` from the previous launch.
- Skin ladder: `./dev/patch_compute_skin.sh --sets` (14 rungs, ~5 min).
  SER ladder: `./dev/patch_ser.sh --install --from ~/.local/lib/callisto/ptq/rcbm/base`.
- `dev/` — shipping patchers; `dev/retired/` — the ones that are done.
- Ideas and their gates: `38`, reviewed in `43`, low-hanging half built in `44`.
- A/B captures live in `a-b-testing/<rung>/S*.png`; `a-b-testing/reproduce.sh`
  regenerates every figure quoted in `46`/`47` (`reproduce_50.py`: `50`); `./dev/ab_launch_audit.py N`
  re-derives what each launch actually served from the layer journal.
