#!/usr/bin/env bash
# Build + install a class-hunt swap set, then clear the pipeline caches.
#
#   ./dev/hunt_hair_class.sh                 # tint all default candidates
#   ./dev/hunt_hair_class.sh 2,3,4           # only these classes
#   ./dev/hunt_hair_class.sh --restore       # put the previous swaps back
#   ./dev/hunt_hair_class.sh --off           # remove swaps, back to vanilla
#
# The installed swaps are backed up on the first hunt run, so --restore
# returns the exact skin build that was in place beforehand.
#
# Launch options need no change: sync_settings.sh only syncs the SSS kernel
# flag, and the layer is installed implicitly from $HOME (nothing in the
# launch line rebuilds swaps).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_DIR="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077"
SHADERCACHE="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500"
INSTALL_DIR="$HOME/.local/lib/callisto"
BACKUP_DIR="$HOME/.local/lib/callisto/swaps.prehunt"
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

backup_once() {
    # Only ever taken once: a second hunt run must not overwrite the backup
    # with hunt swaps, or --restore would hand back the wrong thing.
    if [[ ! -d "$BACKUP_DIR" ]]; then
        mkdir -p "$BACKUP_DIR"
        if compgen -G "$INSTALL_DIR/swaps/*.spv" > /dev/null; then
            cp -f "$INSTALL_DIR/swaps"/*.spv "$BACKUP_DIR/"
            echo "backed up $(ls "$BACKUP_DIR" | wc -l) pre-hunt swap(s) to $BACKUP_DIR"
        else
            echo "no pre-hunt swaps to back up (was passthrough)"
        fi
    fi
}

if [[ "${1:-}" == "--restore" ]]; then
    if [[ ! -d "$BACKUP_DIR" ]]; then
        echo "no backup at $BACKUP_DIR -- nothing to restore"; exit 1
    fi
    mkdir -p "$INSTALL_DIR/swaps"
    rm -f "$INSTALL_DIR/swaps"/*.spv
    if compgen -G "$BACKUP_DIR/*.spv" > /dev/null; then
        cp -f "$BACKUP_DIR"/*.spv "$INSTALL_DIR/swaps/"
        echo "restored $(ls "$INSTALL_DIR/swaps" | wc -l) swap(s)"
    else
        echo "backup was empty -- restored to passthrough"
    fi
    clear_caches
    exit 0
fi

if [[ "${1:-}" == "--off" ]]; then
    backup_once
    rm -f "$SWAPS"/*.spv
    install_swaps
    clear_caches
    echo "swaps removed -- layer passes through, game is vanilla"
    echo "run --restore to put the pre-hunt swaps back"
    exit 0
fi

backup_once

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
cat <<'MSG'

Launch the game, then:
  1. confirm the swap took effect --
       grep -c '"swap":"HIT"' ~/callisto_swap.jsonl     (expect 2)
     if that is 0, the shaders came from cache or the layer is not loading;
     nothing on screen is meaningful until it reads 2. Note the log APPENDS
     across runs, so truncate it first to read a single session:
       : > ~/callisto_swap.jsonl
  2. check SKIN is red (class 1 is the control).
  3. read hair's colour off the legend above.

When done:  ./dev/hunt_hair_class.sh --restore
MSG
