#!/usr/bin/env python3
"""
prov_analyze.py -- read /tmp/prov.jsonl (NGFX_PROV live run) and answer:
  1. what images does 6ac9085c9bd4b7da read/write (its slot -> image map)
  2. which modules WRITE its current-lighting input (storage-image slots
     referencing the same image) -> the evaluator set
"""
import json, sys, glob, os

LOG = sys.argv[1] if len(sys.argv) > 1 else '/tmp/prov.jsonl'
DUMP = os.path.expanduser('~/callisto_dump')
TARGET = '6ac9085c9bd4b7da'

def fnv1a64(path):
    h = 0xcbf29ce484222325
    for b in open(path, 'rb').read():
        h ^= b; h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

# fnv -> dxil id from the dump
fnv2id = {}
for f in glob.glob(DUMP + '/*.dxil.spv'):
    fnv2id['%016x' % fnv1a64(f)] = os.path.basename(f)[:16]

imgs, views, prov = {}, {}, []
for line in open(LOG):
    try: d = json.loads(line)
    except: continue
    ev = d.get('ev')
    if ev == 'CreateImage': imgs[d['img']] = d
    elif ev == 'CreateImageView': views[d['view']] = d['img']
    elif ev == 'prov':
        d['id'] = fnv2id.get(d['fnv'], d['fnv'])
        prov.append(d)

def desc(v):
    i = views.get(v)
    im = imgs.get(i, {})
    return f"img={i} fmt={im.get('format')} {im.get('w')}x{im.get('h')} usage={im.get('usage')}"

print(f'{len(prov)} prov events, {len(set(p["id"] for p in prov))} modules')
tgt = [p for p in prov if p['id'] == TARGET]
print(f'\n=== {TARGET} slots ({len(tgt)} events) ===')
for p in sorted(tgt, key=lambda p: (p['pc'], p['idx'], p['stride'])):
    print(f"  pc={p['pc']} idx={p['idx']} stride={p['stride']} "
          f"type={p['type']} {desc(p['view'])}")

if tgt:
    # candidate input images = sampled (type 1/2) slots of 6ac9
    inputs = sorted({views.get(p['view']) for p in tgt if p['type'] in (1, 2)})
    print('\n=== writers of 6ac9 input images (storage slots elsewhere) ===')
    for p in prov:
        if p['id'] == TARGET or p['type'] != 3: continue
        if views.get(p['view']) in inputs:
            print(f"  {p['id']}: pc={p['pc']} idx={p['idx']} stride={p['stride']}"
                  f" -> {desc(p['view'])}")
