# 30 — Backlit skin transmission: the build

`29-FACE-TRANSLUCENCY-AND-RAYS.md` said the ear/nose backlight was a **go**
and ranked the routes. This is what got built from it. Part B of `29` (more
rays on skin) is **not** in this document and nothing for it was written —
that was scoped out on request.

Nothing here has been seen on screen. Everything below is offline evidence:
`spirv-val`, byte comparisons, and a sweep over the whole anchored module
set. The ledger rule (`19`, `28`) still applies — until an A/B says
otherwise, this is an experiment with a switch, defaulting off.

---

## 1. What the pass does

Barré-Brisebois translucency, added to the skin diffuse at the point where
the compute lighting evaluators write it out:

```
L    = normalize(cbv sun direction)          ; reissued, see §3
H    = normalize(L + N * t_distort)
back = saturate(-dot(V, H)) ^ t_power
mask = back * t_thick
     * lerp(1, saturate(-dot(N, L)), t_wback)    ; the light is behind me
     * lerp(1, 1 - sunShadow,        t_wshadow)  ; ...and I am in shadow
     * lerp(1, blockerMask,          t_wblock)   ; ...my OWN shadow
T_c  = lightColour_c * lerp(1, albedo_c, t_walbedo) * tint_c * mask
acc_c = acc_c * lerp(1, 1 - t_damp, isSkin) + select(isSkin, T_c, 0)
```

`saturate(-dot(N, L))` is the term that keeps this off directly-lit skin, and
it is the reason the pass does not need a per-pixel thickness channel to be
better than a uniform wax glow: it is nonzero only where the light is on the
far side of the surface, which is the geometric content of "the light is
coming through the ear".

`29` A4 ranked four thickness routes and recommended R1 × a local proxy. That
is what shipped, with the proxy split into three separately-weighted masks so
the experiment can attribute a result to one of them:

- **`t_wback`** — `saturate(-N·L)`, always available, on by default.
- **`t_wshadow`** — `1 - sunShadowMask`, recovered in **78 of 78** spliceable
  modules, off by default.
- **`t_wblock`** — the engine's own `CharacterLightBlockers` term, present in
  **40 of 84**, off by default. This is the `29` A3 finding turned around:
  the engine computes a per-pixel "the sun is on the far side of this
  character's own volume" signal and today only *subtracts* with it. It is
  the one mask that can tell "in my own head's shadow" from "in a building's
  shadow", which no purely local term can do.

`t_damp` (scale the existing skin diffuse down so the added light is a
redistribution rather than a brightening — `23` §4's ship-phase requirement)
is implemented and defaults to **0**, i.e. off, so it cannot confound the
first A/B. Turn it on before anything ships.

## 2. Why it could not go where Tier-1 and Tier-3 go

This is the trap `29` A5 named, and it is worth restating because it is the
single likeliest way this feature ships as a silent no-op:

The per-light lighting arm — where c1 and the gloss splice — sits under

```
%s = NClamp(cbv.y + shadowMaskTexel, 0, 1)      ; the sun shadow
%g = (dot(lightCol, lightCol) * %s) > 0
     OpBranchConditional %g <lighting> <merge>
```

A backlit ear **is** shadowed on the face you are looking at — that is what
"the light is behind it" means — so a transmission term spliced inside that
arm is multiplied by zero at exactly the pixels it exists for. It would be
`27` §7.5's failure class one layer deeper: not "the swap did not run", but
"the swap ran, on the wrong side of a branch".

So Tier-4 splices at the **light-gate merge** instead — the predecessor of
the block that holds the diffuse `OpImageWrite`, reached whether or not the
light arm ran. It also lands upstream of the module's own output scale and
its `NMin(…, 65000)`, which is what GOTCHAS' "scale before a clamp, never
after" asks for.

## 3. Two things the detector had to get right

**The write block has a bypass edge.** The diffuse accumulators are `OpPhi`s
at the top of the write block, and one incoming edge is the depth/sky
early-out that phis in a literal zero. Adding the term *inside* the write
block would light up the sky. So the term is spliced into each incoming block
that actually carries light — identified as the ones where the G-buffer
inputs dominate, which the early-out by construction does not. The sweep
reports **0 uncovered light-carrying edges** across all 78 spliceable
modules, so no module gets a term on only some of its paths.

**The sun direction does not dominate the splice point.** It is loaded inside
the light gate. Its `OpAccessChain` operands are module-scope (a global
variable and constants), so the load is *reissued* at the splice point rather
than read. Same for `saturate(-N·L)` and the blocker mask, both recomputed
from inputs rather than read as values.

## 4. The sibling sweep — `dev/survey_translucency.py`

GOTCHAS 3, and `29` A6 made it non-optional: the four evaluators read by hand
are a sample, not the schema. The survey runs the **real** detector — the
same `find_transmission_site()` the patcher calls, imported, not
reimplemented — over every disassembled compute lib and prints one row per
module plus a tally of every reason it declined.

```
$ dev/survey_translucency.py
240 modules   spliceable 78   with light blocker 40   phi-edge splice 78
   uncovered light-carrying edges: 0
   of the spliceable: albedo recovered 78, sun-shadow mask recovered 78

  156  not a Disney diffuse module
   78  OK
    2  no radiance image writes
    2  no splice point where the inputs dominate
    1  no diffuse write among 1 radiance writes
    1  no c1 sites
```

156 of the 240 disassembled libs are not in the anchored set at all; of the
**84 anchored** libs, 78 are spliceable and 6 are not. All four
dispatch-proven evaluators (`2e73a32c35778d85`, `4d46848998312027`,
`9a3fa53c53a3a21b`, `20e6c7b3626ae0d6`, `~/callisto_swap.jsonl`, 8 dispatch
events each) are in the 78, all four carry the light blocker, and the site
the detector picks for `4d46848998312027` is block `%1565` writing image
`%49` — **the same site `29` A5 derived by hand**, arrived at independently.

Emitting into all 84 and validating gives:

```
   75  spirv-val clean
    7  declined: no material G-buffer read found (neither >>5 nor &31)
    2  structural (no radiance write / ambiguous diffuse write)
```

The 7 with no material class read cannot be gated on skin and are skipped by
the existing Tier-1 machinery too — the shipping build patches 77, not 84.

## 5. Three bugs, and what found each

The first two were invisible on `4d46848998312027` and broke a large minority
of its siblings — the whole argument for GOTCHAS 3. The third was invisible in
the sweep and only showed up when the pass ran inside the real patcher next to
the other tiers, which is the argument for reading the emitted SPIR-V at least
once instead of trusting `spirv-val` and an exit code.

**`OpSelectionMerge` adjacency.** Inserting "just before the terminator"
is wrong in a structured block: `OpSelectionMerge`/`OpLoopMerge` must remain
the second-to-last instruction. **47 of 84** modules failed `spirv-val` with
*"OpSelectionMerge must immediately precede either an OpBranchConditional or
OpSwitch"*. Fixed by `_pre_terminator()`, which walks back over any merge
instructions.

**Stopping at the first matching source.** The diffuse albedo is
`basecolour * (1 - metalness)`, so walking back from its **red** channel
reaches component 0 of the basecolour texel *and* component 0 of the
metal/roughness texel. Taking whichever the traversal popped first made the
red channel disagree with green and blue, and the albedo was rejected in
**70 of 78** modules — a silent quality loss, not an error. Fixed by
collecting every candidate source per channel and intersecting the three.

**Pass ordering against pending edits.** The patchers defer their insertions
to `apply_edits()` at the very end, but `replace_all_uses()` rewrites
`mod.lines` immediately. Between the two, the module references ids whose
defining instruction does not exist yet. Tier-1's c1 rewrite points the
diffuse product chain at exactly such an id — so with Tier-4 running after it,
the detector's backwards walk from the image write dead-ended before reaching
any diffuse scalar and the pass reported *"no diffuse write among 2 radiance
writes"* and emitted **nothing**. `spirv-val` was clean, the build succeeded,
and the module was unchanged: the `27` §7.5 symptom produced entirely by
patcher ordering. Fixed by running Tier-4 first, and now GOTCHAS 12.

A third, earlier one is worth recording because it is the same shape as `29`'s
own warning about anchoring: the first cut matched the per-channel diffuse
product by its **nesting**, `((c*a)*NoL)*fd`. dxil-spirv associates it
differently between permutations, so 33 of 84 declined. Flattening the
multiply tree and comparing factor *sets* — the mode-independent half of the
signature, GOTCHAS 4 — took it from 47 to 78.

## 6. Identity, and what that proves

`t_thick = 0` emits nothing at all, and without `--with-translucency` the
knob is forced to 0. So a build without the flag must be byte-identical to
one made before the pass existed:

```
built 77 modules, --tier skin, no flag
vs the parked ~/.local/lib/callisto/skin.set/off:
  identical=77  differ=0  missing=0
```

That is the check that says the Tier-4 code cannot be responsible for a
change in any existing set.

## 7. The ladder, and why it is a 5 × 5 matrix

Transmission splices the **same 84 modules** as the gloss, and the layer
serves the first file it finds for an id, so they cannot be two overlays —
the same constraint that produced `build_ptq.sh`'s fifteen combinations. And
the knobs are `OpConstant`s baked at build time, so neither can be a live
slider (`26` §5). Both are therefore ladders, and the *combinations* are
pre-built:

```
./dev/patch_compute_skin.sh --sets           # 5 gloss rungs, as before
./dev/patch_compute_skin.sh --sets --trans   # + the 5x5 matrix
```

parked as `skin.set/<gloss>+t<trans>/`. `sync_settings.sh` composes the name
from `skinspec` and the new `skintrans` key. A combination that was never
built falls back to the **gloss-only set of the same strength**, not to off:
dropping to off would move the gloss as well, and the next A/B would credit
transmission with a difference that was really the gloss shifting underneath
it.

Levels (`TLEVELS` in `dev/patch_compute_skin.sh`, `TRANS_LEVELS` in
`init.lua` — they must stay in step):

| level | `t_thick` | `t_power` | what it is for |
|---|---|---|---|
| `subtle`  | 0.25 | 16 | a hint at the silhouette only |
| `medium`  | 0.55 | 12 | the intended look: ears read warm against the sun |
| `strong`  | 1.00 | 8  | pushed; the whole backlit side glows |
| `extreme` | 2.50 | 2  | **diagnostic** — `t_wback=0` drops the geometry gate |

`extreme` is not a look. It answers "does this splice reach the screen at
all" — the `27` §7.5 question — before the aesthetic one is worth asking.
Expect it to look wrong.

The two mask experiments are deliberately **not** rungs, because they are not
strengths. They are forwarded verbatim to every rung:

```
./dev/patch_compute_skin.sh --sets --trans --set t_wshadow=1
./dev/patch_compute_skin.sh --sets --trans --set t_wblock=1
```

## 8. How to run the experiment

1. `./dev/patch_compute_skin.sh --sets --trans`. The build asserts every rung
   differs from `off` **and** from the rung below it on its own axis — a knob
   that never reached the shader would make two rungs byte-identical and fail
   the build rather than produce an uninterpretable A/B.

   It has been run. 25 sets parked, and the numbers cross-check the sweep:
   every gloss step moves **77 of 77** modules, every transmission step moves
   **75** — exactly the 75 the sweep predicted would emit, with the 2
   structural declines still receiving c1 and the gloss. The two axes moving
   different counts is itself the evidence that they are independent.
2. Launch through the Steam launch options (otherwise `sync_settings.sh`
   never runs and the selector is decorative — the CET page will say so).
3. Set **Backlit skin transmission → Extreme**, relaunch. If backlit skin
   does not visibly change, stop: nothing downstream is interpretable, and
   the question is a dispatch question, not a tuning one.
4. If it does: **Medium**, and find a low sun with a face between you and it.
   Ears and nostrils are the test, not cheeks.
5. Then, and only then, the masks. `t_wblock=1` is the interesting one — it
   is the only signal in the frame that knows the character's own geometry is
   what is blocking the sun.

`~/callisto_launches.log` records the content hash of what was actually
served each launch, so an observation can be attributed to a rung rather than
to a name. Use it — `26` §7 is the session where a result was credited to a
set that had never been launched.

## 9. What is not done

- **Part B of `29`** — per-material ray budget. Not started, out of scope.
- **`t_damp` defaults to 0.** The energy damp is implemented but off, so this
  currently *adds* light rather than redistributing it. `23` §4 requires it
  before anything ships.
- **No per-pixel thickness.** `29` A4's route 3 (bind the engine's skin
  back-depth target) is still the only route to a real thickness signal, and
  it is still an offline-replay job that has not been done. The masks are a
  proxy.
- **Nothing has been observed.** Every claim above is `spirv-val`, a byte
  comparison, or a sweep count. Nothing in this document is committed either
  — the working tree carries it; commit when you are ready to.

## 10. Files

- `dev/patch_compute_skin.py` — `find_transmission_site()` (detector),
  `build_skin_transmission()` (emitter), `--with-translucency`.
- `dev/survey_translucency.py` — the GOTCHAS 3 sibling sweep, sharing the
  detector with the patcher.
- `dev/patch_skin_brdf.py` — the `t_*` knobs.
- `dev/patch_compute_skin.sh` — `TLEVELS`, `--trans`, the matrix build and
  its per-axis difference assertions.
- `release/game/red4ext/plugins/CallistoSSS/sync_settings.sh` — `skintrans`,
  the composed set name, the gloss-preserving fallback.
- `init.lua` (and its mirror) — `TRANS_LEVELS`, the selector, and the two
  silent-no-op warnings.
- `handoff/GOTCHAS.md` — rule 12, the pass-ordering constraint from §5.
