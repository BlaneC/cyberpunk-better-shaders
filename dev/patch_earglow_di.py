#!/usr/bin/env python3
"""earglow-di -- ear glow (skin translucency) from LOCAL lights, in the 77
compute direct-light resolvers. handoff/112.

WHY (read handoff/111 sec 13 and handoff/94 sec 2.1 first).

The shipped ear glow (`101`/`111`) lives in rgs_reference_main and is SUN-ONLY:
query C tests visibility of the exit point to the sun, so the term is EXACTLY
zero in shade, overcast, interiors and neon. `111` sec 13 called bounce/local
light "the bigger win" and its route (a) assumed the raygen payload carried
radiance -- it does not (`59`-`61`: basecolor+metallic, oct normal+roughness,
a scalar, t). Local direct light is not shaded in the raygen at all: it is the
clustered light loop of the 77 compute resolvers (`94` sec 2.1). So that is
where the term goes.

THE SPLICE, per light, per pixel, inside the light loop of a resolver:

    site       the engine's `vis * atten > 0` branch. A BACKLIT ear has
               vis = 0 (the shadow test says the light is behind the
               surface) so the engine never enters the lit block. The
               splice sits in the block BEFORE that branch, where the
               light record (pos, dir, colour, flags), the attenuation
               phi and `lightPos - P` are all defined and dominate.
    L          normalize(select(directional, -dir, lightPos - P))  -- built
               here from the record, not taken from the engine's own select
               (the unshadowed-light loops branch on the flag instead).
    query A    98's primary-surface query, from the CAMERA (the TLAS origin,
               `99` sec 10.6) along (P - C)/|P - C|, bracket
               |d| +- max(0.1 % |d|, 5 mm), flags 517: committed InstanceId
               = the instance the PIXEL is on.
    query B    `101`'s thickness query: origin P - C, direction L, flags 545
               (Opaque|CullFrontFacing|SkipAABBs), tmin 1.5 mm, tmax 18 mm,
               committed t and InstanceId.
    query C    `101` sec 15's visibility query, now toward the LIGHT: origin
               P - C + (t + 1 mm) L, direction L, flags 517, tmin 1 mm,
               tmax max(dist - t - 1 mm, 1 mm) (100 m for a directional
               local light).
    accept     A hit AND B hit AND A.InstanceId == B.InstanceId AND C MISSED
    transfer   `111` v7, constants read from the SAME model JSON the shipped
               -hue1 raygen rung uses (dev/transmit_model.py --ref 0.006
               --fb-derm 0.01 --no-sensitivity):
                 t_eff = NMax(t, 6 mm)
                 T_c   = 0.5 (exp(-a1_c t_eff) + exp(-a2_c t_eff)) tint_c
                 W     = k NMax(-N.L, 0)
                 add_c = NMin(T_c W atten colour_c, 100)
               atten is the engine's own attenuation x spot factor -- the
               ONE factor of the `> 0` product whose value depends on the
               light's colour (the engine folds a 1 % colour-sum cull into
               it); every OTHER factor of that product is a shadow /
               visibility mask and is deliberately NOT applied, because a
               backlit ear is exactly the pixel those masks zero.
    gate       class == 1 (skin) AND slot magic AND atten > 0, folded into
               the cull mask (255 / 0): a shut gate is three free misses.
    write      accumulated per channel in Function storage and added ONCE,
               at the DIFFUSE output write -- identified as the write the
               Disney diffuse (c1) term reaches, never as "the first write".

Modules with no light loop (15 sun-only resolvers) and the two declined by
name (`103`: ab0bc2fee876d489, 99bb7c2698997b2a) come out BYTE-IDENTICAL.

THE LAYER IS HALF THE FEATURE (`103`). The TLAS reaches a compute module only
through swap_layer.c's BDA slot: this file carries the same marker, sentinel
pair and slot idiom as dev/patch_bda.py (imported, never retyped), and the
layer REJECTS the overlay on a device where the slot could not be armed.

  ./dev/build_earglow_di.sh          # all four rungs + gates
  python3 dev/patch_earglow_di.py <in.spvasm> --outdir <dir> --model r6lo.json \
          [--mode glow|hit|ctl] [--k-scale 2] [--decoy ...] [--census]

NOT EDITED BY THIS FILE, only imported: dev/patch_bda.py, dev/wpos_core.py,
dev/patch_curv.py, dev/patch_compute_skin.py, dev/patch_earglow7.py.
"""
import argparse, collections, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_shadow_brdf import CFG
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift, find_c1_sites
from patch_earglow7 import load_model
import wpos_core as W
from patch_bda import (MARKER, SENT_LO, SENT_HI, MAGIC, ID_W, SLOT_MEMBERS,
                       W_MAGIC, W_LO, W_HI, DECLINE_ALL, DECLINE_RQ,
                       insert_sections, entry_hoist_line, exact_float,
                       need_type, resolve_marker_ids)

# ---- the ray contract (101 sec 2 / sec 15, 98 sec 10.4) -------------------
FLAGS_A = 0x001 | 0x004 | 0x200         # 517 Opaque|TerminateOnFirstHit|SkipAABBs
FLAGS_B = 0x001 | 0x020 | 0x200         # 545 Opaque|CullFrontFacing|SkipAABBs
FLAGS_B_DECOY = 0x001 | 0x010 | 0x200   # 529 CullBackFacing: reads the FRONT wall
FLAGS_C = FLAGS_A
MASK = 255
TMIN_B, TMAX_B = 0.0015, 0.018          # 1.5 mm .. 18 mm  (101 sec 2)
PUSH = 0.001                            # exit point 1 mm past the wall (101 sec 15)
TMIN_C = 0.001
TMAX_C_DIRECTIONAL = 100.0
BRACKET_REL, BRACKET_MIN = 0.001, 0.005  # query A: |d| +- max(0.1 %, 5 mm)
FLOOR = 0.006                           # 101 sec 18: t_eff = NMax(t, 6 mm)
CLAMP = 100.0                           # 111: per-channel add cap
LIGHT_STRIDE = 128
OFF_POS, OFF_DIR, OFF_COL, OFF_FLAGS = 0, 16, 32, 44
DIRECTIONAL_BIT = 128

DIAG_BLUE = (0.0, 0.4, 3.2)     # accepted: same-instance wall, exit point sees the light
DIAG_AMBER = (3.2, 1.6, 0.0)    # B committed same-instance, C HIT (interior wall / occluder)
DIAG_RED = (3.2, 0.0, 0.0)      # the slot magic was wrong (the layer did not arm)

DECOYS = ('', 'nomarker', 'badid', 'scan', 'world', 'cullback', 'noc', 'noa',
          'flatk', 'spec')


# ------------------------------------------------------------------ helpers
def defs(mod):
    D = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(\S+)(.*)$', ln)
        if m:
            D[m.group(1)] = (i, m.group(2), m.group(3).split())
    return D


def fconsts(mod):
    K = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)', ln)
        if m:
            try:
                K[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return K


def uconsts(mod):
    K = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %uint (\d+)\s*$', ln)
        if m:
            K[m.group(1)] = int(m.group(2))
    return K


def _cone(D, root, limit=4000):
    seen, st = set(), [root]
    while st and len(seen) < limit:
        y = st.pop()
        if y in seen or y not in D:
            continue
        seen.add(y)
        st.extend(o for o in D[y][2] if o.startswith('%'))
    return seen


def _flatten_mul(D, x, out):
    if D.get(x, (0, ''))[1] == 'OpFMul':
        for o in D[x][2][1:3]:
            _flatten_mul(D, o, out)
    else:
        out.append(x)


def block_start(mod, line):
    for k in range(line, -1, -1):
        if re.match(r'\s*%\w+\s*=\s*OpLabel\s*$', mod.lines[k]):
            return k
    return None


def label_line(mod, lab):
    for i, ln in enumerate(mod.lines):
        if re.match(r'\s*' + re.escape(lab) + r'\s*=\s*OpLabel\s*$', ln):
            return i
    return None


def find_light_sites(mod, D, ctx):
    """One site per clustered-light record read: the `vis * atten > 0` branch.

    Anchors, all structural (never an id): the stride-128 OpRawAccessChainNV
    into the light list at offset 0 (pos), its v3 load and three extracts,
    the three `pos_c - P_c` subtractions against the module's OWN P, the dir
    (16) / colour (32) / flags (44) loads of the SAME record, and the one
    `OpFOrdGreaterThan x 0` + OpSelectionMerge + OpBranchConditional whose
    TRUE block consumes those subtractions within its first instructions.
    Returns (sites, skipped).
    """
    P = list(ctx['p'])
    KU = uconsts(mod)
    KF = fconsts(mod)
    stride_ids = {i for i, v in KU.items() if v == LIGHT_STRIDE}
    off_ids = {o: {i for i, v in KU.items() if v == o}
               for o in (OFF_POS, OFF_DIR, OFF_COL, OFF_FLAGS)}
    sites, skipped = [], []
    loads_of = collections.defaultdict(list)
    extracts_of = collections.defaultdict(dict)
    for k, v in D.items():
        if v[1] == 'OpLoad' and len(v[2]) >= 2:
            loads_of[v[2][1]].append(k)
        elif v[1] == 'OpCompositeExtract' and len(v[2]) == 3:
            extracts_of[v[2][1]][int(v[2][2])] = k
    rec = {}
    for k, v in D.items():
        if (v[1] == 'OpRawAccessChainNV' and len(v[2]) >= 5
                and v[2][2] in stride_ids):
            rec.setdefault((v[2][1], v[2][3]), {})[v[2][4]] = (k, v[2][0])

    def one_off(r, off, ty):
        c = [k for o, (k, t) in r.items() if o in off_ids[off] and t == ty]
        return c[0] if len(c) == 1 else None

    order = sorted(rec.items(), key=lambda kv: min(D[k][0] for k, _ in kv[1].values()))
    bounds = [min(D[k][0] for k, _ in r.values()) for _, r in order] + [len(mod.lines)]
    for n, ((base, idx), r) in enumerate(order):
        pos = one_off(r, OFF_POS, '%_ptr_StorageBuffer_v3float')
        if pos is None:
            continue                       # not a light record read
        ld = loads_of.get(pos, [])
        if len(ld) != 1 or sorted(extracts_of.get(ld[0], {})) != [0, 1, 2]:
            skipped.append(dict(chain=pos, why='pos load/extract shape'))
            continue
        ex = extracts_of[ld[0]]
        sub = [None] * 3
        for k, v in D.items():
            if v[1] == 'OpFSub' and len(v[2]) == 3:
                for c in range(3):
                    if v[2][1] == ex[c] and v[2][2] == P[c]:
                        sub[c] = k
        if None in sub:
            skipped.append(dict(chain=pos, why='no lightPos - P triple'))
            continue
        dirc = one_off(r, OFF_DIR, '%_ptr_StorageBuffer_v3float')
        colc = one_off(r, OFF_COL, '%_ptr_StorageBuffer_v3float')
        flc = one_off(r, OFF_FLAGS, '%_ptr_StorageBuffer_uint')
        if not (dirc and colc and flc):
            skipped.append(dict(chain=pos, why='record lacks dir/colour/flags'))
            continue
        dld, cld, fld = (loads_of.get(x, []) for x in (dirc, colc, flc))
        if not (len(dld) == len(cld) == len(fld) == 1):
            skipped.append(dict(chain=pos, why='dir/colour/flags not loaded once'))
            continue
        dex, cex = extracts_of.get(dld[0], {}), extracts_of.get(cld[0], {})
        if sorted(dex) != [0, 1, 2] or sorted(cex) != [0, 1, 2]:
            skipped.append(dict(chain=pos, why='dir/colour extract shape'))
            continue
        # selects of the subtractions (the shadowed loops build L before
        # the branch; the unshadowed ones branch on the flag instead)
        sel_of_sub = {k for k, v in D.items()
                      if v[1] == 'OpSelect' and len(v[2]) == 4
                      and (v[2][2] in sub or v[2][3] in sub)}
        consumers = set(sub) | sel_of_sub
        first = D[sub[0]][0]
        # Every `x > 0` gate of THIS record's loop whose product carries the
        # light's colour and whose lit block consumes L. A shadowed loop has
        # two: `atten > 0` guarding the spot-cone block, then
        # `vis * atten_spot > 0` guarding the lit block -- the site is the
        # LAST. An unshadowed loop has only the first, and its spot factor
        # is computed INSIDE the lit block, so it is skipped by name.
        cands = []
        for i in range(first, bounds[n + 1]):
            m = re.match(r'\s*(%\w+)\s*=\s*OpFOrdGreaterThan %bool (%\w+) (%\w+)\s*$',
                         mod.lines[i])
            if not m or KF.get(m.group(3)) != 0.0:
                continue
            if not mod.lines[i + 1].strip().startswith('OpSelectionMerge '):
                continue
            mb = re.match(r'\s*OpBranchConditional ' + re.escape(m.group(1))
                          + r' (%\w+) (%\w+)\s*$', mod.lines[i + 2])
            if not mb:
                continue
            merge = mod.lines[i + 1].split()[1]
            t_lab = mb.group(1) if mb.group(2) == merge else None
            if t_lab is None:
                continue
            tl = label_line(mod, t_lab)
            if tl is None:
                continue
            head = ' '.join(mod.lines[tl + 1:tl + 16])
            if not any(re.search(re.escape(c) + r'\b', head) for c in consumers):
                continue
            fac = []
            _flatten_mul(D, m.group(2), fac)
            att = [f for f in fac if cld[0] in _cone(D, f)]
            if len(att) != 1:
                continue
            cands.append((i, m.group(1), m.group(2), t_lab, fac, att[0]))
        if not cands:
            skipped.append(dict(chain=pos, why='no colour-gated lit branch'))
            continue
        line, cond, prod, t_lab, fac, atten = cands[-1]
        if len(fac) < 2:
            skipped.append(dict(chain=pos, line=line + 1,
                                why='unshadowed loop: no visibility factor, spot '
                                    'factor is inside the lit block'))
            continue
        sites.append(dict(line=line, cond=cond, prod=prod, atten=atten,
                          factors=fac, n_masks=len(fac) - 1, sub=sub,
                          dir=[dex[c] for c in range(3)],
                          col=[cex[c] for c in range(3)], flags=fld[0],
                          col_load=cld[0], lit=t_lab, chain=pos,
                          n_gates=len(cands)))
    return sites, skipped


def find_pixel_normal(mod, D, ctx):
    """The module's `normalize(fetch(N).xyz - 0.5)` AT THE PIXEL'S OWN COORD.

    patch_curv's find_normal_decode matches the same shape but dies on more
    than one hit -- and the shipped default's compute half IS `109`'s curv
    modules, which carry extra decodes at +-1 texel for the curvature taps.
    The pixel's own decode is the one whose fetch coordinate is the position
    chain's coordinate (the same id as the depth fetch, or a construct of the
    same x, y ids). Exactly one must match.
    """
    hits = []
    for idt, (line, txt) in D.items():
        m = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$', txt)
        if not m:
            continue
        img, coord, lod = m.groups()
        ex = {}
        for i2, (_l2, t2) in D.items():
            me = re.match(r'OpCompositeExtract %float ' + re.escape(idt) + r' (\d)\s*$', t2)
            if me:
                ex[int(me.group(1))] = i2
        if not all(k in ex for k in (0, 1, 2)):
            continue
        sub = {}
        for k in (0, 1, 2):
            for i3, (_l3, t3) in D.items():
                mm = re.match(r'OpFAdd %float ' + re.escape(ex[k]) + r' (%\w+)\s*$', t3)
                if mm and re.match(r'OpConstant %float -0\.5\s*$', D.get(mm.group(1), (0, ''))[1]):
                    sub[k] = i3
        if len(sub) != 3:
            continue
        cons = [i for i, (_l, t) in D.items()
                if t.strip() == 'OpCompositeConstruct %v3float ' + sub[0] + ' ' + sub[1] + ' ' + sub[2]]
        dots = [i for i, (_l, t) in D.items()
                if re.match(r'OpDot %float (%\w+) (%\w+)\s*$', t)
                and set(re.findall(r'%\w+', t)[1:]) <= set(cons)]
        rsq = [i for i, (_l, t) in D.items()
               if any(re.match(r'OpExtInst %float %\w+ InverseSqrt ' + re.escape(d) + r'\s*$', t) for d in dots)]
        if not rsq:
            continue
        muls = {}
        for k in (0, 1, 2):
            for i4, (_l4, t4) in D.items():
                if t4.strip() in ('OpFMul %float ' + rsq[0] + ' ' + sub[k], 'OpFMul %float ' + sub[k] + ' ' + rsq[0]):
                    muls[k] = i4
        if len(muls) != 3:
            continue
        hits.append(dict(img=img, coord=coord, lod=lod, fetch_line=line, n=[muls[k] for k in (0, 1, 2)]))
    own = []
    dcoord = ctx['depth']['coord'] if ctx.get('depth') else None
    xy = tuple(ctx['coord_xy']) if ctx.get('coord_xy') else None
    for h in hits:
        if h['coord'] == dcoord:
            own.append(h); continue
        mc = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$', D.get(h['coord'], (0, ''))[1])
        if xy and mc and mc.groups() == xy:
            own.append(h)
    if len(own) != 1:
        die('%s: %d normal decodes at the pixel coordinate (%d in all), want exactly 1'
            % (mod.name, len(own), len(hits)))
    return own[0]


def diffuse_write(mod, D, writes):
    """The write the Disney diffuse (c1) term reaches; exactly one."""
    c1, _ = find_c1_sites(mod)
    if not c1:
        die(f"{mod.name}: no Disney diffuse site to trace the diffuse output from")
    uses = collections.defaultdict(set)
    for k, v in D.items():
        for o in v[2]:
            if o.startswith('%') and o in D:
                uses[o].add(k)
    seen = {s['scalar'] for s in c1}
    st = list(seen)
    while st:
        x = st.pop()
        for y in uses[x]:
            if y not in seen:
                seen.add(y)
                st.append(y)
    hit = [w for w in writes if w['comps'] and any(c in seen for c in w['comps'][:3])]
    if len(hit) != 1:
        die(f"{mod.name}: the diffuse term reaches {len(hit)} writes, want 1")
    return hit[0]


# --------------------------------------------------------------- the build
def build(mod, cfg, mode, model, kscale, decoy):
    D = defs(mod)
    consts, decos, caps, exts = [], [], [], []
    uc = {}
    I = mod.new_id

    def C(v):
        nid, c = mod.const(v)
        if c:
            consts.append(c)
        return nid

    def U(n):
        key = ('u', int(n))
        if key in uc:
            return uc[key]
        nid, c = mod.uconst(n)
        if c:
            consts.append(c)
        uc[key] = nid
        return nid

    uc['decls'] = consts
    for t in ('%uint', '%v2uint', '%bool', '%float', '%v3float', '%v4float'):
        need_type(mod, t)
    ptr_ff = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$', ln)
        if m:
            ptr_ff = m.group(1)
    if ptr_ff is None:
        ptr_ff = I()
        consts.append(f"    {ptr_ff} = OpTypePointer Function %float")

    ctx = W.find_pos_chain(mod)
    if ctx is None:
        die(f"{mod.name}: no P = M.(x,y,depth,1)/w reconstruction")
    cam = W.find_campos(mod, ctx)
    if cam is None:
        die(f"{mod.name}: no camera position (C - P) triple")
    nd = find_pixel_normal(mod, W.defs_index(mod), ctx)
    sites, skipped = find_light_sites(mod, D, ctx)
    writes = find_image_writes(mod)
    rep = {'mode': mode, 'decoy': decoy, 'sites': [], 'skipped': skipped,
           'declined': False, 'control': False}
    if not sites:
        rep['emitted'] = 0
        rep['why'] = 'no clustered light loop -- identity'
        return None, rep
    wr = diffuse_write(mod, D, writes)
    if decoy == 'spec':
        others = [w for w in writes if w is not wr and w['comps']]
        if not others:
            die(f"{mod.name}: --decoy spec needs a second write")
        wr = others[0]

    # ---- the slot (103), verbatim idiom -----------------------------------
    slot, ptr_slot, ptr_uint = I(), I(), I()
    for k in range(SLOT_MEMBERS):
        decos.append(f"               OpMemberDecorate {slot} {k} Offset {4 * k}")
    decos.append(f"               OpDecorate {slot} Block")
    for k in range(SLOT_MEMBERS):
        decos.append(f"               OpMemberDecorate {slot} {k} NonWritable")
    consts.append(f"    {slot} = OpTypeStruct " + ' '.join(['%uint'] * SLOT_MEMBERS))
    consts.append(f"    {ptr_slot} = OpTypePointer PhysicalStorageBuffer {slot}")
    consts.append(f"    {ptr_uint} = OpTypePointer PhysicalStorageBuffer %uint")
    lo, hi = I(), I()
    consts.append(f"    {lo} = OpConstant %uint {SENT_LO}")
    consts.append(f"    {hi} = OpConstant %uint {SENT_HI}")
    if decoy == 'scan':
        d1, d2 = I(), I()
        consts.append(f"    {d1} = OpConstant %uint {SENT_LO}")
        consts.append(f"    {d2} = OpConstant %uint {SENT_HI}")
    magic = I()
    consts.append(f"    {magic} = OpConstant %uint {MAGIC}")
    marker = None
    if decoy != 'nomarker':
        badl = 4294967295 if decoy == 'badid' else 0
        marker = ('%{0} = OpString "{1} lo=%{2:0{4}d} hi=%{3:0{4}d} '
                  'sent={5:016x} magic={6:08x}"').format(
            I()[1:], MARKER, badl, badl, ID_W,
            (SENT_HI << 32) | SENT_LO, MAGIC)
    caps.append("               OpCapability RayQueryKHR")
    caps.append("               OpCapability RayTraversalPrimitiveCullingKHR")
    exts.append('               OpExtension "SPV_KHR_ray_query"')
    rq_ty, rq_ptr, as_ty = I(), I(), I()
    consts.append(f"    {rq_ty} = OpTypeRayQueryKHR")
    consts.append(f"    {rq_ptr} = OpTypePointer Function {rq_ty}")
    consts.append(f"    {as_ty} = OpTypeAccelerationStructureKHR")
    rqA, rqB, rqC = I(), I(), I()
    gv = [I(), I(), I()]
    f0 = exact_float(mod, '0', consts)
    f1 = exact_float(mod, '1', consts)
    v2, pp, ac0, w0, ok = I(), I(), I(), I(), I()
    acl, ach, ldl, ldh, av2, accel = I(), I(), I(), I(), I(), I()
    hoist = [f"        {rqA} = OpVariable {rq_ptr} Function",
             f"        {rqB} = OpVariable {rq_ptr} Function",
             f"        {rqC} = OpVariable {rq_ptr} Function"]
    hoist += [f"        {g} = OpVariable {ptr_ff} Function" for g in gv]
    hoist += [
        f"        {v2} = OpCompositeConstruct %v2uint {lo} {hi}",
        f"        {pp} = OpBitcast {ptr_slot} {v2}",
        f"        {ac0} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_MAGIC)}",
        f"        {w0} = OpLoad %uint {ac0} Aligned 4",
        f"        {ok} = OpIEqual %bool {w0} {magic}",
        f"        {acl} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_LO)}",
        f"        {ldl} = OpLoad %uint {acl} Aligned 4",
        f"        {ach} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_HI)}",
        f"        {ldh} = OpLoad %uint {ach} Aligned 4",
        f"        {av2} = OpCompositeConstruct %v2uint {ldl} {ldh}",
        f"        {accel} = OpConvertUToAccelerationStructureKHR {as_ty} {av2}",
    ]
    hoist += [f"        OpStore {g} {f0}" for g in gv]

    # ---- constants ----
    zero3 = I()
    consts.append(f"    {zero3} = OpConstantComposite %v3float {f0} {f0} {f0}")
    u_fa = U(FLAGS_A)
    u_fb = U(FLAGS_B_DECOY if decoy == 'cullback' else FLAGS_B)
    u_fc = U(FLAGS_C)
    u_255, u_0, u_1 = U(MASK), U(0), U(1)
    u_dirbit = U(DIRECTIONAL_BIT)
    f_tminb, f_tmaxb = C(TMIN_B), C(TMAX_B)
    f_push, f_tminc, f_far = C(PUSH), C(TMIN_C), C(TMAX_C_DIRECTIONAL)
    f_brel, f_bmin = C(BRACKET_REL), C(BRACKET_MIN)
    f_floor, f_clamp, f_half = C(FLOOR), C(CLAMP), C(0.5)
    rates, tint, k0, _ = model
    k = k0 * kscale
    f_k = C(k)
    f_a1 = [C(r[0]) for r in rates]
    f_a2 = [C(r[1]) for r in rates]
    f_tint = [None, C(tint[1]), C(tint[2])]
    if mode == 'hit':
        c_blue = [C(x) for x in DIAG_BLUE]
        c_amber = [C(x) for x in DIAG_AMBER]
        c_red = [C(x) for x in DIAG_RED]
    glsl = mod.glsl

    shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod, cfg)
    consts.extend(pre_consts)
    edits = []
    if pre_ins:
        edits.append((ins_line, pre_ins))
    edits.append((entry_hoist_line(mod), hoist))

    done = []
    for s in sites:
        L = s['line']
        need = [s['atten'], s['flags'], s['col_load'], dom_id] + s['sub'] + s['dir'] + nd['n']
        bad = [x for x in need if not cfg.dominates_line(x, L)]
        p_top = all(cfg.dominates_line(i, L) for i in ctx['p'])
        if bad or not p_top:
            skipped.append(dict(chain=s['chain'], line=L + 1,
                                why='inputs do not dominate: %s' % bad))
            continue
        ins = []
        ind = '        '

        def E(op, ty, *a):
            n = I()
            ins.append(f"{ind}{n} = {op} {ty} " + ' '.join(a))
            return n

        def X(fn, *a):
            return E('OpExtInst', '%float', glsl, fn, *a)

        # gate -> cull mask. class == 1 AND magic AND atten > 0
        g_cls = E('OpIEqual', '%bool', shift, u_1)
        g_att = E('OpFOrdGreaterThan', '%bool', s['atten'], f0)
        g1 = E('OpLogicalAnd', '%bool', g_cls, ok)
        gate = E('OpLogicalAnd', '%bool', g1, g_att)
        mask = E('OpSelect', '%uint', gate, u_255, u_0)
        # P - C (99 sec 10.6)
        pos = W.emit_world_pos(mod, cfg, ctx, L, ins, uc=uc,
                               relative_to_camera=(decoy != 'world'), cam=cam)
        org = E('OpCompositeConstruct', '%v3float', *pos)
        # L = normalize(select(directional, -dir, lightPos - P))
        fbit = E('OpBitwiseAnd', '%uint', s['flags'], u_dirbit)
        isdir = E('OpINotEqual', '%bool', fbit, u_0)
        raw = []
        for c in range(3):
            nd_c = E('OpFNegate', '%float', s['dir'][c])
            raw.append(E('OpSelect', '%float', isdir, nd_c, s['sub'][c]))
        rv = E('OpCompositeConstruct', '%v3float', *raw)
        d2 = E('OpDot', '%float', rv, rv)
        dist = X('Sqrt', d2)
        inv = E('OpFDiv', '%float', f1, dist)
        Lc = [E('OpFMul', '%float', raw[c], inv) for c in range(3)]
        Lv = E('OpCompositeConstruct', '%v3float', *Lc)
        # query A: camera -> P bracket, same instance as the pixel
        dd = E('OpDot', '%float', org, org)
        dl = X('Sqrt', dd)
        dinv = E('OpFDiv', '%float', f1, dl)
        dA = [E('OpFMul', '%float', pos[c], dinv) for c in range(3)]
        dAv = E('OpCompositeConstruct', '%v3float', *dA)
        wrel = E('OpFMul', '%float', dl, f_brel)
        wA = X('NMax', wrel, f_bmin)
        tminA = E('OpFSub', '%float', dl, wA)
        tmaxA = E('OpFAdd', '%float', dl, wA)
        ins.append(f"{ind}OpRayQueryInitializeKHR {rqA} {accel} {u_fa} {mask} "
                   f"{zero3} {tminA} {dAv} {tmaxA}")
        E('OpRayQueryProceedKHR', '%bool', rqA)
        tyA = E('OpRayQueryGetIntersectionTypeKHR', '%uint', rqA, u_1)
        hitA = E('OpINotEqual', '%bool', tyA, u_0)
        idA = E('OpRayQueryGetIntersectionInstanceIdKHR', '%uint', rqA, u_1)
        # query B: thickness toward the light
        ins.append(f"{ind}OpRayQueryInitializeKHR {rqB} {accel} {u_fb} {mask} "
                   f"{org} {f_tminb} {Lv} {f_tmaxb}")
        E('OpRayQueryProceedKHR', '%bool', rqB)
        tyB = E('OpRayQueryGetIntersectionTypeKHR', '%uint', rqB, u_1)
        hitB = E('OpINotEqual', '%bool', tyB, u_0)
        idB = E('OpRayQueryGetIntersectionInstanceIdKHR', '%uint', rqB, u_1)
        tB = E('OpRayQueryGetIntersectionTKHR', '%float', rqB, u_1)
        t = E('OpSelect', '%float', hitB, tB, f_tmaxb)
        same = E('OpIEqual', '%bool', idA, idB)
        # query C: from the exit point toward the light
        tp = E('OpFAdd', '%float', t, f_push)
        oc = []
        for c in range(3):
            st = E('OpFMul', '%float', Lc[c], tp)
            oc.append(E('OpFAdd', '%float', pos[c], st))
        ocv = E('OpCompositeConstruct', '%v3float', *oc)
        rem = E('OpFSub', '%float', dist, tp)
        rem2 = X('NMax', rem, f_tminc)
        tmaxC = E('OpSelect', '%float', isdir, f_far, rem2)
        if decoy != 'noc':
            ins.append(f"{ind}OpRayQueryInitializeKHR {rqC} {accel} {u_fc} {mask} "
                       f"{ocv} {f_tminc} {Lv} {tmaxC}")
            E('OpRayQueryProceedKHR', '%bool', rqC)
            tyC = E('OpRayQueryGetIntersectionTypeKHR', '%uint', rqC, u_1)
            hitC = E('OpINotEqual', '%bool', tyC, u_0)
            visC = E('OpLogicalNot', '%bool', hitC)
        # accept
        ab = E('OpLogicalAnd', '%bool', hitA, hitB)
        abi = ab if decoy == 'noa' else E('OpLogicalAnd', '%bool', ab, same)
        acc = abi if decoy == 'noc' else E('OpLogicalAnd', '%bool', abi, visC)
        if mode == 'hit':
            # class-1 pixels only (the mask already shuts the queries)
            for c in range(3):
                inner = E('OpSelect', '%float', abi, c_amber[c], f0)
                sel = E('OpSelect', '%float', acc, c_blue[c], inner)
                pm = E('OpSelect', '%float', ok, sel, c_red[c])
                pg = E('OpSelect', '%float', g_cls, pm, f0)
                ld = E('OpLoad', '%float', gv[c])
                ad = E('OpFAdd', '%float', ld, pg)
                ins.append(f"{ind}OpStore {gv[c]} {ad}")
        else:
            # transfer (111 v7)
            nv = E('OpCompositeConstruct', '%v3float', *nd['n'])
            ndl = E('OpDot', '%float', nv, Lv)
            nneg = E('OpFNegate', '%float', ndl)
            wrap = X('NMax', nneg, f0)
            wk = E('OpFMul', '%float', wrap, f_k)
            wa = E('OpFMul', '%float', wk, s['atten'])
            teff = X('NMax', t, f_floor)
            tneg = E('OpFNegate', '%float', teff)
            for c in range(3):
                if decoy == 'flatk':
                    T = f1
                else:
                    e1 = E('OpFMul', '%float', tneg, f_a1[c])
                    x1 = X('Exp', e1)
                    e2 = E('OpFMul', '%float', tneg, f_a2[c])
                    x2 = X('Exp', e2)
                    sm = E('OpFAdd', '%float', x1, x2)
                    T = E('OpFMul', '%float', sm, f_half)
                    if c:
                        T = E('OpFMul', '%float', T, f_tint[c])
                m1 = E('OpFMul', '%float', T, wa)
                m2 = E('OpFMul', '%float', m1, s['col'][c])
                m3 = X('NMin', m2, f_clamp)
                g = E('OpSelect', '%float', acc, m3, f0)
                ld = E('OpLoad', '%float', gv[c])
                ad = E('OpFAdd', '%float', ld, g)
                ins.append(f"{ind}OpStore {gv[c]} {ad}")
        edits.append((L, ins))
        done.append(dict(line=L + 1, n_masks=s['n_masks'], lit=s['lit'],
                         instructions=len(ins)))
    if not done:
        die(f"{mod.name}: light loops found but no site could be spliced")

    # ---- add at the DIFFUSE write ----
    if wr['comps'] is None:
        die(f"{mod.name}: the diffuse write is not a v4 construct")
    c = wr['comps']
    wind = re.match(r'(\s*)', mod.lines[wr['line']]).group(1)
    wi, newc = [], []
    for ch in range(3):
        l = I(); wi.append(f"{wind}{l} = OpLoad %float {gv[ch]}")
        a = I(); wi.append(f"{wind}{a} = OpFAdd %float {c[ch]} {l}")
        newc.append(a)
    nt = I()
    wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
              f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
    edits.append((wr['line'] - 1, wi))
    mod.lines[wr['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                   r'\g<1>' + nt, mod.lines[wr['line']])
    rep.update(sites=done, write_line=wr['line'] + 1, n_writes=len(writes),
               k=k, k_scale=kscale, rates=rates, tint=tint,
               flags=dict(A=FLAGS_A, B=(FLAGS_B_DECOY if decoy == 'cullback' else FLAGS_B), C=FLAGS_C),
               tmin_b=TMIN_B, tmax_b=TMAX_B, push=PUSH, tmin_c=TMIN_C,
               floor=FLOOR, clamp=CLAMP, mask=MASK,
               space='world' if decoy == 'world' else 'camera_relative',
               campos_member=cam['member'], cbv_slot=ctx['cbv_slot'],
               matrix_members=ctx['mat'], class_anchor=dom_id,
               slot_members=SLOT_MEMBERS,
               sentinel='%016x' % ((SENT_HI << 32) | SENT_LO),
               magic='%08x' % MAGIC, emitted=1)
    return (consts, edits, caps, exts, marker, decos), rep


def process(path, outdir, mode, model, kscale, decoy, do_rt=True):
    target_env = detect_target_env(path) or 'spv1.3'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    h = mod.ident.split('.')[0]
    if mode == 'ctl' or h in DECLINE_ALL or h in DECLINE_RQ:
        rep['earglow_di'] = {'mode': mode, 'control': mode == 'ctl',
                             'declined': mode != 'ctl', 'sites': [],
                             'skipped': [], 'emitted': 0, 'decoy': decoy}
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    parts, r = build(mod, cfg, mode, model, kscale, decoy)
    rep['earglow_di'] = r
    if parts is None:
        return CS._emit(mod, outdir, target_env, rep)
    consts, edits, caps, exts, marker, decos = parts
    apply_edits(mod, consts, edits)
    insert_sections(mod, caps, exts, marker, decos)
    rep = CS._emit(mod, outdir, target_env, rep)
    r.update(resolve_marker_ids(rep['out'], decoy))
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', rep['out']],
                       capture_output=True, text=True)
    if v.returncode != 0:
        os.unlink(rep['out'])
        die(f"spirv-val (vulkan1.4) FAILED after the marker rewrite on "
            f"{mod.name}:\n" + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(rep['out'], 'rb').read()).hexdigest()
    return rep


def census(paths):
    out = []
    for p in paths:
        mod, _ = load_lenient(p)
        D = defs(mod)
        ctx = W.find_pos_chain(mod)
        if ctx is None:
            out.append(dict(module=mod.name, why='no P chain'))
            continue
        sites, skipped = find_light_sites(mod, D, ctx)
        out.append(dict(module=mod.name, sites=[(s['line'] + 1, s['n_masks']) for s in sites],
                        skipped=skipped))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir')
    ap.add_argument('--model', help='transmit_model.py JSON (rates, tint, k)')
    ap.add_argument('--mode', choices=('glow', 'hit', 'ctl'), default='glow')
    ap.add_argument('--k-scale', type=float, default=1.0)
    ap.add_argument('--decoy', default='', choices=DECOYS)
    ap.add_argument('--census', action='store_true')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    if a.census:
        census(a.modules)
        return
    if not a.outdir:
        die('--outdir is required')
    model = load_model(a.model) if a.mode != 'ctl' else (None, None, 0.0, None)
    reps = [process(p, a.outdir, a.mode, model, a.k_scale, a.decoy,
                    do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
