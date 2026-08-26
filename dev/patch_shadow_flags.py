#!/usr/bin/env python3
"""
patch_shadow_flags.py -- drop RayFlags CullBackFacingTriangles from shadow
rays, so thin double-sided hair cards occlude regardless of winding.

The problem (observed): dangling hair casts correct sharp shadows onto the
face, but there is an overlit gap right at the hairline seam. Hair is clearly
in the BVH, so this is not missing geometry -- and tMin is 1e-6, so it is not
ray bias either.

The cause: shadow rays are traced with RayFlags 28 =
    TerminateOnFirstHit(4) | SkipClosestHitShader(8) | CullBackFacingTriangles(16)

Hair is card geometry: thin, single-layer, double-sided quads. Any card whose
winding faces away from the light is invisible to the shadow ray and occludes
nothing. In a thick clump enough cards face the light that the shadow still
reads; at the sparse, near-edge-on hairline seam it does not, and light pours
through exactly there.

Fix: clear bit 0x10, 28 -> 12. This is NOT an exotic configuration -- the game
itself already traces the MAJORITY of its shadow rays with flags 12 (52 call
sites vs 28 with flags 28), so the renderer is known to work that way.

Why this is visible when BRDF raygen patches were not: the estimator is
`BRDF x light x visibility / pdf`. The `/pdf` cancels the SAMPLING
distribution, which is why raygen BRDF edits never showed up (handoff/00 §2).
Visibility is a factor of the integrand and is not cancelled, so changing what
a shadow ray can hit changes the image.

Scope: this is a global change to shadow rays -- ray flags are per-trace-call
and cannot know the occluder will be hair. Back-face culling is often enabled
to suppress self-shadow acne on closed meshes, so this ships as a toggle.

Only traces that are unambiguously shadow/visibility rays are touched:
flags must contain BOTH TerminateOnFirstHit and SkipClosestHitShader (0x0C)
as well as CullBackFacingTriangles (0x10). Anything else is left alone.

Usage:
  python3 dev/patch_shadow_flags.py <dump>.spvasm --outdir swaps.shadowcull/
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

SHADOW_BITS = 0x0C          # TerminateOnFirstHit | SkipClosestHitShader
CULL_BACK = 0x10


def find_shadow_traces(mod):
    """OpTraceRayKHR calls whose flags operand is a shadow-ray constant that
    also culls back faces. Returns [(line, old_flags_token, old_value)]."""
    out = []
    for i, ln in enumerate(mod.lines):
        if 'OpTraceRayKHR' not in ln:
            continue
        toks = ln.split()
        try:
            flg = toks[toks.index('OpTraceRayKHR') + 2]
        except (ValueError, IndexError):
            continue
        val = None
        m = re.match(r'%uint_(\d+)$', flg)
        if m:
            val = int(m.group(1))
        else:
            # non-canonical id: resolve it if it is still a literal constant
            _, d = mod.find_def(flg)
            md = re.match(r'OpConstant %uint (\d+)\s*$', d or '')
            if md:
                val = int(md.group(1))
        if val is None:
            continue
        if (val & SHADOW_BITS) == SHADOW_BITS and (val & CULL_BACK):
            out.append((i, flg, val))
    return out


def process(path, outdir, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, _ = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity in OpString")
    traces = find_shadow_traces(mod)
    if not traces:
        die(f"{mod.name}: no back-face-culling shadow ray found")
    if do_rt:
        roundtrip_check(path, target_env)

    consts, changed = [], []
    newids = {}
    for line, flg, val in traces:
        nv = val & ~CULL_BACK
        if nv not in newids:
            nid, decl = mod.uconst(nv)
            if decl:
                consts.append(decl)
            newids[nv] = nid
        # replace only the flags operand (the token right after the accel id)
        toks = mod.lines[line].split()
        idx = toks.index('OpTraceRayKHR') + 2
        toks[idx] = newids[nv]
        mod.lines[line] = '               ' + ' '.join(toks)
        changed.append({"line": line + 1, "from": val, "to": nv})

    apply_edits(mod, consts, [])
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
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    return dict(module=mod.name, ident=mod.ident, traces=changed,
                spirv_val='clean',
                sha256=hashlib.sha256(open(spv_out, 'rb').read()).hexdigest(),
                out=spv_out)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    print(json.dumps([process(p, a.outdir, do_rt=not a.no_roundtrip_check)
                      for p in a.modules], indent=1))


if __name__ == '__main__':
    main()
