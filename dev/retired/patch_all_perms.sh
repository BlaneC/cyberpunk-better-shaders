#!/usr/bin/env bash
# Patch EVERY live rgs_reference_main permutation captured by the layer's
# dump mode -- the fix for "12 permutations exist, only 2 were patched".
#
#   ./dev/patch_all_perms.sh                  # hairhunt every dumped raygen
#   ./dev/patch_all_perms.sh --forcetint      # ungated red on every dumped raygen
#   ./dev/patch_all_perms.sh /path/to/dumps   # different dump dir
#
# Prereq: one launch with the dump layer installed and
#   CALLISTO_DUMP_DIR=$HOME/callisto_dump CALLISTO_DUMP_MATCH=rgs_reference_main
# in the launch options. Reach gameplay (so pipelines are actually built),
# then quit.
#
# Each permutation is patched independently: a structural-anchor failure on
# one does not block the rest. Failures are listed at the end; the modules
# that patched fine are installed and the caches are cleared.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="$HOME/callisto_dump"
GAME_DIR="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077"
SHADERCACHE="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500"
INSTALL_DIR="$HOME/.local/lib/callisto"
SWAPS="$MOD_DIR/swaps"
WORK="$MOD_DIR/dev/disasm/live"

TIER_ARGS=(--tier hairhunt)
for a in "$@"; do
    case "$a" in
        --forcetint) TIER_ARGS=(--tier forcetint --set tint_r=6.0 --set tint_g=0.05 --set tint_b=0.05) ;;
        -*) echo "unknown flag: $a" >&2; exit 2 ;;
        *)  DUMP_DIR="$a" ;;
    esac
done

shopt -s nullglob
dumps=("$DUMP_DIR"/*.rgs_reference_main.spv "$DUMP_DIR"/*.dxil.spv)
if (( ${#dumps[@]} == 0 )); then
    echo "no dumped raygen modules in $DUMP_DIR" >&2
    echo "launch once with: CALLISTO_DUMP_DIR=\$HOME/callisto_dump CALLISTO_DUMP_MATCH=rgs_reference_main" >&2
    echo "(or CALLISTO_DUMP_MATCH=dxil for the whole-library modules PT dispatches)" >&2
    exit 1
fi
echo "=== ${#dumps[@]} dumped raygen permutation(s)/libraries in $DUMP_DIR ==="

# Which raygen(s) has the game actually dispatched so far? (new layer only)
if [[ -f "$HOME/callisto_swap.jsonl" ]]; then
    echo "--- dispatched raygen(s) in the current log ---"
    grep -o '"ev":"trace_rays"[^}]*' "$HOME/callisto_swap.jsonl" | sort -u || echo "  (none -- is the new layer installed and the log truncated?)"
fi

rm -rf "$WORK"; mkdir -p "$WORK"
asms=()
for f in "${dumps[@]}"; do
    out="$WORK/$(basename "${f%.spv}").spvasm"
    spirv-dis "$f" -o "$out"
    asms+=("$out")
done

rm -f "$SWAPS"/*.spv "$SWAPS"/*.spvasm 2>/dev/null || true
pass=(); fail=()
for a in "${asms[@]}"; do
    name="$(basename "${a%.spvasm}")"
    if python3 "$MOD_DIR/dev/patch_skin_brdf.py" "$a" "${TIER_ARGS[@]}" \
            --outdir "$SWAPS" > "$SWAPS/.report.$name.json" 2>"$SWAPS/.report.$name.err"; then
        pass+=("$name")
        echo "  patched  $name"
    else
        fail+=("$name")
        echo "  FAILED   $name  (see swaps/.report.$name.err)"
    fi
done
# Keep one report as the canonical hunt_report.json (all modules used the
# same tier/legend); per-module reports stay as .report.<name>.json.
first_rep="$(ls "$SWAPS"/.report.*.json 2>/dev/null | head -1 || true)"
if [[ -n "$first_rep" ]]; then cp -f "$first_rep" "$SWAPS/hunt_report.json"; fi

if (( ${#pass[@]} == 0 )); then
    echo "nothing patched -- no swaps installed" >&2
    exit 1
fi

# Legend for the hunt tier, from whichever module reported it.
python3 - "$SWAPS/hunt_report.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    rep = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
if isinstance(rep, list) and rep and "hunt" in rep[0]:
    print("=== colour legend ===")
    for e in rep[0]["hunt"]["legend"]:
        note = "  <- skin, CONTROL" if e["class"] == 1 else ""
        print(f"  class {e['class']:>2} = {e['colour']}{note}")
PY

mkdir -p "$INSTALL_DIR/swaps"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
rm -f "$INSTALL_DIR/swaps"/*.spv
cp -f "$SWAPS"/*.spv "$INSTALL_DIR/swaps/"
echo "installed $(ls "$INSTALL_DIR/swaps" | wc -l) swap(s) -> $INSTALL_DIR/swaps"

rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
echo "caches cleared (first launch after this will be slow -- normal)"

if (( ${#fail[@]} > 0 )); then
    echo
    echo "WARNING: ${#fail[@]} permutation(s) did not patch:"
    printf '  %s\n' "${fail[@]}"
    echo "If the game dispatches one of these, nothing will change on screen."
fi

cat <<'MSG'

Next:
  : > ~/callisto_swap.jsonl     # truncate; the log appends across runs
  launch the game, then check:
    grep '"ev":"trace_rays"' ~/callisto_swap.jsonl   # the DISPATCHED raygen(s)
    grep -c '"swap":"HIT"' ~/callisto_swap.jsonl     # swaps actually served
  If the dispatched rgs has swapped=1 and skin is still not red, the problem
  is the gate/class value, not the permutation.

Restore the pre-hunt tier-1 build at any time:
  ./dev/hunt_hair_class.sh --restore
MSG
