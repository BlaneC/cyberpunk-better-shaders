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
                       W_MAGIC, W_GEN, W_LO, W_HI)

CENSUS = {'probe': dict(modules=77, painted=76, writes=151,
                        declined=DECLINE_ALL),
          'rq': dict(modules=77, painted=75, writes=150,
                     declined=DECLINE_ALL | DECLINE_RQ)}
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


def slot_pointer(mod, D, name):
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
    sm = re.match(r'OpTypeStruct((?: %\w+){' + str(SLOT_MEMBERS) + r'})\s*$',
                  D.get(st, (0, ''))[1])
    if not sm or set(sm.group(1).split()) != {'%uint'}:
        raise Fail('%s: the slot struct is not %d x uint (%r)'
                   % (name, SLOT_MEMBERS, D.get(st, (0, ''))[1]))
    src = '\n'.join(mod.lines)
    if not re.search(r'OpDecorate ' + re.escape(st) + r' Block\b', src):
        raise Fail('%s: the slot struct is not a Block' % name)
    for k in range(SLOT_MEMBERS):
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


# ------------------------------------------------------------ the modules
def check_module(path, spv, mode, knobs):
    mod, _ = load_lenient(path)
    name = mod.name.split('.')[0]
    D = W.defs_index(mod)
    K = consts(mod)
    src = '\n'.join(mod.lines)

    writes = [(i, re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln).group(3))
              for i, ln in enumerate(mod.lines)
              if re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)]
    v4writes = [(i, t) for i, t in writes
                if re.match(r'OpCompositeConstruct %v4float', D.get(t, (0, ''))[1])]
    if name in CENSUS[mode]['declined']:
        check_marker(spv, name, expect_marker=False)
        for op in ('OpRayQueryInitializeKHR', 'OpConvertUToAcceleration'):
            if op in src:
                raise Fail('%s: a DECLINED module carries %s' % (name, op))
        return dict(module=name, painted=0, declined=True)
    if not v4writes:
        raise Fail('%s: no v4float radiance write to paint' % name)

    bm = check_marker(spv, name, expect_marker=True)
    ptr = slot_pointer(mod, D, name)
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
    if mode == 'probe':
        if n_i or n_p or n_t or 'OpConvertUToAcceleration' in src:
            raise Fail('%s: --mode probe carries ray-query instructions' % name)
        for k in (W_GEN, W_LO, W_HI):
            if re.search(r'OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint '
                         + re.escape(ptr) + r' %uint_' + str(k) + r'\b', src):
                raise Fail('%s: --mode probe reads slot word %d' % (name, k))
        acc = None
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

        if mode == 'probe':
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
    ap.add_argument('--mode', choices=('probe', 'rq'), default='probe')
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
    for f in rgs:
        m = binary_marker(f)
        if m['markers'] or m['n_lo'] or m['n_hi']:
            raise SystemExit('FAIL: a RAYGEN carries the marker: %s'
                             % os.path.basename(f))
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
    if not ok:
        raise SystemExit(1)
    print('verify_bda OK (--mode %s): %d modules, %d painted writes, '
          '%d declined by name, %d distinct (lo,hi) id pairs across the set; '
          'marker sentinel %016x magic %08x; slot %d x uint'
          % (a.mode, len(painted_mods), tot, len(declined), len(ids),
             (SENT_HI << 32) | SENT_LO, MAGIC, SLOT_MEMBERS)
          + ('' if a.mode == 'probe' else
             '; flags %d mask %d tmin %g tmax %g, origin = P - cbv[..][0]'
             % (knobs['flags'], knobs['mask'], knobs['tmin'], knobs['tmax'])))


if __name__ == '__main__':
    main()
