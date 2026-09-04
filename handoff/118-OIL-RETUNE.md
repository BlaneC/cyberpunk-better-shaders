# 118 — 72's coat was tuned against a BRDF that never paid for it

## 0. What this is

Four rungs and a control. No new maths, no new instructions, no new gate:
`117`'s `cons` changed the economics of a feature that shipped a month ago,
and this is the correction.

`72` put a Schlick reshape on the skin-gated Fresnel — an oil coat. `74` read
it on screen as twice too strong and halved it (`oilh`, `n_s = 0.55`). That
tuning was done against a BRDF in which the coat's reflected energy was a
**pure add**: the diffuse lobe kept every photon it had, and the coat's share
was piled on top. `117`'s `cons` now multiplies the diffuse by `(1 − F)` per
channel. The same `F` is therefore doing two jobs it was not tuned to do at
once — it is louder in the highlight *and* it is now the thing that darkens
the body — so the coat as shipped is weaker than the number `74` chose.

This build moves it back up, one lever per rung.

## 1. Where it lives

The 77 GLCompute resolvers, at the same Fresnel groups `72` spliced. Compute
side, so under PT this is **direct sun only** (`112` §12) — the same frame
`115` and `117` were read on.

## 2. The maths, and the third constant that was never real

`72` emits, per Fresnel group:

```
sv  = NClamp(VoH, 0, 1)
b   = 1 − sv
bm  = NMax(b, 1e-4)
l   = Log2(bm)
xe  = l · P                 P = 5r                    shipped 4.5
pr  = Exp2(xe)                    = (1 − VoH)^P
s2r = NClamp(C, 0, 1)       C = 2 − r                 shipped 1.1
amp = s2r · G               G = spec_gain             shipped 1.0
    ---- per channel c ----
t1  = (1 − f0_c) · pr
t2  = t1 · amp
fp  = f0_c + t2
fc  = NMin(fp, 1)
F'  = select(skin, fc, F_c)
```

with `r = 2(1 − n_s)`, so `n_s = 0.55 → P = 4.5` and `C = 1.1`.

**`C` has never mattered.** It only reaches the shader through
`NClamp(C, 0, 1)`, and every rung on the oil ladder has `n_s ≥ 0.5`, hence
`r ≤ 1`, hence `C = 2 − r ≥ 1`, hence `sat(C) = 1` exactly. The
`saturate(2 − r)` amplitude term in `patch_compute_skin.build_skin_spec` has
been pinned at 1 for the entire life of the feature. `patch_compute_skin.sh`
half-notices this in a comment ("its saturate(2-r) amplitude term is clamped
to 1 across this whole direction") but the docs have carried it as if it were
a live lever. It is not. **The shipped coat is plain Schlick with the exponent
slackened 5 → 4.5, amplitude 1.0**, and `G` alone is the amplitude.

That claim is not left as an argument. `oil-inert` moves `C` from 1.1 to 1.9:
the bytes differ in 77 of 77 modules and the screen must not move at all. If
it does, this section is wrong.

### The rungs

| rung | P | G | what it is |
|---|---|---|---|
| `oil-ctl` | 4.5 | 1.00 | the shipped coat — 93/93 byte-identical to the default |
| `oilhi` | **4.0** | 1.00 | the ladder's own next step (`n_s` 0.55 → 0.60) |
| `oilhi-g` | 4.5 | **1.25** | the other lever alone |
| `oilhi2` | **4.0** | **1.25** | both — the louder candidate, not a diagnostic |
| `oil-inert` | 4.5 | 1.00 | `C` 1.1 → 1.9. Bytes move, screen must not |

`F` at `f0 = 0.04` (`dev/oil_model.py --table`):

```
      VoH    deg    oil-ctl    oilhi   oilhi-g   oilhi2
   1.0000    0.0     0.0400   0.0400    0.0400   0.0400
   0.7500   41.4     0.0419   0.0437    0.0423   0.0447
   0.5000   60.0     0.0824   0.1000    0.0930   0.1150
   0.2588   75.0     0.2894   0.3297    0.3518   0.4022
   0.1000   84.3     0.6375   0.6699    0.7869   0.8273
```

Two honest notes:

1. **Facing skin cannot move on any rung.** `(1 − VoH)^P = 0` at `VoH = 1`
   for every `P > 0`, so `F = f0` exactly on all five. This is a
   grazing-band read — cheekbone, nose flank, brow ridge, jaw, ear rim — and
   a forehead-on comparison will show nothing on any of them.
2. **The two levers are not the same shape.** The exponent widens the rim
   (biggest relative lift in the 40–60° band); the gain lifts everything off
   normal proportionally and hits the `NMin(·, 1)` ceiling sooner at grazing.
   They were sized to be within 1.5× of each other at 60° so the A/B is a
   question about *shape*, not about strength.

## 3. What is found, and how

`dev/patch_oil.py`. Anchored on each `Exp2` in the module and walked
**outward in both directions** — nothing by name, nothing by id:

- up: `Exp2(FMul(Log2(NMax(FSub(1, NClamp(voh,0,1)), eps)), P))`
- down: the power must feed **exactly three** products; each must have exactly
  one `OpFMul` consumer; all three must multiply the **same** `amp`; `amp`
  must be `FMul(NClamp(C,0,1), G)`; each channel must end
  `FAdd(f0, ·) → NMin(·, 1) → OpSelect(gate, ·, F)`; all three `OpSelect`s
  must agree on **one** gate.

Anything else is declined and reported, never guessed at.

Census on the shipped default: **357 groups in 77 of 77 modules, 1071
channels = 3 × 357 exactly** — and the patcher *asserts* that all 357 carry
`(4.5, 1.0, 1.1)` before it writes anything, so a base whose coat is not the
shipped one is refused rather than silently retuned into something else.

The patch itself is one operand token on one line, twice. It adds no
instruction, deletes none, and changes no opcode.

## 4. The gates (`dev/build_oil.sh`, all passed)

0. base provenance: 77 compute + 16 raygen, `src_ser=` present
1. `dev/oil_model.py` — 21 float32 self-checks
2. disassemble 77
3. round-trip neutrality, 77/77 byte-identical at each module's own version
4. patch 5 rungs
5. coverage from the reports: census **identical in every rung**, and the
   write counts are exactly what each rung declares —
   `ctl (0,0,0)`, `hi (357,0,0)`, `hig (0,357,0)`, `hi2 (357,357,0)`,
   `inert (0,0,357)`
6. assemble: 93 modules, **16/16 raygens `cmp`-identical** (compute-only
   asserted), `spirv-val --target-env vulkan1.4`
6b. `oil-ctl` == `skin.set/micro` in **93/93**; every other rung differs in
    exactly 77 of 77 compute modules; all 10 rung pairs differ
7. the verifier on shipped bytes, plus 8 rejections
8. install

## 5. The verifier (`dev/verify_oil.py`)

Re-derives every claim from the shipped `.spv` of the base and the rung, and
trusts nothing the patcher said:

1. the group census is identical to the base's **module for module**
2. every group carries the **declared** `(P, G, C)`, and all groups in a
   module agree — one coat per build, no stragglers
3. the base's own groups carry `(4.5, 1.0, 1.1)`, so the deltas mean what the
   rung says they mean
4. **the function-body opcode multiset is identical to the base's, module for
   module.** This is the no-op proof, and it is id-independent (`spirv-as`
   renumbers, so a text diff would prove nothing)
5. at most 2 new float constants per module
6. the rung differs from the base in exactly the declared number of modules

Rejections gated in the build: the default read as `oilhi`; `oilhi` read as
the shipped coat, as `oilhi-g`; `oilhi-g` read as `oilhi`; `oilhi2` read as
either half; the inert decoy read as the default; the control read as
differing; `oilhi` read as unchanged.

## 6. What is NOT in this build

- **The roughness ceiling `alpha_max = 0.2025`.** It is the *dominant* oil
  lever (`patch_compute_skin.sh`'s own ladder table says so), it lives in a
  different pass, and moving it here would make every rung two variables.
  It also now interacts with `117`'s `rough`, which scales `alpha` up by
  `(1 + 0.5·cav)` **after** the cap — so a pore can already sit above the
  ceiling, and what that ceiling means is no longer quite what `72` meant.
  That is a real loose end and it belongs to whoever moves `alpha_max` next.
- **Any raygen change.** Compute-only, asserted by `cmp` in gate 6.
- **Cost.** Zero added instructions, so this one is genuinely free — the only
  build in the tree where that is true by construction rather than by
  measurement.

## 7. Settings contract and the pre-registered reading

**State these before launching, not after** (`ab-settings-sync`):

- `ser = class`
- `shadowset = full-shadow`
- path tracing ON, **direct sun**, sunlit close-up face at 0.3–1 m
- the same frame `117` was read on

Order, one launch:

1. `oil-inert` vs the default. **Must be indistinguishable.** If it is not,
   stop — §2 is wrong and every number in the table above is wrong with it.
2. `oilhi` vs the default. Look at the **grazing band**: the outer cheekbone,
   the flank of the nose, the brow ridge, the jaw under the ear. Facing skin
   is unchanged by construction, so if the whole face moved, something other
   than this rung moved it.
3. `oilhi-g` vs `oilhi`. Same band. The question is shape, not strength:
   `-g` should read as a more uniform lift, `oilhi` as a wider rim.
4. `oilhi2` only if one of 2 or 3 read as "still not enough".

The failure mode to watch for is the one `74` already named once: an
achromatic grazing haze that makes dim or indoor skin look plastic. `cons`
should now *counteract* that — the body darkens as the rim brightens — which
is the whole reason this retune is defensible at all.

## 8. Files

- `dev/oil_model.py` — the model and its 21 self-checks; `--table` prints §2
- `dev/patch_oil.py` — the detector and the two-operand rewrite
- `dev/verify_oil.py` — re-derivation from shipped bytes
- `dev/build_oil.sh` — the 9 gates
- `init.lua` — 5 rung rows

## 9. Verdict — SHOT, KEPT, AND MADE THE DEFAULT

**`oilhi` KEPT 2026-09-04.** User verbatim: *"oilhi looks great."* A LIVE
read-out, no capture. The default is now

```
gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll-bump-micro-oilhi
```

content sha `e80282bcf564d270`, parked as a byte-identical alias of
`skin.set/oilhi` (`dev/park_alias.sh`, 93 modules, `cmp` clean both ways,
`src_ser`/`ser_sha`/`ptq_sha` carried). The previous default
`…-ll-bump-micro` **is `oil-ctl` by bytes**, so it is the A/B 'before' and
needs no separate build.

The coat now ships at exponent 4.0, gain 1.0. Sixteen raygens unchanged.

Other content shas: `oilhi-g` `29a1c28c38452d30`, `oilhi2`
`f53ca8faf3eec6e7`.

### What the verdict does NOT establish

1. **The other lever was never walked.** `oilhi-g` (gain 1.0 → 1.25) and
   `oilhi2` (both) are parked and unshot. `oilhi` was compared against the
   default, not against them, so "the exponent is the right lever" is not
   something this read-out says — only that this rung is better than no rung.
2. **`oil-inert` was not shot.** §2's claim that `sat(2−r)` has been pinned
   at 1 for the whole life of the feature is still an argument from the
   disassembly plus a build that gates on it, not a screen result. The rung
   is parked and costs one launch.
3. **The grazing-band framing was not confirmed.** Facing skin *cannot* have
   moved (`(1−VoH)^p = 0` at `VoH = 1`), so whatever was seen was in the
   grazing band by construction — but no one checked a forehead-on shot to
   confirm it stayed put.

## 10. Follow-ups (not requests)

0. `oilhi-g` and `oilhi2` vs `oilhi`, and `oil-inert` vs the default — §9.
   Three rungs, one launch, and the only way to know whether the exponent is
   the lever that carried this.
1. `alpha_max` — §6. The ceiling is the loudest lever and it is now
   entangled with `117`'s `rough`.
2. The `sat(2 − r)` finding means `n_s` above 0.5 has only ever been an
   exponent knob. Every doc that describes it as an amplitude is wrong;
   `72`, `74` and `patch_compute_skin.sh`'s ladder comments should be
   corrected when someone next touches them.
