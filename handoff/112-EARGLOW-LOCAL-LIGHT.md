# 112 — Ear glow from LOCAL lights (`earglow-di`): 111's transmittance driven by the clustered light loop, through 103's BDA slot

**Status 2026-09-03: BUILT, GATED (10/10), VERIFIED FROM SHIPPED BYTES, PARKED, INSTALLED — UNSHOT.**
Four rungs on the shipped default, selectable as `skinspec`:

| rung | what it is | content sha | compute-half sha |
|---|---|---|---|
| `earglow-di` | the default + ear glow from local lights, k = 7.2787 (`111`'s `-hue1` model, untouched) | `57750a496fde7d92` | `bc862085d0b08d3a` |
| `earglow-di-hi` | same, k × 2 — louder, nothing else | `e91d5108cabca9e0` | `c50ec032a294e3a9` |
| `earglow-di-hit` | DIAGNOSTIC paint on skin, per light: BLUE / AMBER / RED (§9) | `41cbd55db32278d6` | `b0dee6e49d7284c4` |
| `earglow-di-ctl` | byte-identical to the default (93/93 `cmp`) | `728b63de50c2a6a5` | `217a1087d48a39ce` |

Base = `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1`
(content `728b63de50c2a6a5`; the `earglow7-hue1` bytes under the stack name). The
16 raygens are the base's, verbatim. 60 of the 77 compute resolvers differ.

**This rung cannot be read without the BDA layer.** The TLAS reaches a compute
module only through `103`'s layer-owned slot. Shoot `bda-probe` FIRST (§8).

---

## 0. The ask, and the premise `111` §13 got wrong

Ask, verbatim: *"Implement the skin translucency from local light feature."*

`111` §13 offered route **(a)**: one extra shaded `OpTraceRayKHR` from the
raygen's entry point, reusing the raygen's irradiance. **That route rests on a
false premise.** The `rgs_reference_main` payload carries no radiance — the
raygen's ear glow (`101`/`111`) gets its light from the *sun* term it sits
next to, and there is no local-light irradiance anywhere in the raygen to
multiply against. Local (non-sun) lighting on skin is shaded in the **77
`GLCompute` resolvers**, inside a clustered light loop that walks 128-byte
light records, and that is the only place a per-light backside irradiance can
be formed. So this is `111` §13's route **(b)** in practice — compute side,
inline ray queries, `103` Stage 2c's mechanism — but at the *direct* light
loop, not at a ReSTIR-GI radiance.

`111` §13 is amended in place with a one-line pointer here.

## 1. The term

Per shadowed light record, per pixel, added at the **diffuse** radiance write:

```
raw   = directional ? -dir : lightPos - P            (the engine's own select, mirrored)
dist  = |raw|,   L = raw / dist
W     = k · max(-N·L, 0)                              (entry-face Lambert; N = the pixel's own decoded normal)
t     = query B hit ? t_B : 0.018                     (thickness toward the light, cull-front, 1.5–18 mm)
t_eff = max(t, 0.006)
T_c   = ½ (exp(-a1_c t_eff) + exp(-a2_c t_eff)) · tint_c
add_c = min(T_c · W · atten · colour_c, 100)          only if accept, else 0
```

`k = 7.2787`, `a1 = 865.41`, `a2 = 648.54`, `tint = [1, 0.02927, 0.12788]` —
`dev/transmit_model.py --ref 0.006 --fb-derm 0.01 --no-sensitivity`, the
**same `r6lo.json` the default ships** (gate 2 asserts the base's MANIFEST
names it). `atten` is the engine's own distance × spot attenuation scalar for
that light (§3 says exactly which one). `colour_c` is the record's colour at
offset 32.

`accept = hitA ∧ hitB ∧ (idA == idB) ∧ ¬hitC` — `101` §13's instance match and
`101` §15's exit-visibility query, unchanged in meaning from `earglow-rq3`:

| query | flags | origin | direction | tmin | tmax | reads |
|---|---|---|---|---|---|---|
| A | 517 (opaque, terminate-first) | `(0,0,0)` = the camera in TLAS space | `(P−C)/|P−C|` | `d − b` | `d + b`, `b = max(0.001 d, 5 mm)` | instance id of the pixel's own surface |
| B | 545 (cull FRONT, terminate-first) | `P − C` | `L` | 1.5 mm | 18 mm | `t` = back-wall distance toward the light, its instance id |
| C | 517 | `P − C + L (t + 1 mm)` | `L` | 1 mm | directional: 100 m; else `max(dist − (t+1 mm), 1 mm)` | anything between the exit point and the light |

Cull mask = `select(class == 1 ∧ slot-magic-ok ∧ atten > 0, 255, 0)`. A mask
of 0 makes the traversal trivial on non-skin and on lights that do not reach
the pixel; there is no branch.

## 2. Where it lives: the clustered light loop, and the two gates

Every compute resolver with local lights walks records via
`OpRawAccessChainNV %ptr %base %uint_128 %idx <offset>`: pos @0, dir @16,
colour @32, **flags @44** (a bitfield the engine ANDs with eight different
masks; bit 128 = directional, and the engine's own `select(flags&128, −dir,
pos−P)` is the template the splice mirrors), inverse range @68, shadow index
@72. (`93`'s "offset 44 = half2 scale/bias" is a *different* record — the
cavity cone's — not this one.)

The thing the site finder had to learn, and the census confirmed on all 77:
**a SHADOWED light loop has two colour-dependent `x > 0` gates per record**:

1. `atten > 0` — guards the spot-cone block (its true-block starts with the
   `FDiv sub/dist` that forms `L`);
2. `vis · atten_spot > 0` — guards the lit block (its true-block starts by
   constructing the `L` selects).

The site is the **LAST** such gate in the record's line range, and the splice
goes **immediately before it** — before the engine's own branch — because a
backlit ear is precisely the pixel where `vis = 0` and the engine skips the
lit block. `atten` is the unique factor of the flattened `FMul` product at that
gate whose backward cone contains the record's colour load; every other factor
is a visibility mask (phis, usually with a `%float_1` default), and **those are
deliberately not applied** (§4).

An UNSHADOWED loop has only gate 1 — its spot factor is computed *inside* the
lit block, so there is no `atten` scalar live before the branch. Those loops
are **skipped by name** (30 of them). Consequence, stated up front: **a light
that casts no shadow map does not glow the ear.** Fixing that means computing
the spot factor a second time before the branch; not built (§10).

Census on the 77 (gate 4, identical for the three glow rungs):

| class | modules | sites |
|---|---|---|
| shadowed loops, spliced | **60** | **102** (3 queries each) |
| unshadowed loops, skipped by name | 30 loops (in those same modules and others) | 0 |
| sun-only (no light loop) → identity, no marker | 15 | 0 |
| declined by name (`ab0bc2fee876d489`, `99bb7c2698997b2a` — no P chain, `103`'s two) | 2 | 0 |

So 17 compute modules are byte-identical to the base in every rung.

## 3. The splice, instruction by instruction (site 1 of `126aff4093652bf5`, shipped bytes)

Per site: **117 instructions**, all straight-line, in the block that ends with
the engine's gate. Hoisted once per module: three `OpVariable %rq` (A/B/C),
three `Private float` accumulators stored `0` at entry, the `103` slot pointer
→ magic test `ok` (`%263`) → `OpConvertUToAccelerationStructureKHR` (`%269`).

```
%1383 = OpIEqual %413 %92            ; class == 1      (gbuf.y >> 5, acquire_class_shift)
%1384 = OpFOrdGreaterThan %1345 0    ; atten > 0       (%1345 = the engine's atten phi)
%1385 = OpLogicalAnd %1383 %263      ; ∧ slot magic ok
%1386 = OpLogicalAnd %1385 %1384
%1387 = OpSelect %1386 255 0         ; cull mask
%1388..%1390 = OpFSub P_c − C_c      ; P − C  (emit_world_pos(relative_to_camera=True), 99 sec 10.6)
%1391 = OpCompositeConstruct         ; pos
%1392 = OpBitwiseAnd %1142 128 ; %1393 = INotEqual 0   ; directional?
%1395/%1397/%1399 = OpSelect isdir (−dir_c) (lightPos_c − P_c)   ; %1159.. are the ENGINE's own subs
%1400..%1407 : raw, dist = Sqrt(Dot), L = raw/dist
%1408..%1414 : (P−C) normalised                       ; query A direction
%1415..%1418 : b = NMax(d·0.001, 0.005); d−b, d+b
OpRayQueryInitializeKHR rqA %269 517 mask (0,0,0) d−b dirA d+b ; Proceed; type != 0 → hitA; InstanceId idA
OpRayQueryInitializeKHR rqB %269 545 mask pos 0.0015 L 0.018     ; Proceed; hitB; idB; t_B
%1428 = OpSelect hitB t_B 0.018      ; t
%1429 = OpIEqual idA idB             ; same instance
%1430 = t + 0.001 ; %1432/%1434/%1436 = pos + L·(t+push) ; %1437 = exit point
%1438..%1440 : tmaxC = Select(isdir, 100, NMax(dist − (t+push), 0.001))
OpRayQueryInitializeKHR rqC %269 517 mask exit 0.001 L tmaxC    ; Proceed; hitC
%1444..%1447 : accept = hitA ∧ hitB ∧ same ∧ ¬hitC
%1448 = N (the pixel's own decode) ; %1449 = Dot N L ; %1451 = NMax(−N·L, 0)
%1452 = × 7.2787 ; %1453 = × atten                  ; W·atten
%1454 = NMax(t, 0.006) ; %1455 = −t_eff
per channel c: Exp(−a1 t) + Exp(−a2 t) → × 0.5 → (× tint_c) → × W·atten → × colour_c → NMin 100 → Select(accept, ·, 0)
                → OpLoad gv_c ; OpFAdd ; OpStore gv_c
```

then the engine's own `OpSelectionMerge` / `OpBranchConditional` on `%1382`,
untouched. At the diffuse write (exactly the write index the Disney `c1`
scalars reach, `find_c1_sites` forward closure — index 0 in all 77 modules;
"first write" was never the rule) the stored vector's components become
`FAdd(comp_c, Load gv_c)`. Accumulating across the loop is what makes two
lights sum.

In `hit` mode the three stores are replaced by
`Select(class==1, Select(ok, Select(accept, BLUE, Select(hitA∧hitB∧same, AMBER, 0)), RED), 0)`
with BLUE `(0, 0.4, 3.2)`, AMBER `(3.2, 1.6, 0)`, RED `(3.2, 0, 0)`.

The normal: the default's compute half is `109`'s curv modules, which carry
**three** `normalize(fetch − 0.5)` decodes (the pixel's and two ±1-texel
taps). `patch_curv.find_normal_decode` dies on that ("3 normal decodes,
expected exactly 1" on all 77 — that is what killed build attempt 2).
`find_pixel_normal` enumerates them and keeps the one whose fetch coordinate
is the depth fetch's coordinate or a `%v2uint` construct of the pixel's
`coord_xy`; it must be unique.

## 4. What is deliberately NOT applied, and why

- **The engine's visibility masks** (shadow-map / RT-shadow phis multiplied into
  the gate product). A pixel on the far side of the ear from the light has
  `vis = 0` by construction — the light is behind the surface. Multiplying by
  it would zero the term exactly where it is meant to fire. Occlusion is
  handled by query C from the *exit* point instead, which is the physically
  right test.
- **The engine's N·L wrap / diffuse BRDF.** Replaced by the entry-face Lambert
  `max(−N·L, 0)` on the *back* face, as `111` §1 argued for the sun.
- **The spot cone.** It is *inside* `atten` (gate 2's product includes the
  spot factor computed at gate 1), so a spotlight pointing away from the head
  contributes 0. This is why the last gate, not the first, is the site.
- **The unshadowed loops.** §2.

## 5. Gates (`dev/build_earglow_di.sh`, all green, log verbatim)

```
0. base = the shipped default (its MANIFEST names r6lo.json)
1. 77 of 77 compute resolvers round-trip byte-identically (spirv-dis -> spirv-as)
2. k = 7.2787, tint = [1, 0.0293, 0.1279], rates R [865.4, 648.5]   (re-emitted, asserted against WANT_K)
3. each of di / hi / hit: 93 modules, 60 compute differ from the base, spirv-val (vulkan1.4) clean
   ctl: 0 differ.  di / hi / hit differ pairwise on exactly the 60 spliced modules
4. reports: 60 spliced, 102 sites, 30 unshadowed skipped, 15 sun-only + 2 declined identical, 49 distinct marker id pairs
5. shipped-byte census: 60 markers, 120 sentinel constants, 306 Initialize (102 x A/B/C), 306 Proceed,
   102 t reads, 204 InstanceId reads, 60 AS conversions; OpTraceRayKHR / OpImageWrite counts unchanged
6. earglow-di-ctl: 93 of 93 byte-identical to the base
7. verify_earglow_di.py: di (glow, k x 1), hi (glow, k x 2), hit (hit) -- 60 spliced, 102 sites, 17 identical;
   --negative on the base and on ctl: 77 modules, no marker, no sentinel, no ray query
8. 18 rejections (sec 6)
9. simulated layer fixup: both literals rewritten to 0x00007f1234567000 in 60 modules, re-validated clean
10. 4 MANIFESTs, provenance (src_ser="ser.set/class" ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71) carried verbatim
```

Line 1 of each rung MANIFEST is rewritten (`<rung> (BUILT ON <base> …)`,
`-ctl`: `ALIAS of <base>`); the first build inherited the base's "ALIAS of
earglow7-hue1" line and was rebuilt for that alone — same shas.

## 6. `verify_earglow_di.py` — what it re-derives from the `.spv`, and the 18 things it refuses

Per module: unmarked ⇒ byte-identical to the base *and* no ray-query op;
marked ⇒ `RayQueryKHR`/`PhysicalStorageBufferAddresses` capabilities, `103`'s
slot pointer idiom and the two sentinel literals named by the marker, then per
B-site (flags 545): A and C initialised in the same block; each query
Initialize → Proceed → committed-type getters on its own variable, **scoped to
the site's block** (a module-wide count let a 2-site module pass with the
wrong pairing — fixed); every constant (517/545, 1.5 mm, 18 mm, 1 mm, 5 mm,
0.001, 6 mm, 100), the mask gate shape, A's bracket, B's origin = the position
triple (`verify_wpos._check_position_triple`) minus the camera, C's origin = B's
origin + L·(t+push), C's tmax select; that the block ends with the engine's own
`> 0` gate, that `atten` is a factor of it and the *only* colour-dependent one;
the accept shape; the glow transfer (rates, tint, `k = k0 × --k-scale`, floor,
clamp against `--model`) or the hit palette; exactly one image write adds the
accumulators and it is the c1-reached write; raygens marker-free.

Refused (gate 8, each a full build of the decoy):

| decoy | what it drops |
|---|---|
| `nomarker` | the pointer with no `OpString` authorising the fixup |
| `badid` | a marker naming ids that do not exist |
| `scan` | a second, unnamed sentinel pair |
| `world` | raw world P as the origin (`99` §10.6) |
| `cullback` | query B at 529: reads the front wall, `t = tmin` |
| `noc` | no query C — `101` §15's glow-through-shade |
| `noa` | no instance match — `101` §13's collar/hair bleed |
| `flatk` | `T = 1`, thickness ignored |
| `spec` | the term added at the specular write |
| cross-reads | di as hit, hit as glow, di at k×2, hi at k×1 |
| base / ctl read as a rung; di read with `--negative` | |
| `bda-probe`, `bda-rq-probe` read as this rung | `103`'s marker without this splice |

## 7. Cost

Per pixel, per shadowed light, unconditionally: 117 ALU-class instructions plus
three inline ray queries. On non-skin and on lights with `atten = 0` the mask
is 0 and each query terminates at Initialize/Proceed; the ALU cost is paid
regardless (no branch was added — adding one inside the engine's structured
loop was judged not worth the anchor risk). Skin pixels under N shadowed
lights pay 3N real traversals, most of them ≤ 18 mm (B) or short (C).
`earglow-rq3` paid 3 queries per skin pixel *once* (sun only) with no reported
cost; this is that times the shadowed-light count. **Unmeasured.** If it is
felt, the first knob is a `dist · invRange` cut before the queries.

## 8. SETTINGS CONTRACT — state this BEFORE the launch (`103` §8, `111` §12)

| setting | value | why |
|---|---|---|
| `ser` | **`class`** | the rungs carry the base's SER-permutation raygens verbatim; `ser=off` → refused `gi-needs-ser` |
| `shadowset` | **`full-shadow`** | raygen-bearing rung; `gi_refuse` checks it |
| `ptq` | unchanged (`ptq_sha 55ed4e5c6884ab71`) | else `gi-stale-ptq` |
| RR / DLSS-D | **OFF** | |
| path tracing | ON, photo mode, camera pinned | |
| frame generation | **OFF — state it** | `100` §7 |
| skinspec | one of the four rungs | |
| the layer | **the rebuilt one** — `libVkLayer_callisto_spvswap.so` md5 `ab46f8cb0096db267a2469973676783a`, `cmp`-identical repo == `release/vulkan` == `~/.local/lib/callisto` as of this doc; carries the `bda_*` log events | without it every rung reads as the base (the layer would `bda_reject` → next overlay → base bytes) |

Deploy state at writing: `make release && make install` done; live CET
`init.lua` and `sync_settings.sh` `cmp` == release; the four rungs parked in
`~/.local/lib/callisto/skin.set/<rung>/` 93/93 `cmp` against the build,
`MANIFEST.txt` identical.

**Order:**

1. **`bda-probe` first** (built on the `-glintdense` bytes, so its *skin*
   looks like `100`, not like the default — read the GREEN/RED, not the skin).
   `103` §9 rows 1–3. Grep the log: `"ev":"bda","action":"armed"`,
   ≥1 `bda_fixup`, `bda_tlas` with `prims` in the tens of thousands, **no**
   `bda_reject`. If any of those fail, stop — nothing below means anything.
2. `earglow-di-hit` — the per-light paint. `bda_summary` at exit should show
   `fixups` = 60 × (number of times the game created those modules); `103`
   expected 76 for its 76 marked modules, so the ratio is what to check.
3. `earglow-di`, then `earglow-di-ctl` on the identical frame. Read
   `status.txt` after each: `want_skinspec=<rung>` (not `off:gi-*`),
   `want_ser=class:in-skin`.
4. `earglow-di-hi` only if `di` reads as "there but faint".

**The frame:** night or interior. A head with an ear between the camera and a
**shadow-casting** local light (a street lamp, a neon sign, a car headlight,
an interior spot) — the light *behind* the head from the camera's view, within
its range. Sun absent or low, so the raygen's own ear glow does not confound.
Then the same frame with the ear *facing* the light (nothing should be added:
`−N·L < 0`), and one with a hand or collar between the ear and the light
(query C should kill it).

## 9. Pre-registered interpretation (written BEFORE any screen)

| # | reading | means | do |
|---|---|---|---|
| 1 | `-hit`: skin **BLUE** on the far-side ear rim / nostril / thin skin, **black** on the lit face | the whole chain works: slot, TLAS, instance match, thickness, exit visibility | shoot `di` |
| 2 | `-hit`: **AMBER** on the far-side ear | thickness ok, exit point cannot see the light: a second occluder, or the exit point is inside the head (t too short) | compare with the same pose on `bda-rq-probe`; if amber persists on an open ear, push > 1 mm is the first knob |
| 3 | `-hit`: **RED** anywhere on skin | slot magic wrong — the layer did not arm, or armed a stale slot | grep `bda` lines; `103` §9 row 2 |
| 4 | `-hit`: **all black** with `bda-probe` green | no shadowed light reaches the pixel with `atten > 0`, or the scene's lights are all in the UNSHADOWED loops | try a different light source (a spot with a visible shadow); if still black, §10's first item is the fix |
| 5 | `di`: a red-orange rim on the far ear that `ctl` lacks, hue like `earglow7-hue1`'s sun glow | **the feature works** | user verdict; consider making it default |
| 6 | `di`: glow on the lit face too | `−N·L` sign wrong at that site (N points the wrong way) — would also show in `-hit` as blue on the lit face | compare `-hit`; if blue there, the normal decode picked a tap, not the pixel |
| 7 | `di`: glow through a hand/collar | query C failed — `101` §15's defect returned | `-hit` should show amber there; if it shows blue, C's tmax is wrong |
| 8 | `di` == `ctl` with `-hit` blue | the accumulator is not reaching the write, or the write index is wrong for that module | `verify` says it is index 0; check the *pipeline* — is the diffuse write the one composited? |
| 9 | crash/hang on `di` not `ctl` | a bad fixed-up address, as `103` §9 row 9 | `CALLISTO_BDA_DISABLE=1` reproduces the base; log |

Void: no `skin_sha` line, `skin_sha` ≠ the rung's sha, `status.txt` reads
`off:gi-*`, or any `bda_reject` — as `103` §9 V1–V3.

## 10. NOT done

- **Unshadowed loops (30).** Lights without a shadow map contribute nothing.
  Needs the spot factor recomputed before gate 1; ~30 more instructions/site.
- **No `dist · invRange` cut** before the queries — cost is paid for every
  record the cluster hands the pixel.
- **No driver self-test** (`dev/selftest_bda.sh` pattern). `spirv-val` on
  every rung, and `103`'s 54/54 self-test already exercised the identical
  slot/query idiom on this driver; a second one for the glow arithmetic was
  judged not worth the hour. `111` §11's argument applies.
- **`bda-probe` is still built on the `-glintdense` base**, not the default.
  Rebuilding it on the default (`build_bda.sh` with the new BASE) would give a
  same-skin control; the mechanism it tests is base-independent.
- **The 111 §13 amendment is one line.** Route (a) should be struck; it is
  marked, not deleted.
- **Cost is unmeasured.**
- **Nothing committed.**

## 11. Files

| file | lines | what |
|---|---|---|
| `dev/patch_earglow_di.py` | 780 | patcher: `find_light_sites`, `find_pixel_normal`, `diffuse_write`, `build`, `process`, `census`; `--mode glow\|hit\|ctl --k-scale --decoy` |
| `dev/verify_earglow_di.py` | 620 | §6; `<dir> --base --model --mode [--k-scale]` or `--negative <dir>` |
| `dev/build_earglow_di.sh` | 482 | §5; `--install` parks with `.earglow-di-owned` |
| `dev/disasm/earglow_di/{asm,model,swaps.*}` | | provenance disasm of the default, `r6lo.json`, per-rung asm + reports |
| `swaps.earglow-di{,-hi,-hit,-ctl}/` | | the shipped bytes, `MANIFEST.txt`, `*.earglow_di.report.json` |
| `init.lua` | | four rows after the DEFAULT row, comment block pointing here; the duplicate `bda-*` rows this session first added were removed — the originals further down the same table stand |
| `handoff/111` §13 | | one-line amendment |

No shared patcher was edited. `patch_bda.py`, `wpos_core.py`,
`patch_compute_skin.py`, `patch_earglow7.py`, `patch_shadow_brdf.py`,
`patch_compute_brdf.py` are imported, not changed.

## 12. SHOT 2026-09-03 21:13–21:28 — `earglow-di` shows nothing, and the indoor `bda-probe` frame says why

Two launches, both live read-outs plus photo-mode PNGs (2560×1440, in the
Proton prefix's `Pictures/Cyberpunk 2077/`): `earglow-di` (pid 1115399,
`photomode_03092026_211300/211521.png` — Judy in a stairwell, a fluorescent
tube above/behind, a blue source left) then `bda-probe` (pid 1122072,
`…_212706.png` unlit room, `…_212855.png` the same room lit). Settings served
per `status.txt`: `ser=class:in-skin`, `shadowset=full-shadow`, `ptq=rcbm`,
`failed=0`. **Frame generation / RR state not stated by the user.**

**Log, both runs — every `103` §8 precondition green:** `bda armed` at
`0x4720000`, `bda_fixup` (log capped at 8 lines by `BDA_MAX_FIXUP_LINES`),
109 swap HITs = 77 resolvers + 10 shadow + 15 raygen + 3 refl + 4 gi, **zero
`bda_reject`**, `bda_tlas` `prims:0` then `prims:54869` (the real TLAS won).
All 77 resolvers appear in `cpipe` (built as compute pipelines — `103`'s hole
4 is closed on the mechanism side) and 19 of them show a `dispatch`
(dedup-per-pipeline, indirect group counts), so they ran.

**USER, verbatim:** *"I saw nothing different in the earglow-di launch.
bda-probe makes the skin look black? Or deep red?"* — **Neither.** Pixel
samples (9×9 means): the lit `bda-probe` frame's cheek is R 179 / G 149 /
B 129, R/G 1.21 — ordinary skin; a green or red paint (×3 on one channel,
×0.15 on the others) would put R/G near 0.05 or 20. The unlit frame's skin
is R 8 / G 37 / B 42: the room's blue source, nothing else.

**Reading: `103` §9 row 3, "unchanged", and the frame violated `103` §8's
spec (face in DIRECT sun).** The probe's paint is a *multiply* on the
resolver's radiance texel under the class-1 gate `99` proved fires in sun.
Skin under a room's local light took no tint at all, so **the 77 resolvers'
painted writes contribute ~nothing to skin lit only by local lights under
path tracing.** The raygens, checked afterwards (`dev/disasm/earglow7/asm`),
each carry **13 `OpRawAccessChainNV` walks of the same 128-byte light records
and 12 `OpTraceRayKHR`** — the path tracer does its own light sampling. So the
premise in §0 ("local lighting on skin is shaded in the 77 resolvers") was
read off the disassembly, not the screen, and the screen says the resolvers'
local-light loop is not what lights a PT face. **`earglow-di` showing nothing
is expected regardless of whether the term is correct**, and `-hit` would
paint nothing either. This does not touch the term's arithmetic, the BDA
mechanism, or the gates; it says the *site* is in the wrong pass for PT.

**What settles what, next:**

| launch | frame | answers |
|---|---|---|
| `bda-probe` | face in **direct sun** (`103` §8) | the Stage 2b mechanism, GREEN/RED — still unread; every BDA-based feature needs it |
| `hunt-paint` | the 21:28 room, same pose | the pre-registered row-3 control: confirms the resolvers write nothing to skin under local light (expected: unpainted) |
| `earglow-di-hit` | — | **do not shoot** until the site moves |

**Where the feature has to go:** the raygen's light-record walk — `111` §13's
route (a) after all, but at the NEE sample, where the sampled light's colour
and direction are live, not at the payload. Unbuilt.

**Addendum 21:38 — `bda-probe` in direct sun is GREEN** (`103` §12,
`a-b-testing/bda/probe-sun-213804.png`; user verbatim *"green skin in
sunlight"*). The mechanism every rung here rests on is proven in the game.
The verdict on this feature stands: green skin in sun plus unpainted skin
under local light says the resolver write carries sun + sky but not local
light under PT. The term moves to the raygen's light sampling. Row 1 of the
table above is done; `hunt-paint` indoors is now optional confirmation only.

**Addendum 22:13 — rebuilt at the raygen's light-sample site: `113`
(`earglow-ll`).** This document's rungs stay parked as the negative reference.
The selector rows for `earglow-di*` had been added to the release copy of
`init.lua` only and were overwritten by `make release`; they are now in the
source `init.lua` next to the `earglow-ll*` rows.
