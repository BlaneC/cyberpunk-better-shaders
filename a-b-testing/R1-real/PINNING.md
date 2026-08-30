# R1 `real` — settings pinning: RR was ON, established after the fact

R1 was shot before `dev/ab_settings.py` existed, so no snapshot predates it.
`UserSettings.post.json` here is the game's write at **17:53:41**, 43s after
the last capture (17:52:58), and it reads `DLSS_D: false`. That looked
alarming until R2 established how the file is actually written.

**The game writes `UserSettings.json` on Apply, while it is running** — proven
at R2: the file was written 18:05:41 with the game launched at 18:04:48 and
still running afterwards. It is *not* an exit-only flush.

That closes the only loophole. The timeline:

| time | event | `DLSS_D` |
|---|---|---|
| 16:57:07 | L8's write; read directly and recorded in `handoff/49` §0 | **true** |
| 17:44:38 | R1 launches — loads the file as it stands | **true** |
| 17:49:24 / 17:51:32 / 17:52:58 | S1 / S2 / S3 captured | **true** |
| 17:53:41 | Apply write — RR toggled off | false |

Because writes land on Apply, **no settings change occurred between 16:57:07
and 17:53:41** — an unwritten change is not a thing. So R1's three captures
ran on the 16:57 state: **Ray Reconstruction ON**, matching R2.

Corroborating pixel evidence, from before the write-on-Apply fact was known
(kept because it is independent): against E1/E2a — known RR-on, same framing,
same character — R1's fine-energy in regions `skinspec` cannot reach was
grass 22.76 vs 22.92 / 22.79 (**0.7%** apart, under the ~3% S1 non-skin floor
of `46` §16.2) and sky 1.403 vs 1.412 / 1.414, while the face moved +10.4%
(11.09 vs 10.05). A denoiser swap is global; it cannot leave grass and sky
untouched while moving only the face.

**Status: pinned by argument.** Every rung from R2 on is pinned by timestamp,
which is cheaper and stronger. Nothing in the ladder turns on this note —
R1, R2 and R3 all ran RR on.
