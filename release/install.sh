#!/usr/bin/env bash
# CallistoSSS installer (Linux / Proton).
#
# Installs three things:
#   1. game payload   -> <game>/red4ext/plugins/CallistoSSS/ and the CET mod
#   2. Vulkan layer   -> ~/.local/lib/callisto/ (.so + swaps)
#   3. layer manifest -> ~/.local/share/vulkan/implicit_layer.d/ (generated
#                        with your absolute path, so it loads inside the
#                        Steam Linux Runtime container)
# then clears the shader/pipeline caches (required for the swap to take
# effect) and prints the Steam launch-options line to paste.
#
# Usage:
#   ./install.sh [--game-dir "/path/to/Cyberpunk 2077"] [--keep-cache] [--dry-run]
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_DIR=""
KEEP_CACHE=0
DRY=0

say()  { echo "[CallistoSSS] $*"; }
warn() { echo "[CallistoSSS] WARNING: $*" >&2; }
die()  { echo "[CallistoSSS] ERROR: $*" >&2; exit 1; }
run()  { if (( DRY )); then echo "[dry-run] $*"; else "$@"; fi }

while (( $# )); do
    case "$1" in
        --game-dir)   GAME_DIR="${2:?--game-dir needs a path}"; shift 2 ;;
        --keep-cache) KEEP_CACHE=1; shift ;;
        --dry-run)    DRY=1; shift ;;
        -h|--help)    sed -n '2,16p' "$0"; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

# ---------------------------------------------------------- find the game
steam_roots=(
    "$HOME/.steam/steam"
    "$HOME/.steam/debian-installation"
    "$HOME/.local/share/Steam"
)

candidate_libs=()
for root in "${steam_roots[@]}"; do
    vdf="$root/steamapps/libraryfolders.vdf"
    [[ -f "$vdf" ]] || continue
    candidate_libs+=("$root")
    while IFS= read -r p; do
        candidate_libs+=("$p")
    done < <(sed -n 's/.*"path"[[:space:]]*"\([^"]*\)".*/\1/p' "$vdf")
done

is_game_dir() { [[ -f "$1/bin/x64/Cyberpunk2077.exe" ]]; }

if [[ -n "$GAME_DIR" ]]; then
    is_game_dir "$GAME_DIR" || die "no bin/x64/Cyberpunk2077.exe under '$GAME_DIR'"
else
    seen=""
    for lib in "${candidate_libs[@]:-}"; do
        [[ -n "$lib" ]] || continue
        g="$lib/steamapps/common/Cyberpunk 2077"
        case " $seen " in *" $g "*) continue ;; esac
        seen="$seen $g"
        if is_game_dir "$g"; then GAME_DIR="$g"; break; fi
    done
    [[ -n "$GAME_DIR" ]] || die "could not find Cyberpunk 2077 in any Steam library.
Re-run with: ./install.sh --game-dir \"/path/to/Cyberpunk 2077\""
fi
LIB_ROOT="$(cd "$GAME_DIR/../../.." && pwd)"  # the Steam library root
say "game: $GAME_DIR"

# ---------------------------------------------------------- sanity checks
[[ -d "$GAME_DIR/red4ext" ]] || warn "red4ext not found -- install RED4ext first or the kernel swap will not load."
[[ -d "$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks" ]] || warn "Cyber Engine Tweaks not found -- the in-game toggle will be unavailable (kernel stays ON)."

# ---------------------------------------------------------- 1. game payload
say "installing game payload..."
run cp -a "$SRC/game/." "$GAME_DIR/"

# ---------------------------------------------------------- 2. vulkan layer
LIB_DIR="$HOME/.local/lib/callisto"
LAYER_DIR="$HOME/.local/share/vulkan/implicit_layer.d"
say "installing Vulkan layer to $LIB_DIR ..."
run mkdir -p "$LIB_DIR/swaps" "$LAYER_DIR"
run cp -f "$SRC/vulkan/libVkLayer_callisto_spvswap.so" "$LIB_DIR/"
run cp -f "$SRC/vulkan/swaps/"*.spv "$LIB_DIR/swaps/"

# ---------------------------------------------------------- 3. manifest
MANIFEST="$LAYER_DIR/VkLayer_callisto_spvswap.json"
say "writing layer manifest: $MANIFEST"
if (( DRY )); then
    sed "s|@CALLISTO_LIB@|$LIB_DIR|g" "$SRC/vulkan/VkLayer_callisto_spvswap.json"
else
    sed "s|@CALLISTO_LIB@|$LIB_DIR|g" "$SRC/vulkan/VkLayer_callisto_spvswap.json" > "$MANIFEST"
fi

# ---------------------------------------------------------- 4. caches
# vkd3d/fossilize/NVIDIA cache the *pipeline*, not just the module: without
# this the swapped shader may never be picked up.
if (( KEEP_CACHE )); then
    say "keeping caches (--keep-cache) -- if the mod does not appear, clear them:"
    say "  rm -rf \"$GAME_DIR/bin/x64/GLCache\"/* \"$LIB_ROOT/steamapps/shadercache/1091500\"/*"
else
    say "clearing shader/pipeline caches..."
    [[ -d "$GAME_DIR/bin/x64/GLCache" ]] && run rm -rf "$GAME_DIR/bin/x64/GLCache"/*
    [[ -d "$LIB_ROOT/steamapps/shadercache/1091500" ]] && run rm -rf "$LIB_ROOT/steamapps/shadercache/1091500"/*
fi

# ---------------------------------------------------------- done
cat <<EOF

[CallistoSSS] install complete.

LAST STEP -- set the Steam launch options for Cyberpunk 2077 to:

  "$GAME_DIR/red4ext/plugins/CallistoSSS/sync_settings.sh"; CALLISTO_LOG=\$HOME/callisto_swap.jsonl %command%

(Right-click the game -> Properties -> Launch Options.)

Vanilla control run:  prefix the line with CALLISTO_LAYER_DISABLE=1
Verify the layer:     vulkaninfo --summary | grep -i callisto
In-game proof:        grep HIT \$HOME/callisto_swap.jsonl
EOF
