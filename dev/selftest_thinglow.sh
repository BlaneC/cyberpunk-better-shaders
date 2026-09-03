#!/usr/bin/env bash
# thinglow LAYER self-test -- the on-device half of handoff/105.
#
# ./dev/build_thinglow.sh gates the four rungs entirely offline. spirv-val is
# not a driver: it never lowers OpRayQueryGetIntersectionTKHR, and it does not
# care how many ray query objects are live at once. 101's self-test proved a
# driver compiles THREE. This rung STACKS three more into the same raygen, so
# the questions only a real Vulkan device can answer are:
#
#   1. does the layer still put VK_KHR_ray_query on the VkDevice when the
#      application never asked for it (vkd3d-proton never does)?
#   2. does the driver compile SIX live ray query objects in one raygen --
#      flags 517/545/517 twice, FOUR committed InstanceId getters, TWO
#      committed T getters, two OpIEqual and two Exp -- into an RT pipeline?
#      A driver that spills or serialises query objects turns the stack into
#      a register-pressure cliff, and "each half compiles" is not the claim.
#   3. do the REAL ~300 KB stacked raygens of all four rungs survive
#      vkCreateShaderModule when served THROUGH THE LAYER by the same
#      first-file-wins overlay path the game uses?
#   4. does the reject guard still fall through to the NEXT OVERLAY (not to
#      vanilla) when ray query is unavailable -- and does it fire on the
#      CONTROL too? It must: thinglow-ctl is byte-identical to the standing
#      default, which already carries 101's three queries. That is the
#      opposite of 101's case D and is the point: there is no ray-query-free
#      control in this family any more.
#
#   ./dev/selftest_thinglow.sh          # everything; no game involved
#
# NEW FILE on purpose: dev/selftest_earglow_rq.sh is 101's shipped gate and is
# not touched. Its VkDevice/RT-pipeline probe is EXTRACTED from it read-only
# rather than retyped, so the two files cannot drift into testing different
# devices; everything else here is written for 105.
#
# Loader note, inherited and worth repeating because getting it wrong makes
# every result a lie: the layer installs as an IMPLICIT layer and the loader
# dedupes implicit layers BY NAME, so VK_ADD_LAYER_PATH pointed at a fresh
# build still binds the INSTALLED .so. The manifest below therefore names the
# test copy VK_LAYER_CALLISTO_thinglowtest.
#
# Overlay fixtures are SYMLINKS to swaps.<rung>/, never copies: the bytes the
# driver is handed are literally the shipped bytes this repo just gated.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNGS=(thinglow-ctl thinglow-hit thinglow thinglow-hi)
LIVE=(thinglow-hit thinglow thinglow-hi)
for r in "${RUNGS[@]}"; do
    [[ -d "$MOD_DIR/swaps.$r" ]] || {
        echo "selftest: swaps.$r is missing -- run ./dev/build_thinglow.sh first" >&2
        exit 1; }
done

ok=0; bad=0; skip=0
chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
        else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
b()  { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
# Separate negated form on purpose: `b ! cmd` cannot work -- `!` is a shell
# keyword, not a command, so it resolves to "command not found" and returns 0
# for BOTH outcomes. That silent always-fail is what this form exists to stop.
bn() { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }

for t in spirv-as spirv-dis spirv-val gcc python3; do
    command -v "$t" >/dev/null || { echo "selftest: need $t" >&2; exit 1; }
done
[[ -f /usr/include/vulkan/vulkan.h ]] || {
    echo "selftest: need Vulkan headers (/usr/include/vulkan/vulkan.h)" >&2; exit 1; }

w="$(mktemp -d)" || exit 1
trap 'rm -rf "$w"' EXIT

( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
    echo "selftest: layer build failed" >&2; tail -5 "$w/build.log" >&2; exit 1; }
mkdir -p "$w/lay" "$w/lay/swaps.tgfb" "$w/stand"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/thinglowtest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_thinglowtest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the thinglow self-test"
    }
}
EOJ

# ------------------------------------------------------------------ fixtures
# The ten painted ids come from the shipped rungs themselves, not from a list
# typed here: a hardcoded list would keep passing after a rung stopped
# painting one of them. thinglow-ctl is the base, so "differs from the ctl" is
# exactly "this rung painted it".
mapfile -t IDS < <(cd "$MOD_DIR/swaps.thinglow" &&
    for f in *.rgs_reference_main.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.thinglow-ctl/$f" || echo "${f%%.*}"
    done | sort)
(( ${#IDS[@]} == 10 )) || { echo "selftest: expected 10 painted ids, got ${#IDS[@]}" >&2; exit 1; }
for r in "${LIVE[@]}"; do
    mapfile -t I2 < <(cd "$MOD_DIR/swaps.$r" &&
        for f in *.rgs_reference_main.spv; do
            cmp -s "$f" "$MOD_DIR/swaps.thinglow-ctl/$f" || echo "${f%%.*}"
        done | sort)
    [[ "${I2[*]}" == "${IDS[*]}" ]] || {
        echo "selftest: $r paints a different id set than thinglow" >&2; exit 1; }
done

# The synthetic SIX-query raygen: 101's triple and 105's triple in one entry
# point, with every operand the driver could constant-fold made dynamic off
# the launch id, so "it compiles" cannot be "it compiled nothing".
cat > "$w/tg.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
       %glsl = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "cccccccccccccccc.?thinglowtest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
               OpDecorate %accel DescriptorSet 0
               OpDecorate %accel Binding 0
               OpDecorate %out DescriptorSet 0
               OpDecorate %out Binding 1
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
      %float = OpTypeFloat 32
       %bool = OpTypeBool
     %v2uint = OpTypeVector %uint 2
     %v3uint = OpTypeVector %uint 3
    %v3float = OpTypeVector %float 3
    %v4float = OpTypeVector %float 4
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
%_ptr_Input_uint = OpTypePointer Input %uint
%_ptr_Function_float = OpTypePointer Function %float
        %lid = OpVariable %_ptr_Input_v3uint Input
         %as = OpTypeAccelerationStructureKHR
%_ptr_UniformConstant_as = OpTypePointer UniformConstant %as
      %accel = OpVariable %_ptr_UniformConstant_as UniformConstant
        %img = OpTypeImage %float 2D 0 0 0 2 Rgba32f
%_ptr_UniformConstant_img = OpTypePointer UniformConstant %img
        %out = OpVariable %_ptr_UniformConstant_img UniformConstant
         %rq = OpTypeRayQueryKHR
%_ptr_Function_rq = OpTypePointer Function %rq
     %uint_0 = OpConstant %uint 0
     %uint_1 = OpConstant %uint 1
     %uint_4 = OpConstant %uint 4
     %uint_8 = OpConstant %uint 8
    %uint_39 = OpConstant %uint 39
   %uint_517 = OpConstant %uint 517
   %uint_545 = OpConstant %uint 545
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
  %float_100 = OpConstant %float 100
   %float_n0 = OpConstant %float -0
%float_0_1 = OpConstant %float 0.100000001
%float_0_5 = OpConstant %float 0.5
%float_egtmin = OpConstant %float 0.00150000001
%float_egtmax = OpConstant %float 0.0179999992
%float_tgtmin = OpConstant %float 0.000299999992
%float_tgtmax = OpConstant %float 0.0250000004
%float_push = OpConstant %float 0.00100000005
%float_rate = OpConstant %float 500
   %float_eg = OpConstant %float 272.479553
%float_10000 = OpConstant %float 10000
      %coord = OpConstantComposite %v2uint %uint_0 %uint_0
     %v3zero = OpConstantComposite %v3float %float_0 %float_0 %float_0
       %main = OpFunction %void None %3
          %5 = OpLabel
        %qa1 = OpVariable %_ptr_Function_rq Function
        %qb1 = OpVariable %_ptr_Function_rq Function
        %qc1 = OpVariable %_ptr_Function_rq Function
        %qa2 = OpVariable %_ptr_Function_rq Function
        %qb2 = OpVariable %_ptr_Function_rq Function
        %qc2 = OpVariable %_ptr_Function_rq Function
        %gr0 = OpVariable %_ptr_Function_float Function
        %gg0 = OpVariable %_ptr_Function_float Function
        %gb0 = OpVariable %_ptr_Function_float Function
               OpStore %gr0 %float_n0
               OpStore %gg0 %float_n0
               OpStore %gb0 %float_n0
         %pl = OpAccessChain %_ptr_Input_uint %lid %uint_0
         %lx = OpLoad %uint %pl
         %fv = OpConvertUToF %float %lx
        %cls = OpBitwiseAnd %uint %lx %uint_8
       %ncl1 = OpINotEqual %bool %cls %uint_1
       %ncl4 = OpINotEqual %bool %cls %uint_4
       %ncl8 = OpINotEqual %bool %cls %uint_8
        %met = OpFMul %float %fv %float_0_1
       %nmet = OpFOrdLessThan %bool %met %float_0_1
       %nrgh = OpFOrdGreaterThan %bool %fv %float_0_5
         %a1 = OpLogicalAnd %bool %ncl1 %ncl4
         %a2 = OpLogicalAnd %bool %a1 %ncl8
         %a3 = OpLogicalAnd %bool %a2 %nmet
       %gate = OpLogicalAnd %bool %a3 %nrgh
       %mask = OpSelect %uint %gate %uint_39 %uint_0
       %orig = OpCompositeConstruct %v3float %fv %fv %fv
        %sun = OpCompositeConstruct %v3float %float_0 %float_1 %fv
        %vue = OpCompositeConstruct %v3float %fv %float_0 %float_1
          %a = OpLoad %as %accel
               OpRayQueryInitializeKHR %qa1 %a %uint_517 %mask %v3zero %float_egtmin %vue %float_egtmax
       %pra1 = OpRayQueryProceedKHR %bool %qa1
       %tya1 = OpRayQueryGetIntersectionTypeKHR %uint %qa1 %uint_1
       %hta1 = OpINotEqual %bool %tya1 %uint_0
       %ida1 = OpRayQueryGetIntersectionInstanceIdKHR %uint %qa1 %uint_1
               OpRayQueryInitializeKHR %qb1 %a %uint_545 %mask %orig %float_egtmin %sun %float_egtmax
       %prb1 = OpRayQueryProceedKHR %bool %qb1
       %tyb1 = OpRayQueryGetIntersectionTypeKHR %uint %qb1 %uint_1
       %htb1 = OpINotEqual %bool %tyb1 %uint_0
       %tqb1 = OpRayQueryGetIntersectionTKHR %float %qb1 %uint_1
       %tub1 = OpSelect %float %htb1 %tqb1 %float_egtmax
       %idb1 = OpRayQueryGetIntersectionInstanceIdKHR %uint %qb1 %uint_1
       %sam1 = OpIEqual %bool %ida1 %idb1
       %tp1 = OpFAdd %float %tub1 %float_push
       %of1 = OpVectorTimesScalar %v3float %sun %tp1
       %og1 = OpFAdd %v3float %orig %of1
               OpRayQueryInitializeKHR %qc1 %a %uint_517 %mask %og1 %float_push %sun %float_10000
       %prc1 = OpRayQueryProceedKHR %bool %qc1
       %tyc1 = OpRayQueryGetIntersectionTypeKHR %uint %qc1 %uint_1
       %htc1 = OpINotEqual %bool %tyc1 %uint_0
       %vic1 = OpLogicalNot %bool %htc1
       %bo1 = OpLogicalAnd %bool %hta1 %htb1
       %mt1 = OpLogicalAnd %bool %bo1 %sam1
       %ok1 = OpLogicalAnd %bool %mt1 %vic1
       %kg1 = OpSelect %float %ok1 %float_0_5 %float_n0
       %e11 = OpFMul %float %tub1 %float_eg
       %e21 = OpFNegate %float %e11
       %tr1 = OpExtInst %float %glsl Exp %e21
       %kw1 = OpFMul %float %kg1 %tr1
               OpRayQueryInitializeKHR %qa2 %a %uint_517 %mask %v3zero %float_tgtmin %vue %float_tgtmax
       %pra2 = OpRayQueryProceedKHR %bool %qa2
       %tya2 = OpRayQueryGetIntersectionTypeKHR %uint %qa2 %uint_1
       %hta2 = OpINotEqual %bool %tya2 %uint_0
       %ida2 = OpRayQueryGetIntersectionInstanceIdKHR %uint %qa2 %uint_1
               OpRayQueryInitializeKHR %qb2 %a %uint_545 %mask %orig %float_tgtmin %sun %float_tgtmax
       %prb2 = OpRayQueryProceedKHR %bool %qb2
       %tyb2 = OpRayQueryGetIntersectionTypeKHR %uint %qb2 %uint_1
       %htb2 = OpINotEqual %bool %tyb2 %uint_0
       %tqb2 = OpRayQueryGetIntersectionTKHR %float %qb2 %uint_1
       %tub2 = OpSelect %float %htb2 %tqb2 %float_tgtmax
       %idb2 = OpRayQueryGetIntersectionInstanceIdKHR %uint %qb2 %uint_1
       %sam2 = OpIEqual %bool %ida2 %idb2
       %tp2 = OpFAdd %float %tub2 %float_push
       %of2 = OpVectorTimesScalar %v3float %sun %tp2
       %og2 = OpFAdd %v3float %orig %of2
               OpRayQueryInitializeKHR %qc2 %a %uint_517 %mask %og2 %float_push %sun %float_10000
       %prc2 = OpRayQueryProceedKHR %bool %qc2
       %tyc2 = OpRayQueryGetIntersectionTypeKHR %uint %qc2 %uint_1
       %htc2 = OpINotEqual %bool %tyc2 %uint_0
       %vic2 = OpLogicalNot %bool %htc2
       %bo2 = OpLogicalAnd %bool %hta2 %htb2
       %mt2 = OpLogicalAnd %bool %bo2 %sam2
       %ok2 = OpLogicalAnd %bool %mt2 %vic2
       %kg2 = OpSelect %float %ok2 %float_0_5 %float_n0
       %e12 = OpFMul %float %tub2 %float_rate
       %e22 = OpFNegate %float %e12
       %tr2 = OpExtInst %float %glsl Exp %e22
       %kw2 = OpFMul %float %kg2 %tr2
        %sqr = OpFMul %float %fv %fv
        %m1r = OpFMul %float %kw2 %sqr
        %m2r = OpFMul %float %m1r %float_1
        %m3r = OpExtInst %float %glsl NMin %m2r %float_100
        %sqg = OpFMul %float %fv %fv
        %m1g = OpFMul %float %kw2 %sqg
        %m2g = OpFMul %float %m1g %float_1
        %m3g = OpExtInst %float %glsl NMin %m2g %float_100
        %sqb = OpFMul %float %fv %fv
        %m1b = OpFMul %float %kw2 %sqb
        %m2b = OpFMul %float %m1b %float_1
        %m3b = OpExtInst %float %glsl NMin %m2b %float_100
        %lr = OpLoad %float %gr0
        %sr = OpFAdd %float %lr %m3r
              OpStore %gr0 %sr
        %lg = OpLoad %float %gg0
        %sg = OpFAdd %float %lg %m3g
              OpStore %gg0 %sg
        %lb = OpLoad %float %gb0
        %sb = OpFAdd %float %lb %m3b
              OpStore %gb0 %sb
        %fr0 = OpLoad %float %gr0
        %fg0 = OpLoad %float %gg0
        %fb0 = OpLoad %float %gb0
        %er = OpFAdd %float %kw1 %fr0
        %eg1 = OpFAdd %float %kw1 %fg0
        %eb = OpFAdd %float %kw1 %fb0
        %tex = OpCompositeConstruct %v4float %er %eg1 %eb %float_1
         %im = OpLoad %img %out
               OpImageWrite %im %coord %tex
               OpReturn
               OpFunctionEnd
EOA
spirv-as --target-env spv1.4 "$w/tg.spvasm" -o "$w/tg.spv" 2>"$w/as.err" || {
    echo "selftest: the synthetic module does not assemble" >&2
    sed -n '1,5p' "$w/as.err" >&2; exit 1; }
spirv-val --target-env vulkan1.4 "$w/tg.spv" || {
    echo "selftest: the synthetic module does not validate" >&2; exit 1; }

# One stand-in raygen per painted id -- what the "application" (vkd3d-proton)
# creates. It carries only the dxil identity string; the layer replaces its
# bytes with the rung's real ~300 KB module. Each also gets a byte-distinct
# fallback twin in swaps.tgfb/ so a reject can be seen to land on the NEXT
# OVERLAY rather than on vanilla.
python3 - "$w" "${IDS[@]}" <<'PYGEN'
import os, subprocess, sys
w, ids = sys.argv[1], sys.argv[2:]
TMPL = '''               OpCapability RayTracingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid
        %str = OpString "HASH.?rgs_reference_main@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
     %v3uint = OpTypeVector %uint 3
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
        %lid = OpVariable %_ptr_Input_v3uint Input
     %uint_0 = OpConstant %uint 0
  %uint_mark = OpConstant %uint MARK
%_ptr_Input_uint = OpTypePointer Input %uint
       %main = OpFunction %void None %3
          %5 = OpLabel
          %p = OpAccessChain %_ptr_Input_uint %lid %uint_0
          %v = OpLoad %uint %p
          %h = OpBitwiseAnd %uint %v %uint_mark
               OpReturn
               OpFunctionEnd
'''
for h in ids:
    for tag, mark, out in (('stand', 7, os.path.join(w, 'stand', h + '.spv')),
                           ('fb', 13, os.path.join(w, 'lay', 'swaps.tgfb',
                                                   h + '.rgs_reference_main.spv'))):
        a = out + '.spvasm'
        open(a, 'w').write(TMPL.replace('HASH', h).replace('MARK', str(mark)))
        subprocess.run(['spirv-as', '--target-env', 'spv1.4', a, '-o', out],
                       check=True)
        os.remove(a)
PYGEN

# ---------------------------------------------------------------------- probe
# EXTRACTED, not retyped, from 101's self-test: same VkDevice, same extension
# list, same RT pipeline. Read-only -- this script never writes that file.
SRC_ST="$MOD_DIR/dev/selftest_earglow_rq.sh"
[[ -f "$SRC_ST" ]] || { echo "selftest: $SRC_ST is missing" >&2; exit 1; }
awk '/^cat > "\$w\/st\.c" <<.EOC.$/{f=1;next} /^EOC$/{f=0} f' "$SRC_ST" > "$w/st.c"
n_c=$(wc -l < "$w/st.c")
grep -q 'vkCreateRayTracingPipelinesKHR' "$w/st.c" && grep -q 'VK_KHR_RAY_QUERY_EXTENSION_NAME' "$w/st.c" \
    && (( n_c > 80 )) || {
    echo "selftest: the probe extracted from $SRC_ST is not the expected" \
         "source ($n_c lines) -- refusing to run a test whose device is unknown" >&2
    exit 1; }
gcc -O1 -o "$w/st" "$w/st.c" -lvulkan 2>"$w/cc.err" || {
    echo "selftest: could not build the probe (need libvulkan-dev):" >&2
    sed -n '1,5p' "$w/cc.err" >&2; exit 1; }

STAND=(); for h in "${IDS[@]}"; do STAND+=("$w/stand/$h.spv"); done

run() { # run <log> <overlays> [extra env ...]
    local log="$1" ov="$2"; shift 2
    env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_thinglowtest \
        CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" \
        "$@" "$w/st" "$w/tg.spv" "${STAND[@]}" >"$log.out" 2>&1
}
has() { grep -q -- "$2" "$1"; }

echo "thinglow layer self-test  (probe extracted from selftest_earglow_rq.sh, $n_c lines)"
echo "layer: $MOD_DIR/libVkLayer_callisto_spvswap.so"
echo "10 painted ids: ${IDS[*]}"
echo

# ---- case A: SIX live ray query objects on the driver ----------------------
# Non-vacuity first: assert the synthetic module really is the six-query
# shape, so "it compiled" cannot be "it compiled nothing".
n_init=$(spirv-dis "$w/tg.spv" | grep -c 'OpRayQueryInitializeKHR')
n_proc=$(spirv-dis "$w/tg.spv" | grep -c 'OpRayQueryProceedKHR')
n_iid=$(spirv-dis "$w/tg.spv" | grep -c 'OpRayQueryGetIntersectionInstanceIdKHR')
n_tg=$(spirv-dis "$w/tg.spv" | grep -c 'OpRayQueryGetIntersectionTKHR')
n_eq=$(spirv-dis "$w/tg.spv" | grep -c 'OpIEqual')
n_exp=$(spirv-dis "$w/tg.spv" | grep -c 'Exp ')
echo "case A -- SIX live ray query objects, four InstanceId getters, two committed T"
chk "the synthetic module is the stacked shape (6/6/4/2/2, got $n_init/$n_proc/$n_iid/$n_tg/$n_eq)" \
    "$([[ $n_init -eq 6 && $n_proc -eq 6 && $n_iid -eq 4 && $n_tg -eq 2 && $n_eq -eq 2 ]] && echo 1 || echo 0)"
chk "...and carries both transfers (2 OpExtInst Exp, got $n_exp)" \
    "$([[ $n_exp -eq 2 ]] && echo 1 || echo 0)"
ln -sfn "$MOD_DIR/swaps.thinglow" "$w/lay/swaps.tgrung"
run "$w/a.log" tgrung,tgfb env; ra=$?
sed -n '1,4p' "$w/a.log.out" | sed 's/^/    /'
chk "probe exits 0"                             "$([[ $ra -eq 0 ]] && echo 1 || echo 0)"
chk "layer enabled VK_KHR_ray_query"            "$(b has "$w/a.log" '"ev":"rayq","action":"enabled"')"
chk "synthetic six-query module accepted"       "$(b grep -q "tg.spv.*-> 0" "$w/a.log.out")"
chk "...and its RT PIPELINE links (the driver lowered ALL SIX queries)" \
    "$(b grep -q 'vkCreateRayTracingPipelinesKHR -> 0' "$w/a.log.out")"
chk "no rayq_reject"                            "$(bn has "$w/a.log" 'rayq_reject')"
chk "no rt_pipeline_failed"                     "$(bn has "$w/a.log" 'rt_pipeline_failed')"
echo

# ---- case B: the real ~300 KB stacked raygens, served through the layer ----
# The synthetic module above is under 3 KB and proves nothing about six
# queries spliced into 15 000 lines of shipped raygen.
echo "case B -- every rung's real raygens, served by the overlay, on the driver"
for rung in "${RUNGS[@]}"; do
    ln -sfn "$MOD_DIR/swaps.$rung" "$w/lay/swaps.tgrung"
    run "$w/b_$rung.log" tgrung,tgfb env; rb=$?
    chk "$rung: probe exits 0, no served module refused" \
        "$([[ $rb -eq 0 ]] && echo 1 || echo 0)"
    nhit=0
    for h in "${IDS[@]}"; do
        sz=$(stat -c%s "$MOD_DIR/swaps.$rung/$h.rgs_reference_main.spv")
        grep -q "\"ev\":\"swap_load\".*swaps.tgrung/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/b_$rung.log" \
          && grep -q "\"id\":\"$h.rgs_reference_main\".*\"swap\":\"HIT\",\"result\":0" "$w/b_$rung.log" \
          && nhit=$((nhit+1))
    done
    chk "$rung: 10 of 10 real raygens served at their shipped size and accepted (got $nhit)" \
        "$([[ $nhit -eq 10 ]] && echo 1 || echo 0)"
done
echo

# ---- case C: the reject guard falls through to the NEXT OVERLAY ------------
ln -sfn "$MOD_DIR/swaps.thinglow" "$w/lay/swaps.tgrung"
run "$w/c.log" tgrung,tgfb env CALLISTO_RAYQ_DISABLE=1; rc=$?
echo "case C -- CALLISTO_RAYQ_DISABLE=1: reject thinglow, fall through to swaps.tgfb/"
chk "probe still exits 0 (degrades, does not break)" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
chk "layer skipped ray query, reason env_disabled" \
    "$(b has "$w/c.log" '"ev":"rayq","action":"skipped"')"
nrej=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/c.log")
chk "all 10 painted raygens rejected with action next_overlay (got $nrej)" \
    "$([[ $nrej -eq 10 ]] && echo 1 || echo 0)"
nfb=0
for h in "${IDS[@]}"; do
    sz=$(stat -c%s "$w/lay/swaps.tgfb/$h.rgs_reference_main.spv")
    grep -q "\"ev\":\"swap_load\".*swaps.tgfb/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/c.log" \
      && nfb=$((nfb+1))
done
chk "and all 10 fell through to the NEXT OVERLAY, not to vanilla (got $nfb)" \
    "$([[ $nfb -eq 10 ]] && echo 1 || echo 0)"
# The synthetic module is NOT one of the painted ids -- its dxil identity
# (cccccccccccccccc.thinglowtest) has no swap file in either overlay, so a
# MISS on it is correct and must not be read as a painted module going vanilla.
nvan=$(grep -c '"swap":"MISS"' "$w/c.log")
chk "no PAINTED module went vanilla (MISS count is $nvan, the synthetic only)" \
    "$([[ $nvan -le 1 ]] && echo 1 || echo 0)"
echo

# ---- case D: the CONTROL is not ray-query-free ----------------------------
# 101's control was the pre-earglow base and carried no query at all, so its
# case D asserted ZERO rejects. This family's control is byte-identical to the
# STANDING DEFAULT, which carries 101's three queries -- so it must be
# rejected exactly like the live rungs. Asserting that is what keeps case C
# honest: a guard that fired on "six queries" rather than on the capability
# would pass case C and fail here.
ln -sfn "$MOD_DIR/swaps.thinglow-ctl" "$w/lay/swaps.tgrung"
run "$w/d.log" tgrung,tgfb env CALLISTO_RAYQ_DISABLE=1; rd=$?
echo "case D -- the k=0 control under the same guard: it is the standing default"
chk "probe exits 0"                               "$([[ $rd -eq 0 ]] && echo 1 || echo 0)"
nrejd=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/d.log")
chk "the control is rejected too, 10 of 10 (got $nrejd) -- it carries 101's queries" \
    "$([[ $nrejd -eq 10 ]] && echo 1 || echo 0)"
n_ctl_q=$(spirv-dis "$MOD_DIR/swaps.thinglow-ctl/${IDS[0]}.rgs_reference_main.spv" \
          | grep -c 'OpRayQueryInitializeKHR')
chk "...and it does: 3 OpRayQueryInitializeKHR in the control (got $n_ctl_q)" \
    "$([[ $n_ctl_q -eq 3 ]] && echo 1 || echo 0)"
n_live_q=$(spirv-dis "$MOD_DIR/swaps.thinglow/${IDS[0]}.rgs_reference_main.spv" \
           | grep -c 'OpRayQueryInitializeKHR')
chk "...against 6 in the live rung (got $n_live_q): the stack is real" \
    "$([[ $n_live_q -eq 6 ]] && echo 1 || echo 0)"
echo

rm -f "$w/lay/swaps.tgrung"
echo "=== $ok passed, $bad failed$( ((skip)) && echo ", $skip skipped")"
(( bad == 0 ))
