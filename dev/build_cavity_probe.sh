#!/usr/bin/env bash
# handoff/93 sec 5 -- the DEBUG PAINT that settles whether the 64-byte light
# struct's offset-12 HIGH half is a SOURCE RADIUS or a cull/fade margin.
#
# 93 established that k*mix(sa_ratio,1,saturate(1-t/2mm)) (88 sec 5c) is not
# buildable at either spliced local-light NEE site: site A shades every light
# as a POINT (analytic 1/d^2, no pdf at all) and site B's only 1/pdf is a
# discrete RIS light-SELECTION weight in units of 1/luminance. The single open
# question is that one field, which has exactly ONE use in the whole module --
# the cull test d^2 > (U + R)^2 -- so it cannot be identified statically.
#
# These rungs paint it. The light's own radiance triple is replaced by a
# monotonic encoding of the struct fields, so the engine's 1/d^2 * spot * BRDF
# * visibility weighting is untouched and the frame still reads as a lit frame;
# the probe is read by HUE and CHANNEL RATIO, both invariant to that common
# weighting and therefore also to the base rung's cavity factor.
#
# Base: the -cone2allgf rung, i.e. 90's FIXED gate on the plain standing base.
# The paint's own gate is class-1 skin AND path_counter == 0, re-derived by
# find_path_counter, never E.find_bounce_counter (90 sec 1).
#
# Reach: rgs_reference_main ONLY. All 77 compute and all 4 ReSTIR-GI modules
# are byte-identical to the base and are cmp-asserted so.
#
# THESE ARE DIAGNOSTIC RUNGS. They deliberately destroy local-light colour.
# Never ship one, never judge a look from one.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi-cone2allgf"
GI="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi-cone2allgf"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/probe_12"
PY="$MOD_DIR/dev/patch_cavity_probe.py"
VERIFY="$MOD_DIR/dev/verify_cavity_probe.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# rung -> "mode,rscale,uscale,sscale"   ONE VARIABLE PER STEP:
#   probeu   -> probeu10 : USCALE only, 0.5 -> 0.05 (a 10x gain on the unknown,
#                          so centimetre-scale values are still readable)
#   probeu   -> probe44  : the OTHER packed half2 (offset 44), with the same
#                          ratio anchor kept in blue
RUNG_NAMES=("$BASE_NAME-probeu"
            "$BASE_NAME-probeu10"
            "$BASE_NAME-probe44")
RUNG_SPECS=("u,20,0.5,2"
            "u,20,0.05,2"
            "44,20,0.5,2")

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt -- run dev/build_cavity4.sh first" >&2; exit 1; }

# --- base provenance -------------------------------------------------------
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

# --- NEGATIVE CONTROL: the base carries no paint ---------------------------
python3 "$VERIFY" --negative "$GI"
echo "  negative control: CLEAN 12/12 (no paint group in the base)"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${REFS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 dest $2 mode $3 rscale $4 uscale $5 sscale $6 gain
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" \
        CB_M="$2" CB_R="$3" CB_U="$4" CB_S="$5" CB_G="$6" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" --mode "$CB_M" \
                --rscale "$CB_R" --uscale "$CB_U" --sscale "$CB_S" \
                --gain "$CB_G" --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
}

# --- gain=0 IDENTITY CONTROL: every emitted byte is ours -------------------
K0="$MOD_DIR/dev/disasm/probe_k0_all"
rm -rf "$K0"; mkdir -p "$K0"
patch_all "$K0" u 20 0.5 2 0
nk=0
for f in "$K0"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || {
        echo "gain=0 rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
    nk=$((nk+1))
done
(( nk == 12 )) || { echo "gain=0 control produced $nk modules, expected 12" >&2; exit 1; }
echo "  gain=0 identity control: $nk/12 byte-identical to base"
rm -rf "$K0"

build_rung() {  # $1 name  $2 "mode,rscale,uscale,sscale"
    local name="$1" spec="$2"
    IFS=, read -r mode rscale uscale sscale <<< "$spec"
    local dest="$MOD_DIR/swaps.gi.${1#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    echo "== $name  (mode=$mode rscale=$rscale uscale=$uscale sscale=$sscale)"
    patch_all "$dest" "$mode" "$rscale" "$uscale" "$sscale" 1

    python3 - "$dest" << 'PYS'
import glob, json, os, sys
d = sys.argv[1]
mods, bad = 0, []
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))['probe']
    h = os.path.basename(f).split('.')[0]
    if r['n_sites'] != 1:
        bad.append(f"{h}: {r['n_sites']} sites")
    if r['n_rewrites'] != 3:
        bad.append(f"{h}: {r['n_rewrites']} rewrites")
    if len(r['radiance_extracts']) != 3 or len(set(r['radiance_extracts'])) != 3:
        bad.append(f"{h}: radiance extracts {r['radiance_extracts']}")
    mods += 1
if mods != 12 or bad:
    print(f'SITE COVERAGE FAILED: {mods} modules\n  ' + '\n  '.join(bad))
    sys.exit(1)
print(f'  site coverage: {mods}/12 modules, 1 site x 3 operand rewrites each')
PYS

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
            && { echo "$name: $h identical to base -- paint emitted nothing" >&2; exit 1; }
    done

    local nval=0
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
        nval=$((nval+1))
    done
    (( nval == 93 )) || { echo "$name: spirv-val ran on $nval, expected 93" >&2; exit 1; }
    echo "  spirv-val: $nval/93 clean"

    python3 "$VERIFY" "$dest" "$GI" --mode "$mode" --rscale "$rscale" \
        --uscale "$uscale" --sscale "$sscale"

    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
        grep -q "$tag" "$dest/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
    done
    {
        echo "# DIAGNOSTIC DEBUG PAINT (handoff/93 sec 5). NOT A LOOK RUNG."
        echo "# Replaces the LOCAL light's radiance triple with an encoding of"
        echo "# its own 64-byte struct fields, on lit class-1 skin at the"
        echo "# primary hit only (gate: class==1 AND path_counter==0)."
        echo "# mode=$mode rscale=$rscale uscale=$uscale sscale=$sscale"
        if [[ "$mode" == u ]]; then
        echo "#   R = saturate(range        / $rscale)   offset 12 LOW  (KNOWN)"
        echo "#   G = saturate(unknown      / $uscale)   offset 12 HIGH (the question)"
        else
        echo "#   R = saturate(spot_scale   / $sscale)   offset 44 LOW"
        echo "#   G = saturate(spot_bias)                offset 44 HIGH"
        fi
        echo "#   B = saturate(unknown / max(range, 1e-4))  the scale-free ratio"
        echo "# Read: if the UNKNOWN is a SOURCE RADIUS, G and B vary by orders"
        echo "# of magnitude between a small practical and a big panel. If it is"
        echo "# a cull/fade margin proportional to range, B is the SAME on every"
        echo "# fixture. See handoff/93 sec 10 for the full read-out table."
        echo "# Gate false -> OpSelect returns the ORIGINAL id -> bit-identical."
        echo "# Sun, compute (77) and ReSTIR-GI (4) untouched and cmp-asserted."
        echo "# DO NOT SHIP. DO NOT JUDGE A LOOK FROM THIS."
    } > "$dest/README.txt"
    rm -f "$dest"/*.spvasm
    echo "  built $dest"
}

for i in "${!RUNG_NAMES[@]}"; do
    build_rung "${RUNG_NAMES[$i]}" "${RUNG_SPECS[$i]}"
done

# --- VERIFIER NON-VACUITY: it must REJECT, not just accept -----------------
echo "== verifier non-vacuity"
PU="$MOD_DIR/swaps.gi.${RUNG_NAMES[0]#gi-}"
P10="$MOD_DIR/swaps.gi.${RUNG_NAMES[1]#gi-}"
P44="$MOD_DIR/swaps.gi.${RUNG_NAMES[2]#gi-}"
nv_fail() {  # $1 label, rest: args that MUST fail
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "NON-VACUITY BROKEN: verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejects $label"
}
nv_fail "wrong uscale (0.5 vs 0.05)"  "$P10" "$GI" --mode u --rscale 20 --uscale 0.5
nv_fail "wrong rscale (2 vs 20)"      "$PU"  "$GI" --mode u --rscale 2  --uscale 0.5
nv_fail "wrong mode (44 on a u rung)" "$PU"  "$GI" --mode 44 --sscale 2
nv_fail "wrong mode (u on a 44 rung)" "$P44" "$GI" --mode u --rscale 20 --uscale 0.5
nv_fail "wrong sscale (0.5 vs 2)"     "$P44" "$GI" --mode 44 --sscale 0.5
nv_fail "the unpatched base"          "$GI"  "$GI" --mode u --rscale 20 --uscale 0.5
if python3 "$VERIFY" --negative "$PU" >/dev/null 2>&1; then
    echo "NON-VACUITY BROKEN: negative control ACCEPTED a painted rung" >&2; exit 1
fi
echo "  rejects a painted rung under --negative"

# --- standing rungs still verify ------------------------------------------
echo "== standing rungs"
for r in real-gloss-bleedn-oilh real-gloss-bleedn-oilh-deep; do
    python3 "$MOD_DIR/dev/verify_bleed_norm.py" "$MOD_DIR/swaps.skin.$r" >/dev/null \
        || { echo "verify_bleed_norm.py FAILED on swaps.skin.$r" >&2; exit 1; }
    echo "  verify_bleed_norm.py PASS  swaps.skin.$r"
done
"$MOD_DIR/dev/verify_gi_ladder.sh" >/dev/null \
    || { echo "verify_gi_ladder.sh FAILED" >&2; exit 1; }
echo "  verify_gi_ladder.sh PASS"

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
    echo "NOW RUN: make install   (selector rows -- NOT added by this script)"
fi
echo "OK -- ${#RUNG_NAMES[@]} DIAGNOSTIC rungs. Never ship one."
