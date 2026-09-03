#!/usr/bin/env bash
# Ray-query LAYER self-test -- the on-device half of Unlock 1
# (handoff/98-RAYQUERY.md). The shader half is built and gated entirely
# offline by ./dev/build_rayq.sh; this script proves the three things only a
# real Vulkan device can answer:
#
#   1. does the layer actually get VK_KHR_ray_query onto the VkDevice when
#      the application never asked for it (vkd3d-proton never does), and
#      does a module declaring OpCapability RayQueryKHR then link?
#   2. does the reject guard fire when the extension is NOT enabled, and does
#      it fall through to the NEXT OVERLAY rather than to vanilla?
#      (GOTCHAS: "an overlay reject must fall through" -- serving a vanilla
#      raygen on top of a patched compute set is a worse failure than serving
#      the base image.)
#   3. does the AS journal (Stage 2a) actually observe an acceleration
#      structure being created and its device address queried?
#   4. does the driver COMPILE each committed-intersection getter -- and each
#      FOLD -- the rungs use? spirv-val is not a driver. Case E links one
#      raygen per getter/fold
#      (sbt / geom / the ObjectToWorld matrix) and then feeds a real ~300 KB
#      patched raygen from each rung to vkCreateShaderModule.
#
#   ./dev/patch_rayq.sh --selftest     # all of the above, no game involved
#   ./dev/patch_rayq.sh --help
#
# This is a NEW file on purpose: dev/patch_ser.sh is shared machinery and is
# not touched. The SER self-test still passes unchanged -- run both.
#
# Loader note, inherited from patch_ser.sh and non-obvious enough to repeat:
# the layer is installed as an IMPLICIT layer and the loader dedupes implicit
# layers by NAME, so VK_ADD_LAYER_PATH pointed at a fresh build still binds
# the INSTALLED .so. The manifest written below therefore names the copy
# VK_LAYER_CALLISTO_rayqtest. Without that rename this test silently measures
# the old binary and every result is a lie.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"

usage() { sed -n '2,30p' "$0"; }

selftest() {
    local w
    w="$(mktemp -d)" || return 1
    trap 'rm -rf "$w"' RETURN

    for t in spirv-as spirv-val gcc python3; do
        command -v "$t" >/dev/null || { echo "selftest: need $t" >&2; return 1; }
    done
    [[ -f /usr/include/vulkan/vulkan.h ]] || {
        echo "selftest: need Vulkan headers (/usr/include/vulkan/vulkan.h)" >&2; return 1; }

    ( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
        echo "selftest: layer build failed" >&2; cat "$w/build.log" >&2; return 1; }
    mkdir -p "$w/lay/swaps.rayqtest" "$w/lay/swaps.fallback"
    cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
    cat > "$w/lay/rayqtest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_rayqtest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the ray-query self-test"
    }
}
EOJ

    # Three raygens sharing one synthetic DXIL identity:
    #   plain.spv  what the "application" creates (stands in for vkd3d-proton)
    #   rq.spv     the ray-query module, in the FIRST overlay
    #   fb.spv     a plain module in the SECOND overlay -- the thing a reject
    #              must fall through to. It is byte-distinct from plain.spv so
    #              a HIT cannot be confused with no swap at all.
    cat > "$w/plain.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid
        %str = OpString "bbbbbbbbbbbbbbbb.?rayqtest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
     %v3uint = OpTypeVector %uint 3
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
        %lid = OpVariable %_ptr_Input_v3uint Input
       %main = OpFunction %void None %3
          %5 = OpLabel
               OpReturn
               OpFunctionEnd
EOA
    # The ray query in miniature, with the same shape the real splice emits:
    # a Function-storage OpTypeRayQueryKHR variable, Initialize with flags
    # 517 (Opaque | TerminateOnFirstHit | SkipAABBs), ONE Proceed, then the
    # committed getters. The AS is a null descriptor here -- this test asks
    # whether the module LINKS, not what it hits.
    cat > "$w/rq.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpCapability RayQueryKHR
               OpCapability RayTraversalPrimitiveCullingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_KHR_ray_query"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid %accel %out
        %str = OpString "bbbbbbbbbbbbbbbb.?rayqtest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
               OpDecorate %accel DescriptorSet 0
               OpDecorate %accel Binding 0
               OpDecorate %out DescriptorSet 0
               OpDecorate %out Binding 1
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
      %float = OpTypeFloat 32
     %v3uint = OpTypeVector %uint 3
    %v3float = OpTypeVector %float 3
    %v4float = OpTypeVector %float 4
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
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
   %uint_255 = OpConstant %uint 255
   %uint_517 = OpConstant %uint 517
    %float_0 = OpConstant %float 0
    %float_1 = OpConstant %float 1
 %float_1000 = OpConstant %float 1000
       %orig = OpConstantComposite %v3float %float_0 %float_0 %float_0
        %dir = OpConstantComposite %v3float %float_0 %float_0 %float_1
      %v2int = OpTypeVector %uint 2
       %coord = OpConstantComposite %v2int %uint_0 %uint_0
       %bool = OpTypeBool
       %main = OpFunction %void None %3
          %5 = OpLabel
          %q = OpVariable %_ptr_Function_rq Function
          %a = OpLoad %as %accel
               OpRayQueryInitializeKHR %q %a %uint_517 %uint_255 %orig %float_0 %dir %float_1000
          %p = OpRayQueryProceedKHR %bool %q
          %t = OpRayQueryGetIntersectionTypeKHR %uint %q %uint_1
          %i = OpRayQueryGetIntersectionInstanceIdKHR %uint %q %uint_1
          %c = OpRayQueryGetIntersectionInstanceCustomIndexKHR %uint %q %uint_1
          %m = OpRayQueryGetIntersectionPrimitiveIndexKHR %uint %q %uint_1
         %s0 = OpIAdd %uint %t %i
         %s1 = OpIAdd %uint %s0 %c
         %s2 = OpIAdd %uint %s1 %m
         %f0 = OpConvertUToF %float %s2
         %px = OpCompositeConstruct %v4float %f0 %f0 %f0 %float_1
         %im = OpLoad %img %out
               OpImageWrite %im %coord %px
               OpReturn
               OpFunctionEnd
EOA
    cat > "$w/fb.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid
        %str = OpString "bbbbbbbbbbbbbbbb.?rayqtest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
     %v3uint = OpTypeVector %uint 3
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
        %lid = OpVariable %_ptr_Input_v3uint Input
     %uint_0 = OpConstant %uint 0
     %uint_7 = OpConstant %uint 7
%_ptr_Input_uint = OpTypePointer Input %uint
       %main = OpFunction %void None %3
          %5 = OpLabel
          %p = OpAccessChain %_ptr_Input_uint %lid %uint_0
          %v = OpLoad %uint %p
          %h = OpBitwiseAnd %uint %v %uint_7
               OpReturn
               OpFunctionEnd
EOA
    # The three sec-13 getters, each in a module of its own -- derived from
    # rq.spvasm above so the ONLY difference is the readback, and each folded
    # into the value the module writes so nothing can dead-code it away. A
    # module per getter, rather than one module carrying all three, so a driver
    # that refuses one of them names which one.
    python3 - "$w" <<'PYGEN'
import os, sys
w = sys.argv[1]
base = open(os.path.join(w, 'rq.spvasm')).read()
VAR = {
    'sbt':  ('', '%gv = OpRayQueryGetIntersectionInstanceShaderBindingTableRecordOffsetKHR %uint %q %uint_1'),
    'geom': ('', '%gv = OpRayQueryGetIntersectionGeometryIndexKHR %uint %q %uint_1'),
    # the matrix getter, folded exactly as patch_rayq.py folds it: column 3,
    # x/y/z, OpBitcast to uint, XOR. Raw bits, no quantisation.
    'xf':   ('%mat4v3 = OpTypeMatrix %v3float 4',
             '\n'.join([
                 '%xm = OpRayQueryGetIntersectionObjectToWorldKHR %mat4v3 %q %uint_1',
                 '%xc = OpCompositeExtract %v3float %xm 3',
                 '%xx = OpCompositeExtract %float %xc 0',
                 '%xy = OpCompositeExtract %float %xc 1',
                 '%xz = OpCompositeExtract %float %xc 2',
                 '%bx = OpBitcast %uint %xx',
                 '%by = OpBitcast %uint %xy',
                 '%bz = OpBitcast %uint %xz',
                 '%b1 = OpBitwiseXor %uint %bx %by',
                 '%gv = OpBitwiseXor %uint %b1 %bz'])),
    # 98 sec 14. The driver question these two add over 'xf' is OpConvertFToS
    # applied to a ray-query result inside a raygen -- spirv-val says it is
    # well-formed, only a driver says it compiles. 'xfw' additionally carries
    # the world-offset ADD; here the offset is a constant triple rather than a
    # uniform load, because what is under test is the FOLD SHAPE, not the
    # descriptor -- the descriptor is covered by the real ~300 KB raygen from
    # swaps.hunt-rayq-pxfw that this same run hands to vkCreateShaderModule.
    'xfq':  ('%mat4v3 = OpTypeMatrix %v3float 4\n     %int = OpTypeInt 32 1\n'
             '  %float_100 = OpConstant %float 100',
             '\n'.join([
                 '%xm = OpRayQueryGetIntersectionObjectToWorldKHR %mat4v3 %q %uint_1',
                 '%xc = OpCompositeExtract %v3float %xm 3',
                 '%xx = OpCompositeExtract %float %xc 0',
                 '%xy = OpCompositeExtract %float %xc 1',
                 '%xz = OpCompositeExtract %float %xc 2',
                 '%mx = OpFMul %float %xx %float_100',
                 '%my = OpFMul %float %xy %float_100',
                 '%mz = OpFMul %float %xz %float_100',
                 '%qx = OpConvertFToS %int %mx',
                 '%qy = OpConvertFToS %int %my',
                 '%qz = OpConvertFToS %int %mz',
                 '%bx = OpBitcast %uint %qx',
                 '%by = OpBitcast %uint %qy',
                 '%bz = OpBitcast %uint %qz',
                 '%b1 = OpBitwiseXor %uint %bx %by',
                 '%gv = OpBitwiseXor %uint %b1 %bz'])),
    'xfw':  ('%mat4v3 = OpTypeMatrix %v3float 4\n     %int = OpTypeInt 32 1\n'
             '  %float_100 = OpConstant %float 100\n'
             '  %float_7 = OpConstant %float 7',
             '\n'.join([
                 '%xm = OpRayQueryGetIntersectionObjectToWorldKHR %mat4v3 %q %uint_1',
                 '%xc = OpCompositeExtract %v3float %xm 3',
                 '%xx0 = OpCompositeExtract %float %xc 0',
                 '%xy0 = OpCompositeExtract %float %xc 1',
                 '%xz0 = OpCompositeExtract %float %xc 2',
                 '%xx = OpFAdd %float %float_7 %xx0',
                 '%xy = OpFAdd %float %float_7 %xy0',
                 '%xz = OpFAdd %float %float_7 %xz0',
                 '%mx = OpFMul %float %xx %float_100',
                 '%my = OpFMul %float %xy %float_100',
                 '%mz = OpFMul %float %xz %float_100',
                 '%qx = OpConvertFToS %int %mx',
                 '%qy = OpConvertFToS %int %my',
                 '%qz = OpConvertFToS %int %mz',
                 '%bx = OpBitcast %uint %qx',
                 '%by = OpBitcast %uint %qy',
                 '%bz = OpBitcast %uint %qz',
                 '%b1 = OpBitwiseXor %uint %bx %by',
                 '%gv = OpBitwiseXor %uint %b1 %bz'])),
}
for tag, (ty, body) in VAR.items():
    s = base
    if ty:
        assert '%bool = OpTypeBool' in s
        s = s.replace('%bool = OpTypeBool', ty + '\n       %bool = OpTypeBool', 1)
    assert '%s0 = OpIAdd %uint %t %i' in s
    s = s.replace('%s0 = OpIAdd %uint %t %i',
                  body + '\n         %s0 = OpIAdd %uint %t %gv', 1)
    open(os.path.join(w, 'rq_%s.spvasm' % tag), 'w').write(s)
PYGEN
    for f in plain rq fb rq_sbt rq_geom rq_xf rq_xfq rq_xfw; do
        spirv-as --target-env spv1.4 "$w/$f.spvasm" -o "$w/$f.spv" || {
            echo "selftest: spirv-as failed on $f" >&2; return 1; }
        spirv-val --target-env vulkan1.4 "$w/$f.spv" || {
            echo "selftest: spirv-val failed on $f" >&2; return 1; }
    done
    cp -pf "$w/rq.spv" "$w/lay/swaps.rayqtest/bbbbbbbbbbbbbbbb.rayqtest.spv"
    cp -pf "$w/fb.spv" "$w/lay/swaps.fallback/bbbbbbbbbbbbbbbb.rayqtest.spv"

    # ---------------------------------------------------------------- probe
    cat > "$w/st.c" <<'EOC'
/* The same API calls the game makes -- create a device WITHOUT asking for
 * ray query, create a raygen, build an RT pipeline -- plus a top-level
 * acceleration structure whose device address is queried, which is the only
 * way to see the Stage 2a journal hooks fire without the game. */
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
/* Buffer helper for the AS-journal exercise. Soft-fails (returns 0) rather
 * than aborting the probe: a driver that will not give us a device-local
 * address-capable buffer must not turn the ray-query link test red. */
static VkDevice G_dev; static VkPhysicalDevice G_phys;
static int mkbuf(VkDeviceSize sz, VkBufferUsageFlags u,
                 VkBuffer *b, VkDeviceMemory *m) {
    VkBufferCreateInfo bci={VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bci.size=sz?sz:256; bci.usage=u|VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
    bci.sharingMode=VK_SHARING_MODE_EXCLUSIVE;
    if(vkCreateBuffer(G_dev,&bci,NULL,b)!=VK_SUCCESS) return 0;
    VkMemoryRequirements mr; vkGetBufferMemoryRequirements(G_dev,*b,&mr);
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(G_phys,&mp);
    uint32_t mt=UINT32_MAX;
    for(uint32_t i=0;i<mp.memoryTypeCount;i++)
        if((mr.memoryTypeBits&(1u<<i)) &&
           (mp.memoryTypes[i].propertyFlags&VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)){mt=i;break;}
    if(mt==UINT32_MAX) return 0;
    VkMemoryAllocateFlagsInfo mf={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO};
    mf.flags=VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
    VkMemoryAllocateInfo mai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    mai.pNext=&mf; mai.allocationSize=mr.size; mai.memoryTypeIndex=mt;
    if(vkAllocateMemory(G_dev,&mai,NULL,m)!=VK_SUCCESS) return 0;
    if(vkBindBufferMemory(G_dev,*b,*m,0)!=VK_SUCCESS) return 0;
    return 1;
}
static VkDeviceAddress bufaddr(VkBuffer b){
    VkBufferDeviceAddressInfo i={VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO};
    i.buffer=b; return vkGetBufferDeviceAddress(G_dev,&i);
}
int main(int argc, char **argv) {
    const char *spv = argc>1 ? argv[1] : "plain.spv";
    /* argv[2..] are create-only modules, e.g. real patched raygens -- one per
     * rung, so a rung whose getter the driver refuses names itself. */
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
    G_dev=dev; G_phys=phys;
    printf("device created with %u extensions requested by the app\n",dci.enabledExtensionCount);

    size_t n; uint32_t *code=slurp(spv,&n);
    VkShaderModuleCreateInfo smi={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smi.codeSize=n; smi.pCode=code;
    VkShaderModule sm; VkResult r=vkCreateShaderModule(dev,&smi,NULL,&sm);
    printf("vkCreateShaderModule(%s, %zu B) -> %d\n",spv,n,r);
    if(r!=VK_SUCCESS){printf("RESULT: module rejected\n");return 5;}
    for(int ai=2; ai<argc; ai++){
        size_t n2; uint32_t *c2=slurp(argv[ai],&n2);
        VkShaderModuleCreateInfo s2={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        s2.codeSize=n2; s2.pCode=c2;
        VkShaderModule m2; VkResult r2=vkCreateShaderModule(dev,&s2,NULL,&m2);
        printf("vkCreateShaderModule(real raygen %s, %zu B) -> %d\n",
               argv[ai],n2,r2);
        if(r2!=VK_SUCCESS)return 5;
    }
    /* The module above declares a descriptor set; give the pipeline a layout
     * that matches it, or creation fails for reasons unrelated to ray query. */
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

    /* ---- AS journal exercise (Stage 2a) ---- */
    PFN_vkCreateAccelerationStructureKHR fCreate=(PFN_vkCreateAccelerationStructureKHR)
        vkGetDeviceProcAddr(dev,"vkCreateAccelerationStructureKHR");
    PFN_vkGetAccelerationStructureDeviceAddressKHR fAddr=
        (PFN_vkGetAccelerationStructureDeviceAddressKHR)
        vkGetDeviceProcAddr(dev,"vkGetAccelerationStructureDeviceAddressKHR");
    if(fCreate&&fAddr){
        VkBufferCreateInfo bci={VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
        bci.size=4096;
        bci.usage=VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR
                 |VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
        bci.sharingMode=VK_SHARING_MODE_EXCLUSIVE;
        VkBuffer buf; CK(vkCreateBuffer(dev,&bci,NULL,&buf),"vkCreateBuffer");
        VkMemoryRequirements mr; vkGetBufferMemoryRequirements(dev,buf,&mr);
        VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(phys,&mp);
        uint32_t mt=UINT32_MAX;
        for(uint32_t i=0;i<mp.memoryTypeCount;i++)
            if((mr.memoryTypeBits&(1u<<i)) &&
               (mp.memoryTypes[i].propertyFlags&VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)){mt=i;break;}
        if(mt==UINT32_MAX){printf("FAIL no device-local memory type\n");return 4;}
        VkMemoryAllocateFlagsInfo mf={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO};
        mf.flags=VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
        VkMemoryAllocateInfo mai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        mai.pNext=&mf; mai.allocationSize=mr.size; mai.memoryTypeIndex=mt;
        VkDeviceMemory mem; CK(vkAllocateMemory(dev,&mai,NULL,&mem),"vkAllocateMemory");
        CK(vkBindBufferMemory(dev,buf,mem,0),"vkBindBufferMemory");
        VkAccelerationStructureCreateInfoKHR aci={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR};
        aci.buffer=buf; aci.offset=0; aci.size=1024;
        aci.type=VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
        VkAccelerationStructureKHR tlas;
        VkResult ra=fCreate(dev,&aci,NULL,&tlas);
        printf("vkCreateAccelerationStructureKHR(top, 1024 B) -> %d\n",(int)ra);
        if(ra==VK_SUCCESS){
            VkAccelerationStructureDeviceAddressInfoKHR adi=
                {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_DEVICE_ADDRESS_INFO_KHR};
            adi.accelerationStructure=tlas;
            VkDeviceAddress a1=fAddr(dev,&adi), a2=fAddr(dev,&adi);
            printf("as device address: 0x%llx (stable across two queries: %s)\n",
                   (unsigned long long)a1, a1==a2?"yes":"NO");
        }

        /* ---- the vkd3d-proton shape: CREATE generic, CLASSIFY at build ----
         * 98 sec 12.5: v1 of the journal took the type from the create info,
         * which vkd3d-proton always sets to GENERIC, so it never saw a TLAS.
         * Both structures below are created GENERIC and only the build info
         * says what they are -- which is the exact case that used to be
         * misread.  Nothing is submitted: the journal reads the CPU-side
         * structs at record time, so a recorded-and-abandoned command buffer
         * is enough and the GPU never touches the uninitialised scratch. */
        PFN_vkGetAccelerationStructureBuildSizesKHR fSizes=
            (PFN_vkGetAccelerationStructureBuildSizesKHR)
            vkGetDeviceProcAddr(dev,"vkGetAccelerationStructureBuildSizesKHR");
        PFN_vkCmdBuildAccelerationStructuresKHR fBuild=
            (PFN_vkCmdBuildAccelerationStructuresKHR)
            vkGetDeviceProcAddr(dev,"vkCmdBuildAccelerationStructuresKHR");
        VkCommandPool pool=VK_NULL_HANDLE; VkCommandBuffer cmd=VK_NULL_HANDLE;
        if(fSizes&&fBuild){
            VkCommandPoolCreateInfo pci={VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
            pci.queueFamilyIndex=0;
            CK(vkCreateCommandPool(dev,&pci,NULL,&pool),"vkCreateCommandPool");
            VkCommandBufferAllocateInfo cbi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
            cbi.commandPool=pool; cbi.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;
            cbi.commandBufferCount=1;
            CK(vkAllocateCommandBuffers(dev,&cbi,&cmd),"vkAllocateCommandBuffers");
            VkCommandBufferBeginInfo cbb={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
            CK(vkBeginCommandBuffer(cmd,&cbb),"vkBeginCommandBuffer");
            for(int pass=0;pass<3;pass++){
                int top = pass!=1;              /* TLAS, BLAS, TLAS again    */
                uint32_t prims = top?3:12;
                VkAccelerationStructureGeometryKHR ge=
                    {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR};
                VkBuffer ib; VkDeviceMemory im;
                if(!mkbuf(1<<16,
                    VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR,
                    &ib,&im)){printf("SKIP build exercise: no input buffer\n");break;}
                if(top){
                    ge.geometryType=VK_GEOMETRY_TYPE_INSTANCES_KHR;
                    ge.geometry.instances.sType=
                        VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR;
                    ge.geometry.instances.arrayOfPointers=VK_FALSE;
                    ge.geometry.instances.data.deviceAddress=bufaddr(ib);
                }else{
                    ge.geometryType=VK_GEOMETRY_TYPE_TRIANGLES_KHR;
                    ge.geometry.triangles.sType=
                        VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_TRIANGLES_DATA_KHR;
                    ge.geometry.triangles.vertexFormat=VK_FORMAT_R32G32B32_SFLOAT;
                    ge.geometry.triangles.vertexData.deviceAddress=bufaddr(ib);
                    ge.geometry.triangles.vertexStride=12;
                    ge.geometry.triangles.maxVertex=prims*3-1;
                    ge.geometry.triangles.indexType=VK_INDEX_TYPE_NONE_KHR;
                }
                VkAccelerationStructureBuildGeometryInfoKHR gi=
                    {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR};
                /* The build info carries the real type -- GENERIC is forbidden
                 * here by VUID-...-type-03654, which is precisely why the
                 * build is the only place the truth exists. */
                gi.type = top?VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR
                             :VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR;
                gi.flags=VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR;
                gi.mode=VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR;
                gi.geometryCount=1; gi.pGeometries=&ge;
                VkAccelerationStructureBuildSizesInfoKHR sz=
                    {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
                fSizes(dev,VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR,
                       &gi,&prims,&sz);
                VkDeviceSize asz=sz.accelerationStructureSize?sz.accelerationStructureSize:1024;
                VkDeviceSize ssz=sz.buildScratchSize?sz.buildScratchSize:1024;
                VkBuffer ab,sb; VkDeviceMemory am,sm;
                if(!mkbuf(asz,VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR,&ab,&am)
                 ||!mkbuf(ssz,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,&sb,&sm)){
                    printf("SKIP build exercise: no AS/scratch buffer\n");break;}
                VkAccelerationStructureCreateInfoKHR ci2=
                    {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR};
                ci2.buffer=ab; ci2.offset=0; ci2.size=asz;
                ci2.type=VK_ACCELERATION_STRUCTURE_TYPE_GENERIC_KHR;   /* <-- */
                VkAccelerationStructureKHR acc;
                if(fCreate(dev,&ci2,NULL,&acc)!=VK_SUCCESS){
                    printf("SKIP build exercise: generic create refused\n");break;}
                VkAccelerationStructureDeviceAddressInfoKHR ai=
                    {VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_DEVICE_ADDRESS_INFO_KHR};
                ai.accelerationStructure=acc; (void)fAddr(dev,&ai);
                gi.dstAccelerationStructure=acc;
                gi.scratchData.deviceAddress=bufaddr(sb);
                VkAccelerationStructureBuildRangeInfoKHR rg;
                memset(&rg,0,sizeof rg); rg.primitiveCount=prims;
                const VkAccelerationStructureBuildRangeInfoKHR *prg=&rg;
                fBuild(cmd,1,&gi,&prg);
                if(top) fBuild(cmd,1,&gi,&prg);   /* twice in one frame */
                printf("recorded %s build: created GENERIC, built as %s, prims=%u\n",
                       top?"TLAS(instances)":"BLAS(triangles)",
                       top?"top":"bottom",prims);
            }
            vkEndCommandBuffer(cmd);      /* recorded, deliberately NOT submitted */
        } else {
            printf("build entry points unavailable (sizes=%p build=%p)\n",
                   (void*)fSizes,(void*)fBuild);
        }
        /* The frame tick. There is no swapchain here, so vkQueuePresentKHR
         * never resolves and the journal's vkQueueSubmit fallback is what
         * ticks -- which is the branch that needs proving. */
        VkQueue qq; vkGetDeviceQueue(dev,0,0,&qq);
        for(int i=0;i<4;i++){
            VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO};
            vkQueueSubmit(qq,1,&si,VK_NULL_HANDLE);
        }
        vkQueueWaitIdle(qq);
    } else {
        printf("AS entry points unavailable (fCreate=%p fAddr=%p)\n",
               (void*)fCreate,(void*)fAddr);
    }
    vkDestroyDevice(dev,NULL);          /* makes the layer emit as_summary */
    printf("RESULT: OK\n");
    return 0;
}
EOC
    gcc -O1 -o "$w/st" "$w/st.c" -lvulkan 2>"$w/cc.err" || {
        echo "selftest: could not build the probe (need libvulkan-dev):" >&2
        sed -n '1,5p' "$w/cc.err" >&2; return 1; }

    # A real patched raygen, if one is parked, gets a create-only pass too:
    # the synthetic module is under a kilobyte and proves nothing about 290 KB.
    local real=""
    for cand in "$MOD_DIR/swaps.hunt-rayq-p" "$DEST/skin.set/hunt-rayq-p" \
                "$MOD_DIR/swaps.hunt-rayq" "$DEST/skin.set/hunt-rayq"; do
        real="$(ls "$cand"/*.rgs_reference_main.spv 2>/dev/null | head -1)"
        [[ -n "$real" ]] && break
    done
    # ...and one from each sec-13 rung. The synthetic modules above are under a
    # kilobyte; these are ~300 KB and carry the getter inside the real module's
    # 14 000 lines, which is the only version of the question that matters.
    local REALS=(); [[ -n "$real" ]] && REALS+=("$real")
    local NEWRUNGS=(hunt-rayq-psbt hunt-rayq-pgeom hunt-rayq-pxf
                    hunt-rayq-pxfq hunt-rayq-pxfw)
    local nr rr
    for nr in "${NEWRUNGS[@]}"; do
        rr="$(ls "$MOD_DIR/swaps.$nr"/*.rgs_reference_main.spv 2>/dev/null | head -1)"
        [[ -z "$rr" ]] && rr="$(ls "$DEST/skin.set/$nr"/*.rgs_reference_main.spv 2>/dev/null | head -1)"
        [[ -n "$rr" ]] && REALS+=("$rr")
    done

    _run() { # _run <logfile> <overlays> <env...>
        local log="$1" ov="$2"; shift 2
        env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
            VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_rayqtest \
            CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" \
            "$@" "$w/st" "$w/plain.spv" ${REALS+"${REALS[@]}"} >"$log.out" 2>&1
        return $?
    }
    _has() { grep -q -- "$2" "$1"; }
    local ok=0 bad=0
    _chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
             else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
    _b()   { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
    # Separate negated form: `_b ! cmd` cannot work -- `!` is a shell keyword,
    # not a command, so it would resolve to "command not found" and report 0
    # for BOTH outcomes. That silent always-fail is exactly the kind of dead
    # assertion this file exists to prevent.
    _bn()  { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }

    echo "ray query layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
    echo

    # ---- case A: the extension must be enabled and the module must link ----
    _run "$w/on.log" rayqtest,fallback env; local r_on=$?
    echo "case A -- ray query enabled by the layer, swaps.rayqtest/ serves it"
    sed -n '1,8p' "$w/on.log.out" | sed 's/^/    /'
    _chk "probe exits 0"                            "$([[ $r_on -eq 0 ]] && echo 1 || echo 0)"
    _chk "layer enabled VK_KHR_ray_query"           "$(_b _has "$w/on.log" '"ev":"rayq","action":"enabled"')"
    _chk "the ray-query module was served (HIT)"    "$(_b _has "$w/on.log" '"swap":"HIT"')"
    _chk "RT pipeline reports the swap (swapped:1)" "$(_b _has "$w/on.log" '"swapped":1')"
    _chk "no rayq_reject"                           "$(_bn _has "$w/on.log" 'rayq_reject')"
    _chk "no rt_pipeline_failed"                    "$(_bn _has "$w/on.log" 'rt_pipeline_failed')"
    _chk "SER still enabled alongside it"           "$(_b _has "$w/on.log" '"ev":"ser","action":"enabled"')"
    echo

    # ---- case B: the reject must fall through to the NEXT OVERLAY ----
    _run "$w/off.log" rayqtest,fallback env CALLISTO_RAYQ_DISABLE=1; local r_off=$?
    echo "case B -- CALLISTO_RAYQ_DISABLE=1: reject, then fall through to swaps.fallback/"
    sed -n '1,8p' "$w/off.log.out" | sed 's/^/    /'
    _chk "probe still exits 0 (degrades, does not break)" "$([[ $r_off -eq 0 ]] && echo 1 || echo 0)"
    _chk "layer skipped, reason env_disabled"       "$(_b _has "$w/off.log" '"ev":"rayq","action":"skipped","reason":"env_disabled"')"
    _chk "rayq_reject fired"                        "$(_b _has "$w/off.log" '"ev":"rayq_reject"')"
    _chk "and its action is next_overlay"           "$(_b _has "$w/off.log" '"rayq_reject".*"action":"next_overlay"')"
    _chk "the NEXT overlay served (HIT, not vanilla)" "$(_b _has "$w/off.log" '"swap":"HIT"')"
    _chk "pipeline still reports a swap (swapped:1)"  "$(_b _has "$w/off.log" '"swapped":1')"
    echo

    # ---- case B2: with nothing to fall through to, vanilla is correct ----
    _run "$w/only.log" rayqtest env CALLISTO_RAYQ_DISABLE=1; local r_only=$?
    echo "case B2 -- same reject with no second overlay: vanilla is the only answer left"
    _chk "probe exits 0"                            "$([[ $r_only -eq 0 ]] && echo 1 || echo 0)"
    _chk "rayq_reject fired"                        "$(_b _has "$w/only.log" '"ev":"rayq_reject"')"
    _chk "no swap served"                           "$(_b _has "$w/only.log" '"swap":"none"')"
    echo

    # ---- case C: a real 290 KB patched raygen ----
    if [[ -n "$real" ]]; then
        echo "case C -- a real patched raygen ($(basename "$real"), $(stat -c%s "$real") B)"
        _chk "accepted by vkCreateShaderModule" \
             "$(_b grep -q 'real raygen.*-> 0' "$w/on.log.out")"
    else
        echo "case C -- skipped: no hunt-rayq build found (run ./dev/build_rayq.sh --install)"
    fi
    echo

    # ---- case E: the sec-13 getters, on the driver ----
    # build_rayq.sh proves the three new rungs assemble and validate offline.
    # spirv-val is not a driver: it does not compile the getter. These runs do,
    # once per getter, through the same served-overlay path the game uses.
    echo "case E -- the sec 13/14 getters and folds compile and link in a raygen"
    local g re
    for g in sbt geom xf xfq xfw; do
        cp -pf "$w/rq_$g.spv" "$w/lay/swaps.rayqtest/bbbbbbbbbbbbbbbb.rayqtest.spv"
        _run "$w/e_$g.log" rayqtest,fallback env; re=$?
        _chk "--field $g: probe exits 0"                   "$([[ $re -eq 0 ]] && echo 1 || echo 0)"
        _chk "--field $g: served (HIT) and the RT pipeline links (swapped:1)" \
             "$(_b grep -q '"swapped":1' "$w/e_$g.log")"
    done
    cp -pf "$w/rq.spv" "$w/lay/swaps.rayqtest/bbbbbbbbbbbbbbbb.rayqtest.spv"
    # Asked of the REALS list actually handed to the probe, not of the
    # filesystem: an `ls` over two candidate paths returns non-zero when either
    # is absent, which would silently report "not built" for a rung the probe
    # had just loaded.
    for g in psbt pgeom pxf pxfq pxfw; do
        if printf '%s\n' ${REALS+"${REALS[@]}"} | grep -q "hunt-rayq-$g/"; then
            _chk "a real hunt-rayq-$g raygen is accepted by vkCreateShaderModule" \
                 "$(_b grep -q "real raygen .*hunt-rayq-$g.*-> 0" "$w/on.log.out")"
        else
            echo "  ....  hunt-rayq-$g not built; run ./dev/build_rayq.sh"
        fi
    done
    echo

    # ---- case D: the AS journal (Stage 2a) ----
    echo "case D -- AS journal"
    _chk "hooks armed on an AS-capable device"      "$(_b _has "$w/on.log" '"ev":"asjournal","action":"armed"')"
    _chk "as_create logged, type top"               "$(_b _has "$w/on.log" '"ev":"as_create".*"type":"top"')"
    _chk "as_addr logged with a distinct top address" "$(_b _has "$w/on.log" '"ev":"as_addr".*"distinct_top_addr":1')"
    _chk "as_summary at device destroy"             "$(_b _has "$w/on.log" '"ev":"as_summary","why":"device_destroy"')"
    # --- the 98 sec 12.5 regression: create says GENERIC, the build says top ---
    _chk "a GENERIC create is logged as generic"    "$(_b _has "$w/on.log" '"ev":"as_create".*"type":"generic"')"
    _chk "its build is classified TOP anyway"       "$(_b _has "$w/on.log" '"ev":"as_build".*"type":"top".*"declared_at_create":"generic"')"
    _chk "a triangles build is classified BOTTOM"   "$(_b _has "$w/on.log" '"ev":"as_build".*"type":"bottom".*"declared_at_create":"generic"')"
    _chk "NO as_build line says untracked"          "$(_bn grep -q '"ev":"as_build".*untracked' "$w/on.log")"
    _chk "the TLAS is reported as a TLAS row"       "$(_b _has "$w/on.log" '"ev":"as_tlas"')"
    _chk "... carrying the build's instance count"  "$(_b _has "$w/on.log" '"ev":"as_tlas".*"instances_last":3,"instances_max":3')"
    # A TLAS created but never built legitimately reports 0 instances and 0
    # builds; that row is a correct answer, not a miss, so it is asserted too.
    _chk "... and a never-built TLAS reads 0/0"     "$(_b _has "$w/on.log" '"ev":"as_tlas".*"builds":0,"updates":0.*"instances_max":0')"
    _chk "... and 2 builds in one frame"            "$(_b _has "$w/on.log" '"ev":"as_tlas".*"max_builds_per_frame":2')"
    _chk "summary counts >0 tlas_handles"           "$(_bn grep -q '"ev":"as_summary".*"tlas_handles":0[,}]' "$w/on.log")"
    _chk "summary reports untracked_builds:0"       "$(_b _has "$w/on.log" '"ev":"as_summary".*"untracked_builds":0')"
    _chk "the frame tick ran, source named"         "$(_b _has "$w/on.log" '"ev":"as_summary".*"frame_src":"submit"')"
    _chk "... and counted the submits"              "$(_bn grep -q '"ev":"as_summary","why":"device_destroy","frames":0' "$w/on.log")"
    _chk "the table did not overflow"               "$(_b _has "$w/on.log" '"ev":"as_summary".*"table_overflow":0')"
    _run "$w/noj.log" rayqtest,fallback env CALLISTO_ASJOURNAL_DISABLE=1
    local r_noj=$?
    _chk "CALLISTO_ASJOURNAL_DISABLE=1 silences it" "$(_bn grep -q '"ev":"as_' "$w/noj.log")"
    _chk "... and the probe still exits 0"          "$([[ $r_noj -eq 0 ]] && echo 1 || echo 0)"
    echo

    echo "$ok passed, $bad failed"
    if ((bad)); then
        echo "logs kept: $w" >&2; trap - RETURN; return 1
    fi
    cat <<'EOM'

What this does NOT prove: that the ray query HITS anything in the game. The
null-descriptor query above is a link test -- it says the driver compiles and
links OpRayQueryInitializeKHR in a raygen created by vkd3d-proton's own path,
nothing more. Whether the module's %accel holds a TLAS with real instances at
the moment the splice runs is a question only a frame can answer; that is what
skinspec=hunt-rayq-p is for. See handoff/98-RAYQUERY.md.
EOM
    return 0
}

case "${1:---selftest}" in
    --selftest) selftest; exit $? ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac
