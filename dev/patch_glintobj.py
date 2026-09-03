#!/usr/bin/env python3
"""glintobj -- OBJECT-SPACE car-paint glints.

handoff/106-OBJECT-SPACE-GLINTS.md is the document. Read its sec 0 and its
pre-registered table (sec 9) BEFORE looking at a frame, and read `94` sec 2.1
before expecting to see anything on a directly-viewed panel: this raygen shades
bounces >= 1.

    python3 dev/patch_glintobj.py <mod.spvasm> --outdir DIR
                                  [--mode glint|cell|miss|ctl] [--report]
                                  [--decoy world|noselect|primary|nofallback]

WHAT PROBLEM THIS SOLVES
------------------------
`100`'s shipped glints hash a WORLD-space point

    P_w[k] = cbv[..][56][k] + P[k]                (`98` sec 15's proven offset)

into a cell index. A world cell is welded to the WORLD, so on a PARKED car the
flakes are stable -- and on a MOVING car the paint slides through a static
lattice and the flakes CRAWL across the panel. The fix is to hash the same hit
point in the hit object's OWN space, where a rigid body's surface points are
constant no matter where the body is:

    P_o = WorldToObject * (P, 1)                  ; 3x4 affine, columns 0..3

`98` sec 15 proved the TLAS is built in CAMERA-RELATIVE space. That is the
whole reason this is cheap and the reason the member-56 add is NOT wanted here:
ObjectToWorld maps object -> camera-relative, so its inverse maps
CAMERA-RELATIVE -> object. The point to feed the inverse is therefore the
module's own hit position P **without** the offset. Adding member 56 first
would put the camera translation into the object frame twice and is a bug, not
a refinement. (`98` sec 15.4 needed the offset for the opposite reason: it was
reading a translation OUT of ObjectToWorld and into world space.)

WHERE THE MATRIX COMES FROM
---------------------------
`OpRayQueryGetIntersectionWorldToObjectKHR` on the COMMITTED intersection of a
ray query that re-traverses the segment the module has already traced --
`98` sec 2's bounce splice, verbatim in shape:

    t     = payload[3]                     ; the trace's own hit distance
    tmin  = 0.999 t ; tmax = 1.001 t + 1e-4
    OpRayQueryInitializeKHR %rq <accel> 517 <cullMask> <origin> tmin <dir> tmax

with `<accel>`, `<cullMask>`, `<origin>` and `<dir>` cloned BY SSA ID from the
module's own first `OpTraceRayKHR` (`55`'s clone-by-id discipline). Flags
517 = Opaque | TerminateOnFirstHit | SkipAABBs, so no candidate can require
shader intervention, ONE Proceed completes traversal, and the splice adds ZERO
control flow (`98` sec 2.3).

DEVIATION FROM THE BRIEF, STATED UP FRONT
-----------------------------------------
The brief named `98`'s PRIMARY-family splice (camera ray, origin = the zero
triple). That family commits the PRIMARY visible surface. The glint splice
shades a bounce vertex, whose surface is in general a DIFFERENT OBJECT -- so a
primary-ray query would hand the glints the wrong instance's frame and the
flakes would still crawl (worse: they would crawl with whatever is in front of
the camera). The brief's own operative sentence is "so the query commits the
surface you are already shading", and that is the bounce clone. The primary
family IS used, unchanged, for `--mode cell`, where the question is per-pixel
and the primary hit is the surface being asked about.

THE FALLBACK, AND WHY THE FEED IS STILL A REPLACEMENT
-----------------------------------------------------
A query can legitimately commit nothing: an alpha-cut card inside the bracket,
a degenerate segment, `98` sec 3.4's raster/TLAS disagreement. Rather than
hash garbage, each axis becomes

    P_hash[k] = committed ? P_o[k] : P_w[k]

so a miss degrades to EXACTLY `100`'s shipped behaviour. The world feed is
therefore still in the bytes -- and it is DISCONNECTED FROM THE HASH, which is
the claim this patcher makes and `dev/verify_glintobj.py` gate 3 proves:

  * every `OpFDiv %float _ %s` (the cell divide) now takes an `OpSelect`,
    never the `OpFAdd(cb56_k, P_k)` it took in the base;
  * every one of those three `OpFAdd`s has EXACTLY ONE use in the whole
    module: the FALSE operand of that select;
  * the TRUE operand's backward closure contains the WorldToObject getter, the
    module's own hit position and constants -- and NO access chain on member
    56 at all.

`100`'s own `dev/verify_carglint.py` REJECTS these rungs at its axis 7 for the
first of those reasons, which is an independent implementation saying the same
thing.

MODES
-----
  glint  THE FEATURE. One query per preamble execution; the cell feed replaced.
  cell   the CRAWL FALSIFIER, analogous to `100`'s `carglint-cell`: the feature
         PLUS a second, PRIMARY-ray query whose committed WorldToObject puts
         the primary hit into object space, hashed to one of eight flat hues
         and painted at every radiance write. On a MOVING car the hues must
         ride WITH the paint; `carglint-cell` (world) is the comparison.
  miss   the feature PLUS a magenta paint wherever the bounce query RAN and
         committed nothing, so the fallback rate can be read off a frame.
  ctl    emits NOTHING and rewrites nothing: byte-identical to the base.

NOTHING ELSE MOVES. cell size, nu0, theta_bin, glint_max, k_glint, the gate
ramp, the fade, the firefly clamp, the PCG, the angular bin and all six GGX
rewrites are the base's own bytes, untouched. This is one variable.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glint_model as GM
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
# One derivation of member 56 and of the primary reconstruction in the repo,
# not four: `98`'s finders are IMPORTED and are not modified here.
from patch_rayq import (_find_world_offset, _find_primary_ray, _entry,
                        _func_span, _assert_payload_float3, TRACE_RE,
                        COMMIT_FLAGS, COMMITTED, _add_header)
# `100`'s emitters, imported for --mode cell so the diagnostic's ladder and
# hash are the SAME arithmetic the feature uses, not a paraphrase of it.
from patch_carglint import Emitter, emit_cells, emit_pcg, _ensure
from patch_ms_ggx import find_ggx_blocks, count_sg_sites

RAY_FLAGS, RAY_FLAG_NAMES = COMMIT_FLAGS['first']      # 517
T_LO, T_HI, T_EPS = 0.999, 1.001, 1.0e-4               # `98` sec 2.4's bracket
MAGENTA = (3.00, 0.20, 3.00)                           # `98`'s palette entry 6
PALETTE8 = [(3.00, 0.20, 0.20), (3.00, 1.20, 0.20), (3.00, 3.00, 0.20),
            (0.20, 3.00, 0.20), (0.20, 3.00, 3.00), (0.20, 0.60, 3.00),
            (3.00, 0.20, 3.00), (2.40, 2.40, 2.40)]
MODES = ('glint', 'cell', 'miss', 'ctl')
DECOYS = ('world', 'noselect', 'primary', 'nofallback', 'flags')


def _d(mod, tok):
    _, s = mod.find_def(tok)
    return s or ''


def _line(mod, tok):
    i, _ = mod.find_def(tok)
    return i


def _m(mod, tok, pat):
    return re.match(pat, _d(mod, tok))


def _fval(mod, tok):
    m = re.match(r'OpConstant %float (\S+)\s*$', _d(mod, tok))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _uval(mod, tok):
    m = re.match(r'OpConstant %uint (\d+)\s*$', _d(mod, tok))
    return int(m.group(1)) if m else None


def _uses(mod, tok, skip_line=None):
    """Every line that REFERENCES tok and is not its own definition."""
    pat = re.compile(r'(?<![%\w])' + re.escape(tok) + r'(?![\w])')
    isdef = re.compile(r'^\s*' + re.escape(tok) + r'\s*=')
    out = []
    for i, ln in enumerate(mod.lines):
        if i == skip_line or isdef.match(ln):
            continue
        if pat.search(ln):
            out.append(i)
    return out


# --------------------------------------------------------------- detection
def find_glint_chain(mod, fs, fe):
    """Locate `100`'s SHIPPED cell chain in the base bytes -- structurally.

    The anchor is the dyadic LOD ladder, which nothing else in a 15 000-line
    raygen has: NClamp(_, 1.0, 65536) -> Log2 -> Ceil -> Exp2 -> * cell. From
    its `s` the three cell axes are reached as the only `OpFDiv _ %s`, and each
    of those must be `OpFAdd(cb[M][k], P[k]) / s` -- `100` sec 2.2's own shape,
    read back out of the bytes rather than assumed. Dies unless there is
    exactly ONE such chain and exactly THREE axes.
    """
    found = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        s, a, b = m.groups()
        for cell_c, ex in ((a, b), (b, a)):
            cv = _fval(mod, cell_c)
            if cv is None or not (0.0 < cv < 1.0):
                continue
            me = _m(mod, ex, r'OpExtInst %float %\w+ Exp2 (%\w+)\s*$')
            if not me:
                continue
            mc = _m(mod, me.group(1), r'OpExtInst %float %\w+ Ceil (%\w+)\s*$')
            if not mc:
                continue
            ml = _m(mod, mc.group(1), r'OpExtInst %float %\w+ Log2 (%\w+)\s*$')
            if not ml:
                continue
            mn = _m(mod, ml.group(1),
                    r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
            if not mn:
                continue
            if _fval(mod, mn.group(2)) != 1.0 or \
                    _fval(mod, mn.group(3)) != float(GM.RATIO_MAX):
                continue
            found.append(dict(s=s, s_line=i, cell=cv, ratio=mn.group(1),
                              ladder=[mn.group(1), ml.group(1), mc.group(1),
                                      me.group(1), ex]))
    if len(found) != 1:
        die(f"{mod.name}: expected exactly ONE carglint LOD ladder "
            f"(NClamp(_,1,{float(GM.RATIO_MAX)}) -> Log2 -> Ceil -> Exp2 -> *cell), "
            f"found {len(found)} -- is this base really a glint rung?")
    g = found[0]
    s = g['s']

    # s2 = s*s, the unique square of s (k_den = NU0 * s2)
    sq = [m.group(1) for ln in mod.lines
          for m in [re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(s)
                             + r' ' + re.escape(s) + r'\s*$', ln)] if m]
    if len(sq) != 1:
        die(f"{mod.name}: {len(sq)} squares of the cell size {s}, want exactly 1")
    g['s2'] = sq[0]
    g['s2_line'] = _line(mod, sq[0])

    # the three cell axes
    divs = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpFDiv %float (%\w+) ' + re.escape(s) + r'\s*$', ln)
        if m:
            divs.append((i, m.group(1), m.group(2)))
    if len(divs) != 3:
        die(f"{mod.name}: {len(divs)} cell divides by {s}, want exactly 3")
    axes = []
    cbvs, mems = set(), set()
    for div_line, q, num in divs:
        ma = _m(mod, num, r'OpFAdd %float (%\w+) (%\w+)\s*$')
        if not ma:
            die(f"{mod.name}: cell numerator {num} is '{_d(mod, num)}', not the "
                f"base's OpFAdd(cb56_k, P_k) -- this base is not `100`'s glint "
                f"rung, or something already replaced the feed")
        off, pos = ma.groups()
        me = _m(mod, off, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not me:
            off, pos = pos, off
            me = _m(mod, off, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not me:
            die(f"{mod.name}: neither operand of {num} is a component of a "
                f"constant-buffer load")
        k = int(me.group(2))
        ml = _m(mod, me.group(1), r'OpLoad %v4float (%\w+)\s*$')
        mac = _m(mod, ml.group(1),
                 r'OpAccessChain %\w+ (%\w+) (%\w+) (%\w+)\s*$') if ml else None
        if not mac or _uval(mod, mac.group(2)) != 0:
            die(f"{mod.name}: the offset for cell axis {k} is not "
                f"cbv[0][member].{k}")
        cbvs.add(mac.group(1))
        mems.add(_uval(mod, mac.group(3)))
        # downstream: the divide must reach the documented totality guard and
        # the axis-k hash multiplier, so an axis cannot be silently swapped.
        gu = [j for j in _uses(mod, q) if 'NClamp' in mod.lines[j]]
        if len(gu) != 1:
            die(f"{mod.name}: cell axis {k}'s divide has {len(gu)} NClamp "
                f"consumers, want exactly 1")
        clamp = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NClamp (%\w+) '
                         r'(%\w+) (%\w+)\s*$', mod.lines[gu[0]])
        if not clamp or abs(_fval(mod, clamp.group(4)) or 0.0) != \
                float(GM.CELL_MAX):
            die(f"{mod.name}: cell axis {k} has no +-{float(GM.CELL_MAX)} "
                f"totality guard")
        cur = clamp.group(1)
        for label, op in (('Floor', r'OpExtInst %float %\w+ Floor '),
                          ('ConvertFToS', r'OpConvertFToS %\w+ '),
                          ('Bitcast', r'OpBitcast %uint ')):
            nxt = [m2.group(1) for ln2 in mod.lines
                   for m2 in [re.match(r'\s*(%\w+) = ' + op
                                       + re.escape(cur) + r'\s*$', ln2)] if m2]
            if len(nxt) != 1:
                die(f"{mod.name}: cell axis {k}: {len(nxt)} {label} consumers "
                    f"of {cur}, want exactly 1")
            cur = nxt[0]
        mulc = None
        for j in _uses(mod, cur):
            m2 = re.match(r'\s*%\w+ = OpIMul %uint ' + re.escape(cur)
                          + r' (%\w+)\s*$', mod.lines[j])
            if m2:
                mulc = _uval(mod, m2.group(1))
        if mulc != int(GM.C_CELL[k]):
            die(f"{mod.name}: cell axis {k} is folded with {mulc}, not the "
                f"model's {int(GM.C_CELL[k])} -- the axes are permuted")
        axes.append(dict(k=k, div_line=div_line, div=q, world=num,
                         world_line=_line(mod, num), offset=off, pos=pos,
                         extract=me.group(1)))
    if sorted(a['k'] for a in axes) != [0, 1, 2]:
        die(f"{mod.name}: cell axes are {[a['k'] for a in axes]}, want 0,1,2")
    if len(cbvs) != 1 or len(mems) != 1:
        die(f"{mod.name}: the three cell axes read {len(cbvs)} CBVs / "
            f"{len(mems)} members")
    axes.sort(key=lambda a: a['k'])
    g['axes'] = axes
    g['cbv'] = cbvs.pop()
    g['member'] = mems.pop()
    g['position'] = [a['pos'] for a in axes]

    # dist -> t_primary + t_segment, off the ladder's own ratio
    mr = _m(mod, g['ratio'], r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mr:
        die(f"{mod.name}: the ladder ratio {g['ratio']} is not r_fp * (1/cell)")
    rfp = mr.group(1) if _fval(mod, mr.group(2)) is not None else mr.group(2)
    mf = _m(mod, rfp, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mf:
        die(f"{mod.name}: the footprint radius {rfp} is not dist * pix_angle")
    dist = mf.group(1) if _fval(mod, mf.group(2)) is not None else mf.group(2)
    md = _m(mod, dist, r'OpFAdd %float (%\w+) (%\w+)\s*$')
    if not md:
        die(f"{mod.name}: dist {dist} is not t_primary + t_segment")
    def _is_tprim(tok):
        mm = _m(mod, tok, r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mm:
            return False
        return any(re.match(r'OpExtInst %float %\w+ InverseSqrt ', _d(mod, x))
                   for x in mm.groups())
    a, b = md.groups()
    cands = [x for x in (a, b) if _is_tprim(x)]
    if len(cands) != 1:
        die(f"{mod.name}: {len(cands)} of dist's two operands look like "
            f"t_primary = dot*rsqrt, want exactly 1")
    tprim = cands[0]
    tseg = b if tprim == a else a
    g['dist'], g['t_primary'], g['t_segment'] = dist, tprim, tseg
    return g


def find_trace(mod, fs, fe, tseg):
    """The module's own first OpTraceRayKHR, and the assertion that `tseg` is
    the word-3 load IT filled -- so the bracket cannot be built around some
    other segment's distance."""
    tl = next((i for i in range(fs, fe) if TRACE_RE.match(mod.lines[i])), None)
    if tl is None:
        die(f"{mod.name}: no OpTraceRayKHR in the raygen entry function")
    ops = TRACE_RE.match(mod.lines[tl]).groups()[1].split()
    if len(ops) != 11:
        die(f"{mod.name}: the trace at line {tl+1} has {len(ops)} operands, "
            f"want 11")
    accel, cullmask, origin, direction, payload = \
        ops[0], ops[2], ops[6], ops[8], ops[10]
    _assert_payload_float3(mod, payload)
    ml = _m(mod, tseg, r'OpLoad %float (%\w+)\s*$')
    if not ml:
        die(f"{mod.name}: t_segment {tseg} is not an OpLoad")
    if not re.match(r'OpInBoundsAccessChain %_ptr_RayPayloadKHR_float '
                    + re.escape(payload) + r' %uint_3\s*$', _d(mod, ml.group(1))):
        die(f"{mod.name}: t_segment {tseg} does not load word 3 of the trace's "
            f"own payload {payload}")
    if _line(mod, tseg) < tl:
        die(f"{mod.name}: t_segment is defined above the trace")
    return dict(line=tl, accel=accel, cullmask=cullmask, origin=origin,
                direction=direction, payload=payload,
                operands=' '.join(ops))


# ---------------------------------------------------------------- emission
def _matrix_type(mod, consts):
    if not any(re.match(r'\s*%v3float\s*=\s*OpTypeVector %float 3\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no %v3float to build OpTypeMatrix %v3float 4 on")
    return _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeMatrix %v3float 4\s*$',
                   lambda n: f"    {n} = OpTypeMatrix %v3float 4")


def emit_query(E, rq, accel, flags, cullmask, origin, direction, t, f_lo, f_hi,
               f_eps, boolt, u0, u1):
    """`98` sec 2's bracketed re-traversal. Straight line, no control flow."""
    tlo = E.op('OpFMul', '%float', t, f_lo)
    th0 = E.op('OpFMul', '%float', t, f_hi)
    thi = E.op('OpFAdd', '%float', th0, f_eps)
    E.ins.append(f"{E.ind}OpRayQueryInitializeKHR {rq} {accel} {flags} "
                 f"{cullmask} {origin} {tlo} {direction} {thi}")
    proceed = E.op('OpRayQueryProceedKHR', boolt, rq)
    ityp = E.op('OpRayQueryGetIntersectionTypeKHR', '%uint', rq, u1)
    comm = E.op('OpINotEqual', boolt, ityp, u0)
    return dict(tmin=tlo, tmax=thi, proceed=proceed, type=ityp, committed=comm)


def emit_to_object(E, rq, mat_t, u1, pos):
    """P_o = WorldToObject * (P, 1), the 3x4 affine as four v3 columns.

    The point handed in is the module's own CAMERA-RELATIVE hit position. That
    is the space the TLAS is built in (`98` sec 15), which is exactly the space
    this matrix inverts, so member 56 must NOT be added first.
    """
    W = E.op('OpRayQueryGetIntersectionWorldToObjectKHR', mat_t, rq, u1)
    col = [E.op('OpCompositeExtract', '%v3float', W, str(k)) for k in range(4)]
    m = [E.op('OpVectorTimesScalar', '%v3float', col[k], pos[k])
         for k in range(3)]
    a0 = E.op('OpFAdd', '%v3float', m[0], m[1])
    a1 = E.op('OpFAdd', '%v3float', a0, m[2])
    po = E.op('OpFAdd', '%v3float', a1, col[3])
    comps = [E.op('OpCompositeExtract', '%float', po, str(k)) for k in range(3)]
    return dict(matrix=W, matrix_type=mat_t, columns=col, scaled=m,
                point=po, components=comps)


def build(mod, mode, decoy=None):
    consts, edits = [], []
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)

    # ---- detectors FIRST, before anything rewrites mod.lines (GOTCHAS 12) --
    # `94` sec 3.4 / `100` sec 4 gate 1b: two of the twelve reference
    # permutations are SCALAR-SPECULAR (p*Vis*D, no F0 in the lobe), carry no
    # GGX block and therefore no glint splice in the base. They are declined BY
    # NAME and counted, never silently skipped (GOTCHAS: a module count that
    # differs from the ladder's is a finding).
    blocks = find_ggx_blocks(mod)
    sg = count_sg_sites(mod)
    if sg and not blocks:
        return None, None, dict(mode=mode, decoy=decoy, written=False,
                                sg_sites=sg, ggx_blocks=0,
                                variant='scalar-specular (no F0 in lobe) '
                                        '-- declined by name')
    if len(blocks) != 6:
        die(f"{mod.name}: {len(blocks)} GGX blocks, want 6")
    chain = find_glint_chain(mod, fs, fe)
    trace = find_trace(mod, fs, fe, chain['t_segment'])
    prim = _find_primary_ray(mod, fs, fe)
    # `98`'s independent derivation of the SAME anchor. Two implementations
    # that must agree, the discipline of `98` sec 14.6a.
    woff = _find_world_offset(mod, fs, fe)
    if woff['member'] != chain['member'] or woff['cbv'] != chain['cbv']:
        die(f"{mod.name}: the shipped cell feed reads cb[{chain['cbv']}]"
            f"[{chain['member']}] but `98`'s finder derives "
            f"cb[{woff['cbv']}][{woff['member']}]")
    if list(woff['position']) != list(chain['position']):
        die(f"{mod.name}: the cell feed's hit position {chain['position']} is "
            f"not the trace-origin position {woff['position']}")

    rep = dict(mode=mode, decoy=decoy, sg_sites=sg, ggx_blocks=len(blocks),
               cell=chain['cell'],
               member=chain['member'], cbv=chain['cbv'],
               position=chain['position'], s=chain['s'], s2=chain['s2'],
               t_primary=chain['t_primary'], t_segment=chain['t_segment'],
               trace_line=trace['line'] + 1, trace_operands=trace['operands'],
               accel=trace['accel'], cullmask=trace['cullmask'],
               ray_flags=RAY_FLAGS, ray_flags_names=RAY_FLAG_NAMES,
               bracket=[T_LO, T_HI, T_EPS],
               axes=[dict(k=a['k'], world=a['world'], pos=a['pos'],
                          div=a['div']) for a in chain['axes']])

    if mode == 'ctl':
        rep['written'] = True
        rep['emitted'] = 0
        rep['note'] = 'the CONTROL: no constants, no instructions, no rewrite'
        return [], [], rep

    # placement: everything the query consumes must be defined above the splice
    at = chain['s2_line']
    for tok in (trace['accel'], trace['cullmask'], trace['origin'],
                trace['direction'], chain['t_segment']) + tuple(chain['position']):
        ln = _line(mod, tok)
        if ln is None or ln >= at:
            die(f"{mod.name}: {tok} is defined at line "
                f"{'?' if ln is None else ln+1}, not above the splice point "
                f"(line {at+1})")
    if not re.match(r'\s*%\w+ = Op', mod.lines[at]):
        die(f"{mod.name}: line {at+1} is not an ordinary instruction")

    boolt = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                    lambda n: f"    {n} = OpTypeBool")
    int_t = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeInt 32 1\s*$',
                    lambda n: f"    {n} = OpTypeInt 32 1")
    rqt = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                  lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure(mod, consts,
                     r'\s*(%\w+)\s*=\s*OpTypePointer Function '
                     + re.escape(rqt) + r'\s*$',
                     lambda n: f"    {n} = OpTypePointer Function {rqt}")
    mat_t = _matrix_type(mod, consts)
    # SkipAABBs (0x200) is illegal without this, and it is not ours to add.
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability")

    K = Emitter(mod, consts)          # constant-interning helper only
    u0, u1 = K.U(0), K.U(1)
    u_flags = K.U(0 if decoy == 'flags' else RAY_FLAGS)
    f_lo, f_hi, f_eps = K.C(T_LO), K.C(T_HI), K.C(T_EPS)
    if K.ins:
        die(f"{mod.name}: the constant helper emitted instructions")

    # ---- the ray query variable(s), leading instructions of the entry block
    lab = next(i for i in range(fs, fe)
               if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    vat = lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[vat + 1]):
        vat += 1
    ind = re.match(r'(\s*)', mod.lines[vat]).group(1)
    rq = mod.new_id()
    head = [f"{ind}{rq} = OpVariable {ptr_rq} Function"]
    rq2 = None
    if mode == 'cell':
        rq2 = mod.new_id()
        head.append(f"{ind}{rq2} = OpVariable {ptr_rq} Function")

    # ---- the query + the object-space point, above the first cell divide ---
    E = Emitter(mod, consts)
    E.ind = re.match(r'(\s*)', mod.lines[at]).group(1)
    q = emit_query(E, rq, trace['accel'], u_flags, trace['cullmask'],
                   trace['origin'], trace['direction'], chain['t_segment'],
                   f_lo, f_hi, f_eps, boolt, u0, u1)
    if decoy == 'primary':
        # Deliberately WRONG: transform the hit point by the matrix of the
        # PRIMARY surface instead of the shading surface. Never installed.
        obj = emit_to_object(E, rq, mat_t, u1, list(prim['P']))
    elif decoy == 'world':
        # Deliberately WRONG: transform the WORLD point (P + cb56) instead of
        # the camera-relative one -- the camera offset counted TWICE, because
        # `98` sec 15 proved the TLAS is already camera-relative. Never
        # installed.
        #
        # It re-emits its own `cb[member].xyz + P` here rather than reusing the
        # base's adds: those are defined BELOW the splice point (the ladder
        # comes first, the world adds sit between it and the divides), so
        # reusing them by id produced a forward reference and spirv-val threw
        # "ID has not been defined" on all ten permutations. A decoy that
        # cannot assemble proves nothing.
        woff = _offset_triple(E, mod, chain, u0)
        wpos = [E.op('OpFAdd', '%float', woff[k], chain['position'][k])
                for k in range(3)]
        obj = emit_to_object(E, rq, mat_t, u1, wpos)
    else:
        obj = emit_to_object(E, rq, mat_t, u1, list(chain['position']))
    rep['query'] = dict(var=rq, line=at + 1, count=len(E.ins), **q)
    rep['object'] = {k: v for k, v in obj.items() if k != 'matrix_type'}

    # ---- one select per axis, and the FDiv repointed ----------------------
    sels = []
    for a in chain['axes']:
        S = Emitter(mod, consts)
        S.ind = re.match(r'(\s*)', mod.lines[a['world_line']]).group(1)
        if decoy == 'nofallback':
            # Deliberately WRONG: no select at all, so a missed query hashes
            # whatever the getter returned. Never installed.
            sel = obj['components'][a['k']]
        elif decoy == 'noselect':
            sel = a['world']
        else:
            sel = S.op('OpSelect', '%float', q['committed'],
                       obj['components'][a['k']], a['world'])
        if S.ins:
            edits.append((a['world_line'], S.ins))
        old = mod.lines[a['div_line']]
        new = re.sub(r'(= OpFDiv %float )' + re.escape(a['world'])
                     + r'(?![\w])', r'\g<1>' + sel, old)
        if new == old and sel != a['world']:
            die(f"{mod.name}: could not repoint cell axis {a['k']}'s divide")
        mod.lines[a['div_line']] = new
        sels.append(dict(k=a['k'], select=sel, world=a['world'],
                         obj=obj['components'][a['k']]))
    rep['selects'] = sels

    # ---- optional paints ---------------------------------------------------
    if mode in ('cell', 'miss'):
        # The latch is emitted into the SAME instruction run as the query, so
        # it cannot be reordered above the `committed` bool it reads. Two edits
        # at one line index would be sorted stably and inserted in the WRONG
        # order (apply_edits inserts each at pos+1), which is exactly how this
        # failed the first time it was built.
        _paint(mod, consts, edits, E, eline, fs, fe, mode, chain, prim, trace,
               rq2, q, mat_t, boolt, int_t, u0, u1, u_flags, f_lo, f_hi, f_eps,
               rep, decoy)
    edits.append((at, E.ins))
    edits.append((vat, head))
    rep['emitted'] = sum(len(i) for _p, i in edits)
    rep['written'] = True
    return consts, edits, rep


def _paint(mod, consts, edits, L, eline, fs, fe, mode, chain, prim, trace, rq2,
           q, mat_t, boolt, int_t, u0, u1, u_flags, f_lo, f_hi, f_eps, rep,
           decoy):
    """The two diagnostic rungs' radiance paint, `98` sec 2's latch shape.

    A Private uint is stored 0 in the entry block and written first-write-wins
    at the splice, so what reaches the paint is the FIRST path segment of the
    invocation -- deterministic per pixel, not a stochastic average.
    """
    writes = find_image_writes(mod)
    ptr_priv_u = _ensure(mod, consts,
                         r'\s*(%\w+)\s*=\s*OpTypePointer Private %uint\s*$',
                         lambda n: f"    {n} = OpTypePointer Private %uint")
    var = mod.new_id()
    consts.append(f"    {var} = OpVariable {ptr_priv_u} Private")
    mod.lines[eline] = mod.lines[eline].rstrip() + f' {var}'
    lab = next(i for i in range(fs, fe)
               if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    zat = lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[zat + 1]):
        zat += 1
    ind = re.match(r'(\s*)', mod.lines[zat]).group(1)
    edits.append((zat, [f"{ind}OpStore {var} {u0}"]))

    C = GM.constants(GM.knobs(cell=chain['cell']))
    at = chain['s2_line']
    n0 = len(L.ins)

    if mode == 'miss':
        # 0 never ran, 1 ran and committed nothing, 2 ran and hit.
        u2 = L.U(2)
        old = L.op('OpLoad', '%uint', var)
        first = L.op('OpIEqual', boolt, old, u0)
        nst = L.op('OpSelect', '%uint', q['committed'], u2, u1)
        wst = L.op('OpSelect', '%uint', first, nst, old)
        L.ins.append(f"{L.ind}OpStore {var} {wst}")
        nbuckets = 0
        rep['latch'] = dict(var=var, states=3, count=len(L.ins) - n0)
    else:
        # a SECOND query, down `98` sec 2.1's primary family: origin = the zero
        # triple (the camera IS the origin of this space), direction = the
        # module's own normalized view ray, bracket around |P|.
        for tok in list(prim['P']) + list(prim['V']) + [prim['dot'], prim['rsqrt']]:
            if _line(mod, tok) >= at:
                die(f"{mod.name}: the primary reconstruction id {tok} is not "
                    f"above the splice point")
        f0 = L.C(0.0)
        v3zero = _ensure(
            mod, consts,
            r'\s*(%\w+)\s*=\s*OpConstantComposite %v3float ' + re.escape(f0)
            + r' ' + re.escape(f0) + r' ' + re.escape(f0) + r'\s*$',
            lambda n: f"    {n} = OpConstantComposite %v3float {f0} {f0} {f0}")
        tp = L.op('OpFMul', '%float', prim['dot'], prim['rsqrt'])
        pdir = L.op('OpCompositeConstruct', '%v3float',
                    prim['V'][0], prim['V'][1], prim['V'][2])
        q2 = emit_query(L, rq2, trace['accel'], u_flags, trace['cullmask'],
                        v3zero, pdir, tp, f_lo, f_hi, f_eps, boolt, u0, u1)
        o2 = emit_to_object(L, rq2, mat_t, u1, list(prim['P']))
        # the same graceful fallback: on a miss (the sky), the WORLD cell.
        off = _offset_triple(L, mod, chain, u0)
        pw = [L.op('OpFAdd', '%float', off[k], prim['P'][k]) for k in range(3)]
        src = [L.op('OpSelect', '%float', q2['committed'],
                    o2['components'][k], pw[k]) for k in range(3)]
        rfp = L.op('OpFMul', '%float', tp, L.C(C['PIX']))
        # emit_cells with no offset: the point is ALREADY in the space we want
        # to hash, so the `nooffset` path is the correct one here (in `100` it
        # is the camrel DECOY, because there the point was camera-relative).
        _s, _s2, seed, cid = emit_cells(L, C, int_t, src, [None] * 3, rfp,
                                        C['CELL'], decoy='nooffset')
        out = emit_pcg(L, seed)
        L.ins.append(f"{L.ind}OpStore {var} {out}")
        nbuckets = 8
        rep['latch'] = dict(var=var, states='hash', count=len(L.ins) - n0,
                            query2=dict(var=rq2, **q2), object2=
                            {k: v for k, v in o2.items() if k != 'matrix_type'},
                            world=pw, feed=src, seed=seed, hash=out,
                            cell_int=cid['cell_int'])

    # the paint itself
    one = L.C(1.0)
    if nbuckets:
        u7 = L.U(7)
        ubk = [L.U(k) for k in range(8)]
        hue = [[L.C(v) for v in rgb] for rgb in PALETTE8]
    else:
        mag = [L.C(v) for v in MAGENTA]
    painted, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1,
                            'why': 'texel not a v4float construct'})
            continue
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({'line': w['line'] + 1, 'why': 'constant-zero'})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({'line': w['line'] + 1, 'why': 'scalar-broadcast'})
            continue
        W = Emitter(mod, consts)
        W.ind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        lv = W.op('OpLoad', '%uint', var)
        if nbuckets:
            h3 = W.op('OpBitwiseAnd', '%uint', lv, u7)
            gates = [(W.op('OpIEqual', boolt, h3, ubk[k]), hue[k])
                     for k in range(8)]
        else:
            gates = [(W.op('OpIEqual', boolt, lv, u1), mag)]
        newc = []
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                cur = W.op('OpSelect', '%float', g, rgb[ch], cur)
            newc.append(W.op('OpFMul', '%float', c[ch], cur))
        nt = W.op('OpCompositeConstruct', '%v4float',
                  newc[0], newc[1], newc[2], c[3])
        edits.append((w['line'] - 1, W.ins))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        painted.append(w['line'] + 1)
    if not painted:
        die(f"{mod.name}: no radiance write to paint at")
    rep['painted'] = painted
    rep['skipped'] = skipped
    rep['palette'] = ('cell8' if nbuckets else 'magenta-on-miss')


def _ptr_of(mod, chain):
    """The pointer type of the base's own member-56 access chain, reused so the
    diagnostic's fresh chain is the same shape as the shipped one."""
    for a in chain['axes']:
        ml = _m(mod, a['extract'], r'OpLoad %v4float (%\w+)\s*$')
        if ml:
            mac = _m(mod, ml.group(1), r'OpAccessChain (%\w+) ')
            if mac:
                return mac.group(1)
    die(f"{mod.name}: could not read the world offset's pointer type")


def _offset_triple(E, mod, chain, u0):
    ac = E.op('OpAccessChain', _ptr_of(mod, chain), chain['cbv'], u0,
              E.U(chain['member']))
    lo = E.op('OpLoad', '%v4float', ac)
    return [E.op('OpCompositeExtract', '%float', lo, str(k)) for k in range(3)]


# ------------------------------------------------------------------ driver
def process(path, outdir, mode, do_rt=True, decoy=None, report_only=False):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, r = build(mod, mode, decoy)
    rep['glintobj'] = r
    if consts is None:
        rep['written'] = False
        return rep
    if report_only:
        rep['written'] = False
        return rep
    apply_edits(mod, consts, edits)
    _add_header(mod)
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    a = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if a.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{a.stderr}")
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
    rep['written'] = True
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--mode', default='glint', choices=MODES)
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--decoy', choices=DECOYS, default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_glintobj.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    reps = [process(p, a.outdir, a.mode, do_rt=not a.no_roundtrip_check,
                    decoy=a.decoy, report_only=a.report)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
