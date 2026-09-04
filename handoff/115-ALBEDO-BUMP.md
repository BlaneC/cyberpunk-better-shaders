# 115 — Albedo-derived micro-normal on skin (`bump`)

**Status 2026-09-04: SHOT, KEPT AND MADE THE DEFAULT (§11). User verbatim:
*"The bump option was the best thing I've tested so far. IT LOOKS
INCREDIBLE."* Built, gated (gates 0–10), verified from shipped bytes (13
decoys rejected), parked, installed. Live read-out only, no capture.**

| Rung | What | Bytes |
|---|---|---|
| `bump` | H = 10 mm per unit luma | 75 of 77 compute modules differ from the default; 16 of 16 raygens verbatim |
| `bump-hi` | H = 20 mm | same coverage, twice the relief |
| `bump-vis` | diagnostic: tilt magnitude painted on skin | 150 of 150 radiance writes class-gated, non-skin slice identical to base |
| `bump-ctl` | H = 0 | 93 of 93 `cmp`-identical to the default, non-tautologically |
| `…-curv-t7hue1-ll-bump` | the previous default + `bump`, under the stack name — **THE DEFAULT** | content sha `241bb736f0ed93b6`, 93/93 = `skin.set/bump` |

Base: `gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll`
(content `076f3108e312ef4f`, the previous default, `113` §11; = `bump-ctl` by bytes). Provenance
(`src_ser` / `ser_sha` / `ptq_sha`) carried on every MANIFEST, so
`sync_settings.sh` serves the rungs (the `110`/`105` blank-launch trap).

## 0. What it is, in one paragraph

Pores are not in the BVH and never will be (`33`, `38` §0d), so no ray
budget creates a pore micro-shadow. But the skin albedo already carries the
pores — the texture artist painted them dark — and the shipped
micro-shadowing (`44` §3.4) reads that darkness as a scalar occlusion. This
reads its **gradient as geometry**: a height field `h = H · L(albedo)`,
darker = deeper, whose tangential slope tilts the shading normal,

    N' = normalize( N − H · ∇ₜ L )

and every consumer of N — the diffuse N·L, the specular N·H and N·V, the c1
lobes, the terminator bleed's NoL — sees the pore as a dent: darker on its
lit rim, brighter on its far rim, and **breaking up the oil highlight**,
which is what a real pore does and a scalar darkening cannot.

## 1. Where it lives, and the consequence

Compute side: the 77 resolvers, the same modules `109` patched. Under PT the
raygens shade local lights themselves and the resolvers' shading shows
**only in direct sun** (`112` §12, `113` §1). So this build changes sunlit
faces and does nothing under a neon at night. That is the A/B frame (§8).
The raygen port is the follow-up (§10). It was built here first because
every input is already proven in the resolvers: neighbour G-buffer taps
(`70`, `109`), the metric P chain (`99`), the albedo fetch (`44`, `96` §1.2)
and the class gate. The raygen has none of those detectors yet.

## 2. The math (dev/bump_model.py, float32, as emitted)

    L      = 0.2126 r² + 0.7152 g² + 0.0722 b²        albedo is sqrt-encoded (96 §1.2)
    gx     = L(x+1, y) − L(x, y)     gy = L(x, y+1) − L(x, y)        [luma/texel]
    g'     = g · (1 − smoothstep(T0, T1, |g|))                      the edge-kill band
    dPx    = P(x+1, y) − P           dPy = P(x, y+1) − P             [m], 109's taps
    grad   = g'x / max(|dPx|², ε) · dPx  +  g'y / max(|dPy|², ε) · dPy   [luma/m]
    t      = grad − (grad·N) N                                       tangential part
    d      = −H · t ;  d ·= min(1, DMAX / |d|)                       the tilt clamp
    N'     = normalize(N + d)
    valid  = |dPx|² < J²  &&  |dPy|² < J²                            109's guard
    N''ₖ   = select(valid && class == 1, N'ₖ, Nₖ)

Knobs and why:

| Knob | Value | Why |
|---|---|---|
| H | 0.010 m/luma (`-hi` 0.020) | a 0.02-luma pore across a 1.45 mm texel (1 m, 720p) tilts 7.9°; across 0.43 mm (0.3 m) 24.7° |
| T0, T1 | 0.05, 0.12 luma/texel | pores after filtering are 0.01–0.05; a lip line, brow or eyeliner edge is 0.15–0.4 and must NOT become a ridge (the classic albedo-to-normal artifact) |
| DMAX | 0.5 (26.6°) | a thin texel at grazing view or a texture seam cannot flip the normal |
| J | 0.05 m | verbatim `109`: a neighbour on another surface falls back to N; `OpFOrdLessThan` is false for NaN so an out-of-bounds tap falls back too |
| step | 1 texel | |

Model output (`python3 dev/bump_model.py`, reference pore dL = 0.02):

| distance | texel | tilt | 10-bit LSB noise |
|---|---|---|---|
| 0.3 m | 0.43 mm | 24.8° | 1.7° |
| 0.5 m | 0.72 mm | 15.5° | 1.0° |
| 1.0 m | 1.45 mm | 7.9° | 0.5° |
| 2.0 m | 2.89 mm | 4.0° | 0.3° |

Two honest notes on that table. (a) The 0.02 step is held constant with
distance, which is pessimistic at 0.3 m: a magnified texture is smooth
between its own texels, so the per-screen-texel step shrinks as you close
in. The clamp is the backstop either way. (b) Quantisation of the
A2B10G10R10 sqrt encoding is 0.0013 luma at mid-tone, half a degree at 1 m:
not a noise source.

Self-check, 7 assertions: H = 0 identity; reference pore tan 0.2 leaning
toward the darker side; a 0.3 edge killed by the band; clamp at DMAX; guard
on a 6 cm jump; 5× longer dP → 5× less tilt; |N'| = 1 for an off-axis N.

## 3. What is rewritten (the part that matters)

The shading normal is **not the decode**. In 68 of 75 modules the three
decoded components feed one `OpPhi` each at the material-class switch's
merge (case 4 substitutes a hair normal) and every lighting term reads the
phi. The patcher rewrites the phi triple, after the phi group. In the other
7 modules the switch does not touch the normal and the decode is read
directly; there the decode's three ids are rewritten **except** the two
`OpFSub N(neighbour) − N` reads `109`'s curvature estimator makes — curvature
must be measured on the raw surface, not on the bump (the report and the
verifier both count those: 2 per component in raw modules, 0 in phi
modules).

One splice site per module, 243 instructions, 6 fetches (3 albedo, 2
neighbour depth, and the centre P refetch because P is defined after the
phi in all 75 modules). Unconditional — the gate is an `OpSelect`, not a
branch — so the cost lands on every pixel of every resolver. Unmeasured.

Detected, never guessed (GOTCHAS 5/10/12): P via `wpos_core.find_pos_chain`;
the pixel's own normal decode among `109`'s three; the albedo fetch walked
from the Disney diffuse sites through `find_diffuse_colour` /
`_albedo_channel_root` to one v4 fetch whose xyz are squared, at the pixel
coordinate, same LOD as the normal; the class value via
`acquire_class_shift`. Anchors single-valued across all 75: matrix
`cbv[reg0+12][69..72]`, depth `registers[1]+0`, albedo `registers[1]+1`,
normal `registers[1]+2`. Declined by name: `99bb7c2698997b2a` (no P chain)
and `ab0bc2fee876d489` (v4uint writes, no P), the same two as `109`.

## 4. Gates (`dev/build_bump.sh`, all passed 2026-09-04)

0. base provenance: 77 + 16 (12 + 4), MANIFEST carries `src_ser=`.
1. `bump_model.py` self-check.
2. disassemble 77.
3. dis → as byte-neutral at each module's own version, 77/77 (makes the control non-tautological).
4. patch six trees: bump, hi, vis, ctl, and the decoys noguard, noband.
5. coverage from the JSON reports vs `CENSUS`: 75 patched = 68 phi + 7 raw, 243 instr/module, every use of every component rewritten minus the kept curvature taps, anchors and knobs single-valued, ctl emitted 77 with 0 rewrites, vis 150 writes 0 skipped.
6. assemble 93; raygens and declined modules `cmp`-verbatim; `spirv-val --target-env vulkan1.4`; differ counts exactly 75; every pair of rungs differs; ctl 0 of 93.
7. verifier on shipped bytes (§5), plus 13 rejections.
8. vis: 150/150 writes gate on `(gbuf.y >> 5) == 1` and the non-skin slice is opcode-identical to the base.
9. stack: 93/93 = `bump`, verifier passes on the stack's own bytes.
10. MANIFESTs with provenance; park under new names only (`.built-by-build_bump` marker).

## 5. The verifier (`dev/verify_bump.py`)

Independent of the patcher's report. Per module it finds the three
`OpSelect`s whose condition resolves to `IEqual … %uint_1` and whose true
arm is `v · InverseSqrt(Dot(v,v))` with the false arm inside `v`, then
walks: the shared normalise → the clamp `NMin(DMAX·rsqrt(max(|d|²,ε)), 1)`
→ `d = −H·(grad − (grad·N)N)` against the same N ids → `grad = ix·dPx +
iy·dPy` with shared ix/iy → `ix = g' / max(Dot(dP,dP), ε)` → the band
polynomial constant by constant (or its absence under `--no-band`) →
`g = L₁ − L₀` → three sums of Rec.709-weighted squared fetch components →
one albedo image at one LOD; the depth taps to one depth image ≠ the albedo
image; the albedo tap and the depth tap of one axis read the **same
coordinate id**; taps are `(x+step, y)` and `(x, y+step)` about the centre
P's coordinate; the guard tests the same `|dP|²` ids the gradient divides
by. Then: no consumer of the pre-bump normal survives outside the block
except the curvature `OpFSub`s (0 or 2 per component, equal across
components), every bumped component has a consumer, and the read-back
constants reproduce `bump_model.bump` on four gradient cases.

Rejected, each by exit code: the base, the H=0 control, the vis rung, the
no-guard decoy, the no-band decoy, bump read as -hi and vice versa, wrong
T1, wrong DMAX, wrong J, wrong step, bump read as unguarded, bump read as
unbanded.

## 6. What is NOT in this build

- **The roughness half.** The brainstorm paired the bump with a small
  roughness rise in the dark spots. Not built: the alpha at the GGX sites is
  already the `108`/cap `OpSelect(class==1, …)` and a second rewrite there
  needs its own census. The bump alone breaks up the highlight
  geometrically, which was the point.
- **The raygen port.** §1. Without it, no local-light effect.
- **A capture.** The verdict (§11) is a live read-out; no frame was saved.
- **Cost.** Unmeasured. 243 instructions + 6 fetches per pixel per resolver.

## 7. `bump-vis`

Paints `|d'| / DMAX` on class-1 pixels: blue = flat (no tilt), green = half
the clamp, red = clamped; **white** where the silhouette guard fired.
Modulated by scene luminance (clamped 0.25–2) so it reads independently of
shading. Non-skin pixels are the base value by proof (gate 8).

Read it first. Expected on a sunlit close-up: a fine blue-green speckle
following the pore map, green-to-red **only** on creases and along albedo
edges that slipped under T1, white along the silhouette and at the
hairline. Diagnoses:

| Seen | Meaning |
|---|---|
| uniform blue | gradient too small at this distance → the feature is invisible here; step closer or raise H |
| large red areas | the band is not catching edges (T1 too high) or H too high |
| red haloes around lips/brows | edge leak; lower T1 |
| no pattern, flat colour | the albedo read is not the pore map (family void) |

## 8. Settings contract and the A/B

Set **before** launch, state them in the log (memory: never infer settings
from captures):

    skinspec = bump   (or the stack name)      ser = class      shadowset = full-shadow
    PT on, DLSS as shipped, no Ray Reconstruction change

Frame: **direct sun, close-up face at 0.3–1 m**, still camera. A/B against
the default (`…-curv-t7hue1-ll`, = `bump-ctl` by bytes). Order:

1. `bump-vis` — the ramp must follow the pore map (§7). Flat = void.
2. `bump` vs default — look at the cheek and nose highlight: does the oil
   sheen break into a pore pattern instead of a smooth blob? Does the
   terminator side of the cheek gain micro-contrast?
3. `bump-hi` — is 2× still skin or does it read as sandpaper?
4. Pan to a lip line and an eyebrow with `bump`: any ridge along the edge
   is the band failing. That is a reject, not a tuning note.

Pre-registered readings:

| Outcome | Verdict |
|---|---|
| highlight breaks up, no edge ridges | keep; consider `-hi` |
| visible but too strong at 0.3 m | lower H, or make H scale with the texel footprint (§10) |
| edge ridges on lips/brows | lower T1 (0.08), rebuild |
| nothing visible in sun with a correct vis ramp | H too small for the texture's pore contrast; try `-hi` before concluding |
| nothing visible AND vis flat | the albedo target is not the one the diffuse term reads at this pixel — census error, report |

## 9. Files

    dev/bump_model.py      the numbers above, self-checked
    dev/patch_bump.py      the patcher (tiers feature | vis; --height 0 = control)
    dev/verify_bump.py     the independent read-back
    dev/build_bump.sh      gates 0–10, --install, --stack
    swaps.bump{,.hi,.vis,.ctl}/, swaps.<base>-bump/    build outputs (ignored)
    ~/.local/lib/callisto/skin.set/{bump,bump-hi,bump-vis,bump-ctl,<base>-bump}/
    init.lua               4 rung rows + 1 stack row (not the default)

Rebuild: `./dev/build_bump.sh --install --stack` (90 s). Retune: `--t1 0.08
--name bump-t8 --install`.

## 11. Verdict and the default (2026-09-04)

Served live, no capture. User verbatim: *"The bump option was the best
thing I've tested so far. IT LOOKS INCREDIBLE."* Kept, and made the default:

    skinspec = gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll-bump

content sha `241bb736f0ed93b6`, 93 of 93 bytes = `skin.set/bump`. The
previous default `…-curv-t7hue1-ll` (= `bump-ctl`) is the A/B 'before'.
Contract unchanged: `ser=class`, `shadowset=full-shadow`. The rung MANIFESTs
and the stack MANIFEST carry the verdict (rebuilt by `build_bump.sh`, same
sha). Not read yet: `bump-vis`, `bump-hi`, the lip-line edge check of §8
step 4, and any night/local-light frame (expected: no change, §1). Those
stay open as tuning questions, not as blockers.

## 10. Follow-ups, in order

1. Shoot `bump-vis` and `bump-hi`, and the lip-line edge check (§8 step 4).
2. Footprint-aware H: multiply H by `min(1, |dPx| / 1 mm)` so the tilt per
   pore is constant in world terms instead of growing as the camera closes.
   One extra multiply on values already in the block.
3. The raygen port: the same block at the raygen's primary-hit normal, so
   local lights see the pore. Needs a raygen-side G-buffer neighbour
   detector — none exists yet.
4. The roughness half, on its own census of the alpha selects.
