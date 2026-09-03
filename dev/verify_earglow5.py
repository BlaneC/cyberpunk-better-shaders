#!/usr/bin/env python3
"""verify_earglow5.py <rung-dir> --base <base-dir> --k K --cut M
                      --mode none|tint|rate [--floor M] [--tint R,G,B]
                      [--no-cutoff]
   verify_earglow5.py <rung-dir> --vs-centre <centre-dir> --axis k|cut|tint|cutoff
   verify_earglow5.py --negative <base-dir>
   verify_earglow5.py --control <ctl-dir> --base <base-dir>

Re-derives the ear-glow v5 edit from the SHIPPED .spv bytes -- never from
patch_earglow5.py's report and never from a byte diff (GOTCHAS 42).

The claim this file exists to prove is narrow and unusual: **the ray queries
did not change.**  v5 rewrites constants and adds at most six instructions, so
almost every check below is an assertion that something is STILL THERE and
STILL THE SAME, and only checks 5-7 look at what moved.

  1  the query is UNTOUCHED: 3 ray query variables, 3 Initialize, 3 Proceed,
     2 committed InstanceId, 1 committed T, 0 forbidden getters -- identical
     to the base's census, which is read from --base and compared, not
     assumed;
  2  query B still carries flags 545 bit by bit and tmin 0.0015; its tmax is
     now t_cut, and the NaN guard's miss arm is the SAME id, so "missed" and
     "at the cutoff" cannot disagree;
  3  101 sec 18's floor NMax(t, floor) is still on the guarded t and its
     constant is exactly --floor.  With the default --floor 0.006 that is the
     assertion that v5 did NOT move the floor.  With a -floor rung's value it
     is stronger: the shared 0.006 constant must STILL EXIST, must NOT be the
     one the NMax reads (an in-place rewrite of it would have changed the
     module's own OpTraceRayKHR tmaxes), and must still be read by at least
     one OpTraceRayKHR.  Only the earglow's own NMax operand may have moved;
  4  the instance match (OpIEqual over the two committed InstanceId results)
     and query C's OpLogicalNot are still reached by the k select's condition;
  5  (a) the k select's true arm is k_new and its false arm is NEGATIVE zero;
  6  (b) the cutoff fade: SmoothStep(t_cut - 1 mm, t_cut, THE GUARDED t) ->
     OpFSub(1, s) -> OpFMul(k select, w), and that product -- not the raw k
     select -- is what multiplies the wrap smoothstep.  Reading the FLOORED
     t instead is rejected (at --cut 0.006 it is the constant 0.006 and the
     rung would be black); so is a missing OpFSub (--decoy invfade), which
     would light only the pixels past the cutoff;
  7  (c) colour.  tint: exactly three OpFMul between each channel's 0.5*(sum)
     and the shared weight, carrying the tint triple in R,G,B chain order,
     where the channel order is established from the RATES (1/ld strictly
     increasing R->G->B), not from line order.  rate: the four G/B rate
     constants equal 1/ld_new and 1/(4*ld_new), and there is NO tint multiply
     at all;
  9  --vs-centre: a LADDER check, not a base check.  110 sec 14 builds seven
     rungs around one centre and claims each differs from it on ONE AXIS.
     This re-derives (k, t_cut, floor, tint, fade-present) from BOTH modules
     and demands that exactly the named axis's field differs and every other
     one is equal -- and, separately, that the two INSTRUCTION streams are
     identical under id and constant-name normalisation (so a value moved and
     nothing else did).  The `cutoff` axis is the one exception and is checked
     harder: the streams must differ by exactly THREE deleted lines and those
     three must be the SmoothStep, the OpFSub and the OpFMul of the fade.

  8  and with --base, the base's whole disassembly is an ordered SUBSEQUENCE
     of the rung's under id renumbering -- zero deleted, zero reordered
     instructions -- and the added-line count is exactly what the mode says.
"""
import argparse, difflib, glob, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
from verify_earglow_rq import (dis, index, fval, uval, close, count,
                               PASS_THROUGH, GETTERS_OTHER)

bad = V.bad
GET_ID = 'OpRayQueryGetIntersectionInstanceIdKHR'
T_GET = 'OpRayQueryGetIntersectionTKHR'
TYPE_GET = 'OpRayQueryGetIntersectionTypeKHR'
FLAGS_B = 1 | 32 | 512               # 545
TMIN_B = 0.0015
CAP6 = 0.006
FADE_W = 0.001
WIDE = 4.0
LD_OLD = (0.00367, 0.00137, 0.00068)
LD_RATE = (0.00367, 0.00070, 0.00035)
TINT = (1.0, 0.40, 0.22)
K_OLD = 0.22
TMAX_OLD = 0.018
NUM = re.compile(r'%\d+')
# spirv-dis derives a constant's FRIENDLY NAME from its value, and it
# disambiguates a collision with a `_0` suffix.  Rewriting query B's tmax to
# 0.008 in a module that already had a 0.008 therefore RENAMES the unrelated
# one -- a disassembler artifact that looks like an edit.  Constant names are
# flattened here so check 8 sees opcodes, arity and literals; the VALUES are
# checked by name-independent means in checks 2, 3, 5, 6 and 7.
KNAME = re.compile(r'%(?:float|half|double|uint|int|bool|v\d+(?:float|half|uint|int|bool))_\S*')


CDECL_RE = re.compile(r'^%K = OpConstant %float [-+0-9.eE]+$')
NOTOP_RE = re.compile(r'^(?:%K = OpConstant |%# = OpString |'
                      r'Op(?:Source|ModuleProcessed|Name|MemberName|'
                      r'Decorate|MemberDecorate)\b)')


def body(d, t):
    return d.get(t, (0, ''))[1]


def fv(d, t, want, rel=1e-4):
    return close(fval(d, t), want, rel)


def negzero(d, t):
    return re.match(r'OpConstant %float -0$', body(d, t)) is not None


def normlines(lines):
    return [KNAME.sub('%K', NUM.sub('%#', l.strip())) for l in lines
            if l.strip() and not l.startswith(';')]


def subsequence(base_path, rung_path, name):
    a, b = normlines(dis(base_path)), normlines(dis(rung_path))
    # v5 REWRITES constant declarations in place, so a `replace` block whose
    # every line on BOTH sides is an `OpConstant %float` declaration is the
    # edit itself and is counted, not rejected. Anything else -- a replaced
    # instruction, a deleted line, a reordering -- is a hard failure.
    CDECL = CDECL_RE
    # An inserted line is either a new CONSTANT / debug line (how many depends
    # on what the module already happened to declare) or a real INSTRUCTION
    # in the raygen body (fixed by the mode, and the number that matters).
    NOTOP = NOTOP_RE
    ins = rew = decl = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == 'insert':
            for l in b[j1:j2]:
                if NOTOP.match(l):
                    decl += 1
                else:
                    ins += 1
        elif tag == 'equal':
            continue
        elif tag == 'replace' and (i2 - i1) == (j2 - j1) and \
                all(CDECL.match(x) for x in a[i1:i2] + b[j1:j2]):
            rew += i2 - i1
        else:
            bad(name, f"8: the base is NOT a subsequence of the rung -- a "
                      f"'{tag}' block at base line {i1+1} "
                      f"({a[i1:i2][:1]} -> {b[j1:j2][:1]})")
            return None
    return ins, rew, decl


def glow(lines, d, name, tag):
    """The same shape re-found here as in the patcher, written from the
    SPIR-V rather than imported, so agreement is evidence not tautology."""
    binit = []
    for l in lines:
        m = re.match(r'\s*OpRayQueryInitializeKHR (%\w+) (%\w+) (%\w+) (%\w+) '
                     r'(%\w+) (%\w+) (%\w+) (%\w+)\s*$', l)
        if m and uval(d, m.group(3)) == FLAGS_B:
            binit.append(list(m.groups()))
    if len(binit) != 1:
        bad(name, f"{tag}: {len(binit)} queries with flags {FLAGS_B}, want 1")
        return None
    b = binit[0]
    tq = [t for t in d if re.match(T_GET + r' %float ' + re.escape(b[0])
                                   + r' %uint_1$', body(d, t))]
    guard = [t for t in d
             if tq and re.match(r'OpSelect %float %\w+ ' + re.escape(tq[0])
                                + r' ' + re.escape(b[7]) + r'$', body(d, t))]
    if len(tq) != 1 or len(guard) != 1:
        bad(name, f"{tag}: {len(tq)} committed T / {len(guard)} miss guards, "
                  f"want 1 / 1 (and the guard's miss arm must be query B's "
                  f"own tmax id)")
        return None
    floor = [t for t in d
             if re.match(r'OpExtInst %float %\w+ NMax ' + re.escape(guard[0])
                         + r' (%\w+)$', body(d, t))]
    if len(floor) != 1:
        bad(name, f"{tag}: {len(floor)} NMax floors on the guarded t, want 1")
        return None
    cap = re.match(r'OpExtInst %float %\w+ NMax %\w+ (%\w+)$',
                   body(d, floor[0])).group(1)
    ksel = [t for t in d
            if re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, t))
            and negzero(d, re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$',
                                    body(d, t)).group(2))
            and fval(d, re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$',
                                 body(d, t)).group(1)) is not None]
    if len(ksel) != 1:
        bad(name, f"{tag}: {len(ksel)} OpSelect(cond, k, -0.0), want 1")
        return None
    ksel = ksel[0]
    wrap = [t for t in d
            if re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, t))
            and any(re.match(r'OpExtInst %float %\w+ SmoothStep ', body(d, x))
                    for x in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                      body(d, t)).groups())]
    wrap = [t for t in wrap
            if any(re.match(r'OpFMul %float ', body(d, x))
                   or x == ksel
                   for x in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                     body(d, t)).groups())]
    if len(wrap) != 1:
        bad(name, f"{tag}: {len(wrap)} products of a smoothstep and the k "
                  f"chain, want 1 (the wrap)")
        return None
    w0 = wrap[0]
    chains = []
    for t in d:
        m = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, t))
        if not m or w0 not in m.groups():
            continue
        pre = [x for x in m.groups() if x != w0]
        if not pre:
            continue
        pre = pre[0]
        tint = None
        hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, pre))
        if hm and fval(d, hm.group(2)) is not None and \
                re.match(r'OpFMul %float ', body(d, hm.group(1))):
            tint, pre = hm.group(2), hm.group(1)
        hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, pre))
        if not hm:
            continue
        s = [x for x in hm.groups() if fv(d, x, 0.5, 1e-6)]
        add = [x for x in hm.groups() if re.match(r'OpFAdd %float ', body(d, x))]
        if not s or not add:
            continue
        am = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(d, add[0]))
        rates = []
        for e in am.groups():
            em = re.match(r'OpExtInst %float %\w+ Exp (%\w+)$', body(d, e))
            nm = em and re.match(r'OpFNegate %float (%\w+)$', body(d, em.group(1)))
            mm = nm and re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                 body(d, nm.group(1)))
            if not mm or floor[0] not in mm.groups():
                break
            rates.append([x for x in mm.groups() if x != floor[0]][0])
        if len(rates) != 2:
            continue
        vs = sorted(fval(d, r) or 0.0 for r in rates)
        chains.append({'tint': tint, 'wide': vs[0], 'narrow': vs[1],
                       'line': d[t][0]})
    if len(chains) != 3:
        bad(name, f"{tag}: {len(chains)} transfer chains, want 3")
        return None
    chains.sort(key=lambda c: c['narrow'])
    return dict(b=b, tq=tq[0], guard=guard[0], floor=floor[0], cap=cap,
                ksel=ksel, w0=w0, chains=chains)


def check_module(path, base_path, mode, k, cut, floor=CAP6, tint=TINT,
                 cutoff=True):
    name = os.path.basename(path)
    lines = dis(path)
    d = index(lines)

    # ---- 1. the query is UNTOUCHED ----------------------------------------
    census = {}
    for op, want in ((f'{TYPE_GET} %uint', 3), (f'{GET_ID} %uint', 2),
                     (f'{T_GET} %float', 1), ('OpRayQueryProceedKHR', 3),
                     ('OpRayQueryInitializeKHR', 3)):
        census[op] = count(lines, op)
        if census[op] != want:
            bad(name, f"1: {census[op]} {op.split()[0]}, want {want} -- v5 "
                      f"must not add or remove a ray query")
    for g in GETTERS_OTHER:
        if g != GET_ID and count(lines, g):
            bad(name, f"1: forbidden getter {g}")
    if base_path:
        bl = dis(base_path)
        for op in census:
            if count(bl, op) != census[op]:
                bad(name, f"1: {op.split()[0]} count differs from the base "
                          f"({count(bl, op)} -> {census[op]})")

    g = glow(lines, d, name, '2')
    if g is None:
        return None

    # ---- 2. query B: flags and the cutoff ---------------------------------
    fb = uval(d, g['b'][2])
    if fb != FLAGS_B:
        bad(name, f"2: query B flags {fb}, want {FLAGS_B}")
    else:
        for bit, nm in ((1, 'Opaque'), (32, 'CullFrontFacingTriangles'),
                        (512, 'SkipAABBs')):
            if not fb & bit:
                bad(name, f"2: query B lost the {nm} bit")
        if fb & 16:
            bad(name, "2: query B culls BACK faces")
    if not fv(d, g['b'][5], TMIN_B):
        bad(name, f"2: query B tmin {fval(d, g['b'][5])}, want {TMIN_B}")
    if not fv(d, g['b'][7], cut):
        bad(name, f"2: query B tmax "
                  f"({'THE CUTOFF' if cutoff else 'which this rung leaves at the shipped value'})"
                  f" is {fval(d, g['b'][7])}, want {cut}")

    # ---- 3. the thickness floor -------------------------------------------
    if not fv(d, g['cap'], floor, 1e-5):
        bad(name, f"3: the thickness floor is {fval(d, g['cap'])} m, want "
                  f"{floor}" + ("" if abs(floor - CAP6) > 1e-9 else
                                " -- this rung must not move 101 sec 18's floor"))
    if abs(floor - CAP6) > 1e-9:
        # A -floor rung must have moved ONE operand and nothing else. The
        # 0.006 constant is shared with the module's own OpTraceRayKHR tmaxes
        # and OpFOrdLessThan tests, so an in-place rewrite of it -- which is
        # the obvious, wrong way to build this rung -- is caught here.
        shared = [t for t in d if fv(d, t, CAP6, 1e-5)
                  and re.match(r'OpConstant %float ', body(d, t))]
        if len(shared) != 1:
            bad(name, f"3: {len(shared)} constants still equal to {CAP6}, "
                      f"want 1 -- the shared floor constant was REWRITTEN in "
                      f"place and every OpTraceRayKHR that read it moved too")
        else:
            tok = shared[0]
            if tok == g['cap']:
                bad(name, f"3: the floor reads {tok}, the shared {CAP6} "
                          f"constant -- the repoint did not happen")
            pat = re.compile(r'(?<![\w])' + re.escape(tok) + r'(?![\w])')
            users = [l for l in lines if pat.search(l)
                     and not re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant', l)]
            if len(users) < 12:
                bad(name, f"3: only {len(users)} consumers of the shared "
                          f"{CAP6} constant survive, want the base's 12")
            if not any('OpTraceRayKHR' in l for l in users):
                bad(name, f"3: no OpTraceRayKHR still reads the shared "
                          f"{CAP6} constant")
        if not any(re.match(r'\s*%\w+ = OpConstant %float ', body(d, g['cap']) and '') for _ in ()):
            pass

    # ---- 4. the match and query C survive ---------------------------------
    ids = [m.group(1) for m in
           (re.match(r'\s*(%\w+) = ' + GET_ID + r' %uint (%\w+) %uint_1\s*$', l)
            for l in lines) if m]
    eqs = [l for l in lines
           if re.match(r'\s*%\w+ = OpIEqual %bool (%\w+) (%\w+)\s*$', l)
           and set(re.match(r'\s*%\w+ = OpIEqual %bool (%\w+) (%\w+)\s*$',
                            l).groups()) == set(ids)]
    if len(ids) != 2 or len(eqs) != 1:
        bad(name, f"4: {len(ids)} InstanceId reads / {len(eqs)} OpIEqual over "
                  f"them, want 2 / 1 -- the instance match is gone")
    if not any(re.match(r'\s*%\w+ = OpLogicalNot %bool ', l) for l in lines):
        bad(name, "4: query C's OpLogicalNot is gone")

    # ---- 5. brightness ----------------------------------------------------
    km = re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, g['ksel']))
    if not fv(d, km.group(1), k, 1e-4):
        bad(name, f"5: k is {fval(d, km.group(1))}, want {k}")
    if not negzero(d, km.group(2)):
        bad(name, "5: the k select's false arm is not NEGATIVE zero")

    # ---- 6. the cutoff fade ----------------------------------------------
    wm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, g['w0']))
    kchain = [x for x in wm.groups()
              if not re.match(r'OpExtInst %float %\w+ SmoothStep ', body(d, x))]
    if not kchain:
        bad(name, "6: the wrap product has no k side")
        return None
    kc = kchain[0]
    if not cutoff:
        # the -cutoff rung: there must be NO fade at all, and query B's tmax
        # must still be the shipped 18 mm (checked above), so the transfer's
        # own decay is the only falloff there is.
        if kc != g['ksel']:
            bad(name, "6: --no-cutoff, but a fade is spliced in anyway -- "
                      "this rung must carry the k select straight into the "
                      "wrap product")
        return _finish(name, path, base_path, d, g, mode, tint, floor, cut,
                       k, cutoff)
    if kc == g['ksel']:
        bad(name, "6: NO cutoff fade -- the k select reaches the wrap "
                  "directly, so the cutoff is a hard edge at t_cut")
        return None
    fm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, kc))
    if not fm or g['ksel'] not in fm.groups():
        bad(name, f"6: the fade is not a product of the k select ({body(d, kc)!r})")
        return None
    wtok = [x for x in fm.groups() if x != g['ksel']][0]
    sm = re.match(r'OpFSub %float (%\w+) (%\w+)$', body(d, wtok))
    if not sm or not fv(d, sm.group(1), 1.0, 1e-6):
        bad(name, "6: the fade weight is not 1 - SmoothStep(...) -- an "
                  "un-negated smoothstep lights ONLY the pixels past the cut")
        return None
    ss = re.match(r'OpExtInst %float %\w+ SmoothStep (%\w+) (%\w+) (%\w+)$',
                  body(d, sm.group(2)))
    if not ss:
        bad(name, "6: the fade's inner term is not a SmoothStep")
        return None
    if not fv(d, ss.group(1), cut - FADE_W) or not fv(d, ss.group(2), cut):
        bad(name, f"6: the fade edges are "
                  f"[{fval(d, ss.group(1))}, {fval(d, ss.group(2))}], want "
                  f"[{cut - FADE_W}, {cut}]")
    if ss.group(3) == g['floor']:
        bad(name, "6: the fade reads the FLOORED t. At --cut 0.006 that is "
                  "the constant 0.006 and the whole rung would be black")
    elif ss.group(3) != g['guard']:
        bad(name, f"6: the fade reads {body(d, ss.group(3))!r}, want the "
                  f"guarded t")

    return _finish(name, path, base_path, d, g, mode, tint, floor, cut, k,
                   cutoff)


def _finish(name, path, base_path, d, g, mode, tint, floor, cut, k, cutoff):
    # ---- 7. colour --------------------------------------------------------
    tints = [c['tint'] for c in g['chains']]
    got_ld = [1.0 / c['narrow'] if c['narrow'] else 0.0 for c in g['chains']]
    if mode == 'tint':
        if any(t is None for t in tints):
            bad(name, f"7: {sum(t is None for t in tints)} channels carry no "
                      f"tint multiply, want 0")
        else:
            for i, (t, want) in enumerate(zip(tints, tint)):
                if not fv(d, t, want, 1e-4):
                    bad(name, f"7: chan {i} tint is {fval(d, t)}, want {want}")
        for i, ld in enumerate(got_ld):
            if not close(ld, LD_OLD[i], 1e-3):
                bad(name, f"7: chan {i} ld is {ld}, want {LD_OLD[i]} "
                          f"unchanged in tint mode")
    elif mode == 'rate':
        if any(t is not None for t in tints):
            bad(name, "7: the rate rung carries a tint multiply -- (c1) and "
                      "(c2) must never be blended")
        for i, ld in enumerate(got_ld):
            if not close(ld, LD_RATE[i], 1e-3):
                bad(name, f"7: chan {i} ld is {ld} m, want {LD_RATE[i]}")
            if not close(g['chains'][i]['wide'],
                         1.0 / (WIDE * LD_RATE[i]), 1e-3):
                bad(name, f"7: chan {i} wide rate is "
                          f"{g['chains'][i]['wide']}, want "
                          f"1/({WIDE}*{LD_RATE[i]})")
    else:
        if any(t is not None for t in tints):
            bad(name, "7: mode none carries a tint multiply")

    # ---- 8. nothing was deleted ------------------------------------------
    sub = subsequence(base_path, path, name) if base_path else None
    ins = rew = None
    if sub is not None:
        ins, rew, decl = sub
        # COMPUTED, not tabulated: 3 instructions for the fade (only when
        # there is a cutoff) and 3 for the tint; one rewritten declaration per
        # constant whose VALUE actually moved, which is why earglow6-k22 (k
        # back at the shipped 0.22) legitimately shows one rewrite, not two.
        want_ins = (3 if cutoff else 0) + (3 if mode == 'tint' else 0)
        want_rew = ((0 if close(k, K_OLD, 1e-4) else 1)
                    + (1 if cutoff and not close(cut, TMAX_OLD, 1e-4) else 0)
                    + (4 if mode == 'rate' else 0))
        if ins != want_ins:
            bad(name, f"8: {ins} inserted lines, want {want_ins} "
                      f"(mode={mode}, cutoff={cutoff})")
        if rew != want_rew:
            bad(name, f"8: {rew} rewritten constant declarations, want "
                      f"{want_rew} (k {'unchanged' if close(k, K_OLD, 1e-4) else 'moved'}, "
                      f"tmax {'moved' if cutoff and not close(cut, TMAX_OLD, 1e-4) else 'unchanged'})")
        # the fade's two edges; the G and B tint; and, on a floor rung, the
        # new floor constant. Reuse of a value the module already declared can
        # only make this smaller, so it is an upper bound.
        max_decl = ((2 if cutoff else 0)
                    + (sum(1 for t in tint[1:] if abs(t - 1.0) > 1e-9)
                       if mode == 'tint' else 0)
                    + (0 if abs(floor - CAP6) < 1e-9 else 1))
        if decl > max_decl:
            bad(name, f"8: {decl} added declarations, want at most "
                      f"{max_decl}")
    return {'inserted': ins, 'rewritten': rew, 'ld': got_ld, 'floor': fval(d, g['cap']),
            'tint': [fval(d, t) if t else None for t in tints]}


# --------------------------------------------------------------------------
# 9. the LADDER check: one axis between a rung and the centre
AXIS_FIELD = {'k': {'k'}, 'cut': {'cut'}, 'tint': {'tint'}, 'cutoff': {'cut'}}
FADE_OPS = (r'^%# = OpExtInst %float %# SmoothStep %K %K %#$',
            r'^%# = OpFSub %float %K %#$',
            r'^%# = OpFMul %float %# %#$')


def summarise(path, name):
    """(k, t_cut, floor, tint, fade?) plus the normalised INSTRUCTION stream,
    all re-derived structurally from one module."""
    lines = dis(path)
    d = index(lines)
    g = glow(lines, d, name, '9')
    if g is None:
        return None
    km = re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, g['ksel']))
    wm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(d, g['w0']))
    kchain = [x for x in wm.groups()
              if not re.match(r'OpExtInst %float %\w+ SmoothStep ', body(d, x))]
    return dict(
        k=fval(d, km.group(1)), cut=fval(d, g['b'][7]), floor=fval(d, g['cap']),
        tint=tuple(fval(d, c['tint']) if c['tint'] else None
                   for c in g['chains']),
        fade=bool(kchain) and kchain[0] != g['ksel'],
        ops=[l for l in normlines(lines) if not NOTOP_RE.match(l)])


def _same(a, b):
    if isinstance(a, tuple) or isinstance(b, tuple):
        return (a is not None and b is not None and len(a) == len(b)
                and all(_same(x, y) for x, y in zip(a, b)))
    if a is None or b is None:
        return a is b
    return close(a, b, 1e-4)


def pairwise(rung_dir, centre_dir, axis):
    """110 sec 14's ladder claim: every rung differs from the CENTRE on
    exactly one axis. Not a byte diff -- both modules are re-derived and the
    four tuning fields are compared, then the instruction streams are compared
    under id and constant-name normalisation, so a moved VALUE is invisible in
    the stream and a moved INSTRUCTION is not."""
    want = AXIS_FIELD[axis]
    n = 0
    for p in sorted(glob.glob(os.path.join(rung_dir,
                                           '*.rgs_reference_main.spv'))):
        nm = os.path.basename(p)
        if nm.split('.')[0] in PASS_THROUGH:
            continue
        c = os.path.join(centre_dir, nm)
        if not os.path.exists(c):
            bad(nm, "9: no centre counterpart")
            continue
        R, C = summarise(p, nm), summarise(c, nm + ' (centre)')
        if R is None or C is None:
            continue
        moved = {f for f in ('k', 'cut', 'floor', 'tint')
                 if not _same(C[f], R[f])}
        if moved != want:
            bad(nm, f"9: axis={axis}: the fields that differ from the centre "
                    f"are {sorted(moved) or ['none']}, want {sorted(want)} "
                    f"(centre k={C['k']} cut={C['cut']} floor={C['floor']} "
                    f"tint={C['tint']}; rung k={R['k']} cut={R['cut']} "
                    f"floor={R['floor']} tint={R['tint']})")
        if axis == 'cutoff':
            if R['fade']:
                bad(nm, "9: the -cutoff rung still carries a fade")
            if not C['fade']:
                bad(nm, "9: the CENTRE carries no fade, so removing it is "
                        "not a one-axis step")
            dels = [(i1, i2) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                        None, C['ops'], R['ops'], autojunk=False).get_opcodes()
                    if tag != 'equal']
            gone = [C['ops'][i1:i2] for i1, i2 in dels]
            flat = [l for blk in gone for l in blk]
            if len(dels) != 1 or len(flat) != 3:
                bad(nm, f"9: the streams differ in {len(dels)} block(s) / "
                        f"{len(flat)} line(s), want exactly one block of 3 "
                        f"(the fade)")
            elif not all(re.match(pat, l) for pat, l in zip(FADE_OPS, flat)):
                bad(nm, f"9: the three removed lines are not the fade: {flat}")
        else:
            if R['fade'] != C['fade']:
                bad(nm, "9: one of the pair has a cutoff fade and the other "
                        "does not -- that is a second axis")
            if R['ops'] != C['ops']:
                sm = difflib.SequenceMatcher(None, C['ops'], R['ops'],
                                             autojunk=False)
                d0 = [o for o in sm.get_opcodes() if o[0] != 'equal']
                bad(nm, f"9: axis={axis} moved {len(d0)} INSTRUCTION block(s), "
                        f"not just a constant: {C['ops'][d0[0][1]:d0[0][2]][:1]}")
        n += 1
    print(f"ladder: {n} modules differ from the centre on axis '{axis}' and "
          f"on nothing else")


def negative(base_dir):
    n = 0
    for p in sorted(glob.glob(os.path.join(base_dir, '*.rgs_reference_main.spv'))):
        name = os.path.basename(p)
        if name.split('.')[0] in PASS_THROUGH:
            continue
        lines = dis(p)
        d = index(lines)
        gg = glow(lines, d, name, 'negative')
        if gg is None:
            continue
        km = re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(d, gg['ksel']))
        if not fv(d, km.group(1), K_OLD, 1e-4):
            bad(name, f"negative: the BASE's k is {fval(d, km.group(1))}, "
                      f"want {K_OLD}")
        if not fv(d, gg['b'][7], TMAX_OLD, 1e-4):
            bad(name, f"negative: the BASE's tmax is {fval(d, gg['b'][7])}, "
                      f"want {TMAX_OLD}")
        if not fv(d, gg['cap'], CAP6, 1e-5):
            bad(name, f"negative: the BASE's floor is {fval(d, gg['cap'])}, "
                      f"want {CAP6}")
        if any(c['tint'] is not None for c in gg['chains']):
            bad(name, "negative: the BASE already carries a tint multiply")
        n += 1
    print(f"negative control: {n} base reference modules carry k={K_OLD}, "
          f"tmax={TMAX_OLD}, floor={CAP6} and no tint")


def control(ctl_dir, base_dir):
    n = 0
    for p in sorted(glob.glob(os.path.join(ctl_dir, '*.rgs_reference_main.spv'))):
        name = os.path.basename(p)
        b = os.path.join(base_dir, name)
        if not os.path.exists(b):
            bad(name, "control: no base counterpart")
            continue
        if open(p, 'rb').read() != open(b, 'rb').read():
            bad(name, "control: NOT byte identical to the base")
        n += 1
    print(f"control: {n} modules compared byte for byte against the base")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--negative')
    ap.add_argument('--control')
    ap.add_argument('--mode', default='tint', choices=('none', 'tint', 'rate'))
    ap.add_argument('--k', type=float, default=0.055)
    ap.add_argument('--cut', type=float, default=0.008)
    ap.add_argument('--vs-centre',
                    help='the CENTRE rung directory; with --axis, run the '
                         'ladder check of 110 sec 14 instead of a base check')
    ap.add_argument('--axis', choices=tuple(AXIS_FIELD))
    ap.add_argument('--tint', default=None,
                    help='expected (c1) tint as R,G,B (default 1.0,0.40,0.22)')
    ap.add_argument('--no-cutoff', action='store_true',
                    help='the rung must carry NO fade and query B must still '
                         'hold the shipped tmax')
    ap.add_argument('--floor', type=float, default=CAP6,
                    help='101 sec 18 thickness floor in METRES that the '
                         'shipped bytes must carry (default 0.006)')
    a = ap.parse_args()
    tint = TINT
    if a.tint:
        tint = tuple(float(x) for x in a.tint.split(','))
        if len(tint) != 3:
            ap.error('--tint wants three comma-separated numbers')
    if a.vs_centre:
        if not a.axis:
            ap.error('--vs-centre needs --axis')
        if not a.rung:
            ap.error('need <rung-dir>')
        pairwise(a.rung, a.vs_centre, a.axis)
    elif a.negative:
        negative(a.negative)
    elif a.control:
        if not a.base:
            ap.error('--control needs --base')
        control(a.control, a.base)
    else:
        if not a.rung:
            ap.error('need <rung-dir>')
        n = ins = rew = 0
        ld = tint_got = fl = None
        for p in sorted(glob.glob(os.path.join(a.rung,
                                               '*.rgs_reference_main.spv'))):
            if os.path.basename(p).split('.')[0] in PASS_THROUGH:
                continue
            b = os.path.join(a.base, os.path.basename(p)) if a.base else None
            if b and not os.path.exists(b):
                bad(os.path.basename(p), "no base counterpart")
                continue
            r = check_module(p, b, a.mode, a.k, a.cut, a.floor, tint,
                             not a.no_cutoff)
            n += 1
            if r:
                ins += r['inserted'] or 0
                rew += r['rewritten'] or 0
                ld, tint_got, fl = r['ld'], r['tint'], r['floor']
        print(f"verify_earglow5: {n} permutations, {ins} inserted lines, "
              f"{rew} rewritten constants, "
              f"mode={a.mode}, k={a.k}, cut={a.cut*1000:g} mm, "
              f"floor={(fl or 0)*1000:g} mm, "
          f"cutoff={'NONE (tmax 18 mm, transfer decay only)' if a.no_cutoff else f'{a.cut*1000:g} mm'}, "
              f"ld={[round(x*1000, 3) for x in (ld or [])]} mm, tint={tint_got}, "
              f"query UNCHANGED (3/3/2/1)")
    if V.FAIL:
        for f in V.FAIL:
            print("  FAIL " + f)
        raise SystemExit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
