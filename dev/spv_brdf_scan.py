#!/usr/bin/env python3
"""Read-only BRDF/class census over the shader dump (handoff/48).

    python3 dev/spv_brdf_scan.py [--dump ~/callisto_dump] [--journal ~/callisto_swap.jsonl]

For every module in the dump, from the BINARY SPIR-V, decides:

  write_colour  does it OpImageWrite a float vector into a float 2D image
  anchor        does it carry BOTH float32(1/pi) and float32(0.107508637)
                -- the pair dev/patch_compute_skin.sh selects on
  pi            does it carry float32(1/pi) at all
  pow5          Log2 -> FMul(...,5) -> Exp2  (Schlick's (1-c)^5)
  ggx           an FMul by float32(pi) or FDiv by it (the GGX D denominator)
  cls           `OpCompositeExtract 1` of an OpImageFetch %v4uint, then >>5
                (the material-class byte, handoff/40)
  cls1          that class value compared against, or switched on, 1 (= skin)
  disp          how many times the layer journal saw it dispatch / trace

`grep -r` over the dump silently returns 0 for strings that ARE present
(GOTCHAS), so nothing here greps text.
"""
import argparse, collections, glob, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spv_census import parse, imgdesc, valdesc, resolve, OP, f32

LOG2, EXP2 = 30, 29          # GLSL.std.450 Log2 / Exp2
FMUL, FDIV, FSUB = 133, 136, 131
EXTINST, IEQUAL, SWITCH, COMPEXTRACT = 12, 170, 251, 81
IMAGEFETCH, IMAGEREAD, SHR = 95, 98, 194
PI_INV, KRETRO, PI = 0.318309873, 0.107508637, 3.14159274


def scan(path):
    m = parse(path)
    if m is None:
        return None
    d = open(path, 'rb').read()
    w = struct.unpack('<%dI' % (len(d) // 4), d[:len(d) // 4 * 4])
    consts, tid = {}, m.ids
    fetch_uint, extract1, shr5, cls_ids, cls1 = set(), {}, {}, set(), False
    log2_res, mul5_res, exp2 = set(), set(), False
    ggx = False
    cmps, sw = [], []
    i = 5
    while i < len(w):
        wc, op = w[i] >> 16, w[i] & 0xffff
        if wc == 0:
            break
        ops = w[i + 1:i + wc]
        if op == OP['CONSTANT'] and wc == 4:
            consts[ops[1]] = ops[2]
        elif op == IMAGEFETCH or op == IMAGEREAD:
            t = resolve(m, m.ids.get(ops[1]))
            if t and t[0] == 'vec':
                b = m.types.get(t[1])
                if b and b[0] == 'int':
                    fetch_uint.add(ops[1])
        elif op == COMPEXTRACT and wc == 5 and ops[3] == 1:
            extract1[ops[1]] = ops[2]
        elif op == SHR and wc == 5:
            shr5[ops[1]] = (ops[2], ops[3])
        elif op == EXTINST and wc >= 5:
            which = ops[3]
            if which == LOG2:
                log2_res.add(ops[1])
            elif which == EXP2 and len(ops) > 4 and ops[4] in mul5_res:
                exp2 = True
        elif op == FMUL and wc == 5:
            a, b = ops[2], ops[3]
            fv = [consts.get(x) for x in (a, b)]
            for x, o in ((a, b), (b, a)):
                if x in consts and abs(f32(consts[x]) - 5.0) < 1e-6 and o in log2_res:
                    mul5_res.add(ops[1])
            for x in (a, b):
                if x in consts and abs(f32(consts[x]) - PI) < 1e-5:
                    ggx = True
        elif op == FDIV and wc == 5:
            for x in ops[2:4]:
                if x in consts and abs(f32(consts[x]) - PI) < 1e-5:
                    ggx = True
        elif op == IEQUAL and wc == 5:
            cmps.append((ops[2], ops[3]))
        elif op == SWITCH and wc >= 5:
            sw += [(ops[0], w[j]) for j in range(i + 3, i + wc, 2)]
        i += wc

    # material class = (fetch(v4uint).y) >> 5
    for r, (base, sh) in shr5.items():
        if consts.get(sh) == 5 and base in extract1 and extract1[base] in fetch_uint:
            cls_ids.add(r)
    for a, b in cmps:
        for x, o in ((a, b), (b, a)):
            if x in cls_ids and o in consts and consts[o] == 1:
                cls1 = True
    for sel, lit in sw:
        if sel in cls_ids and lit == 1:
            cls1 = True

    fl = m.floats
    ws = [(imgdesc(m, m.ids.get(im)), valdesc(m, tx)) for im, tx in m.writes]
    colour = [x for x in ws if x[0] and x[0]['sampled_type'] == 'float'
              and x[0]['dim'] == '2D' and x[1].startswith('v')
              and x[1].endswith('float')]
    return dict(
        name=m.name, stage=m.stage, words=m.nwords,
        write_colour=len(colour),
        anchor=any(abs(v - PI_INV) < 1e-7 for v in fl) and
               any(abs(v - KRETRO) < 1e-7 for v in fl),
        pi=any(abs(v - PI_INV) < 1e-7 for v in fl),
        pow5=exp2, ggx=ggx, cls=len(cls_ids) > 0, cls1=cls1,
        nfetch=m.fetches, nread=m.reads, localsize=m.localsize)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', default='~/callisto_dump')
    ap.add_argument('--journal', default='~/callisto_swap.jsonl')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    disp = collections.Counter()
    jp = os.path.expanduser(a.journal)
    if os.path.exists(jp):
        for l in open(jp):
            if '"dispatch"' in l or '"trace_rays"' in l:
                try:
                    dd = json.loads(l)
                except ValueError:
                    continue
                k = dd.get('id') or dd.get('rgs') or ''
                if k:
                    disp[k.split('.')[0]] += 1
    rows = []
    for f in sorted(glob.glob(os.path.expanduser(a.dump) + '/*.spv')):
        r = scan(f)
        if r:
            r['disp'] = disp.get(r['name'].split('.')[0], 0)
            rows.append(r)
    if a.json:
        with open(os.path.expanduser(a.json), 'w') as fh:
            for r in rows:
                fh.write(json.dumps(r) + '\n')

    def n(pred):
        return sum(1 for r in rows if pred(r))
    print(f"modules                                        : {len(rows)}")
    print(f"anchor pair (1/pi AND 0.107508637)             : {n(lambda r: r['anchor'])}")
    print(f"  ... in *.dxil.spv (what the patcher globs)   : "
          f"{n(lambda r: r['anchor'] and r['name'].endswith('.dxil.spv'))}")
    print(f"  ... NOT *.dxil.spv (glob-excluded)           : "
          f"{n(lambda r: r['anchor'] and not r['name'].endswith('.dxil.spv'))}")
    print(f"writes float colour to a 2D image              : {n(lambda r: r['write_colour'])}")
    print(f"  ... and NOT anchored                         : "
          f"{n(lambda r: r['write_colour'] and not r['anchor'])}")
    print(f"  ... + BRDF math (pow5 or ggx)                : "
          f"{n(lambda r: r['write_colour'] and not r['anchor'] and (r['pow5'] or r['ggx']))}")
    print(f"  ... + reads the material class byte          : "
          f"{n(lambda r: r['write_colour'] and not r['anchor'] and (r['pow5'] or r['ggx']) and r['cls'])}")
    print(f"  ... + tests class == 1 (skin)                : "
          f"{n(lambda r: r['write_colour'] and not r['anchor'] and (r['pow5'] or r['ggx']) and r['cls1'])}")
    print(f"  ... + seen dispatching / tracing in journal  : "
          f"{n(lambda r: r['write_colour'] and not r['anchor'] and (r['pow5'] or r['ggx']) and r['cls1'] and r['disp'])}")
    print()
    print("FINALISTS (float-colour writer, no anchor pair, BRDF math, class==1 test):")
    fin = [r for r in rows if r['write_colour'] and not r['anchor']
           and (r['pow5'] or r['ggx']) and r['cls1']]
    for r in sorted(fin, key=lambda r: -r['words']):
        print(f"  {r['name']:52s} {r['stage']:12s} w={r['words']:6d} "
              f"col={r['write_colour']} pi={int(r['pi'])} pow5={int(r['pow5'])} "
              f"ggx={int(r['ggx'])} disp={r['disp']:4d} ls={r['localsize']}")
    print()
    print("ANCHORED modules the *.dxil.spv glob excludes:")
    for r in sorted([r for r in rows if r['anchor'] and not r['name'].endswith('.dxil.spv')],
                    key=lambda r: r['name']):
        print(f"  {r['name']:52s} {r['stage']:12s} w={r['words']:6d} "
              f"col={r['write_colour']} cls={int(r['cls'])} cls1={int(r['cls1'])} disp={r['disp']:4d}")


if __name__ == '__main__':
    main()
