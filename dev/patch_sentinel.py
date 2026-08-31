#!/usr/bin/env python3
"""G-U5 payload sentinel (handoff/55): does an INJECTED OpTraceRayKHR execute?

The gate for the traced-thickness transmission (51 sec 7). The graveyard it is
designed against: 26 sec 7d -- a second STATIC trace site in rgs_shadow_main
validated, was served, and did nothing. 29 sec B5 narrows it: the reference
raygen's single site executes many dynamic traces (the bounce loop ships), so
what is untested is a second static SITE in THESE pipelines.

Two tiers, two rungs, one variable between them:

  --tier miss   ("sentinel")  rgs: fresh payload var (same struct type),
                ARM stored at entry, a clone of the module's first radiance
                trace with cullMask -> 0 (guaranteed miss) and payload -> the
                fresh var; at every radiance write, paint MAGENTA where
                payload word0 == MAGIC.  ms_empty_main (same library hash,
                separately swapped -- the layer keys on <hash>.<entry>): a
                guarded ARM -> MAGIC handshake (select, no control flow).
                Fires ONLY if the injected trace runs AND the SBT's miss
                index 0 is this library's ms_empty_main AND the payload
                round-trips raygen -> miss -> raygen.

  --tier clone  ("sentinel-b") rgs only: the same clone with EVERY operand
                kept verbatim except payload -> fresh armed var. On a hit the
                pipeline's own (unpatched) CHS writes the payload; on a miss
                the unpatched ms_empty writes nothing. Paint CYAN where word0
                != ARM ("something executed and wrote my payload"). No miss
                patch, no assumption about SBT miss mapping: this isolates
                "does an injected static trace execute at all".

Interpretation is pre-registered in handoff/55 -- the build refuses to exist
without an outcome table (GOTCHAS: a structural detector proves a site's
shape, never what it means; a launch decides).

Constants (uint bit patterns, improbable by construction):
  ARM   = 0x5EA71E51   MAGIC = 0x3141C0DE
Collision risk, priced: tier miss patches ms_empty to rewrite word0 only when
it equals ARM. Live misses carry a payload word0 the raygen authored; if it
ever coincidentally equals ARM, one sample's word0 becomes MAGIC -- a
one-in-4e9 per-miss event confined to a diagnostic rung. Accepted.
"""
import argparse, hashlib, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish

ARM   = 0x5EA71E51
MAGIC = 0x3141C0DE
PAINT = {'miss': (10.0, 0.0, 10.0),    # magenta
         'clone': (0.0, 10.0, 10.0)}   # cyan

TRACE_RE = re.compile(r'^(\s*)OpTraceRayKHR\s+(.+?)\s*$')


def _entry(mod, model):
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpEntryPoint ' + model + r' (%\w+) "', ln)
        if m:
            return i, m.group(1)
    die(f"{mod.name}: no {model} entry point")


def _func_span(mod, fid):
    s = None
    for i, ln in enumerate(mod.lines):
        if re.match(r'\s*' + re.escape(fid) + r'\s*=\s*OpFunction\b', ln):
            s = i
        elif s is not None and 'OpFunctionEnd' in ln:
            return s, i
    die(f"{mod.name}: no function body for {fid}")


def _payload_ptr_and_struct(mod, storage):
    """(ptr_type_id, struct_id) for the payload struct pointer in `storage`,
    asserting member 0 is %uint (the sentinel word)."""
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypePointer ' + storage + r' (%\w+)\s*$', ln)
        if not m:
            continue
        _, d = mod.find_def(m.group(2))
        if d and d.startswith('OpTypeStruct'):
            mem = d.split()[1:]
            if not mem or mem[0] != '%uint':
                die(f"{mod.name}: payload struct member 0 is "
                    f"{mem[0] if mem else 'missing'}, expected %uint")
            return m.group(1), m.group(2)
    die(f"{mod.name}: no {storage} struct pointer type")


def _ensure_line(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def _uc(mod, consts, v):
    nid, decl = mod.uconst(v)
    if decl:
        consts.append(decl)
    return nid


def _fc(mod, consts, v):
    nid, decl = mod.const(v)
    if decl:
        consts.append(decl)
    return nid


def build_rgs(mod, tier):
    consts, edits = [], []
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)
    ptrS, _ = _payload_ptr_and_struct(mod, 'RayPayloadKHR')
    ptrU = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %uint\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %uint")
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
        lambda n: f"    {n} = OpTypeBool")
    u0 = _uc(mod, consts, 0)
    arm = mod.new_id(); consts.append(f"    {arm} = OpConstant %uint {ARM}")
    magic = mod.new_id(); consts.append(f"    {magic} = OpConstant %uint {MAGIC}")
    paints = [_fc(mod, consts, v) for v in PAINT[tier]]

    spay = mod.new_id()
    consts.append(f"    {spay} = OpVariable {ptrS} RayPayloadKHR")
    # SPIR-V >= 1.4: every referenced global must be on the entry interface
    mod.lines[eline] = mod.lines[eline].rstrip() + ' ' + spay

    rep = {"tier": tier, "arm": hex(ARM), "magic": hex(MAGIC)}

    # detectors first (GOTCHAS 12): writes + the clone site, before any edit
    writes = find_image_writes(mod)
    trace_line = None
    for i in range(fs, fe):
        if TRACE_RE.match(mod.lines[i]):
            trace_line = i
            break
    if trace_line is None:
        die(f"{mod.name}: no OpTraceRayKHR in the raygen entry function")
    ind, ops = TRACE_RE.match(mod.lines[trace_line]).groups()
    ops = ops.split()
    if len(ops) != 11:
        die(f"{mod.name}: trace at line {trace_line+1} has {len(ops)} "
            f"operands, expected 11")
    rep["clone_of_line"] = trace_line + 1
    rep["orig_operands"] = ' '.join(ops)

    # 1. arm the fresh payload in the entry block, after leading OpVariables
    lab = next(i for i in range(fs, fe) if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    at = lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    a = mod.new_id()
    edits.append((at, [
        f"{ind}{a} = OpInBoundsAccessChain {ptrU} {spay} {u0}",
        f"{ind}OpStore {a} {arm}"]))

    # 2. the injected trace, immediately after the original site
    nops = list(ops)
    nops[10] = spay
    if tier == 'miss':
        nops[2] = u0          # cullMask 0: nothing intersects, miss runs
        if ops[5] != '%uint_0':
            rep["missIndex_note"] = f"cloned missIndex is {ops[5]}, not %uint_0"
    edits.append((trace_line, [f"{ind}OpTraceRayKHR " + ' '.join(nops)]))
    rep["injected_operands"] = ' '.join(nops)

    # 3. readback + paint at every radiance write
    painted, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            die(f"{mod.name}: write at line {w['line']+1} has a non-construct "
                f"texel -- refusing (no dual-arm writes expected in reference)")
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({"line": w['line']+1, "why": "constant-zero"})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({"line": w['line']+1, "why": "scalar-broadcast"})
            continue
        wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        ac, ld, eq = mod.new_id(), mod.new_id(), mod.new_id()
        ins = [f"{wind}{ac} = OpInBoundsAccessChain {ptrU} {spay} {u0}",
               f"{wind}{ld} = OpLoad %uint {ac}"]
        if tier == 'miss':
            ins.append(f"{wind}{eq} = OpIEqual {boolt} {ld} {magic}")
        else:
            ins.append(f"{wind}{eq} = OpINotEqual {boolt} {ld} {arm}")
        newc = []
        for ch in range(3):
            s = mod.new_id()
            ins.append(f"{wind}{s} = OpSelect %float {eq} {paints[ch]} {c[ch]}")
            newc.append(s)
        nt = mod.new_id()
        ins.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        painted.append({"line": w['line']+1})
    if not painted:
        die(f"{mod.name}: no radiance write to read the sentinel back at")
    rep["painted"], rep["skipped"] = painted, skipped
    return consts, edits, rep


def build_ms(mod):
    """ms_empty_main: word0 = (word0 == ARM) ? MAGIC : word0, before every
    return. Unconditional guarded store -- no new control flow, and a live
    miss (never armed) is byte-for-byte behaviour-identical."""
    consts, edits = [], []
    _, fid = _entry(mod, 'MissKHR')
    fs, fe = _func_span(mod, fid)
    pay = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpVariable %\w+ IncomingRayPayloadKHR\s*$', ln)
        if m:
            pay = m.group(1)
            break
    if pay is None:
        die(f"{mod.name}: no IncomingRayPayloadKHR variable")
    _payload_ptr_and_struct(mod, 'IncomingRayPayloadKHR')   # asserts member0 uint
    ptrU = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer IncomingRayPayloadKHR %uint\s*$',
        lambda n: f"    {n} = OpTypePointer IncomingRayPayloadKHR %uint")
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
        lambda n: f"    {n} = OpTypeBool")
    u0 = _uc(mod, consts, 0)
    arm = mod.new_id(); consts.append(f"    {arm} = OpConstant %uint {ARM}")
    magic = mod.new_id(); consts.append(f"    {magic} = OpConstant %uint {MAGIC}")

    rets = [i for i in range(fs, fe) if mod.lines[i].strip() == 'OpReturn']
    if not rets:
        die(f"{mod.name}: no OpReturn in miss entry")
    for r in rets:
        ind = '               '
        a, l, e, s = (mod.new_id() for _ in range(4))
        edits.append((r - 1, [
            f"{ind}{a} = OpInBoundsAccessChain {ptrU} {pay} {u0}",
            f"{ind}{l} = OpLoad %uint {a}",
            f"{ind}{e} = OpIEqual {boolt} {l} {arm}",
            f"{ind}{s} = OpSelect %uint {e} {magic} {l}",
            f"{ind}OpStore {a} {s}"]))
    return consts, edits, {"kind": "ms_empty handshake", "returns_patched": len(rets),
                           "arm": hex(ARM), "magic": hex(MAGIC)}


def process(path, outdir, tier):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, tier=tier)
    if problems:
        rep['module_warnings'] = problems
    if tier == 'ms':
        consts, edits, rep['sentinel'] = build_ms(mod)
    else:
        consts, edits, rep['sentinel'] = build_rgs(mod, tier)
    apply_edits(mod, consts, edits)
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
    ap.add_argument('--tier', required=True, choices=('miss', 'clone', 'ms'))
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    rep = process(args.spvasm, args.outdir, args.tier)
    import json
    print(json.dumps(rep))


if __name__ == '__main__':
    main()
