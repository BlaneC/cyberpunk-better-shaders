#!/usr/bin/env python3
"""Scan a module dump for every tonemap-LUT-generator permutation.

The AgX patch was applied to b174eb4af0fea652, which turns out to be the HDR
permutation.  SDR runs a sibling.  All of them share a structural signature
that nothing else in the dump has:

  * OpExecutionMode LocalSize 8 8 8         (a 3D LUT grid)
  * exactly one OpImageWrite of a v4float   (the LUT texel)
  * three Exp2 whose inputs derive from gl_GlobalInvocationID (log2 shaper)
  * a mode ladder: >=3 OpFOrdEqual against the same value vs 0/1/2/3/4

Selecting by structure, not by constants -- 10-DISPATCH-TRUTH.md's rule.
"""
import os, re, subprocess, sys, glob
from concurrent.futures import ProcessPoolExecutor


def classify(path):
    try:
        asm = subprocess.run(['spirv-dis', path], capture_output=True,
                             text=True, timeout=120)
    except Exception:
        return None
    if asm.returncode != 0:
        return None
    t = asm.stdout
    if 'LocalSize 8 8 8' not in t:
        return None
    lines = t.splitlines()

    writes = [i for i, l in enumerate(lines)
              if re.match(r'\s*OpImageWrite %\w+ %\w+ %\w+\s*$', l)]
    if len(writes) != 1:
        return None

    ladder = {}
    for l in lines:
        m = re.match(r'\s*%\w+\s*=\s*OpFOrdEqual %bool (%\w+) %float_(\d)\s*$', l)
        if m:
            ladder.setdefault(m.group(1), set()).add(int(m.group(2)))
    modes = max((len(v) for v in ladder.values()), default=0)
    if modes < 3:
        return None

    chain = {m.group(1): int(m.group(2)) for m in
             (re.match(r'\s*(%\w+)\s*=\s*OpAccessChain %_ptr_Input_uint '
                       r'%gl_GlobalInvocationID %uint_(\d)\s*$', l) for l in lines) if m}
    seeds = set()
    for l in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpLoad %uint (%\w+)\s*$', l)
        if m and m.group(2) in chain:
            seeds.add(m.group(1))
    if len(seeds) != 3:
        return None
    taint, exp2 = set(seeds), 0
    for l in lines:
        if re.search(r'\bOp(SelectionMerge|LoopMerge|BranchConditional|Switch)\b', l):
            break
        m = re.match(r'\s*(%\w+)\s*=\s*Op\w+(.*)$', l)
        if not m:
            continue
        if set(re.findall(r'%\w+', m.group(2))) & taint:
            taint.add(m.group(1))
            if re.match(r'\s*%\w+\s*=\s*OpExtInst %float %\w+ Exp2 %\w+\s*$', l):
                exp2 += 1
    if exp2 < 3:
        return None

    pq = sum(t.count(f'OpConstant %float {c}') for c in
             ('0.159301758', '78.84375', '0.8359375', '18.8515625', '18.6875'))
    return dict(path=path, id=os.path.basename(path).split('.')[0],
                lines=len(lines), modes=modes, exp2=exp2, pq=pq,
                size=os.path.getsize(path))


def main():
    dump = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/callisto_dump')
    files = sorted(glob.glob(dump + '/*.dxil.spv'))
    print(f'scanning {len(files)} modules in {dump} ...', file=sys.stderr)
    hits = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(classify, files, chunksize=16):
            if r:
                hits.append(r)
    print(f'\n{len(hits)} tonemap-LUT-generator permutation(s):\n')
    print(f"{'id':<18}{'lines':>7}{'modes':>7}{'PQ consts':>11}{'bytes':>9}")
    for h in sorted(hits, key=lambda h: -h['lines']):
        print(f"{h['id']:<18}{h['lines']:>7}{h['modes']:>7}{h['pq']:>11}{h['size']:>9}")


if __name__ == '__main__':
    main()
