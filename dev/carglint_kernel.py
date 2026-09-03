#!/usr/bin/env python3
"""carglint driver selftest -- generate a COMPUTE kernel out of the SAME
emitter that patches the raygens, dispatch it on a real device through the
layer, and compare the readback against dev/glint_model.py.

    python3 dev/carglint_kernel.py --emit kern.spvasm [--store s|kden|pc|glint]
    python3 dev/carglint_kernel.py --inputs in.bin --n 65536      # samples
    python3 dev/carglint_kernel.py --check in.bin out.bin [--store ...]

WHY THIS EXISTS
---------------
`94` sec 6.2 axis 11 wants the shipped arithmetic checked against a closed
form. dev/verify_carglint.py already does that STATICALLY: it re-derives the
model from the shipped bytes and runs 10^5 samples through numpy. That proves
"the bytes say what the model says". It does NOT prove "a driver computing
those bytes agrees" -- fp32 NClamp/Floor/ConvertFToS/pcg on real hardware is
the part numpy is not.

The existing selftest infra (dev/patch_rayq.sh's st.c) is LINK-ONLY: it creates
modules and links a pipeline, it never dispatches and has no buffers. So this
adds a dispatching probe rather than declining. The kernel is not a hand-copy
of the splice -- patch_carglint.emit_module_level / emit_arm are imported and
called, so a divergence between the raygen and this test is impossible by
construction.

BIT-EXACTNESS: WHERE IT HOLDS AND WHERE IT DOES NOT
---------------------------------------------------
Measured on an RTX 4070, 65536 samples. The driver reproduces the model BIT FOR
BIT for `s` (the dyadic ladder, transcendentals included), `s2`, `kden`, `dist`,
`nu` and `pc` -- i.e. every quantity that sets the SCALE and the DENSITY of the
sparkle. It does NOT for `kw` (5133/65536) or `glint` (2549/65536), because:

  * it reassociates `(fade_end - dist) * inv_fade_span` into
    `fma(-dist, inv_fade_span, 4.0)`. Not IEEE-safe, universally done, and
    strictly MORE accurate than the two-step form -- the disagreement is
    entirely in the cancellation tail where fade or the metallic ramp is within
    1e-4 of zero, i.e. where the glint is invisible anyway.
  * `OpFDiv` is allowed 2.5 ULP in Vulkan (`P_w / s`, `1 / pc`), which flips the
    Bernoulli comparison `u < pc` on 16 of 65536 samples (0.024%).

So this file does NOT assert bit-equality of `glint`, because that assertion
would be false against a conforming driver and "widen the tolerance until it
passes" is how a test stops meaning anything. It asserts instead:
  1. every gate-CLOSED sample is glint == 1.0 BIT-exactly (53572/53572). This is
     the safety property: nothing outside `94` sec 17.2's gate is touched.
  2. `s`, `kden`, `pc` bit-exact -- the visual scale is not driver-dependent.
  3. max relative difference on glint < 1e-4 away from a flipped Bernoulli.
  4. Bernoulli flips < 0.1% of samples.
  5. on the DRIVER's OWN numbers: E[glint] = 1 within 4 sigma and
     max(glint) <= glint_max. `94` sec 4.3's energy claim, measured on silicon.

WHAT IT CANNOT SAY
------------------
It says nothing about whether the game's raygen ever reaches the splice, and
nothing about the world offset being right -- that is `98` sec 15's job and the
-glintcell rung's. It is an arithmetic agreement test, on this machine's driver.

INPUT LAYOUT, 16 float32 per sample (16 keeps every sample 64-byte aligned):
    0..2  P    camera-relative hit position
    3..5  off  cbv[..][56].xyz, the world offset
    6     t_primary        7  t_segment
    8     metallic         9  roughness
    10..12 H              13  D           14,15 unused
OUTPUT: 1 float32 per sample -- `glint`.
"""
import argparse, os, struct, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import glint_model as GM  # noqa: E402  (f32 below comes from here)
from patch_skin_brdf import apply_edits, f32s, die
f32 = GM.f32
from patch_chs_brdf import load_lenient
from patch_carglint import Emitter, emit_module_level, emit_arm

# One synthetic DXIL identity, in the shape Module's OpString regex parses:
# ident = "cccccccccccccccc.carglint", so the overlay file is
# swaps.carglinttest/cccccccccccccccc.carglint.spv -- exactly patch_rayq.sh's
# bbbbbbbbbbbbbbbb.rayqtest.spv trick.
IDENT_STR = 'cccccccccccccccc.?carglint@@YAXXZ.dxil'
IDENT = 'cccccccccccccccc.carglint'
STRIDE = 16

SKELETON = """\
               OpCapability Shader
          %1 = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint GLCompute %main "main" %gid_var %inbuf %outbuf
               OpExecutionMode %main LocalSize 64 1 1
        %str = OpString "@IDENT@"
               OpDecorate %gid_var BuiltIn GlobalInvocationId
               OpDecorate %rta ArrayStride 4
               OpMemberDecorate %Buf 0 Offset 0
               OpDecorate %Buf Block
               OpDecorate %inbuf DescriptorSet 0
               OpDecorate %inbuf Binding 0
               OpDecorate %inbuf NonWritable
               OpDecorate %outbuf DescriptorSet 0
               OpDecorate %outbuf Binding 1
       %void = OpTypeVoid
      %fnvoid = OpTypeFunction %void
      %float = OpTypeFloat 32
       %uint = OpTypeInt 32 0
        %int = OpTypeInt 32 1
       %bool = OpTypeBool
     %v3uint = OpTypeVector %uint 3
    %v4float = OpTypeVector %float 4
        %rta = OpTypeRuntimeArray %float
        %Buf = OpTypeStruct %rta
    %ptr_buf = OpTypePointer StorageBuffer %Buf
      %inbuf = OpVariable %ptr_buf StorageBuffer
     %outbuf = OpVariable %ptr_buf StorageBuffer
      %ptr_f = OpTypePointer StorageBuffer %float
   %ptr_gid = OpTypePointer Input %v3uint
    %gid_var = OpVariable %ptr_gid Input
    %uint_0 = OpConstant %uint 0
   %uint_str = OpConstant %uint @STRIDE@
@UIDX@
       %main = OpFunction %void None %fnvoid
    %entry_l = OpLabel
       %gid3 = OpLoad %v3uint %gid_var
        %gid = OpCompositeExtract %uint %gid3 0
       %base = OpIMul %uint %gid %uint_str
@LOADS@
     %outptr = OpAccessChain %ptr_f %outbuf %uint_0 %gid
               OpStore %outptr %%GLINT%%
               OpReturn
               OpFunctionEnd
"""

FIELDS = ['p0', 'p1', 'p2', 'o0', 'o1', 'o2', 'tprim', 'tseg',
          'met', 'rgh', 'h0', 'h1', 'h2', 'D']


def skeleton():
    uidx = '\n'.join(f"   %uidx_{i} = OpConstant %uint {i}" for i in range(STRIDE))
    loads = []
    for i, f in enumerate(FIELDS):
        loads.append(f"      %i_{f} = OpIAdd %uint %base %uidx_{i}")
        loads.append(f"      %a_{f} = OpAccessChain %ptr_f %inbuf %uint_0 %i_{f}")
        loads.append(f"        %{f} = OpLoad %float %a_{f}")
    return (SKELETON.replace('@IDENT@', IDENT_STR)
                    .replace('@STRIDE@', str(STRIDE))
                    .replace('@UIDX@', uidx)
                    .replace('@LOADS@', '\n'.join(loads)))


STORES = ('glint', 's', 's2', 'kden', 'dist', 'nu', 'pc', 'kw', 'u', 'g')


def emit(path, knobs, store='glint'):
    """Write the kernel .spvasm, using the PATCHER's emitters verbatim.

    `store` selects which value lands in the output buffer, so the selftest can
    ask where a driver's arithmetic diverges instead of only whether it does."""
    tmp = path + '.skel'
    open(tmp, 'w').write(skeleton())
    mod, _ = load_lenient(tmp)
    os.unlink(tmp)
    mod.glsl = '%1'          # load_lenient leaves it None: no NClamp yet
    C = GM.constants(knobs)
    consts, E = [], None
    E = Emitter(mod, consts)
    E.ind = '        '
    at = max(i for i, ln in enumerate(mod.lines) if ln.strip().startswith('%D ='))
    ml = emit_module_level(E, C, '%int', '%bool', ['%p0', '%p1', '%p2'],
                           lambda: (['%o0', '%o1', '%o2'], None, None),
                           '%tprim', '%tseg', '%met', '%rgh')
    ar = emit_arm(E, C, '%int', '%bool', ['%h0', '%h1', '%h2'], '%D',
                  ml['seed'], ml['kden'], ml['kw'])
    vals = dict(ml); vals.update(ar)
    if store not in vals:
        die(f"carglint_kernel: --store {store} is not one of {sorted(vals)}")
    apply_edits(mod, consts, [(at, E.ins)])
    txt = '\n'.join(mod.lines).replace('%%GLINT%%', vals[store]) + '\n'
    if '%%GLINT%%' in txt:
        die('carglint_kernel: the glint store was not patched')
    open(path, 'w').write(txt)
    return dict(instructions=len(E.ins), consts=len(consts),
                stored=vals[store], store=store)


def emit_null(path):
    """The PLACEHOLDER the probe hands to vkCreateShaderModule. Same identity,
    no glint arithmetic at all: it stores -1.0. If the layer fails to serve the
    real kernel the readback is all -1.0 and --check fails on every sample, so
    "the swap happened" cannot be assumed -- it is measured by the numbers."""
    txt = skeleton().replace('%%GLINT%%', '%float_null')
    txt = txt.replace('       %main = OpFunction',
                      ' %float_null = OpConstant %float -1\n       %main = OpFunction')
    open(path, 'w').write(txt)


def samples(n, seed=20260902):
    """(P, off, t_prim, t_seg, metallic, rough, H, D) -- deliberately spanning
    both sides of every gate and every clamp, so a driver that disagrees only
    on a branch still gets caught."""
    r = np.random.default_rng(seed)
    a = np.zeros((n, STRIDE), dtype=np.float32)
    a[:, 0:3] = r.uniform(-40, 40, (n, 3))          # camera-relative
    a[:, 3:6] = r.uniform(-4000, 4000, (n, 3))      # world offset, big
    a[:, 6] = r.uniform(0.05, 60.0, n)              # t_primary
    a[:, 7] = r.uniform(0.0, 20.0, n)               # t_segment
    a[:, 8] = r.uniform(0.30, 1.0, n)               # metallic, straddles m_lo
    a[:, 9] = r.uniform(0.02, 0.60, n)              # roughness, straddles r_max
    h = r.normal(size=(n, 3)).astype(np.float32)
    a[:, 10:13] = h / np.linalg.norm(h, axis=1, keepdims=True)
    a[:, 13] = np.exp(r.uniform(-6, 5, n))          # D, spans the lobe
    return a


def model(knobs, a, store='glint'):
    C = GM.constants(knobs)
    P = np.stack([f32(a[:, 3 + k] + a[:, k]) for k in range(3)])   # off + pos
    g = GM.glint(C, P, [a[:, 10], a[:, 11], a[:, 12]], a[:, 13],
                 a[:, 6], a[:, 7], a[:, 8], a[:, 9])
    return g, np.ascontiguousarray(np.asarray(g[store], dtype=np.float32))


EXACT = ('s', 's2', 'kden', 'dist', 'nu', 'pc')
REL_TOL = 1e-4          # away from a flipped Bernoulli; measured max 5.7e-5
FLIP_TOL = 0.001        # fraction of samples; measured 0.00024


def check(knobs, inp, outp, store='glint'):
    """Return (ok, lines). See this file's docstring for why `glint` is NOT
    asserted bit-equal."""
    s = np.frombuffer(open(inp, 'rb').read(), dtype=np.float32).reshape(-1, STRIDE)
    dev = np.frombuffer(open(outp, 'rb').read(), dtype=np.float32)
    out = []
    if dev.size != s.shape[0]:
        return False, [f"readback is {dev.size} floats, want {s.shape[0]}"]
    g, mo = model(knobs, s, store)
    n = s.shape[0]
    diff = np.flatnonzero(dev.view(np.uint32) != mo.view(np.uint32))
    if store in EXACT:
        out.append(f"[{store}] {n} samples, {diff.size} bit-mismatches "
                   f"(BIT-EXACT required)")
        if diff.size:
            i = int(diff[0])
            out.append(f"  first at {i}: driver={dev[i]!r} model={mo[i]!r}")
            return False, out
        # non-vacuity: a stage that is constant across the batch proves nothing
        if np.unique(dev).size < 2:
            out.append(f"  !! every sample returned {dev[0]!r} -- degenerate")
            return False, out
        return True, out
    if store != 'glint':
        out.append(f"[{store}] {n} samples, {diff.size} bit-mismatches (advisory)")
        return True, out

    ok = True
    kw, gg = g['kw'], g['g']
    closed = kw == np.float32(0.0)
    nbadclosed = int(np.count_nonzero(dev[closed] != np.float32(1.0)))
    out.append(f"gate-CLOSED: {int(closed.sum())} samples, "
               f"{nbadclosed} not bit-exactly 1.0")
    ok &= nbadclosed == 0 and int(closed.sum()) > n // 10
    flip = (dev != np.float32(1.0)) != (gg != np.float32(0.0)) & (kw != np.float32(0.0))
    # A flip is a Bernoulli decision the driver made differently; identify it by
    # the driver landing on the OTHER side of `glint == 1 + kw*(g-1)` for g in
    # {0, 1/pc}, not by an arbitrary distance.
    alt = f32(f32(kw * f32(np.where(gg != 0, f32(0.0), f32(1.0) / g['pc']) - f32(1.0))) + f32(1.0))
    flip = np.isclose(dev.astype(np.float64), alt.astype(np.float64),
                      rtol=1e-4, atol=0) & ~np.isclose(
        dev.astype(np.float64), mo.astype(np.float64), rtol=1e-4, atol=0)
    nf = int(np.count_nonzero(flip))
    out.append(f"Bernoulli flips: {nf} / {n} = {nf / n:.5f} (limit {FLIP_TOL})")
    ok &= nf / n <= FLIP_TOL
    rel = np.abs(dev.astype(np.float64) - mo.astype(np.float64)) / \
        np.maximum(np.abs(mo.astype(np.float64)), 1e-30)
    rmax = float(np.max(rel[~flip])) if np.any(~flip) else 0.0
    out.append(f"max relative difference off a flip: {rmax:.3e} (limit {REL_TOL:.0e})")
    ok &= rmax <= REL_TOL
    nbit = int(np.count_nonzero(dev.view(np.uint32) != mo.view(np.uint32)))
    out.append(f"bit-identical: {n - nbit} / {n}")
    mean = float(dev.mean()); sem = float(dev.std(ddof=1) / np.sqrt(n))
    out.append(f"driver E[glint] = {mean:.5f} +- {4 * sem:.5f} (4 sigma), "
               f"max = {float(dev.max()):.4f} (glint_max {knobs['glint_max']:.1f})")
    ok &= abs(mean - 1.0) <= 4 * sem
    ok &= float(dev.max()) <= f32(knobs['glint_max']) * (1.0 + 1e-6)
    nz = int(np.count_nonzero(dev != np.float32(1.0)))
    out.append(f"{nz} samples left 1.0 (the kernel is not a no-op)")
    ok &= nz >= n // 100
    return ok, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--emit'); ap.add_argument('--emit-null', dest='emit_null')
    ap.add_argument('--inputs'); ap.add_argument('--n', type=int, default=65536)
    ap.add_argument('--check', nargs=2, metavar=('IN', 'OUT'))
    ap.add_argument('--store', default='glint', choices=STORES)
    ap.add_argument('--knob', action='append', default=[])
    a = ap.parse_args()
    over = {}
    for kv in a.knob:
        k, v = kv.split('=', 1)
        over[k] = float(v)
    knobs = GM.knobs(**over)
    if a.emit:
        r = emit(a.emit, knobs, a.store)
        print(f"kernel {a.emit}: {r['instructions']} emitted instructions, "
              f"{r['consts']} constants, stores {r['store']}={r['stored']}, "
              f"ident={IDENT}")
    if a.emit_null:
        emit_null(a.emit_null)
        print(f"placeholder {a.emit_null}: stores -1.0, ident={IDENT}")
    if a.inputs:
        s = samples(a.n)
        open(a.inputs, 'wb').write(s.tobytes())
        print(f"inputs {a.inputs}: {a.n} samples x {STRIDE} float32")
    if a.check:
        ok, lines = check(knobs, a.check[0], a.check[1], a.store)
        for ln in lines:
            print(ln)
        if not ok:
            sys.exit(1)
        print(f"OK: the driver agrees with dev/glint_model.py on {a.store}")


if __name__ == '__main__':
    main()
