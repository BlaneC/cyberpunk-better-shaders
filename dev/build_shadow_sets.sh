#!/usr/bin/env bash
# Build the content sets for the `shadowcull` overlay.
#
#   ./dev/build_shadow_sets.sh                    # the shipping sets
#   ./dev/build_shadow_sets.sh full-shadow        # just one
#
# sync_settings.sh materializes the chosen set into swaps.shadowcull/ at
# launch; the CET selector offers the same names.
#
# SHIPPING
#   full-shadow  flags 28 -> 12 in place (back-face culling off) on the 10
#                rgs_shadow modules. Closes the hairline seam; leaves reduced
#                flicker on flat props at LOD transitions. THE DEFAULT.
#   full         the same edit on all 18 modules (full-shadow + the 8
#                rgs_restirgi_*). Also closes the seam, flickers more; the GI
#                half is pure cost. Kept as the original proven build.
#
# RETIRED -- recipes preserved below so the results stay reproducible, but not
# built or installed, because each one is either falsified or built on a
# mechanism that does not execute. See handoff/26-SESSION-0828.md.
#
#   Falsified on screen:
#     split               patch_shadow_opacity.py
#         vanilla ray + a second CullOpaque (76) ray, min-combined. The seam
#         came back => the hairline occluder is authored OPAQUE and opacity is
#         not a discriminator.
#     full-shadow-nosun   patch_shadow_flags.py --tmin-sites nonzero
#     full-shadow-sun     patch_shadow_flags.py --tmin-sites zero
#     full-shadow-bias    patch_shadow_flags.py --set-zero-tmin 0.001
#         The 20 shadow sites split by extent: 17 bounded (tMin 1e-6) and 3
#         unbounded with tMin exactly 0 (sun). The theory was that the 3 sun
#         rays were the flicker, back-face culling being their only
#         self-intersection guard. `full-shadow-nosun` closed the seam with the
#         flicker UNCHANGED, so the 17 bounded sites are necessary, sufficient,
#         AND where the flicker lives. Theory dead.
#     full-gi             patch_shadow_flags.py, filter '\.rgs_restirgi'
#         The GI half alone. Flicker, no visible seam contribution.
#
#   Void -- the two-ray splice never executes:
#     sctrl   patch_shadow_opacity.py --ray-b-flags 12, filter '\.rgs_shadow'
#         The POSITIVE control. Ray A vanilla (28) + ray B unculled (12), same
#         mask, min-combined. Ray 12's hit set is a strict superset of ray
#         28's, so tB <= tA always and min() is always ray B: a working splice
#         MUST look exactly like full-shadow. It came back VANILLA. The
#         disassembly is correct -- paired OpTraceRayKHR into the same payload,
#         OpFOrdLessThan + OpSelect, FLT_MAX miss test consuming the result --
#         so the edit is right and the second trace simply does not run.
#     ctrl m1 m2 m4 m6 m16 m32 m64 m112 m118 m119 sm6 sm112
#         All ray-B cull-mask bisects. Uninterpretable: they vary a ray that
#         never executes. `ctrl` additionally could never have decided
#         anything, being neutral by construction ("looks vanilla" is equally
#         consistent with a working splice and an inert one) -- which is why
#         `sctrl` was built loud.
#
# The standing conclusion: ray flags are per-RAY, so no subset of trace sites
# can separate "the hair loses culling" from "the flat props lose culling".
# Only the CullMask selects geometry, and reaching it needs a second ray, which
# does not run. full-shadow is therefore the best available build.
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${CALLISTO_DUMP:-$HOME/callisto_dump}"
WORK="$MOD_DIR/dev/disasm/shadowsets"

# name    patcher                  extra args
VARIANTS=(
  "full-shadow  patch_shadow_flags.py"
  "full         patch_shadow_flags.py"
)

# Module-subset variants. These apply `full`'s exact in-place 28->12 edit to
# only PART of the 18 modules, so they use the one mechanism that is proven to
# work on screen (17 launches) rather than the second ray, which is not.
# A module absent from the overlay is simply served by the game unpatched.
declare -A FILTER=(
  ["full-shadow"]='\.rgs_shadow'
)

WANT=("$@")
want() {
    (( ${#WANT[@]} == 0 )) && return 0
    local w; for w in "${WANT[@]}"; do [[ "$w" == "$1" ]] && return 0; done
    return 1
}

shopt -s nullglob
mkdir -p "$WORK"
ASM=()
for f in "$DUMP"/*.rgs_shadow_main.spv "$DUMP"/*.rgs_shadow_transparent_main.spv \
         "$DUMP"/*.rgs_restirgi_*.spv; do
    b="$(basename "$f" .spv)"
    [[ -f "$WORK/$b.spvasm" ]] || spirv-dis --no-color "$f" -o "$WORK/$b.spvasm" || exit 1
    ASM+=("$WORK/$b.spvasm")
done
echo "candidates: ${#ASM[@]} modules"

# The patchers die on a module with no anchor, which is the normal case here
# (initial_temporal traces nothing at all) -- so drive them one module at a
# time and count, rather than letting one skip abort the set.
build() {  # build <outdir> <patcher> <filter-regex-or-empty> [args...]
    local out=$1 patcher=$2 filter=$3; shift 3
    local f=0
    rm -rf "$out"; mkdir -p "$out"
    for a in "${ASM[@]}"; do
        [[ -n "$filter" && ! "$(basename "$a")" =~ $filter ]] && continue
        if python3 "$MOD_DIR/dev/$patcher" "$a" --outdir "$out" \
                   --no-roundtrip-check "$@" >/dev/null 2>"$out/.err"; then
            :  # wrote a swap, or found no anchor and said so in its report
        elif grep -qE "no back-face-culling shadow ray|KeyError|IndexError" "$out/.err"; then
            : # no anchor in this module -- expected
        elif [[ -s "$out/.err" ]]; then
            echo "  FAILED $(basename "$a" .spvasm): $(head -1 "$out/.err" | cut -c1-70)" >&2
            f=$((f+1))
        fi
    done
    rm -f "$out/.err"
    printf '  %-6s %-28s %2d modules, %d failed\n' \
        "$(basename "$out" | sed 's/^swaps\.shadowcull\.//')" "$*" \
        "$(ls "$out"/*.spv 2>/dev/null | wc -l)" "$f"
    (( f == 0 ))
}

echo "round-tripping the unpatched modules once:"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
for a in "${ASM[@]}"; do
    spirv-as --target-env spv1.4 "$a" -o "$T/rt.spv" >/dev/null 2>&1 \
        && spirv-val "$T/rt.spv" >/dev/null 2>&1 \
        || { echo "  FAIL $(basename "$a")" >&2; exit 2; }
done
echo "  ok"

echo "building:"
BUILT=()
for v in "${VARIANTS[@]}"; do
    read -r name patcher args <<<"$(echo "$v" | sed 's/  */ /g')"
    read -ra argv <<<"${args:-}"
    want "$name" || continue
    build "$MOD_DIR/swaps.shadowcull.$name" "$patcher" "${FILTER[$name]:-}" "${argv[@]}" || exit 2
    BUILT+=("$name")
done

# Every set must cover the same ids as `full`, or the CET selector would also
# be switching coverage and an A/B could attribute nothing.
ref="$MOD_DIR/swaps.shadowcull.full"
if [[ -d "$ref" ]]; then
    a="$(cd "$ref" && ls *.spv | sort)"
    for name in "${BUILT[@]}"; do
        b="$(cd "$MOD_DIR/swaps.shadowcull.$name" && ls *.spv | sort)"
        if [[ -n "${FILTER[$name]:-}" ]]; then
            # A subset variant must be a non-empty STRICT subset of full: the
            # point is that the modules it omits stay vanilla.
            [[ -n "$b" ]] || { echo "set '$name' is empty -- filter matched nothing" >&2; exit 2; }
            comm -13 <(echo "$a") <(echo "$b") | grep -q . \
                && { echo "set '$name' covers modules 'full' does not" >&2; exit 2; }
            echo "  $name: $(echo "$b" | wc -l) of $(echo "$a" | wc -l) modules (subset, by design)"
            continue
        fi
        [[ "$a" == "$b" ]] && continue
        echo "MISMATCH: set '$name' covers different modules than 'full'" >&2
        diff <(echo "$a") <(echo "$b") >&2
        exit 2
    done
    echo "  full-coverage sets all cover the same $(echo "$a" | wc -l) modules"
fi
echo "done. install with: ./dev/install_shadow_sets.sh"
