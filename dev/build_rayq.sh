#!/usr/bin/env bash
# hunt-rayq -- Unlock 1: a Vulkan RAY QUERY inside rgs_reference_main.
# handoff/98-RAYQUERY.md is the document. Read its section 5 (the
# pre-registered outcome table) BEFORE looking at a frame.
#
#   ./dev/build_rayq.sh                # build + verify (nothing installed)
#   ./dev/build_rayq.sh --install      # ALSO park the twelve rungs in skin.set/
#   ./dev/build_rayq.sh --base NAME    # build on a different parked rung
#
# Fourteen rungs, one variable each, all on the STANDING selection's own bytes,
# in TWO FAMILIES that differ only in which ray the query clones.
#
# PRIMARY (site=primary) -- shoot these first. The query clones the module's
# own reconstructed CAMERA ray: origin = the zero triple (the camera's own
# position in P's space, 94 sec 3.3), direction = the module's own normalized
# view ray, t = |P| bracketed at +-0.1%. One identity per VISIBLE pixel, so
# the reading is a flat per-object silhouette in a single frame -- no denoiser
# argument, no "stable tint vs boil" judgement call.
#
#   hunt-rayq-p      InstanceId          hashed to 8 hues     <- THE LEAD RUNG
#   hunt-rayq-pcust  InstanceCustomIndex hashed to the same 8 hues
#   hunt-rayq-pprim  PrimitiveIndex      hashed to the same 8 hues
#   hunt-rayq-pclosest  InstanceId, but ray flags 513: the query commits the
#                    NEAREST hit in the bracket instead of any hit in it. Still
#                    exactly one OpRayQueryProceedKHR, so still zero added
#                    control flow -- TerminateOnFirstHit was never what made
#                    one Proceed sufficient (see patch_rayq.COMMIT_FLAGS).
#   hunt-rayq-psbt   instanceShaderBindingTableRecordOffset -- the app-assigned
#                    hit-group offset. It picks WHICH SHADER RECORD runs, so it
#                    plausibly names the MATERIAL, and a material has no reason
#                    to be rewritten when the TLAS is rebuilt.
#   hunt-rayq-pgeom  GeometryIndex -- which geometry of the hit BLAS. Stable per
#                    geometry WITHIN a BLAS, NOT unique across BLASes, so a few
#                    hues over the whole frame is the EXPECTED reading.
#   hunt-rayq-pxf    ObjectToWorld column 3 (the instance's world translation),
#                    RAW BITS, XOR-folded, NO quantisation. A static object's
#                    transform is bit-identical every frame and a moving one's
#                    is not: buildings stable + cars/NPCs flickering is the
#                    pre-registered SIGNATURE, not a defect.
#   hunt-rayq-pxfq   the same column 3, QUANTISED to 1 cm (x100, OpConvertFToS,
#                    OpBitcast) and NOTHING else. The CONTROL for -pxfw: if the
#                    TLAS is camera-relative this still flickers with camera
#                    motion, because rounding a value that genuinely changes
#                    does not make it stop changing.
#   hunt-rayq-pxfw   column 3 + 94 sec 3.3's world offset cbv[..][56].xyz, then
#                    the same 1 cm quantisation. If the TLAS is built in
#                    CAMERA-RELATIVE space -- which is what 98 sec 13.7 missed
#                    and the -pxf read-out points at -- this is a frame-stable
#                    WORLD translation: static buildings flat and stable under
#                    camera motion, movers changing. A PASS also puts 94's
#                    "inferred, not proven" world-offset line on screen.
#   hunt-rayq-pctl   InstanceId, PAINT GAIN 0 -- the control for this family
#
# BOUNCE (site=bounce) -- the original family. The query clones the module's
# own BOUNCE trace, t bracketed at +-0.1% of the payload's own hit distance.
# The latched identity is the first bounce, which is stochastic; kept because
# it is the only family that can say anything about the light INSIDE a
# reflection.
#
#   hunt-rayq        InstanceId          hashed to 8 hues
#   hunt-rayq-cust   InstanceCustomIndex hashed to the same 8 hues
#   hunt-rayq-prim   PrimitiveIndex      hashed to the same 8 hues
#   hunt-rayq-ctl    InstanceId, PAINT GAIN 0 -- the control for this family
#
# A control per family is not redundancy: the two splices emit different
# instructions, so -ctl is NOT a valid control for -p. In both, the ray query
# is emitted and executes and every multiplier is exactly 1.0 -- byte-DISTINCT
# from the base, and it must be VISUALLY INDISTINGUISHABLE from it. That is
# the control the sentinel never had: it separates "the query changed the
# picture" from "the query broke the picture", and it is the only rung that
# can convict the LAYER (a pipeline that refuses the capability is a black
# screen, not a colour).
#
# The no-hit multiplier differs by family ON PURPOSE. Bounce: BLACK, because
# the bounce ray has a hit distance and an empty bracket is a failure worth
# seeing. Primary: IDENTITY, because the primary ray legitimately misses on
# every sky pixel and the sky staying UNPAINTED is this family's built-in
# control (the 56 sky argument) -- a coloured sky means the query is
# committing garbage and the frame is void.
#
# The 77 compute modules, the 4 rgs_restirgi and the 2 radiance-write-free
# reference permutations ship BYTE-VERBATIM from the base and are cmp-asserted.
# Only 10 of the 12 rgs_reference_main are touched -- the same 10 that 55/56
# painted, for the same reason (40c6faab / ab7f1822 have no radiance write at
# all, so there is nowhere to read the query back).
#
# The rungs REQUIRE a layer that enables VK_KHR_ray_query on the VkDevice
# (swap_layer.c, handoff/98 section 6). Without it the layer's own guard sends
# these modules to the NEXT overlay -- never to vanilla (GOTCHAS: "an overlay
# reject must fall through") -- and the launch reads as the base image with
# `rayq_reject` lines in ~/callisto_swap.jsonl. Prove the layer first:
#     ./dev/patch_rayq.sh --selftest
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_rayq.py"
VERIFY="$MOD_DIR/dev/verify_rayq.py"
WORK="$MOD_DIR/dev/disasm/rayq"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }

mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }

echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the reference raygens ---------------
# Without this the "-ctl is the same modules with gain 0" claim rests on the
# patcher, and the coverage gate below could be satisfied by an assembler
# artefact. 94 sec 11 is the precedent.
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  10 of 10 reference permutations round-trip byte-identically"
rm -rf "$WORK/rt"

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.rayq.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir
    local dest="$1" src="$2"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$SRC/$p.rgs_reference_main.spv" "$dest/"; done
    # provenance: everything we did not patch is the base, byte for byte
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for p in "${PASS[@]}"; do
        cmp -s "$SRC/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            || { echo "  !! pass-through $p differs from the base" >&2; exit 1; }
    done
    # the 10 patched must DIFFER
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "  !! $h is byte-identical to the base -- the splice emitted nothing" >&2; exit 1; }
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# The PRIMARY rungs lead. A first-bounce paint at 1 spp through the denoiser
# gives a "stable tint vs boil" reading a screenshot cannot settle; a primary
# paint answers "is InstanceId a per-object identity" as flat silhouettes in
# ONE frame. The bounce rungs stay because they are the only ones that can say
# anything about the light *inside* a reflection.
echo "=== 2. patch + assemble the fourteen rungs"
declare -A RUNG_FIELD=( [hunt-rayq-p]=id [hunt-rayq-pcust]=custom
                        [hunt-rayq-pprim]=prim [hunt-rayq-pclosest]=id
                        [hunt-rayq-psbt]=sbt [hunt-rayq-pgeom]=geom
                        [hunt-rayq-pxf]=xf [hunt-rayq-pxfq]=xfq
                        [hunt-rayq-pxfw]=xfw
                        [hunt-rayq-pctl]=id
                        [hunt-rayq]=id [hunt-rayq-cust]=custom
                        [hunt-rayq-prim]=prim [hunt-rayq-ctl]=id )
declare -A RUNG_GAIN=( [hunt-rayq-p]=1.0 [hunt-rayq-pcust]=1.0
                       [hunt-rayq-pprim]=1.0 [hunt-rayq-pclosest]=1.0
                       [hunt-rayq-psbt]=1.0 [hunt-rayq-pgeom]=1.0
                       [hunt-rayq-pxf]=1.0 [hunt-rayq-pxfq]=1.0
                       [hunt-rayq-pxfw]=1.0
                       [hunt-rayq-pctl]=0.0
                       [hunt-rayq]=1.0 [hunt-rayq-cust]=1.0
                       [hunt-rayq-prim]=1.0 [hunt-rayq-ctl]=0.0 )
declare -A RUNG_SITE=( [hunt-rayq-p]=primary [hunt-rayq-pcust]=primary
                       [hunt-rayq-pprim]=primary [hunt-rayq-pclosest]=primary
                       [hunt-rayq-psbt]=primary [hunt-rayq-pgeom]=primary
                       [hunt-rayq-pxf]=primary [hunt-rayq-pxfq]=primary
                       [hunt-rayq-pxfw]=primary
                       [hunt-rayq-pctl]=primary
                       [hunt-rayq]=bounce [hunt-rayq-cust]=bounce
                       [hunt-rayq-prim]=bounce [hunt-rayq-ctl]=bounce )
# commit mode: 'first' = flags 517 (TerminateOnFirstHit), 'closest' = flags 513.
# Both need exactly ONE OpRayQueryProceedKHR -- see patch_rayq.COMMIT_FLAGS --
# so -pclosest costs zero added control flow, same as every other rung.
declare -A RUNG_COMMIT=( [hunt-rayq-pclosest]=closest )
declare -A RUNG_FLAGS=( [hunt-rayq-pclosest]=513 )
ORDER=(hunt-rayq-p hunt-rayq-pcust hunt-rayq-pprim hunt-rayq-pclosest
       hunt-rayq-psbt hunt-rayq-pgeom hunt-rayq-pxf hunt-rayq-pxfq hunt-rayq-pxfw
       hunt-rayq-pctl
       hunt-rayq hunt-rayq-cust hunt-rayq-prim hunt-rayq-ctl)
for r in "${ORDER[@]}"; do
    patch_set "$WORK/p.$r" --field "${RUNG_FIELD[$r]}" --gain "${RUNG_GAIN[$r]}" \
              --site "${RUNG_SITE[$r]}" --commit "${RUNG_COMMIT[$r]:-first}"
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r"
    echo "  swaps.$r: 93 modules, 10 patched, site=${RUNG_SITE[$r]}, commit=${RUNG_COMMIT[$r]:-first}, flags=${RUNG_FLAGS[$r]:-517}, spirv-val (vulkan1.4) clean"
done
# The two sites must not collide: a primary rung and a bounce rung of the same
# field must differ on every patched module, or one of them is not what it says.
d=0
for h in "${TARGETS[@]}"; do
    cmp -s "$MOD_DIR/swaps.hunt-rayq-p/$h.rgs_reference_main.spv" \
           "$MOD_DIR/swaps.hunt-rayq/$h.rgs_reference_main.spv" || d=$((d+1))
done
[[ "$d" == 10 ]] || { echo "  !! only $d of 10 primary modules differ from the bounce build" >&2; exit 1; }
echo "  10 of 10 primary modules differ from the bounce build of the same field"

# --- 3. coverage, from the REPORTS, never from byte counts (the 42 rule) ----
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir = sys.argv[1]
rungs = sys.argv[2:]
# rung -> (expected ray flags, expected commit mode). Kept here rather than
# passed in, so gate 3 cannot be satisfied by whatever the build script felt
# like asking for: it is a second, independent statement of the same fact.
WANT = {'hunt-rayq-pclosest': (513, 'closest')}
bad = []
CENSUS = None
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    mods, writes, skipped, flags, fields, sites = 0, 0, 0, set(), set(), set()
    commits = set()
    want_flags, want_commit = WANT.get(r, (517, 'first'))
    for f in sorted(glob.glob(os.path.join(d, '*.rayq.report.json'))):
        rep = json.load(open(f))[0]
        q = rep['rayq']
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        mods += 1
        writes += len(q['painted'])
        # every skip must be one of the two documented, benign kinds
        for s in q['skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
            skipped += 1
        flags.add(q['ray_flags'])
        commits.add(q.get('commit'))
        fields.add(q['field'])
        sites.add(q['site'])
        if q['site'] == 'primary':
            if not q.get('primary'):
                bad.append((r, rep['module'], 'site=primary but no primary-ray '
                                              'reconstruction was recorded'))
            elif len(q['primary']['V']) != 3 or None in q['primary']['V']:
                bad.append((r, rep['module'], 'primary view ray incomplete'))
        elif q.get('primary'):
            bad.append((r, rep['module'], 'site=bounce but a primary ray was recorded'))
        if q['accel'] != q['trace_operands'].split()[0]:
            bad.append((r, rep['module'], 'accel is not the trace operand'))
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if flags != {want_flags}:
        bad.append((r, '-', f'ray flags {sorted(flags)}, want {{{want_flags}}}'))
    if commits != {want_commit}:
        bad.append((r, '-', f'commit modes {sorted(commits)}, want {{{want_commit}}}'))
    if len(fields) != 1:
        bad.append((r, '-', f'modules disagree on the field: {sorted(fields)}'))
    if len(sites) != 1:
        bad.append((r, '-', f'modules disagree on the site: {sorted(sites)}'))
    if CENSUS is None:
        CENSUS = (writes, skipped)
    elif (writes, skipped) != CENSUS:
        bad.append((r, '-', f'painted/skipped {(writes, skipped)} != {CENSUS} '
                            '(the rungs must differ by ONE variable)'))
    print(f'  {r:19s} 10 modules, {writes} painted writes, '
          f'{skipped} benign skips, site={sorted(sites)[0]}, '
          f'field={sorted(fields)[0]}, flags={want_flags} ({want_commit})')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. no ray was added, and exactly one query was ------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src = sys.argv[1], sys.argv[2]
rungs = sys.argv[3:]
bad = []
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f)
        b = dis(os.path.join(src, h + '.rgs_reference_main.spv'))
        if h in ('40c6faab52a13874', 'ab7f1822eeb0331b'):
            if 'RayQueryKHR' in a:
                bad.append(f'{r}/{h}: pass-through carries a ray query')
            continue
        if a.count('OpTraceRayKHR') != b.count('OpTraceRayKHR'):
            bad.append(f'{r}/{h}: trace count {a.count("OpTraceRayKHR")} != '
                       f'base {b.count("OpTraceRayKHR")} -- a RAY was added')
        for op, want in (('OpRayQueryInitializeKHR', 1),
                         ('OpRayQueryProceedKHR', 1),
                         ('OpRayQueryGetIntersectionTypeKHR', 1),
                         ('OpTypeRayQueryKHR', 1)):
            if a.count(op) != want:
                bad.append(f'{r}/{h}: {a.count(op)} x {op}, want {want}')
        if 'OpCapability RayQueryKHR' not in a:
            bad.append(f'{r}/{h}: no RayQueryKHR capability')
        if 'SPV_KHR_ray_query' not in a:
            bad.append(f'{r}/{h}: no SPV_KHR_ray_query extension')
    print(f'  {r:17s} 10 x (1 query, 1 proceed, 0 added rays), 2 pass-throughs clean')
if bad:
    for x in bad[:12]:
        sys.stderr.write('    ' + x + '\n')
    sys.exit(1)
PY

# --- 5. the gain-0 rebuild must reproduce each control byte for byte -------
# Each site needs its OWN control: the primary splice and the bounce splice
# emit different instructions, so -ctl is NOT a valid control for -p.
echo "=== 5. --gain 0 reproducibility"
gain0_check () {   # $1 = site, $2 = control rung
    patch_set "$WORK/p.regain0.$1" --field id --gain 0.0 --site "$1"
    local d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$WORK/p.regain0.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 0 ]] || { echo "  !! $d of 10 gain-0 rebuilds differ from $2" >&2; exit 1; }
    echo "  site=$1: 10 of 10 byte-identical to $2"
    d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 $2 modules differ from the base" >&2; exit 1; }
    echo "  site=$1: 10 of 10 differ from the base -- the control executes the query"
}
gain0_check primary hunt-rayq-pctl
gain0_check bounce  hunt-rayq-ctl
# and the two controls must differ from EACH OTHER, or one site is a no-op
d=0
for h in "${TARGETS[@]}"; do
    cmp -s "$MOD_DIR/swaps.hunt-rayq-pctl/$h.rgs_reference_main.spv" \
           "$MOD_DIR/swaps.hunt-rayq-ctl/$h.rgs_reference_main.spv" || d=$((d+1))
done
[[ "$d" == 10 ]] || { echo "  !! only $d of 10 controls differ between the two sites" >&2; exit 1; }
echo "  10 of 10 primary controls differ from the bounce controls"

# --- 6. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "=== 6. verifier"
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-p"     --field id     --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pcust" --field custom --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pprim" --field prim   --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pclosest" --field id  --site primary --commit closest
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-psbt"  --field sbt    --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pgeom" --field geom   --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pxf"   --field xf     --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pxfq"  --field xfq    --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pxfw"  --field xfw    --site primary
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-pctl"  --field id     --site primary --gain0
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq"      --field id
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-cust" --field custom
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-prim" --field prim
python3 "$VERIFY" "$MOD_DIR/swaps.hunt-rayq-ctl"  --field id --gain0

reject () {  # $1 = human name, rest = verifier args
    local what="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $what -- it is vacuous" >&2; exit 1
    fi
    echo "  rejects $what, as required"
}
echo "  non-vacuity, 39 ways:"
reject "the unpatched base"                 "$SRC"
reject "the gain-0 control read as a probe" "$MOD_DIR/swaps.hunt-rayq-ctl" --field id
reject "the probe read as the control"      "$MOD_DIR/swaps.hunt-rayq" --field id --gain0
reject "the InstanceId rung read as prim"   "$MOD_DIR/swaps.hunt-rayq" --field prim
# the two sites must not be able to impersonate each other
reject "the PRIMARY rung read as a bounce rung" \
       "$MOD_DIR/swaps.hunt-rayq-p" --field id --site bounce
reject "the BOUNCE rung read as a primary rung" \
       "$MOD_DIR/swaps.hunt-rayq" --field id --site primary
# the two commit modes must not be able to impersonate each other either:
# 517 and 513 differ by one bit and that bit is the whole of -pclosest
reject "the first-hit rung read as closest-hit" \
       "$MOD_DIR/swaps.hunt-rayq-p" --field id --site primary --commit closest
reject "the closest-hit rung read as first-hit" \
       "$MOD_DIR/swaps.hunt-rayq-pclosest" --field id --site primary
reject "the pprim rung read as an InstanceId rung" \
       "$MOD_DIR/swaps.hunt-rayq-pprim" --field id --site primary
# The five field rungs of sec 13 and sec 14 differ ONLY in what feeds the hash,
# so each one read as any of the other four must be rejected: 5 accepts above
# and the 20 rejects below are the full 5x5 matrix. It matters more here than
# it did at 3x3, because xf, xfq and xfw share ONE getter -- check 7's per-
# getter count cannot separate them and only 7b's re-derivation of the fold
# can, so without this matrix "the build differs" would be the only evidence
# that the quantisation or the world offset is there at all.
FIELDRUNGS=(psbt:sbt pgeom:geom pxf:xf pxfq:xfq pxfw:xfw)
for A in "${FIELDRUNGS[@]}"; do
    ra="${A%%:*}"; fa="${A##*:}"
    for B in "${FIELDRUNGS[@]}"; do
        fb="${B##*:}"
        [[ "$fa" == "$fb" ]] && continue
        reject "hunt-rayq-$ra read as --field $fb" \
               "$MOD_DIR/swaps.hunt-rayq-$ra" --field "$fb" --site primary
    done
done
# ...and the two new rungs against the three uint fields as well, so the matrix
# covers xfq/xfw against every other field this patcher can emit.
for A in pxfq pxfw; do
    for fb in id custom prim; do
        reject "hunt-rayq-$A read as --field $fb" \
               "$MOD_DIR/swaps.hunt-rayq-$A" --field "$fb" --site primary
    done
done
patch_set "$WORK/p.decoy_ray" --field id --gain 1.0 --decoy ray
assemble  "$WORK/rung.decoy_ray" "$WORK/p.decoy_ray"
reject "a --decoy ray build (origin is not the trace's origin)" "$WORK/rung.decoy_ray"
patch_set "$WORK/p.decoy_pray" --field id --gain 1.0 --decoy ray --site primary
assemble  "$WORK/rung.decoy_pray" "$WORK/p.decoy_pray"
reject "a --decoy ray PRIMARY build (direction is the bounce ray's)" \
       "$WORK/rung.decoy_pray" --site primary
patch_set "$WORK/p.decoy_flags" --field id --gain 1.0 --decoy flags
assemble  "$WORK/rung.decoy_flags" "$WORK/p.decoy_flags"
reject "a --decoy flags build (ray flags 0, not 517)" "$WORK/rung.decoy_flags"

# --- 6b. the hash chain: nothing per-frame may reach the paint --------------
# 98 sec 12.6(c). The audit is an independent reader: it starts at the
# committed-field getter in the SHIPPED bytes, walks forward to the latch and
# on through every hash multiply, then takes the transitive operand closure of
# each select chain and requires every leaf to be a constant, a ray-query
# getter, or one of the two Private latch variables. An LCG state, a frame
# index, a sample index or any descriptor load appears as a FOREIGN leaf.
echo "=== 6b. hash-chain audit"
AUDIT="$MOD_DIR/dev/audit_rayq_hash.py"
python3 "$AUDIT" "$MOD_DIR/swaps.${ORDER[0]}" --ids || exit 1
for r in "${ORDER[@]:1}"; do
    python3 "$AUDIT" "$MOD_DIR/swaps.$r" || exit 1
done
reject_audit () {   # $1 = human name, $2 = directory
    if python3 "$AUDIT" "$2" >/dev/null 2>&1; then
        echo "  !! the hash audit ACCEPTS $1 -- it is vacuous" >&2; exit 1
    fi
    echo "  rejects $1, as required"
}
reject_audit "the unpatched base (no query at all)" "$SRC"
patch_set "$WORK/p.decoy_hash" --field id --gain 1.0 --site primary --decoy hash
assemble  "$WORK/rung.decoy_hash" "$WORK/p.decoy_hash"
reject_audit "a --decoy hash build (this frame's radiance folded into the hash)" \
             "$WORK/rung.decoy_hash"
# 98 sec 14: the FOLD whitelist had to widen for the quantised/offset fields, so
# the audit gained a backwards walk from the OpStore into the latch. This decoy
# is the only thing that proves that walk is not vacuous -- it folds the
# bracket's own depth-derived t into the latched value, upstream of the paint,
# where 12.6(c)'s select-chain closure cannot see it.
patch_set "$WORK/p.decoy_latch" --field xfw --gain 1.0 --site primary --decoy latch
assemble  "$WORK/rung.decoy_latch" "$WORK/p.decoy_latch"
reject_audit "a --decoy latch build (the depth-derived t folded into the LATCH)" \
             "$WORK/rung.decoy_latch"
# and the field verifier must refuse it too -- the fold is no longer the
# documented one
reject "a --decoy latch build read as --field xfw" \
       "$WORK/rung.decoy_latch" --field xfw --site primary

# --- 7. MANIFESTs ----------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung, $3 = tail
    sed -e "1s/^$BASE /$2 /" \
        -e "1s/ref=12([^)]*)/ref=12(10 rayq ${RUNG_SITE[$2]} + 2 pass-through)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    {   echo "# $2 (handoff/98): an OpRayQueryInitializeKHR spliced after the path"
        echo "# loop's radiance trace in 10 of 12 rgs_reference_main; flags"
        if [[ "${RUNG_COMMIT[$2]:-first}" == closest ]]; then
            echo "# 513 = Opaque|SkipAABBs -- the CLOSEST hit, not the first."
        else
            echo "# 517 = Opaque|TerminateOnFirstHit|SkipAABBs."
        fi
        if [[ "${RUNG_SITE[$2]}" == primary ]]; then
            echo "# site=PRIMARY: the query clones the module's OWN reconstructed camera"
            echo "# ray -- origin = the zero triple (the camera's position in P's own"
            echo "# space, 94 sec 3.3), direction = the module's own normalized view ray,"
            echo "# t = |P| bracketed at +-0.1%. One identity per VISIBLE pixel."
        else
            echo "# site=BOUNCE: the query clones the module's own bounce trace, t"
            echo "# bracketed at +-0.1% of the trace's own payload word3. The latched"
            echo "# identity is the FIRST BOUNCE, which is stochastic."
        fi
        echo "# $3"
        echo "# REQUIRES a layer that enables VK_KHR_ray_query (./dev/patch_rayq.sh --selftest)."
        echo "# Read handoff/98 section 5 BEFORE the screen."
    } >> "$1/MANIFEST.txt"
}
manifest "$MOD_DIR/swaps.hunt-rayq-p"     hunt-rayq-p     "Paints hash(InstanceId). THE LEAD RUNG -- shoot this first."
manifest "$MOD_DIR/swaps.hunt-rayq-pcust" hunt-rayq-pcust "Paints hash(InstanceCustomIndex) at the primary hit."
manifest "$MOD_DIR/swaps.hunt-rayq-pprim" hunt-rayq-pprim "Paints hash(PrimitiveIndex) at the primary hit -- confetti is the PASS."
manifest "$MOD_DIR/swaps.hunt-rayq-pclosest" hunt-rayq-pclosest "Paints hash(InstanceId) at the primary hit, committing the NEAREST hit in the bracket instead of any hit in it."
manifest "$MOD_DIR/swaps.hunt-rayq-psbt" hunt-rayq-psbt "Paints hash(instanceShaderBindingTableRecordOffset) at the primary hit -- the app-assigned hit-group/material selector."
manifest "$MOD_DIR/swaps.hunt-rayq-pgeom" hunt-rayq-pgeom "Paints hash(GeometryIndex) at the primary hit -- one or two hues over the frame is the EXPECTED reading."
manifest "$MOD_DIR/swaps.hunt-rayq-pxf" hunt-rayq-pxf "Paints hash(ObjectToWorld[3] raw bits, XOR-folded) at the primary hit -- static geometry stable, moving geometry flickering, BY CONSTRUCTION."
manifest "$MOD_DIR/swaps.hunt-rayq-pxfq" hunt-rayq-pxfq "Paints hash(quantise(ObjectToWorld[3], 1 cm)) at the primary hit -- the CONTROL for -pxfw: quantisation alone, no world offset."
manifest "$MOD_DIR/swaps.hunt-rayq-pxfw" hunt-rayq-pxfw "Paints hash(quantise(ObjectToWorld[3] + cbv[..][56].xyz, 1 cm)) at the primary hit -- 94 sec 3.3's world offset; static buildings stable under camera motion is the pre-registered PASS."
manifest "$MOD_DIR/swaps.hunt-rayq-pctl"  hunt-rayq-pctl  "CONTROL for the primary rungs: gain 0, every multiplier 1.0; must look exactly like $BASE."
manifest "$MOD_DIR/swaps.hunt-rayq"      hunt-rayq      "Paints hash(InstanceId)."
manifest "$MOD_DIR/swaps.hunt-rayq-cust" hunt-rayq-cust "Paints hash(InstanceCustomIndex)."
manifest "$MOD_DIR/swaps.hunt-rayq-prim" hunt-rayq-prim "Paints hash(PrimitiveIndex)."
manifest "$MOD_DIR/swaps.hunt-rayq-ctl"  hunt-rayq-ctl  "CONTROL for the bounce rungs: gain 0, every multiplier 1.0; must look exactly like $BASE."

echo
if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json \
               "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        echo "  parked -> $park ($(ls "$park"/*.spv | wc -l) modules)"
    done
else
    echo "NOT installed. To park: ./dev/build_rayq.sh --install"
fi
echo
echo "select with skinspec=hunt-rayq-p (LEAD) | hunt-rayq-pcust | hunt-rayq-pprim"
echo "            | hunt-rayq-pclosest | hunt-rayq-psbt | hunt-rayq-pgeom"
echo "            | hunt-rayq-pxf | hunt-rayq-pxfq | hunt-rayq-pxfw | hunt-rayq-pctl"
echo "            | hunt-rayq | hunt-rayq-cust | hunt-rayq-prim | hunt-rayq-ctl"
echo "contract: ser=class + shadowset=full-shadow ($BASE's own), and a layer"
echo "with VK_KHR_ray_query enabled -- ./dev/patch_rayq.sh --selftest proves that."
