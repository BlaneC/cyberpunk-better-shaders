# 53 — Terminator colour bleed: built, validated, parked, NEVER on screen

Written 2026-08-30 night (delegated build; plan `51` §3). The kept half of
`43`'s A7 verdict: the shadow-terminator warms because red diffuses further
through skin than green and blue less — the pre-integrated-scattering
colour cue, WITHOUT the blur half (that would double-count the SSS kernel).
**Nothing here has been on screen. Built, validated and parked is the
ceiling of this document; the launch and the A/B are the main session's.**

## 0. Verdict first

| claim | confidence |
|---|---|
| The three bleed rungs + `gi-50-bleed` are valid SPIR-V, byte-distinct from their parents, coverage-equal to the ladder | **high** — build assertions below, `spirv-val` clean everywhere |
| The emitted math is exactly `m_R = 1+0.336k·w`, `m_B = 1−0.101k·w`, `m_G = 1`, `w = sat(1−NoL/0.35)²`, skin-gated | **high** — re-read from the emitted `.spvasm` AND machine-evaluated at 7 NoL points against the closed form (§4); gate-false path evaluates to exact identity |
| `bleed_k=0` emits nothing | **high** — a k=0 build is byte-identical to the PREVIOUSLY PARKED `off` (predates this session's patcher edit) |
| The R/B channel identification is right | **high** — census over the shipped 77: every eligible site roots at ONE `v4` fetch with components {0,1,2} distinct; `find_diffuse_colour`'s triple order measured = R,G,B at 153/153 dump-wide (§2) |
| Where the diffuse term is zero, it stays zero | **by construction** — multiplicative only; no additive path exists in the emitted code |
| The bleed renders, and looks like skin | **unknown — this is what the launch decides** |

## 1. What was built

Three ladder rungs + one assembled rung, all parked in
`~/.local/lib/callisto/skin.set/`, selected by `skinspec=` once registered
(§7). One knob: `bleed_k` (identity 0.0).

| rung | parent | modules | c1 | bleed sites | skipped | other axes |
|---|---|---|---|---|---|---|
| `bleed` | off | 77 | 173 | **150** | 23 | none |
| `bleed-x` (k=3) | bleed | 77 | 173 | 150 | 23 | none |
| `real-gloss-bleed` | real-gloss | 77 | 173 | 150 | 23 | 408 alphas, 173 coupling, 150 micro — real-gloss unchanged |
| `gi-50-bleed` | gi-50 | 93 | — | — | — | assembly: gi-50 raygens byte-verbatim + real-gloss-bleed compute |

Every one of the 77 modules carries at least one bled site; 17 modules are
partial, and the 23-site skip list is character-for-character the micro_k
skip list (`99bb7c26` 6/12, the rest 1–3 each) — same structural cause, no
reachable albedo triple.

Files touched: `dev/patch_skin_brdf.py` (knob `bleed_k`, identity 0.0 in
KNOBS + VANILLA), `dev/patch_compute_skin.py` (`_albedo_channel_root`,
`find_bleed_targets`, the emission in `build_skin_c1`), `dev/patch_compute_skin.sh`
(three LEVELS rungs + coverage accounting), `dev/build_gi_bleed.sh` (new).
`init.lua`, `sync_settings.sh`, `Makefile`: **not touched** — registration
diff in §7. Nothing named `*ser*` touched; ser/ptq bases untouched.

## 2. The mechanism, and the two detectors

The c1 pass multiplies the site's shared Disney-diffuse scalar — one factor,
all three channels. A colour bleed needs PER-CHANNEL reach, so this pass
rewrites the site's three fan-out FMuls (the ones `find_diffuse_colour`
already walks for micro-shadowing), multiplying the R and B results only:

    scalar ──(c1·coupling·micro, one replace, unchanged)──> out
    out ──ch-R FMul──> ×m_R      <- one replace_all_uses, per-site-unique id
    out ──ch-G FMul──> (untouched, m_G ≡ 1, zero instructions)
    out ──ch-B FMul──> ×m_B      <- one replace_all_uses, per-site-unique id

Channel identity is NOT assumed from operand order: `find_bleed_targets`
walks each consumer's diffuse colour (`albedo·(1−metal)`) back to the albedo
fetch and reads the component index off `OpCompositeExtract`. The walk
(`_albedo_channel_root`) is a bounded multi-path search over the decode
idioms found on the anchored set: the sRGB squaring decode, literal-scaled
FMul/FAdd, the material-guard `OpPhi`, the white-override `OpSelect`, and the
uint `ConvertUToF` decode. It FAILS (site skips, reported) unless every path
lands on one component of one `v4` image fetch and the site's three channels
come out `{0,1,2}` distinct.

Census, before any emission was written (the detector ran read-only over the
dump — GOTCHAS 12 ordering is also kept inside the pass: targets are
precomputed before the first `replace_all_uses`):

| population | sites | eligible | no albedo triple | walk-fail | shared-consumer collisions |
|---|---|---|---|---|---|
| shipped 77 | 173 | **150** | 23 (the identical micro_k skip set) | 0 | 0 |
| all 84 anchored | 181 | 153 | 25 | 3 — all in `e47009fbdc79c311` / `f7a29100e09ef0d7`, which are among the 7 modules that never build (no class anchor); their albedo is a packed-uint bitfield decode | 0 |

Side-finding, free: `find_diffuse_colour`'s triple order — which `44`'s
micro-shadowing pass bets its Rec.709 luminance weights on — measured
R,G,B at every one of the 153 eligible sites dump-wide. Micro's assumption
holds everywhere it applies.

## 3. The shape, and what it deliberately is not

    w   = sat(1 − NoL/0.35)²           band: NoL ∈ [0, 0.35)
    m_R = 1 + k·0.336·w
    m_G = 1
    m_B = 1 − k·0.101·w

- **Multiplicative only** (`38` 0d / `39` §3.3): the factors multiply the
  per-channel diffuse term the pixel already has. Where that term is zero —
  unlit, shadowed, backfacing — the product is zero. No added light, no
  tile grid, by construction rather than by tuning.
- **Amplitude ratio from the same physics as the A6 kernel**: per-channel
  diffuse mean free paths (Jensen 2001 skin1 via `σtr=√(3σa·σt′)`) give
  `d_R:d_G:d_B = 2.68:1:0.50`; the bleed amplitudes are the differences
  against green, `(d_R−d_G):(d_G−d_B) = 1.68:0.504 = 0.336:0.101` at the
  chosen overall scale. One knob (`bleed_k`) scales both together; the
  ratio is baked. `53` and the A6 rung deliberately share their chromatic
  story.
- **NoL is real at the site** — the c1 site census hands it over
  (`find_c1_sites`), the same id the micro pass uses. Nothing is proxied.
- **The band width (0.35) is a fixed stylization constant, and the doc says
  so out loud.** Physically the terminator band scales with curvature×d.
  Curvature from 720p depth taps was scoped per the plan and NOT built:
  raw reverse-Z second differences cannot be converted to curvature without
  the projection constants, which no detector currently names across 77
  permutations, and an *uncalibrated* curvature threshold is precisely the
  `39` §3.2 proxy-knob trap — a knob approximating a quantity the splice
  cannot see. Written down instead of built, per the plan's own stop rule.
  Consequence to expect on screen: the bleed width is the same on a cheek
  as on a nose wing; physically the cheek's should be narrower. If that
  reads wrong, the fix is a calibrated curvature input (projection
  constants via U1b, or U3), not a proxy.
- At `k=1`, peak effect at the terminator edge: R×1.34, B×0.90 (R/B ratio
  ≈1.49 where the term is already nearly dark), decayed to nothing by
  NoL=0.35. `bleed-x` (k=3) is the DIAGNOSTIC rung — R×2 at the edge,
  ladder convention `33` — an "is it working" rung, not a look candidate.

## 4. The emitted code, re-read and re-evaluated

From `4d46848998312027` in the `bleed` rung (site 1 of 2; ids are the
build's own):

    %1603 = OpFMul %float %706 %1571          ; NoL · (1/0.35)
    %1604 = OpFSub %float %float_1 %1603
    %1605 = OpExtInst NClamp %1604 %float_n0 %float_1
    %1606 = OpFMul %float %1605 %1605         ; w
    %1607 = OpFMul %float %1606 %1572         ; w·0.336k
    %1608 = OpFMul %float %1606 %1573         ; w·0.101k
    %1609 = OpFAdd %float %float_1 %1607      ; m_R
    %1610 = OpFSub %float %float_1 %1608      ; m_B
    %1611 = OpSelect %float %1567 %1609 %float_1   ; skin-gated
    %1612 = OpSelect %float %1567 %1610 %float_1
    %1613 = OpFMul %float %812 %1611          ; R fan-out × m_R
    %1614 = OpFMul %float %818 %1612          ; B fan-out × m_B
    %828  = OpPhi ... %1613 ...               ; downstream reads the bled id
    %830  = OpPhi ... %1614 ...

(`%float_n0` is the module's own −0.0, deduped by value; `NClamp(x,−0,1)`
is numerically saturate.) The chain was then machine-evaluated from the
emitted text at NoL ∈ {0, .05, .1, .2, .3, .35, .9}: exact match with the
closed form at all 7 points, and exact identity (1.0, 1.0) with the skin
gate false. The G fan-out `%815` is untouched in the emitted module.

Instruction cost: 10 + 2 per bled site, ~14% on top of the c1 block; no new
fetches, no loops, no new resources.

## 5. Rungs, composition, and the one-variable guarantee

| rung | parent | knobs | what it is |
|---|---|---|---|
| `bleed` | off | bleed_k=1 | single-axis attribution rung |
| `bleed-x` | bleed | bleed_k=3 | diagnostic ("is it working") |
| `real-gloss-bleed` | real-gloss | real-gloss knobs + bleed_k=1 | the standing compute build + one variable |
| `gi-50-bleed` | gi-50 | — (assembly) | the STANDING RUNG + one variable |

**Composition decision.** `gi-50` = 77 compute (real-gloss) + 16 raygen
files + MANIFEST (`dev/build_gi_rung.sh`). The bleed lives only in the
compute half, so `dev/build_gi_bleed.sh` does an ASSEMBLY, not a patcher
run: gi-50's sixteen raygen files are copied **byte-verbatim** (asserted by
`cmp` per file — a failed compare aborts the build) and the 77 compute
swap to `real-gloss-bleed`. The A/B `gi-50` vs `gi-50-bleed` is one
variable **by construction**, and the raygen provenance fields
(`src_ser`/`ser_sha`/`ptq_sha`) carry over verbatim, so sync's `gi_refuse`
contract holds unchanged: **needs `ser=class` + `shadowset=full-shadow`**,
refused loudly otherwise. Rebuilding the raygen half was therefore NOT
required and was not done; ser/ptq bases untouched.

Ordering note for rebuilds: `--sets` wipes every non-`probe-*` dir in
`skin.set/` including the gi rungs. The restore chain is
`./dev/patch_compute_skin.sh --sets` → `./dev/build_gi_rung.sh --install` →
`./dev/build_gi_bleed.sh --install`, in that order.

## 6. Validation record

All from this build, 2026-08-30 night; every check ran, none inferred.

- **`spirv-val` clean on every module of every rung** — the patcher dies on
  a validation failure (`_emit`), and `build_gi_bleed.sh` re-validates all
  93 files of the assembly. Zero failures.
- **`bleed_k=0` emits nothing, and the patcher edit is inert**: all 14
  pre-existing rungs (off…real-gloss) rebuilt **byte-identical to a
  pre-session snapshot** of the parked sets, 77/77 modules each. `gi-50`
  and `gi-100`, rebuilt via `./dev/build_gi_rung.sh --install` after
  `--sets` wiped them, came back **0/93 differing** from the snapshot.
- **Ladder byte-difference checks** (the .sh's own): every rung differs
  from `off` AND from its parent on 77/77 modules — `bleed` vs off,
  `bleed-x` vs bleed, `real-gloss-bleed` vs real-gloss all 77/77.
- **Coverage from reports, not byte diffs** (the `42` rule): 150 bled /
  23 skipped / 0 dup-guarded, identical across all three rungs; zero
  `skipped_dom` anywhere; every module ≥1 bled site. (A byte diff could
  not prove this — the knob constants are emitted even where a site
  skips, the known property the .sh documents.)
- **`gi-50-bleed` one-variable assertions** (`build_gi_bleed.sh`, all
  fatal on failure): 93 files = 77+12+4; all 16 raygen files `cmp`-equal
  to gi-50's; compute file lists identical; 77/77 compute differ from
  gi-50's; MANIFEST line 1 carries gi-50's provenance verbatim
  (`ser_sha=310513f3… ptq_sha=55ed4e5c…` — the values `50` §1 quotes).
- **Emitted-math machine evaluation** (§4): exact match with the closed
  form at 7 NoL points, exact identity with the skin gate false.
- `make check` passes; `bash -n` clean on both touched scripts.

## 7. Registration diff (NOT applied — the main session applies it)

`init.lua`, `SKIN_LEVELS`, after the `real-gloss` entry / before `probe-gi`:

    -- 53: terminator colour bleed (43 A7 kept half): the shadow edge warms --
    -- red diffuses further than green, blue less. Multiplicative, skin-gated.
    { id = "bleed",            label = "Terminator bleed only -- warm shadow edge" },
    { id = "bleed-x",          label = "Terminator bleed x3 -- diagnostic" },
    { id = "real-gloss-bleed", label = "REAL-GLOSS + terminator bleed" },
    -- 53: gi-50's raygens byte-verbatim + real-gloss-bleed compute (needs ser=class)
    { id = "gi-50-bleed",      label = "GI-50 + terminator bleed" },

`sync_settings.sh` needs **nothing**: it serves any parked `skin.set/<name>`
and the raygen guard reads the MANIFEST fields, which carry gi-50's values.
`Makefile` needs nothing.

## 8. A/B protocol suggestion (per `45`)

**Required game settings, stated up front (house rule — before the launch,
never inferred after):** Path Tracing on, `ser=class`,
`shadowset=full-shadow`, `shadowcull=on`, `tier=1`, `skin=on`,
`kernel=detail` (or the A6 winner if that A/B has run — state which),
`ptbounce/ptrefl/ptclamp/ptmsggx` at standing config, `ptreg=off`, RR state
pinned and recorded (the `collect.sh` snapshot verifies — `47`'s lesson,
both directions).

1. **First look: `skinspec=gi-50-bleed` vs `skinspec=gi-50`.** One variable
   (assembly-guaranteed). Scene: a face near a hard sun terminator or a
   strong practical — the effect lives where NoL crosses zero on lit skin;
   S1-style sun scenes are ideal. Stationary light; same-session control
   per `50` §6's cross-session lesson.
2. Attribution if step 1 shows anything: `bleed` vs `off` (bleed alone, no
   gloss/realism axes).
3. If step 1 shows nothing: one look at `bleed-x` (k=3, diagnostic). Still
   nothing at k=3 on a terminator close-up ⇒ the splice does not reach the
   screen the way the census says, and that is a finding — write it down
   before touching knobs.
4. What "working" looks like: the falloff edge on lit skin warms (R up, B
   down) over roughly the last third of the falloff; shadow cores, ambient
   and bounce light are untouched (the term rides the DIRECT diffuse arm —
   `46` §12: these modules write the direct-light term; the GI raygens'
   diffuse is NOT bled by this build). What "wrong" looks like: a warm
   band of constant width on every skin edge regardless of feature size —
   that is the fixed-β approximation showing (§3), and the verdict should
   say whether it is objectionable, not just visible.

## 9. Surprises and side-findings

- `find_diffuse_colour`'s R,G,B ordering assumption (micro's Rec.709
  weights) verified at 153/153 sites — previously unproven, now measured.
- Two of the seven never-built anchored modules (`e47009…`, `f7a2…`) decode
  albedo from a packed uint (`&255`-style), not a `v4float` fetch — noted
  for whoever next extends coverage; irrelevant to the shipped 77.
- Zero shared-consumer collisions dump-wide, so the one-replace-per-id rule
  (`31` §4.1) holds with room to spare; the dup guard in the pass should
  never fire and is there for the day it does.

> **2026-08-30 night, user verdict on screen:** the user ran the A/B
> themselves the same night and both new rungs win by eye (*"A/B tested
> myself and these are the shit"*). Settings unrecorded (user-driven
> session); no radiometric claims ride on this. Look-confirmed.
> Later, unprompted: *"The bleed shader and better skin shader was
> incredible."*
