#!/usr/bin/env bash
# Patch the GLCompute lighting-resolve shaders -- where the visible pixels are
# actually shaded (handoff/07-COMPUTE-RESOLVE.md).
#
#   ./dev/patch_compute_perms.sh              # skin-gated red at every resolve write
#   ./dev/patch_compute_perms.sh --ungated    # red everywhere (bisect step)
#
# Selects every dumped whole-library module that carries BOTH shading anchors
# (1/pi and the Disney 0.107508637 constant) and tints the r,g,b of each
# OpImageWrite, gated on the module's own gbuf>>5==1 skin test. RT raygen and
# hit-shader swaps are left installed.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps}"
WORK="$MOD_DIR/dev/disasm/compute"

EXTRA=()
for a in "$@"; do
    case "$a" in
        --ungated) EXTRA+=(--ungated) ;;
        -*) echo "unknown flag: $a" >&2; exit 2 ;;
        *)  DUMP_DIR="$a" ;;
    esac
done

# Anchored = contains both float32(1/pi) and float32(0.107508637) as bytes.
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
if (( ${#targets[@]} == 0 )); then
    echo "no anchored compute libraries in $DUMP_DIR" >&2
    exit 1
fi
echo "=== ${#targets[@]} anchored compute librar(ies) in $DUMP_DIR ==="

rm -rf "$WORK"; mkdir -p "$WORK"
rm -f "$SWAPS"/*.dxil.spv "$SWAPS"/*.dxil.spvasm 2>/dev/null || true

pass=(); fail=()
for f in "${targets[@]}"; do
    name="$(basename "${f%.spv}")"
    asm="$WORK/$name.spvasm"
    spirv-dis "$f" -o "$asm" 2>/dev/null || { fail+=("$name"); continue; }
    if python3 "$MOD_DIR/dev/patch_compute_brdf.py" "$asm" "${EXTRA[@]}" \
            --outdir "$SWAPS" > "$SWAPS/.cm.$name.json" 2>"$SWAPS/.cm.$name.err"; then
        pass+=("$name")
    else
        fail+=("$name")
    fi
done

echo "patched ${#pass[@]}, failed ${#fail[@]}"
if (( ${#fail[@]} > 0 )); then
    echo "--- failures (first line each) ---"
    for n in "${fail[@]}"; do
        echo "  $n :: $(sed 's/.*error: //' "$SWAPS/.cm.$n.err" 2>/dev/null | head -1 | cut -c1-70)"
    done
fi
if (( ${#pass[@]} == 0 )); then
    echo "nothing patched -- no swaps installed" >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR/swaps"
rm -f "$INSTALL_DIR/swaps"/*.dxil.spv
cp -f "$SWAPS"/*.dxil.spv "$INSTALL_DIR/swaps/"
inst=("$INSTALL_DIR/swaps"/*.dxil.spv)
echo "installed ${#inst[@]} compute swap(s) -> $INSTALL_DIR/swaps"

if [[ -n "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    echo "cache clear SKIPPED (CALLISTO_NO_CACHE_CLEAR set)"
else
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared (first launch after this will be slow -- normal)"
fi

cat <<'MSG'

Next:
  : > ~/callisto_swap.jsonl
  launch (any RT/PT mode), reach gameplay with a character in frame:
    grep '"swap":"HIT"' ~/callisto_swap.jsonl | grep -c dxil

  skin red        -> compute resolve confirmed as the visible shading surface;
                     the class-hunt palette ports here directly (same gate).
  everything red  -> only with --ungated; same conclusion.
  no change       -> the HIT lines will say whether the swaps were even
                     served; if they were, the resolve set is incomplete --
                     re-dump with no CALLISTO_DUMP_MATCH and widen.
MSG
