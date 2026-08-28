#!/usr/bin/env bash
# Install / bisect the unconditional-tint net (dev/build_tintnet.sh) to find
# which indirect-light evaluator paints interior hair.
#
#   ./dev/bisect_tint.sh all        # all 15 (start here)
#   ./dev/bisect_tint.sh A | B      # halves
#   ./dev/bisect_tint.sh range 4 7  # inclusive index range
#   ./dev/bisect_tint.sh one <id>   # a single module
#   ./dev/bisect_tint.sh fam B|C|D  # one lighting family
#   ./dev/bisect_tint.sh list
#   ./dev/bisect_tint.sh off        # restore vanilla (empty overlay)
#
# These modules carry NO class gate -- they are tile-classified permutations,
# so dispatch is the gate and the tint paints exactly the tiles the module
# owns.  Expect broad red wherever the module runs, not a hair-shaped mask:
# the question is whether INTERIOR (shadowed) hair reddens, which names the
# module that lights it.
#
# Shares the "hair" overlay slot with dev/bisect_hunt.sh -- only one net can be
# installed at a time.  `bisect_hunt.sh all` restores the palette net.
set -euo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$MOD_DIR/swaps.tintall"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}/swaps.hair"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"

FAM_B='1ecc0c40|23bb4979|66d2f831|9112430b|99bb7c26|afe73b89|ce2a6197|d48dd37d'
FAM_C='1921a495|705c012d|a5f4a903|f209f068|f9a66670'
FAM_D='204eaf5b|384aa954|5f0de0f5|6e91dc5e|84ea63ad|85119cfc|9731d633|ac38cf69|cbaeaa8c'

[[ -d $SRC ]] || { echo "no $SRC -- run dev/build_tintnet.sh first" >&2; exit 2; }
mapfile -t mods < <(ls "$SRC"/*.dxil.spv 2>/dev/null | sort)
n=${#mods[@]}
(( n > 0 )) || { echo "$SRC is empty -- run dev/build_tintnet.sh" >&2; exit 2; }
half=$(( (n + 1) / 2 ))
sel=()

case "${1:-all}" in
    A)     sel=("${mods[@]:0:$half}") ;;
    B)     sel=("${mods[@]:$half}") ;;
    all)   sel=("${mods[@]}") ;;
    off)   sel=() ;;
    range) lo=${2:?range needs LO}; hi=${3:?range needs HI}
           sel=("${mods[@]:$lo:$((hi-lo+1))}") ;;
    one)   id=${2:?one needs an id}
           for m in "${mods[@]}"; do [[ $(basename "$m") == "$id"* ]] && sel+=("$m"); done
           (( ${#sel[@]} )) || { echo "no module matching $id in $SRC" >&2; exit 2; } ;;
    fam)   case "${2:?fam needs B|C|D}" in
               B) pat=$FAM_B ;; C) pat=$FAM_C ;; D) pat=$FAM_D ;;
               *) echo "fam takes B, C or D" >&2; exit 2 ;;
           esac
           for m in "${mods[@]}"; do
               [[ $(basename "$m") =~ ^($pat) ]] && sel+=("$m")
           done ;;
    list)  for ((i=0; i<n; i++)); do
               b=$(basename "${mods[$i]}" .dxil.spv)
               f='?'
               [[ $b =~ ^($FAM_B) ]] && f=B
               [[ $b =~ ^($FAM_C) ]] && f=C
               [[ $b =~ ^($FAM_D) ]] && f=D
               printf '%3d  %s  family %s\n' "$i" "$b" "$f"
           done
           echo "(half A = 0..$((half-1)), half B = $half..$((n-1)))"
           exit 0 ;;
    *) echo "usage: $0 all|A|B|range LO HI|one ID|fam B|C|D|list|off" >&2; exit 2 ;;
esac

rm -f "$DEST"/*.dxil.spv
for m in ${sel[@]+"${sel[@]}"}; do cp "$m" "$DEST/"; done
rm -f "${DEST%/swaps.hair}/hair.disable"
rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
: > ~/callisto_swap.jsonl
echo "installed ${#sel[@]}/$n tint modules [$*] -> $DEST ; caches cleared ; relaunch"
