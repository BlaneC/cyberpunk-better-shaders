#!/usr/bin/env bash
# Build the unconditional-tint hunt net for the indirect-light evaluator
# families named in handoff/15-RENDER-GRAPH.md 2.
#
# Why this exists: the palette tier needs a material-class read, which is what
# made 149 of 178 dispatched modules unpatchable.  These modules are
# tile-classified permutations -- dispatch IS the gate -- so an unconditional
# output multiply paints exactly the tiles the module was dispatched for.
#
#   ./dev/build_tintnet.sh          # build every candidate into swaps.tintall/
#   ./dev/build_tintnet.sh B        # family B only (GI / ReSTIR)
#
# Then install with dev/bisect_tint.sh.
set -uo pipefail   # not -e: a per-module failure must not abort the sweep
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${CALLISTO_DUMP:-$HOME/callisto_dump}"
OUT="$MOD_DIR/swaps.tintall"
TINT="${TINT:-1.0,0.25,0.25}"      # red: survives any nonzero output

# Family B -- GI / ReSTIR reservoirs, 1280x720 (writes 0x15b1ed30/0x15b1d030/0x15b14c00)
FAM_B=(1ecc0c405786e1e3 23bb4979d6edc2fd 66d2f831627dc8cd 9112430b0c381450
       99bb7c2698997b2a afe73b89b1f04f6d ce2a6197bd23b33c d48dd37d800deb46)
# Family C -- 1280x720 pair (writes 0x15b434a0/0x15b3faa0)
FAM_C=(1921a49565aad925 705c012dd38f55d9 a5f4a903683893b4 f209f068dc4a55bc
       f9a666709dbbfbbe)
# Family D -- quarter-res 640x360 (writes 0x19bad070)
FAM_D=(204eaf5b16ecff04 384aa95441751429 5f0de0f55d67c607 6e91dc5e05af59b3
       84ea63ad0fdedb95 85119cfcee1a8646 9731d633b09c6b01 ac38cf69e12c1c15
       cbaeaa8ce898b20d)

case "${1:-all}" in
    B)   mods=("${FAM_B[@]}") ;;
    C)   mods=("${FAM_C[@]}") ;;
    D)   mods=("${FAM_D[@]}") ;;
    all) mods=("${FAM_B[@]}" "${FAM_C[@]}" "${FAM_D[@]}") ;;
    *)   echo "usage: $0 B|C|D|all" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
ok=0; fail=0
for id in "${mods[@]}"; do
    spv="$DUMP/$id.dxil.spv"
    if [[ ! -f $spv ]]; then
        echo "MISS  $id  (not in $DUMP)"; fail=$((fail+1)); continue
    fi
    asm="$OUT/$id.dxil.spvasm.src"
    spirv-dis "$spv" -o "$asm" 2>/dev/null || { echo "DIS   $id"; fail=$((fail+1)); continue; }
    # the patcher names its output after the module's dxil ident, which is
    # already "<id>.dxil" -- so it lands as <id>.dxil.spv with no renaming.
    if python3 "$MOD_DIR/dev/patch_compute_hair.py" "$asm" --tier hunttint \
           --tint "$TINT" --outdir "$OUT" > "$OUT/$id.tint.json" 2>"$OUT/$id.err"; then
        rm -f "$OUT/$id.err"
        n=$(python3 -c "import json;d=json.load(open('$OUT/$id.tint.json'));print(len(d[0]['tint']['writes']))" 2>/dev/null || echo '?')
        echo "OK    $id  ${n} write(s)"
        ok=$((ok+1))
    else
        echo "FAIL  $id  $(sed -n 's/.*error: //p' "$OUT/$id.err" | head -1)"
        fail=$((fail+1))
    fi
    rm -f "$asm"
done
echo "--- tint net: $ok built, $fail failed -> $OUT"
