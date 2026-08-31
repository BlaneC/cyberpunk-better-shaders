# 75 — Sun-only fuzz: proven, then parked at the user's request (2026-08-31)

## 0. Verdict

Mid-investigation the user reversed the ask: *"the peach fuzz shader is
incredible like 99 percent of the time. Keep it how it is."* The shipped
state is `74`'s stack, unchanged: `gi-50b-bleed-oil-sheen` (half oil, half
fuzz k=0.5, direct+bounce bleed). **Nothing was undone because nothing was
built** — the whole sun-gate investigation was read-only census scripts.
This doc exists so the finding isn't re-derived if the ask comes back.

## 1. The parked request

Gate the peach-fuzz lobe to SUN light only (oil and bleed untouched), and
make the fuzz carry the sun's time-of-day colour. The second half is free
once the first half works: the lobe is spliced UPSTREAM of each module's
light-colour multiply (73 §2), so a sun-gated fuzz is sun-coloured by
construction — golden at dusk, white at noon, blue-grey moon.

## 2. The finding — a working sun-site discriminator (do not re-derive)

Census over the 77 parent modules in
`dev/disasm/peach.gi-50-bleed-oil-sheen/asm/` (find_ggx_sites ∩
find_sheen_inputs, 457 sites):

- **Loop membership splits the sites.** Classify each GGX site by whether
  it sits inside any `OpLoopMerge` body (merge label bounds the range):
  **191 unlooped (U) / 266 looped (L)**. The loops are the light-list
  loops; the unlooped sites are the per-pixel celestial light.
- **U sites read an exclusive cbuffer slot; L sites never do.** Walk each
  site's NoH back through arithmetic/phis (depth 16) to
  `OpLoad ← OpAccessChain <base> %uint_0 %uint_N` cbuffer loads, base
  resolved through the bindless array (`cbv@<idx-expr>` — identity is
  per-module, NOT global). Per module: ∩(U sites' slots) − ∪(L sites'
  slots). Result: **slot index 5 is an exclusive common U read in 75 of
  the 76 U-bearing modules** — the sun/moon direction. Discriminator:
  `sun site := unlooped ∧ NoH-chain reads the module's slot 5`.
- **Two exceptions, both already the known odd modules.**
  `ab0bc2fee876d489`: 0 U sites (20 L) — writes a v4uint sample-index
  buffer, cannot affect pixels (46 §12); would ship fuzz-free under sun
  scope, needs the `peach_sites==0` die relaxed. `99bb7c2698997b2a`: its
  single U site (line 54600) roots in `OpRawAccessChainNV` storage-buffer
  loads plus cbv slots {0,1,2,8,9,10,11,56,58} — **no slot 5 even at
  depth 40**; unprovable, so under the die-don't-guess rule its U site is
  excluded and the module ships fuzz-free (its 61 L sites read slot 77).
- **Dead end, recorded:** the first discriminator attempt
  (dynamic-vs-fixed AccessChain index feeding NoH) found ZERO dynamic
  loads — light data flows through bindless CBVs, fetches and phis, not
  indexed cbuffer reads. Loop membership is the real signal.

## 3. If it ever gets built

`peach_sun` float knob (0=all, 1=sun-only) in `build_peach`
(dev/patch_subtype_probe.py:739): skip L sites, skip U sites without the
slot-5 read (report `sun_sites`/`skipped_local`/`skipped_unproven`), relax
the zero-site die for ab0bc2fe/99bb7c26 under sun scope only; restore
`k_peach=1.0` (the daylight level the user called perfect — the dim path
is dead by construction); wire through `build_gi_bleed_sheen.sh`. The
useful A/B twin is a no-fuzz `gi-50b-bleed-oil` — pre-register: indoors
the sun-only candidate must be pixel-close to it; visible indoor fuzz =
leak. Estimated: one short session.

## 4. State

No files changed for this investigation. The commit accompanying this doc
is the accumulated 71–74 work (ear glow v5, oil, targeted fuzz, half-oil +
bounce-bleed) plus this doc.
