# 63 — Ear glow v2 on screen: the gates work, and the three survivors share ONE mechanism

Written 2026-08-31, from the user's `earglow` (k=0.22) launch at 08:01. User
verdict: *"WE ARE AGONIZINGLY CLOSE. ITS ALMOST THERE… OTHERWISE IT LOOKS
PERFECT!!"* — v1's five artifact classes are down to three, all of them
boundary cases, and S1 (the v1 disaster scene re-shot) is clean.

Captures: `a-b-testing/earglow-v2/S{1,2,3}.png` + `UserSettings.atshoot.json`
(= photomode 080311 / 080659 / 081129). Serve verified: `skinspec=earglow`,
0 rejects; settings pinned (last write 02:20, captures 08:03+).

## 0. Scorecard vs `62` §5's pre-registered table

| v1 artifact | v2 on screen |
|---|---|
| necklace / septum ring / under-clothing | **GONE** (S1 — same scene as v1's failure) |
| eye corners | **GONE** |
| lit-skin crevice speckle | **GONE** |
| occluded ears | not re-staged, no complaint — presumed killed by (a) |
| hair seam | **SURVIVES as strand glow** (S2/S3 — Panam's temple strands) |
| — new report | Panam's neckpiece top edge glows (S2/S3) |
| — new report | V's forehead glows under his fringe (S1 background) |

## 1. The unifying read: all three survivors are PIXEL↔PRIMARY boundary leaks

The class gate reads the **raster G-buffer** at the checkerboarded launch
pixel. Everything else — the backlit bool, the albedo compare, the thickness
ray origin — lives on the **PT primary hit**. Those two disagree exactly on
sub-pixel boundary slivers: a hair strand over the face, the collar's top
edge against the neck, a fringe line over a forehead. At such a pixel the
G-buffer says *skin* (gate passes), the primary hit is the *prop*, and v2's
albedo compare degenerates to prop-vs-prop — vacuously true. Sun visible →
glow paints the sliver. The rims in S2/S3 follow the strands at exactly the
1–2-internal-pixel width this predicts.

Secondary suspect for V's forehead (a wider band than a sliver): the 0.25
albedo threshold passing brown fringe vs tan skin — the threshold case `62`
§6 listed as unmeasured. Both mechanisms are covered in v3's table.

Denied en route: the reference CHS payload's spare byte (m1 bits 24–31) is
`(1 + slope·t)·phi·510` — ray-cone/LOD footprint, not translucency, not a
material id. No authored mask rides the payload; the fetch-slot decode is in
`chs_main_15` `:1269–1294, :1751`.

## 2. What v3 must do (build delegated; see `64`)

1. **Consistency gate**: the PT primary must BE the pixel's raster surface —
   G-buffer depth (or albedo) at the same checkerboarded coordinates the
   class fetch already uses, compared against the primary hit. Kills all
   three boundary leaks in one term. Gated on the slot being **provable
   offline** (GOTCHAS 13: existence ≠ addressability) — the restirgi G-buffer
   maps from `48`/`50` are the lift source.
2. **Albedo threshold** 0.25 → tightened, justified from the unpack
   semantics, for the V-fringe/skin-toned-prop class.
3. If the slot cannot be proven offline: threshold-only v3, and the gap
   documented as the (b′)/(d) decision point.

## 3. Confidence

| claim | confidence |
|---|---|
| v2's five→three reduction is real | **certain** — same-scene S1 comparison, serve verified |
| survivors are boundary leaks | **high** — mechanism follows from code already read; rim width matches; not pixel-proven |
| V's forehead is threshold, not boundary | **medium** — resolution too low in S1; v3's table separates them |
| payload spare byte is LOD, not a mask | **high** — decoded from the pack math |
