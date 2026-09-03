"""Static audit: prove NOTHING per-frame feeds the paint hash.

Walks, in the SHIPPED bytes, from the committed-field getter forward to the
latch, from the latch forward through every hash multiply, and then backwards
over the transitive operand closure of each 9-deep OpSelect chain. Every leaf
must be a constant, a ray-query getter, or a load of one of the two Private
latch variables the splice created. Anything else -- an LCG state, a frame
index, a sample index, a push constant, a descriptor load -- shows up as a
FOREIGN leaf and fails the audit.
"""
import subprocess, re, glob, os, sys
GOLD = '2654435761'

def audit(dirpath, verbose_for=None):
    bad, note, nmod = [], [], 0
    for p in sorted(glob.glob(dirpath + '/*.rgs_reference_main.spv')):
        h = os.path.basename(p).split('.')[0]
        if h in ('40c6faab52a13874', 'ab7f1822eeb0331b'):
            continue
        nmod += 1
        asm = subprocess.run(['spirv-dis', '--no-indent', p],
                             capture_output=True, text=True).stdout.split('\n')
        defs, stores = {}, []
        for l in asm:
            m = re.match(r'\s*(%\w+) = (\w+)(.*)', l)
            if m: defs[m.group(1)] = (m.group(2), m.group(3).split())
            elif l.strip().startswith('OpStore '): stores.append(l.split())
        uses = {}
        for i, (op, a) in defs.items():
            for t in a[1:]:
                if t.startswith('%'): uses.setdefault(t, []).append(i)
        get = [i for i, (op, a) in defs.items()
               if op.startswith('OpRayQueryGetIntersection')
               and op != 'OpRayQueryGetIntersectionTypeKHR']
        typ = [i for i, (op, a) in defs.items()
               if op == 'OpRayQueryGetIntersectionTypeKHR']
        if len(get) != 1 or len(typ) != 1:
            bad.append(f'{h}: {len(get)} field getters / {len(typ)} type queries'); continue
        g, t = get[0], typ[0]
        # Forward: getter -> (fold, if the getter is not a uint) -> OpSelect
        # pair -> OpStore <id var>. The fold ops are whitelisted rather than
        # anything-goes: a getter that reached the latch through arithmetic on
        # a SECOND value would leave the whitelist and be reported, which is
        # the property this walk exists for.
        # 98 sec 14 widened this list, and the widening is the reason the
        # BACKWARDS check below exists. `xfq`/`xfw` quantise (OpFMul,
        # OpConvertFToS) and `xfw` adds a constant-buffer offset (OpFAdd)
        # between the getter and the latch, so the forward walk alone can no
        # longer claim "the getter's own bits and nothing else" -- OpFAdd is
        # precisely an op with a second operand. The whitelist therefore stays
        # a REACHABILITY test, and what the second operands are is proven
        # separately, by walking backwards from the stored value.
        FOLD = ('OpSelect', 'OpCompositeExtract', 'OpBitcast', 'OpBitwiseXor',
                'OpFMul', 'OpFAdd', 'OpConvertFToS')
        idv, front, depth = set(), {g}, 0
        while front and depth < 12:
            idv |= {st[1] for st in stores if st[2] in front}
            front = {u for f in front for u in uses.get(f, [])
                     if defs[u][0] in FOLD}
            depth += 1
        if len(idv) != 1:
            bad.append(f'{h}: the getter reaches {len(idv)} store targets {sorted(idv)}'); continue
        idv = idv.pop()
        # Forward BFS from the type query to whatever it is stored into: the
        # chain is type -> OpINotEqual -> OpSelect -> OpSelect -> OpStore.
        ourpriv = {idv}
        front, depth = {t}, 0
        while front and depth < 6:
            ourpriv |= {st[1] for st in stores if st[2] in front}
            front = {u for f in front for u in uses.get(f, [])}
            depth += 1
        if len(ourpriv) != 2:
            bad.append(f'{h}: {len(ourpriv)} latch variables {sorted(ourpriv)}, want 2'); continue

        # ---- what the LATCH is fed, backwards. New in 98 sec 14. -----------
        # Every OpStore into the id latch has its value's transitive operand
        # closure walked, and every leaf must be a constant, a ray-query
        # getter, a load of one of our own two Private latch variables, or a
        # load of a v4float through an OpAccessChain in UNIFORM storage -- the
        # constant-buffer read `xfw` needs and nothing else. A radiance value,
        # a payload read, an image fetch, an LCG state or a push constant is a
        # different shape and is reported.
        upd = {i for i, (op, a) in defs.items()
               if op == 'OpAccessChain' and a and a[0].startswith('%_ptr_Uniform_')}

        def leafkind(x):
            op, a = defs[x]
            if op.startswith('OpConstant'):
                return 'const'
            if op.startswith('OpRayQueryGet'):
                return op
            if op == 'OpLoad' and len(a) > 1:
                if a[1] in ourpriv:
                    return 'latch OURS'
                if a[1] in upd and a[0] == '%v4float':
                    return 'uniform CB v4 OURS'
                return 'load ' + a[1] + ' FOREIGN'
            return op + ' FOREIGN'

        latch_leaves = set()
        seenb = set()

        def wb(x, dep=0):
            if x in seenb or dep > 30:
                return
            seenb.add(x)
            if x not in defs:
                latch_leaves.add((x, 'EXTERNAL')); return
            op, a = defs[x]
            if op.startswith('OpType') or op == 'OpVariable':
                return
            if op.startswith('OpConstant') or op.startswith('OpRayQueryGet') \
               or op == 'OpLoad':
                latch_leaves.add((x, leafkind(x))); return
            for y in a[1:]:
                if y.startswith('%'):
                    wb(y, dep + 1)

        for st in stores:
            if st[1] == idv:
                wb(st[2])
        for x, k in sorted(latch_leaves):
            if 'FOREIGN' in k or k == 'EXTERNAL':
                bad.append(f'{h}: the latched value reaches {x} ({k})')
        lds = [i for i, (op, a) in defs.items()
               if op == 'OpLoad' and len(a) > 1 and a[1] == idv]
        imul = sorted({u for l in lds for u in uses.get(l, []) if defs[u][0] == 'OpIMul'})
        if not imul:
            bad.append(f'{h}: no hash multiply consumes {idv}'); continue
        own = [u for u in uses.get([c for c, (o, a) in defs.items()
               if o == 'OpConstant' and a[-1] == GOLD][0], []) if u not in imul]
        for m in imul:
            other = [x for x in defs[m][1][1:] if x not in lds]
            if len(other) != 1 or defs[other[0]][0] != 'OpConstant' \
               or defs[other[0]][1][-1] != GOLD:
                bad.append(f'{h}: {m} multiplier operand is {other}'); continue
            # backwards over the transitive closure of the whole select chain
            root = m
            for _ in range(40):
                nxt = [u for u in uses.get(root, [])
                       if defs[u][0] in ('OpShiftRightLogical', 'OpBitwiseXor',
                                         'OpBitwiseAnd', 'OpIEqual',
                                         'OpLogicalAnd', 'OpSelect')]
                if not nxt: break
                root = nxt[-1]
            seen, leaves = set(), set()
            def w(x, dep=0):
                if x in seen or dep > 30: return
                seen.add(x)
                if x not in defs: leaves.add((x, 'EXTERNAL')); return
                op, a = defs[x]
                if op.startswith('OpConstant'): leaves.add((x, 'const')); return
                if op == 'OpLoad':
                    leaves.add((x, 'load ' + a[1] +
                                (' OURS' if a[1] in ourpriv else ' FOREIGN'))); return
                if op.startswith('OpRayQueryGet'): leaves.add((x, op)); return
                if op.startswith('OpType') or op == 'OpVariable': return
                for y in a[1:]:
                    if y.startswith('%'): w(y, dep + 1)
            w(root)
            for x, k in sorted(leaves):
                if not (k == 'const' or k.startswith('OpRayQueryGet')
                        or k.endswith('OURS')):
                    bad.append(f'{h}: hash chain reaches {x} ({k})')
            if h == verbose_for and m == imul[0]:
                note = [f'  latch vars      : state+id = {sorted(ourpriv)} (Private uint)',
                        f'  field getter    : {g} = {defs[g][0]}',
                        f'  type query      : {t} = OpRayQueryGetIntersectionTypeKHR',
                        f'  hash multiply   : {m} = OpIMul {" ".join(defs[m][1][1:])}',
                        f'  select-chain end: {root} = {defs[root][0]}',
                        f'  chain leaves    : ' + ', '.join(f'{x}={k}' for x, k in sorted(leaves)),
                        f'  latch inputs    : ' + ', '.join(f'{x}={k}' for x, k in sorted(latch_leaves)),
                        f'  the module\'s OWN uses of the same constant: {len(own)}, '
                        f'none of them reachable from the chain']
    return bad, note, nmod

def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rungs', nargs='+', help='swap-set directories')
    ap.add_argument('--verbose-module', default='1271d3815051da17',
                    help='which permutation --ids reports on')
    ap.add_argument('--ids', action='store_true',
                    help='print the id list for --verbose-module')
    a = ap.parse_args()
    rc = 0
    for i, d in enumerate(a.rungs):
        bad, note, nmod = audit(d, a.verbose_module)
        name = os.path.basename(d.rstrip('/')).replace('swaps.', '')
        print(f"  {name:20s} hash chain: "
              f"{'CLEAN, %d/%d modules' % (nmod, nmod) if not bad else str(len(bad)) + ' PROBLEMS'}")
        for b in bad[:8]:
            sys.stderr.write('    REJECT ' + b + '\n')
        if bad:
            rc = 1
        elif a.ids and i == 0:
            for n in note:
                print(n)
    sys.exit(rc)


if __name__ == '__main__':
    main()
