#!/usr/bin/env bash
# concavity -- 102's traced hemispherical occlusion, generalised OFF skin, as
# two rung families. handoff/104-TRACED-CONCAVITY.md is the document; read its
# section 7 (the pre-registered interpretation table) BEFORE looking at a frame.
#
#   ./dev/build_concavity.sh              # build + 10 gates (nothing installed)
#   ./dev/build_concavity.sh --install    # ALSO park the six rungs
#   ./dev/build_concavity.sh --base NAME  # build on a different parked rung
#   ./dev/build_concavity.sh --family fold|crevice   # build one family only
#
# SIX RUNGS, one variable each, all on the STANDING selection's own bytes
# (gi-50b-...-earglow-cap6-glintdense, NOT 102's older -fog base: a rung built
# on -fog would read as an ear-glow AND a glint regression the moment it is
# A/B'd against the default).
#
#   foldrq-ctl    k=0. The patcher emits NOTHING and rewrites nothing, so the
#                 output is BYTE-IDENTICAL to the base (gate 5, resting on gate
#                 1's round-trip neutrality). Control for the SELECTOR and the
#                 LAYER, not for the splice.
#   foldrq-hit    THE INSTRUMENT. o painted flat as a grey ramp over the
#                 radiance writes on gated cloth: white = clear, black = fully
#                 occluded. Readable INDEPENDENTLY of the darkening.
#   foldrq        K = 4, tmax 10 cm, achromatic, weighted by 81's own
#                 saturate((alpha - 0.10) * 5) roughness ramp. THE FEATURE.
#   crevice-ctl   k=0. Byte-identical to the base, as above.
#   crevice-hit   THE INSTRUMENT for the crevice gate.
#   crevice       K = 4, tmax 5 cm, TINTED: fac_c = 1 - K_c * o with
#                 K_c = 1 - tint_c*(1 - 0.85), tint = (0.55, 0.45, 0.35), so a
#                 concave pixel reads darker AND warmer.
#
# GATES (both families share everything but these two clauses):
#   fold      class != 1 and class != 4 and max3(F0) < 0.09     (80/81)
#   crevice   class != 1 and class != 4 and rough > 0.60 and metallic < 0.10
#
# THE RAY: from the cone tap's own origin lifted 0.1 mm along N, K fixed
# cosine-weighted directions in the hemisphere about N (basis built in-module
# from N, whole set rotated by a gl_LaunchID-seeded angle -- frame-stable),
# flags 517 = Opaque | TerminateOnFirstHit | SkipAABBs, NO face culling,
# tmin 1 mm. o = hits/K.
#
# THIS IS THE OPPOSITE OF 102. 102 REPLACED 88's analytic cavity cone, because
# 102's term covered the cone's own pixels (class-1 skin). Both families here
# are gated class != 1, i.e. DISJOINT from the cone, so the cone stays LIVE:
# its occ still feeds its own OpFMul, all six of its flags-16 taps keep a live
# cull mask, and OpTraceRayKHR is unchanged. Gate 7 proves the verifier
# REJECTS a build that kills it (--decoy kill).
#
# All 77 compute and all 4 rgs_restirgi_* ship BYTE-VERBATIM and are
# cmp-asserted. All TWELVE reference permutations are patched.
#
# The rungs REQUIRE a layer that enables VK_KHR_ray_query on the VkDevice
# (swap_layer.c, handoff/98 sec 6/7). Prove the layer and the driver FIRST,
# without the game:
#     ./dev/selftest_concavity.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_concavity.py"
VERIFY="$MOD_DIR/dev/verify_concavity.py"
WORK="$MOD_DIR/dev/disasm/concavity"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
DO_INSTALL=0
ONLY=""
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        --family) ONLY="${2:?--family needs fold or crevice}"; shift ;;
        -h|--help) sed -n '2,54p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
case "$ONLY" in ''|fold|crevice) ;; *) echo "--family must be fold or crevice" >&2; exit 1 ;; esac

SRC="$INSTALL_DIR/skin.set/$BASE"

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }

mapfile -t TARGETS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#TARGETS[@]} == 12 )) || { echo "expected 12 reference raygens" >&2; exit 1; }

echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the reference raygens ---------------
# Everything the two -ctl rungs claim rests on this: at k=0 the patcher emits
# no instructions, rewrites no operand, and writes the disassembly straight
# back.
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
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.concavity.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 12 ]] || { echo "  !! $out produced $n modules, want 12" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir, $3 = 1 if the 12 must be
                #      byte-identical to the base (the k=0 control)
    local dest="$1" src="$2" identical="${3:-0}"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for h in "${TARGETS[@]}"; do
        if (( identical )); then
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                || { echo "  !! CONTROL $h is NOT byte-identical to the base" >&2; exit 1; }
        else
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                && { echo "  !! $h is byte-identical to the base -- the splice emitted nothing" >&2; exit 1; }
        fi
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the rungs"
ORDER_FOLD=(foldrq-ctl foldrq-hit foldrq)
ORDER_CREV=(crevice-ctl crevice-hit crevice)
ORDER=()
[[ "$ONLY" == crevice ]] || ORDER+=("${ORDER_FOLD[@]}")
[[ "$ONLY" == fold    ]] || ORDER+=("${ORDER_CREV[@]}")
declare -A RUNG_ARGS=(
    [foldrq-ctl]="--family fold --k 0 --rays 4"
    [foldrq-hit]="--family fold --k 1 --rays 4 --mode hit"
    [foldrq]="--family fold --k 1 --rays 4"
    [crevice-ctl]="--family crevice --k 0 --rays 4"
    [crevice-hit]="--family crevice --k 1 --rays 4 --mode hit"
    [crevice]="--family crevice --k 1 --rays 4"
)
declare -A RUNG_IDENT=([foldrq-ctl]=1 [crevice-ctl]=1)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_IDENT[$r]:-0}"
    echo "  swaps.$r: 93 modules, $( (( ${RUNG_IDENT[$r]:-0} )) && echo '12 identity' || echo '12 patched'), spirv-val (vulkan1.4) clean"
done
PAIRS=()
[[ "$ONLY" == crevice ]] || PAIRS+=("foldrq-hit foldrq")
[[ "$ONLY" == fold    ]] || PAIRS+=("crevice-hit crevice")
[[ -n "$ONLY" ]] || PAIRS+=("foldrq crevice" "foldrq-hit crevice-hit")
for pair in "${PAIRS[@]}"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 12 ]] || { echo "  !! only $d of 12 differ between $1 and $2" >&2; exit 1; }
    echo "  12 of 12 differ: $1 vs $2"
done
# The two controls are the SAME BYTES (both are the base). Asserted, not
# assumed: if a family ever leaked something into its k=0 path this catches it
# even though gate 5 would too.
if [[ -z "$ONLY" ]]; then
    d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.foldrq-ctl/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.crevice-ctl/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 0 ]] || { echo "  !! the two controls differ on $d modules" >&2; exit 1; }
    echo "  0 of 12 differ: foldrq-ctl vs crevice-ctl (both ARE the base)"
fi

# --- 3. coverage census, from the REPORTS (never from byte counts; 42) ------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of what the build script asked the patcher for:
# a rung that silently changed its family, its bracket or its tint must fail
# this gate even if the request above changed with it.
TINT = [0.55, 0.45, 0.35]
KC = [round(1.0 - t * (1.0 - 0.85), 6) for t in TINT]
WANT = {
    'foldrq-ctl':  dict(ctl=True, family='fold'),
    'foldrq-hit':  dict(family='fold', mode='hit', rays=4, flags=517,
                        tmin=0.001, tmax=0.10, chan=1, tint=None),
    'foldrq':      dict(family='fold', mode='dark', rays=4, flags=517,
                        tmin=0.001, tmax=0.10, chan=1, tint=None),
    'crevice-ctl': dict(ctl=True, family='crevice'),
    'crevice-hit': dict(family='crevice', mode='hit', rays=4, flags=517,
                        tmin=0.001, tmax=0.05, chan=3, tint=TINT),
    'crevice':     dict(family='crevice', mode='dark', rays=4, flags=517,
                        tmin=0.001, tmax=0.05, chan=3, tint=TINT),
}
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = painted = skipped = scaled = 0
    legacy_wrong, base_sample = [], []
    splice, apply_n = set(), set()
    for f in sorted(glob.glob(os.path.join(d, '*.concavity.report.json'))):
        rep = json.load(open(f))
        q = rep['concavity']
        mods += 1
        h = rep['ident'].split('.')[0]
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['family'] != want['family']:
            bad.append((r, rep['module'], f"family {q['family']}"))
        if q['legacy_helper_was_wrong']:
            legacy_wrong.append(h)
        if q['base_cone_gate_was_sample']:
            base_sample.append(h)
        if want.get('ctl'):
            if q.get('emitted') != 0:
                bad.append((r, rep['module'], 'the control emitted instructions'))
            continue
        for key in ('mode', 'rays', 'tmin', 'tmax'):
            if q[key] != want[key]:
                bad.append((r, rep['module'], f'{key} {q[key]} != {want[key]}'))
        if q['ray_flags'] != want['flags']:
            bad.append((r, rep['module'], f"flags {q['ray_flags']} != {want['flags']}"))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if q['gate_mask'] != 39:
            bad.append((r, rep['module'], f"gate cull mask {q['gate_mask']} != 39"))
        # THE CONE MUST STILL BE ALIVE -- this is the inversion of 102.
        if q['cone_replaced'] != 0 or q['cone_taps_neutered'] != 0:
            bad.append((r, rep['module'], 'the analytic cone was killed; the '
                                          'gates here are DISJOINT from it'))
        if q['cones_scaled'] != 3:
            bad.append((r, rep['module'], f"{q['cones_scaled']} cones scaled, want 3"))
        if q['channel_factors'] != want['chan']:
            bad.append((r, rep['module'],
                        f"{q['channel_factors']} channel factors, want {want['chan']}"))
        if q['tint'] != (list(want['tint']) if want['tint'] else None):
            bad.append((r, rep['module'], f"tint {q['tint']} != {want['tint']}"))
        kc = [round(x, 6) for x in q['channel_k']]
        exp = KC if want['tint'] else [0.85, 0.85, 0.85]
        if any(abs(a - b) > 1e-6 for a, b in zip(kc, exp)):
            bad.append((r, rep['module'], f"channel_k {kc} != {exp}"))
        if q['cone_k'] is None:
            bad.append((r, rep['module'], "the cone's own k was not read"))
        # the tap set: unit, upper hemisphere, and exactly `rays` of them
        for (cx, cy, cz) in q['tap_dirs']:
            if abs(cx*cx + cy*cy + cz*cz - 1.0) > 1e-9:
                bad.append((r, rep['module'], 'a tap direction is not unit'))
            if cz <= 0.0:
                bad.append((r, rep['module'], 'a tap direction leaves the hemisphere'))
        if len(q['tap_dirs']) != want['rays']:
            bad.append((r, rep['module'], 'tap count mismatch'))
        splice.add(q['splice_instructions']); apply_n.add(q['apply_instructions'])
        scaled += q['cones_scaled']
        painted += len(q['writes_painted']); skipped += len(q['writes_skipped'])
        for s in q['writes_skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
    if mods != 12:
        bad.append((r, '-', f'{mods} patched modules, want 12'))
    if want.get('ctl'):
        print(f'  {r:13s} 12 modules, 0 instructions emitted (the identity control)')
    else:
        print(f'  {r:13s} 12 modules, {scaled} cone applications scaled, '
              f'0 cones killed, 0 taps neutered, {painted} painted writes, '
              f'{skipped} benign skips, K={want["rays"]}, flags={want["flags"]}, '
              f'tmin={want["tmin"]}, tmax={want["tmax"]}, '
              f'channels={want["chan"]}, splice={sorted(splice)} insns, '
              f'apply={sorted(apply_n)} insns')
    # 90 sec 1, recorded rather than hidden: the STANDING BASE's own cone gate
    # tested the SAMPLE counter on these permutations.
    print(f'                base cone gated on the SAMPLE counter on '
          f'{len(base_sample)}/12: {sorted(base_sample)}')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes -----------------------------
# The base ALREADY carries ray queries (101's earglow-rq3, three of them on 10
# of 12 permutations), so every count here is BASE + K. Nothing absolute.
echo "=== 4. instruction census on the SHIPPED bytes (all counts are base + K)"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
RAYS = {'foldrq-hit': 4, 'foldrq': 4, 'crevice-hit': 4, 'crevice': 4}
def dis(p):
    return subprocess.run(['spirv-dis', '--no-color', p],
                          capture_output=True, text=True).stdout
bad = []
for r in rungs:
    ctl = r.endswith('-ctl')
    want = 0 if ctl else RAYS[r]
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(init=0, proceed=0, tget=0, base_init=0, live_taps=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n = [a.count(x) - b.count(x) for x in
             ('OpRayQueryInitializeKHR', 'OpRayQueryProceedKHR',
              'OpRayQueryGetIntersectionTypeKHR')]
        if n != [want] * 3:
            bad.append(f'{r}/{h}: ADDED init/proceed/type {n}, want {want}')
        dt = a.count('OpRayQueryGetIntersectionTKHR') - \
             b.count('OpRayQueryGetIntersectionTKHR')
        if dt:
            bad.append(f'{r}/{h}: the committed-T getter count moved by {dt} '
                       f'-- this asks a BOOLEAN, and 101 must be untouched')
        dtr = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        if dtr != 0:
            bad.append(f'{r}/{h}: OpTraceRayKHR count changed by {dtr}')
        # 88's six flags-16 cone taps must stay LIVE on EVERY rung here
        live = len(re.findall(r'OpTraceRayKHR %\w+ %uint_16 (?!%uint_0\b)', a))
        n16 = len(re.findall(r'OpTraceRayKHR %\w+ %uint_16 ', a))
        if n16 != 6:
            bad.append(f'{r}/{h}: {n16} flags-16 cone taps, want 6')
        if live != 6:
            bad.append(f'{r}/{h}: only {live} of 6 cone taps still carry a '
                       f'live cull mask -- the analytic cone MUST stay alive')
        tot['init'] += a.count('OpRayQueryInitializeKHR')
        tot['base_init'] += b.count('OpRayQueryInitializeKHR')
        tot['proceed'] += a.count('OpRayQueryProceedKHR')
        tot['tget'] += a.count('OpRayQueryGetIntersectionTypeKHR')
        tot['live_taps'] += live
    print(f"  {r:13s} {tot['init']} Initialize ({tot['base_init']} base + "
          f"{tot['init']-tot['base_init']} ours), {tot['proceed']} Proceed, "
          f"{tot['tget']} committed-type getters, 0 added committed-T getters, "
          f"0 added traces, {tot['live_taps']} live cone taps")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. k=0 identity, over the WHOLE set ------------------------------------
echo "=== 5. k=0 identity controls"
for r in "${ORDER[@]}"; do
    [[ "$r" == *-ctl ]] || continue
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 0 ]] || { echo "  !! $r differs from the base on $d files" >&2; exit 1; }
    echo "  $r: 93 of 93 byte-identical to $BASE"
done
for r in "${ORDER[@]}"; do
    [[ "$r" == *-ctl ]] && continue
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 12 ]] || { echo "  !! $r differs from the base on $d files, want exactly 12" >&2; exit 1; }
    echo "  $r: 12 of 93 differ (all 12 reference permutations; 77 compute + 4 restirgi verbatim)"
done

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_concavity.py on the shipped .spv"
for r in "${ORDER[@]}"; do
    [[ "$r" == *-ctl ]] && continue
    fam=fold; [[ "$r" == crevice* ]] && fam=crevice
    mode=dark; [[ "$r" == *-hit ]] && mode=hit
    python3 "$VERIFY" "$MOD_DIR/swaps.$r" --base "$SRC" --family "$fam" \
            --mode "$mode" --rays 4
done
[[ "$ONLY" == crevice ]] || python3 "$VERIFY" --negative "$SRC" --family fold
[[ "$ONLY" == fold    ]] || python3 "$VERIFY" --negative "$SRC" --family crevice

# --- 7. verifier NON-VACUITY: it must REJECT every decoy -------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
DECOYS=(flags tmax counter basis class kill)
[[ "$ONLY" == fold ]] || DECOYS+=(notint)
DFAM=fold; [[ "$ONLY" == crevice ]] && DFAM=crevice
for dec in "${DECOYS[@]}"; do
    fam="$DFAM"; [[ "$dec" == notint ]] && fam=crevice
    patch_set "$WORK/decoy/$dec" --family "$fam" --k 1 --rays 4 --decoy "$dec"
done
V=(--base "$SRC" --family "$DFAM" --mode dark --rays 4)
reject "--decoy flags (545 = CullFrontFacing, 101's THICKNESS word)" \
       "$WORK/decoy/flags" "${V[@]}"
reject "--decoy tmax (101's 0.018 m T_SEG -- an ear, not a fold)" \
       "$WORK/decoy/tmax" "${V[@]}"
reject "--decoy counter (79/85's legacy find_bounce_counter; 90 sec 1)" \
       "$WORK/decoy/counter" "${V[@]}"
reject "--decoy basis (a fixed WORLD frame instead of one built from N)" \
       "$WORK/decoy/basis" "${V[@]}"
reject "--decoy class (the class != 4 hair clause dropped)" \
       "$WORK/decoy/class" "${V[@]}"
reject "--decoy kill (102's REPLACE: the analytic cone deleted under a gate \
that is DISJOINT from it -- this would silently drop the shipped skin cavity term)" \
       "$WORK/decoy/kill" "${V[@]}"
if [[ "$ONLY" != fold ]]; then
    reject "--decoy notint (crevice built achromatic -- the dirt tint gone)" \
           "$WORK/decoy/notint" --base "$SRC" --family crevice --mode dark --rays 4
fi
reject "the unpatched BASE read as a rung" "$SRC" "${V[@]}"
for r in "${ORDER[@]}"; do
    [[ "$r" == *-ctl ]] || continue
    reject "the k=0 CONTROL $r read as a rung" "$MOD_DIR/swaps.$r" "${V[@]}"
done
if [[ "$ONLY" != crevice ]]; then
    reject "foldrq read as the -hit instrument" \
           "$MOD_DIR/swaps.foldrq" --base "$SRC" --family fold --mode hit --rays 4
    reject "foldrq-hit read as the darkening rung" \
           "$MOD_DIR/swaps.foldrq-hit" --base "$SRC" --family fold --mode dark --rays 4
    reject "foldrq read against 101's flag word (545)" \
           "$MOD_DIR/swaps.foldrq" --base "$SRC" --family fold --mode dark --rays 4 --flags 545
    reject "foldrq read as K=8" \
           "$MOD_DIR/swaps.foldrq" --base "$SRC" --family fold --mode dark --rays 8
fi
if [[ "$ONLY" != fold ]]; then
    reject "crevice read as the -hit instrument" \
           "$MOD_DIR/swaps.crevice" --base "$SRC" --family crevice --mode hit --rays 4
    reject "crevice-hit read as the darkening rung" \
           "$MOD_DIR/swaps.crevice-hit" --base "$SRC" --family crevice --mode dark --rays 4
fi
# CROSS-FAMILY: the two gates and the two brackets must not be interchangeable.
if [[ -z "$ONLY" ]]; then
    reject "foldrq read as the crevice family (different gate, different reach)" \
           "$MOD_DIR/swaps.foldrq" --base "$SRC" --family crevice --mode dark --rays 4
    reject "crevice read as the fold family (tint and ramp are not optional)" \
           "$MOD_DIR/swaps.crevice" --base "$SRC" --family fold --mode dark --rays 4
fi
# Parked rungs that are REAL ray queries in this exact module family, and the
# WRONG one. Free decoys, and the strongest ones available. 102's own rungs
# are the sharpest: same estimator, same site, WRONG gate and a DEAD cone.
for other in contact-rq contact-rq-8 contact-rq-hit earglow-rq3 hunt-rayq-p; do
    if [[ -d "$INSTALL_DIR/skin.set/$other" ]]; then
        reject "$other (a ray query in this raygen, but the wrong question)" \
               "$INSTALL_DIR/skin.set/$other" "${V[@]}"
    fi
done
rm -rf "$WORK/decoy"

# --- 7b. the SHIPPED base features must survive ----------------------------
# A rung that quietly regressed the ear glow, the glints or the fog would still
# pass every gate above, and the A/B against the standing default would then be
# reading two variables. 102's rungs are on the older -fog base and CANNOT be
# A/B'd against the default at all; these can, and this gate is what buys that.
#
# 7b.1 STRUCTURAL CONTAINMENT. Disassembled with --raw-id and with every id
#      normalised away, the base's instruction stream must be an exact
#      SUBSEQUENCE of the rung's: zero deletions, zero replacements, only
#      insertions. One assertion covering the ear glow, the glints, the fog,
#      88's cones and everything else in the module at once -- no base
#      instruction was removed, reordered or reshaped. (Our operand repointing
#      is invisible to it BY DESIGN: an id is an id. What repoints to what is
#      verify_concavity.py section 10's job, and that checks the resolved
#      channel strengths and the R/G/B order, which no diff can.)
# 7b.2 The three EARGLOW queries the base already carries (101's rq3) keep
#      their exact ray words: every base (flags, tmin, tmax) triple survives,
#      and the getters the glow reads (committed T, InstanceId, FrontFace,
#      InstanceCustomIndex) keep their counts.
# 7b.3 100's own verify_carglint.py must still ACCEPT every rung.
# 7b.4 101's verify_earglow_rq3.py hard-asserts "exactly 3 ray query
#      variables" -- a clause written before anything else in this repo added
#      a query, and the one thing our 4th variable is guaranteed to trip. It
#      is RECORDED here, not edited (it is not our file): the gate asserts it
#      passes on the base, and that on every rung every failure line is that
#      one clause and nothing else.
echo "=== 7b. base-feature regression (containment, earglow-rq3, glintdense)"
EGBASE="$INSTALL_DIR/skin.set/gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PZ' || exit 1
import difflib, glob, os, re, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
ID = re.compile(r'%\d+')
GET = ('OpRayQueryGetIntersectionTKHR',
       'OpRayQueryGetIntersectionInstanceIdKHR',
       'OpRayQueryGetIntersectionFrontFaceKHR',
       'OpRayQueryGetIntersectionInstanceCustomIndexKHR')
bad = []


def dis(p, raw=False):
    cmd = ['spirv-dis', '--no-color'] + (['--raw-id'] if raw else [])
    return subprocess.run(cmd + [p], capture_output=True, text=True).stdout


def stream(p):
    return [ID.sub('%N', l).strip() for l in dis(p, raw=True).split('\n')
            if l.strip() and not l.lstrip().startswith(';')]


def words(asm):
    """(flags, tmin, tmax) per OpRayQueryInitializeKHR, resolved to constant
    VALUES where they are constants and to 'dyn' where they are not."""
    d = {}
    for l in asm.split('\n'):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d.setdefault(m.group(1), m.group(2))
    def cv(t):
        m = re.match(r'OpConstant %(?:float|uint) (\S+)$', d.get(t, ''))
        if m:
            return m.group(1)
        m = re.match(r'%uint_(\d+)$', t)
        return m.group(1) if m else 'dyn'
    out = []
    for l in asm.split('\n'):
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        if m:
            o = m.group(1).split()
            out.append((cv(o[2]), cv(o[5]), cv(o[7])))
    return sorted(out)


for r in rungs:
    ins = 0
    for f in sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r,
                                           '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        bp = os.path.join(src, os.path.basename(f))
        A, Bl = stream(bp), stream(f)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, A, Bl, autojunk=False).get_opcodes():
            if tag == 'insert':
                ins += j2 - j1
            elif tag == 'delete':
                bad.append(f'{r}/{h}: {i2-i1} BASE instructions DELETED at '
                           f'{i1} -- e.g. {A[i1]!r}')
            elif tag == 'replace':
                bad.append(f'{r}/{h}: {i2-i1} BASE instructions RESHAPED at '
                           f'{i1} -- e.g. {A[i1]!r} -> {Bl[j1]!r}')
        aa, ab = dis(bp), dis(f)
        rem = words(aa)
        for w in words(ab):
            if w in rem:
                rem.remove(w)
        if rem:
            bad.append(f'{r}/{h}: base ray words {rem} did not survive')
        for g in GET:
            if ab.count(g) != aa.count(g):
                bad.append(f'{r}/{h}: {g} {ab.count(g)} vs base {aa.count(g)}')
    print(f'  {r:13s} base stream contained VERBATIM: 0 deleted, 0 reshaped, '
          f'{ins} inserted over 12 modules; every base ray word survives; '
          f'earglow getters unchanged')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PZ
for r in "${ORDER[@]}"; do
    python3 "$MOD_DIR/dev/verify_carglint.py" "$MOD_DIR/swaps.$r" --nu0 600000
done
echo "  --- 101's verify_earglow_rq3.py, recorded (not edited: not our file) ---"
python3 "$MOD_DIR/dev/verify_earglow_rq3.py" "$SRC" --base "$EGBASE" \
        --mode glow --floor --wide 4.0 --wrap 0.35 | sed 's/^/  base: /'
for r in "${ORDER[@]}"; do
    out=$(python3 "$MOD_DIR/dev/verify_earglow_rq3.py" "$MOD_DIR/swaps.$r" \
            --base "$EGBASE" --mode glow --floor --wide 4.0 --wrap 0.35 2>&1 || true)
    nf=$(printf '%s\n' "$out" | grep -c 'FAIL' || true)
    na=$(printf '%s\n' "$out" | grep -c '4 ray query variables, want exactly 3' || true)
    [[ "$nf" == "$na" ]] || {
        printf '%s\n' "$out" | grep FAIL | grep -v '4 ray query variables' >&2
        echo "  !! $r regressed the ear glow beyond the arity clause" >&2; exit 1; }
    if [[ "$r" == *-ctl ]]; then
        [[ "$nf" == 0 ]] || { echo "  !! the CONTROL $r failed the earglow verifier" >&2; exit 1; }
        echo "  $r: ALL PASS (it IS the base, byte for byte)"
    else
        echo "  $r: $nf failures, all $na of them 101's own 'exactly 3 ray query variables' clause"
    fi
done

# --- 8. the estimator, closed form, against the SHIPPED direction constants --
echo "=== 8. closed-form estimator check (numpy) against the shipped tap set"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir, rungs = sys.argv[1], sys.argv[2:]
TMIN = 0.001
TMAX = {'foldrq': 0.10, 'crevice': 0.05}
bad = []


def taps_from_spv(path, tmax):
    """Read the K (cx, cy, cz) tap coefficients back OUT of the shipped
    module, by walking OUR queries' direction operands. The base's own three
    earglow queries are excluded by tmax -- absolute counts are meaningless
    here (gate 4)."""
    asm = subprocess.run(['spirv-dis', '--no-color', path],
                         capture_output=True, text=True).stdout.split('\n')
    d = {}
    for l in asm:
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d.setdefault(m.group(1), m.group(2))
    def fv(t):
        m = re.match(r'OpConstant %float (\S+)$', d.get(t, ''))
        return float(m.group(1)) if m else None
    out = []
    for l in asm:
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        if not m:
            continue
        o = m.group(1).split()
        t = fv(o[7])
        if t is None or abs(t - tmax) > 1e-9:
            continue
        a1 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', d.get(o[6], ''))
        a2 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', d.get(a1.group(1), ''))
        c = []
        for t2 in (a2.group(1), a2.group(2), a1.group(2)):
            v = re.match(r'OpVectorTimesScalar %v3float %\w+ (%\w+)$', d.get(t2, ''))
            c.append(fv(v.group(1)))
        out.append(tuple(c))
    return out


def occ_discrete(T, dw, tmax, npsi=2048):
    """o for a synthetic half-space: an infinite wall standing perpendicular
    to the tangent plane at horizontal distance dw. The per-pixel rotation is
    uniform in psi, so the expectation over pixels is the mean over psi."""
    T = np.asarray(T)
    psi = np.linspace(0.0, 2.0 * np.pi, npsi, endpoint=False)
    md = np.outer(np.cos(psi), T[:, 0]) - np.outer(np.sin(psi), T[:, 1])
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(md > 0, dw / md, np.inf)
    return float(np.mean((t > TMIN) & (t < tmax)))


def occ_analytic(dw, tmax, n=262144):
    """The same wall against a CONTINUOUS cosine-weighted hemisphere -- what
    the K-tap estimator is estimating."""
    rng = np.random.default_rng(7)
    u1, u2 = rng.random(n), rng.random(n)
    r, ph = np.sqrt(u1), 2 * np.pi * u2
    x = r * np.cos(ph)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(x > 0, dw / x, np.inf)
    return float(np.mean((t > TMIN) & (t < tmax)))


for rung in rungs:
    if rung.endswith('-ctl') or rung.endswith('-hit'):
        continue
    tmax = TMAX[rung]
    fs = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + rung,
                                       '*.rgs_reference_main.spv')))
    sets = {tuple(sorted(taps_from_spv(f, tmax))) for f in fs}
    if len(sets) != 1:
        bad.append(f'{rung}: the 12 modules do not share one tap set')
        continue
    T = list(sets.pop())
    if len(T) != 4:
        bad.append(f'{rung}: {len(T)} taps read back from the .spv at '
                   f'tmax {tmax}, want 4')
        continue
    for (cx, cy, cz) in T:
        if abs(cx * cx + cy * cy + cz * cz - 1.0) > 2e-6:
            bad.append(f'{rung}: a shipped tap is not unit')
        if cz <= 0:
            bad.append(f'{rung}: a shipped tap leaves the hemisphere')
    cm = tmax * 100.0
    print(f'  {rung} (K=4, tmax {cm:.0f} cm, tap coefficients read back from '
          f'the .spv):')
    print('     wall d(cm)   o(K taps)   o(cosine-weighted, continuous)')
    prev = None
    for dcm in (0.1 * cm, 0.5 * cm, 0.9 * cm, 1.1 * cm):
        od = occ_discrete(T, dcm * 1e-2, tmax)
        oa = occ_analytic(dcm * 1e-2, tmax)
        print(f'   {dcm:9.1f}   {od:9.4f}   {oa:9.4f}')
        if abs(dcm - 0.1 * cm) < 1e-9 and not (0.35 <= od <= 0.55):
            bad.append(f'{rung}: a wall at {dcm:.1f} cm reads o={od:.3f}; a '
                       f'half-space well inside tmax should occlude about '
                       f'half the hemisphere')
        if abs(dcm - 1.1 * cm) < 1e-9 and od != 0.0:
            bad.append(f'{rung}: a wall at {dcm:.1f} cm reads o={od:.3f}, but '
                       f'tmax is {cm:.0f} cm -- the reach is wrong')
        if prev is not None and od > prev + 1e-9:
            bad.append(f'{rung}: o is not monotone decreasing in distance')
        prev = od
    err = max(abs(occ_discrete(T, d * 1e-2, tmax) - occ_analytic(d * 1e-2, tmax))
              for d in (0.1 * cm, 0.5 * cm, 0.9 * cm))
    print(f'   max |K-tap - continuous| over d in [{0.1*cm:.1f}, {0.9*cm:.1f}] '
          f'cm: {err:.4f}')
    if err > 0.20:
        bad.append(f'{rung}: the K=4 estimator is biased by {err:.3f} against '
                   f'the continuous cosine-weighted answer')
# The transfer, in closed form, from the SAME numbers the .spv carries.
K = 0.85
TINT = (0.55, 0.45, 0.35)
KC = tuple(1.0 - t * (1.0 - K) for t in TINT)
print('  transfer at o = 1 (fully occluded):')
print(f'    foldrq   fac = 1 - {K}*o        -> {1-K:.4f} (achromatic)')
print('    crevice  fac_c = 1 - K_c*o with K_c = '
      + ', '.join(f'{k:.4f}' for k in KC)
      + ' -> ' + ', '.join(f'{1-k:.4f}' for k in KC))
for c in range(3):
    if abs((1 - KC[c]) - TINT[c] * (1 - K)) > 1e-9:
        bad.append('the crevice transfer is not lerp(1, tint*(1-k), o)')
if not ((1 - KC[0]) > (1 - KC[1]) > (1 - KC[2])):
    bad.append('the crevice residual is not WARM -- red must survive MOST and '
               'blue LEAST, or the tint is inverted and crevices read cold')
if (1 - KC[0]) >= (1 - K):
    bad.append('the crevice residual is not DARKER than the fold residual')
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 9. MANIFEST provenance -------------------------------------------------
echo "=== 9. MANIFEST provenance"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    sed -e "1s/^$BASE /$r /" "$SRC/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
      echo "# concavity (handoff/104): 102's TRACED hemispherical contact occlusion,"
      echo "# generalised OFF skin and ADDED to -- never replacing -- 88's analytic"
      echo "# cavity cone, whose class-1 gate is DISJOINT from this one."
      echo "# K=4 queries in the hemisphere about N from the cone tap's own origin"
      echo "# + 0.1mm*N; flags 517 = Opaque|TerminateOnFirstHit|SkipAABBs, no face"
      echo "# culling; tmin 1mm; o = hits/K."
      case "$r" in
        foldrq*)
          echo "# GATE (fold, 80/81's cloth proxy): class != 1 and class != 4 and"
          echo "# max3(F0) < 0.09, weighted by wr = saturate((rough^2 - 0.10)*5)."
          echo "# tmax 10cm. fac = 1 - 0.85*wr*o, achromatic, on the WHOLE direct"
          echo "# term: the cloth SHEEN lobe lives in the 77 COMPUTE modules and is"
          echo "# not reachable at this site at all (104 sec 2)." ;;
        crevice*)
          echo "# GATE (crevice, rough dielectric): class != 1 and class != 4 and"
          echo "# rough > 0.60 and metallic < 0.10. tmax 5cm."
          echo "# fac_c = 1 - K_c*o, K_c = 1 - tint_c*(1-0.85),"
          echo "# tint = (0.55, 0.45, 0.35): a concave pixel reads darker AND warmer." ;;
      esac
      case "$r" in
        *-ctl) echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE (k=0). Control for the selector." ;;
        *-hit) echo "# INSTRUMENT: flat grey ramp on gated pixels, white = clear, black = occluded." ;;
        *)     echo "# THE FEATURE." ;;
      esac
      echo "# rgs_reference_main ONLY -> photo mode / reference PT. A MULTIPLY on"
      echo "# DIRECT light (98 sec 12.4): arithmetically incapable of doing anything"
      echo "# in shade."
      echo "# NEEDS a layer with VK_KHR_ray_query (98 sec 6/7). NOT working until the"
      echo "# screen says so. A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  ${#ORDER[@]} MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {  # cat every matching file in name order -> one sha
    # NB: -print0/sort -z/xargs -0. The repo path contains a space, so
    # `ls | xargs cat` hashes NOTHING (e3b0c442..., the empty string).
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-13s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-13s content=%s  raygen-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    # NEW names only. Never touch a parked dir this script did not create --
    # other agents are building in this same skin.set.
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        case "$r" in
            foldrq|foldrq-hit|foldrq-ctl|crevice|crevice-hit|crevice-ctl) ;;
            *) echo "  !! refusing to park under the unexpected name $r" >&2; exit 1 ;;
        esac
        if [[ -d "$park" && ! -f "$park/.concavity-owned" ]]; then
            echo "  !! $park exists and was not created by this script -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; touch "$park/.concavity-owned"
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
echo "select with skinspec=foldrq-ctl / foldrq-hit / foldrq"
echo "            skinspec=crevice-ctl / crevice-hit / crevice"
echo "contract: ser=class, shadowset=full-shadow REQUIRED; ptq unchanged; RR OFF;"
echo "          PHOTO MODE (this is rgs_reference_main only), camera pinned,"
echo "          weather CLEAR and the sun HIGH: this is a multiply on DIRECT"
echo "          light and is invisible in shade."
echo "          Read handoff/104 sec 7 BEFORE the screen, and shoot the -hit"
echo "          rungs FIRST."
