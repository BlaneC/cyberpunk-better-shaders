#!/usr/bin/env python3
"""hunt_wpos -- per-module table of where world position lives in the 77
compute resolvers (handoff/99 sec 2-3).

    python3 dev/hunt_wpos.py <dir-of-.spvasm | .spvasm ...> [--md OUT.md] [--json OUT.json]

For every module it reports, from the bytes alone:
  * P source          -- reconstructed in-module (matrix x (x,y,depth,1)) or read
  * matrix CBV member -- the four consecutive v4 members
  * camera CBV member -- the v4 the module subtracts P from to build V
  * offset adds       -- any `P_i + X` triple (the 94 sec 3.3 world-offset shape)
  * NoV coverage      -- eps-clamped NoV dots whose cone contains P
  * dominance         -- does P dominate every radiance OpImageWrite site
  * confidence
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes
import wpos_core as W


def analyse(path):
    mod, _ = load_lenient(path)
    D = W.defs_index(mod)
    r = dict(module=os.path.basename(path).split('.')[0], ident=mod.ident,
             lines=len(mod.lines))
    ctx = W.find_pos_chain(mod, D)
    if ctx is None:
        r.update(p_source='NONE', note='no matrix x (x,y,depth,1) / w divide')
        # is there any position-shaped buffer read instead?
        r['fdiv_groups'] = sum(1 for ln in mod.lines if 'OpFDiv %float' in ln)
        return mod, None, r
    r['p_source'] = 'reconstructed'
    r['p'] = list(ctx['p'])
    r['matrix'] = dict(cbv=ctx['cbv'], members=ctx['mat'])
    r['depth'] = None if not ctx['depth'] else dict(
        fetch=ctx['depth']['fetch'], image=ctx['depth']['image'],
        z=ctx['depth']['z'], slot=ctx.get('img_slot'), comp=ctx['depth']['comp'])
    r['cbv_slot'] = ctx.get('cbv_slot')
    r['pix'] = list(ctx['pix'] or [])
    cam = W.find_campos(mod, ctx, D)
    r['campos'] = None if cam is None else dict(cbv=cam['cbv'], member=cam['member'])
    r['campos_same_cbv'] = bool(cam and cam['cbv'] == ctx['cbv'])
    subs = W.find_p_subtractions(mod, ctx, D)
    r['p_subs'] = len(subs)
    kinds = {}
    for s_ in subs:
        k = s_['kind']['kind']
        if k == 'cbv':
            k = 'cbv[%d]' % s_['kind']['member']
        kinds[k] = kinds.get(k, 0) + 1
    r['p_sub_kinds'] = kinds
    adds = W.find_offset_adds(mod, ctx, D)
    r['offset_adds'] = {k: [(a, b) for a, b, _l in v] for k, v in adds.items()}
    r['n_offset_axes'] = len(adds)
    cons = W.p_consumers(mod, ctx, D)
    r['p_consumers'] = [(l + 1, op) for l, _i, op in cons]
    hit, shaped, tot = W.nov_roots_at_p(mod, ctx, D)
    r['nov_eps'] = tot
    r['nov_sites'] = shaped
    r['nov_rooted_at_p'] = hit
    # dominance of P at the radiance writes
    dom = W.Dom(mod)
    writes = [w for w in find_image_writes(mod) if w['comps'] is not None]
    r['writes'] = len(writes)
    ok = sum(1 for w in writes if all(dom.dominates_line(i, w['line']) for i in ctx['p']))
    r['p_dominates_writes'] = ok
    ins = W.pos_inputs(ctx)
    r['refetch_inputs'] = len(ins)
    r['refetchable'] = sum(1 for w in writes
                           if all(dom.dominates_line(i, w['line']) for i in ins))
    return mod, ctx, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--md')
    ap.add_argument('--json')
    a = ap.parse_args()
    files = []
    for p in a.paths:
        files += sorted(glob.glob(os.path.join(p, '*.spvasm'))) if os.path.isdir(p) else [p]
    rows = []
    for f in files:
        try:
            _m, _c, r = analyse(f)
        except Exception as e:
            r = dict(module=os.path.basename(f).split('.')[0], p_source='ERROR',
                     note=repr(e))
        rows.append(r)
        print(json.dumps(r, sort_keys=True))
    n = len(rows)
    rec = [r for r in rows if r.get('p_source') == 'reconstructed']
    print('\n--- summary over %d modules ---' % n)
    print('  P reconstructed in-module : %d' % len(rec))
    print('  P not found               : %s'
          % sorted(r['module'] for r in rows if r.get('p_source') != 'reconstructed'))
    mats = sorted({tuple(r['matrix']['members']) for r in rec})
    print('  matrix members            : %s' % (mats,))
    axs = sorted({tuple(r.get('depth') is not None for _ in [0]) for r in rec})
    print('  depth fetch resolved      : %d of %d'
          % (sum(1 for r in rec if r.get('depth')), len(rec)))
    cams = sorted({(r['campos'] or {}).get('member') for r in rec}, key=lambda x: (x is None, x))
    print('  depth image slot          : %s'
          % sorted({tuple(r['depth']['slot'] or ()) for r in rec}))
    print('  view CBV slot             : %s'
          % sorted({tuple(r['cbv_slot'] or ()) for r in rec}))
    print('  camera CBV member         : %s' % (cams,))
    print('  campos in the SAME cbv    : %d of %d'
          % (sum(1 for r in rec if r['campos_same_cbv']), len(rec)))
    print('  modules with ANY P + X add: %d' % sum(1 for r in rec if r['n_offset_axes']))
    print('  NoV (dot-shaped 1e-5) at P: %d of %d dot-shaped, %d eps clamps total'
          % (sum(r['nov_rooted_at_p'] for r in rec), sum(r['nov_sites'] for r in rec),
             sum(r['nov_eps'] for r in rec)))
    print('  modules where every NoV roots at P: %d of %d'
          % (sum(1 for r in rec if r['nov_rooted_at_p'] == r['nov_sites']), len(rec)))
    print('  writes P dominates        : %d of %d'
          % (sum(r['p_dominates_writes'] for r in rec), sum(r['writes'] for r in rec)))
    print('  writes P is refetchable at: %d of %d'
          % (sum(r['refetchable'] for r in rec), sum(r['writes'] for r in rec)))
    kk = {}
    for r in rec:
        for k, v in r.get('p_sub_kinds', {}).items():
            kk[k] = kk.get(k, 0) + v
    print('  X in `X - P`, by source  : %s' % sorted(kk.items(), key=lambda kv: -kv[1]))
    ops = {}
    for r in rec:
        for _l, op in r['p_consumers']:
            ops[op] = ops.get(op, 0) + 1
    print('  opcodes consuming P       : %s' % sorted(ops.items(), key=lambda kv: -kv[1]))
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=1, sort_keys=True)
    if a.md:
        with open(a.md, 'w') as fh:
            fh.write('| module | lines | P source | matrix cbv/members | cam member | '
                     'NoV@P | writes | P dominates | refetchable | P+X adds |\n')
            fh.write('|---|---|---|---|---|---|---|---|---|---|\n')
            for r in sorted(rows, key=lambda r: r['module']):
                if r.get('p_source') != 'reconstructed':
                    fh.write('| `%s` | %s | **%s** | — | — | — | — | — | — | — |\n'
                             % (r['module'], r.get('lines', '?'), r.get('p_source')))
                    continue
                fh.write('| `%s` | %d | reconstructed | `%s`[%d..%d] | %s | %d/%d | %d | %d | %d | %d |\n'
                         % (r['module'], r['lines'], r['matrix']['cbv'],
                            r['matrix']['members'][0], r['matrix']['members'][3],
                            (r['campos'] or {}).get('member'),
                            r['nov_rooted_at_p'], r['nov_sites'], r['writes'],
                            r['p_dominates_writes'], r['refetchable'],
                            r['n_offset_axes']))
        print('  wrote %s' % a.md)


if __name__ == '__main__':
    main()
