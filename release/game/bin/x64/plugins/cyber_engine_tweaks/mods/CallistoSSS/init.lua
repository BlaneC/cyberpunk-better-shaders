-- CallistoSSS settings (CET mod) -- release build.
-- The release exposes only the SSS kernel toggle: the Callisto BRDF shader
-- swaps ship pre-built at tuned defaults and need no settings. CET sandboxes
-- each mod's file I/O to its own folder, so brdf_params.txt lives next to
-- this file; sync_settings.sh (in red4ext/plugins/CallistoSSS, run via the
-- Steam launch options shown by install.sh) reads it and syncs kernel=on/off
-- to the RED4ext plugin's disable.flag. Applies on the NEXT GAME LAUNCH.
local PARAMS = "brdf_params.txt"

local settings = { kernel = "on" }

local function loadParams()
    local f = io.open(PARAMS, "r")
    if not f then return end
    for line in f:lines() do
        -- NB: %w excludes '_'; keep the explicit class for future keys.
        local k, v = line:match("^([%w_]+)=([%w%.%-]+)")
        if k == "kernel" then settings.kernel = v end
    end
    f:close()
end

local function saveParams()
    local f = io.open(PARAMS, "w")
    if not f then print("[CallistoSSS] cannot write brdf_params.txt") return end
    f:write("kernel=" .. settings.kernel .. "\n")
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
        settings.kernel ~= "off", true,
        function(state) settings.kernel = state and "on" or "off" saveParams() end)
end)
