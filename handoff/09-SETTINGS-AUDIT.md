# 09 — Settings: why the page can't be trusted, and the plan

Written after the 2026-08-26 null result, where an A/B session produced
screenshots in which only one of five effects was actually running. The cache
bug was the proximate cause; this document is about why nothing *told us*.

The settings page is not buggy in one place. It is five toggles encoded five
different ways, written by two programs with different schemas, read by two
launch gates with different semantics, applied through a shader cache that can
veto all of it, with no path by which the result is ever reported back. Each
piece is individually defensible. Together they mean **a switch reading "on"
is not evidence of anything.**

---

## 1. Where state actually lives

| # | State | Location | Encoding | Written by | Read by |
|---|---|---|---|---|---|
| 1 | `tier` | `~/.local/lib/callisto/swaps/*.spv` | file presence | `sync_settings.sh` | layer |
| 2 | `skinray` | **the same 2 files** | file presence | `sync_settings.sh` | layer |
| 3 | `hair` | `~/.local/lib/callisto/hair.disable` | negative flag | `sync_settings.sh` | layer |
| 4 | `shadowcull` | `~/.local/lib/callisto/shadowcull.disable` | negative flag | `sync_settings.sh` | layer |
| 5 | `kernel` | `<game>/red4ext/plugins/CallistoSSS/disable.flag` | negative flag, *different dir, different name pattern* | `sync_settings.sh` | RED4ext DLL |
| 6 | `rho_f`…`m_r` | `brdf_params.txt` | values | `init.lua` | `regen_and_clear.sh` **only** |
| 7 | layer on/off | `CALLISTO_LAYER_DISABLE` | env | Steam launch options | Vulkan loader |
| 8 | swap dir, overlay list, passthrough | `CALLISTO_SWAP_DIR`, `CALLISTO_OVERLAYS`, `CALLISTO_SWAP_DISABLE` | env | Steam launch options | layer |
| 9 | **whether any of it applied** | *nowhere* | — | — | — |

Five encodings for one concept. Two of them (#1, #2) are the same two files.
Row 9 is the whole problem.

---

## 2. Confirmed defects

Each verified, not inferred.

**D1 — `skinray` is a dead toggle.** In `sync_settings.sh` the skinray block
deletes the raygens, then the `tier` block immediately copies them back from
`swaps.prehunt/`. Reproduced in a sandbox: `skinray=off` leaves 2 raygens
installed. `regen_and_clear.sh` has the same bug by a different route —
`sync_install`'s `rm` + re-copy runs after the skinray block. The switch has
never done anything except when `tier=off` also happened to be set.

**D2 — the master switch is not master.** `tier=off` empties `swaps/` but does
not touch `swaps.hair/`, and `patch_compute_hair.sh:44` splices the Callisto
tier-1 skin `c1` into the hair overlay (`--with-tier1`). So "Callisto BRDF
enabled = off" leaves the Callisto skin BRDF running on all 70 compute
resolves. Verified in sandbox: `tier=off` → `hair.disable` absent.
`00-ARCHITECTURE.md` §5's claim that all-toggles-off is "bit-exact vanilla" is
true only if you know to also turn hair off.

**D3 — six sliders that do nothing.** `rho_f`, `n_f`, `m_f`, `rho_r`, `n_r`,
`m_r` are baked in by the patcher, which only `regen_and_clear.sh` runs. The
shipped launch line runs `sync_settings.sh`, which ignores them. The installed
`init.lua` shows all six anyway.

**D4 — the release UI is a state-destroying writer.** `release/…/init.lua`
knows only `kernel`, and its `saveParams()` writes a one-line file. Ship it and
the first boot silently truncates `brdf_params.txt`, wiping tier/hair/skinray/
shadowcull — which `sync_settings.sh` then reads as its defaults (all on),
regardless of what the user had set. Two writers, one file, different schemas,
no version field. Not yet live: the dev `init.lua` is what's installed.

**D5 — the pipeline cache can veto every toggle.** A cached pipeline never
re-creates its shader module, so the layer never sees it. Only visible on the
GLCompute resolves (RT raygens rebuild every launch) — i.e. precisely where
every visible effect lives. Fixed 2026-08-26 by the cache gate in
`sync_settings.sh`, but the *class* of failure survives: any state change that
doesn't move the stamp is still invisible.

**D6 — the release tree can't install.** `release/vulkan/` ships no swaps at
all, so `install.sh:87` (`cp -f "$SRC/vulkan/swaps/"*.spv`) fails, and
`swaps.hair/`, `swaps.shadowcull/`, `swaps.prehunt/` are never packaged.

**D7 — two launch gates, and the docs name the wrong one.** `init.lua:3` tells
the reader that `regen_and_clear.sh` runs at launch and regenerates swaps. The
shipped line runs `sync_settings.sh`, which does neither.

**D8 — env vars silently outrank the UI.** `CALLISTO_LAYER_DISABLE`,
`CALLISTO_SWAP_DISABLE`, `CALLISTO_SWAP_DIR`, `CALLISTO_OVERLAYS` each override
the settings with no trace in the page. `CALLISTO_LAYER_DISABLE=1` additionally
bypasses the cache gate — the documented A/B method was itself the trap.

**D9 — the log resists verification.** No timestamps, appended across launches,
so "70 resolve hits" is a cumulative number that says nothing about *this* run
without splitting on `log_open` by hand.

**D10 — the one honest toggle is mislabelled.** `kernel` is checked per texture
upload, so it is the only setting that could apply without a relaunch. The UI
says "applies on next game launch."

**D11 — the visual confirmations were never isolated.** The hair before/after
evidence in `README.md`, and `handoff/README.md`'s "all four effects confirmed
on screen", were shot with **Ultra Plus** installed. Its hair ray-bounce
settings were not isolated, and its contribution was attributed to this mod.
With other mods removed, the hair BRDF produces no observable change. So the
package went to "confirmed" on the strength of another mod's output, while the
static evidence (spirv-val, site counts, 0 dead ids) that *did* hold was only
ever evidence that the code was well-formed — never that it did anything.
Reported by the user 2026-08-26 after deliberate isolation.

---

## 3. Root causes

Three, and every defect above is downstream of one of them.

1. **Toggles are encoded as side effects, not as declared state.** Each setting
   runs its own `rm`/`cp`/`touch` against a shared directory. Two settings
   touching the same files means order decides the outcome — that is exactly
   D1, and it is invisible in review because each block reads fine alone.
2. **The same state is duplicated with no single source.** Two `init.lua`
   copies with different schemas (D4), two launch gates with different
   semantics (D7, D3), five encodings for one concept (§1).
3. **The loop is open.** Nothing ever compares intent against what happened.
   The page renders `brdf_params.txt` — the *request* — and calls it status.

---

## 4. The plan

Ordered by trust-per-unit-work. Phase 3 is the one that answers "I can never
trust my settings page"; do it even if the rest slips.

### Phase 1 — one resolver that materializes, never mutates

Kills D1, D2, D8, and the ordering-bug class permanently.

- `brdf_params.txt` is the only input. `sync_settings.sh` is the only resolver.
- The resolver **builds the whole install state from scratch** each launch:
  `rm -rf ~/.local/lib/callisto/active/`, then populate it. No per-setting
  `rm`/`cp` against shared dirs, so no ordering. The layer serves exactly
  `active/` and nothing else — delete overlay dirs and `*.disable` from the
  runtime path entirely.
- Skin `c1` and hair are spliced into the *same* 70 modules, so they can't be
  separated by directory at runtime. Pre-build the combinations at patch time —
  `variants/skin+hair/`, `variants/hair/`, `variants/skin/`, plus empty — and
  have the resolver select one. ~5.6 MB per variant, ~22 MB total. Now the two
  switches can each mean what they say.
- `skinray` becomes an ordinary part of that same materialize step.

### Phase 2 — one writer, versioned schema

Kills D4, D7.

- Delete `release/…/init.lua`. One `init.lua`, with a `RELEASE_UI` boolean if
  the release really must show fewer controls.
- Add `schema=2` as the first line. Read-modify-write: **never write a key you
  did not parse** — an old writer must not be able to drop new keys.
- Fix the `init.lua` header to name the gate that actually runs.

### Phase 3 — close the loop (the trust fix) — **DONE 2026-08-26**

Kills D9, D10, and the *reason* D5 went unnoticed for a full session.

Shipped slightly differently from the sketch, because the launch options run
`sync_settings.sh` and `%command%` as *separate* commands — the script cannot
export env into the game, so `CALLISTO_STATUS` could not be the bridge without
making every user edit their launch options.

- The layer writes `~/.local/lib/callisto/last_run.json` next to its own `.so`
  (found via `dladdr`, no env needed): overlays live, passthrough state, and
  hit counts split into resolve / shadow / raygen / GI / failed. Rewritten on
  every hit and via `tmp`+`rename`, so a crash still leaves an accurate file
  and a reader never sees a half-written one.
- `sync_settings.sh` copies that forward into the CET mod dir as `status.txt`
  at the next launch, alongside what it resolved this launch and what the
  *previous* launch had asked for (off the stamp — comparing last launch's
  result against this launch's switch positions would cry wolf every time a
  toggle was flipped).
- `init.lua` reads `status.txt` (already inside CET's sandbox, no new I/O
  permissions) and renders it at the top of the tab:

  > **Last launch:** skin+hair · 70/70 resolves · 10 shadow · caches cleared

  A toggle that didn't take now shows as a mismatch between the switch and the
  last run, instead of reading "on" forever. This is the single change that
  converts the page from a wish list into a status display.
- Warnings fire on the failure modes that actually happened: layer never
  loaded, `hair` on with 0 resolve swaps (the 2026-08-26 null result), and any
  swap that failed to create. The hair and shadow switches also carry their own
  `[last launch: N swaps applied]` counter in the description.
- Verified against a stubbed `nativeSettings` for four cases: no record yet,
  healthy run, the 0-resolve failure, and layer-absent.

### Phase 4 — hygiene

- Log: per-launch timestamps, and truncate (or per-launch files) so one `grep`
  answers "did it apply *this* run".
- ~~Cache key: hash the materialized tree, not the param string, so a swap
  regeneration invalidates the cache too.~~ **DONE 2026-08-26** — the stamp
  now includes a hash of every installed `.spv` plus the layer `.so`
  (`stat -c '%n %s %Y' | sha256sum`), so a patcher re-run under unchanged
  settings evicts the caches by itself.
- Populate `release/vulkan/` from the built swaps, or delete `release/` until
  it's real (D6).
- Either wire the six sliders into the shipped gate or hide them in the release
  UI (D3).
- Relabel the kernel toggle, or make it re-read the flag live (D10).

---

## 5. Invariants

The rules that would have prevented each defect. Check a change against these
before it lands.

- **I1 — one writer per file.** (D4)
- **I2 — resolve by materializing, never by mutating.** The resolver emits the
  complete state from the params every launch; no step may depend on the order
  of a previous step. (D1)
- **I3 — positive logic.** Enabled lists, never `*.disable` files. Absence
  should mean off, not on. (§1, D2)
- **I4 — one switch, one artifact.** If two features share an artifact, ship
  the combinations; never let a switch half-apply. (D2)
- **I5 — any state change invalidates the pipeline cache,** keyed on the
  materialized state, not on the request. (D5)
- **I6 — nothing reads "on" until a run confirmed it applied.** The page shows
  last-run truth next to intent. (D9, and the reason D5 cost a session)
- **I7 — a visual confirmation is worthless without isolation.** One mod, one
  change, other mods off, both halves re-shot. "Loaded" (a swap HIT) is not
  "dispatched", and "dispatched" is not "visible" — each needs its own
  evidence. (D11)


---

## 6. Current tree state (2026-08-26, after Phase 3)

- Cache gate (D5) and the status loop (Phase 3) are installed and live.
- The 19:27 launch was the first with the cache gate: **70/70 compute-resolve
  swaps applied**, confirming the plumbing end to end. The effects had never
  actually been on screen before that.
- `swaps.hair/` currently holds a **deliberate diagnostic overshoot**
  (`m_aniso=6, m_dual=4, wR/wTRT=1.5, k_sheen=2, s_h=0.25,
  trt=(1.0, 0.15, 0.05), gi_boost=3`), built to answer whether the splice
  reaches visible hair pixels at all. It is *meant* to look wrong.
  The shipping-tuned build is backed up at
  `swaps.hair.tuned_20260826_1955/` — restore with `cp -f` and relaunch.
- Still open from §4: Phase 1 (materializing resolver, which fixes the dead
  `skinray` switch D1 and the non-master master switch D2) and Phase 2 (the
  duplicate `init.lua` landmine D4).
