# 08 — Shifted dual-lobe hair (R + TRT) + two latent spec-output bugs

Written Aug 26 2026. Adds the Marschner-flavoured shifted dual-lobe to hair
(Phase 2 of the fidelity roadmap) and, in the process, fixes **two latent bugs
in the spec-output splice path that made parts of the shipped hair overlay
silently not render.** Both were proven by dead-code analysis on the generated
`.spvasm`, not inferred from docs (per the "docs may be outdated" warning).

---

## 1. The feature: shifted dual lobe (R + TRT)

Vanilla path-traced hair = one isotropic GGX lobe. The Kajiya-Kay aniso pass
shaped that into a strand-following highlight. The dual lobe adds the two
physically-distinct highlights real hair has, each **shifted along the strand**:

- **R (primary reflection)** — sharp, white, shifted toward the root.
- **TRT (transmission)** — wide, tinted, shifted toward the tip. This is the
  coloured "glint" that most sells real hair.

Math (validated offline by `dev/validate_dual_lobe.py`): with the
structure-tensor tangent `T` and a per-lobe tangent shift `s = tan(beta)`,

```
tpH  = (ToH + s*NoH) / sqrt(1 + 2*s*ToN + s^2)   == dot(normalize(T+s*N), H)
lobe = (1 - tpH^2)^(p/2)                          == sin(T',H)^p  (Kajiya form)
factor_c = aniso_fac*(1 + m_dual*aniso*wR*L_R)
         + aniso_fac*m_dual*aniso*wTRT*L_TRT*tint_c     (tint_c = trt_r/g/b)
combined_c = factor_c      (multiplies the spec outs, hair-gated)
```

- The shift is a **tangent shift** `T' = normalize(T + s*N)` (Scheuermann/
  Marschner real-time form), computed in closed form with no v3 normalize —
  the validation script confirmed it matches explicit vector normalize to
  4e-15, that `s=0` is identity, and that the R/TRT peaks move in **opposite**
  directions (+7.1° / -9.8° for beta=-7°/+10°).
- **Additive-boost form**, not the ratio form originally sketched: the ratio
  form `(wR*LR+wTRT*LTRT)/D_vanilla` hit **713×** in a 20k-config sweep
  (firefly risk). The additive form is bounded at
  `1 + m_dual*(wR+wTRT)` ≈ 2.3×, so no clamp is needed and no division by a
  possibly-tiny `D_vanilla`.
- `aniso` (the structure-tensor confidence) scales the whole thing, so
  non-fibre pixels fall back to exactly 1.0.

### Knobs (all identity-safe; `--set k=v`, flow through brdf_params.txt)

```
m_dual 1.0      strength; 0 = off/identity
beta_R -7.0     R shift, deg     beta_TRT 10.0   TRT shift, deg
p_R 28.0        R exponent       p_TRT 10.0      TRT exponent
wR 1.0          R weight         wTRT 0.3        TRT weight
trt_r/g/b 1.0/0.85/0.55  TRT transmission tint (identity at 1,1,1)
# GI-resolver variants (wider, TRT-weighted):
m_dual_gi -1    (<0 = follow m_dual)   p_R_gi 8   p_TRT_gi 6   wTRT_gi 0.5
```

`m_aniso=0,m_dual=0` ⇒ combined factor `== 1`; `k_sheen=0` ⇒ sheen not
emitted at all. Non-hair pixels and `--vanilla` are bit-exact.

---

## 2. Bug A — the grazing sheen was DEAD CODE (never rendered)

**The shipped "grazing sheen" (39 sites) produced no visible effect.** Two
independent passes each called `replace_all_uses` on the same `s['outs']`:

1. `build_hairaniso` ran first: `out → out*sel_aniso`, consuming every use.
2. `build_hair_spec` 2b (sheen) ran second: emitted
   `c = Select(gate, min(out+add, vd), out)` then `replace_all_uses(out, c)` —
   but `out` had no uses left, so **`c` was dead.**

Dead-code analysis on a patched module (`05511714f20081b4`): every sheen
`OpSelect` (`%3489, %3492, %3495, %3501, %3504, %3507`) had **zero uses**.
Not caught earlier because the effects are not independently toggleable and
aniso dominates visually. (00-ARCHITECTURE §4 even warned "two passes
rewriting the same scalar's uses clobber each other" for the *diffuse* path —
the same failure existed, unnoticed, on the *spec* path.)

**Fix:** one combined pass — `build_hair_spec_lobes` — computes
`(sheen_base) × (aniso_fac × dual_fac)` and multiplies each out **once**.
Sheen is now live for the first time.

## 3. Bug B — `last_out` anchoring missed interleaved out-consumers

The old code anchored each out's rewrite at `last_out` (the last out's def
line) and called `replace_all_uses(out, new, last_out)`. But on modules that
**interleave** outs with their consumers —

```
%913 = vd*F_r ; %914 = %913*w_r      <- consumer of out1, BEFORE last_out
%915 = vd*F_g ; %916 = %915*w_g
%917 = vd*F_b ; ... %918 = %917*w_b  <- consumer of out3, AFTER last_out
```

— consumers defined *before* `last_out` are never rewritten, so those channels
kept the vanilla value. On `05511714f20081b4` the aniso multiply for channels
1&2 (`%3013`, `%3014`) was **dead** while channel 3 (`%3015`) was live: aniso
was applied to **one of three channels**. The same bug existed in the GI
resolver path (26 dead effect multiplies on `99bb7c2698997b2a`).

**Fix:** per-out-at-def anchoring. The combined factor is computed in a block
inserted immediately before the **first** out's def; each out is then
rewritten **right after its own def line** (`replace_all_uses(out, new,
odef)`), which catches every consumer regardless of layout. Applied to both
`build_hair_spec_lobes` (direct) and `build_hair_gi` (indirect).

---

## 4. What ships now (this build)

| splice | sites | note |
|---|---|---|
| alpha reshape (2a) | per source | unchanged |
| Kajiya aniso | 361 direct + 81 GI | now reaches **all** channels (Bug B) |
| **shifted dual lobe (R+TRT)** | 361 direct + 81 GI | **new** |
| **TRT transmission tint** | 361 direct + 81 GI | **new** (constant RGB; per-pixel albedo not recoverable) |
| grazing sheen | 39 direct | now **live** (Bug A) |
| diffuse wrap + c1 | 149 | unchanged (build_skin_c1) |
| **tensor hoist** | 68/68 direct modules | **new** (tensor + tangent emitted once, not per site) |

Verification (all local, no game):
- `spirv-val` clean on all **70** modules (68 direct + 2 GI); 14 expected
  skips (11 no class gate, 3 no normal G-buffer) — unchanged from baseline.
- Site totals **361 direct + 81 GI** — match the pre-existing baseline.
- **0 dead effect ids** across all patched modules (was: sheen fully dead,
  aniso partially dead).
- **Tensor hoist** succeeded on all 68 direct modules (no per-site fallback).
- `--vanilla` ⇒ identity (sheen skipped, every factor == 1); `trt=(1,1,1)`
  ⇒ identical dual math to the pre-tint build.
- `dev/validate_dual_lobe.py` — shift math, degenerate cases, firefly bound.
- `hairhunt` behaviour unchanged (`>>5` modules work, `&31` don't —
  pre-existing).

**Disable path (vanilla A/B).** Every new effect ships in the `swaps.hair/`
overlay, which the CET "Callisto hair BRDF" switch turns off by writing
`hair.disable` (the layer then serves no compute swaps). With that plus
shadowcull/skinray/kernel/tier off, the render is bit-exact vanilla — the
intended A/B baseline. Per-knob hair tuning is build-time only (`--set
m_dual=… trt_r=…`); the knobs are not yet CET sliders (see §5).

**Still needs the game:** visual A/B (`compare_brdf_ab.py` masked to hair),
firefly check on backlit hair, and the m_aniso-vs-m_dual tuning A/B (the dual
lobe subsumes the Kajiya highlight shaping; consider lowering `m_aniso`).

---

## 5. Deferred

- **Per-pixel TRT albedo tint.** The constant `trt_r/g/b` tint is a stand-in:
  the compute resolvers do **not** expose the diffuse albedo in the triple
  form `classify_triples` expects (0/82 modules recover it), and 425/481 spec
  sites are scalar (a per-channel tint is impossible there without splitting
  the Fresnel). A real per-pixel tint needs a new albedo recovery for these
  modules.
- **CET sliders for the hair knobs** (`m_aniso`, `m_dual`, `trt_r/g/b`, …).
  Currently the hair overlay is pre-built once (`patch_compute_hair.sh`) and
  toggled whole by the hair switch; exposing per-knob sliders would require
  rebuilding 84 compute modules at launch, which is too slow. A cheaper path
  is a few pre-built overlay variants toggled by flags.
- **180° tangent ambiguity** swaps the R/TRT shift directions; bounded by
  small |beta| and the aniso confidence. Acceptable.
