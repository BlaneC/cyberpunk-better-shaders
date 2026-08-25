#!/usr/bin/env bash
# Build + install a class-hunt swap set, then clear the pipeline caches.
#
#   ./dev/hunt_hair_class.sh                 # tint all default candidates
#   ./dev/hunt_hair_class.sh 2,3,4           # only these classes
#   ./dev/hunt_hair_class.sh --off           # remove swaps, back to vanilla
#
# Then launch the game WITHOUT regen_and_clear.sh in the launch options (it
# would immediately overwrite these swaps with the tier-1 skin build).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_DIR="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077"
SHADERCACHE="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500"
INSTALL_DIR="$HOME/.local/lib/callisto"
SWAPS="$MOD_DIR/swaps"

clear_caches() {
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared (first launch after this will be slow -- normal)"
}

install_swaps() {
    mkdir -p "$INSTALL_DIR/swaps"
    cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
    rm -f "$INSTALL_DIR/swaps"/*.spv
    if compgen -G "$SWAPS/*.spv" > /dev/null; then
        cp -f "$SWAPS"/*.spv "$INSTALL_DIR/swaps/"
        echo "installed $(ls "$INSTALL_DIR/swaps" | wc -l) swap(s)"
    fi
}

if [[ "${1:-}" == "--off" ]]; then
    rm -f "$SWAPS"/*.spv
    install_swaps
    clear_caches
    echo "swaps removed -- layer passes through, game is vanilla"
    exit 0
fi

ARGS=(--tier hairhunt)
[[ -n "${1:-}" ]] && ARGS+=(--classes "$1")

python3 "$MOD_DIR/dev/patch_skin_brdf.py" \
    "$MOD_DIR/dev/disasm/spv_0170.spvasm" \
    "$MOD_DIR/dev/disasm/spv_0171.spvasm" \
    "${ARGS[@]}" --outdir "$SWAPS" > "$SWAPS/hunt_report.json"

echo
echo "=== colour legend ==="
python3 - "$SWAPS/hunt_report.json" <<'PY'
import json, sys
rep = json.load(open(sys.argv[1]))
for e in rep[0]["hunt"]["legend"]:
    note = "  <- skin, CONTROL: must light up or the test is invalid" \
           if e["class"] == 1 else ""
    print(f"  class {e['class']:>2} = {e['colour']}{note}")
PY
echo
install_swaps
clear_caches
echo "Launch the game and look at hair. Its colour names its class."
