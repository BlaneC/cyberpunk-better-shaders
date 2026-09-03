#!/usr/bin/env python3
"""thinglow -- BACKLIT TRANSLUCENCY FOR EVERY THIN NON-SKIN SURFACE.
handoff/105.

WHAT THIS IS. `101`'s ear glow measures the sun-path thickness of the primary
surface with three inline ray queries and adds a Beer-Lambert transmission
term. Its gate is `class == 1` (SKIN). Everything about the *measurement* is
material-agnostic: a curtain, a tent wall, an umbrella, a paper sign, a tarp
and a shirt are all thin closed shells with a sunward backface a few
millimetres in. This build takes `101` sec 16's query C construction verbatim
and points it at the complement of skin.

    gate   NOT class 1 (skin: the ear glow owns it and MUST stay bit-identical)
           NOT class 4 (hair: `54`/`57`)
           NOT class 8 (eyes -- see THE CLASS 8 NOTE below; this term is
                        VACUOUS on today's dump and is emitted anyway)
           metallic  < M_MAX (0.1)   -- the module's OWN metallic byte
           roughness > R_MIN (0.5)   -- the module's OWN roughness byte
           backlit                   -- the module's OWN N.S <= 0 boolean
           path segment == 0         -- the primary surface only

    query A  517, camera origin, the module's own view ray, +/-0.1% bracket
             on |P|, committed InstanceId          (98 sec 2.1, 101 sec 12.5)
    query B  545 (Opaque|CullFrontFacing|SkipAABBs), the NEE trace's own
             origin P and direction S, tmin 0.3 mm, tmax 25 mm, committed
             CLOSEST, committed InstanceId and committed T = THE THICKNESS
    query C  517, origin P + (t_B + 1 mm)*S, tmin 1 mm, the module's own sun
             shadow-ray tmax, no culling: "can the exit point see the sun"

    accept <=> gate AND A committed AND B committed
               AND A.InstanceId == B.InstanceId AND C MISSED

    transfer   L += k * exp(-t/LD) * albedo_c * sunRadiance_c,  clamped
               LD = 2 mm SCALAR (one Exp, shared by the three channels)
               albedo_c = the module's own base-colour G-buffer, SQUARED --
               which is what the module itself does with it two instructions
               later (OpFMul %a %a), so a red tarp glows red.

WHY THE THICKNESS RANGE MOVED. `101` uses tmin 1.5 mm (the thinnest ear) and
tmax 18 mm (the thickest pinna). Cloth, plastic sheeting and paper are an
order of magnitude thinner and their folds are thicker, so the bracket is
[0.3 mm, 25 mm]. The 0.3 mm floor is what still rejects a decal or a coplanar
z-fight; the 25 mm ceiling is what stops the query reading through a doorway.

WHY A SINGLE EXPONENTIAL. `101` needs a dual lobe because it carries three
per-channel mean free paths (Jensen skin1) and a single lobe turns 1 mm of
thickness error into a 3.9x brightness error on flesh. Here the colour comes
from the ALBEDO, not from the per-channel rates, so one scalar LD is the whole
model and the three channels differ only by albedo. One Exp, not six.

WHY IT ADDS AND DOES NOT MULTIPLY. `98` sec 12.4, measured: a multiply on the
reference raygen's radiance is invisible on a lit surface and is still zero on
a dark one. Backlit cloth is dark. `0 * anything = 0`.

THE ALPHA-TEST DECISION (handoff/105 sec 6, and it is a CHOICE, not an
oversight). All three queries carry `Opaque` (0x01), so alpha-tested geometry
commits its bounding triangle instead of being pierced (`98` sec 2.3). The
alternative is NOT "flags without Opaque so any-hit runs": a Vulkan RAY QUERY
never executes an any-hit shader. Dropping Opaque only makes traversal hand
non-opaque candidates back to the shader, which must then either confirm them
(identical to Opaque), reject them all (which deletes alpha-cut curtains and
tarps -- the surfaces this feature exists for), or run an alpha test it cannot
run at a raygen with no UVs and no material binding. Any of the three needs a
`while(OpRayQueryProceedKHR)` loop inside a 15 000-line structured CFG with
three nested loops, i.e. exactly the hazard `98` sec 2.3 designed the splice
to avoid. So: Opaque stays, and the false-positive class is PRE-REGISTERED --
see handoff/105 sec 6 and sec 11.

THE CLASS 8 NOTE. The brief asks for `NOT class 8 (eyes)`. `94` sec 1.1's
whole-dump census (3290 modules) finds the class vocabulary is exactly
{0, 1, 3, 4, 5}; `96` sec 2.1 confirms nothing anywhere compares against 2, 6
or 7, and no module writes an 8. THERE IS NO EYE CLASS. The term is emitted
anyway (two instructions, `class != 8`), it can never fire on today's data,
and it is reported as `class8_vacuous: true` so the build and the handoff can
say so rather than implying an eye gate that does not exist. Eyes reach this
feature as class 0 or class 1 and are rejected by geometry instead: an eyeball
is a closed sphere, the sunward backface is >= 12 mm away through the globe,
and query C's exit point is inside the socket -- the same rejection `101`
sec 15.4 measured for the ear glow.

WHAT MAKES THE EAR GLOW SAFE. The gate's first term is `class != 1`, so on a
skin pixel the k select yields the module's own `%float_n0` (NEGATIVE zero),
every operation between it and the radiance write is an FMul by a finite
non-negative factor or an NMin against +100, and `x + (-0.0) == x` bit for bit
for EVERY finite x including -0.0 (which `x + (+0.0)` does not preserve). The
`-0` constant is located by an exact regex, never by `mod.const(-0.0)`:
`Module.fconst` is keyed by a Python float and `-0.0 == 0.0` there, so asking
for -0.0 can hand back `%float_0`. build_thinglow.sh gate 6 asserts the shipped
bytes carry `%float_n0` in the k select's false arm and in the three
accumulator stores.

  ./dev/build_thinglow.sh              # all four rungs + gates
  python3 dev/patch_thinglow.py <in.spvasm> --outdir D --k 0.5 [--mode hit]
          [--ld 0.002] [--decoy ...]

NOT EDITED BY THIS FILE, only imported: dev/patch_rayq.py, dev/patch_earglow.py,
dev/patch_earglow_rq.py, dev/patch_earglow_rq2.py, dev/patch_earglow_rq3.py,
dev/patch_cavity2.py, dev/patch_skin_brdf.py, dev/patch_chs_brdf.py,
dev/patch_compute_brdf.py, dev/patch_subtype_probe.py.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
import patch_earglow as E
from patch_earglow import (find_nee_trace, find_sun_radiance, clone_chain,
                           entry_block_span, CLAMP)
from patch_cavity2 import find_path_counter
# query A's anchor and the header inserter, verbatim from 98.
from patch_rayq import _find_primary_ray, _add_header
# query B's flags and the shared cull-mask value, verbatim from 101 sec 2.
from patch_earglow_rq import _ensure_line, FLAGS, FLAGS_NAMES, GATE_MASK
# query A's flags and bracket, verbatim from 101 sec 12.
from patch_earglow_rq2 import (FLAGS_A, FLAGS_A_NAMES, BRACKET_LO, BRACKET_HI,
                               BRACKET_EPS, GETTER_ID)

# --- this build's own numbers ----------------------------------------------
FLAGS_C = FLAGS_A                   # 517: C asks only "is anything in the way"
FLAGS_C_NAMES = FLAGS_A_NAMES
PUSH = 0.001                        # 1 mm past the committed wall, into air
TMIN_C = 0.001

TMIN = 0.0003        # 0.3 mm -- cloth/plastic/paper are thinner than an ear
TMAX = 0.025         # 25 mm  -- a folded curtain, not a doorway
LD_M = 0.002         # 2 mm scalar mean free path (the colour is the albedo)
M_MAX = 0.1          # metallic strictly below this
R_MIN = 0.5          # roughness strictly above this
CLS_SKIN, CLS_HAIR, CLS_EYES = 1, 4, 8

# The -hit diagnostic's amplitude, in units of the sun radiance -- the same
# 0.32 the `101` sec 13.3 / sec 16.1 maps use, so the two diagnostics are
# directly comparable in one frame (101 sec 12.3: a paint fixed in absolute
# radiance is unreadable on a lit surface).
DIAG = 0.32

DECOYS = ('noc', 'cullfront', 'invert', 'noskin', 'nometal', 'norough',
          'noalbedo', 'wideband')

# The base MUST already carry `101` sec 16's three queries and sec 18's floor.
# These are the rate constants of the ear glow's dual-lobe transfer at
# wide=4.0 and the 6 mm floor, read back out of the shipped default's bytes.
EARGLOW_MARKERS = ('%float_272_479553', '%float_68_1198883',
                   '%float_729_927002', '%float_182_48175',
                   '%float_1470_58826', '%float_367_647064',
                   '%float_0_219999999', '%float_0_00600000005')


def _res(line):
    m = re.match(r'\s*(%\w+)\s*=\s*Op', line)
    return m.group(1) if m else None


def uval(mod, ident):
    _, body = mod.find_def(ident)
    m = re.match(r'OpConstant %\w+ (\d+)$', body or '')
    return int(m.group(1)) if m else None


def fval_of(mod, ident):
    _, body = mod.find_def(ident)
    m = re.match(r'OpConstant %\w+ ([-+0-9.eE]+)$', body or '')
    return float(m.group(1)) if m else None


def _negzero(mod, consts):
    """The module's own `OpConstant %float -0`, by EXACT text.

    NOT `mod.const(-0.0)`: `Module.fconst` is a dict keyed by a Python float
    and `-0.0 == 0.0` hashes equal there, so that call can return `%float_0`
    -- which would turn the gate-shut identity from `x + (-0.0) == x` into
    `x + (+0.0)`, and the latter does not preserve a -0.0 radiance component.
    """
    return _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpConstant %float -0\s*$',
                        lambda n: f"    {n} = OpConstant %float -0")


def _poszero(mod, consts):
    return _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpConstant %float 0\s*$',
                        lambda n: f"    {n} = OpConstant %float 0")


def _fc(mod, consts, v):
    """`mod.const` with the -0/+0 collision made impossible: this refuses to
    be asked for a zero at all. Use _negzero/_poszero for those."""
    if v == 0.0:
        die("_fc: use _negzero()/_poszero() -- Module.fconst cannot tell "
            "-0.0 from +0.0")
    nid, decl = mod.const(v)
    if decl:
        consts.append(decl)
    return nid


def _uc(mod, consts, v, _memo={}):
    """Memoised, because `Module.uconst` scans `mod.lines` only and cannot see
    a constant still pending in `consts` -- asking twice would mint the id
    twice and spirv-val rejects `Id N is defined more than once` (GOTCHAS)."""
    key = (id(mod), int(v))
    if key in _memo:
        return _memo[key]
    nid, decl = mod.uconst(v)
    if decl:
        consts.append(decl)
    _memo[key] = nid
    return nid


# --------------------------------------------------------------------------
def find_material_site(mod, fs, fe):
    """The module's OWN primary-surface material read, located structurally.

    `96` sec 2.2 records that every `rgs_reference_main` permutation is
    "compare-only" on the class and carries, in one place, the test

        skin  <=>  class == 1  AND  metallic < 0.1

    That test is the anchor, and it is mode-independent (GOTCHAS 4): it is not
    a constant that happens to appear, it is the module's own material
    decision, and everything this build needs hangs off it.

        %F   = OpImageFetch %v4float ...        the material G-buffer
        %m   = OpCompositeExtract %float %F 0   METALLIC
        %r   = OpCompositeExtract %float %F 1   ROUGHNESS, and the module
               proves that reading by clamping it NMax(.,0.04) -> NMin(.,1)
               and seeding the path loop's roughness phi with it (94 sec 2.1)
        %c   = OpShiftRightLogical %uint %w %uint_5      the CLASS
        %lt  = OpFOrdLessThan %bool %m %float_0_100000001
        %eq  = OpIEqual %bool %c %uint_1
        %res = OpLogicalAnd %bool %lt %eq          (either operand order)

    and, hanging off %res, the base-colour fetch:

        %G   = OpImageFetch %v4float ...        the base-colour G-buffer
        %a_i = OpCompositeExtract %float %G i    i = 0,1,2
        %sq  = OpFMul %float %a_i %a_i           the module SQUARES it
        OpSelect %float %res %float_1 %sq        (skin gets 1.0 instead)

    The albedo is tied to the SAME site by that select, so this cannot pick up
    an unrelated fetch. Refuses unless there is exactly one such site and
    unless all three colour channels are present (GOTCHAS 10: a shape found is
    not a place found -- the uniqueness is what makes it a place).
    """
    defs = {}
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*)$', mod.lines[i])
        if m:
            defs[m.group(1)] = (m.group(2), i)

    def body(x):
        return defs.get(x, ('', -1))[0]

    hits = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLogicalAnd %bool (%\w+) (%\w+)\s*$',
                     mod.lines[i])
        if not m:
            continue
        res, o1, o2 = m.groups()
        for lt, eq in ((o1, o2), (o2, o1)):
            dm = re.match(r'OpFOrdLessThan %bool (%\w+) (%float_\w+)$', body(lt))
            de = re.match(r'OpIEqual %bool (%\w+) %uint_1$', body(eq))
            if not (dm and de):
                continue
            thr = fval_of(mod, dm.group(2))
            if thr is None or abs(thr - M_MAX) > 1e-6:
                continue
            met, cls = dm.group(1), de.group(1)
            em = re.match(r'OpCompositeExtract %float (%\w+) 0$', body(met))
            if not em:
                continue
            F = em.group(1)
            if not body(F).startswith('OpImageFetch %v4float'):
                continue
            if not re.match(r'OpShiftRightLogical %uint %\w+ %uint_5$', body(cls)):
                continue
            rough = [k for k, v in defs.items()
                     if v[0] == f'OpCompositeExtract %float {F} 1']
            if len(rough) != 1:
                continue
            rq = rough[0]
            c1 = [k for k, v in defs.items() if re.match(
                r'OpExtInst %float %\w+ NMax ' + re.escape(rq)
                + r' %float_0_0399999991$', v[0])]
            c2 = [k for k, v in defs.items() if c1 and re.match(
                r'OpExtInst %float %\w+ NMin ' + re.escape(c1[0])
                + r' %float_1$', v[0])]
            if not (c1 and c2):
                continue
            alb, gset = {}, set()
            for k, v in defs.items():
                sm = re.match(r'OpSelect %float ' + re.escape(res)
                              + r' %float_1 (%\w+)$', v[0])
                if not sm:
                    continue
                fm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(sm.group(1)))
                if not (fm and fm.group(1) == fm.group(2)):
                    continue
                am = re.match(r'OpCompositeExtract %float (%\w+) ([012])$',
                              body(fm.group(1)))
                if not am:
                    continue
                alb[int(am.group(2))] = fm.group(1)
                gset.add(am.group(1))
            if sorted(alb) != [0, 1, 2] or len(gset) != 1:
                continue
            G = gset.pop()
            if not body(G).startswith('OpImageFetch %v4float') or G == F:
                continue
            hits.append(dict(line=i + 1, skin_bool=res, material_fetch=F,
                             albedo_fetch=G, metallic=met, roughness=rq,
                             rough_clamped=c2[0], cls=cls,
                             albedo=[alb[0], alb[1], alb[2]]))
    if len(hits) != 1:
        die(f"{mod.name}: expected exactly ONE class==1 && metallic<0.1 "
            f"material site, found {len(hits)}")
    return hits[0]


def assert_earglow_base(mod, fs, fe):
    """This rung STACKS. Refuse to build on anything that is not the standing
    default -- the ear glow's three queries and `101` sec 18's 6 mm floor must
    ALREADY be in the input bytes, or `--k 0` reproducing the base proves
    nothing and "the ear glow is untouched" is a claim about a shader that
    never carried it."""
    text = '\n'.join(mod.lines[fs:fe])
    n_i = text.count('OpRayQueryInitializeKHR')
    n_p = text.count('OpRayQueryProceedKHR')
    n_d = text.count('OpRayQueryGetIntersectionInstanceIdKHR')
    n_t = text.count('OpRayQueryGetIntersectionTKHR')
    if (n_i, n_p, n_d, n_t) != (3, 3, 2, 1):
        die(f"{mod.name}: the base carries {n_i}/{n_p}/{n_d}/{n_t} ray-query "
            f"Initialize/Proceed/InstanceId/T, want 3/3/2/1 -- this is not "
            f"the earglow-cap6 stack and thinglow refuses to stack on it")
    missing = [c for c in EARGLOW_MARKERS
               if not any(re.match(r'\s*' + re.escape(c) + r'\s*=\s*OpConstant',
                                   l) for l in mod.lines)]
    if missing:
        die(f"{mod.name}: the base is missing the ear glow's own constants "
            f"{missing} -- refusing to stack")
    return dict(base_queries=[n_i, n_p, n_d, n_t],
                base_markers=list(EARGLOW_MARKERS))


# --------------------------------------------------------------------------
def build(mod, k, ld, mode='glow', decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, ALL of them, before any edit (GOTCHAS 12) -------------
    writes = find_image_writes(mod)
    nee = find_nee_trace(mod, fs, fe)
    sunrad = find_sun_radiance(mod, nee["line"])
    counter, phdr = find_path_counter(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)
    mat = find_material_site(mod, fs, fe)
    stacked = assert_earglow_base(mod, fs, fe)
    if prim['line'] > nee["line"]:
        die(f"{mod.name}: the primary reconstruction (line {prim['line']}) is "
            f"below the splice site (line {nee['line']+1}) -- query A's ids "
            f"would not dominate")
    eb_lab, eb_term = entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability -- "
            f"ray flag SkipAABBsKHR (0x200) would be illegal")
    accel = nee["ops"][0]
    aline, _ = mod.find_def(accel)
    if aline is None or aline > nee["line"]:
        die(f"{mod.name}: acceleration structure {accel} has no definition "
            f"above the sun-NEE trace")

    # Query C must see the occluders the SUN sees, so its cull mask has to be
    # the module's own sun shadow-ray mask. Asserted, never assumed (101
    # sec 16.1): a module whose shadow ray uses a different mask would give C
    # a different occluder set than the sun and the test would be a lie.
    _, mbody = mod.find_def(nee["ops"][2])
    msel = re.match(r'OpSelect %\w+ (%\w+) (%\w+) (%\w+)$', mbody or '')
    if not msel:
        die(f"{mod.name}: the sun shadow ray's cull mask {nee['ops'][2]} is "
            f"not an OpSelect -- cannot re-derive the sun's occluder set")
    marms = [uval(mod, msel.group(2)), uval(mod, msel.group(3))]
    if sorted(x for x in marms if x is not None) != [0, GATE_MASK]:
        die(f"{mod.name}: the sun shadow ray's cull mask arms are {marms}, "
            f"want [0, {GATE_MASK}]")
    tmax_c = nee["ops"][9]
    if uval(mod, tmax_c) is None and fval_of(mod, tmax_c) is None:
        die(f"{mod.name}: the sun shadow ray's tmax {tmax_c} is not a constant")

    tmax_b = TMAX * 4.0 if decoy == 'wideband' else TMAX
    rep = {
        "mode": mode, "k": k, "ld_m": ld, "tmin": TMIN, "tmax": tmax_b,
        "m_max": M_MAX, "r_min": R_MIN,
        "excluded_classes": [CLS_SKIN, CLS_HAIR, CLS_EYES],
        "class8_vacuous": True,          # 94 sec 1.1 / 96 sec 2.1: no class 8
        "ray_flags_a": FLAGS_A, "ray_flags_a_names": FLAGS_A_NAMES,
        "ray_flags_b": FLAGS, "ray_flags_b_names": FLAGS_NAMES,
        "ray_flags_c": FLAGS_C, "ray_flags_c_names": FLAGS_C_NAMES,
        "opaque_alpha_test_accepted": True,   # handoff/105 sec 6
        "bracket": [BRACKET_LO, BRACKET_HI, BRACKET_EPS],
        "commit_a": "first", "commit_b": "closest",
        "match_getter": GETTER_ID,
        "match_op": "OpINotEqual" if decoy == 'invert' else "OpIEqual",
        "push_c": PUSH, "tmin_c": TMIN_C, "tmax_c": tmax_c,
        "tmax_c_value": (uval(mod, tmax_c) if uval(mod, tmax_c) is not None
                         else fval_of(mod, tmax_c)),
        "sun_mask_arms": marms, "gate_mask": GATE_MASK,
        "vis_gate": decoy != 'noc',
        "vis_flags_cull_front": decoy == 'cullfront',
        "vis_inverted": decoy == 'invert',
        "gate_not_skin": decoy != 'noskin',
        "gate_metallic": decoy != 'nometal',
        "gate_roughness": decoy != 'norough',
        "albedo_tinted": decoy != 'noalbedo',
        "decoy": decoy,
        "nee_line": nee["line"] + 1, "accel": accel,
        "origin": nee["ops"][6], "direction": nee["ops"][8],
        "backlit": nee["backlit"], "sun_radiance": sunrad,
        "path_counter": counter, "path_header": phdr,
        "primary_line": prim['line'], "primary_V": prim['V'],
        "material_site": {kk: mat[kk] for kk in
                          ('line', 'skin_bool', 'material_fetch',
                           'albedo_fetch', 'metallic', 'roughness', 'cls')},
        "diag_scaled_by_sun_radiance": mode == 'hit',
        "diag_amplitude": DIAG if mode == 'hit' else None,
        "stacked_on": stacked,
    }

    # ---- types / constants ------------------------------------------------
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")

    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    umask = _uc(mod, consts, GATE_MASK)
    ucls = {c: _uc(mod, consts, c)
            for c in (CLS_SKIN, CLS_HAIR, CLS_EYES)}
    uflags_a = _uc(mod, consts, FLAGS_A)
    uflags_b = _uc(mod, consts, FLAGS)
    # FLAGS_C == FLAGS_A for the live rungs; _uc is memoised so asking twice
    # returns the same id and declares it once.
    uflags_c = (_uc(mod, consts, 0x10 | FLAGS_C) if decoy == 'cullfront'
                else uflags_a)

    fn0 = _negzero(mod, consts)          # the gate-shut identity: -0.0
    fp0 = _poszero(mod, consts)
    if fn0 == fp0:
        die(f"{mod.name}: -0 and +0 resolved to the same id ({fn0}) -- the "
            f"gate-shut identity would not be exact")
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, tmax_b)
    flo = _fc(mod, consts, BRACKET_LO)
    fhi = _fc(mod, consts, BRACKET_HI)
    feps = _fc(mod, consts, BRACKET_EPS)
    fpush = _fc(mod, consts, PUSH)
    ftmin_c = _fc(mod, consts, TMIN_C)
    fmmax = _fc(mod, consts, M_MAX)
    frmin = _fc(mod, consts, R_MIN)
    fclamp = _fc(mod, consts, CLAMP)
    v3zero = _ensure_line(
        mod, consts,
        r'\s*(%\w+)\s*=\s*OpConstantComposite %v3float '
        + re.escape(fp0) + r' ' + re.escape(fp0) + r' ' + re.escape(fp0) + r'\s*$',
        lambda n: f"    {n} = OpConstantComposite %v3float {fp0} {fp0} {fp0}")
    if mode == 'hit':
        fdiag = _fc(mod, consts, DIAG)
        fone = _ensure_line(mod, consts,
                            r'\s*(%\w+)\s*=\s*OpConstant %float 1\s*$',
                            lambda n: f"    {n} = OpConstant %float 1")
        fspan = _fc(mod, consts, 1.0 / (tmax_b - TMIN))
    else:
        fk = _fc(mod, consts, k) if k != 0.0 else fn0
        finv = _fc(mod, consts, 1.0 / ld)

    # ---- entry block: THREE query objects + 3 accumulators, ONE edit -------
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rqA, rqB, rqC = mod.new_id(), mod.new_id(), mod.new_id()
    gv = [mod.new_id() for _ in range(3)]
    ind0 = '               '
    edits.append((at, [f"{ind0}{rqA} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqB} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqC} = OpVariable {ptr_rq} Function"]
                  + [f"{ind0}{g} = OpVariable {ptrFF} Function" for g in gv]
                  + [f"{ind0}OpStore {g} {fn0}" for g in gv]))

    # ---- the splice: straight-line, immediately after the sun-NEE trace ----
    # It lands BETWEEN the trace and `101`'s own block, references nothing that
    # block defines, and defines nothing it consumes. The ear glow's
    # instructions are the same instructions, in the same order, with the same
    # ids -- build_thinglow.sh gate 6 proves that by running 101's own
    # verifiers on the output.
    ops, ind = nee["ops"], nee["ind"]
    ins = []
    nid = mod.new_id

    # ---- the gate ---------------------------------------------------------
    # class, metallic, roughness and albedo are CLONED from the module's own
    # primary G-buffer reads rather than referenced: the originals sit in a
    # block far above and proving dominance would be a claim, while a clone
    # back to push constants, the descriptor heap and gl_LaunchID is
    # correct by construction (GOTCHAS: dominance is never assumed).
    cloned, fresh = [], {}
    cls_h = clone_chain(mod, mat['cls'], safe, fresh, cloned, fs)
    met_h = clone_chain(mod, mat['metallic'], safe, fresh, cloned, fs)
    rgh_h = clone_chain(mod, mat['roughness'], safe, fresh, cloned, fs)
    alb_h = [clone_chain(mod, a, safe, fresh, cloned, fs) for a in mat['albedo']]
    for cid, cbody in cloned:
        ins.append(f"{ind}{cid} = {cbody}")
    rep["cloned_ops"] = len(cloned)
    rep["cloned_fetches"] = sum(1 for _, b in cloned if b.startswith('OpImageFetch'))

    terms = []
    if decoy != 'noskin':
        t = nid(); ins.append(f"{ind}{t} = OpINotEqual {boolt} {cls_h} {ucls[CLS_SKIN]}")
        terms.append(t)
    t = nid(); ins.append(f"{ind}{t} = OpINotEqual {boolt} {cls_h} {ucls[CLS_HAIR]}")
    terms.append(t)
    t = nid(); ins.append(f"{ind}{t} = OpINotEqual {boolt} {cls_h} {ucls[CLS_EYES]}")
    terms.append(t)
    if decoy != 'nometal':
        t = nid(); ins.append(f"{ind}{t} = OpFOrdLessThan {boolt} {met_h} {fmmax}")
        terms.append(t)
    if decoy != 'norough':
        t = nid(); ins.append(f"{ind}{t} = OpFOrdGreaterThan {boolt} {rgh_h} {frmin}")
        terms.append(t)
    terms.append(nee['backlit'])
    t = nid(); ins.append(f"{ind}{t} = OpIEqual {boolt} {counter} {u0}")
    terms.append(t)
    g_all = terms[0]
    for t in terms[1:]:
        n = nid(); ins.append(f"{ind}{n} = OpLogicalAnd {boolt} {g_all} {t}")
        g_all = n
    g_msk = nid(); ins.append(f"{ind}{g_msk} = OpSelect %uint {g_all} {umask} {u0}")
    rep["gate_terms"] = len(terms)

    # ---- query A: the primary surface's instance (98, 101 sec 12.5) -------
    tA = nid(); ins.append(f"{ind}{tA} = OpFMul %float {prim['dot']} {prim['rsqrt']}")
    dA = nid(); ins.append(f"{ind}{dA} = OpCompositeConstruct %v3float "
                           f"{prim['V'][0]} {prim['V'][1]} {prim['V'][2]}")
    aLo = nid(); ins.append(f"{ind}{aLo} = OpFMul %float {tA} {flo}")
    aH0 = nid(); ins.append(f"{ind}{aH0} = OpFMul %float {tA} {fhi}")
    aHi = nid(); ins.append(f"{ind}{aHi} = OpFAdd %float {aH0} {feps}")
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqA} {accel} {uflags_a} {g_msk} "
               f"{v3zero} {aLo} {dA} {aHi}")
    proA = nid(); ins.append(f"{ind}{proA} = OpRayQueryProceedKHR {boolt} {rqA}")
    ityA = nid(); ins.append(f"{ind}{ityA} = OpRayQueryGetIntersectionTypeKHR %uint {rqA} {u1}")
    hitA = nid(); ins.append(f"{ind}{hitA} = OpINotEqual {boolt} {ityA} {u0}")
    idA = nid(); ins.append(f"{ind}{idA} = {GETTER_ID} %uint {rqA} {u1}")

    # ---- query B: the sunward cull-front thickness query -------------------
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqB} {accel} {uflags_b} {g_msk} "
               f"{ops[6]} {ftmin} {ops[8]} {ftmax}")
    proB = nid(); ins.append(f"{ind}{proB} = OpRayQueryProceedKHR {boolt} {rqB}")
    ityB = nid(); ins.append(f"{ind}{ityB} = OpRayQueryGetIntersectionTypeKHR %uint {rqB} {u1}")
    hitB = nid(); ins.append(f"{ind}{hitB} = OpINotEqual {boolt} {ityB} {u0}")
    tqB = nid(); ins.append(f"{ind}{tqB} = OpRayQueryGetIntersectionTKHR %float {rqB} {u1}")
    # the miss guard: T on a non-committed query is UNDEFINED, and one NaN in
    # a radiance accumulator poisons the pixel for the rest of the frame.
    tu = nid(); ins.append(f"{ind}{tu} = OpSelect %float {hitB} {tqB} {ftmax}")
    idB = nid(); ins.append(f"{ind}{idB} = {GETTER_ID} %uint {rqB} {u1}")

    # ---- the instance match (101 sec 12.5) --------------------------------
    same = nid()
    eqop = 'OpINotEqual' if decoy == 'invert' else 'OpIEqual'
    ins.append(f"{ind}{same} = {eqop} {boolt} {idA} {idB}")
    both = nid(); ins.append(f"{ind}{both} = OpLogicalAnd {boolt} {hitA} {hitB}")
    match = nid(); ins.append(f"{ind}{match} = OpLogicalAnd {boolt} {both} {same}")

    # ---- query C: sun visibility from the exit point (101 sec 15.5) -------
    tp = nid(); ins.append(f"{ind}{tp} = OpFAdd %float {tu} {fpush}")
    off = nid(); ins.append(f"{ind}{off} = OpVectorTimesScalar %v3float {ops[8]} {tp}")
    org = nid(); ins.append(f"{ind}{org} = OpFAdd %v3float {ops[6]} {off}")
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqC} {accel} {uflags_c} {g_msk} "
               f"{org} {ftmin_c} {ops[8]} {tmax_c}")
    proC = nid(); ins.append(f"{ind}{proC} = OpRayQueryProceedKHR {boolt} {rqC}")
    ityC = nid(); ins.append(f"{ind}{ityC} = OpRayQueryGetIntersectionTypeKHR %uint {rqC} {u1}")
    hitC = nid(); ins.append(f"{ind}{hitC} = OpINotEqual {boolt} {ityC} {u0}")
    if decoy == 'invert':
        visC = hitC                     # accept exactly the OCCLUDED pixels
    else:
        visC = nid(); ins.append(f"{ind}{visC} = OpLogicalNot {boolt} {hitC}")

    gm = nid(); ins.append(f"{ind}{gm} = OpLogicalAnd {boolt} {g_all} {match}")
    if decoy == 'noc':
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {gm} {gm}")
        nv = nid(); ins.append(f"{ind}{nv} = OpLogicalNot {boolt} {match}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gm} {nv}")
    else:
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {gm} {visC}")
        nv = nid(); ins.append(f"{ind}{nv} = OpLogicalNot {boolt} {visC}")
        rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gm} {nv}")
    rep["vis_id"] = visC
    rep["ok_id"] = ok

    if mode == 'hit':
        # The thickness RAMP. No transfer, no albedo, no k -- it maps where
        # the query committed and how thick it read, and nothing else.
        #   u = NClamp((t - tmin) / (tmax - tmin), 0, 1)
        #   accepted : BLUE at u=0 (0.3 mm) -> GREEN at u=1 (25 mm)
        #   rejected : RED (B committed same-instance, but C HIT)
        # Scaled by the sun radiance, per 101 sec 12.3: a paint fixed in
        # absolute radiance is unreadable next to a lit surface.
        d0 = nid(); ins.append(f"{ind}{d0} = OpFSub %float {tu} {ftmin}")
        d1 = nid(); ins.append(f"{ind}{d1} = OpFMul %float {d0} {fspan}")
        uu = nid(); ins.append(f"{ind}{uu} = OpExtInst %float {glsl} NClamp {d1} {fp0} {fone}")
        gg = nid(); ins.append(f"{ind}{gg} = OpFMul %float {uu} {fdiag}")
        bb = nid(); ins.append(f"{ind}{bb} = OpFSub %float {fdiag} {gg}")
        okv = [fn0, gg, bb]
        rjv = [fdiag, fn0, fn0]
        for c in range(3):
            s0 = nid(); ins.append(f"{ind}{s0} = OpSelect %float {rej} {rjv[c]} {fn0}")
            s1 = nid(); ins.append(f"{ind}{s1} = OpSelect %float {ok} {okv[c]} {s0}")
            s2 = nid(); ins.append(f"{ind}{s2} = OpFMul %float {s1} {sunrad[c]}")
            s3 = nid(); ins.append(f"{ind}{s3} = OpExtInst %float {glsl} NMin {s2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {s3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    else:
        # k * exp(-t/LD) * albedo_c * sunRadiance_c, clamped.
        # ONE Exp: LD is a scalar, so the transmittance is the same for the
        # three channels and all the colour comes from the albedo.
        kg = nid(); ins.append(f"{ind}{kg} = OpSelect %float {ok} {fk} {fn0}")
        e1 = nid(); ins.append(f"{ind}{e1} = OpFMul %float {tu} {finv}")
        e2 = nid(); ins.append(f"{ind}{e2} = OpFNegate %float {e1}")
        tr = nid(); ins.append(f"{ind}{tr} = OpExtInst %float {glsl} Exp {e2}")
        kw = nid(); ins.append(f"{ind}{kw} = OpFMul %float {kg} {tr}")
        for c in range(3):
            if decoy == 'noalbedo':
                m1 = kw
            else:
                sq = nid(); ins.append(f"{ind}{sq} = OpFMul %float {alb_h[c]} {alb_h[c]}")
                m1 = nid(); ins.append(f"{ind}{m1} = OpFMul %float {kw} {sq}")
            m2 = nid(); ins.append(f"{ind}{m2} = OpFMul %float {m1} {sunrad[c]}")
            m3 = nid(); ins.append(f"{ind}{m3} = OpExtInst %float {glsl} NMin {m2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {m3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    edits.append((nee["line"], ins))
    rep["splice_instructions"] = len(ins)
    rep["rq_vars"] = [rqA, rqB, rqC]
    rep["accum_vars"] = gv

    # ---- ADD the accumulated term at every radiance write ------------------
    # The texel operand is ALREADY an OpCompositeConstruct of the ear glow's
    # (and the glints') adds. This chains onto it: `c[ch]` below IS the ear
    # glow's own result, unchanged, and the new construct replaces only the
    # OpImageWrite's operand.
    added, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            die(f"{mod.name}: write at line {w['line']+1} has a non-construct "
                f"texel -- refusing")
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({"line": w['line'] + 1, "why": "constant-zero"})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({"line": w['line'] + 1, "why": "scalar-broadcast"})
            continue
        wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        wi, newc = [], []
        for ch in range(3):
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {gv[ch]}")
            a = nid(); wi.append(f"{wind}{a} = OpFAdd %float {c[ch]} {l}")
            newc.append(a)
        nt = nid()
        wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                  f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((w['line'] - 1, wi))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        added.append({"line": w['line'] + 1})
    if not added:
        die(f"{mod.name}: no radiance write to add the term at")
    rep["writes_added"], rep["writes_skipped"] = added, skipped
    return consts, edits, rep


def process(path, outdir, k, ld, mode='glow', decoy=None, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    if mode == 'glow' and k == 0.0 and decoy is None:
        # THE CONTROL. Nothing is emitted, so the output IS the base bytes --
        # which are the standing default, ear glow, floor, glints and all.
        rep['thinglow'] = {"mode": "control", "k": 0.0, "emitted": 0,
                           "why": "k=0 glow: identity, no instructions"}
    else:
        consts, edits, rep['thinglow'] = build(mod, k, ld, mode, decoy)
        apply_edits(mod, consts, edits)
        _add_header(mod)

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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--k', type=float, required=True)
    ap.add_argument('--ld', type=float, default=LD_M,
                    help='mean free path in METRES (scalar, default 0.002)')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--decoy', choices=DECOYS, default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_thinglow.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    print(json.dumps(process(a.spvasm, a.outdir, a.k, a.ld, a.mode, a.decoy,
                             do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
