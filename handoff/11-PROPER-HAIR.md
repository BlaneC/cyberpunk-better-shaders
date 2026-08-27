# 11 — What a proper hair shader would take

Written 2026-08-26, after `10-DISPATCH-TRUTH.md` identified the shaders that
actually own hair pixels. This document answers one question: **what would it
take to shade hair with a real strand tangent — read from the hair's own
texture — instead of estimated from the normal field?**

It is a scoping document, not a plan of record. The decision point in §6 comes
first.

---

## 1. Where we actually stand

`10-DISPATCH-TRUTH.md` established that the modules this project had been
patching mostly never run. Fixing the class-anchor (commit `ba79030`) brought
three previously-unreachable modules into coverage:

```
d5166c0f1ea464b9    7ae88cd87950a898    03dc7a51279e7427
```

Isolated to those three, with the hunt palette and nothing else installed, the
game showed:

- **yellow along the sunlit rim of the hair**, following the sun exactly and
  stopping where the sun stops
- boundaries **stair-stepped in ~8px blocks** — tile-classification
  granularity, not geometry
- the shadowed bulk of the hair keeping its original colour
- **no red on skin at all**

Evidence: `photomode_26082026_223354.png` (repo root).

Three things follow, all of them firsts for this project:

1. These modules **demonstrably shade hair on screen.** Every earlier "it
   works" claim was creation counts or another mod's output (`09` D11).
2. **Class 4 is hair**, confirmed independently of the original class hunt.
3. They shade hair **and not skin** — consistent with shaders that compare
   `class == 4` and `OpSwitch` on it, which is exactly why the old skin-pinned
   anchor could never find them.

Their scope is the **sunlit rim only**. Shadowed hair belongs to the `&31`
local-light permutations; indirect belongs to the coarse 320×360 GI resolvers.

---

## 2. What that shader can see

Read off `dev/disasm/compute/d5166c0f1ea464b9.dxil.spvasm`. Five fetches, all
bindless, all screen-space:

| fetch | contents | evidence |
|---|---|---|
| `%163` | depth | feeds `%173 = u.x*d + u.y`, tested `< 1.0` against a uniform |
| `%176` | albedo rgb + `.w` | components **squared** (`%204–%206`) — sRGB→linear |
| `%182` | normal + `.w` | components **−0.5** (`%207–%210`) then `dot(v,v)` normalize |
| `%188` | `.x` metal-ish (`< 0.1` test), `.y` **F0/roughness** (`NMax(x, 0.04)`), `.z`/`.w` **×255** (8-bit ids) | `%368`, `%220`, `%371`, `%224` |
| `%194` | material `uint4`; `.y >> 5` = class | `%196`, `%203` |

**No tangent. No UVs. No material textures.**

That is the blocker, and it is structural rather than incidental. A deferred
resolve has no texture space: it cannot sample a flow map because it does not
know where on the hair card the pixel sits. This is the same wall
`03-HAIR-WORK.md` hit from the other direction ("none stored, but one can be
estimated"), and it is the entire reason the structure tensor exists.

**There is also no free channel to put one in.** Every component this shader
reads has a live consumer: `%181` (albedo.w), `%187` (normal.w), `%190`–`%193`
(all four misc channels). Checked individually; none is dead.

---

## 3. Route 1 — deliver the tangent through the G-buffer

The real answer to "get the direction from the texture". The hair's **fragment
shader** is where texture space exists: it has the UVs, the interpolated mesh
tangent, and whatever flow/normal maps the material binds. Encode the strand
direction there; read it back in these three compute modules.

Requirements, in order:

1. **Find the hair G-buffer writers.** Fragment shaders whose material writes
   class 4. The layer maps compute pipelines → modules already; extending the
   same machinery to `vkCreateGraphicsPipelines` + `vkCmdDraw*` is a modest
   addition (see §5).
2. **Confirm what the hair material actually binds.** If a flow/tangent map is
   present, the tangent is a texture read. If not, hair cards still carry a
   consistent V direction in the mesh tangent — worse than a flow map, far
   better than a structure tensor.
3. **Find bits to carry it.** Two channels (octahedral, or one angle plus a
   confidence bit). This needs the **capture**, not the shaders: we need the
   render-target *formats*, which the disassembly does not give. Candidates:
   the low bits of `%192`/`%193` (they are `×255`, so 8-bit ids), or normal
   precision. Every other reader of those bits must be surveyed first — this
   is the part that can quietly corrupt unrelated materials.
4. **Patch writer and reader as a matched pair.** Include a tag bit so a
   mismatched pair (one swapped, one not — routine during iteration, and
   guaranteed after a game patch) degrades to vanilla rather than to garbage.

This is a real project, not a splice. Steps 1–3 are each their own
investigation, and step 3 is the one that can break other materials.

---

## 4. Routes 2 and 3

**Route 2 — fake it at G-buffer time.** Write an anisotropically-bent normal,
or direction-dependent roughness, from the hair fragment shader. No delivery
problem, no bit-stealing, no coordination between two shaders. But lighting is
unknown at that point, so it buys a stretched-looking highlight, not a real
dual lobe. Cheap and shippable; low ceiling.

**Route 3 — the closest-hit shader.** The CHS has the hit triangle, vertex
attributes and material bindings, so a true tangent is computable there.
But `07-COMPUTE-RESOLVE.md` established the CHS produces *samples* which
compute resolves — so a CHS-side tangent still has to reach the resolve, and
Route 1's delivery problem returns unchanged. Only worth it if CHS-side
shading turns out to contribute directly.

---

## 5. Tooling that would be needed first

The dispatch tracking added in `0508789` covers compute only. Route 1 step 1
needs the graphics-side equivalent:

- hook `vkCreateGraphicsPipelines`, mapping pipeline → fragment module (copy
  the id **by value**, per the bug fixed in `0508789`)
- hook `vkCmdDraw*`, logging bound pipeline + module id, deduped per pipeline
- that yields the set of fragment shaders that actually draw, which can then be
  filtered for class-4 writers

Same shape as `dispatch_maybe_log`. Perhaps 60 lines.

**Select by dispatch, not by constants** (`10` §3). The `1/π + k` anchor scan
mis-selected the target family for this entire project; the graphics-side hunt
should be driven by what draws, from the start.

---

## 6. The decision point that comes first

**Do not start Route 1 before running the additive probe.** It is already
built and staged: those same three modules, isolated, with

```
spec_add = 8      (additive — survives an output whose value is zero)
hair diffuse x4   (w_wrap=1.0, k_diff=4.0, r_max=8.0)
all lobes off     (m_aniso=0, m_dual=0, k_sheen=0, roughness identity)
```

- **The sunlit rim changes** → our splice sites feed hair's visible output.
  The mechanism works end to end and every earlier null was magnitude. Note
  these modules carry only **1–2 GGX sites and 1–2 wrap sites each** (against
  10+ in the modules previously patched), so even a working effect is
  rim-sized — consistent with "I can't tell" at tuned defaults.
- **The rim does not change** → the sites do not feed hair's visible output,
  even though the modules demonstrably shade it. Route 1's *reader* side then
  has nowhere to land either, and this document needs rewriting before any of
  it is attempted.

---

## 7. Honest ceiling

Worth stating before anyone commits:

- These three modules own the **sunlit rim**. A complete hair shader means
  solving tangent delivery *and* applying it consistently across three
  families — sun/direct (`>>5`), local-light (`&31`), and the coarse GI
  resolvers — of which only the first is confirmed to shade hair at all.
- Tile granularity is visible in the screenshot. Whatever ships inherits it.
- The `&31` family has never been confirmed to shade anything on screen. It
  should get the same isolated hunt treatment these three just got, before it
  is assumed to work.

What is confirmed and shippable today remains the **hair shadow-leak fix** and
the **SSS kernel**. The shadow fix works because it changes ray *visibility* —
geometry, not shading math — which is why it never depended on any of this.
