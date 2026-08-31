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
# skinspec (Callisto Tier-3 skin gloss) defaults OFF since 2026-08-29:
# alpha_max is a roughness CEILING and every rung clamps the whole face to one
# constant alpha, erasing the authored roughness variation (handoff/33). Opt-in.
# Defaults must stay in step with init.lua's: when the two disagree the effect
# appears to switch itself off on any launch where CET has not yet written
# brdf_params.txt.
#
# There is no `skinray` key any more (removed 2026-08-30, handoff/43): the
# raygen-side skin BRDF is sampling-only and cannot change a pixel
# (00-ARCHITECTURE section 2), and keeping it cost a second half of the ptq
# matrix plus a SER trap. A stale key in brdf_params.txt is ignored.
tier=1 kernel=detail skin=on shadowcull=on shadowset=full-shadow
#
# There is no `skintrans`/`skinthick` key: the Tier-4 backlit transmission
# they selected was removed 2026-08-30 (handoff/39). A stale brdf_params.txt
# may still carry them; they are ignored, which is the intended behaviour --
# the read loop below whitelists keys, so an unknown one falls through.
ptreg=off ptclamp=on ptbounce=on ptrefl=on ptmsggx=on skinspec=off ser=off refract=off
if [[ -f "$PARAMS" ]]; then
    while IFS='=' read -r k v; do
        v="${v%$'\r'}"
        case "$k" in
            tier|kernel|skin|shadowcull|shadowset) printf -v "$k" '%s' "$v" ;;
            ptreg|ptclamp|ptbounce|ptrefl|ptmsggx|skinspec) printf -v "$k" '%s' "$v" ;;
            ser|refract) printf -v "$k" '%s' "$v" ;;
        esac
    done < "$PARAMS"
fi

mkdir -p "$INSTALL_DIR/swaps"

# kernel -- SSS diffusion kernel (RED4ext). Since 44-LOW-HANGING-FRUIT this
# names a PRESET (detail | balanced | callisto | vanilla), one of the four
# kernels dev/author_callisto_kernel.py ships in kernels/; the chosen one is
# copied over kernel.bin, which the plugin reads once per boot. `on` is the
# legacy alias for detail. vanilla is a re-authored copy of the engine's own
# kernel, NOT the engine data: `off` (disable.flag) is the true A/B control.
case "$kernel" in on|1|'') kernel=detail ;; esac
kernel_note=""
if [[ "$kernel" == "off" ]]; then
    echo 1 > "$KERNEL_FLAG"
else
    ksrc="$PLUGIN_DIR/kernels/kernel.$kernel.bin"
    if [[ ! -f "$ksrc" && -f "$PLUGIN_DIR/kernels/kernel.detail.bin" ]]; then
        echo "[CallistoSSS] kernel='$kernel' has no kernels/kernel.$kernel.bin; using detail" >&2
        kernel=detail; ksrc="$PLUGIN_DIR/kernels/kernel.detail.bin"
    fi
    if [[ -f "$ksrc" ]]; then
        cp -pf "$ksrc" "$PLUGIN_DIR/kernel.bin"
    else
        kernel_note=" (no kernels/ shipped -- serving the kernel.bin already present)"
        echo "[CallistoSSS] no kernels/ dir next to sync_settings.sh; kernel.bin left as is" >&2
    fi
    rm -f "$KERNEL_FLAG"
fi

# tier -- the MASTER switch for every shader swap. Off forces every overlay
# below off (and empties swaps/), so the layer passes through bit-exact
# vanilla: the A/B baseline. It does not touch the SSS kernel, which is engine
# data, not a shader swap. Before 2026-08-30 it only gated the raygen side,
# so "Callisto BRDF off" still served the skin and shadow overlays (handoff/43).
if [[ "$tier" == "off" ]]; then
    skin=off shadowcull=off
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
# A level name is now just a gloss rung. The composed "<gloss>+t<trans>[+k]"
# names went with the Tier-4 transmission (removed 2026-08-30, handoff/39);
# a stale skin.set/<gloss>+t.../ from an older build is simply never named
# here, and `--sets` rm -rf's skin.set/ on every run, so a rebuild clears it.
skin_set=fixed
want_skin="$skinspec"
case "$want_skin" in
    on)  want_skin=strong ;;
    ''|0) want_skin=off ;;
esac
if [[ -d "$INSTALL_DIR/skin.set" ]]; then
    if [[ ! -d "$INSTALL_DIR/skin.set/$want_skin" ]]; then
        echo "[CallistoSSS] skinspec='$skinspec' is not a built level; using off" >&2
        want_skin=off
    fi
    # Empty the overlay BEFORE testing the rung dir: if even skin.set/off/ is
    # missing, the previous launch's rung must not stay behind and get served
    # under the new name.
    mkdir -p "$INSTALL_DIR/swaps.skin"
    rm -f "$INSTALL_DIR/swaps.skin/"*.spv "$INSTALL_DIR/swaps.skin/MANIFEST.txt"
    if [[ -d "$INSTALL_DIR/skin.set/$want_skin" ]]; then
        cp -pf "$INSTALL_DIR/skin.set/$want_skin/"*.spv \
              "$INSTALL_DIR/swaps.skin/" 2>/dev/null && skin_set=$want_skin
        # probe-gi ships a MANIFEST.txt (provenance for the guard below; the
        # layer echoes line 1 into the journal). Other rungs ship none.
        [[ -f "$INSTALL_DIR/skin.set/$want_skin/MANIFEST.txt" ]] && \
            cp -pf "$INSTALL_DIR/skin.set/$want_skin/MANIFEST.txt" \
                   "$INSTALL_DIR/swaps.skin/" 2>/dev/null
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

# swaps/ -- the base dir. It used to carry the two skinray raygens; those are
# gone, so it is always emptied. Overlays are the only thing served now, which
# also means the ptq matrix no longer needs its skin/ half.
rm -f "$INSTALL_DIR/swaps/"*.spv

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
    rm -f "$INSTALL_DIR/ptq.disable"
    ptq_state="$combo"
else
    # An empty overlay dir still reads as "enabled" in the layer's log, which
    # would be a lie in the status page. Flag it off explicitly.
    echo 1 > "$INSTALL_DIR/ptq.disable"
    ptq_state=off
fi

# --- raygen-bearing skin rungs (probe-gi, handoff/48 §8 / 50) ---------------
# A skin rung that ships rgs_* files owns ids that ser (above skin) and ptq
# (below it) also serve. First-file-wins makes that a stack of traps, each of
# which this repo has already paid for once:
#   * its rgs_reference_main files MUST be built on the ser.set (which is
#     built on the served ptq combo), or serving them un-patches ptq+SER for
#     those ids ("an overlay reject must fall through, never to vanilla");
#   * swaps.ser MUST NOT be materialised while it serves, or ser wins the
#     race and the rung's raygen files are dead with no error anywhere;
#   * its vanilla-based rgs_restirgi_* files collide with shadowset=full
#     (which patches those 8 ids); only full-shadow is compatible;
#   * a PT-switch change after the rung was built re-creates the stale-ser
#     trap one overlay up, so the provenance in the rung's MANIFEST.txt is
#     verified here EVERY launch, exactly like swaps.ser's own manifest.
# On any mismatch the rung is refused loudly (skinspec reads off:gi-*) --
# a probe served over the wrong base is worse than no probe.
skin_owns_raygens=0
if [[ "$skin" != "off" ]] && compgen -G "$INSTALL_DIR/swaps.skin/"'*.rgs_*.spv' >/dev/null; then
    skin_owns_raygens=1
fi
gi_refuse() {
    echo "[CallistoSSS] skinspec=$skin_set REFUSED: $1" >&2
    rm -f "$INSTALL_DIR/swaps.skin/"*.spv "$INSTALL_DIR/swaps.skin/MANIFEST.txt"
    skin_set="off:$2"
    skin_owns_raygens=0
}
if (( skin_owns_raygens )); then
    GIM="$INSTALL_DIR/swaps.skin/MANIFEST.txt"
    gi_src="$(sed -n 's/.*src_ser="\([^"]*\)".*/\1/p' "$GIM" 2>/dev/null | head -1)"
    gi_ser_sha="$(sed -n 's/.*ser_sha=\([0-9a-f]*\).*/\1/p' "$GIM" 2>/dev/null | head -1)"
    gi_ptq_sha="$(sed -n 's/.*ptq_sha=\([0-9a-f]*\).*/\1/p' "$GIM" 2>/dev/null | head -1)"
    gi_ser_now="$(cat "$INSTALL_DIR/$gi_src"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
    gi_ptq_now="$(cat "$INSTALL_DIR/swaps.ptq/"*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
    if [[ -z "$gi_ser_sha" || -z "$gi_ptq_sha" || -z "$gi_src" ]]; then
        gi_refuse "raygen-bearing rung has no readable provenance MANIFEST.txt" "gi-no-manifest"
    elif [[ "$gi_ser_now" != "$gi_ser_sha" ]]; then
        gi_refuse "built on $gi_src which has since changed ($gi_ser_sha -> ${gi_ser_now:-empty}); rebuild: ./dev/build_probe_gi.sh --install" "gi-stale-ser"
    elif [[ "$gi_ptq_now" != "$gi_ptq_sha" ]]; then
        gi_refuse "baked against ptq $gi_ptq_sha but this launch serves ${gi_ptq_now:-empty} (ptq=$ptq_state); restore the PT switches or rebuild the probe" "gi-stale-ptq"
    elif compgen -G "$INSTALL_DIR/swaps.skin/"'*.rgs_restirgi_*.spv' >/dev/null && [[ "$shadow_set" != "full-shadow" ]]; then
        gi_refuse "ships vanilla-based rgs_restirgi_* but shadowset=$shadow_set patches those ids; set shadowset=full-shadow" "gi-shadowset"
    elif [[ "$ser" == "off" ]]; then
        gi_refuse "carries SER splices (built on $gi_src) but ser=off was requested; set ser=class" "gi-needs-ser"
    fi
fi

# ser -- the Shader Execution Reordering overlay (handoff/41), off by default.
# `ser` names a HINT RUNG the way `skinspec` names a gloss build: off, class,
# byte, hit, class+hit. dev/patch_ser.sh --install parks all four in ser.set/,
# so switching rungs is a copy and never a patcher re-run -- same contract as
# the ptq matrix and skin.set.
#
# swaps.ser/ is built ON TOP of whatever swaps.ptq/ serves, and `ser` is FIRST
# in the overlay list, so its twelve rgs_reference_main files outrank every ptq
# matrix cell. That ordering is what makes it work; it is also the trap. A
# swaps.ser/ built against a DIFFERENT combo keeps serving that combo after a
# PT toggle -- and the toggle LOOKS applied, because the cache stamp below sees
# swaps.ptq/ change and clears the pipeline caches. You would pay a full shader
# recompile for a setting that never reached the driver. The matrix exists
# precisely so PT settings are a copy and never a rebuild; an unchecked ser
# overlay silently takes that back.
#
# So verify rather than document: patch_ser.sh records the content sha of its
# source in MANIFEST.txt, and this recomputes it over what was just
# materialised. On any mismatch the overlay is turned OFF. Failing that way
# round is deliberate -- losing SER costs a scheduling hint that CANNOT change
# a pixel, while a stale SER silently overrides the PT quality selection, which
# can. Asymmetric failure modes get the safe default, not a comment telling the
# next person to be careful.
#
# This check can only ever force OFF. It must never turn SER on by itself:
# --install ships it disabled on purpose so the first launch is the A/B control.
SER="$INSTALL_DIR/swaps.ser"
ser_state=off
if [[ "$ser" != "off" && "$tier" != "off" && "$skin_owns_raygens" == "1" ]]; then
    # The skin rung owns the twelve rgs_reference_main ids and carries the
    # SER splices itself (provenance verified above). Materialising swaps.ser
    # here would put the SAME ids in an overlay that outranks skin, and the
    # rung's files -- the whole point of the launch -- would be dead with no
    # error anywhere. So the hints ride the skin overlay and swaps.ser stays
    # empty and disabled.
    mkdir -p "$SER"; rm -f "$SER"/*.spv "$SER/MANIFEST.txt"
    ser_state="$ser:in-skin"
elif [[ "$ser" != "off" && "$tier" != "off" ]]; then
    # Materialise the requested rung, exactly as ptq and skin.set do. The
    # overlay is emptied whether or not the rung exists: an older swaps.ser/
    # left in place would otherwise pass every check below under its own
    # manifest and be served in place of the rung that was asked for.
    mkdir -p "$SER"; rm -f "$SER"/*.spv "$SER/MANIFEST.txt"
    if [[ -d "$INSTALL_DIR/ser.set/$ser" ]]; then
        cp -pf "$INSTALL_DIR/ser.set/$ser"/*.spv \
               "$INSTALL_DIR/ser.set/$ser/MANIFEST.txt" "$SER/" 2>/dev/null
    fi
    ser_src="$(sed  -n 's/.*src="\([^"]*\)".*/\1/p'       "$SER/MANIFEST.txt" 2>/dev/null | head -1)"
    ser_want="$(sed -n 's/.*src_sha=\([0-9a-f]*\).*/\1/p' "$SER/MANIFEST.txt" 2>/dev/null | head -1)"
    ser_var="$(sed  -n 's/.*variant=\([a-z+]*\).*/\1/p'    "$SER/MANIFEST.txt" 2>/dev/null | head -1)"
    # Same glob and same order as dev/patch_ser.sh:389-403, so the shas compare.
    ser_have="$(cat "$PTQ"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
    if ! compgen -G "$SER/*.spv" >/dev/null; then
        ser_state="off:rung-missing"
        echo "[CallistoSSS] ser=$ser requested but no such rung -- run ./dev/patch_ser.sh --install."
    elif [[ -z "$ser_want" ]]; then
        ser_state="off:no-manifest"
        echo "[CallistoSSS] ser DISABLED: swaps.ser/ has no readable MANIFEST.txt, so its source cannot be verified."
    elif [[ "$ser_src" == VANILLA* ]]; then
        # --from-vanilla is only safe with every other raygen patch off.
        # patch_ser.sh already shouts about this at build.
        if [[ "$ptq_state" == off ]]; then
            ser_state="${ser_var:-$ser}:vanilla"
        else
            ser_state="off:vanilla-vs-patched"
            echo "[CallistoSSS] ser DISABLED: built --from-vanilla, but ptq=$ptq_state would be un-patched by it."
        fi
    elif [[ "$ser_want" != "$ser_have" ]]; then
        ser_state="off:stale"
        echo "[CallistoSSS] ser DISABLED (stale): built against ptq $ser_want, ptq is now ${ser_have:-empty} (ptq=$ptq_state)."
        echo "[CallistoSSS]   rebuild it with ./dev/patch_ser.sh --install -- it reads the installed swaps.ptq/ as served."
    else
        ser_state="${ser_var:-$ser}"
    fi
fi
if [[ "$ser_state" == off* || "$ser_state" == *:in-skin ]]; then
    echo 1 > "$INSTALL_DIR/ser.disable"     # in-skin: the DIR is empty; the
else rm -f "$INSTALL_DIR/ser.disable"; fi   # hints serve from swaps.skin

# ptrefl -- the same cullMask widening on the three reflection raygens. Nothing
# else patches those modules, so it is an ordinary independent overlay.
if [[ "$ptrefl" == "off" || "$tier" == "off" ]]; then
    echo 1 > "$INSTALL_DIR/ptrefl.disable"
else
    rm -f "$INSTALL_DIR/ptrefl.disable"
fi

# refract -- Phase 0.5 glass refraction (handoff/20 par5b, 51 par4, 76). The
# transparent-reflection raygen id is OWNED by the ptrefl overlay (first-file-
# wins), so this is not its own overlay: the chosen level is materialized INTO
# swaps.ptrefl/, and off restores the plain ptrefl file. eta15/eta20 repoint
# the traced mirror direction to the refracted one (n=1.5 / n=2.0) and push
# the ray origin through the surface; ladder parked in refract.set/ by
# ./dev/build_refract.sh --install. Nothing is patched at launch -- a copy,
# like skin.set and shadowcull.set.
refract_state="$refract"
RSET="$INSTALL_DIR/refract.set"
RMOD="ee6d252e090adc74.rgs_reflection_transparent_main.spv"
if [[ ! -d "$RSET/off" ]]; then
    # pre-refract install: nothing parked, nothing to restore -- leave the
    # ptrefl overlay exactly as installed and only complain if asked for more.
    if [[ "$refract" != "off" ]]; then
        refract_state="off:rung-missing"
        echo "[CallistoSSS] refract=$refract requested but no refract.set/ -- run ./dev/build_refract.sh --install."
    fi
elif [[ ! -d "$INSTALL_DIR/swaps.ptrefl" ]]; then
    refract_state="off:no-ptrefl-dir"
else
    lvl="$refract"
    if [[ "$lvl" != "off" && ( "$ptrefl" == "off" || "$tier" == "off" ) ]]; then
        # the rung rides the ptrefl overlay; with ptrefl.disable set the file
        # would sit there unserved and LOOK selected. Refuse loudly instead.
        refract_state="off:needs-ptrefl"
        echo "[CallistoSSS] refract DISABLED: rides the ptrefl overlay, and ptrefl/tier is off."
        lvl=off
    elif [[ "$lvl" != "off" && ! -d "$RSET/$lvl" ]]; then
        refract_state="off:no-such-level"
        echo "[CallistoSSS] refract=$refract has no refract.set/$refract -- serving off."
        lvl=off
    fi
    # Materialize even for off, so a previous launch's eta file can never
    # linger behind a changed setting (the stale-rung rule, handoff/43).
    cp -pf "$RSET/$lvl/$RMOD" "$INSTALL_DIR/swaps.ptrefl/$RMOD"
    # first MANIFEST line is echoed into the journal by the layer, so the
    # serve identity of the ptrefl overlay names the refract level.
    cp -pf "$RSET/$lvl/MANIFEST.txt" "$INSTALL_DIR/swaps.ptrefl/MANIFEST.txt" 2>/dev/null || true
fi

echo "[CallistoSSS] synced: tier=$tier kernel=$kernel$kernel_note skin=$skin/skinspec=$skin_set shadowcull=$shadowcull/$shadow_set"
echo "[CallistoSSS] path tracing: ptq=$ptq_state (reg=$ptreg clamp=$ptclamp bounce=$ptbounce msggx=$ptmsggx) ptrefl=$ptrefl refract=$refract_state ser=$ser_state"

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
              "$INSTALL_DIR"/swaps.ser/*.spv \
              "$INSTALL_DIR"/swaps.ptrefl/*.spv \
              "$INSTALL_DIR"/libVkLayer_callisto_spvswap.so 2>/dev/null \
           | sort | sha256sum | cut -c1-16)"
want="tier=$tier kernel=$kernel skin=$skin skinspec=$skin_set shadowcull=$shadowcull shadowset=$shadow_set ptq=$ptq_state ser=$ser_state ptrefl=$ptrefl refract=$refract_state payload=$payload"
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
ptrefl_sha="$(cat "$INSTALL_DIR/swaps.ptrefl/"*.spv 2>/dev/null | sha256sum | cut -c1-16)"
skin_sha="$(cat "$INSTALL_DIR/swaps.skin/"*.spv 2>/dev/null | sha256sum | cut -c1-16)"
ser_sha="$(cat "$INSTALL_DIR/swaps.ser/"*.spv 2>/dev/null | sha256sum | cut -c1-16)"
printf '%s shadowset=%s sc_sha=%s ptq=%s ser=%s ser_sha=%s ptrefl=%s refract=%s ptrefl_sha=%s skin=%s skinspec=%s skin_sha=%s tier=%s cache=%s payload=%s\n' \
    "$(date -Is)" "$shadow_set" "${sc_sha:-none}" "$ptq_state" \
    "$ser_state" "$(case "$ser_state" in off*) echo none;; *:in-skin) echo in-skin;; *) echo "${ser_sha:-none}";; esac)" "$ptrefl" "$refract_state" "${ptrefl_sha:-none}" \
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
    echo "want_shadowcull=$shadowcull"
    echo "want_shadowset_req=$shadowset"
    echo "want_shadowset=$shadow_set"
    echo "want_skinspec_req=$skinspec"
    echo "want_skinspec=$skin_set"
    echo "want_ptreg=$ptreg"
    echo "want_ptclamp=$ptclamp"
    echo "want_ptbounce=$ptbounce"
    echo "want_ptrefl=$ptrefl"
    echo "want_refract=$refract_state"
    echo "req_refract=$refract"
    echo "want_ptq=$ptq_state"
    echo "want_ser=$ser_state"
    echo "req_ser=$ser"
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
