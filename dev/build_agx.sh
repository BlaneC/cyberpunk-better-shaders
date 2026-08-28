#!/usr/bin/env bash
# Rebuild every AgX variant from the captured LUT-generator modules.
#
#   ./dev/build_agx.sh            # all variants -> swaps.agx.<name>/
#
# Both permutations are built every time: SDR and HDR dispatch different
# compilations of the same pass, so a variant with only one is half-installed.
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${CALLISTO_DUMP:-$HOME/callisto_dump}"
# Ten permutations of the tonemap-LUT generator.  The first two are the HDR
# pair (ACES output transform, float mode ladder); the other eight are SDR
# (integer encode ladder), and were invisible to the first scanner because it
# required the float ladder.  The eight are a 2x2 lattice of two compile-time
# booleans -- ACES-fit matrices present, cbv[30] luminance normalisation
# present -- and in one corner the tone curve is compiled away entirely.
# patch_agx.py --site auto picks the right splice for each: ap1 for the HDR
# pair, sdr2 for all eight SDR ones.
IDS=(b174eb4af0fea652 1d02efd8fe8014cc
     065fcdcc6ce51fe7 1c9000b415918fb1 6040914437ae18cb 7a858d59a4d6705c
     8bbd5900a4074442 90fa8b3f5068b7d8 e0e20375b6685f6a ef31e1058af96c51)
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

ASM=()
for ID in "${IDS[@]}"; do
    spirv-dis "$DUMP/$ID.dxil.spv" -o "$WORK/$ID.dxil.spvasm" || exit 1
    ASM+=("$WORK/$ID.dxil.spvasm")
done

build() {  # build <name> <patch_agx args...>
    local name=$1; shift
    rm -rf "$MOD_DIR/swaps.agx.$name"
    if python3 "$MOD_DIR/dev/patch_agx.py" "${ASM[@]}" \
           --outdir "$MOD_DIR/swaps.agx.$name" "$@" >/dev/null; then
        echo "  ok   $name ($(ls "$MOD_DIR/swaps.agx.$name"/*.spv | wc -l)/${#IDS[@]} modules)"
    else
        echo "  FAIL $name" >&2
    fi
}

# Every look builds GRADED (patch_agx's grade=1 default) in BOTH display
# modes: AgX is fed the game's own graded, exposure-scaled scene colour
# instead of the raw log shaper, so the authored per-area grade and the
# per-setup exposure survive.  SDR reaches the same contract through --site
# sdr2, which replaces the game's own tone curve between the two grade-stack
# gates instead of splicing at the basic grade's output the way the old
# --site sdr did -- that was upstream of the curve, so the curve ran on top of
# AgX and SDR read dark.
echo "building AgX variants (site=auto: ap1 for HDR, sdr2 for SDR):"
build neutral
build punchy        --look punchy
build punchy70      --look punchy70
build punchy70desat --look punchy70desat
build golden        --look golden

# Saturation bracket around punchy70desat (sat 1.175), so 5% and 10% less
# chroma than punchy70 can be judged against it in the same session.  `sat`
# multiplies the distance from luma, so the number is the chroma scale.
build punchy70.sat95 --look punchy70 --set sat=1.207
build punchy70.sat90 --look punchy70 --set sat=1.143

# A/B legs.
#   .nograde  AgX at the right site but fed the RAW shaper: no grade, no
#             exposure.  (Not the same as the build that shipped before SDR
#             was fixed -- that one also spliced at the wrong SDR site.)
#   .preexp   graded but WITHOUT cbv[42].z, so "the grade came back" and "the
#             exposure came back" can be told apart instead of confounded
#   .hue      AgX drives everything past max_ev to white, which a warm grade
#             cannot undo; this restores highlight chroma so the sun can read
#             yellow rather than white
build punchy70.nograde --look punchy70 --set grade=0
build neutral.nograde                  --set grade=0
build punchy70.preexp  --look punchy70 --set grade=2
build punchy70.hue     --look punchy70 --set hue_restore=0.5

build half    --set mix=0.5
build quarter --set mix=0.25
build diag    --set tint_g=4.0 --set tint_r=0.15 --set tint_b=0.15
echo "done. install with: ./dev/install_agx.sh <name>"
