#!/usr/bin/env python3
"""84: the ENVIRONMENT chroma bleed -- luminance-held chroma widening on the
ReSTIR-GI *diffuse* raygens' final radiance triple.

Walls, floors and props pick up the chroma of the light that bounced onto
them (Night City neon), while each pixel's Rec.709 luminance is held EXACTLY
by construction. Skin (class 1) and hair (class 4) are bit-identical to the
base.

WHY THE SITE IS THE WRITE AND NOT THE BLED SITE -- read this before
"improving" it. The obvious place is where 74/78 put the terminator bleed:
the ST tail's `albedo_ch * (1/pi) * NoL` triple. That triple is ALBEDO-side.
The reservoir's radiance multiplies DOWNSTREAM of it (74 s3, 78 s4), so a
chroma operator there widens the chroma of the ALBEDO -- a grey wall under a
red neon sign stays grey, which is the exact opposite of the feature. The
chroma has to be read AFTER the radiance multiply, and the only point past it
that is per-channel identified is the module's own final radiance triple, the
last per-channel value before the write's fp16 clamp / output encode. That is
where this patcher splices, in all four modules.

THE OPERATOR (per channel, on the site's own RGB triple C, q = --env-chroma):

    Y   = 0.2126*C_R + 0.7152*C_G + 0.0722*C_B        (Rec.709)
    r_c = C_c / max(Y, eps)                           (scale-invariant ratio)
    g_c = (1-q) + q*r_c                               (the widening gain)
    n   = sum_j w_j * r_j * g_j                       (= luma of the widened
                                                       triple, in Y units)
    out_c = C_c * clamp(g_c / max(n, eps), 0, GMAX)

Properties, all BY CONSTRUCTION rather than by tuning:

  * sum_c w_c*out_c == Y exactly (n is precisely the factor the luma grew by,
    and dividing by it takes it back out). Zero energy drift; there is no
    amplitude to get wrong.
  * Non-negative for q in [0,1] and C >= 0: every factor is non-negative
    (g_c >= 1-q >= 0, n >= 1 by Jensen since sum_c w_c*r_c == 1).
  * Homogeneous of degree 1: out(lambda*C) = lambda*out(C). So it commutes
    with the SP pair's flat c1 factor, with exposure, and with any uniform
    scale downstream -- the order of this splice against those cannot matter.
  * It cannot invent a hue. Every channel is multiplied by a POSITIVE scalar,
    so channel ORDER is preserved and a channel that is zero stays zero. The
    chroma can only widen along the direction the indirect term already has.
  * Grey in, grey out (r_c == 1 => g_c == 1 => n == 1).
  * Self-limiting: the gain is affine in the ratio, so a near-neutral pixel
    gets ~(1+q) times its chroma while an already-vivid one moves ~10%.
    dev/env_chroma_model.py prints the table.

GUARDS AND BOUNDS (why nothing here can blow up):

  * n >= 1 for any non-negative C, so max(n, eps) is a NaN/negative guard,
    not a division rescue.
  * g_c/n <= 1/w_c <= 13.86 for non-negative C (proof: out_c <= Y/w_c because
    n >= w_c*r_c*g_c). GMAX = 16 therefore PROVABLY never binds on the domain
    where the hold is claimed; it exists so that a negative or denormal input
    cannot produce an unbounded factor. The verifier checks both halves.
  * The widened value is passed through the module's OWN fp16 clamp idiom
    (NMin(NMax(x, -65504), 65504), the same two constants the module already
    declares) inside the gate-true arm, so a ~2x gain on a channel that was
    already at the fp16 ceiling cannot store an inf (GOTCHAS "scale before a
    clamp": the clamp is the last thing that touches the value). Gate-false
    bypasses it and returns the ORIGINAL id, so skin and hair stay bit-exact
    rather than clamp-exact.

THE GATE: (class != 1) && (class != 4), off the class value the module's OWN
material OpSwitch decodes (cases 1 and 4 on a fetched >>5 -- find_gi_class).
One class word, the same one the shipped skin gate reads. Gate-false takes
OpSelect's ORIGINAL id, so skin and hair are bit-exact, not
approximately-identity.

WHY NO METAL / F0 CLAUSE (the cloth sheen needs one, this does not): this is
a homogeneous rescale of the DIFFUSE GI term, and a metal's diffuse colour is
albedo*(1-metal) ~ 0, so out(0) == 0 exactly. Glass and transparent surfaces
are shaded by a different raygen family entirely (76). There is nothing to
gate off.

WHY IT CANNOT COMPOUND FRAME OVER FRAME: the reservoir is a separate SSBO at
push-constant registers[5], stored ABOVE this splice; the image written here
is registers[5]+1. The widened chroma never re-enters the reservoir. And both
raygen pairs write that same image as alternative finals (50 s4), so no pixel
can collect the factor twice.

Runs as a SECOND pass over an already-built gi rung (dev/build_gi_env.sh), not
inside patch_gi_c1.py: that keeps it out of build_gi_rung.sh's one-variable
assertions, gives a literal "q=0 rebuild is byte-identical", and -- GOTCHAS
rule 12 -- means every detector here runs in a fresh process against bytes
that are fully written, never against ids whose defining instruction is still
pending in an edit list.

    ./dev/patch_gi_env.py <mod.spvasm>... --env-chroma 0.35 --out DIR
"""

import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_subtype_probe as PSP
from patch_skin_brdf import apply_edits, die, replace_all_uses, roundtrip_check
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG
from patch_compute_brdf import find_image_writes, detect_target_env

DIFFUSE = ('006ba4e3c8c05205', '038867e9a3bf0626',
           '5e1e98e44d854712', 'fc60b8a0b56529b8')
LUM_W = (0.2126, 0.7152, 0.0722)
GMAX = 16.0            # > 1/0.0722 = 13.85; provably slack, see the header
EPS = 1e-30            # ~7 orders below the fp16 subnormal floor of the target
SKIN_CLASS, HAIR_CLASS = 1, 4

# the module's own fp16 store clamp, as a pair of GLSL NaN-avoiding ops
CLAMP_HI, CLAMP_LO = '%float_65504', '%float_n65504'


# --------------------------------------------------------------- detector
def _peel_fp16_clamp(mod, cid):
    """comp -> the value the module clamps for the fp16 store, or None.

    The shape is NMin(NMax(x, -65504), 65504) in every RGB-writing
    permutation. Returns x. Anything else returns None, which makes the
    caller die rather than guess a site."""
    m = re.match(r'OpExtInst %float %[\w$]+ NMin (%[\w$]+) ' + CLAMP_HI + r'\s*$',
                 mod.find_def(cid)[1] or '')
    if not m:
        return None
    m2 = re.match(r'OpExtInst %float %[\w$]+ NMax (%[\w$]+) ' + CLAMP_LO + r'\s*$',
                  mod.find_def(m.group(1))[1] or '')
    return m2.group(1) if m2 else None


# Everything that may legitimately consume the final radiance triple between
# our insertion point and the write. Anything else means the triple is ALSO
# feeding something that is not the write (a reservoir store, a p-hat) and the
# splice must not silently reach it -- die instead.
USE_OK = (
    r'OpCompositeConstruct %v3float ',          # the YCoCg encode's source
    r'OpCompositeConstruct %v4float ',          # the write texel
    r'OpPhi %float ',                           # the encode/passthrough ladder
    r'OpExtInst %float %[\w$]+ NMax ',          # the module's own fp16 clamp
    r'OpExtInst %float %[\w$]+ NMin ',
)


def find_env_site(mod, cfg):
    """The single final radiance triple of a GI diffuse raygen, in RGB.

    Two shapes, both measured on the four modules and both enforced, and they
    need two different WIRINGS:

      rgb    the write's three colour components already are R, G, B
             (006ba4e3, 5e1e98e4). The triple IS the components, and the
             splice rebuilds the write's texel -- no use is rewritten. That
             is what makes it immune to the interleaving these permutations
             have: R's own fp16 clamp is emitted between R's and G's
             definitions, so there is no single line below all three
             definitions and above all three uses, and a replace_all_uses
             wiring would silently leave R un-widened.
      ycocg  the write is select(YCoCg(RGB), RGB) of ONE triple: each colour
             component is an OpPhi over {an encode dot, the plain triple
             member for that position} (038867e9, fc60b8a0). The write's
             components are therefore NOT channels -- comp 0 is "Y or R" --
             so the splice goes on the encode's RGB source instead, by
             rewriting its uses. Channel identity is STRUCTURAL, not
             positional: the Co row (0.5, 0, -0.5) is asymmetric in R and B,
             so matching {Y, Co, Cg} pins which member is R and which is B.
             The passthrough arm must then agree position-for-position,
             which is checked, not assumed.
    """
    writes = [w for w in find_image_writes(mod)
              if w['comps'] and not all(PSP._gi_zeroish(mod, c)
                                        for c in w['comps'][:3])]
    if len(writes) != 1:
        die(f"{mod.name}: {len(writes)} live radiance writes, want exactly 1")
    w = writes[0]
    comps = w['comps'][:3]

    leaves = [PSP._gi_leaves(mod, c) for c in comps]
    dots = [d for dd, _p in leaves for d in dd]
    if dots:
        shape = 'ycocg'
        roles, triples = set(), set()
        for d in dots:
            role, tri = PSP._gi_dot_parts(mod, d)
            if role is None or tri is None:
                die(f"{mod.name}: encode dot {d} has no recognizable YCoCg row "
                    f"or no value triple")
            roles.add(role)
            triples.add(tri)
        if roles != {'Y', 'Co', 'Cg'} or len(triples) != 1:
            die(f"{mod.name}: encode dots give roles {sorted(roles)} over "
                f"{len(triples)} triples -- not one YCoCg encode")
        triple = list(triples.pop())
        # the passthrough arm must be the SAME triple, member for member
        for ch, (_dd, plains) in enumerate(leaves):
            if not plains or any(p != triple[ch] for p in plains):
                die(f"{mod.name}: write component {ch}'s non-encode arm is "
                    f"{plains}, not the encode source {triple[ch]} -- the two "
                    f"output arms disagree about the channel, refusing")
    else:
        shape = 'rgb'
        # Every colour component must be the module's own fp16 store clamp:
        # that is what proves these are the final per-channel radiance values
        # and not some other v4 the write happens to build.
        for ch, c in enumerate(comps):
            if _peel_fp16_clamp(mod, c) is None:
                die(f"{mod.name}: write component {ch} ({c}) is neither a "
                    f"YCoCg encode nor an fp16 clamp pair -- unrecognized")
        triple = list(comps)

    if len(set(triple)) != 3:
        die(f"{mod.name}: radiance triple {triple} is not 3 distinct ids")
    dlines = []
    for t in triple:
        dl, _ = mod.find_def(t)
        if dl is None:
            die(f"{mod.name}: triple member {t} has no defining instruction")
        dlines.append(dl)
    uses = {}
    if shape == 'rgb':
        # Wire by rebuilding the texel: insert immediately before the write,
        # which every component provably dominates (they are operands of the
        # texel construct on the line above it). Nothing else is touched, so
        # a reservoir store or a p-hat that reads the same value keeps the
        # base's number by construction -- there is no use to enumerate.
        at = w['line'] - 1
        if mod.find_def(w['texel'])[0] != at:
            die(f"{mod.name}: the write's texel is not built on the line "
                f"above the write -- insertion point unproven")
        for t in triple:
            if not cfg.dominates_line(t, at):
                die(f"{mod.name}: write component {t} does not dominate the "
                    f"insertion line {at + 1}")
    else:
        at = max(dlines)
        if at >= w['line']:
            die(f"{mod.name}: triple defs land at/after the write")
        for t, dl in zip(triple, dlines):
            if dl != at and not cfg.dominates_line(t, at):
                die(f"{mod.name}: triple member {t} does not dominate the "
                    f"insertion line {at + 1}")
        # Every use of the triple below the insertion point gets rewritten.
        # Prove that set is only the write's own tail, so we cannot perturb a
        # reservoir store or a p-hat weight; and that nothing uses it ABOVE
        # us, which would be a use the splice silently misses.
        for t in triple:
            tok = re.compile(r'(?<![%\w])' + re.escape(t) + r'(?![\w])')
            isdef = re.compile(r'^\s*' + re.escape(t) + r'\s*=')
            u = []
            for i, ln in enumerate(mod.lines):
                if isdef.match(ln) or not tok.search(ln):
                    continue
                if i <= at:
                    die(f"{mod.name}: {t} is used at line {i + 1}, above the "
                        f"insertion point {at + 1} -- that use would keep the "
                        f"un-widened value")
                body = ln.split('=', 1)[1].strip() if '=' in ln else ln.strip()
                if not any(re.match(p, body) for p in USE_OK):
                    die(f"{mod.name}: {t} feeds an unexpected consumer at line "
                        f"{i + 1}: {body[:70]} -- the triple is not "
                        f"exclusively the write's, refusing")
                u.append(i + 1)
            if not u:
                die(f"{mod.name}: {t} has no uses below the insertion point")
            uses[t] = u

    shift, cands, how = PSP.find_gi_class(mod, 'gi-diffuse')
    ok = sorted(x for x in cands if cfg.dominates_line(x, at))
    if not ok:
        die(f"{mod.name}: no class form dominates the radiance triple at "
            f"line {at + 1} -- the gate cannot reach the site")
    return dict(shape=shape, triple=triple, at=at, write_line=w['line'],
                uses=uses, class_value=ok[0], class_how=how,
                class_forms=ok, comps=comps, alpha=w['comps'][3],
                texel=w['texel'])


# ---------------------------------------------------------------- builder
def build_env(mod, site, q):
    glsl = mod.glsl
    if glsl is None:
        for ln in mod.lines:
            m = re.match(r'\s*(%\w+)\s*=\s*OpExtInstImport "GLSL.std.450"', ln)
            if m:
                glsl = m.group(1)
                break
    if glsl is None:
        die(f"{mod.name}: no GLSL.std.450 import")

    consts, edits = [], []

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    one, zero, eps = C(1.0), C(0.0), C(EPS)
    gmax = C(GMAX)
    fhi, flo = C(65504.0), C(-65504.0)
    qid, omq = C(q), C(1.0 - q)
    lw = [C(x) for x in LUM_W]
    # uconst() has no pending cache (GOTCHAS): ask once per value, never twice.
    u1, d1 = mod.uconst(SKIN_CLASS)
    if d1:
        consts.append(d1)
    u4, d4 = mod.uconst(HAIR_CLASS)
    if d4:
        consts.append(d4)

    I = mod.new_id
    t = site['triple']
    cls = site['class_value']
    g1, g4, g = I(), I(), I()
    y1, y2, y3, ya, Y, ym, iy = (I() for _ in range(7))
    ins = [
        f"        {g1} = OpINotEqual %bool {cls} {u1}",
        f"        {g4} = OpINotEqual %bool {cls} {u4}",
        f"        {g} = OpLogicalAnd %bool {g1} {g4}",
        f"        {y1} = OpFMul %float {t[0]} {lw[0]}",
        f"        {y2} = OpFMul %float {t[1]} {lw[1]}",
        f"        {y3} = OpFMul %float {t[2]} {lw[2]}",
        f"        {ya} = OpFAdd %float {y1} {y2}",
        f"        {Y} = OpFAdd %float {ya} {y3}",
        f"        {ym} = OpExtInst %float {glsl} NMax {Y} {eps}",
        f"        {iy} = OpFDiv %float {one} {ym}",
    ]
    r, gc, p = [], [], []
    for ch in range(3):
        ri, qi, gi, pi = I(), I(), I(), I()
        ins += [
            f"        {ri} = OpFMul %float {t[ch]} {iy}",
            f"        {qi} = OpFMul %float {ri} {qid}",
            f"        {gi} = OpFAdd %float {omq} {qi}",
            f"        {pi} = OpFMul %float {ri} {gi}",
        ]
        r.append(ri); gc.append(gi); p.append(pi)
    n1, n2, n3, na, n, nm, s = (I() for _ in range(7))
    ins += [
        f"        {n1} = OpFMul %float {p[0]} {lw[0]}",
        f"        {n2} = OpFMul %float {p[1]} {lw[1]}",
        f"        {n3} = OpFMul %float {p[2]} {lw[2]}",
        f"        {na} = OpFAdd %float {n1} {n2}",
        f"        {n} = OpFAdd %float {na} {n3}",
        f"        {nm} = OpExtInst %float {glsl} NMax {n} {eps}",
        f"        {s} = OpFDiv %float {one} {nm}",
    ]
    spliced, sel = [], []
    for ch in range(3):
        hi, hc, oi, cl, cm, se = (I() for _ in range(6))
        ins += [
            f"        {hi} = OpFMul %float {gc[ch]} {s}",
            f"        {hc} = OpExtInst %float {glsl} NClamp {hi} {zero} {gmax}",
            f"        {oi} = OpFMul %float {t[ch]} {hc}",
            # the module's own fp16 store clamp, on the widened value only
            f"        {cl} = OpExtInst %float {glsl} NMax {oi} {flo}",
            f"        {cm} = OpExtInst %float {glsl} NMin {cl} {fhi}",
            f"        {se} = OpSelect %float {g} {cm} {t[ch]}",
        ]
        sel.append(se)
        spliced.append({"chan": ch, "src": t[ch], "out": se})
    if site['shape'] == 'rgb':
        # Rebuild the texel; the alpha component (a hit distance / age, NOT a
        # weight -- GOTCHAS rule 11) is carried through untouched.
        nt = I()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{sel[0]} {sel[1]} {sel[2]} {site['alpha']}")
        mod.lines[site['write_line']] = re.sub(
            r'(OpImageWrite %[\w$]+ %[\w$]+ )%[\w$]+\s*$',
            r'\g<1>' + nt, mod.lines[site['write_line']])
        if nt not in mod.lines[site['write_line']]:
            die(f"{mod.name}: could not rewrite the image write's texel")
        for d in spliced:
            d['uses_rewritten'] = 1
            d['use_lines'] = [site['write_line'] + 1]
        wiring = 'texel-rebuild'
    else:
        # Every consumer below the insertion point was enumerated and
        # allow-listed by the detector; this is what rewrites them.
        for ch, d in enumerate(spliced):
            d['uses_rewritten'] = replace_all_uses(mod, t[ch], sel[ch],
                                                   site['at'])
            d['use_lines'] = site['uses'][t[ch]]
            if d['uses_rewritten'] < len(d['use_lines']):
                die(f"{mod.name}: rewrote {d['uses_rewritten']} uses of "
                    f"{t[ch]}, detector found {len(d['use_lines'])}")
        wiring = 'use-rewrite'
    edits.append((site['at'], ins))
    return consts, edits, {
        "mode": "env-chroma", "shape": site['shape'], "wiring": wiring,
        "q": q, "site_line": site['at'] + 1,
        "write_line": site['write_line'] + 1,
        "class_value": cls, "class_how": site['class_how'],
        "gate": "class != 1 && class != 4", "gmax": GMAX, "eps": EPS,
        "lum_w": list(LUM_W), "instructions": len(ins),
        "spliced": spliced}


# ----------------------------------------------------------------- driver
def process(path, outdir, q):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    h = (mod.ident or '').split('.')[0]
    if h not in DIFFUSE:
        die(f"{mod.name}: {h} is not a ReSTIR-GI diffuse raygen")
    roundtrip_check(path, target_env)
    cfg = CFG(mod)
    rep = dict(module=mod.name, ident=mod.ident, env_chroma=q)
    if problems:
        rep['module_warnings'] = problems
    # DETECT FIRST, EMIT AFTER (GOTCHAS rule 12): build_env's
    # replace_all_uses rewrites mod.lines immediately, so no detector may run
    # after it.
    site = find_env_site(mod, cfg)
    if q <= 0.0:
        # BYTE-INERT AT ZERO, and it has to be inertness of the EMISSION, not
        # of a gate: the 42 rule is that a module can be "patched" with zero
        # spliced instructions and still differ by the constants a patcher
        # declares before it looks at a site. Nothing is declared and nothing
        # is spliced here, so the assembled output is the assembled input --
        # which dev/build_gi_env.sh asserts against the parked base's bytes.
        rep['gi_env'] = {"mode": "env-chroma", "shape": site['shape'],
                         "wiring": "none", "q": 0.0,
                         "site_line": site['at'] + 1,
                         "write_line": site['write_line'] + 1,
                         "class_value": site['class_value'],
                         "class_how": site['class_how'],
                         "gate": "class != 1 && class != 4",
                         "gmax": GMAX, "eps": EPS, "lum_w": list(LUM_W),
                         "instructions": 0, "spliced": []}
    else:
        consts, edits, rep['gi_env'] = build_env(mod, site, q)
        apply_edits(mod, consts, edits)
    rep = PSP._emit(mod, outdir, target_env, rep)
    with open(os.path.join(outdir, mod.ident + '.json'), 'w') as f:
        json.dump(rep, f, indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env-chroma', type=float, required=True,
                    help='q, the chroma widening. 0 = emit NOTHING (the '
                         'output is byte-identical to the input); 1 = the '
                         'non-negativity ceiling.')
    ap.add_argument('--out', required=True)
    ap.add_argument('files', nargs='+')
    a = ap.parse_args()
    if not (0.0 <= a.env_chroma <= 1.0):
        die(f"--env-chroma {a.env_chroma} outside [0,1]: above 1 the gain "
            f"(1-q) + q*r goes negative for a dim channel and the operator "
            f"stops being a widening")
    for p in a.files:
        r = process(p, a.out, a.env_chroma)
        e = r['gi_env']
        print("%s  %s  %-5s site@%d write@%d  chans=%s  +%d instr"
              % (r['ident'], e['mode'], e['shape'], e['site_line'],
                 e['write_line'], [x['chan'] for x in e['spliced']] or 'none',
                 e['instructions']))


if __name__ == '__main__':
    main()
