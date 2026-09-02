#!/usr/bin/env python3
"""Converged-mode profile: the expensive rungs, gated on the accumulation state.

handoff/92. The premise, from handoff/89 sec 5b: the bounce floor (`-b3`) and
the skin sample bump (handoff/77) both LOST on screen at 1 spp, because both
are noise SOURCES at a fixed sample budget. They only pay where the variance is
paid for separately -- photo mode with `RayNumber` raised, or reference
accumulation with a pinned camera. So: build ONE rung that spends the extra
work ONLY THERE and is behaviourally the standing rung everywhere else.

WHAT THE GATE READS, AND WHY IT IS NOT AN ACCUMULATION FLAG.
There is no accumulation flag in these bytes. Censused, not assumed: across all
12 `rgs_reference_main` permutations of the standing base, cbv[188] is read as
  .x  NEVER (0 uses in 12/12)
  .y  RayNumber        8x in the 6 live-loop permutations, 4x in the 2 SER ones
  .z  BounceNumber     4x
  .w  a float (an exposure/bias term, NMax/NMin to [-1,1] then Log2)
and the module carries no debug names, so the remaining uint-valued cbv words
that are compared against 0 (78.x/.w, 81.w, 84.y, 90.x, 97.x, 101.x, 193.x/.y/.w,
194.z, 198.x) are unnamed and none of them reads as accumulation -- 193.x/.w
force a roughness to 1 (a debug override), 194.z is a loop bound, 198.x ORs into
a russian-roulette probability. `EnableReferenceAccumulation` / `SampleNumber` /
`SkipSamples` (handoff/32 sec 2) have no identifiable landing site here.

So the gate is handoff/92's stated fallback, and it is stated plainly:

    accum := ( bitcast(cbv[188]).y > 1 )        i.e. RayNumber raised above 1

That is a proxy for "the frame is being paid for with samples", not a proxy for
"the accumulator is running". It is true in exactly the configuration 89 sec 5b
names as the one where these rungs pay, and false in 1 spp gameplay, which is
the configuration where they were falsified.

THE TWO GATED COSTS.

1. Bounce floor (handoff/89's `-b3`), gated:

       bound' = UMax(bound, OpSelect(accum, N, 0))

   `UMax` with a floor of 0 is the identity on any uint, so when `accum` is
   false the path loop's bound is bit-for-bit the engine's own -- literal or
   CVar extract, whichever the permutation carried. When `accum` is true the
   floor is N (default 3). Still a floor and never a cap: BounceNumber set
   above N still wins.

2. Skin sample floor (handoff/77's `-spp4`), gated. handoff/77's own edit is
   reused unchanged; the ONLY difference is what feeds its skin predicate:

       77:    gate = isSkin
       here:  gate = isSkin && accum

   which is implemented by wrapping `patch_skin_spp.clone_class_fetch` -- the
   one function both of 77's tiers get their `isSkin` from -- so the dyn tier's
   `eff = (gate && rayN != 0) ? UMax(rayN, S) : rayN` and the baked tier's
   `N = OpSelect(gate, S, 1)` / `invN = OpSelect(gate, 1/S, 1)` are 77's code
   verbatim with a narrower gate. Off the gate: eff == rayN by construction in
   the dyn tier; N == 1 and invN == 1.0 (exact in half) in the baked tier, so
   one iteration and `acc = 0 + x`, `avg = acc * 1.0`.

BEHAVIOURAL IDENTITY vs BYTE IDENTITY -- say which one is claimed.
A gate-FALSE frame is BEHAVIOURALLY identical to the standing rung; it is not
byte-identical, because the gate's own instructions are in the binary. The
byte-identity control is the BUILD-time one: `--off` runs every detector and
emits nothing, and `dev/build_conv.sh` asserts that rebuild is 12/12
byte-identical to the base rung.

ORDER. The bounce edit runs FIRST, on clean loop structure, because 77's baked
tier rewires the outermost loop; both passes re-scan, so the line indices never
cross. `--n 0` skips the bounce half, `--spp 0` skips the skin half, `--off`
skips both.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
import patch_skin_spp as SPP
import patch_bounce as B
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

IDT = SPP.IDT
CBV_WORD = 188          # the sampling cbuffer word
RAYN_COMP = 1           # .y == RayNumber (handoff/77 sec 1)


# ------------------------------------------------------------ the gate

def find_cbv_base(mod):
    """The descriptor id every cbv[188] access chain is rooted at. Asserted
    unique -- if a permutation ever loads that word through two different
    bindless handles, this build must stop rather than guess."""
    bases, first = set(), None
    for i, ln in enumerate(mod.lines):
        m = re.search(r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 '
                      r'%uint_' + str(CBV_WORD) + r'\s*$', ln)
        if m:
            bases.add(m.group(1))
            if first is None:
                first = i
    if len(bases) != 1:
        die(f"{mod.name}: {len(bases)} distinct cbv[{CBV_WORD}] bases {bases}, "
            f"expected exactly 1")
    base = bases.pop()
    dline, _ = mod.find_def(base)
    if dline is None:
        die(f"{mod.name}: cbv base {base} has no definition")
    return base, dline


def emit_accum(mod, consts, base, boolt, ids):
    """lines computing `accum = bitcast(cbv[188]).y > 1`, plus the id."""
    u0 = SPP._uc(mod, consts, 0)          # noqa: F841 (kept for symmetry)
    u1 = SPP._uc(mod, consts, 1)
    a, ld, bc, ext, acc = (mod.new_id() for _ in range(5))
    ids.update(access=a, extract=ext, accum=acc)
    return [
        f"{IDT}{a} = OpAccessChain %_ptr_Uniform_v4float {base} %uint_0 "
        f"%uint_{CBV_WORD}",
        f"{IDT}{ld} = OpLoad %v4float {a}",
        f"{IDT}{bc} = OpBitcast %v4uint {ld}",
        f"{IDT}{ext} = OpCompositeExtract %uint {bc} {RAYN_COMP}",
        f"{IDT}{acc} = OpUGreaterThan {boolt} {ext} {u1}",
    ], acc


# ------------------------------------------------------- 1. bounce floor

def patch_bounce_gated(mod, n, base, base_dline):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()            # the memo is keyed on id(mod)
    _, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    bb = B.find_bounce_bound(mod, fs, fe)
    rep = {"n": n, "header": bb["header"], "loops": bb["loops"],
           "cmp_line": bb["cmp_line"] + 1, "sign": bb["sign"],
           "bound": bb["bound"], "bound_def": bb["bound_def"],
           "bound_kind": bb["kind"]}
    if bb["kind"] == 'literal':
        rep["bound_value"] = int(bb["bound_def"].split()[-1])
    if n == 0:
        rep["emitted"] = "nothing (--n 0)"
        return [], [], rep
    if base_dline >= bb["cmp_line"]:
        die(f"{mod.name}: cbv base {base} is defined at line "
            f"{base_dline + 1}, at or after the path-loop compare at "
            f"{bb['cmp_line'] + 1} -- the gate would not dominate")

    boolt = SPP._ensure(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                        lambda x: f"    {x} = OpTypeBool")
    ids = {}
    lines, acc = emit_accum(mod, consts, base, boolt, ids)
    un = SPP._uc(mod, consts, n)
    u0 = SPP._uc(mod, consts, 0)
    sel, nid = mod.new_id(), mod.new_id()
    # OpSelect(accum, n, 0): UMax(bound, 0) is the identity on any uint, so a
    # gate-false frame runs the engine's own bound with no arithmetic effect.
    lines += [
        f"{IDT}{sel} = OpSelect %uint {acc} {un} {u0}",
        f"{IDT}{nid} = OpExtInst %uint {glsl} UMax {bb['bound']} {sel}",
    ]
    edits.append((bb["cmp_line"] - 1, lines))
    old = mod.lines[bb["cmp_line"]]
    new = re.sub(r'Op([SU])LessThan %bool (%\w+) ' + re.escape(bb["bound"])
                 + r'\s*$',
                 lambda m: f"Op{m.group(1)}LessThan %bool {m.group(2)} {nid}",
                 old)
    if new == old:
        die(f"{mod.name}: bound rewrite did not take at line "
            f"{bb['cmp_line'] + 1}")
    mod.lines[bb["cmp_line"]] = new
    rep.update(new_bound=nid, floor_select=sel, emitted=1, **ids)
    return consts, edits, rep


# --------------------------------------------- 2. skin spp, gate narrowed

def _wrap_class_fetch(base, base_dline, seen):
    """Wrap SPP.clone_class_fetch so the `isSkin` it hands back to EITHER of
    handoff/77's tiers is `isSkin && accum`. 77's code is otherwise untouched:
    this is the single point both tiers take their predicate from."""
    orig = SPP.clone_class_fetch

    def wrapped(mod, consts, ins_line):
        out, skin, boolt, rep = orig(mod, consts, ins_line)
        if base_dline >= ins_line:
            die(f"{mod.name}: cbv base {base} defined at line "
                f"{base_dline + 1}, at or after the skin-gate insertion point "
                f"{ins_line + 1} -- the gate would not dominate")
        ids = {}
        lines, acc = emit_accum(mod, consts, base, boolt, ids)
        gated = mod.new_id()
        lines.append(f"{IDT}{gated} = OpLogicalAnd {boolt} {skin} {acc}")
        rep.update(is_skin=skin, gated=gated, **ids)
        seen.append(rep)
        return out + lines, gated, boolt, rep

    return wrapped


def skin_tier(mod):
    """dyn / baked (handoff/77 sec 1-3), or `ser` -- the two SER permutations
    (40c6faab, ab7f1822) carry no `& ~31` class mask at all; they feed the
    class to OpReorderThreadWithHintNV instead (handoff/88 sec 1). handoff/77's
    own rung leaves those two as pass-through (`ref=12(6 spp4-dyn + 4
    spp4-baked + 2 pass-through)`) and so does this one: they get the gated
    bounce floor and no skin bump."""
    ands = sum(bool(re.search(r'= OpBitwiseAnd %uint %\w+ %uint_4294967264\s*$',
                              ln)) for ln in mod.lines)
    if ands == 0:
        return 'ser'
    if ands != 1:
        die(f"{mod.name}: {ands} class-mask BitwiseAnd, expected 0 or 1")
    tier, _ = SPP.detect_tier(mod.lines)
    return tier


def patch_skin_gated(mod, tier, spp, base, base_dline):
    _, reads = SPP.detect_tier(mod.lines)
    if spp == 0 or tier == 'ser':
        return {"tier": tier, "spp": 0,
                "emitted": "nothing (--spp 0)" if spp == 0
                           else "nothing (SER permutation, no class mask -- "
                                "pass-through, as in handoff/77)"}
    seen = []
    orig = SPP.clone_class_fetch
    SPP.clone_class_fetch = _wrap_class_fetch(base, base_dline, seen)
    try:
        if tier == 'dyn':
            rep = SPP.patch_dyn(mod, spp, reads)
        else:
            rep = SPP.patch_baked(mod, spp)
    finally:
        SPP.clone_class_fetch = orig
    if len(seen) != 1:
        die(f"{mod.name}: skin gate emitted {len(seen)} times, expected 1")
    rep['tier'] = tier
    return rep


# ---------------------------------------------------------------- driver

def process(path, outdir, n, spp, expect_tier):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    n_traces = sum('OpTraceRayKHR' in ln for ln in mod.lines)
    base, base_dline = find_cbv_base(mod)
    tier = skin_tier(mod)
    if expect_tier and tier != expect_tier:
        die(f"{mod.name}: detected tier {tier}, --expect {expect_tier}")

    rep = dict(module=mod.name, ident=mod.ident, tier=tier,
               cbv_base=base, cbv_word=CBV_WORD, rayn_component=RAYN_COMP)
    if problems:
        rep['module_warnings'] = problems

    # SKIN FIRST, BOUNCE SECOND, and the order is load-bearing twice over:
    #  * the bounce gate emits its own cbv[188].y read, which would flip 77's
    #    tier probe from `baked` to `dyn` and would then be swallowed by the
    #    dyn tier's own use-rewrite (the gate would end up reading `eff`, the
    #    per-pixel count, instead of the engine's RayNumber);
    #  * 89's path-loop detector tolerates 77's surgery (the wired sample loop
    #    seeds its half accumulators with 0.0, so the 3-unit-phi throughput
    #    discriminator stays clean and the path loop stays nested inside it),
    #    which is asserted, not assumed -- find_bounce_bound dies otherwise.
    rep['skin_spp'] = patch_skin_gated(mod, tier, spp, base, base_dline)
    # re-find the base: the skin pass shifted line numbers, not ids.
    base, base_dline = find_cbv_base(mod)
    consts, edits, rep['bounce'] = patch_bounce_gated(mod, n, base, base_dline)
    apply_edits(mod, consts, edits)

    if sum('OpTraceRayKHR' in ln for ln in mod.lines) != n_traces:
        die(f"{mod.name}: trace count changed -- this patch adds ITERATIONS "
            f"and a loop bound, never a trace site")
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
    ap.add_argument('--n', type=int, default=3,
                    help='bounce-loop floor WHEN ACCUMULATING; 0 = skip')
    ap.add_argument('--spp', type=int, default=4,
                    help='skin sample floor WHEN ACCUMULATING; 0 = skip')
    ap.add_argument('--off', action='store_true',
                    help='byte-identity control: run every detector, emit '
                         'nothing (equivalent to --n 0 --spp 0)')
    ap.add_argument('--expect', choices=('dyn', 'baked'))
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    n, spp = (0, 0) if a.off else (a.n, a.spp)
    if not 0 <= n <= 8:
        ap.error('--n must be in [0,8]')
    if spp and not 2 <= spp <= 16:
        ap.error('--spp must be 0 or in [2,16]')
    print(json.dumps(process(a.spvasm, a.outdir, n, spp, a.expect)))


if __name__ == '__main__':
    main()
