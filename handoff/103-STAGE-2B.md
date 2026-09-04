# 103 — Stage 2b UNLOCKED: a 64-bit TLAS address reaches a COMPUTE resolver, and Stage 2c ran on this driver

Written 2026-09-03. **SHOT 2026-09-03 21:38 — `bda-probe` GREEN in direct sun (§12): all four of `98` §10.3's holes are now closed, the fourth on screen.** Original text follows.

Written 2026-09-03. This closes `98` §10.3's four holes — **three of them
measured on the driver, the fourth pre-registered for a launch that has not
happened** (it has now — §12).** Three rungs built, gated, self-tested, parked, selectable.
**Nothing shot. Nothing committed. `make install` NOT run.**

`98` §10.3 said "stopped at the design, four holes, stated precisely." All four
are addressed below and each one says whether it is **measured** or **inferred**.
A dispatch that reads the magic is not a picture; a ray query that hits a
synthetic triangle in a self-test is not a hit in Night City. Everything below
labels which it is.

---

## 0. Verdict first

| question | answer | confidence |
|---|---|---|
| Can the layer put a 64-bit device address into a compute module's constants? | **Yes.** 256 B slot, `SHADER_DEVICE_ADDRESS` usage + `MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT`, rewritten at `vkCreateShaderModule` | **high — measured**, self-test case A |
| Does a COMPUTE dispatch actually read it? | **YES.** A real `vkCmdDispatch` on this RTX 4070 read `slot[0] == 0xca115701` back through a `PhysicalStorageBuffer` pointer the layer fixed up | **high — measured**, case A |
| Does the app already have `bufferDeviceAddress`? | **Yes**, and the layer detects rather than forces it: `decide:"already_enabled_vk12"` | **high — measured** in the self-test; **inferred for the game**, but `VK_KHR_acceleration_structure` requires the feature and vkd3d-proton enables that extension on every RT device |
| Which memory type? | `mem_type:4`, `mem_flags:7` = `DEVICE_LOCAL｜HOST_VISIBLE｜HOST_COHERENT` — the BAR heap. Coherent on purpose, so the record-time write needs no flush | **high — measured**, hole 3 |
| Is the marker forgery-proof? | **Yes on the evidence available.** A reserved `OpString` + two structurally located `OpConstant`s named by SSA id; **0 of 3416** dumped modules carry the marker or either sentinel half | **high — measured** (census, gate 8); "proof" is an absence over 3416 modules, not a theorem |
| Does the reject guard fall through to the **next overlay**, never to vanilla? | **Yes — measured both ways**, and it caught two real layer bugs on the way (§4.3) | **high — measured**, cases C/E/F |
| Is the TLAS address stable enough for a constant fixup? | **Yes** — `98` §13.4 measured `handles_with_moving_addr:0`, `addr_moved:0` over 600 presents / 632 TLAS builds. **The indirection was built anyway** (brief's preference), so stability is not load-bearing | **high — measured** for stability; the indirection makes it moot |
| Does the layer's TLAS hook actually refresh the slot? | **YES.** In the self-test the layer wrote `0xdf3e100000` into words 2/3, byte-for-byte the address the app itself queried | **high — measured**, case B |
| **Does a COMPUTE-side inline ray query work off that address?** | **YES, off-screen.** `rq_up=1` (committed hit on a triangle at z=+1), `rq_dn=0` (miss downward). Same query, opposite direction, opposite answer | **high — measured**, case B |
| Will the real ~300 KB resolvers **link** in the game's pipeline? | **Unproven, and honestly so.** Proven at `vkCreateShaderModule` (76/76 at shipped size, accepted) but NOT at `vkCreateComputePipelines` — see §7.1 for exactly why, and why the synthetic dispatch is the stronger evidence anyway | **medium — inferred.** This is hole 4 and it is a launch |
| Will the game's TLAS address reach the journal in-game? | **Probably.** `98` §13.4 measured `addr_calls:15679` against `creates:15679` — the app queries the address of every AS it creates. But the layer needs the query to precede the *build*, and that ordering is **inferred**, not measured | **medium — inferred.** Pre-registered as void row V2 |
| Which TLAS does the slot point at? | The **populated** one. `98` §13.4 found two TLASes built in lockstep, one permanently `instances_last:0`; a query against the empty one commits nothing, so `bda_note_tlas` latches the populated one and ignores empty builds thereafter | **high — coded to a measurement** |

**One-line summary.** `98` §10.2 measured that compute modules cannot reach the
RTAS heap; the layer now hands them the TLAS by value instead. A layer-owned
256-byte host-coherent buffer carries `{magic, generation, addr_lo, addr_hi,
prims, builds, frame, flags}`; every recorded top-level build refreshes words
2/3; a reserved `OpString` in the overlay names the two `OpConstant`s that hold
the pointer's halves, and the layer rewrites exactly those two words at
`vkCreateShaderModule` after checking four conjuncts. On this driver a real
compute dispatch read the magic, and a real compute inline ray query, built from
the address the layer delivered, hit a triangle and missed empty space.
**Stage 2b is unlocked. Stage 2c ran off-screen. Neither has been on screen.**

---

## 1. What was built

Three rungs on the standing base
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense`:

| rung | what it is | modules touched |
|---|---|---|
| `bda-ctl` | **byte-identical to the base**, 93/93. Control for the selector, the deploy and the layer itself | 0 |
| `bda-probe` | **Stage 2b.** Loads `slot[0]` through the fixed-up pointer; class-1 (skin) pixels paint GREEN on `== magic`, RED otherwise | 76 of 77 compute resolvers, 151 write sites |
| `bda-rq-probe` | **Stage 2c.** Converts `slot[2..3]` to an acceleration structure, traces one ray straight up from the resolver's world P converted to TLAS space; skin paints BLUE on hit, AMBER on miss, RED if the magic was wrong | 75 of 77, 150 write sites |

Declines, by name, the same two as `99` §5 and for the same reasons:
`ab0bc2fee876d489` (its one `OpImageWrite` stores a v4uint reservoir record, not
radiance — `46` §12) is declined in **every** mode; `99bb7c2698997b2a` (the big
GI resolver, no view vector so no position chain — `97` §1.5) has a radiance
write so `bda-probe` still paints it, and only `--mode rq`, which needs P,
declines it.

The 16 raygens in all three rungs are **verbatim from the base** (gate 5). This
family touches compute only.

---

## 2. The slot, and the marker ABI

### 2.1 The slot (layer side, 256 B, `CALLISTO_BDA_WORDS = 64`)

| word | name | written by | meaning |
|---|---|---|---|
| 0 | `BDA_W_MAGIC` | `bda_setup`, once | `0xCA115701`. The shader's "am I talking to the layer" test |
| 1 | `BDA_W_GEN` | `bda_note_tlas` | increments only when the address actually **changes** |
| 2 | `BDA_W_LO` | `bda_note_tlas` | TLAS device address, low 32 |
| 3 | `BDA_W_HI` | `bda_note_tlas` | TLAS device address, high 32 |
| 4 | `BDA_W_PRIMS` | `bda_note_tlas` | instance count of the last top-level build |
| 5 | `BDA_W_BUILDS` | `bda_note_tlas` | top-level builds seen |
| 6 | `BDA_W_FRAME` | `bda_note_tlas` | frame of the last refresh |
| 7 | `BDA_W_FLAGS` | `bda_note_tlas` | bit 0 = a populated TLAS has been seen |

Words 8–63 are reserved and zero. The shader reads words 0, 2 and 3 only.

**Why no barrier.** The memory is `HOST_COHERENT`, and in the steady state the
write is a **no-op**: `changed` is false, so words 2/3 are not touched at all.
`98` §13.4's `addr_moved:0` says that is the normal case. The only writes that
matter happen once, long before any dispatch reads them, and the implicit
host→device domain operation at `vkQueueSubmit` covers them.

### 2.2 The marker (module side) — `98` §10.3 holes 1 and 2

Verbatim from the shipped `bda-probe/03dc7a51279e7427.dxil.spv`:

```
%7 = OpString "CALLISTO_BDA_SLOT_V1 lo=%0000000178 hi=%0000000179 sent=ca1157000bda0001 magic=ca115701"
```

The ids are zero-padded to a fixed width (`ID_W = 10`) for a reason that cost an
hour: **`spirv-as` does not preserve numeric SSA ids written in assembly.**
`%9001` came back as id 18. So `patch_bda.py` assembles once with placeholder
ids, reads the *real* ids of the two sentinel constants out of the assembled
binary, and rewrites the marker in place — same byte length, so no re-assembly
and no id churn (`resolve_marker_ids`). The build asserts the substitution
changed the string and did not change its length.

**Hole 1 (no discriminating capability) is closed by this string, not by a
capability.** `98` §10.3 measured 3281/3322 modules declaring
`PhysicalStorageBufferAddresses`; the current dump says 3282/3323. It
discriminates nothing and the layer never looks at it.

**Hole 2 (accidental sentinel) is closed by never scanning for a value.** The
layer takes the two ids **from the module's own marker** and then validates four
conjuncts before touching a byte (`bda_fixup`, `swap_layer.c`):

1. **exactly one** marker in the module (two markers → `two_markers`, refused —
   ambiguity is a reject, never a pass);
2. the marker parses, both ids are non-zero and distinct, and both are below the
   module's id bound `w[3]` (`marker_malformed`, `id_out_of_bound`);
3. each named id is **exactly one** `OpConstant` whose type is a 32-bit unsigned
   `OpTypeInt`, found by walking the header to the first `OpFunction`
   (`named_ids_are_not_uint_constants`);
4. those two constants **currently hold** `0x0BDA0001` and `0xCA115700`
   (`constants_do_not_hold_the_sentinel`).

Only then are those two words overwritten with the address halves. Conjunct 4
also makes the fixup **idempotent-hostile on purpose**: a second pass over
already-fixed bytes fails, which is how layer bug 2 (§4.3) was caught.

Census, gate 8: **3416 modules scanned (0 unreadable): 0 carry
`CALLISTO_BDA_SLOT_V1`, 0 carry either sentinel half as an `OpConstant %uint`.**

---

## 3. The splice, instruction by instruction

### 3.1 `bda-probe` — hoisted into the entry block, once per module

Verbatim from the shipped bytes:

```
%182 = OpLabel
%183 = OpCompositeConstruct %v2uint %uint_198836225 %uint_3390134016
%184 = OpBitcast %_ptr_PhysicalStorageBuffer__struct_42 %183
%185 = OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint %184 %uint_0
%186 = OpLoad %uint %185 Aligned 4
%187 = OpIEqual %bool %186 %uint_3390134017
%188 = OpSelect %float %187 %float_0_150000006 %float_3      ; r: green 0.15 : red 3.0
%189 = OpSelect %float %187 %float_3 %float_0_150000006      ; g: green 3.0  : red 0.15
%190 = OpSelect %float %187 %float_0_150000006 %float_0_150000006  ; b
```

`%uint_198836225` = `0x0BDA0001` (lo) and `%uint_3390134016` = `0xCA115700`
(hi) are the two constants the marker names; `%uint_3390134017` = `0xCA115701`
is the magic and is **not** rewritten. `_struct_42` is a fresh `Block`-decorated
struct of 8 `uint` members at offsets 0,4,…,28, every member `NonWritable` —
the game's own BDA idiom, and deliberately **no `OpCapability Int64`**: the
address is carried as a `v2uint` and bitcast, exactly as the engine does it.

Per painted write site the three hoisted channel values are multiplied into the
radiance texel under a class-1 gate, in `94`'s hunt-paint magnitudes so the
frame stays recognisable.

### 3.2 `bda-rq-probe` — the same hoist plus the AS conversion

Verbatim from the shipped `bda-rq-probe/03dc7a51279e7427.dxil.spv`:

```
%190 = OpLabel
%191 = OpVariable %_ptr_Function_181 Function          ; the ray query object
%192 = OpCompositeConstruct %v2uint %uint_198836225 %uint_3390134016
%193 = OpBitcast %_ptr_PhysicalStorageBuffer__struct_42 %192
%194 = OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint %193 %uint_0
%195 = OpLoad %uint %194 Aligned 4
%196 = OpIEqual %bool %195 %uint_3390134017            ; magic ok?
%197 = OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint %193 %uint_2
%198 = OpLoad %uint %197 Aligned 4                     ; addr lo
%199 = OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint %193 %uint_3
%200 = OpLoad %uint %199 Aligned 4                     ; addr hi
%201 = OpCompositeConstruct %v2uint %198 %200
%202 = OpConvertUToAccelerationStructureKHR %183 %201
```

`OpConvertUToAccelerationStructureKHR` takes the 2-component 32-bit uint vector
directly — another reason `Int64` is never declared.

Per painted write site (verbatim, one site):

```
%1451..%1453 = OpFDiv                      ; P, the module's OWN perspective divide
%1454 = OpAccessChain %_ptr_Uniform_v4float %269 %uint_0 %uint_0   ; camera = member 0
%1459..%1461 = OpFSub %float %145x %145y   ; P - C
%1462 = OpCompositeConstruct %v3float %1459 %1460 %1461
        OpRayQueryInitializeKHR %191 %202 %uint_517 %uint_255 %1462 %float_0_0500000007 %187 %float_3
%1463 = OpRayQueryProceedKHR %bool %191
%1464 = OpRayQueryGetIntersectionTypeKHR %uint %191 %uint_1        ; committed
%1465 = OpINotEqual %bool %1464 %uint_0
%1466 = OpSelect %float %1465 %float_0_150000006 %float_3          ; hit? blue.r : amber.r
%1467 = OpSelect %float %196 %1466 %float_3                        ; magic? ... : red.r
        ... g, b the same shape ...
%1472 = OpIEqual %bool %1403 %uint_1                               ; class == 1 (skin)
%1473 = OpSelect %float %1472 %1467 %float_1
%1474 = OpFMul %float %1390 %1473
%1479 = OpCompositeConstruct %v4float %1474 %1476 %1478 %float_1
        OpImageWrite %215 %1393 %1479
```

with `%187 = OpConstantComposite %v3float %float_0 %float_0 %float_1` — the ray
direction, straight up in the resolver's axis convention.

**`OpFSub`, and NOT a raw P — this is `99` §10.6's two-spaces rule.** The
resolver's P is **world**; the TLAS is built **camera-relative** (`98` §15.7,
proven on screen by `-pxfw`). So the origin is `P − C` where `C` is member 0 of
the same CB the resolver already uses,
`cbv[registers[0]+12][0].xyz`. `verify_bda.py` asserts this structurally by
importing `_check_position_triple` from `verify_wpos.py`, and the build has a
decoy (`--decoy world`) that ships raw world P and **must** be rejected — it is
(gate 7).

Ray parameters: `flags 517` = `Opaque | TerminateOnFirstHit | SkipAABBs` (needs
`OpCapability RayTraversalPrimitiveCullingKHR`), `mask 255`, `tmin 0.05`,
`tmax 3.0`. One query object, reused across all sites, re-initialised at each.

---

## 4. Layer changes (`swap_layer.c` — the only shared file edited)

`git diff --stat`: **559 insertions, 14 deletions.** Rebuilt from scratch with
`make layer` (rc 0), emitting **only** the pre-existing
`swap_layer.c:422 -Wformat-truncation` warning that predates this work. A
report of a "too few arguments, expected 5, have 4" error around lines
2244/2248 was checked and is **stale**: `load_swap()` gained a fifth parameter
(`bda_addr`) and both call sites (now 2276 and 2280) pass five. `touch
swap_layer.c && make layer` compiles and installs the `.so` clean.

### 4.1 Getting the feature

`bda_decide()` is **detect-first, enable-as-fallback**, and its most important
property is what it refuses to do. `VkPhysicalDeviceBufferDeviceAddressFeatures`
must never be chained next to a `VkPhysicalDeviceVulkan12Features`
(VUID-VkDeviceCreateInfo-pNext-02829/02830) — doing so fails device creation for
the whole game. So: if a `Vulkan12Features` is present, the layer reads
`bufferDeviceAddress` out of it and **returns either way**
(`already_enabled_vk12` / `vk12_features_chained_off`); same for a
`BufferDeviceAddressFeatures`. Only when neither is chained does it enumerate
device extensions and add `VK_KHR_buffer_device_address` itself. When the app
chained the struct with the feature **off**, the layer **stands down and says
so** rather than "fixing" it.

Measured decision on the self-test device: `decide:"already_enabled_vk12"`.

### 4.2 Allocating, refreshing, tearing down

- `bda_setup()` runs only on a device that (a) has the feature and (b) wants ray
  tracing — a dozen Proton helper processes create devices through this layer
  and none of them has an AS to point at, so they pay nothing
  (`not_an_rt_device`). Memory selection is two passes: BAR heap
  (`DEVICE_LOCAL｜HOST_VISIBLE｜HOST_COHERENT`) first, plain host-visible
  coherent second. Never non-coherent — a flush has no natural home at record
  time.
- `bda_note_tlas()` is called from `asj_note_build()` for every **top-level**
  build whose address is known, and **prefers a populated TLAS**: once
  `instances > 0` has been seen, empty builds are ignored (`98` §13.4's second,
  permanently empty TLAS would commit nothing).
- `bda_teardown()` unmaps, destroys, frees and logs a summary.

### 4.3 The reject guard, and the two bugs it caught

The guard lives in `load_swap()`, next to the SER and ray-query guards, and
obeys the same rule (`44` §2.1, `98` §7.2): **a module the layer cannot fix up
falls through to the NEXT overlay, never to vanilla.**

> **Layer bug 1 — two-marker ambiguity.** `spv_bda_marker_text` returned the
> first marker it found; a module with two markers made `spv_has_bda_marker`
> return 0, so the guard never ran and the module reached the driver **still
> holding the sentinel** — a dereference of `0xCA115700_0BDA0001`. Fixed:
> `spv_bda_marker_count()` saturates at 2 and `bda_fixup` refuses `nm != 1` with
> reason `two_markers`. Ambiguous is a reject, never a pass.

> **Layer bug 2 — destructive double fixup.** A last-line-of-defence guard in
> `xCreateShaderModule` re-ran `bda_fixup` on modules `load_swap` had already
> fixed. Conjunct 4 correctly failed (`constants_do_not_hold_the_sentinel`) and
> the layer served **vanilla**. Symptom: the dispatch read back `0xeeeeeeee`,
> the host fill. Fixed by moving the base-`swaps/` guard into the tail of
> `load_swap()` and deleting the `xCreateShaderModule` block — the marker is now
> guarded and rewritten **exactly once, in exactly one place**.

Both were found by the self-test, not by inspection. Neither would have been
visible offline.

### 4.4 Log lines (verbatim from the self-test)

```
{"ev":"bda","action":"armed","reason":"armed","decide":"already_enabled_vk12","addr":"0x40e0000","magic":"0xca115701","bytes":256,"mem_type":4,"mem_flags":7,"second_device":0}
{"ev":"bda_fixup","id":"03dc7a51279e7427.dxil","size":32964,"dir":".../swaps.bdarung","addr":"0x40e0000","lo_id":178,"hi_id":179,"nth":1}
{"ev":"bda_tlas","addr":"0xdf3e100000","prims":1,"frame":1,"changes":1}
{"ev":"bda_reject","id":"bda0000000000011.dxil","size":1868,"dir":"...","reason":"id_out_of_bound","action":"next_overlay"}
{"ev":"bda_summary","why":"device_destroy","fixups":76,"tlas_refreshes":0,"tlas_changes":0,"last_tlas":"0x0"}
```

`bda_fixup` lines are capped at 8 (`BDA_MAX_FIXUP_LINES`); the count is in the
summary. `CALLISTO_BDA_DISABLE=1` skips the slot entirely, which is how case E
proves the reject path without touching the modules.

---

## 5. Offline gates — all 10 green (measurement)

`./dev/build_bda.sh --install` → rc 0. Verbatim:

```
=== 0. base: gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)
  77 of 77 compute resolvers round-trip byte-identically
=== 2. patch + assemble the three rungs
  swaps.bda-ctl: 93 modules, 77 identity, spirv-val (vulkan1.4) clean
  swaps.bda-probe: 93 modules, 76 patched, spirv-val (vulkan1.4) clean
  swaps.bda-rq-probe: 93 modules, 75 patched, spirv-val (vulkan1.4) clean
  bda-probe vs bda-rq-probe: 76 of 77 differ (only ab0bc2fee876d489 is common)
=== 3. coverage census
  bda-ctl        77 modules, 0 instructions emitted (the identity control)
  bda-probe      76 painted modules, 1 declined by name, 151 painted writes (0 site-local refetches), 62 distinct marker id pairs
  bda-rq-probe   75 painted modules, 2 declined by name, 150 painted writes (30 site-local refetches), 61 distinct marker id pairs
=== 4. instruction census on the SHIPPED bytes
  bda-ctl        0 markers, 0 sentinel constants, 0 added PSB bitcasts, 0 Initialize, 0 Proceed, 0 committed-type getters, 0 AS conversions
  bda-probe      76 markers, 152 sentinel constants, 76 added PSB bitcasts, 0 Initialize, 0 Proceed, 0 committed-type getters, 0 AS conversions
  bda-rq-probe   75 markers, 150 sentinel constants, 75 added PSB bitcasts, 150 Initialize, 150 Proceed, 150 committed-type getters, 75 AS conversions
=== 5. bda-ctl identity
  bda-ctl: 93 of 93 byte-identical to gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
  bda-probe: 76 of 93 differ (all compute; the 16 raygens are verbatim)
  bda-rq-probe: 75 of 93 differ (all compute; the 16 raygens are verbatim)
=== 6. verify_bda.py on the shipped .spv
verify_bda OK (--mode probe): 76 modules, 151 painted writes, 1 declined by name, 62 distinct (lo,hi) id pairs across the set; marker sentinel ca1157000bda0001 magic ca115701; slot 8 x uint
verify_bda OK (--mode rq): 75 modules, 150 painted writes, 2 declined by name, 61 distinct (lo,hi) id pairs across the set; marker sentinel ca1157000bda0001 magic ca115701; slot 8 x uint; flags 517 mask 255 tmin 0.05 tmax 3, origin = P - cbv[..][0]
verify_bda --negative OK: 0 of 93 modules carry CALLISTO_BDA_SLOT_V1 or either sentinel half
verify_bda --negative OK: 0 of 93 modules carry CALLISTO_BDA_SLOT_V1 or either sentinel half
=== 7. verifier non-vacuity (each of these MUST fail)
  rejected: --decoy nomarker (the pointer, with NO marker to authorise the fixup)
  rejected: --decoy badid (a well-formed marker naming ids that do not exist)
  rejected: --decoy scan (a SECOND, unnamed sentinel pair -- the module on which a value-scanning layer would rewrite the wrong constant)
  rejected: --decoy world (raw world P as the ray origin -- 99 sec 10.6's two-spaces trap)
  rejected: --decoy noflags (flags 4: no Opaque, no SkipAABBs)
  rejected: the unpatched BASE read as a rung
  rejected: the bda-ctl CONTROL read as a rung
  rejected: bda-probe read as the ray-query rung
  rejected: bda-rq-probe read as the magic-only probe
  rejected: bda-rq-probe read against 102's contact reach (tmax 0.10 m)
  rejected: bda-rq-probe read against 101's flag word (545 = CullFrontFacing)
  rejected: bda-probe --negative (a marker-carrying rung read as marker-free)
  rejected: hunt-paint (class-1 paint in this module family, no slot)
  rejected: hunt-wpos (class-1 paint in this module family, no slot)
  rejected: hunt-wpos-cam (class-1 paint in this module family, no slot)
=== 8. marker uniqueness over the whole dump
  3416 modules scanned (0 unreadable): 0 carry `CALLISTO_BDA_SLOT_V1`, 0 carry either sentinel half as an OpConstant %uint
  sentinel = 0xca1157000bda0001  (lo 0x0bda0001 = 198836225, hi 0xca115700 = 3390134016), magic = 0xca115701
=== 9. simulated fixup: rewrite both literals, re-validate
  151 modules rewritten to addr 0x00007f1234567000 and re-validated clean (spirv-val --target-env vulkan1.4)
=== 10. MANIFEST provenance
  3 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim

=== shas (content = cat of all 93 .spv in name order)
  bda-ctl        content=3bb0aee03a1bfda8  compute-half=df1e42643408d1c8
  bda-probe      content=b4ea7e8515eee0f2  compute-half=d693c908d55fafd3
  bda-rq-probe   content=d95ffe64d37831b0  compute-half=dc9665d341686f31
  (base)         content=3bb0aee03a1bfda8  compute-half=df1e42643408d1c8
```

Two gate readings worth writing down, because both were wrong first:

- **Gate 2's cross-rung count is 76, not 75.** 75 modules carry both splices and
  differ in the splice; plus `99bb7c2698997b2a`, which `probe` patches and `rq`
  declines. Only `ab0bc2fee876d489` is common to both.
- **Gate 9 is the one that would have caught a bad rewrite.** It rewrites both
  literals to a plausible address and re-runs `spirv-val` on all 151 modules.
  A fixup that broke the type or the id bound would show here, offline.

`--install` refuses to touch any parked directory that lacks a `.bda-owned`
marker file. Nothing else in `~/.local/lib/callisto/skin.set/` was written.

---

## 6. Driver self-test — 54/54 (measurement)

`./dev/selftest_bda.sh` → rc 0, on **NVIDIA GeForce RTX 4070**, ray query
advertised by the ICD: yes. Verbatim:

```
bda layer self-test  (layer: .../libVkLayer_callisto_spvswap.so)
76 painted compute ids from swaps.bda-probe; 8 synthetic modules

case 0 -- the marker ABI is one ABI
  PASS  swap_layer.c carries CALLISTO_BDA_SLOT_V1
  PASS  swap_layer.c carries 0x0BDA0001
  PASS  swap_layer.c carries 0xCA115700
  PASS  swap_layer.c carries 0xCA115701
  PASS  the layer's slot is 64 words (256 B)

case A -- Stage 2b: the slot is armed, fixed up, and read back by a dispatch
    device: NVIDIA GeForce RTX 4070  ray query advertised by ICD: yes
    device created with 2 extensions requested by the app
    vkCreateShaderModule(<workdir>/stand/bda0000000000001.spv, 204 B) -> 0
    vkCreateComputePipelines -> 0
    slot: [0]=0xca115701 [1]=0x00000000 [2]=0x00000000 [3]=0x00000000 [4]=0x00000000 [5]=0x00000000 [6]=0x00000000 [7]=0x00000000
  PASS  probe exits 0
  PASS  the layer ARMED the slot
  PASS  ...on the app's own bufferDeviceAddress (decide=already_enabled_vk12)
  PASS  ...at a non-zero device address
  PASS  the synthetic module was FIXED UP
  PASS  no bda_reject
  PASS  the compute pipeline LINKED
  PASS  THE DISPATCH READ THE MAGIC (slot[0] == 0xca115701)
  PASS  ...and the buffer was NOT still the host fill (0xeeeeeeee)
  PASS  slot[2]/[3] are zero with no TLAS built

case B -- Stage 2c: the TLAS address reaches the slot and a COMPUTE ray query uses it
    blas addr 0xdf3e140000
    tlas addr 0xdf3e100000
    vkCreateComputePipelines -> 0
    slot: [0]=0xca115701 [1]=0x00000001 [2]=0x3e100000 [3]=0x000000df [4]=0x00000001 [5]=0x00000001 [6]=0x00000001 [7]=0x00000001
    rq_up=1 rq_dn=0
    "ev":"bda_tlas","addr":"0xdf3e100000","prims":1
  PASS  probe exits 0
  PASS  the layer saw a TOP-LEVEL build and refreshed the slot
  PASS  ...with prims 1 (a populated TLAS)
  PASS  slot[3]:[2] == the TLAS device address the app queried (0xdf3e100000 vs 0xdf3e100000)
  PASS  the generation counter moved (slot[1] != 0)
  PASS  THE RAY QUERY HIT the triangle above the origin (rq_up == 1)
  PASS  ...and MISSED below it (rq_dn == 0) -- the query is not stuck on 'hit'
  PASS  the layer enabled VK_KHR_ray_query for a device that never asked

case C -- forgeries: every conjunct of the fixup, refused one at a time
  PASS  probe exits 0 (every forged module degraded, none broke the app)
  PASS  rejected (sentinel_mismatch): real ids, real sentinel, WRONG magic
  PASS  ...and fell through to the NEXT OVERLAY, not to vanilla
  PASS  rejected (sentinel_mismatch): real ids, WRONG sentinel (a marker from another build)
  PASS  ...and fell through to the NEXT OVERLAY, not to vanilla
  PASS  rejected (id_out_of_bound): a marker naming two ids past the module's id bound
  PASS  ...and fell through to the NEXT OVERLAY, not to vanilla
  PASS  rejected (two_markers): two markers in one module (ambiguous, so refused)
  PASS  ...and fell through to the NEXT OVERLAY, not to vanilla
  PASS  rejected (constants_do_not_hold_the_sentinel): a marker naming real uint constants that hold 0 and 1
  PASS  ...and fell through to the NEXT OVERLAY, not to vanilla
  PASS  the marker-free module was NEITHER fixed up NOR rejected (served verbatim)
  PASS  exactly the 2 honest synthetic modules were fixed up (got 2)

case D -- every live rung's real resolvers, served by the overlay, on the driver
  PASS  bda-probe: probe exits 0, no served module refused
  PASS  bda-probe: 76 of 76 real resolvers served at their shipped size and accepted (got 76)
  PASS  bda-probe: the summary counts 76 fixups (got 76)
  PASS  bda-rq-probe: probe exits 0, no served module refused
  PASS  bda-rq-probe: 76 of 76 real resolvers served at their shipped size and accepted (got 76)
  PASS  bda-rq-probe: the summary counts 75 fixups (got 75)
  PASS  bda-ctl: probe exits 0, no served module refused
  PASS  bda-ctl: 76 of 76 real resolvers served at their shipped size and accepted (got 76)
  PASS  bda-ctl: the CONTROL was never fixed up (got 0, want 0)

case E -- CALLISTO_BDA_DISABLE=1: no slot, so every marked module is refused
  PASS  probe still exits 0 (degrades, does not break)
  PASS  the layer skipped the slot, reason env_disabled
  PASS  all 76 marked resolvers rejected with action next_overlay (got 76)
  PASS  and all 76 fell through to the NEXT OVERLAY, not to vanilla (got 76)
  PASS  no marked module went vanilla
  PASS  no fixup happened at all

case F -- refused with no fallback overlay: the app still gets its own module
  PASS  probe exits 0
  PASS  all 76 refused (got 76)
  PASS  and none was served a marker-carrying module anyway

=== 54 passed, 0 failed
```

**Case B is the headline.** The C probe builds a one-triangle BLAS at z=+1 and a
one-instance TLAS, queries the TLAS device address **before recording the
build**, lets the layer's `asj_note_build` hook see the build and refresh the
slot, then dispatches a compute shader that reads words 2/3, converts them to an
acceleration structure and traces up and down. `rq_up=1`, `rq_dn=0`. That is
`98` §10.4's sketch, running.

**A precondition discovered here and stated as a risk:** the app must call
`vkGetAccelerationStructureDeviceAddressKHR` on the TLAS **before** the build is
recorded, or `asj_note_build` sees `addr == 0` and the slot never fills. `98`
§13.4 measured `addr_calls:15679` against `creates:15679` in the real game — it
queries the address of every AS it creates — but the *ordering* relative to the
build is inferred, not measured. Void row V2 below covers it.

---

## 7. What is NOT done

### 7.1 The real resolvers are proven at module creation, not at pipeline link

Case D serves all 76 real ~300 KB resolvers through the layer at their shipped
size and the driver **accepts** every one at `vkCreateShaderModule`. It does not
build a `vkCreateComputePipelines` around them, and that is a deliberate refusal
rather than an omission: their bindless layout aliases three `UniformConstant`
runtime arrays at set 1 binding 1, plus set 2 binding 0 as **both** an SSBO and
a Uniform, plus a push-constant block. Reconstructing that layout in the
self-test would test **my guess at the game's descriptor layout**, and a pass
would mean nothing while a failure would be uninterpretable.

The **dispatched synthetic module** (case A/B) is the stronger evidence for the
splice shape, because it actually runs. This mirrors exactly how `98` §6 and
`dev/selftest_contact_rq.sh` case B proved the raygen half. **Hole 4 is a
launch, and it stays open.**

### 7.2 Also not done

- **Not shot.** No frame. Every colour statement in §9 is a prediction.
- **Not installed.** `make install` was not run; the rungs are parked under
  `~/.local/lib/callisto/skin.set/` and not deployed. Per the deploy-check rule,
  the game runs **copies** — `cmp` and `make install` before reading a launch.
- **Not committed.** Nothing in git.
- **`init.lua` not edited** — see §10.
- **No consumer.** These are diagnostics. `88`'s cavity cone is the intended
  first real consumer (`98` §10.4) and nothing has been pointed at it.
- **Multi-device is logged, not handled.** `g_bda_multi_dev` counts a second RT
  device arming a slot; the first one wins and the second is recorded in
  `second_device`. Fine for this app, wrong in general.
- **The 3 m `tmax` and the straight-up direction are diagnostic choices**, not
  tuned for anything. `bda-rq-probe` answers "does traversal work from a
  resolver", not "is this a good AO ray".

---

## 8. The shoot — READ THIS BEFORE LAUNCHING

**Settings, stated now, before any frame. Do not infer them from a capture
afterwards.**

| setting | value | why |
|---|---|---|
| `ser` | **`class`** | the rungs carry the base's SER-permutation raygens verbatim |
| `shadowset` | **`full-shadow`** — NOT optional | any rung shipping raygens needs it |
| `ptq` | unchanged from the standing default | `ptq_sha` must match or `sync_settings.sh` refuses |
| RR | **OFF** | |
| path tracing | ON, reference/photo mode, camera **pinned** | |
| frame generation | **state it** (`100` §7; also settles `98` §13.4's open builds-per-present question) | |
| sun | **HIGH — face in DIRECT sun** | the paint is a multiply on radiance; it is invisible where radiance is zero |
| `skinspec` | one of the three rows in §10 | |

**Precondition, non-negotiable (`101` §10 row 0, `99` §10.8e):** before reading a
single colour, grep the launch log for `skin_sha`, confirm it equals the §5 sha
for the rung you think you shot, and confirm the served `rgs_reference_main`
permutation.

**New precondition for this family — grep the log for these four lines before
reading any colour:**

1. `"ev":"bda","action":"armed"` — if it says `"skipped"`, read `reason` and stop.
2. `"ev":"bda_fixup"` with a plausible `addr` — at least one, `nth` counting up.
3. `"ev":"bda_tlas"` with `prims` in the tens of thousands — this is the one that
   says the game's own TLAS reached the slot. `prims:0` means the empty TLAS won,
   which the code is supposed to prevent.
4. **No** `"ev":"bda_reject"` at all. Any reject means some resolver went to the
   next overlay and the rung is not what you think it is.

`bda_summary` at exit should read `fixups:76` for `bda-probe`, `fixups:75` for
`bda-rq-probe`, `fixups:0` for `bda-ctl`.

**Order: shoot `bda-probe` FIRST.** It is the only rung that can falsify the
mechanism, and every `bda-rq-probe` reading is conditional on it being green.

**The frame:** a face in direct sun, camera pinned, with open forehead/cheek and
some geometry within 3 m above the head (an awning, a ceiling, a doorway) as
well as a spot with open sky above. Then the identical frame on `bda-ctl` and on
the standing default.

---

## 9. Pre-registered interpretation table (prediction — written BEFORE any screen)

**Read `bda-probe` first. Rows 1–3 are read off `bda-probe` alone.**

| # | reading | what it means | what to do |
|---|---|---|---|
| 1 | `bda-probe`: skin is **GREEN** — **THIS ROW FIRED 2026-09-03 21:38, §12** | **Stage 2b is unlocked in the game.** The layer's slot, its fixup, and a compute-side `PhysicalStorageBuffer` load all work in Cyberpunk's real pipeline. Hole 4 is closed | go to rows 4–7 |
| 2 | `bda-probe`: skin is **RED** | the module ran and the pointer resolved, but the word it read was not the magic. Either the fixup wrote a wrong address or the buffer is not visible to this queue. **The dereference did not fault**, which is itself information | dump `slot[0]` from the layer at exit; suspect memory type before suspecting the splice |
| 3 | `bda-probe`: skin is **unchanged** (neither green nor red) | the splice did not execute. Either the class-1 gate never fires in this frame (compare against `hunt-paint`, same family, same gate) or the resolver was not served. **Not a Stage 2b result either way** | check `skin_sha`, then shoot `hunt-paint` on the same frame |
| 4 | `bda-rq-probe`: skin is **BLUE under the awning and AMBER under open sky** | **Stage 2c is unlocked.** A compute resolver traced the game's own TLAS. This is the result the whole doc is for | write it up; point `88`'s cavity cone at it |
| 5 | `bda-rq-probe`: skin is **AMBER everywhere**, including under a ceiling | the AS handle converted but traversal committed nothing. Suspect, in order: the slot holds the **empty** TLAS (`prims:0` in the log); `tmax` 3 m is short for the geometry; the origin is in the wrong space despite §3.2 | read `bda_tlas`'s `prims` first — it decides between the three |
| 6 | `bda-rq-probe`: skin is **BLUE everywhere**, including under open sky | the origin is inside geometry, or `P − C` is not the TLAS-space point. **Compare with `bda-probe` GREEN in the same frame**: if 2b is green and this is uniformly blue, it is the space, not the address | shoot a `tmin` rung; do not touch the address path |
| 7 | `bda-rq-probe`: skin is **RED** while `bda-probe` is **GREEN** | contradiction — the same magic test, opposite answers, in two rungs built by one patcher. Would mean the two rungs' fixups differ | stop; re-run §6's self-test and `cmp` the deploy before reading anything else |
| 8 | **`bda-ctl` is distinguishable from the standing default** | the layer is not serving what it claims, and **every A/B in this repo inherits the doubt** | stop; §6 self-test and deploy `cmp` before anything else |
| 9 | the game **crashes or hangs** on `bda-probe` but not on `bda-ctl` | the fixup wrote a bad address, or the buffer died before the dispatch. Set `CALLISTO_BDA_DISABLE=1` and re-launch: the rung should fall through to the base image, **not** to vanilla, and the log should carry 76 `bda_reject`/`next_overlay` lines | the disable path is the diagnostic; case E proves it works off-screen |

**Void rows — these are not results, they are wasted launches:**

| # | condition | why it is void |
|---|---|---|
| V1 | the log has **no** `"ev":"bda","action":"armed"` line | no slot exists; the modules were rejected and you are looking at the base image. Read `reason` |
| V2 | the log has `"ev":"bda_tlas"` **never**, or only with `prims:0` | **the game did not query its TLAS address before recording the build**, so §6's precondition failed in the real app. The slot's words 2/3 are zero and `bda-rq-probe` traces a null handle. `bda-probe` is still readable; `bda-rq-probe` is not |
| V3 | `skin_sha` does not match §5, or names an unpatched permutation | **VOID.** No colour means anything (`101`'s whole capture died here) |
| V4 | any `"ev":"bda_reject"` line | at least one resolver fell to the next overlay; the frame is a mixture of rungs |
| V5 | the skin in frame is **not in direct sun** | **VOID, not a null.** A multiply cannot act on zero direct radiance (`99` §10.8e) |
| V6 | `make install` was not run, or the installed/built `cmp` fails | the game runs **copies**; you shot the previous build |

---

## 10. init.lua entries to add

I did not edit `init.lua`. Add these three rows to `SKIN_LEVELS` (style matches
the existing rows at lines 489–542):

```lua
{ id = "bda-ctl",      label = "BDA CONTROL (byte-identical to the shipped default; control for the selector and the layer)" },
{ id = "bda-probe",    label = "DIAGNOSTIC (Stage 2b): skin GREEN = the layer's TLAS slot was read through a fixed-up 64-bit pointer, RED = it was not" },
{ id = "bda-rq-probe", label = "DIAGNOSTIC (Stage 2c): compute-side ray query straight up, 5cm-3m -- skin BLUE = hit, AMBER = miss, RED = the slot magic was wrong" },
```

---

## 11. Files

New, none shared:
`dev/patch_bda.py`, `dev/verify_bda.py`, `dev/build_bda.sh`,
`dev/selftest_bda.sh`, `handoff/103-STAGE-2B.md`.

Edited, one shared file: **`swap_layer.c`** (+559 −14). Rebuilt with
`make layer`.

Imported unmodified: `patch_skin_brdf` (`apply_edits`, `roundtrip_check`),
`patch_chs_brdf` (`load_lenient`), `patch_compute_brdf` (`find_image_writes`,
`detect_target_env`), `patch_wpos` (the position chain), `verify_wpos`
(`_check_position_triple`, `consts`), `cfg_dom`.

Read and **not** edited: `dev/patch_rayq.sh`, `dev/selftest_contact_rq.sh`,
`dev/build_contact_rq.sh`, `dev/patch_earglow_rq.py`, `init.lua`, `Makefile`,
`handoff/CURRENT.md`, `handoff/GOTCHAS.md`, and every existing handoff doc.

Parked (not deployed) at `~/.local/lib/callisto/skin.set/`: `bda-ctl`,
`bda-probe`, `bda-rq-probe`, each carrying a `.bda-owned` marker so
`--install` will never touch a directory this build script did not create.

**Nothing committed. Nothing installed. Nothing on screen.**

## 12. SHOT 2026-09-03 21:38 — GREEN. Row 1 fired.

`a-b-testing/bda/probe-sun-213804.png` (2560×1440, photo mode, same session as
`112` §12's indoor frames — pid 1122072, `bda-probe` served, `status.txt`
`want_skinspec=bda-probe`, `ser=class:in-skin`, `shadowset=full-shadow`,
`failed=0`; log: `bda armed` at `0x4720000`, fixups with **zero**
`bda_reject`, `bda_tlas prims:54869`, all 77 resolvers in `cpipe`).
**USER, verbatim: *"green skin in sunlight"*.** Panam's face, neck and chest
are green; the hair, the clothes, the masked NPC beside her and the ground are
untouched (class-1 gate, as designed). The shaded neck under the collar is
green too — the painted write carries sky/indirect as well as sun outdoors;
`112` §12's indoor frame showed it carries **no local-light radiance** under
PT. Frame generation / RR state not stated by the user.

**What is now proven on screen, in one frame:** the layer's slot exists in
the game, its address is fixed up into a compute resolver's two `OpConstant`
literals at `vkCreateShaderModule`, the resolver runs as a compute pipeline
(hole 4), loads `slot[0]` through a `PhysicalStorageBuffer` pointer and reads
the magic. Stage 2b is unlocked in the game, not just on the driver.

**Not proven by this frame:** Stage 2c (`bda-rq-probe`, a trace on the slot's
TLAS from a resolver) — still §9 rows 4–7, unshot. And the mechanism being
green does not rescue `112`: the resolver pass it lives in does not light a
PT face from local lights.

An earlier frame the same evening (`a-b-testing/bda/probe-indoor-212855.png`,
indoors, local light only) read as row 3 "unchanged" — void under §8's frame
spec, but informative: see `112` §12.

## 13. SHOT 2026-09-03 21:45 — `bda-rq-probe` BLUE on skin in direct sun

`a-b-testing/bda/rq-probe-sun-214502.png` (pid 1132684, `status.txt`
`want_skinspec=bda-rq-probe`, log: armed, fixups, **zero** `bda_reject`,
`bda_tlas prims:0` then `prims:4052` — a smaller TLAS than the 55 k of the
evening's earlier runs; noted, not explained). **USER, verbatim: *"bda-rq-probe
-> direct sunlight reads BLUE on skin"*.** Panam's face and chest carry the
blue multiply (chest B/R 1.19 against 0.67 for the sand and 0.71 for the
masked NPC's neck; the face reads purple because the blue is on top of
sunlit skin). `a-b-testing/bda/probe-doorway-214008.png` (21:40, still
`bda-probe`) is a second GREEN, this time with a doorway lintel above.

**What BLUE proves:** the `OpConvertUToAccelerationStructureKHR` of the slot's
words 2/3 yields a traversable handle and traversal COMMITS hits — §9 row 5
(AMBER everywhere, "the AS handle converted but traversal committed nothing")
is excluded, and row 7 (RED) is excluded. The slot → TLAS → compute-side
inline query chain works end to end in the game.

**What it does not separate:** row 4 from row 6. The probe's ray goes
straight up 5 cm–3 m from the skin point, and from a cheek, forehead or chest
that ray meets the brow, the hair or the chin within centimetres — BLUE on a
face under open sky is the expected geometry, not evidence that the origin is
inside the head or that `P − C` is the wrong space. §8's "open forehead/cheek
with open sky above" was a bad frame spec for a face. The discriminator is
**bare skin with nothing above it** — a hand or forearm held out under open
sky — which should read AMBER, and the same hand under an awning BLUE. Not
shot. Until it is, the TLAS-space correctness of the origin rests on `99`
§10.6 + `112`'s verifier (the origin is asserted to be `P − C`), not on a
frame.
