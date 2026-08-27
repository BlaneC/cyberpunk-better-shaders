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

# --- pipeline cache gate ---------------------------------------------------
# Flag files alone are not enough. Once a pipeline is cached, the game never
# calls vkCreateShaderModule for its shaders again -- the layer never sees the
# module, and the swap silently does nothing. This is only visible on the
# GLCompute resolve modules (the RT raygens are rebuilt every launch), which
# is exactly where every visible effect lives, so a stale cache reads as "the
# mod does nothing" with a perfectly healthy-looking flag state.
#
# So: whenever the effective settings differ from what the caches were last
# built against, evict them. Unchanged settings cost nothing.
#
# Caveat: a launch that bypasses this script (no launch options, or
# CALLISTO_LAYER_DISABLE=1) recompiles vanilla pipelines without updating the
# stamp. Run vanilla A/B halves through the CET toggles instead -- that moves
# the stamp and clears the caches on the way in and on the way back out. Or
# force it with CALLISTO_FORCE_CLEAR=1.
STEAMAPPS="$(cd "$GAME_DIR/../.." 2>/dev/null && pwd || true)"
SHADERCACHE="${STEAMAPPS:+$STEAMAPPS/shadercache/1091500}"
GLCACHE="$GAME_DIR/bin/x64/GLCache"
STAMP="$PLUGIN_DIR/.cache_stamp"

# I5: key the cache on the MATERIALIZED state, not on the request. Settings
# can sit unchanged while the swap payload underneath them is regenerated
# (a patcher re-run), which is the same silent no-op in a different costume.
# Hashing the installed .spv set and the layer .so catches both.
payload="$(stat -c '%n %s %Y' \
              "$INSTALL_DIR"/swaps/*.spv \
              "$INSTALL_DIR"/swaps.hair/*.spv \
              "$INSTALL_DIR"/swaps.shadowcull/*.spv \
              "$INSTALL_DIR"/libVkLayer_callisto_spvswap.so 2>/dev/null \
           | sort | sha256sum | cut -c1-16)"
want="tier=$tier kernel=$kernel hair=$hair skinray=$skinray shadowcull=$shadowcull payload=$payload"
have="$(cat "$STAMP" 2>/dev/null || true)"
if [[ "$want" != "$have" || "${CALLISTO_FORCE_CLEAR:-0}" == "1" ]]; then
    [[ -d "$GLCACHE" ]] && rm -rf "${GLCACHE:?}/"* 2>/dev/null
    [[ -n "$SHADERCACHE" && -d "$SHADERCACHE" ]] && rm -rf "${SHADERCACHE:?}/"* 2>/dev/null
    printf '%s' "$want" > "$STAMP" 2>/dev/null
    if [[ "$want" != "$have" ]]; then why="settings changed"; else why="forced"; fi
    cache_action=cleared
    echo "[CallistoSSS] $why -- pipeline caches cleared (this launch recompiles shaders)"
else
    cache_action=kept
    echo "[CallistoSSS] settings unchanged -- pipeline caches kept"
fi

# --- status feedback loop --------------------------------------------------
# The settings page renders brdf_params.txt -- the REQUEST. Nothing ever told
# it whether the request was honoured, which is how a whole A/B session got
# shot with four of five effects silently inert (handoff/09-SETTINGS-AUDIT.md).
#
# The layer records what it actually swapped into last_run.json next to its own
# .so. CET sandboxes mod I/O to the mod folder, so the layer cannot write there
# and the page cannot read the layer's file; this script bridges the two. What
# lands in the page is necessarily the PREVIOUS launch's outcome -- this run
# has not happened yet -- so the page must label it "last launch".
LAST_RUN="$INSTALL_DIR/last_run.json"
LOADED="$INSTALL_DIR/last_run.json.loaded"   # contentless "the layer loaded"
SEEN="$PLUGIN_DIR/.layer_seen"
STATUS="$(dirname "$PARAMS")/status.txt"

# Values stay [alnum . - + _] so the Lua pattern in init.lua can read them.
jnum() { grep -o "\"$1\": *[0-9]*" "$LAST_RUN" 2>/dev/null | grep -o '[0-9]*$' | head -1; }

{
    echo "schema=1"
    echo "synced_at=$(date +%s)"
    echo "want_tier=$tier"
    echo "want_kernel=$kernel"
    echo "want_hair=$hair"
    echo "want_skinray=$skinray"
    echo "want_shadowcull=$shadowcull"
    echo "cache=${cache_action:-kept}"
    # What the PREVIOUS launch asked for, straight off the stamp. Without it
    # the page would compare this launch's intent against last launch's result
    # and cry wolf every time a toggle was just flipped.
    if [[ -n "$have" ]]; then
        for kv in $have; do echo "last_want_${kv%%=*}=${kv#*=}"; done
    fi
    if [[ -f "$LAST_RUN" ]]; then
        echo "last_layer=loaded"
        touch "$SEEN" 2>/dev/null
        # bracket contents only -- matching bare quoted words would also
        # capture the "overlays" key itself
        ovl="$(sed -n 's/.*"overlays": *\[\([^]]*\)\].*/\1/p' "$LAST_RUN" \
               | grep -o '[a-z]\+' | paste -sd+ -)"
        echo "last_overlays=${ovl:-none}"
        echo "last_resolve=$(jnum resolve)"
        echo "last_shadow=$(jnum shadow)"
        echo "last_raygen=$(jnum raygen)"
        echo "last_gi=$(jnum gi)"
        echo "last_failed=$(jnum failed)"
    elif [[ -f "$LOADED" ]]; then
        # The layer loaded but no process swapped anything -- a real fault
        # (empty swap dirs, ids that no longer match), not a reporting gap.
        echo "last_layer=loaded_noswap"
        touch "$SEEN" 2>/dev/null
    elif [[ -f "$SEEN" ]]; then
        # The layer writes its record from its constructor, so a launch that
        # loaded it leaves a file even if the game dies a second later. Once
        # we have seen one, a missing file is real evidence: not installed,
        # manifest gone, or CALLISTO_LAYER_DISABLE=1 in the launch options.
        echo "last_layer=absent"
    else
        # Never seen one yet -- a fresh install, or the previous launch predates
        # the status loop. Absence proves nothing; do not cry wolf.
        echo "last_layer=unknown"
    fi
} > "$STATUS" 2>/dev/null

# Keep the layer's record honest: this run's counts start empty, so a launch
# that crashes before creating any module cannot leave last launch's numbers
# standing as if they were fresh.
rm -f "$LAST_RUN" "$LOADED" 2>/dev/null
