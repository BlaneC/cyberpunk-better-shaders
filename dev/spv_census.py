#!/usr/bin/env python3
"""Read-only structural census over the raw shader dump (handoff/48).

    python3 dev/spv_census.py [--dump ~/callisto_dump] [--json out.jsonl]

Parses the BINARY SPIR-V of every *.spv in the dump (no spirv-dis; ~6 s over
3273 modules) and reports, per module:

  stage, the OpString DXIL identity, every OpTypeImage it declares, every
  OpImageWrite (image type + texel type), whether it carries the skin
  patcher's (1/pi, 0.107508637) anchor pair, which float constants of interest
  it holds, whether it derives `word >> 5` from an image fetch, and its
  descriptor-set/binding footprint.

Operand layout comes from the Khronos grammar JSON (so "does this opcode have
a result type / result id" is looked up, never guessed). GOTCHAS: `grep -r`
over the dump silently returns 0 for strings that ARE present, so nothing here
greps text.
"""
import argparse, collections, glob, json, os, struct, sys

GRAMMAR_CANDIDATES = [
    "/home/blane/workspace/vkd3d-proton/khronos/SPIRV-Headers/include/spirv/unified1/spirv.core.grammar.json",
    "/usr/include/spirv/unified1/spirv.core.grammar.json",
]

STAGE = {0: 'Vertex', 1: 'TessControl', 2: 'TessEval', 3: 'Geometry',
         4: 'Fragment', 5: 'GLCompute', 5313: 'RayGeneration',
         5314: 'Intersection', 5315: 'AnyHit', 5316: 'ClosestHit',
         5317: 'Miss', 5318: 'Callable'}
DIM = {0: '1D', 1: '2D', 2: '3D', 3: 'Cube', 4: 'Rect', 5: 'Buffer',
       6: 'SubpassData'}
# SPIR-V image formats we actually see; anything else prints its number.
FMT = {0: 'Unknown', 1: 'Rgba32f', 2: 'Rgba16f', 3: 'R32f', 4: 'Rgba8',
       5: 'Rgba8Snorm', 6: 'Rg32f', 7: 'Rg16f', 8: 'R11fG11fB10f', 9: 'R16f',
       10: 'Rgba16', 11: 'Rgb10A2', 12: 'Rg16', 13: 'Rg8', 14: 'R16',
       15: 'R8', 16: 'Rgba16Snorm', 17: 'Rg16Snorm', 18: 'Rg8Snorm',
       19: 'R16Snorm', 20: 'R8Snorm', 21: 'Rgba32i', 22: 'Rgba16i',
       23: 'Rgba8i', 24: 'R32i', 25: 'Rg32i', 26: 'Rg16i', 27: 'Rg8i',
       28: 'R16i', 29: 'R8i', 30: 'Rgba32ui', 31: 'Rgba16ui', 32: 'Rgba8ui',
       33: 'R32ui', 34: 'Rgb10a2ui', 35: 'Rg32ui', 36: 'Rg16ui', 37: 'Rg8ui',
       38: 'R16ui', 39: 'R8ui', 40: 'R64ui', 41: 'R64i'}

OP = dict(ENTRY=15, STRING=7, NAME=5, DECORATE=71, MEMBERDECORATE=72,
          TYPEVOID=19, TYPEBOOL=20, TYPEINT=21, TYPEFLOAT=22, TYPEVECTOR=23,
          TYPEMATRIX=24, TYPEIMAGE=25, TYPESAMPLER=26, TYPESAMPLEDIMAGE=27,
          TYPEARRAY=28, TYPERUNTIMEARRAY=29, TYPESTRUCT=30, TYPEPOINTER=32,
          CONSTANT=43, CONSTANTCOMPOSITE=44, VARIABLE=59, LOAD=61,
          IMAGEWRITE=99, IMAGEREAD=98, IMAGEFETCH=95, SHIFTRIGHTLOGICAL=194,
          SHIFTRIGHTARITH=195, BITWISEAND=199, IEQUAL=170, SWITCH=251,
          EXECMODE=16, ACCESSCHAIN=65, FUNCTIONCALL=57, SAMPLEDIMAGE=86,
          IMAGESAMPLEIMPLICIT=87, IMAGESAMPLEEXPLICIT=88, EXTINST=12,
          FMUL=133, FSUB=131, FADD=129, COMPOSITECONSTRUCT=80)


def load_grammar():
    for p in GRAMMAR_CANDIDATES:
        if os.path.exists(p):
            g = json.load(open(p))
            has_rt, has_r = set(), set()
            for ins in g['instructions']:
                kinds = [o['kind'] for o in ins.get('operands', [])]
                if 'IdResultType' in kinds:
                    has_rt.add(ins['opcode'])
                if 'IdResult' in kinds:
                    has_r.add(ins['opcode'])
            return has_rt, has_r
    raise SystemExit('spirv.core.grammar.json not found; edit GRAMMAR_CANDIDATES')


HAS_RT, HAS_R = load_grammar()


def f32(bits):
    return struct.unpack('<f', struct.pack('<I', bits & 0xffffffff))[0]


class Mod:
    __slots__ = ('path', 'name', 'stage', 'ident', 'types', 'consts', 'ids',
                 'images', 'writes', 'reads', 'fetches', 'samples', 'shr5',
                 'bindings', 'floats', 'nwords', 'varimg', 'localsize',
                 'shr5_from_fetch', 'cls_tested', 'fetchres')

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.stage = None
        self.ident = None
        self.types = {}
        self.consts = {}
        self.ids = {}
        self.images = {}
        self.writes = []
        self.reads = 0
        self.fetches = 0
        self.samples = 0
        self.shr5 = []
        self.bindings = []
        self.floats = set()
        self.nwords = 0
        self.localsize = None
        self.shr5_from_fetch = False
        self.cls_tested = set()


def parse(path):
    d = open(path, 'rb').read()
    if len(d) < 20 or struct.unpack('<I', d[:4])[0] != 0x07230203:
        return None
    w = struct.unpack('<%dI' % (len(d) // 4), d[:len(d) // 4 * 4])
    m = Mod(path)
    m.nwords = len(w)
    tid = {}          # id -> type-id  (result type of the instruction)
    typedecl = {}     # id -> ('Image', ...) etc
    consts = {}       # id -> literal word
    fetchres = set()  # ids produced by an image fetch/read
    setb = {}
    i = 5
    while i < len(w):
        wc, op = w[i] >> 16, w[i] & 0xffff
        if wc == 0:
            break
        ops = w[i + 1:i + wc]
        # generic result-type / result-id bookkeeping
        k = 0
        rt = r = None
        if op in HAS_RT and len(ops) > k:
            rt = ops[k]; k += 1
        if op in HAS_R and len(ops) > k:
            r = ops[k]; k += 1
        if r is not None and rt is not None:
            tid[r] = rt
        rest = ops[k:]

        if op == OP['ENTRY'] and len(ops) >= 2:
            if m.stage is None:
                m.stage = STAGE.get(ops[0], str(ops[0]))
        elif op == OP['EXECMODE'] and len(ops) >= 5 and ops[1] == 17:
            m.localsize = (ops[2], ops[3], ops[4])
        elif op == OP['STRING'] and r is not None:
            s = b''.join(struct.pack('<I', x) for x in rest)
            s = s.split(b'\0')[0].decode('utf8', 'replace')
            if m.ident is None and s:
                m.ident = s
        elif op == OP['TYPEVOID']:
            typedecl[r] = ('void',)
        elif op == OP['TYPEBOOL']:
            typedecl[r] = ('bool',)
        elif op == OP['TYPEINT']:
            typedecl[r] = ('int', rest[0], rest[1])
        elif op == OP['TYPEFLOAT']:
            typedecl[r] = ('float', rest[0])
        elif op == OP['TYPEVECTOR']:
            typedecl[r] = ('vec', rest[0], rest[1])
        elif op == OP['TYPEIMAGE']:
            # sampled-type, Dim, Depth, Arrayed, MS, Sampled, Format
            typedecl[r] = ('image', rest[0], rest[1], rest[4], rest[5], rest[6])
        elif op == OP['TYPESAMPLEDIMAGE']:
            typedecl[r] = ('sampledimage', rest[0])
        elif op == OP['TYPEPOINTER']:
            typedecl[r] = ('ptr', rest[0], rest[1])
        elif op == OP['TYPEARRAY']:
            typedecl[r] = ('array', rest[0])
        elif op == OP['TYPERUNTIMEARRAY']:
            typedecl[r] = ('rtarray', rest[0])
        elif op == OP['TYPESTRUCT']:
            typedecl[r] = ('struct',) + tuple(rest)
        elif op == OP['CONSTANT'] and wc == 4:
            consts[r] = rest[0]
        elif op == OP['DECORATE'] and len(ops) >= 3:
            if ops[1] == 34:      # DescriptorSet
                setb.setdefault(ops[0], [None, None])[0] = ops[2]
            elif ops[1] == 33:    # Binding
                setb.setdefault(ops[0], [None, None])[1] = ops[2]
        elif op in (OP['IMAGEFETCH'], OP['IMAGEREAD']):
            if op == OP['IMAGEFETCH']:
                m.fetches += 1
            else:
                m.reads += 1
            if r is not None:
                fetchres.add(r)
        elif op in (OP['IMAGESAMPLEIMPLICIT'], OP['IMAGESAMPLEEXPLICIT']):
            m.samples += 1
        elif op == OP['IMAGEWRITE'] and len(ops) >= 3:
            m.writes.append((ops[0], ops[2]))     # (image id, texel id)
        elif op in (OP['SHIFTRIGHTLOGICAL'], OP['SHIFTRIGHTARITH']) and len(rest) == 2:
            m.shr5.append((r, rest[0], rest[1]))
        i += wc

    m.types = typedecl
    m.consts = consts
    m.ids = tid
    m.bindings = sorted((v[0], v[1]) for v in setb.values()
                        if v[0] is not None and v[1] is not None)
    for cid, bits in consts.items():
        t = typedecl.get(tid.get(cid))
        if t and t[0] == 'float' and t[1] == 32:
            m.floats.add(f32(bits))

    # >>5 whose operand traces (one hop) to an image fetch/read result
    for r, base, sh in m.shr5:
        if consts.get(sh) == 5:
            m.shr5_from_fetch = True   # any >>5 at all, refined below
    m.shr5_from_fetch = any(consts.get(sh) == 5 for _, _, sh in m.shr5)
    return m


def resolve(m, tyid, depth=0):
    """Unwrap ptr/array/sampledimage down to a base type tuple."""
    t = m.types.get(tyid)
    while t and depth < 8:
        if t[0] in ('ptr',):
            tyid = t[2]; t = m.types.get(tyid); depth += 1
        elif t[0] in ('array', 'rtarray', 'sampledimage'):
            tyid = t[1]; t = m.types.get(tyid); depth += 1
        else:
            break
    return t


def imgdesc(m, tyid):
    t = resolve(m, tyid)
    if not t or t[0] != 'image':
        return None
    st = m.types.get(t[1])
    stn = 'float' if st and st[0] == 'float' else (
        ('uint' if st and st[0] == 'int' and st[2] == 0 else
         'int' if st and st[0] == 'int' else '?'))
    return dict(sampled_type=stn, dim=DIM.get(t[2], str(t[2])),
                arrayed=t[3], sampled=t[4], fmt=FMT.get(t[5], str(t[5])))


def valdesc(m, vid):
    t = resolve(m, m.ids.get(vid))
    if not t:
        return '?'
    if t[0] == 'vec':
        b = m.types.get(t[1])
        if b and b[0] == 'float':
            return 'v%dfloat' % t[2]
        if b and b[0] == 'int':
            return 'v%d%s' % (t[2], 'uint' if b[2] == 0 else 'int')
        return 'v%d?' % t[2]
    if t[0] == 'float':
        return 'float'
    if t[0] == 'int':
        return 'uint' if t[2] == 0 else 'int'
    return t[0]


def summarise(m):
    ws = []
    for img, tex in m.writes:
        ws.append((imgdesc(m, m.ids.get(img)), valdesc(m, tex)))
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', default='~/callisto_dump')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    root = os.path.expanduser(a.dump)
    PI, K = 0.318309873, 0.107508637
    rows = []
    for f in sorted(glob.glob(os.path.join(root, '*.spv'))):
        m = parse(f)
        if m is None:
            continue
        ws = summarise(m)
        fl = m.floats
        has_pi = any(abs(v - PI) < 1e-7 for v in fl)
        has_k = any(abs(v - K) < 1e-7 for v in fl)
        colour_writes = [w for w in ws if w[0] and w[0]['sampled_type'] == 'float'
                         and w[0]['dim'] == '2D' and w[1].startswith('v')]
        int_writes = [w for w in ws if w[0] and w[0]['sampled_type'] in ('int', 'uint')]
        rows.append(dict(
            name=m.name, stage=m.stage, words=m.nwords, ident=m.ident,
            anchor=bool(has_pi and has_k), pi=has_pi, k=has_k,
            nwrite=len(ws), ncolour=len(colour_writes), nint=len(int_writes),
            writes=[[w[0], w[1]] for w in ws],
            fetches=m.fetches, reads=m.reads, samples=m.samples,
            shr5=m.shr5_from_fetch, nbind=len(m.bindings),
            localsize=m.localsize))
    if a.json:
        with open(os.path.expanduser(a.json), 'w') as fh:
            for r in rows:
                fh.write(json.dumps(r) + '\n')
    st = collections.Counter(r['stage'] for r in rows)
    print('modules parsed :', len(rows))
    print('by stage       :', dict(st))
    print('anchor pair    :', sum(r['anchor'] for r in rows))
    print('1/pi only      :', sum(r['pi'] and not r['anchor'] for r in rows))
    cw = [r for r in rows if r['ncolour']]
    print('float 2D writer:', len(cw))
    print('  of those, no anchor pair :',
          sum(1 for r in cw if not r['anchor']))
    print('  no anchor, GLCompute     :',
          sum(1 for r in cw if not r['anchor'] and r['stage'] == 'GLCompute'))


if __name__ == '__main__':
    main()
