#!/usr/bin/env python3
"""Verify handoff/95's sun transmittance FROM THE SHIPPED BYTES.

Nothing here trusts the patcher's own report.  Every module is disassembled
back out of the .spv that will actually be served, the sun NEE trace and its
visibility branch are re-derived with the same hop-by-hop walk the patcher
used, and then the transmittance chain is walked BACKWARDS from each of the
three direct-sun products to the constants -- so the strength, the spectral
exponent, the scale height, the up axis and the absolute-vs-camera height
reference are all READ OFF THE EMITTED CODE and compared with what the build
asked for.

The five non-vacuity axes (95 sec 7 G6), each of which a wrong build fails:

  --a       recovered from A2_g / log2(e)
  --p       recovered from the RATIO A2_r : A2_g : A2_b, so a neutral build
            cannot pass as a tinted one or vice versa
  --h       recovered from B = -log2(e)/H
  --up      the chain must read component <up> of the NEE trace's OWN origin
            ctor AND component <up> of its OWN direction ctor -- the same
            index, twice, from two independent operands
  --height  `abs` requires the FAdd against a slot-56 cbv extract on the same
            component; `cam` requires its ABSENCE and h == the origin component

Plus, and these are the ones that make it a gate rather than a description:

  * ZERO RAYS.  Every module's OpTraceRayKHR count must equal the base's.
    This is the feature's headline claim against 88 and it is asserted here.
  * NOT GATED.  Neither find_path_counter's phi nor find_bounce_counter's may
    appear anywhere in the transmittance chain: the term runs at EVERY bounce
    by design (95 sec 6), and an accidental gate would be invisible on screen.
  * T <= 1 PROVABLE.  A2_c > 0, the NClamp and NMin bounds are present and
    finite, and the Exp2 argument is an FNegate of a non-negative NMin -- so
    the emitted factor cannot exceed 1.0 and 53's constraint holds
    mechanically, not by intention.
  * The closed form.  dev/volsun_model.py evaluates the recovered constants
    two ways over a 60k-point (height, elevation) grid; worst relative error
    must be under 2e-5, which is the float32 floor of the Exp2 chain.

  ./dev/verify_volsun.py DEST BASE --a 0.25 --h 120 --y0 20 --p 1 \
      --up 2 --height abs
  ./dev/verify_volsun.py --negative BASE
"""
import argparse, glob, math, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
import patch_cavity2 as C2
import patch_volsun as V
import volsun_model as M
from patch_chs_brdf import load_lenient

TOL = 2e-5
CTOL = 1e-6


def fail(msg):
    print("VERIFY FAILED: " + msg)
    sys.exit(1)


def disasm(spv):
    fd, path = tempfile.mkstemp(suffix='.spvasm')
    os.close(fd)
    r = subprocess.run(['spirv-dis', '--no-color', spv, '-o', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"spirv-dis failed on {spv}: {r.stderr}")
    return path


def cval(mod, idt):
    _, d = mod.find_def(idt)
    m = re.match(r'OpConstant %float (\S+)\s*$', d or '')
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def hop(mod, idt, pat, what, mname):
    _, d = mod.find_def(idt)
    m = re.match(pat + r'\s*$', d or '')
    if not m:
        fail(f"{mname}: transmittance walk ({what}): {idt} is {d!r}, "
             f"wanted {pat}")
    return m


def comm(mod, idt, op, mname, what, pick):
    """One FMul/FAdd/FSub operand chosen by predicate; returns (picked, other)."""
    m = hop(mod, idt, rf'Op{op} %float (%\w+) (%\w+)', what, mname)
    a, b = m.group(1), m.group(2)
    if pick(a):
        return a, b
    if pick(b):
        return b, a
    fail(f"{mname}: transmittance walk ({what}): neither operand of {idt} "
         f"({a}, {b}) matched")


def walk(mod, mname, tid, seen, fs, fe):
    """Backwards from one channel's T to every constant it rests on."""
    r = {}
    e = hop(mod, tid, r'OpExtInst %float %\w+ Exp2 (%\w+)', 'T = Exp2', mname)
    neg = hop(mod, e.group(1), r'OpFNegate %float (%\w+)', 'Exp2 arg', mname)
    nm = hop(mod, neg.group(1), r'OpExtInst %float %\w+ NMin (%\w+) (%\w+)',
             'tau NMin', mname)
    tau0, r['tau_max2'] = nm.group(1), cval(mod, nm.group(2))
    if r['tau_max2'] is None:
        fail(f"{mname}: tau NMin's bound {nm.group(2)} is not a constant")
    a2id, q = comm(mod, tau0, 'FMul', mname, 'tau = q*A2',
                   lambda x: cval(mod, x) is not None)
    r['a2'] = cval(mod, a2id)
    colid, amid = comm(mod, q, 'FMul', mname, 'q = col*am',
                       lambda x: re.match(r'OpExtInst %float %\w+ Exp2 ',
                                          mod.find_def(x)[1] or ''))
    # --- column: col = Exp2(NClamp(FMul(FSub(h, y0), B))) ------------------
    ce = hop(mod, colid, r'OpExtInst %float %\w+ Exp2 (%\w+)', 'col', mname)
    cl = hop(mod, ce.group(1),
             r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)',
             'col exponent clamp', mname)
    r['exp_lo'], r['exp_hi'] = cval(mod, cl.group(2)), cval(mod, cl.group(3))
    bid, hy = comm(mod, cl.group(1), 'FMul', mname, 'e0 = (h-y0)*B',
                   lambda x: cval(mod, x) is not None)
    r['B'] = cval(mod, bid)
    sm = hop(mod, hy, r'OpFSub %float (%\w+) (%\w+)', 'h - y0', mname)
    r['y0'] = cval(mod, sm.group(2))
    if r['y0'] is None:
        fail(f"{mname}: the subtrahend of h-y0 ({sm.group(2)}) is not a constant")
    h = sm.group(1)
    _, hd = mod.find_def(h)
    am2 = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', hd or '')
    # `abs` is recognised by SHAPE, not by the top-level opcode: the origin
    # component is itself an FAdd (prehit + t*D) in every permutation, so
    # "h is an FAdd" proves nothing. The discriminator is a cbv CompositeExtract
    # operand. A malformed `abs` build therefore reads back as `cam` and is
    # caught by the caller's height comparison rather than passing silently.
    cu = None
    if am2:
        for cand, other in ((am2.group(1), am2.group(2)),
                            (am2.group(2), am2.group(1))):
            _, cd = mod.find_def(cand)
            if not re.match(r'OpCompositeExtract %float (%\w+) \d+\s*$', cd or ''):
                continue
            ld0 = re.match(r'OpCompositeExtract %float (%\w+) \d+\s*$', cd)
            _, lld = mod.find_def(ld0.group(1))
            if not re.match(r'OpLoad %v4float %\w+\s*$', lld or ''):
                continue
            cu, r['P_up'] = cand, other
            break
    if cu is not None:
        r['height'] = 'abs'
        ex = hop(mod, cu, r'OpCompositeExtract %float (%\w+) (\d+)',
                 'camera height extract', mname)
        r['cam_comp'] = int(ex.group(2))
        ld = hop(mod, ex.group(1), r'OpLoad %v4float (%\w+)',
                 'camera cbv load', mname)
        ch = hop(mod, ld.group(1),
                 r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_(\d+)',
                 'camera cbv chain', mname)
        r['cbv_base'], r['cbv_slot'] = ch.group(1), int(ch.group(2))
    else:
        r['height'] = 'cam'
        r['P_up'] = h
        r['cam_comp'] = None
        r['cbv_slot'] = None
    # --- airmass excess: am = NMax(FDiv(1,NMax(L_up,LUMIN)) - 1, 0) --------
    an = hop(mod, amid, r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)',
             'am NMax', mname)
    if cval(mod, an.group(2)) != 0.0:
        fail(f"{mname}: am is floored at {an.group(2)}, not 0.0 -- T<=1 is "
             f"not provable")
    a0 = hop(mod, an.group(1), r'OpFSub %float (%\w+) %float_1', 'am - 1', mname)
    dv = hop(mod, a0.group(1), r'OpFDiv %float %float_1 (%\w+)', '1/lu', mname)
    ln = hop(mod, dv.group(1), r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)',
             'lu NMax', mname)
    r['L_up'], r['lu_min'] = ln.group(1), cval(mod, ln.group(2))
    if r['lu_min'] is None or r['lu_min'] <= 0.0:
        fail(f"{mname}: the FDiv denominator's floor is {ln.group(2)}, not a "
             f"positive constant -- a zero divide is reachable")
    # TRANSITIVE closure of the emitted term, so a gate spliced ANYWHERE
    # inside it is caught -- not just a counter substituted at one of the
    # positions this walk happens to name. The recursion stops at the three
    # declared leaves (the NEE trace's own origin and direction components and
    # the camera cbv object): everything below them is the engine's code, and
    # the claim being tested is only ever about what WE emitted.
    seen.update(closure(mod, tid, fs, fe,
                        {r['P_up'], r['L_up'], r.get('cbv_base')}))
    return r


def closure(mod, root, fs, fe, leaves, cap=4096):
    """Every id the emitted transmittance rests on, down to `leaves`."""
    out, stack = set(), [root]
    while stack and len(out) < cap:
        i = stack.pop()
        if i in out or not i.startswith('%'):
            continue
        out.add(i)
        if i in leaves:
            continue
        ln, d = mod.find_def(i)
        if ln is None or not (fs < ln < fe):
            continue                      # a global: type, constant, variable
        for tok in re.findall(r'%\w+', d):
            if tok != i:
                stack.append(tok)
    return out


def check_module(spv, base_spv, args):
    p = disasm(spv)
    mod, _ = load_lenient(p)
    os.unlink(p)
    mname = mod.ident or os.path.basename(spv)
    el, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    nee = E.find_nee_trace(mod, fs, fe)
    sb = V.find_sun_branch(mod, nee, fs, fe)
    sites = V.find_sun_result_sites(mod, fs, fe, sb)
    if len(sites) != 3:
        fail(f"{mname}: {len(sites)} sun sites")
    geo = V.find_nee_geometry(mod, nee)

    # --- zero rays --------------------------------------------------------
    pb = disasm(base_spv)
    bmod, _ = load_lenient(pb)
    os.unlink(pb)
    nb = sum(ln.count('OpTraceRayKHR') for ln in bmod.lines)
    nt = sum(ln.count('OpTraceRayKHR') for ln in mod.lines)
    if nt != nb:
        fail(f"{mname}: {nt} traces, base has {nb} -- this feature adds ZERO rays")

    # --- each sun product must be consumed by exactly one FMul with a T ----
    seen, rs = set(), []
    for c, s in enumerate(sites):
        pat = re.compile(r'(?<![%\w])' + re.escape(s["res"]) + r'(?![\w])')
        uses = [i for i in range(fs, fe)
                if pat.search(mod.lines[i])
                and not re.match(r'\s*' + re.escape(s["res"]) + r'\s*=',
                                 mod.lines[i])]
        if len(uses) != 1:
            fail(f"{mname}: channel {c}: sun product {s['res']} has "
                 f"{len(uses)} consumers, expected exactly 1 (the "
                 f"transmittance multiply; replace_all_uses redirects the rest)")
        m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$',
                     mod.lines[uses[0]])
        if not m:
            fail(f"{mname}: channel {c}: the only consumer of {s['res']} is "
                 f"not an FMul: {mod.lines[uses[0]]!r}")
        tid = m.group(3) if m.group(2) == s["res"] else m.group(2)
        rs.append(walk(mod, mname, tid, seen, fs, fe))

    # --- one geometry, three channels: everything but A2 must agree -------
    for k in ('B', 'y0', 'tau_max2', 'exp_lo', 'exp_hi', 'lu_min',
              'height', 'cam_comp', 'cbv_slot', 'P_up', 'L_up'):
        vs = {r[k] for r in rs}
        if len(vs) != 1:
            fail(f"{mname}: the three channels disagree on {k}: {vs}")
    r0 = rs[0]

    # --- the up axis, twice, from two independent operands -----------------
    if r0['P_up'] != geo['origin'][args.up]:
        fail(f"{mname}: the height reads {r0['P_up']}, which is not component "
             f"{args.up} of the NEE trace's own origin ({geo['origin']})")
    if r0['L_up'] != geo['dir'][args.up]:
        fail(f"{mname}: the elevation reads {r0['L_up']}, which is not "
             f"component {args.up} of the NEE direction ({geo['dir']})")
    if r0['height'] != args.height:
        fail(f"{mname}: height reference is {r0['height']}, asked {args.height}")
    if args.height == 'abs':
        if r0['cbv_slot'] != V.CBV_SLOT:
            fail(f"{mname}: camera height read from cbv slot {r0['cbv_slot']}, "
                 f"expected {V.CBV_SLOT}")
        if r0['cam_comp'] != args.up:
            fail(f"{mname}: camera height uses component {r0['cam_comp']}, "
                 f"expected {args.up}")
        cbv = V.find_cbv_base(mod, nee, fs, fe)
        if r0['cbv_base'] != cbv['base']:
            fail(f"{mname}: camera cbv base {r0['cbv_base']} is not the object "
                 f"the engine's own slot-77 offset load uses ({cbv['base']})")

    # --- NOT GATED (95 sec 6) ---------------------------------------------
    path_ctr, _ = C2.find_path_counter(mod, fs, fe)
    samp_ctr = E.find_bounce_counter(mod, fs, fe, nee["line"])
    for tag, cid in (("path", path_ctr), ("sample", samp_ctr)):
        if cid in seen:
            fail(f"{mname}: the transmittance chain references the {tag} "
                 f"counter {cid} -- this term must run at EVERY bounce")
    if len(seen) > 400:
        fail(f"{mname}: the transmittance closure is {len(seen)} ids -- it has "
             f"escaped its declared leaves, so the no-gate proof is vacuous")

    # --- the constants, against what the build asked for -------------------
    wantB = -M.LOG2E / args.H
    if abs(r0['B'] - wantB) > CTOL * max(1.0, abs(wantB)):
        fail(f"{mname}: B is {r0['B']}, expected {wantB} (H={args.H})")
    if abs(r0['y0'] - args.y0) > 1e-4:
        fail(f"{mname}: y0 is {r0['y0']}, expected {args.y0}")
    if abs(r0['lu_min'] - V.LU_MIN) > 1e-6:
        fail(f"{mname}: LU_MIN is {r0['lu_min']}, expected {V.LU_MIN}")
    if abs(r0['tau_max2'] - V.TAU_MAX * M.LOG2E) > 1e-3:
        fail(f"{mname}: TAU_MAX is {r0['tau_max2'] / M.LOG2E}, expected "
             f"{V.TAU_MAX}")
    if abs(r0['exp_lo'] + V.EXP_LIM) > 1e-6 or abs(r0['exp_hi'] - V.EXP_LIM) > 1e-6:
        fail(f"{mname}: column exponent clamp is [{r0['exp_lo']}, "
             f"{r0['exp_hi']}], expected +-{V.EXP_LIM}")
    want = [x * M.LOG2E for x in V.channel_scales(args.a, args.p)]
    got = [r['a2'] for r in rs]
    for c in range(3):
        if got[c] is None or got[c] <= 0.0:
            fail(f"{mname}: channel {c}: A2 is {got[c]} -- T<=1 is not provable")
        if abs(got[c] - want[c]) > CTOL * max(1.0, want[c]):
            fail(f"{mname}: channel {c}: A2 is {got[c]}, expected {want[c]} "
                 f"(a={args.a}, p={args.p})")
    # the SPECTRAL axis, from the ratio alone -- a neutral build cannot pass
    ratio = [got[0] / got[1], got[2] / got[1]]
    wr = [(M.LAMBDA[1] / M.LAMBDA[0]) ** args.p,
          (M.LAMBDA[1] / M.LAMBDA[2]) ** args.p]
    for i in range(2):
        if abs(ratio[i] - wr[i]) > 1e-5:
            fail(f"{mname}: spectral ratio {ratio} != {wr} (p={args.p})")
    return {"module": mname, "a2": got, "B": r0['B'], "y0": r0['y0'],
            "height": r0['height'], "traces": nt, "closure": len(seen)}


def negative(d):
    mods = sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv')))
    if len(mods) != 12:
        fail(f"{d}: {len(mods)} reference raygens, expected 12")
    for spv in mods:
        p = disasm(spv)
        mod, _ = load_lenient(p)
        os.unlink(p)
        el, fid = E._entry(mod, 'RayGenerationKHR')
        fs, fe = E._func_span(mod, fid)
        nee = E.find_nee_trace(mod, fs, fe)
        sb = V.find_sun_branch(mod, nee, fs, fe)
        for c, s in enumerate(V.find_sun_result_sites(mod, fs, fe, sb)):
            pat = re.compile(r'(?<![%\w])' + re.escape(s["res"]) + r'(?![\w])')
            for i in range(fs, fe):
                if not pat.search(mod.lines[i]):
                    continue
                m = re.match(r'\s*%\w+\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$',
                             mod.lines[i])
                if not m:
                    continue
                other = m.group(2) if m.group(1) == s["res"] else m.group(1)
                if re.match(r'OpExtInst %float %\w+ Exp2 ',
                            mod.find_def(other)[1] or ''):
                    fail(f"{os.path.basename(spv)}: channel {c} already "
                         f"carries a transmittance multiply -- this is NOT a "
                         f"clean base")
    print(f"  negative control: {len(mods)}/12 clean (no transmittance "
          f"multiply on any sun product)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dest')
    ap.add_argument('base', nargs='?')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--a', type=float)
    ap.add_argument('--h', dest='H', type=float, default=120.0)
    ap.add_argument('--y0', type=float, default=20.0)
    ap.add_argument('--p', type=float, default=1.0)
    ap.add_argument('--up', type=int, default=2)
    ap.add_argument('--height', choices=('abs', 'cam'), default='abs')
    args = ap.parse_args()
    if args.negative:
        negative(args.dest)
        return
    if args.a is None or args.base is None:
        ap.error('need BASE and --a unless --negative')
    mods = sorted(glob.glob(os.path.join(args.dest, '*.rgs_reference_main.spv')))
    if len(mods) != 12:
        fail(f"{args.dest}: {len(mods)} reference raygens, expected 12")
    out = []
    for spv in mods:
        b = os.path.join(args.base, os.path.basename(spv))
        if not os.path.exists(b):
            fail(f"no base module for {os.path.basename(spv)}")
        out.append(check_module(spv, b, args))
    w, at, n = M.grid(args.a, args.H, args.y0, args.p,
                      lu_min=V.LU_MIN, tau_max=V.TAU_MAX, exp_lim=V.EXP_LIM)
    if w > TOL:
        fail(f"closed-form check: worst relative error {w:.3e} over {n} "
             f"points, tolerance {TOL:.0e} (at {at})")
    cl = max(o["closure"] for o in out)
    print(f"  verify_volsun: 12/12 modules, 36/36 sun sites, "
          f"0 rays added, ungated at every bounce "
          f"(closure <= {cl} ids, both counters absent)")
    print(f"  constants re-derived from the shipped bytes: "
          f"a={args.a} p={args.p} H={args.H} y0={args.y0} up={args.up} "
          f"height={args.height}")
    print(f"  closed form: worst rel err {w:.2e} over {n} points "
          f"(tol {TOL:.0e})")


if __name__ == '__main__':
    main()
