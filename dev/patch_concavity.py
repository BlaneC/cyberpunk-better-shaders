#!/usr/bin/env python3
"""concavity: 102's traced hemispherical occlusion, generalised OFF skin.

handoff/104-TRACED-CONCAVITY.md is the document. Read handoff/102 (the
estimator this clones), 88 sec 0-2/5 (the analytic cone that owns the site),
80 + 81 (the cloth proxy gate) and 98 sec 2.3 / 3.4 / 12.4 / 12.6 before
touching this file.

WHAT THIS IS
------------
102 measured `o = (1/K) . sum_j [the hemisphere about N is blocked within
tmax along d_j]` with K inline ray queries and used it to darken DIRECT light
on class-1 SKIN, REPLACING 88's analytic cavity cone at the cone's own site.

This file keeps the estimator, the site and the ray word, and changes ONLY the
gate and the transfer, in two families:

  --family fold      80/81's CLOTH PROXY gate:
                       class != 1 (skin) and class != 4 (hair)
                       and max3(F0) < 0.09         (every metal / coat / glass out)
                       and wr = saturate((rough^2 - 0.10) * 5.0)   (81's ramp)
                     tmax 10 cm, achromatic:  fac = 1 - 0.85 * wr * o

  --family crevice   ROUGH DIELECTRIC gate:
                       class != 1 and class != 4
                       and rough > 0.60 and metallic < 0.10
                     tmax 5 cm, TINTED per channel:
                       fac_c = 1 - K_c * o,   K_c = 1 - tint_c * (1 - 0.85)
                       tint = (0.55, 0.45, 0.35)
                     i.e. exactly lerp(1, tint_c * (1 - k), o): identity at
                     o = 0, and tint_c * 0.15 at o = 1, which is darker AND
                     warmer than the fold family's flat 0.15.

ADD, DO NOT REPLACE -- THIS IS THE OPPOSITE OF 102
--------------------------------------------------
102 KILLED the cone, because 102's term replaced it on the SAME pixels
(class-1 skin). Both families here are gated `class != 1`, i.e. DISJOINT from
the cone's own pixels, so killing the cone would delete the shipped skin
cavity darkening and make every rung a two-variable A/B. The cone therefore
stays LIVE, byte for byte:

  * its `occ` still feeds its own `OpFMul occ k`;
  * all six of its flags-16 tap rays keep their own live cull mask;
  * `OpTraceRayKHR` count is unchanged.

Our factor is multiplied INTO the same chain the cone's `fac` already scales,
one level below it, so on a skin pixel our factor is exactly 1.0 and on a
gated pixel the cone's `fac` is exactly 1.0. The composition is a product of
two terms that are never both active.

WHERE IT LANDS (and therefore what it can reach)
------------------------------------------------
`rgs_reference_main` ONLY -- the reference / photo-mode path tracer (88 sec 5,
"Reach is unchanged from 85 sec 2"). All 77 compute and all 4 rgs_restirgi_*
modules ship byte-verbatim. So this is a photo-mode / reference-PT feature and
nothing else, and it is a MULTIPLY on DIRECT light (98 sec 12.4), so it is
arithmetically incapable of doing anything on a pixel the sun and the local
lights do not reach.

WHY THE WHOLE DIRECT TERM AND NOT THE SHEEN LOBE
------------------------------------------------
The brief asked for the sheen lobe alone if it is separately reachable here.
It is not reachable here AT ALL: 81's Charlie x Neubelt sheen was spliced into
the 77 direct-light COMPUTE BRDF sites, and 81 sec 0 records -- and `cmp`
re-confirms -- that 0 of 16 raygens differ between `...-deep` and
`...-deep-clothhi`. There is no sheen lobe in this shader to multiply. The
cone's `fac` scales `NClamp(diffuse*NoL + spec, 0, 1)` per channel, so what is
reachable is the whole direct term, which is also what a fold physically
occludes. Documented, not hidden: 104 sec 2.5.

THE APPLICATION NODE
--------------------
Each of 88's three cones ends in `fac = 1 - occ*k`. The sun's `fac` has
exactly THREE per-channel consumers `OpFMul %float <term_c> fac`. Each local
light's `fac` has exactly ONE consumer `S = OpFMul %float <v> fac`, and S has
exactly three per-channel consumers `OpFMul %float S <radiance_c>`. So in
both cases there is a scalar node with exactly three per-channel consumers;
we emit `S_ch = OpFMul S f_ch` right after it and repoint consumer ch. That is
where a per-channel tint becomes reachable at all, and it is asserted 12/12.

USAGE
    python3 dev/patch_concavity.py <mod.spvasm> --outdir DIR \
        --family fold|crevice --k 0|1 [--rays 4] [--mode dark|hit] \
        [--decoy flags|tmax|counter|basis|class|notint|kill]

    --k 0 emits NOTHING and writes the module back unchanged: the CONTROL
    rung, byte-identical to the base (build gate 1 proves the round trip is
    neutral). --k 1 is live.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish, find_f0_triples
import patch_earglow as E
import cfg_dom
# 90 sec 1's FIXED path-loop counter, imported, never re-derived here.
from patch_cavity2 import find_path_counter
# 102's detectors for 88's cone, imported READ-ONLY. If 88's emitted shape
# ever moves these die instead of patching the wrong instruction, which is
# exactly the behaviour we want inherited.
from patch_contact_rq import (find_cones, find_cone_taps, find_sun_geometry,
                              find_launch_id, taps, _uc, _fc, _ensure_line,
                              _mask_of)
# 98's header inserter. patch_rayq.py is NOT edited by this file.
from patch_rayq import _add_header

# --- SPIR-V RayFlags (SPV_KHR_ray_query shares the ray-tracing enum) --------
RF_OPAQUE     = 0x001
RF_TERMINATE  = 0x004
RF_CULL_FRONT = 0x020
RF_SKIP_AABBS = 0x200
FLAGS = RF_OPAQUE | RF_TERMINATE | RF_SKIP_AABBS               # 517
FLAGS_NAMES = 'OpaqueKHR|TerminateOnFirstHitKHR|SkipAABBsKHR'
# 101's word. CullFrontFacing asks "how thick is this", not "is anything near
# me", and the difference is invisible in a diff.
FLAGS_DECOY = RF_OPAQUE | RF_CULL_FRONT | RF_SKIP_AABBS        # 545

COMMITTED = 1               # RayQueryCommittedIntersectionKHR
GATE_MASK = 39              # the module's own NEE cullMask when lit (88/98)
CONE_FLAGS = 16             # the cone taps' literal ray-flag word
TMIN = 0.001                # 1 mm, the self-hit guard
EPS_N = 1e-4                # 0.1 mm origin lift along N
NEPS = 1e-6                 # degenerate-normal floor
HIT_SCALE = 3.2             # -hit grey ramp full-scale (66's probe magnitude)
PHI_INV = 0.6180339887498949

K_STRENGTH = 0.85           # 88's own strength constant, reused by VALUE so
                            # that mod.const() hands back the cone's own id.

CLS_SKIN = 1                # 13 / 88 sec 4
CLS_HAIR = 4

# 81 sec 2's shipped cloth gate, verbatim.
CLOTH_F0MAX = 0.09
CLOTH_A0 = 0.10             # ramp start, on ALPHA = roughness^2
CLOTH_A1 = 0.30             # ramp end
CLOTH_RAMP = 1.0 / (CLOTH_A1 - CLOTH_A0)    # 5.0

# The rough-dielectric gate the brief specifies.
CREV_RMIN = 0.60            # roughness (NOT alpha) above this
CREV_METMAX = 0.10          # metallic below this
DIRT_TINT = (0.55, 0.45, 0.35)

FAMILIES = {
    'fold':    dict(tmax=0.10, tint=None),
    'crevice': dict(tmax=0.05, tint=DIRT_TINT),
}

# 32-bit hash constants: Knuth's golden ratio, glibc's LCG multiplier, and
# Wang's finaliser. Pixel in, angle out; nothing per-frame is read.
H_A = 1103515245
H_B = 2654435761
H_C = 2246822519


def channel_k(family, k_strength):
    """The per-channel strength K_c such that fac_c = 1 - K_c*o is exactly
    lerp(1, tint_c*(1 - k), o): identity at o = 0 by construction."""
    tint = FAMILIES[family]['tint']
    if tint is None:
        return (k_strength, k_strength, k_strength)
    return tuple(1.0 - t * (1.0 - k_strength) for t in tint)


def find_primary_material(mod, cls, fs, fe):
    """The PRIMARY hit's metallic, roughness and F0, by SSA id.

    Anchored on the module's UNIQUE slot-5 `>>5` class word (88 sec 4), which
    88's cone already reads: that word is `CompositeExtract(<v4uint
    ImageFetch at texel C>, 1)`. The primary PBR decode is the
    `F0 = lerp(0.04, albedo, metallic)` triple (80 sec 2.4's idiom, detected
    by patch_subtype_probe.find_f0_triples) whose METALLIC is
    `CompositeExtract(<v4float ImageFetch at the SAME texel C>, 0)`.

    Same texel, same pixel: that is the discriminator, and it is what
    separates the primary decode from the SECOND F0 triple every one of these
    raygens carries for a later path segment. Roughness is component 1 of the
    same fetch, and is returned in the module's OWN clamped form
    `NMin(NMax(r, 0.04), 1)` -- the value the shader's own GGX squares into
    alpha, so no roughness convention is invented here.

    Asserted unique in 12 of 12; anything else dies.
    """
    cl, cd = mod.find_def(cls)
    m = re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', cd or '')
    if not m:
        die(f"{mod.name}: the class word {cls} is not a slot-5 `>>5` word")
    _, mwd = mod.find_def(m.group(1))
    ce = re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', mwd or '')
    if not ce:
        die(f"{mod.name}: the material word is not component 1 of a fetch -- "
            f"got {mwd}")
    _, fd = mod.find_def(ce.group(1))
    fm = re.match(r'OpImageFetch %v4uint %\w+ (%\w+) Lod %uint_0\s*$', fd or '')
    if not fm:
        die(f"{mod.name}: the class word's source is not an OpImageFetch "
            f"%v4uint -- got {fd}")
    _, coord_def = mod.find_def(fm.group(1))
    if not coord_def or not coord_def.startswith('OpCompositeConstruct %v2uint'):
        die(f"{mod.name}: the class fetch coordinate is not a v2uint construct")

    hits = []
    for line, (f0r, f0g, f0b) in find_f0_triples(mod):
        if not (fs <= line < fe):
            continue
        _, d = mod.find_def(f0r)
        a = re.match(r'OpFAdd %float (%\w+) %float_0_0399999991\s*$', d or '')
        if not a:
            continue
        _, d2 = mod.find_def(a.group(1))
        mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d2 or '')
        if not mm:
            continue
        met = None
        for z, mt in (mm.groups(), mm.groups()[::-1]):
            _, dz = mod.find_def(z)
            if re.match(r'OpFAdd %float %\w+ %float_n0_0399999991\s*$', dz or ''):
                met = mt
                break
        if met is None:
            continue
        _, md = mod.find_def(met)
        me = re.match(r'OpCompositeExtract %float (%\w+) 0\s*$', md or '')
        if not me:
            continue
        _, fd2 = mod.find_def(me.group(1))
        fm2 = re.match(r'OpImageFetch %v4float %\w+ (%\w+) Lod %uint_0\s*$',
                       fd2 or '')
        if not fm2:
            continue
        _, cd2 = mod.find_def(fm2.group(1))
        if cd2 != coord_def:
            continue          # a later path segment's decode, not the primary
        hits.append((line, met, me.group(1), (f0r, f0g, f0b)))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} primary F0 triples fetched at the class "
            f"word's own texel, expected exactly 1")
    line, met, fetch, f0 = hits[0]

    rough_raw = None
    for ln in mod.lines:
        mr = re.match(r'\s*(%\w+) = OpCompositeExtract %float '
                      + re.escape(fetch) + r' 1\s*$', ln)
        if mr:
            if rough_raw is not None:
                die(f"{mod.name}: component 1 of the primary material fetch is "
                    f"extracted more than once -- roughness is ambiguous")
            rough_raw = mr.group(1)
    if rough_raw is None:
        die(f"{mod.name}: the primary material fetch has no component-1 "
            f"extract -- there is no roughness here")
    rough = None
    for ln in mod.lines:
        mn = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NMax '
                      + re.escape(rough_raw)
                      + r' %float_0_0399999991\s*$', ln)
        if not mn:
            continue
        for ln2 in mod.lines:
            mn2 = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NMin '
                           + re.escape(mn.group(1)) + r' %float_1\s*$', ln2)
            if mn2:
                if rough is not None and rough != mn2.group(1):
                    die(f"{mod.name}: more than one clamped roughness")
                rough = mn2.group(1)
    if rough is None:
        die(f"{mod.name}: no NMin(NMax(rough, 0.04), 1) clamp on {rough_raw} "
            f"-- the shader's own roughness form has moved")
    return dict(line=line, met=met, fetch=fetch, f0=f0,
                rough_raw=rough_raw, rough=rough)


def _mentions(mod, idtok, skip_line=None):
    out = []
    for i, ln in enumerate(mod.lines):
        if i == skip_line:
            continue
        if re.search(re.escape(idtok) + r'(?![0-9A-Za-z_])', ln):
            out.append(i)
    return out


def find_channel_node(mod, cone):
    """The scalar node below a cone's `fac` that has exactly THREE per-channel
    OpFMul consumers. Returns (node_id, node_line, [3 consumer lines]).

    Sun cone      : the node IS `fac` (3 direct consumers, one per channel).
    Local light   : `fac` has ONE consumer `S = v * fac` (88 sec 5b's single
                    visibility scalar) and S has the 3 per-channel consumers.

    Both shapes are re-derived here from the bytes; neither is assumed.
    """
    fl, _ = mod.find_def(cone['fac'])
    cons = _mentions(mod, cone['fac'], fl)

    def three(node, nline):
        cs = _mentions(mod, node, nline)
        if len(cs) != 3:
            return None
        for i in cs:
            if not re.match(r'\s*%\w+ = OpFMul %float %\w+ %\w+\s*$',
                            mod.lines[i]):
                return None
            if len(re.findall(re.escape(node) + r'(?![0-9A-Za-z_])',
                              mod.lines[i])) != 1:
                return None
        return cs

    cs = three(cone['fac'], fl)
    if cs is not None:
        return cone['fac'], fl, cs, 'direct'
    if len(cons) != 1:
        die(f"{mod.name}: the cone fac {cone['fac']} at line {fl+1} has "
            f"{len(cons)} consumers, expected 3 (sun) or 1 (local light)")
    sl = cons[0]
    sm = re.match(r'\s*(%\w+) = OpFMul %float %\w+ %\w+\s*$', mod.lines[sl])
    if not sm:
        die(f"{mod.name}: the local cone's single fac consumer at line "
            f"{sl+1} is not an OpFMul -- got {mod.lines[sl].strip()}")
    cs = three(sm.group(1), sl)
    if cs is None:
        die(f"{mod.name}: {sm.group(1)} (the local light's visibility scalar) "
            f"does not have exactly 3 per-channel OpFMul consumers")
    return sm.group(1), sl, cs, 'via'


BLOCKING = ('OpBranch', 'OpBranchConditional', 'OpSwitch', 'OpReturn',
            'OpReturnValue', 'OpUnreachable', 'OpKill', 'OpSelectionMerge',
            'OpLoopMerge', 'OpLabel', 'OpFunctionEnd', 'OpPhi')


def _opcode(line):
    p = line.split()
    if not p:
        return ''
    if len(p) >= 3 and p[0].startswith('%') and p[1] == '=':
        return p[2]
    return p[0]


def _insertable_after(mod, line):
    """An instruction may follow `line` only if the next line is neither a
    block terminator / merge (nothing may follow those) nor an OpPhi (which
    must stay at block top). GOTCHAS: 'OpPhi must be at block top'."""
    return _opcode(mod.lines[line + 1].strip()) not in BLOCKING


def build(mod, family, k, rays, mode='dark', decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)
    fam = FAMILIES[family]

    # ---- detectors, ALL of them, before any edit (GOTCHAS 12) -------------
    sun, locs = find_cones(mod, fs, fe)
    tps = find_cone_taps(mod, fs, fe)
    if len(tps) != 6:
        die(f"{mod.name}: {len(tps)} flags-16 cone taps, expected 6 "
            f"(2 per cone x 3 cones)")
    geo = find_sun_geometry(mod, sun, tps)
    lid = find_launch_id(mod)
    counter, phdr = find_path_counter(mod, fs, fe)
    legacy = None
    try:
        legacy = E.find_bounce_counter(mod, fs, fe, geo['taps'][0]['line'])
    except SystemExit:
        legacy = None
    if decoy == 'counter':
        if legacy is None:
            die(f"{mod.name}: --decoy counter needs the legacy helper")
        counter = legacy
    mat = find_primary_material(mod, sun['cls'], fs, fe)
    nodes = [find_channel_node(mod, c) for c in [sun] + locs]
    writes = find_image_writes(mod) if mode == 'hit' else []

    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$',
                        l) for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR -- SkipAABBsKHR "
            f"(0x200) would be illegal")

    flags = FLAGS_DECOY if decoy == 'flags' else FLAGS
    tmax = fam['tmax']
    if decoy == 'tmax':
        # the OTHER family's reach: a real number, in range, and wrong.
        tmax = FAMILIES['crevice' if family == 'fold' else 'fold']['tmax']
    kch = channel_k(family, K_STRENGTH)
    if decoy == 'notint':
        kch = (K_STRENGTH, K_STRENGTH, K_STRENGTH)

    n_trace_before = sum(1 for l in mod.lines if 'OpTraceRayKHR' in l)
    rep = {"family": family, "mode": mode, "k": k, "rays": rays,
           "ray_flags": flags, "ray_flags_names": FLAGS_NAMES,
           "tmin": TMIN, "tmax": tmax, "eps_n": EPS_N, "decoy": decoy,
           "gate_mask": GATE_MASK, "k_strength": K_STRENGTH,
           "channel_k": list(kch), "tint": FAMILIES[family]['tint'],
           "cloth_f0max": CLOTH_F0MAX, "cloth_a0": CLOTH_A0,
           "cloth_a1": CLOTH_A1, "crev_rmin": CREV_RMIN,
           "crev_metmax": CREV_METMAX,
           "commit": "first (TerminateOnFirstHit)",
           "cone_k": sun['k'], "class_word": sun['cls'],
           "base_cone_counter": sun['ctr'], "path_counter": counter,
           "path_header": phdr, "legacy_counter": legacy,
           "legacy_helper_was_wrong": (legacy is not None and legacy != counter),
           "base_cone_gate_was_sample": sun['ctr'] != counter,
           "sun_cone_line": sun['occk_line'] + 1,
           "local_cone_lines": [c['occk_line'] + 1 for c in locs],
           "origin": geo['org'], "normal": geo['nraw'], "accel": geo['accel'],
           "launch_id": lid,
           "material": {k2: v for k2, v in mat.items() if k2 != 'line'},
           "material_line": mat['line'] + 1,
           "channel_nodes": [dict(node=n[0], line=n[1] + 1,
                                  consumers=[c + 1 for c in n[2]], shape=n[3])
                             for n in nodes],
           "cone_taps": [t['line'] + 1 for t in tps],
           "traces_before": n_trace_before,
           "tap_dirs": taps(rays)}

    if k == 0.0:
        rep["emitted"] = 0
        rep["why"] = "k=0: identity control, no instructions"
        return [], [], rep

    # everything the estimator reads must dominate every site it feeds
    for tag, idt in (("path counter", counter), ("class word", sun['cls']),
                     ("metallic", mat['met']), ("roughness", mat['rough']),
                     ("F0.r", mat['f0'][0]), ("F0.g", mat['f0'][1]),
                     ("F0.b", mat['f0'][2])):
        dl, _ = mod.find_def(idt)
        if dl is None:
            die(f"{mod.name}: {tag} {idt} has no definition")
        if not cfg_dom.dominates(mod, fs, fe, dl, sun['occk_line']):
            die(f"{mod.name}: {tag} (line {dl+1}) does not dominate the "
                f"estimator at line {sun['occk_line']+1}")
    for c in locs:
        if not cfg_dom.dominates(mod, fs, fe, sun['occk_line'], c['occk_line']):
            die(f"{mod.name}: the estimator (line {sun['occk_line']+1}) does "
                f"not dominate the local cone at line {c['occk_line']+1}")
    for node, nline, cons, shape in nodes:
        if not _insertable_after(mod, nline):
            die(f"{mod.name}: line {nline+1} is followed by "
                f"{mod.lines[nline+1].strip()[:40]!r} -- nothing can be "
                f"inserted after the channel node")
        for ci in cons:
            if ci <= nline:
                die(f"{mod.name}: a channel consumer at line {ci+1} precedes "
                    f"its node at line {nline+1}")

    # ---- types / constants ------------------------------------------------
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    ptrIU = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Input %uint\s*$',
        lambda n: f"    {n} = OpTypePointer Input %uint")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")

    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u4 = _uc(mod, consts, CLS_HAIR)
    u8 = _uc(mod, consts, 8)
    umask = _uc(mod, consts, GATE_MASK)
    uflags = _uc(mod, consts, flags)
    uha, uhb, uhc = (_uc(mod, consts, H_A), _uc(mod, consts, H_B),
                     _uc(mod, consts, H_C))
    f0c, f1c = '%float_0', '%float_1'
    fn1 = _fc(mod, consts, -1.0)
    feps = _fc(mod, consts, EPS_N)
    fneps = _fc(mod, consts, NEPS)
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, tmax)
    finvk = _fc(mod, consts, 1.0 / rays)
    f2pi24 = _fc(mod, consts, 2.0 * math.pi / 16777216.0)
    dirc = [[_fc(mod, consts, v) for v in d] for d in taps(rays)]
    # per-channel strengths, deduped by VALUE (mod.const memoises, so an
    # achromatic family hands back ONE id three times) -- the fold family
    # therefore emits one factor chain and the crevice family three, and the
    # census asserts exactly that.
    kch_ids = [_fc(mod, consts, v) for v in kch]
    korder = []
    for cid in kch_ids:
        if cid not in korder:
            korder.append(cid)
    if family == 'fold':
        fa0 = _fc(mod, consts, CLOTH_A0)
        framp = _fc(mod, consts, CLOTH_RAMP)
        ff0max = _fc(mod, consts, CLOTH_F0MAX)
    else:
        frmin = _fc(mod, consts, CREV_RMIN)
        fmetmax = _fc(mod, consts, CREV_METMAX)
    if mode == 'hit':
        fscale = _fc(mod, consts, HIT_SCALE)

    # ---- entry block: the query object (+ the -hit latch), ONE edit --------
    eb_lab, eb_term = E.entry_block_span(mod, fs, fe)
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rq = mod.new_id()
    ind0 = '               '
    head = [f"{ind0}{rq} = OpVariable {ptr_rq} Function"]
    hv = None
    if mode == 'hit':
        hv = mod.new_id()
        head.append(f"{ind0}{hv} = OpVariable {ptrFF} Function")
        head.append(f"{ind0}OpStore {hv} {fn1}")
    edits.append((at, head))

    # ---- the estimator: one straight-line run, no branches ----------------
    ind = re.match(r'(\s*)', mod.lines[sun['occk_line']]).group(1)
    ins = []
    nid = mod.new_id

    def em(fmt):
        i = nid()
        ins.append(f"{ind}{i} = {fmt}")
        return i

    # ---- the gate ---------------------------------------------------------
    # Common to both families: NOT skin, NOT hair, PRIMARY path segment, and a
    # normal that can survive Normalize. 80 sec 2.3: class 1 is cut because
    # skin already owns this site (88's cone, still live underneath); class 4
    # is cut because hair is an anisotropic shifted-specular path.
    if decoy == 'class':
        g_cls = em(f"OpIEqual {boolt} {u1} {u1}")     # always true: the LEAK
    else:
        g_ns = em(f"OpINotEqual {boolt} {sun['cls']} {u1}")
        g_nh = em(f"OpINotEqual {boolt} {sun['cls']} {u4}")
        g_cls = em(f"OpLogicalAnd {boolt} {g_ns} {g_nh}")
    g_p0 = em(f"OpIEqual {boolt} {counter} {u0}")
    g_cp = em(f"OpLogicalAnd {boolt} {g_cls} {g_p0}")

    if family == 'fold':
        # 80/81's dielectric clause: max3(F0) < 0.09 kills every metal
        # (F0 = albedo >= 0.5), glass, clearcoat and polished plastic.
        m01 = em(f"OpExtInst %float {glsl} NMax {mat['f0'][0]} {mat['f0'][1]}")
        m3 = em(f"OpExtInst %float {glsl} NMax {m01} {mat['f0'][2]}")
        g_mat = em(f"OpFOrdLessThan {boolt} {m3} {ff0max}")
    else:
        g_r = em(f"OpFOrdGreaterThan {boolt} {mat['rough']} {frmin}")
        g_m = em(f"OpFOrdLessThan {boolt} {mat['met']} {fmetmax}")
        g_mat = em(f"OpLogicalAnd {boolt} {g_r} {g_m}")
    g_cm = em(f"OpLogicalAnd {boolt} {g_cp} {g_mat}")

    # a degenerate G-buffer normal must never reach Normalize -> NaN -> an
    # undefined ray direction. 88's select-before-normalize, with a length
    # test in front of it because our gate is wider than 88's.
    nlen = em(f"OpExtInst %float {glsl} Length {geo['nraw']}")
    nok = em(f"OpFOrdGreaterThan {boolt} {nlen} {fneps}")
    gate = em(f"OpLogicalAnd {boolt} {g_cm} {nok}")
    msk = em(f"OpSelect %uint {gate} {umask} {u0}")
    nsel = em(f"OpSelect %v3float {gate} {geo['nraw']} {geo['lv']}")
    Nu = em(f"OpExtInst %v3float {glsl} Normalize {nsel}")

    # origin = the cone's own origin, lifted EPS along N
    ne = em(f"OpVectorTimesScalar %v3float {Nu} {feps}")
    org = em(f"OpFAdd %v3float {geo['org']} {ne}")

    # pixel-seeded rotation angle. gl_LaunchID only: frame-stable by
    # construction, and 98 sec 12.6's audit stays true (nothing per-frame).
    axc = em(f"OpAccessChain {ptrIU} {lid} {u0}")
    px = em(f"OpLoad %uint {axc}")
    ayc = em(f"OpAccessChain {ptrIU} {lid} {u1}")
    py = em(f"OpLoad %uint {ayc}")
    h1 = em(f"OpIMul %uint {px} {uha}")
    h2 = em(f"OpIMul %uint {py} {uhb}")
    h3 = em(f"OpBitwiseXor %uint {h1} {h2}")
    h4 = em(f"OpIMul %uint {h3} {uhc}")
    h5 = em(f"OpShiftRightLogical %uint {h4} {u8}")
    hf = em(f"OpConvertUToF %float {h5}")
    psi = em(f"OpFMul %float {hf} {f2pi24}")
    cps = em(f"OpExtInst %float {glsl} Cos {psi}")
    sps = em(f"OpExtInst %float {glsl} Sin {psi}")

    # orthonormal basis about N -- Duff et al. 2017, branch-free.
    nx = em(f"OpCompositeExtract %float {Nu} 0")
    ny = em(f"OpCompositeExtract %float {Nu} 1")
    nz = em(f"OpCompositeExtract %float {Nu} 2")
    if decoy == 'basis':
        Tv = em(f"OpCompositeConstruct %v3float {f1c} {f0c} {f0c}")
        Bv = em(f"OpCompositeConstruct %v3float {f0c} {f1c} {f0c}")
    else:
        zp = em(f"OpFOrdGreaterThanEqual {boolt} {nz} {f0c}")
        sgn = em(f"OpSelect %float {zp} {f1c} {fn1}")
        den = em(f"OpFAdd %float {sgn} {nz}")
        a = em(f"OpFDiv %float {fn1} {den}")
        nxy = em(f"OpFMul %float {nx} {ny}")
        b = em(f"OpFMul %float {nxy} {a}")
        nxx = em(f"OpFMul %float {nx} {nx}")
        nxxa = em(f"OpFMul %float {nxx} {a}")
        t0a = em(f"OpFMul %float {sgn} {nxxa}")
        t0 = em(f"OpFAdd %float {f1c} {t0a}")
        t1 = em(f"OpFMul %float {sgn} {b}")
        t2a = em(f"OpFMul %float {sgn} {nx}")
        t2 = em(f"OpFNegate %float {t2a}")
        Tv = em(f"OpCompositeConstruct %v3float {t0} {t1} {t2}")
        nyy = em(f"OpFMul %float {ny} {ny}")
        nyya = em(f"OpFMul %float {nyy} {a}")
        b1 = em(f"OpFAdd %float {sgn} {nyya}")
        b2 = em(f"OpFNegate %float {ny}")
        Bv = em(f"OpCompositeConstruct %v3float {b} {b1} {b2}")

    # rotate the BASIS once, not each direction
    tc = em(f"OpVectorTimesScalar %v3float {Tv} {cps}")
    bs = em(f"OpVectorTimesScalar %v3float {Bv} {sps}")
    Tr = em(f"OpFAdd %v3float {tc} {bs}")
    ts = em(f"OpVectorTimesScalar %v3float {Tv} {sps}")
    bc = em(f"OpVectorTimesScalar %v3float {Bv} {cps}")
    Br = em(f"OpFSub %v3float {bc} {ts}")

    acc = None
    for j in range(rays):
        cx, cy, cz = dirc[j]
        d1 = em(f"OpVectorTimesScalar %v3float {Tr} {cx}")
        d2 = em(f"OpVectorTimesScalar %v3float {Br} {cy}")
        d3 = em(f"OpVectorTimesScalar %v3float {Nu} {cz}")
        d4 = em(f"OpFAdd %v3float {d1} {d2}")
        dj = em(f"OpFAdd %v3float {d4} {d3}")
        ins.append(f"{ind}OpRayQueryInitializeKHR {rq} {geo['accel']} "
                   f"{uflags} {msk} {org} {ftmin} {dj} {ftmax}")
        em(f"OpRayQueryProceedKHR {boolt} {rq}")
        ty = em(f"OpRayQueryGetIntersectionTypeKHR %uint {rq} {u1}")
        hj = em(f"OpINotEqual {boolt} {ty} {u0}")
        cj = em(f"OpSelect %float {hj} {f1c} {f0c}")
        acc = cj if acc is None else em(f"OpFAdd %float {acc} {cj}")
    occ = em(f"OpFMul %float {acc} {finvk}")

    # ---- the family's own weight on o -------------------------------------
    if family == 'fold':
        # 81's roughness ramp, on ALPHA. The raygen carries perceptual
        # roughness and squares it into alpha itself (`r*r`), so alpha is one
        # multiply away and 81's constants transfer verbatim.
        alpha = em(f"OpFMul %float {mat['rough']} {mat['rough']}")
        wa = em(f"OpFSub %float {alpha} {fa0}")
        wb = em(f"OpFMul %float {wa} {framp}")
        wr = em(f"OpExtInst %float {glsl} NClamp {wb} {f0c} {f1c}")
        o_eff = em(f"OpFMul %float {occ} {wr}")
    else:
        o_eff = occ

    if mode == 'hit':
        inv = em(f"OpFSub %float {f1c} {o_eff}")
        gr = em(f"OpFMul %float {inv} {fscale}")
        pv = em(f"OpSelect %float {gate} {gr} {fn1}")
        ins.append(f"{ind}OpStore {hv} {pv}")

    edits.append((sun['occk_line'] - 1, ins))
    rep["splice_instructions"] = len(ins)
    rep["rq_var"] = rq

    # ---- application, per cone, per channel -------------------------------
    # Our factor is multiplied INTO the chain the cone's own `fac` already
    # scales, one level below it. The cone is NOT touched: its `occ` still
    # feeds its own FMul and its six taps keep their live cull masks. The two
    # gates are DISJOINT (ours is class != 1, the cone's is class == 1), so
    # the product is always exactly one factor or the other, never both.
    #
    # Every cone's application is emitted at ITS OWN channel node, including
    # the sun's: the node IS the cone's `fac`, which is defined one line BELOW
    # the estimator's insertion point, so emitting it inside the estimator run
    # would reference an id that does not exist yet (GOTCHAS: "referencing an
    # id defined after the splice point is an undefined-id validation error").
    def apply_at(cone, node, nline, cons):
        lind = re.match(r'(\s*)', mod.lines[nline]).group(1)
        buf = []

        def emit(fmt):
            i = nid()
            buf.append(f"{lind}{i} = {fmt}")
            return i
        gi = emit(f"OpLogicalAnd {boolt} {gate} {cone['lit']}")
        oc = emit(f"OpSelect %float {gi} {o_eff} {f0c}")
        by_k = {}
        for cid in korder:
            p = emit(f"OpFMul %float {oc} {cid}")
            f = emit(f"OpFSub %float {f1c} {p}")
            by_k[cid] = emit(f"OpFMul %float {node} {f}")
        for ch in range(3):
            newnode = by_k[kch_ids[ch]]
            line = cons[ch]
            old = mod.lines[line]
            new = re.sub(re.escape(node) + r'(?![0-9A-Za-z_])', newnode, old)
            if new == old or len(re.findall(
                    re.escape(newnode) + r'(?![0-9A-Za-z_])', new)) != 1:
                die(f"{mod.name}: channel rewrite did not take at line "
                    f"{line+1}")
            mod.lines[line] = new
        edits.append((nline, buf))
        return len(buf)

    n_app = 0
    for cone, (node, nline, cons, shape) in zip([sun] + locs, nodes):
        n_app += apply_at(cone, node, nline, cons)

    rep["cones_scaled"] = 3
    rep["channel_factors"] = len(korder)
    rep["apply_instructions"] = n_app
    rep["cone_taps_neutered"] = 0
    rep["cone_replaced"] = 0

    # ---- --decoy kill: 102's REPLACE, which is wrong here -----------------
    # 102 disconnected each cone's occ and neutered its six tap rays because
    # its term replaced the cone on the SAME pixels. Here the gates are
    # disjoint, so doing that deletes the shipped skin cavity term. The
    # verifier must reject it; this is how the rejection is proved non-vacuous.
    if decoy == 'kill':
        for c in [sun] + locs:
            old = mod.lines[c['occk_line']]
            new = re.sub(r'OpFMul %float ' + re.escape(c['occ']) + r' '
                         + re.escape(c['k']) + r'\s*$',
                         f"OpFMul %float {occ} {c['k']}", old)
            if new == old:
                die(f"{mod.name}: --decoy kill could not disconnect the cone "
                    f"at line {c['occk_line']+1}")
            mod.lines[c['occk_line']] = new
        for t in tps:
            old = mod.lines[t['line']]
            new = re.sub(r'(OpTraceRayKHR %\w+ %uint_' + str(CONE_FLAGS)
                         + r' )' + re.escape(t['mask']), r'\g<1>' + u0, old)
            if new == old:
                die(f"{mod.name}: --decoy kill could not neuter the tap at "
                    f"line {t['line']+1}")
            mod.lines[t['line']] = new
        rep["cone_taps_neutered"] = len(tps)
        rep["cone_replaced"] = 3

    # ---- -hit: paint o as a flat grey ramp over the radiance writes -------
    added, skipped = [], []
    if mode == 'hit':
        for w in writes:
            if w['comps'] is None:
                die(f"{mod.name}: write at line {w['line']+1} has a "
                    f"non-construct texel -- refusing")
            c = w['comps']
            if all(_gi_zeroish(mod, x) for x in c[:3]):
                skipped.append({"line": w['line'] + 1, "why": "constant-zero"})
                continue
            if c[0] == c[1] == c[2]:
                skipped.append({"line": w['line'] + 1,
                                "why": "scalar-broadcast"})
                continue
            wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
            wi, newc = [], []
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {hv}")
            u = nid(); wi.append(f"{wind}{u} = OpFOrdGreaterThanEqual {boolt} "
                                 f"{l} {f0c}")
            for ch in range(3):
                s = nid()
                wi.append(f"{wind}{s} = OpSelect %float {u} {l} {c[ch]}")
                newc.append(s)
            nt = nid()
            wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                      f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
            edits.append((w['line'] - 1, wi))
            mod.lines[w['line']] = re.sub(
                r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
                mod.lines[w['line']])
            added.append({"line": w['line'] + 1})
    rep["writes_painted"], rep["writes_skipped"] = added, skipped
    return consts, edits, rep


def process(path, outdir, family, k, rays, mode='dark', decoy=None,
            do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['concavity'] = build(mod, family, k, rays, mode, decoy)
    if k != 0.0:
        apply_edits(mod, consts, edits)
        _add_header(mod)
    # k == 0: nothing was emitted and nothing was rewritten, so the module is
    # written back exactly as disassembled -> byte-identical to the base.

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', spv_out],
                       capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--family', required=True, choices=sorted(FAMILIES))
    ap.add_argument('--k', type=float, required=True,
                    help='0 = the byte-identity CONTROL (emit nothing); '
                         '1 = live')
    ap.add_argument('--rays', type=int, default=4,
                    help='K, the number of contact queries per gated pixel')
    ap.add_argument('--mode', default='dark', choices=('dark', 'hit'),
                    help="dark = the darkening; hit = the flat grey occlusion "
                         "map, readable independently of the darkening")
    ap.add_argument('--decoy',
                    choices=('flags', 'tmax', 'counter', 'basis', 'class',
                             'notint', 'kill'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_concavity.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if a.k not in (0.0, 1.0):
        ap.error('--k is a switch: 0 = control, 1 = live')
    if a.rays < 1 or a.rays > 32:
        ap.error('--rays out of range')
    if a.decoy == 'notint' and a.family != 'crevice':
        ap.error('--decoy notint only means anything for --family crevice')
    print(json.dumps(process(a.spvasm, a.outdir, a.family, a.k, a.rays,
                             a.mode, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
