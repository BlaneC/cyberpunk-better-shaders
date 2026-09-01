# 51 — Look plan: A6 → A7 → D3 → A8 → M1, gates and sequencing

Written 2026-08-30 night. The user ranked the surviving `38`/`43` ideas by
expected look payoff: **A6 spectral kernel → A7 terminator bleed → D3 glass
refraction → A8 iridescence → M1 denoiser roughness.** A6 and A7 are being
built now (delegated; docs `52` and `53`). D3/A8/M1 resume from this page.
The ear-glow (traced transmission) route from the same planning session is
§7 — it is not in the ranked five but it is the standing answer to the
user's original itch.

> **2026-08-31: the gate launches are read (`56`/`57`/`58`). Start at §10 —
> the post-gate board: ear glow is a build now (delegated, doc `59`), `29`
> Part B is open, A8 is dead, and the sheen gate PASSED — A3 peach fuzz is
> buildable (`58`). §§1–9 are the pre-gate plan.**

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

## 5. A8 — thin-film iridescence on chrome (**DEAD — gate failed 2026-08-31**)

> **The gate answered NO (`57` §3.1).** `probe-both` launched; the R-man's
> chrome cheek plate reads `0.536/0.279/0.186` against his own adjacent skin at
> `0.500/0.305/0.194` — same hue family, inside albedo noise. User's independent
> read: *"I dont see normal cyberware get any different colour on bodies."*
> **Chrome cyberware has no subtype of its own, so step 2's Belcour-Barla route
> cannot be gated.** The fallback (ObjectID-hashed film thickness) is what `43`
> already calls noise-per-object. **Recommendation: drop A8, do not build the
> fallback.** The steps below are kept only as the record of what was gated.
>
> Same launch also: skin does **not** split (`57` §3.2), so `c1sub` need not
> launch; hair carries ≥2 subtypes (`57` §3.3). **A2/A3 sheen is still
> unanswered** — the `both` merge confounded it (`57` §4).

1. ~~**Gate: launch the parked subtype probe**~~ **DONE 2026-08-31 (`57`).**
   (`probe-both`, built in `40`, parked in `skin.set/`) — was also meant to
   answer cloth + ungated sheen (A2/A3) in the same launch; it did **not**,
   see `57` §4. Decode the legend (E11, offline, still open as of `46`) — and
   `57` §5 says that needs a **vanilla control at the same camera**, not
   another probe.
2. If chrome cyberware has its own subtype: Belcour-Barla airy reflectance,
   ~20 instructions at the Schlick sites (metallic already in a register,
   `22` §1), gated on that subtype. If not: fallback is ObjectID-hashed film
   thickness — `43` calls it noise per object; decide then whether it's worth
   it, gated `metallic>0.9`.
3. One launch, eyeball A/B.

## 6. M1 — the denoiser sees vanilla roughness (FALSIFIED 2026-08-31, `79`)

> **Dead. Do not run the falsifier below — it does not test the claim.** It
> swaps RR for NRD, and both read G-buffer roughness, so either outcome is
> consistent with M1 being false. The discriminating differential already ran
> with RR **on** (`46` §11.3, E2a→E2b: top-3% highlight +3.23%, flat face,
> flat controls) and the roughness edit plainly survives RR. Also: every look
> approved 2026-08-31 was judged with `DLSS_D: false` — RR was not in the
> pipeline at all. Routes (a) and (b) below are both blocked; `79` §6. The
> live version of this mechanism is the ReBLUR specular prepass radius in
> `detail_engine.lua`, never once enabled — `79` §7.

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

**The design target, user's words (2026-08-30 night):** *"I want ears to go
full red when light from the sun is being cast through them. Like for them to
illuminate… Same with noses."* Note the physics delivers this for free: with
per-channel extinction from the same Jensen coefficients as `52`/`53`
(ld = 3.67/1.37/0.68 mm), a ~5 mm ear transmits red and kills green/blue —
the saturated red glow IS the spectral falloff, no tint knob needed.

`39` §6's two reopening conditions, and the plan agreed 2026-08-30:

1. ~~**G-U3, offline, zero launches**~~ **DONE 2026-08-30 night (`54`) —
   answered NEGATIVE.** The slot is the per-pixel **light-channel bitmask**
   (`EMM_LightChannels`), written by volume proxies late in the frame and
   read every pixel by the colour-writing ReSTIR-GI resolver (`38`'s
   "unread in both GI resolvers" was wrong). NOT translucency, NOT free to
   write — `38` U3/B2 retire. No free thinness input exists; step 2 is the
   only honest route. Side-finding: material subtypes gate live GI (hair
   family → bit 512, eye subtype 25 → bit 1024) — partial subtype decode
   before `probe-both` ever launches.
2. ~~**G-U5, payload sentinel — BUILT AND PARKED, launch pending.**~~
   **PASSED ON SCREEN 2026-08-30/31 — `56-SENTINEL-RESULT.md`.** Rung A
   (`sentinel`, cullMask 0 + patched miss handshake) came back **dark**; rung B
   (`sentinel-b`, all operands verbatim, stock CHS) **paints cyan on geometry
   with the sky clean in the same frame** — so the injected static trace
   executes and round-trips a CHS-written payload. Interpretation table was
   pre-registered in `55` §4 and read before the screen; identity-when-dead was
   the negative control and the sky is where it fired. **`GOTCHAS`' flat "a
   second `OpTraceRayKHR` does not execute" is overturned** — it was one sample
   in the *shadow* family with hand-picked SBT indices; H2 is dead, H3 was the
   real cause (`56` §4). Two limits carried forward: the **miss** leg is *not*
   established (A was dark), and only the **reference raygen** family was
   tested. Gates traced thickness AND all of `29` Part B — both now open.
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

## 9. Post-launch analysis runbook (written 2026-08-30 night, pre-launch)

> **ALL THREE LAUNCHES ARE DONE (2026-08-30 23:57 → 2026-08-31 00:17).**
> §9.1 `probe-both` → `57-SUBTYPE-DECODED.md`. §9.2 `sentinel` → dark, then
> `sentinel-b` → **pass**, both in `56-SENTINEL-RESULT.md`. This section is kept
> as the pre-registered plan it was; the results supersede its "next" columns.
> Ordering note for the record: `sentinel` was run **first** and `probe-both`
> last, the reverse of the numbering here — they share no state, and doing the
> CET-selector rungs before the hand-edited one avoids the `brdf_params.txt`
> reset dance. Do it that way again.

State at time of writing: everything below is **deployed and cmp-verified**
(`make install` backup `20260830-231725`; `init.lua` in the game dir is
byte-identical to root; `skin.set/` carries `probe-both`, `sentinel`,
`sentinel-b`). All of tonight's work is **uncommitted** — `git status` shows
it; nothing was committed on purpose (house rule). The two launches below
were NOT run yet as of this writing. A clean session picking up afterwards:
read this section, then the doc each step names. **Trust the journal and the
audit before trusting any pixel** — serve first, then look.

### 9.1 Launch: `probe-both` (G-U4 + A2/A3 gate)

- Selected by hand-editing `brdf_params.txt` (`skin=on`,
  `skinspec=probe-both`) — NOT in the CET selector, and CET resets the file
  after every launch, so re-write it each time. The CET warning
  "running 'probe-both' but the selector says 'off'" is the **confirmation
  it served** (`40` §launch runbook). Launch through Steam so sync runs.
- Verify serve: `./dev/ab_launch_audit.py 1` — expect the compute skin
  overlay serving 76 modules (the 77th, `ab0bc2fe`, writes an int
  sample-index buffer and is correctly absent — `46` §12), 0 rejects.
- Captures → `a-b-testing/probe-both/S*.png` (skin, cloth, chrome
  cyberware, eyes, hair in frame if possible).
- Decode: `./dev/patch_subtype_probe.sh --legend-md` prints the
  palette↔value key; `40` §0 carries the pre-registered falsifier table
  (vanilla-looking `sub` next to painting `cls` = the sub-enum read is
  broken; uniform single colour = constant field, a different and
  interesting result). **Calibration anchors from `54`:** hair-family
  subtypes and eye subtype 25 are independently confirmed live in GI's
  light-channel logic — the decoded legend must be consistent with those
  two or the decode is wrong.
- What the outcomes gate: sheen paints ⇒ A3 peach fuzz buildable (`51` §5
  caveat: additive, must modulate the existing highlight — `0d`);
  chrome has its own subtype ⇒ A8 gate passes; subtype meanings ⇒ G-U4
  closed, `40` §10 has the follow-on table.

### 9.2 Launch: `sentinel` (G-U5 — the gate for traced-thickness ear glow)

- Selected from the CET Skin build selector (registered). Settings contract
  = `gi-50`: PT on, `ser=class`, `shadowset=full-shadow`, standing PT
  switches, RR pinned and verified in the collect snapshot. Sync refuses
  the rung otherwise.
- Verify serve: `./dev/ab_launch_audit.py 1` — expect 12 `rgs_reference` +
  4 `rgs_restirgi` + **10 `ms_empty_main`** HITs, 0 rejects, manifest echo
  `sentinel …`.
- Readout is binary, by eye, pre-registered in **`55` §4** (read it BEFORE
  interpreting anything):
  | saw | means | next |
  |---|---|---|
  | magenta | injected trace + payload round trip work | build traced transmission (§7 step 3); skip B |
  | dark, frame == gi-50 | trace dead OR miss mapping failed | launch `sentinel-b` |
  | (B) cyan on geometry, dark sky | traces execute; only miss-0 mapping failed | transmission still viable — it rides the CHS path B proves |
  | (B) dark too | injected static traces don't execute in this family | G-U5 fails; fallback is B4 screen-space thickness (worse, tile-quantised) — re-read `39` §6 before building anything |
- On a pass: the transmission build spec is §7 step 3 + the design target
  quote above; per-channel extinction constants come from the same Jensen
  set as `52`/`53` (ld = 3.67/1.37/0.68 mm). Site machinery: `50` §1 and
  `dev/build_gi_bleed.sh` are the templates; `55`'s handshake pattern is
  how the thickness ray reports back.

### 9.3 The rest of the board, unchanged

`kernel=spectral` and the bleed family are look-confirmed (user A/B, this
page item 5). D3 waits on its consumer-naming read (§4). M1 waits on the
RR-off falsifier (§6). A8 waits on 9.1's legend. U3/B2 are retired (`54`).

## 10. Post-gate board (2026-08-31, after `56`/`57` — what is now possible)

All three gate launches are read. The ranked five now: **A6 + A7
look-confirmed and standing** — the user runs `skinspec=gi-50-bleed` +
`kernel=spectral` and that combination is the **standing base config**; every
A/B below is one variable at that base. **A8 dead** (§5). **D3 unchanged** —
its gate is offline and still unrun (§4). **M1 unchanged** — still waiting on
the RR-off falsifier (§6), settings-only, can share any session.

### Unblocked by G-U5 (`56`)

1. **Traced-thickness ear glow (§7 step 3) — now a build, not a gate.**
   **BUILT 2026-08-31 (`59`): three rungs (k=0.10/0.22/0.45) over
   `gi-50-bleed`, validated offline, parked, registered, deployed
   (cmp-verified 01:41). LAUNCHED 01:46 — look FAILS, three structural
   defects, mechanism confirmed; `60` has the verdict and routes.** The
   constraints below were the brief, carried from `56`:
   - **CHS path only.** The miss leg is unproven (rung A dark). Thickness
     comes back via the armed-word handshake (`55`): word still armed after
     the trace = no hit inside tmax ⇒ transmission 0, identity. Nothing may
     depend on a miss shader writing anything.
   - **Build it in the reference family** — the only family the gate proves,
     and the right site anyway: skin hits live in its path loop. First build
     task is confirming L (or −L) is in scope at the skin hit; `50` §3's
     lesson is that assumed inputs die on contact with the disassembly.
   - Class-1 gate is sufficient AND complete — skin does not split
     (`57` §3.2), so there is no per-subtype refinement to chase.
   - ld = 3.67/1.37/0.68 mm (same Jensen set as `52`/`53`); the red glow is
     the spectral falloff, no tint knob.
   - Templates: `50` §1 serve machinery, `dev/build_gi_bleed.sh`, `55`'s
     clone-by-id splice. Optional rung, A/B at the standing base. Not
     working until the screen says so.
2. **`29` Part B — the skin ray budget.** Item 4 (the sentinel) gated all of
   it and passed. Buildable in `29`'s own order: skin bounce bump (§B3,
   tiny, honest caveat: wrong lever for "vague faces"), skin sample loop
   (§B4, the real lever, largest patcher change since AgX; photo-mode
   feature per §B7). §B6 shadow rays stay deferred — the shadow family was
   NOT retested (`56` §4) and it is where `sctrl` died. `29` items 1–2
   (CharacterLightBlockers look, RayNumber / AdaptiveSampling re-test) never
   needed the gate, cost minutes, and are still unrun.

### A3 peach fuzz — was the one gated item; gate PASSED hours later

- **A3 gate PASSED 2026-08-31 00:47 (`58`).** The user ran `probe-sheen`
  alone (serve audit-verified, settings pinned): white grazing sheen on
  clothing, vegetation and skin — `40` §10's "rim on everything" row,
  expected for an ungated probe and the pass. A2 cloth is alive, the
  doomsday null is dead. A3 is now a **build**: class-1-gated Charlie
  lobe, `0d`-bounded, one look A/B at the standing base. `58` §3 carries
  the one-variable caveats (that frame's face is vanilla+sheen, not
  base+sheen). Raygen-side sheen stays a non-route: no NoV in scope at
  the gi-50 sites (`50` §3).

### Suggested next session (per §8: diagnostics share, look A/Bs are one variable)

1. ~~Offline, no launch: build the ear-glow rung.~~ **DONE (`59`).**
2. ~~Launch: ear-glow A/B at the standing base~~ **DONE 01:46 — FAILED on
   look (`60`); route decision is the user's, (b)'s offline CHS read first
   if any.**
3. ~~Launch, same session: `probe-sheen`~~ **DONE — user-run 2026-08-31
   00:47, PASSED (`58`); the A3 build replaces it on this list.**
4. ~~Free rider whenever convenient: the RR-off look (M1 falsifier,
   settings-only) — confirm `DLSS_D: false` in the snapshot BEFORE shooting.~~
   **DEAD (`79`).** RR has been off since; the falsifier never discriminated.
