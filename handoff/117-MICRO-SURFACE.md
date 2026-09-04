# 117 — The other four-fifths of the pore, plus the layer `72` forgot (`micro`)

**Status 2026-09-04: SHOT, KEPT AND MADE THE DEFAULT (§9). User verbatim:
*"micro looks great!"*** The shipping stack is
`gi-50b-…-curv-t7hue1-ll-bump-micro` (content sha `a581bc58f3c1eddc`, 93/93 =
`skin.set/micro`, `dev/park_alias.sh` byte copy). The previous default
`…-curv-t7hue1-ll-bump` (`115`) is `micro-ctl` by bytes and is the 'before'
for any future A/B. Seven rungs remain in `skin.set/`; the five single-half
rungs were **not** walked, so which half carries the verdict is open (§9).

Base: `gi-50b-…-cap6-glintdense-curv-t7hue1-ll` — the same base `115` used.
Control: `micro-ctl` is **`cmp`-identical to the shipped default
`skin.set/bump` in 93 of 93 modules** (§4 gate 6b). Every differing byte in
every other rung is one of the five halves and nothing else.

---

## 0. What it is, in one paragraph

`115` built a height field out of the skin albedo (`h = H·L`) and spent it on
exactly one thing: a tilt. This spends the same field four more ways, and adds
the one multiply `72`'s oil layer has been missing since it shipped. Nothing
here needs a fetch the `115` block does not already make — two more albedo taps
for a Laplacian, and then arithmetic on values already in the lighting block.

| half | edit | why |
|---|---|---|
| `occ` | `diffuse *= 1 − 0.35·cav` | a pit is shadowed by its own rim. `115` makes a pore's two rims part in brightness; nothing yet **darkens** the pit |
| `rough` | `alpha *= 1 + 0.5·cav` | `115` §6 / §10.4. Pore-varying α is what turns one oil highlight into skin instead of plastic |
| `term` | `diffuse *= 1 + w − w²` | Chiang et al. 2019. The fix for the artifact **`115` itself introduces** |
| `gtso` | `spec *= SO(NoV, ao, α²)` | Jimenez et al. 2016. `38` A5 was parked as "needs a bent normal"; this form does not |
| `cons` | `diffuse *= 1 − F` | `72`'s oil layer is a pure **add**. A coat that adds energy without removing `(1−F)` from the diffuse beneath it is the textbook wet-plastic failure |

## 1. Where it lives, and the consequence

The 77 compute resolvers, 75 patched (the same two decline by hash as `115`).
Under PT the raygens shade local lights themselves, so — exactly as `112` §12,
`113` §1 and `115` §1 — **this changes sunlit faces and does nothing under a
neon at night.** A night frame is the null, not a failure.

## 2. The maths (`dev/micro_model.py`, float32, as emitted; 18 self-checks)

    lap   = 0.25·(L(x+1) + L(x−1) + L(y+1) + L(y−1)) − L0            [luma]
    lap'  = lap · (1 − smoothstep(C0, C1, |lap|))                    edge-kill
    cav   = clamp(lap' / CREF, 0, 1)                                 0 flat, 1 a pore
    cav  ·= (class == 1) && `109`'s two silhouette comparisons

    occ:   ao = 1 − KOCC·cav
    rough: α' = α·(1 + KRGH·cav)          on the shipped `OpSelect(class==1,…)`
    term:  w  = clamp(NoL(N') / max(NoL(N), 1e−4), 0, 1);  f = 1 + w − w²
    gtso:  SO = clamp(pow(NoV + ao, exp2(−16·α² − 1)) − 1 + ao, 0, 1)
    cons:  kd = select(class==1, 1 − F_channel, 1)                   per channel

| knob | value | why |
|---|---|---|
| CREF | 0.02 luma | `115`'s own reference pore step; `cav = 1` is one pore deep |
| C0, C1 | 0.05, 0.12 | verbatim `115` §2: a lip line, brow or eyeliner is 0.15–0.4 and must not become a groove |
| KOCC | 0.35 | the deepest pore keeps 65% of its diffuse. AO, not a black dot |
| KRGH | 0.50 | the deepest pore is 1.5× rougher. Multiplicative, so `108`/cap's clamp keeps its meaning |

Three notes on the terms, in the order they will be questioned.

**(a) `occ` is not double-darkening.** `115` §0 says the shipped micro-shadow
(`44` §3.4) already reads albedo darkness as occlusion. It does — as a term
whose full range is 0.72% (`%1129` in the resolver: `clamp((R²−0.1)·5)·0.0072`).
That is not an ambient-occlusion term and this is.

**(b) `term` only ever brightens.** The lobe already carries `NoL(N') = w·NoL(N)`,
so the multiplier that turns it into Chiang's `G(w)·NoL(N)` is `G(w)/w = 1+w−w²`,
which is 1 at `w = 1`, 1.25 at `w = 0.5`, and ≥ 1 everywhere on [0,1]. `w` is
clamped above at 1, so a pore that faces *toward* the sun is left alone. This is
the half that is load-bearing only **because** `115` shipped: perturbing a
shading normal is what creates the hard micro-terminator in the first place.

**(c) `cons` is per channel and uses the module's own Fresnel.** Not an average,
not a refit — `F_r`, `F_g`, `F_b` are the three values the specular lobe of the
same light already multiplies, which on skin is `72`'s oil Fresnel
(`F0 + (0.96−F0)·(1−VoH)^4.5·1.1`, clamped). At the shipped `F0 = 0.04` that is
a 4% removal at normal incidence and a large one at grazing — which is the
point, and is why the oil can then be pushed.

## 3. What is found, and how (`dev/brdf_sites.py`)

Nothing by name, nothing by id (GOTCHAS 5/10/12). Three anchors:

* **roughness** — the GGX `D` term is the only `OpFDiv` whose denominator is a
  multiply by `π`; its numerator is `α·α`; `α` is an `OpSelect` and its
  predicate **is** the module's class test.
* **diffuse** — the Disney retro constant `1/π − R·0.107508637`, walked up its
  single-consumer product chain to the node three per-channel products multiply.
* **specular tail** — `D·NoL·Vis` (`Vis` = the game's `0.5 / (Smith sum)`,
  `28` §2), walked *down* to the first node three per-channel products multiply.
  The diffuse site is paired to its specular lobe through the shared light
  colour, which also names the Fresnel triple in the diffuse channels' own
  colour order.

Census over the 75 patched modules of the base, all reproduced independently by
the verifier from the shipped bytes:

| family | sites | modules |
|---|---|---|
| roughness selects (deduplicated — one select can anchor several `D` terms) | 343 | 75/75 |
| diffuse BRDF scalars | 142 | 75/75 |
| specular tails | 336 | 75/75 |
| diffuse paired to a specular lobe | 142/142 | 75/75 |

Applied: `rough` 343/343, `occ` 142/142, `cons` 426 = 3×142, `gtso` 336/336,
**`term` 106 of 142**.

**The one honest gap.** At 36 of the 142 diffuse sites the light's `NoL` is an
`OpPhi`, not a `Clamp(Dot(N, L))`, so the raw-normal dot the terminator factor
needs cannot be re-issued without following the phi. Those sites get the other
four halves and no `term`. The patcher reports it per module and the verifier
does not demand 142.

## 4. Gates (`dev/build_micro.sh`, all passed 2026-09-04)

0. base provenance: 77 compute + 16 raygen, `src_ser=` present, default parked
1. `dev/micro_model.py` — 18 float32 assertions
2. disassemble 77
3. round-trip neutrality: 77/77 `dis → as` byte-identical at each module's own
   version, so the control is not tautological
4. patch 7 rungs + 2 decoys
5. coverage from the patcher's reports: 75 modules and exactly the two known
   declines in every rung; the census is **identical in all seven rungs**; each
   half is applied at every site of its own family and at **zero** sites in a
   rung that does not declare it; `spirv-val` clean on every module
6. assemble: 93 modules, 16/16 raygens `cmp`-identical to the base (compute-only,
   asserted, not assumed), `spirv-val --target-env vulkan1.4` on all 93
6b. **`micro-ctl` == `skin.set/bump` in 93/93 modules**; each feature rung
   differs from the default in exactly 75 of 77 compute modules; all 21 rung
   pairs differ
7. the verifier on shipped bytes (§5), plus 19 rejections
8. install

## 5. The verifier (`dev/verify_micro.py`)

Takes a rung's bytes and nothing else — no report, no base, no id from the
patcher. It re-runs the detector on the *patched* module (which is why
`brdf_sites` accepts a scaled roughness select and a factored diffuse BRDF),
then for each half re-derives the emitted ladder and asserts the wiring:

* the cavity: exactly **one** banded chain per module — a `NClamp(lap'/CREF)`
  whose `lap'` is `lap·(1 − u²(3−2u))` and whose `lap` is `0.25·(a 4-term FAdd)
  − centre` — gated by exactly one `OpSelect(gate, cav, 0)`, whose `gate` is an
  `OpLogicalAnd` of one `OpIEqual` class test and `109`'s two `OpFOrdLessThan`
* `rough`: `α = sel·(1 + KRGH·cav)`, **and no unscaled reader of `sel` survives**
* `occ`: `1 − KOCC·cav` inside the diffuse BRDF's factor tree
* `term`: `1 + w − w²` with `w` an `NClamp` of an `OpFDiv`
* `gtso`: the full Jimenez ladder — `Exp2(Log2(x)·Exp2(α²·(−16) − 1)) − 1 + ao`
* `cons`: per channel, `OpSelect(is_skin, 1 − F, 1)`
* **every half is looked for on every rung**, so a rung that ships a half it does
  not declare fails. That is what makes "read as another rung" a real rejection.

Rejections it makes (gate 7): the unpatched base; **the shipped default, i.e.
`115` alone**; the all-off control; the no-edge-band decoy; the
no-silhouette-guard decoy; `micro` read as unguarded; a wrong `CREF`, `KOCC` or
`KRGH`; and, in both directions, `micro` against each of the five single-half
rungs.

## 6. What is NOT in this build

- **The raygen port.** `115` §10.3 unchanged: no local-light effect. `116`'s
  scratch channel is the route and Stage 3b was mid-flight when this was called.
- **`term` at the 36 phi-NoL sites** (§3).
- **A `micro-vis` diagnostic.** `bump-vis` already paints the same height field's
  gradient; the cavity is its Laplacian and would need its own rung. If `micro`
  reads as noise rather than pores, build it before tuning knobs.
- **Cost.** Unmeasured. Two extra albedo fetches and roughly 30 + 6·sites
  instructions per pixel per resolver.
- **Footprint-aware `H`** (`115` §10.2) — still open, and it applies to `CREF`
  the same way.

## 7. Settings contract and the A/B — READ BEFORE THE LAUNCH

Required, stated in advance (memory `ab-settings-sync`); do not infer any of
this from a capture afterwards:

* `ser = class`
* `shadowset = full-shadow`
* path tracing ON
* **DIRECT SUN.** A night or interior frame is the null by construction (§1)
* close-up face, **0.3–1 m**
* everything else exactly as the shipped default

Order:

1. **`micro`** — all five. Sunlit cheek and nose, 0.3–1 m.
2. **`micro-ctl`** — must be indistinguishable from the default. It is the same
   bytes; if it looks different, the read is not a read.
3. If (1) moved: walk `micro-occ`, `micro-rgh`, `micro-trm`, `micro-gts`,
   `micro-cns` and say which one carries it.
4. The edge check `115` §8 step 4 still applies and now applies twice: a lip
   line and an eyebrow must not gain a **groove** (`occ`) or a **matte streak**
   (`rough`). Either one is a reject for that half, not for the build.

What each half should look like if it is working:

| rung | expected |
|---|---|
| `micro-occ` | a fine, even darkening in the pore field; skin reads less waxy. Blotches or a dirty look = `KOCC` too high or the band too narrow |
| `micro-rgh` | the oil highlight loses its hard edge and gains structure. A uniformly duller face = the cavity is not tracking pores |
| `micro-trm` | the light/shade boundary on the cheek and jaw softens. **Nothing may get darker anywhere** — if something does, the sign is wrong |
| `micro-gts` | grazing specular in creases (nose wing, eye corner, lip seam) stops floating |
| `micro-cns` | the wettest parts of the face lose a little diffuse brightness; the specular is untouched. This is the one that makes the oil pushable |

Known failure modes and what they mean:

| symptom | reading |
|---|---|
| pores look like noise, not skin | `CREF` too small — the Laplacian is measuring texture filtering |
| a black line at the lips or brow | the edge-kill band is too narrow for this texture; raise `C1` |
| the face reads flatter, not deeper | `occ` and `rough` are fighting the `115` tilt; shoot the single-half rungs |
| everything looks the same | check the frame is direct sun (§1), then `micro-ctl` to prove the harness |

## 9. Verdict and the default (2026-09-04)

Served live, no capture, user verbatim: **"micro looks great!"** Kept and made
the default in the same breath, so the reading is one A/B against `115` alone
and nothing finer.

What that does and does not establish:

* **Established.** The five halves together, in direct sun on a close-up face,
  are an improvement over the shipped `115` default. `micro-ctl` was not shot,
  but it is the previous default's bytes exactly, so the 'before' half of the
  A/B is the frame the user had been looking at all session.
* **NOT established.** Which half carries it. `micro-occ`, `-rgh`, `-trm`,
  `-gts` and `-cns` are all still parked and all still unshot. It is entirely
  possible that one half does the work and another is inert or mildly harmful
  and is being carried by the others. §7's attribution walk is now a
  **follow-up**, not a prerequisite.
* **NOT established.** The `115` §8 step 4 edge check — a lip line and an
  eyebrow — was not reported on. `occ` and `rough` are the two halves that
  could put a groove or a matte streak there, and neither has been ruled out.
* **NOT established.** Cost. Still unmeasured: two extra albedo fetches and
  roughly 30 + 6·sites instructions per pixel per resolver, on top of `115`'s
  243 + 6 fetches.

## 10. Follow-ups, in order

1. The attribution walk (§7 step 3) and the edge check (§7 step 4). One launch,
   same frame, and it is the only way to know whether all five are earning
   their instructions.
2. `cons` makes the oil layer safe to push. `72`'s coat strength was tuned
   against a BRDF that did not remove `(1−F)` from the diffuse; with that
   removal in place the same strength is now conservative. A `-oilhi` rung on
   top of this default is cheap and is the obvious next win.
3. `term` at the 36 phi-valued-NoL sites (§3).
4. The raygen port (`115` §10.3) — unchanged, and `116`'s scratch channel is
   still the route.
5. Footprint-aware `H` (`115` §10.2), which applies to `CREF` the same way.

## 8. Files

    dev/micro_model.py      the maths + 18 float32 self-checks
    dev/brdf_sites.py       the three structural anchors and the lobe pairing
    dev/patch_micro.py      the patcher (emits 115's block verbatim, then five halves)
    dev/verify_micro.py     re-derives every claim from shipped bytes
    dev/build_micro.sh      the 9 gates
    dev/patch_bump.py       +`want_lum` (byte-neutral: hands back 115's luma taps)
    dev/park_alias.sh       parks micro under the full stack name
    init.lua                7 rungs + the stack row + the default skinspec
    handoff/117             this
