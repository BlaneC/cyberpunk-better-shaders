# 42 — The skin BRDF was direct-light only: the class gate never reached the bounce resolvers

Written 2026-08-30. Prompt: *the oily skin effect only applies to skin in
direct sunlight from what I can tell — confirm that, and if it is the case,
fix it so any light source or bounce lighting from any light influences the
effect.*

**Confirmed, and the cause is bigger than the gloss.** In the two indirect /
GI resolvers — including `99bb7c2698997b2a`, the one module `10` proved
dispatches **directly** — the class-1 gate reached **none** of the 218 lines
the three passes splice at (205 rejections once the alpha ids are deduped).
Not the gloss, not the roughness cap, and not the shipping tier-1 `c1`
either. Every one was rejected by the dominance check and counted as
`skipped_dom`, while the module still validated, still reported "patched",
and still differed in bytes from the baseline. Bounce-lit skin has never had
any part of this mod's BRDF on it, in either the hair-patcher era or the skin
one.

Fixed by lifting the gate anchor onto the phi that carries the material class
past its own guard. Coverage after: **0 skipped sites anywhere**, 157 → 173
`c1` sites, 879 → 1071 gloss channels, 343 → 408 alpha caps.

**NOT CONFIRMED ON SCREEN.** `19-STATUS.md` carries the row.

---

## 1. What was measured

Per-module, against the same disassembly the shipped `medium` rung was built
from, counting sites *accepted* and sites *rejected for dominance*:

| module | c1 | gloss channels | alpha caps | skipped_dom |
|---|---|---|---|---|
| `99bb7c2698997b2a` (52,765 lines, the GI resolve) | 0 | 0 | 0 | **205** |
| `ab0bc2fee876d489` (18,633 lines, the second one) | 0 | 0 | 0 | **68** |
| every other patched module (75) | 157 | 879 | 343 | 0 |

`00-ARCHITECTURE.md` §9 already names these two and says it plainly: *"Both
failed the normal path because their own class gate dominates **0** eval
sites."* That sentence was written for the hair patcher and stayed true for
the skin one; nothing carried it forward into a check.

The class values `99bb7c2698997b2a` computes, scored against its own 218
splice lines:

```
99bb7c2698997b2a           dominates
  %330  = y >> 5   @3977      0 / 218      <- the anchor the patcher chose
  %329  = OpPhi    @4243    218 / 218      <- the value the SHADER itself uses
  %1553 = y >> 5   @4631      0 / 218
  %2356 = y >> 5   @36214     0 / 218
  %3151 = y >> 5   @44623     0 / 218
```

## 2. Why the shift dominates nothing

dxil-spirv guards the material fetch behind a bounds test and merges the
result out with a phi:

```spirv
      %44574 = OpLabel
               ...
               OpBranchConditional %328 %44586 %44575     ; skip if out of bounds
      %44575 = OpLabel
        %642 = OpImageFetch %v4uint %101 %643 Lod %uint_0
        %644 = OpCompositeExtract %uint %642 1
        %330 = OpShiftRightLogical %uint %644 %uint_5     ; <- the class
               ...
      %44586 = OpLabel
        %329 = OpPhi %uint %uint_0 %44574 %330 %44585     ; <- class, or 0
```

`%330` is defined inside the guarded block, so it dominates nothing below the
merge — and *all* the shading is below the merge. `%329` dominates everything,
and the shader's own class tests read `%329`, not `%330`
(`%5297 = OpIEqual %bool %329 %uint_1`, line 8795, in the middle of the
Fresnel sites). `find_class_shift` anchors on a `>>5` reached through an
`OpImageFetch`, so it can only ever return `%330`; a phi does not match that
shape, and the one comparison against `%uint_1` that *does* read a raw shift
(`%717`, line 4153) is inside the guarded block too.

The direct-light evaluators do not have this problem: they fetch the material
unguarded and switch on it in the same block (`4d46848998312027`:
`%203 = OpShiftRightLogical %uint %196 %uint_5`, then
`OpSwitch %203 … 1 %1540 …`), so the shift dominates every arm.

## 3. Why every check that exists passed anyway

This is the part worth keeping. The Tier-3 build asserts, per rung:

- `spirv-val` clean — **passes**, a module with zero splices is still valid;
- each rung differs from `off` in every module — **passes**, because
  `mod.const()` emits the `alpha_max` / `5r` / `2-r` OpConstants whether or
  not a single site consumes them. On `99bb7c2698997b2a` the `off` → `medium`
  delta was **48 bytes**, i.e. the constants and nothing else. The check
  counts *modules that differ*, and 48 bytes of dead constants differ;
- the ladder's rungs differ from each other — **passes**, same reason;
- `--sets` coverage lists match — **passes**, the module is in both lists.

Every one of these answers "did the file change", and none answers "did any
instruction get spliced". `27` §7.3 recorded *"72 modules differ, 2 identical
— exactly the two GI resolvers"* and read that as the two being skipped;
`27` §8.3 then recorded *"the two GI resolvers … are also covered now — so
faces lit only by bounce light previously got no gloss; now they do"* on the
strength of those same two modules starting to differ. They had started to
differ **by 48 bytes of unused constants**.

The 78cc6b5 commit message inherits the error and inverts the history: the
hair patcher's `if not dominated:` early return was not what *excluded* the
GI resolvers, it was the only thing that ever *handled* them —
`build_hair_gi`, refetching the class at a hoisted common dominator. Deleting
the hair net deleted that path, and the skin passes were left to meet the
dominance check and skip 100% of their sites. Note also that the early return
fired **before** `build_skin_c1`, so the shipping tier-1 diffuse was absent
from the GI resolvers in that era too. There is no era in which bounce-lit
skin got anything.

## 4. The fix

`lift_class_gate()` in `dev/patch_compute_skin.py`. After
`acquire_class_shift` picks an anchor the usual way, score it against every
line the three passes would splice at (`splice_lines()`); if it does not
dominate all of them, walk the `OpPhi %uint` chain that forwards it
(`find_class_phis()`) and take a candidate that dominates strictly more.
The gate is then emitted after the last `OpPhi` in that block, since phis must
stay first in their block.

Three properties, each deliberate:

- **Only a strict improvement replaces the anchor**, so every module whose own
  shift already dominates keeps its old anchor line and its old bytes. That is
  the `69220ed5e0ca675f` lesson quoted in `find_class_shift`: moving a working
  anchor broke a module once already.
- **Every phi operand must be a known class value or a `%uint_` constant.** A
  phi mixing in an unrelated uint would produce a gate that fires on something
  that is not the material class — the silent-wrong-pixel failure, which no
  offline check catches.
- **`%uint_0` as the guard's other operand is correct, not a compromise.**
  Class 0 is not skin, so a pixel that skipped the fetch gates off, which is
  what the shader's own class tests do with the same phi.

Chosen over the hair patcher's refetch-and-hoist because it emits **no
instructions at all** for the class: the value already exists, dominates, and
is the module's own. Refetching would have added an image fetch per module and
re-derived a value sitting one block up.

### 4.1 The check that would have caught it

`dev/patch_compute_skin.sh` now reads the per-module JSON reports after every
build and **aborts** the build if any module reports a non-empty `skipped_dom`
or lands zero `c1` sites, printing coverage per rung:

```
  coverage: 77 modules, 173 c1 sites, 1071 gloss channels, 408 alphas
            (2 gate(s) lifted onto a class phi)
```

Coverage is now asserted from the reports. It is never inferred from a byte
diff again.

## 5. Verification (all offline)

- **77/77 patched, `spirv-val` clean, on all five rungs.**
- **Exactly 2 modules changed** vs the previously installed build — in every
  one of the five rungs, `99bb7c2698997b2a` and `ab0bc2fee876d489` and nothing
  else. The other 75 are byte-identical, which is the no-regression proof.
- Coverage: `skipped_dom` is **0** across all 77 modules on every rung
  (was 16 c1 + 192 Fresnel + 65 alpha sites skipped).
- The new build check was exercised against a doctored report and exits 1.
- `off` → `medium` byte delta on `99bb7c2698997b2a`: **48 → 29,044 bytes**.
- The ladder's own assertions still hold: each rung differs from `off` and
  from the rung below it, in all 77 modules.

## 6. What to expect, and the tuning consequence

The effect now responds to bounce light and to any light resolved through the
indirect path, so at a given rung it will read **stronger overall** than the
same rung did before — interiors and shade most of all, since that is where
the coverage was zero.

**`33` §2's warning now applies to bounce-lit skin as well.** `alpha_max` is a
ceiling: authored skin sits at alpha 0.16–0.36 and `medium` clamps it to 0.09,
so every skin pixel it reaches gets one constant roughness. Until now it
reached only directly-lit skin; it now reaches all of it. That makes `33` §5's
scoped item — replace the ceiling with a **scale**, `alpha' = saturate(alpha·k)`,
one knob at the same site and the same single `replace_all_uses` — the
next thing to build, not a nicety. Start at `subtle` when judging this, not at
the rung that looked right before.

The gloss ladder is opt-in (`33` flipped the default to `off`). The live
`brdf_params.txt` currently reads `skinspec=probe-cls`, which is not a built
rung, so `sync_settings.sh` will warn and serve `off`: pick a rung in the CET
panel before judging any of this.

## 7. What this does **not** fix

- The 7 anchored modules that still fail on *"no material G-buffer read
  found"* (`3acf2ec0e9eb2693`, `57fa8971e5d4bbce`, `d1a91e5e7152cdf7`,
  `e47009fbdc79c311`, `ee2dda2c2440be84`, `f568c84d782802c0`,
  `f7a29100e09ef0d7`). They have no class read the patcher recognises at all —
  a different problem from this one, and none of them is known to dispatch.
- Anything outside the compute resolvers. The Fragment stage has still never
  been shown to execute a splice (`36` G1).
- **Whether it shows.** `10`'s rule stands: a swap HIT proves a module was
  created, not that it ran, and a spliced site proves an instruction exists,
  not that a pixel moved. The A/B is a face in shade or interior light,
  `skinspec` moved one rung, nothing else changed.
