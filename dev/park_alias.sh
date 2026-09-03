#!/usr/bin/env bash
# park_alias.sh -- give a parked rung a SECOND, self-describing name.
#
#   ./dev/park_alias.sh <source rung> <alias> [--install]
#
# The layer picks a skin overlay by DIRECTORY: sync_settings.sh copies
# skin.set/<skinspec>/ into swaps.skin/, so the value of `skinspec` is a
# directory name and nothing else.  A rung built by build_earglow7.sh is
# therefore parked under its rung name (earglow7-hue1), which says what the
# LAST edit was and nothing about the stack underneath it -- while the stack
# names that came before it (gi-50b-...-cap6-glintdense-curv) say the whole
# chain.  This makes an alias: the same 93 bytes under the long name, so the
# CET selector reads as a chain again.
#
# It is a COPY, not a symlink -- `make install` and sync_settings.sh both
# cp -a, and a dangling link would be served as an empty overlay, which is the
# exact failure mode of 111 sec 0.1.  Both directories are asserted
# byte-identical afterwards, in both directions, so the two names can never
# drift into meaning different shaders.
#
# MANIFEST.txt line 1 is rewritten to name the alias and record what it is an
# alias OF; every other line -- the whole provenance chain the guard in
# sync_settings.sh reads (src_ser/ser_sha/ptq_sha) -- is carried through
# untouched, because dropping it is what gets a rung refused as gi-no-manifest.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/lib/callisto}"
DO_INSTALL=0

SRC_RUNG="${1:?usage: park_alias.sh <source rung> <alias> [--install]}"
ALIAS="${2:?usage: park_alias.sh <source rung> <alias> [--install]}"
shift 2
for a in "$@"; do
    case "$a" in
        --install) DO_INSTALL=1 ;;
        *) echo "unknown arg: $a" >&2; exit 2 ;;
    esac
done

SRC="$MOD_DIR/swaps.$SRC_RUNG"
DST="$MOD_DIR/swaps.$ALIAS"
[[ -d "$SRC" ]] || { echo "no such rung: $SRC" >&2; exit 1; }
[[ "$SRC_RUNG" != "$ALIAS" ]] || { echo "alias equals source" >&2; exit 1; }
[[ -f "$SRC/MANIFEST.txt" ]] || {
    echo "$SRC has no MANIFEST.txt -- a raygen-bearing rung without one is" >&2
    echo "refused at launch as gi-no-manifest (111 sec 0.1).  Refusing." >&2
    exit 1; }

echo "=== copy  swaps.$SRC_RUNG -> swaps.$ALIAS"
rm -rf "$DST"
cp -a "$SRC" "$DST"

# Line 1 names the rung; the rest is provenance and is carried verbatim.
{
    printf '%s (ALIAS of %s -- the same bytes under the full stack name; dev/park_alias.sh)\n' \
        "$ALIAS" "$SRC_RUNG"
    tail -n +2 "$SRC/MANIFEST.txt"
} > "$DST/MANIFEST.txt"

echo "=== gate 1: the alias is byte-identical to its source, both directions"
n=0
for f in "$SRC"/*.spv; do
    b="$(basename "$f")"
    cmp -s "$f" "$DST/$b" || { echo "  !! differs: $b" >&2; exit 1; }
    n=$((n+1))
done
for f in "$DST"/*.spv; do
    b="$(basename "$f")"
    [[ -f "$SRC/$b" ]] || { echo "  !! extra module in alias: $b" >&2; exit 1; }
done
echo "  $n modules, cmp clean both ways"

echo "=== gate 2: the provenance the launch guard reads survived the rewrite"
for tok in src_ser= ser_sha= ptq_sha=; do
    a="$(grep -o -- "$tok[^ ]*" "$SRC/MANIFEST.txt" | head -1)"
    [[ -n "$a" ]] || { echo "  !! source MANIFEST lacks $tok" >&2; exit 1; }
    grep -q -- "$a" "$DST/MANIFEST.txt" || {
        echo "  !! alias MANIFEST lost $a -- would be refused gi-no-manifest" >&2
        exit 1; }
    echo "  carried: $a"
done

if (( DO_INSTALL )); then
    echo "=== install"
    rm -rf "$INSTALL_DIR/skin.set/$ALIAS"
    cp -a "$DST" "$INSTALL_DIR/skin.set/$ALIAS"
    m=0
    for f in "$DST"/*.spv; do
        cmp -s "$f" "$INSTALL_DIR/skin.set/$ALIAS/$(basename "$f")" \
            || { echo "  !! install differs: $(basename "$f")" >&2; exit 1; }
        m=$((m+1))
    done
    echo "  installed $ALIAS ($m modules, cmp clean)"
fi
echo "=== done"
