#!/usr/bin/env python3
"""
hunt_u3.py -- G-U3: who actually READS the R8_UINT G-buffer slot (38 U3)?

For every module the prov log shows binding a target image, parse its
disassembly for the bindless fetch idiom

    %a = OpAccessChain %_ptr_PushConstant_uint %registers %uint_<PC>
    %b = OpLoad %uint %a
    %c = OpIAdd %uint %b %uint_<OFF>          (absent => OFF = 0)
    %d = OpAccessChain %_ptr_UniformConstant_* %<heap> %c
    %e = OpLoad %<imgty> %d

infer each pc-register's table base from the prov idx set (base = min idx,
checked for consistency against every fetched offset), and report whether the
offset that resolves to the target image is fetched at all -- and if so, by
which SSA id, so the semantic trace can start there.

KNOWN LIMIT (measured, 54 s3): the probe's pc attribution can mix two tables
into one pc row-set, so base = min(idx) can be WRONG. 99bb7c2698997b2a's true
pc[1] base is 82698 (format-anchored by hand: +1=D32 float, +2=RGBA8 float,
+4=R8_UINT uint, +7=A2B10G10R10 float all match), not min(idx)=82696 -- the
tool prints "+6 unread" for it and the truth is "+4 READ". Treat every
BASE-UNCERTAIN row as UNRESOLVED and format-anchor it by hand before believing
a verdict. Rows whose fetched-offset set maps cleanly (family A) are reliable.

Usage: hunt_u3.py LOG IMAGE_HANDLE [--disasm DIR ...]
Reproduce (54):
  python3 CallistoSSS/dev/hunt_u3.py analysis/evidence/meta/capA_prov.jsonl \
      0x1c850e10 --disasm CallistoSSS/dev/disasm/compute <scratch>/u3disasm
"""
import argparse, collections, glob, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prov_map import load, desc

FETCH_AC = re.compile(r'^\s*(%\w+)\s*=\s*OpAccessChain\s+%_ptr_PushConstant_uint\s+'
                      r'%registers\s+%uint_(\d+)\s*$')
LOAD    = re.compile(r'^\s*(%\w+)\s*=\s*OpLoad\s+%uint\s+(%\w+)\s*$')
IADD    = re.compile(r'^\s*(%\w+)\s*=\s*OpIAdd\s+%uint\s+(%\w+)\s+%uint_(\d+)\s*$')
HEAP_AC = re.compile(r'^\s*(%\w+)\s*=\s*OpAccessChain\s+%_ptr_UniformConstant_(\w+)\s+'
                     r'(%\w+)\s+(%\w+)\s*$')
IMGTY   = re.compile(r'^\s*%(\w+)\s*=\s*OpTypeImage\s+%(\w+)\s+2D\s+\d+\s+\d+\s+\d+\s+(\d+)')
IMGLOAD = re.compile(r'^\s*(%\w+)\s*=\s*OpLoad\s+%\w+\s+(%\w+)\s*$')


def fetches(path):
    """-> list of (pc, off, handle_ssa_id)"""
    lines = open(path).read().splitlines()
    ac_pc, ld_of, add_of, imgty = {}, {}, {}, {}
    out = []
    for ln in lines:
        m = IMGTY.match(ln)
        if m: imgty[m.group(1)] = (m.group(2), 'storage' if m.group(3) == '2' else 'sampled')
        m = FETCH_AC.match(ln)
        if m: ac_pc[m.group(1)] = int(m.group(2)); continue
        m = LOAD.match(ln)
        if m and m.group(2) in ac_pc:
            ld_of[m.group(1)] = ac_pc[m.group(2)]; continue
        m = IADD.match(ln)
        if m and m.group(2) in ld_of:
            add_of[m.group(1)] = (ld_of[m.group(2)], int(m.group(3))); continue
        m = HEAP_AC.match(ln)
        if m:
            idx = m.group(4)
            if idx in add_of:
                pc, off = add_of[idx]
            elif idx in ld_of:
                pc, off = ld_of[idx], 0
            else:
                continue
            ty = imgty.get(m.group(2), ('?', '?'))
            out.append((pc, off, m.group(1), ty))
    # second pass: map heap-AC id -> image handle load id
    ac_ids = {h: (pc, off, ty) for pc, off, h, ty in out}
    final = []
    for ln in lines:
        m = IMGLOAD.match(ln)
        if m and m.group(2) in ac_ids:
            pc, off, ty = ac_ids[m.group(2)]
            final.append((pc, off, m.group(1), ty))
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log'); ap.add_argument('image')
    ap.add_argument('--disasm', nargs='+', required=True)
    a = ap.parse_args()
    imgs, views, prov = load(a.log)
    print(f'target {a.image} {desc(imgs, a.image)}')

    by_mod = collections.defaultdict(list)
    for p in prov:
        by_mod[p['id']].append(p)
    binders = sorted({p['id'] for p in prov if p['img'] == a.image})

    for mid in binders:
        f = None
        for d in a.disasm:
            c = os.path.join(d, mid + '.dxil.spvasm')
            if os.path.exists(c): f = c; break
        if not f:
            print(f'{mid}  NO-DISASM'); continue
        fx = fetches(f)
        rows = by_mod[mid]
        verdicts = []
        for p in (r for r in rows if r['img'] == a.image):
            pc = p['pc']
            idxs = sorted({r['idx'] for r in rows if r['pc'] == pc})
            base = min(idxs)
            offs = sorted({o for c, o, _, _ in fx if c == pc})
            ok = all(base + o in idxs for o in offs)
            toff = p['idx'] - base
            # a claimed hit must also LOAD as a sampled uint image -- an
            # R8_UINT cannot come back as float or storage (kills the
            # base-inference false positive measured on 9b7a5e20 pc[5])
            hit = [f'{h}({t[0]},{t[1]})' for c, o, h, t in fx
                   if c == pc and o == toff and t == ('uint', 'sampled')]
            near = [f'+{o}:{t[0]}/{t[1]}' for c, o, _, t in fx if c == pc]
            verdicts.append((pc, toff, bool(hit), ok, hit[:3], offs, near))
        for pc, toff, read, ok, ids, offs, near in verdicts:
            flag = 'READ' if read else 'unread'
            note = '' if ok else '  BASE-UNCERTAIN(' + ' '.join(near) + ')'
            print(f'{mid}  pc[{pc}] +{toff}  {flag:6s} fetched-offsets={offs}'
                  f'{"  ids=" + ",".join(ids) if ids else ""}{note}')


if __name__ == '__main__':
    main()
