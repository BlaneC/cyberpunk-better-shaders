-- CallistoSSS settings (CET mod). CET sandboxes each mod's file I/O to its
-- own folder, so BOTH files live here (plain relative names = this mod dir);
-- regen_and_clear.sh (host side, runs before each launch via the Steam launch
-- options) reads brdf_params.txt from here, regenerates the shader swaps, and
-- syncs kernel=on/off to the RED4ext plugin's disable.flag. Everything in
-- this tab therefore applies on the NEXT GAME LAUNCH.
local PARAMS = "brdf_params.txt"

local brdf = { tier = "1", kernel = "on", rho_f = 1.35, rho_r = 1.25,
               n_f = 0.75, m_f = 0.75, n_r = 0.75, m_r = 0.75 }

local function loadParams()
    local f = io.open(PARAMS, "r")
    if not f then return end
    for line in f:lines() do
        -- NB: %w excludes '_', so rho_f/n_f/... need the explicit class here;
        -- without it every numeric knob silently failed to load and the
        -- defaults were written straight back over the file on launch.
        local k, v = line:match("^([%w_]+)=([%w%.%-]+)")
        if k == "tier" or k == "kernel" then brdf[k] = v
        elseif k and brdf[k] then brdf[k] = tonumber(v) or brdf[k] end
    end
    f:close()
end

local function saveParams()
    local f = io.open(PARAMS, "w")
    if not f then print("[CallistoSSS] cannot write brdf_params.txt") return end
    f:write("tier=" .. brdf.tier .. "\n")
    f:write("kernel=" .. brdf.kernel .. "\n")
    for _, k in ipairs({"rho_f", "rho_r", "n_f", "m_f", "n_r", "m_r"}) do
        f:write(string.format("%s=%.3f\n", k, brdf[k]))
    end
    f:close()
end

registerForEvent("onInit", function()
    loadParams()
    saveParams() -- ensure the file exists with current values
    local nativeSettings = GetMod("nativeSettings")
    if not nativeSettings then
        print("[CallistoSSS] nativeSettings not found; toggle unavailable")
        return
    end
    nativeSettings.addTab("/callistoSSS", "Callisto SSS")
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
