#!/usr/bin/env bash
# CallistoSSS uninstaller (Linux / Proton).
# Removes the game payload, the Vulkan layer, and the layer manifest, then
# clears the shader/pipeline caches so the game rebuilds vanilla pipelines.
#
# Usage:
#   ./uninstall.sh [--game-dir "/path/to/Cyberpunk 2077"] [--keep-cache] [--dry-run]
set -euo pipefail

GAME_DIR=""
KEEP_CACHE=0
DRY=0

say()  { echo "[CallistoSSS] $*"; }
die()  { echo "[CallistoSSS] ERROR: $*" >&2; exit 1; }
run()  { if (( DRY )); then echo "[dry-run] $*"; else "$@"; fi }

while (( $# )); do
    case "$1" in
        --game-dir)   GAME_DIR="${2:?--game-dir needs a path}"; shift 2 ;;
        --keep-cache) KEEP_CACHE=1; shift ;;
        --dry-run)    DRY=1; shift ;;
        -h|--help)    sed -n '2,9p' "$0"; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

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
    for lib in "${candidate_libs[@]:-}"; do
        [[ -n "$lib" ]] || continue
        g="$lib/steamapps/common/Cyberpunk 2077"
        if is_game_dir "$g"; then GAME_DIR="$g"; break; fi
    done
    [[ -n "$GAME_DIR" ]] || die "could not find Cyberpunk 2077; pass --game-dir"
fi
LIB_ROOT="$(cd "$GAME_DIR/../../.." && pwd)"
say "game: $GAME_DIR"

say "removing game payload..."
run rm -rf "$GAME_DIR/red4ext/plugins/CallistoSSS"
run rm -rf "$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS"

say "removing Vulkan layer..."
run rm -rf "$HOME/.local/lib/callisto"
run rm -f "$HOME/.local/share/vulkan/implicit_layer.d/VkLayer_callisto_spvswap.json"

if (( KEEP_CACHE )); then
    say "keeping caches (--keep-cache) -- vanilla may not be restored until they are cleared."
else
    say "clearing shader/pipeline caches..."
    [[ -d "$GAME_DIR/bin/x64/GLCache" ]] && run rm -rf "$GAME_DIR/bin/x64/GLCache"/*
    [[ -d "$LIB_ROOT/steamapps/shadercache/1091500" ]] && run rm -rf "$LIB_ROOT/steamapps/shadercache/1091500"/*
fi

say "uninstall complete. You can also remove the launch-options line in Steam."
