#!/usr/bin/env bash
# Build + park the Phase 0.5 glass-refraction ladder (handoff/76):
#   swaps.refract.off/     the plain ptrefl transparent raygen, byte-identical
#                          copy -- the A/B control sync restores on refract=off
#   swaps.refract.eta15/   mirror direction repointed to refracted, n=1.5
#   swaps.refract.eta20/   same, n=2.0 -- exaggerated bend for adjudication
# --install parks the ladder at $INSTALL_DIR/refract.set/{off,eta15,eta20}/.
# The rung RIDES swaps.ptrefl/ (that overlay owns this module id, first-file-
# wins): sync_settings.sh materializes the chosen level INTO swaps.ptrefl/.
set -euo pipefail
cd "$(dirname "$0")/.."
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/lib/callisto}"
MOD=ee6d252e090adc74.rgs_reflection_transparent_main

python3 dev/patch_refract.py --n 1.5 --out swaps.refract.eta15
python3 dev/patch_refract.py --n 2.0 --out swaps.refract.eta20
mkdir -p swaps.refract.off
cp -pf "swaps.ptrefl/$MOD.spv" "swaps.ptrefl/$MOD.spvasm" swaps.refract.off/

# the two eta builds must differ from off and from each other
cmp -s "swaps.refract.off/$MOD.spv" "swaps.refract.eta15/$MOD.spv" && { echo "eta15 == off ?!"; exit 1; }
cmp -s "swaps.refract.eta15/$MOD.spv" "swaps.refract.eta20/$MOD.spv" && { echo "eta15 == eta20 ?!"; exit 1; }

for lvl in off eta15 eta20; do
    d="swaps.refract.$lvl"
    spirv-val "$d/$MOD.spv"
    sha="$(sha256sum "$d/$MOD.spv" | cut -c1-16)"
    case "$lvl" in
        off)   note="plain ptrefl (cullMask 255) transparent raygen, the A/B control" ;;
        eta15) note="refract n=1.5 eta=0.6667 origin=P+eps*D cullMask=255" ;;
        eta20) note="refract n=2.0 eta=0.5 origin=P+eps*D cullMask=255" ;;
    esac
    printf 'ptrefl refract=%s %s sha=%s built=%s\n# Phase 0.5 glass refraction (handoff/20 par5b, 76); rides swaps.ptrefl, materialized by sync_settings.sh\n' \
        "$lvl" "$note" "$sha" "$(date -Is)" > "$d/MANIFEST.txt"
    echo "  $lvl: $sha"
done

if [[ "${1:-}" == "--install" ]]; then
    for lvl in off eta15 eta20; do
        mkdir -p "$INSTALL_DIR/refract.set/$lvl"
        cp -pf "swaps.refract.$lvl/$MOD.spv" "swaps.refract.$lvl/MANIFEST.txt" \
               "$INSTALL_DIR/refract.set/$lvl/"
    done
    echo "installed -> $INSTALL_DIR/refract.set/ (select with refract=off|eta15|eta20; sync materializes into swaps.ptrefl/)"
fi
