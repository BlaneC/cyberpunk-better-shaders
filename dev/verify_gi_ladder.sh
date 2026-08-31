#!/usr/bin/env bash
# Prove that a set of parked gi-* rungs is a ONE-VARIABLE ladder, offline,
# before a launch is spent on it (handoff/72 sec 5).
#
#   ./dev/verify_gi_ladder.sh                      # the 72 ladder
#   ./dev/verify_gi_ladder.sh rungA rungB ...      # any parked rungs
#   ./dev/verify_gi_ladder.sh --gi gi-50b rungs... # rungs on the gi-50b
#                                                  # raygen base (74)
#
# Checks, in order: equal file lists; the 16 raygens byte-identical to the
# named base (default gi-50) in every rung (that is what makes the compute
# half the only variable); the
# pairwise compute deltas; and the provenance the launch-time gi_refuse block
# will re-check (src_ser / ser_sha / ptq_sha). It reads only what is parked in
# $CALLISTO_INSTALL_DIR/skin.set -- it never rebuilds anything.
set -uo pipefail
I="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
GIBASE=gi-50
RUNGS=()
while (( $# )); do
    case "$1" in
        --gi) GIBASE="${2:?--gi needs a parked rung name}"; shift ;;
        *)    RUNGS+=("$1") ;;
    esac
    shift
done
(( ${#RUNGS[@]} )) || RUNGS=(gi-50-bleed gi-50-bleed-oil gi-50-bleed-sheen2
                             gi-50-bleed-oil-sheen gi-50-bleed-sheen)
fail=0
for r in "${RUNGS[@]}"; do
    [[ -d "$I/skin.set/$r" ]] || { echo "no such parked rung: $r" >&2; exit 2; }
done

echo "== file lists =="
ref=$(cd "$I/skin.set/${RUNGS[0]}" && ls *.spv | sort | md5sum)
for r in "${RUNGS[@]}"; do
    n=$(ls "$I/skin.set/$r"/*.spv | wc -l)
    m=$(cd "$I/skin.set/$r" && ls *.spv | sort | md5sum)
    if [[ "$m" == "$ref" ]]; then s="same as ${RUNGS[0]}"; else s="DIFFERENT"; fail=1; fi
    printf "  %-24s %3d modules, file list %s\n" "$r" "$n" "$s"
done

echo "== raygens byte-identical to $GIBASE (the one-variable guarantee) =="
for r in "${RUNGS[@]}"; do
    d=0
    for f in "$I/skin.set/$GIBASE"/*.rgs_*.spv; do
        cmp -s "$f" "$I/skin.set/$r/$(basename "$f")" || d=$((d+1))
    done
    printf "  %-24s %d of 16 raygens differ%s\n" "$r" "$d" \
           "$( (( d == 0 )) || echo '   <-- NOT one variable')"
    (( d == 0 )) || fail=1
done

echo "== pairwise compute deltas =="
for ((i=0; i<${#RUNGS[@]}; i++)); do
    for ((j=i+1; j<${#RUNGS[@]}; j++)); do
        d=0
        for f in "$I/skin.set/${RUNGS[i]}"/*.dxil.spv; do
            cmp -s "$f" "$I/skin.set/${RUNGS[j]}/$(basename "$f")" || d=$((d+1))
        done
        printf "  %-24s vs %-24s %2d of 77 differ\n" "${RUNGS[i]}" "${RUNGS[j]}" "$d"
        (( d > 0 )) || { echo "    ^ identical builds under two names" >&2; fail=1; }
    done
done

echo "== gi_refuse provenance (what sync_settings.sh re-checks at launch) =="
# swaps.ptq/ is materialised BY sync_settings.sh at launch, so between
# launches it is empty and the live sha is meaningless. Fall back to the
# parked combo the manifests name, and say which one was used.
ptq_now="$(cat "$I/swaps.ptq/"*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
src_note="swaps.ptq (live)"
if [[ -z "$(ls -A "$I/swaps.ptq" 2>/dev/null)" ]]; then
    ptq_now=""; src_note="swaps.ptq is empty between launches -- matched against ptq/*/ instead"
fi
for r in "${RUNGS[@]}"; do
    M="$I/skin.set/$r/MANIFEST.txt"
    src="$(sed -n 's/.*src_ser="\([^"]*\)".*/\1/p' "$M" 2>/dev/null | head -1)"
    ser="$(sed -n 's/.*ser_sha=\([0-9a-f]*\).*/\1/p' "$M" 2>/dev/null | head -1)"
    ptq="$(sed -n 's/.*ptq_sha=\([0-9a-f]*\).*/\1/p' "$M" 2>/dev/null | head -1)"
    if [[ -z "$src" || -z "$ser" || -z "$ptq" ]]; then
        printf "  %-24s NO PROVENANCE -- would be refused (gi-no-manifest)\n" "$r"; fail=1; continue
    fi
    ser_now="$(cat "$I/$src"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
    ok=OK
    [[ "$ser" == "$ser_now" ]] || { ok="STALE-SER ($ser -> ${ser_now:-empty})"; fail=1; }
    if [[ -n "$ptq_now" ]]; then
        [[ "$ptq" == "$ptq_now" ]] || { ok="$ok STALE-PTQ ($ptq -> $ptq_now)"; fail=1; }
    else
        combo=""
        for d in "$I/ptq"/*/*/; do
            compgen -G "$d"'*.rgs_reference_main.spv' >/dev/null || continue
            [[ "$(cat "$d"*.rgs_reference_main.spv | sha256sum | cut -c1-16)" == "$ptq" ]] \
                && { combo="${d#$I/ptq/}"; break; }
        done
        [[ -n "$combo" ]] && ok="OK (ptq combo ${combo%/})" \
                          || { ok="PTQ $ptq matches no parked combo"; fail=1; }
    fi
    printf "  %-24s src_ser=%-16s %s\n" "$r" "$src" "$ok"
done
echo "  ($src_note)"
echo
(( fail == 0 )) && echo "ALL CHECKS PASS" || { echo "FAILURES ABOVE"; exit 1; }
