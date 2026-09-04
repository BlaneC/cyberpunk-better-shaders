#!/usr/bin/env python3
"""bda-probe / bda-rq-probe: Stage 2b and 2c in the COMPUTE resolvers.

WHY THIS EXISTS
---------------
`98` sec 10.2 measured that a compute module cannot reach the TLAS: in a
compute pipeline vkd3d-proton binds `AtomicCounters` at set 1 binding 0, which
is where a raygen has `RTASHeap`.  0 of 675 compute modules in the dump can
name an acceleration structure.  So the 64-bit device address has to arrive
through the layer, and `98` sec 10.3 listed four holes in that plan.  This file
closes the SHADER half of holes 1 and 2.

THE MARKER (hole 1 -- a forgery-proof discriminator)
----------------------------------------------------
`OpCapability PhysicalStorageBufferAddresses` discriminates NOTHING: 3282 of
3323 dumped modules declare it, and all 77 compute resolvers of the standing
base use the `PhysicalStorageBuffer64` addressing model already.  So the
module carries a RESERVED OpString instead:

    CALLISTO_BDA_SLOT_V1 lo=%0000000123 hi=%0000000124 sent=<64-bit> magic=<32>

Census over `~/callisto_dump`: 0 of 3323 modules contain the string
`CALLISTO` in any OpString, and 0 contain either sentinel half as an
`OpConstant %uint`.  The layer refuses to serve a marker-carrying module to a
device where it could not allocate the slot, and the refusal falls through to
the NEXT overlay (`98` sec 7.2).

THE FIXUP ANCHOR (hole 2 -- never a value scan)
-----------------------------------------------
The marker NAMES the two `OpConstant %uint` that hold the sentinel's halves,
by their SSA id **in the assembled binary**.  `spirv-as` does not preserve the
numeric ids written in the assembly, so the ids are resolved AFTER assembly by
reading them back out of the .spv and rewriting the (fixed-width, zero-padded)
id fields of the marker in place.  The build then records them in
`bda_manifest.json` and `dev/verify_bda.py` re-derives them independently.

At `vkCreateShaderModule` the layer requires all four conjuncts -- one marker,
well-formed ids, ids defined by 32-bit unsigned `OpConstant`s, those constants
currently holding the sentinel -- before it rewrites two words.  A module that
merely CONTAINS the sentinel value is not touched, because it names nothing.

THE POINTER
-----------
The idiom is the game's own, lifted verbatim from `0b190a1f53c31393.chs_main_9`
(36 dumped modules use it), which is why it needs no `Int64` capability and no
new device feature:

    %v  = OpCompositeConstruct %v2uint %lo %hi        <- the two sentinel halves
    %p  = OpBitcast %_ptr_PhysicalStorageBuffer_CallistoBdaSlot %v
    %a  = OpInBoundsAccessChain %_ptr_PhysicalStorageBuffer_uint %p %uint_K
    %w  = OpLoad %uint %a Aligned 4

`CallistoBdaSlot` is an 8 x uint Block, member K at Offset 4K, mirroring the
layer's own layout table (swap_layer.c, "BDA SLOT"):

    0 magic   1 generation   2 tlas_lo   3 tlas_hi
    4 prims   5 builds       6 frame     7 flags

THE RUNGS
---------
  --mode ctl    emits NOTHING and rewrites nothing: byte-identical to the base.
  --mode probe  Stage 2b.  Reads word 0 and paints class-1 (skin) pixels GREEN
                when it equals the magic and RED when it does not.  Every other
                material class is multiplied by 1.0, i.e. untouched.
  --mode wprobe Stage 3a (handoff/116).  The WIDENED slot: reads words 8/9/10
                (the scratch address and its size), 6 (the layer's frame
                counter) and 0, and then per skin pixel READS the word this
                pixel owns, compares it against the value the PREVIOUS frame
                would have left there, and writes this frame's.  Skin paints
                GREEN when the comparison holds -- i.e. a word this shader
                wrote survived a frame in a buffer no descriptor names -- BLUE
                when it does not, AMBER when the layer allocated no scratch,
                and RED when the magic is wrong.  No ray query.
  --mode wprobe2 Stage 3a, second cut (handoff/116 sec 8).  TWO words per
                pixel: an identity word that carries NO frame stamp, and the
                frame the write happened on.  The identity answers "did this
                pixel's word persist and is the index right" without depending
                on a counter the host writes at RECORD time; the frame word
                measures HOW OLD the survivor is.  Skin: BLUE = the word is not
                this pixel's, GREEN = it is and is exactly one frame old, CYAN
                = zero frames old (the resolver ran twice for one present),
                MAGENTA = two or more frames old (the counter jumped or froze).
                AMBER and RED as in --mode wprobe.
  --mode rq     Stage 2c.  ALSO reads words 2/3, converts them to an
                acceleration structure and runs ONE inline ray query per
                painted write from the resolver's own shading point, straight
                up (+Z), flags 517, tmin 5 cm, tmax 3 m.  Skin paints BLUE on a
                committed hit and AMBER on a miss -- and still RED if the magic
                is wrong, so "2b broke" is never confusable with "the ray
                missed".

THE TWO SPACES (`99` sec 10.6, and this is the whole trap)
-----------------------------------------------------------
The resolvers' P is a WORLD position (`99` sec 10.4, measured on screen); the
TLAS is CAMERA-RELATIVE (`98` sec 15.4, measured on screen).  A world P handed
to the TLAS must therefore have the camera position SUBTRACTED, and the
resolver's own camera position is member 0 of the same CBV -- the mirror of
the raygen's member 56.  That is exactly
`wpos_core.emit_world_pos(..., relative_to_camera=True)`, which `99` built as
the `hunt-wpos-cam` control.  Nothing is imported from the raygen side.

Usage:
    python3 dev/patch_bda.py <mod.spvasm> --outdir DIR --mode probe|rq|ctl
        [--tmax 3.0] [--tmin 0.05] [--flags 517] [--mask 255]
        [--decoy nomarker|badid|scan|world|noflags|noguard|sameframe|stamped
                 |paints|rgstore|xoffset]
"""
import argparse, hashlib, json, os, re, struct, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_shadow_brdf import CFG, find_class_fetch, class_fetch_inputs, \
                              emit_class_value
from patch_compute_brdf import find_image_writes, detect_target_env
import patch_compute_skin as CS
from patch_compute_skin import acquire_class_shift
import wpos_core as W

# ---------------------------------------------------------------- contract
# These four numbers are the ABI between this file, dev/verify_bda.py and
# swap_layer.c's "BDA SLOT" section. Changing one changes all three.
MARKER = 'CALLISTO_BDA_SLOT_V1'
SENT_LO = 0x0BDA0001          # 198836225
SENT_HI = 0xCA115700          # 3390134016
MAGIC = 0xCA115701            # 3390134017
ID_W = 10                     # zero-padded id field width in the marker
SLOT_MEMBERS = 8              # 8 x uint, Offset 4k, Block, NonWritable

W_MAGIC, W_GEN, W_LO, W_HI, W_FRAME = 0, 1, 2, 3, 6

# Stage 3a (handoff/116): the slot's words 8..11 point at a much larger buffer
# the SHADER writes. A module that only needs the TLAS keeps declaring the
# 8-member mailbox -- every rung built before this one still verifies -- and a
# module that wants the scratch declares the 12-member form instead.
SLOT_MEMBERS_V2 = 12
W_SCR_LO, W_SCR_HI, W_SCR_WORDS, W_SCR_FLAGS = 8, 9, 10, 11
SCRATCH_HDR = 16              # words the layer reserves for shader counters
SCRATCH_SIG = 0xC0FFEE01      # "a shader was here", the value the probe leaves
SCR_F_ARMED, SCR_F_READBACK = 1, 2

# Declines, BY NAME -- the same two `99` sec 5 declines, for the same reasons.
#   ab0bc2fee876d489 -- its one OpImageWrite stores a v4uint reservoir record,
#                       not radiance (`46` sec 12). Declined in EVERY mode.
#   99bb7c2698997b2a -- the big GI resolver: no view vector, so no position
#                       chain (`97` sec 1.5). It HAS a radiance write, so the
#                       Stage 2b probe still paints it; only --mode rq, which
#                       needs P, declines it.
DECLINE_ALL = {'ab0bc2fee876d489'}
DECLINE_RQ = {'99bb7c2698997b2a'}

# Paint multipliers on the radiance texel, in `94`'s hunt-paint magnitudes so
# the frame stays recognisable and the class-1 channel is the same one that
# was already proven to reach the screen (`99` sec 10.8e).
COL = {
    'green': (0.15, 3.00, 0.15),   # 2b: the magic word was found
    'red':   (3.00, 0.15, 0.15),   # 2b: it was NOT -- the fixup did not happen
    'blue':  (0.15, 0.15, 3.00),   # 2c: the query committed a hit
    'amber': (3.00, 1.20, 0.15),   # 2c: the query missed
    'cyan':  (0.15, 3.00, 3.00),   # 3b: written again in the SAME frame
    'magenta': (3.00, 0.15, 3.00), # 3b: older than one frame
}
# --mode wprobe reuses the same four, one meaning each (see the docstring):
#   GREEN  this pixel's word survived from the previous frame
#   BLUE   the scratch is there, the word did not survive
#   AMBER  the slot is there, the scratch is not (CALLISTO_BDA_SCRATCH_MB=0)
#   RED    the magic is wrong, i.e. no fixup happened

# The scratch's per-pixel map, and the ONE place these numbers are written.
# The index is LINEAR in the pixel and the value is HASHED, never the other way
# round: a hashed index collides (two pixels, one word, a false BLUE), while a
# hashed value only has to be unlikely to equal a neighbour's.
# NB the pitch and the scratch SIZE are one decision: `pix & mask` is only
# injective while pitch * height <= mask + 1. At 4096 and 2 words per pixel a
# 32 MiB scratch gives 512 unique rows, and rows 512.. alias onto rows 0.. --
# which is what painted the top and bottom thirds of a 1280x720 frame blue in
# handoff/116 sec 9. The layer's default is 128 MiB for that reason.
PIX_PITCH = 4096              # y * PITCH + x; the internal width is never more
PIX_HASH = 2654435761         # Knuth's 2^32/phi
WORDS_PER_PIXEL = {'wprobe': 1, 'wprobe2': 2, 'xprobe': 2}
# --mode xprobe is the first rung that patches BOTH stages, and the two halves
# do OPPOSITE things:
#   compute resolver  WRITES its pixel's identity + the frame, paints NOTHING
#   raygen            READS at ITS OWN write coordinate, paints, stores nothing
# so the picture is the game, tinted exactly where a raygen found the word a
# resolver left for that pixel. The whole question is whether those two
# coordinates are the same pixel; see handoff/116 sec 10.1.
XPROBE_REG = 5                # the push-constant word every raygen's radiance
XPROBE_OFFS = (0, 1)          # descriptor index comes from: registers[5] + 0/1.
                              # Measured across all 16: every raygen writes
                              # radiance to exactly those two and nothing else
                              # (1271d38 also has a registers[5]+8 guide buffer,
                              # which is NOT painted -- tinting a denoiser guide
                              # would make the read unreadable).
PARK_WORD_2 = 33              # the second parked word, for the age store
PARK_WORD = 32                # where an UNARMED pixel writes: slot word 32, in
                              # the layer's own 64-word buffer, which nothing
                              # reads (words 12..63 are reserved). It exists so
                              # the store needs no branch and can never be out
                              # of bounds.

DEFAULTS = dict(flags=517, mask=255, tmin=0.05, tmax=3.0)


def is_raygen(mod):
    return any(re.match(r'\s*OpEntryPoint RayGenerationKHR\b', ln)
               for ln in mod.lines)


def raygen_radiance_writes(mod, writes):
    """The subset of `writes` that go to registers[5] + 0/1.

    Re-derived per module rather than assumed: the image is an OpLoad of an
    OpAccessChain into the descriptor array, indexed by the push constant (plus
    a literal offset). Anything else -- notably the registers[5]+8 guide
    buffer -- is left alone."""
    out = []
    for w in writes:
        _, ld = mod.find_def(w['img'])
        m = re.match(r'OpLoad %\w+ (%\w+)\s*$', ld or '')
        if not m:
            continue
        _, ac = mod.find_def(m.group(1))
        m = re.match(r'OpAccessChain %\w+ %\w+ (%\w+)\s*$', ac or '')
        if not m:
            continue
        _, v = mod.find_def(m.group(1))
        off, base = 0, m.group(1)
        m2 = re.match(r'OpIAdd %uint (%\w+) %uint_(\d+)\s*$', v or '')
        if m2:
            base, off = m2.group(1), int(m2.group(2))
            _, v = mod.find_def(base)
        m3 = re.match(r'OpLoad %uint (%\w+)\s*$', v or '')
        if not m3:
            continue
        _, pc = mod.find_def(m3.group(1))
        m4 = re.match(r'OpAccessChain %_ptr_PushConstant_uint %registers '
                      r'%uint_(\d+)\s*$', pc or '')
        if not m4 or int(m4.group(1)) != XPROBE_REG or off not in XPROBE_OFFS:
            continue
        w = dict(w); w['img_off'] = off
        out.append(w)
    return out


# ------------------------------------------------------- section insertion
def _last_line(mod, pat):
    """Index of the LAST line matching `pat`, or None."""
    rx = re.compile(pat)
    out = None
    for i, ln in enumerate(mod.lines):
        if rx.match(ln):
            out = i
    return out


def insert_sections(mod, caps, exts, marker, decos):
    """Put new instructions in their LEGAL SPIR-V sections.

    apply_edits() drops everything just above the first OpFunction, which is
    right for types and constants and WRONG for capabilities, extensions,
    OpString and decorations: spirv-val enforces the logical layout, so a
    decoration emitted after the type section is a hard validation failure,
    not a stylistic one. Called LAST, after apply_edits, so the line indices
    everything else recorded are already spent.
    """
    def after(idx, new):
        if not new:
            return
        if idx is None:
            die(f"{mod.name}: no anchor for {new[0].strip().split()[0]}")
        mod.lines[idx + 1:idx + 1] = new

    # Decorations first: every insertion below sits ABOVE this line, so doing
    # the lowest one first keeps the other anchors valid.
    after(_last_line(mod, r'\s*(OpDecorate|OpMemberDecorate|OpGroupDecorate|'
                          r'OpDecorationGroup|OpGroupMemberDecorate)\b'), decos)
    after(_last_line(mod, r'\s*%\w+\s*=\s*OpString\b'),
          [f'         {marker}'] if marker else [])
    after(_last_line(mod, r'\s*OpExtension\b')
          or _last_line(mod, r'\s*OpCapability\b'), exts)
    after(_last_line(mod, r'\s*OpCapability\b'), caps)


def entry_hoist_line(mod):
    """The line after the entry function's leading run of Function OpVariables.

    Everything before the first control-flow instruction dominates the whole
    function (GOTCHAS), and SPIR-V additionally requires every Function-storage
    OpVariable to be among the FIRST instructions of the first block -- which
    is why the ray query's variable has to go exactly here and not at the
    splice site.
    """
    src = '\n'.join(mod.lines)
    m = re.search(r'OpEntryPoint (?:GLCompute|RayGenerationKHR) (%\w+) ', src)
    if not m:
        die(f"{mod.name}: no GLCompute or RayGenerationKHR OpEntryPoint")
    fn = m.group(1)
    fline = None
    for i, ln in enumerate(mod.lines):
        if re.match(r'\s*' + re.escape(fn) + r'\s*=\s*OpFunction\b', ln):
            fline = i
            break
    if fline is None:
        die(f"{mod.name}: entry function {fn} has no OpFunction")
    lab = None
    for i in range(fline, len(mod.lines)):
        if re.match(r'\s*%\w+\s*=\s*OpLabel\s*$', mod.lines[i]):
            lab = i
            break
    if lab is None:
        die(f"{mod.name}: entry function has no OpLabel")
    j = lab
    while (j + 1 < len(mod.lines)
           and re.match(r'\s*%\w+\s*=\s*OpVariable %\w+ Function\b',
                        mod.lines[j + 1])):
        j += 1
    return j


def exact_float(mod, lit, consts):
    """The id of `OpConstant %float <lit>` by LITERAL TEXT, not by value."""
    pat = re.compile(r'\s*(%\w+)\s*=\s*OpConstant %float ' + re.escape(lit) + r'\s*$')
    for ln in mod.lines:
        m = pat.match(ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(f"    {nid} = OpConstant %float {lit}")
    return nid


def need_type(mod, name):
    if not any(re.match(r'\s*' + re.escape(name) + r'\s*=\s*OpType', ln)
               for ln in mod.lines):
        die(f"{mod.name}: no {name} type")
    return name


# --------------------------------------------------------------- the build
def build(mod, cfg, writes, mode, knobs, decoy, rgen=False):
    consts, decos, caps, exts = [], [], [], []
    uc = {}

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
    I = mod.new_id
    for t in ('%uint', '%v2uint', '%bool', '%float', '%v4float'):
        need_type(mod, t)
    if mode == 'rq':
        need_type(mod, '%v3float')

    # ---- the slot type, decorated exactly as the game's own PSB structs ----
    slot = I()
    ptr_slot = I()
    ptr_uint = I()
    n_slot = SLOT_MEMBERS_V2 if mode in WORDS_PER_PIXEL else SLOT_MEMBERS
    for k in range(n_slot):
        decos.append(f"               OpMemberDecorate {slot} {k} Offset {4 * k}")
    decos.append(f"               OpDecorate {slot} Block")
    for k in range(n_slot):
        decos.append(f"               OpMemberDecorate {slot} {k} NonWritable")
    consts.append(f"    {slot} = OpTypeStruct " + ' '.join(['%uint'] * n_slot))
    consts.append(f"    {ptr_slot} = OpTypePointer PhysicalStorageBuffer {slot}")
    consts.append(f"    {ptr_uint} = OpTypePointer PhysicalStorageBuffer %uint")

    # ---- the sentinel pair. FRESH ids, never mod.uconst: the layer rewrites
    # these two literals and nothing else may share them. The values are
    # absent from all 3323 dumped modules (build gate 8).
    lo = I()
    hi = I()
    consts.append(f"    {lo} = OpConstant %uint {SENT_LO}")
    consts.append(f"    {hi} = OpConstant %uint {SENT_HI}")
    if decoy == 'scan':
        # A second, UNNAMED copy of the sentinel pair. The layer must rewrite
        # neither of these (it anchors on the marker's ids), and the verifier
        # must refuse the module for carrying them.
        d1, d2 = I(), I()
        consts.append(f"    {d1} = OpConstant %uint {SENT_LO}")
        consts.append(f"    {d2} = OpConstant %uint {SENT_HI}")
    magic = I()
    consts.append(f"    {magic} = OpConstant %uint {MAGIC}")
    one = C(1.0)

    marker = None
    if decoy != 'nomarker':
        # The ids are PLACEHOLDERS. spirv-as does not preserve the numeric ids
        # written in the assembly (measured: `%9001` came back as id 18), so
        # the real ones can only be learned from the assembled binary --
        # resolve_marker_ids() rewrites these fixed-width fields in place.
        badl = 4294967295 if decoy == 'badid' else 0
        marker = ('%{0} = OpString "{1} lo=%{2:0{4}d} hi=%{3:0{4}d} '
                  'sent={5:016x} magic={6:08x}"').format(
            I()[1:], MARKER, badl, badl, ID_W,
            (SENT_HI << 32) | SENT_LO, MAGIC)

    # ---- hoisted: the pointer, the magic word, and (rq) the query state ----
    hoist = []
    v2 = I()
    pp = I()
    ac0 = I()
    w0 = I()
    ok = I()
    hoist += [
        f"        {v2} = OpCompositeConstruct %v2uint {lo} {hi}",
        f"        {pp} = OpBitcast {ptr_slot} {v2}",
        f"        {ac0} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_MAGIC)}",
        f"        {w0} = OpLoad %uint {ac0} Aligned 4",
        f"        {ok} = OpIEqual %bool {w0} {magic}",
    ]
    scr = {}
    if mode in WORDS_PER_PIXEL:
        # The scratch type: a runtime array of uint, and -- the whole
        # difference from the slot -- NOT NonWritable anywhere.
        arr, blk, ptr_scr = I(), I(), I()
        decos.append(f"               OpDecorate {arr} ArrayStride 4")
        decos.append(f"               OpDecorate {blk} Block")
        decos.append(f"               OpMemberDecorate {blk} 0 Offset 0")
        consts.append(f"    {arr} = OpTypeRuntimeArray %uint")
        consts.append(f"    {blk} = OpTypeStruct {arr}")
        consts.append(f"    {ptr_scr} = OpTypePointer PhysicalStorageBuffer {blk}")
        acw, wW, acl, sl, ach, sh = I(), I(), I(), I(), I(), I()
        armed, half, maskv = I(), I(), I()
        bl, bh, bv2, sp = I(), I(), I(), I()
        acf, fr, prevf = I(), I(), I()
        hoist += [
            # words 8/9/10: the scratch address and its size.
            f"        {acw} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_SCR_WORDS)}",
            f"        {wW} = OpLoad %uint {acw} Aligned 4",
            f"        {acl} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_SCR_LO)}",
            f"        {sl} = OpLoad %uint {acl} Aligned 4",
            f"        {ach} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_SCR_HI)}",
            f"        {sh} = OpLoad %uint {ach} Aligned 4",
            f"        {armed} = OpINotEqual %bool {wW} {U(0)}",
            # Only the LOWER HALF of the payload is addressed. The layer's size
            # is a power of two, so `words/2 - 1` is a mask, and
            # SCRATCH_HDR + (pix & mask) is in bounds for every pixel and every
            # size the layer can hand us -- with no clamp and no branch.
            f"        {half} = OpShiftRightLogical %uint {wW} "
            f"{U(WORDS_PER_PIXEL[mode])}",
            f"        {maskv} = OpISub %uint {half} {U(1)}",
            # An UNARMED pixel is pointed at the SLOT instead, where its store
            # lands in reserved word 32. The sentinel pair is the slot's own
            # address once the layer has rewritten it, so this costs nothing.
            # --decoy noguard drops exactly these two selects, which is the
            # null dereference this shape exists to prevent.
            (f"        {bl} = OpSelect %uint {armed} {sl} {lo}"
             if decoy != 'noguard' else
             f"        {bl} = OpCopyObject %uint {sl}"),
            (f"        {bh} = OpSelect %uint {armed} {sh} {hi}"
             if decoy != 'noguard' else
             f"        {bh} = OpCopyObject %uint {sh}"),
            f"        {bv2} = OpCompositeConstruct %v2uint {bl} {bh}",
            f"        {sp} = OpBitcast {ptr_scr} {bv2}",
            # The layer's frame counter (word 6): what makes "survived a frame"
            # a claim about time rather than about this dispatch.
            f"        {acf} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_FRAME)}",
            f"        {fr} = OpLoad %uint {acf} Aligned 4",
            f"        {prevf} = OpISub %uint {fr} {U(1)}",
        ]
        scr = dict(ptr=sp, mask=maskv, armed=armed, fr=fr, prevf=prevf,
                   ptr_scr=ptr_scr, words=wW, wpp=WORDS_PER_PIXEL[mode])

    rq_var = accel = None
    if mode == 'rq':
        caps.append("               OpCapability RayQueryKHR")
        caps.append("               OpCapability RayTraversalPrimitiveCullingKHR")
        exts.append('               OpExtension "SPV_KHR_ray_query"')
        rq_ty, rq_ptr, as_ty = I(), I(), I()
        consts.append(f"    {rq_ty} = OpTypeRayQueryKHR")
        consts.append(f"    {rq_ptr} = OpTypePointer Function {rq_ty}")
        consts.append(f"    {as_ty} = OpTypeAccelerationStructureKHR")
        rq_var = I()
        acl, ach, ldl, ldh, av2 = I(), I(), I(), I(), I()
        accel = I()
        hoist = [f"        {rq_var} = OpVariable {rq_ptr} Function"] + hoist + [
            f"        {acl} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_LO)}",
            f"        {ldl} = OpLoad %uint {acl} Aligned 4",
            f"        {ach} = OpInBoundsAccessChain {ptr_uint} {pp} {U(W_HI)}",
            f"        {ldh} = OpLoad %uint {ach} Aligned 4",
            f"        {av2} = OpCompositeConstruct %v2uint {ldl} {ldh}",
            f"        {accel} = OpConvertUToAccelerationStructureKHR {as_ty} {av2}",
        ]

    # ---- the colour, folded once per module ----
    if mode in ('rq',) or mode in WORDS_PER_PIXEL:
        c_blue = [C(x) for x in COL['blue']]
        c_amber = [C(x) for x in COL['amber']]
    if mode in ('wprobe2', 'xprobe'):
        c_cyan = [C(x) for x in COL['cyan']]
        c_magenta = [C(x) for x in COL['magenta']]
    c_green = [C(x) for x in COL['green']]
    c_red = [C(x) for x in COL['red']]
    ok_col = []
    if mode == 'probe':
        # Folded ONCE per module, not once per site: the magic does not vary
        # across write sites. In --mode rq the colour also depends on the
        # query, so it is built per site and this hoist would be dead code.
        for ch in range(3):
            s = I()
            hoist.append(f"        {s} = OpSelect %float {ok} "
                         f"{c_green[ch]} {c_red[ch]}")
            ok_col.append(s)

    # ---- ray-query constants ----
    if mode == 'rq':
        f_tmin, f_tmax = C(knobs['tmin']), C(knobs['tmax'])
        # NOT mod.const(): it memoises on the float32 VALUE, and -0.0 == 0.0,
        # so asking it for 0.0 hands back the module's own `OpConstant %float
        # -0` and the shipped direction reads (-0, -0, 1). That traverses the
        # same on this hardware, but the reciprocal of -0 is exactly the
        # operand a BVH slab test is famous for getting wrong, and it is not
        # what this document says the direction is. Take the module's own
        # POSITIVE zero by literal, and only emit one if it has none.
        f0 = exact_float(mod, '0', consts)
        f1 = exact_float(mod, '1', consts)
        dirv = I()
        consts.append(f"    {dirv} = OpConstantComposite %v3float {f0} {f0} {f1}")
        u_flags = U(knobs['flags'] if decoy != 'noflags' else 4)
        u_mask = U(knobs['mask'])
        u_comm = U(1)

    # ---- class gate ----
    # A raygen has no class word and needs none: the READER paints wherever it
    # finds a word, and "wherever" is precisely the measurement.
    if rgen:
        shift, dom_id, edits = None, None, []
    else:
        shift, ins_line, pre_ins, pre_consts, dom_id = acquire_class_shift(mod)
        consts.extend(pre_consts)
        edits = []
        if pre_ins:
            edits.append((ins_line, pre_ins))
    edits.append((entry_hoist_line(mod), hoist))

    ctx = cam = leaves = None
    if mode == 'rq':
        ctx = W.find_pos_chain(mod)
        if ctx is None:
            die(f"{mod.name}: no P = M.(x,y,depth,1)/w reconstruction")
        cam = W.find_campos(mod, ctx)
        if cam is None:
            die(f"{mod.name}: no camera position (C - P) triple")
        leaves = W.pos_leaves(ctx)

    cf = None
    done, skipped, refetched = [], [], []
    for w in writes:
        if w['comps'] is None:
            skipped.append({'line': w['line'] + 1,
                            'why': 'texel not a v4float construct'})
            continue
        ins = []
        cls = shift
        if rgen:
            pass
        elif not cfg.dominates_line(dom_id, w['line']):
            if cf is None:
                cf = find_class_fetch(mod)
            if any(not cfg.dominates_line(x, w['line'])
                   for x in class_fetch_inputs(cf)):
                skipped.append({'line': w['line'] + 1,
                                'why': 'class refetch inputs do not dominate'})
                continue
            cls = emit_class_value(mod, cf, ins)
        col = ok_col
        if mode == 'rq':
            p_top = all(cfg.dominates_line(i, w['line']) for i in ctx['p'])
            if not p_top and any(not cfg.dominates_line(x, w['line'])
                                 for x in leaves):
                skipped.append({'line': w['line'] + 1,
                                'why': 'position refetch inputs do not dominate'})
                continue
            if not p_top and not cfg.dominates_line(ctx['cbv'], w['line']):
                skipped.append({'line': w['line'] + 1,
                                'why': 'cbv base does not dominate'})
                continue
            # `99` sec 10.6: P is WORLD, the TLAS is CAMERA-RELATIVE, so the
            # origin is P - C. --decoy world feeds raw world P instead, which
            # is the mistake that rule exists to prevent.
            pos = W.emit_world_pos(mod, cfg, ctx, w['line'], ins, uc=uc,
                                   relative_to_camera=(decoy != 'world'),
                                   cam=cam)
            if not p_top:
                refetched.append(w['line'] + 1)
            org = mod.new_id()
            ins.append(f"        {org} = OpCompositeConstruct %v3float "
                       f"{pos[0]} {pos[1]} {pos[2]}")
            ins.append(f"        OpRayQueryInitializeKHR {rq_var} {accel} "
                       f"{u_flags} {u_mask} {org} {f_tmin} {dirv} {f_tmax}")
            pr = mod.new_id()
            ins.append(f"        {pr} = OpRayQueryProceedKHR %bool {rq_var}")
            ty = mod.new_id()
            ins.append(f"        {ty} = OpRayQueryGetIntersectionTypeKHR %uint "
                       f"{rq_var} {u_comm}")
            hit = mod.new_id()
            ins.append(f"        {hit} = OpINotEqual %bool {ty} {U(0)}")
            col = []
            for ch in range(3):
                h = mod.new_id()
                ins.append(f"        {h} = OpSelect %float {hit} "
                           f"{c_blue[ch]} {c_amber[ch]}")
                g = mod.new_id()
                ins.append(f"        {g} = OpSelect %float {ok} {h} {c_red[ch]}")
                col.append(g)
        if mode in WORDS_PER_PIXEL:
            # The pixel this write is about, taken from the write's OWN
            # coordinate -- no builtin lookup, and nothing that has to
            # dominate: the coord construct is at the site.
            cm = re.match(r'\s*OpImageWrite %\w+ (%\w+) %\w+\s*$',
                          mod.lines[w['line']])
            coord = cm.group(1) if cm else None
            cc = None
            for ln in mod.lines:
                m2 = re.match(r'\s*' + re.escape(coord or '\0')
                              + r'\s*=\s*OpCompositeConstruct %v2uint '
                                r'(%\w+) (%\w+)\s*$', ln)
                if m2:
                    cc = m2.groups()
                    break
            if cc is None:
                skipped.append({'line': w['line'] + 1,
                                'why': 'the write coordinate is not a v2uint construct'})
                continue
            px, py = cc
            pix, yp, hv, sx = (mod.new_id() for _ in range(4))
            if decoy == 'xoffset' and mode == 'xprobe' and rgen:
                # The reader looks one pixel to the right. Everything still
                # runs; the screen would just be quietly wrong -- which is the
                # entire class of bug this rung exists to detect, so the
                # verifier has to refuse it.
                shifted = mod.new_id()
                ins.append(f"        {shifted} = OpIAdd %uint {px} {U(1)}")
                px = shifted
            sub, wide, idxp, idx, chain, got = (mod.new_id() for _ in range(6))
            # `live` decides whether this pixel gets a REAL slot index or the
            # parked one. Armed always; and for the xprobe WRITER also class-1,
            # because a store cannot sit under an OpSelect but its ADDRESS can,
            # and that is how the writer stays confined to skin with no branch.
            live = scr['armed']
            if mode == 'xprobe' and not rgen:
                gate_c = mod.new_id()
                live = mod.new_id()
                ins.append(f"        {gate_c} = OpIEqual %bool {cls} {U(1)}")
                ins.append(f"        {live} = OpLogicalAnd %bool "
                           f"{scr['armed']} {gate_c}")
            ins += [
                f"        {yp} = OpIMul %uint {py} {U(PIX_PITCH)}",
                f"        {pix} = OpIAdd %uint {yp} {px}",
                f"        {sub} = OpBitwiseAnd %uint {pix} {scr['mask']}",
                # Two words per pixel means the slot index advances by two, or
                # pixel N's second word IS pixel N+1's first.
                *([f"        {wide} = OpIMul %uint {sub} {U(scr['wpp'])}"]
                  if scr['wpp'] != 1 else []),
                f"        {idxp} = OpIAdd %uint "
                f"{sub if scr['wpp'] == 1 else wide} {U(SCRATCH_HDR)}",
                f"        {idx} = OpSelect %uint {live} {idxp} {U(PARK_WORD)}",
                f"        {hv} = OpIMul %uint {pix} {U(PIX_HASH)}",
                f"        {sx} = OpBitwiseXor %uint {hv} {U(SCRATCH_SIG)}",
                f"        {chain} = OpInBoundsAccessChain {ptr_uint} "
                f"{scr['ptr']} {U(0)} {idx}",
            ]
            if mode != 'xprobe' or rgen:
                # READ FIRST, then write: a store before the load would make
                # the comparison trivially true. The xprobe WRITER never
                # reads -- it is the other stage's business to read.
                ins.append(f"        {got} = OpLoad %uint {chain} Aligned 4")
            seen = mod.new_id()
            if mode == 'wprobe':
                wnow, wold = mod.new_id(), mod.new_id()
                ins += [
                    f"        {wnow} = OpBitwiseXor %uint {sx} {scr['fr']}",
                    # --decoy sameframe stamps the EXPECTED word with this
                    # frame, so a store made moments earlier reads back as a
                    # survival and the rung paints green having proved nothing.
                    (f"        {wold} = OpBitwiseXor %uint {sx} {scr['prevf']}"
                     if decoy != 'sameframe' else
                     f"        {wold} = OpBitwiseXor %uint {sx} {scr['fr']}"),
                    f"        {seen} = OpIEqual %bool {got} {wold}",
                    f"        OpStore {chain} {wnow} Aligned 4",
                ]
            elif mode == 'xprobe' and not rgen:
                # THE WRITER. Two stores, no load, no paint: it leaves this
                # pixel's identity and the frame it left them, and nothing
                # else about the frame changes. Everything visible in this
                # rung is the RAYGEN's doing.
                idx2, ch2 = mod.new_id(), mod.new_id()
                ins += [
                    f"        OpStore {chain} {sx} Aligned 4",
                    f"        {idx2} = OpIAdd %uint {idx} {U(1)}",
                    f"        {ch2} = OpInBoundsAccessChain {ptr_uint} "
                    f"{scr['ptr']} {U(0)} {idx2}",
                    f"        OpStore {ch2} {scr['fr']} Aligned 4",
                ]
                if decoy == 'paints':
                    # The WRITER tints too, so the screen no longer shows the
                    # raygen's verdict alone -- a silent way to read a green
                    # frame that the compute side painted.
                    nc = []
                    for ch in range(3):
                        n = mod.new_id()
                        ins.append(f"        {n} = OpFMul %float "
                                   f"{w['comps'][ch]} {c_green[ch]}")
                        nc.append(n)
                    nt = mod.new_id()
                    ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                               f"{nc[0]} {nc[1]} {nc[2]} {w['comps'][3]}")
                    mod.lines[w['line']] = re.sub(
                        r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                        r'\g<1>' + nt, mod.lines[w['line']])
                edits.append((w['line'] - 1, ins))
                done.append(w['line'] + 1)
                continue
            elif mode == 'xprobe':
                # THE READER, in a raygen. Reads the two words at ITS OWN write
                # coordinate and stores nothing at all -- so a wrong answer
                # here cannot be an artefact of the reader having scribbled.
                idx2, ch2, got2, age = (mod.new_id() for _ in range(4))
                is0, is1, present = (mod.new_id() for _ in range(3))
                ins += [
                    f"        {seen} = OpIEqual %bool {got} {sx}",
                    f"        {present} = OpINotEqual %bool {got} {U(0)}",
                    f"        {idx2} = OpIAdd %uint {idx} {U(1)}",
                    f"        {ch2} = OpInBoundsAccessChain {ptr_uint} "
                    f"{scr['ptr']} {U(0)} {idx2}",
                    f"        {got2} = OpLoad %uint {ch2} Aligned 4",
                    *([f"        OpStore {ch2} {scr['fr']} Aligned 4"]
                      if decoy == 'rgstore' else []),
                    f"        {age} = OpISub %uint {scr['fr']} {got2}",
                    f"        {is0} = OpIEqual %bool {age} {U(0)}",
                    f"        {is1} = OpIEqual %bool {age} {U(1)}",
                ]
                col = []
                for ch in range(3):
                    h0, h1, h2, h3, h4, h5 = (mod.new_id() for _ in range(6))
                    ins += [
                        f"        {h0} = OpSelect %float {is1} "
                        f"{c_green[ch]} {c_magenta[ch]}",
                        f"        {h1} = OpSelect %float {is0} "
                        f"{c_cyan[ch]} {h0}",
                        # A word IS there but it is not mine: the two stages
                        # disagree about which pixel this is. That is the one
                        # answer this rung was built to be able to give.
                        f"        {h2} = OpSelect %float {present} "
                        f"{c_red[ch]} {one}",
                        f"        {h3} = OpSelect %float {seen} {h1} {h2}",
                        f"        {h4} = OpSelect %float {scr['armed']} "
                        f"{h3} {c_amber[ch]}",
                        f"        {h5} = OpSelect %float {ok} {h4} "
                        f"{c_blue[ch]}",
                    ]
                    col.append(h5)
                newc = []
                for ch in range(3):
                    n = mod.new_id()
                    ins.append(f"        {n} = OpFMul %float "
                               f"{w['comps'][ch]} {col[ch]}")
                    newc.append(n)
                nt = mod.new_id()
                ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                           f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
                edits.append((w['line'] - 1, ins))
                mod.lines[w['line']] = re.sub(
                    r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                    r'\g<1>' + nt, mod.lines[w['line']])
                done.append(w['line'] + 1)
                continue
            else:
                # wprobe2: the identity word carries NO frame, so `seen` is a
                # statement about this buffer and this index alone. The age
                # comes out of the SECOND word, and only decides the hue.
                idx2, ch2, got2, age, sxs = (mod.new_id() for _ in range(5))
                is0, is1 = mod.new_id(), mod.new_id()
                ins += [
                    # --decoy stamped folds the frame back INTO the identity
                    # word, which is exactly the coupling this rung exists to
                    # remove: it would flicker for the same reason wprobe did.
                    *([f"        {sxs} = OpBitwiseXor %uint {sx} {scr['fr']}"]
                      if decoy == 'stamped' else []),
                    f"        {seen} = OpIEqual %bool {got} "
                    f"{sxs if decoy == 'stamped' else sx}",
                    f"        OpStore {chain} "
                    f"{sxs if decoy == 'stamped' else sx} Aligned 4",
                    f"        {idx2} = OpIAdd %uint {idx} {U(1)}",
                    f"        {ch2} = OpInBoundsAccessChain {ptr_uint} "
                    f"{scr['ptr']} {U(0)} {idx2}",
                    f"        {got2} = OpLoad %uint {ch2} Aligned 4",
                    f"        OpStore {ch2} {scr['fr']} Aligned 4",
                    f"        {age} = OpISub %uint {scr['fr']} {got2}",
                    f"        {is0} = OpIEqual %bool {age} {U(0)}",
                    f"        {is1} = OpIEqual %bool {age} {U(1)}",
                ]
            col = []
            for ch in range(3):
                a1, a2, a3 = mod.new_id(), mod.new_id(), mod.new_id()
                if mode == 'wprobe':
                    ins.append(f"        {a1} = OpSelect %float {seen} "
                               f"{c_green[ch]} {c_blue[ch]}")
                else:
                    h0, h1 = mod.new_id(), mod.new_id()
                    ins.append(f"        {h0} = OpSelect %float {is1} "
                               f"{c_green[ch]} {c_magenta[ch]}")
                    ins.append(f"        {h1} = OpSelect %float {is0} "
                               f"{c_cyan[ch]} {h0}")
                    ins.append(f"        {a1} = OpSelect %float {seen} "
                               f"{h1} {c_blue[ch]}")
                ins.append(f"        {a2} = OpSelect %float {scr['armed']} "
                           f"{a1} {c_amber[ch]}")
                ins.append(f"        {a3} = OpSelect %float {ok} {a2} "
                           f"{c_red[ch]}")
                col.append(a3)
        g1 = mod.new_id()
        ins.append(f"        {g1} = OpIEqual %bool {cls} {U(1)}")
        newc = []
        for ch in range(3):
            s = mod.new_id()
            ins.append(f"        {s} = OpSelect %float {g1} {col[ch]} {one}")
            n = mod.new_id()
            ins.append(f"        {n} = OpFMul %float {w['comps'][ch]} {s}")
            newc.append(n)
        nt = mod.new_id()
        ins.append(f"        {nt} = OpCompositeConstruct %v4float "
                   f"{newc[0]} {newc[1]} {newc[2]} {w['comps'][3]}")
        edits.append((w['line'] - 1, ins))
        mod.lines[w['line']] = re.sub(r'(OpImageWrite %\w+ %\w+ )%\w+\s*$',
                                      r'\g<1>' + nt, mod.lines[w['line']])
        done.append(w['line'] + 1)
    if not done:
        die(f"{mod.name}: no radiance image write reachable for the probe")
    rep = {'mode': mode, 'writes': done, 'skipped': skipped,
           'paints': bool(mode != 'xprobe' or rgen),
           'refetched': refetched, 'class_anchor': dom_id,
           'slot_members': n_slot, 'decoy': decoy,
           'sentinel': '%016x' % ((SENT_HI << 32) | SENT_LO),
           'magic': '%08x' % MAGIC}
    if mode in WORDS_PER_PIXEL:
        rep.update(pitch=PIX_PITCH, hash=PIX_HASH, hdr=SCRATCH_HDR,
                   sig=SCRATCH_SIG, park=PARK_WORD,
                   words_per_pixel=WORDS_PER_PIXEL[mode],
                   slot_words_read=[W_MAGIC, W_FRAME, W_SCR_LO, W_SCR_HI,
                                    W_SCR_WORDS])
    if mode == 'rq':
        rep.update(flags=knobs['flags'] if decoy != 'noflags' else 4,
                   mask=knobs['mask'], tmin=knobs['tmin'], tmax=knobs['tmax'],
                   space='world' if decoy == 'world' else 'camera_relative',
                   campos_member=cam['member'],
                   cbv_slot=ctx['cbv_slot'], matrix_members=ctx['mat'])
    return consts, edits, caps, exts, marker, decos, rep


# ------------------------------------------------------- post-assembly ids
def resolve_marker_ids(spv_path, decoy):
    """Rewrite the marker's lo=/hi= fields with the ids spirv-as actually used.

    spirv-as renumbers: `%9001 = OpConstant %uint N` in the assembly comes back
    as some other id in the binary, so the ids CANNOT be known before
    assembly. They are found here by the one value scan this design allows --
    at BUILD time, in a module we wrote, with a uniqueness assertion. The
    layer never does this; it reads the ids out of the marker.
    """
    b = bytearray(open(spv_path, 'rb').read())
    n = len(b) // 4
    w = list(struct.unpack('<%dI' % n, bytes(b[:n * 4])))
    if w[0] != 0x07230203:
        die(f"{spv_path}: not SPIR-V")
    uint_ty, lo_ids, hi_ids, marker_at = set(), [], [], None
    i = 5
    while i < n:
        ln, op = w[i] >> 16, w[i] & 0xffff
        if ln == 0 or i + ln > n:
            break
        if op == 54:                                  # OpFunction: header ends
            break
        if op == 21 and ln == 4 and w[i + 2] == 32 and w[i + 3] == 0:
            uint_ty.add(w[i + 1])
        elif op == 43 and ln == 4 and w[i + 1] in uint_ty:
            if w[i + 3] == SENT_LO:
                lo_ids.append(w[i + 2])
            elif w[i + 3] == SENT_HI:
                hi_ids.append(w[i + 2])
        elif op == 7 and ln >= 3:
            raw = bytes(b[(i + 2) * 4:(i + ln) * 4])
            s = raw.split(b'\0')[0].decode('utf-8', 'replace')
            if s.startswith(MARKER):
                if marker_at is not None:
                    die(f"{spv_path}: two markers")
                marker_at = ((i + 2) * 4, s)
        i += ln
    if decoy == 'nomarker':
        if marker_at is not None:
            die(f"{spv_path}: --decoy nomarker still carries a marker")
        return {'lo_id': None, 'hi_id': None, 'sentinel_pairs': len(lo_ids)}
    if marker_at is None:
        die(f"{spv_path}: the marker OpString did not survive assembly")
    want = 2 if decoy == 'scan' else 1
    if len(lo_ids) != want or len(hi_ids) != want:
        die(f"{spv_path}: {len(lo_ids)}/{len(hi_ids)} sentinel constants, "
            f"want {want}/{want}")
    if decoy == 'badid':
        return {'lo_id': 4294967295, 'hi_id': 4294967295,
                'sentinel_pairs': len(lo_ids)}
    off, s = marker_at
    pat = 'lo=%' + r'\d{' + str(ID_W) + '} hi=%' + r'\d{' + str(ID_W) + '}'
    rep = 'lo=%{0:0{2}d} hi=%{1:0{2}d}'.format(lo_ids[0], hi_ids[0], ID_W)
    new = re.sub(pat, rep, s)
    if new == s or len(new) != len(s):
        die(f"{spv_path}: marker id rewrite changed the length ({s!r})")
    b[off:off + len(new)] = new.encode()
    open(spv_path, 'wb').write(bytes(b))
    return {'lo_id': lo_ids[0], 'hi_id': hi_ids[0], 'sentinel_pairs': len(lo_ids)}


def process(path, outdir, mode, knobs, decoy, do_rt=True):
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
    rgen = is_raygen(mod)
    if rgen and mode != 'xprobe':
        die(f"{mod.name}: a RAYGEN was handed to --mode {mode}; only xprobe "
            f"patches the raygen side (handoff/116 sec 11)")
    if mode == 'ctl' or (not rgen and h in DECLINE_ALL) \
            or (mode == 'rq' and h in DECLINE_RQ):
        rep['bda'] = {'mode': mode, 'control': mode == 'ctl',
                      'declined': mode != 'ctl',
                      'writes': [], 'skipped': [], 'refetched': [],
                      'emitted': 0, 'decoy': decoy}
        return CS._emit(mod, outdir, target_env, rep)
    cfg = CFG(mod)
    writes = find_image_writes(mod)
    if rgen:
        writes = raygen_radiance_writes(mod, writes)
    consts, edits, caps, exts, marker, decos, r = build(
        mod, cfg, writes, mode, knobs, decoy, rgen=rgen)
    r['stage'] = 'raygen' if rgen else 'compute'
    apply_edits(mod, consts, edits)
    insert_sections(mod, caps, exts, marker, decos)
    r['emitted'] = 1
    r['declined'] = False
    r['control'] = False
    rep['bda'] = r
    rep = CS._emit(mod, outdir, target_env, rep)
    r.update(resolve_marker_ids(rep['out'], decoy))
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', rep['out']],
                       capture_output=True, text=True)
    if v.returncode != 0:
        os.unlink(rep['out'])
        die(f"spirv-val (vulkan1.4) FAILED after the marker rewrite "
            f"on {mod.name}:\n" + '\n'.join(v.stderr.splitlines()[:20]))
    rep['sha256'] = hashlib.sha256(open(rep['out'], 'rb').read()).hexdigest()
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', nargs='+')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--mode',
                    choices=('ctl', 'probe', 'rq', 'wprobe', 'wprobe2',
                             'xprobe'),
                    default='probe')
    ap.add_argument('--flags', type=int, default=DEFAULTS['flags'])
    ap.add_argument('--mask', type=int, default=DEFAULTS['mask'])
    ap.add_argument('--tmin', type=float, default=DEFAULTS['tmin'])
    ap.add_argument('--tmax', type=float, default=DEFAULTS['tmax'])
    ap.add_argument('--decoy', default='',
                    choices=('', 'nomarker', 'badid', 'scan', 'world',
                             'noflags', 'noguard', 'sameframe', 'stamped',
                             'paints', 'rgstore', 'xoffset'),
                    help='deliberately wrong builds, for verifier non-vacuity')
    ap.add_argument('--no-roundtrip-check', action='store_true')
    a = ap.parse_args()
    knobs = dict(flags=a.flags, mask=a.mask, tmin=a.tmin, tmax=a.tmax)
    reps = [process(p, a.outdir, a.mode, knobs, a.decoy,
                    do_rt=not a.no_roundtrip_check) for p in a.modules]
    print(json.dumps(reps, indent=1))


if __name__ == '__main__':
    main()
