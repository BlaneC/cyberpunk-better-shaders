#!/usr/bin/env python3
"""
gfx_map.py -- the RASTER half of the render graph, from a probe log.

prov_map.py answers "which compute dispatch reads/writes which image".  It
cannot answer "which render pass WRITES this image", because prov_scan() only
ever ran from vkCmdDispatch -- the probe layer had no graphics hooks at all.
So every render target that is produced on the raster side and merely consumed
by compute looked, in the log, like a buffer nothing creates.

This tool closes that gap generally, and stays useful for any question of the
form "does this raster pass run in RT Overdrive, and what does it write".
GOTCHAS 5 is why that matters: a bound-but-cleared target looks identical to a
working one from the shader's side, so residency has to be measured, not
assumed.

It was written for one such question -- handoff/29 A4 route 3, the engine's
`CRenderNode_RenderSkinBackDepthForTranslucency` pass, which draws skin BACK
faces to a depth target.  That question is answered and closed: the pass is
found (depth-only, 1280x720, uniquely clear=1.0 for reverse-Z, 25 indexed
draws) and it DOES run in Overdrive, but its bindless heap index is not stable
across captures, so it is not addressable offline.  That is GOTCHAS 13, and
the feature it was for was removed (handoff/39).  The finding stands; so does
the tool.

Generate the log with the graphics-hooked layer, same command as prov_map.py:

  cd GraphicsCaptures
  VK_ADD_LAYER_PATH=$PWD/analysis/probe VK_INSTANCE_LAYERS=VK_LAYER_NGFXPROBE_probe \
  CALLISTO_LAYER_DISABLE=1 NGFXPROBE_STRIP_ALLOC=3 \
  NGFXPROBE_LOG=$PWD/analysis/evidence/meta/capA_gfx.jsonl \
  NGFX_PROV=1 NGFX_PROV_ONLY=1 \
  <ngfx-replay> --present-hidden -n 1 --quiet --no-multithreaded-init CAP

The capture uses dynamic rendering exclusively (194 vkCmdBeginRendering, zero
vkCmdBeginRenderPass / vkCreateFramebuffer), so a "scope" here is always one
BeginRendering..EndRendering pair.

Usage:  gfx_map.py LOG [--depth-only] [--image 0x...]
"""
import argparse
import collections
import json

VKFMT = {9: 'R8_UNORM', 13: 'R8_UINT', 16: 'R8G8_UNORM', 37: 'R8G8B8A8_UNORM',
         43: 'R8G8B8A8_SRGB', 44: 'B8G8R8A8_UNORM', 64: 'A2B10G10R10_UNORM',
         70: 'R16_UNORM', 74: 'R16_UINT', 76: 'R16_SFLOAT', 82: 'R16G16_SINT',
         83: 'R16G16_SFLOAT', 91: 'R16G16B16A16_UNORM',
         97: 'R16G16B16A16_SFLOAT', 98: 'R16G16B16A16_UINT',
         100: 'R32_SFLOAT', 109: 'R32G32B32A32_SFLOAT',
         122: 'B10G11R11_UFLOAT', 124: 'D16_UNORM', 126: 'D32_SFLOAT',
         127: 'S8_UINT', 129: 'D24_UNORM_S8_UINT', 130: 'D32_SFLOAT_S8_UINT',
         133: 'BC1_RGBA_UNORM', 137: 'BC3_UNORM', 138: 'BC3_SRGB',
         139: 'BC4_UNORM'}
# VkAttachmentLoadOp / StoreOp
LOAD = {0: 'LOAD', 1: 'CLEAR', 2: 'DONTCARE', 1000400000: 'NONE'}
STORE = {0: 'STORE', 1: 'DONTCARE', 1000301000: 'NONE'}

DEPTH_FMT = {124, 126, 127, 129, 130}


def fmtname(f):
    return VKFMT.get(f, 'fmt%d' % f)


def load(path):
    imgs, views, scopes = {}, {}, []
    cur = {}          # cb -> open scope
    for line in open(path):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ev = d.get('ev')
        if ev == 'CreateImage':
            imgs[d['img']] = d
        elif ev == 'CreateImageView':
            views[d['view']] = d
        elif ev == 'gfxBegin':
            cur[d['cb']] = dict(begin=d, draws=[], n=0)
        elif ev == 'gfxDraw':
            s = cur.get(d['cb'])
            if s:
                s['draws'].append(d)
        elif ev == 'gfxEnd':
            s = cur.pop(d['cb'], None)
            if s:
                s['n'] = d.get('draws', 0)
                s['end'] = d
                scopes.append(s)
    # any scope still open at end of log (no EndRendering seen) still counts
    scopes.extend(cur.values())
    return imgs, views, scopes


def resolve(views, imgs, vh):
    """view handle -> the CreateImage record, or None."""
    v = views.get(vh)
    if not v:
        return None
    return imgs.get(v.get('img'))


def describe(views, imgs, vh):
    im = resolve(views, imgs, vh)
    if not im:
        return '%s (unresolved)' % vh
    return '%s %dx%d %s usage=%d' % (im['img'], im['w'], im['h'],
                                     fmtname(im['format']), im['usage'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--depth-only', action='store_true',
                    help='only scopes with a depth attachment and no colour '
                         '-- the shape a back-depth prepass has')
    ap.add_argument('--image', help='only scopes touching this image handle')
    a = ap.parse_args()

    imgs, views, scopes = load(a.log)
    print('%d images, %d views, %d rendering scopes, %d draws total\n'
          % (len(imgs), len(views), len(scopes), sum(s['n'] for s in scopes)))

    shown = 0
    for i, s in enumerate(scopes):
        b = s['begin']
        dep = b.get('depth')
        ncol = b.get('nColor', 0)
        if a.depth_only and not (dep and ncol == 0):
            continue
        if a.image:
            touched = [c['view'] for c in b.get('color') or []]
            if dep:
                touched.append(dep['view'])
            hs = {resolve(views, imgs, v)['img']
                  for v in touched if resolve(views, imgs, v)}
            if a.image not in hs:
                continue
        shown += 1
        print('scope %d  %dx%d at (%d,%d)  layers=%d  draws=%d'
              % (i, b['w'], b['h'], b['x'], b['y'], b['layers'], s['n']))
        for c in b.get('color') or []:
            print('    color  %s  load=%s store=%s'
                  % (describe(views, imgs, c['view']),
                     LOAD.get(c['load'], c['load']),
                     STORE.get(c['store'], c['store'])))
        if dep:
            print('    DEPTH  %s  load=%s store=%s clear=%g'
                  % (describe(views, imgs, dep['view']),
                     LOAD.get(dep['load'], dep['load']),
                     STORE.get(dep['store'], dep['store']),
                     dep.get('clear', 0.0)))
        if b.get('stencil'):
            print('    stncl  %s'
                  % describe(views, imgs, b['stencil']['view']))
        for dr in s['draws'][:2]:
            print('    draw   %s pipe=%s n0=%d n1=%d'
                  % (dr['kind'], dr['pipe'], dr['n0'], dr['n1']))
        print()

    if a.depth_only or a.image:
        print('%d scopes matched' % shown)
        return

    # who writes each image, the raster-side answer to prov_map's question
    print('--- images written by a rendering scope ---')
    wr = collections.defaultdict(list)
    for i, s in enumerate(scopes):
        b = s['begin']
        for c in b.get('color') or []:
            im = resolve(views, imgs, c['view'])
            if im:
                wr[im['img']].append((i, 'color', s['n']))
        if b.get('depth'):
            im = resolve(views, imgs, b['depth']['view'])
            if im:
                wr[im['img']].append((i, 'depth', s['n']))
    for h, uses in sorted(wr.items(), key=lambda kv: -len(kv[1])):
        im = imgs[h]
        tag = 'DEPTH-FMT' if im['format'] in DEPTH_FMT else ''
        print('  %s %dx%d %-12s %-9s scopes=%s'
              % (h, im['w'], im['h'], fmtname(im['format']), tag,
                 ','.join('%d(%s,%dd)' % u for u in uses[:6])))


if __name__ == '__main__':
    main()
