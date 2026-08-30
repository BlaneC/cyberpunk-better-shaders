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
    a pending id. (Tier-4 itself was later removed — `39` — but this rule
    outlived it and is general.) Order every read-only detector ahead of every
    rewriting emitter, and say why in the code, because the constraint is
    invisible at the call site.

13. **Existence is not addressability. Prove you can *reach* a signal before
    designing anything that consumes it.** `29` A4 R3 wanted the engine's own
    skin back-depth target for real per-pixel thickness. The pass was found
    (depth-only, 1280x720, uniquely `clear=1.0` — reverse-Z for "keep the
    farthest fragment"), and it was proven to **run in RT Overdrive** with 25
    indexed draws, which is the question rule 5 tells you to ask. It is still
    unusable: in a bindless heap the resource is named by an *index*, and that
    index moved from 73203 to 503350 across two captures **29 seconds apart in
    the same session**, with the offset from the consuming shader's
    push-constant base moving -10322 -> -955/-15230 (not even single-valued in
    the second capture). A baked constant would multiply whatever resource
    landed in that slot into the light.

    So the go/no-go for any new input has three parts, not one: does it exist,
    does it run, and **is its address stable**. Answer the third before
    writing a detector, because a route can pass the first two convincingly
    and still be dead. `39` §6 carries the evidence; it is closed, not
    deferred, and the only thing that reopens it is an engine-side binding.

14. **Before importing a sampling technique, check which of its preconditions
    this renderer actually meets.** Cranley-Patterson randomizes a *low-discrepancy
    point set*; on a plain LCG `frac(u+c)` is a measure-preserving bijection and
    provably changes nothing — and there is no Sobol/Halton/Owen sequence anywhere
    in the reference raygens. Heitz & Belcour's blue-noise error distribution comes
    from the *mask*, not from the rotation, and it additionally requires surrendering
    the per-pixel seed: a white per-pixel seed re-randomizes each pixel and destroys
    the mask's spatial structure downstream, so the gain needs the seed hash
    **deleted**, not offset. A named technique from a real paper, correctly cited,
    can still be a no-op on this renderer. The check is cheap — model the shader's
    RNG in forty lines of numpy and measure it (`dev/validate_sampler_rng.py`)
    before writing a patcher. (`37`)

## Mechanics

- **`ngfx-replay` hanging at 0% CPU is usually a dialog, not a hang.** It opens
  a `zenity` window about `VK_KHR_external_semaphore` / `VK_EXT_present_timing`
  incompatibility and blocks on it forever, which under a headless or
  background invocation looks exactly like a deadlock. Add
  `--no-block-on-incompatibility` to the `15` §0 command. `NGFXPROBE_STRIP_ALLOC=3`
  is still mandatory or you get a SIGSEGV inside `libnvidia-glcore`.
- **In `probe_layer.c`, never name anything `b`.** `LOGF` declares its own
  `char b[8192]`, so a parameter called `b` shadows it and the buffer is
  silently passed where the format string expects a number. Build with
  `-Wformat` — that is what caught it. The file now carries a comment saying so.
- **Widening `prov_scan`'s offset window needs two fixes, not one.** A negative
  low bound added to an *unsigned* push-constant base wraps to ~4e9 and walks
  the heap read off the buffer (SIGSEGV); compute the candidate in `int64_t`
  and reject `< 0` before casting. And the old `prov_lookup` was an O(n) linear
  scan over ~19k descriptors, which a 7x wider sweep turns quadratic and the
  replay unusable — it now goes through an open-addressed hash that preserves
  first-insert semantics.
- **`mod.uconst()` has no pending-declaration cache; `mod.const()` does.**
  `const()` memoises in `self.fconst`, so asking twice for the same float
  returns the id and `None` — no second declaration. `uconst()` only scans
  `mod.lines`, which does **not** yet contain the constants the current pass
  is about to append, so the second call hands back the same id *and* another
  declaration of it. Any emitter that can run more than once per module (one
  splice target per light-carrying edge, say) then fails `spirv-val` with
  `Id N is defined more than once`. Memoise at the call site. This only shows
  up in the multi-target minority of modules, so a single-module test passes
  and the ladder build is what catches it.
- **Parallelise the ladder with `CALLISTO_JOBS`.** `build_into` patches its 77
  modules with `xargs -P` (default `nproc`); they are independent processes
  sharing only the output directory and each writes files named after its own
  module. A 29-set ladder went 31 min -> 6.5 min on 24 cores. `spirv-dis`
  stays **sequential on purpose**: it writes into `dev/disasm/compute`, which
  every set shares, so racing sets would interleave writes into one file.
  `CALLISTO_JOBS=1` restores the old serial order when a failure needs
  reading in sequence.
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
- **`grep -r` over `~/callisto_dump` silently returns 0 for strings that are
  there.** The extension census in `38` first read as "BDA is absent" —
  `grep -rl physical_storage_buffer ~/callisto_dump/` gave **0** while
  `strings` on any single module showed `SPV_KHR_physical_storage_buffer` on
  line 2. Run it as `cd ~/callisto_dump && grep -la <str> *.spv | wc -l`, which
  gives 3225 of 3273. The failure mode is the dangerous one: a census that
  returns zero looks like a finding, and "no module declares X" is exactly the
  shape of claim these documents build on.
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

---

### A byte diff is not coverage — a module can be "patched" with zero sites

`27` §8.3 claimed all 77 modules carried the Tier-3 gloss, including the two
GI resolvers. They did not: the class gate was rejected at **every** splice
site in both, and what made them "differ from the baseline" was **48 bytes of
`OpConstant`** that no instruction consumed. The knobs are emitted by
`mod.const()` before any site is examined, so a pass that splices nothing
still changes the file. Every check the build ran — `spirv-val`, "each rung
differs from `off`", "each rung differs from the rung below", "coverage lists
match" — passed on that delta, for two years' worth of builds, while the whole
skin BRDF was absent from bounce-lit skin (`42`).

- **Assert the site count, not the file hash.** `patch_compute_skin.sh` now
  reads the per-module JSON reports and aborts on any non-empty `skipped_dom`
  or any module landing zero `c1` sites. A byte diff answers "did the file
  change"; only the report answers "did an instruction get spliced".
- A `skipped_*` list that nothing ever reads is the same bug one level up.
  Every skip counter this repo emits should be fatal by default, and loud
  where it is legitimately non-zero.
- The corollary for the ladder: **two rungs differing does not mean the knob
  reached the shader.** If both rungs' deltas are their own constants, the
  A/B compares nothing and looks exactly like a knob that does not matter.

### The value a shader tests is not always the value the shader computed

dxil-spirv guards the material-class fetch behind a bounds test and merges it
out with `OpPhi %uint %uint_0 <skipped> <shift> <fetched>`. Below that merge
the **shift dominates nothing** and the **phi dominates everything** — and the
shader's own class tests read the phi. `find_class_shift` anchors on the
`>>5` reached through an `OpImageFetch`, which is structurally the fetched
value and can never be the phi, so in the two GI resolvers it returned an
anchor that could not reach a single site.

- When a gate is rejected everywhere, look one block **down**, not for another
  fetch. The dominating form of the value is often already there, and it costs
  no instructions (compare the hair patcher, which refetched the class and
  hoisted it — correct, and more expensive than it needed to be).
- Guarded-fetch phis are safe to gate on: the guard's other operand is
  `%uint_0`, which is not skin, so a pixel that skipped the fetch gates off.
  Check every operand anyway — a phi mixing in an unrelated uint would give a
  gate that fires on something that is not the material class, and no offline
  check catches that.
