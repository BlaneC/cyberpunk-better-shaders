#!/usr/bin/env bash
# gi-50-bleed: the standing rung (gi-50) plus ONE variable -- the terminator
# colour bleed on the compute half (handoff/53).
#
#   ./dev/build_gi_bleed.sh              # assemble + verify (no install)
#   ./dev/build_gi_bleed.sh --install    # ALSO park as skin.set/gi-50-bleed
#
# Composition, and why it is an ASSEMBLY and not a patcher run: gi-50 is
# 77 compute (real-gloss) + 12 rgs_reference (ser.set/class) + 4 rgs_restirgi
# splices + MANIFEST (dev/build_gi_rung.sh). The bleed lives only in the
# compute half, so this copies gi-50's SIXTEEN raygen files BYTE-VERBATIM
# (asserted below) and swaps the 77 compute for skin.set/real-gloss-bleed.
# The A/B "gi-50 vs gi-50-bleed" is then one variable by construction.
# Provenance fields (src_ser/ser_sha/ptq_sha) carry over VERBATIM: the
# raygens are gi-50's own bytes, so gi-50's contract with sync_settings.sh's
# gi_refuse block still holds -- needs ser=class + shadowset=full-shadow.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
GI="$INSTALL_DIR/skin.set/gi-50"
RGB="$INSTALL_DIR/skin.set/real-gloss-bleed"
DEST="$MOD_DIR/swaps.gi.50-bleed"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt -- run ./dev/build_gi_rung.sh --install first" >&2; exit 1; }
[[ -d "$RGB" ]] || { echo "no $RGB -- run ./dev/patch_compute_skin.sh --sets" >&2; exit 1; }
n_rgb=$(ls "$RGB"/*.spv | wc -l)
[[ "$n_rgb" == 77 ]] || { echo "$RGB has $n_rgb modules, expected 77" >&2; exit 1; }

rm -rf "$DEST"; mkdir -p "$DEST"
cp -pf "$GI"/*.rgs_*.spv "$DEST/"
n_rgs=$(ls "$DEST"/*.rgs_*.spv | wc -l)
[[ "$n_rgs" == 16 ]] || { echo "copied $n_rgs raygen files from gi-50, expected 16 (12+4)" >&2; exit 1; }
cp -pf "$RGB"/*.spv "$DEST/"
n=$(ls "$DEST"/*.spv | wc -l)
[[ "$n" == 93 ]] || { echo "rung has $n modules, expected 93 (77+12+4)" >&2; exit 1; }

# raygens byte-identical to gi-50's -- the one-variable guarantee, half 1
for f in "$GI"/*.rgs_*.spv; do
    cmp -s "$f" "$DEST/$(basename "$f")" || { echo "raygen $(basename "$f") differs from gi-50 -- NOT one variable" >&2; exit 1; }
done
# compute half must differ from gi-50's (i.e. from real-gloss) on the modules
# the bleed reached -- half 2. Equal-coverage (same file list) asserted too.
diff <(cd "$GI" && ls *.dxil.spv) <(cd "$RGB" && ls *.dxil.spv) >/dev/null \
    || { echo "compute file lists differ between gi-50 and real-gloss-bleed" >&2; exit 1; }
d=0
for f in "$RGB"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || d=$((d+1))
done
(( d > 0 )) || { echo "real-gloss-bleed is byte-identical to gi-50's compute -- bleed emitted nothing" >&2; exit 1; }
echo "  compute: $d of 77 modules differ from gi-50 (bleed-covered)"

for f in "$DEST"/*.spv; do spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done

# MANIFEST: gi-50's provenance verbatim, renamed, compute half renamed.
sed -e '1s/^gi-50 /gi-50-bleed /' -e '1s/compute=77(real-gloss)/compute=77(real-gloss-bleed)/' \
    "$GI/MANIFEST.txt" > "$DEST/MANIFEST.txt"
grep -q '^gi-50-bleed .*compute=77(real-gloss-bleed)' "$DEST/MANIFEST.txt" \
    || { echo "MANIFEST rewrite failed -- check $GI/MANIFEST.txt line 1 format" >&2; exit 1; }
echo '# terminator colour bleed rides the compute half; raygens are gi-50 bytes; see handoff/53' >> "$DEST/MANIFEST.txt"
echo "  built $DEST: 93 modules, raygens = gi-50 bytes, all spirv-val clean"

if [[ "$DO_INSTALL" == 1 ]]; then
    park="$INSTALL_DIR/skin.set/gi-50-bleed"
    mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
    cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$park/"
    echo "  parked -> $park"
else
    echo "NOT installed. To park: ./dev/build_gi_bleed.sh --install"
fi
echo "select with skinspec=gi-50-bleed; needs ser=class, shadowset=full-shadow (gi-50's contract)"
