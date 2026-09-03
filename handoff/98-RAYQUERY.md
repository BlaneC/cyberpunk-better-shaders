# 98 — Ray queries as a second G-buffer: SHOT, and the identity is FOUND.

Written 2026-09-02 and revised twice the same day. Revision 1 after review:
the **camera-ray (primary) family became the lead**. Revision 2 after the
first launch (§12): `hunt-rayq-p` and `hunt-rayq-pctl` have been on screen,
**no §5.1 row fired**, and the reason is structural and was already written
down in §3.2. Unlock 1 of the ray-query brief. Nine rungs built, gated
offline, proven on the driver by a self-test, parked, selectable, installed.
**Two shot. Nothing committed.** A swap HIT is not execution and a validated
splice is not a picture — everything below is either a measurement or a
prediction, and each one says which.

Revision 3 after the second shoot (§13): `-pcust`, `-pprim` and `-pclosest`
have been on screen, **the query commits the same triangle every frame and both
instance fields are per-frame**, the AS journal has its first real read-out, and
three more rungs (`-psbt`, `-pgeom`, `-pxf`) are built, gated, parked and
installed. **Twelve rungs. Five shot. Nothing committed.**

Revision 4 after the third shoot (§14): `-pgeom` is a clean positive control,
`-psbt` flickers so the **whole instance record is regenerated per frame**, and
`-pxf` flickered on statics for a reason §13.7 had no row for — `94` §3.3's
**camera-relative space**. Two rungs, `-pxfq` and `-pxfw`, were built to separate
it. Revision 5 after the fourth shoot (§15): **`-pxfw` PASSED.** Static geometry
is flat and stable under camera motion, the TLAS **is** built in camera-relative
space, and `ObjectToWorld` column 3 + `cbv[..][56].xyz`, quantised to 1 cm, is a
frame-stable world-space object key. **Fourteen rungs. Nine shot. Nothing
committed.**

**Read §12 before §5, §13 before §12.7, and §15 before §14.7.** §5, §12.7, §13.7
and §14.7 are left exactly as they were pre-registered, including the rows that
turned out to be unreachable and the mover row §15.5 falsified.

---

## 0. Verdict first

| question | answer | confidence |
|---|---|---|
| Can a ray query be spliced into the reference raygen at all? | **Yes. 10 of 12 permutations, 1 query each, `spirv-val --target-env vulkan1.4` clean** | **high** — built, §2/§4 |
| Does the driver accept and link it in a raygen? | **Yes — measured on this RTX 4070**, both a synthetic module and a real 304 788 B patched raygen | **high** — `./dev/patch_rayq.sh --selftest`, 51/51, §6 |
| Can the layer get `VK_KHR_ray_query` onto a device that never asked for it? | **Yes, alongside SER, with progressive fallback** | **high** — measured, §6 |
| Does the reject guard fall through to the **next overlay**, never to vanilla? | **Yes — measured both ways** (with a second overlay: HIT; without one: vanilla, and that is then correct) | **high** — §6 case B/B2 |
| Does the query commit a hit **at all**, in the game? | **YES — measured 2026-09-02.** Most of the frame paints, the sky stays clean, the control is neutral | **high** — §12 |
| Does it commit the **same** hit each frame? | **Yes — `-pprim` proved the committed triangle is stable (§13).** What changed frame to frame was the *fields*, not the hit | **high** — §13.3 |
| Does `InstanceId` carry a usable object identity? | **No — and neither does `InstanceCustomIndex` nor the SBT record offset.** The whole `VkAccelerationStructureInstanceKHR` is regenerated every frame (§13, §14.5) | **high** — three rungs on screen |
| **Is there ANY frame-stable per-object key?** | **YES, and it is on screen (§15).** `ObjectToWorld` column 3 **+ `cbv[..][56].xyz`**, quantised to 1 cm and hashed: static geometry is flat and stable under camera motion. The TLAS is built in **camera-relative** space, which is why the offset is what makes it work | **high** — `-pxfw` shot, `-pxfq` the control |
| Is `94` §3.3's `P + cbv[104][56].xyz` really frame-stable world space? | **PROVEN ON SCREEN (§15.4).** The same CB member, located structurally as member 56 in 10/10 permutations, makes a *different* camera-relative quantity frame-invariant | **high** — was "inferred, not proven" |
| Does anything here paint the **primary visible surface**? | **It aims at it, and it does not land on it.** The query is aimed down the module's own camera ray, but the paint multiplies this raygen's *radiance*, so it only shows where that radiance is what you are looking at — shadow, ambient, glass, chrome. Sunlit surfaces are untinted, measured at one part in 270 | **high** — §12.4 |
| Is the primary ray re-derived, or the module's own? | **The module's own, structurally located and unique in all 12 permutations** — perspective divide → normalize, exactly one site per module | **high** — §2.2 |
| Is a **compute**-side ray query reachable today? | **No — and now for a measured reason**, not a guessed one: set 1 binding 0 is `RTASHeap` in raygens but `AtomicCounters` in compute (§10) | **high** — census |

**One-line summary.** The mechanism is real, the driver takes it, **the frame
proves it, and the identity hunt is CLOSED with a positive result**: a ray query
aimed down the module's own reconstructed camera ray commits real hits on real
geometry across most of a Cyberpunk 2077 frame, and its committed instance's
`ObjectToWorld` translation **plus `94` §3.3's world offset**, quantised to 1 cm,
is a frame-stable per-object key — static geometry flat and stable under camera
motion, on screen, with a clean sky and a neutral control (§15). Getting there
cost five rejected fields, and the reason they were rejected is now measured
rather than guessed: the engine regenerates the entire instance record every
frame and builds its TLAS in camera-relative space. The screenshot could never have shown flat
per-object silhouettes anyway, because the paint multiplies this raygen's
radiance rather than writing a G-buffer — §3.2 said so before the launch and
§5.1's table failed to carry it into the prediction. That is recorded as a
pre-registration defect in §12.3, not smoothed over.

---

## 1. What was built

### 1.1 New files (nothing shared was edited)

| file | what it is |
|---|---|
| `dev/patch_rayq.py` | the splicer. Emits the ray query + the hash paint, at either site (`--site bounce\|primary`). Imports helpers from the existing patchers; **edits none of them** |
| `dev/verify_rayq.py` | the independent verifier. Re-derives the splice from the **shipped** `.spv` via `spirv-dis` and asserts the operand identities (§4.1), including a **second, independent implementation** of the primary-ray detector |
| `dev/build_rayq.sh` | the build + 10 gates + `--install` parking |
| `dev/audit_rayq_hash.py` | **new (§12.6c)** — a third independent reader: walks the paint's whole operand closure in the shipped bytes and requires every leaf to be a constant, a ray-query getter, or one of the two Private latch variables |
| `dev/patch_rayq.sh` | `--selftest`: the on-device half — layer, extension, reject fall-through, real raygen, AS journal (§6) |
| `handoff/98-RAYQUERY.md` | this file |

Modified: `swap_layer.c` (§7, §8) and nine selector rows in `init.lua` (§9).
The four `hunt-wpos` rows another agent owns are untouched (`grep -c` on the
**installed** `init.lua`: 4 `hunt-wpos`, 9 `hunt-rayq`).

### 1.2 The rungs

All nine are built **on the standing rung's bytes**,
`gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog`, and the compute and
ReSTIR-GI halves are `cmp`-asserted byte-verbatim — **0 of 81 differ**. Only
the reference raygens are patched.

| rung | site | field painted | content sha256 (93 modules) | raygen half sha |
|---|---|---|---|---|
| **`hunt-rayq-p`** — **the lead rung** | primary | `InstanceId` | `951c1d09627046ac` | `597d6ad55092513f` |
| `hunt-rayq-pcust` | primary | `InstanceCustomIndex` | `8fa92dd27c6b7cf0` | `a7f0b5098920eb56` |
| `hunt-rayq-pprim` **(new, §12.6)** | primary | `PrimitiveIndex` | `a8e4693f85569180` | `bd1ec97a5687de49` |
| `hunt-rayq-pclosest` **(new, §12.6)** | primary | `InstanceId`, **flags 513** | `8adb716c30617d0a` | `4d2dd5662c950021` |
| `hunt-rayq-pctl` | primary | `InstanceId`, **gain 0** | `9e7ac409ff8db3f7` | `9397398ecfd43261` |
| `hunt-rayq` | bounce | `InstanceId` | `aca372a010fb9416` | `6070af6010dccede` |
| `hunt-rayq-cust` | bounce | `InstanceCustomIndex` | `b07893744c0796df` | `9e27b0365c6bde98` |
| `hunt-rayq-prim` | bounce | `PrimitiveIndex` | `619aad1609df5823` | `ca47fc5ae1ce685a` |
| `hunt-rayq-psbt` **(new, §13.6)** | primary | `instanceSBTRecordOffset` | `3fb96c406ca2d796` | `092522d97995cf72` |
| `hunt-rayq-pgeom` **(new, §13.6)** | primary | `GeometryIndex` | `5b141d145cdd9554` | `89955de3420fe52f` |
| `hunt-rayq-pxf` **(new, §13.6)** | primary | `ObjectToWorld[3]`, raw bits | `0754da611bcd3915` | `511d4ea6850824cc` |
| `hunt-rayq-ctl` | bounce | `InstanceId`, **gain 0** | `4b73d25732d6efb2` | `2beb4e70ea701db1` |
| *(base, for reference)* | — | — | `4dc824ca77d95feb` | `1f09268e3d294697` |

The four bounce hashes are **bit-identical to the pre-revision build**, which
is the cheapest possible proof that adding the primary site changed nothing
about the family that was already accepted. The same is now true one level up:
adding `-pprim` and `-pclosest` left **all seven** earlier hashes bit-identical,
including the three primary ones — so the commit-mode plumbing (§2.3) changed
nothing about the rungs that were already shot. **Still true one level up
again:** adding `-psbt`, `-pgeom` and `-pxf` (§13.6) left **all nine** earlier
hashes bit-identical, content and raygen half.

Each is 93 modules: 77 compute + 4 restirgi (verbatim) + 12
`rgs_reference_main`, of which **10 are patched and 2 ship verbatim**
(`40c6faab52a13874`, `ab7f1822eeb0331b` — their only image writes are
constant zero, the same 10/12 split `55`/`56` used).

Each family has **its own** gain-0 control, and that is not redundancy: the
two splices emit different instructions, so the 10 `-pctl` modules differ from
the 10 `-ctl` modules on every file (gate 5). A control is **not** a copy of
the base either. Round-trip neutrality is proven first (§4.1), then `--gain 0`
keeps every instruction *and the executing query* and collapses only the
multipliers to exactly 1.0 — so each control is byte-distinct from the base
(10/10 differ) and must be **visually identical** to it. That makes it a real
control instead of a tautology.

---

## 2. The splice, instruction for instruction

Both families share one splice site, one `%accel`, one set of ray flags, one
latch and one paint. They differ in exactly one thing: **which ray the query
re-runs.** The bounce body is below; the primary body is §2.1.

Read off the **shipped** file
`~/.local/lib/callisto/skin.set/hunt-rayq/1271d3815051da17.rgs_reference_main.spv`
(`spirv-dis`, friendly names). This is the whole emitted body:

```
; --- the module's OWN trace, untouched, for context ---
%2208 = OpLoad %v2uint %2207                       ; RTASHeap[i], set 1 binding 0
%2209 = OpConvertUToAccelerationStructureKHR %1014 %2208
%2210 = OpCompositeConstruct %v3float %1726 %1728 %1730   ; origin
%2211 = OpCompositeConstruct %v3float %2179 %2180 %2181   ; direction
        OpTraceRayKHR %2209 %2203 %uint_255 %uint_1 %uint_1 %uint_0
                      %2210 %float_9_99999997en07 %2211 %float_10000 %21

; --- everything below is ours ---
%2212 = OpInBoundsAccessChain %_ptr_RayPayloadKHR_float %21 %uint_3
%2213 = OpLoad %float %2212                        ; t  (10000.0 == miss)
%2214 = OpFMul %float %2213 %float_0_999000013     ; tmin = 0.999 t
%2215 = OpFMul %float %2213 %float_1_00100005
%2216 = OpFAdd %float %2215 %float_9_99999975en05  ; tmax = 1.001 t + 1e-4
        OpRayQueryInitializeKHR %1250 %2209 %uint_517 %uint_255
                                %2210 %2214 %2211 %2216
%2217 = OpRayQueryProceedKHR %bool %1250
%2218 = OpRayQueryGetIntersectionTypeKHR %uint %1250 %uint_1   ; committed
%2219 = OpINotEqual %bool %2218 %uint_0
%2220 = OpRayQueryGetIntersectionInstanceIdKHR %uint %1250 %uint_1
; branchless first-write-wins latch on two Private uints:
%2221 = OpLoad %uint %26                           ; state: 0 none 1 miss 2 hit
%2222 = OpIEqual %bool %2221 %uint_0
%2223 = OpSelect %uint %2219 %uint_2 %uint_1
%2224 = OpSelect %uint %2222 %2223 %2221
        OpStore %26 %2224
%2225 = OpLoad %uint %27                           ; the latched raw field
%2226 = OpSelect %uint %2219 %2220 %uint_0
%2227 = OpSelect %uint %2222 %2226 %2225
        OpStore %27 %2227
```

and at each of the 25 radiance writes, before the `OpImageWrite`:

```
%12806 = OpLoad %uint %26
%12807 = OpLoad %uint %27
%12808 = OpIMul %uint %12807 %uint_2654435761      ; Knuth golden ratio
%12809 = OpShiftRightLogical %uint %12808 %uint_15
%12810 = OpBitwiseXor %uint %12808 %12809
%12811 = OpBitwiseAnd %uint %12810 %uint_7         ; 8 buckets
%12812 = OpIEqual %bool %12806 %uint_2             ; hit?
%12813 = OpIEqual %bool %12806 %uint_1             ; miss?
... 8 x (OpIEqual + OpLogicalAnd) ...
%12830..%12848 = 9-deep OpSelect chain rooted at %float_1  (per component)
%12849 = OpFMul %float %12701 %12848               ; multiplied into the write
```

Header additions (inserted after `apply_edits`, separately, because
`apply_edits` cannot place capabilities): `OpCapability RayQueryKHR` (4472),
`OpCapability RayTraversalPrimitiveCullingKHR`, `OpExtension
"SPV_KHR_ray_query"`, `%1232 = OpTypeRayQueryKHR`, one Function-storage
`OpVariable` as the **leading** instruction of the entry block, and two
Private `uint`s (`%26`, `%27`) zero-stored at function entry and listed in the
`OpEntryPoint` interface (SPIR-V 1.4 requires **every** storage class there).

### 2.1 The primary variant, instruction for instruction

Same splice site, same `%accel`, same flags, same latch, same paint — **only
the ray changes**. Read off the shipped
`skin.set/hunt-rayq-p/1271d3815051da17.rgs_reference_main.spv`:

```
        OpTraceRayKHR %2210 %2204 %uint_255 %uint_1 %uint_1 %uint_0
                      %2211 %float_9_99999997en07 %2212 %float_10000 %21
; --- ours ---
%2213 = OpFMul %float %1480 %1481                  ; t = |P| = dot(P,P)*rsqrt(dot(P,P))
%2214 = OpCompositeConstruct %v3float %1482 %1483 %1484   ; the module's own view ray
%2215 = OpFMul %float %2213 %float_0_999000013     ; tmin
%2216 = OpFMul %float %2213 %float_1_00100005
%2217 = OpFAdd %float %2216 %float_9_99999975en05  ; tmax
        OpRayQueryInitializeKHR %1251 %2210 %uint_517 %uint_255
                                %1237 %2215 %2214 %2217
```

with, upstream in the module and **untouched**:

```
%1475..%1477 = OpFDiv %float ... %1474      ; P = perspective divide of the
                                            ;     depth reconstruction
%1478 = OpCompositeConstruct %v3float %1475 %1476 %1477
%1479 = OpCompositeConstruct %v3float %1475 %1476 %1477
%1480 = OpDot %float %1478 %1479            ; dot(P,P)
%1481 = OpExtInst %float %1 InverseSqrt %1480
%1482 = OpFMul %float %1481 %1475           ; V = normalize(P), the view ray
%1483 = OpFMul %float %1481 %1476
%1484 = OpFMul %float %1481 %1477
%1237 = OpConstantComposite %v3float %float_n0 %float_n0 %float_n0
```

Four things about this are worth stating plainly.

**The origin is the zero triple**, because the camera *is* the origin of this
space. `94` §3.3 established that P is camera-relative precisely by observing
that the module normalises it and uses the result as the view ray — which is
only valid with the camera at zero. So the module has no camera-position id to
borrow, and the honest origin is the constant zero vector. (`spirv-dis`
renders it `%float_n0` because the module already carried −0.0 and the patcher
reuses the module's own float-zero constant; −0.0 and +0.0 are the same point.)

**The direction is the module's own ids**, never a re-derived value: the
splice constructs a `v3float` from `%1482 %1483 %1484` and nothing else. The
verifier asserts exactly that (§4.1, check 4′).

**`t` costs one instruction and no new constant**: `|P| = dot(P,P) ·
rsqrt(dot(P,P))`, both operands already in the module. Bracketing
`[0.999·|P|, 1.001·|P| + 1e-4]` means the query can only commit a surface at
the distance the *depth buffer* says the primary hit is at.

**The no-hit multiplier is 1.0 here, not black** (§2.5): the primary ray
legitimately misses on every sky pixel, and an unpainted sky is this family's
built-in control.

### 2.2 How the primary ray is found — structurally, and it is unique

`patch_rayq._find_primary_ray` matches the shape, not a position:

```
%P{0,1,2} = OpFDiv ... %w              <- perspective divide, ONE shared %w
%pa = OpCompositeConstruct %v3float %P0 %P1 %P2
%pb = OpCompositeConstruct %v3float %P0 %P1 %P2
%d  = OpDot %float %pa %pb
%r  = OpExtInst %float %1 InverseSqrt %d
%V{0,1,2} = OpFMul %float (%r, %Pk)    <- either operand order
```

The perspective-divide requirement is what separates this from the dozen other
normalizes in a 14 000-line module. Census over the standing base: **exactly
one match in all 12 permutations**, including the two pass-throughs, so the
detector never has to choose (GOTCHAS 10: no positional guess). The patcher
also refuses if the site is not *above* the splice point, so the ids provably
dominate.

The query still sits at the module's own trace, inside the path loop, so it
runs once per bounce — but now with the **same operands every time**, so the
first-write-wins latch is deterministic per pixel rather than stochastic. The
repeated executions are wasted work and nothing else; a probe can afford them,
and avoiding them would cost a branch (§2.3).

### 2.3 Why ray flags 517, chosen consciously — and why 513 costs nothing

`517 = 0x01 Opaque | 0x04 TerminateOnFirstHit | 0x200 SkipAABBs`.

`Opaque` forces every candidate to be treated as opaque, so **no candidate can
ever require shader processing** — which means one `OpRayQueryProceedKHR` is
provably enough and the splice adds **zero control flow**. That is not a
convenience; it is what makes the splice safe. The raygen has a structured CFG
with three nested loops and ~14 200 lines, and a `while(Proceed)` loop spliced
into the middle of it is a merge/continue-block problem waiting to happen. As
emitted, the splice is a straight-line run of 20 instructions with no branch,
so it cannot perturb the module's control flow at all.

The cost is stated honestly: **alpha-tested geometry (hair cards, foliage,
chain-link) will commit its bounding triangle rather than being pierced.** The
module's own trace uses flags `%2203` (runtime) with any-hit shaders bound, so
on those surfaces the query and the trace can disagree — the query commits
*nearer*. This is the right trade for a probe whose question is "is there an
identity here at all"; it is the wrong trade for a shipped feature, and a
non-probe version would use `NoOpaque` and a real Proceed loop with a
`RayQueryGetIntersectionCandidateAABBOpaque` / alpha test, i.e. a much larger
splice. `SkipAABBs` (with its required capability) says we only care about
triangles; this renderer's TLAS is triangles.

**`TerminateOnFirstHit` is not part of that argument, and dropping it is free.**
Re-read the reasoning above: what makes one `Proceed` sufficient is that no
*candidate* can require shader intervention — `Opaque` removes the alpha-test
case, `SkipAABBs` removes the procedural case. `TerminateOnFirstHit` only
decides **which** intersection ends up committed once traversal runs: any hit
in range, or the nearest one. Take the bit away and traversal still completes
inside the first `Proceed`; it just commits the closest hit instead of an
arbitrary one.

That is the whole of **`hunt-rayq-pclosest`**: ray flags `513 = Opaque |
SkipAABBs`, one constant different, same body, same latch, same paint, still
one `Proceed`, still zero added control flow (gate 4 counts it on the shipped
bytes, per rung). It exists because §12.5 cause (b) — the query committing a
*different* coplanar candidate each frame — is only reachable while
`TerminateOnFirstHit` is set. `patch_rayq.py --commit closest` selects it, and
gate 3 checks the emitted constant against a table stated independently of the
build script's own request.

Note the two flag words are one bit apart, so the verifier is made to reject
each rung read as the other (gate 7): a build that silently reverted to 517
would otherwise pass every other check.

### 2.4 Why the `t` bracket

The brief asked for tmin/tmax bracketing payload word 3. `t` is the trace's
own hit distance in the payload (`94` §2.2; `10000.0` is the miss sentinel).
Bracketing `[0.999 t, 1.001 t + 1e-4]` means the query can only commit a
surface at the distance the trace already found — so a *hit* is the same
surface, not merely *a* surface along the ray. On a miss (`t == 10000.0`) the
bracket is `[9990, 10010.0001]`, an empty shell far past anything, so the
query correctly commits nothing and the pixel latches state 1.

For the primary family the same bracket is built around `|P|` instead
(§2.1), so a hit means "the BVH agrees with the depth buffer about this
pixel's surface, to a tenth of a percent". Where they disagree — silhouette
edges, alpha-tested hair — the query correctly commits nothing, and §5
pre-registers that thin rim as *expected*, not as a failure.

### 2.5 Why a latch, and what the void condition looks like

The cloned trace is **inside the path loop**: it executes once per bounce per
sample. The latch is branchless and first-write-wins, so the painted identity
is the **first** query that ran on that pixel — the first bounce.

Three visible states, and the third is the void-condition control the brief
asked for:

| latched state | bounce multiplier | primary multiplier | what it means |
|---|---|---|---|
| 2 — committed a hit | palette hue, gain 3.0/0.2 | same | the query ran and hit |
| 1 — ran, committed nothing | **0.0 (black)** | **1.0 (unchanged)** | the query ran and the bracket was empty |
| 0 — never ran | **1.0 (unchanged)** | **1.0 (unchanged)** | the splice never executed on this pixel |

For the **bounce** family "black" and "looks like the base rung" are
*different* readings with *different* causes, and the frame can tell them
apart. That distinction is the whole reason the latch has three states instead
of a bool.

For the **primary** family the no-hit arm is deliberately identity instead,
and it costs nothing: the primary ray legitimately misses on every sky pixel,
so painting misses black would turn a *correct* frame into a black sky and
throw away the family's best control. An **unpainted sky is the control**
(`56`'s sky argument): if the sky comes back coloured, the query is committing
garbage against a far-plane bracket and the frame is void. The price is that
states 0 and 1 are indistinguishable on these rungs — accepted, because the
sky answers the same question more directly.

---

## 3. What this is NOT

### 3.1 The bounce family is not the primary surface — which is why it is not the lead
The splice site is the path loop's radiance trace, i.e. bounces ≥ 1 — the same
site `94` §2 found is *not* the primary hit. The first version of this
document treated the brief's "clone the origin/direction verbatim" gate and
its "welded to visible geometry" expectation as being in conflict, and
followed the gate.

**That conflict was not real, and the review was right to reject it.** The
gate's purpose is "provably the same segment the module resolved", and for the
primary hit an equally strong gate exists: the module *already* reconstructs
the primary ray and normalises it, so cloning **its own** `P`, its own view
ray and its own `|P|` is exactly as verifiable as cloning the bounce trace's
operands — and §2.2 shows it is uniquely locatable, which the trace operands
are not more so. The primary family (§2.1) is therefore the lead, and its
verifier checks are *stricter*, not looser (§4.1).

What survives of the original objection is the reason the bounce family is
kept rather than deleted: at 1 spp through a denoiser it can only ever produce
a per-object *tint*, and a screenshot cannot cleanly settle "stable tint vs
boil". So it is a second read, for a question the primary rung cannot answer —
whether the light *inside* a reflection carries an identity.

### 3.2 It is not a G-buffer yet
Nothing is stored anywhere a later pass can read. This writes a hue into the
radiance the raygen was already writing. A real second G-buffer needs a
storage image and a pass that consumes it; that is `88`'s cavity cone, and it
is not started.

### 3.3 "It links" is not "it hits"
The self-test proves the driver compiles, links and pipelines the module. It
does not prove `%accel` holds a TLAS with instances at the moment the splice
runs, and it cannot: the self-test binds a null descriptor. Only a frame
answers that.

### 3.4 The query's hit is not guaranteed to be the raster's hit — at mover silhouettes
Added 2026-09-02 after §15.4, where it showed up on screen and no
pre-registration had listed it. The primary query is aimed down the module's
own reconstructed camera ray and bracketed at ±0.1 % of `|P|`, where `P` comes
from the **depth buffer**. Where the raster G-buffer and the TLAS disagree
about where a thing is — a mover that moved between the depth pass and the TLAS
build, upsampler jitter, a disocclusion edge — the bracket can land on a
**different object** from the one that shaded the pixel. It is a thin band at
moving silhouettes, it is invisible whenever the committed field is stable
(the wrong object still paints a steady hue), and it is loud whenever the field
is per-frame. Nothing is built for it; it is a caveat on every reading this
family produces, not a defect in the splice.

---

## 4. The gates — every number

`./dev/build_rayq.sh` is build-failing on all ten. Run today, all green:

| # | gate | number |
|---|---|---|
| 0 | standing-base provenance | base `MANIFEST.txt` present; 77 compute / 4 restirgi / 12 reference — exact counts, refuses otherwise |
| 1 | round-trip neutrality | `spirv-dis → spirv-as` reproduces the base **byte-identically, 10 of 10** — so any later diff is ours |
| 2 | patch + assemble | **9 rungs × 93 modules, 10 patched each**, `spirv-val --target-env vulkan1.4` clean on every file; compute+restirgi `cmp`-verbatim (**0 of 81 differ**); patched files must differ; and **10/10 primary modules differ from the bounce build of the same field** |
| 3 | paintable coverage, from the reports | **10 modules, 25 painted writes, 22 benign skips** on every one of the 9 rungs, with the ray flags and commit mode checked against a table stated **inside the gate** (517/`first` for eight rungs, 513/`closest` for `-pclosest`) rather than against whatever the build script asked for; the site is consistent across a rung's 10 modules, and a `site=primary` module must carry a resolved primary reconstruction while a `site=bounce` module must not |
| 4 | instruction census on the **shipped bytes** | **10 × (1 query, 1 proceed, 0 added `OpTraceRayKHR`)**, 2 pass-throughs clean, all 9 rungs — the `1 proceed` is what makes "zero added control flow" a measurement rather than an argument, and it holds for `-pclosest` too |
| 5 | `--gain 0` reproducibility, **per family** | primary: **10/10 byte-identical to `-pctl`**; bounce: **10/10 byte-identical to `-ctl`**; each control **10/10 differs from the base**; and the two controls **differ from each other 10/10** — so neither family's control can stand in for the other's |
| 6 | verifier on shipped `.spv` | **10/10 permutations, 25 painted writes, ALL PASS**, on each of the nine rungs, each read at its own site **and its own commit mode** |
| 6b | hash-chain audit on shipped `.spv` | `dev/audit_rayq_hash.py`: **CLEAN, 10/10 modules on all 9 rungs** — every leaf of the paint's operand closure is a constant, a ray-query getter, or one of the two Private latch variables (§12.6c) |
| 7 | verifier non-vacuity | rejects **12** decoys: the unpatched base; `-ctl` read as a probe; a probe read as `-ctl`; the `id` rung read as `prim`; **the primary rung read as a bounce rung**; **the bounce rung read as a primary rung**; `--decoy ray` (origin ≠ the trace's origin); **`--decoy ray --site primary`** (direction is the bounce ray's, a real id but the wrong one); `--decoy flags` (flags 0, not 517); **the first-hit rung read as closest-hit** and **the closest-hit rung read as first-hit** (one bit apart); **`-pprim` read as an `InstanceId` rung** |
| 7b | hash-audit non-vacuity | rejects the unpatched base, and rejects a **`--decoy hash`** build that folds this frame's own radiance into the hash input — the exact failure mode §12.6c exists to rule out |

### 4.1 What the verifier actually asserts
`dev/verify_rayq.py` disassembles the **installed** file and re-derives, per
permutation, that:

1. `OpRayQueryInitializeKHR`'s AS operand `==` the `OpTraceRayKHR`'s AS
   operand — **the same SSA id**, i.e. the module's own `%accel`, not a
   look-alike;
2. **at `--site bounce`**: its origin operand `==` the trace's origin id, and
   its direction operand `==` the trace's direction id (what `--decoy ray`
   breaks);
   **at `--site primary`** the same two operands are checked *harder*: the
   verifier re-derives the primary reconstruction itself — a **second,
   independent implementation** of the detector, so that a verifier importing
   the patcher's own could not merely prove the patcher agreed with itself —
   requires exactly one such site, and asserts the direction is an
   `OpCompositeConstruct` of precisely the module's own `V` ids, that it is
   **not** the bounce ray's, that the origin is an `OpConstantComposite`
   `%v3float` whose three components are float `0.0`, and that it is **not**
   the bounce ray's origin;
3. cull mask `==` the trace's cull mask;
4. ray flags `== 517` (what `--decoy flags` breaks);
5. `tmin`/`tmax` are built by the exact FMul/FAdd chain — **at `--site
   bounce`** from payload word 3 of *that trace's* payload variable; **at
   `--site primary`** from `dot(P,P) · rsqrt(dot(P,P))` with both operands the
   module's own re-derived ids, and *not* an `OpLoad` (which would be a bounce
   build being read as a primary one);
6. exactly one Initialize and exactly one Proceed per patched module, and zero
   added trace instructions;
7. 12 traces present, 2 pass-throughs untouched;
8. the two Private latch variables exist and are zero-stored at entry;
9. the paint is a 9-deep `OpSelect` chain rooted at `1.0` at each of the 25
   writes;
10. the getter is the one the rung claims (`id` / `custom` / `prim`), and the
    palette matches the site's own no-hit arm (black for bounce, identity for
    primary).

Checks 2 and 5 are **mutually exclusive between the sites**, so verifying a
rung at the wrong `--site` is itself a decoy — which is why gate 7 runs both
crossings.

A byte diff is not coverage (`42`): none of these are file hashes.

---

## 5. Pre-registered interpretation — write this down BEFORE the screen

Shoot **`hunt-rayq-p` first**. It is the rung that answers the question this
unlock exists for, and it answers it in one frame. **Every** row below is a
legitimate outcome, including the ones that kill the idea.

### 5.1 `hunt-rayq-p` — the primary rung, the lead read

| what you see | reading | what to do next |
|---|---|---|
| **Flat per-object silhouettes** — the whole car one hue, the wall another, each object's colour constant across its own surface and stable as you strafe | **PASS. The unlock works.** `InstanceId` is a real per-instance handle reaching the shader | shoot `-pcust`; if it agrees, the engine's own authored id is usable and `88` has its key |
| The **sky stays unpainted** | **Required.** This is the family's built-in control (§2.5): a miss is identity, so an untouched sky means the bracket and the traversal are behaving | — |
| The **sky is coloured** | **VOID.** The query is committing something against a far-plane bracket; nothing else in the frame can be trusted | do not read the rest of the frame; investigate the bracket before anything else |
| A **thin dark / unpainted rim** at silhouette edges, and on hair | **EXPECTED, not a failure.** This is the depth-vs-BVH mismatch `85` §1 already measured; the query commits nothing where the reconstructed P falls off the triangle | ignore it; it is not evidence about `InstanceId` either way |
| **Everything unpainted** (the frame looks like the base rung) | The bracket is empty — the re-found primary is off the BVH by more than 0.1 % | **widen the bracket to 1 % and re-shoot before concluding anything.** Only if 1 % is also empty is this a real negative |
| Large flat regions painted, but **two adjacent distinct objects share one hue** | Either a genuine hash collision (8 buckets — expected occasionally) or the ids are coarse | re-shoot with more objects in frame; a collision moves, a coarse id does not |
| **One uniform hue** over every painted surface | `InstanceId` is constant or zero here | shoot `-pcust`. If it is also uniform, run the bounce `-prim` rung as the positive control (below) |
| Hue is per-object but **slides with the camera** | The identity is tracking something view-dependent, not geometry | compare against `-pctl`; if `-pctl` is clean, the paint is real and the id is the problem |
| **Black screen / game does not start** | The pipeline rejected the capability | `"ev":"rayq","action":"skipped"` in the jsonl names the reason; `CALLISTO_RAYQ_DISABLE=1` is the escape |
| **Looks exactly like the base rung, and the jsonl shows `rayq_reject`** | The overlay lost or the layer refused — **not** a shader result | grep `rayq_reject`, `"swap":"HIT"`, `trace_rays` **before** blaming the splice |
| `-pctl` differs from the base in any way | **The layer is not serving what it claims. Stop and debug the layer, not the shader** | — |

> **SHOT 2026-09-02 — read §12 before using this table again.** The table above is
> left exactly as it was pre-registered. It was **incomplete**: no row of it
> fired, because every row silently assumed the paint lands in a G-buffer, which
> §3.2 had already said it does not. §12 records what actually happened and why
> §5.1 could not have fired.

### 5.2 The bounce rungs — the second read

Only after the primary rungs have been read. These answer a different
question: whether the light *inside* a reflection carries an identity.

| what you see | reading | what to do next |
|---|---|---|
| **Stable per-object hue tints** — a tint, never a silhouette | The identity survives the first bounce | shoot `-cust` |
| Hues **swim/boil** frame to frame on a static scene | Expected in part — the first bounce is stochastic. A screenshot cannot settle "some boil" vs "all boil"; **do not** over-read it | if `hunt-rayq-p` passed, this rung adds little; move on |
| **Everything black** | The query runs and commits nothing — bracket empty, or the TLAS is empty/stale at this point in the frame | check `as_summary` (§8); consider widening the bracket |
| `-prim` shows **triangle confetti** | **PASS, not fail.** `PrimitiveIndex` *should* look like noise; it proves the query commits real geometry | use it as the positive control whenever an `InstanceId` rung reads uniform |
| `-ctl` differs from the base in any way | **Debug the layer, not the shader** | — |

### 5.3 Launch protocol and the settings contract

State the settings **before** the launch; never infer them from the capture
afterwards.

```
skinspec = hunt-rayq-p        FIRST. then -pcust, then -pctl.
                              only then -> hunt-rayq, -cust, -prim, -ctl
ser      = class              REQUIRED — the rung carries SER splices; ser=off is refused
shadowset= full-shadow        REQUIRED — the rung ships vanilla-based rgs_restirgi_*
ptq      = unchanged from the standing selection (the rung is baked against
           ptq_sha=55ed4e5c6884ab71; sync_settings.sh refuses a mismatch)
```

and the layer must be the one built here. Prove that first, without the game:

```
./dev/patch_rayq.sh --selftest      # expect 23 passed, 0 failed
```

Shot list: one frame, a street scene with several distinct objects at
different depths (a parked car, a wall, a market stall), **sky visible in the
frame** — the sky is the control, so a shot without it is worth less — plus a
character so the skin can be sanity-checked. Then the **same** framing on
`-pctl`. Read `~/callisto_swap.jsonl` after every launch:
`"ev":"rayq","action"`, `rayq_reject`, `"swap":"HIT"`, `trace_rays`,
`as_summary`.

---

## 6. The self-test — the half only a driver can answer

`./dev/patch_rayq.sh --selftest`, run today on **NVIDIA GeForce RTX 4070**:
**36 passed, 0 failed** (was 23 before the §8.2 journal fix; case D grew from
6 assertions to 19 and the probe grew a real build exercise).

It builds the layer from this repo, installs it under the renamed manifest
`VK_LAYER_CALLISTO_rayqtest` (the loader dedupes implicit layers by *name*, so
without the rename the test silently measures the *installed* binary — this
trap is inherited from `41`), builds three synthetic raygens sharing one fake
DXIL identity, and runs a ~200-line Vulkan probe that makes the same calls
vkd3d-proton makes.

| case | what it proves | result |
|---|---|---|
| **A** | the layer enables `VK_KHR_ray_query` on a device that requested only RT-pipeline/AS/DHO; the ray-query module is served (HIT); the RT pipeline links (`swapped:1`); **SER is still enabled alongside it** | 7/7 |
| **B** | `CALLISTO_RAYQ_DISABLE=1` ⇒ `"ev":"rayq","action":"skipped","reason":"env_disabled"`, `rayq_reject` with `"action":"next_overlay"`, and **the next overlay serves** (HIT, `swapped:1`) — the GOTCHAS invariant, measured | 6/6 |
| **B2** | same reject with **no** second overlay ⇒ `"swap":"none"`, probe still exits 0. Vanilla is the only answer left, and that is correct | 3/3 |
| **C** | a **real** patched raygen, `hunt-rayq-p`'s `1271d3815051da17.rgs_reference_main.spv`, **304 820 B**, accepted by `vkCreateShaderModule` | 1/1 |
| **D** | the AS journal (§8): hooks armed; `as_create type=top`; `as_addr` with `distinct_top_addr:1`; `as_summary` at device destroy; **a GENERIC create whose build is classified `top` anyway**; a triangles build classified `bottom`; **no `as_build` line says `untracked`**; an `as_tlas` row carrying the build's instance count; a never-built TLAS correctly reading 0/0; `max_builds_per_frame:2`; `untracked_builds:0`; the frame tick with `frame_src:"submit"` and a nonzero count; `table_overflow:0`; and `CALLISTO_ASJOURNAL_DISABLE=1` silences all of it | 19/19 |

`./dev/patch_ser.sh --selftest` still passes **11/11** unchanged — the
`xCreateDevice` rewrite is backward compatible, and so is the journal v2
rewrite (it adds two hooks, changes no existing path's behaviour).

---

## 7. Layer changes (`swap_layer.c`)

### 7.1 Enabling the extension
`ser_enable_setup()` is replaced by a decision/assembly split, because the old
shape could not compose: each path built its own `VkDeviceCreateInfo` copy, so
a second extension would have discarded the first.

```c
typedef struct { int want, already; const char *reason; } ExtWant;
static void ext_decide(inst, phys, ci, ext, dep, feat_stype, env_disabled, ExtWant *w);
```

`ext_decide` asks the driver rather than assuming
(`vkEnumerateDeviceExtensionProperties`), refuses if the dependency
(`VK_KHR_acceleration_structure` for ray query) is not in the app's own list,
and — importantly — **leaves the chain alone if the app already chained the
feature struct**, since a duplicate `sType` is invalid usage. Two
`_Static_assert`s pin the "first `VkBool32` after `sType`+`pNext`" assumption
that reads the app's struct; a header reorder stops the build instead of
silently misreading it. (The first version of those asserts was wrong —
`sizeof(VkStructureType)+sizeof(void*)` is 12, the real offset is 16 with
padding; they now use `sizeof(VkBaseInStructure)` and the compiler caught it.)

`xCreateDevice` then builds **one** `ci2` with up to two appended extension
names and two prepended feature structs, and falls back progressively: both →
SER only → vanilla, logging `"ev":"devext","action":"fallback"` at each step.
It never fails device creation. Result per device is recorded in `DevData` as
`d->ser` / `d->rayq` — per device, not global, because a dozen Proton helper
processes create devices through this layer.

**On the brief's worry** that vkd3d-proton might already chain a conflicting
features struct: it does not today, and if it ever does, `ext_decide` reports
`feature_already_chained` and stands down rather than corrupting the chain.

### 7.2 The reject guard
`load_swap()` now takes `allow_rayq` alongside `allow_ser`, and a candidate
declaring `OpCapability RayQueryKHR` (4472) on a device without the extension
is skipped **and the search continues to the next overlay**:

```
"ev":"rayq_reject","id":"…","size":…,"dir":"…","reason":"device_extension_not_enabled","action":"next_overlay"
```

This is the GOTCHAS rule, and it is enforced *inside* the search rather than
after it for the reason `44` gives: a rejected `hunt-rayq` module must fall
through to `swaps.skin/`→`swaps.ptq/` and produce the **base image**, never a
vanilla raygen sitting on top of a patched compute set. A second copy of the
guard remains in `xCreateShaderModule` as a last line of defence for the base
`swaps/` dir, and that one does log `"action":"vanilla"` — correctly, because
at that point there is nothing left to fall through to.

`CALLISTO_RAYQ_DISABLE=1` is the escape hatch, exactly parallel to
`CALLISTO_SER_DISABLE=1`.

---

## 8. Stage 2a — the AS journal (v2: it was wrong, here is the fix)

### 8.1 v1 was wrong twice, and the launches proved it

Both launches of §12 produced this, every time:

```
{"ev":"as_summary","why":"periodic","addr_calls":8192,"distinct_top_addr":0,"top_addr_overflow":0}
{"ev":"as_create","as":"0x…","type":"generic","size":33554432,"reuse":0,"n":1,"n_top":0}
{"ev":"as_build","dst":"0x…","type":"untracked","mode":0,"flags":6,"geoms":1,"prims":673}
```

**24 of 24 `as_create` lines said `generic`. 31 of 32 `as_build` lines said
`untracked`. `distinct_top_addr` was 0 on both launches.** The journal saw
every hook fire and learned nothing. Two independent bugs:

**Bug 1 — the type came from the wrong call.** v1 read
`VkAccelerationStructureCreateInfoKHR::type`. vkd3d-proton creates *every*
acceleration structure as `VK_ACCELERATION_STRUCTURE_TYPE_GENERIC_KHR`,
because D3D12 does not commit to top/bottom at creation either. The type is
only knowable at **build** time from
`VkAccelerationStructureBuildGeometryInfoKHR::type` — and the spec forbids
`GENERIC` in that field (VUID‑…‑type‑03654), which is precisely why the build
is the only place the truth exists. A build whose geometry is
`VK_GEOMETRY_TYPE_INSTANCES_KHR` is a TLAS build whatever any field claims,
because nothing else consumes `VkAccelerationStructureInstanceKHR`.

**Bug 2 — the build line looked its type up in a table that had lost it.**
`as_build` printed the type it found for `dstAccelerationStructure` in the
handle table, and printed `untracked` on a miss. The table was
`MAX_AS = 128` entries while a streaming city creates thousands of BLASes, so
it saturated; `g_as_overflow` counted the loss, but that counter was only ever
printed by the `device_destroy` summary — and **not one `device_destroy`
summary exists in any launch's jsonl**, because the game never destroys its
device cleanly. A saturating table whose only alarm is on a line that never
prints is a silent failure by construction, which is the part worth
remembering.

The evidence that separates the two bugs is in the log: every `as_addr` line
resolved its handle (`"type":"generic"`, never `untracked`), and the
`untracked` builds start at `seq 5241`, immediately after the address log hit
its 64-line cap and well after the create log hit its 24-line cap — i.e. the
misses are on handles created later, not on a hook that failed to fire.

### 8.2 What v2 does instead

| hook | event | fields |
|---|---|---|
| `vkCreateAccelerationStructureKHR` | `as_create` | handle, declared `type`, size, `reuse`, running totals |
| `vkGetAccelerationStructureDeviceAddressKHR` | `as_addr` | handle, address, **effective** type, `moved`, query count, `distinct_top_addr` |
| `vkCmdBuildAccelerationStructuresKHR` | `as_build` | dst, its device address, **classified `type`**, `build_info_type`, `declared_at_create`, mode (`build`/`update`), flags, geoms, prims, `nth_build`, `in_frame`, `frame`, `new_tlas` |
| `vkQueuePresentKHR` (fallback `vkQueueSubmit`) | — | the frame tick |
| every 8192 address calls, every 600 frames, **and** `vkDestroyDevice` | `as_tlas` + `as_summary` | see below |

Five changes, each aimed at one of the failures above:

1. **`asj_classify()` is the single place that decides what an AS is.**
   Precedence: any `INSTANCES` geometry ⇒ top-level, whatever `::type` says;
   else an explicit top/bottom `::type`; else (GENERIC with non-instance
   geometry — the game's every BLAS) bottom-level.
2. **`as_build` takes its type from the build info, never from the table.**
   `type:"untracked"` is now unreachable by construction, and the summary
   states `"untracked_builds":0` as a standing assertion.
3. **`asj_note_build()` interns a missing destination** instead of shrugging,
   and so does `asj_note_addr()` — an address query on an AS created before
   the hook was armed is still a fact worth keeping.
4. **The table cannot silently lose a TLAS.** 2048 entries behind a 4096-slot
   open-addressed index (tombstones, rebuilt when they exceed ¾), round-robin
   eviction of unpinned entries, and **anything classified top-level is
   pinned and never evicted**. `evictions`, `index_rebuilds`,
   `table_overflow`, `tlas_handle_overflow` and `tlas_addr_overflow` are
   printed in **every** summary.
5. **The summary no longer waits for a teardown that never comes.** It fires
   every 8192 address calls, every 600 frames, and at `vkDestroyDevice`.

The address table is keyed on the **(build destination, device address)
pair**, as the review asked — so a handle whose address changes and an address
reused by a new handle are two different rows, not one confused one.

Per-TLAS, one `as_tlas` row each:

```
{"ev":"as_tlas","why":"device_destroy","as":"0x…","addr":"0x…","builds":2,"updates":0,
 "max_builds_per_frame":2,"builds_per_frame":{"2":1},"instances_last":3,"instances_max":3,
 "geoms":1,"build_flags":4,"addr_moved":0}
```

`builds_per_frame` is a live histogram — bucket *k* counts the frames in which
that TLAS was built *k* times, `8+` saturating — maintained incrementally, so
"is the TLAS rebuilt once per frame or many times" is answered without
post-processing. For a TLAS, `instances_last`/`instances_max` are the
`primitiveCount` of the instance geometry, i.e. **the instance count** — which
is the number §12.5 cause (a) needs.

**The frame tick.** `vkQueuePresentKHR` is the real frame boundary;
`vkQueueSubmit` is the fallback for a device with no swapchain (the self-test
probe). Every summary names which one produced its count as `frame_src`, so a
reader never has to guess what `frames` counts.

### 8.3 What the self-test now reports

`./dev/patch_rayq.sh --selftest` — **36 passed, 0 failed** (was 23). Case D
grew from 6 assertions to 19, and the probe grew a real build exercise that
reproduces the vkd3d-proton shape: it creates three acceleration structures
with `type = GENERIC` and builds them with instance geometry (twice, in one
frame) and triangle geometry, **recording the commands and never submitting
them** — the journal reads the CPU-side structs at record time, so an
abandoned command buffer is enough and the GPU never touches the uninitialised
scratch. Verbatim from `on.log`:

```
{"ev":"as_build","dst":"0x…","addr":"0x…","type":"top","build_info_type":"top",
 "declared_at_create":"generic","mode":"build","flags":4,"geoms":1,"prims":3,
 "nth_build":1,"in_frame":1,"frame":0,"new_tlas":1}
{"ev":"as_build","dst":"0x…","type":"bottom",…,"declared_at_create":"generic","prims":12,…}
{"ev":"as_tlas","why":"device_destroy","as":"0x…","builds":2,"updates":0,
 "max_builds_per_frame":2,"builds_per_frame":{"2":1},"instances_last":3,"instances_max":3,…}
{"ev":"as_summary","why":"device_destroy","frames":4,"frame_src":"submit",
 "tlas_handles":3,"tlas_addr_pairs":3,"creates":4,"creates_declared_top":1,"builds":5,
 "build_geoms":5,"tlas_builds":4,"tlas_updates":0,"blas_builds":1,"addr_calls":5,
 "tracked":4,"handles_with_moving_addr":0,"evictions":0,"index_rebuilds":0,
 "table_overflow":0,"tlas_handle_overflow":0,"tlas_addr_overflow":0,"untracked_builds":0}
```

The assertions that matter, all green: a GENERIC create is logged `generic`;
**its build is classified `top` anyway**; a triangles build is classified
`bottom`; **no `as_build` line says `untracked`**; the TLAS row carries the
build's instance count; a TLAS created but never built correctly reads `0/0`
(a right answer, not a miss, so it is asserted too); `max_builds_per_frame:2`;
`untracked_builds:0`; `frame_src:"submit"` with a nonzero frame count; and
`table_overflow:0`.

Handle recycling is still handled explicitly:
`vkDestroyAccelerationStructureKHR` is deliberately **not** hooked, so
`as_create` resets any entry whose handle value it collides with and counts it
as a `reuse` — a recycle is visible in the journal instead of silently read as
"the address moved".

Default on, cheap; `CALLISTO_ASJOURNAL_DISABLE=1` skips even the pointer
resolution, so none of the five hooks is exposed (case D asserts both
directions, and that the probe still exits 0).

**Still not measured in the game.** v2 has never seen the game's TLAS either —
the fix is proven against a TLAS this repo built. The first read of the next
launch is `as_tlas` / `as_summary`, and §12.6 says what each answer means.

---

## 9. Deployment

`./dev/build_rayq.sh --install` parked all **nine** rungs (93 modules each) in
`~/.local/lib/callisto/skin.set/`. **Nine** rows are in `SKIN_LEVELS` in
`init.lua` (minimal exact-match insertion after the `hunt-wpos-ctl` row, the
file re-read immediately before the edit; `init.lua:465` coerces an unknown
`skinspec` to `off` silently, which is why the rows matter). The other agent's
four `hunt-wpos` rows are untouched — asserted on the **live** file after
deploying, not on the repo copy. `sync_settings.sh` needs no change —
`skin.set/<name>` is generic — and each rung's `MANIFEST.txt` carries the
`src_ser`/`ser_sha`/`ptq_sha` provenance the launch-time `gi_refuse` checks
demand, plus a site line and, for `-pclosest`, a flags line saying it commits
the closest hit.

`make install` (2026-09-02 17:22) carried:

* `init.lua` (+ the four unchanged engine luas) → the game's CET mod dir —
  on the **live** file `grep -c 'id = "hunt-rayq'` returns **9** and
  `grep -c 'id = "hunt-wpos'` still returns **4**; the nine are
  `hunt-rayq-p`, `-pcust`, `-pprim`, `-pclosest`, `-pctl`, `hunt-rayq`,
  `-cust`, `-prim`, `-ctl`;
* `kernel.bin` and the five `kernels/*.bin` → red4ext plugin dir (unchanged
  content);
* `libVkLayer_callisto_spvswap.so` → `~/.local/lib/callisto/` — **rebuilt this
  session** for the §8.2 journal fix, `md5 2625d5c2c4fd227fecbe2ac102b89b53`
  (was `fa4ca62dd02343dfd8d3fabcbd500a89`). `cmp` clean against the repo build
  **and** against `release/vulkan/`, all three byte-identical, and `strings` on
  the **installed** `.so` shows `VK_KHR_ray_query`, `"ev":"rayq"`,
  `rayq_reject … next_overlay`, `as_create`, `asjournal`, and the v2 markers
  `as_tlas`, `builds_per_frame`, `frame_src`, `untracked_builds`,
  `periodic_frame`, `vkQueuePresentKHR`, `vkQueueSubmit`;
* `detail_engine.txt`: already present, left alone (player state);
* backup written to `…/Cyberpunk 2077/.callisto_backup/20260902-172233`
  (earlier deploys: `…/20260902-172201`, `…/20260902-144506`,
  `…/20260902-142542`).

`make check` (luac + `bash -n` over every shipped script) passes. Both
self-tests pass on the installed layer: `./dev/patch_rayq.sh --selftest`
**36 passed, 0 failed**; `./dev/patch_ser.sh --selftest` **11 passed, 0
failed**. **Nothing was committed.**

---

## 10. Stage 2b / 2c — design only, and one correction that changes both

### 10.1 The brief's premise was wrong, and the correction is good news
The brief stated that **0** modules use `OpConvertUToAccelerationStructureKHR`.
A whole-dump opcode census says **38 do** — and all 38 are raygens:

```
modules=3322  OpConvertUToAccelerationStructureKHR=38
              cap RayQueryKHR=0   SPV_KHR_ray_query=0
              cap PhysicalStorageBufferAddresses=3281
```

(The companion claim — 0 modules declaring `SPV_KHR_ray_query` — is exactly
right.) So the TLAS already arrives at the shader as a **64-bit device address
in a bindless SSBO**: `RTASHeap = OpTypeStruct %_runtimearr_v2uint` at **set 1
binding 0**, loaded and converted per trace. That is the route, and it means
raygen-side ray query needs no address hack at all — which is why the Stage 1
splice above simply reuses `%2209`.

### 10.2 …but it does not extend to compute, and now we know why
The obvious follow-up — read the same heap from a compute resolver — **does
not work**, and the reason is measured rather than guessed. In compute
modules, set 1 binding 0 is a *different* heap:

```
compute modules with a set-1/binding-0 variable: 8 of 675
  and it is:  %AtomicCounters = OpTypeStruct %_runtimearr_v2uint
raygens:      %RTASHeap       = OpTypeStruct %_runtimearr_v2uint   (set 1, binding 0)
```

Same shape, same slot, different contents: vkd3d-proton reuses the slot per
pipeline type. **No compute module in the dump can reach a TLAS.** A compute
ray query therefore needs the address delivered another way — which is
precisely what Stage 2b was for.

### 10.3 Stage 2b (buffer device address) — designed, NOT built, and here are the holes
Design: the layer allocates a host-visible buffer with
`SHADER_DEVICE_ADDRESS` usage + `DEVICE_ADDRESS` alloc flag, writes a magic
word, and at `xCreateShaderModule` rewrites a sentinel 64-bit `OpConstant`
pair (`0xCA1157000BDA0001`) with the real device address; a probe rung loads
the magic through a `PhysicalStorageBuffer` pointer and paints on match.

**Stopped at the design.** Four holes, stated precisely:

1. **No discriminating capability for a reject guard.** SER and ray query each
   have a capability the layer can refuse on (5383, 4472). **3281 of 3322**
   modules already declare `PhysicalStorageBufferAddresses`, so it
   discriminates nothing — a BDA rung served to a device where the fixup did
   not happen would read a garbage pointer and fault. This needs a distinct
   in-module marker (a reserved `OpString`, or the sentinel constant itself)
   before it is safe to install, and that marker has to be forgery-proof
   against the 3281.
2. **The sentinel constant can occur by accident.** Rewriting "the 64-bit
   constant equal to X" is a search over module bytes; a stray match in an
   unrelated module is a silent memory corruption. The fixup must be anchored
   structurally (the constant's SSA id, recorded at build time in the rung's
   manifest), not by value scan.
3. **Memory type and lifetime are unproven.** Host-visible + device-address on
   this driver, mapped for the process lifetime, visible to the GPU without an
   explicit barrier — plausible, untested. Nothing offline settles it.
4. **The dispatch half cannot be proven offline.** "One proven-dispatching
   compute resolver" is a claim about the frame, not the bytes, and the
   existing compute self-test infrastructure does not build a dispatching
   pipeline.

Holes 1–3 are closeable with a compute self-test in the shape of §6. Hole 4 is
closeable only by a launch. None of it should be built before `hunt-rayq-p` has
been read on screen — **verify the mechanism before building a matrix.**

### 10.4 Stage 2c — the compute-side ray query, sketched
Given 10.2, the splice is:

```
%addr = <64-bit TLAS device address, delivered by 2b or by a layer-added descriptor>
%as   = OpConvertUToAccelerationStructureKHR %accel_type %addr
%rq   = OpVariable %_ptr_Function_rq Function
        OpRayQueryInitializeKHR %rq %as <flags> <mask> <P + eps*d> <tmin> <d> <tmax>
```

with `P` the world position the 77 resolvers already reconstruct (`99`) — so
the two unlocks compose: `99` supplies the origin, `98` supplies the traversal.

**Which TLAS**: the journal (§8) answers this empirically. If
`distinct_top_addr` is 1 and `handles_with_moving_addr` is 0, a single
constant fixup per launch suffices and Stage 2b collapses to something almost
trivial. If the address moves per frame, the shader must read it through an
indirection — a pointer to a layer-owned buffer the layer refreshes — which is
the full 2b design. **Read the journal before designing further.**

**Cost model, 720p, tile-classified.** The compute resolvers dispatch at full
resolution; class-1 (skin) pixels are a small fraction of a 1280×720 frame —
call it 3–8 % in a face close-up, well under 1 % in a street scene. A
`TerminateOnFirstHit` opaque query over a short cone ray is roughly the cost of
a shadow ray. At 8 % of 921 600 pixels that is ~74 k rays per cone tap; the
`88` cavity cone wants 4–8 taps, so ~300–600 k rays per frame — comparable to
one extra shadow pass, and cheap next to the path tracer's own budget. The
number that actually decides it is ray *coherence*, not ray count, and that is
not predictable offline.

**First consumer**: `88`'s cavity cone in gameplay. It currently cannot ask
"is there geometry within 10 cm of this skin pixel"; a compute ray query
answers exactly that, and it is the one question the G-buffer provably cannot.

---

## 11. What is NOT done

* ~~**No launch.**~~ **SUPERSEDED 2026-09-02 — see §12.** `hunt-rayq-p` and
  `hunt-rayq-pctl` have been shot. §5 stays as pre-registered; §12 records what
  fired. The bounce family (`hunt-rayq`, `-cust`, `-prim`, `-ctl`) is **still
  unshot**, so the original caveat still stands for it: nothing here is
  evidence that the primary family reads better than the bounce family — that
  is an argument from how the two are constructed, not a measurement.
* **No commit.** `swap_layer.c`, `init.lua`, the four new `dev/` files and this
  doc are working-tree changes.
* **No camera-position offset.** The primary origin is the zero triple because
  the camera is at the origin of P's space (`94` §3.3). That is a *contract
  about a space* inferred from two consumers, not proven; if it is wrong, the
  primary rungs will read as "everything unpainted" and §5.1 says to widen the
  bracket before concluding anything.
* **No 1 % bracket variant built.** §5.1 asks for one if 0.1 % comes back
  empty; it is a one-line rebuild, not a design change. §12 says the bracket
  is **not** empty, so this is no longer on the critical path — but §12.6b
  raises the opposite question, whether ±0.1 % is too *wide*.
* **Stage 2b is design only** (§10.3), with four named holes.
* **Stage 2c is design only** (§10.4), and blocked on the journal's first real
  read-out.
* **Alpha-tested geometry is knowingly mis-committed** by flags 517 (§2.3).
  Fine for a probe, wrong for a feature.
* **The AS journal has never seen the game's TLAS.** Case D proves the hooks
  fire on a TLAS this repo created, nothing more — and §8.1 is the record of
  what happens when that is mistaken for a measurement: v1 shipped, ran twice
  in the game, and reported `distinct_top_addr:0` both times.
* **No `mask=39` rung** (§12.6a). One constant; deliberately withheld until
  `-pclosest` says whether the candidate set is the problem.
* **`vkCmdBuildAccelerationStructuresIndirectKHR` is not hooked.** If this
  game ever builds indirectly, those builds are invisible to the journal and
  the TLAS counts would be low without saying so.

---

## 12. Shot 2026-09-02 — the paint reaches the screen, and §5.1 was the wrong table

### 12.1 What was launched

Two launches, from `~/callisto_launches.log`:

```
2026-09-02T16:24:09-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-rayq-p    skin_sha=951c1d09627046ac tier=on cache=cleared \
  payload=2828f963dccefd43
2026-09-02T16:29:25-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-rayq-pctl skin_sha=9e7ac409ff8db3f7 tier=on cache=cleared \
  payload=58876b4699f41581
```

Both match §5.3's contract exactly: `ser=class`, `shadowset=full-shadow`,
`ptq` unchanged, `ptq_sha=55ed4e5c6884ab71`, cache cleared.

Serve, per launch, from `~/callisto_swap.jsonl` — **identical on both rungs**:

```
90 dxil HITs   15 rgs_reference_main HITs   4 rgs_restirgi HITs
0 rayq_reject  0 ser_reject
3x {"ev":"rayq","action":"enabled","reason":"already_enabled_feature_on","ext":"VK_KHR_ray_query"}
manifest: hunt-rayq-p ... ref=12(10 rayq primary + 2 pass-through)
          ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71
```

Frames and the full numeric read-out are parked in `a-b-testing/rayq-p/`
(`RESULT.md`, three PNGs, three side-by-side crops).

### 12.2 The read-out

> "Every shadow or shaded area flickers its shadow between different colours
> of the rainbow. Reflective surfaces like glass and chrome wheels as well.
> Sky is normal. The control shades normally."

Corroborated numerically in `a-b-testing/rayq-p/RESULT.md`. The two numbers
that carry it, after normalising the two frames' lit pixels to each other:

* **Sunlit stone**, `(R-G)/Y` = **+0.271** under `-p` vs **+0.272** under
  `-pctl`. One part in 270. The lit half of the frame is untouched.
* **Shadow pixels**, `(R-G)/Y` moves **+0.09 to +0.11** under `-p` in every
  registered dark region, and the spatial spread of the low-passed hue over
  shadow pixels is **0.317 / 0.203** on the two painted frames vs **0.129** on
  the control, while the `(G-B)` spread is identical on all three
  (0.380 / 0.392 / 0.393 — that channel is the scene's own sky/sun split).

### 12.3 Which row fired — and the honest answer is "none of §5.1's"

| §5.1 row | fired? |
|---|---|
| **Sky stays unpainted** | **YES — as required.** The family's built-in control held; the frame is **not** void |
| **`-pctl` differs from the base** | **NO.** The control shades normally — the layer is serving what it claims |
| Flat per-object silhouettes (**PASS**) | **NO** |
| Everything unpainted | **NO** — the bracket is **not** empty; do **not** widen it |
| One uniform hue | **NO** — hues vary |
| Hue per-object but slides with the camera | **NO** — the hue is not per-object, and it changes with the camera *parked* |
| Sky coloured / black screen / `rayq_reject` | **NO** |

The row the outcome actually matches — *"hues swim/boil frame to frame on a
static scene"* — is **§5.2's**, pre-registered for the **bounce** family.
The review's read attributed it to §5.1; §5.1 has no such row. §5.1's table is
left unedited above, with a pointer to here.

### 12.4 Why §5.1 could not have fired, and it was knowable before the shot

§3.2 already said it in one sentence: *"This writes a hue into the radiance the
raygen was already writing."* The paint is an `OpFMul` on the reference
raygen's 25 radiance stores (§2), **not** a store to a G-buffer. Therefore:

1. A directly-sunlit pixel is dominated by terms this raygen does not produce.
   Scaling this raygen's contribution by a hue barely moves it — measured at
   one part in 270 on sunlit stone. Hence "lit direct surfaces look untinted".
2. A shadowed, ambient-lit, glass or chrome pixel is *mostly* this raygen's
   output. There the hue survives. Hence the cast, exactly where the read-out
   put it.
3. That output is accumulated and denoised, so a per-frame change in the
   committed hit arrives as a smoothly-varying drifting tint, not a hard
   flicker — which is what the crops show and what "swim/boil" described.

**Moving the query from the bounce to the primary surface fixed where the ray
is aimed. It did nothing about where the paint lands.** §5.1's PASS row
silently assumed a G-buffer write that §3.2 had already ruled out, so it was
unreachable on any frame. That is a pre-registration defect and it is recorded
as one; the correction is *not* to the aim, it is that "flat per-object
silhouettes in one frame" needs a **storage-image** destination (`88`'s
second G-buffer), which is still not built (§11).

### 12.5 What is now proven, and what is still open

**Proven.** An `OpRayQueryInitializeKHR` / `Proceed` /
`GetIntersectionInstanceIdKHR` spliced into a shipped raygen, aimed down the
module's own reconstructed primary ray with a ±0.1 % bracket and flags 517,
commits real hits on real geometry over most of the frame — no crash, no
reject, no validation break, clean sky, neutral control. **Unlock 1's
capability question is answered YES.**

**Open.** "The hue changes frame to frame" has three causes and this shoot
cannot separate them:

| # | cause | the rung that tests it |
|---|---|---|
| a | The TLAS is rebuilt every frame and `InstanceId` is a per-frame slot index | `-pcust` (`InstanceCustomIndex` is author-assigned, not slot-assigned) + the AS journal's TLAS rebuild count |
| b | The query commits a *different* hit each frame — `TerminateOnFirstHit` inside a ±0.1 % bracket may pick a different coplanar candidate (decal, proxy, LOD shell) | `-pprim`: `PrimitiveIndex` is stable iff the committed triangle is stable |
| c | Only the accumulator is showing several frames of different hues at once | any of the above reading *stable* kills this one |

The AS journal cannot currently answer (a): both launches logged
`as_summary … distinct_top_addr:0`, all 24 `as_create` lines
`type:"generic" n_top:0`, and 32 of 33 `as_build` lines `type:"untracked"`.
That is fixed in §8.

### 12.6 Three questions the review asked, answered from the bytes

#### (a) Which cull mask, and is it the right one

The primary query uses **255**, and it is not a choice — it is `%uint_255`,
the cull-mask operand of the trace the splice clones, cloned by SSA id like
every other operand (§4.1 check 1). A census of the base rung's own reference
raygens says what else was available:

```
144 OpTraceRayKHR sites across the 12 rgs_reference_main
cull masks: 255 x 24, 39 x 36, and 84 sites with a RUNTIME mask
```

In `1271d3815051da17` the three constant-mask shapes are distinguishable:

| site | mask | sbtOffset | miss | tmin | tmax | what it is |
|---|---|---|---|---|---|---|
| line 2338 | **255** | 1 | 0 | 1e-6 | `10000` | **the radiance trace — the one we clone** |
| line 3339 | 255 | 0 | 1 | 0.0 | 1.0 | the **visibility / shadow** ray (no CHS, normalised t) |
| lines 3750, 4337, 10377 | **39** | 1 | 0 | 1e-6 | *runtime* | further radiance traces, narrower mask |

So the question "should it be the visibility ray's 255 or the bounce ray's
mask" has a flat answer: **they are the same value, 255.** Both the trace we
clone and the shadow ray accept every instance category, and 255 is the right
mask for a "what is visible at this pixel" probe — a narrower mask would make
the query *miss* geometry that is genuinely on screen and paint holes that
would read as a negative result about `InstanceId` when they were an artefact
of the mask.

**But 255 is not free, and it points straight at (b).** `39 = 0x27` (bits
0, 1, 2, 5) is the mask three of this module's own radiance traces use, so
bits 3, 4, 6 and 7 mark instance categories the engine deliberately excludes
from *some* traces — shadow-only proxies, LOD shells, decal geometry are the
usual occupants. A 255 mask accepts all of them. Inside a ±0.1 % distance
bracket that is exactly the population of near-coplanar candidates that (b)
is about.

A `mask=39` variant is a one-constant rebuild and is **deliberately not
built**: it would break the "every operand is the module's own, by id" gate
for no gain until `-pclosest` has said whether coplanar candidates are the
problem at all. If they are, it is the next rung.

#### (b) TerminateOnFirstHit, coplanar candidates, and `hunt-rayq-pclosest`

Yes: with `TerminateOnFirstHit` set, the query commits **whichever** hit
traversal reaches first inside `[0.999·|P|, 1.001·|P| + 1e-4]`, and "first" is
a traversal-order artefact, not a geometric fact. Two triangles from different
instances sitting inside a ±0.1 % shell — a decal over a wall, a proxy shell
over a mesh, two LOD levels of the same object — are both legal answers, and
nothing forces the same one to win on consecutive frames. A TLAS rebuilt with
a different instance order (§12.5 cause (a)) would reorder traversal, and the
paint would change without the geometry changing. Combined with the 255 mask
above, that is a complete and plausible mechanism for the flicker.

**`hunt-rayq-pclosest` is built, not designed** (`8adb716c30617d0a`), because
the verifier can still prove zero added control-flow hazards — and the proof
turned out to be the one already in §2.3, correctly read: what makes one
`OpRayQueryProceedKHR` sufficient is `Opaque` + `SkipAABBs` removing every
candidate that could require shader intervention. `TerminateOnFirstHit` never
participated in that argument; it only picks which intersection is committed.
Flags `513 = Opaque | SkipAABBs`, one constant different, one `Proceed`, no
`OpLoopMerge`, no `OpSelectionMerge`, gate 4 counting it on the shipped bytes
for all 10 modules.

It is not a cure, only a discriminator: if a shadow-only proxy is *nearer*
than the visible surface, closest-hit commits the proxy every frame — which
is a **stable** wrong answer, and a stable wrong answer is exactly what
distinguishes (b) from (a).

#### (c) The hash chain: nothing per-frame feeds it, with the ids

`dev/audit_rayq_hash.py` (new, gate 6b) reads the **shipped** bytes with no
knowledge of how they were made: it finds the committed-field getter, walks
*forward* to the two Private latch variables, forward again through every hash
multiply, and then takes the transitive operand closure of each 9-deep
`OpSelect` chain backwards. Every leaf must be a constant, a ray-query getter,
or a load of one of those two latch variables.

**CLEAN, 10/10 modules, on all nine rungs.** For `hunt-rayq-p` /
`1271d3815051da17`:

```
latch vars      : %26 (state), %27 (id)          -- Private uint, both ours
field getter    : %2221 = OpRayQueryGetIntersectionInstanceIdKHR
type query      : %2219 = OpRayQueryGetIntersectionTypeKHR
hash multiply   : %12748 = OpIMul %12747 %uint_2654435761
select-chain end: %12798 = OpSelect
chain leaves    : %12746 = load %26   (ours)
                  %12747 = load %27   (ours)
                  %uint_0 %uint_1 %uint_2 %uint_3 %uint_4 %uint_5 %uint_6
                  %uint_7 %uint_15 %uint_2654435761
                  %float_1 %float_3 %float_2_4000001 %float_0_200000003
```

Fourteen leaves: two loads of our own latch, twelve constants. **No LCG state,
no frame index, no sample index, no push constant, no descriptor load reaches
the paint.** The value in `%27` is written only by the two-`OpSelect` latch
whose sole non-constant input is `%2221`, the committed `InstanceId`.

One thing the audit had to be taught, and it is worth recording because it
nearly produced a wrong answer: a first pass keyed on "the `OpIMul` by
`2654435761`" reported 2–3 such multiplies per module and looked like
contamination. It is not — there is one per radiance write site (2 in
`1271d…`, 3 in `21a92f…`, 25 across the 10 modules), and a census of the
**base** rung confirms `OpConstant %uint 2654435761` appears **0 times** in
the unpatched bytes. The constant is ours alone.

The audit is proven non-vacuous two ways (gate 7b): it rejects the unpatched
base, and it rejects a `patch_rayq.py --decoy hash` build that folds this
frame's own radiance into the hash input — the precise failure mode this
question exists to rule out. That decoy is never installed.

---

### 12.7 Pre-registered for the NEXT launch — write this down BEFORE the screen

Shoot in this order: **`hunt-rayq-pcust`, then `hunt-rayq-pprim`, then
`hunt-rayq-pclosest`.** Read `~/callisto_swap.jsonl` for `as_tlas` /
`as_summary` after **every** one of them — the journal now answers cause (a)
directly and it costs nothing to look.

#### Settings contract — stated now, not inferred from the captures afterwards

```
skinspec  = hunt-rayq-pcust      FIRST, then hunt-rayq-pprim, then hunt-rayq-pclosest
ser       = class                REQUIRED — the rung carries SER splices; ser=off is refused
shadowset = full-shadow          REQUIRED — the rung ships vanilla-based rgs_restirgi_*
ptq       = rcbm                 unchanged; the rungs are baked against ptq_sha=55ed4e5c6884ab71
ptrefl    = on, refract = fres   unchanged from the 16:24 and 16:29 launches
tier      = on,  cache = cleared
```

skin_sha, to be checked against `~/callisto_launches.log` after each launch:

| rung | skin_sha |
|---|---|
| `hunt-rayq-pcust` | `8fa92dd27c6b7cf0` |
| `hunt-rayq-pprim` | `a8e4693f85569180` |
| `hunt-rayq-pclosest` | `8adb716c30617d0a` |
| `hunt-rayq-pctl` (control, already shot) | `9e7ac409ff8db3f7` |

Same framing as §12: a street with several distinct objects at different
depths, **sky in frame** (it is the control), a character, and — new — **stand
still for several seconds and watch**, because the finding under test is
temporal and a screenshot cannot hold it. `./dev/patch_rayq.sh --selftest`
must read **36 passed, 0 failed** before any of this.

#### The table

| what you see | reading | what to do next |
|---|---|---|
| **`-pcust` gives stable flat per-object tints** (a car one hue, a wall another, holding still as you wait) | **The TLAS is rebuilt per frame and `InstanceId` is a per-frame slot index. `InstanceCustomIndex` is the identity to build on** — it is author-assigned, so it survives a rebuild | stop hunting identity; `88` has its key. Confirm with the journal: `as_tlas` should show `builds` ≈ `frames` with `tlas_updates` 0 |
| **`-pcust` still flickers, `-pprim` is stable confetti** | The query **commits consistently** — the same triangle every frame — and *both* instance fields are per-frame. The engine reuses instance slots and rewrites custom indices; **identity must come from somewhere other than the instance record** | do not shoot `-pclosest` for this; go to the geometry: `PrimitiveIndex` + `GeometryIndex` + the BLAS address, i.e. Stage 2b (§10.3) |
| **`-pprim` also flickers** | The query itself commits a **different hit** each frame. Cause (b) is live | shoot `-pclosest`, and read `as_summary`'s TLAS count **before anything else** |
| `-pclosest` is **stable** where `-p` flickered | Confirmed (b): `TerminateOnFirstHit` inside the ±0.1 % bracket was picking between coplanar candidates | narrow the bracket, or build the `mask=39` variant (§12.6a), and re-read `-pcust` on the stable base |
| `-pclosest` **flickers identically to `-p`** | (b) is dead. The candidate set is stable and the *fields* are changing — cause (a), or a TLAS being rebuilt with different contents | the journal decides it: `as_tlas.builds_per_frame` and `instances_max` |
| `as_summary` shows **more than one TLAS handle** with builds in the same frame | The raygen's `%accel` may not be the TLAS the query should be asking about at all | read `as_tlas` `addr` against the `RTASHeap` slot the module loads (§10.4); nothing else in the frame is interpretable until that matches |
| `as_summary` shows **`tlas_builds` ≈ `frames`, `tlas_updates` 0, `instances_max` in the thousands** | Full rebuild every frame — the strongest possible support for cause (a) | expect `-pcust` to be the rung that passes |
| `as_summary` shows **`untracked_builds` non-zero**, or `table_overflow` / `tlas_handle_overflow` non-zero | **The journal is lying again.** v2 asserts these are 0 by construction | fix the journal before reading any rung |
| **Sky painted** on any rung | **VOID**, exactly as §5.1 said | do not read the frame; investigate the bracket |
| **Everything unpainted** on `-pprim` while `-p` painted | Not a bracket problem (the bracket is shared). A `PrimitiveIndex` that hashes to one bucket everywhere | compare against `-pcust`; if that paints, the getter is the story |
| Any rung differs from `-pctl` in a way that is **not** a hue | **Debug the layer, not the shader** | grep `rayq_reject`, `"swap":"HIT"`, the manifest echo |

**What none of these rungs can produce, and it is now understood rather than
hoped for:** flat per-object silhouettes on a *sunlit* surface. §12.4 explains
why — the paint multiplies this raygen's radiance, and a sunlit pixel is not
made of this raygen's radiance. Every reading above is a reading of the
**shaded and reflective** part of the frame. Fixing that needs a storage-image
destination, not a better ray.

---

## 13. Shot 2026-09-02, 17:37–18:27 — the query is consistent, the instance record is not

Three more rungs on screen, the AS journal's **first real read-out**, and the
answer to §12.5: cause (b) is dead, cause (a) is confirmed, and **both**
instance fields are per-frame. The identity is not in the instance record. Three
new rungs are built, gated, parked and installed to ask somewhere else.

### 13.1 What was launched

Verbatim from `~/callisto_launches.log`:

```
2026-09-02T17:37:09-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-rayq-pcust    skin_sha=8fa92dd27c6b7cf0 tier=on cache=cleared
2026-09-02T17:38:05-05:00 ... skinspec=hunt-rayq-pcust    skin_sha=8fa92dd27c6b7cf0 cache=kept
2026-09-02T17:44:07-05:00 ... skinspec=hunt-rayq-pprim    skin_sha=a8e4693f85569180 cache=cleared
2026-09-02T18:27:01-05:00 ... skinspec=hunt-rayq-pclosest skin_sha=8adb716c30617d0a cache=cleared
```

All four match §12.7's contract exactly — `ser=class`, `shadowset=full-shadow`,
`ptq=rcbm`, `ptrefl=on`, `refract=fres`, `tier=on` — and every `skin_sha`
matches the value §12.7 pre-registered for that rung. 17:38 is 17:37 relaunched
with the cache kept; same rung, same payload.

### 13.2 The read-out, verbatim

> "hunt-rayq-pprim is constant and consistent. pcust and pclosest flicker. It
> kinda makes colours alot more into triangles of different colours on some
> surfaces but is consistent and doesnt flicker with movement."

**A frame exists for `-pprim` only.** `a-b-testing/rayq-p/C-pprim-174636.png`
(2560×1440, copied verbatim from the game's photomode directory) and
`crop-pprim-facade.png`. It shows stable per-triangle colour blocks over
building facades, the parked car and the market signage, a **clean blue sky**,
and a **sunlit road that is essentially untinted** — exactly the three things
§12.4 predicted and nothing more.

**There is no `-pclosest` screenshot.** The newest photo in that directory is
`photomode_02092026_182409.png` at 18:24:09; the launch was at 18:27:01. The
`-pclosest` result in this section is the live read-out and nothing else, and
is recorded as such.

### 13.3 Which §12.7 row fired

| §12.7 row | fired? |
|---|---|
| **"`-pcust` still flickers, `-pprim` is stable confetti"** | **YES. This is the read-out.** |
| "`-pcust` gives stable flat per-object tints" | NO — `InstanceCustomIndex` flickers too |
| "`-pprim` also flickers" | NO |
| "`-pclosest` is stable where `-p` flickered" | NO |
| "`-pclosest` flickers identically to `-p`" | YES (see below) |
| "more than one TLAS handle with builds in the same frame" | **YES, literally — and §13.4 answers it** |
| "`untracked_builds` / `table_overflow` / `tlas_handle_overflow` non-zero" | NO — all three are 0 |
| Sky painted / everything unpainted / a non-hue difference from `-pctl` | NO |

The reading the fired row pre-registered, unchanged:

**The query commits the same triangle every frame.** `PrimitiveIndex` is stable
under movement, so traversal is not picking a different candidate per frame —
**§12.5 cause (b) is dead.** `-pclosest` kills it a second time and
independently: flags 513 commits the *nearest* hit rather than any hit in the
bracket, and it flickers exactly like `-p`, which it could not do if the
flicker came from choosing between coplanar candidates.

**Therefore both instance fields are per-frame.** The same committed triangle
yields a different `InstanceId` *and* a different `InstanceCustomIndex` from one
frame to the next. That requires the TLAS to be rebuilt every frame with the
instances in a varying order **and** `instanceCustomIndex` rewritten along with
the order — the journal (§13.4) confirms the rebuild half directly.
**Identity must come from something other than the instance slot**, which is
what §13.6's three rungs are.

**§12.7 said "do not shoot `-pclosest` for this", and it was shot anyway.**
Recorded because the pre-registration is only worth anything if departures from
it are written down: the extra data point is *consistent* with the row that
fired, it kills (b) a second time by a different mechanism, and it cost one
launch. It changed no conclusion.

### 13.4 The AS journal's first real read-out

The v2 journal (§8.2) has now seen the game's TLAS. Verbatim, the two periodic
summaries 600 presents apart and their `as_tlas` rows, from
`~/callisto_swap.jsonl`:

```
{"seq":5677,"ev":"as_tlas","why":"periodic_frame","as":"0x7de6689d0730","addr":"0x60c00000","builds":17,"updates":0,"max_builds_per_frame":3,"builds_per_frame":{"1":10,"2":2,"3":1},"instances_last":0,"instances_max":0,"geoms":1,"build_flags":4,"addr_moved":0}
{"seq":5678,"ev":"as_tlas","why":"periodic_frame","as":"0x55559027c580","addr":"0x1b68e0000","builds":17,"updates":0,"max_builds_per_frame":3,"builds_per_frame":{"1":10,"2":2,"3":1},"instances_last":48618,"instances_max":62374,"geoms":1,"build_flags":4,"addr_moved":0}
{"seq":5679,"ev":"as_summary","why":"periodic_frame","frames":16800,"frame_src":"present","tlas_handles":2,"tlas_addr_pairs":2,"creates":12815,"creates_declared_top":0,"builds":12831,"build_geoms":22970,"tlas_builds":34,"tlas_updates":0,"blas_builds":12797,"addr_calls":12815,"tracked":2048,"handles_with_moving_addr":0,"evictions":11891,"index_rebuilds":8,"table_overflow":0,"tlas_handle_overflow":0,"tlas_addr_overflow":0,"untracked_builds":0}

{"seq":7713,"ev":"as_tlas","why":"periodic_frame","as":"0x7de6689d0730","addr":"0x60c00000","builds":316,"updates":0,"max_builds_per_frame":3,"builds_per_frame":{"1":305,"2":4,"3":1},"instances_last":0,"instances_max":0,"geoms":1,"build_flags":4,"addr_moved":0}
{"seq":7714,"ev":"as_tlas","why":"periodic_frame","as":"0x55559027c580","addr":"0x1b68e0000","builds":316,"updates":0,"max_builds_per_frame":3,"builds_per_frame":{"1":305,"2":4,"3":1},"instances_last":47406,"instances_max":62374,"geoms":1,"build_flags":4,"addr_moved":0}
{"seq":7715,"ev":"as_summary","why":"periodic_frame","frames":17400,"frame_src":"present","tlas_handles":2,"tlas_addr_pairs":2,"creates":15679,"creates_declared_top":0,"builds":129095,"build_geoms":262821,"tlas_builds":632,"tlas_updates":0,"blas_builds":128463,"addr_calls":15679,"tracked":2048,"handles_with_moving_addr":0,"evictions":16138,"index_rebuilds":10,"table_overflow":0,"tlas_handle_overflow":0,"tlas_addr_overflow":0,"untracked_builds":0}
```

**The journal is not lying this time**, and that is an assertion the summary
carries itself: `untracked_builds:0`, `table_overflow:0`,
`tlas_handle_overflow:0`, `tlas_addr_overflow:0`, `handles_with_moving_addr:0`.
§8.1's failure mode cannot be hiding here.

What it says, over the 600 presents between the two summaries:

| quantity | value | what it settles |
|---|---|---|
| `tlas_handles` / `tlas_addr_pairs` | **2 / 2** | two TLASes, two addresses, neither moved |
| `tlas_updates` | **0**, both summaries | **nothing is ever refit.** Every TLAS build is a full rebuild — `ALLOW_UPDATE` is not even set (see `build_flags`) |
| `build_flags` (per TLAS) | **4** = `PREFER_FAST_TRACE` only | no `ALLOW_UPDATE` (2), no `ALLOW_DATA_ACCESS` (0x800). §13.5 |
| populated TLAS `instances_last` / `_max` | **47 406 / 62 374** | ~50 k instances in frame; §12.7's "instances_max in the thousands" row |
| its `builds` | **17 → 316**, i.e. **299 builds / 600 presents** | see below |
| `builds_per_frame` | `{"1":305,"2":4,"3":1}` — 310 frames carried a build | a build lands in roughly half the presents, almost always singly |
| `tlas_builds` (both handles) | **34 → 632**, exactly 2 × 299 | the two TLASes are built in lockstep, in the same frames |
| `blas_builds` | **12 797 → 128 463** | **115 666 BLAS builds over 600 presents, ~193 per present** |

**One TLAS build per two presents — UNRESOLVED, and deliberately not asserted.**
`frame_src` is `"present"`, so `frames` counts `vkQueuePresentKHR`. The TLAS's
first build was at frame 16778 and it had 316 builds spread over 310 distinct
frames by frame 17400, i.e. one build in every second present. The obvious
reading is that **frame generation doubles the presents** and there is exactly
one TLAS rebuild per *rendered* frame — but this session did not state whether
frame generation was on before the launch, and the settings-sync rule is that a
setting is stated up front, never inferred from a capture afterwards. So it
stays open. It is settled cheaply next launch: state the frame-generation
setting in the contract, or count `vkQueueSubmit` alongside `vkQueuePresentKHR`
in the journal. **Either way it does not change §13.3**: 299 full rebuilds with
`tlas_updates:0` is a per-frame rebuild by any reading, which is what cause (a)
needs.

**~193 BLAS builds per present is noted and NOT chased.** A streaming city
rebuilding skinned and deforming geometry every frame is the expected shape, and
nothing in the identity question depends on it. It is written down so that a
later reader who finds it surprising knows it was seen and consciously left.

**The second TLAS is empty, and its identity is UNKNOWN.** Handle
`0x7de6689d0730` at `0x60c00000` reads `instances_last:0, instances_max:0` in
every row, and its first build is logged in full:

```
{"seq":5324,"ev":"as_build","dst":"0x7de6689d0730","addr":"0x60c00000","type":"top","build_info_type":"top","declared_at_create":"generic","mode":"build","flags":4,"geoms":1,"prims":0,"nth_build":1,"in_frame":1,"frame":16778,"new_tlas":1}
{"seq":5322,"ev":"as_create","as":"0x7de6689d0730","type":"generic","size":33554432,"reuse":0,"n":1,"n_top":0}
```

So it is a genuine top-level build (`prims:0`, one instance geometry with zero
instances) against a 32 MiB allocation, created `GENERIC` like everything else,
built in exactly the same frames and the same counts as the populated one
(17/17, then 316/316, with identical `builds_per_frame` histograms), address
never moved. The same pairing appears in earlier launches with different
handles (`0x798d7cd75880`/`0x61200000` at `prims:0` beside
`0x798d8cdef450`/`0x199410000` at `prims:52469`), so it is **structural, not a
one-off**. What it is *for* — a second RT scene the engine keeps but does not
populate here, or a placeholder bound to descriptor slots that must be valid —
the journal cannot say, and it is left unknown rather than guessed.

**This answers §12.7's "more than one TLAS handle" row**, which said nothing in
the frame is interpretable until the raygen's `%accel` is matched to a TLAS. It
matches by elimination and the frame itself is the evidence: a query against a
TLAS with zero instances commits nothing, so it would paint nothing, and the
frames from `-p`, `-pcust`, `-pprim` and `-pclosest` are all painted over most
of their area. The raygen's `%accel` is therefore the populated TLAS. That is an
argument from the paint, not a descriptor trace, and it is worth exactly that
much.

### 13.5 No position-fetch rung, and the reason is in the journal

The obvious next field is
`OpRayQueryGetIntersectionTriangleVertexPositionsKHR` — the committed triangle's
three object-space vertices, which would give a geometric identity with no
instance record involved at all. **It is not built, and it must not be**:
`build_flags` is **4** on both TLASes, i.e. `PREFER_FAST_TRACE` alone.
`VK_BUILD_ACCELERATION_STRUCTURE_ALLOW_DATA_ACCESS_BIT_KHR` (0x800) is **not**
set on any build in this journal, and the vertex-position fetch requires it on
the *acceleration structure being read*. Reading it anyway is undefined
behaviour, not a wrong answer: a rung built on it would paint garbage that looks
exactly like a result. The `88` census habit applies — the flag is a
measurement, so the rung is refused on the measurement.

**Design note, one paragraph, not built.** The layer already intercepts
`vkCmdBuildAccelerationStructuresKHR` for the journal (§8.2), and that hook sees
`VkAccelerationStructureBuildGeometryInfoKHR::flags` before the driver does. It
could OR `ALLOW_DATA_ACCESS` into every top- and bottom-level build, which would
make the position fetch legal and would unlock a genuinely instance-free
identity. Four things would have to be settled first, and none of them is free:
the flag must be advertised (`VkPhysicalDeviceRayTracingPositionFetchFeaturesKHR`,
which the layer would also have to enable on the device the way it enables ray
query, §7.1); the build **sizes** are queried through
`vkGetAccelerationStructureBuildSizesKHR` with the app's own flags, so the layer
would have to rewrite the flags there too or the driver may be handed a scratch
and result buffer sized for a structure it is not building; ~193 BLAS builds per
present means any per-build cost or size growth is paid ~193 times a frame; and
a rewrite that silently changes what the app asked for is exactly the class of
layer edit that produces a corrupted frame with no log line, so it needs its own
`--selftest` case and its own env kill-switch before it goes near the game.

### 13.6 Three new rungs — same splice, same flags, different question

All three are **primary site, first hit, flags 517**, the same
`%accel`/cull-mask/origin/direction/bracket clone, the same latch, the same
palette and the same hash chain as `hunt-rayq-p`. They differ in **exactly one
thing: what feeds the hash.**

| rung | field | getter | why it might survive a TLAS rebuild |
|---|---|---|---|
| **`hunt-rayq-psbt`** | `sbt` | `OpRayQueryGetIntersectionInstanceShaderBindingTableRecordOffsetKHR` | app-assigned per instance, and it selects **which hit group runs** — i.e. plausibly the material. A material assignment has no reason to be rewritten when the instance order changes |
| **`hunt-rayq-pgeom`** | `geom` | `OpRayQueryGetIntersectionGeometryIndexKHR` | it is not an instance field at all. Stable per geometry **within** a BLAS; **not unique across BLASes**, so a small number of hues over the whole frame is the *expected* reading |
| **`hunt-rayq-pxf`** | `xf` | `OpRayQueryGetIntersectionObjectToWorldKHR`, column 3, **raw bits** | the instance's world translation. A static object's transform is **bit-identical** every frame; a moving one's is not |

`-pxf` is the only one whose getter is not a `uint`, and its fold is stated
here because it is the whole rung. Read off the shipped
`skin.set/hunt-rayq-pxf/1271d3815051da17.rgs_reference_main.spv`:

```
%mat4v3float = OpTypeMatrix %v3float 4          ; line 1353, type section, ours
...
%2222 = OpRayQueryGetIntersectionObjectToWorldKHR %mat4v3float %1252 %uint_1
%2223 = OpCompositeExtract %v3float %2222 3     ; column 3 = the translation
%2224 = OpCompositeExtract %float %2223 0
%2225 = OpCompositeExtract %float %2223 1
%2226 = OpCompositeExtract %float %2223 2
%2227 = OpBitcast %uint %2224
%2228 = OpBitcast %uint %2225
%2229 = OpBitcast %uint %2226
%2230 = OpBitwiseXor %uint %2227 %2228
%2231 = OpBitwiseXor %uint %2230 %2229          ; -> the latch, unchanged
```

**No quantisation, and that is the design.** Rounding the translation to a grid
would smear a moving car into a stable bucket and destroy the exact asymmetry
the rung exists to show. **Buildings stable and moving cars/NPCs flickering is
the pre-registered signature, not a defect** (§13.7). The type did not exist —
a census of the base rung finds **0 of 12** reference raygens declaring any
`OpTypeMatrix` — so all 10 patched modules get a fresh `%mat4v3float`, emitted
into the module's own type section: line 1353, below `%v3float` (line 1046) and
above the first `OpFunction` (line 1363). `_ensure_line` reuses an existing
declaration where there is one; the verifier re-derives the section placement
from the shipped bytes rather than trusting that.

Shas, computed the way `sync_settings.sh` computes `skin_sha`
(`cat <dir>/*.spv | sha256sum | cut -c1-16`):

| rung | content sha256 (93 modules) | raygen half sha |
|---|---|---|
| `hunt-rayq-psbt` | `3fb96c406ca2d796` | `092522d97995cf72` |
| `hunt-rayq-pgeom` | `5b141d145cdd9554` | `89955de3420fe52f` |
| `hunt-rayq-pxf` | `0754da611bcd3915` | `511d4ea6850824cc` |

**All nine earlier rungs are bit-identical to §1.2's table after this change** —
content and raygen-half sha both, every one — so adding three fields changed
nothing about the four rungs already shot.

Gates, all green, `./dev/build_rayq.sh` build-failing on every one:

| gate | result on the three new rungs |
|---|---|
| 1 round-trip neutrality | 10/10 base permutations `spirv-dis → spirv-as` byte-identical |
| 2 patch + assemble | 93 modules each, 10 patched, `spirv-val --target-env vulkan1.4` clean; compute+restirgi `cmp`-verbatim; **exactly 10 of 93 files differ from the base rung** |
| 3 coverage census | **10 modules, 25 painted writes, 22 benign skips**, site=primary, flags 517/`first` — identical to every other rung, which is what "differ by ONE variable" means |
| 4 instruction census, shipped bytes | 10 × (1 Initialize, 1 Proceed, 0 added `OpTraceRayKHR`), 2 pass-throughs clean |
| 5 gain-0 reproducibility | unchanged and still green: primary 10/10 byte-identical to `-pctl`, 10/10 differing from the base. (A gain-0 build is **not** byte-identical to the base — the query still executes; that is the point of §2's control, and gate 5 asserts the difference explicitly) |
| 6 verifier, shipped bytes | 10/10 permutations, 25 painted writes, ALL PASS, each read at its own field |
| 6b hash-chain audit | CLEAN, 10/10 modules, each rung |
| 7 verifier non-vacuity | **18 decoys rejected**, up from 12: the six new ones are the full 3×3 field matrix (§13.6a) |
| cull mask | `%uint_255` on 10/10 modules of each rung, and asserted **by SSA id** against the module's own trace, not by value |

#### 13.6a The 3×3 field matrix

Each rung read as each field. Diagonal accepts, off-diagonal rejects; every
reject line is the verifier's own, printed by `./dev/build_rayq.sh`:

|  | `--field sbt` | `--field geom` | `--field xf` |
|---|---|---|---|
| `hunt-rayq-psbt` | **PASS** | REJECT | REJECT |
| `hunt-rayq-pgeom` | REJECT | **PASS** | REJECT |
| `hunt-rayq-pxf` | REJECT | REJECT | **PASS** |

```
  rejects hunt-rayq-psbt read as --field geom, as required
  rejects hunt-rayq-psbt read as --field xf, as required
  rejects hunt-rayq-pgeom read as --field sbt, as required
  rejects hunt-rayq-pgeom read as --field xf, as required
  rejects hunt-rayq-pxf read as --field sbt, as required
  rejects hunt-rayq-pxf read as --field geom, as required
```

The verifier gained a check to make `xf` more than a getter-name match (7b): it
re-derives the fold instruction by instruction from the shipped bytes — the
result type **is** an `OpTypeMatrix %v3float 4` declared above the first
`OpFunction` and below `%v3float`; the matrix is consumed **exactly once**, by
the extraction of column 3; each of x/y/z is extracted once and `OpBitcast` to
`uint` **with no arithmetic in between**, which is what "raw bits" means as a
check rather than as a claim; and the two XORs fold all three into the value the
committed arm of the latch select writes.

`dev/audit_rayq_hash.py` needed one change for the same reason: its forward walk
from the getter to the latch assumed the getter's result *was* the latched
value. It now walks a whitelist (`OpSelect`, `OpCompositeExtract`, `OpBitcast`,
`OpBitwiseXor`) — so a getter that reached the latch through arithmetic on a
**second** value would leave the whitelist and be reported. The backwards leaf
closure is untouched, and it still rejects the `--decoy hash` build that folds
this frame's radiance into the hash.

#### 13.6b The self-test grew, and it grew where it was blind

`./dev/patch_rayq.sh --selftest`: **45 passed, 0 failed** (was 36).
`./dev/patch_ser.sh --selftest` still **11 passed, 0 failed**.

The nine new assertions are **case E**, and they exist because `spirv-val` is
not a driver: it checks that a getter is well-formed, not that this NVIDIA
driver will compile it. Case E builds one synthetic raygen **per getter**
(derived from the existing `rq.spvasm` so the only difference is the readback,
with the getter folded into the value the module writes so nothing can dead-code
it), serves each through the layer, and requires the RT pipeline to link
(`"swapped":1`) — a module per getter so a driver that refuses one names which.
It then requires a **real ~300 KB patched raygen from each of the three rungs**
to be accepted by `vkCreateShaderModule` (`hunt-rayq-pxf`'s is 305 004 B, 184 B
larger than the others — the fold and the matrix type). All nine pass on
**NVIDIA GeForce RTX 4070**.

`make install` (2026-09-02 18:49) then carried `init.lua` with **12**
`hunt-rayq` rows and the untouched **4** `hunt-wpos` rows, asserted on the
**live** file; `cmp` clean against the repo copy and `release/`. The layer is
byte-unchanged this session (`md5 2625d5c2c4fd227fecbe2ac102b89b53`), `cmp`
clean against both the repo build and `release/vulkan/`. All 12 rungs are parked
in `~/.local/lib/callisto/skin.set/`, `cmp` clean file-for-file against the
build outputs (0 of 93 differ, each). **Nothing was committed.**

---

### 13.7 Pre-registered for the NEXT launch — written BEFORE anyone looks at a screen

Shoot in this order: **`hunt-rayq-psbt`, then `hunt-rayq-pxf`, then
`hunt-rayq-pgeom`.** `-psbt` is first because it is the only one of the three
that could be an *identity* rather than a diagnostic; `-pxf` second because its
outcome is pre-registered as an asymmetry and therefore cannot be talked into
agreeing with whatever is seen; `-pgeom` last because its most likely reading is
"a handful of hues", which is informative only next to the other two.

#### Settings contract — stated now, not inferred from the captures afterwards

```
skinspec  = hunt-rayq-psbt       FIRST, then hunt-rayq-pxf, then hunt-rayq-pgeom
ser       = class                REQUIRED -- the rungs carry SER splices; ser=off is refused
shadowset = full-shadow          REQUIRED -- the rungs ship vanilla-based rgs_restirgi_*
ptq       = rcbm                 unchanged; baked against ptq_sha=55ed4e5c6884ab71
ptrefl    = on, refract = fres   unchanged from the 16:24 .. 18:27 launches
tier      = on,  cache = cleared
frame generation = STATE IT (13.4's one-build-per-two-presents is open on it)
```

skin_sha, to be checked against `~/callisto_launches.log` after each launch:

| rung | skin_sha |
|---|---|
| `hunt-rayq-psbt` | `3fb96c406ca2d796` |
| `hunt-rayq-pgeom` | `5b141d145cdd9554` |
| `hunt-rayq-pxf` | `0754da611bcd3915` |
| `hunt-rayq-pctl` (control, already shot) | `9e7ac409ff8db3f7` |

Same framing as §12 and §12.7: a street with several distinct objects at
different depths, **sky in frame** (it is the control), a character, and — for
`-pxf` specifically — **both a static building and a moving car or NPC in the
same shot**, because that rung's whole reading is the *difference* between them.
**Stand still for several seconds and watch**; the finding is temporal and a
still cannot hold it. `./dev/patch_rayq.sh --selftest` must read **45 passed, 0
failed** before any of this.

#### The table

| what you see | reading | what to do next |
|---|---|---|
| **`-psbt` is stable and flat per object** — a car one hue, a wall another, holding still and under movement | **The identity is found.** The SBT record offset survives the rebuild, so an app-assigned per-instance value **is** reachable. `88` has its key | stop hunting. Confirm it is not accidentally constant by checking that **several distinct hues** are present, then build the consumer |
| **`-psbt` is stable but SHARED** — large groups of unrelated objects share one hue and the hue count is small | **Also a pass, and the more likely one.** It is a *material* handle, not an object handle: stable, coarse, and exactly what a hit-group index should look like | good enough for per-material work (car paint, skin, glass) and **not** good enough for per-object. Say which the consumer needs before building it |
| **`-psbt` flickers** like `-p` and `-pcust` | The engine rewrites the SBT offset with the instance order too — the whole `VkAccelerationStructureInstanceKHR` is regenerated per frame, not just the index fields | the instance record is dead as an identity source. Go to `-pxf` and `-pgeom`, and then to the BLAS address (Stage 2b, §10.3) |
| **`-pxf` is stable on buildings and flickers on moving cars/NPCs** | **The pre-registered signature, and a PASS.** The transform is a real, frame-stable identity for static geometry, and the flicker on movers is arithmetic — a moving object's translation genuinely changes. It also proves the committed *instance* is consistent frame to frame even though its slot index is not | use it as the identity for static geometry, and note that "stable" here means "stable while the object does not move", which most of a city is |
| **`-pxf` flickers on static buildings too** | One of two things, and they are distinguishable **without another launch**: (i) the engine rewrites the object-to-world matrix of static instances every frame (a real finding, and it would kill transform-based identity outright), or (ii) the splice reads the wrong thing — the wrong column, or a mis-declared matrix type | **check (ii) first, offline**: `python3 dev/verify_rayq.py <rung> --field xf --site primary` re-derives the type as `OpTypeMatrix %v3float 4`, its declaration's section, the single consumer of the matrix, the extraction of **column 3**, and the three raw `OpBitcast`s. If that passes, (ii) is excluded and (i) is the finding |
| **`-pxf` is stable everywhere, movers included** | The extraction is not reading a translation at all — a column of a rotation basis is much more nearly constant. Treat as (ii) above until the verifier says otherwise | same offline check; if it passes, suspect the column convention and read `ObjectToWorld` column 3 against a known-moving object before believing it |
| **`-pgeom` is mostly one or two hues** over the whole frame | **Expected, and not a failure.** `GeometryIndex` is 0 for most single-geometry BLASes. It confirms the getter reaches the shader and says nothing about identity | do not over-read it. Its only job is as a positive control for "a non-instance field reaches the paint" |
| **`-pgeom` shows many hues** | More multi-geometry BLASes than expected — mildly interesting, still not an identity (it is not unique across BLASes) | record it, move on |
| **Sky painted** on any rung | **VOID**, exactly as §5.1 and §12.7 said | do not read the frame; investigate the bracket |
| **Everything unpainted** on one rung while the others paint | Not a bracket problem (the bracket is shared and unchanged). That field hashes to one bucket everywhere, or is constant zero | compare against `-pctl`; the getter is the story, not the ray |
| Any rung differs from `-pctl` in a way that is **not a hue** — geometry, brightness, a crash, a black screen | **Debug the LAYER, not the shader.** The three rungs differ from `-pctl` by one getter and the palette gain and nothing else | grep `rayq_reject`, `"swap":"HIT"`, `"ev":"rayq"`, the manifest echo, **before** blaming the splice |
| `as_summary` shows `untracked_builds`, `table_overflow` or `tlas_handle_overflow` non-zero | The journal is lying again; v2 asserts these are 0 by construction | fix the journal before reading any rung |

**What none of these rungs can produce, and it is understood rather than hoped
for:** flat per-object silhouettes on a **sunlit** surface. §12.4 measured why —
the paint is an `OpFMul` on this raygen's radiance, and a sunlit pixel is not
made of this raygen's radiance (one part in 270 on sunlit stone). Every row
above is a reading of the **shaded, ambient, glass and chrome** part of the
frame, and of the per-triangle blocks `-pprim` put on the facades. Changing that
needs a **storage-image destination** — `88`'s second G-buffer — not a better
ray and not a better field.

---

## 14. Shot 2026-09-02, 19:00–19:04 — the transform is camera-relative, and §13.7 had no row for it

Three rungs on screen. `-pgeom` did exactly what §13.7 said it would and is a
clean positive control. `-psbt` and `-pxf` both flickered, and **the reading
§13.7 pre-registered for `-pxf` was incomplete**: there is a third cause it
does not list, `94` §3.3 names it, the user's own phrasing points straight at
it, and two new rungs are built to separate it from the two that *are* listed.

### 14.1 What was launched

Verbatim from `~/callisto_launches.log`:

```
2026-09-02T19:00:36-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-rayq-psbt  skin_sha=3fb96c406ca2d796 tier=on cache=cleared
2026-09-02T19:02:37-05:00 ... skinspec=hunt-rayq-pxf   skin_sha=0754da611bcd3915 cache=cleared
2026-09-02T19:04:42-05:00 ... skinspec=hunt-rayq-pgeom skin_sha=5b141d145cdd9554 cache=cleared
```

All three match §13.7's contract — `ser=class`, `shadowset=full-shadow`,
`ptq=rcbm`, `ptrefl=on`, `refract=fres`, `tier=on`, cache cleared — and every
`skin_sha` is the value §13.7 pre-registered for that rung. The shoot order was
§13.7's: `-psbt`, then `-pxf`, then `-pgeom`.

**Frame captures: one, for `-pgeom` only.** The game's photomode directory holds
exactly one PNG newer than the three launches,
`photomode_02092026_191320.png` (19:13:38); it post-dates the 19:04:42 `-pgeom`
launch, so it is that rung's frame, and it is copied verbatim to
`a-b-testing/rayq-p/D-pgeom-191320.png` with the numbers in that directory's
`RESULT.md`. **There is no `-psbt` and no `-pxf` capture.** Both of those
read-outs are about *motion*, which a still could not have held in any case, so
nothing is lost that a screenshot could have supplied — but it is recorded
rather than glossed.

### 14.2 The read-out, verbatim

> "hunt-rayq-pgeom is the only stable one. Every single wall, person, and car is
> red. The direct ground in the sun is not red (actually it probably is red just
> only noticeable in shadow). Sky is normal. hunt-rayq-pxf flickers like crazy
> with motion. Same with hunt-rayq-psbt. Windows dont seem to be red. yea pretty
> sure every surface except for windows are red. Unless the windows are just so
> blue from reflection in the first place that I cant notice"

Asked afterwards whether `-pxf` was stable while standing still, the answer, in
full:

> "If anything moved it would flicker"

### 14.3 Which §13.7 rows fired

| §13.7 row | fired? |
|---|---|
| **"`-pgeom` is mostly one or two hues over the whole frame"** | **YES — one hue, red, over everything** |
| "`-psbt` flickers like `-p` and `-pcust`" | **YES** |
| "`-pxf` flickers on static buildings too" | **YES** — and see §14.5: the row's two candidate causes are not the only two |
| "`-psbt` is stable and flat per object" / "stable but SHARED" | NO |
| "`-pxf` is stable on buildings and flickers on movers" (the pre-registered PASS) | NO |
| "`-pxf` is stable everywhere, movers included" | NO |
| "`-pgeom` shows many hues" | NO |
| **Sky painted** | NO — "sky is normal" on all three, the built-in control holds |
| Everything unpainted on one rung | NO |
| A non-hue difference from `-pctl` | NO |
| `untracked_builds` / `table_overflow` / `tlas_handle_overflow` non-zero | not re-read this shoot; §13.4's journal is the standing read |

### 14.4 `-pgeom`: `GeometryIndex` is 0 everywhere, and 0 is red

The frame is a single red cast. Measured against the two frames already in
`a-b-testing/rayq-p/`, over all pixels and over the darker half:

| frame | mean RGB | `(R−G)/Y` all | `(R−G)/Y` shaded | `(G−B)/Y` all |
|---|---|---|---|---|
| `B-pctl-163134.png` (control) | 107.3 / 98.5 / 81.9 | 0.031 | 0.029 | 0.123 |
| `C-pprim-174636.png` | 118.7 / 104.3 / 87.1 | 0.062 | 0.085 | 0.115 |
| **`D-pgeom-191320.png`** | **127.9 / 87.0 / 67.5** | **0.207** | **0.302** | 0.138 |

An order of magnitude past the control on red-minus-green, ~10× on the shaded
half, while green-minus-blue (the scene's own sky/sun split) barely moves. One
hue, and it is red.

**That it is red is arithmetic on the shipped constants, not a guess.** The
palette is fixed and ordered, `PALETTE[0] = red (3.00, 0.20, 0.20)`, and the
bucket is `h = id * 2654435761; h ^= h >> 15; bucket = h & 7`. For `id = 0`:
`0 * 2654435761 = 0`, `0 >> 15 = 0`, `0 ^ 0 = 0`, `0 & 7 = 0` → **bucket 0 →
red**. So "every surface red" is exactly "`GeometryIndex == 0` on every
committed hit", which is §13.6's own expectation for the field: stable per
geometry *within* a BLAS, and this engine's BLASes are overwhelmingly
single-geometry. It says the getter reaches the paint and the query commits on
essentially the whole frame; it says nothing about identity. That was its only
job and it did it.

"The direct ground in the sun is not red (actually it probably is red just only
noticeable in shadow)" is §12.4, measured: the paint is an `OpFMul` on this
raygen's radiance and a sunlit pixel is not made of this raygen's radiance —
one part in 270 on sunlit stone. The user reached the right reading unprompted.

**The windows are UNRESOLVED, recorded and not chased.** Two candidates, and
this shoot cannot separate them: (a) the glass geometry is at a geometry index
≠ 0 inside its BLAS and lands in a bucket the reflection hides, or (b) window
pixels' radiance arrives through a path this paint does not multiply — a
separate reflection/refraction write, or a resolve that does not pass through
the 25 painted stores. The user's own hedge ("unless the windows are just so
blue from reflection in the first place that I cant notice") is a third and
entirely live possibility. No rung is built for it.

### 14.5 `-psbt` and `-pxf`, and the row §13.7 did not write

**`-psbt` fired §13.7's third row and the reading is unchanged.** The SBT record
offset flickers exactly like `InstanceId` and `InstanceCustomIndex`, so the
engine rewrites the hit-group offset along with the instance order: **the whole
`VkAccelerationStructureInstanceKHR` is regenerated per frame**, not just the
index fields. The instance record is dead as an identity source, in all three of
its app-writable fields.

**`-pxf` fired the "flickers on static buildings too" row, whose two candidates
were (i) the engine rewrites the object-to-world matrix of static instances
every frame, and (ii) the splice reads the wrong thing.** §13.7 required (ii) to
be checked offline first, and the reviewer ran it:

```
python3 dev/verify_rayq.py hunt-rayq-pxf --site primary --field xf
  -> PASS, 10/10 permutations, 25 painted writes, column 3, three raw bitcasts
```

So **(ii) is excluded** — the matrix type, its section, the single consumer, the
column-3 extraction and the three arithmetic-free `OpBitcast`s are all as
documented in the shipped bytes — and by §13.7's own rule (i) stands.

**But (i) is not the only thing left, and §13.7 should have said so.** There is
a third reading, it is not exotic, and this document already contains the
sentence that implies it:

> **The TLAS is built in CAMERA-RELATIVE space.** `94` §3.3: the module's own
> hit position is camera-relative, and the shader adds `cbv[..][56].xyz` to it
> before storing it anywhere that has to survive a frame. If the acceleration
> structure is built in that same space, then **every** instance's
> `ObjectToWorld` translation is `world − camera`, and a perfectly static
> building's translation changes *exactly when the camera moves* — not because
> anything rewrote it, but because the space it is expressed in moved.

Under that reading "flickers on static buildings" is not a finding about the
engine's instance bookkeeping at all; it is arithmetic, the same way the
pre-registered flicker on moving cars was arithmetic. And it makes a prediction
(i) does not: a per-frame *rewrite* would flicker while the camera is parked and
nothing in the scene moves, whereas camera-relative space would hold perfectly
still.

**§13.7 has no row for this, and that is a pre-registration defect.** It is
recorded as one. The `-pxf` row was written with two candidates and an
instruction to check one of them offline; the check passed, the row's own logic
then pointed at (i), and (i) is a *stronger* claim than the evidence supports.
The two rungs in §14.6 exist to separate them, and until they are shot the
honest state of `-pxf` is "(ii) excluded; (i) and camera-relative space both
live".

**The user's answer points at camera-relative space, and this is an
interpretation of a short answer.** Asked to split still from moving, the reply
was *"If anything moved it would flicker"* — read as: the paint held while
nothing moved, and flickered as soon as the camera or an object moved. That is
the camera-relative signature and **not** the per-frame-rewrite reading, because
a per-frame rewrite would flicker while standing still too. It is seven words
about a temporal effect, so it is treated as a strong hint and not as a result:
§14.7 asks for the still-versus-motion split again, on `-pxfw`, as a separate
line.

### 14.6 Two new rungs — the same splice, differing only in the arithmetic on one column

Both are **primary site, first hit, flags 517**, the same `%accel` / cull-mask /
origin / direction / bracket clone by SSA id, the same latch, the same palette,
the same hash chain, the same getter as `-pxf`
(`OpRayQueryGetIntersectionObjectToWorldKHR`, column 3). They differ from `-pxf`
and from each other in **exactly what happens to the three floats of that
column** before they are bitcast.

| rung | field | fold | the question |
|---|---|---|---|
| **`hunt-rayq-pxfq`** | `xfq` | `bitcast(int(t.c * 100))`, XOR-folded | **the CONTROL.** Quantisation and nothing else. Under the camera-relative reading it must **still flicker with camera motion** — rounding a value that genuinely changes does not make it stop changing |
| **`hunt-rayq-pxfw`** | `xfw` | `bitcast(int((t.c + cb[56].c) * 100))`, XOR-folded | **the test.** `t + offset` is `(world − camera) + camera = world`, a frame-stable world translation, if and only if the TLAS really is camera-relative and `cbv[..][56]` really is that camera offset |

`-pxfq` is not decoration. If it turned out to be stable, the whole
camera-relative story would be wrong and the answer would instead be that the
raw translation was jittering sub-centimetre and `-pxf` was reading fp32 noise.
That is a different world, and one rung tells them apart.

#### 14.6a Where the world offset comes from, and how it is found

`94` §3.3 identifies it as `cbv[104][56].xyz`. **104 is not an index** — it is
that dump's SSA id for the bindless-CBV access chain, and every permutation
renumbers, so it cannot be used. `56` *is* a member index, but it is not assumed
either. Both patcher and verifier re-derive the anchor from the shape `94`
actually reasoned from, independently of each other
(`patch_rayq._find_world_offset`, `verify_rayq.derive_world_offset` — a
deliberate second implementation, the same discipline as the primary-ray
detector):

> the CB member whose `.xyz` is added, component by component, to the module's
> own **path-vertex hit position** — the `v3float` triple that is the **origin
> operand** of the module's own shadow/NEE `OpTraceRayKHR` sites.

Over the 10 patchable permutations of the standing base that resolves to
**member 56 in 10 of 10**, with exactly one `(CBV, member, position)` match per
module. A second candidate exists — member 5 — and is excluded by the
trace-origin clause alone: it is added to a triple that is never a ray origin.
The base pointer is asserted to be an `OpAccessChain %_ptr_Uniform_BindlessCBV`,
i.e. the module's own bindless constant-buffer heap, not a lookalike. If the
match is not unique the patcher **dies** rather than picking (GOTCHAS 10).

**The sign convention, read off the base rather than assumed.** In
`1271d3815051da17` the module itself does, at three separate sites:

```
%4137 = OpFAdd %float %4134 %1715        ; cb56.x + P.x   (reservoir path)
%3097 = OpFAdd %float %3094 %1715        ; cb56.x + P.x
%3211 = OpFSub %float (%3204 - %1715) %3207   ; (L.x - P.x) - cb56.x
```

The third is `L − (P + cb56)`, which pins the direction: **world = position +
offset**, an addition, no negation anywhere. The splice therefore emits
`OpFAdd %float <cb56.c> <translation.c>` — **offset first**, matching the
operand order of `94` §3.3's own quoted `%1419 = OpFAdd %float %1416 %727`. The
base uses both operand orders at different sites and `OpFAdd` is commutative, so
the order is a convention this build records, not a fact it discovered; the
*sign* is the fact, and it is an add.

**Placement.** No existing access chain on member 56 dominates the splice site
in 6 of the 10 permutations (in `1271d381` the first one is at line 2498, the
splice at 2338), so **all 10 get their own fresh chain and load** at the splice
rather than 4 of them reusing and 6 not — a rung whose splice differs between
modules is not one variable. The chain is emitted on the module's **own**
bindless-CBV pointer, which the patcher requires to be defined above the splice
site, and the dominance itself is proven the only way that is worth anything:
`spirv-val --target-env vulkan1.4` enforces use-def dominance and is run on all
93 modules of both rungs, clean.

#### 14.6b The quantisation, and its known defect stated up front

Three components, each `OpFMul` by `100.0`, `OpConvertFToS` to a signed 32-bit
integer, `OpBitcast` to uint, then the same two XORs `-pxf` uses. One centimetre
buckets; `int32` holds ±21 km of that, which is wider than the world. The type
is signed on purpose — the translation is signed and the sign must survive.

Quantisation is needed because `(world − camera) + camera` **is not bit-stable
in fp32** even when the object has not moved: the reconstruction rounds, and a
raw-bits hash turns the last mantissa bit into a different hue. That is exactly
why `-pxf`'s "no quantisation, and that is the design" (§13.6) cannot simply be
carried over once an offset is added.

**The defect this introduces, stated before the screen and not after.** A
component sitting within fp32 rounding of a 1 cm boundary can cross that
boundary as the camera moves, so **a small minority of static objects may
alternate between two hues under motion.** That is a *boundary artefact*, not a
per-frame rewrite, and the two are distinguishable by eye: the discriminator is
that **most buildings hold**. A result where a handful of surfaces toggle
between two colours while the facades around them stay flat is a PASS with a
known artefact; a result where the frame boils is not.

#### 14.6c Shas

Computed the way `sync_settings.sh` computes `skin_sha`
(`cat <dir>/*.spv | sha256sum | cut -c1-16`):

| rung | content sha256 (93 modules) | raygen-half sha |
|---|---|---|
| `hunt-rayq-pxfq` | `f951613292863de8` | `cd9d9057e0343817` |
| `hunt-rayq-pxfw` | `ca0b93c66b2b62ba` | `c8dbb940ac6c2031` |

**All twelve earlier rungs are bit-identical to §1.2's and §13.6's tables after
this change** — content and raygen-half sha both, every one, including
`hunt-rayq-psbt 3fb96c406ca2d796`, `hunt-rayq-pgeom 5b141d145cdd9554` and
`hunt-rayq-pxf 0754da611bcd3915`. Adding two fields changed nothing about the
seven rungs already shot.

#### 14.6d Gates

| gate | result on the two new rungs |
|---|---|
| 1 round-trip neutrality | 10/10 base permutations `spirv-dis → spirv-as` byte-identical |
| 2 patch + assemble | 93 modules each, 10 patched, `spirv-val --target-env vulkan1.4` clean; compute + restirgi + the 2 pass-throughs `cmp`-verbatim; **exactly 10 of 93 files differ** from `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog` |
| 3 coverage census | **10 modules, 25 painted writes, 22 benign skips**, site=primary, flags 517/`first` — identical to all twelve other rungs, which is what "differ by ONE variable" means |
| 4 instruction census, shipped bytes | 10 × (1 Initialize, 1 Proceed, 0 added `OpTraceRayKHR`), 2 pass-throughs clean |
| 5 gain-0 reproducibility | unchanged and green: primary 10/10 byte-identical to `-pctl`, 10/10 differing from the base |
| 6 verifier, shipped bytes | 10/10 permutations, 25 painted writes, ALL PASS, each rung read at its own field |
| 6b hash-chain audit | CLEAN, 10/10 modules, all fourteen rungs |
| 7 verifier non-vacuity | **39 decoys rejected**, up from 18 — see below |
| cull mask | `%uint_255` on 10/10 modules of each, asserted **by SSA id** against the module's own trace |

**The decoy matrix, and why it had to grow more than by two.** `xf`, `xfq` and
`xfw` **share one getter**, so check 7's per-getter count — the thing that made
every earlier rung a decoy for every other — **cannot tell them apart at all**.
Everything now rests on check 7b re-deriving the fold. The matrix is therefore
the full 5×5 over the field rungs (`psbt`, `pgeom`, `pxf`, `pxfq`, `pxfw`): 5
accepts on the diagonal, **20 rejects** off it, plus **6 more** reading the two
new rungs as `id` / `custom` / `prim`. Every reject line is the verifier's own,
printed by `./dev/build_rayq.sh`:

|  | `sbt` | `geom` | `xf` | `xfq` | `xfw` |
|---|---|---|---|---|---|
| `-psbt` | **PASS** | REJECT | REJECT | REJECT | REJECT |
| `-pgeom` | REJECT | **PASS** | REJECT | REJECT | REJECT |
| `-pxf` | REJECT | REJECT | **PASS** | REJECT | REJECT |
| `-pxfq` | REJECT | REJECT | REJECT | **PASS** | REJECT |
| `-pxfw` | REJECT | REJECT | REJECT | REJECT | **PASS** |

and `-pxfq` / `-pxfw` are each rejected as `id`, `custom` and `prim` as well.
What does the separating work inside the shared getter, all re-derived from the
shipped `.spv`:

* **`xf` rejects `xfq`/`xfw`** because each translation component must be
  `OpBitcast` to uint with *nothing* in between **and have no other consumer at
  all** — "raw bits" as a check rather than as a claim.
* **`xfq` rejects `xf`** (no multiply exists) and **rejects `xfw`** (the
  component is consumed by an `OpFAdd`, not by the scale). The scale constant is
  read back out of the bytes and required to be 100.0; the `OpConvertFToS`
  result type is read back and required to be an `OpTypeInt 32 1` declared above
  the first `OpFunction`.
* **`xfw` rejects `xf`/`xfq`** because the offset add must be there, its operand
  must be `OpCompositeExtract` component *k* of an `OpLoad %v4float` of an
  `OpAccessChain` on the module's **own** bindless CBV, and both access-chain
  indices are checked against the anchor the verifier derived for itself —
  index 0 and **member 56 as a result, not a constant in the source**.

**The hash audit needed a real change, and a new decoy to keep it honest.**
`dev/audit_rayq_hash.py`'s forward walk from the getter to the latch runs on a
whitelist (§13.6a). `xfq`/`xfw` add `OpFMul`, `OpConvertFToS` and — the
important one — `OpFAdd`, an operation *with a second operand*, so widening the
whitelist would have quietly retired the property the walk exists for. The fix
is not to widen and hope: the whitelist is now explicitly only a **reachability**
test, and what the second operands are is proven by a **new backwards walk**
from the `OpStore` into the id latch. Every leaf of that closure must be a
constant, a ray-query getter, a load of one of our own two Private latch
variables, or an `OpLoad %v4float` through an `OpAccessChain` in **Uniform**
storage — the constant-buffer read `xfw` needs and nothing else. An image fetch,
a payload read, an LCG state, a frame index or a push constant is a different
shape and is reported. For `hunt-rayq-p`/`1271d381` the walk reports exactly:

```
latch inputs : %2219=OpRayQueryGetIntersectionTypeKHR
               %2221=OpRayQueryGetIntersectionInstanceIdKHR
               %2222=latch OURS  %2226=latch OURS  %uint_0=const
```

That walk would be vacuous with nothing to reject, so `patch_rayq.py --decoy
latch` is new: it XORs the bracket's own `t` — a depth-buffer-derived value, and
therefore a different one every frame — into the value the latch stores,
**upstream of the paint**, where §12.6(c)'s select-chain closure cannot see it.
The audit rejects it, and `verify_rayq.py --field xfw` rejects it too. Never
installed. Non-vacuity is now **39 ways**: the 9 structural decoys, 26 field
decoys, and 4 patcher decoys (`ray`, `ray --site primary`, `flags`, `latch`).

#### 14.6e The self-test grew to 51

`./dev/patch_rayq.sh --selftest`: **51 passed, 0 failed** (was 45).
`./dev/patch_ser.sh --selftest` still **11 passed, 0 failed**.

The six new assertions extend **case E** — the case that exists because
`spirv-val` is not a driver. Two more synthetic raygens (one per fold, derived
from the same `rq.spvasm` so the only difference is the readback, with the
result folded into the value the module writes so nothing can dead-code it) are
served through the layer and required to link, and a **real ~300 KB patched
raygen from each of the two new rungs** is required to be accepted by
`vkCreateShaderModule`. The new driver question the folds raise over `xf` is
`OpConvertFToS` applied to a ray-query result inside a raygen; `spirv-val` says
it is well-formed, only a driver says it compiles. The synthetic `xfw` module
uses a constant offset triple rather than a uniform load — what it tests is the
**fold shape**, and the descriptor is covered by the real `hunt-rayq-pxfw`
raygen in the same run. All pass on **NVIDIA GeForce RTX 4070**.

#### 14.6f Deployment

`make install` (2026-09-02 19:35) carried `init.lua` with **14** `hunt-rayq`
`SKIN_LEVELS` rows (the two new ones mirror the existing `-pxf` row) and the
untouched **4** `hunt-wpos` rows, asserted on the **live** file; `cmp` clean
against the repo copy and against `release/`. The layer is byte-unchanged this
session (`md5 2625d5c2c4fd227fecbe2ac102b89b53`), `cmp` clean against the repo
build, `release/vulkan/` and the installed copy. All **14** rungs are parked in
`~/.local/lib/callisto/skin.set/`, `cmp` clean file-for-file against the build
outputs (**0 of 94 files differ, each**, MANIFEST included). **Nothing was
committed.**

### 14.7 Pre-registered for the NEXT launch — written BEFORE anyone looks at a screen

Shoot in this order: **`hunt-rayq-pxfw`, then `hunt-rayq-pxfq`.** `-pxfw` first
because it is the one with a signature that can fail; `-pxfq` second because its
job is to say whether quantisation alone explains whatever `-pxfw` does, and
that question only has meaning after `-pxfw` has been seen.

**Report the still-versus-motion split separately, and as two answers rather
than one.** For `-pxfw`, say (a) what the paint does while you stand completely
still with nothing moving in frame for several seconds, and (b) what it does
while you walk or turn the camera. The whole of §14.5 turns on that split, and
the previous answer to it — *"If anything moved it would flicker"* — is being
read as "still = stable, motion = flicker" on seven words. Say it plainly this
time so the reading does not have to be inferred.

#### Settings contract — stated now, not inferred from the captures afterwards

```
skinspec  = hunt-rayq-pxfw       FIRST, then hunt-rayq-pxfq
ser       = class                REQUIRED -- the rungs carry SER splices; ser=off is refused
shadowset = full-shadow          REQUIRED -- the rungs ship vanilla-based rgs_restirgi_*
ptq       = rcbm                 unchanged; baked against ptq_sha=55ed4e5c6884ab71
ptrefl    = on, refract = fres   unchanged from the 16:24 .. 19:04 launches
tier      = on,  cache = cleared
frame generation = STATE IT      (13.4's one-build-per-two-presents is still open on it)
```

skin_sha, to be checked against `~/callisto_launches.log` after each launch:

| rung | skin_sha |
|---|---|
| `hunt-rayq-pxfw` | `ca0b93c66b2b62ba` |
| `hunt-rayq-pxfq` | `f951613292863de8` |
| `hunt-rayq-pxf` (raw bits, already shot) | `0754da611bcd3915` |
| `hunt-rayq-pctl` (control, already shot) | `9e7ac409ff8db3f7` |

Same framing as §12, §12.7 and §13.7: a street with several distinct objects at
different depths, **sky in frame** (it is the control), a character, and — for
these two specifically — **a static building and a moving car or NPC in the same
shot**, because the whole reading is the *difference* between them. **Stand
still for several seconds and watch, then move, and report the two separately.**
`./dev/patch_rayq.sh --selftest` must read **51 passed, 0 failed** before any of
this.

#### The table

| what you see | reading | what to do next |
|---|---|---|
| **`-pxfw`: static buildings flat and stable under camera motion, and moving cars/NPCs flicker or change hue as they move; sky clean** | **PASS, and the strongest result this family can give.** The TLAS is built in **camera-relative** space; `ObjectToWorld[3] + cbv[..][56].xyz` is a frame-stable **world** translation, and it is a real identity for static geometry. It also **proves `94` §3.3's "inferred, not proven" line on screen**: the CB member really is the camera offset that turns the module's camera-relative position into world space | stop hunting identity for static geometry. Record the proof in `94` §7 (the confidence table's row moves off "inferred"). Then decide whether per-*object* granularity is needed beyond per-position, and note that two co-located instances share a hue by construction |
| **`-pxfw` flickers on static buildings, like `-pxf`** | Either the offset is the wrong CB member, or the TLAS is **not** in that space and `-pxf`'s flicker really was §13.7's cause (i) — a per-frame rewrite of the object-to-world matrix | **name the offline check before re-shooting**: `python3 dev/verify_rayq.py hunt-rayq-pxfw --site primary --field xfw`, which re-derives the anchor member from the shipped bytes by the trace-origin rule and asserts the splice's own access chain matches it. If that PASSES, the member is right and the space is wrong, and transform-based identity is dead — go to the BLAS address (Stage 2b, §10.3) |
| **`-pxfw` is stable everywhere, movers included** | **A BUG, not a result.** A moving car's world translation genuinely changes; anything that makes it constant is reading a rotation basis column rather than the translation, or is reading a matrix that is not `ObjectToWorld` | same offline check; then read column 3 against a known-moving object before believing any of it. Do **not** report a pass |
| **`-pxfq` is STABLE where `-pxf` flickered** | Quantisation alone fixed it → the raw translation was **jittering sub-centimetre** and `-pxf` was hashing fp32 noise. The transform was never per-frame-rewritten and it was never camera-relative in a way that mattered; **the offset is irrelevant** | drop the camera-relative story, say so in §14.5, and use `-pxfq` as the identity. `-pxfw` is then redundant and should be retired, not shipped |
| **`-pxfw` and `-pxfq` flicker identically** | Neither quantisation nor the world offset helps. **Transform-based identity is dead** — the object-to-world matrix of static geometry is not frame-stable in any space this splice can reach | stop this family. Stage 2b (buffer device address / BLAS address, §10.3) is the only remaining line |
| **A minority of static surfaces toggle between exactly two hues while most buildings hold** | **The known quantisation defect (§14.6b), and still a PASS.** A component near a 1 cm boundary crosses it as the camera moves | read the majority. If it is worth removing, coarsen to 10 cm and rebuild — one constant, one rung |
| **Sky painted** on either rung | **VOID**, exactly as §5.1, §12.7 and §13.7 said | do not read the frame; investigate the bracket |
| **Everything unpainted** on one rung while the other paints | Not a bracket problem (the bracket is shared and unchanged). That fold hashes to one bucket everywhere, or `OpConvertFToS` is saturating | compare against `-pctl`; the fold is the story, not the ray |
| Any rung differs from `-pctl` in a way that is **not a hue** — geometry, brightness, a crash, a black screen | **Debug the LAYER, not the shader.** The two rungs differ from `-pctl` by one fold and the palette gain and nothing else | grep `rayq_reject`, `"swap":"HIT"`, `"ev":"rayq"`, the manifest echo, **before** blaming the splice |

**What neither rung can produce, unchanged since §12.4 and understood rather
than hoped for:** flat per-object silhouettes on a **sunlit** surface. The paint
is an `OpFMul` on this raygen's radiance and a sunlit pixel is not made of this
raygen's radiance — one part in 270 on sunlit stone, and the user saw it again
this shoot ("the direct ground in the sun is not red"). Every row above reads
the **shaded, ambient, glass and chrome** part of the frame. Changing that needs
a **storage-image destination** — `88`'s second G-buffer — not a better ray, not
a better field, and not a better fold.

---

## 15. Shot 2026-09-02, 19:51–20:15 — the identity hunt is CLOSED, with a positive result

`-pxfw` fired §14.7's PASS row. **The TLAS is built in camera-relative space**,
`ObjectToWorld` column 3 plus the member-56 offset is a frame-stable world-space
object key, and `94` §3.3's "inferred, not proven" line is **proven on screen**.
`-pxfq`, the control, behaved exactly as the camera-relative reading requires.
No new rungs are built.

### 15.1 What was launched

Verbatim from `~/callisto_launches.log`:

```
2026-09-02T19:51:00-05:00 shadowset=full-shadow sc_sha=57ef80ee1f72f54a ptq=rcbm \
  ser=class:in-skin ser_sha=in-skin ptrefl=on refract=fres ptrefl_sha=ff8e6a509e516b73 \
  skin=on skinspec=hunt-rayq-pxfw skin_sha=ca0b93c66b2b62ba tier=on cache=cleared
2026-09-02T20:15:18-05:00 ... skinspec=hunt-rayq-pxfq skin_sha=f951613292863de8 cache=cleared
```

Both match §14.7's contract — `ser=class`, `shadowset=full-shadow`, `ptq=rcbm`,
`ptrefl=on`, `refract=fres`, `tier=on`, cache cleared — both `skin_sha` values
are the ones §14.7 pre-registered, and the order is §14.7's: `-pxfw` first.

**Frame generation was asked for in the contract and was NOT answered.** §13.4's
one-TLAS-build-per-two-presents therefore **stays open**, exactly as it was: the
obvious reading is that frame generation doubles the presents and there is one
rebuild per rendered frame, and the settings-sync rule forbids inferring it from
a capture afterwards. It changes nothing in §13.3 or here — 299 full rebuilds
with `tlas_updates:0` is a per-frame rebuild by any reading — and it is settled
next time by stating the setting or by counting `vkQueueSubmit` alongside
`vkQueuePresentKHR` in the journal.

**Frames: six, all `-pxfw`.** The game's photomode directory holds six PNGs
between 20:00:58 and 20:11:58 — after the 19:51:00 `-pxfw` launch and before the
20:15:18 `-pxfq` launch — so all six are `-pxfw`. They are copied verbatim to
`a-b-testing/rayq-p/E1-pxfw-200044.png` … `E6-pxfw-201141.png` with the numbers
in that directory's `RESULT.md`. **There is no `-pxfq` capture**, and that rung's
result rests on the live read-out alone; it is a read-out about motion, which a
still could not have held.

### 15.2 The read-out, verbatim

> "pxfw -> Movers stay sorta stable, but they might slowly get a different hue
> when they enter a different area. Very stable otherwise. pxfq -> unstable,
> occulusion from other objects changes the hue behind movers. Every sampled ray
> behind a mover takes a random colour"

### 15.3 Which §14.7 rows fired

| §14.7 row | fired? |
|---|---|
| **`-pxfw`: static geometry flat and stable under camera motion; sky clean** | **YES — "very stable otherwise". This is the PASS row.** |
| `-pxfw` flickers on static buildings like `-pxf` | NO |
| `-pxfw` stable everywhere including movers (the "bug" row) | **NO** — movers do change hue, so the extraction is reading a real translation, not a basis column |
| `-pxfq` stable where `-pxf` flickered | **NO** — "unstable", which is what the camera-relative reading requires |
| Both flicker identically (transform identity dead) | NO |
| A minority of statics toggling between two hues (the known 1 cm artefact) | **not reported** — no such toggling was called out, so the boundary artefact either did not fire or was below notice |
| Sky painted / everything unpainted / a non-hue difference | NO |
| **Movers change hue rapidly as they move** — §14.6's own expectation | **NO. See §15.5** |

### 15.4 Reading 1 — the key, and what it is

**Static geometry is flat and stable under camera motion.** That is the whole
finding, and it settles three things at once:

1. **The TLAS is built in camera-relative space.** `-pxf` (raw bits, no offset)
   flickered on static buildings; `-pxfq` (quantised, no offset) is still
   unstable; `-pxfw` (quantised, *with* the offset) is stable. The only
   difference between `-pxfq` and `-pxfw` is `+ cbv[..][56].xyz`, so the offset
   is what makes a static object's translation frame-invariant — which is only
   true if the translation was `world − camera` to begin with. §13.7's candidate
   (i), "the engine rewrites the object-to-world matrix of static instances every
   frame", is **dead**: nothing was being rewritten, the space was moving.
2. **`94` §3.3 is PROVEN ON SCREEN.** That document inferred
   `P_world = P + cbv[104][56].xyz` from two consumers agreeing (the ReSTIR-GI
   reservoir store and a light vector) and flagged it *"inferred from two
   consumers, not proven"*, with §6.3 step 4 designating a behavioural on-screen
   test. This is that test, by a different route: the same CB member — located
   structurally as member **56** in 10/10 permutations by the trace-origin rule
   (§14.6a), never by index — added to a *different* quantity (a ray query's
   `ObjectToWorld` translation rather than the shader's hit position) makes a
   camera-relative value frame-stable. That is what a camera offset does and
   nothing else does it. `94` §7's confidence table moves off "inferred".
3. **The identity hunt that opened at §12 is CLOSED, positively.** Five fields
   were tried and rejected — `InstanceId`, `InstanceCustomIndex` and the SBT
   record offset are all regenerated per frame (§13, §14.5); `PrimitiveIndex` is
   stable but triangle-scale; `GeometryIndex` is 0 almost everywhere. The sixth
   works.

**The key, in one sentence a later patcher can act on:**
`OpRayQueryGetIntersectionObjectToWorldKHR` on the committed intersection →
`OpCompositeExtract` **column 3** → add `cbv[<the module's own bindless
CBV>][56].xyz` component-wise (offset first, `world = translation + offset`) →
`× 100.0`, `OpConvertFToS %int`, `OpBitcast %uint` per component → XOR the three
together → that uint is a **frame-stable, world-space, 1 cm object key**, and
`dev/patch_rayq.py --field xfw` emits exactly it.

**Numbers, from the six frames.** Low-passed to 32×32 blocks so texture cannot
be mistaken for object structure, against the frames already in
`a-b-testing/rayq-p/`:

| frame | lowpass sd `(R−G)/Y` | distinct hue cells |
|---|---|---|
| `B-pctl-163134.png` (control) | 0.058 | 29 |
| `C-pprim-174636.png` (per-triangle) | 0.092 | 55 |
| `D-pgeom-191320.png` (one hue) | 0.160 | 37 |
| **`E1…E6-pxfw`** | **0.181 – 0.401** | **76 – 163** |

Three to seven times the control's block-scale hue spread and three to five
times its distinct-hue count, and — unlike `-pprim`, whose confetti a 32-px
low-pass averages away — the variety **survives** the low-pass, which is what
object-scale colouring means as a measurement rather than as an impression.

### 15.5 Reading 2 — the movers did NOT do what was pre-registered, and this is unexplained

§14.6 and §14.7 both say a moving car or NPC should change hue **as it moves** —
at 1 cm quantisation, essentially continuously. What actually happened:

> "Movers stay sorta stable, but they might slowly get a different hue when they
> enter a different area."

**That is not the pre-registered behaviour and it is recorded as unexplained.**
The rung is doing something real — movers *do* change hue, so it is not reading a
constant — but they change in **steps, on entering a different area**, not
continuously with motion.

**Leading hypothesis, stated as a hypothesis and not asserted.** §13.4 measured
**~193 BLAS builds per present**. A plausible shape for that number is that this
engine rebuilds animated and moving meshes' bottom-level structures every frame
**with the vertices already displaced into their current pose and place**, in
which case the instance's `ObjectToWorld` translation is not the object's live
position at all — it is a coarse anchor, a sector or area origin or a rarely
updated attachment point, and it moves in steps when the object crosses whatever
boundary owns it. That would produce exactly "stable, then a different hue in a
different area". It is consistent with everything measured and it is **not
established**.

**The offline check that would decide it**, if anyone cares: extend the AS
journal (§8.2) to record, for a handful of frames, the `transform` field of each
`VkAccelerationStructureInstanceKHR` in the TLAS build alongside whether that
instance's BLAS was among the ~193 rebuilt that present — a mover whose
translation is constant while its BLAS is rebuilt every frame is the hypothesis
confirmed; a mover whose translation tracks its motion smoothly kills it.
**It is not needed for the identity result**, which is a statement about static
geometry and is already carried by the frames.

### 15.6 Reading 3 — the control did its job, and exposed something not on the list

**`-pxfq` is unstable under motion, which is the control passing.** Quantisation
alone does not stabilise a value that genuinely changes: the camera-relative
translation moves whenever the camera moves, 1 cm buckets or not. That kills
§14.7's alternative reading ("the raw translation was jittering sub-centimetre
and `-pxf` was hashing fp32 noise"), and it means the offset — not the rounding —
is what does the work in `-pxfw`.

It also produced a line no pre-registration listed:

> "occulusion from other objects changes the hue behind movers. Every sampled ray
> behind a mover takes a random colour"

**Leading hypothesis, stated as such.** The query is bracketed at ±0.1 % of the
`|P|` the module reconstructs from the **depth buffer**, while the query itself
traverses the **TLAS**. At a mover's silhouette those two need not agree about
where the mover is — it moved between the depth pass and the TLAS build, or the
upsampler's jitter and disocclusion put the pixel's depth on the background while
the ray still clips the mover — so on a thin band of pixels the query commits the
**mover** while the pixel was shaded as background. Under `-pxfq` the mover's own
hue is per-frame random, so those pixels read as random colour; under `-pxfw` the
mover's hue is stable, so the same pixels are painted a steady colour and are
invisible. That is consistent with the read-out — the effect is reported on
`-pxfq` and not on `-pxfw` — and it is a hypothesis.

This is a **real property of the primary-surface query**, not a defect in these
rungs, and it is now written into §3.4 as a standing caveat: *the query's hit and
the raster's hit are not guaranteed to be the same object at moving silhouettes.*
Nothing is built for it.

### 15.7 What this unlocks

* **A frame-stable per-object key exists and is cheap.** The thing that actually
  asked for it is `94` **§4.4**, whose glint model is written as
  `P_w = (%727,%729,%731) + cbv[104][56].xyz` feeding a cell hash, and whose
  §3.3 warned that without a proven offset the glints would crawl across parked
  paint at walking speed; `94` §6.3 step 4's `-glintcell` diagnostic exists to
  test exactly that. That offset is now proven.
* **This document's own "`88` has its key" rows (§5.1, §12.7) were loose.** `88`'s
  ask, as §10.4 records it, is a *visibility* question ("is there geometry within
  10 cm of this skin pixel"), not an identity one. The key helps per-instance
  variation; it is not what the cavity cone was waiting for.
* **The whole primary-surface query mechanism is proven end to end** — trace,
  commit, field read, fold, paint — on real frames with a neutral control and a
  clean sky. Any further raygen-side ray-query use (thickness, off-screen
  visibility) can be built on this splice **without another sentinel rung**.
* **Two spaces in one frame — see `99` §10.** The compute resolvers reconstruct
  their shading point P in **world** space (measured on screen the same day:
  `hunt-wpos` welds to the environment, `hunt-wpos-cam` slides), while this
  raygen's TLAS and hit positions are **camera-relative**. Anything carrying a
  position between the two pipelines must add member 56 going raygen→resolver
  and subtract it going resolver→raygen; `99` §10.6 states the rule and §3
  there refuses to import member 56 into a resolver as an offset for P.
