#!/usr/bin/env python3
"""Relaxed scan for tonemap-LUT-generator permutations.

find_tonemap_gens.py required a >=3-entry output-mode ladder.  A permutation
compiled for a KNOWN display mode has that ladder constant-folded away, so it
was invisible to that scan -- which is a candidate explanation for "HDR works,
SDR does not".

This keeps only the mode-independent half of the signature:

  * exactly one OpImageWrite of a v4float          (the LUT texel)
  * >=3 Exp2 tainted from gl_GlobalInvocationID    (the log2 shaper)

and REPORTS the rest (local size, ladder size, whether the ACES AP1->XYZ
matrix is present) instead of filtering on it.
"""
import re, subprocess, sys, glob
from concurrent.futures import ProcessPoolExecutor


def classify(path):
    try:
        r = subprocess.run(['spirv-dis', path], capture_output=True,
                           text=True, timeout=180)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()

    writes = 0
    defs = {}
    for l in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*Op(\w+)(.*)$', l)
        if m:
            defs[m.group(1)] = (m.group(2), m.group(3))
    for l in lines:
        m = re.match(r'\s*OpImageWrite %\w+ %\w+ (%\w+)\s*$', l)
        if m:
            d = defs.get(m.group(1))
            if d and d[0] == 'CompositeConstruct' and d[1].strip().startswith('%v4float'):
                writes += 1
    if writes != 1:
        return None

    chain = {m.group(1): int(m.group(2)) for m in
             (re.match(r'\s*(%\w+)\s*=\s*OpAccessChain %_ptr_Input_uint '
                       r'%gl_GlobalInvocationID %uint_(\d)\s*$', l) for l in lines) if m}
    seeds = {m.group(1) for m in
             (re.match(r'\s*(%\w+)\s*=\s*OpLoad %uint (%\w+)\s*$', l) for l in lines)
             if m and m.group(2) in chain}
    if len(seeds) < 3:
        return None
    taint, exp2 = set(seeds), 0
    for l in lines:
        if re.search(r'\bOp(SelectionMerge|LoopMerge|BranchConditional|Switch)\b', l):
            break
        m = re.match(r'\s*(%\w+)\s*=\s*Op\w+(.*)$', l)
        if m and set(re.findall(r'%\w+', m.group(2))) & taint:
            taint.add(m.group(1))
            if re.match(r'\s*%\w+\s*=\s*OpExtInst %float %\w+ Exp2 %\w+\s*$', l):
                exp2 += 1
    if exp2 < 3:
        return None

    ladder = {}
    for l in lines:
        m = re.match(r'\s*%\w+\s*=\s*OpFOrdEqual %bool (%\w+) %float_(\d)\s*$', l)
        if m:
            ladder.setdefault(m.group(1), set()).add(int(m.group(2)))
    ls = re.search(r'LocalSize (\d+) (\d+) (\d+)', r.stdout)
    return dict(path=path,
                id=path.split('/')[-1].split('.')[0],
                lines=len(lines),
                local='x'.join(ls.groups()) if ls else '?',
                exp2=exp2,
                modes=max((len(v) for v in ladder.values()), default=0),
                aces='yes' if '0.662454128' in r.stdout else 'no',
                pq='yes' if '78.84375' in r.stdout else 'no')


def main():
    files = sorted(glob.glob(sys.argv[1] + '/*.spv'))
    print(f"scanning {len(files)} modules...", file=sys.stderr)
    with ProcessPoolExecutor() as ex:
        hits = [h for h in ex.map(classify, files, chunksize=8) if h]
    hits.sort(key=lambda h: (h['aces'] != 'yes', -h['modes']))
    print(f"{'id':<20}{'lines':>7}{'local':>9}{'exp2':>6}{'modes':>7}"
          f"{'AP1->XYZ':>10}{'PQ':>5}")
    for h in hits:
        print(f"{h['id']:<20}{h['lines']:>7}{h['local']:>9}{h['exp2']:>6}"
              f"{h['modes']:>7}{h['aces']:>10}{h['pq']:>5}")
    print(f"\n{len(hits)} candidates", file=sys.stderr)


if __name__ == '__main__':
    main()
