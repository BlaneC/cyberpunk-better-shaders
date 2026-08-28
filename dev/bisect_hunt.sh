#!/usr/bin/env bash
# Bisect the hunt overlay to find which module owns a painted surface.
#
#   ./dev/bisect_hunt.sh A    # install first half of the 29-module hunt net
#   ./dev/bisect_hunt.sh B    # install second half
#   ./dev/bisect_hunt.sh all  # install all 29 (default state)
#   ./dev/bisect_hunt.sh list # list the two halves
#
# After each run: relaunch the game (caches are cleared here) and check the
# SAME painted surface. If paint survives on half A, the owner is in A; else
# it's in B. Then ask for the next split of that half.
set -euo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$MOD_DIR/swaps.huntall"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}/swaps.hair"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"

mapfile -t mods < <(ls "$SRC"/*.dxil.spv | sort)
n=${#mods[@]}
half=$(( (n + 1) / 2 ))

case "${1:-all}" in
    A)    lo=0;    hi=$half ;;
    B)    lo=$half; hi=$n ;;
    all)  lo=0;    hi=$n ;;
    range) lo=${2:?range needs LO}; hi=$((${3:?range needs HI} + 1)) ;;
    list)
        echo "half A (0..$((half-1))):"
        for ((i=0; i<half; i++)); do echo "  $(basename "${mods[$i]}")"; done
        echo "half B ($half..$((n-1))):"
        for ((i=half; i<n; i++)); do echo "  $(basename "${mods[$i]}")"; done
        exit 0 ;;
    *) echo "usage: $0 A|B|all|list" >&2; exit 2 ;;
esac

rm -f "$DEST"/*.dxil.spv
for ((i=lo; i<hi; i++)); do cp "${mods[$i]}" "$DEST/"; done
rm -f "${DEST%/swaps.hair}/hair.disable"
rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
: > ~/callisto_swap.jsonl
echo "installed $((hi-lo))/$n hunt modules [$1] -> $DEST ; caches cleared ; relaunch"
