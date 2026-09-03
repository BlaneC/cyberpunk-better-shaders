#!/usr/bin/env python3
"""The car-paint GLINT model of `94` sec 4.4, written ONCE in numpy float32 and
uint32, so that the patcher, the verifier, the driver probe and the closed-form
check all speak about the same arithmetic instead of three paraphrases of it.

handoff/100-GLINTS.md is the document. `94` sec 4.4 is the design; `98` sec 15
is the proof that the world offset this depends on is real; `99` sec 10.8 is the
measurement that the world unit is the metre and the up axis is Z.

WHAT sec 4.4 SPECIFIES

    P_w  = hit + cbv[..][56].xyz                     ; world, frame-stable
    r    = pix_angle * (t_primary + t_segment)       ; footprint radius, metres
    s    = cell * exp2(ceil(log2(max(1, r/cell))))   ; dyadic LOD ladder
    ci   = floor(P_w / s)                            ; 3 ints
    di   = floor(H * q),  q = 1/theta_bin            ; world-frame angular bin
    u    = pcg_mix(ci, di) * 2^-32                   ; in [0,1)
    nu   = nu0 * D * omega_bin * s*s
    p    = min(nu, 1)
    pc   = max(p, 1/glint_max)                       ; the firefly clamp
    g    = (u < pc) ? 1/pc : 0                       ; E[g] = 1, g <= glint_max
    glint = mix(1, g, k_glint * w_fade)

WHAT THIS FILE ADDS, and why -- every one of these is a DEVIATION and is
recorded in handoff/100 sec 3 with its consequence:

  * `omega_bin` and `nu0` are FOLDED at build time into one constant NU0 =
    nu0*omega_bin, because both are build knobs and their product is the only
    thing the shader needs. No behaviour changes; the instruction count drops
    by one per arm.
  * `pix_angle` is a BUILD CONSTANT. Nothing at the splice site carries the
    projection; deriving it would be a second hunt (`98` sec 14.6a's discipline
    says a constant guessed from an index is worse than one stated).
  * The gate is `94` sec 17.2's RAMP, not sec 4.1's boolean, and the ramp
    weight multiplies into the mix weight: kw = k_glint * w_gate * w_fade.
    `glint = mix(1, g, kw)` has E[glint] = 1 for ANY kw, so this is still
    energy-neutral in expectation and is EXACTLY 1.0 when kw = 0.
  * Three NClamp totality guards (on the LOD ratio, on P_w/s and on H*q) so
    that no OpConvertFToS can ever see a NaN or an out-of-int32 value.
    SPIR-V leaves that conversion UNDEFINED, and "undefined" in a shipped
    shader is a crash waiting for a denormal normal.
  * `pcg_mix` is named but not specified by sec 4.4. It is fixed here as
    three odd multiplies + XOR per triple, the two triples XORed, and the
    32-bit PCG RXS-M-XS finaliser.
"""
import numpy as np

f32 = np.float32
u32 = np.uint32

# ---------------------------------------------------------------- constants
# Odd 32-bit multipliers, one per axis. Distinct per axis so a hash that
# correlated along an axis (visible stripes on a car door, `94` sec 6.2 row 6)
# cannot arise from two axes sharing a multiplier.
C_CELL = (u32(0x9E3779B1), u32(0x85EBCA77), u32(0xC2B2AE3D))
C_BIN  = (u32(0x27D4EB2F), u32(0x165667B1), u32(0x1B873593))
# PCG RXS-M-XS, 32 bit. A bijection, so distinct (cell, bin) pairs that survive
# the XOR fold stay distinct.
PCG_MUL   = u32(747796405)
PCG_INC   = u32(2891336453)
PCG_XMUL  = u32(277803737)
TWO_M32   = f32(2.0 ** -32)

# Totality guards (see the module docstring).
RATIO_MAX = f32(65536.0)     # s <= cell * 65536
CELL_MAX  = f32(1.0e9)       # |P_w / s| clamp before floor
BIN_MAX   = f32(1024.0)      # |H * q|   clamp before floor

DEFAULTS = dict(
    cell=0.008,          # 8 mm -- 94 sec 4.4: above the 720p footprint at
                         # conversational distance, so flakes survive the resolve
    pix_angle=1.2e-3,    # rad/px: vfov 0.88 rad (FOV 80 horizontal at 16:9)
                         # over ~740 internal rows (1440p, DLSS Balanced)
    nu0=1.5e5,           # flakes per m^2
    theta_bin=0.02,      # rad -- finer than the lobe it sits in
    glint_max=16.0,      # 94 sec 4.4's shipping default
    k_glint=1.0,
    m_lo=0.55, m_hi=0.70,   # 94 sec 17.3's recommended ramp
    r_max=0.35,             # 94 sec 12.3's "m >= 0.5 and r < 0.35"
    fade_end=40.0, fade_span=10.0,
)


def knobs(**over):
    k = dict(DEFAULTS)
    bad = set(over) - set(DEFAULTS)
    if bad:
        raise SystemExit('glint_model: unknown knob(s): ' + ', '.join(sorted(bad)))
    k.update({a: float(b) for a, b in over.items()})
    return k


def constants(k):
    """The float32 constants the patcher bakes. One place, so the verifier can
    re-derive them from the knobs and compare against the shipped bytes."""
    if k['cell'] <= 0 or k['glint_max'] < 1.0 or k['theta_bin'] <= 0:
        raise SystemExit('glint_model: cell>0, theta_bin>0, glint_max>=1 required')
    if not (k['m_hi'] > k['m_lo']):
        raise SystemExit('glint_model: m_hi must exceed m_lo')
    if k['fade_span'] <= 0:
        raise SystemExit('glint_model: fade_span must be > 0')
    return dict(
        CELL=f32(k['cell']),
        INV_CELL=f32(1.0 / f32(k['cell'])),
        PIX=f32(k['pix_angle']),
        # nu0 * omega_bin, folded (omega_bin = theta_bin^2)
        NU0=f32(f32(k['nu0']) * f32(f32(k['theta_bin']) * f32(k['theta_bin']))),
        QBIN=f32(1.0 / f32(k['theta_bin'])),
        INV_GMAX=f32(1.0 / f32(k['glint_max'])),
        K=f32(k['k_glint']),
        M_LO=f32(k['m_lo']),
        INV_M_SPAN=f32(1.0 / f32(f32(k['m_hi']) - f32(k['m_lo']))),
        R_MAX=f32(k['r_max']),
        FADE_END=f32(k['fade_end']),
        INV_FADE_SPAN=f32(1.0 / f32(k['fade_span'])),
        RATIO_MAX=RATIO_MAX, CELL_MAX=CELL_MAX, BIN_MAX=BIN_MAX,
        TWO_M32=TWO_M32,
    )


# ------------------------------------------------------------------ helpers
def _nmax(a, b):
    """GLSL.std.450 NMax: returns the other operand when one is NaN."""
    a, b = f32(a), f32(b)
    return np.where(np.isnan(a), b, np.where(np.isnan(b), a, np.maximum(a, b))).astype(np.float32)


def _nmin(a, b):
    a, b = f32(a), f32(b)
    return np.where(np.isnan(a), b, np.where(np.isnan(b), a, np.minimum(a, b))).astype(np.float32)


def _nclamp(x, lo, hi):
    return _nmin(_nmax(x, lo), hi)


def pcg(v):
    """PCG RXS-M-XS, 32 bit -- the finaliser the splice emits."""
    v = np.asarray(v, dtype=np.uint32)
    with np.errstate(over='ignore'):
        state = (v * PCG_MUL + PCG_INC).astype(np.uint32)
        sh = ((state >> u32(28)) + u32(4)).astype(np.uint32)
        word = (((state >> sh) ^ state) * PCG_XMUL).astype(np.uint32)
        return ((word >> u32(22)) ^ word).astype(np.uint32)


def _fold(v3, mult):
    with np.errstate(over='ignore'):
        return ((v3[0] * mult[0]) ^ (v3[1] * mult[1]) ^ (v3[2] * mult[2])).astype(np.uint32)


def _to_int(x):
    """OpConvertFToS on a value already clamped into int32 range."""
    return np.asarray(x, dtype=np.float64).astype(np.int32).astype(np.uint32)


# ------------------------------------------------------------- the module part
def module_level(C, P, t_prim, t_seg, metallic, rough):
    """Everything the splice computes ONCE per invocation.

    P is the CAMERA-RELATIVE hit position ALREADY offset by cbv[..][56].xyz --
    i.e. P_w. The add itself is three OpFAdd in the shader and is not modelled
    here, because the offset is a uniform this model cannot see; `98` sec 15 is
    what makes the add correct and dev/verify_carglint.py is what asserts the
    shipped bytes really add THAT member.
    """
    P = np.asarray(P, dtype=np.float32)
    t_prim, t_seg = f32(t_prim), f32(t_seg)
    dist = f32(t_prim + t_seg)
    r_fp = f32(dist * C['PIX'])
    ratio = f32(r_fp * C['INV_CELL'])
    m1 = _nclamp(ratio, f32(1.0), C['RATIO_MAX'])
    s = f32(C['CELL'] * f32(np.exp2(np.ceil(np.log2(m1.astype(np.float64))).astype(np.float32))))
    s2 = f32(s * s)
    kden = f32(C['NU0'] * s2)

    q = [f32(P[i] / s) for i in range(3)]
    qc = [_nclamp(q[i], -C['CELL_MAX'], C['CELL_MAX']) for i in range(3)]
    ci = [_to_int(np.floor(qc[i].astype(np.float64)).astype(np.float32)) for i in range(3)]
    hc = _fold(ci, C_CELL)

    # gate: 94 sec 17.2's ramp on metallic, hard on roughness
    mt = _nclamp(f32(f32(f32(metallic) - C['M_LO']) * C['INV_M_SPAN']), f32(0.0), f32(1.0))
    sm = f32(f32(mt * mt) * f32(f32(mt * f32(-2.0)) + f32(3.0)))
    w = np.where(np.asarray(rough, dtype=np.float32) < C['R_MAX'], sm, f32(0.0)).astype(np.float32)
    wf = _nclamp(f32(f32(C['FADE_END'] - dist) * C['INV_FADE_SPAN']), f32(0.0), f32(1.0))
    kw = f32(C['K'] * f32(w * wf))
    return dict(dist=dist, s=s, s2=s2, kden=kden, cell=ci, hc=hc,
                w_gate=w, w_fade=wf, kw=kw)


def per_arm(C, ml, H, D):
    """Everything the splice computes once per GGX arm."""
    H = np.asarray(H, dtype=np.float32)
    b = [_nclamp(f32(H[i] * C['QBIN']), -C['BIN_MAX'], C['BIN_MAX']) for i in range(3)]
    di = [_to_int(np.floor(b[i].astype(np.float64)).astype(np.float32)) for i in range(3)]
    hb = _fold(di, C_BIN)
    out = pcg((ml['hc'] ^ hb).astype(np.uint32))
    u = f32(out.astype(np.float32) * C['TWO_M32'])

    nu = f32(ml['kden'] * f32(D))
    p = _nmin(nu, f32(1.0))
    pc = _nmax(p, C['INV_GMAX'])
    rec = f32(f32(1.0) / pc)
    g = np.where(u < pc, rec, f32(0.0)).astype(np.float32)
    glint = f32(f32(ml['kw'] * f32(g - f32(1.0))) + f32(1.0))
    return dict(u=u, nu=nu, p=p, pc=pc, g=g, glint=glint, bin=di)


def glint(C, P, H, D, t_prim, t_seg, metallic, rough):
    """The whole thing, for a batch of samples."""
    ml = module_level(C, P, t_prim, t_seg, metallic, rough)
    pa = per_arm(C, ml, H, D)
    pa.update(ml)
    return pa
