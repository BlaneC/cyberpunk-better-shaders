#!/usr/bin/env python3
"""hunt-rayq: does a Vulkan RAY QUERY execute inside rgs_reference_main, and
does it return the per-instance identity the payload does not carry?

handoff/98-RAYQUERY.md is the document; read its section 5 (the pre-registered
outcome table) BEFORE looking at a frame.

Why this exists
---------------
94 sec 2.2 measured the reference raygen's payload:

    OpTypeStruct { uint, uint, float, float }
      word0  baseColor.rgb (bytes 0..2) + METALLIC (byte 3)
      word1  octahedral normal (12+12) + ROUGHNESS (byte 3)
      word2  a scalar
      word3  t   (10000.0 == miss)

No class, no subtype, no object id, no UV, no barycentrics. Every feature that
wants to know WHICH THING was hit -- per-vehicle paint, per-instance material
overrides, object-stable hashes for flakes/decals -- is blocked at that struct.

A ray query is a second G-buffer: it re-traverses the SAME acceleration
structure the module already traces, inline, and its result object exposes
InstanceId / InstanceCustomIndex / PrimitiveIndex / geometry index / object-to-
world matrices -- none of which the payload has. 0 of 3322 dumped modules
declare SPV_KHR_ray_query, so nothing in this renderer has ever done it here.

What the splice does, per rgs_reference_main permutation
-------------------------------------------------------
Immediately after the module's FIRST OpTraceRayKHR (the path loop's radiance
trace -- the identical site 55's sentinel injected at, which is proven on
screen to execute, 56 sec 2):

    t     = payload[3]                        ; the hit distance just written
    tmin  = t * 0.999
    tmax  = t * 1.001 + 1e-4                  ; the +eps covers t -> 0
    OpRayQueryInitializeKHR %rq <accel> 517 <cullMask> <origin> tmin <dir> tmax
    OpRayQueryProceedKHR %rq
    committed = OpRayQueryGetIntersectionTypeKHR(%rq, 1) != 0
    field     = OpRayQueryGetIntersection{InstanceId,InstanceCustomIndex,
                                         PrimitiveIndex}KHR(%rq, 1)

<accel>, <cullMask>, <origin> and <dir> are the module's OWN operand ids,
cloned verbatim from that trace (55's clone-by-id discipline -- it is what
made the injected trace execute where 26 sec 7d's hand-picked operands did
not). The tight bracket around the trace's own t makes the query re-find the
same hit and makes it cheap: it is a re-traversal of one already-known
segment, not a new ray.

Ray flags 517 = OpaqueKHR(0x01) | TerminateOnFirstHitKHR(0x04) |
SkipAABBsKHR(0x200), and the choice is deliberate, not a default:

  * A ray query has NO any-hit shader. A candidate on non-opaque geometry
    (alpha-tested hair, foliage, chain-link) is handed back to the shader for
    OpRayQueryConfirmIntersectionKHR, and a query that never confirms would
    return "no committed intersection" on EXACTLY the surfaces this probe
    cares most about -- and that null would read identically to "the ray query
    did not execute". OpaqueKHR forces every candidate committed, so the hit
    cannot be lost. Priced: an alpha-CUT hole can now commit its card. It only
    matters if that card sits inside the +-0.1% bracket around the trace's own
    hit distance (5 mm at 5 m), so it is a rare mis-attribution, not a
    systematic one. The alternative -- CullNoOpaqueKHR -- loses hair
    systematically, which is worse.
  * SkipAABBsKHR removes procedural (AABB) candidates, which are the OTHER
    thing that makes OpRayQueryProceedKHR return true. It needs capability
    RayTraversalPrimitiveCullingKHR, which all twelve permutations already
    declare (asserted below).
  * With those two, no candidate can ever require shader processing, so ONE
    OpRayQueryProceedKHR completes traversal and returns false. That is why
    this patcher emits no loop and no new control flow at all -- which is also
    why it cannot perturb the module's structured-control-flow graph.
  * TerminateOnFirstHitKHR ends traversal at the first accepted hit. Inside a
    0.2%-wide t bracket that hit is the hit, and it caps the cost.

The latch and the identity-when-dead construction
-------------------------------------------------
Two Private uints, stored 0 in the entry block (which dominates everything):

    rq_state  0 = the query never executed
              1 = it executed and committed NOTHING
              2 = it executed and committed a hit
    rq_id     the chosen field, 0 unless committed

The trace is inside the path loop, so the splice runs once per path segment.
Both stores are FIRST-WRITE-WINS (a pure OpSelect on `rq_state == 0`, no
branch), so what reaches the paint is the FIRST traced segment of the FIRST
sample -- deterministic per invocation, and the one segment whose ray origin
is the primary G-buffer surface.

At every radiance write the texel RGB is multiplied by a chain rooted at 1.0:

    rq_state == 0  ->  x1.0        vanilla, bit-exact. If the query never ran,
                                   the rung is the base image. This is the
                                   built-in negative control, and it is the
                                   same construction 55 used.
    rq_state == 1  ->  BLACK       "ran, found nothing". The sky is this by
                                   construction: a primary miss writes
                                   t = 10000, the bracket sits at 9990..10010,
                                   and nothing is there.
    rq_state == 2  ->  hue[h & 7]  h = (id * 2654435761) ^ ((id * 2654435761)
                                   >> 15). Eight hues; see PALETTE.

--gain 0 keeps every instruction and every ray query but collapses each
multiplier to exactly 1.0, so the control rung is byte-DISTINCT from the base
(the query really is executing) and must be VISUALLY identical to it. That is
the control the sentinel never had: it separates "the ray query changes the
picture" from "the ray query breaks the picture".

Usage:
    python3 dev/patch_rayq.py <mod.spvasm> --outdir DIR
                              [--field id|custom|prim|sbt|geom|xf]
                              [--site bounce|primary] [--gain 1.0]
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish

# SPIR-V enumerants. These are NOT in any header this file can include, so
# each one is stated with where it was checked. swap_layer.c learned the hard
# way (its SER capability was 5345 for a while, and the guard was dead).
SPV_CAP_RAY_QUERY = 4472          # Capability RayQueryKHR
RAY_FLAGS = 0x01 | 0x04 | 0x200   # Opaque | TerminateOnFirstHit | SkipAABBs

# Two commit modes, and BOTH need exactly one OpRayQueryProceedKHR -- which is
# the whole reason this splice adds zero control flow (98 sec 2.3).
#
#   Proceed returns true only when traversal has produced a CANDIDATE the
#   shader must resolve: a non-opaque triangle (alpha test) or an AABB
#   (procedural intersection).  RayFlagsOpaqueKHR forces every candidate
#   opaque and SkipAABBsKHR removes the AABB case, so no candidate can ever
#   need shader intervention and the first Proceed runs traversal to
#   completion and returns false.
#
#   TerminateOnFirstHit does NOT participate in that argument.  It changes
#   WHICH intersection ends up committed -- any hit in range vs the nearest
#   one -- not whether the shader is asked to resolve a candidate.  Dropping
#   it therefore buys a closest-hit query at zero control-flow cost, which is
#   what 'closest' is: the same body, one bit different in one constant.
COMMIT_FLAGS = {
    'first':   (0x01 | 0x04 | 0x200, 'OpaqueKHR|TerminateOnFirstHitKHR|SkipAABBsKHR'),
    'closest': (0x01 | 0x200,        'OpaqueKHR|SkipAABBsKHR'),
}
COMMITTED = 1                     # RayQueryCommittedIntersectionKHR operand
GOLDEN = 2654435761               # Knuth's 2^32/phi -- the hash multiplier

FIELDS = {
    'id':     ('OpRayQueryGetIntersectionInstanceIdKHR',
               'InstanceId: the index of the instance inside its TLAS'),
    'custom': ('OpRayQueryGetIntersectionInstanceCustomIndexKHR',
               'InstanceCustomIndex: the 24-bit value the app wrote into '
               'VkAccelerationStructureInstanceKHR::instanceCustomIndex'),
    'prim':   ('OpRayQueryGetIntersectionPrimitiveIndexKHR',
               'PrimitiveIndex: the triangle index within its geometry'),
    # --- added for 98 sec 13, after -pprim proved BOTH instance fields are
    #     per-frame: the identity, if there is one, is not in the instance slot.
    'sbt':    ('OpRayQueryGetIntersectionInstanceShaderBindingTableRecordOffsetKHR',
               'instanceShaderBindingTableRecordOffset: the app-assigned hit-'
               'group offset in VkAccelerationStructureInstanceKHR. It selects '
               'WHICH SHADER RECORD runs, so in this engine it plausibly names '
               'the MATERIAL, and a material assignment has no reason to be '
               'rewritten when the TLAS is rebuilt'),
    'geom':   ('OpRayQueryGetIntersectionGeometryIndexKHR',
               'GeometryIndex: which geometry of the hit BLAS. Stable per '
               'geometry WITHIN a BLAS and NOT unique across BLASes, so a few '
               'hues over the whole frame is the expected reading, not a fault'),
    'xf':     ('OpRayQueryGetIntersectionObjectToWorldKHR',
               "ObjectToWorld[3], RAW BITS: the hit instance's world "
               'translation, bitcast and XOR-folded. A static object has a '
               'bit-identical transform every frame and a moving one does not, '
               'so buildings stable + cars/NPCs flickering IS the signature, '
               'not a defect'),
    # --- added for 98 sec 14, after -pxf flickered on static buildings and the
    #     user's read-out ("if anything moved it would flicker") pointed at the
    #     THIRD reading 13.7 missed: the TLAS is built in CAMERA-RELATIVE
    #     space, so a static instance's ObjectToWorld translation is
    #     (world - camera) and changes exactly when the camera moves.
    'xfq':    ('OpRayQueryGetIntersectionObjectToWorldKHR',
               'ObjectToWorld[3], QUANTISED to 1 cm (x100 -> OpConvertFToS -> '
               'OpBitcast) with NO offset. The CONTROL for xfw: under the '
               'camera-relative reading it still flickers with camera motion, '
               'because quantising a value that genuinely changes does not '
               'make it stop changing'),
    'xfw':    ('OpRayQueryGetIntersectionObjectToWorldKHR',
               "ObjectToWorld[3] + cbv[..][56].xyz -- 94 sec 3.3's world "
               'offset, the same CB member the shader itself adds to the hit '
               'position before storing it in the ReSTIR-GI reservoir -- then '
               'the same 1 cm quantisation. If the TLAS is camera-relative '
               'this is a frame-stable WORLD translation: static buildings '
               'flat and stable under camera motion, movers changing'),
}

# Fields whose getter does not return a uint. Only one so far, and it is the
# reason this table exists rather than an `if field == 'xf'`: the splice has to
# know the RESULT TYPE (which it may have to declare) and how to fold it down
# to the single uint the latch and the hash chain take.
#
# OpRayQueryGetIntersectionObjectToWorldKHR returns a 4-column matrix of
# 3-component vectors (SPV_KHR_ray_query: "Result Type must be a matrix with
# four columns of three-component vector of floating-point type"). Column 3 is
# the translation -- the object's world position. It is folded as
#
#     bitcast(x) ^ bitcast(y) ^ bitcast(z)
#
# with NO quantisation, deliberately. Quantising would smear a moving object
# into a stable bucket and destroy the very asymmetry the rung is for.
#
# `xfq` and `xfw` keep the same getter, the same column and the same XOR fold
# and differ from `xf` -- and from each other -- in exactly two dials:
#
#   quantise : None, or a float grid step in metres**-1. 100.0 means the three
#              components are multiplied by 100, OpConvertFToS'd to a signed
#              32-bit integer and OpBitcast to uint, i.e. rounded to 1 cm
#              before they reach the hash. It exists because a WORLD
#              translation reconstructed as (world - camera) + camera is not
#              bit-stable in fp32 even when the object has not moved, and a
#              raw-bits hash turns the last mantissa bit into a different hue.
#              The KNOWN DEFECT is the flip side: a component sitting within
#              fp32 rounding of a 1 cm boundary can cross it as the camera
#              moves, so a small minority of static objects may alternate
#              between two hues. That is a BOUNDARY artefact, not a per-frame
#              rewrite, and the discriminator is that MOST buildings hold.
#   offset   : add 94 sec 3.3's world offset before quantising. See
#              _find_world_offset for how the CB member is located -- by
#              structure, in every module, never by index.
MATRIX_FIELDS = {
    'xf':  {'type_name': 'mat4v3float',
            'type_decl': 'OpTypeMatrix %v3float 4',
            'column': 3, 'quantise': None, 'offset': False},
    'xfq': {'type_name': 'mat4v3float',
            'type_decl': 'OpTypeMatrix %v3float 4',
            'column': 3, 'quantise': 100.0, 'offset': False},
    'xfw': {'type_name': 'mat4v3float',
            'type_decl': 'OpTypeMatrix %v3float 4',
            'column': 3, 'quantise': 100.0, 'offset': True},
}

# name -> rgb multiplier at gain 1. Eight buckets, chosen to be mutually
# distinguishable on a photograph and none of them near neutral.
PALETTE = [
    ('red',     (3.00, 0.20, 0.20)),
    ('orange',  (3.00, 1.20, 0.20)),
    ('yellow',  (3.00, 3.00, 0.20)),
    ('green',   (0.20, 3.00, 0.20)),
    ('cyan',    (0.20, 3.00, 3.00)),
    ('blue',    (0.20, 0.60, 3.00)),
    ('magenta', (3.00, 0.20, 3.00)),
    ('white',   (2.40, 2.40, 2.40)),
]
# The no-hit multiplier is site-dependent, and deliberately so.
#
#   bounce : black. The bounce ray HAS a hit distance in the payload, so a
#            query that commits nothing means the bracket was empty -- a
#            failure worth seeing, and distinguishable from "never ran"
#            (which stays at 1.0, i.e. the base image).
#   primary: IDENTITY. The primary ray legitimately misses on every sky
#            pixel, and the sky staying unpainted is this rung's built-in
#            control (the `56` sky argument): if the sky comes back COLOURED,
#            the query is committing garbage and the frame is void. Painting
#            it black instead would throw that control away and would make a
#            correct frame look broken.
NOHIT = {
    'bounce':  ('black',     (0.0, 0.0, 0.0)),
    'primary': ('unpainted', (1.0, 1.0, 1.0)),
}
SITES = ('bounce', 'primary')

TRACE_RE = re.compile(r'^(\s*)OpTraceRayKHR\s+(.+?)\s*$')


# ------------------------------------------------------------ small helpers
def _entry(mod, model):
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*OpEntryPoint ' + model + r' (%\w+) "', ln)
        if m:
            return i, m.group(1)
    die(f"{mod.name}: no {model} entry point")


def _func_span(mod, fid):
    s = None
    for i, ln in enumerate(mod.lines):
        if re.match(r'\s*' + re.escape(fid) + r'\s*=\s*OpFunction\b', ln):
            s = i
        elif s is not None and 'OpFunctionEnd' in ln:
            return s, i
    die(f"{mod.name}: no function body for {fid}")


def _assert_payload_float3(mod, payload):
    """The trace's payload variable must be a struct whose member 3 is float
    (94 sec 2.2: word3 is the hit distance t). Anything else and the bracket
    would be built out of a bit pattern."""
    _, d = mod.find_def(payload)
    m = re.match(r'OpVariable (%\w+) RayPayloadKHR\s*$', d or '')
    if not m:
        die(f"{mod.name}: trace payload {payload} is not a RayPayloadKHR variable")
    _, pd = mod.find_def(m.group(1))
    mp = re.match(r'OpTypePointer RayPayloadKHR (%\w+)\s*$', pd or '')
    if not mp:
        die(f"{mod.name}: payload pointer type of {payload} unreadable")
    _, sd = mod.find_def(mp.group(1))
    if not (sd or '').startswith('OpTypeStruct'):
        die(f"{mod.name}: payload {payload} is not a struct")
    mem = sd.split()[1:]
    if len(mem) < 4 or mem[3] != '%float':
        die(f"{mod.name}: payload struct member 3 is "
            f"{mem[3] if len(mem) > 3 else 'missing'}, expected %float (t)")
    return mp.group(1)


def _ensure_line(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def _uc(mod, consts, v):
    nid, decl = mod.uconst(v)
    if decl:
        consts.append(decl)
    return nid


def _fc(mod, consts, v):
    nid, decl = mod.const(v)
    if decl:
        consts.append(decl)
    return nid


# ------------------------------------------------------------------- build
def _find_primary_ray(mod, fs, fe):
    """Locate the module's OWN primary view ray, structurally.

    The reference raygen reconstructs the primary hit from the depth buffer
    with a 4x4 transform and a perspective divide, then normalises it and uses
    the result as the view ray (`94` sec 3.3, in vanilla ids:
    `%361..%363 = normalize(%354..%356)`). That is only valid with the camera
    at the ORIGIN of that space, which is the same fact `94` records: P is
    camera-relative. So the shape to match is

        %P{0,1,2} = OpFDiv ... %w            <- perspective divide, shared %w
        %pa = OpCompositeConstruct %v3float %P0 %P1 %P2
        %pb = OpCompositeConstruct %v3float %P0 %P1 %P2
        %d  = OpDot %float %pa %pb
        %r  = OpExtInst %float %1 InverseSqrt %d
        %V{0,1,2} = OpFMul %float (%r, %Pk)  in either operand order

    The perspective-divide requirement is what makes this the PRIMARY
    reconstruction rather than any other normalize in a module that contains
    a dozen of them -- and the function REFUSES unless it finds exactly one,
    so nothing here is a positional guess (GOTCHAS 10).

    |P| falls out for free and exactly, with one instruction and no new
    constant: |P| = dot(P,P) * rsqrt(dot(P,P)) = %d * %r.
    """
    defs = {}
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+) = (Op\w+)(?: %\w+)?(.*)$', mod.lines[i])
        if m:
            defs[m.group(1)] = (m.group(2), m.group(3).split(), i)
    found = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ InverseSqrt (%\w+)\s*$',
                     mod.lines[i])
        if not m:
            continue
        rsq, dot = m.groups()
        dd = defs.get(dot)
        if not dd or dd[0] != 'OpDot' or len(dd[1]) < 2:
            continue
        ca, cb = defs.get(dd[1][0]), defs.get(dd[1][1])
        if not ca or not cb:
            continue
        if ca[0] != 'OpCompositeConstruct' or cb[0] != 'OpCompositeConstruct':
            continue
        if ca[1] != cb[1] or len(ca[1]) != 3:
            continue
        P = ca[1]
        divs = [defs.get(x) for x in P]
        if not all(d and d[0] == 'OpFDiv' and len(d[1]) == 2 for d in divs):
            continue
        if len({d[1][1] for d in divs}) != 1:      # one shared denominator
            continue
        V = []
        for comp in P:
            hit = None
            for j in range(i + 1, min(i + 16, fe)):
                mm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) (%\w+)\s*$',
                              mod.lines[j])
                if mm and {mm.group(2), mm.group(3)} == {rsq, comp}:
                    hit = mm.group(1)
                    break
            V.append(hit)
        if any(v is None for v in V):
            continue
        found.append({'line': i + 1, 'P': P, 'dot': dot, 'rsqrt': rsq,
                      'V': V, 'w': divs[0][1][1]})
    if len(found) != 1:
        die(f"{mod.name}: expected exactly ONE primary-ray reconstruction "
            f"(perspective divide -> normalize), found {len(found)}")
    return found[0]


def _find_world_offset(mod, fs, fe):
    """Locate `94` sec 3.3's world offset -- STRUCTURALLY, in this module.

    `94` sec 3.3 identifies it as `cbv[104][56].xyz`, where 104 is that dump's
    SSA id for the bindless-CBV access chain and 56 is the member index. An id
    is not a fact about the bytes we ship (every permutation renumbers), so the
    member is re-derived from the property that made `94` believe it:

        the CB member whose .xyz is added, component by component, to the
        module's own PATH-VERTEX HIT POSITION -- the v3 triple that is the
        origin operand of the module's own shadow/NEE OpTraceRayKHR sites.

    That is the same pair of consumers `94` cites (the ReSTIR-GI reservoir
    store and the light vector), reduced to the one shape a script can check.
    Over the 10 patchable permutations of the standing base it resolves to
    member **56** in 10/10 and to exactly ONE (cbv, member, position) triple
    per module: a second candidate (member 5) is added to a triple that is
    never a trace origin, and it is excluded by that clause alone. If the
    match is not unique the function DIES rather than picking (GOTCHAS 10).

    Sign convention, read off the base and NOT assumed: the base adds --
    `OpFAdd(cb56.c, P.c)` -- and the corroborating site is
    `(L.c - P.c) - cb56.c`, i.e. `L - (P + cb56)`. So world = position +
    offset, and the splice emits `OpFAdd %float <cb56.c> <translation.c>`,
    the offset first, matching the operand order of `94`'s own quoted
    `%1419 = OpFAdd %float %1416 %727`.
    """
    defs = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = (.*?)\s*$', ln)
        if m:
            defs.setdefault(m.group(1), (m.group(2), i))

    def d(x):
        return defs.get(x, ('', None))[0]

    # every OpTraceRayKHR origin that is an explicit v3 construct
    origins = set()
    for i in range(fs, fe):
        m = TRACE_RE.match(mod.lines[i])
        if not m:
            continue
        ops = m.group(2).split()
        if len(ops) != 11:
            continue
        cc = re.match(r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)\s*$',
                      d(ops[6]))
        if cc:
            origins.add(cc.groups())

    # extract_k(load(OpAccessChain <ptr_uniform_v4> <cbv> %uint_0 %uint_M))
    ex = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+) = OpCompositeExtract %float (%\w+) (\d+)\s*$', ln)
        if not m:
            continue
        ld = re.match(r'OpLoad %v4float (%\w+)\s*$', d(m.group(2)))
        if not ld:
            continue
        ac = re.match(r'OpAccessChain (%\w+) (%\w+) (%\w+) (%\w+)\s*$',
                      d(ld.group(1)))
        if not ac:
            continue
        i0 = re.match(r'OpConstant %uint (\d+)\s*$', d(ac.group(3)))
        i1 = re.match(r'OpConstant %uint (\d+)\s*$', d(ac.group(4)))
        if not i0 or not i1 or i0.group(1) != '0':
            continue
        ex[m.group(1)] = (ac.group(2), ac.group(1), int(i1.group(1)),
                          int(m.group(3)))

    # (cbv, member) -> component -> {the other operand of the FAdd}
    per = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*%\w+ = OpFAdd %float (%\w+) (%\w+)\s*$', ln)
        if not m:
            continue
        for u, v in ((m.group(1), m.group(2)), (m.group(2), m.group(1))):
            if u in ex:
                cbv, pty, mem, comp = ex[u]
                per.setdefault((cbv, pty, mem), {}).setdefault(comp, set()).add(v)

    hits = []
    for (cbv, pty, mem), byc in per.items():
        if set(byc) != {0, 1, 2}:
            continue
        for trip in origins:
            if all(trip[k] in byc[k] for k in range(3)):
                hits.append({'cbv': cbv, 'ptr_type': pty, 'member': mem,
                             'position': list(trip),
                             'cbv_line': defs[cbv][1] + 1})
    if len(hits) != 1:
        die(f"{mod.name}: expected exactly ONE (bindless CBV, member) whose "
            f".xyz is added component-wise to a trace-origin hit position "
            f"(94 sec 3.3's world offset), found {len(hits)}")
    h = hits[0]
    cbd = d(h['cbv'])
    if not cbd.startswith('OpAccessChain %_ptr_Uniform_BindlessCBV'):
        die(f"{mod.name}: the world offset's base {h['cbv']} is '{cbd}', not "
            f"an access chain into the module's bindless CBV heap")
    return h


def build(mod, field, gain, decoy=None, site='bounce', commit='first'):
    consts, edits = [], []
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)

    # --- detectors FIRST, before anything rewrites mod.lines (GOTCHAS 12) ---
    writes = find_image_writes(mod)
    trace_line = None
    for i in range(fs, fe):
        if TRACE_RE.match(mod.lines[i]):
            trace_line = i
            break
    if trace_line is None:
        die(f"{mod.name}: no OpTraceRayKHR in the raygen entry function")
    ind, ops = TRACE_RE.match(mod.lines[trace_line]).groups()
    ops = ops.split()
    if len(ops) != 11:
        die(f"{mod.name}: trace at line {trace_line+1} has {len(ops)} operands, "
            f"expected 11 (accel flags cullMask sbtOff sbtStride missIdx "
            f"origin tmin dir tmax payload)")
    accel, cullmask, origin, direction, payload = \
        ops[0], ops[2], ops[6], ops[8], ops[10]
    # the AS must be the module's own, and it must be defined before the site
    aline, adef = mod.find_def(accel)
    if aline is None or aline > trace_line:
        die(f"{mod.name}: acceleration structure {accel} has no definition "
            f"above the trace")
    # SkipAABBsKHR needs this, and it is not ours to add silently
    if not any(re.match(r'\s*OpCapability RayTraversalPrimitiveCullingKHR\s*$', l)
               for l in mod.lines):
        die(f"{mod.name}: no RayTraversalPrimitiveCullingKHR capability -- "
            f"ray flag SkipAABBsKHR (0x200) would be illegal")
    payload_struct = _assert_payload_float3(mod, payload)
    prim = _find_primary_ray(mod, fs, fe) if site == 'primary' else None
    if prim is not None and prim['line'] > trace_line:
        die(f"{mod.name}: the primary reconstruction (line {prim['line']}) is "
            f"below the splice site (line {trace_line+1}) -- its ids would not "
            f"dominate")
    # 94 sec 3.3's world offset, for the fields that add it. Located here with
    # the other detectors, BEFORE anything rewrites mod.lines (GOTCHAS 12).
    woff = None
    if MATRIX_FIELDS.get(field, {}).get('offset'):
        woff = _find_world_offset(mod, fs, fe)
        # PLACEMENT PROOF, part 1 (part 2 is spirv-val's own dominance check,
        # run on every shipped module by process() below): the splice emits its
        # OWN OpAccessChain on the module's OWN bindless-CBV pointer, so that
        # pointer must be defined above the splice site. No existing chain on
        # member 56 is reused: one dominates the splice in only 4 of the 10
        # permutations, and a rung whose splice differs between modules is not
        # one variable.
        if woff['cbv_line'] > trace_line + 1:
            die(f"{mod.name}: the bindless CBV {woff['cbv']} is defined at line "
                f"{woff['cbv_line']}, below the splice site (line "
                f"{trace_line+1}) -- it would not dominate the offset load")

    # ------------------------------------------------------------ types etc.
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
                         lambda n: f"    {n} = OpTypeBool")
    ptrF_float = _ensure_line(
        mod, consts, r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %float\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %float")
    rqt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeRayQueryKHR\s*$',
                       lambda n: f"    {n} = OpTypeRayQueryKHR")
    ptr_rq = _ensure_line(
        mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function ' + re.escape(rqt) + r'\s*$',
        lambda n: f"    {n} = OpTypePointer Function {rqt}")
    ptr_priv_u = _ensure_line(
        mod, consts, r'\s*(%\w+)\s*=\s*OpTypePointer Private %uint\s*$',
        lambda n: f"    {n} = OpTypePointer Private %uint")
    # A non-scalar getter needs its result type. _ensure_line REUSES the
    # module's own declaration when it has one and only declares a new type
    # when it does not; apply_edits puts `consts` immediately before the first
    # OpFunction, i.e. inside the module's own types/constants/globals section
    # and BELOW the %v3float this type is built from, which is where SPIR-V
    # requires it. (Census over the base rung: 0 of 12 reference raygens
    # declare any OpTypeMatrix at all, so today all 10 get a fresh one.)
    mfield = MATRIX_FIELDS.get(field)
    mat_t = None
    if mfield:
        if not any(re.match(r'\s*%v3float\s*=\s*OpTypeVector %float 3\s*$', l)
                   for l in mod.lines):
            die(f"{mod.name}: no %v3float to build {mfield['type_decl']} on")
        mat_t = _ensure_line(
            mod, consts,
            r'\s*(%\w+)\s*=\s*' + re.escape(mfield['type_decl']) + r'\s*$',
            lambda n: f"    {n} = {mfield['type_decl']}")

    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u2 = _uc(mod, consts, 2)
    u3 = _uc(mod, consts, 3)
    u7 = _uc(mod, consts, 7)
    u15 = _uc(mod, consts, 15)
    # Deliberately WRONG builds, used only by build_rayq.sh to prove
    # verify_rayq.py is not vacuous. They are never installed.
    if decoy == 'ray' and site == 'bounce':
        origin = direction          # the ray is no longer the module's ray
    # (for site=primary the same decoy swaps the DIRECTION to the bounce ray's
    #  -- a real id, but the wrong one; see the query body below)
    want_flags, flags_names = COMMIT_FLAGS[commit]
    flags_value = 0 if decoy == 'flags' else want_flags
    u_flags = _uc(mod, consts, flags_value)
    u_golden = _uc(mod, consts, GOLDEN)
    u_bucket = [_uc(mod, consts, k) for k in range(8)]

    v3zero = None
    if site == 'primary':
        f0 = _fc(mod, consts, 0.0)
        v3zero = _ensure_line(
            mod, consts,
            r'\s*(%\w+)\s*=\s*OpConstantComposite %v3float '
            + re.escape(f0) + r' ' + re.escape(f0) + r' ' + re.escape(f0) + r'\s*$',
            lambda n: f"    {n} = OpConstantComposite %v3float {f0} {f0} {f0}")

    f_lo = _fc(mod, consts, 0.999)
    f_hi = _fc(mod, consts, 1.001)
    f_eps = _fc(mod, consts, 1.0e-4)
    one = _fc(mod, consts, 1.0)

    def mix(rgb):
        # gain lerps from vanilla toward the palette entry; gain 0 is exactly
        # 1.0 in every channel, so the control keeps the instructions and
        # loses the colour.
        return tuple(1.0 + gain * (x - 1.0) for x in rgb)

    hue_ids = [[_fc(mod, consts, v) for v in mix(rgb)] for _n, rgb in PALETTE]
    nohit_name, nohit_rgb = NOHIT[site]
    nohit_ids = [_fc(mod, consts, v) for v in mix(nohit_rgb)]

    st = mod.new_id()
    consts.append(f"    {st} = OpVariable {ptr_priv_u} Private")
    idv = mod.new_id()
    consts.append(f"    {idv} = OpVariable {ptr_priv_u} Private")
    # SPIR-V >= 1.4: EVERY global the entry point references must be on the
    # interface list, whatever its storage class.
    mod.lines[eline] = mod.lines[eline].rstrip() + f' {st} {idv}'

    # --------- 1. the ray query variable + the armed state, in the entry block
    # All Function-storage OpVariables must be the leading instructions of the
    # first block, so the query object goes at the end of that run and the two
    # Private stores immediately after it -- one edit, so apply_edits cannot
    # reorder them against each other.
    lab = next(i for i in range(fs, fe) if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    at = lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    rq = mod.new_id()
    edits.append((at, [
        f"{ind}{rq} = OpVariable {ptr_rq} Function",
        f"{ind}OpStore {st} {u0}",
        f"{ind}OpStore {idv} {u0}"]))

    # --------------- 2. the ray query itself, immediately after the trace ----
    getter, field_doc = FIELDS[field]
    tlo, thi0, thi = (mod.new_id() for _ in range(3))
    proceed, ityp, comm, raw = (mod.new_id() for _ in range(4))
    old, first, nstate, wstate = (mod.new_id() for _ in range(4))
    oldid, v0, wid = (mod.new_id() for _ in range(3))
    q = []
    if site == 'bounce':
        # t comes from the payload the module's own trace just filled.
        tac, t = mod.new_id(), mod.new_id()
        q += [
            f"{ind}{tac} = OpInBoundsAccessChain {ptrF_float} {payload} {u3}",
            f"{ind}{t} = OpLoad %float {tac}",
        ]
        q_origin, q_dir = origin, direction
    else:
        # The primary ray: camera at the origin of P's space (94 sec 3.3), so
        # the origin is the zero triple and the direction is the module's own
        # normalized view ray. t = |P| = dot(P,P) * rsqrt(dot(P,P)) -- one
        # instruction, no new constant, entirely the module's own ids.
        t = mod.new_id()
        q += [f"{ind}{t} = OpFMul %float {prim['dot']} {prim['rsqrt']}"]
        pdir = mod.new_id()
        q += [f"{ind}{pdir} = OpCompositeConstruct %v3float "
              f"{prim['V'][0]} {prim['V'][1]} {prim['V'][2]}"]
        q_origin = v3zero
        q_dir = direction if decoy == 'ray' else pdir
    q += [
        f"{ind}{tlo} = OpFMul %float {t} {f_lo}",
        f"{ind}{thi0} = OpFMul %float {t} {f_hi}",
        f"{ind}{thi} = OpFAdd %float {thi0} {f_eps}",
        f"{ind}OpRayQueryInitializeKHR {rq} {accel} {u_flags} {cullmask} "
        f"{q_origin} {tlo} {q_dir} {thi}",
        f"{ind}{proceed} = OpRayQueryProceedKHR {boolt} {rq}",
        f"{ind}{ityp} = OpRayQueryGetIntersectionTypeKHR %uint {rq} {u1}",
        f"{ind}{comm} = OpINotEqual {boolt} {ityp} {u0}",
    ]
    if mfield is None:
        q += [f"{ind}{raw} = {getter} %uint {rq} {u1}"]
        xf_ids = None
    else:
        # ObjectToWorld -> column 3 (the translation) -> uint, XOR-folded.
        #
        #   xf   RAW bits, no quantisation and no offset: a static instance's
        #        transform is bit-identical every frame and a moving one's is
        #        not, and that asymmetry was the signal the rung was built for.
        #   xfq  + 1 cm quantisation.  The CONTROL for xfw.
        #   xfw  + 94 sec 3.3's world offset, THEN the same quantisation.
        mat, col = mod.new_id(), mod.new_id()
        cxyz = [mod.new_id() for _ in range(3)]
        q += [f"{ind}{mat} = {getter} {mat_t} {rq} {u1}",
              f"{ind}{col} = OpCompositeExtract %v3float {mat} {mfield['column']}"]
        q += [f"{ind}{cxyz[k]} = OpCompositeExtract %float {col} {k}"
              for k in range(3)]
        xf_ids = {'matrix': mat, 'matrix_type': mat_t,
                  'column': col, 'column_index': mfield['column'],
                  'components': cxyz}
        src = cxyz
        if woff is not None:
            # world = translation + cbv[..][member].xyz.  Offset FIRST, which
            # is the operand order of 94 sec 3.3's own quoted
            # `%1419 = OpFAdd %float %1416 %727`; the base uses both orders at
            # different sites and OpFAdd is commutative, so this is a
            # convention choice recorded, not a fact discovered.
            u_mem = _uc(mod, consts, woff['member'])
            oac, olo = mod.new_id(), mod.new_id()
            oxyz = [mod.new_id() for _ in range(3)]
            sxyz = [mod.new_id() for _ in range(3)]
            q += [f"{ind}{oac} = OpAccessChain {woff['ptr_type']} {woff['cbv']} "
                  f"{u0} {u_mem}",
                  f"{ind}{olo} = OpLoad %v4float {oac}"]
            q += [f"{ind}{oxyz[k]} = OpCompositeExtract %float {olo} {k}"
                  for k in range(3)]
            q += [f"{ind}{sxyz[k]} = OpFAdd %float {oxyz[k]} {cxyz[k]}"
                  for k in range(3)]
            xf_ids.update({'offset_chain': oac, 'offset_load': olo,
                           'offset_cbv': woff['cbv'],
                           'offset_member': woff['member'],
                           'offset_components': oxyz, 'world': sxyz,
                           'offset_position': woff['position'],
                           'offset_order': 'offset_first'})
            src = sxyz
        bsrc = src
        if mfield.get('quantise'):
            # x * 100 -> OpConvertFToS (a signed 32-bit int: the translation is
            # signed and the sign must survive) -> OpBitcast to the uint the
            # latch takes. 1 cm buckets; +-21 km of range in int32, which is
            # more than the world is wide.
            int_t = _ensure_line(mod, consts,
                                 r'\s*(%\w+)\s*=\s*OpTypeInt 32 1\s*$',
                                 lambda n: f"    {n} = OpTypeInt 32 1")
            fq = _fc(mod, consts, mfield['quantise'])
            mxyz = [mod.new_id() for _ in range(3)]
            ixyz = [mod.new_id() for _ in range(3)]
            q += [f"{ind}{mxyz[k]} = OpFMul %float {src[k]} {fq}"
                  for k in range(3)]
            q += [f"{ind}{ixyz[k]} = OpConvertFToS {int_t} {mxyz[k]}"
                  for k in range(3)]
            xf_ids.update({'quantise': mfield['quantise'], 'scale_const': fq,
                           'int_type': int_t, 'scaled': mxyz, 'quantised': ixyz})
            bsrc = ixyz
        bxyz = [mod.new_id() for _ in range(3)]
        x01 = mod.new_id()
        q += [f"{ind}{bxyz[k]} = OpBitcast %uint {bsrc[k]}" for k in range(3)]
        x2 = raw if decoy != 'latch' else mod.new_id()
        q += [f"{ind}{x01} = OpBitwiseXor %uint {bxyz[0]} {bxyz[1]}",
              f"{ind}{x2} = OpBitwiseXor %uint {x01} {bxyz[2]}"]
        if decoy == 'latch':
            # Deliberately WRONG: fold the bracket's own t -- a value the
            # DEPTH BUFFER produces, so a different one every frame -- into
            # the value the latch stores, upstream of the paint. The 12.6(c)
            # backwards walk starts at the select chain and would never see
            # it; the 98 sec 14 walk starts at the OpStore into the latch and
            # must. Exists only to prove that walk is not vacuous. Never
            # installed.
            tb = mod.new_id()
            q += [f"{ind}{tb} = OpBitcast %uint {t}",
                  f"{ind}{raw} = OpBitwiseXor %uint {x2} {tb}"]
        xf_ids.update({'bitcast': bxyz, 'folded': raw})
    q += [
        # first-write-wins latch: a pure select pair, no control flow
        f"{ind}{old} = OpLoad %uint {st}",
        f"{ind}{first} = OpIEqual {boolt} {old} {u0}",
        f"{ind}{nstate} = OpSelect %uint {comm} {u2} {u1}",
        f"{ind}{wstate} = OpSelect %uint {first} {nstate} {old}",
        f"{ind}OpStore {st} {wstate}",
        f"{ind}{oldid} = OpLoad %uint {idv}",
        f"{ind}{v0} = OpSelect %uint {comm} {raw} {u0}",
        f"{ind}{wid} = OpSelect %uint {first} {v0} {oldid}",
        f"{ind}OpStore {idv} {wid}",
    ]
    edits.append((trace_line, q))

    # ----------------------------- 3. paint, at every radiance write --------
    painted, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1, 'why': 'texel not a v4float construct'})
            continue
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({'line': w['line'] + 1, 'why': 'constant-zero'})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({'line': w['line'] + 1, 'why': 'scalar-broadcast'})
            continue
        wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        ins = []

        def N(op, ty, *a):
            i = mod.new_id()
            ins.append(f"{wind}{i} = {op} {ty} " + ' '.join(a))
            return i

        lst = N('OpLoad', '%uint', st)
        lid = N('OpLoad', '%uint', idv)
        if decoy == 'hash':
            # Deliberately WRONG: fold this pixel's own radiance -- a value that
            # changes every frame -- into the hash input, so the paint is no
            # longer a function of the committed field alone. Exists only so
            # audit_rayq_hash.py can be shown to reject it. Never installed.
            lid = N('OpBitwiseXor', '%uint', lid, N('OpBitcast', '%uint', c[0]))
        h0 = N('OpIMul', '%uint', lid, u_golden)
        h1 = N('OpShiftRightLogical', '%uint', h0, u15)
        h2 = N('OpBitwiseXor', '%uint', h0, h1)
        h3 = N('OpBitwiseAnd', '%uint', h2, u7)
        is_hit = N('OpIEqual', boolt, lst, u2)
        is_none = N('OpIEqual', boolt, lst, u1)

        gates = []
        for k in range(8):
            eq = N('OpIEqual', boolt, h3, u_bucket[k])
            g = N('OpLogicalAnd', boolt, is_hit, eq)
            gates.append((g, hue_ids[k]))
        gates.append((is_none, nohit_ids))

        newc = []
        for ch in range(3):
            cur = one
            for g, rgb in gates:
                s = mod.new_id()
                ins.append(f"{wind}{s} = OpSelect %float {g} {rgb[ch]} {cur}")
                cur = s
            n_ = mod.new_id()
            ins.append(f"{wind}{n_} = OpFMul %float {c[ch]} {cur}")
            newc.append(n_)
        nt = mod.new_id()
        ins.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        painted.append(w['line'] + 1)

    if not painted:
        die(f"{mod.name}: no radiance write to read the ray query back at")

    rep = {
        'site': site,
        'field': field, 'getter': getter, 'field_doc': field_doc,
        'gain': gain, 'ray_flags': want_flags, 'commit': commit,
        'ray_flags_names': flags_names,
        'hash_multiplier': GOLDEN, 'decoy': decoy,
        'clone_of_line': trace_line + 1,
        'trace_operands': ' '.join(ops),
        'accel': accel, 'cullmask': cullmask, 'origin': origin,
        'direction': direction, 'payload': payload,
        'payload_struct': payload_struct,
        'rq_var': rq, 'state_var': st, 'id_var': idv, 'xf': xf_ids,
        'painted': painted, 'skipped': skipped,
        'palette': [n for n, _ in PALETTE] + [nohit_name + '(no-hit)'],
        'primary': prim,
    }
    return consts, edits, rep


def _add_header(mod):
    """OpCapability / OpExtension live above OpMemoryModel, which apply_edits
    cannot reach (it inserts before the first OpFunction). Done afterwards, on
    freshly located lines."""
    caps = [i for i, l in enumerate(mod.lines)
            if re.match(r'\s*OpCapability\b', l)]
    if not any('RayQueryKHR' in mod.lines[i] for i in caps):
        mod.lines.insert(caps[-1] + 1, '               OpCapability RayQueryKHR')
    exts = [i for i, l in enumerate(mod.lines) if re.match(r'\s*OpExtension\b', l)]
    if not exts:
        die(f"{mod.name}: no OpExtension section to append SPV_KHR_ray_query to")
    if not any('SPV_KHR_ray_query' in mod.lines[i] for i in exts):
        mod.lines.insert(exts[-1] + 1,
                         '               OpExtension "SPV_KHR_ray_query"')


def process(path, outdir, field, gain, do_rt=True, decoy=None,
            site='bounce', commit='first'):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    if do_rt:
        roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident, target_env=target_env)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['rayq'] = build(mod, field, gain, decoy, site, commit)
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
    # Reference raygens are SPIR-V 1.4 -> Vulkan 1.4 is the env that admits
    # both the module version and SPV_KHR_ray_query.
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--field', default='id', choices=sorted(FIELDS))
    ap.add_argument('--site', default='bounce', choices=SITES,
                    help="bounce = clone the module's own bounce trace "
                         "(stochastic, first-bounce identity); primary = the "
                         "module's own reconstructed camera ray (one identity "
                         "per visible pixel)")
    ap.add_argument('--gain', type=float, default=1.0,
                    help='0 = the CONTROL: every instruction and the ray query '
                         'stay, every multiplier collapses to 1.0')
    ap.add_argument('--commit', default='first', choices=sorted(COMMIT_FLAGS),
                    help="first = TerminateOnFirstHit, flags 517: commits ANY "
                         "hit inside the bracket, so two coplanar surfaces can "
                         "swap between frames; closest = flags 513, commits the "
                         "NEAREST hit. Both need exactly one Proceed.")
    ap.add_argument('--decoy', choices=('ray', 'flags', 'hash', 'latch'),
                    default=None,
                    help='emit a deliberately WRONG build, to prove '
                         'verify_rayq.py rejects it. Never installed.')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    reps = [process(p, a.outdir, a.field, a.gain,
                    do_rt=not a.no_roundtrip_check, decoy=a.decoy, site=a.site,
                    commit=a.commit)
            for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
