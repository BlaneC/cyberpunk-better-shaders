# Hair BRDF work (branch `hair-brdf`)

Goal: make hair look better under path tracing. The user runs a *stylized*
hair mod and finds it flat/waxy in PT.

## The core finding: PT hair gets no dedicated shading

The material `OpSwitch` (`%6862`, line 5701; second copy `%5562`, line 10709)
holds **only per-class parameter-record loaders**. Every class merges into one
shared eval: Lambert diffuse plus one isotropic GGX lobe. No anisotropy, no
tangent, no second lobe anywhere in the raygen.

So the path tracer shades hair like slightly rough plastic. That is why
stylized hair reads as waxy — the raster hair shader's tricks do not exist on
this path.

## Specular site map (spv_0170, first copy; re-locate structurally)

| id | meaning |
|---|---|
| `%5649` | perceptual roughness R = `NMin(%5648, 1)` (line 8547) |
| `%5655` | α = R² (line 8553) — **shared by eval AND the sampling branch** |
| `%691/%693/%695` | F0 rgb = metallic + 0.04 |
| `%9963` | NoV | `%9967` NoH | `%9971` VoH |
| `%9948` | L-side cosine — **area-light modified, NOT plain NoL** |
| `%9980` | GGX D | `%9986` Vis | `%9990` Schlick pow5 | `%9995–97` F rgb |
| `%7576/%7578/%7580` | spec out = F·D·Vis |

Diffuse triples: primary at lines 8883 / 9807 / 13891; env at 8914 / 9838 /
13922.

## What is implemented (all `spirv-val` clean, all identity-safe)

| tier | does |
|---|---|
| `hair2` | roughness reshape at each α source + gated grazing sheen |
| `hair3` | energy-normalized diffuse wrap |
| `hair23` | both |
| `hairdbg` | paints structure-tensor confidence on hair (red = no strand signal) |
| `hairaniso` | Kajiya-Kay lobe from the estimated tangent |
| `hairhunt` | tints 10 candidate classes 10 colours — **the class-discovery build** |
| `forcetint` | ungated tint of all 6 triples — **the null-result bisect** |
| `--with-tier1` | also applies skin c1, combined into one multiply per triple |

Every tier has an identity default (`s_h=1, a_min=0, k_sheen=0, w_wrap=0,
m_aniso=0`), and tier-1 output stays byte-identical.

### Design decisions worth knowing
- **Roughness reshape rewrites ALL uses of α**, so the importance-sampling
  branch and the eval agree — otherwise MIS is biased. A real BRDF change, not
  an eval-only hack.
- **Sheen is added to the spec outputs, not to F.** `out = F·vd`, so adding
  `sheen·vd` to the output equals adding sheen to F, and clamping to `vd` is
  exactly the F≤1 clamp. Needed because spv_0171 has **scalar** spec sites with
  no per-channel Fresnel expansion — an F-id route found 0 sites there.
- **The sheen splice is OpSelect-gated**, not left to `k_sheen=0`, because the
  clamp to `vd` is only a no-op where `out ≤ vd`. Gating makes non-hair pixels
  bit-exact by construction.
- **Diffuse wrap is spliced as `wrap/NoL`**, because NoL is already folded into
  the site's light weight; multiplying by wrap directly would apply the cosine
  twice.
- **α is per-copy**: three sources per module (`%5655`, `%5721`, `%5344` in
  spv_0170), each feeding two spec sites.

## The tangent question — resolved twice

**First verdict (correct but incomplete):** no *geometric* tangent exists. The
hit payload is 16 bytes with every bit accounted for, and the raygen has zero
cross products. True Marschner is out of reach from a raygen swap.

**Correction:** a tangent can be **estimated**. A screen-space normal G-buffer
is readable (SRV `registers[1] + 2`), and pixel coords are live everywhere, so
neighbour fetches can be spliced. On a cylindrical fibre the normal rotates
fast *across* the strand and stays constant *along* it, so the minor
eigenvector of the normal field's structure tensor is the strand direction, and
`(λ1−λ2)/(λ1+λ2)` measures confidence. Implemented in `emit_aniso`.

A synthetic-fibre test caught a real bug before it shipped: the single-row
eigenvector form `(l1−d, b)` is a zero vector when the strand aligns with a
screen axis, giving a 90°-wrong tangent at angle 0. Fixed by computing both row
forms and picking the longer branchlessly. Recovery is now exact (0.00° error)
at every tested angle; flat normals give confidence 0, so the factor stays 1.

**Untested risk:** this depends on the hair normals carrying strand flow. A
stylized mod may have smooth/flat hair normals, in which case the tensor is
degenerate and the whole avenue is dead. That is exactly what `hairdbg` exists
to answer, and it has never been run.

## THE BLOCKER

All hair tiers need **hair's G-buffer material class N**, which is unknown.
`hairhunt` was built to find it in one launch. It renders nothing — including
its own control. See `01-BLOCKER.md`.

Nothing about hair can be concluded until something visibly renders.

## Order once rendering works

1. `hairhunt` → read N off the colour.
2. `hairdbg --hair-class N` → red means anisotropy is dead for this hair mod;
   green means proceed.
3. `hair23 --hair-class N --with-tier1` → the shippable improvement.
4. `hairaniso` only if step 2 came back green.

## Fallbacks if hair never tints but skin does

- Hair may **share skin's class** (class 1) — some engines treat hair as a skin
  variant separated by a flag. If hair turns red alongside skin, that is the
  answer, and gating it apart needs one of the unidentified material flags
  (`0x200` / `0x2000`).
- Hair may be gated off by material flag **`0x800`**, which zeroes the whole
  diffuse term (`01-BLOCKER.md` §6).
- Hair may not be path-traced at all — some hair renders in a forward/alpha
  path, and the hair mod could force that.
- The class field is bits[9:5], so it spans 0–31; the hunt's default candidate
  list only covers values that appear as `OpSwitch` cases. Extend
  `HUNT_PALETTE` and sweep 9–12, 15–31.
