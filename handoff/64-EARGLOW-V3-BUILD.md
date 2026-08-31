# 64 — Ear glow v3: the consistency gate, built and parked

Written 2026-08-31. One gate-system revision over v2 (`62`), per `63` §2: a
pixel↔primary consistency gate plus the albedo threshold tightened 0.25→0.10.
Built over `gi-50-bleed` bytes, all three rungs parked over
`~/.local/lib/callisto/skin.set/earglow{,-lo,-hi}`. Launch pending. Nothing
committed; selector stays `gi-50-bleed`.

## 1. Leak theory VERIFIED — the reference PT has no traced camera primary

`63` §1 called the survivors pixel↔primary boundary leaks at "high — not
pixel-proven". Code-reading upgrades that to **certain as a mechanism**: the
reference raygen never traces a camera primary at all. It rebuilds the primary
from the raster G-buffer and then **re-finds** the surface with a real ray:

- fetches raster depth from `heap[registers[1]+1]` at the same checkerboarded
  coords the class fetch uses (`cbv[78].y + LaunchId.x, LaunchId.y`);
  reverse-Z, `.x==0` → sky early-out (`:1439–1446`, merge `%1318`);
- linearizes (`%1377`, cbv[59]) and unprojects via the cbv[8–11]/cbv[0–3]
  matrices to camera-relative **P_raster = `%1478–1480`** (`:1610–1612`, an
  FDiv triple over one shared denominator);
- applies its own cbv[77] self-hit offset (`:1652–1654`) and enters the bounce
  loop with direction = normalize(that position) — the bounce-0 "radiance
  trace" (`:2290`) is a **real ray query aimed back at the raster surface**.

On a sub-pixel boundary sliver that re-trace lands on the *other* surface: the
G-buffer says skin (class gate passes), the primary hit is the strand / collar
edge / fringe, v2's albedo compare degenerates to prop-vs-prop, sun visible →
glow. Exactly the three survivors. Theory verified before building, per the
directive.

## 2. The slot proof (GOTCHAS 13): satisfied in-module — no lift needed

The feared hard precondition was proving a G-buffer depth slot addressable
from this module. It dissolves: **the module already does the fetch and the
reconstruction itself.** The gate compares two triples the module computes
anyway:

- **P_primary** = `%2442–2444` = P_i + t·D (`:2623–2628`; `%2439 = OpFMul
  %2148 %2120` confirmed t×D) — the bounce-0 hit position *before* the NEE
  origin offset;
- **P_raster** = `%1478–1480` — the unprojected raster position from §1.

Zero new descriptor fetches. The `48`/`50` restirgi maps and the `20` Phase
0.5 reflection lift sources are not needed — they were the fallback for an
*external* slot, and there is no external slot. Addressability is mechanical,
asserted per module by the detector (`find_raster_position`):

- the three P_raster FDivs share one denominator and precede the loop header;
- the splice site (NEE, `:3583`) sits inside the depth≠0 branch: sky merge
  label `%1318` is at `:14788` > 3583 — structured dominance, recorded as
  `sky_merge_line` in each report.json.

## 3. What was emitted (hand-read on d622fb9e)

Between v2's gate AND-chain and the thickness-trace mask select:

```
%12991–93 = OpFSub  prehit_i − praster_i        (×3, module's own ids)
%12994    = OpCompositeConstruct v3
%12995    = OpDot   (self)                       |Δ|²
%12996    = OpFOrdLessThan  %12995  2.5e-5       CONS_EPS² (5mm)
%12997    = g_a3 = g_a2 ∧ cons
%12998    = OpSelect g_a3 ? 39 : 0               thickness cullMask
```

and the vis-ray condition (`vc0`) moved g_a2→g_a3. Albedo compares now hit
`%float_0_100000001` ×3; no new 0.25 compare. Identity-when-dead unchanged:
gate false → mask 0 → thickness ray misses → m3 stays 10000 → vd false → k
select 0 → contribution exactly 0. Full diff: 7 hunks, 260 lines — entry-point
interface, constants+payload var, accumulators, the one splice, three
image-write merges. Nothing else.

Cost: 3 FSub + dot + compare + AND per gated pixel — noise next to the two
traces v2 already pays. No new traces, no new fetches.

## 4. CONS_EPS = 5mm (not the suggested 1–2mm)

The compare is squared camera-relative meters: `|Δ|² < 2.5e-5`. Budget on a
TRUE match: f32 reverse-Z depth error at portrait range (<0.1mm) +
unprojection rounding are negligible; the dominant term is the engine's own
self-hit offset — the re-trace starts from an origin pushed off the surface by
`c0·N·clamp(0.005·√t, 0.005, 0.1)`, so the re-hit slides along the surface by
that offset times tan(grazing angle), plausibly **several mm at portrait
distances** before any leak is involved. 1–2mm sits inside that band and risks
killing true positives; 5mm sits above it while a strand/collar/fringe leak is
a *different surface* — centimetres of separation in depth. Rim-grazing true
positives are empirically covered: v2's re-trace demonstrably holds ear
surfaces at rims (the ears glow in v2). Fail direction is closed: too tight
kills glow, never paints.

## 5. ALBEDO_EPS 0.25 → 0.10

The payloads quantize RGBA8 (1/255 ≈ 0.004/step); 0.10 = 25 steps — far above
codec noise, so the compare stays meaningful. v2's 0.25 passed brown fringe vs
tan skin (`63`'s secondary suspect for V's forehead band): dark-brown hair
runs ~0.05–0.15 per channel vs tan skin ~0.3–0.5 — per-channel diffs of
0.15–0.35, most of which 0.25 admits and 0.10 rejects. Coordinator's range was
0.10–0.12; taking the tight end because the failure mode is fail-closed.

**Honest envelope**: same-skin albedo variation (cartilage vs lobe, freckles,
makeup, tattoo edges) exceeding 0.10 per channel kills glow *locally* on those
pixels — patchy glow, not artifacts. Dark skin has lower absolute albedo and
therefore smaller absolute variation, so 0.10 is roomier there, not tighter;
the exposure is makeup/tattoo boundaries on any skin tone.

## 6. CHS spare byte: denial confirmed

m1 bits 24–31 = `(1 + slope·t)·510·φ(sampled map)` — ray-cone/LOD footprint
(`chs_main_15` `:1269–1294` decode, `:1751` pack). Not translucency, not an
id, nothing to ride. `63`'s denial stands.

## 7. Validation record

- 3 rungs × 93 modules: spirv-val clean; emitted re-read clean. New asserts:
  albedo compares at 0.10 = base+3 (baseline-aware — 0.1 is a pre-existing
  engine constant with its own compare), zero new 0.25 compares, consistency
  compare at 2.5e-5 = base+1, Dot = base+2; all v2 asserts retained.
- d622fb9e diff hand-read in full (§3).
- Parked == built, cmp verbatim, 93×3; MANIFEST line-1 provenance verbatim +
  v3 comment lines. d622fb9e k=0.22 sha256 prefix `af59db3ec840c7ca`.
- report.json per module records `cons_eps`, `albedo_eps`, `prehit`,
  `praster`, `sky_merge_line`.

## 8. Pre-registered table — fill from the launch, then attribute

| observation | attribution |
|---|---|
| temple strands GONE | consistency gate — they were sub-pixel re-trace leaks |
| collar top edge GONE | consistency gate — same mechanism |
| V's forehead band GONE (strands also gone) | either term; not separable this launch |
| strands GONE but V's band PERSISTS | the band was the **threshold** case, not boundary — fringe-vs-skin diff < 0.10; next step is a *measured* tighten or (b′), not guessing |
| **PASS row** | backlit ears/noses glow against open sun; all three artifacts gone; S1/S2/S3 re-staged clean |
| ALL glow dead, incl. a staged backlit ear | ε too tight or the compare is broken — a true positive dying means broken pairing (prehit/praster mismatch), not "tighten worked"; dump the two triples before touching ε |
| strands PERSIST | leak theory wrong despite §1, or something stale — **do not iterate blind; escalate to (b′)/(d)** |

## 9. Confidence

| claim | confidence |
|---|---|
| survivors are boundary leaks | **certain as mechanism** — §1 code-read; the only "primary" is a re-trace |
| consistency gate kills the slivers | **high** — mechanism follows; ε not empirically proven |
| 0.10 kills the V band | **medium** — albedos estimated, not measured (`63` said medium) |
| no true-positive kill at 5mm | **medium-high** — offset-scale bound + v2's rim empirics |
