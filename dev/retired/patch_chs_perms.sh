#!/usr/bin/env bash
# Patch the closest-hit shaders -- where LIVE PATH TRACING actually shades.
#
#   ./dev/patch_chs_perms.sh                  # ungated red on the PT diffuse
#   ./dev/patch_chs_perms.sh /path/to/dumps
#
# The clean vanilla PT session dispatched thin whole-library raygens
# (fd1d0f0c84607e41, c6bce844e971491a) that contain NO shading at all -- no
# 1/pi, no Disney. PT shades in the closest-hit shader reached through the
# pipeline's SBT, which trace_rays logging can never reveal because it only
# records raygens. Every earlier patcher targeted raygens, which is why PT
# frames always rendered vanilla. See handoff/06-PT-IS-THE-CHS.md.
#
# Only hit shaders that actually carry the Disney diffuse anchor are patched;
# the rest are hit shaders for shadow/alpha-test rays with no shading and are
# reported as skipped, which is expected.
#
# Existing reference/shadow swaps are left installed -- this only adds the
# hit-shader swaps, so whichever surface the game uses is covered.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps}"
WORK="$MOD_DIR/dev/disasm/chs"

TINT=(--set tint_r=6.0 --set tint_g=0.05 --set tint_b=0.05)
for a in "$@"; do
    case "$a" in
        -*) echo "unknown flag: $a" >&2; exit 2 ;;
        *)  DUMP_DIR="$a" ;;
    esac
done

shopt -s nullglob
dumps=("$DUMP_DIR"/*.chs_*.spv "$DUMP_DIR"/*.ahs_*.spv)
if (( ${#dumps[@]} == 0 )); then
    echo "no dumped hit shaders in $DUMP_DIR" >&2
    echo "launch once with CALLISTO_DUMP_DIR=\$HOME/callisto_dump and no DUMP_MATCH" >&2
    exit 1
fi
echo "=== ${#dumps[@]} dumped hit shader(s) in $DUMP_DIR ==="

rm -rf "$WORK"; mkdir -p "$WORK"
rm -f "$SWAPS"/*.chs_*.spv "$SWAPS"/*.chs_*.spvasm \
      "$SWAPS"/*.ahs_*.spv "$SWAPS"/*.ahs_*.spvasm 2>/dev/null || true

pass=(); noshade=(); fail=()
for f in "${dumps[@]}"; do
    name="$(basename "${f%.spv}")"
    asm="$WORK/$name.spvasm"
    spirv-dis "$f" -o "$asm" 2>/dev/null || { fail+=("$name"); continue; }
    if python3 "$MOD_DIR/dev/patch_chs_brdf.py" "$asm" --tier forcetint "${TINT[@]}" \
            --outdir "$SWAPS" > "$SWAPS/.chs.$name.json" 2>"$SWAPS/.chs.$name.err"; then
        sites=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[0]['diffuse_sites'])" \
                "$SWAPS/.chs.$name.json" 2>/dev/null || echo '?')
        pass+=("$name")
        echo "  patched  $name  ($sites diffuse site(s))"
    # A hit shader with no 1/pi, no Disney, or not even a GLSL.std.450 import
    # carries no shading at all (shadow/alpha-test hit groups). Not a failure.
    elif grep -q "carries no Disney diffuse\|1/pi constant not found\|no GLSL.std.450 NClamp found" \
            "$SWAPS/.chs.$name.err"; then
        noshade+=("$name")
    else
        fail+=("$name")
        echo "  FAILED   $name  (see swaps/.chs.$name.err)"
    fi
done

if (( ${#pass[@]} == 0 )); then
    echo "no hit shader carried the Disney diffuse anchor -- nothing installed" >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR/swaps"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$SWAPS"/*.chs_*.spv "$INSTALL_DIR/swaps/" 2>/dev/null || true
cp -f "$SWAPS"/*.ahs_*.spv "$INSTALL_DIR/swaps/" 2>/dev/null || true

inst_chs=("$INSTALL_DIR/swaps"/*.chs_*.spv)
inst_rgs=("$INSTALL_DIR/swaps"/*.rgs_*.spv)
echo "installed ${#inst_chs[@]} hit-shader swap(s) -> $INSTALL_DIR/swaps"
echo "  (raygen swaps left in place: ${#inst_rgs[@]})"
echo "  skipped ${#noshade[@]} hit shader(s) with no Disney diffuse (expected)"

if [[ -n "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    echo "cache clear SKIPPED (CALLISTO_NO_CACHE_CLEAR set)"
else
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared (first launch after this will be slow -- normal)"
fi

if (( ${#fail[@]} > 0 )); then
    echo
    echo "WARNING: ${#fail[@]} module(s) failed to patch:"
    printf '  %s\n' "${fail[@]}"
fi

cat <<'MSG'

Next:
  : > ~/callisto_swap.jsonl
  launch with PATH TRACING on, reach gameplay, then:
    grep '"ev":"module"' ~/callisto_swap.jsonl | grep chs_main | grep HIT

  red screen  -> CONFIRMED: the closest-hit shader is the live PT shading
                 surface. The hair BRDF work moves here. Note this shader has
                 NO gbuf class gate, so hair needs a different gate signal --
                 that is the next question to answer, not the tint.
  no change   -> this CHS is not in the PT pipeline's SBT. Widen: patch every
                 hit shader carrying the anchor, and dump with no DUMP_MATCH
                 so no hit group is missed.
MSG
