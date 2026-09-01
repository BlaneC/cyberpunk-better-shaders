#!/usr/bin/env bash
# handoff/88 -- cavity contact shadow v2: the cosine-weighted micro-occlusion
# cone, on ALL TWELVE reference raygens.
#
# What changed against 85's build (dev/build_cavity.sh), and why:
#   * PASS=() is gone. 85 shipped 40c6faab52a13874 and ab7f1822eeb0331b
#     byte-verbatim because its detector anchored on the `& ~31 == 160` class
#     compare, which those two (the SER permutations) fold away. On
#     2026-09-01 09:16 the game dispatched 40c6faab52a13874 and the "k=1.0"
#     capture contained no cavity code at all. patch_cavity2 anchors on the
#     bindless material fetch instead and reaches 12/12.
#   * up to four taps per sample, cosine-weighted, with a distance ramp.
#   * tmin 0.5mm -> 0.1mm.
#
# Reach is unchanged: rgs_reference_main ONLY, i.e. the reference/photo-mode
# path tracer. All 77 compute and all 4 ReSTIR-GI modules are byte-identical
# to the base and are cmp-asserted so. Judge it in photo mode or not at all.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi"
GI="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/cavity12"
PY="$MOD_DIR/dev/patch_cavity2.py"
VERIFY="$MOD_DIR/dev/verify_cavity2.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# rung -> "k,tmax,taps,theta"   ONE VARIABLE PER STEP (88 sec 8):
#   cone1 -> cone2 : + the horizon tap
#   cone2 -> cone4 : + the two lateral taps
#   cone4 -> cone4w: theta 12 -> 25
#   cone2 -> cone2w: theta 12 -> 25          (added 2026-09-01, 88 sec 2c)
# cone2w exists because the 10:3x ladder confounded the two axes: cone4w
# differs from cone2 in BOTH the lateral taps AND the angle, and cone4->cone4w
# measured at 1.55x its own shadowed-skin noise floor. cone2w is the only rung
# that isolates the angle, and it costs exactly what cone2 costs.
#   cone2  -> cone2all: SCOPE, sun-only -> every direct light
# cone2all is the cost/benefit A/B the user asked for. It is the SAME cone as
# cone2 -- same k, tmax, taps, theta -- spliced additionally at the two
# local-light NEE sites, so the pair isolates SCOPE and nothing else. One of
# those sites is inside the light loop, so its added ray count scales with the
# visible light count: this rung is the one that can actually cost something.
RUNG_NAMES=(gi-50b-bleed-oil-sheen-deep-clothhi-cone1
            gi-50b-bleed-oil-sheen-deep-clothhi-cone2
            gi-50b-bleed-oil-sheen-deep-clothhi-cone2w
            gi-50b-bleed-oil-sheen-deep-clothhi-cone2all
            gi-50b-bleed-oil-sheen-deep-clothhi-cone4
            gi-50b-bleed-oil-sheen-deep-clothhi-cone4w)
#   cone2all -> cone2all{20,35,50}: k_local, the LOCAL-light strength alone.
# 88 sec 5c. cone2all removes k=0.85 of every local light's whole term; an area
# light subtends tens of degrees while the 12deg cone covers only part of it,
# so that over-darkens by roughly the source's solid angle. These three move
# k_local ONLY -- the sun stays at 0.85 in all of them, so the sun rung's
# verdict is not re-opened.
RUNG_NAMES+=(gi-50b-bleed-oil-sheen-deep-clothhi-cone2all20
             gi-50b-bleed-oil-sheen-deep-clothhi-cone2all35
             gi-50b-bleed-oil-sheen-deep-clothhi-cone2all50)
RUNG_SPECS=("0.85,0.006,1,12,sun" "0.85,0.006,2,12,sun" "0.85,0.006,2,25,sun"
            "0.85,0.006,2,12,all"
            "0.85,0.006,4,12,sun" "0.85,0.006,4,25,sun"
            "0.85,0.006,2,12,all,0.20" "0.85,0.006,2,12,all,0.35"
            "0.85,0.006,2,12,all,0.50")

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt" >&2; exit 1; }

# --- base provenance: the repo dir must BE the parked standing rung ---------
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

# --- NEGATIVE CONTROL: the unpatched base carries none of the splice --------
python3 "$VERIFY" --negative "$GI"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${REFS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 dest $2 k $3 tmax $4 taps $5 theta $6 ""|--all-lights $7 k_local
    local kl=""
    [[ -n "${7:-}" ]] && kl="--k-local $7"
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_K="$2" \
        CB_T="$3" CB_N="$4" CB_A="$5" CB_L="${6:-} $kl" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" --k "$CB_K" --tmax "$CB_T" \
                --taps "$CB_N" --theta "$CB_A" $CB_L --outdir "$CB_D" \
                > "$CB_D/$0.rgs.report.json"'
}

# --- k=0 IDENTITY CONTROL: proves the dis->as round trip AND that every -----
# --- emitted byte is ours. Runs once; it is independent of the rung knobs. --
K0="$MOD_DIR/dev/disasm/cavity2_k0"
rm -rf "$K0"; mkdir -p "$K0"
# The k=0 identity control runs WITH --all-lights, so it covers the local-light
# rewrites too: if any of the five were not exactly *1.0, this fails.
patch_all "$K0" 0 0.006 4 12 --all-lights
nk=0
for f in "$K0"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || {
        echo "k=0 rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
    nk=$((nk+1))
done
(( nk == 12 )) || { echo "k=0 control produced $nk modules, expected 12" >&2; exit 1; }
echo "  k=0 identity control: $nk/12 byte-identical to base"
rm -rf "$K0"

build_rung() {  # $1 rung name  $2 "k,tmax,taps,theta,sun|all[,k_local]"
    local name="$1" spec="$2"
    IFS=, read -r k tmax taps theta scope klocal <<< "$spec"
    scope="${scope:-sun}"
    local alflag="" lights=1 nloc=0
    if [[ "$scope" == all ]]; then alflag=--all-lights; lights=3; nloc=2; fi
    [[ "$scope" == all ]] || klocal=""      # meaningless without --all-lights
    local dest="$MOD_DIR/swaps.gi.${1#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    echo "== $name  (k=$k tmax=$tmax taps=$taps theta=$theta scope=$scope${klocal:+ k_local=$klocal})"
    patch_all "$dest" "$k" "$tmax" "$taps" "$theta" "$alflag" "$klocal"

    # --- HARD GATE: 12 modules x 3 sun sites (+ 2 local), no skips ---------
    python3 - "$dest" "$taps" "$nloc" << 'PYS'
import glob, json, os, sys
d, taps, nloc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
tot, loc, mods, bad = 0, 0, 0, []
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))['cavity2']
    h = os.path.basename(f).split('.')[0]
    if r['n_sites'] != 3:
        bad.append(f"{h}: {r['n_sites']} sites")
    if r['taps'] != taps:
        bad.append(f"{h}: taps {r['taps']} != {taps}")
    if not r['class_dominates_splice']:
        bad.append(f"{h}: class word does not dominate the splice")
    if r.get('n_local_sites', 0) != nloc:
        bad.append(f"{h}: {r.get('n_local_sites', 0)} local sites, want {nloc}")
    tot += r['n_sites']; loc += r.get('n_local_sites', 0); mods += 1
if mods != 12 or tot != 36 or loc != 12 * nloc or bad:
    print(f'SITE COVERAGE FAILED: {mods} modules, {tot} sun sites, '
          f'{loc} local sites\n  ' + '\n  '.join(bad))
    sys.exit(1)
print(f'  site coverage: {mods}/12 modules, {tot}/36 sun sites, '
      f'{loc}/{12 * nloc} local-light sites')
PYS

    # --- the 2 modules 85 could not reach must now be PATCHED ---------------
    for p in 40c6faab52a13874 ab7f1822eeb0331b; do
        cmp -s "$GI/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            && { echo "$name: $p is STILL byte-verbatim -- 88's whole point" >&2; exit 1; }
    done
    echo "  85's two pass-through modules: both patched"

    # --- verbatim halves: 77 dxil + 4 restirgi, cmp-asserted ---------------
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
    python3 "$VERIFY" "$dest" "$GI" --k "$k" --tmax "$tmax" --taps "$taps" \
        --theta "$theta" --lights "$lights" ${klocal:+--k-local "$klocal"}

    local tmm; tmm=$(python3 -c "print(f'{float('$tmax')*1000:g}')")
    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(12 cone k=$k tmax=${tmm}mm taps=$taps theta=${theta}deg ramp=on)/" \
        -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
        grep -q "$tag" "$dest/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
    done
    {
        echo "# cavity contact shadow v2 (handoff/88), reference/photo-mode PT ONLY."
        echo "# $taps ray(s) per lit skin sample from prehit: tap 0 along the module's"
        echo "# own sun-disc NEE direction, the rest rotated ${theta}deg -- one TOWARD the"
        echo "# tangent plane (the horizon tap), the others lateral. Cosine-weighted"
        echo "# average, weight floor 0.05, distance ramp occ=saturate(1-t/tmax)."
        echo "# flags 16 (CullBackFacing), mask 39, tmin 0.1mm, tmax ${tmm}mm."
        echo "# direct sun *= 1 - $k*occ.  gate: class 1 AND bounce==0 AND the"
        if [[ "$scope" == all ]]; then
        echo "# SCOPE=ALL LIGHTS: the same cone also runs at the 2 local-light NEE"
        echo "# sites (point/spot/area), one of which is INSIDE the light loop, so"
        echo "# the added ray count scales with the visible light count."
        echo "# local-light strength k_local=${klocal:-$k} (88 sec 5c: an area light"
        echo "# subtends tens of degrees, so removing k of the WHOLE term"
        echo "# over-darkens in proportion to the source's solid angle)."
        else
        echo "# SCOPE=SUN ONLY: local point/spot/area lights are untouched."
        fi
        echo "# module's own sun-visibility branch. gate false -> occ is exactly 0"
        echo "# -> factor exactly 1.0 -> bit-identical to base."
        echo "# ALL 12 reference permutations patched (85 reached only 10)."
        echo "# A/B against $BASE_NAME; NOT working until the screen says so."
    } > "$dest/README.txt"
    rm -f "$dest"/*.spvasm
    echo "  built $dest"
}

for i in "${!RUNG_NAMES[@]}"; do
    build_rung "${RUNG_NAMES[$i]}" "${RUNG_SPECS[$i]}"
done

# --- standing rungs still verify (nothing here touched their bytes) --------
echo "== standing rungs"
for r in real-gloss-bleedn-oilh real-gloss-bleedn-oilh-deep; do
    python3 "$MOD_DIR/dev/verify_bleed_norm.py" "$MOD_DIR/swaps.skin.$r" >/dev/null \
        || { echo "verify_bleed_norm.py FAILED on swaps.skin.$r" >&2; exit 1; }
    echo "  verify_bleed_norm.py PASS  swaps.skin.$r (150 hold sites / 77 modules)"
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
    echo "NOW RUN: make install   (init.lua selector rows)"
fi
echo "OK -- ${#RUNG_NAMES[@]} rungs. Nothing is working until the screen says so."
