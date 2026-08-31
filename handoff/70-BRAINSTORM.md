# 70 — The GO NUTS board: candidate endgames for ear glow, priced

Written 2026-08-31 on the user's request ("one last crack… brainstorm a wild
insane solution. GO NUTS"). Ideas ranked by payoff/feasibility; the v5 brief
(`71`) draws from the top of this list.

## W1. AIM THE RAY THE OTHER WAY (cull-FRONT sunward) — the one that dissolves the leak problem

Every version so far traced a REVERSED segment (origin P+2cm·S, direction
−S, cull-BACK) and treated any front-face within the segment as "the far
side of flesh" — that is v1 defect 1's material blindness, which the
consistency gate has been fighting ever since. Flip it: trace **from P
straight toward the sun, cull FRONT faces, tmax 18mm**. Inside a closed
flesh manifold (backlit surface ⇒ the sun is on the other side ⇒ the ray
immediately travels through the interior), the first visible surface is the
sun-side wall seen FROM INSIDE — a **backface at exactly t = the true
sun-path flesh thickness**. Every leak class dies by construction:

- strand/collar card as primary: its own backface at ~0.2–0.5mm → a
  **min-t floor (~1.2–1.5mm; thinnest real ear ≈ 2mm)** rejects it;
- sliver pixel whose primary is the FACE behind a strand: sunward through
  the head → no backface within 18mm → miss (v1's "3mm of skin" reading is
  geometrically impossible now);
- strand stacks faking 2–8mm gaps: the vis ray from the exit point still
  has to reach the sun through the rest of the hair → blocked.

Consequences: the CONSISTENCY GATE BECOMES REDUNDANT and can be dropped —
the term that has been killing true positives since v3 exits the design
entirely. The ray finally measures the quantity the feature always wanted
(sun-path transmission, not local proximity). Falsifier (pre-registered):
if the engine strips interior backfaces from the BVH, everything goes dark
→ revert to v4 machinery + the s-band probe path (`69` §2). Offline read
first: flag semantics (CullFront = 32), CHS/AHS behavior on backface hits,
whether any-hit alpha testing interferes.

## W2. LET THE ACCUMULATOR DO THE DIFFUSION (jittered entry, converged by photo mode)

Real SSS transmission = an integral over an entry AREA, not one point. The
reference PT **accumulates samples in a photo-mode still** — so jitter the
thickness-ray origin per frame within a ~3–5mm tangent disc and the
accumulator Monte-Carlo-integrates the diffusion aperture FOR US. Zero
extra traces, converges to true area-integrated transmission while the
camera sits still; in motion it is one ray of noise the denoiser eats.
Needs offline: harvest a per-frame-varying value (the module's own PT PRNG
chain, or the jitter/frame cbv) + confirm the accumulation path. Pairs
with W1 (jitter the sunward origin along the surface tangent).

## W3. SOFT TRANSFER + WRAP ENVELOPE (the reliable base; `69` §2 Track D)

Beer–Lambert with ld=0.68–3.67mm maps 2–3mm of thickness to 3–20×
brightness — that IS the lightbulb. Sum-of-two-exponentials per channel
(diffusion-profile shape) so t∈[1,8]mm spans ~2–3×, plus smoothstep wrap
on −N·S (and optionally a forward-phase term on D̂·S) so gate borders
feather instead of snapping.

## W4. RIDE THE ReSTIR-GI RAIL (the architectural insanity, held in reserve)

gi-50's c1 term already injects a skin-gated radiance term into the
ReSTIR-GI diffuse path — and ReSTIR's spatial/temporal reuse is a
LATERAL FILTER. Inject the transmission term there instead of the
reference radiance and the engine's own filter diffuses it across pixels,
denoised, for free — and it would glow in live gameplay too. Gated on an
unproven splice family (G-U5 was only proven for rgs_reference_main;
`56`'s scope limit) and a real scope expansion. If v5 fails, this is the
next mountain.

## W5. NEIGHBOR-DEPTH VARIANCE (screen-space sliver detector) — dominated

Fetch raster depth at ±1px (same heap, addressable), suppress on skin-
classed neighbors with cm-scale jumps. Dies to the same grazing-slope
ambiguity as every screen-space discriminator (`65` §1). Dominated by W1;
kept for the record.

## W6. s-BAND PROBE (`68`'s successor) — the measurement fallback

Only needed if W1's falsifier fires and we are back to threshold-land.

## The v5 composition (delegated in `71`)

`earglow` = W1+W2+W3 (full v5) · `earglow-lo` = v4 gates + W3 only
(conservative comparator) · `earglow-hi` = W1+W2+W3 with stronger
softening. All k=0.22 — the ladder is DESIGN, not strength. **Do not tune
k** still stands.
