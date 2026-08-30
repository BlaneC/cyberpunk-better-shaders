# 47 — Process trace of the 2026-08-30 afternoon A/B session (L1–L8)

**Written for a peer reviewer.** `46` §11–§18 is the *result* record, written
incrementally as each launch landed. This document is the *decision* record:
what I believed at each step, why I chose the next launch, what I predicted,
and where I was wrong. It deliberately preserves reasoning that was later
overturned, in sequence, because the review question is whether the process
was sound — not just whether the surviving numbers are.

Read `46` §18 for where things landed. Read this for how.

Eight launches, 14:45 → 16:53. Two of my conclusions were withdrawn during
the session and one of my launch-queue decisions was reversed. Both failures
have the same cause, called out in §6 below.

---

## 1. Inherited state and the first correction

`46` §1–§10 recorded six launches (E0, E1, E2a `rough-1.3`, E2b `gloss-0.7`,
plus two earlier), peer-reviewed in §9, with a queue L1–L4 defined in §9.4.
The standing claims I was handed:

- `rough-1.3` and `gloss-0.7` add +35% / +48% fine skin texture (§5.2)
- the shipping default *costs* 15.9% of skin texture vs vanilla (§6.2)
- tier-1 `c1` is absent on bounce-lit skin — `42` reopened (§6.1)
- no noise floor had ever been measured

**Pre-flight** (`make check`, ladder inventory, `ser.set` src_sha vs ptq base,
kernel presets, `cmp` of `init.lua` / `pt_engine.lua` / `sync_settings.sh` /
layer `.so`): all clean. One discrepancy — **§10 claimed the params file was
at the E1 config; it was actually at `skinspec=gloss-0.7`** from the 13:50 E2b
launch. Corrected before L1. Minor, but it is the class of thing that silently
mis-attributes a launch, so it is logged.

I also wrote `a-b-testing/collect.sh` (pull the N newest photo-mode captures
into a rung dir in shooting order) because the same pickup was going to happen
four or more times.

---

## 2. L1 — the null relaunch, and the conclusion I got wrong

**Decision.** Run §9.4's L1 unchanged: a byte-identical relaunch of E1, to
measure what two identical launches disagree about. This was the right call
and I would make it again — the project had six launches of published numbers
and zero floor.

**Serve verified** before looking at pixels: `skin_sha=0d0f3ee45ea0d538`,
`payload=225acb871d94a4b8`, 77/12/10/3 HITs, 0 `ser_reject` — identical to E1.

**What I measured (E1 → L1):**

| | S1 | S2 | S3 |
|---|---|---|---|
| mean `dLum` | +1.232 | −0.061 | −0.020 |
| fine texture | +58.5% | −0.4% | −25.6% |

**What I concluded, and published as §11:** S1 and S3 have a floor larger than
every effect ever measured in them; S2 is the only trustworthy scene. I
rendered difference heatmaps, saw dense pore-scale speckle over the whole face
with flat static controls and 0,0 alignment, and wrote §11.4: *"the floor is
Ray Reconstruction resolving different pores between runs."*

**Consequent queue decisions:** dropped L3 (`ptclamp=off`) on the grounds that
its only motivation — §6.2's −15.9% — was inside the floor; promoted L4 from
one launch to two, so the RR-off *floor* would be measured rather than just
the RR effect.

**This was wrong.** Not the measurement — the two frames really do differ that
much — but the *attribution*. I had two samples and treated their difference
as a property of the process, without asking whether one of the two was
anomalous. See §5.

**What I should have done at this exact point:** run the same texture metric
on a non-skin region of the same frames. It costs one command, it was
available, and it would have shown immediately that sky and terrain had moved
too — which no skin overlay can cause. I did not think of it until L4a forced
it three launches later.

---

## 3. L2 — a static pre-flight that changed the experiment, and a good user catch

### 3.1 The pre-flight find (`46` §12)

Before staging L2 I checked what `skinspec=probe-cls` would actually serve.
**76 modules, where every skin rung has 77.** The missing one was
`ab0bc2fee876d489` — which `46` §9 c2 had named as one of "the two GI
resolvers" and used to *exclude* the "the lift missed the module" hypothesis.

I reproduced the decline (`no image write reachable for the hunt`) and then
disassembled it:

| | `ab0bc2fe` | `99bb7c26` |
|---|---|---|
| sole `OpImageWrite` target | `OpTypeImage %int 2D … 2` | float 2D |
| value written | `v4uint` → `OpBitcast %v4int` | `v4float` |
| components | `OpSelect(valid, RoundEven→ConvertFToS(f), 0xFFFFFFFF)` | radiance |
| guards | `IsInf`/`IsNan`, `ULessThan … 2`, `&255`+1 counter | none |
| workgroup/subgroup | LDS, `%SubgroupSize`, `LocalSize 32 16 1` | none |

Census: **76 of 77 write `v4float`; exactly one writes `v4uint`.**

Conclusion: `ab0bc2fe` is a sample-index / reservoir pass (ReSTIR-shaped),
not a radiance resolver. It matches the (1/π, 0.107508637) anchor because it
evaluates the material stack to compute a reuse *weight*. §9 c2's exclusion
does not hold; there is **one** colour-writing resolver in the anchored set.

**Reasoning about whether this breaks L2.** My first instinct was that L2 had
become a false-negative trap — the probe cannot paint `ab0bc2fe`, so an
unpainted face would be ambiguous. I then rejected that: `ab0bc2fe` has no
colour output at all, so it cannot paint by *any* mechanism and is not a
competing explanation for an unpainted face. L2's negative case is therefore
*cleaner* than §9.4 assumed, not muddier. I ran it.

This is the one step in the session I would hold up as done right: a static
check, costing no launch, that corrected a peer-reviewed claim and sharpened
the experiment before it ran.

### 3.2 The user caught a design flaw

I initially staged L2 as "S2 only", following §9.4 literally. The user asked
*"you just need the S2?"* — and the answer was no. I revised to S1 + S2:

- **S1 is the positive control.** With S2 alone, an unpainted face could mean
  "the gate fails on bounce-lit skin" *or* "the probe didn't work this
  launch". Not separable.
- **S1 answers E5 for free.** The palette paints class 8 violet, and E5's most
  valuable outcome (`45` §3) is finding out whether the eyes are class 8 at
  all.

A single-scene probe launch with no positive control was a real design error
and the user's question is what caught it. Logged as such.

### 3.3 Results and the reading

Serve verified: **dxil ×76** — exactly as §12 predicted — `skin_sha=53722d3d833238ab`.

User's unprompted report: *"S1 showed the red on skin and pink in plants. The
red only shows up from sunlight. S2/3 dont have that colouring."*

Measured, with a non-skin control (which by this point I was using):

| scene | skin px painted beyond the null's p99.9 |
|---|---|
| S1 | **25.8%** |
| S2 | **0.0%** (skin median −0.354, *less* red than non-skin) |
| S3 | **0%** — its +0.131 matched non-skin's +0.119, i.e. global |

S3's apparent paint was the probe tinting GI scene-wide: painted surfaces
bounce painted light onto unpainted ones. Worth remembering for any future
probe launch.

Paint strength vs illumination (S1 skin, R−G of the ratio):

| baseline lum | probe | null |
|---|---|---|
| 11–94 | +0.008 | +0.003 |
| 94–117 | +0.041 | +0.003 |
| **117–139** | **+0.285** | +0.003 |
| **139–209** | **+0.317** | +0.011 |

A step function, not a ramp.

**Conclusion:** the class gate passes on skin — hypothesis (a) is dead — but
the painted modules write only the **direct-light term**. Bounce-lit radiance
comes from a writer outside the painted 76 → **§6.1 hypothesis (b)**. `42`
does not close: the commit *"Skin BRDF was direct-light only: lift the class
gate into the GI resolvers"* did not achieve its goal.

### 3.4 My error on the eyes

I looked at a zoomed eye crop and reported the eyes were **not** violet, and
that E5 was therefore predicted null. The user pushed back: *"eyes have a tint
of violet in them but only from the sun barely clipping them, look again."*

They were right. Quantifying against the null pair:

- 267 px with `B−G > 0.35` vs the null's 132 in the same box
- **30 px above the null's maximum** (+0.893), clustered on both upper lash
  lines, y-band 555–588
- mean L1 `[46.5, 36.9, 15.8]` → L2 `[75.8, 57.2, 44.6]`: **blue ×2.82**
  against the palette's ×3.0, red ×1.63 against ×1.5

A side-by-side against the unpainted launch showed the sclera turning violet
and the lower lashes turning **yellow** (class 4 = hair — a clean internal
consistency check).

**Why I got it wrong:** I judged a sparse, sub-1%-of-pixels effect by eye on a
single crop, when the whole session was otherwise built on measuring against a
null. The correct move was the ratio test first, eyeball second. Note also
that the green channel does *not* fit a clean multiply model (it rises when
paint should crush it), so the 30-px result is real but the model is not
fully explained — a reviewer may want to attack this.

---

## 4. L4a — the failure that exposed §11

### 4.1 Verification caught it before a second launch was wasted

I staged L4 (RR off) and asked for two launches. After the first, the mod side
verified clean, but the journal cannot see game settings — so I read
`UserSettings.json`: **`DLSS_D: true`**. RR had never been turned off. I told
the user to stop rather than spend the second launch.

This is the verification discipline working. It is also the moment the session
turned, because a third same-config sample was now available.

### 4.2 Three samples beat two

L1 ↔ L4a differed *far less* than E1 ↔ L1:

| pair | S1 mean | S1 fine texture |
|---|---|---|
| E1 → L1 (my "floor") | +1.232 | +58.5% |
| L1 → L4a | +0.166 | +6.1% |

That asymmetry is only explicable if one capture is anomalous. I finally ran
the check I should have run at L1 — **the same metric on non-skin**:

| capture | time | non-skin fine | vs E0 |
|---|---|---|---|
| E0 | 12:59 | 5.881 | — |
| E1 | 13:19 | 5.721 | −2.7% |
| E2a | 13:38 | 6.583 | **+11.9%** |
| E2b | 13:53 | 6.987 | **+18.8%** |
| L1 | 14:47 | 6.600 | **+12.2%** |
| L4a | 15:39 | 6.785 | **+15.4%** |

**Static geometry gained 12–19% fine energy between 13:28 and 13:36 and stayed
there.** No skin overlay can do that. Something changed in the renderer —
most likely a graphics setting (DLSS preset or `DLSS_NewSharpness`, currently
0.25); the settings file stores only current state so the history is gone.

Call pre-13:30 **regime A** (E0, E1) and post-13:30 **regime B** (E2a, E2b,
L1, L2, L4a, and everything after). **Every E1-baselined figure in `46` §5
straddles the break.**

### 4.3 What I withdrew and what I reversed

- **§11.4 withdrawn outright.** "RR resolves different pores" was read off a
  heatmap spanning the break. RR remained untested.
- **§11.1's floor figure withdrawn.** True within-regime floor (L1→L4a): S1
  mean +0.166 / texture +6.1%; S2 +0.043; S3 mean +0.449 / texture +9.3%.
- **E2 rungs re-measured inside regime B, with a non-skin control:**
  skin-specific movement `rough-1.3` +1.4 pp, `gloss-0.7` +5.1 pp, against a
  null-to-null +3.3 pp. **Still dead — but for the right reason** (a ~6% floor
  plus a contaminated baseline, not a 58% floor).
- **§11.3 survived and strengthened**: S2's floor is +0.043 with a
  within-regime null, and the E2a→E2b differential (both regime B) gives a
  flat face with **+3.23%** on the top-3% highlight against a null top-bin of
  −0.95%.
- **L3 reinstated.** I had dropped it using the invalid cross-regime floor.
  §6.2 was *unproven*, not disproven.

---

## 5. The pivot: why I stopped chasing RR and went for vanilla

The user asked, in plain terms, what to do and whether RR should be on. My
answer was: **leave RR on, touch nothing, and shoot vanilla instead.**
Reasoning, in the order it mattered:

1. **Settings changes are what broke the data.** Having just discovered a
   settings-induced regime break, deliberately introducing another one
   mid-investigation was the wrong risk.
2. **The headline question was unmeasurable.** Two mod-default captures
   existed in regime B and zero vanilla ones. "Does the mod change anything
   you can see" could not be answered at all.
3. **Cost asymmetry.** Vanilla is one launch and answers a product question;
   the RR floor is two launches and answers a methodology question.
4. **Ordering.** Do all RR-on work first, then switch deliberately as a block.

I consider this the best decision of the session. It converted a stalled
methodology chase into a chain of five launches that each answered something.

---

## 6. L5 → L8: the elimination chain

Each launch from here carried an **explicit falsifiable prediction written
before it ran**. Two of the three predictions failed, which is why the chain
converged instead of wandering.

### L5 (16:08) — vanilla in regime B

Verified `payload=d2dfb3f53119172b`, 0 HITs — identical fingerprint to the
12:38 E0. Saved by the user into the `L4b-rr-off` dir with `DLSS_D` reading
`false` afterwards, so I had to establish whether RR was off *during* capture:
S1 non-skin **6.581** against L1's **6.600** (0.3%) on a metric where the
regime break moved 12–19%, plus a visually identical terrain crop. **RR was on
during the shots, toggled after.** Refiled as `L5-vanilla-regimeB`.

Results — the first valid mod-vs-vanilla measurement the project has:

| S1 baseline tone | mod effect | floor |
|---|---|---|
| 10.6–88.2 | +0.21…+0.26% | +0.35…+1.14% |
| 88.2–106.4 | +0.43% | +0.14% |
| **106.4–135.1** | **+1.83%** | +0.23% |
| **135.1–166.5** | **+1.66%** | −0.59% |

**The mod brightens only the lit half of the face**, switching on at ~106
luminance — independently reproducing L2's paint threshold of ~116 from a
completely different instrument. S2 at/near floor with the wrong sign for c1
(§6.1 stands). S3: mean −0.478, bright bins −3.91% / −6.90%.

Texture: **S1 skin-specific 0.0 pp and +3.3 pp → the mod costs no skin texture
in direct sun.** §6.2's headline is retired on evidence. S3: non-skin −9.6% /
−9.9%.

**Hypothesis formed:** `ptclamp`. A firefly clamp clips bright outliers, which
in a dim sample-starved scene is most of the high-frequency energy.

### L3 (16:26) — `ptclamp=off`. Prediction FAILED.

Verified `ptq=rbm`, RR on (S1 non-skin 6.667, in band). S3 non-skin **2.441**
against 2.431 / 2.424 with the clamp *on* — **no movement**. The clamp *was*
convicted of dimming (mean vanilla→mod flips −0.478 → +0.153; bright bins
−3.91→−2.30, −6.90→−5.11), but exonerated for the detail loss. §6.2's
mechanism is wrong.

**Next hypothesis:** `ptreg` — path regularization literally trades
high-frequency variance for smoothness.

### L6 (16:37) — `ptreg=off`. Prediction FAILED again.

Verified `ptq=cbm`. S3 non-skin **2.458** — ~1 pp. Cleared.

**Second metric withdrawal, found here.** L1 and L4a (identical config) give
S3 *skin* fine energy **1.574 vs 1.720 — 9.3% apart**, while the same pair
gives S3 non-skin **0.3% apart**. S3's skin mask is small (57,883 px, 23.9% of
crop) on the noisiest surface in the dimmest scene. **Every S3-skin figure in
§14–§15 was inside its own floor** and was withdrawn, including the
"skin loses 11–18 pp beyond the scene-wide loss" claim I had made two steps
earlier. S3 non-skin stands.

**Decision point.** Four mod samples now clustered within 1.4%; vanilla sat
+10.3% above — on **one** sample. I applied the rule I had written into
`GOTCHAS` that same afternoon (*a rung is not measured until a null relaunch
of the same config has been measured*) and spent the next launch on repeating
the baseline rather than continuing elimination. Given §11 had just been
withdrawn for exactly this error, continuing would have been indefensible.

### L7 (16:45) — vanilla repeat. The effect is real.

| | n | mean | spread |
|---|---|---|---|
| vanilla (L5, L7) | 2 | 2.708 | 1.4% |
| mod (L1, L4a, L3, L6) | 4 | 2.438 | 1.4% |

Difference **−9.9%**, **7.3×** the larger within-cluster spread, **no
overlap** (vanilla min 2.689 > mod max 2.458). Dim light only — S1 shows
vanilla 6.581/6.456 against mod 6.600/6.785, fully overlapping.

**Next hypothesis, on mechanism rather than elimination:** `ptbounce`. The
bounce cull mask 1→255 puts far more geometry into indirect paths → better
converged GI → an effect that appears only where indirect light dominates.

I also wrote the noise-vs-detail caveat into §17.3 *before* the launch, and
asked the user for an eye verdict at the same launch that identified the
switch — specifically so the interpretation would not be decided afterwards by
whoever liked their own hypothesis.

### L8 (16:53) — `ptbounce=off`. Confirmed.

**A near-miss first.** Journal read `ptq=rcm` but `payload=225acb871d94a4b8`
— identical to the default's. I almost discarded the launch as a
non-serve. Checking the overlay content directly: `swaps.ptq` hashed
`6fe05ecc3ab345df` = `ptq/rcm/base`. Correct serve. The payload field is
computed from `stat -c '%n %s %Y'` (name/size/mtime), so two different builds
with equal sizes and build-run mtimes collide. **Equal payload does not prove
equal bytes.** New `GOTCHAS` rule; cache eviction is unaffected (it keys off
the whole `want` string).

Result: S3 non-skin **2.796** — above *both* vanilla samples, **+14.7%** vs
the bounce-on cluster. One switch spans the entire gap. S1 unaffected.

**And the sign flips.** The user's verdict, given before knowing which switch
was under test: *"I like PT bounce. Like knowing there's more proper path
tracing happening. The effect is super subtle."* Combined with the mechanism
and the dim-light-only signature, the honest description is **the mod
converges dim-light GI better, and the fine-energy metric scores that
improvement as a 10% loss.** `ptbounce` stays on; params restored to default.

---

## 7. Where the results stand

**Replicated on both sides, surviving:**

- `ptbounce` converges dim-light GI: −9.9% scene-wide fine energy, 2 vanilla
  vs 4 mod samples, no overlap, one switch spans it. Interpreted as
  improvement (§18.2).
- The skin BRDF reaches **directly-lit skin only**. Two independent
  instruments, one threshold: paint probe ~116 lum, radiometric ~106.
- `42` does **not** close. The GI radiance writer for skin is not among the 77
  anchored modules.
- `ab0bc2fe` writes integer sample indices, not colour (§12); §9 c2 corrected.
- Material classes: skin 1, hair 4 (incl. eyelashes), plants 5, eyes 8.
- S2 is a low-floor scene (+0.043 mean, −0.4% texture); §6.1's S2 null is real.
- E2a→E2b differential: flat face, **+3.23%** top-3% highlight vs −0.95% null.

**Dead or withdrawn:**

| claim | why |
|---|---|
| §5.2 E2 texture gains (+35%/+48%) | cross-regime baseline; re-measured in regime B they are inside the floor |
| §5.1 E2 means (+1.40%/+1.37%) | same |
| §6.2 "default costs 15.9% of skin texture" | regime artefact; L5 shows 0.0 pp skin-specific in S1 |
| the `ptclamp` mechanism | L3: no movement |
| `ptreg` as a cause | L6: ~1 pp |
| §11.1 floor figure, §11.4 RR mechanism | §13: it was the regime break |
| all S3-**skin** texture figures | §16.2: 9.3% same-config floor |

**Metric reliability, measured (same-config floors):** S3 non-skin **0.3%**,
S1 non-skin **~3%**, S1 skin **~6%**, S3 skin **~9%**. Region choice matters
more than metric choice.

**Still open:** the real L4 (RR off, two launches — RR has never actually been
tested); the roughness fork (still `rough-1.3`, on the user's eye and the `33`
§2 wet-plastic argument, not on numbers); finding the GI radiance writer
(a static search, no launch needed); the probe legend decode (`45` E11).

---

## 8. Self-critique

**Both of my withdrawn conclusions have one cause: I trusted an unreplicated
baseline.** §11 treated E1 as a valid second sample of its own config; §14–§15
treated L5 as a valid vanilla baseline and computed skin-specific figures off
an S3-skin metric whose floor I had not measured. Both produced *confident*
wrong answers with mechanisms attached — §11.4 named Ray Reconstruction,
§14.3 named the firefly clamp — which is worse than a hedge, because a named
mechanism invites the next person to test it. In the clamp's case that is
exactly what happened, and it cost a launch.

The corrective that worked, both times, was the same and was cheap: **a
control region that the manipulation cannot affect**, and **a repeat of the
baseline**. Neither needed new tooling. I had `--mask` inversion available
from the first minute.

Ranked, my errors:

1. **§11's floor attribution** — the largest. Caused a wrong queue decision
   (dropping L3) that took three launches to reverse.
2. **§11.4's RR mechanism claim** — a causal story from a confounded pair.
3. **S3-skin figures in §14–§15** — quoted a metric whose floor I had not
   measured, in the same session in which I wrote a rule about exactly that.
4. **The eyes** — judged a sub-1% effect by eye instead of by ratio test;
   corrected by the user.
5. **L2 staged without a positive control** — caught by the user's question.
6. **Nearly discarding L8** on a colliding payload field.

What I would keep: verifying the serve before reading any pixel (it caught the
RR-still-on case before the second launch was wasted); the static pre-flight
that produced §12; writing falsifiable predictions before each launch; and
asking for the user's visual verdict at the same launch that identified the
switch, rather than after the interpretation was already leaning.

---

## 9. Where a reviewer should attack this first

Ordered by how much rests on them.

1. **The regime break is uncharacterised.** I never identified what changed at
   ~13:30, only that it did. Regime membership for every later capture is
   asserted from the S1 non-skin band (6.456–6.809). If a second, smaller
   break occurred inside regime B, the L5→L8 cluster comparison would absorb
   it silently. Test: re-derive the break using an independent statistic
   (e.g. mid/coarse bands, or a sky-only crop) and check it partitions the
   captures the same way.
2. **RR state during capture is inferred, never observed.** `UserSettings.json`
   records only state at process exit, and the user toggled RR repeatedly
   *after* shooting. For L5, L6, L7, L8 I concluded "RR was on" from S1
   non-skin sitting in-band. If that inference is wrong for even one capture,
   the vanilla and mod clusters are mixed and §17's separation is unsafe.
3. **The mod "cluster" of n=4 mixes three configs.** L3 and L6 differ from
   default by one switch each, and each switch was independently shown to move
   the metric ~1 pp. Pooling them tightens the apparent spread. A stricter
   reading uses only L1 and L4a (n=2, 2.431/2.424) against L5 and L7 (n=2,
   2.689/2.726) — still separated, but with n=2 on both sides.
4. **L8 exceeds vanilla** (2.796 vs 2.689/2.726) and I did not explain it. If
   `ptbounce=off` returns to vanilla behaviour, why is it higher? n=1.
5. **"Noise, not detail" is an inference, not a measurement.** It rests on
   mechanism + dim-light-only + one user preference. Nothing measured
   separates converged noise from authored detail. A real test exists
   (frame-to-frame variance at a fixed camera) and was not run.
6. **The two-instrument threshold agreement (~116 vs ~106)** uses different
   metrics with different bin edges. The agreement may be looser than §5
   presents it.
7. **The eye class-8 result is 30 pixels**, and its green channel contradicts
   a pure multiply model. Real, but thin.
8. **S2's old-character caveat still stands** (`46` §6.1). I tested whether a
   current-character E0→E1 S2 pair existed and it does not — SSD 283 vs the
   null's 6.7, controls swinging ±3 with sd 20. §6.1 still rests on the
   old-character pair.

---

## 10. Reproduction

```bash
bash a-b-testing/reproduce.sh     # sections 1-7 regenerate every figure quoted
./dev/ab_launch_audit.py 12       # per-launch layer verification
```

Captures: `a-b-testing/<rung>/S*.png`, one `CONFIG.md` per rung where written,
`LAUNCHES.md` for the serve record. `reproduce.sh` §5 is the L1 floor block,
§6 the regime break and the true floor, §7 the L5–L8 chain — **added by the
§11 review below; before it, the one replicated result of the day was the one
figure the reproduction script did not cover.**

Launch ledger for this session:

| # | time | config | journal | purpose |
|---|---|---|---|---|
| L1 | 14:45:50 | E1 exact | `rcbm`, sha 0d0f3ee4 | noise floor |
| L2 | 15:11:55 | `probe-cls` | dxil ×76, sha 53722d3d | class gate |
| L4a | 15:37:29 | E1 exact (RR *not* off) | `rcbm` | intended RR arm; became 3rd null |
| L5 | 16:08:20 | `tier=off kernel=off` | `ptq=off`, payload d2dfb3f5 | vanilla baseline |
| L3 | 16:26:45 | `ptclamp=off` | `rbm` | clamp hypothesis |
| L6 | 16:37:33 | `ptreg=off` | `cbm` | reg hypothesis |
| L7 | 16:45:53 | `tier=off kernel=off` | `ptq=off`, payload d2dfb3f5 | vanilla repeat |
| L8 | 16:53:40 | `ptbounce=off` | `rcm`, content 6fe05ecc | bounce hypothesis |

Params file was restored to the shipping default after L8. Nothing committed.

---

## 11. Peer review of this trace (2026-08-30 late evening, second Fable pass)

**Method.** Every load-bearing figure re-derived from the captures, not from
the ledger: §18.1's chain reproduces to the digit (S3 non-skin 2.689/2.726
vanilla, 2.431/2.424/2.441/2.458 mod, 2.796 bounce-off), §14.1's tone bins
likewise (+0.21 → +1.83% at the 106.4 bin), the S1 regime band matches.
`LAUNCHES.md` was regenerated for all 14 launches — it had been stale at 7,
so the serve record for L2–L8 existed only in the journal. The regenerated
record independently confirms two claims: the 15:11 L2 row reads **dxil ×76
/ 104 HITs** (§12's census, from the layer's own log), and the 16:53 L8 row
shows `payload=225acb871d94a4b8` beside `ptq=rcm` (§18.3's collision, now
visible in the record). Also found: `reproduce.sh` ended at §6 while
`CURRENT.md` claimed it regenerated every figure in `46`/`47` — §7 added,
claim now true.

### 11.1 Verdicts on §9's attack list

1–2. **Regime break / RR-state inference — agree, and do not excavate.**
No surviving conclusion depends on naming the ~13:30 cause, and the RR state
of past captures is unknowable. Prevented instead: `collect.sh` now copies
`UserSettings.json` into the rung dir at pickup and prints `DLSS_D` + mtime.
Both failure classes become recorded facts from here on.
3. n=4 pooling: disclosed, and the strict 2-vs-2 reading still separates
with no overlap. Accepted.
4. L8 above vanilla (+3.2%, n=1): real oddity, nothing rides on it. Park.
5. **Noise-vs-detail — an argument the trace missed, from its own data:**
same-config pair disagreement is itself a residual-noise measure, and the
mod pair replicates to **0.3%** (L1/L4a) where the vanilla pair spreads
**1.4%** (L5/L7) on S3 non-skin. Better-converged frames replicate better;
removing *authored* detail could not improve launch-to-launch agreement.
n=2 per side, but this is the frame-variance test §9 item 5 asked for,
already sitting in the data. §18.2 is strengthened.
6. The ~106/~116 threshold agreement: directional, and directional is
enough — no decision rides on the exact value.
7. Eyes (30 px): thin but internally consistent (lashes went hair-yellow).
Folds into the eyeball ladder; no dedicated launch.
8. S2 old-character pair: stands as caveated. The GI-writer search decides
`42` more cheaply than a reshoot would.

**One elision to carry wherever §14.1 is quoted:** the S1 **wall-L control
moved +0.825 (sd 24.8)** on L5→L1 — larger than the skin mean (+0.732) —
and only the two flat controls (ceiling −0.045, floor −0.000) were quoted.
Defensible: the second NPC stands in that rectangle. But it must be said,
and the finding is carried by the tone-bin structure plus the independent
L2 threshold, not by the mean. Noted in `reproduce.sh` §7c.

### 11.2 Process verdict — what the protocol turned out to be for

Fourteen launches. Ranked by cost per answer, what actually decided things:

1. **Serve verification and paint probes** — cheap and decisive every time.
   The journal caught the mis-set params file and the 76-module serve; the
   settings read caught RR-still-on before a launch was wasted; L2 settled
   *reach* in one launch and threw in the eye-class answer for free.
2. **The user's eye** — decided the roughness fork, decided `ptbounce`'s
   sign, caught the missing positive control, caught the eye tint.
3. **Radiometry** — produced one real product number all day (the ~106
   threshold, and L2 had already found it as ~116) and one methodology
   chain whose main output was retracting radiometry's own earlier claims.

`45` §3's ladder implicitly assumed numbers would arbitrate aesthetics.
They cannot: the day ended with the metric scoring an improvement as a 10%
loss and the eye overruling it — correctly. The protocol's *verification*
half (§0–§2) is permanent procedure. The *measurement* half is reserved for
disputes, under the `GOTCHAS` rules the day paid for: replicated baseline on
both sides, non-skin control, floor before conclusion. The E-queue collapses
to the four-line list in `CURRENT.md`; the two-launch RR floor (the "real
L4") is **dropped**, because no pending decision still rides on S1/S3
radiometry — RR survives as a one-look eyeball question (`43` M1) at the
winning rung.

### 11.3 Changes made with this review

`reproduce.sh` §7 (the missing L5–L8 block) · `LAUNCHES.md` regenerated to
14 launches · `collect.sh` settings snapshot · `CURRENT.md` queue collapsed
and a duplicated ptbounce bullet merged · `45` banner. Nothing committed.
