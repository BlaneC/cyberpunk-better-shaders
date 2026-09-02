#!/usr/bin/env python3
"""Participating media on the SUN SHADOW RAY: analytic Beer-Lambert on the
direct-sun term of the reference path tracer.  handoff/95.

WHAT IT DOES, one paragraph
---------------------------
The engine's direct sun term is `FMul(BRDF, sunRadiance_c)`, three of them,
one per channel, inside the region its own NEE ray reached only when the pixel
was LIT.  This multiplies that RESULT by a per-channel transmittance
`T_c <= 1` computed in closed form from the shading point's WORLD HEIGHT and
the SUN ELEVATION, for an exponential height-fog density.  No rays, no PRNG
draw, no branch: ~28 instructions of arithmetic per module.

THE MATHS, and the one decision that keeps it honest (95 sec 3)
---------------------------------------------------------------
    rho(s) = d0 * exp(-(h + s*L_u - y0)/H)          along P + s*L
    tau_abs = d0*H/L_u * exp(-(h-y0)/H)             (the sun ray's tmax is
                                                     10000, i.e. unbounded,
                                                     so the integral is exact)
Shipping tau_abs DOUBLE-COUNTS: the engine's sun radiance is already authored
to look right under an atmosphere the artist implied, and an absolute vertical
optical depth of 0.4 dims NOON by a third -- which reads as "the mod turned
the sun down", not as fog.  So what is emitted is the AIRMASS EXCESS over
zenith, i.e. the slant column MINUS the zenith column the engine already baked
in:

    col   = exp(-(h - y0)/H)                        normalised column at h
    lu    = max(L_u, LU_MIN)                        LU_MIN = 0.02 (~1.15 deg)
    am    = max(1/lu - 1, 0)                        >= 0, and == 0 at zenith
    tau_c = min(A_c * col * am, TAU_MAX)
    T_c   = exp(-tau_c)                             == 1.0 EXACTLY at zenith
    site_c := site_c * T_c

`A = d0*H*exp(y0/H)` -- d0 and y0 are NOT independent; for a fixed build they
collapse into one constant.  A wrong y0 is therefore a pure SCALE error on A
and cannot change the street-to-rooftop gradient, which is set by H alone.

Per-channel sigma: `A_c = A * (550/lambda_c)^p`, lambda = 610/550/465 nm.
p=1 (Mie-ish urban haze) is the ship default; p=0 is neutral; p=4 is Rayleigh
and is a deliberately-too-much diagnostic.  Every T_c <= 1, so handoff/53's
multiplicative-only constraint holds by construction: nothing is ever
brightened, and the blue that is removed is NOT re-added anywhere (that would
be in-scattering, which this splice cannot do -- 95 sec 0).

WHY THE SITE IS THE FMul RESULT, NOT ITS OPERAND
------------------------------------------------
85/88 rewrote the FMul's BRDF operand.  This multiplies the RESULT and
`replace_all_uses` it, for two reasons.  (a) It COMPOSES: the standing rung
`...-cone2all` has already rewritten that operand to the cavity's `%new`, so
find_sun_sites' `NClamp` assertion would die on the patched base; a downstream
multiply needs no change to the inherited shape.  (b) GOTCHAS "scale before a
clamp, never after" is satisfied trivially -- T is in [0,1], so the edit can
only REDUCE an already-bounded value and no fp16 store can be pushed to inf.
The radiance component's exactly-3-uses assertion also means the sun's own
"is the radiance non-zero" branch test is untouched: T -> 0 dims the term but
does not flip a branch, so divergence and the LCG chain stay bit-identical.

WHY THE ORIGIN IS THE NEE TRACE'S OWN, NOT 85/88's `prehit`
-----------------------------------------------------------
`prehit` is the PRIMARY hit, harvested because 85/88 fight a millimetre-scale
raster-depth error that exists only there.  This term runs at EVERY bounce, so
at bounce >= 1 `prehit` is the wrong point entirely.  The trace's own origin
operand is the current bounce's point; it carries the engine's self-hit offset
of at most 0.1 m along N, nine orders below a ~120 m scale height.

WHY IT IS UNGATED ON BOUNCE -- the OPPOSITE of 88 (95 sec 6)
-------------------------------------------------------------
88 gates on `path_counter == 0` because its term is a CORRECTION to a
primary-hit-only artefact (the raster-depth re-find plus the engine's own mm
origin lift); at bounce >= 1 the point comes from a real traced intersection
and the cheat would darken geometry the path tracer already resolved, and it
COMPOUNDS -- 90 sec 1 measured exactly that.  Beer-Lambert is not a cheat: T
at bounce k is the true transmittance of that bounce's own shadow ray, and the
product over a path is what the physical path integral computes.  Gating at
bounce 0 would systematically OVER-estimate indirect sunlight, and the error
would grow with depth.  Both counters are still located every build so the
report can prove, positively, that neither is referenced.

IDENTITY WHEN DEAD
------------------
`--a 0` emits NOTHING (every detector still runs): the byte-identity control.
With A > 0 the term is still exactly 1.0 at zenith sun (am == 0 => tau == 0 =>
Exp2(-0) == 1.0), and T <= 1 is provable from the emitted constants because
A2_c > 0, col > 0, am >= 0 and the Exp2 argument is an FNegate of a
non-negative NMin.  No division by zero: the only FDiv's denominator is
NMax(L_u, LU_MIN) >= 0.02.  No unbounded exponent: the Exp2 argument of `col`
passes through NClamp(+-EXP_LIM) and tau through NMin(TAU_MAX).

  ./dev/patch_volsun.py <in.spvasm> --a 0.25 --h 120 --y0 20 --p 1 \
      --up 2 --height abs --outdir DIR
"""
import argparse, hashlib, json, math, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
import patch_cavity2 as C2
import cfg_dom
from patch_skin_brdf import apply_edits, roundtrip_check, replace_all_uses, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

LU_MIN = 0.02        # ~1.15 deg of sun elevation; the FDiv denominator floor
TAU_MAX = 30.0       # T >= 9.4e-14; keeps Exp2 bounded with no branch
EXP_LIM = 40.0       # clamp on the column exponent, both signs
LOG2E = 1.4426950408889634
LAMBDA = (610.0, 550.0, 465.0)     # nm, R/G/B; green is the reference
CBV_SLOT = 56        # the camera world position (95 sec 1b)
OFF_SLOT = 77        # the engine's own self-hit offset scales; the cbv anchor
SEARCH = 600         # lines to scan forward for the sun branch (88's cone
                     # inserts ~101 instructions between the NEE trace and the
                     # OpSelectionMerge, so patch_cavity's 24-line window is
                     # far too narrow on a composed base)


def _def(mod, idt, pat):
    _, d = mod.find_def(idt)
    return re.match(pat + r'\s*$', d or '')


def _comm2(mod, idt, pat, pick):
    """FMul/FAdd operand order is not guaranteed; return (matching, other)."""
    m = _def(mod, idt, pat)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    if pick(a):
        return a, b
    if pick(b):
        return b, a
    return None


# --------------------------------------------------------------- detectors
def find_sun_branch(mod, nee, fs, fe):
    """The visibility branch guarding the DIRECT SUN block.

    Same hop-by-hop walk as patch_cavity.find_sun_branch (any deviation is a
    finding, not a guess -- GOTCHAS 10), but anchored on the SHAPE instead of
    a 24-line window, because on a cavity-composed base the cone's ~101
    instructions sit between the NEE trace and the OpSelectionMerge.  Exactly
    one branch within SEARCH lines may validate.
    """
    n = nee["line"]
    ok = []
    for i in range(n + 1, min(n + SEARCH, fe)):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', mod.lines[i])
        if not m:
            continue
        sm = re.match(r'\s*OpSelectionMerge (%\w+) None\s*$', mod.lines[i - 1])
        if not sm:
            continue
        r = _validate_sun_branch(mod, nee, fs, fe, i, m, sm)
        if r:
            ok.append(r)
    if len(ok) != 1:
        die(f"{mod.name}: {len(ok)} sun-visibility branches validated within "
            f"{SEARCH} lines of the NEE trace, expected exactly 1")
    return ok[0]


def _validate_sun_branch(mod, nee, fs, fe, bline, m, sm):
    cond, tlab, flab = m.group(1), m.group(2), m.group(3)
    merge = sm.group(1)
    if merge not in (tlab, flab):
        return None
    gm = _def(mod, cond, r'OpFOrdGreaterThan %bool (%\w+) %float_0')
    if not gm:
        return None
    fm = _def(mod, gm.group(1), r'OpFMul %float (%\w+) (%\w+)')
    if not fm:
        return None
    vb, dot = fm.group(1), fm.group(2)
    if not _def(mod, dot, r'OpDot %float (%\w+) (%\w+)'):
        vb, dot = dot, vb
    dm = _def(mod, dot, r'OpDot %float (%\w+) (%\w+)')
    if not dm:
        return None
    rad = None
    for c in (dm.group(1), dm.group(2)):
        cm = _def(mod, c, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
        if not cm:
            return None
        r3 = [cm.group(1), cm.group(2), cm.group(3)]
        if rad is None:
            rad = r3
        elif rad != r3:
            return None
    sm2 = _def(mod, vb, r'OpSelect %float (%\w+) %float_0 (%\w+)')
    if not sm2 or sm2.group(1) != nee["backlit"]:
        return None
    vm = _def(mod, sm2.group(2), r'OpSelect %float (%\w+) %float_1 %float_0')
    if not vm:
        return None
    em = _def(mod, vm.group(1), r'OpFOrdEqual %bool (%\w+) %float_10000')
    if not em:
        return None
    lm = _def(mod, em.group(1), r'OpLoad %float (%\w+)')
    if not lm:
        return None
    if not _def(mod, lm.group(1),
                r'OpInBoundsAccessChain %\w+ ' + re.escape(nee["ops"][10])
                + r' %uint_3'):
        return None
    if E.find_sun_radiance(mod, nee["line"]) != rad:
        die(f"{mod.name}: branch radiance {rad} is not the slot-6 extracts")
    mlab = next((i for i in range(bline, fe)
                 if re.match(r'\s*' + re.escape(merge) + r' = OpLabel',
                             mod.lines[i])), None)
    if mlab is None:
        return None
    return {"cond": cond, "sel_line": bline - 1, "merge_line": mlab, "rad": rad}


def find_sun_result_sites(mod, fs, fe, sb):
    """The three DIRECT SUN products `OpFMul(x, sunRadiance_c)` -- the RESULT.

    Inherits patch_cavity.find_sun_sites' two real guards (exactly one such
    FMul per channel; the radiance component has exactly 3 uses in the whole
    module, so multiplying here reaches the entire direct-sun term and nothing
    else -- GOTCHAS 3) and DROPS only its assertion that the other operand is
    an NClamp, because on a cavity-composed base that operand is the cavity's
    own FMul.  Which it is, is recorded rather than assumed.
    """
    sites = []
    for c, r in enumerate(sb["rad"]):
        hits = [(i, m.group(1), m.group(2))
                for i in range(fs, fe)
                for m in [re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) '
                                   + re.escape(r) + r'\s*$', mod.lines[i])]
                if m]
        if len(hits) != 1:
            die(f"{mod.name}: channel {c}: {len(hits)} FMul(x, {r}) sites, "
                f"expected exactly 1")
        line, res, src = hits[0]
        _, sd = mod.find_def(src)
        if re.match(r'OpExtInst %float %\w+ NClamp %\w+ %float_0 %float_1\s*$',
                    sd or ''):
            kind = "nclamp(base)"
        elif re.match(r'OpFMul %float %\w+ %\w+\s*$', sd or ''):
            kind = "fmul(composed)"
        else:
            die(f"{mod.name}: channel {c}: FMul source {src} is neither an "
                f"NClamp(.,0,1) nor a composed FMul: {sd!r}")
        uses = 0
        for ln in mod.lines:
            if re.match(r'\s*' + re.escape(r) + r'\s*=', ln):
                continue
            uses += len(re.findall(re.escape(r) + r'(?![0-9A-Za-z_])', ln))
        if uses != 3:
            die(f"{mod.name}: channel {c}: sun radiance {r} has {uses} uses, "
                f"expected exactly 3 (2 composites + 1 FMul)")
        if not (sb["sel_line"] < line < sb["merge_line"]):
            die(f"{mod.name}: channel {c}: site at line {line+1} is outside "
                f"the visibility selection region")
        sites.append({"line": line, "res": res, "src": src, "rad": r,
                      "src_kind": kind})
    return sites


def find_nee_geometry(mod, nee):
    """The shading point and the sun direction, from the NEE trace's OWN
    operands, plus the structural proof that the direction is already UNIT.

    The direction is asserted to be `a_i * InverseSqrt(dot(a, a))` over one
    shared reciprocal -- so no Normalize is emitted and L_u is a true cosine.
    A permutation that does not carry that shape is a finding: this dies.
    """
    om = _def(mod, nee["ops"][6],
              r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    if not om:
        die(f"{mod.name}: NEE origin operand {nee['ops'][6]} is not a "
            f"v3 CompositeConstruct")
    dm = _def(mod, nee["ops"][8],
              r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    if not dm:
        die(f"{mod.name}: NEE direction operand {nee['ops'][8]} is not a "
            f"v3 CompositeConstruct")
    org = [om.group(i) for i in (1, 2, 3)]
    dirc = [dm.group(i) for i in (1, 2, 3)]
    pre, scale = [], set()
    for i, d in enumerate(dirc):
        mm = _def(mod, d, r'OpFMul %float (%\w+) (%\w+)')
        if not mm:
            die(f"{mod.name}: NEE direction component {i} is not an FMul: "
                f"cannot prove it is unit")
        a, s = mm.group(1), mm.group(2)
        if _def(mod, a, r'OpExtInst %float %\w+ InverseSqrt (%\w+)'):
            a, s = s, a
        if not _def(mod, s, r'OpExtInst %float %\w+ InverseSqrt (%\w+)'):
            die(f"{mod.name}: NEE direction component {i} has no InverseSqrt "
                f"factor: cannot prove it is unit")
        pre.append(a)
        scale.add(s)
    if len(scale) != 1:
        die(f"{mod.name}: NEE direction components use {len(scale)} different "
            f"InverseSqrt factors, expected 1")
    isq = _def(mod, scale.pop(), r'OpExtInst %float %\w+ InverseSqrt (%\w+)')
    dd = _def(mod, isq.group(1), r'OpDot %float (%\w+) (%\w+)')
    if not dd:
        die(f"{mod.name}: the direction's InverseSqrt argument is not a dot")
    for c in (dd.group(1), dd.group(2)):
        cm = _def(mod, c, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
        if not cm or [cm.group(i) for i in (1, 2, 3)] != pre:
            die(f"{mod.name}: the direction's dot is not over its own "
                f"pre-normalised components")
    return {"origin": org, "dir": dirc, "unit_proof": "InverseSqrt(dot(v,v))"}


def find_cbv_base(mod, nee, fs, fe):
    """The constant-buffer object that carries the camera world position.

    Anchored on the engine's OWN slot-77 load (the self-hit offset scales,
    present 12/12 and already asserted by E.find_origin_offset), then
    cross-checked: the module must itself read slot CBV_SLOT off the SAME
    object, which is 88 sec 4's same-texel discipline applied to a cbv.

    The base pointer is NOT required to be in the entry block: that block is
    the tiny OpVariable prologue and the bindless chains live in the block
    after it.  Dominance over every splice is proved in build() with
    dev/cfg_dom.py instead of assumed from position (GOTCHAS "dominance is
    never assumed").
    """
    off = E.find_origin_offset(mod, nee)
    if off["slot"] != OFF_SLOT:
        die(f"{mod.name}: offset cbv slot is {off['slot']}, expected {OFF_SLOT}")
    lm = _def(mod, off["load"], r'OpLoad %v4float (%\w+)')
    cm = _def(mod, lm.group(1),
              r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_'
              + str(OFF_SLOT))
    base = cm.group(1)
    own = [i for i in range(fs, fe)
           if re.search(r'OpAccessChain %_ptr_Uniform_v4float '
                        + re.escape(base) + r' %uint_0 %uint_' + str(CBV_SLOT)
                        + r'\s*$', mod.lines[i])]
    if not own:
        die(f"{mod.name}: the module never reads slot {CBV_SLOT} off {base} "
            f"-- the camera-position anchor is not cross-checked")
    bl, _ = mod.find_def(base)
    if bl is None or not (fs < bl < fe):
        die(f"{mod.name}: cbv base {base} has no definition inside the raygen")
    return {"base": base, "line": bl, "own_slot56_lines": [i + 1 for i in own],
            "offset_slot": off["slot"]}


# ----------------------------------------------------------------- emission
def channel_scales(a, p):
    """A_c = A * (550/lambda_c)^p, green the reference."""
    return tuple(a * (LAMBDA[1] / L) ** p for L in LAMBDA)


def build(mod, a, H, y0, p, up, absolute):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()          # the memo is keyed on id(mod)
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors: ALL of them, before any edit (GOTCHAS 12) -------------
    nee = E.find_nee_trace(mod, fs, fe)
    sb = find_sun_branch(mod, nee, fs, fe)
    sites = find_sun_result_sites(mod, fs, fe, sb)
    geo = find_nee_geometry(mod, nee)
    cbv = find_cbv_base(mod, nee, fs, fe)
    # Located ONLY so the report can prove, positively, that the term is NOT
    # gated on either of them (95 sec 6).  Never referenced by the emission.
    path_ctr, path_hdr = C2.find_path_counter(mod, fs, fe)
    samp_ctr = E.find_bounce_counter(mod, fs, fe, nee["line"])

    splice = sb["sel_line"]
    ac = channel_scales(a, p)
    rep = {"a": a, "H": H, "y0": y0, "p": p, "up": up,
           "height": "abs" if absolute else "cam",
           "lu_min": LU_MIN, "tau_max": TAU_MAX, "exp_lim": EXP_LIM,
           "lambda_nm": list(LAMBDA), "a_channel": list(ac),
           "cbv_slot": CBV_SLOT, "cbv_base": cbv["base"],
           "cbv_own_reads": cbv["own_slot56_lines"],
           "nee_line": nee["line"] + 1, "backlit": nee["backlit"],
           "sun_cond": sb["cond"], "sun_radiance": sb["rad"],
           "origin": geo["origin"], "dir": geo["dir"],
           "dir_unit_proof": geo["unit_proof"],
           "path_counter": path_ctr, "path_header": path_hdr,
           "sample_counter": samp_ctr, "gated": False,
           "traces_added": 0,
           "splice_before_line": splice + 1,
           "sites": [{"line": s["line"] + 1, "res": s["res"],
                      "rad": s["rad"], "src_kind": s["src_kind"]}
                     for s in sites],
           "n_sites": len(sites)}
    if len(sites) != 3:
        die(f"{mod.name}: {len(sites)} sun sites, expected 3")

    # ---- dominance: everything read must dominate all three sites ---------
    need = [("cbv base", cbv["line"])]
    for tag, ids in (("origin", [geo["origin"][up]]),
                     ("direction", [geo["dir"][up]])):
        for c in ids:
            dl, _ = mod.find_def(c)
            if dl is None:
                die(f"{mod.name}: {tag} component {c} has no definition")
            need.append((f"{tag} {c}", dl))
    for s in sites:
        for tag, dl in need:
            if not cfg_dom.dominates(mod, fs, fe, dl, s["line"]):
                die(f"{mod.name}: {tag} (line {dl+1}) does not dominate the "
                    f"sun site at line {s['line']+1}")
    rep["dominates_all_sites"] = True

    if a == 0.0:
        rep["emitted"] = "nothing (a=0 identity control)"
        return [], [], rep

    # ---- constants --------------------------------------------------------
    for tok in ('%float_0', '%float_1'):
        if not any(re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant %float ',
                            ln) for ln in mod.lines):
            die(f"{mod.name}: expected constant {tok} is absent")
    u0 = E._uc(mod, consts, 0)
    uslot = E._uc(mod, consts, CBV_SLOT)
    uup = E._uc(mod, consts, up)
    fB = E._fc(mod, consts, -LOG2E / H)          # exponent of the column term
    fy0 = E._fc(mod, consts, y0)
    fexp_lo = E._fc(mod, consts, -EXP_LIM)
    fexp_hi = E._fc(mod, consts, EXP_LIM)
    flumin = E._fc(mod, consts, LU_MIN)
    ftaumax = E._fc(mod, consts, TAU_MAX * LOG2E)
    fa2 = [E._fc(mod, consts, x * LOG2E) for x in ac]

    ind = '               '
    ins = []

    def em(fmt):
        i = mod.new_id()
        ins.append(f"{ind}{i} = {fmt.format(i=i)}")
        return i

    # h = P_up (+ C_up)
    Pu = geo["origin"][up]
    if absolute:
        ch = em(f"OpAccessChain %_ptr_Uniform_v4float {cbv['base']} {u0} {uslot}")
        cv = em(f"OpLoad %v4float {ch}")
        Cu = em(f"OpCompositeExtract %float {cv} {up}")
        h = em(f"OpFAdd %float {Pu} {Cu}")
    else:
        h = Pu                       # camera-relative height: y0 is the camera
    hy = em(f"OpFSub %float {h} {fy0}")
    e0 = em(f"OpFMul %float {hy} {fB}")
    e = em(f"OpExtInst %float {glsl} NClamp {e0} {fexp_lo} {fexp_hi}")
    col = em(f"OpExtInst %float {glsl} Exp2 {e}")

    # am = max(1/max(L_up, LU_MIN) - 1, 0) -- the airmass EXCESS over zenith
    Lu = geo["dir"][up]
    lu = em(f"OpExtInst %float {glsl} NMax {Lu} {flumin}")
    inv = em(f"OpFDiv %float %float_1 {lu}")
    am0 = em(f"OpFSub %float {inv} %float_1")
    am = em(f"OpExtInst %float {glsl} NMax {am0} %float_0")
    q = em(f"OpFMul %float {col} {am}")

    # T_c = Exp2(-min(A2_c * q, TAU_MAX2)).  Channels sharing a constant share
    # the whole chain, so p=0 emits ONE transmittance, not three.
    tcache, tids = {}, []
    for c in range(3):
        key = fa2[c]
        if key not in tcache:
            t0 = em(f"OpFMul %float {q} {key}")
            t1 = em(f"OpExtInst %float {glsl} NMin {t0} {ftaumax}")
            t2 = em(f"OpFNegate %float {t1}")
            tcache[key] = em(f"OpExtInst %float {glsl} Exp2 {t2}")
        tids.append(tcache[key])

    # ---- application: multiply the RESULT, then redirect every consumer ----
    for c, s in enumerate(sites):
        nid = mod.new_id()
        n = replace_all_uses(mod, s["res"], nid, s["line"])
        if n == 0:
            die(f"{mod.name}: channel {c}: sun product {s['res']} has no "
                f"consumers to redirect")
        edits.append((s["line"], [f"{ind}{nid} = OpFMul %float {s['res']} "
                                  f"{tids[c]}"]))
        rep["sites"][c].update(new_res=nid, transmittance=tids[c],
                               uses_redirected=n)

    edits.append((splice - 1, ins))
    rep["transmittance_ids"] = tids
    rep["distinct_transmittances"] = len(tcache)
    rep["emitted"] = len(ins) + 3
    return consts, edits, rep


def process(path, outdir, a, H, y0, p, up, absolute):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    ntr_before = sum(ln.count('OpTraceRayKHR') for ln in mod.lines)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['volsun'] = build(mod, a, H, y0, p, up, absolute)
    apply_edits(mod, consts, edits)
    ntr_after = sum(ln.count('OpTraceRayKHR') for ln in mod.lines)
    if ntr_after != ntr_before:
        die(f"{mod.name}: trace count changed {ntr_before} -> {ntr_after}; "
            f"this feature adds ZERO rays")
    rep['volsun']['n_traces'] = ntr_after
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv_out], capture_output=True, text=True)
    if v.returncode != 0:
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--a', type=float, required=True,
                    help='vertical optical depth at y0 (== d0*H*exp(y0/H)). '
                         '0 emits nothing: the byte-identity control')
    ap.add_argument('--h', dest='H', type=float, default=120.0,
                    help='fog scale height in metres; sets the street-to-'
                         'rooftop gradient and nothing else')
    ap.add_argument('--y0', type=float, default=20.0,
                    help='world height at which --a IS the vertical optical '
                         'depth. Degenerate with --a: a wrong y0 rescales the '
                         'strength and cannot change the gradient')
    ap.add_argument('--p', type=float, default=1.0,
                    help='spectral exponent, sigma ~ lambda^-p. 0 neutral, '
                         '1 Mie-ish urban haze (ship), 4 Rayleigh (diagnostic)')
    ap.add_argument('--up', type=int, choices=(0, 1, 2), default=2,
                    help='world up axis. 2 (Z-up) per 95 sec 1c; --up 1 is '
                         'the one-frame falsifier')
    ap.add_argument('--height', choices=('abs', 'cam'), default='abs',
                    help='abs: world height via cbv slot 56 (the camera world '
                         'position). cam: camera-relative height, i.e. the fog '
                         'layer follows the camera -- the slot-56 discriminator')
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    if not 0.0 <= args.a <= 4.0:
        ap.error('--a must be in [0,4]')
    if not 5.0 <= args.H <= 5000.0:
        ap.error('--h must be in [5,5000] metres')
    if not 0.0 <= args.p <= 6.0:
        ap.error('--p must be in [0,6]')
    print(json.dumps(process(args.spvasm, args.outdir, args.a, args.H,
                             args.y0, args.p, args.up,
                             args.height == 'abs')))


if __name__ == '__main__':
    main()
