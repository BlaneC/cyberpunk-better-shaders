#!/usr/bin/env bash
# handoff/90 -- the cavity cone rebuilt on the -b3 BOUNCE FLOOR base, with the
# 89 sec 2 GATE FIX.
#
# Two changes against dev/build_cavity2.sh, and both are the point:
#
#   1. BASE. The base is gi-50b-bleed-oil-sheen-deep-clothhi-b3, not
#      -clothhi. -b3 is a kept, on-screen rung (89 sec 0) and the cone could
#      not be combined with it before, because every cone rung sat on the
#      un-floored base.
#
#   2. GATE. The cone's `== 0` conjunct now tests the PATH loop's counter.
#      Pre-89 it tested whatever `E.find_bounce_counter` returned, and that
#      helper's documented tie-break is "outermost wins" -- the SAMPLE loop.
#      It was wrong in 5 of the 12 permutations, right in the other 7, so the
#      cavity term ran at every bounce in 5 and only at the primary hit in 7,
#      dispatched at random per launch (88 sec 1). That is a coin flip inside
#      a term that was being A/B'd, and it is the leading suspect for 88 sec
#      5c's area-light over-darkening: in the 5 bad permutations a darkening
#      meant for one hit compounded over every bounce -- now three of them.
#
# The -sg rung keeps the OLD gate deliberately: -b3-cone2all vs -b3-cone2allsg
# is one variable, the gate, and it is the only pair that measures the fix.
#
# Reach is unchanged: rgs_reference_main ONLY. All 77 compute and all 4
# ReSTIR-GI modules are byte-identical to the base and are cmp-asserted so.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi-b3"
GI="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi-b3"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/cavity3_12"
PY="$MOD_DIR/dev/patch_cavity2.py"
VERIFY="$MOD_DIR/dev/verify_cavity2.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# rung -> "k,tmax,taps,theta,sun|all,gate[,k_local]"  ONE VARIABLE PER STEP:
#   -b3          -> -b3-cone2       : + the sun cavity cone (88's kept shape)
#   -b3-cone2    -> -b3-cone2all    : + SCOPE, the 2 local-light NEE sites
#   -b3-cone2all -> -b3-cone2allsg  : the GATE, and nothing else. THE PAIR
#                                     THAT MEASURES 89 sec 2. -sg reproduces
#                                     the old sample-counter gate.
#   -b3-cone2all -> -b3-cone2all35  : k_local 0.85 -> 0.35, the fallback if
#                                     the gate fix alone does not settle the
#                                     area lights (88 sec 5c). Sun stays 0.85.
RUNG_NAMES=(gi-50b-bleed-oil-sheen-deep-clothhi-b3-cone2
            gi-50b-bleed-oil-sheen-deep-clothhi-b3-cone2all
            gi-50b-bleed-oil-sheen-deep-clothhi-b3-cone2allsg
            gi-50b-bleed-oil-sheen-deep-clothhi-b3-cone2all35)
RUNG_SPECS=("0.85,0.006,2,12,sun,bounce"
            "0.85,0.006,2,12,all,bounce"
            "0.85,0.006,2,12,all,sample"
            "0.85,0.006,2,12,all,bounce,0.35")

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

patch_all() {  # $1 dest $2 k $3 tmax $4 taps $5 theta $6 ""|--all-lights $7 k_local $8 gate
    local kl=""
    [[ -n "${7:-}" ]] && kl="--k-local $7"
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_K="$2" \
        CB_T="$3" CB_N="$4" CB_A="$5" CB_L="${6:-} $kl" CB_G="${8:-bounce}" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" --k "$CB_K" --tmax "$CB_T" \
                --taps "$CB_N" --theta "$CB_A" --gate "$CB_G" $CB_L \
                --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
}

# --- k=0 IDENTITY CONTROL: proves the dis->as round trip AND that every -----
# --- emitted byte is ours. Runs once; it is independent of the rung knobs. --
K0="$MOD_DIR/dev/disasm/cavity3_k0"
rm -rf "$K0"; mkdir -p "$K0"
# The k=0 identity control runs WITH --all-lights, so it covers the local-light
# rewrites too: if any of the five were not exactly *1.0, this fails.
patch_all "$K0" 0 0.006 4 12 --all-lights "" bounce
nk=0
for f in "$K0"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || {
        echo "k=0 rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
    nk=$((nk+1))
done
(( nk == 12 )) || { echo "k=0 control produced $nk modules, expected 12" >&2; exit 1; }
echo "  k=0 identity control: $nk/12 byte-identical to base"
rm -rf "$K0"

build_rung() {  # $1 rung name  $2 "k,tmax,taps,theta,sun|all,gate[,k_local]"
    local name="$1" spec="$2"
    IFS=, read -r k tmax taps theta scope gate klocal <<< "$spec"
    gate="${gate:-bounce}"
    scope="${scope:-sun}"
    local alflag="" lights=1 nloc=0
    if [[ "$scope" == all ]]; then alflag=--all-lights; lights=3; nloc=2; fi
    [[ "$scope" == all ]] || klocal=""      # meaningless without --all-lights
    local dest="$MOD_DIR/swaps.gi.${1#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    echo "== $name  (k=$k tmax=$tmax taps=$taps theta=$theta scope=$scope gate=$gate${klocal:+ k_local=$klocal})"
    patch_all "$dest" "$k" "$tmax" "$taps" "$theta" "$alflag" "$klocal" "$gate"

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
        --theta "$theta" --lights "$lights" --gate "$gate" \
        ${klocal:+--k-local "$klocal"}

    local tmm; tmm=$(python3 -c "print(f'{float('$tmax')*1000:g}')")
    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12([^)]*)/ref=12(12 bounce floor n=3 + cone k=$k tmax=${tmm}mm taps=$taps theta=${theta}deg gate=$gate)/" \
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
        echo "# direct sun *= 1 - $k*occ.  gate: class 1 AND <$gate>==0 AND the"
        if [[ "$gate" == sample ]]; then
        echo "# !! GATE=SAMPLE: the pre-89 behaviour, kept ONLY as the control"
        echo "# !! that isolates the gate fix. Do not ship this rung."
        fi
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
        echo "# Base carries 89's bounce floor n=3, so this rung is cone + floor."
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
