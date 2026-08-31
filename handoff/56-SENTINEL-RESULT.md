# 56 — G-U5 on screen: the injected static trace EXECUTES. Traced thickness is unblocked.

Written 2026-08-31, immediately after the two launches. Both rungs of `55` ran
under a stated, pinned settings contract. **Rung A dark, rung B paints.** The
gate passes, and the four-document-old assumption it was built to test —
`GOTCHAS`' "a second `OpTraceRayKHR` does not execute" — is **overturned**.

Captures and machine-readable records: `a-b-testing/sentinel/RESULT.md`,
`a-b-testing/sentinel-b/{RESULT.md,S1.png}`, both with
`UserSettings.{pre,atshoot}.json`.

---

## 0. Verdict

| question | answer | evidence |
|---|---|---|
| does a **new static `OpTraceRayKHR` site** spliced into a raygen execute? | **YES** | `sentinel-b`, cyan on all painted geometry |
| does a payload written by **another stage** round-trip back to the raygen? | **YES**, via the pipeline's own unpatched CHS | same |
| does it round-trip via the **miss** shader at `missIndex 0`? | **NO** (or the SBT miss-0 mapping is not this library's `ms_empty_main`) | `sentinel`, dark |
| is traced-thickness ear glow (`51` §7 step 3) buildable? | **YES** — it needs CHS→payload hit distance, which B proves | §3 |
| H2 (driver/vkd3d forbids multiple static sites) | **DEAD** | §4 |

---

## 1. What was served — both launches verified before any pixel was read

    A  2026-08-30T23:57:36  skinspec=sentinel    skin_sha=677b22d29dd9c322
       12 rgs_reference_main + 10 ms_empty_main + 4 rgs_restirgi + 77 dxil HITs
       0 ser_reject   manifest: sentinel ... ptq_sha=55ed4e5c6884ab71

    B  2026-08-31T00:05:39  skinspec=sentinel-b  skin_sha=a6d3342f636f1040
       12 rgs_reference_main + 4 rgs_restirgi + 77 dxil HITs
       **0 ms_empty_main** (correct — B patches none)
       0 ser_reject   manifest: sentinel-b ... ref=12(10 sentinel-clone + 2 pass-through)

Settings identical across both and **proven, not trusted**: `ab_settings.py`
reports the last `UserSettings.json` write 4277 s before the first capture.
PT on, PT-in-photo-mode on, **Ray Reconstruction off**, DLSS Balanced,
RayTracedLighting Psycho, 2560x1440.

## 2. Rung B — the measurement

Paint is `OpSelect` to **(0, 10, 10)**: R crushed, **G == B**. A natural blue
sky is **B > G > R**. Those two signatures are separable and they separate.

    region                RGB                    R/(GB avg)   painted?
    face, lit cheek       [ 36.8 159.6 161.4]      0.229      YES  (G==B)
    face, shadow side     [ 39.8 176.3 174.8]      0.227      YES
    bush                  [ 61.6 169.0 162.8]      0.371      YES
    distant city          [ 51.1 112.6 113.0]      0.453      YES
    jacket                [ 90.4 166.0 166.1]      0.544      YES
    bare tree             [122.4 178.3 181.3]      0.681      partial
    sky (clear, upper L)  [ 87.9 135.8 157.8]      0.599      NO — B>G by 22, blue intact
    cloud                 [167.5 187.8 186.7]      0.894      NO
    ground dirt (fg L)    [139.0 142.1 126.1]      1.036      NO
    ground dirt (fg R)    [152.0 150.4 133.4]      1.072      NO
    distant hills         [151.9 144.6 133.2]      1.094      NO

**Why this is the pass and not the disqualifying outcome.** The readback
predicate is `word0 != ARM`, and word0 is armed to `0x5EA71E51` in the entry
block, which dominates every path. Paint therefore *implies* the payload was
written, which implies the injected trace executed and the CHS wrote to it.

`55` §4 pre-registered **"cyan everywhere incl. sky"** as a readback defect or
payload aliasing — *treat as build bug, do not interpret*. The sky is **not**
painted. Sky pixels are where the primary ray misses; the injected clone (all
operands verbatim) misses too; rung B's *unpatched* `ms_empty_main` writes
nothing; word0 stays ARM; nothing paints. **The identity-when-dead control
fired correctly on the sky in the same frame that paints the geometry.**
Aliasing is excluded by observation, not by argument.

## 3. Rung A — dark, and the escape hatches that were closed first

The audit's `dispatched raygens` line for launch A named no `rgs_reference_main`.
That was checked and is **not** evidence of anything:

- `trace_rays` is deduped **per VkPipeline** through a cb→pipe table capped at
  `MAX_CBBIND 1024` (`swap_layer.c:728`). Once full, new command buffers are
  never registered and their traces are never logged. All 9 `trace_rays` lines
  in launch A fall in one early burst (seq 4641–4662 of 7256 journal lines).
- 51 RT pipelines were **built** that launch; 8 got a dispatch record.
- `rgs_restirgi_*` has appeared in **no** launch's dispatch list, ever — yet
  `gi-50`'s restirgi splice is confirmed on screen (`50` §6). The list is a
  sample, not a census. **Do not read absence from it as non-execution.**

Second hatch, also closed: only 10 of the 12 ref permutations are painted. The
two pass-throughs are `40c6faab52a13874` and `ab7f1822eeb0331b` — the atomic
pair `55` §2 flagged as having no radiance write. **All 10 painted permutations
built pipelines in launch A**, including `d622fb9e1dcb8cd0` and
`4270b745d11a5e8a`, the two `24` §T1.4 recorded actually dispatching and
tracing. The dispatching permutations are painted ones.

So A is genuinely dark, and per `55` §4 the failure is localised to the **miss
path**: cullMask 0 + a patched `ms_empty_main` handshake. B differs in exactly
one operand (cullMask 255) plus using the stock CHS, and works. Candidates,
none of which need chasing now: SBT miss-0 is not this library's
`ms_empty_main`; the handshake `OpSelect` did not take; or a cullMask-0 trace
does not invoke a miss shader here at all.

**Do not spend a launch diagnosing A.** Transmission needs CHS→payload (hit
distance), which B proves. `55` §4's own instruction: A's miss-0 assumption
gets one follow-up look *only if a miss-written term is ever needed*.

## 4. What this overturns — `GOTCHAS` correction

`GOTCHAS.md` §"Verify the mechanism before building the matrix" asserts flatly:

> **A second `OpTraceRayKHR` spliced into a raygen shader does not execute** in
> this game under vkd3d-proton.

That is now **false as written**, and the correction is applied in place. It
rested on **one** sample: `sctrl` (`26` §7d), in the **shadow** pipeline family,
with payload and SBT indices chosen by hand. `55` engineered that difference
out by cloning every operand by id from a trace that demonstrably executes, one
instruction later. In the **reference** family, that executes.

Therefore, of `26` §7d's three hypotheses:

- **H1** (recursion/pipeline depth limit) — not excluded, but not needed.
- **H2** (vkd3d-proton/driver restriction on multiple static sites) — **DEAD.**
- **H3** (wrong SBT indices for the second call) — **the surviving explanation**
  for `sctrl`, and the reason clone-by-id works.

**Scope discipline — the limit of this result.** Both rungs put the injected
trace in a **raygen**. Neither tests a second static site in a hit or miss
shader, and neither retests the *shadow* pipeline family. The honest claim is:
*a second static trace site executes in the reference raygen family when every
operand is cloned from a live trace.* Do not let this become a new
over-broad GOTCHA in the other direction — that is exactly how the first one
was written.

## 5. Open, and NOT gating anything

Terrain — ground **and** distant hills — is the only unpainted geometry in B.
Everything else painted. Candidates: terrain is shaded by one of the two
unpainted pass-through permutations, or its radiance write is among the sites
the patcher skipped (constant-zero early-outs, scalar hit-distance writes).
Answerable offline from the per-module `rgs.report.json` skip lists plus the
`rt_pipeline` permutation list — no launch. Irrelevant to ear glow, which is
class-1 skin only, and skin is the **most strongly painted surface in the
frame** (R/(GB) = 0.227, the lowest sampled).

## 6. `55` §5 is wrong about `ptreg` — corrected in place

`55` §5 step 1 lists the settings contract as "standing PT switches
(`ptbounce/ptrefl/ptmsggx` on, `ptclamp` on, **`ptreg` off**)". Following that
literally **wastes the launch**: sync refuses the rung and `skinspec` reads
`off:gi-stale-ptq`.

`ptreg` contributes the `r` to the ptq combo letters
(`sync_settings.sh:217`). The sentinel MANIFEST carries
`ptq_sha=55ed4e5c6884ab71`, which is the **`rcbm`** base — `ptreg` **on**. With
it off the combo is `cbm`, sha `3f8facb8314ede95`, and `gi_refuse` fires.

The doc confused `ptreg`'s **look** verdict (dead, `46` §18) with its **combo
letter**, which is load-bearing for every parked raygen-bearing rung. Both
launches ran with `ptreg=on` and were accepted. Fixed in `55`.

## 7. What is now unblocked

`51` §7 step 3, unchanged and now buildable: short ray along −L from the skin
hit ⇒ measured thickness ⇒ transmission term in the raygen. Per-channel
extinction from the same Jensen skin1 set as `52`/`53`
(ld = 3.67 / 1.37 / 0.68 mm), so a ~5 mm ear transmits red and kills green and
blue — **the saturated red glow is the spectral falloff, not a tint knob.**
Measured thickness kills `39`'s forehead-scores-like-an-ear defect;
non-tile-quantised RT output kills its blocky grid. Both `39` defects die
structurally rather than by tuning.

Machinery: `50` §1 and `dev/build_gi_bleed.sh` are the site/serve templates;
`55`'s clone-by-id splice and armed-word handshake are how the thickness ray is
injected and reports back. Ship as an optional rung with an A/B control, per
house rule. **It is not working until an on-screen A/B says so.**

## 8. Confidence

| claim | confidence |
|---|---|
| the injected static trace executed in the reference raygen family | **certain** — paint requires a payload write; sky control clean in the same frame |
| payload round-trips raygen→CHS→raygen | **certain** — same |
| A's failure is the miss path, not the trace | **high** — B differs in one operand plus the stock CHS |
| H2 is dead | **high** — one family is a counterexample to a universal claim |
| the result generalises to hit/miss stages or the shadow family | **untested — do not assume** (§4) |
| traced thickness will look good | **unknown — that is an A/B, not a gate** |
