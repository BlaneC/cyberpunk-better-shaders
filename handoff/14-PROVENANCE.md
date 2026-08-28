# 14 — Provenance hunt: what was tried, what failed, and the exact plan

> **SUPERSEDED 2026-08-27 by `15-RENDER-GRAPH.md`.** §2.4 ("ngfx-replay
> segfaults → offline replay unavailable") is **wrong**: the replayer needs
> `NGFXPROBE_STRIP_ALLOC=3`, documented in `../analysis/HANDOFF.md` §8.6 and
> implemented in `probe_layer.c:842`. Replay reproduced working; 2920 prov
> events obtained offline. **§4 (port prov hooks into `swap_layer.c`, then a
> live launch) is withdrawn — do not build it.** §1–§3 remain accurate as a
> record of the other dead ends.

Written 2026-08-27. Follows `13` (which named `6ac9085c9bd4b7da` the temporal
resolve that owns hair's per-pixel pixels). This document is the full record
of the attempt to name **6ac9's inputs** and **the modules that write its
current-lighting buffer** — including every dead end, so none are retried.

**Goal (unchanged):** find the interior-hair lighting evaluator — the module
that computes hair lighting for the buffer 6ac9 resolves. It is believed to
be a non-class-gated tile permutation among the 149 hunt failures (`13` §5),
so it cannot be found by palette hunting. It CAN be found by buffer
provenance: 6ac9 reads a current-lighting image; whoever writes it is the
evaluator set.

---

## 1. Facts established from capA (offline)

From `analysis/evidence/meta/capA_probe.jsonl` + 6ac9's disassembly
(`CallistoSSS/dev/disasm/compute/6ac9085c9bd4b7da.dxil.spvasm`):

- 6ac9 = `spv_0049` in capA (size 6452, one module handle, one pipeline,
  **dispatched once**, seq 1908211). Push consts there:
  `pc[1]=0xcb26 (52006)`, `pc[5]=0xcb2e`.
- Slot math (static, from the disasm; all images DescriptorSet 1 Binding 1,
  the bindless image heap):
  - history sample  `= heap[pc[1] + 0]`   (array %14)
  - current input   `= heap[pc[1] + 1]`   (array %14)
  - velocity buffer `= heap[pc[1] + 5]`   (array %14)
  - material uint   `= heap[pc[1] + 6]`   (array %18)
  - output image    `= heap[pc[5]]`       (array %22, storage)
- `dev/provenance_6ac9.py` (CallistoSSS) does this correlation and prints the
  above; it works up to the heap lookup, which fails (see §2).

## 2. Dead ends (do not retry)

1. **SetName events** — 47K of them, all NSIGHT auto-labels
   ("DeviceMemory_217"), no game render-target names.
2. **Heap reconstruction via `pData`** (calibrate_heap.py technique) — dead:
   ALL 1,419,148 `GetDescriptor` calls in capA stage into ONE stack temp
   (`0x7ffe9cb210e8`, 7 distinct (type,pData) pairs total). The game memcpys
   from the temp into the mapped heap; the memcpy is not a Vulkan call, so
   heap idx→view is unrecoverable from the call stream.
3. **Heap-build order hypothesis** — dead: slot values reach 52006 but only
   17,963 image-descriptor calls exist; no linear relation.
4. **ngfx-replay** (the path that produced capA_probe.jsonl) — **segfaults**
   on this machine (`/opt/nvidia/.../ngfx-replay` → SIGSEGV, recorded in
   `capA_replay_stdout.txt`). Offline replay augmentation is not available.
5. **The ngfxprobe layer live** — see §3; instructive failure.

## 3. The probe-layer prov mode: built, works, and why it failed live

`analysis/probe/probe_layer.c` was extended with a provenance mode that DOES
work (verified in `vulkaninfo`; the replay path is dead per §2.4):

- **Payload table**: every `vkGetDescriptorEXT` for image types (1/2/3) is
  recorded: 4-byte payload → `view` handle. The payload bytes ARE the heap
  content — this defeats the staged-memcpy problem.
- **Heap readback at dispatch**: at `vkCmdDispatch(Indirect)`, once per
  pipeline: resolve the bound set-1 VA → host pointer (`va_to_cpu`, from its
  MapMemory/BindBufferMemory/GetBufferDeviceAddress maps), read push
  constants (tracked per cb, 64B), then for each push dword D and offsets
  −1..+8 and strides {4,8,16}, match `heap[D+o]` against the payload table.
  Emits `{"ev":"prov","pipe","fnv","pc","idx","stride","type","view"}`.
- Build: `gcc -shared -fPIC -O2 -o VkLayer_ngfxprobe.so.prov probe_layer.c -lpthread`
- Registered: `~/.local/share/vulkan/implicit_layer.d/VkLayer_ngfxprobe.json`
  (needs `disable_environment` — newer loader skips the layer without it).
- Defaults: prov scan + prov-only log filter are ON by default (env vars do
  NOT reliably reach the game through Steam/Proton — proven twice:
  `NGFXPROBE_LOG` never reached the game process; `CALLISTO_LOG` does).

**Live failure (the important finding):** in the live game the probe layer
only ever sees **creation calls** (CreateShaderModule ×2474,
CreateRTPipeline ×1163, CreateImage ×34, vkCreateDevice ×20) and **zero**
command-buffer/descriptor/memory traffic (no CmdDispatch, no GetDescriptor,
no MapMemory, no PushConstants). The Callisto swap layer, in the same
session, logs dispatches fine. Conclusion: vkd3d-proton caches per-device
function pointers such that CB traffic routes through the swap layer's
chain only; the probe is bypassed for everything that matters. Under
ngfx-replay it saw everything — replay drives the calls differently.

Secondary defect (would matter even if the chain worked): the probe's device
tracking is replay-shaped — `g_dev[4]`, `dev_from_handle` returns the LAST
device. The live game creates ~20 devices; the table overflows and every new
device `memset`s slot 3.

## 4. The plan: port provenance into the swap layer

The swap layer (`CallistoSSS/swap_layer.c`) provably sees live dispatches
(`"ev":"dispatch"` in `~/callisto_swap.jsonl`). Port the prov machinery
there. Everything needed exists as reference code in
`analysis/probe/probe_layer.c` (`prov_desc_record`, `prov_lookup4`,
`prov_scan`, `va_to_cpu`, `cmd_state`, the Slot maps).

**Hooks to add** (swap layer currently has none of these):
`vkGetDescriptorEXT`, `vkMapMemory`(+`2KHR`), `vkUnmapMemory`,
`vkBindBufferMemory`(+`2`,`2KHR`), `vkGetBufferDeviceAddress`(+`KHR`),
`vkCreateBuffer`, `vkCreateImage`, `vkCreateImageView`,
`vkCmdBindDescriptorBuffersEXT`, `vkCmdSetDescriptorBufferOffsetsEXT`,
`vkCmdPushConstants`.

**Anchor points in swap_layer.c:**
- `DevData` struct (~line 404): add fields for the new function pointers.
- GRAB block in `xCreateDevice` (~711–736): grab them.
- `cond_dev_hook` + exports (~1040–1110): route the new names; CB functions
  should follow the `g_next_dispatch` pattern (grab once, hand out always).
- `xCmdDispatch`/`xCmdDispatchIndirect`: call `prov_scan(cb)` before the
  existing log path (same as the probe patch).

**Design differences from the probe version (improvements):**
- The swap layer already maps **cpipe → dxil id** (`g_cpipe`), so `prov`
  events can carry the module's dxil id directly — no fnv→id join needed.
- **No new env vars.** Gate the feature on a flag FILE
  (`~/.local/lib/callisto/prov.enable`) — env propagation to the game is
  unreliable (§3), the file check is trivial and the layer already reads
  `hair.disable` the same way. Log prov events into the normal callisto log
  (`CALLISTO_LOG`, proven to propagate).
- Per-cb state: keep a small table like the existing `g_cbbind` (cb→pipe);
  add push-constant bytes (64B), setva[8], infoaddr[8].
- Bounds: clamp every heap read to the resolved MapMemory region size
  (descriptor buffer seen at 32,000,064 B; push-slot values ~52–66K entries;
  stride≤16 → stay well inside).
- Payload collisions are possible (duplicate descriptors); log all candidate
  (stride, offset) matches per slot — the analysis step disambiguates by
  consistency (all five 6ac9 slots must resolve; material must be a big uint
  image, current/history full-res float, velocity float too).

**Then:** one live launch (Panam spot, ~1 min), then
`dev/prov_analyze.py /path/to/log` (adjust: read `id` directly from prov
events instead of fnv join) →

1. 6ac9's slot map (validate the semantic assignment: which of
   pc1+0/pc1+1 is *current* vs *history* — the current input should be
   written by compute evaluators THIS frame; history is written by 6ac9
   itself or an upstream copy).
2. **The writers**: every module whose storage-image (type 3) slots
   reference the current-lighting image → the evaluator set. The
   interior-hair evaluator is among them; it should be a tile-classified
   indirect dispatch, full-res, no class read in its disasm (one of the 149).

## 5. After the evaluator is named (the actual goal)

- It needs no class gate (tile-classified: dispatched per hair tile).
- Splice the hair BRDF there (the `--hair` tier sites: GGX + wrap; if it
  lacks the 1/π anchor, extend the patcher to its diffuse idiom — it must
  have *some* diffuse eval; the patcher's site finders are the next thing
  that will need teaching).
- The temporal resolve (6ac9) stays unmodified — it just resolves whatever
  the evaluators write.
- The rim-three / sun-family question (`12` §1, the `%937`-phi discard) is
  orthogonal and still open; the user's scenes don't exercise it.

## 6. Current install state

- `~/.local/lib/callisto/swaps.hair/` = rim-three spec_add probe (3 modules;
  from the Panam A/B — out-of-scope test, no conclusion). The 29-module hunt
  net is at `swaps.hair.bak_huntall29_20260827/`; restore with
  `dev/bisect_hunt.sh all` + cache clear if palette hunting resumes.
- `~/.local/share/vulkan/implicit_layer.d/VkLayer_ngfxprobe.json` →
  `analysis/probe/VkLayer_ngfxprobe.so.prov` (prov build; harmless to leave,
  useless live per §3 — remove if layering noise matters).
- New files this phase: `dev/provenance_6ac9.py`, `dev/prov_analyze.py`,
  `dev/bisect_hunt.sh`, `analysis/probe/probe_layer.c` (prov mode),
  `handoff/12-FRESH-HUNT.md`, `handoff/13-OWNER-NAMED.md`, this doc.
- Patcher changes (`12` §3) are uncommitted on branch `hair-brdf`.
