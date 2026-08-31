# 60 — Ear glow on screen: the TRACE works, the MODEL fails. Three defects, and none of them are the two `39` killed.

Written 2026-08-31, from the user's `earglow-hi` launch (01:46). The look
**fails** — user rejection, artifacts listed below — but the mechanism
finding underneath it is real and extends `56`. Do not delete the rungs
before reading §2; do not rebuild before reading §5.

Capture and records: `a-b-testing/earglow-hi/{S1.png,UserSettings.atshoot.json}`
(= `photomode_31082026_014830.png`).

---

## 0. Verdict

| question | answer |
|---|---|
| does an injected static trace at a **new** site, with **overridden** operands (flags 16, tmax 0.018, new origin/direction), execute and round-trip CHS hit distance? | **YES** — glow requires `hitT < 0.0179` written by the CHS; `56`'s "one step past the evidence" limit is closed |
| did `39`'s tile grid recur? | **NO** — raygen-resolution output, as designed |
| did `39`'s forehead-scores-like-an-ear recur? | **NO** — foreheads are dark; measured thickness did its job |
| is the **look** right? | **NO** — three structural defects (§3), user A/B rejection |
| was it the pre-registered polarity bug (`59` §6 row 3)? | **NO** — polarity verified correct in the deployed binary (§4) |

## 1. Serve and settings — verified before any pixel

    2026-08-31T01:46:12  skinspec=earglow-hi  skin_sha=1dfacfec230f21e9
    77 dxil + 12 rgs_reference + 4 rgs_restirgi HITs, 0 ser_reject
    manifest: earglow-hi … ref=12(10 earglow k=0.45 + 2 pass-through)
    ptq_sha=55ed4e5c6884ab71 (rcbm)

Settings PINNED — last write 504 s before capture, same contract as every
launch tonight (PT on, RR off, DLSS Balanced, 1440p). What is on screen IS
this build; there is no serve doubt.

## 2. The mechanism result — keep this even though the look died

Every red pixel in S1 requires: the injected trace executed, the CHS ran for
a sub-2 cm hit, wrote member 3, and the raygen read it back through the
validity compare. That is a **new static site** (not `56`'s clone-one-line-
later), **overridden** origin/direction/tmax, literal flags 16 — and it
executes in the wild across the frame. `56` §8's "the result generalises …
untested" row is now **tested for new-site-in-the-same-family**. Future
traced features (`29` Part B shadow work aside) ride on this.

## 3. The three defects — all structural, none fixable by k

User: *"its placing the effect underneath clothing, through the corners of
eyes, at the hair seam. Skin in direct sun glows red. Ears even when
ocluded from the head are red."* S1 confirms: red rim at the hairline seam
(left temple), red inner eye corners, red ring around the septum piercing,
orange-red band on the neck under the necklace and collar edge.

1. **The thickness ray is material-blind.** Any front-face hit within 18 mm
   sun-side of P is treated as the sun-side surface of *flesh*. A necklace
   bead 3 mm off the neck, a hair card at the seam, a collar edge, lash/brow
   geometry at the eye corner — each reads as "3 mm of skin" and transmits
   like an ear. The payload carries only hit distance; nothing identifies
   *what* was hit. This is the dominant defect in S1 — every artifact site
   is skin adjacent to close-proximity props.
2. **The term models local thickness, not sun-path transmission.** The 2 cm
   segment cannot see an occluder beyond it. An ear with the whole head
   between it and the sun still measures 5 mm thin and glows. `59` §1's
   occluder story only covers occluders *inside* the segment.
3. **The backlit gate is per-shading-normal, not per-feature.** `%3225` is
   the NEE's own `N·S ≤ 0` on the *shading* normal — which is true inside
   normal-map crevices scattered across a directly lit face (exactly where
   vanilla kills the sun sample). Wherever it opens, defect 1 supplies a
   bogus thin reading, so lit skin picks up red speckle/flush. "Skin in
   direct sun glows red" is this, not a sign error.

## 4. Polarity check — done offline, in the DEPLOYED binary

`spirv-dis` of `skin.set/earglow-hi/d622fb9e…spv`: gate is
`%3339 = (class == 32)` ∧ `%3225 = (N·S ≤ 0)` ∧ `%3340 = (bounce == 0)` →
`%3343 = OpSelect(gate, 39, 0)` → trace mask. Correct as designed; `%3225`
is the identical bool the module's own NEE visibility kill uses. `59` §6
row 3 ("sign fix, rebuild") does NOT apply. The build is faithful to the
design; **the design's inputs are insufficient** — which is `39`'s lesson
one level up: a transmission term needs to know what the light passed
through, and this one only knows how far.

## 5. Routes, priced — decision is the user's

- **(a) Sun-visibility ray from the entry point Q** (second injected trace,
  long, mask 39, NEE-style). Kills defect 2 (occluded ears) and crevice glow
  where the prop shadows Q. Does NOT kill defect 1 when the prop itself is
  the "entry surface" (necklace bead reads as flesh and the sky above it is
  clear). Cost: one more trace per thin-skin pixel; buildable on §2's proof.
- **(b) Identify the hit.** If the radiance CHS writes anything identifying
  the hit surface into payload members 0–2 (instance/material bits), gate on
  hit-is-flesh and defect 1 dies. **Answerable OFFLINE from the CHS
  disassembly — no build, no launch.** This read should happen before any
  other decision; if the payload carries nothing, honest routes narrow to
  (a)-only or (d). **READ DONE 2026-08-31 → `61`: attributes yes, identity
  no; the instance-writing CHS is live-PT's, not this pipeline's — (b) as
  conceived is dead; repriced variants in `61` §6.**
- **(c) = (a) + (b):** entry surface is skin AND the sun reaches it. That is
  a defensible transmission model; residual error is multi-feature paths.
- **(d) Drop it, second strike.** `39` §6 predicted a restart would be honest
  only with a real thickness input; we got one and it measures the wrong
  thing near props. If dropped, keep §2 — the mechanism result outlives the
  feature.

**Do not tune k** (pre-registered, `59` §6). **Do not launch anything** until
(b)'s offline read is done if any fix route is taken. Standing config is
untouched — flip the CET selector back to `gi-50-bleed`.

## 6. Confidence

| claim | confidence |
|---|---|
| serve/settings clean; the frame is this build | **certain** — audit + pin |
| injected new-site trace executes and round-trips hitT | **certain** — glow exists and requires it |
| gate polarity correct as designed | **certain** — read from the deployed binary |
| defect 1 (material-blind) explains the prop-adjacent artifacts | **high** — every artifact site is skin-near-prop; mechanism requires nothing else |
| defect 3 explains lit-skin flush | **medium-high** — consistent with shading-normal crevices; not pixel-proven |
| route (b) is feasible | **unknown — one offline CHS read decides** |
