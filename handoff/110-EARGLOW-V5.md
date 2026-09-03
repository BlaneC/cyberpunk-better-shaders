# 110 — Ear glow, v5 and v6. Two screen verdicts, two re-tunes, **the ray queries untouched throughout**. BUILT, GATED, PARKED, UNSHOT.

Written 2026-09-03. **§13** built the fix §3.2 named; **§14 is a second pass
after the v5 shot erased the effect** and replaces the point-estimate style of
§1–§13 with a ladder. Fifteen rungs, twelve offline gates green, thirty decoys
and cross-reads rejected, **no driver self-test and §6 says why**.

> **Reading order if you only want what to shoot now: §14.**
> §1–§13 are the v5 family, which is superseded on screen but not deleted —
> §14.1 and §14.7 only make sense against them. Built on the standing
default `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`
(content `3bb0aee03a1bfda8`). **Nothing on screen. Nothing committed.
`make install` not run.**

## 0. The verdict, verbatim

> "It looks like a lightbulb behind ears. Needs to be like 3/4 less bright,
> moreso just colouring the effected location. Also needs to have a hard
> cutoff at a certain thickness. Getting some transmittance through the upper
> nose bridge which doesn't make sense. The nose bleed effect also carries
> light of a colour that's too yellow. Really shallow depth transmission
> should still be coloured more red."

| complaint | v5's answer | confidence |
|---|---|---|
| "like a lightbulb" / "3/4 less bright" | **(a)** `k` 0.22 → 0.055, one in-place constant rewrite. Red at the floor drops 0.0945 → 0.0236 | **high** — arithmetic, and the constant is read back out of the shipped `.spv` by gate 8 |
| "hard cutoff at a certain thickness" | **(b)** query B's `tmax` 18 mm → `t_cut`. Past `t_cut` the query **misses**, so `hitB` is false, so the accept is false, so the term is **exactly zero** — not small. Plus a 1 mm smoothstep below `t_cut` so the cut has no visible edge | **high** — this is a property of the accept, not of the transfer |
| "transmittance through the upper nose bridge" | **(b)** at `t_cut` = 8 mm. Ears are 2–6 mm and pass; cartilage + bone across a nose bridge is well over 8 mm and misses. `-cut6` / `-cut10` bracket the choice | **medium** — the 8 mm figure is anatomy, not a measurement from this renderer. `-hit` was never re-shot at v5 |
| "colour too yellow" / "shallow should be red" | **(c1)** tint (1.0, 0.40, 0.22) → **R/G 2.48 → 6.19**; or **(c2)** `ld_G` 1.37 → 0.70 mm, `ld_B` 0.68 → 0.35 mm → **R/G 7.31**. Two rungs, never blended | **high** on the ratio, **none** on which one the user wants |
| "**really shallow** depth" | **CANNOT BE DONE WITHOUT TOUCHING THE 6 mm FLOOR.** See §3.2 — this is the finding of this document | **high**, and it is bad news |
| did the ray queries change? | **No.** Gate 4 compares eight ray-query opcode counts against the base, module by module, and every one is identical | **high** |

---

## 1. What moved, and how little

| | edit | instructions |
|---|---|---|
| (a) brightness | `OpConstant %float 0.219999999` → `0.055`, **in place** | 0 |
| (b) cutoff | `OpConstant %float 0.0179999992` → `t_cut`, **in place**. That one id is query B's `tmax` **and** the miss guard's false arm, so "missed" and "at the cutoff" cannot drift apart | 0 |
| (b) fade | `w = 1 − SmoothStep(t_cut − 1 mm, t_cut, t_guarded)`, folded into the k select | **3** |
| (c1) tint | `OpFMul(0.5·(exp+exp), tint_c)` per channel | **3** |
| (c2) rates | four **in-place** rewrites: `1/ld_G`, `1/(4·ld_G)`, `1/ld_B`, `1/(4·ld_B)` | **0** |

`earglow5` / `-cut6` / `-cut10` are +6 instructions and 2 rewrites per module.
`earglow5-rate` is +3 instructions and 6 rewrites. **Untouched:** all three ray
queries, flags 545/517/517, the ±0.1 % bracket, the instance match, query C,
the wrap smoothstep, the firefly clamp, the write shape, the 6 mm floor, and
all 81 non-reference modules.

An in-place rewrite is only taken after `rewrite_const()` proves the earglow
sites are the constant's **only** consumers. On this base every one of the six
is exclusive (one declaration, one or two reads, all inside the glow block); a
module where that stopped being true would abort the build rather than silently
change unrelated shading.

### 1.1 The bug this file's own gate caught

`Module.fconst` is keyed by value and maps `0.22 → %float_0_219999999`. (a)
rewrites **that id** to `0.055`. The blue tint of (c1) is also `0.22`, so the
first build asked for `0.22`, was handed the id that now holds the brightness,
and tinted blue at `k` instead of at `0.22`. `patch_earglow5._fc` resolves
constants by value against the module's **current** lines instead, and
`--decoy tintswap` plus verifier check 7 keep it caught.

---

## 2. The splice, in place

```
  %tq   = OpRayQueryGetIntersectionTKHR %float %qB %uint_1
  %tg   = OpSelect %float %hitB %tq   <tmax>          <- tmax REWRITTEN to t_cut
  %te   = OpExtInst %float %glsl NMax %tg %float_0_006   <- 101 sec 18, UNTOUCHED
  ...
  %k    = OpSelect %float %ok  <k>   %float_n0        <- k REWRITTEN to 0.055
+ %s    = OpExtInst %float %glsl SmoothStep <t_cut-1mm> <t_cut> %tg
+ %w    = OpFSub %float %float_1 %s
+ %kw   = OpFMul %float %k %w
  %W    = OpFMul %float %kw %wrap                     <- operand repointed
  ... per channel c:
  %h_c  = OpFMul %float (OpFAdd(Exp,Exp)) %float_0_5
+ %t_c  = OpFMul %float %h_c <tint_c>                 <- (c1) only
  %m_c  = OpFMul %float %t_c %W                       <- operand repointed
```

**The fade reads `%tg`, the GUARDED t — never `%te`, the FLOORED t.** At
`--cut 0.006`, `%te` is the constant `0.006` for every pixel, a smoothstep over
[5 mm, 6 mm] on it evaluates to 1 everywhere, `w = 0`, and the entire rung goes
black. `--decoy fadefloored` builds exactly that and verifier check 6 rejects
it by name.

---

## 3. The cutoff

### 3.1 Why `tmax` is the cutoff, and why it is exact
Beyond `tmax` query B commits nothing. `hitB` is false ⇒ the accept
`(gate ∧ hitA ∧ hitB ∧ same ∧ ¬C)` is false ⇒ the k select yields `-0.0` ⇒ the
channel adds `-0.0`. **Zero, not a small number.** It also makes the ray
cheaper: traversal stops at 8 mm instead of 18 mm.

Choosing `t_cut` from `101` §5's own table:

| structure | thickness | at `t_cut` = 6 mm | 8 mm | 10 mm |
|---|---|---|---|---|
| child's ear | ~2–3 mm | passes | passes | passes |
| adult ear rim | ~2–4 mm | passes | passes | passes |
| adult ear at the concha | ~5–6 mm | **faded to 0** | passes | passes |
| earlobe | ~6–8 mm | cut | fading | passes |
| **nose bridge (cartilage + bone)** | **>8 mm, often 10–15** | cut | **cut** | borderline |
| cheek, brow, jaw | 15 mm+ | cut | cut | cut |

**`earglow5` ships 8 mm.** `-cut6` is the aggressive bracket and will remove
the thicker part of an adult ear as well as the nose; `-cut10` is the
permissive bracket and may leave a thin nose bridge glowing. That is the A/B.

### 3.2 THE FINDING: the 6 mm floor already flattened everything the user is looking at

`101` §18's `NMax(t, 0.006)` runs **before** the transfer. So on the bytes the
user judged:

| true t | what the transfer actually evaluated | R | G | B | R/G |
|---|---|---|---|---|---|
| 1 mm | **6 mm** | 0.09454 | 0.03818 | 0.01213 | 2.48 |
| 2 mm | **6 mm** | 0.09454 | 0.03818 | 0.01213 | 2.48 |
| 4 mm | **6 mm** | 0.09454 | 0.03818 | 0.01213 | 2.48 |
| 6 mm | 6 mm | 0.09454 | 0.03818 | 0.01213 | 2.48 |
| 8 mm | 8 mm | 0.07622 | 0.02587 | 0.00581 | 2.95 |
| 18 mm | 18 mm | 0.03309 | 0.00412 | 0.00015 | 8.03 |

**Every ear thinner than 6 mm renders at exactly one brightness and exactly one
colour.** There is no shallow-depth gradient left to make red — that is most of
what "looks like a lightbulb" means, and it is why the raw `101` §5 numbers
(R/G 1.29 at 1 mm, 1.57 at 2 mm, 1.82 at 3 mm) never actually reached the
screen. The brief forbids touching the floor, so **`earglow5` and its cut/colour
siblings change the colour and the brightness AT 6 mm and cannot restore the
gradient.**

> **§13 builds the fix.** `earglow5-floor3` and `earglow5-floor2` lower that
> `NMax` to 3 mm and 2 mm — one operand repointed, nothing else changed — and
> §13.2 gives their tables. Read §13.3 before picking: restoring the gradient
> also makes the thin edge *less* red, which is the opposite of what the
> verdict asked for.

---

## 4. Colour: (c1) and (c2), never blended

Both are computed below from the rate constants **read back out of the shipped
`.spv`** by gate 8, exactly as `101` §5 does.

**Shipped `101`, as it renders (k = 0.22, floor 6 mm):** R 0.09454, G 0.03818,
B 0.01213, **R/G 2.48**.

### (c1) `earglow5` — fixed tint (1.0, 0.40, 0.22), ld unchanged (3.67 / 1.37 / 0.68 mm)

| t (mm) | t_eff (mm) | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 1 | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 2 | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 4 | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 6 | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 8 | 8.00 | 0 | 0 | 0 | — | 0.000 |

### (c2) `earglow5-rate` — ld 3.67 / **0.70** / **0.35** mm, no tint

| t (mm) | t_eff (mm) | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 1 | 6.00 | 0.023636 | 0.003231 | 0.000379 | 7.31 | 1.000 |
| 2 | 6.00 | 0.023636 | 0.003231 | 0.000379 | 7.31 | 1.000 |
| 4 | 6.00 | 0.023636 | 0.003231 | 0.000379 | 7.31 | 1.000 |
| 6 | 6.00 | 0.023636 | 0.003231 | 0.000379 | 7.31 | 1.000 |
| 8 | 8.00 | 0 | 0 | 0 | — | 0.000 |

### `earglow5-cut10` — the only rung with a live 8 mm row

| t (mm) | t_eff (mm) | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 6 | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 8 | 8.00 | 0.019055 | 0.002587 | 0.000320 | 7.37 | 1.000 |

### `earglow5-cut6` — where the fade bites

| t (mm) | R | fade | note |
|---|---|---|---|
| 4 | 0.023636 | 1.000 | full |
| 6 | 0 | 0.000 | the concha of an adult ear is **gone** at this rung |
| 8 | 0 | — | query B misses |

**Read the difference honestly:** (c1) and (c2) have the **same red** and differ
only in how hard they crush green and blue (R/G 6.19 vs 7.31, R/B 35× vs 62×).
(c2) is the more physical of the two — it is a shorter mean free path, not a
post-multiply — but it also makes green and blue collapse faster with depth, so
on `-cut10`'s 8 mm row (c2) would be redder still. If the user wants "colouring
the location" rather than "light", (c1) is the safer default because its ratio
is fixed and does not drift with thickness.

---

## 5. Gates, with numbers

`./dev/build_earglow5.sh` — twelve gates, all offline, all green. The numbers
below are the original five-rung family; §13.5 covers the two gates added
there, and §14.8 the twelfth gate and the fifteen-rung run.

| # | gate | result |
|---|---|---|
| 0 | base provenance 77/4/12 **and the base is the earglow-cap6 stack** | 10 paintable permutations at 3/3/2/1 with k=0.22, tmax=0.018, floor=0.006 and all six `101` rate constants |
| 1 | round-trip neutrality | 10 of 10 |
| 2 | patch + `spirv-val --target-env vulkan1.4`, 81 non-reference + 2 pass-through modules cmp-verbatim | 5 rungs × 93 clean; 10 of 10 differ between every pair of live rungs |
| 3 | coverage census from the reports against a WANT table stated independently | `earglow5` / `-cut6` / `-cut10`: +6 instructions, 2 in-place rewrites; `-rate`: +3, 6 rewrites; floor 6 mm untouched in all |
| 4 | **eight ray-query opcode counts vs the base, module by module** | 30 Initialize, 30 Proceed, 20 InstanceId, 10 committed-T, 144 traces — **ALL IDENTICAL TO THE BASE** in all five rungs |
| 5 | identity | `-ctl` **93 of 93** byte-identical (content `3bb0aee03a1bfda8`); every live rung differs on exactly **10 of 93** |
| 6 | `verify_earglow5.py`, 8 check groups re-derived from shipped bytes | ALL PASS ×4, plus `--negative` and `--control` |
| 7 | non-vacuity: **19** decoys and cross-reads | 19 rejected |
| 8 | closed-form transfer, rates/tint/cut read back through the verifier's own re-derivation | §4 |
| 5b | **regression: the parked rungs rebuild byte-identical** (§13.5) | `earglow5`, `-cut6`, `-cut10`, `-rate`, `-ctl`: 93 of 93 each |
| 9 | MANIFEST provenance; `--install` parks NEW names only | 7 written |

The seven `--decoy` builds:

| decoy | what it breaks | why it must be caught |
|---|---|---|
| `flatk` | k left at 0.22 | still a lightbulb |
| `nocut` | fade added, `tmax` left at 18 mm | the nose bridge still glows |
| `nofade` | `tmax` cut, no smoothstep | a visible hard edge at `t_cut` |
| `invfade` | the `OpFSub(1, s)` dropped | lights **only** the pixels past the cutoff |
| `fadefloored` | the fade reads the **floored** t | at `-cut6` the rung is black everywhere |
| `notint` | tint (1, 1, 1) | still yellow |
| `tintswap` | tint reversed to (0.22, 0.40, 1.0) | blue, not red |

and an eighth added in §13: `floorshared`, which rewrites the shared 0.006
constant in place instead of repointing — see §13.1 for why that is the
dangerous mistake.

plus eleven cross-reads: the base as a rung, the control as a rung, `earglow5`
read at cut 6, `-cut10` read at cut 8, `earglow5` read as the rate rung,
`-rate` read as the tint rung, `earglow5` read at the old k, the control
read as byte-different, `earglow5` read at floor 3 mm, `-floor3` read at the
6 mm floor, and `-floor2` read at floor 3 mm.

Content shas:

| set | content | raygen half |
|---|---|---|
| `earglow5` | `77d0a7039e65e5b7` | `5db02b254e9c934a` |
| `earglow5-cut6` | `c86b14e606dba2ff` | `25466a02e5023e99` |
| `earglow5-cut10` | `8577c75fb2135442` | `2119e878caa5f9c3` |
| `earglow5-rate` | `30b086d2cf9faec6` | `4aa06f14d34bde19` |
| `earglow5-floor3` | `165191cc19dfbc73` | `631b922473793c74` |
| `earglow5-floor2` | `212d785de229034f` | `b1136bf4aab6a273` |
| `earglow5-ctl` | `3bb0aee03a1bfda8` | `20d5c23ea50e339e` |
| (base) | `3bb0aee03a1bfda8` | `20d5c23ea50e339e` |

The first five are **unchanged by §13** and gate 5b `cmp`-proves it against the
parked sets, file by file.

---

## 6. No driver self-test, and what licenses skipping it

`dev/selftest_earglow_rq.sh` exists to answer questions about the **ray
queries**: does the layer enable `VK_KHR_ray_query`, does the driver lower
three live query objects with flags 545 and 517, do the real ~300 KB raygens
survive `vkCreateShaderModule`. v5 changes six float constants and adds at most
six scalar ALU instructions. **Gate 4 proves, per module and against the base,
that all eight ray-query opcode counts are unchanged** — same objects, same
flags, same getters, same `OpTraceRayKHR` count. The bytes the driver is handed
are the same shapes that self-test already compiled, so its case A and case E
results carry over unchanged and re-running it would restate them.

**Re-run it the moment a rung touches the query itself.** Gate 4 is the tripwire
that would force that.

---

## 7. SETTINGS CONTRACT — state it BEFORE the launch

* `ser = class`, **`shadowset = full-shadow`**, `ptq` unchanged, **RR OFF**
* **Photo mode / reference path-tracer reach — let it converge.** The glow is
  gated on `path == 0`; a noisy frame is not a read.
* **BACKLIT head**, sun low and **behind**, camera on the sun side of the ear.
* **ONE frame must contain all three:** a **child**, an **adult**, and a
  **nose-bridge view** (3/4 or profile, the bridge silhouetted against the sun).
  The child answers brightness, the adult answers the cutoff at the concha, the
  nose bridge answers the complaint that started this document.
* Shoot **`earglow5-ctl` first** in the same camera position — it is
  byte-identical to what the user judged, so it is the "before".
* Then `earglow5`, then whichever of `-cut6` / `-cut10` the first shot argues
  for, then `earglow5-rate` against `earglow5` for the colour A/B.
* The game runs **copies**: `cmp` the parked sets or `make install` before
  reading a launch.

---

## 8. Pre-registered interpretation table

| # | observation | reading |
|---|---|---|
| 1 | `earglow5` still reads as a lightbulb | k is not the problem; the **floor** is (§3.2). Next rung lowers `%float_0_006`, not k |
| 2 | glow is now too dim to see at all | k/4 overshot; the ladder needs k ≈ 0.11 between `-ctl` and `earglow5` |
| 3 | nose bridge is **clean** at `earglow5` | (b) is SHOT at 8 mm. Keep |
| 4 | nose bridge still glows at 8 mm | the bridge reads under 8 mm to the query — a geometry fact, not a tuning one. Go to `-cut6` and accept the concha loss |
| 5 | `-cut6` removes the concha as §3.1 predicts | expected; only ship it if the nose matters more than the ear |
| 6 | a visible **ring/edge** at the cutoff | the 1 mm fade is too narrow. Widen to 2 mm (one constant) |
| 7 | ears now read RED and the nose is gone | **SHOT.** Pick between `earglow5` and `-rate` on colour alone |
| 8 | still yellow at `earglow5` | (c1)'s tint is not strong enough; `-rate` is the stronger arm (R/G 7.31 vs 6.19) |
| 9 | `-rate` reads *too* red / clay-like | (c1) is the pick; the ratio there does not drift with depth |
| 10 | the glow is flat across the whole ear | §3.2 confirmed on screen. The floor, not v5 |
| 11 | any difference between `-ctl` and the previous default | impossible — they are byte-identical. Would falsify gate 5 |

**VOID** — every row. Nothing has been on screen.

---

## 9. Cost

Zero added rays; the rays are **cheaper** (`tmax` 18 mm → 8 mm). +3 to +6
scalar ALU instructions per invocation, at path 0 only. +2 to +3 constant
declarations. No new capability, no new control flow, no new descriptor read.

---

## 10. What is NOT done

* ~~**The 6 mm floor is untouched**~~ — **superseded by §13.** It is untouched
  in the five rungs of §1–§12, which was the brief; `earglow5-floor3` and
  `earglow5-floor2` lower it, and §13.6 lists what is still not done after
  them.
* **No `-hit` diagnostic at v5.** `earglow-rq3-hit` still reports the *old*
  band (tmax 18 mm) and is therefore the wrong instrument for reading a
  cut at 8 mm.
* **The 8 mm figure is anatomy, not a measurement** from this renderer's meshes.
* **k = 0.055 is the brief's arithmetic**, not a tuned value; no `k/2` rung.
* **(c1) and (c2) are not blended**, on purpose, so the A/B is one variable.
* **Nothing shot**, no launch, no `make install`, no commit, and no self-test
  (§6 says why).

---

## 11. Files

| file | what |
|---|---|
| `dev/patch_earglow5.py` | structural re-derivation of `101`'s glow block, then in-place constant rewrites + the fade + the tint + `--floor` + `--tint` + `--no-cutoff`; 8 `--decoy` modes; refuses any base that is not 3/3/2/1 with the 6 mm floor |
| `dev/verify_earglow5.py` | 9 check groups from the shipped `.spv`; `--negative`, `--control`, `--floor`, `--tint`, `--no-cutoff`, and `--vs-centre/--axis` (the §14.4 ladder check); check 3 proves a floor rung repointed one operand and left the shared constant's twelve other consumers alone; check 8 tolerates **only** `OpConstant %float` replacements and counts them |
| `dev/build_earglow5.sh` | twelve gates, fifteen rungs, thirty rejections; `--install` parks NEW names only |
| `swaps.earglow5{,-cut6,-cut10,-rate,-floor3,-floor2,-ctl}/` | 93 modules each, 10 patched (0 for `-ctl`) |
| `swaps.earglow6{,-cut10,-cut15,-cutoff,-k11,-k22,-mild,-deep}/` | the §14 ladder; 93 modules each, 10 patched |

**Nothing existing was edited.** `init.lua`, `swap_layer.c`, the `Makefile`,
`CURRENT.md`, `GOTCHAS.md`, every existing `dev/` script and every existing
handoff document are untouched.

---

## 12. `init.lua` entries to add

**This document does not edit `init.lua`.** Add these five entries to
`SKIN_LEVELS`, after the `earglow-cap6` block (around line 531) — then the two
in §13.8 and the eight in §14.11. **If you are only shooting the current
ladder, §14.11's eight plus `earglow5-ctl` are all you need.**

```lua
    -- 110: EAR GLOW v5, on the user's screen verdict ("looks like a lightbulb
    -- behind ears ... 3/4 less bright ... hard cutoff at a certain thickness
    -- ... transmittance through the upper nose bridge ... too yellow ...
    -- really shallow depth should still be coloured more red").
    -- THREE VARIABLES, and the RAY QUERIES ARE NOT AMONG THEM (build gate 4
    -- checks eight ray-query opcode counts against the base, per module):
    --   (a) k 0.22 -> 0.055; red at the floor 0.0945 -> 0.0236.
    --   (b) query B tmax 18 mm -> t_cut, so past t_cut the query MISSES and
    --       the term is EXACTLY zero, plus a 1 mm smoothstep below t_cut.
    --   (c) colour, two arms, never blended: a fixed tint (1.0,0.40,0.22)
    --       gives R/G 2.48 -> 6.19; shorter ld_G/ld_B (1.37->0.70,
    --       0.68->0.35 mm) gives 7.31.
    -- READ handoff/110 sec 3.2 FIRST: 101 sec 18's 6 mm floor runs BEFORE the
    -- transfer, so every ear thinner than 6 mm already renders at ONE
    -- brightness and ONE colour. v5 changes that colour; it cannot restore a
    -- shallow-depth gradient the floor removed. Lowering the floor IS built,
    -- as earglow5-floor3 / earglow5-floor2; see sec 13.8 for those two lines.
    -- Shoot BACKLIT with a CHILD, an ADULT and a NOSE-BRIDGE view in ONE
    -- frame, shadowset=full-shadow, and shoot earglow5-ctl first as "before".
    { id = "earglow5-ctl",    label = "CONTROL for ear glow v5 -- byte-identical to the DEFAULT stack (this is the 'before')" },
    { id = "earglow5",        label = "Ear glow v5 (k=0.055, hard cutoff 8 mm + 1 mm fade, tint 1.0/0.40/0.22 -> R/G 6.19) -- the pick" },
    { id = "earglow5-cut6",   label = "Ear glow v5, cutoff 6 mm -- aggressive: kills the nose bridge AND the concha of an adult ear" },
    { id = "earglow5-cut10",  label = "Ear glow v5, cutoff 10 mm -- permissive: a thin nose bridge may still glow" },
    { id = "earglow5-rate",   label = "Ear glow v5, colour by SHORTER ld_G/ld_B (0.70/0.35 mm) instead of a tint -> R/G 7.31; A/B this against earglow5 on colour alone" },
```

Park them first: `./dev/build_earglow5.sh --install`.

---

## 13. The §3.2 fix, built: `earglow5-floor3` and `earglow5-floor2`

§3.2 said the 6 mm floor, not `k`, is most of what "looks like a lightbulb",
and §10 called lowering it "the obvious next rung". It is now built. **The
floor is the only variable against `earglow5`** — same `k` 0.055, same 8 mm
cutoff, same 1 mm fade, same (c1) tint, same query.

### 13.1 It is a REPOINT, not a rewrite — and it had to be

`%float_0_00600000005` is **shared**. In every one of the ten paintable
permutations it is also

* the `tmax` of **six** of the module's own `OpTraceRayKHR`s, and
* the right-hand side of **six** `OpFOrdLessThan` tests,

— twelve consumers that have nothing to do with the ear glow. Rewriting that
declaration in place (the obvious way to build this rung) would move all
twelve. `patch_earglow5.py`'s `rewrite_const()` refuses it, correctly, so
`set_floor()` declares a **new** constant and repoints **only** the earglow's
own `NMax` operand:

```
%2955 = OpExtInst %float %1 NMax %2954 %float_0_00600000005   # base
%2958 = OpExtInst %float %1 NMax %2957 %float_0_00300000003   # -floor3
```

(the id moves only because the three fade instructions of (b) are numbered
first; `1271d3815051da17`, the same site in both.)

That module carries **ten** `NMax` instructions — floors at 1, 5 and 10 mm that
belong to the engine — so the site is found by shape, never by value: query B
(the unique flags-545 initialize) → its committed `T` → its `OpSelect` miss
guard → the unique `NMax` on that guard. `--floor` cannot reach any of the other
nine.

Cost: **0 instructions**, 1 declaration, 12 other consumers untouched. The
patcher reports `other_consumers_left_alone: 12`; `verify_earglow5.py` check 3
re-proves it from the shipped bytes — the 0.006 constant must still exist, must
**not** be the one the `NMax` reads, must keep ≥ 12 consumers, and at least one
of them must still be an `OpTraceRayKHR`. `--decoy floorshared` builds the
in-place version and is rejected (gate 7).

### 13.2 Transfer, from the constants read back out of the shipped `.spv`

k = 0.055, cut 8 mm + 1 mm fade, tint (1.0, 0.40, 0.22), ld 3.67 / 1.37 / 0.68 mm.

**`earglow5-floor3` — `NMax(t, 3 mm)`**

| t | t_eff | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 1 mm | **3.00** | 0.034560 | 0.007594 | 0.002081 | 4.55 | 1.000 |
| 2 mm | **3.00** | 0.034560 | 0.007594 | 0.002081 | 4.55 | 1.000 |
| 3 mm | 3.00 | 0.034560 | 0.007594 | 0.002081 | 4.55 | 1.000 |
| 4 mm | 4.00 | 0.030188 | 0.005895 | 0.001407 | 5.12 | 1.000 |
| 6 mm | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 8 mm | 8.00 | 0 | 0 | 0 | — | 0.000 |

**`earglow5-floor2` — `NMax(t, 2 mm)`**

| t | t_eff | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 1 mm | **2.00** | 0.039944 | 0.010191 | 0.003220 | 3.92 | 1.000 |
| 2 mm | 2.00 | 0.039944 | 0.010191 | 0.003220 | 3.92 | 1.000 |
| 3 mm | 3.00 | 0.034560 | 0.007594 | 0.002081 | 4.55 | 1.000 |
| 4 mm | 4.00 | 0.030188 | 0.005895 | 0.001407 | 5.12 | 1.000 |
| 6 mm | 6.00 | 0.023636 | 0.003818 | 0.000667 | 6.19 | 1.000 |
| 8 mm | 8.00 | 0 | 0 | 0 | — | 0.000 |

For reference, `earglow5` is the 6 mm row **six times**: 0.023636 / 0.003818 /
0.000667, R/G 6.19, at every t from 1 to 6 mm. That is the flatness §3.2
described, and these two rungs are the only ones in the family that have a
gradient at all.

### 13.3 Two consequences the tables make unavoidable

**(1) Lowering the floor partly undoes variable (a).** Peak red rises 0.023636
→ 0.034560 (`-floor3`, ×1.46) → 0.039944 (`-floor2`, ×1.69). Against the bytes
the user called a lightbulb (R 0.09454 flat), `-floor2` is still **0.42×** and
`-floor3` **0.37×** at their brightest, and both fall to 0.023636 by 6 mm — so
neither is a return to the old level, but neither is the flat quarter either.

**(2) The gradient runs the WRONG WAY for "shallow should read redder".** The
verdict asked for shallow transmission to be *more* red. A single exponential
does the opposite, and `101` §18.1 already said so in as many words — *"A thin
ear is not only brighter, it is less red … thin flesh passes green and blue that
thick flesh eats."* R/G at 1 mm is 4.55 (`-floor3`) and 3.92 (`-floor2`) against
6.19 at 6 mm. The fixed tint supplies the red and is depth-**in**dependent, so
lowering the floor lets the physics pull the ratio back toward yellow exactly
where the user wanted it reddest. The rungs are **still redder at 1 mm than the
shipped default was on any ear** (3.92 against a flat 2.48 everywhere under
6 mm), so this is a trade, not a regression. But if `-floor2` wins on gradient
and loses on colour, the answer is a *depth-dependent* tint, or `--mode rate` at
a lowered floor — one rung, not built here, named in §13.6.

### 13.4 Why `101` §18 put the floor at 6 mm, and why that argument is now 4× weaker

The floor exists because of an earlier verdict, `101` §18.1, verbatim:

> **Also if the intensity gets more intense as geometry gets thinner, we might
> want to cap that at a certain point. Childrens ears GLOW. They emit alot of
> light which doesnt look correct. Everything else looks great**

At k = 0.22 that is arithmetically forced: the transfer is monotone decreasing
in `t`, the only ceiling in the build is query B's 1.5 mm `tmin`, and an
unfloored 2 mm child ear evaluated **R = 0.15977** against 0.09454 at 6 mm.

Note what `101` §18.3 predicted about the rung that then shipped:

> **cap6 will visibly change adult ears** (it lifts the floor above a 4 mm ear
> entirely …) and that is why cap6 is in the ladder as a bracket and is *not*
> expected to ship.

It shipped anyway, and §3.2 is the consequence. At k = 0.055 the same 2 mm ear
gives **0.039944** — **25 %** of the value that blew out and **42 %** of what
currently ships and is being called a lightbulb. The ceiling argument is
therefore exactly four times weaker, which is the whole of variable (a).

**It is still unmeasured.** No child's ear has been on screen at any k but 0.22,
and none at a lowered floor. That is what these two rungs are for, and it is why
the settings contract (§7) already demands a child and an adult in one frame —
row 12 below is the point of shooting them.

### 13.5 Gates

`./dev/build_earglow5.sh` now runs eleven gates over **seven** rungs, with
**nineteen** rejections (eight `--decoy` builds, eleven cross-reads). All green;
the four pre-existing rungs' content shas are unchanged (§5). Three things are
new:

* **gate 5b — regression against the parked rungs.** `earglow5`, `-cut6`,
  `-cut10`, `-rate` and `-ctl` are rebuilt and `cmp`-ed against what is
  installed, not against a fresh build of themselves, so adding `--floor` cannot
  have drifted a byte of the four rungs already parked.
* **gate 3 — floor census per rung.** The `WANT` table names each rung's floor,
  and a rung whose floor is 6 mm must carry **no** `floor_repoint` at all.
* **`--decoy floorshared`** (§13.1), the in-place rewrite of the shared
  constant — the mistake this rung most invites.

Gate 4 (the ray-query census, op by op against the base) covers the two new
rungs unchanged — a floor repoint touches one operand of an `OpExtInst`, so the
self-test stays skipped for exactly the reason §6 gives.

### 13.6 What is NOT done, still

* **A depth-dependent tint**, which §13.3(2) argues is the real answer if the
  floor rungs win on gradient and lose on colour. One `mix()` on the existing
  `t_eff`; three instructions; not built.
* **`--mode rate` at a lowered floor.** `-rate` and `-floor*` are separate
  variables on purpose; nothing combines them yet.
* **A floor below 2 mm.** 2 mm is already under a child's helix; going lower
  buys gradient only where the query's 1.5 mm `tmin` starts to matter.
* **Nothing shot.** No launch, no `make install`, no commit.

### 13.7 Interpretation table, floor rungs (pre-registered, all VOID)

| # | observation | reading |
|---|---|---|
| 12 | a child's ear blows out at `-floor2` but not `-floor3` | 101 §18's ceiling survives k/4 at 2 mm but not 3 mm. Ship `-floor3`; the floor is a real constraint, not an artifact of k = 0.22 |
| 13 | neither blows out, and the ear now has visible depth structure | **SHOT.** §3.2 confirmed and fixed. `-floor2` is the pick unless 14 fires |
| 14 | the thin rim reads yellower than the thick part | §13.3(2) on screen. Neither rung is the answer; build the depth-dependent tint |
| 15 | `-floor3` and `-floor2` are indistinguishable | the meshes' ear thickness never goes under 3 mm; take `-floor3` and stop |
| 16 | `-floor3` looks the same as `earglow5` | the floor is not being reached at all — the *query* is returning ≥ 6 mm, which would falsify §3.2 and make the 8 mm cut suspect too |
| 17 | the glow reads brighter than `earglow5` overall | expected and quantified (§13.3(1), ×1.46 / ×1.69 at the thinnest). Only a defect if it exceeds `-ctl` |

**VOID** — every row. Nothing has been on screen.

### 13.8 `init.lua` entries to add

Two more `SKIN_LEVELS` entries, after the five in §12:

```lua
    -- 110 sec 13: the sec 3.2 fix. 101 sec 18's NMax(t, 6 mm) runs BEFORE the
    -- transfer, so earglow5 renders EVERY ear thinner than 6 mm at one
    -- brightness and one colour. These two rungs lower that floor and change
    -- NOTHING else (same k, same 8 mm cut, same tint, same query). It is a
    -- REPOINT of one OpExtInst operand onto a new constant, not a rewrite of
    -- the shared 0.006 -- that constant is also six OpTraceRayKHR tmaxes.
    -- Peak red rises 0.0236 -> 0.0346 (floor3) / 0.0399 (floor2), still 0.37x
    -- / 0.42x of the shipped default the user called a lightbulb.
    -- 101 sec 18 picked 6 mm because CHILDREN's ears blew out at k=0.22; at
    -- k=0.055 that argument is 4x weaker but UNMEASURED, so shoot a child.
    -- Watch for the trap in sec 13.3: R/G FALLS toward the thin edge
    -- (6.19 at 6 mm -> 3.92 at 2 mm) because a single exponential makes
    -- shallow transmission LESS red, not more.
    { id = "earglow5-floor3", label = "Ear glow v5 with the thickness floor at 3 mm, not 6 mm -- restores the depth gradient earglow5 cannot have; A/B against earglow5" },
    { id = "earglow5-floor2", label = "Ear glow v5 with the thickness floor at 2 mm -- the strongest gradient; check a CHILD's ear for blow-out (101 sec 18's original reason for 6 mm)" },
```

---

## 14. earglow6 — a ladder, after the v5 shot erased the effect

### 14.0 The verdict, verbatim

> **the earglow intentions were taken a bit too literally. By redder at the
> shallow points Im meaning there still should be a gradient from the brightest
> skin to red, but the brightest skin should probably be more red at its peak
> than it was set to, moreso because the resolution of the rays make it not look
> right. There will be one almost white beige point GLOWING, with a bit of red
> around it, whereas the area of that ray, that area should probably be on
> average more red. Maybe on a real person that exact spot would be that bright,
> but because the rays are lower resolution, it should be more averaged towards
> red hues. Also the cutoff is completely removing all rays now. I'd try making
> the cutoff for depth a bit larger (maybe like 12mm or a bit more) and bright
> the brightness back up to something like 75% of what it was. I can no longer
> see the earglow.**

The user has since said the 12 mm and 75 % figures are **vibes, not
measurements**. So §14 does not build a point; it builds a **ladder**: one
centre and seven steps, each differing from the centre in exactly one axis, so
one frame brackets the answer instead of testing a guess.

### 14.1 Why an 8 mm cutoff erased the effect

**`t` is not ear thickness. It is the chord of the sun ray through the flesh.**
Query B fires along `S` — the sun direction — and commits the first backface.
For a locally planar slab of thickness `d` whose normal makes an angle θ with
`S`, that chord is `d / cos θ`, and θ is *large* in exactly the lighting this
effect needs. `101` §14 already said the geometric half of it:

> In front lighting … the sunward direction runs **along** the ear and **into**
> the skull — the sun path is the long axis of the head, not a 2–4 mm crossing.
> … The only lighting in which the sun path *across* an ear rim or a nostril
> wall is short is **backlit**.

Backlit means the sun is low and *behind*, so on most of the pinna's lit-from-
behind skin `S` is closer to the surface plane than to the normal. The
arithmetic — **mine, not a measurement**:

| slab `d` | θ=0° | 45° | 60° | 70° | 75° | 80° |
|---|---|---|---|---|---|---|
| 2 mm | 2.0 | 2.8 | 4.0 | 5.8 | 7.7 | 11.5 |
| 3 mm | 3.0 | 4.2 | 6.0 | 8.8 | 11.6 | 17.3 |
| 4 mm | 4.0 | 5.7 | 8.0 | 11.7 | 15.5 | 23.0 |

An 8 mm ceiling therefore keeps a 3 mm pinna only out to **θ ≈ 68°** and a 4 mm
one only to **θ ≈ 60°**. Everything more grazing — which is most of a curved
pinna under a low sun — **misses**, and a miss is exactly zero. Add the 1 mm
fade, which is already zero at 8 mm and only 0.5 at 7.5 mm, and the usable band
was `t ∈ [1.5, 7] mm`. "I can no longer see the earglow" is the correct
prediction from that.

Three further points, kept honest about their provenance:

* **`101` §5 chose 18 mm as a *chord* budget in the first place** — "`tmax =
  0.018` m (18 mm, `T_SEG`) is the thickest ear/nostril worth reading". §12 cut
  that budget by **56 %** while calling it a thickness.
* **`101` §11.5 pre-registered this exact failure** as a live hypothesis with
  a named action: *"18 mm is shorter than the sun-path thickness at the pixels
  that matter → rebuild the glow rung with a larger `tmax`."* v5 moved it the
  wrong way.
* **There is no per-region measurement of the concha anywhere in `101`.** The
  only anatomical figure in the track is "thinnest real ear ≈ 2 mm" (§1) and
  "a 2–4 mm crossing" (§14). The concha is a bowl with cartilage and the
  mastoid behind it, so its chord is long at every angle and it should not glow
  — but that is a prediction, not something this track has measured. Say so
  before reading a frame.

### 14.2 Should the query's `tmax` stay coupled to `t_cut`?

**Keep them coupled while `t_cut` < 18 mm and the wanted falloff is a hard
zero. Decouple the moment either stops being true.** The argument:

* Coupled, the cutoff is **exact and free**: past `tmax` query B misses, `hitB`
  is false, the accept is false, the term is `-0.0`. The rays are also shorter,
  so the rung is *cheaper* than the base, not dearer.
* But coupling **destroys the distinction between "too thick" and "no back wall
  at all"**, and it makes a soft tail impossible: the NaN guard substitutes
  `tmax` for `t` on a miss, so `t_eff` saturates at `t_cut` and no transfer
  written past that point can ever run.
* It also **entangles two axes**. `tmax` decides *what geometry is considered*;
  `t_cut` decides *what is drawn*. While `t_cut` < 18 mm they can share a
  constant harmlessly. At `t_cut` ≥ 18 mm they cannot, because raising `tmax`
  starts admitting hair cards, collars and the far side of the skull that
  `101` §13 spent a whole section proving the 18 mm ceiling was keeping out.

`earglow6-cutoff` is the decoupled extreme and the reason it is in the ladder:
`tmax` back at the shipped 18 mm, **no fade at all**, the transfer's own
exponential the only falloff. If it wins, no hard cutoff is wanted and the
whole of variable (b) comes out.

### 14.3 The "resolution of the rays" complaint

One ray per pixel per frame samples a quantity — the chord — that varies fast
across a curved pinna. The visible symptom is exactly what was reported: a
near-white point where the chord happened to be shortest, with red around it.

Be clear about what does and does not address that:

* **The tint does not.** It multiplies every channel by a constant, so it moves
  the hot point and its surround together. It makes the effect redder; it does
  **not** make the peak red *relative to* its neighbours.
* **A floor does** — it clamps the short chords, which is precisely what `101`
  §18's 6 mm floor was for, and precisely what §3.2 showed also destroys the
  gradient. Floor and hot point come out together.
* **Lowering `k` does**, by pulling the whole range down out of the region
  where the tone-mapper clips to white — which is what "almost white beige"
  describes. `-k11` is the arm that tests this.

So the two halves of the verdict — *"there still should be a gradient"* and
*"that area should be on average more red"* — pull against each other under a
single exponential and a point sample. The ladder brackets the trade; it does
not resolve it. The thing that would resolve it is a **soft floor** — a smooth
minimum on `t` instead of `NMax` — which kills the hot point without flattening
the ramp. That is three instructions and it is **not built** (§14.9).

### 14.4 The ladder

Centre **`earglow6`**: k 0.165, cutoff 12 mm + 1 mm fade, floor 3 mm, tint
(1.0, 0.40, 0.22). Every other rung moves **one** axis:

| axis | rungs |
|---|---|
| cutoff | `-cut10` (10 mm) · **`earglow6`** (12 mm) · `-cut15` (15 mm) · `-cutoff` (none: `tmax` 18 mm, no fade) |
| brightness | `-k11` (0.11) · **`earglow6`** (0.165) · `-k22` (0.22, the shipped brightness) |
| colour | `-deep` (1.0, 0.30, 0.15) · **`earglow6`** (0.40, 0.22) · `-mild` (1.0, 0.55, 0.35) |

`earglow5-ctl` remains **the** control for both families — it is byte-identical
to the standing default — and no second identity rung was built. Build gate 6b
proves the one-axis claim pairwise from the shipped bytes: it re-derives
(k, `t_cut`, floor, tint, fade-present) from the rung *and* the centre, demands
exactly the named field differ, and demands the two normalised **instruction
streams be identical** — except on the `cutoff` axis, where they must differ by
exactly the three lines of the fade and nothing else.

### 14.5 The centre's transfer, from the constants read back out of the `.spv`

k = 0.165, cut 12 mm + 1 mm fade, floor 3 mm, tint (1.0, 0.40, 0.22),
ld 3.67 / 1.37 / 0.68 mm.

| t | t_eff | R | G | B | R/G | fade |
|---|---|---|---|---|---|---|
| 1 mm | **3.00** | 0.103680 | 0.022782 | 0.006244 | 4.55 | 1.000 |
| 2 mm | **3.00** | 0.103680 | 0.022782 | 0.006244 | 4.55 | 1.000 |
| 3 mm | 3.00 | 0.103680 | 0.022782 | 0.006244 | 4.55 | 1.000 |
| 4 mm | 4.00 | 0.090563 | 0.017684 | 0.004221 | 5.12 | 1.000 |
| 6 mm | 6.00 | 0.070907 | 0.011455 | 0.002002 | 6.19 | 1.000 |
| 8 mm | 8.00 | 0.057166 | 0.007761 | 0.000959 | 7.37 | 1.000 |
| 10 mm | 10.00 | 0.047154 | 0.005343 | 0.000459 | 8.82 | 1.000 |
| 12 mm | 12.00 | 0 | 0 | 0 | — | 0.000 |

There is now a **1.81× red ramp** from the peak to 8 mm, and R/G climbs 4.55 →
8.82 across it. That is the "gradient from the brightest skin to red" the
verdict asked for; `earglow5` had none, because its floor sat at 6 mm.

### 14.6 One line per rung

Peak means the whole band `t ≤ 3 mm`, where the floor clamps — gate 8 finds it
by scanning rather than assuming it sits at the floor, so its log reports
`peak@ 0.5mm`, the first grid point in that band. All eight rungs share floor
3 mm and ld 3.67 / 1.37 / 0.68 mm, so the peak-to-8 mm **shape** is identical
by construction — only the level and the hue move.

| rung | peak R | peak G | peak B | R/G @2 mm | R/G @8 mm | peak/8 mm R |
|---|---|---|---|---|---|---|
| **`earglow6`** | 0.103680 | 0.022782 | 0.006244 | 4.55 | 7.37 | 1.81× |
| `-cut10` | 0.103680 | 0.022782 | 0.006244 | 4.55 | 7.37 | 1.81× |
| `-cut15` | 0.103680 | 0.022782 | 0.006244 | 4.55 | 7.37 | 1.81× |
| `-cutoff` | 0.103680 | 0.022782 | 0.006244 | 4.55 | 7.37 | 1.81× |
| `-k11` | 0.069120 | 0.015188 | 0.004163 | 4.55 | 7.37 | 1.81× |
| `-k22` | 0.138240 | 0.030376 | 0.008325 | 4.55 | 7.37 | 1.81× |
| `-mild` | 0.103680 | 0.031325 | 0.009934 | 3.31 | 5.36 | 1.81× |
| `-deep` | 0.103680 | 0.017087 | 0.004257 | 6.07 | 9.82 | 1.81× |

The cutoff rungs are identical everywhere the table looks — **on purpose**. The
cutoff axis changes only *where the effect stops*, and 8 mm is inside every one
of them. What separates `-cut10` from `-cutoff` is entirely off the right-hand
edge of this table, at 10–18 mm, which on §14.1's arithmetic is where most of a
grazing-lit pinna actually sits.

### 14.7 The number to argue about first

**`earglow6` is not 75 % of the brightness the user liked. At the peak it is
110 % of it.** The two requests multiply:

| | peak R | vs the shipped default (0.09454, flat) |
|---|---|---|
| shipped default (`earglow5-ctl`) | 0.09454 | 1.00× |
| `earglow5` (k/4, floor 6 mm) | 0.023636 | 0.25× — the one the user could not see |
| **`earglow6`** (k 0.165, floor 3 mm) | 0.103680 | **1.10×** |
| `-k11` (k 0.11, floor 3 mm) | 0.069120 | **0.73×** |
| `-k22` (k 0.22, floor 3 mm) | 0.138240 | 1.46× |

"75 % of what it was" was said about `k` (0.22 → 0.165), but the 3 mm floor of
§13 independently multiplies the peak by **1.46×**, because a 1 mm chord now
evaluates at 3 mm instead of 6 mm. 0.75 × 1.46 = 1.10. **`-k11` is the rung
that is literally 75 % at the peak**, and it is the honest reading of the
verdict — shoot it next to the centre, not as an afterthought.

### 14.8 Gates

Twelve gates, all offline, all green, over **fifteen** rungs (the seven v5 sets
plus the eight of the ladder), with **thirty** decoy and cross-read rejections.
New since §13:

* **gate 6b — the ladder check** (`--vs-centre … --axis`), described in §14.4.
  Non-vacuity: `-mild` claimed on axis `k`, `-k11` on axis `tint`, `-cutoff` on
  axis `cut`, and `earglow5-floor2` claimed as a one-axis step from the centre
  are all rejected.
* **gate 3 now names each rung's tint, floor, cutoff-present and rewrite set**
  in a table stated independently of the build's own arguments.
* **gate 8** extends the grid to 12 mm and adds the one-line-per-rung summary
  reproduced in §14.6.
* **gate 5b now freezes all seven v5 rungs**, not four: `earglow5`, `-cut6`,
  `-cut10`, `-rate`, `-floor3`, `-floor2` and `-ctl` are rebuilt and `cmp`-ed
  against what is parked.

Check 8's expectations are now **computed, not tabulated** — `3 × cutoff +
3 × tint` inserted instructions, and one rewritten declaration per constant
whose value actually moved. That is why `-k22` legitimately reports **one**
rewrite: its `k` is the shipped 0.22, so the declaration never changes. (It
also shares one constant id between `k` and the blue tint, both being 0.22 —
sound, since constants are values, and invisible to the ladder check because
constant names are normalised away.)

Gate 4 is unchanged and still green on all fifteen: **not one ray-query opcode
count moved against the base**, `-cutoff` included, so the driver self-test
stays skipped for the reason §6 gives.

Content shas (all seven v5 shas are byte-for-byte what §5 and §13 recorded —
that is gate 5b, not a coincidence):

| rung | content | raygen half |
|---|---|---|
| `earglow6` | `cb003520e37b56e0` | `ddaa47c124945a08` |
| `earglow6-cut10` | `7a266436a64498b1` | `c7a93bdd483d2b4a` |
| `earglow6-cut15` | `ddb0e9d0456ee109` | `c39cc907ba43e476` |
| `earglow6-cutoff` | `7030498a1845ceba` | `2718a3394f7942ff` |
| `earglow6-k11` | `da56d11ddfd039c6` | `258e9f12ef1fb94c` |
| `earglow6-k22` | `2870882510332151` | `82770e937161f13e` |
| `earglow6-mild` | `2e0368bad33edd7f` | `48567522283654f0` |
| `earglow6-deep` | `3d2df03d72378886` | `435c49a11b670586` |
| `earglow5-ctl` = (base) | `3bb0aee03a1bfda8` | `20d5c23ea50e339e` |

### 14.9 What is NOT done

* **The soft floor** (§14.3) — a smooth minimum on `t` in place of `NMax`,
  which is the only thing in sight that kills the near-white point *without*
  flattening the ramp. Three instructions. Not built.
* **No floor axis in this ladder.** All eight rungs sit at 3 mm; §13's
  `-floor2` / `-floor3` / 6 mm bracket already exists at k 0.055 and was not
  re-run at k 0.165.
* **No `-hit` diagnostic at 12 mm.** `earglow-rq3-hit` still reports the 18 mm
  band, so it cannot tell you where a 12 mm cut bites.
* **`101` §11.5's `nocull` and `back` discriminators were never shot.** If the
  ladder's cutoff axis shows *nothing* changes between 10 mm and no cutoff at
  all, that is the frame to shoot next — it would mean backfaces are absent,
  not distant, and no `tmax` fixes that.
* **Nothing on screen.** No launch, no `make install`, no commit.

### 14.10 Interpretation table (pre-registered, all VOID)

| # | observation | reading |
|---|---|---|
| 18 | `-cut10`, `earglow6`, `-cut15` and `-cutoff` are indistinguishable | the chord almost never exceeds 10 mm on these meshes; §14.1's arithmetic overstates the grazing case. Ship the cheapest, `-cut10` |
| 19 | the effect grows monotonically 10 → 12 → 15 → none | §14.1 confirmed; there is no thickness the user wants excluded. Drop the cutoff, ship `-cutoff`, and delete variable (b) |
| 20 | `-cutoff` glows on the nose bridge / cheek but the others do not | the cutoff *is* wanted and is doing the §3.1 job. Pick the largest cut that keeps the bridge dark |
| 21 | `-cutoff` glows on **hair, collar or eyes** | not thickness — the instance gate. `101` §13's finding, not a tuning problem; do not raise `tmax` again |
| 22 | `earglow6` still shows a near-white hot point | k is not the lever; build the soft floor (§14.3). `-k11` will dim it without removing it |
| 23 | `-k11` reads correct and `earglow6` reads hot | the 3 mm floor's 1.46× (§14.7) is real on screen. Ship `-k11`; it is the literal 75 % |
| 24 | `-k22` reads correct | the original 0.22 was never the problem — the 8 mm cut was. Ship `-k22` and note that v5's whole (a) was a misdiagnosis |
| 25 | `-deep` reads like a bruise / plum | the tint is overdriven; the answer is between `earglow6` and `-mild` |
| 26 | `-mild` reads yellow again | (c1) at 0.40/0.22 is the floor of usable red; go the other way only with `-deep` |
| 27 | any two rungs on the same axis are byte-different but visually identical | the axis is dead; drop it from the next ladder rather than sub-dividing it |
| 28 | any difference between `earglow5-ctl` and the standing default | impossible — byte-identical, gate 5 |

**VOID** — every row. Nothing has been on screen.

### 14.11 `init.lua` entries to add

Eight more `SKIN_LEVELS` entries, after §13.8's two:

```lua
    -- 110 sec 14: the EARGLOW6 LADDER, after v5 was shot and erased the effect
    -- ("the cutoff is completely removing all rays now ... I can no longer see
    -- the earglow"). READ 110 sec 14.1 FIRST: query B measures the SUN-PATH
    -- CHORD, not ear thickness. At backlit grazing angles a 3 mm pinna reads
    -- 8.8 mm at 70 deg and 11.6 mm at 75 deg, so v5's 8 mm cut discarded most
    -- of the effect. 101 sec 11.5 pre-registered exactly this.
    -- ONE CENTRE, SEVEN SINGLE-AXIS STEPS. earglow5-ctl is the control for
    -- this family too; there is no earglow6-ctl. Build gate 6b proves the
    -- one-axis claim pairwise from the shipped bytes.
    -- Centre earglow6 = k 0.165, cut 12 mm + 1 mm fade, floor 3 mm, tint
    -- (1.0, 0.40, 0.22): peak R 0.1037, R/G 4.55 at the peak rising to 7.37
    -- at 8 mm -- a 1.81x red ramp, which earglow5 did not have at all.
    -- WATCH THE TRAP IN sec 14.7: the centre is 110% of the brightness the
    -- user liked, not 75%, because k 0.75x and the 3 mm floor 1.46x multiply.
    -- earglow6-k11 is the rung that is literally 75% at the peak.
    { id = "earglow6",        label = "Ear glow v6 CENTRE (k 0.165, cutoff 12 mm, floor 3 mm, tint 1.0/0.40/0.22) -- shoot this and earglow5-ctl in one frame" },
    { id = "earglow6-cut10",  label = "Ear glow v6, CUTOFF axis: 10 mm instead of 12 -- the tightest cut that should still survive a grazing sun" },
    { id = "earglow6-cut15",  label = "Ear glow v6, CUTOFF axis: 15 mm instead of 12 -- admits a 4 mm pinna out to 75 deg" },
    { id = "earglow6-cutoff", label = "Ear glow v6, CUTOFF axis: NONE. tmax back to the shipped 18 mm, no fade; the transfer's own decay is the only falloff. If this wins, drop the cutoff entirely" },
    { id = "earglow6-k11",    label = "Ear glow v6, BRIGHTNESS axis: k 0.11 -- peak R 0.0691, the rung that is literally 75% of the brightness the user asked to get back" },
    { id = "earglow6-k22",    label = "Ear glow v6, BRIGHTNESS axis: k 0.22, the ORIGINAL shipped brightness with the new cutoff, floor and tint -- tests whether k was ever the problem" },
    { id = "earglow6-mild",   label = "Ear glow v6, COLOUR axis: tint (1.0,0.55,0.35), R/G 3.31 at the peak -- less red than the centre" },
    { id = "earglow6-deep",   label = "Ear glow v6, COLOUR axis: tint (1.0,0.30,0.15), R/G 6.07 at the peak -- more red than the centre" },
```

Park them first: `./dev/build_earglow5.sh --install`.
