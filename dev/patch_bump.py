#!/usr/bin/env python3
"""bump -- albedo-derived micro-normal on skin, in the 77 compute resolvers.

handoff/115.  Pores are not in the BVH, so no ray budget creates a pore
micro-shadow (33, 38 sec 0d).  The skin ALBEDO already carries them, painted
dark, and the shipped micro-shadowing (44 sec 3.4) reads that darkness as a
scalar occlusion.  This reads its GRADIENT as geometry: a height field
h = H * L(albedo) whose tangential slope tilts the shading normal,

    N' = normalize( N - H * grad_t L )

so every consumer of N -- the diffuse N.L, the specular N.H and N.V, the c1
lobes, the terminator bleed's NoL -- sees a pore as a tiny dent: darker on
its lit rim, brighter on its far rim, and BREAKING UP the oil highlight.

THIS PATCHER RUNS ON ALREADY-PATCHED BYTES, the same way `patch_curv` does:
it is a post-processor over the standing selection (the composed default
carries ear glow, glints and the ray queries in the raygens and half a dozen
skin terms plus 109's curvature estimator in the compute half, and none of it
may move).  The raygens are not touched at all.

WHAT IS FOUND, STRUCTURALLY
---------------------------
1. `wpos_core.find_pos_chain` -- P in metres, the depth image, the dispatch
   coords (99).  75 of 77; the two declines are 99's, by hash.
2. The pixel's OWN normal decode `normalize(fetch(N).xyz - 0.5)` at the
   pixel's own coordinate (`patch_earglow_di.find_pixel_normal`; the shipped
   compute half is 109's and carries two more decodes at +1 texel).
3. THE SHADING NORMAL, which is NOT the decode: in 68 of 75 modules the
   three decoded components feed one OpPhi each at the material-class
   switch's merge (case 4 substitutes a hair normal), and every lighting term
   reads the PHI.  That phi triple is the value rewritten.  In the other 7
   the class switch does not touch the normal and the decode is read
   directly; there the decode's own three ids are rewritten, EXCEPT for the
   two `OpFSub N(neighbour) - N` the curvature estimator emitted -- the
   curvature must be measured on the raw surface, not on the bump.
4. The ALBEDO fetch: walked from the Disney diffuse site through
   `find_diffuse_colour` and `_albedo_channel_root` to ONE v4float fetch
   whose xyz are squared (the sqrt-encoded A2B10G10R10 decode, 96 sec 1.2)
   at the pixel's own coordinate.  Never a slot number.
5. The class value (`acquire_class_shift`) -- the gate is `class == 1`.

WHAT IS EMITTED, once per module, directly after the phi group (or after
the raw decode):

    L(c)  = 0.2126*r^2 + 0.7152*g^2 + 0.0722*b^2      three albedo taps
    gx    = L(x+1,y) - L(x,y)      gy = L(x,y+1) - L(x,y)
    g'    = g * (1 - smoothstep(T0, T1, |g|))         the edge-kill band
    dPx   = P(x+1,y) - P           dPy = P(x,y+1) - P   two depth taps
    grad  = g'x/max(|dPx|^2,eps) dPx + g'y/max(|dPy|^2,eps) dPy
    t     = grad - (grad.N) N
    d     = -H * t ;  d *= min(1, DMAX / |d|)          the tilt clamp
    N'    = normalize(N + d)
    valid = |dPx|^2 < J^2 && |dPy|^2 < J^2              109's guard
    N''_k = select(valid && class==1, N'_k, N_k)

and every use of N_k below the site now reads N''_k.  H = 0 emits NOTHING
(the byte-identical control).  The depth taps read the SAME coordinate ids
as the albedo taps, so gx and dPx are measured between the same two texels.

GOTCHAS THIS FILE OBEYS
-----------------------
* 12  -- every detector runs to completion before the first rewrite.
* 5/10 -- nothing is anchored on a slot number or an SSA id.
* the `uconst` duplicate trap -- one memo dict per module.
* "assert the site count, not the file hash" -- per-module counts in the
  report; build_bump.sh fails on any drift from CENSUS.

Usage:
    python3 dev/patch_bump.py <mod.spvasm> --outdir DIR [--height 0.010]
        [--tier feature|vis] [--t0 0.05] [--t1 0.12] [--dmax 0.5]
        [--jump 0.05] [--step 1] [--no-guard] [--no-band]
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
from patch_curv import Emit, _emit_normal_at, NEG_HALF
import wpos_core as W
import bump_model as BM

# BY NAME, with the reason -- the same two 99/109 decline.
#   99bb7c2698997b2a -- the big GI resolver: no P reconstruction, so no metric
#                       length to convert a luma gradient into a slope.
#   ab0bc2fee876d489 -- the reservoir / sample-index pass: v4uint writes, no P.
KNOWN_DECLINE = {'ab0bc2fee876d489', '99bb7c2698997b2a'}

# Census of the standing base
# gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll
# (compute half = 109's curv).  Measured; build_bump.sh fails on any drift.
CENSUS = dict(modules=77, patched_modules=75,
              phi_modules=68, raw_modules=7,
              writes=150,                       # 2 per patched module
              normal_slot=[1, 2], depth_slot=[1, 0], albedo_slot=[1, 1],
              matrix_members=[69, 70, 71, 72], cbv_slot=[0, 12])

DEFAULTS = dict(height=BM.HEIGHT, t0=BM.T0, t1=BM.T1, dmax=BM.DMAX,
                jump=BM.JUMP, eps=BM.EPS, step=1, guard=True, band=True,
                vis_lo=0.25, vis_hi=2.0)

REC709 = (0.2126, 0.7152, 0.0722)


# ------------------------------------------------------------- detectors
def normal_decodes(mod, D):
    """Every `normalize(fetch(N).xyz - 0.5)` in the module, whole shape."""
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
    return hits


def pixel_normal(mod, D, ctx, hits):
    """The decode at the pixel's own coordinate; exactly one."""
    dcoord = ctx['depth']['coord'] if ctx.get('depth') else None
    xy = tuple(ctx['coord_xy'])
    own = []
    for h in hits:
        if h['coord'] == dcoord:
            own.append(h)
            continue
        mc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$',
                      D.get(h['coord'], (0, ''))[1])
        if mc and mc.groups() == xy:
            own.append(h)
    if len(own) != 1:
        die('%s: %d normal decodes at the pixel coordinate (%d in all), '
            'want exactly 1' % (mod.name, len(own), len(hits)))
    return own[0]


def shading_normal_phi(mod, D, nd):
    """The OpPhi triple the decode feeds, or None if the decode is read raw.

    Each component must feed exactly one phi, the three phis must sit in one
    contiguous phi group (same block), and their incoming labels must agree.
    Anything else is a shape this patcher has not seen and it dies.
    """
    trip = []
    for k in range(3):
        ph = set()
        for j in uses_of(mod, nd['n'][k]):
            m = re.match(r'\s*(%\d+)\s*=\s*OpPhi %float', mod.lines[j])
            if m:
                ph.add(m.group(1))
        if len(ph) > 1:
            die('%s: normal component %d feeds %d phis' % (mod.name, k, len(ph)))
        trip.append(next(iter(ph)) if ph else None)
    if all(t is None for t in trip):
        return None
    if any(t is None for t in trip):
        die('%s: only some normal components feed a phi' % mod.name)
    lines = [D[t][0] for t in trip]
    labels = [tuple(D[t][1].split()[3::2]) for t in trip]
    if len(set(labels)) != 1:
        die('%s: the three normal phis disagree on incoming labels' % mod.name)
    # contiguous phi group: walk down from the first phi of the block
    lo = min(lines)
    while lo > 0 and re.match(r'\s*%\w+\s*=\s*OpPhi ', mod.lines[lo - 1]):
        lo -= 1
    hi = max(lines)
    while hi + 1 < len(mod.lines) and re.match(r'\s*%\w+\s*=\s*OpPhi ',
                                                mod.lines[hi + 1]):
        hi += 1
    if not (lo <= min(lines) and max(lines) <= hi):
        die('%s: normal phis are not in one phi group' % mod.name)
    return dict(n=trip, last_phi_line=hi, lines=lines)


def find_albedo(mod, cfg, D, ctx, nd):
    """The albedo fetch, from the diffuse colour the c1 sites feed.

    dict(img, coord, lod, vec) -- the fetch is at the pixel's own coordinate
    and each of xyz is squared somewhere (the sqrt-encoding decode).
    """
    sites, _ = CS.find_c1_sites(mod)
    roots = set()
    for s in sites:
        trip = CS.find_diffuse_colour(mod, cfg, s)
        if not trip:
            continue
        rr = tuple(CS._albedo_channel_root(mod, t) for t in trip)
        if all(rr):
            roots.add(rr)
    if len(roots) != 1:
        die('%s: %d distinct albedo roots from %d c1 sites, want exactly 1'
            % (mod.name, len(roots), len(sites)))
    rr = next(iter(roots))
    vecs = {v for v, _ in rr}
    if len(vecs) != 1 or [i for _, i in rr] != [0, 1, 2]:
        die('%s: albedo channels do not root at xyz of ONE fetch: %s'
            % (mod.name, rr))
    vec = next(iter(vecs))
    m = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$', D[vec][1])
    if not m:
        die('%s: albedo root %s is not a v4float fetch' % (mod.name, vec))
    img, coord, lod = m.groups()
    xy = tuple(ctx['coord_xy'])
    mc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$',
                  D.get(coord, (0, ''))[1])
    if not ((mc and mc.groups() == xy) or coord == ctx['depth']['coord']):
        die('%s: albedo fetch is not at the pixel coordinate' % mod.name)
    if lod != nd['lod']:
        die('%s: albedo LOD differs from the normal LOD' % mod.name)
    for k in range(3):
        ex = [i for i, (_l, t) in D.items()
              if t.strip() == 'OpCompositeExtract %%float %s %d' % (vec, k)]
        if not any(re.match(r'OpFMul %%float %s %s\s*$' % (re.escape(e), re.escape(e)),
                            D[i][1]) for e in ex for i in D):
            die('%s: albedo channel %d is not squared (not the sqrt decode)'
                % (mod.name, k))
    return dict(img=img, coord=coord, lod=lod, vec=vec)


def albedo_leaves(D, alb):
    """The ids a re-issued albedo fetch reads; ALL must dominate the site."""
    parts = W._img_parts(W._chain_of(D, alb['img']))
    if parts is None:
        die('albedo image chain is not OpLoad(OpAccessChain)')
    return [x for x in (parts['arr'], parts['slot']) if re.match(r'%\d+$', x)]


def curv_tap_lines(mod, D, nd, hits):
    """Lines of `OpFSub N(neighbour)_k - N_k`: the 109 estimator's centre
    reads, which must keep the RAW normal.  {k: [lines]}."""
    others = set()
    for h in hits:
        if h is not nd:
            others.update(h['n'])
    out = {}
    for k in range(3):
        ls = []
        for j in uses_of(mod, nd['n'][k]):
            m = re.match(r'\s*%\w+\s*=\s*OpFSub %float (%\w+) ' + re.escape(nd['n'][k])
                         + r'\s*$', mod.lines[j])
            if m and m.group(1) in others:
                ls.append(j)
        out[k] = ls
    return out


def replace_uses_except(mod, old, new, after_line, skip):
    """replace_all_uses with a set of line indices left alone."""
    tok = re.compile(r'(?<![%\w])' + re.escape(old) + r'(?![\w])')
    isdef = re.compile(r'^\s*' + re.escape(old) + r'\s*=')
    n = 0
    for j in range(after_line + 1, len(mod.lines)):
        if j in skip or isdef.match(mod.lines[j]):
            continue
        ln2, k = tok.subn(new, mod.lines[j])
        if k:
            mod.lines[j] = ln2
            n += k
    return n


# -------------------------------------------------------------- emitter
def _pos_at(em, ctx, rows, co, coord_x, coord_y, depth_ld, lod, comp):
    """P at texel `co` (an existing v2uint id), reusing pre-loaded rows."""
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
    return [em.E('OpFDiv', '%float', outs[c], outs[3]) for c in range(3)]


def emit_bump(mod, cfg, D, ctx, alb, ncur, site_line, consts, uc, knobs,
              ins_out, want_mag=False):
    """Emit the micro-normal at `site_line`.

    Returns dict(nb=[3 ids], valid, mag, refetched, n_ins).  Contract, all
    checked by the caller: ctx['coord_xy'], pos_leaves(ctx) and the albedo
    image chain dominate the line; `ncur` is the shading normal live there.
    """
    em = Emit(mod, consts, uc)
    em.ins = ins_out
    n0 = len(ins_out)
    aparts = W._img_parts(W._chain_of(D, alb['img']))
    if aparts is None:
        die('%s: albedo image chain is not OpLoad(OpAccessChain)' % mod.name)
    imgd = ctx['img']

    step = em.U(knobs['step'])
    cx, cy = ctx['coord_xy']
    cx1 = em.E('OpIAdd', '%uint', cx, step)
    cy1 = em.E('OpIAdd', '%uint', cy, step)
    co0 = em.E('OpCompositeConstruct', '%v2uint', cx, cy)
    co1 = em.E('OpCompositeConstruct', '%v2uint', cx1, cy)
    co2 = em.E('OpCompositeConstruct', '%v2uint', cx, cy1)

    # --- three albedo taps -> linear luma
    aac = em.E('OpAccessChain', aparts['ptrty'], aparts['arr'], aparts['slot'])
    ald = em.E('OpLoad', aparts['imgty'], aac)
    wts = [em.C(w) for w in REC709]

    def luma(co):
        f = em.E('OpImageFetch', '%v4float', ald, co, 'Lod ' + alb['lod'])
        e = [em.E('OpCompositeExtract', '%float', f, str(k)) for k in range(3)]
        s = [em.E('OpFMul', '%float', e[k], e[k]) for k in range(3)]
        p = [em.E('OpFMul', '%float', s[k], wts[k]) for k in range(3)]
        a = em.E('OpFAdd', '%float', p[0], p[1])
        return em.E('OpFAdd', '%float', a, p[2])

    L0, L1, L2 = luma(co0), luma(co1), luma(co2)
    gx = em.E('OpFSub', '%float', L1, L0)
    gy = em.E('OpFSub', '%float', L2, L0)

    one = em.C(1.0)
    # --- the edge-kill band: g' = g * (1 - smoothstep(t0, t1, |g|))
    if knobs['band']:
        t0 = em.C(knobs['t0'])
        inv = em.C(1.0 / (knobs['t1'] - knobs['t0']))
        zero, two, three = em.C(0.0), em.C(2.0), em.C(3.0)

        def band(g):
            ag = em._ext('FAbs', '%float', g)
            u0 = em.E('OpFSub', '%float', ag, t0)
            u1 = em.E('OpFMul', '%float', u0, inv)
            u = em._ext('NClamp', '%float', u1, zero, one)
            uu = em.E('OpFMul', '%float', u, u)
            tw = em.E('OpFMul', '%float', u, two)
            th = em.E('OpFSub', '%float', three, tw)
            poly = em.E('OpFMul', '%float', uu, th)
            w = em.E('OpFSub', '%float', one, poly)
            return em.E('OpFMul', '%float', g, w)
        gx, gy = band(gx), band(gy)

    # --- the depth image and the matrix rows, loaded once
    dac = em.E('OpAccessChain', imgd['ptrty'], imgd['arr'], imgd['slot'])
    dld = em.E('OpLoad', imgd['imgty'], dac)
    rows = []
    for m in ctx['mat']:
        ac = em.E('OpAccessChain', '%_ptr_Uniform_v4float', ctx['cbv'],
                  '%uint_0', em.U(m))
        ld = em.E('OpLoad', '%v4float', ac)
        rows.append([em.E('OpCompositeExtract', '%float', ld, str(k))
                     for k in range(4)])

    # --- centre P: the module's own if it dominates, else 99's refetch
    refetched = False
    if all(cfg.dominates_line(i, site_line) for i in ctx['p']):
        pc = ctx['p']
    else:
        pc = W.emit_world_pos(mod, cfg, ctx, site_line, em.ins, uc=uc)
        refetched = True

    dlod, dcomp = ctx['depth']['lod'], ctx['depth']['comp']
    dp, q = [], []
    for co, ax, ay in ((co1, cx1, cy), (co2, cx, cy1)):
        pn = _pos_at(em, ctx, rows, co, ax, ay, dld, dlod, dcomp)
        d = [em.E('OpFSub', '%float', pn[k], pc[k]) for k in range(3)]
        v = em.E('OpCompositeConstruct', '%v3float', *d)
        dp.append(d)
        q.append(em.E('OpDot', '%float', v, v))

    eps = em.C(knobs['eps'])
    ix = em.E('OpFDiv', '%float', gx, em._ext('NMax', '%float', q[0], eps))
    iy = em.E('OpFDiv', '%float', gy, em._ext('NMax', '%float', q[1], eps))
    grad = []
    for k in range(3):
        a = em.E('OpFMul', '%float', ix, dp[0][k])
        b = em.E('OpFMul', '%float', iy, dp[1][k])
        grad.append(em.E('OpFAdd', '%float', a, b))
    vg = em.E('OpCompositeConstruct', '%v3float', *grad)
    vn = em.E('OpCompositeConstruct', '%v3float', *ncur)
    gn = em.E('OpDot', '%float', vg, vn)
    negh = em.C(-knobs['height'])
    d = []
    for k in range(3):
        along = em.E('OpFMul', '%float', gn, ncur[k])
        t = em.E('OpFSub', '%float', grad[k], along)
        d.append(em.E('OpFMul', '%float', t, negh))
    vd = em.E('OpCompositeConstruct', '%v3float', *d)
    m2 = em.E('OpDot', '%float', vd, vd)
    r = em._ext('InverseSqrt', '%float', em._ext('NMax', '%float', m2, eps))
    sc0 = em.E('OpFMul', '%float', em.C(knobs['dmax']), r)
    sc = em._ext('NMin', '%float', sc0, one)
    dq = [em.E('OpFMul', '%float', d[k], sc) for k in range(3)]
    v = [em.E('OpFAdd', '%float', ncur[k], dq[k]) for k in range(3)]
    vv = em.E('OpCompositeConstruct', '%v3float', *v)
    l2 = em.E('OpDot', '%float', vv, vv)
    rr = em._ext('InverseSqrt', '%float', l2)
    nb = [em.E('OpFMul', '%float', v[k], rr) for k in range(3)]

    mag = None
    if want_mag:
        sq = em._ext('Sqrt', '%float', m2)
        mg = em._ext('NMin', '%float', sq, em.C(knobs['dmax']))
        mag = em.E('OpFMul', '%float', mg, em.C(1.0 / knobs['dmax']))

    valid = None
    if knobs['guard']:
        j2 = em.C(knobs['jump'] * knobs['jump'])
        bx = em.E('OpFOrdLessThan', '%bool', q[0], j2)
        by = em.E('OpFOrdLessThan', '%bool', q[1], j2)
        valid = em.E('OpLogicalAnd', '%bool', bx, by)
    return dict(nb=nb, valid=valid, mag=mag, refetched=refetched, one=one,
                n_ins=len(em.ins) - n0)


# ------------------------------------------------------------ tier: feature
def build_bump_feature(mod, cfg, knobs):
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    D = W.defs_index(mod)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        die('%s: no P chain (99 sec 1)' % mod.name)
    hits = normal_decodes(mod, D)
    nd = pixel_normal(mod, D, ctx, hits)
    alb = find_albedo(mod, cfg, D, ctx, nd)
    phi = shading_normal_phi(mod, D, nd)
    if phi:
        site = phi['last_phi_line']
        ncur = phi['n']
        skip = {}
        mode = 'phi'
    else:
        site = nd['nline']
        ncur = nd['n']
        skip = curv_tap_lines(mod, D, nd, hits)
        for k in range(3):
            if len(skip[k]) != 2:
                die('%s: raw normal %d has %d curvature taps, expected 2 '
                    '(is the base the curv default?)' % (mod.name, k, len(skip[k])))
        mode = 'raw'
    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)

    # ---- ALL detection is finished above this line (GOTCHAS 12) ----------
    use = site + 1     # the inserted block occupies the line after `site`
    leaves = list(W.pos_leaves(ctx)) + [ctx['coord_xy'][0], ctx['coord_xy'][1]]
    leaves += albedo_leaves(D, alb)
    for i in leaves:
        if not cfg.dominates_line(i, use):
            die('%s: leaf %s does not dominate the bump site' % (mod.name, i))
    for i in ncur:
        if not cfg.dominates_line(i, use):
            die('%s: shading normal %s does not dominate the site' % (mod.name, i))
    before = {k: len(uses_of(mod, ncur[k])) for k in range(3)}

    ins = []
    if pre_ins:
        edits.append((ins_line, pre_ins))
    class_refetched = False
    if cfg.dominates_line(dom_id, use):
        cls = shift
    else:
        cf = find_class_fetch(mod)
        for i in class_fetch_inputs(cf):
            if not cfg.dominates_line(i, use):
                die('%s: class refetch input %s does not dominate' % (mod.name, i))
        cls = emit_class_value(mod, cf, ins)
        class_refetched = True
    b = emit_bump(mod, cfg, D, ctx, alb, ncur, use, consts, uc, knobs, ins)
    em = Emit(mod, consts, uc)
    em.ins = ins
    is_skin = em.E('OpIEqual', '%bool', cls, em.U(1))
    gate = em.E('OpLogicalAnd', '%bool', b['valid'], is_skin) if b['valid'] \
        else is_skin
    new = [em.E('OpSelect', '%float', gate, b['nb'][k], ncur[k]) for k in range(3)]
    edits.append((site, ins))

    rewritten = []
    for k in range(3):
        n = replace_uses_except(mod, ncur[k], new[k], site, set(skip.get(k, [])))
        want = before[k] - len(skip.get(k, []))
        # uses_of counts LINES; a line may hold the id more than once
        if n < want:
            die('%s: rewrote %d uses of %s, expected at least %d'
                % (mod.name, n, ncur[k], want))
        rewritten.append(n)

    rep = dict(tier='feature', mode=mode, height=knobs['height'],
               t0=knobs['t0'], t1=knobs['t1'], dmax=knobs['dmax'],
               jump=knobs['jump'], eps=knobs['eps'], step=knobs['step'],
               guard=bool(knobs['guard']), band=bool(knobs['band']),
               site_line=use, bump_instructions=b['n_ins'],
               centre_pos_refetched=b['refetched'],
               class_refetched=class_refetched,
               uses_rewritten=rewritten, uses_before=[before[k] for k in range(3)],
               curv_taps_kept=[len(skip.get(k, [])) for k in range(3)],
               shading_normal=list(ncur), decode_normal=list(nd['n']),
               matrix=ctx['mat'], cbv_slot=list(ctx['cbv_slot']),
               depth_slot=list(ctx['img_slot']),
               normal_slot=list(W._pc_slot(D, nd['img'])),
               albedo_slot=list(W._pc_slot(D, alb['img'])))
    return consts, edits, rep


# --------------------------------------------------------------- tier: vis
def build_bump_vis(mod, cfg, writes, knobs):
    """Paint |d|/DMAX as blue(flat) -> green -> red(clamped) on class-1
    pixels, modulated by scene luminance; white where the guard fired.

    The normal at a write is the pixel's RAW decode re-issued there (the
    shading phi does not dominate the writes), which is what the feature
    uses on skin anyway -- case 1 of the switch passes the decode through.
    """
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    D = W.defs_index(mod)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        die('%s: no P chain' % mod.name)
    hits = normal_decodes(mod, D)
    nd = pixel_normal(mod, D, ctx, hits)
    alb = find_albedo(mod, cfg, D, ctx, nd)
    nparts = W._img_parts(W._chain_of(D, nd['img']))
    leaves = list(W.pos_leaves(ctx)) + [ctx['coord_xy'][0], ctx['coord_xy'][1]]
    leaves += albedo_leaves(D, alb) + [x for x in (nparts['arr'], nparts['slot'])
                                       if re.match(r'%\d+$', x)]

    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((ins_line, pre_ins))
    cf = None
    done, skipped, refetched = [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float'})
            continue
        if any(not cfg.dominates_line(x, w['line']) for x in leaves):
            skipped.append({'line': w['line'] + 1, 'why': 'leaves do not dominate'})
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
        em = Emit(mod, consts, uc)
        em.ins = ins
        em.imgty, em.ptr_n = nparts['imgty'], nparts['ptrty']
        em.arr_n, em.slot_n = nparts['arr'], nparts['slot']
        co_c = em.E('OpCompositeConstruct', '%v2uint', *ctx['coord_xy'])
        ncur = _emit_normal_at(em, nd, co_c)
        b = emit_bump(mod, cfg, D, ctx, alb, ncur, w['line'], consts, uc,
                      knobs, ins, want_mag=True)
        if b['refetched']:
            refetched.append(w['line'] + 1)
        one = b['one']
        t = b['mag']
        omt = em.E('OpFSub', '%float', one, t)
        g0 = em.E('OpFMul', '%float', t, omt)
        gmid = em.E('OpFMul', '%float', g0, em.C(4.0))
        ramp = [t, gmid, omt]
        lr = em.E('OpFMul', '%float', w['comps'][0], em.C(0.2126))
        lg = em.E('OpFMul', '%float', w['comps'][1], em.C(0.7152))
        lb = em.E('OpFMul', '%float', w['comps'][2], em.C(0.0722))
        la = em.E('OpFAdd', '%float', lr, lg)
        lum = em.E('OpFAdd', '%float', la, lb)
        br = em._ext('NClamp', '%float', lum, em.C(knobs['vis_lo']),
                     em.C(knobs['vis_hi']))
        col = [em.E('OpFMul', '%float', ramp[k], br) for k in range(3)]
        if b['valid'] is not None:
            wht = em.E('OpFMul', '%float', br, one)
            col = [em.E('OpSelect', '%float', b['valid'], col[k], wht)
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
        tier='vis', height=knobs['height'], t0=knobs['t0'], t1=knobs['t1'],
        dmax=knobs['dmax'], jump=knobs['jump'], step=knobs['step'],
        guard=bool(knobs['guard']), band=bool(knobs['band']),
        writes=done, skipped=skipped, centre_pos_refetched=refetched,
        matrix=ctx['mat'], cbv_slot=list(ctx['cbv_slot']),
        depth_slot=list(ctx['img_slot']),
        normal_slot=list(W._pc_slot(D, nd['img'])),
        albedo_slot=list(W._pc_slot(D, alb['img'])))


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
    if knobs['height'] == 0.0:
        # THE CONTROL: nothing detected, nothing emitted, nothing rewritten.
        rep['bump'] = dict(tier=tier, height=0.0, control=True,
                           uses_rewritten=[0, 0, 0], writes=[])
        return CS._emit(mod, outdir, target_env, rep)
    if mod.dxil in KNOWN_DECLINE:
        die('%s: declined by name -- %s' % (mod.name, mod.dxil))
    cfg = CFG(mod)
    if tier == 'feature':
        consts, edits, rep['bump'] = build_bump_feature(mod, cfg, knobs)
    elif tier == 'vis':
        consts, edits, rep['bump'] = build_bump_vis(
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
    ap.add_argument('--tier', default='feature', choices=('feature', 'vis'))
    ap.add_argument('--height', type=float, default=DEFAULTS['height'],
                    help='metres of height per unit luma; 0 = the control')
    ap.add_argument('--t0', type=float, default=DEFAULTS['t0'])
    ap.add_argument('--t1', type=float, default=DEFAULTS['t1'])
    ap.add_argument('--dmax', type=float, default=DEFAULTS['dmax'])
    ap.add_argument('--jump', type=float, default=DEFAULTS['jump'])
    ap.add_argument('--step', type=int, default=DEFAULTS['step'])
    ap.add_argument('--no-guard', action='store_true',
                    help='DECOY: drop the silhouette fallback')
    ap.add_argument('--no-band', action='store_true',
                    help='DECOY: drop the edge-kill band')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    knobs = dict(DEFAULTS)
    knobs.update(height=a.height, t0=a.t0, t1=a.t1, dmax=a.dmax, jump=a.jump,
                 step=a.step, guard=not a.no_guard, band=not a.no_band)
    if a.height < 0 or a.t1 <= a.t0 or a.dmax <= 0 or a.step < 1 or a.jump <= 0:
        die('bad knobs')
    reps = [process(p, a.outdir, a.tier, knobs, do_rt=not a.no_roundtrip_check)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
