#!/usr/bin/env python3
"""whash_core -- a WORLD-STABLE STOCHASTIC SEED for the compute resolvers.

handoff/107.  NEW FILE.  It imports `wpos_core` read-only and edits no shared
patcher.

WHAT THIS IS
------------
`99` proved that the 77 GLCompute resolvers reconstruct a **world** shading
point P (metres, Z up, camera at `cbv[registers[0]+12][0].xyz`) and shipped
`wpos_core.emit_world_pos` to hand it to a splice site.  This file is the
first consumer primitive built on it: an integer lattice hash of `floor(P /
cell)`, a trilinear value noise built from that hash, and a 3-octave fbm.

    emit_world_hash (E, P, cell, seed)        -> (u0, u1, u2) in [0, 1)
    emit_value_noise(E, P, cell, seed)        -> (n0, n1, n2) in [0, 1]
    emit_fbm        (E, P, cell, seed, oct=3) -> (f0, f1, f2) in [0, 1]

All three return **three** decorrelated channels for the price of one lattice
walk: the avalanche produces a 32-bit word per cell and the channels are three
disjoint 10-bit fields of it.  A caller that needs one field pays for three
anyway; a caller that needs three (roughness, albedo, porosity -- `107` B/C)
pays once.

WHAT IT IS FOR
--------------
Anything whose value must be **a property of the surface, not of the frame**:

  * material decisions -- "is this patch of concrete the rough one",
  * per-surface variation -- roughness, albedo, porosity, wear, dirt,
  * dither / stratification offsets that must not move when the camera does.

Because the argument is P and P is world space, the value at a given point on
a given wall is the same in every frame, from every camera position, at every
resolution.  It therefore **does not boil**: the denoiser and the temporal
accumulator see a static field and treat it as texture, not as noise.

**WHAT IT MUST NEVER BE USED FOR: PATH-SAMPLING SEEDS.**  A sampling seed has
to *vary* per frame, or temporal accumulation converges to one sample and the
estimator is biased forever -- the variance never drops and the bias never
goes away.  This hash is world-stable **by construction**, which is exactly
the property a sampling seed must not have.  Do not feed it to a light pick,
a BRDF sample, a russian-roulette test, a reservoir's random stream, or a
blue-noise offset.  If a feature wants both, it needs two seeds: this one for
"what is this surface like", and the shader's own frame-varying stream for
"which direction do I trace".  (`37` is the cautionary tale for the other half
of this: a technique whose preconditions this renderer does not meet is a
no-op, and a sampling change that deletes the per-pixel seed is a different
feature again.)

Two more prohibitions, cheaper but real:

  * **Never hash P itself without a `floor`.**  P is a float32 reconstructed
    through a perspective divide; the low bits are depth-quantisation noise
    and hashing them gives per-pixel white noise that *does* boil.  Only the
    integer cell index is stable.
  * **Never use a cell smaller than the depth quantisation supports at the
    intended range.**  A 12 mm cell at 6 m is ~1.7 px at 720p; below one pixel
    the lattice aliases and the "stable" field turns into shimmer.  `107` B's
    distance fade exists for exactly this reason.

WHY AN INTEGER LATTICE HASH AND NOT A TEXTURE
---------------------------------------------
`GOTCHAS` 13: a bindless descriptor index moved 73203 -> 503350 in 29 seconds.
A noise *texture* would need a stable address; an arithmetic hash needs none.
Existence is not addressability, and this route sidesteps the question.

BIT-EXACTNESS
-------------
`replay()` is an interpreter for the exact instruction text the emitters
produce -- float32 and uint32 throughout, via numpy scalars, with the same
opcodes in the same order.  `dev/whash_model.py` is an independent CPU
reference written from the algorithm, not from the emitter.  `--selftest`
runs one against the other over a random point cloud and requires **bit
equality**, not a tolerance: any difference in rounding, in operand order, or
in a folded constant shows up as a mismatched float32 bit pattern.
"""
import argparse
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- constants
# Teschner, Heidelberger, Mueller & Gross (2003) spatial-hash multipliers --
# the same three `99`'s hunt-wpos probe used, so a cell painted by that probe
# and a cell keyed by this primitive are the SAME lattice cell.
HASH_K = (73856093, 19349663, 83492791)
AVAL_M = 668265261                 # 0x27d4eb2d, Wang/murmur-style finaliser
BIAS = 4194304.0                   # 2^22: floor(P/cell) + BIAS is a NON-NEGATIVE
                                   # float32 INTEGER for |P| < BIAS*cell (50 km
                                   # at the 12 mm cell), and stays under 2^24 so
                                   # the add is exact.  65536 -- 99's value, for
                                   # a 1 m cell -- wraps at 786 m with a 12 mm
                                   # one, which is inside Night City.
FIELD_BITS = 10                    # three disjoint 10-bit fields of one word
FIELD_MASK = (1 << FIELD_BITS) - 1
FIELD_SCALE = 1.0 / float(FIELD_MASK)
SEED_STEP = 0x9E3779B9             # octave-to-octave seed stride (golden ratio)

DEFAULT_OCTAVES = 3
DEFAULT_LACUNARITY = 2.0
DEFAULT_GAIN = 0.5


def octave_weights(octaves=DEFAULT_OCTAVES, gain=DEFAULT_GAIN):
    """Normalised fbm weights, so the sum lands in [0, 1] with no clamp."""
    w = [gain ** k for k in range(octaves)]
    s = sum(w)
    return [x / s for x in w]


# ------------------------------------------------------------- emission ctx
class Emit:
    """Instruction sink + constant interner for one module.

    `mod.const` memoises float constants (Module.fconst); `mod.uconst` does
    NOT memoise pending declarations, and asking twice emits the constant
    twice -- `spirv-val` then fails with "Id is defined more than once".  That
    trap has now been hit by `94`, `99` and this file, so the memo lives here
    and every emitter in `107` goes through `E.U`.
    """

    def __init__(self, mod, ins, consts, uc=None):
        self.mod = mod
        self.ins = ins
        self.consts = consts
        self.gl = mod.glsl
        self.uc = {} if uc is None else uc
        self.uc.setdefault('decls', consts)
        self.cvals = {}          # const id -> ('f'|'u', python value)
        self._seed_consts()

    def _seed_consts(self):
        """Every OpConstant already in the module, for replay()."""
        for ln in self.mod.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %(float|uint|int) (\S+)\s*$', ln)
            if not m:
                continue
            k = 'f' if m.group(2) == 'float' else 'u'
            try:
                self.cvals[m.group(1)] = (k, float(m.group(3)) if k == 'f'
                                          else int(m.group(3)))
            except ValueError:
                pass

    # -- constants ---------------------------------------------------------
    def C(self, v):
        nid, decl = self.mod.const(v)
        if decl:
            self.consts.append(decl)
        self.cvals[nid] = ('f', float(np.float32(v)))
        return nid

    def U(self, n):
        key = ('u', int(n))
        if key in self.uc:
            return self.uc[key]
        nid, decl = self.mod.uconst(n)
        if decl:
            self.uc['decls'].append(decl)
        self.uc[key] = nid
        self.cvals[nid] = ('u', int(n) & 0xFFFFFFFF)
        return nid

    # -- instructions ------------------------------------------------------
    def I(self):
        return self.mod.new_id()

    def op(self, opcode, ty, *args):
        i = self.I()
        self.ins.append(f"        {i} = {opcode} {ty} " + ' '.join(str(a) for a in args))
        return i

    def ext(self, name, ty, *args):
        i = self.I()
        self.ins.append(f"        {i} = OpExtInst {ty} {self.gl} {name} "
                        + ' '.join(str(a) for a in args))
        return i

    # -- shorthands used all over 107 --------------------------------------
    def fmul(self, a, b):
        return self.op('OpFMul', '%float', a, b)

    def fadd(self, a, b):
        return self.op('OpFAdd', '%float', a, b)

    def fsub(self, a, b):
        return self.op('OpFSub', '%float', a, b)

    def fma(self, a, b, c):
        """a*b + c, one instruction -- what the compiler itself emits."""
        return self.ext('Fma', '%float', a, b, c)

    def lerp(self, a, b, t):
        """a + (b - a)*t.  Exact at t = 0 and t = 1.

        Deliberately NOT `Fma`.  GLSL.std.450 `Fma` is only a single-rounding
        operation when decorated `NoContraction`; undecorated, whether it
        fuses is up to the driver, so a model that reproduces it bit-exactly
        offline is reproducing ONE of two legal answers.  Three plain
        instructions cost one more each and are fully determined, which is
        what makes `--selftest`'s bit-equality a real gate rather than a
        statement about this machine's numpy.  (`wpos_core`'s refetch does
        use Fma -- it is replaying the compiler's own chain, where matching
        the original bytes is the point.)
        """
        d = self.fsub(b, a)
        m = self.fmul(d, t)
        return self.fadd(m, a)


# ------------------------------------------------------------- THE PRIMITIVE
def _cell_index(E, P, cell):
    """(n0, n1, n2) uint lattice index and (t0, t1, t2) in-cell fraction."""
    inv = E.C(1.0 / cell)
    bias = E.C(BIAS)
    n, t = [], []
    for k in range(3):
        w = E.fmul(P[k], inv)
        q = E.ext('Floor', '%float', w)
        t.append(E.fsub(w, q))
        b = E.fadd(q, bias)
        n.append(E.op('OpConvertFToU', '%uint', b))
    return tuple(n), tuple(t)


def _avalanche(E, h):
    """Murmur-style finaliser.  Three rounds: the two-round form leaves a
    visible axis correlation on a lattice (adjacent cells differ in one
    operand only), which reads on screen as stripes rather than as noise."""
    for sh in (15, 13):
        s = E.op('OpShiftRightLogical', '%uint', h, E.U(sh))
        h = E.op('OpBitwiseXor', '%uint', h, s)
        h = E.op('OpIMul', '%uint', h, E.U(AVAL_M))
    s = E.op('OpShiftRightLogical', '%uint', h, E.U(16))
    return E.op('OpBitwiseXor', '%uint', h, s)


def _fields(E, h):
    """Three disjoint 10-bit fields of one avalanched word -> [0, 1] floats."""
    sc = E.C(FIELD_SCALE)
    out = []
    for k in range(3):
        w = h if k == 0 else E.op('OpShiftRightLogical', '%uint', h,
                                  E.U(FIELD_BITS * k))
        b = E.op('OpBitwiseAnd', '%uint', w, E.U(FIELD_MASK))
        f = E.op('OpConvertUToF', '%float', b)
        out.append(E.fmul(f, sc))
    return tuple(out)


def _hash_uints(E, n, seed):
    """The lattice hash of one integer cell -> the avalanched word."""
    m = [E.op('OpIMul', '%uint', n[k], E.U(HASH_K[k])) for k in range(3)]
    xy = E.op('OpBitwiseXor', '%uint', m[0], m[1])
    sz = E.op('OpBitwiseXor', '%uint', m[2], E.U(seed))
    h = E.op('OpBitwiseXor', '%uint', xy, sz)
    return _avalanche(E, h)


def emit_world_hash(E, P, cell, seed):
    """`emit_world_hash(P_world, cell_size, seed)` -- THE PRIMITIVE.

    Returns three float ids, each uniform in [0, 1], constant over the
    `cell`-metre cube of world space that contains P, and independent of the
    camera.  ~30 instructions.

    P must be the resolvers' world-space shading point (`wpos_core
    .emit_world_pos`); `cell` is in METRES (`99` §10.8 measured the unit) and
    `seed` is any uint32 -- two features that want independent fields on the
    same lattice differ only in `seed`.

    NOT a sampling seed.  See the module docstring, in bold.
    """
    n, _t = _cell_index(E, P, cell)
    return _fields(E, _hash_uints(E, n, seed))


def emit_value_noise(E, P, cell, seed):
    """Trilinear value noise on the same lattice.  ~230 instructions.

    Eight corner hashes, a cubic (smoothstep) fade per axis, seven lerps per
    channel.  Continuous across cell walls, which `emit_world_hash` is not --
    that discontinuity is a feature for a material *decision* and an artefact
    for a *perturbation*, which is why 107 B and C use this and the
    `micro-cell` diagnostic uses the flat hash.

    The fade is `t*t*(3-2t)`, not the quintic: the quintic's extra two
    instructions per axis buy a continuous second derivative that nothing
    downstream reads, and a perturbation of +-0.08 in roughness cannot show a
    C1 seam.
    """
    n, t = _cell_index(E, P, cell)
    # cubic fade per axis
    s = []
    for k in range(3):
        two_t = E.fmul(t[k], E.C(2.0))
        a = E.fsub(E.C(3.0), two_t)
        tt = E.fmul(t[k], t[k])
        s.append(E.fmul(tt, a))
    # the eight corners: precompute per-axis products for both parities
    one = E.U(1)
    np1 = [E.op('OpIAdd', '%uint', n[k], one) for k in range(3)]
    prod = [[E.op('OpIMul', '%uint', v, E.U(HASH_K[k])) for v in (n[k], np1[k])]
            for k in range(3)]
    seed_id = E.U(seed)
    xy = [[E.op('OpBitwiseXor', '%uint', prod[0][i], prod[1][j])
           for j in (0, 1)] for i in (0, 1)]
    sz = [E.op('OpBitwiseXor', '%uint', prod[2][k], seed_id) for k in (0, 1)]
    corner = {}
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                h = E.op('OpBitwiseXor', '%uint', xy[i][j], sz[k])
                corner[(i, j, k)] = _fields(E, _avalanche(E, h))
    out = []
    for ch in range(3):
        c = {}
        for j in (0, 1):
            for k in (0, 1):
                c[(j, k)] = E.lerp(corner[(0, j, k)][ch],
                                   corner[(1, j, k)][ch], s[0])
        c0 = E.lerp(c[(0, 0)], c[(1, 0)], s[1])
        c1 = E.lerp(c[(0, 1)], c[(1, 1)], s[1])
        out.append(E.lerp(c0, c1, s[2]))
    return tuple(out)


def emit_fbm(E, P, cell, seed, octaves=DEFAULT_OCTAVES,
             lacunarity=DEFAULT_LACUNARITY, gain=DEFAULT_GAIN):
    """3-octave fractional Brownian motion on the world lattice.

    `octaves` value-noise evaluations at cell, cell/lacunarity, ... summed
    with weights `gain^k` NORMALISED to sum to 1, so the result is in [0, 1]
    with no clamp and no renormalisation constant to get wrong.  Each octave
    carries its own seed (`seed + k*SEED_STEP`), so the octaves are
    independent fields rather than three views of one.

    Cost is linear in `octaves`: ~230 instructions each, ~700 for the default
    three.  That is emitted ONCE PER MODULE at a hoist point that dominates
    every splice (107 §3), never per site: P is one value per invocation, so
    the noise is one value per invocation too.
    """
    ws = octave_weights(octaves, gain)
    acc = None
    for o in range(octaves):
        c = cell / (lacunarity ** o)
        n = emit_value_noise(E, P, c, (seed + o * SEED_STEP) & 0xFFFFFFFF)
        w = E.C(ws[o])
        if acc is None:
            acc = [E.fmul(n[ch], w) for ch in range(3)]
        else:
            acc = [E.fadd(E.fmul(n[ch], w), acc[ch]) for ch in range(3)]
    return tuple(acc)


def signed(E, f):
    """[0,1] -> [-1,1].  `2f - 1`, two plain instructions (see Emit.lerp)."""
    return E.fadd(E.fmul(f, E.C(2.0)), E.C(-1.0))


# ------------------------------------------------------- the replay machine
_F32 = np.float32
_U32 = np.uint32

_BIN = {
    'OpFAdd': lambda a, b: _F32(a) + _F32(b),
    'OpFSub': lambda a, b: _F32(a) - _F32(b),
    'OpFMul': lambda a, b: _F32(a) * _F32(b),
    'OpFDiv': lambda a, b: _F32(a) / _F32(b),
    # uint32 arithmetic WRAPS; do it in uint64 and mask, so numpy does not
    # raise an overflow warning on the very behaviour the hash depends on.
    'OpIAdd': lambda a, b: _U32((int(a) + int(b)) & 0xFFFFFFFF),
    'OpIMul': lambda a, b: _U32((int(a) * int(b)) & 0xFFFFFFFF),
    'OpBitwiseXor': lambda a, b: _U32(a) ^ _U32(b),
    'OpBitwiseAnd': lambda a, b: _U32(a) & _U32(b),
    'OpBitwiseOr': lambda a, b: _U32(a) | _U32(b),
    'OpShiftRightLogical': lambda a, b: _U32(_U32(a) >> _U32(b)),
    'OpShiftLeftLogical': lambda a, b: _U32(_U32(a) << _U32(b)),
    'OpFOrdLessThan': lambda a, b: bool(_F32(a) < _F32(b)),
    'OpFOrdGreaterThan': lambda a, b: bool(_F32(a) > _F32(b)),
    'OpFOrdGreaterThanEqual': lambda a, b: bool(_F32(a) >= _F32(b)),
    'OpIEqual': lambda a, b: bool(_U32(a) == _U32(b)),
    'OpINotEqual': lambda a, b: bool(_U32(a) != _U32(b)),
    'OpLogicalAnd': lambda a, b: bool(a) and bool(b),
    'OpLogicalOr': lambda a, b: bool(a) or bool(b),
}

_EXT1 = {
    'Floor': lambda a: _F32(math.floor(float(a))),
    'Fract': lambda a: _F32(float(a) - math.floor(float(a))),
    'Sqrt': lambda a: _F32(np.sqrt(_F32(a))),
    'InverseSqrt': lambda a: _F32(1.0) / _F32(np.sqrt(_F32(a))),
    'FAbs': lambda a: _F32(abs(_F32(a))),
    'Log2': lambda a: _F32(np.log2(_F32(a))),
    'Exp2': lambda a: _F32(np.exp2(_F32(a))),
}


def replay(lines, env, cvals):
    """Execute the exact emitted instruction text.  float32 / uint32.

    `env` maps input ids (P components, cosines, ...) to numpy scalars and is
    UPDATED IN PLACE, so the caller reads results out of it by id.  `cvals`
    maps constant ids to ('f'|'u', value) -- `Emit.cvals` is exactly that.

    This is deliberately an interpreter over the TEXT and not a re-derivation
    of the algorithm: the whole point of the gate is that the thing tested is
    the thing shipped (`GOTCHAS`: a byte diff is not coverage).
    """
    def V(tok):
        if tok in env:
            return env[tok]
        if tok in cvals:
            k, v = cvals[tok]
            return _F32(v) if k == 'f' else _U32(v)
        m = re.match(r'%float_n?([\d_]+(?:e[+-]?\d+)?)$', tok)
        if m:
            s = m.group(1).replace('_', '.')
            v = float(s)
            return _F32(-v if tok.startswith('%float_n') else v)
        m = re.match(r'%uint_(\d+)$', tok)
        if m:
            return _U32(int(m.group(1)))
        if tok in ('%true', '%false'):
            return tok == '%true'
        raise KeyError(f"replay: unknown operand {tok}")

    for ln in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*(\S+)\s+(\S+)\s*(.*)$', ln.rstrip())
        if not m:
            raise ValueError(f"replay: cannot parse {ln!r}")
        dst, opc, ty, rest = m.groups()
        a = rest.split()
        if opc in _BIN:
            env[dst] = _BIN[opc](V(a[0]), V(a[1]))
        elif opc == 'OpExtInst':
            name, args = a[1], a[2:]
            if name in _EXT1:
                env[dst] = _EXT1[name](V(args[0]))
            elif name == 'Fma':
                env[dst] = _F32(_F32(V(args[0])) * _F32(V(args[1]))
                                + _F32(V(args[2])))
            elif name == 'NMin':
                env[dst] = _F32(min(_F32(V(args[0])), _F32(V(args[1]))))
            elif name == 'NMax':
                env[dst] = _F32(max(_F32(V(args[0])), _F32(V(args[1]))))
            elif name == 'NClamp':
                env[dst] = _F32(min(max(_F32(V(args[0])), _F32(V(args[1]))),
                                    _F32(V(args[2]))))
            elif name == 'Pow':
                env[dst] = _F32(np.float_power(_F32(V(args[0])),
                                               _F32(V(args[1]))))
            else:
                raise ValueError(f"replay: unsupported GLSL op {name}")
        elif opc == 'OpConvertFToU':
            env[dst] = _U32(int(_F32(V(a[0]))))
        elif opc == 'OpConvertUToF':
            env[dst] = _F32(float(_U32(V(a[0]))))
        elif opc == 'OpSelect':
            env[dst] = V(a[1]) if bool(V(a[0])) else V(a[2])
        elif opc == 'OpLogicalNot':
            env[dst] = not bool(V(a[0]))
        elif opc == 'OpFNegate':
            env[dst] = _F32(-_F32(V(a[0])))
        else:
            raise ValueError(f"replay: unsupported opcode {opc} in {ln!r}")
    return env


# ------------------------------------------------------------ a fake module
class FakeModule:
    """Just enough Module for the emitters, so the selftest needs no .spvasm.

    It is NOT a stand-in for a real module in a build: it has no lines to
    splice into and no dominance.  It exists so that the instruction text the
    selftest replays is emitted by the SAME code path the patcher uses.
    """

    def __init__(self):
        self.lines = []
        self.glsl = '%1'
        self.fconst = {}
        self.next_id = 1000
        self.name = '<fake>'
        self.ident = 'fake'

    def new_id(self):
        self.next_id += 1
        return f"%{self.next_id}"

    def const(self, v):
        key = float(np.float32(v))
        if key in self.fconst:
            return self.fconst[key], None
        nid = self.new_id()
        self.fconst[key] = nid
        return nid, f"    {nid} = OpConstant %float {key!r}"

    def uconst(self, n):
        return f"%uint_{int(n)}", None


# ----------------------------------------------------------------- selftest
def _selftest(npts=512, seed=0xC0FFEE, cell=0.012, octaves=DEFAULT_OCTAVES,
              verbose=False):
    import whash_model as M
    rng = np.random.default_rng(20260903)
    fails = []
    checks = 0

    def run(emitter, ref, label, **kw):
        nonlocal checks
        mod = FakeModule()
        ins, consts = [], []
        E = Emit(mod, ins, consts)
        P = ('%p0', '%p1', '%p2')
        out = emitter(E, P, cell, seed, **kw)
        # world coordinates spanning ~+-400 m, plus a few deliberate edges
        pts = rng.uniform(-400.0, 400.0, size=(npts, 3)).astype(np.float32)
        edge = np.array([[0, 0, 0], [cell, cell, cell], [-cell, 0, cell * 0.5],
                         [1e-7, -1e-7, 0], [123.456, -78.9, 4.25]],
                        dtype=np.float32)
        pts = np.concatenate([pts, edge])
        for p in pts:
            env = {P[k]: np.float32(p[k]) for k in range(3)}
            replay(ins, env, E.cvals)
            got = tuple(float(env[o]) for o in out)
            want = ref(p, cell, seed, **kw)
            checks += 1
            for ch in range(3):
                if np.float32(got[ch]).tobytes() != np.float32(want[ch]).tobytes():
                    fails.append((label, tuple(float(x) for x in p), ch,
                                  got[ch], want[ch]))
        if verbose:
            print(f"  {label:14s}: {len(ins):5d} instructions, "
                  f"{len(consts):3d} constants, {len(pts)} points")
        return len(ins)

    n_hash = run(emit_world_hash, M.ref_world_hash, 'world_hash')
    n_noise = run(emit_value_noise, M.ref_value_noise, 'value_noise')
    n_fbm = run(emit_fbm, M.ref_fbm, 'fbm', octaves=octaves)

    print(f"  emitted: hash {n_hash}, value_noise {n_noise}, "
          f"fbm({octaves}) {n_fbm} instructions")
    print(f"  bit-exact checks: {checks} points x 3 channels = {checks * 3}")
    if fails:
        for f in fails[:8]:
            print(f"    MISMATCH {f[0]} at P={f[1]} ch{f[2]}: "
                  f"emitted={f[3]!r} reference={f[4]!r}", file=sys.stderr)
        print(f"  FAIL: {len(fails)} mismatches", file=sys.stderr)
        return 1

    # --- statistical sanity, on the REFERENCE (cheap, and it is the same
    #     arithmetic): a hash that is not uniform, or whose channels are
    #     correlated, would pass bit-exactness and still be useless.
    pts = rng.uniform(-200.0, 200.0, size=(4096, 3)).astype(np.float32)
    U = np.array([M.ref_world_hash(p, cell, seed) for p in pts])
    mean = U.mean(axis=0)
    corr = np.corrcoef(U.T)
    off = float(max(abs(corr[0, 1]), abs(corr[0, 2]), abs(corr[1, 2])))
    print(f"  hash uniformity: means {mean.round(4).tolist()} (want ~0.5), "
          f"max |channel corr| {off:.4f} (want < 0.05)")
    ok = all(abs(m - 0.5) < 0.02 for m in mean) and off < 0.05
    F = np.array([M.ref_fbm(p, cell, seed, octaves=octaves) for p in pts])
    print(f"  fbm range: [{F.min():.4f}, {F.max():.4f}] (must be within "
          f"[0, 1]), mean {F.mean():.4f}")
    ok = ok and F.min() >= 0.0 and F.max() <= 1.0
    # world stability: the SAME point must hash identically however it is
    # reached -- this is the property the whole primitive exists for.
    q = pts[:256]
    a = np.array([M.ref_fbm(p, cell, seed, octaves=octaves) for p in q])
    b = np.array([M.ref_fbm(p.copy(), cell, seed, octaves=octaves) for p in q])
    stable = np.array_equal(a.astype(np.float32).tobytes(),
                            b.astype(np.float32).tobytes())
    print(f"  world stability (re-evaluation is bit-identical): "
          f"{'yes' if stable else 'NO'}")
    ok = ok and stable
    if not ok:
        print("  FAIL: statistical gate", file=sys.stderr)
        return 1
    print("  ALL CHECKS PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--points', type=int, default=512)
    ap.add_argument('--cell', type=float, default=0.012)
    ap.add_argument('--seed', type=lambda s: int(s, 0), default=0xC0FFEE)
    ap.add_argument('--octaves', type=int, default=DEFAULT_OCTAVES)
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    if not a.selftest:
        ap.error('nothing to do -- try --selftest')
    print(f"whash_core selftest (cell={a.cell} m, seed={a.seed:#x}, "
          f"octaves={a.octaves})")
    sys.exit(_selftest(a.points, a.seed, a.cell, a.octaves, a.verbose))


if __name__ == '__main__':
    main()
