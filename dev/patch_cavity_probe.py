#!/usr/bin/env python3
"""Light-struct DEBUG PAINT probe -- settles handoff/93 sec 5.

93 established that the cavity cone's area-light over-darkening (88 sec 5c)
cannot be repaired at the two spliced local-light NEE sites, because neither
site has any source-extent input: site A shades every light as a POINT with an
analytic 1/d^2 falloff and no pdf at all, and site B's only 1/pdf is a discrete
RIS light-SELECTION weight (wsum/p_hat) in units of 1/luminance.

The ONE open question is 93 sec 1.2: the 64-byte light struct's offset-12 HIGH
half (`U` below) has exactly ONE use in 14949 lines --

    %4832 = OpFAdd %float U R        ; R == offset 12 LOW half, the range
    %4833 = OpFMul %float %4832 %4832
    %4834 = OpFOrdGreaterThan %bool d2 %4833      ; cull if d2 > (U + R)^2

-- so it is either a SOURCE RADIUS (which would make k*mix(sa_ratio,1,...)
buildable at site A) or a cull/fade margin (which would kill the whole track).
One use is not an identification and 93 refused to guess it. This patcher
answers it by PAINT, not by argument: it replaces the light's own radiance
triple with a monotonic encoding of the struct fields, so a single screenshot
reads the values off the lit skin.

WHY THE RADIANCE TRIPLE AND NOT THE OUTPUT. Overwriting the shaded result
would make every visible light add a flat colour into the same accumulator,
so an N-light frame reads as a saturated sum of N constants. Rewriting the
light's COLOUR instead keeps the engine's own 1/d^2 * spot * BRDF * visibility
weighting intact: the frame still looks like a lit frame, the nearest lamp
still dominates its own neighbourhood, and the probe is read by HUE and by
CHANNEL RATIO, both of which are invariant to that common weighting -- and
therefore also invariant to the base rung's cavity factor.

Each of the three OpCompositeExtracts of the offset-16 radiance load has
EXACTLY ONE use in the module (asserted, 12/12), so three operand rewrites are
the whole edit.

CHANNELS (mode `u`, the decisive rung):
    R_ch = saturate(R / RSCALE)        the KNOWN field: the attenuation range.
                                       The sanity channel -- if this does not
                                       vary sensibly with fixture reach, the
                                       whole decode is wrong and nothing else
                                       in the frame is readable.
    G_ch = saturate(U / USCALE)        the UNKNOWN, monotonic.
    B_ch = saturate(U / max(R, eps))   the RATIO. Scale-free per light: if U is
                                       a cull margin PROPORTIONAL to range this
                                       is the same value on every fixture; if U
                                       is a physical radius it varies by orders
                                       of magnitude between a bulb and a panel.

CHANNELS (mode `44`): decodes the other packed half2 the struct carries.
    R_ch = saturate(spot_scale / SSCALE)   offset 44 LOW half
    G_ch = saturate(spot_bias)             offset 44 HIGH half (1.0 for an omni)
    B_ch = saturate(U / max(R, eps))       the same ratio anchor as mode `u`

IDENTITY WHEN DEAD. Each rewrite is OpSelect(gate, paint, THE ORIGINAL ID), so
a false gate makes the site compute the original value bit-for-bit. The gate is
class-1 skin AND path_counter == 0 -- the FIXED gate of handoff/90 sec 1, never
E.find_bounce_counter, which returns the SAMPLE counter in 5 of 12 modules.

`--gain 0` emits NOTHING while running every detector: the byte-identity
control.

  ./dev/patch_cavity_probe.py <in.spvasm> --mode u --rscale 20 --uscale 0.5 \
      --outdir DIR
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
import cfg_dom
from patch_cavity2 import find_class_word, find_path_counter
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env

EPS = 1e-4          # divisor guard on R (metres); R is never legitimately ~0
STRIDE = 64         # the light struct 93 sec 1 decodes
OFF_RANGE = 12      # packed half2: lo = attenuation range R, hi = U (UNKNOWN)
OFF_RAD = 16        # v3float radiance -- the triple we repaint
OFF_SPOT = 44       # packed half2: lo = cone scale, hi = cone bias
MASK = 39           # the engine's own shadow cullMask


# ---------------------------------------------------------------- detection
def _raw_chains(mod, fs, fe):
    """Every OpRawAccessChainNV on the 64-byte light struct, keyed by field."""
    pat = re.compile(
        r'\s*(%\w+)\s*=\s*OpRawAccessChainNV (%\w+) (%\w+) %uint_'
        + str(STRIDE) + r' (%\w+) %uint_(\d+) RobustnessPerElementNV\s*$')
    out = []
    for i in range(fs, fe):
        m = pat.match(mod.lines[i])
        if m:
            out.append(dict(line=i, ptr=m.group(1), ptype=m.group(2),
                            base=m.group(3), idx=m.group(4),
                            off=int(m.group(5))))
    return out


def _loaded(mod, fs, fe, ptr):
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLoad %\w+ ' + re.escape(ptr)
                     + r'(?: Aligned \d+)?\s*$', mod.lines[i])
        if m:
            return i, m.group(1)
    return None, None


def _uses(mod, idtok):
    """(line, text) for every instruction that MENTIONS idtok but is not its
    own definition."""
    out = []
    for i, ln in enumerate(mod.lines):
        if re.match(r'\s*' + re.escape(idtok) + r'\s*=', ln):
            continue
        if re.search(re.escape(idtok) + r'(?![0-9A-Za-z_])', ln):
            out.append((i, ln))
    return out


def _vis_targets(mod, fs, fe):
    """The second operands of the 3 FMuls that consume a literal-mask-39
    trace's visibility scalar. Used only to tell site A (the light-loop NEE)
    apart from the RIS CANDIDATE loop, which reads the same struct fields but
    whose radiance reaches a shading site only THROUGH the reservoir phis.
    """
    tp = re.compile(r'\s*OpTraceRayKHR (%\w+) %uint_\d+ %uint_' + str(MASK)
                    + r' %uint_1 %uint_1 %uint_0 (%\w+) (%\w+) (%\w+) (%\w+) '
                    r'(%\w+)\s*$')
    tgt = set()
    for i in range(fs, fe):
        m = tp.match(mod.lines[i])
        if not m:
            continue
        pay = m.group(6)
        t = None
        for j in range(i + 1, min(i + 8, fe)):
            g = re.match(r'\s*(%\w+)\s*=\s*OpLoad %float (%\w+)\s*$',
                         mod.lines[j])
            if g:
                _, cd = mod.find_def(g.group(2))
                if re.match(r'OpInBoundsAccessChain %\w+ ' + re.escape(pay)
                            + r' %uint_3\s*$', cd or ''):
                    t = g.group(1)
                break
        if t is None:
            continue
        eq = vis = None
        for j in range(i + 1, min(i + 10, fe)):
            g = re.match(r'\s*(%\w+)\s*=\s*OpFOrdEqual %\w+ ' + re.escape(t)
                         + r' %float_10000\s*$', mod.lines[j])
            if g:
                eq = g.group(1)
                break
        if eq is None:
            continue
        for j in range(i + 1, min(i + 12, fe)):
            g = re.match(r'\s*(%\w+)\s*=\s*OpSelect %float ' + re.escape(eq)
                         + r' %float_1 %float_0\s*$', mod.lines[j])
            if g:
                vis = g.group(1)
                break
        if vis is None:
            continue
        # V is the visibility itself (unpatched base) or the cavity rung's
        # OpFMul(vis, fac) -- either way it is the value with exactly 3 FMuls.
        cands = [vis]
        for j in range(fs, fe):
            g = re.match(r'\s*(%\w+)\s*=\s*OpFMul %float ' + re.escape(vis)
                         + r' (%\w+)\s*$', mod.lines[j])
            if g:
                cands.append(g.group(1))
        for V in cands:
            muls = [re.match(r'\s*(%\w+)\s*=\s*OpFMul %float ' + re.escape(V)
                             + r' (%\w+)\s*$', mod.lines[j])
                    for j in range(fs, fe)]
            muls = [m2.group(2) for m2 in muls if m2]
            if len(muls) == 3:
                tgt.update(muls)
    return tgt


def _reaches_no_phi(mod, fs, fe, start, targets, limit=4000):
    """Forward def-use reachability that REFUSES to cross an OpPhi.

    This is the whole discriminator. Site A's radiance extracts reach a
    shading site by straight dataflow; the RIS candidate loop's reach one only
    through the reservoir's OpPhis (93 sec 2), so refusing phis separates them
    without hard-coding either.
    """
    seen, stack, n = set(), [start], 0
    while stack and n < limit:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        n += 1
        for i, ln in _uses(mod, cur):
            if not (fs <= i < fe):
                continue
            m = re.match(r'\s*(%\w+)\s*=\s*(Op\S+)', ln)
            if not m:
                continue
            if m.group(2) == 'OpPhi':
                continue
            if m.group(1) in targets:
                return True
            stack.append(m.group(1))
    return False


def find_paint_site(mod, fs, fe):
    """Site A: the light-loop NEE's own 64-byte light struct read.

    Required, and each half dies rather than guesses:
      * a stride-64 offset-16 v3float radiance load,
      * the SAME (base, index) also loading offset 12 and offset 44,
      * the three radiance extracts having EXACTLY ONE use each,
      * those extracts reaching a mask-39 trace's visibility multiply by
        straight dataflow (no OpPhi) -- which the RIS candidate loop cannot do.
    Exactly one group must qualify.
    """
    chains = _raw_chains(mod, fs, fe)
    if not chains:
        die(f"{mod.name}: no stride-{STRIDE} light-struct raw access chains")
    tgt = _vis_targets(mod, fs, fe)
    if not tgt:
        die(f"{mod.name}: found no mask-{MASK} visibility multiply triple")
    groups = {}
    for c in chains:
        groups.setdefault((c["base"], c["idx"]), {})[c["off"]] = c
    hits = []
    for key, g in groups.items():
        if not {OFF_RANGE, OFF_RAD, OFF_SPOT} <= set(g):
            continue
        if g[OFF_RAD]["ptype"] != '%_ptr_StorageBuffer_v3float':
            continue
        rl, rad = _loaded(mod, fs, fe, g[OFF_RAD]["ptr"])
        if rad is None:
            continue
        ext = []
        for comp in (0, 1, 2):
            e = None
            for i in range(rl, min(rl + 8, fe)):
                m = re.match(r'\s*(%\w+)\s*=\s*OpCompositeExtract %float '
                             + re.escape(rad) + r' ' + str(comp) + r'\s*$',
                             mod.lines[i])
                if m:
                    e = (i, m.group(1))
                    break
            if e is None:
                break
            ext.append(e)
        if len(ext) != 3:
            continue
        if not _reaches_no_phi(mod, fs, fe, ext[0][1], tgt):
            continue
        u12 = _loaded(mod, fs, fe, g[OFF_RANGE]["ptr"])
        u44 = _loaded(mod, fs, fe, g[OFF_SPOT]["ptr"])
        if u12[1] is None or u44[1] is None:
            continue
        uses = []
        for _, eid in ext:
            us = _uses(mod, eid)
            if len(us) != 1:
                die(f"{mod.name}: radiance extract {eid} has {len(us)} uses, "
                    f"expected exactly 1 -- the operand rewrite is not safe")
            uses.append(us[0][0])
        hits.append(dict(base=key[0], idx=key[1], rad_load=rl, rad=rad,
                         ext=[e[1] for e in ext], ext_line=[e[0] for e in ext],
                         use_line=uses, off12=u12[1], off12_line=u12[0],
                         off44=u44[1], off44_line=u44[0],
                         off12_chain=g[OFF_RANGE]["ptr"],
                         off44_chain=g[OFF_SPOT]["ptr"],
                         rad_chain=g[OFF_RAD]["ptr"]))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} candidate light-loop NEE struct reads, "
            f"expected exactly 1")
    return hits[0]


# ------------------------------------------------------------------- build
def build(mod, mode, gain, rscale, uscale, sscale):
    consts, edits = [], []
    E._uc.__defaults__[-1].clear()
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    glsl = E._glsl_set(mod)

    # ---- detectors, all of them, before any edit (GOTCHAS 12) -------------
    site = find_paint_site(mod, fs, fe)
    cls_word, cls_fetch, cls_line = find_class_word(mod, fs, fe)
    path_ctr, path_hdr = find_path_counter(mod, fs, fe)
    samp_ctr = E.find_bounce_counter(mod, fs, fe, site["rad_load"])
    splice = min(site["use_line"])

    cnt_line, _ = mod.find_def(path_ctr)
    need = [("class word", cls_line), ("path counter", cnt_line),
            ("offset-12 load", site["off12_line"]),
            ("offset-44 load", site["off44_line"])]
    for e, l in zip(site["ext"], site["ext_line"]):
        need.append((f"radiance extract {e}", l))
    for tag, dl in need:
        if not cfg_dom.dominates(mod, fs, fe, dl, splice):
            die(f"{mod.name}: {tag} (line {dl+1}) does not dominate the paint "
                f"splice (line {splice+1})")

    rep = {"mode": mode, "gain": gain, "rscale": rscale, "uscale": uscale,
           "sscale": sscale, "eps": EPS, "stride": STRIDE,
           "struct_base": site["base"], "struct_index": site["idx"],
           "radiance_load_line": site["rad_load"] + 1,
           "radiance_extracts": site["ext"],
           "use_lines": [u + 1 for u in site["use_line"]],
           "off12_id": site["off12"], "off44_id": site["off44"],
           "class_word": cls_word, "class_line": cls_line + 1,
           "path_counter": path_ctr, "path_header": path_hdr,
           "sample_counter": samp_ctr,
           "legacy_helper_was_wrong": samp_ctr != path_ctr,
           "splice_before_line": splice + 1, "n_sites": 1, "n_rewrites": 3}

    if gain == 0.0:
        rep["emitted"] = "nothing (gain=0 identity control)"
        return [], [], rep

    boolt = E._ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                           lambda n: f"    {n} = OpTypeBool")
    v2f = E._ensure_line(mod, consts,
                         r'\s*(%\w+)\s*=\s*OpTypeVector %float 2\s*$',
                         lambda n: f"    {n} = OpTypeVector %float 2")
    u0 = E._uc(mod, consts, 0)
    u1 = E._uc(mod, consts, 1)
    u16 = E._uc(mod, consts, 16)
    for tok in ('%float_0', '%float_1'):
        if not any(re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant '
                            r'%float ', ln) for ln in mod.lines):
            die(f"{mod.name}: expected constant {tok} is absent")
    f0, f1 = '%float_0', '%float_1'
    finvR = E._fc(mod, consts, 1.0 / rscale)
    finvU = E._fc(mod, consts, 1.0 / uscale)
    finvS = E._fc(mod, consts, 1.0 / sscale)
    feps = E._fc(mod, consts, EPS)

    ind = '               '
    ins = []

    def em(fmt):
        i = mod.new_id()
        ins.append(f"{ind}{i} = {fmt.format(i=i)}")
        return i

    def half2(src):
        a = em(f"OpExtInst {v2f} {glsl} UnpackHalf2x16 {src}")
        lo = em(f"OpCompositeExtract %float {a} 0")
        s = em(f"OpShiftRightLogical %uint {src} {u16}")
        b = em(f"OpExtInst {v2f} {glsl} UnpackHalf2x16 {s}")
        hi = em(f"OpCompositeExtract %float {b} 0")
        return lo, hi

    def sat(x):
        return em(f"OpExtInst %float {glsl} NClamp {x} {f0} {f1}")

    R, U = half2(site["off12"])                 # range, the unknown
    Rg = em(f"OpExtInst %float {glsl} NMax {R} {feps}")
    ratio = sat(em(f"OpFDiv %float {U} {Rg}"))  # the scale-free anchor channel

    if mode == 'u':
        pr = sat(em(f"OpFMul %float {R} {finvR}"))
        pg = sat(em(f"OpFMul %float {U} {finvU}"))
        pb = ratio
    elif mode == '44':
        SC, BI = half2(site["off44"])
        pr = sat(em(f"OpFMul %float {SC} {finvS}"))
        pg = sat(BI)
        pb = ratio
    else:
        die(f"unknown mode {mode}")

    g_skin = em(f"OpIEqual {boolt} {cls_word} {u1}")
    g_b0 = em(f"OpIEqual {boolt} {path_ctr} {u0}")
    gate = em(f"OpLogicalAnd {boolt} {g_skin} {g_b0}")

    outs = []
    for paint, orig in zip((pr, pg, pb), site["ext"]):
        # FALSE OPERAND IS THE ORIGINAL ID -- gate false is bit-for-bit base.
        outs.append(em(f"OpSelect %float {gate} {paint} {orig}"))

    edits.append((splice - 1, ins))
    for line, orig, new in zip(site["use_line"], site["ext"], outs):
        old = mod.lines[line]
        rewritten = re.sub(re.escape(orig) + r'(?![0-9A-Za-z_])', new, old)
        if rewritten == old:
            die(f"{mod.name}: paint operand rewrite did not take at line "
                f"{line+1}")
        mod.lines[line] = rewritten

    rep["gate"] = gate
    rep["paint"] = {"r": pr, "g": pg, "b": pb}
    rep["selects"] = outs
    rep["emitted"] = len(ins)
    return consts, edits, rep


def process(path, outdir, mode, gain, rscale, uscale, sscale):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['probe'] = build(mod, mode, gain, rscale, uscale,
                                        sscale)
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
    ap.add_argument('--mode', choices=('u', '44'), default='u')
    ap.add_argument('--gain', type=float, default=1.0,
                    help='0 emits nothing: the byte-identity control')
    ap.add_argument('--rscale', type=float, default=20.0,
                    help='metres mapping to full red (the KNOWN range field)')
    ap.add_argument('--uscale', type=float, default=0.5,
                    help='metres mapping to full green (the UNKNOWN field)')
    ap.add_argument('--sscale', type=float, default=2.0,
                    help='mode 44: spot-cone scale mapping to full red')
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    print(json.dumps(process(a.spvasm, a.outdir, a.mode, a.gain, a.rscale,
                             a.uscale, a.sscale), indent=1))


if __name__ == '__main__':
    main()
