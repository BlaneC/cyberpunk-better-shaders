#!/usr/bin/env bash
# handoff/95 -- participating media on the SUN SHADOW RAY, built on the LIVE
# standing selection so that fog-vs-no-fog is ONE variable against what the
# user is actually looking at.
#
# Reach: rgs_reference_main ONLY (reference / photo-mode PT). All 77 compute
# and all 4 ReSTIR-GI modules are byte-identical to the base and cmp-asserted.
#
# Read 95 sec 0 before judging anything: this term produces NO light shafts
# and NO distance-based aerial perspective -- both need in-scattering along a
# camera ray, which a multiply on a surface term cannot do and which 53's
# multiplicative-only constraint forbids. What it produces is sun-elevation
# and height dependent extinction and reddening, at EVERY bounce, for zero
# rays.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi-cone2all"
GI="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cone2all"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/volsun12"
PY="$MOD_DIR/dev/patch_volsun.py"
VERIFY="$MOD_DIR/dev/verify_volsun.py"
MODEL="$MOD_DIR/dev/volsun_model.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# rung -> "a,H,y0,p,up,height"   ONE VARIABLE PER STEP:
#   base      -> -fog     : the ship candidate, A=0.25
#   -fog      -> -foghi   : STRENGTH alone, A 0.25 -> 0.50
#   -fog      -> -fogx    : STRENGTH, the "is it working" diagnostic (33's
#                           ladder convention), A=1.00
#   -fog      -> -fogn    : the TINT axis alone, p 1 -> 0 (neutral T)
#   -fog      -> -fogcam  : the HEIGHT REFERENCE alone, absolute -> camera-
#                           relative. 95 F3's discriminator for cbv slot 56.
#   -fog      -> -fogy    : the UP AXIS alone, 2 -> 1. THE ONE-FRAME
#                           FALSIFIER (95 F1); never ship it.
RUNG_NAMES=("$BASE_NAME-fog" "$BASE_NAME-foghi" "$BASE_NAME-fogx"
            "$BASE_NAME-fogn" "$BASE_NAME-fogcam" "$BASE_NAME-fogy")
RUNG_SPECS=("0.25,120,20,1,2,abs" "0.50,120,20,1,2,abs" "1.00,120,20,1,2,abs"
            "0.25,120,20,0,2,abs" "0.25,120,20,1,2,cam" "0.25,120,20,1,1,abs")

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt" >&2; exit 1; }

# --- base provenance: the repo dir must BE the parked standing rung --------
if [[ -d "$PARK_BASE" ]]; then
    for f in "$GI"/*.spv; do
        cmp -s "$f" "$PARK_BASE/$(basename "$f")" || {
            echo "base drift: $(basename "$f") differs from $PARK_BASE" >&2; exit 1; }
    done
    echo "  base provenance: $(basename "$GI") == skin.set/$BASE_NAME (93/93)"
else
    echo "  base provenance: $PARK_BASE not parked -- repo dir taken as base" >&2
fi

mapfile -t REFS < <(cd "$GI" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#REFS[@]} == 12 )) || { echo "base has ${#REFS[@]} rgs_reference_main, expected 12" >&2; exit 1; }
NDX=$(ls "$GI"/*.dxil.spv | wc -l)
(( NDX == 77 )) || { echo "base has $NDX dxil, expected 77" >&2; exit 1; }
NRI=$(ls "$GI"/*.rgs_restirgi_*.spv | wc -l)
(( NRI == 4 )) || { echo "base has $NRI restirgi, expected 4" >&2; exit 1; }

# --- NEGATIVE CONTROL: the unpatched base carries none of the splice -------
python3 "$VERIFY" --negative "$GI"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${REFS[@]}"; do
    spirv-dis --no-color "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 dest  $2 a  $3 H  $4 y0  $5 p  $6 up  $7 abs|cam
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_A="$2" \
        CB_H="$3" CB_Y="$4" CB_S="$5" CB_U="$6" CB_M="$7" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" --a "$CB_A" --h "$CB_H" \
                --y0 "$CB_Y" --p "$CB_S" --up "$CB_U" --height "$CB_M" \
                --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
}

# --- sigma = 0 IDENTITY CONTROL -------------------------------------------
# Every detector still runs; the emission is skipped. Proves the dis->as round
# trip AND that every emitted byte in the real rungs is ours. Run in BOTH
# height modes, because they are two different emissions.
for mode in abs cam; do
    A0="$MOD_DIR/dev/disasm/volsun_a0_$mode"
    rm -rf "$A0"; mkdir -p "$A0"
    patch_all "$A0" 0 120 20 1 2 "$mode"
    n0=0
    for f in "$A0"/*.spv; do
        cmp -s "$f" "$GI/$(basename "$f")" || {
            echo "a=0 ($mode) rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
        n0=$((n0+1))
    done
    (( n0 == 12 )) || { echo "a=0 control produced $n0 modules, expected 12" >&2; exit 1; }
    echo "  sigma=0 identity control ($mode): $n0/12 byte-identical to base"
    rm -rf "$A0"
done

build_rung() {  # $1 name  $2 "a,H,y0,p,up,height"
    local name="$1" spec="$2"
    IFS=, read -r a H y0 p up height <<< "$spec"
    local dest="$MOD_DIR/swaps.gi.${name#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    echo "== $name  (a=$a H=${H}m y0=${y0}m p=$p up=$up height=$height)"
    patch_all "$dest" "$a" "$H" "$y0" "$p" "$up" "$height"

    # --- HARD GATE: 12 modules x 3 sun sites, zero rays, ungated ----------
    python3 - "$dest" "$up" "$height" << 'PYS'
import glob, json, os, sys
d, up, height = sys.argv[1], int(sys.argv[2]), sys.argv[3]
tot, mods, bad = 0, 0, []
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))['volsun']
    h = os.path.basename(f).split('.')[0]
    if r['n_sites'] != 3:
        bad.append(f"{h}: {r['n_sites']} sun sites")
    if r['traces_added'] != 0:
        bad.append(f"{h}: {r['traces_added']} rays added -- must be 0")
    if r['gated']:
        bad.append(f"{h}: gated -- this term runs at EVERY bounce")
    if not r.get('dominates_all_sites'):
        bad.append(f"{h}: inputs do not dominate every site")
    if r['up'] != up or r['height'] != height:
        bad.append(f"{h}: up/height {r['up']}/{r['height']} != {up}/{height}")
    if any(s['uses_redirected'] < 1 for s in r['sites']):
        bad.append(f"{h}: a sun product had no consumer to redirect")
    tot += r['n_sites']; mods += 1
if mods != 12 or tot != 36 or bad:
    print(f'SITE COVERAGE FAILED: {mods} modules, {tot} sun sites\n  '
          + '\n  '.join(bad))
    sys.exit(1)
print(f'  site coverage: {mods}/12 modules, {tot}/36 sun sites, 0 rays added')
PYS

    # --- verbatim halves: 77 dxil + 4 restirgi, cmp-asserted --------------
    cp -pf "$GI"/*.dxil.spv "$dest/"
    cp -pf "$GI"/*.rgs_restirgi_*.spv "$dest/"
    local nv=0
    for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
        nv=$((nv+1))
    done
    (( nv == 81 )) || { echo "$name: cmp-asserted $nv verbatim, expected 81" >&2; exit 1; }
    for h in "${REFS[@]}"; do
        cmp -s "$GI/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "$name: $h identical to base -- splice emitted nothing" >&2; exit 1; }
    done

    # --- spirv-val on every emitted module ---------------------------------
    local nval=0
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
        nval=$((nval+1))
    done
    (( nval == 93 )) || { echo "$name: spirv-val ran on $nval, expected 93" >&2; exit 1; }
    echo "  spirv-val: $nval/93 clean"

    # --- re-read the EMITTED binaries (39 sec 3.4) -------------------------
    python3 "$VERIFY" "$dest" "$GI" --a "$a" --h "$H" --y0 "$y0" --p "$p" \
        --up "$up" --height "$height"

    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12([^)]*)/ref=12(12 volsun a=$a H=${H}m y0=${y0}m p=$p up=$up height=$height)/" \
        -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
        grep -q "$tag" "$dest/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
    done
    {
        echo "# participating media on the SUN SHADOW RAY (handoff/95),"
        echo "# reference/photo-mode PT ONLY. Zero rays, zero PRNG draws."
        echo "#   col   = exp(-(h-${y0})/${H})        h = world height, up axis $up"
        echo "#   am    = max(1/max(L_up,0.02) - 1, 0)   airmass EXCESS over zenith"
        echo "#   T_c   = exp(-min(A_c*col*am, 30))      A=$a, sigma ~ lambda^-$p"
        echo "#   direct sun *= T_c, at EVERY bounce (95 sec 6 -- the OPPOSITE"
        echo "#   of 88's bounce-0 cavity gate, and the doc says why)."
        echo "# T == 1.0 EXACTLY at zenith sun, and T <= 1 everywhere, so 53's"
        echo "# multiplicative-only constraint holds by construction."
        case "$height" in
        cam) echo "# HEIGHT REFERENCE = CAMERA-RELATIVE: the fog layer follows the"
             echo "# camera vertically. This is the DISCRIMINATOR rung for 95 F3,"
             echo "# not a look candidate." ;;
        *)   echo "# HEIGHT REFERENCE = ABSOLUTE world height via cbv slot 56 (the"
             echo "# camera world position). y0 and A are degenerate: a wrong y0"
             echo "# rescales the strength and CANNOT change the gradient." ;;
        esac
        (( up == 2 )) || {
        echo "# !! UP AXIS $up: this is the ONE-FRAME FALSIFIER for 95 F1."
        echo "# !! If Z-up is right this rung is visibly wrong. DO NOT SHIP IT." ; }
        echo "# NO light shafts and NO distance aerial perspective -- 95 sec 0."
        echo "# A/B against $BASE_NAME; NOT working until the screen says so."
    } > "$dest/README.txt"
    rm -f "$dest"/*.spvasm
    echo "  built $dest"
}

for i in "${!RUNG_NAMES[@]}"; do
    build_rung "${RUNG_NAMES[$i]}" "${RUNG_SPECS[$i]}"
done

# --- the axis rungs must actually differ from the ship candidate -----------
echo "== rung-to-rung separation"
SHIP="$MOD_DIR/swaps.gi.${RUNG_NAMES[0]#gi-}"
for other in fogn fogcam fogy foghi fogx; do
    d="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}-$other"
    nd=0
    for h in "${REFS[@]}"; do
        cmp -s "$SHIP/$h.rgs_reference_main.spv" "$d/$h.rgs_reference_main.spv" || nd=$((nd+1))
    done
    (( nd == 12 )) || { echo "-$other differs from -fog in only $nd/12 modules" >&2; exit 1; }
    ndx=0
    for f in "$d"/*.dxil.spv "$d"/*.rgs_restirgi_*.spv; do
        cmp -s "$SHIP/$(basename "$f")" "$f" || ndx=$((ndx+1))
    done
    (( ndx == 0 )) || { echo "-$other differs from -fog in $ndx compute/GI modules" >&2; exit 1; }
    echo "  -$other vs -fog: 12/12 reference modules differ, 0/81 others"
done

# --- NON-VACUITY: a verifier that cannot FAIL proves nothing (GOTCHAS 12) --
# Every line below claims something FALSE about the shipped bytes and MUST be
# rejected. The --up and --p lines are the two the brief named explicitly.
echo "== verifier non-vacuity (each line must FAIL)"
FOG="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}-fog"
FOGN="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}-fogn"
FOGY="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}-fogy"
FOGCAM="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}-fogcam"
must_fail() {  # $1 label, rest: verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "NON-VACUITY BROKEN: verifier ACCEPTED a false claim: $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
must_fail "-fog claimed A=0.50 (strength)"   "$FOG" "$GI" --a 0.50 --h 120 --y0 20 --p 1 --up 2 --height abs
must_fail "-fog claimed p=0 (TINT AXIS)"     "$FOG" "$GI" --a 0.25 --h 120 --y0 20 --p 0 --up 2 --height abs
must_fail "-fog claimed H=1000m (gradient)"  "$FOG" "$GI" --a 0.25 --h 1000 --y0 20 --p 1 --up 2 --height abs
must_fail "-fog claimed y0=0m"               "$FOG" "$GI" --a 0.25 --h 120 --y0 0 --p 1 --up 2 --height abs
must_fail "-fog claimed up=1 (UP FLAG)"      "$FOG" "$GI" --a 0.25 --h 120 --y0 20 --p 1 --up 1 --height abs
must_fail "-fog claimed height=cam"          "$FOG" "$GI" --a 0.25 --h 120 --y0 20 --p 1 --up 2 --height cam
must_fail "-fogn claimed p=1 (TINT AXIS)"    "$FOGN" "$GI" --a 0.25 --h 120 --y0 20 --p 1 --up 2 --height abs
must_fail "-fogy claimed up=2 (UP FLAG)"     "$FOGY" "$GI" --a 0.25 --h 120 --y0 20 --p 1 --up 2 --height abs
must_fail "-fogcam claimed height=abs"       "$FOGCAM" "$GI" --a 0.25 --h 120 --y0 20 --p 1 --up 2 --height abs
must_fail "-fog claimed UNPATCHED (negative)" --negative "$FOG"

# --- the closed-form table the doc quotes, regenerated from the model ------
echo "== transmittance table (regenerated)"
for spec in "0.25 -fog" "0.50 -foghi" "1.00 -fogx"; do
    set -- $spec
    echo "  A=$1  ($2)"
    python3 "$MODEL" --a "$1" --h 120 --y0 20 --p 1 --table | tail -8
done

# --- standing rungs still verify (nothing here touched their bytes) -------
echo "== standing rungs"
for r in real-gloss-bleedn-oilh real-gloss-bleedn-oilh-deep; do
    python3 "$MOD_DIR/dev/verify_bleed_norm.py" "$MOD_DIR/swaps.skin.$r" >/dev/null \
        || { echo "verify_bleed_norm.py FAILED on swaps.skin.$r" >&2; exit 1; }
    echo "  verify_bleed_norm.py PASS  swaps.skin.$r"
done
"$MOD_DIR/dev/verify_gi_ladder.sh" >/dev/null \
    || { echo "verify_gi_ladder.sh FAILED" >&2; exit 1; }
echo "  verify_gi_ladder.sh PASS  (the 72 ladder, parked)"

if (( DO_INSTALL )); then
    mkdir -p "$INSTALL_DIR/skin.set"
    for name in "${RUNG_NAMES[@]}"; do
        d="$MOD_DIR/swaps.gi.${name#gi-}"
        rm -rf "$INSTALL_DIR/skin.set/$name"
        cp -a "$d" "$INSTALL_DIR/skin.set/$name"
        n=$(ls "$INSTALL_DIR/skin.set/$name"/*.spv | wc -l)
        (( n == 93 )) || { echo "parked $name with $n modules, expected 93" >&2; exit 1; }
        echo "  parked skin.set/$name ($n modules)"
    done
    echo "NOTE: no init.lua selector row exists for these rungs. init.lua:288"
    echo "coerces an unknown skinspec to off -- a SILENT no-op. Add the rows"
    echo "deliberately, and remember make install carries 82/84/90's undeployed"
    echo "changes with it."
fi
echo "OK -- ${#RUNG_NAMES[@]} rungs. Nothing is working until the screen says so."
