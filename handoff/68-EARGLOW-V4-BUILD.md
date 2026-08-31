# 68 — Ear glow v4: the one-sided gate, built and parked

Written 2026-08-31, after `67`'s probe verdict (rim = cons AND albedo; night
face = cons alone, flat-on at ~2 m). The mandated offline read was done
BEFORE constants were set; its finding reshapes `67` §2's theory (§1 below).
All three rungs parked over `earglow{,-lo,-hi}` (93 modules each; d622fb9e
k=0.22 sha256 prefix `2fdf7950b061638e`). `probe-earglow` untouched
(`bb5702337d39d803`, still the v3-gate instrument — `67`'s readings remain
valid against it). Nothing committed; selector stays `gi-50-bleed`.

## 1. The bias read: NO along-ray systematic exists — the error is LATERAL

Full re-read of the deployed chain (input spvasm cited; the deployed v3
bytes are identical in this region — the splice hunks sit outside it):

- **P_raster**: depth fetch `heap[registers[1]+1]` at the checkerboarded
  coords (`:1439–1444`); NDC = pixel+0.5 × cbv[58].zw — **no jitter term is
  re-applied** (`:1562–1569`); near/far matrix split on d≥0.9 (reverse-Z
  near-field precision path, cbv[8–11] with d remapped ×10, vs cbv[0–3]
  raw; portrait pixels take the far path) (`:1570–1609`); homogeneous
  divide → `%1478–80` (`:1610–1612`). The linearization `%1377` (cbv[59],
  `:1505–1509`) feeds ONLY the offset scales (dscale `:1623–1626`, nmag
  `:1637–1642`), never the compared position.
- **The re-trace**: init position `%1520–22` = praster − c1·D̂·dscale +
  c0·N·nmag·[N.z>0] (`:1620–1654`), direction = normalize(that)
  (`:1655–1661`); the loop position/direction phis init from exactly these
  (`:1844–1849`); the radiance trace's origin operand is the position phi
  **verbatim** — no hidden per-bounce offset (`:2288–2290`).
- **prehit** `%2442–44` = phi + m3·D (`:2623–2628`) where the CHS stores
  m3 = **BuiltIn RayTmaxKHR unmodified** (`chs_main_15` `:100`, `:225`,
  `:1709`) → prehit is the EXACT traced hit point.
- **`%2454–56`** (the flagged triple): components of c1·D·dscale inside the
  NEXT-bounce origin offset (`:2636–2641`), applied to prehit to form
  `%1729/31/33` (`:2658–2665`). Offsets live in ray ORIGINS only; neither
  compared point carries one.

Algebra on a surface plane (normal N_s, μ = −D̂·N_s): the c1 back-off along
D̂ cancels in the re-hit (travel u = δD + δN/μ); the c0·N push does NOT —
it slides the re-hit laterally: Δ = δN·(N + D̂/μ), so |Δ| = δN·tanθ and
s = Δ·D̂ = **+δN·sin²θ/μ ≥ 0 for c0>0 — behind, the SAFE side of a
one-sided gate**. δN = c0·clamp(0.005·√t_lin, 0.005, 0.1) ≈ 5–7 mm·c0 at
portrait range: distance-scaled, zero flat-on.

**So no additive along-ray term exists to subtract — `67` §2 is demoted in
form and confirmed in substance**: the systematic is praster's lateral
registration error (jitter never re-applied; checkerboarded depth
registration; the engine's own N-slide), magnitude ≈ p·θ_px·t with p ≈ 2
internal pixels (θ_px ≈ 1.1e-3, DLSS Balanced). The v3 two-sided NORM saw
it through local slope (night face: nose/cheek slopes 45–70°, |Δ| ≈
2.2·t·tanθ mm > 5 mm — RED; nostril at t<1 m — under it — BLUE). It is
**removable by projection**: an along-ray compare zeroes it flat-on by
construction, and its grazing conversion is exactly lateral·tanθ — which
fixes the slope term's shape (tan, not the flat a·t/μ of `66` §6: the flat
shape would waste a·t ≈ 5.5 mm of flat-on leak sensitivity at 2.5 m).

## 2. The gate as built

    s      = (prehit − praster) · D̂        D̂ = %2120–22 (the bounce-0 direction phis,
                                            the same ids prehit is built from)
    pass  ⟺ s > −ε_eff                     (kill only in FRONT — a leak's occluder
                                            is strictly nearer the camera)
    ε_eff  = ε₀ + b·t + a·t·√(1−μ²)/max(μ, c)
    μ      = |N·D̂|                          N = %1703/%1705/%1707 (the module's own
                                            primary-normal decode), t = %2148 (m3)

    ε₀ = 3 mm    b = 1.5 mm/m    a = 2.2 mm/m·tan (= p·θ_px, p=2 px)    c = 0.10

All ids module-own; in scope because the whole region `:2565–2670` is one
basic block (last label `%2152` at `:2564`) and prehit's in-scope proof
transfers transitively. D̂/t/N are harvested by the extended
`find_origin_offset` walk with cross-checks: direction ids must match
between the dterm chain and the prehit t·D product; t common across
components; harvested N.z must be the operand of the engine's own [N.z>0]
select. Emission: +21 instructions replacing v3's 3 (two Dots, one Sqrt,
one FDiv, the ε_eff sum, one FOrdGreaterThan); no new fetches or traces;
identity-when-dead unchanged (cons false → mask 0 → thin false → 0).
Albedo eps back to **0.25** (v2's — every ear glowed under it; leaks don't
care, albedo is vacuous at leak pixels per `65` §0). Vis ray, thin-hit, k
rungs, ld, NMin clamp: byte-level unchanged.

## 3. Sanity arithmetic vs 67's loci (mm; ε_eff = 3 + 1.5t + 2.2t·tanθ_eff)

True positives — expected |s| ≈ lateral·tanθ = 2.2t·tanθ (the a-term is
calibrated AS this, so margin = ε₀ + b·t):

| locus | ε_eff | expected \|s\| | verdict |
|---|---|---|---|
| night face 2.5 m, slopes ≤55° | 14.6 | 7.9 | PASS ×1.85 (v3 failed: \|Δ\|=7.9 > 5) |
| sunward nostril 1 m, 60° | 8.3 | 3.8 | PASS ×2.2 |
| ear rim 1.75 m, 80° | 27.4 | 21.8 | PASS ×1.26 — the a=2px bet |
| rim ≥85° (cap μ→0.1) | 44 | ≥44 | boundary — beyond ~85° stays gated (registered) |
| v3's crease line | — | — | roomier than the 5 mm it already passed |

Leaks — |s| = standoff/μ, kill iff |s| > ε_eff:

| locus | ε_eff | kill threshold | verdict |
|---|---|---|---|
| S4 temple strand 1.75 m, 45° | 9.5 | standoff > 6.7 mm | overhanging strands (est. 8–20 mm) DIE; lying strands (<5 mm) survive — registered |
| flat-on strand 2 m | 6.0 | standoff > 6 mm | tightest case the tan shape preserves |
| collar edge 1.5 m, 60–80° | 12–25 | standoff > 6–12 mm | collar standoffs (est. 10–30 mm) DIE |

v2 strand/collar statement (asked): v2 had no consistency gate — those
leaks existed under albedo 0.25, so 0.25 cannot re-open them alone. v4
kills them again iff their standoff exceeds ~7 mm (flat) to ~12 mm (60°) at
their range; the estimates (overhang 8–30 mm) say YES, but `67` §2's
corollary stands — the separation was never measured, hence the RETURN row.

## 4. Pre-registered table — fill from the launch

| observation | attribution |
|---|---|
| **PASS row**: whole backlit ear incl. helix rim glows, nose glows sun-side, frame otherwise == gi-50-bleed | v4 wins; the lateral-registration read was right |
| strands/collar RETURN | standoff < kill threshold at that range — **measured escalation via an s-band probe** (reuse the 66 machinery: paint sign/magnitude buckets of s/ε_eff — RED s<−ε_eff, YELLOW −ε_eff<s<0, GREEN 0≤s<ε_eff, BLUE s≥ε_eff), NOT blind tightening |
| ear glows but rim still dark | residual angle term (p > 2 px, or the ≥85° cap) — same s-band probe at the rim decides a vs cap |
| everything dead again | **sign error in the one-sided term — check FIRST**: one-sided flips polarity risk; verify leak-side really is s<0 (D̂ orientation) in a dump before touching any constant |
| V-band returns on the forehead | the 0.25 albedo readmitted it — its own measured pass later (`63`; never re-verified) |

## 5. Validation record

- 3 rungs × 93: spirv-val clean; emitted re-read clean, baseline-aware:
  albedo 0.25 = base+3, zero stale 0.10 / 2.5e-5 compares, Dot = base+3,
  Sqrt = base+1, FOrdGreaterThan = base+2 (N.z gate + one-sided cons), v4
  constants present by value, plus all v2/v3 structural asserts.
- Hand-read d622fb9e diff (7 hunks, 278 lines): the gate block §2
  verbatim; albedo compares at `%float_0_25` ×3; vis condition on g_a3;
  k-select and glow block untouched.
- Parked == built cmp-verbatim ×3 + MANIFESTs (provenance line verbatim,
  v4 comment lines).
- `probe-earglow` NOT rebuilt: parked bytes still `bb5702337d39d803` (the
  v3-gate instrument). The shared patcher now emits v4 gates, so a probe
  REBUILD measures v4 — `build_probe_earglow.sh` asserts updated to match,
  with a header note distinguishing parked-vs-rebuilt semantics.

## 6. Confidence

| claim | confidence |
|---|---|
| no along-ray systematic in the compare's construction | **certain** — every hop read: RayTmaxKHR unmodified, origin = phi verbatim, offsets origin-only, back-off cancels |
| lateral registration is the flat-on killer | **high** — it is the only remaining candidate and p≈2 px fits all five loci; p itself is estimated, not read |
| one-sided tan-shaped gate recovers the rim to ~85° | **medium-high** — ×1.26 margin at 80° rests on the p=2 estimate |
| leak kill survives the widened gate | **medium** — standoff estimates only; the RETURN row carries the measured escalation |
