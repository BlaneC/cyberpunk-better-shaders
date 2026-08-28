#!/usr/bin/env bash
# Build the path-tracing quality matrix (handoff/23 tier 1) and the reflection
# cullMask overlay.
#
#   ./dev/build_ptq.sh
#
# Three independent toggles all splice the SAME twelve `rgs_reference_main`
# permutations, and the swap layer serves the first file it finds for an id --
# so they cannot be three overlays. They are pre-built as a matrix of the seven
# non-empty combinations instead, and sync_settings.sh copies the selected one
# into swaps.ptq/ at launch. No patcher runs on the player's machine.
#
#   r  regularize   perceptual-roughness floor on indirect vertices (T1.1)
#   c  clamp        per-segment indirect radiance ceiling           (T1.2)
#   b  bounce       shading-ray cullMask 1 -> 255                   (T1.4)
#
# Each combo carries two bases, because skinray already ships a patched copy of
# two of the twelve permutations and an overlay hit would silently replace it:
#
#   <combo>/base/   all twelve, patched from vanilla   (skinray=off)
#   <combo>/skin/   the two skinray permutations, patched from the SKIN build,
#                   copied over base/ at launch        (skinray=on)
#
# The three reflection raygens have no path loop, so only the cullMask edit
# applies to them; nothing else touches those modules, so they ship as their
# own ordinary overlay (swaps.ptrefl/ + ptrefl.disable).
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${CALLISTO_DUMP:-$HOME/callisto_dump}"
SKIN="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}/swaps.prehunt"
OUT="$MOD_DIR/swaps.ptq.matrix"
REFL="$MOD_DIR/swaps.ptrefl"

# Compile-time constants. They are baked into the SPIR-V, so changing one means
# rebuilding the matrix -- there is no slider that could reach them at runtime.
#
# REG=0.25 perceptual roughness (alpha = 0.0625). Kaplanyan-style: enough to
#          turn a near-mirror second bounce into something the denoiser can
#          resolve, small enough that a genuinely rough surface is untouched.
# CLAMP=16 output units, i.e. the units the pass writes AFTER its own x1/64
#          scale. fp16 saturates the accumulator at 1023 of those units, and
#          plausible indirect radiance sits far below 16, so this is a firefly
#          ceiling rather than an exposure control.
REG=0.25
CLAMP=16

VANILLA=("$DUMP"/*.rgs_reference_main.spv)
REFLMODS=("$DUMP"/*.rgs_reflection_opaque_main.spv "$DUMP"/*.rgs_reflection_transparent_main.spv)
SKINMODS=("$SKIN"/*.rgs_reference_main.spv)

for f in "${VANILLA[@]}" "${REFLMODS[@]}"; do
    [[ -f "$f" ]] || { echo "missing dump module: $f" >&2; exit 2; }
done
[[ -f "${SKINMODS[0]:-}" ]] || { echo "no skin base in $SKIN -- run the skin build first" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
dis() {  # dis <outdir> <spv...>; echoes the .spvasm paths
    local d=$1; shift
    mkdir -p "$d"
    local out=()
    for f in "$@"; do
        local b; b="$(basename "$f" .spv)"
        spirv-dis --no-color "$f" -o "$d/$b.spvasm" || exit 1
        out+=("$d/$b.spvasm")
    done
    printf '%s\n' "${out[@]}"
}
mapfile -t VASM < <(dis "$WORK/vanilla" "${VANILLA[@]}")
mapfile -t SASM < <(dis "$WORK/skin"    "${SKINMODS[@]}")
mapfile -t RASM < <(dis "$WORK/refl"    "${REFLMODS[@]}")

args() {  # args <combo> -> the patcher flags that combo means
    local a=()
    [[ $1 == *r* ]] && a+=(--regularize "$REG")
    [[ $1 == *c* ]] && a+=(--clamp "$CLAMP")
    [[ $1 == *b* ]] && a+=(--bounce-mask)
    printf '%s\n' "${a[@]}"
}

run() {  # run <outdir> <combo> <spvasm...>
    local d=$1 combo=$2; shift 2
    local flags=(); mapfile -t flags < <(args "$combo")
    # --no-roundtrip-check: the vanilla round trip is proven once below, and
    # re-proving it 7x14 times triples the build for no new information.
    python3 "$MOD_DIR/dev/patch_pt_quality.py" "$@" --outdir "$d" \
            --no-roundtrip-check "${flags[@]}" >/dev/null
}

echo "round-tripping the unpatched modules once (spirv-as + spirv-val):"
for f in "${VASM[@]}" "${SASM[@]}" "${RASM[@]}"; do
    spirv-as --target-env spv1.4 "$f" -o "$WORK/rt.spv" >/dev/null 2>&1 \
        && spirv-val "$WORK/rt.spv" >/dev/null 2>&1 \
        || { echo "  FAIL $(basename "$f")" >&2; exit 2; }
done
echo "  ok (${#VASM[@]} vanilla + ${#SASM[@]} skin + ${#RASM[@]} reflection)"

rm -rf "$OUT" "$REFL"
echo "building the {r,c,b} matrix (reg=$REG clamp=$CLAMP):"
for combo in b c r cb rb rc rcb; do
    if run "$OUT/$combo/base" "$combo" "${VASM[@]}" \
       && run "$OUT/$combo/skin" "$combo" "${SASM[@]}"; then
        echo "  ok   $combo ($(ls "$OUT/$combo/base"/*.spv | wc -l) base + $(ls "$OUT/$combo/skin"/*.spv | wc -l) skin)"
    else
        echo "  FAIL $combo" >&2; exit 2
    fi
done

echo "building the reflection cullMask overlay:"
if run "$REFL" b "${RASM[@]}"; then
    echo "  ok   ptrefl ($(ls "$REFL"/*.spv | wc -l)/${#RASM[@]} modules)"
else
    echo "  FAIL ptrefl" >&2; exit 2
fi

# The matrix is 7x14 modules; keeping their disassembly triples it on disk for
# no benefit -- the per-module .spvasm of any single build is one patcher run
# away. ptrefl is three modules, so its asm stays for inspection.
find "$OUT" -name '*.spvasm' -delete

echo "done. install with: ./dev/install_ptq.sh"
