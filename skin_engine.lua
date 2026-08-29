-- CallistoSSS -- engine skin specular / sheen panel.
--
-- WHAT THIS IS. Cyberpunk's renderer already parameterises skin's specular
-- response, and none of it needs a shader swap: the shipping exe carries
-- eight skin shader constants -- cvSkinSpecular, cvSkinFresnel,
-- cvSkinConstOffset, cvSkin_SpecularTint_{R,G,B,Weight},
-- cvSkin_AllowAmbientMix, cvSkin_Ambient{Intensity,Mix}Factor (handoff/16
-- section 7) -- bound to CVars under Editor/Characters/Skin and the
-- RimEnhancement groups.  The rim family is a grazing-angle additive
-- specular ("poor man's sheen", handoff/22 section 3): exactly the "more
-- obvious sheen on faces" lever, live-tunable.
--
-- Everything below is verified present in the shipping Cyberpunk2077.exe
-- (59,945,608 B, 2026-08-20; `strings -n 6`, handoff/27 for the block):
--
--   Editor/Characters/Skin            SubsurfaceSpecularTint_{R,G,B},
--                                     SubsurfaceSpecularTintWeight,
--                                     AllowSkinAmbientMix,
--                                     SkinAmbient{Intensity,Mix}_Factor
--   Editor/Characters/RimEnhancement/Skin    FresnelCoefficient,
--                                     SpecularCoefficient, ConstOffsetCoefficient
--                                     (unprefixed -- the other categories
--                                     carry Foliage_/Weapon_/Standard_ prefixes)
--   Editor/Characters/RimEnhancement  GlobalCharacterFresnel
--   Editor/Characters/RimEnhancement_RayTracing/Skin   RoughnessFactor_{Bias,Scale},
--                                     LightBlockerInfluence
--   Developer/FeatureToggles          CharacterRimEnhancement,
--                                     CharacterSubsurface{Translucency,Scattering}
--
-- CAVEAT, stated: the three RimEnhancement_RayTracing keys sit next to the
-- RT/Skin path in the string table, but the string is deduplicated so
-- whether they belong to RT/Skin alone or are shared by all four RT
-- categories is an inference from layout (handoff/22 made the opposite
-- guess for them).  A wrong (path,key) pair here reads as nil and the knob
-- is dead -- the subcategory header counts how many CVars were actually
-- found, so the gap is loud rather than silent.
--
-- UNLIKE every other Callisto knob, these apply LIVE -- no relaunch, no
-- cache clear.  They are engine settings, not shader swaps.
--
-- CONFLICT: while the master switch is on, this panel re-asserts its values
-- on a timer, so it will override any other mod writing the same CVars.
-- Turn it off to hand control back.

local M = {}

local FILE = "skin_engine.txt"

local SKIN    = "Editor/Characters/Skin"
local RIM     = "Editor/Characters/RimEnhancement/Skin"
local RIMROOT = "Editor/Characters/RimEnhancement"
local RIMRT   = "Editor/Characters/RimEnhancement_RayTracing/Skin"
local TOGGLES = "Developer/FeatureToggles"

-- label, path, key, kind, min, max, dflt.
-- dflt is only a fallback for a CVar that cannot be read at all: at register
-- time every value is snapshotted from the live engine, so turning the panel
-- on with untouched sliders writes back exactly what the game shipped.
local DEFS = {
  -- the sheen levers proper (rim family: grazing-angle additive specular)
  { key = "FresnelCoefficient",     path = RIM, label = "Rim: Fresnel coefficient",      min = 0.0, max = 4.0,  dflt = 1.0 },
  { key = "SpecularCoefficient",    path = RIM, label = "Rim: Specular coefficient",     min = 0.0, max = 4.0,  dflt = 1.0 },
  { key = "ConstOffsetCoefficient", path = RIM, label = "Rim: Const offset coefficient", min = -1.0, max = 1.0, dflt = 0.0 },
  { key = "GlobalCharacterFresnel", path = RIMROOT, label = "Global character Fresnel",  min = 0.0, max = 4.0,  dflt = 1.0 },
  { key = "RoughnessFactor_Bias",   path = RIMRT, label = "RT rim: Roughness bias",      min = -0.5, max = 0.5, dflt = 0.0 },
  { key = "RoughnessFactor_Scale",  path = RIMRT, label = "RT rim: Roughness scale",     min = 0.0, max = 4.0,  dflt = 1.0 },
  { key = "LightBlockerInfluence",  path = RIMRT, label = "RT rim: Light blocker influence",
    min = 0.0, max = 1.0, dflt = 1.0 },

  -- specular tint (subsurface specular colour)
  { key = "SubsurfaceSpecularTint_R",      path = SKIN, label = "Specular tint R",      min = 0.0, max = 2.0, dflt = 1.0 },
  { key = "SubsurfaceSpecularTint_G",      path = SKIN, label = "Specular tint G",      min = 0.0, max = 2.0, dflt = 1.0 },
  { key = "SubsurfaceSpecularTint_B",      path = SKIN, label = "Specular tint B",      min = 0.0, max = 2.0, dflt = 1.0 },
  { key = "SubsurfaceSpecularTintWeight",  path = SKIN, label = "Specular tint weight", min = 0.0, max = 1.0, dflt = 0.0 },

  -- ambient mix (adjacent skin response, same CVar family)
  { key = "AllowSkinAmbientMix",      path = SKIN, kind = "bool", label = "Allow skin ambient mix", dflt = false },
  { key = "SkinAmbientIntensity_Factor", path = SKIN, label = "Skin ambient intensity factor", min = 0.0, max = 2.0, dflt = 1.0 },
  { key = "SkinAmbientMix_Factor",    path = SKIN, label = "Skin ambient mix factor",    min = 0.0, max = 2.0, dflt = 1.0 },

  -- feature gates for the passes above
  { key = "CharacterRimEnhancement",       path = TOGGLES, kind = "bool", dflt = true,
    label = "Feature: Character rim enhancement" },
  { key = "CharacterSubsurfaceTranslucency", path = TOGGLES, kind = "bool", dflt = true,
    label = "Feature: Subsurface translucency" },
  { key = "CharacterSubsurfaceScattering",   path = TOGGLES, kind = "bool", dflt = true,
    label = "Feature: Subsurface scattering" },
}

local function id(d) return d.path .. "/" .. d.key end

local enabled = false
local vals    = {}   -- id -> current value
local vanilla = {}   -- id -> value snapshotted at first init (true engine default)
local haveVanilla = false

-- Every GameOptions call is pcall'd: a CVar that a future game patch renames
-- (or one attributed to the wrong path here) must degrade to "that one knob
-- does nothing", never to a broken mod.
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

-- The engine resets these across loads / fast travel, and other mods (Ultra
-- Plus writes the same families) reapply their presets on the same events.
-- Re-asserting on a slow timer is the dependency-free way to stay
-- authoritative; 2 s is far below any perceptible drift.
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
    -- of numbers copied out of somebody's preset -- and so enabling the
    -- panel with untouched sliders changes nothing.
    local found, missing = 0, {}
    for _, d in ipairs(DEFS) do
        local v = getRaw(d)
        if v ~= nil then vanilla[id(d)] = v; found = found + 1
        else table.insert(missing, id(d)) end
    end
    haveVanilla = next(vanilla) ~= nil
    for _, d in ipairs(DEFS) do
        vals[id(d)] = vanilla[id(d)]
        if vals[id(d)] == nil then vals[id(d)] = d.dflt end
    end
    if #missing > 0 then
        print("[CallistoSSS] skin panel: " .. #missing .. " CVars not found: "
              .. table.concat(missing, ", "))
    end
    load()
    -- A saved "on" must take effect at launch, not at the first slider touch.
    if enabled then M.apply() end

    local P = "/callistoSSS/engineskin"
    -- The found-count makes a dead CVar (renamed key, wrong path
    -- attribution) visible in the header instead of as a silently inert
    -- slider -- the loud-gap discipline the patchers follow.
    ns.addSubcategory(P, string.format(
        "Skin specular / sheen (engine, applies live) -- %d/%d CVars found",
        found, #DEFS))
    ns.addSwitch(P, "Take over engine skin settings",
        "Cyberpunk's renderer already parameterises skin's specular "
        .. "response: a rim (grazing-angle) Fresnel/specular family, a "
        .. "subsurface specular tint, and ambient mix -- all engine CVars, "
        .. "all applying LIVE, no relaunch.\n"
        .. "These are NOT Callisto shader swaps: they stack with the skin "
        .. "BRDF (which only touches the diffuse term) and compose with it "
        .. "multiplicatively.\n"
        .. "While this is on, Callisto re-asserts the values every 2s and "
        .. "will override any other mod writing the same settings.\n"
        .. "A/B method: fixed face framing, one knob at a time, "
        .. "exaggerate first to see which knobs act in the current render "
        .. "mode, then dial back to taste. 'Restore engine defaults' puts "
        .. "back what the game shipped when this session started.",
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
        local desc = key
        if d.path == RIMRT then
            desc = desc .. "\n(attribution inferred: if this slider does "
                .. "nothing, the key may belong to another RimEnhancement "
                .. "category -- see skin_engine.lua header)"
        end
        if d.kind == "bool" then
            ns.addSwitch(P, d.label, desc, vals[key] and true or false,
                d.dflt and true or false,
                function(state)
                    vals[key] = state
                    if enabled then setRaw(d, state) end
                    M.save()
                end)
        else
            local step = (d.max - d.min) / 200.0
            ns.addRangeFloat(P, d.label, desc, d.min, d.max, step, "%.3f",
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
