#!/usr/bin/env python3
"""GOTCHAS 3 sibling sweep for the Tier-4 skin transmission splice.

Rule 3 says: after locating a splice site in one module, sweep for structural
siblings before writing the emitter.  handoff/29 A6 makes that explicit for
this feature -- the four evaluators read by hand are a sample, not the
schema.  So this runs the REAL detector (find_transmission_site, imported,
not reimplemented) across every anchored compute lib and prints what it
found, one row per module, plus a tally of the reasons it declined.

The point is to answer three questions before a single instruction is
emitted:

  1. How many of the anchored libs carry a spliceable diffuse write at all?
  2. Of those, how many carry the engine's light blocker (the free
     "the sun is behind this surface" mask, handoff/29 A4 route 2)?
  3. Where the detector declines, is the reason a real structural
     difference or a hole in the detector?

Question 3 is the one that matters: a detector that silently matches nothing
looks identical to a feature that is not present, which is the handoff/27 7.5
failure class.  Every decline is printed with its reason.

Usage:
    dev/survey_translucency.py [--dir dev/disasm/compute] [--verbose]
"""
import argparse
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG
import patch_skin_brdf as P
import patch_compute_skin as S


class Declined(Exception):
    pass


# The helpers die() on a module they were not built for -- right for a build,
# wrong for a sweep, whose whole job is to visit modules that do not match.
P.die = lambda msg: (_ for _ in ()).throw(Declined(msg.split(': ')[-1]))


def survey_one(path):
    mod, _problems = load_lenient(path)
    row = dict(name=os.path.basename(path).split('.')[0])
    if not mod.fconst.get(P.f32(0.107508637)):
        row['verdict'] = 'not a Disney diffuse module'
        return row
    sites, skipped = S.find_c1_sites(mod)
    row['c1'] = len(sites)
    row['c1_skipped'] = len(skipped)
    if not sites:
        row['verdict'] = 'no c1 sites'
        return row
    writes = S.find_radiance_writes(mod)
    row['writes'] = len(writes)
    row['scaled'] = sum(1 for w in writes if w['scale'])
    cfg = CFG(mod)
    site, why = S.find_transmission_site(mod, cfg)
    if not site:
        row['verdict'] = why
        return row
    row['verdict'] = 'OK'
    row['kind'] = site['kind']
    row['targets'] = len(site['targets'])
    row['uncovered'] = len(site['uncovered'])
    row['block'] = site['block']
    row['blocker'] = bool(site['blocker'])
    row['accs'] = site['accs']
    row['albedo'] = site['has_albedo']
    row['shadow'] = site['has_shadow']
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'disasm', 'compute'))
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()

    paths = sorted(os.path.join(a.dir, f) for f in os.listdir(a.dir)
                   if f.endswith('.spvasm'))
    if not paths:
        sys.exit(f'no .spvasm under {a.dir}')

    rows, reasons = [], collections.Counter()
    for p in paths:
        try:
            r = survey_one(p)
        except Declined as e:
            r = dict(name=os.path.basename(p).split('.')[0],
                     verdict=f'declined: {e}')
        except Exception as e:                       # noqa: BLE001
            r = dict(name=os.path.basename(p).split('.')[0],
                     verdict=f'ERROR {type(e).__name__}: {e}')
        rows.append(r)
        reasons[r['verdict']] += 1

    w = max(len(r['name']) for r in rows)
    print(f"{'module':<{w}}  c1  wr  scl  splice         tgt  blk  alb  shd  verdict")
    print('-' * (w + 48))
    for r in rows:
        ok = r['verdict'] == 'OK'
        print(f"{r['name']:<{w}}  "
              f"{r.get('c1', 0):>2}  {r.get('writes', 0):>2}  "
              f"{r.get('scaled', 0):>3}  "
              f"{(r.get('kind', '') + ' ' + r.get('block', '')).strip():<14} "
              f"{(str(r['targets']) + ('+%d!' % r['uncovered'] if r.get('uncovered') else '')) if ok else '':<5}"
              f"{('yes' if r.get('blocker') else '-' if ok else ''):<4} "
              f"{('yes' if r.get('albedo') else '-' if ok else ''):<4} "
              f"{('yes' if r.get('shadow') else '-' if ok else ''):<4} "
              f"{r['verdict']}")

    n_ok = reasons['OK']
    n_blk = sum(1 for r in rows if r.get('blocker'))
    n_pred = sum(1 for r in rows if r.get('kind') == 'phi')
    n_alb = sum(1 for r in rows if r.get('albedo'))
    n_shd = sum(1 for r in rows if r.get('shadow'))
    print()
    print(f"{len(rows)} modules   spliceable {n_ok}   "
          f"with light blocker {n_blk}   phi-edge splice {n_pred}")
    print(f"   uncovered light-carrying edges: "
          f"{sum(r.get('uncovered', 0) for r in rows)}")
    print(f"   of the spliceable: albedo recovered {n_alb}, "
          f"sun-shadow mask recovered {n_shd}")
    print()
    for why, n in reasons.most_common():
        print(f"  {n:>3}  {why}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
