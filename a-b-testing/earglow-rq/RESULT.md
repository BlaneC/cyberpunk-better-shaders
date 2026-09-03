# earglow-rq — SHOT. It leaks. Diagnosed, and the fix is built.

Written 2026-09-02. Full write-up: `handoff/101-EARGLOW-RQ.md` §12 (the shot,
the measurements, the diagnosis) and §13 (the pre-registered `rq2` shoot).

## The frames

| file | rung | launch log | `skin_sha` |
|---|---|---|---|
| `A-hit-224607.png` | `earglow-rq-hit` | 22:44:45 | `737f37a613022455` |
| `B-hi-225122.png` | **`earglow-rq-hi`** | 22:49:01 | `90fa5762820c82ac` |
| `C-glowmap-hi-minus-hit.png` | derived: σ=6 low-pass `B − A`, warm gain | — |

**B is `-hi`, not `-rq`.** The middle rung of the ladder was never put on
screen. `-hi` is the *softer, wider* transfer, not a different mechanism.

The two `photomode_020920260 22:08 / 22:09` files also in this folder are the
world-position agent's `hunt-wpos-frac` frames from the earlier VOID capture
(`101` §10). They are kept as the evidence of that misattribution and are not
earglow frames. Do not read anything against them.

## The verdict, verbatim

> Its the same edge case issue as before. The far side of the head is glowing
> at the hairline, underneath her clothes, wrong side of her ear. Side closest
> to the sun isnt glowing any brighter. Eyelid in shaded side of face is glowing

## What the frames measure

Full resolution, per-region blue-channel alignment (residual 2–8 counts,
shifts `dy 0, dx +1..+4`). Exposure between the frames is achromatic and ≤3 %
(desert ground 1.011, sky 1.026, jacket 1.019), i.e. ~2 counts on skin at
level 100 — every number below is 5–40× that.

`Δ = B − A`, sRGB counts, worst first:

| region | Δ R | Δ G | Δ B | ΔR/ΔG |
|---|---|---|---|---|
| lower eyelid, **shaded** side | +51.4 | +20.2 | +2.7 | 2.54 |
| cheek, shaded | +43.3 | +20.5 | +3.7 | 2.11 |
| temple, far side | +43.0 | +29.0 | +8.7 | 1.48 |
| lower eyelid, lit side | +40.8 | +18.1 | +3.2 | 2.25 |
| scalp / hair boundary, far side | +38.7 | +21.9 | +6.8 | 1.77 |
| chin | +19.8 | +11.1 | +1.9 | 1.79 |
| nose tip | +16.3 | +8.1 | +0.6 | 2.02 |
| cheek, **sunlit** | +15.8 | +11.6 | +5.7 | 1.36 |
| neck, under the jaw/collar | +15.2 | +10.1 | +1.7 | 1.51 |
| **ear, far side** | +15.2 | +12.7 | +3.5 | 1.20 |
| forehead centre (lit) | +14.8 | +7.6 | +0.7 | 1.94 |
| upper lip | +12.5 | +4.9 | +0.3 | 2.56 |
| **ear, sun side** | +6.6 | +6.4 | +2.9 | 1.02 |
| chest, inside the open jacket | +0.9 | +5.0 | +2.1 | 0.18 |

The ear — the feature's whole point — is nearly the weakest region on the head.

## The diagnosis, in one line

The gate did what it says: it opens on skin facing away from the sun. On a
front-lit head that is the far hairline, the skin under the collar, the back of
the ear and a shaded eyelid — and on those pixels the sunward ray committed a
backface within 18 mm that **is not the far wall of flesh**: hair cards lying
on the scalp, the inner surface of clothing, the eyeball behind the eyelid.
`70` W1's central claim is false wherever another mesh sits within 18 mm
sunward of the skin. The consistency gate was removed for exactly this class of
false positive, and W1 did not dissolve it; it moved it.

Two of the four complaints are the **design**, not a defect: the back of the
ear glowing is W1 (that is the thinnest sun path on the head), and the sun side
not brightening is the wrap term (`smoothstep(0, wrap, −N·L)` is zero on
sun-facing skin). Both stop being complaints in a **backlit** frame. `101` §7
never said the frame must be backlit; it does now.

## The `-hit` frame could not have been read

Its paint is an `OpFAdd` — an add, not a multiply — but of a bare **3.2** in
absolute radiance. For that to be as visible as `-hi`'s `0.198 · S` you would
need a sun radiance of ~16. Every hit map from here scales its paint by the
same radiance the feature scales by; `earglow-rq2-hit` does.

## §14 — `earglow-rq2-hit` shot 23:34:12 (`9cdea033376b82ad`), WRONG FRAME

`D-rq2hit-234004.png` is the **same front-lit pose as §12**, not the backlit
frame §13 requires — the third front-lit frame against a backlit contract. It
is pixel-registered to `A-hit-224607.png` (`dy 0 dx 0`, desert-ground gain
1.000, control Δ = 0.0), so it is the cleanest measurement in this folder.

Classified by signature (the paints are exactly `(0.32,0,0)·S` and
`(0,0.04,0.32)·S`, so the blue test is the 1 : 8 `ΔB/ΔG` ratio, not a level
threshold; non-vacuous: 1.4 % on `-hi`'s warm glow, 0 on a self-difference):
**35.2 % RED, 9 px BLUE** over the head/torso box. `E-rq2hit-classmap.png` is
that classification over a desaturated D.

- **Red = the fix working.** Heaviest at the far hairline (+124 R), the shaded
  eyelid crease (+62), the shaded cheek (+59), the temple (+57), under the
  jaw/collar (+26) — the instance-match gate rejecting the hair cards, eyeball,
  clothing and mouth interior that §12.4 named *before* this frame existed.
- **No blue is expected front-lit.** From sun-averted skin the sunward ray runs
  along the ear and into the skull, never across it, so no same-instance
  backface lies within 18 mm and the cap correctly finds nothing. The 9 blue
  pixels are all at the **nostril wall**, the one place front-lighting allows.
- **What this frame cannot exclude:** the pinna may not be closed on its medial
  side, in which case a backlit frame also yields no blue on the ear and only
  the nose can ever pass. `101` §13's table discriminates the two and is
  unchanged.

## §15 — `earglow-rq2` shot 23:46:49 (`c62e024e8725ad21`), FIRST BACKLIT FRAME

`F-rq2-backlit-235113.png` — a 1254x940 desktop screenshot, **not** a photo-mode
capture, a different character, and with **no same-pose control**, so it is a
single-frame reading (chromaticity against unaffected skin inside the frame).

Verdict: *"shows the effect still bleeding through the front of faces. Faces in
shadow still get the effect. Otherwise the ears and noses look great."*

- **The ears and noses PASS.** That is `101` §13's pass row; the instance-match
  gate works and none of §12's hair/collar/eyelid leaks are present.
- **The glow bleeds through the shaded FRONT of the face** — inner eye corners
  and nose bridge (R/G 1.84–2.08, G/B 2.1–51), lower lip (R/G 1.65) against
  shadowed skin at R/G 1.27–1.54.
- **Diagnosis:** sunward from that skin the ray goes back INTO the head and
  commits a same-instance wall a few mm away — the eye socket, the nasal cavity,
  the inner lip. Same mesh, thin, and **never lit**. `rq2` measures a thickness
  and assumes the far end of it is in sunlight. The same omission is why a face
  standing in shadow still glows.
- **The S-sign question is closed twice:** from the bytes (query B reuses the sun
  shadow ray's own origin and direction ids) and from this frame (sun behind the
  head, glow on the camera-facing side).

`earglow-rq3` adds query C — sun visibility from the exit point — and is parked.
Read `handoff/101` §16 before shooting it.

## Next

`earglow-rq3-hit` / `earglow-rq3` / `earglow-rq3-hi` are built, gated and parked, and `-rq3-hit`
must be shot first. **Read `handoff/101` §16 first.** The frame must be
BACKLIT — sun low and BEHIND the head, camera on the sun side of the ear, and
the ear clear of hair (this character's sun-averted ear is partly covered).
Also shoot a face standing in the shadow of a wall or vehicle: half the verdict is about that.

---

## §17 — `rq3` SHOT and KEPT (2026-09-03)

Launches: `00:35:14 skinspec=earglow-rq3-hit skin_sha=eed4c2ca8f71f5d3`,
`00:38:40 skinspec=earglow-rq3 skin_sha=359060c26c8c7367`. Both shas are §16.1's,
pre-registered.

`G-rq3hit-003639.png` — the ONLY capture in the window, at 00:36:39, i.e.
between the two launches, so it is the **`-rq3-hit` diagnostic**.
**No `-rq3` frame exists**; the user's verdict on the glow rung
(*"THE EFFECT IS PERFECT. earglow-rq3 is the defacto."*) is **live-only**.

Measured (2560×1440, `R−G > 120` after establishing that an absolute hue test is
worthless in a sunset desert — 35 616 px pass `R−G > 60` on terrain alone):
4 448 painted px, bbox x 1231–1471 y 366–871 (the head). Red by region:
inner canthi 2 429, nose bridge 2 039, hairline 391, lower lip 65, open cheek 0.
**Blue on the head: zero** (4 px whole-frame, all sky; head-box `max(B−G)` = 21,
all of it background sand at x ≥ 1472).

Read-out: the red set is §15's measured bleed set exactly — query C rejects the
interior walls it was built to reject. The blue half is unobservable because the
ear is at the frame edge behind hair (§16.2 required it clear). **No §16.3 row
fires as written**; see 101 §17.5.

---

## §18 — the thickness floor: SHOT, `cap6` KEPT (2026-09-03)

Launches: `01:24:07 skinspec=earglow-cap3 skin_sha=b3c690d79eb0a36d`,
`01:25:56 skinspec=earglow-cap6 skin_sha=2b2a31c414e366b9`. Both shas are
§18.4's, pre-registered. **`earglow-cap4` was never shot.**

**No frames.** The only captures in the window (01:08:29, 01:11:27) are both
BEFORE the 01:24 launch and belong to `100`'s glint launches. The decision —
*"Get a subagent to use earglow-cap6 as the default."* — is **live-only**, and
**none of §18.6's six pre-registered rows can be read**: every one of them is a
child-vs-adult-vs-control comparison in a single frame, and no such frame exists.

The default is now the cap6 stack `…-cone2all-fog-earglow-cap6-glintdense`
(`3bb0aee03a1bfda8`). `cap4` stays parked as the untried middle.
