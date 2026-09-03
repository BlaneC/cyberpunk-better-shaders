#!/usr/bin/env bash
# bda LAYER self-test -- the on-device half of handoff/103, and the ONLY thing
# that can close hole 3 of `98` sec 10.3 (memory type, lifetime, visibility).
#
# ./dev/build_bda.sh gates the three rungs entirely offline. spirv-val is not a
# driver: it will happily validate a module that dereferences a 64-bit pointer
# nobody ever wrote, and it has no opinion at all on whether a HOST_VISIBLE
# allocation's device address is readable from a compute dispatch. This script
# answers the questions only a real Vulkan device can:
#
#   1. can the layer allocate a SHADER_DEVICE_ADDRESS buffer on the device the
#      application created, map it, and get a non-zero device address -- when
#      the application (like vkd3d-proton) enabled bufferDeviceAddress through
#      VkPhysicalDeviceVulkan12Features and never asked for anything else?
#   2. does a COMPUTE dispatch actually READ THE MAGIC BACK through a pointer
#      the layer fixed up at vkCreateShaderModule?  That is Stage 2b, end to
#      end, with no game and no screen.
#   3. does the layer's TLAS hook put a REAL top-level device address in the
#      slot, and can a compute-side inline ray query built from those two
#      words hit a triangle that is there and miss where there is none?  That
#      is Stage 2c, end to end.
#   4. do the REAL patched resolvers of both live rungs survive
#      vkCreateShaderModule when served THROUGH THE LAYER by the same
#      first-file-wins overlay path the game uses?
#   5. does the reject guard refuse a FORGED marker and fall through to the
#      NEXT OVERLAY (never to vanilla), and does it refuse everything when the
#      slot could not be armed?
#
#   ./dev/selftest_bda.sh          # everything; no game involved
#
# NEW FILE on purpose: dev/patch_rayq.sh (98), dev/selftest_earglow_rq.sh (101)
# and dev/selftest_contact_rq.sh (102) are not touched.
#
# Loader note, inherited from dev/patch_rayq.sh and worth repeating because
# getting it wrong makes every result a lie: the layer installs as an IMPLICIT
# layer and the loader dedupes implicit layers BY NAME, so VK_ADD_LAYER_PATH
# pointed at a fresh build still binds the INSTALLED .so. The manifest below
# therefore names the test copy VK_LAYER_CALLISTO_bdatest.
#
# Overlay fixtures are SYMLINKS to swaps.<rung>/, never copies: the bytes the
# driver is handed are literally the shipped bytes build_bda.sh just gated.
set -uo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNGS=(bda-ctl bda-probe bda-rq-probe)

ok=0; bad=0; skip=0
chk() { if (($2)); then printf '  PASS  %s\n' "$1"; ok=$((ok+1))
        else            printf '  FAIL  %s\n' "$1"; bad=$((bad+1)); fi; }
note(){ printf '  ....  %s\n' "$1"; skip=$((skip+1)); }
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
for r in "${RUNGS[@]}"; do
    [[ -d "$MOD_DIR/swaps.$r" ]] || {
        echo "selftest: run ./dev/build_bda.sh first (no swaps.$r)" >&2; exit 1; }
done

w="$(mktemp -d)" || exit 1
# CALLISTO_SELFTEST_KEEP=1 keeps the work dir (logs, generated modules, the
# probe source) for post-mortem instead of deleting it.
if [[ -z "${CALLISTO_SELFTEST_KEEP:-}" ]]; then trap 'rm -rf "$w"' EXIT
else trap 'echo "work dir kept: $w"' EXIT; fi

( cd "$MOD_DIR" && ./build_swap_layer.sh ) >"$w/build.log" 2>&1 || {
    echo "selftest: layer build failed" >&2; tail -5 "$w/build.log" >&2; exit 1; }
mkdir -p "$w/lay" "$w/lay/swaps.bdasyn" "$w/lay/swaps.bdafb" "$w/stand"
cp -pf "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$w/lay/"
cat > "$w/lay/bdatest.json" <<'EOJ'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_CALLISTO_bdatest",
        "type": "GLOBAL",
        "library_path": "./libVkLayer_callisto_spvswap.so",
        "api_version": "1.3.280",
        "implementation_version": "1",
        "description": "Callisto spvswap, renamed for the bda self-test"
    }
}
EOJ

# ------------------------------------------------------------------ fixtures
# The synthetic modules ARE the splice shape, in miniature: the same
# OpCompositeConstruct/OpBitcast/OpInBoundsAccessChain/OpLoad Aligned 4 idiom,
# the same marker, the same sentinel constants -- emitted from the SAME
# constants dev/patch_bda.py uses (imported, never retyped) and given their
# real ids by the SAME resolve_marker_ids(). If the ABI drifts, this file
# stops testing the rungs and says so at gate 0.
#
# Every forgery below is a module the layer must REFUSE. They are separate
# modules rather than a mutated one because the four conjuncts are separate
# claims and a single failure has to be attributable.
python3 - "$w" "$MOD_DIR/dev" <<'PYGEN' || { echo "selftest: could not emit the synthetic modules" >&2; exit 1; }
import os, struct, subprocess, sys
w = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from patch_bda import (MARKER, SENT_LO, SENT_HI, MAGIC, SLOT_MEMBERS, ID_W,
                       resolve_marker_ids, DEFAULTS)

SYN = os.path.join(w, 'lay', 'swaps.bdasyn')
FB = os.path.join(w, 'lay', 'swaps.bdafb')
STAND = os.path.join(w, 'stand')
OUT_WORDS = 16
KINDS = [
    ('bda0000000000001', 'magic'),
    ('bda0000000000002', 'rq'),
    ('bda0000000000010', 'nomarker'),
    ('bda0000000000011', 'badid'),
    ('bda0000000000012', 'wrongsent'),
    ('bda0000000000013', 'wrongmagic'),
    ('bda0000000000014', 'idtype'),
    ('bda0000000000015', 'twomarkers'),
]


def mk(lo, hi, sent, magic, name='mk'):
    return (f'        %{name} = OpString "{MARKER} lo=%{lo:0{ID_W}d} '
            f'hi=%{hi:0{ID_W}d} sent={sent:016x} magic={magic:08x}"')


def build(ident, kind):
    rq = kind == 'rq'
    L = []
    A = L.append
    A('               OpCapability Shader')
    A('               OpCapability PhysicalStorageBufferAddresses')
    if rq:
        A('               OpCapability RayQueryKHR')
        A('               OpCapability RayTraversalPrimitiveCullingKHR')
    A('               OpExtension "SPV_KHR_physical_storage_buffer"')
    if rq:
        A('               OpExtension "SPV_KHR_ray_query"')
    A('               OpMemoryModel PhysicalStorageBuffer64 GLSL450')
    A('               OpEntryPoint GLCompute %main "main"')
    A('               OpExecutionMode %main LocalSize 1 1 1')
    A(f'        %sid = OpString "{ident}.dxil"')
    # ---- the marker, in the debug section, exactly where the rungs put it
    lo_f = hi_f = 0
    sent = (SENT_HI << 32) | SENT_LO
    mg = MAGIC
    if kind == 'badid':
        # DISTINCT and non-zero, so the id-shape check passes and the module
        # is refused for the reason under test: the ids are past the bound.
        lo_f, hi_f = 4294967295, 4294967294
    if kind != 'nomarker':
        A(mk(lo_f, hi_f, sent, mg))
    if kind == 'twomarkers':
        A(mk(0, 0, sent, mg, name='mk2'))
    # ---- annotations
    A('               OpDecorate %rtarr ArrayStride 4')
    A('               OpDecorate %Out Block')
    A('               OpMemberDecorate %Out 0 Offset 0')
    A('               OpDecorate %out DescriptorSet 0')
    A('               OpDecorate %out Binding 0')
    for k in range(SLOT_MEMBERS):
        A(f'               OpMemberDecorate %Slot {k} Offset {4 * k}')
        A(f'               OpMemberDecorate %Slot {k} NonWritable')
    A('               OpDecorate %Slot Block')
    # ---- types
    A('       %void = OpTypeVoid')
    A('        %fty = OpTypeFunction %void')
    A('       %uint = OpTypeInt 32 0')
    A('       %bool = OpTypeBool')
    A('     %v2uint = OpTypeVector %uint 2')
    A('      %float = OpTypeFloat 32')
    A('    %v3float = OpTypeVector %float 3')
    A('      %rtarr = OpTypeRuntimeArray %uint')
    A('        %Out = OpTypeStruct %rtarr')
    A('%_ptr_StorageBuffer_Out = OpTypePointer StorageBuffer %Out')
    A('%_ptr_StorageBuffer_uint = OpTypePointer StorageBuffer %uint')
    A('        %out = OpVariable %_ptr_StorageBuffer_Out StorageBuffer')
    A('       %Slot = OpTypeStruct ' + ' '.join(['%uint'] * SLOT_MEMBERS))
    A('%_ptr_PSB_Slot = OpTypePointer PhysicalStorageBuffer %Slot')
    A('%_ptr_PSB_uint = OpTypePointer PhysicalStorageBuffer %uint')
    for k in range(max(SLOT_MEMBERS, OUT_WORDS)):
        A(f'    %uint_{k} = OpConstant %uint {k}')
    A(f'      %sentlo = OpConstant %uint {SENT_LO}')
    A(f'      %senthi = OpConstant %uint {SENT_HI}')
    if rq:
        A(f' %uint_flags = OpConstant %uint {DEFAULTS["flags"]}')
        A(f'  %uint_mask = OpConstant %uint {DEFAULTS["mask"]}')
        A(f'     %f_tmin = OpConstant %float {DEFAULTS["tmin"]!r}')
        A(f'     %f_tmax = OpConstant %float {DEFAULTS["tmax"]!r}')
        A('        %f_0 = OpConstant %float 0')
        A('        %f_1 = OpConstant %float 1')
        A('       %f_n1 = OpConstant %float -1')
        A('        %org = OpConstantComposite %v3float %f_0 %f_0 %f_0')
        A('     %dir_up = OpConstantComposite %v3float %f_0 %f_0 %f_1')
        A('     %dir_dn = OpConstantComposite %v3float %f_0 %f_0 %f_n1')
        A('       %rqty = OpTypeRayQueryKHR')
        A('%_ptr_Function_rq = OpTypePointer Function %rqty')
        A('       %asty = OpTypeAccelerationStructureKHR')
    # ---- the body
    A('       %main = OpFunction %void None %fty')
    A('        %top = OpLabel')
    if rq:
        A('        %rq0 = OpVariable %_ptr_Function_rq Function')
        A('        %rq1 = OpVariable %_ptr_Function_rq Function')
    A('         %av2 = OpCompositeConstruct %v2uint %sentlo %senthi')
    A('          %pp = OpBitcast %_ptr_PSB_Slot %av2')
    for k in range(SLOT_MEMBERS):
        A(f'        %ac{k} = OpInBoundsAccessChain %_ptr_PSB_uint %pp %uint_{k}')
        A(f'        %wd{k} = OpLoad %uint %ac{k} Aligned 4')
        A(f'        %oc{k} = OpAccessChain %_ptr_StorageBuffer_uint %out '
          f'%uint_0 %uint_{k}')
        A(f'               OpStore %oc{k} %wd{k}')
    if rq:
        A('         %tv2 = OpCompositeConstruct %v2uint %wd2 %wd3')
        A('          %as = OpConvertUToAccelerationStructureKHR %asty %tv2')
        for i, (var, d) in enumerate((('%rq0', '%dir_up'), ('%rq1', '%dir_dn'))):
            A(f'               OpRayQueryInitializeKHR {var} %as %uint_flags '
              f'%uint_mask %org %f_tmin {d} %f_tmax')
            A(f'        %pr{i} = OpRayQueryProceedKHR %bool {var}')
            A(f'        %ty{i} = OpRayQueryGetIntersectionTypeKHR %uint {var} '
              f'%uint_1')
            A(f'        %og{i} = OpAccessChain %_ptr_StorageBuffer_uint %out '
              f'%uint_0 %uint_{8 + i}')
            A(f'               OpStore %og{i} %ty{i}')
    A('               OpReturn')
    A('               OpFunctionEnd')
    return '\n'.join(L) + '\n'


def emit(path, text):
    a = path + '.spvasm'
    open(a, 'w').write(text)
    r = subprocess.run(['spirv-as', '--target-env', 'spv1.3', a, '-o', path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('spirv-as failed for %s:\n%s' % (path, r.stderr))
    os.remove(a)
    validate(path)


def validate(path):
    v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', path],
                       capture_output=True, text=True)
    if v.returncode:
        sys.exit('spirv-val failed for %s:\n%s' % (path, v.stderr))


def corrupt_field(path, field, width):
    """Flip the low byte of the marker's `sent=` or `magic=` hex field.

    Emitted like the honest module and then corrupted, so the ids are REAL and
    the layer gets past every earlier conjunct: the refusal is attributable to
    this field and to nothing else."""
    b = bytearray(open(path, 'rb').read())
    n = len(b) // 4
    wds = struct.unpack('<%dI' % n, bytes(b[:n * 4]))
    i, at = 5, None
    while i < n:
        ln, op = wds[i] >> 16, wds[i] & 0xffff
        if ln == 0 or op == 54:
            break
        if op == 7 and ln >= 3:
            t = bytes(b[(i + 2) * 4:(i + ln) * 4]).split(b'\0')[0].decode()
            if t.startswith(MARKER):
                at = ((i + 2) * 4, t)
                break
        i += ln
    off, t = at
    head, rest = t.split(field + '=', 1)
    val, tail = rest[:width], rest[width:]
    new = head + field + '=' + f'{int(val, 16) ^ 0xff:0{width}x}' + tail
    assert len(new) == len(t) and new != t, (t, new)
    b[off:off + len(new)] = new.encode()
    open(path, 'wb').write(bytes(b))


def retarget_marker(path, lo, hi):
    """Rewrite the marker's id fields IN PLACE (same width, same length)."""
    b = bytearray(open(path, 'rb').read())
    n = len(b) // 4
    wds = struct.unpack('<%dI' % n, bytes(b[:n * 4]))
    i, at = 5, None
    while i < n:
        ln, op = wds[i] >> 16, wds[i] & 0xffff
        if ln == 0 or op == 54:
            break
        if op == 7 and ln >= 3:
            s = bytes(b[(i + 2) * 4:(i + ln) * 4]).split(b'\0')[0].decode()
            if s.startswith(MARKER):
                at = ((i + 2) * 4, s)
                break
        i += ln
    off, s = at
    head, tail = s.split(' lo=%', 1)
    _, rest = tail.split(' hi=%', 1)
    _, tail2 = rest.split(' sent=', 1)
    new = f'{head} lo=%{lo:0{ID_W}d} hi=%{hi:0{ID_W}d} sent={tail2}'
    assert len(new) == len(s), (s, new)
    b[off:off + len(new)] = new.encode()
    open(path, 'wb').write(bytes(b))


def uint_consts(path):
    """(id of `OpConstant %uint 0`, id of `OpConstant %uint 1`)."""
    b = open(path, 'rb').read()
    n = len(b) // 4
    wds = struct.unpack('<%dI' % n, b[:n * 4])
    uty, out, i = set(), {}, 5
    while i < n:
        ln, op = wds[i] >> 16, wds[i] & 0xffff
        if ln == 0 or op == 54:
            break
        if op == 21 and ln == 4 and wds[i + 2] == 32 and wds[i + 3] == 0:
            uty.add(wds[i + 1])
        elif op == 43 and ln == 4 and wds[i + 1] in uty:
            out.setdefault(wds[i + 3], wds[i + 2])
        i += ln
    return out[0], out[1]


TW = ('               OpCapability Shader\n'
      '               OpMemoryModel Logical GLSL450\n'
      '               OpEntryPoint GLCompute %main "main"\n'
      '               OpExecutionMode %main LocalSize 1 1 1\n'
      '        %sid = OpString "HASH.dxil"\n'
      '       %void = OpTypeVoid\n'
      '        %fty = OpTypeFunction %void\n'
      '       %uint = OpTypeInt 32 0\n'
      '     %uint_k = OpConstant %uint MARK\n'
      '       %main = OpFunction %void None %fty\n'
      '        %top = OpLabel\n'
      '               OpReturn\n'
      '               OpFunctionEnd\n')

for h, kind in KINDS:
    p = os.path.join(SYN, h + '.dxil.spv')
    emit(p, build(h, kind))
    if kind in ('magic', 'rq', 'wrongsent', 'wrongmagic'):
        # give the marker the ids the ASSEMBLER chose -- the same two-pass fix
        # the rungs use, and the reason a marker can name binary ids at all.
        ids = resolve_marker_ids(p, '')
        if kind == 'wrongsent':
            corrupt_field(p, 'sent', 16)
        elif kind == 'wrongmagic':
            corrupt_field(p, 'magic', 8)
        validate(p)
        print('  syn %s (%-10s) lo_id=%d hi_id=%d'
              % (h, kind, ids['lo_id'], ids['hi_id']))
    elif kind == 'idtype':
        # A well-formed marker naming ids that ARE 32-bit uint constants but
        # hold 0 and 1, not the sentinel: conjunct 4, and nothing else.
        c0, c1 = uint_consts(p)
        retarget_marker(p, c0, c1)
        validate(p)
        print('  syn %s (%-10s) names uint constants %d/%d, which hold 0/1'
              % (h, kind, c0, c1))
    else:
        print('  syn %s (%s)' % (h, kind))
    emit(os.path.join(FB, h + '.dxil.spv'),
         TW.replace('HASH', h).replace('MARK', '13'))
    emit(os.path.join(STAND, h + '.spv'),
         TW.replace('HASH', h).replace('MARK', '7'))
PYGEN
[[ -s "$w/lay/swaps.bdasyn/bda0000000000001.dxil.spv" ]] || {
    echo "selftest: synthetic modules missing" >&2; exit 1; }

# App-side stand-ins for the REAL painted resolvers, so the layer has something
# to swap. They carry only the dxil identity; the layer replaces their bytes
# with the rung's real module.
mapfile -t IDS < <(cd "$MOD_DIR/swaps.bda-probe" &&
    for f in *.dxil.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.bda-ctl/$f" || echo "${f%%.*}"
    done | sort)
(( ${#IDS[@]} == 76 )) || { echo "selftest: expected 76 painted ids, got ${#IDS[@]}" >&2; exit 1; }
python3 - "$w" "${IDS[@]}" <<'PYGEN2'
import os, subprocess, sys
w, ids = sys.argv[1], sys.argv[2:]
TMPL = ('               OpCapability Shader\n'
        '               OpMemoryModel Logical GLSL450\n'
        '               OpEntryPoint GLCompute %main "main"\n'
        '               OpExecutionMode %main LocalSize 1 1 1\n'
        '        %sid = OpString "HASH.dxil"\n'
        '       %void = OpTypeVoid\n'
        '          %3 = OpTypeFunction %void\n'
        '       %uint = OpTypeInt 32 0\n'
        '     %uint_k = OpConstant %uint MARK\n'
        '       %main = OpFunction %void None %3\n'
        '          %5 = OpLabel\n'
        '               OpReturn\n'
        '               OpFunctionEnd\n')
for h in ids:
    for mark, out in ((7, os.path.join(w, 'stand', h + '.spv')),
                      (13, os.path.join(w, 'lay', 'swaps.bdafb', h + '.dxil.spv'))):
        a = out + '.spvasm'
        open(a, 'w').write(TMPL.replace('HASH', h).replace('MARK', str(mark)))
        subprocess.run(['spirv-as', '--target-env', 'spv1.3', a, '-o', out],
                       check=True)
        os.remove(a)
PYGEN2

# ---------------------------------------------------------------------- probe
# The same calls vkd3d-proton makes, in the same order: a device that enables
# bufferDeviceAddress through VkPhysicalDeviceVulkan12Features and asks for
# NOTHING else the layer needs, then acceleration structures, then a compute
# pipeline. argv[1] picks what to do; argv[2] is the module that is dispatched;
# argv[3..] are created and thrown away (the real resolvers).
cat > "$w/bt.c" <<'EOC'
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CK(x,m) do{VkResult _r=(x); if(_r!=VK_SUCCESS){printf("FAIL %s -> %d\n",m,_r);exit(4);}}while(0)
static VkDevice dev; static VkPhysicalDevice phys; static VkQueue queue;
static uint32_t qfam; static VkCommandPool cpool;
static PFN_vkCreateAccelerationStructureKHR pCreateAS;
static PFN_vkGetAccelerationStructureBuildSizesKHR pSizes;
static PFN_vkGetAccelerationStructureDeviceAddressKHR pASAddr;
static PFN_vkCmdBuildAccelerationStructuresKHR pBuildAS;

static uint32_t *slurp(const char *p, size_t *n) {
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(3); }
    fseek(f,0,SEEK_END); long s = ftell(f); fseek(f,0,SEEK_SET);
    uint32_t *b = malloc(s); if (fread(b,1,s,f)!=(size_t)s) exit(3);
    fclose(f); *n = s; return b;
}
static uint32_t memtype(uint32_t bits, VkMemoryPropertyFlags want) {
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(phys,&mp);
    for (uint32_t i=0;i<mp.memoryTypeCount;i++)
        if ((bits>>i & 1u) && (mp.memoryTypes[i].propertyFlags & want)==want) return i;
    printf("FAIL no memory type for 0x%x\n",want); exit(4);
}
static void mkbuf(VkDeviceSize sz, VkBufferUsageFlags us, VkMemoryPropertyFlags mp,
                  VkBuffer *buf, VkDeviceMemory *mem, void **map) {
    VkBufferCreateInfo bi={VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bi.size=sz; bi.usage=us; bi.sharingMode=VK_SHARING_MODE_EXCLUSIVE;
    CK(vkCreateBuffer(dev,&bi,NULL,buf),"vkCreateBuffer");
    VkMemoryRequirements rq; vkGetBufferMemoryRequirements(dev,*buf,&rq);
    VkMemoryAllocateFlagsInfo fi={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO};
    fi.flags=VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
    VkMemoryAllocateInfo ai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.pNext=&fi; ai.allocationSize=rq.size; ai.memoryTypeIndex=memtype(rq.memoryTypeBits,mp);
    CK(vkAllocateMemory(dev,&ai,NULL,mem),"vkAllocateMemory");
    CK(vkBindBufferMemory(dev,*buf,*mem,0),"vkBindBufferMemory");
    if (map) CK(vkMapMemory(dev,*mem,0,VK_WHOLE_SIZE,0,map),"vkMapMemory");
}
static VkDeviceAddress bufaddr(VkBuffer b) {
    VkBufferDeviceAddressInfo i={VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO}; i.buffer=b;
    return vkGetBufferDeviceAddress(dev,&i);
}
static VkCommandBuffer begin(void) {
    VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    ai.commandPool=cpool; ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ai.commandBufferCount=1;
    VkCommandBuffer cb; CK(vkAllocateCommandBuffers(dev,&ai,&cb),"alloc cb");
    VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    bi.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    CK(vkBeginCommandBuffer(cb,&bi),"begin cb"); return cb;
}
static void endsub(VkCommandBuffer cb) {
    CK(vkEndCommandBuffer(cb),"end cb");
    VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO}; si.commandBufferCount=1; si.pCommandBuffers=&cb;
    CK(vkQueueSubmit(queue,1,&si,VK_NULL_HANDLE),"vkQueueSubmit");
    CK(vkQueueWaitIdle(queue),"vkQueueWaitIdle");
}

/* one opaque triangle at z = +1, and a TLAS with one instance of it. */
static void build_as(void) {
    static const float V[9] = {-1,-1,1,  1,-1,1,  0,1,1};
    VkBuffer vb, ib, bb, tb, sb1, sb2; VkDeviceMemory vm, im, bm, tm, sm1, sm2; void *p;
    mkbuf(sizeof V, VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT|
          VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR,
          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
          &vb,&vm,&p);
    memcpy(p,V,sizeof V);

    VkAccelerationStructureGeometryKHR g={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR};
    g.geometryType=VK_GEOMETRY_TYPE_TRIANGLES_KHR; g.flags=VK_GEOMETRY_OPAQUE_BIT_KHR;
    g.geometry.triangles.sType=VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_TRIANGLES_DATA_KHR;
    g.geometry.triangles.vertexFormat=VK_FORMAT_R32G32B32_SFLOAT;
    g.geometry.triangles.vertexData.deviceAddress=bufaddr(vb);
    g.geometry.triangles.vertexStride=12; g.geometry.triangles.maxVertex=2;
    g.geometry.triangles.indexType=VK_INDEX_TYPE_NONE_KHR;
    VkAccelerationStructureBuildGeometryInfoKHR bi={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR};
    bi.type=VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR;
    bi.flags=VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR;
    bi.mode=VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR;
    bi.geometryCount=1; bi.pGeometries=&g;
    uint32_t one=1;
    VkAccelerationStructureBuildSizesInfoKHR sz={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
    pSizes(dev,VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR,&bi,&one,&sz);
    mkbuf(sz.accelerationStructureSize,
          VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR|
          VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,&bb,&bm,NULL);
    mkbuf(sz.buildScratchSize+256, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|
          VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,&sb1,&sm1,NULL);
    VkAccelerationStructureCreateInfoKHR ci={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR};
    ci.buffer=bb; ci.size=sz.accelerationStructureSize;
    ci.type=VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR;
    VkAccelerationStructureKHR blas; CK(pCreateAS(dev,&ci,NULL,&blas),"create BLAS");
    bi.dstAccelerationStructure=blas; bi.scratchData.deviceAddress=bufaddr(sb1);
    VkAccelerationStructureBuildRangeInfoKHR r={0}; r.primitiveCount=1;
    const VkAccelerationStructureBuildRangeInfoKHR *pr=&r;
    VkCommandBuffer cb=begin(); pBuildAS(cb,1,&bi,&pr); endsub(cb);
    VkAccelerationStructureDeviceAddressInfoKHR di={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_DEVICE_ADDRESS_INFO_KHR};
    di.accelerationStructure=blas;
    VkDeviceAddress ba=pASAddr(dev,&di);
    printf("blas addr 0x%llx\n",(unsigned long long)ba);

    VkAccelerationStructureInstanceKHR inst; memset(&inst,0,sizeof inst);
    inst.transform.matrix[0][0]=1; inst.transform.matrix[1][1]=1; inst.transform.matrix[2][2]=1;
    inst.mask=0xFF; inst.accelerationStructureReference=(uint64_t)ba;
    mkbuf(sizeof inst, VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT|
          VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR,
          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
          &ib,&im,&p);
    memcpy(p,&inst,sizeof inst);
    VkAccelerationStructureGeometryKHR gi={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR};
    gi.geometryType=VK_GEOMETRY_TYPE_INSTANCES_KHR; gi.flags=VK_GEOMETRY_OPAQUE_BIT_KHR;
    gi.geometry.instances.sType=VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR;
    gi.geometry.instances.data.deviceAddress=bufaddr(ib);
    VkAccelerationStructureBuildGeometryInfoKHR ti={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR};
    ti.type=VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
    ti.flags=VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR;
    ti.mode=VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR;
    ti.geometryCount=1; ti.pGeometries=&gi;
    VkAccelerationStructureBuildSizesInfoKHR tsz={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR};
    pSizes(dev,VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR,&ti,&one,&tsz);
    mkbuf(tsz.accelerationStructureSize,
          VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR|
          VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,&tb,&tm,NULL);
    mkbuf(tsz.buildScratchSize+256, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|
          VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,&sb2,&sm2,NULL);
    VkAccelerationStructureCreateInfoKHR tci={VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR};
    tci.buffer=tb; tci.size=tsz.accelerationStructureSize;
    tci.type=VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
    VkAccelerationStructureKHR tlas; CK(pCreateAS(dev,&tci,NULL,&tlas),"create TLAS");
    /* the address query MUST precede the build: the layer's journal learns an
     * address here and only a build whose destination already has one can
     * refresh the slot (swap_layer.c, asj_note_addr -> bda_note_tlas). */
    di.accelerationStructure=tlas;
    VkDeviceAddress ta=pASAddr(dev,&di);
    printf("tlas addr 0x%llx\n",(unsigned long long)ta);
    ti.dstAccelerationStructure=tlas; ti.scratchData.deviceAddress=bufaddr(sb2);
    VkAccelerationStructureBuildRangeInfoKHR tr={0}; tr.primitiveCount=1;
    const VkAccelerationStructureBuildRangeInfoKHR *ptr=&tr;
    cb=begin(); pBuildAS(cb,1,&ti,&ptr); endsub(cb);
}

int main(int argc, char **argv) {
    const char *mode = argc>1 ? argv[1] : "none";
    const char *spv  = argc>2 ? argv[2] : NULL;
    if (spv && !strcmp(spv,"-")) spv=NULL;   /* "-" = create only */
    VkApplicationInfo app={VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.apiVersion=VK_API_VERSION_1_3;
    VkInstanceCreateInfo ii={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ii.pApplicationInfo=&app;
    VkInstance inst; CK(vkCreateInstance(&ii,NULL,&inst),"vkCreateInstance");
    uint32_t np=0; vkEnumeratePhysicalDevices(inst,&np,NULL);
    VkPhysicalDevice *pd=calloc(np,sizeof*pd); vkEnumeratePhysicalDevices(inst,&np,pd);
    VkPhysicalDeviceProperties props; int adv=0; phys=VK_NULL_HANDLE;
    for (uint32_t i=0;i<np;i++){
        uint32_t ne=0; vkEnumerateDeviceExtensionProperties(pd[i],NULL,&ne,NULL);
        VkExtensionProperties *ep=calloc(ne,sizeof*ep);
        vkEnumerateDeviceExtensionProperties(pd[i],NULL,&ne,ep);
        int as=0,rq=0;
        for(uint32_t k=0;k<ne;k++){
            if(!strcmp(ep[k].extensionName,VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME))as=1;
            if(!strcmp(ep[k].extensionName,VK_KHR_RAY_QUERY_EXTENSION_NAME))rq=1;
        }
        free(ep);
        if(as){phys=pd[i];adv=rq;vkGetPhysicalDeviceProperties(phys,&props);break;}
    }
    if(!phys){printf("FAIL no device with VK_KHR_acceleration_structure\n");return 4;}
    printf("device: %s  ray query advertised by ICD: %s\n",props.deviceName,adv?"yes":"NO");
    uint32_t nq=0; vkGetPhysicalDeviceQueueFamilyProperties(phys,&nq,NULL);
    VkQueueFamilyProperties *qp=calloc(nq,sizeof*qp);
    vkGetPhysicalDeviceQueueFamilyProperties(phys,&nq,qp);
    qfam=UINT32_MAX;
    for(uint32_t i=0;i<nq;i++) if(qp[i].queueFlags&VK_QUEUE_COMPUTE_BIT){qfam=i;break;}
    if(qfam==UINT32_MAX){printf("FAIL no compute queue\n");return 4;}
    float prio=1.0f;
    VkDeviceQueueCreateInfo q={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    q.queueFamilyIndex=qfam;q.queueCount=1;q.pQueuePriorities=&prio;
    /* deliberately does NOT list VK_KHR_ray_query and does NOT ask for a BDA
     * extension: bufferDeviceAddress arrives the way vkd3d-proton delivers it,
     * through VkPhysicalDeviceVulkan12Features, and ray query is the layer's job. */
    const char *exts[]={VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME,
                        VK_KHR_DEFERRED_HOST_OPERATIONS_EXTENSION_NAME};
    VkPhysicalDeviceAccelerationStructureFeaturesKHR as={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ACCELERATION_STRUCTURE_FEATURES_KHR};
    as.accelerationStructure=VK_TRUE;
    VkPhysicalDeviceVulkan12Features v12={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    v12.bufferDeviceAddress=VK_TRUE; v12.pNext=&as;
    VkDeviceCreateInfo dci={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.pNext=&v12; dci.queueCreateInfoCount=1; dci.pQueueCreateInfos=&q;
    dci.enabledExtensionCount=2; dci.ppEnabledExtensionNames=exts;
    CK(vkCreateDevice(phys,&dci,NULL,&dev),"vkCreateDevice");
    printf("device created with %u extensions requested by the app\n",dci.enabledExtensionCount);
    vkGetDeviceQueue(dev,qfam,0,&queue);
    VkCommandPoolCreateInfo pi={VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    pi.queueFamilyIndex=qfam; CK(vkCreateCommandPool(dev,&pi,NULL,&cpool),"cmd pool");
#define GD(n) (PFN_##n)vkGetDeviceProcAddr(dev,#n)
    pCreateAS=GD(vkCreateAccelerationStructureKHR);
    pSizes=GD(vkGetAccelerationStructureBuildSizesKHR);
    pASAddr=GD(vkGetAccelerationStructureDeviceAddressKHR);
    pBuildAS=GD(vkCmdBuildAccelerationStructuresKHR);
    if(!pCreateAS||!pSizes||!pASAddr||!pBuildAS){printf("FAIL AS entry points missing\n");return 4;}
    if(!strcmp(mode,"rq")) build_as();

    int nbad=0;
    if(spv){
        size_t n; uint32_t *code=slurp(spv,&n);
        VkShaderModuleCreateInfo smi={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        smi.codeSize=n; smi.pCode=code;
        VkShaderModule sm; VkResult r=vkCreateShaderModule(dev,&smi,NULL,&sm);
        printf("vkCreateShaderModule(%s, %zu B) -> %d\n",spv,n,r);
        if(r!=VK_SUCCESS){printf("RESULT: module rejected\n");return 5;}
        VkBuffer ob; VkDeviceMemory om; void *op;
        mkbuf(64, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
              VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
              &ob,&om,&op);
        memset(op,0xEE,64);
        VkDescriptorSetLayoutBinding b={0};
        b.binding=0;b.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        b.descriptorCount=1;b.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;
        VkDescriptorSetLayoutCreateInfo dl={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        dl.bindingCount=1;dl.pBindings=&b;
        VkDescriptorSetLayout dsl; CK(vkCreateDescriptorSetLayout(dev,&dl,NULL,&dsl),"dsl");
        VkPipelineLayoutCreateInfo pl={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
        pl.setLayoutCount=1; pl.pSetLayouts=&dsl;
        VkPipelineLayout plo; CK(vkCreatePipelineLayout(dev,&pl,NULL,&plo),"pipeline layout");
        VkComputePipelineCreateInfo cpi={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
        cpi.stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        cpi.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT; cpi.stage.module=sm; cpi.stage.pName="main";
        cpi.layout=plo;
        VkPipeline pipe; VkResult rp=vkCreateComputePipelines(dev,VK_NULL_HANDLE,1,&cpi,NULL,&pipe);
        printf("vkCreateComputePipelines -> %d\n",rp);
        if(rp!=VK_SUCCESS){printf("RESULT: PIPELINE REJECTED\n");return 6;}
        VkDescriptorPoolSize ps={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1};
        VkDescriptorPoolCreateInfo dp={VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
        dp.maxSets=1;dp.poolSizeCount=1;dp.pPoolSizes=&ps;
        VkDescriptorPool pool; CK(vkCreateDescriptorPool(dev,&dp,NULL,&pool),"desc pool");
        VkDescriptorSetAllocateInfo da={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
        da.descriptorPool=pool;da.descriptorSetCount=1;da.pSetLayouts=&dsl;
        VkDescriptorSet ds; CK(vkAllocateDescriptorSets(dev,&da,&ds),"desc set");
        VkDescriptorBufferInfo dbi={ob,0,VK_WHOLE_SIZE};
        VkWriteDescriptorSet wr={VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        wr.dstSet=ds;wr.dstBinding=0;wr.descriptorCount=1;
        wr.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;wr.pBufferInfo=&dbi;
        vkUpdateDescriptorSets(dev,1,&wr,0,NULL);
        VkCommandBuffer cb=begin();
        vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipe);
        vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,plo,0,1,&ds,0,NULL);
        vkCmdDispatch(cb,1,1,1);
        endsub(cb);
        uint32_t *o=(uint32_t*)op;
        printf("slot:");
        for(int k=0;k<8;k++) printf(" [%d]=0x%08x",k,o[k]);
        printf("\n");
        printf("rq_up=%u rq_dn=%u\n",o[8],o[9]);
    }
    for(int ai=3; ai<argc; ai++){
        size_t n2; uint32_t *c2=slurp(argv[ai],&n2);
        VkShaderModuleCreateInfo s2={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        s2.codeSize=n2; s2.pCode=c2;
        VkShaderModule m2; VkResult r2=vkCreateShaderModule(dev,&s2,NULL,&m2);
        if(r2!=VK_SUCCESS){printf("served %s -> %d\n",argv[ai],r2); nbad++;}
        free(c2);
    }
    vkDestroyDevice(dev,NULL);
    printf("RESULT: OK  served_failures=%d\n",nbad);
    return nbad?7:0;
}
EOC
gcc -O1 -o "$w/bt" "$w/bt.c" -lvulkan 2>"$w/cc.err" || {
    echo "selftest: could not build the probe (need libvulkan-dev):" >&2
    sed -n '1,5p' "$w/cc.err" >&2; exit 1; }

STAND=(); for h in "${IDS[@]}"; do STAND+=("$w/stand/$h.spv"); done
SYN_IDS=(bda0000000000001 bda0000000000002 bda0000000000010 bda0000000000011
         bda0000000000012 bda0000000000013 bda0000000000014 bda0000000000015)
SYNSTAND=(); for h in "${SYN_IDS[@]}"; do SYNSTAND+=("$w/stand/$h.spv"); done
for f in "${SYNSTAND[@]}"; do
    [[ -f "$f" ]] || { echo "selftest: missing stand-in $f" >&2; exit 1; }
done

run() { # run <log> <overlays> <mode> <dispatch|-> [extra args ...]
    local log="$1" ov="$2" mode="$3" disp="$4"; shift 4
    env CALLISTO_LAYER_DISABLE=1 VK_ADD_LAYER_PATH="$w/lay" \
        VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_bdatest \
        CALLISTO_OVERLAYS="$ov" CALLISTO_LOG="$log" "${EXTRA[@]}" \
        "$w/bt" "$mode" "$disp" "$@" >"$log.out" 2>&1
}
has() { grep -q -- "$2" "$1"; }
EXTRA=()

echo
echo "bda layer self-test  (layer: $MOD_DIR/libVkLayer_callisto_spvswap.so)"
echo "76 painted compute ids from swaps.bda-probe; 8 synthetic modules"
echo

# ---- case 0: the ABI in this file is the ABI in the layer ------------------
echo "case 0 -- the marker ABI is one ABI"
for k in CALLISTO_BDA_SLOT_V1 0x0BDA0001 0xCA115700 0xCA115701; do
    chk "swap_layer.c carries $k" "$(b grep -q -- "$k" "$MOD_DIR/swap_layer.c")"
done
chk "the layer's slot is 64 words (256 B)" \
    "$(b grep -q '#define CALLISTO_BDA_WORDS  *64' "$MOD_DIR/swap_layer.c")"
echo

# ---- case A: arm the slot and READ THE MAGIC BACK FROM A DISPATCH ----------
run "$w/a.log" bdasyn,bdafb magic "$w/stand/bda0000000000001.spv"; ra=$?
echo "case A -- Stage 2b: the slot is armed, fixed up, and read back by a dispatch"
grep -E '^(device:|device created|vkCreateShaderModule|vkCreateComputePipelines|slot:)' \
     "$w/a.log.out" | sed 's/^/    /'
grep -o '"ev":"bda","action":"[a-z]*","reason":"[a-z_]*","decide":"[a-z_]*","addr":"0x[0-9a-f]*"' \
     "$w/a.log" | sed 's/^/    /'
chk "probe exits 0"                          "$([[ $ra -eq 0 ]] && echo 1 || echo 0)"
chk "the layer ARMED the slot"               "$(b has "$w/a.log" '"ev":"bda","action":"armed"')"
chk "...on the app's own bufferDeviceAddress (decide=already_enabled_vk12)" \
    "$(b has "$w/a.log" '"decide":"already_enabled_vk12"')"
chk "...at a non-zero device address"        "$(bn has "$w/a.log" '"addr":"0x0","magic"')"
chk "the synthetic module was FIXED UP"      "$(b has "$w/a.log" '"ev":"bda_fixup"')"
chk "no bda_reject"                          "$(bn has "$w/a.log" '"ev":"bda_reject"')"
chk "the compute pipeline LINKED"            "$(b grep -q 'vkCreateComputePipelines -> 0' "$w/a.log.out")"
chk "THE DISPATCH READ THE MAGIC (slot[0] == 0xca115701)" \
    "$(b grep -q 'slot: \[0\]=0xca115701' "$w/a.log.out")"
chk "...and the buffer was NOT still the host fill (0xeeeeeeee)" \
    "$(bn grep -q 'slot: \[0\]=0xeeeeeeee' "$w/a.log.out")"
chk "slot[2]/[3] are zero with no TLAS built" \
    "$(b grep -q 'slot:.*\[2\]=0x00000000 \[3\]=0x00000000' "$w/a.log.out")"
echo

# ---- case B: Stage 2c -- a real TLAS address, and a real query -------------
run "$w/b.log" bdasyn,bdafb rq "$w/stand/bda0000000000002.spv"; rb=$?
echo "case B -- Stage 2c: the TLAS address reaches the slot and a COMPUTE ray query uses it"
grep -E '^(blas addr|tlas addr|vkCreateComputePipelines|slot:|rq_)' "$w/b.log.out" | sed 's/^/    /'
grep -o '"ev":"bda_tlas","addr":"0x[0-9a-f]*","prims":[0-9]*' "$w/b.log" | sed 's/^/    /'
chk "probe exits 0"                          "$([[ $rb -eq 0 ]] && echo 1 || echo 0)"
chk "the layer saw a TOP-LEVEL build and refreshed the slot" \
    "$(b has "$w/b.log" '"ev":"bda_tlas"')"
chk "...with prims 1 (a populated TLAS)"     "$(b has "$w/b.log" '"prims":1')"
ta=$(grep -o 'tlas addr 0x[0-9a-f]*' "$w/b.log.out" | head -1 | cut -d' ' -f3)
sl=$(grep -o 'slot:.*' "$w/b.log.out" | head -1)
lo=$(sed -n 's/.*\[2\]=0x\([0-9a-f]*\).*/\1/p' <<<"$sl")
hi=$(sed -n 's/.*\[3\]=0x\([0-9a-f]*\).*/\1/p' <<<"$sl")
comb=$(printf '0x%x' $(( 0x${hi:-0} * 4294967296 + 0x${lo:-0} )) 2>/dev/null)
chk "slot[3]:[2] == the TLAS device address the app queried ($comb vs $ta)" \
    "$([[ -n "$ta" && "$comb" == "$ta" ]] && echo 1 || echo 0)"
chk "the generation counter moved (slot[1] != 0)" \
    "$(bn grep -q 'slot:.*\[1\]=0x00000000' "$w/b.log.out")"
chk "THE RAY QUERY HIT the triangle above the origin (rq_up == 1)" \
    "$(b grep -q 'rq_up=1 ' "$w/b.log.out")"
chk "...and MISSED below it (rq_dn == 0) -- the query is not stuck on 'hit'" \
    "$(b grep -q 'rq_dn=0' "$w/b.log.out")"
chk "the layer enabled VK_KHR_ray_query for a device that never asked" \
    "$(b has "$w/b.log" '"ev":"rayq","action":"enabled"')"
echo

# ---- case C: the four conjuncts, one forgery each -------------------------
run "$w/c.log" bdasyn,bdafb none - "${SYNSTAND[@]}"; rc=$?
echo "case C -- forgeries: every conjunct of the fixup, refused one at a time"
chk "probe exits 0 (every forged module degraded, none broke the app)" \
    "$([[ $rc -eq 0 ]] && echo 1 || echo 0)"
declare -A FORGE=(
  [bda0000000000011]="id_out_of_bound|a marker naming two ids past the module's id bound"
  [bda0000000000012]="sentinel_mismatch|real ids, WRONG sentinel (a marker from another build)"
  [bda0000000000013]="sentinel_mismatch|real ids, real sentinel, WRONG magic"
  [bda0000000000014]="constants_do_not_hold_the_sentinel|a marker naming real uint constants that hold 0 and 1"
  [bda0000000000015]="two_markers|two markers in one module (ambiguous, so refused)"
)
for h in "${!FORGE[@]}"; do
    why="${FORGE[$h]%%|*}"; what="${FORGE[$h]#*|}"
    chk "rejected ($why): $what" \
        "$(b grep -q "\"ev\":\"bda_reject\",\"id\":\"$h.dxil\".*\"reason\":\"$why\",\"action\":\"next_overlay\"" "$w/c.log")"
    sz=$(stat -c%s "$w/lay/swaps.bdafb/$h.dxil.spv")
    chk "...and fell through to the NEXT OVERLAY, not to vanilla" \
        "$(b grep -q "swaps.bdafb/$h.dxil.spv\",\"size\":$sz}" "$w/c.log")"
done
# A module that carries the POINTER but no marker is served UNTOUCHED -- which
# is exactly why dev/patch_bda.py always emits the marker, and why the marker,
# not the capability or the constant's value, is the discriminator.
chk "the marker-free module was NEITHER fixed up NOR rejected (served verbatim)" \
    "$(bn grep -qE '"ev":"bda_(fixup|reject)","id":"bda0000000000010\.dxil"' "$w/c.log")"
nfix=$(grep -c '"ev":"bda_fixup"' "$w/c.log")
chk "exactly the 2 honest synthetic modules were fixed up (got $nfix)" \
    "$([[ $nfix -eq 2 ]] && echo 1 || echo 0)"
echo

# ---- case D: the real resolvers, served through the layer ------------------
echo "case D -- every live rung's real resolvers, served by the overlay, on the driver"
for rung in bda-probe bda-rq-probe bda-ctl; do
    ln -sfn "$MOD_DIR/swaps.$rung" "$w/lay/swaps.bdarung"
    run "$w/d_$rung.log" bdarung,bdafb none - "${STAND[@]}"; rd=$?
    chk "$rung: probe exits 0, no served module refused" \
        "$([[ $rd -eq 0 ]] && echo 1 || echo 0)"
    nhit=0
    for h in "${IDS[@]}"; do
        sz=$(stat -c%s "$MOD_DIR/swaps.$rung/$h.dxil.spv")
        grep -q "\"ev\":\"swap_load\".*swaps.bdarung/$h.dxil.spv\",\"size\":$sz}" "$w/d_$rung.log" \
          && grep -q "\"id\":\"$h.dxil\".*\"swap\":\"HIT\",\"result\":0" "$w/d_$rung.log" \
          && nhit=$((nhit+1))
    done
    chk "$rung: 76 of 76 real resolvers served at their shipped size and accepted (got $nhit)" \
        "$([[ $nhit -eq 76 ]] && echo 1 || echo 0)"
    nf=$(grep -c '"ev":"bda_fixup"' "$w/d_$rung.log")
    if [[ "$rung" == bda-ctl ]]; then
        chk "$rung: the CONTROL was never fixed up (got $nf, want 0)" \
            "$([[ $nf -eq 0 ]] && echo 1 || echo 0)"
    else
        # the layer caps the fixup log at BDA_MAX_FIXUP_LINES; the count below
        # is a floor, and the summary at device destroy carries the total.
        tot=$(grep -o '"ev":"bda_summary".*"fixups":[0-9]*' "$w/d_$rung.log" |
              sed 's/.*"fixups":\([0-9]*\).*/\1/' | tail -1)
        # bda-probe marks 76 modules; bda-rq-probe marks 75 (99bb7c2698997b2a
        # has no position chain, so --mode rq declines it and it ships as the
        # base bytes). The stand-in set is the same 76 either way.
        wantfix=76; [[ "$rung" == bda-rq-probe ]] && wantfix=75
        chk "$rung: the summary counts $wantfix fixups (got ${tot:-none})" \
            "$([[ "${tot:-0}" -eq $wantfix ]] && echo 1 || echo 0)"
    fi
done
echo

# ---- case E: no slot => refuse, and fall through to the next overlay -------
ln -sfn "$MOD_DIR/swaps.bda-probe" "$w/lay/swaps.bdarung"
EXTRA=(CALLISTO_BDA_DISABLE=1)
run "$w/e.log" bdarung,bdafb none - "${STAND[@]}"; re=$?
EXTRA=()
echo "case E -- CALLISTO_BDA_DISABLE=1: no slot, so every marked module is refused"
chk "probe still exits 0 (degrades, does not break)" "$([[ $re -eq 0 ]] && echo 1 || echo 0)"
chk "the layer skipped the slot, reason env_disabled" \
    "$(b has "$w/e.log" '"ev":"bda","action":"skipped","reason":"env_disabled"')"
nrej=$(grep -c '"ev":"bda_reject".*"action":"next_overlay"' "$w/e.log")
chk "all 76 marked resolvers rejected with action next_overlay (got $nrej)" \
    "$([[ $nrej -eq 76 ]] && echo 1 || echo 0)"
nfb=0
for h in "${IDS[@]}"; do
    sz=$(stat -c%s "$w/lay/swaps.bdafb/$h.dxil.spv")
    grep -q "\"ev\":\"swap_load\".*swaps.bdafb/$h.dxil.spv\",\"size\":$sz}" "$w/e.log" \
      && nfb=$((nfb+1))
done
chk "and all 76 fell through to the NEXT OVERLAY, not to vanilla (got $nfb)" \
    "$([[ $nfb -eq 76 ]] && echo 1 || echo 0)"
chk "no marked module went vanilla" \
    "$(bn grep -q '"id":"[0-9a-f]*\.dxil".*"swap":"none"' "$w/e.log")"
chk "no fixup happened at all"                "$(bn has "$w/e.log" '"ev":"bda_fixup"')"
echo

# ---- case F: with NO next overlay, a refused module must go vanilla --------
# The last line of defence in xCreateShaderModule: if the only overlay holding
# the module is refused, the app must still get a working shader.
EXTRA=(CALLISTO_BDA_DISABLE=1)
run "$w/f.log" bdarung none - "${STAND[@]}"; rf=$?
EXTRA=()
echo "case F -- refused with no fallback overlay: the app still gets its own module"
chk "probe exits 0"                           "$([[ $rf -eq 0 ]] && echo 1 || echo 0)"
nvan=$(grep -c '"ev":"bda_reject".*"action":"next_overlay"' "$w/f.log")
chk "all 76 refused (got $nvan)"              "$([[ $nvan -eq 76 ]] && echo 1 || echo 0)"
chk "and none was served a marker-carrying module anyway" \
    "$(bn has "$w/f.log" '"ev":"bda_fixup"')"
echo

rm -f "$w/lay/swaps.bdarung"
echo "=== $ok passed, $bad failed$( ((skip)) && echo ", $skip noted")"
exit $(( bad ? 1 : 0 ))
