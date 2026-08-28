#!/usr/bin/env python3
"""
patch_shadow_opacity.py -- a SECOND shadow trace, min-combined with the game's
own, so one slice of the world can lose back-face culling without the rest of
the world changing at all.

READ THIS FIRST
---------------
The original premise below -- "hair is the non-opaque geometry, so give ray B
CullOpaqueKHR" -- is FALSIFIED. It shipped, launched, and the hairline seam
came back (`handoff/25-SHADOW-FLICKER.md` §9). `NoOpaqueKHR` on the PT
visibility ray *forces* geometry non-opaque, which is only necessary because
the geometry is authored OPAQUE. Opacity is not a discriminator here.

What survives is the mechanism. `--ray-b-flags`, `--ray-b-mask` and
`--ray-b-tmin` aim ray B at any slice of the world; ray A is untouched, so
whatever ray B does not see behaves bit-for-bit as vanilla. The live use is the
cull-mask bisect in `25` §9: ray B = flags 12 with its mask ANDed down, hunting
the smallest set of instance bits that has to lose back-face culling.
`dev/build_shadow_sets.sh` drives the whole variant matrix.

Why this exists
---------------
`dev/patch_shadow_flags.py` fixes the hairline light leak by clearing
CullBackFacingTriangles on every shadow ray (flags 28 -> 12). It works, and it
is the project's most solid visible win -- but it is a *global* change, and it
regressed flat props: cardboard and ground clutter flash black for a frame
during LOD transitions (`handoff/25-SHADOW-FLICKER.md`).

That document concluded there is "no occluder-material signal at trace time".
There is one. RayFlags carries `CullOpaqueKHR` (0x40) and `CullNoOpaqueKHR`
(0x80), evaluated per hit during traversal, and the game's shadow rays use
neither -- flags 28 sets no ForceOpaque/ForceNonOpaque either, so geometry
participates according to its **authored** opacity. Hair is alpha-tested card
geometry (`17` §2: the PT visibility ray sets ForceNonOpaque specifically "so
anyhit runs and hair alpha-tests"); solid props are opaque.

So instead of unculling everything, trace twice:

    ray A   flags 28  = TerminateFirst | SkipCHS | CullBackFacing   (VANILLA)
    ray B   flags 76  = TerminateFirst | SkipCHS | CullOpaque       (NEW)
    t = min(tA, tB)

  * opaque geometry -> only ray A sees it, back faces culled: bit-for-bit
    vanilla behaviour, so it cannot contribute the LOD flicker
  * non-opaque geometry (hair, foliage, alpha cards) -> ray B sees it with no
    back-face culling, so a card occludes whichever way it is wound

The combine is exact and needs no control flow: the payload is
`OpTypeStruct { float }` holding the hit distance, and a miss leaves
`FLT_MAX` -- the identity for `min`. Verified across all 13 `rgs_shadow_main`
modules in the dump: the struct has exactly one member and every access chain
on a payload variable indexes `%uint_0`, so ray B may reuse ray A's payload
variable with nothing to clobber (no new `RayPayloadKHR` global, hence no
`OpEntryPoint` interface edit -- see GOTCHAS).

`min` rather than a boolean OR because the consumer reads the distance, not a
flag: `%1268 = OpFOrdEqual %bool %1894 %float_3_40282347e_38` is the module's
own "did I hit anything" test, and other sites feed the distance onward.

What this is NOT
----------------
Not a fix for alpha-tested clutter. Trash sheets, foliage and chain-link are
non-opaque too, so ray B still sees their back faces and they keep whatever
flicker the global build gave them. If flat garbage turns out to be
alpha-tested rather than solid, this narrows the problem rather than closing
it, and the next lever is a raised tMin on ray B alone (it can carry its own,
and only alpha-tested geometry would pay for it).

Cost: one extra shadow ray per site, unconditionally. Gating ray B on "ray A
missed" would halve it in shadowed regions but needs a real CFG edit; the
straight-line form is the safe first build.

Scope
-----
Only unambiguous occlusion rays: the flags operand must be a **constant** with
TerminateOnFirstHit | SkipClosestHitShader (0x0C) AND CullBackFacingTriangles
(0x10) -- i.e. exactly the 28 sites `patch_shadow_flags.py` already owns.

Deliberately NOT widened to the flags-16 modules, even though
`25-SHADOW-FLICKER.md` §3 is wrong that they don't exist (`rgs_diffuse_main`,
`rgs_importance_main`, `281c46c2.rgs_shadow_main` all use bare 16, and
`94e675a5.rgs_shadow_main` uses `OpSelect(28, 16)`). Flags 16 lacks
SkipClosestHitShader, so those rays RUN the closest-hit shader and their
payload carries shading, not a distance -- min-combining it would be
nonsense. `94e675a5` is skipped for the same reason: one arm of its select is
a shading ray. Those are reported, not patched.

Usage:
  # the falsified default (ray B = flags 76, CullOpaque)
  python3 dev/patch_shadow_opacity.py <dump>.spvasm... --outdir swaps.shadowcull.split/
  # the plumbing control: ray B = the global unculled build, mask untouched
  python3 dev/patch_shadow_opacity.py <dump>.spvasm... --ray-b-flags 12 --outdir OUT/
  # one bisect step: ray B unculled, but only for instance-mask bits 4,5,6
  python3 dev/patch_shadow_opacity.py <dump>.spvasm... --ray-b-flags 12 \
          --ray-b-mask 112 --outdir OUT/
  python3 dev/patch_shadow_opacity.py <dump>.spvasm... --report

--ray-b-mask is applied as `OpBitwiseAnd` against ray A's OWN mask operand, not
as a replacement: all 10 rgs_shadow_main pick their mask at runtime with
`OpSelect(%c, %uint_86, %uint_38)`, and ANDing keeps ray B a strict subset of
what ray A could have seen whichever arm won.
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, replace_all_uses, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

SHADOW_BITS = 0x0C          # TerminateOnFirstHit | SkipClosestHitShader
CULL_BACK   = 0x10          # CullBackFacingTriangles
CULL_OPAQUE = 0x40          # CullOpaqueKHR -- only non-opaque geometry hits
LOAD_WINDOW = 8             # how far past the trace the payload load may sit

TERMINATORS = ('OpBranch', 'OpBranchConditional', 'OpSwitch', 'OpReturn',
               'OpReturnValue', 'OpKill', 'OpUnreachable', 'OpTerminateRayKHR',
               'OpIgnoreIntersectionKHR')


def const_uint(mod, tok):
    m = re.match(r'%uint_(\d+)$', tok)
    if m:
        return int(m.group(1))
    _, d = mod.find_def(tok)
    md = re.match(r'OpConstant %uint (\d+)\s*$', d or '')
    return int(md.group(1)) if md else None


def bool_type(mod, consts):
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypeBool\s*$', ln)
        if m:
            return m.group(1)
    for d in consts:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypeBool\s*$', d)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(f"       {nid} = OpTypeBool")
    return nid


def uint_type(mod, consts):
    """The 32-bit unsigned type id, for a runtime mask narrowing on ray B."""
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypeInt 32 0\s*$', ln)
        if m:
            return m.group(1)
    die(f"{mod.name}: no OpTypeInt 32 0")


def payload_is_single_float(mod, pay):
    """Every access chain on this payload variable indexes member 0 only.

    Cheap proof that ray B may reuse ray A's payload: there is nothing else in
    it to clobber. Returns the member-0 pointer ids, or None if any chain
    reaches a different member.
    """
    ptrs = []
    pat = re.compile(r'^\s*(%\w+)\s*=\s*Op(?:InBounds)?AccessChain '
                     r'(%\w+) ' + re.escape(pay) + r'((?: %\w+)+)\s*$')
    for ln in mod.lines:
        m = pat.match(ln)
        if not m:
            continue
        idx = m.group(3).split()
        if idx != ['%uint_0']:
            return None
        ptrs.append(m.group(1))
    return ptrs or None


def find_sites(mod):
    """Occlusion traces that cull back faces, each paired with the load of the
    hit distance they write."""
    sites, skipped = [], []
    for i, ln in enumerate(mod.lines):
        if 'OpTraceRayKHR' not in ln:
            continue
        toks = ln.split()
        try:
            k = toks.index('OpTraceRayKHR')
        except ValueError:
            continue
        operands = toks[k + 1:]
        if len(operands) < 11:
            continue
        flg, pay = operands[1], operands[10]
        val = const_uint(mod, flg)
        if val is None:
            skipped.append(dict(line=i + 1, why='flags not a constant '
                                '(one arm may run the closest-hit shader)'))
            continue
        if not ((val & SHADOW_BITS) == SHADOW_BITS and (val & CULL_BACK)):
            if val & CULL_BACK:
                skipped.append(dict(line=i + 1, flags=val,
                                    why='culls back faces but is not an '
                                        'occlusion ray (payload carries shading)'))
            continue
        ptrs = payload_is_single_float(mod, pay)
        if not ptrs:
            skipped.append(dict(line=i + 1, flags=val,
                                why='payload has members other than 0'))
            continue
        # the load of the distance ray A just wrote: same block, just below
        load = None
        for j in range(i + 1, min(i + 1 + LOAD_WINDOW, len(mod.lines))):
            s = mod.lines[j].strip()
            if s.split(' ')[0] in TERMINATORS or 'OpLabel' in s:
                break
            m = re.match(r'^(%\w+)\s*=\s*OpLoad %float (%\w+)\s*$', s)
            if m and m.group(2) in ptrs:
                load = (j, m.group(1), m.group(2))
                break
        if load is None:
            skipped.append(dict(line=i + 1, flags=val,
                                why='no payload load within the window'))
            continue
        sites.append(dict(trace=i, flags_tok=flg, flags=val, payload=pay,
                          load_line=load[0], load_res=load[1], ptr=load[2]))
    return sites, skipped


def process(path, outdir, opts, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, _ = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    sites, skipped = find_sites(mod)
    rep = dict(module=mod.name, ident=mod.ident,
               sites=[dict(line=s['trace'] + 1, flags=s['flags']) for s in sites],
               skipped=skipped)
    if opts.report or not sites:
        rep['written'] = False
        return rep
    if do_rt:
        roundtrip_check(path, target_env)

    consts, edits = [], []
    bty = bool_type(mod, consts)
    uty = uint_type(mod, consts) if opts.ray_b_mask is not None else None
    rewritten = 0
    for s in sites:
        if opts.ray_b_flags is not None:
            nv = opts.ray_b_flags
        else:
            nv = (s['flags'] & ~CULL_BACK) | CULL_OPAQUE
        fid, decl = mod.uconst(nv)
        if decl and decl not in consts:
            consts.append(decl)
        # ray B: ray A's trace verbatim, with only the operands we name changed
        toks = mod.lines[s['trace']].split()
        k = toks.index('OpTraceRayKHR')
        toks[k + 2] = fid
        pre = []
        if opts.ray_b_mask is not None:
            # AND rather than replace: ray B must stay a SUBSET of what ray A
            # could see, whatever the module's own mask turns out to be at
            # runtime (all 10 rgs_shadow_main use OpSelect(86, 38), not a
            # constant -- see 25-SHADOW-FLICKER.md).
            kid, kdecl = mod.uconst(opts.ray_b_mask)
            if kdecl and kdecl not in consts:
                consts.append(kdecl)
            mb = mod.new_id()
            pre.append(f"       {mb} = OpBitwiseAnd {uty} {toks[k + 3]} {kid}")
            toks[k + 3] = mb
        if opts.ray_b_tmin is not None:
            tid, tdecl = mod.const(opts.ray_b_tmin)
            if tdecl and tdecl not in consts:
                consts.append(tdecl)
            toks[k + 8] = tid
        trace_b = '               ' + ' '.join(toks)
        tb, cmp_id, res = mod.new_id(), mod.new_id(), mod.new_id()
        # OpFOrdLessThan + OpSelect rather than GLSL NMin: the nearer hit wins,
        # FLT_MAX (miss) loses, and it needs no extended-instruction import.
        ins = pre + [
            trace_b,
            f"       {tb} = OpLoad %float {s['ptr']}",
            f"       {cmp_id} = OpFOrdLessThan {bty} {tb} {s['load_res']}",
            f"       {res} = OpSelect %float {cmp_id} {tb} {s['load_res']}",
        ]
        edits.append((s['load_line'], ins))
        rewritten += replace_all_uses(mod, s['load_res'], res, s['load_line'])
    rep['patched'] = len(sites)
    rep['uses_rewritten'] = rewritten
    rep['ray_b'] = dict(flags=opts.ray_b_flags, mask=opts.ray_b_mask,
                        tmin=opts.ray_b_tmin)

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
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)          # never leave a stale .spv for the installer
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['written'] = True
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()[:16]
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--report', action='store_true',
                    help='detect and print, write nothing')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--ray-b-flags', type=lambda v: int(v, 0), default=None,
                    metavar='N',
                    help='ray B RayFlags (default: ray A with CullBackFacing '
                         'swapped for CullOpaque). 12 = the global unculled '
                         'fix applied to ray B alone.')
    ap.add_argument('--ray-b-mask', type=lambda v: int(v, 0), default=None,
                    metavar='K',
                    help="AND ray B's cull mask with K, so ray B sees a subset "
                         "of ray A's geometry. Use to bisect which instance "
                         "class is the hairline occluder.")
    ap.add_argument('--ray-b-tmin', type=float, default=None, metavar='T',
                    help="ray B's own tMin, in metres (default: ray A's).")
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    if a.ray_b_flags is not None and (a.ray_b_flags & SHADOW_BITS) != SHADOW_BITS:
        ap.error('--ray-b-flags must keep TerminateOnFirstHit|SkipClosestHitShader '
                 f'(0x{SHADOW_BITS:02x}); without SkipClosestHitShader ray B runs '
                 'the closest-hit shader and its payload is not a distance')
    print(json.dumps([process(p, a.outdir, a, do_rt=not a.no_roundtrip_check)
                      for p in a.modules], indent=1))


if __name__ == '__main__':
    main()
