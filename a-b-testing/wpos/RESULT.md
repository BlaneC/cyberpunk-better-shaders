# wpos (`hunt-wpos*`, handoff `99-WORLD-POS.md` §10) — 2026-09-02

Four launches, **one capture**. Read `99` §10 for the analysis; this file is the
evidence index.

## The four launches, verbatim from `~/callisto_launches.log`

    2026-09-02T20:29:21-05:00  skinspec=hunt-wpos-ctl   skin_sha=4dc824ca77d95feb  payload=c87c5d1342c466b1
    2026-09-02T20:33:47-05:00  skinspec=hunt-wpos       skin_sha=81095d4aff8c0f73  payload=216c8b1faa1c26f2
    2026-09-02T20:36:23-05:00  skinspec=hunt-wpos-cam   skin_sha=492dc8e4db029413  payload=680b49f24f520c42
    2026-09-02T20:48:34-05:00  skinspec=hunt-wpos-frac  skin_sha=19161b2acdd5d01f  payload=36067d003d8b8480
    all four: shadowset=full-shadow  sc_sha=57ef80ee1f72f54a  ptq=rcbm
              ser=class:in-skin  ptrefl=on  refract=fres  ptrefl_sha=ff8e6a509e516b73
              tier=on  cache=cleared

Every `skin_sha` re-derives from the parked bytes:
`cat ~/.local/lib/callisto/skin.set/<rung>/*.spv | sha256sum | cut -c1-16`.
`hunt-wpos-frac`'s was written down in `99` §10.7 **before** its launch.

## Captures

| file | rung | source |
|---|---|---|
| `F-frac-205714.png` | `hunt-wpos-frac` | `photomode_02092026_205714.png`, 2560×1440, md5 `94c0835bd93871d4e1257ddbda970c65`, copied verbatim |

**`hunt-wpos-ctl`, `hunt-wpos` and `hunt-wpos-cam` produced NO captures.** The
newest photomode PNG before those three launches is `photomode_02092026_201141.png`
(20:11:41), which belongs to `98` §15's `-pxfw` shoot. Their result — `hunt-wpos`
welded to the environment, `hunt-wpos-cam` sliding with the camera, i.e. **P is a
world space** — rests on the live read-out alone and cannot be re-measured.

## What `F-frac-205714.png` shows, measured (numbers re-derived in `99` §10.8)

V stands against a flat wall; no road and no horizon, so this is **not** the
anchor frame `99` §10.7 pre-registered. The wall alone carries both headline
readings.

* **Up axis = blue = component 2 = Z.** Column band x=1540–1600: blue resets at
  y = 158, 678, 1198 (jumps +41…+56 of 255); red is flat through both edges
  (largest positive jump +1.6), green steps only +7.1. Blue rises with height ⇒
  **+Z up**.
* **Unit = metre.** Column band nearest V (x=1410–1460): resets at y = 170, 682,
  1195 ⇒ **512.5 px/cell**. V spans hair top y≈457 to boot sole y≈1402 =
  **945 px = 1.844 cells** ⇒ cell = **1.00 m at V = 1.85 m** (0.95 m at 1.75 m,
  1.03 m at 1.90 m). The user, independently: *"hed just be under 2 squares"*.
* **Handedness NOT read** — a lateral red sawtooth exists (row band y=150–190,
  red → 0.0 at x≈835 and x≈1252, period 417 px, green continuous) but it is on a
  differently-oriented part of the facade (its own vertical period ~485 px), and
  the wall's facing was never recorded.
* **V's skin is NOT red** — lit arm 214.7/165.9/126.9, shadowed arm
  182.9/160.0/128.6, wall beside V 193.3/173.0/152.8, **0.00 %** of arm pixels at
  R≥250 against a class-1 tint of ×3 on red. Frame-wide saturated red is 0.39 %
  of pixels and sits on the chairs at frame left, not on V. `99` §7's void row
  fired; `99` §10.8e argues the row was over-strict, since the serving proof is
  the `skin_sha` plus the deploy `cmp` and the paint is demonstrably live at the
  emitter's exact period.

## User read-out, verbatim

> "hunt-wpos-cam translates with the camera just like how we wanted. When you
> rotate the camera upwards on the x axis (x axis  left and right from pov of
> camera y forwards). When looking upwards I see some squares up at the top of
> buildings translate left to right. When looking downwards, I see those squares
> go right to left. Otherwise the squares follow the character. hunt-wpos stay
> locked onto the environment."

> "At the anchor the squares smooth out pink to white from left to right. There's
> about 5-6 squares across a lane on a street. 1.5 across a door."

> "The squares are definetly in meters. Check the latest photomode.png for proof
> but trust me. Its meters. If you lined up V to those squares hed just be under
> 2 squares"

`hunt-wpos-ctl` drew **no remark at all** — an absence, not a stated pass.
