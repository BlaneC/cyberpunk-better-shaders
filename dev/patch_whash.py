#!/usr/bin/env python3
"""107 -- the world-hash material pack: triplanar micro-detail on rough
dielectrics (B), porous backscatter for concrete (C), and the `micro-cell`
crawl diagnostic, all seeded by `dev/whash_core`'s world-stable hash.

NEW FILE.  It imports `wpos_core`, `patch_subtype_probe`, `patch_compute_skin`,
`patch_shadow_brdf`, `patch_compute_brdf` and `patch_skin_brdf` READ-ONLY and
edits none of them.

--------------------------------------------------------------------------
WHY THIS SHAPE, AND WHERE EACH THING IS SPLICED
--------------------------------------------------------------------------
`99` gave the resolvers a world-space P.  `107` is the first feature built on
it.  Everything here is a *material* decision keyed on world position, which
is the one thing the primitive is for and the one thing a denoiser cannot
smear: the field is static in the world, so temporal accumulation sees texture
rather than noise.  **It is never a sampling seed** -- `whash_core`'s
docstring says why, in bold.

There are four splice families and they are at four different places, because
the resolvers decode their material in a fixed order and not everything is in
scope everywhere.  Measured over the 77 compute modules of the standing base:

  material decode  albedo, metallic, F0, albedo*(1-metal)   line ~550
  position         P = M . (px, py, depth, 1) / w           line ~640
  BRDF             alpha, a2, D, Vis, spec                  line ~900+
  radiance write   OpImageWrite                             end

  1. THE HOIST (once per module).  Everything world-space is emitted ONCE, at
     `HL` = the last of {P's own leaves, the metallic def, the class anchor}.
     P is one value per invocation, so the fbm is one value per invocation;
     emitting it per site would cost ~800 instructions x 376 sites.  P is
     obtained through `wpos_core.emit_world_pos`, which REFETCHES here (the
     module's own P is computed ~300 lines later) -- and it may, because
     `pos_leaves` are all module-entry values.  Measured: HL dominates 343 of
     343 alphas, 157 of 157 Burley scalars and 376 of 376 sheen sites in all
     75 reachable modules.

  2. B-ROUGHNESS, at each distinct `alpha` definition (343).  `alpha` is the
     site's own GGX alpha = authored roughness^2.  Rewritten with
     `replace_all_uses` at its DEF line, exactly as the shipped gloss cap
     does, so the D term, the Vis term and any importance-sampling branch all
     see one value and cannot disagree.  The 343 alphas were checked to be
     mutually independent (no alpha is in another's backward def cone), so no
     alpha can be perturbed twice.

  3. B-ALBEDO, at each Burley diffuse scalar `f_d` (157) -- 81 sec 3's sites.
     NOT at the albedo triple.  The albedo channels are decoded ~90 lines
     BEFORE P and ~350 before any roughness, so a gate that needs both cannot
     be built there: measured, the roughness roots dominate the diffuse-colour
     triple in **2 of 75** modules.  Perturbing `f_d` instead perturbs the
     diffuse REFLECTANCE by the same +-6 %, achromatically, and leaves F0
     alone -- which for a dielectric under this gate is the same picture to
     within the 4 % Fresnel share.  This is a real deviation from "perturb
     albedo" and it is stated in handoff/107 sec 9, not buried.

  4. C-POROUS, at each sheen splice (376) -- 81's own site set, reached with
     81's own `find_sheen_inputs`, its `_emit_fuzz_lobe`, its `_emit_defres`,
     its `_saturate_cosines` and its `_fold_cosine`, all imported unchanged.

  5. micro-cell paints at the 150 radiance writes instead, and carries NO
     perturbation: it is a falsifier, and a falsifier that also changes the
     thing it is testing is worth nothing.

--------------------------------------------------------------------------
THE GATES
--------------------------------------------------------------------------
B (`--gate-*`), all four clauses, at the alpha and the f_d splices:

    class != 1 (skin) && class != 4 (hair) && class != 8 (eyes)
      && metallic < 0.10
      && roughness > 0.60           (i.e. the site's own alpha > 0.36)

`80` sec 2.3's rough-dielectric proxy with two changes, both deliberate:
class 8 (eyes) is excluded as well -- `97` sec 1.5 names it and a wet eye is
not a rough dielectric -- and the metal clause tests **metallic directly**
rather than `max3(F0) < 0.09`.  The metallic scalar is the lerp parameter of
`F0 = lerp(0.04, albedo, metallic)`, read structurally out of the same triple
81 reads F0 from, so it is the authored value with no albedo mixed in.

C narrows B further:

    ... && roughness > 0.75         (alpha > 0.5625)
      && max3(albedo) - min3(albedo) < 0.08      (low saturation)

The saturation clause runs on the RAW albedo triple (the operands of the
`albedo - 0.04` that feeds the F0 lerp), not on the diffuse colour: at
metallic < 0.1 they differ by <10 %, and the raw triple dominates 376 of 376
sheen sites while the diffuse colour is a phi in some.

--------------------------------------------------------------------------
ORDERING (GOTCHAS 12)
--------------------------------------------------------------------------
`replace_all_uses` rewrites `mod.lines` IMMEDIATELY, while `apply_edits` runs
at the end.  Between the two, a backwards walk dead-ends silently.  So every
detector in this file runs in `_detect()` BEFORE the first emission, and the
results are carried in a dict.  Nothing below `_detect` reads the listing to
find an anchor.

Usage:
    python3 dev/patch_whash.py <mod.spvasm> --outdir DIR
        [--micro-rough 0.08] [--micro-alb 0.06] [--porous 0.06]
        [--paint cell] [--cell 0.012] [--seed 0x...] [--octaves 3]
        [--fade-near 6] [--fade-far 14]
"""
import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, replace_all_uses, die
from patch_chs_brdf import load_lenient, uses_of
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
import patch_subtype_probe as SP
from patch_subtype_probe import (_emit_fuzz_lobe, _emit_defres,
                                 _saturate_cosines, _fold_cosine,
                                 find_diffuse_scalars)
import wpos_core as W
import whash_core as H

# ---------------------------------------------------------------- declines
# BY NAME, and only these two.  Both are `99`'s KNOWN_DECLINE and the reason
# is the same one: no P chain, so no world position, so nothing this document
# is about can be evaluated in them.
#   99bb7c2698997b2a -- the coarse indirect-bounce GI resolver.  It computes
#                       no view vector (97 sec 1.5), so wpos_core finds no
#                       M.(x,y,depth,1)/w reconstruction.  62 GGX D sites,
#                       49 alphas and 81 sheen sites live here and are NOT
#                       reached.  This is the single biggest coverage hole in
#                       107 and it is named, not rounded away.
#   ab0bc2fee876d489 -- writes v4uint into an OpTypeImage %int 2D: a sample-
#                       index / reservoir pass, not a resolver (46 sec 12).
#                       20 D sites, 16 alphas.
KNOWN_DECLINE = {'99bb7c2698997b2a', 'ab0bc2fee876d489'}

# Census of the standing base
# gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense.
# build_whash.sh FAILS on any drift from these numbers.
CENSUS = dict(modules=77, reached=75, declined=2,
              ggx_d_all=473, ggx_d=391,          # GGX D sites: all / reachable
              alphas=343, sheen_all=457, sheen=376,
              fd_all=173, fd=157, writes=150)

DEFAULTS = dict(
    cell=0.012,              # 12 mm, handoff/107 sec 2
    seed=0xCA11157C,         # "callisto" -- any uint32; only decorrelation matters
    octaves=3,
    lacunarity=2.0,
    gain=0.5,
    fade_near=6.0,
    fade_far=14.0,
    gate_metal=0.10,
    gate_rough=0.60,         # B: alpha > 0.36
    gate_rough_c=0.75,       # C: alpha > 0.5625
    gate_sat=0.08,
    rough_floor=0.045,       # the perturbed roughness cannot go below this
    a_porous=0.9,            # Charlie alpha "near 1"
    porous_cap=0.5,          # the same NMin cap 81 puts on its cloth lobe
    porous_defres=1.0,
    paint_lo=0.55,           # micro-cell hue endpoints (a MULTIPLY on radiance)
    paint_hi=1.85,
)

CLASS_EXCLUDE = (1, 4, 8)    # skin, hair, eyes -- 97 sec 1.5


# --------------------------------------------------------------- detectors
def find_ggx_d_sites(mod):
    """Every GGX `D = a2 / (pi * x)` with `a2 = alpha*alpha`.

    This is `patch_skin_brdf.find_ggx_sites`'s anchor with its three WINDOWED
    searches (Vis within 80 lines, outputs within 160, the Schlick pow5 within
    220) removed, and it is why this file has its own copy rather than calling
    the shared one.  On the pristine `-deep` base the two agree; on the
    STANDING base -- which carries the peach fuzz, the cloth sheen, the cavity
    cone, the fog, the ear glow and the glints, all of which insert
    instructions between D and its consumer -- the windowed version finds 417
    of the 473 sites that are still there, and the 56 it loses are a silent
    coverage hole.  The anchor here is the pi denominator plus the
    `OpFMul(alpha, alpha)` numerator, both of which are exact and neither of
    which any splice can move.

    `vd` (the unique FMul consuming D) is found without a window too, and is
    what `_fold_cosine` needs.
    """
    pi = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float 3.14159274\b', ln)
        if m:
            pi = m.group(1)
            break
    if pi is None:
        return []
    out = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFDiv %float (%\d+) (%\d+)\s*$', ln)
        if not m:
            continue
        d_id, a2_id, den = m.groups()
        _, dn = mod.find_def(den)
        if not dn or not re.match(r'OpFMul %float %\d+ ' + re.escape(pi) + r'\s*$', dn):
            continue
        _, a2d = mod.find_def(a2_id)
        am = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', a2d or '')
        if not am or am.group(1) != am.group(2):
            continue
        cons = [j for j in uses_of(mod, d_id)
                if re.match(r'\s*%\d+\s*=\s*OpFMul %float ', mod.lines[j])]
        vd = re.match(r'\s*(%\d+)', mod.lines[cons[0]]).group(1) if len(cons) == 1 else None
        out.append(dict(line=i, d=d_id, a2=a2_id, alpha=am.group(1), vd=vd))
    return out


def find_material_triples(mod):
    """`F0 = lerp(0.04, albedo, metallic)`, returning ALBEDO and METALLIC too.

    `patch_subtype_probe.find_f0_triples` parses the identical shape and keeps
    only F0 and metallic; 107 needs the albedo operand for its saturation
    clause, so the same walk is repeated here rather than the shared function
    being edited.  The two 0.04 constants of opposite sign make the shape
    unambiguous (81 sec 8); three consecutive channels must share one metallic.
    """
    per = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+) = OpFAdd %float (%\d+) '
                     + re.escape(SP.F0_LERP_C) + r'\s*$', ln)
        if not m:
            continue
        f0, y = m.groups()
        mm = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', SP._def(mod, y) or '')
        if not mm:
            continue
        for z, mt in (mm.groups(), mm.groups()[::-1]):
            ma = re.match(r'OpFAdd %float (%\d+) ' + re.escape(SP.F0_LERP_NC)
                          + r'\s*$', SP._def(mod, z) or '')
            if ma:
                per[i] = (f0, mt, ma.group(1))
                break
    out, i, keys = [], 0, sorted(per)
    while i < len(keys):
        a = keys[i]
        if (a + 1 in per and a + 2 in per
                and per[a][1] == per[a + 1][1] == per[a + 2][1]):
            out.append(dict(line=a + 2,
                            f0=(per[a][0], per[a + 1][0], per[a + 2][0]),
                            alb=(per[a][2], per[a + 1][2], per[a + 2][2]),
                            met=per[a][1]))
            i += 3
            while i < len(keys) and keys[i] <= a + 2:
                i += 1
            continue
        i += 1
    return out


def dom_line(cfg, def_line, use_line):
    """Structured-CFG dominance between two LINES.

    `CFG.dominates_line` takes an id; the hoist has no id yet when its
    position is being chosen, so the same block walk is done on the line.
    """
    db = cfg.block_of(def_line)
    ub = cfg.block_of(use_line)
    if db is None:
        return True
    if ub is None:
        return False
    if db['label'] not in cfg.reachable or ub['label'] not in cfg.reachable:
        return False
    if db['label'] == ub['label']:
        return def_line < use_line
    return db['label'] in cfg.dom.get(ub['label'], set())


TERMINATORS = ('OpBranch', 'OpBranchConditional', 'OpSwitch', 'OpReturn',
               'OpReturnValue', 'OpKill', 'OpUnreachable', 'OpSelectionMerge',
               'OpLoopMerge', 'OpLabel')


def _opcode(line):
    s = line.strip()
    if not s:
        return ''
    if s.startswith('%') and '=' in s:
        return s.split('=', 1)[1].strip().split()[0]
    return s.split()[0]


def _detect(mod, cfg):
    """EVERY read-only walk, all of it, before the first emission.

    GOTCHAS 12: `replace_all_uses` rewrites `mod.lines` in place, and any
    detector that runs afterwards walks into ids whose defining instruction is
    still sitting in an unapplied edit list.  It fails silently, which from
    the chair is identical to the feature not working.
    """
    d = {}
    d['ctx'] = W.find_pos_chain(mod)
    d['dom'] = W.Dom(mod)
    d['cam'] = W.find_campos(mod, d['ctx']) if d['ctx'] else None
    d['ggx'] = find_ggx_d_sites(mod)
    d['mat'] = find_material_triples(mod)
    d['fd'] = find_diffuse_scalars(mod)
    d['writes'] = find_image_writes(mod)
    d['class_fetch'] = find_class_fetch(mod)
    try:
        d['cls'] = acquire_class_shift(mod, cfg)
    except SystemExit:
        d['cls'] = None
    try:
        d['cls_plain'] = acquire_class_shift(mod)
    except SystemExit:
        d['cls_plain'] = None
    d['sheen'] = {}
    for s in d['ggx']:
        f = SP.find_sheen_inputs(mod, s)
        if f:
            d['sheen'][s['line']] = f
            f['fold'] = _fold_cosine(mod, s, f)
    d['alphas'] = sorted({s['alpha'] for s in d['ggx']},
                         key=lambda a: mod.find_def(a)[0])
    return d


# ------------------------------------------------------------- the emitters
def _emit_campos(E, det, site_line):
    """C = cbv[...][member 0].xyz -- `99` sec 1's camera position.

    `wpos_core._emit_campos` verbatim, which reuses the module's OWN already-
    loaded components where they dominate and re-loads them where they do not.
    Reimplementing the load here would be a second, unverified copy of a chain
    `99` sec 6 already gated.
    """
    return W._emit_campos(E.mod, det['dom'], det['cam'], det['ctx'],
                          E.ins, E.U, site_line)


def _emit_fade(E, P, C, near, far):
    """1 inside `near` metres, 0 beyond `far`, linear between.

    `d = |P - C|` in METRES (`99` sec 10.8 measured the unit off a frame).
    The fade exists because a 12 mm lattice is 2.9 resolve pixels at 6 m and
    1.3 at 14 m: below one pixel the field cannot be resolved and becomes
    shimmer under the denoiser rather than texture.  `whash_model --fade`
    prints the table.
    """
    dd = [E.fsub(P[k], C[k]) for k in range(3)]
    s = E.fmul(dd[0], dd[0])
    for k in (1, 2):
        s = E.fadd(s, E.fmul(dd[k], dd[k]))
    dist = E.ext('Sqrt', '%float', s)
    u = E.fmul(E.fsub(dist, E.C(near)), E.C(1.0 / (far - near)))
    uc = E.ext('NClamp', '%float', u, E.C(0.0), E.C(1.0))
    return E.fsub(E.C(1.0), uc), dist


def _emit_class_gate(E, shift):
    """class not in {1, 4, 8}."""
    g = None
    for c in CLASS_EXCLUDE:
        t = E.op('OpINotEqual', '%bool', shift, E.U(c))
        g = t if g is None else E.op('OpLogicalAnd', '%bool', g, t)
    return g


def _emit_gate_m(E, shift, metallic, metal_max):
    """The rough-dielectric proxy minus its roughness clause -- everything in
    it that is ONE value per pixel, so it is hoisted once per module."""
    g = _emit_class_gate(E, shift)
    diel = E.op('OpFOrdLessThan', '%bool', metallic, E.C(metal_max))
    return E.op('OpLogicalAnd', '%bool', g, diel)


def build_hoist(mod, cfg, det, K, consts, uc):
    """The once-per-module world-space block.  Returns (line, ins, dict)."""
    ctx, cam = det['ctx'], det['cam']
    shift, cls_line, pre_ins, pre_consts, dom_id = det['cls']
    consts.extend(pre_consts)
    leaves = W.pos_leaves(ctx)
    met = det['mat'][0]['met'] if det['mat'] else None
    if met is None:
        die(f"{mod.name}: no F0 = lerp(0.04, albedo, metallic) triple")
    anchors = [mod.find_def(x)[0] for x in leaves + [met]]
    if any(x is None for x in anchors):
        die(f"{mod.name}: a hoist anchor has no definition line")
    dline = mod.find_def(dom_id)[0]
    HL = max(anchors + ([cls_line] if pre_ins else []) +
             ([dline] if dline is not None else []))
    if _opcode(mod.lines[HL]) in TERMINATORS:
        die(f"{mod.name}: hoist line {HL + 1} is a {_opcode(mod.lines[HL])} -- "
            f"inserting after it would leave the block")
    for x in leaves + [met] + ([dom_id] if dline is not None else []):
        xl = mod.find_def(x)[0]
        if xl is not None and xl > HL:
            die(f"{mod.name}: hoist anchor {x} is below the hoist line")
        if xl is not None and xl < HL and not dom_line(cfg, xl, HL):
            die(f"{mod.name}: hoist anchor {x} does not dominate the hoist")
    ins = list(pre_ins)
    E = H.Emit(mod, ins, consts, uc=uc)
    Pw = W.emit_world_pos(mod, det['dom'], ctx, HL, ins, uc=uc)
    C = _emit_campos(E, det, HL)
    fade, dist = _emit_fade(E, Pw, C, K['fade_near'], K['fade_far'])
    gate_m = _emit_gate_m(E, shift, met, K['gate_metal'])
    out = dict(line=HL, gate_m=gate_m, fade=fade, dist=dist, P=Pw,
               shift=shift, metallic=met, E=E, dr=None, da=None, amp=None)
    need_noise = K['k_rough'] > 0 or K['k_alb'] > 0 or K['k_porous'] > 0
    if need_noise:
        f = H.emit_fbm(E, Pw, K['cell'], K['seed'], octaves=K['octaves'],
                       lacunarity=K['lacunarity'], gain=K['gain'])
        out['fbm'] = f
        if K['k_rough'] > 0:
            # dr = (2f - 1) * k_rough * fade
            out['dr'] = E.fmul(E.fmul(H.signed(E, f[0]), E.C(K['k_rough'])), fade)
        if K['k_alb'] > 0:
            # da = 1 + (2f - 1) * k_alb * fade
            out['da'] = E.fadd(E.C(1.0),
                               E.fmul(E.fmul(H.signed(E, f[1]),
                                             E.C(K['k_alb'])), fade))
        if K['k_porous'] > 0:
            # amp = k_porous * (1 + (f - 0.5) * fade):  the MODULATION fades
            # with distance, the lobe itself does not.  Beyond fade_far the
            # amplitude is exactly k_porous, i.e. the unmodulated lobe -- so
            # the 12 mm porosity field cannot alias at range while the chalky
            # rim itself stays.
            pm = E.fsub(f[2], E.C(0.5))
            out['amp'] = E.fmul(E.fadd(E.C(1.0), E.fmul(pm, fade)),
                                E.C(K['k_porous']))
    return out, ins


def build_micro_rough(mod, cfg, det, K, hoist, consts, uc, rep):
    """B, roughness: alpha' = (sqrt(alpha) + dr)^2 on gate-true pixels."""
    edits = []
    a_min = K['gate_rough'] ** 2
    for alpha in det['alphas']:
        aline = mod.find_def(alpha)[0]
        if not dom_line(cfg, hoist['line'], aline):
            rep['skipped_rough'].append({'alpha': alpha, 'line': aline + 1,
                                         'why': 'hoist does not dominate'})
            continue
        ins = []
        E = H.Emit(mod, ins, consts, uc=uc)
        rough_ok = E.op('OpFOrdGreaterThan', '%bool', alpha, E.C(a_min))
        gate = E.op('OpLogicalAnd', '%bool', hoist['gate_m'], rough_ok)
        r = E.ext('Sqrt', '%float', alpha)
        r2 = E.fadd(r, hoist['dr'])
        rc = E.ext('NClamp', '%float', r2, E.C(K['rough_floor']), E.C(1.0))
        an = E.fmul(rc, rc)
        sel = E.op('OpSelect', '%float', gate, an, alpha)
        n = replace_all_uses(mod, alpha, sel, aline)
        if not n:
            die(f"{mod.name}: alpha {alpha} has no uses below its definition")
        edits.append((aline, ins))
        rep['rough_sites'].append({'alpha': alpha, 'line': aline + 1,
                                   'uses': n})
    return edits


def build_micro_albedo(mod, cfg, det, K, hoist, consts, uc, rep):
    """B, albedo: f_d *= da on gate-true pixels.  81 sec 3's 173 sites."""
    edits = []
    a_min = K['gate_rough'] ** 2
    seen = set()
    for d in det['fd']:
        if d['fd'] in seen:
            rep['skipped_alb'].append({'line': d['line'] + 1, 'why': 'duplicate f_d'})
            continue
        seen.add(d['fd'])
        if not (dom_line(cfg, hoist['line'], d['line'])
                and cfg.dominates_line(d['rough'], d['line'])):
            rep['skipped_alb'].append({'line': d['line'] + 1,
                                       'why': 'hoist or roughness does not dominate'})
            continue
        ins = []
        E = H.Emit(mod, ins, consts, uc=uc)
        al = E.fmul(d['rough'], d['rough'])
        rough_ok = E.op('OpFOrdGreaterThan', '%bool', al, E.C(a_min))
        gate = E.op('OpLogicalAnd', '%bool', hoist['gate_m'], rough_ok)
        fac = E.op('OpSelect', '%float', gate, hoist['da'], E.C(1.0))
        nfd = E.fmul(d['fd'], fac)
        n = replace_all_uses(mod, d['fd'], nfd, d['line'])
        if not n:
            die(f"{mod.name}: f_d {d['fd']} has no uses below its definition")
        edits.append((d['line'], ins))
        rep['alb_sites'].append({'line': d['line'] + 1, 'uses': n})
    return edits


def build_porous(mod, cfg, det, K, hoist, consts, uc, rep):
    """C: a broad Charlie x Neubelt lobe ADDED at 81's sheen splice.

    The lobe, the defres weight, the cosine saturation and the cosine fold are
    all 81's emitters, imported unchanged -- so the arithmetic composing onto
    the shipped cloth sheen is provably the same arithmetic, and the only new
    things here are the amplitude (fbm porosity) and the two extra gate
    clauses.
    """
    edits = []
    a_min = K['gate_rough_c'] ** 2
    gl = mod.glsl
    if gl is None:
        die(f"{mod.name}: no GLSL.std.450 set")
    shift, cls_line, pre_ins, pre_consts, dom_id = det['cls']
    seen = set()
    for s in det['ggx']:
        f = det['sheen'].get(s['line'])
        if f is None:
            rep['skipped_porous'].append({'line': s['line'] + 1,
                                          'why': 'not sheen-shaped'})
            continue
        line = f['spec_line']
        if f['spec'] in seen:
            rep['skipped_porous'].append({'line': line + 1, 'why': 'duplicate spec'})
            continue
        mat = None
        for t in det['mat']:
            if (all(cfg.dominates_line(x, line) for x in t['alb'])
                    and cfg.dominates_line(t['met'], line)):
                mat = t
        bad = [x for x in (f['noh'], f['nol'], f['nov'], s['alpha'], dom_id)
               if not cfg.dominates_line(x, line)]
        if mat is None or bad or not dom_line(cfg, hoist['line'], line):
            rep['skipped_porous'].append(
                {'line': line + 1,
                 'why': ('no dominating albedo triple' if mat is None
                         else ('hoist does not dominate' if not bad
                               else 'inputs do not dominate: %s' % bad))})
            continue
        seen.add(f['spec'])
        ins = []
        E = H.Emit(mod, ins, consts, uc=uc)
        zero, one = E.C(0.0), E.C(1.0)
        KP = dict(one=one, eps=E.C(1e-6), four=E.C(4.0), den_min=E.C(1e-4),
                  inv2a=E.C(1.0 / (2.0 * K['a_porous'])),
                  pre=E.C((2.0 + 1.0 / K['a_porous']) / (2.0 * math.pi)),
                  cap=E.C(K['porous_cap']), zero=zero)
        c0, c1, nc = _saturate_cosines(mod, gl, ins, one, zero, f)
        rep['porous_clamped'] += nc
        fold = f['fold']
        if fold is not None:
            fold = c0 if fold == f['nol'] else c1
            rep['porous_folded'] += 1
        else:
            fold = E.ext('NMin', '%float', c0, c1)
            rep['porous_folded_min'] += 1
        lobe = _emit_fuzz_lobe(mod, gl, ins, f['noh'], c0, c1, KP)
        beta = K['porous_defres']
        beta_id = E.C(beta) if beta not in (0.0, 1.0) else None
        w = (_emit_defres(mod, gl, ins, f['noh'], c0, c1, KP, zero, beta_id)
             if beta > 0.0 else None)
        # saturation of the raw albedo, and the narrower roughness clause
        mx = E.ext('NMax', '%float', mat['alb'][0], mat['alb'][1])
        mx = E.ext('NMax', '%float', mx, mat['alb'][2])
        mn = E.ext('NMin', '%float', mat['alb'][0], mat['alb'][1])
        mn = E.ext('NMin', '%float', mn, mat['alb'][2])
        sat = E.fsub(mx, mn)
        low_sat = E.op('OpFOrdLessThan', '%bool', sat, E.C(K['gate_sat']))
        rough_ok = E.op('OpFOrdGreaterThan', '%bool', s['alpha'], E.C(a_min))
        g = E.op('OpLogicalAnd', '%bool', hoist['gate_m'], rough_ok)
        gate = E.op('OpLogicalAnd', '%bool', g, low_sat)
        cur = E.fmul(lobe, hoist['amp'])
        if w is not None:
            cur = E.fmul(cur, w)
        cur = E.fmul(cur, fold)
        sel = E.op('OpSelect', '%float', gate, cur, zero)
        new = E.fadd(f['spec'], sel)
        n = replace_all_uses(mod, f['spec'], new, line)
        if not n:
            die(f"{mod.name}: spec {f['spec']} has no uses below its definition")
        edits.append((line, ins))
        rep['porous_sites'].append({'line': line + 1, 'uses': n})
    return edits


def build_cell_paint(mod, cfg, det, K, consts, uc, rep):
    """micro-cell: a flat per-12 mm-cell hue on the radiance writes.

    Gate: `class not in {1, 4, 8}` ONLY.  The metallic clause is deliberately
    absent: it dominates 120 of the 150 radiance writes and is not refetchable
    at the other 30 (it is a decoded G-buffer value, not a module-entry one),
    and a diagnostic whose gate varies between writes is worth less to a crawl
    test than one that is uniform everywhere.  Stated in handoff/107 sec 5.

    The paint is a MULTIPLY on the texel (94's hunt-paint shape), attenuated
    toward 1.0 by the SAME distance fade the feature uses -- so the frame also
    reads back whether the fade lands where the model says it does.
    """
    edits = []
    ctx, cam = det['ctx'], det['cam']
    shift, cls_line, pre_ins, pre_consts, dom_id = det['cls_plain']
    consts.extend(pre_consts)
    if pre_ins:
        edits.append((cls_line, pre_ins))
    cf = det['class_fetch']
    leaves = W.pos_leaves(ctx)
    for wsite in det['writes']:
        line = wsite['line']
        if wsite['comps'] is None:
            rep['skipped_paint'].append({'line': line + 1,
                                         'why': 'texel is not a v4float construct'})
            continue
        if any(not cfg.dominates_line(x, line) for x in leaves):
            rep['skipped_paint'].append({'line': line + 1,
                                         'why': 'position refetch inputs do not dominate'})
            continue
        ins = []
        E = H.Emit(mod, ins, consts, uc=uc)
        cls = shift
        if not cfg.dominates_line(dom_id, line):
            if cf is None or any(not cfg.dominates_line(x, line)
                                 for x in class_fetch_inputs(cf)):
                rep['skipped_paint'].append({'line': line + 1,
                                             'why': 'class refetch inputs do not dominate'})
                continue
            cls = emit_class_value(mod, cf, ins)
            rep['paint_class_refetch'] += 1
        p_top = all(det['dom'].dominates_line(i, line) for i in ctx['p'])
        Pw = W.emit_world_pos(mod, det['dom'], ctx, line, ins, uc=uc)
        if not p_top:
            rep['paint_pos_refetch'] += 1
        C = _emit_campos(E, det, line)
        fade, _dist = _emit_fade(E, Pw, C, K['fade_near'], K['fade_far'])
        u = H.emit_world_hash(E, Pw, K['cell'], K['seed'])
        gate = _emit_class_gate(E, cls)
        one = E.C(1.0)
        lo, span = E.C(K['paint_lo']), E.C(K['paint_hi'] - K['paint_lo'])
        newc = []
        for ch in range(3):
            tint = E.fadd(E.fmul(u[ch], span), lo)
            faded = E.fadd(E.fmul(E.fsub(tint, one), fade), one)
            sel = E.op('OpSelect', '%float', gate, faded, one)
            newc.append(E.fmul(wsite['comps'][ch], sel))
        nt = E.op('OpCompositeConstruct', '%v4float', newc[0], newc[1],
                  newc[2], wsite['comps'][3])
        edits.append((line - 1, ins))
        mod.lines[line] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                 r'\g<1>' + nt, mod.lines[line])
        rep['paint_sites'].append(line + 1)
    return edits


# ------------------------------------------------------------------ driver
def build(mod, cfg, K):
    consts, edits, uc = [], [], {}
    uc['decls'] = consts
    rep = {'knobs': {k: K[k] for k in sorted(K)},
           'rough_sites': [], 'alb_sites': [], 'porous_sites': [],
           'paint_sites': [], 'skipped_rough': [], 'skipped_alb': [],
           'skipped_porous': [], 'skipped_paint': [],
           'porous_clamped': 0, 'porous_folded': 0, 'porous_folded_min': 0,
           'paint_pos_refetch': 0, 'paint_class_refetch': 0}
    det = _detect(mod, cfg)
    if det['ctx'] is None:
        die(f"{mod.name}: no P = M.(x,y,depth,1)/w reconstruction "
            f"(handoff/99 sec 1; declined by name)")
    if det['cam'] is None:
        die(f"{mod.name}: no camera position (C - P) triple")
    if det['cls'] is None or det['cls_plain'] is None:
        die(f"{mod.name}: no material-class anchor")
    rep['census'] = {'ggx_d': len(det['ggx']), 'alphas': len(det['alphas']),
                     'sheen': len(det['sheen']), 'fd': len(det['fd']),
                     'writes': len(det['writes']),
                     'mat_triples': len(det['mat'])}
    if K['paint'] == 'cell':
        edits += build_cell_paint(mod, cfg, det, K, consts, uc, rep)
        if not rep['paint_sites']:
            die(f"{mod.name}: no radiance write reachable for the cell paint")
        return consts, edits, rep
    hoist, hins = build_hoist(mod, cfg, det, K, consts, uc)
    rep['hoist_line'] = hoist['line'] + 1
    rep['hoist_instructions'] = len(hins)
    if K['k_rough'] > 0:
        edits += build_micro_rough(mod, cfg, det, K, hoist, consts, uc, rep)
    if K['k_alb'] > 0:
        edits += build_micro_albedo(mod, cfg, det, K, hoist, consts, uc, rep)
    if K['k_porous'] > 0:
        edits += build_porous(mod, cfg, det, K, hoist, consts, uc, rep)
    edits.append((hoist['line'], hins))
    touched = (len(rep['rough_sites']) + len(rep['alb_sites'])
               + len(rep['porous_sites']))
    if touched == 0:
        die(f"{mod.name}: the hoist was emitted and NOTHING consumes it -- "
            f"a module whose bytes differ only by dead constants is the "
            f"46 sec 12 / 27 sec 8.3 failure, not coverage")
    return consts, edits, rep


def process(path, outdir, K, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    active = (K['k_rough'] > 0 or K['k_alb'] > 0 or K['k_porous'] > 0
              or K['paint'] != 'none')
    if not active:
        # THE CONTROL.  Nothing detected, nothing emitted, nothing rewritten:
        # the module is re-assembled from the untouched disassembly, which
        # build_whash.sh proves is byte-neutral on all 77 base modules FIRST.
        rep['whash'] = {'control': True, 'rough_sites': [], 'alb_sites': [],
                        'porous_sites': [], 'paint_sites': []}
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    consts, edits, rep['whash'] = build(mod, cfg, K)
    apply_edits(mod, consts, edits)
    return CS._emit(mod, outdir, target_env, rep)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--micro-rough', type=float, default=0.0,
                    help='B: roughness swing, +-K (0 = off)')
    ap.add_argument('--micro-alb', type=float, default=0.0,
                    help='B: diffuse-reflectance swing, +-K (0 = off)')
    ap.add_argument('--porous', type=float, default=0.0,
                    help='C: porous sheen amplitude (0 = off)')
    ap.add_argument('--paint', choices=('none', 'cell'), default='none',
                    help="'cell' = the micro-cell crawl diagnostic; it carries "
                         "no perturbation")
    for k in ('cell', 'octaves', 'lacunarity', 'gain', 'fade_near', 'fade_far',
              'gate_metal', 'gate_rough', 'gate_rough_c', 'gate_sat',
              'rough_floor', 'a_porous', 'porous_cap', 'porous_defres',
              'paint_lo', 'paint_hi'):
        ap.add_argument('--' + k.replace('_', '-'),
                        type=(int if k == 'octaves' else float),
                        default=DEFAULTS[k])
    ap.add_argument('--seed', type=lambda s: int(s, 0), default=DEFAULTS['seed'])
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    K = {k: getattr(a, k) for k in DEFAULTS}
    K.update(k_rough=a.micro_rough, k_alb=a.micro_alb, k_porous=a.porous,
             paint=a.paint)
    if K['cell'] <= 0:
        die('--cell must be > 0')
    if K['octaves'] < 1:
        die('--octaves must be >= 1')
    if K['fade_far'] <= K['fade_near']:
        die('--fade-far must exceed --fade-near')
    if not 0.0 <= K['porous_defres'] <= 1.0:
        die('--porous-defres must be in [0, 1]')
    if K['paint'] != 'none' and (K['k_rough'] or K['k_alb'] or K['k_porous']):
        die('--paint cell is a diagnostic and must carry no perturbation')
    reps = [process(p, a.outdir, K, do_rt=not a.no_roundtrip_check)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
