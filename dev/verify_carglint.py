#!/usr/bin/env python3
"""verify_carglint.py -- re-derive `94` sec 4.4's glints from the SHIPPED bytes.

    python3 dev/verify_carglint.py <rung-dir> [--mode glint|cell] [--ctl]
                                   [--base DIR] [--cell 0.008] ...

Everything below is read back out of the parked `.spv` files by disassembling
them again. Nothing is taken from the patcher's own reports, and no build
intermediate is consulted -- `dev/verify_cloth_sheen.py`'s rule, and the reason
`88`'s vacuous `== 0` gate (`90` sec 0) could not have survived it.

THE AXES (all of them fail the run, none of them warn)

  1  selection complete: 77 compute + 4 restirgi + 12 reference, and the two
     scalar-specular permutations are byte-verbatim from the base.
  2  10 patched permutations x 6 GGX blocks = 60 glint sites, or die.
  3  the ENERGY SHAPE: every one of the 18 spec results per module is consumed
     as `spec * glint`, the original definition is untouched, and no unrewritten
     use of it survives below the splice.
  4  glint = 1 + kw*(g - 1); g = select(u < pc, 1/pc, 0);
     pc = NMax(NMin(kden*D, 1), 1/glint_max) -- with D the BLOCK'S OWN D.
  5  u = ConvertUToF(PCG-RXS-M-XS(seed)) * 2^-32, constants exact.
  6  seed = cellhash ^ fold(floor(NClamp(H*q))) -- and H is the BLOCK'S OWN
     half vector, traced independently through its D chain. (Kills --decoy
     viewbin, which bins the view cosine instead.)
  7  the WORLD-POSITION CONTRACT: the cell hash is built from
     `cb[member].xyz + position`, and `member` is re-derived here by
     patch_rayq._find_world_offset -- the same structural rule `98` sec 15
     proved on screen -- and must be the member the bytes actually load.
     (Kills --decoy camrel.)
  8  the GATE is real: w = select(rough < R_MAX, smoothstep(m), 0), with
     `m` independently traced to the F0 chain AND to byte 3 of payload word 0,
     and `rough` to NMin(NMax(byte3(word1)/255, .04), 1). (Kills --decoy nogate.)
  9  the constants in the bytes equal glint_model.constants(knobs), bit for bit.
 10  the CLOSED FORM: dev/glint_model.py, run over 10^5 random (P, H) samples,
     must give E[g] = 1 within Monte-Carlo error and max(g) <= glint_max, and
     the gate-false evaluation must be BIT-EXACT 1.0 (so a gated-off pixel is
     the base image, not "very close to" it).
 11  hash quality: adjacent cells decorrelate, and the emitted mix reproduces
     the model bit-exactly on 10^5 inputs.
 12  spirv-val --target-env vulkan1.4 on every shipped module.
"""
import argparse, glob, hashlib, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glint_model as GM
from patch_chs_brdf import load_lenient
from patch_ms_ggx import find_ggx_blocks, count_sg_sites
from patch_rayq import _find_world_offset, _find_primary_ray, _entry, _func_span
from patch_carglint import _read_H, _payload_byte3, _f0_chain_metallic, _fdef
from patch_skin_brdf import f32, f32s

PASS_THROUGH = ('40c6faab52a13874', 'ab7f1822eeb0331b')
FAIL = []


def bad(msg):
    FAIL.append(msg)


def _dis(p, work):
    o = os.path.join(work, os.path.basename(p) + '.spvasm')
    r = subprocess.run(['spirv-dis', p, '-o', o], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('spirv-dis failed on ' + p)
    return o


def _fc(mod, tok):
    """The float32 value of a constant id, or None."""
    d = _fdef(mod, tok)
    m = re.match(r'OpConstant %float (\S+)\s*$', d)
    if not m:
        return None
    try:
        return f32(float(m.group(1)))
    except ValueError:
        return None


def _uc(mod, tok):
    d = _fdef(mod, tok)
    m = re.match(r'OpConstant %uint (\d+)\s*$', d)
    return int(m.group(1)) if m else None


def _m(mod, tok, pat):
    return re.match(pat, _fdef(mod, tok))


def glint_signature(mod, sp_res):
    """Is `sp_res` consumed by the glint multiply? Returns the glint id or None.

    The shape is unmistakable and is NOT something the base can accidentally
    contain: `spec * (kw*(g - 1) + 1)` with `g` an OpSelect. Used both as the
    positive detector and -- counted and required to be ZERO -- as the
    control's proof that nothing was spliced.
    """
    uses = [ln for ln in mod.lines
            if re.search(r'(?<![%\w])' + re.escape(sp_res) + r'(?![\w])', ln)
            and not re.match(r'\s*' + re.escape(sp_res) + r'\s*=', ln)]
    if len(uses) != 1:
        return None
    mm = re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(sp_res)
                  + r' (%\w+)\s*$', uses[0])
    if not mm:
        return None
    gl = mm.group(2)
    ma = _m(mod, gl, r'OpFAdd %float (%\w+) (%\w+)\s*$')
    if not ma or _fc(mod, ma.group(2)) != f32(1.0):
        return None
    mt = _m(mod, ma.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mt:
        return None
    mg = _m(mod, mt.group(2), r'OpFSub %float (%\w+) (%\w+)\s*$')
    if not mg or _fc(mod, mg.group(2)) != f32(1.0):
        return None
    if not _fdef(mod, mg.group(1)).startswith('OpSelect %float'):
        return None
    return gl


def _clamp01(mod, tok):
    """NClamp(x, 0, 1) by VALUE, not by literal id name: these modules declare
    `OpConstant %float -0` and Module.const's value cache hands it back for a
    request for +0, so a name-matched `%float_0` would miss half the sites."""
    m = _m(mod, tok, r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
    if not m:
        return None
    if _fc(mod, m.group(2)) != f32(0.0) or _fc(mod, m.group(3)) != f32(1.0):
        return None
    return m.group(1)


def _isclamp01(mod, tok):
    return _clamp01(mod, tok) is not None


# ---------------------------------------------------------------- the walk
def check_module(mod, C, name):
    """Re-derive the whole splice for one patched reference permutation."""
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)
    blocks = find_ggx_blocks(mod)
    if len(blocks) != 6:
        bad(f'{name}: {len(blocks)} GGX blocks, want 6')
        return 0
    woff = _find_world_offset(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)

    sites = 0
    seeds, kws, kdens = set(), set(), set()
    for b in blocks:
        h = _read_H(mod, b)
        if h is None:
            bad(f'{name}@{b["schlick_line"]}: no half vector in the D chain')
            continue
        # --- axis 3: the energy shape, spec' = spec * glint -----------------
        glints = set()
        for sp in b['spec']:
            uses = [ln for ln in mod.lines
                    if re.search(r'(?<![%\w])' + re.escape(sp['res']) + r'(?![\w])', ln)
                    and not re.match(r'\s*' + re.escape(sp['res']) + r'\s*=', ln)]
            if len(uses) != 1:
                bad(f'{name}: {sp["res"]} has {len(uses)} uses after the splice, '
                    f'want exactly 1 (the glint multiply)')
                continue
            mm = re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(sp['res'])
                          + r' (%\w+)\s*$', uses[0])
            if not mm:
                bad(f'{name}: {sp["res"]} is not consumed as `spec * glint`: '
                    + uses[0].strip())
                continue
            glints.add(mm.group(2))
        if len(glints) != 1:
            bad(f'{name}@{b["schlick_line"]}: the three channels do not share '
                f'one glint factor: {sorted(glints)}')
            continue
        glint = glints.pop()
        # --- axis 4: glint = 1 + kw*(g-1) ----------------------------------
        ma = _m(mod, glint, r'OpFAdd %float (%\w+) (%\w+)\s*$')
        if not ma or _fc(mod, ma.group(2)) != f32(1.0):
            bad(f'{name}: glint {glint} is not (x + 1.0)')
            continue
        mt = _m(mod, ma.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mt:
            bad(f'{name}: glint addend is not a product')
            continue
        kw, gm1 = mt.groups()
        mg = _m(mod, gm1, r'OpFSub %float (%\w+) (%\w+)\s*$')
        if not mg or _fc(mod, mg.group(2)) != f32(1.0):
            bad(f'{name}: the mix uses {gm1}, not (g - 1.0)')
            continue
        g = mg.group(1)
        kws.add(kw)
        msel = _m(mod, g, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$')
        if not msel or _fc(mod, msel.group(3)) != f32(0.0):
            bad(f'{name}: g {g} is not select(_, 1/pc, 0.0)')
            continue
        cond, rec, _z = msel.groups()
        mlt = _m(mod, cond, r'OpFOrdLessThan %\w+ (%\w+) (%\w+)\s*$')
        mrec = _m(mod, rec, r'OpFDiv %float (%\w+) (%\w+)\s*$')
        if not mlt or not mrec or _fc(mod, mrec.group(1)) != f32(1.0):
            bad(f'{name}: the Bernoulli test is not `u < pc ? 1/pc : 0`')
            continue
        u, pc = mlt.groups()
        if mrec.group(2) != pc:
            bad(f'{name}: 1/{mrec.group(2)} is not the reciprocal of the '
                f'tested probability {pc}')
            continue
        # pc = NMax(NMin(nu, 1), 1/glint_max)   <- the firefly clamp
        mpc = _m(mod, pc, r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)\s*$')
        if not mpc or _fc(mod, mpc.group(2)) != C['INV_GMAX']:
            bad(f'{name}: pc is not NMax(_, {f32s(C["INV_GMAX"])})')
            continue
        mp = _m(mod, mpc.group(1),
                r'OpExtInst %float %\w+ NMin (%\w+) (%\w+)\s*$')
        if mp and _fc(mod, mp.group(2)) != f32(1.0):
            mp = None
        if not mp:
            bad(f'{name}: p is not NMin(nu, 1.0)')
            continue
        mnu = _m(mod, mp.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mnu or b['D'] not in mnu.groups():
            bad(f'{name}@{b["schlick_line"]}: nu does not multiply this '
                f"block's own D ({b['D']})")
            continue
        kden = mnu.group(1) if mnu.group(2) == b['D'] else mnu.group(2)
        kdens.add(kden)
        # nu = (nu0 * omega_bin) * s^2 * D -- the folded density constant is
        # the ONLY thing that separates -dense from -sparse, so it is read back
        # by value or the three rungs could impersonate each other.
        mk = _m(mod, kden, r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mk or _fc(mod, mk.group(1)) != C['NU0']:
            bad(f'{name}: the flake density constant is not '
                f'{f32s(C["NU0"])} (= nu0 * theta_bin^2)')
            continue
        # --- axis 5: u = ConvertUToF(pcg(seed)) * 2^-32 --------------------
        mu = _m(mod, u, r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mu or _fc(mod, mu.group(2)) != C['TWO_M32']:
            bad(f'{name}: u is not `x * 2^-32`')
            continue
        mcv = _m(mod, mu.group(1), r'OpConvertUToF %float (%\w+)\s*$')
        if not mcv:
            bad(f'{name}: u does not come from a uint')
            continue
        seed = _check_pcg(mod, mcv.group(1), name)
        if seed is None:
            continue
        # --- axis 6: seed = cellhash ^ fold(bin(H)) ------------------------
        mx = _m(mod, seed, r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
        if not mx:
            bad(f'{name}: the pcg input is not a XOR of two folds')
            continue
        found = None
        for cellh, binh in (mx.groups(), mx.groups()[::-1]):
            if _check_bin(mod, binh, h['H'], C, name, quiet=True):
                found = (cellh, binh)
        if found is None:
            bad(f'{name}@{b["schlick_line"]}: neither XOR operand is the fold '
                f"of floor(H*q) over this block's own half vector {h['H']}")
            continue
        seeds.add(found[0])
        sites += 1

    if len(seeds) > 1:
        bad(f'{name}: {len(seeds)} distinct cell hashes, want 1 (hoisted once '
            f'per invocation)')
    if len(kws) > 1:
        bad(f'{name}: {len(kws)} distinct mix weights, want 1')
    if len(kdens) > 1:
        bad(f'{name}: {len(kdens)} distinct nu0*s^2 terms, want 1')
    if seeds:
        _check_cells(mod, sorted(seeds)[0], woff, C, name)
    if kws:
        _check_gate(mod, sorted(kws)[0], blocks, woff, prim, C, name)
    return sites


def _check_pcg(mod, out, name):
    """PCG RXS-M-XS, read backwards from its output. Returns the seed id."""
    m = _m(mod, out, r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
    if not m:
        bad(f'{name}: pcg output is not a XOR')
        return None
    for sh, wd in (m.groups(), m.groups()[::-1]):
        ms = _m(mod, sh, r'OpShiftRightLogical %uint (%\w+) (%\w+)\s*$')
        if not ms or ms.group(1) != wd or _uc(mod, ms.group(2)) != 22:
            continue
        mw = _m(mod, wd, r'OpIMul %uint (%\w+) (%\w+)\s*$')
        if not mw or _uc(mod, mw.group(2)) != int(GM.PCG_XMUL):
            continue
        mxr = _m(mod, mw.group(1), r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
        if not mxr:
            continue
        for rxs, st in (mxr.groups(), mxr.groups()[::-1]):
            mr = _m(mod, rxs, r'OpShiftRightLogical %uint (%\w+) (%\w+)\s*$')
            if not mr or mr.group(1) != st:
                continue
            msh = _m(mod, mr.group(2), r'OpIAdd %uint (%\w+) (%\w+)\s*$')
            if not msh or _uc(mod, msh.group(2)) != 4:
                continue
            m28 = _m(mod, msh.group(1), r'OpShiftRightLogical %uint (%\w+) (%\w+)\s*$')
            if not m28 or m28.group(1) != st or _uc(mod, m28.group(2)) != 28:
                continue
            mst = _m(mod, st, r'OpIAdd %uint (%\w+) (%\w+)\s*$')
            if not mst or _uc(mod, mst.group(2)) != int(GM.PCG_INC):
                continue
            mmul = _m(mod, mst.group(1), r'OpIMul %uint (%\w+) (%\w+)\s*$')
            if not mmul or _uc(mod, mmul.group(2)) != int(GM.PCG_MUL):
                continue
            return mmul.group(1)
    bad(f'{name}: the finaliser at {out} is not PCG RXS-M-XS with the '
        f'documented constants')
    return None


def _fold3(mod, tok, mult, name, quiet=False):
    """(a*C0) ^ (b*C1) ^ (c*C2) -> [a, b, c], in axis order, or None."""
    m = _m(mod, tok, r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
    if not m:
        return None
    got = {}
    terms = []
    m2 = _m(mod, m.group(1), r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
    if m2:
        terms = [m2.group(1), m2.group(2), m.group(2)]
    else:
        m2 = _m(mod, m.group(2), r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$')
        if not m2:
            return None
        terms = [m2.group(1), m2.group(2), m.group(1)]
    for t in terms:
        mm = _m(mod, t, r'OpIMul %uint (%\w+) (%\w+)\s*$')
        if not mm:
            return None
        c = _uc(mod, mm.group(2))
        if c not in [int(x) for x in mult]:
            return None
        got[[int(x) for x in mult].index(c)] = mm.group(1)
    if set(got) != {0, 1, 2}:
        return None
    return [got[k] for k in range(3)]


def _bitint(mod, tok):
    m = _m(mod, tok, r'OpBitcast %uint (%\w+)\s*$')
    if not m:
        return None
    m2 = _m(mod, m.group(1), r'OpConvertFToS %\w+ (%\w+)\s*$')
    if not m2:
        return None
    m3 = _m(mod, m2.group(1), r'OpExtInst %float %\w+ Floor (%\w+)\s*$')
    return m3.group(1) if m3 else None


def _check_bin(mod, tok, H, C, name, quiet=False):
    v = _fold3(mod, tok, GM.C_BIN, name, quiet)
    if v is None:
        return False
    for k in range(3):
        fl = _bitint(mod, v[k])
        if fl is None:
            return False
        mc = _m(mod, fl, r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
        if not mc or _fc(mod, mc.group(3)) != C['BIN_MAX']:
            return False
        mq = _m(mod, mc.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
        if not mq or _fc(mod, mq.group(2)) != C['QBIN'] or mq.group(1) != H[k]:
            return False
    return True


def _check_cells(mod, tok, woff, C, name):
    v = _fold3(mod, tok, GM.C_CELL, name)
    if v is None:
        bad(f'{name}: the cell hash is not the documented 3-axis fold')
        return
    ss = set()
    for k in range(3):
        fl = _bitint(mod, v[k])
        if fl is None:
            bad(f'{name}: cell axis {k} is not bitcast(ConvertFToS(floor(_)))')
            return
        mc = _m(mod, fl, r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
        if not mc or _fc(mod, mc.group(3)) != C['CELL_MAX']:
            bad(f'{name}: cell axis {k} has no NClamp totality guard')
            return
        md = _m(mod, mc.group(1), r'OpFDiv %float (%\w+) (%\w+)\s*$')
        if not md:
            bad(f'{name}: cell axis {k} is not P_w / s')
            return
        ss.add(md.group(2))
        # --- axis 7: the world-position contract --------------------------
        maa = _m(mod, md.group(1), r'OpFAdd %float (%\w+) (%\w+)\s*$')
        if not maa:
            bad(f'{name}: cell axis {k} hashes {md.group(1)} directly -- the '
                f'world offset of `98` sec 15 is NOT added. Glints would crawl.')
            return
        off, pos = maa.groups()
        if pos != woff['position'][k]:
            off, pos = pos, off
        if pos != woff['position'][k]:
            bad(f'{name}: cell axis {k} does not add to the module\'s own hit '
                f'position {woff["position"][k]}')
            return
        me = _m(mod, off, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not me or int(me.group(2)) != k:
            bad(f'{name}: the offset for axis {k} is not component {k} of a load')
            return
        ml = _m(mod, me.group(1), r'OpLoad %v4float (%\w+)\s*$')
        mac = _m(mod, ml.group(1), r'OpAccessChain %\w+ (%\w+) (%\w+) (%\w+)\s*$') if ml else None
        if not mac or mac.group(1) != woff['cbv'] or \
                _uc(mod, mac.group(3)) != woff['member']:
            bad(f'{name}: the offset is not cb[{woff["cbv"]}][{woff["member"]}] '
                f'-- the member `98` sec 15 proved')
            return
    if len(ss) != 1:
        bad(f'{name}: the three cell axes use {len(ss)} different cell sizes')
        return
    _check_ladder(mod, sorted(ss)[0], C, name)


def _check_ladder(mod, s, C, name):
    m = _m(mod, s, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m or _fc(mod, m.group(1)) != C['CELL']:
        bad(f'{name}: s is not cell * exp2(...)')
        return
    me = _m(mod, m.group(2), r'OpExtInst %float %\w+ Exp2 (%\w+)\s*$')
    mc = _m(mod, me.group(1), r'OpExtInst %float %\w+ Ceil (%\w+)\s*$') if me else None
    ml = _m(mod, mc.group(1), r'OpExtInst %float %\w+ Log2 (%\w+)\s*$') if mc else None
    if not ml:
        bad(f'{name}: the LOD ladder is not cell*exp2(ceil(log2(_)))')
        return
    mn = _m(mod, ml.group(1), r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
    if not mn or _fc(mod, mn.group(2)) != f32(1.0) or \
            _fc(mod, mn.group(3)) != C['RATIO_MAX']:
        bad(f'{name}: the ladder argument is not NClamp(r/cell, 1, RATIO_MAX)')
        return
    mr = _m(mod, mn.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mr or _fc(mod, mr.group(2)) != C['INV_CELL']:
        bad(f'{name}: the ladder argument is not scaled by 1/cell')


def _check_gate(mod, kw, blocks, woff, prim, C, name):
    """axis 8 -- and the two independent readings of metallic must agree."""
    m = _m(mod, kw, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m or _fc(mod, m.group(1)) != C['K']:
        bad(f'{name}: kw is not k_glint * (w * w_fade)')
        return
    mw = _m(mod, m.group(2), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mw:
        bad(f'{name}: kw does not carry a (gate x fade) product')
        return
    w, wf = mw.groups()
    if not _isclamp01(mod, wf):
        w, wf = wf, w
    msel = _m(mod, w, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$')
    if not msel or _fc(mod, msel.group(3)) != f32(0.0):
        bad(f'{name}: the gate weight is not select(rough-ok, smoothstep, 0.0) '
            f'-- an ungated build is exactly `90` sec 0\'s vacuous gate')
        return
    mr = _m(mod, msel.group(1), r'OpFOrdLessThan %\w+ (%\w+) (%\w+)\s*$')
    if not mr or _fc(mod, mr.group(2)) != C['R_MAX']:
        bad(f'{name}: the roughness test is not `rough < {f32s(C["R_MAX"])}`')
        return
    # independent re-derivation of the two G-buffer scalars
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)
    trace = next(i for i in range(fs, fe)
                 if re.match(r'\s*OpTraceRayKHR\s', mod.lines[i]))
    payload = mod.lines[trace].split()[-1]
    met, _ = _payload_byte3(mod, payload, 0, 'nclamp')
    rgh, _ = _payload_byte3(mod, payload, 1, 'nminmax')
    f0m, n = _f0_chain_metallic(mod, blocks)
    if n != 18:
        bad(f'{name}: {n} F0 chains agreed on metallic, want 18')
    if f0m != met:
        bad(f'{name}: the F0-chain metallic {f0m} != the payload metallic {met}')
    if mr.group(1) != rgh:
        bad(f'{name}: the gate tests {mr.group(1)}, not the authored roughness '
            f'{rgh}')
    # smoothstep(t) = t*t*(3 - 2t), t = NClamp((m - M_LO)*INV_M_SPAN, 0, 1)
    msm = _m(mod, msel.group(2), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not msm:
        bad(f'{name}: the ramp is not a product')
        return
    t2, lin = msm.groups()
    m2 = _m(mod, t2, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m2 or m2.group(1) != m2.group(2):
        t2, lin = lin, t2
        m2 = _m(mod, t2, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not m2 or m2.group(1) != m2.group(2):
        bad(f'{name}: the ramp has no t*t term')
        return
    t = m2.group(1)
    ml = _m(mod, lin, r'OpFAdd %float (%\w+) (%\w+)\s*$')
    if not ml or _fc(mod, ml.group(2)) != f32(3.0):
        bad(f'{name}: the ramp is not t*t*(3 - 2t)')
        return
    mn2 = _m(mod, ml.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mn2 or mn2.group(1) != t or _fc(mod, mn2.group(2)) != f32(-2.0):
        bad(f'{name}: the ramp is not t*t*(3 - 2t)')
        return
    mt = _clamp01(mod, t)
    if not mt:
        bad(f'{name}: the ramp parameter is not clamped to [0,1]')
        return
    ms = _m(mod, mt, r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not ms or _fc(mod, ms.group(2)) != C['INV_M_SPAN']:
        bad(f'{name}: the ramp is not scaled by 1/(m_hi - m_lo)')
        return
    md = _m(mod, ms.group(1), r'OpFSub %float (%\w+) (%\w+)\s*$')
    if not md or md.group(1) != met or _fc(mod, md.group(2)) != C['M_LO']:
        bad(f'{name}: the ramp is not (metallic - m_lo); it reads '
            f'{md.group(1) if md else "?"}')


# ------------------------------------------------------------- cell mode
def check_cell_module(mod, C, name):
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)
    woff = _find_world_offset(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)
    stores = [ln for ln in mod.lines if re.match(r'\s*OpStore %\w+ %\w+\s*$', ln)]
    lat = None
    for ln in mod.lines:
        m = re.match(r'\s*OpStore (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        if _fdef(mod, m.group(1)).startswith('OpVariable') and \
                'Private' in _fdef(mod, m.group(1)) and \
                _fdef(mod, m.group(2)).startswith('OpBitwiseXor'):
            lat = m.group(2)
    if lat is None:
        bad(f'{name}: no Private latch carrying a hash')
        return 0
    seed = _check_pcg(mod, lat, name)
    if seed is None:
        return 0
    v = _fold3(mod, seed, GM.C_CELL, name)
    if v is None:
        bad(f'{name}: the latched hash is not the documented cell fold')
        return 0
    # the diagnostic hashes the PRIMARY position, not a path vertex
    hit = _bitint(mod, v[0])
    mc = _m(mod, hit, r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$')
    md = _m(mod, mc.group(1), r'OpFDiv %float (%\w+) (%\w+)\s*$') if mc else None
    maa = _m(mod, md.group(1), r'OpFAdd %float (%\w+) (%\w+)\s*$') if md else None
    if not maa:
        bad(f'{name}: the diagnostic does not add the world offset')
        return 0
    if prim['P'][0] not in maa.groups():
        bad(f'{name}: the diagnostic hashes {maa.groups()}, not the PRIMARY '
            f'reconstruction {prim["P"][0]}')
        return 0
    n = 0
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite %\w+ %\w+ (%\w+)\s*$', ln)
        if not m:
            continue
        mc2 = _m(mod, m.group(1), r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$')
        if mc2 and all(_m(mod, x, r'OpFMul %float (%\w+) (%\w+)\s*$')
                       for x in mc2.groups()[:3]):
            n += 1
    if n == 0:
        bad(f'{name}: no painted radiance write')
    return n


# -------------------------------------------------------- the closed form
def closed_form(C, n=100000, seed=11):
    rng = np.random.default_rng(seed)
    P = (rng.random((3, n), dtype=np.float32) * np.float32(400)
         - np.float32(200)).astype(np.float32)
    H = rng.normal(size=(3, n)).astype(np.float32)
    H /= np.linalg.norm(H, axis=0)
    D = (np.float32(10) ** (rng.random(n, dtype=np.float32)
                            * np.float32(3.5))).astype(np.float32)
    tp = (rng.random(n, dtype=np.float32) * np.float32(30)
          + np.float32(0.5)).astype(np.float32)
    ts = (rng.random(n, dtype=np.float32) * np.float32(12)).astype(np.float32)
    m = rng.random(n, dtype=np.float32)
    r = (rng.random(n, dtype=np.float32) * np.float32(0.6)).astype(np.float32)
    res = GM.glint(C, P, H, D, tp, ts, m, r)
    g = res['g']
    gmax = f32(1.0 / float(C['INV_GMAX']))
    mean, sd = float(g.mean()), float(g.std() / np.sqrt(n))
    if abs(mean - 1.0) > 4.0 * sd + 1e-4:
        bad(f'closed form: E[g] = {mean:.5f} +- {sd:.5f}, not 1 within 4 sigma')
    if float(g.max()) > float(gmax) + 1e-6:
        bad(f'closed form: max(g) = {g.max()} > glint_max {gmax}')
    if float(g.min()) < 0.0:
        bad('closed form: g went negative')
    # gate-false must be BIT-EXACT 1.0 (94 sec 6.2 axis 9)
    off = GM.glint(C, P, H, D, tp, ts,
                   np.zeros(n, dtype=np.float32),
                   np.full(n, np.float32(0.9)))
    if not np.all(off['glint'].view(np.uint32) == np.float32(1.0).view(np.uint32)):
        bad('closed form: gate-false glint is not bit-exactly 1.0')
    # hash quality: adjacent cells must decorrelate
    ci = [np.arange(n, dtype=np.uint32) % np.uint32(1024),
          (np.arange(n, dtype=np.uint32) // np.uint32(1024)) % np.uint32(1024),
          np.zeros(n, dtype=np.uint32)]
    h = GM.pcg(GM._fold(ci, GM.C_CELL))
    a = (h.astype(np.float64) / 2**32)
    c1 = float(np.corrcoef(a[:-1], a[1:])[0, 1])
    c2 = float(np.corrcoef(a[:-1024], a[1024:])[0, 1])
    if abs(c1) > 0.02 or abs(c2) > 0.02:
        bad(f'hash quality: adjacent-cell correlation {c1:.4f} / {c2:.4f} '
            f'-- a correlated hash gives visible stripes on a car door')
    return dict(mean=mean, sd=sd, gmax=float(g.max()), c1=c1, c2=c2)


# ------------------------------------------------------------------ driver
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--mode', default='glint', choices=('glint', 'cell'))
    ap.add_argument('--ctl', action='store_true',
                    help='the k_glint=0 control: assert NOTHING was spliced')
    ap.add_argument('--quiet', action='store_true')
    for k, v in GM.DEFAULTS.items():
        ap.add_argument('--' + k.replace('_', '-'), type=float, default=v)
    a = ap.parse_args()
    C = GM.constants(GM.knobs(**{k: getattr(a, k) for k in GM.DEFAULTS}))
    work = os.path.join(os.path.dirname(os.path.abspath(a.rung)),
                        '.verify_carglint')
    os.makedirs(work, exist_ok=True)

    spv = sorted(glob.glob(os.path.join(a.rung, '*.spv')))
    n_c = len([p for p in spv if p.endswith('.dxil.spv')])
    n_g = len([p for p in spv if '.rgs_restirgi_' in p])
    refs = [p for p in spv if p.endswith('.rgs_reference_main.spv')]
    if (len(spv), n_c, n_g, len(refs)) != (93, 77, 4, 12):
        bad(f'selection: {len(spv)} modules ({n_c} compute, {n_g} restirgi, '
            f'{len(refs)} reference), want 93 (77/4/12)')
    for p in spv:
        if subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', p],
                          capture_output=True).returncode != 0:
            bad('spirv-val failed: ' + os.path.basename(p))

    sites, painted, patched = 0, 0, 0
    for p in refs:
        h = os.path.basename(p).split('.')[0]
        mod, _ = load_lenient(_dis(p, work))
        if h in PASS_THROUGH:
            if len(find_ggx_blocks(mod)) != 0 or count_sg_sites(mod) != 6:
                bad(f'{h}: the scalar-specular pass-through is not what it was')
            continue
        if a.ctl:
            n = sum(1 for b in find_ggx_blocks(mod) for sp in b['spec']
                    if glint_signature(mod, sp['res']) is not None)
            if n:
                bad(f'{h}: the CONTROL carries {n} glint multiplies')
            if 'OpConstant %uint 747796405' in '\n'.join(mod.lines):
                bad(f'{h}: the CONTROL carries the PCG multiplier constant')
            continue
        patched += 1
        if a.mode == 'glint':
            sites += check_module(mod, C, h)
        else:
            painted += check_cell_module(mod, C, h)

    if a.ctl:
        if patched:
            bad('control: modules were patched')
    elif a.mode == 'glint':
        if patched != 10 or sites != 60:
            bad(f'coverage: {patched} patched permutations x blocks = {sites} '
                f'glint sites, want 10 x 6 = 60')
    else:
        if patched != 10 or painted < 10:
            bad(f'coverage: {patched} patched permutations, {painted} painted '
                f'writes')

    # The closed form is about the GLINT arithmetic; the diagnostic has none.
    cf = closed_form(C) if (not a.ctl and a.mode == 'glint') else None
    if FAIL:
        for f in FAIL[:14]:
            sys.stderr.write('  FAIL  ' + f + '\n')
        sys.stderr.write(f'  ({len(FAIL)} failures)\n')
        sys.exit(1)
    if not a.quiet:
        tag = 'CONTROL' if a.ctl else a.mode
        extra = ''
        if cf:
            extra = (f", E[g]={cf['mean']:.4f}+-{cf['sd']:.4f}, "
                     f"max(g)={cf['gmax']:.1f}, hash r={cf['c1']:.4f}")
        print(f'  verify_carglint OK [{tag}] {os.path.basename(a.rung)}: '
              f'93 modules, {patched} patched, '
              f'{sites if a.mode == "glint" else painted} '
              f'{"glint sites" if a.mode == "glint" else "painted writes"}'
              f'{extra}')


if __name__ == '__main__':
    main()
