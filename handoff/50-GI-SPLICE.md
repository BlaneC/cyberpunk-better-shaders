# 50 — The bounce-lit skin writer is the ReSTIR-GI diffuse family, and c1 now rides it

One probe launch (2026-08-30 19:36). The S2 face moved **red** — the diffuse
raygens' paint — by −0.32..−0.35 in ln(G/R) against three in-frame controls
and the R3-off null, every face sub-region agreeing. 48 §8's decision table
row "red" fired: **splice Site A**. Built as `skinspec=gi-50` / `gi-100`,
parked, staged, **unlaunched** — the A/B is the next session's first move.

## 1. The probe that ran

`skinspec=probe-gi` (built by `dev/build_probe_gi.sh`, patcher tier `gi` in
`dev/patch_subtype_probe.py`): class-1-gated hue multiply at every raygen
radiance write. reference ×12 **green** ×[.3,3,.3] · restirgi diffuse ×4
**red** ×[3,.3,.3] · restirgi spec ×4 **blue** ×[.3,.3,3]. Compute probe off
(the rung ships no compute files → the 77 resolvers served **vanilla**, so
this launch also had no tier-1/real-gloss — one variable: the paint).

Deltas against 48 §8 as written, each forced by a verified fact:

- **SER.** User mid-task: *"enable SER. Just keep it on and trust it works."*
  So the 12 reference paints were built ON `ser.set/class` (one file =
  ptq+SER+paint), `ser=class` went into the live params, and
  `sync_settings.sh` grew an **in-skin** mode: when the skin rung owns
  `rgs_*` ids it materialises **nothing** into `swaps.ser` (first-file-wins
  would kill the paint silently) and journals `ser=class:in-skin`. This
  launch is therefore **the first ever to serve a SER splice** (`46` E9 note:
  every prior launch had ser=off). Zero `ser_reject`, game ran. `41`'s serve
  path is now proven; its perf claim is still not.
- **Two reference permutations have no radiance write.** `40c6faab`,
  `ab7f1822` accumulate via SSBO atomics (fixed-point ×10000) — shipped as
  unpainted ser passthroughs, documented in the rung MANIFEST.
- **A provenance guard in sync** (`sync_settings.sh`, the `gi_refuse` block):
  any raygen-bearing skin rung must carry MANIFEST fields
  `src_ser/ser_sha/ptq_sha`; sync recomputes both shas **every launch** and
  refuses the rung loudly (`skinspec=off:gi-no-manifest / gi-stale-ser /
  gi-stale-ptq / gi-shadowset / gi-needs-ser`) instead of serving a probe
  over the wrong base. The `gi-needs-ser` path was negative-tested offline.

Serve verified from the journal before any pixel was read
(`./dev/ab_launch_audit.py`, which now prints manifest echoes and dispatch
lines): **12 `rgs_reference_main` + 4+4 `rgs_restirgi_*` HITs**, overlays
`skin+shadowcull+ptq+ptrefl`, manifest echo `probe-gi ref=12(painted=10,
atomic-pass=2)… ser_sha=310513f3 ptq_sha=55ed4e5c`, `ser=class:in-skin`,
0 rejects. (`trace_rays` "dispatched raygens" is weak evidence: under
vkd3d-proton the DXR libraries are multi-entry modules and the rgs name can
alias any entry — a listed `ms_empty_main` "raygen" is that artefact, not a
serve failure. `ptbounce`'s on-screen effect rides these same files.)

## 2. The readout

Captures: `a-b-testing/probe-gi/S{1,2,3}.png` (user-placed, **not**
photo-mode — no photomode files exist after 19:00; framing matches the R
sets). Null: `a-b-testing/R3-off` (18:18, skinspec=off = tier-1-only
compute). Metric: median ln(G/R) over hand-placed regions on linearized
sRGB, face minus in-frame non-skin control, probe minus null. Controls
between the two launches agree to ±0.01 (S1 jacket +0.704 vs +0.705, sand
−0.187 vs −0.188) — that is the empirical floor, and it also bounds every
cross-launch confound (below). Every number in this section and §6
regenerates from `a-b-testing/reproduce_50.py` (boxes embedded there).

| scene | vs hair | vs jacket | vs floor/ground/sand | reading |
|---|---|---|---|---|
| **S2** Afterlife (bounce) | **−0.318** | **−0.346** | **−0.338** | face LESS green / MORE red — the diffuse family's paint |
| S3 alley (shade) | +0.074 | +0.071 | +0.083 | slightly greener |
| S1 sun (control) | +0.088 | +0.104 | +0.101 | slightly greener; face bfrac 0.145→0.090 |

S2 face sub-regions (Δ probe−null): forehead −0.64, eyes −0.34,
cheeks/nose −0.19, mouth/chin −0.17, chest (independent region) −0.32 —
the shift is everywhere and **scales with how bounce-dominated the region
is**. Channel shares on the S2 face: R +32%, B −26%, G ≈flat.

Interpretation per the palette: every painted family multiplies B by 0.3
except spec (B×3) — B collapsing on the S2/S1 face means the painted
families carry the skin's indirect light and **spec's share is nil**. R
rising past G on S2 names **restirgi diffuse** as the dominant bounce
writer in the target scene. G rising past R on S1/S3 (+0.07..0.10, small
but 4–10× the floor) says **reference carries a real but secondary painted
share outdoors** — consistent with 48 §5's "the one term bounce light
rides", and left for a later rung (Site B stays unbuilt; never two families
between observations).

Caveats, honestly priced:
- **RR ran OFF in the probe launch** despite the user intending it on: the
  quit-time `UserSettings.json` write (19:48:17, after the last capture)
  says `Ray Reconstruction=False`, and any mid-session Apply would have
  been overwritten only by quit-state. The inverse of `47`'s "RR-off
  attempts silently ran RR on". Immaterial here — the ±0.01 control
  agreement bounds RR's chroma effect below the floor, and RR is not
  class-aware — but **these frames must never enter an RR-on radiometric
  comparison**.
- The null served 77 tier-1-c1 compute modules; the probe served zero
  (probe rung = raygens only). c1 is a scalar on the **direct** term —
  chroma-neutral, dim-S2-inert (~106 lum switch-on, `46` §14).
- CET writes `brdf_params.txt` CRLF and rewrites it at quit: two hand-edits
  in a row missed their line by assuming the ending. Edit CR-tolerantly.

## 3. Three more 48 §9 claims died offline

(48 already lost §4's ">>5 dominates" during the probe build — the
guarded-fetch phi trap; `find_gi_class`'s fixpoint walk is the fix, and the
served probe is its proof.)

1. **"NoV is in scope" — false.** In all four diffuse modules, no dot
   against the pixel normal dominates the write, and **no view vector is
   ever computed** (Lambert needs none). Proven by structural hunt
   (scratchpad `nov_hunt`/`view_hunt`): the only dominating normalize is an
   octahedral decode of a reservoir record, not V.
2. **"NoL @ the write" — false.** The lit arm's NoL (`%1446` in `006ba4e3`)
   is computed under the final-visibility branch and does not dominate the
   merged `%1375/77/79` site §9 names.
3. **The four are not one shape.** The **spatiotemporal** pair
   (`006ba4e3`, `038867e9`) re-shades the winning reservoir in its tail
   (`albedo × 1/π × NoL × radiance·W` — the appearance site). The
   **spatial** pair (`5e1e98e4`, `fc60b8a0`) only re-weights radiance
   shaded upstream — its tail divides the radiance back out (the `%217`
   cancellation) and even special-cases class 4 hair; its only 1/π evals
   are the self-normalizing p̂ loops (§9's pdf rule, one level up: they
   reduce through a `dot(·, lum)` — that dot is the discriminator the
   detector uses).

## 4. The splice (`dev/patch_gi_c1.py` + `dev/build_gi_rung.sh`)

One feature, two shapes, both gated on the probe's proven class-1 form:

- **ST pair — c1's NoL-half at the tail shading triple** (the only honest
  angle, per §9's own fallback language):
  `c1_l = (1+(ρ_f−1)(1−NoL)^2.5)(1+(ρ_r−1)NoL^2.5)`, NoL = the module's own
  clamped dot. Spliced by multiplying the three `albedo·(1/π)·NoL` FMuls
  (`%1448/50/52` in `006ba4e3`), found by forward-reachability to the write
  through value ops only (FDiv and the luminance dot excluded — that is
  what separates shading from p̂/W). Upstream of the NaN guard and the
  ±65504 clamps (GOTCHAS: scale before a clamp).
- **SP pair — flat `c̄ = E[c1_l]` (cosine-weighted) at the write channels**
  the probe painted (reach proven on screen; no angle exists there).
  `c̄` = 1.0781 at strength 0.5, 1.1569 at 1.0.
- **No double-scaling:** both pairs write the SAME image
  (`registers[5]+1`, the GI diffuse denoiser input) — alternative finals,
  never chained.
- Untouched: the p̂ loops, `1/pdf`, the spec family, `rgs_reference_main`
  (beyond the unchanged SER passthrough), the ReSTIR reservoirs.

Rungs `gi-50` (ρ 1.175/1.125 — start below the eye, `42` §6: mixed-light
skin already gets compute c1 on its direct term) and `gi-100` (1.35/1.25).
Each rung dir = **93 modules**: 77 `real-gloss` compute (the standing
winner, unchanged — without them the rung would drop the on-screen look and
carry two variables) + 12 reference from `ser.set/class` + the 4 splices.
MANIFEST carries the same guard contract as probe-gi. CET: two new
`skinspec` entries. All spirv-val clean, asserted from the patcher's JSON
reports (site count + uses_rewritten, never byte diffs).

## 5. Staged for the next launch

`skinspec=gi-50`, `ser=class` live; sync smoke-run accepted
(93 materialised, `ser=class:in-skin`, caches cleared). Requirements at
launch: PT on, shadowset=full-shadow, **RR ON and verified** (the pin is
`collect.sh` → `ab_settings.py`; do not trust the toggle).

The A/B: **gi-50 vs `R2-real-gloss`** (18:06 captures, same scenes), an eye
decision on bounce-lit skin — S2/S3 face fullness/warmth, S1 must not move
(direct term untouched; only mixed-light second-order). Two knowingly
carried deltas, both documented: SER (class vs off — spec-neutral to
radiance, user's standing instruction) and RR if it drifts again. If gi-50
is invisible, gi-100 is parked; if S1 moves, stop and re-read §3 here.

Open after this: the reference-green secondary share (Site B, `%683==1`
gate, only after an observation demands it) · the spec family (nil share on
these scenes) · `41`'s perf claim (SER serves now; measure whenever).

## 6. The A/B — gi-50 wins, and S3 carries the proof

Launched 2026-08-30 20:19:36, captures 20:22–20:26. Serve journal-verified
before pixels: `dxil x77 + rgs_reference_main x12 + rgs_restirgi_spatial x2
+ rgs_restirgi_spatiotemporal x2` — the four spliced files and nothing
else — manifest echo `gi-50 … strength=0.5 flat=1.0781`, `ser=class:in-skin`,
0 rejects. First launch where a swapped raygen is visible by name in
`trace_rays` (`1ddeee1de7a88da0.rgs_shadow_main`); the aliasing caveat from
§1 still applies to the rest. RR: `true` at quit, written 24 s after the
last capture — held ON through the shoot, same as R2. The axis is fair.

**User verdict, unprompted, against `R2-real-gloss`:** *"I like these pics
better… They're sharper and they have a bit more… correctness to them? It
feels like there's more complexity in the shading of the face maybe?"*

**The numbers corroborate — on the one scene that can testify.**
Method as in §2: median ln(lum) and ln(G/R) over hand-placed regions,
face minus in-frame control, gi-50 minus R2.

- **S3 is the clean pair.** All three controls (hair, jacket, ground)
  match between the shots to ≤0.008 ln — that scene's lighting is
  stationary across the 2h20m session gap. Against every control the face
  moves the same way: **+1.2..1.8 % luminance, −0.009 ln(G/R)** — up,
  and achromatic, exactly the splice's shape (a scalar on GI diffuse).
  A 3×3 face grid (each cell vs the hair anchor) shows the lift is
  **structured, not flat**: forehead row ±0.008 (the floor), lower face
  +1.8..+4.4 % at jaw/chin — largest where direct light is weakest and
  the GI-diffuse share highest. That gradient *is* the mechanism, and it
  is also literally the user's "more complexity in the shading."
- **S2 is disqualified**, by eye before by numbers: different NPCs in
  different positions between the shots (white-shirt vs leopard-coat at
  the counter, an occluder shadow on R2's floor tiles that gi-50 lacks),
  and the controls disagree among *themselves* by ±0.05..0.09 — scene
  state drifted by more than the expected +2..8 % signal. No reading.
- **S1 face moved +18 % with controls unmoved (≤0.015)** — and that is
  the confound's signature, not the splice's: the factor is hard-capped
  at ×1.175 *on the GI-diffuse component alone*, which in direct sun is
  a minor share; +18 % total is out of reach by an order of magnitude.
  The face also shifted redward (−0.046 ln(G/R)) while sand/hair/jacket
  held ±0.002: a lower, warmer sun hitting the one near-vertical surface.
  The shots are 2h16m of real time apart and the in-game sun moved.
  §5's "if S1 moves, stop" tripwire assumed a same-session pair; this
  pair cannot test the prediction either way.

**Lesson for the protocol:** a cross-session A/B pair is only
lighting-matched in scenes with stationary light (S3 interior: yes;
S1 sun, S2 crowd: no). If a sun-lit delta ever matters, reshoot both
sides in one session — the R2-vs-R3 pairs matched to ±0.01 at 12 min
apart, which is what "matched" looks like.

All figures above: `a-b-testing/reproduce_50.py`.

**Decision: `skinspec=gi-50` is the standing rung**, live in
`brdf_params.txt` with `ser=class`. `42` closes: tier-1 `c1` now reaches
bounce-lit skin, on screen, eye-preferred, measured. `gi-100` stays
parked — worth one look in a future session if the user wants the effect
louder; the S3 numbers say gi-50's lift sits comfortably above the floor
already.
