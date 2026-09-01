#!/usr/bin/env python3
"""Skin-only sample count in rgs_reference_main (handoff/29 part B4, handoff/77).

"More rays only on skin": class-1 pixels path-trace SPP samples per pixel,
everything else keeps the engine's own count. Gated on the G-U5 sentinel
(handoff/56 -- an injected trace executes in this family; here we do not even
need that, we only add ITERATIONS of the existing site, the shape ptbounce
already ships).

What 29 sec B4 did not know, and this build is shaped by (handoff/77 sec 1):
the engine's own sample loop EXISTS and is LIVE in the runtime-bound
permutations. cbv[188].y is the sample count (RayNumber): the loop header
phis carry the LCG state, the radiance accumulators and a counter, the latch
compares the counter against cbv[188].y, and every per-sample NEE/MIS weight
divides by the same read. Only the four baked permutations (29 sec B3's
literal-bound list) have it constant-folded to the degenerate skeleton that
29 sec B4 describes.

So there are two tiers, auto-detected per module:

  dyn    (8-of-12 shape) The engine loop is live. Compute once, early:
             isSkin = (gbuf1.y & ~31) == 32        (the 29 sec B2 gate)
             eff    = isSkin && rayN != 0 ? max(rayN, SPP) : rayN
         and replace the USES of every cbv[188].y read at/after the loop
         header with eff -- the loop bound, the per-sample 1/N weights, and
         the accumulation-mode divide all follow the same per-pixel count,
         so normalization is exact by construction. RNG threading and
         accumulator wiring are the engine's own. Reads BEFORE the header
         (the seed stride at entry, the rayN==0 skip gate) stay engine-wide.

  baked  (4-of-12 shape) The 29 sec B4 surgery, on the outermost degenerate
         loop (continue block referenced exactly twice = def + OpLoopMerge):
           * the old merge block becomes the CONTINUE block -- every existing
             branch to it (from inside nested selections) is then a legal
             continue, which is why this direction is chosen over inserting
             a new latch block;
           * its K leading OpPhi %half per-sample results are accumulated
             there, counter++ and a remixed seed follow, and the terminator
             becomes  BranchConditional (ctr < N) header, new-merge;
           * the new merge starts with avg = acc * OpSelect(isSkin, 1/N, 1)
             and takes over the old merge's post-phi code; downstream uses
             of the old phi ids are rewritten to the averages, downstream
             OpPhi incoming labels naming the old merge are repointed;
           * the header gets phis for ctr / acc[K] / seed; the bounce-level
             RNG phi (the one feeding OpIMul x 1664525) has its from-header
             incoming rewired to the seed phi so samples decorrelate.
         Deviation from 29 sec B4 as written: the seed is REMIXED per sample
         (seed' = seed*747796405 + 2891336453, a distinct LCG) instead of
         threading the body's exit-state LCG value, which does not dominate
         the continue block. The engine's own live loop does thread it; the
         remix gives an equally decorrelated but different stream. Known
         residual risk, priced in handoff/77 sec 4: the baked family's 22
         in-body storage-buffer record writes now run N times (last write
         wins); 14 are inside the RNG cone, so their consumers see the LAST
         sample's record rather than the only sample's. The spp<N>d rung
         exists to separate that risk on screen.

The skin gate is cloned by id from the module's own post-loop class fetch
(the 55 discipline): every instruction of the fetch chain defined after the
insertion point is re-emitted with fresh ids, operands that already dominate
(pixel coords, descriptor array, push constants) are referenced verbatim.

Usage:
  patch_skin_spp.py IN.spvasm --spp 4 --outdir D            # auto tier
  patch_skin_spp.py IN.spvasm --probe                       # print tier, no build
  patch_skin_spp.py IN.spvasm --spp 4 --outdir D --expect dyn|baked
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import die, roundtrip_check
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

REMIX_MUL, REMIX_ADD = 747796405, 2891336453   # PCG-style, != the module's 1664525
IDT = '               '


def _tok_replace(line, old, new):
    return re.sub(r'(?<![\w%])' + re.escape(old) + r'(?![\w])', new, line)


def _find_def(L, tok):
    pat = re.compile(r'^\s*' + re.escape(tok) + r'\s*=\s*(.*)$')
    for i, ln in enumerate(L):
        m = pat.match(ln)
        if m:
            return i, m.group(1)
    return None, None


def _glsl_import(L):
    for ln in L:
        m = re.match(r'\s*(%\w+) = OpExtInstImport "GLSL.std.450"', ln)
        if m:
            return m.group(1)
    die("no GLSL.std.450 import")


def _ensure(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def _uc(mod, consts, v):
    nid, decl = mod.uconst(v)
    if decl and decl not in consts:
        consts.append(decl)
    return nid


def _hconst(mod, consts, text_variants, literal):
    """find an OpConstant %half among text_variants, else create with literal."""
    for tv in text_variants:
        for ln in mod.lines:
            m = re.match(r'\s*(%\w+) = OpConstant %half ' + re.escape(tv) + r'\s*$', ln)
            if m:
                return m.group(1)
    nid = mod.new_id()
    consts.append(f"    {nid} = OpConstant %half {literal}")
    return nid


# ---------------------------------------------------------------- detection

def find_rayn_reads(L):
    """[(acc_line, extract_line, extract_id, base_var)] for cbv[.][188].y reads."""
    out = []
    for i, ln in enumerate(L):
        m = re.search(r'(%\w+) = OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_188\s*$', ln)
        if not m:
            continue
        acc, base = m.groups()
        ld = bc = None
        for j in range(i + 1, min(i + 5, len(L))):
            m2 = re.match(r'\s*(%\w+) = OpLoad %v4float ' + re.escape(acc) + r'\s*$', L[j])
            if m2:
                ld = m2.group(1)
                continue
            if ld:
                m3 = re.match(r'\s*(%\w+) = OpBitcast %v4uint ' + re.escape(ld) + r'\s*$', L[j])
                if m3:
                    bc = m3.group(1)
                    continue
            if bc:
                m4 = re.match(r'\s*(%\w+) = OpCompositeExtract %uint ' + re.escape(bc) + r' 1\s*$', L[j])
                if m4:
                    out.append((i, j, m4.group(1), base))
                    break
    return out


def find_degenerate_outer(L):
    """the outermost degenerate loop: continue block referenced exactly twice
    (its own OpLabel + the OpLoopMerge) and containing only OpBranch header.
    Returns dict or None."""
    refs = {}
    for i, ln in enumerate(L):
        for t in re.findall(r'%[\w]+', ln):
            refs.setdefault(t, []).append(i)
    cands = []
    for i, ln in enumerate(L):
        m = re.match(r'\s*OpLoopMerge (%\w+) (%\w+)', ln)
        if not m:
            continue
        mg, ct = m.groups()
        r = refs.get(ct, [])
        if len(r) != 2:
            continue
        dl = [j for j in r if re.match(r'\s*' + re.escape(ct) + r' = OpLabel', L[j])]
        if not dl:
            continue
        cd = dl[0]
        bm = re.match(r'\s*OpBranch (%\w+)\s*$', L[cd + 1])
        if not bm:
            continue
        hj = next(j for j in range(i, -1, -1) if re.match(r'\s*%\w+ = OpLabel', L[j]))
        hdr = re.match(r'\s*(%\w+) = OpLabel', L[hj]).group(1)
        if bm.group(1) != hdr:
            continue
        md, _ = _find_def(L, mg)
        cands.append(dict(lm=i, hdr=hdr, hj=hj, merge=mg, md=md, cont=ct, cd=cd,
                          span=cd - i))
    if not cands:
        return None
    outer = max(cands, key=lambda c: c['span'])
    for c in cands:
        if c is not outer and not (outer['hj'] < c['lm'] and c['cd'] < outer['cd']):
            die(f"degenerate loop at line {c['lm']+1} not nested in the outermost "
                f"({outer['hj']+1}..{outer['cd']+1}) -- shape assumption broken")
    body = '\n'.join(L[outer['hj']:outer['md']])
    if 'OpTraceRayKHR' not in body:
        die("outermost degenerate loop has no OpTraceRayKHR in its body")
    return outer


def detect_tier(L):
    reads = find_rayn_reads(L)
    if reads:
        return 'dyn', reads
    return 'baked', []


# ---------------------------------------------------------------- skin gate

def clone_class_fetch(mod, consts, ins_line):
    """Clone the module's class fetch (BitwiseAnd ~31 on gbuf1.y) so it is
    available at ins_line; every chain instruction defined AFTER ins_line is
    re-emitted with a fresh id, earlier defs are referenced verbatim.
    Returns (lines, isSkin_id, report)."""
    L = mod.lines
    ands = [(i, ln) for i, ln in enumerate(L)
            if re.search(r'= OpBitwiseAnd %uint %\w+ %uint_4294967264\s*$', ln)]
    if len(ands) != 1:
        die(f"expected exactly 1 class-mask BitwiseAnd, found {len(ands)}")
    ai, aln = ands[0]
    # transitive closure of operands with def line > ins_line
    need, order, seen = [ai], [], {ai}
    while need:
        i = need.pop()
        order.append(i)
        for t in re.findall(r'%[\w]+', L[i])[1:]:
            di, _ = _find_def(L, t)
            if di is not None and di > ins_line and di not in seen \
               and re.match(r'\s*%[\w]+ = Op', L[di]):
                seen.add(di)
                need.append(di)
    order.sort()
    remap, out = {}, []
    for i in order:
        m = re.match(r'\s*(%[\w]+) = (.*)$', L[i])
        rid, body = m.groups()
        nid = mod.new_id()
        remap[rid] = nid
        for old, new in remap.items():
            body = _tok_replace(body, old, new)
        out.append(f"{IDT}{nid} = {body}")
    boolt = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                    lambda n: f"    {n} = OpTypeBool")
    u32 = _uc(mod, consts, 32)
    skin = mod.new_id()
    and_id = aln.strip().split()[0]
    out.append(f"{IDT}{skin} = OpIEqual {boolt} {remap[and_id]} {u32}")
    rep = dict(cloned=len(order), from_and_line=ai + 1)
    return out, skin, boolt, rep


# ---------------------------------------------------------------- dyn tier

def patch_dyn(mod, spp, reads):
    L = mod.lines
    consts, rep = [], {}
    glsl = _glsl_import(L)
    # the rayN==0 skip gate names the block that dominates the loop
    gates = []
    for (accl, extl, eid, base) in reads:
        for j in range(extl + 1, min(extl + 4, len(L))):
            if re.search(r'= OpIEqual %bool ' + re.escape(eid) + r' %uint_0\s*$', L[j]):
                gates.append((extl, j, eid))
    if len(gates) != 1:
        die(f"expected exactly 1 rayN==0 gate, found {len(gates)}")
    gate_ext, gate_eq, gate_eid = gates[0]
    # insertion point: just before the OpSelectionMerge that follows the gate
    smi = next((j for j in range(gate_eq + 1, gate_eq + 4)
                if re.match(r'\s*OpSelectionMerge ', L[j])), None)
    if smi is None:
        die("no OpSelectionMerge after the rayN==0 gate")
    ins = smi - 1   # insert AFTER this line
    # the loop header: latch = ULessThan whose rhs is a .y extract, feeding a
    # backward conditional branch
    hdr_line = None
    for (accl, extl, eid, base) in reads:
        for j in range(extl + 1, min(extl + 4, len(L))):
            m = re.match(r'\s*(%\w+) = OpULessThan %bool (%\w+) ' + re.escape(eid), L[j])
            if m:
                # the conditional may sit a few OpStores below the compare
                # (the 21a92f1a-shaped structurization spills loop state to
                # variables in the latch)
                for k in range(j + 1, min(j + 30, len(L))):
                    m2 = re.match(r'\s*OpBranchConditional ' + re.escape(m.group(1))
                                  + r' (%\w+) (%\w+)', L[k])
                    if m2:
                        hj, _ = _find_def(L, m2.group(1))
                        if hj is not None and hj < j:
                            hdr_line = hj
                        break
                    if re.match(r'\s*(Op(Branch|Return|Switch|Unreachable)\b|%\w+ = OpLabel)', L[k].strip()):
                        break
    if hdr_line is None:
        die("no sample-loop latch (ULessThan on a cbv[188].y read) found")
    if ins >= hdr_line:
        die("insertion point is not above the sample-loop header")
    # build the gate + effective count at ins
    lines, skin, boolt, crep = clone_class_fetch(mod, consts, ins)
    base = reads[0][3]
    a, ld, bc, ext = (mod.new_id() for _ in range(4))
    uN = _uc(mod, consts, spp)
    u0 = _uc(mod, consts, 0)
    nz, andg, mx, eff = (mod.new_id() for _ in range(4))
    lines += [
        f"{IDT}{a} = OpAccessChain %_ptr_Uniform_v4float {base} %uint_0 %uint_188",
        f"{IDT}{ld} = OpLoad %v4float {a}",
        f"{IDT}{bc} = OpBitcast %v4uint {ld}",
        f"{IDT}{ext} = OpCompositeExtract %uint {bc} 1",
        f"{IDT}{nz} = OpINotEqual {boolt} {ext} {u0}",
        f"{IDT}{andg} = OpLogicalAnd {boolt} {skin} {nz}",
        f"{IDT}{mx} = OpExtInst %uint {glsl} UMax {ext} {uN}",
        f"{IDT}{eff} = OpSelect %uint {andg} {mx} {ext}",
    ]
    # replace uses of every .y extract at/after the header with eff
    patched = []
    for (accl, extl, eid, _b) in reads:
        if extl <= hdr_line and extl != gate_ext:
            # pre-loop non-gate reads (seed stride) stay engine-wide
            continue
        if extl == gate_ext:
            continue
        n = 0
        for i in range(len(L)):
            if i == extl:
                continue
            if re.search(r'(?<![\w%])' + re.escape(eid) + r'(?![\w])', L[i]):
                L[i] = _tok_replace(L[i], eid, eff)
                n += 1
        patched.append(dict(extract_line=extl + 1, uses=n))
    if not patched:
        die("dyn tier found no in-loop RayNumber reads to patch")
    L[ins + 1:ins + 1] = lines
    fidx = next(i for i, ln in enumerate(L) if ' OpFunction ' in ln)
    L[fidx:fidx] = consts
    rep.update(tier='dyn', spp=spp, gate=crep, sites=patched,
               header_line=hdr_line + 1, eff_id=eff)
    return rep


# ---------------------------------------------------------------- baked tier

def patch_baked(mod, spp):
    L = mod.lines
    consts, rep = [], {}
    outer = find_degenerate_outer(L)
    if outer is None:
        die("baked tier: no degenerate outer loop")
    hj, lm, md, cd = outer['hj'], outer['lm'], outer['md'], outer['cd']
    hdr, mg, ct = outer['hdr'], outer['merge'], outer['cont']
    if re.match(r'\s*%\w+ = OpPhi ', L[hj + 1]):
        die("outer header already has phis -- not the folded skeleton")
    # single external pred branching to header
    preds = [i for i, ln in enumerate(L)
             if re.match(r'\s*OpBranch ' + re.escape(hdr) + r'\s*$', ln) and i != cd + 1]
    if len(preds) != 1:
        die(f"expected exactly 1 pred branch to {hdr}, found {len(preds)}")
    pb = preds[0]
    plj = next(j for j in range(pb, -1, -1) if re.match(r'\s*%\w+ = OpLabel', L[j]))
    pred_lbl = re.match(r'\s*(%\w+) = OpLabel', L[plj]).group(1)
    # merge phis (per-sample results)
    phis = []
    i = md + 1
    while True:
        m = re.match(r'\s*(%[\w]+) = OpPhi (%\w+) ', L[i])
        if not m:
            break
        if m.group(2) != '%half':
            die(f"merge phi {m.group(1)} is {m.group(2)}, expected %half")
        phis.append(m.group(1))
        i += 1
    mp_end = i - 1
    if not 1 <= len(phis) <= 8:
        die(f"unexpected merge phi count {len(phis)}")
    # the bounce-level RNG phi: incoming-from-header, feeds IMul by 1664525
    rngs = []
    for i2, ln in enumerate(L):
        m = re.match(r'\s*(%[\w]+) = OpPhi %uint (.*)$', ln)
        if not m:
            continue
        pairs = m.group(2).split()
        if hdr not in pairs:
            continue
        rid = m.group(1)
        if any(re.search(r'= OpIMul %uint ' + re.escape(rid) + r' %uint_1664525\s*$', l2)
               for l2 in L):
            s0 = pairs[pairs.index(hdr) - 1]
            rngs.append((i2, rid, s0))
    if len(rngs) != 1:
        die(f"expected exactly 1 RNG phi (IMul x 1664525), found {len(rngs)}")
    rng_line, rng_id, s0 = rngs[0]
    # constants and ids
    boolt = _ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                    lambda n: f"    {n} = OpTypeBool")
    u0, u1 = _uc(mod, consts, 0), _uc(mod, consts, 1)
    uN = _uc(mod, consts, spp)
    umul, uadd = _uc(mod, consts, REMIX_MUL), _uc(mod, consts, REMIX_ADD)
    h0 = _hconst(mod, consts, ['0x0p+0'], '0x0p+0')
    h1 = _hconst(mod, consts, ['0x1p+0'], '0x1p+0')
    hinv = _hconst(mod, consts, [], repr(1.0 / spp))
    gate_lines, skin, _bt, crep = clone_class_fetch(mod, consts, pb - 1)
    nid = mod.new_id
    N, invN = nid(), nid()
    gate_lines += [
        f"{IDT}{N} = OpSelect %uint {skin} {uN} {u1}",
        f"{IDT}{invN} = OpSelect %half {skin} {hinv} {h1}",
    ]
    ctr, ctrN, seed, t1, seed2, more, mnew = (nid() for _ in range(7))
    accs = [nid() for _ in phis]
    acc2s = [nid() for _ in phis]
    avgs = [nid() for _ in phis]
    # ---- tail rewrites first (indices unshifted): after the old merge's phi
    # block, uses of the per-sample phi ids become the averages, and OpPhi
    # incoming labels naming the old merge become the new merge.
    renamed_uses = 0
    repointed = 0
    for i2 in range(mp_end + 1, len(L)):
        ln = L[i2]
        for pk, av in zip(phis, avgs):
            if re.search(r'(?<![\w%])' + re.escape(pk) + r'(?![\w])', ln):
                ln = _tok_replace(ln, pk, av)
                renamed_uses += 1
        if ' = OpPhi ' in ln and re.search(r'(?<![\w%])' + re.escape(mg) + r'(?![\w])', ln):
            ln = _tok_replace(ln, mg, mnew)
            repointed += 1
        L[i2] = ln
    # RNG phi: from-header incoming value -> seed phi (exact pair)
    L[rng_line] = re.sub(re.escape(s0) + r'(\s+)' + re.escape(hdr),
                         seed + r'\g<1>' + hdr, L[rng_line], count=1)
    # ---- structural edits, bottom-up ------------------------------------
    # 5. continue-block tail: accumulate + count + remix + conditional
    #    back-edge, then the new merge label and the averages (insert after
    #    mp_end; the old post-phi code then belongs to the new merge block).
    tail = []
    for pk, ac, a2 in zip(phis, accs, acc2s):
        tail.append(f"{IDT}{a2} = OpFAdd %half {ac} {pk}")
    tail += [
        f"{IDT}{ctrN} = OpIAdd %uint {ctr} {u1}",
        f"{IDT}{t1} = OpIMul %uint {seed} {umul}",
        f"{IDT}{seed2} = OpIAdd %uint {t1} {uadd}",
        f"{IDT}{more} = OpULessThan {boolt} {ctrN} {N}",
        f"{IDT}OpBranchConditional {more} {hdr} {mnew}",
        f"      {mnew} = OpLabel",
    ]
    for a2, av in zip(acc2s, avgs):
        tail.append(f"{IDT}{av} = OpFMul %half {a2} {invN}")
    L[mp_end + 1:mp_end + 1] = tail
    # 4. delete the dead continue block (label + OpBranch) -- indices below
    #    mp_end are unaffected by the insert above only if cd > mp_end is
    #    false; cd < md always (continue defined before merge), so adjust.
    del_at = cd if cd < mp_end + 1 else cd + len(tail)
    if not re.match(r'\s*' + re.escape(ct) + r' = OpLabel', L[del_at]):
        die("internal: dead-continue index drifted")
    del L[del_at:del_at + 2]
    # 3. header phis + retargeted OpLoopMerge (cd > lm > hj > pb, so the
    #    deletion above shifted none of them; edits below go top-down last)
    if not pb < hj < lm:
        die("internal: pred/header/loopmerge text order violated")
    hdr_ins = [
        f"{IDT}{ctr} = OpPhi %uint {u0} {pred_lbl} {ctrN} {mg}",
    ]
    for pk, ac, a2 in zip(phis, accs, acc2s):
        hdr_ins.append(f"{IDT}{ac} = OpPhi %half {h0} {pred_lbl} {a2} {mg}")
    hdr_ins.append(f"{IDT}{seed} = OpPhi %uint {s0} {pred_lbl} {seed2} {mg}")
    assert 'OpLoopMerge' in L[lm]
    L[lm] = f"{IDT}OpLoopMerge {mnew} {mg} None"
    L[hj + 1:hj + 1] = hdr_ins
    # 1. gate + N + invN at the end of the pred block (before its OpBranch)
    L[pb:pb] = gate_lines
    fidx = next(i for i, ln in enumerate(L) if ' OpFunction ' in ln)
    L[fidx:fidx] = consts
    rep.update(tier='baked', spp=spp, gate=crep, header=hdr, old_merge=mg,
               new_merge=mnew, merge_phis=len(phis), rng_phi=rng_id,
               tail_use_renames=renamed_uses, phi_labels_repointed=repointed,
               dead_continue_removed=ct)
    return rep


# ---------------------------------------------------------------- driver

def process(path, outdir, spp, expect):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    tier, reads = detect_tier(mod.lines)
    if expect and tier != expect:
        die(f"{mod.name}: detected tier {tier}, --expect {expect}")
    n_traces = sum('OpTraceRayKHR' in ln for ln in mod.lines)
    rep = dict(module=mod.name, ident=mod.ident, tier=tier, spp=spp)
    if problems:
        rep['module_warnings'] = problems
    if tier == 'dyn':
        rep['skin_spp'] = patch_dyn(mod, spp, reads)
    else:
        rep['skin_spp'] = patch_baked(mod, spp)
    if sum('OpTraceRayKHR' in ln for ln in mod.lines) != n_traces:
        die(f"{mod.name}: trace count changed -- this patch must not add traces")
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out, '-o', spv_out],
                       capture_output=True, text=True)
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--spp', type=int, default=4)
    ap.add_argument('--outdir')
    ap.add_argument('--probe', action='store_true',
                    help='print the detected tier and exit')
    ap.add_argument('--expect', choices=('dyn', 'baked'))
    args = ap.parse_args()
    if args.probe:
        mod, _ = load_lenient(args.spvasm)
        tier, reads = detect_tier(mod.lines)
        print(json.dumps(dict(module=mod.name, ident=mod.ident, tier=tier,
                              rayn_reads=len(reads))))
        return
    if not args.outdir:
        ap.error('--outdir required unless --probe')
    if not 2 <= args.spp <= 16:
        ap.error('--spp out of range [2,16]')
    print(json.dumps(process(args.spvasm, args.outdir, args.spp, args.expect)))


if __name__ == '__main__':
    main()
