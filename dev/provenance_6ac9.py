#!/usr/bin/env python3
"""
provenance_6ac9.py -- what does 6ac9085c9bd4b7da (the temporal resolve) read,
and who writes its current-lighting input?

Stage 1: find 6ac9's dispatches in capA, decode push constants, resolve the
         bindless-heap image descriptors for its slots (material/velocity/
         current/history/output).
Stage 2: invert the heap -- all storage-image descriptors for those images.
Stage 3: scan every dispatch's push constants for those storage indices ->
         candidate writer modules.

Reuse of calibrate_heap.py's model: vkGetDescriptor pData points into the
mapped heap buffer; set1 = bindless image heap, 4-byte image descriptors.
"""
import json, struct
from collections import defaultdict

LOG = '/home/blane/Documents/NVIDIA Nsight Graphics/GraphicsCaptures/analysis/evidence/meta/capA_probe.jsonl'
TARGET_ID = '6ac9085c9bd4b7da'
TARGET_SPV_SIZE = 6452

images, views, writes = {}, {}, []
pipes, mods = {}, {}
mapmem, bindbuf, bufaddr, buffers = [], {}, {}, {}
# per-cb stream state -> dispatches
cb_state = defaultdict(dict)
dispatches = []          # (seq, cb, pipe, push_hex, desc_infos, set_offs)

for line in open(LOG):
    try: d = json.loads(line)
    except: continue
    ev = d['ev']
    if ev == 'CreateImage': images[d['img']] = d
    elif ev == 'CreateImageView': views[d['view']] = d['img']
    elif ev == 'GetDescriptor': writes.append(d)
    elif ev == 'CreateShaderModule': mods[d['mod']] = d
    elif ev == 'CreateComputePipeline': pipes[d['pipe']] = d
    elif ev == 'MapMemory': mapmem.append((d['mem'], d['off'], d['size'], int(d['ptr'], 16)))
    elif ev == 'BindBufferMemory': bindbuf[d['buf']] = (d['mem'], d['off'])
    elif ev == 'GetBufferDeviceAddress': bufaddr[d['buf']] = int(d['addr'], 16)
    elif ev == 'CreateBuffer': buffers[d['buf']] = d['size']
    elif ev == 'CmdBindPipeline' and d.get('bp') == 1:
        cb_state[d['cb']]['pipe'] = d['pipe']
    elif ev == 'CmdPushConstants':
        cb_state[d['cb']]['push'] = d['hex']
    elif ev == 'CmdBindDescriptorBuffers':
        cb_state[d['cb']]['infos'] = [i['addr'] for i in d['infos']]
    elif ev == 'CmdSetDescriptorBufferOffsets':
        cb_state[d['cb']]['offs'] = {o['set']: (o['bufIdx'], o['off']) for o in d['offs']}
    elif ev in ('CmdDispatch', 'CmdDispatchIndirect'):
        st = cb_state[d['cb']]
        dispatches.append((d['seq'], d['cb'], st.get('pipe'),
                           st.get('push'), st.get('infos'), st.get('offs')))

def cpu_of(va):
    for b, bv in bufaddr.items():
        if bv <= va < bv + buffers.get(b, 0):
            mem, memoff = bindbuf[b]
            for mmem, moff, msize, mptr in mapmem:
                if mmem == mem and moff <= memoff < moff + msize:
                    return mptr + (memoff - moff) + (va - bv)
    return None

by_pdata = defaultdict(list)
for w in writes:
    by_pdata[int(w['pData'], 16)].append(w)

# 6ac9's module handle(s): match by spv size
target_mods = [h for h, m in mods.items() if m.get('size') == TARGET_SPV_SIZE]
print(f'module handles with size {TARGET_SPV_SIZE}: {len(target_mods)}')
target_pipes = [p for p, c in pipes.items() if c.get('mod') in target_mods]
print(f'pipelines: {len(target_pipes)}')

tg = [d for d in dispatches if d[2] in target_pipes]
print(f'6ac9 dispatches in capA: {len(tg)}')
if not tg:
    raise SystemExit('6ac9 never dispatched in capA -- need another frame')

def heap_entry(set_va, idx, stride=4):
    cpu = cpu_of(set_va)
    if cpu is None: return None, f'no cpu map for {set_va:#x}'
    p = cpu + idx * stride
    ws = by_pdata.get(p)
    if not ws: return None, f'nothing at idx {idx}'
    w = ws[-1]
    v = w.get('view'); i = views.get(v)
    im = images.get(i, {})
    return (w, f'type={w["type"]} img={i} fmt={im.get("format")} '
               f'{im.get("w")}x{im.get("h")} usage={im.get("usage")}')

for seq, cb, pipe, push, infos, offs in tg[:3]:
    print(f'\n--- dispatch seq={seq} pipe={pipe}')
    if not (push and infos and offs): print('  incomplete state'); continue
    pc = struct.unpack('<%dI' % (len(bytes.fromhex(push))//4), bytes.fromhex(push))
    print('  push dwords:', [hex(x) for x in pc[:8]])
    bufIdx, off = offs.get(1, (None, None))
    if bufIdx is None: print('  no set1 offset'); continue
    set1_va = int(infos[bufIdx], 16) + off
    print(f'  set1 VA = {set1_va:#x}')
    base = pc[1]
    for label, idx in [('history  (p1+0)', base), ('current  (p1+1)', base+1),
                       ('velocity (p1+5)', base+5), ('material (p1+6)', base+6),
                       ('output   (p5)', pc[5])]:
        w, s = heap_entry(set1_va, idx)
        print(f'   {label} idx={idx}: {s}')
