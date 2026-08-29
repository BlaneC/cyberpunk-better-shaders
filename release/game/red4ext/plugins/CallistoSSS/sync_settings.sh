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

# ptreg defaults OFF: unlike the other four it is a deliberate look trade
# (indirect gloss goes softer in exchange for less noise), so it is opt-in.
# ptmsggx defaults ON since it was confirmed on screen 2026-08-28 (handoff/28).
# skinspec (Callisto Tier-3 skin gloss) defaults to 'strong' on explicit
# request (2026-08-29: "make it very obviously oily to start"). This is NOT a
# confirmed-on-screen default -- the ledger rule (handoff/19, /28) still
# applies and it has never been A/B'd -- it is an author's choice that the
# feature be visible when enabled rather than invisible. Drop to off/subtle
# here if that turns out wrong. Must stay in step with init.lua's own default:
# when the two disagree the effect appears to switch itself off on any launch
# where CET has not yet written brdf_params.txt.
tier=1 kernel=on skin=on skinray=on shadowcull=on shadowset=full-shadow
# skintrans (Callisto Tier-4 backlit skin transmission) defaults OFF: it has
# never been seen on screen, and unlike skinspec it changes light where the
# engine currently puts none, so it is opt-in until an A/B says otherwise.
ptreg=off ptclamp=on ptbounce=on ptrefl=on ptmsggx=on skinspec=strong
skintrans=off
if [[ -f "$PARAMS" ]]; then
    while IFS='=' read -r k v; do
        v="${v%$'\r'}"
        case "$k" in
            tier|kernel|skin|skinray|shadowcull|shadowset) printf -v "$k" '%s' "$v" ;;
            ptreg|ptclamp|ptbounce|ptrefl|ptmsggx|skinspec) printf -v "$k" '%s' "$v" ;;
            skintrans) printf -v "$k" '%s' "$v" ;;
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

# skin -- the compute-resolve skin overlay (tier-1 c1, plus the Tier-3 gloss
# when skinspec selects it). Replaced the `hair` overlay on 2026-08-28 when the
# hair BRDF was removed: c1 used to ride swaps.skin/, so hair=off silently
# disabled a shipping, confirmed feature as well as the unconfirmed one.
if [[ "$skin" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/skin.disable"
else
    rm -f "$INSTALL_DIR/skin.disable"
fi

# skinspec -- WHICH build of the skin overlay is served, i.e. how oily. The
# Tier-3 gloss (handoff/27 Phase 2) is spliced into the same compute-resolve
# modules as the tier-1 c1, so it cannot be its own overlay -- the layer serves
# the first file it finds for an id -- and its knobs are OpConstants baked in
# at build time, so no runtime slider can move them. Strength is therefore a
# LADDER of pre-built sets, exactly like shadowset below.
#
# dev/patch_compute_skin.sh --sets parks them in skin.set/<level>/:
#
#   off       tier-1 c1 only -- the gloss-free baseline, and the A/B control
#   subtle    roughness capped at 0.40 -- a damp sheen, barely past vanilla
#   medium    0.30 -- clearly wet, still plausible skin
#   strong    0.21 -- unmistakably oily
#   extreme   0.14 -- diagnostic. Answers "is the splice working at all",
#             not "does this look right"; expect it to read as wet plastic.
#
# Every set carries an IDENTICAL c1, so moving this changes the gloss and
# nothing else. `on` is accepted as a legacy alias for `strong` so an existing
# brdf_params.txt keeps working.
#
# Only acts once --sets has been run; an install with a single fixed
# swaps.skin/ is left untouched and reports skinspec=fixed rather than
# pretending the request was honoured. An unknown or unbuilt level falls back
# to off rather than silently serving a different strength than the one named.
#
# skintrans -- the Tier-4 backlit transmission ladder (handoff/29). It splices
# the SAME 84 compute modules as the gloss, so for the same first-file-wins
# reason it cannot be a second overlay either: the combinations are pre-built
# by `dev/patch_compute_skin.sh --sets --trans` and parked under the composed
# name "<skinspec>+t<skintrans>". off/subtle/medium/strong/extreme, where
# extreme is the diagnostic rung (fires on all lit skin, ignoring geometry --
# it answers "does the splice reach the screen", not "does it look right").
#
# A combination that was never built falls back to the gloss-only set of the
# same strength, NOT to off: dropping silently to off would change the gloss
# as well, and the next A/B would be attributing a difference to transmission
# that was really the gloss moving underneath it.
skin_set=fixed
want_skin="$skinspec"
case "$want_skin" in
    on)  want_skin=strong ;;
    ''|0) want_skin=off ;;
esac
want_gloss="$want_skin"
case "$skintrans" in
    off|''|0) ;;
    *) want_skin="$want_skin+t$skintrans" ;;
esac
if [[ -d "$INSTALL_DIR/skin.set" ]]; then
    if [[ ! -d "$INSTALL_DIR/skin.set/$want_skin" \
          && -d "$INSTALL_DIR/skin.set/$want_gloss" \
          && "$want_skin" != "$want_gloss" ]]; then
        echo "[CallistoSSS] skintrans='$skintrans' has no built set for" >&2
        echo "[CallistoSSS]   skinspec=$want_gloss; using $want_gloss (no" >&2
        echo "[CallistoSSS]   transmission). Run: ./dev/patch_compute_skin.sh --sets --trans" >&2
        want_skin="$want_gloss"
    fi
    if [[ ! -d "$INSTALL_DIR/skin.set/$want_skin" ]]; then
        echo "[CallistoSSS] skinspec='$skinspec' is not a built level; using off" >&2
        want_skin=off
    fi
    if [[ -d "$INSTALL_DIR/skin.set/$want_skin" ]]; then
        mkdir -p "$INSTALL_DIR/swaps.skin"
        rm -f "$INSTALL_DIR/swaps.skin/"*.spv
        cp -pf "$INSTALL_DIR/skin.set/$want_skin/"*.spv \
              "$INSTALL_DIR/swaps.skin/" 2>/dev/null && skin_set=$want_skin
    fi
elif [[ "$want_skin" != "off" ]]; then
    echo "[CallistoSSS] skinspec=$want_skin but no skin.set/ is parked --" >&2
    echo "[CallistoSSS]   run: ./dev/patch_compute_skin.sh --sets" >&2
fi

# shadowcull -- the hair shadow leak fix overlay.
if [[ "$shadowcull" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/shadowcull.disable"
else
    rm -f "$INSTALL_DIR/shadowcull.disable"
fi

# shadowset -- WHICH build of that overlay is served. Names come from
# dev/build_shadow_sets.sh; the CET selector offers the same list.
#
#   full-shadow  THE SHIPPING BUILD, and the default. Flags 28 -> 12 in place
#                (back-face culling off) on the 10 rgs_shadow modules only.
#                Closes the hairline seam; leaves a reduced amount of flicker
#                on flat props at LOD transitions.
#   full         the same edit on all 18 modules, i.e. full-shadow plus the 8
#                rgs_restirgi_* GI modules. Kept because it is the original
#                proven build, but the GI half adds flicker and contributes
#                nothing visible to the seam -- prefer full-shadow.
#
# Everything else was a diagnostic and has been removed; the recipes stay in
# dev/build_shadow_sets.sh with their results. The short version (`26` §7a-d):
# the two-ray splice never executed -- `sctrl`, a control built so that a
# working splice MUST look like full-shadow, came back vanilla -- so no cull
# mask experiment was ever interpretable, and ray flags cannot separate hair
# from flat props because they apply to the whole ray.
#
# Only acts when dev/install_shadow_sets.sh has parked the sets; an older
# install with a single fixed swaps.shadowcull/ is left untouched. An unknown
# or retired name falls back to full-shadow rather than serving nothing.
shadow_set=fixed
want_set="$shadowset"
case "$want_set" in off|'') want_set=full-shadow ;; esac
if [[ ! -d "$INSTALL_DIR/shadowcull.set/$want_set" && -d "$INSTALL_DIR/shadowcull.set/full-shadow" ]]; then
    echo "[CallistoSSS] shadowset='$want_set' is retired or not installed; using full-shadow" >&2
    want_set=full-shadow
fi
if [[ -d "$INSTALL_DIR/shadowcull.set/$want_set" ]]; then
    mkdir -p "$INSTALL_DIR/swaps.shadowcull"
    rm -f "$INSTALL_DIR/swaps.shadowcull/"*.spv
    cp -pf "$INSTALL_DIR/shadowcull.set/$want_set/"*.spv \
          "$INSTALL_DIR/swaps.shadowcull/" 2>/dev/null && shadow_set=$want_set
fi

# skinray -- the tier-1 raygen sampling (eval-invisible skin BRDF). The
# pristine copies live in swaps.prehunt/; off removes them from swaps/.
if [[ "$skinray" == "off" ]]; then
    rm -f "$INSTALL_DIR/swaps/"*.rgs_reference_main.spv
elif [[ "$tier" != "off" ]]; then
    cp -pf "$INSTALL_DIR/swaps.prehunt/"*.rgs_reference_main.spv \
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
        [[ -f "$INSTALL_DIR/swaps/$base" ]] || cp -pf "$f" "$INSTALL_DIR/swaps/"
    done
fi

# ptreg / ptclamp / ptbounce / ptmsggx -- the path-tracing splices (handoff/23
# tier 1, plus T2.1 energy compensation). All four splice the same twelve
# rgs_reference_main permutations, and the layer serves the FIRST file it finds
# for an id, so they cannot be four overlays. dev/build_ptq.sh pre-builds the
# fifteen non-empty combinations; this picks one and materializes it into the
# single swaps.ptq/ overlay.
#
# The combo letters are in r,c,b,m order to match the built directory names.
combo=""
[[ "$ptreg"    != "off" ]] && combo+="r"
[[ "$ptclamp"  != "off" ]] && combo+="c"
[[ "$ptbounce" != "off" ]] && combo+="b"
[[ "$ptmsggx"  != "off" ]] && combo+="m"

PTQ="$INSTALL_DIR/swaps.ptq"
mkdir -p "$PTQ"
rm -f "$PTQ/"*.spv
if [[ "$tier" != "off" && -n "$combo" && -d "$INSTALL_DIR/ptq/$combo/base" ]]; then
    cp -pf "$INSTALL_DIR/ptq/$combo/base/"*.spv "$PTQ/" 2>/dev/null
    # skinray ships its own patched copies of two of the twelve permutations in
    # the base swaps/ dir. Every overlay outranks that dir, so a vanilla-based
    # ptq module would silently un-patch them; the matrix carries skin-based
    # builds of exactly those two for this case.
    if [[ "$skinray" != "off" ]]; then
        cp -pf "$INSTALL_DIR/ptq/$combo/skin/"*.spv "$PTQ/" 2>/dev/null
    fi
    rm -f "$INSTALL_DIR/ptq.disable"
    ptq_state="$combo$([[ "$skinray" != "off" ]] && echo "+skin")"
else
    # An empty overlay dir still reads as "enabled" in the layer's log, which
    # would be a lie in the status page. Flag it off explicitly.
    echo 1 > "$INSTALL_DIR/ptq.disable"
    ptq_state=off
fi

# ptrefl -- the same cullMask widening on the three reflection raygens. Nothing
# else patches those modules, so it is an ordinary independent overlay.
if [[ "$ptrefl" == "off" || "$tier" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/ptrefl.disable"
else
    rm -f "$INSTALL_DIR/ptrefl.disable"
fi

echo "[CallistoSSS] synced: tier=$tier kernel=$kernel skin=$skin/skinspec=$skin_set (skintrans=$skintrans) skinray=$skinray shadowcull=$shadowcull/$shadow_set"
echo "[CallistoSSS] path tracing: ptq=$ptq_state (reg=$ptreg clamp=$ptclamp bounce=$ptbounce msggx=$ptmsggx) ptrefl=$ptrefl"

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
# -p on every materializing copy above is what makes this stable: mtime comes
# from the parked source, so an unchanged selection hashes the same next launch
# and the caches survive. Without it every launch recompiled every shader.
payload="$(stat -c '%n %s %Y' \
              "$INSTALL_DIR"/swaps/*.spv \
              "$INSTALL_DIR"/swaps.skin/*.spv \
              "$INSTALL_DIR"/swaps.shadowcull/*.spv \
              "$INSTALL_DIR"/swaps.ptq/*.spv \
              "$INSTALL_DIR"/swaps.ptrefl/*.spv \
              "$INSTALL_DIR"/libVkLayer_callisto_spvswap.so 2>/dev/null \
           | sort | sha256sum | cut -c1-16)"
want="tier=$tier kernel=$kernel skin=$skin skinspec=$skin_set skinray=$skinray shadowcull=$shadowcull shadowset=$shadow_set ptq=$ptq_state ptrefl=$ptrefl payload=$payload"
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

# --- launch journal ----------------------------------------------------------
# The layer log records each swap's FILE NAME and SIZE, which cannot tell two
# variants apart when they differ only in a constant's value: in binary SPIR-V
# an OpConstant is the same size whatever it holds, so m1/m2/m4/m6/m16/m32 are
# byte-size-identical and so are m118/m119. Attributing an observation to a
# variant from the log alone is therefore impossible for 6 of the 13 sets, and
# a result was once credited to a set that had never been launched at all
# (`26` §7). This journal is the fix: one append-only line per launch, keyed on
# the CONTENT hash of what was actually served.
sc_sha="$(cat "$INSTALL_DIR/swaps.shadowcull/"*.spv 2>/dev/null | sha256sum | cut -c1-16)"
skin_sha="$(cat "$INSTALL_DIR/swaps.skin/"*.spv 2>/dev/null | sha256sum | cut -c1-16)"
printf '%s shadowset=%s sc_sha=%s ptq=%s ptrefl=%s skin=%s skinspec=%s skin_sha=%s tier=%s cache=%s payload=%s\n' \
    "$(date -Is)" "$shadow_set" "${sc_sha:-none}" "$ptq_state" "$ptrefl" \
    "$skin" "$skin_set" "${skin_sha:-none}" \
    "$tier" "${cache_action:-kept}" "$payload" \
    >> "$HOME/callisto_launches.log" 2>/dev/null || true

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
    echo "want_skin=$skin"
    echo "want_skinray=$skinray"
    echo "want_shadowcull=$shadowcull"
    echo "want_shadowset_req=$shadowset"
    echo "want_shadowset=$shadow_set"
    echo "want_skinspec_req=$skinspec"
    echo "want_skintrans_req=$skintrans"
    echo "want_skinspec=$skin_set"
    echo "want_ptreg=$ptreg"
    echo "want_ptclamp=$ptclamp"
    echo "want_ptbounce=$ptbounce"
    echo "want_ptrefl=$ptrefl"
    echo "want_ptq=$ptq_state"
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
        echo "last_refl=$(jnum refl)"
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
