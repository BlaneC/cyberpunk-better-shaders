# 12 — Fresh hunt: dispatch-driven, third idiom found, 29-module net staged

Written 2026-08-27, after the Phase 0 additive probe (`11` §6) ran and came back
**inconclusive**. This document supersedes the probe plan in `11` §6 and
re-runs it on a wider, dispatch-selected net.

---

## 1. What the Phase 0 probe actually showed

The staged probe (rim three, `spec_add=8`, diffuse ×4, lobes off) was run at a
new scene (Panam, tourist-info spot, daytime). A/B result: **no visible
difference** — but the run proved nothing about the splice sites, because the
control shot exposed a scope problem:

- The dispatch log (`~/callisto_swap.jsonl`) shows all three patched modules
  **dispatched with `swapped:1`** in the probe launch. The swap mechanism and
  the A/B hygiene were correct.
- Re-running the **hunt palette** (the exact 22:34 build) at the Panam scene
  painted **nothing** — not on Panam, not on NPCs, toggled on or off.

So at that scene the rim three never touch visible hair. `11` §1's scope note
("sunlit rim only") is the explanation: Panam's hair there is not in the
direct-sun path those modules own. The spec_add null is void — the splice
sites were never exercised. **Phase 0 has not actually run yet**; it needs a
scene where hair demonstrably paints (see §4).

A secondary static finding, for when Phase 0 does run properly: in
`d5166c0f1ea464b9` the spliced `+8` feeds `%761 = OpPhi %float %float_0 %937
%756 %938` — control arriving via `%937` **discards it for 0.0**. If the hair
path enters via `%937`, even a exercised site would show nothing. Check which
branch hair takes before reading too much into a future null.

## 2. The fresh hunt — dispatch-selected, not constant-selected

Per `10`'s lesson, targets came from the **live dispatch log** of the Panam
session, not the `1/π + k` byte scan:

- **178 distinct compute modules dispatched** in the session (all present in
  `~/callisto_dump`).
- Each was disassembled and run through `--tier hairhunt` individually.
- **29 patched clean (all `spirv-val` pass), 149 failed.** Installed as the
  `swaps.hair` overlay (29 files).

The 29 include: the rim three, the GI resolver `99bb7c2698997b2a`, the
previously-patchable anchored set, **all four of `10`'s "executing but
unpatchable" modules** (incl. `0e5e5a6a78fdf1dd`), and 9 newly-covered
mask-idiom modules.

## 3. The third idiom (patcher changes)

`10` §5 predicted "a third encoding". Found it:

```
%217 = OpBitwiseAnd %uint %193 %uint_4294967264   # (y & ~31)
%219 = OpIEqual     %bool %217 %uint_128           # == 4<<5  ⇔  (y>>5)==4
```

Ten dispatched modules use this mask-compare instead of a `>>5` shift. Changes
made to cover them (all in the class-fetch machinery, `--hair` tier regression
tested clean on the rim three afterwards):

1. **`patch_compute_hair.find_class_anchor_variant`** — also anchor on
   extracts masked with `%uint_4294967264`, and (second phase) anchor directly
   on the mask-compare itself, looking through an `OpPhi` if dxil-spirv lifted
   the extract. Handles the `OpLoad %v4float` + `OpBitcast` fetch shape.
2. **`patch_compute_hair.build_hunt_writes`** — uses `acquire_class_shift`
   (was: `find_class_shift` directly, dying on every variant module), and
   tests dominance on the **anchor id**, not the pending new shift (which has
   no def in the module yet and was treated as always-dominating — the
   `spirv-val` "does not dominate" failures).
3. **`patch_shadow_brdf.find_class_fetch`** — candidates now include the
   mask-idiom extract (looked through `OpPhi` if needed); the refetch emits
   its own `>> %uint_5` (present in all these modules).

Known uncovered:

- `84ea63ad0fdedb95` — grep false positive; its `4294967264` use is
  `OpIAdd` arithmetic (`x - 32`), not a mask. Not class-aware by this idiom.
- `8e5618efab94b955` — **covered after all**: mask-compare on extract
  **component 0** (`(x & ~31) == 160` = class 5<<5 — its own internal gate is
  class 5). The anchor now accepts a mask-compare on component 0 or 1. If
  this module shades hair, hair may read as class 5 (magenta) here — watch
  for it; that would mean class numbering or channel packing differs per
  family.

## 4. What to do in the morning

The 29-module hunt overlay is **installed**, caches cleared, log truncated.

1. **Launch and hunt for paint.** Check, in order:
   - the Panam tourist-info spot (the probe scene — does her hair paint now?),
   - V's own hair in **direct unobstructed sun** (the 22:34 proven case),
   - any NPC hair in shade / under local light (`&31` territory — never
     confirmed, `11` §7).
2. **Read the colour off the legend:** 1 red (skin, control) · 2 green ·
   3 blue · **4 yellow** · 5 magenta · 6 cyan · 7 orange · 8 violet ·
   13 azure · 14 lime. If hair paints anything other than yellow, the class
   number differs per family — record it.
3. Screenshot whatever paints, drop in `pics/`.

**Then bisect.** 29 modules all paint with the same palette, so a painted
pixel doesn't name its owner. `dev/bisect_hunt.sh` does the split:
`./dev/bisect_hunt.sh A` (first 15), `./dev/bisect_hunt.sh B` (last 14),
`all` to restore, `list` to see membership. It clears caches and truncates
the log each run — just relaunch and re-check the same surface. ~5 rounds
(29→15→8→4→2→1) name the owner.

**If hair paints yellow at the Panam scene now:** the owner is in the 29 and
the Phase 0 probe can be re-run properly — rebuild that ONE module (once
bisection names it) with `--hair 4` + the §6 probe knobs, isolated, same
scene. That is the real gate.

**If hair still doesn't paint anywhere:** the owners are outside the patched
29 — next suspects are the 149 no-class-read failures (post-process-shaped or
yet another idiom), then the graphics side (`11` §5 tooling:
`vkCreateGraphicsPipelines` + `vkCmdDraw*` logging) — the same
dispatch-driven selection should be applied there. Also possible: the
visible hair pixels are written by ray-tracing passes (CHS) rather than any
compute resolve in some lighting — `06`/`07` territory.

## 5. Housekeeping

- `swaps.hair` = 29-module hunt net (active). `dev/bisect_hunt.sh` splits it.
- Backups in `~/.local/lib/callisto/`: `swaps.hair.bak_hunt_20260826_2234`
  (the 3-module 22:34 hunt), `swaps.hair.bak_probe_20260827_0018` (the
  Phase 0 spec_add build — reinstall it when Phase 0 gets a real scene).
- Build artifacts: `CallistoSSS/swaps.huntall/` (+ `.h.*.json` reports).
- The rim-three probe config for reproduction:
  `--tier hair --hair-class 4 --set spec_add=8 w_wrap=1.0 k_diff=4.0
  r_max=8.0 m_aniso=0 m_dual=0 k_sheen=0 s_h=1.0 a_min=0.0`
