#!/usr/bin/env bash
# thinglow -- BACKLIT TRANSLUCENCY FOR EVERY THIN SURFACE. handoff/105.
#
# 101's ear glow proved the construction: trace sunward from the shaded point,
# cull FRONT faces so the first hit is the far wall, demand the far wall belong
# to the SAME instance as the primary surface, demand the exit point see the
# sun, and add k * exp(-t/ld) * sunRadiance. That rung is gated on class 1 and
# lights ears and nothing else. This rung STACKS the same construction on the
# complement -- curtains, tents, umbrellas, tarps, plastic sheeting, paper
# signs, thin clothing -- with an albedo tint so a red tarp glows red, and a
# 0.3 -> 25 mm band instead of 1.5 -> 18 mm.
#
# It is built ON TOP of the standing default, which already carries the ear
# glow, the 6 mm floor and the dense glints. Gate 6 proves the ear glow is
# bit-identical on skin pixels: its gate's FIRST term is class != 1, and gate
# 6's check 14 re-derives 101's own term still reaching the pixel.
#
#   ./dev/build_thinglow.sh [--install] [--base <skin.set name>]
#
# Ten gates, all offline, then the driver self-test:
#   0 base provenance 77/4/12 + the ear glow IS in it
#   1 dis->as byte-neutral            6 verify_thinglow.py + --negative/--control
#   2 patch + spirv-val vulkan1.4     7 non-vacuity: eight decoys REJECTED
#   3 coverage census from reports    8 closed-form transfer (numpy)
#   4 instruction census on bytes     9 MANIFEST provenance
#   5 identity: ctl 93/93, live 10/93
#   then: ./dev/selftest_thinglow.sh   (layer + driver, no game)
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_thinglow.py"
VERIFY="$MOD_DIR/dev/verify_thinglow.py"
WORK="$MOD_DIR/dev/disasm/thinglow"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
K=0.5
KHI=1.0
LD=0.002
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
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
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }
echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-80))"

# THE STACKING PRECONDITION. `--k 0` reproducing this base proves nothing
# unless the base is the one that carries the ear glow, so assert it here
# BEFORE a single byte is patched -- 3/3/2/1 ray-query ops per paintable
# permutation, and 0 in the two pass-throughs.
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
        bad.append(f'{h}: {got}, want 3/3/2/1 -- the base has no ear glow')
    for c in ('272.479553', '68.1198883', '729.927002', '182.48175',
              '1470.58826', '367.647064', '0.219999999', '0.00600000005'):
        if c not in a:
            bad.append(f'{h}: 101/102 constant {c} missing from the base')
if bad:
    for b in bad[:8]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
print(f'  {len(targets)} paintable permutations carry 3/3/2/1 ray-query ops '
      f'and all 8 ear-glow constants -- this IS the earglow-cap6 stack')
PY

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
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
                > "$CB_O/$0.thinglow.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir, $3 = 1 if the modules
                #      must DIFFER from the base (0 for the control)
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
            || { echo "  !! pass-through $p differs from the base" >&2; exit 1; }
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
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the four rungs"
ORDER=(thinglow-hit thinglow thinglow-hi thinglow-ctl)
LIVE=(thinglow-hit thinglow thinglow-hi)
declare -A RUNG_ARGS=(
    [thinglow-hit]="--k $K --ld $LD --mode hit"
    [thinglow]="--k $K --ld $LD"
    [thinglow-hi]="--k $KHI --ld $LD"
    [thinglow-ctl]="--k 0 --ld $LD"
)
for r in "${ORDER[@]}"; do
    live=1; [[ "$r" == thinglow-ctl ]] && live=0
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "$live"
    echo "  swaps.$r: 93 modules, $(( live * 10 )) patched, spirv-val (vulkan1.4) clean"
done
for pair in "thinglow-hit thinglow" "thinglow thinglow-hi" \
            "thinglow-hit thinglow-hi"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 differ between every pair of live rungs"
# ... and every live rung differs from the ear glow it stacks on, on all ten.
for r in "${LIVE[@]}"; do
    d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$r/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs from the base on only $d of 10" >&2; exit 1; }
done

# --- 3. coverage census, from the REPORTS ----------------------------------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of the argv above: a rung that silently changed
# its flags, its band, its gate or its match field must fail even if the
# request changed with it.
WANT = {
 'thinglow-hit': dict(mode='hit',  k=0.5, ld=0.002),
 'thinglow':     dict(mode='glow', k=0.5, ld=0.002),
 'thinglow-hi':  dict(mode='glow', k=1.0, ld=0.002),
 'thinglow-ctl': dict(mode='control', k=0.0, ld=None),
}
bad, CENSUS = [], None
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = writes = skipped = 0
    for f in sorted(glob.glob(os.path.join(d, '*.thinglow.report.json'))):
        rep = json.load(open(f)); q = rep['thinglow']; mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['mode'] != want['mode']:
            bad.append((r, rep['module'], f"mode {q['mode']} != {want['mode']}"))
        if want['mode'] == 'control':
            if q.get('emitted') != 0:
                bad.append((r, rep['module'], 'the CONTROL emitted instructions'))
            continue
        if q['k'] != want['k'] or q['ld_m'] != want['ld']:
            bad.append((r, rep['module'], f"k/ld {q['k']}/{q['ld_m']}"))
        writes += len(q['writes_added'])
        for s in q['writes_skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
            skipped += 1
        if q['ray_flags_b'] != 545 or q['ray_flags_a'] != 517 \
                or q['ray_flags_c'] != 517:
            bad.append((r, rep['module'], f"flags A/B/C {q['ray_flags_a']}/"
                                          f"{q['ray_flags_b']}/{q['ray_flags_c']}"))
        if q['tmin'] != 0.0003 or q['tmax'] != 0.025:
            bad.append((r, rep['module'], f"band {q['tmin']}/{q['tmax']}"))
        if q['m_max'] != 0.1 or q['r_min'] != 0.5:
            bad.append((r, rep['module'], f"m/r gate {q['m_max']}/{q['r_min']}"))
        if q['excluded_classes'] != [1, 4, 8]:
            bad.append((r, rep['module'], f"excluded {q['excluded_classes']} "
                                          f"-- class 1 missing would paint "
                                          f"over the ear glow"))
        if not (q['gate_not_skin'] and q['gate_metallic'] and q['gate_roughness']
                and q['albedo_tinted']):
            bad.append((r, rep['module'], 'a gate term or the albedo tint is off'))
        if q['gate_terms'] != 7:
            bad.append((r, rep['module'], f"{q['gate_terms']} gate terms, want 7"))
        if q['push_c'] != 0.001 or q['tmin_c'] != 0.001:
            bad.append((r, rep['module'], f"C push/tmin {q['push_c']}/{q['tmin_c']}"))
        if q['sun_mask_arms'] not in ([0, 39], [39, 0]):
            bad.append((r, rep['module'], f"sun shadow-ray mask arms {q['sun_mask_arms']}"))
        if q['tmax_c_value'] != 10000:
            bad.append((r, rep['module'], f"C tmax {q['tmax_c_value']}, want the "
                                          f"module's own sun shadow tmax 10000"))
        if not q['vis_gate'] or q['vis_flags_cull_front'] or q['vis_inverted']:
            bad.append((r, rep['module'], 'the sun-visibility gate is absent, '
                                          'culling, or inverted'))
        if q['bracket'] != [0.999, 1.001, 0.0001]:
            bad.append((r, rep['module'], f"bracket {q['bracket']}"))
        if q['commit_a'] != 'first' or q['commit_b'] != 'closest':
            bad.append((r, rep['module'], 'commit modes wrong'))
        if q['match_getter'] != 'OpRayQueryGetIntersectionInstanceIdKHR' \
                or q['match_op'] != 'OpIEqual':
            bad.append((r, rep['module'], 'the instance match is absent or inverted'))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if q['gate_mask'] != 39:
            bad.append((r, rep['module'], f"gate cull mask {q['gate_mask']}"))
        if not q['opaque_alpha_test_accepted']:
            bad.append((r, rep['module'], 'the alpha-test cost is not declared'))
        if q['stacked_on']['base_queries'] != [3, 3, 2, 1]:
            bad.append((r, rep['module'], f"stacked on {q['stacked_on']['base_queries']}"))
        if want['mode'] == 'hit' and not q['diag_scaled_by_sun_radiance']:
            bad.append((r, rep['module'], 'the -hit paint is NOT scaled by the '
                                          'sun radiance (101 sec 12.3)'))
        if q['primary_line'] >= q['nee_line']:
            bad.append((r, rep['module'], 'query A does not dominate the splice'))
        if q['material_site']['line'] >= q['nee_line']:
            bad.append((r, rep['module'], 'the material site is below the splice'))
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if want['mode'] == 'control':
        print(f'  {r:14s} 10 modules, 0 instructions emitted (identity)')
        continue
    if CENSUS is None:
        CENSUS = (writes, skipped)
    elif (writes, skipped) != CENSUS:
        bad.append((r, '-', f'painted/skipped {(writes, skipped)} != {CENSUS}'))
    print(f'  {r:14s} 10 modules, {writes} painted writes, {skipped} benign '
          f'skips, A=517 B=545 C=517, band=[{q["tmin"]}, {q["tmax"]}] m, '
          f'gate=7 terms (class!=1/4/8, m<{q["m_max"]}, r>{q["r_min"]}, '
          f'backlit, path==0), k={want["k"]}, ld={want["ld"]} m')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes ----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    ctl = r.endswith('-ctl')
    tot = dict(init=0, proceed=0, iid=0, tget=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_d = a.count('OpRayQueryGetIntersectionInstanceIdKHR')
        n_t = a.count('OpRayQueryGetIntersectionTKHR')
        n_c = a.count('OpRayQueryGetIntersectionInstanceCustomIndexKHR')
        dt = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        # The base carries 101's 3/3/2/1. This rung adds its own three
        # queries, two more InstanceId reads and one more committed T, so a
        # live rung MUST read 6/6/4/2 and the control MUST read 3/3/2/1.
        if h in PASS:
            want = (0, 0, 0, 0)
        elif ctl:
            want = (3, 3, 2, 1)
        else:
            want = (6, 6, 4, 2)
        if (n_i, n_p, n_d, n_t) != want:
            bad.append(f'{r}/{h}: init/proceed/instanceId/T = '
                       f'{(n_i, n_p, n_d, n_t)}, want {want}')
        if n_c:
            bad.append(f'{r}/{h}: {n_c} x InstanceCustomIndex -- that is the decoy field')
        if dt != 0:
            bad.append(f'{r}/{h}: OpTraceRayKHR count changed by {dt}')
        tot['init'] += n_i; tot['proceed'] += n_p; tot['iid'] += n_d; tot['tget'] += n_t
    print(f"  {r:14s} {tot['init']} Initialize, {tot['proceed']} Proceed, "
          f"{tot['iid']} committed InstanceId, {tot['tget']} committed-T, "
          f"0 added traces")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. identity, over the WHOLE set ---------------------------------------
echo "=== 5. identity control"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.thinglow-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! thinglow-ctl differs from the base on $d files" >&2; exit 1; }
echo "  thinglow-ctl: 93 of 93 byte-identical to $BASE"
for r in "${LIVE[@]}"; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs on $d files, want exactly 10" >&2; exit 1; }
done
echo "  the three live rungs: 10 of 93 differ (the 10 paintable permutations)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_thinglow.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.thinglow-hit" --base "$SRC" --mode hit --k "$K" --ld "$LD"
python3 "$VERIFY" "$MOD_DIR/swaps.thinglow"     --base "$SRC" --mode glow --k "$K"   --ld "$LD"
python3 "$VERIFY" "$MOD_DIR/swaps.thinglow-hi"  --base "$SRC" --mode glow --k "$KHI" --ld "$LD"
python3 "$VERIFY" --negative "$SRC"
python3 "$VERIFY" --control "$MOD_DIR/swaps.thinglow-ctl" --base "$SRC"

# --- 7. verifier NON-VACUITY -----------------------------------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
G=(--base "$SRC" --mode glow --k "$K" --ld "$LD")
declare -A DECOY_WHY=(
    [noc]="query C traced but never consulted -- a curtain with a wall behind it still glows"
    [cullfront]="C culls front faces: it would miss the occluder it exists to find"
    [invert]="accept when C HITS -- lights exactly the shadowed cloth"
    [noskin]="the class != 1 term dropped -- THIS ONE WOULD PAINT OVER THE EAR GLOW"
    [nometal]="the metallic < 0.1 term dropped -- chain-link and car paint join in"
    [norough]="the roughness > 0.5 term dropped -- glass and polished plastic join in"
    [noalbedo]="the albedo tint dropped -- every tarp glows white"
    [wideband]="tmax x4 (100 mm) -- a wall reads as a thin surface"
)
for dec in noc cullfront invert noskin nometal norough noalbedo wideband; do
    patch_set "$WORK/decoy/$dec" --k "$K" --ld "$LD" --decoy "$dec"
    reject "--decoy $dec (${DECOY_WHY[$dec]})" "$VERIFY" "$WORK/decoy/$dec" "${G[@]}"
    rm -rf "$WORK/decoy/$dec"
done
reject "the unpatched BASE read as a rung" "$VERIFY" "$SRC" "${G[@]}"
reject "the k=0 CONTROL read as a rung" "$VERIFY" "$MOD_DIR/swaps.thinglow-ctl" "${G[@]}"
reject "thinglow read as the -hit diagnostic" \
       "$VERIFY" "$MOD_DIR/swaps.thinglow" --base "$SRC" --mode hit --k "$K" --ld "$LD"
reject "thinglow-hit read as the glow rung" \
       "$VERIFY" "$MOD_DIR/swaps.thinglow-hit" "${G[@]}"
reject "thinglow-hi read with thinglow's k (0.5)" \
       "$VERIFY" "$MOD_DIR/swaps.thinglow-hi" "${G[@]}"
reject "thinglow read with a 1 mm mean free path" \
       "$VERIFY" "$MOD_DIR/swaps.thinglow" --base "$SRC" --mode glow --k "$K" --ld 0.001
reject "the earglow base's OWN rung read as a thinglow rung (3 queries, not 6)" \
       "$VERIFY" "$SRC" --base "$SRC" --mode glow --k 0.22 --ld "$LD"
reject "the CONTROL read as byte-different from the base" \
       "$VERIFY" --control "$MOD_DIR/swaps.thinglow" --base "$SRC"
rm -rf "$WORK/decoy"

# --- 8. the transfer, closed form, against the SHIPPED constants -----------
echo "=== 8. closed-form transfer check (numpy) against the shipped 1/ld bytes"
python3 - "$MOD_DIR" "$K" "$KHI" "$LD" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir, K, KHI, LD = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
RUNGS = {'thinglow': K, 'thinglow-hi': KHI}
bad = []
for rung, k in RUNGS.items():
    f = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + rung,
                                      '*.rgs_reference_main.spv')))[0]
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    vals = []
    for m in re.finditer(r'OpConstant %float ([0-9.e+-]+)\s*$', asm, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    c = [v for v in vals if abs(v - 1.0 / LD) <= 1e-3 * (1.0 / LD)]
    if not c:
        bad.append(f'{rung}: the 1/ld rate {1.0/LD} is not in the shipped bytes')
        rate = 1.0 / LD
    else:
        rate = c[0]
    if not [v for v in vals if abs(v - k) <= 1e-6]:
        bad.append(f'{rung}: k={k} is not in the shipped bytes')
    t = np.array([0.3, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 25.0]) * 1e-3
    T = np.exp(-t * rate)
    print(f'  {rung} (rate read back from the .spv: {rate:.1f} /m, '
          f'ld={1.0/rate*1e3:.2f} mm): k={k}')
    print('     t(mm)     T        k*T     albedo 0.8 -> add')
    for tt, TT in zip(t, T):
        print(f'   {tt*1e3:6.1f}  {TT:9.6f}  {k*TT:9.6f}  {k*TT*0.64:9.6f}')
    # The SHAPE claims 105 sec 5 makes, checked rather than asserted.
    if not (0.40 <= T[0] <= 0.99):
        bad.append(f'{rung}: T at 0.3 mm is {T[0]:.3f} -- the thinnest sheet '
                   f'is meant to be bright, not saturated')
    if T[-1] > 1e-4:
        bad.append(f'{rung}: T at 25 mm is {T[-1]:.2e} -- the band edge must '
                   f'be dark or the tmax cut would be a visible step')
    ratio = T[1] / T[3]      # 1 mm vs 3 mm
    if not (2.0 <= ratio <= 4.0):
        bad.append(f'{rung}: the 1 mm / 3 mm contrast is {ratio:.2f}x')
    if not np.all(np.diff(T) < 0):
        bad.append(f'{rung}: T is not monotonically decreasing in t')
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 9. MANIFEST ------------------------------------------------------------
echo "=== 9. MANIFEST provenance"
src_ser=$(head -1 "$SRC/MANIFEST.txt")
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    {
      echo "$r (base=$BASE) backlit thin-surface translucency, handoff/105"
      echo "# STACKED on the ear glow: the base's 3/3/2/1 ray-query ops are"
      echo "# untouched and this rung's gate begins with class != 1, so skin"
      echo "# pixels are bit-identical to $BASE."
      echo "# query A: flags 517, +/-0.1% bracket on |P|, committed InstanceId"
      echo "# query B: flags 545, tmin 0.0003 m, tmax 0.025 m, committed closest"
      echo "# query C: flags 517, origin P+(t_B+1mm)*S, tmin 0.001, sun tmax"
      echo "# accept <=> gate AND A committed AND B committed AND"
      echo "#            A.InstanceId == B.InstanceId AND C MISSED"
      echo "# gate: class != 1/4/8, metallic < 0.1, roughness > 0.5, backlit,"
      echo "#       path counter == 0"
      if [[ "$r" == thinglow-ctl ]]; then
        echo "# k=0: byte-identical to the base. The A/B control."
      elif [[ "$r" == thinglow-hit ]]; then
        echo "# DIAGNOSTIC: committed thickness as a ramp, BLUE 0.3 mm ->"
        echo "# GREEN 25 mm, RED where B committed but C was occluded. No"
        echo "# transfer, no albedo, no k; scaled by the sun radiance."
      else
        echo "# transfer: k * exp(-t/0.002 m) * albedo^2 * sunRadiance, NMin 100"
      fi
      echo "# ALPHA-TESTED GEOMETRY IS MIS-COMMITTED (98 sec 2.3, 105 sec 6):"
      echo "# flags keep Opaque, so foliage cards read the card GAP as t."
      echo "# src: $src_ser"
      grep -E '^# (src_ser|ser_sha|ptq_sha)' "$SRC/MANIFEST.txt" 2>/dev/null || true
      echo "# UNSHOT. Read handoff/105 sec 9 BEFORE the screen: the frame must"
      echo "# be BACKLIT and must contain a CURTAIN or plastic sheet (not only"
      echo "# a market tarp: 94 sec 14.2a measured those at m >= 0.5, which"
      echo "# this rung's metallic gate REJECTS) and a SKIN control."
    } > "$dest/MANIFEST.txt"
done
echo "  ${#ORDER[@]} MANIFESTs written, provenance carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {
    # -print0/sort -z/xargs -0: the repo path contains a space, and
    # `ls | xargs cat` would hash NOTHING (e3b0c442..., the empty string).
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
        # NEW names only. If a directory of this name already exists it was
        # not created by this script -- refuse rather than delete it.
        if [[ -e "$park" && ! -f "$park/.thinglow" ]]; then
            echo "  !! $park exists and was not parked by build_thinglow.sh -- refusing" >&2
            exit 1
        fi
        rm -rf "$park"; mkdir -p "$park"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        : > "$park/.thinglow"
        n=0
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! park differs: $f" >&2; exit 1; }
            n=$((n+1))
        done
        echo "  parked -> $park ($n modules, cmp-verbatim against the build)"
    done
fi

echo
echo "select with skinspec=thinglow-hit / thinglow / thinglow-hi"
echo "control: thinglow-ctl (byte-identical to the base)"
echo "contract: ser=class, shadowset=full-shadow, ptq unchanged; RR OFF;"
echo "          reference PT reach (photo mode, let it converge); the sun LOW"
echo "          and BEHIND a CURTAIN / tent / plastic sheet, the camera on the"
echo "          shaded side, and a FACE in the same frame as the skin control."
echo "          Read handoff/105 sec 9 BEFORE the screen and shoot"
echo "          thinglow-hit in the SAME frame as thinglow."
