# 48 — The bounce-lit skin writer is a RAYGEN, and the anchor hunt misses it because of a `glob`

Static only. No launch, no commit. Written 2026-08-30 to close
`CURRENT.md` "Still unlaunched" item 1 / `46` §6.1 hypothesis (b).

**Verdict.** Bounce-lit skin radiance is not written by any compute module.
It is written in the **ray-generation stage**, by two families that the skin
patcher has never touched:

| rank | family | hashes | what it writes | why the anchor missed it |
|---|---|---|---|---|
| 1a | `rgs_restirgi_spatiotemporal` / `_spatial`, **diffuse** variants | `006ba4e3c8c05205` `038867e9a3bf0626` `5e1e98e44d854712` `fc60b8a0b56529b8` | indirect **diffuse** irradiance, albedo-demodulated, `registers[5]+1` | two ways: not `*.dxil.spv`, **and** it is Lambert+GGX with no Disney retro constant |
| 1b | `rgs_reference_main` ×12 | `d622fb9e1dcb8cd0` `d002cc05eb940591` `4270b745d11a5e8a` `40c6faab52a13874` `3d871a3170bc5815` `25b54fc4a17688df` `996a3b16253c3e7f` `852b31a841b85b26` `4103c8860c3909e4` `21a92f1a77eb4c22` `1271d3815051da17` `ab7f1822eeb0331b` | a 2-bounce path tracer's diffuse **and** specular radiance, `registers[5]`, `registers[5]+1` | it **carries the exact anchor pair**; `patch_compute_skin.sh` globs `*.dxil.spv` and never sees it |
| 2 | `rgs_restirgi_*`, **specular** variants | `1ca55ed0fc70d56f` `a3b07b0f4f4f79b8` `174dee89ec119981` `9d117caf3ef46c59` | indirect **specular** (GGX D·F·V·NoL × reservoir radiance), YCoCg | same as 1a |
| 3 | compute twins, **never dispatch in PT** | `715d349aa3787397` `cd7206ece6616e2c` | 2 float targets, same class switch and skin idiom as 1a | no Disney retro constant |

**The headline is not "a module was missed". It is that the anchor set is
narrow for a reason nobody wrote down: a filename glob.** 110 modules in the
dump carry the `(1/π, 0.107508637)` pair. `dev/patch_compute_skin.sh` line 118
globs `'/*.dxil.spv'`, which drops **26 of them** — 12 `rgs_reference_main`,
10 `rgs_shadow_main`, 2 `rgs_reflection_opaque_main`, 1
`rgs_reflection_transparent_main`, 1 `chs_main`. Every one of the 22 raygens
among those **writes float colour to a 2D image** and 22/26 **test the
material class against 1**. `00` §2's "84 GLCompute libs carry the full
material stack" is true and misleading: 110 modules do, and the other 26 are
where the indirect light is.

---

## 1. Reproducing every number here

Two new read-only scripts, ~3 s and ~4 s over all 3273 modules. They parse
the **binary** SPIR-V (operand layout from the Khronos grammar JSON), because
`grep -r` over the dump silently returns 0 for strings that are present
(`GOTCHAS`).

```bash
python3 dev/spv_census.py                  # stages, writes, anchor pair
python3 dev/spv_brdf_scan.py               # the narrowing chain + finalists
```

Neither writes anything outside its own stdout. Nothing under `dev/` that
ships was modified; `patch_compute_skin.py`, `patch_skin_brdf.py` and
`patch_subtype_probe.py` are untouched.

Disassembly line numbers below are from a fresh
`spirv-dis ~/callisto_dump/<file> | grep -n ...` and were checked to match the
committed copies in `dev/disasm/live/` and `dev/disasm/gi/` exactly.

## 2. The narrowing, with the pool size at every step

`python3 dev/spv_brdf_scan.py`:

| step | filter | left | split |
|---|---|---|---|
| 0 | every `.spv` in `~/callisto_dump` | **3273** | 1290 Fragment, 1179 Vertex, 675 GLCompute, 57 Miss, 43 RayGeneration, 24 ClosestHit, 5 AnyHit |
| 1 | `OpImageWrite` of a float vector into a float 2D image | **524** | 488 GLCompute, 36 RayGeneration |
| 2 | …and does **not** carry the `(1/π, 0.107508637)` pair | **419** | 406 GLCompute, 13 RayGeneration |
| 3 | …and does BRDF-shaped math (`Log2→×5→Exp2` Schlick pow5, or a multiply/divide by float32(π)) | **74** | 68 GLCompute, 6 RayGeneration |
| 4 | …and derives the material class (`>>5` of `OpCompositeExtract 1` of an `OpImageFetch %v4uint`) | **8** | 6 RayGeneration, 2 GLCompute |
| 5 | …and tests that class against **1** | **8** | unchanged — every class-reading candidate tests skin |
| 6 | …and has a dispatch/trace record in `~/callisto_swap.jsonl` | **4** | all RayGeneration |

Step 3 → 4 is where the compute pool dies: **68 unanchored compute
float-colour writers do BRDF-ish math and exactly 2 of them read the material
class byte**, and those 2 never dispatch. The compute answer does not exist in
this render mode.

Run separately, the glob-excluded set:

```
ANCHORED modules the *.dxil.spv glob excludes:  26
  12 rgs_reference_main  (col 2–6, cls1=1)
  10 rgs_shadow_main     (col 0–5, cls1=1)
   2 rgs_reflection_opaque_main + 1 rgs_reflection_transparent_main (cls1=0)
   1 55f6172c71799e4d.chs_main (col 0 — a hit shader, writes the payload; `06` stands)
```

### 2.1 Sanity checks that the census reproduces known facts

- **84** `.dxil.spv` carry the anchor pair. The 7 modules `42` §7 names as
  *"no material G-buffer read found"* (`3acf2ec0`, `57fa8971`, `d1a91e5e`,
  `e47009fb`, `ee2dda2c`, `f568c84d`, `f7a29100`) are all in the 84.
  **84 − 7 = 77.** The ladder's number reconciles.
- **76 of 77 write `v4float`, one writes `v4uint`** — `46` §12 reproduces.

## 3. New fact: `ab0bc2fee876d489` never runs

`46` §12 established that `ab0bc2fe` writes indices, not colour. The dispatch
journal adds a harder fact:

```bash
python3 - <<'PY'
import json, collections
c=collections.Counter()
for l in open('/home/blane/callisto_swap.jsonl'):
    if '"dispatch"' in l: c[json.loads(l)['id'].split('.')[0]] += 1
for k in ('ab0bc2fee876d489','99bb7c2698997b2a','743ab2734ff240ad','11c15299f77e54dc'):
    print(k, c.get(k,0))
PY
```
→ `ab0bc2fee876d489 0`. **It is not a reservoir pass that runs; it is a
module that is created, swapped, and never dispatched.** The tier-1 `c1`
spliced into it does nothing at all, not even perturb a weight. `46` §12's
"whether that is harmless is untested" is now answered: harmless.

More generally: **only 31 of the 84 anchored compute modules ever dispatch.**
30 of the 31 have `LocalSize 8 8 1`, write **two** float targets, and are
dispatched **indirectly** (groups `0xFFFFFFFF`) — the tile-classified
direct/local-light resolves of `00` §3. Exactly one has `LocalSize 32 16 1`,
writes **one** target, and dispatches with explicit groups `(40,45,1)` at
`32×16` = 1280×720: `99bb7c2698997b2a`, the resolver `42` chased.

## 4. Finalist 1a — the ReSTIR GI diffuse raygens

`006ba4e3c8c05205.rgs_restirgi_spatiotemporal` (17 369 words), and its three
siblings `038867e9`, `5e1e98e4`, `fc60b8a0`.

```bash
spirv-dis ~/callisto_dump/006ba4e3c8c05205.rgs_restirgi_spatiotemporal.spv > /tmp/gi.spvasm
```

| line | instruction | reading |
|---|---|---|
| 583 | `%308 = OpImageFetch %v4float` at `registers[1]+7` | G-buffer **albedo** |
| 603 | `%329 = OpCompositeExtract %float %327 0` | **metalness** |
| 736 | `%155 = OpShiftRightLogical %uint %467 %uint_5`, from `OpCompositeExtract 1` of an `OpImageFetch %v4uint` at `registers[2]+2` | **material class** |
| 753 | `OpSwitch %155 %2538 4 %2533 1 %2532` | class **4 → hair** arm, class **1 → skin** arm |
| 818–823 | `%758 = %329 < 0.1`; `%759 = %758 && <cvar>`; `%661/%663/%665 = OpSelect(%759, 1.0, albedo²)` | **skin diffuse demodulation** — on skin, albedo is replaced by white |
| 835 | `%149 = %660 − %666` = `albedo·(1−metal)` | diffuse albedo |
| 3043–3046 | `%1356 = 1/%148`, `%1359 = select(%148≤0, 0, %1356)` | **1 / diffuse albedo** |
| 3061–3067 | `%1375 = (radiance × 0.015625) × %1370` ×3 | radiance ÷ albedo — the **demodulated indirect diffuse** |
| 3079 | `OpImageWrite` to `registers[5]+1` | the GI diffuse denoiser input |

`%155` is defined at 736 and the block runs unbroken to the `OpSwitch` at
753, so it **dominates** the write at 3079. `find_class_shift` in
`patch_compute_skin.py` matches this shape exactly (`>>5` reached through an
`OpImageFetch`) — **no phi lift is needed here**, unlike `42`.

The specular siblings (`1ca55ed0`, `a3b07b0f`, `174dee89`, `9d117caf`)
have the same class switch and multiply the reservoir radiance by a full GGX
lobe — GGX `D` (`α²/(π·(…)²)`, `1ca55ed0` @3489–3514), Schlick `(1−c)^5`
Fresnel with per-channel F0 (`Log2 → ×5 → Exp2`, @3499–3507), Smith
height-correlated `V` (@3517–3528), `× NoL` (@3475–3477) — then write it in
**YCoCg** (`Y = dot(rgb, (.25,.5,.25))`, `Co = dot(rgb, (.5,0,−.5))`,
`Cg = dot(rgb, (−.25,.5,−.25))`, @3754–3763) plus hit distance at
`registers[5]+8`.

The four `rgs_restirgi_initial_temporal` write **no image at all** — pure
reservoir passes. That is the clean line: **initial_temporal = sampling;
spatial and spatiotemporal = shading.**

> **Correction to `00` §3.** The row *"`rgs_restirgi_*` | ReSTIR GI reservoirs
> | sampling only"* is wrong for 8 of the 12. It was inferred from the pass
> names (`GOTCHAS` method rule 9). The 8 `spatial`/`spatiotemporal` modules
> evaluate a BRDF against the reservoir radiance and write the result.
> `04` fact 4 and `23`'s note ("thin evals, 1/π, no Disney") described the
> constants correctly and drew the wrong conclusion from them: the missing
> Disney retro term means these passes use **Lambert + GGX**, not that they do
> no shading.

The one 1/π *multiply* in `1ca55ed0` (@1310, `%892 = dot(N,L) · 1/π`) really
is sampling — it feeds `%703 = 1/pdf`, the ReSTIR target-function reciprocal.
**Do not splice there.** That is the one place `00` §2's argument holds
literally. (`05` §111 reports "14 1/π sites" in this family; a fresh
`grep -c float_0_318309873` on `1ca55ed0` returns 2, one of them the
declaration. Not adjudicated — possibly a different permutation or a
different count.)

## 5. Finalist 1b — `rgs_reference_main`, and the one term bounce light rides

`d622fb9e1dcb8cd0.rgs_reference_main` (75 762 words). `24` §2 already
overturned `00` §2 and `06` for this module — *"in the current mode they do
dispatch, and the module writes the pass's two radiance images itself"* — but
nothing carried that into the skin work.

```bash
spirv-dis ~/callisto_dump/d622fb9e1dcb8cd0.rgs_reference_main.spv > /tmp/ref.spvasm
```

| line | instruction | reading |
|---|---|---|
| 1680–1682 | `%436 = OpImageFetch %v4uint` at `registers[1]+5`; `%438 = extract 1`; `%439 = %438 >> 5` | **material class** |
| 1688 | `%446 = OpIEqual %bool %439 %uint_1` | **class == 1 = skin** |
| 1691 | `%449/%450/%451 = OpSelect(%448, 1.0, albedo²)` where `%448 = (metal<0.1) && %446` | the **same skin demodulation idiom** as §4 |
| 1696–1755 | branch `%12264`, a per-profile LUT read at index `%471 = … + 65` | skin SSS profile fetch |
| 1758 | `%514 = OpPhi(1.0, %485)` | a **skin-only scale on both output channels** (@14388/14380) |
| 1762 | `%518 = %449 − %449·metal` | primary **diffuse albedo** |
| 1811/1814 | `%12276` / `%12277` loop | the bounce loop |
| 1815 | `%683 = OpPhi %uint %439 %12276 %uint_0 %12786` | **class on the first iteration, 0 on every later one** |
| 2036 | `%1117 = OpFDiv %float %684 %876` (block `%12285`) | **the diffuse-lobe throughput**: `albedo / p_lobe` |
| 2043 | `%1123 = half(%1117) × %719` | × previous throughput |
| 2282 | `OpTraceRayKHR … cullMask %uint_1` | the bounce ray — this is `ptbounce` |
| 14280 | `%3241 = OpFMul %half %3238 %721` | segment radiance × throughput |
| 14290 | `%3244 = OpSLessThan %bool %741 %uint_2` | **exactly 2 bounces** |
| 14474 / 14481 | `OpImageWrite` at `registers[5]+1` and `registers[5]` | diffuse + specular radiance, `.a` = NRD normalized hit distance |

`%439` and `%446` sit in one unbroken basic block ending at the branch on
line 1695 (no `OpLabel` between 1560 and 1694, and the module has **one**
`OpFunction`), so the skin gate **dominates both image writes**. This module
has none of `42`'s dominance problem.

**The load-bearing detail, and it cuts against the obvious splice.** The
diffuse lobe is cosine-sampled (`%12284`: `Sqrt`, `Cos`/`Sin`, tangent frame,
@1988–2020) and its throughput at `%12285` is `albedo / p_lobe` — the `1/π`
and the cosine are **analytically cancelled**. So:

- the module's **six** `albedo × 1/π` triples (@8883, 8914, 9807, 9838,
  13891, 13922) are NEE/MIS **direct-light** evals at the *current* surface,
  which on iterations ≥ 1 is a bounce surface, not the face. `patch_skin_brdf.py`
  targets exactly these six. **Patching them would not brighten bounce-lit
  skin, and on the second bounce it would apply a skin factor to a wall.**
- the **only** term through which indirect light reaches a primary skin pixel
  in this module is `%1117/%1118/%1119`. That site has never been patched by
  anything in this repo.

## 6. What is *not* the answer, and why

- **Any compute module.** Step 4 of §2: 68 unanchored compute float-colour
  writers do BRDF math; 2 read the class; both (`715d349aa3787397`,
  `cd7206ece6616e2c`) have **0 dispatches**. They are structurally the compute
  twins of §4 — same `OpSwitch class {1,4}`, same `metal < 0.1` skin
  demodulation, 16×16, two float targets — i.e. the same job in a **non-PT
  render mode**. Record them; do not build for them.
- **`743ab2734ff240ad` / `11c15299f77e54dc`** (the two compute modules that
  survive a "1/π + `>>5` + one colour write + 14 fetches" filter and look
  exactly like a GI resolve): **0 dispatches**. Filed because they will look
  attractive to the next search too.
- **`fbace6abe5c2ab11`**: 1/π, indirect dispatch, 38 runs — but **0
  `OpImageFetch`**, so it reads no G-buffer, and its `>>5`s are not on a
  fetched `v4uint`. Not a G-buffer shader.
- **`55f6172c71799e4d.chs_main`**: anchored, glob-excluded, but writes **no
  image**. `06`'s structural claim survives; only its conclusion about where
  shading lives was superseded by `24` §2.

## 7. Where this is weak — attack these first

1. **`rgs_reference_main` vs `rgs_restirgi_*` is not settled statically.**
   Both dispatch in the user's mode (`24` §2), both write to `registers[5]+1`,
   both use the same 1/64 pre-scale and the same skin demodulation. One of
   them is probably feeding the other, or one is mode-dead. Nothing here
   decides it. §8 is designed to decide it in one launch.
2. **The dispatch evidence for raygens is the stale table.** `00` §8 item 4:
   `trace_rays` output is untrustworthy. The counts in §2 step 6 (`d002cc05`
   ×6, `4270b745` ×3, `006ba4e3` ×2, `5e1e98e4` ×2) are *lower bounds at best*.
   `pipe_stage` shows all 8 restirgi radiance writers compiled into RT
   pipelines every launch, which is creation, not execution (`GOTCHAS` rule 2).
   **Do not quote the raygen dispatch counts as proof of execution.**
3. **The `46` §12/L2 null on S2 is "below two instruments' floor", not "this
   module does not write these pixels".** The probe's paint is *multiplicative*
   and S1's own paint was a step function of luminance (+0.008 below 94,
   +0.285 above 117 — `47` §3.3). A dim face producing sub-threshold paint is
   not formally excluded by that measurement. The structural finding in §2
   does not depend on it, but the *ranking* partly does.
4. **`715d349a`/`cd7206ec` having 0 dispatches is a claim about one journal**
   spanning the 2026-08-30 launches. If the user has ever run without PT since
   the log was truncated, that window is not covered.
5. **`0.015625` = 1/64 in both families** is read here as an f16 range
   pre-scale, not a 64-sample average (the outer "loop" `%12276→%12818` has an
   unconditional back edge and exits through the inner loop's merge — a
   dxil-spirv structurizer artefact, not a 64-iteration loop). Not proven.
6. **`%514`** is called "a skin-only output scale". It is `OpPhi(1.0, %485)`
   where `%485` comes from the class-1 LUT branch, and it multiplies both
   written channels. Its *meaning* (SSS profile weight? diffusion energy
   normalisation?) is not established, and `GOTCHAS` method rule 5 applies:
   the space that site holds is a contract nobody has read.

## 8. (a) The cheapest on-screen confirmation — one launch, three answers

**`skinspec=probe-gi`: a hue-coded class probe in the raygens.** Extend
`dev/patch_subtype_probe.py` (it already imports `patch_skin_brdf`'s raygen
machinery, `patch_shadow_brdf.find_class_fetch` and
`patch_compute_brdf.find_image_writes` — the parts needed already exist and
are already validated) to paint at the raygen radiance writes, gated on
class 1, with a **different palette per family** rather than per class:

| family | modules | paint (multiply on the written RGB) |
|---|---|---|
| `rgs_reference_main` | 12 | **green** `×[0.30, 3.00, 0.30]` |
| `rgs_restirgi_*` diffuse | 4 | **red** `×[3.00, 0.30, 0.30]` |
| `rgs_restirgi_*` specular | 4 | **blue** `×[0.30, 0.30, 3.00]` |

Compute probe **off** — this launch is only about the raygens.
Shoot **S2 (bounce-lit interior, the question)** and **S1 (direct sun, the
positive control — `47` §3.2's lesson: never a single-scene probe launch)**.

Reading, on the S2 face, measured as `47` §3.3 did (ratio against the null,
non-skin control in the same frame, p99.9 threshold):

| S2 face | conclusion |
|---|---|
| **green** | `rgs_reference_main` writes bounce-lit skin. Splice §9 site B. |
| **red** | the ReSTIR GI diffuse raygens do. Splice §9 site A. |
| **blue only** | only indirect *specular* reaches it — the diffuse term is composited elsewhere; re-open the search at the re-modulation pass. |
| **yellow / magenta / white** | both families contribute; splice both, and expect them to double-count. |
| **no paint anywhere, S1 painted** | the raygen radiance is not what lands on that face either. Then the next suspect is the **re-modulation / SSS composite** compute pass that multiplies the demodulated diffuse back by albedo — find it as the reader of the image `registers[5]+1` resolves to. |
| **no paint in S1 either** | the probe did not serve. Audit before reading anything. |

Build and serve notes, each one a rule this repo already paid for:

- Build the probe **on top of the installed ptq base**, the way `patch_ser.sh`
  does (`--from ~/.local/lib/callisto/ptq/rcbm/base`), or the overlay will
  un-patch ptq and the launch will be uninterpretable (`GOTCHAS`: *an overlay
  reject must fall through, never to vanilla*).
- **Assert the site count from the patcher's own JSON report**, not a byte
  diff: 20 modules, ≥1 painted write each, 0 `skipped_dom`
  (`GOTCHAS`: *a byte diff is not coverage*).
- Verify the serve from the journal before believing the frame:
  `./dev/ab_launch_audit.py N` should show **12** `rgs_reference_main` HITs and
  **8** `rgs_restirgi_*` HITs. A count that differs from 20 is a finding.
- **Expect global tint and measure against it.** `47` §3.3: painting a class
  tints the whole scene through GI. Painting the *GI pass itself* is worse.
  The class-1 gate keeps first-order paint on skin; everything else is
  second-order. Report skin-vs-non-skin, never absolute.
- `make install`, then `cmp` (`GOTCHAS`), and confirm `brdf_params.txt` names
  a rung that was actually built — `42` §6 lost a launch to exactly that.

## 9. (b) The splice plan, if confirmed

### Site A — `rgs_restirgi_{spatial,spatiotemporal}` diffuse ×4

- **Gate:** the existing `>>5` (`%155` in `006ba4e3`). It is a `>>5` of
  `OpCompositeExtract 1` of an `OpImageFetch %v4uint`, which is the *exact*
  shape `acquire_class_shift` already looks for, and it **dominates the image
  write**. No `lift_class_gate` phi walk, no refetch. Assert dominance in the
  report anyway — `42` is the reason that assert exists.
- **Sites:** the three channels feeding the write (`%1375/%1377/%1379` in
  `006ba4e3` @3061–3067). Multiply each by tier-1 `c1`. The buffer holds
  irradiance ÷ diffuse albedo, and on skin the albedo has already been forced
  to 1.0, so `c1` lands on a clean irradiance term — but that also means
  **`alpha_max`, the gloss ladder and anything albedo-shaped have nothing to
  act on here.** Ship `c1` only at site A; do not port `skinspec`.
- **Angles:** `NoV` is in scope. `NoL` for the reservoir's sample direction is
  in scope in the *specular* siblings (`%1593 = dot(N,L)` in `1ca55ed0`
  @3475). If it is not recoverable in the diffuse variants, ship the
  **NoV-only half** of `c1` and say so in the report — do not silently
  substitute 1.0 for `NoL` and call it tier-1.
- **Do not touch** the `1/π` at `%892` or anything feeding `%703`. That is the
  ReSTIR pdf. Editing it changes noise, not appearance, and it will look like
  a working patch that does nothing (`00` §2's one true case).
- Add `rgs_restirgi_*` to `sync_settings.sh`'s materialisation the way the
  `shadowsets` overlay already moves those eight files (`25` (§"sync_settings.sh moves the *rgs_restirgi_* files")).

### Site B — `rgs_reference_main` ×12

- **Gate:** `%683 == 1`. `%683` is the class phi at the loop header
  (`OpPhi %uint %439 <preheader> %uint_0 <latch>`, @1815). It is the primary
  surface's class on the first iteration and `%uint_0` on every later one, so
  `%683 == 1` means exactly **"first bounce AND the primary surface is
  skin"**. That is a free, exact primary-only skin gate that emits no
  instructions — the same trick `42` §4 used, here handed to us by the
  compiler. Class 0 is not skin, so the guard operand is safe
  (`GOTCHAS`: *guarded-fetch phis are safe to gate on* — check every operand
  anyway; here there are exactly two, `%439` and `%uint_0`).
- **Site:** `%1117/%1118/%1119 = %684/%876` in block `%12285` (@2036–2038) —
  the diffuse-lobe throughput. Multiply by `c1`. This is the **only** path by
  which indirect light reaches a primary skin pixel in this module.
- **Angles:** the cosine-sampled direction `%970/%971/%972` and the shading
  normal `%698/%700/%702` are both in scope at `%12285`, so the full
  `c1(NoL, NoV)` is computable without a refetch.
- **Do NOT** enable `patch_skin_brdf.py`'s existing tier-1 pass on the six
  triples as-is. They are NEE at the *current* surface; gated on the
  *primary* skin test they would apply a skin factor to bounce surfaces
  (§5). If those sites are wanted at all, they need the `%683` gate too,
  which restricts them to the primary hit — at which point they are a second
  *direct-light* term stacked on the compute resolvers' `c1`, i.e. a
  double-count. Ship site B alone first.

### Ordering

Site A is the cleaner splice (dominating gate, one multiply, no bounce-depth
reasoning). Site B has the only on-screen proof of reach in the repo
(`ptbounce`, `46` §18) and the only free exact gate. Build whichever family
the §8 launch paints, not both — `GOTCHAS`: *never land two independent
visual features between two observations*.

### What this does not fix

- The direct term still comes from the 77 anchored compute modules. After
  this lands, a skin pixel in mixed light gets `c1` from **two** surfaces.
  Whether the rung values still read the same is a tuning question, and `42`
  §6's warning applies again with more force: start a rung below where the
  eye currently sits.
- `rgs_shadow_main` ×10 is anchored, glob-excluded, writes float colour and
  tests class 1 — the **direct** shadow/visibility family. It is out of scope
  here and it is a separate question whether the shipped shadow patchers ever
  touched its shading sites.
