# 59 — Traced-thickness ear glow: built, validated, parked. ~~NEVER on screen.~~

> **LAUNCHED 2026-08-31 01:46 (`earglow-hi`, user-run) — the look FAILS on
> screen: three structural defects, none of them `39`'s two and none priced
> in §6 (the polarity row does NOT apply — verified in the deployed binary).
> The mechanism result underneath is real and extends `56`. Read
> `60-EARGLOW-RESULT.md` before touching this build.**

Written 2026-08-31 (delegated build; spec `51` §7 step 3 + §10, gate result
`56` §7). Three rungs — `earglow-lo` / `earglow` / `earglow-hi` (k = 0.10 /
0.22 / 0.45) — are parked in `skin.set/`, built over the standing
`gi-50-bleed` byte-verbatim, one variable by construction. **Nothing here is
working until an on-screen A/B says so.** Read §6 (the pre-registered
interpretation table) BEFORE the screen.

The design target, user's words: *"I want ears to go full red when light from
the sun is being cast through them. Like for them to illuminate… Same with
noses."*

## 0. What was built, one paragraph

In each of the 10 paintable `rgs_reference_main`, immediately after the
module's own **sun-NEE shadow trace**, one injected `OpTraceRayKHR` measures
the geometric thickness of the primary surface along the sun direction, and a
per-channel Beer–Lambert transmission `exp(−thickness/ld) × sunRadiance × k`
(ld = 3.67/1.37/0.68 mm, the same Jensen skin1 set as `52`/`53`) accumulates
into three Function-storage floats that are added to the module's radiance
image writes. Gates — **class-1 skin** (clone of the module's own G-buffer
material fetch, compared `== 32` instead of its `== 160`) ∧ **backlit**
(the module's own `N·S ≤ 0` bool) ∧ **bounce 0** (the bounce-loop counter
phi `== 0`) — fold into the cullMask (`select(gate, 39, 0)`); a gated-off
trace is a mask-0 guaranteed miss, near-free (`55`'s costing). No new control
flow, no `replace_all_uses`, no phis. A ~5 mm ear transmits R at 0.26, G at
0.026, B at 0.0006 of the sun — **the saturated red IS the spectral falloff,
no tint knob** — and a forehead (path through the skull > 2 cm) measures
nothing and stays dark. `39`'s two defects die structurally: measured
thickness (not a proxy) kills forehead-scores-like-an-ear; raygen-resolution
output kills the tile grid.

Files: `dev/patch_earglow.py`, `dev/build_earglow.sh` (both re-runnable);
work disasms `dev/disasm/earglow/`; rungs `swaps.earglow{,-lo,-hi}/` and
parked `skin.set/earglow{,-lo,-hi}/`, per-module `*.rgs.report.json` inside.

## 1. The measurement, and why the ray is REVERSED

`51` §7 sketches "short ray along −L from the skin hit". Built literally,
that ray starts at the surface and needs a **back-face hit from inside the
flesh** — a configuration no engine ray exercises (the radiance rays carry
`CullBackFacingTriangles`), and instance-level culling could kill it silently.
Instead:

    origin    = P + S·T_CAP        P = the sun-NEE trace's own offset origin
    direction = −S                 S = the module's own cone-jittered unit sun dir
    tmax      = T_SEG = 0.018      (T_CAP = 0.02 m; stops 2 mm short of P)
    flags     = 16 (CullBackFacing), SBT 1/1/0 = the radiance hit groups
    thickness = T_CAP − hitT

The first hit walking back toward P is the **sun-side surface of whatever P
is inside of, front-facing to the ray** — the hit configuration every engine
ray already exercises. Failure modes all land on T = 0 (identity):

- **miss** (nothing sun-side within 2 cm — includes "origin buried in flesh",
  i.e. genuinely thick): the engine's miss-0 writes payload member 3 = 10000
  ⇒ fails the `t < 0.0179` validity compare ⇒ contribution 0. That miss
  convention is **proven in-module, not assumed**: the sun-NEE trace itself
  relies on mask-0 ⇒ miss ⇒ `member3 == 10000` (its visibility test), and
  the primary trace tests `member3 == 10000` for its sky path.
- member 3 is additionally **pre-armed to 10000** before the trace, so even
  a total no-write (trace dead, miss dead) leaves T = 0. The rungs are
  identity-when-dead: the adds become `+0.0` at every write, bit-exact.
- **occluder sun-side of P** (hat brim, wall): small hitT ⇒ thickness ≈ 2 cm
  ⇒ T ≈ 0.004 ⇒ dark. Occluders read as thick, which is the right answer.

Payload: a fresh variable of the module's own `{uint,uint,float,float}`
struct (on the SPIR-V 1.4 entry interface), member 3 = hit distance — the
member the raygen itself pre-arms and reads at both existing traces
(`%1151`-pattern). The CHS-writes-member-3-on-hit leg is what `56` rung B
proved; the miss leg my design does NOT depend on (`56`'s open limit).

## 2. Everything cloned by id from the module's own instructions

Per module, the detectors (all read-only, before any edit — GOTCHAS 12):

| input | source | how found |
|---|---|---|
| sun-NEE trace | the ONE trace with literal flags 12 + tmax `%float_10000` | asserted exactly 1 in all 10 |
| backlit bool | the condition of its cullMask `OpSelect(cond, 0, 39)` | asserted shape; `cond = (N·S ≤ 0)` verified by hand |
| P, S | the trace's own origin/direction composites | operand ids |
| sun radiance RGB | the slot-6 `cbv[…][6]` load + 3 extracts in the same block (slot-5 sun-dir sibling asserted) | `cbv121[5]` = unit dir toward sun, `[6]` = radiance — verified at two independent uses (NEE base dir; the H = normalize(L−D) construction) |
| bounce counter | the `OpPhi %uint` init-0 whose +1 increment conditions a back-edge **targeting the phi's own block**, body containing the NEE trace | rejects the interior light-sampling loops AND the outer sample loop (§9) |
| skin class | clone of the module's own material fetch chain (20 ops: `heap[registers[1]+5]`, checkerboard X-offset from a bindless CBV + LaunchId — replicated verbatim), `& ~31 == 32` | the module's own `== 160` (class 5) test names the pattern |

Clone-by-id is `55`'s method: every operand of the injected trace is either
the live trace's own id one line earlier in the same block (dominance
trivial) or a literal constant. The 2 atomic permutations (`40c6faab`,
`ab7f1822`, no radiance write) ship byte-verbatim pass-throughs as always.

## 3. Validation — all pass, re-runnable

- 93 modules per rung × 3 rungs, `spirv-val` clean at auto-detected env.
- cmp-asserted: 77 compute + 4 restirgi + 2 atomic refs **byte-identical to
  `gi-50-bleed`**; the 10 patched refs assert **different**.
- Emitted-code re-read from the OUTPUT binaries (`39` §3.4), per module:
  trace count = base+1; exactly one flags-16 trace with tmax 0.018; the
  gate select `(gate, 39, 0)`; the class-32 compare; exactly 3 `Exp`s; the
  three 1/ld constants within 0.1 % of 272.48/729.93/1470.59; the k
  constant; every rewritten `OpImageWrite` texel is FAdd-composed.
- Hand-read of the full id-preserving diff on `d622fb9e` (the dispatch-
  proven permutation): 79-instruction splice + 3 write-site adds + entry
  block (3 Function vars, zero-init) + interface append, and **nothing
  else**. Detector picks verified against the source: `%1742` = init-0
  header phi, `%3214` = the `N·S ≤ 0` bool itself, `%3194–96` = slot-6
  extracts, `%3303–05` = the NEE trace's own AS/origin/direction.
  (Do NOT diff re-disassembled binaries whole-file — id renumbering makes
  it garbage, `40` §8. The patcher's emitted `.spvasm` is id-preserving.)
- Closed form: T(th) = exp(−th/ld). th=3 mm → R .44 G .11 B .012;
  5 mm → .26/.026/6e-4; 8 mm → .11/.003/~0; 15 mm → .017/~0/~0. Contribution
  = T × sunRadiance × k, NMin-clamped at 100/channel (fp16 headroom,
  GOTCHAS: scale before a clamp).

## 4. Units and magnitudes, with the evidence

Engine units are **meters**: tmin 1e-6 and radiance tmax 10000 (10 km sky
rays) in these modules, dynamic NEE tmax = light distance, RED engine
convention. T_CAP = 2 cm covers ears (4–8 mm) and noses (8–15 mm) with
nothing to spare for skulls. The 2 mm blind zone at the segment end (tmax
stops short of P to avoid self-hit) floors measurable thickness at 2 mm ⇒
max R transmission 0.58. k = 0.22 puts a 5 mm backlit ear at ~6 % of raw sun
radiance in R — same order as lit-skin diffuse — with `-lo`/`-hi` bracketing
half/double. If the default reads wrong, move along the ladder, do not
re-derive constants.

## 5. Launch protocol (per `45`; settings STATED, house rule)

1. Contract = `gi-50-bleed`'s, verbatim: PT on (photo mode PT on), `ser=class`,
   `shadowset=full-shadow`, standing PT switches with **`ptreg` ON** (the
   rcbm combo — `56` §6; the MANIFEST carries `ptq_sha=55ed4e5c6884ab71` and
   sync refuses otherwise), RR state pinned and verified in the collect
   snapshot. CET-selectable once the §7 diff is applied — no
   `brdf_params.txt` hand-edit needed.
2. `./dev/ab_launch_audit.py 1` BEFORE reading any pixel: expect 77 dxil +
   12 `rgs_reference_main` + 4 `rgs_restirgi_*` HITs, 0 rejects, manifest
   echo `earglow … k=0.22`.
3. **The scene is half the experiment**: a close head, low sun BEHIND the
   subject, ears or nose rim toward camera. A frontlit face is a negative
   control and should show NOTHING. Shoot the A/B against `gi-50-bleed`
   at the same camera in the same session (`50` §6's lesson: cross-session
   sun pairs cannot be lighting-matched).
4. One rung per launch, `earglow` (k=0.22) first.

## 6. PRE-REGISTERED interpretation table — read BEFORE the screen

| on screen | means | next |
|---|---|---|
| ears/nose glow red against a low sun; forehead and cheeks do NOT; frontlit face unchanged; no tile grid | the mechanism works end-to-end | pick a k rung by eye; A/B decides the keeper |
| frame == `gi-50-bleed` exactly, including a staged backlit close-up | the injected static trace at the NEE site does not execute (one step past `56`'s site), OR the gates never open, OR back-hits never validate | do NOT burn launches guessing: a diagnostic build (paint-on-valid, gates dropped) is a ten-minute patcher flag; build it, then one launch |
| glow on frontlit skin (sun on camera side) | backlit gate polarity wrong | sign fix, rebuild; do not tune k |
| red wash across the whole face, forehead included | thickness measurement broken (everything reads thin) — origin/direction/units wrong | STOP. Re-read §1 and §4; this is `39`'s defect and tuning k is the mistake `39` documents |
| glow with a blocky tile grid | impossible from this splice (raygen-res output) — the effect on screen is NOT this build | audit the serve before any theory |
| overbright sparks/fireflies on skin edges | clamp/strength vs RR interaction | `earglow-lo`; if still there, lower CLAMP in the patcher |
| crash / device lost at pipeline creation | this family tolerates the sentinel's injected site but not this one | remove the rung; `56` stands but becomes site-dependent — document that narrowing |

## 7. Registration diff — NOT applied (main session applies)

`init.lua`, `SKIN_LEVELS`, after the `gi-50-bleed` entry:

    -- 59: traced-thickness ear glow (A/B vs gi-50-bleed; read handoff/59 sec 6 BEFORE launching)
    { id = "earglow-lo",  label = "Ear glow lo (traced thickness, k=0.10)" },
    { id = "earglow",     label = "Ear glow (traced thickness, k=0.22)" },
    { id = "earglow-hi",  label = "Ear glow hi (traced thickness, k=0.45)" },

`sync_settings.sh`: no change (served by name; MANIFEST provenance is
`gi-50-bleed`'s verbatim, so the `gi_refuse` contract holds unchanged).
`Makefile`: no change.

## 8. Built vs unproven

**Built and verified offline (high confidence):** everything in §3.

**Unproven, and only a launch can prove it:**

| claim | confidence |
|---|---|
| rungs valid SPIR-V; byte-verbatim outside the 10 patched refs | **certain** — build asserts, re-runnable |
| splices carry exactly the designed instructions | **high** — script re-read + hand-read diff + detector ids verified in source |
| identity-when-dead (frame == gi-50-bleed if the trace never runs) | **high** — pre-armed 10000 ⇒ T=0 ⇒ `+0.0` adds, bit-exact; same construction the sentinel proved behaviourally |
| the injected trace EXECUTES at this site | **unknown** — `56` proved a clone at the *primary* trace site with verbatim operands; this is a new site, literal flags 16, overridden origin/direction/tmax. One step beyond the evidence, priced in §6 row 2 |
| CHS writes hit-T into member 3 for my hits | **high** — engine convention proven at both existing traces; same SBT slots |
| front-face hits resolve at 2 cm scale on character geometry | **medium** — nothing exercises sub-3cm tmax traces today |
| it looks like the design target | **unknown — that is the A/B, not a gate** |

## 9. Side-findings and priced weaknesses

- **`29` §B4's "degenerate outer loop" is true only of the baked-bound
  four.** In the 8 dynamic-bound permutations the outer loop is LIVE:
  `21a92f1a` carries a real counter (`%1716`, init 0, +1, `ULessThan` vs
  `bitcast(cbv[188]).y` = RayNumber) with a wired back-edge, nested around
  the bounce loop (bound = `.z` of the same cbv row). `29` Part B item 6
  ("wire the sample loop") may already be wired in two-thirds of the family
  — re-test `RayTracing/Reference/RayNumber` live before building anything
  (29's item 2, still unrun, now with a reason).
- **RayNumber > 1 would overbrighten the glow ∝N** (the term adds once per
  sample at the write, after any normalization). At the shipping N=1 it is
  exact. If RayNumber ever becomes a used lever, the add must move inside
  the sample loop.
- Only the sun/moon (`cbv121[5]/[6]`) transmits; local lights do not (their
  NEE sites are untouched). That is the ask, not a limitation being hidden.
- S is the cone-jittered sampled sun direction: per-frame sub-mm thickness
  jitter, negligible under RR/DLSS.
- The skin gate reads the G-buffer at the launch pixel (checkerboard offset
  cloned from the module's own idiom); PT-primary vs raster-surface
  disagreement at alpha edges defaults to no-glow.
- `earglow` embeds `gi-50-bleed` bytes: if that rung is ever rebuilt, rerun
  `./dev/build_earglow.sh --install` or the A/B stops being one variable.
- Uncommitted, like everything tonight (house rule).
