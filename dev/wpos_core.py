#!/usr/bin/env python3
"""wpos_core -- the shared structural reader for the compute resolvers' surface
position P, and the emitter that later site-C features call.

handoff/99. NOTHING here edits an existing shared patcher: this file is new and
is imported by dev/hunt_wpos.py, dev/patch_wpos.py and dev/verify_wpos.py.

WHAT IS BEING FOUND
-------------------
Every direct-light resolver computes NoV, so it must have a view vector V, and
V is built from a surface position P.  Measured over all 77 compute modules of
the standing rung, the shape is ONE idiom and it is reconstructed inside the
module (nothing reads a position buffer):

    x  = float(pixel.x)                       ; OpConvertUToF of the tile-decoded x
    y  = float(pixel.y)
    z  = depth                                ; OpImageFetch .x on the D32 front depth
    n0 = M[k+0].x*x + M[k+1].x*y + M[k+2].x*z + M[k+3].x      (Fma chain)
    n1 = ... .y ...
    n2 = ... .z ...
    d  = M[k+0].w*x + M[k+1].w*y + M[k+2].w*z + M[k+3].w
    P  = (n0, n1, n2) / d                     ; THREE OpFDiv sharing one denominator
    V  = normalize(C.xyz - P)                 ; C = a v4 member of the SAME cbv

M is four consecutive `v4float` members of one bindless CBV (member 69..72 in
every module that has it) and C is member 0 of that same CBV.  So P and C live
in the same space by construction, and the ONLY question the bytes can answer
is which space that is -- see hunt_wpos.py's verdict and handoff/99 sec 3.

CONTRACT of emit_world_pos(mod, cfg, ctx, site_line, ins) -> (idx, idy, idz)
---------------------------------------------------------------------------
* `ctx` is find_pos_chain(mod)'s dict.  It is computed ONCE per module.
* If ctx['p'] dominates `site_line` (dev/cfg_dom), the three existing ids are
  returned and `ins` is untouched -- zero added instructions.
* Otherwise a site-local REFETCH is appended to `ins`: the depth fetch, the
  16 CBV component loads, the Fma chain and the three OpFDivs.  Every input it
  needs (the image access chain's base + slot, the two pixel-coordinate ids,
  the CBV access-chain base) must itself dominate the site; `pos_inputs(ctx)`
  is the list, and the caller must check it, because a refetch that reads a
  non-dominating id is an undefined-id validation failure, not a wrong pixel.
* The returned ids are in P's own space (see above).  `emit_world_pos` does
  NOT add a world offset: no such offset exists in these modules (handoff/99
  sec 3).  A caller that wants a frame-stable world hash uses these ids
  directly and accepts P's space; that is what hunt-wpos measures.
* HOIST: the caller may call this once at `hoist_line(mod, cfg, sites)` instead
  of per site.  The hoist point must be ABOVE any OpSelectionMerge in its block
  (00 sec 9), because OpSelectionMerge must stay immediately before its branch.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg_dom

EPS_NOV = '%float_9_99999975en06'

# ---------------------------------------------------------------- utilities
def defs_index(mod):
    d = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*)$', ln)
        if m:
            d.setdefault(m.group(1), (i, m.group(2).strip()))
    return d


def cone(D, root, limit=4000):
    """Backward def cone of `root` (ids only), breadth-first, bounded."""
    seen, stack = set(), [root]
    while stack and len(seen) < limit:
        i = stack.pop()
        if i in seen or i not in D:
            continue
        seen.add(i)
        for j in re.findall(r'%\w+', D[i][1]):
            if j not in seen:
                stack.append(j)
    return seen


def cbv_members(D, ids):
    """{(cbv_base, member_index)} for every v4float CBV access chain in `ids`."""
    out = set()
    pat = re.compile(r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_(\d+)\s*$')
    for i in ids:
        if i in D:
            m = pat.match(D[i][1])
            if m:
                out.add((m.group(1), int(m.group(2))))
    return out


def find_function_span(mod):
    fs = fe = None
    for i, ln in enumerate(mod.lines):
        s = ln.strip()
        if s.startswith('OpFunction ') or ' = OpFunction ' in s:
            if fs is None:
                fs = i
        if s == 'OpFunctionEnd':
            fe = i
    return fs, len(mod.lines) if fe is None else fe


class Dom:
    """cfg_dom over the whole listing; `dominates(def_id, use_line)`."""

    def __init__(self, mod):
        self.mod = mod
        self.D = defs_index(mod)
        self.fs, self.fe = find_function_span(mod)

    def line_of(self, idtok):
        return self.D[idtok][0] if idtok in self.D else None

    def dominates_line(self, idtok, use_line):
        if idtok is None or not str(idtok).startswith('%'):
            return True
        ln = self.line_of(idtok)
        if ln is None:                      # a global (type/constant/variable)
            return True
        if ln < self.fs:
            return True
        return cfg_dom.dominates(self.mod, self.fs, self.fe, ln, use_line)


# ------------------------------------------------------- the position chain
def _mrow(D, idtok, want_comp=None):
    """Parse `FAdd(Fma(Fma(FMul(m0,x), m1,y), m2,z), m3)` -> (members, x, y, z, comp)."""
    def ext(i):
        m = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', D.get(i, (0, ''))[1])
        if not m:
            return None
        ld = re.match(r'OpLoad %v4float (%\w+)\s*$', D.get(m.group(1), (0, ''))[1])
        if not ld:
            return None
        ac = re.match(r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_(\d+)\s*$',
                      D.get(ld.group(1), (0, ''))[1])
        if not ac:
            return None
        return ac.group(1), int(ac.group(2)), int(m.group(2))

    m = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', D.get(idtok, (0, ''))[1])
    if not m:
        return None
    t3, d3 = m.groups()
    e3 = ext(d3)
    if e3 is None:                       # operands may be the other way round
        t3, d3 = d3, t3
        e3 = ext(d3)
    if e3 is None:
        return None
    rows = [e3]
    axes = []
    cur = t3
    for _ in range(2):
        m = re.match(r'OpExtInst %float %\w+ Fma (%\w+) (%\w+) (%\w+)\s*$',
                     D.get(cur, (0, ''))[1])
        if not m:
            return None
        c, ax, nxt = m.groups()
        e = ext(c)
        if e is None:
            c, ax = ax, c
            e = ext(c)
        if e is None:
            return None
        rows.append(e)
        axes.append(ax)
        cur = nxt
    m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$', D.get(cur, (0, ''))[1])
    if not m:
        return None
    c, ax = m.groups()
    e = ext(c)
    if e is None:
        c, ax = ax, c
        e = ext(c)
    if e is None:
        return None
    rows.append(e)
    axes.append(ax)
    # rows are [k+3, k+2, k+1, k+0]; every row must share one cbv and one comp
    cbvs = {r[0] for r in rows}
    comps = {r[2] for r in rows}
    if len(cbvs) != 1 or len(comps) != 1:
        return None
    if want_comp is not None and comps != {want_comp}:
        return None
    mem = [r[1] for r in rows][::-1]
    if any(mem[i] + 1 != mem[i + 1] for i in range(3)):
        return None
    x, z, y = axes[2], axes[1], axes[0]   # FMul axis, Fma#1 axis, Fma#2 axis
    return dict(cbv=cbvs.pop(), members=mem, comp=comps.pop(),
                x=axes[2], y=axes[1], z=axes[0])


def find_pos_chain(mod, D=None):
    """Locate P = (M . (x, y, depth, 1)) / w.  Returns a ctx dict or None.

    STRICT: each of the four rows is parsed as the exact Fma chain the
    compiler emits, so the matrix member indices and the (x, y, depth) axis
    ids are read out of the instruction stream, never guessed from position
    (GOTCHAS 10).
    """
    D = D or defs_index(mod)
    fdiv = re.compile(r'OpFDiv %float (%\w+) (%\w+)\s*$')
    groups = {}
    for idtok, (line, txt) in D.items():
        m = fdiv.match(txt)
        if m:
            groups.setdefault(m.group(2), []).append((line, idtok, m.group(1)))
    best = None
    for den, members in groups.items():
        if len(members) < 3:
            continue
        members.sort()
        wrow = _mrow(D, den, want_comp=3)
        if wrow is None:
            continue
        for s in range(len(members) - 2):
            trio = members[s:s + 3]
            rows = [_mrow(D, t[2], want_comp=c) for c, t in enumerate(trio)]
            if any(r is None for r in rows):
                continue
            if len({(r['cbv'], tuple(r['members'])) for r in rows + [wrow]}) != 1:
                continue
            if len({(r['x'], r['y'], r['z']) for r in rows + [wrow]}) != 1:
                continue
            cand = dict(p=tuple(t[1] for t in trio),
                        num=tuple(t[2] for t in trio),
                        den=den, line=trio[2][0],
                        cbv=rows[0]['cbv'], mat=rows[0]['members'],
                        ax=(rows[0]['x'], rows[0]['y'], rows[0]['z']),
                        cone=set())
            for _l, _i, num in trio:
                cand['cone'] |= cone(D, num)
            cand['cone'] |= cone(D, den)
            if best is None or cand['line'] < best['line']:
                best = cand
    if best is None:
        return None
    _decode_inputs(mod, D, best)
    return best


def _decode_inputs(mod, D, ctx):
    """Resolve the three axis operands: pixel x, pixel y and the depth fetch."""
    ax, ay, az = ctx['ax']
    def conv(i):
        m = re.match(r'OpConvertUToF %float (%\w+)\s*$', D.get(i, (0, ''))[1])
        return m.group(1) if m else None
    ctx['pix'] = (ax, ay)
    ctx['pix_src'] = (conv(ax), conv(ay))
    depth = None
    m = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', D.get(az, (0, ''))[1])
    if m:
        f = m.group(1)
        mf = re.match(r'OpImageFetch %v4float (%\w+) (%\w+) Lod (%\w+)\s*$',
                      D.get(f, (0, ''))[1])
        if mf:
            img, coord, lod = mf.groups()
            depth = dict(fetch=f, image=img, coord=coord, lod=lod, z=az,
                         comp=int(m.group(2)))
    ctx['depth'] = depth
    ctx['cbv_chain'] = _chain_of(D, ctx['cbv'])
    ctx['cbv_slot'] = _pc_slot(D, ctx['cbv'])
    ctx['cbvv'] = _cbv_parts(ctx['cbv_chain'])
    if depth:
        ctx['img_chain'] = _chain_of(D, depth['image'])
        ctx['img_slot'] = _pc_slot(D, depth['image'])
        ctx['img'] = _img_parts(ctx['img_chain'])
        mc = D.get(depth['coord'], (None, ''))[1]
        m2 = re.match(r'OpCompositeConstruct %v2uint (%\w+) (%\w+)\s*$', mc)
        ctx['coord_xy'] = m2.groups() if m2 else None
    else:
        ctx['img_chain'], ctx['coord_xy'] = None, None
        ctx['img_slot'], ctx['img'] = None, None


def _img_parts(chain):
    """(ptrty, imgty, arr, slot) for `OpLoad T (OpAccessChain ptrT arr slot)`."""
    if not chain or len(chain) < 2:
        return None
    m = re.match(r'OpLoad (%\w+) (%\w+)\s*$', chain[0][1])
    if not m:
        return None
    m2 = re.match(r'OpAccessChain (%\S+) (%\w+) (%\w+)\s*$', chain[1][1])
    if not m2 or m2.group(0).split()[2] != chain[1][1].split()[2]:
        pass
    if not m2:
        return None
    return dict(imgty=m.group(1), ptrty=m2.group(1), arr=m2.group(2), slot=m2.group(3))


def _cbv_parts(chain):
    """(arr, slot) for the bindless CBV `OpAccessChain ptr arr slot`."""
    if not chain:
        return None
    m = re.match(r'OpAccessChain %_ptr_Uniform_BindlessCBV (%\w+) (%\w+)\s*$', chain[0][1])
    return None if not m else dict(arr=m.group(1), slot=m.group(2))


def _pc_slot(D, idtok):
    """`registers[i] + k` behind a bindless load -> (i, k), or None.

    38 sec 1.1: `registers[1]+0` is the D32 front depth; the resolvers' view
    constant buffer is `registers[0]+12`.  Reading the base out of a push
    constant at runtime is why this survives GOTCHAS 13 -- nothing is baked.
    """
    cur, guard = idtok, 0
    while cur in D and guard < 16:
        guard += 1
        txt = D[cur][1]
        m = re.match(r'OpAccessChain %_ptr_PushConstant_uint %registers %uint_(\d+)\s*$', txt)
        if m:
            return (int(m.group(1)), 0)
        m = re.match(r'OpIAdd %uint (%\w+) %uint_(\d+)\s*$', txt)
        if m:
            inner = _pc_slot(D, m.group(1))
            return None if inner is None else (inner[0], inner[1] + int(m.group(2)))
        m = re.match(r'OpLoad \S+ (%\w+)\s*$', txt) or \
            re.match(r'OpAccessChain \S+ %\w+ (%\w+)\s*$', txt)
        if not m:
            return None
        cur = m.group(1)
    return None


def _chain_of(D, idtok):
    """Unroll `%x = OpLoad T %ac` / `OpAccessChain ...` into a replayable list."""
    out, cur, guard = [], idtok, 0
    while cur in D and guard < 16:
        guard += 1
        txt = D[cur][1]
        out.append((cur, txt))
        nxt = None
        m = re.match(r'OpLoad \S+ (%\w+)\s*$', txt)
        if m:
            nxt = m.group(1)
        else:
            m = re.match(r'OpAccessChain \S+ (%\w+) (.*)$', txt)
            if m and m.group(1) in D:
                nxt = m.group(1)
            else:
                m = re.match(r'OpIAdd %uint (%\w+) (%\w+)\s*$', txt)
                if m:
                    nxt = m.group(1)
        if nxt is None:
            break
        cur = nxt
    return out


def pos_inputs(ctx):
    """Ids a site-local refetch of P reads.  All must dominate the splice."""
    ids = []
    if ctx.get('coord_xy'):
        ids += list(ctx['coord_xy'])
    if ctx.get('pix_src'):
        ids += list(ctx['pix_src'])
    d = ctx.get('depth')
    if d:
        ids += [d['lod']]
    for chain in (ctx.get('img_chain'), ctx.get('cbv_chain')):
        for cur, txt in (chain or []):
            ids += re.findall(r'%\w+', txt)
    return sorted({i for i in ids if re.match(r'%\d+$', i)})


# ------------------------------------------------- the camera-position load
def find_p_subtractions(mod, ctx, D=None):
    """Every `X - P` triple, with the source of X classified.

    This is the GOTCHAS-5 evidence: P's SPACE is whatever these X live in.
    Two independent kinds are found in the resolvers -- the camera position
    (a CBV member, used to build V) and the LIGHT positions (loaded out of
    the light-list storage buffer, used to build L).
    """
    D = D or defs_index(mod)
    px, py, pz = ctx['p']
    by_p = {px: [], py: [], pz: []}
    for idtok, (line, txt) in D.items():
        m = re.match(r'OpFSub %float (%\w+) (%\w+)\s*$', txt)
        if m and m.group(2) in by_p:
            by_p[m.group(2)].append((line, idtok, m.group(1)))
    for k in by_p:
        by_p[k].sort()
    out = []
    used = set()
    for line, idtok, src in by_p[px]:
        # the matching y and z subtractions are the nearest ones after it
        cand = {}
        for k, p in ((1, py), (2, pz)):
            best = None
            for l2, i2, s2 in by_p[p]:
                if (p, i2) in used:
                    continue
                if best is None or abs(l2 - line) < abs(best[0] - line):
                    best = (l2, i2, s2)
            cand[k] = best
        if cand[1] is None or cand[2] is None:
            continue
        if max(abs(cand[1][0] - line), abs(cand[2][0] - line)) > 12:
            continue
        used.add((py, cand[1][1])); used.add((pz, cand[2][1]))
        srcs = (src, cand[1][2], cand[2][2])
        out.append(dict(line=line, ids=(idtok, cand[1][1], cand[2][1]),
                        srcs=srcs, kind=_classify_src(D, srcs)))
    return sorted(out, key=lambda d: d['line'])


def _classify_src(D, srcs):
    """cbv[N] / ssbo / phi / other -- what space-mate X came from."""
    cbv = []
    for k, c in enumerate(srcs):
        m = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', D.get(c, (0, ''))[1])
        if not m or int(m.group(2)) != k:
            cbv = None
            break
        ld = re.match(r'OpLoad %v4float (%\w+)\s*$', D.get(m.group(1), (0, ''))[1])
        if not ld:
            cbv = None
            break
        ac = re.match(r'OpAccessChain %_ptr_Uniform_v4float (%\w+) %uint_0 %uint_(\d+)\s*$',
                      D.get(ld.group(1), (0, ''))[1])
        if not ac:
            cbv = None
            break
        cbv.append((ac.group(1), int(ac.group(2))))
    if cbv and len(set(cbv)) == 1:
        return dict(kind='cbv', cbv=cbv[0][0], member=cbv[0][1])
    # a v3 loaded straight out of the light-list storage buffer
    ss = []
    for k, c in enumerate(srcs):
        m = re.match(r'OpCompositeExtract %float (%\w+) (\d+)\s*$', D.get(c, (0, ''))[1])
        if not m or int(m.group(2)) != k:
            ss = None
            break
        ld = re.match(r'OpLoad %v3float (%\w+)(?: Aligned \d+)?\s*$', D.get(m.group(1), (0, ''))[1])
        if not ld:
            ss = None
            break
        rc = re.match(r'OpRawAccessChainNV \S+ (%\w+) %uint_(\d+) (%\w+) %uint_(\d+)',
                      D.get(ld.group(1), (0, ''))[1])
        if not rc:
            ss = None
            break
        ss.append((rc.group(1), int(rc.group(2)), int(rc.group(4))))
    if ss and len(set(ss)) == 1:
        return dict(kind='ssbo', buf=ss[0][0], stride=ss[0][1], off=ss[0][2])
    kinds = set()
    for c in srcs:
        txt = D.get(c, (0, ''))[1]
        if txt.startswith('OpLoad %float'):
            tgt = re.findall(r'%\w+', txt)[-1]
            t2 = D.get(tgt, (0, ''))[1]
            kinds.add('ssbo' if 'RawAccessChainNV' in t2 or 'StorageBuffer' in t2 else 'load')
        elif txt.startswith('OpPhi'):
            kinds.add('phi')
        else:
            kinds.add(txt.split()[0] if txt else 'unknown')
    return dict(kind='/'.join(sorted(kinds)))


def find_campos(mod, ctx, D=None):
    """The camera position: the CBV-sourced `C - P` triple nearest to P."""
    D = D or defs_index(mod)
    subs = [s for s in find_p_subtractions(mod, ctx, D) if s['kind']['kind'] == 'cbv']
    if not subs:
        return None
    s = subs[0]
    return dict(cbv=s['kind']['cbv'], member=s['kind']['member'],
                comps=s['srcs'], sub=s['ids'], line=s['line'], n_cbv_subs=len(subs))


# ------------------------------------------------- world-offset hunt (sec 3)
def find_offset_adds(mod, ctx, D=None):
    """Any `P_i + <something>` triple -- the 94 sec 3.3 world-offset pattern."""
    D = D or defs_index(mod)
    px, py, pz = ctx['p']
    hits = {}
    for idtok, (line, txt) in D.items():
        m = re.match(r'OpFAdd %float (%\w+) (%\w+)\s*$', txt)
        if not m:
            continue
        a, b = m.groups()
        for p, other in ((a, b), (b, a)):
            if p in (px, py, pz):
                hits.setdefault(p, []).append((idtok, other, line))
    return hits


def p_consumers(mod, ctx, D=None):
    """Every instruction that reads a component of P, with its opcode."""
    D = D or defs_index(mod)
    ps = set(ctx['p'])
    out = []
    for idtok, (line, txt) in sorted(D.items(), key=lambda kv: kv[1][0]):
        ops = re.findall(r'%\w+', txt)
        if ps & set(ops):
            out.append((line, idtok, txt.split()[0]))
    for i, ln in enumerate(mod.lines):
        s = ln.strip()
        if s.startswith('Op') and (ps & set(re.findall(r'%\w+', s))):
            out.append((i, None, s.split()[0]))
    seen, res = set(), []
    for line, idtok, op in sorted(out):
        if line in seen:
            continue
        seen.add(line)
        res.append((line, idtok, op))
    return res


# ------------------------------------------------------- NoV cross-check
def find_nov_chains(mod, D=None):
    """The eps-clamped NoV sites: [(clamp_id, dot_id, (A3), (B3))]."""
    D = D or defs_index(mod)
    out = []
    for idtok, (line, txt) in D.items():
        m = re.match(r'OpExtInst %float (%\w+) NMax (%\w+) ' + re.escape(EPS_NOV) + r'\s*$', txt)
        if not m:
            continue
        dot = m.group(2)
        dtx = D.get(dot, (0, ''))[1]
        md = re.match(r'OpDot %float (%\w+) (%\w+)\s*$', dtx)
        if not md:
            out.append((idtok, dot, None, None))
            continue
        tri = []
        for v in md.groups():
            mv = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                          D.get(v, (0, ''))[1])
            tri.append(mv.groups() if mv else None)
        out.append((idtok, dot, tri[0], tri[1]))
    return sorted(out, key=lambda t: D[t[0]][0])


def nov_roots_at_p(mod, ctx, D=None):
    """(rooted, dot_shaped, all_eps) over the eps-clamped 1e-5 sites.

    Only the clamps whose operand is `OpDot(v3, v3)` are NoV candidates
    (97 sec 1.5); the same 1e-5 floor is used on scalars elsewhere.  A NoV is
    counted as rooted at P when one of the dot's two operand triples has P in
    its backward cone -- i.e. the view vector really is built from this P.
    """
    D = D or defs_index(mod)
    ps = set(ctx['p'])
    rooted = shaped = 0
    sites = find_nov_chains(mod, D)
    for clamp, dot, A, B in sites:
        if not (A and B):
            continue
        shaped += 1
        for tri in (A, B):
            c = set()
            for v in tri:
                c |= cone(D, v, limit=4000)
            if ps & c:
                rooted += 1
                break
    return rooted, shaped, len(sites)


# ------------------------------------------------------------- THE EMITTER
def pos_leaves(ctx):
    """The ids a site-local refetch of P reads.  ALL must dominate the site."""
    ids = [ctx['img']['arr'], ctx['img']['slot'],
           ctx['cbvv']['arr'], ctx['cbvv']['slot'],
           ctx['coord_xy'][0], ctx['coord_xy'][1], ctx['depth']['lod']]
    return [i for i in ids if re.match(r'%\d+$', i)]


def emit_world_pos(mod, dom, ctx, site_line, ins, uc=None,
                   relative_to_camera=False, cam=None):
    """Return (id_x, id_y, id_z): the surface position at `site_line`.

    CONTRACT
    --------
    * `ctx`  = find_pos_chain(mod)  -- one per module, computed once.
    * `dom`  = wpos_core.Dom(mod)   -- the structured-CFG dominator tree.
    * `ins`  = the caller's instruction list for THIS splice; appended to.
    * `uc`   = a dict used to memoise `mod.uconst` (GOTCHAS: uconst has no
               pending-declaration cache, so asking twice emits the constant
               twice and `spirv-val` fails with "defined more than once").
               Pass the SAME dict for the whole module and append
               `uc['decls']` to the module's constant list.
    * If `ctx['p']` dominates `site_line` the three existing ids are returned
      and NOTHING is emitted.  Otherwise ~50 instructions of site-local
      refetch are appended: the depth fetch, the four matrix rows, the Fma
      chain and the perspective divide.  The refetch reads only
      `pos_leaves(ctx)`, and the CALLER must have proved each of those
      dominates `site_line` -- a refetch that reads a non-dominating id is an
      undefined-id validation failure, not a wrong pixel.
    * `relative_to_camera=True` returns `P - C`, where C is the camera
      position the module itself loads to build V (`cam` = find_campos(...)).
      That value is camera-relative BY CONSTRUCTION and is the hunt-wpos-cam
      control.
    * SPACE: the ids are in P's own space.  No world offset is added because
      none exists in these modules (handoff/99 sec 3): every consumer of P in
      all 75 modules is a SUBTRACTION, and a difference of positions cannot
      tell world from camera-relative.  Callers that need frame-stable world
      space must read handoff/99 sec 3 first.
    * HOIST: to emit once per module instead of once per site, call this at a
      line that dominates every site and insert ABOVE any `OpSelectionMerge`
      in that block (00 sec 9) -- OpSelectionMerge must stay immediately
      before its branch.
    """
    if uc is None:
        uc = {}
    uc.setdefault('decls', [])

    def U(n):
        key = ('u', int(n))
        if key in uc:
            return uc[key]
        nid, decl = mod.uconst(n)
        if decl:
            uc['decls'].append(decl)
        uc[key] = nid
        return nid

    p = ctx['p']
    if not all(dom.dominates_line(i, site_line) for i in p):
        p = _emit_refetch(mod, ctx, ins, U)
    if not relative_to_camera:
        return p
    if cam is None:
        raise ValueError('relative_to_camera needs cam=find_campos(...)')
    c = _emit_campos(mod, dom, cam, ctx, ins, U, site_line)
    out = []
    for k in range(3):
        i = mod.new_id()
        ins.append(f"        {i} = OpFSub %float {p[k]} {c[k]}")
        out.append(i)
    return tuple(out)


def _emit_campos(mod, dom, cam, ctx, ins, U, site_line):
    if all(dom.dominates_line(i, site_line) for i in cam['comps']):
        return cam['comps']
    I = mod.new_id
    a, b = I(), I()
    ins += [
        f"        {a} = OpAccessChain %_ptr_Uniform_v4float {ctx['cbv']} %uint_0 {U(cam['member'])}",
        f"        {b} = OpLoad %v4float {a}",
    ]
    out = []
    for k in range(3):
        i = I()
        ins.append(f"        {i} = OpCompositeExtract %float {b} {k}")
        out.append(i)
    return tuple(out)


def _emit_refetch(mod, ctx, ins, U):
    """Replay the module's own reconstruction at the splice point."""
    I = mod.new_id
    img, cb, d = ctx['img'], ctx['cbvv'], ctx['depth']
    ac, ld, co, fe, z = I(), I(), I(), I(), I()
    ins += [
        f"        {ac} = OpAccessChain {img['ptrty']} {img['arr']} {img['slot']}",
        f"        {ld} = OpLoad {img['imgty']} {ac}",
        f"        {co} = OpCompositeConstruct %v2uint {ctx['coord_xy'][0]} {ctx['coord_xy'][1]}",
        f"        {fe} = OpImageFetch %v4float {ld} {co} Lod {d['lod']}",
        f"        {z} = OpCompositeExtract %float {fe} {d['comp']}",
    ]
    fx, fy = I(), I()
    ins += [
        f"        {fx} = OpConvertUToF %float {ctx['coord_xy'][0]}",
        f"        {fy} = OpConvertUToF %float {ctx['coord_xy'][1]}",
    ]
    rows = []
    for m in ctx['mat']:
        a, b = I(), I()
        ins += [
            f"        {a} = OpAccessChain %_ptr_Uniform_v4float {ctx['cbv']} %uint_0 {U(m)}",
            f"        {b} = OpLoad %v4float {a}",
        ]
        comps = []
        for k in range(4):
            i = I()
            ins.append(f"        {i} = OpCompositeExtract %float {b} {k}")
            comps.append(i)
        rows.append(comps)
    glsl = mod.glsl
    outs = []
    for c in range(4):
        t1, t2, t3, t4 = I(), I(), I(), I()
        ins += [
            f"        {t1} = OpFMul %float {rows[0][c]} {fx}",
            f"        {t2} = OpExtInst %float {glsl} Fma {rows[1][c]} {fy} {t1}",
            f"        {t3} = OpExtInst %float {glsl} Fma {rows[2][c]} {z} {t2}",
            f"        {t4} = OpFAdd %float {t3} {rows[3][c]}",
        ]
        outs.append(t4)
    p = []
    for c in range(3):
        i = I()
        ins.append(f"        {i} = OpFDiv %float {outs[c]} {outs[3]}")
        p.append(i)
    return tuple(p)
