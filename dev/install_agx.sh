#!/usr/bin/env bash
# Install / remove the AgX tonemapper swap.
#
#   ./dev/install_agx.sh neutral|punchy70|punchy70desat|punchy|golden|...
#   ./dev/install_agx.sh off        # back to the game's own tonemapper
#   ./dev/install_agx.sh list
#
# All variants are now graded in BOTH display modes: AgX is fed the game's own
# graded, exposure-scaled scene colour, and in SDR it REPLACES the game's tone
# curve rather than running before it.
#
#   punchy70            the reference look
#   punchy70desat       punchy70 with 7.5% less chroma, nothing else changed
#   punchy70.sat95      5% less chroma than punchy70   ) brackets desat, to
#   punchy70.sat90      10% less chroma than punchy70  ) settle it in one go
#
# A/B legs:
#   punchy70.preexp     graded, no exposure -- grade vs exposure, disambiguated
#   punchy70.nograde    AgX at the right sites but fed the raw shaper: no
#                       grade, no exposure
#   punchy70.hue        punchy70 + hue_restore=0.5, for highlights that read
#                       white when the grade says they should read warm
#
# Goes into the base `swaps/` overlay, which the layer always loads while
# tier != off -- no swap-layer change needed, and sync_settings.sh's cache
# stamp already hashes swaps/*.spv, so the pipeline caches evict correctly.
# (`tier=off` in the CET page wipes swaps/ and therefore removes this too;
# that is the intended "vanilla everything" behaviour.)
set -euo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}/swaps"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
# Ten permutations of the LUT generator: the HDR pair plus eight SDR ones.
# Install all of them or the effect appears in only some display modes.
IDS=(b174eb4af0fea652.dxil 1d02efd8fe8014cc.dxil
     065fcdcc6ce51fe7.dxil 1c9000b415918fb1.dxil 6040914437ae18cb.dxil
     7a858d59a4d6705c.dxil 8bbd5900a4074442.dxil 90fa8b3f5068b7d8.dxil
     e0e20375b6685f6a.dxil ef31e1058af96c51.dxil)

case "${1:-list}" in
    list)
        echo "available:"
        for d in "$MOD_DIR"/swaps.agx.*; do
            [[ -d $d ]] && echo "  ${d##*swaps.agx.}"
        done
        n=0
        for ID in "${IDS[@]}"; do
            if [[ -f "$DEST/$ID.spv" ]]; then n=$((n+1)); else echo "  missing: $ID"; fi
        done
        echo "installed: $n/${#IDS[@]} permutations"
        (( n == ${#IDS[@]} )) || echo "  (incomplete: display modes use different permutations)"
        exit 0 ;;
    off)
        for ID in "${IDS[@]}"; do rm -f "$DEST/$ID.spv"; done
        echo "AgX removed -- vanilla tonemapper" ;;
    *)
        SRC="$MOD_DIR/swaps.agx.$1"
        [[ -d $SRC ]] || { echo "no variant '$1' (try: list)" >&2; exit 2; }
        for ID in "${IDS[@]}"; do
            [[ -f "$SRC/$ID.spv" ]] || { echo "variant '$1' is missing $ID -- rebuild it" >&2; exit 2; }
            cp -f "$SRC/$ID.spv" "$DEST/"
        done
        echo "AgX '$1' installed (${#IDS[@]} permutations) -> $DEST/" ;;
esac

rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
: > ~/callisto_swap.jsonl
echo "caches cleared; relaunch. Confirm with:"
echo "  grep dispatch ~/callisto_swap.jsonl | grep -E '$(IFS='|'; echo "${IDS[*]}")'"
