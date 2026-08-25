/*
 * VK_LAYER_NGFXPROBE_probe -- minimal Vulkan logging layer for ngfx-replay analysis.
 *
 * Purpose: during replay of an .ngfx-capture, log (as JSONL) every Vulkan call
 * needed to resolve the vkd3d-proton descriptor chain offline:
 *   shader modules (hash), compute pipelines, images/views, buffers/memory,
 *   descriptor-buffer bindings, descriptor writes (vkGetDescriptorEXT),
 *   push constants, pipeline binds, dispatches.
 *
 * The layer is a "dumb logger": all resolution happens offline in Python.
 *
 * Env:
 *   NGFXPROBE_LOG          output path (default /tmp/ngfxprobe.jsonl)
 *   NGFXPROBE_SURVEY       1 = dump every CPU->image upload, not just the
 *                          narrow kernel-LUT filter (adds fnv/ew/eh/bpp fields)
 *   NGFXPROBE_SURVEY_HEX   max hex payload bytes per upload (default 4096)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>

#ifndef VK_LAYER_EXPORT
#define VK_LAYER_EXPORT __attribute__((visibility("default")))
#endif

/* ------------------------------------------------------------------ */
/* logging                                                             */
/* ------------------------------------------------------------------ */
static FILE *g_log;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_seq;

static void log_open(void) {
    const char *p = getenv("NGFXPROBE_LOG");
    if (!p) p = "/tmp/ngfxprobe.jsonl";
    g_log = fopen(p, "a");
    if (!g_log) g_log = stderr;
}

static void log_line(const char *s) {
    pthread_mutex_lock(&g_mu);
    if (g_log) { fputs(s, g_log); fputc('\n', g_log); fflush(g_log); }
    pthread_mutex_unlock(&g_mu);
}

/* emit into a big stack buffer; every event starts with seq + tag */
#define LOGF(...) do { \
    char b[8192]; \
    uint64_t q = __sync_fetch_and_add(&g_seq, 1); \
    int n = snprintf(b, sizeof b, "{\"seq\":%llu,", (unsigned long long)q); \
    snprintf(b + n, sizeof b - n, __VA_ARGS__); \
    log_line(b); \
} while (0)

static char *hexenc(char *out, const void *p, size_t n, size_t cap) {
    const unsigned char *b = p;
    size_t max = (cap - 1) / 2;
    if (n > max) n = max;
    for (size_t i = 0; i < n; i++) sprintf(out + 2 * i, "%02x", b[i]);
    out[2 * n] = 0;
    return out;
}

static uint64_t fnv1a64(const void *data, size_t len) {
    const unsigned char *p = data;
    uint64_t h = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < len; i++) { h ^= p[i]; h *= 0x100000001b3ull; }
    return h;
}

/* ------------------------------------------------------------------ */
/* tiny tracking maps: image dims, buffer binds, memory maps           */
/* (used to hex-dump copy sources into small float images)             */
/* ------------------------------------------------------------------ */
static pthread_mutex_t g_mapmu = PTHREAD_MUTEX_INITIALIZER;

#define SLOT_SZ (1u << 21)
typedef struct { uint64_t k, v; } Slot;      /* v==0 -> empty */
static Slot *g_imgmap, *g_bindmap, *g_memmap;

typedef struct { uint64_t mem, off; } BindEnt;
typedef struct { uint64_t ptr, off, size; } MapEnt;
static BindEnt *g_bind; static uint32_t g_bind_n;
static MapEnt *g_map;  static uint32_t g_map_n;

static Slot *slot_for(Slot **tab, uint64_t key) {
    if (!*tab) *tab = calloc(SLOT_SZ, sizeof(Slot));
    uint64_t h = (key * 0x9E3779B97F4A7C15ull) >> 32;
    for (uint32_t i = 0; i < SLOT_SZ; i++) {
        Slot *s = &(*tab)[(h + i) & (SLOT_SZ - 1)];
        if (s->k == key || s->v == 0) return s;
    }
    return NULL;
}
static void map_put(Slot **tab, uint64_t key, uint64_t val) {
    pthread_mutex_lock(&g_mapmu);
    Slot *s = slot_for(tab, key);
    if (s) { s->k = key; s->v = val; }
    pthread_mutex_unlock(&g_mapmu);
}
static uint64_t map_get(Slot **tab, uint64_t key) {
    pthread_mutex_lock(&g_mapmu);
    Slot *s = *tab ? slot_for(tab, key) : NULL;
    uint64_t v = (s && s->k == key) ? s->v : 0;
    pthread_mutex_unlock(&g_mapmu);
    return v;
}
static uint32_t bind_put(uint64_t mem, uint64_t off) {
    pthread_mutex_lock(&g_mapmu);
    if (!g_bind) g_bind = malloc(1 << 24);
    uint32_t i = ++g_bind_n;
    g_bind[i].mem = mem; g_bind[i].off = off;
    pthread_mutex_unlock(&g_mapmu);
    return i;
}
static uint32_t mapent_put(uint64_t ptr, uint64_t off, uint64_t size) {
    pthread_mutex_lock(&g_mapmu);
    if (!g_map) g_map = malloc(1 << 24);
    uint32_t i = ++g_map_n;
    g_map[i].ptr = ptr; g_map[i].off = off; g_map[i].size = size;
    pthread_mutex_unlock(&g_mapmu);
    return i;
}

/* ---------------- SSS dispatch CB sniffer --------------------------- */
/* SSS_Blur shader module fnv1a-64 hashes (vertical/horizontal) */
#define SSS_FNV_V 0x8bdb51faadec8c17ull
#define SSS_FNV_H 0xf892d76f87bc344cull

static Slot *g_modmap;   /* shader module -> fnv */
static uint64_t g_sss_pipes[64]; static uint32_t g_sss_pipes_n;

typedef struct {
    uint64_t pipe;
    unsigned char pc[64]; int pc_len;
    uint64_t setva[8];
    uint64_t infoaddr[8];
} CmdState;
static CmdState *g_cmd; static uint32_t g_cmd_n;
static Slot *g_cmdmap;

static CmdState *cmd_state(uint64_t cb) {
    uint64_t idx = map_get(&g_cmdmap, cb);
    if (!idx) {
        pthread_mutex_lock(&g_mapmu);
        if (!g_cmd) g_cmd = calloc(4096, sizeof(CmdState));
        idx = ++g_cmd_n;
        pthread_mutex_unlock(&g_mapmu);
        map_put(&g_cmdmap, cb, idx);
    }
    return &g_cmd[idx];
}
static int is_sss_pipe(uint64_t p) {
    for (uint32_t i = 0; i < g_sss_pipes_n; i++)
        if (g_sss_pipes[i] == p) return 1;
    return 0;
}

/* buffer VA table for VA->CPU resolution */
typedef struct { uint64_t lo, hi, buf; } VaEnt;
static VaEnt *g_va; static uint32_t g_va_n;
static void va_add(uint64_t lo, uint64_t size, uint64_t buf) {
    pthread_mutex_lock(&g_mapmu);
    if (!g_va) g_va = malloc(1 << 26);
    g_va[++g_va_n].lo = lo; g_va[g_va_n].hi = lo + size; g_va[g_va_n].buf = buf;
    pthread_mutex_unlock(&g_mapmu);
}
static uint64_t va_to_cpu(uint64_t va) {
    pthread_mutex_lock(&g_mapmu);
    uint64_t buf = 0, lo = 0;
    for (uint32_t i = g_va_n; i >= 1; i--)
        if (va >= g_va[i].lo && va < g_va[i].hi) {
            buf = g_va[i].buf; lo = g_va[i].lo; break;
        }
    pthread_mutex_unlock(&g_mapmu);
    if (!buf) return 0;
    uint64_t bi = map_get(&g_bindmap, buf);
    if (!bi) return 0;
    pthread_mutex_lock(&g_mapmu);
    uint64_t mem = g_bind[bi].mem, off = g_bind[bi].off;
    pthread_mutex_unlock(&g_mapmu);
    uint64_t mi = map_get(&g_memmap, mem);
    if (!mi) return 0;
    pthread_mutex_lock(&g_mapmu);
    uint64_t ptr = g_map[mi].ptr, moff = g_map[mi].off;
    pthread_mutex_unlock(&g_mapmu);
    return ptr + (off - moff) + (va - lo);
}
static Slot *g_bufsizemap;

/* scan all mapped memory for the SSS per-dispatch CB pattern:
   [f32 depthScale][i32 baseX in {0,15,24}][i32 taps in {6,9,15}][?] */
static int g_scanned;
static void scan_for_sss_cb(void) {
    if (g_scanned) return;
    g_scanned = 1;
    pthread_mutex_lock(&g_mapmu);
    uint32_t nmap = g_map_n;
    pthread_mutex_unlock(&g_mapmu);
    uint32_t hits = 0;
    for (uint32_t mi = 1; mi <= nmap && hits < 48; mi++) {
        pthread_mutex_lock(&g_mapmu);
        uint64_t ptr = g_map[mi].ptr, off = g_map[mi].off, size = g_map[mi].size;
        pthread_mutex_unlock(&g_mapmu);
        if (!ptr || size > (1ull << 31)) continue;
        const unsigned char *p = (const unsigned char *)(uintptr_t)ptr;
        for (uint64_t i = 0; i + 16 <= size && hits < 48; i += 4) {
            uint32_t w1, w2;
            float w0;
            memcpy(&w0, p + i, 4); memcpy(&w1, p + i + 4, 4);
            memcpy(&w2, p + i + 8, 4);
            if (!(w1 == 0 || w1 == 15 || w1 == 24)) continue;
            if (!(w2 == 6 || w2 == 9 || w2 == 15)) continue;
            if (!(w0 > 1e-6f && w0 < 1e8f)) continue;
            uint64_t q = __sync_fetch_and_add(&g_seq, 1);
            pthread_mutex_lock(&g_mu);
            if (g_log) {
                fprintf(g_log, "{\"seq\":%llu,\"ev\":\"SSSCBHit\",\"mapIdx\":%u,"
                        "\"off\":%llu,\"w0\":%g,\"w1\":%u,\"w2\":%u,"
                        "\"w3\":\"%02x%02x%02x%02x\"}\n",
                        (unsigned long long)q, mi, (unsigned long long)(off + i),
                        w0, w1, w2, p[i+12], p[i+13], p[i+14], p[i+15]);
                fflush(g_log);
            }
            pthread_mutex_unlock(&g_mu);
            hits++;
        }
    }
}

/* at SSS dispatch: dump CBV descriptor + CB content */
static void sss_sniff(uint64_t cb_handle, const char *evname) {
    CmdState *st = cmd_state(cb_handle);
    if (!is_sss_pipe(st->pipe) || st->pc_len < 8) return;
    scan_for_sss_cb();
    uint32_t regs0, regs1;
    memcpy(&regs0, st->pc + 0, 4); memcpy(&regs1, st->pc + 4, 4);
    char msg[4096]; int n = 0;
    n += snprintf(msg + n, sizeof msg - n, "\"ev\":\"%s\",\"pipe\":\"%p\","
                  "\"regs0\":%u,\"regs1\":%u,", evname, (void *)st->pipe,
                  regs0, regs1);
    /* set2 binding0 UBO descriptors, 8 bytes each, at (regs0+k) */
    uint64_t set2 = st->setva[2];
    for (int k = 0; k <= 6; k += 6) {
        uint64_t descva = set2 + (uint64_t)(regs0 + k) * 8;
        uint64_t cpu = va_to_cpu(descva);
        char hex[17] = ""; uint64_t cbva = 0, cbcpu = 0; char cbhex[33] = "";
        if (cpu) {
            hexenc(hex, (const void *)(uintptr_t)cpu, 8, sizeof hex);
            /* NVIDIA UBO descriptor: guess VA in low 48 bits */
            uint64_t raw; memcpy(&raw, (const void *)(uintptr_t)cpu, 8);
            uint64_t cand = raw & 0x0000FFFFFFFFFFFFull;
            cbcpu = va_to_cpu(cand);
            if (cbcpu) { cbva = cand; hexenc(cbhex, (const void *)(uintptr_t)cbcpu, 16, sizeof cbhex); }
        }
        n += snprintf(msg + n, sizeof msg - n, "\"cb%d\":{\"descva\":\"0x%llx\","
                      "\"desc\":\"%s\",\"cbva\":\"0x%llx\",\"cb\":\"%s\"},",
                      k, (unsigned long long)descva, hex,
                      (unsigned long long)cbva, cbhex);
    }
    /* set1 binding1 SRV descriptors, 16 bytes each, at (regs1+4); boff unknown */
    uint64_t set1 = st->setva[1];
    n += snprintf(msg + n, sizeof msg - n, "\"srv_candidates\":[");
    for (int b = 0; b < 4; b++) {
        static const int boff[4] = {0, 16, 32, 64};
        uint64_t descva = set1 + boff[b] + (uint64_t)(regs1 + 4) * 16;
        uint64_t cpu = va_to_cpu(descva);
        char hex[33] = "";
        if (cpu) hexenc(hex, (const void *)(uintptr_t)cpu, 16, sizeof hex);
        n += snprintf(msg + n, sizeof msg - n, "%s{\"boff\":%d,\"hex\":\"%s\"}",
                      b ? "," : "", boff[b], hex);
    }
    n += snprintf(msg + n, sizeof msg - n, "]}");
    uint64_t q = __sync_fetch_and_add(&g_seq, 1);
    pthread_mutex_lock(&g_mu);
    if (g_log) { fprintf(g_log, "{\"seq\":%llu,%s\n", (unsigned long long)q, msg); fflush(g_log); }
    pthread_mutex_unlock(&g_mu);
    /* raw descriptor-table context dumps */
    struct { uint64_t base; const char *tag; } ctx[2] = {
        { st->setva[2] + (uint64_t)regs0 * 8, "cbvtab" },
        { st->setva[1] + (uint64_t)regs1 * 16, "srvtab" },
    };
    for (int t = 0; t < 2; t++) {
        uint64_t cpu = ctx[t].base ? va_to_cpu(ctx[t].base) : 0;
        if (!cpu) continue;
        char *big = malloc(512 + 1);
        hexenc(big, (const void *)(uintptr_t)cpu, 256, 513);
        uint64_t q2 = __sync_fetch_and_add(&g_seq, 1);
        pthread_mutex_lock(&g_mu);
        if (g_log) {
            fprintf(g_log, "{\"seq\":%llu,\"ev\":\"SSSTab\",\"tag\":\"%s\","
                    "\"va\":\"0x%llx\",\"hex\":\"%s\"}\n",
                    (unsigned long long)q2, ctx[t].tag,
                    (unsigned long long)ctx[t].base, big);
            fflush(g_log);
        }
        pthread_mutex_unlock(&g_mu);
        free(big);
    }
}

/* Uncompressed VkFormat -> bytes per pixel. 0 = compressed/unknown, which the
 * survey reports without a byte count rather than guessing a stride. */
static uint32_t fmt_bpp(uint32_t f) {
    if (f >= 1 && f <= 8) return 2;                     /* packed 16-bit */
    if (f >= 9 && f <= 15) return 1;                    /* R8 */
    if (f >= 16 && f <= 22) return 2;                   /* R8G8 */
    if (f >= 23 && f <= 36) return 3;                   /* R8G8B8 / B8G8R8 */
    if (f >= 37 && f <= 50) return 4;                   /* R8G8B8A8 / B8G8R8A8 */
    if (f >= 51 && f <= 69) return 4;                   /* A8B8G8R8 / A2 packed32 */
    if (f >= 70 && f <= 76) return 2;                   /* R16 */
    if (f >= 77 && f <= 83) return 4;                   /* R16G16 */
    if (f >= 84 && f <= 90) return 6;                   /* R16G16B16 */
    if (f >= 91 && f <= 97) return 8;                   /* R16G16B16A16 */
    if (f >= 98 && f <= 100) return 4;                  /* R32 */
    if (f >= 101 && f <= 103) return 8;                 /* R32G32 */
    if (f >= 104 && f <= 106) return 12;                /* R32G32B32 */
    if (f >= 107 && f <= 109) return 16;                /* R32G32B32A32 */
    if (f >= 110 && f <= 112) return 8;                 /* R64 */
    if (f >= 113 && f <= 115) return 16;                /* R64G64 */
    if (f >= 116 && f <= 118) return 24;                /* R64G64B64 */
    if (f >= 119 && f <= 121) return 32;                /* R64G64B64A64 */
    if (f == 122 || f == 123) return 4;                 /* B10G11R11 / E5B9G9R9 */
    if (f == 124) return 2;                             /* D16 */
    if (f == 125 || f == 126) return 4;                 /* X8D24 / D32 */
    if (f == 127) return 1;                             /* S8_UINT */
    return 0;                                           /* depth-stencil combos, BC/ASTC */
}

/* Survey mode (NGFXPROBE_SURVEY=1) widens the dump from the narrow kernel-LUT
 * filter to every CPU->image upload, so the whole capture's LUT/noise/grading
 * texture inventory can be enumerated in one replay. Hex payload is capped by
 * NGFXPROBE_SURVEY_HEX (default 4096 bytes) to keep the log tractable; the
 * fnv1a64 content hash is always emitted so uploads can be diffed across
 * captures for determinism regardless of size. */
static int g_survey = -1;
static uint64_t g_survey_hex = 4096;

static void survey_init(void) {
    const char *s = getenv("NGFXPROBE_SURVEY");
    g_survey = (s && *s && *s != '0') ? 1 : 0;
    const char *h = getenv("NGFXPROBE_SURVEY_HEX");
    if (h && *h) g_survey_hex = strtoull(h, NULL, 0);
}

/* dump copy-source bytes when dst is a small float image (kernel LUT hunt),
 * or -- under NGFXPROBE_SURVEY -- for every upload */
static void maybe_dump_imgcopy(const void *src, const void *dst,
                               uint64_t bufferOffset,
                               uint32_t ew, uint32_t eh) {
    if (g_survey < 0) survey_init();
    uint64_t info = map_get(&g_imgmap, (uint64_t)dst);
    if (!info) return;
    uint32_t w = (uint32_t)(info >> 40), h = (uint32_t)((info >> 24) & 0xffff),
             fmt = (uint32_t)(info & 0xffffff);
    uint32_t bpp;
    if (g_survey) {
        bpp = fmt_bpp(fmt);
        if (!bpp) return; /* compressed: stride unknown, nothing safe to read */
    } else {
        if (!(h <= 16 && w >= 4 && w <= 512 && (fmt == 97 || fmt == 109))) return;
        bpp = fmt == 97 ? 8 : 16;
    }
    /* In survey mode size the read from the copy region, which is what this
     * call actually writes; the narrow path keeps whole-image sizing so its
     * output stays byte-identical to previous runs. */
    uint64_t bytes = g_survey
        ? (uint64_t)(ew ? ew : w) * (eh ? eh : h) * bpp
        : (uint64_t)w * h * bpp;
    uint64_t cap = g_survey ? g_survey_hex : 65536;
    uint64_t bi = map_get(&g_bindmap, (uint64_t)src);
    const char *hex = NULL; char *big = NULL;
    uint64_t hash = 0; int hashed = 0;
    if (bi) {
        pthread_mutex_lock(&g_mapmu);
        uint64_t mem = g_bind[bi].mem, off = g_bind[bi].off;
        pthread_mutex_unlock(&g_mapmu);
        uint64_t mi = map_get(&g_memmap, mem);
        if (mi) {
            pthread_mutex_lock(&g_mapmu);
            uint64_t ptr = g_map[mi].ptr, moff = g_map[mi].off, msz = g_map[mi].size;
            pthread_mutex_unlock(&g_mapmu);
            uint64_t rel = (off - moff) + bufferOffset;
            if (rel + bytes > msz) bytes = rel < msz ? msz - rel : 0;
            /* Hash the full payload even when the hex dump is truncated, so
             * two captures can be compared for determinism on large uploads. */
            hash = fnv1a64((const void *)(uintptr_t)(ptr + rel), bytes);
            hashed = 1;
            uint64_t dumped = bytes > cap ? cap : bytes;
            big = malloc(2 * dumped + 1);
            hexenc(big, (const void *)(uintptr_t)(ptr + rel), dumped, 2 * dumped + 1);
            hex = big;
        }
    }
    uint64_t q = __sync_fetch_and_add(&g_seq, 1);
    pthread_mutex_lock(&g_mu);
    if (g_log) {
        fprintf(g_log, "{\"seq\":%llu,\"ev\":\"CopyImgDump\",\"src\":\"%p\","
                "\"dst\":\"%p\",\"bufOff\":%llu,\"w\":%u,\"h\":%u,\"fmt\":%u,"
                "\"bytes\":%llu",
                (unsigned long long)q, src, dst,
                (unsigned long long)bufferOffset, w, h, fmt,
                (unsigned long long)bytes);
        if (g_survey) {
            fprintf(g_log, ",\"ew\":%u,\"eh\":%u,\"bpp\":%u,\"trunc\":%d",
                    ew, eh, bpp, bytes > cap ? 1 : 0);
            if (hashed)
                fprintf(g_log, ",\"fnv\":\"%016llx\"", (unsigned long long)hash);
        }
        fprintf(g_log, ",\"hex\":\"%s\"}\n", hex ? hex : "");
        fflush(g_log);
    }
    pthread_mutex_unlock(&g_mu);
    free(big);
}

/* ------------------------------------------------------------------ */
/* dispatch tables (single instance/device is enough for ngfx-replay)  */
/* ------------------------------------------------------------------ */
typedef struct {
    VkInstance inst;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkCreateDevice CreateDevice;
    PFN_vkGetPhysicalDeviceProperties2 GetPhysicalDeviceProperties2;
    PFN_vkGetPhysicalDeviceProperties2KHR GetPhysicalDeviceProperties2KHR;
    PFN_vkGetPhysicalDeviceMemoryProperties GetPhysicalDeviceMemoryProperties;
    PFN_vkDestroyInstance DestroyInstance;
} InstData;

typedef struct {
    VkDevice dev;
    VkPhysicalDevice phys;
    PFN_vkGetDeviceProcAddr gdpa;
    PFN_vkDestroyDevice DestroyDevice;
    PFN_vkCreateShaderModule CreateShaderModule;
    PFN_vkCreateComputePipelines CreateComputePipelines;
    PFN_vkCreateGraphicsPipelines CreateGraphicsPipelines;
    PFN_vkCreateRayTracingPipelinesKHR CreateRayTracingPipelinesKHR;
    PFN_vkCreatePipelineLayout CreatePipelineLayout;
    PFN_vkCreateDescriptorSetLayout CreateDescriptorSetLayout;
    PFN_vkGetDescriptorSetLayoutBindingOffsetEXT GetDescriptorSetLayoutBindingOffsetEXT;
    PFN_vkCreateImage CreateImage;
    PFN_vkCreateImageView CreateImageView;
    PFN_vkCreateBuffer CreateBuffer;
    PFN_vkCreateBufferView CreateBufferView;
    PFN_vkAllocateMemory AllocateMemory;
    PFN_vkBindBufferMemory BindBufferMemory;
    PFN_vkBindBufferMemory2 BindBufferMemory2;
    PFN_vkBindBufferMemory2KHR BindBufferMemory2KHR;
    PFN_vkBindImageMemory BindImageMemory;
    PFN_vkGetBufferDeviceAddress GetBufferDeviceAddress;
    PFN_vkGetBufferDeviceAddressKHR GetBufferDeviceAddressKHR;
    PFN_vkMapMemory MapMemory;
    PFN_vkMapMemory2KHR MapMemory2KHR;
    PFN_vkUnmapMemory UnmapMemory;
    PFN_vkSetDebugUtilsObjectNameEXT SetDebugUtilsObjectNameEXT;
    PFN_vkGetDescriptorEXT GetDescriptorEXT;
    PFN_vkCmdBindPipeline CmdBindPipeline;
    PFN_vkCmdPushConstants CmdPushConstants;
    PFN_vkCmdBindDescriptorBuffersEXT CmdBindDescriptorBuffersEXT;
    PFN_vkCmdSetDescriptorBufferOffsetsEXT CmdSetDescriptorBufferOffsetsEXT;
    PFN_vkCmdDispatch CmdDispatch;
    PFN_vkCmdDispatchIndirect CmdDispatchIndirect;
    PFN_vkCmdTraceRaysKHR CmdTraceRaysKHR;
    PFN_vkCmdCopyBufferToImage CmdCopyBufferToImage;
    PFN_vkCmdCopyBufferToImage2KHR CmdCopyBufferToImage2KHR;
    PFN_vkQueueSubmit QueueSubmit;
    PFN_vkQueueSubmit2 QueueSubmit2;
    PFN_vkQueueSubmit2KHR QueueSubmit2KHR;
    PFN_vkQueuePresentKHR QueuePresentKHR;
} DevData;

static InstData g_inst[4]; static int g_ninst;
static DevData g_dev[4];   static int g_ndev;

static InstData *find_inst(VkInstance i) {
    for (int k = 0; k < g_ninst; k++) if (g_inst[k].inst == i) return &g_inst[k];
    return NULL;
}
static DevData *find_dev(VkDevice d) {
    for (int k = 0; k < g_ndev; k++) if (g_dev[k].dev == d) return &g_dev[k];
    return NULL;
}
/* command buffers / queues: locate owning device via loader's private table */
static DevData *dev_from_handle(void *h) {
    /* The dispatchable handle's first field is the loader's dispatch table ptr;
       but simplest robust approach: search known devices by walking our table
       via the layer_data_map is overkill -- ngfx-replay uses one device. */
    (void)h;
    return g_ndev ? &g_dev[g_ndev - 1] : NULL;
}

/* ------------------------------------------------------------------ */
/* instance-level intercepts                                           */
/* ------------------------------------------------------------------ */
static VkResult VKAPI_CALL xCreateInstance(const VkInstanceCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkInstance *pInst) {
    /* advance loader chain */
    const VkLayerInstanceCreateInfo *lc = ci->pNext;
    while (lc && !(lc->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO &&
                   lc->function == VK_LAYER_LINK_INFO))
        lc = lc->pNext;
    if (!lc) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr next_gipa = lc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkCreateInstance next_create = (PFN_vkCreateInstance)
        next_gipa(NULL, "vkCreateInstance");
    /* move the chain info forward so the next layer sees its own link */
    VkLayerInstanceCreateInfo save = *lc;
    /* temporarily point this link at next entry */
    ((VkLayerInstanceCreateInfo *)lc)->u.pLayerInfo = lc->u.pLayerInfo->pNext;
    VkResult r = next_create(ci, ac, pInst);
    ((VkLayerInstanceCreateInfo *)lc)->u.pLayerInfo = save.u.pLayerInfo;
    if (r != VK_SUCCESS) return r;

    InstData *d = &g_inst[g_ninst < 4 ? g_ninst++ : 3];
    memset(d, 0, sizeof *d);
    d->inst = *pInst;
    d->gipa = next_gipa;
    d->CreateDevice = (PFN_vkCreateDevice)next_gipa(*pInst, "vkCreateDevice");
    d->GetPhysicalDeviceProperties2 = (PFN_vkGetPhysicalDeviceProperties2)
        next_gipa(*pInst, "vkGetPhysicalDeviceProperties2");
    d->GetPhysicalDeviceProperties2KHR = (PFN_vkGetPhysicalDeviceProperties2KHR)
        next_gipa(*pInst, "vkGetPhysicalDeviceProperties2KHR");
    d->GetPhysicalDeviceMemoryProperties = (PFN_vkGetPhysicalDeviceMemoryProperties)
        next_gipa(*pInst, "vkGetPhysicalDeviceMemoryProperties");
    d->DestroyInstance = (PFN_vkDestroyInstance)next_gipa(*pInst, "vkDestroyInstance");
    LOGF("\"ev\":\"vkCreateInstance\",\"inst\":\"%p\"}", (void *)*pInst);
    return r;
}

static void log_desc_buf_props(const VkPhysicalDeviceProperties2 *p) {
    const void *c = p->pNext;
    while (c) {
        const VkStructureType st = *(const VkStructureType *)c;
        if (st == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_BUFFER_PROPERTIES_EXT) {
            const VkPhysicalDeviceDescriptorBufferPropertiesEXT *db = c;
            LOGF("\"ev\":\"DescriptorBufferProps\","
                 "\"samplerDescriptorSize\":%zu,"
                 "\"combinedImageSamplerDescriptorSize\":%zu,"
                 "\"sampledImageDescriptorSize\":%zu,"
                 "\"storageImageDescriptorSize\":%zu,"
                 "\"uniformTexelBufferDescriptorSize\":%zu,"
                 "\"storageTexelBufferDescriptorSize\":%zu,"
                 "\"uniformBufferDescriptorSize\":%zu,"
                 "\"storageBufferDescriptorSize\":%zu,"
                 "\"inputAttachmentDescriptorSize\":%zu,"
                 "\"accelerationStructureDescriptorSize\":%zu}",
                 db->samplerDescriptorSize, db->combinedImageSamplerDescriptorSize,
                 db->sampledImageDescriptorSize, db->storageImageDescriptorSize,
                 db->uniformTexelBufferDescriptorSize,
                 db->storageTexelBufferDescriptorSize,
                 db->uniformBufferDescriptorSize, db->storageBufferDescriptorSize,
                 db->inputAttachmentDescriptorSize,
                 db->accelerationStructureDescriptorSize);
        }
        c = ((const VkBaseInStructure *)c)->pNext;
    }
}

static void VKAPI_CALL xGetPhysicalDeviceProperties2(VkPhysicalDevice pd,
        VkPhysicalDeviceProperties2 *p) {
    InstData *d = find_inst(g_inst[0].inst);
    if (d && d->GetPhysicalDeviceProperties2) d->GetPhysicalDeviceProperties2(pd, p);
    log_desc_buf_props(p);
}
static void VKAPI_CALL xGetPhysicalDeviceProperties2KHR(VkPhysicalDevice pd,
        VkPhysicalDeviceProperties2 *p) {
    InstData *d = find_inst(g_inst[0].inst);
    if (d && d->GetPhysicalDeviceProperties2KHR) d->GetPhysicalDeviceProperties2KHR(pd, p);
    else if (d && d->GetPhysicalDeviceProperties2) d->GetPhysicalDeviceProperties2(pd, p);
    log_desc_buf_props(p);
}

static void VKAPI_CALL xGetPhysicalDeviceMemoryProperties(VkPhysicalDevice pd,
        VkPhysicalDeviceMemoryProperties *p) {
    InstData *d = find_inst(g_inst[0].inst);
    if (d && d->GetPhysicalDeviceMemoryProperties) d->GetPhysicalDeviceMemoryProperties(pd, p);
    for (uint32_t i = 0; i < p->memoryTypeCount && i < 32; i++)
        LOGF("\"ev\":\"MemoryType\",\"idx\":%u,\"flags\":%u,\"heap\":%u}",
             i, p->memoryTypes[i].propertyFlags, p->memoryTypes[i].heapIndex);
}

/* ------------------------------------------------------------------ */
/* device creation                                                     */
/* ------------------------------------------------------------------ */
#define GRAB(field, name) \
    d->field = (PFN_vk##field)d->gdpa(dev, "vk" #name)

static VkResult VKAPI_CALL xCreateDevice(VkPhysicalDevice phys,
        const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *ac, VkDevice *pDev) {
    const VkLayerDeviceCreateInfo *lc = ci->pNext;
    while (lc && !(lc->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO &&
                   lc->function == VK_LAYER_LINK_INFO))
        lc = lc->pNext;
    if (!lc) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr next_gipa = lc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr next_gdpa = lc->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    InstData *id = g_ninst ? &g_inst[g_ninst - 1] : NULL;
    PFN_vkCreateDevice next_create = id ? id->CreateDevice : NULL;
    if (!next_create) next_create = (PFN_vkCreateDevice)
        next_gipa(g_ninst ? g_inst[g_ninst - 1].inst : VK_NULL_HANDLE, "vkCreateDevice");
    ((VkLayerDeviceCreateInfo *)lc)->u.pLayerInfo = lc->u.pLayerInfo->pNext;
    VkResult r = next_create(phys, ci, ac, pDev);
    /* restore not strictly needed after success/failure for loader */
    if (r != VK_SUCCESS) return r;

    VkDevice dev = *pDev;
    DevData *d = &g_dev[g_ndev < 4 ? g_ndev++ : 3];
    memset(d, 0, sizeof *d);
    d->dev = dev; d->phys = phys; d->gdpa = next_gdpa;
    GRAB(DestroyDevice, DestroyDevice);
    GRAB(CreateShaderModule, CreateShaderModule);
    GRAB(CreateComputePipelines, CreateComputePipelines);
    GRAB(CreateGraphicsPipelines, CreateGraphicsPipelines);
    GRAB(CreateRayTracingPipelinesKHR, CreateRayTracingPipelinesKHR);
    GRAB(CreatePipelineLayout, CreatePipelineLayout);
    GRAB(CreateDescriptorSetLayout, CreateDescriptorSetLayout);
    GRAB(GetDescriptorSetLayoutBindingOffsetEXT, GetDescriptorSetLayoutBindingOffsetEXT);
    GRAB(CreateImage, CreateImage);
    GRAB(CreateImageView, CreateImageView);
    GRAB(CreateBuffer, CreateBuffer);
    GRAB(CreateBufferView, CreateBufferView);
    GRAB(AllocateMemory, AllocateMemory);
    GRAB(BindBufferMemory, BindBufferMemory);
    GRAB(BindBufferMemory2, BindBufferMemory2);
    GRAB(BindBufferMemory2KHR, BindBufferMemory2KHR);
    GRAB(BindImageMemory, BindImageMemory);
    GRAB(GetBufferDeviceAddress, GetBufferDeviceAddress);
    GRAB(GetBufferDeviceAddressKHR, GetBufferDeviceAddressKHR);
    GRAB(MapMemory, MapMemory);
    GRAB(MapMemory2KHR, MapMemory2KHR);
    GRAB(UnmapMemory, UnmapMemory);
    GRAB(SetDebugUtilsObjectNameEXT, SetDebugUtilsObjectNameEXT);
    GRAB(GetDescriptorEXT, GetDescriptorEXT);
    GRAB(CmdBindPipeline, CmdBindPipeline);
    GRAB(CmdPushConstants, CmdPushConstants);
    GRAB(CmdBindDescriptorBuffersEXT, CmdBindDescriptorBuffersEXT);
    GRAB(CmdSetDescriptorBufferOffsetsEXT, CmdSetDescriptorBufferOffsetsEXT);
    GRAB(CmdDispatch, CmdDispatch);
    GRAB(CmdDispatchIndirect, CmdDispatchIndirect);
    GRAB(CmdTraceRaysKHR, CmdTraceRaysKHR);
    GRAB(CmdCopyBufferToImage, CmdCopyBufferToImage);
    GRAB(CmdCopyBufferToImage2KHR, CmdCopyBufferToImage2KHR);
    GRAB(QueueSubmit, QueueSubmit);
    GRAB(QueueSubmit2, QueueSubmit2);
    GRAB(QueueSubmit2KHR, QueueSubmit2KHR);
    GRAB(QueuePresentKHR, QueuePresentKHR);
    LOGF("\"ev\":\"vkCreateDevice\",\"dev\":\"%p\",\"phys\":\"%p\"}",
         (void *)dev, (void *)phys);
    return r;
}

/* ------------------------------------------------------------------ */
/* device-level intercepts (logging)                                   */
/* ------------------------------------------------------------------ */
static VkResult VKAPI_CALL xCreateShaderModule(VkDevice dev,
        const VkShaderModuleCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkShaderModule *pMod) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateShaderModule(dev, ci, ac, pMod);
    if (r == VK_SUCCESS) {
        uint64_t fv = fnv1a64(ci->pCode, ci->codeSize);
        map_put(&g_modmap, (uint64_t)*pMod, fv);
        LOGF("\"ev\":\"CreateShaderModule\",\"mod\":\"%p\",\"size\":%zu,"
             "\"fnv\":\"%016llx\"}", (void *)*pMod, ci->codeSize,
             (unsigned long long)fv);
    }
    return r;
}

static VkResult VKAPI_CALL xCreateComputePipelines(VkDevice dev, VkPipelineCache pc,
        uint32_t n, const VkComputePipelineCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkPipeline *pPipes) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateComputePipelines(dev, pc, n, ci, ac, pPipes);
    if (r == VK_SUCCESS)
        for (uint32_t i = 0; i < n; i++) {
            uint64_t fv = map_get(&g_modmap, (uint64_t)ci[i].stage.module);
            if ((fv == SSS_FNV_V || fv == SSS_FNV_H) &&
                g_sss_pipes_n < sizeof g_sss_pipes / sizeof g_sss_pipes[0])
                g_sss_pipes[g_sss_pipes_n++] = (uint64_t)pPipes[i];
            LOGF("\"ev\":\"CreateComputePipeline\",\"pipe\":\"%p\",\"mod\":\"%p\","
                 "\"layout\":\"%p\",\"entry\":\"%s\"}", (void *)pPipes[i],
                 (void *)ci[i].stage.module, (void *)ci[i].layout,
                 ci[i].stage.pName ? ci[i].stage.pName : "");
        }
    return r;
}

static VkResult VKAPI_CALL xCreateGraphicsPipelines(VkDevice dev, VkPipelineCache pc,
        uint32_t n, const VkGraphicsPipelineCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkPipeline *pPipes) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateGraphicsPipelines(dev, pc, n, ci, ac, pPipes);
    if (r == VK_SUCCESS)
        for (uint32_t i = 0; i < n; i++)
            LOGF("\"ev\":\"CreateGraphicsPipeline\",\"pipe\":\"%p\"}",
                 (void *)pPipes[i]);
    return r;
}

static VkResult VKAPI_CALL xCreateRayTracingPipelinesKHR(VkDevice dev,
        VkDeferredOperationKHR op, VkPipelineCache pc, uint32_t n,
        const VkRayTracingPipelineCreateInfoKHR *ci,
        const VkAllocationCallbacks *ac, VkPipeline *pPipes) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateRayTracingPipelinesKHR(dev, op, pc, n, ci, ac, pPipes);
    if (r == VK_SUCCESS)
        for (uint32_t i = 0; i < n; i++)
            LOGF("\"ev\":\"CreateRTPipeline\",\"pipe\":\"%p\"}", (void *)pPipes[i]);
    return r;
}

static VkResult VKAPI_CALL xCreatePipelineLayout(VkDevice dev,
        const VkPipelineLayoutCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkPipelineLayout *pLayout) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreatePipelineLayout(dev, ci, ac, pLayout);
    if (r == VK_SUCCESS) {
        char *p, tmp[2048]; p = tmp; *p = 0;
        for (uint32_t i = 0; i < ci->setLayoutCount && i < 16; i++)
            p += sprintf(p, "%s\"%p\"", i ? "," : "", (void *)ci->pSetLayouts[i]);
        LOGF("\"ev\":\"CreatePipelineLayout\",\"layout\":\"%p\",\"sets\":[%s]}",
             (void *)*pLayout, tmp);
    }
    return r;
}

static VkResult VKAPI_CALL xCreateDescriptorSetLayout(VkDevice dev,
        const VkDescriptorSetLayoutCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkDescriptorSetLayout *pLayout) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateDescriptorSetLayout(dev, ci, ac, pLayout);
    if (r == VK_SUCCESS) {
        char tmp[4096], *p = tmp; *p = 0;
        for (uint32_t i = 0; i < ci->bindingCount && i < 32; i++) {
            const VkDescriptorSetLayoutBinding *b = &ci->pBindings[i];
            p += sprintf(p, "%s{\"b\":%u,\"t\":%d,\"n\":%u}",
                         i ? "," : "", b->binding, (int)b->descriptorType,
                         b->descriptorCount);
        }
        LOGF("\"ev\":\"CreateDescriptorSetLayout\",\"layout\":\"%p\","
             "\"flags\":%u,\"bindings\":[%s]}", (void *)*pLayout, ci->flags, tmp);
    }
    return r;
}

static void VKAPI_CALL xGetDescriptorSetLayoutBindingOffsetEXT(VkDevice dev,
        VkDescriptorSetLayout layout, uint32_t binding, VkDeviceSize *pOffset) {
    DevData *d = dev_from_handle(dev);
    if (d->GetDescriptorSetLayoutBindingOffsetEXT)
        d->GetDescriptorSetLayoutBindingOffsetEXT(dev, layout, binding, pOffset);
    else *pOffset = 0;
    LOGF("\"ev\":\"GetDescriptorSetLayoutBindingOffset\",\"layout\":\"%p\","
         "\"binding\":%u,\"offset\":%llu}", (void *)layout, binding,
         (unsigned long long)*pOffset);
}

static VkResult VKAPI_CALL xCreateImage(VkDevice dev, const VkImageCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkImage *pImg) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateImage(dev, ci, ac, pImg);
    if (r == VK_SUCCESS) {
        map_put(&g_imgmap, (uint64_t)*pImg,
                ((uint64_t)ci->extent.width << 40) |
                ((uint64_t)ci->extent.height << 24) | (uint32_t)ci->format);
        LOGF("\"ev\":\"CreateImage\",\"img\":\"%p\",\"w\":%u,\"h\":%u,\"depth\":%u,"
             "\"mips\":%u,\"layers\":%u,\"format\":%d,\"usage\":%u,\"tiling\":%d,"
             "\"samples\":%d,\"flags\":%u,\"type\":%d}",
             (void *)*pImg, ci->extent.width, ci->extent.height, ci->extent.depth,
             ci->mipLevels, ci->arrayLayers, (int)ci->format, ci->usage,
             (int)ci->tiling, (int)ci->samples, ci->flags, (int)ci->imageType);
    }
    return r;
}

static VkResult VKAPI_CALL xCreateImageView(VkDevice dev,
        const VkImageViewCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkImageView *pView) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateImageView(dev, ci, ac, pView);
    if (r == VK_SUCCESS)
        LOGF("\"ev\":\"CreateImageView\",\"view\":\"%p\",\"img\":\"%p\","
             "\"viewType\":%d,\"format\":%d,\"baseMip\":%u,\"mips\":%u,"
             "\"baseLayer\":%u,\"layers\":%u}",
             (void *)*pView, (void *)ci->image, (int)ci->viewType, (int)ci->format,
             ci->subresourceRange.baseMipLevel, ci->subresourceRange.levelCount,
             ci->subresourceRange.baseArrayLayer, ci->subresourceRange.layerCount);
    return r;
}

static VkResult VKAPI_CALL xCreateBuffer(VkDevice dev, const VkBufferCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkBuffer *pBuf) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateBuffer(dev, ci, ac, pBuf);
    if (r == VK_SUCCESS) {
        map_put(&g_bufsizemap, (uint64_t)*pBuf, ci->size);
        LOGF("\"ev\":\"CreateBuffer\",\"buf\":\"%p\",\"size\":%llu,\"usage\":%u}",
             (void *)*pBuf, (unsigned long long)ci->size, ci->usage);
    }
    return r;
}

static VkResult VKAPI_CALL xCreateBufferView(VkDevice dev,
        const VkBufferViewCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkBufferView *pView) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->CreateBufferView(dev, ci, ac, pView);
    if (r == VK_SUCCESS)
        LOGF("\"ev\":\"CreateBufferView\",\"view\":\"%p\",\"buf\":\"%p\","
             "\"format\":%d,\"offset\":%llu,\"range\":%llu}",
             (void *)*pView, (void *)ci->buffer, (int)ci->format,
             (unsigned long long)ci->offset, (unsigned long long)ci->range);
    return r;
}

static int g_strip_alloc = -1; /* env NGFXPROBE_STRIP_ALLOC bitmask */
static int strip_alloc_mask(void) {
    if (g_strip_alloc < 0) {
        const char *s = getenv("NGFXPROBE_STRIP_ALLOC");
        g_strip_alloc = s ? atoi(s) : 0;
    }
    return g_strip_alloc;
}

static VkResult VKAPI_CALL xAllocateMemory(VkDevice dev,
        const VkMemoryAllocateInfo *ci, const VkAllocationCallbacks *ac,
        VkDeviceMemory *pMem) {
    DevData *d = dev_from_handle(dev);
    /* Optionally unlink crash-triggering structs from the pNext chain.
       bit0: MEMORY_DEDICATED_ALLOCATE_INFO (1000127001)
       bit1: MEMORY_OPAQUE_CAPTURE_ADDRESS_ALLOCATE_INFO (1000257003)
       bit2: MEMORY_PRIORITY_ALLOCATE_INFO_EXT (1000238001)
       bit3: MEMORY_ALLOCATE_FLAGS_INFO (1000060000)            */
    int mask = strip_alloc_mask();
    VkBaseInStructure *mut = (VkBaseInStructure *)(void *)ci->pNext;
    VkBaseInStructure *prev = NULL;
    int stripped = 0;
    while (mut) {
        int st = (int)mut->sType;
        int drop = ((mask & 1) && st == 1000127001) ||
                   ((mask & 2) && st == 1000257003) ||
                   ((mask & 4) && st == 1000238001) ||
                   ((mask & 8) && st == 1000060000);
        if (drop) {
            if (prev) prev->pNext = mut->pNext;
            else ((VkMemoryAllocateInfo *)ci)->pNext = mut->pNext;
            stripped |= 1;
            mut = mut->pNext;
        } else {
            prev = mut;
            mut = mut->pNext;
        }
    }
    {
        char chain[256], *p = chain; *p = 0;
        const VkBaseInStructure *c = ci->pNext;
        while (c && p < chain + 200) { p += sprintf(p, "%s%d", *chain ? "," : "", (int)c->sType); c = c->pNext; }
        LOGF("\"ev\":\"AllocateMemory_pre\",\"size\":%llu,\"type\":%u,\"stripped\":%d,\"pnext\":[%s]}",
             (unsigned long long)ci->allocationSize, ci->memoryTypeIndex, stripped, chain);
    }
    VkResult r = d->AllocateMemory(dev, ci, ac, pMem);
    if (r == VK_SUCCESS)
        LOGF("\"ev\":\"AllocateMemory\",\"mem\":\"%p\",\"size\":%llu,\"type\":%u}",
             (void *)*pMem, (unsigned long long)ci->allocationSize,
             ci->memoryTypeIndex);
    return r;
}

static VkResult VKAPI_CALL xBindBufferMemory(VkDevice dev, VkBuffer buf,
        VkDeviceMemory mem, VkDeviceSize off) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->BindBufferMemory(dev, buf, mem, off);
    if (r == VK_SUCCESS) {
        map_put(&g_bindmap, (uint64_t)buf, bind_put((uint64_t)mem, off));
        LOGF("\"ev\":\"BindBufferMemory\",\"buf\":\"%p\",\"mem\":\"%p\","
             "\"off\":%llu}", (void *)buf, (void *)mem, (unsigned long long)off);
    }
    return r;
}

static VkResult VKAPI_CALL xBindBufferMemory2(VkDevice dev, uint32_t n,
        const VkBindBufferMemoryInfo *bi) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->BindBufferMemory2(dev, n, bi);
    if (r == VK_SUCCESS)
        for (uint32_t i = 0; i < n; i++) {
            map_put(&g_bindmap, (uint64_t)bi[i].buffer,
                    bind_put((uint64_t)bi[i].memory, bi[i].memoryOffset));
            LOGF("\"ev\":\"BindBufferMemory\",\"buf\":\"%p\",\"mem\":\"%p\","
                 "\"off\":%llu}", (void *)bi[i].buffer, (void *)bi[i].memory,
                 (unsigned long long)bi[i].memoryOffset);
        }
    return r;
}
static VkResult VKAPI_CALL xBindBufferMemory2KHR(VkDevice dev, uint32_t n,
        const VkBindBufferMemoryInfo *bi) {
    return xBindBufferMemory2(dev, n, bi);
}

static VkResult VKAPI_CALL xBindImageMemory(VkDevice dev, VkImage img,
        VkDeviceMemory mem, VkDeviceSize off) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->BindImageMemory(dev, img, mem, off);
    if (r == VK_SUCCESS)
        LOGF("\"ev\":\"BindImageMemory\",\"img\":\"%p\",\"mem\":\"%p\","
             "\"off\":%llu}", (void *)img, (void *)mem, (unsigned long long)off);
    return r;
}

static VkDeviceAddress VKAPI_CALL xGetBufferDeviceAddress(VkDevice dev,
        const VkBufferDeviceAddressInfo *info) {
    DevData *d = dev_from_handle(dev);
    VkDeviceAddress a = 0;
    if (d->GetBufferDeviceAddress) a = d->GetBufferDeviceAddress(dev, info);
    else if (d->GetBufferDeviceAddressKHR) a = d->GetBufferDeviceAddressKHR(dev, info);
    if (a) va_add(a, map_get(&g_bufsizemap, (uint64_t)info->buffer),
                  (uint64_t)info->buffer);
    LOGF("\"ev\":\"GetBufferDeviceAddress\",\"buf\":\"%p\",\"addr\":\"0x%llx\"}",
         (void *)info->buffer, (unsigned long long)a);
    return a;
}
static VkDeviceAddress VKAPI_CALL xGetBufferDeviceAddressKHR(VkDevice dev,
        const VkBufferDeviceAddressInfo *info) {
    return xGetBufferDeviceAddress(dev, info);
}

static VkResult VKAPI_CALL xMapMemory(VkDevice dev, VkDeviceMemory mem,
        VkDeviceSize off, VkDeviceSize size, VkMemoryMapFlags flags, void **pp) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->MapMemory(dev, mem, off, size, flags, pp);
    if (r == VK_SUCCESS) {
        map_put(&g_memmap, (uint64_t)mem,
                mapent_put((uint64_t)*pp, off, size));
        LOGF("\"ev\":\"MapMemory\",\"mem\":\"%p\",\"off\":%llu,\"size\":%llu,"
             "\"ptr\":\"%p\"}", (void *)mem, (unsigned long long)off,
             (unsigned long long)size, *pp);
    }
    return r;
}
static VkResult VKAPI_CALL xMapMemory2KHR(VkDevice dev,
        const VkMemoryMapInfoKHR *info, void **pp) {
    DevData *d = dev_from_handle(dev);
    VkResult r = d->MapMemory2KHR ? d->MapMemory2KHR(dev, info, pp)
        : d->MapMemory(dev, info->memory, info->offset, info->size, info->flags, pp);
    if (r == VK_SUCCESS) {
        map_put(&g_memmap, (uint64_t)info->memory,
                mapent_put((uint64_t)*pp, info->offset, info->size));
        LOGF("\"ev\":\"MapMemory\",\"mem\":\"%p\",\"off\":%llu,\"size\":%llu,"
             "\"ptr\":\"%p\"}", (void *)info->memory,
             (unsigned long long)info->offset, (unsigned long long)info->size, *pp);
    }
    return r;
}
static void VKAPI_CALL xUnmapMemory(VkDevice dev, VkDeviceMemory mem) {
    DevData *d = dev_from_handle(dev);
    LOGF("\"ev\":\"UnmapMemory\",\"mem\":\"%p\"}", (void *)mem);
    map_put(&g_memmap, (uint64_t)mem, 0);
    d->UnmapMemory(dev, mem);
}

static VkResult VKAPI_CALL xSetDebugUtilsObjectNameEXT(VkDevice dev,
        const VkDebugUtilsObjectNameInfoEXT *info) {
    DevData *d = dev_from_handle(dev);
    VkResult r = VK_ERROR_UNKNOWN;
    if (d->SetDebugUtilsObjectNameEXT) r = d->SetDebugUtilsObjectNameEXT(dev, info);
    LOGF("\"ev\":\"SetName\",\"objType\":%d,\"handle\":\"0x%llx\",\"name\":\"%s\"}",
         (int)info->objectType, (unsigned long long)info->objectHandle,
         info->pObjectName ? info->pObjectName : "");
    return r;
}

static void VKAPI_CALL xGetDescriptorEXT(VkDevice dev,
        const VkDescriptorGetInfoEXT *info, size_t dataSize, void *pData) {
    DevData *d = dev_from_handle(dev);
    if (d->GetDescriptorEXT) d->GetDescriptorEXT(dev, info, dataSize, pData);
    char extra[1024] = "";
    switch (info->type) {
    case VK_DESCRIPTOR_TYPE_SAMPLER:
        snprintf(extra, sizeof extra, ",\"sampler\":\"%p\"",
                 (void *)info->data.pSampler ? *(void **)info->data.pSampler : 0);
        break;
    case VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:
    case VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE:
        snprintf(extra, sizeof extra, ",\"view\":\"%p\",\"sampler\":\"%p\","
                 "\"imgLayout\":%d", (void *)info->data.pSampledImage->imageView,
                 (void *)info->data.pSampledImage->sampler,
                 (int)info->data.pSampledImage->imageLayout);
        break;
    case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE:
    case VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT:
        snprintf(extra, sizeof extra, ",\"view\":\"%p\",\"imgLayout\":%d",
                 (void *)info->data.pStorageImage->imageView,
                 (int)info->data.pStorageImage->imageLayout);
        break;
    case VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER:
    case VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER:
        if (info->data.pStorageTexelBuffer)
            snprintf(extra, sizeof extra, ",\"addr\":\"0x%llx\",\"range\":%llu",
                     (unsigned long long)info->data.pStorageTexelBuffer->address,
                     (unsigned long long)info->data.pStorageTexelBuffer->range);
        break;
    case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER:
    case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER:
        if (info->data.pUniformBuffer)
            snprintf(extra, sizeof extra, ",\"addr\":\"0x%llx\",\"range\":%llu",
                     (unsigned long long)info->data.pUniformBuffer->address,
                     (unsigned long long)info->data.pUniformBuffer->range);
        break;
    case VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR:
        snprintf(extra, sizeof extra, ",\"as\":\"0x%llx\"",
                 (unsigned long long)info->data.accelerationStructure);
        break;
    default: break;
    }
    char hx[1024];
    /* dump the raw descriptor bytes actually written (cap 256B) */
    size_t dump = dataSize < 256 ? dataSize : 256;
    hexenc(hx, pData, dump, sizeof hx);
    LOGF("\"ev\":\"GetDescriptor\",\"type\":%d,\"dataSize\":%zu,\"pData\":\"%p\""
         "%s,\"hex\":\"%s\"}", (int)info->type, dataSize, pData, extra, hx);
}

/* ------------------------- command buffer side -------------------- */
static void VKAPI_CALL xCmdBindPipeline(VkCommandBuffer cb,
        VkPipelineBindPoint bp, VkPipeline pipe) {
    DevData *d = dev_from_handle(cb);
    cmd_state((uint64_t)cb)->pipe = (uint64_t)pipe;
    LOGF("\"ev\":\"CmdBindPipeline\",\"cb\":\"%p\",\"bp\":%d,\"pipe\":\"%p\"}",
         (void *)cb, (int)bp, (void *)pipe);
    d->CmdBindPipeline(cb, bp, pipe);
}

static void VKAPI_CALL xCmdPushConstants(VkCommandBuffer cb, VkPipelineLayout layout,
        VkShaderStageFlags stages, uint32_t off, uint32_t size, const void *pVals) {
    DevData *d = dev_from_handle(cb);
    CmdState *st = cmd_state((uint64_t)cb);
    if (off < 64) {
        uint32_t cp = size < 64 - off ? size : 64 - off;
        memcpy(st->pc + off, pVals, cp);
        st->pc_len = off + cp > (uint32_t)st->pc_len ? (int)(off + cp) : st->pc_len;
    }
    char hx[8192 / 2];
    hexenc(hx, pVals, size < 2048 ? size : 2048, sizeof hx);
    LOGF("\"ev\":\"CmdPushConstants\",\"cb\":\"%p\",\"layout\":\"%p\","
         "\"stages\":%u,\"off\":%u,\"size\":%u,\"hex\":\"%s\"}",
         (void *)cb, (void *)layout, stages, off, size, hx);
    d->CmdPushConstants(cb, layout, stages, off, size, pVals);
}

static void VKAPI_CALL xCmdBindDescriptorBuffersEXT(VkCommandBuffer cb,
        uint32_t count, const VkDescriptorBufferBindingInfoEXT *infos) {
    DevData *d = dev_from_handle(cb);
    CmdState *st = cmd_state((uint64_t)cb);
    char tmp[2048], *p = tmp; *p = 0;
    for (uint32_t i = 0; i < count && i < 8; i++) {
        st->infoaddr[i] = infos[i].address;
        p += sprintf(p, "%s{\"addr\":\"0x%llx\",\"usage\":%u}",
                     i ? "," : "",
                     (unsigned long long)infos[i].address, infos[i].usage);
    }
    LOGF("\"ev\":\"CmdBindDescriptorBuffers\",\"cb\":\"%p\",\"infos\":[%s]}",
         (void *)cb, tmp);
    if (d->CmdBindDescriptorBuffersEXT) d->CmdBindDescriptorBuffersEXT(cb, count, infos);
}

static void VKAPI_CALL xCmdSetDescriptorBufferOffsetsEXT(VkCommandBuffer cb,
        VkPipelineBindPoint bp, VkPipelineLayout layout, uint32_t firstSet,
        uint32_t setCount, const uint32_t *bufIdx, const VkDeviceSize *offs) {
    DevData *d = dev_from_handle(cb);
    CmdState *st = cmd_state((uint64_t)cb);
    char tmp[2048], *p = tmp; *p = 0;
    for (uint32_t i = 0; i < setCount && i < 8; i++) {
        if (firstSet + i < 8 && bufIdx[i] < 8)
            st->setva[firstSet + i] = st->infoaddr[bufIdx[i]] + offs[i];
        p += sprintf(p, "%s{\"set\":%u,\"bufIdx\":%u,\"off\":%llu}", i ? "," : "",
                     firstSet + i, bufIdx[i], (unsigned long long)offs[i]);
    }
    LOGF("\"ev\":\"CmdSetDescriptorBufferOffsets\",\"cb\":\"%p\",\"bp\":%d,"
         "\"layout\":\"%p\",\"offs\":[%s]}", (void *)cb, (int)bp, (void *)layout, tmp);
    if (d->CmdSetDescriptorBufferOffsetsEXT)
        d->CmdSetDescriptorBufferOffsetsEXT(cb, bp, layout, firstSet, setCount,
                                            bufIdx, offs);
}

static void VKAPI_CALL xCmdDispatch(VkCommandBuffer cb, uint32_t x, uint32_t y,
        uint32_t z) {
    DevData *d = dev_from_handle(cb);
    sss_sniff((uint64_t)cb, "SSSDispatch");
    LOGF("\"ev\":\"CmdDispatch\",\"cb\":\"%p\",\"x\":%u,\"y\":%u,\"z\":%u}",
         (void *)cb, x, y, z);
    d->CmdDispatch(cb, x, y, z);
}
static void VKAPI_CALL xCmdDispatchIndirect(VkCommandBuffer cb, VkBuffer buf,
        VkDeviceSize off) {
    DevData *d = dev_from_handle(cb);
    sss_sniff((uint64_t)cb, "SSSDispatchIndirect");
    LOGF("\"ev\":\"CmdDispatchIndirect\",\"cb\":\"%p\",\"buf\":\"%p\",\"off\":%llu}",
         (void *)cb, (void *)buf, (unsigned long long)off);
    d->CmdDispatchIndirect(cb, buf, off);
}

static void VKAPI_CALL xCmdTraceRaysKHR(VkCommandBuffer cb,
        const VkStridedDeviceAddressRegionKHR *raygen,
        const VkStridedDeviceAddressRegionKHR *miss,
        const VkStridedDeviceAddressRegionKHR *hit,
        const VkStridedDeviceAddressRegionKHR *callable,
        uint32_t w, uint32_t h, uint32_t depth) {
    DevData *d = dev_from_handle(cb);
    LOGF("\"ev\":\"CmdTraceRays\",\"cb\":\"%p\",\"w\":%u,\"h\":%u,\"d\":%u}",
         (void *)cb, w, h, depth);
    if (d->CmdTraceRaysKHR) d->CmdTraceRaysKHR(cb, raygen, miss, hit, callable,
                                               w, h, depth);
}

static void VKAPI_CALL xCmdCopyBufferToImage(VkCommandBuffer cb, VkBuffer src,
        VkImage dst, VkImageLayout layout, uint32_t n,
        const VkBufferImageCopy *regions) {
    DevData *d = dev_from_handle(cb);
    for (uint32_t i = 0; i < n && i < 16; i++) {
        LOGF("\"ev\":\"CmdCopyBufferToImage\",\"cb\":\"%p\",\"src\":\"%p\","
             "\"dst\":\"%p\",\"bufOff\":%llu,\"rowLen\":%u,\"imgH\":%u,"
             "\"x\":%d,\"y\":%d,\"w\":%u,\"h\":%u,\"mip\":%u,\"layer\":%u}",
             (void *)cb, (void *)src, (void *)dst,
             (unsigned long long)regions[i].bufferOffset,
             regions[i].bufferRowLength, regions[i].bufferImageHeight,
             regions[i].imageOffset.x, regions[i].imageOffset.y,
             regions[i].imageExtent.width, regions[i].imageExtent.height,
             regions[i].imageSubresource.mipLevel,
             regions[i].imageSubresource.baseArrayLayer);
        maybe_dump_imgcopy((const void *)src, (const void *)dst,
                           regions[i].bufferOffset,
                           regions[i].imageExtent.width,
                           regions[i].imageExtent.height);
    }
    d->CmdCopyBufferToImage(cb, src, dst, layout, n, regions);
}
static void VKAPI_CALL xCmdCopyBufferToImage2KHR(VkCommandBuffer cb,
        const VkCopyBufferToImageInfo2 *info) {
    DevData *d = dev_from_handle(cb);
    for (uint32_t i = 0; i < info->regionCount && i < 16; i++) {
        const VkBufferImageCopy2 *rg = &info->pRegions[i];
        LOGF("\"ev\":\"CmdCopyBufferToImage\",\"cb\":\"%p\",\"src\":\"%p\","
             "\"dst\":\"%p\",\"bufOff\":%llu,\"rowLen\":%u,\"imgH\":%u,"
             "\"x\":%d,\"y\":%d,\"w\":%u,\"h\":%u,\"mip\":%u,\"layer\":%u}",
             (void *)cb, (void *)info->srcBuffer, (void *)info->dstImage,
             (unsigned long long)rg->bufferOffset, rg->bufferRowLength,
             rg->bufferImageHeight, rg->imageOffset.x, rg->imageOffset.y,
             rg->imageExtent.width, rg->imageExtent.height,
             rg->imageSubresource.mipLevel, rg->imageSubresource.baseArrayLayer);
        maybe_dump_imgcopy((const void *)info->srcBuffer,
                           (const void *)info->dstImage, rg->bufferOffset,
                           rg->imageExtent.width, rg->imageExtent.height);
    }
    if (d->CmdCopyBufferToImage2KHR) d->CmdCopyBufferToImage2KHR(cb, info);
}

static VkResult VKAPI_CALL xQueueSubmit(VkQueue q, uint32_t n,
        const VkSubmitInfo *subs, VkFence fence) {
    DevData *d = dev_from_handle(q);
    LOGF("\"ev\":\"QueueSubmit\",\"q\":\"%p\",\"batches\":%u}", (void *)q, n);
    return d->QueueSubmit(q, n, subs, fence);
}
static VkResult VKAPI_CALL xQueueSubmit2(VkQueue q, uint32_t n,
        const VkSubmitInfo2 *subs, VkFence fence) {
    DevData *d = dev_from_handle(q);
    LOGF("\"ev\":\"QueueSubmit2\",\"q\":\"%p\",\"batches\":%u}", (void *)q, n);
    return d->QueueSubmit2 ? d->QueueSubmit2(q, n, subs, fence)
                           : VK_ERROR_UNKNOWN;
}
static VkResult VKAPI_CALL xQueueSubmit2KHR(VkQueue q, uint32_t n,
        const VkSubmitInfo2 *subs, VkFence fence) {
    return xQueueSubmit2(q, n, subs, fence);
}
static VkResult VKAPI_CALL xQueuePresentKHR(VkQueue q,
        const VkPresentInfoKHR *pi) {
    DevData *d = dev_from_handle(q);
    LOGF("\"ev\":\"QueuePresent\",\"q\":\"%p\"}", (void *)q);
    return d->QueuePresentKHR ? d->QueuePresentKHR(q, pi) : VK_ERROR_UNKNOWN;
}

static void VKAPI_CALL xDestroyDevice(VkDevice dev, const VkAllocationCallbacks *ac) {
    DevData *d = dev_from_handle(dev);
    LOGF("\"ev\":\"vkDestroyDevice\"}");
    if (d && d->DestroyDevice) d->DestroyDevice(dev, ac);
}
static void VKAPI_CALL xDestroyInstance(VkInstance inst,
        const VkAllocationCallbacks *ac) {
    InstData *d = find_inst(inst);
    LOGF("\"ev\":\"vkDestroyInstance\"}");
    if (d && d->DestroyInstance) d->DestroyInstance(inst, ac);
    if (g_log && g_log != stderr) { fclose(g_log); g_log = NULL; }
}

/* ------------------------------------------------------------------ */
/* gipa / gdpa                                                         */
/* ------------------------------------------------------------------ */
typedef struct { const char *name; void *fn; } HookEnt;
static const HookEnt kDevHooks[] = {
    {"vkCreateShaderModule", (void *)xCreateShaderModule},
    {"vkCreateComputePipelines", (void *)xCreateComputePipelines},
    {"vkCreateGraphicsPipelines", (void *)xCreateGraphicsPipelines},
    {"vkCreateRayTracingPipelinesKHR", (void *)xCreateRayTracingPipelinesKHR},
    {"vkCreatePipelineLayout", (void *)xCreatePipelineLayout},
    {"vkCreateDescriptorSetLayout", (void *)xCreateDescriptorSetLayout},
    {"vkGetDescriptorSetLayoutBindingOffsetEXT", (void *)xGetDescriptorSetLayoutBindingOffsetEXT},
    {"vkCreateImage", (void *)xCreateImage},
    {"vkCreateImageView", (void *)xCreateImageView},
    {"vkCreateBuffer", (void *)xCreateBuffer},
    {"vkCreateBufferView", (void *)xCreateBufferView},
    {"vkAllocateMemory", (void *)xAllocateMemory},
    {"vkBindBufferMemory", (void *)xBindBufferMemory},
    {"vkBindBufferMemory2", (void *)xBindBufferMemory2},
    {"vkBindBufferMemory2KHR", (void *)xBindBufferMemory2KHR},
    {"vkBindImageMemory", (void *)xBindImageMemory},
    {"vkGetBufferDeviceAddress", (void *)xGetBufferDeviceAddress},
    {"vkGetBufferDeviceAddressKHR", (void *)xGetBufferDeviceAddressKHR},
    {"vkMapMemory", (void *)xMapMemory},
    {"vkMapMemory2KHR", (void *)xMapMemory2KHR},
    {"vkUnmapMemory", (void *)xUnmapMemory},
    {"vkSetDebugUtilsObjectNameEXT", (void *)xSetDebugUtilsObjectNameEXT},
    {"vkGetDescriptorEXT", (void *)xGetDescriptorEXT},
    {"vkCmdBindPipeline", (void *)xCmdBindPipeline},
    {"vkCmdPushConstants", (void *)xCmdPushConstants},
    {"vkCmdBindDescriptorBuffersEXT", (void *)xCmdBindDescriptorBuffersEXT},
    {"vkCmdSetDescriptorBufferOffsetsEXT", (void *)xCmdSetDescriptorBufferOffsetsEXT},
    {"vkCmdDispatch", (void *)xCmdDispatch},
    {"vkCmdDispatchIndirect", (void *)xCmdDispatchIndirect},
    {"vkCmdTraceRaysKHR", (void *)xCmdTraceRaysKHR},
    {"vkCmdCopyBufferToImage", (void *)xCmdCopyBufferToImage},
    {"vkCmdCopyBufferToImage2", (void *)xCmdCopyBufferToImage2KHR},
    {"vkCmdCopyBufferToImage2KHR", (void *)xCmdCopyBufferToImage2KHR},
    {"vkQueueSubmit", (void *)xQueueSubmit},
    {"vkQueueSubmit2", (void *)xQueueSubmit2},
    {"vkQueueSubmit2KHR", (void *)xQueueSubmit2KHR},
    {"vkQueuePresentKHR", (void *)xQueuePresentKHR},
    {"vkDestroyDevice", (void *)xDestroyDevice},
};
static const HookEnt kInstHooks[] = {
    {"vkCreateInstance", (void *)xCreateInstance},
    {"vkCreateDevice", (void *)xCreateDevice},
    {"vkGetPhysicalDeviceProperties2", (void *)xGetPhysicalDeviceProperties2},
    {"vkGetPhysicalDeviceProperties2KHR", (void *)xGetPhysicalDeviceProperties2KHR},
    {"vkGetPhysicalDeviceMemoryProperties", (void *)xGetPhysicalDeviceMemoryProperties},
    {"vkDestroyInstance", (void *)xDestroyInstance},
};

VK_LAYER_EXPORT PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(
        VkDevice dev, const char *name) {
    for (size_t i = 0; i < sizeof kDevHooks / sizeof kDevHooks[0]; i++)
        if (!strcmp(kDevHooks[i].name, name)) return (PFN_vkVoidFunction)kDevHooks[i].fn;
    DevData *d = dev_from_handle(dev);
    if (d && d->gdpa) return d->gdpa(dev, name);
    return NULL;
}

VK_LAYER_EXPORT PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(
        VkInstance inst, const char *name) {
    for (size_t i = 0; i < sizeof kDevHooks / sizeof kDevHooks[0]; i++)
        if (!strcmp(kDevHooks[i].name, name)) return (PFN_vkVoidFunction)kDevHooks[i].fn;
    for (size_t i = 0; i < sizeof kInstHooks / sizeof kInstHooks[0]; i++)
        if (!strcmp(kInstHooks[i].name, name)) return (PFN_vkVoidFunction)kInstHooks[i].fn;
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)vkGetInstanceProcAddr;
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)vkGetDeviceProcAddr;
    InstData *d = find_inst(inst);
    if (d && d->gipa) return d->gipa(inst, name);
    /* instance not yet created: chain via the first (or only) known gipa */
    if (g_ninst && g_inst[0].gipa) return g_inst[0].gipa(inst, name);
    return NULL;
}

VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateInstanceExtensionProperties(
        const char *pLayerName, uint32_t *pCount, VkExtensionProperties *pProps) {
    (void)pLayerName; (void)pCount; (void)pProps;
    if (pLayerName && !strcmp(pLayerName, "VK_LAYER_NGFXPROBE_probe")) {
        *pCount = 0; return VK_SUCCESS;
    }
    return VK_SUCCESS;
}
VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateInstanceLayerProperties(
        uint32_t *pCount, VkLayerProperties *pProps) {
    (void)pCount; (void)pProps;
    return VK_ERROR_LAYER_NOT_PRESENT;
}
VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateDeviceExtensionProperties(
        VkPhysicalDevice dev, const char *pLayerName, uint32_t *pCount,
        VkExtensionProperties *pProps) {
    (void)dev; (void)pProps;
    if (pLayerName && !strcmp(pLayerName, "VK_LAYER_NGFXPROBE_probe")) {
        *pCount = 0; return VK_SUCCESS;
    }
    *pCount = 0; return VK_SUCCESS;
}
VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateDeviceLayerProperties(
        VkPhysicalDevice dev, uint32_t *pCount, VkLayerProperties *pProps) {
    (void)dev; (void)pCount; (void)pProps;
    return VK_ERROR_LAYER_NOT_PRESENT;
}

__attribute__((constructor)) static void probe_init(void) { log_open(); }
