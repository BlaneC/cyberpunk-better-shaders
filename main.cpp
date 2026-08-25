// CallistoSSS — RED4ext plugin that swaps CP2077's runtime-generated SSS_Blur
// diffusion-kernel texture (32x8 R32G32B32A32_FLOAT, CPU-uploaded once at init)
// for a Callisto-reshaped LUT. The kernel is data, not shader code (see
// analysis/HANDOFF.md §8.5/8.6), so no shader patching is needed.
//
// Mechanism: patch the ID3D12GraphicsCommandList vtable slot for
// CopyTextureRegion (vtable obtained from a throwaway device; d3d12.dll —
// vkd3d-proton under Proton — uses one static vtable per interface, shared
// with the game's objects). When a copy targets a 32x8 RGBA32F texture and
// the upload data matches the vanilla kernel fingerprint, the mapped upload
// bytes are overwritten with kernel.bin before the copy is recorded.

#include <windows.h>
#include <RED4ext/Common.hpp>
#include <RED4ext/Api/ApiVersion.hpp>
#include <RED4ext/Api/v1/EMainReason.hpp>
#include <RED4ext/Api/v1/PluginHandle.hpp>
#include <RED4ext/Api/v1/PluginInfo.hpp>
#include <RED4ext/Api/v1/Runtime.hpp>
#include <RED4ext/Api/v1/Sdk.hpp>
#include <RED4ext/Api/v1/SemVer.hpp>
#include <RED4ext/Api/v1/Version.hpp>

#include <windows.h>
#include <d3d12.h>
#include <cstdio>
#include <cstring>

#include "fingerprint.h"

static unsigned char g_kernel[4096];
static bool g_haveKernel = false;
static FILE* g_log = nullptr;
static wchar_t g_disableFlag[MAX_PATH]; // presence = injection off (settings toggle)

static void Log(const char* msg)
{
    if (g_log) { fprintf(g_log, "%s\n", msg); fflush(g_log); }
}

using CopyTextureRegion_t = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,
    const D3D12_TEXTURE_COPY_LOCATION*, UINT, UINT, UINT,
    const D3D12_TEXTURE_COPY_LOCATION*, const D3D12_BOX*);
static CopyTextureRegion_t g_origCopy = nullptr;

static void STDMETHODCALLTYPE HookedCopyTextureRegion(ID3D12GraphicsCommandList* self,
    const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
    const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box)
{
    if (g_haveKernel && dst && src && dst->pResource && src->pResource &&
        dst->Type == D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX &&
        src->Type == D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT)
    {
        D3D12_RESOURCE_DESC d = dst->pResource->GetDesc();
        if (d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.Width == 32 &&
            d.Height == 8 && d.Format == DXGI_FORMAT_R32G32B32A32_FLOAT)
        {
            // Only touch CPU-writable upload heaps: mapping other heaps (or
            // vkd3d internals mid-record) can deadlock/crash the driver.
            D3D12_HEAP_PROPERTIES hp{};
            D3D12_HEAP_FLAGS hf{};
            bool uploadHeap =
                SUCCEEDED(src->pResource->GetHeapProperties(&hp, &hf)) &&
                (hp.Type == D3D12_HEAP_TYPE_UPLOAD ||
                 (hp.Type == D3D12_HEAP_TYPE_CUSTOM &&
                  hp.CPUPageProperty != D3D12_CPU_PAGE_PROPERTY_NOT_AVAILABLE));
            if (!uploadHeap)
                Log("32x8 RGBA32F copy from non-upload heap — skipped");
            const auto& fp = src->PlacedFootprint;
            UINT pitch = fp.Footprint.RowPitch; // >= 512 (32 px * 16 B)
            D3D12_RANGE none{0, 0};
            void* p = nullptr;
            if (uploadHeap && pitch >= 512 &&
                SUCCEEDED(src->pResource->Map(0, &none, &p)) && p)
            {
                unsigned char* rows = (unsigned char*)p + fp.Offset;
                if (memcmp(rows, kFingerprint, 64) == 0)
                {
                    if (GetFileAttributesW(g_disableFlag) != INVALID_FILE_ATTRIBUTES)
                    {
                        Log("kernel upload seen — injection disabled by settings");
                        src->pResource->Unmap(0, nullptr);
                        g_origCopy(self, dst, x, y, z, src, box);
                        return;
                    }
                    for (UINT r = 0; r < 8; ++r)
                        memcpy(rows + r * pitch, g_kernel + r * 512, 512);
                    Log("kernel fingerprint matched — Callisto LUT injected");
                }
                src->pResource->Unmap(0, nullptr);
            }
        }
    }
    g_origCopy(self, dst, x, y, z, src, box);
}

static bool InstallHook()
{
    ID3D12Device* dev = nullptr;
    if (FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_12_0,
                                 IID_PPV_ARGS(&dev))) || !dev)
    {
        Log("ERROR: dummy D3D12CreateDevice failed");
        return false;
    }
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    bool ok = false;
    if (SUCCEEDED(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                                              IID_PPV_ARGS(&alloc))) &&
        SUCCEEDED(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc,
                                         nullptr, IID_PPV_ARGS(&list))))
    {
        void** vtbl = *(void***)list;
        const int SLOT = 16; // ID3D12GraphicsCommandList::CopyTextureRegion
        DWORD old;
        if (VirtualProtect(&vtbl[SLOT], sizeof(void*), PAGE_READWRITE, &old))
        {
            g_origCopy = (CopyTextureRegion_t)vtbl[SLOT];
            vtbl[SLOT] = (void*)&HookedCopyTextureRegion;
            VirtualProtect(&vtbl[SLOT], sizeof(void*), old, &old);
            ok = true;
            Log("CopyTextureRegion vtable hook installed");
        }
        else
            Log("ERROR: VirtualProtect failed");
    }
    else
        Log("ERROR: dummy command list creation failed");
    if (list) list->Release();
    if (alloc) alloc->Release();
    dev->Release();
    return ok;
}

static bool LoadKernel(HMODULE mod)
{
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(mod, path, MAX_PATH);
    wchar_t* s = wcsrchr(path, L'\\');
    if (!s) return false;
    wcscpy(s + 1, L"callisto.log");
    g_log = _wfopen(path, L"w");
    wcscpy(s + 1, L"disable.flag");
    wcscpy(g_disableFlag, path);
    wcscpy(s + 1, L"kernel.bin");
    FILE* f = _wfopen(path, L"rb");
    if (!f) { Log("ERROR: kernel.bin not found next to plugin dll"); return false; }
    bool ok = fread(g_kernel, 1, sizeof(g_kernel), f) == sizeof(g_kernel);
    fclose(f);
    if (!ok) Log("ERROR: kernel.bin is not 4096 bytes");
    return ok;
}

static HMODULE g_self = nullptr;

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) g_self = mod;
    return TRUE;
}

RED4EXT_C_EXPORT bool RED4EXT_CALL Main(RED4ext::v1::PluginHandle, RED4ext::v1::EMainReason aReason,
                                        const RED4ext::v1::Sdk*)
{
    if (aReason == RED4ext::v1::EMainReason::Load)
    {
        g_haveKernel = LoadKernel(g_self);
        if (g_haveKernel) InstallHook();
    }
    return true;
}

RED4EXT_C_EXPORT void RED4EXT_CALL Query(RED4ext::v1::PluginInfo* aInfo)
{
    aInfo->name = L"CallistoSSS";
    aInfo->author = L"blane";
    aInfo->version = RED4EXT_V1_SEMVER(0, 1, 0);
    aInfo->runtime = RED4EXT_V1_RUNTIME_VERSION_INDEPENDENT; // no game-struct use; loader only
    aInfo->sdk = RED4EXT_V1_SDK_VERSION_CURRENT;
}

RED4EXT_C_EXPORT uint32_t RED4EXT_CALL Supports()
{
    return RED4EXT_API_VERSION_1;
}
