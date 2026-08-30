#!/usr/bin/env python3
"""
patch_ser.py -- idea A1 of `handoff/38-WILD-IDEAS.md`: put Shader Execution
Reordering back into the path-tracing raygens.  Build record and evidence:
`handoff/41-SER-BUILD.md`.

    --variant class      hint = the 3-bit material class, at the class fetch
    --variant byte       hint = the full 8-bit material byte (class<<5|subtype)
    --variant hit        hint = the bounce ray's hit/miss bit, after the trace
    --variant class+hit  both of the above

Usage (normally driven by dev/patch_ser.sh, which builds the whole ladder):
  python3 dev/patch_ser.py <src>.spvasm... --outdir swaps.ser.set/class \\
          --variant class
  python3 dev/patch_ser.py <src>.spvasm... --report

------------------------------------------------------------------ why at all

Cyberpunk uses the DXR `HitObject`/SER path on Windows and ships
`cvRayTracingEnableReferenceSER`.  vkd3d-proton does not translate NVAPI
shader intrinsics (issue #2420), so on Linux the CVar is inert: **0 of 3273**
modules in `~/callisto_dump` declare `SPV_*_shader_invocation_reorder`, while
this driver reports `VK_NV_ray_tracing_invocation_reorder` with
`ReorderingHint = REORDER_MODE_REORDER_EXT`.  The game asks, the translation
layer drops it, the hardware can do it.  We patch SPIR-V, so we can put it
back -- three instructions per module, +60 bytes.

`OpReorderThreadWithHintNV <hint> <bits>` is a *hint*: it repacks the
invocation among its resident peers so that peers with equal hints land in one
warp.  It has no observable effect on any value the shader computes, so this
patch **cannot change a pixel**.  Its failure mode is "nothing happened", and
the only honest proof it works is a frame-time delta on a launch.  A swap HIT
is not execution (GOTCHAS #2), and a validated splice is not an executed one
(GOTCHAS: the second `OpTraceRayKHR`).

------------------------------------------------------------------ the module

All twelve `rgs_reference_main` permutations share one shape.  Read off
`1271d3815051da17` (vanilla disasm, `dev/disasm/live/`):

    %11847  entry
              %181 = OpFOrdEqual (depth == 0)          sky / no geometry
              OpBranchConditional %181 -> %12382 (write 0, done) / %11848
    %11848  the pixel HAS geometry
              ... 220 lines of straight-line G-buffer decode ...
              %439 = OpImageFetch %v4uint <gbuf[registers[1]+5]>
              %441 = OpCompositeExtract %uint %439 1     the material byte
              %442 = OpShiftRightLogical %441 %uint_5    the 3-bit class   <-- A
              %449 = OpIEqual %442 %uint_1               the skin gate
              ... sample loop / bounce loop / light loop ...
                OpTraceRayKHR <flags 16|1040> ... %95    the SHADING ray
                %1422 = OpLoad <payload.member3>         the hit distance
                %1423 = OpFOrdEqual %1422 %float_10000   the ray MISSED   <-- B
                OpSelectionMerge %12359 / OpBranchConditional %1423
                  ... 11326 lines: shade the hit, more traces ...

**Site A (`--variant class` / `byte`) is where the divergence *predictor* is
first available**, and it is the earliest point at which it exists: `%442` is
the first instruction that can distinguish two pixels by material.  It sits
inside `%11848`, i.e. after the sky invocations have already branched away, so
the reorder never has to sort threads that are about to exit.

**Site B (`--variant hit`) is where the divergence actually is.**  Measured
across all twelve permutations: the class value is *directly* tested at only
2-3 sites and gates about 60 lines (the class-1 skin profile lookup) plus a
class-0 tail; the bounce ray's miss test gates **11434-13246 lines of a
~14200-line function**, 80-92% of the body.  Every other large selection in
the module turns out to be uniform -- `cbv99[188].y` (sample count),
`cbv99[188].z` (bounce count), `cbv99[193].y`, `cbv99[97].x` -- so it costs
nothing to sort on and nothing to sort for.

So A is cheap and indirect (same-material threads then run the same BSDF arm
and shoot correlated rays, which is second-order coherence for the traversal
and for the hit shaders behind the SBT); B is expensive and direct (it sorts
the one branch that owns most of the shader).  Which wins is not decidable
offline -- B executes once per bounce per sample with the loop's whole
live state across it, and NVIDIA's own guidance is to reorder where live state
is *small* -- so both ship, as a ladder, and frame time decides.  A null delta
on A alone does not kill A1; a null delta on B does.

------------------------------------------------------------------ the payload

`OpReorderThreadWithHintNV`'s second operand is the number of significant bits
in the hint, not a value.  Options considered, with why:

  class (3 bits)   `%442` as it stands.  8 buckets.  This is the validated
                   splice of `38` section 1.5 and the default.
  byte  (8 bits)   `%441 & 255` -- class<<5 | the 5-bit sub-enum `38` section
                   1.2 found populated with {0,12..17,21,25,30,31}.  Strictly
                   more informative *if* the subtype predicts anything the
                   raygen or its hit shaders do; the raygen itself never tests
                   it, so this rung is a real question and not an improvement.
                   Costs one `OpBitwiseAnd`.  256 buckets can also fragment
                   warps: more buckets is not automatically better.
  hit   (1 bit)    `OpSelect(missed, 0, 1)`.  The single most predictive bit in
                   the module, per the span measurement above.

Rejected: the SBT/hit-group index (not available -- `OpTraceRayKHR` is a fused
trace-and-invoke, there is no `HitObject` to key on under
`SPV_NV_shader_invocation_reorder` without restructuring the trace, and
GOTCHAS is explicit that a second trace spliced into a raygen does not
execute here); and the packed payload members, which are an RGBA8 albedo and a
12:12 octahedral normal -- continuous quantities, not identities.

------------------------------------------------------------------ composition

`swaps/` already carries patched `rgs_reference_main` modules (skinray), and
`swaps.ptq/` -- an OVERLAY, which outranks the base dir -- carries the tier-1
+ MS-GGX build of all twelve.  The layer serves the FIRST file it finds for an
id (GOTCHAS), so a SER overlay built from vanilla would silently un-patch both.
A1 is therefore built ON TOP of the served ptq set, exactly as ptq is built on
top of skinray: `dev/patch_ser.sh` defaults its source to the installed
`swaps.ptq/`, records the source's content hash in the output MANIFEST, and
refuses a vanilla source unless `--from-vanilla` is passed.

Both detectors below were verified to sweep 12/12 on the vanilla dump AND
12/12 on the ptq-patched set.  The `hit` detector deliberately keys on the ray
FLAGS and not on the cullMask, because ptq's `--bounce-mask` rewrites the mask
from 1 to 255 and a mask-based detector would find nothing on a ptq source and
say so as "no anchor" -- a false negative in the shape of a finding.

------------------------------------------------------------------ loudness

GOTCHAS #3 and the house rule: a permutation whose anchor does not match is a
hard error, not a skip.  `process()` calls `die()` on a missing or ambiguous
anchor, so a build either covers all twelve or fails on the console.
"""

import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

SKIP_CHS = 0x08                 # RayFlagsSkipClosestHitShaderKHR
SER_CAP = 'ShaderInvocationReorderNV'
SER_EXT = '"SPV_NV_shader_invocation_reorder"'
VARIANTS = ('class', 'byte', 'hit', 'class+hit')


# ------------------------------------------------------------------ helpers
def const_uint(mod, tok):
    """value of a %uint id if it is a literal constant, else None"""
    m = re.match(r'%uint_(\d+)$', tok)
    if m:
        return int(m.group(1))
    _, d = mod.find_def(tok)
    md = re.match(r'OpConstant %uint (\d+)\s*$', d or '')
    return int(md.group(1)) if md else None


def flag_values(mod, tok, depth=0):
    """The set of constant RayFlags a trace's flags operand can take.

    Copied in spirit from dev/patch_pt_quality.py: the shading trace selects
    between two constants (1040 / 16) at runtime, so one level of
    OpSelect/OpPhi has to be followed or the site reads as unresolvable.
    """
    v = const_uint(mod, tok)
    if v is not None:
        return {v}
    if depth > 2:
        return None
    _, d = mod.find_def(tok)
    if not d:
        return None
    m = re.match(r'OpSelect %uint %\w+ (%\w+) (%\w+)\s*$', d)
    if m:
        parts = [flag_values(mod, g, depth + 1) for g in m.groups()]
        return None if any(p is None for p in parts) else set().union(*parts)
    m = re.match(r'OpPhi %uint (.*)$', d)
    if m:
        toks = re.findall(r'%\w+', m.group(1))[0::2]
        parts = [flag_values(mod, t, depth + 1) for t in toks]
        return None if any(p is None for p in parts) else set().union(*parts)
    return None


class UConst:
    """Memoised mod.uconst().

    GOTCHAS: `mod.uconst()` has no pending-declaration cache -- it only scans
    mod.lines, which does not yet hold the constants this pass is about to
    append, so asking twice for the same value emits two declarations of the
    same id and `spirv-val` fails with "Id N is defined more than once".  The
    `class+hit` variant asks for %uint_1 twice, which is exactly that case.
    """

    def __init__(self, mod, consts):
        self.mod, self.consts, self.seen = mod, consts, {}

    def __call__(self, n):
        if n not in self.seen:
            nid, decl = self.mod.uconst(n)
            if decl:
                self.consts.append(decl)
            self.seen[n] = nid
        return self.seen[n]


# ---------------------------------------------------------------- detection
def find_class_site(mod):
    """The G-buffer material-class fetch, matched as a whole chain:

        %C = OpShiftRightLogical %uint %B %uint_5
        %B = OpCompositeExtract %uint %F 1
        %F = OpImageFetch %v4uint %I %coord Lod %uint_0
        %I = OpLoad <img> %A
        %A = OpAccessChain <ptr> <heap> %X
        %X = OpIAdd %uint %P %uint_5
        %P = OpLoad %uint (OpAccessChain %_ptr_PushConstant_uint %registers %uint_1)

    Matching only `>> 5` would be a constant-shaped guard of exactly the kind
    GOTCHAS #10 warns about; the chain pins the *place*, and the push-constant
    base pins it as the G-buffer table rather than some other uint4 fetch.
    GOTCHAS #13 does not bite here: the slot is addressed relative to a
    push-constant base, so nothing about a bindless heap index is baked in.

    Returns a list of dicts -- the caller requires exactly one.
    """
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpShiftRightLogical %uint (%\w+) %uint_5\s*$', ln)
        if not m:
            continue
        cls, byte = m.groups()

        _, d = mod.find_def(byte)
        me = re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', d or '')
        if not me:
            continue
        _, d = mod.find_def(me.group(1))
        mf = re.match(r'OpImageFetch %v4uint (%\w+) (%\w+) Lod %uint_0\s*$', d or '')
        if not mf:
            continue
        _, d = mod.find_def(mf.group(1))
        if not (d or '').startswith('OpLoad '):
            continue
        _, d = mod.find_def(re.findall(r'%\w+', d)[-1])
        if not (d or '').startswith('OpAccessChain '):
            continue
        _, d = mod.find_def(re.findall(r'%\w+', d)[-1])
        mi = re.match(r'OpIAdd %uint (%\w+) %uint_5\s*$', d or '')
        if not mi:
            continue
        _, d = mod.find_def(mi.group(1))
        if not (d or '').startswith('OpLoad %uint '):
            continue
        _, d = mod.find_def(re.findall(r'%\w+', d)[-1])
        if not re.match(r'OpAccessChain %_ptr_PushConstant_uint %\w+ %uint_1\s*$',
                        d or ''):
            continue
        out.append(dict(line=i, cls=cls, byte=byte))
    return out


def find_hit_site(mod):
    """The bounce ray's hit/miss test:

        OpTraceRayKHR <as> <flags> <mask> ... <tmax> <payload>
        %d = OpLoad %float (OpInBoundsAccessChain <payload> %uint_3)
        %b = OpFOrdEqual %bool %d <tmax>          <- the ray MISSED
        OpSelectionMerge <m> None                 <- and it BRANCHES on it

    Three guards, each doing separate work:

    * the flags must not contain `SkipClosestHitShader` (0x08).  Without it
      the occlusion trace (flags 12), whose identical-looking miss test feeds
      a branchless `OpSelect`, comes along too.  Keyed on flags and NOT on the
      cullMask, because ptq's `--bounce-mask` rewrites the mask 1 -> 255.
    * the compare's right operand must be the trace's OWN tMax, not the
      literal 10000: the constant is a sample, the operand is the schema.
    * the very next line must be `OpSelectionMerge`.  That is what makes the
      site a *divergence* site rather than a value; the occlusion trace's test
      fails this and is dropped even if the flag test ever stopped working.
    """
    out = []
    for i, ln in enumerate(mod.lines):
        if 'OpTraceRayKHR' not in ln:
            continue
        toks = ln.split()
        k = toks.index('OpTraceRayKHR')
        try:
            flags, tmax, payload = toks[k + 2], toks[k + 10], toks[k + 11]
        except IndexError:
            continue
        fv = flag_values(mod, flags)
        if fv is None or any(v & SKIP_CHS for v in fv):
            continue
        for j in range(i + 1, min(i + 12, len(mod.lines))):
            m = re.match(r'\s*(%\w+) = OpFOrdEqual %bool (%\w+) '
                         + re.escape(tmax) + r'\s*$', mod.lines[j])
            if not m:
                continue
            miss, dist = m.groups()
            _, d = mod.find_def(dist)
            if not (d or '').startswith('OpLoad %float '):
                break
            _, d = mod.find_def(re.findall(r'%\w+', d)[-1])
            if 'AccessChain' not in (d or '') or payload not in (d or ''):
                break
            if j + 1 >= len(mod.lines) or \
               not mod.lines[j + 1].strip().startswith('OpSelectionMerge'):
                break
            out.append(dict(line=j, miss=miss, trace=i,
                            flags=sorted(fv), tmax=tmax))
            break
    return out


# ------------------------------------------------------------------ splicing
def check_insert_after(mod, line, what):
    """A new instruction may follow `line` iff `line` is not a block
    terminator and the following line is not a label.  Splicing after a
    terminator, or ahead of a phi run, is invalid SPIR-V rather than a runtime
    bug (GOTCHAS: splice ordering).  Nothing here can land inside a phi run:
    every anchor is a non-phi instruction, and phis are all at block top.
    """
    txt = mod.lines[line].strip()
    for term in ('OpBranch', 'OpReturn', 'OpSwitch', 'OpKill', 'OpUnreachable',
                 'OpTerminate', 'OpIgnoreIntersection'):
        if txt.startswith(term) or ' = ' + term in txt:
            die(f"{mod.name}: {what} anchor at line {line + 1} is a terminator")
    nxt = mod.lines[line + 1].strip() if line + 1 < len(mod.lines) else ''
    if ' OpLabel' in nxt:
        die(f"{mod.name}: {what} anchor at line {line + 1} ends its block")


def insert_header(mod):
    """`OpCapability ShaderInvocationReorderNV` + the OpExtension, in the only
    place the SPIR-V layout rules allow: capabilities first, then extensions,
    both before OpExtInstImport / OpMemoryModel / OpEntryPoint.

    Run AFTER apply_edits, never before: apply_edits addresses mod.lines by
    absolute index, and prepending here would slide every recorded splice
    position by two.
    """
    caps = [i for i, l in enumerate(mod.lines)
            if re.match(r'\s*OpCapability ', l)]
    if not caps:
        die(f"{mod.name}: no OpCapability section")
    pad = re.match(r'(\s*)OpCapability', mod.lines[caps[0]]).group(1)
    exts = [i for i, l in enumerate(mod.lines) if re.match(r'\s*OpExtension ', l)]
    if any(SER_CAP in mod.lines[i] for i in caps):
        die(f"{mod.name}: already declares {SER_CAP} -- source is already SER-patched")
    # extensions first so the capability insert above does not move their index
    if exts:
        mod.lines.insert(exts[-1] + 1, pad + 'OpExtension ' + SER_EXT)
    else:
        mod.lines.insert(caps[-1] + 1, pad + 'OpExtension ' + SER_EXT)
    mod.lines.insert(caps[-1] + 1, pad + 'OpCapability ' + SER_CAP)


def emit_class(mod, site, uc, bits):
    """Site A.  bits=3 reorders on `%442` as it stands; bits=8 masks the whole
    material byte first, which is class<<5 | the 5-bit sub-enum."""
    check_insert_after(mod, site['line'], 'class')
    ins = []
    if bits == 3:
        hint = site['cls']
    else:
        hint = mod.new_id()
        ins.append(f"       {hint} = OpBitwiseAnd %uint {site['byte']} {uc(255)}")
    ins.append(f"               OpReorderThreadWithHintNV {hint} {uc(bits)}")
    return site['line'], ins


def emit_hit(mod, site, uc):
    """Site B.  The hint is a uint, the anchor is a bool, so one OpSelect.
    Spliced between the compare and the OpSelectionMerge -- legal, because
    the merge instruction only has to immediately precede its branch."""
    check_insert_after(mod, site['line'], 'hit')
    hint = mod.new_id()
    return site['line'], [
        f"       {hint} = OpSelect %uint {site['miss']} {uc(0)} {uc(1)}",
        f"               OpReorderThreadWithHintNV {hint} {uc(1)}",
    ]


# -------------------------------------------------------------------- driver
def process(path, outdir, opts, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, _ = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env,
               variant=opts.variant)

    cls_sites = find_class_site(mod)
    hit_sites = find_hit_site(mod)
    rep['class_sites'] = [dict(line=s['line'] + 1, cls=s['cls'], byte=s['byte'])
                          for s in cls_sites]
    rep['hit_sites'] = [dict(line=s['line'] + 1, miss=s['miss'],
                             trace=s['trace'] + 1, flags=s['flags'])
                        for s in hit_sites]
    if opts.report:
        rep['written'] = False
        return rep

    want_class = opts.variant in ('class', 'byte', 'class+hit')
    want_hit = opts.variant in ('hit', 'class+hit')

    # GOTCHAS #3 / the house rule: a permutation the anchor misses is a hard
    # error.  Twelve siblings that must all be covered is exactly the shape
    # that has silently patched 1-of-N three times in this repo.
    if want_class and len(cls_sites) != 1:
        die(f"{mod.name}: expected exactly 1 material-class fetch, "
            f"found {len(cls_sites)}")
    if want_hit and len(hit_sites) != 1:
        die(f"{mod.name}: expected exactly 1 shading-ray miss branch, "
            f"found {len(hit_sites)}")

    consts, edits = [], []
    uc = UConst(mod, consts)
    if want_class:
        edits.append(emit_class(mod, cls_sites[0], uc,
                                8 if opts.variant == 'byte' else 3))
    if want_hit:
        edits.append(emit_hit(mod, hit_sites[0], uc))
    rep['reorders'] = len(edits)

    if do_rt:
        roundtrip_check(path, target_env)
    apply_edits(mod, consts, edits)
    insert_header(mod)

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")

    # Validate at BOTH the module's own env and the one the driver reports
    # (1.4.341).  A capability that is legal at vulkan1.3 and rejected at
    # vulkan1.4 -- or the reverse -- would only show up on the launch.
    for env in ('vulkan1.3', 'vulkan1.4'):
        v = subprocess.run(['spirv-val', '--target-env', env, spv_out],
                           capture_output=True, text=True)
        if v.returncode != 0:
            open(spv_out + '.val.log', 'w').write(v.stderr)
            os.unlink(spv_out)          # GOTCHAS: never leave a stale .spv
            die(f"spirv-val FAILED ({env}) on PATCHED {mod.name}:\n"
                + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean vulkan1.3 + vulkan1.4'

    # Read the emitted instruction BACK and diff it against the source
    # (handoff/35 section 6: an exit code is not a verification).
    rep['readback'] = readback_diff(path, spv_out, target_env, opts.variant)
    rep['bytes_added'] = (os.path.getsize(spv_out)
                          - source_spv_size(path, target_env))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()[:16]
    rep['out'] = spv_out
    rep['written'] = True
    return rep


def source_spv_size(src_asm, target_env):
    tmp = src_asm + '.size.spv'
    subprocess.run(['spirv-as', '--target-env', target_env, src_asm, '-o', tmp],
                   capture_output=True, text=True, check=True)
    n = os.path.getsize(tmp)
    os.unlink(tmp)
    return n


def readback_diff(src_asm, out_spv, target_env, variant):
    """Disassemble what was actually EMITTED and diff it against the source.

    `handoff/35` section 6: reading the emitted SPIR-V back by hand is repo
    practice, not optional -- `30` section 5 records a pass-ordering bug that
    made a whole feature emit nothing while the build reported success, and it
    was only visible here.  This is that check, automated so every module in
    every set gets it rather than the one someone happens to open.

    Both sides are round-tripped through the same assemble/disassemble pair so
    formatting cancels, and numeric ids are normalised to `%#` so that
    `spirv-as`'s renumbering of everything below an insertion does not read as
    a thousand changed lines.  A SER splice is purely ADDITIVE by
    construction, so the assertion is strong: zero removed lines, and exactly
    the expected instructions added.
    """
    import difflib

    def norm(lines):
        return [re.sub(r'%\d+\b', '%#', l.strip())
                for l in lines if l.strip() and not l.lstrip().startswith(';')]

    def dis(spv):
        r = subprocess.run(['spirv-dis', '--no-color', spv],
                           capture_output=True, text=True)
        if r.returncode != 0:
            die(f"spirv-dis failed reading back {spv}:\n{r.stderr}")
        return r.stdout.splitlines()

    stmp = src_asm + '.norm.spv'
    subprocess.run(['spirv-as', '--target-env', target_env, src_asm, '-o', stmp],
                   capture_output=True, text=True, check=True)
    a, b = norm(dis(stmp)), norm(dis(out_spv))
    os.unlink(stmp)

    added, removed = [], []
    for d in difflib.unified_diff(a, b, n=0, lineterm=''):
        if d.startswith('+') and not d.startswith('+++'):
            added.append(d[1:])
        elif d.startswith('-') and not d.startswith('---'):
            removed.append(d[1:])
    if removed:
        die(f"readback: the splice REMOVED lines from {out_spv} -- it is "
            f"supposed to be purely additive:\n  " + '\n  '.join(removed[:10]))
    if not any('ShaderInvocationReorderNV' in x for x in added):
        die(f"readback: no OpCapability ShaderInvocationReorderNV in {out_spv}")
    n_reorder = sum(1 for x in added if 'OpReorderThreadWithHintNV' in x)
    want = 2 if variant == 'class+hit' else 1
    if n_reorder != want:
        die(f"readback: {n_reorder} OpReorderThreadWithHintNV in {out_spv}, "
            f"expected {want} for variant {variant} -- a build that reports "
            f"success and emits nothing is the failure mode this check exists "
            f"for (handoff/30 section 5)")
    return added


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--variant', choices=VARIANTS, default='class',
                    help='which coherence key to reorder on (default: class)')
    ap.add_argument('--report', action='store_true',
                    help='detect and print, write nothing')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    out = [process(p, a.outdir, a, do_rt=not a.no_roundtrip_check)
           for p in a.modules]
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
