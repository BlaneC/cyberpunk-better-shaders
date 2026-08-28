# 15 — The render graph, from capture provenance (offline)

Written 2026-08-27, after `14-PROVENANCE.md`. It **replaces `14` §4's plan**
(port descriptor provenance into `swap_layer.c`, then a live launch) — that
work is unnecessary. It also **corrects `13`'s architecture** and **falsifies
`13` §5's hypothesis** about where the interior-hair evaluator hides.

Everything below came from one offline command. No game launch, no new layer
code, no live hooks.

---

## 0. The headline: `14` §2.4 is wrong

`14` §2.4 recorded "**ngfx-replay segfaults on this machine → offline replay
augmentation is not available**" and built the whole `14` §4 plan around that
constraint. The segfault is real, is **not** a machine defect, and was
diagnosed and solved by this project on 2026-08-24. The fix is written down in
`../analysis/HANDOFF.md` §8.6:

> `NGFXPROBE_STRIP_ALLOC=3` (strips DEDICATED+OPAQUE_CAPTURE_ADDRESS alloc
> pNexts — vanilla replay otherwise SIGSEGVs in libnvidia-glcore at a
> fixed-VA dedicated alloc)

The strip is implemented **inside the probe layer** (`probe_layer.c:842`), so
replaying *without* the probe layer segfaults too — which is exactly the
"nolayer" control in `capA_replay_nolayer.txt` that made it look like the
replayer itself was broken. It is not. Reproduced today, both ways.

**The working command** (also the docstring of `dev/prov_map.py`):

```sh
cd GraphicsCaptures
CALLISTO_LAYER_DISABLE=1 NGFXPROBE_STRIP_ALLOC=3 \
NGFXPROBE_LOG=$PWD/analysis/evidence/meta/capA_prov.jsonl \
NGFX_PROV=1 NGFX_PROV_ONLY=1 \
/opt/nvidia/nsight-graphics-for-linux/nsight-graphics-for-linux-2026.3.1.0/\
host/linux-desktop-nomad-x64/ngfx-replay \
  --present-hidden -n 1 --quiet --no-multithreaded-init \
  GameThread_2026_08_23_22_24_36.ngfx-capture
```

Runtime ~3 min. Output: **2920 `prov` events over 114 compute pipelines**,
`analysis/evidence/meta/capA_prov.jsonl` (6.5 MB, committed as evidence).
Zero payload collisions — every `(pipe, pc, idx, stride)` slot resolved to
exactly one image view, so the slot→image map is unambiguous.

`CALLISTO_LAYER_DISABLE=1` keeps the swap layer out of the replay so no
patched module perturbs the graph.

**Do not** add the `14` §4 hooks to `swap_layer.c`. Nothing needs them.

## 1. `6ac9085c9bd4b7da` — its actual inputs and outputs

Slot arithmetic read off `dev/disasm/compute/6ac9085c9bd4b7da.dxil.spvasm`
lines 119–146, matched against the prov events. In the capA frame
`pc[1] = 52007`, `pc[5] = 52015` (`14` §1's `0xcb26/0xcb2e` were one low).

| SPIR-V | slot | heap idx | image | size / format | usage |
|---|---|---|---|---|---|
| `%63` sampled (`%179`, `%206` taps) | `heap14[pc1+0]` | 52007 | `0x1c8282d0` | **1280×720 R16G16B16A16_SFLOAT** | 31 |
| `%59` fetched (`%196`) + 4 offset taps | `heap14[pc1+1]` | 52008 | `0x1c835940` | **2560×1440 R16G16B16A16_SFLOAT** | 31 |
| `%54` velocity (`%159`) | `heap14[pc1+5]` | 52012 | `0x1c850420` | **1280×720 R16G16B16A16_SFLOAT** | 23 |
| `%48` material `v4uint` (`%135`) | `heap18[pc1+6]` | 52013 | `0x1c84bd60` | **1280×720 D32_SFLOAT_S8_UINT** | 39 |
| `%40` **output** (`OpImageWrite`) | `heap22[pc5+0]` | 52015 | `0x1c81eb30` | **2560×1440 R16G16B16A16_SFLOAT** | 31 |

Evidence (verbatim from the analysis over `capA_prov.jsonl`):

```
  pc=1 idx=52007 stride=16 type=2 img=0x1c8282d0 fmt=97 1280x720  usage=31
  pc=1 idx=52008 stride=16 type=2 img=0x1c835940 fmt=97 2560x1440 usage=31
  pc=1 idx=52012 stride=16 type=2 img=0x1c850420 fmt=97 1280x720  usage=23
  pc=1 idx=52013 stride=16 type=2 img=0x1c84bd60 fmt=130 1280x720 usage=39
  pc=5 idx=52015 stride=16 type=3 img=0x1c81eb30 fmt=97 2560x1440 usage=31
```

Three corrections to `13` §3 follow:

1. **6ac9 runs at output resolution (2560×1440), not render resolution.**
   It writes at raw `gl_GlobalInvocationID` (`%144`, `%278`) into a 1440p
   image. The game renders at **1280×720** internally (2560×1440 with a 2×
   upscaler); the material fetch is scaled into the 720p buffer by `cbv[79].xy`
   (`%130`/`%131`) — that is what the scale factor is *for*.
2. **The material word 6ac9 gates on is the stencil of the 720p depth-stencil
   buffer** (`D32_SFLOAT_S8_UINT`, usage 39 = TRANSFER_SRC|DST|SAMPLED|
   DEPTH_STENCIL_ATTACHMENT), not the G-buffer material RT the evaluators read.
   The class-4 gate still works — it is the same packing — but it is read at
   half resolution and point-scaled, so 6ac9's class paint is 2×2-blocky at
   1440p, not truly per-pixel.
3. **It is not a reprojecting TAA.** `%179` samples `%63` at the *un-offset*
   UV; the ±0.2/±0.4 velocity offsets (`%201`–`%241`) are applied to `%59`, the
   same image `%196` point-fetches. Four motion-direction taps blended into a
   point sample of the same buffer is **directional smear (motion blur) /
   late-frame AA**, not a history resolve. `13` §3's "history sampled at the
   reprojected UV" is the wrong way round.

**Nothing in the compute set writes `0x1c835940`** (6ac9's 1440p input).
114 compute pipelines: three *read* it (`dd1d562e6c883c3c`,
`1a086cfc67bb848c`, `6ac9085c9bd4b7da`), none holds a storage handle. It is a
graphics-pass render target or a copy destination. The 720p input
`0x1c8282d0` has **exactly one** compute writer, `9929ec8dce30f765`.

So `13`'s diagram — *tile evaluators → 6ac9 → screen* — has the endpoints
right and the middle wrong. 6ac9 sits **after the upscale**, downstream of at
least one stage nothing in the compute set produces. It owns hair's final
pixels the way the last `OpImageWrite` in any chain owns everything: truly,
and without telling you where hair was lit.

## 2. The lighting families (the part that was actually wanted)

Working *forward* from the four modules proven on screen to shade hair
(`13` §2 bisection) is far more direct than working back from 6ac9. All four
write the same two storage slots:

```
03dc7a51279e7427   pc=5 idx=83557 img=0x19b9cc50 1280x720 fmt=97 usage=31
03dc7a51279e7427   pc=5 idx=83558 img=0x1c854e90 1280x720 fmt=97 usage=31
d5166c0f1ea464b9   pc=5 idx=83557 / 83558   (same two images)
7ae88cd87950a898   pc=5 idx=83557 / 83558   (same two images)
4d46848998312027   pc=5 idx=83557 / 83558   (same two images)
```

(`4a8efc3f674e9c35` holds **no** storage slot at all — `13` §2 round 4's
"skin–hair boundary tiles" attribution belongs to `4d46` alone.)

Asking who else writes `0x19b9cc50` / `0x1c854e90` names the family exactly:

### Family A — direct lighting, 1280×720 RGBA16F ×2 — **9 modules**

```
03dc7a51279e7427 *  0e5e5a6a78fdf1dd    20e6c7b3626ae0d6    2e73a32c35778d85
4d46848998312027 *  7ae88cd87950a898 *  81c13c37112d09df    9a3fa53c53a3a21b
d5166c0f1ea464b9 *
                                        (* = proven on screen to shade hair)
```

Nine permutations, identical slot layout — the tile-classified direct-light
evaluator. `0x1c854e90` has one compute reader (`3e02d1116b61abbe`);
`0x19b9cc50` has none, so its consumer is on the graphics side.

**All nine were already in the 29-module hunt net** (`swaps.huntall/`) — every
one installed, dispatched, and palette-patched during `13`'s bisection. There
is no unfound direct-light hair evaluator. `13` §5's hypothesis is dead for
family A.

The other three families are where it went.

### Family B — GI / ReSTIR, 1280×720 — 8 modules — **7 of 8 unpatched**

Writes `0x15b1ed30` (R16G16_SFLOAT), `0x15b1d030` (R16G16_SINT — reservoir
indices), `0x15b14c00` (RGBA16F radiance).

```
1ecc0c405786e1e3    23bb4979d6edc2fd    66d2f831627dc8cd    9112430b0c381450
99bb7c2698997b2a #  afe73b89b1f04f6d    ce2a6197bd23b33c    d48dd37d800deb46
                                                    (# = in the hunt net)
```

### Family C — 1280×720 RGBA16F ×2 — 5 modules — **4 of 5 unpatched**

Writes `0x15b434a0`, `0x15b3faa0`.

```
1921a49565aad925    705c012dd38f55d9    a5f4a903683893b4 #  f209f068dc4a55bc
f9a666709dbbfbbe
```

### Family D — quarter-res 640×360 RGBA16F — 9 modules — **0 of 9 patched**

Writes `0x19bad070`.

```
204eaf5b16ecff04    384aa95441751429    5f0de0f55d67c607    6e91dc5e05af59b3
84ea63ad0fdedb95    85119cfcee1a8646    9731d633b09c6b01    ac38cf69e12c1c15
cbaeaa8ce898b20d
```

Reproduce any of this with `dev/prov_map.py` (`--module ID`, `--image 0x…`,
or bare for the whole graph).

## 3. Where interior hair is lit

Direct lighting (family A) is fully covered and paints only the **sunlit rim**
and **skin-boundary tiles** — consistent with every screenshot in `11` and
`13`. Interior/shadowed hair therefore gets its light from **indirect**, i.e.
family B and/or family D, of which **21 of 22 modules have never been
patched**.

This turns `13` §5's "one of the 149 unpatchable hunt failures" into a named
list of **22 candidates**, and the hunt does not need a class read to
discriminate them: these are tile/permutation dispatches, so **dispatch is the
gate** (`14` §5). An *unconditional* output tint in one of them paints exactly
the pixels it was dispatched for. That removes the very requirement
(`acquire_class_shift`, `patch_compute_hair.py:923`) that made all 149 fail.
A `hunttint` tier — `build_hunt_writes` with the palette/gate machinery
deleted, one constant multiply per `OpImageWrite` — is ~25 lines, and 22
candidates bisect in ~5 launches.

## 4. What a hair-BRDF splice in these evaluators requires

Unchanged from `11` §2 in kind, and worse in degree now that the resolution is
known:

- **No tangent, no UV, no material texture** in any of these — the G-buffer
  they read (`11` §2 table: depth, albedo, normal, misc, material) has no
  strand direction and **no free channel** to carry one. Cards or strands, the
  deferred evaluator cannot know where on the hair a pixel sits.
- **They write at 1280×720**, and `6ac9` then upscales to 1440p *and* smears
  along velocity (§1). A hair specular is the highest-frequency feature on the
  character; that path is actively hostile to it. Any highlight authored in an
  evaluator arrives on screen half-res, tile-quantised (8px, visible in
  `photomode_26082026_223354.png`), and motion-smeared.
- Family B is a **ReSTIR reservoir** stage (R16G16_SINT indices). Splicing a
  BRDF into a reservoir update is not the same operation as splicing into a
  lighting eval and should not be attempted before the family's own disasm is
  read.

The one delivery route that survives is still `11` §3 Route 1 (write a strand
direction from the hair **fragment** shader, read it in the evaluators), and it
still needs the graphics-side dispatch tooling from `11` §5 — which the same
replay can now supply offline, since the capture holds `CreateGraphicsPipeline`
events (118 in capA) alongside everything else.

## 5. Open, and what did not change

- The rim-three Phase 0 `spec_add=8` probe (`11` §6, staged in
  `~/.local/lib/callisto/swaps.hair/`) has still **never run at a valid
  scene** — both attempts were at Panam, out of scope (`12` §1). It remains the
  cheapest falsification of the whole splice mechanism and is still pending.
- Caveat on scope: capA is the **2026-08-23 22:24 frame**, a different scene
  from `13`'s Panam bisection. Module identities are stable across both (all
  nine family-A modules and 6ac9 appear in each), so the *topology* transfers;
  **heap indices and push-constant values do not** — re-derive them per capture.
- capA is also pre-2.x-patch relative to nothing in particular, but it predates
  the `12` §3 patcher changes. It is a vanilla frame: that is the point.

## 6. New/changed files

- `dev/prov_map.py` — render-graph builder over a prov log (replaces
  `dev/prov_analyze.py`, which hard-codes 6ac9 and joins fnv→id by scanning
  `~/callisto_dump`; `prov_map.py` does the same join but generalises the query).
- `analysis/evidence/meta/capA_prov.jsonl` — the 2920-event prov log.
- No changes to `swap_layer.c`. `14` §4 is withdrawn.

## 7. Built since: the unconditional-tint net

`3` proposed a `hunttint` tier; it exists now.

- `dev/patch_compute_hair.py --tier hunttint --tint R,G,B` — unconditional
  constant multiply at every reconstructable image write. No class read, no
  dominance test, so it patches the tile-permutation modules the palette tier
  rejects.
- `dev/build_tintnet.sh [B|C|D|all]` → `swaps.tintall/`.
- `dev/bisect_tint.sh all|A|B|range LO HI|one ID|fam B|C|D|list|off` — installs
  into the same `swaps.hair` overlay slot `bisect_hunt.sh` uses.

**Result of the build: 15 of the 22 candidates patched clean (spirv-val 15/15);
7 refused, correctly.** Those 7 write integers or buffers, not radiance:

| module | why refused |
|---|---|
| `1ecc0c405786e1e3` | writes `v4uint` to a `Buffer` image (reservoir packing) |
| `5f0de0f55d67c607` | `OpCompositeConstruct %v4uint` texel |
| `6e91dc5e05af59b3` | 4 writes, all `%v4uint` constants (counters/flags) |
| `9112430b0c381450`, `f209f068dc4a55bc` | no `OpImageWrite` at all |
| `f9a666709dbbfbbe`, `84ea63ad0fdedb95` | no `OpImageWrite`; only `OpStore` (structured buffers) |

So the radiance-writing candidate set for interior hair is **15 modules**, and
that is what bisects. Their type-3 prov entries are storage handles they hold,
not colour they write.

Expect broad tinting wherever a module runs — these carry no class gate. The
question each round answers is only whether **interior (shadowed) hair**
reddens.
