# 89 — Bounce floor: the path loop's bound raised in all 12 permutations, three rungs, never launched (2026-09-01)

The brief, verbatim: *"Could this bug also be from us overriding the number of
light bounces? I'd like the path traced lighting to bounce at least 3 times."*

Two separate things. §1 answers the diagnostic question (**no**, but the
question found a real bug — §2). §3 onward is the feature. **Nothing here is
on screen. There is no verdict until a one-variable A/B says so.**

## 0. State — SHOT TWICE, and the verdict is REVERTED

**`-b3` is out. It reads as SUPER NOISY.** User's words, second look: *"b3
makes things SUPER noisy. Lets try removing it again."* The live selection is
back to `gi-50b-bleed-oil-sheen-deep-clothhi`. The rungs stay built and parked;
nothing is deleted, because §5b says exactly when they would pay.

**§5 under-stated the cost and this doc owns that.** It said more bounces "does
not reduce variance and is not a fix for noise". That is true and insufficient:
an extra bounce is an extra *stochastic path segment*, so at a fixed sample
count it **adds** variance — it is not noise-neutral, it is a noise SOURCE. At
`RayNumber = 1` that is the dominant visible effect and it swamps the indirect
light it buys. Written before the launch as a warning about what the rung
*cannot* do; it should have been a warning about what it *does*.

### The first look, kept for the record

**`-b3` was initially read as a clear win.** *"I couldn't tell the difference
just setting the CET settings. -b3 is much better."* User's words: *"I couldn't tell
the difference just setting the CET settings. -b3 is much better."* The live
selection is now `gi-50b-bleed-oil-sheen-deep-clothhi-b3`. Deployed
(`make install` ran 12:20:24), parked, verified live.

Deploy check on the reading launch (the `45` rule): the run's `rt_pipeline` /
`pipe_stage` records name every reference permutation with `swapped:1`,
**including `d002cc05` and `d622fb9e`** — two of the four that baked the bound
and that no CVar can reach. The bytes under the verdict are the patched ones.

**The null CVar half is itself the result.** `BounceNumber` /
`BounceNumberScreenshot` produced no visible change; the patch, which is the
same number applied deterministically to 12/12, produced an obvious one. That
is precisely what §3's census predicts — the CVar moves 8 of 12 and which
permutation gets dispatched changes per launch, so across a session it averages
out to "can't tell". It also closes `pt_engine.lua`'s open question in both
directions at once: the wire is real (§4) *and* useless on its own.

⚠ **The `-b2` control was NOT shot.** The A/B was `-b3` against the standing
base, not against `-b2`. The two rungs differ only in one `%uint` constant, so
the exposure is small, but the identification is not yet closed the way §7 §1
demands. One shot of `-b2` still owes: it must be indistinguishable from
`-clothhi`.

⚠ **`-b3` carries NO cavity term.** The `b` rungs are built on `-clothhi`, not
on any `cone` rung, so selecting `-b3` silently dropped `88`'s cone. Whatever
was judged here was judged without it. This is the reason §9's rebuild question
exists.

### 5b. When the floor WOULD pay

The noise verdict was read at **1 sample per pixel**. Extra bounces buy
indirect light and cost variance, so they pay only where the variance is paid
for separately:

- **`RayNumber` / `RayNumberScreenshot` raised**, or
- **reference accumulation on** with a pinned camera, which converges the
  variance away for free and leaves the extra bounce as pure gain.

That is a photo-mode combination, and it is the only configuration in which
`-b3` should be re-tested. Do NOT re-test it at 1 spp; that experiment is done.

| rung | N | what it isolates |
|---|---|---|
| `…-deep-clothhi-b2` | **2** | **the control.** Restates the shipped default. Must be indistinguishable from `-clothhi`. If it is not, the loop identification is wrong and nothing below is safe. |
| `…-deep-clothhi-b3` | **3** | one more path segment. The ask. ~+50% path work. |
| `…-deep-clothhi-b4` | 4 | the depth axis, photo mode only. |

Required game settings, stated **before** the launch and never inferred from
the capture afterwards (the `45` rule):

- **PT Overdrive on**, **PT-in-photo-mode ON** — this loop is in
  `rgs_reference_main` only. Without photo-mode PT the rungs are inert.
- **Ray Reconstruction OFF**, DLSS **Balanced**, RayTracedLighting **Psycho**,
  **2560×1440**, photo mode, **camera pinned**, both halves the same frame.
- **`BounceNumber` / `BounceNumberScreenshot` left at their defaults (2)** in
  the CET panel for the whole A/B. The patch is a `UMax` floor, so a CVar set
  higher silently wins and the two halves stop being one variable apart.
- Pick a frame with **visible indirect bounce light** — a wall-bounce onto a
  shadowed cheek, a bright floor under a face. A face lit only by direct sun
  and sky cannot show a third bounce and will read as a null result.

`brdf_params.txt`, the live file with **one line changed**:

    skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-b3

## 1. The diagnostic answer: no, nothing in this stack overrides bounces

`88` §5c's area-light over-darkening cannot come from a bounce override,
because until this doc there was no bounce override. Checked, not assumed:

- `grep -rln "SLessThan\|ULessThan" dev/*.py` returns exactly one patcher,
  `dev/patch_skin_spp.py`, and that one retargets the **sample** loop.
- No rung in the standing chain (`50b` → `bleed` → `oil` → `sheen` → `deep` →
  `clothhi`) touches any loop bound. `dev/verify_bounce.py --negative` on the
  base is CLEAN across 12/12 modules: no `UMax` anywhere near the bound.
- It would not survive the differential anyway. `-cone2all` vs `-cone2` is one
  variable; a bounce count wrong in both halves cancels.

## 2. What the question actually found: `find_bounce_counter` returns the SAMPLE counter

`rgs_reference_main` carries **two nested counted loops**, both of whose bodies
contain the sun NEE trace. Every previous doc has treated them as one.

| | bound | header phis | latch |
|---|---|---|---|
| **outer** | `bitcast(cbv[188])`**`.y`** | 8 fp phis, **all seeded 0** | sums, firefly-clamped `NMin 1024` → **the SAMPLE loop** (`RayNumber`) |
| **inner** | `bitcast(cbv[188])`**`.z`** | 23–34 fp phis, **exactly 3 seeded 1.0** | multiplies the throughput down → **the PATH loop** (`BounceNumber`) |

The three phis seeded to `1.0` are the RGB throughput. That is the
discriminator, and it is clean in all 12 permutations: **3** on the path
header, **0** on the sample header, no ties. Independent confirmation: in the
4 permutations where the bound is baked, the folded literal is **2** — exactly
`BounceNumber`'s shipped default — and in those same 4 the sample loop is gone
entirely, folded flat by `RayNumber = 1`.

`dev/patch_earglow.py`'s `find_bounce_counter` documents its tie-break as
*"Outermost (earliest header) wins if nested loops both qualify"*. Outermost is
the **sample** loop. So:

> **`88`'s cavity gate and `79`'s ear glow gate on `sample == 0` in 5 of the
> 12 permutations** (correct in the other 7 — see `90` §1 for the per-module
> split). Which one a launch gets is a coin flip.

With `RayNumber = 1` (gameplay, and the default), `sample == 0` is *always
true* — so in those 5 permutations both terms run at **every bounce**, not just
the primary hit, and in the other 7 they behave as documented. That
is a live candidate explanation for `88` §5c: a darkening meant for the primary
hit, applied once per bounce, compounds. It also predicts that both terms get
*weaker* as `RayNumber` rises in photo mode, which is testable in the panel
without rebuilding anything. **Fixed for the cavity term in `90`**, which also ships the
control that measures it. `79`'s ear glow still carries it.

A first pass in this doc made the same mistake, anchoring the bound search on
`find_bounce_counter` and reporting a bogus "5× component 1 / 3× component 2"
split. `29` §B3's `.z` was right all along. The detector was rewritten to find
the loop structurally, with no counter-phi anchor at all (§4).

## 3. The edit

    bound' = UMax(bound, N)

`UMax`, not a store. A CVar set above N still wins: this raises a floor and
never caps anything. One `OpExtInst` and one operand rewrite per module —
**one line added**, plus the `%uint_N` constant if the module lacked it.

Reach: `rgs_reference_main` **only**, 12/12. All 77 compute and all 4
ReSTIR-GI modules are byte-identical to the base and `cmp`-asserted so.

Census from the shipped base, printed by the build every run:

    runtime  OpCompositeExtract %uint <bitcast cbv> 2    8/12  (CVar-reachable)
    LITERAL  OpConstant %uint 2                          4/12  (4103c886,
                                                                996a3b16,
                                                                d002cc05,
                                                                d622fb9e)

## 4. Why a patch and not the CVar — and use the CVar first anyway

`BounceNumber` / `BounceNumberScreenshot` are already in the CET panel
(`pt_engine.lua`), and §3's census settles the open question that panel's
header was written around: **the wire is live**, into 8 of 12 permutations,
straight into the path loop's bound. Ultra Plus's `0xDEADBEEF` verdict was
wrong about two-thirds of the shader.

So try the panel first. It costs nothing and it moves the same number. What it
cannot do is the other 4 permutations, which folded the bound to 2 at compile
time — and since the dispatched permutation changes per launch (`88` §1), the
CVar alone gives a bounce depth that is **a coin flip per run**. That is the
whole reason this patch exists: it makes the floor deterministic. The panel and
the patch stack cleanly (`UMax`), which is exactly why the settings contract in
§0 pins the CVar at its default for the A/B.

## 5. What this is not

It adds indirect **depth**, not samples. A third-bounce contribution is dim and
already the smoothest part of the image; it does not reduce variance and it is
not a fix for noise (that is `77`/`RayNumber`). It costs rays: the loop body is
a whole path segment, so `-b3` is roughly **+50% path work** against the
shipped 2, unpaid by any importance heuristic.

**Uncertain, and say so.** The test is `bounce + 1 < bound`, so `bound = 2`
runs indices 0 and 1. Whether CDPR calls that "2 bounces" or "1 bounce plus the
primary hit" is not established, so N means *"N iterations of this loop"* —
possibly 3 or 4 bounces in the UI's vocabulary. A throughput / russian-roulette
early-out inside the body could also terminate a path before the bound; that
would make `-b3` and `-b4` look identical, and is the first thing to suspect if
they do. The ladder exists so this is read off the screen, not argued.

## 6. Verification

`dev/verify_bounce.py` re-derives everything from the **shipped bytes**, with
no help from the patcher — it re-finds the path loop by the throughput
discriminator, then asserts:

- the bound is `OpExtInst %uint <glsl> UMax <inner> <floor>`, `floor` **by
  resolved value** == N;
- `inner` is the **same kind** the base carried — a literal keeps its value, a
  runtime extract keeps its component index, so a rung can never silently drop
  the engine's own CVar wire on the floor;
- the compare sign is unchanged;
- exactly one line added, plus the constant only if the base lacked it —
  nothing else may move;
- the non-path loop seeds **zero** unit phis and the path loop is **nested
  inside** it, so the discriminator is not merely an argmax.

Build gates, all in `dev/build_bounce.sh`: base provenance `cmp` 93/93 against
the parked standing rung; negative control on the base; **`--n 0` identity
control** (every detector runs, nothing is emitted, 12/12 byte-identical);
12/12 bound coverage with exactly 1 rewrite each; 81/81 verbatim `cmp`; a
per-module assert that the patched raygen is **not** identical to the base;
93/93 `spirv-val`; then the verifier. Green on all three rungs.

## 7. The ladder

1. **`-b2` first.** It must be indistinguishable from `-clothhi`. This is the
   only step that tests the identification, and it is not optional.
2. `-b3` vs `-b2`, same frame, camera pinned. Look at shadowed skin lit by
   bounce, not at directly lit skin.
3. `-b4` only if `-b3` reads as a win, to find where it stops paying.
4. Frame time on every rung. `-b3` at ~+50% path work is a photo-mode knob
   until measured otherwise.

## 8. Files

| file | what |
|---|---|
| `dev/patch_bounce.py` | the patcher; `--n 0` is the identity control |
| `dev/verify_bounce.py` | shipped-bytes verifier; `--negative` |
| `dev/build_bounce.sh` | 3 rungs + every gate above; `--install` parks |
| `init.lua` | 3 selector rows after the `88` cone block |
| `swaps.gi.50b-…-clothhi-b{2,3,4}` | the rungs, 93 modules each |

## 9. Open

- **Promote `-b3` to the standing base?** It is a keep, but every other live
  rung (`88`'s nine cones, `84`'s env bleed, `85`'s cavity) is built on
  `-clothhi` *without* the bounce floor, so they cannot currently be combined.
  Rebuilding the ladder on a `-b3` base is the fix, and it is the same rebuild
  the gate fix below needs — do both in one pass, not two.
- **`-b2`, one shot.** The control that was skipped. §0.
- **`-b4`**, to find where the depth stops paying, and frame time on both.
- **`88` §5c / `79`: the `sample == 0` gate.** §2. Highest value item here —
  and now MORE urgent, not less: at a floor of 3 bounces a term that wrongly
  runs every bounce compounds over three, not two.
- Whether N iterations = N bounces in the UI's vocabulary (§5).
- Whether a russian-roulette early-out caps the path before the bound (§5).
- `make install` still not run; it will also carry `84`'s env-bleed rows,
  `85`'s rows, `88`'s nine cone rows and `82`'s `detail_engine.txt` step.
