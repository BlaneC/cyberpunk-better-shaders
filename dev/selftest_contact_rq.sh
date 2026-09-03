#!/usr/bin/env bash
# contact-rq LAYER self-test -- the on-device half of handoff/102.
#
# ./dev/build_contact_rq.sh gates the four rungs entirely offline. spirv-val is
# NOT a driver: it never lowers four OpRayQueryInitializeKHR in a row, it does
# not care whether a driver accepts ray flags 517 with no cull bit set, and it
# has no opinion on a raygen that both traces rays (the engine's own) and runs
# ray queries (ours). This script answers the three questions only a real
# Vulkan device can:
#
#   1. does the layer put VK_KHR_ray_query on the VkDevice when the
#      application never asked for it (vkd3d-proton never does), so a served
#      contact-rq raygen can link at all?
#   2. does the driver COMPILE the contact splice shape -- flags 517, FOUR
#      Initialize/Proceed/committed-type triples, NO committed-T getter, the
#      branch-free Duff basis, the launch-id hash and its Cos/Sin, and the
#      1/K average -- inside a raygen that is then built into an RT pipeline?
#   3. do the REAL ~300 KB patched raygens of all four rungs survive
#      vkCreateShaderModule when served THROUGH THE LAYER by the same
#      first-file-wins overlay path the game uses -- and does the reject guard
#      fall through to the next overlay (not to vanilla) when ray query is
#      unavailable?
#
#   ./dev/selftest_contact_rq.sh          # everything; no game involved
#
# NEW FILE on purpose: dev/selftest_earglow_rq.sh (101) and
# dev/patch_rayq.sh --selftest (98) are not touched. Run all three.
#
# Loader note, inherited from dev/patch_rayq.sh and worth repeating because
# getting it wrong makes every result a lie: the layer installs as an IMPLICIT
# layer and the loader dedupes implicit layers BY NAME, so VK_ADD_LAYER_PATH
# pointed at a fresh build still binds the INSTALLED .so. The manifest below
# therefore names the test copy VK_LAYER_CALLISTO_contacttest.
#
# Overlay fixtures are SYMLINKS to swaps.<rung>/, never copies: the bytes the
# driver is handed are literally the shipped bytes this repo just gated.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
RUNGS=(contact-rq-ctl contact-rq-hit contact-rq contact-rq-8)

ok=0; bad=0; skip=0
chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
        else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
b()  { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
# Separate negated form on purpose: `b ! cmd` cannot work -- `!` is a shell
# keyword, not a command, so it resolves to "command not found" and returns 0
# for BOTH outcomes.
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
mkdir -p "$w/lay" "$w/lay/swaps.crfb" "$w/stand"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/contacttest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_contacttest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the contact-rq self-test"
    }
}
EOJ

# ------------------------------------------------------------------ fixtures
# The painted ids come from the shipped rung itself, not from a list typed
# here: a hardcoded list would keep passing after the rung stopped painting
# one of them. contact-rq reaches ALL TWELVE (88 sec 4's anchor), unlike 101.
mapfile -t IDS < <(cd "$MOD_DIR/swaps.contact-rq" &&
    for f in *.rgs_reference_main.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.contact-rq-ctl/$f" || echo "${f%%.*}"
    done | sort)
(( ${#IDS[@]} == 12 )) || { echo "selftest: expected 12 painted ids, got ${#IDS[@]}" >&2; exit 1; }

# The synthetic contact raygen: the splice shape in miniature, with every
# operand the driver could constant-fold away made dynamic off the launch id,
# so a "compiles" result cannot be a dead-code result. The tap coefficients
# come from patch_contact_rq.taps(4) -- the same function the rungs were built
# with, imported, not retyped.
python3 - "$w" "$MOD_DIR/dev" <<'PYGEN' || { echo "selftest: could not emit the synthetic module" >&2; exit 1; }
import os, sys, math
w = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from patch_contact_rq import taps, FLAGS, TMIN, TMAX, EPS_N, H_A, H_B, H_C
T = taps(4)
head = f'''               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
       %glsl = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "cccccccccccccccc.?contacttest@@YAXXZ.dxil"
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
     %uint_8 = OpConstant %uint 8
    %uint_39 = OpConstant %uint 39
 %uint_flags = OpConstant %uint {FLAGS}
    %uint_ha = OpConstant %uint {H_A}
    %uint_hb = OpConstant %uint {H_B}
    %uint_hc = OpConstant %uint {H_C}
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
   %float_n1 = OpConstant %float -1
 %float_tmin = OpConstant %float {TMIN}
 %float_tmax = OpConstant %float {TMAX}
  %float_eps = OpConstant %float {EPS_N}
 %float_invk = OpConstant %float {1.0/len(T)}
%float_scale = OpConstant %float {2.0*math.pi/16777216.0}
   %float_k  = OpConstant %float 0.850000024
      %coord = OpConstantComposite %v2uint %uint_0 %uint_0
'''
for j, (cx, cy, cz) in enumerate(T):
    head += f'   %float_x{j} = OpConstant %float {cx}\n'
    head += f'   %float_y{j} = OpConstant %float {cy}\n'
    head += f'   %float_z{j} = OpConstant %float {cz}\n'
body = '''       %main = OpFunction %void None %3
          %5 = OpLabel
          %q = OpVariable %_ptr_Function_rq Function
         %pl = OpAccessChain %_ptr_Input_uint %lid %uint_0
         %lx = OpLoad %uint %pl
        %pl2 = OpAccessChain %_ptr_Input_uint %lid %uint_1
         %ly = OpLoad %uint %pl2
         %fv = OpConvertUToF %float %lx
         %ga = OpBitwiseAnd %uint %lx %uint_1
       %gate = OpINotEqual %bool %ga %uint_0
       %mask = OpSelect %uint %gate %uint_39 %uint_0
       %nraw = OpCompositeConstruct %v3float %fv %float_0 %float_1
        %lvv = OpCompositeConstruct %v3float %float_0 %float_1 %float_0
       %nsel = OpSelect %v3float %gate %nraw %lvv
         %nu = OpExtInst %v3float %glsl Normalize %nsel
        %pre = OpCompositeConstruct %v3float %fv %fv %fv
         %ne = OpVectorTimesScalar %v3float %nu %float_eps
        %org = OpFAdd %v3float %pre %ne
         %h1 = OpIMul %uint %lx %uint_ha
         %h2 = OpIMul %uint %ly %uint_hb
         %h3 = OpBitwiseXor %uint %h1 %h2
         %h4 = OpIMul %uint %h3 %uint_hc
         %h5 = OpShiftRightLogical %uint %h4 %uint_8
         %hf = OpConvertUToF %float %h5
        %psi = OpFMul %float %hf %float_scale
        %cps = OpExtInst %float %glsl Cos %psi
        %sps = OpExtInst %float %glsl Sin %psi
         %nx = OpCompositeExtract %float %nu 0
         %ny = OpCompositeExtract %float %nu 1
         %nz = OpCompositeExtract %float %nu 2
         %zp = OpFOrdGreaterThanEqual %bool %nz %float_0
         %sg = OpSelect %float %zp %float_1 %float_n1
         %dn = OpFAdd %float %sg %nz
         %aa = OpFDiv %float %float_n1 %dn
        %nxy = OpFMul %float %nx %ny
         %bb = OpFMul %float %nxy %aa
        %nxx = OpFMul %float %nx %nx
        %nxa = OpFMul %float %nxx %aa
        %t0a = OpFMul %float %sg %nxa
         %t0 = OpFAdd %float %float_1 %t0a
         %t1 = OpFMul %float %sg %bb
        %t2a = OpFMul %float %sg %nx
         %t2 = OpFNegate %float %t2a
         %Tv = OpCompositeConstruct %v3float %t0 %t1 %t2
        %nyy = OpFMul %float %ny %ny
        %nya = OpFMul %float %nyy %aa
         %b1 = OpFAdd %float %sg %nya
         %b2 = OpFNegate %float %ny
         %Bv = OpCompositeConstruct %v3float %bb %b1 %b2
         %tc = OpVectorTimesScalar %v3float %Tv %cps
         %bs = OpVectorTimesScalar %v3float %Bv %sps
         %Tr = OpFAdd %v3float %tc %bs
         %ts = OpVectorTimesScalar %v3float %Tv %sps
         %bc = OpVectorTimesScalar %v3float %Bv %cps
         %Br = OpFSub %v3float %bc %ts
          %a = OpLoad %as %accel
'''
prev = None
for j in range(len(T)):
    body += f'''       %d{j}a = OpVectorTimesScalar %v3float %Tr %float_x{j}
       %d{j}b = OpVectorTimesScalar %v3float %Br %float_y{j}
       %d{j}c = OpVectorTimesScalar %v3float %nu %float_z{j}
       %d{j}d = OpFAdd %v3float %d{j}a %d{j}b
        %d{j} = OpFAdd %v3float %d{j}d %d{j}c
               OpRayQueryInitializeKHR %q %a %uint_flags %mask %org %float_tmin %d{j} %float_tmax
       %pr{j} = OpRayQueryProceedKHR %bool %q
       %ty{j} = OpRayQueryGetIntersectionTypeKHR %uint %q %uint_1
       %hi{j} = OpINotEqual %bool %ty{j} %uint_0
       %cj{j} = OpSelect %float %hi{j} %float_1 %float_0
'''
    if prev is None:
        prev = f'%cj{j}'
    else:
        body += f'      %ac{j} = OpFAdd %float {prev} %cj{j}\n'
        prev = f'%ac{j}'
body += f'''        %occ = OpFMul %float {prev} %float_invk
         %og = OpSelect %float %gate %occ %float_0
        %ok2 = OpFMul %float %og %float_k
        %fac = OpFSub %float %float_1 %ok2
         %px = OpCompositeConstruct %v4float %fac %fac %fac %float_1
         %im = OpLoad %img %out
               OpImageWrite %im %coord %px
               OpReturn
               OpFunctionEnd
'''
open(os.path.join(w, 'cr.spvasm'), 'w').write(head + body)
PYGEN
spirv-as --target-env spv1.4 "$w/cr.spvasm" -o "$w/cr.spv" || {
    echo "selftest: spirv-as failed on the synthetic contact module" >&2; exit 1; }
spirv-val --target-env vulkan1.4 "$w/cr.spv" || {
    echo "selftest: spirv-val failed on the synthetic contact module" >&2; exit 1; }

# One stand-in raygen per painted id -- what the "application" (vkd3d-proton)
# creates. It carries only the dxil identity string; the layer replaces its
# bytes with the rung's real ~300 KB module. Each also gets a byte-distinct
# fallback twin in swaps.crfb/ so a reject can be seen to land on the NEXT
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
                           ('fb', 13, os.path.join(w, 'lay', 'swaps.crfb',
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
    const char *spv = argc>1 ? argv[1] : "cr.spv";
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
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_contacttest \
        CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" \
        "$@" "$w/st" "$w/cr.spv" "${STAND[@]}" >"$log.out" 2>&1
}
has() { grep -q -- "$2" "$1"; }

echo "contact-rq layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
echo "12 painted ids: ${IDS[*]}"
echo

# ---- case A: the layer supplies ray query the app never asked for ----------
ln -sfn "$MOD_DIR/swaps.contact-rq" "$w/lay/swaps.crrung"
run "$w/a.log" crrung,crfb env; ra=$?
echo "case A -- the layer enables VK_KHR_ray_query and serves contact-rq"
sed -n '1,4p' "$w/a.log.out" | sed 's/^/    /'
chk "probe exits 0"                             "$([[ $ra -eq 0 ]] && echo 1 || echo 0)"
chk "layer enabled VK_KHR_ray_query"            "$(b has "$w/a.log" '"ev":"rayq","action":"enabled"')"
chk "synthetic contact module accepted"         "$(b grep -q "cr.spv.*-> 0" "$w/a.log.out")"
chk "...and its RT PIPELINE links (the driver compiled 4x flags 517 + the Duff basis)" \
    "$(b grep -q 'vkCreateRayTracingPipelinesKHR -> 0' "$w/a.log.out")"
chk "no rayq_reject"                            "$(bn has "$w/a.log" 'rayq_reject')"
chk "no rt_pipeline_failed"                     "$(bn has "$w/a.log" 'rt_pipeline_failed')"
echo

# ---- case B: the real ~300 KB raygens, served through the layer ------------
echo "case B -- every rung's real raygens, served by the overlay, on the driver"
for rung in "${RUNGS[@]}"; do
    ln -sfn "$MOD_DIR/swaps.$rung" "$w/lay/swaps.crrung"
    run "$w/b_$rung.log" crrung,crfb env; rb=$?
    chk "$rung: probe exits 0, no served module refused" \
        "$([[ $rb -eq 0 ]] && echo 1 || echo 0)"
    nhit=0
    for h in "${IDS[@]}"; do
        sz=$(stat -c%s "$MOD_DIR/swaps.$rung/$h.rgs_reference_main.spv")
        grep -q "\"ev\":\"swap_load\".*swaps.crrung/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/b_$rung.log" \
          && grep -q "\"id\":\"$h.rgs_reference_main\".*\"swap\":\"HIT\",\"result\":0" "$w/b_$rung.log" \
          && nhit=$((nhit+1))
    done
    chk "$rung: 12 of 12 real raygens served at their shipped size and accepted (got $nhit)" \
        "$([[ $nhit -eq 12 ]] && echo 1 || echo 0)"
done
echo

# ---- case C: the reject guard falls through to the NEXT OVERLAY ------------
ln -sfn "$MOD_DIR/swaps.contact-rq" "$w/lay/swaps.crrung"
run "$w/c.log" crrung,crfb env CALLISTO_RAYQ_DISABLE=1; rc=$?
echo "case C -- CALLISTO_RAYQ_DISABLE=1: reject contact-rq, fall through to swaps.crfb/"
chk "probe still exits 0 (degrades, does not break)" "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
chk "layer skipped ray query, reason env_disabled" \
    "$(b has "$w/c.log" '"ev":"rayq","action":"skipped","reason":"env_disabled"')"
nrej=$(grep -c '"ev":"rayq_reject".*"action":"next_overlay"' "$w/c.log")
chk "all 12 painted raygens rejected with action next_overlay (got $nrej)" \
    "$([[ $nrej -eq 12 ]] && echo 1 || echo 0)"
nfb=0
for h in "${IDS[@]}"; do
    sz=$(stat -c%s "$w/lay/swaps.crfb/$h.rgs_reference_main.spv")
    grep -q "\"ev\":\"swap_load\".*swaps.crfb/$h.rgs_reference_main.spv\",\"size\":$sz}" "$w/c.log" \
      && nfb=$((nfb+1))
done
chk "and all 12 fell through to the NEXT OVERLAY, not to vanilla (got $nfb)" \
    "$([[ $nfb -eq 12 ]] && echo 1 || echo 0)"
# Scoped to rgs_reference_main on purpose: the synthetic module's own identity
# has no swap file in either overlay, so it legitimately logs swap:none.
chk "no PAINTED module went vanilla" \
    "$(bn grep -q '"id":"[0-9a-f]*\.rgs_reference_main".*"swap":"none"' "$w/c.log")"
echo

# ---- case D: the control carries no ray query at all ----------------------
ln -sfn "$MOD_DIR/swaps.contact-rq-ctl" "$w/lay/swaps.crrung"
run "$w/d.log" crrung,crfb env CALLISTO_RAYQ_DISABLE=1; rd=$?
echo "case D -- the k=0 control under the same guard: nothing to reject"
chk "probe exits 0"                               "$([[ $rd -eq 0 ]] && echo 1 || echo 0)"
chk "NO rayq_reject on the control"               "$(bn has "$w/d.log" 'rayq_reject')"
nctl=$(grep -c '"swap":"HIT","result":0' "$w/d.log")
chk "all 12 control raygens served anyway (got $nctl)" \
    "$([[ $nctl -eq 12 ]] && echo 1 || echo 0)"
echo

rm -f "$w/lay/swaps.crrung"
echo "=== $ok passed, $bad failed$( ((skip)) && echo ", $skip skipped")"
exit $(( bad ? 1 : 0 ))
