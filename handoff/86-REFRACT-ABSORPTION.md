# 86 — Coloured transmission: Beer–Lambert on the refracted segment

Written 2026-09-01. Built, verified offline, parked. **NOT installed, not
launched, not on screen.** Builds on `76` (Phase 0.5 glass refraction, KEPT,
live selection `refract=eta15`) and answers `20` §5b's absorption half.

> **Nothing here is on screen. Nothing in this document is a result.** Three
> rungs are parked in the repo; until a one-variable A/B has been run and
> adjudicated by eye, every claim below is an offline claim about bytes and
> arithmetic, not about pixels. `76` earned its verdict from a launch; this
> has not had one.

---

## 0. Read this first: σ is GLOBAL, and it has to be

The obvious design — *derive σ per channel from the glass surface's own albedo,
so red visors redden and green bottles green with zero new data plumbing* — is
**dead on contact with the disassembly** (`50` §3's lesson, again).

`ee6d252e090adc74.rgs_reflection_transparent_main` makes **exactly three**
G-buffer reads in 3084 lines:

| what | where | used as |
|---|---|---|
| depth | `OpImageFetch`, `registers[1]+1`, `.x` (`%120→%122`) | gate test, world-pos rebuild |
| normal | `OpImageRead`, `registers[5]`, `.xyz` (`%129→%131-133`) | N for the bend |
| transparent gate | `OpImageFetch`, `registers[2]+14`, `.x` (`%140→%142`) | the pass's own gate, and the written alpha |

There is **no material fetch of any kind** — no base colour, no UV, no
instance/material CB, no bindless material index. The only RGB triples that
exist anywhere in the module are

- the CHS payload's albedo (`%350/%352/%353`) — that is the surface **behind**
  the glass, i.e. exactly the thing we are tinting, so using it would tint
  every object by its own colour;
- the env cubemap sample (`%315`); and
- the SSR scene-colour sample (`registers[1]+6`, `%719`), read at the
  **reprojected** hit uv. Sampling it at the pixel's own uv to recover the
  raster glass tint is the only per-pixel chroma in reach and it is a feedback
  loop on a buffer this very pass writes into. Not doing that.

So: **one global glass hue, for every pane in the game.** That is less of a
limitation than it sounds, because *real glass is one hue*: the green-cyan edge
tint of soda-lime float glass is a property of the iron in the melt, not of the
asset. What is lost is authored tint — a red visor stays a red visor in the
raster layer and gets the same green-cyan transmission as a window. Say that
out loud rather than re-chasing it.

## 1. σ_rgb — the physics, and the one authoring choice

**Reference spectrum: standard soda-lime "clear float" glass.** Anchored on the
published 6 mm figure — visible transmittance ≈ 0.89 including both Fresnel
interfaces (≈ 0.918), so **internal** transmittance over 6 mm ≈ 0.970 — and
split across RGB by the two iron bands that make the edge green: Fe²⁺ absorbs
in the red (its 1050 nm band tails into the visible), Fe³⁺ in the blue/violet,
green passes. Hence **σ_R > σ_B > σ_G**.

    sigma_ref            = (9.80, 3.63, 7.31) 1/m
    attenuation length   = ( 102,  275,  137) mm      <- 1/sigma, real glass
    internal T( 6 mm)    = (0.9429, 0.9785, 0.9571)   Rec.709 luma 0.9694
    internal T(10 mm)    = (0.9066, 0.9644, 0.9295)   Rec.709 luma 0.9496
    hue ratio R:G:B      = 2.700 : 1.000 : 2.014

**The one authoring choice, stated as a number.** The mod's `d` is *not* pane
thickness — it is the traced distance **behind** the interface (§2). At true
float-glass magnitude the medium saturates in ~0.3 m and every window in Night
City would read black. So the rungs keep the hue ratio **exactly** and rescale
the magnitude, quoted honestly as *millimetres of real float glass absorbed per
metre of traced path*:

| rung | mm glass / m | σ_rgb (1/m) | 1/σ (m) | T at 10 m | luma at 10 m |
|---|---|---|---|---|---|
| `-absorb`, `-absorbp` | 4.50 | 0.04410 / 0.01634 / 0.03289 | 22.7 / 61.2 / 30.4 | 0.643 / 0.849 / 0.720 | 0.796 |
| `-absorbhi` | 11.25 | 0.11025 / 0.04084 / 0.08224 | 9.1 / 24.5 / 12.2 | 0.332 / 0.665 / 0.439 | 0.578 |

`-absorb` is "one windowpane of absorption per metre of view distance".
`-absorbhi` is 2.5× that — the `eta20` of this ladder: built to *find* the
effect, not to be correct.

`d_max = 40 m` on both: the medium ends there and no further absorption
accrues. Without it the luma-held rungs saturate to pure glass hue on any
distant backdrop.

## 2. Mechanism

**d.** `%267 = OpLoad %float %250` — payload member 3, one instruction after
the trace. In the eta15 build this is the **refracted** ray's hit distance,
because Phase 0.5 rewrote the trace's direction operand (`%266 ← %2913-2915`,
`76` §1). It is proven to be a length by its own vanilla uses: hit-position
rebuild `%394-396 = %267·dir` (+origin), the 0..1 fade `%403 = t·0.001`, the
`sqrt(t)` normal offset `%414-417`, the miss sentinel `%267 == 10000` (`%268`),
and the re-store into payload `%56` member 3 at `%453`. The direction is unit
(`patch_refract.py` asserts `|T| = 1` every build), so `t` is in world metres.

**It is the segment behind the interface, not the thickness of the pane.**
There is one bend and no exit interface (`20` §5b, unchanged). Physically the
rungs treat the glass as a semi-infinite tinted medium that everything behind
it sits inside. That is why the magnitude had to be rescaled (§1) and it is the
honest description of what the picture will show: *far things through glass get
more tinted than near things*. A visor 5 cm from a face will tint almost
nothing.

**The site, and why there is exactly one.** The radiance triple exists as a
single named value in exactly one place: the phis `%273/%275/%277` at the top
of block `%2827`, which merges the env-miss arm (`%2826`) with the hit arm
after aerial-perspective fog (`%2825`). `%267` is defined in `%2769`, which
dominates `%2827`. It does **not** dominate `%2830` — the block holding the
×1/64 encode and the ±65504 fp16 clamp — so `20` §6's "splice before the clamp"
site is unreachable to anything consuming `t`. `%2827` is upstream of both
anyway, so the module's own clamp still bounds the result (GOTCHAS: *scale
before a clamp*).

**The splice** (17 instructions physical, 33 luma-held; all straight-line, no
new blocks, no new globals, SPIR-V 1.4 interface list untouched):

    d      = OpSelect(miss, 0, NMin(t, d_max))          ; miss arm kept finite
    T_c    = exp(-sigma_c * d)                for c in RGB
    a_c    = radiance_c * T_c
    -- luma-held rungs only:
    L0     = dot(Rec709, radiance) ; L1 = dot(Rec709, a)
    s      = NClamp(L0 / NMax(L1, 1e-9), 0, s_max)
    a_c    = a_c * s
    out_c  = OpSelect(miss, radiance_c, a_c)            ; BIT-EXACT identity

Then all **6** downstream uses of `%273/%275/%277` on **4** lines are rewritten
to the three `OpSelect` results: the volume-probe magnitude `%710`, and the
three `frontier_phi_2_5_ladder*` phis at `%2829`. Defs left in place.

**Two miss guards, and only the second one is load-bearing.** The inner
`OpSelect` sets `d = 0` so the dead arm carries no `exp(-σ·10000)` and no `0/0`
in the luma divide. The **outer** `OpSelect` is what makes a miss bit-exact
identity, and it deliberately does not rely on `exp(-0) == 1.0`: GLSL.std.450
`Exp` carries a ULP tolerance and a driver returning `0.99999994` would
otherwise tint the sky. Sky through glass is byte-for-byte the `eta15` picture.

**`s_max` is a no-op by construction.** For non-negative radiance
`L0/L1 ≤ 1/min_c T(d_max) = exp(max σ · d_max)` — 5.84 for `-absorb`, 82.27 for
`-absorbhi` — and the constant is set to that bound ×1.0000001. It only fires
on negative radiance, which the fog lerp could in principle produce. The build
**fails** if the clamp binds on any non-negative sample (§4).

## 3. The composite contract — GOTCHAS rule 11, addressed

`20` §5b's warning is the thing that killed the two-ray combine, so it was
answered before anything was written. **The consumer of this buffer is still
unnamed** (`20` open item 1, still open in `19` §235 and `76` §0) and this
session did not close it. Three facts settle the question anyway.

**(i) The output UAV *is* the input.** The surface normal is `OpImageRead` from
bindless index `registers[5]` (`%124-129`, image type `%38` = `OpTypeImage
%float 2D 0 0 0 2 Unknown`, a storage image) and the radiance is
`OpImageWrite`n to **the same variable `%41`, the same index `registers[5]`,
the same texel `(%90,%92)`** (`%290-295`, `:3082`). This pass reads a
transparent-layer normal and **overwrites it in place** with its own result. It
is a dedicated transparent-RT scratch target; the pass does not accumulate into
a shared radiance buffer, so a multiply here scales exactly one term, exactly
once. (The two `rgs_reflection_opaque_main` siblings do **not** do this — they
fetch normals from `registers[1..3]`. The aliasing is specific to this module.)

**(ii) The ×1/64 is a shared encode.** All three reflection raygens write
`RGB · 0.015625`, so the consumer decodes ×64. Constant factor, cancels.

**(iii) Absorption cannot ghost, and that is the whole point.** `20` §5b feared
`F·refl + (1−F)·refr`: *adding a second image*, which over an already
alpha-blended glass pixel gives a doubled edge. Absorption adds nothing. It is
a multiply by `T ∈ (0,1]³` of the one term this pass already owns, so under
**add, lerp or replace alike** it is monotone in σ and bounded above by the σ=0
frame. It cannot ghost, cannot go negative, cannot exceed today's picture. The
composite does not gate it.

**What the composite *does* gate is the look, and this is the honest ceiling.**
If the consumer adds this buffer over the raster alpha-blended see-through,
then the see-through — the thing the brief wants tinted — is the raster layer,
which this module cannot reach. The tint lands on the RT-traced **bent overlay
only**. There is no multiplicative double-tint on the same photons (two layers,
each tinted once), but the overlay will read as more saturated than the raster
glass beside it. **"Tinted visors tint what you see through them" is only
partly deliverable from this site**, and if the A/B reads as "the sparkle went
green but the window didn't", that is this, not a bug.

**Why luma-held is the recommended rung.** Because the consumer is unnamed
*and* the see-through is unreachable, we cannot predict what fraction of a glass
pixel physical absorption is darkening — `-absorbp` at 10 m removes 20% of the
term's luma and at 40 m removes 57%. The `-lumn` rail (`78`) bounds that to
zero by construction: Rec.709 luma is held to <2.6e-7 relative and only hue
moves with distance. Physical stays parked as `-absorbp` so the comparison is
available rather than argued about.

## 4. Verification — all of it on the shipped bytes

`./dev/build_refract_absorb.sh` fails the build on any row below.

| # | check | result |
|---|---|---|
| 1 | **negative control**: patcher run on `swaps.refract.off` and on vanilla `swaps.ptrefl` | **dies, 0 sites** — it anchors on Phase 0.5's `%float_refr_eta` marker, so it cannot patch a non-refracted base |
| 2 | **σ=0 rebuild byte-identical to `eta15`**, both modes | **PASS** — `cmp` equal. Guards the GOTCHAS trap "48 bytes of `OpConstant` nothing consumes": at knob 0 the patcher emits *no* constants, *no* body, *no* rewrites |
| 3 | site coverage, enforced per rung | anchors 5×1, **6 uses rewritten on 4 lines** (asserted `== 6` or the build dies), and the four vanilla consumer strings are absent from every rung's `.spvasm` |
| 4 | miss-identity guard present | exactly **3** `OpSelect %float %268 %27{3,5,7}` per rung |
| 5 | `spirv-as --target-env spv1.4` + `spirv-val` | clean, 3 rungs × (asm + val) + 2 σ=0 rebuilds |
| 6 | **closed-form execution check, 6000 points/rung** (>5k required) | max relative error **3.4e-07** (luma), **0.00e+00** (physical, exact) vs an independently written float32 closed form, over t ∈ [0, 12000] incl. the sentinel, radiance 1e-3..1e3 incl. zeros and negatives |
| 7 | **miss ⇒ bit-exact identity**, enforced as `==` not a tolerance | 1500 miss samples per rung, **bit-equal** |
| 8 | **luma held** (`-absorb`, `-absorbhi`) | max relative luma error **2.28e-07 / 2.56e-07**, threshold 1e-5 |
| 9 | `s_max` clamp is a no-op for representable input | **0 binds** on non-negative samples (build fails on any) |
| 10 | rungs differ from base and from each other | `cmp` all pairs |
| 11 | **standing rungs untouched** | `off ac2cd8f7d550fe93`, `eta15 8c88926a273ae541`, `eta20 c96eaef809c8a734` — byte-identical to the shas `76` §2 recorded |
| 12 | hand-read of the emitted block | done: the 33 inserted instructions (17 physical), the 9 constants and all 4 rewritten consumers read correctly against §2 |

Not checked, and not checkable offline: whether any of it reaches a pixel.

### Parked

| level | sha16 | what |
|---|---|---|
| `eta15-absorb` | `e9c54662f5d6701b` | luma-held chroma-only, 4.50 mm/m — **the recommended rung** |
| `eta15-absorbhi` | `021b4af29ecf957f` | luma-held chroma-only, 11.25 mm/m — for finding the effect |
| `eta15-absorbp` | `3f5f3e7b279e8426` | physical Beer–Lambert, 4.50 mm/m — the honest reference |

## 5. Serve and install — exact commands

**Do not run `make install` from this document without checking who else is
mid-deploy** (parallel-agent race; this session deliberately did not run it).

```bash
# 1. deploy the repo (only if the installed tree is stale -- 45 §1 cmp first)
make install

# 2. park the three rungs beside the existing refract ladder
./dev/build_refract_absorb.sh --install     # -> ~/.local/lib/callisto/refract.set/

# 3. select one. sync_settings.sh's refract block takes ANY refract.set/<level>
#    by name (it only special-cases "off"), so no CET/init.lua change is needed:
sed -i 's/^refract=.*/refract=eta15-absorb/' \
  "<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt"
```

The CET selector still lists only `off/eta15/eta20`; it will read
*"Glass refraction experiment: eta20"* or similar while `brdf_params.txt` says
`eta15-absorb`. **That is the `27` §8 / "one knob, two defaults" trap in
miniature** — trust `status.txt`'s `want_refract` / `req_refract` and the
journal's MANIFEST echo (`ptrefl refract=eta15-absorb … sha=e9c5…`), not the
selector, until someone adds the three levels to `init.lua`.

Confirm the serve before believing anything:

```bash
grep -E 'want_refract|req_refract|last_refl' ~/.local/lib/callisto/status.txt
sha256sum ~/.local/lib/callisto/swaps.ptrefl/ee6d252e090adc74.*.spv | cut -c1-16
tail -5 ~/callisto_launches.log
```

Rebuild without installing: `./dev/build_refract_absorb.sh` (no flag).

## 6. A/B protocol — one variable, one launch

**Required game settings, stated up front (`45`, memory rule) — state them
again in the message that reports the result:**

- Path tracing: **RT Overdrive ON**
- `tier=on`, `ptrefl=on` (the rung *rides* the ptrefl overlay; sync refuses as
  `off:needs-ptrefl` if either is off, and then the picture is vanilla glass)
- `refract=eta15-absorbhi` **first** — find the effect before judging it
- Ray Reconstruction: record its state (`DLSS_D` in `UserSettings.json`) before
  and after; `79` exists because nobody did

**Scene:** a large window at night with lit interior/exterior geometry **well
behind the pane** (10-40 m — the effect is zero at zero distance by
construction), camera oblique to the glass. The bar glassware from `76` is a
poor test here: everything behind it is centimetres away.

**The control is `refract=eta15`, not `off`.** One variable. `off` changes the
bend *and* the absorption at once and adjudicates nothing.

Pre-registered outcomes:

- **PASS** — through-glass content picks up a green-cyan cast that **grows with
  distance**, near objects behind the pane essentially unchanged, sky through
  the glass identical to `eta15`. Then step down to `-absorb`, then compare
  `-absorb` against `-absorbp` for whether the energy loss is wanted.
- **TINT ON THE OVERLAY ONLY** — the bent/lensed highlight goes green while the
  straight-through view does not. **This is §3's predicted ceiling, not a bug.**
  Record it and stop; the fix is naming the consumer (`20` open item 1), not
  tuning σ.
- **NO CHANGE at `-absorbhi`** — check `status.txt` `last_refl` and the journal
  MANIFEST echo first. Served and traced but identical ⇒ either the transparent
  pass does not run on that glass (`20` §6 FAIL branch) or its contribution is
  a negligible fraction of the composited pixel.
- **Glass goes dark/black** — `d_max` or σ too large for that scene's depth
  range; report the scene and the distance, do not tune blind.
- **Sky through glass changed** — the miss guard failed. That is a falsification
  of check 7 on real hardware; report it immediately, it means `OpSelect` on
  `%268` is not doing what the offline model says.

**Nothing in this document is on screen until that A/B says so.**
