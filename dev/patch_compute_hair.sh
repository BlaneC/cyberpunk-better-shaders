#!/usr/bin/env bash
# Hair tiers on the GLCompute resolve shaders (the confirmed visible surface).
#
#   ./dev/patch_compute_hair.sh --hunt          # 10-class palette: find hair's class
#   ./dev/patch_compute_hair.sh --hair N        # the hair BRDF, gated on class N
#
# --hunt first (one launch, read hair's colour off the legend), then --hair N.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps}"
WORK="$MOD_DIR/dev/disasm/compute"

TIER=""; CLASS=""
while (( $# )); do
    case "$1" in
        --hunt) TIER=hairhunt ;;
        --hair) TIER=hair; CLASS="${2:?--hair needs a class number}"; shift ;;
        -*) echo "unknown flag: $1" >&2; exit 2 ;;
        *)  DUMP_DIR="$1" ;;
    esac
    shift
done
[[ -n "$TIER" ]] || { echo "usage: $0 --hunt | --hair N" >&2; exit 2; }

mapfile -t targets < <(python3 - "$DUMP_DIR" <<'PY'
import glob, struct, sys
pi = struct.pack('<f', 0.318309873)
k = struct.pack('<f', 0.107508637)
for f in sorted(glob.glob(sys.argv[1] + '/*.dxil.spv')):
    d = open(f, 'rb').read()
    if pi in d and k in d:
        print(f)
PY
)
echo "=== tier $TIER${CLASS:+ (class $CLASS)} | ${#targets[@]} anchored compute libs ==="

mkdir -p "$WORK"
rm -f "$SWAPS"/*.dxil.spv "$SWAPS"/*.dxil.spvasm 2>/dev/null || true

ARGS=(--tier "$TIER")
[[ "$TIER" == hair ]] && ARGS+=(--with-tier1)   # Callisto tier-1 skin c1 rides along
[[ -n "$CLASS" ]] && ARGS+=(--hair-class "$CLASS")

pass=(); fail=()
for f in "${targets[@]}"; do
    name="$(basename "${f%.spv}")"
    asm="$WORK/$name.spvasm"
    [[ -f "$asm" ]] || spirv-dis "$f" -o "$asm" 2>/dev/null || { fail+=("$name"); continue; }
    if python3 "$MOD_DIR/dev/patch_compute_hair.py" "$asm" "${ARGS[@]}" \
            --outdir "$SWAPS" > "$SWAPS/.hair.$name.json" 2>"$SWAPS/.hair.$name.err"; then
        pass+=("$name")
    else
        fail+=("$name")
    fi
done
echo "patched ${#pass[@]}, failed ${#fail[@]}"
if (( ${#fail[@]} > 0 )); then
    for n in "${fail[@]}"; do
        echo "  $n :: $(sed 's/.*error: //' "$SWAPS/.hair.$n.err" 2>/dev/null | head -1 | cut -c1-70)"
    done | sort | uniq -c | sort -rn | head -8
fi
(( ${#pass[@]} > 0 )) || { echo "nothing patched" >&2; exit 1; }

if [[ "$TIER" == hairhunt ]]; then
    echo "=== colour legend (read hair's colour, then run --hair N) ==="
    python3 - "$MOD_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + '/dev')
from patch_skin_brdf import HUNT_PALETTE, HUNT_DEFAULT
for n in HUNT_DEFAULT:
    name, _ = HUNT_PALETTE[n]
    print(f"  class {n:>2} = {name}" + ("   <- skin, CONTROL" if n == 1 else ""))
PY
fi

# Hair ships as an OVERLAY: the layer checks swaps.hair/ before swaps/, and
# skips it entirely when <layerdir>/hair.disable exists. That makes the CET
# toggle a one-file, one-relaunch operation with no re-patching.
DEST="$INSTALL_DIR/swaps.hair"
mkdir -p "$DEST"
rm -f "$DEST"/*.dxil.spv
cp -f "$SWAPS"/*.dxil.spv "$DEST/"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
inst=("$DEST"/*.dxil.spv)
echo "installed ${#inst[@]} compute swap(s) -> $DEST (overlay 'hair')"
if [[ -f "$INSTALL_DIR/hair.disable" ]]; then
    echo "NOTE: hair.disable present -- effect is currently OFF (remove it, or set hair=on in the CET settings)"
fi

if [[ -z "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared"
fi
echo "next: : > ~/callisto_swap.jsonl ; launch ; character in frame"
