# rayq-p (hunt-rayq-p / hunt-rayq-pctl) -- 2026-09-02T16:24:09-05:00 -- PAINT REACHES THE SCREEN. IT IS NOT THE PASS ROW.

`InstanceId` from a ray query at the reconstructed primary hit **does** reach
the frame, and the sky control held. But it does not arrive as flat per-object
silhouettes. It arrives as a hue that appears **only where the reference
raygen's radiance is what you are looking at** -- shadow, ambient-lit surfaces,
glass, chrome -- and it is **unstable frame to frame**. Directly sunlit
surfaces are untinted. The sky is clean. The control is neutral.

Serve verified, per launch, from `~/callisto_swap.jsonl`:
90 dxil + 15 rgs_reference_main + 4 rgs_restirgi module HITs, **0 rayq_reject,
0 ser_reject**, 3x `{"ev":"rayq","action":"enabled","reason":"already_enabled_feature_on"}`,
3x `ser/enabled`, manifest echo
`hunt-rayq-p ... ref=12(10 rayq primary + 2 pass-through) ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71`
(and the same line for `hunt-rayq-pctl`). Identical HIT counts on both rungs.

Settings PINNED and stated before the launch (`98` sec 5.3), echoed by the
launch log:

    2026-09-02T16:24:09-05:00  skinspec=hunt-rayq-p    skin_sha=951c1d09627046ac
    2026-09-02T16:29:25-05:00  skinspec=hunt-rayq-pctl skin_sha=9e7ac409ff8db3f7
    both: shadowset=full-shadow  sc_sha=57ef80ee1f72f54a  ptq=rcbm
          ser=class:in-skin  ptrefl=on  refract=fres  tier=on  cache=cleared
    payload=2828f963dccefd43 (A) / 58876b4699f41581 (B)

Captures: `A1-rayq-p-162640.png`, `A2-rayq-p-162729.png` (rung A),
`B-pctl-163134.png` (control), all 2560x1440, copied verbatim from the game's
photomode directory.

## The read-out (the user, at the screen -- the part no still can hold)

> "Every shadow or shaded area flickers its shadow between different colours
> of the rainbow. Reflective surfaces like glass and chrome wheels as well.
> Sky is normal. The control shades normally."

**The flicker is the primary finding and it is temporal.** Three stills cannot
contain it. Everything measured below is corroboration of the *spatial* half
only; the temporal half rests on the live read-out, and it is the half that
decides the next rung.

## Framing caveat, stated up front

A2 and B share the camera almost exactly -- static geometry is pixel-registered
between them -- but they are **not simultaneous**: traffic differs, and the
frames sit 4 min 5 s apart, over which the sun moved. B is globally ~8 %
darker. Every number below is therefore taken after normalising A2's channels
so that its top-20 % lit pixels match B's (gain `[0.987 0.993 1.015]`), and the
in-frame sunlit and sky controls are reported alongside so the reader can see
what the normalisation did and did not remove. A1 is a **different camera** and
is used only as an unregistered exemplar.

## The measurement

Crops: `crop-shaded-wall.png`, `crop-road-shadow.png` (both registered),
`crop-chrome-wheel.png` (labelled NOT registered).

Registered regions, dark pixels only (mask taken from the *control* frame so
both rungs are read on the same pixels):

    region                    rung        RGB                  Y   (R-G)/Y  (G-B)/Y
    shaded wall + glass       rayq-p      [35.4 33.0 14.6]  27.7    +0.080   +0.951
    shaded wall + glass       pctl        [31.7 31.8 13.6]  25.7    -0.025   +0.939
    left facade, lower        rayq-p      [35.9 32.4 10.2]  26.2    +0.126   +0.932
    left facade, lower        pctl        [31.9 30.8  9.7]  24.1    +0.036   +0.971
    shadowed pavement, right  rayq-p      [62.0 54.5 43.4]  53.3    +0.142   +0.215
    shadowed pavement, right  pctl        [55.1 50.8 38.6]  48.2    +0.087   +0.263

In-frame controls, whole box, no mask -- these are what says the shift above is
not the normalisation:

    sunlit limestone pier     rayq-p    [186.1 147.7 111.6] 148.5    +0.271   +0.251
    sunlit limestone pier     pctl      [172.7 136.5 102.3] 137.2    +0.272   +0.257
    sky                       rayq-p      [92.6 88.0 73.5]  84.7    +0.039   +0.262
    sky                       pctl        [78.5 76.5 66.6]  73.9    +0.025   +0.234

Sunlit stone: `(R-G)/Y` +0.271 vs +0.272 -- **one part in 270**. Sky: +0.039 vs
+0.025. The lit and sky halves of the frame are the same colour under both
rungs. The dark half is not: every shadow region moves +0.09 to +0.11 in
`(R-G)/Y` under `hunt-rayq-p`. That is the paint, and it lands only in shadow.

Because the paint is a *hue that varies across a surface*, the mean is the weak
statistic. The spatial one -- the spread of the 49 px low-passed hue over every
shadow pixel in the frame -- separates the rungs cleanly:

    frame                        shadow%   sd lf(R-G)/Y   sd lf(G-B)/Y
    A1 hunt-rayq-p    16:26:40      25.1          0.317          0.380
    A2 hunt-rayq-p    16:27:29      34.1          0.203          0.392
    B  hunt-rayq-pctl 16:31:34      35.0          0.129          0.393

`(R-G)` spread is 1.6x and 2.5x the control's on the two painted frames; `(G-B)`
is identical across all three (0.380 / 0.392 / 0.393) -- that channel is carrying
the scene's own sky-vs-sun split, which the paint does not touch. The two
painted frames also disagree with **each other** (0.317 vs 0.203) at the same
location seconds apart, which is the still-frame shadow of the flicker.

## Which pre-registered row fired

**None of `98` sec 5.1's rows fired exactly, and that is a defect in the
pre-registration, not a hedge.** Recorded here and beneath sec 5.1 in `98`,
without editing the table:

- sec 5.1 "sky stays unpainted" -- **fired, as required.** The family's built-in
  control held. The frame is not void.
- sec 5.1 "`-pctl` differs from the base in any way" -- **did not fire.** The
  control shades normally. The layer is serving what it claims.
- sec 5.1 "flat per-object silhouettes" (PASS) -- **did not fire.**
- sec 5.1 "everything unpainted" -- **did not fire.** The bracket is not empty;
  do **not** widen it.
- sec 5.1 "one uniform hue" -- **did not fire.** Hues vary.
- sec 5.1 "hue slides with the camera" -- closest 5.1 row, but wrong: the hue is
  not per-object, and it changes on a *static* camera.
- The row the outcome actually matches is **sec 5.2's "hues swim/boil"** -- which
  was pre-registered for the **bounce** family, not this one. The coordinator's
  read attributed it to 5.1; 5.1 has no such row.

## Why 5.1 could not have fired, and it was knowable before the shot

`98` sec 3.2 already says it: "This writes a hue into the radiance the raygen
was already writing." The paint is `OpFMul` into the reference raygen's
radiance stores (sec 2, the 25 write sites), not a store to a G-buffer. So:

1. A directly-sunlit surface's pixel is dominated by terms this raygen does not
   produce. Multiplying this raygen's contribution by a hue moves that pixel
   almost not at all -- hence "lit direct surfaces look untinted", measured above
   as one part in 270 on sunlit stone.
2. A shadowed, ambient-lit, glass or chrome pixel is *mostly* this raygen's
   output. There the hue survives -- hence the cast, exactly where the read-out
   put it.
3. The output then goes through accumulation and a denoiser, so a per-frame
   change in the committed hit becomes a *smoothly varying, drifting* tint
   rather than a hard-edged flicker.

Moving the ray query from the bounce to the primary surface fixed **where the
query is aimed**. It did nothing about **where the paint lands**. sec 5.1's
"flat per-object silhouettes" row silently assumed a G-buffer write, which sec
3.2 had already ruled out. Fixing the aim without fixing the destination could
not have produced that row on any frame.

## Consequences

1. **The mechanism is proven end to end.** A `OpRayQueryInitializeKHR` +
   `Proceed` + `GetIntersectionInstanceIdKHR` spliced into a shipped raygen,
   aimed down the module's own reconstructed primary ray with a +/-0.1 %
   bracket, commits real hits on real geometry across most of the frame, with
   no crash, no reject, no validation break, and a clean sky. Unlock 1's
   *capability* question is answered YES.
2. **The identity question is NOT answered.** "Hues change frame to frame"
   has three distinct causes and this shoot cannot separate them:
   (a) the TLAS is rebuilt per frame and `InstanceId` is a per-frame slot;
   (b) the query commits a *different* hit per frame (TerminateOnFirstHit
   inside a +/-0.1 % bracket can pick a different coplanar candidate);
   (c) the accumulator is showing several frames of different hues at once.
   `-pcust` and `-pprim` are the rungs that separate them (`98` sec 12).
3. **The AS journal is the blocker for reading (a).** It reported
   `distinct_top_addr:0` on both launches, every `as_create` `type:"generic"`,
   32 of 33 `as_build` lines `type:"untracked"`. It cannot currently say how
   many TLASes exist or how often they are rebuilt -- which is exactly the
   question outcome (a) needs. Fixed under task 2 of the same review.
4. **`ray_query` was already enabled by the app.** Both launches logged
   `"reason":"already_enabled_feature_on"` -- vkd3d-proton enables
   `VK_KHR_ray_query` on this device without being asked, so the layer's
   append was a no-op here. The append still matters as a guarantee, but the
   extension was never the risk.

## Open, and NOT gating the feature

- **The chrome crop is not a controlled comparison.** No frame pair in this
  shoot contains the same chrome asset under both rungs. `crop-chrome-wheel.png`
  says so on its face. If chrome specifically ever needs to be argued, it needs
  its own shoot with a parked camera.
- **The road-shadow crop is the weakest of the three** -- the effect is there in
  the numbers (+0.055 in `(R-G)/Y`) but it is near the edge of what a still
  shows. The shaded-wall crop is the one that carries the claim.
- **Two frames, one location.** The temporal claim is the user's, not the
  measurement's. A parked-camera video would settle it in seconds and has not
  been shot.
- `trace_rays` logged 14 lines per launch, all `swapped=0`; the swapped raygen
  does not appear in that throttled sample. Serve is established by the 15
  `rgs_reference_main` module HITs and the manifest echo, **not** by
  `trace_rays`. That throttle should be made rung-aware, or its output stopped
  being read as evidence.

---

## Second shoot, 2026-09-02 17:37-18:27 (`-pcust`, `-pprim`, `-pclosest`)

Full read-out in `handoff/98-RAYQUERY.md` section 13. Captures added here:

- `C-pprim-174636.png` -- `hunt-rayq-pprim` (`skin_sha=a8e4693f85569180`),
  2560x1440, copied verbatim from the game's photomode directory
  (`photomode_02092026_174636.png`, 17:46:36, launch 17:44:07).
- `crop-pprim-facade.png` -- a 1000x700 crop of it at (700,300).

What the frame shows, and it is exactly what section 12.4 predicted: **stable
per-triangle colour blocks** over the building facades, the parked car and the
market signage; a **clean blue sky**; a **sunlit road that is essentially
untinted**. The user's read-out is the part the still cannot hold:

> "hunt-rayq-pprim is constant and consistent. pcust and pclosest flicker. It
> kinda makes colours alot more into triangles of different colours on some
> surfaces but is consistent and doesnt flicker with movement."

**There is no `-pclosest` capture.** The newest photo in the game's directory is
`photomode_02092026_182409.png` at 18:24:09; the `-pclosest` launch was at
18:27:01. That rung's result rests on the live read-out alone.

Reading: `PrimitiveIndex` stable under movement means the query commits the
**same triangle** every frame, so section 12.5 cause (b) is dead -- and
`-pclosest` (flags 513, nearest hit) flickering exactly like `-p` kills it a
second time, independently. Both `InstanceId` and `InstanceCustomIndex` are
therefore per-frame: the TLAS is fully rebuilt each frame with a varying
instance order and the custom index rewritten with it. **The identity is not in
the instance record.** `hunt-rayq-psbt` / `-pxf` / `-pgeom` ask elsewhere;
section 13.7 pre-registers that launch.

---

## Third shoot, 2026-09-02 19:00-19:04 (`-psbt`, `-pxf`, `-pgeom`)

Full read-out in `handoff/98-RAYQUERY.md` section 14. **One** capture exists
for the three launches:

- `D-pgeom-191320.png` -- `hunt-rayq-pgeom` (`skin_sha=5b141d145cdd9554`),
  2560x1440, copied verbatim from the game's photomode directory
  (`photomode_02092026_191320.png`, 19:13:38). It is the only PNG in that
  directory newer than the three launches (19:00:36 `-psbt`, 19:02:37 `-pxf`,
  19:04:42 `-pgeom`), and it post-dates the `-pgeom` launch, so it is that
  rung's frame. **There is no `-psbt` and no `-pxf` capture** -- those two rest
  on the live read-out alone, and both of them are read-outs about *motion*,
  which a still could not have held anyway.

Measured against the two existing frames, on all pixels and on the darker half:

| frame | mean RGB | `(R-G)/Y` all | `(R-G)/Y` shaded | `(G-B)/Y` all |
|---|---|---|---|---|
| `B-pctl-163134.png` (control) | 107.3 / 98.5 / 81.9 | 0.031 | 0.029 | 0.123 |
| `C-pprim-174636.png` | 118.7 / 104.3 / 87.1 | 0.062 | 0.085 | 0.115 |
| `D-pgeom-191320.png` | **127.9 / 87.0 / 67.5** | **0.207** | **0.302** | 0.138 |

A **single red cast over the whole frame**, an order of magnitude past the
control on the red-minus-green axis and roughly 7x on the shaded half, while
the green-minus-blue axis (the scene's own sky/sun split) barely moves. That is
the numeric form of the user's "every single wall, person, and car is red", and
it is `GeometryIndex == 0` everywhere: `h = 0 * 2654435761 = 0`,
`h ^= h >> 15` leaves 0, `h & 7 = 0`, and bucket 0 of the palette is
`red (3.00, 0.20, 0.20)`. Section 13.7 pre-registered exactly this row.

---

## Fourth shoot, 2026-09-02 19:51-20:15 (`-pxfw`, `-pxfq`) -- THE PASS

Full read-out in `handoff/98-RAYQUERY.md` section 15. **Six** captures, all
`hunt-rayq-pxfw` (`skin_sha=ca0b93c66b2b62ba`): the six PNGs in the game's
photomode directory between 20:00:58 and 20:11:58 sit after the 19:51:00
`-pxfw` launch and before the 20:15:18 `-pxfq` launch, so all six are that rung.
Copied verbatim as `E1-pxfw-200044.png` .. `E6-pxfw-201141.png`. **There is no
`-pxfq` capture**; that rung rests on the live read-out alone.

> "pxfw -> Movers stay sorta stable, but they might slowly get a different hue
> when they enter a different area. Very stable otherwise. pxfq -> unstable,
> occulusion from other objects changes the hue behind movers. Every sampled ray
> behind a mover takes a random colour"

Low-passed to 32x32 blocks, so texture cannot be mistaken for object structure:

| frame | lowpass sd `(R-G)/Y` | distinct hue cells |
|---|---|---|
| `B-pctl-163134.png` (control) | 0.058 | 29 |
| `C-pprim-174636.png` (per-triangle) | 0.092 | 55 |
| `D-pgeom-191320.png` (one hue) | 0.160 | 37 |
| **`E1..E6-pxfw`** | **0.181 - 0.401** | **76 - 163** |

Three to seven times the control's block-scale hue spread and three to five
times its distinct-hue count -- and unlike `-pprim`, whose confetti a 32-pixel
low-pass averages away, the variety **survives** the low-pass. That is
object-scale colouring as a measurement rather than an impression.

Reading: static geometry flat and stable under camera motion, on a rung whose
only difference from the unstable `-pxfq` is `+ cbv[..][56].xyz`. **The TLAS is
built in camera-relative space**, that CB member is the camera offset, and
`ObjectToWorld[3] + cb[56].xyz` quantised to 1 cm is a frame-stable world-space
object key. `94` section 3.3's "inferred, not proven" is proven on screen. Two
things section 14.7 did not predict are recorded in section 15.5 (movers change
hue in area-sized steps, not continuously -- unexplained) and section 15.6
(random colour behind movers on `-pxfq` -- the query's hit and the raster's hit
need not be the same object at moving silhouettes, now a standing caveat in
section 3.4).
