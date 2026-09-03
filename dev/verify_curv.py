#!/usr/bin/env python3
"""verify_curv -- read the curvature rung back off the SHIPPED BYTES.

handoff/109 sec 6.  This does not trust the patcher's own report: it
disassembles each `.spv` that is actually going to be served, finds the
estimator and the two bleed rewrites structurally, walks the whole chain from
the terminator band back to the two neighbour texel fetches, checks every
baked constant against the rung's knobs, and then INTERPRETS the six mapping
instructions over a kappa sweep and compares against `dev/curv_model.scale`.

It is written to be non-vacuous by construction, and `build_curv.sh` proves
that by feeding it the base, the control, a wrong gain, a wrong kappa0, a
wrong jump and a guard-less decoy, each of which it must REJECT.

The chain it insists on, bottom up, per bleed site:

    bq'  = OpFDiv  bq  S           the band WIDTH   (W -> W*s)
    bw'  = OpFMul  bw  S           the AMPLITUDE    (w -> w*s)
    S    = OpSelect (dpx2 < J^2 && dpy2 < J^2) Sraw 1.0        [guard]
    Sraw = NClamp(1 + g*(NClamp(kappa, kmin, kmax)/k0 - 1), smin, smax)
    kappa= 0.5 * ( sqrt(dnx2 / max(dpx2, eps)) + sqrt(dny2 / max(dpy2, eps)) )
    dp*2 = Dot(P(neighbour) - P(centre))       both from the module's own
    dn*2 = Dot(N(neighbour) - N(centre))       matrix rows / normal decode
    neighbour coords = (x+step, y) and (x, y+step), the SAME OpCompositeConstruct
                       feeding both the depth fetch and the normal fetch

Usage:
    python3 dev/verify_curv.py <dir-of-spv> [--tier bleed|vis] [--gain 1.0]
        [--kappa0 10] [--kmin .5] [--kmax 40] [--smin .3] [--smax 2]
        [--jump 0.05] [--step 1] [--no-guard]
"""
import argparse, glob, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wpos_core as W
import curv_model as CM
from patch_chs_brdf import load_lenient
from patch_curv import KNOWN_DECLINE, CENSUS

# The three constants the shipped bleed bakes in (97 sec 3.4): the band width
# 1/0.35, and the two Jensen channel ratios.  The verifier anchors on these
# rather than on anything the patcher told it, so it is an independent read.
INVB_TOK = '%float_2_85714293'
A_R_TOK = '%float_0_335999995'
A_B_TOK = '%float_0_101000004'


def bleed_sites(mod, D):
    """Every terminator-bleed block, found from its two channel constants.

    Tolerates both forms.  Shipped:

        bw  = OpFMul t t                 <- both operands equal
        r   = OpFMul bw 0.336
        b   = OpFMul bw 0.101

    Curvature-scaled:

        bw  = OpFMul t t
        amp = OpFMul bw s                <- operands differ
        r   = OpFMul amp 0.336
    """
    out = []
    for i, (ln, txt) in D.items():
        m = re.match(r'OpFMul %float (%\w+) ' + A_R_TOK + r'\s*$', txt.strip())
        if not m:
            continue
        amp = m.group(1)
        if not any(t.strip() == 'OpFMul %float ' + amp + ' ' + A_B_TOK
                   for _i, (_l, t) in D.items()):
            continue
        out.append(dict(amp=amp, line=ln))
    out.sort(key=lambda d: d['line'])
    return out

FAIL = []


def bad(mod, why):
    FAIL.append('%s :: %s' % (mod, why))


def fconst(mod, idt):
    """float value of a constant id, or None."""
    _, d = mod.find_def(idt)
    m = re.match(r'OpConstant %float (\S+)\s*$', d or '')
    return float(m.group(1)) if m else None


def uconst(mod, idt):
    _, d = mod.find_def(idt)
    m = re.match(r'OpConstant %uint (\d+)\s*$', d or '')
    return int(m.group(1)) if m else None


def img_src(C, idt):
    """Resolve an image id back to its descriptor, so two separate OpLoads of
    the same binding compare equal."""
    ld = C.m(idt, r'OpLoad %\w+ (%\w+)')
    if not ld:
        return idt
    ac = C.m(ld.group(1), r'OpAccessChain %\w+ (%\w+) (%\w+)')
    return ' '.join(ac.groups()) if ac else ld.group(1)


def near(a, b, tol=1e-5):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


class Chain:
    def __init__(self, mod, D):
        self.mod, self.D = mod, D

    def op(self, idt):
        return self.D.get(idt, (None, ''))[1]

    def m(self, idt, pat):
        return re.match(pat + r'\s*$', self.op(idt))

    def ext(self, idt, name):
        return self.m(idt, r'OpExtInst %float %\w+ ' + name + r' (.*)')

    def fetches(self, root, depth=8):
        """Every (image, coord, lod) reachable from `root` within `depth`.

        The reconstruction chain is FDiv(FAdd(Fma(Fma(FMul)))) over the four
        matrix rows, so the texel fetch sits 4-5 operands deep; the normal
        decode is 3-4 deep.  Walking rather than pattern-matching the whole
        chain means the check survives a different Fma/FMul spelling."""
        out, seen, stack = [], set(), [(root, 0)]
        while stack:
            idt, d = stack.pop()
            if idt in seen or d > depth:
                continue
            seen.add(idt)
            t = self.op(idt)
            mm = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$',
                          t.strip())
            if mm:
                out.append(mm.groups())
                continue
            for o in re.findall(r'%\w+', t):
                stack.append((o, d + 1))
        return out


def check_module(path, knobs, tier):
    mod, _ = load_lenient(path)
    D = W.defs_index(mod)
    name = mod.dxil or os.path.basename(path)
    C = Chain(mod, D)
    sites = bleed_sites(mod, D)
    if not sites:
        bad(name, 'no terminator-bleed block at all')
        return None

    # ---- 1. every site must be rewritten, and by the SAME s ---------------
    S, shipped = set(), 0
    for st in sites:
        amp = st['amp']
        mm = C.m(amp, r'OpFMul %float (%\w+) (%\w+)')
        if not mm:
            bad(name, 'bleed amplitude %s is not a product' % amp)
            continue
        a1, a2 = mm.groups()
        if a1 == a2:
            shipped += 1                      # untouched: amp IS w = t*t
            bw, s_a = amp, None
        else:
            bw, s_a = a1, a2
            if C.m(a2, r'OpFMul %float (%\w+) \1'):
                bw, s_a = a2, a1
            sq = C.m(bw, r'OpFMul %float (%\w+) (%\w+)')
            if not sq or sq.group(1) != sq.group(2):
                bad(name, 'the scaled amplitude does not wrap the shipped w = t*t')
                continue
            S.add(s_a)
        sq = C.m(bw, r'OpFMul %float (%\w+) (%\w+)')
        if not sq or sq.group(1) != sq.group(2):
            bad(name, 'band amplitude is not t*t')
            continue
        cl = C.ext(sq.group(1), 'NClamp')
        if not cl:
            bad(name, 'the band is not saturated')
            continue
        parts = cl.group(1).split()
        if fconst(mod, parts[1]) > 0.0 or fconst(mod, parts[2]) != 1.0:
            bad(name, 'the band saturate is [%s, %s], not [0, 1]'
                % (parts[1], parts[2]))
        fs = C.m(parts[0], r'OpFSub %float %float_1 (%\w+)')
        if not fs:
            bad(name, 'the band is not 1 - NoL/W')
            continue
        q = fs.group(1)
        qd = C.m(q, r'OpFDiv %float (%\w+) (%\w+)')
        if s_a is None:
            if qd:
                bad(name, 'the width is scaled but the amplitude is not')
            elif not C.m(q, r'OpFMul %float (%\w+) ' + INVB_TOK):
                bad(name, 'the shipped width is not NoL * 1/0.35')
        else:
            if not qd:
                bad(name, 'the amplitude is scaled but the width is not -- '
                          'this widens nothing, it only brightens')
                continue
            if qd.group(2) != s_a:
                bad(name, 'width and amplitude are scaled by different values')
            if not C.m(qd.group(1), r'OpFMul %float (%\w+) ' + INVB_TOK):
                bad(name, 'the divided width is not the shipped NoL * 1/0.35')
        cons = [t2.strip() for _i, (_l, t2) in D.items()
                if amp in re.findall(r'%\w+', t2)]
        if len(cons) != 3:
            bad(name, 'bleed amplitude has %d consumers, expected 3' % len(cons))
        elif len([c for c in cons if A_R_TOK not in c and A_B_TOK not in c]) != 1:
            bad(name, "the amplitude does not reach 78's luminance delta")

    if name in KNOWN_DECLINE:
        if S:
            bad(name, 'declined module carries a scaled bleed site')
        if shipped != len(sites):
            bad(name, 'declined module is not byte-shipped at every site')
        return dict(declined=True, sites=len(sites), s=None)
    if shipped:
        bad(name, '%d of %d bleed sites are still unscaled'
            % (shipped, len(sites)))
    if len(S) != 1:
        bad(name, '%d distinct scale values across %d sites'
            % (len(S), len(sites)))
        return None
    s_id = S.pop()

    # ---- 2. the guard ----------------------------------------------------
    sraw = s_id
    if knobs['guard']:
        g = C.m(s_id, r'OpSelect %float (%\w+) (%\w+) (%\w+)')
        if not g:
            bad(name, 's is not an OpSelect -- the silhouette guard is missing')
            return None
        cond, sraw, fallback = g.groups()
        if fconst(mod, fallback) != 1.0:
            bad(name, 'silhouette fallback is %s, must be the shipped 1.0'
                % fallback)
        la = C.m(cond, r'OpLogicalAnd %bool (%\w+) (%\w+)')
        if not la:
            bad(name, 'guard condition is not a LogicalAnd of two tests')
            return None
        dps = []
        for b in la.groups():
            lt = C.m(b, r'OpFOrdLessThan %bool (%\w+) (%\w+)')
            if not lt:
                bad(name, 'guard test is not OpFOrdLessThan (NaN must fall back)')
                return None
            dps.append(lt.group(1))
            j2 = fconst(mod, lt.group(2))
            if not near(j2, knobs['jump'] ** 2):
                bad(name, 'guard threshold %s != jump^2 = %g' % (j2, knobs['jump'] ** 2))
    else:
        if C.m(s_id, r'OpSelect %float (.*)'):
            bad(name, 's IS guarded but --no-guard was asserted')

    # ---- 3. the mapping, constant by constant ----------------------------
    cl = C.ext(sraw, 'NClamp')
    if not cl:
        bad(name, 's is not clamped')
        return None
    q3, cs_lo, cs_hi = cl.group(1).split()
    if not near(fconst(mod, cs_lo), knobs['smin']) or \
       not near(fconst(mod, cs_hi), knobs['smax']):
        bad(name, 's clamp is [%s, %s], expected [%g, %g]'
            % (fconst(mod, cs_lo), fconst(mod, cs_hi), knobs['smin'], knobs['smax']))
    a = C.m(q3, r'OpFAdd %float (%\w+) (%\w+)')
    if not a:
        bad(name, 'mapping is not 1 + g*(...)')
        return None
    one_id, q2 = a.groups()
    if fconst(mod, one_id) != 1.0:
        one_id, q2 = q2, one_id
    if fconst(mod, one_id) != 1.0:
        bad(name, 'mapping pivot is not 1.0')
    mm = C.m(q2, r'OpFMul %float (%\w+) (%\w+)')
    if not mm:
        bad(name, 'no gain multiply')
        return None
    q1, gid = mm.groups()
    if fconst(mod, gid) is None:
        q1, gid = gid, q1
    if not near(fconst(mod, gid), knobs['gain']):
        bad(name, 'gain is %s, expected %g' % (fconst(mod, gid), knobs['gain']))
    sm = C.m(q1, r'OpFSub %float (%\w+) (%\w+)')
    if not sm or fconst(mod, sm.group(2)) != 1.0:
        bad(name, 'mapping is not (kappa/k0 - 1)')
        return None
    q0 = sm.group(1)
    km = C.m(q0, r'OpFMul %float (%\w+) (%\w+)')
    if not km:
        bad(name, 'no kappa0 divide')
        return None
    kc, k0id = km.groups()
    if fconst(mod, k0id) is None:
        kc, k0id = k0id, kc
    if not near(fconst(mod, k0id), 1.0 / knobs['kappa0'], 1e-4):
        bad(name, '1/kappa0 is %s, expected %g'
            % (fconst(mod, k0id), 1.0 / knobs['kappa0']))
    kcl = C.ext(kc, 'NClamp')
    if not kcl:
        bad(name, 'kappa is not clamped')
        return None
    kappa, kk_lo, kk_hi = kcl.group(1).split()
    if not near(fconst(mod, kk_lo), knobs['kmin']) or \
       not near(fconst(mod, kk_hi), knobs['kmax']):
        bad(name, 'kappa clamp is [%s, %s], expected [%g, %g]'
            % (fconst(mod, kk_lo), fconst(mod, kk_hi), knobs['kmin'], knobs['kmax']))

    # ---- 4. kappa = mean of the two axis ratios --------------------------
    hm = C.m(kappa, r'OpFMul %float (%\w+) (%\w+)')
    if not hm:
        bad(name, 'kappa is not a mean')
        return None
    ksum, halfid = hm.groups()
    if fconst(mod, halfid) is None:
        ksum, halfid = halfid, ksum
    if not near(fconst(mod, halfid), 0.5):
        bad(name, 'kappa mean factor is %s, expected 0.5' % fconst(mod, halfid))
    ad = C.m(ksum, r'OpFAdd %float (%\w+) (%\w+)')
    if not ad:
        bad(name, 'kappa is not the sum of two axis ratios')
        return None
    axes = []
    for ka in ad.groups():
        sq = C.ext(ka, 'Sqrt')
        if not sq:
            bad(name, 'axis ratio is not a Sqrt')
            return None
        dv = C.m(sq.group(1).strip(), r'OpFDiv %float (%\w+) (%\w+)')
        if not dv:
            bad(name, 'axis ratio is not |dN|^2 / |dP|^2')
            return None
        dn2, den = dv.groups()
        nx = C.ext(den, 'NMax')
        if not nx:
            bad(name, '|dP|^2 is not floored by NMax')
            return None
        dp2, eps = nx.group(1).split()
        axes.append((dn2, dp2))

    # ---- 5. the two neighbour taps ---------------------------------------
    def diff_triple(dot_id, what):
        dd = C.m(dot_id, r'OpDot %float (%\w+) (%\w+)')
        if not dd or dd.group(1) != dd.group(2):
            bad(name, '%s is not Dot(v, v)' % what)
            return None
        cc = C.m(dd.group(1), r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
        if not cc:
            bad(name, '%s is not a v3 of differences' % what)
            return None
        out = []
        for k in range(3):
            sb = C.m(cc.group(k + 1), r'OpFSub %float (%\w+) (%\w+)')
            if not sb:
                bad(name, '%s component %d is not a subtraction' % (what, k))
                return None
            out.append(sb.groups())
        return out

    coords, dimgs, nimgs = [], set(), set()
    for ax, (dn2, dp2) in enumerate(axes):
        dp = diff_triple(dp2, 'dP axis %d' % ax)
        dn = diff_triple(dn2, 'dN axis %d' % ax)
        if dp is None or dn is None:
            return None
        # the neighbour P must come from a depth texel, and the neighbour N
        # from a normal texel at the SAME coordinate -- otherwise dN and dP
        # are measured across different surface points and kappa is noise.
        fp = C.fetches(dp[0][0])
        fn = C.fetches(dn[0][0])
        if len(fp) != 1:
            bad(name, 'axis %d: %d depth fetches under the neighbour P'
                % (ax, len(fp)))
            return None
        if len(fn) != 1:
            bad(name, 'axis %d: %d normal fetches under the neighbour N'
                % (ax, len(fn)))
            return None
        (dimg, dco, dlod), (nimg, nco, nlod) = fp[0], fn[0]
        if dco != nco:
            bad(name, 'axis %d: the neighbour normal is not fetched at the '
                      'neighbour depth coordinate' % ax)
        if dlod != nlod:
            bad(name, 'axis %d: depth and normal are fetched at different LODs'
                % ax)
        dimgs.add(img_src(C, dimg))
        nimgs.add(img_src(C, nimg))
        cc = C.m(dco, r'OpCompositeConstruct %v2uint (%\w+) (%\w+)')
        if not cc:
            bad(name, 'axis %d: the tap coordinate is not a v2uint construct' % ax)
            return None
        coords.append(cc.groups())
        # the centre of both differences must be shared between the axes
        if ax == 1:
            if [x[1] for x in dp] != centre_p or [x[1] for x in dn] != centre_n:
                bad(name, 'the two axes are differenced against different centres')
        else:
            centre_p = [x[1] for x in dp]
            centre_n = [x[1] for x in dn]
    if len(dimgs) != 1 or len(nimgs) != 1:
        bad(name, 'the two taps read different images (%d depth, %d normal)'
            % (len(dimgs), len(nimgs)))
    if dimgs and nimgs and dimgs == nimgs:
        bad(name, 'depth and normal are the same image -- one slot is wrong')

    # The two taps must be one texel apart in x and in y FROM A COMMON
    # CENTRE.  Comparing the two coordinate constructs against each other
    # proves that without having to know what the centre coordinate is:
    # axis0 = (C0+step, C1) and axis1 = (C0, C1+step), or the mirror.
    def off(a, b):
        ia = C.m(a, r'OpIAdd %uint (%\w+) (%\w+)')
        if not ia:
            return None
        p1, p2 = ia.groups()
        if p1 == b and uconst(mod, p2) is not None:
            return uconst(mod, p2)
        if p2 == b and uconst(mod, p1) is not None:
            return uconst(mod, p1)
        return None

    (a0, b0), (a1, b1) = coords
    cand = [(off(a0, a1), off(b1, b0)), (off(a1, a0), off(b0, b1))]
    good = [c for c in cand if c[0] == knobs['step'] and c[1] == knobs['step']]
    if len(good) != 1:
        bad(name, 'the two taps are not (+%d, 0) and (0, +%d) about a common '
                  'centre: %s' % (knobs['step'], knobs['step'], cand))

    # ---- 6. interpret the mapping numerically ----------------------------
    g = fconst(mod, gid)
    k0 = 1.0 / fconst(mod, k0id)
    for kv in (0.0, 0.2, 0.5, 1.0, 3.0, 7.3, 10.0, 13.0, 20.0, 40.0, 1e5):
        want = CM.scale(kv, knobs['gain'], knobs['kappa0'], knobs['smin'],
                        knobs['smax'], knobs['kmin'], knobs['kmax'])
        got = CM.scale(kv, g, k0, fconst(mod, cs_lo), fconst(mod, cs_hi),
                       fconst(mod, kk_lo), fconst(mod, kk_hi))
        if abs(want - got) > 1e-6:
            bad(name, 'emitted mapping disagrees at kappa=%g: %g vs %g'
                % (kv, got, want))
            break
    return dict(declined=False, sites=len(sites), s=s_id)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--tier', default='bleed', choices=('bleed', 'vis'))
    ap.add_argument('--gain', type=float, default=1.0)
    ap.add_argument('--kappa0', type=float, default=CM.KAPPA0)
    ap.add_argument('--kmin', type=float, default=CM.KAPPA_MIN)
    ap.add_argument('--kmax', type=float, default=CM.KAPPA_MAX)
    ap.add_argument('--smin', type=float, default=CM.S_MIN)
    ap.add_argument('--smax', type=float, default=CM.S_MAX)
    ap.add_argument('--jump', type=float, default=CM.JUMP)
    ap.add_argument('--step', type=int, default=1)
    ap.add_argument('--no-guard', action='store_true')
    a = ap.parse_args()
    knobs = dict(gain=a.gain, kappa0=a.kappa0, kmin=a.kmin, kmax=a.kmax,
                 smin=a.smin, smax=a.smax, jump=a.jump, step=a.step,
                 guard=not a.no_guard)
    if a.tier != 'bleed':
        sys.exit('verify_curv: only --tier bleed is verifiable this way; the '
                 'vis rung is a diagnostic and is gated by build_curv.sh on '
                 'its report, not here.')
    files = sorted(glob.glob(os.path.join(a.dir, '*.dxil.spv')))
    if not files:
        sys.exit('verify_curv: no *.dxil.spv in ' + a.dir)
    tmp = tempfile.mkdtemp(prefix='verify_curv.')
    n_patched = n_declined = n_sites = 0
    for f in files:
        asm = os.path.join(tmp, os.path.basename(f) + '.spvasm')
        r = subprocess.run(['spirv-dis', f, '-o', asm],
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad(os.path.basename(f), 'spirv-dis failed')
            continue
        res = check_module(asm, knobs, a.tier)
        if res is None:
            continue
        if res['declined']:
            n_declined += 1
        else:
            n_patched += 1
            n_sites += res['sites']
    print('  modules            : %d' % len(files))
    print('  patched            : %d  (census %d)' % (n_patched, CENSUS['patched_modules']))
    print('  declined by name   : %d  (%s)' % (n_declined, ', '.join(sorted(KNOWN_DECLINE))))
    print('  bleed sites scaled : %d  (census %d)' % (n_sites, CENSUS['bleed_sites_reached']))
    if len(files) != CENSUS['modules']:
        bad('SET', '%d modules, census %d' % (len(files), CENSUS['modules']))
    if n_patched != CENSUS['patched_modules']:
        bad('SET', '%d patched, census %d' % (n_patched, CENSUS['patched_modules']))
    if n_declined != len(KNOWN_DECLINE):
        bad('SET', '%d declined, expected %d' % (n_declined, len(KNOWN_DECLINE)))
    if n_sites != CENSUS['bleed_sites_reached']:
        bad('SET', '%d sites, census %d' % (n_sites, CENSUS['bleed_sites_reached']))
    if FAIL:
        for x in FAIL[:20]:
            sys.stderr.write('  FAIL  %s\n' % x)
        sys.stderr.write('  %d failures\n' % len(FAIL))
        sys.exit(1)
    print('  ALL PASS')


if __name__ == '__main__':
    main()
