#!/usr/bin/env bash
# Callisto SKIN BRDF on the GLCompute resolve shaders -- the confirmed-visible
# surface.
#
#   ./dev/patch_compute_skin.sh              # c1 only (the shipping build)
#   ./dev/patch_compute_skin.sh --sets       # the gloss STRENGTH LADDER, parked
#   ./dev/patch_compute_skin.sh --hunt       # 10-class palette (diagnostic)
#
# --sets is the one to use for the Tier-3 skin gloss (handoff/27 Phase 2). The
# gloss is spliced into the same modules as the tier-1 c1, so it cannot be a
# second overlay -- the layer serves the first file it finds for an id
# (GOTCHAS: first-file-wins). And its knobs are OpConstants baked in at build
# time, so no runtime slider can move them: a CET slider claiming to would be
# the inert-slider trap of handoff/26 section 5 all over again.
#
# So strength is a LADDER of pre-built sets. This builds the skin overlay once
# per level plus a gloss-free baseline, parks them in
# $INSTALL_DIR/skin.set/<level>/, and sync_settings.sh materializes whichever
# one `skinspec` names into swaps.skin/ at launch -- exactly how `shadowset`
# picks a shadowcull build. The CET selector offers the same list.
#
# Every set carries an IDENTICAL c1 from the same source in the same run, so
# moving the selector changes the gloss and nothing else.
#
# For a value not on the ladder, --set overrides any level:
#   ./dev/patch_compute_skin.sh --sets --set alpha_max=0.06
#
# Replaces dev/patch_compute_hair.sh (deleted 2026-08-28 with the hair BRDF).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps.skin.build}"
WORK="$MOD_DIR/dev/disasm/compute"

# The gloss strength ladder. `alpha_max` is the dominant lever by far: it is a
# GGX-alpha ceiling, and authored skin roughness in this game sits around
# 0.40-0.60, so a cap above ~0.16 (roughness 0.40) barely bites at all. The
# Fresnel half only broadens the falloff -- its saturate(2-r) amplitude term is
# clamped to 1 across this whole direction, so spec_gain is what moves it, and
# F' is clamped to 1 regardless (Fresnel cannot exceed unity).
#
#   level    roughness cap   Fresnel exponent
#   subtle       0.40              4.0     barely past vanilla; a damp sheen
#   medium       0.30              3.0     clearly wet, still plausible skin
#   strong       0.21              2.0     unmistakably oily -- the default
#   extreme      0.14              1.0     diagnostic: answers "is it working"
#                                          rather than "does it look right"
#
# Adding a level is one line here plus one in init.lua's SKIN_LEVELS.
LEVELS=(
    "subtle:n_s=0.60,spec_gain=1.0,alpha_max=0.1600"
    "medium:n_s=0.70,spec_gain=1.2,alpha_max=0.0900"
    "strong:n_s=0.80,spec_gain=1.5,alpha_max=0.0450"
    "extreme:n_s=0.90,spec_gain=2.0,alpha_max=0.0200"
)

TIER=skin; EXTRA=(); SETS=0; SKINSPEC=0
while (( $# )); do
    case "$1" in
        --hunt) TIER=hunt ;;
        --tint) TIER=tint ;;
        # forwarded verbatim, so a tuning sweep is one command:
        #   ./dev/patch_compute_skin.sh --sets --set alpha_max=0.12
        --set) EXTRA+=(--set "${2:?--set needs K=V}"); shift ;;
        --with-skinspec) SKINSPEC=1 ;;
        --sets) SETS=1 ;;
        -*) echo "unknown flag: $1" >&2; exit 2 ;;
        *)  DUMP_DIR="$1" ;;
    esac
    shift
done
if (( SETS )) && [[ "$TIER" != skin ]]; then
    echo "--sets only applies to the skin tier" >&2; exit 2
fi
if (( SETS && SKINSPEC )); then
    echo "--sets already builds the with-skinspec variant; drop --with-skinspec" >&2
    exit 2
fi

mapfile -t targets < <(python3 - "$DUMP_DIR" <<'PY'
import glob, struct, sys
pi = struct.pack('<f', 0.318309873)
k = struct.pack('<f', 0.107508637)
for f in sorted(glob.glob(sys.argv[1] + '/*.dxil.spv')):
    d = open(f, 'rb').read()
    if pi in d and k in d:
        print(f)
PY
)
echo "=== tier $TIER | ${#targets[@]} anchored compute libs ==="

mkdir -p "$WORK"
RT_DONE=0

# Build the whole anchored set into $1 with the base args plus any extras.
# Sets BUILT to the number of modules patched. A function so --sets can run it
# once per rung against the same disassembly and the same base args, which is
# what makes the ladder a clean single-variable comparison: between any two
# levels the ONLY thing that moved is the three gloss knobs.
build_into() {
    local dest="$1"; shift
    local args=(--tier "$TIER")
    if (( ${#EXTRA[@]} )); then args+=("${EXTRA[@]}"); fi
    args+=("$@")

    mkdir -p "$dest"
    rm -f "$dest"/*.spv "$dest"/*.spvasm 2>/dev/null || true

    # The roundtrip check re-assembles and validates the UNPATCHED module to
    # prove the tooling is sane. That is worth doing once, not once per rung:
    # the ladder feeds all its builds the same disassembly, so repeating it
    # would multiply the build time for no extra signal.
    if (( RT_DONE )); then args+=(--no-roundtrip-check); fi
    local pass=() fail=() name asm f n
    for f in "${targets[@]}"; do
        name="$(basename "${f%.spv}")"
        asm="$WORK/$name.spvasm"
        [[ -f "$asm" ]] || spirv-dis "$f" -o "$asm" 2>/dev/null || { fail+=("$name"); continue; }
        if python3 "$MOD_DIR/dev/patch_compute_skin.py" "$asm" "${args[@]}" \
                --outdir "$dest" > "$dest/.skin.$name.json" 2>"$dest/.skin.$name.err"; then
            pass+=("$name")
        else
            fail+=("$name")
        fi
    done
    echo "patched ${#pass[@]}, failed ${#fail[@]}${1:+  [$*]}"
    if (( ${#fail[@]} > 0 )); then
        for n in "${fail[@]}"; do
            echo "  $n :: $(sed 's/.*error: //' "$dest/.skin.$n.err" 2>/dev/null | head -1 | cut -c1-70)"
        done | sort | uniq -c | sort -rn | head -8
    fi
    BUILT=${#pass[@]}
    RT_DONE=1
    (( BUILT > 0 )) || { echo "nothing patched" >&2; exit 1; }
}

if (( SETS )); then
    echo "--- set 'off' (tier-1 c1 only, the gloss-free baseline) ---"
    build_into "$MOD_DIR/swaps.skin.off"
    off_n=$BUILT
    BUILT_SETS=(off)
    for spec in "${LEVELS[@]}"; do
        lvl="${spec%%:*}"; kv="${spec#*:}"
        setargs=(--with-skinspec)
        IFS=',' read -ra kvs <<< "$kv"
        for one in "${kvs[@]}"; do setargs+=(--set "$one"); done
        echo "--- set '$lvl' (c1 + gloss: $kv) ---"
        build_into "$MOD_DIR/swaps.skin.$lvl" "${setargs[@]}"
        BUILT_SETS+=("$lvl")
    done

    # Equal coverage across every set is what makes the ladder attributable: if
    # one level patched a module another did not, moving the selector would also
    # change which modules are vanilla, and the observation would mean nothing.
    ref="$(cd "$MOD_DIR/swaps.skin.off" && ls *.spv 2>/dev/null | sort)"
    for lvl in "${BUILT_SETS[@]}"; do
        cur="$(cd "$MOD_DIR/swaps.skin.$lvl" && ls *.spv 2>/dev/null | sort)"
        if [[ "$cur" != "$ref" ]]; then
            echo "set '$lvl' coverage differs from 'off' -- not a clean A/B" >&2
            diff <(echo "$ref") <(echo "$cur") | head -10 >&2
            exit 1
        fi
    done

    # Every level must differ from the baseline AND from the level below it, or
    # two rungs are the same build under two names and the selector would
    # silently compare nothing. This is what catches a knob that turned out not
    # to reach the shader at all.
    prev=off
    for lvl in "${BUILT_SETS[@]}"; do
        [[ "$lvl" == off ]] && continue
        d_base=0; d_prev=0
        for f in "$MOD_DIR/swaps.skin.off"/*.spv; do
            b="$(basename "$f")"
            cmp -s "$f" "$MOD_DIR/swaps.skin.$lvl/$b" || d_base=$((d_base+1))
            cmp -s "$MOD_DIR/swaps.skin.$prev/$b" "$MOD_DIR/swaps.skin.$lvl/$b" || d_prev=$((d_prev+1))
        done
        printf '  %-8s %3d module(s) differ from off, %3d from %s\n' \
               "$lvl" "$d_base" "$d_prev" "$prev"
        (( d_base > 0 )) || { echo "'$lvl' is byte-identical to 'off'" >&2; exit 1; }
        (( d_prev > 0 )) || { echo "'$lvl' is byte-identical to '$prev'" >&2; exit 1; }
        prev="$lvl"
    done
    SWAPS="$MOD_DIR/swaps.skin.off"      # what lands in swaps.skin/ as the default
else
    if (( SKINSPEC )); then
        build_into "$SWAPS" --with-skinspec
        echo "NOTE: this build welds the gloss to the skin overlay -- there is"
        echo "      no way to A/B it against c1 alone. Use --sets for that."
    else
        build_into "$SWAPS"
    fi
fi

DEST="$INSTALL_DIR/swaps.skin"
mkdir -p "$DEST"
rm -f "$DEST"/*.spv
cp -f "$SWAPS"/*.spv "$DEST/"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
inst=("$DEST"/*.spv)
echo "installed ${#inst[@]} compute swap(s) -> $DEST (overlay 'skin')"

# --sets additionally PARKS every rung in skin.set/<level>/. The layer never
# reads that dir -- it only serves swaps.<name> -- so parking is inert until
# sync_settings.sh copies the level named by skinspec into swaps.skin/ at
# launch. The rm -rf is load-bearing: level names change (the old two-set
# {off,on} became a five-rung ladder), and a stale dir left behind is a level
# the selector can still be pointed at while nothing rebuilds it.
if (( SETS )); then
    rm -rf "$INSTALL_DIR/skin.set"
    for v in "${BUILT_SETS[@]}"; do
        vd="$INSTALL_DIR/skin.set/$v"
        mkdir -p "$vd"
        rm -f "$vd"/*.spv
        # -p so the mtime comes from the build, not from this copy: without it
        # every launch would hash a fresh payload and evict the pipeline caches
        # (the cp -p GOTCHA -- it cost a session of "the mod does nothing").
        cp -pf "$MOD_DIR/swaps.skin.$v"/*.spv "$vd/"
    done
    echo "parked ${#BUILT_SETS[@]} sets -> $INSTALL_DIR/skin.set: ${BUILT_SETS[*]}"
    echo "  the CET selector 'Oily / wet skin' (skinspec) picks between them"
fi

if [[ -f "$INSTALL_DIR/skin.disable" ]]; then
    echo "NOTE: skin.disable present -- the overlay is currently OFF"
fi

if [[ -z "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared"
fi
echo "next: : > ~/callisto_swap.jsonl ; launch ; face in frame"
