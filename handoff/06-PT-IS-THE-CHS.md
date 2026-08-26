# 06 — Live PT shades in the CLOSEST-HIT shader, not the raygen

Aug 25, after a clean vanilla PT run (launcher mods off, mod folders renamed,
PT confirmed on by frametime + visible grain). **This is the current source of
truth** and it explains every null result in `01`–`05`.

## The finding

The clean PT session's dispatch log:

```
seq 333-340   rgs_shadow_main ×5 (swapped:1), rgs_reference_main ×1 (swapped:1),
              ms_shadow_main
seq 1059-1062 fd1d0f0c84607e41.dxil ×3, c6bce844e971491a.dxil   <- PT proper
```

Both PT raygens were disassembled:

| module | size | 1/π | Disney | ray_query |
|---|---|---|---|---|
| `fd1d0f0c84607e41.dxil` | 18564 | **0** | **0** | no |
| `c6bce844e971491a.dxil` | 9816 | **0** | **0** | no |

**They contain no material shading whatsoever.** Live path tracing does not
shade in the raygen — the raygen is a thin tracer, and the shading happens in
the **closest-hit shader** reached through the pipeline's shader binding table.

`vkCmdTraceRaysKHR` binds a pipeline; the layer logs that pipeline's *raygen*.
Hit shaders never appear in `trace_rays` and never can. So the dispatch log —
the tool this project trusted as ground truth for four sessions — is
structurally blind to where PT shading lives. Every patcher built so far
(`patch_skin_brdf.py`, `patch_shadow_brdf.py`) targets raygens, which is why PT
frames rendered vanilla no matter what was installed and validated.

Inline ray tracing was ruled out first: **0** of 2265 dumped libraries declare
`SPV_KHR_ray_query`.

## The shading shader

`55f6172c71799e4d.chs_main` — `ClosestHitKHR`, 172816 bytes, the only hit
shader of 29 dumped that carries the Disney anchor. Confirmed created in the PT
session (`seq 2335`, size matches the dump byte for byte).

One diffuse site, a textbook Disney diffuse:

```
%5330 = OpFMul %float <roughness> 0.107508637
%5332 = OpFSub %float 0.318309873 %5330     <- Disney base (1/pi - k*rough)
%5334 = OpFMul %float %5332 %5323           <- FD90 term, L
%5335 = OpFMul %float %5334 %5329           <- FD90 term, V  = shared scalar
%5336 = OpFMul %float %5335 %2658           ) albedo.r  )
%5337 = OpFMul %float %5335 %2659           ) albedo.g  ) the diffuse triple
%5338 = OpFMul %float %5335 %2660           ) albedo.b  )
```

then each × NoL (`%5298`) and added to the specular (`%5386-%5388`).

Detection walks forward from the Disney base through single-use FMul hops until
it reaches a value consumed by exactly three *consecutive* FMuls. Hop count is
discovered, not assumed. Each triple value has exactly one consumer, so
`replace_single_use()` from the reference patcher applies unchanged.

## Critical structural difference: there is NO class gate here

`gbuf >> 5` — the material-class gate every previous tier depends on — **does
not exist in this shader** (verified absent). A hit shader reads material data
directly from the SBT/instance data; it has no screen-space G-buffer to index.

So the class-hunt palette technique does not port to the CHS as-is. Identifying
hair here needs a different signal (material id / SBT record / instance data)
and that is the next question to answer once the surface is confirmed.

## What was built

- `dev/patch_chs_brdf.py` — CHS anchor family, `forcetint` tier. Ungated by
  necessity (see above), which is also exactly what the first test wants.
- `dev/patch_chs_perms.sh` — patch/install every dumped hit shader carrying the
  anchor. Leaves raygen swaps installed. Same env overrides as the shadow
  driver (`CALLISTO_INSTALL_DIR`, `CALLISTO_SWAPS_DIR`,
  `CALLISTO_NO_CACHE_CLEAR=1`).

Verified: `spirv-val` clean; tint spliced between the triple and its consumers
(`%5389-%5391` now read the tinted values); the 0.05 constant correctly deduped
against the module's existing roughness clamp; 28 of 29 hit shaders correctly
skipped as carrying no shading (shadow / alpha-test hit groups), 0 failures.

**Installed** to `~/.local/lib/callisto/swaps/55f6172c71799e4d.chs_main.spv`,
caches cleared, log truncated. Awaiting the launch that decides it.

## Reading the result

- **Red** → the CHS is the live PT shading surface. The hair work moves here,
  and the immediate next problem is the gate signal, not the tint.
- **No change** → this CHS is not in the PT pipeline's SBT. Dump with no
  `CALLISTO_DUMP_MATCH` at all and patch every hit shader carrying the anchor.
