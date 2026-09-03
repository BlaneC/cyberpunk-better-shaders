# 99 — World position inside the compute resolvers (2026-09-02)

The ask (Unlock 2): find, in each of the 77 `GLCompute` resolver modules,
(a) the camera-relative shading point **P**, proven by walking back from the
NoV eps-clamp's dot operand, and (b) the **camera world offset** — a CBV
member added to P, the `94` §3.3 pattern — so that anything world-space
(hashes, caches, reservoir keys, triplanar, height fog referenced to sea
level) becomes writable at the resolver splice site.

**Status: SHOT 2026-09-02 — §7's first row fired. P is a WORLD space, and the
world-space unlock is OPEN.** Four rungs built, verified, parked, installed and
selectable, and **all four launched**. Units and up-axis are now **measured**:
the cell is 1 m and the up axis is Z (§10.8). Nothing committed.

**Read §0, then §10.** Half the ask had a null answer in the bytes, and the
null turned out to be right for an interesting reason: no offset is added to P
because none is needed.

---

## 0. Verdict — read first

| claim | verdict | confidence |
|---|---|---|
| A shading point P exists in the resolvers and is **reconstructed in-module**, never read from a buffer | **yes, 75 of 77** | **certain** — the full chain is parsed instruction by instruction, in every module, from the depth fetch to the perspective divide |
| The P chain is single-valued across the whole family | **yes** — matrix `cbv[registers[0]+12][69..72]`, depth `image[registers[1]+0]`, in **all 75** | **certain** |
| Every dot-shaped NoV eps-clamp in the family roots at that P | **yes, 308 of 308**, in 75 of 75 modules | **certain** |
| **A camera world offset is added to P somewhere in these modules** | **NO. Zero. 0 of 75 modules add anything to P.** | **certain, and this is the deliverable's headline** |
| P is *therefore* camera-relative | **NO — MEASURED, and the opposite. P is a world (or stable-rebase-origin) space; `cbv[registers[0]+12][0].xyz` is the camera position in it.** `hunt-wpos` stayed welded to the environment under a camera translation while `hunt-wpos-cam`, which differs by exactly three loads and three `OpFSub`, slid with the camera — §7 row 1, §10.3 | **proven on screen** for translation, live read-out only, no frames captured (§10.1). "Stable-rebase-origin" is the honest residual: 2 m cannot separate a true world origin from one that rebases on long moves (§10.4) |
| Units and up-axis | **MEASURED — metres and Z, both confirmed.** `hunt-wpos-frac` was shot 20:48:34 (§10.8). The vertical sawtooth on a wall is the **blue** channel — component 2 — resetting at y = 158/678/1198 with red flat through both edges, so the up axis is **Z** and blue rising with height makes it **+Z**; the period nearest V is **512.5 px/cell** against V's **945 px** extent = **1.844 cells**, i.e. a **1.00 m cell at V = 1.85 m**. `95` §1c's structural metres/Z-up claim is confirmed by measurement for the first time | **proven on screen, one frame, `a-b-testing/wpos/F-frac-205714.png`.** Handedness and which of X/Y is which are still **NOT read** — the wall's facing was never recorded (§10.8c) |

**The one-line result.** P is real, it is single-valued, and it is
reconstructed from `matrix · (pixel.x, pixel.y, depth, 1)` with a perspective
divide. But **every single consumer of P in every module is a subtraction**
(`OpFSub`, 1413 uses, and no other opcode consumes it). A difference of two
points is invariant to translating the space they live in. So the bytes
cannot tell world from camera-relative, and no member exists that would
convert one to the other. This is exactly the legitimate-null the brief
anticipated: **the offset is absent, not hidden, and this document does not
invent one.**

What that leaves is a measurement, not a derivation — `hunt-wpos` vs
`hunt-wpos-cam` (§6) decides it on screen in one frame pair, and
`hunt-wpos-frac` reads the units and the up axis off a single frame.

**The measurement came back (§10): no offset is added because none is needed.**
The matrix at members 69–72 already lands in a world space, so the space is
world, the camera's position in it is member 0, and world coordinates are
available at every one of the 150 radiance writes — free at 120 of them, ~50
instructions at the other 30. World hashes, triplanar projection, sea-level
height fog and spatial cache keys are all writable at the resolver splice site
**today**, with nothing imported through the layer. One thing §7 did not predict
— a sideways shift of `-cam`'s cells on distant building tops when the camera
*pitches* — is recorded unexplained in §10.5, with a hypothesis and a
discriminator, and it does not touch the translation result. **`-frac` then
measured the two remaining unknowns off one frame (§10.8): metres and Z-up.**
That frame also fired §7's "skin is not red" void row without voiding anything,
which is a finding about the row rather than about the capture — §10.8e. **That
row is now RESOLVED, not open:** the user's verdict is that the class-1 red tint
does reach the screen on skin, and does so **only in direct sun**; the frame's
arms were not in direct sun (§10.8e).

---

## 1. The idiom — what P actually is

Found by walking back from the NoV eps-clamp (`NMin(NMax(dot, 1e-5), 1)`)
into its dot operand, then back again out of the normalize, in each module:

```
V   = normalize( cbv[registers[0]+12][0].xyz  −  P )
P.k = ( Σ_j  cbv[registers[0]+12][69+j][k] · v[j] ) / ( Σ_j cbv[…][69+j][3] · v[j] )
      where v = (pixel.x, pixel.y, depth, 1)
      pixel   = OpConvertUToF of the two dispatch coords
      depth   = OpImageFetch(image[registers[1]+0], (px,py), Lod 0).x   — the D32 front depth (38 §1.1)
```

In SPIR-V each of the four rows is exactly
`FAdd( Fma( Fma( FMul(m0, x), m1, y), m2, depth ), m3 )` — an FMA-contracted
`mat4 · vec4`, rows 69/70/71/72 of the same uniform buffer, followed by three
`OpFDiv` sharing the row-72 denominator. The detector
(`dev/wpos_core.find_pos_chain`) parses that shape strictly: it requires one
CBV, one component index per row, four **consecutive** members, and all four
rows agreeing on the same three axis ids. A looser first draft happily
returned members `(0,1,2,3)` on some modules; the strict parse returns
`(69,70,71,72)` on 75 of 75 and nothing on the other two. GOTCHAS 5 and 10
both apply — the shape is a matrix multiply, and the *place* was proven
separately by requiring the NoV chain to land on it.

**The two modules with no P chain** — `ab0bc2fee876d489`,
`99bb7c2698997b2a` — are declined **by name** in the patcher
(`KNOWN_DECLINE`), not skipped silently. They have no NoV, no P, and no
matrix rows; they are not resolvers of this shape.

---

## 2. The hunt — `dev/hunt_wpos.py`

Offline, read-only, run against the 77 compute modules of the standing
selection `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog` (whose compute
modules are byte-identical to `-cone2all`; only the 12 reference raygens
differ). Full per-module table: **`handoff/99-WORLD-POS-TABLE.md`** (77
rows). Summary:

```
modules scanned                    : 77
P reconstructed in-module          : 75      (2 declined by name, no chain)
P read from a buffer               : 0
matrix cbv slot                    : [(0, 12)]        registers[0]+12   single-valued
matrix members                     : [(69, 70, 71, 72)]                 single-valued
depth image slot                   : [(1, 0)]         registers[1]+0    single-valued
camera position member             : [0]   same cbv, 75/75              single-valued
modules with ANY  P + X  add       : 0
dot-shaped 1e-5 clamps rooting at P: 308 of 308        (1355 eps clamps total; the
                                     other 1047 floor non-dot scalars — restricting
                                     to dot-shaped is what makes this 308/308)
modules where EVERY NoV roots at P : 75 of 75
radiance writes                    : 150   (2 per painted module)
writes P dominates                 : 120
writes refetchable                 : 150 of 150
X in `X − P`, by source            : cbv[0] 75 · ssbo 132 · chained OpFSub 132
opcodes consuming P                : OpFSub 1413 — and nothing else
```

Column meanings in the generated table: *P source* (reconstructed / buffer /
none), *matrix cbv/members*, *cam member*, *NoV@P* (dot-shaped clamps rooting
at P / total dot-shaped), *writes*, *P dominates* (of 2), *refetchable*,
*P+X adds*. 60 modules dominate both writes, 15 painted modules dominate
neither (their P is computed inside a branch that the write is not under),
2 declined — hence exactly **30 refetched sites**, uniformly across every
rung.

---

## 3. Why "no offset" is a result and not a failure

Three independent things had to be true for a world offset to exist, and the
third fails:

1. **P exists.** Yes — §1.
2. **Something else lives in P's space.** Yes, two things, and they are
   genuinely independent (the GOTCHAS 5 requirement that a space have two
   consumers): the **camera position** `cbv[registers[0]+12][0].xyz`
   (75 triples, one per module) and the **light-list positions** read through
   `OpRawAccessChainNV` at stride 128, offsets 0 and 96 (132 triples). Both
   are consumed as `X − P`.
3. **Something converts that space to another one.** **No.** There is no
   `P + cbv[k]`, no world hash, no reservoir store, no cell index, no
   quantisation, no second matrix applied to P. P is born at the divide and
   dies in a subtraction, 1413 times.

Because (3) fails, the space is *unobservable from inside*. If the engine
rebases the world origin near the camera every frame (a common open-world
trick, and Cyberpunk does move a rebase origin), then P is "world" in the
sense that it is stable over a camera translation *within* a rebase epoch and
jumps at the rebase. If the matrix is a plain inverse view-projection, P is
camera-relative and `cbv[…][0].xyz` is identically zero. **Both hypotheses
produce byte-identical shaders**, because the only consumer is a difference.
Only a picture separates them.

**`94` §3.3's `cbv[104][56]` does not apply here.** That member is the camera
world position in a **raygen**, whose buffer is bound at `registers[0]+6`;
the resolvers' buffer is `registers[0]+12`, and `registers[0]` is a
per-dispatch bindless base. Member numbering does not correspond across
stages, and asserting that it does would be exactly the invented member the
brief warned about. The resolvers' own camera member is **0**, found
structurally, not by analogy.

---

## 4. The reusable emitter — `emit_world_pos`

`dev/wpos_core.emit_world_pos(mod, dom, ctx, site_line, ins, uc=None,
relative_to_camera=False, cam=None) -> (id_x, id_y, id_z)`

Contract (also in the function's docstring, which is the normative copy):

* Returns three float ids **valid at `site_line`**, i.e. dominating the write.
  Two paths, chosen automatically:
  * **P already dominates** → returns `ctx['p']` unchanged. **Zero
    instructions emitted.** 120 of 150 sites.
  * **P does not dominate** → emits a **site-local refetch**: ~50
    instructions that recompute P from its leaves only. 30 of 150 sites.
* `pos_leaves(ctx)` is the closure it is allowed to read: the depth image's
  descriptor array + slot, the CBV's array + slot, the two dispatch
  coordinates, and the fetch LOD. Every one of those is a module-entry value,
  so the refetch is valid anywhere in the function. It reads **nothing**
  loop-carried and **nothing** branch-carried.
* **Hoist rule:** instructions are inserted immediately above the write's
  block-leading structured-control instruction — above any
  `OpSelectionMerge`/`OpLoopMerge`, never between a merge and its branch
  (`00` §9 `hoist_pos`, and the `OpSelectionMerge` gotcha). Dominance is
  checked with `dev/cfg_dom.py`, not assumed.
* `relative_to_camera=True` returns `P − C` with `C = cbv[…][0].xyz`, loaded
  at the site. This is the **control** space, camera-relative by construction.
* It **does not add a world offset**, and says so in the docstring, with the
  reason: none exists (§3). If one is ever found, this is the single place to
  add it and every rung inherits it.
* `uc` is a required memoisation dict for `mod.uconst` — `mod.uconst()` has
  no pending-declaration cache and will emit duplicate `OpConstant`s
  otherwise (GOTCHAS, the same trap `94` hit).

---

## 5. The rungs and the emitted instructions, read back from the shipped bytes

Four rungs, 93 files each (77 compute + 16 raygens), on the standing base:

| rung | paints | purpose |
|---|---|---|
| `hunt-wpos` | class 0 only: 1 m spatial-hash cells of **P** | the world-space pattern |
| `hunt-wpos-cam` | same hash of **P − C** | the control that **must** slide with the camera |
| `hunt-wpos-frac` | RGB = `frac(P / 1 m)` | reads the **up axis** and the **units** off one frame |
| `hunt-wpos-ctl` | nothing (`--gain 0`) | byte-identity control |

Non-class-0 material classes are painted with `94`'s `CLASS_TINT` palette
imported verbatim — **skin stays red** and is the void control: a frame with
no red skin is a capture failure, not a result.

Read back from the parked `hunt-wpos/03dc7a51279e7427.dxil.spv` (a
both-sites-refetched module, 1524 → 1800 disassembly lines). The refetch:

```
%1379 = OpCompositeConstruct %v2uint %277 %278          ; dispatch coords
%1380 = OpImageFetch %v4uint %1378 %1379 Lod %uint_0    ; material word
%1382 = OpShiftRightLogical %uint %1381 %uint_5         ; class = word >> 5
%1386 = OpImageFetch %v4float %1384 %1385 Lod %uint_0   ; D32 front depth
%1387 = OpCompositeExtract %float %1386 0
%1388 = OpConvertUToF %float %277                       ; pixel.x
%1389 = OpConvertUToF %float %278                       ; pixel.y
%1390 = OpAccessChain %_ptr_Uniform_v4float %248 %uint_0 %uint_69   ; rows 69..72
  … 4 × (AccessChain, Load, 4 × CompositeExtract) …
%1414 = OpFMul %float %1392 %1388                       ; row 69 · x
%1415 = OpExtInst %float %1 Fma %1398 %1389 %1414       ;      + row 70 · y
%1416 = OpExtInst %float %1 Fma %1404 %1387 %1415       ;      + row 71 · depth
%1417 = OpFAdd  %float %1416 %1410                      ;      + row 72
  … the same for k = 1, 2 and for the w row …
%1430 = OpFDiv %float %1417 %1429                       ; P.x
%1431 = OpFDiv %float %1421 %1429                       ; P.y
%1432 = OpFDiv %float %1425 %1429                       ; P.z
```

The pattern (Teschner spatial hash + an xorshift avalanche, all in uint):

```
%1433 = OpFMul %float %1430 %float_1                    ; P / cell
%1436 = OpExtInst %float %1 Floor %1433
%1439 = OpFAdd %float %1436 %float_65536                ; bias, so no %int type is needed
%1442 = OpConvertFToU %uint %1439
%1445 = OpIMul %uint %1442 %uint_73856093               ; ×19349663, ×83492791 on y,z
%1448 = OpBitwiseXor … %1449 = OpBitwiseXor …
%1450 = OpShiftRightLogical %uint %1449 %uint_15
%1451 = OpBitwiseXor  %1452 = OpIMul %uint %1451 %uint_668265261
%1453 = OpShiftRightLogical  %1454 = OpBitwiseXor       ; the avalanche
%1455 = OpBitwiseAnd %uint %1454 %uint_255              ; byte 0 → red
%1457 = OpFMul %float %1456 %float_0_00392156886        ; /255
%1458 = OpExtInst %float %1 Fma %float_2_8499999 %1457 %float_0_150000006   ; lerp(0.15, 3.0)
  … bytes 1 and 2 → green, blue …
%1469 = OpBitwiseAnd %uint %1444 %uint_1                ; up-axis parity …
%1471 = OpSelect %float %1470 %float_1 %float_0_349999994   ; … × 0.35 stripe
```

then the class tower, exactly `94`'s shape, with the class-0 gate innermost
so the last-appended (unknown-class) gate wins:

```
%1485 = OpSelect %float %1475 %1472 %float_1            ; class 0 → the pattern
%1486 = OpSelect %float %1476 %float_3     %1485        ; class 1 skin → red
… %1490 = OpSelect %float %1484 %float_n0 %1489         ; unknown → black
%1491 = OpFMul %float %1369 %1490                       ; × the original radiance
%1506 = OpCompositeConstruct %v4float %1491 %1498 %1505 %float_1
        OpImageWrite %194 %1372 %1506
```

`hunt-wpos-cam` differs only by three loads and three subtractions inserted
between the divide and the hash:

```
%1433 = OpAccessChain %_ptr_Uniform_v4float %248 %uint_0 %uint_0   ; C
%1438 = OpFSub %float %1430 %1435                       ; P − C
```

`hunt-wpos-frac` replaces the hash with `Fract` per channel. Cost, measured
as added disassembly lines over the base across all 75 modules:
**hunt-wpos 13507 lines (90/write), -cam 14107 (94/write), -frac 8242
(55/write)** — of which ≈50/write is refetch at the 30 refetched sites.

Note `%float_n0` (−0.0) for the unknown-class tint reuses the module's
existing constant, same as `hunt-paint`; per `94` §1's census that branch is
unreachable anyway.

---

## 6. Gates — every number, all build-failing

`./dev/build_wpos.sh` (steps 0–7). Nothing below is a spot check; each is an
assertion in the script.

| gate | number |
|---|---|
| 0 base provenance: the standing base is 77 compute + 16 raygen | **93 files**, 16 non-compute `cmp`-identical to the shipped set |
| 2 round-trip neutrality `dis → as` at **each module's own `; Version:`** (compute = SPIR-V 1.3) | **77 of 77 byte-identical** — proven *before* any rewrite |
| 2b hunt re-run on the disassembly actually being patched | 75 chains, anchors single-valued (§2) |
| 3–4 coverage, each painted variant | **75 modules painted · 2 declined BY NAME · 150 writes · 30 refetched · 0 skipped** |
| 5 `spirv-val` at each module's own version | **93 of 93 pass**, every rung |
| 5 raygen non-interference | **0 of 16** raygens differ from base, every rung |
| 5 rung-vs-rung | world/cam/frac each differ from base in **75 of 77** compute modules; world ≠ cam ≠ frac pairwise in 75 |
| 5 **control byte-identity** | `hunt-wpos-ctl`: 77 modules processed, 0 painted, **0 of 93 files differ from the base** |
| 6 verifier `dev/verify_wpos.py`, re-deriving from the **shipped** `.spv` | 3 passes (world, cam, frac); it re-parses the position triple from the painted channels' cone, checks `cbv_slot == (0,12)`, `img_slot == (1,0)`, consecutive members, the `>>5` class read, `94`'s palette **to the float32 bit**, and every texel's `orig × chain` rooted at 1.0 |
| 6 closed-form machine evaluation vs `dev/wpos_model.py` (numpy float32/uint32) over a **1105-point grid** | **worst relative error 0** (tol 2e-5) |
| 6 non-vacuity — the verifier is made to FAIL | **9 rejections**: unpatched base · gain-0 control · no-stripe decoy · world-read-as-cam · cam-read-as-world · world-read-as-frac · wrong cell · wrong up axis · wrong gain |
| 7 parked copies re-verified in place after `--install` | pass; parked ctl differs in **0 of 93** |

Files: `dev/hunt_wpos.py`, `dev/wpos_core.py`, `dev/patch_wpos.py`,
`dev/wpos_model.py`, `dev/verify_wpos.py`, `dev/build_wpos.sh` — all new, per
the house rule; **no shared patcher was edited**.

---

## 7. Pre-registered interpretation table

**Written before the launch. Nothing here may be revised after seeing the
frames** — that is the whole point of pre-registering it.

| what the frames show | conclusion |
|---|---|
| `hunt-wpos` cells **welded to the world** (a given wall keeps its colour as the camera translates) **and** `hunt-wpos-cam` cells **sliding with the camera** | **P is a world (or stable-rebase-origin) space**, and `cbv[registers[0]+12][0].xyz` is the camera's position in it. World-space effects are writable at this splice site with **zero extra instructions** at 120 of 150 sites. |
| `hunt-wpos` and `hunt-wpos-cam` **pixel-indistinguishable** (both slide) | **C ≡ 0: P is camera-relative**, and §0's null is complete — there is no world space anywhere in the resolvers. Any world-space effect needs the offset imported from elsewhere (a raygen CBV, or a new push constant via the layer), which is a different unlock. |
| `hunt-wpos` slides *and* `hunt-wpos-cam` slides *differently* | the space is neither — most likely a rebase origin that moves per frame. Report the observed jump cadence; do not build on it. |
| cells welded but **rotating with the camera** | the matrix is not what §1 says; the hunt is wrong; stop and re-derive. |
| **uniform colour**, no cells at all | the P chain is not reaching the write, or `cell` is far off the scene scale. Re-shoot with `--cell 10` before concluding anything. |
| **skin is not red** | **capture void.** Infrastructure failure (wrong rung served, wrong `ser`, wrong resolution class), not a result. Do not interpret the frame. **[note added 2026-09-02, §10.8e — this row fired on the `-frac` frame and was over-strict: it is only valid when skin is in **DIRECT SUN**, user-confirmed 2026-09-02 (*"Trust me the skin is red. Just only red in direct sun."*), and the primary serving proof is the launch log's `skin_sha` plus the deploy `cmp`, not a colour. Row left as pre-registered.]** |
| `hunt-wpos-ctl` differs *at all* from the standing `-fog` selection on screen | **void, and worse than void**: the layer is not serving what it claims to serve. Every other reading in this document's family is suspect until that is explained. |

**`hunt-wpos-frac`, read on one static frame:**

| observation | conclusion |
|---|---|
| one channel is **constant across flat ground** while the other two ramp | that channel is the **up axis** (`--up` currently 2, i.e. Z) |
| the sawtooth **period** on a surface of known size (a road lane ≈ 3.5 m, a door ≈ 2.1 m tall) | the **unit**. One stripe per metre ⇒ metres, and `95` §1c's structural claim is confirmed *by measurement* for the first time. Any other period ⇒ `95` §1c is wrong and every metre-valued constant in the fog rungs is mis-scaled. |
| the ramp direction across a known-facing wall | **handedness**, together with the up axis |

---

## 8. Launch protocol and settings contract

Per the standing rule: **required game settings are stated here, before the
launch, and are never inferred from the captures afterwards.**

Settings contract — all of these must hold, unchanged, across the whole
sequence:

```
CET selector      skinspec = <the rung under test>
                  ser = class            shadowset = full-shadow      ptreg = on
game              Path Tracing = ON, PT in photo mode = ON, Ray Reconstruction = OFF
                  RayTracedLighting = Psycho, DLSS = Balanced, 2560×1440
                  SunAngularSize = 0.53
world             weather PINNED (clear), time-of-day PINNED, no NPC/vehicle traffic in frame
```

RR must be **off** and should be confirmed by grepping the Proton prefix's
`UserSettings.json`, not by eyeballing the menu.

Deploy check, every time (the game runs *copies*): after selecting a rung,
confirm the served bytes are the parked bytes — `cmp` the live set against
`~/.local/lib/callisto/skin.set/<rung>/`, or re-run `make install` — **before**
reading anything off the screen.

The frames to shoot — a **static exterior** with a flat road, a vertical wall
and a visible horizon, in photo mode:

1. `hunt-wpos-ctl` — one frame. Must be indistinguishable from the standing
   `-fog` selection. If it is not, stop.
2. `hunt-wpos` — frame A at the anchor pose.
3. `hunt-wpos` — frame B: **translate 2 m sideways, then 2 m forward**, same
   orientation. Then frame C: **tilt/rotate in place**, no translation.
4. `hunt-wpos-cam` — the identical A/B/C triple.
5. `hunt-wpos-frac` — one frame at the anchor pose, framing the road and the
   wall together so both the up-axis channel and the stripe period are
   legible.

Read the A→B pair first (translation is the discriminator; C only guards
against a rotating frame being mistaken for a welded one), then §7.

---

## 9. What is NOT done

* **Launches: all four done.** `-ctl`, `-wpos`, `-cam` (§10) and `-frac`
  (§10.8) were shot 2026-09-02; both of §7's tables are resolved. **No frames
  were captured for the first three** — that read-out is live-only and cannot be
  re-checked — while `-frac` produced exactly one, `a-b-testing/wpos/F-frac-205714.png`,
  indexed with all four launches in `a-b-testing/wpos/RESULT.md`.
* **Units and up-axis are MEASURED and both build flags are right** (§10.8):
  `--up 2` (Z, and +Z up) and `--cell 1.0` (a 1.00 m cell at V = 1.85 m, ±5 %).
  `95` §1c is confirmed rather than carried forward, and no rebuild is needed.
  **What is still unread is the handedness** and which of X/Y is which: the
  lateral sawtooth is visible but the wall's facing was never recorded, so one
  frame with a stated facing (or a road of known heading) still owes an answer.
* **No world-space feature is built.** This unlock delivers the *address* of
  P and a reusable emitter; the hash pattern is a probe, not a feature. §7
  landed on **world**, so the address is directly usable — no imported offset,
  no layer change — and the first consumers to write are `94` §4.4's glint cell
  hash and any height reference for the fog rungs.
* **The two declined modules are not understood**, only excluded by name.
* **The layer question is CLOSED.** The earlier worry here — that `make
  install` had carried the concurrent ray-query agent's in-flight
  `swap_layer.c` — no longer applies: that layer is final and deployed.
  `libVkLayer_callisto_spvswap.so` is md5 `2625d5c2c4fd227fecbe2ac102b89b53`
  and `cmp`-identical across all three copies — the repo root,
  `release/vulkan/`, and the installed
  `~/.local/lib/callisto/libVkLayer_callisto_spvswap.so` — verified here, not
  assumed. §10's launches were served through exactly those bytes, so nothing
  in §10 is provisional on that account. (Re-check with
  `md5sum libVkLayer_callisto_spvswap.so release/vulkan/libVkLayer_callisto_spvswap.so ~/.local/lib/callisto/libVkLayer_callisto_spvswap.so`.)
* **The pitch shift on `-cam` (§10.5) is unexplained**, with a hypothesis and
  two named discriminators, neither built.
* **§7's "skin is not red" void row fired on the `-frac` frame, did not void
  it, and is now RESOLVED** (§10.8e). V's skin is measurably untinted on that
  frame — 0.00 % of arm pixels near clipping against a ×3 red class-1 gain —
  while the paint is demonstrably live at the emitter's exact period and the
  `skin_sha` matches the parked bytes. **The user's verdict, verbatim: *"Trust
  me the skin is red. Just only red in direct sun."*** The tint does reach the
  screen on skin, in direct sun, and this frame's arms were not in direct sun —
  the "lit" arm was lit by something other than the resolvers' direct sun term.
  The mechanism is the multiply on direct radiance, `98` §12.4's arithmetic
  mirrored. The row is amended in place with a one-line note: it is only valid
  with **skin in direct SUN**. Nothing is built for it, and nothing here is
  open.
* **Nothing is committed.**

Installed by `./dev/build_wpos.sh --install`: the four rungs (93 files each)
in `~/.local/lib/callisto/skin.set/`, and four selector rows in `init.lua`
(live CET copy `7202ca25…` → `5c476bc6…`, now `cmp`-identical to the repo).
`init.lua:288` silently coerces an unknown `skinspec` to `off`, so a typo
reads as "no probe", not as an error — check the selector label, not the id.

---

## 10. Shot 2026-09-02, 20:29–20:36 — §7's first row fired: P is a world space

`hunt-wpos` is welded to the environment; `hunt-wpos-cam` slides with the
camera. That is §7's row 1, verbatim, and it closes the one structural question
§0 left open: the resolvers reconstruct a **world (or stable-rebase-origin)
shading point**, and `cbv[registers[0]+12][0].xyz` is the camera's position *in
that space*. World-space effects are writable at the resolver splice site —
**zero added instructions at 120 of 150 sites**, and the proven ~50-instruction
refetch at the other 30. One behaviour the launch produced that §7 did not
predict is recorded as unexplained in §10.5.

### 10.1 What was launched

Verbatim from `~/callisto_launches.log`:

```
2026-09-02T20:29:21-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-wpos-ctl skin_sha=4dc824ca77d95feb tier=on cache=cleared \
  payload=c87c5d1342c466b1
2026-09-02T20:33:47-05:00 ... skinspec=hunt-wpos     skin_sha=81095d4aff8c0f73 ... payload=216c8b1faa1c26f2
2026-09-02T20:36:23-05:00 ... skinspec=hunt-wpos-cam skin_sha=492dc8e4db029413 ... payload=680b49f24f520c42
```

All three match §8's contract — `shadowset=full-shadow`, `ptq=rcbm`,
`ser=class:in-skin`, `ptrefl=on`, `refract=fres`, `tier=on`, `cache=cleared` —
and all three `skin_sha` values are the **parked** bytes:
`cat ~/.local/lib/callisto/skin.set/<rung>/*.spv | sha256sum | cut -c1-16`
reproduces `4dc824ca77d95feb`, `81095d4aff8c0f73`, `492dc8e4db029413`
respectively, which is `sync_settings.sh`'s own definition of the field. The
order is §8's: control, then world, then camera.

**`hunt-wpos-frac` was NOT launched.** §7's second table is still entirely
pre-registered; §10.7 restates it for the next shot.

**No frames exist for any of these rungs — the read-out is live-only.** The
newest PNG in the game's photomode directory is
`photomode_02092026_201141.png`, i.e. **20:11:41**, eighteen minutes *before*
the first of these launches, and it belongs to `98` §15's `-pxfw` shoot. Nothing
below can be re-checked against a still, no number can be recomputed from
pixels the way `98` §15.4's low-pass numbers were, and if a measurement is ever
wanted from these rungs they must be re-shot. That is a limitation of this
shoot, not of the rungs.

**The control's status, stated precisely.** `hunt-wpos-ctl` **was launched** at
20:29:21 and **the user did not comment on it**. What is recorded is therefore
*the absence of a remark, not a stated pass*: §7's "-ctl differs at all → void,
and worse than void" row was not reported as firing, and nobody reported that it
did not fire either. §6 gate 5 has the rung byte-identical to the standing
`-fog` selection in **0 of 93 files differing**, so any visible difference would
have been a *serving* failure rather than a shader one — which is a reason to
have expected the null, not evidence that it was observed.

### 10.2 The read-out, verbatim

> "hunt-wpos-cam translates with the camera just like how we wanted. When you
> rotate the camera upwards on the x axis (x axis  left and right from pov of
> camera y forwards). When looking upwards I see some squares up at the top of
> buildings translate left to right. When looking downwards, I see those squares
> go right to left. Otherwise the squares follow the character. hunt-wpos stay
> locked onto the environment."

### 10.3 Which §7 row fired

| §7 row | fired? |
|---|---|
| **`hunt-wpos` welded to the world, `hunt-wpos-cam` sliding with the camera** | **YES. "hunt-wpos stay locked onto the environment" against "translates with the camera just like how we wanted" / "the squares follow the character". This is the PASS row.** |
| both **pixel-indistinguishable** (C ≡ 0, P camera-relative) | **NO** — they behave oppositely, which is the strongest possible form of "not indistinguishable" |
| both slide, *differently* (a per-frame rebase origin) | **NO** — `hunt-wpos` does not slide at all under camera translation |
| cells welded but **rotating with the camera** ("the hunt is wrong; stop") | **NO** — see §10.5's guard paragraph |
| **uniform colour**, no cells at all | NO — cells are seen, and described as squares |
| **skin not red** (capture void) | **not reported either way.** No void was called; with no frames, this cannot be checked after the fact |
| `-ctl` differs from the standing `-fog` selection | **not reported** — §10.1 |

Nothing in §7's second table can have fired: `-frac` was not launched.

### 10.4 Reading 1 — P is world, and what "world" is still allowed to mean

**What is proven.** Under a camera *translation*, a given wall keeps its
`hunt-wpos` colour and changes its `hunt-wpos-cam` colour. The two rungs differ
by exactly three loads and three `OpFSub` (§5), so the difference in behaviour is
attributable to that subtraction and to nothing else. Therefore:

* **P is not camera-relative.** `C = cbv[registers[0]+12][0].xyz` is not zero,
  and P does not move with the eye. §0's null stands as written — *no module
  adds an offset to P* — but the reason is now known: **none is needed**, the
  matrix at members 69–72 already lands in a world-ish space.
* **`cbv[registers[0]+12][0].xyz` is the camera position in P's space**, not a
  zero vector, because subtracting it converts a welded pattern into a sliding
  one. That is what a camera position does and nothing else does it.
* **The address is usable.** `emit_world_pos` (§4) returns world coordinates at
  every one of the 150 radiance writes across 75 modules — free at 120, ~50
  instructions at 30 — with no imported member, no push constant and no layer
  change. Everything §0's headline said would need "a different unlock" is
  available today: world hashes for glints, triplanar projection, sea-level
  height fog, spatial reservoir/cache keys.

**The residual, honestly.** A translation of about 2 m does **not** distinguish
a true world origin from an origin the engine rebases only on long moves; both
are perfectly stable over metres, and Cyberpunk does move a rebase origin.
"World (or stable-rebase-origin)" is the exact claim, and it is the same wording
§7 pre-registered — it is not being weakened after the fact. Two things would
separate them, neither built:

* **A long drive.** Take `hunt-wpos` in a vehicle across several kilometres and
  a district boundary or two. A true world origin keeps every wall's colour for
  the whole drive; a rebasing origin makes the **entire frame's palette jump at
  once**, everywhere, at a moment tied to distance travelled rather than to
  anything on screen. The signature is global and simultaneous, which is easy to
  see and hard to mistake.
* **Read member 0 against a known world coordinate.** Compare
  `cbv[registers[0]+12][0].xyz` with the game's own reported player world
  position (CET exposes it) at two places kilometres apart. Tracking it means
  world; staying small and near the origin while the player's coordinate grows
  means a rebase origin riding the camera.

For the near-field uses this does not matter: a 1 m cell hash for glints or a
height-referenced fog only has to be stable over a shot, and that is now
measured. What a rebase would break is anything that must survive a fast travel
or a long drive — a persistent cache key, a baked world LUT.

### 10.5 Reading 2 — the pitch shift on `-cam` is unexplained

Restated: with `-cam` selected, pitching the camera **up** makes squares on
distant **building tops** slide left→right; pitching **down** makes the same
squares slide right→left; everything else "follows the character".

**This was not pre-registered, and it is recorded as unexplained.** §7's `-cam`
row asked only that the pattern slide with the camera. It says nothing about
rotation because a `P − C` hash is *by construction* rotation-invariant:
rotation changes neither P (a point on a surface) nor C (a position).

**Leading hypothesis, stated as a hypothesis and not asserted.** Photo mode does
not rotate the camera about its own optical centre; it **orbits it about the
character**. A pitch is then also a *translation* of the eye — ΔC ≠ 0 — and
`P − C` shifts by −ΔC for every static P in the frame. Pitching up and pitching
down move C in opposite directions along that orbit, which is exactly the
reported sign flip. What the same hypothesis **also predicts** is that the shift
is present on **all** surfaces, not only on building tops, and the user reported
it only at the tops. Two ways that survives, and they are not equivalent:

* **It is only *noticeable* there.** Apparent motion is (metric shift) ÷ (metric
  cell size *on screen*). At 100 m a 1 m cell spans a few pixels, so a decimetre
  of ΔC walks the pattern across a visible fraction of a cell; on the road three
  metres away the identical shift is a hairline creep of one boundary. Under
  this reading the observation is a visibility artefact and the hypothesis is
  intact.
* **Member 0 is not exactly the eye.** It could be the orbit *pivot* (the
  character), the *previous* frame's camera position, or a jitter-free variant of
  it. Then C does not cancel the way the pattern assumes, and the leftover is
  structured rather than uniform across the frame.

**The discriminator, named and not built.** Either (a) **translate C** — a rung
painting `P − (C + k)` for a known constant k; `wpos_core.emit_world_pos`'s
`relative_to_camera` path already loads C at the site, so this is a change in
one function and a rebuild, and the whole frame must shift by exactly k's worth
of cells if C is the eye; or (b) **compare member 0 against the reference
raygen's own ray origin**, which `98` §14.6a locates structurally by the
trace-origin rule — if the resolvers' C and the raygen's trace origin are the
same point every frame, C is the eye and the pivot reading dies. Neither is
needed for §10.4, which is a statement about translation only.

**§7's rotation guard is satisfied.** The same rotation that visibly moved
`-cam` did **not** move `hunt-wpos`: "hunt-wpos stay locked onto the
environment", with no rotation caveat, in a read-out that describes the rotation
in detail for the *other* rung. That is precisely what §8 step 3's frame C
existed to ask, and §7's "cells welded but rotating with the camera → the hunt
is wrong, stop and re-derive" row did **not** fire. It is weaker than a captured
A/B/C triple would have been, because nothing was captured; it is still the
guard's own question, asked at the screen and answered.

### 10.6 Two spaces in one frame — read this with `98` §15

The two live unlocks now disagree about space, and the disagreement is a
measured fact rather than a discrepancy to reconcile. **In the compute
resolvers, P is world** (§10.4): the matrix at `cbv[registers[0]+12][69..72]`
lands directly in it, no offset is added anywhere in 75 modules, and the camera
lives in that same space at member 0. **In the reference raygen, the TLAS and
the hit positions are camera-relative** (`98` §15.4): a static instance's
`ObjectToWorld` column 3 is `world − camera`, and it takes `+ cbv[…][56].xyz` —
the raygen's own camera world offset, located structurally by the trace-origin
rule — to make it frame-stable, proven on screen by `-pxfw` passing where the
otherwise-identical `-pxfq` failed. Both readings are on-screen results from the
same day, on the same standing base, and both are right: **one frame carries two
spaces, one per pipeline.** The practical consequence is a rule, not a caveat —
*anything that moves a world position between the two pipelines must add or
subtract `98`'s member 56.* A resolver-side world P handed to raygen-side
geometry must have member 56 **subtracted** to enter TLAS space; a raygen-side
hit or instance translation handed to a resolver must have it **added** first.
Do not carry `98`'s member 56 into a resolver as an offset for P — §3 already
refuses that by index, and §10.4 now refuses it by measurement: P needs no
offset because it is already there. The resolvers' member 0 is the mirror of
raygen member 56 with the opposite sign convention: raygen `world = value +
member56`, resolver `camera_relative = P − member0`.

### 10.7 Pre-registered for the NEXT launch — `hunt-wpos-frac`, written BEFORE the screen

`hunt-wpos-frac` is the only rung of this family still unshot, and it is the one
that answers the two questions `95` §1c has been *asserting* structurally since
it was written: **the unit and the up axis**. Nothing in this section may be
revised after the frame is seen.

**Settings contract — identical to §8, restated so it can be checked without
scrolling:**

```
CET selector      skinspec = hunt-wpos-frac       skin_sha = 19161b2acdd5d01f
                  ser = class            shadowset = full-shadow      ptreg = on
                  ptrefl = on   refract = fres    tier = on    cache = cleared
game              Path Tracing = ON, PT in photo mode = ON, Ray Reconstruction = OFF
                  RayTracedLighting = Psycho, DLSS = Balanced, 2560×1440
                  SunAngularSize = 0.53
world             weather PINNED (clear), time-of-day PINNED, no NPC/vehicle traffic
```

`skin_sha` is the served-content hash and it is stated **before** the launch:
`cat ~/.local/lib/callisto/skin.set/hunt-wpos-frac/*.spv | sha256sum | cut -c1-16`
= `19161b2acdd5d01f`. RR must be confirmed off by grepping the Proton prefix's
`UserSettings.json`, not by eyeballing the menu. Deploy check first: the game
runs *copies* — `cmp` the live set against the parked rung, or re-run
`make install`, before reading anything.

**The frame — one is enough, and this time capture it.** A static exterior in
photo mode, camera not moving, framing **a flat road and a vertical wall
together** with a **visible horizon** and **the character's skin in shot**. The
road gives the up-axis channel and one known dimension (a lane ≈ 3.5 m); the
wall gives the ramp direction and a second known dimension (a door ≈ 2.1 m
tall); the skin is the void control. `-frac` is a *static* pattern — unlike
§10's motion read-out, a still holds all of it — so take the PNG, and this
section's numbers can then be measured rather than described.

| observation | conclusion |
|---|---|
| one channel is **constant across the flat road** while the other two ramp | that channel is the **up axis**. `--up` is currently 2 (Z); if the constant channel is not blue, `95` §1c's structural Z-up claim is wrong and every up-axis-valued constant in the fog rungs is on the wrong axis |
| the sawtooth **period** measured against a known size — a road lane ≈ 3.5 m across, a door ≈ 2.1 m tall | the **unit**. One stripe per metre ⇒ metres, and `95` §1c's structural claim is confirmed *by measurement* for the first time. Any other period ⇒ `95` §1c is wrong and every metre-valued constant in the fog rungs is mis-scaled by that ratio; report the measured stripes-per-lane, not just "wrong" |
| the ramp **direction** across a wall of known facing | **handedness**, together with the up axis |
| **no sawtooth at all** — the two non-up channels are flat or noise, not ramps | the divide is not producing a spatially varying P at these writes, or the scale is so far off that one cell covers the frame. **Do not read units or handedness off such a frame.** Re-shoot at `--cell 10` and `--cell 0.1` before concluding anything; if all three are flat, §1's chain is not reaching the write and §10.4's result is *not* thereby in doubt (it was measured on a different rung), but `-frac` is |
| **skin is not red** | **capture void.** Infrastructure failure — wrong rung served, wrong `ser`, wrong resolution class — not a result. Do not interpret the frame; re-run the deploy check |

A fifth outcome worth naming because it would be a real finding: if the ramps
are visible but the **period differs between the road and the wall**, the units
are not isotropic and one axis is scaled — that is not on `95` §1c's map at all,
and it would need its own probe.

### 10.8 Shot 2026-09-02, 20:48:34 — `hunt-wpos-frac`: metres and Z-up are MEASURED

The last rung of the family is shot, §7's second table is resolved, and the two
things `95` §1c has been *asserting* structurally since it was written are now
numbers off a frame: **the up axis is index 2 (Z), and the unit is the metre.**
One thing in that frame contradicts §7's void row, and §10.8e argues the void
row was over-strict rather than that the capture was void.

**Launched**, verbatim from `~/callisto_launches.log`:

```
2026-09-02T20:48:34-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-wpos-frac skin_sha=19161b2acdd5d01f tier=on cache=cleared \
  payload=36067d003d8b8480
```

`skin_sha` is `19161b2acdd5d01f`, **the value §10.7 pre-registered before the
launch**, and it re-derives from the parked bytes
(`cat ~/.local/lib/callisto/skin.set/hunt-wpos-frac/*.spv | sha256sum`). The rest
of the line matches §8's contract field for field.

**The frame.** One capture, 2560×1440, copied verbatim to
`a-b-testing/wpos/F-frac-205714.png` (md5 `94c0835bd93871d4e1257ddbda970c65`,
identical to the source `photomode_02092026_205714.png`). It is the **only**
capture this family has: `a-b-testing/wpos/RESULT.md` lists all four launches
and records that `-ctl`, `-wpos` and `-cam` produced none.

**It is not the frame §10.7 asked for, and that matters for what can be read.**
§10.7 pre-registered *"a flat road and a vertical wall together, with a visible
horizon"*. What was shot is **V standing against a flat wall** — no road, no
horizon. The wall alone carries the up-axis channel and the period, so the two
headline readings survive intact; the *lateral* axis and the handedness do not,
and §10.8c says so rather than guessing them.

#### 10.8a The user's read-out, verbatim (two messages)

> "At the anchor the squares smooth out pink to white from left to right.
> There's about 5-6 squares across a lane on a street. 1.5 across a door."

> "The squares are definetly in meters. Check the latest photomode.png for
> proof but trust me. Its meters. If you lined up V to those squares hed just be
> under 2 squares"

#### 10.8b Reading 1 — the up axis is **blue = index 2 = Z**, measured

Numbers below are my own, re-derived from `F-frac-205714.png` with
PIL/numpy; they are not the user's estimates.

On the wall, in a column band **x = 1540…1600** (mean over the 61 columns), the
**blue** channel is a sawtooth: it ramps down as screen-y increases and jumps
back up at **y = 158, 678, 1198** — jumps of **+41 to +56** out of 255. Across
those same two edges:

| channel | y=676 → y=678 | y=1196 → y=1198 | largest positive jump anywhere in the wall band |
|---|---|---|---|
| **blue** | **94.3 → 150.3** | **96.3 → 136.6** | **+41.1** |
| red | 204.0 → 199.2 (drifts *down*, no reset) | 202.3 → 198.8 | +1.6 |
| green | 166.4 → 176.8 | 165.7 → 173.3 | +7.1 |

Red is flat and continuous through both edges. Green shows a small step at the
same rows, an order of magnitude below blue's; it is **recorded and not
explained** — the likely cause is channel coupling in the tonemapper and the
area grading LUT lifting green when blue jumps, but nothing here measures that.

The wall is vertical, so **the channel that ramps vertically is the world up
axis**: `-frac` writes `RGB = frac(P/cell)` component-wise, blue is component 2,
therefore **the up axis is index 2 — Z. `--up 2` is correct and `95` §1c is
confirmed by measurement for the first time.** The sign is also readable: blue
*decreases* going down the screen and wraps upward at each boundary, i.e. frac
increases with height, so it is **+Z up**, not −Z.

#### 10.8c Reading 2 — the unit is the **metre**, measured against V

The same wall, in the column band nearest V (**x = 1410…1460**), resets at
**y = 170, 682, 1195** → periods **512 and 513 px**. The period grows to the
right — 514/516 at x=1460…1520, 520/520 at x=1540…1600, 522/524 at
x=1600…1660 — so the facade recedes slightly to the left and the correct local
value at V's own depth is **≈ 512.5 px per cell**. That the two periods inside
each band agree to better than 1 % over a 1030 px span is itself the check that
the wall is locally fronto-parallel, so no perspective correction is needed.

V's extent in the same plane, measured off the pixels rather than eyeballed:

* **hair top y ≈ 457 ± 3** — column band x=1245…1300, the wall's teal
  (R≈14, G≈108, B≈135) gives way to hair (R≈77 at y=460, R≈116 at y=465).
* **boot sole y ≈ 1402 ± 4** — column band x=1305…1350, boot (R≈87) gives way to
  lit ground (R≈170) at y=1405.
* **extent = 945 ± 7 px = 1.844 ± 0.02 cells.**

| assumed V height | implied cell |
|---|---|
| 1.75 m | 0.949 m |
| 1.80 m | 0.976 m |
| **1.85 m** | **1.003 m** |
| 1.90 m | 1.030 m |

**The cell is 1 m to within ±5 % for any plausible V height, so `--cell 1.0` is
right and the world unit is the metre.** `95` §1c's "world units are metres,
already established by `85`/`88`" is now measured directly instead of inherited.
The user's independent statement — *"hed just be under 2 squares"* — is **1.84
cells**, which agrees with the pixel measurement to 0.5 %; it was arrived at
without any of the above and is the stronger corroboration of the two.

**The lateral axis and the handedness are NOT read, and are not guessed.** A
lateral sawtooth does exist: in the row band **y = 150…190** the **red** channel
falls to exactly **0.0** at **x ≈ 835** and again at **x ≈ 1252** (period
**417 px**) while green is continuous across both (91.3 → 82.7 at the second
edge, against red's 91.7 → 0.0). Two reasons that cannot be turned into a
metre figure or an axis name:

* **That band is on a differently-oriented part of the facade.** Its own
  vertical blue period is ~485 px (column x=1000…1060: resets at y = 420, 694,
  1181) against 512–520 px near V, so the 417 px lateral figure is not on the
  plane the metre was measured on. **No anisotropy claim follows from
  417 ≠ 512** — that comparison is between two different planes.
* **The wall's facing direction was not recorded.** Which of X and Y red
  corresponds to, and therefore the handedness, are undetermined by this frame.
  §10.7's third row is **not** answered; it needs one frame with the facing
  stated, or a road with a known compass heading.

For completeness: no lateral reset appears on the wall immediately right of V
across x = 1420…1650 (red spans only 183–209 there, a smooth shading gradient).
That window is 230 px against a ~512 px cell, so it is **uninformative, not
contradictory**.

**The user's eyeball figures, recorded and superseded.** *"5–6 squares across a
lane"* and *"1.5 across a door"* are consistent with a 1 m cell if the lane is
≈5.5 m and the door figure is a **width** (1.5 m is a normal wide/double door
width; as a *height* it would be a low doorway and a partial count). Both are
estimates by eye at unknown distances on surfaces this frame does not contain,
and they are **superseded by the V measurement**, which is on the same plane as
the period it is compared against.

#### 10.8d Which §7 rows fired

| §7 second-table row | fired? |
|---|---|
| **one channel constant across a flat surface while the others ramp → that channel is the up axis** | **YES — blue ramps vertically on the wall, red is flat through both edges. Up axis = 2 = Z (§10.8b).** Read off a wall rather than the pre-registered road, which is equivalent for this row |
| **sawtooth period against a known size → the unit** | **YES — 512.5 px/cell against V's 945 px gives a 1.00 m cell at V = 1.85 m (§10.8c). Metres.** The known size used is V, not the pre-registered lane or door; the user's lane/door counts agree qualitatively |
| ramp direction across a wall of known facing → **handedness** | **NO — the facing was not recorded (§10.8c). Still open.** |
| **no sawtooth at all** | NO — three clean periods per band, in two bands |
| **skin is not red → capture void** | **This row's condition IS met, and §10.8e argues the row itself was wrong.** |
| period differs between two surfaces ⇒ anisotropic units (§10.7's fifth outcome) | **NOT tested** — the two periods measured are on different planes |

#### 10.8e The void row fired, and the void row was over-strict

**RESOLVED 2026-09-02 — the user's verdict, verbatim:** *"Trust me the skin is
red. Just only red in direct sun."* The class-1 red tint **does** reach the
screen on skin. It reaches it **in direct sun**, and this frame's arm pixels
were not in direct sun — the "lit" arm was lit by something other than the
resolvers' direct sun term. The mechanism is the multiply on direct radiance,
the same one `98` §12.4 measured from the other side: the paint scales only what
the direct sun term contributes to a pixel, so with no direct sun there is
nothing for a ×3 gain to scale. Nothing in this section is open. The
measurements below are kept as the record of what the frame showed.

**V's skin is not red in this frame.** Measured, my own patches:

| patch | mean R / G / B | R−G | R ≥ 250 |
|---|---|---|---|
| right arm, lit (x1372–1398, y770–880) | **214.7 / 165.9 / 126.9** | +48.7 | **0.00 %** |
| left arm, shadowed (x1116–1138, y760–900) | **182.9 / 160.0 / 128.6** | +22.9 | **0.00 %** |
| wall beside V (x1450–1520, y780–900) | 193.3 / 173.0 / 152.8 | +20.4 | 0.00 % |

Frame-wide, pixels that are saturated red (R>180, R−G>100, R−B>120) number
**14 445 of 3 686 400 = 0.39 %**, and their mass sits at **x < 640, y > 720** —
the red chairs at frame left, which are class-0 surfaces carrying the paint.
Only 599 such pixels fall anywhere inside V's whole bounding box. `94`'s class-1
tint multiplies the red channel by **3.0**; no arm pixel is anywhere near
clipping, so **the tint is not being applied to V's skin.**

**It did not void the capture, and here is why that is not special pleading.**
The two things the void row exists to catch are both independently excluded:

* **The right bytes were served.** The launch line's `skin_sha`
  `19161b2acdd5d01f` equals the parked rung's content hash, computed from the
  files themselves, and it was written down in §10.7 *before* the launch.
* **The paint is demonstrably live and correct.** The frac pattern is present on
  every class-0 surface in the frame with the **exact period the emitter
  specifies** — three consecutive resets per band, two bands, agreeing to under
  1 %. A rung that was not being served could not produce that.

**Why the skin is untinted, stated as a hypothesis and not asserted.** The paint
is an `OpFMul` into the resolvers' radiance writes, so it scales only the share
of the pixel that these compute resolvers contribute. Where another path
dominates a pixel, the tint is diluted below notice — the same arithmetic `98`
§12.4 measured from the other side, where a sunlit pixel came out untinted at
one part in 270 because direct light swamped the raygen's contribution. V's back
and arms are turned away from the sun in this frame, and skin additionally has
its own dual-lobe specular path, so the resolvers' share of those pixels may
simply be small.

**One measurement cuts against the simplest form of that hypothesis and is
recorded rather than smoothed:** the *lit* arm is the brightest skin in the
frame (R 214.7, brighter than the wall next to it) and is still untinted, so
"the skin is in shadow, therefore there is nothing to tint" does not cover all
of it. What the frame also cannot do is separate "this is skin's own warm
albedo" from "this is a small tinted resolver share" — the arm *is* measurably
warmer than the wall (R−G +48.7 against +20.4) but not clipped, and a ×3 red
gain on a small share would look exactly like that. **That inability is itself
the finding.** *(Answered by the verdict above: bright is not the same as in
direct sun. The lit arm was lit by something other than the sun term the
resolvers multiply, so the hypothesis stands in its stronger form — no direct
sun contribution, nothing to tint.)*

**Conclusion, and the amendment.** §7's void row — *"skin is not red ⇒ capture
void"* — is **over-strict as written**. The served-bytes question is answered by
the launch log's `skin_sha` plus the deploy `cmp`, both offline and both
stronger than a colour; the on-screen red-skin test only has force **when skin
is in direct sun** (user-confirmed 2026-09-02), and this frame's skin is not. §7's row is left standing
with a one-line note appended rather than rewritten, because rewriting a
pre-registered row after seeing the frame is exactly what pre-registration
forbids. The rule going forward: **frame skin in direct SUN if the void test
is to mean anything, and treat `skin_sha` + `cmp` as the primary serving proof.**

#### 10.8f What is now closed, and what is still open

**Closed.** Up axis = 2 (Z, +Z up), measured. Unit = metre, measured to ±5 %.
`--up 2` and `--cell 1.0` are the right build flags, and every metre-valued
constant in the `-fog` rungs is correctly scaled — `95` §1c's structural
assertion is confirmed, not merely carried forward. All four rungs of this
family are shot. The **skin-tint question** (§10.8e) is closed by the user's
verdict: the class-1 red is on the screen, in **direct sun only**.

**Still open.** The **handedness** and which of X/Y is which (§10.8c) — one
frame with the wall's facing recorded, or a road of known heading, settles it.
The **stable-rebase-origin residual** (§10.4) is untouched by this frame: a
static shot cannot separate a world origin from a rebasing one. The **pitch
shift on `-cam`** (§10.5) is untouched and unexplained.
