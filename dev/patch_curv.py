#!/usr/bin/env python3
"""curv -- curvature-driven skin scattering in the compute resolvers.

handoff/109.  Pre-integrated skin shading (Penner 2011) makes the diffuse
scattering width and the terminator's red shift scale with the surface
curvature 1/r.  The shipped terminator bleed (97 sec 3.4) uses ONE width for
all skin and says so out loud: *"the 0.35 band width is a stylization constant
... physically the band scales with curvature x d"*.  handoff/99 removed the
blocker -- P is reconstructed in-module and 99 sec 10.8 measured it in METRES
-- so curvature in real 1/m is now computable at the splice site.

THIS PATCHER RUNS ON ALREADY-PATCHED BYTES.  It is a post-processor over the
standing selection, not a re-emission of the skin ladder: it finds the bleed
block `patch_compute_skin.build_skin_c1` already emitted and rescales two of
its values.  That is deliberate -- the composed default carries earglow, the
6 mm floor and the glints in the raygens and half a dozen skin knobs in the
compute half, and none of it may move.

WHAT IS FOUND, STRUCTURALLY
---------------------------
1. `wpos_core.find_pos_chain` -- P = (cbv[reg0+12][69..72] . (x,y,depth,1))/w,
   the depth image at registers[1]+0, the two dispatch coords.  75 of 77.
2. `find_normal_decode` -- the module's own G-buffer normal decode,
       N = normalize(fetch(registers[1]+2, (x,y)).xyz - 0.5)
   anchored on the whole shape (fetch -> 3 extracts -> 3 `+ -0.5` ->
   v3 construct -> Dot -> InverseSqrt -> 3 FMul), never on the slot number.
   Census: exactly ONE such decode in each of those 75, all at (1, 2), all on
   the SAME coordinate pair as the depth fetch, same descriptor array, same
   image type, same LOD.
3. `find_bleed_blocks` -- the emitted bleed:
       bq  = NoL * (1/0.35)      <- the width
       t   = clamp(1 - bq, 0, 1)
       bw  = t * t               <- the amplitude weight
   with bw consumed by EXACTLY three instructions (`bw*0.336`, `bw*0.101`,
   `nd0*bw`), the third being 78's luminance-hold delta.  Census: 150 blocks
   over 77 modules, 3 consumers in every one.

WHAT IS EMITTED
---------------
Once per module, at a hoist line proved to dominate every bleed site:

    kappa = 0.5 * ( |N(x+1,y)-N| / |P(x+1,y)-P|  +  |N(x,y+1)-N| / |P(x,y+1)-P| )
    s     = clamp(1 + g*(clamp(kappa, 0.5, 40)/10 - 1), 0.3, 2.0)
    s     = (|dPx|^2 < JUMP^2 && |dPy|^2 < JUMP^2) ? s : 1.0

Then, at each bleed site, TWO instructions:

    bq' = bq / s      (widen the band:  W -> W*s)
    bw' = bw * s      (scale the shift: w -> w*s)

and one `replace_all_uses` each.  Rescaling `bw` reaches all three consumers,
so 78's luminance hold is rescaled in lockstep and stays algebraically exact
for every s -- `curv_model.luminance_hold_residual` measures 9e-8 worst case
over 4 colours x 5 s x 7 NoL.  The specular is not touched: `bw` has no
specular consumer, by census.

The `c1` term takes NO curvature.  It has no width or wrap parameter -- it has
two lobe SHARPNESS exponents (5*r(n), 97 sec 3.2), and the one that survives
in the standing base is the grazing-VIEW lobe alpha_r, whose physical driver
is path length at grazing view, not curvature.  The grazing-LIGHT lobe alpha_f
is the one a curvature argument could touch, and `-deep` switched it off
(rho_f = 1.0, 97 sec 3.5), so it multiplies by zero.  Stated in 109 sec 4.

GOTCHAS THIS FILE OBEYS
-----------------------
* 12  -- every detector runs to completion before the first replace_all_uses.
* 5/10 -- the normal decode is anchored on its whole shape and cross-checked
          against the depth fetch's own coordinate ids, not on a slot number.
* the `uconst` duplicate-declaration trap -- one memo dict per module.
* "assert the site count, not the file hash" -- the report carries per-module
  site counts and build_curv.sh fails on any drift from CENSUS.

Usage:
    python3 dev/patch_curv.py <mod.spvasm> --outdir DIR [--gain 1.0]
        [--tier bleed|vis] [--kappa0 10] [--jump 0.05] [--no-guard]
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die, replace_all_uses
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
import wpos_core as W
import cfg_dom
import curv_model as CM

# ---------------------------------------------------------------- declines
# BY NAME, with the reason, exactly as handoff/99's patcher does.  A decline
# anywhere else is a coverage failure and build_curv.sh treats it as one.
#   99bb7c2698997b2a -- the big GI resolver.  No view vector (97 sec 1.5) and
#                       no P reconstruction (99 sec 1), so there is no metric
#                       length to divide the normal difference by.  Carries 6
#                       bleed blocks, all left at the shipped 0.35.
#   ab0bc2fee876d489 -- the reservoir / sample-index pass (46 sec 12): writes
#                       v4uint, not radiance, and has no P chain either.
#                       Carries 2 bleed blocks, left alone.
KNOWN_DECLINE = {'ab0bc2fee876d489', '99bb7c2698997b2a'}

# Census of the standing base
# gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense.
# Measured, not assumed; build_curv.sh fails on any drift.
CENSUS = dict(modules=77, patched_modules=75,
              bleed_sites_total=150, bleed_sites_reached=142,
              bleed_sites_declined=8,
              c1_sites_total=173,
              writes=150,                      # 2 per patched module (99 sec 2)
              normal_slot=[1, 2], depth_slot=[1, 0],
              matrix_members=[69, 70, 71, 72], cbv_slot=[0, 12])

# The bleed's shipped reciprocal band width, 1/0.35, as spirv-dis prints it.
# This is the ONE literal anchor in the file and it is the feature's own
# emitted constant, not a guess about the game (patch_compute_skin: invb).
INVB_TOK = '%float_2_85714293'
NEG_HALF = '%float_n0_5'

DEFAULTS = dict(kappa0=CM.KAPPA0, kmin=CM.KAPPA_MIN, kmax=CM.KAPPA_MAX,
                smin=CM.S_MIN, smax=CM.S_MAX, jump=CM.JUMP, step=1,
                guard=True, vis_lo=0.25, vis_hi=2.0)


# ------------------------------------------------------------- detectors
def find_normal_decode(mod, D):
    """The module's own `normalize(fetch(N).xyz - 0.5)`, whole shape.

    Returns dict(img, coord, lod, fetch_line, n=[3 ids], nline) or None.
    The shape is matched end to end so a decode of some OTHER v4float fetch
    (albedo, roughness) cannot satisfy it: only the normal target is biased by
    -0.5 on three components and then normalised.
    """
    hits = []
    for idt, (line, txt) in D.items():
        m = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$', txt)
        if not m:
            continue
        img, coord, lod = m.groups()
        ex = {}
        for i2, (_l2, t2) in D.items():
            me = re.match(r'OpCompositeExtract %float ' + re.escape(idt)
                          + r' (\d)\s*$', t2)
            if me:
                ex[int(me.group(1))] = i2
        if not all(k in ex for k in (0, 1, 2)):
            continue
        sub = {}
        for k in (0, 1, 2):
            want = 'OpFAdd %float ' + ex[k] + ' ' + NEG_HALF
            for i3, (_l3, t3) in D.items():
                if t3.strip() == want:
                    sub[k] = i3
        if len(sub) != 3:
            continue
        cons = [i for i, (_l, t) in D.items()
                if t.strip() == ('OpCompositeConstruct %v3float '
                                 + sub[0] + ' ' + sub[1] + ' ' + sub[2])]
        if not cons:
            continue
        dots = [i for i, (_l, t) in D.items()
                if re.match(r'OpDot %float (%\w+) (%\w+)\s*$', t)
                and set(re.findall(r'%\w+', t)[1:]) <= set(cons)]
        if not dots:
            continue
        rsq = [i for i, (_l, t) in D.items()
               if any(re.match(r'OpExtInst %float %\w+ InverseSqrt '
                               + re.escape(d) + r'\s*$', t) for d in dots)]
        if not rsq:
            continue
        muls = {}
        for k in (0, 1, 2):
            for i4, (_l4, t4) in D.items():
                if t4.strip() in ('OpFMul %float ' + rsq[0] + ' ' + sub[k],
                                  'OpFMul %float ' + sub[k] + ' ' + rsq[0]):
                    muls[k] = i4
        if len(muls) != 3:
            continue
        hits.append(dict(img=img, coord=coord, lod=lod, fetch_line=line,
                         n=[muls[k] for k in (0, 1, 2)],
                         nline=max(D[muls[k]][0] for k in (0, 1, 2))))
    if not hits:
        return None
    if len(hits) > 1:
        # Two normal decodes would make "which normal" a guess (GOTCHAS: the
        # wrong-sibling failure).  Census says exactly one in all 75.
        die('%s: %d normal decodes, expected exactly 1' % (mod.name, len(hits)))
    return hits[0]


def find_bleed_blocks(mod, D):
    """Every emitted terminator-bleed block, whole shape (97 sec 3.4).

    [{bq, bq_line, nol, bw, bw_line, bw_uses}], sorted by line.
    """
    out = []
    for idt, (line, txt) in D.items():
        m = (re.match(r'OpFMul %float (%\w+) ' + re.escape(INVB_TOK) + r'\s*$', txt)
             or re.match(r'OpFMul %float ' + re.escape(INVB_TOK) + r' (%\w+)\s*$', txt))
        if not m:
            continue
        nol = m.group(1)
        sub = [i for i, (_l, t) in D.items()
               if t.strip() == 'OpFSub %float %float_1 ' + idt]
        if len(sub) != 1:
            continue
        cl = [i for i, (_l, t) in D.items()
              if re.match(r'OpExtInst %float %\w+ NClamp ' + re.escape(sub[0])
                          + r' \S+ %float_1\s*$', t)]
        if len(cl) != 1:
            continue
        bw = [i for i, (_l, t) in D.items()
              if t.strip() == 'OpFMul %float ' + cl[0] + ' ' + cl[0]]
        if len(bw) != 1:
            continue
        out.append(dict(bq=idt, bq_line=line, nol=nol, bw=bw[0],
                        bw_line=D[bw[0]][0]))
    return sorted(out, key=lambda d: d['bq_line'])


def hoist_line(mod, D, ctx, nd):
    """The line to emit the curvature block after.

    Every input the block reads must be defined at or above it; the block's
    result must dominate every bleed site.  Both are CHECKED, not assumed:
    the caller runs cfg_dom.dominates against each site and dies otherwise.
    """
    leaves = list(W.pos_leaves(ctx)) + [nd['img'],
                                        ctx['coord_xy'][0], ctx['coord_xy'][1]]
    lines = [D[i][0] for i in leaves if i in D]
    lines.append(max(D[p][0] for p in ctx['p']))     # P itself
    h = max(lines)
    s = mod.lines[h].strip()
    if s.startswith('OpSelectionMerge') or s.startswith('OpLoopMerge'):
        die('%s: hoist line %d is a merge instruction' % (mod.name, h + 1))
    return h


# -------------------------------------------------------------- emitter
class Emit:
    """Append-only instruction builder with a per-module constant memo."""

    def __init__(self, mod, consts, uc):
        self.mod, self.consts, self.uc = mod, consts, uc
        self.ins = []

    def C(self, v):
        nid, c = self.mod.const(v)
        if c:
            self.consts.append(c)
        return nid

    def U(self, n):
        key = ('u', int(n))
        if key in self.uc:
            return self.uc[key]
        nid, c = self.mod.uconst(n)
        if c:
            self.consts.append(c)
        self.uc[key] = nid
        return nid

    def E(self, op, ty, *a):
        i = self.mod.new_id()
        self.ins.append('        %s = %s %s %s' % (i, op, ty, ' '.join(a)))
        return i

    def _ext(self, name, ty, *a):
        i = self.mod.new_id()
        self.ins.append('        %s = OpExtInst %s %s %s %s'
                        % (i, ty, self.mod.glsl, name, ' '.join(a)))
        return i


def _emit_normal_at(em, nd, coord):
    """Re-issue the module's own decode at `coord`.  11 instructions."""
    ac = em.E('OpAccessChain', em.ptr_n, em.arr_n, em.slot_n)
    ld = em.E('OpLoad', em.imgty, ac)
    f = em.E('OpImageFetch', '%v4float', ld, coord, 'Lod ' + nd['lod'])
    e = [em.E('OpCompositeExtract', '%float', f, str(k)) for k in range(3)]
    s = [em.E('OpFAdd', '%float', e[k], NEG_HALF) for k in range(3)]
    v = em.E('OpCompositeConstruct', '%v3float', *s)
    d = em.E('OpDot', '%float', v, v)
    r = em._ext('InverseSqrt', '%float', d)
    return [em.E('OpFMul', '%float', r, s[k]) for k in range(3)]


def _emit_pos_at(em, ctx, rows, coord_x, coord_y, depth_ld, lod, comp):
    """P at an arbitrary integer texel, reusing pre-loaded matrix rows."""
    co = em.E('OpCompositeConstruct', '%v2uint', coord_x, coord_y)
    f = em.E('OpImageFetch', '%v4float', depth_ld, co, 'Lod ' + lod)
    z = em.E('OpCompositeExtract', '%float', f, str(comp))
    fx = em.E('OpConvertUToF', '%float', coord_x)
    fy = em.E('OpConvertUToF', '%float', coord_y)
    outs = []
    for c in range(4):
        t1 = em.E('OpFMul', '%float', rows[0][c], fx)
        t2 = em._ext('Fma', '%float', rows[1][c], fy, t1)
        t3 = em._ext('Fma', '%float', rows[2][c], z, t2)
        outs.append(em.E('OpFAdd', '%float', t3, rows[3][c]))
    p = [em.E('OpFDiv', '%float', outs[c], outs[3]) for c in range(3)]
    return p, co


def emit_curvature(mod, cfg, ctx, nd, site_line, consts, uc, knobs, ins_out):
    """Emit the estimator at `site_line`.  Returns dict(s, kappa, valid, ...).

    Contract, and every clause of it is checked by the caller before the call:
      * `ctx['coord_xy']`, `pos_leaves(ctx)` and `nd['img']` dominate the line.
      * The centre P is `ctx['p']` when that dominates, else a wpos_core
        site-local refetch (the 99 sec 4 emitter, used verbatim).
      * The centre N is the module's OWN decode when it dominates, else the
        same decode re-issued here.  Never the post-phi shading normal: a phi
        is not re-issuable at a neighbour texel, and mixing a phi centre with
        a raw neighbour would fabricate curvature on the phi's other arm.
    """
    em = Emit(mod, consts, uc)
    em.ins = ins_out
    imgd = ctx['img']
    nparts = W._img_parts(W._chain_of(W.defs_index(mod), nd['img']))
    if nparts is None:
        die('%s: normal image chain is not OpLoad(OpAccessChain)' % mod.name)
    em.imgty, em.ptr_n = nparts['imgty'], nparts['ptrty']
    em.arr_n, em.slot_n = nparts['arr'], nparts['slot']
    n0 = len(ins_out)

    step = em.U(knobs['step'])
    cx, cy = ctx['coord_xy']
    cx1 = em.E('OpIAdd', '%uint', cx, step)
    cy1 = em.E('OpIAdd', '%uint', cy, step)

    # --- the depth image, loaded once for both neighbours
    dac = em.E('OpAccessChain', imgd['ptrty'], imgd['arr'], imgd['slot'])
    dld = em.E('OpLoad', imgd['imgty'], dac)

    # --- the four matrix rows, loaded once for both neighbours
    rows = []
    for m in ctx['mat']:
        ac = em.E('OpAccessChain', '%_ptr_Uniform_v4float', ctx['cbv'],
                  '%uint_0', em.U(m))
        ld = em.E('OpLoad', '%v4float', ac)
        # rows[i][c] = component c of matrix member ctx['mat'][i], exactly
        # the indexing wpos_core._emit_refetch uses.
        rows.append([em.E('OpCompositeExtract', '%float', ld, str(k))
                     for k in range(4)])

    # --- centre P
    refetched = False
    if all(cfg.dominates_line(i, site_line) for i in ctx['p']):
        pc = ctx['p']
    else:
        pc = W.emit_world_pos(mod, cfg, ctx, site_line, em.ins, uc=uc)
        refetched = True

    # --- centre N
    if all(cfg.dominates_line(i, site_line) for i in nd['n']):
        nc = nd['n']
        n_reused = True
    else:
        co_c = em.E('OpCompositeConstruct', '%v2uint', cx, cy)
        nc = _emit_normal_at(em, nd, co_c)
        n_reused = False

    dp2, dn2 = [], []
    for coord_x, coord_y in ((cx1, cy), (cx, cy1)):
        pn, co = _emit_pos_at(em, ctx, rows, coord_x, coord_y, dld,
                              nd['lod'], ctx['depth']['comp'])
        nn = _emit_normal_at(em, nd, co)
        dp = [em.E('OpFSub', '%float', pn[k], pc[k]) for k in range(3)]
        dn = [em.E('OpFSub', '%float', nn[k], nc[k]) for k in range(3)]
        vp = em.E('OpCompositeConstruct', '%v3float', *dp)
        vn = em.E('OpCompositeConstruct', '%v3float', *dn)
        dp2.append(em.E('OpDot', '%float', vp, vp))
        dn2.append(em.E('OpDot', '%float', vn, vn))

    # kappa_axis = sqrt(|dN|^2 / max(|dP|^2, eps)) -- one Sqrt, not two, and
    # the guard then compares SQUARED lengths, so no extra root is needed.
    eps2 = em.C(1e-12)
    ka = []
    for k in range(2):
        d = em._ext('NMax', '%float', dp2[k], eps2)
        r = em.E('OpFDiv', '%float', dn2[k], d)
        ka.append(em._ext('Sqrt', '%float', r))
    ksum = em.E('OpFAdd', '%float', ka[0], ka[1])
    kappa = em.E('OpFMul', '%float', ksum, em.C(0.5))
    kc = em._ext('NClamp', '%float', kappa, em.C(knobs['kmin']),
                 em.C(knobs['kmax']))

    # s = clamp(1 + g*(kappa/kappa0 - 1), smin, smax)
    q0 = em.E('OpFMul', '%float', kc, em.C(1.0 / knobs['kappa0']))
    one = em.C(1.0)
    q1 = em.E('OpFSub', '%float', q0, one)
    q2 = em.E('OpFMul', '%float', q1, em.C(knobs['gain']))
    q3 = em.E('OpFAdd', '%float', one, q2)
    sraw = em._ext('NClamp', '%float', q3, em.C(knobs['smin']),
                   em.C(knobs['smax']))

    # Silhouette fallback.  OpFOrdLessThan is FALSE for NaN, so a NaN neighbour
    # (an out-of-bounds tap, a degenerate divide) also falls back.  The
    # fallback value is 1.0 == the shipped constant, by construction.
    valid = None
    s = sraw
    if knobs['guard']:
        j2 = em.C(knobs['jump'] * knobs['jump'])
        bx = em.E('OpFOrdLessThan', '%bool', dp2[0], j2)
        by = em.E('OpFOrdLessThan', '%bool', dp2[1], j2)
        valid = em.E('OpLogicalAnd', '%bool', bx, by)
        s = em.E('OpSelect', '%float', valid, sraw, one)
    return dict(s=s, kappa=kc, valid=valid, refetched=refetched,
                n_reused=n_reused, one=one, n_ins=len(em.ins) - n0)


# ------------------------------------------------------------- tier: bleed
def build_curv_bleed(mod, cfg, knobs):
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    D = W.defs_index(mod)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        die('%s: no P chain (99 sec 1)' % mod.name)
    nd = find_normal_decode(mod, D)
    if nd is None:
        die('%s: no normal G-buffer decode' % mod.name)

    # GOTCHAS 10 / 5: the normal fetch must read the SAME texel coordinate the
    # depth fetch does, or "the neighbour" means two different pixels.
    mco = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$',
                   D[nd['coord']][1])
    if not mco or mco.groups() != tuple(ctx['coord_xy']):
        die('%s: normal fetch coordinate is not the depth fetch coordinate'
            % mod.name)
    if nd['lod'] != ctx['depth']['lod']:
        die('%s: normal fetch LOD differs from the depth fetch LOD' % mod.name)

    sites = find_bleed_blocks(mod, D)
    if not sites:
        die('%s: no terminator-bleed block found (is this the right base?)'
            % mod.name)

    # ---- ALL detection is finished above this line (GOTCHAS 12) ----------
    fs, fe = W.find_function_span(mod)
    h = hoist_line(mod, D, ctx, nd)
    for st in sites:
        if not cfg_dom.dominates(mod, fs, fe, h, st['bq_line']):
            die('%s: hoist line %d does not dominate bleed site at %d'
                % (mod.name, h + 1, st['bq_line'] + 1))

    # bw's consumer census, before anything is rewritten.
    for st in sites:
        u = uses_of(mod, st['bw'])
        st['bw_uses'] = len(u)
        if len(u) != 3:
            die('%s: bleed weight %s has %d consumers, expected 3 '
                '(0.336, 0.101 and 78\'s luminance delta)'
                % (mod.name, st['bw'], len(u)))
        if len(uses_of(mod, st['bq'])) != 1:
            die('%s: band argument %s has %d consumers, expected 1'
                % (mod.name, st['bq'], len(uses_of(mod, st['bq']))))

    ins = []
    # The block is INSERTED AFTER line `h`, so the line its instructions
    # actually occupy is `h + 1`: that is the line dominance must be tested
    # against, or P -- whose own definition is usually the thing that fixed
    # `h` -- reads as not dominating itself and triggers a pointless refetch.
    # `h + 1` is always in the same basic block as `h` (a block ends with a
    # terminator, so there is at least one instruction between `h` and the
    # next OpLabel).
    cur = emit_curvature(mod, cfg, ctx, nd, h + 1, consts, uc, knobs, ins)
    edits.append((h, ins))
    s = cur['s']

    for st in sites:
        i1 = mod.new_id()
        edits.append((st['bq_line'],
                      ['        %s = OpFDiv %%float %s %s' % (i1, st['bq'], s)]))
        n1 = replace_all_uses(mod, st['bq'], i1, st['bq_line'])
        i2 = mod.new_id()
        edits.append((st['bw_line'],
                      ['        %s = OpFMul %%float %s %s' % (i2, st['bw'], s)]))
        n2 = replace_all_uses(mod, st['bw'], i2, st['bw_line'])
        st.update(width_rewrites=n1, amp_rewrites=n2, s_id=s,
                  bq_new=i1, bw_new=i2)
        if n1 != 1 or n2 != 3:
            die('%s: rewrote %d width / %d amplitude uses, expected 1 / 3'
                % (mod.name, n1, n2))

    rep = dict(tier='bleed', gain=knobs['gain'], kappa0=knobs['kappa0'],
               kmin=knobs['kmin'], kmax=knobs['kmax'], smin=knobs['smin'],
               smax=knobs['smax'], jump=knobs['jump'], step=knobs['step'],
               guard=bool(knobs['guard']),
               hoist_line=h + 1, curv_instructions=cur['n_ins'],
               centre_normal_reused=cur['n_reused'],
               centre_pos_refetched=cur['refetched'],
               bleed_sites=len(sites),
               sites=[dict(bq_line=x['bq_line'] + 1, bw_line=x['bw_line'] + 1,
                           bw_uses=x['bw_uses']) for x in sites],
               matrix=ctx['mat'], cbv_slot=list(ctx['cbv_slot']),
               depth_slot=list(ctx['img_slot']),
               normal_slot=list(W._pc_slot(D, nd['img'])),
               p=list(ctx['p']))
    return consts, edits, rep


# --------------------------------------------------------------- tier: vis
def build_curv_vis(mod, cfg, writes, knobs):
    """Paint s as a blue(flat) -> green -> red(tight) ramp on class-1 pixels.

    The paint REPLACES the class-1 texel with `ramp(s) * clamp(Y, lo, hi)`,
    where Y is the pixel's own Rec.709 luminance.  Hue is therefore a pure
    function of kappa -- readable independently of the shading, which is the
    whole point of the rung -- while the brightness window keeps the frame
    exposed.  That is a deliberate departure from 94's hunt-paint multiply
    (40 sec 3): a multiply would put the shading back into the colour.

    Pixels where the silhouette guard fired are painted WHITE, so "no reading"
    is never confusable with a ramp colour.
    """
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    D = W.defs_index(mod)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        die('%s: no P chain' % mod.name)
    nd = find_normal_decode(mod, D)
    if nd is None:
        die('%s: no normal decode' % mod.name)
    leaves = W.pos_leaves(ctx) + [nd['img']]

    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((ins_line, pre_ins))
    cf = None

    done, skipped, refetched, reused = [], [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float'})
            continue
        if any(not cfg.dominates_line(x, w['line']) for x in leaves):
            skipped.append({'line': w['line'] + 1,
                            'why': 'curvature leaves do not dominate'})
            continue
        ins = []
        cls = shift
        if not cfg.dominates_line(dom_id, w['line']):
            if cf is None:
                cf = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line'])
                   for x in class_fetch_inputs(cf)):
                skipped.append({'line': w['line'] + 1,
                                'why': 'class refetch inputs do not dominate'})
                continue
            cls = emit_class_value(mod, cf, ins)
        cur = emit_curvature(mod, cfg, ctx, nd, w['line'], consts, uc,
                             knobs, ins)
        if cur['refetched']:
            refetched.append(w['line'] + 1)
        if cur['n_reused']:
            reused.append(w['line'] + 1)
        em = Emit(mod, consts, uc)
        em.ins = ins
        one = cur['one']
        # t = (s - smin) / (smax - smin)
        t0 = em.E('OpFSub', '%float', cur['s'], em.C(knobs['smin']))
        t = em.E('OpFMul', '%float', t0,
                 em.C(1.0 / (knobs['smax'] - knobs['smin'])))
        omt = em.E('OpFSub', '%float', one, t)
        g0 = em.E('OpFMul', '%float', t, omt)
        gmid = em.E('OpFMul', '%float', g0, em.C(4.0))
        ramp = [t, gmid, omt]
        # brightness = clamp(Rec.709(texel), lo, hi)
        lr = em.E('OpFMul', '%float', w['comps'][0], em.C(0.2126))
        lg = em.E('OpFMul', '%float', w['comps'][1], em.C(0.7152))
        lb = em.E('OpFMul', '%float', w['comps'][2], em.C(0.0722))
        la = em.E('OpFAdd', '%float', lr, lg)
        lum = em.E('OpFAdd', '%float', la, lb)
        br = em._ext('NClamp', '%float', lum, em.C(knobs['vis_lo']),
                     em.C(knobs['vis_hi']))
        col = [em.E('OpFMul', '%float', ramp[k], br) for k in range(3)]
        if cur['valid'] is not None:
            wht = em.E('OpFMul', '%float', br, one)
            col = [em.E('OpSelect', '%float', cur['valid'], col[k], wht)
                   for k in range(3)]
        is_skin = em.E('OpIEqual', '%bool', cls, em.U(1))
        newc = [em.E('OpSelect', '%float', is_skin, col[k], w['comps'][k])
                for k in range(3)]
        nt = em.E('OpCompositeConstruct', '%v4float', newc[0], newc[1],
                  newc[2], w['comps'][3])
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                      r'\g<1>' + nt, mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die('%s: no radiance image write reachable for the diagnostic' % mod.name)
    return consts, edits, dict(
        tier='vis', gain=knobs['gain'], kappa0=knobs['kappa0'],
        smin=knobs['smin'], smax=knobs['smax'], jump=knobs['jump'],
        step=knobs['step'], guard=bool(knobs['guard']),
        writes=done, skipped=skipped, class_anchor=dom_id,
        centre_pos_refetched=refetched, centre_normal_reused=reused,
        matrix=ctx['mat'], cbv_slot=list(ctx['cbv_slot']),
        depth_slot=list(ctx['img_slot']),
        normal_slot=list(W._pc_slot(D, nd['img'])))


# ------------------------------------------------------------------ driver
def process(path, outdir, tier, knobs, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die('%s: no dxil identity' % os.path.basename(path))
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, dxil=mod.dxil)
    if problems:
        rep['module_warnings'] = problems
    if knobs['gain'] == 0.0:
        # THE CONTROL.  Nothing detected, nothing emitted, nothing rewritten:
        # the module is re-assembled from the untouched disassembly, which
        # build_curv.sh proves byte-neutral on all 77 base modules FIRST, so
        # this is a non-tautological identity.
        rep['curv'] = dict(tier=tier, gain=0.0, control=True,
                           bleed_sites=0, writes=[])
        return CS._emit(mod, outdir, target_env, rep)
    if mod.dxil in KNOWN_DECLINE:
        die('%s: declined by name -- %s' % (mod.name, mod.dxil))
    cfg = CFG(mod)
    if tier == 'bleed':
        consts, edits, rep['curv'] = build_curv_bleed(mod, cfg, knobs)
    elif tier == 'vis':
        consts, edits, rep['curv'] = build_curv_vis(
            mod, cfg, find_image_writes(mod), knobs)
    else:
        die('unknown tier %s' % tier)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--tier', default='bleed', choices=('bleed', 'vis'))
    ap.add_argument('--gain', type=float, default=1.0,
                    help='0 = the byte-identical control (emits nothing); '
                         '1 = clamp(kappa/10, 0.3, 2.0); 2 = curv-hi')
    ap.add_argument('--kappa0', type=float, default=DEFAULTS['kappa0'])
    ap.add_argument('--kmin', type=float, default=DEFAULTS['kmin'])
    ap.add_argument('--kmax', type=float, default=DEFAULTS['kmax'])
    ap.add_argument('--smin', type=float, default=DEFAULTS['smin'])
    ap.add_argument('--smax', type=float, default=DEFAULTS['smax'])
    ap.add_argument('--jump', type=float, default=DEFAULTS['jump'],
                    help='metres; a neighbour |dP| above this is a silhouette')
    ap.add_argument('--step', type=int, default=DEFAULTS['step'],
                    help='neighbour offset in texels (the brief says 1)')
    ap.add_argument('--no-guard', action='store_true',
                    help='DECOY: drop the silhouette fallback. verify_curv.py '
                         'must reject the result.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    knobs = dict(DEFAULTS)
    knobs.update(gain=a.gain, kappa0=a.kappa0, kmin=a.kmin, kmax=a.kmax,
                 smin=a.smin, smax=a.smax, jump=a.jump, step=a.step,
                 guard=not a.no_guard)
    if a.kappa0 <= 0 or a.smax <= a.smin or a.kmax <= a.kmin or a.step < 1:
        die('bad knobs')
    reps = [process(p, a.outdir, a.tier, knobs, do_rt=not a.no_roundtrip_check)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
