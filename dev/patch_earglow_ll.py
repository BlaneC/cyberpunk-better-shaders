#!/usr/bin/env python3
"""earglow-ll -- ear glow from LOCAL LIGHTS, spliced at the raygen's own
light-sample site. handoff/113.

WHY THIS EXISTS (read handoff/112 sec 12 and handoff/103 sec 12-13 first).

`112` (`earglow-di`) spliced the local-light glow into the 77 compute
resolvers and was shot invisible: under path tracing the resolvers' painted
write carries sun + sky and NO local-light radiance on skin. Local light lives
in the `rgs_reference_main` raygens, which do their own next-event estimation
over a per-cluster light list. `103`'s bda-probe (GREEN) and bda-rq-probe
(BLUE) proved the layer's slot, fixup and traversal; none of that is needed
here, because the raygen already holds the acceleration structure, the light
records and the surface point. This file is the sun glow (`101` sec 15's rq3
queries + `111` v7's measured transfer) re-hung on the local-light loop.

THE SITE. Each raygen has exactly one light loop of this shape (census over
all 10, dev/disasm/earglow_ll):

    toLight = lightPos - P - cam                 (three FSub chains)
    d2      = NMax(dot(toLight, toLight), 1e-7)
    skip    = (dot(N, toLight) < 0) OR (d2 > (range + radius)^2)
    OpSelectionMerge %merge / OpBranchConditional skip %merge %lit
    %lit:  d = Sqrt(d2); L = toLight / d; atten; spot; ... ; shadow trace

The engine SKIPS backlit lights before it ever computes the light's radiance
-- exactly the lights that make an ear glow. So the splice goes in the block
that ends with that guard, BEFORE the OpSelectionMerge, where every light
record field, toLight and d2 are already defined and the guard has not fired.
The attenuation x spot chain from inside %lit is cloned above the guard with
the engine's own Sqrt re-pointed to a fresh one (pure ops only, refused
otherwise), so E_c = atten_spot x colour_c is the engine's own unshadowed
radiance for this light, evaluated on the far side of the ear.

The second loop (the resampled-importance pass) rejects backlit candidates
inside the loop and traces only the chosen light afterwards: it has no shadow
trace in its lit block, the finder declines it by that shape, and it is
reported as such. A backlit ear cannot be lit from that loop without changing
the engine's sampling, which this file does not do.

PER LOOP, ONCE (in the loop's preheader, i.e. once per path vertex per sample):
    class fetch clone  -> skin (class-1: (word & ~31) == 32)
    counter == 0       -> primary path segment only (patch_cavity2)
    query A  flags 517 from the camera along the module's own primary view
             ray with 101 sec 12's +/-0.1 % bracket -> committed InstanceId
PER LIGHT (before the guard):
    d = Sqrt(d2); L = toLight / d
    gate = skin AND counter==0 AND A committed AND dot(N,toLight) < 0
           AND NOT (d2 > (range+radius)^2)
    mask = Select(gate, 39, 0)   -- a shut gate is two free misses
    query B  flags 545 (cull front) from the module's sun-NEE origin (P with
             the engine's own self-hit offset) along L, tmin 1.5 mm, tmax
             18 mm -> t_B, committed InstanceId
    query C  flags 517 from P + (t_B + 1 mm) L along L, tmin 1 mm, tmax
             NMax(0.8 d - (t_B + 1 mm), 0): the engine's own shadow ray stops
             at 0.775-1.0 d so the emitter's own mesh is never an occluder
    ok   = gate AND A.id == B.id AND B committed AND C missed
    T_c  = 0.5 (exp(-a1c t) + exp(-a2c t)) tint_c,  t = NMax(t_B, 6 mm)  (111 v7)
    W    = k Select(ok, 1, 0) NMax(-N.L, 0)
    add_c = NMin(T_c W E_c, 100)   -> three Function accumulators
    ... added at every radiance write, exactly as rq3 / v7 do for the sun.

NOT included: the light record's per-light diffuse/specular scale bytes (word
60) and the "affects diffuse" flag bits. They are on/off and mode-selected;
ordinary lights carry 1. Recorded here so nobody thinks it was forgotten.

MODES
    glow   the rung (k from the model, --k-scale for -hi)
    hit    the diagnostic: BLUE where ok, AMBER where the gate and the instance
           match pass but C hits, both scaled by the light's own E so the
           paint reads on lit skin; carries the glow's FULL gate
    ctl    nothing emitted -- the byte-identical control

  ./dev/build_earglow_ll.sh [--install]
  python3 dev/patch_earglow_ll.py <in.spvasm> --outdir <dir> --model <r6lo.json>
          [--k-scale 2] [--mode glow|hit|ctl] [--decoy noc|nomatch|flatk|front]

NOT EDITED BY THIS FILE, only imported: dev/patch_rayq.py, dev/patch_earglow.py,
dev/patch_earglow_rq.py, dev/patch_earglow_rq2.py, dev/patch_earglow7.py,
dev/patch_cavity2.py.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish
import patch_earglow as E
from patch_earglow import (find_nee_trace, find_class_fetch, find_origin_offset,
                           clone_chain, entry_block_span, CLAMP)
from patch_cavity2 import find_path_counter
from patch_rayq import _find_primary_ray, _add_header
from patch_earglow_rq import (_uc, _fc, _ensure_line, FLAGS, FLAGS_NAMES,
                              GATE_MASK, TMIN, TMAX)
from patch_earglow_rq2 import (FLAGS_A, FLAGS_A_NAMES, BRACKET_LO, BRACKET_HI,
                               BRACKET_EPS, GETTER_ID)
from patch_earglow7 import load_model

FLAGS_C = FLAGS_A                       # 517: anything at all occludes
PUSH = 0.001                            # C starts 1 mm past the committed wall
TMIN_C = 0.001
REACH = 0.8                             # C's tmax = 0.8 d - (t + PUSH); the
                                        # engine's own shadow ray stops at
                                        # 0.775..1.0 d (its tmax operand)
FLOOR = 0.006                           # 101 sec 18 / 111 v7: t_eff floor
DIAG_OK = (0.0, 0.04, 0.32)             # BLUE  ok
DIAG_REJ = (0.32, 0.16, 0.0)            # AMBER gate+match passed, C hit
PURE_OPS = (r'Op(FMul|FDiv|FAdd|FSub|FNegate|ExtInst|Select|INotEqual|IEqual|'
            r'BitwiseAnd|BitwiseOr|ShiftRightLogical|ShiftLeftLogical|FConvert|'
            r'UConvert|SConvert|ConvertUToF|ConvertSToF|CompositeExtract|'
            r'CompositeConstruct|Dot|Load|AccessChain|InBoundsAccessChain|'
            r'RawAccessChainNV|IAdd|ISub|IMul|Bitcast|FOrdLessThan|'
            r'FOrdGreaterThan|FOrdLessThanEqual|FOrdGreaterThanEqual|'
            r'LogicalAnd|LogicalOr|LogicalNot|VectorTimesScalar)\b')


def _def(mod, ident):
    ln, d = mod.find_def(ident)
    return ln, (d or '')


def _fval(mod, ident):
    _, d = _def(mod, ident)
    m = re.match(r'OpConstant %\w+ ([-+0-9.eE]+)$', d)
    return float(m.group(1)) if m else None


def _construct3(mod, ident):
    _, d = _def(mod, ident)
    m = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)$', d)
    return list(m.groups()) if m else None


def find_light_sites(mod, fs, fe):
    """Every `OpBranchConditional (dot(N,toLight) < thr) OR (d2 > rr2)` guard
    whose lit block opens with Sqrt(d2). Returns the accepted sites (a shadow
    trace inside the lit region) and the declined ones (none: the resampled
    loop), each with everything the splice needs, all re-derived."""
    labels = {}
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', mod.lines[i])
        if m:
            labels[m.group(1)] = i
    sites, declined = [], []
    for i in range(fs, fe):
        m = re.match(r'(\s*)OpBranchConditional (%\w+) (%\w+) (%\w+)\s*$',
                     mod.lines[i])
        if not m:
            continue
        ind, cond, t_merge, t_lit = m.groups()
        _, cd = _def(mod, cond)
        om = re.match(r'OpLogicalOr %bool (%\w+) (%\w+)$', cd)
        if not om:
            continue
        _, ad = _def(mod, om.group(1))
        am = re.match(r'OpFOrdLessThan %bool (%\w+) (%\w+)$', ad)
        _, bd = _def(mod, om.group(2))
        bm = re.match(r'OpFOrdGreaterThan %bool (%\w+) (%\w+)$', bd)
        if not (am and bm):
            continue
        dot, thr = am.groups()
        thrv = _fval(mod, thr)
        if thrv is None:
            continue
        _, dd = _def(mod, dot)
        dm = re.match(r'OpDot %float (%\w+) (%\w+)$', dd)
        if not dm:
            continue
        nvec, tvec = _construct3(mod, dm.group(1)), _construct3(mod, dm.group(2))
        if not (nvec and tvec):
            continue
        d2, rr2 = bm.groups()
        _, d2d = _def(mod, d2)
        nm = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$', d2d)
        if not nm:
            continue
        _, ddd = _def(mod, nm.group(1))
        ddm = re.match(r'OpDot %float (%\w+) (%\w+)$', ddd)
        if not ddm or _construct3(mod, ddm.group(1)) != tvec \
                or _construct3(mod, ddm.group(2)) != tvec:
            continue
        _, rrd = _def(mod, rr2)
        rm = re.match(r'OpFMul %float (%\w+) (%\w+)$', rrd)
        if not rm or rm.group(1) != rm.group(2):
            continue
        _, rd = _def(mod, rm.group(1))
        ram = re.match(r'OpFAdd %float (%\w+) (%\w+)$', rd)
        if not ram:
            continue
        if not re.match(r'\s*OpSelectionMerge ' + re.escape(t_merge) + r' None\s*$',
                        mod.lines[i - 1]):
            die(f"{mod.name}: light guard at line {i+1} is not preceded by its "
                f"OpSelectionMerge {t_merge}")
        lit = labels.get(t_lit)
        merge = labels.get(t_merge)
        if lit != i + 1 or merge is None or merge < lit:
            die(f"{mod.name}: light guard at line {i+1}: lit block {t_lit} not "
                f"at line {i+2} or merge {t_merge} not below it")
        sq = re.match(r'\s*(%\w+)\s*=\s*OpExtInst %float %\w+ Sqrt '
                      + re.escape(d2) + r'\s*$', mod.lines[lit + 1])
        if not sq:
            continue
        traces = [j for j in range(lit, merge)
                  if re.match(r'\s*OpTraceRayKHR\b', mod.lines[j])]
        # the loop this guard lives in: the nearest OpLoopMerge above whose
        # merge label lies below the guard
        hdr = None
        for j in range(i - 1, fs, -1):
            lm = re.match(r'\s*OpLoopMerge (%\w+) (%\w+) None\s*$', mod.lines[j])
            if lm and labels.get(lm.group(1), -1) > i:
                hdr = (j, lm.group(1), lm.group(2))
                break
        if hdr is None:
            die(f"{mod.name}: light guard at line {i+1} is not inside a loop")
        hl = hdr[0]
        while not re.match(r'\s*%\w+ = OpLabel', mod.lines[hl]):
            hl -= 1
        hlab = re.match(r'\s*(%\w+) = OpLabel', mod.lines[hl]).group(1)
        mline = labels[hdr[1]]
        preds = [j for j in range(fs, fe)
                 if re.match(r'\s*OpBranch ' + re.escape(hlab) + r'\s*$',
                             mod.lines[j]) and not (hl <= j < mline)]
        if len(preds) != 1:
            die(f"{mod.name}: loop header {hlab} has {len(preds)} unconditional "
                f"predecessors outside the loop, want exactly 1 (the preheader)")
        pre = preds[0]
        if re.match(r'\s*Op(Selection|Loop)Merge\b', mod.lines[pre - 1]):
            pre -= 1
        rec = dict(line=i, ind=ind, cond=cond, merge=t_merge, lit=t_lit,
                   lit_line=lit, merge_line=merge, dot=dot, thr=thrv,
                   N=nvec, toLight=tvec, d2=d2, rangefail=om.group(2),
                   range_sum=rm.group(1), sqrt=sq.group(1),
                   traces=[t + 1 for t in traces], header_line=hl,
                   header=hlab, loop_merge=hdr[1], loop_continue=hdr[2],
                   preheader_line=pre)
        (sites if traces else declined).append(rec)
    return sites, declined


def find_record_colour(mod, site):
    """The light record's colour: the ONE stride-64 offset-16 v3float load
    between the loop header and the guard, and its three extracts."""
    hits = []
    for j in range(site['header_line'], site['line']):
        m = re.match(r'\s*(%\w+)\s*=\s*OpRawAccessChainNV %_ptr_StorageBuffer_v3float '
                     r'(%\w+) %uint_64 (%\w+) %uint_16 RobustnessPerElementNV\s*$',
                     mod.lines[j])
        if m:
            hits.append((j, m.group(1)))
    if len(hits) != 1:
        die(f"{mod.name}: light loop at line {site['line']+1}: {len(hits)} "
            f"stride-64 offset-16 record chains, want exactly 1 (the colour)")
    j, chain = hits[0]
    lm = re.match(r'\s*(%\w+)\s*=\s*OpLoad %v3float ' + re.escape(chain),
                  mod.lines[j + 1])
    if not lm:
        die(f"{mod.name}: colour chain {chain} not followed by its load")
    ld = lm.group(1)
    ext = {}
    for k in range(j + 2, min(j + 6, site['line'])):
        m = re.match(r'\s*(%\w+)\s*=\s*OpCompositeExtract %float '
                     + re.escape(ld) + r' (\d)\s*$', mod.lines[k])
        if m:
            ext[int(m.group(2))] = m.group(1)
    if sorted(ext) != [0, 1, 2]:
        die(f"{mod.name}: colour extracts incomplete: {sorted(ext)}")
    return [ext[0], ext[1], ext[2]]


def find_atten(mod, site, colour):
    """Inside the lit region: the three `FMul X colour_c`; X is the engine's
    atten x spot factor. Asserted one X for all three channels."""
    xs = set()
    for j in range(site['lit_line'], site['merge_line']):
        m = re.match(r'\s*%\w+\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$',
                     mod.lines[j])
        if not m:
            continue
        a, b = m.groups()
        for c in colour:
            if a == c and b not in colour:
                xs.add((c, b))
            elif b == c and a not in colour:
                xs.add((c, a))
    by_x = {}
    for c, x in xs:
        by_x.setdefault(x, set()).add(c)
    full = [x for x, cs in by_x.items() if len(cs) == 3]
    if len(full) != 1:
        die(f"{mod.name}: light loop at line {site['line']+1}: {len(full)} "
            f"factors multiply all three colour channels, want exactly 1 "
            f"(atten x spot); candidates {by_x}")
    x = full[0]
    _, xd = _def(mod, x)
    xm = re.match(r'OpFMul %float (%\w+) (%\w+)$', xd)
    if not xm:
        die(f"{mod.name}: atten x spot {x} is not an FMul: {xd}")
    kinds = []
    for o in xm.groups():
        _, od = _def(mod, o)
        kinds.append(od.split()[0] if od else '?')
    if sorted(kinds) != ['OpExtInst', 'OpSelect']:
        die(f"{mod.name}: atten x spot {x} operands are {kinds}, want "
            f"NClamp(spot) and Select(atten type)")
    return x


def clone_pure(mod, root, avail_line, fresh, out, fs):
    """Clone the def chain of `root` with fresh ids, stopping at ids defined at
    lines below `avail_line` (they dominate the splice: the guard block and
    everything the engine itself consumes there), at globals and at ids
    already in `fresh` (the re-pointed Sqrt). Pure ops only; a phi, a store,
    a Function-pointer load or an image op is a refusal, not a guess."""
    if root in fresh:
        return fresh[root]
    if not root.startswith('%'):
        return root
    ln, d = mod.find_def(root)
    if d is None or ln < fs or ln < avail_line:
        return root
    if not re.match(PURE_OPS, d):
        die(f"{mod.name}: clone_pure refuses {root} = {d.split()[0]} (defined "
            f"at line {ln+1}, inside the lit block, not pure)")
    if re.match(r'OpLoad %\w+ (%\w+)', d):
        pl, pd = _def(mod, re.match(r'OpLoad %\w+ (%\w+)', d).group(1))
        if 'Function' in (pd.split()[1] if pd else '') or \
                re.search(r'_ptr_Function_', pd):
            die(f"{mod.name}: clone_pure refuses a Function-variable load {root}")
    parts = d.split()
    newparts = [parts[0]]
    for p in parts[1:]:
        newparts.append(clone_pure(mod, p, avail_line, fresh, out, fs)
                        if p.startswith('%') else p)
    nid = mod.new_id()
    fresh[root] = nid
    out.append((nid, ' '.join(newparts)))
    return nid


def build(mod, rates, tint, k, mode='glow', decoy=None):
    consts, edits = [], []
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, ALL of them, before any edit ---------------------------
    writes = find_image_writes(mod)
    nee = find_nee_trace(mod, fs, fe)
    fetch_root = find_class_fetch(mod, fs, fe)
    offctor = find_origin_offset(mod, nee)
    counter, phdr = find_path_counter(mod, fs, fe)
    prim = _find_primary_ray(mod, fs, fe)
    sites, declined = find_light_sites(mod, fs, fe)
    if len(sites) != 1:
        die(f"{mod.name}: {len(sites)} light-sample sites with a shadow trace, "
            f"want exactly 1 (census, handoff/113 sec 2)")
    eb_lab, eb_term = entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability")
    accel = nee["ops"][0]
    origin_ids = _construct3(mod, nee["ops"][6])
    if not origin_ids:
        die(f"{mod.name}: sun-NEE origin {nee['ops'][6]} is not a v3 construct")
    site = sites[0]
    if site['N'] != offctor['normal']:
        die(f"{mod.name}: the light guard's normal {site['N']} is not the "
            f"origin-offset normal {offctor['normal']}")
    if prim['line'] > site['preheader_line'] or nee['line'] > site['preheader_line']:
        die(f"{mod.name}: primary ray (line {prim['line']+1}) or sun NEE (line "
            f"{nee['line']+1}) below the light loop's preheader "
            f"(line {site['preheader_line']+1})")
    colour = find_record_colour(mod, site)
    atten = find_atten(mod, site, colour)

    rep = {"mode": mode, "k": k, "decoy": decoy, "floor_m": FLOOR,
           "rates_1_per_m": [list(r) for r in rates], "tint": list(tint),
           "ray_flags_a": FLAGS_A, "ray_flags_a_names": FLAGS_A_NAMES,
           "ray_flags_b": FLAGS, "ray_flags_b_names": FLAGS_NAMES,
           "ray_flags_c": FLAGS_C, "tmin_b": TMIN, "tmax_b": TMAX,
           "push_c": PUSH, "tmin_c": TMIN_C, "reach_c": REACH,
           "bracket": [BRACKET_LO, BRACKET_HI, BRACKET_EPS],
           "gate_mask": GATE_MASK, "match_getter": GETTER_ID,
           "accel": accel, "origin": nee["ops"][6],
           "sun_nee_line": nee["line"] + 1,
           "path_counter": counter, "path_header": phdr,
           "primary_line": prim['line'] + 1,
           "site": {kk: (v + 1 if kk.endswith('_line') or kk == 'line' else v)
                    for kk, v in site.items()},
           "declined": [{"line": d['line'] + 1, "thr": d['thr'],
                         "why": "no shadow trace in the lit block "
                                "(the resampled loop)"} for d in declined],
           "colour": colour, "atten_spot": atten,
           "per_light_scales": "not applied (word 60 / flag bits)",
           "diag_scaled_by_light": mode == 'hit'}

    # ---- types / constants -------------------------------------------------
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")
    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u32 = _uc(mod, consts, 32)
    umask = _uc(mod, consts, GATE_MASK)
    uflags_b = _uc(mod, consts, FLAGS)
    uflags_a = _uc(mod, consts, FLAGS_A)          # C shares it (517)
    f0 = _fc(mod, consts, 0.0)
    f1 = _fc(mod, consts, 1.0)
    fhalf = _fc(mod, consts, 0.5)
    ftmin = _fc(mod, consts, TMIN)
    ftmax = _fc(mod, consts, TMAX)
    flo = _fc(mod, consts, BRACKET_LO)
    fhi = _fc(mod, consts, BRACKET_HI)
    feps = _fc(mod, consts, BRACKET_EPS)
    v3zero = _ensure_line(
        mod, consts,
        r'\s*(%\w+)\s*=\s*OpConstantComposite %v3float '
        + re.escape(f0) + r' ' + re.escape(f0) + r' ' + re.escape(f0) + r'\s*$',
        lambda n: f"    {n} = OpConstantComposite %v3float {f0} {f0} {f0}")
    fclamp = _fc(mod, consts, CLAMP)
    fpush = _fc(mod, consts, PUSH)
    ftmin_c = _fc(mod, consts, TMIN_C)
    freach = _fc(mod, consts, REACH)
    ffloor = _fc(mod, consts, FLOOR)
    seen = {}
    def fcm(v):                       # memoised: _fc cannot see pending consts
        key = float(v)
        if key not in seen:
            seen[key] = _fc(mod, consts, v)
        return seen[key]
    seen.update({0.0: f0, 1.0: f1, 0.5: fhalf, float(TMIN): ftmin,
                 float(TMAX): ftmax, float(BRACKET_LO): flo,
                 float(BRACKET_HI): fhi, float(BRACKET_EPS): feps,
                 float(CLAMP): fclamp, float(PUSH): fpush,
                 float(TMIN_C): ftmin_c, float(REACH): freach,
                 float(FLOOR): ffloor})
    if mode == 'hit':
        okc = [fcm(v) for v in DIAG_OK]
        rejc = [fcm(v) for v in DIAG_REJ]
        fthird = fcm(1.0 / 3.0)
    else:
        fk = fcm(k)
        frate = [[fcm(a) for a in pair] for pair in rates]
        ftint = [fcm(t) for t in tint]

    # ---- entry block: three MORE query objects + 3 accumulators ------------
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rqA, rqB, rqC = mod.new_id(), mod.new_id(), mod.new_id()
    gv = [mod.new_id() for _ in range(3)]
    ind0 = '               '
    edits.append((at, [f"{ind0}{rqA} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqB} = OpVariable {ptr_rq} Function",
                       f"{ind0}{rqC} = OpVariable {ptr_rq} Function"]
                  + [f"{ind0}{g} = OpVariable {ptrFF} Function" for g in gv]
                  + [f"{ind0}OpStore {g} {f0}" for g in gv]))
    nid = mod.new_id

    # ---- the PREHEADER: class gate, counter, query A, once per path vertex --
    ind = site['ind']
    pre = []
    cloned = []
    fetch_here = clone_chain(mod, fetch_root, safe, {}, cloned, fs)
    for cid, body in cloned:
        pre.append(f"{ind}{cid} = {body}")
    g_ext = nid(); pre.append(f"{ind}{g_ext} = OpCompositeExtract %uint {fetch_here} 1")
    g_and = nid(); pre.append(f"{ind}{g_and} = OpBitwiseAnd %uint {g_ext} %uint_4294967264")
    g_skin = nid(); pre.append(f"{ind}{g_skin} = OpIEqual {boolt} {g_and} {u32}")
    g_p0 = nid(); pre.append(f"{ind}{g_p0} = OpIEqual {boolt} {counter} {u0}")
    g_pre = nid(); pre.append(f"{ind}{g_pre} = OpLogicalAnd {boolt} {g_skin} {g_p0}")
    m_pre = nid(); pre.append(f"{ind}{m_pre} = OpSelect %uint {g_pre} {umask} {u0}")
    tA = nid(); pre.append(f"{ind}{tA} = OpFMul %float {prim['dot']} {prim['rsqrt']}")
    dA = nid(); pre.append(f"{ind}{dA} = OpCompositeConstruct %v3float "
                           f"{prim['V'][0]} {prim['V'][1]} {prim['V'][2]}")
    aLo = nid(); pre.append(f"{ind}{aLo} = OpFMul %float {tA} {flo}")
    aH0 = nid(); pre.append(f"{ind}{aH0} = OpFMul %float {tA} {fhi}")
    aHi = nid(); pre.append(f"{ind}{aHi} = OpFAdd %float {aH0} {feps}")
    pre.append(f"{ind}OpRayQueryInitializeKHR {rqA} {accel} {uflags_a} {m_pre} "
               f"{v3zero} {aLo} {dA} {aHi}")
    proA = nid(); pre.append(f"{ind}{proA} = OpRayQueryProceedKHR {boolt} {rqA}")
    ityA = nid(); pre.append(f"{ind}{ityA} = OpRayQueryGetIntersectionTypeKHR %uint {rqA} {u1}")
    hitA = nid(); pre.append(f"{ind}{hitA} = OpINotEqual {boolt} {ityA} {u0}")
    idA = nid(); pre.append(f"{ind}{idA} = {GETTER_ID} %uint {rqA} {u1}")
    g_hoist = nid(); pre.append(f"{ind}{g_hoist} = OpLogicalAnd {boolt} {g_pre} {hitA}")
    edits.append((site['preheader_line'] - 1, pre))
    rep["preheader_instructions"] = len(pre)
    rep["cloned_fetch_ops"] = len(cloned)

    # ---- the SITE: before the guard's OpSelectionMerge ---------------------
    ins = []
    d = nid(); ins.append(f"{ind}{d} = OpExtInst %float {glsl} Sqrt {site['d2']}")
    L = []
    for c in range(3):
        l = nid(); ins.append(f"{ind}{l} = OpFDiv %float {site['toLight'][c]} {d}")
        L.append(l)
    Lv = nid(); ins.append(f"{ind}{Lv} = OpCompositeConstruct %v3float {L[0]} {L[1]} {L[2]}")
    if decoy == 'front':
        # the gate WITHOUT the backlit arm: lights in front of the face glow
        backlit = nid(); ins.append(f"{ind}{backlit} = OpFOrdGreaterThanEqual {boolt} {site['dot']} {f0}")
    else:
        backlit = nid(); ins.append(f"{ind}{backlit} = OpFOrdLessThan {boolt} {site['dot']} {f0}")
    inr = nid(); ins.append(f"{ind}{inr} = OpLogicalNot {boolt} {site['rangefail']}")
    g_1 = nid(); ins.append(f"{ind}{g_1} = OpLogicalAnd {boolt} {g_hoist} {backlit}")
    g_all = nid(); ins.append(f"{ind}{g_all} = OpLogicalAnd {boolt} {g_1} {inr}")
    g_msk = nid(); ins.append(f"{ind}{g_msk} = OpSelect %uint {g_all} {umask} {u0}")
    # query B: the cull-front thickness query along L from the sun NEE's own
    # offset origin (101 sec 2 with S -> L)
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqB} {accel} {uflags_b} {g_msk} "
               f"{nee['ops'][6]} {ftmin} {Lv} {ftmax}")
    proB = nid(); ins.append(f"{ind}{proB} = OpRayQueryProceedKHR {boolt} {rqB}")
    ityB = nid(); ins.append(f"{ind}{ityB} = OpRayQueryGetIntersectionTypeKHR %uint {rqB} {u1}")
    hitB = nid(); ins.append(f"{ind}{hitB} = OpINotEqual {boolt} {ityB} {u0}")
    tqB = nid(); ins.append(f"{ind}{tqB} = OpRayQueryGetIntersectionTKHR %float {rqB} {u1}")
    tu = nid(); ins.append(f"{ind}{tu} = OpSelect %float {hitB} {tqB} {ftmax}")
    idB = nid(); ins.append(f"{ind}{idB} = {GETTER_ID} %uint {rqB} {u1}")
    same = nid(); ins.append(f"{ind}{same} = OpIEqual {boolt} {idA} {idB}")
    if decoy == 'nomatch':
        match = hitB
    else:
        match = nid(); ins.append(f"{ind}{match} = OpLogicalAnd {boolt} {hitB} {same}")
    # query C: light visibility from the exit point, reaching 0.8 d
    tp = nid(); ins.append(f"{ind}{tp} = OpFAdd %float {tu} {fpush}")
    off = nid(); ins.append(f"{ind}{off} = OpVectorTimesScalar %v3float {Lv} {tp}")
    org = nid(); ins.append(f"{ind}{org} = OpFAdd %v3float {nee['ops'][6]} {off}")
    r0 = nid(); ins.append(f"{ind}{r0} = OpFMul %float {d} {freach}")
    r1 = nid(); ins.append(f"{ind}{r1} = OpFSub %float {r0} {tp}")
    tmaxC = nid(); ins.append(f"{ind}{tmaxC} = OpExtInst %float {glsl} NMax {r1} {f0}")
    ins.append(f"{ind}OpRayQueryInitializeKHR {rqC} {accel} {uflags_a} {g_msk} "
               f"{org} {ftmin_c} {Lv} {tmaxC}")
    proC = nid(); ins.append(f"{ind}{proC} = OpRayQueryProceedKHR {boolt} {rqC}")
    ityC = nid(); ins.append(f"{ind}{ityC} = OpRayQueryGetIntersectionTypeKHR %uint {rqC} {u1}")
    hitC = nid(); ins.append(f"{ind}{hitC} = OpINotEqual {boolt} {ityC} {u0}")
    visC = nid(); ins.append(f"{ind}{visC} = OpLogicalNot {boolt} {hitC}")
    gm = nid(); ins.append(f"{ind}{gm} = OpLogicalAnd {boolt} {g_all} {match}")
    if decoy == 'noc':
        ok = gm
    else:
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {gm} {visC}")
    rej = nid(); ins.append(f"{ind}{rej} = OpLogicalAnd {boolt} {gm} {hitC}")
    rep.update(ok_id=ok, match_id=same, vis_id=visC, L=L, d=d)

    # the light's own unshadowed radiance: atten x spot cloned from the lit
    # block with the engine's Sqrt re-pointed to ours, times the record colour
    fresh = {site['sqrt']: d}
    cl = []
    att_here = clone_pure(mod, atten, site['lit_line'], fresh, cl, fs)
    for cid, body in cl:
        ins.append(f"{ind}{cid} = {body}")
    rep["cloned_atten_ops"] = len(cl)
    Ec = []
    for c in range(3):
        e = nid(); ins.append(f"{ind}{e} = OpFMul %float {att_here} {colour[c]}")
        Ec.append(e)
    # the entry-face Lambert on the FAR side: NMax(-N.L, 0) with L normalised
    ndl = nid(); ins.append(f"{ind}{ndl} = OpFDiv %float {site['dot']} {d}")
    bnd = nid(); ins.append(f"{ind}{bnd} = OpFNegate %float {ndl}")
    w = nid(); ins.append(f"{ind}{w} = OpExtInst %float {glsl} NMax {bnd} {f0}")

    if mode == 'hit':
        lum0 = nid(); ins.append(f"{ind}{lum0} = OpFAdd %float {Ec[0]} {Ec[1]}")
        lum1 = nid(); ins.append(f"{ind}{lum1} = OpFAdd %float {lum0} {Ec[2]}")
        lum = nid(); ins.append(f"{ind}{lum} = OpFMul %float {lum1} {fthird}")
        lw = nid(); ins.append(f"{ind}{lw} = OpFMul %float {lum} {w}")
        for c in range(3):
            s0 = nid(); ins.append(f"{ind}{s0} = OpSelect %float {rej} {rejc[c]} {f0}")
            s1 = nid(); ins.append(f"{ind}{s1} = OpSelect %float {ok} {okc[c]} {s0}")
            s2 = nid(); ins.append(f"{ind}{s2} = OpFMul %float {s1} {lw}")
            s3 = nid(); ins.append(f"{ind}{s3} = OpExtInst %float {glsl} NMin {s2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {s3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    else:
        kg = nid(); ins.append(f"{ind}{kg} = OpSelect %float {ok} {fk} {f0}")
        kw = nid(); ins.append(f"{ind}{kw} = OpFMul %float {kg} {w}")
        te = nid(); ins.append(f"{ind}{te} = OpExtInst %float {glsl} NMax {tu} {ffloor}")
        for c in range(3):
            if decoy == 'flatk':
                tr = ftint[c]
            else:
                e1 = nid(); ins.append(f"{ind}{e1} = OpFMul %float {te} {frate[c][0]}")
                e2 = nid(); ins.append(f"{ind}{e2} = OpFNegate %float {e1}")
                e3 = nid(); ins.append(f"{ind}{e3} = OpExtInst %float {glsl} Exp {e2}")
                e4 = nid(); ins.append(f"{ind}{e4} = OpFMul %float {te} {frate[c][1]}")
                e5 = nid(); ins.append(f"{ind}{e5} = OpFNegate %float {e4}")
                e6 = nid(); ins.append(f"{ind}{e6} = OpExtInst %float {glsl} Exp {e5}")
                e7 = nid(); ins.append(f"{ind}{e7} = OpFAdd %float {e3} {e6}")
                e8 = nid(); ins.append(f"{ind}{e8} = OpFMul %float {e7} {fhalf}")
                tr = nid(); ins.append(f"{ind}{tr} = OpFMul %float {e8} {ftint[c]}")
            m1 = nid(); ins.append(f"{ind}{m1} = OpFMul %float {tr} {kw}")
            m2 = nid(); ins.append(f"{ind}{m2} = OpFMul %float {m1} {Ec[c]}")
            m3 = nid(); ins.append(f"{ind}{m3} = OpExtInst %float {glsl} NMin {m2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {m3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    # before the OpSelectionMerge (line-1), which must stay glued to the branch
    edits.append((site['line'] - 2, ins))
    rep["splice_instructions"] = len(ins)
    rep["rq_vars"] = [rqA, rqB, rqC]
    rep["accum_vars"] = gv

    # ---- ADD the accumulated term at every radiance write -------------------
    added, skipped = [], []
    for wr in writes:
        if wr['comps'] is None:
            die(f"{mod.name}: write at line {wr['line']+1} has a non-construct "
                f"texel -- refusing")
        c = wr['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({"line": wr['line'] + 1, "why": "constant-zero"})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({"line": wr['line'] + 1, "why": "scalar-broadcast"})
            continue
        wind = re.match(r'(\s*)', mod.lines[wr['line']]).group(1)
        wi, newc = [], []
        for ch in range(3):
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {gv[ch]}")
            a = nid(); wi.append(f"{wind}{a} = OpFAdd %float {c[ch]} {l}")
            newc.append(a)
        nt = nid()
        wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                  f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((wr['line'] - 1, wi))
        mod.lines[wr['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[wr['line']])
        added.append({"line": wr['line'] + 1})
    if not added:
        die(f"{mod.name}: no radiance write to add the term at")
    rep["writes_added"], rep["writes_skipped"] = added, skipped
    return consts, edits, rep


def process(path, outdir, rates, tint, k, mode='glow', decoy=None, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    if mode == 'ctl':
        rep['earglow_ll'] = {"mode": "control", "emitted": 0,
                             "why": "ctl: identity, no instructions"}
    else:
        consts, edits, rep['earglow_ll'] = build(mod, rates, tint, k, mode, decoy)
        apply_edits(mod, consts, edits)
        _add_header(mod)
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', spv_out],
                       capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--model', required=True, help='111 v7 model json (r6lo.json)')
    ap.add_argument('--k-scale', type=float, default=1.0)
    ap.add_argument('--mode', default='glow', choices=('glow', 'hit', 'ctl'))
    ap.add_argument('--decoy', choices=('noc', 'nomatch', 'flatk', 'front'),
                    default=None, help='a deliberately WRONG build, so '
                    'verify_earglow_ll.py can be shown to reject it')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    rates, tint, k, _ = load_model(a.model)
    print(json.dumps(process(a.spvasm, a.outdir, rates, tint, k * a.k_scale,
                             a.mode, a.decoy, do_rt=not a.no_roundtrip_check)))


if __name__ == '__main__':
    main()
