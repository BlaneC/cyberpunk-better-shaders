#!/usr/bin/env python3
"""Tier-1 c1 on the ReSTIR-GI *diffuse* raygens -- the 48 SS9 Site A splice,
as corrected by the probe-gi launch readout (handoff/50).

The probe named this family: the S2 bounce-lit face moved red (its paint),
-0.32..-0.35 in ln(G/R) against three in-frame controls and the R3-off null,
every face sub-region agreeing. So bounce-lit skin gets the skin BRDF factor
here, not in `rgs_reference_main` (green stayed second-order).

Three of SS9's structural claims about these four modules are WRONG, each
proven offline before this patcher was written:
  * the >>5 class shift does NOT dominate the radiance write (guarded-fetch
    phi trap again); the dominating form is the class OpPhi -- reuse
    patch_subtype_probe.find_gi_class, which the served probe already proved.
  * NoV is NOT in scope: no dot against the pixel normal dominates the
    write in any of the four, and no view vector is ever computed (Lambert
    needs none). The only honest angle is NoL, and only in the lit arm.
  * the four are not one shape: the SPATIOTEMPORAL pair (006ba4e3, 038867e9)
    re-shades the winning reservoir in its tail (albedo x 1/pi x NoL, then
    x radiance*W), while the SPATIAL pair (5e1e98e4, fc60b8a0) only
    re-weights radiance that was shaded upstream -- its tail has no BRDF
    site at all, and its only 1/pi evals are the self-normalizing p-hat
    loops (the SS9 "do not touch the pdf" rule, one level up).

So the splice is two shapes under one feature:
  ST pair -- c1's NoL-half at the lit-arm shading triple:
        c1_l = (1 + (rho_f-1)*(1-NoL)^2.5) * (1 + (rho_r-1)*NoL^2.5)
    (the NoV factors of BRDF_HANDOFF tier-1 pinned to their maximum, per
    SS9's own fallback language: ship the half you can prove and say so).
  SP pair -- the flat factor cbar = E[c1_l] under cosine-weighted NoL, at
    the write channels the probe painted (reach proven on screen). Both
    pairs write the SAME image (registers[5]+1), so they are alternative
    finals, never chained: no pixel can collect the factor twice.

Both gated on the probe's dominating class-1 form. Identity off skin.
--strength scales both rhos toward 1 (0.5 -> 1.175/1.125): 42 SS6's rule,
start the rung below where the eye sits -- mixed-light pixels already carry
the compute resolvers' c1 on their direct term.
"""

import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_subtype_probe as PSP
from patch_skin_brdf import apply_edits, die, replace_all_uses, roundtrip_check
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG
from patch_compute_brdf import find_image_writes, detect_target_env

ST = ('006ba4e3c8c05205', '038867e9a3bf0626')   # spatiotemporal: tail BRDF
SP = ('5e1e98e44d854712', 'fc60b8a0b56529b8')   # spatial: re-weight only
RHO_F, RHO_R, EXPO = 1.35, 1.25, 2.5
LUM = ('0_212599993', '0_715200007', '0_0722000003')

# 74: the terminator colour bleed (handoff/53), on BOUNCE light. Same closed
# form and the same amplitudes as the compute-side bleed -- w = sat(1 -
# NoL/0.35)^2, m_R = 1 + 0.336k*w, m_B = 1 - 0.101k*w, m_G = 1 -- but NoL here
# is the ST tail's own cosine against the RESERVOIR's sample direction, so the
# warm edge appears where indirect light grazes the skin. This is what the
# compute bleed structurally cannot do: those modules write the direct-light
# term only (46 s12), so indoors, where bounce dominates, the rosy terminator
# cue washed out. The SP pair carries NO bleed: it has no angle in scope, and
# the flat cosine-weighted expectation E[m_R] = 1.007 / E[m_B] = 0.998 is an
# order of magnitude below the S3 measurement floor -- emitting it would be
# a variable that cannot be seen.
BLEED_R, BLEED_B, BLEED_BAND = 0.336, 0.101, 0.35


def rhos(strength):
    return 1.0 + (RHO_F - 1.0) * strength, 1.0 + (RHO_R - 1.0) * strength


def c1_l(x, rf, rr):
    return (1.0 + (rf - 1.0) * (1.0 - x) ** EXPO) * (1.0 + (rr - 1.0) * x ** EXPO)


def cbar(strength, n=4096):
    """E[c1_l] over the cosine-weighted hemisphere: integral 2x*c1_l(x) dx."""
    rf, rr = rhos(strength)
    return sum(2.0 * ((i + 0.5) / n) * c1_l((i + 0.5) / n, rf, rr)
               for i in range(n)) / n


# ------------------------------------------------------------- ST detector
def find_st_shading_triple(mod, wline):
    """The unique albedo x 1/pi x NoL triple whose values reach the radiance
    write through value ops only. The p-hat loop copies of the same formula
    scalarize through a luminance dot or pass through the reservoir's FDiv
    normalization -- neither is on the allowed path, so they cannot reach."""
    dl = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%[\w$]+)\s*=\s*Op', ln)
        if m:
            dl[m.group(1)] = i

    def d(v):
        return mod.lines[dl[v]] if v in dl else ''

    pi_prod = {}   # id -> line, for  %x = OpFMul %float %a %float_0_318309873
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%[\w$]+)\s*=\s*OpFMul %float (%[\w$]+) '
                     r'%float_0_318309873', ln)
        if m:
            pi_prod[m.group(1)] = i

    # groups of FMuls (pi_prod x shared scalar), keyed by the scalar
    groups = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%[\w$]+)\s*=\s*OpFMul %float (%[\w$]+) (%[\w$]+)',
                     ln)
        if not m:
            continue
        r, a, b = m.groups()
        if a in pi_prod and b not in pi_prod:
            groups.setdefault(b, []).append((r, i))

    # the scalar must be NMax(eps, NClamp(dot, 0, 1))
    def is_nol(s):
        m = re.match(r'\s*%[\w$]+\s*=\s*OpExtInst %float %[\w$]+ NMax '
                     r'(%[\w$]+) (%[\w$]+)', d(s))
        if not m:
            return False
        args = [x for x in m.groups()]
        cl = [x for x in args
              if re.match(r'\s*%[\w$]+\s*=\s*OpExtInst %float %[\w$]+ NClamp '
                          r'(%[\w$]+) ', d(x))]
        if len(cl) != 1:
            return False
        mm = re.match(r'\s*%[\w$]+\s*=\s*OpExtInst %float %[\w$]+ NClamp '
                      r'(%[\w$]+) ', d(cl[0]))
        return bool(re.match(r'\s*%[\w$]+\s*=\s*OpDot ', d(mm.group(1))))

    cands = [(s, sorted(g, key=lambda t: t[1]))
             for s, g in groups.items() if len(g) == 3 and is_nol(s)]
    if not cands:
        die(f"{mod.name}: no albedo*(1/pi)*NoL triple found")

    # forward reach to the write texel through value ops only
    prop = re.compile(
        r'\s*(%[\w$]+)\s*=\s*(OpFMul %float|OpFAdd %float|OpFSub %float|'
        r'OpSelect %float|OpPhi %float|OpCopyObject %float|'
        r'OpCompositeConstruct %v4float|'
        r'OpExtInst %float %[\w$]+ (?:NMax|NMin|NClamp)) (.*)$')
    texel = re.match(r'\s*OpImageWrite %[\w$]+ %[\w$]+ (%[\w$]+)',
                     mod.lines[wline]).group(1)

    def reaches_write(seed_ids):
        live = set(seed_ids)
        changed = True
        while changed:
            changed = False
            for ln in mod.lines:
                m = prop.match(ln)
                if not m or m.group(1) in live:
                    continue
                ops = re.findall(r'%[\w$]+', m.group(3))
                if any(o in live for o in ops):
                    live.add(m.group(1))
                    changed = True
        return texel in live

    hits = [(s, g) for s, g in cands if reaches_write([r for r, _ in g])]
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} shading triples reach the write "
            f"(candidates at {[ [i+1 for _, i in g] for _, g in cands ]}) -- "
            f"need exactly 1")
    return hits[0]      # (nol_id, [(result, line) x3])


# ---------------------------------------------------- ST channel identity
def _st_albedo_channel(mod, alb):
    """The unique (fetch, component) an ST albedo channel id roots at.

    The compute-side rule (39: never guess a channel from operand order)
    applied to the raygen tail. Bounded multi-path walk over the idioms
    measured on both ST modules (2026-08-31): the frontier/ladder OpPhi
    chains, the diffuse-colour FSub (albedo - albedo*metal -- follow the
    MINUEND only, the subtrahend roots at the metalness fetch), the
    white-override OpSelect, the sRGB squaring decode (FMul x x), and
    literal-scaled FMul/FAdd. Returns None unless EVERY path lands on ONE
    component of ONE v4float image fetch."""
    roots, seen, stack = set(), set(), [(alb, 0)]
    while stack:
        cur, depth = stack.pop()
        if cur in seen:
            continue
        if depth > 12:
            return None
        seen.add(cur)
        _, d = mod.find_def(cur)
        if d is None:
            return None
        me = re.match(r'OpCompositeExtract %float (%[\w$]+) (\d+)\s*$', d)
        if me:
            roots.add((me.group(1), int(me.group(2))))
            continue
        mp = re.match(r'OpPhi %float((?:\s+%[\w$]+)+)\s*$', d)
        if mp:
            stack += [(op, depth + 1) for op in set(mp.group(1).split()[0::2])
                      if not op.startswith('%float_')]
            continue
        ms = re.match(r'OpFSub %float (%[\w$]+) (%[\w$]+)\s*$', d)
        if ms:
            stack.append((ms.group(1), depth + 1))
            continue
        msel = re.match(r'OpSelect %float %[\w$]+ (%[\w$]+) (%[\w$]+)\s*$', d)
        if msel:
            stack += [(op, depth + 1) for op in msel.groups()
                      if not op.startswith('%float_')]
            continue
        mm = re.match(r'OpF(?:Mul|Add) %float (%[\w$]+) (%[\w$]+)\s*$', d)
        if mm:
            a, b = mm.groups()
            if a == b:
                stack.append((a, depth + 1))
            elif a.startswith('%float_'):
                stack.append((b, depth + 1))
            elif b.startswith('%float_'):
                stack.append((a, depth + 1))
            else:
                return None
            continue
        return None
    if len(roots) != 1:
        return None
    vec, idx = next(iter(roots))
    _, dv = mod.find_def(vec)
    if not re.match(r'OpImageFetch %v4float ', dv or ''):
        return None
    return (vec, idx)


def st_triple_channels(mod, triple):
    """{triple result id: albedo component} for the three shading FMuls, or
    die: each is pi_prod x NoL, pi_prod is albedo_ch x 1/pi, and the walk
    must name all three channels {0,1,2} distinct off ONE fetch."""
    out, fetches = {}, set()
    for r, _ in triple:
        _, d = mod.find_def(r)
        m = re.match(r'OpFMul %float (%[\w$]+) (%[\w$]+)\s*$', d or '')
        if not m:
            die(f"{mod.name}: triple member {r} is not a 2-op FMul")
        _, dp = mod.find_def(m.group(1))
        mp = re.match(r'OpFMul %float (%[\w$]+) %float_0_318309873\s*$',
                      dp or '')
        if not mp:
            die(f"{mod.name}: {r}'s first operand is not albedo*(1/pi)")
        root = _st_albedo_channel(mod, mp.group(1))
        if root is None:
            die(f"{mod.name}: albedo channel walk failed for {r} -- "
                f"cannot prove R/B identity, refusing to guess")
        fetches.add(root[0])
        out[r] = root[1]
    if len(fetches) != 1 or sorted(out.values()) != [0, 1, 2]:
        die(f"{mod.name}: triple channels are not {{0,1,2}} of one fetch: "
            f"{out} over {fetches}")
    return out


# ------------------------------------------------------------- ST builder
def build_st(mod, cfg, writes, strength, bleed=0.0):
    rf, rr = rhos(strength)
    glsl = mod.glsl
    if glsl is None:
        for ln in mod.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpExtInstImport "GLSL.std.450"', ln)
            if m:
                glsl = m.group(1)
                break
    if glsl is None:
        die(f"{mod.name}: no GLSL.std.450 import")

    real = [w for w in writes if w['comps']]
    zeroish = [w for w in real
               if all(PSP._gi_zeroish(mod, c) for c in w['comps'][:3])]
    live = [w for w in real if w not in zeroish]
    if len(live) != 1:
        die(f"{mod.name}: expected 1 live radiance write, found {len(live)}")
    wline = live[0]['line']

    nol, triple = find_st_shading_triple(mod, wline)
    shift, cands, how = PSP.find_gi_class(mod, 'gi-diffuse')
    at = max(i for _, i in triple)
    ok = sorted(x for x in cands if cfg.dominates_line(x, at))
    if not ok:
        die(f"{mod.name}: no class form dominates the shading triple at "
            f"line {at + 1}")
    chans = st_triple_channels(mod, triple) if bleed > 0.0 else {}

    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one, eps = C(1.0), C(1e-6)
    ex, drf, drr = C(EXPO), C(rf - 1.0), C(rr - 1.0)
    uid1, ud = mod.uconst(1)
    if ud:
        consts.append(ud)

    I = mod.new_id
    g0, onl, b1, l1, x1, af = I(), I(), I(), I(), I(), I()
    l2, x2, ar, tf, tr, cf, cr, c1, g = (I() for _ in range(9))
    ins = [
        f"        {g0} = OpIEqual %bool {ok[0]} {uid1}",
        f"        {onl} = OpFSub %float {one} {nol}",
        f"        {b1} = OpExtInst %float {glsl} NMax {onl} {eps}",
        f"        {l1} = OpExtInst %float {glsl} Log2 {b1}",
        f"        {x1} = OpFMul %float {l1} {ex}",
        f"        {af} = OpExtInst %float {glsl} Exp2 {x1}",
        f"        {l2} = OpExtInst %float {glsl} Log2 {nol}",
        f"        {x2} = OpFMul %float {l2} {ex}",
        f"        {ar} = OpExtInst %float {glsl} Exp2 {x2}",
        f"        {tf} = OpFMul %float {af} {drf}",
        f"        {tr} = OpFMul %float {ar} {drr}",
        f"        {cf} = OpFAdd %float {one} {tf}",
        f"        {cr} = OpFAdd %float {one} {tr}",
        f"        {c1} = OpFMul %float {cf} {cr}",
        f"        {g} = OpSelect %float {g0} {c1} {one}",
    ]
    gr = gb = None
    if bleed > 0.0:
        # w = sat(1 - NoL/0.35)^2 off the SAME NoL the c1 factor consumes --
        # the band and the factor cannot disagree. Gated on the same class
        # bool; identity off skin, identity for NoL >= 0.35.
        inv, zero = C(1.0 / BLEED_BAND), C(0.0)
        kr, kb = C(BLEED_R * bleed), C(BLEED_B * bleed)
        b1, b2, b3, w, wr, wb, mr, mb = (I() for _ in range(8))
        gr, gb = I(), I()
        ins += [
            f"        {b1} = OpFMul %float {nol} {inv}",
            f"        {b2} = OpFSub %float {one} {b1}",
            f"        {b3} = OpExtInst %float {glsl} NClamp {b2} {zero} {one}",
            f"        {w} = OpFMul %float {b3} {b3}",
            f"        {wr} = OpFMul %float {w} {kr}",
            f"        {wb} = OpFMul %float {w} {kb}",
            f"        {mr} = OpFAdd %float {one} {wr}",
            f"        {mb} = OpFSub %float {one} {wb}",
            f"        {gr} = OpSelect %float {g0} {mr} {one}",
            f"        {gb} = OpSelect %float {g0} {mb} {one}",
        ]
    done = []
    for r, _ in triple:
        n = I()
        ins.append(f"        {n} = OpFMul %float {r} {g}")
        fin, ch = n, chans.get(r)
        if ch == 0:
            fin = I()
            ins.append(f"        {fin} = OpFMul %float {n} {gr}")
        elif ch == 2:
            fin = I()
            ins.append(f"        {fin} = OpFMul %float {n} {gb}")
        uses = replace_all_uses(mod, r, fin, at)
        done.append({"id": r, "chan": ch, "uses_rewritten": uses})
    edits.append((at, ins))
    return consts, edits, {
        "mode": "st-lit-arm", "strength": strength, "rho_f": rf, "rho_r": rr,
        "bleed_k": bleed, "nol": nol, "site_line": at + 1, "class_how": how,
        "gate_on": ok[0], "spliced": done}


# ---------------------------------------------------------------- driver
def process(path, outdir, strength, bleed=0.0):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    h = (mod.ident or '').split('.')[0]
    cfg = CFG(mod)
    writes = find_image_writes(mod)
    rep = dict(module=mod.name, ident=mod.ident, strength=strength)
    if problems:
        rep['module_warnings'] = problems

    if h in ST:
        consts, edits, rep['gi_c1'] = build_st(mod, cfg, writes, strength,
                                               bleed=bleed)
    elif h in SP:
        flat = cbar(strength)
        saved = PSP.GI_TINTS['gi-diffuse']
        PSP.GI_TINTS['gi-diffuse'] = (flat, flat, flat)
        try:
            consts, edits, pr = PSP.build_gi_paint(mod, cfg, writes)
        finally:
            PSP.GI_TINTS['gi-diffuse'] = saved
        pr['mode'] = 'sp-flat'
        pr['flat_factor'] = flat
        rep['gi_c1'] = pr
    else:
        die(f"{mod.name}: {h} is not a restirgi diffuse module")

    apply_edits(mod, consts, edits)
    rep = PSP._emit(mod, outdir, target_env, rep)
    with open(os.path.join(outdir, mod.ident + '.json'), 'w') as f:
        json.dump(rep, f, indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--strength', type=float, required=True)
    ap.add_argument('--bleed', type=float, default=0.0,
                    help='terminator bleed on the ST pair (bleed_k; 0 = off, '
                         'byte-identical to a pre-74 build)')
    ap.add_argument('--out', required=True)
    ap.add_argument('files', nargs='+')
    a = ap.parse_args()
    if not (0.0 < a.strength <= 1.0):
        die(f"--strength {a.strength} outside (0,1]")
    if not (0.0 <= a.bleed <= 3.0):
        die(f"--bleed {a.bleed} outside [0,3]")
    for p in a.files:
        r = process(p, a.out, a.strength, bleed=a.bleed)
        gc = r['gi_c1']
        print("%s  %s  %s%s" % (r['ident'], gc['mode'],
              "site@%d" % gc['site_line'] if 'site_line' in gc
              else "painted=%d flat=%.4f" % (len(gc['painted']),
                                             gc['flat_factor']),
              "  bleed_k=%.2f chans=%s" % (gc['bleed_k'],
                  [x['chan'] for x in gc['spliced']])
              if gc.get('bleed_k') else ""))


if __name__ == '__main__':
    main()
