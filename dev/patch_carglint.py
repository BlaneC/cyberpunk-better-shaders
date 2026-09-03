#!/usr/bin/env python3
"""carglint -- `94` sec 4.4's metallic-flake GLINTS, spliced into the six GGX
specular lobes of `rgs_reference_main` (site A of `94` sec 2.3).

handoff/100-GLINTS.md is the document. Read its sec 0 and its pre-registered
table BEFORE looking at a frame; read `94` sec 2.1 before expecting to SEE
anything, because this site does not shade the primary hit.

    python3 dev/patch_carglint.py <mod.spvasm> --outdir DIR [--mode glint|cell]
                                  [--k-glint 1.0] [--nu0 1.5e5] [--cell 0.008]
                                  [--report] [--decoy ...]

WHAT IS SPLICED, and where
--------------------------
`28`'s Schlick spherical-gaussian anchor finds the six `F*Vis*D` blocks
(dev/patch_ms_ggx.find_ggx_blocks, reused unmodified). Each block's three
`spec_c` results are multiplied by one scalar `glint`, and every downstream use
is redirected -- exactly `28`'s `emit_comp` shape, for exactly `28`'s reason:
the definition is left alone so the rewrite is provably total.

`glint = mix(1, g, kw)` with `E[g] = 1` EXACTLY, so this is a redistribution of
the base metal's energy across the pixel footprint, not new energy (`94`
sec 4.3). It multiplies the FLAKE/BASE lobe, not a coat: `94` sec 17 kills the
dielectric arm on physics and the coat is not built here.

--k-glint 0 emits NOTHING -- no constants, no instructions, no rewrite -- so
the control rung is BYTE-IDENTICAL to the base (`94` sec 6.1; `27` sec 8.3 is
the cautionary tale about 48 bytes of unconsumed OpConstant).

THE FIVE INPUTS sec 4.4 ASKS FOR, and what is actually available
----------------------------------------------------------------
  P_w        AVAILABLE.  The module's own trace-origin hit position plus
             cbv[..][56].xyz, the member located STRUCTURALLY by
             patch_rayq._find_world_offset (imported, not copied, not edited).
             `98` sec 15 proved that member on screen.
  H          AVAILABLE.  Per block, from the OpDot that feeds NoH inside the
             block's own D chain: of the dot's two v3 constructs, the one that
             is NOT the shading normal. Unit length, world-frame (a direction
             is unaffected by the camera translation), which is the property
             sec 4.4 wants -- a glint must move with the LIGHT, not the camera.
  D          AVAILABLE.  patch_ms_ggx._read_vis already returns it.
  t_segment  AVAILABLE.  The OpLoad of payload word 3 that the module's own
             path-loop trace fills -- the same word `94` sec 2.2 measured.
  t_primary  AVAILABLE.  |P| = dot(P,P) * rsqrt(dot(P,P)) off the module's own
             primary reconstruction (patch_rayq._find_primary_ray), one FMul.
  pix_angle  NOT AVAILABLE -- a BUILD CONSTANT. See dev/glint_model.py.

MODES
-----
  glint  the feature.
  cell   `94` sec 6.3 step 4's `-glintcell` diagnostic: no glint at all; the
         PRIMARY hit's world cell hash is painted as one of eight flat hues at
         every radiance write, so a camera translation either leaves the cells
         welded to the geometry (the world offset is right) or makes them crawl
         (it is wrong). This is the only rung of the family that CAN be read on
         a still, and it is the one that can falsify the whole splice.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glint_model as GM
from patch_skin_brdf import (apply_edits, roundtrip_check, replace_all_uses,
                             f32, f32s, die)
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
from patch_ms_ggx import find_ggx_blocks, count_sg_sites
# The world offset and the primary reconstruction are `98`'s, re-used by
# IMPORT so there is one derivation of member 56 in the repo, not two.
from patch_rayq import (_find_world_offset, _find_primary_ray, _entry,
                        _func_span, TRACE_RE, PALETTE)

F_MET_SCALE = '%float_0_00392156886'      # 1/255
F_R_FLOOR = '%float_0_0399999991'         # the authored-roughness floor


def _fdef(mod, tok):
    _, d = mod.find_def(tok)
    return d or ''


def _fline(mod, tok):
    i, _ = mod.find_def(tok)
    return i


# ------------------------------------------------------------- detection
def _payload_byte3(mod, payload, word, want_clamp):
    """The module's own `byte3(payload[word]) * 1/255`, then a clamp.

    word 0 -> METALLIC, clamped NClamp(_, 0, 1)          (`94` sec 3.2's %1314)
    word 1 -> ROUGHNESS, clamped NMin(NMax(_, .04), 1)   (`94` sec 3.2's %697,
              the AUTHORED value, before ptreg's regularisation -- the alpha at
              the block is regularised and sec 3.2 says do not gate on it)

    Anchored on the payload id of the module's own first OpTraceRayKHR, so no
    positional guess is possible (GOTCHAS 10). Dies unless exactly one matches.
    """
    ac = None
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpInBoundsAccessChain %_ptr_RayPayloadKHR_uint '
                     + re.escape(payload) + r' %uint_' + str(word) + r'\s*$', ln)
        if m:
            if ac is not None:
                die(f"{mod.name}: two access chains onto payload word {word}")
            ac = m.group(1)
    if ac is None:
        die(f"{mod.name}: no access chain onto payload word {word} of {payload}")
    loads = [m.group(1) for ln in mod.lines
             for m in [re.match(r'\s*(%\w+) = OpLoad %uint ' + re.escape(ac) + r'\s*$', ln)]
             if m]
    hits = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) ' + re.escape(F_MET_SCALE) + r'\s*$', ln)
        if not m:
            continue
        cv = re.match(r'OpConvertUToF %float (%\w+)\s*$', _fdef(mod, m.group(2)))
        if not cv:
            continue
        sh = re.match(r'OpShiftRightLogical %uint (%\w+) %uint_24\s*$',
                      _fdef(mod, cv.group(1)))
        if not sh or sh.group(1) not in loads:
            continue
        hits.append(m.group(1))
    if len(hits) != 1:
        die(f"{mod.name}: expected exactly ONE byte3(payload[{word}])/255, "
            f"found {len(hits)}")
    scaled = hits[0]
    out = []
    for i, ln in enumerate(mod.lines):
        if want_clamp == 'nclamp':
            m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NClamp '
                         + re.escape(scaled) + r' %float_0 %float_1\s*$', ln)
            if m:
                out.append(m.group(1))
        else:
            m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NMax '
                         + re.escape(scaled) + r' ' + re.escape(F_R_FLOOR) + r'\s*$', ln)
            if not m:
                continue
            for j, l2 in enumerate(mod.lines):
                m2 = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ NMin '
                              + re.escape(m.group(1)) + r' %float_1\s*$', l2)
                if m2:
                    out.append(m2.group(1))
    if len(out) != 1:
        die(f"{mod.name}: expected exactly ONE clamp of byte3(payload[{word}]), "
            f"found {len(out)}")
    return out[0], scaled


def _f0_chain_metallic(mod, blocks):
    """`94` sec 3.4's site-local recovery, used as an INDEPENDENT second
    reading of metallic: F0_c = OpFAdd(OpFMul(m, OpFAdd(base_c, -0.04)), 0.04).

    Returns the single id all 18 (3 channels x 6 blocks) agree on, or dies.
    """
    got = set()
    n = 0
    for b in blocks:
        for s in b['spec']:
            d = _fdef(mod, s['f0'])
            m = re.match(r'OpFAdd %float (%\w+) ' + re.escape(F_R_FLOOR) + r'\s*$', d)
            if not m:
                die(f"{mod.name}: F0 {s['f0']} is '{d}', not (x + 0.04)")
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, m.group(1)))
            if not mm:
                die(f"{mod.name}: F0 {s['f0']}'s addend is not a product")
            a, bb = mm.groups()
            pick = None
            for u, v in ((a, bb), (bb, a)):
                if re.match(r'OpFAdd %float %\w+ %float_n0_0399999991\s*$',
                            _fdef(mod, v)):
                    pick = u
            if pick is None:
                die(f"{mod.name}: neither operand of F0 {s['f0']}'s product has "
                    f"a (base - 0.04) sibling")
            got.add(pick)
            n += 1
    if len(got) != 1:
        die(f"{mod.name}: the F0 chains disagree on metallic: {sorted(got)}")
    return got.pop(), n


def _read_H(mod, blk):
    """The block's own half vector, from the OpDot that feeds NoH.

    D = alpha^2 / (pi * (NoH^2*(alpha^2-1) + 1)^2). Walk that denominator down
    to the NClamp'd NoH, take its OpDot, and of the dot's two v3 constructs
    return the one that is NOT the shading normal -- the normal is the triple
    the block's OTHER dots (NoV, NoL) also use, so it identifies itself.
    """
    md = re.match(r'OpFDiv %float (%\w+) (%\w+)\s*$', _fdef(mod, blk['D']))
    if not md:
        return None
    den = md.group(2)
    mp = re.match(r'OpFMul %float (%\w+) %float_3_14159274\s*$', _fdef(mod, den))
    if not mp:
        return None
    msq = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, mp.group(1)))
    if not msq or msq.group(1) != msq.group(2):
        return None
    ma = re.match(r'OpFAdd %float (%\w+) %float_1\s*$', _fdef(mod, msq.group(1)))
    if not ma:
        return None
    mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, ma.group(1)))
    if not mm:
        return None
    noh2 = None
    for u, v in (mm.groups(), mm.groups()[::-1]):
        m2 = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, u))
        if m2 and m2.group(1) == m2.group(2):
            noh2 = m2.group(1)
    if noh2 is None:
        return None
    inner = noh2
    for _ in range(4):
        mc = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 %float_1\s*$',
                      _fdef(mod, inner))
        if not mc:
            break
        inner = mc.group(1)
    mdot = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', _fdef(mod, inner))
    if not mdot:
        return None
    tri = []
    for t in mdot.groups():
        mc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      _fdef(mod, t))
        tri.append(list(mc.groups()) if mc else None)
    if None in tri:
        return None
    # the shading normal is the triple that also feeds this block's NoV dot
    normal = None
    for slot in (blk['nov'], blk['nol']):
        d = _fdef(mod, slot)
        while True:
            m = re.match(r'OpExtInst %float %\w+ (NClamp|NMin|NMax) (%\w+)', d)
            if not m:
                break
            d = _fdef(mod, m.group(2))
        mdo = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', d)
        if not mdo:
            continue
        for t in mdo.groups():
            mc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                          _fdef(mod, t))
            if mc and list(mc.groups()) in tri:
                normal = list(mc.groups())
    if normal is None or tri[0] == tri[1]:
        return None
    h = tri[1] if tri[0] == normal else tri[0] if tri[1] == normal else None
    if h is None:
        return None
    # H must be a normalised vector: h_k = rsqrt(dot(u,u)) * u_k
    for k in range(3):
        if not re.match(r'OpFMul %float %\w+ %\w+\s*$', _fdef(mod, h[k])):
            return None
    return {'H': h, 'normal': normal, 'noh': inner, 'dot': inner}


def _find_tseg(mod, payload, fs, fe, trace_line, position):
    """t_segment: the payload word-3 load that PRODUCED this hit position.

    `94` sec 2.2's word 3 is the traced distance. The module loads it more than
    once, so "the load of word 3" is not a unique answer and picking the first
    would be a positional guess (GOTCHAS 10). The load is instead identified by
    the property that makes it the right one: it is the value multiplied into
    all THREE components of the module's own hit position

        P_c = ((t * dir_c) + prev_c) + offset_c

    -- so a bounded backward walk from each component, intersected over the
    three, leaves exactly one payload-t load. Dies otherwise.
    """
    acs = [m.group(1) for ln in mod.lines
           for m in [re.match(r'\s*(%\w+) = OpInBoundsAccessChain '
                              r'%_ptr_RayPayloadKHR_float ' + re.escape(payload)
                              + r' %uint_3\s*$', ln)] if m]
    if len(acs) != 1:
        die(f"{mod.name}: {len(acs)} access chains onto payload word 3 of "
            f"{payload}, want exactly 1")
    loads = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpLoad %float ' + re.escape(acs[0]) + r'\s*$', ln)
        if m:
            loads[m.group(1)] = i
    if not loads:
        die(f"{mod.name}: no load of payload word 3")

    def reach(tok, depth):
        seen = set()
        stack = [(tok, 0)]
        while stack:
            t, d = stack.pop()
            if t in seen or d > depth:
                continue
            seen.add(t)
            dd = _fdef(mod, t)
            if not re.match(r'Op(FAdd|FSub|FMul|FNegate) %float ', dd):
                continue
            for u in re.findall(r'%\w+', dd)[1:]:
                stack.append((u, d + 1))
        return seen

    common = reach(position[0], 5) & reach(position[1], 5) & reach(position[2], 5)
    hits = sorted(common & set(loads))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} payload-t loads feed all three hit "
            f"position components, want exactly 1")
    tid = hits[0]
    line = loads[tid]
    if not (fs <= line < fe) or line < trace_line:
        die(f"{mod.name}: the payload-t load at line {line+1} is not below the "
            f"path-loop trace at line {trace_line+1}")
    return tid, line


# --------------------------------------------------------------- emission
class Emitter:
    def __init__(self, mod, consts):
        self.mod, self.consts, self.ins = mod, consts, []
        self.ind = '       '

    def C(self, v):
        # 0.0 needs its own path: Module.const keys its cache on the float32
        # VALUE, and -0.0 == 0.0 in Python, so a module that declares
        # `OpConstant %float -0` (all ten of these do) hands back the NEGATIVE
        # zero for a request for +0. The arithmetic survives it -- every use
        # here is an NClamp lower bound or an OpSelect false arm, and
        # -0.0 * x + 1.0 is still exactly 1.0 -- but the emitted bytes would
        # then differ from dev/glint_model.py in an intermediate, and "the
        # model and the bytes agree" is the whole claim.
        if float(v) == 0.0 and not str(float(v)).startswith('-'):
            return _ensure(self.mod, self.consts,
                           r'\s*(%\w+)\s*=\s*OpConstant %float 0\s*$',
                           lambda n: f"    {n} = OpConstant %float 0")
        nid, decl = self.mod.const(float(v))
        if decl:
            self.consts.append(decl)
        return nid

    def U(self, v):
        # uconst() searches mod.lines, which does NOT yet hold the declarations
        # queued in `consts` -- six arms asking for the same PCG constant would
        # each queue their own and the assembler would see six definitions of
        # one id. The cache lives on the module so every Emitter shares it.
        v = int(v) & 0xFFFFFFFF
        cache = getattr(self.mod, '_carglint_u', None)
        if cache is None:
            cache = self.mod._carglint_u = {}
        if v in cache:
            return cache[v]
        nid, decl = self.mod.uconst(v)
        if decl:
            self.consts.append(decl)
        cache[v] = nid
        return nid

    def op(self, opname, ty, *a):
        i = self.mod.new_id()
        self.ins.append(f"{self.ind}{i} = {opname} {ty} " + ' '.join(a))
        return i

    def ext(self, name, ty, *a):
        i = self.mod.new_id()
        self.ins.append(f"{self.ind}{i} = OpExtInst {ty} {self.mod.glsl} {name} "
                        + ' '.join(a))
        return i


def _ensure(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def emit_cells(E, C, int_t, pos, off_xyz, dist, cell_c, decoy=None):
    """s -> ci -> the cell half of the hash. Returns (s, s2, hash_seed, ids)."""
    ratio = E.op('OpFMul', '%float', dist, E.C(C['INV_CELL']))
    m1 = E.ext('NClamp', '%float', ratio, E.C(1.0), E.C(C['RATIO_MAX']))
    lg = E.ext('Log2', '%float', m1)
    cl = E.ext('Ceil', '%float', lg)
    ex = E.ext('Exp2', '%float', cl)
    s = E.op('OpFMul', '%float', E.C(C['CELL']), ex)
    s2 = E.op('OpFMul', '%float', s, s)
    pw, ci, cu = [], [], []
    for k in range(3):
        # offset FIRST -- `94` sec 3.3's own quoted `%1419 = OpFAdd %float
        # %1416 %727`, and the order patch_rayq.py already emits.
        src = pos[k] if decoy == 'nooffset' else \
            E.op('OpFAdd', '%float', off_xyz[k], pos[k])
        pw.append(src)
        q = E.op('OpFDiv', '%float', src, s)
        qc = E.ext('NClamp', '%float', q, E.C(-float(C['CELL_MAX'])),
                   E.C(C['CELL_MAX']))
        fl = E.ext('Floor', '%float', qc)
        iv = E.op('OpConvertFToS', int_t, fl)
        ci.append(iv)
        cu.append(E.op('OpBitcast', '%uint', iv))
    mul = [E.op('OpIMul', '%uint', cu[k], E.U(int(GM.C_CELL[k]))) for k in range(3)]
    x0 = E.op('OpBitwiseXor', '%uint', mul[0], mul[1])
    seed = E.op('OpBitwiseXor', '%uint', x0, mul[2])
    return s, s2, seed, dict(world=pw, cell_int=ci, cell_uint=cu, s=s, s2=s2,
                             seed=seed, ladder=[ratio, m1, lg, cl, ex])


def emit_pcg(E, seed):
    st0 = E.op('OpIMul', '%uint', seed, E.U(int(GM.PCG_MUL)))
    st = E.op('OpIAdd', '%uint', st0, E.U(int(GM.PCG_INC)))
    s28 = E.op('OpShiftRightLogical', '%uint', st, E.U(28))
    sh = E.op('OpIAdd', '%uint', s28, E.U(4))
    rxs = E.op('OpShiftRightLogical', '%uint', st, sh)
    xr = E.op('OpBitwiseXor', '%uint', rxs, st)
    wd = E.op('OpIMul', '%uint', xr, E.U(int(GM.PCG_XMUL)))
    s22 = E.op('OpShiftRightLogical', '%uint', wd, E.U(22))
    return E.op('OpBitwiseXor', '%uint', s22, wd)


def emit_module_level(E, C, int_t, boolt, position, off_provider, tprim, tseg,
                      met, rgh, decoy=None):
    """`94` sec 4.4's ONCE-PER-INVOCATION half, as pure emission.

    The raygen splice and the driver selftest's compute kernel both go through
    THIS function, so "the model reproduces the shipped bytes" is a claim about
    one emitter, not two that happen to agree today.  `off_provider` is a
    callable so the cbv AccessChain/Load lands at the same point in the id
    stream as it did before this was factored out.
    """
    dist = E.op('OpFAdd', '%float', tprim, tseg)
    if decoy == 'camrel':
        # Deliberately WRONG: drop `98` sec 15's world offset, so the cell hash
        # is a function of the CAMERA-RELATIVE position and every glint crawls.
        # Exists only to prove verify_carglint.py rejects it. Never installed.
        off, off_ac, off_lo = [None, None, None], None, None
    else:
        off, off_ac, off_lo = off_provider()
    rfp = E.op('OpFMul', '%float', dist, E.C(C['PIX']))
    s, s2, seed, cid = emit_cells(E, C, int_t, position, off, rfp, C['CELL'],
                                  decoy='nooffset' if decoy == 'camrel' else None)
    kden = E.op('OpFMul', '%float', E.C(C['NU0']), s2)
    # gate: `94` sec 17.2's ramp on metallic x a hard roughness ceiling
    if decoy == 'nogate':
        # Deliberately WRONG: no gate at all, w == 1 everywhere. `90` sec 0's
        # vacuous-gate failure, reproduced on purpose. Never installed.
        w = E.C(1.0)
    else:
        md = E.op('OpFSub', '%float', met, E.C(C['M_LO']))
        mt0 = E.op('OpFMul', '%float', md, E.C(C['INV_M_SPAN']))
        mt = E.ext('NClamp', '%float', mt0, E.C(0.0), E.C(1.0))
        mt2 = E.op('OpFMul', '%float', mt, mt)
        n2 = E.op('OpFMul', '%float', mt, E.C(-2.0))
        m3 = E.op('OpFAdd', '%float', n2, E.C(3.0))
        sm = E.op('OpFMul', '%float', mt2, m3)
        rok = E.op('OpFOrdLessThan', boolt, rgh, E.C(C['R_MAX']))
        w = E.op('OpSelect', '%float', rok, sm, E.C(0.0))
    fd0 = E.op('OpFSub', '%float', E.C(C['FADE_END']), dist)
    fd1 = E.op('OpFMul', '%float', fd0, E.C(C['INV_FADE_SPAN']))
    wf = E.ext('NClamp', '%float', fd1, E.C(0.0), E.C(1.0))
    ww = E.op('OpFMul', '%float', w, wf)
    kw = E.op('OpFMul', '%float', E.C(C['K']), ww)
    return dict(t_primary=tprim, dist=dist, s=s, s2=s2, kden=kden, seed=seed,
                kw=kw, offset_chain=off_ac, offset_load=off_lo,
                offset_components=off, world=cid['world'],
                cell_int=cid['cell_int'], gate_w=w, fade=wf)


def emit_arm(A, C, int_t, boolt, H, D, seed, kden, kw):
    """`94` sec 4.4's PER-LOBE half: angular bin -> pcg -> Bernoulli flake ->
    `glint = mix(1, g, kw)`.  Returns the dict the report and the selftest read;
    `glint` is the one scalar the caller multiplies into the lobe."""
    bu = []
    for k in range(3):
        m0 = A.op('OpFMul', '%float', H[k], A.C(C['QBIN']))
        mc = A.ext('NClamp', '%float', m0, A.C(-float(C['BIN_MAX'])),
                   A.C(C['BIN_MAX']))
        fl = A.ext('Floor', '%float', mc)
        iv = A.op('OpConvertFToS', int_t, fl)
        bu.append(A.op('OpBitcast', '%uint', iv))
    bm = [A.op('OpIMul', '%uint', bu[k], A.U(int(GM.C_BIN[k]))) for k in range(3)]
    bx0 = A.op('OpBitwiseXor', '%uint', bm[0], bm[1])
    bx1 = A.op('OpBitwiseXor', '%uint', bx0, bm[2])
    sd = A.op('OpBitwiseXor', '%uint', seed, bx1)
    out = emit_pcg(A, sd)
    uf = A.op('OpConvertUToF', '%float', out)
    u = A.op('OpFMul', '%float', uf, A.C(C['TWO_M32']))
    nu = A.op('OpFMul', '%float', kden, D)
    p = A.ext('NMin', '%float', nu, A.C(1.0))
    pc = A.ext('NMax', '%float', p, A.C(C['INV_GMAX']))
    rec = A.op('OpFDiv', '%float', A.C(1.0), pc)
    lt = A.op('OpFOrdLessThan', boolt, u, pc)
    g = A.op('OpSelect', '%float', lt, rec, A.C(0.0))
    gm1 = A.op('OpFSub', '%float', g, A.C(1.0))
    t = A.op('OpFMul', '%float', kw, gm1)
    glint = A.op('OpFAdd', '%float', t, A.C(1.0))
    return dict(u=u, nu=nu, pc=pc, g=g, glint=glint, seed=sd, out=out)


def build(mod, opts, decoy=None):
    C = GM.constants(opts.knobs)
    consts, edits = [], []
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)

    # ---- detectors FIRST, before anything rewrites mod.lines (GOTCHAS 12) --
    blocks = find_ggx_blocks(mod)
    sg = count_sg_sites(mod)
    rep = dict(mode=opts.mode, sg_sites=sg, ggx_blocks=len(blocks),
               knobs=dict(opts.knobs), decoy=decoy,
               constants={k: f32s(v) for k, v in C.items()})
    if sg and not blocks:
        rep['variant'] = 'scalar-specular (no F0 in lobe) -- declined by name'
        rep['written'] = False
        return None, None, rep
    if len(blocks) != 6:
        die(f"{mod.name}: {len(blocks)} GGX blocks, want 6")

    trace_line = next((i for i in range(fs, fe) if TRACE_RE.match(mod.lines[i])), None)
    if trace_line is None:
        die(f"{mod.name}: no OpTraceRayKHR in the raygen entry function")
    ops = TRACE_RE.match(mod.lines[trace_line]).groups()[1].split()
    payload = ops[10]

    woff = _find_world_offset(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)
    tseg, tseg_line = _find_tseg(mod, payload, fs, fe, trace_line,
                                 woff['position'])
    met, met_scaled = _payload_byte3(mod, payload, 0, 'nclamp')
    rgh, rgh_scaled = _payload_byte3(mod, payload, 1, 'nminmax')
    f0_met, f0_n = _f0_chain_metallic(mod, blocks)
    if f0_met != met:
        die(f"{mod.name}: the F0-chain metallic {f0_met} is not the payload "
            f"metallic {met} -- the two readings of `94` sec 3.4 disagree")
    hs = []
    for b in blocks:
        h = _read_H(mod, b)
        if h is None:
            die(f"{mod.name}: block at line {b['schlick_line']} -- no half "
                f"vector recoverable from its D chain")
        hs.append(h)
    rep.update(world_offset={'cbv': woff['cbv'], 'member': woff['member'],
                             'position': woff['position']},
               primary={'dot': prim['dot'], 'rsqrt': prim['rsqrt']},
               t_segment=tseg, metallic=met, roughness=rgh,
               f0_metallic_agrees=f0_n,
               arms={k: sum(1 for b in blocks if b['arm'] == k)
                     for k in ('punctual', 'area', 'unknown')},
               blocks=[dict(line=b['schlick_line'], arm=b['arm'], D=b['D'],
                            H=h['H'], spec=[s['res'] for s in b['spec']])
                       for b, h in zip(blocks, hs)])

    if opts.report:
        rep['written'] = False
        return None, None, rep

    # `94` sec 6.1: k = 0 emits NOTHING, so the control is byte-identical.
    if opts.mode == 'glint' and float(C['K']) == 0.0:
        rep['written'] = True
        rep['emitted'] = 0
        rep['note'] = 'k_glint == 0: no constants, no instructions, no rewrite'
        return [], [], rep

    boolt = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                    lambda n: f"    {n} = OpTypeBool")
    int_t = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeInt 32 1\s*$',
                    lambda n: f"    {n} = OpTypeInt 32 1")

    if opts.mode == 'cell':
        return _build_cell(mod, C, consts, edits, eline, fs, fe, woff, prim,
                           int_t, boolt, rep, decoy)
    return _build_glint(mod, C, consts, edits, blocks, hs, woff, prim, tseg,
                        tseg_line, met, rgh, int_t, boolt, rep, decoy)


def _offset_load(E, woff):
    u0 = E.U(0)
    umem = E.U(woff['member'])
    ac = E.op('OpAccessChain', woff['ptr_type'], woff['cbv'], u0, umem)
    lo = E.op('OpLoad', '%v4float', ac)
    return [E.op('OpCompositeExtract', '%float', lo, str(k)) for k in range(3)], ac, lo


def _build_glint(mod, C, consts, edits, blocks, hs, woff, prim, tseg, tseg_line,
                 met, rgh, int_t, boolt, rep, decoy):
    # ---- where the once-per-invocation half goes -------------------------
    # PLACEMENT PROOF part 1: it is emitted after the LAST of the ids it
    # consumes and above the FIRST GGX block, on an ordinary instruction line.
    # Part 2 is spirv-val's own dominance check, run on every shipped module.
    consumed = [prim['dot'], prim['rsqrt'], tseg, met, rgh, woff['cbv']] + \
        list(woff['position'])
    at = max(_fline(mod, t) for t in consumed)
    first_block = min(b['schlick_line'] - 1 for b in blocks)
    if at >= first_block:
        die(f"{mod.name}: the preamble's last input is at line {at+1}, at or "
            f"below the first GGX block (line {first_block+1})")
    if not re.match(r'\s*%\w+ = Op', mod.lines[at]) or \
            re.match(r'\s*%\w+ = OpLabel', mod.lines[at]):
        die(f"{mod.name}: line {at+1} is not an ordinary instruction: "
            f"{mod.lines[at].strip()}")

    E = Emitter(mod, consts)
    tprim = E.op('OpFMul', '%float', prim['dot'], prim['rsqrt'])
    ml = emit_module_level(E, C, int_t, boolt, list(woff['position']),
                           lambda: _offset_load(E, woff), tprim, tseg,
                           met, rgh, decoy)
    s, s2, seed, kden, kw = ml['s'], ml['s2'], ml['seed'], ml['kden'], ml['kw']
    edits.append((at, E.ins))
    rep['preamble'] = dict(line=at + 1, count=len(E.ins), **ml)

    # ---- the per-arm half, once per GGX block ----------------------------
    rewrites, per = [], []
    for b, h in zip(blocks, hs):
        A = Emitter(mod, consts)
        A.ind = re.match(r'(\s*)', mod.lines[b['spec'][0]['line']]).group(1)
        H = [(h['H'][k] if decoy != 'viewbin' else b['nov']) for k in range(3)]
        ar = emit_arm(A, C, int_t, boolt, H, b['D'], seed, kden, kw)
        glint = ar['glint']
        for sp in b['spec']:
            nid = A.op('OpFMul', '%float', sp['res'], glint)
            rewrites.append((max(s2['line'] for s2 in b['spec']), sp['res'], nid))
        pos = max(sp['line'] for sp in b['spec'])
        edits.append((pos, A.ins))
        per.append(dict(line=b['schlick_line'], arm=b['arm'], count=len(A.ins),
                        **ar))
    nuses = 0
    for pos, old, new in rewrites:
        nuses += replace_all_uses(mod, old, new, pos)
    rep['per_arm'] = per
    rep['uses_rewritten'] = nuses
    rep['emitted'] = len(rep['preamble']) and sum(p['count'] for p in per) + \
        rep['preamble']['count']
    rep['written'] = True
    return consts, edits, rep


def _build_cell(mod, C, consts, edits, eline, fs, fe, woff, prim, int_t, boolt,
                rep, decoy):
    """`94` sec 6.3 step 4's `-glintcell`: the PRIMARY hit's world cell, flat.

    The primary reconstruction is used, not the path vertex, for two reasons:
    it is deterministic per pixel (a bounce vertex is stochastic and would read
    as noise, not as a crawl), and it dominates nothing -- so the value goes
    through a Private uint, which has no dominance requirement at all.
    """
    writes = find_image_writes(mod)
    ptr_priv_u = _ensure(mod, consts,
                         r'\s*(%\w+)\s*=\s*OpTypePointer Private %uint\s*$',
                         lambda n: f"    {n} = OpTypePointer Private %uint")
    var = mod.new_id()
    consts.append(f"    {var} = OpVariable {ptr_priv_u} Private")
    mod.lines[eline] = mod.lines[eline].rstrip() + f' {var}'
    u0, _d = mod.uconst(0)
    if _d:
        consts.append(_d)
    lab = next(i for i in range(fs, fe) if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    at0 = lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at0 + 1]):
        at0 += 1
    edits.append((at0, [f"       OpStore {var} {u0}"]))

    # prim['V'] is in the consumed set even though the diagnostic does not use
    # it: patch_rayq._find_primary_ray recognises the reconstruction by finding
    # the three view-ray multiplies within 16 lines of the InverseSqrt, so an
    # insertion above them would make the SHIPPED bytes unreadable to the very
    # detector the verifier re-runs on them.
    at = max(_fline(mod, t) for t in
             [prim['dot'], prim['rsqrt'], woff['cbv']]
             + list(prim['P']) + list(prim['V']))
    E = Emitter(mod, consts)
    tprim = E.op('OpFMul', '%float', prim['dot'], prim['rsqrt'])
    if decoy == 'camrel':
        off = [None, None, None]
        off_ac = off_lo = None
    else:
        off, off_ac, off_lo = _offset_load(E, woff)
    rfp = E.op('OpFMul', '%float', tprim, E.C(C['PIX']))
    s, s2, seed, cid = emit_cells(E, C, int_t, list(prim['P']), off, rfp,
                                  C['CELL'],
                                  decoy='nooffset' if decoy == 'camrel' else None)
    out = emit_pcg(E, seed)
    E.ins.append(f"{E.ind}OpStore {var} {out}")
    edits.append((at, E.ins))
    rep['preamble'] = dict(line=at + 1, count=len(E.ins), t_primary=tprim,
                           s=s, seed=seed, hash=out, latch=var,
                           offset_chain=off_ac, offset_load=off_lo,
                           offset_components=off, world=cid['world'],
                           cell_int=cid['cell_int'])

    one, _d = mod.const(1.0)
    if _d:
        consts.append(_d)
    hue = [[Emitter(mod, consts).C(v) for v in rgb] for _n, rgb in PALETTE]
    # (Emitter.C appends to the same `consts` list; the per-hue Emitters exist
    #  only to reuse the constant-interning helper.)
    u7, _d = mod.uconst(7)
    if _d:
        consts.append(_d)
    ubk = []
    for k in range(8):
        nid, decl = mod.uconst(k)
        if decl:
            consts.append(decl)
        ubk.append(nid)
    painted, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float construct'})
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
        h3 = W.op('OpBitwiseAnd', '%uint', lv, u7)
        gates = []
        for k in range(8):
            gates.append((W.op('OpIEqual', boolt, h3, ubk[k]), hue[k]))
        newc = []
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                cur = W.op('OpSelect', '%float', g, rgb[ch], cur)
            newc.append(W.op('OpFMul', '%float', c[ch], cur))
        nt = W.op('OpCompositeConstruct', '%v4float', newc[0], newc[1], newc[2], c[3])
        edits.append((w['line'] - 1, W.ins))
        mod.lines[w['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                      r'\g<1>' + nt, mod.lines[w['line']])
        painted.append(w['line'] + 1)
    if not painted:
        die(f"{mod.name}: no radiance write to paint the cell hash at")
    rep['painted'] = painted
    rep['skipped'] = skipped
    rep['palette'] = [n for n, _ in PALETTE]
    rep['written'] = True
    return consts, edits, rep


# --------------------------------------------------------------- driver
def process(path, outdir, opts, do_rt=True, decoy=None):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    consts, edits, r = build(mod, opts, decoy)
    rep['carglint'] = r
    if consts is None:
        rep['written'] = False
        return rep
    apply_edits(mod, consts, edits)
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--mode', default='glint', choices=('glint', 'cell'))
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--decoy', choices=('camrel', 'nogate', 'viewbin'), default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_carglint.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    for k, v in GM.DEFAULTS.items():
        ap.add_argument('--' + k.replace('_', '-'), type=float, default=v)
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    a.knobs = GM.knobs(**{k: getattr(a, k) for k in GM.DEFAULTS})
    reps = [process(p, a.outdir, a, do_rt=not a.no_roundtrip_check, decoy=a.decoy)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
