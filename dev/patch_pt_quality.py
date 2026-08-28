#!/usr/bin/env python3
"""
patch_pt_quality.py -- the three Tier-1 path-tracing edits from
`handoff/23-PT-IMPROVEMENT-BRAINSTORM.md`, spliced into the path-tracing
raygens.  None of them is reachable by a CVar, which is the whole point
(`16` proved Ultra Plus only ever writes CVars).

    --bounce-mask     T1.4  bounce/reflection ray cullMask 1 -> 255
    --regularize R    T1.1  Kaplanyan-style roughness floor on indirect lobes
    --clamp C         T1.2  firefly ceiling on each indirect path segment

Usage (normally driven by dev/build_ptq.sh, which builds the whole matrix):
  python3 dev/patch_pt_quality.py <dump>.spvasm... --outdir swaps.ptq.matrix/rcb/base \\
          --bounce-mask --regularize 0.25 --clamp 16
  python3 dev/patch_pt_quality.py <dump>.spvasm... --report

------------------------------------------------------------------ the module

`rgs_reference_main` is not the thin tracer `06` found in the *live* PT
dispatch set: it carries a full nested-loop path tracer.  Read off
`d622fb9e1dcb8cd0` (the 1280x720 dispatch, confirmed live in
`~/callisto_swap.jsonl`):

    %12276  preheader
    %12277  loop header
              %740 = OpPhi %uint %uint_0 <pre> %741 <latch>     bounce index
              %712 = OpPhi %half %half_0 <pre> %714 <latch>     radiance.r  )
              %715, %717                                        radiance.gb ) L
    ...       OpTraceRayKHR ... cullMask %uint_1 ...            <- T1.4
    ...       roughness NMax 0.04 -> NMin 1.0 -> alpha = R*R    <- T1.1
    %12786  latch
              %3241 = OpFMul %half <Li> <throughput>            <- T1.2
              %714  = OpFAdd %half %3241 <L>
              %741  = OpIAdd %uint %1706 %uint_1
              OpBranchConditional (%741 < 2) -> header, else merge

**The loop is indirect-only, and that is load-bearing for T1.1/T1.2.**  The
first instruction group of the body is the trace; every roughness read and
every accumulate below it therefore describes a surface the ray *found*, not
the primary G-buffer surface.  The primary surface's own direct lighting is
resolved in the 84 GLCompute libs (`00` §3), not here.  The three roughness
sites that DO belong to the primary surface sit above the loop header and are
excluded by the in-loop test, not by a depth compare -- so neither edit needs
a bounce-index gate, and neither can touch primary specular.

------------------------------------------------------------------ the edits

T1.4 -- cullMask.  `17` §2: the bounce ray traces with cullMask=1 while the
module's own visibility ray uses 255.  Instances outside mask bit 0 are lit
but never bounce.  Widening it is the one identified lever for indirect light
*from* hair that no CVar fakes.  Only the shading trace is touched: cullMask
must be the constant 1 AND the flags must not contain SkipClosestHitShader
(the occlusion traces use 12/39 and are left alone).  Diagnostic first,
feature second -- a wider mask also lets bounce rays hit proxy geometry.

T1.1 -- path regularization.  R' = max(R, floor) on the roughness of every
in-loop vertex, rewriting ALL uses so the sampling branch and the eval branch
stay consistent (an unregularized pdf against a regularized f is worse than
neither).  Kaplanyan & Dachsbacher 2013; Blender's "Filter Glossy", UE5's
`r.PathTracing.Regularization`.  Anchor is the module's own perceptual-
roughness clamp `NMax(x, 0.04) -> NMin(_, 1.0)` whose square is alpha, which
is the mode-independent half of the signature (GOTCHAS 4).

T1.2 -- indirect radiance clamp.  NMin on each path segment's contribution
before it lands in the fp16 accumulator, i.e. UE's `MaxPathIntensity` applied
per segment.  Clamping the *product* (rather than Li) also catches an fp16
overflow to inf, and sits before the module's own scale so GOTCHAS' "scale
before a clamp" is respected by construction.

The knob is in OUTPUT units.  The accumulator runs in a x64 radiance scale
(the module's own output stage is `L * 0.015625` -- fp16 has no precision to
spare near zero, so radiance is carried pre-multiplied), so the emitted half
constant is `C * scale` with the scale read off that output multiply.  Two of
the twelve permutations have no such output stage; they fall back to 64.

------------------------------------------------------------------ siblings

GOTCHAS 3: all twelve `rgs_reference_main` permutations carry exactly one
cullMask-1 shading trace, and the live log dispatches three of them
(`d622fb9e`, `4270b745`, plus `40c6faab` in the capture).  Patch every
permutation the anchors are found in, never just the dispatched ones.  The
three reflection raygens carry the same cullMask-1 shading trace and are
handled by --bounce-mask too; they have no path loop, so --regularize and
--clamp find nothing there and say so.
"""

import argparse, json, os, re, struct, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, replace_all_uses, f32s, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
from patch_shadow_brdf import CFG

SKIP_CHS = 0x08                 # RayFlagsSkipClosestHitShaderKHR
ROUGH_FLOOR_CONST = '%float_0_0399999991'
DEFAULT_RADIANCE_SCALE = 64.0


# ------------------------------------------------------------------ helpers
def f16(x):
    """round to fp16 and return the exact value"""
    return struct.unpack('<e', struct.pack('<e', float(x)))[0]


def half_lit(x):
    """spirv-as literal for a half constant, exact (hex float, trimmed)."""
    h = float.hex(f16(x))                     # '0x1.0000000000000p+9'
    mant, _, exp = h.partition('p')
    if '.' in mant:
        mant = mant.rstrip('0').rstrip('.')
    return f"{mant}p{exp}"


def half_const(mod, value, consts):
    """find-or-create an `OpConstant %half v`; returns the id."""
    lit = half_lit(value)
    pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %half ' + re.escape(lit) + r'\s*$')
    for ln in mod.lines:
        m = pat.match(ln)
        if m:
            return m.group(1)
    for decl in consts:
        m = pat.match(decl)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(f"    {nid} = OpConstant %half {lit}")
    return nid


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

    Returns None when it cannot be resolved. The reference raygen's bounce
    trace selects between two constants (1040 / 16) at runtime, so one level
    of OpSelect/OpPhi has to be followed or the site reads as unresolvable.
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


# ---------------------------------------------------------------- detection
def find_shading_traces(mod):
    """OpTraceRayKHR whose cullMask is the constant 1 and whose flags never
    contain SkipClosestHitShader -- i.e. the ray that fetches shading, not an
    occlusion probe."""
    out = []
    for i, ln in enumerate(mod.lines):
        if 'OpTraceRayKHR' not in ln:
            continue
        toks = ln.split()
        try:
            k = toks.index('OpTraceRayKHR')
            flags, mask = toks[k + 2], toks[k + 3]
        except (ValueError, IndexError):
            continue
        if const_uint(mod, mask) != 1:
            continue
        fv = flag_values(mod, flags)
        if fv is None or any(v & SKIP_CHS for v in fv):
            continue
        out.append(dict(line=i, mask=mask, flags=sorted(fv)))
    return out


def find_path_loop(mod, cfg):
    """The path-tracing loop: a header carrying a uint bounce counter phi and
    at least three fp16 radiance accumulator phis, both closed by the latch.

    Returns dict(header, merge, cont, depth, accs) or None.  `header` is the
    OpLoopMerge block -- the one the in-loop dominance test needs -- which is
    usually also where the phis live, but dxil-spirv sometimes emits a
    single-predecessor block between them, so the phis are looked for in the
    merge block's successors as a fallback.
    """
    phi = re.compile(r'^\s*(%\w+)\s*=\s*OpPhi (%\w+) (.*)$')

    def scan(hb):
        depth, accs = None, []
        for i in range(hb['start'], (hb['end'] if hb['end'] is not None
                                     else hb['start']) + 1):
            m = phi.match(mod.lines[i])
            if not m:
                continue
            rid, ty, rest = m.groups()
            pairs = re.findall(r'(%\w+) (%\w+)', rest)
            if ty == '%uint':
                for val, _lbl in pairs:
                    _, d = mod.find_def(val)
                    if d and re.match(r'OpIAdd %uint %\w+ %uint_1\s*$', d):
                        depth = rid
            elif ty == '%half':
                zero = any(v == '%half_0x0p_0' for v, _ in pairs)
                add = any((mod.find_def(v)[1] or '').startswith('OpFAdd %half')
                          for v, _ in pairs)
                if zero and add:
                    accs.append(rid)
        return depth, accs

    best = None
    for b in cfg.blocks:
        lm = None
        for i in range(b['start'], (b['end'] if b['end'] is not None
                                    else b['start']) + 1):
            m = re.match(r'\s*OpLoopMerge (%\w+) (%\w+)', mod.lines[i])
            if m:
                lm = m.groups()
                break
        if not lm:
            continue
        merge, cont = lm
        for hb in [b] + [x for x in cfg.blocks if x['label'] in b['succ']]:
            depth, accs = scan(hb)
            if depth and len(accs) >= 3:
                cand = dict(header=b['label'], merge=merge, cont=cont,
                            depth=depth, accs=accs)
                if best is None or len(accs) > len(best['accs']):
                    best = cand
                break
    return best


def acc_closure(mod, accs):
    """Every fp16 value that is the running radiance sum: the header phis plus
    every OpPhi that re-phis one of them (dxil-spirv rebuilds the accumulator
    through several merge blocks before the latch adds to it)."""
    s = set(accs)
    changed = True
    while changed:
        changed = False
        for ln in mod.lines:
            m = re.match(r'^\s*(%\w+)\s*=\s*OpPhi %half (.*)$', ln)
            if not m or m.group(1) in s:
                continue
            vals = re.findall(r'(%\w+) (%\w+)', m.group(2))
            if any(v in s for v, _ in vals):
                s.add(m.group(1))
                changed = True
    return s


def in_loop(cfg, loop, line):
    """A block belongs to the loop body iff the header dominates it and the
    merge block does not.  Dominance by the header alone is not enough: the
    bounce counter phi dominates the whole post-loop tail as well."""
    blk = cfg.block_of(line)
    if blk is None:
        return False
    dom = cfg.dom.get(blk['label'], set())
    return loop['header'] in dom and loop['merge'] not in dom


def find_accumulates(mod, cfg, loop, closure):
    """`OpFAdd %half <contribution> <running sum>` -- one per colour channel per
    accumulate site, restricted to the loop body so the post-loop tail (which
    the accumulator phis also reach) is never touched."""
    out = []
    for i, ln in enumerate(mod.lines):
        if not in_loop(cfg, loop, i):
            continue
        m = re.match(r'^\s*(%\w+)\s*=\s*OpFAdd %half (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        rid, a, b = m.groups()
        ina, inb = a in closure, b in closure
        if ina == inb:                     # neither, or a sum of two sums
            continue
        # operand tokens sit at ['%r','=','OpFAdd','%half',a,b]
        out.append(dict(line=i, res=rid, contrib=(b if ina else a),
                        which=(5 if ina else 4)))
    return out


def find_roughness_sites(mod, cfg, loop):
    """`NMax(x, 0.04) -> NMin(_, 1.0)` whose result is squared into alpha, in
    a block that belongs to the path loop."""
    g = mod.glsl
    nmin = re.compile(r'^\s*(%\w+)\s*=\s*OpExtInst %float ' + re.escape(g)
                      + r' NMin (%\w+) %float_1\s*$')
    nmax = re.compile(r'^\s*(%\w+)\s*=\s*OpExtInst %float ' + re.escape(g)
                      + r' NMax (%\w+) ' + re.escape(ROUGH_FLOOR_CONST) + r'\s*$')
    maxres = {}
    for i, ln in enumerate(mod.lines):
        m = nmax.match(ln)
        if m:
            maxres[m.group(1)] = i
    out = []
    for i, ln in enumerate(mod.lines):
        m = nmin.match(ln)
        if not m or m.group(2) not in maxres:
            continue
        rid = m.group(1)
        sq = re.compile(r'^\s*%\w+\s*=\s*OpFMul %float ' + re.escape(rid)
                        + r' ' + re.escape(rid) + r'\s*$')
        if not any(sq.match(x) for x in mod.lines[i:]):
            continue
        if not in_loop(cfg, loop, i):           # primary-surface sites sit
            continue                            # above the header
        out.append(dict(line=i, rough=rid))
    return out


# ------------------------------------------------------------------ splicing
def safe_insert_point(mod, cfg, idtok):
    """A line index after which a new instruction may legally be inserted so
    that it dominates `idtok`'s uses: the line after its definition, pushed
    past any OpPhi run (all phis must stay at the top of their block)."""
    ln, _ = mod.find_def(idtok)
    if ln is None:
        return None
    b = cfg.block_of(ln)
    last = (b['end'] if b and b['end'] is not None else ln)
    while ln + 1 <= last and re.match(r'\s*%\w+\s*=\s*OpPhi ', mod.lines[ln + 1]):
        ln += 1
    return ln


def emit_clamp(mod, cfg, site, ceil_id):
    """NMin the segment contribution, in place, before it is accumulated.

    The clamp is spliced next to the contribution's own definition rather than
    next to the OpFAdd: the accumulate often sits in a phi run, and a non-phi
    instruction spliced into one is invalid SPIR-V.
    """
    pos = safe_insert_point(mod, cfg, site['contrib'])
    if pos is None or pos >= site['line']:
        return None
    nid = mod.new_id()
    ins = [f"       {nid} = OpExtInst %half {mod.glsl} NMin {site['contrib']} {ceil_id}"]
    toks = mod.lines[site['line']].split()
    toks[site['which']] = nid
    mod.lines[site['line']] = '       ' + ' '.join(toks)
    return pos, ins


def emit_floor(mod, site, floor_id):
    nid = mod.new_id()
    r = site['rough']
    ins = [f"       {nid} = OpExtInst %float {mod.glsl} NMax {r} {floor_id}"]
    n = replace_all_uses(mod, r, nid, site['line'])
    return ins, n


def find_output_scale(mod):
    """The x64 radiance scale, read off the module's own output stage:
    `L * s` feeding the +-65504 fp16 clamp pair. Returns 1/s."""
    for i, ln in enumerate(mod.lines):
        m = re.match(r'^\s*(%\w+)\s*=\s*OpExtInst %float \S+ NMax (%\w+) %float_n65504\s*$', ln)
        if not m:
            continue
        _, d = mod.find_def(m.group(2))
        md = re.match(r'OpFMul %float %\w+ (%\w+)\s*$', d or '')
        if not md:
            continue
        _, cd = mod.find_def(md.group(1))
        cm = re.match(r'OpConstant %float (\S+)', cd or '')
        if cm:
            try:
                s = float(cm.group(1))
            except ValueError:
                continue
            if 0.0 < s < 1.0:
                return 1.0 / s
    return None


# -------------------------------------------------------------------- driver
def process(path, outdir, opts, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, _ = load_lenient(path)
    if not mod.ident:
        die(f"{os.path.basename(path)}: no dxil identity in OpString")
    cfg = CFG(mod)
    rep = dict(module=mod.name, ident=mod.ident)

    consts, edits = [], []
    touched = 0

    # ---- T1.4 -----------------------------------------------------------
    traces = find_shading_traces(mod)
    rep['shading_traces'] = [dict(line=t['line'] + 1, flags=t['flags']) for t in traces]
    if opts.bounce_mask:
        nid, decl = mod.uconst(255)
        if decl:
            consts.append(decl)
        for t in traces:
            toks = mod.lines[t['line']].split()
            toks[toks.index('OpTraceRayKHR') + 3] = nid
            mod.lines[t['line']] = '               ' + ' '.join(toks)
        rep['bounce_mask'] = len(traces)
        touched += len(traces)

    # ---- the path loop, and everything gated on it -----------------------
    loop = find_path_loop(mod, cfg)
    rep['path_loop'] = bool(loop)
    if loop:
        scale = find_output_scale(mod)
        rep['radiance_scale'] = scale
        closure = acc_closure(mod, loop['accs'])
        accs = find_accumulates(mod, cfg, loop, closure)
        rough = find_roughness_sites(mod, cfg, loop)
        rep['accumulates'] = len(accs)
        rep['roughness_sites'] = len(rough)

        if opts.clamp is not None and accs:
            ceil = opts.clamp * (scale if scale else DEFAULT_RADIANCE_SCALE)
            rep['clamp_half'] = f16(ceil)
            cid = half_const(mod, ceil, consts)
            n = 0
            for s in accs:
                e = emit_clamp(mod, cfg, s, cid)
                if e:
                    edits.append(e)
                    n += 1
            rep['clamped'] = n
            touched += n

        if opts.regularize is not None and rough:
            fid, decl = mod.const(opts.regularize)
            if decl:
                consts.append(decl)
            n = 0
            for s in rough:
                ins, k = emit_floor(mod, s, fid)
                edits.append((s['line'], ins))
                n += k
            rep['regularize_uses_rewritten'] = n
            touched += len(rough)
    else:
        rep['accumulates'] = rep['roughness_sites'] = 0

    rep['edits'] = touched
    if opts.report or not touched:
        rep['written'] = False
        return rep

    if do_rt:
        roundtrip_check(path, target_env)
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
        os.unlink(spv_out)                  # GOTCHAS: never leave a stale .spv
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
    ap.add_argument('--bounce-mask', action='store_true',
                    help='T1.4: shading-ray cullMask 1 -> 255')
    ap.add_argument('--regularize', type=float, metavar='R',
                    help='T1.1: perceptual-roughness floor on indirect vertices')
    ap.add_argument('--clamp', type=float, metavar='C',
                    help='T1.2: per-segment indirect radiance ceiling, in the '
                         'output units of the pass (see module docstring)')
    ap.add_argument('--report', action='store_true',
                    help='detect and print, write nothing')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if not a.report and not a.outdir:
        ap.error('--outdir is required unless --report')
    if not a.report and not (a.bounce_mask or a.regularize is not None
                             or a.clamp is not None):
        ap.error('nothing to do: pass at least one of --bounce-mask / '
                 '--regularize / --clamp')
    out = [process(p, a.outdir, a, do_rt=not a.no_roundtrip_check)
           for p in a.modules]
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
