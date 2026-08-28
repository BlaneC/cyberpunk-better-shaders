-- CallistoSSS -- engine hair BRDF panel.
--
-- WHAT THIS IS. Cyberpunk's own renderer ships a three-lobe hair BRDF:
-- R, TT and TRT (the lobe names are Marschner's, and an alpha shift is his
-- cuticle tilt -- but that the shader *is* Marschner is an inference from the
-- CVar naming, never read out of shader code; see handoff/16 section 6), a
-- multiple-scattering term, per-light-path weights (local light / env probe
-- / global light), per-lobe alpha shifts and
-- a TRT exponent -- all of it live-tunable through engine CVars under
-- Editor/Characters/Hair, and all of it verified present in the shipping
-- Cyberpunk2077.exe.  There is also UseReferenceImplementation, which swaps
-- the hair shading to a different (better) engine path.
--
-- This is the BRDF the SPIR-V hair work was trying to build by hand.  See
-- handoff/16-ENGINE-HAIR-BRDF.md.  Ultra Plus reaches the same CVars from its
-- hidden Debug tab; this panel is here so the tuning does not depend on
-- another mod, and so the values live with the rest of Callisto's settings.
--
-- UNLIKE every other Callisto knob, these apply LIVE -- no relaunch, no cache
-- clear.  They are not shader swaps; they are engine settings.
--
-- CONFLICT: while the master switch is on, this panel re-asserts its values
-- on a timer, so it will override Ultra Plus's hair preset.  Turn it off (or
-- turn off Ultra Plus's "Hair Lighting Fixes") to hand control back.

local M = {}

local FILE = "hair_engine.txt"
local CAT  = "Editor/Characters/Hair"

-- name, subpath, kind, min, max, default(UltraPlus 'Enabled' PT preset)
-- Ranges are deliberately wider than the presets: these are tuning knobs and
-- the interesting values are often outside what any preset ships.
local DEFS = {
  { key = "UseReferenceImplementation",       path = CAT,                    kind = "bool",  dflt = true },
  { key = "UseGlobalContactShadowsOnHair",    path = CAT,                    kind = "bool",  dflt = true },
  { key = "UseLocalContactShadowsOnHair",     path = CAT,                    kind = "bool",  dflt = false },
  { key = "AlbedoMultiplier",                 path = CAT,                    min = 0.0, max = 2.0,  dflt = 0.16 },
  { key = "RoughnessFactor",                  path = CAT,                    min = 0.1, max = 6.0,  dflt = 3.0 },
  { key = "AdditionalAreaRoughness",          path = CAT,                    min = 0.0, max = 1.0,  dflt = 0.3 },
  { key = "SpecularRandom_Min",               path = CAT,                    min = -1.0, max = 0.0, dflt = -0.17 },
  { key = "SpecularRandom_Max",               path = CAT,                    min = 0.0, max = 1.0,  dflt = 0.17 },
  { key = "ContactShadowClamp",               path = CAT,                    min = 0.0, max = 1.0,  dflt = 0.0 },

  { key = "Wrap",            path = CAT .. "/Specular",     label = "Specular wrap",            min = 0.0, max = 2.0, dflt = 1.0 },
  { key = "Mask_Intensity",  path = CAT .. "/Specular",     label = "Specular mask intensity",  min = 0.0, max = 2.0, dflt = 1.0 },

  { key = "Wrap",                 path = CAT .. "/MultiScatter", label = "Multiscatter wrap",           min = 0.0, max = 2.0, dflt = 0.3 },
  { key = "Mask_Intensity",       path = CAT .. "/MultiScatter", label = "Multiscatter mask intensity", min = 0.0, max = 2.0, dflt = 0.3 },
  { key = "ShadowFactorExp",      path = CAT .. "/MultiScatter", label = "Multiscatter shadow exponent",min = 0.0, max = 3.0, dflt = 0.37 },
  { key = "DiffuseScatterFactor", path = CAT .. "/MultiScatter", label = "Multiscatter diffuse scatter",min = 0.0, max = 2.0, dflt = 0.0 },

  { key = "R",            path = CAT .. "/LocalLight",  label = "Local light R",            min = 0.0, max = 2.0, dflt = 0.9 },
  { key = "TT",           path = CAT .. "/LocalLight",  label = "Local light TT",           min = 0.0, max = 2.0, dflt = 0.005 },
  { key = "TRT",          path = CAT .. "/LocalLight",  label = "Local light TRT",          min = 0.0, max = 2.0, dflt = 0.8 },
  { key = "MultiScatter", path = CAT .. "/LocalLight",  label = "Local light multiscatter", min = 0.0, max = 2.0, dflt = 0.7 },
  { key = "ScatterDepth", path = CAT .. "/LocalLight",  label = "Local light scatter depth",min = 0.0, max = 6.0, dflt = 1.0 },

  { key = "R",            path = CAT .. "/EnvProbe",    label = "Env probe R",              min = 0.0, max = 2.0, dflt = 0.4 },
  { key = "TT",           path = CAT .. "/EnvProbe",    label = "Env probe TT",             min = 0.0, max = 2.0, dflt = 0.005 },
  { key = "TRT",          path = CAT .. "/EnvProbe",    label = "Env probe TRT",            min = 0.0, max = 2.0, dflt = 0.4 },
  { key = "MultiScatter", path = CAT .. "/EnvProbe",    label = "Env probe multiscatter",   min = 0.0, max = 2.0, dflt = 0.0 },
  { key = "ScatterDepth", path = CAT .. "/EnvProbe",    label = "Env probe scatter depth",  min = 0.0, max = 6.0, dflt = 0.5 },

  { key = "R",            path = CAT .. "/GlobalLight", label = "Global light R",           min = 0.0, max = 2.0, dflt = 0.5 },
  { key = "TT",           path = CAT .. "/GlobalLight", label = "Global light TT",          min = 0.0, max = 2.0, dflt = 0.005 },
  { key = "TRT",          path = CAT .. "/GlobalLight", label = "Global light TRT",         min = 0.0, max = 2.0, dflt = 0.84 },
  { key = "MultiScatter", path = CAT .. "/GlobalLight", label = "Global light multiscatter",min = 0.0, max = 2.0, dflt = 0.39 },
  { key = "ScatterDepth", path = CAT .. "/GlobalLight", label = "Global light scatter depth",min = 0.0, max = 8.0, dflt = 5.0 },

  { key = "R",   path = CAT .. "/AlphaShifts", label = "Alpha shift R",   min = -1.0, max = 1.0, dflt = -0.083 },
  { key = "TT",  path = CAT .. "/AlphaShifts", label = "Alpha shift TT",  min = -1.0, max = 2.0, dflt = 1.0 },
  { key = "TRT", path = CAT .. "/AlphaShifts", label = "Alpha shift TRT", min = -1.0, max = 1.0, dflt = -0.1 },

  { key = "EXP_SCALE", path = CAT .. "/TRT_Params", label = "TRT exponent scale", min = 0.0, max = 8.0, dflt = 3.5 },
  { key = "EXP_BIAS",  path = CAT .. "/TRT_Params", label = "TRT exponent bias",  min = 0.0, max = 4.0, dflt = 0.825 },

  { key = "AAAA_HACK_hairModifiedLocalLightIntensity", path = CAT .. "/HACKS", kind = "bool",
    label = "HACK: modified local light intensity", dflt = false },
  { key = "HACK_Factor0", path = CAT .. "/HACKS", label = "HACK factor 0", min = 0.0, max = 512.0, dflt = 66.0 },
  { key = "HACK_Factor1", path = CAT .. "/HACKS", label = "HACK factor 1", min = 0.0, max = 512.0, dflt = 95.0 },
  { key = "HACK_Factor2", path = CAT .. "/HACKS", label = "HACK factor 2", min = 0.0, max = 512.0, dflt = 213.0 },
  { key = "HACK_Factor3", path = CAT .. "/HACKS", label = "HACK factor 3", min = 0.0, max = 999.0, dflt = 450.0 },
}

local function id(d) return d.path .. "/" .. d.key end
local function label(d) return d.label or d.key end

local enabled = false
local vals    = {}   -- id -> current value
local vanilla = {}   -- id -> value snapshotted at first init (true engine default)
local haveVanilla = false

-- Every GameOptions call is pcall'd: a CVar that a future game patch renames
-- must degrade to "that one knob does nothing", never to a broken mod.
local function getRaw(d)
    local ok, v = pcall(GameOptions.Get, d.path, d.key)
    if not ok or v == nil then return nil end
    local s = tostring(v)
    if d.kind == "bool" then return s == "true" end
    return tonumber(s)
end

local function setRaw(d, v)
    if v == nil then return end
    if d.kind == "bool" then pcall(GameOptions.SetBool, d.path, d.key, v and true or false)
    else pcall(GameOptions.SetFloat, d.path, d.key, tonumber(v) or 0.0) end
end

function M.apply()
    if not enabled then return end
    for _, d in ipairs(DEFS) do setRaw(d, vals[id(d)]) end
end

function M.restoreVanilla()
    if not haveVanilla then return end
    for _, d in ipairs(DEFS) do
        local v = vanilla[id(d)]
        if v ~= nil then vals[id(d)] = v; setRaw(d, v) end
    end
    M.save()
end

function M.save()
    local f = io.open(FILE, "w")
    if not f then return end
    f:write("enabled=" .. (enabled and "1" or "0") .. "\n")
    for _, d in ipairs(DEFS) do
        local v = vals[id(d)]
        if v ~= nil then
            f:write(id(d) .. "=" ..
                (d.kind == "bool" and (v and "1" or "0")
                                  or string.format("%.4f", v)) .. "\n")
        end
    end
    f:close()
end

local function load()
    local f = io.open(FILE, "r")
    if not f then return end
    local byId = {}
    for _, d in ipairs(DEFS) do byId[id(d)] = d end
    for line in f:lines() do
        local k, v = line:match("^([^=]+)=(.+)$")
        if k == "enabled" then enabled = (v == "1")
        elseif k and byId[k] then
            vals[k] = (byId[k].kind == "bool") and (v == "1") or tonumber(v)
        end
    end
    f:close()
end

-- The engine resets these across loads / fast travel, and Ultra Plus reapplies
-- its own preset on the same events.  Re-asserting on a slow timer is the
-- dependency-free way to stay authoritative; 2 s is far below any perceptible
-- drift and costs ~40 CVar writes.
local acc = 0.0
function M.onUpdate(dt)
    if not enabled then return end
    acc = acc + (dt or 0)
    if acc < 2.0 then return end
    acc = 0.0
    M.apply()
end

function M.register(ns)
    -- Snapshot what the game actually shipped BEFORE writing anything, so
    -- "restore vanilla" restores the real engine values rather than a table
    -- of numbers copied out of somebody's preset.
    for _, d in ipairs(DEFS) do
        local v = getRaw(d)
        if v ~= nil then vanilla[id(d)] = v end
    end
    haveVanilla = next(vanilla) ~= nil
    for _, d in ipairs(DEFS) do
        vals[id(d)] = vanilla[id(d)]
        if vals[id(d)] == nil then vals[id(d)] = d.dflt end
    end
    load()
    -- A saved "on" must take effect at launch, not at the first slider touch.
    if enabled then M.apply() end

    local P = "/callistoSSS/enginehair"
    ns.addSubcategory(P, "Hair BRDF (engine, applies live)")
    ns.addSwitch(P, "Take over engine hair settings",
        "Cyberpunk's renderer already has a three-lobe (R/TT/TRT) hair BRDF "
        .. "with multiple scattering, exposed as engine CVars. These apply "
        .. "LIVE -- no relaunch. While this is on, Callisto re-asserts the "
        .. "values every 2s and will override Ultra Plus's hair preset.",
        enabled, false,
        function(state)
            enabled = state
            if state then M.apply() else M.restoreVanilla() end
            M.save()
        end)
    -- Prefer a button; fall back to a switch if this nativeSettings build has
    -- no addButton (the switch latches visually, which is ugly but harmless).
    local restoreDesc = "Write back the values the game had when this session "
        .. "started, and clear Callisto's overrides."
    local okBtn = pcall(ns.addButton, P, "Restore engine defaults", restoreDesc,
        "Restore", 60, function() M.restoreVanilla() end)
    if not okBtn then
        ns.addSwitch(P, "Restore engine defaults", restoreDesc, false, false,
            function(state) if state then M.restoreVanilla() end end)
    end

    for _, d in ipairs(DEFS) do
        local key = id(d)
        if d.kind == "bool" then
            ns.addSwitch(P, label(d), key, vals[key] and true or false,
                d.dflt and true or false,
                function(state)
                    vals[key] = state
                    if enabled then setRaw(d, state) end
                    M.save()
                end)
        else
            local step = (d.max - d.min) / 200.0
            ns.addRangeFloat(P, label(d), key, d.min, d.max, step, "%.3f",
                vals[key] or d.dflt, d.dflt,
                function(v)
                    vals[key] = v
                    if enabled then setRaw(d, v) end
                    M.save()
                end)
        end
    end
end

return M
