# 61 — Ear-glow v2: route (b)'s premise dies offline. The instance-writing CHS is not the reference pipeline's.

Written 2026-08-31, worker fork, offline only. Directed build: retype the
reference raygen payload to 5 members, pre-arm member 4, compare the
thickness ray's hit instance against the primary hit's instance (`60` §3
defect 1, route (b)). **Nothing was built.** The directed premise — that the
reference pipelines' closest-hit shaders write `InstanceCustomIndexKHR &
0xFFFF` at payload offset 16 — fails verification: that CHS family belongs
to the **live-PT** pipelines, not the reference ones. The reference CHS
family writes **no identity anywhere in the payload**. The specified v2
would ship a compare between two values no shader ever writes — provably
inert before any launch. Building and launching it would burn a launch to
learn what this document proves offline.

Standing config untouched (`gi-50-bleed` per `60` §5). The parked
`earglow{,-lo,-hi}` rungs still carry **v1 semantics** (`59`) — do not
launch them expecting any of this.

## 0. Verdict

| question | answer |
|---|---|
| does any reference hit group write instance id into the payload? | **NO** — verified across the bound CHS family (§2, §3) |
| which CHS family binds the reference radiance hit groups? | `0b190a1f53c31393.chs_main_{0..18}` — proven by bit-exact codec identity (§2) |
| whose CHS writes `instance & 0xFFFF` at offset 16? | `55f6172c71799e4d` / `37a0cf548031f3b9` — the **live-PT** shading CHS (`06`), payload `{v3float,float,uint}`, pairs with the thin PT raygens |
| is route (b) as specified in `60` §5 feasible? | **NO** — not without also patching the CHS library (§6) |
| was anything built or parked this pass? | **NO** |

## 1. The directed fix and the premise it stood on

The coordinator's read: `55f6172c…chs_main` ends with stores {m0 v3float
radiance, m1 float RayTmaxKHR, m2 uint = InstanceCustomIndexKHR & 0xFFFF}
(true — `dev/disasm/chs/55f6172c71799e4d.chs_main.spvasm:8523-8528`,
decorations `:212-213`, struct `:604`), and the leap: this CHS shares the
reference raygen's payload, so its m2 store at offset 16 lands past the
raygen's 16-byte declaration — recoverable by retyping. The directive said
verify before building. Verification inverted it.

## 2. The binding, settled by codec identity

The reference raygen unpacks its radiance payload with constants that are
exact float32 inverses of what `0b190a1f`'s permutations pack:

| field | CHS pack (`0b190a1f…chs_main_1.spvasm`) | raygen unpack (`dev/disasm/earglow/d622fb9e…spvasm`) |
|---|---|---|
| m0 = albedo RGBA8 | `×255`, OR-shift 8/16/24 (`:655-664,693-695`) | `&0xFF` per byte, `×0.00392156886` = 1/255 (`:2565-2579`) |
| m1 bits 0-23 = oct normal 12+12 | `×2047.5 + 2047.5`, `<<12` (`:688-692`) | `&0xFFF`, `×0.000488400517` = 1/2047.5, `−1`, oct decode + normalize (`:2580-2611`) |
| m1 bits 24-31 = roughness | `×255`, `<<24` (`:693-697`) | `>>24`, `×1/255`, clamp [0.04,1] (`:2611-2621`) |
| m2 = cone/LOD float | `NMax(log2(…)+…, 0)` (`chs_main_5:951-953`) | `×0.1` (`:2613,2621`) |
| m3 = hitT | `RayTmaxKHR` store (every perm) | pre-arm 0, `==10000` miss test (`:2272-2294`) |

Both declare the identical struct `{uint,uint,float,float}`. A `55f6172c`
binding is additionally impossible on independent grounds: its m0 v3float
(radiance) spans offsets 0-11 — the raygen would unpack radiance float bits
as RGBA8 albedo and oct normals, and reference-mode skin would render
garbage. It renders correctly. And `06` already placed Disney shading for
the **thin live-PT raygens** in `55f6172c`; the reference raygen shades
in-raygen (this project's entire mod history is the proof).

## 3. What the reference payload carries — and doesn't

m0 albedo, m1 normal+roughness, m2 cone LOD, m3 hitT. Identity: none.
Every `chs_main_{0..18}` **does** compute `InstanceCustomIndexKHR & 0xFFFF`
— and feeds it exclusively into a conditional `OpAtomicIAdd` feedback
counter, never the payload (`chs_main_1.spvasm:86,245` + block; same shape
in perms 0/5/9/14, spot-checked). `chs_main_0` is a degenerate debug perm
(m1 = `0xFF7F00FF`, per-instance atomic — `:115-131`). The declared struct
is 16 bytes exactly: nothing is written at offset 16 by any reference hit
group. Retype + pre-arm 0xFFFFFFFF + compare ⇒ compare never passes ⇒
feature permanently dead. That is the specified v2, in full, before any
launch.

## 4. Why not build it anyway as a probe

The only thing v2-as-specified could still discover is a never-dumped 20-byte
CHS bound in place of `0b190a1f` (§8). That is a launch-priced probe of dump
completeness against offline evidence that already answers it — exactly the
spend `60` §5 forbids ("do not launch anything until (b)'s offline read is
done"; it is done, and the answer is no).

## 5. Corrected pipeline model (dumped-raygen census, this session)

| payload struct | raygens | plausible CHS partner |
|---|---|---|
| `{uint,uint,float,float}` 16 B | rgs_reference_main, rgs_reflection_{opaque,transparent}_main | `0b190a1f` gbuffer-pack family |
| `{v3float,float,uint}` 20 B | live-PT thin raygens (`06`: fd1d0f0c, c6bce844) | `55f6172c`, `37a0cf54` (Disney in CHS, instance in m2) |
| `{float}` 4 B | rgs_shadow_main, rgs_shadow_transparent_main, rgs_restirgi_{spatial,spatiotemporal} | `510c9f5a` (single-float) |

The reflection raygens sharing the 16 B ABI matter below: a widened
`0b190a1f` would likely be served into their pipelines too.

## 6. Routes, repriced under the corrected model

- **(b′) Widen both sides:** raygen → 5 members AND patch all 19
  `chs_main_N` to append `m4 = instance & 0xFFFF`. Delivers the designed
  same-instance gate exactly. Two risks no offline check retires: the
  pipeline's payload interface size comes from the game's D3D12 shader
  config (16 B) — stages using 20 B violate it, driver tolerance unknown,
  and the prior "the engine already runs that mismatch" comfort **died with
  the premise**; and swaps are global by hash, so unpatched 16 B reflection
  raygens plausibly binding the same library inherit the violation with no
  local fix. Buildable; carries a genuine UB class.
- **(b″) NaN-sentinel on m2:** CHS writes instance into m2 only when the
  incoming m2 is NaN; my trace arms NaN. Keeps 16 B everywhere — but only
  identifies the **thickness** hit. The primary instance is still unwritten
  (the engine arms m2∈{0,1} and consumes the LOD reply). No compare target.
  **Insufficient alone.**
- **(b‴) Attribute gate, zero ABI change:** v1's payload already round-trips
  the thickness hit's **albedo** (m0) — v1 just never read it. Gate on
  hit-albedo ≈ pixel-albedo (primary m0 is live in scope, raw uints
  `%2385/%2400`). Kills metal piercings, dark hair cards, most cloth; a
  skin-toned collar leaks. It is a thresholded heuristic — the ε is exactly
  the kind of knob `39`/`59` banned as a primary mechanism. Defensible only
  as an AND-term, priced honestly as such.
- **(a) Sun-visibility ray from Q** (`60` §5): unaffected by any of this.
  Raygen-only, proven ABI, proven mechanics (v1 §2). Kills defect 2 and the
  prop-shadowed share of defect 3; not defect 1 when the prop is the entry
  surface. **The only fix route that stays entirely inside the proven-safe
  envelope.**
- **(d) Drop, second strike** — unchanged from `60`.

My read, stated as a read: (a), optionally with (b‴) as a secondary
AND-term, or (d). **APPROVED and BUILT the same night — (a)+(b‴), see
`62`; launch pending.** (b′) only if the payload-interface question is first
settled offline (vkd3d-proton source: how maxPipelineRayPayloadSize is
derived; whether the driver pads payload allocation).

## 7. The liveness re-verify the directive asked for

Moot with nothing built, but answered: the radiance trace (`d622fb9e…:2290`,
payload %22) sits inside the bounce loop before the sun-NEE splice site
(`:3583`, payload %21); %22's members are touched only at `:2272-2291`; at
bounce==0 the splice would read the primary hit's payload uncorrupted. The
plumbing was fine. The data isn't there.

## 8. What I could not verify

- **Dump completeness.** The binding proof assumes the 29 dumped hit-shader
  entries cover the reference pipeline's hit groups. Any undumped CHS would
  still have to emit the §2 codec bit-exactly (or reference mode would not
  render), so "no identity available" survives; only a hypothetical undumped
  variant that *additionally* writes offset 16 escapes — unfalsifiable
  offline, and nothing in-repo hints at one.
- **Reflection pipelines actually binding `0b190a1f`** — inferred from ABI
  identity, not from pipeline-creation records. Affects (b′) pricing only.

## 9. Confidence

| claim | confidence |
|---|---|
| reference radiance hit groups = `0b190a1f` family (or codec-identical) | **certain** — bit-exact inverse constants both directions + struct identity + rendering correctness |
| no reference payload member carries hit identity | **certain** given the family; **high** against undumped variants (§8) |
| v2-as-specified is inert if built | **certain**, conditional on the above |
| `55f6172c`/`37a0cf54` belong to live-PT pipelines | **high** — `06`'s session evidence + 20 B ABI match |
| (b′) driver tolerance of 20 B stages in a 16 B-config pipeline | **unknown** — the load-bearing open question for (b′) |
