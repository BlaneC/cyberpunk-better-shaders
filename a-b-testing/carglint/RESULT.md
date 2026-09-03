# carglint — shot 2026-09-03, 00:55–01:11

Read `handoff/100-GLINTS.md` §12 (the shot record) and §9 (the table that was
pre-registered before any of this existed).

## The verdict, verbatim

> "carglint-dense looks incredible too. Lets keep that around and add it to our
> big giant shader option"

**`carglint-dense` is KEPT.** It is stacked onto the incoming ear-glow default
as `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense`
(content sha `e0de8b9d5a6716d0`, `100` §13).

## The launches, from `~/callisto_launches.log`

All five carry `shadowset=full-shadow`, `ser=class:in-skin`, `tier=on`,
`ptq=rcbm`, `ptrefl=on`, `refract=fres`, `cache=cleared`. **Every `skin_sha`
matches `100` §6's table exactly** — the right bytes were served, five times.

| # | time | `skinspec` | `skin_sha` | matches §6 | capture |
|---|---|---|---|---|---|
| 189 | 00:55:03 | `carglint-cell` | `edacb088d26d95e8` | yes | **none** |
| 190 | 00:57:39 | `carglint` | `0dede3be78b80879` | yes | **none** |
| 191 | 00:58:39 | `carglint` | `0dede3be78b80879` | yes | **none** |
| 192 | 01:06:42 | `carglint-dense` | `16533661e383511e` | yes | `A-dense-010829.png` |
| 193 | 01:10:02 | `carglint-ctl` | `4dc824ca77d95feb` | yes | `B-ctl-011127.png` |

`carglint` was launched **twice** (00:57:39 and 00:58:39) — a relaunch, not two
different rungs; the sha is the same both times.

## The frames

Two, both 2560×1440, copied from the Proton prefix's photo-mode directory.
Attribution is by timestamp against the launch log, which is the only link
available — nothing in a PNG names the rung.

| file | taken | attributed to | why |
|---|---|---|---|
| `A-dense-010829.png` | 01:08:29 | `carglint-dense` | after launch 192 (01:06:42), before 193 (01:10:02) |
| `B-ctl-011127.png` | 01:11:27 | `carglint-ctl` | after launch 193 (01:10:02); no later launch |

**These two are NOT an A/B pair and must not be read as one.** They are a
different camera position, a different car, and a different body colour
(A: copper over a lit forecourt; B: black, camera moved and rotated). Nothing
about the glints can be inferred by differencing them, and no such difference
is claimed here. They are records that a frame was taken on those two rungs,
nothing more.

`carglint-cell` — **the rung `100` §8 said to shoot first, and the only one
that can falsify the whole family** — was launched and produced no capture.

## Which pre-registered rows fired

**Fired:**

- §9.2 row 1 (density), **partially and live-only**: the user preferred the
  dense rung and kept it, which requires that dense was *distinguishable* from
  what came before it. It does **not** establish the monotonic
  sparse < default < dense ordering the row asks for — `carglint-sparse` was
  never launched at all.
- §9.5 row 1 (the control), **live-only**: `carglint-ctl` was launched and drew
  no remark. It is byte-identical to the base (its sha *is* the base's), so
  "no remark" is consistent — but an absence is not a reported pass, and this
  is recorded as such.
- §9.6 (void conditions): **none fired.** Every `skin_sha` matches, the
  contract lines are as stated.

**Not fired, and explicitly NOT passed:**

- §9.1, the whole `carglint-cell` table — **unshot**. The world-offset crawl
  test at this splice site is still open. `98` §15 remains the only evidence,
  and it was measured at a different splice.
- §9.2 rows 2–4 — density ordering and the brightness rows are **unreported**.
  `carglint-sparse` was not launched; nobody said whether dense was brighter or
  merely denser.
- §9.3 (where the glints appear — reflections vs the direct panel), §9.4
  (static vs crawling under camera motion, fireflies, temporal boiling):
  **entirely unreported.** Nothing was said about any of them.

The honest summary: **one rung was liked and kept on a live read-out.** The
diagnostic that could falsify the family, the density ladder, and every
motion/firefly row are still open.
