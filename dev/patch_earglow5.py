#!/usr/bin/env python3
"""patch_earglow5.py <base.spvasm> --outdir DIR [--k K] [--cut M]
                     [--mode none|tint|rate] [--floor M] [--tint R,G,B]
                     [--no-cutoff] [--decoy D]

Ear glow v5 -- handoff/110. The user's verdict on the shipped ear glow
(`gi-50b-...-fog-earglow-cap6-glintdense`), verbatim:

  "It looks like a lightbulb behind ears. Needs to be like 3/4 less bright,
   moreso just colouring the effected location. Also needs to have a hard
   cutoff at a certain thickness. Getting some transmittance through the upper
   nose bridge which doesn't make sense. The nose bleed effect also carries
   light of a colour that's too yellow. Really shallow depth transmission
   should still be coloured more red."

THREE VARIABLES, and nothing else moves:

  (a) BRIGHTNESS.  The k constant, 0.22 -> 0.055 (one quarter).  Pure
      in-place rewrite of `OpConstant %float 0.219999999`.
  (b) HARD CUTOFF, or none at all (`--no-cutoff`, 110 sec 14's `-cutoff`
      rung: tmax stays at the shipped 18 mm and NO fade is emitted, so the
      transfer's own exponential decay is the only falloff and the question
      "is a hard cutoff wanted at all?" becomes answerable).  Otherwise:
      query B's tmax 0.018 -> t_cut.  Beyond t_cut the query
      MISSES, so `hitB` is false, so the accept is false, so the contribution
      is EXACTLY ZERO -- not small, zero.  That is a constant rewrite and it
      also makes every ray cheaper.  Because T(t_cut) is not zero, a bare
      tmax change would leave a visible edge, so THREE instructions are added:
          w = 1 - SmoothStep(t_cut - 1 mm, t_cut, t_guarded)
      folded into the k select's own result.  The fade reads the GUARDED t,
      not the FLOORED t -- see the note in build_fade() -- because at
      --cut 0.006 the floored t is the constant 0.006 and a fade on it would
      black the whole rung out.
  (c) COLOUR, offered as two rungs and not blended:
      (c1) --mode tint: a fixed per-channel tint on each channel's transfer,
           default (1.0, 0.40, 0.22), any triple via --tint.  THREE
           instructions whatever the strength.  110 sec 14 ships two:
           (1.0, 0.40, 0.22) as `earglow6` and (1.0, 0.55, 0.35) as
           `earglow6-mild`.
      (c2) --mode rate: ld_G 1.37 -> 0.70 mm and ld_B 0.68 -> 0.35 mm, i.e.
           four in-place rate rewrites and ZERO added instructions.

  (d) THE FLOOR, added after 110 sec 3.2 was read (`--floor`, 110 sec 13).
      The shipped default applies `NMax(t, 0.006)` BEFORE the transfer, so
      every ear thinner than 6 mm is already rendered as if it were exactly
      6 mm -- flat, no depth gradient at all, which is most of what "looks
      like a lightbulb" means.  `--floor` lowers that constant, and it is the
      ONLY variable between `earglow5` and `earglow5-floor3` / `-floor2`.

      IT IS NOT AN IN-PLACE REWRITE, AND IT CANNOT BE.  `%float_0_00600000005`
      is shared: in every reference permutation it is also the tmax of six
      of the module's own `OpTraceRayKHR`s and the right-hand side of six
      `OpFOrdLessThan`s -- twelve other consumers, uniformly, in all ten.  `rewrite_const()` refuses
      it, correctly.  `set_floor()` therefore declares a NEW constant and
      repoints ONLY the earglow's own NMax operand: zero added instructions,
      one added declaration, and not one other consumer moves.  The report
      records how many consumers were left alone; the verifier re-proves it
      from the shipped bytes (check 3).

WHAT IS NOT TOUCHED: the three ray queries, their flags, the +/-0.1% bracket,
the instance match, query C, the wrap smoothstep, the firefly clamp, the write
shape, and all 81 non-reference modules.  The floor is untouched unless
`--floor` is given, and `--floor` is the only variable in the -floor rungs.
"""
import argparse, hashlib, json, os, re, struct, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import detect_target_env
import patch_earglow as E
from patch_earglow_rq import _ensure_line
from patch_rayq import _add_header

# --- the shipped constants this rung rewrites, all read back structurally ---
K_OLD = 0.219999999
K_NEW = 0.055
CUT_DEFAULT = 0.008
FADE_W = 0.001                       # 1 mm of smoothstep below the cut
CAP6 = 0.006                         # 101 sec 18's floor -- moved ONLY by --floor
TMAX_OLD = 0.0179999992
FLAGS_B = 545                        # Opaque|CullFrontFacingTriangles|SkipAABBs
WIDE = 4.0                           # 101's second (wide) lobe, ld * 4
LD_OLD = (0.00367, 0.00137, 0.00068)
LD_NEW = (0.00367, 0.00070, 0.00035)  # (c2): green and blue shortened
TINT = (1.0, 0.40, 0.22)              # (c1), the 110 sec 4 strength
TINT_MILD = (1.0, 0.55, 0.35)         # (c1) at the 110 sec 14 mild strength
DECOYS = ('nofade', 'nocut', 'notint', 'flatk', 'invfade', 'tintswap',
          'fadefloored', 'floorshared')


def f32(v):
    return struct.unpack('<f', struct.pack('<f', float(v)))[0]


def flit(v):
    return repr(f32(v))


def _res(line):
    m = re.match(r'\s*(%\w+)\s*=\s*Op', line)
    return m.group(1) if m else None


def fval_of(mod, ident):
    _, body = mod.find_def(ident)
    m = re.match(r'OpConstant %\w+ ([-+0-9.eE]+)$', body or '')
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def close(a, b, rel=1e-5):
    return a is not None and abs(a - b) <= rel * max(1.0, abs(b))


def uses_of(mod, tok, fs, fe):
    """Every line that MENTIONS this id, declaration included. An in-place
    constant rewrite is only safe when the earglow sites are the whole set."""
    pat = re.compile(r'(?<![\w])' + re.escape(tok) + r'(?![\w])')
    return [i for i, l in enumerate(mod.lines) if pat.search(l)]


# --------------------------------------------------------------------------
def find_glow(mod, fs, fe):
    """Re-find `101` sec 16's glow block by SHAPE. No SSA id is ever assumed.

    query B (flags 545, unique)  ->  committed T  ->  the miss guard
      ->  NMax(., cap)  ->  three transfer chains, each
          Exp(-t*a1) + Exp(-t*a2) -> * 0.5 -> * (k select * wrap smoothstep)
    """
    d = {}
    for i in range(fs, fe):
        r = _res(mod.lines[i])
        if r:
            d.setdefault(r, (i, mod.lines[i].split('=', 1)[1].strip()))

    def body(t):
        return d.get(t, (0, ''))[1]

    # ---- query B -----------------------------------------------------------
    binit = []
    for i in range(fs, fe):
        m = re.match(r'\s*OpRayQueryInitializeKHR (%\w+) (%\w+) (%\w+) (%\w+) '
                     r'(%\w+) (%\w+) (%\w+) (%\w+)\s*$', mod.lines[i])
        if m and re.match(r'OpConstant %uint ' + str(FLAGS_B) + r'$',
                          body(m.group(3)) or ''):
            binit.append((i, list(m.groups())))
        elif m and m.group(3) == '%uint_' + str(FLAGS_B):
            binit.append((i, list(m.groups())))
    if len(binit) != 1:
        die(f"{mod.name}: {len(binit)} ray queries with flags {FLAGS_B}, want "
            f"exactly 1 -- this is not the earglow base (or thinglow is "
            f"stacked on it, which 110 explicitly does NOT build on)")
    bline, bops = binit[0]
    tmax_tok = bops[7]
    if not close(fval_of(mod, tmax_tok), TMAX_OLD, 1e-4):
        die(f"{mod.name}: query B tmax is {fval_of(mod, tmax_tok)}, want "
            f"{TMAX_OLD}")

    # ---- the committed T, its miss guard, and the cap6 floor --------------
    tq = [t for t in d if re.match(r'OpRayQueryGetIntersectionTKHR %float '
                                   + re.escape(bops[0]) + r' %uint_1$', body(t))]
    if len(tq) != 1:
        die(f"{mod.name}: {len(tq)} committed T getters on query B, want 1")
    guard = [t for t in d if re.match(r'OpSelect %float %\w+ '
                                      + re.escape(tq[0]) + r' '
                                      + re.escape(tmax_tok) + r'$', body(t))]
    if len(guard) != 1:
        die(f"{mod.name}: {len(guard)} NaN guards OpSelect(hitB, t, tmax), "
            f"want 1")
    tguard = guard[0]
    floor = [t for t in d if re.match(r'OpExtInst %float %\w+ NMax '
                                      + re.escape(tguard) + r' (%\w+)$', body(t))]
    if len(floor) != 1:
        die(f"{mod.name}: {len(floor)} thickness floors NMax(t, cap) on the "
            f"guarded t, want exactly 1 -- 110 refuses to build on a base "
            f"without 101 sec 18's floor")
    teff = floor[0]
    cap_tok = re.match(r'OpExtInst %float %\w+ NMax %\w+ (%\w+)$',
                       body(teff)).group(1)
    if not close(fval_of(mod, cap_tok), CAP6, 1e-4):
        die(f"{mod.name}: the floor is {fval_of(mod, cap_tok)} m, want {CAP6}")

    # ---- the k select and the shared weight k * wrap ----------------------
    ksel = [t for t in d if re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$',
                                     body(t))
            and close(fval_of(mod, re.match(r'OpSelect %float %\w+ (%\w+) ',
                                            body(t)).group(1)), K_OLD, 1e-4)]
    if len(ksel) != 1:
        die(f"{mod.name}: {len(ksel)} k selects at k={K_OLD}, want 1")
    ksel = ksel[0]
    k_tok = re.match(r'OpSelect %float %\w+ (%\w+) (%\w+)$', body(ksel)).group(1)
    wsel = [t for t in d if re.match(r'OpFMul %float (%\w+) (%\w+)$', body(t))
            and ksel in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                 body(t)).groups()]
    if len(wsel) != 1:
        die(f"{mod.name}: {len(wsel)} products of the k select, want 1 "
            f"(k * the wrap smoothstep)")
    w0 = wsel[0]
    other = [x for x in re.match(r'OpFMul %float (%\w+) (%\w+)$',
                                 body(w0)).groups() if x != ksel][0]
    if not re.match(r'OpExtInst %float %\w+ SmoothStep ', body(other)):
        die(f"{mod.name}: the k select is not multiplied by the wrap "
            f"smoothstep ({body(other)!r})")

    # ---- the three transfer chains ----------------------------------------
    chains = []
    for t in d:
        m = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(t))
        if not m or w0 not in m.groups():
            continue
        half = [x for x in m.groups() if x != w0]
        if not half:
            continue
        hm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(half[0]))
        if not hm:
            continue
        s = [x for x in hm.groups() if close(fval_of(mod, x), 0.5, 1e-6)]
        add = [x for x in hm.groups() if re.match(r'OpFAdd %float ', body(x))]
        if not s or not add:
            continue
        am = re.match(r'OpFAdd %float (%\w+) (%\w+)$', body(add[0]))
        rates = []
        for e in am.groups():
            em = re.match(r'OpExtInst %float %\w+ Exp (%\w+)$', body(e))
            if not em:
                break
            nm = re.match(r'OpFNegate %float (%\w+)$', body(em.group(1)))
            if not nm:
                break
            mm = re.match(r'OpFMul %float (%\w+) (%\w+)$', body(nm.group(1)))
            if not mm or teff not in mm.groups():
                break
            rates.append([x for x in mm.groups() if x != teff][0])
        if len(rates) != 2:
            continue
        chains.append({'mul_w': t, 'half': half[0], 'rates': rates,
                       'line': d[t][0]})
    if len(chains) != 3:
        die(f"{mod.name}: {len(chains)} transfer chains on the shared weight, "
            f"want exactly 3 (R, G, B)")
    chains.sort(key=lambda c: c['line'])
    # Cross-check the channel order against the RATES rather than trusting
    # line order: 101's ld is 3.67 / 1.37 / 0.68 mm, so the narrow-lobe rate
    # is strictly INCREASING R -> G -> B. A module whose chains were emitted
    # in another order would be caught here, not silently mis-tinted.
    narrow = []
    for c in chains:
        vs = sorted(fval_of(mod, r) or 0.0 for r in c['rates'])
        c['rate_wide'], c['rate_narrow'] = vs[0], vs[1]
        c['tok_wide'] = [r for r in c['rates']
                         if close(fval_of(mod, r), vs[0], 1e-4)][0]
        c['tok_narrow'] = [r for r in c['rates']
                           if close(fval_of(mod, r), vs[1], 1e-4)][0]
        narrow.append(c['rate_narrow'])
    if not (narrow[0] < narrow[1] < narrow[2]):
        die(f"{mod.name}: the three chains' narrow rates are {narrow}, not "
            f"increasing -- the R/G/B order cannot be established")
    for i, c in enumerate(chains):
        want = 1.0 / LD_OLD[i]
        if not close(c['rate_narrow'], want, 1e-3):
            die(f"{mod.name}: chain {i} narrow rate {c['rate_narrow']}, want "
                f"1/{LD_OLD[i]} = {want}")
        if not close(c['rate_wide'], want / WIDE, 1e-3):
            die(f"{mod.name}: chain {i} wide rate {c['rate_wide']}, want "
                f"1/({WIDE}*{LD_OLD[i]})")
    return dict(b_line=bline, b_ops=bops, tmax=tmax_tok, tguard=tguard,
                teff=teff, cap=cap_tok, ksel=ksel, k_tok=k_tok, w0=w0,
                wrap=other, chains=chains, index=d)


def _fc(mod, consts, v):
    """Resolve a float constant BY VALUE against the module's CURRENT lines
    plus the pending declarations -- never via `Module.fconst`.

    That cache is built at load time and maps 0.22 -> `%float_0_219999999`.
    This file REWRITES that constant in place to 0.055, so a later
    `mod.const(0.22)` (the blue tint of (c1) is 0.22) would hand back an id
    that now holds the brightness, silently tinting blue at k instead of at
    0.22.  It did, in the first build of this file; this function is the fix
    and `--decoy tintswap` is not the only thing verify_earglow5.py check 6
    catches because of it."""
    want = f32(v)
    if want == 0.0:
        die("_fc: refusing a zero -- +0.0 and -0.0 are not interchangeable "
            "in this splice")
    pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %float ([-+0-9.eE]+)\s*$')
    for l in list(mod.lines) + list(consts):
        m = pat.match(l)
        if not m:
            continue
        try:
            if f32(float(m.group(2))) == want:
                return m.group(1)
        except ValueError:
            continue
    n = mod.new_id()
    consts.append(f"    {n} = OpConstant %float {flit(v)}")
    return n


# --------------------------------------------------------------------------
def rewrite_const(mod, tok, new, fs, fe, rep, label, sites):
    """Rewrite a constant IN PLACE, but only after proving that the earglow
    sites are its ONLY consumers. If anything else in the module reads it, the
    rewrite would silently change unrelated shading, so this refuses instead."""
    u = uses_of(mod, tok, fs, fe)
    decl = [i for i in u if re.match(r'\s*' + re.escape(tok) + r'\s*=\s*OpConstant',
                                     mod.lines[i])]
    if len(decl) != 1:
        die(f"{mod.name}: {label}: {len(decl)} declarations of {tok}")
    consumers = [i for i in u if i not in decl]
    if sorted(consumers) != sorted(sites):
        die(f"{mod.name}: {label}: {tok} is read at lines "
            f"{[i+1 for i in consumers]} but the earglow sites are "
            f"{[i+1 for i in sites]} -- refusing an in-place rewrite that "
            f"would change unrelated shading")
    old = fval_of(mod, tok)
    mod.lines[decl[0]] = re.sub(r'OpConstant %float [-+0-9.eE]+\s*$',
                                'OpConstant %float ' + flit(new),
                                mod.lines[decl[0]])
    rep.setdefault('rewrites', []).append(
        {'what': label, 'id': tok, 'from': old, 'to': f32(new),
         'consumers': len(consumers), 'in_place': True})


def set_floor(mod, g, new, fs, fe, rep, consts, decoy=None):
    """(d) 101 sec 18's `NMax(t, 0.006)`, lowered.

    Deliberately NOT via rewrite_const(): the 0.006 constant is shared with
    the module's own OpTraceRayKHR tmaxes and OpFOrdLessThan tests, so an
    in-place rewrite would change unrelated shading and rewrite_const() would
    (rightly) refuse.  A new constant is declared instead and ONLY the
    earglow's own NMax operand is repointed.  Cost: 0 instructions, 1
    declaration.  Everything else that reads 0.006 keeps reading 0.006, and
    the count of those survivors goes into the report as evidence."""
    d = g['index']
    old = g['cap']
    site = d[g['teff']][0]
    others = [i for i in uses_of(mod, old, fs, fe)
              if i != site
              and not re.match(r'\s*' + re.escape(old) + r'\s*=\s*OpConstant',
                               mod.lines[i])]
    if not others:
        die(f"{mod.name}: the {CAP6} constant has no consumer but the earglow "
            f"floor -- this is not the shipped base")
    if decoy == 'floorshared':
        # THE OBVIOUS, WRONG WAY. Rewrite the shared 0.006 in place, which
        # also moves six OpTraceRayKHR tmaxes and six OpFOrdLessThan tests
        # in the module's own shading. rewrite_const() refuses this; the decoy
        # goes around it so verify_earglow5.py check 3 is proven to catch it.
        decl = [i for i in uses_of(mod, old, fs, fe)
                if re.match(r'\s*' + re.escape(old) + r'\s*=\s*OpConstant',
                            mod.lines[i])]
        mod.lines[decl[0]] = re.sub(r'OpConstant %float [-+0-9.eE]+\s*$',
                                    'OpConstant %float ' + flit(new),
                                    mod.lines[decl[0]])
        rep['floor_repoint'] = {'from': CAP6, 'to': f32(new), 'id_old': old,
                                'id_new': old, 'other_consumers_left_alone': 0,
                                'in_place': True, 'instructions': 0,
                                'declarations': 0}
        return
    nt = _fc(mod, consts, new)
    before = mod.lines[site]
    mod.lines[site] = re.sub(r'NMax (%\w+) ' + re.escape(old) + r'\s*$',
                             r'NMax \1 ' + nt, before)
    if mod.lines[site] == before:
        die(f"{mod.name}: could not repoint the floor NMax ({before.strip()!r})")
    # the repoint must not have disturbed anything else that reads 0.006
    still = [i for i in uses_of(mod, old, fs, fe)
             if not re.match(r'\s*' + re.escape(old) + r'\s*=\s*OpConstant',
                             mod.lines[i])]
    if sorted(still) != sorted(others):
        die(f"{mod.name}: the floor repoint changed {len(others)} -> "
            f"{len(still)} other consumers of {CAP6}")
    rep['floor_repoint'] = {'from': CAP6, 'to': f32(new), 'id_old': old,
                            'id_new': nt, 'other_consumers_left_alone':
                            len(others), 'in_place': False, 'instructions': 0,
                            'declarations': 1}


def build(mod, k, cut, mode, decoy, fs, fe, floor=CAP6, tint_in=TINT,
          cutoff=True):
    g = find_glow(mod, fs, fe)
    d = g['index']
    consts, edits = [], []
    rep = {'mode': mode, 'k': f32(k), 'cut_m': f32(cut), 'fade_w': FADE_W,
           'decoy': decoy, 'cap6_floor': fval_of(mod, g['cap']),
           'floor_m': f32(floor),
           'floor_source': 'untouched (101 sec 18)',
           'ld_old_m': list(LD_OLD), 'wide': WIDE,
           'query_touched': 'tmax constant only' if cutoff else 'nothing',
           'cutoff': bool(cutoff),
           'flags_b': FLAGS_B}

    # ---- (a) brightness ---------------------------------------------------
    if decoy != 'flatk':
        rewrite_const(mod, g['k_tok'], k, fs, fe, rep, 'k (brightness)',
                      [d[g['ksel']][0]])
    rep['k_applied'] = decoy != 'flatk'

    # ---- (d) the floor, 110 sec 13 ---------------------------------------
    if not close(floor, CAP6, 1e-6):
        set_floor(mod, g, floor, fs, fe, rep, consts, decoy)
        rep['cap6_floor'] = f32(floor)
        rep['floor_source'] = 'repointed (new constant, 0 instructions)'

    # ---- (b) the hard cutoff ---------------------------------------------
    # tmax IS the cutoff: beyond it query B misses, hitB is false, the accept
    # is false and the k select yields -0.0. Exactly zero, not small.
    if decoy != 'nocut' and cutoff:
        rewrite_const(mod, g['tmax'], cut, fs, fe, rep, 'query B tmax (cutoff)',
                      [g['b_line'], d[g['tguard']][0]])
    rep['cut_applied'] = decoy != 'nocut' and cutoff

    if decoy != 'nofade' and cutoff:
        # THE FADE READS THE GUARDED t, NOT THE FLOORED t.  `teff` is
        # NMax(t, 6 mm), so at --cut 0.006 it is the CONSTANT 0.006 and a
        # smoothstep over [5 mm, 6 mm] on it would evaluate to 1 for every
        # pixel -- w = 0 -- and black the entire rung out.  `--decoy
        # fadefloored` builds exactly that mistake so the verifier is proven
        # to catch it.
        src = g['teff'] if decoy == 'fadefloored' else g['tguard']
        glsl = E._glsl_set(mod)
        flo = _fc(mod, consts, cut - FADE_W)
        fhi = _fc(mod, consts, cut)
        fone = _ensure_line(mod, consts,
                            r'\s*(%\w+)\s*=\s*OpConstant %float 1\s*$',
                            lambda n: f"    {n} = OpConstant %float 1")
        ind = re.match(r'(\s*)', mod.lines[d[g['ksel']][0]]).group(1)
        ins = []
        s = mod.new_id()
        ins.append(f"{ind}{s} = OpExtInst %float {glsl} SmoothStep {flo} {fhi} {src}")
        if decoy == 'invfade':
            w = s                       # glows ONLY beyond the cut
        else:
            w = mod.new_id()
            ins.append(f"{ind}{w} = OpFSub %float {fone} {s}")
        kw = mod.new_id()
        ins.append(f"{ind}{kw} = OpFMul %float {g['ksel']} {w}")
        edits.append((d[g['ksel']][0], ins))
        wl = d[g['w0']][0]
        mod.lines[wl] = re.sub(r'(?<![\w])' + re.escape(g['ksel']) + r'(?![\w])',
                               kw, mod.lines[wl])
        rep['fade'] = {'edges_m': [f32(cut - FADE_W), f32(cut)],
                       'on': 'floored t' if decoy == 'fadefloored'
                             else 'guarded t',
                       'inverted': decoy == 'invfade', 'instructions': len(ins)}
    else:
        rep['fade'] = None

    # ---- (c) colour -------------------------------------------------------
    if mode == 'tint':
        tint = list(tint_in)
        if decoy == 'notint':
            tint = [1.0, 1.0, 1.0]
        elif decoy == 'tintswap':
            tint = [tint_in[2], tint_in[1], tint_in[0]]
        rep['tint'] = [f32(x) for x in tint]
        for c, ch in enumerate(g['chains']):
            ft = _fc(mod, consts, tint[c]) if tint[c] != 1.0 else None
            if ft is None:
                ft = _ensure_line(mod, consts,
                                  r'\s*(%\w+)\s*=\s*OpConstant %float 1\s*$',
                                  lambda n: f"    {n} = OpConstant %float 1")
            ind = re.match(r'(\s*)', mod.lines[d[ch['half']][0]]).group(1)
            t = mod.new_id()
            edits.append((d[ch['half']][0],
                          [f"{ind}{t} = OpFMul %float {ch['half']} {ft}"]))
            ml = d[ch['mul_w']][0]
            mod.lines[ml] = re.sub(
                r'(?<![\w])' + re.escape(ch['half']) + r'(?![\w])', t,
                mod.lines[ml])
        rep['ld_new_m'] = list(LD_OLD)
    elif mode == 'rate':
        rep['tint'] = None
        rep['ld_new_m'] = list(LD_NEW)
        for c, ch in enumerate(g['chains']):
            if LD_NEW[c] == LD_OLD[c]:
                continue
            rewrite_const(mod, ch['tok_narrow'], 1.0 / LD_NEW[c], fs, fe, rep,
                          f'1/ld chan {c} (narrow lobe)',
                          [d[x][0] for x in d
                           if re.match(r'OpFMul %float ', d[x][1] or '')
                           and ch['tok_narrow'] in (d[x][1] or '').split()])
            rewrite_const(mod, ch['tok_wide'], 1.0 / (WIDE * LD_NEW[c]), fs, fe,
                          rep, f'1/({WIDE}ld) chan {c} (wide lobe)',
                          [d[x][0] for x in d
                           if re.match(r'OpFMul %float ', d[x][1] or '')
                           and ch['tok_wide'] in (d[x][1] or '').split()])
    else:
        rep['tint'] = None
        rep['ld_new_m'] = list(LD_OLD)

    rep['added_instructions'] = sum(len(e[1]) for e in edits)
    rep['new_constants'] = len(consts)
    return consts, edits, rep




def process(path, outdir, k, cut, mode, decoy, do_rt=True, floor=CAP6,
            tint=TINT, cutoff=True):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    if mode == 'none' and close(k, K_OLD, 1e-6) and close(cut, TMAX_OLD, 1e-6) \
            and close(floor, CAP6, 1e-9) and decoy is None:
        # THE CONTROL. Nothing is emitted, so the bytes ARE the base's.
        find_glow(mod, fs, fe)          # still assert the base is the right one
        rep['earglow5'] = {'mode': 'control', 'emitted': 0,
                           'why': 'k, cut, floor and colour all unchanged'}
    else:
        consts, edits, rep['earglow5'] = build(mod, k, cut, mode, decoy,
                                              fs, fe, floor, tint, cutoff)
        apply_edits(mod, consts, edits)
        _add_header(mod)

    os.makedirs(outdir, exist_ok=True)
    asm_out = os.path.join(outdir, mod.ident + '.spvasm')
    spv_out = os.path.join(outdir, mod.ident + '.spv')
    open(asm_out, 'w').write('\n'.join(mod.lines) + '\n')
    r = subprocess.run(['spirv-as', '--target-env', target_env, asm_out,
                        '-o', spv_out], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on PATCHED {mod.name}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', spv_out],
                       capture_output=True, text=True)
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--k', type=float, default=K_NEW)
    ap.add_argument('--cut', type=float, default=CUT_DEFAULT,
                    help='hard cutoff in METRES; becomes query B tmax')
    ap.add_argument('--mode', default='tint', choices=('none', 'tint', 'rate'))
    ap.add_argument('--floor', type=float, default=CAP6,
                    help='101 sec 18 thickness floor in METRES (default '
                         '0.006 = untouched). Lowering it is a repoint of the '
                         'earglow NMax operand onto a NEW constant, never an '
                         'in-place rewrite of the shared 0.006.')
    ap.add_argument('--no-cutoff', action='store_true',
                    help="emit NO hard cutoff: query B's tmax stays at the "
                         "shipped 18 mm and no fade is added, so the "
                         "transfer's own decay is the only falloff "
                         "(110 sec 14's earglow6-cutoff rung)")
    ap.add_argument('--tint', default=None,
                    help='(c1) per-channel tint as R,G,B (default '
                         '1.0,0.40,0.22). Only read in --mode tint.')
    ap.add_argument('--decoy', choices=DECOYS, default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_earglow5.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    tint = TINT
    if a.tint:
        parts = [float(x) for x in a.tint.split(',')]
        if len(parts) != 3:
            die(f"--tint wants three comma-separated numbers, got {a.tint!r}")
        tint = tuple(parts)
    cut = TMAX_OLD if a.no_cutoff else a.cut
    print(json.dumps(process(a.spvasm, a.outdir, a.k, cut, a.mode, a.decoy,
                             do_rt=not a.no_roundtrip_check, floor=a.floor,
                             tint=tint, cutoff=not a.no_cutoff)))


if __name__ == '__main__':
    main()
