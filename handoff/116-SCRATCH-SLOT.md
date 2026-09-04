# 116 — Stage 3a: the BDA slot widened into a shader-WRITABLE scratch (`bda-wprobe`)

Written 2026-09-04, on the ask *"lets widen the BDA slot and run a test"*.
The test is run: `dev/selftest_bda.sh` is **85 passed, 0 failed** on the real
driver, and the two new cases (G and H) are the ones that matter. Nothing has
been on a screen yet; the in-game rung is built, gated 10/10, verified from the
shipped bytes, parked, installed and selectable.

## 0. What it is, in one paragraph

`103` gave the layer a 256-byte slot and used 8 of its 64 words as a **mailbox**
— the layer writes, the shader reads, every member `NonWritable`. Stage 3a puts
the *other* direction in words 8–11: they now hold the device address and size
of a **32 MiB buffer the shader writes**, allocated by the layer, zero-filled
once by the host and never touched by it again. That is the unlock: a compute
resolver and a raygen that share no descriptor set can share a per-pixel word,
and that word survives the dispatch, the pass and the frame.

## 1. The slot's new words (`swap_layer.c`, "BDA SLOT")

| word | name | written by |
|---|---|---|
| 0–7 | magic, generation, TLAS lo/hi, prims, builds, frame, flags | `103`, unchanged |
| 8 | `scratch_lo` | `bda_setup`, once |
| 9 | `scratch_hi` | " |
| 10 | `scratch_words` | " — **0 when there is no scratch**, and that is the shader's guard |
| 11 | `scratch_flags` | bit 0 armed, bit 1 the layer mapped it and can read it back |

The scratch's own first `CALLISTO_SCRATCH_HDR = 16` words are reserved for
shader-side counters; the payload starts there. `CALLISTO_BDA_SCRATCH_MB`
(default 32, `0` = none) sizes it, and the allocation steps down by halves if
the BAR heap refuses — so `words` is always a power of two, which is what makes
the shader's mask legal without a clamp.

Two properties are load-bearing and were chosen, not inherited:

- **Host-visible.** The layer can therefore *read what a shader wrote* and log
  it (`bda_scratch_hdr`), including a CPU-side population count over 4096
  evenly spaced payload words. That is a read-out with no screenshot and no
  shader cost. Formally a shader write is visible to the host only after a
  `HOST_READ` barrier this layer has nowhere to record; in practice on this
  driver it lands (case G proves it), so treat a zero as "nothing seen", never
  as "the shader did not write".
- **Never written by the layer after the initial memset.** Anything non-zero in
  it came from a shader. That is the entire evidentiary value.

## 2. The rung (`dev/patch_bda.py --mode wprobe`)

Per skin pixel, at each of the 151 painted radiance writes in 76 of the 77
compute resolvers:

```
pix   = y * 4096 + x                    ; the write's OWN coordinate
idx   = armed ? 16 + (pix & (words/2 - 1)) : 32
word  = 0xC0FFEE01 ^ (pix * 2654435761) ^ frame      ; frame = slot word 6
got   = scratch[idx]                     ; READ first
seen  = got == (word with frame - 1)
scratch[idx] = word                      ; then write
```

- **GREEN** — `seen`: the word this pixel wrote *last frame* is still there.
- **BLUE** — the scratch is armed and it is not (first frame, or a pixel whose
  geometry moved, or a second write site in the same frame).
- **AMBER** — the slot is there, the scratch is not (`CALLISTO_BDA_SCRATCH_MB=0`).
- **RED** — the magic is wrong, i.e. the layer never fixed the pointer up.

Three decisions worth keeping:

1. **The index is linear in the pixel and the value is hashed**, not the other
   way round. A hashed index collides and paints a false BLUE; a hashed value
   only has to be unlikely to equal a neighbour's.
2. **Only the lower half of the payload is addressed** (`words/2 - 1` as the
   mask). `16 + (pix & mask)` is then in bounds for every pixel at every size
   the layer can hand back — with no clamp and no branch.
3. **The unarmed pixel is pointed at the SLOT**, index 32, one of the layer's
   own reserved words. So the store needs no control flow and can never
   dereference a null address. `--decoy noguard` is that mistake, and the
   verifier refuses it.

The frame stamp is what makes GREEN a claim about *time*. `--decoy sameframe`
stamps the expected word with this frame instead — the rung then paints green
having proved nothing, and gate 7 refuses it.

## 3. What was run, and what it proved

`./dev/selftest_bda.sh` — **85 passed, 0 failed**, on the RTX 4070 through the
real layer, no game.

Case G (`scratch`, a synthetic module dispatched **twice, in two submits**):

```
slotx: [8]=0x09400000 [9]=0x00000000 [10]=8388608 [11]=0x00000003
scr pass1: prev=0x00000000 count_before=0 readback=0xc0ffee01 words=8388608
scr pass2: prev=0xc0ffee01 count_before=1 readback=0xc0ffee01 words=8388608
"ev":"bda_scratch","action":"armed","reason":"armed","addr":"0x9400000","mb":32,"words":8388608
"ev":"bda_scratch_hdr","words":8388608,"nonzero":1,"w0":2,"w1":"0xc0ffee01"
```

- the dispatch read the scratch's address and size out of slot words 8/9/10;
- **pass 2 read the word pass 1 wrote** — across two submits, through a
  pointer, with no descriptor naming the buffer;
- `OpAtomicIAdd` on a `PhysicalStorageBuffer` pointer works (0 then 1);
- **the layer read the shader's writes back from the host side** (`w0`=2 is a
  number no CPU wrote), and its payload census found the written word.

Case H (`CALLISTO_BDA_SCRATCH_MB=0`): the slot still arms, the scratch does
not, word 10 reads 0, the shader takes its guarded path, nothing faults, and no
`bda_scratch_hdr` line is emitted because there is nothing to read.

Case D now serves all four rungs' **real** resolvers through the layer on the
driver: `bda-wprobe`, 76 of 76 accepted, 76 fixups.

## 4. Gates (`dev/build_bda.sh`, all green, `--install` run)

Unchanged from `103` in shape; what is new in each:

| gate | what it now also asserts |
|---|---|
| 2 | four rungs; `bda-wprobe` differs from the base on 76 of 93 |
| 3 | slot is **12** words in `wprobe` and 8 elsewhere; pitch/hash/hdr/sig/park are this build's; the rung reads slot words `[0, 6, 8, 9, 10]` and no others |
| 4 | **2** added PSB bitcasts (slot + scratch), exactly 1 added `OpTypeRuntimeArray %uint`, at least one added `Aligned 4` store — and **zero** of either in the read-only rungs |
| 6 | `verify_bda.py --mode wprobe` on the shipped bytes |
| 7 | + `--decoy noguard`, `--decoy sameframe`, and each rung read as the other |
| 9 | 227 modules rewritten to a plausible address and re-validated |

`verify_bda.py --mode wprobe` re-derives all of it from the `.spv` and refuses
eleven more things than `103`'s did, the two that matter being the missing
armed-select and the missing frame stamp. It also ties the index to **this
write's own coordinate**: a module that indexed by some other pixel's `(x, y)`
is refused.

Content shas: `bda-wprobe` = `6cc4482d174dae59` (compute half
`c344e86ea2469d9f`), base `3bb0aee03a1bfda8`.

## 5. SETTINGS CONTRACT — state this BEFORE the launch

Same as `103` §8. `ser=class`, `shadowset=full-shadow`, path tracing ON,
`skinspec` = `bda-wprobe`, and the A/B 'before' is `bda-ctl` (byte-identical to
the `cap6-glintdense` base). **This is a diagnostic rung: skin will be flat
colour.** Frame: a sunlit face, 0.3–1 m — the compute resolvers only shade
direct sun under PT (memory `pt-local-light-site`), so an interior frame paints
nothing whatever the scratch does.

Order to read:

1. `bda-probe` first if the layer has changed at all — it is the Stage 2b
   control and it is cheap.
2. `bda-wprobe`. **Skin GREEN = Stage 3a works in the game.** The frame that
   matters is the second one onward; the first frame is legitimately blue.
3. Grep the log: `bda_scratch.*armed`, then `bda_scratch_hdr` and its
   `"nonzero"` — a number that grows with the skin on screen is the same claim
   the screen is making, from the other side.

Pre-registered readings, written before any screen:

| what you see | what it means |
|---|---|
| GREEN skin | the channel works: per-pixel, persistent across frames, correctly addressed |
| BLUE skin, steady | the scratch is armed but nothing survives — the buffer is being cleared, or the frame counter (slot word 6) is not moving |
| BLUE only where the camera moved | correct and expected: that pixel's word belongs to different geometry now |
| AMBER skin | the layer allocated no scratch; read the `bda_scratch` reason |
| RED skin | no fixup — the installed layer is not this build |
| vanilla skin | the rung is not being served; `103` §13's checklist applies |

## 6. What this does NOT establish

- Nothing about a **raygen** reading what a resolver wrote. That is Stage 3b
  and it is the actual prize (`114` §2.4, `115` §10.3): the same block spliced
  at the raygen's primary hit, reading the pore normal the resolver computed,
  so faces have pores under local lights at night. `wprobe` proves the channel;
  it does not use it.
- Nothing about cost. The rung adds one load and one store per skin pixel to a
  host-visible allocation; a device-local scratch (no read-back) is the shipping
  choice and is one memory-type flag away.
- Nothing about a second device. The layer still arms one slot, and a second
  RT-capable device is logged, not served.

## 7. Files

```
swap_layer.c            slot words 8-11, the scratch allocation, bda_scratch_report
dev/patch_bda.py        --mode wprobe, --decoy noguard|sameframe, SLOT_MEMBERS_V2
dev/verify_bda.py       --mode wprobe: scratch_pointer(), check_wprobe_site()
dev/build_bda.sh        the fourth rung and its gates
dev/selftest_bda.sh     the `scratch` synthetic module, cases G and H
init.lua                the CET row
swaps.bda-wprobe/       93 modules, parked to skin.set/bda-wprobe
swaps.bda-wprobe2/      93 modules, parked to skin.set/bda-wprobe2 (sec 8)
```

## 8. The 2026-09-04 launch: the channel works, the RUNG's clock does not

**What was run.** `skinspec=bda-wprobe skin_sha=6cc4482d174dae59`, 12:10:18,
sunlit exterior, PT on. Reported: *"skin flickered between green and blue until
I took a photomode screenshot, now all skin is blue in direct sunlight."* The
photomode PNG (12:12:22) agrees: a blue-violet cast over every lit skin pixel of
both characters, no green anywhere, and the cast is a multiply over the
resolver's own radiance rather than a flat fill — which is what this paint is.

**The channel is not what failed.** From `~/callisto_swap.jsonl` for that run:

```
bda_scratch armed ... words 8388608          the 32 MiB allocated and published
32 fixups, 0 rejects                          the slot reached every marked module
bda_scratch_hdr  nonzero 0 -> 336 -> ... -> 1281   of 4096 sampled payload words
```

`nonzero` is counted **host-side, by the layer, from the mapped scratch**. It
only rises if compute shaders on the GPU wrote words the CPU can then read. So
Stage 3a's actual claim — a shader-written, layer-readable buffer reached with
no descriptor — held in the game. That is the thing that was in doubt, and it
is settled.

**What failed is the frame stamp.** `wprobe` compares the word it reads against
`SIG ^ hash(pix) ^ (frame - 1)`, where `frame` is slot word 6. The layer writes
word 6 while **recording** a command buffer; the shader reads it while
**executing** one. Those are 1–3 frames apart and the gap is not constant.

- While the gap wobbles, `frame_at_execute - frame_at_previous_execute` is
  sometimes 1 and sometimes not → **green/blue flicker**, exactly as reported.
- Photo mode pauses the world. If word 6 stops advancing, every pixel reads back
  a word stamped with the *same* frame it now expects to be one older → the
  compare can never be true → **steady blue**, exactly as reported.

Both halves of the report fall out of one bug, and neither is evidence against
persistence or addressing. (The scarcity of `bda_tlas` lines in the log proves
nothing either way: the layer only emits that event `if (changed)`.)

**The fix, and why it is a new rung rather than an edit.** `wprobe` cannot
distinguish "the word did not survive" from "the clock is wrong", because it
folds both into one integer. `--mode wprobe2` splits them:

| word | contents | what it decides |
|---|---|---|
| `scratch[16 + 2*(pix & mask)]` | `SIG ^ 2654435761*pix` — **no frame** | `seen`: is this my word, at my index, still here? |
| `scratch[17 + 2*(pix & mask)]` | the frame it was last written | `age = frame - stored`: only the hue |

Colours: **BLUE** = not this pixel's word (no persistence, or the index is
wrong — the only real failure). **GREEN** = survived exactly one frame.
**CYAN** = age 0: the resolver ran twice against the same value of word 6,
i.e. record is ahead of execute. **MAGENTA** = age ≥ 2: word 6 jumped or froze
(this is what photo mode should now paint). Every non-blue hue is the channel
working; the hue only reports the clock.

Two new decoys keep the verifier honest about it: `--decoy noguard` again (the
null dereference, in the two-word emission), and `--decoy stamped`, which folds
the frame back into the identity word — the precise mistake `wprobe` made, now
something the verifier refuses to accept.

`swap_layer.c`'s `bda_scratch_hdr` line also now carries `slot_frame` (word 6),
`frame` (the layer's own counter) and `tlas_refreshes`. If the diagnosis above
is right, `slot_frame` will visibly stop moving while photo mode is open.

### 8.1 SETTINGS CONTRACT for the wprobe2 launch

Identical to §5 with `skinspec` = **`bda-wprobe2`**: `ser=class`,
`shadowset=full-shadow`, PT on, sunlit exterior face at 0.3–1 m, A/B 'before'
is `bda-ctl`. Read in this order:

| what you see | what it means |
|---|---|
| GREEN, steady | the channel works AND record/execute are in lockstep |
| CYAN, or CYAN/GREEN mix | the channel works; word 6 is read twice per advance |
| MAGENTA | the channel works; word 6 froze or jumped — open photo mode and this should be what appears |
| BLUE | the real failure: the word did not persist, or the index is wrong |
| BLUE only where the camera swept | expected; that pixel's word belongs to different geometry now |
| AMBER / RED / vanilla | as §5 |

The one reading that would retire §5's ambiguity in a single frame is *any*
non-blue hue in photo mode.

## 9. The wprobe2 launch: STAGE 3a IS PROVEN IN THE GAME

Reported, verbatim: *"Cyan is in the middle of the character but blue is in the
shadowed areas or around the edges of the character in photo mode. The character
flickers for the briefest second to green then back to cyan (cyan more
consistently). … The blue follows the camera. There's a point on the top third
of the screen where all characters' skin goes blue, bottom third there's
consistently noisy flickering back to blue. Magenta gets drawn randomly when I
alt-tab back into the game for a little bit then goes back to the cyan."*

Read against §8.1's pre-registered table:

| seen | pre-registered meaning |
|---|---|
| CYAN, dominant | **the channel works**; word 6 is read twice per advance |
| brief GREEN | the channel works; that frame the gap was exactly 1 |
| MAGENTA on alt-tab | the channel works; word 6 jumped while nothing executed |
| BLUE | the word did not persist, **or the index is wrong** |

Three independent hues, all of which require a shader to have read back a word
another dispatch wrote through a raw device address with no descriptor. **The
question §5 was written to answer is answered: per-pixel, persistent,
correctly-addressed shader-visible storage works in Cyberpunk.** §8's clock
diagnosis is confirmed too, and by the prediction that was hardest to fake:
magenta appeared exactly when the world stopped executing.

### 9.1 The blue is an INDEX bug, and the arithmetic names the resolution

The blue is *screen-space*, not geometry-space — the user's own correction
("the blue follows the camera"). That is the second BLUE arm: the index is
wrong, in bands.

`sub = (y * 4096 + x) & mask`, and with a 32 MiB scratch at two words per pixel
`mask + 1 = words/4 = 2^21`. So `sub` is injective only while `y * 4096 < 2^21`,
i.e. **`y < 512`**. Row 512 lands on row 0's word, row 513 on row 1's, and each
colliding pair overwrites the other's identity, so *both* read back a stranger's
word and paint blue.

That predicts a clean band and two blue bands, at positions that depend on the
render height:

| render res | collision-free rows | as a fraction of the screen |
|---|---|---|
| **1280x720** | 208..511 | **29% .. 71%** |
| 1707x960 | 448..511 | 47% .. 53% |
| 1920x1080 | none | — |

"Top third blue, bottom third blue, middle cyan" is the 1280x720 row — DLSS
Performance at 1440p. The report did not just land in the table, it identified
the internal resolution to the row. The shadowed edges are the other, expected
blue: a pixel whose word belongs to different geometry now.

### 9.2 Fix

Layer-side only; **the shader bytes are unchanged** (`bda-wprobe2` is still
`15bbc98bf6ce10c9`). `CALLISTO_BDA_SCRATCH_MB` now defaults to **128**, so
`mask + 1 = 2^23` and rows 0..2047 at pitch 4096 are collision-free — every
render height this game can produce. The step-down loop still halves on
allocation failure, so a small BAR heap degrades instead of breaking; a run that
steps down to 32 will show §9.1's bands again, and the `bda_scratch` log line
says which size was taken.

The pitch and the size are one decision, and that is now written where both are
defined (`swap_layer.c` header, `dev/patch_bda.py` above `PIX_PITCH`).

Gates re-run 10/10, self-test 88/88, all five rungs re-parked, layer rebuilt and
installed (`79de001e17884937d0a317fc649bccbb`, repo == release == installed).

### 9.3 What to run next

Same contract as §8.1, `skinspec` = `bda-wprobe2`, unchanged. Expect: **cyan
over the whole character, top of screen to bottom**, blue only at shadowed edges
and where the camera just swept, magenta on alt-tab. If a band of blue is still
there, read `bda_scratch` in the log for the size actually taken.

### 9.4 What is now unblocked

Stage 3b, the actual prize: the same block spliced at a raygen's primary hit,
reading the per-pixel word the compute resolver wrote. That is pores under local
lights at night (`115` §10.3, `114` §2.4), and it no longer needs anything
proven — only written. Note the standing constraint it removes: the resolvers
only shade direct sun under PT, so today a resolver-side feature is invisible
indoors. A resolver that *writes* and a raygen that *reads* is how that ends.

One rule the clock work leaves behind: **no feature may depend on slot word 6.**
The layer writes it at command-record time and shaders read it at execute time.
If a future rung needs a frame identity, the shader should own it — an
`OpAtomicIAdd` in the scratch header, which §G of `selftest_bda.sh` already
proves works.

## 10. Confirmed (photomode 12:48). §9.2 closed.

*"Consistently cyan now. Only the odd flicker to green randomly. Magenta on alt
tab. No flickering blue at all in shadow."* The 12:48 frame: a uniform teal wash
over every skin pixel of both characters, top of screen to bottom, the far
character's chest included, the shadowed neck included. **No bands.**

That is §9.1's prediction discharged: the blue was `(y*4096 + x)` aliasing at
`y >= 512`, and 128 MiB of scratch removed it without touching a byte of shader.
"No blue at all in shadow" also retires the last innocent explanation on the
table — a pixel's word surviving is not conditional on how it is lit.

So the whole of Stage 3a stands, on the game, with the pre-registered table
written before the frame:

- a layer-owned buffer reached by shader code through a raw 64-bit address,
  with no descriptor, no binding and no root signature change;
- one word per pixel, correctly addressed, at 1280x720 internal;
- surviving between dispatches and between frames;
- readable by the layer from the host side while the game runs;
- degrading to AMBER, not to a crash, when the layer allocates nothing.

`bda-wprobe2` = `15bbc98bf6ce10c9`, layer `79de001e17884937d0a317fc649bccbb`.

### 10.1 The one thing Stage 3b must establish first

The prize needs a **raygen** to read what a **compute resolver** wrote, and the
two address the pixel differently: the resolver uses its `OpImageWrite`
coordinate, a raygen uses `OpLoad` of `LaunchIdNV`. Nothing yet proves those are
the same grid, the same origin, or even the same resolution — and if they are
not, a Stage 3b feature would fail silently and look like a bad pore normal.

That is one probe, not a feature: the resolver writes `SIG ^ hash(pix)` as
today, the raygen reads `scratch[16 + wpp*(launchY*4096 + launchX)]` and paints
its OWN output GREEN when the word is the one the resolver would have written
for that pixel, BLUE when it is not, MAGENTA when it is some other pixel's word
(i.e. the grids are offset or scaled). It also dates the read, which measures
the resolver-to-raygen latency directly — the number any temporal reprojection
in a real feature will have to assume.

Note what changes in the build: this is the first rung to patch the **raygens**,
which every rung so far has shipped verbatim (and every gate asserts is the
case). Gates 3, 4 and 6 and `verify_bda.py`'s raygen check all have to learn the
difference between "a raygen carries the marker" and "a raygen must not".

## 11. `bda-xprobe` — the cross-stage rung (BUILT, GATED, UNSHOT)

The first rung in this project that patches the **raygens**. Every rung before
it ships all 16 verbatim, and three gates assert that; this one gets the
opposite assertion.

### 11.1 What the two halves do

| stage | reads | writes | paints |
|---|---|---|---|
| 77 compute resolvers (76 patched) | nothing | `SIG ^ 2654435761*pix` and the frame | **nothing** |
| 16 raygens (all patched) | both words at its own coordinate | **nothing** | the tint |

Both halves derive the index the same way, from **the write's own
`OpCompositeConstruct %v2uint` coordinate** — never a builtin, never a
re-derivation. That is the whole measurement: if the resolver's image-write
coordinate and the raygen's image-write coordinate are the same pixel, the
raygen finds the word; if they are offset or scaled, it finds a stranger's.

The writer cannot branch around its stores, so its skin gate rides on the
ADDRESS: `idx = (armed && class == 1) ? 16 + 2*(pix & mask) : 32`. A non-skin
pixel writes reserved slot word 32 and nothing reads it.

### 11.2 The tint, and how to read the screen

The frame is the game, unmodified, multiplied per pixel by:

| tint | meaning |
|---|---|
| untouched (x1.0) | no word at this index — nothing wrote here (non-skin) |
| **GREEN** | the word this pixel's resolver left **one frame** ago |
| **CYAN** | age 0 — the resolver ran earlier in this same frame |
| **MAGENTA** | age >= 2 — stale |
| **RED** | a word IS there and it is **a different pixel's**: the grids disagree |
| AMBER | no scratch | 
| BLUE | no fixup |

**Green (or cyan) landing exactly on the skin silhouette is the answer.** A
displaced or rescaled tinted blob measures the offset directly — its position
is the mis-registration. Red anywhere is the same finding stated the other way.

Because both stages read slot word 6 at EXECUTE time, the age is a true
resolver-to-raygen frame delta: the record/execute skew that ruined §8 cancels.
Whatever number shows up is the latency any real Stage 3b feature must assume.

### 11.3 Why the raygen only reads, and the writer only paints nothing

Two rules, both enforced:

- the **writer changes no pixel** — so a tinted frame cannot be the resolver's
  doing. Gate 4 counts `OpImageWrite`, `OpFMul %float`, `OpSelect %float` and
  `OpCompositeConstruct %v4float` in the shipped module against the base and
  requires every count unchanged (text cannot be diffed: spirv-as renumbers).
- the **reader stores nothing** — so what it reads next frame is never its own
  handwriting. Gate 4 requires zero added aligned stores in all 16 raygens, and
  the verifier refuses a reader that stores through the scratch pointer.

Four new decoys prove those are not vacuous: `--decoy paints` (the writer tints
too), `--decoy rgstore` (the reader writes the age word), `--decoy xoffset`
(the reader indexes the pixel next door — the silent mis-registration the rung
exists to detect), and `--decoy noguard` again, in both stages.

### 11.4 Which raygen writes get painted

Measured across all 16, every raygen writes radiance to `registers[5] + 0` and
`registers[5] + 1` and nothing else — except `1271d3815051da17`, which also has
a `registers[5] + 8` guide buffer. Only +0 and +1 are painted: tinting a
denoiser guide would make the read unreadable. The patcher re-derives the
descriptor index per module and the verifier re-derives it again from the
shipped bytes. 53 painted sites over 16 raygens; two of them
(`40c6faab52a13874`, `ab7f1822eeb0331b`) have only the zero-clear pair, so they
paint zero times zero and cost nothing.

### 11.5 SER comes first, and that matters

The 12 `rgs_reference_main` modules declare `ShaderInvocationReorderNV`. The
layer's SER gate runs BEFORE the marker is looked at, so on a device without
SER they fall through to the next overlay untouched — which the driver
self-test now asserts explicitly (12 `ser_reject`, 0 `bda_reject`, 80 of 92
fixups). **In the game `ser=class` must be ON or the twelve PT raygens are not
this rung's at all.** It is already in every settings contract; it is now also
load-bearing for the measurement.

### 11.6 Gates

```
build_bda.sh   10/10 green, six rungs, --install run
               gate 1 now round-trips the 16 raygens too (spv1.4, byte-exact)
               gate 5 counts compute and raygen diffs apart: 76/77 and 16/16
selftest_bda.sh 93 passed, 0 failed -- case D serves all 92 marked modules
               through the layer on the real driver, raygen stand-ins included
verify_bda.py  --mode xprobe: 76 writers + 16 readers, 151 + 53 sites
shas           bda-xprobe content=c1fbf29b151ca333 compute-half=65a2e9b0e335adb7
               layer 79de001e17884937d0a317fc649bccbb (repo == release == installed)
```

### 11.7 SETTINGS CONTRACT — state this BEFORE the launch

`ser=class` (**required**, see §11.5), `shadowset=full-shadow`, path tracing ON,
`skinspec` = **`bda-xprobe`**, A/B 'before' is `bda-ctl`. Frame: a sunlit
exterior face at 0.3–1 m, same as §5 — the resolvers only write on skin they
shade, and under PT they shade skin only in direct sun.

Pre-registered readings, written before any screen:

| what you see | what it means |
|---|---|
| GREEN on the skin silhouette | **the grids agree**; resolver→raygen latency is one frame. Stage 3b is unblocked as designed |
| CYAN on the skin silhouette | the grids agree and the resolver runs first within the frame — better than expected, zero latency |
| MAGENTA on skin | grids agree, latency ≥ 2 frames — usable, but a feature must reproject |
| a tinted blob NOT on the skin | the grids disagree; where it lands measures the offset or scale |
| RED on or near skin | the same finding: a word is there, from another pixel |
| no tint anywhere, skin unchanged | the raygen never read a word — check `ser=class`, then `bda_scratch` in the log |
| AMBER / BLUE | no scratch / no fixup, as before |

Also grep the log for `ser_reject` — **it should be 0 in the game.** Any
non-zero count means the twelve PT raygens fell through and the reader half
never ran.

### 11.8 What this still does not establish

Nothing about a raygen using the value for shading. This rung proves the
address agreement and measures the latency; the pore normal itself (`115`
§10.3) is the next build, and it is ordinary work once the number in §11.7 is
known.

## 12. The xprobe launch: THE GRIDS AGREE. Stage 3b is unblocked.

Reported: *"Green/Cyan blends together until it's consistent cyan on the skin.
Pink gets slowly drawn onto everything else until everything else is covered
pink."* Photomode 13:21 measured directly:

| signature | pixels (of 3 686 400) |
|---|---|
| CYAN | 452 022 |
| MAGENTA | 77 852 |
| **RED** | **32** — the second character's actual red respirator, bbox x 1802-1993 y 582-712 |
| AMBER | 56 (same, the mask's warm edge) |

### 12.1 What the cyan settles

The cyan lands on the **skin silhouette and nothing else** — both characters,
face, neck, chest, hands, at 1280x720 internal upscaled to 2560x1440. A raygen
tinted a pixel cyan only if the word it loaded equalled
`0xC0FFEE01 ^ 2654435761 * (y*4096 + x)` for **its own** write coordinate, and
the only thing that could have put that word there is the compute resolver that
shaded that same pixel.

**A raygen's image-write coordinate and a compute resolver's image-write
coordinate are the same pixel.** That is the one fact §10.1 said Stage 3b needs
and nothing yet proved. It is now proved, at pixel granularity, on the real
frame, with a pre-registered table.

**And there is no RED.** Not one pixel in the frame read a word belonging to a
different pixel. The rung's ability to say "the grids disagree" was built,
decoy-tested (`--decoy xoffset`) and then had nothing to report.

### 12.2 What the pink settles (and what §11.2 got wrong)

§11.2's table said "untouched = nothing wrote here (non-skin)". That is true
only of a pixel that was **never** skin. Nothing clears the scratch — that was a
deliberate design decision in §1 — so a pixel that was skin at any earlier frame
keeps its word forever while its age grows without bound. The pink is the trail:
the union of everywhere skin has been as the camera moved, painted MAGENTA
because `seen` is true and `age >= 2`.

So the pink is not a defect, it is more of the same evidence over a much larger
area: every one of those 77 852 pixels also matched its **own** identity, at its
own index, from an earlier frame. Correct addressing across most of the frame,
not just where skin happens to be now.

### 12.3 The latency, stated honestly

Cyan means `age == 0`: the resolver's word carries the same value of slot word 6
that the raygen read. That proves the two stages are in the same word-6 epoch,
and it does **not** convert to an exact frame count, because §8 established that
word 6 advances at the layer's TLAS-refresh rate rather than once per frame
(`wprobe2` showed a resolver running more than once per advance). The honest
claim is: **the raygen sees the resolver's word within one epoch, and never
sees a stranger's.** A feature that needs a real frame number must own its own
counter -- an `OpAtomicIAdd` in the scratch header, which `selftest_bda.sh` case
G already proves works there.

### 12.4 The one requirement 12.2 hands to the feature

The pink trail is the shipping failure mode made visible: **a stale word is
indistinguishable from a fresh one unless it is asked.** A pore normal read out
of the scratch with no validity test would be applied to whatever geometry has
since moved under that pixel -- a smear exactly the shape of the pink.

So the Stage 3b feature carries a key, not just a value:

```
word 0   the pore normal, octahedral, 2 x snorm16 packed
word 1   a validity key: the resolver's own depth or instance hash
word 2   the write's epoch (shader-owned atomic, not slot word 6)
```

and the raygen applies the normal only when the key matches its own hit and the
epoch is current. That is ordinary work now: every mechanism it needs has been
shot on screen.

### 12.5 Files and state

Nothing changed in this section -- it is a reading, not a build. The rung that
produced it is `bda-xprobe`, content `c1fbf29b151ca333`, layer
`79de001e17884937d0a317fc649bccbb`, gates 10/10, self-test 93/93.
