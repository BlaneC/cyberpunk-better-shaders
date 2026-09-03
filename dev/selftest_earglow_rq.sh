#!/usr/bin/env bash
# earglow-rq LAYER self-test -- the on-device half of handoff/101.
#
# ./dev/build_earglow_rq.sh gates the four rungs entirely offline. spirv-val
# is NOT a driver: it never compiles OpRayQueryGetIntersectionTKHR, and it
# does not care whether a driver's ray-query lowering accepts ray flags 545
# (Opaque | CullFrontFacingTriangles | SkipAABBs). This script answers the
# three questions only a real Vulkan device can:
#
#   1. does the layer put VK_KHR_ray_query on the VkDevice when the
#      application never asked for it (vkd3d-proton never does), so a served
#      earglow-rq raygen can link at all?
#   2. does the driver COMPILE the earglow splice shape -- flags 545, one
#      Initialize, one Proceed, the committed type + committed T getters, the
#      miss guard OpSelect, the smoothstep wrap and the six OpExtInst Exp --
#      inside a raygen that is then built into an RT pipeline?
#   3. do the REAL ~300 KB patched raygens of all SEVEN rungs survive
#      vkCreateShaderModule when served THROUGH THE LAYER by the same
#      first-file-wins overlay path the game uses -- and does the reject
#      guard fall through to the next overlay (not to vanilla) when ray query
#      is unavailable?
#   4. (rq2, handoff/101 sec 12) does the driver compile TWO ray query objects
#      live in the same raygen -- flags 517 and 545, two committed
#      OpRayQueryGetIntersectionInstanceIdKHR getters and an OpIEqual over
#      them -- into an RT pipeline? spirv-val is happy with any number of
#      query objects; a driver that spills or serialises them is not the same
#      claim, and the instance-match gate is worthless if the second query
#      does not survive lowering.
#
#   ./dev/selftest_earglow_rq.sh          # everything; no game involved
#
# NEW FILE on purpose: dev/patch_rayq.sh --selftest is shared machinery for
# handoff/98 and is not touched. Run both.
#
# Loader note, inherited from dev/patch_rayq.sh and worth repeating because
# getting it wrong makes every result a lie: the layer installs as an IMPLICIT
# layer and the loader dedupes implicit layers BY NAME, so VK_ADD_LAYER_PATH
# pointed at a fresh build still binds the INSTALLED .so. The manifest below
# therefore names the test copy VK_LAYER_CALLISTO_earglowtest.
#
# Overlay fixtures are SYMLINKS to swaps.<rung>/, never copies: the bytes the
# driver is handed are literally the shipped bytes this repo just gated.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
RUNGS=(earglow-rq-ctl earglow-rq-hit earglow-rq earglow-rq-hi
       earglow-rq2-hit earglow-rq2-hitw earglow-rq2 earglow-rq2-hi
       earglow-rq3-hit earglow-rq3 earglow-rq3-hi)
RQ2=(earglow-rq2-hit earglow-rq2-hitw earglow-rq2 earglow-rq2-hi
     earglow-rq3-hit earglow-rq3 earglow-rq3-hi)
# 101 sec 18's thickness-floor rungs, and the SHIPPED DEFAULT they cap, are
# added ONLY if they are built. They are optional on purpose: this file is the
# driver proof for the whole earglow family and must still run in a checkout
# that has rq/rq2/rq3 and nothing else. With them present the count is 48, and
# with 102's contact rungs absent it is 42 -- the printed total says which.
# The last entry is the STACKED default (101 sec 18 + 100's dense glints in the
# same ten modules): its raygens are the biggest thing this family ever hands
# the driver, and "each half compiles" is not evidence that the stack does.
for r in gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow \
         earglow-cap3 earglow-cap4 earglow-cap6 \
         gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense; do
    [[ -d "$MOD_DIR/swaps.$r" ]] && RUNGS+=("$r")
done
for r in "${RUNGS[@]}"; do
    [[ -d "$MOD_DIR/swaps.$r" ]] || {
        echo "selftest: swaps.$r is missing -- run ./dev/build_earglow_rq.sh" \
             "and ./dev/build_earglow_rq2.sh first" >&2; exit 1; }
done

ok=0; bad=0; skip=0
chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
        else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
b()  { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
# Separate negated form on purpose: `b ! cmd` cannot work -- `!` is a shell
# keyword, not a command, so it resolves to "command not found" and returns 0
# for BOTH outcomes. That silent always-fail is what this file exists to stop.
bn() { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }

for t in spirv-as spirv-val gcc python3; do
    command -v "$t" >/dev/null || { echo "selftest: need $t" >&2; exit 1; }
done
[[ -f /usr/include/vulkan/vulkan.h ]] || {
    echo "selftest: need Vulkan headers (/usr/include/vulkan/vulkan.h)" >&2; exit 1; }

w="$(mktemp -d)" || exit 1
trap 'rm -rf "$w"' EXIT

( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
    echo "selftest: layer build failed" >&2; tail -5 "$w/build.log" >&2; exit 1; }
mkdir -p "$w/lay" "$w/lay/swaps.egfb" "$w/stand"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/earglowtest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_earglowtest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the earglow-rq self-test"
    }
}
EOJ

# ------------------------------------------------------------------ fixtures
# The ten paintable ids come from the shipped rung itself, not from a list
# typed here: a hardcoded list would keep passing after the rung stopped
# painting one of them.
mapfile -t IDS < <(cd "$MOD_DIR/swaps.earglow-rq" &&
    for f in *.rgs_reference_main.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.earglow-rq-ctl/$f" || echo "${f%%.*}"
    done | sort)
(( ${#IDS[@]} == 10 )) || { echo "selftest: expected 10 painted ids, got ${#IDS[@]}" >&2; exit 1; }
# rq2 must paint the SAME ten. If it painted nine, case B below would still
# report "10 of 10" for rq2 by looking up ids derived from rq -- and the
# missing permutation would ship vanilla with nobody noticing.
for r in "${RQ2[@]}"; do
    mapfile -t I2 < <(cd "$MOD_DIR/swaps.$r" &&
        for f in *.rgs_reference_main.spv; do
            cmp -s "$f" "$MOD_DIR/swaps.earglow-rq-ctl/$f" || echo "${f%%.*}"
        done | sort)
    [[ "${I2[*]}" == "${IDS[*]}" ]] || {
        echo "selftest: $r paints a different id set than earglow-rq" >&2; exit 1; }
done

# The synthetic earglow raygen: the splice shape in miniature, with every
# operand that the driver could constant-fold away made dynamic off the launch
# id, so a "compiles" result cannot be a dead-code result.
cat > "$w/eg.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
       %glsl = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "cccccccccccccccc.?earglowtest@@YAXXZ.dxil"
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
    %uint_39 = OpConstant %uint 39
   %uint_545 = OpConstant %uint 545
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
  %float_0_5 = OpConstant %float 0.5
  %float_100 = OpConstant %float 100
 %float_tmin = OpConstant %float 0.00150000001
 %float_tmax = OpConstant %float 0.0179999992
 %float_wrap = OpConstant %float 0.349999994
    %float_k = OpConstant %float 0.219999999
   %float_n0 = OpConstant %float -0
    %float_r = OpConstant %float 272.479553
    %float_g = OpConstant %float 729.927002
    %float_b = OpConstant %float 1470.58826
   %float_r4 = OpConstant %float 68.1198883
   %float_g4 = OpConstant %float 182.481751
   %float_b4 = OpConstant %float 367.647064
      %coord = OpConstantComposite %v2uint %uint_0 %uint_0
       %main = OpFunction %void None %3
          %5 = OpLabel
          %q = OpVariable %_ptr_Function_rq Function
         %pl = OpAccessChain %_ptr_Input_uint %lid %uint_0
         %lx = OpLoad %uint %pl
         %fv = OpConvertUToF %float %lx
         %ga = OpBitwiseAnd %uint %lx %uint_1
       %gate = OpINotEqual %bool %ga %uint_0
       %mask = OpSelect %uint %gate %uint_39 %uint_0
       %orig = OpCompositeConstruct %v3float %fv %fv %fv
        %sun = OpCompositeConstruct %v3float %float_0 %float_1 %fv
        %nrm = OpCompositeConstruct %v3float %fv %float_0 %float_1
          %a = OpLoad %as %accel
               OpRayQueryInitializeKHR %q %a %uint_545 %mask %orig %float_tmin %sun %float_tmax
         %pr = OpRayQueryProceedKHR %bool %q
         %ty = OpRayQueryGetIntersectionTypeKHR %uint %q %uint_1
        %hit = OpINotEqual %bool %ty %uint_0
       %traw = OpRayQueryGetIntersectionTKHR %float %q %uint_1
          %t = OpSelect %float %hit %traw %float_tmax
         %ok = OpLogicalAnd %bool %gate %hit
         %kg = OpSelect %float %ok %float_k %float_n0
         %nd = OpDot %float %nrm %sun
         %mn = OpFNegate %float %nd
         %wr = OpExtInst %float %glsl SmoothStep %float_0 %float_wrap %mn
         %kw = OpFMul %float %kg %wr
        %e1r = OpFMul %float %t %float_r
        %n1r = OpFNegate %float %e1r
        %x1r = OpExtInst %float %glsl Exp %n1r
        %e2r = OpFMul %float %t %float_r4
        %n2r = OpFNegate %float %e2r
        %x2r = OpExtInst %float %glsl Exp %n2r
        %sr0 = OpFAdd %float %x1r %x2r
        %sr1 = OpFMul %float %sr0 %float_0_5
        %sr2 = OpFMul %float %sr1 %kw
         %cr = OpExtInst %float %glsl NMin %sr2 %float_100
        %e1g = OpFMul %float %t %float_g
        %n1g = OpFNegate %float %e1g
        %x1g = OpExtInst %float %glsl Exp %n1g
        %e2g = OpFMul %float %t %float_g4
        %n2g = OpFNegate %float %e2g
        %x2g = OpExtInst %float %glsl Exp %n2g
        %sg0 = OpFAdd %float %x1g %x2g
        %sg1 = OpFMul %float %sg0 %float_0_5
        %sg2 = OpFMul %float %sg1 %kw
         %cg = OpExtInst %float %glsl NMin %sg2 %float_100
        %e1b = OpFMul %float %t %float_b
        %n1b = OpFNegate %float %e1b
        %x1b = OpExtInst %float %glsl Exp %n1b
        %e2b = OpFMul %float %t %float_b4
        %n2b = OpFNegate %float %e2b
        %x2b = OpExtInst %float %glsl Exp %n2b
        %sb0 = OpFAdd %float %x1b %x2b
        %sb1 = OpFMul %float %sb0 %float_0_5
        %sb2 = OpFMul %float %sb1 %kw
         %cb = OpExtInst %float %glsl NMin %sb2 %float_100
         %px = OpCompositeConstruct %v4float %cr %cg %cb %float_1
         %im = OpLoad %img %out
               OpImageWrite %im %coord %px
               OpReturn
               OpFunctionEnd
EOA
spirv-as --target-env spv1.4 "$w/eg.spvasm" -o "$w/eg.spv" || {
    echo "selftest: spirv-as failed on the synthetic earglow module" >&2; exit 1; }
spirv-val --target-env vulkan1.4 "$w/eg.spv" || {
    echo "selftest: spirv-val failed on the synthetic earglow module" >&2; exit 1; }

# The rq2/rq3 synthetic raygen: the SAME shape with the second and third
# queries added. THREE OpTypeRayQueryKHR Function objects live at once --
# A on the view ray (flags 517, first-hit, +/-0.1% bracket on |P|), B sunward
# (flags 545), C from B's pushed exit point back at the sun (flags 517) --
# A's and B's committed InstanceIds compared with OpIEqual, C's commit test
# negated, and the transfer multiplied by both. Every operand is derived from
# the launch id so nothing can be folded away; if the driver refuses three
# live query objects, or the InstanceId getter, it fails HERE and not in a
# 300 KB module where the cause would be unreadable.
cat > "$w/eg2.spvasm" <<'EOB'
               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
       %glsl = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "cccccccccccccccc.?earglowtest@@YAXXZ.dxil"
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
    %uint_39 = OpConstant %uint 39
   %uint_517 = OpConstant %uint 517
   %uint_545 = OpConstant %uint 545
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
  %float_0_5 = OpConstant %float 0.5
  %float_100 = OpConstant %float 100
 %float_tmin = OpConstant %float 0.00150000001
 %float_tmax = OpConstant %float 0.0179999992
   %float_lo = OpConstant %float 0.999000013
   %float_hi = OpConstant %float 1.00100005
  %float_eps = OpConstant %float 9.99999975e-05
 %float_push = OpConstant %float 0.00100000005
  %float_far = OpConstant %float 10000
 %float_wrap = OpConstant %float 0.349999994
    %float_k = OpConstant %float 0.219999999
   %float_n0 = OpConstant %float -0
    %float_r = OpConstant %float 272.479553
    %float_g = OpConstant %float 729.927002
    %float_b = OpConstant %float 1470.58826
   %float_r4 = OpConstant %float 68.1198883
   %float_g4 = OpConstant %float 182.481751
   %float_b4 = OpConstant %float 367.647064
      %zero3 = OpConstantComposite %v3float %float_0 %float_0 %float_0
      %coord = OpConstantComposite %v2uint %uint_0 %uint_0
       %main = OpFunction %void None %3
          %5 = OpLabel
         %qa = OpVariable %_ptr_Function_rq Function
         %qb = OpVariable %_ptr_Function_rq Function
         %qc = OpVariable %_ptr_Function_rq Function
         %pl = OpAccessChain %_ptr_Input_uint %lid %uint_0
         %lx = OpLoad %uint %pl
         %fv = OpConvertUToF %float %lx
         %ga = OpBitwiseAnd %uint %lx %uint_1
       %gate = OpINotEqual %bool %ga %uint_0
       %mask = OpSelect %uint %gate %uint_39 %uint_0
       %orig = OpCompositeConstruct %v3float %fv %fv %fv
        %sun = OpCompositeConstruct %v3float %float_0 %float_1 %fv
        %nrm = OpCompositeConstruct %v3float %fv %float_0 %float_1
          %a = OpLoad %as %accel
;      query A -- the module's own view ray, camera-relative (98 sec 15)
        %dot = OpDot %float %orig %orig
        %rsq = OpExtInst %float %glsl InverseSqrt %dot
        %len = OpFMul %float %dot %rsq
         %lo = OpFMul %float %len %float_lo
        %hi0 = OpFMul %float %len %float_hi
         %hi = OpFAdd %float %hi0 %float_eps
        %vdi = OpVectorTimesScalar %v3float %orig %rsq
               OpRayQueryInitializeKHR %qa %a %uint_517 %mask %zero3 %float_0 %vdi %hi
        %pra = OpRayQueryProceedKHR %bool %qa
        %tya = OpRayQueryGetIntersectionTypeKHR %uint %qa %uint_1
        %hia = OpINotEqual %bool %tya %uint_0
         %ta = OpRayQueryGetIntersectionTKHR %float %qa %uint_1
        %gea = OpFOrdGreaterThanEqual %bool %ta %lo
        %oka = OpLogicalAnd %bool %hia %gea
        %ida = OpRayQueryGetIntersectionInstanceIdKHR %uint %qa %uint_1
;      query B -- sunward, cull front faces: the first BACKFACE within 18 mm
               OpRayQueryInitializeKHR %qb %a %uint_545 %mask %orig %float_tmin %sun %float_tmax
        %prb = OpRayQueryProceedKHR %bool %qb
        %tyb = OpRayQueryGetIntersectionTypeKHR %uint %qb %uint_1
        %hib = OpINotEqual %bool %tyb %uint_0
       %traw = OpRayQueryGetIntersectionTKHR %float %qb %uint_1
          %t = OpSelect %float %hib %traw %float_tmax
        %idb = OpRayQueryGetIntersectionInstanceIdKHR %uint %qb %uint_1
;      query C -- sun visibility FROM THE EXIT POINT (rq3, 101 sec 15.5)
         %tp = OpFAdd %float %t %float_push
        %off = OpVectorTimesScalar %v3float %sun %tp
        %org = OpFAdd %v3float %orig %off
               OpRayQueryInitializeKHR %qc %a %uint_517 %mask %org %float_push %sun %float_far
        %prc = OpRayQueryProceedKHR %bool %qc
        %tyc = OpRayQueryGetIntersectionTypeKHR %uint %qc %uint_1
        %hic = OpINotEqual %bool %tyc %uint_0
        %vis = OpLogicalNot %bool %hic
;      THE GATE: same instance, and the exit point sees the sun
       %same = OpIEqual %bool %ida %idb
       %both = OpLogicalAnd %bool %oka %hib
      %match = OpLogicalAnd %bool %both %same
        %mvis = OpLogicalAnd %bool %match %vis
         %ok = OpLogicalAnd %bool %gate %mvis
         %kg = OpSelect %float %ok %float_k %float_n0
         %nd = OpDot %float %nrm %sun
         %mn = OpFNegate %float %nd
         %wr = OpExtInst %float %glsl SmoothStep %float_0 %float_wrap %mn
         %kw = OpFMul %float %kg %wr
        %e1r = OpFMul %float %t %float_r
        %n1r = OpFNegate %float %e1r
        %x1r = OpExtInst %float %glsl Exp %n1r
        %e2r = OpFMul %float %t %float_r4
        %n2r = OpFNegate %float %e2r
        %x2r = OpExtInst %float %glsl Exp %n2r
        %sr0 = OpFAdd %float %x1r %x2r
        %sr1 = OpFMul %float %sr0 %float_0_5
        %sr2 = OpFMul %float %sr1 %kw
         %cr = OpExtInst %float %glsl NMin %sr2 %float_100
        %e1g = OpFMul %float %t %float_g
        %n1g = OpFNegate %float %e1g
        %x1g = OpExtInst %float %glsl Exp %n1g
        %e2g = OpFMul %float %t %float_g4
        %n2g = OpFNegate %float %e2g
        %x2g = OpExtInst %float %glsl Exp %n2g
        %sg0 = OpFAdd %float %x1g %x2g
        %sg1 = OpFMul %float %sg0 %float_0_5
        %sg2 = OpFMul %float %sg1 %kw
         %cg = OpExtInst %float %glsl NMin %sg2 %float_100
        %e1b = OpFMul %float %t %float_b
        %n1b = OpFNegate %float %e1b
        %x1b = OpExtInst %float %glsl Exp %n1b
        %e2b = OpFMul %float %t %float_b4
        %n2b = OpFNegate %float %e2b
        %x2b = OpExtInst %float %glsl Exp %n2b
        %sb0 = OpFAdd %float %x1b %x2b
        %sb1 = OpFMul %float %sb0 %float_0_5
        %sb2 = OpFMul %float %sb1 %kw
         %cb = OpExtInst %float %glsl NMin %sb2 %float_100
         %px = OpCompositeConstruct %v4float %cr %cg %cb %float_1
         %im = OpLoad %img %out
               OpImageWrite %im %coord %px
               OpReturn
               OpFunctionEnd
EOB
spirv-as --target-env spv1.4 "$w/eg2.spvasm" -o "$w/eg2.spv" || {
    echo "selftest: spirv-as failed on the synthetic rq2 module" >&2; exit 1; }
spirv-val --target-env vulkan1.4 "$w/eg2.spv" || {
    echo "selftest: spirv-val failed on the synthetic rq2 module" >&2; exit 1; }

# One stand-in raygen per painted id -- what the "application" (vkd3d-proton)
# creates. It carries only the dxil identity string; the layer replaces its
# bytes with the rung's real ~300 KB module. Each also gets a byte-distinct
# fallback twin in swaps.egfb/ so a reject can be seen to land on the NEXT
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
                           ('fb', 13, os.path.join(w, 'lay', 'swaps.egfb',
                                                   h + '.rgs_reference_main.spv'))):
        a = out + '.spvasm'
        open(a, 'w').write(TMPL.replace('HASH', h).replace('MARK', str(mark)))
        subprocess.run(['spirv-as', '--target-env', 'spv1.4', a, '-o', out],
                       check=True)
        os.remove(a)
PYGEN

# ---------------------------------------------------------------------- probe
cat > "$w/st.c" <<'EOC'
/* The same calls the game makes: a device created WITHOUT asking for ray
 * query, a raygen module, an RT pipeline built from it -- then one plain
 * module per painted id, each of which the layer swaps for the rung's real
 * patched raygen. argv[1] is the module that also gets a pipeline; argv[2..]
 * are create-only. */
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t *slurp(const char *p, size_t *n) {
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(3); }
    fseek(f,0,SEEK_END); long s = ftell(f); fseek(f,0,SEEK_SET);
    uint32_t *b = malloc(s); if (fread(b,1,s,f)!=(size_t)s) exit(3);
    fclose(f); *n = s; return b;
}
#define CK(x,m) do{VkResult _r=(x); if(_r!=VK_SUCCESS){printf("FAIL %s -> %d\n",m,_r);return 4;}}while(0)
int main(int argc, char **argv) {
    const char *spv = argc>1 ? argv[1] : "eg.spv";
    VkApplicationInfo app={VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.apiVersion=VK_API_VERSION_1_3;
    VkInstanceCreateInfo ii={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ii.pApplicationInfo=&app;
    VkInstance inst; CK(vkCreateInstance(&ii,NULL,&inst),"vkCreateInstance");
    uint32_t np=0; vkEnumeratePhysicalDevices(inst,&np,NULL);
    VkPhysicalDevice *pd=calloc(np,sizeof*pd); vkEnumeratePhysicalDevices(inst,&np,pd);
    VkPhysicalDevice phys=VK_NULL_HANDLE; VkPhysicalDeviceProperties props; int adv=0;
    for (uint32_t i=0;i<np;i++){
        uint32_t ne=0; vkEnumerateDeviceExtensionProperties(pd[i],NULL,&ne,NULL);
        VkExtensionProperties *ep=calloc(ne,sizeof*ep);
        vkEnumerateDeviceExtensionProperties(pd[i],NULL,&ne,ep);
        int rtp=0,rq=0;
        for(uint32_t k=0;k<ne;k++){
            if(!strcmp(ep[k].extensionName,VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME))rtp=1;
            if(!strcmp(ep[k].extensionName,VK_KHR_RAY_QUERY_EXTENSION_NAME))rq=1;
        }
        free(ep);
        if(rtp){phys=pd[i];adv=rq;vkGetPhysicalDeviceProperties(phys,&props);break;}
    }
    if(!phys){printf("FAIL no device with VK_KHR_ray_tracing_pipeline\n");return 4;}
    printf("device: %s  ray query advertised by ICD: %s\n",props.deviceName,adv?"yes":"NO");
    float prio=1.0f;
    VkDeviceQueueCreateInfo q={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    q.queueFamilyIndex=0;q.queueCount=1;q.pQueuePriorities=&prio;
    /* deliberately does NOT list VK_KHR_ray_query -- that is the layer's job */
    const char *exts[]={VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME,
                        VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME,
                        VK_KHR_DEFERRED_HOST_OPERATIONS_EXTENSION_NAME};
    VkPhysicalDeviceRayTracingPipelineFeaturesKHR rt={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_TRACING_PIPELINE_FEATURES_KHR};
    rt.rayTracingPipeline=VK_TRUE;
    VkPhysicalDeviceAccelerationStructureFeaturesKHR as={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ACCELERATION_STRUCTURE_FEATURES_KHR};
    as.accelerationStructure=VK_TRUE; as.pNext=&rt;
    VkPhysicalDeviceVulkan12Features v12={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    v12.bufferDeviceAddress=VK_TRUE; v12.pNext=&as;
    VkDeviceCreateInfo dci={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.pNext=&v12; dci.queueCreateInfoCount=1; dci.pQueueCreateInfos=&q;
    dci.enabledExtensionCount=3; dci.ppEnabledExtensionNames=exts;
    VkDevice dev; CK(vkCreateDevice(phys,&dci,NULL,&dev),"vkCreateDevice");
    printf("device created with %u extensions requested by the app\n",dci.enabledExtensionCount);

    size_t n; uint32_t *code=slurp(spv,&n);
    VkShaderModuleCreateInfo smi={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smi.codeSize=n; smi.pCode=code;
    VkShaderModule sm; VkResult r=vkCreateShaderModule(dev,&smi,NULL,&sm);
    printf("vkCreateShaderModule(%s, %zu B) -> %d\n",spv,n,r);
    if(r!=VK_SUCCESS){printf("RESULT: module rejected\n");return 5;}
    int nbad=0;
    for(int ai=2; ai<argc; ai++){
        size_t n2; uint32_t *c2=slurp(argv[ai],&n2);
        VkShaderModuleCreateInfo s2={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        s2.codeSize=n2; s2.pCode=c2;
        VkShaderModule m2; VkResult r2=vkCreateShaderModule(dev,&s2,NULL,&m2);
        printf("served %s -> %d\n",argv[ai],r2);
        if(r2!=VK_SUCCESS) nbad++;
        free(c2);
    }
    /* The synthetic module declares one descriptor set; give the pipeline a
     * matching layout or creation fails for reasons unrelated to ray query. */
    VkDescriptorSetLayoutBinding b[2]={{0}};
    b[0].binding=0;b[0].descriptorType=VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR;
    b[0].descriptorCount=1;b[0].stageFlags=VK_SHADER_STAGE_RAYGEN_BIT_KHR;
    b[1].binding=1;b[1].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
    b[1].descriptorCount=1;b[1].stageFlags=VK_SHADER_STAGE_RAYGEN_BIT_KHR;
    VkDescriptorSetLayoutCreateInfo dsl={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    dsl.bindingCount=2;dsl.pBindings=b;
    VkDescriptorSetLayout dl; CK(vkCreateDescriptorSetLayout(dev,&dsl,NULL,&dl),"dsl");
    VkPipelineLayoutCreateInfo pli={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pli.setLayoutCount=1; pli.pSetLayouts=&dl;
    VkPipelineLayout pl; CK(vkCreatePipelineLayout(dev,&pli,NULL,&pl),"vkCreatePipelineLayout");
    PFN_vkCreateRayTracingPipelinesKHR fn=(PFN_vkCreateRayTracingPipelinesKHR)
        vkGetDeviceProcAddr(dev,"vkCreateRayTracingPipelinesKHR");
    if(!fn){printf("FAIL no vkCreateRayTracingPipelinesKHR\n");return 4;}
    VkPipelineShaderStageCreateInfo st={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};
    st.stage=VK_SHADER_STAGE_RAYGEN_BIT_KHR; st.module=sm; st.pName="main";
    VkRayTracingShaderGroupCreateInfoKHR gr={VK_STRUCTURE_TYPE_RAY_TRACING_SHADER_GROUP_CREATE_INFO_KHR};
    gr.type=VK_RAY_TRACING_SHADER_GROUP_TYPE_GENERAL_KHR; gr.generalShader=0;
    gr.closestHitShader=VK_SHADER_UNUSED_KHR; gr.anyHitShader=VK_SHADER_UNUSED_KHR;
    gr.intersectionShader=VK_SHADER_UNUSED_KHR;
    VkRayTracingPipelineCreateInfoKHR rpi={VK_STRUCTURE_TYPE_RAY_TRACING_PIPELINE_CREATE_INFO_KHR};
    rpi.stageCount=1; rpi.pStages=&st; rpi.groupCount=1; rpi.pGroups=&gr;
    rpi.maxPipelineRayRecursionDepth=1; rpi.layout=pl;
    VkPipeline pipe; r=fn(dev,VK_NULL_HANDLE,VK_NULL_HANDLE,1,&rpi,NULL,&pipe);
    printf("vkCreateRayTracingPipelinesKHR -> %d\n",r);
    if(r!=VK_SUCCESS){printf("RESULT: PIPELINE REJECTED\n");return 6;}
    vkDestroyDevice(dev,NULL);
    printf("RESULT: OK  served_failures=%d\n",nbad);
    return nbad?7:0;
}
EOC
gcc -O1 -o "$w/st" "$w/st.c" -lvulkan 2>"$w/cc.err" || {
    echo "selftest: could not build the probe (need libvulkan-dev):" >&2
    sed -n '1,5p' "$w/cc.err" >&2; exit 1; }

STAND=(); for h in "${IDS[@]}"; do STAND+=("$w/stand/$h.spv"); done

run() { # run <log> <overlays> [extra env ...]
    local log="$1" ov="$2"; shift 2
    env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_earglowtest \
        CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" \
        "$@" "$w/st" "${SYNTH:-$w/eg.spv}" "${STAND[@]}" >"$log.out" 2>&1
}
has() { grep -q -- "$2" "$1"; }

echo "earglow-rq / rq2 layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
echo "10 painted ids: ${IDS[*]}"
echo

# ---- case A: the layer supplies ray query the app never asked for ----------
ln -sfn "$MOD_DIR/swaps.earglow-rq" "$w/lay/swaps.egrung"
run "$w/a.log" egrung,egfb env; ra=$?
echo "case A -- the layer enables VK_KHR_ray_query and serves earglow-rq"
sed -n '1,4p' "$w/a.log.out" | sed 's/^/    /'
chk "probe exits 0"                             "$([[ $ra -eq 0 ]] && echo 1 || echo 0)"
chk "layer enabled VK_KHR_ray_query"            "$(b has "$w/a.log" '"ev":"rayq","action":"enabled"')"
chk "synthetic earglow module accepted"         "$(b grep -q "eg.spv.*-> 0" "$w/a.log.out")"
chk "...and its RT PIPELINE links (the driver compiled flags 545 + committed T)" \
    "$(b grep -q 'vkCreateRayTracingPipelinesKHR -> 0' "$w/a.log.out")"
chk "no rayq_reject"                            "$(bn has "$w/a.log" 'rayq_reject')"
chk "no rt_pipeline_failed"                     "$(bn has "$w/a.log" 'rt_pipeline_failed')"
echo

# ---- case B: the real ~300 KB raygens, served through the layer ------------
# One check per module per rung: the synthetic module above is under 2 KB and
# proves nothing about a query spliced into 14 000 lines of shipped raygen.
echo "case B -- every rung's real raygens, served by the overlay, on the driver"
for rung in "${RUNGS[@]}"; do
    ln -sfn "$MOD_DIR/swaps.$rung" "$w/lay/swaps.egrung"
    run "$w/b_$rung.log" egrung,egfb env; rb=$?
    chk "$rung: probe exits 0, no served module refused" \
        "$([[ $rb -eq 0 ]] && echo 1 || echo 0)"
    nhit=0
    for h in "${IDS[@]}"; do
        sz=$(stat -c%s "$MOD_DIR/swaps.$rung/$h.rgs_reference_main.spv")
        grep -q "\"ev\":\"swap_load\".*swaps.egrung/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/b_$rung.log" \
          && grep -q "\"id\":\"$h.rgs_reference_main\".*\"swap\":\"HIT\",\"result\":0" "$w/b_$rung.log" \
          && nhit=$((nhit+1))
    done
    chk "$rung: 10 of 10 real raygens served at their shipped size and accepted (got $nhit)" \
        "$([[ $nhit -eq 10 ]] && echo 1 || echo 0)"
done
echo

# ---- case C: the reject guard falls through to the NEXT OVERLAY ------------
# GOTCHAS, "an overlay reject must fall through": serving a vanilla raygen on
# top of a patched compute set is a worse failure than serving the base image.
ln -sfn "$MOD_DIR/swaps.earglow-rq" "$w/lay/swaps.egrung"
run "$w/c.log" egrung,egfb env CALLISTO_RAYQ_DISABLE=1; rc=$?
echo "case C -- CALLISTO_RAYQ_DISABLE=1: reject earglow-rq, fall through to swaps.egfb/"
chk "probe still exits 0 (degrades, does not break)" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
chk "layer skipped ray query, reason env_disabled" \
    "$(b has "$w/c.log" '"ev":"rayq","action":"skipped","reason":"env_disabled"')"
nrej=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/c.log")
chk "all 10 painted raygens rejected with action next_overlay (got $nrej)" \
    "$([[ $nrej -eq 10 ]] && echo 1 || echo 0)"
nfb=0
for h in "${IDS[@]}"; do
    sz=$(stat -c%s "$w/lay/swaps.egfb/$h.rgs_reference_main.spv")
    grep -q "\"ev\":\"swap_load\".*swaps.egfb/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/c.log" \
      && nfb=$((nfb+1))
done
chk "and all 10 fell through to the NEXT OVERLAY, not to vanilla (got $nfb)" \
    "$([[ $nfb -eq 10 ]] && echo 1 || echo 0)"
# Scoped to rgs_reference_main on purpose: the synthetic module's own
# identity (cccccccccccccccc.earglowtest) has no swap file in either overlay,
# so it legitimately logs swap:none on every run. An unscoped check here
# fails always, which reads as a real defect and is not one.
chk "no PAINTED module went vanilla" \
    "$(bn grep -q '"id":"[0-9a-f]*\.rgs_reference_main".*"swap":"none"' "$w/c.log")"
echo

# ---- case D: the control carries no ray query at all ----------------------
# Non-vacuity for case C: if the guard fired on -ctl too, the guard would be
# keying on something other than OpCapability RayQueryKHR.
ln -sfn "$MOD_DIR/swaps.earglow-rq-ctl" "$w/lay/swaps.egrung"
run "$w/d.log" egrung,egfb env CALLISTO_RAYQ_DISABLE=1; rd=$?
echo "case D -- the k=0 control under the same guard: nothing to reject"
chk "probe exits 0"                               "$([[ $rd -eq 0 ]] && echo 1 || echo 0)"
chk "NO rayq_reject on the control"               "$(bn has "$w/d.log" 'rayq_reject')"
nctl=$(grep -c '"swap":"HIT","result":0' "$w/d.log")
chk "all 10 control raygens served anyway (got $nctl)" \
    "$([[ $nctl -eq 10 ]] && echo 1 || echo 0)"
echo

# ---- case E: TWO live ray queries + the instance compare (rq2) -------------
# The claim under test is narrow and is the whole of handoff/101 sec 12's fix:
# a driver that compiles ONE query object says nothing about two live at once,
# and OpRayQueryGetIntersectionInstanceIdKHR is a getter the earglow-rq rungs
# never used. Non-vacuity first: assert the synthetic module really carries
# the two-query shape, so "it compiled" cannot be "it compiled nothing".
n_init=$(spirv-dis "$w/eg2.spv" | grep -c 'OpRayQueryInitializeKHR')
n_iid=$(spirv-dis "$w/eg2.spv" | grep -c 'OpRayQueryGetIntersectionInstanceIdKHR')
# spirv-dis renumbers: the assembly's %ida/%idb do not survive the round trip,
# so count the op, not the operand names.
n_eq=$(spirv-dis "$w/eg2.spv" | grep -c 'OpIEqual')
echo "case E -- THREE live ray query objects, two InstanceId getters, one OpIEqual"
chk "the synthetic module is the three-query shape (3/2/1, got $n_init/$n_iid/$n_eq)" \
    "$([[ $n_init -eq 3 && $n_iid -eq 2 && $n_eq -eq 1 ]] && echo 1 || echo 0)"
ln -sfn "$MOD_DIR/swaps.earglow-rq3" "$w/lay/swaps.egrung"
SYNTH="$w/eg2.spv" run "$w/e.log" egrung,egfb env; re=$?
sed -n '1,4p' "$w/e.log.out" | sed 's/^/    /'
chk "probe exits 0"                             "$([[ $re -eq 0 ]] && echo 1 || echo 0)"
chk "synthetic rq2/rq3 module accepted"             "$(b grep -q "eg2.spv.*-> 0" "$w/e.log.out")"
chk "...and its RT PIPELINE links (the driver lowered ALL THREE queries + the compare)" \
    "$(b grep -q 'vkCreateRayTracingPipelinesKHR -> 0' "$w/e.log.out")"
chk "no rayq_reject"                            "$(bn has "$w/e.log" 'rayq_reject')"
chk "no rt_pipeline_failed"                     "$(bn has "$w/e.log" 'rt_pipeline_failed')"
unset SYNTH
echo

rm -f "$w/lay/swaps.egrung"
echo "=== $ok passed, $bad failed$( ((skip)) && echo ", $skip skipped")"
exit $(( bad ? 1 : 0 ))
