# 57 — G-U4 on screen: the sub-enum is real, readable, and too coarse to build on. A8 dies.

Written 2026-08-31, from the third launch of the night. `probe-both` (`40`,
parked since 2026-08-30) went on screen for the first time. **`40` §0's
falsifier does not fire** — so G-U4 opens — but the field does not subdivide
the character materials that every idea riding this gate actually needed.

Capture and records: `a-b-testing/probe-both/{RESULT.md,S1.png}` (= the shot
`Launch3-test.png`), `UserSettings.{pre,atshoot}.json`.

---

## 0. Verdict

| question | answer |
|---|---|
| is the sub-enum readable from the **compute** G-buffer fetch? | **YES** — the frame paints in more than one hue |
| is `& 31` folded away by the optimiser? | **NO** |
| does **chrome / cyberware** carry its own subtype? | **NO** — and this kills A8 |
| does **class-1 skin** split into subtypes? | **NO** — question (c) answered without spending `c1sub` |
| does **hair** carry more than one subtype? | **YES** — at least two, corroborating `54` |
| did A2/A3 (sheen) get answered? | **NO — the merge confounded it.** See §4 |

## 1. Serve — verified before any pixel was read

    2026-08-31T00:17:27  skinspec=probe-both  skin_sha=69af98424a5e9c18
    76 dxil + 12 rgs_reference_main HITs, 0 ser_reject
    overlays: ser, skin, shadowcull, ptq, ptrefl

`skin_sha` matches `40` §7's recorded hash for `probe-both` exactly. 76 dxil is
correct: the 77th (`ab0bc2fee876d489`) declines with *"no image write reachable
for the sub-enum paint"* and is the single difference between the probe's 76 and
the shipping skin overlay's 77 (`40` §1, `46` §12).

Settings **pinned and proven** — last `UserSettings.json` write 778 s before the
first capture. Same contract as the two sentinel launches.

Selected by hand-editing `brdf_params.txt`; CET reset `skinspec` to `off`
afterwards, exactly as `40`'s launch runbook says it would. Expected, not a
fault. Restored to `gi-50-bleed` after the shoot.

## 2. Falsifier check (`40` §0) — does not fire

The frame is **neither vanilla nor one uniform colour**. Per `40` §10's `sub`
table that is the *"several distinct hues correlated with material regions"*
branch: the sub-enum is readable in compute and carries per-material
information. **G-U4 opens** — with §5's caveat on how far the decode reaches.

Note the trap `40` §0 called in advance and which did **not** occur: a
uniformly-zero field would paint bright orange-red everywhere, not vanilla, and
would have meant a fragment-stage-only field. Vegetation reads green and Johnny
reads differently, so the field is populated as compute sees it.

## 3. Measured

Dominant-channel clustering over head bounding boxes, near-black dropped:

    region             red-dom   green-dom  neutral
    L-NPC head          71.4%      9.3%*      0.8%
    R-man head          70.6%      1.2%      11.7%
    masked NPC head     46.5%      6.5%*     18.1%
    Johnny head         20.5%     23.2%      36.1%
    (* background vegetation inside the bbox — ratio matches the world sample)

Point samples (ratio = R:G:B normalised to sum 1):

    sample                 RGB                  ratio
    L-NPC hair        [ 58.2  28.6   1.5]   0.659 0.323 0.017   B crushed to 1.7%
    L-NPC jacket      [176.9  56.8  27.7]   0.677 0.217 0.106
    L-NPC skin        [186.8  97.7  72.6]   0.523 0.274 0.203
    R-man skin        [ 74.2  50.6  26.7]   0.490 0.334 0.176
    R-man cheek plate [185.5  96.5  64.4]   0.536 0.279 0.186   <- CHROME
    Johnny tank       [114.1 176.2 135.9]   0.268 0.413 0.319   green-dominant
    vegetation        [ 59.0 122.1  88.8]   0.219 0.452 0.329

For reference, palette entry 0 (bright orange-red) normalises to
`0.694 0.278 0.028`; entry 9 (dark orange-red) normalises to the **same**
ratio — see §5.

### 3.1 Chrome has no subtype — A8's gate FAILS

The R-man's cheek plate reads `0.536/0.279/0.186`; his own adjacent skin reads
`0.500/0.305/0.194`. Same hue family, inside albedo noise. The user's
independent unprompted read of the whole frame: *"I dont see normal cyberware
get any different colour on bodies just eye balling it."*

`51` §5 step 2 gates thin-film iridescence on chrome cyberware having its own
subtype. It does not. The stated fallback is ObjectID-hashed film thickness,
which `43` already rates as noise-per-object.

**Recommendation: A8 is dropped, not rebuilt on the fallback.** It was ranked
fourth of five in `51`'s look order; the gate it was waiting on has answered no.

### 3.2 Skin does not split — question (c) answered, `c1sub` launch saved

All four characters' skin lands in one red/orange family, and skin, fabric and
hair on ordinary NPCs share it. `40` §10's `c1sub` row: skin painting in **one**
colour answers question (c) *no* — class 1 has no usable sub-structure, so
there is no face-vs-body-vs-cyberware-skin BRDF specialisation on this route.

`c1sub` is parked and need not launch. That is a whole launch saved by a
merged probe, which is the merge earning its keep — unlike §4.

### 3.3 Hair carries at least two subtypes — `54`'s anchor corroborated

Every ordinary NPC's hair is red-dominant (L-NPC `0.659/0.323/0.017`, R-man,
masked NPC). **Johnny's is green-dominant**, and his head clusters 36.1%
neutral / 23.2% green against ~71% red for the others.

`54` established from the light-channel logic that the **hair family holds
multiple subtypes** (hair family → bit 512). Two distinct hair readings on
screen is independent corroboration of that from a different instrument.

**One correction to the first reading of this frame.** Johnny's pale face was
initially taken as evidence he is unpainted. It is not: he is the
brightest-lit subject, and entry 0 `(3.20,1.28,0.13)` blown out through AgX
desaturates toward cream. His face is consistent with the same paint as
everyone else. **The hair is the load-bearing observation** — dark albedo ×
entry 0 would be dark orange, not green.

### 3.4 The `54` eye anchor is untestable here — not contradicted

Eye subtype 25 should paint bright cyan `(0.13,3.20,3.20)`. The eyes read
orange/amber with sclera matching surrounding skin. This is **inconclusive, not
a falsification**: `46` records that the class probe reached eyes on only ~30
sun-clipped catchlight pixels, so eyes barely register in these 76 modules at
all. A frame with a large, close, unclipped eye would be needed to test it, and
nothing currently rides on the answer.

## 4. What this launch COST — the merge confounded A2/A3

> **Update, later the same night: `probe-sheen` ran alone (user launch,
> 00:47) and answered it — the sheen renders; A2/A3 YES (`58`). The section
> below stands as the record of the merge mistake.**

`probe-both` paints **and** sheens the same modules (151 paint writes, 437
sheen sites). The paint dominates the frame, so **no grazing-rim judgement is
possible** and the sheen question is unanswered.

`38` §7 proposed the merge to save a launch. It saved the `c1sub` launch
(§3.2) and spent the sheen answer. That trade was not priced when the merge was
designed, and it is a bad one, because `40` §10 rates a **sheen-null** as *"the
strongest single result available from this launch"*: an ungated 16-instruction
additive lobe at 464 sites producing no pixels — while a paint in the *same
modules* does — would rule out **every future BRDF edit at the specular site in
the compute evaluators**, gated or not. Cloth sheen, retro-reflection, the hair
dual-lobe revival, all of it, and `22`'s feasibility question answered no for
good.

**If A2/A3 is still live, `probe-sheen` deserves its own launch.** It is parked
and needs no rebuild. Lesson for the next merge: **do not merge a probe whose
readout is a hue with a probe whose readout is a highlight.** They compete for
the same pixels.

## 5. Weaknesses — read before quoting any sub-enum INDEX from this

- The paint is a **multiplier on radiance**, not a replacement. Observed hue =
  albedo × palette × lighting, then AgX. **No absolute index is recoverable.**
- The palette is **hue-degenerate in pairs**: 0 and 9 normalise identically
  (`0.694,0.278,0.028`) and differ only in brightness (3.20 vs 0.45); so do
  10 and 31. Tonemapping destroys the brightness discriminator.
- The scene is a **desert** — naturally orange. "Red-dominant" is therefore weak
  evidence on terrain and hills specifically. It is strong on hair (B at 1.7% of
  total) and fabric, which cannot be that saturated naturally.
- A rigorous decode needs a **vanilla control at the same camera** to divide out
  albedo. None was shot. **§3.1–§3.3 are ratio comparisons *within* the frame**
  — chrome against adjacent skin, hair against hair — and survive this. Index
  claims do not.
- One scene, four characters, daylight exterior. No cloth-heavy interior, no
  car paint, no road.

## 6. Net effect on the board

| item | before | after |
|---|---|---|
| G-U4 | unanswered, gating A8 + A3 | **open**, field readable but coarse |
| A8 iridescence | ranked 4th, waiting on the gate | **DEAD** — no chrome subtype (§3.1) |
| question (c), skin sub-structure | open, `c1sub` parked | **answered no** (§3.2); `c1sub` need not launch |
| hair subtypes | inferred from `54`'s static read | **corroborated on screen** (§3.3) |
| A2/A3 sheen | unanswered | ~~still unanswered~~ **answered YES 00:47** — user-run `probe-sheen` (`58`) |
| `40` §10's legend decode (E11) | open | **still open**, and §5 says it needs a vanilla control, not another probe |
