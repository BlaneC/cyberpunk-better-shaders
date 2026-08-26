#!/usr/bin/env bash
# CallistoSSS -- sync the CET settings file (brdf_params.txt) to the flags the
# swap layer and the RED4ext plugin read at boot. Runs once before each launch
# via the Steam launch options; every toggle takes effect on the NEXT launch
# and never needs a patcher re-run (the overlays are pre-built, so toggling
# only moves flag files / pre-built swap files around).
#
# Steam launch options (install.sh prints the exact line for your setup):
#   "<game>/red4ext/plugins/CallistoSSS/sync_settings.sh"; %command%
set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_DIR="$(cd "$PLUGIN_DIR/../../.." && pwd)"
# CET sandboxes each mod's file I/O to its own folder, so the settings UI
# writes here:
PARAMS="$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt"
# RED4ext plugin checks this when the engine uploads the SSS kernel (once/boot):
KERNEL_FLAG="$PLUGIN_DIR/disable.flag"
# The Vulkan swap layer is installed as an IMPLICIT layer from $HOME and finds
# its swap dirs next to its own .so via dladdr:
INSTALL_DIR="$HOME/.local/lib/callisto"

tier=1 kernel=on hair=on skinray=on shadowcull=on
if [[ -f "$PARAMS" ]]; then
    while IFS='=' read -r k v; do
        v="${v%$'\r'}"
        case "$k" in
            tier|kernel|hair|skinray|shadowcull) printf -v "$k" '%s' "$v" ;;
        esac
    done < "$PARAMS"
fi

mkdir -p "$INSTALL_DIR/swaps"

# kernel -- SSS diffusion kernel (RED4ext).
if [[ "$kernel" == "off" ]]; then
    echo 1 > "$KERNEL_FLAG"
else
    rm -f "$KERNEL_FLAG"
fi

# hair -- the compute-resolve hair overlay (aniso + dual lobe + sheen + wrap).
if [[ "$hair" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/hair.disable"
else
    rm -f "$INSTALL_DIR/hair.disable"
fi

# shadowcull -- the hair shadow leak fix overlay.
if [[ "$shadowcull" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/shadowcull.disable"
else
    rm -f "$INSTALL_DIR/shadowcull.disable"
fi

# skinray -- the tier-1 raygen sampling (eval-invisible skin BRDF). The
# pristine copies live in swaps.prehunt/; off removes them from swaps/.
if [[ "$skinray" == "off" ]]; then
    rm -f "$INSTALL_DIR/swaps/"*.rgs_reference_main.spv
elif [[ "$tier" != "off" ]]; then
    cp -f "$INSTALL_DIR/swaps.prehunt/"*.rgs_reference_main.spv \
          "$INSTALL_DIR/swaps/" 2>/dev/null || true
fi

# tier -- the master Callisto BRDF switch. Off empties swaps/ so the layer
# passes through (bit-exact vanilla); on restores the raygens if missing.
if [[ "$tier" == "off" ]]; then
    rm -f "$INSTALL_DIR/swaps/"*.spv
else
    for f in "$INSTALL_DIR/swaps.prehunt/"*.rgs_reference_main.spv; do
        [[ -f "$f" ]] || continue
        base="$(basename "$f")"
        [[ -f "$INSTALL_DIR/swaps/$base" ]] || cp -f "$f" "$INSTALL_DIR/swaps/"
    done
fi

echo "[CallistoSSS] synced: tier=$tier kernel=$kernel hair=$hair skinray=$skinray shadowcull=$shadowcull"
