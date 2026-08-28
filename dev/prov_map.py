#!/usr/bin/env python3
"""
prov_map.py -- build the compute render-graph from an ngfx-replay prov log.

Produces:
  1. per-module slot map (which heap index -> which image, with format/size)
  2. per-image writer/reader sets  == the "who computes this buffer" answer

Generate the log OFFLINE (no game launch) with:

  cd GraphicsCaptures
  VK_ADD_LAYER_PATH=$PWD/analysis/probe VK_INSTANCE_LAYERS=VK_LAYER_NGFXPROBE_probe \
  CALLISTO_LAYER_DISABLE=1 NGFXPROBE_STRIP_ALLOC=3 \
  NGFXPROBE_LOG=$PWD/analysis/evidence/meta/capA_prov.jsonl \
  NGFX_PROV=1 NGFX_PROV_ONLY=1 \
  /opt/nvidia/nsight-graphics-for-linux/nsight-graphics-for-linux-2026.3.1.0/\
host/linux-desktop-nomad-x64/ngfx-replay \
    --present-hidden -n 1 --quiet --no-multithreaded-init \
    GameThread_2026_08_23_22_24_36.ngfx-capture

STRIP_ALLOC=3 is mandatory -- without it the replayer SIGSEGVs in
libnvidia-glcore at a fixed-VA dedicated allocation (analysis/HANDOFF.md 8.6).

Usage:  prov_map.py LOG [--module ID] [--image 0x...] [--min-writers N]
"""
import json, sys, glob, os, collections, argparse

VKFMT = {9:'R8_UNORM', 16:'R8G8_UNORM', 37:'R8G8B8A8_UNORM', 43:'R8G8B8A8_SRGB',
         44:'B8G8R8A8_UNORM', 70:'R16_UNORM', 74:'R16_UINT', 76:'R16_SFLOAT',
         82:'R16G16_SINT', 83:'R16G16_SFLOAT', 91:'R16G16B16A16_UNORM',
         97:'R16G16B16A16_SFLOAT', 100:'R32_SFLOAT', 109:'R32G32B32A32_SFLOAT',
         122:'B10G11R11_UFLOAT', 130:'D32_SFLOAT_S8_UINT', 133:'BC1_RGBA_UNORM',
         137:'BC3_UNORM', 138:'BC3_SRGB', 139:'BC4_UNORM'}
TYPE = {1: 'sampler', 2: 'sampled', 3: 'storage'}


def fnv1a64(path):
    h = 0xcbf29ce484222325
    for b in open(path, 'rb').read():
        h ^= b; h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def load(log, dump=os.path.expanduser('~/callisto_dump')):
    fnv2id = {'%016x' % fnv1a64(f): os.path.basename(f).split('.')[0]
              for f in glob.glob(dump + '/*.spv')}
    imgs, views, prov = {}, {}, []
    for line in open(log):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ev = d.get('ev')
        if ev == 'CreateImage':
            imgs[d['img']] = d
        elif ev == 'CreateImageView':
            views[d['view']] = d
        elif ev == 'prov':
            d['id'] = fnv2id.get(d['fnv'], '?' + d['fnv'])
            d['img'] = None
            prov.append(d)
    for p in prov:
        p['img'] = views.get(p['view'], {}).get('img')
    return imgs, views, prov


def desc(imgs, i):
    im = imgs.get(i, {})
    f = im.get('format')
    return (f"{im.get('w')}x{im.get('h')} {VKFMT.get(f, 'fmt' + str(f))} "
            f"usage={im.get('usage')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--module')
    ap.add_argument('--image')
    ap.add_argument('--min-writers', type=int, default=2)
    a = ap.parse_args()
    imgs, views, prov = load(a.log)
    print(f'{len(prov)} prov events, '
          f'{len(set(p["id"] for p in prov))} modules')

    if a.module:
        sel = [p for p in prov if p['id'].startswith(a.module)]
        for p in sorted(sel, key=lambda p: (p['pc'], p['idx'])):
            print(f"  pc[{p['pc']}] idx={p['idx']} {TYPE.get(p['type'],'?'):>7}"
                  f" img={p['img']} {desc(imgs, p['img'])}")
        return

    W, R = collections.defaultdict(set), collections.defaultdict(set)
    for p in prov:
        (W if p['type'] == 3 else R)[p['img']].add(p['id'])

    if a.image:
        print(f"\n{a.image} {desc(imgs, a.image)}")
        print('  writers: ' + ' '.join(sorted(W[a.image])))
        print('  readers: ' + ' '.join(sorted(R[a.image])))
        return

    rows = sorted(((len(w), i, w) for i, w in W.items()
                   if len(w) >= a.min_writers), reverse=True)
    for n, i, w in rows:
        print(f"\n{i} {desc(imgs, i)}  {n} writers, {len(R[i])} readers")
        print('  W ' + ' '.join(sorted(w)))
        if R[i]:
            print('  R ' + ' '.join(sorted(R[i])))


if __name__ == '__main__':
    main()
