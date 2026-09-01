# 84 — Environment chroma bleed: two rungs off `-clothhi`, luminance held exactly, never launched (2026-09-01)

Night City's neon reaching the walls. The chroma of the light that bounced
onto a surface is widened on that surface; each pixel's Rec.709 luminance is
held **exactly**, by construction, not by tuning — the `78` safety rail
carried from skin to the environment.

## 0. State

**Built, verified, parked, and registered in the selector source. Zero
launches, no verdict, no commit, `make install` NOT run.** The rungs are
default-off; the live selection is still `gi-50b-bleed-oil-sheen-deep-clothhi`
(`brdf_params.txt` read 2026-09-01 02:30). **Nothing here is on screen. A
one-variable A/B against the standing base is the only thing that decides
whether it stays** (§7).

| rung | what it is | content sha |
|---|---|---|
| `gi-50b-bleed-oil-sheen-deep-clothhi` | the standing base, untouched | `b5821b919deede8d` |
| `gi-50b-bleed-oil-sheen-deep-clothhi-envbleed` | the candidate, `q = 0.35` | `8ee6ad5c38e16afe` |
| `gi-50b-bleed-oil-sheen-deep-clothhi-envbleedhi` | the louder half of the A/B, `q = 0.70` | `dd1b7bf4ed7843dc` |

Both are the standing base **plus one variable**, byte-proven: all 77 compute
and all 12 `rgs_reference_main` modules are **byte-identical** to `-clothhi`,
and exactly **4 of 16 raygens** differ — the four ReSTIR-GI diffuse ones.
Skin, hair, cloth sheen, oil, the terminator bleed: bit-identical.

## 1. The mechanism inversion — read this before "improving" it

**The obvious splice site is the wrong one, and it fails silently.** The
`74`/`78` bleed rides the ST tail's `albedo_ch · (1/π) · NoL` triple. That
triple is **albedo-side**: the reservoir's radiance multiplies *downstream* of
it (`74` §3, `78` §4 — the same fact `78` records as its ±3–4% approximation).
A chroma operator there widens the chroma of the **albedo**. A grey wall under
a red neon sign has a grey albedo, so it stays grey — the exact opposite of
this feature. Doubling the strength does not fix it; it is a wrong-quantity
bug, not an amplitude bug.

The chroma must be read **after** the radiance multiply. The only point past
it that is per-channel identified is each module's **final radiance triple**,
the last per-channel value before the write's fp16 clamp / output encode.
That is where all four splices go.

This also kills option (a) of the brief (extend the class-1 radiance injection
to non-skin) twice over: `c1` is a **scalar** with no chroma to give, and the
`78` skin path carries a **fixed red-shift triple** — painting that on walls
just reddens the world, which is not the goal. Environment chroma has to come
from the incoming radiance's own chroma, and only the write triple has it.

## 2. The operator

Per channel, on the site's own RGB triple `C`, with `q = env_chroma`:

```
Y     = 0.2126·C_R + 0.7152·C_G + 0.0722·C_B      (Rec.709)
r_c   = C_c / max(Y, ε)                           (scale-invariant ratio)
g_c   = (1 − q) + q·r_c                           (the widening gain)
n     = Σ_j w_j·r_j·g_j                           (luma of the widened triple)
out_c = C_c · clamp(g_c / max(n, ε), 0, GMAX)     GMAX = 16, ε = 1e-30
```

Properties, all **by construction**, which is the whole argument for shipping
it without an amplitude calibration:

- **`Σ_c w_c·out_c == Y` exactly.** `n` is precisely the factor the luma grew
  by; dividing by it takes it back out. Zero energy drift. There is no
  brightness to get wrong at any `q`.
- **Non-negative** for `q ∈ [0,1]`, `C ≥ 0`: `g_c ≥ 1−q ≥ 0`, and `n ≥ 1` by
  Jensen (since `Σ_c w_c·r_c == 1`), so the divide needs no rescue.
- **Homogeneous of degree 1** — commutes with the SP pair's flat `c1` factor,
  with exposure, and with any uniform scale downstream. Splice order against
  those cannot matter.
- **Cannot invent a hue.** Every channel is scaled by a positive scalar, so
  channel order is preserved and a zero channel stays zero.
- **Grey in, grey out** (`r_c == 1 ⇒ g_c == 1 ⇒ n == 1`).
- **Self-limiting.** The gain is affine in the ratio: a near-neutral pixel
  gets ≈`(1+q)`× its chroma, an already-vivid one moves ~10% (§5).
- **`GMAX` provably never binds:** `g_c/n ≤ 1/w_c ≤ 13.86 < 16` on any
  non-negative colour. It is a NaN/Inf fence, not a look knob.

## 3. The gate

```
gate = (class != 1) && (class != 4)
```

read off **each module's own material `OpSwitch` class word** — the same word
the skin path reads, found structurally per module, never a copied id.
Gate-false takes the `OpSelect`'s original operand, so it is the module's
original value **bit-for-bit**, not an arithmetic no-op.

- **class 1 = skin.** Excluded because skin already has its own tuned bleed
  (`78`); applying both would double-apply chroma on faces. Skin pixels are
  bit-identical to the base — that is an enforced check, not a hope (§6).
- **class 4 = hair.** Excluded for the same reason the cloth sheen excludes
  it (`81` §2): the hair path is tuned separately and a chroma widen on
  strand highlights is not what anyone asked for.
- **Metals and glass need no gate.** This is the *diffuse* GI raygen family.
  A metal's diffuse GI term is `albedo·(1−metal) ≈ 0`, and the operator maps
  `0 → 0` **exactly** (every output is `C_c ×` a finite scalar). Glass is a
  different raygen family entirely (`50` §4 — these four write only the GI
  diffuse image). Neither can pick up chroma from this splice.
- **No feedback.** The ReSTIR reservoir is a separate SSBO at `registers[5]`,
  written *above* the splice; the widened chroma reaches the output image
  only. It cannot compound frame-over-frame.

## 4. The sites — 4, two shapes, two wirings

All four diffuse raygens have **exactly one live radiance write**, dominated
by their own class switch. dxil-spirv emitted them in two shapes:

| module | family | shape | wiring | instr added |
|---|---|---|---|---|
| `006ba4e3c8c05205` | spatiotemporal | `rgb` | texel rebuild | +48 |
| `038867e9a3bf0626` | spatiotemporal | `ycocg` | `replace_all_uses` | +47 |
| `5e1e98e44d854712` | spatial | `rgb` | texel rebuild | +48 |
| `fc60b8a0b56529b8` | spatial | `ycocg` | `replace_all_uses` | +47 |

- **`rgb`**: each component is an fp16 clamp pair `NMin(NMax(x, −65504), 65504)`
  and the `v4` texel is built on the line above the write. The splice peels
  the clamp, widens, **re-clamps inside the gate-true arm**, and rebuilds the
  texel — alpha carried through untouched (`GOTCHAS` #11: alpha at these
  writes is a hit distance, not a weight). The rebuild wiring exists because
  the c1 chain interleaves the three channels' definitions, so no single line
  sits below all three defs and above all three uses; `replace_all_uses` on
  this shape dies with *"used above the insertion point"*, correctly.
- **`ycocg`**: the write is `select(YCoCg(RGB), RGB)` over **one** RGB triple.
  Roles are pinned structurally by the weight rows — `Y = (0.25, 0.5, 0.25)`,
  `Co = (0.5, 0, −0.5)`, `Cg = (−0.25, 0.5, −0.25)` — and it is the **Co row's
  asymmetry that pins R against B** (`GOTCHAS` "never guess a channel"). The
  detector requires all three roles over the same id set, requires every
  passthrough arm to equal the encode source member-for-member, enumerates
  every use, and fails if `replace_all_uses` rewrites fewer than it counted.

Detection runs **before** any emission, in a fresh process against fully
written bytes (`GOTCHAS` #12).

## 5. Calibration — `dev/env_chroma_model.py`

Saturation `(max−min)/max` of the write triple (albedo × incoming radiance),
before → after:

| scene | q=0.25 | **q=0.35** (`-envbleed`) | q=0.50 | **q=0.70** (`-envbleedhi`) | q=1.00 |
|---|---|---|---|---|---|
| magenta neon on concrete | 0.858→0.917 | **→0.931** | →0.948 | **→0.964** | →0.980 |
| cyan neon on concrete | 0.778→0.830 | **→0.849** | →0.876 | **→0.908** | →0.951 |
| sodium street on asphalt | 0.600→0.674 | **→0.701** | →0.738 | **→0.782** | →0.840 |
| white bounce on red wall | 0.771→0.850 | **→0.871** | →0.896 | **→0.921** | →0.948 |
| near-neutral daylight | 0.067→0.083 | **→0.089** | →0.099 | **→0.111** | →0.129 |

Read the shape, not the rows: a **near-neutral** pixel's chroma is multiplied
by ≈`1+q` (×1.34 at q=0.35, ×1.66 at q=0.70) while an **already-vivid** one
moves ~9–12%. The effect lands where it is supposed to — dim, low-chroma
surfaces near a coloured source — and self-limits where the frame is already
saturated. `q = 1.0` is the non-negativity ceiling and one command away (§9).

Worst-case per-channel amplification over 200k random colours: **1.6723** at
q=0.35, **2.0808** at q=0.70 — both far under `GMAX = 16`, and both matched to
3 decimals by the independent measurement on the **shipped bytes** (§6).

## 6. Verification — every number

Build coverage is **fail-hard** (`dev/build_gi_env.sh`); the build refuses to
emit unless every one of these holds:

    env coverage: 4 modules, 4 sites, shapes {'rgb': 2, 'ycocg': 2}, q=0.35,
    gate class!=1 && class!=4 off the module's own class switch
    gi-50bnd-env35 vs gi-50bnd: 4 of 16 raygens differ (the restirgi diffuse
    four); ref 12/12 and compute 77/77 byte-identical
    spirv-val clean on all 93 modules

| check | result |
|---|---|
| **`q = 0` rebuild vs the base `gi-50bnd`** | **93 of 93 modules byte-identical** — the gate-false path is byte-inert, not merely arithmetically inert |
| coverage gate, both rungs | 4 modules, 4 sites, `{rgb: 2, ycocg: 2}`, channels `[0,1,2]` in every module, all modules agree on `q` |
| `spirv-val` on every emitted module | **0 failures** — 93 × (env35, env70, envbleed, envbleedhi) |
| env base vs `gi-50bnd` | exactly **4 of 16 raygens differ**, ref **12/12** and compute **77/77** byte-identical |
| full rung vs standing `-clothhi` | compute **0/77 differ**, ref **0/12 differ**, raygens **4/16 differ** (`006ba4e3…`, `038867e9…`, `5e1e98e4…`, `fc60b8a0…`) |
| rebuild determinism | re-running the q=0.35 build: **0 of 93** modules differ from the parked copy |
| `dev/verify_env_chroma.py` on **shipped bytes**, `-envbleed` | 4/4 sites, **24 000 evaluated points**, luma err ≤ **2.77e-07** (need < 1e-5), closed-form err **0.00e+00**, max gain 1.672, ALL CHECKS PASS |
| same, `-envbleedhi` | 4/4 sites, 24 000 points, luma err ≤ **2.86e-07**, closed-form err **0.00e+00**, max gain 2.080, ALL CHECKS PASS |
| **gate-false leg, both rungs** | **36 000 bit-exact float32 identity checks each** (compared through `struct.pack`, via the emitted `OpSelect` itself, not its operand) |
| both write shapes executed | yes — 2 `rgb` and 2 `ycocg` per rung, the YCoCg pair decoded through the Co-row structural pin |
| model vs shipped max gain | 1.6723 / 2.0808 (model) vs 1.672 / 2.080 (interpreted from the real modules) |
| negative control: verifier on `-clothhi` | **0 sites**, 2 coverage failures, exit 1 — as intended |
| `dev/verify_bleed_norm.py` on shipped bytes, both new rungs **and** `-clothhi` | **150 luminance-hold sites / 77 modules** each, constants exact, channel wiring proven, closed form matched at 120 points per site |
| `dev/verify_cloth_sheen.py --k 1.0`, all three rungs | 457 cloth sites / 173 damp chains / 8696 points, **ALL CHECKS PASS** |
| `dev/verify_gi_ladder.sh --gi gi-50bnd` on the standing `-deep`/`-cloth`/`-clothhi` ladder | **ALL CHECKS PASS** (regression: the standing rungs are untouched) |
| `dev/verify_gi_ladder.sh` per new rung vs its own env base | **0 of 16 raygens differ**, `gi_refuse` provenance `src_ser=ser.set/class` **OK** |
| `make check` | ok |

The verifier re-parses the **shipped `.spv`**: it disassembles from
`skin.set/`, finds the gate structurally (one `OpLogicalAnd` of two
`OpINotEqual` against `{1, 4}` off a single value), identifies the three
gated channels from the *write* (texel positions for `rgb`, the union of
weight-row roles for `ycocg`), cross-checks each channel against the luma
weight it is multiplied by, checks the baked constants, then **interprets the
emitted instructions** against the closed form at 3000 colours × {f32, f64} ×
{gate true, gate false} per module. Every parsed constant is rounded to f32
first — `spirv-dis` prints decimal text, and parsing it as f64 leaves a ~1e-9
error that masquerades as a wiring bug.

## 7. A/B runbook — settings contract FIRST (the `45` rule)

### Required game settings, stated before the launch, never inferred after

**PT Overdrive on · PT-in-photo-mode on · RR OFF (`DLSS_D: false`) · DLSS
Balanced · RayTracedLighting Psycho · 2560×1440.**

**RR must be OFF.** Ray Reconstruction replaces the denoiser and will
redistribute chroma itself; with RR on this A/B measures nothing.

> **The live `UserSettings.json` has drifted before.** A parallel agent
> observed `DLSS_D: true` on 2026-09-01. This document's own read, at
> 2026-09-01 02:31, shows `"value": false`. Neither reading survives the game
> rewriting the file on exit, so **check it immediately before the launch**:
>
>     grep -A2 '"name": "DLSS_D"' "/home/blane/.wine/drive_c/users/blane/AppData/Local/CD Projekt Red/Cyberpunk 2077/UserSettings.json"
>
> If it reads `true`, flip it off in the graphics menu (or edit and relaunch)
> **before** either half of the A/B, and use the same value for both halves.

### Serve it

The shader payload is already parked in `~/.local/lib/callisto/skin.set/`.
Only the two CET dropdown rows need deploying, and **the user runs this, not
an agent**:

    cd "/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/CallistoSSS"
    make install          # copies init.lua into release/ and the game dir

Then select the rung — the CallistoSSS CET tab, or hand-edit the live params
file (`<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt`,
game dir `/mnt/f4333173-.../SteamLibrary/steamapps/common/Cyberpunk 2077`).
This is the live file with **one line changed**:

    tier=on  kernel=spectral  skin=on  shadowcull=on  shadowset=full-shadow
    skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-envbleed
    ser=class  ptreg=on  ptclamp=on  ptbounce=on  ptrefl=on  ptmsggx=on
    refract=eta15

`ser=class` + `shadowset=full-shadow` are the `gi_refuse` provenance contract
(`src_ser=ser.set/class`, `ser_sha=310513f3008cbde4`,
`ptq_sha=55ed4e5c6884ab71`); the new rungs carry the base's manifest verbatim,
so a wrong `ser` refuses the rung loudly rather than serving vanilla quietly.

### Scene — this is what decides whether the launch is worth anything

- **A coloured light source washing a neutral surface**, both in frame:
  neon signage onto concrete/plaster, a sodium street lamp onto asphalt, a
  red/blue interior spill onto a grey wall. That is the claim; shoot the
  claim.
- **A neutral control surface far from any coloured source in the same
  frame** — it must not shift. And **a coloured object under white light**
  (§8's confound) so the two effects can be told apart *in one screenshot*.
- **A face in frame.** Skin is gated out and must look identical. This is the
  cheapest visible falsifier the build has.
- **Pin the camera** (photo mode, do not move between halves) and shoot the
  identical frame on `-clothhi` as the control. `58` §5's gap was shooting the
  effect without a control surface; `81` §10's gap was no pinned frame. Do not
  repeat either.

Ladder, one variable per step:

1. `-envbleed` (q=0.35) vs `-clothhi`, same camera.
2. Only if 1 is ambiguous: `-envbleedhi` (q=0.70). Doubling `q` roughly
   doubles the chroma lift on near-neutral pixels. If `-envbleedhi` is also
   invisible, the sites are wrong, not the amplitude.

## 8. Pre-registered outcomes

| observation | reading |
|---|---|
| neon-lit walls/floors carry the light's colour, neutral areas unchanged | the feature, working — keep `-envbleed`, try `-envbleedhi` for taste |
| **"everything got more colourful", including objects under white light** | **the pre-registered confound (risk (c)): a coloured ALBEDO is widened too.** The operator sees only the product `albedo × radiance` and cannot tell which factor carried the chroma — a red couch under white light saturates exactly like a grey couch under red light. This is inherent to the site, not a bug, and no `q` separates them. If the user dislikes it, the fix is a *different* mechanism (needs a per-pixel albedo readback at the raygen, which these modules do not have), not a retune |
| the scene reads brighter or dimmer at either `q` | **bug** — luminance is held exactly and was verified at 24 000 points. A brightness change means the splice is not where the verifier thinks it is. Kill the rung and file it |
| skin/faces look different | **bug** — class 1 is gated out and gate-false is bit-exact. A skin delta means the class read is wrong. Kill the rung |
| hair looks different | same, for class 4 |
| metal or glass shifts colour | **surprising, not fatal** — §3 argues these terms are ≈0 in this raygen family. Report the surface; it would mean the GI diffuse image reaches them through a path `50` §4 did not record |
| hue *rotates* (red bounce reads orange/pink) | **bug** — the operator preserves channel order and cannot invent a hue. Would mean a channel is mis-wired, which the verifier's weight cross-check should have caught. Kill and file |
| fireflies / colour speckle in dim indirect areas | plausible and expected-ish: chroma noise in the reservoir gets widened along with the signal. Try `-envbleed` if seen on `-envbleedhi`; if present at 0.35 too, the term is amplifying denoiser noise and needs a luma-dependent falloff |
| nothing anywhere, at either `q` | wrong sites — check the serve actually happened (`./dev/ab_launch_audit.py`) before concluding anything about the mechanism |

## 9. Rebuild / retune

    ./dev/build_gi_env.sh --from gi-50bnd --q 0.35 --install     # env base
    ./dev/build_gi_bleed_sheen.sh --install --gi gi-50bnd-env35 \
        --parent real-gloss-bleedn-oilh-deep \
        --name gi-50b-bleed-oil-sheen-deep-clothhi-envbleed --set k_cloth=1.0

Same two commands with `--q 0.70`, `gi-50bnd-env70` and `…-envbleedhi` for
the loud half. `--q 1.0` is the ceiling (non-negativity); above 1.0 the gain
`(1−q) + q·r` goes negative on channels below the luma and the patcher will
happily emit it — do not.

`--q 0` rebuilds the base byte-for-byte; that is the inertness test, and it
should be re-run whenever the patcher is touched:

    ./dev/build_gi_env.sh --from gi-50bnd --q 0 --name gi-50bnd-env00

To rebase on a different standing rung, point `--from` at its parked gi base
and `--parent`/`--set` at its compute half; the patcher is base-agnostic and
asserts its own coverage either way.

## 10. Files

- `dev/patch_gi_env.py` — **new**, the second-pass patcher. Detect-then-emit,
  both write shapes, both wirings, allow-listed use enumeration, dies rather
  than guessing.
- `dev/build_gi_env.sh` — **new**. Runs the patcher over a parked gi base's 4
  diffuse raygens, copies the other 89 modules verbatim and asserts they are
  verbatim, asserts the raygen delta is exactly the 4, `spirv-val`s all 93,
  and carries the provenance line forward.
- `dev/verify_env_chroma.py` — **new**, shipped-bytes verifier: structural
  gate/channel identification, constant check, and an instruction-level
  interpreter run against the closed form.
- `dev/env_chroma_model.py` — **new**, the offline amplitude model of §5.
- `init.lua` — two selector rows added after `-clothhi` (source copy only;
  `make install` deliberately not run — §7).
- Nothing else was touched. `dev/patch_gi_c1.py`, `dev/patch_subtype_probe.py`
  and `dev/build_gi_bleed_sheen.sh` are unmodified; the standing rungs' bytes
  are unmodified and re-verified (§6).

## 11. What this document is not

It is not evidence that the feature looks good. Every number here is offline:
the operator holds luminance, the gate excludes what it claims to exclude, the
bytes are one variable off the standing rung. **Whether Night City's neon
reaching the walls is an improvement is a look-call that only a pinned-frame
A/B at `-clothhi` can make** — and §8's confound means the first question to
ask of any positive read is *"is that the bounce, or is it every coloured
surface in the frame?"*
