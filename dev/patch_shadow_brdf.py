#!/usr/bin/env python3
"""
patch_shadow_brdf.py -- the rgs_shadow_main anchor family.

Why this exists (dev/HAIR_HANDOFF.md, handoff/04-RESET-STATE.md): every live
session dispatches the shadow raygens and never rgs_reference_main, so the
reference-anchored patcher (patch_skin_brdf.py) produces builds that are
correct but never execute. The shading maths in rgs_shadow_main is the same
family -- 1/pi diffuse evals, gbuf>>5 material classes -- but three structural
facts break the reference anchors, and each one is handled here:

  1. classify_triples() intersects the multiplicand leaves of ALL triples to
     find the one albedo triple. The reference raygen has a single shading
     context; rgs_shadow_main has many inlined ones (23 in b80f16ff), so that
     intersection is empty. Here triples are GROUPED by their multiplicand
     tuple instead, and the channel is the position within the triple -- the
     three FMuls are consecutive and already in r,g,b order.

  2. The albedo operands are OpPhi values, not FMul chains, so resolve_leaf()
     has nothing to walk. Nothing needs walking: the phi ids are the channels.

  3. The decisive one -- the game's own skin gate does NOT dominate any eval
     site (verified 0/23, 0/13, 0/3 across the four dispatched modules). The
     reference patcher's trick of inserting an OpIEqual beside the game's own
     test and referencing it at the eval sites cannot work here; it would emit
     SPIR-V that fails validation on dominance. Neither the gate, the shifted
     class value, nor the G-buffer descriptor load dominates.

     What DOES dominate all sites is the pixel coordinate pair feeding the
     G-buffer fetch. So the class is REFETCHED at each site from module-scope
     descriptors plus those coordinates -- the same tactic, and the same
     rationale, as find_normal_gbuffer()/emit_nfetch() in patch_skin_brdf.py,
     where NoV is recomputed at the splice for exactly this reason.

Dominance is not assumed anywhere: the CFG is built, reachability and
dominators are computed, and any site whose inputs do not dominate is SKIPPED
and reported rather than silently emitted as invalid SPIR-V.

Tiers:
  forcetint -- ungated tint at every triple. Needs no class fetch, so it
               isolates "does this raygen execute at all" from every gate and
               class question. Run this FIRST.
  hairhunt  -- per-class palette tint (class 1 = skin = red = the control),
               gated on the refetched material class.

Usage:
  python3 dev/patch_shadow_brdf.py <dump>.spvasm --tier forcetint --outdir swaps/
  python3 dev/patch_shadow_brdf.py <dump>.spvasm --tier hairhunt  --outdir swaps/
"""

import argparse, json, os, re, subprocess, sys, hashlib, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import (Module, find_triples, replace_single_use,
                             apply_edits, roundtrip_check, HUNT_PALETTE,
                             HUNT_DEFAULT, die)

# ------------------------------------------------------------------ CFG
TERMINATORS = ('OpReturn', 'OpReturnValue', 'OpKill', 'OpUnreachable',
               'OpTerminateInvocation', 'OpIgnoreIntersectionKHR',
               'OpTerminateRayKHR')


def build_blocks(mod):
    """Split the module into basic blocks with their successor labels."""
    bs, cur = [], None
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel\s*$', ln)
        if m:
            cur = dict(label=m.group(1), start=i, end=None, succ=[])
            bs.append(cur)
            continue
        if cur is None:
            continue
        s = ln.strip()
        head = s.split(' ')[0]
        if head == 'OpBranchConditional':
            cur['succ'] = re.findall(r'%\w+', s)[1:3]
        elif head == 'OpBranch':
            cur['succ'] = re.findall(r'%\w+', s)[:1]
        elif head == 'OpSwitch':
            # operands: selector, default, then (literal, label) pairs; the
            # literals are plain integers so %-tokens are exactly the labels.
            cur['succ'] = re.findall(r'%\w+', s)[1:]
        elif head in TERMINATORS:
            pass
        else:
            continue
        cur['end'] = i
        cur = None
    return bs


def dominators(bs):
    """Iterative dominators over the blocks REACHABLE from the entry block.

    Unreachable blocks are excluded rather than treated as un-dominated:
    dxil-spirv emits dead `OpUnreachable` merge blocks (49 of them in
    b80f16ff), and counting those as failures would mask real ones.
    """
    succ = {b['label']: b['succ'] for b in bs}
    entry = bs[0]['label']
    seen, stack = {entry}, [entry]
    while stack:
        for s in succ.get(stack.pop(), []):
            if s in succ and s not in seen:
                seen.add(s)
                stack.append(s)
    R = [b for b in bs if b['label'] in seen]
    preds = {b['label']: [] for b in R}
    for b in R:
        for s in b['succ']:
            if s in preds:
                preds[s].append(b['label'])
    dom = {b['label']: set(seen) for b in R}
    dom[entry] = {entry}
    changed = True
    while changed:
        changed = False
        for b in R[1:]:
            l = b['label']
            ps = [dom[p] for p in preds[l] if p in dom]
            new = (set.intersection(*ps) if ps else set()) | {l}
            if new != dom[l]:
                dom[l] = new
                changed = True
    return dom, seen


class CFG:
    def __init__(self, mod):
        self.blocks = build_blocks(mod)
        if not self.blocks:
            die(f"{mod.name}: no basic blocks found")
        self.dom, self.reachable = dominators(self.blocks)
        self.mod = mod

    def block_of(self, line):
        best = None
        for b in self.blocks:
            if b['start'] <= line and (b['end'] is None or line <= b['end']):
                return b
            if b['start'] <= line:
                best = b
        return best

    def dominates_line(self, def_id, use_line):
        """Does %def_id's definition dominate use_line?

        Module-scope ids (constants, global OpVariables, types) have no
        defining block and dominate everything.
        """
        dline, _ = self.mod.find_def(def_id)
        if dline is None:
            return True
        db = self.block_of(dline)
        # Constants, types and global OpVariables are declared before the
        # first OpLabel, so they sit in no basic block and dominate the whole
        # module. block_of() returning None means exactly that.
        if db is None or dline < self.blocks[0]['start']:
            return True
        ub = self.block_of(use_line)
        if ub is None:
            return False
        if db['label'] not in self.reachable or ub['label'] not in self.reachable:
            return False
        if db['label'] == ub['label']:
            return dline < use_line
        return db['label'] in self.dom.get(ub['label'], set())


# ------------------------------------------------- material-class refetch
def find_class_fetch(mod):
    """Everything needed to re-emit the `gbuf.y >> 5` material class anywhere.

    Anchored on the same chain find_class_shift() walks, but instead of
    returning the existing (non-dominating) value it captures the type ids,
    descriptor variables and coordinates so the fetch can be reissued at a
    splice point:

        %a = OpAccessChain <pcty> <regs> <pcidx>     ) SRV slot, read from
        %b = OpLoad %uint %a                         ) the push constants
        %c = OpIAdd %uint %b <off>                   )
        %d = OpAccessChain <ptrty> <arr> %c
        %e = OpLoad <imgty> %d
        %f = OpCompositeConstruct %v2uint <x> <y>
        %g = OpImageFetch %v4uint %e %f Lod <lod>
        %h = OpCompositeExtract %uint %g 1
        %i = OpShiftRightLogical %uint %h <shift>
    """
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpShiftRightLogical %uint (%\d+) (%\w+)\s*$', ln)
        if not m:
            continue
        shift_id, ex_id, shift_const = m.groups()
        if shift_const != '%uint_5':
            continue
        _, exd = mod.find_def(ex_id)
        me = re.match(r'OpCompositeExtract %uint (%\d+) 1\s*$', exd or '')
        if not me:
            continue
        fetch_id = me.group(1)
        fline, fed = mod.find_def(fetch_id)
        mf = re.match(r'OpImageFetch %v4uint (%\d+) (%\d+) Lod (%\w+)\s*$', fed or '')
        if not mf:
            continue
        img, coord, lod = mf.groups()
        _, imgd = mod.find_def(img)
        mi = re.match(r'OpLoad (%\w+) (%\d+)\s*$', imgd or '')
        if not mi:
            continue
        imgty, acc = mi.groups()
        _, accd = mod.find_def(acc)
        ma = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', accd or '')
        if not ma:
            continue
        ptrty, arr, slot = ma.groups()
        _, cd = mod.find_def(coord)
        mc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$', cd or '')
        if not mc:
            continue
        ctx = dict(imgty=imgty, ptrty=ptrty, arr=arr, lod=lod,
                   x=mc.group(1), y=mc.group(2), shift=shift_const,
                   line=fline, slot=slot, slot_chain=None)
        # The SRV slot is normally push-constant relative; capture the pieces
        # so it can be recomputed. If it is some other (already dominating)
        # expression, reuse the id and let dominance checking decide.
        _, sd = mod.find_def(slot)
        ms = re.match(r'OpIAdd %uint (%\d+) (%\w+)\s*$', sd or '')
        if ms:
            base, off = ms.groups()
            _, bd = mod.find_def(base)
            mb = re.match(r'OpLoad %uint (%\d+)\s*$', bd or '')
            if mb:
                _, pd = mod.find_def(mb.group(1))
                mp = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)\s*$', pd or '')
                if mp:
                    ctx['slot_chain'] = dict(pcty=mp.group(1), regs=mp.group(2),
                                             pcidx=mp.group(3), off=off)
        return ctx
    die(f"{mod.name}: material-class G-buffer fetch chain (gbuf.y>>5) not found")


def class_fetch_inputs(ctx):
    """Ids the refetch reads, i.e. what must dominate a candidate splice."""
    ids = [ctx['arr'], ctx['lod'], ctx['x'], ctx['y']]
    if ctx['slot_chain']:
        ids += [ctx['slot_chain']['regs'], ctx['slot_chain']['pcidx'],
                ctx['slot_chain']['off']]
    else:
        ids.append(ctx['slot'])
    return [i for i in ids if i.startswith('%')]


def emit_class_value(mod, ctx, ins):
    """Append the refetch to `ins`; return the material-class uint id."""
    I = mod.new_id
    if ctx['slot_chain']:
        sc = ctx['slot_chain']
        a, b, slot = I(), I(), I()
        ins += [
            f"        {a} = OpAccessChain {sc['pcty']} {sc['regs']} {sc['pcidx']}",
            f"        {b} = OpLoad %uint {a}",
            f"        {slot} = OpIAdd %uint {b} {sc['off']}",
        ]
    else:
        slot = ctx['slot']
    d, e, f, g, h, cls = I(), I(), I(), I(), I(), I()
    ins += [
        f"        {d} = OpAccessChain {ctx['ptrty']} {ctx['arr']} {slot}",
        f"        {e} = OpLoad {ctx['imgty']} {d}",
        f"        {f} = OpCompositeConstruct %v2uint {ctx['x']} {ctx['y']}",
        f"        {g} = OpImageFetch %v4uint {e} {f} Lod {ctx['lod']}",
        f"        {h} = OpCompositeExtract %uint {g} 1",
        f"        {cls} = OpShiftRightLogical %uint {h} {ctx['shift']}",
    ]
    return cls


# ------------------------------------------------------------- triples
def group_triples(mod, triples):
    """Group triples by their multiplicand tuple (one shading context each).

    Channels are positional: the three FMuls of a triple are consecutive and
    carry the albedo's r, g, b components in order. Verified on the four
    dispatched modules -- every triple's operands are three distinct OpPhi
    ids defined together.
    """
    groups = collections.OrderedDict()
    for t in triples:
        key = tuple(t['muls'])
        if len(set(t['muls'])) != 3:
            die(f"{mod.name}: triple @line {t['line']+1} has repeated "
                f"multiplicands {t['muls']}; channel order is not positional")
        t['chan'] = [0, 1, 2]
        groups.setdefault(key, []).append(t)
    return groups


def splice_line(t):
    """apply_edits inserts at pos+1, so pos = last line of the triple puts the
    new block immediately after it and before the consuming FMul."""
    return t['line'] + 2


# --------------------------------------------------------------- tiers
def build_forcetint(mod, triples, knobs):
    """Ungated tint at every triple. No class fetch, no gate, no dominance
    question beyond the triple's own values -- if this does not change the
    screen, the raygen is not executing."""
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    tint = [C(x) for x in knobs['tint']]
    for t in triples:
        ins, newids = [], []
        for k, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {tint[t['chan'][k]]}")
            newids.append(n)
        edits.append((splice_line(t), ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'forcetint')
    return consts, edits, {"triples": len(triples), "tint": list(knobs['tint'])}


def build_hairhunt(mod, cfg, ctx, triples, classes, knobs):
    """Per-class palette tint, gated on the material class refetched at each
    site. Sites whose refetch inputs do not dominate are skipped and counted
    rather than emitted as invalid SPIR-V."""
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one = C(1.0)
    palette, legend = [], []
    for n in classes:
        if n not in HUNT_PALETTE:
            die(f"class {n} has no palette entry; extend HUNT_PALETTE")
        name, rgb = HUNT_PALETTE[n]
        uid, udecl = mod.uconst(n)
        if udecl:
            consts.append(udecl)
        palette.append((n, uid, [C(x) for x in rgb]))
        legend.append({"class": n, "colour": name, "tint": list(rgb)})

    inputs = class_fetch_inputs(ctx)
    done, skipped = 0, []
    for t in triples:
        bad = [i for i in inputs if not cfg.dominates_line(i, t['line'])]
        if bad:
            skipped.append({"line": t['line'] + 1, "undominated": bad})
            continue
        ins = []
        cls = emit_class_value(mod, ctx, ins)
        gates = []
        for _, uid, rgb in palette:
            g = mod.new_id()
            ins.append(f"        {g} = OpIEqual %bool {cls} {uid}")
            gates.append((g, rgb))
        chan_val = {}
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                nid = mod.new_id()
                ins.append(f"        {nid} = OpSelect %float {g} {rgb[ch]} {cur}")
                cur = nid
            chan_val[ch] = cur
        newids = []
        for k, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {chan_val[t['chan'][k]]}")
            newids.append(n)
        edits.append((splice_line(t), ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'hairhunt')
        done += 1
    if done == 0:
        die(f"{mod.name}: no eval site could be gated (all {len(skipped)} "
            f"skipped for dominance) -- the class refetch anchor does not fit")
    return consts, edits, {"legend": legend, "sites": done,
                           "skipped": skipped, "triples": len(triples)}


# -------------------------------------------------------------- driver
def process(path, outdir, tier, knobs, target_env, do_rt=True, hunt_classes=None):
    mod = Module(path)
    if not mod.dxil:
        die(f"{mod.name}: no dxil hash in OpString")
    if do_rt:
        roundtrip_check(path, target_env)
    triples = find_triples(mod)
    if not triples:
        die(f"{mod.name}: no 1/pi diffuse triples found")
    groups = group_triples(mod, triples)
    rep = dict(module=mod.name, dxil=mod.dxil, ident=mod.ident, tier=tier,
               triples=len(triples), groups=len(groups),
               group_sizes=[len(v) for v in groups.values()])

    if tier == 'forcetint':
        consts, edits, rep['force'] = build_forcetint(mod, triples, knobs)
    elif tier == 'hairhunt':
        cfg = CFG(mod)
        ctx = find_class_fetch(mod)
        rep['class_fetch_line'] = ctx['line'] + 1
        rep['slot_reemitted'] = ctx['slot_chain'] is not None
        consts, edits, rep['hunt'] = build_hairhunt(
            mod, cfg, ctx, triples, hunt_classes or HUNT_DEFAULT, knobs)
    else:
        die(f"unknown tier {tier}")

    apply_edits(mod, consts, edits)
    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', spv_out], capture_output=True, text=True)
    rep['spirv_val'] = 'clean' if v.returncode == 0 else 'FAIL'
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        die(f"spirv-val FAILED on PATCHED {mod.name} (see {spv_out}.val.log):\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+', help='input .spvasm files')
    ap.add_argument('--tier', choices=['forcetint', 'hairhunt'], default='forcetint')
    ap.add_argument('--classes', default=None,
                    help='hairhunt: comma-separated candidate classes '
                         '(default %s); class 1 is skin, the control.'
                         % ','.join(map(str, HUNT_DEFAULT)))
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--target-env', default='spv1.4')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--set', action='append', default=[], metavar='K=V',
                    help='override a knob (tint_r/tint_g/tint_b)')
    a = ap.parse_args()

    knobs = {'tint': (6.0, 0.05, 0.05)}
    for kv in a.set:
        k, v = kv.split('=')
        if k.startswith('tint_') and k[-1] in 'rgb':
            t = list(knobs['tint'])
            t['rgb'.index(k[-1])] = float(v)
            knobs['tint'] = tuple(t)
        else:
            die(f"unknown knob {k}")
    hunt = [int(x) for x in a.classes.split(',') if x.strip()] if a.classes else None

    reports = [process(p, a.outdir, a.tier, knobs, a.target_env,
                       do_rt=not a.no_roundtrip_check, hunt_classes=hunt)
               for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
