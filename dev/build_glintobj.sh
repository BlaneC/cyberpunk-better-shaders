#!/usr/bin/env bash
# glintobj -- OBJECT-SPACE car-paint glints, REPLACING `100`'s world-space cell
# feed at the hash input. handoff/106-OBJECT-SPACE-GLINTS.md is the document;
# read its section 9 (the pre-registered interpretation table) BEFORE looking
# at a frame.
#
#   ./dev/build_glintobj.sh              # build + 10 gates (nothing installed)
#   ./dev/build_glintobj.sh --install    # ALSO park the four rungs
#   ./dev/build_glintobj.sh --base NAME  # build on a different parked rung
#
# FOUR RUNGS, one variable each, all on the STANDING DEFAULT's own bytes.
#
#   glintobj-ctl   the patcher emits NOTHING and rewrites nothing, so the
#                  output is BYTE-IDENTICAL to the base (gate 5, resting on
#                  gate 1's round-trip neutrality). Control for the SELECTOR
#                  and the LAYER, not for the splice.
#   glintobj       THE FEATURE. One ray query per glint preamble, down the
#                  module's OWN traced segment; the committed instance's
#                  WorldToObject puts the shading point into OBJECT space and
#                  THAT feeds the existing cell hash.
#   glintobj-cell  the CRAWL FALSIFIER, the object-space analogue of `100`'s
#                  `carglint-cell`: the feature PLUS a second, PRIMARY-ray
#                  query whose object-space cell is painted as one of eight
#                  flat hues at every radiance write.
#   glintobj-miss  the feature PLUS MAGENTA wherever the bounce query ran and
#                  committed nothing, so the world-space FALLBACK RATE can be
#                  read off a frame instead of assumed.
#
# EVERY GLINT KNOB IS THE BASE'S OWN: cell 8 mm, nu0 6e5 (dense), theta_bin
# 0.02, glint_max 16, k_glint 1, the (0.55, 0.70) metallic ramp, r < 0.35, the
# 30->40 m fade and the firefly clamp are the base's BYTES, never re-emitted.
# Gate 10's line-level diff is what proves that, and it is the gate that makes
# this a single-variable A/B.
#
# All 77 compute, all 4 rgs_restirgi_* and BOTH scalar-specular reference
# permutations ship BYTE-VERBATIM and are cmp-asserted.
#
# The rungs REQUIRE a layer that enables VK_KHR_ray_query on the VkDevice
# (swap_layer.c, handoff/98 sec 6/7) -- the base already needs it for `101`'s
# ear glow, so this adds no new layer requirement. Prove the driver FIRST,
# without the game:
#     ./dev/selftest_glintobj.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_glintobj.py"
VERIFY="$MOD_DIR/dev/verify_glintobj.py"
CGVERIFY="$MOD_DIR/dev/verify_carglint.py"
WORK="$MOD_DIR/dev/disasm/glintobj"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
NU0=600000          # the base's own dense knob; asserted, never re-emitted
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing default is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }
# and it must ALREADY carry `100`'s glints -- there is nothing to replace
# otherwise, and a silent build on the pre-glint base would be a STACK.
n_gl=$(ls "$SRC"/*.carglint.report.json 2>/dev/null | wc -l)
[[ "$n_gl" == 10 ]] || { echo "$BASE carries $n_gl carglint reports, expected 10 -- this base is not a glint rung, so there is no world-space feed to REPLACE" >&2; exit 1; }

mapfile -t TARGETS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#TARGETS[@]} == 12 )) || { echo "expected 12 reference raygens" >&2; exit 1; }

echo "=== 0. base: $BASE"
echo "    $(head -1 "$SRC/MANIFEST.txt" | cut -c1-100)"
echo "    content sha $(cat "$SRC"/*.spv | sha256sum | cut -c1-16), 10 carglint reports present"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the reference raygens ---------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  12 of 12 reference permutations round-trip byte-identically"
rm -rf "$WORK/rt"

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | GO_O="$out" GO_P="$PY" GO_W="$WORK" \
        GO_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$GO_A"
            python3 "$GO_P" "$GO_W/asm/$0.spvasm" "${A[@]}" --outdir "$GO_O" \
                > "$GO_O/$0.glintobj.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10 (12 minus the 2 scalar-specular)" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched dir, $3 = 1 if the CONTROL
    local dest="$1" src="$2" identical="${3:-0}"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$SRC"/*.json "$dest/" 2>/dev/null || true   # the base's own reports
    cp -pf "$src"/*.json "$dest/"
    [[ "$identical" == 1 ]] || cp -pf "$src"/*.spv "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    # the two scalar-specular permutations, and on the control ALL twelve,
    # come straight from the base and are cmp-asserted below
    for h in "${TARGETS[@]}"; do
        [[ -f "$dest/$h.rgs_reference_main.spv" ]] || \
            cp -pf "$SRC/$h.rgs_reference_main.spv" "$dest/"
    done
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    local nd=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" || nd=$((nd+1))
    done
    if (( identical )); then
        [[ "$nd" == 0 ]] || { echo "  !! the CONTROL differs from the base on $nd raygens" >&2; exit 1; }
    else
        [[ "$nd" == 10 ]] || { echo "  !! $dest differs from the base on $nd raygens, want exactly 10" >&2; exit 1; }
    fi
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the four rungs"
ORDER=(glintobj-ctl glintobj glintobj-cell glintobj-miss)
declare -A RUNG_MODE=(
    [glintobj-ctl]=ctl [glintobj]=glint
    [glintobj-cell]=cell [glintobj-miss]=miss)
declare -A RUNG_IDENT=([glintobj-ctl]=1)
for r in "${ORDER[@]}"; do
    patch_set "$WORK/p.$r" --mode "${RUNG_MODE[$r]}"
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_IDENT[$r]:-0}"
    echo "  swaps.$r: 93 modules, mode=${RUNG_MODE[$r]}, spirv-val (vulkan1.4) clean"
done
for pair in "glintobj glintobj-cell" "glintobj glintobj-miss" \
            "glintobj-cell glintobj-miss"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 patched permutations differ between every pair of live rungs"

# --- 3. coverage census, from the REPORTS (never from byte counts; 42) ------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of what the build script asked the patcher for.
WANT = {'glintobj-ctl': dict(ctl=True, queries=0, paint=False),
        'glintobj': dict(mode='glint', queries=1, paint=False),
        'glintobj-cell': dict(mode='cell', queries=2, paint=True),
        'glintobj-miss': dict(mode='miss', queries=1, paint=True)}
OK_SKIP = ('constant-zero', 'scalar-broadcast', 'texel not a v4float construct')
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = declined = painted = skipped = sel = q2 = 0
    members, cells, flags, brackets, emitted = set(), set(), set(), set(), set()
    for f in sorted(glob.glob(os.path.join(d, '*.glintobj.report.json'))):
        for rep in json.load(open(f)):
            g = rep['glintobj']
            if not g.get('written'):
                declined += 1
                if 'scalar-specular' not in (g.get('variant') or ''):
                    bad.append((r, rep['ident'], 'declined for the wrong reason'))
                continue
            mods += 1
            if rep.get('spirv_val') != 'clean':
                bad.append((r, rep['ident'], 'spirv-val not clean'))
            if g.get('decoy') is not None:
                bad.append((r, rep['ident'], 'a DECOY build reached a rung'))
            if g['mode'] != (want.get('mode') or 'ctl'):
                bad.append((r, rep['ident'], "mode %s" % g['mode']))
            emitted.add(g.get('emitted'))
            if want.get('ctl'):
                if g.get('emitted') != 0:
                    bad.append((r, rep['ident'], 'the control emitted instructions'))
                if g.get('selects') or g.get('query') or g.get('painted'):
                    bad.append((r, rep['ident'], 'the control spliced something'))
                continue
            members.add(g['member']); cells.add(round(g['cell'], 9))
            flags.add(g['ray_flags']); brackets.add(tuple(g['bracket']))
            if g['ray_flags_names'] != 'OpaqueKHR|TerminateOnFirstHitKHR|SkipAABBsKHR':
                bad.append((r, rep['ident'], 'flag names ' + g['ray_flags_names']))
            if len(g['selects']) != 3:
                bad.append((r, rep['ident'], '%d selects, want 3' % len(g['selects'])))
            sel += len(g['selects'])
            for a in g['selects']:
                if a['world'] == a['select'] or a['obj'] == a['select']:
                    bad.append((r, rep['ident'], 'an axis was not repointed'))
            if [a['world'] for a in g['selects']] != [a['world'] for a in g['axes']]:
                bad.append((r, rep['ident'], 'the select miss arms are not the world feeds'))
            if len(g['object']['columns']) != 4 or len(g['object']['scaled']) != 3:
                bad.append((r, rep['ident'], 'the matrix is not 4 columns / 3 scaled'))
            nq = 1 + (1 if (g.get('latch') or {}).get('query2') else 0)
            q2 += nq
            if nq != want['queries']:
                bad.append((r, rep['ident'], '%d queries, want %d' % (nq, want['queries'])))
            npaint = len(g.get('painted') or [])
            painted += npaint; skipped += len(g.get('skipped') or [])
            if want['paint'] and not npaint:
                bad.append((r, rep['ident'], 'the diagnostic paints nothing'))
            if not want['paint'] and npaint:
                bad.append((r, rep['ident'], 'the FEATURE rung paints'))
            for s in (g.get('skipped') or []):
                if s['why'] not in OK_SKIP:
                    bad.append((r, rep['ident'], 'unexpected skip: ' + s['why']))
    if mods != 10 or declined != 2:
        bad.append((r, '-', '%d patched / %d declined, want 10 / 2' % (mods, declined)))
    if want.get('ctl'):
        print('  %-15s 10 patched + 2 declined by name, 0 instructions emitted,'
              ' nothing spliced' % r)
        continue
    if members != {56}:
        bad.append((r, '-', 'world-offset members %s, want {56}' % sorted(members)))
    if len(cells) != 1 or abs(list(cells)[0] - 0.008) > 1e-6:
        bad.append((r, '-', 'cell sizes %s, want one == 0.008' % sorted(cells)))
    if flags != {517}:
        bad.append((r, '-', 'ray flags %s, want {517}' % sorted(flags)))
    if brackets != {(0.999, 1.001, 0.0001)}:
        bad.append((r, '-', 'brackets %s' % sorted(brackets)))
    print('  %-15s 10 patched + 2 declined by name, member %s, cell %s, flags %s,'
          ' bracket %s, %d queries, %d selects, %d painted writes, %d benign skips,'
          ' emitted %s' % (r, sorted(members), sorted(cells), sorted(flags),
                           sorted(brackets)[0], q2, sel, painted, skipped,
                           sorted(emitted)))
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes -----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
NQ = {'glintobj-ctl': 0, 'glintobj': 1, 'glintobj-cell': 2, 'glintobj-miss': 1}
GET = 'OpRayQueryGetIntersectionWorldToObjectKHR'
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True,
                          text=True).stdout
bad = []
for r in rungs:
    want = NQ[r]
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(i=0, p=0, t=0, w=0, mods=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        if a == b:
            continue                      # declined / control, counted below
        tot['mods'] += 1
        di = a.count('OpRayQueryInitializeKHR') - b.count('OpRayQueryInitializeKHR')
        dp = a.count('OpRayQueryProceedKHR') - b.count('OpRayQueryProceedKHR')
        dt = a.count('OpRayQueryGetIntersectionTypeKHR') - \
            b.count('OpRayQueryGetIntersectionTypeKHR')
        dw = a.count(GET) - b.count(GET)
        if (di, dp, dt, dw) != (want, want, want, want):
            bad.append(f'{r}/{h}: added init/proceed/type/W2O {(di,dp,dt,dw)}, '
                       f'want {want} each')
        if a.count('OpTraceRayKHR') != b.count('OpTraceRayKHR'):
            bad.append(f'{r}/{h}: the OpTraceRayKHR count changed')
        for op in ('OpLabel', 'OpBranch', 'OpSelectionMerge', 'OpLoopMerge'):
            if a.count(op) != b.count(op):
                bad.append(f'{r}/{h}: {op} count changed -- control flow moved')
        tot['i'] += di; tot['p'] += dp; tot['t'] += dt; tot['w'] += dw
    if r == 'glintobj-ctl':
        if tot['mods']:
            bad.append(f'{r}: {tot["mods"]} modules differ from the base')
        print(f'  {r:15s} 0 modules differ from the base (the identity control)')
        continue
    if tot['mods'] != 10:
        bad.append(f'{r}: {tot["mods"]} modules differ, want 10')
    print(f"  {r:15s} {tot['mods']} modules, +{tot['i']} Initialize, "
          f"+{tot['p']} Proceed, +{tot['t']} committed-type, "
          f"+{tot['w']} WorldToObject, 0 added traces, 0 added blocks")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. the control is the base, byte for byte ------------------------------
echo "=== 5. control identity + file census"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.glintobj-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! glintobj-ctl differs from the base on $d files" >&2; exit 1; }
echo "  glintobj-ctl: 93 of 93 byte-identical to $BASE"
for r in glintobj glintobj-cell glintobj-miss; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs from the base on $d files, want exactly 10" >&2; exit 1; }
done
echo "  glintobj / -cell / -miss: 10 of 93 differ (all 77 compute + 4 restirgi + the 2 scalar-specular verbatim)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_glintobj.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.glintobj"      --base "$SRC" --mode glint --nu0 "$NU0"
python3 "$VERIFY" "$MOD_DIR/swaps.glintobj-cell" --base "$SRC" --mode cell  --nu0 "$NU0"
python3 "$VERIFY" "$MOD_DIR/swaps.glintobj-miss" --base "$SRC" --mode miss  --nu0 "$NU0"

# --- 7. THE REPLACE PROOF, by an INDEPENDENT verifier ----------------------
# `100`'s own verify_carglint.py asserts at its axis 7 that each cell divide's
# numerator is `OpFAdd(cb56_k, P_k)`. That is precisely the wire this feature
# cuts, so the SAME verifier must ACCEPT the base and the control and REJECT
# every live rung -- an independent implementation saying "the world-space feed
# no longer reaches the hash". If it ever accepted a live rung, the world feed
# would still be connected and this whole build would be a stack.
echo "=== 7. replace-not-stack: 100's verify_carglint.py must FLIP on the feed"
python3 "$CGVERIFY" "$SRC" --nu0 "$NU0" >/dev/null \
    || { echo "  !! 100's verifier does not accept the BASE -- the base is wrong" >&2; exit 1; }
echo "  verify_carglint.py ACCEPTS the base (the world feed is intact there)"
python3 "$CGVERIFY" "$MOD_DIR/swaps.glintobj-ctl" --nu0 "$NU0" >/dev/null \
    || { echo "  !! 100's verifier does not accept glintobj-ctl" >&2; exit 1; }
echo "  verify_carglint.py ACCEPTS glintobj-ctl (byte-identical to the base)"
for r in glintobj glintobj-cell glintobj-miss; do
    if python3 "$CGVERIFY" "$MOD_DIR/swaps.$r" --nu0 "$NU0" >"$WORK/cg.$r.log" 2>&1; then
        echo "  !! 100's verifier ACCEPTED $r -- the WORLD feed still reaches the hash" >&2
        exit 1
    fi
    line=$(grep -m1 'world offset' "$WORK/cg.$r.log" || true)
    [[ -n "$line" ]] || { echo "  !! $r was rejected, but not at axis 7 (the feed). Rejection log:" >&2; head -3 "$WORK/cg.$r.log" >&2; exit 1; }
    echo "  verify_carglint.py REJECTS $r at its own axis 7:"
    echo "      $(echo "$line" | sed 's/^ *//' | cut -c1-96)"
done

# --- 8. verifier NON-VACUITY: it must REJECT every decoy -------------------
echo "=== 8. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
for dec in world primary nofallback noselect flags; do
    patch_set "$WORK/decoy/$dec" --mode glint --decoy "$dec"
    # decoy dirs hold only the 10 patched raygens; the verifier needs the base
    # for the other 83, so it is pointed at the decoy dir with --base $SRC and
    # the missing files are supplied from the base.
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$WORK/decoy/$dec/" 2>/dev/null || true
    for h in "${TARGETS[@]}"; do
        [[ -f "$WORK/decoy/$dec/$h.rgs_reference_main.spv" ]] || \
            cp -pf "$SRC/$h.rgs_reference_main.spv" "$WORK/decoy/$dec/"
    done
done
reject "--decoy world (the CAMERA OFFSET added before the inverse: counted twice)" \
       "$WORK/decoy/world" --base "$SRC" --mode glint --nu0 "$NU0"
reject "--decoy primary (the PRIMARY hit's matrix used at a BOUNCE vertex)" \
       "$WORK/decoy/primary" --base "$SRC" --mode glint --nu0 "$NU0"
reject "--decoy nofallback (a missed query hashes an undefined matrix)" \
       "$WORK/decoy/nofallback" --base "$SRC" --mode glint --nu0 "$NU0"
reject "--decoy noselect (the query runs and the WORLD feed still wins: a STACK)" \
       "$WORK/decoy/noselect" --base "$SRC" --mode glint --nu0 "$NU0"
reject "--decoy flags (ray flags 0: a Proceed loop this splice cannot service)" \
       "$WORK/decoy/flags" --base "$SRC" --mode glint --nu0 "$NU0"
reject "the unpatched BASE read as a rung" \
       "$SRC" --base "$SRC" --mode glint --nu0 "$NU0"
reject "the byte-identical CONTROL read as a rung" \
       "$MOD_DIR/swaps.glintobj-ctl" --base "$SRC" --mode glint --nu0 "$NU0"
reject "glintobj read as the -cell diagnostic (2 queries, a paint)" \
       "$MOD_DIR/swaps.glintobj" --base "$SRC" --mode cell --nu0 "$NU0"
reject "glintobj-cell read as the feature (1 query, no paint)" \
       "$MOD_DIR/swaps.glintobj-cell" --base "$SRC" --mode glint --nu0 "$NU0"
reject "glintobj-miss read as -cell" \
       "$MOD_DIR/swaps.glintobj-miss" --base "$SRC" --mode cell --nu0 "$NU0"
reject "glintobj read at the DEFAULT nu0 (the dense knob must be the base's)" \
       "$MOD_DIR/swaps.glintobj" --base "$SRC" --mode glint
# Parked rungs that are REAL ray queries in this raygen family, and the WRONG
# question. Free decoys, and the strongest available.
for other in earglow-cap6 hunt-rayq-pxfw contact-rq; do
    if [[ -d "$INSTALL_DIR/skin.set/$other" ]]; then
        reject "$other (a ray query in this raygen, but not this feed)" \
               "$INSTALL_DIR/skin.set/$other" --base "$SRC" --mode glint --nu0 "$NU0"
    fi
done
python3 "$VERIFY" --negative "$SRC" --base "$SRC" --mode glint --nu0 "$NU0" \
    || { echo "  !! --negative did not reject the base" >&2; exit 1; }
rm -rf "$WORK/decoy"

# --- 9. MANIFEST provenance -------------------------------------------------
echo "=== 9. MANIFEST provenance"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    sed -e "1s/^$BASE /$r /" "$SRC/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
      echo "# glintobj (handoff/106): OBJECT-SPACE car-paint glints. The cell"
      echo "# hash of 100's glints is fed from WorldToObject * (P, 1) -- a ray"
      echo "# query down the module's OWN traced segment, flags 517, bracket"
      echo "# [0.999t, 1.001t + 1e-4] on payload word 3 -- instead of from"
      echo "# P + cbv[..][56].xyz. On a MOVING car the flakes ride with the"
      echo "# paint; on a parked one this is visually equivalent."
      echo "# 100's WORLD feed is DISCONNECTED: it survives only as the miss arm"
      echo "# of the select, with exactly one use each, and 100's own"
      echo "# verify_carglint.py rejects these bytes at its axis 7."
      echo "# EVERY glint knob is the base's own bytes (cell 8mm, nu0 6e5,"
      echo "# glint_max 16, firefly clamp): one variable."
      case "$r" in
        *-ctl)  echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE. Control for the selector." ;;
        *-cell) echo "# FALSIFIER: 8 flat hues per OBJECT-SPACE cell of the PRIMARY hit." ;;
        *-miss) echo "# INSTRUMENT: MAGENTA where the query committed nothing (fallback rate)." ;;
        *)      echo "# THE FEATURE." ;;
      esac
      echo "# NOT working until the screen says so. A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  4 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {  # the repo path contains a space: -print0 / sort -z / xargs -0
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-15s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-15s content=%s  raygen-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        # NEW NAMES ONLY. Never delete or rewrite a parked dir this script did
        # not create (GOTCHAS: "--sets rm -rf'd skin.set/ and took the probe
        # rungs with it").
        if [[ -d "$park" && ! -f "$park/.glintobj" ]]; then
            echo "  !! $park exists and was not parked by this script -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; : > "$park/.glintobj"
        rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json \
               "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=$(ls "$park"/*.spv | wc -l)
        [[ "$n" == 93 ]] || { echo "  !! parked $r has $n modules" >&2; exit 1; }
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" \
                || { echo "  !! parked $r differs from the build: $(basename "$f")" >&2; exit 1; }
        done
        echo "  parked -> $park (93 modules, cmp-verbatim against the build)"
    done
fi
echo
echo "select with skinspec=glintobj-ctl / glintobj / glintobj-cell / glintobj-miss"
echo "contract: ser=class, shadowset=full-shadow REQUIRED; ptq unchanged; RR OFF;"
echo "          photo mode, a MOVING car AND a parked one in the same frame,"
echo "          and carglint-cell shot as the world-space comparison."
echo "          Read handoff/106 sec 9 BEFORE the screen, and shoot -cell FIRST."
