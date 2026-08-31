# 71 — Ear glow v5: the ray is FLIPPED (W1) + the diffusion look (W3), built and parked

Written 2026-08-31, from 70's board on the user's "explore flip-the-ray"
request. All three rungs built, verified and parked (93 modules each;
earglow sha256 prefix `57f6d895` on 1271d381; selector stays `gi-50-bleed`).
Nothing committed. W2 (jittered entry) NOT built — it needs a per-frame
PRNG harvest that stays a separate offline read; v5 tests W1 clean.

## 1. What changed and why it kills the leak classes

Every version v1–v4 traced a REVERSED segment (origin P+2cm·S, direction
−S, cull-BACK, thickness = T_CAP − hitT) and treated any front face inside
the segment as "the far side of flesh." That material blindness (60 §3
defect 1) is what the albedo gate (v2), the consistency gate (v3), and the
one-sided distance-aware gate (v4) were all patching — and v4's honest leak
test showed the strand/collar leaks RETURN (69). v1's stated reason for the
reversed design — "a forward ray would need back-face hits from inside the
flesh, a configuration no engine ray exercises" — was a fear, never a
measurement, and 56 killed its premise class (an injected trace with
overridden operands executes and round-trips the pipeline's own CHS).

v5 flips the ray:

    origin    = the sun-NEE trace's own origin operand VERBATIM
                (P + the engine's self-hit offset)
    direction = the sun-NEE trace's own direction operand VERBATIM (S)
    flags     = 32 (CullFrontFacingTriangles)   tmax = 18mm
    t         = hitT DIRECTLY = the true sun-path flesh thickness
    valid    <=> 1.5mm < t < 17.9mm   (pre-armed 10000 => miss fails)

The entering front face is culled; inside real backlit flesh the first
visible surface is the sun-side wall seen FROM WITHIN — a backface at
exactly the sun-path thickness. The leak classes die by GEOMETRY:

- strand/collar card as primary: its own backface at ~0.2–0.5mm — under
  the 1.5mm floor (thinnest real ear ≈ 2mm);
- face-behind-a-strand sliver: sunward from the face goes THROUGH THE
  HEAD — no backface within 18mm — miss (v1's "3mm of skin" reading is
  geometrically impossible now);
- strand stacks faking 2–8mm gaps: the vis ray from the exit point still
  has to clear the rest of the hair.

THE CONSISTENCY GATE EXITS THE DESIGN — the term that ate leaks in v3 and
ate the feature (helix rim, ear top) ever since. No praster compare, no
ε_eff, no distance scaling, nothing to tune. Kept from v2: the albedo gate
(0.25; guards non-skin thin backfaces the floor clears, e.g. a leaf) and
the sun-visibility ray with the engine-mirrored self-hit offset, its D now
= S. The gate chain is skin ∧ backlit ∧ bounce0 (mask select) → floor ∧
valid ∧ albedo ∧ vis.

## 2. W3 — the transfer, because v4's remaining failure was the "lightbulb"

69 §1: raw Beer–Lambert (ld 0.68–3.67mm) turns 2–3mm of thickness
variation into a 3–20× cliff, and the binary gates snap at their borders.
The ladder is DESIGN, not strength — all k=0.22, "do not tune k" stands:

| rung | transfer | wrap |
|---|---|---|
| `earglow-lo` | raw exp(−t/ld) | none — **isolates W1**: if leaks die here, the flip did it, not the softening |
| `earglow` | 0.5·(exp(−t/ld) + exp(−t/4ld)) | smoothstep(0, 0.35, −N·S) |
| `earglow-hi` | 0.5·(exp(−t/ld) + exp(−t/6ld)) | smoothstep(0, 0.5, −N·S) |

Red spans ~2× over t∈[1,6]mm on the soft rungs (vs ~20× raw); green/blue
stay steeper — that IS the spectral falloff, hue still reddens with
thickness. The wrap multiplies the k select with the module's own primary
normal (v4's harvest, reused), so the backlit border feathers to zero
instead of snapping.

## 3. Build record

- Shared patcher `dev/patch_earglow.py` now emits v5; `--wide/--wrap` add
  W3 (omitted = raw). Probe mode kept working: the min-thickness floor
  stands where cons stood in the palette (RED = floor fails only —
  literally "this hit is a card's own backface"), vd = hit-valid only so
  floor and albedo read independently. `build_probe_earglow.sh` asserts
  updated; the PARKED probe rung is still the v3-gate instrument.
- v4's detectors kept where used (`find_origin_offset`: offset cbv clone +
  the normal for the wrap); `find_raster_position` no longer called (left
  in the file — the v4 revert path needs it).
- 3 rungs × 93: spirv-val clean; emitted re-read clean, baseline-aware:
  flags-32 trace ×1 with tmax 0.018 and origin/direction ids equal to the
  sun-NEE trace's operands (asserted from the OUTPUT binary); no stale
  flags-16 / 0.10 / 2.5e-5 / 0.003 / 0.0022; Sqrt count unchanged (v4's
  tan term gone); floor >0.0015 = base+1; Exp 3 (lo) / 6 (soft);
  SmoothStep 0/1; albedo 0.25 = base+3; vis ==10000 = base+1.
- Hand-read of 1271d381 (earglow): gate chain, verbatim operands, floor,
  wrap, and per-channel 1/ld · 1/(4·ld) constants all as designed.
- Parked == built cmp-verbatim ×3; MANIFEST provenance carries verbatim
  (contract unchanged: ser=class, shadowset=full-shadow, ptreg ON).

## 4. Known biases, accepted

- The origin carries the engine's own self-hit offset (c0·N slide), so t
  is thickness ± mm-scale registration — same class of bias v4's origin
  had; the floor absorbs the crumbs.
- The exit-point normal comes from the CHS oct pack of a BACKFACE hit. If
  the engine stores it front-side-out (sunward), the vis-ray offset is
  correct; if it flips toward the ray, the vis ray self-hits and glow dies
  — that reads as probe MAGENTA everywhere, distinguishable from the BVH
  falsifier (no paint at all / RED everywhere).
- Interior geometry (teeth, eye sockets) may present nearer backfaces than
  the true far wall — t underestimates there; bounded by the floor.

## 5. Pre-registered table — fill from the launch

| observation | attribution |
|---|---|
| **PASS row**: strand/collar/fringe leaks DEAD *and* ear+nose coverage ≥ v4's, no lightbulb on the soft rungs | W1 wins; leaks died by geometry, the transfer killed the bulb — pick the soft rung by eye |
| EVERYTHING dark, all rungs | **the falsifier**: BVH strips interior backfaces (or culls them via instance flags) → revert to v4 machinery + the s-band probe (69 §2); check with a probe rebuild first (expect NO paint past the base gates) |
| glow present but leaks persist | thin geometry is CLOSED (double-sided cards with a real backface at standoff t>1.5mm) — raise the floor is the only threshold left; measure with the rebuilt probe (RED vs BLUE separation at leak pixels) |
| ears glow, nose dark (or vice versa) | interior occluders (septum/teeth) shorten or lengthen t asymmetrically — read t via the probe's hue split before touching anything |
| soft rungs glow, `-lo` dark | a W3 bug, not W1 — the three rungs share every gate; diff the k-select block |
| lightbulb SURVIVES on `earglow-hi` | transfer steepness was not the mechanism — 69 §1's diagnosis wrong, the remaining candidate is single-tap entry (W2, jittered origin) or lateral diffusion (W4, the ReSTIR rail) |

## 6. Confidence

| claim | confidence |
|---|---|
| flipped ray executes and CHS round-trips on backface hits | **medium-high** — 56 proved injected traces + this CHS handshake; backface-specific behavior (BVH retention, AHS) is exactly what the launch tests |
| leak classes die by geometry if backfaces exist | **high** — construction, not threshold; the floor's 3× margin (0.5 vs 1.5mm) is the only number in it |
| soft transfer + wrap kills the bulb | **medium-high** — unchanged from 69 §3 |
| CHS normal orientation on backfaces | **unknown — §4's magenta signature identifies it on screen** |

## 7. First launch read (2026-08-31 14:26) — dark, but the falsifier is NOT yet established

Serve verified: journal 14:26:41, skin=on, skinspec=earglow,
skin_sha=2816410116762ed5 == the built/parked v5 set (cat *.spv sha), 12
rgs_reference_main swapped, contract satisfied. The two earlier lines
(14:15, 14:24) had skin=off — not v5 evidence.

User: no ear or nose glow. Captures `photomode_31082026_14{2754,2902,2930}`:

- 142754 (front-lit face) and 142930 (profile, sunlit ear): the sun is
  camera-side — backlit gate correctly OFF on all visible skin. Dark is
  the DESIGNED result there; v4 would be dark too. Not evidence.
- 142902 (back of head, genuinely backlit): the only visible ear patch is
  the TATTOOED ear under hair — albedo gate (67: tattoo B=0.0) and vis ray
  (hair shell, 67 magenta) both kill it BY DESIGN in v5 as in v4. The nose
  is not in frame.

So the observation so far is "the kept gates gate" — the v5-specific
question (does the flipped ray see backfaces at all?) is unanswered. The
probe (rebuilt+parked, v5 semantics) answers it in one launch; add to §5's
table one more dark-mechanism, offline-invisible:

| probe readout | attribution |
|---|---|
| NO paint on a bare backlit ear | the falsifier: BVH has no interior backfaces (miss ⇒ t=10000) → revert v4 |
| RED everywhere | CullFront is a NO-OP (TLAS instances built with facing-cull-disable): the ray self-hits the entering front face at the offset distance, under the floor → W1 dead as specified; fallback = keep the flip but skip the entry face by tmin (needs a per-hit distance read, or revert v4) |
| MAGENTA everywhere | backface CHS normal is flipped toward the ray → vis-ray origin buried; fix = negate N in the mirror when N·S < 0 |
| BLUE on bare ear, dark on screen | gates fine, glow term bug — diff the k-select |
| YELLOW/GREEN patterns | albedo gate at 0.25 misbehaving on backface albedo |

Launch: hand-edit brdf_params.txt to skinspec=probe-earglow (before EVERY
launch); ser=class, shadowset=full-shadow, ptreg ON. Shoot the v4-winning
geometries: low sun BEHIND the head, bare (untattooed) ear, and the
sunward-nostril nose shot — 142902's framing but with the plain ear and
the nose in frame.
