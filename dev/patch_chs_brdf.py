#!/usr/bin/env python3
"""
patch_chs_brdf.py -- the closest-hit-shader anchor family (live PT surface).

Why this exists (handoff/06-PT-IS-THE-CHS.md): a clean vanilla PT session with
mods disabled dispatched hash-only whole-library raygen pipelines
(fd1d0f0c84607e41, c6bce844e971491a). Both were disassembled: ~10-18KB, ZERO
1/pi, ZERO Disney anchors -- they are thin ray tracers that carry no material
shading at all. Live path tracing does NOT shade in the raygen. The shading is
in the CLOSEST-HIT shader reached through the pipeline's SBT, which the layer's
trace_rays hook can never show because it only records raygens.

Every patcher before this one (patch_skin_brdf.py, patch_shadow_brdf.py)
targets raygens, so PT frames rendered vanilla no matter what we installed.

The anchor -- Disney diffuse, one site in 55f6172c71799e4d.chs_main:

    %a = OpFMul %float <roughness> 0.107508637
    %b = OpFSub %float 0.318309873 %a        <- Disney base, 1/pi - k*rough
    %c = OpFMul %float %b <FD90 term for L>
    %d = OpFMul %float %c <FD90 term for V>  <- shared diffuse scalar
    %r = OpFMul %float %d <albedo.r>         )
    %g = OpFMul %float %d <albedo.g>         ) the diffuse triple
    %bl= OpFMul %float %d <albedo.b>         )

Detection walks from the Disney base forward through single-use FMul hops
until it reaches a value consumed by exactly three CONSECUTIVE FMuls; those
are the r,g,b diffuse. Channels are positional. Nothing is hardcoded: the ids
differ per module and the number of hops is discovered, not assumed.

NOTE ON GATING: a hit shader reads material data directly and has no
screen-space G-buffer, so `gbuf>>5` -- the class gate every previous tier
relied on -- does not exist here (verified absent). Class-based hair gating
needs a different signal in this shader; forcetint is deliberately ungated and
is the correct first step regardless.

Usage:
  python3 dev/patch_chs_brdf.py <dump>.spvasm --tier forcetint --outdir swaps/
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as _psb
from patch_skin_brdf import (Module, replace_single_use, apply_edits,
                             roundtrip_check, die)

DISNEY_K = "0.107508637"


def load_lenient(path):
    """Build a Module without requiring a BRDF.

    Module.__init__ dies if the module has no GLSL.std.450 import or no 1/pi
    constant. That is right for the BRDF tiers, but the payload tiers only need
    the id space and the OpString identity, and they must work on the shading-
    free hit shaders (shadow / alpha-test hit groups) too -- those are exactly
    the ones we cannot afford to skip when asking "does ANY hit shader run".
    Both checks happen last in __init__, so suppressing die() leaves a fully
    usable object with glsl/pi_id set to None.
    """
    saved, problems = _psb.die, []
    _psb.die = lambda msg: problems.append(msg)
    try:
        mod = Module(path)
    finally:
        _psb.die = saved
    return mod, problems


def find_const(mod, text):
    pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %float ' + re.escape(text) + r'\b')
    for ln in mod.lines:
        m = pat.match(ln)
        if m:
            return m.group(1)
    return None


def uses_of(mod, vid):
    """Line indices that reference %vid without being its definition."""
    tok = re.compile(r'(?<![%\w])' + re.escape(vid) + r'(?![\w])')
    isdef = re.compile(r'^\s*' + re.escape(vid) + r'\s*=')
    return [j for j, ln in enumerate(mod.lines)
            if tok.search(ln) and not isdef.match(ln)]


def find_disney_bases(mod):
    """Every `OpFSub %float <1/pi> (rough * 0.107508637)` -- the Disney base."""
    k = find_const(mod, DISNEY_K)
    if not k:
        die(f"{mod.name}: Disney constant {DISNEY_K} not found -- "
            f"this module carries no Disney diffuse")
    out = []
    pat = re.compile(r'\s*(%\d+)\s*=\s*OpFSub %float ' + re.escape(mod.pi_id)
                     + r' (%\d+)\s*$')
    kmul = re.compile(r'OpFMul %float %\d+ ' + re.escape(k) + r'\s*$')
    for i, ln in enumerate(mod.lines):
        m = pat.match(ln)
        if not m:
            continue
        _, d = mod.find_def(m.group(2))
        if d and kmul.match(d):
            out.append(dict(line=i, base=m.group(1)))
    return out


def walk_to_triple(mod, base, max_hops=8):
    """From the Disney base, follow single-use FMul hops to the value that is
    consumed by three consecutive FMuls -- the per-channel diffuse."""
    cur, hops = base, 0
    while hops < max_hops:
        u = uses_of(mod, cur)
        fm = [j for j in u if '= OpFMul' in mod.lines[j]]
        if len(fm) == 3 and fm[1] == fm[0] + 1 and fm[2] == fm[1] + 1:
            ids = []
            for j in fm:
                mm = re.match(r'\s*(%\d+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$',
                              mod.lines[j])
                if not mm:
                    return None
                ids.append(mm.group(1))
            return dict(line=fm[2], ids=ids, scalar=cur, hops=hops)
        if len(fm) != 1 or len(u) != 1:
            return None
        mm = re.match(r'\s*(%\d+)\s*=', mod.lines[fm[0]])
        if not mm:
            return None
        cur = mm.group(1)
        hops += 1
    return None


def find_diffuse_triples(mod):
    triples, skipped = [], []
    for b in find_disney_bases(mod):
        t = walk_to_triple(mod, b['base'])
        if t:
            t['base_line'] = b['line'] + 1
            triples.append(t)
        else:
            skipped.append(b['line'] + 1)
    if not triples:
        die(f"{mod.name}: found {len(skipped)} Disney base(s) but none reached "
            f"a diffuse triple (lines {skipped})")
    return triples, skipped


def find_payload_store(mod):
    """The `OpStore <payload.radiance> <v3>` that is this shader's real output.

    Anchor: an OpStore whose pointer is an access chain into the
    IncomingRayPayloadKHR variable at member 0 with v3float pointer type.
    Everything the shader computes reaches the raygen through this one store,
    so patching here is immune to which lighting branch was taken.
    """
    ptr_pat = re.compile(
        r'\s*(%\d+)\s*=\s*Op(?:InBounds)?AccessChain '
        r'(%_ptr_IncomingRayPayloadKHR_v3float|%\w+) %payload (%\w+)\s*$')
    ptrs = {}
    for i, ln in enumerate(mod.lines):
        m = ptr_pat.match(ln)
        if m and 'v3float' in m.group(2):
            ptrs[m.group(1)] = i
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpStore (%\d+) (%\d+)\s*$', ln)
        if m and m.group(1) in ptrs:
            return dict(line=i, ptr=m.group(1), value=m.group(2))
    die(f"{mod.name}: no v3float payload store found -- cannot locate the "
        f"shader's radiance output")


def build_payloadforce(mod, store, tint, replace):
    """Override the radiance written to the payload.

    replace=True  -> store a constant colour, so every pixel this hit shader
                     shades becomes that colour regardless of lighting. This is
                     the true "does this shader execute at all" test.
    replace=False -> scale the computed radiance per channel.
    """
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    tids = [C(x) for x in tint]
    I = mod.new_id
    ins = []
    if replace:
        nv = I()
        ins.append(f"        {nv} = OpCompositeConstruct %v3float "
                   f"{tids[0]} {tids[1]} {tids[2]}")
    else:
        outs = []
        for ch in range(3):
            e, m_ = I(), I()
            ins.append(f"        {e} = OpCompositeExtract %float {store['value']} {ch}")
            ins.append(f"        {m_} = OpFMul %float {e} {tids[ch]}")
            outs.append(m_)
        nv = I()
        ins.append(f"        {nv} = OpCompositeConstruct %v3float "
                   f"{outs[0]} {outs[1]} {outs[2]}")
    # insert immediately before the store, then repoint the store at the result
    edits.append((store['line'] - 1, ins))
    mod.lines[store['line']] = re.sub(
        r'(OpStore %\d+ )%\d+\s*$', r'\g<1>' + nv, mod.lines[store['line']])
    return consts, edits


def build_forcetint(mod, triples, tint):
    """Ungated per-channel tint on the diffuse. Each triple value has exactly
    one consumer (verified), so replace_single_use applies cleanly."""
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    tids = [C(x) for x in tint]
    for t in triples:
        ins, newids = [], []
        for ch, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {tids[ch]}")
            newids.append(n)
        # insert directly after the last line of the triple, before consumers
        edits.append((t['line'], ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'chs-forcetint')
    return consts, edits


def process(path, outdir, tier, tint, target_env, do_rt=True):
    if tier in ('payloadforce', 'payloadtint'):
        mod, problems = load_lenient(path)
    else:
        mod, problems = Module(path), []
    if not mod.ident:
        die(f"{mod.name}: no dxil identity in OpString -- the layer could not "
            f"key a swap for this module")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, tier=tier)
    if problems:
        rep['module_warnings'] = problems

    if tier in ('payloadforce', 'payloadtint'):
        # Deliberately does NOT require a Disney anchor: this tier answers
        # "does this hit shader execute at all", which must work even for hit
        # shaders that carry no recognisable BRDF.
        store = find_payload_store(mod)
        rep['payload_store_line'] = store['line'] + 1
        consts, edits = build_payloadforce(mod, store, tint,
                                           replace=(tier == 'payloadforce'))
        rep['tint'] = list(tint)
    elif tier == 'forcetint':
        triples, skipped = find_diffuse_triples(mod)
        rep.update(diffuse_sites=len(triples),
                   sites=[{"base_line": t['base_line'],
                           "triple_line": t['line'] + 1,
                           "hops": t['hops'], "ids": t['ids']} for t in triples],
                   unmatched_bases=skipped)
        consts, edits = build_forcetint(mod, triples, tint)
        rep['tint'] = list(tint)
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
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+', help='input .spvasm files')
    ap.add_argument('--tier', choices=['forcetint', 'payloadforce', 'payloadtint'],
                    default='forcetint')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--target-env', default='spv1.4')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--set', action='append', default=[], metavar='K=V')
    a = ap.parse_args()

    tint = [6.0, 0.05, 0.05]
    for kv in a.set:
        k, v = kv.split('=')
        if k.startswith('tint_') and k[-1] in 'rgb':
            tint['rgb'.index(k[-1])] = float(v)
        else:
            die(f"unknown knob {k}")

    reports = [process(p, a.outdir, a.tier, tuple(tint), a.target_env,
                       do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
