#!/usr/bin/env bash
# glintobj LAYER self-test -- the on-device half of handoff/106.
#
# ./dev/build_glintobj.sh gates the four rungs entirely offline. spirv-val is
# NOT a driver. In particular it has no opinion on the one instruction this
# whole feature turns on:
#
#     %m = OpRayQueryGetIntersectionWorldToObjectKHR %mat4v3float %q %uint_1
#
# a 3x4 affine returned BY VALUE from a committed intersection, immediately
# decomposed into four v3 columns and recombined into a point. That is the
# getter `98` sec 14.6 never called (xf/xfq/xfw all read the instance id, not
# the matrix), so nothing in this repo has ever asked a driver to lower it.
# This script answers the four questions only a real Vulkan device can:
#
#   1. does the layer put VK_KHR_ray_query on the VkDevice when the
#      application never asked for it (vkd3d-proton never does)? -- inherited
#      from the base, which already needs it for `101`'s ear glow, but a rung
#      that cannot link is not a rung.
#   2. does the driver COMPILE the object-space splice shape -- flags 517, the
#      t bracket, ONE Initialize/Proceed/committed-type, the WorldToObject
#      getter, its four column extracts, the affine recombination, and the
#      per-axis select against the world-space fallback -- inside a raygen that
#      is then built into an RT pipeline?
#   3. do the REAL ~300 KB patched raygens of all four rungs survive
#      vkCreateShaderModule when served THROUGH THE LAYER by the same
#      first-file-wins overlay path the game uses?
#   4. does the reject guard fall through to the NEXT OVERLAY (not to vanilla)
#      when ray query is unavailable -- and does it do so for the CONTROL too?
#      It must: glintobj-ctl is byte-identical to a base that already carries
#      `101`'s queries. This feature adds no NEW layer requirement, and case D
#      is what proves that claim instead of asserting it.
#
#   ./dev/selftest_glintobj.sh          # everything; no game involved
#
# NEW FILE on purpose: dev/selftest_contact_rq.sh (102),
# dev/selftest_earglow_rq.sh (101) and dev/patch_rayq.sh --selftest (98) are
# not touched. Run them too -- they cover different splice shapes.
#
# Loader note, inherited from dev/patch_rayq.sh and worth repeating because
# getting it wrong makes every result a lie: the layer installs as an IMPLICIT
# layer and the loader dedupes implicit layers BY NAME, so VK_ADD_LAYER_PATH
# pointed at a fresh build still binds the INSTALLED .so. The manifest below
# therefore names the test copy VK_LAYER_CALLISTO_glintobjtest.
#
# Overlay fixtures are SYMLINKS to swaps.<rung>/, never copies: the bytes the
# driver is handed are literally the shipped bytes this repo just gated.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNGS=(glintobj-ctl glintobj glintobj-cell glintobj-miss)

ok=0; bad=0; skip=0
chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
        else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
b()  { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
# Separate negated form on purpose: `b ! cmd` cannot work -- `!` is a shell
# keyword, not a command, so it resolves to "command not found" and returns 0
# for BOTH outcomes.
bn() { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }

for t in spirv-as spirv-val spirv-dis gcc python3; do
    command -v "$t" >/dev/null || { echo "selftest: need $t" >&2; exit 1; }
done
[[ -f /usr/include/vulkan/vulkan.h ]] || {
    echo "selftest: need Vulkan headers (/usr/include/vulkan/vulkan.h)" >&2; exit 1; }
for r in "${RUNGS[@]}"; do
    [[ -d "$MOD_DIR/swaps.$r" ]] || {
        echo "selftest: no swaps.$r -- run ./dev/build_glintobj.sh first" >&2; exit 1; }
done

w="$(mktemp -d)" || exit 1
trap 'rm -rf "$w"' EXIT

( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
    echo "selftest: layer build failed" >&2; tail -5 "$w/build.log" >&2; exit 1; }
mkdir -p "$w/lay" "$w/lay/swaps.gofb" "$w/stand"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/glintobjtest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_glintobjtest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the glintobj self-test"
    }
}
EOJ

# ------------------------------------------------------------------ fixtures
# The patched ids come from the shipped rung itself, not from a list typed
# here: a hardcoded list would keep passing after the rung stopped patching one
# of them. glintobj reaches TEN of the twelve -- the two scalar-specular
# permutations are declined by name (`100` sec 2.1) and stay byte-verbatim.
mapfile -t IDS < <(cd "$MOD_DIR/swaps.glintobj" &&
    for f in *.rgs_reference_main.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.glintobj-ctl/$f" || echo "${f%%.*}"
    done | sort)
(( ${#IDS[@]} == 10 )) || { echo "selftest: expected 10 patched ids, got ${#IDS[@]}" >&2; exit 1; }

# The ids that carry a ray query AT ALL -- re-derived from the CONTROL, which
# is the base. The count is expected to be the same 10, because `101`'s ear
# glow already patched exactly this set; case D asserts that rather than
# assuming it.
# grep -c, not grep -q: `set -o pipefail` is on, and `grep -q` exits at the
# first match, which SIGPIPEs spirv-dis and makes the whole pipeline report
# failure -- so the -q form silently found ZERO ray-query raygens in a base
# that has ten.
mapfile -t RQIDS < <(cd "$MOD_DIR/swaps.glintobj-ctl" &&
    for f in *.rgs_reference_main.spv; do
        n=$(spirv-dis "$f" | grep -c 'OpCapability RayQueryKHR')
        [[ "$n" -gt 0 ]] && echo "${f%%.*}"
    done | sort)

# The synthetic object-space raygen: the splice shape in miniature, with every
# operand the driver could constant-fold away made dynamic off the launch id,
# so a "compiles" result cannot be a dead-code result. Flags, bracket, magenta
# and the glint constants are IMPORTED from the patcher and the model -- the
# same values the rungs were built with, never retyped.
python3 - "$w" "$MOD_DIR/dev" <<'PYGEN' || { echo "selftest: could not emit the synthetic module" >&2; exit 1; }
import os, sys
w = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from patch_glintobj import RAY_FLAGS, T_LO, T_HI, T_EPS, MAGENTA
import glint_model as GM
C = GM.constants(GM.knobs(nu0=600000.0))
head = f'''               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
       %glsl = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "dddddddddddddddd.?glintobjtest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
               OpDecorate %accel DescriptorSet 0
               OpDecorate %accel Binding 0
               OpDecorate %out DescriptorSet 0
               OpDecorate %out Binding 1
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
        %int = OpTypeInt 32 1
      %float = OpTypeFloat 32
       %bool = OpTypeBool
     %v2uint = OpTypeVector %uint 2
     %v3uint = OpTypeVector %uint 3
    %v3float = OpTypeVector %float 3
    %v4float = OpTypeVector %float 4
%mat4v3float = OpTypeMatrix %v3float 4
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
     %uint_8 = OpConstant %uint 8
   %uint_255 = OpConstant %uint 255
 %uint_flags = OpConstant %uint {RAY_FLAGS}
     %uint_h0 = OpConstant %uint {int(GM.C_CELL[0])}
     %uint_h1 = OpConstant %uint {int(GM.C_CELL[1])}
     %uint_h2 = OpConstant %uint {int(GM.C_CELL[2])}
    %uint_pcg = OpConstant %uint {int(GM.PCG_MUL)}
    %uint_inc = OpConstant %uint {int(GM.PCG_INC)}
   %uint_xmul = OpConstant %uint {int(GM.PCG_XMUL)}
    %uint_28 = OpConstant %uint 28
    %uint_22 = OpConstant %uint 22
     %uint_4 = OpConstant %uint 4
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
   %float_lo = OpConstant %float {T_LO}
   %float_hi = OpConstant %float {T_HI}
  %float_eps = OpConstant %float {T_EPS}
 %float_cell = OpConstant %float {float(C['CELL'])}
  %float_rmx = OpConstant %float {float(GM.RATIO_MAX)}
  %float_big = OpConstant %float 1e+09
 %float_nbig = OpConstant %float -1e+09
  %float_nu0 = OpConstant %float {float(C['NU0'])}
 %float_2n32 = OpConstant %float {float(C['TWO_M32'])}
   %float_mr = OpConstant %float {MAGENTA[0]}
   %float_mg = OpConstant %float {MAGENTA[1]}
   %float_mb = OpConstant %float {MAGENTA[2]}
      %coord = OpConstantComposite %v2uint %uint_0 %uint_0
'''
body = '''       %main = OpFunction %void None %3
          %5 = OpLabel
          %q = OpVariable %_ptr_Function_rq Function
         %pl = OpAccessChain %_ptr_Input_uint %lid %uint_0
         %lx = OpLoad %uint %pl
        %pl2 = OpAccessChain %_ptr_Input_uint %lid %uint_1
         %ly = OpLoad %uint %pl2
         %fv = OpConvertUToF %float %lx
         %fw = OpConvertUToF %float %ly
         %t  = OpFAdd %float %fv %float_1
       %pcam = OpCompositeConstruct %v3float %fv %fw %float_1
        %dir = OpCompositeConstruct %v3float %float_0 %float_0 %float_1
       ; --- the world-space feed `100` shipped: cb56 + P, faked off the
       ; launch id so the driver cannot fold it away ---------------------
        %o0 = OpFMul %float %fw %float_1
        %w0 = OpFAdd %float %o0 %fv
        %w1 = OpFAdd %float %o0 %fw
        %w2 = OpFAdd %float %o0 %float_1
       ; --- one query down the segment, bracketed on t -------------------
       %tmin = OpFMul %float %t %float_lo
       %thia = OpFMul %float %t %float_hi
       %tmax = OpFAdd %float %thia %float_eps
          %a = OpLoad %as %accel
               OpRayQueryInitializeKHR %q %a %uint_flags %uint_255 %pcam %tmin %dir %tmax
         %pr = OpRayQueryProceedKHR %bool %q
         %ty = OpRayQueryGetIntersectionTypeKHR %uint %q %uint_1
        %hit = OpINotEqual %bool %ty %uint_0
       ; --- THE instruction this whole self-test exists for --------------
          %M = OpRayQueryGetIntersectionWorldToObjectKHR %mat4v3float %q %uint_1
         %c0 = OpCompositeExtract %v3float %M 0
         %c1 = OpCompositeExtract %v3float %M 1
         %c2 = OpCompositeExtract %v3float %M 2
         %c3 = OpCompositeExtract %v3float %M 3
         %s0 = OpVectorTimesScalar %v3float %c0 %fv
         %s1 = OpVectorTimesScalar %v3float %c1 %fw
         %s2 = OpVectorTimesScalar %v3float %c2 %float_1
         %aa = OpFAdd %v3float %s0 %s1
         %ab = OpFAdd %v3float %aa %s2
         %po = OpFAdd %v3float %ab %c3
         %o0e = OpCompositeExtract %float %po 0
         %o1e = OpCompositeExtract %float %po 1
         %o2e = OpCompositeExtract %float %po 2
       ; --- the REPLACE: object space when committed, world space when not
         %f0 = OpSelect %float %hit %o0e %w0
         %f1 = OpSelect %float %hit %o1e %w1
         %f2 = OpSelect %float %hit %o2e %w2
       ; --- `100`'s dyadic ladder and cell hash, unchanged ---------------
        %rat = OpExtInst %float %glsl NClamp %t %float_1 %float_rmx
        %lg2 = OpExtInst %float %glsl Log2 %rat
        %cei = OpExtInst %float %glsl Ceil %lg2
        %ex2 = OpExtInst %float %glsl Exp2 %cei
          %s = OpFMul %float %float_cell %ex2
         %ss = OpFMul %float %s %s
'''
for k in range(3):
    body += f'''       %d{k} = OpFDiv %float %f{k} %s
      %dc{k} = OpExtInst %float %glsl NClamp %d{k} %float_nbig %float_big
      %fl{k} = OpExtInst %float %glsl Floor %dc{k}
      %ci{k} = OpConvertFToS %int %fl{k}
      %cu{k} = OpBitcast %uint %ci{k}
      %cm{k} = OpIMul %uint %cu{k} %uint_h{k}
'''
body += '''       %x01 = OpBitwiseXor %uint %cm0 %cm1
       %seed = OpBitwiseXor %uint %x01 %cm2
        %p1 = OpIMul %uint %seed %uint_pcg
        %p2 = OpIAdd %uint %p1 %uint_inc
        %p3 = OpShiftRightLogical %uint %p2 %uint_28
        %p4 = OpIAdd %uint %p3 %uint_4
        %p5 = OpShiftRightLogical %uint %p2 %p4
        %p6 = OpBitwiseXor %uint %p5 %p2
        %p7 = OpIMul %uint %p6 %uint_xmul
        %p8 = OpShiftRightLogical %uint %p7 %uint_22
        %p9 = OpBitwiseXor %uint %p8 %p7
         %u = OpConvertUToF %float %p9
        %u1 = OpFMul %float %u %float_2n32
       %den = OpFMul %float %float_nu0 %ss
        %pc = OpExtInst %float %glsl NMin %den %float_1
        %lt = OpFOrdLessThan %bool %u1 %pc
         %g = OpSelect %float %lt %float_1 %float_0
       ; --- and the miss paint, so the magenta arm is compiled too -------
        %mr = OpSelect %float %hit %float_1 %float_mr
        %mg = OpSelect %float %hit %float_1 %float_mg
        %mb = OpSelect %float %hit %float_1 %float_mb
        %r0 = OpFMul %float %g %mr
        %r1 = OpFMul %float %g %mg
        %r2 = OpFMul %float %g %mb
        %px = OpCompositeConstruct %v4float %r0 %r1 %r2 %float_1
        %im = OpLoad %img %out
               OpImageWrite %im %coord %px
               OpReturn
               OpFunctionEnd
'''
open(os.path.join(w, 'go.spvasm'), 'w').write(head + body)
PYGEN
spirv-as --target-env spv1.4 "$w/go.spvasm" -o "$w/go.spv" || {
    echo "selftest: spirv-as failed on the synthetic object-space module" >&2; exit 1; }
spirv-val --target-env vulkan1.4 "$w/go.spv" || {
    echo "selftest: spirv-val failed on the synthetic object-space module" >&2; exit 1; }

# One stand-in raygen per patched id -- what the "application" (vkd3d-proton)
# creates. It carries only the dxil identity string; the layer replaces its
# bytes with the rung's real ~300 KB module. Each also gets a byte-distinct
# fallback twin in swaps.gofb/ so a reject can be seen to land on the NEXT
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
                           ('fb', 13, os.path.join(w, 'lay', 'swaps.gofb',
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
 * module per patched id, each of which the layer swaps for the rung's real
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
    const char *spv = argc>1 ? argv[1] : "go.spv";
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
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_glintobjtest \
        CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" \
        "$@" "$w/st" "$w/go.spv" "${STAND[@]}" >"$log.out" 2>&1
}
has() { grep -q -- "$2" "$1"; }

echo "glintobj layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
echo "10 patched ids: ${IDS[*]}"
echo "${#RQIDS[@]} of 12 base raygens already carry a ray query (101's ear glow)"
echo

# ---- case A: the layer supplies ray query the app never asked for ----------
ln -sfn "$MOD_DIR/swaps.glintobj" "$w/lay/swaps.gorung"
run "$w/a.log" gorung,gofb env; ra=$?
echo "case A -- the layer enables VK_KHR_ray_query and serves glintobj"
sed -n '1,4p' "$w/a.log.out" | sed 's/^/    /'
chk "probe exits 0"                             "$([[ $ra -eq 0 ]] && echo 1 || echo 0)"
chk "layer enabled VK_KHR_ray_query"            "$(b has "$w/a.log" '"ev":"rayq","action":"enabled"')"
chk "synthetic object-space module accepted"    "$(b grep -q "go.spv.*-> 0" "$w/a.log.out")"
chk "...and its RT PIPELINE links (the driver LOWERED WorldToObject: mat4v3 by value, 4 column extracts, the affine, the selects)" \
    "$(b grep -q 'vkCreateRayTracingPipelinesKHR -> 0' "$w/a.log.out")"
chk "no rayq_reject"                            "$(bn has "$w/a.log" 'rayq_reject')"
chk "no rt_pipeline_failed"                     "$(bn has "$w/a.log" 'rt_pipeline_failed')"
echo

# ---- case B: the real ~300 KB raygens, served through the layer ------------
echo "case B -- every rung's real raygens, served by the overlay, on the driver"
for rung in "${RUNGS[@]}"; do
    ln -sfn "$MOD_DIR/swaps.$rung" "$w/lay/swaps.gorung"
    run "$w/b_$rung.log" gorung,gofb env; rb=$?
    chk "$rung: probe exits 0, no served module refused" \
        "$([[ $rb -eq 0 ]] && echo 1 || echo 0)"
    nhit=0
    for h in "${IDS[@]}"; do
        sz=$(stat -c%s "$MOD_DIR/swaps.$rung/$h.rgs_reference_main.spv")
        grep -q "\"ev\":\"swap_load\".*swaps.gorung/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/b_$rung.log" \
          && grep -q "\"id\":\"$h.rgs_reference_main\".*\"swap\":\"HIT\",\"result\":0" "$w/b_$rung.log" \
          && nhit=$((nhit+1))
    done
    chk "$rung: 10 of 10 real raygens served at their shipped size and accepted (got $nhit)" \
        "$([[ $nhit -eq 10 ]] && echo 1 || echo 0)"
done
echo

# ---- case C: the reject guard falls through to the NEXT OVERLAY ------------
ln -sfn "$MOD_DIR/swaps.glintobj" "$w/lay/swaps.gorung"
run "$w/c.log" gorung,gofb env CALLISTO_RAYQ_DISABLE=1; rc=$?
echo "case C -- CALLISTO_RAYQ_DISABLE=1: reject glintobj, fall through to swaps.gofb/"
chk "probe still exits 0 (degrades, does not break)" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
chk "layer skipped ray query, reason env_disabled" \
    "$(b has "$w/c.log" '"ev":"rayq","action":"skipped","reason":"env_disabled"')"
nrej=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/c.log")
chk "all 10 patched raygens rejected with action next_overlay (got $nrej)" \
    "$([[ $nrej -eq 10 ]] && echo 1 || echo 0)"
nfb=0
for h in "${IDS[@]}"; do
    sz=$(stat -c%s "$w/lay/swaps.gofb/$h.rgs_reference_main.spv")
    grep -q "\"ev\":\"swap_load\".*swaps.gofb/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/c.log" \
      && nfb=$((nfb+1))
done
chk "and all 10 fell through to the NEXT OVERLAY, not to vanilla (got $nfb)" \
    "$([[ $nfb -eq 10 ]] && echo 1 || echo 0)"
# Scoped to rgs_reference_main on purpose: the synthetic module's own identity
# has no swap file in either overlay, so it legitimately logs swap:none.
chk "no PATCHED module went vanilla" \
    "$(bn grep -q '"id":"[0-9a-f]*\.rgs_reference_main".*"swap":"none"' "$w/c.log")"
echo

# ---- case D: the CONTROL needs ray query too, because the BASE does --------
# This is the case that differs from `102`'s: contact-rq's k=0 control carried
# no query at all, so nothing was rejected. glintobj-ctl is byte-identical to a
# base that already runs `101`'s ear-glow queries, so it is rejected in exactly
# the same way -- which is the proof that this feature adds NO new layer
# requirement. A rung that survived here while the base did not would mean the
# splice had somehow REMOVED a query.
ln -sfn "$MOD_DIR/swaps.glintobj-ctl" "$w/lay/swaps.gorung"
run "$w/d.log" gorung,gofb env CALLISTO_RAYQ_DISABLE=1; rd=$?
echo "case D -- the CONTROL under the same guard: it is the base, so it is rejected too"
chk "probe exits 0"                               "$([[ $rd -eq 0 ]] && echo 1 || echo 0)"
nctl=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/d.log")
chk "the control is rejected on the SAME ${#RQIDS[@]} raygens as the base carries queries (got $nctl)" \
    "$([[ $nctl -eq ${#RQIDS[@]} ]] && echo 1 || echo 0)"
chk "so glintobj adds NO ray-query requirement the base did not already have" \
    "$([[ $nctl -eq $nrej ]] && echo 1 || echo 0)"
echo

rm -f "$w/lay/swaps.gorung"
echo "=== $ok passed, $bad failed$( ((skip)) && echo ", $skip skipped")"
exit $(( bad ? 1 : 0 ))
