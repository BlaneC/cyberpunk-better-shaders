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
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    if (n < 20 || (n & 3)) { fclose(f); LOGF("\"ev\":\"swap_bad\",\"file\":\"%s\",\"size\":%ld}", path, n); return NULL; }
    uint32_t *buf = malloc(n);
    if (!buf || fread(buf, 1, n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    if (buf[0] != 0x07230203) { LOGF("\"ev\":\"swap_bad\",\"file\":\"%s\",\"reason\":\"magic\"}", path); free(buf); return NULL; }
    *out_size = (size_t)n;
    LOGF("\"ev\":\"swap_load\",\"file\":\"%s\",\"size\":%ld}", path, n);
    return buf;
}

/* Resolve <layerdir>/swaps.<name> and its <layerdir>/<name>.disable flag.
 * Name comes from CALLISTO_OVERLAY (default "hair"). Called once, after
 * swapdir_init has filled g_layerdir. */
static void overlay_init(void) {
    const char *list = getenv("CALLISTO_OVERLAYS");
    if (!list || !*list) list = "hair,shadowcull";
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
    unsigned resolve, shadow, raygen, gi, other, failed;
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
        " \"gi\": %u, \"other\": %u, \"failed\": %u }\n"
        "}\n",
        (int)getpid(), (unsigned long long)g_seq, g_swapdir, ovl,
        g_disabled ? "true" : "false",
        g_hits.resolve, g_hits.shadow, g_hits.raygen, g_hits.gi,
        g_hits.other, g_hits.failed);
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
    else if (strstr(id, "rgs_restirgi")) g_hits.gi++;
    else g_hits.other++;
    pthread_mutex_unlock(&g_status_mu);
    status_write();
}

static uint32_t *load_swap(const char *name, size_t *out_size) {
    for (int i = 0; i < g_noverlay; i++) {
        uint32_t *c = load_swap_from(g_overlaydir[i], name, out_size);
        if (c) return c;
    }
    return load_swap_from(g_swapdir, name, out_size);
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
    VkLayerDeviceCreateInfo save = *lc;
    ((VkLayerDeviceCreateInfo *)lc)->u.pLayerInfo = lc->u.pLayerInfo->pNext;
    VkResult r = next_create(phys, ci, ac, pDev);
    ((VkLayerDeviceCreateInfo *)lc)->u.pLayerInfo = save.u.pLayerInfo;
    if (r != VK_SUCCESS) return r;

    VkDevice dev = *pDev;
    DevData *d = add_dev(dev);
    if (!d) {
        LOGF("\"ev\":\"table_full\",\"what\":\"device\",\"max\":%d}", MAX_OBJ);
        return r;                       /* untracked: gdpa falls through */
    }
    d->gdpa = next_gdpa;
    d->DestroyDevice = (PFN_vkDestroyDevice)d->gdpa(dev, "vkDestroyDevice");
    d->CreateShaderModule = (PFN_vkCreateShaderModule)d->gdpa(dev, "vkCreateShaderModule");
    d->DestroyShaderModule = (PFN_vkDestroyShaderModule)d->gdpa(dev, "vkDestroyShaderModule");
    d->DestroyPipeline = (PFN_vkDestroyPipeline)d->gdpa(dev, "vkDestroyPipeline");
    d->CreateRTPipelines = (PFN_vkCreateRayTracingPipelinesKHR)
        d->gdpa(dev, "vkCreateRayTracingPipelinesKHR");
    d->CreateComputePipelines = (PFN_vkCreateComputePipelines)
        d->gdpa(dev, "vkCreateComputePipelines");
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
    char sha[65];
    sha256(ci->pCode, ci->codeSize, sha);

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
                     has_id ? id : sha);
            /* Same module is created repeatedly; first write wins. */
            if (access(path, F_OK) != 0) {
                FILE *df = fopen(path, "wb");
                if (df) {
                    fwrite(ci->pCode, 1, ci->codeSize, df);
                    fclose(df);
                    LOGF("\"ev\":\"dump\",\"id\":\"%s\",\"sha256\":\"%s\","
                         "\"size\":%zu,\"path\":\"%s\"}",
                         has_id ? id : "", sha, ci->codeSize, path);
                }
            }
        }
    }

    if (g_disabled) {
        if (!g_quiet)
            LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"disabled\"}",
                 ci->codeSize, has_id ? id : "", sha);
        VkResult r = next(dev, ci, ac, pMod);
        if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 0);
        return r;
    }

    uint32_t *code = NULL; size_t size = 0;
    if (has_id) code = load_swap(id, &size);          /* <hash>.<entry>.spv */
    if (!code) {
        char name[80];
        snprintf(name, sizeof name, "sha256-%s", sha);
        code = load_swap(name, &size);                /* sha256-<hex>.spv */
    }

    if (!code) {
        if (!g_quiet)
            LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"none\"}",
                 ci->codeSize, has_id ? id : "", sha);
        VkResult r = next(dev, ci, ac, pMod);
        if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 0);
        return r;
    }

    VkShaderModuleCreateInfo sub = *ci;
    sub.pCode = code; sub.codeSize = size;
    VkResult r = next(dev, &sub, ac, pMod);
    LOGF("\"ev\":\"module\",\"size\":%zu,\"id\":\"%s\",\"sha256\":\"%s\",\"swap\":\"%s\",\"result\":%d}",
         ci->codeSize, has_id ? id : "", sha,
         r == VK_SUCCESS ? "HIT" : "hit_failed", (int)r);
    if (r == VK_SUCCESS && pMod) modid_add((uint64_t)*pMod, id, 1);
    status_hit(has_id ? id : "", r == VK_SUCCESS);
    free(code);
    return r;
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
    if (r != VK_SUCCESS && r != VK_PIPELINE_COMPILE_REQUIRED) return r;

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

static void VKAPI_CALL xDestroyDevice(VkDevice dev, const VkAllocationCallbacks *ac) {
    DevData *d = find_dev(dev);
    PFN_vkDestroyDevice next = d ? d->DestroyDevice : NULL;
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
