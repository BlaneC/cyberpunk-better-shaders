#!/usr/bin/env bash
# carglint DRIVER selftest -- `94` sec 6.2 axis 11, on real hardware.
#
# dev/verify_carglint.py already proves STATICALLY that the shipped bytes
# implement dev/glint_model.py. This proves the remaining half: that a driver
# executing those bytes produces the model's numbers, bit for bit.
#
#   1. dev/carglint_kernel.py generates a compute kernel by CALLING
#      patch_carglint.emit_module_level / emit_arm -- the same emitters that
#      patch the raygens. There is no second copy of the arithmetic to drift.
#   2. dev/carglint_probe.c creates a device, two storage buffers and a compute
#      pipeline, and dispatches N samples.
#   3. The module it hands to vkCreateShaderModule is a PLACEHOLDER that stores
#      -1.0. The layer swaps the real kernel in from swaps.carglinttest/, which
#      is patch_rayq.sh case E's route. If the swap does not happen the readback
#      is all -1.0 and every sample mismatches -- the swap is measured, not
#      assumed.
#   4. Each parked rung's real ~300 KB patched rgs_reference_main is then handed
#      to vkCreateShaderModule, so the driver's front end sees the actual
#      shipped bytes and not just a 3 KB toy.
#
# Loader note (patch_rayq.sh sec "Loader note", repeated because it silently
# invalidates everything): the loader dedupes IMPLICIT layers by NAME, so a
# VK_ADD_LAYER_PATH pointing at a fresh build still binds the INSTALLED .so
# unless the manifest renames the layer. This one is VK_LAYER_CALLISTO_carglint.
#
#   ./dev/carglint_selftest.sh            # 65536 samples, default knobs
#   ./dev/carglint_selftest.sh --n 262144
set -uo pipefail
MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
N=65536
while (($#)); do case "$1" in
    --n) N="$2"; shift 2;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    *) echo "unknown: $1" >&2; exit 2;;
esac; done

for t in spirv-as spirv-val gcc python3; do
    command -v "$t" >/dev/null || { echo "need $t" >&2; exit 1; }
done
[[ -f /usr/include/vulkan/vulkan.h ]] || { echo "need Vulkan headers" >&2; exit 1; }

w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT
ok=0; bad=0
_chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
         else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
_b()  { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
_bn() { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }

( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
    echo "layer build failed" >&2; cat "$w/build.log" >&2; exit 1; }
mkdir -p "$w/lay/swaps.carglinttest"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/carglinttest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_carglint",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the carglint driver test"
    }
}
EOJ

echo "carglint driver selftest  ($N samples, layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
echo
python3 "$MOD_DIR/dev/carglint_kernel.py" --emit-null "$w/n.spvasm" \
        --inputs "$w/in.bin" --n "$N" || exit 1
spirv-as --target-env vulkan1.4 "$w/n.spvasm" -o "$w/n.spv" || exit 1
_chk "the placeholder validates at vulkan1.4"      "$(_b spirv-val "$w/n.spv")"
gcc -O1 -o "$w/probe" "$MOD_DIR/dev/carglint_probe.c" -lvulkan 2>"$w/cc.err" || {
    echo "could not build the probe (need libvulkan-dev):" >&2
    sed -n '1,5p' "$w/cc.err" >&2; exit 1; }

# every parked rung's real raygen, create-only
REALS=()
# The stacked rung is the biggest module in the family -- earglow-rq3's three
# ray queries AND the glint splice in the same 10 raygens -- so it is the one
# most likely to hit a driver front-end limit. It is checked FIRST.
for r in gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense \
         carglint carglint-dense carglint-sparse carglint-cell carglint-ctl; do
    f="$(ls "$MOD_DIR/swaps.$r"/*.rgs_reference_main.spv 2>/dev/null | head -1)"
    [[ -z "$f" ]] && f="$(ls "$DEST/skin.set/$r"/*.rgs_reference_main.spv 2>/dev/null | head -1)"
    [[ -n "$f" ]] && REALS+=("$f")
done

_run() { # _run <log> <env...> -- placeholder in, real kernel served
    local log="$1"; shift
    env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_carglint \
        CALLISTO_OVERLAYS=carglinttest CALLISTO_LOG="$log" \
        "$@" "$w/probe" "$w/n.spv" "$w/in.bin" "$w/out.bin" "$N" \
        ${REALS+"${REALS[@]}"} >"$log.out" 2>&1
    return $?
}
_dispatch() { # _dispatch <store> [knob...] -- build, serve, run; leaves out.bin
    local st="$1"; shift
    local KA=(); local k; for k in "$@"; do KA+=(--knob "$k"); done
    python3 "$MOD_DIR/dev/carglint_kernel.py" --emit "$w/k_$st.spvasm" \
            --store "$st" ${KA+"${KA[@]}"} >"$w/emit_$st.txt" 2>&1 || return 1
    spirv-as --target-env vulkan1.4 "$w/k_$st.spvasm" -o "$w/k_$st.spv" || return 1
    spirv-val "$w/k_$st.spv" || return 1
    cp -pf "$w/k_$st.spv" "$w/lay/swaps.carglinttest/cccccccccccccccc.carglint.spv"
    _run "$w/$st.log"
}

# ---- 1. the feature, staged: where must the driver be BIT-exact? ----------
# `s`, `kden` and `pc` set the SCALE and the DENSITY of the sparkle. If a driver
# is free there, the look is hardware-dependent and the rung is not shippable.
for st in s kden pc; do
    _dispatch "$st"; rc=$?
    _chk "dispatch stores $st"  "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
    python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/out.bin" \
            --store "$st" >"$w/chk_$st.txt" 2>&1
    rc=$?; sed 's/^/  /' "$w/chk_$st.txt"
    _chk "$st is BIT-exact against glint_model.py" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
done

# ---- 2. glint itself ------------------------------------------------------
_dispatch glint; r_on=$?
_chk "the probe exits 0"                          "$([[ $r_on -eq 0 ]] && echo 1 || echo 0)"
_chk "the layer SERVED the kernel (swap HIT)"     "$(_b grep -q '"swap":"HIT"' "$w/glint.log")"
_chk "vkCreateShaderModule accepted it"           "$(_b grep -q 'vkCreateShaderModule(kernel.*-> 0' "$w/glint.log.out")"
_chk "the compute pipeline compiled"              "$(_b grep -q 'vkCreateComputePipelines -> 0' "$w/glint.log.out")"
_chk "$N samples dispatched"                      "$(_b grep -q "dispatched $N samples" "$w/glint.log.out")"
if ((${#REALS[@]})); then
    _chk "${#REALS[@]} real ~300 KB patched raygens accepted" \
         "$([[ $(grep -c 'real raygen .*-> 0' "$w/glint.log.out") -eq ${#REALS[@]} ]] && echo 1 || echo 0)"
else
    echo "  ....  no parked rung found; run ./dev/build_carglint.sh"
fi
cp -pf "$w/out.bin" "$w/glint.bin"
python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/glint.bin" >"$w/chk.txt" 2>&1
rc=$?; sed 's/^/  /' "$w/chk.txt"
_chk "the driver agrees with glint_model.py on glint" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"

# ---- 3. non-vacuity: the check must REJECT things that are wrong ----------
_run "$w/off.log" env CALLISTO_SWAP_DISABLE=1 >/dev/null 2>&1
python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/out.bin" >"$w/chk2.txt" 2>&1
_chk "REJECTS the unswapped placeholder (-1.0 everywhere)" \
     "$(_bn grep -q '^OK:' "$w/chk2.txt")"
_chk "... which really was the placeholder, not a swap" \
     "$(_bn grep -q '"swap":"HIT"' "$w/off.log")"
_dispatch glint nu0=6e5 >/dev/null 2>&1
python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/out.bin" >"$w/chk3.txt" 2>&1
_chk "REJECTS a nu0=6e5 kernel read with the default knobs" \
     "$(_bn grep -q '^OK:' "$w/chk3.txt")"
python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/out.bin" --knob nu0=6e5 >"$w/chk4.txt" 2>&1
_chk "... but ACCEPTS it read as nu0=6e5 (not an always-fail)" \
     "$(_b grep -q '^OK:' "$w/chk4.txt")"
_dispatch s cell=0.016 >/dev/null 2>&1
python3 "$MOD_DIR/dev/carglint_kernel.py" --check "$w/in.bin" "$w/out.bin" --store s >"$w/chk5.txt" 2>&1
_chk "REJECTS a cell=0.016 ladder read as cell=0.008" \
     "$(_bn grep -q '^OK:' "$w/chk5.txt")"
# and the k_glint=0 CONTROL must come back exactly 1.0 everywhere -- the same
# null `94` sec 6.1 demands of the shipped control rung, measured on silicon.
_dispatch glint k_glint=0 >/dev/null 2>&1
python3 - "$w/out.bin" <<'EOP'
import sys, numpy as np
d = np.frombuffer(open(sys.argv[1], 'rb').read(), dtype=np.float32)
bad = int(np.count_nonzero(d.view(np.uint32) != np.float32(1.0).view(np.uint32)))
print(f"  k_glint=0 on the driver: {d.size - bad} / {d.size} exactly 1.0")
sys.exit(1 if bad else 0)
EOP
_chk "k_glint=0 returns glint == 1.0 on EVERY sample" "$([[ $? -eq 0 ]] && echo 1 || echo 0)"

echo
grep -m1 "^device:" "$w/glint.log.out"
echo "$ok passed, $bad failed"
if ((bad)); then cp -r "$w" "${w}.keep"; echo "logs kept: ${w}.keep" >&2; exit 1; fi
cat <<'EOM'

What this does NOT prove: that the game's raygen ever REACHES the splice, or
that the world offset is the right one. `98` sec 15 answered the second; only
the -glintcell rung on a real frame can answer it again here.
EOM
