# 80 — Cloth sheen (A2): feasibility, and why the gate is *rough dielectric*, not *material class* (2026-08-31)

## 0. Verdict

**Feasible, direct-light only, on a proxy gate.** Built; see `81`.

Three questions were asked. The answers, up front:

- **(a) Gating.** Option (i) — *class == cloth* — is **dead offline** and `22`
  already said so; this pass proves *why* with the disassembly rather than by
  assertion. Option (ii) — a pure proxy on already-fetched inputs — is
  available at every site but **cannot separate cloth from concrete**. Shipped:
  **option (iii)**, ungated-on-rough-dielectrics with the amplitude bounded so
  that the non-cloth rough dielectrics get a small grazing retroreflection they
  physically have. Exclusions are exact and cheap: **class 1 (skin) and class 4
  (hair) are cut by the class word, every metal and every polished/coated
  dielectric is cut by `max3(F0) < 0.09`, and smooth surfaces are faded out by
  a roughness ramp.**
- **(b) Energy.** `f_d *= (1 − k·E1·wr)` **is reachable at the same sites** —
  the Burley scalar is a named, single-consumer value. Implemented. It is also
  numerically irrelevant (0.36% of the diffuse at the shipping k), so the
  fallback of "bound the additive error numerically" was done anyway as a
  cross-check and agrees.
- **(c) Bounce path.** **Impossible.** `74` §0 is correct and the bytes agree:
  the GI diffuse raygens compute no view vector, and a Charlie×Neubelt lobe is
  a function of `V` through both `H` and the Neubelt visibility. Direct-only
  shipped, closed.

## 1. What the older docs get right, and the one thing they get stale

`22-CLOTH-BRDF-FEASIBILITY.md` concluded "no cloth BRDF exists; clothing is
shaded by the ungated Standard path; the cloth class ID is unreadable
offline." **All three still hold against the bytes.** Nothing in this pass
contradicts `22`, `57` or `58`.

**One thing is stale, and it is in the task brief, not the docs.** The brief
names the standing base `gi-50b-bleed-oil-sheen-lumn`. It is not.
`78` §5.1 and `CURRENT.md` both record **`-deep` beating `-lumn` on screen at
22:28**, the live `brdf_params.txt` reads
`skinspec=gi-50b-bleed-oil-sheen-deep`, and `~/callisto_launches.log`'s last
line served `skin_sha=f8f2890ebcd48252` = `-deep`. Only the newest git commit
*message* still says `-lumn`; the `-deep` verdict landed after that commit.
**Both new rungs are built off `-deep`.** If the user's real intent was
`-lumn`, the rungs must be rebuilt — one command, `81` §7.

## 2. (a) Gating — the evidence, option by option

### 2.1 Option (i), class + subtype: dead, and here is the census that kills it

A census over 240 compute disassemblies of every constant compared against the
class word (`word >> 5`) and the sub-enum (`word & 31`):

| tested value | where | modules |
|---|---|---|
| class 0 (Standard) | class word | 1 |
| class 1 (skin) | class word | 51 |
| class 3 | class word | 2 |
| class 4 (hair) | class word | 44 |
| class 2, 5, 6, 7 | — | **never tested by any compute shader** |
| sub 17 | sub-enum | 1 |
| sub 21 | sub-enum | 54 |
| sub 25 | sub-enum | 54 |

Two independent reasons this closes the option:

1. **No shader anywhere tests a subtype under class 0.** The three sub values
   that *are* tested have exactly one kind of consumer, and it is not a
   material identity — it is a **light-channel flag**. In
   `05511714f20081b4` lines 1110–1122 the pattern is
   `sub == 21 || (sub & 30) == 12 || (sub & 14) == 14 → set bit 512`, and
   `sub == 25 → set bit 1024`. Those are channel masks, not "this is cloth".
   Reading them as a material taxonomy would be reading the wrong field.
2. **No absolute sub index is recoverable offline.** `57` §5 already proved
   the paint probe can only order sub values, not name them; `13`'s on-screen
   class hunt named 1 = skin, 4 = hair, 5 = palm trees and **never once landed
   on clothing**. So even if a cloth sub existed, we do not have its number,
   and getting it costs a probe-launch ladder — which the brief forbids.

**Cost to revive it:** one paint-probe launch series per candidate sub value.
Not worth it before the look is even proven.

### 2.2 Option (ii), pure proxy: available but not discriminating

Every input a proxy would want is already in a register at the BRDF site:
roughness (as the site's own `alpha`), `F0` (hence metallic, since
`F0 = lerp(0.04, albedo, metallic)`), albedo, and the diffuse scalar `f_d`.
Detection is solid — 457/457 sites, after lifting `F0` through `OpPhi`
(§2.4).

It still fails the question asked. Cloth's signature in that space —
mid-to-high roughness, dielectric `F0`, moderate-chroma albedo — is **the same
point in the space as painted plaster, concrete, wood and dirt**. There is no
threshold on those four inputs that admits a denim jacket and rejects a
painted wall, because at the shading site they are the same material.
Any tighter proxy (albedo chroma, luma windows) would be a texture-dependent
lottery that fails differently per garment; that is worse than a clean
physical bound.

### 2.3 Option (iii), shipped: rough dielectric, bounded

```
gate  = (class != 1) && (class != 4) && (max3(F0) < 0.09)
wr    = saturate((alpha - 0.10) * 5.0)          // alpha = the site's own roughness^2
sheen = k * D_charlie(a=0.25) * V_neubelt * wr * defres_weight
```

What each clause buys, and the honest cost:

- `class != 1` — **skin already has its own Charlie lobe** from `72`/`73`.
  Without this the shipped peach fuzz double-dips. Non-negotiable; the brief
  called this out and it is enforced in the bytes.
- `class != 4` — hair is a specular-shifted anisotropic path; a Charlie lobe
  on it is just wrong.
- `max3(F0) < 0.09` — kills **every metal** (`F0` = albedo, ≥ 0.5 for any real
  metal), and kills glass, clearcoat and polished plastic, whose authored `F0`
  sits above dielectric 0.04. This is the clause that makes "ungated" safe:
  the failure mode the brief feared (sheen on chrome, sheen on glass) cannot
  happen, because those pixels never reach the add.
- `wr` ramp on `alpha` — 0 below roughness² 0.10, full at 0.30. Mirrors,
  car paint and window glass fade to exactly zero, so the lobe only exists
  where a fuzzy grazing response is plausible in the first place.
- **What still gets it, honestly:** concrete, plaster, painted drywall, wood,
  dirt, road. They are rough dielectrics and they get the lobe. This is not a
  bug that was hidden — it is the design. Real rough dielectrics *do* have a
  grazing retroreflective lobe; at the shipping amplitude theirs is 11–13% of
  local diffuse at 80° and 0.19% head-on, which is inside plausible and far
  below "painted white". **The A/B is designed to catch it anyway**: `81` §5
  requires a hard non-cloth reference in the same frame.

### 2.4 Why the gate is trustworthy in the bytes, not just on paper

- The class comparison reuses the **same class word** the shipped skin gate
  already reads — the verifier machine-checks that both `!= 1` and `!= 4` hang
  off one `OpShiftRightLogical`, so there is no second, differently-decoded
  material read to get out of sync.
- `F0` needed a fixpoint lift through `OpPhi`: 81 of 457 sites (in
  `99bb7c2698997b2a` and `ab0bc2fee876d489`) compute `F0` inside a guarded
  block and read it back through a phi. Naive dominance found 376/457. With
  the lift, **457/457**, and the build **fails** below that count.
- `alpha` is taken as the site's own alpha, not recomputed from roughness.
  In the patched parent, the alpha def is an `OpSelect` (the class-1 gloss
  cap), so `OpFMul r r` does not exist to find. On any gate-true pixel the
  class is not 1, so that select provably yields authored roughness², and in
  every case it is the value the site's own GGX uses — self-consistent by
  construction.

## 3. (b) Energy — reachable, and measured

The renormalised Burley diffuse `f_d = (1/π − rough·0.107508637)·FD(NoL)·FD(NoV)`
leaves a **named scalar with a single consumer** at 173 sites — exactly the
count of the `c1` constant. `replace_all_uses` on it is safe and was proven so
by the verifier's identity check.

Shipped: `f_d *= (1 − k·Ê1·wr)`, `Ê1 = 0.0072` (the hemisphere-averaged
directional albedo of the shipped lobe, from `dev/cloth_model.py`).

- Damped at **173 of 173** diffuse sites; the build fails otherwise.
- The dielectric clause is **deliberately absent from the damp gate**. A
  metal's diffuse colour is `albedo·(1 − metallic)` = 0, so damping it scales
  zero — adding the test would only add instructions.
- Per-site damping of the 457 *specular* sites was tried first and reached
  272/457. Damping per *diffuse* site instead reaches 173/173, which is the
  complete set.

**Magnitude.** At the shipping k = 0.5 the factor is 0.996 — a 0.36% dim of the
diffuse. Per-view `E1` spans 0.0013 (head-on) to 0.0232 (80°), so the worst
un-damped energy error had this term been dropped is **+0.80%**. It is
implemented because it is free and correct, not because it is visible.

## 4. (c) Bounce — impossible, one sentence and the proof

`74` §0 says the GI diffuse raygens compute no view vector; `50` §3.1 proves
it structurally; a Charlie D needs `H` and Neubelt's V needs `NoV`, both
functions of `V` — **so bounce sheen cannot be evaluated in those raygens at
all**, and the specular GI family that does have `V` measured nil share
(`50` §2). Direct-only. Closed, not deferred.

## 5. What would change the verdict

- An on-screen paint probe that names a cloth sub-enum under class 0 →
  option (i) becomes live and the concrete false-positive disappears. Cost:
  a probe launch ladder.
- The A/B showing sheen on walls as objectionable → tighten `cloth_a0`
  upward, or drop `cloth_f0max`, or abandon. Knobs are exposed; `81` §7.
