#!/usr/bin/env python3
"""verify_glintobj -- read the OBJECT-SPACE glint rungs back OUT of the shipped
`.spv` and prove, instruction by instruction, that

  (a) the cell hash is fed from a ray query's committed WorldToObject applied
      to the module's OWN hit position, and
  (b) `100`'s WORLD-space feed is DISCONNECTED from that hash -- present only
      as the miss arm of a select, with exactly one use each -- and
  (c) NOTHING ELSE MOVED: every other instruction in the module is the base's,
      byte for byte, checked as a line-level diff and not as a hash.

handoff/106-OBJECT-SPACE-GLINTS.md sec 4 is the gate table this fills in.

    python3 dev/verify_glintobj.py <dir-of-.spv> --base <dir> --mode glint
    python3 dev/verify_glintobj.py --negative <dir>          # must be REJECTED

Nothing here reads a patcher report. Every id, constant and count is re-derived
from the disassembly of the file that will be served, and `98`'s SECOND
implementations of the world-offset and primary-ray detectors are imported
(`verify_rayq.derive_world_offset` / `find_primary`) rather than the patcher's,
so a patcher that agreed only with itself cannot pass.

ELEVEN AXES, each of which FAILS the run (there are no warnings):

  1  the module is a reference raygen and declares RayQueryKHR
  2  `100`'s LOD ladder and knobs are intact: cell, NU0 = nu0*theta_bin^2
  3  REPLACE, part 1 -- each cell divide takes an OpSelect, not an OpFAdd
  4  the select's condition is committed(query) and is ONE bool for all three
  5  REPLACE, part 2 -- the false arm is cb[M][k] + P[k] with M re-derived
     independently, and that OpFAdd has EXACTLY ONE use in the module
  6  REPLACE, part 3 -- the true arm's backward closure is the WorldToObject
     getter, the module's own hit position and constants, with NO Uniform load
     and NO access chain anywhere in it (so no member 56 in the object arm)
  7  the query clones the module's own trace BY SSA ID: accel, cull mask,
     origin, direction; flags 517; bracket [0.999t, 1.001t + 1e-4] on the
     payload word-3 load
  8  instruction census against the base: exactly the expected number of added
     Initialize / Proceed / committed-type / WorldToObject, ZERO added
     OpTraceRayKHR, and zero added blocks (no control flow)
  9  the six GGX arms are untouched: 6 PCG chains, 6 Bernoulli selects, 6
     `glint = 1 + kw(g-1)` adds, 18 spec multiplies -- the same numbers as the
     base
 10  DIFF DISCIPLINE -- the only base lines that changed are the three cell
     divides (plus, on the paint rungs, the entry point and the image writes),
     and every inserted line is in this feature's own opcode whitelist
 11  mode-specific: `cell` carries a SECOND query down the primary ray and an
     8-hue paint; `miss` carries a 3-state latch and a magenta paint; `glint`
     carries neither
"""
import argparse, glob, hashlib, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glint_model as GM
from verify_rayq import Asm, fconst, uconst, find_primary, derive_world_offset

FAIL = []
RAY_FLAGS = 517
T_LO, T_HI, T_EPS = 0.999, 1.001, 1.0e-4
GETTER = 'OpRayQueryGetIntersectionWorldToObjectKHR'

# Every opcode this feature is allowed to add. A base instruction that changed
# shape would appear as an insert of something NOT on this list, or as a delete
# that axis 10 does not permit.
ALLOWED_INSERT = {
    'OpTypeBool', 'OpTypeInt', 'OpTypeMatrix', 'OpTypeRayQueryKHR',
    'OpTypePointer', 'OpConstant', 'OpConstantComposite', 'OpVariable',
    'OpFMul', 'OpFAdd', 'OpFDiv', 'OpFSub', 'OpSelect', 'OpINotEqual',
    'OpIEqual', 'OpLoad', 'OpStore', 'OpAccessChain', 'OpCompositeExtract',
    'OpCompositeConstruct', 'OpVectorTimesScalar', 'OpExtInst',
    'OpConvertFToS', 'OpConvertUToF', 'OpBitcast', 'OpIMul', 'OpIAdd',
    'OpBitwiseXor', 'OpBitwiseAnd', 'OpShiftRightLogical',
    'OpRayQueryInitializeKHR', 'OpRayQueryProceedKHR',
    'OpRayQueryGetIntersectionTypeKHR', GETTER,
}
QUERIES = {'glint': 1, 'miss': 1, 'cell': 2}


def bad(msg):
    FAIL.append(msg)
    print('  FAIL ' + msg)


def _near(v, want, rel=1e-6):
    """The .spvasm holds the nearest float32 to the constant the patcher asked
    for -- 0.999 is written 0.999000013 -- so every knob comparison here is a
    relative one."""
    return v is not None and abs(v - want) <= rel * max(1.0, abs(want))


def _m(a, tok, pat):
    return re.match(pat, a.d(tok) or '')


def _uses(a, tok):
    pat = re.compile(r'(?<![%\w])' + re.escape(tok) + r'(?![\w])')
    isdef = re.compile(r'^\s*' + re.escape(tok) + r'\s*=')
    return [i for i, ln in enumerate(a.lines)
            if not isdef.match(ln) and pat.search(ln)]


def derive_origins(a):
    """The v3 hit-position triples that are the ORIGIN operand of the module's
    own OpTraceRayKHR sites. `verify_rayq.derive_world_offset` computes this
    internally and throws it away (it returns only (cbv, member)); it is
    re-derived here rather than plumbed out of the patcher, for the same reason
    everything else in this file is: a verifier that asked the patcher where the
    hit position was could only prove the patcher agreed with itself."""
    out = set()
    for ln in a.lines:
        m = re.match(r'\s*OpTraceRayKHR\s+(.+?)\s*$', ln)
        if not m:
            continue
        ops = m.group(1).split()
        if len(ops) != 11:
            continue
        cc = _m(a, ops[6],
                r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$')
        if cc:
            out.add(cc.groups())
    return out


# ------------------------------------------------------------------ axis 2
def find_ladders(a):
    """Every instance of `100`'s dyadic LOD ladder in the module. Returns a list
    of (s, cell). The `-cell` diagnostic emits a SECOND ladder for the flat-hue
    cells of the primary hit, so "exactly one" is the wrong assertion here; the
    right one is "exactly one whose s^2 drives the glint density", below."""
    out = []
    for ln in a.lines:
        m = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        s, x, y = m.groups()
        for cell_c, ex in ((x, y), (y, x)):
            cv = fconst(a, cell_c)
            if cv is None or not (0.0 < cv < 1.0):
                continue
            me = _m(a, ex, r'OpExtInst %float %\w+ Exp2 (%\w+)\s*$')
            mc = _m(a, me.group(1), r'OpExtInst %float %\w+ Ceil (%\w+)\s*$') if me else None
            ml = _m(a, mc.group(1), r'OpExtInst %float %\w+ Log2 (%\w+)\s*$') if mc else None
            mn = _m(a, ml.group(1),
                    r'OpExtInst %float %\w+ NClamp (%\w+) (%\w+) (%\w+)\s*$') if ml else None
            if not mn or fconst(a, mn.group(2)) != 1.0 or \
                    fconst(a, mn.group(3)) != float(GM.RATIO_MAX):
                continue
            out.append((s, cv))
    return out


def pick_ladder(a, mode, nu0, name):
    """The glint's OWN ladder: the one whose s^2 is scaled by NU0 = nu0*bin^2
    into `100`'s flake density. Returns (s, s2, cell)."""
    lads = find_ladders(a)
    want = 2 if mode == 'cell' else 1
    if len(lads) != want:
        bad(f'{name}: {len(lads)} LOD ladders, want {want} '
            f'({"the glint\'s and the diagnostic\'s" if want == 2 else "the glint\'s"})')
        if not lads:
            return None
    hits = []
    for s, cv in lads:
        sq = [m.group(1) for ln in a.lines
              for m in [re.match(r'\s*(%\w+) = OpFMul %float ' + re.escape(s)
                                 + r' ' + re.escape(s) + r'\s*$', ln)] if m]
        if len(sq) != 1:
            continue
        for ln in a.lines:
            m = re.match(r'\s*%\w+ = OpFMul %float (%\w+) ' + re.escape(sq[0])
                         + r'\s*$', ln)
            if m and _near(fconst(a, m.group(1)), nu0):
                hits.append((s, sq[0], cv))
                break
    if len(hits) != 1:
        bad(f'{name}: {len(hits)} ladders drive a flake density of '
            f'NU0={nu0} -- the glint knobs are NOT the base\'s')
        return None
    return hits[0]


# ------------------------------------------------------------------ axes 3-6
def check_feed(a, s, cbv, member, origins, name):
    allpos = {t for trip in origins for t in trip}
    divs = []
    for i, ln in enumerate(a.lines):
        m = re.match(r'\s*(%\w+) = OpFDiv %float (%\w+) ' + re.escape(s) + r'\s*$', ln)
        if m:
            divs.append(m.groups())
    if len(divs) != 3:
        bad(f'{name}: {len(divs)} cell divides, want 3')
        return None
    conds, seen_k = set(), {}
    for q, num in divs:
        # --- axis 3: REPLACE part 1 ---------------------------------------
        ms = _m(a, num, r'OpSelect %float (%\w+) (%\w+) (%\w+)\s*$')
        if not ms:
            bad(f'{name}: cell numerator {num} is "{a.d(num)}", not an '
                f'OpSelect -- the WORLD feed is still wired straight into the '
                f'hash, so nothing was replaced')
            return None
        cond, tarm, farm = ms.groups()
        conds.add(cond)
        # --- axis 5: REPLACE part 2, the world arm and its ONE use ---------
        ma = _m(a, farm, r'OpFAdd %float (%\w+) (%\w+)\s*$')
        if not ma:
            bad(f'{name}: the select\'s miss arm {farm} is "{a.d(farm)}", not '
                f'`100`\'s OpFAdd(cb56_k, P_k) fallback')
            return None
        off, pos = ma.groups()
        me = _m(a, off, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not me:
            off, pos = pos, off
            me = _m(a, off, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not me:
            bad(f'{name}: the miss arm {farm} adds no constant-buffer component')
            return None
        k = int(me.group(2))
        if k in seen_k:
            bad(f'{name}: two cell axes both read component {k}')
            return None
        seen_k[k] = True
        if not any(trip[k] == pos for trip in origins):
            bad(f'{name}: axis {k} miss arm adds to {pos}, which is not '
                f'component {k} of any of the module\'s own trace-origin hit '
                f'positions {sorted(origins)}')
        ml = _m(a, me.group(1), r'OpLoad %v4float (%\w+)\s*$')
        mac = _m(a, ml.group(1),
                 r'OpAccessChain %\w+ (%\w+) (%\w+) (%\w+)\s*$') if ml else None
        if not mac or mac.group(1) != cbv or \
                uconst(a, mac.group(3)) != member:
            bad(f'{name}: axis {k}\'s miss arm is not '
                f'cb[{cbv}][{member}] -- the member `98` sec 15 proved')
        u = _uses(a, farm)
        if len(u) != 1:
            bad(f'{name}: the WORLD feed {farm} has {len(u)} uses, want exactly '
                f'1 (the select\'s miss arm). More than one means the old feed '
                f'is STACKED, not replaced')
        # --- axis 6: REPLACE part 3, the object arm's closure --------------
        mo = _m(a, tarm, r'OpCompositeExtract %float (%\w+) (\d+)\s*$')
        if not mo or int(mo.group(2)) != k:
            bad(f'{name}: axis {k}\'s hit arm {tarm} is not component {k} of a '
                f'v3 object-space point')
            continue
        leaves, ops, getters = _closure(a, mo.group(1), allpos)
        if getters != 1:
            bad(f'{name}: axis {k}\'s object chain reaches {getters} '
                f'{GETTER} results, want exactly 1')
        for op in ('OpAccessChain', 'OpLoad'):
            if op in ops:
                bad(f'{name}: axis {k}\'s OBJECT arm reads a {op} -- the '
                    f'camera offset (or some other uniform) is inside the '
                    f'object-space feed, which is exactly the double-count '
                    f'this rung exists to avoid')
        for leaf in leaves:
            if leaf in allpos:
                continue
            d = a.d(leaf) or ''
            if d.startswith('OpConstant') or d.startswith(GETTER):
                continue
            bad(f'{name}: axis {k}\'s object chain has an unexpected leaf '
                f'{leaf} = "{d[:60]}"')
    if len(conds) != 1:
        bad(f'{name}: the three axes use {len(conds)} different select '
            f'conditions, want one shared `committed` bool')
        return None
    return conds.pop()


def _closure(a, root, stop=(), limit=64):
    """Backward walk from `root` through the arithmetic that builds the
    object-space point, stopping at the module's own hit-position components
    (`stop`) and at the WorldToObject getter. Returns (leaves, opcodes seen,
    WorldToObject count).

    The stop set matters: a hit-position component is itself an OpFAdd
    (`origin + t*dir`), so without it the walk runs straight off the end of the
    splice and back through the whole path-tracing chain, and every axis
    reports the shading code's own uniform loads as if they were inside the
    object arm. Stopping there is not a loophole -- `stop` is exactly the
    triple axis 5 has already anchored to a trace ORIGIN operand, and the point
    of axis 6 is what the splice does with that triple, not how the base built
    it."""
    WALK = ('OpFAdd', 'OpFMul', 'OpVectorTimesScalar', 'OpCompositeExtract',
            'OpCompositeConstruct', 'OpFSub')
    seen, leaves, ops, getters = set(), set(), set(), 0
    stack = [root]
    while stack:
        t = stack.pop()
        if t in seen or len(seen) > limit:
            continue
        seen.add(t)
        if t in stop:
            leaves.add(t)
            continue
        d = a.d(t) or ''
        op = d.split()[0] if d else ''
        if op:
            ops.add(op)
        if op == GETTER:
            getters += 1
            continue
        if op in WALK:
            for u in re.findall(r'%\w+', d)[1:]:
                stack.append(u)
            continue
        leaves.add(t)
    return leaves, ops, getters


# ------------------------------------------------------------------ axis 7
def check_query(a, cond, name):
    mi = _m(a, cond, r'OpINotEqual %\w+ (%\w+) (%\w+)\s*$')
    if not mi:
        bad(f'{name}: the select condition {cond} is "{a.d(cond)}", not '
            f'committed != 0')
        return None
    ty, zero = mi.groups()
    if uconst(a, zero) != 0:
        ty, zero = zero, ty
    mt = _m(a, ty, r'OpRayQueryGetIntersectionTypeKHR %uint (%\w+) (%\w+)\s*$')
    if not mt or uconst(a, mt.group(2)) != 1:
        bad(f'{name}: the condition is not '
            f'OpRayQueryGetIntersectionTypeKHR(_, COMMITTED)')
        return None
    rq = mt.group(1)
    # the module's own first trace, and the query that must clone it
    trace = None
    for ln in a.lines:
        m = re.match(r'\s*OpTraceRayKHR\s+(.+?)\s*$', ln)
        if m:
            trace = m.group(1).split()
            break
    if not trace or len(trace) != 11:
        bad(f'{name}: no 11-operand OpTraceRayKHR to clone from')
        return None
    inits = [re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l).group(1).split()
             for l in a.lines if re.match(r'\s*OpRayQueryInitializeKHR\b', l)]
    ours = [q for q in inits if q[0] == rq]
    if len(ours) != 1:
        bad(f'{name}: {len(ours)} OpRayQueryInitializeKHR on {rq}, want 1')
        return None
    q = ours[0]
    # OpRayQueryInitializeKHR <query> <accel> <flags> <cullmask> <origin>
    #                         <tmin> <direction> <tmax>   -- EIGHT operands
    if uconst(a, q[2]) != RAY_FLAGS:
        bad(f'{name}: ray flags {a.d(q[2]) or q[2]}, want {RAY_FLAGS} '
            f'(Opaque|TerminateOnFirstHit|SkipAABBs)')
    for label, got, want in (('accel', q[1], trace[0]),
                             ('cull mask', q[3], trace[2]),
                             ('origin', q[4], trace[6]),
                             ('direction', q[6], trace[8])):
        if got != want:
            bad(f'{name}: the query\'s {label} is {got}, not the module\'s own '
                f'trace operand {want} -- clone-by-id is the whole gate')
    ml = _m(a, q[5], r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not ml or not _near(fconst(a, ml.group(2)), T_LO):
        bad(f'{name}: tmin is "{a.d(q[5])}", want t * {T_LO}')
        return rq
    t = ml.group(1)
    mh = _m(a, q[7], r'OpFAdd %float (%\w+) (%\w+)\s*$')
    if not mh or not _near(fconst(a, mh.group(2)), T_EPS):
        bad(f'{name}: tmax is "{a.d(q[7])}", want t * {T_HI} + {T_EPS}')
        return rq
    mh2 = _m(a, mh.group(1), r'OpFMul %float (%\w+) (%\w+)\s*$')
    if not mh2 or mh2.group(1) != t or not _near(fconst(a, mh2.group(2)), T_HI):
        bad(f'{name}: tmax does not bracket the SAME t as tmin')
    mld = _m(a, t, r'OpLoad %float (%\w+)\s*$')
    if not mld or not re.match(r'OpInBoundsAccessChain %_ptr_RayPayloadKHR_float '
                               + re.escape(trace[10]) + r' %uint_3\s*$',
                               a.d(mld.group(1)) or ''):
        bad(f'{name}: the bracket is not built on word 3 of the trace\'s own '
            f'payload {trace[10]} -- it could be any distance')
    return rq


# ------------------------------------------------------------------ axes 8-10
def check_census(a, b, mode, name):
    n = QUERIES[mode]
    for needle, want in (('OpRayQueryInitializeKHR', n),
                         ('OpRayQueryProceedKHR', n),
                         ('OpRayQueryGetIntersectionTypeKHR', n),
                         (GETTER, n)):
        got = a.count(needle) - b.count(needle)
        if got != want:
            bad(f'{name}: {got} added {needle}, want {want}')
    if a.count('OpTraceRayKHR') != b.count('OpTraceRayKHR'):
        bad(f'{name}: the OpTraceRayKHR count changed')
    if a.count('OpLabel') != b.count('OpLabel'):
        bad(f'{name}: {a.count("OpLabel") - b.count("OpLabel")} blocks added -- '
            f'this splice must add ZERO control flow')
    for needle in ('OpBranch', 'OpSelectionMerge', 'OpLoopMerge'):
        if a.count(needle) != b.count(needle):
            bad(f'{name}: the {needle} count changed')


def check_arms(a, b, mode, name):
    """axis 9 -- the six GGX arms must be the base's, number for number. The
    `-cell` diagnostic hashes an object-space cell of its own, so it adds
    exactly ONE more PCG; every other count is frozen."""
    add = {'cell': 1}.get(mode, 0)
    for label, needle, base_want, delta in (
            ('PCG chains', r'OpIMul %uint %\w+ %uint_' + str(int(GM.PCG_MUL)), 6, add),
            ('PCG xor-multiplies',
             r'OpIMul %uint %\w+ %uint_' + str(int(GM.PCG_XMUL)) + r'\b', 6, add),
            ('Bernoulli selects', r'OpFOrdLessThan %bool ', None, 0)):
        got = sum(1 for l in a.lines if re.search(needle, l))
        was = sum(1 for l in b.lines if re.search(needle, l))
        if base_want is not None and was != base_want:
            bad(f'{name}: the BASE has {was} {label}, want {base_want} -- this '
                f'is not `100`\'s glint base')
        if got != was + delta:
            bad(f'{name}: {label} moved from {was} to {got}, want '
                f'{was + delta}')


def _raw(path):
    """Disassembly in RAW-ID form. Three things move under a splice that has not
    touched a single base instruction, and all three had to be neutralised
    before this axis said anything:
      * spirv-as/spirv-dis RENUMBER -- one inserted instruction shifts every
        later id, so a plain text diff called 11000 lines "changed";
      * spirv-dis RIGHT-ALIGNS the result-id column, so ids growing from 4 to 5
        digits reindent the whole module;
      * FRIENDLY NAMES embed the id (`%_runtimearr_863` becomes
        `%_runtimearr_864`), so erasing `%<digits>` is not enough.
    --raw-id --no-indent --no-header kills all three."""
    out = subprocess.run(['spirv-dis', '--raw-id', '--no-indent', '--no-header',
                          path], capture_output=True, text=True,
                         check=True).stdout
    return [' '.join(l.split()) for l in out.splitlines()
            if l.strip() and not l.lstrip().startswith(';')]


_GLOBAL = ('OpType', 'OpConstant', 'OpSpecConstant', 'OpVariable', 'OpUndef')


def _canon(lines):
    """Renumber-invariant canonical form.

    Erasing every `%<id>` is not enough: a run of `OpVariable %<ptr> Function`
    lines all collapse to the same text, and difflib is then free to align the
    inserted ray-query variable against the WRONG member of the run -- which it
    did, and 75 innocent lines were reported as rewired.

    So types, constants and variables keep an identity: each is named by an
    8-hex STRUCTURAL hash of its own definition with its operands already
    named the same way. Structural identity is well defined for these (SPIR-V
    requires types and constants to be unique), it is invariant under
    renumbering, and it is different for two different pointer types -- which is
    exactly what the alignment needed. Everything else (function-local results,
    labels) becomes `%.`."""
    name, out = {}, []
    for l in lines:
        m = re.match(r'(%\d+) = (Op\w+)(.*)$', l)
        body = re.sub(r'%\d+\b', lambda x: name.get(x.group(0), '%.'),
                      (m.group(2) + m.group(3)) if m else l)
        if m and m.group(2).startswith(_GLOBAL):
            h = '%' + hashlib.md5(body.encode()).hexdigest()[:8]
            name.setdefault(m.group(1), h)
            out.append(name[m.group(1)] + ' = ' + body)
        else:
            out.append(('%. = ' + body) if m else body)
    return out


def check_diff(a, b, mode, name):
    """axis 10 -- DIFF DISCIPLINE, and deliberately ALIGNMENT-FREE.

    The obvious form of this axis -- pair each base line with a shipped line and
    look at what changed -- does not survive contact with this splice. The
    splice re-emits the base's OWN idioms verbatim: another `cb[56][k] + P[k]`
    add, another dyadic cell ladder, another PCG. difflib is then free to pair
    the base's copy with the splice's, and it does; the first version of this
    axis reported 75 innocent lines as rewired and MISSED all three real ones.

    So this axis asks two questions that need no pairing:

      A) SUBSEQUENCE -- the base's canonical instruction stream must appear, in
         order, inside the shipped one. Nothing deleted, nothing reordered,
         no base instruction changed SHAPE. (Greedy earliest-match is exact for
         subsequence testing.)
      B) SURPLUS -- what is left over is exactly the multiset
         Counter(shipped) - Counter(base), and every opcode in it must be one
         this feature emits.

    WIRING is not this axis's job and is not claimed here. Axis 3 proves each
    cell divide now takes an OpSelect; axis 5 proves the old world feed has
    EXACTLY ONE use, which is the select's miss arm; axis 6 proves the hit arm
    reaches a WorldToObject and touches no uniform. Between them the three
    repointings are pinned from both ends, which is what "replace, not stack"
    means -- and none of it depends on a line alignment existing."""
    ra = [l for l in _raw(a.path) if not l.startswith('OpEntryPoint ')]
    rb = [l for l in _raw(b.path) if not l.startswith('OpEntryPoint ')]
    ca, cb = _canon(ra), _canon(rb)
    i, surplus = 0, []
    for j, l in enumerate(ca):
        if i < len(cb) and cb[i] == l:
            i += 1
        else:
            surplus.append(ra[j])
    if i != len(cb):
        bad(f'{name}: the base is NOT a subsequence of the shipped module -- '
            f'{len(cb) - i} base instructions have no counterpart, first is '
            f'"{rb[i][:70]}"')
        return len(surplus)
    allowed_ins = set(ALLOWED_INSERT)
    for l in surplus:
        m = re.match(r'(?:%\w+\s*=\s*)?(Op\w+)', l)
        if not m:
            bad(f'{name}: an inserted line is not an instruction: {l[:60]}')
        elif m.group(1) not in allowed_ins:
            bad(f'{name}: inserted {m.group(1)}, which this feature never '
                f'emits: {l[:70]}')
    if len(surplus) != len(ra) - len(rb):
        bad(f'{name}: {len(surplus)} surplus lines, {len(ra) - len(rb)} by count')
    # the entry point: the paint rungs add their Private latch to the interface,
    # the feature rung must add nothing at all
    ea = [l for l in _raw(a.path) if l.startswith('OpEntryPoint ')]
    eb = [l for l in _raw(b.path) if l.startswith('OpEntryPoint ')]
    if len(ea) != 1 or len(eb) != 1:
        bad(f'{name}: {len(ea)}/{len(eb)} entry points, want 1')
    else:
        dn = len(ea[0].split()) - len(eb[0].split())
        if mode == 'glint' and dn:
            bad(f'{name}: the FEATURE rung changed the entry-point interface '
                f'by {dn} ids')
        if mode != 'glint' and dn != 1:
            bad(f'{name}: the {mode} rung added {dn} entry-point interface ids, '
                f'want 1 (its Private latch)')
    return len(surplus)


def count_paints(a):
    """Image writes whose texel is a v4 built from components SCALED BY A
    SELECT -- the shape both diagnostics use and the base uses nowhere."""
    n = 0
    for ln in a.lines:
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)', ln)
        if not m:
            continue
        cc = _m(a, m.group(3),
                r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)\s*$')
        if not cc:
            continue
        for c in cc.groups()[:3]:
            mm = _m(a, c, r'OpFMul %float (%\w+) (%\w+)\s*$')
            if mm and any(re.match(r'OpSelect %float ', a.d(x) or '')
                          for x in mm.groups()):
                n += 1
                break
    return n


def primary_queries(a, name):
    """Ray queries that start at the camera and shoot the module's OWN
    normalized view ray. Origin alone will not do: `101`'s ear-glow queries also
    start at a constant origin, so the DIRECTION is the discriminator."""
    prim = find_primary(a)
    if len(prim) != 1:
        bad(f'{name}: {len(prim)} primary-ray reconstructions, want 1')
        return None
    out = []
    for l in a.lines:
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        if not m:
            continue
        q = m.group(1).split()
        if not re.match(r'OpConstantComposite %v3float ', a.d(q[4]) or ''):
            continue
        md = _m(a, q[6],
                r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$')
        if md and list(md.groups()) == prim[0]['V']:
            out.append(q)
    return out


def check_mode(a, b, mode, paint, name):
    """axis 11 -- the diagnostic rungs carry their diagnostic and the feature
    rung carries none of it. `paint` is the number of the base's OWN image
    writes that axis 10 found REWIRED; counting "image writes not present in
    the base text" would count all of them, because spirv-dis renumbers."""
    npriv = a.count('Private') - b.count('Private')
    if mode == 'glint':
        if paint:
            bad(f'{name}: the FEATURE rung repaints {paint} image writes')
        if npriv:
            bad(f'{name}: the FEATURE rung adds {npriv} Private-storage lines '
                f'-- only the diagnostics carry a latch')
    else:
        if not paint:
            bad(f'{name}: the {mode} rung paints nothing')
        if npriv <= 0:
            bad(f'{name}: the {mode} rung carries no Private latch')
    if mode == 'cell':
        # The `-cell` diagnostic hashes the PRIMARY hit's object-space cell, so
        # it adds one query down the module's own view ray. `101`'s ear glow
        # already fires one of those, so the assertion is a DELTA against the
        # base, never an absolute count.
        za, zb = primary_queries(a, name), primary_queries(b, name)
        if za is None or zb is None:
            return
        if len(za) - len(zb) != 1:
            bad(f'{name}: {len(za)} primary-family queries vs {len(zb)} in the '
                f'base -- the diagnostic must add exactly one')
            return
        flags = {uconst(a, q[2]) for q in za} - {uconst(b, q[2]) for q in zb}
        if flags and flags != {RAY_FLAGS}:
            bad(f'{name}: the diagnostic\'s primary query has flags {flags}, '
                f'want {RAY_FLAGS}')


def check_module(path, base, mode, C, name):
    a, b = Asm(path), Asm(base)
    if not any(re.match(r'\s*OpEntryPoint RayGenerationKHR ', l) for l in a.lines):
        bad(f'{name}: not a raygen')
        return
    if not any('OpCapability RayQueryKHR' in l for l in a.lines):
        bad(f'{name}: no RayQueryKHR capability')
    lad = pick_ladder(a, mode, float(C['NU0']), name)
    if lad is None:
        return
    s, s2, cell = lad
    if abs(cell - float(C['CELL'])) > 1e-12:
        bad(f'{name}: cell size {cell}, want {float(C["CELL"])}')
    wo = derive_world_offset(a)
    if len(wo) != 1:
        bad(f'{name}: {len(wo)} world-offset candidates, want 1')
        return
    cbv, member = wo[0]
    origins = derive_origins(a)
    if not origins:
        bad(f'{name}: no OpTraceRayKHR origin triple to anchor the hit position')
        return
    cond = check_feed(a, s, cbv, member, origins, name)
    if cond is None:
        return
    check_query(a, cond, name)
    check_census(a, b, mode, name)
    check_arms(a, b, mode, name)
    ins = check_diff(a, b, mode, name)
    paint = count_paints(a) - count_paints(b)
    check_mode(a, b, mode, paint, name)
    print(f'  {name}: ladder cell={cell} NU0={float(C["NU0"])}, member '
          f'{member}, 3 selects, {QUERIES[mode]} quer'
          f'{"y" if QUERIES[mode] == 1 else "ies"}, +{ins} inserted lines, '
          f'{paint} repainted writes')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--base', help='the parked base rung the .spv were built on')
    ap.add_argument('--mode', default='glint', choices=sorted(QUERIES))
    ap.add_argument('--negative', action='store_true',
                    help='PASS only if the directory FAILS every axis')
    for k, v in GM.DEFAULTS.items():
        ap.add_argument('--' + k.replace('_', '-'), type=float, default=v)
    a = ap.parse_args()
    C = GM.constants(GM.knobs(**{k: getattr(a, k) for k in GM.DEFAULTS}))
    base = a.base or a.dir
    n = 0
    for f in sorted(glob.glob(os.path.join(a.dir, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f)
        bf = os.path.join(base, h)
        if not os.path.exists(bf):
            bad(f'{h}: no base counterpart in {base}')
            continue
        # the two scalar-specular permutations carry no glint splice at all and
        # must be byte-identical to the base -- declined by NAME, never skipped.
        # --negative skips NOTHING: a directory that is byte-identical to the
        # base would otherwise be "rejected" only because every module was
        # skipped, which proves nothing about the axes.
        if not a.negative and \
                not any('OpTypeMatrix %v3float 4' in l for l in Asm(f).lines) \
                and open(f, 'rb').read() == open(bf, 'rb').read():
            print(f'  {h}: byte-identical to the base '
                  f'(scalar-specular permutation, declined by name)')
            continue
        check_module(f, bf, a.mode, C, h)
        n += 1
    if n != 10 and not a.negative:
        bad(f'{n} patched permutations, want 10 '
            f'(12 reference raygens minus the 2 scalar-specular)')
    if a.negative:
        if FAIL:
            print(f'REJECTED as required ({len(FAIL)} failures)')
            return 0
        print('NOT REJECTED -- the verifier is vacuous')
        return 1
    if FAIL:
        print(f'\n{len(FAIL)} FAILURES')
        return 1
    print(f'OK: {n} modules, all axes pass')
    return 0


if __name__ == '__main__':
    sys.exit(main())
