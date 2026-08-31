# 51 — Look plan: A6 → A7 → D3 → A8 → M1, gates and sequencing

Written 2026-08-30 night. The user ranked the surviving `38`/`43` ideas by
expected look payoff: **A6 spectral kernel → A7 terminator bleed → D3 glass
refraction → A8 iridescence → M1 denoiser roughness.** A6 and A7 are being
built now (delegated; docs `52` and `53`). D3/A8/M1 resume from this page.
The ear-glow (traced transmission) route from the same planning session is
§7 — it is not in the ranked five but it is the standing answer to the
user's original itch.

## 1. Gate map — what shares what, and why

A gate is a one-shot proof of *mechanism* (does a splice at stage X execute;
what does field Y mean), not of look. Ideas stack on mechanisms, so gates are
shared. For the ranked five:

| idea | gate | shared with |
|---|---|---|
| A6 kernel | none — `kernel=` ladder proven on screen (`33` §1) | — |
| A7 bleed | none — compute-resolver splice at the 77 anchored modules | — |
| D3 refraction | name the reflection buffer's consumer (offline, no launch) | private to D3 |
| A8 iridescence | **G-U4** subtype launch (rungs parked since `40`) | A3 vellus sheen + the cloth answer ride the same launch (`probe-both`) |
| M1 fix, route (b) | **G-U2** fragment tint | B5 pores, B2 thickness, D2 glints |

**G-U2 "fragment tint", spelled out** (the term confused once already): three
patchable stages exist. Compute resolvers and RT raygens are *proven* to
execute swapped modules (`gi-50`). The fragment stage — the ~1000+ raster
shaders that *write the G-buffer* (UVs, tangents, material textures, the
material word itself) — has **never had a splice proven to execute** (`36`
G1). The test: tint one fragment shader's output, launch, look. Pass ⇒ Tier B
+ half of Tier C become real (pore detail B5, authored thickness B2, G-buffer
roughness = M1 route (b)). Fail ⇒ they die. One tint, one launch.

Among the ranked five, **nothing shares a gate with anything else** except M1
route (b) ⇒ G-U2. All offline work parallelises; only launches serialise.

## 2. A6 — spectral SSS kernel (BUILDING — Opus subagent, doc `52`)

Per-channel diffusion profile from measured skin optics instead of
one-shape-with-a-red-tint. Physics: Jensen et al. 2001 skin1
`σ′s=(0.74,0.88,1.01)/mm`, `σa=(0.032,0.17,0.48)/mm` → transport
`σtr=√(3·σa·σ′t)` → per-channel diffuse mfp `ld=(3.67,1.37,0.68)mm`; Burley
profile `R(r)=(e^(−r/d)+e^(−r/(3d)))/(8πdr)` with `d_c=ld_c/s`, `s≈3.5`
(Christensen-Burley dmfp fit; near-constant over skin albedos). **Only the
R:G:B ratios (d = 2.68 : 1 : 0.50) come from physics; absolute scale anchors
to the engine's green-channel width** — the 10× radius trap
(`author_callisto_kernel.py` header) must not be re-entered. Offsets (.a)
untouched; weights (.rgb) reshaped; per-channel energy sums preserved.
Ships as `kernel=spectral` rung; A/B vs `detail`, one variable.

## 3. A7 — shadow-terminator colour bleed (BUILDING — fork, doc `53`)

The kept half of `43`'s A7 verdict (the pre-integrated-blur half double-counts
SSS and is dropped). Red wraps further into the terminator than green/blue
because red's mfp is longer — same `d` ratios as §2, deliberately consistent.
**Hard constraint (`0d` / `39` §3.3): multiplicative only.** A per-channel
modulation of the existing diffuse term, ≡1 away from the terminator, anchored
`m_G=1`, clamped; where the base term is zero it stays zero, so no tile grid
by construction. Curvature from neighbour depth taps (720p, reverse-Z),
confidence-weighted to collapse to identity where the estimate is junk (the
hair-tangent pattern). Class-1 gated on the existing `build_skin_c1`
machinery; NoL is in scope at those sites (the `micro_k` pass uses it).
Identity at `k=0`. Rung parked so it can A/B **at the standing config**
(`gi-50` base) with one variable.

## 4. D3 — real glass refraction (DEFERRED)

1. **Gate, offline, no launch:** name the consumer of
   `rgs_reflection_transparent_main`'s output buffer (`20` open item 1, prov
   logs + disassembly). GOTCHAS #11: if it composites over already-blended
   glass, refraction can only read as a ghosted double image ⇒ D3 dies there.
2. If clean: repoint the traced mirror direction to the refracted one. The
   raygen already reconstructs P and V from depth+normal (`20` Phase 0.5).
   **Origin sign:** `20` §1's `P − D·ε` sits *outside* the surface — a
   transmitted ray fired from it self-hits. Fix the sign.
3. One launch, eyeball A/B. Raygen serve machinery from `50` (MANIFEST,
   provenance guard, `ab_launch_audit.py`) is the template.

## 5. A8 — thin-film iridescence on chrome (DEFERRED)

1. **Gate: launch the parked subtype probe** (`probe-both`, built in `40`,
   parked in `skin.set/`) — also answers cloth + ungated sheen (A2/A3) in the
   same launch. Decode the legend (E11, offline, still open as of `46`).
2. If chrome cyberware has its own subtype: Belcour-Barla airy reflectance,
   ~20 instructions at the Schlick sites (metallic already in a register,
   `22` §1), gated on that subtype. If not: fallback is ObjectID-hashed film
   thickness — `43` calls it noise per object; decide then whether it's worth
   it, gated `metallic>0.9`.
3. One launch, eyeball A/B.

## 6. M1 — the denoiser sees vanilla roughness (DEFERRED)

Every roughness edit lives in the resolve; RR/NRD reads roughness from the
G-buffer and smears the tight highlight `real-gloss` makes. `43` §3 rates
this the most important item; it amplifies the already-won rung.

1. **Falsifier (already CURRENT queue item 3): RR-off look at `real-gloss`.**
   Settings-only, one launch. Confirm `DLSS_D: false` in the `collect.sh`
   snapshot BEFORE shooting (`47`'s silent-RR lesson, both directions).
2. Highlight does NOT sharpen ⇒ M1 dead, stop, saved the work.
3. Highlight sharpens ⇒ two fix routes:
   (a) find RR's roughness guide-buffer producer in the dump (offline hunt)
   and apply the same alpha rewrite there;
   (b) do the roughness edit at the G-buffer write — **needs G-U2** (§1).
   Run the tint first; it is ten minutes of prep and decides the route.

## 7. The ear-glow route (traced transmission) — for when the itch returns

`39` §6's two reopening conditions, and the plan agreed 2026-08-30:

1. **G-U3, offline, zero launches:** name the writer of the skipped
   `R8_UINT` at `registers[1]+3` and what it holds. `EMM_SurfaceTranslucency`
   is a named candidate (`38` §1.1/U3) — if the engine already writes
   per-pixel translucency there, the thickness-input problem is solved free.
2. **G-U5, payload sentinel, one small launch** (`29` §B5, unrun for four
   documents): miss shader writes a constant into the payload, read back
   after iteration 2, written somewhere visible. Gates traced thickness AND
   all of `29` Part B. Note `26` §7d: a *second static* `OpTraceRayKHR`
   validates, serves, does not execute — the sentinel is exactly the
   experiment that maps what does.
3. If it passes: short ray along −L from the skin hit ⇒ measured thickness ⇒
   transmission term in the raygen. Measured thickness kills the
   forehead-scores-like-an-ear defect; non-tile-quantised RT output kills the
   blocky grid. Both `39` defects die structurally. Ship as a rung, A/B.

## 8. Session/launch budgeting

- **Launches are the scarce resource.** Diagnostics (G-U4 probe, RR-off look,
  G-U2 tint) can share a session as separate launches; look A/Bs are one
  variable each per `45`, settings stated before launch (house rule).
- Suggested next session: A6 A/B, then A7 A/B at the A6 winner. Session
  after: G-U4 probe + RR-off + (optional) fragment tint — three diagnostics.
- **Integration rule for the delegated builds:** neither agent touches
  `init.lua`, `sync_settings.sh`, or `Makefile`. Registration diffs live in
  `52`/`53` and are applied here after both land, to avoid two agents
  colliding on shared config. `make release` picks up new
  `dev/kernels/kernel.*.bin` via wildcard; no Makefile change needed.
- Nothing in `52`/`53` is *working* until an on-screen A/B says so — built,
  validated, parked is the ceiling for a subagent.
