#!/usr/bin/env python3
"""Material-byte census over the raw shader dump (handoff/40 sec 2).

    python3 dev/census_subenum.py [~/callisto_dump]

Answers, from the BINARY SPIR-V (no spirv-dis, ~1 s over 3273 modules):

  * how many modules derive BOTH `word >> 5` (the 3-bit material class) and
    `word & 31` (the 5-bit sub-enum) from ONE value -- that pairing is what
    makes the low bits a sub-field of the material byte rather than an
    unrelated mask, and it is the rule that separates a real sub-enum test
    from a coincidental `& 31` somewhere else in the module;
  * which sub-enum values are tested, by which execution model;
  * which class values are tested anywhere in the dump.

Why binary rather than grep: `grep -r` over the dump silently returns 0 for
strings that are present (GOTCHAS), and a zero from grep looks exactly like a
finding. Values are collected from OpIEqual, OpINotEqual AND OpSwitch
literals -- the fragment module that carries the widest sub-enum test routes
seven of its values through a single OpSwitch, so a comparison-only scan
misses them entirely.
"""
import collections, glob, struct, sys, os

SHR, AND, EQ, INEQ, CONST, SWITCH, ENTRY = 194, 199, 170, 171, 43, 251, 15
STAGE = {0: 'Vertex', 1: 'TessControl', 2: 'TessEval', 3: 'Geometry',
         4: 'Fragment', 5: 'GLCompute', 5313: 'RayGeneration',
         5314: 'Intersection', 5315: 'AnyHit', 5316: 'ClosestHit',
         5317: 'Miss', 5318: 'Callable'}


def scan(path):
    """-> (stage, {sub values}, {class values}) or None if not SPIR-V."""
    d = open(path, 'rb').read()
    if len(d) < 20 or struct.unpack('<I', d[:4])[0] != 0x07230203:
        return None
    w = struct.unpack('<%dI' % (len(d) // 4), d[:len(d) // 4 * 4])
    consts, shr, band, cmps, sw, stage = {}, {}, {}, [], [], None
    i = 5
    while i < len(w):
        wc, op = w[i] >> 16, w[i] & 0xffff
        if wc == 0:
            break
        if op == ENTRY and wc >= 4 and stage is None:
            stage = STAGE.get(w[i + 1], str(w[i + 1]))
        elif op == CONST and wc == 4:
            consts[w[i + 2]] = w[i + 3]
        elif op == SHR and wc == 5:
            shr[w[i + 2]] = (w[i + 3], w[i + 4])
        elif op == AND and wc == 5:
            band[w[i + 2]] = (w[i + 3], w[i + 4])
        elif op in (EQ, INEQ) and wc == 5:
            cmps.append((w[i + 3], w[i + 4]))
        elif op == SWITCH and wc >= 5:
            sw += [(w[i + 1], w[j]) for j in range(i + 3, i + wc, 2)]
        i += wc

    def tested(res):
        out = set()
        for a, b in cmps:
            if a == res and b in consts:
                out.add(consts[b])
            if b == res and a in consts:
                out.add(consts[a])
        for sel, lit in sw:
            if sel == res:
                out.add(lit)
        return out

    bases = {b for _, (b, s) in shr.items() if consts.get(s) == 5}
    cls = set()
    for r, (b, s) in shr.items():
        if consts.get(s) == 5:
            cls |= tested(r)
    # the sub-enum: only where ONE word feeds both the shift and the mask
    sub, paired = set(), False
    for r, (b, s) in band.items():
        if consts.get(s) == 31 and b in bases:
            paired = True
            sub |= tested(r)
    return stage, (sub if paired else None), cls


def main():
    root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1
                              else '~/callisto_dump')
    sub_mod = collections.defaultdict(set)
    cls_mod = collections.defaultdict(set)
    by_stage = collections.defaultdict(set)
    paired = collections.Counter()
    n = n_paired = n_tests = 0
    for f in sorted(glob.glob(os.path.join(root, '*.spv'))):
        r = scan(f)
        if r is None:
            continue
        n += 1
        stage, sub, cls = r
        name = os.path.basename(f)
        for v in cls:
            cls_mod[v].add(name)
        if sub is None:
            continue
        n_paired += 1
        paired[stage] += 1
        if sub:
            n_tests += 1
        for v in sub:
            sub_mod[v].add(name)
            by_stage[stage].add(v)
    print(f"modules scanned                        : {n}")
    print(f"one word feeds both >>5 and &31        : {n_paired} "
          f"{dict(paired)}")
    print(f"of those, testing a sub-enum value     : {n_tests}")
    print("sub-enum value -> #modules             :",
          {k: len(v) for k, v in sorted(sub_mod.items())})
    print("sub-enum values by stage               :",
          {k: sorted(v) for k, v in sorted(by_stage.items())})
    print("class value -> #modules (whole dump)   :",
          {k: len(v) for k, v in sorted(cls_mod.items())})
    for v in sorted(sub_mod):
        if len(sub_mod[v]) == 1:
            print(f"  sub-enum {v} appears in exactly one module: "
                  f"{sorted(sub_mod[v])[0]}")


if __name__ == '__main__':
    main()
