#!/usr/bin/env python3
"""
patch_ms_ggx.py -- multi-scatter GGX energy compensation (`23` T2.1), spliced
into the path-tracing raygens' specular lobes.

    --strength S   0 = identity (bit-identical), 1 = full compensation
    --arms A       punctual | area | both   (default: both)

Usage (normally driven by dev/build_msggx.sh):
  python3 dev/patch_ms_ggx.py <dump>.spvasm... --outdir swaps.msggx --strength 1.0
  python3 dev/patch_ms_ggx.py <dump>.spvasm... --report

------------------------------------------------------------------ the maths

Single-scattering GGX drops the light that bounces off a second microfacet, so
rough surfaces come out too dark. Compensation multiplies the lobe by

    comp = 1 + strength * F0 * max(loss(alpha), 0)
    loss = j0*a + j1*a^2 + j2*a^3 + j3*a^4          (a = alpha = R*R)

`loss` is the measured shortfall of *this game's* lobe, integrated by
`dev/fit_ms_ggx.py` and normalized against the lobe's own alpha->0 limit
(exactly 0.5 -- see `dev/MS_GGX_NOTES.md` §2). Two things about it matter:

  * It is NOT a textbook Kulla-Conty / Lazarov fit. The game's `Vis` uses the
    SUM of the two Smith-Schlick G1 denominators where a correct separable
    Smith uses their PRODUCT, which over-brightens at high roughness and
    accidentally recovers about half the lost energy already. A published fit
    spliced here would roughly DOUBLE-compensate.
  * It is alpha-only, deliberately. The same sum-vs-product substitution also
    costs up to 28% at grazing angles, which is larger than the roughness
    error -- but that is a different defect, and compensating it would re-light
    every grazing surface in the game. Excluded on purpose; see the notes.

Every term carries a factor of alpha, so `loss` is identically 0 at alpha = 0
and `comp` is exactly 1.0 there regardless of fit error.

At --strength 0 every coefficient is exactly 0.0, so the Horner chain yields
0.0, `NMax(0,0)` is 0.0, `comp` is `F0*0 + 1` = 1.0, and `spec * 1.0` is `spec`
for every finite float -- the RESULT is identical to vanilla, though the SPIR-V
is not byte-identical (the instructions are still emitted, they just compute
the identity). Alpha is the module's own clamped R*R with R in [0.04, 1], so it
is always finite and the `0 * alpha` terms cannot produce a NaN.

------------------------------------------------------------------ the anchor

The GGX evaluator is located by its Schlick spherical-gaussian Fresnel fit,
whose two constants are mode-independent (GOTCHAS 4):

    %e  = OpFSub  %float %float_n6_98316002 (OpFMul VoH %float_5_55472994)
    %p  = OpExtInst Exp2 (OpFMul %e VoH)
    %om = OpFSub  %float %float_1 %p
    %F<c> = OpFAdd %float (OpFMul %om <F0_c>) %p        c = r,g,b
    %vd = OpFMul %float <Vis> <D>
    %spec_c = OpFMul %float %F<c> %vd                   <- the three to scale

F0 is read out of the `%om * F0_c` multiplies, so the per-channel mapping comes
from the module rather than from an assumption. `alpha` is read off the Vis
chain's own trailing `+ alpha`, and cross-checked against the `(1 - alpha/2)`
factor -- if the two disagree the block is not this lobe and is skipped.

------------------------------------------------------------------ two arms

GOTCHAS: `spv_0170` carries TWO structurally identical GGX evaluators, selected
by `(flags & 2) == 0`. Reading the wrong one is what produced (and for weeks
sustained) the E_ss blocker.

    punctual   Vis's NoL slot is NClamp(OpDot(N,L), 0, 1)
    area/tube  Vis's NoL slot is NClamp(OpPhi ...) -- a sphere/tube
               *illuminance* factor, not a cosine

Both are classified here by exactly that test, and both are patched by default.
The compensation is a function of alpha only, so it does not depend on what
occupies the NoL slot; and Cyberpunk is full of tube and sphere lights, so
patching only the punctual arm would brighten rough metal under a spotlight but
not under a neon strip -- which would read as a bug. `--arms` exists so the two
can still be A/B'd separately.
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import (apply_edits, roundtrip_check, replace_all_uses,
                             f32, f32s, die)
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

# Schlick spherical-gaussian fit, as printed by spirv-dis. Both are required:
# either alone appears elsewhere.
SG_A = '%float_5_55472994'
SG_B = '%float_n6_98316002'

# Measured shortfall of the game's own lobe, alpha-only at NoV=1.
# dev/fit_ms_ggx.py -- max abs err 0.0064, rms 0.0024 over alpha in [0,1].
LOSS_COEF = (-0.35581642, 0.66852058, 0.82793009, -0.40552339)


# ---------------------------------------------------------------- detection
def _fdef(mod, idtok):
    _, d = mod.find_def(idtok)
    return d or ''


def count_sg_sites(mod):
    """Every Schlick spherical-gaussian site, regardless of how it is consumed.

    Exists so that "no blocks found" can never be silent. Two of the twelve
    `rgs_reference_main` permutations (`40c6faab52a13874`, `ab7f1822eeb0331b`)
    carry six SG sites each that assemble a MONOCHROME specular --
    `p * Vis * D`, with no `1-p` lerp and no F0 anywhere in the lobe. Those are
    deliberately not patched: `comp` needs the lobe's own F0, and these modules
    have none in scope, so the only way to patch them would be to guess which
    of the module's two unrelated `+0.04` triples to borrow. That guess is
    exactly the failure GOTCHAS 10 is about. Both confirmed-live permutations
    (`d622fb9e`, `4270b745`) are the three-channel form and are patched.
    """
    n = 0
    for ln in mod.lines:
        # the OpConstant declaration mentions it too; count only USES
        if SG_B in ln and ' = OpConstant ' not in ln:
            n += 1
    return n


def find_ggx_blocks(mod):
    """Every `F*D*Vis` specular triple reachable from a Schlick SG Fresnel.

    Returns dicts with the three result ids to scale, their F0 ids, the shared
    Vis*D id, alpha, and the arm classification.
    """
    out = []
    for i, ln in enumerate(mod.lines):
        # %om = OpFSub %float %float_1 %p   where %p = Exp2(...)
        m = re.match(r'^\s*(%\w+)\s*=\s*OpFSub %float %float_1 (%\w+)\s*$', ln)
        if not m:
            continue
        om, p = m.groups()
        d = _fdef(mod, p)
        me = re.match(r'OpExtInst %float \S+ Exp2 (%\w+)\s*$', d)
        if not me:
            continue
        # the exponent must be the SG fit: (-6.983 - 5.555*VoH) * VoH
        d2 = _fdef(mod, me.group(1))
        m2 = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', d2)
        if not m2:
            continue
        d3 = _fdef(mod, m2.group(1))
        if SG_B not in d3 or SG_A not in _fdef(mod, re.findall(r'%\w+', d3)[-1]):
            continue

        # F_c = FAdd(FMul(om, F0_c), p), in source order r,g,b
        f0, fres = [], []
        for j in range(i + 1, min(i + 24, len(mod.lines))):
            mm = re.match(r'^\s*(%\w+)\s*=\s*OpFMul %float ' + re.escape(om)
                          + r' (%\w+)\s*$', mod.lines[j])
            if mm:
                f0.append((mm.group(1), mm.group(2)))
        for prod, c in f0:
            for j in range(i + 1, min(i + 32, len(mod.lines))):
                mm = re.match(r'^\s*(%\w+)\s*=\s*OpFAdd %float ' + re.escape(prod)
                              + r' ' + re.escape(p) + r'\s*$', mod.lines[j])
                if mm:
                    fres.append((mm.group(1), c))
                    break
        if len(fres) != 3:
            continue

        # spec_c = FMul(F_c, VisD) -- all three sharing the same second operand
        spec, visd = [], None
        for fid, c in fres:
            for j in range(i + 1, min(i + 40, len(mod.lines))):
                mm = re.match(r'^\s*(%\w+)\s*=\s*OpFMul %float ' + re.escape(fid)
                              + r' (%\w+)\s*$', mod.lines[j])
                if mm:
                    spec.append(dict(line=j, res=mm.group(1), f0=c))
                    visd = visd or mm.group(2)
                    break
        if len(spec) != 3 or len({s['res'] for s in spec}) != 3:
            continue

        info = _read_vis(mod, visd)
        if not info:
            continue
        info.update(schlick_line=i + 1, visd=visd, spec=spec)
        out.append(info)
    return out


def _read_vis(mod, visd):
    """Unpack `VisD = Vis * D` and read alpha + the NoL slot off the Vis chain.

        Vis = 0.25 / ((NoV + NoL) * (1 - alpha/2) + alpha)

    Returns None unless the whole shape matches AND the two independent
    readings of alpha agree -- a block that only half-matches is not this lobe.
    """
    m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, visd))
    if not m:
        return None
    for vis, dee in (m.groups(), m.groups()[::-1]):
        md = re.match(r'OpFDiv %float %float_0_25 (%\w+)\s*$', _fdef(mod, vis))
        if not md:
            continue
        den = md.group(1)
        ma = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', _fdef(mod, den))
        if not ma:
            continue
        prod, alpha = ma.groups()
        mp = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', _fdef(mod, prod))
        if not mp:
            continue
        for sm, omh in (mp.groups(), mp.groups()[::-1]):
            ms = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', _fdef(mod, sm))
            mo = re.match(r'OpFSub %float %float_1 (%\w+)\s*$', _fdef(mod, omh))
            if not (ms and mo):
                continue
            mh = re.match(r'OpFMul %float (%\w+) %float_0_5\s*$',
                          _fdef(mod, mo.group(1)))
            if not mh or mh.group(1) != alpha:      # the two alpha readings
                continue                            # must be the same id
            nov, nol = ms.groups()
            return dict(alpha=alpha, D=dee, vis=vis,
                        arm=_classify(mod, nov, nol), nov=nov, nol=nol)
    return None


def _classify(mod, nov, nol):
    """punctual vs area, by what feeds the Vis denominator's cosine slots.

    The punctual arm clamps a plain OpDot; the area arm clamps an OpPhi that
    resolves the tube/sphere illuminance factor. Both slots are checked because
    which of the two FAdd operands is NoV and which is NoL is not fixed by the
    disassembly order.
    """
    kinds = []
    for tok in (nov, nol):
        d = _fdef(mod, tok)
        m = re.match(r'OpExtInst %float \S+ (NClamp|NMin) (%\w+)', d)
        inner = _fdef(mod, m.group(2)) if m else d
        while re.match(r'OpExtInst %float \S+ (NMin|NMax) ', inner):
            inner = _fdef(mod, re.findall(r'%\w+', inner)[1])
        kinds.append('phi' if inner.startswith('OpPhi') else
                     'dot' if inner.startswith('OpDot') else 'other')
    return 'area' if 'phi' in kinds else 'punctual' if 'dot' in kinds else 'unknown'


# ------------------------------------------------------------------ splicing
def emit_comp(mod, blk, coef, consts):
    """comp = 1 + F0_c * max(loss(alpha), 0), applied to the three spec outs.

    Horner, so the polynomial costs 3 FMul + 3 FAdd regardless of degree, and
    every term keeps its factor of alpha -- loss(0) == 0 exactly.
    """
    a = blk['alpha']
    ins = []

    def cst(v):
        cid, decl = mod.const(v)
        if decl:
            consts.append(decl)
        return cid

    # j3*a + j2 -> *a + j1 -> *a + j0 -> *a
    acc = cst(coef[3])
    for c in (coef[2], coef[1], coef[0]):
        t = mod.new_id()
        ins.append(f"       {t} = OpFMul %float {acc} {a}")
        acc2 = mod.new_id()
        ins.append(f"       {acc2} = OpFAdd %float {t} {cst(c)}")
        acc = acc2
    loss = mod.new_id()
    ins.append(f"       {loss} = OpFMul %float {acc} {a}")
    # never darken below vanilla: the fit dips slightly negative near a=0.25
    lc = mod.new_id()
    ins.append(f"       {lc} = OpExtInst %float {mod.glsl} NMax {loss} %float_0")

    rewrites = []
    for s in blk['spec']:
        t = mod.new_id()
        ins.append(f"       {t} = OpFMul %float {s['f0']} {lc}")
        comp = mod.new_id()
        ins.append(f"       {comp} = OpFAdd %float {t} %float_1")
        nid = mod.new_id()
        ins.append(f"       {nid} = OpFMul %float {s['res']} {comp}")
        rewrites.append((s['res'], nid))

    # splice after the last of the three spec multiplies, then redirect every
    # later use of the originals to the compensated ids
    pos = max(s['line'] for s in blk['spec'])
    return pos, ins, rewrites


# -------------------------------------------------------------------- driver
def process(path, outdir, opts, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, _ = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    rep = dict(module=mod.name, ident=mod.ident)

    blocks = find_ggx_blocks(mod)
    rep['ggx_blocks'] = [dict(line=b['schlick_line'], arm=b['arm'],
                              alpha=b['alpha']) for b in blocks]
    rep['arms'] = {k: sum(1 for b in blocks if b['arm'] == k)
                   for k in ('punctual', 'area', 'unknown')}

    # A module with Fresnel sites but no matched blocks is either the known
    # monochrome variant or a detector regression. Never let that be silent.
    rep['sg_sites'] = count_sg_sites(mod)
    if rep['sg_sites'] and not blocks:
        rep['variant'] = 'scalar-specular (no F0 in lobe) -- skipped by design'
    elif rep['sg_sites'] and len(blocks) != rep['sg_sites']:
        rep['variant'] = (f"PARTIAL MATCH: {rep['sg_sites']} Fresnel sites but "
                          f"{len(blocks)} blocks -- detector may have regressed")

    want = {'both': ('punctual', 'area'), 'punctual': ('punctual',),
            'area': ('area',)}[opts.arms]
    targets = [b for b in blocks if b['arm'] in want]
    rep['patched_blocks'] = len(targets)

    if opts.report or not targets:
        rep['written'] = False
        return rep

    # strength folds into the coefficients: nothing to evaluate at runtime, and
    # strength=0 zeroes every term, so the splice is exactly identity.
    coef = tuple(f32(c * opts.strength) for c in LOSS_COEF)
    rep['coef'] = [f32s(c) for c in coef]

    consts, edits, rewrites = [], [], []
    for b in targets:
        pos, ins, rw = emit_comp(mod, b, coef, consts)
        edits.append((pos, ins))
        rewrites.extend((pos, o, n) for o, n in rw)

    # Rewrite uses BEFORE inserting, so the line indices the edits carry are
    # still the ones apply_edits() expects.
    nuses = 0
    for pos, old, new in rewrites:
        nuses += replace_all_uses(mod, old, new, pos)
    rep['uses_rewritten'] = nuses

    if do_rt:
        roundtrip_check(path, target_env)
    apply_edits(mod, consts, edits)
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv_out], capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)               # GOTCHAS: never leave a stale .spv
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['written'] = True
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()[:16]
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--strength', type=float, default=1.0,
                    help='0 = identity (bit-identical), 1 = full compensation')
    ap.add_argument('--arms', choices=('both', 'punctual', 'area'),
                    default='both')
    ap.add_argument('--report', action='store_true',
                    help='detect and print, write nothing')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    out = [process(p, a.outdir, a, do_rt=not a.no_roundtrip_check)
           for p in a.modules]
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
