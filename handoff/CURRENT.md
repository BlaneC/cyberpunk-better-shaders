# CallistoSSS — current state (2026-08-30)

One page. Everything here points at the document with the evidence. The rule
this project keeps relearning: *built*, *loaded* and *swapped* are not
*working* — only an on-screen A/B is.

## Ships and is confirmed on screen

| feature | switch | doc |
|---|---|---|
| SSS diffusion kernel, `detail` rung (engine radius; shipped one was 10×) | `kernel` | `33` §1 |
| Skin BRDF tier-1 `c1` in the compute resolvers | `skin` | `02`, `03` |
| Hair shadow-leak fix, direct shadow rays only | `shadowcull` / `full-shadow` | `26` §7 |
| PT: bounce cull mask 1→255, reflection mask, firefly clamp | `ptbounce`, `ptrefl`, `ptclamp` | `26` §4 |
| MS-GGX rough-metal energy compensation | `ptmsggx` | `28` |
| AgX tonemapper, HDR and SDR, over the authored area LUTs | `dev/install_agx.sh` | `21` |

## Ships, default off, unproven

| feature | why off | doc |
|---|---|---|
| Oily/wet skin gloss ladder (`skinspec`) | every rung is a roughness *ceiling* and flattens authored roughness | `33` §2 |
| Path regularization (`ptreg`) | a deliberate look trade | `24` |
| SER restoration (`ser`) | built, validated, never measured; frame time is the only proof | `41` |
| Engine CVar panels (hair 40, skin 17, PT 12, detail 22) | live, never A/B'd; the NRD knobs are dead if Ray Reconstruction is on | `16`, `27`, `32`, `33` §3 |

## Built, NOT yet on screen — launch these first

1. **`42`** — the skin BRDF never reached the two GI resolvers (0 of 218 sites).
   Fixed; bounce-lit skin has never carried `c1`, the cap or the gloss. One launch.
2. **`40`** — the sub-enum rainbow + ungated sheen probe (G-U4 / A2). One launch,
   answers three questions.
3. **`41`** — SER. Frame-time delta, not a screenshot.

## Removed (do not rebuild without reading why)

Hair BRDF (`19`, `27` §8) · Tier-4 backlit transmission (`39`) · `skinray`
and the numeric sliders (`43`) · the two-ray shadow splice (`26` §7d).

## Where things are

- `init.lua` + `*_engine.lua` (root) are the source; `make release` copies
  them into `release/`. `make layer` rebuilds the Vulkan layer.
- `sync_settings.sh` runs from the Steam launch options and materialises
  every overlay; the CET page reads back `status.txt` from the previous launch.
- `dev/` — shipping patchers; `dev/retired/` — the ones that are done.
- Ideas and their gates: `38`, reviewed and re-ordered in `43`.
