#!/usr/bin/env python3
"""
patch_compute_brdf.py -- the GLCompute lighting-resolve anchor family.

The unifying explanation for six sessions of null results (handoff/07): the
game's RT passes (shadow / restirgi / reflection raygens, and the hit shaders
behind the thin PT raygens) produce SAMPLES -- visibility, reservoirs,
reflection hits. The pixels the player sees are shaded in COMPUTE: 84 dumped
whole-library GLCompute modules carry the full material stack (1/pi diffuse,
Disney retro constant 0.107508637, and the same `gbuf>>5 == 1` skin gate the
raygens use). Patching raygens or hit shaders perturbs sampling weights at
most; the visible BRDF lives here. That is why forcetint on dispatched,
swapped raygens changed nothing on screen.

This patcher marks skin through the final image write:

    %texel = OpCompositeConstruct %v4float r g b a
             OpImageWrite %img %coord %texel

For every OpImageWrite whose texel is a v4float construct, the r,g,b
components are multiplied by the tint, gated on the module's own skin test
(class 1). Skin-gated red at the resolve output is simultaneously the
diagnostic ("is compute the visible surface") and the original control the
hair hunt needs. Dominance of the gate over each write is COMPUTED, not
assumed (CFG + dominators from patch_shadow_brdf); a write the gate cannot
reach falls back to refetching the class from the G-buffer at the write site
(the shadow-patcher tactic), and only if that also fails is the write skipped
and reported.

Identity note: these modules carry hash-only OpStrings ("<libhash>.dxil"), so
the swap files are named "<libhash>.dxil.spv" -- which is exactly the id the
layer's scan_dxil_id produces. The Module ident regex was fixed for this
(it used to return None on one-dot OpStrings).

Usage:
  python3 dev/patch_compute_brdf.py <dump>.spvasm --outdir swaps/
  python3 dev/patch_compute_brdf.py <dump>.spvasm --ungated --outdir swaps/
"""

import argparse, json, os, re, subprocess, sys, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import (Module, apply_edits, roundtrip_check, die,
                             find_skin_gate)
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value


def find_image_writes(mod):
    """Every OpImageWrite whose texel is a v4float OpCompositeConstruct."""
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        img, coord, texel = m.groups()
        dline, d = mod.find_def(texel)
        mc = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      d or '')
        out.append(dict(line=i, img=img, coord=coord, texel=texel,
                        comps=list(mc.groups()) if mc else None,
                        texel_line=dline))
    return out


def build_skinmark(mod, cfg, writes, tint, ungated):
    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one = C(1.0)
    tids = [C(x) for x in tint]
    gate = None if ungated else find_skin_gate(mod)
    ctx = None
    done, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({"line": w['line'] + 1, "why": "texel not a v4 construct"})
            continue
        ins = []
        if ungated:
            sel = tids
        else:
            g = gate
            if not cfg.dominates_line(gate, w['line']):
                # The module's own gate cannot reach this write -- refetch the
                # class here, exactly as the shadow patcher does at its sites.
                if ctx is None:
                    ctx = find_class_fetch(mod)
                bad = [x for x in class_fetch_inputs(ctx)
                       if not cfg.dominates_line(x, w['line'])]
                if bad:
                    skipped.append({"line": w['line'] + 1,
                                    "why": f"gate and refetch both fail ({bad})"})
                    continue
                cls = emit_class_value(mod, ctx, ins)
                g = mod.new_id()
                ins.append(f"        {g} = OpIEqual %bool {cls} %uint_1")
            sel = []
            for ch in range(3):
                s = mod.new_id()
                ins.append(f"        {s} = OpSelect %float {g} {tids[ch]} {one}")
                sel.append(s)
        newc = []
        for ch in range(3):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {w['comps'][ch]} {sel[ch]}")
            newc.append(n)
        nt = mod.new_id()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        # insert just above the write, then point the write at the new texel
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die(f"{mod.name}: no image write could be tinted "
            f"({len(skipped)} skipped)")
    return consts, edits, {"writes": done, "skipped": skipped,
                           "gate": "none" if ungated else gate}


def detect_target_env(path):
    """Read the '; Version: X.Y' header spirv-dis writes. The compute libs are
    SPIR-V 1.3 while the RT modules are 1.4, and 1.4 tightened the entry-point
    interface rules -- assembling a 1.3 module as 1.4 fails validation on the
    UNPATCHED input."""
    for ln in open(path, errors='replace').readlines()[:6]:
        m = re.match(r';\s*Version:\s*(\d+)\.(\d+)', ln)
        if m:
            return f"spv{m.group(1)}.{m.group(2)}"
    return None


def process(path, outdir, tint, ungated, target_env, do_rt=True):
    detected = detect_target_env(path)
    if detected:
        target_env = detected
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity in OpString")
    if do_rt:
        roundtrip_check(path, target_env)
    writes = find_image_writes(mod)
    if not writes:
        die(f"{mod.name}: no OpImageWrite found -- not a resolve shader")
    cfg = CFG(mod)
    consts, edits, marks = build_skinmark(mod, cfg, writes, tint, ungated)
    rep = dict(module=mod.name, ident=mod.ident,
               tier='skinmark-ungated' if ungated else 'skinmark',
               image_writes=len(writes), tint=list(tint), mark=marks)
    if problems:
        rep['module_warnings'] = problems

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
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--ungated', action='store_true',
                    help='tint every pixel, no skin gate (bisect step)')
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

    reports = [process(p, a.outdir, tuple(tint), a.ungated, a.target_env,
                       do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reports, indent=1))


if __name__ == '__main__':
    main()
