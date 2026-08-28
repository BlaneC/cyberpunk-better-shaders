#!/usr/bin/env bash
# Install every built shadowcull content set so the CET page can switch between
# them without a rebuild.
#
#   ./dev/install_shadow_sets.sh          # install / refresh all built sets
#   ./dev/install_shadow_sets.sh status
#   ./dev/install_shadow_sets.sh remove   # back to a single fixed set
#
# The sets are parked in $INSTALL_DIR/shadowcull.set/<name>/, which the layer
# never reads -- it only serves swaps.<name> dirs. sync_settings.sh copies the
# selected set into swaps.shadowcull/ at launch, exactly the way it picks a ptq
# combo. Removing the parked sets leaves whatever is in swaps.shadowcull/ alone,
# so an older install keeps working untouched.
#
# Which sets exist is decided by dev/build_shadow_sets.sh -- this script just
# parks whatever it finds, so adding a variant there needs no edit here. The
# names must match the `SETS` list in init.lua's selector.
#
# Caches are not cleared here: sync_settings.sh hashes swaps.shadowcull/*.spv
# into its stamp, so the next launch through the Steam launch options evicts
# them by itself.
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"

shopt -s nullglob
SETS=()
for d in "$MOD_DIR"/swaps.shadowcull.*/; do
    SETS+=("$(basename "${d%/}" | sed 's/^swaps\.shadowcull\.//')")
done

case "${1:-install}" in
    status)
        for d in "$DEST"/shadowcull.set/*/; do
            printf '  %-6s %2d modules\n' "$(basename "${d%/}")" \
                "$(ls "$d"/*.spv 2>/dev/null | wc -l)"
        done
        echo "  live:  $(ls "$DEST/swaps.shadowcull"/*.spv 2>/dev/null | wc -l) modules in swaps.shadowcull/"
        [[ -f "$DEST/shadowcull.disable" ]] && echo "  shadowcull.disable present (overlay OFF)"
        exit 0 ;;
    remove)
        rm -rf "$DEST/shadowcull.set"
        echo "parked sets removed; swaps.shadowcull/ left as-is."
        echo "NOTE: the CET 'Shadow-ray build' selector can no longer change anything."
        exit 0 ;;
esac

(( ${#SETS[@]} )) || { echo "no swaps.shadowcull.* -- run ./dev/build_shadow_sets.sh first" >&2; exit 2; }
printf '%s\n' "${SETS[@]}" | grep -qx full \
    || { echo "'full' is missing -- it is the reference set; rebuild" >&2; exit 2; }

# Every set must be `full`'s module list or a non-empty subset of it. Equal
# coverage is what makes two full-coverage sets a clean A/B; a subset variant
# (full-shadow / full-gi) deliberately leaves the rest of the modules vanilla,
# which is the whole point of it, so it is allowed -- but it may never patch a
# module `full` does not, or it would be testing something else entirely.
a="$(cd "$MOD_DIR/swaps.shadowcull.full" && ls *.spv | sort)"
for s in "${SETS[@]}"; do
    b="$(cd "$MOD_DIR/swaps.shadowcull.$s" && ls *.spv | sort)"
    [[ -n "$b" ]] || { echo "set '$s' is empty -- rebuild" >&2; exit 2; }
    comm -13 <(echo "$a") <(echo "$b") | grep -q . \
        && { echo "set '$s' covers modules 'full' does not -- rebuild" >&2; exit 2; }
    [[ "$a" == "$b" ]] || echo "  note: '$s' is a $(echo "$b" | wc -l)/$(echo "$a" | wc -l)-module subset"
done

rm -rf "$DEST/shadowcull.set"
for s in "${SETS[@]}"; do
    mkdir -p "$DEST/shadowcull.set/$s"
    cp -f "$MOD_DIR/swaps.shadowcull.$s"/*.spv "$DEST/shadowcull.set/$s/"
done
mkdir -p "$DEST/swaps.shadowcull"
echo "installed: $(echo "$a" | wc -l) modules x ${#SETS[@]} sets -> $DEST/shadowcull.set/"
echo "  ${SETS[*]}"
echo "  $(du -sh "$DEST/shadowcull.set" | cut -f1) on disk"
echo "pick one in the CET page (Hair -> 'Shadow-ray build'); it takes effect on"
echo "the next launch made through the Steam launch options."
