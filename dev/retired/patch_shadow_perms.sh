#!/usr/bin/env bash
# Patch the rgs_shadow_main family -- the raygens the game ACTUALLY dispatches.
#
#   ./dev/patch_shadow_perms.sh              # ungated tint (run this FIRST)
#   ./dev/patch_shadow_perms.sh --hairhunt   # per-class palette, gated
#   ./dev/patch_shadow_perms.sh /path/to/dumps
#
# Every live session so far dispatched only rgs_shadow_main-family pipelines
# and never rgs_reference_main (handoff/04-RESET-STATE.md), so the reference
# builds were correct but never executed. This targets the dispatched surface.
#
# Prereq: one launch with the dump layer installed and
#   CALLISTO_DUMP_DIR=$HOME/callisto_dump CALLISTO_DUMP_MATCH=rgs_shadow_main
# in the launch options; reach gameplay, then quit.
#
# Unlike patch_all_perms.sh this does NOT clear the reference swaps -- only
# the shadow ones are replaced, so a reference build stays installed and both
# surfaces are covered whichever the game dispatches.
#
# Modules with no 1/pi constant are shadow-visibility raygens that carry no
# shading at all; they are reported as skipped, which is expected, not a bug.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Overridable so the pipeline can be exercised without touching the real
# install or wiping the game's shader cache (CALLISTO_NO_CACHE_CLEAR=1).
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps}"
WORK="$MOD_DIR/dev/disasm/shadow"

TIER_ARGS=(--tier forcetint --set tint_r=6.0 --set tint_g=0.05 --set tint_b=0.05)
TIER_NAME=forcetint
for a in "$@"; do
    case "$a" in
        --hairhunt)  TIER_ARGS=(--tier hairhunt); TIER_NAME=hairhunt ;;
        --forcetint) ;;
        -*) echo "unknown flag: $a" >&2; exit 2 ;;
        *)  DUMP_DIR="$a" ;;
    esac
done

shopt -s nullglob
dumps=("$DUMP_DIR"/*.rgs_shadow_main.spv)
if (( ${#dumps[@]} == 0 )); then
    echo "no dumped rgs_shadow_main modules in $DUMP_DIR" >&2
    echo "launch once with: CALLISTO_DUMP_DIR=\$HOME/callisto_dump CALLISTO_DUMP_MATCH=rgs_shadow_main" >&2
    exit 1
fi
echo "=== tier $TIER_NAME | ${#dumps[@]} dumped shadow raygen(s) in $DUMP_DIR ==="

if [[ -f "$HOME/callisto_swap.jsonl" ]]; then
    echo "--- dispatched raygen(s) in the current log ---"
    grep -o '"rgs":"[^"]*"' "$HOME/callisto_swap.jsonl" 2>/dev/null \
        | sort -u | sed 's/^/  /' || echo "  (none logged)"
fi

rm -rf "$WORK"; mkdir -p "$WORK"
asms=()
for f in "${dumps[@]}"; do
    out="$WORK/$(basename "${f%.spv}").spvasm"
    spirv-dis "$f" -o "$out"
    asms+=("$out")
done

rm -f "$SWAPS"/*.rgs_shadow_main.spv "$SWAPS"/*.rgs_shadow_main.spvasm 2>/dev/null || true
pass=(); noshade=(); fail=()
for a in "${asms[@]}"; do
    name="$(basename "${a%.spvasm}")"
    if python3 "$MOD_DIR/dev/patch_shadow_brdf.py" "$a" "${TIER_ARGS[@]}" \
            --outdir "$SWAPS" > "$SWAPS/.shadow.$name.json" 2>"$SWAPS/.shadow.$name.err"; then
        pass+=("$name")
        sites=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]))[0];print(d['triples'])" "$SWAPS/.shadow.$name.json" 2>/dev/null || echo '?')
        echo "  patched  $name  ($sites eval sites)"
    elif grep -q "1/pi constant not found\|no 1/pi diffuse triples" "$SWAPS/.shadow.$name.err"; then
        noshade+=("$name")
        echo "  skipped  $name  (no diffuse shading in this raygen)"
    else
        fail+=("$name")
        echo "  FAILED   $name  (see swaps/.shadow.$name.err)"
    fi
done

if (( ${#pass[@]} == 0 )); then
    echo "nothing patched -- no swaps installed" >&2
    exit 1
fi

first_rep="$(ls "$SWAPS"/.shadow.*.json 2>/dev/null | head -1 || true)"
if [[ -n "$first_rep" ]]; then cp -f "$first_rep" "$SWAPS/shadow_report.json"; fi

python3 - "$SWAPS/shadow_report.json" <<'PY' 2>/dev/null || true
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
rm -f "$INSTALL_DIR/swaps"/*.rgs_shadow_main.spv
cp -f "$SWAPS"/*.rgs_shadow_main.spv "$INSTALL_DIR/swaps/"
# Counted by globbing into an array: `ls <glob> | wc -l` reports the whole
# working directory when nullglob eats an empty match.
inst_shadow=("$INSTALL_DIR/swaps"/*.rgs_shadow_main.spv)
inst_ref=("$INSTALL_DIR/swaps"/*.rgs_reference_main.spv)
echo "installed ${#inst_shadow[@]} shadow swap(s) -> $INSTALL_DIR/swaps"
echo "  (reference swaps left in place: ${#inst_ref[@]})"

if [[ -n "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    echo "cache clear SKIPPED (CALLISTO_NO_CACHE_CLEAR set)"
else
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared (first launch after this will be slow -- normal)"
fi

if (( ${#noshade[@]} > 0 )); then
    echo "note: ${#noshade[@]} raygen(s) carry no diffuse shading (expected):"
    printf '  %s\n' "${noshade[@]}"
fi
if (( ${#fail[@]} > 0 )); then
    echo
    echo "WARNING: ${#fail[@]} module(s) failed to patch:"
    printf '  %s\n' "${fail[@]}"
fi

cat <<'MSG'

Next:
  : > ~/callisto_swap.jsonl     # truncate; the log appends across runs
  launch, reach gameplay with a character in frame, then:
    grep '"ev":"trace_rays"' ~/callisto_swap.jsonl   # dispatched raygen(s)
    grep -c '"swap":"HIT"' ~/callisto_swap.jsonl     # swaps actually served

  forcetint: the screen should be visibly red wherever this raygen shades.
    no change  -> the shadow raygens are not shading the view either; the
                  dispatch log is then the only thing left to read.
    red        -> this IS the live shading surface. Re-run with --hairhunt
                  and read hair's class off the legend (skin must be red).
MSG
