#!/usr/bin/env python3
"""
patch_agx.py -- replace Cyberpunk's tonemap curve with AgX, in the LUT
generator.

WHY THIS SHAPE (see handoff/18-AGX-FEASIBILITY.md):

The game does not upload a tonemap LUT -- it GENERATES one
(`CRenderNode_GenerateTonemappingLUT`).  The generator is a single compute
module (`b174eb4af0fea652` in capA): 8x8x8 workgroups over a 48^3 grid, reads
the authored 32^3 grading LUT, writes one 48^3 RGBA16F LUT, and contains
exactly ONE OpImageWrite.

Its prologue decodes the grid index through a log2 shaper:

    t          = gid / (lutSize - 1)
    linear.rgb = Exp2((t - shaperOffset) / shaperScale)

so `linear` is scene-referred HDR radiance -- exactly AgX's input domain.

WHAT AgX IS FED (`--set grade=`, and the reason for handoff/20):

Reading the raw shaper skips ~1900 lines that are NOT dead weight.  Between it
and the splice the generator applies the shadow/mid/highlight balance, the
basic grade, the AUTHORED PER-AREA GRADE LUTs (8 slots, CPU-weighted, the
mechanism the game cross-fades locations with) and then `x cbv[42].z`, the
per-grading-setup EXPOSURE.  `grade=0` discards all of it -- and discarding
the exposure is the expensive half: AgX's ceiling is max_ev = 4.026 (~16.0
linear), so un-exposed daylight radiance clips to white whatever the look says.

    grade=1 (default)  graded x exposure   -- the game's authored look, tone
                                              mapped by AgX instead of CDPR's
                                              filmic spline
    grade=2            graded, pre-exposure -- A/B leg: isolates "the grade
                                              came back" from "the exposure
                                              came back"
    grade=0            raw shaper           -- the pre-handoff/20 behaviour

    input --> [NMax 0] --> [pre_gain] --> [inset] --> log2+normalise
          --> sigmoid --> [look] --> [hue_restore] --> [outset]
          --> EOTF --> [Rec.709 -> AP1] --> lerp(vanilla, agx, mix)
          --> the game's own ACES output transform --> OpImageWrite

WHERE TO SPLICE (this cost one wrong build -- see handoff/18 "The colour-space
bug"):  the tail of this shader is a stock ACES output transform.

    %3032..%3034  ACEScg (AP1)        <-- splice here (--site ap1, default)
      [AP1 -> CIE XYZ]                    (matches the ACES matrix to 8e-8)
      [D60 -> D65 CAT, conditional]
    %3064..%3066  CIE XYZ             <-- NOT RGB.  --site pre wrote Rec.709
      [CBV 21/22/23 display matrix]       here; the display matrix's large
      [per-mode encode: clamp / PQ]       off-diagonals then split every
                                          neutral pink-vs-cyan.
The LUT's *input* domain is Rec.709 linear (the first matrix in the shader is
Rec.709 -> XYZ, fed straight from the shaper), so AgX's input needed no change.

Knobs (--set k=v):
  min_ev  -12.47393   log2 range floor (AgX default)
  max_ev    4.026069  log2 range ceiling
  slope_r/g/b  1.0    per-channel look slope (golden uses 1.0/0.9/0.5)
  offset      0.0     look offset
  power       1.0     look power   (punchy: 1.35)
  sat         1.0     look saturation (punchy: 1.4)
  eotf        2.2     0 = leave display-encoded; >0 = pow(x, eotf) to linear.
                      Required at --site ap1: that site holds LINEAR display
                      light, and AgX's sigmoid output is display-encoded.
  mix         1.0     0 = vanilla, 1 = full AgX. The A/B knob.
  grade       1       what AgX is fed: 1 = the graded, exposed scene colour
                      (the authored per-area grade and exposure survive),
                      2 = graded but pre-exposure, 0 = the raw shaper (the
                      behaviour before handoff/20).  Only the two HDR
                      permutations can honour it; the eight SDR ones warn and
                      fall back to 0.
  pre_gain    1.0     multiply the input before AgX.  min_ev/max_ev are an
                      ABSOLUTE log window, so grade=1's unknown cbv[42].z
                      slides the whole image inside it; this compensates
                      without re-deriving the look parameters.
  hue_restore 0.0     0..1.  AgX drives everything past max_ev to white, so a
                      warm grade cannot make the sun yellow again on its own.
                      Pushes highlights back toward the input's chroma ratios,
                      weighted by luma^2.  0 emits nothing.
  tint_r/g/b  1.0     final per-channel multiply. White balance -- and the
                      DIAGNOSTIC: `--set tint_g=4 tint_r=0.15 tint_b=0.15`
                      makes the frame violently green, so "is this module on
                      screen at all" stops being a question of taste.

  --look none|punchy70|punchy|golden  presets applied before --set

Usage:
  python3 dev/patch_agx.py <module.spvasm> --outdir swaps.agx/ [--set mix=0.5]
"""
import argparse, json, os, re, sys, subprocess, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
from patch_shadow_brdf import CFG

# AgX rotated primaries ("inset"), row-major.  Rows sum to ~1.
AGX_IN = ((0.842479062253094,  0.0784335999999992, 0.0792237451477643),
          (0.0423282422610123, 0.878468636469772,  0.0791661274605434),
          (0.0423756549057051, 0.0784336,          0.879142973793104))
# Inverse ("outset"), row-major.
AGX_OUT = (( 1.19687900512017,   -0.0980208811401368, -0.0990297440797205),
           (-0.0528968517574562,  1.15190312990417,   -0.0989611768448433),
           (-0.0529716355144438, -0.0980434501171241,  1.15107367264116))
# 6th-order fit of the AgX contrast sigmoid (the widely used
# agxDefaultContrastApprox), highest order first.
SIGMOID = (15.5, -40.14, 31.96, -6.868, 0.4298, 0.1191, -0.00232)

# The generator's tail is a stock ACES output transform whose working space is
# ACEScg (AP1).  `%3032..%3034` are AP1; `%3064..%3066` are already CIE XYZ.
# AgX emits Rec.709, so the splice needs Rec.709 -> AP1.  Derived from this
# shader's own AP1->XYZ, D60<->D65 CAT and Rec709->XYZ constants
# (inv(AP1_XYZ) @ inv(CAT) @ R709_XYZ), so the round trip is exact in-pipeline;
# it agrees with the canonical ACES matrix to 2.6e-6.
REC709_TO_AP1 = ((0.613097676, 0.339522152, 0.047379776),
                 (0.070194057, 0.916356391, 0.013451934),
                 (0.020615777, 0.109570032, 0.869815004))
# Rec.709 -> CIE XYZ (D65), the canonical published matrix.  The generator's
# FIRST constant 3x3 -- it is what the graded, exposure-scaled scene-linear
# colour is fed into, which is what PROVES that value's colour space (GOTCHAS
# #5).  Used to LOCATE the graded input, not to compute anything.
REC709_TO_XYZ = ((0.4123908, 0.3575843, 0.1804808),
                 (0.2126390, 0.7151687, 0.0721923),
                 (0.0193308, 0.1191948, 0.9505322))
# ACES AP1 -> CIE XYZ (D60).  Used to LOCATE the splice, not to compute it.
AP1_TO_XYZ = ((0.6624541811, 0.1340042065, 0.1561876870),
              (0.2722287168, 0.6740817658, 0.0536895174),
              (-0.0055746495, 0.0040607335, 1.0103391003))
# The Stephen Hill ACES fit (`ACESInputMat` / `ACESOutputMat` from aces.hlsl),
# reproduced coefficient-for-coefficient by four of the eight SDR
# permutations.  ACESInputMat's domain is Rec.709 linear BY DEFINITION, so
# finding it applied to the value at the SDR splice is what proves that value
# is Rec.709 -- the SDR modules carry no Rec.709->XYZ to identify (GOTCHAS #5).
# They are a matched pair: the segment between them is Rec.709 in, Rec.709 out.
ACES_INPUT = ((0.59719, 0.35458, 0.04823),
              (0.07600, 0.90834, 0.01566),
              (0.02840, 0.13383, 0.83777))
ACES_OUTPUT = (( 1.60475, -0.53108, -0.07367),
               (-0.10208,  1.10813, -0.00605),
               (-0.00327, -0.07276,  1.07602))
LUMA = (0.2126, 0.7152, 0.0722)

DEFAULTS = dict(min_ev=-12.47393, max_ev=4.026069,
                slope_r=1.0, slope_g=1.0, slope_b=1.0,
                offset=0.0, power=1.0, sat=1.0, eotf=2.2, mix=1.0,
                tint_r=1.0, tint_g=1.0, tint_b=1.0,
                grade=1.0, pre_gain=1.0, hue_restore=0.0)
# `mix` is an A/B knob, not a strength knob: it cross-fades AgX against the
# game's own tonemap, and blending two different curves flattens contrast --
# `half` reads bright, grey and desaturated rather than "less AgX".  To soften
# a look, scale the look parameters toward neutral instead, as punchy70 does.
LOOKS = {
    'none':   {},
    'punchy': dict(power=1.35, sat=1.4),
    # 68% of the way from neutral to punchy
    'punchy70': dict(power=1.24, sat=1.27),
    # punchy70 with the chroma pulled back 7.5% and nothing else touched.
    # `sat` multiplies the distance from luma, so the number IS the chroma
    # scale: 1.27 -> 1.175 is 7.5% less saturated, the middle of the 5-10%
    # band.  Contrast (`power`) is deliberately left alone -- desaturating by
    # softening the curve instead would flatten the image as well.
    'punchy70desat': dict(power=1.24, sat=1.175),
    'golden': dict(slope_r=1.0, slope_g=0.9, slope_b=0.5, power=0.8, sat=0.8),
}


# ---------------------------------------------------------------- detection
def find_lut_write(mod):
    """The single OpImageWrite whose texel is an OpCompositeConstruct %v4float."""
    hits = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        img, coord, texel = m.groups()
        tl, td = mod.find_def(texel)
        tm = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      td or '')
        if tm:
            hits.append(dict(line=i, img=img, coord=coord, texel=texel,
                             texel_line=tl, comps=list(tm.groups())))
    if len(hits) != 1:
        die(f"{mod.name}: expected exactly 1 v4float OpImageWrite, found {len(hits)}"
            " -- this does not look like the tonemap LUT generator")
    return hits[0]


def find_shaper_exp2(mod, write_line):
    """The three Exp2 results that decode the grid index to linear radiance.

    Per-component taint from gl_GlobalInvocationID: the shaper's three Exp2
    calls must each be tainted by a *different* gid component, which is a much
    stronger check than "the first three Exp2 in the file".
    """
    # ids loaded out of gl_GlobalInvocationID, by component
    seeds = {}
    chain = {}   # accesschain id -> component
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpAccessChain %_ptr_Input_uint '
                     r'%gl_GlobalInvocationID %uint_(\d)\s*$', ln)
        if m:
            chain[m.group(1)] = int(m.group(2))
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpLoad %uint (%\w+)\s*$', ln)
        if m and m.group(2) in chain:
            seeds[chain[m.group(2)]] = m.group(1)
    if sorted(seeds) != [0, 1, 2]:
        die(f"{mod.name}: could not find all three gl_GlobalInvocationID loads")

    taint = {c: {seeds[c]} for c in (0, 1, 2)}
    # Straight-line prologue only: stop at the first control flow, which both
    # keeps the taint sound without a full CFG and proves dominance over the
    # write (everything before the first branch dominates the whole function).
    found = {}
    for i, ln in enumerate(mod.lines):
        if re.search(r'\bOp(SelectionMerge|LoopMerge|BranchConditional|Switch)\b', ln):
            break
        m = re.match(r'\s*(%\w+)\s*=\s*Op\w+(.*)$', ln)
        if not m:
            continue
        res, rest = m.group(1), m.group(2)
        ops = set(re.findall(r'%\w+', rest))
        e = re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ Exp2 (%\w+)\s*$', ln)
        for c in (0, 1, 2):
            if ops & taint[c]:
                taint[c].add(res)
                if e and c not in found and e.group(2) in taint[c]:
                    found[c] = e.group(1)
    if sorted(found) != [0, 1, 2]:
        die(f"{mod.name}: shaper Exp2 triple not found (got {sorted(found)}) "
            "-- the LUT domain is not the expected log2 encoding")
    for c in (0, 1, 2):
        dl, _ = mod.find_def(found[c])
        if dl is None or dl >= write_line:
            die(f"{mod.name}: shaper Exp2 for component {c} does not precede the write")
    return [found[0], found[1], found[2]]


def _find_mode_ladder(mod):
    """The output-transform mode ladder: several OpFOrdEqual on the same id."""
    ladder = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*%\w+\s*=\s*OpFOrdEqual %bool (%\w+) %float_(\d)\s*$', ln)
        if m:
            ladder.setdefault(m.group(1), []).append((int(m.group(2)), i))
    cand = [(v, sorted(l)) for v, l in ladder.items() if len(l) >= 3]
    if len(cand) != 1:
        die(f"{mod.name}: expected exactly one output-transform mode ladder, "
            f"found {len(cand)}")
    mode_id, entries = cand[0]
    return mode_id, entries, len(entries), entries[0][1]


def find_output_transform(mod):
    """The three values entering the output-transform matrix + mode encode.

    The tail of the generator is:

        %3085 = OpFMul %float <m00> <in0>          # 3x3 primaries matrix,
        %3086 = OpExtInst Fma  <m01> <in1> %3085   # rows from CBV 21/22/23
        %3087 = OpExtInst Fma  <m02> <in2> %3086
        ... (rows 1 and 2) ...
        %3094 = OpCompositeExtract %float <cbv> 2  # output-transform MODE
        %3095 = OpFOrdEqual %bool %3094 %float_0   # 0 = clamp (SDR)
        ...  == 1, == 2, == 3 (PQ / ST2084), == 4

    Splicing at <in0..2> puts AgX *before* the primaries conversion and the
    per-mode encode, so the game's own SDR clamp or HDR PQ path still runs on
    top.  That is what makes one patch correct in both SDR and HDR; splicing at
    the final OpImageWrite instead would overwrite the PQ encode with SDR
    values.  Returns (ids, insert_line).
    """
    mode_id, _, _, first_cmp = _find_mode_ladder(mod)

    # the last three matrix rows before the ladder
    rows = []
    i = 0
    while i < first_cmp:
        m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$', mod.lines[i])
        if m:
            acc, ins = m.group(1), [m.group(3)]
            lines = [i]
            j = i + 1
            while j < first_cmp and len(ins) < 3:
                mm = re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ Fma '
                              r'(%\w+) (%\w+) ' + re.escape(acc) + r'\s*$',
                              mod.lines[j])
                if not mm:
                    break
                acc = mm.group(1); ins.append(mm.group(3)); lines.append(j); j += 1
            if len(ins) == 3:
                rows.append((tuple(ins), lines))
                i = j
                continue
        i += 1
    if len(rows) < 3:
        die(f"{mod.name}: output-transform matrix not found ({len(rows)} rows)")
    rows = rows[-3:]
    if len({r[0] for r in rows}) != 1:
        die(f"{mod.name}: the last three matrix rows do not share their inputs")
    return list(rows[0][0]), [l for r in rows for l in r[1]], mode_id


def _const_matrices(mod, before):
    """Every 3x3 matrix with constant coefficients applied before `before`.

    Returns [(inputs, coeffs, lines)] for each run of three consecutive
    FMul/Fma/Fma rows that share their three input ids.
    """
    cv = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)\s*$', ln)
        if m:
            try:
                cv[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    rows, i = [], 0
    while i < min(before, len(mod.lines)):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$', mod.lines[i])
        if m:
            res, a, b = m.groups()
            coef, var = (a, b) if a in cv else (b, a)
            if coef in cv:
                acc, cs, vs, lines = res, [cv[coef]], [var], [i]
                j = i + 1
                while j < before and len(cs) < 3:
                    mm = re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ Fma '
                                  r'(%\w+) (%\w+) ' + re.escape(acc) + r'\s*$',
                                  mod.lines[j])
                    if not mm:
                        break
                    nr, x, y = mm.groups()
                    if x in cv:
                        c, v = cv[x], y
                    elif y in cv:
                        c, v = cv[y], x
                    else:
                        break
                    cs.append(c); vs.append(v); acc = nr; lines.append(j); j += 1
                if len(cs) == 3:
                    rows.append((tuple(vs), tuple(cs), lines))
                    i = j
                    continue
        i += 1
    out, k = [], 0
    while k + 2 < len(rows) + 1:
        grp = rows[k:k + 3]
        if len(grp) == 3 and len({g[0] for g in grp}) == 1:
            out.append((list(grp[0][0]), [g[1] for g in grp],
                        [l for g in grp for l in g[2]]))
            k += 3
        else:
            k += 1
    return out


def find_ap1_site(mod):
    """Inputs to the LAST AP1->XYZ matrix -- i.e. the value in ACEScg, just
    before the game's own ACES output transform (AP1->XYZ, optional D60->D65
    chromatic adaptation, the CBV display matrix, and the per-mode encode).

    Splicing here leaves that entire chain intact and correct, so one patch is
    right in SDR and in HDR.  Splicing at its OUTPUT instead (`--site pre`)
    writes Rec.709 into a slot holding CIE XYZ, which the display matrix then
    expands by its large off-diagonal terms -- neutrals split pink/cyan.
    """
    _, _, _, first_cmp = _find_mode_ladder(mod)
    hits = [m for m in _const_matrices(mod, first_cmp)
            if max(abs(m[1][r][c] - AP1_TO_XYZ[r][c])
                   for r in range(3) for c in range(3)) < 1e-5]
    if not hits:
        die(f"{mod.name}: no AP1->XYZ matrix before the mode ladder -- the tail "
            "is not the expected ACES output transform")
    ins, _, lines = hits[-1]
    return ins, lines


def find_graded_color(mod, with_exposure=True):
    """The GRADED, exposure-scaled scene-linear colour -- what the game's own
    tonemap curve is fed, and what AgX should be fed instead of the raw shaper.

    The generator's chain is

        Exp2 shaper  (raw Rec.709 scene-linear, per LUT cell)
          -> shadow/mid/highlight balance   (piecewise-affine, identity at
             neutral params, so still scene-linear)
          -> basic grade: sat / lift / gain / hue / channel mix  (cbv[0..7])
          -> [area grade LUT stack 1, taken iff cbv[42].y == 1]
          -> x cbv[42].z                    <-- EXPOSURE.  Returned by default.
        %399,%400,%401
          -> [Rec.709 -> XYZ] -> ACES chain -> CDPR filmic spline -> AP1 site

    Splicing AgX at the AP1 site while reading the *shaper* discards all of
    that: the authored per-area grade AND the per-grading-setup exposure.  The
    exposure matters most -- AgX's default ceiling is max_ev = 4.026 (~16.0
    linear), so un-exposed daylight radiance clips to white no matter what the
    look parameters say.

    Located by identifying the Rec.709 -> XYZ matrix against its published
    coefficients, so the returned triple's colour space is proven, not assumed
    (GOTCHAS #5).  That matrix occurs exactly once in each HDR permutation --
    unlike AP1->XYZ, which occurs twice and forces find_ap1_site into hits[-1].

    with_exposure=False peels the `x cbv[42].z` multiply back off and returns
    the pre-exposure graded triple, so a launch can tell the restored grade and
    the restored exposure apart instead of confounding them.
    """
    _, _, _, first_cmp = _find_mode_ladder(mod)
    hits = [m for m in _const_matrices(mod, first_cmp)
            if max(abs(m[1][r][c] - REC709_TO_XYZ[r][c])
                   for r in range(3) for c in range(3)) < 1e-5]
    if len(hits) != 1:
        die(f"{mod.name}: expected exactly one Rec.709->XYZ matrix, found "
            f"{len(hits)} -- cannot prove which value is the graded colour")
    ins, _, _ = hits[0]
    if with_exposure:
        return ins

    # each is `OpFMul <exposure> <graded>`; the exposure scalar is the operand
    # the three share, which is what identifies it without assuming an order.
    ops = []
    for i in ins:
        _, d = mod.find_def(i)
        m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d or '')
        if not m:
            die(f"{mod.name}: {i} is not the exposure multiply ({d!r})")
        ops.append((m.group(1), m.group(2)))
    common = set(ops[0]) & set(ops[1]) & set(ops[2])
    if len(common) != 1:
        die(f"{mod.name}: the three exposure multiplies share {len(common)} "
            "operands, expected exactly the scalar")
    exp_id = common.pop()
    pre = [b if a == exp_id else a for a, b in ops]
    if len(set(pre)) != 3:
        die(f"{mod.name}: pre-exposure triple is not three distinct ids ({pre})")
    return pre


def _cbv_component(mod, index, comp, as_uint=False):
    """Every id that is component `comp` of constant-buffer vector `index`."""
    def matches(pat, src=None):
        out = set()
        for ln in mod.lines:
            m = re.match(pat, ln)
            if m and (src is None or m.group(2) in src):
                out.add(m.group(1))
        return out

    chains = matches(r'\s*(%\w+)\s*=\s*OpAccessChain \S+ (%\w+) %uint_0 %uint_'
                     + str(index) + r'\s*$')
    src = matches(r'\s*(%\w+)\s*=\s*OpLoad %v4float (%\w+)\s*$', chains)
    ty = '%float'
    if as_uint:
        src = matches(r'\s*(%\w+)\s*=\s*OpBitcast %v4uint (%\w+)\s*$', src)
        ty = '%uint'
    return matches(r'\s*(%\w+)\s*=\s*OpCompositeExtract ' + re.escape(ty)
                   + r' (%\w+) ' + str(comp) + r'\s*$', src)


def find_sdr_tonemap(mod, grade=1):
    """The game's own tone curve in an SDR permutation: what feeds it, what it
    produces, and where to cut.

    `--site sdr` was misidentified.  Its anchor -- the first three values
    compared against the sRGB threshold 0.0031308 -- lands in the FIRST of the
    sixteen per-LUT encode blocks inside the grade stacks, not in the display
    encode at the tail, so `_resolve_phi` walked back to the output of the
    basic grade and AgX was spliced there.  The game's own tone curve then ran
    on top of AgX's output: a double tone map, which is why SDR reads dark.
    (The `groups >= 3` guard did not catch it because it was satisfied by the
    three stack-1 merge phis rather than the seventeen encode branches it was
    written to count.)

    Every SDR permutation has the same skeleton, and so does the HDR pair:

        shaper Exp2 -> basic grade -> [area LUT stack 1, iff cbv[42].y == 1]
          -> x cbv[42].z                       EXPOSURE          %380..%382
          -> [ / cbv[30].x ]                   normalise
          -> the tone curve                                       <-- replace
          -> [ x cbv[30].x ]                   denormalise
          -> [area LUT stack 2, iff cbv[42].y == 0]
          -> display encode -> OpImageWrite

    so the cut is defined by the two gates rather than by the curve, which is
    what makes one detector cover all eight.  The curve itself differs across a
    2x2 lattice of compile-time booleans and is not always present at all:

        matrices + cbv[30]   065fcdcc 6040914437   ACES fit, normalised
        matrices, no cbv[30] 8bbd5900 ef31e105     ACES fit or Reinhard, picked
                                                   at RUNTIME on cbv[42].x
        cbv[30], no matrices 7a858d59 e0e20375     luminance-only curve on max()
        neither              1c9000b4 90fa8b3f     NO CURVE -- the exposure
                                                   output goes straight to the
                                                   stack-2 gate

    Colour space is proven, not assumed (GOTCHAS #5).  Four permutations apply
    Stephen Hill's ACESInputMat, whose domain is Rec.709 linear by definition,
    and close with its inverse; the other four apply no 3x3 at all between the
    two gates, so whatever space goes in comes out, and what comes out feeds
    the sRGB OETF and is therefore display Rec.709.  Either way the segment is
    Rec.709 in, Rec.709 out -- which is what AgX needs.  Any OTHER constant 3x3
    in the segment means the space is not what this reasoning assumed, and is a
    hard error rather than a silent mis-splice.

    Returns a dict: `lin` (AgX's input triple), `pre_div` (the cbv[30].x id to
    divide `lin` by first, or None), `out` (the triple to replace), `ins` (the
    line to emit after) and `proof`.
    """
    zids = _cbv_component(mod, 42, 2)           # exposure scalar
    yids = _cbv_component(mod, 42, 1, as_uint=True)   # which stack is taken
    if not zids or not yids:
        die(f"{mod.name}: no cbv[42].z exposure / cbv[42].y stack selector")

    # --- the exposure multiply: three FMuls sharing the cbv[42].z scalar -----
    expo = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        res, a, b = m.groups()
        if a in zids:
            expo.append((i, res, b))
        elif b in zids:
            expo.append((i, res, a))
    if len(expo) != 3:
        die(f"{mod.name}: expected 3 cbv[42].z exposure multiplies, "
            f"found {len(expo)}")
    exp_line = max(e[0] for e in expo)
    exposed = [e[1] for e in expo]              # x cbv[42].z
    graded = [e[2] for e in expo]               # the stack-1 merge phis
    if len(set(graded)) != 3:
        die(f"{mod.name}: the exposure multiplies do not take three distinct "
            f"graded components ({graded})")

    # --- the stack-2 gate, and the three values that skip it ----------------
    gates = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*%\w+\s*=\s*OpIEqual %bool (%\w+) %uint_0\s*$', ln)
        if m and m.group(1) in yids:
            mm = re.match(r'\s*OpSelectionMerge (%\w+) None\s*$',
                          mod.lines[i + 1] if i + 1 < len(mod.lines) else '')
            if mm:
                gates.append((i, mm.group(1)))
    if len(gates) != 1:
        die(f"{mod.name}: expected exactly one `cbv[42].y == 0` stack-2 gate, "
            f"found {len(gates)}")
    gate_line, merge = gates[0]
    cfg = CFG(mod)
    gate_block = cfg.block_of(gate_line)
    if gate_block is None:
        die(f"{mod.name}: the stack-2 gate at line {gate_line + 1} is in no block")
    lbl = gate_block['label']

    mline = next((i for i, ln in enumerate(mod.lines)
                  if re.match(r'\s*' + re.escape(merge) + r'\s*=\s*OpLabel\s*$', ln)),
                 None)
    if mline is None:
        die(f"{mod.name}: no label for the stack-2 merge block {merge}")
    out = []
    for j in range(mline + 1, min(mline + 8, len(mod.lines))):
        m = re.match(r'\s*(%\w+)\s*=\s*OpPhi %float (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                     mod.lines[j])
        if not m:
            break
        _, v0, l0, v1, l1 = m.groups()
        picked = v0 if l0 == lbl else (v1 if l1 == lbl else None)
        if picked is None:
            die(f"{mod.name}: stack-2 merge phi at line {j + 1} has no incoming "
                f"from the gate block {lbl}")
        out.append(picked)
    if len(out) != 3 or len(set(out)) != 3:
        die(f"{mod.name}: expected 3 distinct stack-2 merge phis, got {out}")

    # --- peel the cbv[30].x normalise/denormalise pair, if it is there ------
    # It brackets the curve: the divide before and the multiply after cancel,
    # so replacing what is BETWEEN them keeps vanilla's range convention
    # whatever cbv[30].x holds.  Splicing outside the pair instead would leave
    # AgX's [0,1] output scaled by an unknown factor -- and unlike an exposure
    # error that is not something `pre_gain` can undo.
    scales = _cbv_component(mod, 30, 0)
    pre_div, proof_scale = None, 'none (no cbv[30] normalisation)'
    for sc in sorted(scales):
        quot = {}
        for i, ln in enumerate(mod.lines):
            m = re.match(r'\s*(%\w+)\s*=\s*OpFDiv %float (%\w+) '
                         + re.escape(sc) + r'\s*$', ln)
            if m and m.group(2) in exposed:
                quot[m.group(2)] = m.group(1)
        inner = []
        for o in out:
            _, d = mod.find_def(o)
            m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d or '')
            if not m:
                break
            a, b = m.groups()
            if a == sc:
                inner.append(b)
            elif b == sc:
                inner.append(a)
            else:
                break
        if len(quot) == 3 and len(inner) == 3 and len(set(inner)) == 3:
            pre_div = sc
            exposed = [quot[e] for e in exposed]
            out = inner
            proof_scale = f'cbv[30].x ({sc}) divided out and multiplied back'
            break

    # --- what AgX is fed ----------------------------------------------------
    if grade == 1:
        lin, src = exposed, 'graded, x cbv[42].z exposure'
        pre_div = None                          # already divided
    elif grade == 2:
        lin, src = graded, 'graded, pre-exposure'
    else:
        w = find_lut_write(mod)
        lin = find_shaper_exp2(mod, w['line'])
        src = 'shaper Exp2 (raw scene-linear, pre-grade)'

    # --- colour space, and only then the splice -----------------------------
    seg_lo = min(l for l in (mod.find_def(i)[0] for i in exposed) if l is not None)
    seg_hi = max(l for l in (mod.find_def(o)[0] for o in out) if l is not None)
    named = {'ACESInputMat': ACES_INPUT, 'ACESOutputMat': ACES_OUTPUT}
    seen, unknown = [], []
    for ins_ids, coeffs, lines in _const_matrices(mod, seg_hi + 1):
        if min(lines) < seg_lo:
            continue
        for nm, ref in named.items():
            if max(abs(coeffs[r][c] - ref[r][c])
                   for r in range(3) for c in range(3)) < 1e-4:
                seen.append(nm)
                break
        else:
            unknown.append(f'line {min(lines) + 1}')
    if unknown:
        die(f"{mod.name}: unidentified 3x3 in the tone-curve segment at "
            f"{', '.join(unknown)} -- cannot prove the splice is Rec.709 in "
            "and Rec.709 out")
    if seen:
        proof = ('Rec.709 by ' + ' + '.join(sorted(set(seen)))
                 + ' (published ACES fit, domain Rec.709 linear)')
    else:
        proof = ('Rec.709 by exclusion: no 3x3 between the gates, so the '
                 'segment cannot change colour space, and its output feeds '
                 'the sRGB OETF')

    # --- dominance (GOTCHAS: never assumed) ---------------------------------
    # Emit after the LAST of the values being replaced, not merely after the
    # values being read.  Both work for the splice itself, but only this one
    # leaves the vanilla curve's result in scope, which `mix` needs in order to
    # cross-fade against it -- and in the permutations that pick between two
    # curves at runtime it also puts the emitted code below their merge, so one
    # splice bypasses both branches.
    ins = max([exp_line]
              + [mod.find_def(i)[0] for i in lin + out
                 if mod.find_def(i)[0] is not None]
              + ([mod.find_def(pre_div)[0]] if pre_div is not None
                 and mod.find_def(pre_div)[0] is not None else []))
    # Only uses BELOW the splice get rewritten, so a use above it would be left
    # reading the vanilla curve while its siblings read AgX.  (In the two
    # permutations that compile the curve away entirely, `out` IS the exposure
    # triple and its only appearance above the splice is its own definition,
    # which is fine -- the emitted AgX reads it deliberately.)
    for o in out:
        dl, _ = mod.find_def(o)
        for j in range(0, ins + 1):
            if j != dl and re.search(r'(?<![%\w])' + re.escape(o) + r'(?![\w])',
                                     mod.lines[j].partition('=')[2] or mod.lines[j]):
                die(f"{mod.name}: {o} is used at line {j + 1}, above the splice "
                    f"at line {ins + 1} -- that use would keep the vanilla curve")
    for j in range(ins + 1, len(mod.lines)):
        if any(re.search(r'(?<![%\w])' + re.escape(o) + r'(?![\w])', mod.lines[j])
               for o in out):
            for e in exposed:
                if not cfg.dominates_line(e, j):
                    die(f"{mod.name}: the splice at line {ins + 1} does not "
                        f"dominate the use at line {j + 1}")
    for i in lin:
        if not cfg.dominates_line(i, ins + 1):
            die(f"{mod.name}: AgX input {i} does not dominate the splice at "
                f"line {ins + 1}")

    return dict(lin=lin, pre_div=pre_div, out=out, ins=ins, proof=proof,
                input_source=src, scale=proof_scale, gate_line=gate_line + 1)


def _resolve_phi(mod, i, depth=32):
    """Follow OpPhi first-incoming edges back to the value they all share."""
    for _ in range(depth):
        _, d = mod.find_def(i)
        m = re.match(r'OpPhi %float (%\w+) %\w+', d or '')
        if not m:
            return i
        i = m.group(1)
    die(f"{mod.name}: phi chain from {i} did not terminate")


def find_srgb_site(mod):
    """The three LINEAR display-RGB values entering the game's output encode.

    The SDR permutations are a different compilation entirely: no ACES, no
    colour-space matrices at all, and an INTEGER mode ladder (`OpIEqual ...
    %uint_N`) rather than the float one the HDR pair uses -- which is why the
    first scanner, requiring a float ladder, never saw them.

    Their tail is:

        %462..%464 = OpPhi              # linear display RGB   <-- splice here
        OpIEqual %413 %uint_0/1/2       # encode mode
          mode 1: the sRGB OETF (12.92 / 1.055 / 1/2.4)
        ... -> OpCompositeConstruct %v4float -> OpImageWrite

    Located by the sRGB piecewise threshold: the three values compared against
    0.0031308 are, by definition, linear display light.  Returns the ids, the
    line to insert after (the end of the phi run in their defining block), and
    the encode-mode selector.
    """
    thr = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)\s*$', ln)
        if m:
            try:
                if abs(float(m.group(2)) - 0.0031308) < 1e-9:
                    thr = m.group(1)
                    break
            except ValueError:
                pass
    if thr is None:
        die(f"{mod.name}: no sRGB OETF threshold -- not an SDR LUT generator")

    cmps = [(i, m.group(1)) for i, m in
            ((i, re.match(r'\s*%\w+\s*=\s*OpFOrdLessThanEqual %bool (%\w+) '
                          + re.escape(thr) + r'\s*$', ln))
             for i, ln in enumerate(mod.lines)) if m]
    if len(cmps) < 3:
        die(f"{mod.name}: sRGB threshold compared {len(cmps)} times, expected >=3")
    ids = [c[1] for c in cmps[:3]]
    if len(set(ids)) != 3:
        die(f"{mod.name}: the first three sRGB comparisons are not three "
            f"distinct components ({ids})")

    # %462.. is only ONE of ~17 sibling encode branches, every one of them a
    # phi whose first incoming value is the SAME triple -- the graded linear
    # RGB.  Patching the branch would patch one permutation of the encode and
    # leave the other sixteen vanilla, so resolve back to that common source.
    src = [_resolve_phi(mod, i) for i in ids]
    if len(set(src)) != 3:
        die(f"{mod.name}: the encode inputs do not resolve to three distinct "
            f"sources ({src})")
    groups = sum(1 for ln in mod.lines
                 if re.match(r'\s*%\w+\s*=\s*OpPhi %float ' + re.escape(src[0])
                             + r'\s', ln))
    if groups < 3:
        die(f"{mod.name}: {src[0]} sources only {groups} encode branches -- "
            "expected the common pre-encode value")

    dls = []
    for i in src:
        dl, _ = mod.find_def(i)
        if dl is None:
            die(f"{mod.name}: no definition for {i}")
        dls.append(dl)
    ins = max(dls)
    if ins >= cmps[0][0]:
        die(f"{mod.name}: the source triple does not precede the encode")
    # everything up to the first branch dominates the whole function; these
    # defs must sit there for the splice to dominate all 17 consumers
    for j, ln in enumerate(mod.lines):
        if re.search(r'\bOp(SelectionMerge|LoopMerge|BranchConditional|Switch)\b', ln):
            if ins > j:
                die(f"{mod.name}: source triple at {ins + 1} is inside control "
                    f"flow (first branch at {j + 1}) -- cannot prove dominance")
            break

    sel = None
    for ln in mod.lines:
        m = re.match(r'\s*%\w+\s*=\s*OpIEqual %bool (%\w+) %uint_\d+\s*$', ln)
        if m:
            sel = m.group(1)
            break
    return src, ins, sel


# ------------------------------------------------------------------ codegen
class Emit:
    """Accumulates SPIR-V lines plus any constants they need."""

    def __init__(self, mod):
        self.mod, self.ins, self.consts = mod, [], []

    def C(self, v):
        # mod.const keys on the float value, and Python has 0.0 == -0.0, so a
        # module that already declares `OpConstant %float -0` hands that back
        # for 0.0.  Harmless for a clamp bound, confusing in a disassembly.
        if v == 0.0:
            for ln in self.mod.lines:
                m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float 0\s*$', ln)
                if m:
                    return m.group(1)
        nid, decl = self.mod.const(float(v))
        if decl:
            self.consts.append(decl)
        return nid

    def op(self, opcode, *args):
        r = self.mod.new_id()
        self.ins.append(f"        {r} = {opcode} %float " + " ".join(args))
        return r

    def ext(self, name, *args):
        r = self.mod.new_id()
        self.ins.append(f"        {r} = OpExtInst %float {self.mod.glsl} "
                        f"{name} " + " ".join(args))
        return r

    def mul(self, a, b): return self.op('OpFMul', a, b)
    def add(self, a, b): return self.op('OpFAdd', a, b)
    def sub(self, a, b): return self.op('OpFSub', a, b)

    def mad(self, a, b, c):
        """a*b + c, as explicit ops (Fma exists here but keep it plain)."""
        return self.add(self.mul(a, b), c)

    def matmul(self, m, v):
        out = []
        for row in m:
            acc = self.mul(v[0], self.C(row[0]))
            for k in (1, 2):
                acc = self.mad(v[k], self.C(row[k]), acc)
            out.append(acc)
        return out

    def lerp(self, a, b, t):
        return self.add(a, self.mul(self.sub(b, a), t))


def build_agx(mod, lin, vanilla, k, post=None, clamp_in=False, pre_div=None,
              clamp_out=False):
    """lin = [r,g,b] linear radiance ids; vanilla = the 3 ids being replaced."""
    e = Emit(mod)

    def luma_of(t):
        acc = e.mul(t[0], e.C(LUMA[0]))
        for i in (1, 2):
            acc = e.mad(t[i], e.C(LUMA[i]), acc)
        return acc

    if pre_div is not None:
        # Enter the same normalised domain the replaced curve worked in, so the
        # `x cbv[30].x` that vanilla applies after it lands on a value of the
        # same scale.  Only needed when `lin` did not come from inside the pair
        # already (grade=0 and grade=2 on --site sdr2).
        lin = [e.op('OpFDiv', c, pre_div) for c in lin]
    if clamp_in:
        # The shaper's Exp2 output is strictly positive; a GRADED value is not
        # (negative lift, the channel mixer, the grade LUT's soft-clip unwind).
        # The NMax under the log below would launder it, but only after the
        # inset has mixed the negative channel into the other two -- a hue
        # shift in deep shadows.  Three instructions, before the mixing.
        z = e.C(0.0)
        lin = [e.ext('NMax', c, z) for c in lin]
    if k['pre_gain'] != 1.0:
        # min_ev/max_ev are an ABSOLUTE log window, so changing the input's
        # scale slides the whole image inside it.  Switching from the raw
        # shaper to the graded input multiplies by the unknown cbv[42].z; this
        # is the knob that compensates without re-deriving the look.
        g = e.C(k['pre_gain'])
        lin = [e.mul(c, g) for c in lin]
    v = e.matmul(AGX_IN, lin)                                   # inset

    lo, hi = e.C(k['min_ev']), e.C(k['max_ev'])
    inv = e.C(1.0 / (k['max_ev'] - k['min_ev']))
    eps = e.C(1e-10)
    enc = []
    for c in v:
        x = e.ext('Log2', e.ext('NMax', c, eps))
        x = e.ext('NClamp', x, lo, hi)
        enc.append(e.mul(e.sub(x, lo), inv))

    sig = []
    for x in enc:                                               # Horner
        acc = e.C(SIGMOID[0])
        for co in SIGMOID[1:]:
            acc = e.mad(acc, x, e.C(co))
        sig.append(acc)

    # look: pow(max(s*slope + offset, 0), power), then saturation about luma
    slopes = (k['slope_r'], k['slope_g'], k['slope_b'])
    neutral_gain = all(s == 1.0 for s in slopes) and k['offset'] == 0.0
    if not neutral_gain or k['power'] != 1.0:
        zero, off = e.C(0.0), e.C(k['offset'])
        tmp = []
        for c, s in zip(sig, slopes):
            x = e.mad(c, e.C(s), off) if not neutral_gain else c
            x = e.ext('NMax', x, zero)
            if k['power'] != 1.0:
                x = e.ext('Pow', x, e.C(k['power']))
            tmp.append(x)
        sig = tmp
    if k['sat'] != 1.0:
        luma = e.mul(sig[0], e.C(LUMA[0]))
        for i in (1, 2):
            luma = e.mad(sig[i], e.C(LUMA[i]), luma)
        sat = e.C(k['sat'])
        sig = [e.mad(e.sub(c, luma), sat, luma) for c in sig]

    if k['hue_restore'] > 0.0:
        # AgX drives everything above max_ev to white by construction, so a
        # warm grade tints the approach to white but never the core -- the sun
        # keeps reading as a white disc however the grade is authored.  This
        # pushes the tonemapped colour back toward the INPUT's chroma ratios,
        # weighted by luminance squared so only the highlights move.
        # 0 = stock AgX (no instructions emitted), 1 = full restoration.
        zr, on = e.C(0.0), e.C(1.0)
        lv = e.ext('NMax', luma_of(v), e.C(1e-6))
        ls = luma_of(sig)
        w = e.ext('NClamp', e.mul(e.C(k['hue_restore']), e.mul(ls, ls)), zr, on)
        sig = [e.lerp(c, e.ext('NClamp', e.mul(ls, e.op('OpFDiv', ci, lv)),
                               zr, on), w)
               for c, ci in zip(sig, v)]

    out = e.matmul(AGX_OUT, sig)                                # outset

    zero, one = e.C(0.0), e.C(1.0)
    if k['eotf'] > 0.0:
        out = [e.ext('Pow', e.ext('NMax', c, zero), e.C(k['eotf'])) for c in out]
    else:
        out = [e.ext('NClamp', c, zero, one) for c in out]

    tints = (k['tint_r'], k['tint_g'], k['tint_b'])
    if any(t != 1.0 for t in tints):
        out = [e.mul(c, e.C(t)) for c, t in zip(out, tints)]

    # into the space the splice site actually holds (Rec.709 -> AP1 for
    # --site ap1).  Must precede the mix: `vanilla` is already in that space.
    if post is not None:
        out = e.matmul(post, out)

    if k['mix'] != 1.0:
        t = e.C(k['mix'])
        out = [e.lerp(vanilla[i], out[i], t) for i in range(3)]
    if clamp_out:
        # The SDR splice writes into a slot the game clamped to [0,1] before
        # scaling it back up, and nothing below it clamps again -- so AgX's
        # small overshoot (the outset matrix, and `power`/`sat` acting on a
        # sigmoid that already reaches 1) has to be clamped here instead.
        zc, oc = e.C(0.0), e.C(1.0)
        out = [e.ext('NClamp', c, zc, oc) for c in out]
    return e, out


# ------------------------------------------------------------------- driver
def process(path, outdir, knobs, site='pre', do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if not mod.glsl:
        die(f"{mod.name}: no GLSL.std.450 import -- cannot emit AgX")
    if do_rt:
        roundtrip_check(path, target_env)

    w = find_lut_write(mod)
    shaper = find_shaper_exp2(mod, w['line'])
    lin, input_src = shaper, 'shaper Exp2 (raw scene-linear, pre-grade)'

    if site == 'auto':
        # The HDR permutations end in an ACES output transform; the SDR ones
        # have no colour matrices at all and an integer encode ladder.
        site = 'ap1' if any('0.662454128' in l for l in mod.lines) else 'sdr2'

    grade = int(knobs['grade'])
    warnings, rep_extra = [], {}
    if grade and site not in ('ap1', 'pre', 'sdr2'):
        # `--site sdr` and `--site write` splice UPSTREAM of the grade, so
        # feeding them the graded colour would apply the grade twice.  Warn and
        # build the raw-shaper module rather than failing, so one command still
        # produces all ten permutations.
        warnings.append(
            f"grade={grade} ignored: --site {site} splices upstream of the "
            "grade, so the graded input would double it -- built from the raw "
            "shaper input")
        grade = 0

    if site == 'sdr2':
        t = find_sdr_tonemap(mod, grade)
        lin, input_src = t['lin'], t['input_source']
        e, out = build_agx(mod, lin, t['out'], knobs, clamp_in=bool(grade),
                           pre_div=t['pre_div'], clamp_out=True)
        ins = t['ins']
        sub = dict(zip(t['out'], out))
        # The replaced triple is read by the stack-2 branch, by its merge phi
        # and by every encode block below it, so rewrite every use from the
        # splice down.  The emitted AgX is inserted afterwards and so is not
        # itself rewritten -- it still reads the vanilla input ids.
        for j in range(ins + 1, len(mod.lines)):
            head, eq, tail = mod.lines[j].partition('=')
            if not eq:                      # OpBranch / OpImageWrite / ...
                head, tail = '', mod.lines[j]
            mod.lines[j] = head + eq + re.sub(
                r'%\w+', lambda m: sub.get(m.group(0), m.group(0)), tail)
        edits = [(ins, e.ins)]
        mode_id = None
        replaced = t['out']
        where = (f"the game's own tone curve, between the two grade-stack "
                 f"gates (line {ins + 1}, stack-2 gate at line {t['gate_line']})")
        rep_extra = dict(colour_space_proof=t['proof'], normalisation=t['scale'])
    elif site == 'sdr':
        ids, ins, sel = find_srgb_site(mod)
        e, out = build_agx(mod, lin, ids, knobs)
        sub = dict(zip(ids, out))
        for j in range(ins + 1, len(mod.lines)):
            head, eq, tail = mod.lines[j].partition('=')
            if not eq:                      # OpImageWrite / OpBranch / ...
                head, tail = '', mod.lines[j]
            mod.lines[j] = head + eq + re.sub(
                r'%\w+', lambda m: sub.get(m.group(0), m.group(0)), tail)
        edits = [(ins, e.ins)]
        mode_id = sel
        replaced = ids
        where = f"linear display RGB, before the output encode (line {ins + 1})"
    elif site in ('ap1', 'pre'):
        if site == 'ap1':
            ins_ids, rowlines = find_ap1_site(mod)
            mode_id = _find_mode_ladder(mod)[0]
            post = REC709_TO_AP1
        else:
            ins_ids, rowlines, mode_id = find_output_transform(mod)
            post = None
        first = min(rowlines)
        if grade:
            lin = find_graded_color(mod, with_exposure=(grade == 1))
            input_src = ('graded, x cbv[42].z exposure' if grade == 1
                         else 'graded, pre-exposure')
            # The graded triple is defined in the stack-1 selection MERGE
            # block, not the entry block, so unlike the shaper it does not
            # dominate trivially.  Prove it (GOTCHAS: dominance is never
            # assumed) rather than leaving it to spirv-val.
            cfg = CFG(mod)
            bad = [i for i in lin if not cfg.dominates_line(i, first)]
            if bad:
                die(f"{mod.name}: graded input {bad} does not dominate the "
                    f"splice at line {first + 1}")
        e, out = build_agx(mod, lin, ins_ids, knobs, post=post,
                           clamp_in=bool(grade))
        # rewrite only the operands inside those three matrix chains, so an
        # unrelated later use of the same ids is untouched
        sub = dict(zip(ins_ids, out))
        for ln_i in rowlines:
            def rep_op(m, _s=sub):
                return _s.get(m.group(0), m.group(0))
            head, _, tail = mod.lines[ln_i].partition('=')
            mod.lines[ln_i] = head + '=' + re.sub(r'%\w+', rep_op, tail)
        edits = [(first - 1, e.ins)]
        label = ("AP1 working space, before the ACES output transform"
                 if site == 'ap1' else "output-transform inputs")
        replaced, where = ins_ids, f"{label} (line {first + 1})"
    else:
        e, out = build_agx(mod, lin, w['comps'][:3], knobs)
        edits = [(w['texel_line'] - 1, e.ins)]
        mod.lines[w['texel_line']] = re.sub(
            r'OpCompositeConstruct %v4float %\w+ %\w+ %\w+ (%\w+)\s*$',
            f'OpCompositeConstruct %v4float {out[0]} {out[1]} {out[2]} \\1',
            mod.lines[w['texel_line']])
        mode_id = None
        replaced, where = w['comps'][:3], f"final texel (line {w['line'] + 1})"
    apply_edits(mod, e.consts, edits)

    rep = dict(module=mod.name, ident=mod.ident, tier='agx', site=site,
               agx_input=lin, input_source=input_src, grade=grade,
               shaper_exp2=shaper, write_line=w['line'] + 1, spliced_at=where,
               mode_selector=mode_id,
               replaced=replaced, emitted=len(e.ins),
               consts=len(e.consts), params=knobs)
    rep.update(rep_extra)
    if problems:
        rep['module_warnings'] = problems
    if warnings:
        rep['warnings'] = warnings
        for msg in warnings:
            print(f"warning: {mod.name}: {msg}", file=sys.stderr)

    os.makedirs(outdir, exist_ok=True)
    asm = os.path.join(outdir, mod.ident + '.spvasm')
    spv = os.path.join(outdir, mod.ident + '.spv')
    open(asm, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm, '-o', spv],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv], capture_output=True, text=True)
    rep['spirv_val'] = 'clean' if v.returncode == 0 else 'FAIL'
    if v.returncode != 0:
        open(spv + '.val.log', 'w').write(v.stderr)
        os.unlink(spv)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv, 'rb').read()).hexdigest()
    rep['out'] = spv
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--look', choices=sorted(LOOKS), default='none')
    ap.add_argument('--site',
                    choices=('auto', 'ap1', 'sdr2', 'sdr', 'pre', 'write'),
                    default='auto',
                    help="auto (default): ap1 for the HDR permutations, sdr2 "
                         "for the SDR ones. ap1: splice in the ACEScg working "
                         "space, before the game's whole ACES output transform. "
                         "sdr2: replace the SDR tone curve between the two "
                         "grade-stack gates. sdr: LEGACY and wrong -- it "
                         "splices at the basic grade's output, inside the LUT "
                         "stack, so the game's curve runs on top of AgX; kept "
                         "only to A/B against. pre: before the display matrix; "
                         "WRONG, that slot holds CIE XYZ, not RGB. write: "
                         "overwrite the final texel; SDR only.")
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()

    knobs = dict(DEFAULTS)
    knobs.update(LOOKS[a.look])
    for kv in a.set:
        k, _, val = kv.partition('=')
        if k not in knobs:
            die(f"unknown knob {k} (have: {', '.join(sorted(knobs))})")
        knobs[k] = float(val)
    if knobs['max_ev'] <= knobs['min_ev']:
        die("max_ev must exceed min_ev")
    if knobs['grade'] not in (0.0, 1.0, 2.0):
        die("grade must be 0 (raw shaper), 1 (graded + exposure) or "
            "2 (graded, pre-exposure)")
    if knobs['pre_gain'] <= 0.0:
        die("pre_gain must be positive")

    if a.site == 'write' and knobs['eotf'] != 0.0:
        die("--site write expects eotf=0 (the mode encode is being bypassed)")
    if a.site in ('auto', 'ap1', 'sdr2', 'sdr') and knobs['eotf'] <= 0.0:
        die(f"--site {a.site} expects eotf>0: the site holds LINEAR display "
            "light, and AgX's sigmoid output is display-encoded")
    reports = [process(p, a.outdir, knobs, site=a.site,
                       do_rt=not a.no_roundtrip_check)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
