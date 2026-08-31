#!/usr/bin/env python3
"""Traced-thickness ear glow (handoff/59; spec 51 sec 7 step 3 + 56 sec 7).

At the sun-NEE site of each paintable rgs_reference_main, inject ONE extra
OpTraceRayKHR (clone-by-id of live operands, 55's method) that measures the
geometric thickness of the primary surface along the sun direction, and add a
per-channel Beer-Lambert transmission term exp(-thickness/ld) * sunRadiance * k
into the module's radiance image writes. ld = (3.67, 1.37, 0.68) mm, the same
Jensen skin1 set as the spectral kernel (52) and the terminator bleed (53):
a ~5 mm ear transmits red and kills green/blue -- the saturated red glow IS
the spectral falloff, no tint knob.

The REVERSED-segment measurement (why the ray is not "along -L from the hit"):
  origin    = P + S*T_CAP          (S = the module's own cone-jittered unit
                                    sun direction; P = the module's own
                                    offset NEE origin)
  direction = -S, tmax = T_SEG < T_CAP
  first hit = the sun-side surface of whatever P is inside of, FRONT-FACING
              to the ray -- the hit configuration every engine ray already
              exercises. thickness = T_CAP - hitT.
A forward ray from P toward the sun would need BACK-FACE hits from inside the
flesh, a configuration no engine ray exercises and instance-level culling
could silently kill. The reversed segment needs no such assumption, and its
failure modes all land on T=0 (identity):
  - miss (nothing sun-side within T_CAP; includes "origin buried in flesh"):
    the engine's real miss-0 writes payload member 3 = 10000 (PROVEN in-module:
    the sun-NEE trace itself relies on mask-0 => miss => member3==10000, and
    the primary trace tests member3==10000 for its sky path), so hitT=10000
    fails the validity compare => contribution 0.
  - the payload member 3 is additionally PRE-ARMED to 10000 before the trace,
    so even a total no-write leaves T=0. Identity-when-dead by construction.
  - occluder sun-side of P (hat brim): small hitT => thickness ~ T_CAP => T~0.

Three gates, all module-derived, folded into the cullMask (no new branches;
mask 0 = guaranteed near-free miss, 55's costing):
  bounce==0   the loop counter phi (init 0, +1, compared against the bounce
              bound) equals 0 -- transmission is a primary-surface term only
  backlit     the condition of the module's own OpSelect(cond, 0, 39) cullMask
              idiom at the sun-NEE trace (cond = N.S <= 0)
  skin        clone of the module's own post-loop G-buffer material fetch
              (heap[registers[1]+5], word.y & ~31), compared == 32 (class 1)
              instead of its == 160 (class 5)

Cost: one extra trace per pixel per bounce; mask 0 (miss, near-free) unless
skin+backlit+bounce0, where it traces a <=2 cm segment and runs the radiance
CHS once on a hit.

Emission is straight-line (stores into 3 Function-storage floats accumulated
at the radiance writes) -- no new control flow, no phis, no replace_all_uses.

V2 (handoff/62; the fix for 60 sec 3 defects 1-3 via routes (a)+(b''')):
two additional validity terms folded into the k select, everything else
v1-identical. Both terms are identity-when-dead by construction.

  (b''') albedo-similarity gate: the reference CHS family (0b190a1f, see
  handoff/61 sec 2) round-trips the hit's RGBA8 albedo in payload member 0.
  The thickness hit's albedo must be within ALBEDO_EPS per RGB channel of
  the pixel's own albedo, read fresh from the primary radiance payload
  variable (found by its Select(1040,16) flags idiom; liveness asserted:
  every store to it precedes the radiance trace, and the bounce==0 gate
  guarantees the bounce-0 CHS pack is still live at the splice). THIS IS A
  THRESHOLDED HEURISTIC, not identity: another character's skin passes
  (geometrically rare); skin-dark-as-cloth may fail closed. Miss fails
  closed twice over: member 0 is pre-armed 0 AND member 3 stays 10000.

  (a) sun-visibility ray from the entry point Q = thicknessOrigin + hitT*(-S):
  NEE-shaped -- literal flags 12 (terminate-on-first-hit + skip-CHS; no CHS
  runs, payload ABI irrelevant), the engine's own tmin/tmax (1e-6/10000),
  missIndex 0, direction S, payload zero-armed exactly like the engine's own
  NEE pre-arm; visible <=> member3 == 10000 (ms_empty's proven handshake).
  The origin is offset by the ENGINE'S OWN self-hit scheme, mirrored per
  module from its NEE-origin construction (not invented): offset =
  c0*N*clamp(0.005*sqrt(t),.005,.1)*[N.z>0] - c1*D*(1+9*clamp(t/1000,0,1)),
  with c0/c1 cloned from the module's own cbv slot, N = the thickness hit's
  own decoded oct-normal (payload member 1), D = -S, t = thickness hitT.
  The cullMask is Select(gate AND thin AND similar, 39, 0), so the ray is a
  near-free guaranteed miss unless it can actually change the answer; a
  mask-0 miss writes member3=10000 ("visible") but every such lane is
  already dead through the same AND at the k select.

V3 (handoff/64; the fix for 63's three boundary-leak survivors): the
reference PT is a HYBRID -- no traced camera primary. It fetches raster
depth (heap[registers[1]+1], the module's own fetch, ==0 = sky early-out),
unprojects it to a camera-relative raster position P_raster (the FDiv
triple), applies its own cbv[77] self-hit offset, and the bounce-0
"radiance trace" RE-FINDS that surface as a real ray query. On sub-pixel
boundary slivers the re-trace can hit a DIFFERENT surface (strand/collar/
fringe in front of the skin that won the raster pixel) -- the class gate
(raster) and every hit-side term (traced) then disagree, and v2's albedo
compare degenerates to prop-vs-prop. The v3 CONSISTENCY GATE closes this:
|P_tracedPrimary - P_raster|^2 < CONS_EPS^2, ANDed into the thickness-trace
cullMask. Both sides are the module's OWN values, in scope at the splice by
structured dominance (the whole PT body lives inside the depth!=0 branch;
asserted mechanically per module): P_tracedPrimary = the pre-offset hit
position (P_i + t*D, the FAdd pair feeding the NEE-origin offset),
P_raster = the unprojection FDiv triple feeding the position phis' initial
values. No new fetch, no slot arithmetic, no lift from another family --
GOTCHAS 13 is satisfied by the module itself. Identity-when-dead: cons
false => mask 0 => t stays 10000 => thin false => contribution exactly 0.
Also in v3: ALBEDO_EPS 0.25 -> 0.10.

V4 (handoff/68; the fix for 67's flat-on RED + yellow ear rim): v3's
two-sided norm compare saw praster's LATERAL registration error (~2 px of
internal-res mis-registration, ~3-5mm/m through face slopes) and killed
true positives at range. The deployed-binary read found no additive
along-ray systematic (prehit = the exact traced hit; offsets live only in
ray origins and the back-off cancels in the re-hit), so v4 projects the
error out instead of subtracting anything: s = Delta . D_hat, kill only
on the leak side (s < -eps_eff, re-trace hit nearer the camera), with
eps_eff = EPS0 + B*t + A*t*sqrt(1-mu^2)/max(mu,CMIN) -- see the CONS_*
constants block. D/t/N are harvested from the module's own NEE-offset and
prehit chains with cross-checks. Also in v4: ALBEDO_EPS back to 0.25.

V5 (handoff/71; 70's W1+W3): the ray is FLIPPED. The reversed segment above
was v1's founding assumption -- "a forward ray would need back-face hits
from inside the flesh, a configuration no engine ray exercises" -- and its
material blindness is what v2's albedo gate, v3's consistency gate and v4's
one-sided distance-aware gate were all patching. 56 overturned the fear's
premise class (an injected trace with overridden operands executes and
round-trips the CHS), so v5 tests the configuration directly and carries
the BVH-strips-interior-backfaces risk as its pre-registered falsifier
(everything dark -> revert to v4 machinery + the s-band probe, 69 sec 2).
  origin    = the sun-NEE trace's own origin operand VERBATIM (P + the
              engine's self-hit offset)
  direction = the sun-NEE trace's own direction operand VERBATIM (S)
  flags     = 32 (CullFrontFacingTrianglesKHR), tmax = T_SEG
The entering front face is culled; inside real backlit flesh the first
visible surface is the sun-side wall seen FROM WITHIN -- a backface at
exactly t = the true sun-path flesh thickness. Validity = TH_FLOOR < t <
T_VALID. The leak classes die by geometry: a card's own backface sits at
~0.2-0.5mm (under TH_FLOOR); a face-behind-strand pixel finds no backface
within T_SEG through the head; strand stacks still fail the sun-visibility
ray. THE CONSISTENCY GATE IS GONE (find_raster_position is no longer
called); the albedo gate (b3) and the visibility ray (a) stay, with the
vis-ray offset mirror's D now = S (the flipped ray's direction). In probe
mode the min-thickness floor stands where cons stood in the palette: RED =
floor fails only (a card's own backface), YELLOW = floor AND albedo fail.
W3 (--wide/--wrap, the soft rungs): raw Beer-Lambert maps 2-3mm of
thickness to a 3-20x brightness cliff -- 69's "lightbulb". The soft
transfer is 0.5*(exp(-t/ld) + exp(-t/(wide*ld))) per channel (t in [1,8]mm
spans ~2-3x on red), and the k select is multiplied by a smoothstep wrap
w = smoothstep(0, WRAP, -N.S) on the module's own primary normal, so the
backlit border feathers instead of snapping.
"""
import argparse, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_skin_brdf as P
from patch_skin_brdf import apply_edits, roundtrip_check, die
from patch_chs_brdf import load_lenient
from patch_compute_brdf import find_image_writes, detect_target_env
from patch_subtype_probe import _gi_zeroish

# --- physics (Jensen skin1, per-channel diffuse mfp; engine units = meters,
#     evidenced by tmin 1e-6 / radiance tmax 10000 / NEE-to-light dynamic tmax
#     in these modules and RED engine convention) -------------------------
LD_M   = (0.00367, 0.00137, 0.00068)   # ld in meters (3.67/1.37/0.68 mm)
T_SEG  = 0.018         # trace tmax = max measurable sun-path thickness (v5
                       # traces FROM the surface TOWARD the sun; miss = thick)
T_VALID = 0.0179       # hitT below this = real hit (miss writes 10000)
TH_FLOOR = 0.0015      # v5 min-thickness floor: a primary card's own backface
                       # sits at ~0.2-0.5 mm, the thinnest real ear at ~2 mm
CLAMP  = 100.0         # contribution ceiling per channel (fp16 headroom)
ALBEDO_EPS = 0.25      # v4: back to v2's value (67 item 3 -- 0.10 killed
                       # plain-skin ear rims, YELLOW at two S4 sites; every
                       # ear glowed under 0.25; leaks stay dead via cons,
                       # albedo being vacuous at leak pixels per 65 sec 0).
# PROBE mode (handoff/66): gate-attribution paint, replaces the glow.
# Additive palette, one hue per pixel by priority; dead channels are exact
# 0.0 (floors fed AgX inset crosstalk and only hurt pair separation -- the
# degeneracy check in 66 sec 2 picked these values numerically).
PROBE_PALETTE = (
    ("magenta", (3.2, 0.0, 3.2)),   # thin-hit valid but sun-vis ray FAILS
    ("yellow",  (3.2, 3.2, 0.0)),   # vis passes; consistency AND albedo fail
    ("red",     (3.2, 0.0, 0.0)),   # consistency fails only
    ("green",   (0.0, 3.2, 0.0)),   # albedo fails only
    ("blue",    (0.0, 0.4, 3.2)),   # all pass (v3's surviving glow set)
)

# V5 (handoff/71): the consistency gate and its CONS_* constants are GONE
# -- the flipped ray measures sun-path thickness directly and the leak
# classes it thresholded against die by geometry (see the docstring).

TRACE_RE = re.compile(r'^(\s*)OpTraceRayKHR\s+(.+?)\s*$')


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


def _payload_ptr_and_struct(mod, storage):
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpTypePointer ' + storage + r' (%\w+)\s*$', ln)
        if not m:
            continue
        _, d = mod.find_def(m.group(2))
        if d and d.startswith('OpTypeStruct'):
            mem = d.split()[1:]
            if len(mem) < 4 or mem[0] != '%uint' or mem[3] != '%float':
                die(f"{mod.name}: payload struct members {mem} -- expected "
                    f"member0 %uint, member3 %float")
            return m.group(1), m.group(2)
    die(f"{mod.name}: no {storage} struct pointer type")


def _ensure_line(mod, consts, pattern, make):
    for ln in mod.lines:
        m = re.match(pattern, ln)
        if m:
            return m.group(1)
    nid = mod.new_id()
    consts.append(make(nid))
    return nid


def _uc(mod, consts, v, memo={}):
    key = (id(mod), v)
    if key in memo:
        return memo[key]
    nid, decl = mod.uconst(v)
    if decl:
        consts.append(decl)
    memo[key] = nid
    return nid


def _fc(mod, consts, v):
    nid, decl = mod.const(v)
    if decl:
        consts.append(decl)
    return nid


def _glsl_set(mod):
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpExtInstImport "GLSL.std.450"', ln)
        if m:
            return m.group(1)
    die(f"{mod.name}: no GLSL.std.450 import")


def find_nee_trace(mod, fs, fe):
    """The sun-NEE trace: literal flags 12, tmax %float_10000, cullMask from
    OpSelect(cond, 0, 39). Exactly one per module (verified across all 12)."""
    hits = []
    for i in range(fs, fe):
        m = TRACE_RE.match(mod.lines[i])
        if not m:
            continue
        ops = m.group(2).split()
        if len(ops) == 11 and ops[1] == '%uint_12' and ops[9] == '%float_10000':
            hits.append((i, m.group(1), ops))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} flags-12/tmax-10000 traces, expected 1")
    line, ind, ops = hits[0]
    _, mdef = mod.find_def(ops[2])
    sm = re.match(r'OpSelect %uint (%\w+) %uint_0 %uint_39\s*$', mdef or '')
    if not sm:
        die(f"{mod.name}: sun-NEE cullMask def is not Select(cond,0,39): {mdef}")
    return {"line": line, "ind": ind, "ops": ops, "backlit": sm.group(1)}


def find_sun_radiance(mod, trace_line):
    """In the sun-NEE block (nearest label above the trace): the slot-6 cbv
    load and its three extracts = sun radiance RGB. The slot-5 (sun dir)
    sibling chain must exist in the same range, or this is not the sun pair."""
    top = trace_line
    while top > 0 and not re.match(r'\s*%\w+ = OpLabel', mod.lines[top]):
        top -= 1
    cbv = None
    for i in range(top, trace_line):
        m = re.match(r'\s*(%\w+)\s*=\s*OpAccessChain %_ptr_Uniform_v4float '
                     r'(%\w+) %uint_0 %uint_6\s*$', mod.lines[i])
        if m:
            cbv = (i, m.group(1), m.group(2))
            break
    if not cbv:
        die(f"{mod.name}: no slot-6 cbv chain in the sun-NEE block")
    i, chain, base = cbv
    if not any(re.match(r'\s*%\w+\s*=\s*OpAccessChain %_ptr_Uniform_v4float '
                        + re.escape(base) + r' %uint_0 %uint_5\s*$', mod.lines[j])
               for j in range(top, trace_line)):
        die(f"{mod.name}: slot-6 chain has no slot-5 (sun dir) sibling on {base}")
    lm = re.match(r'\s*(%\w+)\s*=\s*OpLoad %v4float ' + re.escape(chain),
                  mod.lines[i + 1])
    if not lm:
        die(f"{mod.name}: slot-6 chain not followed by its load")
    ld = lm.group(1)
    ext = {}
    for j in range(i + 2, min(i + 8, trace_line)):
        m = re.match(r'\s*(%\w+)\s*=\s*OpCompositeExtract %float '
                     + re.escape(ld) + r' (\d)\s*$', mod.lines[j])
        if m:
            ext[int(m.group(2))] = m.group(1)
    if sorted(ext) != [0, 1, 2]:
        die(f"{mod.name}: sun radiance extracts incomplete: {sorted(ext)}")
    return [ext[0], ext[1], ext[2]]


def find_bounce_counter(mod, fs, fe, nee_line):
    """The bounce-loop counter phi: OpPhi %uint with an %uint_0 incoming and
    an OpIAdd %uint <x> %uint_1 incoming (the IAdd base need not be the phi
    itself -- dxil-spirv re-merges the counter through interior phis), whose
    incremented value feeds an Op[SU]LessThan that conditions a back-edge
    branch TARGETING THE PHI'S OWN BLOCK (a real loop), and whose body span
    [header, back-edge] CONTAINS the sun-NEE trace. Interior light-sampling
    loops fail one of the last two. Outermost (earliest header) wins if
    nested loops both qualify; ambiguity at the same depth dies loudly."""
    cands = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpPhi %uint (.+)$', mod.lines[i])
        if not m:
            continue
        phi, rest = m.group(1), m.group(2).split()
        inc = [rest[k] for k in range(0, len(rest), 2)]
        if '%uint_0' not in inc:
            continue
        hdr = None
        for j in range(i, fs, -1):
            lm = re.match(r'\s*(%\w+)\s*=\s*OpLabel', mod.lines[j])
            if lm:
                hdr = (j, lm.group(1))
                break
        if not hdr:
            continue
        for v in inc:
            if v == '%uint_0':
                continue
            _, d = mod.find_def(v)
            if not (d and re.match(r'OpIAdd %uint %\w+ %uint_1\s*$', d)):
                continue
            for j in range(fs, fe):
                cm = re.match(r'\s*(%\w+)\s*=\s*Op[SU]LessThan %bool '
                              + re.escape(v) + r' ', mod.lines[j])
                if not cm:
                    continue
                for b in range(j, min(j + 3, fe)):
                    bm = re.match(r'\s*OpBranchConditional '
                                  + re.escape(cm.group(1)) + r' (%\w+) (%\w+)',
                                  mod.lines[b])
                    if bm and hdr[1] in (bm.group(1), bm.group(2)) \
                          and hdr[0] < nee_line < b:
                        cands.append((hdr[0], phi))
    if not cands:
        die(f"{mod.name}: no bounce-counter phi found")
    cands.sort()
    if len(cands) > 1 and cands[0][0] == cands[1][0]:
        die(f"{mod.name}: ambiguous bounce-counter phis at the same header: "
            f"{cands}")
    return cands[0][1]


def find_class_fetch(mod, fs, fe):
    """The G-buffer material-word fetch feeding the module's own class test
    (& 0xFFFFFFE0 == 160). Returns the def LINES of the fetch chain and the
    ids they consume, for clone-by-text at the splice site."""
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpBitwiseAnd %uint (%\w+) '
                     r'%uint_4294967264\s*$', mod.lines[i])
        if not m:
            continue
        if not any(re.match(r'\s*%\w+\s*=\s*OpIEqual %bool '
                            + re.escape(m.group(1)) + r' %uint_160\s*$',
                            mod.lines[j]) for j in range(i, min(i + 4, fe))):
            continue
        _, extd = mod.find_def(m.group(2))
        em = re.match(r'OpCompositeExtract %uint (%\w+) 1\s*$', extd or '')
        if not em:
            die(f"{mod.name}: class-test AND source is not extract-1: {extd}")
        return em.group(1)   # the OpImageFetch result id
    die(f"{mod.name}: no & ~31 == 160 class test found")


def find_radiance_trace(mod, fs, fe, nee_line):
    """V2: the primary/bounce radiance trace -- flags from the module's own
    OpSelect(cond, 1040, 16) idiom, cullMask %uint_255, tmax %float_10000.
    Exactly one per module; must precede the sun-NEE trace (same iteration:
    trace, shade, NEE). Returns its payload variable id + trace line.
    LIVENESS assert for the (b''') pixel-albedo read: every OpStore through
    any access chain on that payload variable must sit at or before the
    radiance trace line -- so at the splice (bounce==0 gated) member 0 still
    holds the bounce-0 CHS albedo pack, unclobbered."""
    hits = []
    for i in range(fs, fe):
        m = TRACE_RE.match(mod.lines[i])
        if not m:
            continue
        ops = m.group(2).split()
        if len(ops) != 11 or ops[2] != '%uint_255' or ops[9] != '%float_10000':
            continue
        _, fdef = mod.find_def(ops[1])
        if fdef and re.match(r'OpSelect %uint %\w+ %uint_1040 %uint_16\s*$', fdef):
            hits.append((i, ops))
    if len(hits) != 1:
        die(f"{mod.name}: {len(hits)} Select(1040,16)/mask-255 radiance "
            f"traces, expected 1")
    line, ops = hits[0]
    if not line < nee_line:
        die(f"{mod.name}: radiance trace at {line+1} does not precede the "
            f"sun-NEE trace at {nee_line+1}")
    pv = ops[10]
    _, pdef = mod.find_def(pv)
    if not (pdef and pdef.startswith('OpVariable') and 'RayPayloadKHR' in pdef):
        die(f"{mod.name}: radiance trace payload {pv} is not a RayPayloadKHR "
            f"variable: {pdef}")
    chains = set()
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpInBoundsAccessChain %\w+ '
                     + re.escape(pv) + r' %uint_\d+\s*$', mod.lines[i])
        if m:
            chains.add(m.group(1))
    for i in range(fs, fe):
        m = re.match(r'\s*OpStore (%\w+) ', mod.lines[i])
        if m and m.group(1) in chains and i > line:
            die(f"{mod.name}: store into radiance payload {pv} at line {i+1} "
                f"AFTER the radiance trace ({line+1}) -- pixel-albedo "
                f"liveness broken, refusing")
    return {"line": line, "payload": pv}


def _def_re(mod, idtok, pattern):
    _, d = mod.find_def(idtok)
    m = re.match(pattern + r'\s*$', d or '')
    if not m:
        die(f"{mod.name}: origin-offset walk: {idtok} def mismatch:\n"
            f"  have: {d}\n  want: {pattern}")
    return m


def _fval(mod, idtok):
    _, d = mod.find_def(idtok)
    m = re.match(r'OpConstant %float (\S+)', d or '')
    return float(m.group(1)) if m else None


def _comm(mod, idtok, op, side_pat):
    """Match `id = Op<op> %float %a %b` where ONE operand's def matches
    side_pat (regex on the def) or side_pat(value) for constants; returns
    (matched_operand, other_operand)."""
    m = _def_re(mod, idtok, r'Op' + op + r' %float (%\w+) (%\w+)')
    for a, b in ((m.group(1), m.group(2)), (m.group(2), m.group(1))):
        _, d = mod.find_def(a)
        if callable(side_pat):
            v = _fval(mod, a)
            if v is not None and side_pat(v):
                return a, b
        elif d and re.match(side_pat + r'\s*$', d):
            return a, b
    die(f"{mod.name}: origin-offset walk: neither operand of {idtok} "
        f"({m.group(1)}, {m.group(2)}) matches")


def find_origin_offset(mod, nee):
    """V2 (a): verify the module's NEE-origin self-hit offset construction
    (handoff/62; read from d622fb9e :2626-2666) and return what the mirror
    needs: the v4float cbv LOAD id to clone (components 0/1 = the normal-
    and ray-direction offset scales) and the cbv slot for the report.
      origin.x = P.x + (c0*N.x*nmag*[N.z>0] - c1*D.x*(1+9*clamp(t/1000)))
      nmag     = clamp(0.005*2^(log2(t)/2), 0.005, 0.1)
    The walk asserts this exact shape hop by hop and dies on any deviation
    (verification-first: a differing permutation is a finding, not a guess)."""
    om = _def_re(mod, nee["ops"][6], r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    prehit = []
    offs = []
    for ci in (1, 2, 3):
        addm = _def_re(mod, om.group(ci), r'OpFAdd %float (%\w+) (%\w+)')
        oc, ac = None, None
        for cand, other in ((addm.group(1), addm.group(2)),
                            (addm.group(2), addm.group(1))):
            _, d = mod.find_def(cand)
            if d and re.match(r'OpFSub %float %\w+ %\w+\s*$', d):
                oc, ac = cand, other
                break
        if oc is None:
            die(f"{mod.name}: origin-offset walk: no FSub addend in NEE "
                f"origin component {ci-1}")
        # A = P_i + t*D: one operand is the position phi, the other t*D
        am = _def_re(mod, ac, r'OpFAdd %float (%\w+) (%\w+)')
        if not any(re.match(r'OpPhi %float ', mod.find_def(x)[1] or '')
                   for x in (am.group(1), am.group(2))):
            die(f"{mod.name}: pre-offset hit position {ac} is not "
                f"FAdd(phi, t*D)")
        prehit.append(ac)
        offs.append(oc)
    add = _def_re(mod, om.group(1), r'OpFAdd %float (%\w+) (%\w+)')
    off = offs[0]
    sm = _def_re(mod, off, r'OpFSub %float (%\w+) (%\w+)')
    nterm, dterm = sm.group(1), sm.group(2)
    # dTerm = (c1 * D.x) * dscale;  dscale = 1 + 9*NClamp(t*0.001, 0, 1)
    dmul, dscale = _comm(mod, dterm, 'FMul', r'OpFMul %float %\w+ %\w+')
    ds_in, _one = _comm(mod, dscale, 'FAdd', lambda v: abs(v - 1.0) < 1e-9)
    ds_in, ds_nine = _comm(mod, _one, 'FMul', r'OpExtInst %float %\w+ NClamp .*')
    if abs(_fval(mod, ds_nine) - 9.0) > 1e-9:
        die(f"{mod.name}: origin-offset walk: dscale multiplier is not 9")
    c1, _dx = _comm(mod, dmul, 'FMul',
                    r'OpCompositeExtract %float %\w+ 1')
    c1m = _def_re(mod, c1, r'OpCompositeExtract %float (%\w+) 1')
    # normalTerm = (c0 * N.x) * (nmag * [N.z>0])
    nmul, nsc = _comm(mod, nterm, 'FMul', r'OpFMul %float %\w+ %\w+')
    # disambiguate: nsc must contain the Select(gz,1,0) branch
    def has_select(idtok):
        m = re.match(r'OpFMul %float (%\w+) (%\w+)\s*$',
                     mod.find_def(idtok)[1] or '')
        if not m:
            return False
        return any(re.match(r'OpSelect %float %\w+ %float_1 %float_0\s*$',
                            mod.find_def(x)[1] or '')
                   for x in (m.group(1), m.group(2)))
    if not has_select(nsc):
        nmul, nsc = nsc, nmul
    if not has_select(nsc):
        die(f"{mod.name}: origin-offset walk: no [N.z>0] select factor")
    c0, _nx = _comm(mod, nmul, 'FMul',
                    r'OpCompositeExtract %float %\w+ 0')
    c0m = _def_re(mod, c0, r'OpCompositeExtract %float (%\w+) 0')
    if c0m.group(1) != c1m.group(1):
        die(f"{mod.name}: origin-offset scales come from different loads: "
            f"{c0m.group(1)} vs {c1m.group(1)}")
    ld = c0m.group(1)
    ldm = _def_re(mod, ld, r'OpLoad %v4float (%\w+)')
    chm = _def_re(mod, ldm.group(1),
                  r'OpAccessChain %_ptr_Uniform_v4float %\w+ %uint_0 %uint_(\d+)')
    # V4 (handoff/68): harvest the bounce-0 direction D (from the dterm AND
    # the prehit t*D product -- cross-checked), the primary hitT t (must be
    # common across components), and the primary-hit normal N (from the
    # nterm; N.z cross-checked against the [N.z>0] select condition).
    dirs, dirs2, norms, ts = [], [], [], []
    nsci = None
    for i in range(3):
        smi = _def_re(mod, offs[i], r'OpFSub %float (%\w+) (%\w+)')
        nti, dti = smi.group(1), smi.group(2)
        dmi, _dsci = _comm(mod, dti, 'FMul', r'OpFMul %float %\w+ %\w+')
        _c1i, di = _comm(mod, dmi, 'FMul',
                         r'OpCompositeExtract %float %\w+ 1')
        dirs.append(di)
        nmi, nsci = _comm(mod, nti, 'FMul', r'OpFMul %float %\w+ %\w+')
        if not has_select(nsci):
            nmi, nsci = nsci, nmi
        if not has_select(nsci):
            die(f"{mod.name}: v4 walk: component {i} nterm has no "
                f"[N.z>0] select factor")
        _c0i, ni = _comm(mod, nmi, 'FMul',
                         r'OpCompositeExtract %float %\w+ 0')
        norms.append(ni)
        pam = _def_re(mod, prehit[i], r'OpFAdd %float (%\w+) (%\w+)')
        tdi = None
        for cand in (pam.group(1), pam.group(2)):
            _, dd = mod.find_def(cand)
            if dd and re.match(r'OpFMul %float %\w+ %\w+\s*$', dd):
                tdi = cand
        if tdi is None:
            die(f"{mod.name}: v4 walk: prehit component {i} has no t*D term")
        ti, d2i = _comm(mod, tdi, 'FMul', r'OpLoad %float %\w+')
        ts.append(ti)
        dirs2.append(d2i)
    if dirs != dirs2:
        die(f"{mod.name}: v4 walk: direction ids differ between dterm "
            f"({dirs}) and prehit t*D ({dirs2})")
    if len(set(ts)) != 1:
        die(f"{mod.name}: v4 walk: prehit t differs per component: {ts}")
    nsm = _def_re(mod, nsci, r'OpFMul %float (%\w+) (%\w+)')
    sel = None
    for x in (nsm.group(1), nsm.group(2)):
        _, dd = mod.find_def(x)
        if dd and re.match(r'OpSelect %float %\w+ %float_1 %float_0\s*$', dd):
            sel = x
    gzm = _def_re(mod, sel, r'OpSelect %float (%\w+) %float_1 %float_0')
    nzm = _def_re(mod, gzm.group(1),
                  r'OpFOrdGreaterThan %bool (%\w+) %float_0')
    if nzm.group(1) != norms[2]:
        die(f"{mod.name}: v4 walk: [N.z>0] select tests {nzm.group(1)} "
            f"but harvested N.z is {norms[2]}")
    return {"load": ld, "slot": int(chm.group(1)), "prehit": prehit,
            "dir": dirs, "t": ts[0], "normal": norms}


def find_raster_position(mod, fs, fe, nee, prehit):
    """V3: the unprojected raster-surface position [x,y,z] (camera-relative,
    the FDiv triple), plus the mechanical dominance proof that it is in
    scope at the splice. Walk: each pre-offset hit component = FAdd(t*D,
    posPHI); posPHI's loop-carried incoming must be the NEE-origin
    component (the loop invariant v2 already relies on); its INITIAL
    incoming = FAdd(normTerm, FSub(P_raster, dTerm)) -- the engine applying
    its own self-hit offset to the raster surface. P_raster components must
    all be FDiv sharing one denominator (the unprojection w). Dominance:
    defs precede the loop header, and the module's depth==0 sky branch
    (heap[registers[1]+1] fetch, .x == 0.0) merges AFTER the splice -- the
    whole PT body is inside the depth!=0 arm, so pre-loop defs dominate it
    (structured control flow)."""
    om = _def_re(mod, nee["ops"][6], r'OpCompositeConstruct %v3float (%\w+) (%\w+) (%\w+)')
    praster, denoms, phis = [], [], []
    for ci, pre in enumerate(prehit):
        am = _def_re(mod, pre, r'OpFAdd %float (%\w+) (%\w+)')
        phi = next((x for x in (am.group(1), am.group(2))
                    if re.match(r'OpPhi %float ', mod.find_def(x)[1] or '')), None)
        pm = _def_re(mod, phi, r'OpPhi %float (%\w+) (%\w+) (%\w+) (%\w+)')
        inc = {pm.group(1): pm.group(2), pm.group(3): pm.group(4)}
        carried = om.group(ci + 1)
        init = next((v for v in inc if v != carried), None)
        if carried not in inc or init is None:
            die(f"{mod.name}: position phi {phi} loop-carried incoming is "
                f"not the NEE-origin component {carried}: {inc}")
        im = _def_re(mod, init, r'OpFAdd %float (%\w+) (%\w+)')
        sub = None
        for cand in (im.group(1), im.group(2)):
            _, d = mod.find_def(cand)
            if d and re.match(r'OpFSub %float %\w+ %\w+\s*$', d):
                sub = cand
        if sub is None:
            die(f"{mod.name}: position init {init} has no FSub addend "
                f"(raster - dTerm)")
        sm = _def_re(mod, sub, r'OpFSub %float (%\w+) (%\w+)')
        dm = _def_re(mod, sm.group(1), r'OpFDiv %float (%\w+) (%\w+)')
        _, subd = mod.find_def(sm.group(2))
        if not re.match(r'OpFMul %float ', subd or ''):
            die(f"{mod.name}: raster-offset subtrahend {sm.group(2)} is not "
                f"an FMul dTerm: {subd}")
        praster.append(sm.group(1))
        denoms.append(dm.group(2))
        phis.append(phi)
    if len(set(denoms)) != 1:
        die(f"{mod.name}: raster unprojection FDivs do not share one "
            f"denominator: {denoms}")
    hdr = None
    phi_line, _ = mod.find_def(phis[0])
    for j in range(phi_line, fs, -1):
        if re.match(r'\s*%\w+ = OpLabel', mod.lines[j]):
            hdr = j
            break
    for p in praster:
        pl, _ = mod.find_def(p)
        if not (fs < pl < hdr):
            die(f"{mod.name}: raster position {p} (line {pl+1}) does not "
                f"precede the loop header (line {hdr+1})")
    # the depth==0 sky branch and its merge label
    merges = []
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpFOrdEqual %bool (%\w+) %float_0\s*$',
                     mod.lines[i])
        if not m:
            continue
        _, xd = mod.find_def(m.group(2))
        xm = re.match(r'OpCompositeExtract %float (%\w+) 0\s*$', xd or '')
        if not xm:
            continue
        _, fd = mod.find_def(xm.group(1))
        if not (fd and fd.startswith('OpImageFetch %v4float')):
            continue
        img = fd.split()[2]
        _, imgd = mod.find_def(img)
        lm = re.match(r'OpLoad %\w+ (%\w+)\s*$', imgd or '')
        if not lm:
            continue
        _, chd = mod.find_def(lm.group(1))
        cm = re.match(r'OpAccessChain %\w+ %\w+ (%\w+)\s*$', chd or '')
        if not cm:
            continue
        _, ixd = mod.find_def(cm.group(1))
        if not (ixd and re.match(r'OpIAdd %uint %\w+ %uint_1\s*$', ixd)):
            continue
        sm2 = re.match(r'\s*OpSelectionMerge (%\w+) None', mod.lines[i + 1])
        bc = re.match(r'\s*OpBranchConditional ' + re.escape(m.group(1)),
                      mod.lines[i + 2])
        if sm2 and bc:
            merges.append(sm2.group(1))
    if len(merges) != 1:
        die(f"{mod.name}: {len(merges)} depth==0 sky branches found, "
            f"expected exactly 1")
    ml, _ = mod.find_def(merges[0])
    if ml is None:
        ml = next(i for i in range(fs, fe)
                  if re.match(r'\s*' + re.escape(merges[0]) + r' = OpLabel',
                              mod.lines[i]))
    if ml < nee["line"]:
        die(f"{mod.name}: sky-branch merge {merges[0]} (line {ml+1}) "
            f"precedes the splice ({nee['line']+1}) -- dominance broken")
    return {"praster": praster, "header_line": hdr, "merge_line": ml}


def entry_block_span(mod, fs, fe):
    lab = next(i for i in range(fs, fe)
               if re.match(r'\s*%\w+ = OpLabel', mod.lines[i]))
    term = next(i for i in range(lab, fe)
                if re.match(r'\s*(OpBranch|OpBranchConditional|OpSwitch|'
                            r'OpReturn|OpUnreachable)\b',
                            mod.lines[i].strip()))
    return lab, term


def clone_chain(mod, root, safe_ids, fresh, out, fs):
    """Recursively clone the def chain of `root` with fresh ids, stopping at
    ids in safe_ids (constants, globals, entry-block defs). Returns the id to
    use for `root` at the splice site. Emits def lines into `out` in
    dependency order."""
    if root in fresh:
        return fresh[root]
    if root in safe_ids or not root.startswith('%'):
        return root
    ln, d = mod.find_def(root)
    if d is None or ln < fs:            # global scope: types/consts/vars
        return root
    if not re.match(r'Op(Load|AccessChain|InBoundsAccessChain|IAdd|IMul|'
                    r'CompositeConstruct|CompositeExtract|ImageFetch|Bitcast|'
                    r'ShiftRightLogical|BitwiseAnd|UConvert|RawAccessChainNV)\b', d):
        die(f"{mod.name}: clone_chain refuses op for {root}: {d.split()[0]} "
            f"(id defined mid-function, not in the safe set)")
    parts = d.split()
    newparts = [parts[0]]
    for p in parts[1:]:
        if p.startswith('%'):
            newparts.append(clone_chain(mod, p, safe_ids, fresh, out, fs))
        else:
            newparts.append(p)
    nid = mod.new_id()
    fresh[root] = nid
    out.append((nid, ' '.join(newparts)))
    return nid


def build(mod, k, probe=False, soft=None):
    consts, edits = [], []
    eline, fid = _entry(mod, 'RayGenerationKHR')
    fs, fe = _func_span(mod, fid)
    glsl = _glsl_set(mod)
    ptrS, _ = _payload_ptr_and_struct(mod, 'RayPayloadKHR')
    ptrPF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %float\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %float")
    ptrPU = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer RayPayloadKHR %uint\s*$',
        lambda n: f"    {n} = OpTypePointer RayPayloadKHR %uint")
    ptrFF = _ensure_line(mod, consts,
        r'\s*(%\w+)\s*=\s*OpTypePointer Function %float\s*$',
        lambda n: f"    {n} = OpTypePointer Function %float")
    boolt = _ensure_line(mod, consts, r'\s*(%\w+)\s*=\s*OpTypeBool\s*$',
        lambda n: f"    {n} = OpTypeBool")

    rep = {"k": None if probe else k, "t_seg": T_SEG,
           "ld_m": LD_M, "mode": "probe" if probe else "glow"}
    if probe:
        rep["palette"] = {n: v for n, v in PROBE_PALETTE}

    # ---- detectors, all before any edit (GOTCHAS 12) ----------------------
    writes = find_image_writes(mod)
    nee = find_nee_trace(mod, fs, fe)
    sunrad = find_sun_radiance(mod, nee["line"])
    counter = find_bounce_counter(mod, fs, fe, nee["line"])
    fetch_root = find_class_fetch(mod, fs, fe)
    radiance = find_radiance_trace(mod, fs, fe, nee["line"])       # v2
    offctor = find_origin_offset(mod, nee)                         # v2/v5
    eb_lab, eb_term = entry_block_span(mod, fs, fe)
    safe = set()
    for i in range(fs, eb_term):
        m = re.match(r'\s*(%\w+)\s*=\s*Op', mod.lines[i])
        if m:
            safe.add(m.group(1))
    rep["nee_line"] = nee["line"] + 1
    rep["backlit"] = nee["backlit"]
    rep["counter_phi"] = counter
    rep["sun_radiance"] = sunrad
    rep["radiance_line"] = radiance["line"] + 1
    rep["radiance_payload"] = radiance["payload"]
    rep["offset_cbv_slot"] = offctor["slot"]
    rep["albedo_eps"] = ALBEDO_EPS
    rep["th_floor"] = TH_FLOOR
    rep["soft"] = {"wide": soft[0], "wrap": soft[1]} if soft else None

    # ---- constants --------------------------------------------------------
    u0 = _uc(mod, consts, 0)
    u1 = _uc(mod, consts, 1)
    u3 = _uc(mod, consts, 3)
    u16 = _uc(mod, consts, 16)
    u32 = _uc(mod, consts, 32)
    f0 = _fc(mod, consts, 0.0)
    fseg = _fc(mod, consts, T_SEG)
    fflr = _fc(mod, consts, TH_FLOOR)
    fvalid = _fc(mod, consts, T_VALID)
    f10000 = _fc(mod, consts, 10000.0)
    if probe:
        pconst = [[(_fc(mod, consts, c) if c != 0.0 else None) for c in v]
                  for _, v in PROBE_PALETTE]
    else:
        fclamp = _fc(mod, consts, CLAMP)
        fk = _fc(mod, consts, k)
        finv = [_fc(mod, consts, 1.0 / ld) for ld in LD_M]
        if soft:
            finv2 = [_fc(mod, consts, 1.0 / (soft[0] * ld)) for ld in LD_M]
            fwrap = _fc(mod, consts, soft[1])
    # v2 constants (all dedup against the module's own by f32 value)
    u2 = _uc(mod, consts, 2)
    u8 = _uc(mod, consts, 8)
    u12 = _uc(mod, consts, 12)
    u39 = _uc(mod, consts, 39)
    u255 = _uc(mod, consts, 255)
    u4095 = _uc(mod, consts, 4095)
    f1 = _fc(mod, consts, 1.0)
    fn1 = _fc(mod, consts, -1.0)
    fhalf = _fc(mod, consts, 0.5)
    f9 = _fc(mod, consts, 9.0)
    f001 = _fc(mod, consts, 0.001)
    f0005 = _fc(mod, consts, 0.005)
    f01 = _fc(mod, consts, 0.1)
    finv255 = _fc(mod, consts, 1.0 / 255.0)
    finv2047 = _fc(mod, consts, 1.0 / 2047.5)
    feps = _fc(mod, consts, ALBEDO_EPS)

    # ---- entry block: fresh payload + 3 glow accumulators -----------------
    spay = mod.new_id()
    consts.append(f"    {spay} = OpVariable {ptrS} RayPayloadKHR")
    mod.lines[eline] = mod.lines[eline].rstrip() + ' ' + spay
    at = eb_lab
    while re.match(r'\s*%\w+ = OpVariable ', mod.lines[at + 1]):
        at += 1
    gv = [mod.new_id() for _ in range(3)]
    ind = '               '
    entry_ins = [f"{ind}{g} = OpVariable {ptrFF} Function" for g in gv]
    entry_ins += [f"{ind}OpStore {g} {f0}" for g in gv]
    edits.append((at, entry_ins))

    # ---- the splice, straight-line, after the sun-NEE trace ---------------
    ops = nee["ops"]
    ind = nee["ind"]
    ins = []
    nid = mod.new_id

    # skin gate: clone the module's own material fetch chain to this site
    cloned = []
    fetch_here = clone_chain(mod, fetch_root, safe, {}, cloned, fs)
    for cid, body in cloned:
        ins.append(f"{ind}{cid} = {body}")
    g_ext = nid(); ins.append(f"{ind}{g_ext} = OpCompositeExtract %uint {fetch_here} 1")
    g_and = nid(); ins.append(f"{ind}{g_and} = OpBitwiseAnd %uint {g_ext} %uint_4294967264")
    g_skin = nid(); ins.append(f"{ind}{g_skin} = OpIEqual {boolt} {g_and} {u32}")
    g_b0 = nid(); ins.append(f"{ind}{g_b0} = OpIEqual {boolt} {counter} {u0}")
    g_a1 = nid(); ins.append(f"{ind}{g_a1} = OpLogicalAnd {boolt} {g_skin} {nee['backlit']}")
    g_a2 = nid(); ins.append(f"{ind}{g_a2} = OpLogicalAnd {boolt} {g_a1} {g_b0}")
    # v5 (handoff/71, W1): no consistency gate. The thickness ray is the
    # FLIPPED one -- origin/direction are the sun-NEE trace's own operands
    # VERBATIM (ops[6]/ops[8]: P + the engine's self-hit offset, toward the
    # sun), flags CullFrontFacingTriangles (32): the entering front face is
    # culled and the first hit is the far wall's BACKFACE at t = the true
    # sun-path thickness. Validity = TH_FLOOR < t < T_VALID, post-trace.
    g_msk = nid(); ins.append(
        f"{ind}{g_msk} = OpSelect %uint {g_a2} %uint_39 {u0}")

    # component extracts of the flipped ray (Q construction and the W3
    # wrap need them; the trace itself uses the composites verbatim)
    o_c, s_c, oo, dd = [], [], ops[6], ops[8]
    for c in range(3):
        oe = nid(); ins.append(f"{ind}{oe} = OpCompositeExtract %float {oo} {c}")
        de = nid(); ins.append(f"{ind}{de} = OpCompositeExtract %float {dd} {c}")
        o_c.append(oe); s_c.append(de)

    # payload member chains (member 0 = albedo pack, 1 = oct-normal pack,
    # 2 = cone float, 3 = hitT) and the thickness-trace pre-arm: member 3
    # to 10000 (miss/thick default), member 0 to 0 ((b''') albedo fails
    # closed on a no-write even before the hitT term does), 1 and 2 zeroed
    # for definedness.
    m0c = nid(); ins.append(f"{ind}{m0c} = OpInBoundsAccessChain {ptrPU} {spay} {u0}")
    m1c = nid(); ins.append(f"{ind}{m1c} = OpInBoundsAccessChain {ptrPU} {spay} {u1}")
    m2c = nid(); ins.append(f"{ind}{m2c} = OpInBoundsAccessChain {ptrPF} {spay} {u2}")
    pa = nid(); ins.append(f"{ind}{pa} = OpInBoundsAccessChain {ptrPF} {spay} {u3}")
    ins.append(f"{ind}OpStore {m0c} {u0}")
    ins.append(f"{ind}OpStore {m1c} {u0}")
    ins.append(f"{ind}OpStore {m2c} {f0}")
    ins.append(f"{ind}OpStore {pa} {f10000}")
    ins.append(f"{ind}OpTraceRayKHR {ops[0]} {u32} {g_msk} {u1} {u1} {u0} "
               f"{oo} {ops[7]} {dd} {fseg} {spay}")
    t = nid(); ins.append(f"{ind}{t} = OpLoad %float {pa}")
    vdh = nid(); ins.append(f"{ind}{vdh} = OpFOrdLessThan {boolt} {t} {fvalid}")
    # v5 min-thickness floor; stands where cons stood in the probe palette
    cons = nid(); ins.append(f"{ind}{cons} = OpFOrdGreaterThan {boolt} {t} {fflr}")
    if probe:
        vd = vdh
    else:
        vd = nid(); ins.append(f"{ind}{vd} = OpLogicalAnd {boolt} {vdh} {cons}")
    ha = nid(); ins.append(f"{ind}{ha} = OpLoad %uint {m0c}")
    hn = nid(); ins.append(f"{ind}{hn} = OpLoad %uint {m1c}")

    # ---- v2 (b'''): thickness-hit albedo vs the pixel's own ---------------
    # fresh chain+load on the radiance payload VARIABLE (module-scope, so no
    # dominance question); liveness asserted in find_radiance_trace.
    pxc = nid(); ins.append(f"{ind}{pxc} = OpInBoundsAccessChain {ptrPU} {radiance['payload']} {u0}")
    pl = nid(); ins.append(f"{ind}{pl} = OpLoad %uint {pxc}")
    def unpack8(src, shift):
        s = src
        if shift is not None:
            s2 = nid(); ins.append(f"{ind}{s2} = OpShiftRightLogical %uint {src} {shift}")
            s = s2
        b = nid(); ins.append(f"{ind}{b} = OpBitwiseAnd %uint {s} {u255}")
        cf = nid(); ins.append(f"{ind}{cf} = OpConvertUToF %float {b}")
        r = nid(); ins.append(f"{ind}{r} = OpFMul %float {cf} {finv255}")
        return r
    sim = None
    for shift in (None, u8, u16):
        hc = unpack8(ha, shift)
        pc = unpack8(pl, shift)
        df = nid(); ins.append(f"{ind}{df} = OpFSub %float {hc} {pc}")
        av = nid(); ins.append(f"{ind}{av} = OpExtInst %float {glsl} FAbs {df}")
        lt = nid(); ins.append(f"{ind}{lt} = OpFOrdLessThan {boolt} {av} {feps}")
        if sim is None:
            sim = lt
        else:
            s2 = nid(); ins.append(f"{ind}{s2} = OpLogicalAnd {boolt} {sim} {lt}")
            sim = s2

    # ---- v2 (a): decode the thickness hit's oct normal (payload m1, the
    # module's own 12+12 codec -- handoff/61 sec 2) ------------------------
    na = nid(); ins.append(f"{ind}{na} = OpBitwiseAnd %uint {hn} {u4095}")
    nb0 = nid(); ins.append(f"{ind}{nb0} = OpShiftRightLogical %uint {hn} {u12}")
    nb = nid(); ins.append(f"{ind}{nb} = OpBitwiseAnd %uint {nb0} {u4095}")
    xa = nid(); ins.append(f"{ind}{xa} = OpConvertUToF %float {na}")
    ya = nid(); ins.append(f"{ind}{ya} = OpConvertUToF %float {nb}")
    xs = nid(); ins.append(f"{ind}{xs} = OpFMul %float {xa} {finv2047}")
    ys = nid(); ins.append(f"{ind}{ys} = OpFMul %float {ya} {finv2047}")
    xf = nid(); ins.append(f"{ind}{xf} = OpFAdd %float {xs} {fn1}")
    yf = nid(); ins.append(f"{ind}{yf} = OpFAdd %float {ys} {fn1}")
    axx = nid(); ins.append(f"{ind}{axx} = OpExtInst %float {glsl} FAbs {xf}")
    s1 = nid(); ins.append(f"{ind}{s1} = OpFSub %float {f1} {axx}")
    ayy = nid(); ins.append(f"{ind}{ayy} = OpExtInst %float {glsl} FAbs {yf}")
    zf = nid(); ins.append(f"{ind}{zf} = OpFSub %float {s1} {ayy}")
    nzf = nid(); ins.append(f"{ind}{nzf} = OpFNegate %float {zf}")
    tcl = nid(); ins.append(f"{ind}{tcl} = OpExtInst %float {glsl} NClamp {nzf} {f0} {f1}")
    gx = nid(); ins.append(f"{ind}{gx} = OpFOrdGreaterThanEqual {boolt} {xf} {f0}")
    gy = nid(); ins.append(f"{ind}{gy} = OpFOrdGreaterThanEqual {boolt} {yf} {f0}")
    ntc = nid(); ins.append(f"{ind}{ntc} = OpFNegate %float {tcl}")
    sx = nid(); ins.append(f"{ind}{sx} = OpSelect %float {gx} {ntc} {tcl}")
    sy = nid(); ins.append(f"{ind}{sy} = OpSelect %float {gy} {ntc} {tcl}")
    xo = nid(); ins.append(f"{ind}{xo} = OpFAdd %float {sx} {xf}")
    yo = nid(); ins.append(f"{ind}{yo} = OpFAdd %float {sy} {yf}")
    vv = nid(); ins.append(f"{ind}{vv} = OpCompositeConstruct %v3float {xo} {yo} {zf}")
    dp = nid(); ins.append(f"{ind}{dp} = OpDot %float {vv} {vv}")
    iq = nid(); ins.append(f"{ind}{iq} = OpExtInst %float {glsl} InverseSqrt {dp}")
    nvec = []
    for comp in (xo, yo, zf):
        r = nid(); ins.append(f"{ind}{r} = OpFMul %float {comp} {iq}")
        nvec.append(r)

    # ---- v2 (a): Q + the ENGINE'S OWN self-hit offset, mirrored ----------
    # Q_i = thicknessOrigin_i + t*S_i (v5: the ray runs TOWARD the sun);
    # then offset with the module's own scheme (find_origin_offset verified
    # the shape; c0/c1 cloned from its own cbv slot):
    #   + c0*N*clamp(0.005*sqrt(t),.005,.1)*[N.z>0]
    #   - c1*D*(1+9*clamp(t*0.001,0,1)),  D = S (the flipped ray), N = nvec.
    cloned2 = []
    ld2 = clone_chain(mod, offctor["load"], safe, {}, cloned2, fs)
    for cid, body in cloned2:
        ins.append(f"{ind}{cid} = {body}")
    c0e = nid(); ins.append(f"{ind}{c0e} = OpCompositeExtract %float {ld2} 0")
    c1e = nid(); ins.append(f"{ind}{c1e} = OpCompositeExtract %float {ld2} 1")
    dm0 = nid(); ins.append(f"{ind}{dm0} = OpFMul %float {t} {f001}")
    dm1 = nid(); ins.append(f"{ind}{dm1} = OpExtInst %float {glsl} NClamp {dm0} {f0} {f1}")
    dm2 = nid(); ins.append(f"{ind}{dm2} = OpFMul %float {dm1} {f9}")
    dsc = nid(); ins.append(f"{ind}{dsc} = OpFAdd %float {dm2} {f1}")
    lg = nid(); ins.append(f"{ind}{lg} = OpExtInst %float {glsl} Log2 {t}")
    lh = nid(); ins.append(f"{ind}{lh} = OpFMul %float {lg} {fhalf}")
    ex = nid(); ins.append(f"{ind}{ex} = OpExtInst %float {glsl} Exp2 {lh}")
    nm0 = nid(); ins.append(f"{ind}{nm0} = OpFMul %float {ex} {f0005}")
    nm1 = nid(); ins.append(f"{ind}{nm1} = OpExtInst %float {glsl} NMax {nm0} {f0005}")
    nmg = nid(); ins.append(f"{ind}{nmg} = OpExtInst %float {glsl} NMin {nm1} {f01}")
    gz = nid(); ins.append(f"{ind}{gz} = OpFOrdGreaterThan {boolt} {nvec[2]} {f0}")
    gs = nid(); ins.append(f"{ind}{gs} = OpSelect %float {gz} {f1} {f0}")
    nm2 = nid(); ins.append(f"{ind}{nm2} = OpFMul %float {nmg} {gs}")
    qv = []
    for i in range(3):
        td = nid(); ins.append(f"{ind}{td} = OpFMul %float {t} {s_c[i]}")
        qi = nid(); ins.append(f"{ind}{qi} = OpFAdd %float {o_c[i]} {td}")
        d1 = nid(); ins.append(f"{ind}{d1} = OpFMul %float {c1e} {s_c[i]}")
        d2 = nid(); ins.append(f"{ind}{d2} = OpFMul %float {d1} {dsc}")
        n1 = nid(); ins.append(f"{ind}{n1} = OpFMul %float {c0e} {nvec[i]}")
        n2 = nid(); ins.append(f"{ind}{n2} = OpFMul %float {n1} {nm2}")
        of = nid(); ins.append(f"{ind}{of} = OpFSub %float {n2} {d2}")
        qf = nid(); ins.append(f"{ind}{qf} = OpFAdd %float {qi} {of}")
        qv.append(qf)

    # ---- v2 (a): the visibility trace -- NEE-shaped, mask gated ----------
    if probe:
        vc0 = nid(); ins.append(f"{ind}{vc0} = OpLogicalAnd {boolt} {g_a2} {vd}")
        vmk = nid(); ins.append(f"{ind}{vmk} = OpSelect %uint {vc0} {u39} {u0}")
    else:
        vc0 = nid(); ins.append(f"{ind}{vc0} = OpLogicalAnd {boolt} {g_a2} {vd}")
        vc1 = nid(); ins.append(f"{ind}{vc1} = OpLogicalAnd {boolt} {vc0} {sim}")
        vmk = nid(); ins.append(f"{ind}{vmk} = OpSelect %uint {vc1} {u39} {u0}")
    ins.append(f"{ind}OpStore {m0c} {u0}")
    ins.append(f"{ind}OpStore {m1c} {u0}")
    ins.append(f"{ind}OpStore {m2c} {f0}")
    ins.append(f"{ind}OpStore {pa} {f0}")
    qC = nid(); ins.append(f"{ind}{qC} = OpCompositeConstruct %v3float {' '.join(qv)}")
    sC = nid(); ins.append(f"{ind}{sC} = OpCompositeConstruct %v3float {' '.join(s_c)}")
    ins.append(f"{ind}OpTraceRayKHR {ops[0]} {ops[1]} {vmk} {u1} {u1} {u0} "
               f"{qC} {ops[7]} {sC} {f10000} {spay}")
    t2 = nid(); ins.append(f"{ind}{t2} = OpLoad %float {pa}")
    vis = nid(); ins.append(f"{ind}{vis} = OpFOrdEqual {boolt} {t2} {f10000}")

    if probe:
        # ---- gate-attribution paint (handoff/66): one hue per pixel ------
        # base = class AND backlit AND bounce0 AND thin-hit; then by
        # priority: magenta = vis FAILS; yellow = cons+albedo fail; red =
        # cons only; green = albedo only; blue = all pass. Exhaustive and
        # mutually exclusive within base; no paint when base fails.
        nv = nid(); ins.append(f"{ind}{nv} = OpLogicalNot {boolt} {vis}")
        nc = nid(); ins.append(f"{ind}{nc} = OpLogicalNot {boolt} {cons}")
        ns = nid(); ins.append(f"{ind}{ns} = OpLogicalNot {boolt} {sim}")
        h_m = nid(); ins.append(f"{ind}{h_m} = OpLogicalAnd {boolt} {vc0} {nv}")
        pv = nid(); ins.append(f"{ind}{pv} = OpLogicalAnd {boolt} {vc0} {vis}")
        yy0 = nid(); ins.append(f"{ind}{yy0} = OpLogicalAnd {boolt} {nc} {ns}")
        h_y = nid(); ins.append(f"{ind}{h_y} = OpLogicalAnd {boolt} {pv} {yy0}")
        rr0 = nid(); ins.append(f"{ind}{rr0} = OpLogicalAnd {boolt} {nc} {sim}")
        h_r = nid(); ins.append(f"{ind}{h_r} = OpLogicalAnd {boolt} {pv} {rr0}")
        gg0 = nid(); ins.append(f"{ind}{gg0} = OpLogicalAnd {boolt} {cons} {ns}")
        h_g = nid(); ins.append(f"{ind}{h_g} = OpLogicalAnd {boolt} {pv} {gg0}")
        bb0 = nid(); ins.append(f"{ind}{bb0} = OpLogicalAnd {boolt} {cons} {sim}")
        h_b = nid(); ins.append(f"{ind}{h_b} = OpLogicalAnd {boolt} {pv} {bb0}")
        hues = (h_m, h_y, h_r, h_g, h_b)
        for c in range(3):
            acc = f0
            for hi in range(len(PROBE_PALETTE) - 1, -1, -1):
                pc = pconst[hi][c]
                if pc is None:
                    pc = f0
                sl = nid(); ins.append(
                    f"{ind}{sl} = OpSelect %float {hues[hi]} {pc} {acc}")
                acc = sl
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs2 = nid(); ins.append(f"{ind}{gs2} = OpFAdd %float {gl} {acc}")
            ins.append(f"{ind}OpStore {gv[c]} {gs2}")
    else:
        # ---- the k select: thin AND similar AND sunlit; t IS thickness ---
        ok0 = nid(); ins.append(f"{ind}{ok0} = OpLogicalAnd {boolt} {vd} {sim}")
        ok = nid(); ins.append(f"{ind}{ok} = OpLogicalAnd {boolt} {ok0} {vis}")
        kg = nid(); ins.append(f"{ind}{kg} = OpSelect %float {ok} {fk} {f0}")
        if soft:
            # W3 wrap: feather the backlit border -- w = smoothstep(0,
            # WRAP, -N.S) on the module's own primary normal and sun dir
            nvp = nid(); ins.append(f"{ind}{nvp} = OpCompositeConstruct %v3float {' '.join(offctor['normal'])}")
            svp = nid(); ins.append(f"{ind}{svp} = OpCompositeConstruct %v3float {' '.join(s_c)}")
            nds = nid(); ins.append(f"{ind}{nds} = OpDot %float {nvp} {svp}")
            bnd = nid(); ins.append(f"{ind}{bnd} = OpFNegate %float {nds}")
            wrp = nid(); ins.append(f"{ind}{wrp} = OpExtInst %float {glsl} SmoothStep {f0} {fwrap} {bnd}")
            kw = nid(); ins.append(f"{ind}{kw} = OpFMul %float {kg} {wrp}")
        else:
            kw = kg
        for c in range(3):
            e1 = nid(); ins.append(f"{ind}{e1} = OpFMul %float {t} {finv[c]}")
            e2 = nid(); ins.append(f"{ind}{e2} = OpFNegate %float {e1}")
            e3 = nid(); ins.append(f"{ind}{e3} = OpExtInst %float {glsl} Exp {e2}")
            if soft:
                # W3 transfer: 0.5*(exp(-t/ld) + exp(-t/(wide*ld)))
                e4 = nid(); ins.append(f"{ind}{e4} = OpFMul %float {t} {finv2[c]}")
                e5 = nid(); ins.append(f"{ind}{e5} = OpFNegate %float {e4}")
                e6 = nid(); ins.append(f"{ind}{e6} = OpExtInst %float {glsl} Exp {e5}")
                e7 = nid(); ins.append(f"{ind}{e7} = OpFAdd %float {e3} {e6}")
                tr = nid(); ins.append(f"{ind}{tr} = OpFMul %float {e7} {fhalf}")
            else:
                tr = e3
            m1 = nid(); ins.append(f"{ind}{m1} = OpFMul %float {tr} {kw}")
            m2 = nid(); ins.append(f"{ind}{m2} = OpFMul %float {m1} {sunrad[c]}")
            m3 = nid(); ins.append(f"{ind}{m3} = OpExtInst %float {glsl} NMin {m2} {fclamp}")
            gl = nid(); ins.append(f"{ind}{gl} = OpLoad %float {gv[c]}")
            gs = nid(); ins.append(f"{ind}{gs} = OpFAdd %float {gl} {m3}")
            ins.append(f"{ind}OpStore {gv[c]} {gs}")
    edits.append((nee["line"], ins))
    rep["splice_instructions"] = len(ins)
    rep["cloned_fetch_ops"] = len(cloned)
    rep["cloned_offset_ops"] = len(cloned2)

    # ---- add the accumulated glow at every radiance write -----------------
    added, skipped = [], []
    for w in writes:
        if w['comps'] is None:
            die(f"{mod.name}: write at line {w['line']+1} has a non-construct "
                f"texel -- refusing")
        c = w['comps']
        if all(_gi_zeroish(mod, x) for x in c[:3]):
            skipped.append({"line": w['line']+1, "why": "constant-zero"})
            continue
        if c[0] == c[1] == c[2]:
            skipped.append({"line": w['line']+1, "why": "scalar-broadcast"})
            continue
        wind = re.match(r'(\s*)', mod.lines[w['line']]).group(1)
        wi, newc = [], []
        for ch in range(3):
            l = nid(); wi.append(f"{wind}{l} = OpLoad %float {gv[ch]}")
            a = nid(); wi.append(f"{wind}{a} = OpFAdd %float {c[ch]} {l}")
            newc.append(a)
        nt = nid()
        wi.append(f"{wind}{nt} = OpCompositeConstruct %v4float "
                  f"{newc[0]} {newc[1]} {newc[2]} {c[3]}")
        edits.append((w['line'] - 1, wi))
        mod.lines[w['line']] = re.sub(
            r'(OpImageWrite %\w+ %\w+ )%\w+\s*$', r'\g<1>' + nt,
            mod.lines[w['line']])
        added.append({"line": w['line']+1})
    if not added:
        die(f"{mod.name}: no radiance write to add the glow at")
    rep["writes_added"], rep["writes_skipped"] = added, skipped
    return consts, edits, rep


def process(path, outdir, k, probe=False, soft=None):
    target_env = detect_target_env(path) or 'spv1.4'
    mod, problems = load_lenient(path)
    if not mod.ident:
        die(f"{mod.name}: no dxil identity")
    roundtrip_check(path, target_env)
    rep = dict(module=mod.name, ident=mod.ident)
    if problems:
        rep['module_warnings'] = problems
    consts, edits, rep['earglow'] = build(mod, k, probe=probe, soft=soft)
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
    if v.returncode != 0:
        os.unlink(spv_out)
        die(f"spirv-val FAILED on PATCHED {mod.name}:\n"
            + '\n'.join(v.stderr.splitlines()[:20]))
    rep['spirv_val'] = 'clean'
    rep['sha256'] = hashlib.sha256(open(spv_out, 'rb').read()).hexdigest()
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spvasm')
    ap.add_argument('--k', type=float, required=True,
                    help='transmission strength (sunRadiance multiplier); '
                         'ignored under --probe')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--probe', action='store_true',
                    help='gate-attribution paint instead of the glow '
                         '(handoff/66; v5 semantics -- RED is the '
                         'min-thickness floor, not cons)')
    ap.add_argument('--wide', type=float,
                    help='W3 soft transfer: second-lobe widening factor')
    ap.add_argument('--wrap', type=float,
                    help='W3 wrap: smoothstep upper edge on -N.S')
    args = ap.parse_args()
    if (args.wide is None) != (args.wrap is None):
        ap.error('--wide and --wrap must be given together')
    soft = (args.wide, args.wrap) if args.wide is not None else None
    print(json.dumps(process(args.spvasm, args.outdir, args.k,
                             probe=args.probe, soft=soft)))


if __name__ == '__main__':
    main()
