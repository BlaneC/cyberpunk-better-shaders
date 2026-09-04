/*
 * VK_LAYER_CALLISTO_spvswap -- Vulkan layer that substitutes SPIR-V shader
 * modules at vkCreateShaderModule time (Callisto BRDF injection vehicle).
 *
 * Background: analysis/BRDF_HANDOFF.md. The game runs under Proton/
 * vkd3d-proton, so every shader reaches the driver as SPIR-V via
 * vkCreateShaderModule, with the original DXIL identity preserved as an
 * OpString "<dxilhash>.<mangled-entry>.dxil" (dxil-spirv keeps it).
 *
 * For every vkCreateShaderModule:
 *   1. Scan pCode for the embedded dxil identity: a run of 16 lowercase hex
 *      chars followed by ".dxil" (possibly after a mangled entry name).
 *   2. Compute sha256(pCode) as a secondary key.
 *   3. If <swapdir>/<dxilhash>.spv exists, substitute it. Fallback:
 *      <swapdir>/sha256-<hex>.spv.
 *   4. Log one JSONL line per module (hit or miss) -- the log is how we
 *      discover the live game's hashes and prove the swap fired.
 *
 * Env:
 *   CALLISTO_SWAP_DIR       swap directory (default: <dir of this .so>/swaps)
 *   CALLISTO_LOG            log path (default: stderr)
 *   CALLISTO_SWAP_DISABLE=1 pure passthrough (modules still logged)
 *   CALLISTO_SWAP_QUIET=1   log swap hits/errors only, not every module
 *   CALLISTO_DUMP_DIR       dump incoming SPIR-V of every module here
 *   CALLISTO_DUMP_MATCH     only dump ids containing this substring
 *   CALLISTO_SER_DISABLE=1  never ask for VK_NV_ray_tracing_invocation_reorder
 *   CALLISTO_RAYQ_DISABLE=1 never ask for VK_KHR_ray_query (see "RAY QUERY")
 *   CALLISTO_ASJOURNAL_DISABLE=1  do not journal acceleration structures
 *   CALLISTO_BDA_DISABLE=1  never allocate the BDA slot (see "BDA SLOT")
 *   CALLISTO_BDA_SCRATCH_MB=N  size of the shader-writable scratch buffer that
 *                           the slot points at (default 128, 0 = none).
 *                           A rung indexes it as `y * 4096 + x` masked to a
 *                           power of two, so the size is what decides how many
 *                           SCREEN ROWS get a word of their own: 128 MiB is
 *                           2^23 two-word slots = rows 0..2047 collision-free.
 *                           Undersize it and rows alias in screen space --
 *                           handoff/116 sec 9, where 32 MiB gave exactly 512
 *                           unique rows and painted the other two thirds of a
 *                           720p frame blue.
 *
 * SER -- Shader Execution Reordering (handoff/41-SER-BUILD.md, idea A1 of
 * handoff/38-WILD-IDEAS.md). Cyberpunk uses the DXR HitObject/SER path on
 * Windows and ships `cvRayTracingEnableReferenceSER`; vkd3d-proton does not
 * translate NVAPI shader intrinsics, so on Linux the CVar is inert and 0 of
 * 3273 dumped modules declare SPV_NV_shader_invocation_reorder -- while this
 * driver reports VK_NV_ray_tracing_invocation_reorder with
 * ReorderingHint = REORDER_MODE_REORDER_EXT. dev/patch_ser.py puts the
 * instruction back into the twelve rgs_reference_main permutations.
 *
 * A module that declares that capability is REJECTED at pipeline creation
 * unless the extension is enabled on the VkDevice, and the application (i.e.
 * vkd3d-proton) never asks for it. So this layer asks on its behalf, in
 * xCreateDevice: it appends the extension name to a COPY of the caller's
 * array and chains VkPhysicalDeviceRayTracingInvocationReorderFeaturesNV into
 * pNext. Every step is conditional and every refusal is logged:
 *   {"ev":"ser","action":"enabled"|"skipped"|"fallback",...}
 * If anything at all is off -- env flag, driver without the extension, an app
 * that did not enable VK_KHR_ray_tracing_pipeline (the extension's own
 * dependency; enabling ours without it would make vkCreateDevice FAIL and the
 * game not start) -- the call passes straight through untouched. And if the
 * modified create fails anyway, it is retried with the caller's original
 * struct, so this can never be the reason the game does not launch.
 *
 * The other half of the safety net is in xCreateShaderModule: a swap file
 * that declares the SER capability is NOT served to a device that does not
 * have it enabled. Without that check a stale swaps.ser/ against a layer
 * that failed to enable the extension would turn into a raytracing-pipeline
 * creation failure, i.e. a black screen, rather than a log line.
 *
 * RAY QUERY -- handoff/98-RAYQUERY.md, "Unlock 1". Exactly the same shape as
 * SER, for exactly the same reason. A module that declares OpCapability
 * RayQueryKHR is REJECTED at pipeline creation unless VK_KHR_ray_query is
 * enabled on the VkDevice, and vkd3d-proton never asks for it (it translates
 * DXR 1.0 pipelines; DXR 1.1 inline ray tracing is not what Cyberpunk's
 * reference path tracer uses). This layer asks on the app's behalf in
 * xCreateDevice, next to the SER request and through the same code path, and
 * xCreateShaderModule refuses a ray-query swap on a device that did not get
 * it -- refusing to the NEXT OVERLAY, never to vanilla (GOTCHAS: "an overlay
 * reject must fall through", 44 sec 2.1).
 *   {"ev":"rayq","action":"enabled"|"skipped","reason":...}
 *   {"ev":"rayq_reject","id":...,"action":"next_overlay"}
 * ./dev/patch_rayq.sh --selftest proves both halves against the real driver
 * without launching the game.
 *
 * AS JOURNAL -- handoff/98 section 8 (Unlock 2a). One line per distinct
 * acceleration structure and per distinct device address, so "how many TLAS
 * are there, which one does the path tracer use, and is its address stable
 * across frames" is answerable from an ordinary launch with no shader change
 * and no risk. Deduped by handle, so it costs a short table walk per
 * vkGetAccelerationStructureDeviceAddressKHR and nothing else.
 *   {"ev":"as_create","as":...,"type":"TLAS"|"BLAS","size":N}
 *   {"ev":"as_addr","as":...,"type":...,"addr":"0x...","distinct":N}
 *   {"ev":"as_build","dst":...,"type":...,"n":N,"builds":N}
 *
 * BDA SLOT -- handoff/103-STAGE-2B.md (Stage 2b of handoff/98 section 10.3).
 * Compute modules CANNOT reach the RTAS heap: in a compute pipeline
 * vkd3d-proton binds AtomicCounters at set 1 binding 0, where a raygen has
 * RTASHeap (98 section 10.2, measured). So a compute-side inline ray query needs
 * the 64-bit TLAS device address delivered by the layer instead.
 *
 * This layer allocates ONE 256-byte host-visible buffer per RT-capable device
 * with SHADER_DEVICE_ADDRESS usage, writes a magic word into it, and refreshes
 * word 2/3 with the newest populated TOP-LEVEL acceleration structure address
 * every time a TLAS build is RECORDED (the same hook the AS journal uses).
 * A patched module carries a reserved marker
 *      OpString "CALLISTO_BDA_SLOT_V1 lo=%<id> hi=%<id> sent=... magic=..."
 * plus the two OpConstant %uint the marker NAMES BY SSA ID, holding the two
 * halves of a sentinel address. At vkCreateShaderModule the layer rewrites
 * exactly those two literals with the real buffer address. It is NOT a value
 * scan (98 section 10.3 hole 2): the ids come from the module's own marker and all
 * four conjuncts -- marker present, ids well formed, ids are 32-bit unsigned
 * OpConstants, their current values are the sentinel -- must hold, or the
 * candidate is REFUSED and the search falls through to the next overlay.
 *   {"ev":"bda","action":"armed"|"skipped","reason":...,"addr":"0x..."}
 *   {"ev":"bda_fixup","id":...,"addr":"0x..."}
 *   {"ev":"bda_reject","id":...,"reason":...,"action":"next_overlay"|"vanilla"}
 *   {"ev":"bda_tlas","addr":"0x...","gen":N,"prims":N}
 * ./dev/selftest_bda.sh proves the whole chain against the real driver --
 * including a real DISPATCH that reads the magic back through the fixed-up
 * pointer -- without launching the game.
 *
 * Dispatch evidence (the missing link between "created" and "dispatched"):
 * the layer records every module's identity, then hooks
 * vkCreateRayTracingPipelinesKHR to log which raygen module each RT pipeline
 * is built from, and vkCmdBindPipeline/vkCmdTraceRays*KHR to log, once per
 * distinct pipeline, which raygen actually TRACES RAYS. Watch for:
 *   {"ev":"rt_pipeline","rgs":"<id>",...}      pipeline built from this raygen
 *   {"ev":"trace_rays","rgs":"<id>",...}       this raygen is DISPATCHED
 * A swap HIT proves creation; trace_rays proves dispatch. Patch whatever
 * shows up in trace_rays.
 *
 * Build:
 *   gcc -shared -fPIC -O2 -o libVkLayer_callisto_spvswap.so swap_layer.c -ldl -lpthread
 *
 * Enable (Steam launch options):
 *   VK_ADD_LAYER_PATH=<dir> VK_INSTANCE_LAYERS=VK_LAYER_CALLISTO_spvswap %command%
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <dlfcn.h>
#include <unistd.h>
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
static int g_quiet, g_disabled;
static int g_ser_disabled;       /* CALLISTO_SER_DISABLE */
static int g_rayq_disabled;      /* CALLISTO_RAYQ_DISABLE */
static int g_asj_disabled;       /* CALLISTO_ASJOURNAL_DISABLE */
static int g_bda_disabled;       /* CALLISTO_BDA_DISABLE */
static uint32_t g_bda_scratch_mb = 128;  /* CALLISTO_BDA_SCRATCH_MB */
static const char *g_dump_dir;   /* CALLISTO_DUMP_DIR */

/* The constructor can run before the sandbox has finished setting up the
 * process's filesystem view (under pressure-vessel the game's log fopen fails
 * there and everything silently falls back to stderr, which Steam swallows).
 * So the env flags are read eagerly but the log file is opened LAZILY on
 * first use, and re-tried until it succeeds. */
static const char *g_logpath;
static int g_log_tried;

static void log_open(void) {
    g_logpath = getenv("CALLISTO_LOG");
    g_quiet = getenv("CALLISTO_SWAP_QUIET") && !strcmp(getenv("CALLISTO_SWAP_QUIET"), "1");
    g_disabled = getenv("CALLISTO_SWAP_DISABLE") && !strcmp(getenv("CALLISTO_SWAP_DISABLE"), "1");
    g_dump_dir = getenv("CALLISTO_DUMP_DIR");
    g_ser_disabled = getenv("CALLISTO_SER_DISABLE")
                     && !strcmp(getenv("CALLISTO_SER_DISABLE"), "1");
    g_rayq_disabled = getenv("CALLISTO_RAYQ_DISABLE")
                     && !strcmp(getenv("CALLISTO_RAYQ_DISABLE"), "1");
    g_asj_disabled = getenv("CALLISTO_ASJOURNAL_DISABLE")
                     && !strcmp(getenv("CALLISTO_ASJOURNAL_DISABLE"), "1");
    g_bda_disabled = getenv("CALLISTO_BDA_DISABLE")
                     && !strcmp(getenv("CALLISTO_BDA_DISABLE"), "1");
    {   /* Stage 3a. Clamped rather than rejected: a silly value must not be
         * the difference between a slot that arms and one that does not. */
        const char *mb = getenv("CALLISTO_BDA_SCRATCH_MB");
        if (mb) {
            long v = strtol(mb, NULL, 10);
            if (v < 0) v = 0;
            if (v > 256) v = 256;
            g_bda_scratch_mb = (uint32_t)v;
        }
    }
}

/* call with g_mu held */
static FILE *log_file(void) {
    if (g_log) return g_log;
    if (g_logpath && *g_logpath) {
        FILE *f = fopen(g_logpath, "a");
        if (f) {
            setvbuf(f, NULL, _IOLBF, 0);   /* survive a crash mid-session */
            fprintf(f, "{\"ev\":\"log_open\",\"pid\":%d}\n", (int)getpid());
            g_log = f;
            return g_log;
        }
    }
    /* keep retrying the file for a while before settling on stderr */
    if (++g_log_tried > 64) g_log = stderr;
    return g_log ? g_log : stderr;
}

#define LOGF(...) do { \
    char b[8192]; \
    uint64_t q = __sync_fetch_and_add(&g_seq, 1); \
    int _n = snprintf(b, sizeof b, "{\"seq\":%llu,", (unsigned long long)q); \
    snprintf(b + _n, sizeof b - _n, __VA_ARGS__); \
    pthread_mutex_lock(&g_mu); \
    { FILE *_f = log_file(); \
      if (_f) { fputs(b, _f); fputc('\n', _f); fflush(_f); } } \
    pthread_mutex_unlock(&g_mu); \
} while (0)

/* ------------------------------------------------------------------ */
/* sha256 (self-contained, FIPS 180-4)                                 */
/* ------------------------------------------------------------------ */
typedef struct { uint32_t h[8]; uint64_t len; unsigned char buf[64]; size_t n; } Sha256;
static const uint32_t kK[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2 };
static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
static void sha256_block(Sha256 *s, const unsigned char *p) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4*i]<<24 | (uint32_t)p[4*i+1]<<16 | (uint32_t)p[4*i+2]<<8 | p[4*i+3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i-15],7) ^ rotr(w[i-15],18) ^ (w[i-15]>>3);
        uint32_t s1 = rotr(w[i-2],17) ^ rotr(w[i-2],19) ^ (w[i-2]>>10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=s->h[0],b=s->h[1],c=s->h[2],d=s->h[3],e=s->h[4],f=s->h[5],g=s->h[6],h=s->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = rotr(e,6)^rotr(e,11)^rotr(e,25), ch = (e&f)^(~e&g);
        uint32_t t1 = h + S1 + ch + kK[i] + w[i];
        uint32_t S0 = rotr(a,2)^rotr(a,13)^rotr(a,22), mj = (a&b)^(a&c)^(b&c);
        uint32_t t2 = S0 + mj;
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    s->h[0]+=a; s->h[1]+=b; s->h[2]+=c; s->h[3]+=d; s->h[4]+=e; s->h[5]+=f; s->h[6]+=g; s->h[7]+=h;
}
static void sha256(const void *data, size_t len, char outhex[65]) {
    Sha256 s = {{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}, 0, {0}, 0};
    const unsigned char *p = data;
    while (len >= 64) { sha256_block(&s, p); p += 64; len -= 64; s.len += 512; }
    size_t rem = len;
    memcpy(s.buf, p, rem);
    s.buf[rem++] = 0x80;
    if (rem > 56) { memset(s.buf+rem, 0, 64-rem); sha256_block(&s, s.buf); rem = 0; }
    memset(s.buf+rem, 0, 56-rem);
    uint64_t bits = s.len + (uint64_t)len * 8;
    for (int i = 0; i < 8; i++) s.buf[63-i] = (unsigned char)(bits >> (8*i));
    sha256_block(&s, s.buf);
    for (int i = 0; i < 8; i++) sprintf(outhex + 8*i, "%08x", s.h[i]);
    outhex[64] = 0;
}

/* ------------------------------------------------------------------ */
/* dxil identity scan. dxil-spirv emits OpString                        */
/* "<libhash>.<mangled-entry>.dxil", e.g.                               */
/* "d622fb9e1dcb8cd0.?rgs_reference_main@@YAXXZ.dxil".                  */
/* NOTE: the 16-hex part is the DXIL *library* hash and is NOT unique   */
/* per shader -- one library yields several modules (rgs/ms/chs entry   */
/* points). Identity must be hash+entry.                                */
/* out_id: "<hash>.<entry>" (entry demangled: [A-Za-z0-9_] after ".?",  */
/* up to "@@"). out_hash: raw 16-hex library hash.                      */
/* ------------------------------------------------------------------ */
static int ishex(unsigned char c) { return (c>='0'&&c<='9') || (c>='a'&&c<='f'); }
static int isident(unsigned char c) { return (c>='0'&&c<='9') || (c>='a'&&c<='z') || (c>='A'&&c<='Z') || c=='_'; }
static int scan_dxil_id(const uint32_t *code, size_t size,
                        char out_id[96], char out_hash[17]) {
    const unsigned char *p = (const unsigned char *)code;
    if (size < 24) return 0;
    for (size_t i = 0; i + 17 < size; i++) {
        if (i > 0 && ishex(p[i-1])) continue;          /* must start a token */
        int ok = 1;
        for (int j = 0; j < 16; j++) if (!ishex(p[i+j])) { ok = 0; break; }
        if (!ok || p[i+16] != '.') continue;
        size_t lim = i + 16 + 128; if (lim > size - 5) lim = size - 5;
        size_t dx = 0;
        for (dx = i + 16; dx < lim; dx++)
            if (!memcmp(p + dx, ".dxil", 5)) break;
        if (dx >= lim) continue;                       /* no .dxil nearby */
        /* entry: after the '.', skipping a control byte and/or '?'
           (form seen: "<hash>.\x01?<entry>@@<mangle>.dxil") */
        size_t e = i + 17;
        while (e < size && (p[e] == '?' || p[e] < 0x20)) e++;
        size_t elen = 0;
        char entry[64];
        while (e + elen < size && isident(p[e+elen]) && elen < sizeof(entry)-1) {
            entry[elen] = p[e+elen]; elen++;
        }
        entry[elen] = 0;
        memcpy(out_hash, p + i, 16); out_hash[16] = 0;
        if (elen) snprintf(out_id, 96, "%s.%s", out_hash, entry);
        else      snprintf(out_id, 96, "%s", out_hash);
        return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* swap file resolution                                                */
/* ------------------------------------------------------------------ */
static char g_swapdir[4096];
static char g_layerdir[4096];
static void swapdir_init(void) {
    Dl_info di;
    if (dladdr((void *)swapdir_init, &di) && di.dli_fname) {
        snprintf(g_layerdir, sizeof g_layerdir, "%s", di.dli_fname);
        char *s = strrchr(g_layerdir, '/');
        if (s) *s = 0; else g_layerdir[0] = 0;
    }
    const char *env = getenv("CALLISTO_SWAP_DIR");
    if (env && *env) { snprintf(g_swapdir, sizeof g_swapdir, "%s", env); return; }
    if (g_layerdir[0]) {
        snprintf(g_swapdir, sizeof g_swapdir, "%s/swaps", g_layerdir);
        return;
    }
    snprintf(g_swapdir, sizeof g_swapdir, "swaps");
}

/* returns malloc'd code + size, or NULL */
/* Optional overlay directory, checked BEFORE the base swaps dir.
 *
 * This is the shader-side equivalent of the RED4ext plugin's disable.flag:
 * an effect that ships as its own set of swap files lives in <layerdir>/
 * swaps.<name>/, and a flag file <layerdir>/<name>.disable turns it off
 * without uninstalling anything. sync_settings.sh writes that flag from the
 * CET settings UI at launch, so the toggle costs one relaunch and never
 * needs the patcher re-run. The base swaps/ dir is always served. */
#define MAX_OVERLAYS 8
static char g_overlaydir[MAX_OVERLAYS][4096];
static char g_overlayname[MAX_OVERLAYS][64];
static int g_noverlay;

static uint32_t *load_swap_from(const char *dir, const char *name,
                                size_t *out_size) {
    char path[4608];
    snprintf(path, sizeof path, "%s/%s.spv", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    long n = -1;
    if (fseek(f, 0, SEEK_END) == 0) n = ftell(f);
    if (n < 0 || fseek(f, 0, SEEK_SET) != 0) { fclose(f); return NULL; }
    if (n < 20 || (n & 3)) { fclose(f); LOGF("\"ev\":\"swap_bad\",\"file\":\"%s\",\"size\":%ld}", path, n); return NULL; }
    uint32_t *buf = malloc(n);
    if (!buf || fread(buf, 1, n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    if (buf[0] != 0x07230203) { LOGF("\"ev\":\"swap_bad\",\"file\":\"%s\",\"reason\":\"magic\"}", path); free(buf); return NULL; }
    *out_size = (size_t)n;
    LOGF("\"ev\":\"swap_load\",\"file\":\"%s\",\"size\":%ld}", path, n);
    return buf;
}

/* If an overlay dir carries a MANIFEST.txt, echo its first line into the log.
 *
 * `26` section 7 is the reason: the layer logs a swap's FILE NAME and SIZE,
 * and binary SPIR-V stores an OpConstant in a fixed-width instruction, so two
 * variants that differ only in a constant are indistinguishable in the log --
 * and an on-screen result was once credited to a set that had never been
 * launched. A one-line provenance stamp written by the patcher costs nothing
 * and makes any future observation attributable from the log alone.
 * Everything outside [ -~] and the two JSON metacharacters is dropped, since
 * the line goes straight into a JSONL field. */
static void log_overlay_manifest(const char *name, const char *dir) {
    char path[4608];
    snprintf(path, sizeof path, "%s/MANIFEST.txt", dir);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char raw[512], clean[512];
    if (fgets(raw, sizeof raw, f)) {
        size_t j = 0;
        for (size_t i = 0; raw[i] && j + 1 < sizeof clean; i++) {
            unsigned char c = (unsigned char)raw[i];
            if (c < 0x20 || c > 0x7e || c == '"' || c == '\\') continue;
            clean[j++] = (char)c;
        }
        clean[j] = 0;
        LOGF("\"ev\":\"overlay_manifest\",\"name\":\"%s\",\"line\":\"%s\"}",
             name, clean);
    }
    fclose(f);
}

/* Resolve <layerdir>/swaps.<name> and its <layerdir>/<name>.disable flag.
 * Name comes from CALLISTO_OVERLAYS (default "skin,..."). Called once, after
 * swapdir_init has filled g_layerdir. */
static void overlay_init(void) {
    const char *list = getenv("CALLISTO_OVERLAYS");
    /* ptq carries the path-tracing quality matrix that sync_settings.sh
     * materializes per launch; it must precede the base swaps/ dir (all
     * overlays do) so its reference raygens win over the skinray copies
     * there -- which is why the matrix also ships skin-based variants. */
    /* "skin" replaced "hair" on 2026-08-28 when the hair BRDF was removed
     * (handoff/27 section 8). Deliberately NOT listed alongside it: overlays are
     * first-file-wins, so a leftover swaps.hair/ from an older install would
     * shadow the skin modules for the same shader ids and silently serve the
     * retired build. Dropping the name makes any stale dir inert. */
    /* "ser" is FIRST on purpose. It is built ON TOP of whatever ptq serves
     * (dev/patch_ser.sh refuses a vanilla source for exactly this reason), so
     * it has to win the first-file-wins race against ptq for the twelve
     * rgs_reference_main ids -- if ptq won, swaps.ser/ would be dead with no
     * error anywhere. The flip side is the trap this ordering creates: a
     * swaps.ser/ built against an OLD ptq combo keeps serving that combo
     * after the CET page changes a PT toggle -- silently, and while LOOKING
     * applied, because the cache stamp sees swaps.ptq/ change and clears the
     * pipeline caches. sync_settings.sh now ENFORCES this rather than asking
     * the reader to remember it: it recomputes the content sha of the
     * materialized swaps.ptq/ and compares it against the src_sha in
     * swaps.ser/MANIFEST.txt, writing ser.disable on any mismatch. Failing
     * that way round is the safe one -- losing the hint cannot change a pixel,
     * whereas a stale ser silently overrides the PT quality selection. */
    if (!list || !*list) list = "ser,skin,shadowcull,ptq,ptrefl";
    const char *base = g_layerdir[0] ? g_layerdir : ".";
    char buf[1024];
    snprintf(buf, sizeof buf, "%s", list);
    for (char *tok = strtok(buf, ","); tok && g_noverlay < MAX_OVERLAYS;
         tok = strtok(NULL, ",")) {
        while (*tok == ' ') tok++;
        if (!*tok) continue;
        char dir[4096], flag[4608];
        snprintf(dir, sizeof dir, "%s/swaps.%s", base, tok);
        snprintf(flag, sizeof flag, "%s/%s.disable", base, tok);
        int on = (access(dir, F_OK) == 0) && (access(flag, F_OK) != 0);
        LOGF("\"ev\":\"overlay\",\"name\":\"%s\",\"dir\":\"%s\",\"enabled\":%d}",
             tok, dir, on);
        if (on) {
            snprintf(g_overlayname[g_noverlay], 64, "%s", tok);
            snprintf(g_overlaydir[g_noverlay], 4096, "%s", dir);
            g_noverlay++;
            log_overlay_manifest(tok, dir);
        }
    }
}

/* ------------------------------------------------------------------ */
/* run status (the settings-page feedback loop)                        */
/* ------------------------------------------------------------------ */
/* The CET settings page can only render what it was asked for -- it has no
 * way to know whether a toggle actually reached the GPU. A stale pipeline
 * cache, a missing swap file or an env override all leave the page reading
 * "on" while nothing happens (see handoff/09-SETTINGS-AUDIT.md, D5/D9).
 *
 * So the layer records what it really did. CET sandboxes mod file I/O to the
 * mod's own folder, which the layer cannot know, so we write next to our own
 * .so and let sync_settings.sh copy the previous run's file into the CET mod
 * dir at the next launch. The page therefore shows "last launch", which is
 * the honest claim: this run's totals do not exist until this run is over.
 *
 * Rewritten on every hit (~92 tiny writes per launch) rather than at exit, so
 * a crash still leaves an accurate record. Written via tmp+rename so a reader
 * never sees a half-file. */
static pthread_mutex_t g_status_mu = PTHREAD_MUTEX_INITIALIZER;
static char g_statuspath[4608];
static struct {
    unsigned resolve, shadow, raygen, refl, gi, other, failed;
} g_hits;

static void status_init(void) {
    const char *env = getenv("CALLISTO_STATUS");
    if (env && *env) snprintf(g_statuspath, sizeof g_statuspath, "%s", env);
    else if (g_layerdir[0])
        snprintf(g_statuspath, sizeof g_statuspath, "%s/last_run.json", g_layerdir);
}

/* Under Proton a dozen processes load this layer -- the game, plus Steam's
 * fossilize pre-cache replayers and assorted helpers, none of which create
 * modules. A "created it first" rule was not enough: a helper still wins the
 * race when it starts before the game, and sync_settings.sh (which runs at
 * launch, concurrently with those helpers) then reads its zeroes and reports
 * "0 applied" for a launch that swapped everything.
 *
 * So the record is only ever written by a process that actually swapped
 * something. Helpers cannot produce one. "The layer loaded at all" is a
 * separate, contentless marker file, which any process may touch -- that
 * keeps "loaded but swapped nothing" (a real fault) distinguishable from
 * "never loaded" without letting a helper speak for the game. */
static void status_mark_loaded(void) {
    if (!g_statuspath[0]) return;
    char mark[4680];
    snprintf(mark, sizeof mark, "%s.loaded", g_statuspath);
    FILE *f = fopen(mark, "w");
    if (f) fclose(f);
}

static void status_write(void) {
    if (!g_statuspath[0]) return;
    char tmp[4680];
    snprintf(tmp, sizeof tmp, "%s.tmp", g_statuspath);
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    char ovl[MAX_OVERLAYS * 68], *o = ovl; *o = 0;
    for (int i = 0; i < g_noverlay; i++)
        o += snprintf(o, sizeof ovl - (size_t)(o - ovl), "%s\"%s\"",
                      i ? ", " : "", g_overlayname[i]);
    pthread_mutex_lock(&g_status_mu);
    fprintf(f,
        "{\n"
        "  \"pid\": %d,\n"
        "  \"modules_seen\": %llu,\n"
        "  \"layer\": \"loaded\",\n"
        "  \"swap_dir\": \"%s\",\n"
        "  \"overlays\": [%s],\n"
        "  \"passthrough\": %s,\n"
        "  \"hits\": { \"resolve\": %u, \"shadow\": %u, \"raygen\": %u,"
        " \"refl\": %u, \"gi\": %u, \"other\": %u, \"failed\": %u }\n"
        "}\n",
        (int)getpid(), (unsigned long long)g_seq, g_swapdir, ovl,
        g_disabled ? "true" : "false",
        g_hits.resolve, g_hits.shadow, g_hits.raygen, g_hits.refl,
        g_hits.gi, g_hits.other, g_hits.failed);
    pthread_mutex_unlock(&g_status_mu);
    fclose(f);
    if (rename(tmp, g_statuspath) != 0) remove(tmp);
}

/* Classify by the entry-point half of the module id, which is what the
 * settings page cares about: "resolve" is the GLCompute set where every
 * visible effect lives, and is the count that silently goes to zero. */
static void status_hit(const char *id, int ok) {
    pthread_mutex_lock(&g_status_mu);
    if (!ok) g_hits.failed++;
    else if (strstr(id, ".dxil")) g_hits.resolve++;
    else if (strstr(id, "rgs_shadow_main")) g_hits.shadow++;
    else if (strstr(id, "rgs_reference_main")) g_hits.raygen++;
    /* The reflection raygens get their own bucket: they are the only thing in
     * the ptrefl overlay, so "did ptrefl do anything" has to be answerable
     * without reading the jsonl. Lumped into `other` it was unanswerable. */
    else if (strstr(id, "rgs_reflection")) g_hits.refl++;
    else if (strstr(id, "rgs_restirgi")) g_hits.gi++;
    else g_hits.other++;
    pthread_mutex_unlock(&g_status_mu);
    status_write();
}

static int spv_declares_ser(const uint32_t *w, size_t bytes);
static int spv_declares_rayq(const uint32_t *w, size_t bytes);
/* BDA slot (handoff/103). `spv_has_bda_marker` is a cheap yes/no on the
 * reserved OpString; `bda_fixup` does the full four-conjunct validation and
 * rewrites the two named constants in place. Both are defined next to the
 * other SPIR-V helpers below. */
static int spv_has_bda_marker(const uint32_t *w, size_t bytes);
static int bda_fixup(uint32_t *w, size_t bytes, uint64_t addr,
                     const char **reason, uint32_t ids[2]);

/* First-file-wins across the overlays, then the base dir -- with one
 * exception (44-LOW-HANGING-FRUIT): when the device has no SER, a candidate
 * that declares ShaderInvocationReorderNV is skipped and the search
 * CONTINUES to the next overlay. Before this the reject happened after the
 * search, so a stale/unusable swaps.ser/ file turned the module VANILLA --
 * bypassing swaps.ptq/ and every splice below it, with a log line that read
 * as a SER problem rather than a PT-stack problem.
 *
 * The ray query gate (handoff/98) is the identical rule for capability
 * RayQueryKHR, and it is here rather than after the search for exactly that
 * reason: a hunt-rayq overlay served on a device without VK_KHR_ray_query
 * must fall through to swaps.skin/ and produce the BASE image, not vanilla
 * raygens on top of a patched compute set. */
static uint64_t g_bda_fixups, g_bda_fixup_lines;
#define BDA_MAX_FIXUP_LINES 8

static uint32_t *load_swap(const char *name, size_t *out_size, int allow_ser,
                           int allow_rayq, uint64_t bda_addr) {
    for (int i = 0; i < g_noverlay; i++) {
        uint32_t *c = load_swap_from(g_overlaydir[i], name, out_size);
        if (!c) continue;
        if (!allow_ser && spv_declares_ser(c, *out_size)) {
            LOGF("\"ev\":\"ser_reject\",\"id\":\"%s\",\"size\":%zu,\"dir\":\"%s\","
                 "\"reason\":\"device_extension_not_enabled\",\"action\":\"next_overlay\"}",
                 name, *out_size, g_overlaydir[i]);
            free(c);
            continue;
        }
        if (!allow_rayq && spv_declares_rayq(c, *out_size)) {
            LOGF("\"ev\":\"rayq_reject\",\"id\":\"%s\",\"size\":%zu,\"dir\":\"%s\","
                 "\"reason\":\"device_extension_not_enabled\",\"action\":\"next_overlay\"}",
                 name, *out_size, g_overlaydir[i]);
            free(c);
            continue;
        }
        /* The BDA marker is the SAME rule (98 section 7.2): a module whose
         * sentinel we cannot rewrite would dereference a garbage 64-bit
         * pointer, so it is refused HERE and the next overlay gets its turn.
         * The check is on the module's own reserved OpString, never on a
         * constant's value -- 3282 of 3323 dumped modules declare
         * PhysicalStorageBufferAddresses, so the capability discriminates
         * nothing (98 section 10.3 hole 1). */
        if (spv_has_bda_marker(c, *out_size)) {
            const char *why = "device_has_no_bda_slot";
            uint32_t ids[2] = {0, 0};
            int ok = bda_addr && bda_fixup(c, *out_size, bda_addr, &why, ids);
            if (!ok) {
                LOGF("\"ev\":\"bda_reject\",\"id\":\"%s\",\"size\":%zu,\"dir\":\"%s\","
                     "\"reason\":\"%s\",\"action\":\"next_overlay\"}",
                     name, *out_size, g_overlaydir[i], why);
                free(c);
                continue;
            }
            uint64_t n = __sync_fetch_and_add(&g_bda_fixups, 1);
            if (__sync_fetch_and_add(&g_bda_fixup_lines, 0) < BDA_MAX_FIXUP_LINES) {
                __sync_fetch_and_add(&g_bda_fixup_lines, 1);
                LOGF("\"ev\":\"bda_fixup\",\"id\":\"%s\",\"size\":%zu,\"dir\":\"%s\","
                     "\"addr\":\"0x%llx\",\"lo_id\":%u,\"hi_id\":%u,\"nth\":%llu}",
                     name, *out_size, g_overlaydir[i],
                     (unsigned long long)bda_addr, ids[0], ids[1],
                     (unsigned long long)(n + 1));
            }
        }
        return c;
    }
    /* The BASE swaps/ dir gets the SAME guard, and it is applied HERE rather
     * than in xCreateShaderModule for one reason: the fixup is DESTRUCTIVE.
     * Once a module's two constants hold the device address they no longer
     * hold the sentinel, so a second pass over the same bytes would refuse --
     * correctly, by conjunct 4 -- a module that is already right, and the
     * caller would fall back to vanilla. The marker is guarded and rewritten
     * exactly once, in exactly one place. */
    {
        uint32_t *c = load_swap_from(g_swapdir, name, out_size);
        if (c && spv_has_bda_marker(c, *out_size)) {
            const char *why = "device_has_no_bda_slot";
            uint32_t ids[2] = {0, 0};
            if (!bda_addr || !bda_fixup(c, *out_size, bda_addr, &why, ids)) {
                LOGF("\"ev\":\"bda_reject\",\"id\":\"%s\",\"size\":%zu,"
                     "\"dir\":\"%s\",\"reason\":\"%s\",\"action\":\"vanilla\"}",
                     name, *out_size, g_swapdir, why);
                free(c);
                return NULL;
            }
            __sync_fetch_and_add(&g_bda_fixups, 1);
        }
        return c;
    }
}

/* ------------------------------------------------------------------ */
/* dispatch tables                                                     */
/* ------------------------------------------------------------------ */
/* Entries are keyed by the loader dispatch key -- the first pointer-sized
 * word of a dispatchable handle -- not by the handle value. The loader hands
 * different trampoline handles to different layers for the same object, but
 * the dispatch key is stable for the object's lifetime, so this is what
 * layers are expected to key on. */
#define MAX_OBJ 16
typedef void *DispatchKey;
static DispatchKey disp_key(void *h) { return h ? *(void **)h : NULL; }

typedef struct {
    DispatchKey key;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkCreateDevice CreateDevice;
    PFN_vkDestroyInstance DestroyInstance;
    /* Needed only to ask whether the physical device supports SER before we
     * try to enable it. Resolved through the NEXT layer's gipa, so it is the
     * driver's answer, not ours. */
    PFN_vkEnumerateDeviceExtensionProperties EnumDevExt;
    /* Needed by the BDA slot (handoff/103) to pick a host-visible coherent
     * memory type. Resolved with the REAL VkInstance -- gipa(NULL, ...) only
     * hands out the global commands, so a NULL-instance lookup here would
     * silently return NULL and the slot would never arm. */
    PFN_vkGetPhysicalDeviceMemoryProperties GetMemProps;
} InstData;
typedef struct {
    DispatchKey key;
    PFN_vkGetDeviceProcAddr gdpa;
    PFN_vkDestroyDevice DestroyDevice;
    PFN_vkCreateShaderModule CreateShaderModule;
    PFN_vkDestroyShaderModule DestroyShaderModule;
    PFN_vkDestroyPipeline DestroyPipeline;
    PFN_vkCreateRayTracingPipelinesKHR CreateRTPipelines;
    PFN_vkCreateComputePipelines CreateComputePipelines;
    /* 1 iff VK_NV_ray_tracing_invocation_reorder is enabled on THIS device.
     * Per-device rather than global on purpose: a dozen Proton helper
     * processes and their devices load this layer, and serving a SER module
     * to a device without the extension is a pipeline-creation failure. */
    int ser;
    /* 1 iff VK_KHR_ray_query is enabled on THIS device (handoff/98). Same
     * per-device reasoning as `ser`: a ray-query module handed to a device
     * without the extension is a raytracing-pipeline creation failure, i.e.
     * a black screen with no obvious cause. */
    int rayq;
    /* AS journal (handoff/98 sec 8). NULL when VK_KHR_acceleration_structure
     * is not enabled, in which case the hooks are never exposed. */
    PFN_vkCreateAccelerationStructureKHR CreateAS;
    PFN_vkGetAccelerationStructureDeviceAddressKHR GetASAddr;
    /* BDA slot (handoff/103). `bda_addr` is 0 unless the whole chain came up:
     * the bufferDeviceAddress feature is on, the 256 B buffer was created,
     * bound to host-visible memory, mapped and given a device address. It is
     * the ONE value xCreateShaderModule needs, and 0 is the right default --
     * a marker-carrying module is then refused rather than handed a garbage
     * pointer. Per device for the same reason `ser`/`rayq` are. */
    uint64_t bda_addr;
    VkBuffer bda_buf;
    VkDeviceMemory bda_mem;
    volatile uint32_t *bda_map;
    /* Stage 3a: the shader-WRITABLE scratch the slot points at. 0/NULL when
     * it could not be allocated, in which case slot word 10 stays 0 and a
     * shader that reads it takes its own "no scratch" path -- the slot itself
     * still arms, so nothing that only needs the TLAS is affected. */
    uint64_t bda_scratch_addr;
    uint32_t bda_scratch_words;
    VkBuffer bda_scratch_buf;
    VkDeviceMemory bda_scratch_mem;
    volatile uint32_t *bda_scratch_map;
    PFN_vkDestroyBuffer DestroyBuffer;
    PFN_vkFreeMemory FreeMemory;
    PFN_vkUnmapMemory UnmapMemory;
} DevData;

static InstData g_inst[MAX_OBJ]; static int g_ninst;
static DevData g_dev[MAX_OBJ];   static int g_ndev;
static pthread_mutex_t g_tbl_mu = PTHREAD_MUTEX_INITIALIZER;

/* Lookups return a pointer into the table. Entries are only ever removed in
 * vkDestroy{Device,Instance}, which the app may not call concurrently with
 * use of the same object, so the returned pointer is safe to use unlocked. */
static InstData *find_inst(VkInstance i) {
    DispatchKey k = disp_key(i);
    InstData *r = NULL;
    pthread_mutex_lock(&g_tbl_mu);
    for (int n = 0; n < g_ninst; n++) if (g_inst[n].key == k) { r = &g_inst[n]; break; }
    pthread_mutex_unlock(&g_tbl_mu);
    return r;
}
static DevData *find_dev(VkDevice d) {
    DispatchKey k = disp_key(d);
    DevData *r = NULL;
    pthread_mutex_lock(&g_tbl_mu);
    for (int n = 0; n < g_ndev; n++) if (g_dev[n].key == k) { r = &g_dev[n]; break; }
    pthread_mutex_unlock(&g_tbl_mu);
    return r;
}

/* returns NULL if the table is full (logged by the caller) */
static InstData *add_inst(VkInstance i) {
    InstData *d = NULL;
    pthread_mutex_lock(&g_tbl_mu);
    if (g_ninst < MAX_OBJ) {
        d = &g_inst[g_ninst++];
        memset(d, 0, sizeof *d);
        d->key = disp_key(i);
    }
    pthread_mutex_unlock(&g_tbl_mu);
    return d;
}
static DevData *add_dev(VkDevice v) {
    DevData *d = NULL;
    pthread_mutex_lock(&g_tbl_mu);
    if (g_ndev < MAX_OBJ) {
        d = &g_dev[g_ndev++];
        memset(d, 0, sizeof *d);
        d->key = disp_key(v);
    }
    pthread_mutex_unlock(&g_tbl_mu);
    return d;
}

static void del_inst(VkInstance i) {
    DispatchKey k = disp_key(i);
    pthread_mutex_lock(&g_tbl_mu);
    for (int n = 0; n < g_ninst; n++)
        if (g_inst[n].key == k) { g_inst[n] = g_inst[--g_ninst]; break; }
    pthread_mutex_unlock(&g_tbl_mu);
}
static void del_dev(VkDevice v) {
    DispatchKey k = disp_key(v);
    pthread_mutex_lock(&g_tbl_mu);
    for (int n = 0; n < g_ndev; n++)
        if (g_dev[n].key == k) { g_dev[n] = g_dev[--g_ndev]; break; }
    pthread_mutex_unlock(&g_tbl_mu);
}

/* ------------------------------------------------------------------ */
/* identity tracking: module -> id, pipeline -> raygen module,         */
/* command buffer -> bound RT pipeline. This is how a swap HIT (module  */
/* CREATED) gets connected to a raygen actually being DISPATCHED.       */
/* ------------------------------------------------------------------ */
#define MAX_MODID 16384
#define MAX_RTPIPE 1024
#define MAX_CBBIND 1024

typedef struct { uint64_t h; char id[96]; int swapped; } ModId;
typedef struct { uint64_t h; int rgs; } RtPipe;      /* rgs: index into g_modid, -1 unknown */
typedef struct { const void *cb; uint64_t pipe; uint64_t cpipe; } CbBind;
/* compute pipeline -> the module it was built from. A swap HIT only proves
 * the module was CREATED; this is what proves it is DISPATCHED, and the group
 * counts say at what resolution -- per-pixel, or a coarse probe/tile grid. */
/* id and swapped are copied BY VALUE at pipeline creation. Storing an index
 * into g_modid was wrong: modid_del compacts the table (last entry swaps into
 * the freed slot), and the game destroys shader modules right after building
 * pipelines, so every stored index goes stale and misattributes the result. */
typedef struct { uint64_t h; char id[128]; int swapped; } CPipe;
#define MAX_CPIPE 4096

static ModId g_modid[MAX_MODID];   static int g_nmodid;
static RtPipe g_rtpipe[MAX_RTPIPE]; static int g_nrtpipe;
static CbBind g_cbbind[MAX_CBBIND]; static int g_ncbbind;
static CPipe g_cpipe[MAX_CPIPE];    static int g_ncpipe;
static uint64_t g_dispatched[MAX_CPIPE]; static int g_ndispatched; /* dedup */
static uint64_t g_traced[MAX_RTPIPE]; static int g_ntraced;   /* dedup trace_rays */
static pthread_mutex_t g_id_mu = PTHREAD_MUTEX_INITIALIZER;

/* next pointers for command-buffer hooks (resolved at device creation) */
static PFN_vkCmdBindPipeline g_next_bind;
static PFN_vkCmdDispatch g_next_dispatch;
static PFN_vkCmdDispatchIndirect g_next_dispatch_ind;
static PFN_vkCmdTraceRaysKHR g_next_trace;
static PFN_vkCmdTraceRaysIndirectKHR g_next_trace_ind;
static PFN_vkCmdTraceRaysIndirect2KHR g_next_trace_ind2;
/* AS journal: command-buffer scoped, so device-independent like the rest. */
static PFN_vkCmdBuildAccelerationStructuresKHR g_next_build_as;
/* AS journal frame tick. Present is the real frame boundary; submit is the
 * fallback for a device with no swapchain (the self-test probe). */
static PFN_vkQueuePresentKHR g_next_present;
static PFN_vkQueueSubmit g_next_submit;

/* call with g_id_mu held */
static int modid_find(uint64_t h) {
    for (int n = 0; n < g_nmodid; n++) if (g_modid[n].h == h) return n;
    return -1;
}
static void modid_add(uint64_t h, const char *id, int swapped) {
    if (!id || !*id) return;
    pthread_mutex_lock(&g_id_mu);
    int i = modid_find(h);
    if (i < 0 && g_nmodid < MAX_MODID) {
        i = g_nmodid++;
        g_modid[i].h = h;
    }
    if (i >= 0) {
        snprintf(g_modid[i].id, sizeof g_modid[i].id, "%s", id);
        g_modid[i].swapped = swapped;
    }
    pthread_mutex_unlock(&g_id_mu);
}
static void modid_del(uint64_t h) {
    pthread_mutex_lock(&g_id_mu);
    int i = modid_find(h);
    if (i >= 0) g_modid[i] = g_modid[--g_nmodid];
    pthread_mutex_unlock(&g_id_mu);
}
/* call with g_id_mu held */
static int rtpipe_find(uint64_t h) {
    for (int n = 0; n < g_nrtpipe; n++) if (g_rtpipe[n].h == h) return n;
    return -1;
}
static void rtpipe_set(uint64_t h, int rgs) {
    pthread_mutex_lock(&g_id_mu);
    int i = rtpipe_find(h);
    if (i < 0 && g_nrtpipe < MAX_RTPIPE) {
        i = g_nrtpipe++;
        g_rtpipe[i].h = h;
    }
    if (i >= 0) g_rtpipe[i].rgs = rgs;
    pthread_mutex_unlock(&g_id_mu);
}
static void rtpipe_del(uint64_t h) {
    pthread_mutex_lock(&g_id_mu);
    int i = rtpipe_find(h);
    if (i >= 0) g_rtpipe[i] = g_rtpipe[--g_nrtpipe];
    for (i = 0; i < g_ntraced; i++)
        if (g_traced[i] == h) { g_traced[i] = g_traced[--g_ntraced]; break; }
    pthread_mutex_unlock(&g_id_mu);
}
static void cpipe_set(uint64_t h, const char *id, int swapped) {
    pthread_mutex_lock(&g_id_mu);
    int i;
    for (i = 0; i < g_ncpipe; i++) if (g_cpipe[i].h == h) break;
    if (i == g_ncpipe && g_ncpipe < MAX_CPIPE) { g_cpipe[i].h = h; g_ncpipe++; }
    if (i < g_ncpipe) {
        snprintf(g_cpipe[i].id, sizeof g_cpipe[i].id, "%s", id ? id : "");
        g_cpipe[i].swapped = swapped;
    }
    pthread_mutex_unlock(&g_id_mu);
}

/* Logged once per pipeline per group-count, not per dispatch: these run every
 * frame and the log would be useless otherwise. */
static void dispatch_maybe_log(const void *cb, uint32_t gx, uint32_t gy,
                               uint32_t gz) {
    uint64_t pipe = 0;
    pthread_mutex_lock(&g_id_mu);
    for (int i = 0; i < g_ncbbind; i++)
        if (g_cbbind[i].cb == cb) { pipe = g_cbbind[i].cpipe; break; }
    int seen = 0;
    for (int i = 0; i < g_ndispatched; i++)
        if (g_dispatched[i] == pipe) { seen = 1; break; }
    char id[128]; int swapped = 0;
    id[0] = 0;
    if (pipe && !seen) {
        for (int i = 0; i < g_ncpipe; i++)
            if (g_cpipe[i].h == pipe) {
                snprintf(id, sizeof id, "%s", g_cpipe[i].id);
                swapped = g_cpipe[i].swapped;
                break;
            }
        if (g_ndispatched < MAX_CPIPE) g_dispatched[g_ndispatched++] = pipe;
    }
    pthread_mutex_unlock(&g_id_mu);
    if (pipe && !seen)
        LOGF("\"ev\":\"dispatch\",\"pipe\":\"0x%llx\",\"id\":\"%s\","
             "\"swapped\":%d,\"groups\":[%u,%u,%u]}",
             (unsigned long long)pipe, id, swapped, gx, gy, gz);
}

static void cbbind_set(const void *cb, uint64_t pipe) {
    pthread_mutex_lock(&g_id_mu);
    int i;
    for (i = 0; i < g_ncbbind; i++) if (g_cbbind[i].cb == cb) break;
    if (i == g_ncbbind && g_ncbbind < MAX_CBBIND) {
        g_cbbind[i].cb = cb; g_ncbbind++;
    }
    if (i < g_ncbbind) g_cbbind[i].pipe = pipe;
    pthread_mutex_unlock(&g_id_mu);
}

static void cbbind_set_compute(const void *cb, uint64_t pipe) {
    pthread_mutex_lock(&g_id_mu);
    int i;
    for (i = 0; i < g_ncbbind; i++) if (g_cbbind[i].cb == cb) break;
    if (i == g_ncbbind && g_ncbbind < MAX_CBBIND) {
        g_cbbind[i].cb = cb; g_ncbbind++;
    }
    if (i < g_ncbbind) g_cbbind[i].cpipe = pipe;
    pthread_mutex_unlock(&g_id_mu);
}
static void trace_maybe_log(const void *cb) {
    pthread_mutex_lock(&g_id_mu);
    uint64_t pipe = 0;
    for (int i = 0; i < g_ncbbind; i++)
        if (g_cbbind[i].cb == cb) { pipe = g_cbbind[i].pipe; break; }
    if (pipe) {
        for (int i = 0; i < g_ntraced; i++)
            if (g_traced[i] == pipe) pipe = 0;   /* already logged */
    }
    if (pipe && g_ntraced < MAX_RTPIPE) {
        g_traced[g_ntraced++] = pipe;
        int pi = rtpipe_find(pipe);
        const char *id = ""; int sw = -1;
        if (pi >= 0 && g_rtpipe[pi].rgs >= 0) {
            id = g_modid[g_rtpipe[pi].rgs].id;
            sw = g_modid[g_rtpipe[pi].rgs].swapped;
        }
        pthread_mutex_unlock(&g_id_mu);
        LOGF("\"ev\":\"trace_rays\",\"pipe\":\"0x%llx\",\"rgs\":\"%s\",\"swapped\":%d}",
             (unsigned long long)pipe, id, sw);
        return;
    }
    pthread_mutex_unlock(&g_id_mu);
}

/* ------------------------------------------------------------------ */
/* AS journal (handoff/98 sec 8, Stage 2a)                             */
/* ------------------------------------------------------------------ */
/* Pure measurement: it answers "how many top-level acceleration structures
 * does this game have, how often is each one rebuilt, and how many instances
 * does it carry" without touching a single shader byte.  Everything here is
 * throttled -- these calls run every frame and an untuned log would be
 * gigabytes -- so the invariant is: a bounded number of lines per RUN, not per
 * frame.  CALLISTO_ASJOURNAL_DISABLE=1 makes every entry point a passthrough.
 *
 * ---- What the first version got wrong, and why (98 sec 12.5) --------------
 *
 * v1 took the AS type from VkAccelerationStructureCreateInfoKHR::type.
 * vkd3d-proton creates EVERY acceleration structure as
 * VK_ACCELERATION_STRUCTURE_TYPE_GENERIC_KHR -- D3D12 does not commit to
 * top/bottom at creation either -- so v1 saw `type:"generic"` on all 24 logged
 * creates, classified nothing as top-level, and reported
 * `distinct_top_addr:0` on every launch.  The real type is only knowable at
 * BUILD time, from VkAccelerationStructureBuildGeometryInfoKHR::type, and a
 * build whose geometry is VK_GEOMETRY_TYPE_INSTANCES_KHR is a TLAS whatever
 * that field claims.  Classification therefore moved to asj_note_build().
 *
 * v1 also reported `type:"untracked"` on 31 of 32 as_build lines.  That was a
 * second, independent bug: the build line took its type from the handle table,
 * so a dstAccelerationStructure the table did not hold printed "untracked".
 * The table did not hold it because MAX_AS was 128 while a streaming world
 * creates thousands of BLASes; g_as_overflow counted the loss but was only
 * printed by the device_destroy summary, and the game never destroys its
 * device cleanly, so that line was never emitted in any launch.  Three fixes,
 * and any one of them alone would have removed the symptom:
 *   1. the build line's type now comes from the build info, never the table,
 *      so "untracked" is unreachable by construction;
 *   2. asj_note_build() INSERTS a missing destination instead of shrugging;
 *   3. the table is larger, evicts round-robin, PINS anything classified
 *      top-level so a TLAS can never be evicted, and every summary -- now
 *      emitted periodically, not only at device teardown -- prints the
 *      overflow and eviction counters.
 *
 * Handle recycling: we deliberately do not hook vkDestroyAccelerationStructure.
 * A destroyed handle whose value is later reused by a fresh AS would otherwise
 * read as "the address moved", so as_create resets any entry it collides with
 * and counts it as a reuse; a reuse between the create and the next address
 * query is therefore visible in the journal rather than silently miscounted. */
#define MAX_AS        2048   /* handle table entries (TLASes are pinned)    */
#define AS_IX_BITS    12
#define AS_IX_SZ      (1u << AS_IX_BITS)     /* open-addressed index slots  */
#define MAX_TLAS      64     /* distinct handles ever classified top-level  */
#define MAX_TLAS_ADDR 64     /* distinct (handle, device address) pairs     */
#define ASJ_MAX_CREATE_LINES 24   /* BLAS creates past this are counted only */
#define ASJ_MAX_ADDR_LINES   64
#define ASJ_MAX_BUILD_LINES  32   /* first build of each BLAS destination    */
#define ASJ_MAX_TLAS_LINES   64   /* "a new TLAS appeared" lines             */
#define ASJ_SUMMARY_EVERY  8192   /* address queries between summary lines   */
#define ASJ_SUMMARY_FRAMES  600   /* frames between summary lines            */
#define ASJ_BPF_BUCKETS       9   /* builds-per-frame histogram, 8 = "8 or more" */

typedef struct {
    uint64_t h;            /* VkAccelerationStructureKHR                  */
    uint64_t addr;         /* last device address returned, 0 = unqueried */
    uint64_t size;         /* VkAccelerationStructureCreateInfoKHR.size   */
    uint32_t create_type;  /* as DECLARED at create; vkd3d says "generic" */
    uint32_t build_type;   /* as CLASSIFIED at build; the authority       */
    uint32_t queries;      /* vkGetAccelerationStructureDeviceAddressKHR  */
    uint32_t moved;        /* address changed while the handle lived      */
    uint32_t builds;       /* MODE_BUILD as a build destination           */
    uint32_t updates;      /* MODE_UPDATE as a build destination          */
    uint32_t reused;       /* handle value recycled by a later create     */
    uint32_t last_prims;   /* last build's total primitiveCount           */
    uint32_t max_prims;    /*  (for a TLAS: the instance count)           */
    uint32_t geoms;        /* last build's geometryCount                  */
    uint32_t flags;        /* last build's VkBuildAccelerationStructureFlags */
    uint64_t frame_last;   /* frame tick of the most recent build         */
    uint32_t in_frame;     /* builds recorded during frame_last           */
    uint32_t bpf[ASJ_BPF_BUCKETS];  /* histogram of builds-per-frame      */
    uint8_t  pinned;       /* classified top-level: never evict           */
} AsEnt;

static AsEnt   g_as[MAX_AS];
static int     g_nas;
static int32_t g_as_ix[AS_IX_SZ];   /* 0 empty, -1 tombstone, else idx+1  */
static int     g_as_ix_used;        /* slots that are not empty            */
static int     g_as_evict_cur;
static uint64_t g_as_evictions, g_as_ix_rebuilds;
static int     g_as_overflow;               /* inserts dropped, all pinned */
static struct { uint64_t addr, h; } g_tlas_addr[MAX_TLAS_ADDR];
static int     g_ntlas_addr, g_tlas_addr_overflow;
static uint64_t g_tlas_handles[MAX_TLAS];
static int     g_ntlas_handles, g_tlas_handle_overflow;
static uint64_t g_as_creates, g_as_creates_declared_top;
static uint64_t g_as_addr_calls, g_as_build_calls, g_as_build_ranges;
static uint64_t g_as_builds_top, g_as_updates_top, g_as_builds_bottom;
static uint64_t g_frame;                    /* frame tick                  */
static const char *g_frame_src = "none";    /* present | submit | none     */
static int      g_asj_create_lines, g_asj_addr_lines;
static int      g_asj_build_lines, g_asj_tlas_lines;
static pthread_mutex_t g_as_mu = PTHREAD_MUTEX_INITIALIZER;

static const char *as_type_name(uint32_t t) {
    switch (t) {
    case VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR:    return "top";
    case VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR: return "bottom";
    case VK_ACCELERATION_STRUCTURE_TYPE_GENERIC_KHR:      return "generic";
    default:                                              return "unknown";
    }
}

/* The one function that decides what an acceleration structure IS.
 * Precedence, strongest first:
 *   1. any geometry of type INSTANCES  -> top-level, whatever ::type says.
 *      An instance-geometry build is a TLAS build by definition; nothing else
 *      can consume VkAccelerationStructureInstanceKHR.
 *   2. ::type when it is explicitly top or bottom.
 *   3. GENERIC with non-instance geometry -> bottom-level. This is the
 *      vkd3d-proton case for every BLAS in the game. */
static uint32_t asj_classify(const VkAccelerationStructureBuildGeometryInfoKHR *gi) {
    for (uint32_t g = 0; g < gi->geometryCount; g++) {
        const VkAccelerationStructureGeometryKHR *ge =
            gi->pGeometries    ? &gi->pGeometries[g] :
            gi->ppGeometries   ?  gi->ppGeometries[g] : NULL;
        if (ge && ge->geometryType == VK_GEOMETRY_TYPE_INSTANCES_KHR)
            return VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
    }
    if (gi->type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR ||
        gi->type == VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR)
        return gi->type;
    return VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR;
}

/* Effective type of a tracked handle: the build-time answer if there has been
 * a build, otherwise the create-time declaration -- but only when that
 * declaration was not GENERIC, because GENERIC says nothing. */
static uint32_t as_eff_type(const AsEnt *e) {
    if (e->build_type != (uint32_t)-1) return e->build_type;
    if (e->create_type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR ||
        e->create_type == VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR)
        return e->create_type;
    return (uint32_t)-1;
}

/* ---- handle table: open addressing, linear probing, tombstones ---- */
static uint32_t as_hash(uint64_t h) {
    h *= 0x9E3779B97F4A7C15ull;
    return (uint32_t)(h >> (64 - AS_IX_BITS)) & (AS_IX_SZ - 1);
}
static void as_ix_rebuild(void) {
    memset(g_as_ix, 0, sizeof g_as_ix);
    g_as_ix_used = 0;
    for (int i = 0; i < g_nas; i++) {
        uint32_t s = as_hash(g_as[i].h);
        while (g_as_ix[s] > 0) s = (s + 1) & (AS_IX_SZ - 1);
        g_as_ix[s] = i + 1;
        g_as_ix_used++;
    }
    g_as_ix_rebuilds++;
}
/* Caller holds g_as_mu. */
static AsEnt *as_find(uint64_t h) {
    uint32_t s = as_hash(h);
    for (uint32_t n = 0; n < AS_IX_SZ; n++, s = (s + 1) & (AS_IX_SZ - 1)) {
        int32_t v = g_as_ix[s];
        if (v == 0) return NULL;                    /* empty: definitely absent */
        if (v > 0 && g_as[v - 1].h == h) return &g_as[v - 1];
    }
    return NULL;
}
static void as_ix_put(uint64_t h, int idx) {
    uint32_t s = as_hash(h), ts = 0; int have_tomb = 0;
    for (uint32_t n = 0; n < AS_IX_SZ; n++, s = (s + 1) & (AS_IX_SZ - 1)) {
        int32_t v = g_as_ix[s];
        if (v < 0) { if (!have_tomb) { have_tomb = 1; ts = s; } continue; }
        if (v == 0) {
            if (have_tomb) g_as_ix[ts] = idx + 1;    /* reuse: used unchanged */
            else { g_as_ix[s] = idx + 1; g_as_ix_used++; }
            return;
        }
        if (g_as[v - 1].h == h) { g_as_ix[s] = idx + 1; return; }
    }
    if (have_tomb) { g_as_ix[ts] = idx + 1; return; }
    as_ix_rebuild();                                 /* index saturated */
    as_ix_put(h, idx);
}
static void as_ix_drop(uint64_t h) {
    uint32_t s = as_hash(h);
    for (uint32_t n = 0; n < AS_IX_SZ; n++, s = (s + 1) & (AS_IX_SZ - 1)) {
        int32_t v = g_as_ix[s];
        if (v == 0) return;
        if (v > 0 && g_as[v - 1].h == h) { g_as_ix[s] = -1; return; }
    }
}
/* Caller holds g_as_mu. Returns an entry for h, creating (and if necessary
 * evicting an UNPINNED entry) to make room. NULL only when every one of the
 * MAX_AS entries is a pinned TLAS, which cannot happen with MAX_TLAS < MAX_AS
 * but is handled rather than assumed. */
static AsEnt *as_intern(uint64_t h) {
    AsEnt *e = as_find(h);
    if (e) return e;
    int idx;
    if (g_nas < MAX_AS) {
        idx = g_nas++;
    } else {
        int start = g_as_evict_cur, found = -1;
        for (int n = 0; n < MAX_AS; n++) {
            int i = (start + n) % MAX_AS;
            if (!g_as[i].pinned) { found = i; break; }
        }
        if (found < 0) { g_as_overflow++; return NULL; }
        g_as_evict_cur = (found + 1) % MAX_AS;
        as_ix_drop(g_as[found].h);
        g_as_evictions++;
        idx = found;
    }
    memset(&g_as[idx], 0, sizeof g_as[idx]);
    g_as[idx].h = h;
    g_as[idx].build_type = (uint32_t)-1;
    g_as[idx].create_type = (uint32_t)-1;
    as_ix_put(h, idx);
    if (g_as_ix_used * 4 > (int)AS_IX_SZ * 3) as_ix_rebuild();  /* dump tombstones */
    return &g_as[idx];
}

/* Caller holds g_as_mu. Records that h is a TLAS, and -- the requirement from
 * the review -- keys the address table on the build destination AND its
 * device address, so the pair is what is counted, not either half. */
static int asj_note_tlas(AsEnt *e) {
    int fresh = 0;
    if (!e->pinned) {
        e->pinned = 1;
        if (g_ntlas_handles < MAX_TLAS) g_tlas_handles[g_ntlas_handles++] = e->h;
        else g_tlas_handle_overflow++;
        fresh = 1;
    }
    if (e->addr) {
        int seen = 0;
        for (int i = 0; i < g_ntlas_addr; i++)
            if (g_tlas_addr[i].addr == e->addr && g_tlas_addr[i].h == e->h) { seen = 1; break; }
        if (!seen) {
            if (g_ntlas_addr < MAX_TLAS_ADDR) {
                g_tlas_addr[g_ntlas_addr].addr = e->addr;
                g_tlas_addr[g_ntlas_addr].h = e->h;
                g_ntlas_addr++;
            } else g_tlas_addr_overflow++;
        }
    }
    return fresh;
}

/* ---- the summary: emitted periodically AND at device teardown ---- */
/* v1 emitted the run's whole answer only from vkDestroyDevice, which this game
 * never reaches -- not one device_destroy line exists in any launch's jsonl.
 * The rows are snapshotted under the lock and logged outside it. */
static void asj_report(const char *why) {
    struct { uint64_t h, addr; uint32_t b, u, mx, lp, mp, gm, fl, mv;
             uint32_t bpf[ASJ_BPF_BUCKETS]; } row[MAX_TLAS];
    int nrow = 0;
    pthread_mutex_lock(&g_as_mu);
    uint64_t cr = g_as_creates, crt = g_as_creates_declared_top;
    uint64_t ac = g_as_addr_calls, bc = g_as_build_calls, br = g_as_build_ranges;
    uint64_t bt = g_as_builds_top, ut = g_as_updates_top, bb = g_as_builds_bottom;
    uint64_t fr = g_frame, ev = g_as_evictions, rb = g_as_ix_rebuilds;
    const char *fs = g_frame_src;
    int nas = g_nas, nth = g_ntlas_handles, nta = g_ntlas_addr;
    int ovf = g_as_overflow, tho = g_tlas_handle_overflow, tao = g_tlas_addr_overflow;
    int moved = 0;
    for (int i = 0; i < g_nas; i++) if (g_as[i].moved) moved++;
    for (int i = 0; i < g_nas && nrow < MAX_TLAS; i++) {
        if (!g_as[i].pinned) continue;
        AsEnt *e = &g_as[i];
        uint32_t mx = 0;
        for (int b = ASJ_BPF_BUCKETS - 1; b >= 0; b--)
            if (e->bpf[b]) { mx = (uint32_t)b; break; }
        row[nrow].h = e->h; row[nrow].addr = e->addr;
        row[nrow].b = e->builds; row[nrow].u = e->updates; row[nrow].mx = mx;
        row[nrow].lp = e->last_prims; row[nrow].mp = e->max_prims;
        row[nrow].gm = e->geoms; row[nrow].fl = e->flags; row[nrow].mv = e->moved;
        memcpy(row[nrow].bpf, e->bpf, sizeof e->bpf);
        nrow++;
    }
    pthread_mutex_unlock(&g_as_mu);
    if (!cr && !ac && !bc) return;      /* nothing observed; stay silent */
    for (int i = 0; i < nrow; i++) {
        char hist[128]; int p = 0;
        for (int b = 1; b < ASJ_BPF_BUCKETS && p < (int)sizeof hist - 12; b++)
            if (row[i].bpf[b])
                p += snprintf(hist + p, sizeof hist - p, "%s\"%d%s\":%u",
                              p ? "," : "", b,
                              b == ASJ_BPF_BUCKETS - 1 ? "+" : "", row[i].bpf[b]);
        hist[p] = 0;
        LOGF("\"ev\":\"as_tlas\",\"why\":\"%s\",\"as\":\"0x%llx\",\"addr\":\"0x%llx\","
             "\"builds\":%u,\"updates\":%u,\"max_builds_per_frame\":%u,"
             "\"builds_per_frame\":{%s},\"instances_last\":%u,\"instances_max\":%u,"
             "\"geoms\":%u,\"build_flags\":%u,\"addr_moved\":%u}",
             why, (unsigned long long)row[i].h, (unsigned long long)row[i].addr,
             row[i].b, row[i].u, row[i].mx, hist,
             row[i].lp, row[i].mp, row[i].gm, row[i].fl, row[i].mv);
    }
    LOGF("\"ev\":\"as_summary\",\"why\":\"%s\",\"frames\":%llu,\"frame_src\":\"%s\","
         "\"tlas_handles\":%d,\"tlas_addr_pairs\":%d,\"creates\":%llu,"
         "\"creates_declared_top\":%llu,\"builds\":%llu,\"build_geoms\":%llu,"
         "\"tlas_builds\":%llu,\"tlas_updates\":%llu,\"blas_builds\":%llu,"
         "\"addr_calls\":%llu,\"tracked\":%d,\"handles_with_moving_addr\":%d,"
         "\"evictions\":%llu,\"index_rebuilds\":%llu,\"table_overflow\":%d,"
         "\"tlas_handle_overflow\":%d,\"tlas_addr_overflow\":%d,"
         "\"untracked_builds\":0}",
         why, (unsigned long long)fr, fs, nth, nta,
         (unsigned long long)cr, (unsigned long long)crt,
         (unsigned long long)bc, (unsigned long long)br,
         (unsigned long long)bt, (unsigned long long)ut,
         (unsigned long long)bb, (unsigned long long)ac,
         nas, moved, (unsigned long long)ev, (unsigned long long)rb,
         ovf, tho, tao);
}

static void asj_note_create(uint64_t h, uint32_t type, uint64_t size) {
    int log_it = 0, reuse = 0;
    pthread_mutex_lock(&g_as_mu);
    g_as_creates++;
    if (type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR) g_as_creates_declared_top++;
    AsEnt *e = as_find(h);
    if (e) {                       /* handle value recycled -- start over */
        uint32_t r = e->reused + 1;
        memset(e, 0, sizeof *e);
        e->h = h; e->reused = r; e->build_type = (uint32_t)-1; reuse = 1;
    } else {
        e = as_intern(h);
    }
    if (e) { e->create_type = type; e->size = size;
             if (type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR)
                 asj_note_tlas(e); }
    /* A create that DECLARES top-level is worth a line (there are a handful);
     * the rest are capped, because a streaming world makes thousands.  Note
     * vkd3d-proton declares GENERIC for all of them -- see the header. */
    if (type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR ||
        g_asj_create_lines < ASJ_MAX_CREATE_LINES) {
        g_asj_create_lines++;
        log_it = 1;
    }
    uint64_t n = g_as_creates, nt = g_as_creates_declared_top;
    pthread_mutex_unlock(&g_as_mu);
    if (log_it)
        LOGF("\"ev\":\"as_create\",\"as\":\"0x%llx\",\"type\":\"%s\","
             "\"size\":%llu,\"reuse\":%d,\"n\":%llu,\"n_top\":%llu}",
             (unsigned long long)h, as_type_name(type),
             (unsigned long long)size, reuse,
             (unsigned long long)n, (unsigned long long)nt);
}

static void asj_note_addr(uint64_t h, uint64_t addr) {
    int log_it = 0, moved = 0, newaddr = 0, summary = 0;
    uint32_t type = (uint32_t)-1, queries = 0;
    pthread_mutex_lock(&g_as_mu);
    g_as_addr_calls++;
    AsEnt *e = as_intern(h);       /* intern, not find: an address query on an
                                    * AS created before we were hooked is still
                                    * a fact worth keeping */
    if (e) {
        if (e->addr && e->addr != addr) { e->moved++; moved = 1; }
        if (!e->addr) newaddr = 1;
        e->addr = addr;
        e->queries++;
        queries = e->queries;
        type = as_eff_type(e);
        /* Already known to be a TLAS? then this (handle,address) pair goes in
         * the table now. If it is not classified yet, the first build will do
         * it and pick the address up from the entry. */
        if (type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR && addr) {
            int before = g_ntlas_addr;
            asj_note_tlas(e);
            if (g_ntlas_addr != before) newaddr = 1;
        }
    }
    if ((newaddr || moved) && g_asj_addr_lines < ASJ_MAX_ADDR_LINES) {
        g_asj_addr_lines++;
        log_it = 1;
    }
    if (g_as_addr_calls % ASJ_SUMMARY_EVERY == 0) summary = 1;
    int ntl = g_ntlas_addr;
    pthread_mutex_unlock(&g_as_mu);
    if (log_it)
        LOGF("\"ev\":\"as_addr\",\"as\":\"0x%llx\",\"addr\":\"0x%llx\","
             "\"type\":\"%s\",\"moved\":%d,\"queries\":%u,"
             "\"distinct_top_addr\":%d}",
             (unsigned long long)h, (unsigned long long)addr,
             type == (uint32_t)-1 ? "unclassified" : as_type_name(type),
             moved, queries, ntl);
    if (summary) asj_report("periodic_addr");
}

/* Stage 2b's refresh hook; defined below, next to the slot it writes. */
static void bda_note_tlas(uint64_t addr, uint32_t prims, uint64_t frame);
static void bda_scratch_report(const char *why);

static void asj_note_build(uint32_t n,
        const VkAccelerationStructureBuildGeometryInfoKHR *infos,
        const VkAccelerationStructureBuildRangeInfoKHR *const *ranges) {
    if (!infos) return;
    for (uint32_t i = 0; i < n; i++) {
        uint64_t dst = (uint64_t)infos[i].dstAccelerationStructure;
        uint32_t type = asj_classify(&infos[i]);   /* the authority. */
        int is_top = type == VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
        int upd = infos[i].mode == VK_BUILD_ACCELERATION_STRUCTURE_MODE_UPDATE_KHR;
        uint32_t prims = 0;
        if (ranges && ranges[i])
            for (uint32_t g = 0; g < infos[i].geometryCount; g++)
                prims += ranges[i][g].primitiveCount;
        int log_it = 0, fresh_tlas = 0; uint32_t nb = 0, in_frame = 0;
        uint32_t declared = (uint32_t)-1;
        uint64_t addr = 0, frame;
        pthread_mutex_lock(&g_as_mu);
        g_as_build_calls++;
        g_as_build_ranges += infos[i].geometryCount;
        if (is_top) { if (upd) g_as_updates_top++; else g_as_builds_top++; }
        else g_as_builds_bottom++;
        frame = g_frame;
        AsEnt *e = as_intern(dst);
        if (e) {
            e->build_type = type;
            if (upd) e->updates++; else e->builds++;
            e->last_prims = prims;
            if (prims > e->max_prims) e->max_prims = prims;
            e->geoms = infos[i].geometryCount;
            e->flags = (uint32_t)infos[i].flags;
            if (e->frame_last != frame || !e->in_frame) {
                e->frame_last = frame; e->in_frame = 0;
            }
            /* Maintain the builds-per-frame histogram incrementally: move this
             * destination out of its old bucket and into the new one. */
            if (e->in_frame) {
                int ob = e->in_frame < ASJ_BPF_BUCKETS - 1
                       ? (int)e->in_frame : ASJ_BPF_BUCKETS - 1;
                if (e->bpf[ob]) e->bpf[ob]--;
            }
            e->in_frame++;
            {
                int nbk = e->in_frame < ASJ_BPF_BUCKETS - 1
                        ? (int)e->in_frame : ASJ_BPF_BUCKETS - 1;
                e->bpf[nbk]++;
            }
            in_frame = e->in_frame;
            nb = e->builds + e->updates;
            addr = e->addr;
            declared = e->create_type;   /* what the CREATE claimed, if seen */
            if (is_top) fresh_tlas = asj_note_tlas(e);
        }
        /* Every first sighting of a TLAS gets a line; BLAS destinations get
         * their first build only, capped. */
        if (fresh_tlas) {
            if (g_asj_tlas_lines < ASJ_MAX_TLAS_LINES) { g_asj_tlas_lines++; log_it = 2; }
        } else if (!is_top && nb <= 1 && g_asj_build_lines < ASJ_MAX_BUILD_LINES) {
            g_asj_build_lines++; log_it = 1;
        }
        pthread_mutex_unlock(&g_as_mu);
        if (log_it)
            LOGF("\"ev\":\"as_build\",\"dst\":\"0x%llx\",\"addr\":\"0x%llx\","
                 "\"type\":\"%s\",\"build_info_type\":\"%s\","
                 "\"declared_at_create\":\"%s\",\"mode\":\"%s\","
                 "\"flags\":%u,\"geoms\":%u,\"prims\":%u,\"nth_build\":%u,"
                 "\"in_frame\":%u,\"frame\":%llu,\"new_tlas\":%d}",
                 (unsigned long long)dst, (unsigned long long)addr,
                 as_type_name(type), as_type_name((uint32_t)infos[i].type),
                 declared == (uint32_t)-1 ? "not_seen" : as_type_name(declared),
                 upd ? "update" : "build",
                 (unsigned)infos[i].flags, infos[i].geometryCount, prims,
                 nb, in_frame, (unsigned long long)frame, log_it == 2);
        /* Stage 2b: the newest top-level address goes into the layer's slot.
         * Done OUTSIDE g_as_mu (bda_note_tlas takes its own lock) and at
         * command-RECORD time, which is before the submit that consumes it. */
        if (is_top && addr) bda_note_tlas(addr, prims, frame);
    }
}

/* The frame tick. vkQueuePresentKHR is the real frame boundary; vkQueueSubmit
 * is the fallback for a device with no swapchain (the self-test probe), and
 * whichever armed first is named in every summary as frame_src so a reader
 * never has to guess what "frames" counts. */
static void asj_note_frame(const char *src) {
    uint64_t f; int summary;
    pthread_mutex_lock(&g_as_mu);
    g_frame_src = src;             /* the source of the MOST RECENT tick */
    f = ++g_frame;
    summary = (f % ASJ_SUMMARY_FRAMES) == 0;
    pthread_mutex_unlock(&g_as_mu);
    if (summary) { asj_report("periodic_frame");
                   bda_scratch_report("periodic_frame"); }
}

static void asj_final_summary(void) { asj_report("device_destroy"); }

/* ------------------------------------------------------------------ */
/* BDA SLOT -- Stage 2b (handoff/103-STAGE-2B.md)                       */
/* ------------------------------------------------------------------ */
/* One 256 B host-visible buffer per RT-capable device. Layout, in uint32
 * words, and this table is the normative copy -- dev/patch_bda.py reads the
 * same offsets and dev/verify_bda.py asserts them:
 *
 *   [0] magic          CALLISTO_BDA_MAGIC, written once at allocation
 *   [1] generation     bumped every time [2]/[3] change
 *   [2] tlas_addr_lo   newest POPULATED top-level AS device address, low 32
 *   [3] tlas_addr_hi   ... high 32
 *   [4] tlas_prims     that build's instance count
 *   [5] tlas_builds    how many top-level builds have been recorded
 *   [6] frame          the AS journal's frame counter at the last refresh
 *   [7] flags          bit 0: a POPULATED TLAS has been seen (prims > 0)
 *   [8] scratch_lo     SCRATCH buffer device address, low 32   (Stage 3a)
 *   [9] scratch_hi     ... high 32
 *  [10] scratch_words  its size in uint32 words, 0 when there is none
 *  [11] scratch_flags  bit 0: armed, bit 1: the layer can READ it back
 *
 * STAGE 3a -- THE SCRATCH BUFFER (handoff/116). Words 0-7 are a MAILBOX: the
 * layer writes, the shader reads, and the shader's struct decorates every
 * member NonWritable. Words 8-11 point at a SECOND, much larger allocation
 * that is the other way round -- the shader writes it, and it persists across
 * dispatches, passes and frames because nobody clears it after the initial
 * host zero-fill. That is the whole unlock: a compute resolver and a raygen
 * that share no descriptor can share a per-pixel word.
 *
 * The first 16 words of the scratch are reserved for shader-side counters
 * (CALLISTO_SCRATCH_HDR); the payload starts there. The layer only ever reads
 * that header, and only to log it -- it never writes the scratch after
 * allocation, so a value in it came from a shader or from nobody.
 *
 * Host read-back is a convenience, not a guarantee: a shader write reaching
 * HOST_COHERENT memory is formally visible to the host only after a barrier
 * with dst HOST_READ, and this layer records no command buffer of its own in
 * which to put one. In practice on this driver the write lands, and the
 * SHADER-side read-back (a later invocation reading an earlier one's word) is
 * the claim that needs no host visibility at all and is what the rungs test.
 *
 * Why host-visible and not staged: the address is written at COMMAND RECORD
 * time, i.e. before the vkQueueSubmit that consumes it, and Vulkan's implicit
 * host-to-device domain operation at submit makes a host write to coherent
 * memory visible to that submission. And in the steady state the write is a
 * no-op: 98 section 13.4 measured `addr_moved:0` / `handles_with_moving_addr:0`
 * over 600 presents and 632 TLAS builds, so after the first frame the same 64
 * bits are re-written, which is why nothing here needs a barrier. The refresh
 * still exists rather than a one-shot constant because a per-launch constant
 * cannot survive an address that moves, and the journal's evidence is one
 * session -- the indirection costs one dword load and removes the assumption. */
#define CALLISTO_BDA_MARKER  "CALLISTO_BDA_SLOT_V1"
#define CALLISTO_BDA_SENT_LO 0x0BDA0001u
#define CALLISTO_BDA_SENT_HI 0xCA115700u
#define CALLISTO_BDA_MAGIC   0xCA115701u
#define CALLISTO_BDA_WORDS   64          /* 256 bytes */
#define BDA_W_MAGIC 0u
#define BDA_W_GEN   1u
#define BDA_W_LO    2u
#define BDA_W_HI    3u
#define BDA_W_PRIMS 4u
#define BDA_W_BUILDS 5u
#define BDA_W_FRAME 6u
#define BDA_W_FLAGS 7u
#define BDA_W_SCR_LO    8u
#define BDA_W_SCR_HI    9u
#define BDA_W_SCR_WORDS 10u
#define BDA_W_SCR_FLAGS 11u
#define BDA_SCR_F_ARMED    1u   /* the address in [8]/[9] is real            */
#define BDA_SCR_F_READBACK 2u   /* ... and the layer mapped it, so it logs   */
#define CALLISTO_SCRATCH_HDR 16u /* words reserved for shader-side counters  */

/* The device whose slot the AS-journal build hook refreshes. The hook is a
 * command-buffer entry point and cannot name a VkDevice, and the game creates
 * exactly one AS-capable device; a second one arming is logged rather than
 * silently ignored, because "the wrong device's address" is the failure this
 * would produce and it would be invisible on screen. */
static DevData *g_bda_dev;
static uint64_t g_bda_tlas_addr, g_bda_tlas_refreshes, g_bda_tlas_changes;
static int g_bda_multi_dev;
static pthread_mutex_t g_bda_mu = PTHREAD_MUTEX_INITIALIZER;

#define SPV_OP_STRING     7u
#define SPV_OP_TYPE_INT  21u
#define SPV_OP_CONSTANT  43u
#define SPV_OP_FUNCTION  54u

/* Read the packed literal string of an OpString-shaped instruction into `out`
 * (always NUL-terminated). Returns 0 if it does not fit. */
static int spv_literal_string(const uint32_t *w, uint32_t first, uint32_t last,
                              char *out, size_t cap) {
    size_t k = 0;
    for (uint32_t i = first; i < last; i++) {
        for (int b = 0; b < 4; b++) {
            char c = (char)((w[i] >> (8 * b)) & 0xffu);
            if (k + 1 >= cap) return 0;
            out[k++] = c;
            if (!c) { return 1; }
        }
    }
    if (k >= cap) return 0;
    out[k] = 0;
    return 1;
}

/* Count the reserved marker OpStrings, and copy the first one's text out.
 * The scan stops at the first OpFunction: OpString lives in the debug section,
 * so nothing after the function bodies begin can be one, and a module's whole
 * body is not walked on every one of ~3300 vkCreateShaderModule calls.
 *
 * Returns the COUNT, saturating at 2, and the distinction matters: a module
 * carrying TWO markers must be REFUSED, not quietly served. Returning a bare
 * "not found" for it would make spv_has_bda_marker() say no, the reject guard
 * would never run, and the module would reach the driver still holding the
 * sentinel -- i.e. a wild 64-bit pointer. Ambiguous is a reject, never a pass. */
static int spv_bda_marker_count(const uint32_t *w, size_t bytes,
                                char *out, size_t cap) {
    size_t n = bytes / 4, i;
    int found = 0;
    if (!w || n < 5 || w[0] != 0x07230203) return 0;
    for (i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffffu;
        if (len == 0 || i + len > n) break;
        if (op == SPV_OP_FUNCTION) break;
        if (op == SPV_OP_STRING && len >= 3) {
            char buf[256];
            if (spv_literal_string(w, i + 2, i + len, buf, sizeof buf)
                && !strncmp(buf, CALLISTO_BDA_MARKER,
                            sizeof CALLISTO_BDA_MARKER - 1)) {
                if (found) return 2;          /* two markers: ambiguous */
                found = 1;
                if (out) snprintf(out, cap, "%s", buf);
            }
        }
        i += len;
    }
    return found;
}

static int spv_has_bda_marker(const uint32_t *w, size_t bytes) {
    return spv_bda_marker_count(w, bytes, NULL, 0) > 0;
}

/* Rewrite the two OpConstant literals the marker NAMES. Four conjuncts, all
 * required, and any failure leaves the module untouched and refused:
 *   1. exactly one well-formed marker string, parsed for lo=/hi=/sent=/magic=
 *   2. the declared sentinel and magic match this build's
 *   3. each named id is defined by exactly one OpConstant of a 32-bit
 *      UNSIGNED OpTypeInt
 *   4. each of those constants currently holds its half of the sentinel
 * This is what makes the fixup structural rather than a value scan
 * (98 section 10.3 hole 2): a stray module that happens to contain the sentinel
 * words has no marker, so nothing is rewritten in it, and a forged marker
 * naming ids that are not sentinel-valued uint constants is refused. */
static int bda_fixup(uint32_t *w, size_t bytes, uint64_t addr,
                     const char **reason, uint32_t ids[2]) {
    char m[256];
    unsigned lo_id = 0, hi_id = 0;
    unsigned long long sent = 0; unsigned long magic = 0;
    size_t n = bytes / 4, i;
    {
        int nm = spv_bda_marker_count(w, bytes, m, sizeof m);
        *reason = "no_marker";
        if (nm == 0) return 0;
        *reason = "two_markers";
        if (nm != 1) return 0;
    }
    *reason = "marker_malformed";
    if (sscanf(m, CALLISTO_BDA_MARKER " lo=%%%u hi=%%%u sent=%llx magic=%lx",
               &lo_id, &hi_id, &sent, &magic) != 4) return 0;
    if (!lo_id || !hi_id || lo_id == hi_id) return 0;
    *reason = "sentinel_mismatch";
    if (sent != (((unsigned long long)CALLISTO_BDA_SENT_HI << 32)
                 | CALLISTO_BDA_SENT_LO)) return 0;
    if (magic != CALLISTO_BDA_MAGIC) return 0;
    if (lo_id >= w[3] || hi_id >= w[3]) { *reason = "id_out_of_bound"; return 0; }

    /* Pass 1: the set of 32-bit unsigned integer type ids. */
    uint32_t uint_ty[8]; int n_uint_ty = 0;
    for (i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffffu;
        if (len == 0 || i + len > n) break;
        if (op == SPV_OP_FUNCTION) break;
        if (op == SPV_OP_TYPE_INT && len == 4 && w[i + 2] == 32 && w[i + 3] == 0
            && n_uint_ty < (int)(sizeof uint_ty / sizeof uint_ty[0]))
            uint_ty[n_uint_ty++] = w[i + 1];
        i += len;
    }
    if (!n_uint_ty) { *reason = "no_uint32_type"; return 0; }

    /* Pass 2: locate the two named constants and check their current value. */
    size_t at_lo = 0, at_hi = 0; int n_lo = 0, n_hi = 0;
    for (i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffffu;
        if (len == 0 || i + len > n) break;
        if (op == SPV_OP_FUNCTION) break;
        if (op == SPV_OP_CONSTANT && len == 4) {
            uint32_t rid = w[i + 2], ty = w[i + 1];
            int is_uint = 0;
            for (int k = 0; k < n_uint_ty; k++) if (uint_ty[k] == ty) is_uint = 1;
            if (is_uint && rid == lo_id) { at_lo = i + 3; n_lo++; }
            if (is_uint && rid == hi_id) { at_hi = i + 3; n_hi++; }
        }
        i += len;
    }
    if (n_lo != 1 || n_hi != 1) { *reason = "named_ids_are_not_uint_constants"; return 0; }
    if (w[at_lo] != CALLISTO_BDA_SENT_LO || w[at_hi] != CALLISTO_BDA_SENT_HI) {
        *reason = "constants_do_not_hold_the_sentinel";
        return 0;
    }
    w[at_lo] = (uint32_t)(addr & 0xffffffffu);
    w[at_hi] = (uint32_t)(addr >> 32);
    ids[0] = lo_id; ids[1] = hi_id;
    *reason = "ok";
    return 1;
}

/* Called from asj_note_build() for every TOP-LEVEL build whose device address
 * is known. Prefers a POPULATED TLAS: 98 section 13.4 measured TWO top-level
 * structures built in lockstep every frame, one of them permanently empty
 * (`instances_last:0` in every row), and a query against the empty one commits
 * nothing. Once a populated one has been seen, empty builds are ignored. */
static void bda_note_tlas(uint64_t addr, uint32_t prims, uint64_t frame) {
    DevData *d;
    int changed = 0;
    if (!addr) return;
    pthread_mutex_lock(&g_bda_mu);
    d = g_bda_dev;
    if (d && d->bda_map) {
        uint32_t flags = d->bda_map[BDA_W_FLAGS];
        if (prims > 0 || !(flags & 1u)) {
            uint32_t lo = (uint32_t)(addr & 0xffffffffu), hi = (uint32_t)(addr >> 32);
            changed = (d->bda_map[BDA_W_LO] != lo || d->bda_map[BDA_W_HI] != hi);
            if (changed) {
                d->bda_map[BDA_W_LO] = lo;
                d->bda_map[BDA_W_HI] = hi;
                d->bda_map[BDA_W_GEN] = d->bda_map[BDA_W_GEN] + 1;
                g_bda_tlas_changes++;
            }
            d->bda_map[BDA_W_PRIMS] = prims;
            d->bda_map[BDA_W_BUILDS] = d->bda_map[BDA_W_BUILDS] + 1;
            d->bda_map[BDA_W_FRAME] = (uint32_t)frame;
            if (prims > 0) d->bda_map[BDA_W_FLAGS] = flags | 1u;
            g_bda_tlas_addr = addr;
            g_bda_tlas_refreshes++;
        }
    }
    pthread_mutex_unlock(&g_bda_mu);
    if (changed)
        LOGF("\"ev\":\"bda_tlas\",\"addr\":\"0x%llx\",\"prims\":%u,"
             "\"frame\":%llu,\"changes\":%llu}",
             (unsigned long long)addr, prims, (unsigned long long)frame,
             (unsigned long long)g_bda_tlas_changes);
}

/* Read the scratch's shader-owned header back and log it. The layer never
 * writes those words after the allocation memset, so a non-zero value here is
 * a value a SHADER wrote -- which is the whole point of Stage 3a, and the
 * cheapest possible read-out (no screenshot, no A/B).
 *
 * Formally this needs a HOST_READ barrier the layer has nowhere to record
 * (see the section comment); a zero here is therefore "nothing seen", never
 * "the shader did not write". The shader-side read-back in the rungs is the
 * claim that does not depend on it. */
#define BDA_SCRATCH_SAMPLES 4096u
static void bda_scratch_report(const char *why) {
    DevData *d;
    uint32_t h[8] = {0}, words = 0, nz = 0, sampled = 0, slot_frame = 0;
    uint64_t refreshes = 0;
    int have = 0;
    pthread_mutex_lock(&g_bda_mu);
    d = g_bda_dev;
    if (d && d->bda_scratch_map && d->bda_scratch_words) {
        volatile const uint32_t *m = d->bda_scratch_map;
        uint32_t pay, stride, k;
        for (k = 0; k < 8; k++) h[k] = m[k];
        words = d->bda_scratch_words;
        /* A POPULATION COUNT over the payload, on the CPU, costing the shader
         * nothing. The rungs write one word per skin pixel and never touch
         * the header, so "how many of 4096 evenly spaced payload words are
         * non-zero" is the whole read-out: 0 means no shader has written,
         * and a number that grows with the skin on screen means one has. */
        pay = words > CALLISTO_SCRATCH_HDR ? words - CALLISTO_SCRATCH_HDR : 0;
        stride = pay / BDA_SCRATCH_SAMPLES;
        if (stride < 1) stride = 1;
        for (k = 0; k < pay && sampled < BDA_SCRATCH_SAMPLES; k += stride) {
            sampled++;
            if (m[CALLISTO_SCRATCH_HDR + k]) nz++;
        }
        slot_frame = d->bda_map ? d->bda_map[BDA_W_FRAME] : 0;
        refreshes = g_bda_tlas_refreshes;
        have = 1;
    }
    pthread_mutex_unlock(&g_bda_mu);
    if (!have) return;
    /* `slot_frame` vs `frame` is the whole diagnosis of 116 sec 8: the shader
     * reads slot word 6 at EXECUTE time, the layer writes it at RECORD time,
     * and a rung that compares against "frame - 1" is only right while those
     * two advance in lockstep. A slot_frame that stops moving, or moves in
     * steps other than 1 per present, says so here. */
    LOGF("\"ev\":\"bda_scratch_hdr\",\"why\":\"%s\",\"words\":%u,"
         "\"sampled\":%u,\"nonzero\":%u,\"slot_frame\":%u,\"frame\":%llu,"
         "\"tlas_refreshes\":%llu,"
         "\"w0\":%u,\"w1\":\"0x%08x\",\"w2\":\"0x%08x\",\"w3\":\"0x%08x\","
         "\"w4\":\"0x%08x\",\"w5\":\"0x%08x\",\"w6\":\"0x%08x\","
         "\"w7\":\"0x%08x\"}",
         why, words, sampled, nz, slot_frame, (unsigned long long)g_frame,
         (unsigned long long)refreshes,
         h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
}

/* Allocate, bind, map and address the slot. Every failure is soft: the layer
 * logs a reason, leaves d->bda_addr at 0, and a marker-carrying module is then
 * refused rather than served a garbage pointer. */
static void bda_setup(DevData *d, VkDevice dev, VkPhysicalDevice phys,
                      InstData *inst, int feature_on, int want_rt,
                      const char *decide) {
    const char *reason = "not_attempted";
    uint32_t mt = UINT32_MAX, chosen_flags = 0;
    if (g_bda_disabled)  { reason = "env_disabled";       goto out; }
    if (!feature_on)     { reason = "feature_not_enabled"; goto out; }
    /* Only the device that can hold a TLAS gets a slot. A dozen Proton helper
     * processes create devices through this layer and none of them has an
     * acceleration structure to point at, so they pay nothing. */
    if (!want_rt)        { reason = "not_an_rt_device";   goto out; }
    {
    PFN_vkCreateBuffer CreateBuffer = (PFN_vkCreateBuffer)
        d->gdpa(dev, "vkCreateBuffer");
    PFN_vkGetBufferMemoryRequirements GetReq = (PFN_vkGetBufferMemoryRequirements)
        d->gdpa(dev, "vkGetBufferMemoryRequirements");
    PFN_vkAllocateMemory Alloc = (PFN_vkAllocateMemory)
        d->gdpa(dev, "vkAllocateMemory");
    PFN_vkBindBufferMemory Bind = (PFN_vkBindBufferMemory)
        d->gdpa(dev, "vkBindBufferMemory");
    PFN_vkMapMemory Map = (PFN_vkMapMemory)d->gdpa(dev, "vkMapMemory");
    PFN_vkGetBufferDeviceAddress GetAddr = (PFN_vkGetBufferDeviceAddress)
        d->gdpa(dev, "vkGetBufferDeviceAddress");
    if (!GetAddr) GetAddr = (PFN_vkGetBufferDeviceAddress)
        d->gdpa(dev, "vkGetBufferDeviceAddressKHR");
    PFN_vkGetPhysicalDeviceMemoryProperties MemProps =
        inst ? inst->GetMemProps : NULL;
    d->DestroyBuffer = (PFN_vkDestroyBuffer)d->gdpa(dev, "vkDestroyBuffer");
    d->FreeMemory = (PFN_vkFreeMemory)d->gdpa(dev, "vkFreeMemory");
    d->UnmapMemory = (PFN_vkUnmapMemory)d->gdpa(dev, "vkUnmapMemory");
    if (!CreateBuffer || !GetReq || !Alloc || !Bind || !Map || !GetAddr
        || !MemProps) { reason = "entrypoint_missing"; goto out; }

    VkBufferCreateInfo bci = { VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
    bci.size = CALLISTO_BDA_WORDS * 4;
    bci.usage = VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT
              | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT
              | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (CreateBuffer(dev, &bci, NULL, &d->bda_buf) != VK_SUCCESS) {
        d->bda_buf = VK_NULL_HANDLE; reason = "create_buffer_failed"; goto out;
    }
    VkMemoryRequirements mr; GetReq(dev, d->bda_buf, &mr);
    VkPhysicalDeviceMemoryProperties mp; MemProps(phys, &mp);
    /* Prefer the BAR heap (DEVICE_LOCAL and HOST_VISIBLE at once) so the GPU
     * read is local; fall back to plain host-visible coherent. Both are
     * COHERENT on purpose -- a non-coherent choice would need an explicit
     * vkFlushMappedMemoryRanges the record-time write has no natural place
     * for. */
    const VkMemoryPropertyFlags need = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
                                     | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (int pass = 0; pass < 2 && mt == UINT32_MAX; pass++) {
        VkMemoryPropertyFlags want = need
            | (pass == 0 ? VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT : 0);
        for (uint32_t k = 0; k < mp.memoryTypeCount; k++)
            if ((mr.memoryTypeBits & (1u << k))
                && (mp.memoryTypes[k].propertyFlags & want) == want) {
                mt = k; chosen_flags = mp.memoryTypes[k].propertyFlags; break;
            }
    }
    if (mt == UINT32_MAX) { reason = "no_host_visible_memory_type"; goto out; }
    VkMemoryAllocateFlagsInfo mf = { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO };
    mf.flags = VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
    VkMemoryAllocateInfo mai = { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
    mai.pNext = &mf; mai.allocationSize = mr.size; mai.memoryTypeIndex = mt;
    if (Alloc(dev, &mai, NULL, &d->bda_mem) != VK_SUCCESS) {
        d->bda_mem = VK_NULL_HANDLE; reason = "allocate_failed"; goto out;
    }
    if (Bind(dev, d->bda_buf, d->bda_mem, 0) != VK_SUCCESS) {
        reason = "bind_failed"; goto out;
    }
    void *ptr = NULL;
    if (Map(dev, d->bda_mem, 0, VK_WHOLE_SIZE, 0, &ptr) != VK_SUCCESS || !ptr) {
        reason = "map_failed"; goto out;
    }
    d->bda_map = (volatile uint32_t *)ptr;
    for (uint32_t k = 0; k < CALLISTO_BDA_WORDS; k++) d->bda_map[k] = 0;
    d->bda_map[BDA_W_MAGIC] = CALLISTO_BDA_MAGIC;
    VkBufferDeviceAddressInfo bi = { VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO };
    bi.buffer = d->bda_buf;
    d->bda_addr = (uint64_t)GetAddr(dev, &bi);
    if (!d->bda_addr) { reason = "zero_device_address"; goto out; }
    reason = "armed";

    /* ---- Stage 3a: the scratch buffer, and its address into words 8-11.
     * Failures here are NOT failures of the slot: every earlier feature reads
     * words 0-7 only, so the scratch is allowed to be absent and says so in
     * word 10. Sizes step down because a BAR heap is small and a 128 MiB
     * host-visible-plus-device-local allocation is exactly the one a driver
     * refuses first; the host-visible fallback (pass 1 of the memory-type
     * loop) is system memory and will take it. */
    {
        const char *sreason = "disabled";
        uint32_t smt = UINT32_MAX, sflags_mem = 0, mb = g_bda_scratch_mb;
        uint32_t words = 0, sflags = 0;
        if (mb) {
            sreason = "not_attempted";
            for (; mb >= 1 && !d->bda_scratch_addr; mb /= 2) {
                VkBufferCreateInfo sbi = { VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
                VkMemoryRequirements smr;
                VkPhysicalDeviceMemoryProperties smp;
                VkMemoryAllocateFlagsInfo smf =
                    { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO };
                VkMemoryAllocateInfo smai =
                    { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
                VkBufferDeviceAddressInfo sai =
                    { VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO };
                void *sptr = NULL;
                sbi.size = (VkDeviceSize)mb << 20;
                sbi.usage = VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT
                          | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT
                          | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
                sbi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
                if (CreateBuffer(dev, &sbi, NULL, &d->bda_scratch_buf)
                    != VK_SUCCESS) {
                    d->bda_scratch_buf = VK_NULL_HANDLE;
                    sreason = "create_buffer_failed"; continue;
                }
                GetReq(dev, d->bda_scratch_buf, &smr);
                MemProps(phys, &smp);
                smt = UINT32_MAX;
                for (int pass = 0; pass < 2 && smt == UINT32_MAX; pass++) {
                    VkMemoryPropertyFlags want = need
                        | (pass == 0 ? VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT : 0);
                    for (uint32_t k = 0; k < smp.memoryTypeCount; k++)
                        if ((smr.memoryTypeBits & (1u << k))
                            && (smp.memoryTypes[k].propertyFlags & want) == want) {
                            smt = k;
                            sflags_mem = smp.memoryTypes[k].propertyFlags;
                            break;
                        }
                }
                if (smt == UINT32_MAX) { sreason = "no_host_visible_memory_type"; }
                else {
                    smf.flags = VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
                    smai.pNext = &smf;
                    smai.allocationSize = smr.size;
                    smai.memoryTypeIndex = smt;
                    if (Alloc(dev, &smai, NULL, &d->bda_scratch_mem) != VK_SUCCESS) {
                        d->bda_scratch_mem = VK_NULL_HANDLE;
                        sreason = "allocate_failed";
                    } else if (Bind(dev, d->bda_scratch_buf,
                                    d->bda_scratch_mem, 0) != VK_SUCCESS) {
                        sreason = "bind_failed";
                    } else if (Map(dev, d->bda_scratch_mem, 0, VK_WHOLE_SIZE, 0,
                                   &sptr) != VK_SUCCESS || !sptr) {
                        sreason = "map_failed";
                    } else {
                        sai.buffer = d->bda_scratch_buf;
                        d->bda_scratch_map = (volatile uint32_t *)sptr;
                        /* The one and only write the layer makes to the
                         * scratch: everything read out of it afterwards came
                         * from a shader. */
                        memset(sptr, 0, (size_t)sbi.size);
                        d->bda_scratch_addr = (uint64_t)GetAddr(dev, &sai);
                        if (!d->bda_scratch_addr) sreason = "zero_device_address";
                        else {
                            words = (uint32_t)(sbi.size / 4);
                            sflags = BDA_SCR_F_ARMED | BDA_SCR_F_READBACK;
                            sreason = "armed";
                        }
                    }
                }
                if (!d->bda_scratch_addr) {   /* step down and retry smaller */
                    if (d->bda_scratch_map) { d->UnmapMemory(dev, d->bda_scratch_mem);
                                              d->bda_scratch_map = NULL; }
                    if (d->bda_scratch_mem) { d->FreeMemory(dev, d->bda_scratch_mem, NULL);
                                              d->bda_scratch_mem = VK_NULL_HANDLE; }
                    if (d->bda_scratch_buf) { d->DestroyBuffer(dev, d->bda_scratch_buf, NULL);
                                              d->bda_scratch_buf = VK_NULL_HANDLE; }
                }
            }
        }
        d->bda_scratch_words = words;
        d->bda_map[BDA_W_SCR_LO] = (uint32_t)(d->bda_scratch_addr & 0xffffffffu);
        d->bda_map[BDA_W_SCR_HI] = (uint32_t)(d->bda_scratch_addr >> 32);
        d->bda_map[BDA_W_SCR_WORDS] = words;
        d->bda_map[BDA_W_SCR_FLAGS] = sflags;
        LOGF("\"ev\":\"bda_scratch\",\"action\":\"%s\",\"reason\":\"%s\","
             "\"addr\":\"0x%llx\",\"mb\":%u,\"words\":%u,\"hdr\":%u,"
             "\"mem_type\":%d,\"mem_flags\":%u,\"flags\":%u}",
             d->bda_scratch_addr ? "armed" : "skipped", sreason,
             (unsigned long long)d->bda_scratch_addr, words / (1u << 18),
             words, CALLISTO_SCRATCH_HDR,
             smt == UINT32_MAX ? -1 : (int)smt, (unsigned)sflags_mem, sflags);
    }
    pthread_mutex_lock(&g_bda_mu);
    if (g_bda_dev) g_bda_multi_dev++;
    else g_bda_dev = d;
    pthread_mutex_unlock(&g_bda_mu);
    }
out:
    LOGF("\"ev\":\"bda\",\"action\":\"%s\",\"reason\":\"%s\",\"decide\":\"%s\","
         "\"addr\":\"0x%llx\",\"magic\":\"0x%08x\",\"bytes\":%u,\"mem_type\":%d,"
         "\"mem_flags\":%u,\"second_device\":%d}",
         d->bda_addr ? "armed" : "skipped", reason, decide,
         (unsigned long long)d->bda_addr, CALLISTO_BDA_MAGIC,
         CALLISTO_BDA_WORDS * 4, mt == UINT32_MAX ? -1 : (int)mt,
         (unsigned)chosen_flags, g_bda_multi_dev);
}

static void bda_teardown(DevData *d, VkDevice dev) {
    if (!d) return;
    bda_scratch_report("device_destroy");
    pthread_mutex_lock(&g_bda_mu);
    if (g_bda_dev == d) g_bda_dev = NULL;
    d->bda_addr = 0;
    d->bda_map = NULL;
    pthread_mutex_unlock(&g_bda_mu);
    if (d->bda_mem && d->UnmapMemory) d->UnmapMemory(dev, d->bda_mem);
    if (d->bda_buf && d->DestroyBuffer) d->DestroyBuffer(dev, d->bda_buf, NULL);
    if (d->bda_mem && d->FreeMemory) d->FreeMemory(dev, d->bda_mem, NULL);
    d->bda_buf = VK_NULL_HANDLE; d->bda_mem = VK_NULL_HANDLE;
    if (d->bda_scratch_mem && d->UnmapMemory)
        d->UnmapMemory(dev, d->bda_scratch_mem);
    if (d->bda_scratch_buf && d->DestroyBuffer)
        d->DestroyBuffer(dev, d->bda_scratch_buf, NULL);
    if (d->bda_scratch_mem && d->FreeMemory)
        d->FreeMemory(dev, d->bda_scratch_mem, NULL);
    d->bda_scratch_buf = VK_NULL_HANDLE; d->bda_scratch_mem = VK_NULL_HANDLE;
    d->bda_scratch_map = NULL; d->bda_scratch_addr = 0; d->bda_scratch_words = 0;
    LOGF("\"ev\":\"bda_summary\",\"why\":\"device_destroy\",\"fixups\":%llu,"
         "\"tlas_refreshes\":%llu,\"tlas_changes\":%llu,\"last_tlas\":\"0x%llx\"}",
         (unsigned long long)g_bda_fixups,
         (unsigned long long)g_bda_tlas_refreshes,
         (unsigned long long)g_bda_tlas_changes,
         (unsigned long long)g_bda_tlas_addr);
}

/* ------------------------------------------------------------------ */
/* SER -- Shader Execution Reordering                                   */
/* ------------------------------------------------------------------ */
/* See the header comment. Two pieces:
 *
 *   ser_enable_setup()  decides whether to add
 *                       VK_NV_ray_tracing_invocation_reorder to a
 *                       VkDeviceCreateInfo, and builds the modified copy.
 *   spv_declares_ser()  says whether a swap file needs it, so a module is
 *                       never handed to a device that cannot take it.
 *
 * Note on vkEnumerateDeviceExtensionProperties: this layer deliberately does
 * NOT intercept the application-facing form of it, and does not need to. We
 * are not implementing an extension -- the NVIDIA ICD already advertises this
 * one, so vkd3d-proton's own queries already see it and would see it with or
 * without us. It simply never asks for it, because it has no SER to express.
 * Advertising it *harder* would buy nothing and could mislead a caller into
 * believing a translation path exists that does not. (The layer's exported
 * vkEnumerateDeviceExtensionProperties is only ever reached by the loader
 * with pLayerName == our own layer name, for our own -- empty -- list;
 * vkGetInstanceProcAddr does not hand the symbol out, so an app query falls
 * through to the next link in the chain untouched.)
 *
 * vkd3d-proton queries features independently, through
 * vkGetPhysicalDeviceFeatures2 with its own pNext chain, and never reads back
 * ppEnabledExtensionNames -- so appending to a copy of that array is
 * invisible to it. The one thing that would bite is a duplicate feature
 * struct in pNext, which is invalid usage, so the chain is walked first and
 * ours is not added if one is already there. */
#define CALLISTO_SER_EXT VK_NV_RAY_TRACING_INVOCATION_REORDER_EXTENSION_NAME
#define CALLISTO_RTPIPE_EXT VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME
/* VK_KHR_ray_query's own dependency is VK_KHR_acceleration_structure (plus
 * SPIR-V 1.4, which is core in the Vulkan 1.2+ device vkd3d-proton creates).
 * Enabling ours without it makes vkCreateDevice FAIL, and DXR is a setting
 * the player can switch off, so this is not hypothetical. */
#define CALLISTO_RAYQ_EXT VK_KHR_RAY_QUERY_EXTENSION_NAME
#define CALLISTO_ASTRUCT_EXT VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME

/* SPIR-V: Capability ShaderInvocationReorderNV. Not in vulkan_core.h -- it is
 * a SPIR-V enumerant, not a Vulkan one, so there is no header to include and
 * no compiler error if it is wrong. The value below was NOT taken from a spec
 * table; it was read out of an assembled module:
 *   spirv-as a raygen declaring the capability, then dump word[6] of the
 *   OpCapability run. It is 5383. An earlier build of this file had 5345,
 *   which compiled and ran and silently never matched -- the guard below was
 *   a no-op and would have served a SER module to a device without the
 *   extension. dev/patch_ser.sh --selftest is what caught it; keep that test
 *   working. */
#define SPV_CAP_SHADER_INVOCATION_REORDER_NV 5383u
/* SPIR-V: Capability RayQueryKHR. Same caveat as the SER enumerant above --
 * it is a SPIR-V value, not a Vulkan one, so nothing here would fail to
 * compile if it were wrong and the guard would silently never fire. 4472 was
 * read out of an assembled module the same way (spirv-as a shader declaring
 * OpCapability RayQueryKHR and dump the OpCapability operand);
 * dev/patch_rayq.sh --selftest re-proves it against the real driver, and
 * case B of that test is exactly the "the guard is dead" detector. */
#define SPV_CAP_RAY_QUERY_KHR 4472u
#define SPV_OP_CAPABILITY 17u

/* Does this module declare capability `cap`? Capabilities are the first
 * section after the 5-word header and are contiguous, so the scan stops at
 * the first instruction that is not OpCapability. */
static int spv_declares_cap(const uint32_t *w, size_t bytes, uint32_t cap) {
    size_t n = bytes / 4, i;
    if (!w || n < 5 || w[0] != 0x07230203) return 0;
    for (i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffffu;
        if (len == 0 || i + len > n) break;
        if (op != SPV_OP_CAPABILITY) break;
        if (len >= 2 && w[i + 1] == cap) return 1;
        i += len;
    }
    return 0;
}
static int spv_declares_ser(const uint32_t *w, size_t bytes) {
    return spv_declares_cap(w, bytes, SPV_CAP_SHADER_INVOCATION_REORDER_NV);
}
static int spv_declares_rayq(const uint32_t *w, size_t bytes) {
    return spv_declares_cap(w, bytes, SPV_CAP_RAY_QUERY_KHR);
}

static int names_have(const char *const *names, uint32_t n, const char *want) {
    for (uint32_t i = 0; i < n; i++)
        if (names[i] && !strcmp(names[i], want)) return 1;
    return 0;
}

/* Decide, per extension, whether to ASK for it. Nothing is built here --
 * SER and the ray query both want to append a name and prepend a feature
 * struct, and each used to build its own copy of the VkDeviceCreateInfo, so
 * the second copy would have thrown the first away. They are decided
 * separately and assembled once, below.
 *
 * *reason is always set to a short token for the log. `already` is 1 when the
 * application enabled the extension itself, which is `enabled` as far as
 * serving a module is concerned -- 44-LOW-HANGING-FRUIT: treating our own
 * no-op as "off" made the layer reject every SER swap on the one device that
 * had the extension. */
typedef struct { int want, already; const char *reason; } ExtWant;

static void ext_decide(InstData *inst, VkPhysicalDevice phys,
        const VkDeviceCreateInfo *ci, const char *ext, const char *dep,
        VkStructureType feat_stype, int env_disabled, ExtWant *w) {
    w->want = 0; w->already = 0; w->reason = "not_attempted";
    if (env_disabled)               { w->reason = "env_disabled";  return; }
    if (!inst || !inst->EnumDevExt) { w->reason = "no_enum_fn";    return; }

    const char *const *names = ci->ppEnabledExtensionNames;
    uint32_t n = ci->enabledExtensionCount;
    if (n && !names)                { w->reason = "bad_ext_array"; return; }
    if (names_have(names, n, ext)) {
        w->already = 1;
        w->reason = "already_enabled_no_feature_struct";
        for (const VkBaseInStructure *p = ci->pNext; p; p = p->pNext)
            if (p->sType == feat_stype) {
                /* The first member of every VkPhysicalDevice*FeaturesKHR/NV
                 * used here is the single VkBool32 we care about, right after
                 * sType+pNext. Both structs this layer chains have that
                 * layout, and both are checked at compile time below. */
                const VkBool32 *on = (const VkBool32 *)((const char *)p
                        + sizeof(VkBaseInStructure));
                w->reason = *on ? "already_enabled_feature_on"
                                : "already_enabled_feature_off";
                return;
            }
        return;
    }
    if (!names_have(names, n, dep))  { w->reason = "missing_dependency"; return; }

    /* Ask the driver, do not assume. */
    uint32_t cnt = 0;
    if (inst->EnumDevExt(phys, NULL, &cnt, NULL) != VK_SUCCESS || !cnt) {
        w->reason = "enum_failed";
        return;
    }
    VkExtensionProperties *props = calloc(cnt, sizeof *props);
    if (!props)                      { w->reason = "oom";          return; }
    int have = 0;
    if (inst->EnumDevExt(phys, NULL, &cnt, props) == VK_SUCCESS)
        for (uint32_t i = 0; i < cnt && !have; i++)
            if (!strcmp(props[i].extensionName, ext)) have = 1;
    free(props);
    if (!have)                       { w->reason = "unsupported";  return; }

    /* A duplicate sType in a pNext chain is invalid usage. If the app already
     * chained the feature struct (it does not today, but a future
     * vkd3d-proton might), leave the chain alone and let it speak. */
    for (const VkBaseInStructure *p = ci->pNext; p; p = p->pNext)
        if (p->sType == feat_stype) {
            w->reason = "feature_already_chained";
            return;
        }
    w->want = 1;
    w->reason = "enabled";
}

/* bufferDeviceAddress is a FEATURE, not just an extension name, and on this
 * app it is almost certainly already on: VK_KHR_acceleration_structure
 * requires it, and vkd3d-proton enables the acceleration-structure extension
 * on every RT device. So the decision is DETECT FIRST, enable only as a
 * fallback -- and the one thing that must never happen is chaining
 * VkPhysicalDeviceBufferDeviceAddressFeatures next to a
 * VkPhysicalDeviceVulkan12Features, which is invalid usage
 * (VUID-VkDeviceCreateInfo-pNext-02829/02830) and would fail device creation
 * for the whole game. When a Vulkan12Features is present with the feature OFF
 * the layer stands down and says so, rather than "fixing" it. */
#define BDA_STYPE_VK12   VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES
#define BDA_STYPE_BDAF   VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_BUFFER_DEVICE_ADDRESS_FEATURES
#define CALLISTO_BDA_EXT VK_KHR_BUFFER_DEVICE_ADDRESS_EXTENSION_NAME

static void bda_decide(InstData *inst, VkPhysicalDevice phys,
                       const VkDeviceCreateInfo *ci, ExtWant *w) {
    w->want = 0; w->already = 0; w->reason = "not_attempted";
    if (g_bda_disabled) { w->reason = "env_disabled"; return; }
    for (const VkBaseInStructure *p = ci->pNext; p; p = p->pNext) {
        if (p->sType == BDA_STYPE_VK12) {
            const VkPhysicalDeviceVulkan12Features *f =
                (const VkPhysicalDeviceVulkan12Features *)p;
            w->already = f->bufferDeviceAddress ? 1 : 0;
            w->reason = f->bufferDeviceAddress ? "already_enabled_vk12"
                                               : "vk12_features_chained_off";
            return;                      /* cannot chain ours next to it */
        }
        if (p->sType == BDA_STYPE_BDAF) {
            const VkPhysicalDeviceBufferDeviceAddressFeatures *f =
                (const VkPhysicalDeviceBufferDeviceAddressFeatures *)p;
            w->already = f->bufferDeviceAddress ? 1 : 0;
            w->reason = f->bufferDeviceAddress ? "already_enabled_feature_struct"
                                               : "feature_already_chained_off";
            return;
        }
    }
    if (!inst || !inst->EnumDevExt) { w->reason = "no_enum_fn"; return; }
    uint32_t cnt = 0;
    if (inst->EnumDevExt(phys, NULL, &cnt, NULL) != VK_SUCCESS || !cnt) {
        w->reason = "enum_failed"; return;
    }
    VkExtensionProperties *props = calloc(cnt, sizeof *props);
    if (!props) { w->reason = "oom"; return; }
    int have = 0;
    if (inst->EnumDevExt(phys, NULL, &cnt, props) == VK_SUCCESS)
        for (uint32_t i = 0; i < cnt && !have; i++)
            if (!strcmp(props[i].extensionName, CALLISTO_BDA_EXT)) have = 1;
    free(props);
    if (!have) { w->reason = "unsupported"; return; }
    w->want = 1;
    w->reason = "enabled";
}

_Static_assert(offsetof(VkPhysicalDeviceBufferDeviceAddressFeatures,
                        bufferDeviceAddress) == sizeof(VkBaseInStructure),
               "VkPhysicalDeviceBufferDeviceAddressFeatures layout changed");

/* The compile-time half of ext_decide()'s "first VkBool32 after sType+pNext"
 * assumption. If a header ever reorders these, this stops the build instead
 * of silently misreading the app's feature struct. */
_Static_assert(offsetof(VkPhysicalDeviceRayQueryFeaturesKHR, rayQuery)
               == sizeof(VkBaseInStructure),
               "VkPhysicalDeviceRayQueryFeaturesKHR layout changed");
_Static_assert(offsetof(VkPhysicalDeviceRayTracingInvocationReorderFeaturesNV,
                        rayTracingInvocationReorder)
               == sizeof(VkBaseInStructure),
               "VkPhysicalDeviceRayTracingInvocationReorderFeaturesNV layout changed");

/* ------------------------------------------------------------------ */
/* instance / device creation (loader chain advance)                   */
/* ------------------------------------------------------------------ */
static VkResult VKAPI_CALL xCreateInstance(const VkInstanceCreateInfo *ci,
        const VkAllocationCallbacks *ac, VkInstance *pInst) {
    const VkLayerInstanceCreateInfo *lc = ci->pNext;
    while (lc && !(lc->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO &&
                   lc->function == VK_LAYER_LINK_INFO))
        lc = lc->pNext;
    if (!lc) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr next_gipa = lc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkCreateInstance next_create = (PFN_vkCreateInstance)
        next_gipa(NULL, "vkCreateInstance");
    VkLayerInstanceCreateInfo save = *lc;
    ((VkLayerInstanceCreateInfo *)lc)->u.pLayerInfo = lc->u.pLayerInfo->pNext;
    VkResult r = next_create(ci, ac, pInst);
    ((VkLayerInstanceCreateInfo *)lc)->u.pLayerInfo = save.u.pLayerInfo;
    if (r != VK_SUCCESS) return r;

    InstData *d = add_inst(*pInst);
    if (!d) {
        LOGF("\"ev\":\"table_full\",\"what\":\"instance\",\"max\":%d}", MAX_OBJ);
        return r;                       /* untracked: gipa falls through */
    }
    d->gipa = next_gipa;
    d->CreateDevice = (PFN_vkCreateDevice)next_gipa(*pInst, "vkCreateDevice");
    d->DestroyInstance = (PFN_vkDestroyInstance)next_gipa(*pInst, "vkDestroyInstance");
    d->EnumDevExt = (PFN_vkEnumerateDeviceExtensionProperties)
        next_gipa(*pInst, "vkEnumerateDeviceExtensionProperties");
    d->GetMemProps = (PFN_vkGetPhysicalDeviceMemoryProperties)
        next_gipa(*pInst, "vkGetPhysicalDeviceMemoryProperties");
    LOGF("\"ev\":\"vkCreateInstance\",\"inst\":\"%p\"}", (void *)*pInst);
    return r;
}

static VkResult VKAPI_CALL xCreateDevice(VkPhysicalDevice phys,
        const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *ac, VkDevice *pDev) {
    const VkLayerDeviceCreateInfo *lc = ci->pNext;
    while (lc && !(lc->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO &&
                   lc->function == VK_LAYER_LINK_INFO))
        lc = lc->pNext;
    if (!lc) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr next_gipa = lc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr next_gdpa = lc->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    /* A VkPhysicalDevice shares its parent instance's dispatch key, so this
     * finds the right instance even with several live. */
    InstData *id = find_inst((VkInstance)phys);
    PFN_vkCreateDevice next_create = id ? id->CreateDevice : NULL;
    if (!next_create) next_create = (PFN_vkCreateDevice)
        next_gipa(VK_NULL_HANDLE, "vkCreateDevice");
    if (!next_create) return VK_ERROR_INITIALIZATION_FAILED;
    /* ---- Ask for VK_NV_ray_tracing_invocation_reorder (SER, handoff/41)
     * and VK_KHR_ray_query (handoff/98) on the app's behalf. Everything here
     * is conditional and reversible: on any failure the call is retried with
     * strictly less added, and finally with exactly what the caller passed,
     * so this can never be the reason the game does not start.
     *
     * Backward compatibility is explicit rather than assumed: if adding both
     * fails, the SER-only create -- the one every launch before handoff/98
     * made -- is retried before giving up. A launch that uses no ray query is
     * bit-for-bit the old behaviour. */
    ExtWant ws, wq, wb;
    ext_decide(id, phys, ci, CALLISTO_SER_EXT, CALLISTO_RTPIPE_EXT,
               VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_TRACING_INVOCATION_REORDER_FEATURES_NV,
               g_ser_disabled, &ws);
    ext_decide(id, phys, ci, CALLISTO_RAYQ_EXT, CALLISTO_ASTRUCT_EXT,
               VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_QUERY_FEATURES_KHR,
               g_rayq_disabled, &wq);
    bda_decide(id, phys, ci, &wb);

    VkPhysicalDeviceRayTracingInvocationReorderFeaturesNV serfeat = {
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_TRACING_INVOCATION_REORDER_FEATURES_NV,
        NULL, VK_TRUE };
    VkPhysicalDeviceRayQueryFeaturesKHR rqfeat = {
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_QUERY_FEATURES_KHR, NULL, VK_TRUE };
    VkPhysicalDeviceBufferDeviceAddressFeatures bdafeat = {
        BDA_STYPE_BDAF, NULL, VK_TRUE, VK_FALSE, VK_FALSE };
    const char **exts = NULL;
    VkDeviceCreateInfo ci2;
    int ser_on = 0, rayq_on = 0, bda_on = 0;

    /* build(want_ser, want_rayq, want_bda) -> ci2 */
    uint32_t n0 = ci->enabledExtensionCount;
    int nadd = ws.want + wq.want + wb.want;
    if (nadd) {
        exts = malloc((size_t)(n0 + 3) * sizeof *exts);
        if (!exts) {
            nadd = 0; ws.want = wq.want = wb.want = 0; ws.reason = "oom";
        }
    }

    VkLayerDeviceCreateInfo save = *lc;
    ((VkLayerDeviceCreateInfo *)lc)->u.pLayerInfo = lc->u.pLayerInfo->pNext;

    VkResult r;
    int try_ser = ws.want, try_rayq = wq.want, try_bda = wb.want;
    for (;;) {
        if (!try_ser && !try_rayq && !try_bda) {
            r = next_create(phys, ci, ac, pDev); break;
        }
        uint32_t k = 0;
        for (uint32_t i = 0; i < n0; i++) exts[k++] = ci->ppEnabledExtensionNames[i];
        if (try_ser)  exts[k++] = CALLISTO_SER_EXT;
        if (try_rayq) exts[k++] = CALLISTO_RAYQ_EXT;
        if (try_bda)  exts[k++] = CALLISTO_BDA_EXT;
        /* Prepending keeps every node the caller built -- including the
         * loader's own VkLayerDeviceCreateInfo, whose pLayerInfo is advanced
         * and restored by pointer around this loop. Nothing is copied but
         * the head. */
        const void *head = ci->pNext;
        if (try_ser)  { serfeat.pNext = (void *)(uintptr_t)head; head = &serfeat; }
        if (try_rayq) { rqfeat.pNext  = (void *)(uintptr_t)head; head = &rqfeat; }
        if (try_bda)  { bdafeat.pNext = (void *)(uintptr_t)head; head = &bdafeat; }
        ci2 = *ci;
        ci2.pNext = head;
        ci2.enabledExtensionCount = k;
        ci2.ppEnabledExtensionNames = exts;
        r = next_create(phys, &ci2, ac, pDev);
        if (r == VK_SUCCESS) {
            ser_on = try_ser; rayq_on = try_rayq; bda_on = try_bda; break;
        }
        LOGF("\"ev\":\"devext\",\"action\":\"fallback\",\"result\":%d,"
             "\"tried_ser\":%d,\"tried_rayq\":%d,\"tried_bda\":%d}",
             (int)r, try_ser, try_rayq, try_bda);
        /* Drop the NEWEST request first, so a launch that uses none of this
         * degrades to exactly the behaviour of the build before it. */
        if (try_bda)  { try_bda = 0;  wb.reason = "create_failed"; continue; }
        if (try_rayq) { try_rayq = 0; wq.reason = "create_failed"; continue; }
        try_ser = 0; ws.reason = "create_failed";
    }
    ((VkLayerDeviceCreateInfo *)lc)->u.pLayerInfo = save.u.pLayerInfo;
    free(exts);
    if (ws.already && r == VK_SUCCESS) ser_on = 1;
    if (wq.already && r == VK_SUCCESS) rayq_on = 1;
    if (wb.already && r == VK_SUCCESS) bda_on = 1;
    LOGF("\"ev\":\"ser\",\"action\":\"%s\",\"reason\":\"%s\","
         "\"ext\":\"%s\",\"app_exts\":%u,\"result\":%d}",
         ser_on ? "enabled" : "skipped", ws.reason, CALLISTO_SER_EXT,
         ci->enabledExtensionCount, (int)r);
    LOGF("\"ev\":\"rayq\",\"action\":\"%s\",\"reason\":\"%s\","
         "\"ext\":\"%s\",\"app_exts\":%u,\"result\":%d}",
         rayq_on ? "enabled" : "skipped", wq.reason, CALLISTO_RAYQ_EXT,
         ci->enabledExtensionCount, (int)r);
    if (r != VK_SUCCESS) return r;

    VkDevice dev = *pDev;
    DevData *d = add_dev(dev);
    if (!d) {
        /* Untracked: gdpa falls through, and xCreateShaderModule's SER guard
         * reads a NULL DevData as "no SER on this device", so a SER-carrying
         * swap is refused rather than handed to a device we cannot vouch for. */
        LOGF("\"ev\":\"table_full\",\"what\":\"device\",\"max\":%d}", MAX_OBJ);
        return r;
    }
    d->gdpa = next_gdpa;
    d->ser = ser_on;
    d->rayq = rayq_on;
    d->DestroyDevice = (PFN_vkDestroyDevice)d->gdpa(dev, "vkDestroyDevice");
    d->CreateShaderModule = (PFN_vkCreateShaderModule)d->gdpa(dev, "vkCreateShaderModule");
    d->DestroyShaderModule = (PFN_vkDestroyShaderModule)d->gdpa(dev, "vkDestroyShaderModule");
    d->DestroyPipeline = (PFN_vkDestroyPipeline)d->gdpa(dev, "vkDestroyPipeline");
    d->CreateRTPipelines = (PFN_vkCreateRayTracingPipelinesKHR)
        d->gdpa(dev, "vkCreateRayTracingPipelinesKHR");
    d->CreateComputePipelines = (PFN_vkCreateComputePipelines)
        d->gdpa(dev, "vkCreateComputePipelines");
    /* BDA slot (handoff/103, Stage 2b). After gdpa is live and before any
     * shader module can be created on this device. */
    bda_setup(d, dev, phys, id, bda_on,
              names_have(ci->ppEnabledExtensionNames, ci->enabledExtensionCount,
                         CALLISTO_ASTRUCT_EXT),
              wb.reason);
    /* Command-buffer hooks are keyed by device-independent globals: the game
     * uses one VkDevice, so first resolution wins. */
    if (!g_next_bind)
        g_next_bind = (PFN_vkCmdBindPipeline)d->gdpa(dev, "vkCmdBindPipeline");
    if (!g_next_dispatch)
        g_next_dispatch = (PFN_vkCmdDispatch)d->gdpa(dev, "vkCmdDispatch");
    if (!g_next_dispatch_ind)
        g_next_dispatch_ind = (PFN_vkCmdDispatchIndirect)
            d->gdpa(dev, "vkCmdDispatchIndirect");
    if (!g_next_trace)
        g_next_trace = (PFN_vkCmdTraceRaysKHR)d->gdpa(dev, "vkCmdTraceRaysKHR");
    if (!g_next_trace_ind)
        g_next_trace_ind = (PFN_vkCmdTraceRaysIndirectKHR)
            d->gdpa(dev, "vkCmdTraceRaysIndirectKHR");
    if (!g_next_trace_ind2)
        g_next_trace_ind2 = (PFN_vkCmdTraceRaysIndirect2KHR)
            d->gdpa(dev, "vkCmdTraceRaysIndirect2KHR");
    /* AS journal. gdpa returns NULL when VK_KHR_acceleration_structure is not
     * enabled on this device, and the hooks below are only exposed when the
     * pointer resolved -- so a non-RT device (every Proton helper) pays
     * nothing, and CALLISTO_ASJOURNAL_DISABLE=1 skips resolution entirely. */
    if (!g_asj_disabled) {
        d->CreateAS = (PFN_vkCreateAccelerationStructureKHR)
            d->gdpa(dev, "vkCreateAccelerationStructureKHR");
        d->GetASAddr = (PFN_vkGetAccelerationStructureDeviceAddressKHR)
            d->gdpa(dev, "vkGetAccelerationStructureDeviceAddressKHR");
        if (!g_next_build_as)
            g_next_build_as = (PFN_vkCmdBuildAccelerationStructuresKHR)
                d->gdpa(dev, "vkCmdBuildAccelerationStructuresKHR");
        if (!g_next_present)
            g_next_present = (PFN_vkQueuePresentKHR)
                d->gdpa(dev, "vkQueuePresentKHR");
        if (!g_next_submit)
            g_next_submit = (PFN_vkQueueSubmit)d->gdpa(dev, "vkQueueSubmit");
        LOGF("\"ev\":\"asjournal\",\"action\":\"%s\",\"create\":%d,"
             "\"addr\":%d,\"build\":%d,\"present\":%d,\"submit\":%d}",
             (d->CreateAS || d->GetASAddr) ? "armed" : "unavailable",
             d->CreateAS ? 1 : 0, d->GetASAddr ? 1 : 0, g_next_build_as ? 1 : 0,
             g_next_present ? 1 : 0, g_next_submit ? 1 : 0);
    }
    LOGF("\"ev\":\"vkCreateDevice\",\"dev\":\"%p\"}", (void *)dev);
    return r;
}

/* ------------------------------------------------------------------ */
/* the swap                                                            */
/* ------------------------------------------------------------------ */
static VkResult VKAPI_CALL xCreateShaderModule(VkDevice dev,
        const VkShaderModuleCreateInfo *ci, const VkAllocationCallbacks *ac,
        VkShaderModule *pMod) {
    /* An untracked device must degrade to passthrough, never to a hard
     * failure: a tracking gap would otherwise break the application. */
    DevData *d = find_dev(dev);
    PFN_vkCreateShaderModule next = d ? d->CreateShaderModule : NULL;
    if (!next) {
        static int warned;
        if (!__sync_fetch_and_add(&warned, 1))
            LOGF("\"ev\":\"untracked_device\",\"dev\":\"%p\"}", (void *)dev);
        for (int k = 0; k < g_ninst && !next; k++)
            if (g_inst[k].gipa)
                next = (PFN_vkCreateShaderModule)
                    g_inst[k].gipa(VK_NULL_HANDLE, "vkCreateShaderModule");
        if (!next) return VK_ERROR_INITIALIZATION_FAILED;
        return next(dev, ci, ac, pMod);
    }

    char id[96] = {0}, dxil[17] = {0};
    int has_id = scan_dxil_id(ci->pCode, ci->codeSize, id, dxil);
    /* The sha256 is only a secondary key (the sha256-<hex>.spv fallback) and
     * a log field. Hashing every one of ~3300 modules per launch is wasted
     * when the id matched and the log is quiet, so it is computed on demand. */
    char sha[65]; int have_sha = 0;
#define SHA() (have_sha ? sha : (have_sha = 1, sha256(ci->pCode, ci->codeSize, sha), sha))

    /* CALLISTO_DUMP_DIR: write the INCOMING SPIR-V for every module whose id
     * contains CALLISTO_DUMP_MATCH (default: all). The live game builds many
     * more shader permutations than any single capture contains -- e.g. 12
     * distinct rgs_reference_main libraries -- so patching only the two from
     * the capture silently misses whichever one is actually dispatched.
     * This is how the rest get their SPIR-V for the patcher. */
    if (g_dump_dir) {
        const char *want = getenv("CALLISTO_DUMP_MATCH");
        if (!want || (has_id && strstr(id, want))) {
            char path[1024];
            snprintf(path, sizeof path, "%s/%s.spv", g_dump_dir,
                     has_id ? id : SHA());
            /* Same module is created repeatedly; first write wins. */
            if (access(path, F_OK) != 0) {
                FILE *df = fopen(path, "wb");
                if (df) {
                    fwrite(ci->pCode, 1, ci->codeSize, df);
                    fclose(df);
                    LOGF("\"ev\":\"dump\",\"id\":\"%s\",\"sha256\":\"%s\","
                         "\"size\":%zu,\"path\":\"%s\"}",
                         has_id ? id : "", SHA(), ci->codeSize, path);
                }
            }
        }
    }

    if (g_disabled) {
        if (!g_quiet)
            LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"disabled\"}",
                 ci->codeSize, has_id ? id : "", SHA());
        VkResult r = next(dev, ci, ac, pMod);
        if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 0);
        return r;
    }

    uint32_t *code = NULL; size_t size = 0;
    if (has_id) code = load_swap(id, &size, d->ser, d->rayq, d->bda_addr);
    if (!code) {
        char name[80];
        snprintf(name, sizeof name, "sha256-%s", SHA());
        code = load_swap(name, &size, d->ser, d->rayq, d->bda_addr);
    }

    /* SER: a swap that declares ShaderInvocationReorderNV is only legal on a
     * device where we managed to enable the extension. Serving it anyway does
     * not fail here -- it fails later, inside
     * vkCreateRayTracingPipelinesKHR, as a black screen with no obvious
     * cause. Refuse it loudly instead and let the vanilla module through, so
     * the worst case of a mismatched swaps.ser/ is "SER did nothing" (which
     * is A1's expected failure mode anyway) rather than "the game is broken".
     * `d->ser` is 0 for an untracked device, which is the right default. */
    if (code && spv_declares_ser(code, size) && !d->ser) {
        /* Unreachable since load_swap() filters per overlay; kept as the
         * last line of defence for the base dir. */
        LOGF("\"ev\":\"ser_reject\",\"id\":\"%s\",\"size\":%zu,"
             "\"reason\":\"device_extension_not_enabled\",\"action\":\"vanilla\"}",
             has_id ? id : "", size);
        free(code);
        code = NULL;
    }
    /* Same rule, same reason, for capability RayQueryKHR (handoff/98). Also
     * unreachable for overlays; the base dir has no ray-query module today
     * and this is what keeps that true safely. */
    if (code && spv_declares_rayq(code, size) && !d->rayq) {
        LOGF("\"ev\":\"rayq_reject\",\"id\":\"%s\",\"size\":%zu,"
             "\"reason\":\"device_extension_not_enabled\",\"action\":\"vanilla\"}",
             has_id ? id : "", size);
        free(code);
        code = NULL;
    }
    /* The BDA marker needs no guard HERE: load_swap() is the single site that
     * both checks and REWRITES it, for the overlays and for the base dir
     * alike, and the rewrite is destructive -- a second pass would refuse a
     * module it had already fixed. See load_swap(). */

    if (!code) {
        if (!g_quiet)
            LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"none\"}",
                 ci->codeSize, has_id ? id : "", SHA());
        VkResult r = next(dev, ci, ac, pMod);
        if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 0);
        return r;
    }

    VkShaderModuleCreateInfo sub = *ci;
    sub.pCode = code; sub.codeSize = size;
    VkResult r = next(dev, &sub, ac, pMod);
    LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"%s\",\"result\":%d}",
         ci->codeSize, has_id ? id : "", SHA(),
         r == VK_SUCCESS ? "HIT" : "hit_failed", (int)r);
    if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 1);
    status_hit(has_id ? id : "", r == VK_SUCCESS);
    free(code);
    return r;
#undef SHA
}

static void VKAPI_CALL xDestroyShaderModule(VkDevice dev, VkShaderModule mod,
        const VkAllocationCallbacks *ac) {
    DevData *d = find_dev(dev);
    PFN_vkDestroyShaderModule next = d ? d->DestroyShaderModule : NULL;
    modid_del((uint64_t)mod);
    if (next) next(dev, mod, ac);
}

static void VKAPI_CALL xDestroyPipeline(VkDevice dev, VkPipeline pipe,
        const VkAllocationCallbacks *ac) {
    DevData *d = find_dev(dev);
    PFN_vkDestroyPipeline next = d ? d->DestroyPipeline : NULL;
    rtpipe_del((uint64_t)pipe);   /* handles get reused -- drop stale raygen + trace dedup */
    if (next) next(dev, pipe, ac);
}

/* Log which raygen module each RT pipeline is built from. This runs at
 * pipeline-build time; it narrows the suspect set but still does not prove
 * dispatch -- that is what the trace_rays hook below is for. */
static VkResult VKAPI_CALL xCreateRayTracingPipelinesKHR(VkDevice dev,
        VkDeferredOperationKHR dop, VkPipelineCache cache, uint32_t count,
        const VkRayTracingPipelineCreateInfoKHR *infos,
        const VkAllocationCallbacks *ac, VkPipeline *pPipes) {
    DevData *d = find_dev(dev);
    PFN_vkCreateRayTracingPipelinesKHR next = d ? d->CreateRTPipelines : NULL;
    if (!next) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = next(dev, dop, cache, count, infos, ac, pPipes);
    if (r != VK_SUCCESS && r != VK_PIPELINE_COMPILE_REQUIRED) {
        /* Used to return silently. A swap that the driver rejects fails
         * HERE, not at module creation, so without this line the only symptom
         * of a bad splice is a missing effect -- indistinguishable from a
         * splice that ran and did nothing, which is exactly A1's own null
         * result. Name the raygen so the log says which one. */
        const char *bad = "";
        if (count && infos) {
            for (uint32_t s2 = 0; s2 < infos[0].stageCount; s2++)
                if (infos[0].pStages[s2].stage == VK_SHADER_STAGE_RAYGEN_BIT_KHR) {
                    pthread_mutex_lock(&g_id_mu);
                    int mi = modid_find((uint64_t)infos[0].pStages[s2].module);
                    if (mi >= 0 && mi < g_nmodid) bad = g_modid[mi].id;
                    pthread_mutex_unlock(&g_id_mu);
                    break;
                }
        }
        LOGF("\"ev\":\"rt_pipeline_failed\",\"result\":%d,\"count\":%u,"
             "\"first_rgs\":\"%s\"}", (int)r, count, bad);
        return r;
    }

    for (uint32_t i = 0; i < count; i++) {
        int rgs = -1;
        const char *rgs_name = "";
        for (uint32_t s = 0; s < infos[i].stageCount; s++) {
            const VkPipelineShaderStageCreateInfo *st = &infos[i].pStages[s];
            if (st->stage == VK_SHADER_STAGE_RAYGEN_BIT_KHR) {
                if (st->pName) rgs_name = st->pName;
                pthread_mutex_lock(&g_id_mu);
                rgs = modid_find((uint64_t)st->module);
                pthread_mutex_unlock(&g_id_mu);
                break;
            }
        }
        /* Pipeline libraries: the raygen may come from a linked library
         * rather than an inline stage -- inherit it. */
        if (rgs < 0 && infos[i].pLibraryInfo) {
            pthread_mutex_lock(&g_id_mu);
            for (uint32_t l = 0; l < infos[i].pLibraryInfo->libraryCount && rgs < 0; l++) {
                int li = rtpipe_find((uint64_t)infos[i].pLibraryInfo->pLibraries[l]);
                if (li >= 0) rgs = g_rtpipe[li].rgs;
            }
            pthread_mutex_unlock(&g_id_mu);
        }
        const char *id = ""; int sw = -1;
        if (rgs >= 0) {
            pthread_mutex_lock(&g_id_mu);
            if (rgs < g_nmodid) { id = g_modid[rgs].id; sw = g_modid[rgs].swapped; }
            pthread_mutex_unlock(&g_id_mu);
        }
        uint64_t ph = pPipes ? (uint64_t)pPipes[i] : 0;
        if (ph) rtpipe_set(ph, rgs);
        LOGF("\"ev\":\"rt_pipeline\",\"pipe\":\"0x%llx\",\"rgs\":\"%s\",\"entry\":\"%s\",\"swapped\":%d}",
             (unsigned long long)ph, id, rgs_name, sw);

        /* Full stage composition. trace_rays can only ever name the RAYGEN of
         * a dispatched pipeline, but in a deferred path tracer the raygen is a
         * thin tracer and the shading lives in the closest-hit shader reached
         * through the SBT -- invisible to every hook we had. Logging every
         * stage lets a traced pipeline handle be joined to its hit shaders, so
         * "which shader actually shades a PT frame" becomes a lookup instead
         * of a guess. */
        for (uint32_t s = 0; s < infos[i].stageCount; s++) {
            const VkPipelineShaderStageCreateInfo *st = &infos[i].pStages[s];
            const char *kind;
            switch (st->stage) {
            case VK_SHADER_STAGE_RAYGEN_BIT_KHR:       kind = "rgen";  break;
            case VK_SHADER_STAGE_CLOSEST_HIT_BIT_KHR:  kind = "chit";  break;
            case VK_SHADER_STAGE_ANY_HIT_BIT_KHR:      kind = "ahit";  break;
            case VK_SHADER_STAGE_MISS_BIT_KHR:         kind = "miss";  break;
            case VK_SHADER_STAGE_INTERSECTION_BIT_KHR: kind = "isect"; break;
            case VK_SHADER_STAGE_CALLABLE_BIT_KHR:     kind = "call";  break;
            default:                                   kind = "other"; break;
            }
            const char *sid = ""; int ssw = -1;
            pthread_mutex_lock(&g_id_mu);
            int mi = modid_find((uint64_t)st->module);
            if (mi >= 0 && mi < g_nmodid) { sid = g_modid[mi].id; ssw = g_modid[mi].swapped; }
            pthread_mutex_unlock(&g_id_mu);
            LOGF("\"ev\":\"pipe_stage\",\"pipe\":\"0x%llx\",\"kind\":\"%s\","
                 "\"id\":\"%s\",\"entry\":\"%s\",\"swapped\":%d}",
                 (unsigned long long)ph, kind, sid,
                 st->pName ? st->pName : "", ssw);
        }
    }
    return r;
}

static VkResult VKAPI_CALL xCreateComputePipelines(VkDevice dev,
        VkPipelineCache cache, uint32_t n,
        const VkComputePipelineCreateInfo *infos,
        const VkAllocationCallbacks *ac, VkPipeline *pipes) {
    DevData *d = find_dev(dev);
    if (!d || !d->CreateComputePipelines)
        return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = d->CreateComputePipelines(dev, cache, n, infos, ac, pipes);
    if (r == VK_SUCCESS && pipes && infos) {
        for (uint32_t i = 0; i < n; i++) {
            char id[128]; int swapped = 0;
            id[0] = 0;
            pthread_mutex_lock(&g_id_mu);
            int mi = modid_find((uint64_t)infos[i].stage.module);
            if (mi >= 0) {
                snprintf(id, sizeof id, "%s", g_modid[mi].id);
                swapped = g_modid[mi].swapped;
            }
            pthread_mutex_unlock(&g_id_mu);
            cpipe_set((uint64_t)pipes[i], id, swapped);
            /* Logged for swapped modules only: this alone answers whether our
             * modules ever reach a compute pipeline, independent of dispatch. */
            if (swapped)
                LOGF("\"ev\":\"cpipe\",\"pipe\":\"0x%llx\",\"id\":\"%s\"}",
                     (unsigned long long)pipes[i], id);
        }
    }
    return r;
}

static void VKAPI_CALL xCmdBindPipeline(VkCommandBuffer cb,
        VkPipelineBindPoint bindPoint, VkPipeline pipe) {
    if (bindPoint == VK_PIPELINE_BIND_POINT_RAY_TRACING_KHR)
        cbbind_set(cb, (uint64_t)pipe);
    else if (bindPoint == VK_PIPELINE_BIND_POINT_COMPUTE)
        cbbind_set_compute(cb, (uint64_t)pipe);
    g_next_bind(cb, bindPoint, pipe);
}

static void VKAPI_CALL xCmdDispatch(VkCommandBuffer cb,
        uint32_t gx, uint32_t gy, uint32_t gz) {
    dispatch_maybe_log(cb, gx, gy, gz);
    g_next_dispatch(cb, gx, gy, gz);
}

/* Indirect dispatches carry their group counts in a buffer we cannot read
 * here, logged as -1. Without this hook a pass dispatched indirectly would
 * look like it never ran at all -- the wrong conclusion, loudly. */
static void VKAPI_CALL xCmdDispatchIndirect(VkCommandBuffer cb,
        VkBuffer buf, VkDeviceSize off) {
    dispatch_maybe_log(cb, (uint32_t)-1, (uint32_t)-1, (uint32_t)-1);
    g_next_dispatch_ind(cb, buf, off);
}

static void VKAPI_CALL xCmdTraceRaysKHR(VkCommandBuffer cb,
        const VkStridedDeviceAddressRegionKHR *rgen,
        const VkStridedDeviceAddressRegionKHR *miss,
        const VkStridedDeviceAddressRegionKHR *hit,
        const VkStridedDeviceAddressRegionKHR *call,
        uint32_t w, uint32_t h, uint32_t d) {
    trace_maybe_log(cb);
    g_next_trace(cb, rgen, miss, hit, call, w, h, d);
}

static void VKAPI_CALL xCmdTraceRaysIndirectKHR(VkCommandBuffer cb,
        const VkStridedDeviceAddressRegionKHR *rgen,
        const VkStridedDeviceAddressRegionKHR *miss,
        const VkStridedDeviceAddressRegionKHR *hit,
        const VkStridedDeviceAddressRegionKHR *call,
        VkDeviceAddress indirect) {
    trace_maybe_log(cb);
    g_next_trace_ind(cb, rgen, miss, hit, call, indirect);
}

static void VKAPI_CALL xCmdTraceRaysIndirect2KHR(VkCommandBuffer cb,
        VkDeviceAddress indirect) {
    trace_maybe_log(cb);
    g_next_trace_ind2(cb, indirect);
}

/* --- AS journal entry points (Stage 2a): observe, never alter. Each one
 * calls down unconditionally; the journal call cannot change any argument,
 * and a failed create is recorded as nothing at all. --- */
static VkResult VKAPI_CALL xCreateAccelerationStructureKHR(VkDevice dev,
        const VkAccelerationStructureCreateInfoKHR *ci,
        const VkAllocationCallbacks *ac, VkAccelerationStructureKHR *pAS) {
    DevData *d = find_dev(dev);
    if (!d || !d->CreateAS) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = d->CreateAS(dev, ci, ac, pAS);
    if (r == VK_SUCCESS && ci && pAS)
        asj_note_create((uint64_t)*pAS, (uint32_t)ci->type, (uint64_t)ci->size);
    return r;
}

static VkDeviceAddress VKAPI_CALL xGetAccelerationStructureDeviceAddressKHR(
        VkDevice dev, const VkAccelerationStructureDeviceAddressInfoKHR *info) {
    DevData *d = find_dev(dev);
    if (!d || !d->GetASAddr) return 0;
    VkDeviceAddress a = d->GetASAddr(dev, info);
    if (info) asj_note_addr((uint64_t)info->accelerationStructure, (uint64_t)a);
    return a;
}

static void VKAPI_CALL xCmdBuildAccelerationStructuresKHR(VkCommandBuffer cb,
        uint32_t n, const VkAccelerationStructureBuildGeometryInfoKHR *infos,
        const VkAccelerationStructureBuildRangeInfoKHR *const *ranges) {
    asj_note_build(n, infos, ranges);
    g_next_build_as(cb, n, infos, ranges);
}

/* The frame tick, and nothing else: neither hook inspects or alters an
 * argument, and both call down unconditionally. Present wins when both are
 * available -- it is armed first (see asj_note_frame) because a swapchain
 * device presents long before the submit path can matter. */
static VkResult VKAPI_CALL xQueuePresentKHR(VkQueue q, const VkPresentInfoKHR *pi) {
    asj_note_frame("present");
    return g_next_present(q, pi);
}
static VkResult VKAPI_CALL xQueueSubmit(VkQueue q, uint32_t n,
        const VkSubmitInfo *si, VkFence f) {
    if (!g_next_present) asj_note_frame("submit");
    return g_next_submit(q, n, si, f);
}

static void VKAPI_CALL xDestroyDevice(VkDevice dev, const VkAllocationCallbacks *ac) {
    DevData *d = find_dev(dev);
    PFN_vkDestroyDevice next = d ? d->DestroyDevice : NULL;
    asj_final_summary();
    bda_teardown(d, dev);               /* unmap + free before the device dies */
    del_dev(dev);                       /* drop before the handle dies */
    if (next) next(dev, ac);
}
static void VKAPI_CALL xDestroyInstance(VkInstance inst, const VkAllocationCallbacks *ac) {
    InstData *d = find_inst(inst);
    PFN_vkDestroyInstance next = d ? d->DestroyInstance : NULL;
    del_inst(inst);
    if (next) next(inst, ac);
    pthread_mutex_lock(&g_mu);
    if (!g_ninst && g_log && g_log != stderr) { fclose(g_log); g_log = NULL; }
    pthread_mutex_unlock(&g_mu);
}

/* ------------------------------------------------------------------ */
/* gipa / gdpa                                                         */
/* ------------------------------------------------------------------ */
typedef struct { const char *name; void *fn; } HookEnt;
static const HookEnt kDevHooks[] = {
    {"vkCreateShaderModule", (void *)xCreateShaderModule},
    {"vkDestroyDevice", (void *)xDestroyDevice},
};
/* Conditionally hooked: only exposed when the underlying entrypoint was
 * resolved at device-creation time, so a missing extension (or an untracked
 * device) degrades to pure passthrough instead of a NULL call. */
static PFN_vkVoidFunction cond_dev_hook(VkDevice dev, const char *name) {
    if (!strcmp(name, "vkDestroyShaderModule")) {
        DevData *d = find_dev(dev);
        if (d && d->DestroyShaderModule) return (PFN_vkVoidFunction)xDestroyShaderModule;
    } else if (!strcmp(name, "vkDestroyPipeline")) {
        DevData *d = find_dev(dev);
        if (d && d->DestroyPipeline) return (PFN_vkVoidFunction)xDestroyPipeline;
    } else if (!strcmp(name, "vkCreateRayTracingPipelinesKHR")) {
        DevData *d = find_dev(dev);
        if (d && d->CreateRTPipelines) return (PFN_vkVoidFunction)xCreateRayTracingPipelinesKHR;
    } else if (!strcmp(name, "vkCreateComputePipelines")) {
        DevData *d = find_dev(dev);
        if (d && d->CreateComputePipelines)
            return (PFN_vkVoidFunction)xCreateComputePipelines;
    } else if (!strcmp(name, "vkCreateAccelerationStructureKHR")) {
        DevData *d = find_dev(dev);
        if (d && d->CreateAS) return (PFN_vkVoidFunction)xCreateAccelerationStructureKHR;
    } else if (!strcmp(name, "vkGetAccelerationStructureDeviceAddressKHR")) {
        DevData *d = find_dev(dev);
        if (d && d->GetASAddr)
            return (PFN_vkVoidFunction)xGetAccelerationStructureDeviceAddressKHR;
    } else if (!strcmp(name, "vkCmdBuildAccelerationStructuresKHR")) {
        if (g_next_build_as) return (PFN_vkVoidFunction)xCmdBuildAccelerationStructuresKHR;
    } else if (!strcmp(name, "vkQueuePresentKHR")) {
        if (g_next_present) return (PFN_vkVoidFunction)xQueuePresentKHR;
    } else if (!strcmp(name, "vkQueueSubmit")) {
        if (g_next_submit) return (PFN_vkVoidFunction)xQueueSubmit;
    } else if (!strcmp(name, "vkCmdDispatch")) {
        if (g_next_dispatch) return (PFN_vkVoidFunction)xCmdDispatch;
    } else if (!strcmp(name, "vkCmdDispatchIndirect")) {
        if (g_next_dispatch_ind) return (PFN_vkVoidFunction)xCmdDispatchIndirect;
    } else if (!strcmp(name, "vkCmdBindPipeline")) {
        if (g_next_bind) return (PFN_vkVoidFunction)xCmdBindPipeline;
    } else if (!strcmp(name, "vkCmdTraceRaysKHR")) {
        if (g_next_trace) return (PFN_vkVoidFunction)xCmdTraceRaysKHR;
    } else if (!strcmp(name, "vkCmdTraceRaysIndirectKHR")) {
        if (g_next_trace_ind) return (PFN_vkVoidFunction)xCmdTraceRaysIndirectKHR;
    } else if (!strcmp(name, "vkCmdTraceRaysIndirect2KHR")) {
        if (g_next_trace_ind2) return (PFN_vkVoidFunction)xCmdTraceRaysIndirect2KHR;
    }
    return NULL;
}
static const HookEnt kInstHooks[] = {
    {"vkCreateInstance", (void *)xCreateInstance},
    {"vkCreateDevice", (void *)xCreateDevice},
    {"vkDestroyInstance", (void *)xDestroyInstance},
};

VK_LAYER_EXPORT PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(
        VkDevice dev, const char *name) {
    for (size_t i = 0; i < sizeof kDevHooks / sizeof kDevHooks[0]; i++)
        if (!strcmp(kDevHooks[i].name, name)) return (PFN_vkVoidFunction)kDevHooks[i].fn;
    PFN_vkVoidFunction ch = cond_dev_hook(dev, name);
    if (ch) return ch;
    DevData *d = find_dev(dev);
    if (d && d->gdpa) return d->gdpa(dev, name);
    return NULL;
}

VK_LAYER_EXPORT PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(
        VkInstance inst, const char *name) {
    for (size_t i = 0; i < sizeof kDevHooks / sizeof kDevHooks[0]; i++)
        if (!strcmp(kDevHooks[i].name, name)) return (PFN_vkVoidFunction)kDevHooks[i].fn;
    /* Device functions the app may fetch through gipa (legal in Vulkan). */
    PFN_vkVoidFunction ch = cond_dev_hook(VK_NULL_HANDLE, name);
    if (ch) return ch;
    for (size_t i = 0; i < sizeof kInstHooks / sizeof kInstHooks[0]; i++)
        if (!strcmp(kInstHooks[i].name, name)) return (PFN_vkVoidFunction)kInstHooks[i].fn;
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)vkGetInstanceProcAddr;
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)vkGetDeviceProcAddr;
    InstData *d = find_inst(inst);
    if (d && d->gipa) return d->gipa(inst, name);
    /* Best effort for pre-instance calls (inst == VK_NULL_HANDLE), where
     * there is no entry to find: any live instance's chain will do. */
    if (g_ninst && g_inst[0].gipa) return g_inst[0].gipa(inst, name);
    return NULL;
}

VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateInstanceExtensionProperties(
        const char *pLayerName, uint32_t *pCount, VkExtensionProperties *pProps) {
    (void)pLayerName; (void)pProps;
    /* This layer exposes no extensions. *pCount must be written on every
     * path -- leaving it untouched has the caller read uninitialized memory. */
    if (pCount) *pCount = 0;
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
    if (pLayerName && !strcmp(pLayerName, "VK_LAYER_CALLISTO_spvswap")) {
        *pCount = 0; return VK_SUCCESS;
    }
    *pCount = 0; return VK_SUCCESS;
}
VK_LAYER_EXPORT VkResult VKAPI_CALL vkEnumerateDeviceLayerProperties(
        VkPhysicalDevice dev, uint32_t *pCount, VkLayerProperties *pProps) {
    (void)dev; (void)pCount; (void)pProps;
    return VK_ERROR_LAYER_NOT_PRESENT;
}

__attribute__((constructor)) static void swap_init(void) {
    log_open(); swapdir_init(); overlay_init(); status_init();
    status_mark_loaded();
}
