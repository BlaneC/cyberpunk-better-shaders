#!/usr/bin/env bash
# Install the "shadowcull" overlay: shadow rays stop culling back-facing
# triangles, so thin double-sided hair cards occlude from either side.
# Fixes the overlit gap at the hairline seam. See dev/patch_shadow_flags.py.
#
#   ./dev/patch_shadow_flags.sh
#
# Toggle without re-patching: CET switch "Hair shadow leak fix", or
# touch/rm ~/.local/lib/callisto/shadowcull.disable
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps.shadowcull}"
WORK="$MOD_DIR/dev/disasm/shadowflags"

shopt -s nullglob
mkdir -p "$WORK" "$SWAPS"
rm -f "$SWAPS"/*.spv "$SWAPS"/*.spvasm

pass=(); skip=0; fail=()
for f in "$DUMP_DIR"/*.rgs_*.spv; do
    name="$(basename "${f%.spv}")"
    asm="$WORK/$name.spvasm"
    [[ -f "$asm" ]] || spirv-dis "$f" -o "$asm" 2>/dev/null || { fail+=("$name"); continue; }
    if python3 "$MOD_DIR/dev/patch_shadow_flags.py" "$asm" --outdir "$SWAPS" \
            > "$SWAPS/.sf.$name.json" 2>"$SWAPS/.sf.$name.err"; then
        n=$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))[0]['traces']))" \
            "$SWAPS/.sf.$name.json" 2>/dev/null || echo '?')
        pass+=("$name"); echo "  patched  $name  ($n shadow trace(s) 28->12)"
    elif grep -q "no back-face-culling shadow ray" "$SWAPS/.sf.$name.err"; then
        skip=$((skip+1))
    else
        fail+=("$name")
        echo "  FAILED   $name :: $(sed 's/.*error: //' "$SWAPS/.sf.$name.err" | head -1 | cut -c1-60)"
    fi
done

echo "patched ${#pass[@]}, skipped $skip (no culling shadow ray), failed ${#fail[@]}"
(( ${#pass[@]} > 0 )) || { echo "nothing patched" >&2; exit 1; }

DEST="$INSTALL_DIR/swaps.shadowcull"
mkdir -p "$DEST"
rm -f "$DEST"/*.spv
cp -f "$SWAPS"/*.spv "$DEST/"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
inst=("$DEST"/*.spv)
echo "installed ${#inst[@]} swap(s) -> $DEST (overlay 'shadowcull')"
[[ -f "$INSTALL_DIR/shadowcull.disable" ]] && \
    echo "NOTE: shadowcull.disable present -- currently OFF"

if [[ -z "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared"
fi
cat <<'MSG'

Watch for: the overlit gap at the hairline seam should close.
Regression to check: self-shadow acne on closed meshes (back-face culling is
often on to suppress it) and a small perf cost from more any-hit work.
Toggle off in CET ("Hair shadow leak fix") if either shows up.
MSG
