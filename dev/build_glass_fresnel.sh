#!/usr/bin/env bash
# Build + park the glass-interface Fresnel ladder (handoff/91).
#
# These rungs REVERT Phase 0.5's bent ray (76) and instead weight the vanilla
# mirror reflection by the dielectric F(theta) of the air->glass interface.
# Rationale in dev/patch_glass_fresnel.py's docstring: on a flat pane the two
# interfaces cancel, so the raster alpha-blend see-through already IS the
# correct transmitted image and a traced transmission can only duplicate it.
# The entire physically-real angle-dependent effect is the reflection ramping
# to a mirror, which is exactly what F gives.
#
#   fres          exact unpolarized Fresnel, n=1.5     <- THE rung
#   fres-schlick  Schlick F0=0.04, same n              <- comparison, not argument
#   fres75        exact, lerp(1,F,0.75)                <- softer, if F reads as
#                                                         "the reflection vanished"
#   fres-null     radiance := 0                        <- DIAGNOSTIC: add or replace?
#   fres-flat     radiance := 8.0 constant             <- DIAGNOSTIC: does the
#                                                         consumer apply its OWN F?
#
# The rungs RIDE swaps.ptrefl/ exactly as the refract ladder does (that overlay
# owns this module id, first-file-wins).  sync_settings.sh's refract= key takes
# any refract.set/<level> by name (86 par5), so no init.lua change is needed to
# serve them -- but the CET selector will still read off/eta15/eta20, so trust
# status.txt's want_refract and the journal MANIFEST echo, not the panel.
#
# --install parks the ladder at $INSTALL_DIR/refract.set/<level>/.
set -euo pipefail
cd "$(dirname "$0")/.."
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/lib/callisto}"
MOD=ee6d252e090adc74.rgs_reflection_transparent_main
SRC="swaps.ptrefl/$MOD.spvasm"
LEVELS=(fres fres-schlick fres75 fres-null fres-flat)

P() { python3 dev/patch_glass_fresnel.py "$@"; }

echo "== building"
P --fresnel exact   --n 1.5 --strength 1.00 --out swaps.refract.fres
P --fresnel schlick --n 1.5 --strength 1.00 --out swaps.refract.fres-schlick
P --fresnel exact   --n 1.5 --strength 0.75 --out swaps.refract.fres75
P --mode null                               --out swaps.refract.fres-null
P --mode flat --flat-value 8.0              --out swaps.refract.fres-flat

# --- check 1: knob-0 rebuild must be byte-identical to the source ----------
# Guards the GOTCHAS trap "constants nothing consumes": at strength 0 the
# patcher must emit no constants, no body and no rewrites.
echo "== check 1: knob-0 byte-inert"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
P --strength 0 --out "$tmp/zero" >/dev/null
cmp "swaps.ptrefl/$MOD.spv" "$tmp/zero/$MOD.spv"
echo "  strength=0 rebuild == plain ptrefl: OK"

# --- check 2: the negative control -----------------------------------------
# Fresnel weights the MIRROR term, so the patcher must refuse a Phase 0.5 rung.
echo "== check 2: refuses a refracted source"
if [[ -f "swaps.refract.eta15/$MOD.spvasm" ]]; then
    if P --src "swaps.refract.eta15/$MOD.spvasm" --out "$tmp/neg" >/dev/null 2>&1; then
        echo "  FAIL: patcher accepted a Phase 0.5 rung"; exit 1
    fi
    echo "  refused swaps.refract.eta15: OK"
else
    echo "  (swaps.refract.eta15 absent -- run dev/build_refract.sh first to test)"
fi

# --- check 3: every rung differs from plain ptrefl and from every other -----
echo "== check 3: all rungs distinct"
for l in "${LEVELS[@]}"; do
    cmp -s "swaps.ptrefl/$MOD.spv" "swaps.refract.$l/$MOD.spv" && \
        { echo "  FAIL: $l == plain ptrefl"; exit 1; }
done
for a in "${LEVELS[@]}"; do for b in "${LEVELS[@]}"; do
    [[ "$a" < "$b" ]] || continue
    cmp -s "swaps.refract.$a/$MOD.spv" "swaps.refract.$b/$MOD.spv" && \
        { echo "  FAIL: $a == $b"; exit 1; }
done; done
echo "  all $(( ${#LEVELS[@]} )) rungs distinct: OK"

# --- check 4: alpha is untouched in every rung -----------------------------
# Alpha is the transparent-gate DEPTH (20 par1), not a coverage flag, and the
# consumer plausibly tests it.  %270 must still reach the OpImageWrite.
echo "== check 4: alpha (%270) untouched"
for l in "${LEVELS[@]}"; do
    grep -q '^\s*%295 = OpCompositeConstruct %v4float %286 %288 %289 %270$' \
        "swaps.refract.$l/$MOD.spvasm" || { echo "  FAIL: $l alpha changed"; exit 1; }
done
echo "  %295 = (..., %270) intact in every rung: OK"

# --- check 5: the standing rungs are byte-identical to what 76 recorded -----
echo "== check 5: standing refract rungs untouched"
for pair in "off:ac2cd8f7d550fe93" "eta15:8c88926a273ae541" "eta20:c96eaef809c8a734"; do
    l="${pair%%:*}"; want="${pair##*:}"
    f="swaps.refract.$l/$MOD.spv"
    [[ -f "$f" ]] || { echo "  ($l absent, skipped)"; continue; }
    got="$(sha256sum "$f" | cut -c1-16)"
    [[ "$got" == "$want" ]] || { echo "  FAIL: $l $got != $want"; exit 1; }
    echo "  $l $got: OK"
done

# --- manifests --------------------------------------------------------------
for l in "${LEVELS[@]}"; do
    d="swaps.refract.$l"
    spirv-val "$d/$MOD.spv"
    sha="$(sha256sum "$d/$MOD.spv" | cut -c1-16)"
    case "$l" in
      fres)         note="mirror reflection x exact unpolarized Fresnel, n=1.5" ;;
      fres-schlick) note="mirror reflection x Schlick F0=0.04, n=1.5" ;;
      fres75)       note="mirror reflection x lerp(1,F_exact,0.75), n=1.5" ;;
      fres-null)    note="DIAGNOSTIC radiance:=0 -- does the consumer add or replace?" ;;
      fres-flat)    note="DIAGNOSTIC radiance:=8.0 -- does the consumer apply its own Fresnel?" ;;
    esac
    printf 'ptrefl refract=%s %s sha=%s built=%s\n# Glass Fresnel (handoff/91); reverts 76 Phase 0.5; rides swaps.ptrefl, materialized by sync_settings.sh\n' \
        "$l" "$note" "$sha" "$(date -Is)" > "$d/MANIFEST.txt"
    echo "  $l: $sha"
done

if [[ "${1:-}" == "--install" ]]; then
    for l in "${LEVELS[@]}"; do
        mkdir -p "$INSTALL_DIR/refract.set/$l"
        cp -pf "swaps.refract.$l/$MOD.spv" "swaps.refract.$l/MANIFEST.txt" \
               "$INSTALL_DIR/refract.set/$l/"
    done
    echo "installed -> $INSTALL_DIR/refract.set/ (select with refract=fres|fres-schlick|fres75|fres-null|fres-flat)"
fi
