# Hair in the path tracer — implementation handoff (ideas 1/2/3)

Audience: the agent implementing hair improvements via the SPIR-V swap layer.
Read with `analysis/BRDF_HANDOFF.md` (injection mechanics, tiers) and
`dev/MS_GGX_NOTES.md` (spec-site ids). Everything below is authored against
`dev/disasm/spv_0170.spvasm`; spv_0171 has the same structure — re-locate all
ids structurally with the patcher, never hardcode them.

## 0. Established facts (do not re-derive)

- PT hair has **no dedicated shading**: the material `OpSwitch %6862`
  (line 5701; cases 2,3,4,5,6,7,8,13,14, default %12526; second copy
  `OpSwitch %5562` line 10709) contains only per-class *parameter-record
  loaders*. Every class merges into ONE eval: Lambert diffuse (three primary
  1/π triples at lines 8883/9807/13891 + three env triples at
  8914/9838/13922) and ONE isotropic GGX lobe. No tangent vector, no
  anisotropy, no second lobe exists anywhere in the raygen.
- Spec-site SSA map (first primary copy; from MS_GGX_NOTES §2):

  | id | meaning |
  |---|---|
  | `%5649` | perceptual roughness R = NMin(%5648, 1) (line 8547) |
  | `%5655` | α = R² (line 8553) — **shared by eval AND the GGX sampling branch** |
  | `%691/%693/%695` | F0 rgb = metallic + 0.04 (lines 3266–3268) |
  | `%9956/57/58` | H (normalized) |
  | `%9963` | NoV = NMin(NMax(dot(N,V),1e-5),1) |
  | `%9967` | NoH (clamped) |
  | `%9971` | VoH (=LoH, clamped) |
  | `%9948` | L-side cosine — **area-light modified, not plain NoL** (MS_GGX_NOTES blocker); fine for gating/shaping, do NOT use for absolute energy math |
  | `%9980` | D, `%9986` | Vis, `%9990` | Schlick pow5, `%9995–97` | F rgb |
  | `%7576/%7578/%7580` | spec out = F·D·Vis (the three values to modify) |
  | `%7583` | diffuse weight = NoL·shadow-ish (`trace_nol` in the patcher finds NoL) |

- Skin gate: `(gbuf.y >> 5) == 1` (`find_skin_gate` in `patch_skin_brdf.py`).
- Albedo ids at the triples: found by `classify_triples` (the 3 leaves shared
  by all 6 triples). Env-triple order gives channel mapping r,g,b.
- Patch BOTH `d622fb9e1dcb8cd0.rgs_reference_main` and
  `40c6faab52a13874.rgs_reference_main`; clear GLCache + steam shadercache
  after every regen (`regen_and_clear.sh`); knobs flow from `brdf_params.txt`.

## 1. Step zero for ALL three ideas: find hair's class value N

Unknown. Candidates: the gbuffer class field is bits[9:5] of gbuf.y, same
field skin uses (=1). Likely N ∈ {2..8, 13, 14} (the switch-case values are
the plausible id space, but the gbuffer class and the switch selector are not
proven to share numbering — treat N as independent).

Method (proven for skin): build a **smoke tint gated on class N**. Clone
`find_skin_gate` into `find_class_gate(mod, N)`:
- find the same structural pattern `OpIEqual %bool (ShiftRightLogical
  (CompositeExtract (ImageFetch v4uint) 1) %uint_5) %uint_1` — then instead of
  reusing that bool, take the ShiftRightLogical result id and emit a NEW
  `OpIEqual %bool %shifted %uint_N` right after the found IEqual line
  (dominance is inherited; `%uint_N` may need an `OpConstant %uint N` added
  next to the other constants).
- run the existing `build_smoke` with that gate, tint (2.0,0.2,0.2). NOTE:
  smoke tints the *diffuse* triples only — hair diffuse is present, so this
  works; if a candidate N shows nothing, also tint spec (`%7576/78/80` × tint)
  before ruling it out.
- Cycle N in-game (regen + cache clear per value, minutes each). Hair turns
  red at the right N. Record N in this file when found.

Everything below writes `gate` for that `OpIEqual` bool.

## 2. Idea 2 — hair roughness/F0 reshape (do first)

Goal: restore sheen; hair cards ship rough/matte params that the single GGX
turns to chalk.

### 2a. α reshape at the common source (MIS-correct)
Insert immediately after `%5655 = OpFMul %float %5649 %5649`:

```
alphaScaled = alpha * s_h            ; s_h knob, default 1.0
alphaH      = NClamp(alphaScaled, a_min, 1.0)   ; a_min knob, default 0.0
alphaSel    = OpSelect %float gate alphaH alpha
```

then **rewrite every subsequent use of `%5655` to `%alphaSel`** (12 uses:
lines 8584–8855 incl. the sampling branch `%7613 = Sqrt %5655`). This is a
replace-ALL, not `replace_single_use` — write a `replace_all_uses(mod, old,
new, after_line)` that skips the def line and the OpSelect itself. Because
sampling and eval read the same value, MIS stays consistent (this is a
legitimate BRDF change, not an eval-only hack). **Verified:** `%5649` has exactly two occurrences (its def at 8547 and the
square at 8553), so it has no independent consumers — reshaping at `%5655`
captures the whole spec path, and reshaping at `%5649` instead would be
equivalent (α = R²·s vs R·√s). Prefer `%5655`.

Identity: s_h=1, a_min=0 ⇒ alphaSel == alpha bit-exact? NClamp(α·1, 0, 1) is
NOT guaranteed bit-identical to α (it is: α ∈ [0,1] already, FMul by 1.0 is
exact, clamp is a no-op — but keep `--vanilla` A/B screenshot as the test).
Suggested start: s_h = 0.55 (sharper highlight), a_min = 0.04.

### 2b. Sheen/F boost at the F outputs (eval-only, per-channel)
Do NOT touch F0 at lines 3266–68 (defined before the gate exists — dominance
risk, and it feeds other consumers). Instead, right after `%9995–97`:

```
fresnelW = (1 - VoH)^p_sheen         ; via Log2/Exp2 like tier1, base NMax(1-VoH, 1e-5)
                                     ; p_sheen knob, default 5 → reuse %9990 when p=5? NO —
                                     ; %9990 is the SG fit of (1-VoH)^5; acceptable to reuse
                                     ; it directly as fresnelW when p_sheen fixed at 5.
sheenAdd = k_sheen * fresnelW        ; k_sheen knob, default 0.0 = identity
F'r = %9995 + gate?sheenAdd:0        ; i.e. add = OpSelect gate sheenAdd zero; FAdd
(same g,b)
```

then rewrite the single FMul uses of `%9995/96/97` (they feed `%7576/78/80`
via `%9998`… actually `%7576 = FMul %9995 %9998` — use `replace_single_use`).
Clamp F' ≤ 1.0 with NMin. Start k_sheen = 0.15, p fixed 5 (reuse `%9990`).

## 3. Idea 3 — hair diffuse wrap (do second)

Fibers scatter light through the card; Lambert NoL gives the dark-helmet look.
Eval-only multiplier at the **3 primary triples AND 3 env triples**, exactly
the c1 pattern (`build_tier1` skeleton):

Math — energy-normalized wrap, expressed as a ratio so it composes with the
existing NoL already folded into `%7583`:

```
NoL   = trace_nol(...)                       ; the real NoL, per site
wrapd = sat((NoL + w) / (1 + w))             ; w knob ∈ [0,1], default 0
norm  = 1 / (1 + w)                          ; energy conservation
ratio = wrapd * norm / NMax(NoL, 1e-3)
ratio = NMin(ratio, r_max)                   ; r_max knob, default 4.0 — firefly guard
mult  = OpSelect gate ratio 1.0
diffuse_out *= mult                          ; multiply the 3 triple outputs, tier1-style
```

Identity: w=0 ⇒ wrapd=NoL, norm=1, ratio=NoL/max(NoL,1e-3)=1 for NoL≥1e-3
(below that ratio ≤1 and diffuse is ~0 anyway — visually identity; document
that bit-exactness only holds for NoL ≥ 1e-3, acceptable). Start w = 0.4.
For env triples NoL tracing may differ — `trace_nol` was written for primary
triples (3 FMul hops); verify hop count on env triples, adjust or apply wrap
to primaries only first (most of the look).

sat(x) = NClamp(x, 0, 1). All pow via Log2/Exp2 with NMax base clamp (tier1
idiom). All new constants via `mod.const()`.

## 4. Idea 1 — dual-lobe pseudo-Marschner spec (after 2+3 ship)

True Marschner needs the strand tangent T (lobes shift along the strand); no
T exists in the raygen inputs. Two options:

### 4a. Isotropic dual lobe (implementable NOW, no tangent)
Replace hair spec with R + TRT analog, both isotropic GGX sharing the site's
D machinery:

```
D(a)   = a² / (π·(NoH²(a²−1)+1)²)            ; recompute with each lobe's a, reuse %9967 NoH
Vis    = %9986                                ; reuse the site's shared Vis (approximation)
F_R    = Schlick white: f0r + (1−f0r)(1−VoH)^5     ; f0r knob ~0.05; reuse %9990 pow5
F_TRT  = tint · (albedo)                     ; TRT is transmission-colored: use the
                                             ; albedo ids from classify_triples, per channel
a_R    = NClamp(α·sR, 0.001, 1)              ; sR ~0.35 (sharp)
a_TRT  = NClamp(α·sTRT, 0.001, 1)            ; sTRT ~1.6 (wide), clamp ≤1
spec_h(ch) = wR·F_R·D(a_R)·Vis + wTRT·albedo_ch·D(a_TRT)·Vis
out(ch) = OpSelect gate ? blend : vanilla
blend   = lerp(%757x, spec_h, m)             ; m knob, default 0 = identity
```

Splice after `%7576/78/80` are defined, rewrite their single uses
(`%7606/08/10 = FMul %760x %757x`). Eval-only: do NOT touch the sampling
branch — sampling still importance-samples the vanilla single lobe; that is
fine for NEE/MIS eval sites (same argument as Tier 1: eval-side modulation).
Energy caveat: absolute normalization of this site is unresolved
(MS_GGX_NOTES blocker), so treat wR/wTRT as artistic knobs (start wR=1.0,
wTRT=0.3, m=1.0 when enabled) and A/B against vanilla brightness.

### 4b. Shifted lobes (needs tangent — future)
Only if 4a insufficient: derive pseudo-T. Hair cards are quads; T ≈ the
G-buffer normal crossed with view won't give strand direction. Real route:
find whether the hit-attribute/vertex data reaches the raygen (the parameter
records loaded in the OpSwitch cases carry per-material data, not geometry).
Likely NOT available ⇒ 4b is probably infeasible in the raygen; note and stop.
Then Marschner shift math for reference: H' built by rotating H around T by
shift β_R≈−7°, β_TRT≈+10°: cosθ' = NoH·cosβ − sqrt(1−NoH²)·sinβ per lobe.

## 5. Verification (all ideas)

1. `--vanilla` regen ⇒ screenshot A/B must be pixel-identical (skin Tier-1
   c1 still active — keep its knobs at current values, not defaults).
2. `spirv-val` clean on both modules (patcher enforces).
3. Offline: `ngfx-replay` + probe layer (`analysis/probe/`,
   `NGFXPROBE_STRIP_ALLOC=3`) still replays without new crashes.
4. In-game A/B with `compare_brdf_ab.py` masked to hair (reuse the skin-mask
   flow; hair gate N gives the mask condition if you dump gbuf.y).
5. Firefly check: bright backlit hair scene; if sparkling, lower r_max / wTRT.

## 6. Knob summary (wire through brdf_params.txt like tier1)

| knob | default(=identity) | suggested |
|---|---|---|
| s_h (α scale) | 1.0 | 0.55 |
| a_min | 0.0 | 0.04 |
| k_sheen | 0.0 | 0.15 |
| w (wrap) | 0.0 | 0.4 |
| r_max | 4.0 | 4.0 |
| m (dual-lobe mix) | 0.0 | 1.0 |
| sR / sTRT | — | 0.35 / 1.6 |
| wR / wTRT | — | 1.0 / 0.3 |
| f0r | — | 0.05 |

Patcher plumbing: add `--tier hair2` (α+sheen), `hair3` (+wrap), `hair1`
(+dual lobe) to `patch_skin_brdf.py`, sharing `find_class_gate`. Tiers must
compose with the existing skin tier-1 splice in one output module (run tier1
edits first, hair edits second; both only append ids and rewrite distinct
uses — verify no site overlap: skin triples are the SAME triples, gates
differ, so wrap's multiply and c1's multiply chain on the same values — order
independent, both OpSelect-gated on disjoint classes; fine).

---

# IMPLEMENTATION STATUS (branch `hair-brdf`)

Ideas 2 and 3 are implemented in `dev/patch_skin_brdf.py`. Idea 1 (dual lobe)
is not. **Nothing is shippable until hair's class value N is identified** —
every hair tier requires `--hair-class N` and refuses to run without it.

## Step zero: find N (must be done in-game)

```
python3 dev/patch_skin_brdf.py dev/disasm/spv_0170.spvasm \
  dev/disasm/spv_0171.spvasm --tier smoke --hair-class N --outdir ../swaps
# then regen_and_clear.sh, launch, look at hair
```
`--tier smoke --hair-class N` gates the red tint on class N instead of skin.
Cycle N over 2..8, 13, 14 (and anything else plausible — the gbuffer class
field and the OpSwitch case numbering are not proven to share an id space).
Hair turns red at the right N. Record it here and in `HAIR_CLASS`.

Caveat: smoke tints the diffuse triples only. If a candidate shows nothing but
you suspect it, check with `--tier hair2 --hair-class N --set k_sheen=3.0`,
which blows out the specular instead.

## Tiers

| tier | does |
|---|---|
| `hair2` | roughness reshape (2a) + gated sheen (2b) |
| `hair3` | diffuse wrap (3) |
| `hair23` | both |
| `--with-tier1` | additionally applies the shipped skin c1, combined into one multiply per triple |

Ship command once N is known:
```
python3 dev/patch_skin_brdf.py dev/disasm/spv_0170.spvasm \
  dev/disasm/spv_0171.spvasm --tier hair23 --hair-class N --with-tier1 \
  --outdir ../swaps
```
`--with-tier1` matters: without it the hair swap **replaces** the skin patch
and you lose the shipped skin look.

## What was built

- `find_class_shift` — returns the `gbuf.y>>5` value plus the line of the skin
  IEqual; the hair gate is a new `OpIEqual` inserted directly after it, so it
  inherits that block's dominance over every eval site.
- `Module.uconst` — find-or-create `OpConstant %uint N`.
- `replace_all_uses` — used for the roughness reshape so the sampling branch
  and the eval read the same reshaped alpha (MIS stays consistent).
- `find_ggx_sites` — anchors on the pi in the GGX D denominator, then walks to
  Vis*D, the outputs, and the Schlick pow5 (found via its spherical-gaussian
  constants -6.98316002 / 5.55472994).
- `emit_c1_factor` — extracted from `build_tier1` so hair and skin factors can
  be multiplied into one per-triple multiply instead of fighting over the same
  single FMul use. **Verified: tier1 output is byte-identical after this
  refactor** (sha256 921f95fc… / 84b17a86…).
- `build_diffuse` — combines whichever factors are enabled.

## Corrections to the plan above, found while implementing

1. **Spec sites are not always 3-channel.** spv_0170 expands Fresnel per
   channel; spv_0171 has scalar sites (`pow5 * Vis*D`, one output). Requiring
   a 3-FMul trio found 0 sites in spv_0171. The finder now takes however many
   FMuls consume Vis*D.
2. **Sheen is applied to the outputs, not to F.** Since out = F*vd, adding
   `sheen*vd` to the output equals adding `sheen` to F, and clamping the
   result to `vd` is exactly the F<=1 clamp (vd is what F=1 yields). This works
   for both site shapes, where the F-id route did not.
3. **The sheen splice is OpSelect-gated**, not left to `k_sheen=0`. The clamp
   to vd is only a no-op where out <= vd; that holds for F*vd with F<=1 but is
   not guaranteed for every generically-matched site, so gating makes every
   non-hair pixel bit-exact by construction.
4. **Alpha is per-copy, not global.** spv_0170 has three alpha sources
   (%5655, %5721, %5344), each feeding two spec sites; spv_0171 likewise
   (%6403, %6469, %5937). The reshape runs once per distinct source.
5. Section 2a's uncertainty about `%5649` is resolved: it occurs exactly twice
   (def + square), so reshaping at the alpha (`%5655`-equivalent) covers the
   whole spec path.
6. Some GGX D sites have no Schlick pow5 nearby (3 in spv_0170, 2 in
   spv_0171) and are skipped for sheen; they still get the roughness reshape.
   Reported as `skipped_no_pow5`.

## Verification done

- `spirv-val` clean on both modules for `hair2`, `hair3`, `hair23`,
  `hair23 --with-tier1`, `--vanilla`, and `smoke --hair-class` for N in
  {2,3,4,13}.
- tier1 byte-identical to its pre-refactor baseline.

## Verification still owed (needs the game)

- Identity: `--vanilla` should look pixel-identical to unpatched.
- The real A/B once N is known; watch for fireflies on backlit hair and lower
  `r_max` / `w_wrap` if they appear.
- Env triples are NOT wrapped (only the three primary/NEE triples), per the
  fallback in section 3. Revisit if hair still reads flat in bounce light.
