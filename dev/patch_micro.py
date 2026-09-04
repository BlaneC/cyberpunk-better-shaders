#!/usr/bin/env python3
"""micro -- the other four-fifths of the pore, plus the layer 72 forgot.

handoff/117.  Supersedes nothing: this is 115's block with four more terms
hung off the height field it already builds, spliced into the same 77 compute
resolvers, on the same base (`...-curv-t7hue1-ll`).  With every strength at
zero it is `cmp`-identical to the shipped default `bump`, which is the control
gate: the bump half is emitted verbatim from patch_bump.emit_bump.

    occ    diffuse *= 1 - KOCC*cav                   a pit is shadowed by its rim
    rough  alpha   *= 1 + KRGH*cav                   pores scatter the highlight
    term   diffuse *= 1 + w - w^2                    Chiang 2019, the fix for the
                                                     artifact 115 introduces
    gtso   spec    *= SO(NoV, ao, alpha^2)           Jimenez 2016; 38 A5 without
                                                     the bent normal it waited on
    cons   diffuse *= 1 - Favg                       72's oil layer is a pure ADD

The maths, its float32 self-checks and the reason for each knob live in
dev/micro_model.py.  WHAT IS FOUND is in dev/brdf_sites.py, and nothing is
found by name or by id: the roughness select is reached through the GGX `D`
term's divide by pi, the diffuse BRDF through the Disney retro constant, and
the specular tail by walking D*NoL*Vis down to the first node three per-channel
products multiply.  Census on the shipped default, 77 modules:

    roughness selects   473   in 77/77
    diffuse BRDF sites  158   in 77/77
    specular tails      400   in 77/77
    diffuse paired to a specular lobe (for `cons`)   158/158

Every strength is independent, so the build ships one rung per half and one
with all five, and the A/B can attribute a verdict to a term.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
    emit_class_value
from patch_compute_brdf import detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
from patch_curv import Emit
import wpos_core as W
import patch_bump as BP
import brdf_sites as BS
import micro_model as MM

DEFAULTS = dict(BP.DEFAULTS)
DEFAULTS.update(cref=float(MM.CREF), c0=float(MM.C0), c1=float(MM.C1),
                kocc=float(MM.KOCC), krgh=float(MM.KRGH),
                occ=1, rough=1, term=1, gtso=1, cons=1)


# ------------------------------------------------------------------ cavity
def emit_cavity(em, lum, knobs):
    """cav in [0,1] from the albedo Laplacian.  Two more taps than 115 makes."""
    cx, cy, step = lum['cx'], lum['cy'], lum['step']
    xm = em.E('OpISub', '%uint', cx, step)
    ym = em.E('OpISub', '%uint', cy, step)
    L3 = lum['fn'](em.E('OpCompositeConstruct', '%v2uint', xm, cy))
    L4 = lum['fn'](em.E('OpCompositeConstruct', '%v2uint', cx, ym))
    a = em.E('OpFAdd', '%float', lum['L'][1], lum['L'][2])
    b = em.E('OpFAdd', '%float', L3, L4)
    s = em.E('OpFAdd', '%float', a, b)
    r = em.E('OpFMul', '%float', s, em.C(0.25))
    lap = em.E('OpFSub', '%float', r, lum['L'][0])
    if knobs['band']:
        # the SAME edge-kill shape as 115 sec 2, on its own band
        c0 = em.C(knobs['c0'])
        inv = em.C(1.0 / (knobs['c1'] - knobs['c0']))
        z, one, two, three = em.C(0.0), em.C(1.0), em.C(2.0), em.C(3.0)
        ag = em._ext('FAbs', '%float', lap)
        u0 = em.E('OpFSub', '%float', ag, c0)
        u1 = em.E('OpFMul', '%float', u0, inv)
        u = em._ext('NClamp', '%float', u1, z, one)
        uu = em.E('OpFMul', '%float', u, u)
        tw = em.E('OpFMul', '%float', u, two)
        th = em.E('OpFSub', '%float', three, tw)
        poly = em.E('OpFMul', '%float', uu, th)
        w = em.E('OpFSub', '%float', one, poly)
        lap = em.E('OpFMul', '%float', lap, w)
    q = em.E('OpFMul', '%float', lap, em.C(1.0 / knobs['cref']))
    return em._ext('NClamp', '%float', q, em.C(0.0), em.C(1.0))


# ------------------------------------------------------------- the four sites
def light_dir(D, nol):
    """The light-direction v3 behind a site's NoL, or None.

    NoL is `NClamp(OpDot(Nv, Lv), 0, 1)` (or the bare dot); Nv is the
    OpCompositeConstruct of the shading normal, Lv the other operand.
    """
    d = D.get(nol)
    if d is None:
        return None
    if d['op'] == 'OpExtInst' and 'NClamp' in d['text']:
        inner = d['args'][0] if D.get(d['args'][0], {}).get('op') == 'OpDot' \
            else (d['args'][1] if len(d['args']) > 1 else None)
        for a in d['args']:
            if D.get(a, {}).get('op') == 'OpDot':
                inner = a
        d = D.get(inner)
    if d is None or d['op'] != 'OpDot' or len(d['args']) != 2:
        return None
    return d['args']


def build_micro(mod, cfg, knobs):
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    D = W.defs_index(mod)
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        die('%s: no P chain (99 sec 1)' % mod.name)
    hits = BP.normal_decodes(mod, D)
    nd = BP.pixel_normal(mod, D, ctx, hits)
    alb = BP.find_albedo(mod, cfg, D, ctx, nd)
    phi = BP.shading_normal_phi(mod, D, nd)
    if phi:
        site, ncur, skip, nmode = phi['last_phi_line'], phi['n'], {}, 'phi'
    else:
        site, ncur = nd['nline'], nd['n']
        skip = BP.curv_tap_lines(mod, D, nd, hits)
        for k in range(3):
            if len(skip[k]) != 2:
                die('%s: raw normal %d has %d curvature taps, expected 2'
                    % (mod.name, k, len(skip[k])))
        nmode = 'raw'
    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
    consts.extend(pre_consts)

    # the BRDF census, on the UNEDITED text (GOTCHAS 12: detect, then emit)
    BD, S = BS.find_sites('\n'.join(mod.lines))

    # ---- ALL detection is finished above this line ----------------------
    use = site + 1
    leaves = list(W.pos_leaves(ctx)) + [ctx['coord_xy'][0], ctx['coord_xy'][1]]
    leaves += BP.albedo_leaves(D, alb)
    for i in leaves + list(ncur):
        if not cfg.dominates_line(i, use):
            die('%s: leaf %s does not dominate the splice' % (mod.name, i))
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

    b = BP.emit_bump(mod, cfg, D, ctx, alb, ncur, use, consts, uc, knobs, ins,
                     want_lum=True)
    em = Emit(mod, consts, uc)
    em.ins = ins
    one, zero = em.C(1.0), em.C(0.0)
    is_skin = em.E('OpIEqual', '%bool', cls, em.U(1))
    gate = em.E('OpLogicalAnd', '%bool', b['valid'], is_skin) if b['valid'] \
        else is_skin
    nb = [em.E('OpSelect', '%float', gate, b['nb'][k], ncur[k]) for k in range(3)]

    cav = None
    if knobs['occ'] or knobs['rough'] or knobs['gtso']:
        cav0 = emit_cavity(em, b['lum'], knobs)
        cav = em.E('OpSelect', '%float', gate, cav0, zero)
    bump_line_ids = dict(cav=cav, is_skin=is_skin, nb=nb)
    edits.append((site, ins))

    # the bump half, verbatim 115: rewrite the shading normal everywhere below
    rewritten = []
    for k in range(3):
        n = BP.replace_uses_except(mod, ncur[k], nb[k], site, set(skip.get(k, [])))
        want = before[k] - len(skip.get(k, []))
        if n < want:
            die('%s: rewrote %d uses of %s, expected at least %d'
                % (mod.name, n, ncur[k], want))
        rewritten.append(n)

    # ------------------------------------------------------------ the halves
    rep_sites = []

    def dom(ids, line):
        return all(cfg.dominates_line(i, line) for i in ids)

    # --- rough: alpha *= 1 + KRGH*cav, at every GGX roughness select
    n_rough = 0
    if knobs['rough'] and cav is not None:
        seen_sel = set()
        for a in S['alpha']:
            if a['sel'] in seen_sel:
                continue
            seen_sel.add(a['sel'])
            ln = BD['D'][a['sel']]['line']
            if not cfg.dominates_line(cav, ln + 1):
                continue
            e = Emit(mod, consts, uc)
            f = e.E('OpFMul', '%float', cav, e.C(knobs['krgh']))
            g = e.E('OpFAdd', '%float', f, e.C(1.0))
            new = e.E('OpFMul', '%float', a['sel'], g)
            BP.replace_uses_except(mod, a['sel'], new, ln, set())
            edits.append((ln, e.ins))
            n_rough += 1

    # --- occ / term / cons: one factor on each diffuse BRDF scalar
    n_occ = n_term = n_cons = 0
    for ds in S['diffuse']:
        ln = BD['D'][ds['diff']]['line']
        ss, F, lc = BS.pair_lobes(BD['D'], BD['U'], ds, S['spec'])
        e = Emit(mod, consts, uc)
        fac = []
        if knobs['occ'] and cav is not None and cfg.dominates_line(cav, ln + 1):
            k = e.E('OpFMul', '%float', cav, e.C(knobs['kocc']))
            fac.append(e.E('OpFSub', '%float', e.C(1.0), k))
            n_occ += 1
        if knobs['term'] and ss is not None:
            Lv = light_dir(BD['D'], ss['nol'])
            Nv = None
            if Lv:
                # the operand that is the shading normal's own construct
                for x in Lv:
                    dd = BD['D'].get(x)
                    if dd and dd['op'] == 'OpCompositeConstruct' and \
                            list(dd['args']) == list(ncur):
                        Nv = x
                Lv = [x for x in Lv if x != Nv]
            if Nv and len(Lv) == 1 and dom(list(ncur) + [ss['nol'], Lv[0]], ln + 1):
                nr = e.E('OpCompositeConstruct', '%v3float', *ncur)
                dr = e.E('OpDot', '%float', nr, Lv[0])
                dc = e._ext('NClamp', '%float', dr, e.C(0.0), e.C(1.0))
                den = e._ext('NMax', '%float', dc, e.C(float(MM.EPS)))
                w0 = e.E('OpFDiv', '%float', ss['nol'], den)
                w = e._ext('NClamp', '%float', w0, e.C(0.0), e.C(1.0))
                ww = e.E('OpFMul', '%float', w, w)
                t0 = e.E('OpFAdd', '%float', e.C(1.0), w)
                fac.append(e.E('OpFSub', '%float', t0, ww))
                n_term += 1
        if fac:
            f = fac[0]
            for x in fac[1:]:
                f = e.E('OpFMul', '%float', f, x)
            new = e.E('OpFMul', '%float', ds['diff'], f)
            BP.replace_uses_except(mod, ds['diff'], new, ln, set())
            edits.append((ln, e.ins))

        # cons is PER CHANNEL and rides the channel product, not the BRDF
        # scalar: the Fresnel is formed BELOW the diffuse BRDF in every module.
        n_here = 0
        if knobs['cons'] and F is not None:
            for i, ch in enumerate(ds['chan']):
                cl = BD['D'][ch]['line']
                if not dom([F[i], is_skin], cl + 1):
                    continue
                e2 = Emit(mod, consts, uc)
                kd = e2.E('OpFSub', '%float', e2.C(1.0), F[i])
                g2 = e2.E('OpSelect', '%float', is_skin, kd, e2.C(1.0))
                nw = e2.E('OpFMul', '%float', ch, g2)
                BP.replace_uses_except(mod, ch, nw, cl, set())
                edits.append((cl, e2.ins))
                n_here += 1
            n_cons += n_here
        rep_sites.append(dict(diff=ds['diff'], spec=ss and ss['S'],
                              factors=len(fac), cons_channels=n_here,
                              paired_by=('colour' if (lc and lc[0]) else 'order')))

    # --- gtso: spec tail *= SO(NoV, ao, alpha^2)
    n_gtso = 0
    if knobs['gtso'] and cav is not None:
        for ss in S['spec']:
            ln = BD['D'][ss['S']]['line']
            if not dom([cav, ss['nov'], ss['a2']], ln + 1):
                continue
            e = Emit(mod, consts, uc)
            k = e.E('OpFMul', '%float', cav, e.C(knobs['kocc']))
            ao = e.E('OpFSub', '%float', e.C(1.0), k)
            x0 = e.E('OpFAdd', '%float', ss['nov'], ao)
            x = e._ext('NMax', '%float', x0, e.C(1e-6))
            p0 = e.E('OpFMul', '%float', ss['a2'], e.C(-16.0))
            p1 = e.E('OpFSub', '%float', p0, e.C(1.0))
            ex = e._ext('Exp2', '%float', p1)
            lg = e._ext('Log2', '%float', x)
            pw = e._ext('Exp2', '%float', e.E('OpFMul', '%float', lg, ex))
            s0 = e.E('OpFSub', '%float', pw, e.C(1.0))
            s1 = e.E('OpFAdd', '%float', s0, ao)
            so = e._ext('NClamp', '%float', s1, e.C(0.0), e.C(1.0))
            new = e.E('OpFMul', '%float', ss['S'], so)
            BP.replace_uses_except(mod, ss['S'], new, ln, set())
            edits.append((ln, e.ins))
            n_gtso += 1

    rep = dict(normal_mode=nmode, site_line=use,
               height=knobs['height'], cref=knobs['cref'],
               kocc=knobs['kocc'], krgh=knobs['krgh'],
               c0=knobs['c0'], c1=knobs['c1'],
               halves=dict(occ=bool(knobs['occ']), rough=bool(knobs['rough']),
                           term=bool(knobs['term']), gtso=bool(knobs['gtso']),
                           cons=bool(knobs['cons'])),
               census=dict(alpha=len({a['sel'] for a in S['alpha']}), diffuse=len(S['diffuse']),
                           spec=len(S['spec']), miss=len(S['miss'])),
               sites=rep_sites,
               applied=dict(rough=n_rough, occ=n_occ, term=n_term,
                            cons=n_cons, gtso=n_gtso),
               bump_instructions=b['n_ins'],
               centre_pos_refetched=b['refetched'],
               class_refetched=class_refetched,
               uses_rewritten=rewritten,
               shading_normal=list(ncur), decode_normal=list(nd['n']))
    return consts, edits, rep


def process(path, outdir, knobs, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die('%s: no dxil identity' % os.path.basename(path))
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, dxil=mod.dxil)
    if problems:
        rep['module_warnings'] = problems
    if mod.dxil in BP.KNOWN_DECLINE:
        die('%s: declined by name -- %s' % (mod.name, mod.dxil))
    cfg = CFG(mod)
    consts, edits, rep['micro'] = build_micro(mod, cfg, knobs)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    for k in ('height', 't0', 't1', 'dmax', 'jump', 'cref', 'c0', 'c1',
              'kocc', 'krgh'):
        ap.add_argument('--' + k, type=float, default=DEFAULTS[k])
    ap.add_argument('--step', type=int, default=DEFAULTS['step'])
    for h in ('occ', 'rough', 'term', 'gtso', 'cons'):
        ap.add_argument('--no-' + h, action='store_true')
    ap.add_argument('--only', help='comma list of halves to keep')
    ap.add_argument('--no-guard', action='store_true',
                    help='DECOY: drop the silhouette fallback')
    ap.add_argument('--no-band', action='store_true',
                    help='DECOY: drop both edge-kill bands')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    knobs = dict(DEFAULTS)
    knobs.update({k: getattr(a, k) for k in
                  ('height', 't0', 't1', 'dmax', 'jump', 'cref', 'c0', 'c1',
                   'kocc', 'krgh', 'step')})
    knobs.update(guard=not a.no_guard, band=not a.no_band)
    for h in ('occ', 'rough', 'term', 'gtso', 'cons'):
        knobs[h] = 0 if getattr(a, 'no_' + h) else 1
    if a.only:
        keep = {x.strip() for x in a.only.split(',') if x.strip()}
        bad = keep - {'occ', 'rough', 'term', 'gtso', 'cons'}
        if bad:
            die('unknown half(s): %s' % ','.join(sorted(bad)))
        for h in ('occ', 'rough', 'term', 'gtso', 'cons'):
            knobs[h] = 1 if h in keep else 0
    if a.height < 0 or a.t1 <= a.t0 or a.c1 <= a.c0 or a.cref <= 0 or \
            a.dmax <= 0 or a.step < 1 or a.jump <= 0 or a.kocc < 0 or \
            a.kocc > 1 or a.krgh < 0:
        die('bad knobs')
    reps = [process(p, a.outdir, knobs, do_rt=not a.no_roundtrip_check)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
