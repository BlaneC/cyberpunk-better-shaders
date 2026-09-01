#!/usr/bin/env python3
"""Raise the reference path tracer's BOUNCE-LOOP BOUND, in all 12 permutations.

handoff/89. The ask: "I'd like the path traced lighting to bounce at least 3
times."

WHAT THE ENGINE ACTUALLY DOES -- AND THE LOOP THIS DOES *NOT* TOUCH.
`rgs_reference_main` carries TWO nested counted loops, both of whose bodies
contain the sun NEE trace, and they are easy to confuse:

    OUTER  bound = <cbv>[188].y   accumulators seeded to 0, firefly-clamped
                                  (NMin 1024) and summed in the latch
                                  -> the SAMPLE loop (rays per pixel)
    INNER  bound = <cbv>[188].z   exactly 3 fp phis seeded to 1.0 -- the RGB
                                  THROUGHPUT, multiplied down each iteration
                                  -> the PATH loop.  THIS one is the bounces.

The throughput-seeded-to-one triple is the discriminator, and it separates the
two cleanly in all 12 permutations: 3 unit-seeded fp phis on the path header,
zero on the sample header. Swept across the standing base:

    runtime  `OpCompositeExtract %uint <bitcast cbv> 2`   8 permutations
    LITERAL  `%uint_2`                                    4 permutations
             (4103c886, 996a3b16, d002cc05, d622fb9e)

Consistent with 29 sec B3's 8-runtime/4-baked split, on the same four modules,
and the folded literal is 2 -- matching BounceNumber's shipped default of 2,
which is the independent confirmation that this is the right loop. In those
same 4 modules the SAMPLE loop is gone entirely: bound 1 folded it flat.

CORRECTION TO AN EARLIER READING. A first pass here keyed the search on
`E.find_bounce_counter`, whose documented tie-break is "outermost wins" -- so
it returns the SAMPLE counter, not the bounce counter, and reported a bogus
5x component-1 / 3x component-2 split. That helper is used by handoff 88's
cavity gate and 79's ear glow, both of which therefore gate on `sample == 0`
and not on `bounce == 0`. Not fixed here (this patch does not touch either),
but it is the first thing to check about those two terms -- and it is a
candidate explanation for 88 sec 5c's area-light over-darkening, since a term
meant for the primary hit that instead runs at EVERY bounce compounds.
29 sec B3's `.z` was right all along; the 5x/3x split was the artefact.

WHY THE CVAR IS NOT ENOUGH. `BounceNumber` / `BounceNumberScreenshot` are
already in the CET panel (pt_engine.lua) and DO have a live wire -- into
two-thirds of the permutations. The other third constant-folded the bound to 2
at compile time and cannot be moved by any CVar. Since the dispatched
permutation changes per launch (88 sec 1), the CVar alone gives a bounce depth
that is a coin flip per run. That is exactly the failure mode 88 was written
about, so this patches the bound instead:

    bound' = UMax(bound, N)

`UMax`, not a store: a CVar set ABOVE N still wins, so this raises a floor and
never caps anything. One OpExtInst per module, one operand rewrite.

    --n 0  emits NOTHING (all detectors still run): the byte-identity control.

WHAT THIS IS NOT. It adds indirect DEPTH, not samples: a third-bounce
contribution that is dim and mostly converged already. It does not reduce
variance and it is not a fix for noise. It also costs rays -- the loop body is
the whole path segment, so N=3 is roughly +50% path work against N=2, unpaid
by any importance heuristic. Judge it in photo mode against the same frame.

UNCERTAIN, AND SAY SO. The loop is bounded by `bounce + 1 < bound`, so bound=2
runs bounce indices 0 and 1. Whether CDPR counts that as "2 bounces" or "1
bounce plus the primary hit" is not established here, so N=3 means "three
iterations of this loop", which may be either 3 or 4 bounces in the UI's
vocabulary. The A/B ladder exists so that is read off the screen, not argued.
A throughput/russian-roulette early-out inside the body could also terminate a
path before the bound -- that would make the higher rungs look identical, and
is the first thing to suspect if they do.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env


UNIT_ONE = ('%half_0x1p_0', '%float_1')


def _counted_trace_loops(mod, fs, fe):
    """Every counted loop `Op[SU]LessThan(x + 1, bound)` on a back edge whose
    body contains an OpTraceRayKHR, with the count of fp phis at its header
    that are seeded with a 1.0 constant. Structural; nothing is assumed about
    which loop is which."""
    labels = {}
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', mod.lines[i])
        if m:
            labels[m.group(1)] = i
    out = []
    for i in range(fs, fe):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)',
                     mod.lines[i])
        if not m:
            continue
        cond, t0, t1 = m.groups()
        cl, cd = mod.find_def(cond)
        cm = re.match(r'Op([SU])LessThan %bool (%\w+) (%\w+)\s*$', cd or '')
        if not cm:
            continue
        sign, a, bound = cm.groups()
        _, ad = mod.find_def(a)
        if not re.match(r'OpIAdd %uint %\w+ %uint_1\s*$', ad or ''):
            continue
        for tgt in (t0, t1):
            hi = labels.get(tgt)
            if hi is None or hi >= i:            # not a back edge
                continue
            if not any('OpTraceRayKHR' in mod.lines[j] for j in range(hi, i)):
                continue
            ones = 0
            for j in range(hi + 1, fe):
                if not re.match(r'\s*\S+\s*=\s*OpPhi ', mod.lines[j]):
                    break                      # end of the header's phi run
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(half|float) (.+?)\s*$',
                              mod.lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(2).split()[0::2]):
                    ones += 1
            out.append({"header": tgt, "header_line": hi, "branch_line": i,
                        "cmp_line": cl, "cond": cond, "sign": sign,
                        "inc": a, "bound": bound, "ones": ones})
    return out


def find_bounce_bound(mod, fs, fe):
    """The PATH loop's exit test, found structurally -- no counter-phi anchor.

    Asserted hop by hop; any deviation dies (GOTCHAS 10):
      * enumerate every counted loop whose body traces rays;
      * exactly ONE of them seeds 3 fp phis with 1.0 (the RGB throughput);
      * that one must be nested inside every other candidate -- the sample
        loop wraps the path loop, never the other way round;
      * every other candidate must seed ZERO phis with 1.0, so the
        discriminator is not merely the argmax of a noisy count;
      * the bound resolves either to an OpConstant %uint or to an
        OpCompositeExtract %uint -- nothing else is accepted.

    Returns dict(cmp_line, cond, sign, header, inc, bound, bound_def, kind).
    """
    loops = _counted_trace_loops(mod, fs, fe)
    if not loops:
        die(f"{mod.name}: no counted ray-tracing loop found")
    hot = [l for l in loops if l["ones"] == 3]
    cold = [l for l in loops if l["ones"] != 3]
    if len(hot) != 1:
        die(f"{mod.name}: {len(hot)} loops carry a 3-wide unit-seeded "
            f"throughput, expected exactly 1: "
            f"{[(l['header'], l['ones']) for l in loops]}")
    bb = hot[0]
    for l in cold:
        if l["ones"] != 0:
            die(f"{mod.name}: non-path loop {l['header']} seeds {l['ones']} "
                f"phis with 1.0 -- the throughput discriminator is not clean")
        if not (l["header_line"] < bb["header_line"]
                and bb["branch_line"] < l["branch_line"]):
            die(f"{mod.name}: path loop {bb['header']} is not nested inside "
                f"{l['header']} -- loop nesting is not what 89 assumes")

    _, bd = mod.find_def(bb["bound"])
    if re.match(r'OpConstant %uint \d+\s*$', bd or ''):
        kind = 'literal'
    elif re.match(r'OpCompositeExtract %uint %\w+ \d+\s*$', bd or ''):
        kind = 'runtime'
    else:
        die(f"{mod.name}: bounce bound {bb['bound']} is {bd!r}, wanted an "
            f"OpConstant %uint or an OpCompositeExtract %uint")
    bb["bound_def"] = bd
    bb["kind"] = kind
    bb["loops"] = len(loops)
    return bb


def build(mod, n):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()          # the memo is keyed on id(mod)
    _, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    bb = find_bounce_bound(mod, fs, fe)
    rep = {"n": n, "header": bb["header"], "loops": bb["loops"],
           "cmp_line": bb["cmp_line"] + 1, "sign": bb["sign"],
           "bound": bb["bound"], "bound_def": bb["bound_def"],
           "bound_kind": bb["kind"]}
    if bb["kind"] == 'literal':
        rep["bound_value"] = int(bb["bound_def"].split()[-1])

    if n == 0:
        rep["emitted"] = "nothing (n=0 identity control)"
        return [], [], rep

    un = E._uc(mod, consts, n)
    nid = mod.new_id()
    ind = '               '
    # UMax, so a CVar set higher than n still wins: this raises a floor.
    edits.append((bb["cmp_line"] - 1,
                  [f"{ind}{nid} = OpExtInst %uint {glsl} UMax "
                   f"{bb['bound']} {un}"]))
    old = mod.lines[bb["cmp_line"]]
    new = re.sub(r'Op([SU])LessThan %bool (%\w+) ' + re.escape(bb["bound"])
                 + r'\s*$', lambda m: f"Op{m.group(1)}LessThan %bool "
                                      f"{m.group(2)} {nid}", old)
    if new == old:
        die(f"{mod.name}: bound rewrite did not take at line "
            f"{bb['cmp_line']+1}")
    mod.lines[bb["cmp_line"]] = new
    rep["new_bound"] = nid
    rep["emitted"] = 1
    return consts, edits, rep


def process(path, outdir, n):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['bounce'] = build(mod, n)
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
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--n', type=int, required=True,
                    help='minimum bounce-loop iterations; 0 = identity control')
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    if not 0 <= a.n <= 8:
        ap.error('--n must be in [0,8]')
    print(json.dumps(process(a.spvasm, a.outdir, a.n)))


if __name__ == '__main__':
    main()
