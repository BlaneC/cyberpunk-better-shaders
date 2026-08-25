#!/usr/bin/env bash
# CallistoSSS -- sync the CET settings file to the RED4ext plugin's
# disable.flag. The plugin checks that flag when the engine uploads the SSS
# kernel (once, at boot), so this only has to run before the game starts.
#
# Steam launch options (install.sh prints the exact line for your setup):
#   "<game>/red4ext/plugins/CallistoSSS/sync_settings.sh"; %command%
set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_DIR="$(cd "$PLUGIN_DIR/../../.." && pwd)"
# CET sandboxes each mod's file I/O to its own folder, so the settings UI
# writes here:
PARAMS="$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt"
FLAG="$PLUGIN_DIR/disable.flag"

kernel=on
if [[ -f "$PARAMS" ]]; then
    while IFS='=' read -r k v; do
        v="${v%$'\r'}"
        [[ "$k" == "kernel" ]] && kernel="$v"
    done < "$PARAMS"
fi

if [[ "$kernel" == "off" ]]; then
    echo 1 > "$FLAG"
    echo "[CallistoSSS] kernel swap disabled (disable.flag written)"
else
    rm -f "$FLAG"
    echo "[CallistoSSS] kernel swap enabled"
fi
