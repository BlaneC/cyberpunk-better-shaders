# 43 — Code review, cleanup, and a second pass over the `38` ideas table

> **2026-08-30 (44):** M2, M3, M4, M5, M6 are **built and parked** as
> optional features (`44` §1); M7 is dead (`+2` is the normal, `44` §2.4);
> M1 and the DLSS preset test are protocol steps in `45` (E10). The order
> below is superseded by `45` §3.

Written 2026-08-30. Review only plus the cleanups listed in §1; **nothing
here was launched**. `38` is left as written; this document corrects and
re-orders it and adds what it was missing.

## 1. What changed in the repo (this session)

| change | why | where |
|---|---|---|
| `skinray` removed (switch, key, ptq `skin/` half, SER check) | sampling-only by `00` §2's own argument, so it could never change a pixel; it cost half the ptq matrix and a SER-staleness trap | `init.lua`, `sync_settings.sh`, `dev/build_ptq.sh`, `dev/patch_ser.sh` |
| `tier` is now a real master switch | off used to leave `swaps.skin/` and `swaps.shadowcull/` serving, so "Callisto BRDF off" was not the vanilla baseline its tooltip promised | `sync_settings.sh` |
| Six numeric sliders + `regen_and_clear.sh` deleted | inert since `26` §5; the script had hardcoded `/mnt/...` paths | `init.lua` |
| Stale-rung fixes | `swaps.ser/` and `swaps.skin/` are now emptied *before* the rung dir is tested, so a missing rung can never leave the previous launch's files being served under the new name | `sync_settings.sh` |
| CET warnings are a list | the silent no-ops stack; showing only the first hid the rest | `init.lua` `warnLines()` |
| Layer: lazy sha256, checked `fseek`/`ftell` | ~3300 hashes per launch were computed and then discarded | `swap_layer.c` |
| `Makefile` (`layer`, `release`, `check`) | root Lua/kernel/.so were hand-copied into `release/` | root |
| `dev/retired/` (13 scripts + index) | half of `dev/` was done or falsified | `dev/retired/README.md` |
| `handoff/CURRENT.md` | the README was a 60-line paragraph | |
| `.gitignore`: `swaps.*/`, `*.bak_*` | untracked overlays and backups at root | |

Still open from the review, not done: `patch_chs_brdf.py` / `patch_compute_brdf.py`
are imported by nine and eight patchers respectively as *libraries* while also
being retired *programs*; a `dev/spv/` package (`load`, `assemble`, `validate`,
`readback_diff`, CFG/dominators from `patch_shadow_brdf.py`) is the right shape
and was not attempted here. `dev/README.md` and `release/README.md` still
describe the raygen era in places.

## 2. Corrections to `38`

**Stale gates.** A1 (`41`) and G-U4/A2 (`40`) are built, and `42` found the
whole skin BRDF never reached the GI resolvers. `38` §7's table should read:
G-U4 and G-A1 *launch-pending*; and **`42`'s fix goes first**, because a large
share of "faces read soft" may simply have been bounce-lit skin carrying none
of the mod.

**0d — the 720p ceiling is a DLSS preset, not an engine constant.**
1280×720 → 2560×1440 is DLSS Performance. Quality resolves at 1707×960, DLAA
at native. `38` treats the resolve resolution as structural and derives a
design rule (multiplicative only) from it. The rule is sound *at a given
preset*, but the preset is the single cheapest face-sharpness lever in the
whole document, and SER/`ptreg` exist to buy back exactly that frame time.
Before assuming anything additive is doomed, check whether the 40×23 tile list
scales with internal resolution.

**A1 — expect a few percent, not 2×.** `41` already says it: a bare
`OpReorderThreadWithHintNV` keyed on the *primary* class reorders threads
that are already spatially coherent. The published gains come from reordering
on the *hit* (`OpHitObjectTraceRayNV` → reorder → `OpHitObjectExecuteShaderNV`),
which is a trace conversion, not a three-instruction splice. Still worth the
launch — it is free — but size the expectation.

**A7 — double-counts.** Penner's pre-integrated skin *substitutes* for SSS
blur; the engine already runs screen-space SSS with the kernel this mod owns.
Keep only the shadow-edge colour-bleed half, or drop A7.

**A6 — the citation is unverifiable** (`arXiv 2606.27604`). The idea stands
without it: Donner & Jensen's three-layer profile gives per-channel mean free
paths directly, and the kernel is a 32×8 upload already authored offline.
Ship as a rung, never a default flip, as `38` says.

**A8 — hashing `ObjectID` to a film thickness is noise per object.** The
plausible version is view-dependent, subtle, gated on `metallic > 0.9 &&
alpha < 0.1`, and it needs a class/subtype hunt first to learn what class 5 is.

**B5 — is a texture-pack problem.** Pore-scale detail at the G-buffer fill
means detail normals and higher-resolution maps, i.e. WolvenKit, not a
shader splice. Say so and stop listing it under shader work.

**C1 / D1 — agree with the doc's own demotion, and go further.** For skin the
lobe is not the bottleneck; the *inputs* (thickness, curvature) are. A learned
lobe over the same three inputs cannot beat a well-tuned analytic one by
enough to justify a CoopVec bring-up under vkd3d-proton.

**D6 — check Ray Reconstruction first.** `pics/example_before_and_after_dlss_5/`
suggests DLSS 5 RR is in use; if so the entire 22-CVar NRD panel is bypassed
(`33` §3 says this too). One graphics-menu check before any time is spent.

## 3. What `38` is missing

### M1 — The denoiser sees vanilla roughness *(probably the most important item)*

Ray Reconstruction / NRD denoise specular using roughness and material inputs
taken from the **G-buffer**. Every roughness edit this mod makes — the
`skinspec` cap, the scoped roughness scale — lives in the *resolve*. The
denoiser therefore still treats the highlight as roughness-0.5 skin and
spatially smears exactly the tight highlight the cap produced. That is a
mechanical reason the gloss "reads soft" independent of everything in `33`.

Two routes: (a) apply the same alpha rewrite where the denoiser reads
roughness — find RR's guide buffer / NRD's `roughness` input in the dump and
cap it in that producer too; (b) do the roughness edit at the G-buffer write
(U2), which is the only place a roughness change is *consistent* across
resolve and denoiser. This reframes U2: it is not just Tier B's prerequisite,
it is the only route to a specular edit the denoiser agrees with.

*Falsifier:* RR off, NRD on, same cap → if the highlight sharpens, M1 is
confirmed and the cap was never given a fair test.

### M2 — Roughness *scale*, not cap (`33` §5)

Scoped, one rewrite at the `build_skin_alpha_cap` site, `k > 1` goes rougher
than vanilla, which the cap can never do. Cheapest "less plastic" knob on the
list and the direct answer to the original complaint. Should be A0.

### M3 — Sun angular diameter

Face realism lives in the terminator and the penumbra. `pt_engine.lua` lists no
sun-disk CVar; if the PT's sun angular radius is an `OpConstant` in the shadow
raygens it is a one-constant splice with a large visible effect on every
outdoor face. Find it before building anything else in Tier A.

### M4 — Diffuse/specular energy coupling

MS-GGX (`28`) fixed the specular side. The diffuse counterpart —
Kulla-Conty's `(1 − F_avg)` scaling of the diffuse lobe — is ~5 instructions
at the same Schlick sites and fixes over-bright grazing skin that `c1`'s
diffuse Fresnel is currently approximating from the other direction.

### M5 — Micro-shadowing from albedo

The Uncharted 4 / Frostbite trick: pores are dark in base colour, so
`NoL *= saturate(1 − (1 − NoL)² · k · (1 − lum(albedo)))`. Multiplicative, so
it *inherits* the 720p quantisation rather than introducing it — precisely
`0d`'s criterion — and albedo is already fetched at `registers[1]+1`.

### M6 — Eyes first, not last

`31` is fully scoped, class 8 is proven on screen, the splice is the existing
gloss machinery retargeted, and eyes are the highest-value per-pixel real
estate for "look like real people". Promote above most of Tier A.

### M7 — Read the hair direction channel offline (G-B1)

An afternoon of disassembly decides whether 70 modules of hair work were
wrong-*input* rather than wrong-idea. Nothing hair-related should be built
before it, and nothing else on the list is this cheap per bit of information.

## 4. Order

1. Launch `42` (bounce-lit skin) — on screen.
2. M2 roughness scale — one rewrite, one launch.
3. M1 — RR off / NRD on control; then find the roughness guide.
4. DLSS preset test — Quality/DLAA at the same scene, same save.
5. `40` sub-enum + sheen probe — one launch.
6. `41` SER — frame time.
7. M6 eyes.
8. M7 hair direction — offline.
9. M3, M4, M5 — one splice each, all at sites the patcher already anchors.
