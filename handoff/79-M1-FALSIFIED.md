# 79 — M1 (the denoiser sees vanilla roughness) is falsified, and the falsifier in `43`/`51` never tested it (2026-08-31)

## 0. Verdict

The user asked whether "RR off looks sharper in screenshots" justifies
building `43` §3 M1 — cap roughness where the denoiser reads it, or move the
roughness edit to the G-buffer write. **No.** The observation is real and has
a cheaper cause; M1's own falsifier does not discriminate; and the test that
*does* discriminate already ran on 2026-08-30 with RR **on**, and M1 lost.

**Nothing was built and nothing was undone** — this was a read-only pass over
the dump, the ledger and the live install. This doc exists so the item is not
re-queued a fourth time.

M1's *premise* survives and is worth stating correctly, because `32` §3 has it
backwards (§5 below). The denoiser does read G-buffer roughness. It is just
not the reason anything reads soft here, and the fix routes are blocked.

## 1. The look you are judging has no Ray Reconstruction in it

Live `UserSettings.json`, read 2026-08-31 (file mtime 22:41; the last launch
was 22:28, so this is the state that launch ran under):

| setting | value | default |
|---|---|---|
| `RayTracedPathTracing` | `true` | false |
| `RayTracedPathTracingForPhotoMode` | `true` | false |
| **`DLSS_D`** (Ray Reconstruction) | **`false`** | false |
| `DLSS` | `Balanced` | — |
| `DLSS_BackendPreset` | `Transformer` | — |
| `DLSS_NewSharpness` | **`0.3000000119`** | **`0.0`** |
| `Resolution` | `2560x1440` | — |
| `DLSSFrameGen` / `DLSS_MultiFrameGeneration` | `true` / `x2` | — |

Live `brdf_params.txt` at the same moment: `skinspec=gi-50b-bleed-oil-sheen-deep`,
`kernel=spectral`, `refract=eta15`, `ser=class`, `ptreg/ptclamp/ptbounce/ptrefl/ptmsggx`
all on.

So the oil, the half-fuzz, `-lumn` and the `-deep` band — every look approved
between 2026-08-31 14:17 and 22:28, including *"Deepest band is actually the
best skin shader right now"* — were judged with RR **not in the pipeline**.
M1 is a claim about a stage that was not running. It cannot be softening the
look being tuned.

> **Side effect, closes an open item:** `CURRENT.md` lists "which level was on
> screen (eta20 vs eta15)" as unrecorded for the `76` refraction launch. The
> live install says **`refract=eta15`**.

## 2. The `43`/`51` falsifier does not test M1

As written (`43` §3, `51` §6.1): *"RR off, NRD on, same cap → if the highlight
sharpens, M1 is confirmed."*

That swaps one roughness-guided denoiser for a different roughness-guided
denoiser. NRD takes roughness as a **required** input (`IN_NORMAL_ROUGHNESS`)
and ReBLUR's specular filter radius scales with it — which is the whole reason
`detail_engine.lua` exposes `LobeAngleFraction` and the specular prepass
radius. Both arms of the test read the same vanilla G-buffer roughness.

So a sharpening under that swap is fully consistent with M1 being **false**.
The test measures *which denoiser*, never *whether the guide is vanilla*. It
should never have been queued as a decision gate, and it sat as `CURRENT.md`
queue item 3 through three sessions on that basis.

**The test that discriminates is differential**, not absolute: does the mod's
roughness edit produce a *larger* on-screen effect with the denoiser out than
with it in? That needs two rungs on the roughness axis, not one setting
toggle. It already exists (§3).

## 3. The discriminating test already ran, with RR on, and M1 lost

`46` §11.3, the E2a→E2b differential. Both launches are post-13:30 regime B
(`46` §13), and both are **RR on**. E2a/E2b ran at 13:36:34 and 13:50:52,
which is before the entire L-session (`47` §5's ledger opens at L1, 14:45:50),
so no RR toggle had been attempted when they were shot. And when one finally
was, it failed: the ledger's only RR-off arm is **L4a, 15:37:29, "E1 exact
(RR *not* off)"** — `UserSettings.json` read `DLSS_D: true` afterwards and the
arm became a third null (`47` §5). RR was still on for L5–L8 as well, verified
independently on the non-skin fine-energy metric (`46` §17).

| launch | rung | roughness | time |
|---|---|---|---|
| `E2a-rough-1.3` | `rough-1.3` | rougher than vanilla | 13:36:34 |
| `E2b-gloss-0.7` | `gloss-0.7` | sharper than vanilla | 13:50:52 |

Measured, S1, with the noise floor cancelling because it is a near-uniform
*relative* offset between two rungs:

- whole face **−0.032** (non-skin controls +0.03 / −0.04 / +0.00 — flat)
- **top-3% highlight bin +5.756 = +3.23%**

`46` §11.3 calls this "the only quantitative S1 result standing" and §11.5
concludes "the metric now confirms *the axis works*". Independently, the user
read `rough-1.3` unprompted as *"…details back on the character. Like a detail
filter. I can see everything."* (`46` line 233) — also RR on.

**A resolve-side roughness edit that moves the specular peak by 3.2% and is
perceived without prompting is reaching the screen through Ray
Reconstruction.** M1's claim is that RR "spatially smears exactly the tight
highlight the cap produced", i.e. that this edit is neutered. It is not.

M1 is not *impossible* — the denoiser filtering at vanilla-roughness radius
while the lobe is tightened is a real, second-order over-blur. It is simply
not the mechanism behind "gloss reads soft", and it is not worth a fragment
unlock.

## 4. What "RR is blurrier" actually is

Two causes, both of which predict the observation with M1 entirely false, and
both of which would blur brick and foliage as much as a cheek:

1. **`DLSS_NewSharpness = 0.3` against a default of `0.0`** — verified above.
   Sharpening is applied on the DLSS Super Resolution path, which is the path
   every recent screenshot was shot on. *(Unverified: whether RR consumes this
   slider at all. There is no RR-specific sharpness key in `UserSettings.json`
   — only `DLSS_NewSharpness` and `DLAA_NewSharpness`. Check before relying
   on it.)*
2. **RR is a joint denoise-and-upscale with longer temporal pooling.** `46`
   §11.4 already measured its signature from the other direction: two
   byte-identical launches differ by dense **pore-scale speckle over the whole
   face** with flat static controls — "which micro-detail Ray Reconstruction
   decided to resolve". A reconstruction that disagrees with itself run-to-run
   at pore scale is one that is pooling hard at pore scale.

**Free check, no launch:** in the RR-on and RR-off screenshots already taken,
crop a non-skin, non-specular surface — brick, asphalt, foliage. If it
softened as much as the cheek did, the cause is reconstruction, not roughness,
and M1 is irrelevant to it. If skin softened *materially more*, reopen §3.

## 5. Doc correction: `32` §3 is wrong about the denoiser

`32` §3 states NRD/DLSS-RR "applies a spatial filter with **no material
awareness**", and derives from it that "the lever is the denoiser or the
internal resolution and neither is in this project's reach."

Both halves are wrong. NRD is material-aware by construction — packed
normal+roughness is a required input and drives the specular radius. And the
denoiser **is** in reach: `detail_engine.lua` has exposed 22 of its knobs
since `33`, and they are live whenever RR is off, which is the standing
config. `43` M1's premise is the correct statement of this; `32` §3 is the
error. Corrected in place.

## 6. Why the fix routes are blocked anyway

**Route (a) — patch RR's roughness guide-buffer producer.** Moot in the
standing config: RR is off, so no RR guide buffer is produced. It only ever
applied to the RR-on gameplay case.

**Route (b) — do the roughness edit at the G-buffer write.** Needs G-U2, and
G-U2 is exactly as unrun as `38` says. Stage census over the 3273 dumped
modules (`dev/census_stage.py`, reproducible):

| stage | modules |
|---|---|
| Fragment | **1290** |
| Vertex | 1179 |
| GLCompute | 675 |
| MissKHR | 57 |
| RayGenerationKHR | 43 |
| ClosestHitKHR | 24 |
| AnyHitKHR | 5 |

and `ls swaps.*/ | grep -ciE '\.ps_|frag|pixel'` returns **0** — no fragment
module has ever been swapped by this project, so `36` G1 ("does a fragment
splice execute at all?") is still unanswered. Route (b) is a speculative
unlock first.

It is also the wrong shape even if the unlock lands. G-buffer roughness feeds
*every* consumer — SSR, reflections, the material system, both GI resolvers —
so the edit would double-apply against the resolve-side `alpha_scale=0.7` +
`alpha_max=0.2025` already carried by the shipping rung
(`dev/patch_compute_skin.sh:127`), forcing a re-tune of a look the user just
approved.

## 7. What the same observation does justify

**(a) The denoiser panel has never been turned on.** `detail_engine.txt` is
**absent** from the live install
(`…/cyber_engine_tweaks/mods/CallistoSSS/`), so every knob sits at its engine
default. With RR off, ReBLUR is the live denoiser at stock radii:

| knob | live value | `detail_engine.lua` |
|---|---|---|
| `NRD/DenoisingRadius` | 30 | :87 |
| **ReBLUR/Direct `SpecularPrepassBlurRadius`** | **20** | :98 |
| ReBLUR/Direct `DiffusePrepassBlurRadius` | 30 | :96 |
| ReBLUR/Direct `StabilizationStrength` | 1.0 | :106 |
| `MaxAccumulatedFrameNum` | 31 | :89 |
| ReLAX `AtrousIterationNum` (direct/bounce) | 5 | :114/:116 |

The specular prepass is, in the file's own words (`detail_engine.lua:94`),
"an unconditional spatial average applied to the radiance before any
edge-aware filtering gets a say." **That is M1's mechanism, live in the
current pipeline, on a runtime slider, at zero build and zero launch cost.**
Verified deployed: `detail_engine.lua` is byte-identical across repo,
`release/` and the live install (`cmp`), and `init.lua:305-310` loads it,
`:734` registers it.

Do this first: enable the panel, pull `SpecularPrepassBlurRadius` toward 0 and
`DenoisingRadius` down, watch the highlight live. `detail_engine.lua:208`
already ships the one-click version — `sharpAsPossible()` zeroes
`DenoisingRadius`, `RB_D_DiffusePrepass` and `RB_D_SpecPrepass` together, so
the ceiling is one button and the useful work is walking back from it. It costs one session and no
launch, and it directly measures how much denoiser radius is worth on this
rung — which is the number M1 was guessing at.

**(b) The DLSS preset.** Balanced at 1440p; PT lighting resolves well under
native and is upscaled. A denoiser radius 20–30% too wide for the tightened
lobe is second-order next to that. `43` §2 (0d) already corrected `38` on this
and called the preset "the single cheapest face-sharpness lever in the whole
document"; it is still unrun as `43` §4 item 4. One launch at Quality or DLAA,
same save, same camera.

Order: (a) then (b). Both beat M1 on cost and on expected effect, and neither
risks the approved look.

## 8. State

No shader, patcher, build script or rung changed. Added:
`dev/census_stage.py` (stage census, §6). Doc edits: `32` §3 corrected (§5),
`43` §3 and `51` §6 marked falsified with a pointer here, `CURRENT.md` queue
item 3 closed, `handoff/README.md` index row.
