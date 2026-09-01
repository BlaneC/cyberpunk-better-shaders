#!/usr/bin/env bash
# Build + park the Beer-Lambert coloured-transmission ladder (handoff/86).
# Rides the Phase 0.5 refraction rung (handoff/76): every rung here is built ON
# swaps.refract.eta15/, so selecting one selects "eta15 + absorption".
#
#   swaps.refract.eta15-absorb/    luma-held chroma-only, 4.50 mm glass / m
#   swaps.refract.eta15-absorbhi/  luma-held chroma-only, 11.25 mm glass / m
#   swaps.refract.eta15-absorbp/   PHYSICAL Beer-Lambert, 4.50 mm glass / m
#
# --install parks them at $INSTALL_DIR/refract.set/<level>/, which is all
# sync_settings.sh needs: its refract block accepts any refract.set/<level>
# directory by name (it only special-cases "off").
#
# Nothing here touches swaps.refract.{off,eta15,eta20} or any other family.
set -euo pipefail
cd "$(dirname "$0")/.."
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/lib/callisto}"
MOD=ee6d252e090adc74.rgs_reflection_transparent_main
BASE=swaps.refract.eta15
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
LEVELS=(eta15-absorb eta15-absorbhi eta15-absorbp)
fail() { echo "BUILD FAILED: $*" >&2; exit 1; }

[[ -f "$BASE/$MOD.spvasm" ]] || fail "no $BASE -- run ./dev/build_refract.sh first"

# ---- 0. negative control: the patcher must find 0 sites on a non-refract base
for neg in swaps.refract.off swaps.ptrefl; do
    if python3 dev/patch_refract_absorb.py --mode luma --mm-per-m 4.5 \
         --src "$neg/$MOD.spvasm" --out "$TMP/neg" >"$TMP/neg.log" 2>&1; then
        fail "negative control: patcher SUCCEEDED on $neg -- it must find 0 sites"
    fi
    grep -q "0 sites: Phase 0.5 marker" "$TMP/neg.log" \
        || fail "negative control on $neg died for the wrong reason: $(cat "$TMP/neg.log")"
    echo "  negative control OK: 0 sites on $neg"
done

# ---- 1. knob-0 rebuild must be BYTE-IDENTICAL to the eta15 base -------------
for m in physical luma; do
    python3 dev/patch_refract_absorb.py --mode "$m" --mm-per-m 0 --out "$TMP/zero-$m" >/dev/null
    cmp -s "$TMP/zero-$m/$MOD.spv" "$BASE/$MOD.spv" \
        || fail "sigma=0 ($m) is NOT byte-identical to $BASE -- the patcher is \
emitting constants nothing consumes (GOTCHAS: 'a byte diff is not coverage')"
    echo "  sigma=0 ($m) rebuild: byte-identical to $BASE"
done

# ---- 2. the shipped rungs ---------------------------------------------------
python3 dev/patch_refract_absorb.py --mode luma     --mm-per-m 4.50  --out swaps.refract.eta15-absorb
python3 dev/patch_refract_absorb.py --mode luma     --mm-per-m 11.25 --out swaps.refract.eta15-absorbhi
python3 dev/patch_refract_absorb.py --mode physical --mm-per-m 4.50  --out swaps.refract.eta15-absorbp

# ---- 3. enforced site coverage ON THE SHIPPED BYTES -------------------------
# The four vanilla consumers of the radiance triple must no longer name it.
# (These two strings exist in the base and must be gone from every rung.)
grep -q "NMax %273 %float_9_99999997en07"          "$BASE/$MOD.spvasm" || fail "coverage probe A absent from base"
grep -q "OpPhi %float %277 %2827 %277 %2828"       "$BASE/$MOD.spvasm" || fail "coverage probe B absent from base"
for lvl in "${LEVELS[@]}"; do
    d="swaps.refract.$lvl"
    ! grep -q "NMax %273 %float_9_99999997en07"    "$d/$MOD.spvasm" || fail "$lvl: volume-probe use of %273 NOT rewritten"
    ! grep -q "OpPhi %float %277 %2827 %277 %2828" "$d/$MOD.spvasm" || fail "$lvl: frontier phi use of %277 NOT rewritten"
    ! grep -q "OpPhi %float %275 %2827 %275 %2828" "$d/$MOD.spvasm" || fail "$lvl: frontier phi use of %275 NOT rewritten"
    ! grep -q "OpPhi %float %273 %2827 %272 %2828" "$d/$MOD.spvasm" || fail "$lvl: frontier phi use of %273 NOT rewritten"
    # the miss guard must be present exactly three times (one per channel)
    n=$(grep -c "OpSelect %float %268 %27[357] " "$d/$MOD.spvasm" || true)
    [[ "$n" -eq 3 ]] || fail "$lvl: expected 3 miss-identity selects, found $n"
    spirv-val "$d/$MOD.spv"
done

# ---- 4. every rung differs from the base and from each other ----------------
for lvl in "${LEVELS[@]}"; do
    cmp -s "$BASE/$MOD.spv" "swaps.refract.$lvl/$MOD.spv" && fail "$lvl == $BASE ?!"
done
cmp -s "swaps.refract.eta15-absorb/$MOD.spv" "swaps.refract.eta15-absorbhi/$MOD.spv" && fail "absorb == absorbhi ?!"
cmp -s "swaps.refract.eta15-absorb/$MOD.spv" "swaps.refract.eta15-absorbp/$MOD.spv"  && fail "absorb == absorbp ?!"

# ---- 5. the standing rungs must be untouched --------------------------------
for lvl in off eta15 eta20; do
    [[ -f "swaps.refract.$lvl/$MOD.spv" ]] || fail "standing rung $lvl vanished"
done

# ---- 6. manifests -----------------------------------------------------------
for lvl in "${LEVELS[@]}"; do
    d="swaps.refract.$lvl"
    sha="$(sha256sum "$d/$MOD.spv" | cut -c1-16)"
    case "$lvl" in
      eta15-absorb)   note="eta15 + Beer-Lambert, LUMA-HELD chroma-only, 4.50mm float-glass/m, dmax=40m" ;;
      eta15-absorbhi) note="eta15 + Beer-Lambert, LUMA-HELD chroma-only, 11.25mm float-glass/m, dmax=40m" ;;
      eta15-absorbp)  note="eta15 + Beer-Lambert, PHYSICAL (energy drops), 4.50mm float-glass/m, dmax=40m" ;;
    esac
    printf 'ptrefl refract=%s %s sha=%s built=%s\n# Coloured transmission through the refracted segment (handoff/86); rides swaps.ptrefl via refract.set, materialized by sync_settings.sh\n' \
        "$lvl" "$note" "$sha" "$(date -Is)" > "$d/MANIFEST.txt"
    echo "  $lvl: $sha"
done

if [[ "${1:-}" == "--install" ]]; then
    for lvl in "${LEVELS[@]}"; do
        mkdir -p "$INSTALL_DIR/refract.set/$lvl"
        cp -pf "swaps.refract.$lvl/$MOD.spv" "swaps.refract.$lvl/MANIFEST.txt" \
               "$INSTALL_DIR/refract.set/$lvl/"
    done
    echo "installed -> $INSTALL_DIR/refract.set/{${LEVELS[*]}}"
fi
echo "ALL CHECKS PASSED"
