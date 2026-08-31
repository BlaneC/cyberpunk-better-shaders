# 58 — A2/A3 on screen: the ungated sheen RENDERS. The specular-site family is alive.

Written 2026-08-31, from the fourth launch of the night — a **user-run** launch
(hand-edited `brdf_params.txt`), read back through the audit and the settings
pin afterwards. `probe-sheen` (`40` set 2) went on screen alone for the first
time. **The doomsday null did not occur.**

Capture and records: `a-b-testing/probe-sheen/{RESULT.md,S1.png}`
(= `photomode_31082026_004916.png`), `UserSettings.atshoot.json` in the same dir.

---

## 0. Verdict

| question | answer |
|---|---|
| does an additive lobe at the compute evaluators' GGX sites reach the screen? | **YES** — white grazing sheen on clothing, vegetation and skin |
| A2 — does it reach **cloth**? | **YES** — the jacket rim is the load-bearing observation (§3) |
| A3 peach fuzz — buildable? | **YES** — as a class-1-gated, shaped, `0d`-bounded version; one look A/B |
| `40` §10's doomsday (sheen-null while paint lives ⇒ no specular-site edit can ever land) | **DEAD** |

## 1. Serve — verified before any pixel was read

    2026-08-31T00:47:48  skinspec=probe-sheen  skin_sha=5d24091dd8e9e93d
    82 dxil HITs, 0 ser_reject; overlays: ser, skin, shadowcull, ptq, ptrefl

`skin_sha` matches `40` §7's recorded hash for `probe-sheen` exactly; 82
modules is the recorded module count for the sheen rung (464 of 481 GGX sites).

Settings **pinned and proven**: `ab_settings.py check` reports the last
`UserSettings.json` write 535 s before the capture, no change during the shoot.
Same contract as the three gate launches: PT on, PT-in-photo-mode on, **RR
off**, DLSS Balanced, RayTracedLighting Psycho, 2560x1440.

## 2. Observed

User's read: *"Its producing white pixels nicely. Not just on the sheen of the
face but also vegetation and clothing."* Image read agrees: white velvety rim
along the jacket shoulders and folds, whitened dry grass throughout, a rim on
the shadow-side edge of the face.

That is `40` §10's second sheen row, nearly verbatim: *"rim on **everything**
… the splice works but the GGX sites are shared across materials — expected
for an ungated probe, and it still proves the mechanism. Gate it later; the
finding stands."* The probe is ungated **by design** — an ungated lobe
painting non-skin is the expected pass, not a defect.

## 3. What is and is not one-variable in this frame

- **Clothing and vegetation ARE clean evidence.** vs the standing config, this
  launch's deltas are all inside the skin overlay: the `gi-50-bleed` compute
  work and the gi-50 restirgi splice are absent (both class-1-scoped — the
  audit shows no `rgs_restirgi` swap this launch), and the ungated sheen is
  added. Nothing removed could whiten a jacket or grass; the cloth rim is
  attributable to the lobe.
- **The face is NOT one-variable.** The probe is built on vanilla parents
  (`40` E2), so this frame's face = vanilla + sheen, not `gi-50-bleed` +
  sheen. The face rim is suggestive for A3, not proof of how peach fuzz will
  read over the standing base.
- Weaknesses, stated: no same-camera `off` control was shot (`40` §9 demands
  one for a *null*; a positive with a verified serve survives — **magnitude**
  claims do not). No hard non-cloth reference in frame (car paint, road), so
  cloth-vs-plastic separation is untested. Desert grass is naturally pale, so
  the vegetation read is weak alone — clothing carries the result.

## 4. Net effect on the board

| item | before | after |
|---|---|---|
| A2 cloth track | unanswered since `22`, confounded by the `both` merge (`57` §4) | **alive** — mechanism proven |
| A3 peach fuzz | gated on this launch | **a build**: class-1 gate + Charlie shape + `0d` bounds, A/B at `gi-50-bleed` + `kernel=spectral` |
| specular-site BRDF family (cloth sheen, retro-reflection, dual-lobe revival*) | at risk of the doomsday null | **alive** (*hair BRDF stays in Removed — this is not an invitation) |
| `22`'s feasibility question | open | **answered yes** at mechanism level |

Next when wanted: build the real A3 rung (gated, shaped, bounded), one
variable at the standing base. If magnitude ever matters, shoot the `off`
control from the same camera first.

## 5. Confidence

| claim | confidence |
|---|---|
| the sheen lobe rendered this frame | **certain** — serve audit-verified, settings pinned, added white read independently by user and model |
| A2: the lobe reaches cloth | **high** — jacket rim, with every removed delta class-1-scoped |
| A3 will look good as peach fuzz | **unknown — that is an A/B, not a gate** |
| cloth separates from plastic | **untested** — no hard reference in frame |
