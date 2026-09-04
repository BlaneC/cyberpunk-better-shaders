#!/usr/bin/env python3
"""verify_bda -- re-derive the Stage 2b/2c claim from the SHIPPED .spv bytes.

    python3 dev/verify_bda.py <rung-dir> --mode probe|rq [--base DIR]
    python3 dev/verify_bda.py --negative <dir>        # must carry NO marker

Nothing here reads a build report and nothing here trusts dev/patch_bda.py.
Every compute module is read TWICE, on purpose:

  * as a BINARY, word by word, exactly the way swap_layer.c reads it.  This is
    the half that proves hole 1 and hole 2 (`98` sec 10.3): one reserved
    OpString marker, well-formed ids, and those ids resolving to `OpConstant`s
    of a 32-bit unsigned `OpTypeInt` that hold the sentinel halves.  It also
    counts how many constants hold each half, because a module carrying a
    SECOND, unnamed copy is exactly the module on which a value-scanning layer
    would rewrite the wrong word -- so it is rejected here even though the
    layer, which never scans, would survive it.  `spirv-dis` prints that
    constant under a friendly name (`%uint_198836225`), which is why the ids
    cannot be read out of the disassembly at all.

  * as a DISASSEMBLY, for the structural claim: that the two named constants
    really are the two halves of a PhysicalStorageBuffer pointer, that the
    struct behind that pointer is the layer's own 8 x uint layout to the
    Offset, that word 0 is compared against the magic, and -- in --mode rq --
    that the acceleration structure is built from words 2 and 3 of the SAME
    pointer and that the ray origin is CAMERA-RELATIVE (`99` sec 10.6).  The
    origin test is verify_wpos's own `_check_position_triple`, imported rather
    than re-implemented, so "the origin is P - C over the module's own matrix
    row Fma chain" is asserted by code written for a different feature.

The link between the two halves is the sentinel VALUE, and it is unambiguous
only because the binary pass has already proved each half occurs exactly once.

WHAT A PASS DOES NOT MEAN: nothing here can prove the layer's fixup runs, that
the device address is valid, or that the query hits anything.  Those are
dev/selftest_bda.sh (driver) and the screen (game).
"""
import argparse, glob, os, re, struct, subprocess, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_chs_brdf import load_lenient
import wpos_core as W
from verify_wpos import _check_position_triple, consts
from patch_bda import (MARKER, SENT_LO, SENT_HI, MAGIC, SLOT_MEMBERS, ID_W,
                       DECLINE_ALL, DECLINE_RQ, COL, DEFAULTS,
                       W_MAGIC, W_GEN, W_LO, W_HI, W_FRAME,
                       SLOT_MEMBERS_V2, W_SCR_LO, W_SCR_HI, W_SCR_WORDS,
                       SCRATCH_HDR, SCRATCH_SIG, PIX_PITCH, PIX_HASH,
                       PARK_WORD, WORDS_PER_PIXEL, XPROBE_REG, XPROBE_OFFS)

CENSUS = {'probe': dict(modules=77, painted=76, writes=151,
                        declined=DECLINE_ALL),
          'rq': dict(modules=77, painted=75, writes=150,
                     declined=DECLINE_ALL | DECLINE_RQ),
          'wprobe': dict(modules=77, painted=76, writes=151,
                         declined=DECLINE_ALL),
          'wprobe2': dict(modules=77, painted=76, writes=151,
                          declined=DECLINE_ALL),
          # xprobe is the only mode with a raygen half. `writes` counts the
          # compute WRITER's store sites; `rg_modules`/`rg_writes` the raygen
          # READER's painted sites (handoff/116 sec 11).
          'xprobe': dict(modules=77, painted=76, writes=151,
                         declined=DECLINE_ALL, rg_modules=16, rg_writes=53)}
N_SLOT = {'probe': SLOT_MEMBERS, 'rq': SLOT_MEMBERS,
          'wprobe': SLOT_MEMBERS_V2, 'wprobe2': SLOT_MEMBERS_V2,
          'xprobe': SLOT_MEMBERS_V2}
WMODES = tuple(WORDS_PER_PIXEL)
DIR_XYZ = (0.0, 0.0, 1.0)


class Fail(Exception):
    pass


# ------------------------------------------------------ half one: the binary
def binary_marker(path):
    """Read the marker and the sentinel constants the way the LAYER does."""
    b = open(path, 'rb').read()
    n = len(b) // 4
    w = struct.unpack('<%dI' % n, b[:n * 4])
    if w[0] != 0x07230203:
        raise Fail('%s: not SPIR-V' % path)
    out = dict(markers=[], n_lo=0, n_hi=0, lo_id=None, hi_id=None,
               lo_ids=[], hi_ids=[], addressing=None)
    uint_ty = set()
    i = 5
    while i < n:
        ln, op = w[i] >> 16, w[i] & 0xffff
        if ln == 0 or i + ln > n:
            raise Fail('%s: truncated instruction stream' % path)
        if op == 54:                                       # OpFunction
            break
        if op == 14 and ln == 3:                           # OpMemoryModel
            out['addressing'] = w[i + 1]
        elif op == 21 and ln == 4 and w[i + 2] == 32 and w[i + 3] == 0:
            uint_ty.add(w[i + 1])                          # OpTypeInt 32 0
        elif op == 43 and ln == 4 and w[i + 1] in uint_ty:  # OpConstant
            if w[i + 3] == SENT_LO:
                out['n_lo'] += 1
                out['lo_ids'].append(w[i + 2])
            elif w[i + 3] == SENT_HI:
                out['n_hi'] += 1
                out['hi_ids'].append(w[i + 2])
        elif op == 7 and ln >= 3:                          # OpString
            s = bytes(b[(i + 2) * 4:(i + ln) * 4]).split(b'\0')[0]
            s = s.decode('utf-8', 'replace')
            if MARKER in s:
                out['markers'].append(s)
        i += ln
    return out


def check_marker(path, name, expect_marker=True):
    m = binary_marker(path)
    if not expect_marker:
        if m['markers'] or m['n_lo'] or m['n_hi']:
            raise Fail('%s: an UNPAINTED module carries the marker or a '
                       'sentinel constant' % name)
        return m
    if len(m['markers']) != 1:
        raise Fail('%s: %d markers, want exactly 1' % (name, len(m['markers'])))
    if m['addressing'] != 5348:      # PhysicalStorageBuffer64
        raise Fail('%s: addressing model %s, want PhysicalStorageBuffer64'
                   % (name, m['addressing']))
    w = r'(\d{' + str(ID_W) + r'})'
    pat = (re.escape(MARKER) + r' lo=%' + w + r' hi=%' + w
           + r' sent=([0-9a-f]{16}) magic=([0-9a-f]{8})$')
    g = re.match(pat, m['markers'][0])
    if not g:
        raise Fail('%s: malformed marker %r' % (name, m['markers'][0]))
    if int(g.group(3), 16) != ((SENT_HI << 32) | SENT_LO):
        raise Fail('%s: marker sentinel %s is not this build' % (name, g.group(3)))
    if int(g.group(4), 16) != MAGIC:
        raise Fail('%s: marker magic %s is not this build' % (name, g.group(4)))
    if (m['n_lo'], m['n_hi']) != (1, 1):
        raise Fail('%s: %d/%d sentinel constants, want 1/1 -- a second, '
                   'unnamed copy makes a value scan ambiguous'
                   % (name, m['n_lo'], m['n_hi']))
    lo, hi = int(g.group(1)), int(g.group(2))
    if lo != m['lo_ids'][0] or hi != m['hi_ids'][0]:
        raise Fail('%s: marker names ids %d/%d, the sentinel constants are '
                   '%d/%d' % (name, lo, hi, m['lo_ids'][0], m['hi_ids'][0]))
    if lo == hi:
        raise Fail('%s: the marker names one id twice' % name)
    m['lo_id'], m['hi_id'] = lo, hi
    return m


# ------------------------------------------------- half two: the structure
def only(D, pat, name, what):
    hits = [(i, re.match(pat, t).groups()) for i, (_, t) in D.items()
            if re.match(pat, t)]
    if len(hits) != 1:
        raise Fail('%s: %d x %s, want exactly 1' % (name, len(hits), what))
    return hits[0]


def slot_pointer(mod, D, name, n_slot=SLOT_MEMBERS):
    """From the two sentinel constants to the loaded magic word."""
    lo = only(D, r'OpConstant %uint ' + str(SENT_LO) + r'\s*$', name,
              'sentinel-lo constant')[0]
    hi = only(D, r'OpConstant %uint ' + str(SENT_HI) + r'\s*$', name,
              'sentinel-hi constant')[0]
    v2 = only(D, r'OpCompositeConstruct %v2uint ' + re.escape(lo) + ' '
              + re.escape(hi) + r'\s*$', name, 'address vector')[0]
    bc = [(i, re.match(r'OpBitcast (%\w+) ' + re.escape(v2) + r'\s*$', t))
          for i, (_, t) in D.items()]
    bc = [(i, m.group(1)) for i, m in bc if m]
    if len(bc) != 1:
        raise Fail('%s: %d bitcasts of the address vector, want 1' % (name, len(bc)))
    ptr, pty = bc[0]
    m = re.match(r'OpTypePointer PhysicalStorageBuffer (%\w+)\s*$',
                 D.get(pty, (0, ''))[1])
    if not m:
        raise Fail('%s: the address is not bitcast to a PhysicalStorageBuffer '
                   'pointer' % name)
    st = m.group(1)
    sm = re.match(r'OpTypeStruct((?: %\w+){' + str(n_slot) + r'})\s*$',
                  D.get(st, (0, ''))[1])
    if not sm or set(sm.group(1).split()) != {'%uint'}:
        raise Fail('%s: the slot struct is not %d x uint (%r)'
                   % (name, n_slot, D.get(st, (0, ''))[1]))
    src = '\n'.join(mod.lines)
    if not re.search(r'OpDecorate ' + re.escape(st) + r' Block\b', src):
        raise Fail('%s: the slot struct is not a Block' % name)
    for k in range(n_slot):
        for d in ('Offset %d' % (4 * k), 'NonWritable'):
            if not re.search(r'OpMemberDecorate ' + re.escape(st) + ' %d %s'
                             % (k, d), src):
                raise Fail('%s: slot member %d lacks `%s`' % (name, k, d))
    return ptr


def slot_word(D, ptr, k, name):
    ac = [i for i, (_, t) in D.items()
          if re.match(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                      + re.escape(ptr) + r' %uint_' + str(k) + r'\s*$', t)]
    if len(ac) != 1:
        raise Fail('%s: %d access chains to slot word %d, want 1'
                   % (name, len(ac), k))
    ld = [i for i, (_, t) in D.items()
          if re.match(r'OpLoad %uint ' + re.escape(ac[0]) + r' Aligned 4\s*$', t)]
    if len(ld) != 1:
        raise Fail('%s: slot word %d is not loaded exactly once (Aligned 4)'
                   % (name, k))
    return ld[0]


def fconst(K, i):
    v = K.get(i)
    return None if v is None else float(np.float32(v))


def want_f(K, i, v, name, what):
    got = fconst(K, i)
    if got is None or np.float32(got) != np.float32(v):
        raise Fail('%s: %s is %s, want %g' % (name, what, got, v))


# --------------------------------------------------- half two-b: the scratch
def scratch_pointer(mod, D, name, ptr, src, mode):
    """From slot words 8/9/10 to the WRITABLE runtime-array pointer.

    Everything here is re-derived from the disassembly. The claim it exists to
    refuse is the dangerous one: a module that dereferences the scratch
    address WITHOUT having selected the parked slot address for the case where
    the layer allocated none. That is a null dereference on every pixel, and
    it is invisible in a report."""
    wW = slot_word(D, ptr, W_SCR_WORDS, name)
    sl = slot_word(D, ptr, W_SCR_LO, name)
    sh = slot_word(D, ptr, W_SCR_HI, name)
    fr = slot_word(D, ptr, W_FRAME, name)
    armed = only(D, r'OpINotEqual %bool ' + re.escape(wW) + r' (%\w+)\s*$',
                 name, 'the armed test')
    if consts(mod).get(armed[1][0]) != 0:
        raise Fail('%s: the armed test is not `words != 0`' % name)
    armed = armed[0]
    half = only(D, r'OpShiftRightLogical %uint ' + re.escape(wW) + r' (%\w+)\s*$',
                name, 'the half-size shift')
    wpp = WORDS_PER_PIXEL[mode]
    # words >> 1 for one word per pixel, words >> 2 for two: the shift is the
    # words-per-pixel only because those two numbers happen to coincide at
    # 1 and 2 -- what it has to be is log2(2 * wpp) - log2(2), i.e. log2(wpp)
    # plus the one bit the mask itself costs.
    if consts(mod).get(half[1][0]) != wpp:
        raise Fail('%s: the payload window is not words >> %d' % (name, wpp))
    mask = only(D, r'OpISub %uint ' + re.escape(half[0]) + r' (%\w+)\s*$',
                name, 'the index mask')
    if consts(mod).get(mask[1][0]) != 1:
        raise Fail('%s: the index mask is not (words >> %d) - 1' % (name, wpp))
    mask = mask[0]
    # the two selects, and that they fall back to the SENTINEL pair
    lo = only(D, r'OpConstant %uint ' + str(SENT_LO) + r'\s*$', name, 'sent-lo')[0]
    hi = only(D, r'OpConstant %uint ' + str(SENT_HI) + r'\s*$', name, 'sent-hi')[0]
    bl = only(D, r'OpSelect %uint ' + re.escape(armed) + ' ' + re.escape(sl)
              + ' ' + re.escape(lo) + r'\s*$', name,
              'the armed/parked select on the low half')[0]
    bh = only(D, r'OpSelect %uint ' + re.escape(armed) + ' ' + re.escape(sh)
              + ' ' + re.escape(hi) + r'\s*$', name,
              'the armed/parked select on the high half')[0]
    bv = only(D, r'OpCompositeConstruct %v2uint ' + re.escape(bl) + ' '
              + re.escape(bh) + r'\s*$', name, 'the scratch address vector')[0]
    bc = [(i, re.match(r'OpBitcast (%\w+) ' + re.escape(bv) + r'\s*$', t))
          for i, (_, t) in D.items()]
    bc = [(i, m.group(1)) for i, m in bc if m]
    if len(bc) != 1:
        raise Fail('%s: %d bitcasts of the scratch address, want 1'
                   % (name, len(bc)))
    sp, pty = bc[0]
    m = re.match(r'OpTypePointer PhysicalStorageBuffer (%\w+)\s*$',
                 D.get(pty, (0, ''))[1])
    if not m:
        raise Fail('%s: the scratch address is not a PhysicalStorageBuffer '
                   'pointer' % name)
    blk = m.group(1)
    bm = re.match(r'OpTypeStruct (%\w+)\s*$', D.get(blk, (0, ''))[1])
    if not bm:
        raise Fail('%s: the scratch block is not a one-member struct' % name)
    arr = bm.group(1)
    if not re.match(r'OpTypeRuntimeArray %uint\s*$', D.get(arr, (0, ''))[1]):
        raise Fail('%s: the scratch member is not a runtime array of uint' % name)
    for d, what in ((r'OpDecorate ' + re.escape(arr) + r' ArrayStride 4',
                     'ArrayStride 4'),
                    (r'OpDecorate ' + re.escape(blk) + r' Block', 'Block'),
                    (r'OpMemberDecorate ' + re.escape(blk) + r' 0 Offset 0',
                     'Offset 0')):
        if not re.search(d, src):
            raise Fail('%s: the scratch block lacks `%s`' % (name, what))
    if re.search(r'OpMemberDecorate ' + re.escape(blk) + r' 0 NonWritable', src):
        raise Fail('%s: the scratch block is NonWritable -- then nothing in '
                   'this rung can write' % name)
    prev = None
    if mode == 'wprobe':
        prevf = only(D, r'OpISub %uint ' + re.escape(fr) + r' (%\w+)\s*$', name,
                     'the previous-frame word')
        if consts(mod).get(prevf[1][0]) != 1:
            raise Fail('%s: the previous frame is not `frame - 1`' % name)
        prev = prevf[0]
    return dict(sp=sp, armed=armed, mask=mask, fr=fr, prevf=prev, wpp=wpp)


def raygen_img_off(mod, D, line):
    """registers[XPROBE_REG] + N for a raygen's image write, or None."""
    m = re.match(r'\s*OpImageWrite (%\w+) %\w+ %\w+\s*$', mod.lines[line])
    if not m:
        return None
    ld = re.match(r'OpLoad %\w+ (%\w+)\s*$', D.get(m.group(1), (0, ''))[1])
    if not ld:
        return None
    ac = re.match(r'OpAccessChain %\w+ %\w+ (%\w+)\s*$',
                  D.get(ld.group(1), (0, ''))[1])
    if not ac:
        return None
    v, off = D.get(ac.group(1), (0, ''))[1], 0
    m2 = re.match(r'OpIAdd %uint (%\w+) %uint_(\d+)\s*$', v)
    if m2:
        off = int(m2.group(2))
        v = D.get(m2.group(1), (0, ''))[1]
    m3 = re.match(r'OpLoad %uint (%\w+)\s*$', v)
    if not m3:
        return None
    pc = re.match(r'OpAccessChain %_ptr_PushConstant_uint %registers '
                  r'%uint_(\d+)\s*$', D.get(m3.group(1), (0, ''))[1])
    if not pc or int(pc.group(1)) != XPROBE_REG:
        return None
    return off


def one(D, K, name, line, ids, what):
    if len(ids) != 1:
        raise Fail('%s@%d: the channels disagree on %s' % (name, line + 1, what))
    return ids.pop()


def site_index(mod, D, K, name, line, coord, chain, S, gated):
    """From an access chain back to THIS write's own pixel. Shared by both
    halves of xprobe, which is the point: the writer and the reader must be
    shown to compute the same index from the same kind of coordinate, or the
    rung measures nothing."""
    ac = re.match(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                  + re.escape(S['sp']) + r' (%\w+) (%\w+)\s*$',
                  D.get(chain, (0, ''))[1])
    if not ac or K.get(ac.group(1)) != 0:
        raise Fail('%s@%d: not scratch[0][idx]' % (name, line + 1))
    idx = ac.group(2)
    sel = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)\s*$',
                   D.get(idx, (0, ''))[1])
    if not sel:
        raise Fail('%s@%d: the index is not guarded -- an unarmed pixel would '
                   'dereference a null address' % (name, line + 1))
    if K.get(sel.group(3)) != PARK_WORD:
        raise Fail('%s@%d: the parked index is %s, want %d'
                   % (name, line + 1, K.get(sel.group(3)), PARK_WORD))
    if gated:
        # the WRITER's guard is `armed AND class == 1`: a store cannot sit
        # under a select, so its ADDRESS carries the skin gate instead.
        la = re.match(r'OpLogicalAnd %bool ' + re.escape(S['armed'])
                      + r' (%\w+)\s*$', D.get(sel.group(1), (0, ''))[1])
        if not la:
            raise Fail('%s@%d: the writer index is not gated on `armed AND '
                       'class` -- it would write outside skin' % (name, line + 1))
        ge = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$',
                      D.get(la.group(1), (0, ''))[1])
        if not ge or K.get(ge.group(2)) != 1:
            raise Fail('%s@%d: the writer gate is not `class == 1`'
                       % (name, line + 1))
        cl = D.get(ge.group(1), (0, ''))[1]
        if not re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$', cl):
            ph = re.match(r'OpPhi %uint (.*)$', cl)
            srcs = re.findall(r'%\w+', ph.group(1)) if ph else []
            if not any(re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$',
                                D.get(x, (0, ''))[1]) for x in srcs):
                raise Fail('%s@%d: the class is not a `word >> 5`'
                           % (name, line + 1))
    elif sel.group(1) != S['armed']:
        raise Fail('%s@%d: the reader index is not guarded on `armed` alone'
                   % (name, line + 1))
    add = re.match(r'OpIAdd %uint (%\w+) (%\w+)\s*$',
                   D.get(sel.group(2), (0, ''))[1])
    if not add or K.get(add.group(2)) != SCRATCH_HDR:
        raise Fail('%s@%d: the payload index does not clear the %d reserved '
                   'header words' % (name, line + 1, SCRATCH_HDR))
    sub = add.group(1)
    if S['wpp'] != 1:
        mul = re.match(r'OpIMul %uint (%\w+) (%\w+)\s*$', D.get(sub, (0, ''))[1])
        if not mul or K.get(mul.group(2)) != S['wpp']:
            raise Fail('%s@%d: the index does not stride by %d words per pixel'
                       % (name, line + 1, S['wpp']))
        sub = mul.group(1)
    band = re.match(r'OpBitwiseAnd %uint (%\w+) ' + re.escape(S['mask'])
                    + r'\s*$', D.get(sub, (0, ''))[1])
    if not band:
        raise Fail('%s@%d: the index is not masked by the layer\'s own size'
                   % (name, line + 1))
    pix = band.group(1)
    pa = re.match(r'OpIAdd %uint (%\w+) (%\w+)\s*$', D.get(pix, (0, ''))[1])
    if not pa:
        raise Fail('%s@%d: the pixel index is not y*pitch + x' % (name, line + 1))
    pm = re.match(r'OpIMul %uint (%\w+) (%\w+)\s*$',
                  D.get(pa.group(1), (0, ''))[1])
    if not pm or K.get(pm.group(2)) != PIX_PITCH:
        raise Fail('%s@%d: the row stride is not %d' % (name, line + 1, PIX_PITCH))
    cc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$',
                  D.get(coord, (0, ''))[1])
    if not cc:
        raise Fail('%s@%d: the write coordinate is not a v2uint construct'
                   % (name, line + 1))
    if (pa.group(2), pm.group(1)) != (cc.group(1), cc.group(2)):
        raise Fail('%s@%d: the index is built from (%s,%s) but the texel is '
                   'written at (%s,%s) -- the two must be the SAME pixel'
                   % (name, line + 1, pa.group(2), pm.group(1),
                      cc.group(1), cc.group(2)))
    return idx, pix


def identity_word(D, K, name, line, sx, pix):
    xs = re.match(r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$', D.get(sx, (0, ''))[1])
    if not xs or K.get(xs.group(2)) != SCRATCH_SIG:
        raise Fail('%s@%d: the word is not signed with %08x'
                   % (name, line + 1, SCRATCH_SIG))
    hm = re.match(r'OpIMul %uint ' + re.escape(pix) + r' (%\w+)\s*$',
                  D.get(xs.group(1), (0, ''))[1])
    if not hm or K.get(hm.group(1)) != PIX_HASH:
        raise Fail('%s@%d: the word does not hash THIS pixel with %d'
                   % (name, line + 1, PIX_HASH))


def check_xprobe_writer(mod, D, K, name, v4writes, coords, S):
    """The compute half: two stores per site, no load, and NO PAINT."""
    # This half must change NO pixel: everything visible in the rung has to be
    # the raygen's doing, or a green frame proves nothing about the raygen. The
    # exact form of the claim is build_bda.sh gate 4, which diffs the shipped
    # OpImageWrite lines against the base; what is checkable from this module
    # alone is that no radiance texel is a channel-wise multiply by one of the
    # paint TRIPLES. (A single magnitude means nothing -- the game's own code
    # multiplies by 3.0 -- but all three channels carrying one COL triple in
    # order is the paint and nothing else.)
    triples = {tuple(np.float32(c) for c in v) for v in COL.values()}
    for line, texel in v4writes:
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) '
                      r'(%\w+)\s*$', D[texel][1])
        if not mc:
            continue
        got = []
        for c in mc.groups()[:3]:
            m = re.match(r'OpFMul %float %\w+ (%\w+)\s*$', D.get(c, (0, ''))[1])
            v = fconst(K, m.group(1)) if m else None
            got.append(None if v is None else np.float32(v))
        if tuple(got) in triples:
            raise Fail('%s@%d: the WRITER tints this texel by a paint triple '
                       '-- this half of xprobe must change no pixel, or the '
                       'raygen\'s verdict cannot be read off the screen'
                       % (name, line + 1))
    stores = [(i, re.match(r'\s*OpStore (%\w+) (%\w+) Aligned 4\s*$', ln))
              for i, ln in enumerate(mod.lines)]
    ours = [(i, m.group(1), m.group(2)) for i, m in stores if m
            and re.match(r'OpInBoundsAccessChain '
                         r'%_ptr_PhysicalStorageBuffer_uint '
                         + re.escape(S['sp']) + r' ',
                         D.get(m.group(1), (0, ''))[1])]
    if len(ours) != len(v4writes) * S['wpp']:
        raise Fail('%s: %d stores through the scratch pointer over %d writes '
                   'at %d words per pixel'
                   % (name, len(ours), len(v4writes), S['wpp']))
    for line, _ in v4writes:
        here = [(i, c, v) for i, c, v in ours if i < line]
        here = here[-2:]
        if len(here) != 2:
            raise Fail('%s@%d: fewer than two stores before this write'
                       % (name, line + 1))
        (l0, c0, v0), (l1, c1, v1) = here
        idx, pix = site_index(mod, D, K, name, line, coords[line], c0, S, True)
        identity_word(D, K, name, line, v0, pix)
        nx = re.match(r'OpIAdd %uint ' + re.escape(idx) + r' (%\w+)\s*$',
                      D.get(re.match(r'OpInBoundsAccessChain %\w+ %\w+ %\w+ '
                                     r'(%\w+)\s*$',
                                     D[c1][1]).group(1), (0, ''))[1])
        if not nx or K.get(nx.group(1)) != 1:
            raise Fail('%s@%d: the second store is not the word NEXT to the '
                       'identity' % (name, line + 1))
        if v1 != S['fr']:
            raise Fail('%s@%d: the second word stored is not the frame'
                       % (name, line + 1))
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpLoad %uint (%\w+) Aligned 4\s*$', ln)
        if m and re.match(r'OpInBoundsAccessChain '
                          r'%_ptr_PhysicalStorageBuffer_uint '
                          + re.escape(S['sp']) + r' ',
                          D.get(m.group(2), (0, ''))[1]):
            raise Fail('%s: the WRITER reads the scratch back; it must only '
                       'write' % name)


def check_xprobe_reader(mod, D, K, name, line, coord, chans, S, ok):
    """The raygen half: the six-way ladder, and NOT ONE STORE."""
    seen, is0, is1, pres = set(), set(), set(), set()
    for ch, c in enumerate(chans):
        h5 = re.match(r'OpSelect %float ' + re.escape(ok)
                      + r' (%\w+) (%\w+)\s*$', D.get(c, (0, ''))[1])
        if not h5:
            raise Fail('%s@%d: channel %d is not selected on the magic'
                       % (name, line + 1, ch))
        want_f(K, h5.group(2), COL['blue'][ch], name, 'the no-fixup colour')
        h4 = re.match(r'OpSelect %float ' + re.escape(S['armed'])
                      + r' (%\w+) (%\w+)\s*$', D.get(h5.group(1), (0, ''))[1])
        if not h4:
            raise Fail('%s@%d: channel %d is not selected on `armed`'
                       % (name, line + 1, ch))
        want_f(K, h4.group(2), COL['amber'][ch], name, 'the no-scratch colour')
        h3 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                      D.get(h4.group(1), (0, ''))[1])
        if not h3:
            raise Fail('%s@%d: channel %d has no found/not-found split'
                       % (name, line + 1, ch))
        seen.add(h3.group(1))
        h2 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                      D.get(h3.group(3), (0, ''))[1])
        if not h2:
            raise Fail('%s@%d: channel %d does not separate "a stranger\'s '
                       'word" from "no word at all"' % (name, line + 1, ch))
        pres.add(h2.group(1))
        want_f(K, h2.group(2), COL['red'][ch], name, 'the wrong-pixel colour')
        want_f(K, h2.group(3), 1.0, name, 'the untouched multiplier')
        h1 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                      D.get(h3.group(2), (0, ''))[1])
        if not h1:
            raise Fail('%s@%d: channel %d does not split the found case on age'
                       % (name, line + 1, ch))
        is0.add(h1.group(1))
        want_f(K, h1.group(2), COL['cyan'][ch], name, 'the same-frame colour')
        h0 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                      D.get(h1.group(3), (0, ''))[1])
        if not h0:
            raise Fail('%s@%d: channel %d has no one-frame arm'
                       % (name, line + 1, ch))
        is1.add(h0.group(1))
        want_f(K, h0.group(2), COL['green'][ch], name, 'the one-frame colour')
        want_f(K, h0.group(3), COL['magenta'][ch], name, 'the stale colour')
    b_seen = one(D, K, name, line, seen, 'the found test')
    b_pres = one(D, K, name, line, pres, 'the present test')
    eq = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$', D.get(b_seen, (0, ''))[1])
    if not eq:
        raise Fail('%s@%d: the found test is not an integer compare'
                   % (name, line + 1))
    got, sx = eq.groups()
    ne = re.match(r'OpINotEqual %bool ' + re.escape(got) + r' (%\w+)\s*$',
                  D.get(b_pres, (0, ''))[1])
    if not ne or K.get(ne.group(1)) != 0:
        raise Fail('%s@%d: the present test is not `the same loaded word != 0`'
                   % (name, line + 1))
    ld = re.match(r'OpLoad %uint (%\w+) Aligned 4\s*$', D.get(got, (0, ''))[1])
    if not ld:
        raise Fail('%s@%d: the compared word is not a 4-aligned load'
                   % (name, line + 1))
    idx, pix = site_index(mod, D, K, name, line, coord, ld.group(1), S, False)
    identity_word(D, K, name, line, sx, pix)
    if re.search(re.escape(S['fr']), D.get(sx, (0, ''))[1]):
        raise Fail('%s@%d: the expected identity is stamped with the frame'
                   % (name, line + 1))
    check_age_word(mod, D, K, name, line, S, idx, is0, is1, store=False)


def check_wprobe_site(mod, D, K, name, line, coord, inner, S, ok, mode):
    """One painted write: its colour ladder, its index, and its words."""
    seen, is0, is1 = set(), set(), set()
    for ch, c in enumerate(inner):
        a2 = re.match(r'OpSelect %float ' + re.escape(ok) + r' (%\w+) (%\w+)\s*$',
                      D.get(c, (0, ''))[1])
        if not a2:
            raise Fail('%s@%d: channel %d is not selected on the magic'
                       % (name, line + 1, ch))
        want_f(K, a2.group(2), COL['red'][ch], name, 'the no-magic colour')
        a1 = re.match(r'OpSelect %float ' + re.escape(S['armed'])
                      + r' (%\w+) (%\w+)\s*$', D.get(a2.group(1), (0, ''))[1])
        if not a1:
            raise Fail('%s@%d: channel %d is not selected on `armed`'
                       % (name, line + 1, ch))
        want_f(K, a1.group(2), COL['amber'][ch], name, 'the no-scratch colour')
        a0 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                      D.get(a1.group(1), (0, ''))[1])
        if not a0:
            raise Fail('%s@%d: channel %d is not selected on the read-back'
                       % (name, line + 1, ch))
        seen.add(a0.group(1))
        if mode == 'wprobe':
            want_f(K, a0.group(2), COL['green'][ch], name, 'the survived colour')
            want_f(K, a0.group(3), COL['blue'][ch], name,
                   'the did-not-survive colour')
        else:
            # wprobe2 splits the survivors by AGE: the false arm is still the
            # one that says the word is not this pixel's.
            want_f(K, a0.group(3), COL['blue'][ch], name,
                   'the did-not-survive colour')
            h1 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                          D.get(a0.group(2), (0, ''))[1])
            if not h1:
                raise Fail('%s@%d: channel %d does not split the survivors on '
                           'age' % (name, line + 1, ch))
            is0.add(h1.group(1))
            want_f(K, h1.group(2), COL['cyan'][ch], name, 'the zero-age colour')
            h0 = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                          D.get(h1.group(3), (0, ''))[1])
            if not h0:
                raise Fail('%s@%d: channel %d has no one-frame-old arm'
                           % (name, line + 1, ch))
            is1.add(h0.group(1))
            want_f(K, h0.group(2), COL['green'][ch], name, 'the one-frame colour')
            want_f(K, h0.group(3), COL['magenta'][ch], name, 'the stale colour')
    eq = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$',
                  D.get(one(D, K, name, line, seen, 'the read-back test'),
                        (0, ''))[1])
    if not eq:
        raise Fail('%s@%d: the read-back test is not an integer compare'
                   % (name, line + 1))
    got, wold = eq.groups()
    ld = re.match(r'OpLoad %uint (%\w+) Aligned 4\s*$', D.get(got, (0, ''))[1])
    if not ld:
        raise Fail('%s@%d: the compared word is not a 4-aligned load'
                   % (name, line + 1))
    chain = ld.group(1)
    ac = re.match(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                  + re.escape(S['sp']) + r' (%\w+) (%\w+)\s*$',
                  D.get(chain, (0, ''))[1])
    if not ac or K.get(ac.group(1)) != 0:
        raise Fail('%s@%d: the load is not scratch[0][idx]' % (name, line + 1))
    idx = ac.group(2)
    # the index: armed ? SCRATCH_HDR + (pix & mask) : PARK_WORD
    sel = re.match(r'OpSelect %uint ' + re.escape(S['armed'])
                   + r' (%\w+) (%\w+)\s*$', D.get(idx, (0, ''))[1])
    if not sel:
        raise Fail('%s@%d: the index is not selected on `armed` -- an '
                   'unarmed pixel would dereference a null address'
                   % (name, line + 1))
    if K.get(sel.group(2)) != PARK_WORD:
        raise Fail('%s@%d: the parked index is %s, want %d'
                   % (name, line + 1, K.get(sel.group(2)), PARK_WORD))
    add = re.match(r'OpIAdd %uint (%\w+) (%\w+)\s*$',
                   D.get(sel.group(1), (0, ''))[1])
    if not add or K.get(add.group(2)) != SCRATCH_HDR:
        raise Fail('%s@%d: the payload index does not clear the %d reserved '
                   'header words' % (name, line + 1, SCRATCH_HDR))
    sub = add.group(1)
    if S['wpp'] != 1:
        mul = re.match(r'OpIMul %uint (%\w+) (%\w+)\s*$', D.get(sub, (0, ''))[1])
        if not mul or K.get(mul.group(2)) != S['wpp']:
            raise Fail('%s@%d: the index does not stride by %d words per pixel '
                       '-- one pixel\'s second word would be the next pixel\'s '
                       'first' % (name, line + 1, S['wpp']))
        sub = mul.group(1)
    band = re.match(r'OpBitwiseAnd %uint (%\w+) ' + re.escape(S['mask'])
                    + r'\s*$', D.get(sub, (0, ''))[1])
    if not band:
        raise Fail('%s@%d: the index is not masked by the layer\'s own size'
                   % (name, line + 1))
    pix = band.group(1)
    # the pixel is THIS write's coordinate, not some other pixel's
    pa = re.match(r'OpIAdd %uint (%\w+) (%\w+)\s*$', D.get(pix, (0, ''))[1])
    if not pa:
        raise Fail('%s@%d: the pixel index is not y*pitch + x' % (name, line + 1))
    pm = re.match(r'OpIMul %uint (%\w+) (%\w+)\s*$',
                  D.get(pa.group(1), (0, ''))[1])
    if not pm or K.get(pm.group(2)) != PIX_PITCH:
        raise Fail('%s@%d: the row stride is not %d' % (name, line + 1, PIX_PITCH))
    cc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$',
                  D.get(coord, (0, ''))[1])
    if not cc:
        raise Fail('%s@%d: the write coordinate is not a v2uint construct'
                   % (name, line + 1))
    if (pa.group(2), pm.group(1)) != (cc.group(1), cc.group(2)):
        raise Fail('%s@%d: the index is built from (%s,%s) but the texel is '
                   'written at (%s,%s)' % (name, line + 1, pa.group(2),
                                           pm.group(1), cc.group(1), cc.group(2)))
    if mode == 'wprobe':
        # the two words: SIG ^ hash(pix) ^ frame, and the same with frame - 1
        xw = re.match(r'OpBitwiseXor %uint (%\w+) ' + re.escape(S['prevf'])
                      + r'\s*$', D.get(wold, (0, ''))[1])
        if not xw:
            raise Fail('%s@%d: the expected word is not stamped with frame - 1 '
                       '-- without that, a store this frame would read back as '
                       'a survival' % (name, line + 1))
        sx = xw.group(1)
    else:
        # wprobe2's identity word carries NO frame: that is the whole point of
        # the rung, so refuse one that smuggles a counter back in.
        sx = wold
        if re.search(re.escape(S['fr']), D.get(sx, (0, ''))[1]):
            raise Fail('%s@%d: the identity word is stamped with the frame -- '
                       'then it cannot separate persistence from the counter'
                       % (name, line + 1))
    xs = re.match(r'OpBitwiseXor %uint (%\w+) (%\w+)\s*$', D.get(sx, (0, ''))[1])
    if not xs or K.get(xs.group(2)) != SCRATCH_SIG:
        raise Fail('%s@%d: the word is not signed with %08x'
                   % (name, line + 1, SCRATCH_SIG))
    hm = re.match(r'OpIMul %uint ' + re.escape(pix) + r' (%\w+)\s*$',
                  D.get(xs.group(1), (0, ''))[1])
    if not hm or K.get(hm.group(1)) != PIX_HASH:
        raise Fail('%s@%d: the word does not hash THIS pixel with %d'
                   % (name, line + 1, PIX_HASH))
    # the store: same chain, AFTER the load
    st = [i for i, ln in enumerate(mod.lines)
          if re.match(r'\s*OpStore ' + re.escape(chain) + r' (%\w+) Aligned 4\s*$',
                      ln)]
    if len(st) != 1:
        raise Fail('%s@%d: %d stores to this pixel\'s word, want 1'
                   % (name, line + 1, len(st)))
    sv = re.match(r'\s*OpStore %\w+ (%\w+) Aligned 4\s*$', mod.lines[st[0]])
    if mode == 'wprobe':
        if not re.match(r'OpBitwiseXor %uint ' + re.escape(sx) + ' '
                        + re.escape(S['fr']) + r'\s*$',
                        D.get(sv.group(1), (0, ''))[1]):
            raise Fail('%s@%d: the stored word is not this frame\'s stamp'
                       % (name, line + 1))
    elif sv.group(1) != sx:
        raise Fail('%s@%d: the stored identity is not the one compared'
                   % (name, line + 1))
    if not (D[got][0] < st[0] < line):
        raise Fail('%s@%d: the store does not sit between the load and the '
                   'image write' % (name, line + 1))
    if mode == 'wprobe2':
        check_age_word(mod, D, K, name, line, S, idx, is0, is1)
    return chain


def check_age_word(mod, D, K, name, line, S, idx, is0, is1, store=True):
    """The SECOND word: the frame the identity was last written, and the two
    age tests the hue is chosen by. This is the half that can be wrong without
    the picture looking wrong, so it is re-derived rather than trusted."""
    b0 = one(D, K, name, line, is0, 'the zero-age test')
    b1 = one(D, K, name, line, is1, 'the one-frame test')
    ages = set()
    for b, wantv, what in ((b0, 0, 'zero'), (b1, 1, 'one')):
        m = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$', D.get(b, (0, ''))[1])
        if not m or K.get(m.group(2)) != wantv:
            raise Fail('%s@%d: the %s-age test is not `age == %d`'
                       % (name, line + 1, what, wantv))
        ages.add(m.group(1))
    age = one(D, K, name, line, ages, 'which value the age is')
    m = re.match(r'OpISub %uint ' + re.escape(S['fr']) + r' (%\w+)\s*$',
                 D.get(age, (0, ''))[1])
    if not m:
        raise Fail('%s@%d: the age is not `frame - stored frame`'
                   % (name, line + 1))
    ld = re.match(r'OpLoad %uint (%\w+) Aligned 4\s*$',
                  D.get(m.group(1), (0, ''))[1])
    if not ld:
        raise Fail('%s@%d: the stored frame is not a 4-aligned load'
                   % (name, line + 1))
    ch2 = ld.group(1)
    ac = re.match(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                  + re.escape(S['sp']) + r' (%\w+) (%\w+)\s*$',
                  D.get(ch2, (0, ''))[1])
    if not ac or K.get(ac.group(1)) != 0:
        raise Fail('%s@%d: the age load is not scratch[0][idx]'
                   % (name, line + 1))
    nx = re.match(r'OpIAdd %uint ' + re.escape(idx) + r' (%\w+)\s*$',
                  D.get(ac.group(2), (0, ''))[1])
    if not nx or K.get(nx.group(1)) != 1:
        raise Fail('%s@%d: the age word is not the one NEXT to this pixel\'s '
                   'identity' % (name, line + 1))
    st = [i for i, ln in enumerate(mod.lines)
          if re.match(r'\s*OpStore ' + re.escape(ch2) + r' \S+ Aligned 4\s*$', ln)]
    if not store:
        if st:
            raise Fail('%s@%d: the READER stores to the age word; it must only '
                       'read, or its own verdict is what it is reading'
                       % (name, line + 1))
        return
    if len(st) != 1 or not re.search(re.escape(S['fr']), mod.lines[st[0]]):
        raise Fail('%s@%d: %d stores of this frame to the age word, want 1'
                   % (name, line + 1, len(st)))
    if not (D[m.group(1)][0] < st[0] < line):
        raise Fail('%s@%d: the age store does not sit between its load and the '
                   'image write' % (name, line + 1))


# ------------------------------------------------------------ the modules
def check_module(path, spv, mode, knobs):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = W.defs_index(mod)
    K = consts(mod)
    src = '\n'.join(mod.lines)

    wm = [(i, re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln))
          for i, ln in enumerate(mod.lines)]
    writes = [(i, m.group(3)) for i, m in wm if m]
    coords = {i: m.group(2) for i, m in wm if m}
    v4writes = [(i, t) for i, t in writes
                if re.match(r'OpCompositeConstruct %v4float', D.get(t, (0, ''))[1])]
    rgen = bool(re.search(r'OpEntryPoint RayGenerationKHR\b', src))
    if rgen and mode != 'xprobe':
        raise Fail('%s: a RAYGEN carries the marker in --mode %s' % (name, mode))
    if rgen:
        # the reader paints only registers[5]+0/1; the guide buffer at +8 must
        # be left exactly as the game wrote it.
        v4writes = [(i, t) for i, t in v4writes
                    if raygen_img_off(mod, D, i) in XPROBE_OFFS]
    if not rgen and name in CENSUS[mode]['declined']:
        check_marker(spv, name, expect_marker=False)
        for op in ('OpRayQueryInitializeKHR', 'OpConvertUToAcceleration'):
            if op in src:
                raise Fail('%s: a DECLINED module carries %s' % (name, op))
        return dict(module=name, painted=0, declined=True)
    if not v4writes:
        raise Fail('%s: no v4float radiance write to paint' % name)

    bm = check_marker(spv, name, expect_marker=True)
    ptr = slot_pointer(mod, D, name, N_SLOT[mode])
    w0 = slot_word(D, ptr, W_MAGIC, name)
    mag = [i for i, (_, t) in D.items()
           if re.match(r'OpConstant %uint ' + str(MAGIC) + r'\s*$', t)]
    if len(mag) != 1:
        raise Fail('%s: %d magic constants, want 1' % (name, len(mag)))
    ok = only(D, r'OpIEqual %bool ' + re.escape(w0) + ' ' + re.escape(mag[0])
              + r'\s*$', name, 'magic comparison')[0]

    n_i = src.count('OpRayQueryInitializeKHR')
    n_p = src.count('OpRayQueryProceedKHR')
    n_t = src.count('OpRayQueryGetIntersectionTypeKHR')
    S = None
    if mode == 'xprobe':
        S = scratch_pointer(mod, D, name, ptr, src, mode)
        if rgen:
            painted = 0
            for line, texel in v4writes:
                mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) '
                              r'(%\w+) (%\w+)\s*$', D[texel][1])
                chans = []
                for c in mc.groups()[:3]:
                    mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$',
                                  D.get(c, (0, ''))[1])
                    if not mm:
                        raise Fail('%s@%d: a channel is not orig * verdict'
                                   % (name, line + 1))
                    chans.append(mm.group(2))
                check_xprobe_reader(mod, D, K, name, line, coords[line],
                                    chans, S, ok)
                painted += 1
            return dict(module=name, painted=painted, declined=False,
                        raygen=True, lo_id=bm['lo_id'], hi_id=bm['hi_id'])
        check_xprobe_writer(mod, D, K, name, v4writes, coords, S)
        return dict(module=name, painted=len(v4writes), declined=False,
                    raygen=False, lo_id=bm['lo_id'], hi_id=bm['hi_id'])
    if mode in ('probe',) + WMODES:
        if n_i or n_p or n_t or 'OpConvertUToAcceleration' in src:
            raise Fail('%s: --mode %s carries ray-query instructions'
                       % (name, mode))
        for k in (W_GEN, W_LO, W_HI):
            if re.search(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                         + re.escape(ptr) + r' %uint_' + str(k) + r'\b', src):
                raise Fail('%s: --mode %s reads slot word %d (the TLAS is not '
                           'this rung\'s business)' % (name, mode, k))
        acc = None
        if mode in WMODES:
            S = scratch_pointer(mod, D, name, ptr, src, mode)
            # Only stores through OUR pointer are counted: several resolvers
            # carry PhysicalStorageBuffer stores of the game's own (which is
            # also why the write half of this rung needs no new idiom).
            ours = {i for i, (_, t) in D.items()
                    if re.match(r'OpInBoundsAccessChain '
                                r'%_ptr_PhysicalStorageBuffer_uint '
                                + re.escape(S['sp']) + r' ', t)}
            n_st = len([ln for ln in mod.lines
                        if re.match(r'\s*OpStore (%\w+) %\w+ Aligned 4\s*$', ln)
                        and re.match(r'\s*OpStore (%\w+) ', ln).group(1) in ours])
            if n_st != len(v4writes) * S['wpp']:
                raise Fail('%s: %d stores through the scratch pointer over %d '
                           'painted writes at %d words per pixel'
                           % (name, n_st, len(v4writes), S['wpp']))
        else:
            for k in (W_FRAME, W_SCR_LO, W_SCR_HI, W_SCR_WORDS):
                if re.search(r'OpInBoundsAccessChain '
                             r'%_ptr_PhysicalStorageBuffer_uint '
                             + re.escape(ptr) + r' %uint_' + str(k) + r'\b', src):
                    raise Fail('%s: --mode probe reads slot word %d'
                               % (name, k))
            slotchains = {i for i, (_, t) in D.items()
                          if re.match(r'OpInBoundsAccessChain '
                                      r'%_ptr_PhysicalStorageBuffer_uint '
                                      + re.escape(ptr) + r' ', t)}
            if any(re.match(r'\s*OpStore (%\w+) ', ln)
                   and re.match(r'\s*OpStore (%\w+) ', ln).group(1) in slotchains
                   for ln in mod.lines):
                raise Fail('%s: --mode probe WRITES through the slot pointer'
                           % name)
    else:
        wlo = slot_word(D, ptr, W_LO, name)
        whi = slot_word(D, ptr, W_HI, name)
        av = only(D, r'OpCompositeConstruct %v2uint ' + re.escape(wlo) + ' '
                  + re.escape(whi) + r'\s*$', name, 'TLAS address vector')[0]
        acc = only(D, r'OpConvertUToAccelerationStructureKHR %\w+ '
                   + re.escape(av) + r'\s*$', name, 'AS conversion')[0]
        if 'OpCapability RayQueryKHR' not in src:
            raise Fail('%s: no RayQueryKHR capability' % name)
        if 'SPV_KHR_ray_query' not in src:
            raise Fail('%s: no SPV_KHR_ray_query extension' % name)
        if not (n_i == n_p == n_t == len(v4writes)):
            raise Fail('%s: init/proceed/type %d/%d/%d over %d writes'
                       % (name, n_i, n_p, n_t, len(v4writes)))

    ctx = cam = None
    if mode == 'rq':
        ctx = W.find_pos_chain(mod, D)
        if ctx is None:
            raise Fail('%s: paint present but no position reconstruction' % name)
        cam = W.find_campos(mod, ctx, D)
        if cam is None or cam['member'] != 0:
            raise Fail('%s: camera position is not cbv member 0' % name)

    painted = 0
    for line, texel in v4writes:
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      D[texel][1])
        chans = mc.groups()[:3]
        chain = []
        for c in chans:
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D.get(c, (0, ''))[1])
            if not mm:
                raise Fail('%s@%d: a radiance channel is not orig * chain'
                           % (name, line + 1))
            chain.append(mm.group(2))
        # the outer gate: class == 1, else EXACTLY 1.0 (bit-exact vanilla)
        gate = set()
        inner = []
        for ch, c in enumerate(chain):
            g = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                         D.get(c, (0, ''))[1])
            if not g:
                raise Fail('%s@%d: channel %d is not a class select'
                           % (name, line + 1, ch))
            gate.add(g.group(1))
            want_f(K, g.group(3), 1.0, name, 'the non-skin multiplier')
            inner.append(g.group(2))
        if len(gate) != 1:
            raise Fail('%s@%d: the three channels use different class gates'
                       % (name, line + 1))
        ge = re.match(r'OpIEqual %bool (%\w+) (%\w+)\s*$',
                      D.get(gate.pop(), (0, ''))[1])
        if not ge or K.get(ge.group(2)) != 1:
            raise Fail('%s@%d: the gate is not `class == 1`' % (name, line + 1))
        cls = ge.group(1)
        if not re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$',
                        D.get(cls, (0, ''))[1]):
            ph = re.match(r'OpPhi %uint (.*)$', D.get(cls, (0, ''))[1])
            srcs = re.findall(r'%\w+', ph.group(1)) if ph else []
            if not any(re.match(r'OpShiftRightLogical %uint (%\w+) %uint_5\s*$',
                                D.get(s, (0, ''))[1]) for s in srcs):
                raise Fail('%s@%d: the class is not a `word >> 5`'
                           % (name, line + 1))

        if mode in WMODES:
            check_wprobe_site(mod, D, K, name, line, coords[line], inner, S, ok,
                              mode)
        elif mode == 'probe':
            for ch, c in enumerate(inner):
                s = re.match(r'OpSelect %float ' + re.escape(ok)
                             + r' (%\w+) (%\w+)\s*$', D.get(c, (0, ''))[1])
                if not s:
                    raise Fail('%s@%d: channel %d is not selected on the magic'
                               % (name, line + 1, ch))
                want_f(K, s.group(1), COL['green'][ch], name, 'the match colour')
                want_f(K, s.group(2), COL['red'][ch], name, 'the mismatch colour')
        else:
            hits = set()
            for ch, c in enumerate(inner):
                s = re.match(r'OpSelect %float ' + re.escape(ok)
                             + r' (%\w+) (%\w+)\s*$', D.get(c, (0, ''))[1])
                if not s:
                    raise Fail('%s@%d: channel %d is not selected on the magic '
                               '-- a missed fixup would read as a miss'
                               % (name, line + 1, ch))
                want_f(K, s.group(2), COL['red'][ch], name, 'the mismatch colour')
                h = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                             D.get(s.group(1), (0, ''))[1])
                if not h:
                    raise Fail('%s@%d: channel %d is not selected on the hit'
                               % (name, line + 1, ch))
                hits.add(h.group(1))
                want_f(K, h.group(2), COL['blue'][ch], name, 'the hit colour')
                want_f(K, h.group(3), COL['amber'][ch], name, 'the miss colour')
            if len(hits) != 1:
                raise Fail('%s@%d: the channels disagree on the hit test'
                           % (name, line + 1))
            hb = re.match(r'OpINotEqual %bool (%\w+) (%\w+)\s*$',
                          D.get(hits.pop(), (0, ''))[1])
            if not hb or K.get(hb.group(2)) != 0:
                raise Fail('%s@%d: the hit test is not `type != None`'
                           % (name, line + 1))
            ty = re.match(r'OpRayQueryGetIntersectionTypeKHR %uint (%\w+) (%\w+)\s*$',
                          D.get(hb.group(1), (0, ''))[1])
            if not ty or K.get(ty.group(2)) != 1:
                raise Fail('%s@%d: the intersection read is not COMMITTED'
                           % (name, line + 1))
            rq = ty.group(1)
            # ONE Function-storage query object is reused by every site in the
            # module, so the site's Initialize is the nearest one ABOVE its
            # committed-type read -- and the two must sit in the SAME basic
            # block with the Proceed between them, or the ordering that makes
            # the reuse safe is not actually in the bytes.
            tline = D[hb.group(1)][0]
            ini = pro = None
            for i in range(tline - 1, -1, -1):
                t = mod.lines[i].strip()
                if re.match(r'OpRayQueryInitializeKHR ' + re.escape(rq) + r'\b', t):
                    ini = i
                    break
                if re.match(r'OpRayQueryProceedKHR %bool ' + re.escape(rq) + r'\s*$',
                            t) or re.search(r'= OpRayQueryProceedKHR %bool '
                                            + re.escape(rq) + r'\s*$', t):
                    pro = i
                if re.match(r'(%\w+ = )?Op(Label|Branch|BranchConditional|Switch'
                            r'|Return|ReturnValue|Kill|Unreachable)\b', t):
                    raise Fail('%s@%d: control flow between the query init and '
                               'its committed-type read' % (name, line + 1))
            if ini is None:
                raise Fail('%s@%d: no Initialize above the committed-type read'
                           % (name, line + 1))
            if pro is None or not (ini < pro < tline):
                raise Fail('%s@%d: no Proceed between Initialize and the '
                           'committed-type read' % (name, line + 1))
            a = mod.lines[ini].split()[1:]
            if a[1] != acc:
                raise Fail('%s@%d: the query is not initialized with the slot '
                           'TLAS' % (name, line + 1))
            if K.get(a[2]) != knobs['flags']:
                raise Fail('%s@%d: ray flags %s, want %d'
                           % (name, line + 1, K.get(a[2]), knobs['flags']))
            if K.get(a[3]) != knobs['mask']:
                raise Fail('%s@%d: cull mask %s, want %d'
                           % (name, line + 1, K.get(a[3]), knobs['mask']))
            want_f(K, a[5], knobs['tmin'], name, 'tmin')
            want_f(K, a[7], knobs['tmax'], name, 'tmax')
            dv = re.match(r'OpConstantComposite %v3float (%\w+) (%\w+) (%\w+)\s*$',
                          D.get(a[6], (0, ''))[1])
            if not dv:
                raise Fail('%s@%d: the direction is not a constant vector'
                           % (name, line + 1))
            for ch in range(3):
                want_f(K, dv.group(ch + 1), DIR_XYZ[ch], name, 'direction')
            org = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                           D.get(a[4], (0, ''))[1])
            if not org:
                raise Fail('%s@%d: the origin is not a v3 construct'
                           % (name, line + 1))
            # `99` sec 10.6 -- the whole point of the rung.
            _check_position_triple(D, list(org.groups()), ctx, cam, 'cam',
                                   name, line)
        painted += 1
    return dict(module=name, painted=painted, declined=False,
                lo_id=bm['lo_id'], hi_id=bm['hi_id'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('--mode', choices=('probe', 'rq') + WMODES,
                    default='probe')
    ap.add_argument('--negative', action='store_true',
                    help='assert the directory carries NO marker anywhere')
    ap.add_argument('--flags', type=int, default=DEFAULTS['flags'])
    ap.add_argument('--mask', type=int, default=DEFAULTS['mask'])
    ap.add_argument('--tmin', type=float, default=DEFAULTS['tmin'])
    ap.add_argument('--tmax', type=float, default=DEFAULTS['tmax'])
    a = ap.parse_args()
    knobs = dict(flags=a.flags, mask=a.mask, tmin=a.tmin, tmax=a.tmax)

    comp = sorted(glob.glob(os.path.join(a.rung, '*.dxil.spv')))
    rgs = sorted(glob.glob(os.path.join(a.rung, '*.rgs_*.spv')))
    if a.negative:
        bad = [f for f in comp + rgs if binary_marker(f)['markers']
               or binary_marker(f)['n_lo'] or binary_marker(f)['n_hi']]
        if bad:
            raise SystemExit('FAIL: %d modules carry the marker or a sentinel: '
                             '%s' % (len(bad), [os.path.basename(x) for x in bad[:3]]))
        print('verify_bda --negative OK: 0 of %d modules carry '
              'CALLISTO_BDA_SLOT_V1 or either sentinel half' % len(comp + rgs))
        return
    want = CENSUS[a.mode]
    if len(comp) != want['modules'] or len(rgs) != 16:
        raise SystemExit('FAIL: %d compute + %d raygen, want %d + 16'
                         % (len(comp), len(rgs), want['modules']))
    rg_painted, rg_tot = [], 0
    if a.mode != 'xprobe':
        for f in rgs:
            m = binary_marker(f)
            if m['markers'] or m['n_lo'] or m['n_hi']:
                raise SystemExit('FAIL: a RAYGEN carries the marker: %s'
                                 % os.path.basename(f))
    else:
        with tempfile.TemporaryDirectory() as td:
            for f in rgs:
                n = os.path.basename(f)[:-4]
                asm = os.path.join(td, n + '.spvasm')
                subprocess.run(['spirv-dis', f, '-o', asm], check=True)
                try:
                    r = check_module(asm, f, a.mode, knobs)
                except Fail as e:
                    raise SystemExit('FAIL: %s' % e)
                if not r.get('raygen'):
                    raise SystemExit('FAIL: %s did not verify as a raygen' % n)
                rg_painted.append(n)
                rg_tot += r['painted']
    painted_mods, tot, ids = [], 0, set()
    with tempfile.TemporaryDirectory() as td:
        for f in comp:
            n = os.path.basename(f)[:-9]
            asm = os.path.join(td, n + '.spvasm')
            subprocess.run(['spirv-dis', f, '-o', asm], check=True)
            try:
                r = check_module(asm, f, a.mode, knobs)
            except Fail as e:
                raise SystemExit('FAIL: %s' % e)
            if not r['declined']:
                painted_mods.append(n)
                tot += r['painted']
                ids.add((r['lo_id'], r['hi_id']))
    declined = {os.path.basename(f)[:-9] for f in comp} - set(painted_mods)
    ok = True
    if len(painted_mods) != want['painted']:
        print('FAIL: %d painted modules, census says %d'
              % (len(painted_mods), want['painted'])); ok = False
    if declined != want['declined']:
        print('FAIL: declines %s, expected %s'
              % (sorted(declined), sorted(want['declined']))); ok = False
    if tot != want['writes']:
        print('FAIL: %d painted writes, census says %d' % (tot, want['writes']))
        ok = False
    if a.mode == 'xprobe':
        if len(rg_painted) != want['rg_modules']:
            print('FAIL: %d raygens verified, census says %d'
                  % (len(rg_painted), want['rg_modules'])); ok = False
        if rg_tot != want['rg_writes']:
            print('FAIL: %d raygen painted writes, census says %d'
                  % (rg_tot, want['rg_writes'])); ok = False
    if not ok:
        raise SystemExit(1)
    print('verify_bda OK (--mode %s): %d modules, %d painted writes, '
          '%d declined by name, %d distinct (lo,hi) id pairs across the set; '
          'marker sentinel %016x magic %08x; slot %d x uint'
          % (a.mode, len(painted_mods), tot, len(declined), len(ids),
             (SENT_HI << 32) | SENT_LO, MAGIC, N_SLOT[a.mode])
          + ('; PLUS %d raygens READING %d sites, storing nothing'
             % (len(rg_painted), rg_tot) if a.mode == 'xprobe' else '')
          + ('; scratch = slot words 8/9/10, index %d + %d*((y*%d + x) & '
             '(words/%d - 1)), identity = %08x ^ %d*pix%s'
             % (SCRATCH_HDR, WORDS_PER_PIXEL[a.mode], PIX_PITCH,
                2 ** WORDS_PER_PIXEL[a.mode], SCRATCH_SIG, PIX_HASH,
                ' ^ frame' if a.mode == 'wprobe' else ' + age word')
             if a.mode in WMODES else
             '' if a.mode == 'probe' else
             '; flags %d mask %d tmin %g tmax %g, origin = P - cbv[..][0]'
             % (knobs['flags'], knobs['mask'], knobs['tmin'], knobs['tmax'])))


if __name__ == '__main__':
    main()
