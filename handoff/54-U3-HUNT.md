# 54 — G-U3: the `R8_UINT` at +3 is the LightChannels mask — not translucency, and not free

Written 2026-08-30 night. Offline only: no launch, no build, nothing
installed. Tool: `dev/hunt_u3.py` (new). Logs: `capA_prov.jsonl`,
`capA_gfx.jsonl`, both pre-existing.

## 0. Verdict first

**The slot the nine family-A evaluators bind at `registers[1]+3` and never
read is the engine's per-pixel light-channel bitmask — `EMM_LightChannels` /
`LC_Channel1..8` — drawn per-volume by `CRenderNode_RenderLightChannelVolumes`
and consumed per-pixel by the ReSTIR-GI colour resolver.** Three consequences:

1. **It is not a translucency/thickness input.** `51` §7 step 1's hoped-for
   shortcut is dead. The traced-transmission route continues unchanged
   through the sentinel (`51` §7 step 2) — nothing else in that plan leaned
   on this.
2. **It is not a free write channel. B2-via-this-slot is dead.** `38` U3/§1.1
   called it plausibly free ("+3 UNREAD in 9/9 family-A and both GI
   resolvers"). Half of that is now measured wrong: `99bb7c2698997b2a` — the
   one colour-writing GI resolver (`46` §12) — **reads it every pixel** and
   folds it into per-light gating. Overwrite it with thickness and every
   light-channel-gated light breaks, worst on characters (LC_Character /
   LC_Player are exactly the drawn channels).
3. Incidental but real: the GI resolver derives two extra mask bits from the
   material **subtype** — `{21, 12,13, 14,15(,30,31 via &14)} → bit 512`
   (hair family), `25 → bit 1024` (eyes) — live confirmation that subtype
   values gate real behaviour in the GI path (`40`'s question, from the
   consumer side).

## 1. The read census (strict, per-binding)

`dev/hunt_u3.py` resolves, per module that binds the image, whether the
SPIR-V actually fetches the offset that lands on it — with an image-type
check (an `R8_UINT` must load as a *sampled uint* image; a float or storage
hit is a base-inference artefact, measured on `9b7a5e20` pc[5]).

Reproduce (from `GraphicsCaptures/`):

    python3 CallistoSSS/dev/prov_map.py analysis/evidence/meta/capA_prov.jsonl --image 0x1c850e10
    python3 CallistoSSS/dev/hunt_u3.py  analysis/evidence/meta/capA_prov.jsonl 0x1c850e10 \
        --disasm CallistoSSS/dev/disasm/compute <scratch>/u3disasm

22 modules bind it (23 rows). Family A binds at **+3, unread, 9/9** — `38`
§1.1 confirmed. Post/misc modules bind it at +2..+8 of their own tables,
unread. **One reader survives** (§3). Six binder modules had no disassembly
and were `spirv-dis`'d to scratch; all six are plain unread binders.

## 2. The writer (capA_gfx.jsonl)

Four `R8_UINT` 1280×720 images exist; the compute-bound one is
`0x4e30c430` in the gfx log's handle space (same 22-binder prov signature).
In the captured frame:

| seq | target | what |
|---|---|---|
| 1867868 | `0x4e30c430` (the bound one) | **clear-only pass** (loadOp=CLEAR, storeOp=STORE, 0 draws) |
| 1868048 | `0x4e30fac0` (sibling) | clear + **2 × `drawIndexed(60)`**, depth-tested against the 720p D32_S8 |

Both passes sit late in the frame (after lighting, beside the bloom
downsample chain) — a ping-pong pair prepared for the *next* frame. 60
indices = 20 triangles = a closed volume proxy; two dynamic
volumes/characters in frame ⇒ two draws. The engine names the machinery:
`CRenderNode_RenderLightChannelVolumes`, `worldLightChannelShapeNode`,
`worldLightChannelVolumeNode` (exe strings, E9 method).

usage=279 carries `FRAGMENT_SHADING_RATE_ATTACHMENT` (0x100) — boilerplate,
not role: NVIDIA's rate-image texel size is 16×16, so a 720p rate image
cannot serve any plausible pass. Do not repeat my first hour and chase VRS.

## 3. The reader — and the correction to `38` and to this doc's own tool

`99bb7c2698997b2a` binds the image at prov idx 82702. Min-idx base
inference says "+6, unread" — **wrong**. Format-anchoring the base against
its fetched offsets (the only assignment where every fetch type matches:
+1=D32 float, +2=RGBA8 float, **+4=uint**, +7=A2B10G10R10 float) puts the
true base at 82698, so the uint fetch at **+4 IS the target**. The probe's
pc attribution mixed a second table into the pc[1] row-set; `hunt_u3.py`'s
docstring now carries this as a measured limit. Treat its BASE-UNCERTAIN
rows as unresolved, always.

The decode, `dev/disasm/compute/99bb7c2698997b2a.dxil.spvasm:4274–4289`
(ids `%390`–`%412`), consumed at `:5289`/`:36614`/`:44951`:

    %392 = R8 value at this pixel
    %394 = %392 != 0 ? %392 : 256          ; 0 => LC_ChannelWorld sentinel
    %410 = subtype in {21,12,13,14,15,...} ? 512 : (subtype==25 ? 1024 : 0)
    %412 = %394 | %410                      ; the pixel's channel word
    ...
    (%412 & 0xFFFF) & <per-light mask> != 0 ? 1.0 : 0.0

A bitmask OR'd with subtype-derived bits and AND-tested against a per-light
word for a binary weight: **per-pixel × per-light channel gating**, exactly
`LC_Channel1..8` + `LC_Character`/`LC_Player` + hair/eye bits. Not an
intensity, not an ID, not thickness. (`%331` is the subtype phi — its
sibling `%330 = word >> 5` is the class; `:3977`/`:4243-4244`.)

Family A never reading it is coherent, not mysterious: the sun is not a
channel-gated light. The `*_Clustered_LightBlockers_*` shader-name family
(exe strings) marks the raster-side consumers; unprovable offline per
GOTCHAS, and nothing rides on it.

## 4. What this means for the plan

- `51` §7 step 1: **answered, negative** — no free thinness input. Step 2
  (sentinel) and step 3 (traced thickness) proceed unchanged; the traced
  route was always the honest one and is now the only one.
- `38` U3 / B2-via-U3: **retire**. The channel is load-bearing in the GI
  resolver this mod already splices (`gi-50` rides `99bb`'s raygen-side
  siblings; the resolver itself reads the mask every pixel).
- If a per-pixel scratch channel is ever needed, it must come from U1/U2
  (inject or author one), not from squatting this slot.

## 5. Confidence

| claim | confidence | basis |
|---|---|---|
| 22 binders, family A +3 unread 9/9 | **certain** | hunt_u3.py strict census, type-checked |
| `99bb` reads the image at its +4 | **certain** | format-anchored base (4/4 type match, unique assignment) + the fetch chain read by hand |
| The value is a light-channel bitmask | **certain** (mechanism) | the `|`/`&`/select chain above |
| The buffer is the LightChannels render mask by name | **high** | `EMM_LightChannels`, `LC_*`, `CRenderNode_RenderLightChannelVolumes` in the exe; drawn-volume writer shape matches |
| Writer = per-volume depth-tested draws, ping-pong pair | **high** | capA_gfx passes; single frame, one scene — draw count will vary per scene |
| Subtype bits 512/1024 = hair/eyes | **high** | values match `40`'s census and the on-screen class map (`46`); eye=25 untested on screen |
| No raster-side conclusions | — | GOTCHAS: compute prov cannot see raster reads; none claimed |

*Falsifier for §0:* a one-line probe on the existing `99bb` splice site
painting `%392 != 0` would show character/volume silhouettes, not ear/nose
thinness — if it showed thinness gradients instead, this doc is wrong and
U3 reopens. Not worth a launch unless something else contradicts.

