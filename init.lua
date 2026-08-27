-- CallistoSSS settings (CET mod). CET sandboxes each mod's file I/O to its
-- own folder, so every file this mod touches lives here under a plain relative
-- name.
--
-- OUT: brdf_params.txt -- what the user asked for. sync_settings.sh (host
--      side, run before each launch by the Steam launch options) reads it,
--      materializes the swap/flag state from it, and evicts the pipeline
--      caches if it changed. Everything in this tab applies NEXT LAUNCH.
-- IN:  status.txt -- what actually happened. The swap layer records its real
--      hit counts, sync_settings.sh copies them in here at the next launch.
--      Rendered at the top of the tab, because a switch position is a request
--      and was never evidence of anything (handoff/09-SETTINGS-AUDIT.md, I6).
local PARAMS = "brdf_params.txt"
local STATUS = "status.txt"

local brdf = { tier = "1", kernel = "on", hair = "on", skinray = "on", shadowcull = "on", rho_f = 1.35, rho_r = 1.25,
               n_f = 0.75, m_f = 0.75, n_r = 0.75, m_r = 0.75 }

local function loadParams()
    local f = io.open(PARAMS, "r")
    if not f then return end
    for line in f:lines() do
        -- NB: %w excludes '_', so rho_f/n_f/... need the explicit class here;
        -- without it every numeric knob silently failed to load and the
        -- defaults were written straight back over the file on launch.
        local k, v = line:match("^([%w_]+)=([%w%.%-]+)")
        if k == "tier" or k == "kernel" or k == "hair" or k == "skinray" or k == "shadowcull" then brdf[k] = v
        elseif k and brdf[k] then brdf[k] = tonumber(v) or brdf[k] end
    end
    f:close()
end

local function saveParams()
    local f = io.open(PARAMS, "w")
    if not f then print("[CallistoSSS] cannot write brdf_params.txt") return end
    f:write("tier=" .. brdf.tier .. "\n")
    f:write("kernel=" .. brdf.kernel .. "\n")
    f:write("hair=" .. brdf.hair .. "\n")
    f:write("skinray=" .. brdf.skinray .. "\n")
    f:write("shadowcull=" .. brdf.shadowcull .. "\n")
    for _, k in ipairs({"rho_f", "rho_r", "n_f", "m_f", "n_r", "m_r"}) do
        f:write(string.format("%s=%.3f\n", k, brdf[k]))
    end
    f:close()
end

local status, haveStatus = {}, false

local function loadStatus()
    local f = io.open(STATUS, "r")
    if not f then return false end
    for line in f:lines() do
        -- values stay [alnum . - + _] so this stays a one-line pattern
        local k, v = line:match("^([%w_]+)=([%w%.%-%+]*)")
        if k then status[k] = v end
    end
    f:close()
    return true
end

local function num(k) return tonumber(status[k] or "") or 0 end

-- The headline. Deliberately says "last launch": this launch's totals do not
-- exist yet, and claiming otherwise is the exact failure this file is fixing.
local function statusLine()
    if not haveStatus then
        return "Last launch: no record -- launch once via the launch options"
    end
    if status.last_layer == "unknown" then
        return "Last launch: no record yet -- relaunch once to populate this"
    end
    if status.last_layer == "loaded_noswap" then
        return "Last launch: layer loaded but swapped NOTHING -- check the "
            .. "swap files are installed"
    end
    if status.last_layer ~= "loaded" then
        return "Last launch: LAYER DID NOT LOAD -- no shader swap took effect"
    end
    return string.format(
        "Last launch: %s | resolve %d, shadow %d, raygen %d, GI %d | caches %s",
        status.last_overlays or "none", num("last_resolve"), num("last_shadow"),
        num("last_raygen"), num("last_gi"), status.cache or "?")
end

-- Compare last launch's INTENT against last launch's RESULT. Comparing against
-- the current switch positions would cry wolf every time one was just flipped.
local function warnLine()
    if not haveStatus or status.last_layer ~= "loaded" then return nil end
    if num("last_failed") > 0 then
        return string.format("WARNING: %d swap(s) failed to create last launch",
                             num("last_failed"))
    end
    if status.last_want_hair == "on" and num("last_resolve") == 0 then
        return "WARNING: hair BRDF was on last launch but 0 compute-resolve "
            .. "swaps applied -- every visible effect lives there. Usually a "
            .. "stale pipeline cache: relaunch, or add CALLISTO_FORCE_CLEAR=1."
    end
    if status.last_want_shadowcull == "on" and num("last_shadow") == 0 then
        return "WARNING: shadow leak fix was on last launch but 0 shadow "
            .. "swaps applied."
    end
    return nil
end

registerForEvent("onInit", function()
    loadParams()
    haveStatus = loadStatus()
    saveParams() -- ensure the file exists with current values
    local nativeSettings = GetMod("nativeSettings")
    if not nativeSettings then
        print("[CallistoSSS] nativeSettings not found; toggle unavailable")
        return
    end
    nativeSettings.addTab("/callistoSSS", "Callisto SSS")
    -- Status first, so the first thing read is what happened, not what was
    -- asked for. Subcategory headers are the only plain-text surface
    -- nativeSettings offers, so the status rides in their labels.
    nativeSettings.addSubcategory("/callistoSSS/status", statusLine())
    local warn = warnLine()
    if warn then nativeSettings.addSubcategory("/callistoSSS/warn", warn) end
    nativeSettings.addSubcategory("/callistoSSS/main", "Skin subsurface scattering")
    nativeSettings.addSwitch("/callistoSSS/main", "Callisto skin kernel",
        "Replace the engine's SSS diffusion kernel with the Callisto-reshaped one. "
        .. "Applies on next game launch.",
        brdf.kernel ~= "off", true,
        function(state) brdf.kernel = state and "on" or "off" saveParams() end)
    local function slider(label, desc, key, min, max, dflt)
        nativeSettings.addRangeFloat("/callistoSSS/brdf", label,
            desc .. " Applies on next game restart.",
            min, max, 0.05, "%.2f", brdf[key], dflt,
            function(v) brdf[key] = v saveParams() end)
    end
    nativeSettings.addSubcategory("/callistoSSS/hair", "Hair")
    nativeSettings.addSwitch("/callistoSSS/hair", "Callisto hair BRDF",
        "The full hair specular package: strand-anisotropic (Kajiya-Kay) "
        .. "highlight, a shifted dual-lobe (sharp white R + wide tinted TRT "
        .. "glint), roughness reshape, grazing sheen and diffuse wrap. The "
        .. "strand direction is estimated per pixel from the normal buffer. "
        .. "Off restores vanilla hair. Applies on next launch."
        .. string.format(" [last launch: %d compute-resolve swaps applied]",
                         num("last_resolve")),
        brdf.hair ~= "off", true,
        function(state) brdf.hair = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/hair", "Hair shadow leak fix",
        "Stop shadow rays from culling back-facing triangles, so thin "
        .. "double-sided hair cards cast shadows from either side. Closes the "
        .. "overlit gap at the hairline. Turn off if you see self-shadow "
        .. "artifacts on other surfaces. Applies on next launch."
        .. string.format(" [last launch: %d shadow swaps applied]",
                         num("last_shadow")),
        brdf.shadowcull ~= "off", true,
        function(state) brdf.shadowcull = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/hair", "Callisto skin raygen sampling",
        "Restore the original tier-1 raygen build (sampling-side skin BRDF). "
        .. "Applies on next launch.",
        brdf.skinray ~= "off", true,
        function(state) brdf.skinray = state and "on" or "off" saveParams() end)
    nativeSettings.addSubcategory("/callistoSSS/brdf",
        "Callisto skin BRDF (restart required)")
    nativeSettings.addSwitch("/callistoSSS/brdf", "Callisto BRDF enabled",
        "Off removes the shader swaps entirely on next restart.",
        brdf.tier ~= "off", true,
        function(state) brdf.tier = state and "1" or "off" saveParams() end)
    slider("Diffuse Fresnel strength (rho_f)",
        "Grazing-angle diffuse boost; 1.0 = off.", "rho_f", 1.0, 2.0, 1.35)
    slider("Fresnel lobe tightness (n_f)",
        "Lower = tighter/stronger falloff lobe.", "n_f", 0.3, 1.0, 0.75)
    slider("Fresnel view exponent (m_f)",
        "View-angle counterpart of n_f.", "m_f", 0.3, 1.0, 0.75)
    slider("Retroreflection strength (rho_r)",
        "Front-lit glow; 1.0 = off.", "rho_r", 1.0, 2.0, 1.25)
    slider("Retro lobe tightness (n_r)",
        "Lower = tighter/stronger retro lobe.", "n_r", 0.3, 1.0, 0.75)
    slider("Retro view exponent (m_r)",
        "View-angle counterpart of n_r.", "m_r", 0.3, 1.0, 0.75)
end)
