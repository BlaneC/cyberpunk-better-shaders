#!/usr/bin/env bash
# Build the Shader Execution Reordering ladder -- idea A1 / gate G-A1 of
# handoff/38-WILD-IDEAS.md. Build record: handoff/41-SER-BUILD.md.
#
#   ./dev/patch_ser.sh                     # build the 4-rung ladder
#   ./dev/patch_ser.sh --variant hit       # ... and materialize `hit` as live
#   ./dev/patch_ser.sh --install           # build + copy into $INSTALL_DIR
#   ./dev/patch_ser.sh --report            # detector sweep, write nothing
#   ./dev/patch_ser.sh --status            # what is built and what is served
#   ./dev/patch_ser.sh --selftest          # prove the LAYER's SER path on
#                                          #   this driver, without the game
#   ./dev/patch_ser.sh remove              # uninstall
#
# The game asks for SER (`cvRayTracingEnableReferenceSER` is in the exe),
# vkd3d-proton does not translate the NVAPI intrinsic (issue #2420), and this
# driver reports `VK_NV_ray_tracing_invocation_reorder` with
# `ReorderingHint = REORDER_MODE_REORDER_EXT`. 0 of 3273 dumped modules declare
# the SPIR-V extension. We patch SPIR-V below vkd3d-proton, so we can put it
# back. The splice CANNOT change a pixel; frame time is the only honest proof.
#
# ---------------------------------------------------------------- the ladder
#
#   class      hint = the 3-bit material class, at the G-buffer class fetch.
#              THE DEFAULT, and the splice validated offline in `38` 1.5:
#              3 instructions, +60 bytes, nothing else moves.
#   byte       hint = the full 8-bit material byte (class<<5 | the 5-bit
#              sub-enum of `38` 1.2). One extra OpBitwiseAnd. More buckets is
#              not automatically better -- 256 keys can fragment warps.
#   hit        hint = the bounce ray's hit/miss bit, spliced after the trace.
#              Measured across all twelve permutations, that one branch gates
#              11434-13246 lines of a ~14200-line function (80-92%), while the
#              class gates about 60. It is the most predictive bit in the
#              module AND the most expensive place to reorder (inside three
#              nested loops, with the loop's whole live state across it).
#   class+hit  both.
#
# Which wins is not decidable offline. Run `class` first -- if the mechanism
# is broken at all it is broken there, at the lowest risk. Then `hit`, which
# is the sensitive gate: a null delta on `class` alone does not kill A1, a
# null delta on `hit` does. Note that a SLOWDOWN also proves execution.
#
# ------------------------------------------------------------- the source dir
#
# GOTCHAS: an overlay serves the FIRST file it finds for an id, and every
# overlay outranks the base swaps/ dir. `swaps/` already carries skinray's
# patched raygens and `swaps.ptq/` (an overlay) carries the tier-1 + MS-GGX
# build of all twelve. So a SER overlay built from VANILLA would silently
# un-patch both, with no error anywhere.
#
# A1 is therefore built ON TOP of the set that is actually being served, the
# same way ptq is built on top of skinray. Source resolution, in order:
#
#   1. --from DIR                       explicit, always wins
#   2. $INSTALL_DIR/swaps.ptq/          what the last launch actually served
#   3. $MOD_DIR/swaps.ptq.matrix/<combo>/{base,skin}   (--combo, default rcbm)
#   4. $CALLISTO_DUMP                   vanilla -- refused unless --from-vanilla
#
# The source's content hash goes into MANIFEST.txt in every output dir, and
# the layer logs that manifest line at startup, so `~/callisto_swap.jsonl`
# alone says which build was served (the `26` section 7 attribution lesson:
# byte sizes cannot tell two variants apart).
#
# ---------------------------------------------------------------- the control
#
# The A/B control is NOT a second set. Writing $INSTALL_DIR/ser.disable makes
# the layer skip swaps.ser/ entirely, so swaps.ptq/ serves the very same
# modules minus the reorder instruction -- a genuine single-variable A/B, with
# no second build to get out of step. `--install` writes that flag for you.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
DUMP="${CALLISTO_DUMP:-$HOME/callisto_dump}"
SETDIR="$MOD_DIR/swaps.ser.set"
LIVE="$MOD_DIR/swaps.ser"
VARIANTS=(class byte hit class+hit)

variant=class
from=""
combo="${CALLISTO_PTQ_COMBO:-rcbm}"
from_vanilla=0
do_install=0
do_report=0

# --------------------------------------------------------------- --selftest
#
# Everything above this line is offline: spirv-as and spirv-val never touch a
# driver. That leaves the half of A1 that only a real Vulkan device can
# answer -- does the LAYER actually get VK_NV_ray_tracing_invocation_reorder
# onto the VkDevice, and does the reject-guard fire when it doesn't? The game
# is not the way to find out (a black screen is not a diagnosis), so this
# builds a ~110-line Vulkan program that does the same three API calls the
# game does and runs the layer against it.
#
# It found a real bug: the layer's SPV_CAP_SHADER_INVOCATION_REORDER_NV was
# 5345 (wrong; it is 5383), so spv_declares_ser() never matched and the
# reject-guard was silently dead. Nothing offline could have caught that --
# the constant is a SPIR-V enumerant with no header to disagree with.
#
# Loader note: the layer is installed as an IMPLICIT layer, and the loader
# dedupes by layer NAME -- so VK_ADD_LAYER_PATH pointed at a fresh build
# still binds the INSTALLED .so, even with CALLISTO_LAYER_DISABLE=1. The
# manifest written below therefore names the copy VK_LAYER_CALLISTO_sertest.
# Without that rename this test silently measures the old binary.
selftest() {
    local w rc=0
    w="$(mktemp -d)" || return 1
    trap 'rm -rf "$w"' RETURN

    for t in spirv-as spirv-val gcc; do
        command -v "$t" >/dev/null || { echo "selftest: need $t" >&2; return 1; }
    done
    [[ -f /usr/include/vulkan/vulkan.h ]] || {
        echo "selftest: need Vulkan headers (/usr/include/vulkan/vulkan.h)" >&2; return 1; }

    # The layer under test is the one in THIS repo, freshly built.
    ( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
        echo "selftest: layer build failed" >&2; cat "$w/build.log" >&2; return 1; }
    mkdir -p "$w/lay/swaps.ser"
    cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
    cat > "$w/lay/sertest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_sertest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the SER self-test"
    }
}
EOJ

    # Two minimal raygens with the same synthetic DXIL identity, so the layer
    # will swap one for the other: the app creates the plain one, swaps.ser/
    # holds the reordering one. That is the game's situation in miniature.
    cat > "$w/nore.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpExtension "SPV_KHR_ray_tracing"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid
        %str = OpString "aaaaaaaaaaaaaaaa.?selftest@@YAXXZ.dxil"
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
    cat > "$w/ser.spvasm" <<'EOA'
               OpCapability RayTracingKHR
               OpCapability ShaderInvocationReorderNV
               OpExtension "SPV_KHR_ray_tracing"
               OpExtension "SPV_NV_shader_invocation_reorder"
               OpMemoryModel Logical GLSL450
               OpEntryPoint RayGenerationKHR %main "main" %lid
        %str = OpString "aaaaaaaaaaaaaaaa.?selftest@@YAXXZ.dxil"
               OpDecorate %lid BuiltIn LaunchIdKHR
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
       %uint = OpTypeInt 32 0
     %v3uint = OpTypeVector %uint 3
%_ptr_Input_v3uint = OpTypePointer Input %v3uint
%_ptr_Input_uint = OpTypePointer Input %uint
        %lid = OpVariable %_ptr_Input_v3uint Input
     %uint_0 = OpConstant %uint 0
     %uint_3 = OpConstant %uint 3
     %uint_7 = OpConstant %uint 7
       %main = OpFunction %void None %3
          %5 = OpLabel
          %p = OpAccessChain %_ptr_Input_uint %lid %uint_0
          %v = OpLoad %uint %p
          %h = OpBitwiseAnd %uint %v %uint_7
               OpReorderThreadWithHintNV %h %uint_3
               OpReturn
               OpFunctionEnd
EOA
    for f in nore ser; do
        spirv-as --target-env spv1.4 "$w/$f.spvasm" -o "$w/$f.spv" || return 1
        spirv-val --target-env vulkan1.3 "$w/$f.spv" || return 1
    done
    cp -pf "$w/ser.spv" "$w/lay/swaps.ser/aaaaaaaaaaaaaaaa.selftest.spv"

    cat > "$w/st.c" <<'EOC'
/* Three API calls, the same three the game makes: create a device WITHOUT
 * asking for the SER extension, create a raygen, build an RT pipeline. */
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
    const char *spv = argc>1 ? argv[1] : "ser.spv";
    const char *extra = argc>2 ? argv[2] : NULL;   /* create-only, e.g. a real raygen */
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
        int rtp=0,ser=0;
        for(uint32_t k=0;k<ne;k++){
            if(!strcmp(ep[k].extensionName,VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME))rtp=1;
            if(!strcmp(ep[k].extensionName,VK_NV_RAY_TRACING_INVOCATION_REORDER_EXTENSION_NAME))ser=1;
        }
        free(ep);
        if(rtp){phys=pd[i];adv=ser;vkGetPhysicalDeviceProperties(phys,&props);break;}
    }
    if(!phys){printf("FAIL no device with VK_KHR_ray_tracing_pipeline\n");return 4;}
    printf("device: %s  SER advertised by ICD: %s\n",props.deviceName,adv?"yes":"NO");
    float prio=1.0f;
    VkDeviceQueueCreateInfo q={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    q.queueFamilyIndex=0;q.queueCount=1;q.pQueuePriorities=&prio;
    /* deliberately does NOT list the SER extension -- that is the layer's job */
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
    if(extra){
        size_t n2; uint32_t *c2=slurp(extra,&n2);
        VkShaderModuleCreateInfo s2={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        s2.codeSize=n2; s2.pCode=c2;
        VkShaderModule m2; VkResult r2=vkCreateShaderModule(dev,&s2,NULL,&m2);
        printf("vkCreateShaderModule(real raygen, %zu B) -> %d\n",n2,r2);
        if(r2!=VK_SUCCESS)return 5;
    }
    VkPipelineLayoutCreateInfo pli={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
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
    printf("RESULT: OK\n");
    return 0;
}
EOC
    gcc -O1 -o "$w/st" "$w/st.c" -lvulkan 2>"$w/cc.err" || {
        echo "selftest: could not build the probe (need libvulkan-dev):" >&2
        sed -n '1,5p' "$w/cc.err" >&2; return 1; }

    # A real patched raygen, if one is built, gets a create-only pass too:
    # the synthetic module is 452 bytes and proves nothing about a 290 KB one.
    local real=""
    real="$(ls "$LIVE"/*.rgs_reference_main.spv 2>/dev/null | head -1)"

    _run() { # _run <name> <logfile> <env...> -- prints nothing, sets REPLY
        local name="$1" log="$2"; shift 2
        env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
            VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_sertest \
            CALLISTO_LOG="$log" "$@" "$w/st" "$w/nore.spv" ${real:+"$real"} \
            >"$log.out" 2>&1
        return $?
    }
    _has() { grep -q "$2" "$1"; }
    local ok=0 bad=0
    _chk() { # _chk <desc> <cond 0/1>
        if (($2)); then printf '  PASS  %s\n' "$1"; ((ok++))
        else            printf '  FAIL  %s\n' "$1"; ((bad++)); fi
    }

    echo "SER layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
    echo

    _run on "$w/on.log" env; local r_on=$?
    echo "case A -- SER enabled, swaps.ser/ serves a reordering module"
    sed -n '1,6p' "$w/on.log.out" | sed 's/^/    /'
    _chk "probe exits 0"                              "$([[ $r_on -eq 0 ]] && echo 1 || echo 0)"
    _chk "layer enabled the device extension"         "$(_has "$w/on.log" '"ev":"ser","action":"enabled"' && echo 1 || echo 0)"
    _chk "the reordering module was served (HIT)"     "$(_has "$w/on.log" '"swap":"HIT"' && echo 1 || echo 0)"
    _chk "RT pipeline reports the swap (swapped:1)"   "$(_has "$w/on.log" '"swapped":1' && echo 1 || echo 0)"
    _chk "no ser_reject"                              "$(_has "$w/on.log" 'ser_reject' && echo 0 || echo 1)"
    _chk "no rt_pipeline_failed"                      "$(_has "$w/on.log" 'rt_pipeline_failed' && echo 0 || echo 1)"
    echo

    _run off "$w/off.log" env CALLISTO_SER_DISABLE=1; local r_off=$?
    echo "case B -- CALLISTO_SER_DISABLE=1: the guard must refuse the module"
    sed -n '1,6p' "$w/off.log.out" | sed 's/^/    /'
    _chk "probe still exits 0 (degrades, does not break)" "$([[ $r_off -eq 0 ]] && echo 1 || echo 0)"
    _chk "layer skipped, reason env_disabled"         "$(_has "$w/off.log" '"action":"skipped","reason":"env_disabled"' && echo 1 || echo 0)"
    _chk "ser_reject fired"                           "$(_has "$w/off.log" '"ev":"ser_reject"' && echo 1 || echo 0)"
    _chk "vanilla served instead (swapped:0)"         "$(_has "$w/off.log" '"swapped":0' && echo 1 || echo 0)"
    echo

    if [[ -n "$real" ]]; then
        echo "case C -- a real patched raygen ($(basename "$real"), $(stat -c%s "$real") B)"
        _chk "accepted by vkCreateShaderModule" \
             "$(grep -q 'real raygen.*-> 0' "$w/on.log.out" && echo 1 || echo 0)"
    else
        echo "case C -- skipped: no $LIVE/*.rgs_reference_main.spv built yet"
    fi
    echo

    echo "$ok passed, $bad failed"
    if ((bad)); then
        echo "logs kept: $w" >&2; trap - RETURN; return 1
    fi
    cat <<'EOM'

What this does NOT prove: that OpReorderThreadWithHintNV changes anything.
The driver accepts and links these modules whether or not the extension is
enabled (measured -- case B builds a pipeline too), so "it loads" is not
evidence of a reorder. Only a frame-time delta is. See handoff/41-SER-BUILD.md.
EOM
    return 0
}

while (($#)); do
    case "$1" in
        --variant)      variant="$2"; shift 2 ;;
        --from)         from="$2"; shift 2 ;;
        --combo)        combo="$2"; shift 2 ;;
        --from-vanilla) from_vanilla=1; shift ;;
        --install)      do_install=1; shift ;;
        --report)       do_report=1; shift ;;
        --selftest)     selftest; exit $? ;;
        --status)
            echo "built sets ($SETDIR):"
            for v in "${VARIANTS[@]}"; do
                n=$(ls "$SETDIR/$v"/*.spv 2>/dev/null | wc -l)
                echo "  $v: $n modules $( [[ -f "$SETDIR/$v/MANIFEST.txt" ]] && head -1 "$SETDIR/$v/MANIFEST.txt" )"
            done
            echo "repo swaps.ser/: $(ls "$LIVE"/*.spv 2>/dev/null | wc -l) modules"
            echo "installed:"
            echo "  $DEST/ser.set:   $(ls -d "$DEST/ser.set"/* 2>/dev/null | wc -l) rungs"
            echo "  $DEST/swaps.ser: $(ls "$DEST/swaps.ser"/*.spv 2>/dev/null | wc -l) modules"
            [[ -f "$DEST/swaps.ser/MANIFEST.txt" ]] && \
                echo "  serving: $(head -1 "$DEST/swaps.ser/MANIFEST.txt")"
            [[ -f "$DEST/ser.disable" ]] && echo "  ser.disable PRESENT -- SER is OFF (this is the A/B control)"
            exit 0 ;;
        remove)
            rm -rf "$DEST/swaps.ser" "$DEST/ser.set"; rm -f "$DEST/ser.disable"
            echo "SER removed from $DEST. swaps.ptq/ serves the raygens again."
            exit 0 ;;
        -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

printf '%s\n' "${VARIANTS[@]}" | grep -qx -- "$variant" \
    || { echo "unknown --variant '$variant' (want: ${VARIANTS[*]})" >&2; exit 2; }

# ------------------------------------------------------------------- source
declare -a SRC=()
src_label=""
if [[ -n "$from" ]]; then
    mapfile -t SRC < <(ls "$from"/*.rgs_reference_main.spv 2>/dev/null)
    src_label="$from"
elif compgen -G "$DEST/swaps.ptq/*.rgs_reference_main.spv" >/dev/null; then
    mapfile -t SRC < <(ls "$DEST/swaps.ptq"/*.rgs_reference_main.spv)
    src_label="swaps.ptq (installed, as served)"
elif [[ -d "$MOD_DIR/swaps.ptq.matrix/$combo/base" ]]; then
    # base/ is all twelve; skin/ overrides the two skinray permutations, which
    # is exactly what sync_settings.sh materializes at launch when skinray=on.
    tmpsrc="$(mktemp -d)"; trap 'rm -rf "$tmpsrc"' EXIT
    cp -pf "$MOD_DIR/swaps.ptq.matrix/$combo/base"/*.spv "$tmpsrc/"
    # skin/ is no longer layered on top: skinray was removed (handoff/43), so
    # sync_settings.sh serves base/ alone and the sha must match base/ alone.
    mapfile -t SRC < <(ls "$tmpsrc"/*.rgs_reference_main.spv)
    src_label="swaps.ptq.matrix/$combo (base+skin)"
elif ((from_vanilla)); then
    mapfile -t SRC < <(ls "$DUMP"/*.rgs_reference_main.spv 2>/dev/null)
    src_label="VANILLA $DUMP"
else
    cat >&2 <<'EOM'
no ptq source found, and --from-vanilla was not given.

Building SER from the vanilla dump would produce an overlay that outranks
swaps.ptq/ and swaps/ and therefore silently UN-PATCHES the PT tier-1,
MS-GGX and skinray splices -- with no error anywhere (GOTCHAS: an overlay
serves the FIRST file it finds for an id). If that is really what you want,
pass --from-vanilla; otherwise run ./dev/build_ptq.sh first, or point
--from at the set you want SER layered on to.
EOM
    exit 2
fi

((${#SRC[@]} == 12)) || {
    echo "expected 12 rgs_reference_main permutations, found ${#SRC[@]} in $src_label" >&2
    echo "(handoff/evidence-raygen-permutations.md: the live game builds exactly 12)" >&2
    exit 2
}

src_sha="$(cat "${SRC[@]}" | sha256sum | cut -c1-16)"
# --report prints machine-readable JSON on stdout, so its provenance banner
# goes to stderr; a build's progress lines stay where a human reads them.
say() { if ((do_report)); then echo "$@" >&2; else echo "$@"; fi; }
say "source: $src_label"
say "        ${#SRC[@]} modules, content sha $src_sha"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK" "${tmpsrc:-}"' EXIT
mkdir -p "$WORK/asm"
declare -a ASM=()
for f in "${SRC[@]}"; do
    b="$(basename "$f" .spv)"
    spirv-dis --no-color "$f" -o "$WORK/asm/$b.spvasm" || exit 2
    ASM+=("$WORK/asm/$b.spvasm")
done

if ((do_report)); then
    python3 "$MOD_DIR/dev/patch_ser.py" "${ASM[@]}" --report
    exit 0
fi

# The unpatched round trip is proven once here rather than 4x12 times inside
# the patcher; every build below runs with --no-roundtrip-check.
echo "round-tripping the unpatched source once (spirv-as + spirv-val):"
for f in "${ASM[@]}"; do
    spirv-as --target-env spv1.4 "$f" -o "$WORK/rt.spv" >/dev/null 2>&1 \
        && spirv-val --target-env vulkan1.4 "$WORK/rt.spv" >/dev/null 2>&1 \
        || { echo "  FAIL $(basename "$f")" >&2; exit 2; }
done
echo "  ok (${#ASM[@]} modules)"

# ------------------------------------------------------------------- build
rm -rf "$SETDIR"
echo "building the SER ladder:"
for v in "${VARIANTS[@]}"; do
    d="$SETDIR/$v"
    if ! python3 "$MOD_DIR/dev/patch_ser.py" "${ASM[@]}" --outdir "$d" \
             --variant "$v" --no-roundtrip-check > "$WORK/$v.json"; then
        echo "  FAIL $v -- see the patcher error above" >&2
        exit 2
    fi
    n=$(ls "$d"/*.spv 2>/dev/null | wc -l)
    ((n == 12)) || { echo "  FAIL $v: wrote $n/12 modules" >&2; exit 2; }
    add=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(",".join(sorted({str(x["bytes_added"]) for x in d})))' "$WORK/$v.json")
    # MANIFEST.txt line 1 is what the layer echoes into the JSONL log, so it
    # has to be one line, JSON-safe, and carry the provenance an observation
    # will later be attributed to.
    {
        echo "ser variant=$v src=\"$src_label\" src_sha=$src_sha modules=$n built=$(date -Is)"
        echo "# spirv-val clean at vulkan1.3 AND vulkan1.4 for all $n modules."
        echo "# bytes added per module: $add"
        echo "# The reorder is a HINT: it cannot change a pixel. Frame time is"
        echo "# the only honest measurement (handoff/41-SER-BUILD.md)."
        python3 - "$WORK/$v.json" <<'PY'
import json, sys
for m in json.load(open(sys.argv[1])):
    print(f"{m['ident']} sha={m['sha256']} +{m['bytes_added']}B "
          f"reorders={m['reorders']} class@{m['class_sites'][0]['line']} "
          f"hit@{m['hit_sites'][0]['line']}")
PY
    } > "$d/MANIFEST.txt"
    echo "  ok   $v  ($n modules, +${add}B each, spirv-val clean vk1.3+vk1.4)"
    cp -pf "$WORK/$v.json" "$d/build.json"
done

# The repo-side swaps.ser/ is the materialized selection, mirroring
# skin.set/ -> swaps.skin/ and shadowcull.set/ -> swaps.shadowcull/.
rm -rf "$LIVE"; mkdir -p "$LIVE"
cp -pf "$SETDIR/$variant"/*.spv "$SETDIR/$variant/MANIFEST.txt" "$LIVE/"
echo "materialized '$variant' into $LIVE/"

# ----------------------------------------------------------------- install
if ((do_install)); then
    rm -rf "$DEST/ser.set"; mkdir -p "$DEST/ser.set"
    for v in "${VARIANTS[@]}"; do
        mkdir -p "$DEST/ser.set/$v"
        cp -pf "$SETDIR/$v"/*.spv "$SETDIR/$v/MANIFEST.txt" "$DEST/ser.set/$v/"
    done
    rm -rf "$DEST/swaps.ser"; mkdir -p "$DEST/swaps.ser"
    cp -pf "$DEST/ser.set/$variant"/*.spv "$DEST/ser.set/$variant/MANIFEST.txt" \
          "$DEST/swaps.ser/"
    # Start OFF. GOTCHAS: an empty or unflagged overlay reads as "enabled" in
    # the layer log even when it does nothing, and a perf feature that turns
    # itself on at install time cannot be A/B'd against the launch before it.
    : > "$DEST/ser.disable"
    echo "installed: ${#VARIANTS[@]} rungs -> $DEST/ser.set/, '$variant' -> $DEST/swaps.ser/"
    echo "SER is currently OFF (ser.disable present) -- that is the A/B control."
    cat <<EOM

next:
  1. rebuild + reinstall the layer -- it is what enables the device extension:
         ./build_swap_layer.sh && cp -f libVkLayer_callisto_spvswap.so "$DEST/"
     (Do NOT skip this because the game still starts without it. Measured on
     driver 610.43.2.0: a module declaring ShaderInvocationReorderNV builds
     into a pipeline even with the extension NOT enabled -- so an un-updated
     layer looks exactly like success and reorders nothing. The extension is
     required by the spec; without it the instruction may legally be dropped.
     `./dev/patch_ser.sh --selftest` checks the layer really enables it.)
  2. pick the half in brdf_params.txt -- do NOT rm ser.disable by hand, as
     sync_settings.sh now owns that flag and rewrites it every launch:
         ser=off              control half (this is how --install leaves it)
         ser=class            or byte / hit / class+hit -- a copy, not a rebuild
  3. the caches take care of themselves: sync_settings.sh hashes swaps.ser/
     into its stamp and keys it on ser=, so switching halves clears them.
  4. it can only ever force ser OFF -- if it does, stdout says why:
         [CallistoSSS] ser DISABLED (stale): built against ptq <a>, ptq is now <b>
     which means swaps.ptq/ changed under it; re-run this script --install.
  5. read ~/callisto_swap.jsonl for:
         {"ev":"ser","action":"enabled",...}         the device extension
         {"ev":"overlay_manifest","name":"ser",...}   which rung is served
         12x {"ev":"module",...,"swap":"HIT"} on rgs_reference_main
         NO {"ev":"ser_reject"...} and NO {"ev":"rt_pipeline_failed"...}
EOM
else
    echo "not installed. run with --install, or copy $LIVE/ to $DEST/swaps.ser/"
fi
