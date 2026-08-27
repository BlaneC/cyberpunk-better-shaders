#!/usr/bin/env python3
"""
patch_skin_brdf.py -- splice Callisto BRDF terms into CP2077's PT raygen SPIR-V.

Text-level patcher: takes the spirv-dis disassembly of rgs_reference_main
(spv_0170 / spv_0171), locates the diffuse eval sites by the 1/pi constant,
splices in new instructions (skin-gated), reassembles with spirv-as and
validates with spirv-val. Emits <outdir>/<dxilhash>.spv ready for the
VK_LAYER_CALLISTO_spvswap layer (analysis/mod/CallistoSSS/).

Background: analysis/BRDF_HANDOFF.md (sites, gating, tiers) and
analysis/callisto_brdf_over_lambert.md (math).

Anchors (all auto-detected structurally, ids differ per module):
  - `%float_0_318309873` = float32(1/pi): the diffuse eval constant.
    Sites = runs of 3 consecutive `OpFMul %float %X %PI`.
      * "primary" triples: multiplicands are (1-w)*albedo FMuls (3 copies:
        NEE/MIS light evals of the primary hit).
      * "env" triples: multiplicands are the raw albedo ids (light-category-2
        branch of each copy).
  - Skin gate: G-buffer class test in the raygen (same as SSS_Blur):
    `OpIEqual %bool (OpShiftRightLogical (OpCompositeExtract fetch 1) 5) 1`.
    It is the primary-hit skin test and dominates every eval site.
  - Channel mapping: env triples multiply albedo in r,g,b order; primary
    triples resolve through one (1-w) FMul to the same albedo ids.
  - Tier-1 per-site angles: NoL = the weight that multiplies the gated
    diffuse (trace r-channel value through 3 FMuls); NoV = the
    NClamp01(NMax(dot,1e-5)) of the GGX block above the triple.

Tiers:
  smoke  -- tint skin diffuse (TINT knob) at ALL triples; proves layer,
            hashing, gating, cache-clearing (BRDF_HANDOFF §5).
  1      -- c1 = lerp(1,rho_f,alpha_f)*lerp(1,rho_r,alpha_r) with
            alpha_f = (1-NoL)^(5 r(n_f)) * NoV^(5 r(m_f)),
            alpha_r = (1-NoV)^(5 r(n_r)) * NoL^(5 r(m_r)),  r(x)=2(1-x);
            applied at the 3 primary triples only (eval-side modulation,
            no pdf change -- BRDF_HANDOFF §4).

Regression: with --vanilla (or defaults rho_f=rho_r=1), every inserted
factor is exactly 1.0 -> bit-identical output (BRDF_HANDOFF §6.2).
"""

import argparse, json, os, re, struct, subprocess, sys, hashlib

# ---------------------------------------------------------------- knobs
KNOBS = {
    # smoke tint (r,g,b)
    "tint": (2.0, 0.2, 0.2),
    # c1 params (BRDF_HANDOFF Tier-1 suggested start; tints white)
    "rho_f": 1.35, "n_f": 0.75, "m_f": 0.75,
    "rho_r": 1.25, "n_r": 0.75, "m_r": 0.75,
    # hair (HAIR_HANDOFF.md); identity at s_h=1, a_min=0, k_sheen=0, w_wrap=0
    "s_h": 0.55,      # roughness scale: <1 sharpens the highlight
    "a_min": 0.04,    # floor so hair never goes mirror-sharp
    "k_sheen": 0.15,  # grazing sheen added to F
    "w_wrap": 0.4,    # diffuse wrap width
    "r_max": 4.0,     # wrap ratio clamp (firefly guard)
    # structure-tensor tangent (HAIR_HANDOFF "tangent can be ESTIMATED")
    "kd_dbg": 4.0,    # hairdbg tint gain (red=low confidence, green=high)
    # Structure-tensor confidence remap. `aniso` = (l1-l2)/(l1+l2) gates BOTH
    # the Kajiya factor and the dual lobe, so a weak tangent estimate collapses
    # every hair effect to identity regardless of m_aniso/m_dual (the
    # 2026-08-26 null result). Identity at gain=1, floor=0.
    # Diagnostic: an ADDITIVE constant on the hair spec outs. Every real hair
    # effect is a multiply, so all of them are invisible if the out is ~0 --
    # which a multiply can never distinguish from "this out is never read".
    # Identity at 0.0.
    "spec_add": 0.0,
    "conf_gain": 1.0,  # scale on the measured confidence
    "conf_floor": 0.0, # lower bound under it; 1.0 = ignore the estimate
    "m_aniso": 0.7,   # anisotropic spec strength; 0 = identity
    "p_aniso": 16.0,  # Kajiya-style exponent on sin(T,H)
    # shifted dual-lobe (R + TRT) -- Marschner-flavoured second highlight.
    # m_dual=0 is the identity; all others only matter when m_dual > 0.
    "m_dual": 0.0,    # dual-lobe strength; 0 = off/identity
    "beta_R": -7.0,   # R-lobe tangent shift, degrees (toward root)
    "beta_TRT": 10.0, # TRT-lobe tangent shift, degrees (toward tip)
    "p_R": 28.0,      # R lobe exponent (sharp, white)
    "p_TRT": 10.0,    # TRT lobe exponent (wide, tinted)
    "wR": 1.0,        # R lobe weight
    "wTRT": 0.3,      # TRT lobe weight
    # TRT transmission tint (per-channel). The TRT lobe is transmit-reflect-
    # transmit light, so real hair colours it. Per-pixel albedo is NOT
    # recoverable in the compute resolvers (see 08-DUAL-LOBE.md), so this is a
    # single constant warm tint; identity at (1,1,1).
    "trt_r": 1.0,     # TRT tint, red
    "trt_g": 0.85,    # TRT tint, green
    "trt_b": 0.55,    # TRT tint, blue
    # GI-resolver dual-lobe variants: wider lobes (many indirect samples make
    # a tight lobe read as noise), TRT-weighted (the coloured glint shows in
    # bounce light). m_dual_gi defaults to m_dual (shared on/off).
    "m_dual_gi": -1.0,   # <0 => follow m_dual; >=0 overrides GI strength
    "p_R_gi": 8.0,       # GI R lobe exponent (wider than direct)
    "p_TRT_gi": 6.0,     # GI TRT lobe exponent (wider than direct)
    "wTRT_gi": 0.5,      # GI TRT weight (bounce-light glint)
}
VANILLA = dict(KNOBS, tint=(1.0, 1.0, 1.0), rho_f=1.0, rho_r=1.0,
               s_h=1.0, a_min=0.0, k_sheen=0.0, w_wrap=0.0, m_aniso=0.0,
               trt_r=1.0, trt_g=1.0, trt_b=1.0)

# gbuffer material class for hair -- NOT yet identified; see HAIR_HANDOFF.md
# section 1 for the discovery procedure. Skin is 1.
HAIR_CLASS = None

PI_CONST = "0.318309873"   # float32(1/pi) as printed by spirv-dis
EPS = 1e-5                 # pow base clamp (matches module's 9.99999975en06)

# ---------------------------------------------------------------- helpers
def f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]

def f32s(x):
    """shortest decimal that round-trips to the same float32."""
    return repr(f32(x))

def die(msg):
    sys.exit("patch_skin_brdf: error: " + msg)

class Module:
    def __init__(self, path):
        self.path = path
        self.lines = open(path, errors='replace').read().splitlines()
        self.name = os.path.basename(path)
        # OpString form: "<libhash>.\x01?<mangled-entry>.dxil"
        m = re.search(r'"([0-9a-f]{16})\.[\x00-\x1f]?\??([A-Za-z0-9_]+)@@[^"]*\.dxil"', '\n'.join(self.lines[:200]))
        if not m:
            m = re.search(r'"([0-9a-f]{16})\.[\x00-\x1f]?\??([A-Za-z0-9_]+)@@[^"]*\.dxil"', '\n'.join(self.lines))
        if m:
            # identity = library hash + entry (the hash alone is NOT unique:
            # one DXIL library yields several entry-point modules, e.g.
            # d622fb9e1dcb8cd0 covers rgs_reference_main AND ms_empty_main)
            self.dxil = m.group(1)
            self.ident = f"{m.group(1)}.{m.group(2)}"
        else:
            # Whole-library modules carry no entry in the OpString -- just
            # "<libhash>.dxil". The layer's scan parses that as id
            # "<libhash>.dxil" (the "entry" reads as "dxil"), so the ident
            # must match or the swap file name will not.
            # The middle segment is optional: a pure hash-only OpString is
            # exactly "<libhash>.dxil" with ONE dot, which the two-dot form of
            # this regex used to miss (ident came back None for every
            # whole-library compute module).
            m2 = re.search(r'"([0-9a-f]{16})\.(?:([^".]*)\.)?dxil"',
                           '\n'.join(self.lines))
            self.dxil = m2.group(1) if m2 else None
            if m2 and not m2.group(2):
                self.ident = f"{self.dxil}.dxil"     # hash-only library module
            else:
                self.ident = self.dxil
        # numeric id space
        ids = [int(x) for ln in self.lines for x in re.findall(r'%(\d+)\b', ln)]
        self.next_id = max(ids) + 1
        # float constants: float32 value -> id
        self.fconst = {}
        for i, ln in enumerate(self.lines):
            mm = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float (\S+)', ln)
            if mm:
                try: self.fconst[f32(float(mm.group(2)))] = mm.group(1)
                except ValueError: pass
        # glsl extinst set id (from an NClamp line -- NClamp is GLSL.std.450)
        self.glsl = None
        for ln in self.lines:
            mm = re.search(r'OpExtInst %float (%\w+) NClamp', ln)
            if mm: self.glsl = mm.group(1); break
        if not self.glsl: die(f"{self.name}: no GLSL.std.450 NClamp found")
        # 1/pi constant id
        self.pi_id = None
        pi_pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %float ' + re.escape(PI_CONST) + r'\b')
        for ln in self.lines:
            mm = pi_pat.match(ln)
            if mm: self.pi_id = mm.group(1); break
        if not self.pi_id: die(f"{self.name}: 1/pi constant not found")

    def new_id(self):
        i = self.next_id; self.next_id += 1
        return f"%{i}"

    def uconst(self, n):
        """Find or create an `OpConstant %uint n`; returns (id, decl_or_None)."""
        pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %uint ' + str(int(n)) + r'\s*$')
        for ln in self.lines:
            m = pat.match(ln)
            if m: return m.group(1), None
        nid = f"%uint_{int(n)}"
        return nid, f"    {nid} = OpConstant %uint {int(n)}"

    def const(self, value):
        v = f32(value)
        if v in self.fconst: return self.fconst[v], None
        nid = self.new_id()
        self.fconst[v] = nid
        return nid, f"    {nid} = OpConstant %float {f32s(v)}"

    def find_def(self, idtok):
        pat = re.compile(r'^\s*' + re.escape(idtok) + r'\s*=\s*(.*)$')
        for i, ln in enumerate(self.lines):
            m = pat.match(ln)
            if m: return i, m.group(1)
        return None, None

# ------------------------------------------------------------- detection
def find_triples(mod):
    """runs of 3 consecutive `OpFMul %float %X %PI` -> list of triple dicts."""
    hits = []
    pat = re.compile(r'^\s*(%\d+)\s*=\s*OpFMul %float (%\w+) ' + re.escape(mod.pi_id) + r'\s*$')
    for i, ln in enumerate(mod.lines):
        m = pat.match(ln)
        if m: hits.append((i, m.group(1), m.group(2)))
    triples, run = [], []
    for h in hits:
        if run and h[0] != run[-1][0] + 1:
            if len(run) == 3: triples.append(run)
            run = []
        run.append(h)
    if len(run) == 3: triples.append(run)
    return [dict(line=r[0][0], ids=[x[1] for x in r], muls=[x[2] for x in r]) for r in triples]

def resolve_leaf(mod, idtok):
    """if idtok = FMul(a,b) return its operands' leaves, else [idtok]."""
    _, body = mod.find_def(idtok)
    if body:
        m = re.match(r'OpFMul %float (%\w+) (%\w+)', body)
        if m: return [m.group(1), m.group(2)]
    return [idtok]

def classify_triples(mod, triples):
    """split into primary ((1-w)*albedo) and env (raw albedo) triples; map channels."""
    leafsets = []
    for t in triples:
        leaves = set()
        for mul in t['muls']: leaves.update(resolve_leaf(mod, mul))
        leafsets.append(leaves)
    # albedo ids = leaves shared by ALL triples
    common = set.intersection(*leafsets) if leafsets else set()
    if len(common) != 3:
        die(f"{mod.name}: expected 3 shared albedo ids across triples, got {sorted(common)}")
    # env triples use albedo directly; primary go through one FMul
    for t in triples:
        t['kind'] = 'env' if all(m in common for m in t['muls']) else 'primary'
    # channel labels: albedo order in the first env triple (r,g,b -- verified
    # against the light-color pairing in the disasm)
    env = next((t for t in triples if t['kind'] == 'env'), None)
    if not env: die(f"{mod.name}: no env triple found (channel order reference)")
    order = env['muls']           # r,g,b
    albedo = {i: a for i, a in enumerate(order)}   # channel 0=r,1=g,2=b -> id
    for t in triples:
        t['chan'] = []
        for mul in t['muls']:
            inter = set(resolve_leaf(mod, mul)) & common
            if len(inter) != 1:
                die(f"{mod.name}: cannot resolve channel for {mul} @line {t['line']+1}")
            t['chan'].append(order.index(sorted(inter)[0]))
    prim = [t for t in triples if t['kind'] == 'primary']
    return prim, [t for t in triples if t['kind'] == 'env'], albedo

def find_skin_gate(mod):
    """the G-buffer class==1 test (SSS_Blur's skin test), as a %bool id."""
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpIEqual %bool (%\d+) %uint_1\s*$', ln)
        if not m: continue
        _, sh = mod.find_def(m.group(2))
        if not sh: continue
        ms = re.match(r'OpShiftRightLogical %uint (%\d+) %uint_5', sh)
        if not ms: continue
        _, ex = mod.find_def(ms.group(1))
        if not ex: continue
        me = re.match(r'OpCompositeExtract %uint (%\d+) 1', ex)
        if not me: continue
        _, fe = mod.find_def(me.group(1))
        if fe and fe.startswith('OpImageFetch %v4uint'):
            return m.group(1)
    die(f"{mod.name}: skin gate (gbuf.y>>5 == 1) not found")

def trace_nol(mod, site_line, r_id):
    """r-channel diffuse value -> 3 FMul hops -> the NoL weight operand."""
    cur, line = r_id, site_line
    nol = None
    pat = re.compile(r'^\s*(%\d+)\s*=\s*OpFMul %float (%\w+) (%\w+)\s*$')
    for hop in range(3):
        found = None
        for j in range(line + 1, min(line + 60, len(mod.lines))):
            m = pat.match(mod.lines[j])
            if m and (m.group(2) == cur or m.group(3) == cur):
                other = m.group(3) if m.group(2) == cur else m.group(2)
                found = (j, m.group(1), other); break
        if not found: die(f"{mod.name}: NoL trace broke at hop {hop} after {cur}")
        line, cur, nol = found
    return nol

def find_nv(mod, site_line):
    """locate the NoV dot of the GGX block above the site and return the
    (N, V) component ids of its two OpCompositeConstruct operands.
    Rationale: the clamped NoV itself is computed inside a branch arm and
    does NOT dominate the diffuse-eval merge block (spirv-val dominance
    error on splice). The N/V components are defined early on the main
    path and dominate every eval site, so we recompute NoV at the splice.
    V is identified by its components being negations (OpFSub -0, x)."""
    eps_id = mod.fconst.get(f32(EPS))
    if not eps_id: die(f"{mod.name}: eps constant missing for NV detect")
    nmax = re.compile(r'^\s*(%\d+)\s*=\s*OpExtInst %float %\w+ NMax (%\d+) ' + re.escape(eps_id) + r'\s*$')
    dot_id = None
    for i in range(site_line - 1, max(site_line - 800, -1), -1):
        m = nmax.match(mod.lines[i])
        if not m: continue
        _, d = mod.find_def(m.group(2))
        if d and d.startswith('OpDot %float'):
            dot_id = m.group(2); break
    if not dot_id: die(f"{mod.name}: NoV dot above site @{site_line+1} not found")
    _, d = mod.find_def(dot_id)
    md = re.match(r'OpDot %float (%\d+) (%\d+)', d)
    comps = []
    for cid in (md.group(1), md.group(2)):
        _, c = mod.find_def(cid)
        mc = re.match(r'OpCompositeConstruct %v3float (%\d+) (%\d+) (%\d+)', c or '')
        if not mc: die(f"{mod.name}: dot operand {cid} is not a v3 construct")
        comps.append(list(mc.groups()))
    def is_negated(c3):
        for x in c3:
            _, b = mod.find_def(x)
            if not b or not re.match(r'OpFSub %float %\w+ %\w+', b): return False
        return True
    if is_negated(comps[1]) and not is_negated(comps[0]):
        return comps[0], comps[1]
    if is_negated(comps[0]) and not is_negated(comps[1]):
        return comps[1], comps[0]
    die(f"{mod.name}: cannot tell N from V at site @{site_line+1}")

# ------------------------------------------------------------- hair support
def find_class_shift(mod):
    """The `gbuf.y >> 5` material-class value, plus the line of the skin
    IEqual that consumes it.

    Same structural walk as find_skin_gate, but returns the shifted uint so a
    gate for any class value can be built from it. Inserting the new IEqual
    directly after the existing one inherits its dominance, which is what lets
    the hair gate reach every eval site the skin gate already reaches.
    """
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpIEqual %bool (%\d+) %uint_1\s*$', ln)
        if not m: continue
        _, sh = mod.find_def(m.group(2))
        if not sh: continue
        ms = re.match(r'OpShiftRightLogical %uint (%\d+) %uint_5', sh)
        if not ms: continue
        _, ex = mod.find_def(ms.group(1))
        if not ex: continue
        me = re.match(r'OpCompositeExtract %uint (%\d+) 1', ex)
        if not me: continue
        _, fe = mod.find_def(me.group(1))
        if fe and fe.startswith('OpImageFetch %v4uint'):
            return m.group(2), i
    die(f"{mod.name}: material-class shift (gbuf.y>>5) not found")


def find_ggx_sites(mod):
    """Locate every GGX specular eval by the pi in its denominator.

    Anchor chain: D = OpFDiv(a2, OpFMul(x, pi)); a2 = OpFMul(alpha, alpha);
    then the Vis*D product, then the three consecutive per-channel FMuls that
    produce F*D*Vis, then the Schlick pow5 shared by the three Fresnel FAdds.
    Sites whose structure does not match completely are skipped rather than
    guessed at.
    """
    pi = None
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float 3.14159274\b', ln)
        if m: pi = m.group(1); break
    if not pi: die(f"{mod.name}: pi constant not found")

    sites = []
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFDiv %float (%\d+) (%\d+)\s*$', ln)
        if not m: continue
        d_id, a2_id, den = m.groups()
        _, dn = mod.find_def(den)
        if not dn or not re.match(r'OpFMul %float %\d+ ' + re.escape(pi) + r'\s*$', dn):
            continue
        _, a2d = mod.find_def(a2_id)
        am = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', a2d or '')
        if not am or am.group(1) != am.group(2):
            continue
        alpha = am.group(1)
        a_line, _ = mod.find_def(alpha)
        # Vis*D: the unique FMul consuming D
        vd = None
        vpat = re.compile(r'^\s*(%\d+)\s*=\s*OpFMul %float (%\d+) (%\d+)\s*$')
        for j in range(i + 1, min(i + 80, len(mod.lines))):
            vm = vpat.match(mod.lines[j])
            if vm and d_id in (vm.group(2), vm.group(3)):
                vd = vm.group(1); break
        if not vd: continue
        # Outputs are every FMul consuming vd. spv_0170 expands Fresnel per
        # channel (three of them); spv_0171 has scalar sites with a single
        # output, so the count must not be assumed.
        outs = []
        for j in range(i + 1, min(i + 160, len(mod.lines))):
            vm = vpat.match(mod.lines[j])
            if vm and vm.group(1) != vd and vd in (vm.group(2), vm.group(3)):
                outs.append(vm.group(1))
        if not outs: continue
        # Schlick pow5 via the spherical-gaussian fit:
        #   Exp2( (-6.98316002 - VoH*5.55472994) * VoH )
        pow5 = None
        for j in range(max(0, i - 60), min(i + 160, len(mod.lines))):
            em = re.match(r'\s*(%\d+)\s*=\s*OpExtInst %float %\w+ Exp2 (%\d+)\s*$',
                          mod.lines[j])
            if not em: continue
            _, q = mod.find_def(em.group(2))
            qm = re.match(r'OpFMul %float (%\d+) (%\d+)\s*$', q or '')
            if not qm: continue
            for r in qm.groups():
                _, rd = mod.find_def(r)
                if rd and re.match(r'OpFSub %float %float_n6_98316002 %\d+', rd):
                    pow5 = em.group(1); break
            if pow5: break
        sites.append(dict(line=i, d=d_id, a2=a2_id, alpha=alpha,
                          alpha_line=a_line, vd=vd, outs=outs, pow5=pow5))
    return sites


def replace_all_uses(mod, old, new, after_line):
    """Rewrite every reference to %old below its definition to %new.

    Used for the roughness reshape, where the point is that BOTH the eval and
    the importance-sampling branch read the reshaped value -- if only the eval
    changed, sampling and evaluation would disagree and MIS would be biased.
    """
    tok = re.compile(r'(?<![%\w])' + re.escape(old) + r'(?![\w])')
    isdef = re.compile(r'^\s*' + re.escape(old) + r'\s*=')
    n = 0
    for j in range(after_line + 1, len(mod.lines)):
        if isdef.match(mod.lines[j]): continue
        ln2, k = tok.subn(new, mod.lines[j])
        if k:
            mod.lines[j] = ln2
            n += k
    return n


# ------------------------------------------------------- class hunt
# One build tints every candidate material class a different colour, so a
# single launch identifies hair by eye instead of one relaunch per candidate.
# Class 1 (skin) is included as a control: if skin does not come out red the
# harness itself is broken, and no conclusion about hair is trustworthy.
HUNT_PALETTE = {
    1:  ("red",     (3.0, 0.15, 0.15)),   # control -- skin, known
    2:  ("green",   (0.15, 3.0, 0.15)),
    3:  ("blue",    (0.15, 0.15, 3.0)),
    4:  ("yellow",  (3.0, 3.0, 0.15)),
    5:  ("magenta", (3.0, 0.15, 3.0)),
    6:  ("cyan",    (0.15, 3.0, 3.0)),
    7:  ("orange",  (3.0, 1.0, 0.15)),
    8:  ("violet",  (1.5, 0.15, 3.0)),
    13: ("azure",   (0.15, 1.5, 3.0)),
    14: ("lime",    (1.5, 3.0, 0.15)),
}
HUNT_DEFAULT = (1, 2, 3, 4, 5, 6, 7, 8, 13, 14)


def build_forcetint(mod, triples, knobs):
    """Unconditional tint at EVERY triple -- no gate, no class test.

    Bisects a null result: if the screen does not change with this loaded,
    the raygen is not executing (path tracing off, or a different raygen in
    use) and no gated result can ever be trusted. If it does change, the
    shader runs and the problem is the gate or the class value.

    Also tints the env triples, which the class hunt leaves alone, so a scene
    lit mainly by the env path still shows it.
    """
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    tint = [C(x) for x in knobs["tint"]]
    for t in triples:
        ins, newids = [], []
        for k, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {tint[t['chan'][k]]}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'forcetint')
    return consts, edits, {"triples": len(triples), "tint": list(knobs["tint"])}


def build_hairhunt(mod, prim, shift, classes, knobs):
    """Tint each candidate class its palette colour at the diffuse triples.

    Emits one OpIEqual per candidate next to the skin gate (inheriting its
    dominance), then a chain of OpSelects per channel that resolves to the
    matching class's tint, or 1.0 when nothing matches.
    """
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    one = C(1.0)
    _, ieq_line = find_class_shift(mod)

    gates, legend = [], []
    ginst = []
    for n in classes:
        if n not in HUNT_PALETTE:
            die(f"class {n} has no palette entry; extend HUNT_PALETTE")
        name, rgb = HUNT_PALETTE[n]
        uid, udecl = mod.uconst(n)
        if udecl: consts.append(udecl)
        g = mod.new_id()
        ginst.append(f"        {g} = OpIEqual %bool {shift} {uid}")
        gates.append((g, [C(x) for x in rgb]))
        legend.append({"class": n, "colour": name, "tint": list(rgb)})
    edits.append((ieq_line, ginst))

    for t in prim:
        ins, newids = [], []
        # per-channel select chain, shared across the three components
        chan_val = {}
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                nid = mod.new_id()
                ins.append(f"        {nid} = OpSelect %float {g} {rgb[ch]} {cur}")
                cur = nid
            chan_val[ch] = cur
        for k, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {chan_val[t['chan'][k]]}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'hairhunt')
    return consts, edits, {"legend": legend, "triples": len(prim)}


# ---------------------------------------------- structure-tensor tangent
def find_normal_gbuffer(mod):
    """Locate the screen-space normal G-buffer fetch and everything needed to
    re-emit fetches of it at arbitrary coordinates.

    Anchor: the ImageFetch %v4float whose components go through the
    (x - 0.5) octahedral-free decode (three FAdd %float_n0_5) -- that is the
    normal buffer (SRV registers[1]+2). The descriptor chain and the pixel
    coordinate ids are read off the found instructions so nothing is
    hardcoded per module.
    """
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\d+)\s*=\s*OpImageFetch %v4float (%\d+) (%\d+)'
                     r' Lod (%\w+)\s*$', ln)
        if not m: continue
        fid, img, coord, lod = m.groups()
        exts = set()
        for j in range(i + 1, min(i + 8, len(mod.lines))):
            mm = re.match(r'\s*(%\d+)\s*=\s*OpCompositeExtract %float '
                          + re.escape(fid) + r' \d\s*$', mod.lines[j])
            if mm: exts.add(mm.group(1))
        hits = 0
        for j in range(i + 1, min(i + 16, len(mod.lines))):
            mm = re.match(r'\s*%\d+\s*=\s*OpFAdd %float (%\d+) %float_n0_5\s*$',
                          mod.lines[j])
            if mm and mm.group(1) in exts: hits += 1
        if hits < 3: continue
        _, imgd = mod.find_def(img)
        mi = re.match(r'OpLoad (%\w+) (%\d+)', imgd or '')
        if not mi: continue
        imgty, ac = mi.groups()
        _, acd = mod.find_def(ac)
        ma = re.match(r'OpAccessChain (%\w+) (%\d+) (%\d+)', acd or '')
        if not ma: continue
        ptrty, arr, slot = ma.groups()
        _, sd = mod.find_def(slot)
        ms = re.match(r'OpIAdd %uint (%\d+) (%\w+)', sd or '')
        if not ms: continue
        _, bd = mod.find_def(ms.group(1))
        mb = re.match(r'OpLoad %uint (%\d+)', bd or '')
        if not mb: continue
        _, pcd = mod.find_def(mb.group(1))
        mp = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+)', pcd or '')
        if not mp: continue
        _, cd = mod.find_def(coord)
        mc = re.match(r'OpCompositeConstruct %v2uint (%\d+) (%\d+)', cd or '')
        if not mc: continue
        return dict(imgty=imgty, ptrty=ptrty, arr=arr, off=ms.group(2),
                    pcty=mp.group(1), regs=mp.group(2), idx=mp.group(3),
                    lod=lod, x=mc.group(1), y=mc.group(2), line=i)
    die(f"{mod.name}: normal G-buffer fetch (rgb-0.5 decode) not found")


def emit_nfetch(mod, ctx, xid, yid, ins):
    """Fetch the normal buffer at (xid, yid); returns the 3 decoded
    (value - 0.5) component ids. Deliberately not normalized: the tensor is a
    ratio and normalization cancels; T is normalized at the end."""
    I = mod.new_id
    a, b, c, d, e, cc, f = [I() for _ in range(7)]
    ins += [
        f"        {a} = OpAccessChain {ctx['pcty']} {ctx['regs']} {ctx['idx']}",
        f"        {b} = OpLoad %uint {a}",
        f"        {c} = OpIAdd %uint {b} {ctx['off']}",
        f"        {d} = OpAccessChain {ctx['ptrty']} {ctx['arr']} {c}",
        f"        {e} = OpLoad {ctx['imgty']} {d}",
        f"        {cc} = OpCompositeConstruct %v2uint {xid} {yid}",
        f"        {f} = OpImageFetch %v4float {e} {cc} Lod {ctx['lod']}",
    ]
    out = []
    for ch in range(3):
        g, h = I(), I()
        ins.append(f"        {g} = OpCompositeExtract %float {f} {ch}")
        ins.append(f"        {h} = OpFAdd %float {g} %float_n0_5")
        out.append(h)
    return out


def emit_aniso(mod, ctx, C, want_tangent):
    """Structure tensor of the normal field at the current pixel.

    Normals rotate fast across a fibre and stay near-constant along it, so
    the minor eigenvector of J = sum(grad N grad N^T) over the neighbourhood
    is the projected strand direction, and (l1-l2)/(l1+l2) measures how
    fibre-like the neighbourhood is. Central differences, closed-form 2x2
    eigen -- no loops, no branches, safe to splice anywhere the coordinate
    ids dominate.

    Returns (instructions, {aniso, T?}). T = normalize(cross(Nc, w)) where w
    is the world-space direction of maximal normal change (gx,gy combined by
    the major eigenvector), i.e. across the strand; crossing with the centre
    normal turns it into the along-strand direction.
    """
    I = mod.new_id
    ins = []
    gl = mod.glsl
    x, y = ctx['x'], ctx['y']
    xp, xm, yp, ym = [I() for _ in range(4)]
    ins += [
        f"        {xp} = OpIAdd %uint {x} %uint_1",
        f"        {xm} = OpISub %uint {x} %uint_1",
        f"        {yp} = OpIAdd %uint {y} %uint_1",
        f"        {ym} = OpISub %uint {y} %uint_1",
    ]
    nxp = emit_nfetch(mod, ctx, xp, y, ins)
    nxm = emit_nfetch(mod, ctx, xm, y, ins)
    nyp = emit_nfetch(mod, ctx, x, yp, ins)
    nym = emit_nfetch(mod, ctx, x, ym, ins)
    gx, gy = [], []
    for ch in range(3):
        g1, g2 = I(), I()
        ins.append(f"        {g1} = OpFSub %float {nxp[ch]} {nxm[ch]}")
        ins.append(f"        {g2} = OpFSub %float {nyp[ch]} {nym[ch]}")
        gx.append(g1); gy.append(g2)

    def dot3(u, v):
        t1, t2, t3, s1, s2 = [I() for _ in range(5)]
        ins.extend([
            f"        {t1} = OpFMul %float {u[0]} {v[0]}",
            f"        {t2} = OpFMul %float {u[1]} {v[1]}",
            f"        {t3} = OpFMul %float {u[2]} {v[2]}",
            f"        {s1} = OpFAdd %float {t1} {t2}",
            f"        {s2} = OpFAdd %float {s1} {t3}",
        ])
        return s2

    a, b, d = dot3(gx, gx), dot3(gx, gy), dot3(gy, gy)
    quarter, eps, two, half = C(0.25), C(1e-6), C(2.0), C(0.5)
    amd, h2, b2, q, r2, r, tr, tre, twor, aniso = [I() for _ in range(10)]
    ins += [
        f"        {amd} = OpFSub %float {a} {d}",
        f"        {h2} = OpFMul %float {amd} {amd}",
        f"        {b2} = OpFMul %float {b} {b}",
        f"        {q} = OpFMul %float {h2} {quarter}",
        f"        {r2} = OpFAdd %float {q} {b2}",
        f"        {r} = OpExtInst %float {gl} Sqrt {r2}",
        f"        {tr} = OpFAdd %float {a} {d}",
        f"        {tre} = OpFAdd %float {tr} {eps}",
        f"        {twor} = OpFMul %float {r} {two}",
        f"        {aniso} = OpFDiv %float {twor} {tre}",
    ]
    out = {"aniso": aniso}
    if want_tangent:
        nc = emit_nfetch(mod, ctx, x, y, ins)
        # Major eigenvector of J. Both row forms of (J - l2*I) are valid
        # eigenvectors: (l1-d, b) and (b, l1-a); each degenerates to zero when
        # the major axis aligns with a coordinate axis (b=0), but never both
        # at once -- pick the longer one branchlessly.
        t_, l1, e1x, e2y = [I() for _ in range(4)]
        m1s, m2s, gtc, vx, vy = [I() for _ in range(5)]
        ins += [
            f"        {t_} = OpFMul %float {tr} {half}",
            f"        {l1} = OpFAdd %float {t_} {r}",
            f"        {e1x} = OpFSub %float {l1} {d}",
            f"        {e2y} = OpFSub %float {l1} {a}",
            f"        {m1s} = OpFMul %float {e1x} {e1x}",
            f"        {m2s} = OpFMul %float {e2y} {e2y}",
            f"        {gtc} = OpFOrdGreaterThan %bool {m1s} {m2s}",
            f"        {vx} = OpSelect %float {gtc} {e1x} {b}",
            f"        {vy} = OpSelect %float {gtc} {b} {e2y}",
        ]
        w = []
        for ch in range(3):
            u1, u2, u3 = I(), I(), I()
            ins += [
                f"        {u1} = OpFMul %float {gx[ch]} {vx}",
                f"        {u2} = OpFMul %float {gy[ch]} {vy}",
                f"        {u3} = OpFAdd %float {u1} {u2}",
            ]
            w.append(u3)
        vn, vw, cr = I(), I(), I()
        ins += [
            f"        {vn} = OpCompositeConstruct %v3float {nc[0]} {nc[1]} {nc[2]}",
            f"        {vw} = OpCompositeConstruct %v3float {w[0]} {w[1]} {w[2]}",
            f"        {cr} = OpExtInst %v3float {gl} Cross {vn} {vw}",
        ]
        tc = []
        for ch in range(3):
            e_ = I()
            ins.append(f"        {e_} = OpCompositeExtract %float {cr} {ch}")
            tc.append(e_)
        dd = dot3(tc, tc)
        dde, inv = I(), I()
        ins += [
            f"        {dde} = OpFAdd %float {dd} {eps}",
            f"        {inv} = OpExtInst %float {gl} InverseSqrt {dde}",
        ]
        out["T"] = []
        for ch in range(3):
            n_ = I()
            ins.append(f"        {n_} = OpFMul %float {tc[ch]} {inv}")
            out["T"].append(n_)
    return ins, out


def build_hairdbg(mod, prim, gate, knobs):
    """Paint the tensor confidence onto hair diffuse: red = no usable strand
    direction, green = strong one. The go/no-go diagnostic for anisotropy."""
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    ctx = find_normal_gbuffer(mod)
    one, kd = C(1.0), C(knobs["kd_dbg"])
    blue = C(knobs["kd_dbg"] * 0.05)
    for t in prim:
        ins, res = emit_aniso(mod, ctx, C, want_tangent=False)
        I = mod.new_id
        ia, rm, gm = I(), I(), I()
        ins += [
            f"        {ia} = OpFSub %float {one} {res['aniso']}",
            f"        {rm} = OpFMul %float {ia} {kd}",
            f"        {gm} = OpFMul %float {res['aniso']} {kd}",
        ]
        tint = {0: rm, 1: gm, 2: blue}
        newids = []
        for k, vid in enumerate(t['ids']):
            s, n = I(), I()
            ins.append(f"        {s} = OpSelect %float {gate} {tint[t['chan'][k]]} {one}")
            ins.append(f"        {n} = OpFMul %float {vid} {s}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'hairdbg')
    return consts, edits, dict(ctx_line=ctx['line'] + 1, triples=len(prim))


def find_site_nh(mod, site):
    """The N and H component ids at a GGX site, via the NoH chain:
    den = NoH^2*(a2-1)+1 -> NoH -> OpDot(N-construct, H-construct).
    H is the construct built nearest the site (L+V is site-local; N is not).
    """
    lo = max(0, site['line'] - 80)
    am1 = None
    for j in range(lo, site['line']):
        m = re.match(r'\s*(%\d+)\s*=\s*OpFAdd %float ' + re.escape(site['a2'])
                     + r' %float_n1\s*$', mod.lines[j])
        if m: am1 = m.group(1); break
    if not am1: return None
    sq = None
    for j in range(lo, site['line']):
        m = re.match(r'\s*%\d+\s*=\s*OpFMul %float (%\d+) ' + re.escape(am1)
                     + r'\s*$', mod.lines[j])
        if m: sq = m.group(1); break
    if not sq: return None
    _, d1 = mod.find_def(sq)
    m = re.match(r'OpFMul %float (%\d+) \1\s*$', d1 or '')
    if not m: return None
    c = m.group(1)
    for _ in range(3):
        _, dd = mod.find_def(c)
        mm = re.match(r'OpExtInst %float %\w+ NClamp (%\d+) ', dd or '')
        if not mm: break
        c = mm.group(1)
    _, dd = mod.find_def(c)
    md = re.match(r'OpDot %float (%\d+) (%\d+)', dd or '')
    if not md: return None
    built = []
    for cid in md.groups():
        ln, cdf = mod.find_def(cid)
        mc = re.match(r'OpCompositeConstruct %v3float (%\d+) (%\d+) (%\d+)', cdf or '')
        if not mc: return None
        built.append((ln, list(mc.groups())))
    built.sort(key=lambda t: t[0])
    return dict(n=built[0][1], h=built[1][1])


def build_hairaniso(mod, sites, gate, knobs):
    """Kajiya-Kay-flavoured spec modulation from the estimated tangent:
        factor = 1 + m_aniso * aniso * (sin(T,H)^p - 1)
    scaled by the tensor confidence so pixels with no strand signal stay at
    exactly 1. m_aniso=0 is the identity."""
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    ctx = find_normal_gbuffer(mod)
    one, eps2 = C(1.0), C(1e-4)
    mkn, pex = C(knobs["m_aniso"]), C(knobs["p_aniso"] * 0.5)
    gl = mod.glsl
    rep = {"aniso_sites": 0, "skipped_no_nh": 0}
    for s in sites:
        nh = find_site_nh(mod, s)
        if not nh:
            rep["skipped_no_nh"] += 1
            continue
        ins, res = emit_aniso(mod, ctx, C, want_tangent=True)
        T = res["T"]
        I = mod.new_id
        m1, m2, m3, a1, toh = [I() for _ in range(5)]
        ins += [
            f"        {m1} = OpFMul %float {T[0]} {nh['h'][0]}",
            f"        {m2} = OpFMul %float {T[1]} {nh['h'][1]}",
            f"        {m3} = OpFMul %float {T[2]} {nh['h'][2]}",
            f"        {a1} = OpFAdd %float {m1} {m2}",
            f"        {toh} = OpFAdd %float {a1} {m3}",
        ]
        t2, f_, fm, lg, ex, sv, sm1, ma, term, fac, sel = [I() for _ in range(11)]
        ins += [
            f"        {t2} = OpFMul %float {toh} {toh}",
            f"        {f_} = OpFSub %float {one} {t2}",
            f"        {fm} = OpExtInst %float {gl} NMax {f_} {eps2}",
            f"        {lg} = OpExtInst %float {gl} Log2 {fm}",
            f"        {ex} = OpFMul %float {lg} {pex}",
            f"        {sv} = OpExtInst %float {gl} Exp2 {ex}",
            f"        {sm1} = OpFSub %float {sv} {one}",
            f"        {ma} = OpFMul %float {mkn} {res['aniso']}",
            f"        {term} = OpFMul %float {ma} {sm1}",
            f"        {fac} = OpFAdd %float {one} {term}",
            f"        {sel} = OpSelect %float {gate} {fac} {one}",
        ]
        last_out = max(mod.find_def(o)[0] for o in s['outs'])
        for o in s['outs']:
            n = I()
            ins.append(f"        {n} = OpFMul %float {o} {sel}")
            replace_all_uses(mod, o, n, last_out)
        edits.append((last_out, ins))
        rep["aniso_sites"] += 1
    return consts, edits, rep


def build_hair_spec(mod, sites, gate, knobs):
    """Idea 2: roughness reshape at the common alpha + gated sheen on F."""
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    one, zero = C(1.0), C(0.0)
    s_h, a_min, k_sh = C(knobs["s_h"]), C(knobs["a_min"]), C(knobs["k_sheen"])
    gl = mod.glsl
    rep = {"alphas": [], "sheen_sites": 0, "skipped_no_pow5": 0}

    # --- 2a: one reshape per distinct alpha source, all uses rewritten
    for alpha in sorted({s['alpha'] for s in sites},
                        key=lambda a: mod.find_def(a)[0]):
        aline, _ = mod.find_def(alpha)
        I = mod.new_id
        sc, cl, sel = I(), I(), I()
        # Replace first, then insert: the new block must keep referring to the
        # original alpha, so it is written after the rewrite has happened.
        replace_all_uses(mod, alpha, sel, aline)
        # apply_edits inserts at pos+1, so pos=aline puts the block directly
        # after alpha's definition -- it reads alpha, so it cannot precede it.
        edits.append((aline, [
            f"        {sc} = OpFMul %float {alpha} {s_h}",
            f"        {cl} = OpExtInst %float {gl} NClamp {sc} {a_min} {one}",
            f"        {sel} = OpSelect %float {gate} {cl} {alpha}",
        ]))
        rep["alphas"].append({"alpha": alpha, "line": aline + 1, "sel": sel})

    # --- 2b: sheen added to the Fresnel term, per site.
    # Each output is F*vd, so adding sheen to F is the same as adding
    # sheen*vd to the output; clamping the result to vd is exactly the F<=1
    # clamp, since vd is what F=1 would produce. Working on outputs instead of
    # on F ids keeps this valid for both the per-channel and the scalar sites.
    for s in sites:
        if not s['pow5']:
            rep["skipped_no_pow5"] += 1
            continue
        I = mod.new_id
        sh, sel, add = I(), I(), I()
        ins = [
            f"        {sh} = OpFMul %float {s['pow5']} {k_sh}",
            f"        {sel} = OpSelect %float {gate} {sh} {zero}",
            f"        {add} = OpFMul %float {sel} {s['vd']}",
        ]
        last_out = max(mod.find_def(o)[0] for o in s['outs'])
        for o in s['outs']:
            a, b, c = I(), I(), I()
            ins.append(f"        {a} = OpFAdd %float {o} {add}")
            ins.append(f"        {b} = OpExtInst %float {gl} NMin {a} {s['vd']}")
            # Select on the gate rather than relying on add==0: the clamp to vd
            # is only a no-op where out <= vd, which holds for F*vd with F<=1
            # but is not guaranteed for every site this matches generically.
            # Gating makes every non-hair pixel bit-exact by construction.
            ins.append(f"        {c} = OpSelect %float {gate} {b} {o}")
            replace_all_uses(mod, o, c, last_out)
        edits.append((last_out, ins))
        rep["sheen_sites"] += 1
        rep["out_counts"] = rep.get("out_counts", []) + [len(s['outs'])]
    return consts, edits, rep


def emit_wrap_factor(mod, t, gate, K, C):
    """Idea 3: energy-normalized diffuse wrap, as a ratio.

    NoL is already folded into the site's light weight, so the factor spliced
    here is wrap/NoL rather than wrap itself -- multiplying by the wrap term
    directly would apply the cosine twice.

        wrap  = sat((NoL + w) / (1 + w)) / (1 + w)
        ratio = min(wrap / max(NoL, 1e-3), r_max)

    At w=0 this is NoL/max(NoL,1e-3) = 1 for NoL >= 1e-3; below that the
    diffuse term is ~0 anyway, so w=0 is a visual identity (not bit-exact).
    """
    one, zero = C(1.0), C(0.0)
    w = K["w_wrap"]
    wk, inv = C(w), C(1.0 / (1.0 + w))
    e3, rmax = C(1e-3), C(K["r_max"])
    gl = mod.glsl
    r_ch = t['chan'].index(0)
    nol = trace_nol(mod, t['line'], t['ids'][r_ch])
    I = mod.new_id
    s1, s2, s3, s4, s5, s6, s7, g = [I() for _ in range(8)]
    ins = [
        f"        {s1} = OpFAdd %float {nol} {wk}",
        f"        {s2} = OpFMul %float {s1} {inv}",
        f"        {s3} = OpExtInst %float {gl} NClamp {s2} {zero} {one}",
        f"        {s4} = OpFMul %float {s3} {inv}",
        f"        {s5} = OpExtInst %float {gl} NMax {nol} {e3}",
        f"        {s6} = OpFDiv %float {s4} {s5}",
        f"        {s7} = OpExtInst %float {gl} NMin {s6} {rmax}",
        f"        {g} = OpSelect %float {gate} {s7} {one}",
    ]
    return ins, g


def build_diffuse(mod, prim, skin_gate, hair_gate, knobs, do_c1, do_wrap):
    """Multiply each primary triple by the product of every enabled factor.

    Skin c1 and hair wrap target the same three values, so they are combined
    into one multiply per channel here. Their gates are disjoint material
    classes and each factor is 1.0 when its gate is false, so the product is
    correct regardless of order.
    """
    consts, edits, report = [], [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    for t in prim:
        ins, factors, info = [], [], {"line": t['line'] + 1}
        if do_c1:
            i1, g1, meta = emit_c1_factor(mod, t, skin_gate, knobs, C)
            ins += i1; factors.append(g1); info["c1"] = meta["nol"]
        if do_wrap:
            i2, g2 = emit_wrap_factor(mod, t, hair_gate, knobs, C)
            ins += i2; factors.append(g2); info["wrap"] = g2
        f = factors[0]
        for extra in factors[1:]:
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {f} {extra}")
            f = n
        newids = []
        for vid in t['ids']:
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {f}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'diffuse')
        report.append(info)
    return consts, edits, report


def replace_single_use(mod, old, new, after_line, context):
    """rewrite the unique `= OpFMul` use of %old after after_line to %new."""
    pat = re.compile(r'(= OpFMul %float %\w+ )' + re.escape(old) + r'\s*$')
    pat2 = re.compile(r'(= OpFMul %float )' + re.escape(old) + r'( %\w+\s*)$')
    isdef = re.compile(r'^\s*' + re.escape(old) + r'\s*=')
    hits = []
    for j in range(after_line, len(mod.lines)):
        ln = mod.lines[j]
        if isdef.match(ln): continue
        if re.search(re.escape(old) + r'\b', ln) and '= OpFMul' in ln:
            hits.append(j)
    if len(hits) != 1:
        die(f"{mod.name}: expected 1 FMul use of {old} ({context}), found {len(hits)}")
    j = hits[0]
    ln2, nsub = pat.subn(r'\g<1>' + new, mod.lines[j])
    if not nsub: ln2, nsub = pat2.subn(r'\g<1>' + new + r'\g<2>', mod.lines[j])
    if not nsub: die(f"{mod.name}: use rewrite failed for {old} @line {j+1}")
    mod.lines[j] = ln2

# ------------------------------------------------------------- splicing
def build_smoke(mod, triples, gate, knobs):
    consts, edits = [], []
    one, c = mod.const(1.0); consts += [c] if c else []
    tids = []
    for t in knobs["tint"]:
        tid, c = mod.const(t); consts += [c] if c else []; tids.append(tid)
    for t in triples:
        ins = []
        sels = []
        for ch in range(3):
            s = mod.new_id()
            ins.append(f"        {s} = OpSelect %float {gate} {tids[ch]} {one}")
            sels.append(s)
        newids = []
        for k, vid in enumerate(t['ids']):
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {sels[t['chan'][k]]}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))   # insert after 3rd line of triple
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'smoke')
    return consts, edits

def emit_c1_factor(mod, t, gate, K, C):
    """Tier-1 c1 for one triple. Returns (instructions, factor_id, info).

    Factored out of build_tier1 so hair tiers can multiply their own gated
    factor into the same triple without two passes fighting over the same
    single FMul use. Emits identical instructions to the original inline
    version -- tier1 output must stay byte-identical.
    """
    one, zero, eps = C(1.0), C(0.0), C(EPS)
    # r(x)=2(1-x); exponent = 5*r = 10*(1-x)
    e_ef = C(10.0 * (1.0 - K["n_f"]))
    e_tf = C(10.0 * (1.0 - K["m_f"]))
    e_er = C(10.0 * (1.0 - K["n_r"]))
    e_tr = C(10.0 * (1.0 - K["m_r"]))
    rf, rr = C(K["rho_f"]), C(K["rho_r"])
    gl = mod.glsl
    r_ch = t['chan'].index(0)            # position of the r-channel value
    nol = trace_nol(mod, t['line'], t['ids'][r_ch])
    n_ids, v_ids = find_nv(mod, t['line'])
    I = mod.new_id
    nv0, nv1, nv2, nv3, nv4, nov = I(), I(), I(), I(), I(), I()
    onl, onv, b1, b2, b3, b4 = I(), I(), I(), I(), I(), I()
    l1, l2, l3, l4 = I(), I(), I(), I()
    x1, x2, x3, x4 = I(), I(), I(), I()
    p1, p2, p3, p4 = I(), I(), I(), I()
    af, ar, df, dr, tf, tr, cf, cr, c1, g = [I() for _ in range(10)]
    ins = [
        f"        {nv0} = OpFMul %float {n_ids[0]} {v_ids[0]}",
        f"        {nv1} = OpFMul %float {n_ids[1]} {v_ids[1]}",
        f"        {nv2} = OpFMul %float {n_ids[2]} {v_ids[2]}",
        f"        {nv3} = OpFAdd %float {nv0} {nv1}",
        f"        {nv4} = OpFAdd %float {nv3} {nv2}",
        f"        {nov} = OpExtInst %float {gl} NClamp {nv4} {zero} {one}",
        f"        {onl} = OpFSub %float {one} {nol}",
        f"        {onv} = OpFSub %float {one} {nov}",
        f"        {b1} = OpExtInst %float {gl} NMax {onl} {eps}",
        f"        {b2} = OpExtInst %float {gl} NMax {onv} {eps}",
        f"        {b3} = OpExtInst %float {gl} NMax {nol} {eps}",
        f"        {b4} = OpExtInst %float {gl} NMax {nov} {eps}",
        f"        {l1} = OpExtInst %float {gl} Log2 {b1}",
        f"        {l2} = OpExtInst %float {gl} Log2 {b2}",
        f"        {l3} = OpExtInst %float {gl} Log2 {b3}",
        f"        {l4} = OpExtInst %float {gl} Log2 {b4}",
        f"        {x1} = OpFMul %float {l1} {e_ef}",
        f"        {x2} = OpFMul %float {l2} {e_tf}",
        f"        {x3} = OpExtInst %float {gl} Exp2 {x1}",
        f"        {x4} = OpExtInst %float {gl} Exp2 {x2}",
        f"        {af} = OpFMul %float {x3} {x4}",
        f"        {p1} = OpFMul %float {l4} {e_er}",
        f"        {p2} = OpFMul %float {l3} {e_tr}",
        f"        {p3} = OpExtInst %float {gl} Exp2 {p1}",
        f"        {p4} = OpExtInst %float {gl} Exp2 {p2}",
        f"        {ar} = OpFMul %float {p3} {p4}",
        f"        {df} = OpFSub %float {rf} {one}",
        f"        {dr} = OpFSub %float {rr} {one}",
        f"        {tf} = OpFMul %float {df} {af}",
        f"        {tr} = OpFMul %float {dr} {ar}",
        f"        {cf} = OpFAdd %float {one} {tf}",
        f"        {cr} = OpFAdd %float {one} {tr}",
        f"        {c1} = OpFMul %float {cf} {cr}",
        f"        {g} = OpSelect %float {gate} {c1} {one}",
    ]
    return ins, g, dict(line=t['line'] + 1, nol=nol, n=n_ids, v=v_ids,
                        ids=t['ids'])


def build_tier1(mod, prim, gate, knobs):
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    report = []
    for t in prim:
        ins, g, info = emit_c1_factor(mod, t, gate, knobs, C)
        newids = []
        for vid in t['ids']:
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {vid} {g}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'tier1')
        report.append(info)
    return consts, edits, report

def apply_edits(mod, consts, edits):
    # insert constants before first OpFunction
    fidx = next(i for i, ln in enumerate(mod.lines) if ' OpFunction ' in ln)
    mod.lines[fidx:fidx] = consts
    # apply instruction insertions bottom-up so line indices stay valid
    for pos, ins in sorted(edits, key=lambda e: -e[0]):
        # recompute position: consts shifted everything below fidx
        shift = len(consts) if pos >= fidx else 0
        mod.lines[pos + shift + 1:pos + shift + 1] = ins

# ------------------------------------------------------------- driver
def roundtrip_check(spvasm, target_env):
    """the unmodified disasm must reassemble + validate (sanity of tooling)."""
    tmp = spvasm + '.rt.spv'
    r = subprocess.run(['spirv-as', '--target-env', target_env, spvasm, '-o', tmp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"spirv-as failed on UNPATCHED {spvasm}:\n{r.stderr}")
    v = subprocess.run(['spirv-val', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if v.returncode != 0:
        die(f"spirv-val failed on UNPATCHED {spvasm}:\n{v.stderr}")

HAIR_TIERS = ('hair2', 'hair3', 'hair23', 'hairdbg', 'hairaniso')


def process(path, outdir, tier, knobs, target_env, do_rt=True,
            hair_class=None, with_tier1=False, hunt_classes=None):
    mod = Module(path)
    if not mod.dxil: die(f"{mod.name}: no dxil hash in OpString")
    if do_rt: roundtrip_check(path, target_env)
    gate = find_skin_gate(mod)
    triples = find_triples(mod)
    if len(triples) < 6:
        die(f"{mod.name}: expected >=6 diffuse triples, found {len(triples)}")
    prim, env, albedo = classify_triples(mod, triples)
    rep = dict(module=mod.name, dxil=mod.dxil, ident=mod.ident, gate=gate, tier=tier,
               triples=len(triples), primary=len(prim), env=len(env),
               albedo={c: albedo[c] for c in sorted(albedo)})
    if tier == 'smoke':
        # With --hair-class N the tint is gated on class N instead of skin.
        # This is the class-discovery loop: cycle N until hair turns red.
        consts, edits = [], []
        sgate = gate
        if hair_class is not None:
            shift, ieq_line = find_class_shift(mod)
            uid, udecl = mod.uconst(hair_class)
            sgate = mod.new_id()
            if udecl: consts.append(udecl)
            edits.append((ieq_line,
                          [f"        {sgate} = OpIEqual %bool {shift} {uid}"]))
            rep.update(smoke_class=hair_class, smoke_gate=sgate)
        c, e = build_smoke(mod, triples, sgate, knobs)
        consts += c; edits += e
        rep['tint'] = knobs['tint']
    elif tier == '1':
        consts, edits, rep['sites'] = build_tier1(mod, prim, gate, knobs)
        rep['params'] = {k: knobs[k] for k in ('rho_f','n_f','m_f','rho_r','n_r','m_r')}
    elif tier == 'forcetint':
        consts, edits, rep['force'] = build_forcetint(mod, triples, knobs)
    elif tier == 'hairhunt':
        shift, _ = find_class_shift(mod)
        consts, edits, rep['hunt'] = build_hairhunt(
            mod, prim, shift, hunt_classes or HUNT_DEFAULT, knobs)
    elif tier in HAIR_TIERS:
        if hair_class is None:
            die("hair tiers need --hair-class N (the gbuffer material class "
                "for hair). It is not yet identified -- see "
                "dev/HAIR_HANDOFF.md section 1 for how to find it.")
        shift, ieq_line = find_class_shift(mod)
        uid, udecl = mod.uconst(hair_class)
        hgate = mod.new_id()
        consts, edits = ([udecl] if udecl else []), []
        # Placed directly after the skin IEqual so it inherits that block's
        # dominance over every eval site.
        edits.append((ieq_line, [f"        {hgate} = OpIEqual %bool {shift} {uid}"]))
        rep.update(hair_class=hair_class, hair_gate=hgate, shift=shift,
                   with_tier1=with_tier1)
        if tier in ('hair2', 'hair23'):
            sites = find_ggx_sites(mod)
            if not sites: die(f"{mod.name}: no GGX specular sites found")
            c2, e2, rep['spec'] = build_hair_spec(mod, sites, hgate, knobs)
            consts += c2; edits += e2
            rep['spec']['sites_found'] = len(sites)
        if tier == 'hairdbg':
            cD, eD, rep['dbg'] = build_hairdbg(mod, prim, hgate, knobs)
            consts += cD; edits += eD
        if tier == 'hairaniso':
            sites = find_ggx_sites(mod)
            if not sites: die(f"{mod.name}: no GGX specular sites found")
            cA, eA, rep['aniso'] = build_hairaniso(mod, sites, hgate, knobs)
            consts += cA; edits += eA
            rep['aniso']['sites_found'] = len(sites)
        do_wrap = tier in ('hair3', 'hair23')
        if do_wrap or with_tier1:
            c3, e3, rep['diffuse'] = build_diffuse(
                mod, prim, gate, hgate, knobs, with_tier1, do_wrap)
            consts += c3; edits += e3
        rep['params'] = {k: knobs[k] for k in
                         ('s_h', 'a_min', 'k_sheen', 'w_wrap', 'r_max')}
        if with_tier1:
            rep['params'].update({k: knobs[k] for k in
                                  ('rho_f','n_f','m_f','rho_r','n_r','m_r')})
    else:
        die(f"unknown tier {tier}")
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
    rep['spirv_val'] = 'clean' if v.returncode == 0 else 'FAIL'
    if v.returncode != 0:
        open(spv_out + '.val.log', 'w').write(v.stderr)
        die(f"spirv-val FAILED on PATCHED {mod.name} (see {spv_out}.val.log):\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    rep['out'] = spv_out
    return rep

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+', help='input .spvasm files')
    ap.add_argument('--tier',
                    choices=['smoke', '1', 'hairhunt', 'forcetint']
                            + list(HAIR_TIERS),
                    default='smoke')
    ap.add_argument('--classes', default=None,
                    help='hairhunt: comma-separated candidate classes '
                         '(default %s). Class 1 is skin and acts as the '
                         'control.' % ','.join(map(str, HUNT_DEFAULT)))
    ap.add_argument('--hair-class', type=int, default=None, metavar='N',
                    help='gbuffer material class for hair (required by hair '
                         'tiers; skin is 1). Cycle candidates with --tier '
                         'smoke to identify it.')
    ap.add_argument('--with-tier1', action='store_true',
                    help='also apply the skin c1 splice, combined into the '
                         'same per-triple multiply (use to keep the shipped '
                         'skin look while adding hair)')
    ap.add_argument('--vanilla', action='store_true',
                    help='force all params to defaults (bit-identical regression)')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--target-env', default='spv1.4')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    ap.add_argument('--set', action='append', default=[], metavar='K=V',
                    help='override a knob (tint_r/rho_f/n_f/m_f/rho_r/n_r/m_r)')
    a = ap.parse_args()
    knobs = dict(VANILLA if a.vanilla else KNOBS)
    knobs['tint'] = tuple(VANILLA['tint'] if a.vanilla else KNOBS['tint'])
    for kv in a.set:
        k, v = kv.split('=')
        if k.startswith('tint_'):
            t = list(knobs['tint']); t['rgb'.index(k[-1])] = float(v)
            knobs['tint'] = tuple(t)
        elif k in knobs and k != 'tint':
            knobs[k] = float(v)
        else:
            die(f"unknown knob {k}")
    hunt = None
    if a.classes:
        hunt = [int(x) for x in a.classes.split(',') if x.strip()]
    reports = []
    for p in a.modules:
        reports.append(process(p, a.outdir, a.tier, knobs, a.target_env,
                               do_rt=not a.no_roundtrip_check,
                               hair_class=a.hair_class,
                               with_tier1=a.with_tier1,
                               hunt_classes=hunt))
    print(json.dumps(reports, indent=1))

if __name__ == '__main__':
    main()
