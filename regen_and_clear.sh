#!/usr/bin/env bash
# Regenerate the Callisto BRDF swap set from the params file the CET sliders
# write, then clear the pipeline caches so the next game launch picks it up.
# Intended for Steam launch options:
#   "/path/to/regen_and_clear.sh"; VK_ADD_LAYER_PATH=... %command%
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_DIR="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077"
SHADERCACHE="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500"
# CET sandboxes mod file I/O to the mod's own folder, so the sliders write here:
PARAMS="$GAME_DIR/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS/brdf_params.txt"
KERNEL_FLAG="$GAME_DIR/red4ext/plugins/CallistoSSS/disable.flag"
PATCHER="$MOD_DIR/dev/patch_skin_brdf.py"
SPVASM_DIR="$MOD_DIR/dev/disasm"
SWAPS="$MOD_DIR/swaps"
LOG="$MOD_DIR/regen.log"
# The game runs inside the Steam Linux Runtime container, which cannot see the
# repo path; the layer is installed as an IMPLICIT layer from $HOME (visible
# inside the container) and finds its swaps next to its own .so via dladdr.
INSTALL_DIR="$HOME/.local/lib/callisto"

sync_install() {
    mkdir -p "$INSTALL_DIR/swaps"
    cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
    rm -f "$INSTALL_DIR/swaps"/*.spv
    if compgen -G "$SWAPS/*.spv" > /dev/null; then
        cp -f "$SWAPS"/*.spv "$INSTALL_DIR/swaps/"
        echo "installed $(ls "$INSTALL_DIR/swaps" | wc -l) swap(s) to $INSTALL_DIR/swaps"
    else
        echo "no swaps to install (passthrough)"
    fi
}

exec >>"$LOG" 2>&1
echo "=== regen $(date -Is) ==="

# --- read params (key=value; CRLF tolerated) ---
tier=1 kernel=on hair=on skinray=on shadowcull=on rho_f=1.35 rho_r=1.25 n_f=0.75 m_f=0.75 n_r=0.75 m_r=0.75
if [[ -f "$PARAMS" ]]; then
    while IFS='=' read -r k v; do
        v="${v%$'\r'}"
        case "$k" in
            tier|kernel|hair|skinray|shadowcull)  printf -v "$k" '%s' "$v" ;;
            rho_f|rho_r|n_f|m_f|n_r|m_r) printf -v "$k" '%s' "$v" ;;
        esac
    done < "$PARAMS"
    echo "params: tier=$tier kernel=$kernel hair=$hair rho_f=$rho_f rho_r=$rho_r n_f=$n_f m_f=$m_f n_r=$n_r m_r=$m_r"
else
    echo "no params file at $PARAMS — using defaults"
fi

# sync the RED4ext kernel-swap flag (the DLL checks disable.flag per upload)
# sync the hair overlay flag. The layer serves $INSTALL_DIR/swaps.hair/ ahead
# of swaps/ unless hair.disable exists, so this toggle needs no re-patching --
# and because the hair build lives in its own directory, sync_install's
# "rm swaps/*.spv" never touches it.
mkdir -p "$INSTALL_DIR"
# skinray: the original Callisto tier-1 raygen build (sampling-side skin
# BRDF). Eval-invisible but empirically measurable in the sampling; kept as
# an option. Files come from the pre-hunt backup.
if [[ "$skinray" == "off" ]]; then
    rm -f "$INSTALL_DIR/swaps/d622fb9e1dcb8cd0.rgs_reference_main.spv" \
          "$INSTALL_DIR/swaps/40c6faab52a13874.rgs_reference_main.spv"
    echo "skin raygen sampling disabled"
else
    cp -f "$INSTALL_DIR/swaps.prehunt/"*.rgs_reference_main.spv \
          "$INSTALL_DIR/swaps/" 2>/dev/null && echo "skin raygen sampling enabled (tier-1 prehunt build)"
fi

if [[ "$shadowcull" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/shadowcull.disable"; echo "hair shadow leak fix disabled"
else
    rm -f "$INSTALL_DIR/shadowcull.disable"; echo "hair shadow leak fix enabled"
fi

if [[ "$hair" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/hair.disable"; echo "hair anisotropy disabled"
else
    rm -f "$INSTALL_DIR/hair.disable"; echo "hair anisotropy enabled"
fi

if [[ "$kernel" == "off" ]]; then
    echo 1 > "$KERNEL_FLAG"; echo "kernel swap disabled"
else
    rm -f "$KERNEL_FLAG"; echo "kernel swap enabled"
fi

clear_caches() {
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared"
}

if [[ "$tier" == "off" ]]; then
    rm -f "$SWAPS"/*.spv
    sync_install
    clear_caches
    echo "tier=off — swaps removed, layer will pass through"
    exit 0
fi

extra=()
[[ "$tier" == "vanilla" ]] && extra+=(--vanilla) && tier=1

if python3 "$PATCHER" --tier "$tier" "${extra[@]}" \
        --set rho_f="$rho_f" --set rho_r="$rho_r" \
        --set n_f="$n_f" --set m_f="$m_f" --set n_r="$n_r" --set m_r="$m_r" \
        --outdir "$SWAPS" \
        "$SPVASM_DIR/spv_0170.spvasm" "$SPVASM_DIR/spv_0171.spvasm" \
        > "$SWAPS/tier${tier}_report.json"; then
    sync_install
    clear_caches
    echo "regen OK"
else
    echo "PATCHER FAILED — keeping previous swaps, caches NOT cleared"
    exit 1
fi
