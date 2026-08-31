# 55 — G-U5 payload sentinel: built, parked, and the outcome table

Written 2026-08-30 night (delegated build; plan `51` §7 step 2, spec `29`
§B5). **Built, validated offline, parked as `skin.set/sentinel` and
`skin.set/sentinel-b`. NEVER on screen. Nothing here is *working* until a
launch says so — the launch is the main session's job.**

## 0. The question, precisely

Can a **new static `OpTraceRayKHR` site** spliced into a raygen execute and
return a payload value written by another stage? This gates the traced-
thickness transmission (`51` §7 — "ears go full red") and all of `29` Part B.

The graveyard: `26` §7d — a second static trace in `rgs_shadow_main`
(`sctrl`), disassembly-correct and spirv-val clean, **did not execute**; a
positive control came back vanilla and voided fourteen mask sets. `29` §B5
narrows it: the same pipelines demonstrably run **multiple dynamic traces**
through one site (the bounce loop, `ptbounce`, on screen), so what is
untested is a second static **site**, and `sctrl` reused payload and SBT
indices by hand in a different pipeline family. Untested hypotheses from
`26` §7d: (H1) recursion/pipeline limit, (H2) a vkd3d-proton/driver
restriction on multiple static sites, (H3) wrong SBT indices for the second
call. This build discriminates them (§4).

## 1. What was built

Two rungs on the standing `gi-50` base — its 77 compute, 4 restirgi, and 2
atomic-reference files ship **byte-verbatim (cmp-asserted)**; the 10
paintable `rgs_reference_main` (bytes asserted = `ser.set/class`, i.e.
gi-50's own pass-throughs) get one splice each:

Common to both rungs, per module (re-read from the emitted binaries, §3):
- a **fresh payload variable** of the module's own payload struct
  (`{uint,uint,float,float}`; ptr type reused; added to the SPIR-V 1.4 entry
  interface),
- word0 **armed** in the entry block, after the leading `OpVariable`s:
  `OpStore <word0> 0x5EA71E51`,
- an **injected `OpTraceRayKHR` immediately after the module's first
  radiance trace** (all 10 modules: the primary ray — cullMask
  `%uint_255`, missIndex `%uint_0`), every operand cloned by id so
  AS/flags/origin/direction/tmin/tmax are the live values, payload → the
  fresh variable,
- at every non-zero, non-scalar radiance write: load word0, compare, and
  `OpSelect` the written RGB to a paint colour — no new control flow, no
  `replace_all_uses`, alpha untouched. Where the predicate is false the
  original channels pass through **unchanged by construction**.

The one variable between the rungs:

| rung | injected trace | other stage | readback predicate | paint |
|---|---|---|---|---|
| `sentinel` (A) | cullMask → `%uint_0` (nothing intersects ⇒ **miss** runs) | this library's `ms_empty_main` — vanilla body is a bare `OpReturn` (verified) — patched with a guarded handshake: `word0 = (word0==ARM) ? MAGIC : word0` before return | `word0 == MAGIC` (0x3141C0DE) | **magenta** (10,0,10) |
| `sentinel-b` (B) | **all operands verbatim** (cullMask 255 ⇒ hits scene, the pipeline's own **unpatched CHS** writes the payload) | none patched | `word0 != ARM` (changed) | **cyan** (0,10,10) |

The miss modules are separately swappable — the layer keys on
`<hash>.<entry>.spv` (`swap_layer.c` ~194) and sync copies `*.spv` from the
rung wholesale, so the 10 patched `ms_empty_main` ride the same overlay.
`ab_launch_audit.py` will show their HITs.

Files: `dev/patch_sentinel.py` (tiers `miss`/`clone`/`ms`),
`dev/build_sentinel.sh` (assembles both rungs; `--install` parks), per-module
JSON reports inside each rung dir.

## 2. Design decisions worth defending

- **Clone-by-id, insert-after-site.** The injected trace reuses the live
  trace's own operand ids one line later, so every operand is defined and
  identical to a trace that demonstrably executes; H3 (wrong SBT/params)
  is engineered out everywhere except the one operand each rung varies.
- **Guarded select, no branches** — in both the miss handshake and the
  paint. A live miss (never armed) is behaviour-identical: `ms_empty_main`
  writes nothing vanilla, and the handshake writes back the loaded value
  unless it equals ARM. Collision risk priced in the patcher docstring
  (one-in-4e9 per miss, diagnostic rung only). The rungs are
  **identity-when-dead**: if the injected trace never executes, word0 stays
  ARM, every select passes the original value, and the frame must look
  exactly like `gi-50`. That is the built-in negative control.
- **Readback needs no dominance from the trace**: word0 is armed in the
  entry block (dominates everything), so a path that skips the injected
  trace reads ARM and paints nothing — no undefined reads, no partial-
  validity trap.
- **The 2 atomic reference permutations** (`40c6faab`, `ab7f1822`) ship
  unpainted pass-throughs, same as `probe-gi` (`50` §1): no radiance write
  to read back at; 0 recorded dispatches to date.

## 3. Validation — all pass

- `spirv-val` clean: 103/103 (`sentinel`), 93/93 (`sentinel-b`).
- Byte-verbatim asserted (cmp) for every unpatched file against `gi-50`;
  every patched file asserted to **differ** from its base.
- gi-50's reference files asserted byte-identical to `ser.set/class` before
  patching (the `ref=12(pass-through)` claim, re-proven not assumed).
- **Emitted-code re-read from the output binaries** (`39` §3.4), per
  module: trace count = vanilla+1; ARM present; rung A additionally: a
  cullMask-0 trace + MAGIC present + `OpSelect %uint` handshake in each of
  the 10 ms files; paint selects present. Coverage: 10/10 modules, 2–3
  writes painted each (23 total), skips are the known constant-zero
  early-outs and scalar hit-distance writes only.
- Hand-read on `1271d381`: the injected trace
  `OpTraceRayKHR %2187 %2181 %uint_0 %uint_1 %uint_1 %uint_0 … %25` sits on
  the line after its source; `%25` is the fresh payload var, on the entry
  interface; ARM store follows the entry block's `OpVariable`s; paint
  compares against `%uint_826392798` (= 0x3141C0DE) and selects
  (10, −0, 10). (−0.0 is `mod.const(0.0)`'s rendering; harmless.)
- MANIFEST: gi-50's line-1 provenance verbatim (`src_ser`, `ser_sha`,
  `ptq_sha`), renamed; `gi_refuse` recomputes both shas at every launch and
  the bases are untouched, so the contract holds unchanged.

## 4. PRE-REGISTERED interpretation table — read BEFORE the screen

Launch A (`sentinel`) first. B exists only if A is dark.

| on screen | meaning | and therefore |
|---|---|---|
| A: **magenta everywhere PT resolves** (whole frame, most scenes) | injected static trace executes; SBT miss-0 is this library's `ms_empty_main`; payload round-trips raygen→miss→raygen | **G-U5 PASSES in full.** Traced thickness is buildable exactly as `51` §7 sketches. `GOTCHAS`' flat "a second trace does not execute" narrows to the shadow pipeline / `sctrl`'s construction. Skip B. |
| A: magenta in patches / one family of scenes | the trace executes where those permutations dispatch | still a PASS; note which permutations (audit journal) before building on it |
| A: **no magenta anywhere** | one of: trace dead (H2), miss-0 mapping wrong, or payload does not round-trip | **launch B** — it removes the last two |
| B: **cyan on geometry, dark sky** | injected static trace executes and the unpatched CHS writes the payload; A's failure was the miss mapping/handshake, not the trace | G-U5 passes for the transmission feature (it needs hit distances, i.e. CHS/miss→payload — which B just proved). Ear-glow proceeds; A's miss-0 assumption gets one follow-up look only if a miss-written term is ever needed |
| B: cyan everywhere incl. sky | readback defect or payload aliasing — a state the identity design should make impossible | treat as build bug: pull `ab_launch_audit.py`, re-read the served bytes, do not interpret |
| A **and** B dark | a new static trace site does not execute in the reference pipeline either — H2 confirmed at the second family | **G-U5 FAILS.** Traced thickness is dead here. Fall back: `51` §7 step 1 (U3 channel) and screen-space B4, with `0d`'s caveats |
| anything else (wrong colour, flicker, vanilla-plus-artefacts) | serve/base mismatch | `ab_launch_audit.py` first; sync refuses loudly on stale bases, so check the journal before theories |

Frame-cost note: rung A's ray hits nothing (cullMask 0) — near-free. Rung
B's ray shades a real hit — one extra primary-ray CHS per pixel; expect a
measurable frame-time dip on B and ignore it, it is a probe.

## 5. Launch protocol (per `45`; settings STATED, house rule)

1. Settings before launch: PT on, `skinspec=sentinel`, `ser=class`,
   `shadowset=full-shadow`, standing PT switches (`ptbounce/ptrefl/ptmsggx`
   on, `ptclamp` on, `ptreg` off), RR state pinned and verified in the
   collect snapshot. Same contract as `gi-50` — sync refuses otherwise
   (`gi-needs-ser` / `gi-shadowset` / stale-sha paths).
2. `./dev/ab_launch_audit.py` after: expect HITs for 12 rgs_reference + 4
   rgs_restirgi + **10 ms_empty_main** (rung A), 0 rejects, manifest echo
   `sentinel …`.
3. One scene is enough; any PT scene with sky visible helps B's pattern.
   Capture S-something for the record, but the readout is binary and by eye.
4. Then `skinspec=sentinel-b` ONLY if A was dark.

## 6. Registration diff (NOT applied — main session applies)

`init.lua`, `SKIN_LEVELS`, after the `gi-50-bleed` entry:

    -- 55: G-U5 payload sentinel (diagnostic; read handoff/55 sec 4 BEFORE launching)
    { id = "sentinel",   label = "SENTINEL: injected-trace probe A -- magenta = trace runs" },
    { id = "sentinel-b", label = "SENTINEL-B: probe B (only if A dark) -- cyan = trace runs" },

`sync_settings.sh`: no change (rungs are served by name; the raygen guard
reads the MANIFEST fields, which carry gi-50's values verbatim).
`Makefile`: no change.

## 7. Confidence

| claim | confidence |
|---|---|
| both rungs valid SPIR-V, byte-verbatim outside the 10+10 patched files | **certain** — cmp + spirv-val in the build, re-runnable |
| the splices carry exactly the designed instructions | **high** — re-read from the emitted binaries by script and by hand |
| the rungs are behaviour-identical to gi-50 if the injected trace is dead | **high** — armed-word + guarded-select construction; not yet proven on screen |
| the ms files will be served by the layer | **high** — `<hash>.<entry>.spv` is the layer's own keying; sync copies `*.spv`; not yet observed in a journal |
| the injected trace executes | **unknown — the launch decides. That is the point.** |
