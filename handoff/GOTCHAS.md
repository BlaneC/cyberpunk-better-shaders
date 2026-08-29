# GOTCHAS — the rules this repo paid for

Every rule here cost at least one wasted session. Read this before starting any
new shader-level feature. `19-STATUS.md` says what is true right now; this file
says how to avoid re-learning what is already known.

---

## Method

1. **Select by dispatch, never by constants.** Picking modules because they
   contain a plausible constant or a plausible name has produced a wrong family
   every single time. Find what actually executes first (`10`, `12`, `15`).

2. **A swap HIT is not execution.** `{"ev":"module","swap":"HIT"}` only means
   the module was created and substituted. The proof of execution is a
   `{"ev":"dispatch",...,"swapped":1}` line in `~/callisto_swap.jsonl`. 70
   modules were "confirmed" as loaded for weeks while 54 of them never ran.

3. **After locating a splice site, sweep for structural siblings, and count
   how many places consume the value you spliced at.** This failed three times
   in the AgX work alone: an HDR permutation patched while SDR ran a sibling;
   eight more permutations invisible to the first detector; one encode branch
   patched out of seventeen that phi from a common source. Permutations of the
   same logical pass are separate DXIL blobs with separate identities.

4. **Write detectors against the mode-independent half of a signature.** A
   permutation compiled for known settings has the variable half constant-folded
   away — a mode ladder, a colour matrix, a PQ curve may simply not be there.
   `dev/find_tonemap_gens.py` (narrow, finds 2) versus `dev/find_lut_gens.py`
   (relaxed, finds all 10) is the worked example.

5. **A splice site is a contract about a *space*, and the contract is
   unwritten.** A structural detector proves a site's shape, never what it
   holds. Enumerate every constant 3×3 in the module and identify each against
   published colour matrices before writing into it — that is a one-command
   check, and skipping it produced pink/cyan neutrals across the whole game
   (`18`).

6. **Prove neutrality offline before launching.** Round-trip greys through the
   full chain in Python; check id substitution counts; `spirv-val` every
   variant. Nearly every bug in `18` was caught this way rather than on screen.

7. **Don't retry `14` §2's dead ends.** In particular `14` §2.4 ("replay
   segfaults") is **false**: offline capture replay works with
   `NGFXPROBE_STRIP_ALLOC=3`. See `dev/prov_map.py`'s docstring for the recipe.
   Offline replay means a whole class of question needs no game launch.

8. **Ask whether the engine already exposes it.** `16-ENGINE-HAIR-BRDF.md` is
   the cautionary tale: a large hair-BRDF effort ran for sessions before anyone
   checked, and the renderer ships a live-tunable three-lobe hair BRDF as
   CVars. Search the exe's CVar strings before writing a patcher — and
   search for the feature you are *actually* asking about: `20`'s exe audit
   was exhaustive on transmission (0 hits, correctly) while missing the
   `RayTracing/Reflection` CVar group sitting next to it, which is the
   engine-side answer to half of the question that document was asked.

9. **State claims at the confidence you actually have.** Several confident
   assertions in `11`–`16` were later retracted (Marschner, "GlobalLight = GI",
   `PT_` = path tracing). `19` §4 lists them. Say "inferred from naming" when
   that is what it is.

10. **A structural guard that can be satisfied by the wrong structure is not
    a guard — and finding the *shape* you looked for does not mean you are at
    the right *place* in the pass.** The SDR AgX splice passed a "is this one
    branch of N?" check, swept its siblings, validated, dispatched and changed
    pixels — while sitting above the game's own tone curve, which then ran on
    AgX's output. The check was satisfied by three unrelated phis. The fix was
    to stop anchoring on a plausible constant (an sRGB threshold that appears
    seventeen times) and anchor on the **runtime gates that bracket the
    segment**, which is the only trait every permutation shares. Before
    believing a site: walk the module from the dispatch's write backwards and
    say what is upstream and downstream of your splice. (`21`)

11. **A pass's output buffer is a contract too.** Rule 5 is about the space a
    splice site holds; this is about what happens to the value after the
    write. Before designing what to write, know how the buffer is composited —
    added, lerped, or replaced — because that sets the ceiling on what the
    edit can look like. `20` §5b planned `F·reflected + (1−F)·refracted` into
    a buffer that is most likely *added* over an already alpha-blended glass
    pixel, where the same maths produces a ghosted double image instead of
    refraction. The channel you assume is a weight may not be one: that
    buffer's alpha is a depth.

12. **A detector must run before any pass that rewrites uses.** The patchers
    apply their edits at the very end (`apply_edits`), but `replace_all_uses`
    rewrites `mod.lines` *immediately* — so between the two, the module names
    ids whose defining instruction does not exist yet. Any later pass that
    walks definitions backwards dead-ends there, and dead-ends **silently**:
    it reports "I could not find my anchor" and emits nothing, which from the
    chair is identical to the feature not working. Tier-4 hit exactly this —
    its detector finds the diffuse image write by walking back to a Disney
    diffuse scalar, and Tier-1's c1 rewrite had already pointed that chain at
    a pending id (`30` §5). Order every read-only detector ahead of every
    rewriting emitter, and say why in the code, because the constraint is
    invisible at the call site.

## Mechanics

- **Env vars do not reach the game.** Proton/Steam launch layering eats them.
  Use flag files plus `CALLISTO_LOG`; the layer reads `CALLISTO_SWAP_DIR`,
  `CALLISTO_LOG`, `CALLISTO_SWAP_DISABLE`, `CALLISTO_SWAP_QUIET`,
  `CALLISTO_DUMP_DIR`, `CALLISTO_DUMP_MATCH` (see `swap_layer.c` header).
- **Clear GLCache + shadercache after any swap change**, or the pipeline cache
  serves the pre-swap module and the change silently does nothing.
  `install_agx.sh` / `sync_settings.sh` already do this; ad-hoc installs do not.
- **`~/callisto_swap.jsonl` gets clobbered.** Several Proton helper PIDs open
  the layer and each `log_open` truncates the file, so the game's own log can be
  overwritten by a helper's. If a log looks impossibly short, that is why.
- **The patchers take `.spvasm`, not `.spv`.** `spirv-dis` first, or you get
  `ValueError: max() iterable argument is empty` from deep inside a patcher.
- **Compute libs are SPIR-V 1.3, RT modules 1.4**; target env is auto-detected
  per module. Do not hard-code.
- **Dominance is never assumed.** Everything before the first control-flow
  instruction dominates the function; anything else must be proven. `OpPhi`
  must be at block top. Patchers compute reachability/dominators and skip
  sites they cannot prove (`dev/patch_shadow_brdf.py` has the reusable code).
- **Splice ordering matters**: referencing an id defined *after* the splice
  point is an undefined-id validation error, not a runtime bug.
- **Scale before a clamp, never after.** A marker or gain spliced past a
  module's own `NMin`/`NMax` can push an fp16 store to `inf`; the same edit one
  instruction earlier stays bounded by the clamp the shader already has.
- **RT payloads: SPIR-V 1.4 requires every referenced global in
  `OpEntryPoint`'s interface list.** A new `RayPayloadKHR` variable that is not
  registered there fails validation. Usually you need none —
  `ee6d252e090adc74` already declares four payload variables of one type, all
  in the interface; the constraint is *liveness*, so an added trace goes before
  the one whose payload is still being consumed.
- **Ray flags carry an occluder-material discriminator.** `CullOpaqueKHR`
  (0x40) and `CullNoOpaqueKHR` (0x80) are evaluated per hit during traversal,
  so "the ray cannot know what it will hit" is only true of *shading*, not of
  opacity. `25` §4 concluded no such signal existed and nearly cost the fix;
  the shadow rays set neither bit, and no Force(Non)Opaque either, so geometry
  participates by its authored opacity and alpha-tested hair can be separated
  from solid props with a second trace.
- **A second trace can reuse the first one's payload — if you prove the
  payload's shape.** The shadow payload is `OpTypeStruct { float }` and every
  access chain on it indexes member 0, so there is nothing to clobber and no
  new `RayPayloadKHR` global (hence no `OpEntryPoint` interface edit) is
  needed. Prove it per module; a payload with a second member makes the same
  splice silently destructive.
- **`SkipClosestHitShader` is what makes a trace an occlusion ray.** Flags
  `16` (bare CullBackFacing) looks like a sibling of flags `28` and is not:
  without 0x08 the closest-hit shader runs and the payload carries shading,
  not a distance. Sweeping "everything that culls back faces" into one patch
  set would have corrupted `rgs_diffuse_main` and `rgs_importance_main`.
- **Ray origins carry a sign convention.**
  `rgs_reflection_transparent_main` builds its origin as `P − D·ε`, pulled back
  along the view ray to the *outside* of the surface. Reuse that for a
  transmitted ray and it self-hits the surface at `t ≈ ε` —
  `CullBackFacing` does not save you, because from outside the front face is
  front-facing.
- **The probe logs descriptor bindings for compute dispatches only.** RT
  stages never appear in a prov log (`capA_prov.jsonl`: 2920 events, 114
  compute modules), so `dev/prov_map.py` cannot name the writer of an RT
  pass's output — and its report loop only lists images that *have* a compute
  writer. Images read by compute with no compute writer are the RT/raster
  outputs; that set is the starting point for naming one.
- **`trace_rays` attribution is unreliable** — `vkDestroyPipeline` never clears
  the rtpipe table, so reused handles report a stale raygen. Use `pipe_stage`.
- **`ls <glob> | wc -l` under `nullglob`** counts the whole directory.
- **A failed `spirv-val` can leave a stale `.spv`** for the installer to pick up.
- **The live pixels are shaded in compute**, not in the RT passes; RT produces
  samples (`07`). Live PT shades in the closest-hit shader, not the raygen
  (`06`). This explains a long run of null results.
- **An overlay serves the FIRST file it finds for an id** (`load_swap()` walks
  the overlay list in order, then the base `swaps/`). So two features that
  patch the *same* module cannot be two overlays — the second is dead, with no
  error anywhere. Either pre-build the combinations (`dev/build_ptq.sh` builds
  the 7-way `{r,c,b}` matrix and `sync_settings.sh` materializes one into
  `swaps.ptq/`), or fold them into one build.
- **Every overlay outranks the base `swaps/` dir**, which is where `skinray`
  installs its patched reference raygens. An overlay that touches
  `rgs_reference_main` therefore silently *un-patches* skinray unless it also
  ships a variant built on top of it — hence `ptq/<combo>/skin/`.
- **An empty overlay directory still reads as `"enabled": 1`** in the layer's
  log. Write the `<name>.disable` flag when a feature is off, or the status
  page reports an overlay that cannot do anything.
- **Git: do not commit unless asked.**

## Where things are

| what | where |
|---|---|
| module dump (3005 `.spv`) | `~/callisto_dump/` |
| dispatch/swap log | `~/callisto_swap.jsonl` |
| installed swaps | `$CALLISTO_INSTALL_DIR` (default `~/.local/lib/callisto`)`/swaps` |
| game | `$CALLISTO_GAME_DIR` (default the SteamLibrary path in `dev/install_agx.sh`) |
| CET mod | `<game>/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/` |

---

### Materializing a swap set with plain `cp` evicts the shader cache every launch

`sync_settings.sh` keys its cache-eviction stamp on a hash of `stat -c '%n %s
%Y'` over the served `.spv` files — name, size, **mtime**. Every overlay that
picks one of several parked variants (`shadowcull.set/`, `ptq/`, `swaps.prehunt/`)
re-copies its files into the served dir on every launch, and a plain `cp -f`
stamps a fresh mtime each time. The hash therefore changed on every single
launch, the stamp never matched, and the pipeline caches were cleared *every
time* — a full shader recompile per launch, for no reason.

Fix: `cp -pf`. mtime comes from the parked source, which is stable, so an
unchanged selection hashes identically next launch. Verified: same selection
twice → "caches kept"; selection changed → "caches cleared".

If you add another parked-variant overlay, use `cp -pf` or you silently
reintroduce this.

### `NoOpaqueKHR` on a ray means the geometry is OPAQUE

`17` §2 records the PT visibility ray using flags `10 = NoOpaqueKHR |
SkipClosestHitShader`, described as "so anyhit runs and hair alpha-tests".
That was read as evidence hair is non-opaque in the BLAS. It is evidence of the
opposite: `NoOpaqueKHR` **forces** geometry non-opaque, and a ray only needs to
force it if the geometry is opaque by default.

This cost a full build-and-launch cycle (`25` §9): the opacity-split shadow ray
gave ray B `CullOpaqueKHR`, expecting it to see hair, and it saw nothing.
Rays that force a property tell you what the geometry is *not*.

### A launch-gated selector must show what is RUNNING, not just what is selected

Cost a whole session on 2026-08-28. The CET selector read "Uncull everything";
the frame was `m112`. Both were true — `sync_settings.sh` had materialized
`m112` at launch, and the in-session change to `full` was written to
`brdf_params.txt` for the *next* launch. Reloading a save cannot help: the
pipelines were compiled at startup, and the layer only substitutes SPIR-V in
`vkCreateShaderModule`.

The running set is now in the widget's **label** (`Shadow-ray build [running:
m112]`), not in the tooltip. A tooltip you have to hover is not where anyone
looks when the picture is wrong. `warnLine()` additionally shouts when the
selector and `status.want_shadowset` disagree at session start, which means the
game was launched outside the Steam launch options and the sync never ran.

Diagnosing which set actually ran: the parked sets have distinct per-file byte
sizes, and the layer logs `{"ev":"swap_load","file":...,"size":N}`. The eight
`rgs_restirgi_*` sizes are the discriminator — the `rgs_shadow_main` sizes
collide between mask variants (`m6` and `m112` are identical there).

### nativeSettings `removeSubcategory` corrupts the tab's key order

It ends with `data[tab].keys[getIndex(keys, subPath)] = nil` — a hole, not a
`table.remove`. After that `#keys` is undefined, so any later
`addSubcategory(path, label, 1)` (which does `table.insert(keys, 1, …)`) can
silently orphan the rest of the tab. A `pcall` does not save you; nothing
throws. Do not build "live" panel elements by remove/re-add. Bake the volatile
value into a label at registration time instead.

### Never land two independent visual features between two observations

Cost about four turns of misdiagnosis on 2026-08-28. The PT tier-1 overlays and
the shadow-ray variant matrix shipped in the same session. When the hairline
looked wrong afterwards, "the shadow fix regressed" and "a new PT feature
changed hair" were indistinguishable from the screen, and the shadow patcher —
which was innocent — absorbed the blame twice.

What settled it was per-launch provenance, not reasoning: the layer logs
`{"ev":"log_open","pid":N}` per process and `{"ev":"swap_load","file":…,"size":N}`
per swap, so every launch's exact served payload can be fingerprinted and
compared against the launches that were known good. Keep `~/callisto_swap.jsonl`
— it is the only record of what was actually in the frame on a given day.

Corollary: `brdf_params.txt` is not that record. It holds the request, it is
rewritten by CET during play, and a 10-entry selector is easy to nudge by
accident (the `shadowset` value moved from `full` to `m6` mid-session with no
one meaning to).

### Do not generalise a cull mask from one sampled module

The shadow-ray bisect was built by reading the mask off one module
(`b80f16ff.rgs_shadow_main` → `OpSelect(86, 38)`) and assuming all 18 matched.
They do not: `rgs_restirgi_*` uses `OpSelect(87, 39)`. The extra bit is class 1,
and every bisect variant dropped it, so two launches produced a result that
looked logically impossible (`25` §9).

Enumerate the operand across every patched site before designing a bisect — 28
sites, seconds of work. The same applies to ray flags, tMin and SBT indices:
one module's constants are a sample, not the schema.


### The layer log cannot tell two swaps apart by size when only a constant differs

Binary SPIR-V stores `OpConstant` in a fixed-width instruction, so changing the
*value* changes no byte count. The layer logs `{"ev":"swap_load","file":…,
"size":N}` — name and size only — so six of the shadow-ray variants
(`m1/m2/m4/m6/m16/m32`) are mutually indistinguishable in the log, as are
`m118/m119`. Attributing an on-screen result to one of them from the log alone
is impossible, and a result was once credited to a set (`ctrl`) that had never
been launched at all.

`sync_settings.sh` now writes `~/callisto_launches.log`, one append-only line
per launch carrying the **content** hash of the served overlay. Use that, not
byte sizes, to attribute any future observation.

### Verify the mechanism before building the matrix

Ten shadow-ray variant sets, a CET selector, two handoff docs and six launches
were built on "the second trace works". It was never confirmed — the control
that would have confirmed it was designed, described as mandatory in three
successive messages, and then never actually run, because new variants kept
getting staged ahead of it. The whole branch is now suspect (`26` §7a).

If a plan has a step whose failure invalidates every later step, run that step
first and confirm it from the launch journal before building anything on it.

- A *neutral* control cannot validate a mechanism. `ctrl` spliced in a second
  ray identical to the first, so "looks vanilla" was equally consistent with
  "the splice works and is correctly neutral" and "ray B never executes". Build
  the control so that a working mechanism produces a **visible** change: `sctrl`
  makes ray B unculled, which must reproduce `full-shadow` exactly.
- Ray flags are per-ray, not per-geometry. Any `28 -> 12` edit unculls
  *everything the ray can reach*, so no subset of trace sites can separate "the
  hair loses culling" from "the flat props lose culling". Only the `CullMask`
  can, and using it means a second ray.
- A reported regression is only attributable if exactly one variable moved
  **and** the launch is fingerprinted. The "PT tier-1 hair regression" was
  neither, and did not exist -- it was the shadow set changing underneath.
- **A second `OpTraceRayKHR` spliced into a raygen shader does not execute** in
  this game under vkd3d-proton. The edit disassembles correctly, `spirv-val`
  passes, the swap is served -- and the result is bit-for-bit vanilla on screen.
  Proven by `sctrl`, whose second ray was unculled with the same mask, so a
  working splice *had* to reproduce `full-shadow`. Before building anything on
  a second trace, prove the trace runs: write a sentinel into the payload from
  a miss shader and read it back.

### A reading can land on the wrong sibling too, not just a patch

`GOTCHAS #10` was written about *patches* applied to one of N structural
siblings. The MS-GGX blocker (`dev/MS_GGX_NOTES.md` §2) was the same failure in
a **reading**: `spv_0170` carries two structurally identical GGX evaluators —
punctual (`%12540`, lines 8558-8613) and area/tube (`%12539`, 8623-9998),
selected by `(flags & 2) == 0`. They share every formula verbatim, so the
disassembly of the wrong one looks exactly as correct as the right one. Six
months of "the lobe loses 60-75% of its energy" came from integrating the area
arm, whose "NoL" is a sphere/tube illuminance factor and whose spec weight
carries Karis's `(alpha/alpha')^2` sphere normalization.

The tell was available the whole time and was not looked for: the area arm's
spec weight `%7581 = clamp(radius*100,0,1) * ...` is **zero at zero radius**.
A block that renders no specular for a point light is not the point-light path.

- When a block reads as implausible, check for a sibling **before** theorising
  about the block. Search for the formula's own constants (`0_25`, the Schlick
  pair `5_55472994` / `-6_98316002`) across the whole module and count the
  hits; two hits means two evaluators.
- An anomaly of exactly 2x or exactly 4x is usually a missing or doubled
  factor, not a discovery. Here it was two: the wrong arm, and an extra `NoL`
  applied to a lobe the shader never multiplies by `NoL`.
- **Absolute normalization is often avoidable.** The blocker was framed as
  "`comp` needs `1/E_ss` in absolute terms, so the normalization must be
  right." Defining the compensation against the lobe's *own* alpha->0 limit
  makes any constant scale error cancel exactly. Before chasing an absolute,
  check whether the feature actually needs one.

---

### One knob, two defaults, in two files that never see each other

`skinspec` has a default in `init.lua` (what the CET selector shows) and a
default in `sync_settings.sh` (what is served when `brdf_params.txt` is
missing or has no such line). They were `strong` and `off` respectively for
one commit, which produces a specific and very confusing symptom: the settings
UI reads "Strong" while the shader served is the unpatched control, on exactly
the launches where CET has not yet written the file — a fresh install, a
wiped mod folder, or a CET load failure. The UI is not lying about what it
will request; it is lying about what is running.

This is the same shape as the `hair=off` accident (`27` §8): a value read from
one file, defaulted in another, with nothing comparing the two.

- The status/selector mismatch warning (`init.lua`) is the thing that catches
  this at runtime, which is why it now compares the **level**, not just
  on-vs-off. `subtle` running under a selector reading `extreme` is the same
  bug and just as easy to stare past.
- When adding a launch-gated setting, grep for every file that names it and
  make the defaults agree in the same edit. Two files, one grep.
