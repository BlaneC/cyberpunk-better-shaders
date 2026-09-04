#!/usr/bin/env bash
# build_earglow_ll.sh -- ear glow from LOCAL lights at the raygen's own
# light-sample site (handoff/113). Four rungs:
#
#   earglow-ll       the rung: 111 v7's transfer (k from the -hue1 model) x the
#                    engine's own unshadowed local-light radiance, gated by
#                    skin / primary segment / backlit / A==B instance / C miss
#   earglow-ll-hi    k x 2, nothing else
#   earglow-ll-hit   the diagnostic: BLUE = accepted, AMBER = same-instance
#                    wall but C hit, both scaled by the light; glow's full gate
#   earglow-ll-ctl   the base, byte for byte (the selector's control)
#
# BASE: the shipped default (sun glow v7 + curv compute). Only the 10
# `rgs_reference_main` permutations change; the 2 pass-through raygens, the 4
# restirgi and the 77 compute resolvers are copied verbatim.
#
#   ./dev/build_earglow_ll.sh [--install] [--base <skin.set name>]
#
# Gates: 0 base + provenance, 1 round-trip neutrality, 2 the model, 3 patch +
# assemble + spirv-val, 4 coverage census from the reports, 5 instruction
# census on the SHIPPED bytes, 6 ctl identity, 7 verify_earglow_ll.py,
# 8 verifier non-vacuity (decoys + cross-reads), 9 MANIFEST provenance, shas.
set -euo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow_ll.py"
VERIFY="$MOD_DIR/dev/verify_earglow_ll.py"
WORK="$MOD_DIR/dev/disasm/earglow_ll"
MODEL="$MOD_DIR/dev/disasm/earglow7/model/r6lo.json"
BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1
K_HI=2
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)
ORDER=(earglow-ll earglow-ll-hi earglow-ll-hit earglow-ll-ctl)
declare -A RUNG_ARGS=(
    [earglow-ll]="--mode glow"
    [earglow-ll-hi]="--mode glow --k-scale $K_HI"
    [earglow-ll-hit]="--mode hit"
    [earglow-ll-ctl]="--mode ctl"
)

# --- 0. the base -------------------------------------------------------------
echo "=== 0. base: $BASE"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the base is not parked" >&2; exit 1; }
[[ -f "$MODEL" ]] || { echo "no model $MODEL (111 v7's -hue1 fit)" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 && "$n_g" == 4 && "$n_r" == 12 ]] \
    || { echo "$BASE is $n_c/$n_g/$n_r, expected 77/4/12" >&2; exit 1; }
grep -q "^# src: .*src_ser=" "$SRC/MANIFEST.txt" || grep -q "src_ser" "$SRC/MANIFEST.txt" \
    || { echo "$BASE's MANIFEST carries no src_ser provenance -- sync_settings.sh would refuse the rungs" >&2; exit 1; }
mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
[[ "${#TARGETS[@]}" == 10 ]] || { echo "${#TARGETS[@]} target raygens, want 10" >&2; exit 1; }
rm -rf "$WORK/asm" "$WORK"/p.* "$WORK/decoy"
mkdir -p "$WORK/asm"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done
echo "  10 target raygens disassembled from the SHIPPED base (not from an older asm dir)"

# --- 1. round-trip neutrality -----------------------------------------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/asm/$h.rt.spv"
    cmp -s "$WORK/asm/$h.rt.spv" "$SRC/$h.rgs_reference_main.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
    rm -f "$WORK/asm/$h.rt.spv"
done
echo "  10 of 10 round-trip byte-identically"

# --- 2. the model ------------------------------------------------------------
echo "=== 2. the transmittance model (111 v7, -hue1 point)"
python3 - "$MODEL" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print("  k = %.4f, tint = [%s], rates R [%.1f, %.1f]" % (
    m['k'], ', '.join('%.4g' % t for t in m['tint']),
    m['rates_1_per_m'][0][0], m['rates_1_per_m'][0][1]))
PY

# --- 3. patch + assemble ----------------------------------------------------
patch_set () {   # $1 = outdir, rest = patcher args
    local out="$1"; shift
    rm -rf "$out"; mkdir -p "$out"
    for h in "${TARGETS[@]}"; do
        python3 "$PY" "$WORK/asm/$h.spvasm" --outdir "$out" --model "$MODEL" \
                --no-roundtrip-check "$@" > "$out/$h.earglow_ll.report.json"
    done
}
assemble () {    # $1 = swaps dir, $2 = patched dir
    local dest="$1" src="$2"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$SRC/$p.rgs_reference_main.spv" "$dest/"; done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, want 93" >&2; exit 1; }
}
echo "=== 3. patch + assemble the four rungs"
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r"
    d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$r/$h.rgs_reference_main.spv" "$SRC/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    want=10; [[ "$r" == *-ctl ]] && want=0
    [[ "$d" == "$want" ]] || { echo "  !! $r: $d raygens differ from the base, want $want" >&2; exit 1; }
    echo "  swaps.$r: 93 modules, $d raygens differ from the base, spirv-val (vulkan1.4) clean"
done
for pair in "earglow-ll earglow-ll-hi" "earglow-ll earglow-ll-hit" "earglow-ll-hi earglow-ll-hit"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  ll / hi / hit differ pairwise on all 10 raygens"

# --- 4. coverage census, from the REPORTS ----------------------------------
echo "=== 4. coverage census (reports)"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
bad = []
for r in rungs:
    reps = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r, '*.earglow_ll.report.json')))]
    if len(reps) != 10:
        bad.append('%s: %d reports, want 10' % (r, len(reps))); continue
    if r.endswith('-ctl'):
        if any(x['earglow_ll'].get('mode') != 'control' for x in reps):
            bad.append('%s: a report is not the control' % r)
        print('  %-15s 10 modules, 0 instructions emitted (the identity control)' % r)
        continue
    sites = sum(1 for x in reps if x['earglow_ll']['site'])
    decl = sum(len(x['earglow_ll']['declined']) for x in reps)
    thr = {x['earglow_ll']['site']['thr'] for x in reps}
    dthr = {d['thr'] for x in reps for d in x['earglow_ll']['declined']}
    att = {x['earglow_ll']['cloned_atten_ops'] for x in reps}
    tr = {len(x['earglow_ll']['site']['traces']) for x in reps}
    wr = sum(len(x['earglow_ll']['writes_added']) for x in reps)
    sc = {x['earglow_ll']['per_light_scales'] for x in reps}
    if sites != 10 or decl != 10 or thr != {0.0} or tr != {3} or len(att) != 1:
        bad.append('%s: sites %d declined %d thr %s traces %s atten %s' % (r, sites, decl, thr, tr, att))
    print('  %-15s 10 sites (guard thr 0, 3 traces in the lit block), 10 resampled loops declined (thr %s), %s cloned atten ops each, %d writes; scales: %s'
          % (r, ', '.join('%.3g' % t for t in dthr), att.pop(), wr, sc.pop()))
if bad:
    for b in bad: sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. instruction census on the SHIPPED bytes -----------------------------
echo "=== 5. instruction census on the SHIPPED bytes"
for r in "${ORDER[@]}"; do
    ini=0; pro=0; tg=0; idg=0; tr=0; trb=0
    for h in "${TARGETS[@]}"; do
        t=$(spirv-dis --no-color "$MOD_DIR/swaps.$r/$h.rgs_reference_main.spv")
        ini=$((ini + $(grep -c "OpRayQueryInitializeKHR" <<<"$t")))
        pro=$((pro + $(grep -c "OpRayQueryProceedKHR" <<<"$t")))
        tg=$((tg + $(grep -c "OpRayQueryGetIntersectionTKHR" <<<"$t")))
        idg=$((idg + $(grep -c "OpRayQueryGetIntersectionInstanceIdKHR" <<<"$t")))
        tr=$((tr + $(grep -c "OpTraceRayKHR" <<<"$t")))
        trb=$((trb + $(spirv-dis --no-color "$SRC/$h.rgs_reference_main.spv" | grep -c "OpTraceRayKHR")))
    done
    if [[ "$r" == *-ctl ]]; then want_ini=30; want_pro=30; want_tg=10; want_idg=20
    else want_ini=60; want_pro=60; want_tg=20; want_idg=40; fi
    [[ "$ini" == "$want_ini" && "$pro" == "$want_pro" && "$tg" == "$want_tg" && "$idg" == "$want_idg" && "$tr" == "$trb" ]] \
        || { echo "  !! $r: init $ini proceed $pro t $tg id $idg traces $tr (base $trb)" >&2; exit 1; }
    echo "  $(printf '%-15s' "$r") $ini Initialize ($((ini/10)) per raygen: sun A/B/C$( [[ "$r" == *-ctl ]] || echo " + local A/B/C")), $pro Proceed, $tg t reads, $idg InstanceId reads, OpTraceRayKHR $tr == base $trb"
done

# --- 6. the identity control --------------------------------------------------
echo "=== 6. earglow-ll-ctl identity"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.earglow-ll-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! earglow-ll-ctl differs from the base on $d files" >&2; exit 1; }
echo "  earglow-ll-ctl: 93 of 93 byte-identical to $BASE"

# --- 7. the verifier ---------------------------------------------------------
echo "=== 7. verify_earglow_ll.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-ll"     --base "$SRC" --model "$MODEL" --mode glow
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-ll-hi"  --base "$SRC" --model "$MODEL" --mode glow --k-scale "$K_HI"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-ll-hit" --base "$SRC" --model "$MODEL" --mode hit
python3 "$VERIFY" --negative "$SRC"
python3 "$VERIFY" --negative "$MOD_DIR/swaps.earglow-ll-ctl"

# --- 8. non-vacuity -----------------------------------------------------------
echo "=== 8. verifier non-vacuity (each of these MUST fail)"
reject () {
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
mkdir -p "$WORK/decoy"
for dec in noc nomatch flatk front; do
    rm -rf "$WORK/decoy/$dec"; mkdir -p "$WORK/decoy/$dec"
    python3 "$PY" "$WORK/asm/${TARGETS[0]}.spvasm" --outdir "$WORK/decoy/$dec" \
            --model "$MODEL" --no-roundtrip-check --mode glow --decoy "$dec" >/dev/null
done
V=(--base "$SRC" --model "$MODEL" --mode glow)
reject "--decoy noc (C traced, never consulted: glow through an occluded exit)" "$WORK/decoy/noc" "${V[@]}"
reject "--decoy nomatch (no A==B instance match: collar/hair bleed)"          "$WORK/decoy/nomatch" "${V[@]}"
reject "--decoy flatk (no transmittance: thickness ignored)"                   "$WORK/decoy/flatk" "${V[@]}"
reject "--decoy front (the gate without its BACKLIT arm)"                      "$WORK/decoy/front" "${V[@]}"
reject "earglow-ll read as the diagnostic"   "$MOD_DIR/swaps.earglow-ll" --base "$SRC" --model "$MODEL" --mode hit
reject "earglow-ll-hit read as the glow"     "$MOD_DIR/swaps.earglow-ll-hit" "${V[@]}"
reject "earglow-ll read at k x $K_HI"        "$MOD_DIR/swaps.earglow-ll" "${V[@]}" --k-scale "$K_HI"
reject "earglow-ll-hi read at k x 1"         "$MOD_DIR/swaps.earglow-ll-hi" "${V[@]}"
reject "the unpatched BASE read as a rung"   "$SRC" "${V[@]}"
reject "the CONTROL read as a rung"          "$MOD_DIR/swaps.earglow-ll-ctl" "${V[@]}"
reject "earglow-ll --negative (a spliced rung read as clean)" --negative "$MOD_DIR/swaps.earglow-ll"
rm -rf "$WORK/decoy"

# --- 9. MANIFEST provenance ---------------------------------------------------
echo "=== 9. MANIFEST provenance"
K=$(python3 -c "import json;print('%.4f'%json.load(open('$MODEL'))['k'])")
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    case "$r" in
      *-ctl) l1="$r (ALIAS of $BASE -- byte-identical control; dev/build_earglow_ll.sh)" ;;
      *)     l1="$r (BUILT ON $BASE by dev/build_earglow_ll.sh -- handoff/113; the 10 rgs_reference_main differ)" ;;
    esac
    { echo "$l1"; sed -e '1d' "$SRC/MANIFEST.txt"; } > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    grep -q "src_ser" "$dest/MANIFEST.txt" || { echo "provenance lost in $r" >&2; exit 1; }
    {
      echo "# earglow-ll (handoff/113): ear glow from LOCAL lights at the raygen's light-sample"
      echo "# site. In the 10 rgs_reference_main, before the light loop's backlit guard, three"
      echo "# inline ray queries (A: primary-surface instance from the camera, once per path"
      echo "# vertex; B: cull-front thickness toward the light 1.5-18 mm; C: exit point ->"
      echo "# light visibility to 0.8 d) drive 111 v7's transfer (the -hue1 model, k=$K, 6 mm"
      echo "# floor) x the engine's own attenuation x spot x light colour, added at the radiance"
      echo "# writes. Only the exhaustive light loop; the resampled loop is left alone."
      echo "# Per-light scale bytes (word 60) are not applied. No BDA slot, no layer dependency."
      case "$r" in
        *-ctl) echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE. Control for the selector." ;;
        *-hi)  echo "# k x $K_HI. Louder, nothing else." ;;
        *-hit) echo "# DIAGNOSTIC: skin BLUE = accepted, AMBER = same-instance wall but C hit; scaled by the light." ;;
      esac
      echo "# A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  4 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z | xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-16s content=%s  raygens=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-16s content=%s  raygens=%s\n' "(base)" "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        if [[ -d "$park" && ! -f "$park/.earglow-ll-owned" ]]; then
            echo "  !! $park exists and was not created by build_earglow_ll.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; touch "$park/.earglow-ll-owned"
        rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=$(ls "$park"/*.spv | wc -l)
        [[ "$n" == 93 ]] || { echo "  !! parked $r has $n modules" >&2; exit 1; }
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! parked $r differs from the build: $(basename "$f")" >&2; exit 1; }
        done
        echo "  parked -> $park (93 modules, cmp-verbatim against the build)"
    done
else
    echo "NOT installed. To park: ./dev/build_earglow_ll.sh --install"
fi
echo "select with skinspec=earglow-ll | earglow-ll-hi | earglow-ll-hit | earglow-ll-ctl;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract). No BDA layer needed."
