#!/usr/bin/env bash
# Install the path-tracing quality matrix + the reflection cullMask overlay.
#
#   ./dev/install_ptq.sh          # install (or refresh) both
#   ./dev/install_ptq.sh remove   # take them back out entirely
#   ./dev/install_ptq.sh status
#
# Unlike the other overlays there is nothing to choose here: which combination
# of the three toggles is live is decided at LAUNCH by sync_settings.sh reading
# the CET page, not at install time. This script only puts the pre-built matrix
# where sync_settings.sh can find it:
#
#   $INSTALL_DIR/ptq/<combo>/{base,skin}/   the matrix (NOT an overlay dir --
#                                           the layer only reads swaps.<name>)
#   $INSTALL_DIR/swaps.ptq/                 materialized per launch
#   $INSTALL_DIR/swaps.ptrefl/              the reflection cullMask overlay
#
# Caches are not cleared here: sync_settings.sh hashes the installed payload
# into its stamp, so the next launch through the Steam launch options sees the
# change and evicts GLCache + shadercache by itself.
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SRC="$MOD_DIR/swaps.ptq.matrix"
COMBOS=(b c m r bm cb cm rb rc rm cbm rbm rcb rcm rcbm)

case "${1:-install}" in
    status)
        for c in "${COMBOS[@]}"; do
            b=$(ls "$DEST/ptq/$c/base"/*.spv 2>/dev/null | wc -l)
            s=$(ls "$DEST/ptq/$c/skin"/*.spv 2>/dev/null | wc -l)
            echo "  $c: $b base + $s skin"
        done
        echo "  ptrefl: $(ls "$DEST/swaps.ptrefl"/*.spv 2>/dev/null | wc -l) modules"
        echo "  live:   $(ls "$DEST/swaps.ptq"/*.spv 2>/dev/null | wc -l) modules in swaps.ptq/"
        [[ -f "$DEST/ptrefl.disable" ]] && echo "  ptrefl.disable present"
        exit 0 ;;
    remove)
        rm -rf "$DEST/ptq" "$DEST/swaps.ptq" "$DEST/swaps.ptrefl"
        rm -f "$DEST/ptrefl.disable"
        echo "path-tracing quality removed. NOTE: the settings page can no longer"
        echo "reach these toggles, so leave them off there too."
        exit 0 ;;
esac

[[ -d "$SRC" ]] || { echo "no matrix at $SRC -- run ./dev/build_ptq.sh first" >&2; exit 2; }
for c in "${COMBOS[@]}"; do
    [[ -d "$SRC/$c/base" && -d "$SRC/$c/skin" ]] \
        || { echo "matrix is incomplete (missing $c) -- rebuild it" >&2; exit 2; }
done

rm -rf "$DEST/ptq"
for c in "${COMBOS[@]}"; do
    mkdir -p "$DEST/ptq/$c/base" "$DEST/ptq/$c/skin"
    cp -f "$SRC/$c/base"/*.spv "$DEST/ptq/$c/base/"
    cp -f "$SRC/$c/skin"/*.spv "$DEST/ptq/$c/skin/"
done
mkdir -p "$DEST/swaps.ptq"
rm -rf "$DEST/swaps.ptrefl"; mkdir -p "$DEST/swaps.ptrefl"
cp -f "$MOD_DIR/swaps.ptrefl"/*.spv "$DEST/swaps.ptrefl/"

echo "installed: ${#COMBOS[@]} combos -> $DEST/ptq/, $(ls "$DEST/swaps.ptrefl"/*.spv | wc -l) modules -> $DEST/swaps.ptrefl/"
echo "the toggles are in the CET page (Callisto SSS -> Path tracing); they take"
echo "effect on the next launch made through the Steam launch options."
