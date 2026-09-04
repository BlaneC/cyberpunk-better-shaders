#!/usr/bin/env python3
"""verify_earglow_ll.py <rung-dir> --base <base-dir> --model <r6lo.json>
                        --mode glow|hit [--k-scale S]
   verify_earglow_ll.py --negative <dir>

Re-derives the earglow-ll splice (handoff/113) from the SHIPPED .spv bytes --
never from the patcher's reports and never by importing its detectors. The
generic re-derivations (constant resolution, the sun-NEE trace, the path-loop
counter, the primary ray) come from verify_earglow_rq.py / verify_earglow_rq3.py,
which implement them independently of the patchers; the light-loop site and
the whole local-light splice are re-derived HERE.

Proven per patched rgs_reference_main permutation:

  1  RayQueryKHR capability + extension; ONE OpTypeRayQueryKHR; exactly SIX
     Function-storage query objects in the entry block's leading OpVariable
     run: the base's three (the sun glow, rq3) plus three new ones;
  2  exactly ONE light-sample site of the census shape -- a guard
     `(dot(N,toLight) < thr) OR (d2 > (range+radius)^2)` whose lit block
     opens with Sqrt(d2) and contains a shadow trace -- and the resampled
     loop (no trace in its lit block) carries NO splice;
  3  the loop's preheader carries the hoisted half: the class-1 test
     ((word & ~31) == 32) on a G-buffer fetch, `path counter == 0` on the
     counter re-derived by 90's throughput discriminator, and query A: flags
     517 from the ZERO triple along the module's own primary view ray with
     101 sec 12's bracket [|P| 0.999, |P| 1.001 + 1e-4], masked by
     Select(skin AND counter==0, 39, 0);
  4  the guard block carries queries B and C on the two remaining objects,
     sharing ONE mask Select(gate, 39, 0) with
     gate = ((skin AND counter==0) AND A committed) AND (dot < 0)
            AND NOT(range test) -- the BACKLIT arm is what `--decoy front`
     drops and what this file demands;
  5  query B: flags 545, origin the SUN NEE's own offset origin id, direction
     the fresh L = toLight / Sqrt(d2) built from the guard's own toLight
     triple, tmin 0.0015, tmax 0.018;
  6  query C: flags 517, origin = origin + L (t + 0.001) with t the GUARDED
     committed t, tmin 0.001, tmax = NMax(0.8 Sqrt(d2) - (t + 0.001), 0);
  7  ok = (gate AND (B committed AND A.id == B.id)) AND NOT(C hit), reached
     from the paint's select through LogicalAnd/LogicalNot only; `--decoy
     nomatch` (no instance compare) and `--decoy noc` (C traced, never
     consulted) are rejected here;
  8  E_c = atten x colour_c with colour_c the record's own offset-16 extracts
     and atten a FRESH FMul(NClamp(..), Select(..)) -- the engine's own chain
     cloned above the guard, not the engine's id (which the guard does not
     dominate);
  9  glow: per channel 2 Exp on NMax(t, 0.006) with the model's rate pair,
     x 0.5, x tint_c, x (Select(ok, k, 0) NMax(-dot/d, 0)), x E_c, NMin 100,
     accumulated; k == model k x --k-scale. `--decoy flatk` (no Exp) is
     rejected. hit: no Exp; BLUE/AMBER selects on ok/rej, scaled by the mean
     of E and the Lambert;
 10  every non-trivial OpImageWrite texel is a construct of three
     FAdd(component, Load(accumulator)) -- an ADD, alpha untouched -- and the
     accumulators are stored 0 in the entry block;
 11  the OpTraceRayKHR count is unchanged from the base.

--negative asserts the modules carry NONE of it (three query objects, no
initialize inside any light guard block).
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
from verify_earglow_rq import (dis, index, fval, uval, close, bad, nee_trace,
                               path_counter, PASS_THROUGH)
from verify_earglow_rq3 import primary_ray, reaches

FLAGS_A, FLAGS_B = 517, 545
GET_ID = 'OpRayQueryGetIntersectionInstanceIdKHR'
BRACKET = (0.999, 1.001, 1.0e-4)
TMIN_B, TMAX_B, PUSH, TMIN_C, REACH, FLOOR, CLAMP = (0.0015, 0.018, 0.001,
                                                    0.001, 0.8, 0.006, 100.0)
DIAG_OK = (0.0, 0.04, 0.32)
DIAG_REJ = (0.32, 0.16, 0.0)


def body(d, tok):
    return d.get(tok, (0, ''))[1]


def by_body(d):
    return {b: t for t, (ln, b) in d.items()}


def m_(d, tok, pat):
    return re.match(pat, body(d, tok))


def c3(d, tok):
    m = m_(d, tok, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$')
    return list(m.groups()) if m else None


def fz(d, tok):
    v = fval(d, tok)
    return v is not None and v == 0.0


def light_sites(lines, d, name):
    """The census shape, re-derived. Returns (accepted, declined) site dicts."""
    labels = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', l)
        if m:
            labels[m.group(1)] = i
    acc, dec = [], []
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        cond, t_merge, t_lit = m.groups()
        om = m_(d, cond, r'OpLogicalOr %bool (%\w+) (%\w+)$')
        if not om:
            continue
        am = m_(d, om.group(1), r'OpFOrdLessThan %bool (%\w+) (%\w+)$')
        bm = m_(d, om.group(2), r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$')
        if not (am and bm) or fval(d, am.group(2)) is None:
            continue
        dm = m_(d, am.group(1), r'OpDot %float (%\w+) (%\w+)$')
        if not dm:
            continue
        N, T = c3(d, dm.group(1)), c3(d, dm.group(2))
        if not (N and T):
            continue
        d2, rr2 = bm.groups()
        nm = m_(d, d2, r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$')
        if not nm:
            continue
        ddm = m_(d, nm.group(1), r'OpDot %float (%\w+) (%\w+)$')
        if not ddm or c3(d, ddm.group(1)) != T or c3(d, ddm.group(2)) != T:
            continue
        rm = m_(d, rr2, r'OpFMul %float (%\w+) (%\w+)$')
        if not rm or rm.group(1) != rm.group(2):
            continue
        lit, merge = labels.get(t_lit), labels.get(t_merge)
        if lit != i + 1 or merge is None:
            continue
        if not re.match(r'\s*%\w+ = OpExtInst %float %\w+ Sqrt ' + re.escape(d2)
                        + r'\s*$', lines[lit + 1]):
            continue
        traces = sum(1 for j in range(lit, merge)
                     if re.match(r'\s*OpTraceRayKHR\b', lines[j]))
        # the block the guard ends: back to its label
        top = i
        while top > 0 and not re.match(r'\s*%\w+ = OpLabel', lines[top]):
            top -= 1
        # its loop header and preheader
        hdr = None
        for j in range(i - 1, 0, -1):
            lm = re.match(r'\s*OpLoopMerge (%\w+) (%\w+) None\s*$', lines[j])
            if lm and labels.get(lm.group(1), -1) > i:
                hdr = j
                break
        if hdr is None:
            continue
        hl = hdr
        while not re.match(r'\s*%\w+ = OpLabel', lines[hl]):
            hl -= 1
        hlab = re.match(r'\s*(%\w+) = OpLabel', lines[hl]).group(1)
        mline = labels[re.match(r'\s*OpLoopMerge (%\w+)', lines[hdr]).group(1)]
        preds = [j for j, ll in enumerate(lines)
                 if re.match(r'\s*OpBranch ' + re.escape(hlab) + r'\s*$', ll)
                 and not (hl <= j < mline)]
        pre_top = None
        if len(preds) == 1:
            pre_top = preds[0]
            while pre_top > 0 and not re.match(r'\s*%\w+ = OpLabel', lines[pre_top]):
                pre_top -= 1
        rec = dict(line=i, top=top, lit=lit, merge=merge, dot=am.group(1),
                   thr=fval(d, am.group(2)), N=N, T=T, d2=d2,
                   rangefail=om.group(2), traces=traces, header=hl,
                   pre_top=pre_top, pre_end=preds[0] if len(preds) == 1 else None)
        (acc if traces else dec).append(rec)
    return acc, dec


def inits_in(lines, a, b):
    out = []
    for j in range(a, b):
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', lines[j])
        if m:
            out.append((j, m.group(1).split()))
    return out


def record_colour(lines, d, site):
    hits = []
    for j in range(site['header'], site['line']):
        m = re.match(r'\s*(%\w+)\s*=\s*OpRawAccessChainNV %_ptr_StorageBuffer_v3float '
                     r'%\w+ %uint_64 %\w+ %uint_16 RobustnessPerElementNV\s*$',
                     lines[j])
        if m:
            hits.append(m.group(1))
    if len(hits) != 1:
        return None
    ld = None
    for tok, (ln, b) in d.items():
        if re.match(r'OpLoad %v3float ' + re.escape(hits[0]) + r'\b', b):
            ld = tok
    if not ld:
        return None
    ext = {}
    for tok, (ln, b) in d.items():
        m = re.match(r'OpCompositeExtract %float ' + re.escape(ld) + r' (\d)$', b)
        if m:
            ext[int(m.group(1))] = tok
    return [ext.get(0), ext.get(1), ext.get(2)] if sorted(ext) == [0, 1, 2] else None


def check_module(path, base_path, mode, k_want, rates, tint):
    name = os.path.basename(path)
    lines = dis(path)
    d = index(lines)
    base = dis(base_path)

    # ---- 1. capability, ONE type, SIX objects --------------------------------
    if not any(re.match(r'\s*OpCapability RayQueryKHR\s*$', l) for l in lines):
        return bad(name, "no OpCapability RayQueryKHR")
    if not any('OpExtension "SPV_KHR_ray_query"' in l for l in lines):
        bad(name, 'no OpExtension "SPV_KHR_ray_query"')
    rqts = [t for t, (ln, b) in d.items() if b == 'OpTypeRayQueryKHR']
    if len(rqts) != 1:
        return bad(name, f"{len(rqts)} OpTypeRayQueryKHR, want 1")
    ptrs = [t for t, (ln, b) in d.items()
            if b == f'OpTypePointer Function {rqts[0]}']
    if len(ptrs) != 1:
        return bad(name, f"{len(ptrs)} Function pointers to the query type")
    rqv = [t for t, (ln, b) in d.items() if b == f'OpVariable {ptrs[0]} Function']
    if len(rqv) != 6:
        return bad(name, f"{len(rqv)} ray query objects, want exactly 6 "
                         f"(the sun glow's 3 + local A/B/C)")
    for v in rqv:
        j = d[v][0] - 1
        while j >= 0 and re.match(r'\s*%\w+ = OpVariable .* Function\s*$', lines[j]):
            j -= 1
        if not re.match(r'\s*%\w+ = OpLabel\s*$', lines[j]):
            bad(name, f"query object {v} is not in the entry block's OpVariable run")

    # ---- 2. the site -----------------------------------------------------------
    acc, dec = light_sites(lines, d, name)
    if len(acc) != 1:
        return bad(name, f"{len(acc)} light-sample sites with a shadow trace, want 1")
    site = acc[0]
    for s in dec:
        if inits_in(lines, s['top'], s['line']):
            bad(name, f"the resampled loop (guard line {s['line']+1}) carries a "
                      f"query -- the splice must not touch it")
    if site['pre_top'] is None:
        return bad(name, "the light loop has no single preheader")
    nee, _ = nee_trace(lines, d, name)
    if nee is None:
        return
    counter = path_counter(lines, d, name)
    if isinstance(counter, tuple):
        counter = counter[0]
    prim = primary_ray(lines, d, name)
    if counter is None or prim is None:
        return

    # ---- 3. the preheader: skin, counter, query A ---------------------------
    pre_inits = inits_in(lines, site['pre_top'], site['pre_end'])
    if len(pre_inits) != 1:
        return bad(name, f"{len(pre_inits)} queries in the preheader, want 1 (A)")
    qA = pre_inits[0][1]
    if len(qA) != 8 or uval(d, qA[2]) != FLAGS_A:
        return bad(name, f"query A flags {qA[2]} are not {FLAGS_A}")
    if qA[1] != nee[0]:
        bad(name, f"query A uses {qA[1]}, not the sun NEE's AS {nee[0]}")
    zm = m_(d, qA[4], r'OpConstantComposite %v3float (%\w+) (%\w+) (%\w+)$')
    if not zm or not all(fz(d, x) for x in zm.groups()):
        bad(name, "query A does not start at the zero triple")
    if c3(d, qA[6]) != prim['V']:
        bad(name, "query A direction is not the module's own primary view ray")
    tA = None
    lo = m_(d, qA[5], r'OpFMul %float (%\w+) (%\w+)$')
    if lo and close(fval(d, lo.group(2)), BRACKET[0]):
        tA = lo.group(1)
    else:
        bad(name, "query A tmin is not |P| x 0.999")
    hi = m_(d, qA[7], r'OpFAdd %float (%\w+) (%\w+)$')
    hm = hi and m_(d, hi.group(1), r'OpFMul %float (%\w+) (%\w+)$')
    if not (hm and close(fval(d, hi.group(2)), BRACKET[2])
            and close(fval(d, hm.group(2)), BRACKET[1]) and hm.group(1) == tA):
        bad(name, "query A tmax is not |P| x 1.001 + 1e-4")
    if tA:
        tm = m_(d, tA, r'OpFMul %float (%\w+) (%\w+)$')
        if not tm or {tm.group(1), tm.group(2)} != {prim['dot'], prim['rsqrt']}:
            bad(name, "|P| is not dot(P,P) x rsqrt(dot(P,P)) of the primary ray")
    mA = m_(d, qA[3], r'OpSelect %uint (%\w+) (%\w+) (%\w+)$')
    if not mA or uval(d, mA.group(2)) != 39 or uval(d, mA.group(3)) != 0:
        return bad(name, "query A's mask is not Select(gate, 39, 0)")
    g_pre = mA.group(1)
    pm = m_(d, g_pre, r'OpLogicalAnd %bool (%\w+) (%\w+)$')
    if not pm:
        return bad(name, "query A's gate is not an AND")
    skin = p0 = False
    for x in pm.groups():
        sm = m_(d, x, r'OpIEqual %bool (%\w+) (%\w+)$')
        if not sm:
            continue
        if uval(d, sm.group(2)) == 32:
            am = m_(d, sm.group(1), r'OpBitwiseAnd %uint (%\w+) %uint_4294967264$')
            em = am and m_(d, am.group(1), r'OpCompositeExtract %uint (%\w+) 1$')
            if em and m_(d, em.group(1), r'OpImageFetch\b'):
                skin = True
        elif uval(d, sm.group(2)) == 0 and sm.group(1) == counter:
            p0 = True
    if not skin:
        bad(name, "the hoisted gate has no class-1 test on a G-buffer fetch")
    if not p0:
        bad(name, f"the hoisted gate does not test path counter {counter} == 0")
    # A's results
    rev = by_body(d)
    ityA = rev.get(f'OpRayQueryGetIntersectionTypeKHR %uint {qA[0]} %uint_1')
    hitA = rev.get(f'OpINotEqual %bool {ityA} %uint_0') if ityA else None
    idA = rev.get(f'{GET_ID} %uint {qA[0]} %uint_1')
    if not (hitA and idA):
        return bad(name, "query A's commit test / InstanceId read not found")

    # ---- 4/5/6. the guard block: B and C -------------------------------------
    sinits = inits_in(lines, site['top'], site['line'])
    if len(sinits) != 2:
        return bad(name, f"{len(sinits)} queries in the guard block, want 2 (B, C)")
    byf = {uval(d, q[2]): q for _, q in sinits}
    if sorted(byf) != [FLAGS_A, FLAGS_B]:
        return bad(name, f"guard-block query flags {sorted(byf)}, want [517, 545]")
    qB, qC = byf[FLAGS_B], byf[FLAGS_A]
    if {qA[0], qB[0], qC[0]} - set(rqv) or len({qA[0], qB[0], qC[0]}) != 3:
        bad(name, "A/B/C do not run on three distinct declared objects")
    if not (qB[1] == qC[1] == nee[0]):
        bad(name, "B/C do not use the sun NEE's acceleration structure")
    if qB[3] != qC[3]:
        bad(name, "B and C do not share one mask")
    if qB[4] != nee[6]:
        bad(name, f"query B origin {qB[4]} is not the sun NEE's offset origin {nee[6]}")
    if not close(fval(d, qB[5]), TMIN_B) or not close(fval(d, qB[7]), TMAX_B):
        bad(name, "query B tmin/tmax are not 1.5 mm / 18 mm")
    Lv = c3(d, qB[6])
    dsq = None
    if Lv:
        for c in range(3):
            fm = m_(d, Lv[c], r'OpFDiv %float (%\w+) (%\w+)$')
            if not fm or fm.group(1) != site['T'][c]:
                bad(name, f"L[{c}] is not toLight[{c}] / d"); break
            sq = m_(d, fm.group(2), r'OpExtInst %float %\w+ Sqrt (%\w+)$')
            if not sq or sq.group(1) != site['d2']:
                bad(name, "L's denominator is not Sqrt(d2) of the guard's d2"); break
            if d[fm.group(2)][0] > site['line']:
                bad(name, "L uses the engine's Sqrt from inside the lit block"); break
            dsq = fm.group(2)
    else:
        bad(name, "query B direction is not a v3 construct")
    if qC[6] != qB[6]:
        bad(name, "query C direction is not L")
    if not close(fval(d, qC[5]), TMIN_C):
        bad(name, "query C tmin is not 1 mm")
    # the guarded t and the exit origin
    tu = None
    for tok, (ln, b) in d.items():
        m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', b)
        if m and m_(d, m.group(2), r'OpRayQueryGetIntersectionTKHR %float '
                    + re.escape(qB[0]) + r' %uint_1$') and close(fval(d, m.group(3)), TMAX_B):
            tu = tok
    if tu is None:
        bad(name, "no NaN-guarded t (Select(hitB, t, 18 mm))")
    om = m_(d, qC[4], r'OpFAdd %v3float (%\w+) (%\w+)$')
    tp = None
    if om and om.group(1) == nee[6]:
        vm = m_(d, om.group(2), r'OpVectorTimesScalar %v3float (%\w+) (%\w+)$')
        if vm and vm.group(1) == qB[6]:
            am = m_(d, vm.group(2), r'OpFAdd %float (%\w+) (%\w+)$')
            if am and am.group(1) == tu and close(fval(d, am.group(2)), PUSH):
                tp = vm.group(2)
    if tp is None:
        bad(name, "query C origin is not origin + L (t + 1 mm)")
    nm = m_(d, qC[7], r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$')
    ok_t = False
    if nm and fz(d, nm.group(2)):
        sm = m_(d, nm.group(1), r'OpFSub %float (%\w+) (%\w+)$')
        if sm and sm.group(2) == tp:
            rm = m_(d, sm.group(1), r'OpFMul %float (%\w+) (%\w+)$')
            ok_t = bool(rm and rm.group(1) == dsq and close(fval(d, rm.group(2)), REACH))
    if not ok_t:
        bad(name, "query C tmax is not NMax(0.8 d - (t + 1 mm), 0)")
    # the mask and the gate
    mm = m_(d, qB[3], r'OpSelect %uint (%\w+) (%\w+) (%\w+)$')
    if not mm or uval(d, mm.group(2)) != 39 or uval(d, mm.group(3)) != 0:
        return bad(name, "B/C mask is not Select(gate, 39, 0)")
    gate = mm.group(1)
    backlit_ok = range_ok = hoist_ok = False
    for tok in _and_leaves(d, gate):
        b = body(d, tok)
        if b == f'OpFOrdLessThan %bool {site["dot"]} %float_0' or \
                b == f'OpFOrdLessThan %bool {site["dot"]} %float_n0':
            backlit_ok = True
        if b == f'OpLogicalNot %bool {site["rangefail"]}':
            range_ok = True
        if tok == hitA or tok == g_pre:
            hoist_ok = True
    if not backlit_ok:
        bad(name, "the gate has no BACKLIT arm (dot(N,toLight) < 0)")
    if not range_ok:
        bad(name, "the gate does not negate the guard's range test")
    if not hoist_ok or not reaches(d, gate, g_pre):
        bad(name, "the gate does not reach the hoisted skin/counter gate")
    if not reaches(d, gate, hitA):
        bad(name, "the gate does not require A committed")

    # ---- 7. ok ---------------------------------------------------------------
    ityB = rev.get(f'OpRayQueryGetIntersectionTypeKHR %uint {qB[0]} %uint_1')
    ityC = rev.get(f'OpRayQueryGetIntersectionTypeKHR %uint {qC[0]} %uint_1')
    hitB = rev.get(f'OpINotEqual %bool {ityB} %uint_0') if ityB else None
    hitC = rev.get(f'OpINotEqual %bool {ityC} %uint_0') if ityC else None
    idB = rev.get(f'{GET_ID} %uint {qB[0]} %uint_1')
    if not (hitB and hitC and idB):
        return bad(name, "B/C commit tests or B's InstanceId read not found")
    same = [t for t, (ln, b) in d.items()
            if b in (f'OpIEqual %bool {idA} {idB}', f'OpIEqual %bool {idB} {idA}')]
    if len(same) != 1:
        return bad(name, f"{len(same)} instance compares A==B, want 1")
    visC = [t for t, (ln, b) in d.items() if b == f'OpLogicalNot %bool {hitC}']
    if len(visC) != 1:
        return bad(name, "no LogicalNot over C's commit test")
    # the paint's own boolean -- searched in the GUARD BLOCK only: the sun
    # glow (v7) below the sun NEE carries the same k select
    span = range(site['top'], site['line'])
    fk = None
    if mode == 'glow':
        cands = [(t, m) for t, (ln, b) in d.items() if ln in span
                 for m in [re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', b)]
                 if m and close(fval(d, m.group(2)), k_want, 1e-4) and fz(d, m.group(3))]
        if len(cands) != 1:
            return bad(name, f"{len(cands)} Select(ok, k={k_want:.6g}, 0), want 1")
        ok, fk = cands[0][1].group(1), cands[0][1].group(2)
    else:
        cands = [(t, m) for t, (ln, b) in d.items() if ln in span
                 for m in [re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)$', b)]
                 if m and close(fval(d, m.group(2)), DIAG_OK[2])
                 and not fz(d, m.group(3))]          # AMBER's red is 0.32 too
        if len(cands) != 1:
            return bad(name, f"{len(cands)} BLUE selects, want 1")
        ok = cands[0][1].group(1)
        rejsel = cands[0][1].group(3)
        rm = m_(d, rejsel, r'OpSelect %float (%\w+) (%\w+) (%\w+)$')
        if not rm or not close(fval(d, rm.group(2)), DIAG_REJ[2]) or not fz(d, rm.group(3)):
            bad(name, "the BLUE select's fallback is not the AMBER select")
        elif not (reaches(d, rm.group(1), hitC) and reaches(d, rm.group(1), same[0])):
            bad(name, "AMBER is not gated by (match AND C hit)")
    for what, tgt in (("the gate", gate), ("the instance compare", same[0]),
                      ("B's commit", hitB), ("A's commit", hitA),
                      ("C's miss", visC[0])):
        if not reaches(d, ok, tgt):
            bad(name, f"the paint does not reach {what}")
    if reaches(d, ok, hitC, depth=3) and not reaches(d, ok, visC[0]):
        bad(name, "the paint consults C's HIT, not its miss")

    # ---- 8. E_c and the Lambert -----------------------------------------------
    colour = record_colour(lines, d, site)
    if not colour:
        return bad(name, "the light record's colour extracts were not re-found")
    Ec = []
    for c in range(3):
        es = [t for t, (ln, b) in d.items()
              for m in [re.match(r'OpFMul %float (%\w+) (%\w+)$', b)]
              if m and m.group(2) == colour[c] and site['top'] < ln < site['line']]
        if len(es) != 1:
            return bad(name, f"{len(es)} FMul(atten, colour[{c}]) in the guard block, want 1")
        Ec.append(es[0])
    atts = {m_(d, e, r'OpFMul %float (%\w+) (%\w+)$').group(1) for e in Ec}
    if len(atts) != 1:
        return bad(name, "the three E_c do not share one atten factor")
    att = atts.pop()
    am = m_(d, att, r'OpFMul %float (%\w+) (%\w+)$')
    kinds = sorted(body(d, x).split()[0] for x in am.groups()) if am else []
    if kinds != ['OpExtInst', 'OpSelect'] or d[att][0] > site['line']:
        bad(name, "atten is not a fresh FMul(NClamp(spot), Select(atten)) above the guard")
    lam = [t for t, (ln, b) in d.items()
           for m in [re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$', b)]
           if m and fz(d, m.group(2)) and site['top'] < ln < site['line']
           and m_(d, m.group(1), r'OpFNegate %float (%\w+)$')
           and body(d, m_(d, m.group(1), r'OpFNegate %float (%\w+)$').group(1))
               == f'OpFDiv %float {site["dot"]} {dsq}']
    if len(lam) != 1:
        bad(name, f"{len(lam)} Lambert NMax(-dot/d, 0), want 1")

    # ---- 9. the transfer / the diagnostic --------------------------------------
    exps = [t for t, (ln, b) in d.items() if ln in span
            and re.match(r'OpExtInst %float %\w+ Exp ', b)]
    if mode == 'glow':
        if len(exps) != 6:
            return bad(name, f"{len(exps)} Exp in the guard block, want 6")
        te = None
        got = []
        for e in exps:
            nm = m_(d, e, r'OpExtInst %float %\w+ Exp (%\w+)$')
            ng = m_(d, nm.group(1), r'OpFNegate %float (%\w+)$')
            fm = ng and m_(d, ng.group(1), r'OpFMul %float (%\w+) (%\w+)$')
            if not fm:
                return bad(name, "an Exp is not Exp(-(t x rate))")
            te = te or fm.group(1)
            if fm.group(1) != te:
                bad(name, "the six Exp do not share one t")
            got.append(fval(d, fm.group(2)))
        want = sorted(a for pair in rates for a in pair)
        if len(got) != len(want) or any(not close(a, b, 1e-4)
                                        for a, b in zip(sorted(got), want)):
            bad(name, f"rates {sorted(got)} are not the model's {want}")
        fm = m_(d, te, r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$')
        if not fm or fm.group(1) != tu or not close(fval(d, fm.group(2)), FLOOR):
            bad(name, "t is not NMax(guarded t_B, 6 mm)")
        tints = sorted(fval(d, m.group(2)) for t, (ln, b) in d.items() if ln in span
                       for m in [re.match(r'OpFMul %float (%\w+) (%\w+)$', b)]
                       if m and fval(d, m.group(2)) is not None
                       and m_(d, m.group(1), r'OpFMul %float (%\w+) %float_0_5$'))
        if len(tints) != 3 or any(not close(a, b, 1e-4) for a, b in zip(tints, sorted(tint))):
            bad(name, f"tints {tints} are not the model's {sorted(tint)}")
    else:
        if exps:
            bad(name, f"the diagnostic carries {len(exps)} Exp")
        third = [t for t, (ln, b) in d.items() if ln in span
                 for m in [re.match(r'OpFMul %float (%\w+) (%\w+)$', b)]
                 if m and close(fval(d, m.group(2)), 1.0 / 3.0)]
        if len(third) != 1:
            bad(name, "the diagnostic is not scaled by the mean of E")
    clamps = [t for t, (ln, b) in d.items() if ln in span
              for m in [re.match(r'OpExtInst %float %\w+ NMin (%\w+) (%\w+)$', b)]
              if m and close(fval(d, m.group(2)), CLAMP)]
    if len(clamps) != 3:
        bad(name, f"{len(clamps)} NMin(.., 100) clamps in the guard block, want 3")
    stores = [l for j, l in enumerate(lines) if j in span and re.match(r'\s*OpStore ', l)]
    if len(stores) != 3:
        bad(name, f"{len(stores)} accumulator stores in the guard block, want 3")
    gvs = {re.match(r'\s*OpStore (%\w+) ', s).group(1) for s in stores}

    # ---- 10. the writes --------------------------------------------------------
    for g in gvs:
        if body(d, g) != 'OpVariable %_ptr_Function_float Function':
            bad(name, f"accumulator {g} is not a Function float")
    nw = 0
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', l)
        if not m:
            continue
        cc = m_(d, m.group(3), r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)$')
        if not cc:
            continue
        adds = 0
        for ch in range(3):
            am = m_(d, cc.group(ch + 1), r'OpFAdd %float (%\w+) (%\w+)$')
            if am:
                for x in am.groups():
                    lm = m_(d, x, r'OpLoad %float (%\w+)$')
                    if lm and lm.group(1) in gvs:
                        adds += 1
        if adds == 3:
            nw += 1
        elif adds:
            bad(name, f"a write at line {i+1} adds only {adds} of 3 local channels")
    if nw == 0:
        bad(name, "no radiance write carries the local-light term")

    # ---- 11. no new rays ------------------------------------------------------
    nt = sum(1 for l in lines if re.match(r'\s*OpTraceRayKHR\b', l))
    nb = sum(1 for l in base if re.match(r'\s*OpTraceRayKHR\b', l))
    if nt != nb:
        bad(name, f"OpTraceRayKHR count {nt} != base {nb}")
    return nw


def _and_leaves(d, tok, depth=8):
    out, stack = [], [(tok, 0)]
    while stack:
        cur, k = stack.pop()
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', body(d, cur))
        if m and k < depth:
            stack.extend((x, k + 1) for x in m.groups())
        else:
            out.append(cur)
    return out


def negative(dirn):
    n = 0
    for p in sorted(glob.glob(os.path.join(dirn, '*.rgs_reference_main.spv'))):
        ident = os.path.basename(p).split('.')[0]
        if ident in PASS_THROUGH:
            continue
        lines = dis(p)
        d = index(lines)
        rqts = [t for t, (ln, b) in d.items() if b == 'OpTypeRayQueryKHR']
        ptrs = [t for t, (ln, b) in d.items()
                if rqts and b == f'OpTypePointer Function {rqts[0]}']
        rqv = [t for t, (ln, b) in d.items()
               if ptrs and b == f'OpVariable {ptrs[0]} Function']
        if len(rqv) != 3:
            bad(os.path.basename(p), f"{len(rqv)} query objects, want the base's 3")
        acc, dec = light_sites(lines, d, os.path.basename(p))
        for s in acc + dec:
            if inits_in(lines, s['top'], s['line']):
                bad(os.path.basename(p), "a light guard block carries a query")
        n += 1
    print(f"negative control: {n} reference modules carry no local-light splice")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--model')
    ap.add_argument('--negative')
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit'))
    ap.add_argument('--k-scale', type=float, default=1.0)
    a = ap.parse_args()
    if a.negative:
        negative(a.negative)
    else:
        if not a.rung or not a.base or not a.model:
            ap.error('need <rung-dir> --base <base-dir> --model <json>')
        m = json.load(open(a.model))
        rates = [tuple(r) for r in m['rates_1_per_m']]
        tint = list(m['tint'])
        k = float(m['k']) * a.k_scale
        n = tot = 0
        for p in sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv'))):
            ident = os.path.basename(p).split('.')[0]
            if ident in PASS_THROUGH:
                continue
            b = os.path.join(a.base, os.path.basename(p))
            if not os.path.exists(b):
                bad(os.path.basename(p), "no base counterpart")
                continue
            r = check_module(p, b, a.mode, k, rates, tint)
            n += 1
            tot += r or 0
        print(f"verify_earglow_ll: {n} permutations, {tot} painted writes, "
              f"mode={a.mode}, k={k:.4f}, A=517 B=545 C=517")
    if V.FAIL:
        for f in V.FAIL:
            print("  FAIL " + f)
        raise SystemExit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
