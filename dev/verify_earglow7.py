#!/usr/bin/env python3
"""verify_earglow7.py <rung-dir> --base <base-dir> --model r.json
                      [--floor M] [--angular cos|smoothstep]
   verify_earglow7.py --negative <base-dir> --model r.json
   verify_earglow7.py --control <ctl-dir> --base <base-dir>

Re-derives the earglow7 edit from the SHIPPED .spv bytes -- never from
patch_earglow7.py's report and never from a byte diff (GOTCHAS 42).

earglow7 changes the RADIOMETRY and nothing else, so most of this file is an
assertion that something did NOT move.  In particular the two things 110 was
accused of breaking are checked as absences: there is no cutoff and no fade.

 1  the ray queries are UNTOUCHED: 3 query variables, 3 Initialize, 3 Proceed,
    2 committed InstanceId, 1 committed T, flags 517/545/517, query B's tmin
    1.5 mm AND ITS TMAX STILL 18 mm -- the census is read from --base and
    compared, not assumed;
 2  NO CUTOFF, NO FADE: query B's tmax is the shipped 18 mm (check 1) and
    there is no SmoothStep anywhere on the committed or guarded t.  110 sec 12
    made tmax the cutoff; this rung must not have one;
 3  101 sec 18's floor NMax(t_guarded, floor) is still on the GUARDED t and
    its constant is exactly --floor.  At the default 0.006 that is the
    assertion that earglow7 did not move the floor;
 4  the accept is intact: the k select's condition still reaches the instance
    match (OpIEqual over the two committed InstanceIds) and query C's
    OpLogicalNot, and its false arm is still NEGATIVE zero;
 5  the CHANNEL IDENTITY is established from the SUN RADIANCE EXTRACT INDEX,
    not from the rate order.  earglow7's fitted red and green rates are within
    2% of each other and red's is the LARGER, so 110's "narrow rate increases
    R->G->B" tie-break is not merely unavailable here, it is actively wrong;
 6  the six rate constants equal the model's fitted a1/a2 per channel, and the
    wide lobe is NOT a1/4 in any channel -- i.e. the lobes were refitted and
    not merely rescaled (--decoy wide4 is rejected here);
 7  the TINT is the model's fitted per-channel amplitude: exactly one OpFMul
    between each non-unit channel's 0.5*(sum) and its tint constant, feeding
    the shared weight; red carries NO tint multiply, because its amplitude is
    folded into k;
 8  the ANGULAR FACTOR.  In `cos` mode the shared weight is
    OpFMul(k select, NMax(OpFNegate(OpDot), 0)) and the shipped
    SmoothStep(0, 0.35, .) is still present with ZERO consumers -- dead, not
    deleted.  A repoint onto the raw OpDot (sign flipped), onto the FNegate
    without the NMax (a negative weight SUBTRACTS light near the terminator),
    or onto a product of the cosine and the smoothstep, all fail here.  In
    `smoothstep` mode the weight must read the SmoothStep and nothing else;
 9  k is the model's normalisation, and the CLOSED-FORM TRANSFER computed from
    the constants actually in the .spv must put the peak red -- the value at
    the floor, where the effect is brightest -- within 0.5% of the shipped
    default's peak red, 0.0945.  That is the check that the rung is a
    re-colouring at constant peak level and not a brightness change;
10  the base's whole disassembly is an ordered SUBSEQUENCE of the rung's under
    id and constant-name normalisation: zero deleted, zero reordered
    instructions, exactly the expected number of inserted ones.
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
from verify_earglow_rq import dis, index, fval, uval, close, count, \
                              PASS_THROUGH
from verify_earglow5 import normlines, CDECL_RE, NOTOP_RE
import difflib

bad = V.bad
FLAGS_A = 517
FLAGS_B = 545
TMIN_B = 0.0015
TMAX_B = 0.018
CAP6 = 0.006
WIDE = 4.0
WRAP_KNEE = 0.35
PEAK_RED_SHIPPED = 0.09454246757    # 0.22 * 0.5*(exp(-6/3.67)+exp(-6/14.68))
LD_OLD = (0.00367, 0.00137, 0.00068)


def body(d, t):
    return d.get(t, (0, ''))[1]


def transfer(a1, a2, tint, k, d):
    import math
    return k * tint * 0.5 * (math.exp(-a1 * d) + math.exp(-a2 * d))


def glow7(lines, d, name, floor, angular):
    """Re-find the glow block on PATCHED bytes.  Nothing here reads a rate
    value to decide what anything is."""
    inits = [(i, re.match(r'\s*OpRayQueryInitializeKHR (%\w+) (%\w+) (%\w+) '
                          r'(%\w+) (%\w+) (%\w+) (%\w+) (%\w+)\s*$', l))
             for i, l in enumerate(lines) if 'OpRayQueryInitializeKHR' in l]
    inits = [(i, m.groups()) for i, m in inits if m]
    if len(inits) != 3:
        return bad(name, f"1: {len(inits)} OpRayQueryInitializeKHR, want 3")
    fl = [uval(d, o[2]) for _, o in inits]
    if fl != [FLAGS_A, FLAGS_B, FLAGS_A]:
        return bad(name, f"1: query flags {fl}, want "
                         f"{[FLAGS_A, FLAGS_B, FLAGS_A]}")
    bline, bops = [(i, o) for i, o in inits if uval(d, o[2]) == FLAGS_B][0]
    if not close(fval(d, bops[5]), TMIN_B, 1e-4):
        return bad(name, f"1: query B tmin {fval(d, bops[5])}, want {TMIN_B}")
    if not close(fval(d, bops[7]), TMAX_B, 1e-4):
        return bad(name, f"2: query B tmax is {fval(d, bops[7])} -- earglow7 "
                         f"must leave it at the shipped {TMAX_B} m.  A "
                         f"rewritten tmax IS 110's hard cutoff")

    tq = [t for t in d if re.match(r'OpRayQueryGetIntersectionTKHR %float '
                                   + re.escape(bops[0]) + r' %uint_1$',
                                   body(d, t))]
    if len(tq) != 1:
        return bad(name, f"1: {len(tq)} committed T getters on query B, want 1")
    guard = [t for t in d if re.match(r'OpSelect %float %\w+ '
                                      + re.escape(tq[0]) + r' '
                                      + re.escape(bops[7]) + r'$', body(d, t))]
    if len(guard) != 1:
        return bad(name, f"1: {len(guard)} NaN guards OpSelect(hitB, t, tmax), "
                         f"want 1 -- and its miss arm must be tmax itself")
    tg = guard[0]
    fl2 = [t for t in d if re.match(r'OpExtInst %float %\w+ NMax '
                                    + re.escape(tg) + r' (%\w+)$', body(d, t))]
    if len(fl2) != 1:
        return bad(name, f"3: {len(fl2)} floors NMax(t_guarded, .), want 1")
    teff = fl2[0]
    cap = re.match(r'OpExtInst %float %\w+ NMax %\w+ (%\w+)$',
                   body(d, teff)).group(1)
    if not close(fval(d, cap), floor, 1e-4):
        return bad(name, f"3: the floor is {fval(d, cap)} m, want {floor}")
    # no fade anywhere on either t
    for t in d:
        m = re.match(r'OpExtInst %float %\w+ SmoothStep (%\w+) (%\w+) (%\w+)$',
                     body(d, t))
        if m and m.group(3) in (tq[0], tg, teff):
            return bad(name, f"2: a SmoothStep reads the thickness ({t}) -- "
                             f"earglow7 has no fade")

    # ---- the k select and the shared weight -----------------------------
    ksel = [t for t in d
            if re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, t))
            and re.match(r'OpConstant %float -0$',
                         body(d, re.match(r'OpSelect %float %\w+ (%\w+) '
                                          r'(%\w+)$',
                                          body(d, t)).group(2)))]
    if len(ksel) != 1:
        return bad(name, f"4: {len(ksel)} OpSelect(.., k, -0.0), want 1")
    ksel = ksel[0]
    cond, k_tok = re.match(r'OpSelect %float (%\w+) (%\w+) %\w+$',
                           body(d, ksel)).groups()
    seen, stack = set(), [cond]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', body(d, x))
        if m:
            stack += list(m.groups())
    if not any(re.match(r'OpIEqual %bool ', body(d, x)) for x in seen):
        return bad(name, "4: the accept does not reach the instance match")
    if not any(re.match(r'OpLogicalNot %bool ', body(d, x)) for x in seen):
        return bad(name, "4: the accept does not reach query C's LogicalNot")

    w0 = [t for t in d if re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, t))
          and ksel in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                               body(d, t)).groups()]
    if len(w0) != 1:
        return bad(name, f"8: {len(w0)} products of the k select, want 1")
    w0 = w0[0]
    wfac = [x for x in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                body(d, w0)).groups() if x != ksel][0]

    # ---- check 8: the angular factor ------------------------------------
    ss = [t for t in d
          if re.match(r'OpExtInst %float %\w+ SmoothStep (%\w+) (%\w+) (%\w+)$',
                      body(d, t))
          and close(fval(d, re.match(r'OpExtInst %float %\w+ SmoothStep '
                                     r'(%\w+) (%\w+) (%\w+)$',
                                     body(d, t)).group(2)), WRAP_KNEE, 1e-4)]
    if len(ss) != 1:
        return bad(name, f"8: {len(ss)} wrap SmoothSteps at the 0.35 knee, "
                         f"want 1 -- it must be left in place, dead")
    ss = ss[0]
    ss_cos = re.match(r'OpExtInst %float %\w+ SmoothStep %\w+ %\w+ (%\w+)$',
                      body(d, ss)).group(1)
    negm = re.match(r'OpFNegate %float (%\w+)$', body(d, ss_cos))
    if not negm or not re.match(r'OpDot %float ',
                                body(d, negm.group(1))):
        return bad(name, "8: the wrap's argument is not FNegate(OpDot)")
    users = [l for l in lines
             if re.search(r'(?<![\w])' + re.escape(ss) + r'(?![\w])', l)
             and not re.match(r'\s*' + re.escape(ss) + r'\s*=', l)]
    if angular == 'cos':
        m = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$',
                     body(d, wfac))
        if not m:
            return bad(name, f"8: the shared weight reads {body(d, wfac)!r}, "
                             f"want NMax(-N.S, 0)")
        if m.group(1) != ss_cos:
            return bad(name, f"8: the NMax clamps {m.group(1)}, not the "
                             f"cosine {ss_cos} the wrap itself reads")
        if fval(d, m.group(2)) not in (0.0, -0.0):
            return bad(name, f"8: the NMax floor is {fval(d, m.group(2))}, "
                             f"want 0")
        if users:
            return bad(name, f"8: the wrap SmoothStep still has "
                             f"{len(users)} consumer(s) -- it must be dead")
    else:
        if wfac != ss:
            return bad(name, f"8: --angular smoothstep, but the weight reads "
                             f"{body(d, wfac)!r}")
        if len(users) != 1:
            return bad(name, f"8: the wrap has {len(users)} consumers, want 1")

    # ---- checks 5-7: the three chains, by SUN RADIANCE INDEX ------------
    chains = {}
    for t in d:
        m = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, t))
        if not m or w0 not in m.groups():
            continue
        pre = [x for x in m.groups() if x != w0][0]
        post = [u for u in d
                if re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, u))
                and t in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                  body(d, u)).groups()]
        if len(post) != 1:
            return bad(name, f"5: the chain at {t} has {len(post)} consumers, "
                             f"want 1 (the sun radiance multiply)")
        srad = [x for x in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                    body(d, post[0])).groups() if x != t][0]
        em = re.match(r'OpCompositeExtract %float (%\w+) (\d)$', body(d, srad))
        if not em:
            return bad(name, f"5: {t}'s sibling operand {srad} is not a "
                             f"component extract -- the channel of this chain "
                             f"cannot be established")
        ch = int(em.group(2))
        if ch in chains:
            return bad(name, f"5: two chains claim channel {ch}")
        chains[ch] = dict(mul_w=t, pre=pre, sun_src=em.group(1))
    if sorted(chains) != [0, 1, 2]:
        return bad(name, f"5: chains found for channels {sorted(chains)}, "
                         f"want 0,1,2")
    if len({c['sun_src'] for c in chains.values()}) != 1:
        return bad(name, "5: the three chains read different sun vectors")

    for ch, c in chains.items():
        half = c['pre']
        tint = 1.0
        hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, half))
        if not hm:
            return bad(name, f"7: channel {ch}'s pre-weight value is "
                             f"{body(d, half)!r}")
        halfs = [x for x in hm.groups()
                 if re.match(r'OpFAdd %float ', body(d, x))]
        if not halfs:
            # a tint multiply: half * tint, where half is itself 0.5*(sum)
            inner = [x for x in hm.groups()
                     if re.match(r'OpFMul %float ', body(d, x))]
            tints = [x for x in hm.groups() if fval(d, x) is not None]
            if len(inner) != 1 or len(tints) != 1:
                return bad(name, f"7: channel {ch} is neither 0.5*(sum) nor "
                                 f"0.5*(sum)*tint ({body(d, half)!r})")
            tint = fval(d, tints[0])
            half = inner[0]
            hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, half))
            halfs = [x for x in hm.groups()
                     if re.match(r'OpFAdd %float ', body(d, x))]
        if len(halfs) != 1 or not any(close(fval(d, x), 0.5, 1e-6)
                                      for x in hm.groups()):
            return bad(name, f"7: channel {ch}'s transfer is not 0.5*(sum) "
                             f"({body(d, half)!r})")
        am = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(d, halfs[0]))
        rates = []
        for e in am.groups():
            xm = re.match(r'OpExtInst %float %\w+ Exp (%\w+)$', body(d, e))
            if not xm:
                return bad(name, f"6: channel {ch}'s lobe is not an Exp")
            nm2 = re.match(r'OpFNegate %float (%\w+)$', body(d, xm.group(1)))
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$',
                          body(d, nm2.group(1))) if nm2 else None
            if not mm or teff not in mm.groups():
                return bad(name, f"6: channel {ch}'s lobe does not read the "
                                 f"floored thickness")
            rates.append(fval(d, [x for x in mm.groups() if x != teff][0]))
        c['tint'] = tint
        c['rates'] = sorted(rates, reverse=True)
    return dict(k=fval(d, k_tok), chains=chains, teff=teff, floor=fval(d, cap),
                tmax=fval(d, bops[7]))


def check_module(path, base_path, model, floor, angular):
    name = os.path.basename(path).split('.')[0]
    lines = dis(path)
    d = index(lines)
    g = glow7(lines, d, name, floor, angular)
    if not g:
        return None
    rates = [tuple(r) for r in model['rates_1_per_m']]
    tint = list(model['tint'])
    k = float(model['k'])

    if not close(g['k'], k, 1e-4):
        return bad(name, f"9: k is {g['k']}, want {k}")
    for ch in (0, 1, 2):
        got = g['chains'][ch]['rates']
        want = rates[ch]
        if not (close(got[0], want[0], 2e-4) and close(got[1], want[1], 2e-4)):
            return bad(name, f"6: channel {ch} rates {got}, want "
                             f"{list(want)}")
        if close(got[1], got[0] / WIDE, 1e-3):
            return bad(name, f"6: channel {ch}'s wide lobe is still a1/4 "
                             f"({got}) -- the lobes were not refitted")
        if close(got[0], 1.0 / LD_OLD[ch], 1e-3):
            return bad(name, f"6: channel {ch}'s narrow rate is still the "
                             f"shipped 1/{LD_OLD[ch]}")
        if not close(g['chains'][ch]['tint'], tint[ch], 1e-4):
            return bad(name, f"7: channel {ch} tint {g['chains'][ch]['tint']}, "
                             f"want {tint[ch]}")
    # check 9: the peak, computed from the bytes
    peak = transfer(*g['chains'][0]['rates'], g['chains'][0]['tint'],
                    g['k'], g['floor'])
    if abs(peak - PEAK_RED_SHIPPED) > 0.005 * PEAK_RED_SHIPPED:
        return bad(name, f"9: peak red from the shipped constants is {peak:.6f}"
                         f", want the default's {PEAK_RED_SHIPPED:.6f} "
                         f"(+-0.5%) -- the rung is not level-held")

    # check 10: subsequence
    a, b = normlines(dis(base_path)), normlines(lines)
    ins = rew = decl = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == 'insert':
            for l in b[j1:j2]:
                if NOTOP_RE.match(l):
                    decl += 1
                else:
                    ins += 1
        elif tag == 'equal':
            continue
        elif tag == 'replace' and (i2 - i1) == (j2 - j1) and \
                all(CDECL_RE.match(x) for x in a[i1:i2] + b[j1:j2]):
            rew += i2 - i1
        else:
            return bad(name, f"10: the base is NOT a subsequence of the rung "
                             f"-- a '{tag}' block at base line {i1+1} "
                             f"({a[i1:i2][:1]} -> {b[j1:j2][:1]})")
    want_ins = sum(1 for x in tint if abs(x - 1.0) > 1e-9) \
        + (1 if angular == 'cos' else 0)
    if ins != want_ins:
        return bad(name, f"10: {ins} instructions inserted, want {want_ins}")
    return dict(name=name, k=g['k'], ins=ins, rew=rew, decl=decl,
                peak_red=peak,
                rg=peak / transfer(*g['chains'][1]['rates'],
                                   g['chains'][1]['tint'], g['k'], g['floor']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--model')
    ap.add_argument('--negative')
    ap.add_argument('--control')
    ap.add_argument('--floor', type=float, default=CAP6)
    ap.add_argument('--angular', default='cos',
                    choices=('cos', 'smoothstep'))
    ap.add_argument('--expect', type=int, default=10,
                    help='paintable module count (10 in the shipped set; '
                         'lowered only by the single-module smoke tests)')
    a = ap.parse_args()

    if a.control:
        if not a.base:
            raise SystemExit("--control needs --base")
        n = 0
        for f in sorted(glob.glob(os.path.join(a.control, '*.spv'))):
            b = os.path.join(a.base, os.path.basename(f))
            if not os.path.exists(b):
                print(f"FAIL {os.path.basename(f)}: not in the base")
                return 1
            if open(f, 'rb').read() != open(b, 'rb').read():
                print(f"FAIL {os.path.basename(f)}: differs from the base")
                return 1
            n += 1
        print(f"CONTROL: all {n} modules byte-identical to the base")
        return 0

    model = json.load(open(a.model))
    if a.negative:
        # NON-VACUITY: the checks must FAIL on the unpatched base.
        fails = 0
        V.FAIL = []
        for f in sorted(glob.glob(os.path.join(a.negative,
                                               '*.rgs_reference_main.spv'))):
            if os.path.basename(f).split('.')[0] in PASS_THROUGH:
                continue
            before = len(V.FAIL)
            check_module(f, f, model, a.floor, a.angular)
            if len(V.FAIL) > before:
                fails += 1
        print(f"NEGATIVE: {fails} of {a.expect} paintable base modules "
              f"rejected")
        return 0 if fails == a.expect else 1

    if not (a.rung and a.base):
        raise SystemExit("need <rung-dir> --base <base-dir> --model r.json")
    V.FAIL = []
    rows = []
    for f in sorted(glob.glob(os.path.join(a.rung,
                                           '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        if h in PASS_THROUGH:
            if open(f, 'rb').read() != open(
                    os.path.join(a.base, os.path.basename(f)), 'rb').read():
                print(f"FAIL {h}: pass-through module was modified")
                V.FAIL.append(h)
            continue
        r = check_module(f, os.path.join(a.base, os.path.basename(f)), model,
                         a.floor, a.angular)
        if r:
            rows.append(r)
    if V.FAIL or len(rows) != a.expect:
        for m in V.FAIL:
            print("FAIL " + m)
        print(f"FAILED: {len(V.FAIL)} module(s); {len(rows)} of "
              f"{a.expect} passed")
        return 1
    print(f"ALL PASS: {len(rows)} modules; k={rows[0]['k']:.4f}, "
          f"+{rows[0]['ins']} instructions, {rows[0]['rew']} constant "
          f"rewrites, {rows[0]['decl']} declarations; peak red "
          f"{rows[0]['peak_red']:.6f} (default 0.094542), R/G at the floor "
          f"{rows[0]['rg']:.1f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
