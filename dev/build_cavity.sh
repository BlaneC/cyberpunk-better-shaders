#!/usr/bin/env bash
# Skin-gated traced CONTACT SHADOW ("cavity"), handoff/85. Reuses 55's
# armed-word handshake (CHS-only, nothing depends on the miss shader), 70 W1's
# cull-mode/min-t reasoning, 75's sun gate, 57 sec 3.2's class-1 gate.
#
# At the skin hit inside the reference raygen's path loop, ONE short ray is
# traced from the un-biased prehit point along the module's OWN sun-disc NEE
# direction (verbatim -- no PRNG draw, so the rest of the frame is bit-stable),
# flags 16 (CullBackFacing), mask 39 (the engine's own sun-shadow occluder
# set), tmin 0.5mm, tmax = the rung's. A hit inside (4e-4, tmax) multiplies the
# DIRECT sun term by (1-k). That is deliberately BESIDE the game's shadow
# chain: it is applied analytically at the shading site, so it never enters a
# denoiser and stays crisp. Extra rays in the SHADOW raygen family are a known
# dead end (29 sec B6) and are not touched here.
#
# The splice sits inside the module's own sun-visibility branch and ANDs that
# branch's condition, so it only runs where the engine already called the pixel
# LIT -> it cannot double-darken against the engine's own shadow.
#
# The ladder is DESIGN, not strength (the 69 sec 2 / 70 lesson): tmax is the
# axis, k moves only once at the end.
#   cavity     tmax  6mm  k=0.85   contact-only: lip line, nostril, eye crease
#   cavityd    tmax 15mm  k=0.85   deeper: nose-over-lip, under-jaw, ear bowl
#   cavityhi   tmax  6mm  k=1.00   contact-only, full occlusion (is 0.85 shy?)
#
#   ./dev/build_cavity.sh            # build + verify (no install)
#   ./dev/build_cavity.sh --install  # ALSO park as skin.set/<rung>
#
# Base is the STANDING rung swaps.gi.50b-bleed-oil-sheen-deep-clothhi. Its 77
# compute + 4 restirgi + the 2 class-test-less reference modules ship
# BYTE-VERBATIM (cmp-asserted); only the 10 paintable rgs_reference_main are
# patched, 3 sites each = 30. So "clothhi vs cavity" is one variable by
# construction. MANIFEST provenance (src_ser/ser_sha/ptq_sha) carries over
# verbatim, so sync's gi_refuse contract holds unchanged.
#
# Reach: the reference/photo-mode path tracer ONLY -- narrower than the compute
# half of the standing rung. See 85 for the premise correction and F1-F8.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi"
GI="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/cavity"
PY="$MOD_DIR/dev/patch_cavity.py"
VERIFY="$MOD_DIR/dev/verify_cavity.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

PASS=(40c6faab52a13874 ab7f1822eeb0331b)
# rung -> "k,tmax"
RUNG_NAMES=(gi-50b-bleed-oil-sheen-deep-clothhi-cavity
            gi-50b-bleed-oil-sheen-deep-clothhi-cavityd
            gi-50b-bleed-oil-sheen-deep-clothhi-cavityhi)
RUNG_SPECS=("0.85,0.006" "0.85,0.015" "1.0,0.006")

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
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0
    for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) || TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }

# --- NEGATIVE CONTROL: the unpatched base carries none of the splice --------
python3 "$VERIFY" --negative "$GI"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${TARGETS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.rgs_reference_main.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 = destdir, $2 = k, $3 = tmax
    printf '%s\0' "${TARGETS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_K="$2" CB_T="$3" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" \
                --k "$CB_K" --tmax "$CB_T" --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
}

build_rung() {  # $1 = rung name, $2 = "k,tmax"
    local name="$1" k="${2%,*}" tmax="${2#*,}" dest="$MOD_DIR/swaps.gi.${1#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    patch_all "$dest" "$k" "$tmax"

    # --- HARD GATE: 30/30 sites, no 0-site module, no skips ----------------
    python3 - "$dest" << 'PYS'
import glob, json, os, sys
d = sys.argv[1]
tot, mods, bad = 0, 0, []
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))['cavity']
    n = r['n_sites']
    if n != 3:
        bad.append(f"{os.path.basename(f).split('.')[0]}: {n} sites")
    if r.get('skipped'):
        bad.append(f"{os.path.basename(f).split('.')[0]}: skipped {r['skipped']}")
    tot += n; mods += 1
if mods != 10 or tot != 30 or bad:
    print(f'SITE COVERAGE FAILED: {mods} modules, {tot} sites\n  ' + '\n  '.join(bad))
    sys.exit(1)
print(f'  site coverage: {mods}/10 modules, {tot}/30 sites')
PYS

    # --- verbatim halves: 77 dxil + 4 restirgi + 2 class-test-less refs -----
    cp -pf "$GI"/*.dxil.spv "$dest/"
    cp -pf "$GI"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$GI/$p.rgs_reference_main.spv" "$dest/"; done
    local nv=0
    for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
        nv=$((nv+1))
    done
    for p in "${PASS[@]}"; do
        cmp -s "$GI/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            || { echo "$name: pass-through $p is NOT byte-verbatim" >&2; exit 1; }
        nv=$((nv+1))
    done
    (( nv == 83 )) || { echo "$name: cmp-asserted $nv verbatim modules, expected 83" >&2; exit 1; }
    for h in "${TARGETS[@]}"; do
        cmp -s "$GI/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "$name: $h byte-identical to base -- splice emitted nothing" >&2; exit 1; }
    done

    # --- spirv-val on every emitted module ---------------------------------
    local nval=0
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
        nval=$((nval+1))
    done
    (( nval == 93 )) || { echo "$name: spirv-val ran on $nval, expected 93" >&2; exit 1; }
    echo "  spirv-val: $nval/93 clean"

    # --- emitted-code re-read from the OUTPUT binaries (39 sec 3.4) --------
    python3 "$VERIFY" "$dest" "$GI" --k "$k" --tmax "$tmax"

    local tmm; tmm=$(python3 -c "print(f'{float('$tmax')*1000:g}')")
    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(10 cavity k=$k tmax=${tmm}mm + 2 pass-through)/" \
        -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
        grep -q "$tag" "$dest/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
    done
    {
        echo "# skin-gated traced contact shadow (handoff/85), reference/photo-mode PT ONLY."
        echo "# one ray from prehit along the module's own sun-disc NEE direction, flags 16"
        echo "# (CullBackFacing), mask 39, tmin 0.5mm, tmax ${tmm}mm; hit in (0.4mm,${tmm}mm)"
        echo "# scales the DIRECT sun term by (1-k)=$(python3 -c "print(round(1-float('$k'),4))")."
        echo "# gate: class 1 (&~31 == 32) AND bounce==0 AND the module's own sun-vis branch."
        echo "# gate false -> mask 0 -> miss -> t stays 10000 -> factor 1.0 -> bit-identical."
        echo "# A/B against $BASE_NAME; NOT working until the screen says so."
    } >> "$dest/MANIFEST.txt"
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "$name has $n modules, expected 93 (77+12+4)" >&2; exit 1; }
    echo "  built swaps.gi.${name#gi-}: $n modules, k=$k tmax=${tmm}mm"
}

for i in "${!RUNG_NAMES[@]}"; do
    echo "== ${RUNG_NAMES[$i]}"
    build_rung "${RUNG_NAMES[$i]}" "${RUNG_SPECS[$i]}"
done

# --- HARD GATE: k=0 rebuild is byte-identical to the base -------------------
echo "== k=0 identity control"
K0="$MOD_DIR/dev/disasm/cavity-k0"
rm -rf "$K0"; mkdir -p "$K0"
patch_all "$K0" 0 0.006
for h in "${TARGETS[@]}"; do
    cmp -s "$GI/$h.rgs_reference_main.spv" "$K0/$h.rgs_reference_main.spv" \
        || { echo "k=0 rebuild of $h DIFFERS from base -- round trip is not clean" >&2; exit 1; }
done
echo "  k=0: 10/10 rebuilt modules byte-identical to base"
rm -rf "$K0"

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
    for r in "${RUNG_NAMES[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"; src="$MOD_DIR/swaps.gi.${r#gi-}"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$src"/*.spv "$src"/*.json "$src/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
fi
echo "select with skinspec=gi-50b-bleed-oil-sheen-deep-clothhi-cavity (or -cavityd / -cavityhi)"
echo "contract: ser=class, shadowset=full-shadow, ptreg ON (rcbm combo) -- the base rung's"
echo "REQUIRED: photo-mode reference PT on, Ray Reconstruction OFF (see handoff/85 sec 0)"
