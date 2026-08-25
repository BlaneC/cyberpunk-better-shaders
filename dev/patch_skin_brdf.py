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
}
VANILLA = dict(KNOBS, tint=(1.0, 1.0, 1.0), rho_f=1.0, rho_r=1.0)

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
            m2 = re.search(r'"([0-9a-f]{16})\.[^"]*\.dxil"', '\n'.join(self.lines))
            self.dxil = m2.group(1) if m2 else None
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

def build_tier1(mod, prim, gate, knobs):
    consts, edits = [], []
    def C(v):
        nid, c = mod.const(v)
        if c: consts.append(c)
        return nid
    one  = C(1.0)
    zero = C(0.0)
    eps  = C(EPS)
    # r(x)=2(1-x); exponent = 5*r = 10*(1-x)
    e_ef = C(10.0 * (1.0 - knobs["n_f"]))
    e_tf = C(10.0 * (1.0 - knobs["m_f"]))
    e_er = C(10.0 * (1.0 - knobs["n_r"]))
    e_tr = C(10.0 * (1.0 - knobs["m_r"]))
    rf   = C(knobs["rho_f"])
    rr   = C(knobs["rho_r"])
    gl   = mod.glsl
    report = []
    for t in prim:
        r_ch = t['chan'].index(0)            # position of the r-channel value
        nol = trace_nol(mod, t['line'], t['ids'][r_ch])
        n_ids, v_ids = find_nv(mod, t['line'])
        I = lambda: mod.new_id()
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
        newids = []
        for vid in t['ids']:
            n = I()
            ins.append(f"        {n} = OpFMul %float {vid} {g}")
            newids.append(n)
        edits.append((t['line'] + 2, ins))
        for vid, n in zip(t['ids'], newids):
            replace_single_use(mod, vid, n, t['line'], 'tier1')
        report.append(dict(line=t['line'] + 1, nol=nol,
                           n=n_ids, v=v_ids, ids=t['ids']))
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

def process(path, outdir, tier, knobs, target_env, do_rt=True):
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
        consts, edits = build_smoke(mod, triples, gate, knobs)
        rep['tint'] = knobs['tint']
    elif tier == '1':
        consts, edits, rep['sites'] = build_tier1(mod, prim, gate, knobs)
        rep['params'] = {k: knobs[k] for k in ('rho_f','n_f','m_f','rho_r','n_r','m_r')}
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
    ap.add_argument('--tier', choices=['smoke', '1'], default='smoke')
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
    reports = []
    for p in a.modules:
        reports.append(process(p, a.outdir, a.tier, knobs, a.target_env,
                               do_rt=not a.no_roundtrip_check))
    print(json.dumps(reports, indent=1))

if __name__ == '__main__':
    main()
