#!/usr/bin/env bash
# G-U4 sub-enum probe + A2 ungated sheen probe (handoff/40-SUBTYPE-PROBE.md).
#
#   ./dev/patch_subtype_probe.sh              # build all five rungs (no install)
#   ./dev/patch_subtype_probe.sh --install    # ALSO park them for the game
#   ./dev/patch_subtype_probe.sh --legend     # print the colour legend
#
# Builds into $MOD_DIR/swaps.probe.<rung>/. Installing is a SEPARATE, opt-in
# step because these are diagnostics, not features: nothing here should ever
# end up served by accident.
#
# WHY THE RUNGS RIDE THE `skin` OVERLAY (--install)
# A new overlay name `probe` would need either an edit to swap_layer.c's
# default list ("ser,skin,shadowcull,ptq,ptrefl") or CALLISTO_OVERLAYS in the
# Steam launch options, since env vars do not otherwise reach the game through
# Proton (GOTCHAS) -- and it would still be WORSE, because overlays coexist
# first-file-wins: a `probe` overlay would shadow `skin` for its 76 ids while
# swaps.skin/ kept serving ab0bc2fee876d489, i.e. a silently mixed payload.
# Riding skin.set guarantees one whole known payload. The probe
# targets EXACTLY the modules the skin overlay already owns (both are built
# from the same 1/pi + 0.107508637 anchored set), so it can simply be another
# parked LEVEL of that overlay:
#
#   $INSTALL_DIR/skin.set/probe-<rung>/   <- parked here by --install
#   brdf_params.txt: skinspec=probe-<rung>
#   sync_settings.sh copies it into swaps.skin/ at launch
#
# sync_settings.sh validates the level only by `-d skin.set/$want_skin`, so an
# arbitrary directory name works, and every piece of existing machinery keeps
# working for free: the payload hash moves so the pipeline caches are evicted,
# and ~/callisto_launches.log records the content hash actually served.
#
# FIRST-FILE-WINS. This build REPLACES swaps.skin for the launch: the probe
# rungs carry NO tier-1 c1 and no gloss, on purpose -- a diagnostic must not
# have a second edit in it. There is no collision with anything else, because
# nothing but the skin overlay patches these GLCompute libs (shadowcull, ptq
# and ptrefl are all RT raygens, and base swaps/ holds only two reference
# raygens). Put the ladder back with ./dev/patch_compute_skin.sh --sets.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
WORK="$MOD_DIR/dev/disasm/compute"
PY="$MOD_DIR/dev/patch_subtype_probe.py"

# rung:tier:extra-args
RUNGS=(
    "sub:sub:"
    "c1sub:c1sub:"
    "cls:cls:"
    "sheen:sheen:"
    "both:both:"
)

DO_INSTALL=0; EXTRA=()
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --legend)  python3 "$PY" --legend; exit 0 ;;
        --legend-md) python3 "$PY" --legend-md; exit 0 ;;
        --set) EXTRA+=(--set "${2:?--set needs K=V}"); shift ;;
        -*) echo "unknown flag: $1" >&2; exit 2 ;;
        *)  DUMP_DIR="$1" ;;
    esac
    shift
done

# Same anchored set as patch_compute_skin.sh -- selected by the two constants
# that identify a module carrying the full material stack (1/pi and the
# Frostbite renormalisation 0.107508637), NOT by name.
mapfile -t targets < <(python3 - "$DUMP_DIR" <<'PYSEL'
import glob, struct, sys
pi = struct.pack('<f', 0.318309873)
k = struct.pack('<f', 0.107508637)
for f in sorted(glob.glob(sys.argv[1] + '/*.dxil.spv')):
    d = open(f, 'rb').read()
    if pi in d and k in d:
        print(f)
PYSEL
)
echo "=== ${#targets[@]} anchored compute libs ==="
mkdir -p "$WORK"

RT_DONE=0
build_into() {
    local dest="$1" tier="$2"; shift 2
    local args=(--tier "$tier")
    if (( ${#EXTRA[@]} )); then args+=("${EXTRA[@]}"); fi
    args+=("$@")
    mkdir -p "$dest"
    rm -f "$dest"/*.spv "$dest"/*.spvasm "$dest"/.ok.* "$dest"/.bad.* "$dest"/.skin.* 2>/dev/null || true
    if (( RT_DONE )); then args+=(--no-roundtrip-check); fi

    # spirv-dis is SEQUENTIAL on purpose: $WORK is shared by every rung, so
    # parallel rungs racing on one missing .spvasm would interleave writes
    # into a single file (the CALLISTO_JOBS gotcha).
    local asms=() missing=() name asm f
    for f in "${targets[@]}"; do
        name="$(basename "${f%.spv}")"
        asm="$WORK/$name.spvasm"
        if [[ ! -f "$asm" ]] && ! spirv-dis "$f" -o "$asm" 2>/dev/null; then
            missing+=("$name"); continue
        fi
        asms+=("$asm")
    done

    local jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
    local argfile="$dest/.args"
    printf '%s\n' "${args[@]}" > "$argfile"
    printf '%s\0' "${asms[@]}" | \
        CB_DEST="$dest" CB_ARGS="$argfile" CB_PY="$PY" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" --outdir "$CB_DEST" \
                    > "$CB_DEST/.rep.$n.json" 2>"$CB_DEST/.err.$n"; then
                : > "$CB_DEST/.ok.$n"
            else
                : > "$CB_DEST/.bad.$n"
            fi' _
    rm -f "$argfile"

    local np nf
    np=$(find "$dest" -maxdepth 1 -name '.ok.*' | wc -l)
    nf=$(find "$dest" -maxdepth 1 -name '.bad.*' | wc -l)
    nf=$(( nf + ${#missing[@]} ))
    printf '  patched %3d, declined %3d\n' "$np" "$nf"
    if (( nf > 0 )); then
        for f in "$dest"/.bad.*; do
            [[ -e "$f" ]] || continue
            n="$(basename "$f")"; n="${n#.bad.}"
            echo "    $(sed 's/.*error: //' "$dest/.err.$n" 2>/dev/null | tail -1 | cut -c1-78)"
        done | sort | uniq -c | sort -rn | head -8
    fi
    rm -f "$dest"/.ok.* "$dest"/.bad.* 2>/dev/null || true
    # A successful module still leaves an empty stderr file; keep only the
    # ones that say something, so `ls .err.*` is the decline list.
    find "$dest" -maxdepth 1 -name '.err.*' -size 0 -delete 2>/dev/null || true
    BUILT=$np
    RT_DONE=1
    (( BUILT > 0 )) || { echo "nothing patched for tier $tier" >&2; exit 1; }
}

declare -A COUNT=()
NAMES=()
for spec in "${RUNGS[@]}"; do
    IFS=':' read -r rung tier extra <<< "$spec"
    echo "--- rung '$rung' (tier $tier) ---"
    if [[ -n "$extra" ]]; then
        # shellcheck disable=SC2086
        build_into "$MOD_DIR/swaps.probe.$rung" "$tier" $extra
    else
        build_into "$MOD_DIR/swaps.probe.$rung" "$tier"
    fi
    COUNT[$rung]=$BUILT
    NAMES+=("$rung")
done

# --- assertions -------------------------------------------------------------
# 1. Every rung must differ from every other rung. Two rungs that came out
#    byte-identical would be the same build under two names, and flipping the
#    selector between them would silently compare nothing (the check that
#    caught an unreachable knob in the gloss ladder).
echo "--- assertions ---"
fail=0
for i in "${!NAMES[@]}"; do
    for j in "${!NAMES[@]}"; do
        (( j > i )) || continue
        a="$MOD_DIR/swaps.probe.${NAMES[$i]}"; b="$MOD_DIR/swaps.probe.${NAMES[$j]}"
        d=0
        for f in "$a"/*.spv; do
            bn="$(basename "$f")"
            [[ -f "$b/$bn" ]] || continue
            cmp -s "$f" "$b/$bn" || d=$((d+1))
        done
        printf '  %-6s vs %-6s : %3d module(s) differ\n' "${NAMES[$i]}" "${NAMES[$j]}" "$d"
        (( d > 0 )) || { echo "  !! identical builds under two names" >&2; fail=1; }
    done
done

# 2. The `cls` rung must be BYTE-IDENTICAL to what patch_compute_skin.sh --hunt
#    produces. That rung is the positive control -- it is the paint that
#    produced pics/panam_working_small.png -- and it is only a control if it is
#    literally the same build. If this ever fails, the control has drifted and
#    a null result on `sub` stops being attributable.
echo "  cls == patch_compute_skin.py --tier hunt ?"
ctl="$MOD_DIR/swaps.probe.cls.ctl"
rm -rf "$ctl"; mkdir -p "$ctl"
for asm in "$WORK"/*.spvasm; do
    n="$(basename "${asm%.spvasm}")"
    [[ -f "$MOD_DIR/swaps.probe.cls/$n.spv" ]] || continue
    python3 "$MOD_DIR/dev/patch_compute_skin.py" "$asm" --tier hunt \
        --outdir "$ctl" --no-roundtrip-check >/dev/null 2>&1 || true
done
same=0; diffn=0
for f in "$MOD_DIR/swaps.probe.cls"/*.spv; do
    bn="$(basename "$f")"
    if [[ -f "$ctl/$bn" ]] && cmp -s "$f" "$ctl/$bn"; then same=$((same+1)); else diffn=$((diffn+1)); fi
done
printf '    identical=%d differ_or_missing=%d\n' "$same" "$diffn"
(( diffn == 0 )) || { echo "  !! the control has drifted from --tier hunt" >&2; fail=1; }
rm -rf "$ctl"
(( fail == 0 )) || exit 1

echo
for n in "${NAMES[@]}"; do
    printf '  swaps.probe.%-6s  %3d modules\n' "$n" "${COUNT[$n]}"
done

if (( DO_INSTALL )); then
    for n in "${NAMES[@]}"; do
        d="$INSTALL_DIR/skin.set/probe-$n"
        mkdir -p "$d"; rm -f "$d"/*.spv
        # -p: mtime comes from the build, so an unchanged selection hashes the
        # same next launch and the pipeline caches survive (the cp -p GOTCHA).
        cp -pf "$MOD_DIR/swaps.probe.$n"/*.spv "$d/"
    done
    echo "parked ${#NAMES[@]} probe rungs -> $INSTALL_DIR/skin.set/probe-*"
    echo "select one with:  skinspec=probe-sub  in brdf_params.txt"
else
    echo
    echo "NOT installed (diagnostics are opt-in). To install:"
    echo "  ./dev/patch_subtype_probe.sh --install"
fi
