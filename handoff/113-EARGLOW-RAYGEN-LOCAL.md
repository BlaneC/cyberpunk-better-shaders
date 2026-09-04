# 113 — Ear glow from LOCAL lights, rebuilt at the raygen's light-sample site (`earglow-ll`)

**Status 2026-09-03 22:3x: SHOT AND KEPT — user verbatim *"earglow-ll looks great!"* — and made the DEFAULT under the stack name `…-curv-t7hue1-ll` (§11).** Built, gated 9/9, verified from shipped bytes, parked, installed.
Four rungs on the shipped default, selectable as `skinspec`:

| rung | what it is | content sha | raygen-half sha |
|---|---|---|---|
| `earglow-ll` | the default + ear glow from local lights at the raygen's NEE site, k = 7.2787 (`111`'s `-hue1` model, untouched) | `076f3108e312ef4f` | `2786dfdb0fac2763` |
| `earglow-ll-hi` | same, k × 2 — louder, nothing else | `01a0fd0402236d19` | `255c176c06e59fd1` |
| `earglow-ll-hit` | DIAGNOSTIC paint on skin, per backlit light: BLUE / AMBER, scaled by the light (§9) | `8b9138803a5d3ac7` | `848e9081da0a7ac7` |
| `earglow-ll-ctl` | byte-identical to the default (93/93 `cmp`) | `728b63de50c2a6a5` | `cffd5626d09a6dd5` |

Base = `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1`
(content `728b63de50c2a6a5`). Only the **10 `rgs_reference_main`** permutations
differ; the 2 pass-through raygens, the 4 restirgi and the 77 compute
resolvers are the base's, verbatim. **No BDA slot, no layer dependency** —
the raygen already holds the acceleration structure, the light records and
the surface point.

---

## 0. Why a third build of the same term

Ask, verbatim: *"bda-rq-probe -> direct sunlight reads BLUE on skin. And yes
please scope the anchors against the raygen disassembly. Rebuild it at the
light sample site."*

`112` spliced this term into the 77 compute resolvers and was shot invisible
(`112` §12): under path tracing the resolvers' painted write carries sun + sky
and no local-light radiance on skin. `103`'s probes then proved the layer's
slot, fixup and traversal work (GREEN, BLUE) — so the mechanism was fine and
the *pass* was wrong. Local light under PT is shaded in the raygen, by its own
next-event estimation over a per-cluster light list. This document moves the
term there. `112`'s rungs stay parked and selectable as the negative
reference; the BLUE verdict is recorded in `103` §13.

## 1. The site, from the disassembly of the SHIPPED base

Census over all 10 target raygens (`dev/disasm/earglow_ll/asm`, disassembled
by the build from the parked default, not from an older asm dir — the
`compute-base-asm` lesson). Each raygen has **two** light loops; only one can
carry the term.

**Loop 1 — the exhaustive loop (the site).** Per light record (64 bytes,
`OpRawAccessChainNV` stride 64: pos @0, half2 range/radius @12, colour @16,
flags @28, spot dir @32, spot half2 @44, scales @60), in vanilla ids of
`1271d3815051da17`:

```
toLight = lightPos − P − cam                       %3421 %3423 %3425
d2      = NMax(dot(toLight,toLight), 1e-7)         %3429
skip    = (dot(N,toLight) < 0) OR (d2 > (range+radius)²)   %3441 | %3437 → %3442
          OpSelectionMerge %3443 / OpBranchConditional %3442 %3443 %3444
%3444:  d = Sqrt(d2) … L = toLight/d … atten (Select on flags&1: windowed
        inverse-square | linear) × spot NClamp → %3496 … × colour → the
        light's radiance … shadow OpTraceRayKHR flags 12, tmax
        NMax(0, 0.85d − 0.075d·c + 0.15d·c·√rand) … two 6 mm skin rays
```

The guard **skips backlit lights before the radiance exists** — exactly the
lights that make an ear glow. So the splice goes in the block that *ends* with
that guard, before its `OpSelectionMerge`, where every record field, `toLight`
and `d2` are live and the guard has not fired. The attenuation × spot chain is
cloned from inside `%3444` with the engine's `Sqrt` re-pointed to a fresh one
(33 pure ops per site; the cloner refuses phis, stores, Function loads and
image ops), so `E_c = atten_spot × colour_c` is the engine's own unshadowed
radiance for *this* light on the *far* side of the ear.

**Loop 2 — the resampled-importance loop (declined).** Same record layout,
guard threshold `1e-5` instead of `0`, and **no shadow trace inside its lit
block**: it builds a reservoir and traces only the chosen light afterwards
(`%4197` trace at line 4553). A backlit ear can never be chosen because the
candidates are filtered inside the loop. Lighting it would mean changing the
engine's sampling, which this build does not do. The finder declines it by
that shape and the reports record it (10 of 10, threshold `9.99999975e-05`).

**Loop 3** (stride-8 records, trace at 10769) is not a per-light loop of this
shape and is untouched.

Anchors, all re-derived per module and asserted (`dev/patch_earglow_ll.py`):
the guard shape above (exactly one accepting site per raygen, or the patcher
dies); the record colour = the one stride-64 offset-16 `v3float` load between
the loop header and the guard; `atten_spot` = the one factor that multiplies
all three colour extracts inside the lit block, an `FMul(NClamp, Select)`;
the guard's normal triple `== find_origin_offset`'s normal; the sun NEE's
offset origin `%2914` and acceleration structure `%2913` (both dominate the
loop — the engine itself consumes them inside `%3444`); the loop's single
preheader (`%3368`: the one unconditional `OpBranch` to the header from
outside the loop).

## 2. The term

Per loop, **once per path vertex per sample** (in the preheader, 37
instructions):

```
skin   = (G-buffer word & ~31) == 32            class-1, find_class_fetch cloned
p0     = path counter == 0                       patch_cavity2.find_path_counter
A      = rayQuery flags 517 from (0,0,0) along the module's own primary view
         ray, t ∈ [|P|·0.999, |P|·1.001 + 1e-4], mask Select(skin∧p0, 39, 0)
hoist  = skin ∧ p0 ∧ A.committed ; idA
```

Per light, before the guard (120 instructions):

```
d = Sqrt(d2);  L = toLight / d
gate = hoist ∧ (dot(N,toLight) < 0) ∧ ¬(d2 > (range+radius)²)
mask = Select(gate, 39, 0)                      a shut gate = two free misses
B    = flags 545 (cull front) from the sun NEE's offset origin along L,
       tmin 1.5 mm, tmax 18 mm  → t_B (guarded: 18 mm when missed), idB
C    = flags 517 from origin + L·(t_B + 1 mm) along L, tmin 1 mm,
       tmax NMax(0.8·d − (t_B + 1 mm), 0)
ok   = gate ∧ (B.committed ∧ idA == idB) ∧ ¬C.hit
E_c  = atten_spot(cloned) × colour_c
T_c  = 0.5·(exp(−a1c·t) + exp(−a2c·t))·tint_c,  t = NMax(t_B, 6 mm)   (111 v7)
W    = Select(ok, k, 0) · NMax(−dot/d, 0)
acc_c += NMin(T_c · W · E_c, 100)
```

The three accumulators are added at every non-trivial radiance write, the
same pattern as `rq3`/`v7` for the sun (25 writes over the 10 raygens; the
constant-zero and scalar-broadcast writes are skipped as before). Sum over the
sample loop, no division — the same convention `v7` uses, so **k is `v7`'s k
unchanged**.

Query C's reach: the engine's own shadow ray stops at 0.775–1.0 d so the
emitter's mesh is never an occluder; 0.8 d does the same and is what the
verifier demands.

## 3. What is deliberately NOT applied

- **The light record's scale bytes** (word 60: two 0.01×byte scales chosen by a
  global mode flag) and the **"affects diffuse/specular" flag bits** (28: bits
  8/16, OR'd with a per-pixel word). They are on/off and mode-selected;
  ordinary lights carry 1. `E` is `atten × spot × colour`, nothing else. The
  reports say `per_light_scales: not applied`.
- **Path throughput.** The gate holds `counter == 0`, where the throughput
  phis are seeded 1. `v7` ignores it for the sun for the same reason.
- **Loop 2.** §1.
- **Any change to the engine's own radiance, shadow rays or sampling.**
  `OpTraceRayKHR` count is asserted equal to the base (120 over the 10).

## 4. Gates (`dev/build_earglow_ll.sh --install`, all green, log verbatim)

```
=== 0. base: gi-50b-…-curv-t7hue1
  10 target raygens disassembled from the SHIPPED base (not from an older asm dir)
=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)
  10 of 10 round-trip byte-identically
=== 2. the transmittance model (111 v7, -hue1 point)
  k = 7.2787, tint = [1, 0.02927, 0.1279], rates R [865.4, 648.5]
=== 3. patch + assemble the four rungs
  swaps.earglow-ll: 93 modules, 10 raygens differ from the base, spirv-val (vulkan1.4) clean
  swaps.earglow-ll-hi: … 10 …   swaps.earglow-ll-hit: … 10 …   swaps.earglow-ll-ctl: … 0 …
  ll / hi / hit differ pairwise on all 10 raygens
=== 4. coverage census (reports)
  earglow-ll      10 sites (guard thr 0, 3 traces in the lit block), 10 resampled loops declined
                  (thr 0.0001), 33 cloned atten ops each, 25 writes; scales: not applied
  (hi, hit: identical census)   earglow-ll-ctl  10 modules, 0 instructions emitted
=== 5. instruction census on the SHIPPED bytes
  earglow-ll      60 Initialize (6 per raygen: sun A/B/C + local A/B/C), 60 Proceed, 20 t reads,
                  40 InstanceId reads, OpTraceRayKHR 120 == base 120      (hi, hit: same)
  earglow-ll-ctl  30 Initialize (3 per raygen: sun A/B/C), 30 Proceed, 10 t reads, 20 InstanceId reads
=== 6. earglow-ll-ctl: 93 of 93 byte-identical to the base
=== 7. verify_earglow_ll.py: 10 permutations, 25 painted writes — ALL PASS for glow (k 7.2787),
       glow k×2 (14.5575), hit; negative control on the base and on -ctl: ALL PASS
=== 8. verifier non-vacuity (each MUST fail): rejected --decoy noc, nomatch, flatk, front;
       ll read as hit; hit read as glow; ll at k×2; hi at k×1; the BASE as a rung; the CONTROL
       as a rung; ll read with --negative
=== 9. MANIFEST provenance: 4 written, src_ser/ser_sha/ptq_sha carried verbatim
  parked -> ~/.local/lib/callisto/skin.set/earglow-ll{,-hi,-hit,-ctl} (93 modules, cmp-verbatim)
```

## 5. `verify_earglow_ll.py` — what it re-derives from the `.spv`, and the 11 things it refuses

From `spirv-dis` of the shipped bytes only, never from reports or a byte diff.
The light site, the record colour, the cloned atten, the gate, the three
queries, the transfer and the writes are re-found here; the sun NEE, the path
counter and the primary ray come from `verify_earglow_rq`/`rq3`, which
implement them independently of the patchers. Per module it proves: one query
type, **six** objects (the sun glow's three + local A/B/C) in the entry
block's variable run; exactly one accepting site and no query in the
resampled loop's guard block; A in the preheader with the 517 flags, zero
origin, the module's own view ray and the ±0.1 % bracket, masked by
`skin ∧ counter==0`; B and C in the guard block on the other two objects with
one shared `Select(gate,39,0)` where the gate's AND-leaves include
`dot < 0`, `¬rangefail` and reach both the hoisted gate and A's commit; B's
origin is the sun NEE's origin id, B's direction is `toLight / Sqrt(d2)` with
a Sqrt defined *above* the guard; C's origin is `origin + L·(t+1 mm)` on the
guarded t and its tmax `NMax(0.8d − (t+1 mm), 0)`; `ok` reaches the gate, the
`idA == idB` compare, both commits and C's *miss* through And/Not only; the
three `E_c` share one fresh `FMul(NClamp, Select)`; the Lambert
`NMax(−dot/d, 0)`; glow: six Exp on `NMax(t_B, 6 mm)` with the model's six
rates, the three tints, `Select(ok, k, 0)` in the guard block (the sun glow
below the NEE carries the same k, so the search is block-scoped); hit: no Exp,
BLUE over AMBER over 0, the ⅓ mean of E; three `NMin(·,100)` and three stores;
every rewritten write adds a load of those accumulators on all three channels;
trace count unchanged.

Refused (gate 8): the four decoys — `noc` (C traced, never consulted),
`nomatch` (no A==B), `flatk` (no transmittance), `front` (gate without the
backlit arm) — and seven cross-reads (mode swaps, k swaps, base, control,
`--negative` on a rung).

## 6. Cost

Per skin pixel per sample, at the primary vertex: 1 query (A) + 37 ALU once,
then per light in the exhaustive loop 2 queries + ~120 ALU. Off skin or off
the primary segment the mask is 0: A/B/C are guaranteed misses, no branch.
For lights in front of the face the mask is 0 too. No new `OpTraceRayKHR`.

## 7. Files

- `dev/patch_earglow_ll.py` — the patcher (site finder, colour/atten anchors,
  the pure-op cloner, modes glow/hit/ctl, `--k-scale`, four decoys).
- `dev/verify_earglow_ll.py` — the verifier (§5).
- `dev/build_earglow_ll.sh` — gates 0–9, shas, `--install`.
- `dev/disasm/earglow_ll/asm/*.spvasm` — the base's 10 raygens, disassembled
  by gate 0; `p.<rung>/` the patched asm + reports.
- `swaps.earglow-ll{,-hi,-hit,-ctl}/` (repo) and
  `~/.local/lib/callisto/skin.set/earglow-ll{,-hi,-hit,-ctl}/` (parked, 93/93
  `cmp`, `MANIFEST.txt` line 1 names the rung and the base, provenance line
  carried).
- `init.lua` (source) → `release/…/init.lua` → live: eight rows added under
  the `earglow7-*` block — the four `earglow-ll*` and, restored, the four
  `earglow-di*` (`112`'s rows had gone into the release copy only and `make
  release` overwrote them). `cmp` source == release == live.

## 8. SETTINGS CONTRACT — state this BEFORE the launch

| setting | value | why |
|---|---|---|
| `ser` | **`class`** | raygen-bearing rung on the base's SER permutations; `ser=off` → `gi-needs-ser` |
| `shadowset` | **`full-shadow`** | raygen-bearing rung; `gi_refuse` checks it |
| `ptq` | unchanged (`ptq_sha 55ed4e5c6884ab71`) | else `gi-stale-ptq` |
| RR / DLSS-D | **OFF** | |
| path tracing | ON, photo mode, camera pinned | |
| frame generation | **OFF — state it** | `100` §7 |
| skinspec | one of the four rungs | |
| the layer | any — no BDA slot is used | the rungs carry no marker; `bda_*` events are irrelevant |

Deploy state at writing (22:13): `make release && make install` done, live
`init.lua` `cmp` == release == source; the four rungs parked 93/93.

**Order:**

1. `earglow-ll-hit` — the per-light paint. Read `status.txt`:
   `want_skinspec=earglow-ll-hit`, `want_ser=class:in-skin`; the swap log's
   `skin_sha` must be the rung's.
2. `earglow-ll`, then `earglow-ll-ctl` on the identical frame.
3. `earglow-ll-hi` only if `ll` reads as "there but faint".

**The frame:** night or interior, sun off the face (the raygen's own sun glow
would confound). A head with an ear or nose bridge between the camera and
**one** local light within its range — the light behind or beside the head
from the camera's view. Then the same pose with the ear *facing* the light
(nothing should be added), and one with a hand or collar between the ear and
the light (C should kill it). A photo-mode PNG of each; `a-b-testing/earglow-ll/`.

## 9. Pre-registered interpretation (written BEFORE any screen)

| # | reading | means | do |
|---|---|---|---|
| 1 | `-hit`: **BLUE** on the far-side ear rim / nostril / thin skin, nothing on the lit face | the chain works: site, instance match, thickness, exit visibility | shoot `ll` |
| 2 | `-hit`: **AMBER** on the far-side ear | thickness ok, the exit point cannot see the light within 0.8 d: a second occluder, or the exit is inside the head | if amber on an open ear, PUSH (1 mm) then REACH (0.8) are the knobs |
| 3 | `-hit`: **nothing anywhere**, `ctl` normal | the scene's lights are all in the resampled loop (§1), or the light is out of range, or `status.txt` says `off:gi-*` | check `status.txt`; try a shadow-casting spot; if still nothing, loop 2 is the next build |
| 4 | `ll`: a red-orange rim on the far ear that `ctl` lacks, hue like the sun glow | **the feature works** | user verdict; consider making it default |
| 5 | `ll`: glow on the lit face | the backlit arm is wrong (N sign) — `-hit` would be blue there too | compare `-hit` |
| 6 | `ll`: glow through a hand/collar | C failed | `-hit` should be amber there; if blue, REACH is too short or PUSH too long |
| 7 | `ll` == `ctl` with `-hit` blue | the accumulator misses the composited write | the writes are the sun glow's; check which write that pipeline composites |
| 8 | `ll` far too bright / clipped | k is `v7`'s sun k; local lights are in different radiance units than the sun cbv | halve k: `--k-scale 0.5`, a new rung |
| 9 | crash/hang on `ll` not `ctl` | a query on an undominated id the validator accepted | `CALLISTO_SKINSPEC=earglow-ll-ctl` reproduces the base; log |

Void: no `skin_sha` line, `skin_sha` ≠ the rung's, `status.txt` `off:gi-*`.

## 10. NOT done

- Loop 2 (the resampled loop): would need a reservoir-side change. Row 3.
- The record scale bytes / flag bits (§3).
- `103` §13's rows 4/6 discriminator (a bare hand under open sky on
  `bda-rq-probe`) is still open; it no longer gates this feature.
- Nothing committed. `git status`: the three `dev/*_earglow_ll.*`, this doc,
  `init.lua`, `CURRENT.md`, `README.md`, `112`, `103`, `111` touched.

## 11. SHOT 2026-09-03 — kept, and made the default

User verbatim, live read-out, no capture: *"earglow-ll looks great! Please add
that to my default look!"*

- `dev/park_alias.sh earglow-ll gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll --install`:
  93/93 `cmp` clean both ways, provenance (`src_ser`, `ser_sha 310513f3008cbde4`,
  `ptq_sha 55ed4e5c6884ab71`) carried. content sha `076f3108e312ef4f`.
- `init.lua`: the default `skinspec` is the new stack name; the `-t7hue1` row
  is labelled the previous default (= `earglow-ll-ctl`); `earglow-ll` stays
  as the short A/B handle for the same bytes.
- Nothing about the shaders moved between §4's build and this promotion.
- Still open: §10's items, and the k-units question (§9 row 8) was not raised
  by the screen.
