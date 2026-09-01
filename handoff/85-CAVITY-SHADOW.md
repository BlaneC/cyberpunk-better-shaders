# 85 — Cavity contact shadow: a skin-gated traced occlusion ray in the reference PT, three rungs, never launched (2026-09-01)

The brief: sunlight bleeds through lips, eyelid creases and nostril interiors
on skin; make those cavities go genuinely dark. This doc is what was built,
what it proves offline, and how to A/B it. **Nothing here is on screen. There
is no verdict until a one-variable A/B at the standing base says so.**

## 0. State, and the settings contract — read before launching

**Built, verified, three rungs in the repo, selector rows added. Not parked,
not installed, not committed, zero launches.** The live selection is still
`gi-50b-bleed-oil-sheen-deep-clothhi`.

| rung | tmax | k | what it isolates |
|---|---|---|---|
| `…-deep-clothhi-cavity` | **6 mm** | 0.85 | contact only: lip seam, eyelid crease / inner canthus, alar groove, nostril rim |
| `…-deep-clothhi-cavityd` | **15 mm** | 0.85 | + under-nose (the nose overhangs the lip 8–15 mm), nostril interior, concha, under-jaw |
| `…-deep-clothhi-cavityhi` | 6 mm | **1.00** | full occlusion — the strength axis, tested only after tmax is settled |

Required game settings, stated **before** the launch and never inferred from
the capture afterwards (the `45` rule):

- **PT Overdrive on**, **PT-in-photo-mode ON** — this term exists only in the
  reference path tracer (§2). Without photo-mode PT the rungs are inert.
- **Ray Reconstruction OFF.** ⚠ The live `UserSettings.json` has drifted to
  `DLSS_D: true` (found by another agent this session). Set it back to false
  and confirm it *in the menu* before the first half of the A/B, or the two
  halves are not comparable.
- DLSS **Balanced**, RayTracedLighting **Psycho**, **2560×1440** — the state
  `79` verified for the 22:28 launch, matched across both halves.
- Photo mode, **camera pinned**, both halves the same frame.

`brdf_params.txt`, the live file with **one line changed**:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-cavity
    ptreg=on  ptclamp=on  ptbounce=on  ptrefl=on  ptmsggx=on
    refract=eta15  ser=class

`ser=class`, `shadowset=full-shadow` and `ptreg=on` (the rcbm combo) are the
base rung's own contract: the MANIFEST carries the base's `src_ser`,
`ser_sha=310513f3008cbde4` and `ptq_sha=55ed4e5c6884ab71` **verbatim**, so
`sync_settings.sh`'s `gi_refuse` block re-checks and refuses on mismatch
exactly as it does for `-clothhi`.

## 1. The premise correction — the brief was wrong about the mechanism

The task was framed as *"bypass the game's low-res SIGMA-denoised shadow
mask"*. **In this shader family there is no such mask.** Every one of the 12
`rgs_reference_main` permutations traces a full sun ray per sample: flags 12,
`tmax = 10000`, `cullMask = Select(backlit, 0, 39)`, and the visibility term
is the `t == 10000` miss test on the payload's member 3. Sun visibility here
is already ray-traced, and already crisp.

So the bleed you can see in a still comes from two *other* holes, and the
design targets those directly:

1. **The primary hit is re-found from raster depth.** The reference raygen
   reconstructs the shading point from the internal-resolution depth buffer,
   which on a face slope at 1440p-internal is mm-scale wrong — enough to place
   the shading point on the *wrong side* of a 1–2 mm lip seam.
2. **The engine lifts its own sun-ray origin off the surface** by
   `c0·N·clamp(0.005·√t, 0.005, 0.1)` along the normal and `c1·D·(1+9·…)`
   back along the view ray (`cbv[..][77]`.xy). At face range that is
   **millimetres** — the same scale as the features we want shadowed. The
   engine's own sun ray starts *above* the crease it should be occluded by.

Our ray fires from the **un-biased traced hit point** with our own 0.5 mm
floor, so it sees the contact-scale geometry the engine's ray steps over.

**This is also why the term can be a no-op — see F1.** If lip/eyelid/nostril
relief is normal-map detail with no BVH geometry, there is nothing to hit and
both tmax rungs render pixel-identical to base. That falsifier *is* the
experiment; one cheap launch decides it.

## 2. Reach — narrower than the standing rung's compute half

This lands in `rgs_reference_main` **only**: the reference / photo-mode path
tracer. Gameplay rendering goes through the ReSTIR-GI + compute-resolve path,
which this build does not touch (all 77 compute and all 4 ReSTIR-GI modules
are byte-identical to base, cmp-asserted). Same surface `earglow` rendered on.
Judge it in photo mode or not at all.

## 3. Mechanism — the emitted code

Spliced immediately before the `OpSelectionMerge` that guards the module's own
sun block, i.e. **inside** the region the engine reaches only when its own NEE
ray reported the pixel LIT. 42 instructions, +972 bytes, identical in all 10
patched modules.

```
; --- gate: class 1 skin AND first bounce AND the engine's own "this pixel is lit"
%cls  = <20-op clone of the module's own G-buffer class fetch>   ; 55/59's clone-by-id
%skin = OpIEqual %bool (OpBitwiseAnd %cls 0xFFFFFFE0) %uint_32   ; class 1  (57 sec 3.2)
%b0   = OpIEqual %bool %bounce_phi %uint_0
%g    = OpLogicalAnd (OpLogicalAnd %skin %b0) %sun_cond
%mask = OpSelect %uint %g %uint_39 %uint_0        ; 0 == provably-missing ray

; --- pre-arm: nothing downstream depends on the miss shader (55)
OpStore payload.0 %uint_0   payload.1 %uint_0   payload.2 %float_0
OpStore payload.3 %float_10000

; --- one ray: from the UN-BIASED hit point, along the engine's own sun-disc sample
%o    = OpCompositeConstruct %v3float %prehit_x %prehit_y %prehit_z
OpTraceRayKHR %as %uint_16 %mask %uint_1 %uint_1 %uint_0 %o %f_5e-4 %nee_dir %f_tmax %payload
                    ^CullBackFacing              ^SBT 1/1/0        ^tmin      ^6 or 15 mm

; --- two-sided validity: a miss can write 10000, or 0, or nothing at all
%t    = OpLoad %float payload.3
%occ  = OpLogicalAnd (OpFOrdGreaterThan %t %f_4e-4) (OpFOrdLessThan %t %f_tmax)
%fac  = OpSelect %float %occ %f_1minusk %float_1

; --- application: 3 sites, one per channel, innermost
%new  = OpFMul %float %NClamp(diffuse*NoL + spec, 0, 1) %fac
%out  = OpFMul %float %new %sunRadiance_c          ; one operand token rewritten
```

**Identity when dead, by four independent paths.** Gate false ⇒ `cullMask = 0`
⇒ the ray provably intersects nothing; the trace never executing at all ⇒ the
pre-arm leaves 10000; a miss shader that writes 10000 ⇒ fails the *upper*
bound; a miss shader that writes 0 ⇒ fails the *lower* bound. In every case
`%fac == %float_1` and each site computes `src * 1.0`, which is bit-identical
to `src` for every finite float. **Nothing depends on the miss shader writing
anything** — `55`'s armed-word rule.

Two of the 12 reference modules (`40c6faab52a13874`, `ab7f1822eeb0331b`) have
no class test to clone and ship **byte-verbatim**, as in every prior raygen
rung.

## 4. The numbers, and the geometry that fixes them

**Mask 39, not 255.** Enumerated on the bytes: all 12 sun-NEE traces use
`Select(cond, 0, 39)`; the local-light traces use a literal 39. Our ray
therefore sees **exactly** the occluder set the engine's own sun ray sees — no
new leak taxonomy to reason about, and no chance of an invisible-to-the-engine
proxy casting a shadow the engine would never cast.

**Direction: the NEE trace's own operand, verbatim.** That vector is already a
sun-disc cone sample drawn from the module's LCG and scaled by
`cbv[..][82].y`. Reusing it gives a real per-sample **penumbra** for free under
photo-mode accumulation, and — because we take the value rather than drawing —
**advances no PRNG state**, so every downstream sample in the frame keeps
bit-identical noise. The A/B stays one variable.

**Origin: `prehit`, the un-biased traced surface point** (§1.2), harvested
structurally in all 12 modules as the pre-offset addend of the engine's own
NEE origin. The verifier re-proves that link in the shipped bytes rather than
trusting the patcher's id bookkeeping.

**tmin = 0.5 mm**, argued against both failure modes:

- *Acne.* Worst-case float position error at face range is `|P_cam|·2⁻²³ ≲
  1 µm`, so the grazing re-hit distance `ε/sinθ` stays under 0.5 mm down to
  θ ≈ 0.1° — 500× margin, and 500× the engine's own 1 µm tmin. More
  importantly `CullBackFacing` kills it **structurally**: at this site
  `N·S > 0`, so the only way to re-hit your own triangle is from underneath,
  which is a back face and is culled before any hit shader runs.
- *`70` W1's thin-card taxonomy.* Strand and collar cards at 0.2–0.5 mm are
  **wanted occluders here** — the sign is flipped from earglow, where a card
  that read as *flesh* was a leak; a card that *casts a contact shadow* is the
  feature. So the floor is set to clear float error while preserving the
  1–2 mm lip and eyelid creases, not to reject cards.

**tmax is the design axis, not the strength axis** (the `69` §2 / `70`
lesson). 6 mm is the reach of the features the brief named: a lip seam is
1–2 mm deep, an eyelid crease 1–3 mm, an alar groove 2–4 mm. 15 mm is the
reach of the *modelled overhangs*: the nose tip stands 8–15 mm proud of the
philtrum, the jaw 10–20 mm off the neck. Those two answer different questions,
which is why they are two rungs and not one knob.

**Flags 16 (CullBackFacing)** is earglow v1–v4's flag, proven on screen to
execute and to round-trip hitT in this exact family (`60` §0).

## 5. Composition against the standing skin stack

Our factor is the **innermost** term in the reference raygen's own Disney+GGX
sun evaluation: it sits *after* the shader's own `NClamp(·, 0, 1)` — safe, and
safe only here, because the factor is ≤ 1 so the product stays strictly inside
the clamp the shader already applied — and *before* the sun-radiance multiply,
the half accumulator, and both radiance `OpImageWrite`s.

The standing stack shares **no instruction and no module** with it: oil, half
fuzz, cloth sheen, real-gloss and `-deep` live in the 77 compute resolvers;
c1 + the terminator bleed live in the 4 ReSTIR-GI raygens. The consequence is
physically right — sheen, fuzz and oil scale *down with the light* inside a
cavity, so a shadowed crease will not carry a bright specular rim.

## 6. Pre-registered confounds and falsifiers

| # | confound / falsifier | observation | reading, and what to do |
|---|---|---|---|
| **F1** | **THE EXPERIMENT.** Creases carry no BVH geometry | **both tmax rungs pixel-identical to base on a close-up front-lit face** | normal-map-only relief. **Before declaring it dead, check the *modelled* overhangs — nose-over-lip, jaw-over-neck, ear — in the same shot.** If those darken and the lip seam does not, the term works and the *creases* are fake. If nothing anywhere darkens, the route closes: nothing to tune, and this doc says so |
| **F2** | acne | fine dark speckle on flat lit skin, scaling with sun grazing angle rather than with geometry | tmin 0.5 → 1.5 mm (`70` W1's number) and rebuild. **Do not lower k** — that hides the feature too. Built-in suppressor: the term we scale is ∝ NoL, so grazing acne multiplies a value already near zero |
| **F3** | double-darkening with the standing `-deep` band | the cheek **terminator** reads crushed to black while cavity features look right | not this term — `-deep` is NoL-driven, this is visibility-driven. Bounded structurally: `78` §1's direct-path row for `-deep` is **0.988 at NoL = 0**, i.e. ≈ neutral on the direct path; its −11 % lives on the **bounce** path, which our factor never touches. Worst-case double ≈ 1 %. Re-shoot on `-lumn` before touching k |
| **F4** | double with the engine's own shadow | — | **structurally impossible at this site**: the splice executes only where the engine's NEE already called the pixel LIT; if it called it shadowed, the branch is not taken and our mask is 0. We can only ever darken a pixel the engine called lit. Honest residual: the compute-resolve half may apply its own screen-space term to the same pixel. Floor is (1−k) = 0.15; the tell is a *black* rather than dark cavity ⇒ step `-cavityhi` → `-cavity`, then k → 0.6 |
| **F5** | fuzz / oil / sheen | a bright sheen rim survives at full strength **inside** a blackened crease | the compute half is a parallel path, not downstream of the reference sun term. That is a real architectural finding to record — **not** a k change |
| **F6** | sample count | — | cannot overbrighten: we scale a per-sample term, so the result is sample-count invariant, unlike `59` §9's additive term. `RayNumber > 1` and photo-mode accumulation are both safe |
| **F7** | penumbra noise (added at build time) | cavity edges look *noisy* in a single non-accumulated frame | expected, not a bug: the direction is a per-sample sun-disc jitter (§4), so the shadow edge converges to a real penumbra only under accumulation. **Judge in photo mode with the camera pinned and the frame settled.** If it is still noisy after settling, the accumulation is not running — check settings, not k |
| **F8** | cost | — | one extra CHS per lit skin pixel per bounce-0 sample at ≤ 15 mm; cheaper than earglow's 18 mm ray + its full-range visibility ray. Photo-mode priced. If frame time is unacceptable, `-cavity` (6 mm) is the cheap rung |

## 7. Verification — every gate, all build-failing

`./dev/build_cavity.sh` aborts on any of these. Run 2026-09-01, all green:

| gate | result |
|---|---|
| base provenance: repo dir == parked `skin.set/gi-50b-bleed-oil-sheen-deep-clothhi` | **93/93 byte-identical** |
| **negative control**: the cavity detector on the *unpatched* base | **0 sites in 12/12** — 0 flags-16 traces, 0 class-32 compares |
| site coverage, per rung (abort on any 0-site module or non-empty skip list) | **10/10 modules × 3 = 30/30**, uniformly 42 instructions / +972 bytes each |
| `spirv-val`, per rung | **93/93 clean** |
| **k = 0 rebuild byte-identical to base** (proves the dis→as round trip *and* that every emitted byte is ours) | **10/10 identical** |
| **gate-false byte-inertness, re-read from the EMITTED binaries** (`dev/verify_cavity.py`, §10) | clean on all 3 rungs |
| verbatim halves, cmp-asserted | **83/83**: 77 dxil + 4 ReSTIR-GI + the **2 class-test-less reference modules** |
| patched modules differ from base | 10/10, and 10/93 modules differ per rung — the one-variable property |
| `dev/verify_bleed_norm.py` on the standing compute rungs | **PASS** ×2 (150 hold sites / 77 modules each) |
| `dev/verify_gi_ladder.sh` | **PASS** (the `72` ladder, parked rungs untouched) |
| MANIFEST provenance | `src_ser` / `ser_sha=310513f3008cbde4` / `ptq_sha=55ed4e5c6884ab71` carried verbatim, asserted present |
| `make check` (lua + bash lint) | ok |

`dev/verify_cavity.py` is the `39` §3.4 discipline: it re-disassembles the
**shipped** binary and re-derives everything structurally (ids are not
comparable across the round trip, `40` §8). Per module it proves trace count =
base + 1; exactly one flags-16 trace; `cullMask = Select(gate, 39, 0)` with the
gate an AND of a class-32 compare, a bounce-0 compare and the module's own
sun-branch condition (cross-checked by finding the `OpBranchConditional` that
condition drives); the origin is the NEE origin's own pre-offset addend triple;
the direction is the NEE direction operand verbatim; tmin and tmax by resolved
constant **value**; the member-3 pre-arm store before the trace and no other
store to it; the two-sided validity test; `factor = Select(occ, 1−k,
%float_1)`; exactly 3 sites of the form `FMul(FMul(NClamp, factor), sunRad_c)`
with each sun-radiance component still at exactly **3 uses**; and finally that
the per-opcode count delta against the base is **zero outside a whitelist** and
**exact** for the eight opcodes the class-fetch clone provably cannot emit.
The verifier was shown non-vacuous: fed the wrong `k` or the wrong `tmax` it
fails.

## 8. A/B runbook

Serve the rungs (§0's settings contract first — it is not optional):

    ./dev/build_cavity.sh --install          # parks all 3 in skin.set/
    make install                             # deploys init.lua's selector rows

Then pick the rung in `brdf_params.txt` (or the CET panel — three rows were
added to `init.lua`; **without them `init.lua:288` coerces an unknown
`skinspec` to `off`**, which is a silent no-op, not an error).

**Scene.** A close-up face, **front-lit by the sun**, in photo mode with the
camera pinned. The frame must contain, at once:

- the **creases** the term is for — lip seam, eyelid crease, nostril; and
- the **modelled overhangs** — nose over the philtrum, jaw over the neck, the
  ear bowl. F1 is decided by comparing these two in the *same* screenshot, not
  by remembering another one.

Ladder, one variable per step:

1. `-cavity` (6 mm) vs `-clothhi`, identical frame. Claim: cavities darken;
   everything not skin, and all bounce light, is untouched.
2. `-cavityd` (15 mm) vs `-cavity`. Claim: the *overhang* shadows appear —
   under-nose, under-jaw, nostril interior. This is the tmax question.
3. Only after tmax is settled: `-cavityhi` vs whichever of 1/2 won. This is
   the k question, and it is last on purpose.

## 9. Rebuild / retune

    ./dev/build_cavity.sh                    # build + verify, no install
    ./dev/build_cavity.sh --install          # ALSO park in skin.set/

Knobs live in `RUNG_SPECS` in the build script (`"k,tmax"` per rung) and as
constants in `dev/patch_cavity.py`: `TMIN` (5e-4), `TLOW` (4e-4, the
fails-closed lower bound), `CULL` (16), `MASK` (39). `--k 0` is byte-inert by
construction and is the build's own identity control. A single module can be
patched and inspected directly:

    ./dev/patch_cavity.py <in.spvasm> --k 0.85 --tmax 0.006 --outdir DIR

To rebase on a different standing rung, point `GI` at it; the patcher is
base-agnostic and every detector dies rather than guessing.

## 10. Files

- `dev/patch_cavity.py` — **new**. The patcher. `find_sun_branch` walks the
  visibility branch hop by hop and **dies on any deviation** (it asserts the
  whole chain `load m3 → FOrdEqual(t,10000) → Select → Select(backlit,…) →
  dot(rad,rad) → FMul → FOrdGreaterThan(·,0) → OpSelectionMerge`, and
  cross-checks the backlit bool against the NEE cullMask's and the radiance
  triple against the cbv slot-6 extracts). `find_sun_sites` asserts exactly one
  `FMul(NClamp(·,0,1), radC)` per channel, that `radC` has exactly 3 uses
  module-wide, and that each site lies strictly inside the sun block. All
  detectors run before any rewrite (GOTCHAS #12); reuses
  `dev/patch_earglow.py`'s clone/detector library rather than forking it.
- `dev/verify_cavity.py` — **new**. The shipped-bytes verifier of §7, plus the
  `--negative` control.
- `dev/build_cavity.sh` — **new**. The three rungs and every gate in §7.
- `swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cavity{,d,hi}/` — 93 modules
  each. **Not parked** (no `make install` was run — parallel agents).
- `init.lua` — three selector rows added after `84`'s env-bleed rows. This is
  the only shared file touched.

## 11. Unsure / not done

- **Never launched. No verdict. Not committed, not parked, not installed.**
- **F1 is genuinely open.** Whether Cyberpunk's face meshes carry real crease
  geometry at 1–3 mm is not knowable from the shader bytes; it is a question
  about the BVH content, and only a launch answers it. Everything else in this
  build is proven; this is the one thing that is not.
- **Gameplay is untouched** (§2). If the effect is wanted outside photo mode
  it is a different, larger build against the ReSTIR-GI + compute path, and
  that path has no equivalent per-sample sun ray to hang off.
- The term ignores the sun's angular diameter for the *tmax* decision: a
  6 mm ray finds a 6 mm occluder regardless of how soft the source is. If the
  result reads as too-hard contact shadows under an overcast sky, that is the
  reason, and the fix is a `cbv[..][82].y`-scaled tmax, not a lower k.
- The two byte-verbatim reference modules are unpatched. If a launch profile
  shows either of them dominating a face close-up, the coverage is 10/12 and
  the missing two need a class fetch synthesised rather than cloned.
- No jitter beyond what the NEE direction already carries (`70` W2's optional
  per-frame jitter was not added — the sun-disc sample already supplies it, and
  adding more would have cost a PRNG advance and broken the one-variable A/B).
