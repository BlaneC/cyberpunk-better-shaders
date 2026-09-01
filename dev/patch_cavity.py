#!/usr/bin/env python3
"""Skin-gated traced CONTACT SHADOW ("cavity") for the reference raygens.

handoff/85. Census + design: 85 sec 1-3. Machinery lineage: the injected-trace
splice is 55's clone-by-id sentinel, proven executing in this family by 56
(clone site) and 60 (NEW site, overridden operands, literal flags, CHS
round-trip of hitT). Detectors are reused verbatim from patch_earglow.py.

WHAT IT DOES, one paragraph
---------------------------
In each paintable rgs_reference_main, at the block that guards the module's
own DIRECT SUN shading, inject ONE short OpTraceRayKHR from the surface
straight toward the sun. A hit inside tmax means a contact-scale occluder the
engine's own sun ray did not see, and the module's three direct-sun terms are
multiplied by (1-k). Bounce light, GI, local lights, sky and emissive are not
touched: the multiply lands on the three
    OpFMul %float NClamp(diffuse*NoL + spec, 0, 1), sunRadiance_c
instructions and on nothing else (each sunRadiance component has exactly three
uses in every one of the 12 permutations -- two CompositeConstructs feeding a
dot-with-itself nonzero test, and that one FMul).

WHY THE ORIGIN IS `prehit` AND NOT THE NEE TRACE'S OWN ORIGIN
-------------------------------------------------------------
The engine builds its sun-shadow origin as
    origin_i = prehit_i + c0*N_i*clamp(0.005*sqrt(t), 0.005, 0.1)*[N.z>0]
                        - c1*D_i*(1 + 9*clamp(t*0.001, 0, 1))
with c0/c1 = cbv[..][77].xy (unknown at build time). The normal term FLOORS at
0.005*c0 metres -- an unknown mm-scale lift, at exactly the scale of the
cavities this feature exists to darken. So the cavity ray starts at `prehit`
(the un-biased traced surface point, harvested 12/12 by
patch_earglow.find_origin_offset) and rejects self-hits with its own tmin.

TMIN = 0.5 mm, against BOTH failure modes
-----------------------------------------
  * acne: worst-case float position error at face range is |P_cam|*2^-23 <~ 1um,
    so the grazing re-hit distance eps/sin(theta) stays under 0.5mm down to
    theta ~ 0.1 deg -- 500x margin, and 500x the engine's own 1e-6 tmin. The
    STRUCTURAL kill is the cull mode: at this site N.S > 0 always (the block is
    frontlit-only), so the only geometric way to re-hit your own triangle is
    from underneath, which is a BACK face -- and the ray is
    CullBackFacingTriangles. Belt (cull mode) and braces (tmin).
  * 70 W1's thin-card taxonomy: strand/collar cards at 0.2-0.5mm are WANTED
    occluders here. The sign is flipped from ear glow -- a card that read as
    *flesh* was a leak; a card that *casts a contact shadow* is the feature --
    so the floor clears float error and preserves the 1-2mm lip/eyelid crease
    rather than rejecting cards.

FOUR-PATH IDENTITY WHEN DEAD (nothing depends on the miss shader)
-----------------------------------------------------------------
payload member 3 is pre-armed to 10000 and occluded = (t > 4e-4) AND (t < tmax):
  gate false  -> cullMask 0 -> guaranteed miss -> t stays 10000 -> upper fails
  trace dead  -> nothing writes            -> t stays 10000 -> upper fails
  miss writes 10000 (the engine convention) ->            upper fails
  miss writes 0    (56 rung A left this open) ->          LOWER fails
and factor = Select(occluded, 1-k, 1.0) is then exactly 1.0, so every rewritten
site computes src*1.0 == src bit-for-bit. 56's rung A limit is respected: the
miss leg carries no information in this design.

GATE
----
class-1 skin (clone of the module's own G-buffer material fetch, & ~31 == 32 --
57 sec 3.2: class 1 has no sub-structure, so the gate is complete for skin)
AND bounce == 0 (the loop counter phi) AND the module's own sun-visibility
branch condition. That last conjunct is what makes double-darkening against the
engine's own shadow STRUCTURALLY IMPOSSIBLE: the site only executes where the
engine's own NEE ray called the pixel LIT. cullMask 39 = the engine's own sun
mask (enumerated across all 12: every NEE trace is Select(cond,0,39)), so the
cavity ray sees exactly the occluder set the engine's sun ray sees.

NO PRNG DRAW
------------
The direction is the NEE trace's own direction operand VERBATIM -- already a
sun-disc sample drawn from the module's LCG (1664525/1013904223) and scaled by
cbv[..][82].y. Reusing it gives free per-frame penumbra convergence under
photo-mode accumulation AND leaves the LCG chain untouched, so every downstream
sample's noise is bit-identical to the base. The A/B is one variable at the
pixel, not just at the build.

  ./dev/patch_cavity.py <in.spvasm> --k 0.85 --tmax 0.006 --outdir DIR
  --k 0 emits NOTHING (all detectors still run): the byte-identity control.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

TMIN = 5e-4     # ray tmin: 0.5 mm (see the docstring's two-failure-mode argument)
TLOW = 4e-4     # lower validity bound, below tmin: a miss that wrote 0 fails closed
CULL = 16       # CullBackFacingTrianglesKHR -- ear glow v1-v4's flag, proven
                # executing and round-tripping hitT on screen (60 sec 0)
MASK = 39       # the engine's own sun-shadow cullMask (enumerated, all 12)


def find_sun_branch(mod, nee, fs, fe):
    """The visibility branch that guards the module's DIRECT SUN block.

    Asserted hop by hop from the sun-NEE trace; any deviation dies (GOTCHAS 10:
    a structural guard that can be satisfied by the wrong structure is not a
    guard, so this walks the whole shape rather than pattern-matching one line):

        t3   = OpLoad %float <chain on the NEE payload, member 3>
        eq   = OpFOrdEqual %bool t3 %float_10000          (miss => visible)
        vis  = OpSelect %float eq %float_1 %float_0
        vb   = OpSelect %float <backlit> %float_0 vis
        c1   = OpCompositeConstruct %v3float r0 r1 r2     (sun radiance)
        c2   = OpCompositeConstruct %v3float r0 r1 r2
        dot  = OpDot %float c1 c2
        prod = OpFMul %float vb dot
        cond = OpFOrdGreaterThan %bool prod %float_0
               OpSelectionMerge <merge> None
               OpBranchConditional cond <then> <merge>

    Returns cond, the merge label's line, the OpSelectionMerge line, and the
    sun radiance triple.
    """
    n = nee["line"]

    def dref(idt, pat, what):
        _, d = mod.find_def(idt)
        m = re.match(pat + r'\s*$', d or '')
        if not m:
            die(f"{mod.name}: sun-branch walk ({what}): {idt} is {d!r}, "
                f"wanted {pat}")
        return m

    br = None
    for i in range(n + 1, min(n + 24, fe)):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', mod.lines[i])
        if m:
            br = (i, m.group(1), m.group(2), m.group(3))
            break
    if br is None:
        die(f"{mod.name}: no OpBranchConditional within 24 lines of the sun-NEE trace")
    bline, cond, tlab, flab = br
    sm = re.match(r'\s*OpSelectionMerge (%\w+) None\s*$', mod.lines[bline - 1])
    if not sm:
        die(f"{mod.name}: line before the sun branch is not OpSelectionMerge: "
            f"{mod.lines[bline - 1]!r}")
    merge = sm.group(1)
    if merge not in (tlab, flab):
        die(f"{mod.name}: sun branch merge {merge} is neither branch target")

    gm = dref(cond, r'OpFOrdGreaterThan %bool (%\w+) %float_0', 'cond')
    fm = dref(gm.group(1), r'OpFMul %float (%\w+) (%\w+)', 'prod')
    vb, dot = fm.group(1), fm.group(2)
    _, dd = mod.find_def(dot)
    if not re.match(r'OpDot %float %\w+ %\w+\s*$', dd or ''):
        vb, dot = dot, vb
    dm = dref(dot, r'OpDot %float (%\w+) (%\w+)', 'dot')
    rad = None
    for c in (dm.group(1), dm.group(2)):
        cm = dref(c, r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)',
                  'radiance composite')
        r3 = [cm.group(1), cm.group(2), cm.group(3)]
        if rad is None:
            rad = r3
        elif rad != r3:
            die(f"{mod.name}: the two dot operands are different composites: "
                f"{rad} vs {r3}")
    sm2 = dref(vb, r'OpSelect %float (%\w+) %float_0 (%\w+)', 'backlit select')
    if sm2.group(1) != nee["backlit"]:
        die(f"{mod.name}: visibility select tests {sm2.group(1)}, but the "
            f"NEE cullMask's backlit bool is {nee['backlit']}")
    vm = dref(sm2.group(2), r'OpSelect %float (%\w+) %float_1 %float_0',
              'visible select')
    em = dref(vm.group(1), r'OpFOrdEqual %bool (%\w+) %float_10000', 'miss compare')
    lm = dref(em.group(1), r'OpLoad %float (%\w+)', 'payload member-3 load')
    cm3 = dref(lm.group(1),
               r'OpInBoundsAccessChain %\w+ ' + re.escape(nee["ops"][10]) +
               r' %uint_3', 'member-3 chain on the NEE payload')

    # the sun radiance triple must be the module's own cbv slot-6 extracts
    sunrad = E.find_sun_radiance(mod, n)
    if sunrad != rad:
        die(f"{mod.name}: branch radiance {rad} != slot-6 extracts {sunrad}")

    mlab = None
    for i in range(bline, fe):
        if re.match(r'\s*' + re.escape(merge) + r' = OpLabel', mod.lines[i]):
            mlab = i
            break
    if mlab is None:
        die(f"{mod.name}: merge label {merge} has no OpLabel")
    return {"cond": cond, "sel_line": bline - 1, "merge_line": mlab, "rad": rad}


def find_sun_sites(mod, fs, fe, sb):
    """The three DIRECT SUN terms: OpFMul(NClamp(BRDF,0,1), sunRadiance_c).

    Asserts, per channel: exactly one such FMul in the function; its non-
    radiance operand is an NClamp to [0,1]; the radiance component has exactly
    three uses in the whole module (the two composites of the branch's dot,
    plus this FMul) -- so multiplying here reaches every consumer of the direct
    sun term and nothing else (GOTCHAS 3: count what consumes the value).
    And the site sits strictly INSIDE the structured selection region the
    visibility branch guards, which is what makes the splice's value dominate it.
    """
    sites = []
    for c, r in enumerate(sb["rad"]):
        hits = []
        for i in range(fs, fe):
            m = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float (%\w+) '
                         + re.escape(r) + r'\s*$', mod.lines[i])
            if m:
                hits.append((i, m.group(1), m.group(2)))
        if len(hits) != 1:
            die(f"{mod.name}: channel {c}: {len(hits)} FMul(x, {r}) sites, "
                f"expected exactly 1")
        line, res, src = hits[0]
        _, sd = mod.find_def(src)
        if not re.match(r'OpExtInst %float %\w+ NClamp %\w+ %float_0 %float_1\s*$',
                        sd or ''):
            die(f"{mod.name}: channel {c}: FMul source {src} is not an "
                f"NClamp(.,0,1): {sd!r}")
        uses = 0
        for ln in mod.lines:
            if re.match(r'\s*' + re.escape(r) + r'\s*=', ln):
                continue
            uses += len(re.findall(re.escape(r) + r'(?![0-9A-Za-z_])', ln))
        if uses != 3:
            die(f"{mod.name}: channel {c}: sun radiance {r} has {uses} uses, "
                f"expected exactly 3 (2 composites + 1 FMul)")
        if not (sb["sel_line"] < line < sb["merge_line"]):
            die(f"{mod.name}: channel {c}: site at line {line+1} is not inside "
                f"the visibility selection region "
                f"({sb['sel_line']+1}..{sb['merge_line']+1})")
        sites.append({"line": line, "res": res, "src": src, "rad": r})
    return sites


def build(mod, k, tmax):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()          # the memo is keyed on id(mod)
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    ptrS, _ = E._payload_ptr_and_struct(mod, 'RayPayloadKHR')

    # ---- detectors: ALL of them, before any edit (GOTCHAS 12) -------------
    nee = E.find_nee_trace(mod, fs, fe)
    sb = find_sun_branch(mod, nee, fs, fe)
    sites = find_sun_sites(mod, fs, fe, sb)
    counter = E.find_bounce_counter(mod, fs, fe, nee["line"])
    fetch_root = E.find_class_fetch(mod, fs, fe)
    offctor = E.find_origin_offset(mod, nee)
    eb_lab, eb_term = E.entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))

    rep = {"k": k, "tmax": tmax, "tmin": TMIN, "tlow": TLOW,
           "cull_flags": CULL, "cullmask": MASK,
           "nee_line": nee["line"] + 1, "backlit": nee["backlit"],
           "sun_cond": sb["cond"], "sun_radiance": sb["rad"],
           "counter_phi": counter, "class_fetch": fetch_root,
           "prehit": offctor["prehit"], "offset_cbv_slot": offctor["slot"],
           "sites": [{"line": s["line"] + 1, "res": s["res"],
                      "src": s["src"], "rad": s["rad"]} for s in sites],
           "n_sites": len(sites)}
    if len(sites) != 3:
        die(f"{mod.name}: {len(sites)} sun sites, expected 3")

    if k == 0.0:
        # the byte-identity control: every assert above still fires, nothing
        # is emitted, and the rebuilt .spv must cmp equal to the base.
        rep["emitted"] = "nothing (k=0 identity control)"
        return [], [], rep

    # ---- constants --------------------------------------------------------
    ptrPF = E._ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %float\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %float")
    ptrPU = E._ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %uint\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %uint")
    boolt = E._ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
        lambda n: f"    {n} = OpTypeBool")
    u0 = E._uc(mod, consts, 0)
    u1 = E._uc(mod, consts, 1)
    u2 = E._uc(mod, consts, 2)
    u3 = E._uc(mod, consts, 3)
    u16 = E._uc(mod, consts, CULL)
    u32 = E._uc(mod, consts, 32)
    u39 = E._uc(mod, consts, MASK)
    # %float_0 / %float_1 are guaranteed present by find_sun_sites' NClamp
    # assertion, %float_10000 by find_nee_trace's tmax -- use the module's own
    # tokens rather than minting -0.0 through mod.const().
    f0, f1, f10000 = '%float_0', '%float_1', '%float_10000'
    for tok in (f0, f1, f10000):
        if not any(re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant %float ', ln)
                   for ln in mod.lines):
            die(f"{mod.name}: expected constant {tok} is absent")
    ftmin = E._fc(mod, consts, TMIN)
    ftlow = E._fc(mod, consts, TLOW)
    ftmax = E._fc(mod, consts, tmax)
    f1mk = E._fc(mod, consts, 1.0 - k)

    # fresh payload variable, on the SPIR-V 1.4 entry interface (GOTCHAS)
    spay = mod.new_id()
    consts.append(f"    {spay} = OpVariable {ptrS} RayPayloadKHR")
    mod.lines[eline] = mod.lines[eline].rstrip() + ' ' + spay

    # ---- the splice: straight-line, immediately before OpSelectionMerge ----
    ind = '               '
    ins = []
    nid = mod.new_id

    # class-1 skin gate: clone the module's own material fetch to this site
    cloned = []
    fetch_here = E.clone_chain(mod, fetch_root, safe, {}, cloned, fs)
    for cid, body in cloned:
        ins.append(f"{ind}{cid} = {body}")
    g_ext = nid(); ins.append(f"{ind}{g_ext} = OpCompositeExtract %uint {fetch_here} 1")
    g_and = nid(); ins.append(f"{ind}{g_and} = OpBitwiseAnd %uint {g_ext} %uint_4294967264")
    g_skin = nid(); ins.append(f"{ind}{g_skin} = OpIEqual {boolt} {g_and} {u32}")
    g_b0 = nid(); ins.append(f"{ind}{g_b0} = OpIEqual {boolt} {counter} {u0}")
    g_a1 = nid(); ins.append(f"{ind}{g_a1} = OpLogicalAnd {boolt} {g_skin} {g_b0}")
    g_a2 = nid(); ins.append(f"{ind}{g_a2} = OpLogicalAnd {boolt} {g_a1} {sb['cond']}")
    g_msk = nid(); ins.append(f"{ind}{g_msk} = OpSelect %uint {g_a2} {u39} {u0}")

    # origin = prehit: the un-biased traced surface point (see the docstring)
    org = nid(); ins.append(f"{ind}{org} = OpCompositeConstruct %v3float "
                            + ' '.join(offctor["prehit"]))

    # pre-arm: member 3 = 10000 (the identity default), 0/1/2 defined
    m0c = nid(); ins.append(f"{ind}{m0c} = OpInBoundsAccessChain {ptrPU} {spay} {u0}")
    m1c = nid(); ins.append(f"{ind}{m1c} = OpInBoundsAccessChain {ptrPU} {spay} {u1}")
    m2c = nid(); ins.append(f"{ind}{m2c} = OpInBoundsAccessChain {ptrPF} {spay} {u2}")
    m3c = nid(); ins.append(f"{ind}{m3c} = OpInBoundsAccessChain {ptrPF} {spay} {u3}")
    ins.append(f"{ind}OpStore {m0c} {u0}")
    ins.append(f"{ind}OpStore {m1c} {u0}")
    ins.append(f"{ind}OpStore {m2c} {f0}")
    ins.append(f"{ind}OpStore {m3c} {f10000}")

    # the cavity ray: AS and direction cloned by id from the sun-NEE trace,
    # SBT 1/1/0 = the radiance hit groups (whose CHS writes hitT into member 3
    # -- the leg 56 rung B and 60 proved), flags 16, our own origin/tmin/tmax.
    ins.append(f"{ind}OpTraceRayKHR {nee['ops'][0]} {u16} {g_msk} {u1} {u1} {u0} "
               f"{org} {ftmin} {nee['ops'][8]} {ftmax} {spay}")

    t = nid(); ins.append(f"{ind}{t} = OpLoad %float {m3c}")
    lo = nid(); ins.append(f"{ind}{lo} = OpFOrdGreaterThan {boolt} {t} {ftlow}")
    hi = nid(); ins.append(f"{ind}{hi} = OpFOrdLessThan {boolt} {t} {ftmax}")
    occ = nid(); ins.append(f"{ind}{occ} = OpLogicalAnd {boolt} {lo} {hi}")
    fac = nid(); ins.append(f"{ind}{fac} = OpSelect %float {occ} {f1mk} {f1}")

    # (1-k) on the three direct-sun terms. The new FMul is inserted here (so it
    # dominates every site) and each site's FMul has ONE operand token
    # rewritten -- no consumer edits, no replace_all_uses, no new control flow.
    # Scaling after the module's own NClamp(.,0,1) is safe here and only here:
    # the factor is <= 1, so the product stays strictly inside the clamp the
    # shader already applied (GOTCHAS "scale before a clamp" -- this cannot
    # push anything toward inf, it can only shrink).
    edits.append((sb["sel_line"] - 1, ins))

    # The (1-k) multiply is emitted immediately BEFORE each site, not at the
    # splice: the site's NClamp source is defined inside the sun block, i.e.
    # after the splice point, so an FMul on it there would be an undefined-id
    # reference (GOTCHAS "splice ordering matters"). `fac` is defined at the
    # splice, which dominates the whole selection region.
    for s in sites:
        sline, sdef = mod.find_def(s["src"])
        if not (sb["sel_line"] < sline < s["line"]):
            die(f"{mod.name}: NClamp source {s['src']} at line {sline+1} is not "
                f"between the splice ({sb['sel_line']+1}) and its site "
                f"({s['line']+1})")
        nf = nid()
        s["new_src"] = nf
        edits.append((s["line"] - 1,
                      [f"{ind}{nf} = OpFMul %float {s['src']} {fac}"]))

    # in-place operand rewrites (line count unchanged, so they are index-safe
    # before apply_edits; every detector above has already run -- GOTCHAS 12)
    for s in sites:
        old = mod.lines[s["line"]]
        new = re.sub(r'OpFMul %float ' + re.escape(s["src"]) + r' '
                     + re.escape(s["rad"]) + r'\s*$',
                     f"OpFMul %float {s['new_src']} {s['rad']}", old)
        if new == old:
            die(f"{mod.name}: operand rewrite did not take at line {s['line']+1}")
        mod.lines[s["line"]] = new

    rep["payload_var"] = spay
    rep["splice_before_line"] = sb["sel_line"] + 1
    rep["factor_id"] = fac
    rep["emitted"] = len(ins)
    for s, r in zip(sites, rep["sites"]):
        r["new_src"] = s["new_src"]
    return consts, edits, rep


def process(path, outdir, k, tmax):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['cavity'] = build(mod, k, tmax)
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
    ap.add_argument('--k', type=float, required=True,
                    help='contact-shadow strength; occluded direct sun is '
                         'scaled by (1-k). 0 emits nothing (identity control).')
    ap.add_argument('--tmax', type=float, required=True,
                    help='cavity ray tmax in metres (design axis: 0.006 '
                         'contact-only / 0.015 deep)')
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    if not 0.0 <= args.k <= 1.0:
        ap.error('--k must be in [0,1]')
    if args.k != 0.0 and not TMIN * 4 <= args.tmax <= 0.05:
        ap.error('--tmax must be between 4*tmin and 50mm')
    print(json.dumps(process(args.spvasm, args.outdir, args.k, args.tmax)))


if __name__ == '__main__':
    main()
