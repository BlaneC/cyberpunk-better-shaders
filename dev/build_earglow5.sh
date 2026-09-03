#!/usr/bin/env bash
# earglow5 -- the ear glow, re-tuned on the user's screen verdict. handoff/110.
#
#   "It looks like a lightbulb behind ears. Needs to be like 3/4 less bright,
#    moreso just colouring the effected location. Also needs to have a hard
#    cutoff at a certain thickness. Getting some transmittance through the
#    upper nose bridge which doesn't make sense. The nose bleed effect also
#    carries light of a colour that's too yellow. Really shallow depth
#    transmission should still be coloured more red."
#
# THREE VARIABLES, and the ray queries are NOT among them:
#   (a) k 0.22 -> 0.055                       -- one in-place constant rewrite
#   (b) query B tmax 18 mm -> t_cut, plus a   -- one rewrite + 3 instructions
#       1 mm smoothstep fade below t_cut         (the cutoff is EXACT: past
#       t_cut query B misses, so the accept is false and the term is ZERO)
#   (c) colour, two rungs, never blended:
#       c1 tint (1.0, 0.40, 0.22) on the transfer   -- 3 instructions
#       c2 ld_G 1.37->0.70 mm, ld_B 0.68->0.35 mm   -- 4 rewrites, 0 added
#   (d) the FLOOR, added after 110 sec 3.2 was read -- ONE operand repointed
#       NMax(t, 6 mm) -> NMax(t, 3 mm) / NMax(t, 2 mm), 0 instructions,
#       1 new declaration, and the shared 0.006 constant's twelve OTHER
#       consumers (six OpTraceRayKHR tmaxes, six OpFOrdLessThan) untouched.
#
# The query, its flags, the +/-0.1% bracket, the instance match, query C and
# the wrap smoothstep are untouched in every rung; 101 sec 18's floor is
# untouched in every rung but the two -floor ones, where it is the ONLY
# variable against earglow5.  All 81 non-reference modules ship byte-verbatim.
#
#   ./dev/build_earglow5.sh [--install] [--base <skin.set name>]
#
# 110 sec 14 adds the earglow6 LADDER: one centre and seven single-axis steps
# (cutoff 10/12/15/none, k 0.11/0.165/0.22, tint deep/c1/mild), because the
# user called 12 mm and 75 percent "more vibes" than measurements. Gate 6b
# proves the one-axis claim pairwise against the centre.
#
# Twelve gates, all offline. NO DRIVER SELF-TEST: nothing about the ray queries
# changed -- same three objects, same flags, same getters, same counts (gate 4
# asserts it against the base) -- so dev/selftest_earglow_rq.sh's case A/E
# claims already cover these bytes. Gate 4 is what licenses that skip.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow5.py"
VERIFY="$MOD_DIR/dev/verify_earglow5.py"
WORK="$MOD_DIR/dev/disasm/earglow5"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
K=0.055
K6=0.165
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 && "$n_g" == 4 && "$n_r" == 12 ]] \
    || { echo "$BASE is $n_c/$n_g/$n_r, expected 77/4/12" >&2; exit 1; }
mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs" >&2; exit 1; }
echo "=== 0. base: $BASE"
python3 - "$SRC" "${TARGETS[@]}" <<'PY' || exit 1
import os, subprocess, sys
src, targets = sys.argv[1], sys.argv[2:]
bad = []
for h in targets:
    a = subprocess.run(['spirv-dis', os.path.join(src, h + '.rgs_reference_main.spv')],
                       capture_output=True, text=True).stdout
    got = (a.count('OpRayQueryInitializeKHR'), a.count('OpRayQueryProceedKHR'),
           a.count('OpRayQueryGetIntersectionInstanceIdKHR'),
           a.count('OpRayQueryGetIntersectionTKHR'))
    if got != (3, 3, 2, 1):
        bad.append(f'{h}: {got}, want 3/3/2/1 -- not the earglow-cap6 stack '
                   f'(6/6/4/2 would be a thinglow rung, which 110 refuses)')
    for c in ('0.219999999', '0.0179999992', '0.00600000005', '272.479553',
              '729.927002', '1470.58826', '68.1198883', '182.48175',
              '367.647064'):
        if c not in a:
            bad.append(f'{h}: constant {c} missing from the base')
if bad:
    for b in bad[:8]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
print(f'  {len(targets)} paintable permutations at 3/3/2/1 with k=0.22, '
      f'tmax=0.018, floor=0.006 and all six 101 rate constants')
PY

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
done
echo "  10 of 10 reference permutations round-trip byte-identically"
rm -rf "$WORK/rt"

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
patch_set () {
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.earglow5.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}
assemble () {
    local dest="$1" src="$2" live="$3"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$SRC/$p.rgs_reference_main.spv" "$dest/"; done
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for p in "${PASS[@]}"; do
        cmp -s "$SRC/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            || { echo "  !! pass-through $p differs" >&2; exit 1; }
    done
    for h in "${TARGETS[@]}"; do
        if (( live )); then
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                && { echo "  !! $h is byte-identical to the base" >&2; exit 1; }
        else
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                || { echo "  !! CONTROL $h differs from the base" >&2; exit 1; }
        fi
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
ORDER=(earglow5 earglow5-cut6 earglow5-cut10 earglow5-rate
       earglow5-floor3 earglow5-floor2 earglow5-ctl
       earglow6 earglow6-cut10 earglow6-cut15 earglow6-cutoff
       earglow6-k11 earglow6-k22 earglow6-mild earglow6-deep)
LIVE=(earglow5 earglow5-cut6 earglow5-cut10 earglow5-rate
      earglow5-floor3 earglow5-floor2
      earglow6 earglow6-cut10 earglow6-cut15 earglow6-cutoff
      earglow6-k11 earglow6-k22 earglow6-mild earglow6-deep)
# the earglow6 ladder: centre + one step per axis. earglow5-ctl stays THE
# control for both families; no second identity rung is built.
V6=(earglow6-cut10 earglow6-cut15 earglow6-cutoff
    earglow6-k11 earglow6-k22 earglow6-mild earglow6-deep)
echo "=== 2. patch + assemble the ${#ORDER[@]} rungs"
declare -A V6_AXIS=(
    [earglow6-cut10]=cut  [earglow6-cut15]=cut  [earglow6-cutoff]=cutoff
    [earglow6-k11]=k      [earglow6-k22]=k
    [earglow6-mild]=tint  [earglow6-deep]=tint
)
# every v5 rung is now FROZEN: adding the v6 ladder must not move one byte
FROZEN=(earglow5 earglow5-cut6 earglow5-cut10 earglow5-rate
        earglow5-floor3 earglow5-floor2 earglow5-ctl)
declare -A RUNG_ARGS=(
    [earglow5]="--k $K --cut 0.008 --mode tint"
    [earglow5-cut6]="--k $K --cut 0.006 --mode tint"
    [earglow5-cut10]="--k $K --cut 0.010 --mode tint"
    [earglow5-rate]="--k $K --cut 0.008 --mode rate"
    [earglow5-floor3]="--k $K --cut 0.008 --mode tint --floor 0.003"
    [earglow5-floor2]="--k $K --cut 0.008 --mode tint --floor 0.002"
    [earglow5-ctl]="--k 0.219999999 --cut 0.0179999992 --mode none"
    [earglow6]="--k $K6 --cut 0.012 --floor 0.003 --mode tint"
    [earglow6-cut10]="--k $K6 --cut 0.010 --floor 0.003 --mode tint"
    [earglow6-cut15]="--k $K6 --cut 0.015 --floor 0.003 --mode tint"
    [earglow6-cutoff]="--k $K6 --no-cutoff --floor 0.003 --mode tint"
    [earglow6-k11]="--k 0.11 --cut 0.012 --floor 0.003 --mode tint"
    [earglow6-k22]="--k 0.22 --cut 0.012 --floor 0.003 --mode tint"
    [earglow6-mild]="--k $K6 --cut 0.012 --floor 0.003 --mode tint --tint 1.0,0.55,0.35"
    [earglow6-deep]="--k $K6 --cut 0.012 --floor 0.003 --mode tint --tint 1.0,0.30,0.15"
)
for r in "${ORDER[@]}"; do
    live=1; [[ "$r" == earglow5-ctl ]] && live=0
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "$live"
    echo "  swaps.$r: 93 modules, $(( live * 10 )) patched, spirv-val clean"
done
for pair in "earglow5 earglow5-cut6" "earglow5 earglow5-cut10" \
            "earglow5-cut6 earglow5-cut10" "earglow5 earglow5-rate" \
            "earglow5 earglow5-floor3" "earglow5 earglow5-floor2" \
            "earglow5-floor3 earglow5-floor2" \
            "earglow6 earglow6-cut10" "earglow6 earglow6-cut15" \
            "earglow6 earglow6-cutoff" "earglow6 earglow6-k11" \
            "earglow6 earglow6-k22" "earglow6 earglow6-mild" \
            "earglow6 earglow6-deep" "earglow6-mild earglow6-deep"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 differ between every pair of live rungs"

# --- 3. coverage census, from the REPORTS ----------------------------------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of the argv above.
LD_C1 = (0.00367, 0.00137, 0.00068)
T_C1 = (1.0, 0.40, 0.22)
WANT = {
 'earglow5':        dict(mode='tint', k=0.055, cut=0.008, add=6, floor=0.006, ld=(0.00367, 0.00137, 0.00068), tint=T_C1),
 'earglow5-cut6':   dict(mode='tint', k=0.055, cut=0.006, add=6, floor=0.006, ld=(0.00367, 0.00137, 0.00068), tint=T_C1),
 'earglow5-cut10':  dict(mode='tint', k=0.055, cut=0.010, add=6, floor=0.006, ld=(0.00367, 0.00137, 0.00068), tint=T_C1),
 'earglow5-rate':   dict(mode='rate', k=0.055, cut=0.008, add=3, floor=0.006, ld=(0.00367, 0.00070, 0.00035)),
 'earglow5-floor3': dict(mode='tint', k=0.055, cut=0.008, add=6, floor=0.003, ld=(0.00367, 0.00137, 0.00068), tint=T_C1),
 'earglow5-floor2': dict(mode='tint', k=0.055, cut=0.008, add=6, floor=0.002, ld=(0.00367, 0.00137, 0.00068), tint=T_C1),
 'earglow5-ctl':    dict(mode='control', k=None, cut=None, add=0, floor=0.006, ld=None),
 # --- the earglow6 ladder: centre first, then one axis at a time ----------
 'earglow6':        dict(mode='tint', k=0.165, cut=0.012, add=6, floor=0.003, ld=LD_C1, tint=T_C1),
 'earglow6-cut10':  dict(mode='tint', k=0.165, cut=0.010, add=6, floor=0.003, ld=LD_C1, tint=T_C1),
 'earglow6-cut15':  dict(mode='tint', k=0.165, cut=0.015, add=6, floor=0.003, ld=LD_C1, tint=T_C1),
 'earglow6-cutoff': dict(mode='tint', k=0.165, cut=0.018, add=3, floor=0.003, ld=LD_C1, tint=T_C1, cutoff=False),
 'earglow6-k11':    dict(mode='tint', k=0.110, cut=0.012, add=6, floor=0.003, ld=LD_C1, tint=T_C1),
 'earglow6-k22':    dict(mode='tint', k=0.220, cut=0.012, add=6, floor=0.003, ld=LD_C1, tint=T_C1),
 'earglow6-mild':   dict(mode='tint', k=0.165, cut=0.012, add=6, floor=0.003, ld=LD_C1, tint=(1.0, 0.55, 0.35)),
 'earglow6-deep':   dict(mode='tint', k=0.165, cut=0.012, add=6, floor=0.003, ld=LD_C1, tint=(1.0, 0.30, 0.15)),
}
def near(a, b, rel=1e-4):
    return a is not None and abs(a - b) <= rel * max(1.0, abs(b))
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]; mods = 0
    for f in sorted(glob.glob(os.path.join(d, '*.earglow5.report.json'))):
        rep = json.load(open(f)); q = rep['earglow5']; mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['mode'] != want['mode']:
            bad.append((r, rep['module'], f"mode {q['mode']}"))
        if want['mode'] == 'control':
            if q.get('emitted') != 0:
                bad.append((r, rep['module'], 'the CONTROL emitted instructions'))
            continue
        if not near(q['k'], want['k']) or not near(q['cut_m'], want['cut']):
            bad.append((r, rep['module'], f"k/cut {q['k']}/{q['cut_m']}"))
        if q['added_instructions'] != want['add']:
            bad.append((r, rep['module'], f"{q['added_instructions']} added, want {want['add']}"))
        if not near(q['cap6_floor'], want['floor'], 1e-4):
            bad.append((r, rep['module'], f"floor is {q['cap6_floor']}, want {want['floor']}"))
        fr = q.get('floor_repoint')
        if abs(want['floor'] - 0.006) < 1e-9:
            if fr is not None:
                bad.append((r, rep['module'], 'the floor was touched'))
        elif fr is None or fr['in_place'] or fr['instructions'] != 0 \
                or fr['other_consumers_left_alone'] != 12:
            bad.append((r, rep['module'], f"floor repoint {fr}"))
        want_touch = 'tmax constant only' if want.get('cutoff', True) else 'nothing'
        if q['flags_b'] != 545 or q['query_touched'] != want_touch:
            bad.append((r, rep['module'], f"query_touched={q['query_touched']}, want {want_touch}"))
        if q.get('cutoff', True) != want.get('cutoff', True):
            bad.append((r, rep['module'], f"cutoff flag {q.get('cutoff')}"))
        for i, ld in enumerate(want['ld']):
            if not near(q['ld_new_m'][i], ld, 1e-3):
                bad.append((r, rep['module'], f"ld[{i}] {q['ld_new_m'][i]}, want {ld}"))
        if want['mode'] == 'tint':
            if not q['tint'] or any(not near(a, b, 1e-3)
                                    for a, b in zip(q['tint'], want['tint'])):
                bad.append((r, rep['module'], f"tint {q['tint']}, want {want['tint']}"))
        else:
            if q['tint'] is not None:
                bad.append((r, rep['module'], '(c1) and (c2) blended'))
        if not want.get('cutoff', True):
            if q['fade'] is not None:
                bad.append((r, rep['module'], 'the -cutoff rung carries a fade'))
        elif q['fade'] is None or q['fade']['on'] != 'guarded t' \
                or q['fade']['inverted']:
            bad.append((r, rep['module'], f"fade {q['fade']}"))
        elif not near(q['fade']['edges_m'][1], want['cut']) \
                or not near(q['fade']['edges_m'][0], want['cut'] - 0.001):
            bad.append((r, rep['module'], f"fade edges {q['fade']['edges_m']}"))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY reached a rung'))
        rw = {x['what'] for x in q.get('rewrites', [])}
        need = {'k (brightness)'}
        if want.get('cutoff', True):
            need.add('query B tmax (cutoff)')
        if want['mode'] == 'rate':
            need |= {f'1/ld chan {i} (narrow lobe)' for i in (1, 2)}
            need |= {f'1/(4.0ld) chan {i} (wide lobe)' for i in (1, 2)}
        if not need <= rw:
            bad.append((r, rep['module'], f"missing rewrites {sorted(need - rw)}"))
        if not all(x['in_place'] for x in q.get('rewrites', [])):
            bad.append((r, rep['module'], 'a rewrite was not in place'))
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if want['mode'] == 'control':
        print(f'  {r:16s} 10 modules, 0 instructions emitted (identity)')
        continue
    fl = ('floor 6 mm UNTOUCHED' if abs(want['floor'] - 0.006) < 1e-9 else
          f"floor {want['floor']*1000:g} mm (repointed)")
    ct = (f"cut={want['cut']*1000:g} mm" if want.get('cutoff', True)
          else 'NO CUTOFF (tmax 18 mm, decay only)')
    tn = f", tint={want['tint']}" if want['mode'] == 'tint' else ''
    print(f"  {r:16s} 10 modules, k={want['k']}, {ct}, "
          f"mode={want['mode']}, +{want['add']} instructions/module, "
          f"{len(need)} in-place constant rewrites, {fl}{tn}")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes ----------------------------
# THIS GATE IS WHAT LICENSES SKIPPING THE DRIVER SELF-TEST: if not one
# ray-query instruction count moved, the driver is being handed the same
# shapes selftest_earglow_rq.sh already compiled.
echo "=== 4. instruction census on the SHIPPED bytes (vs the base, op by op)"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
OPS = ('OpRayQueryInitializeKHR', 'OpRayQueryProceedKHR',
       'OpRayQueryGetIntersectionTypeKHR',
       'OpRayQueryGetIntersectionInstanceIdKHR',
       'OpRayQueryGetIntersectionTKHR',
       'OpRayQueryGetIntersectionInstanceCustomIndexKHR',
       'OpTraceRayKHR', 'OpCapability RayQueryKHR')
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = {o: 0 for o in OPS}
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        for o in OPS:
            if a.count(o) != b.count(o):
                bad.append(f'{r}/{h}: {o} {b.count(o)} -> {a.count(o)}')
            tot[o] += a.count(o)
        if h not in PASS and a.count('OpRayQueryGetIntersectionInstanceCustomIndexKHR'):
            bad.append(f'{r}/{h}: InstanceCustomIndex appeared')
    print(f"  {r:16s} {tot['OpRayQueryInitializeKHR']} Initialize, "
          f"{tot['OpRayQueryProceedKHR']} Proceed, "
          f"{tot['OpRayQueryGetIntersectionInstanceIdKHR']} InstanceId, "
          f"{tot['OpRayQueryGetIntersectionTKHR']} committed-T, "
          f"{tot['OpTraceRayKHR']} traces -- ALL IDENTICAL TO THE BASE")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. identity ------------------------------------------------------------
echo "=== 5. identity control"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.earglow5-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! earglow5-ctl differs on $d files" >&2; exit 1; }
echo "  earglow5-ctl: 93 of 93 byte-identical to $BASE"
for r in "${LIVE[@]}"; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs on $d files, want 10" >&2; exit 1; }
done
echo "  the ${#LIVE[@]} live rungs: 10 of 93 differ"

# --- 5b. REGRESSION: the pre-110-sec-13 rungs are bit-frozen ---------------
# Adding --floor must not have perturbed a single byte of the four rungs the
# user already has parked. This compares against what is INSTALLED, not
# against a fresh build of itself, so a silent drift in the patcher is caught.
echo "=== 5b. regression against the parked rungs"
any=0
for r in "${FROZEN[@]}"; do
    park="$INSTALL_DIR/skin.set/$r"
    if [[ ! -d "$park" ]]; then
        echo "  $r: not parked yet, nothing to compare"; continue
    fi
    d=0; n=0
    for f in "$MOD_DIR/swaps.$r"/*.spv; do
        n=$((n+1))
        cmp -s "$f" "$park/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 0 ]] || { echo "  !! $r: $d of $n modules differ from the parked set" >&2; exit 1; }
    echo "  $r: $n of $n byte-identical to the parked set"
    any=$((any+1))
done
[[ "$any" -ge 1 ]] || echo "  (nothing parked; regression not exercised)"

# --- 6. the verifier --------------------------------------------------------
echo "=== 6. verify_earglow5.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5"        --base "$SRC" --mode tint --k "$K" --cut 0.008
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5-cut6"   --base "$SRC" --mode tint --k "$K" --cut 0.006
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5-cut10"  --base "$SRC" --mode tint --k "$K" --cut 0.010
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5-rate"   --base "$SRC" --mode rate --k "$K" --cut 0.008
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5-floor3" --base "$SRC" --mode tint --k "$K" --cut 0.008 --floor 0.003
python3 "$VERIFY" "$MOD_DIR/swaps.earglow5-floor2" --base "$SRC" --mode tint --k "$K" --cut 0.008 --floor 0.002
V6ARGS () {   # the SAME design, restated here rather than read from RUNG_ARGS
    case "$1" in
      earglow6)        echo "--mode tint --k $K6 --cut 0.012 --floor 0.003" ;;
      earglow6-cut10)  echo "--mode tint --k $K6 --cut 0.010 --floor 0.003" ;;
      earglow6-cut15)  echo "--mode tint --k $K6 --cut 0.015 --floor 0.003" ;;
      earglow6-cutoff) echo "--mode tint --k $K6 --cut 0.0179999992 --no-cutoff --floor 0.003" ;;
      earglow6-k11)    echo "--mode tint --k 0.11 --cut 0.012 --floor 0.003" ;;
      earglow6-k22)    echo "--mode tint --k 0.22 --cut 0.012 --floor 0.003" ;;
      earglow6-mild)   echo "--mode tint --k $K6 --cut 0.012 --floor 0.003 --tint 1.0,0.55,0.35" ;;
      earglow6-deep)   echo "--mode tint --k $K6 --cut 0.012 --floor 0.003 --tint 1.0,0.30,0.15" ;;
    esac
}
for r in earglow6 "${V6[@]}"; do
    # shellcheck disable=SC2046
    python3 "$VERIFY" "$MOD_DIR/swaps.$r" --base "$SRC" $(V6ARGS "$r")
done
python3 "$VERIFY" --negative "$SRC"
python3 "$VERIFY" --control "$MOD_DIR/swaps.earglow5-ctl" --base "$SRC"

# --- 6b. the LADDER: one axis per rung, pairwise against the centre --------
echo "=== 6b. ladder: every earglow6 rung differs from the centre on ONE axis"
for r in "${V6[@]}"; do
    printf '  %-16s ' "$r"
    python3 "$VERIFY" "$MOD_DIR/swaps.$r" --vs-centre "$MOD_DIR/swaps.earglow6" \
            --axis "${V6_AXIS[$r]}"
done

# --- 7. verifier NON-VACUITY ------------------------------------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () { local label="$1"; shift
    if python3 "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1; fi
    echo "  rejected: $label"; }
declare -A WHY=(
    [nofade]="tmax cut but no smoothstep -- a visible hard edge at t_cut"
    [nocut]="fade added but tmax left at 18 mm -- the nose bridge still glows"
    [notint]="tint (1,1,1) -- still yellow, the user's third complaint unfixed"
    [flatk]="k left at 0.22 -- still a lightbulb"
    [invfade]="the fade not negated: lights ONLY past the cutoff"
    [tintswap]="tint reversed to (0.22, 0.40, 1.0) -- blue, not red"
    [fadefloored]="the fade reads the FLOORED t -- at cut6 the rung goes black"
    [floorshared]="the floor REWRITTEN in place: the shared 0.006 constant is also six OpTraceRayKHR tmaxes"
)
G=(--base "$SRC" --mode tint --k "$K" --cut 0.008)
for dec in nofade nocut notint flatk invfade tintswap fadefloored; do
    patch_set "$WORK/decoy/$dec" --k "$K" --cut 0.008 --mode tint --decoy "$dec"
    reject "--decoy $dec (${WHY[$dec]})" "$VERIFY" "$WORK/decoy/$dec" "${G[@]}"
    rm -rf "$WORK/decoy/$dec"
done
patch_set "$WORK/decoy/floorshared" --k "$K" --cut 0.008 --mode tint \
          --floor 0.003 --decoy floorshared
reject "--decoy floorshared (${WHY[floorshared]})" "$VERIFY" \
       "$WORK/decoy/floorshared" --base "$SRC" --mode tint --k "$K" \
       --cut 0.008 --floor 0.003
rm -rf "$WORK/decoy/floorshared"
reject "the unpatched BASE read as a rung" "$VERIFY" "$SRC" "${G[@]}"
reject "the CONTROL read as a rung" "$VERIFY" "$MOD_DIR/swaps.earglow5-ctl" "${G[@]}"
reject "earglow5 read at cut 6 mm" "$VERIFY" "$MOD_DIR/swaps.earglow5" --base "$SRC" --mode tint --k "$K" --cut 0.006
reject "earglow5-cut10 read at cut 8 mm" "$VERIFY" "$MOD_DIR/swaps.earglow5-cut10" "${G[@]}"
reject "earglow5 read as the rate rung" "$VERIFY" "$MOD_DIR/swaps.earglow5" --base "$SRC" --mode rate --k "$K" --cut 0.008
reject "earglow5-rate read as the tint rung" "$VERIFY" "$MOD_DIR/swaps.earglow5-rate" "${G[@]}"
reject "earglow5 read at the OLD k (0.22)" "$VERIFY" "$MOD_DIR/swaps.earglow5" --base "$SRC" --mode tint --k 0.22 --cut 0.008
reject "the CONTROL read as byte-different" "$VERIFY" --control "$MOD_DIR/swaps.earglow5" --base "$SRC"
reject "earglow5 read at floor 3 mm" "$VERIFY" "$MOD_DIR/swaps.earglow5" --base "$SRC" --mode tint --k "$K" --cut 0.008 --floor 0.003
reject "earglow5-floor3 read at the 6 mm floor" "$VERIFY" "$MOD_DIR/swaps.earglow5-floor3" "${G[@]}"
reject "earglow5-floor2 read at floor 3 mm" "$VERIFY" "$MOD_DIR/swaps.earglow5-floor2" --base "$SRC" --mode tint --k "$K" --cut 0.008 --floor 0.003
G6=(--base "$SRC" --mode tint --k "$K6" --cut 0.012 --floor 0.003)
reject "earglow6 read at k 0.11 (the -k11 rung's k)" "$VERIFY" "$MOD_DIR/swaps.earglow6" --base "$SRC" --mode tint --k 0.11 --cut 0.012 --floor 0.003
reject "earglow6-k22 read at the centre's k" "$VERIFY" "$MOD_DIR/swaps.earglow6-k22" "${G6[@]}"
reject "earglow6-mild read at the centre's tint" "$VERIFY" "$MOD_DIR/swaps.earglow6-mild" "${G6[@]}"
reject "earglow6-deep read as the mild tint" "$VERIFY" "$MOD_DIR/swaps.earglow6-deep" "${G6[@]}" --tint 1.0,0.55,0.35
reject "earglow6-cutoff read as if it had a 12 mm cutoff" "$VERIFY" "$MOD_DIR/swaps.earglow6-cutoff" "${G6[@]}"
reject "earglow6 read as the no-cutoff rung" "$VERIFY" "$MOD_DIR/swaps.earglow6" --base "$SRC" --mode tint --k "$K6" --cut 0.0179999992 --no-cutoff --floor 0.003
reject "earglow6-cut15 read at the centre's 12 mm cut" "$VERIFY" "$MOD_DIR/swaps.earglow6-cut15" "${G6[@]}"
reject "the LADDER: earglow6-mild claimed on axis k" "$VERIFY" "$MOD_DIR/swaps.earglow6-mild" --vs-centre "$MOD_DIR/swaps.earglow6" --axis k
reject "the LADDER: earglow6-k11 claimed on axis tint" "$VERIFY" "$MOD_DIR/swaps.earglow6-k11" --vs-centre "$MOD_DIR/swaps.earglow6" --axis tint
reject "the LADDER: earglow6-cutoff claimed on axis cut" "$VERIFY" "$MOD_DIR/swaps.earglow6-cutoff" --vs-centre "$MOD_DIR/swaps.earglow6" --axis cut
reject "the LADDER: earglow5-floor2 claimed a one-axis step from the centre" "$VERIFY" "$MOD_DIR/swaps.earglow5-floor2" --vs-centre "$MOD_DIR/swaps.earglow6" --axis k
rm -rf "$WORK/decoy"

# --- 8. closed-form transfer, from the SHIPPED constants -------------------
echo "=== 8. closed-form transfer (numpy) against the constants in the .spv"
python3 - "$MOD_DIR" "${LIVE[@]}" <<'EOG' || exit 1
import glob, os, sys
import numpy as np
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
# The rates, the tint and the cutoff are read back through the VERIFIER's own
# structural re-derivation of the transfer chains -- not by scraping every
# float in the module and guessing which ones pair up, which is how the first
# version of this gate reported ld = 0.98 mm three times.
from verify_earglow5 import glow, dis, index, fval, body
mod_dir, rungs = sys.argv[1], sys.argv[2:]
bad = []
TS = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0)
FULL = {'earglow5', 'earglow5-cut6', 'earglow5-cut10', 'earglow5-rate',
        'earglow5-floor3', 'earglow5-floor2', 'earglow6'}
SUMMARY = []
for r in rungs:
    f = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r,
                                      '*.rgs_reference_main.spv')))[0]
    lines = dis(f); d = index(lines)
    g = glow(lines, d, os.path.basename(f), '8')
    if g is None:
        bad.append(r + ': the transfer could not be re-derived'); continue
    km = fval(d, body(d, g['ksel']).split()[3])
    cut = fval(d, g['b'][7])
    CAP = fval(d, g['cap'])          # the floor, read back out of the bytes
    a1 = np.array([c['narrow'] for c in g['chains']])
    a2 = np.array([c['wide'] for c in g['chains']])
    tint = np.array([fval(d, c['tint']) if c['tint'] else 1.0
                     for c in g['chains']])
    print(f'  {r}: k={km:g}, cut={cut*1e3:g} mm, floor={CAP*1e3:g} mm, '
          f'ld={np.round(1e3/a1, 2)} mm, '
          f'wide-lobe ld={np.round(1e3/a2, 2)} mm, tint={tint}')
    if r in FULL:
        print('     t(mm)  t_eff(mm)       R           G           B      R/G   fade')
    nofade = (r == 'earglow6-cutoff')

    def at(tt):
        t = tt * 1e-3
        if t > cut:
            return None
        teff = max(t, CAP)
        T = 0.5 * (np.exp(-teff * a1) + np.exp(-teff * a2))
        if nofade:
            fade = 1.0
        else:
            u = float(np.clip((cut - t) / 0.001, 0.0, 1.0))
            fade = u * u * (3 - 2 * u)
        return teff, km * T * tint * fade, fade

    if r in FULL:
        for tt in TS:
            v = at(tt)
            if v is None:
                print(f'   {tt:6.1f}         --    {"0":>9}   {"0":>9}   {"0":>9}     --   CUT (query B misses)')
                continue
            teff, rgb, fade = v
            rg = rgb[0] / rgb[1] if rgb[1] > 0 else float('inf')
            print(f'   {tt:6.1f}     {teff*1e3:6.2f}    {rgb[0]:9.6f}   {rgb[1]:9.6f}   '
                  f'{rgb[2]:9.6f}  {rg:5.2f}  {fade:5.3f}')
    # THE PEAK IS FOUND, NOT ASSUMED. Taking it at t = the floor is wrong
    # whenever the fade's zero sits at or below the floor (earglow5-cut6 is
    # exactly that case: floor 6 mm, fade zero at 6 mm), which reported a peak
    # of 0.000000 and a peak/8 mm ratio of 2.9e12. Scan instead.
    grid = [x * 0.1 for x in range(5, int(cut * 1e3 * 10) + 1)]
    cand = [(at(x), x) for x in grid]
    cand = [(v, x) for v, x in cand if v is not None]
    (pk, pkt) = max(cand, key=lambda c: c[0][1][0])
    v2, v8 = at(2.0), at(8.0)
    ok8 = v8 is not None and v8[1][0] > 1e-9
    rg = lambda v: (v[1][0] / v[1][1]) if (v and v[1][1] > 1e-12) else None
    f2, f8 = rg(v2), rg(v8)
    SUMMARY.append(
        f"  {r:16s} peak@{pkt:4.1f}mm R {pk[1][0]:.6f} G {pk[1][1]:.6f} "
        f"B {pk[1][2]:.6f} | R/G 2mm {f'{f2:5.2f}' if f2 else '   --'} "
        f"8mm {f'{f8:5.2f}' if f8 else '   --'} "
        f"| peak/8mm R {f'x{pk[1][0]/v8[1][0]:.2f}' if ok8 else '-- (8 mm is past this cut)'}")
    # The SHAPE claims 110 sec 5 makes, checked rather than asserted.
    Tf = 0.5 * (np.exp(-CAP * a1) + np.exp(-CAP * a2)) * tint
    if Tf[0] / Tf[1] <= 2.0:
        bad.append(f'{r}: R/G at the floor is {Tf[0]/Tf[1]:.2f}x -- the user '
                   f'asked for RED and 101 shipped 1.3-1.8x')
    if not km <= 0.2201:
        bad.append(f'{r}: k is {km}, above the shipped 0.22')
    if cut > 0.0181:
        bad.append(f'{r}: the cutoff is {cut*1e3:g} mm -- past the shipped tmax')
if SUMMARY:
    print('  --- one line per rung: peak, R/G at 2 and 8 mm, peak-to-8 mm red ---')
    for l in SUMMARY:
        print(l)
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + chr(10))
    sys.exit(1)
EOG

# --- 9. MANIFEST ------------------------------------------------------------
echo "=== 9. MANIFEST provenance"
src_ser=$(head -1 "$SRC/MANIFEST.txt")
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    {
      echo "$r (base=$BASE) ear glow v5, handoff/110"
      echo "# THE QUERY IS UNCHANGED: 3 Initialize / 3 Proceed / 2 InstanceId /"
      echo "# 1 committed T, flags 545+517+517, the same bracket, the same"
      echo "# instance match, the same query C, the same 6 mm cap6 floor."
      case "$r" in
        earglow5-ctl) echo "# k=0.22, cut=18 mm, no tint: byte-identical to the base." ;;
        earglow5-rate) echo "# k=0.055, cut 8 mm + 1 mm fade, ld = 3.67/0.70/0.35 mm (c2)" ;;
        earglow5-cut6) echo "# k=0.055, cut 6 mm + 1 mm fade, tint (1.0,0.40,0.22) (c1)" ;;
        earglow5-cut10) echo "# k=0.055, cut 10 mm + 1 mm fade, tint (1.0,0.40,0.22) (c1)" ;;
        earglow5-floor3) echo "# earglow5 with 101 sec 18's floor at 3 mm, not 6 mm (110 sec 13)" ;;
        earglow5-floor2) echo "# earglow5 with 101 sec 18's floor at 2 mm, not 6 mm (110 sec 13)" ;;
        earglow6)        echo "# 110 sec 14 CENTRE: k=0.165, cut 12 mm + 1 mm fade, floor 3 mm, tint (1.0,0.40,0.22)" ;;
        earglow6-cut10)  echo "# 110 sec 14 ladder, CUTOFF axis: 10 mm (centre is 12 mm)" ;;
        earglow6-cut15)  echo "# 110 sec 14 ladder, CUTOFF axis: 15 mm (centre is 12 mm)" ;;
        earglow6-cutoff) echo "# 110 sec 14 ladder, CUTOFF axis: NONE. tmax stays at the shipped 18 mm and no fade is spliced; the transfer's own decay is the only falloff" ;;
        earglow6-k11)    echo "# 110 sec 14 ladder, BRIGHTNESS axis: k=0.11 (centre is 0.165)" ;;
        earglow6-k22)    echo "# 110 sec 14 ladder, BRIGHTNESS axis: k=0.22, the shipped brightness with the new cutoff, floor and tint" ;;
        earglow6-mild)   echo "# 110 sec 14 ladder, COLOUR axis: tint (1.0,0.55,0.35) (centre is 0.40/0.22)" ;;
        earglow6-deep)   echo "# 110 sec 14 ladder, COLOUR axis: tint (1.0,0.30,0.15) (centre is 0.40/0.22)" ;;
        *) echo "# k=0.055, cut 8 mm + 1 mm fade, tint (1.0,0.40,0.22) (c1)" ;;
      esac
      echo "# cutoff is EXACT: past tmax query B misses, the accept is false."
      case "$r" in
        earglow6*)
          echo "# EARGLOW6 LADDER. earglow5-ctl is the control for this family"
          echo "# too; no second identity rung exists. Every rung differs from"
          echo "# earglow6 on exactly ONE axis and build gate 6b proves it"
          echo "# pairwise from the shipped bytes. Read 110 sec 14 first:"
          echo "# t is a SUN-PATH CHORD, not an anatomical thickness, which is"
          echo "# why an 8 mm cut erased the effect at backlit grazing angles." ;;
        earglow5-floor*)
          echo "# The floor is the ONLY variable against earglow5. It is a"
          echo "# REPOINT, not a rewrite: the shared 0.006 constant keeps its"
          echo "# twelve other consumers (6 OpTraceRayKHR tmax, 6 comparisons)."
          echo "# 101 sec 18 picked 6 mm because CHILDREN's ears blew out at"
          echo "# k=0.22; at k=0.055 that ceiling argument is 4x weaker, but"
          echo "# it is UNMEASURED -- these two rungs are the measurement." ;;
        *)
          echo "# NOTE (110 sec 3.2): the 6 mm floor means every ear thinner"
          echo "# than 6 mm renders as 6 mm. This rung changes the COLOUR at"
          echo "# 6 mm; earglow5-floor3/-floor2 lower the floor itself." ;;
      esac
      echo "# src: $src_ser"
      grep -E '^# (src_ser|ser_sha|ptq_sha)' "$SRC/MANIFEST.txt" 2>/dev/null || true
      echo "# UNSHOT. Read handoff/110 sec 7 BEFORE the screen: BACKLIT head,"
      echo "# a CHILD and an ADULT and a NOSE-BRIDGE view in ONE frame,"
      echo "# shadowset=full-shadow."
    } > "$dest/MANIFEST.txt"
done
echo "  ${#ORDER[@]} MANIFESTs written"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () { find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
            xargs -0 cat | sha256sum | cut -c1-16; }
for r in "${ORDER[@]}"; do
    printf '  %-17s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-17s content=%s  raygen-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        if [[ -e "$park" && ! -f "$park/.earglow5" ]]; then
            echo "  !! $park exists and was not parked by build_earglow5.sh -- refusing" >&2
            exit 1
        fi
        rm -rf "$park"; mkdir -p "$park"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        : > "$park/.earglow5"
        n=0
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! park differs: $f" >&2; exit 1; }
            n=$((n+1))
        done
        echo "  parked -> $park ($n modules, cmp-verbatim)"
    done
fi

echo
echo "NO DRIVER SELF-TEST WAS RUN, on purpose: gate 4 proves not one ray-query"
echo "instruction count changed against the base, so dev/selftest_earglow_rq.sh's"
echo "existing case A/E results already cover these bytes. Re-run it only if a"
echo "future rung touches the query itself."
echo
echo "v5: skinspec=earglow5 / -cut6 / -cut10 / -rate / -floor3 / -floor2"
echo "v6 ladder (110 sec 14): earglow6 is the CENTRE; one axis per step --"
echo "  cutoff: earglow6-cut10 / earglow6 (12) / earglow6-cut15 / earglow6-cutoff (none)"
echo "  bright: earglow6-k11 / earglow6 (0.165) / earglow6-k22"
echo "  colour: earglow6-deep / earglow6 (0.40,0.22) / earglow6-mild"
echo "control: earglow5-ctl (byte-identical to the base)"
echo "contract: ser=class, shadowset=full-shadow, ptq unchanged; RR OFF; photo"
echo "          mode / reference PT reach; BACKLIT head, sun low and behind;"
echo "          a CHILD and an ADULT and a NOSE-BRIDGE (3/4 or profile) view in"
echo "          ONE frame. Read handoff/110 sec 7 BEFORE the screen."
