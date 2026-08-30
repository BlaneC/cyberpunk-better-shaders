-- CallistoSSS -- engine DETAIL / denoiser panel.
--
-- WHAT THIS IS FOR.  "Faces read soft.  The shading just isn't that
-- detailed.  The bounce lighting adds so much, but it's very smoothed
-- over."  That complaint is not about sample counts -- extra path samples
-- reduce NOISE, and noise is not what is wrong.  It is about the stages that
-- run AFTER the integrator and average the signal spatially:
--
--   1. the SSS diffusion blur      -- handled elsewhere (dev/kernels/, the
--                                     "Callisto skin kernel" switch); it was
--                                     running at 10x the engine's own blur
--                                     radius, see handoff/33
--   2. the NRD denoiser            -- THIS PANEL
--   3. SHARC, the radiance cache   -- THIS PANEL; indirect light is looked up
--                                     from a spatial hash, so its detail
--                                     ceiling is the hash cell size, which is
--                                     exactly "the bounce lighting is smoothed"
--   4. DLSS upscaling / Ray Reconstruction -- partly this panel (sharpness),
--                                     mostly the game's own graphics menu
--
-- THE BIG CAVEAT, AND IT DECIDES WHETHER HALF THIS PANEL DOES ANYTHING.
-- In RT Overdrive, Cyberpunk normally denoises with DLSS Ray Reconstruction
-- (the DLSSD feature toggle), which REPLACES NRD wholesale.  If RR is on,
-- every NRD knob below is inert -- not broken, just bypassed.  The found
-- count in the header tells you the CVars EXIST; it cannot tell you they are
-- in the frame.  So the first A/B is: turn Ray Reconstruction off in the
-- game's graphics menu, confirm the NRD knobs then move the picture, and
-- only then decide which denoiser you want to live with.  RR generally
-- preserves more detail than ReBLUR at the same cost -- the honest outcome
-- may be "keep RR, and the fix is upstream in the SSS kernel".
--
-- ATTRIBUTION.  Same problem and same solution as pt_engine.lua: the exe
-- deduplicates CVar KEYS, so `DiffusePrepassBlurRadius` appears once in the
-- string table while ReBLUR/Direct and ReBLUR/Indirect both plausibly own
-- one.  Knobs that must address a SPECIFIC group carry a single explicit
-- path; knobs whose group is genuinely uncertain carry a candidate list and
-- resolve to whichever answers.  Either way the resolved path is printed
-- into the knob's own description and unresolved keys are named on the
-- console, so a wrong guess is a knob that says it is dead rather than
-- handoff/26 section 5's silently inert slider.
--
-- All of these were read out of the shipping Cyberpunk2077.exe string table
-- (59,945,608 B, 2026-08-20) -- the groups Editor/Denoising/NRD,
-- Editor/Denoising/ReBLUR{,/Direct,/Indirect,/AmbientOcclusion},
-- Editor/Denoising/ReLAX/{Direct,Indirect}/{Common,Diffuse,Specular},
-- Editor/SHARC and DLSS.  None of them had ever been exposed by anything.
--
-- DIRECTION OF TRAVEL.  Every knob here is labelled so that the SHARP
-- direction is obvious: blur radii and atrous iterations DOWN, luminance
-- edge-stopping (PhiLuminance) DOWN, history length DOWN for responsiveness
-- and UP for stability.  Denoiser tuning trades detail against noise and
-- temporal stability -- expect to reintroduce shimmer, and expect faces in
-- motion to be the first place you see it.
--
-- These apply LIVE, like the other engine panels.  Master switch default
-- OFF; vanilla snapshotted at init; re-asserted every 2 s.

local M = {}

local FILE = "detail_engine.txt"

local NRD      = "Editor/Denoising/NRD"
local RB       = "Editor/Denoising/ReBLUR"
local RB_D     = "Editor/Denoising/ReBLUR/Direct"
local RB_I     = "Editor/Denoising/ReBLUR/Indirect"
local RX_DC    = "Editor/Denoising/ReLAX/Direct/Common"
local RX_DD    = "Editor/Denoising/ReLAX/Direct/Diffuse"
local RX_IC    = "Editor/Denoising/ReLAX/Indirect/Common"
local RX_ID    = "Editor/Denoising/ReLAX/Indirect/Diffuse"
local RT       = "RayTracing"
local SHARC    = "Editor/SHARC"
local DLSS     = "DLSS"

-- name (unique), key, paths, kind, min, max, dflt, label.
-- `name` exists because the same KEY legitimately appears in several groups
-- and the save file / value table must keep them apart.
local DEFS = {
  -- ---- which denoiser is even running -------------------------------
  { name = "EnableNRD", key = "EnableNRD", paths = { RT }, kind = "bool", dflt = true,
    label = "NRD denoiser enabled" },
  { name = "ReblurDirect", key = "UseReblurForDirectRadiance", paths = { RT }, kind = "bool", dflt = true,
    label = "Direct light: use ReBLUR (off = ReLAX)" },
  { name = "ReblurIndirect", key = "UseReblurForIndirectRadiance", paths = { RT }, kind = "bool", dflt = true,
    label = "Bounce light: use ReBLUR (off = ReLAX)" },

  -- ---- the master radius --------------------------------------------
  { name = "DenoisingRadius", key = "DenoisingRadius", paths = { NRD }, kind = "float",
    min = 0.0, max = 60.0, dflt = 30.0, label = "NRD: denoising radius (LOWER = sharper)" },
  { name = "MaxAccum", key = "MaxAccumulatedFrameNum", paths = { NRD, RB }, kind = "int",
    min = 1, max = 63, dflt = 31, label = "NRD: temporal history length (frames)" },

  -- ---- ReBLUR: the pre-blur that runs BEFORE accumulation ------------
  -- These two are the most direct "stop smearing my face" knobs in the
  -- whole panel: a prepass blur is an unconditional spatial average applied
  -- to the radiance before any edge-aware filtering gets a say.
  { name = "RB_D_DiffusePrepass", key = "DiffusePrepassBlurRadius", paths = { RB_D }, kind = "float",
    min = 0.0, max = 60.0, dflt = 30.0, label = "ReBLUR direct: diffuse prepass blur (LOWER = sharper)" },
  { name = "RB_D_SpecPrepass", key = "SpecularPrepassBlurRadius", paths = { RB_D }, kind = "float",
    min = 0.0, max = 60.0, dflt = 20.0, label = "ReBLUR direct: specular prepass blur (LOWER = sharper)" },
  { name = "RB_I_DiffusePrepass", key = "DiffusePrepassBlurRadius", paths = { RB_I }, kind = "float",
    min = 0.0, max = 60.0, dflt = 30.0, label = "ReBLUR bounce: diffuse prepass blur (LOWER = sharper)" },
  { name = "RB_D_HistoryFix", key = "HistoryFixStrength", paths = { RB_D }, kind = "float",
    min = 0.0, max = 1.0, dflt = 0.5, label = "ReBLUR direct: history-fix strength" },
  { name = "RB_I_HistoryFix", key = "HistoryFixStrength", paths = { RB_I }, kind = "float",
    min = 0.0, max = 1.0, dflt = 0.5, label = "ReBLUR bounce: history-fix strength" },
  { name = "RB_D_Stabilization", key = "StabilizationStrength", paths = { RB_D }, kind = "float",
    min = 0.0, max = 1.0, dflt = 1.0, label = "ReBLUR direct: stabilization (LOWER = more detail, more shimmer)" },
  { name = "RB_D_LobeAngle", key = "LobeAngleFraction", paths = { RB_D }, kind = "float",
    min = 0.0, max = 1.0, dflt = 0.15, label = "ReBLUR direct: lobe angle fraction (normal tolerance)" },

  -- ---- ReLAX: the a-trous edge-stopping filter -----------------------
  -- AtrousIterationNum is a power-of-two-widening blur: each iteration
  -- roughly doubles the reach. Dropping it by one is a big detail win.
  { name = "RX_D_Atrous", key = "AtrousIterationNum", paths = { RX_DC }, kind = "int",
    min = 1, max = 8, dflt = 5, label = "ReLAX direct: a-trous iterations (LOWER = sharper)" },
  { name = "RX_I_Atrous", key = "AtrousIterationNum", paths = { RX_IC }, kind = "int",
    min = 1, max = 8, dflt = 5, label = "ReLAX bounce: a-trous iterations (LOWER = sharper)" },
  { name = "RX_D_PhiLum", key = "PhiLuminance", paths = { RX_DD }, kind = "float",
    min = 0.0, max = 8.0, dflt = 2.0, label = "ReLAX direct: luminance edge-stop (LOWER = keeps contrast)" },
  { name = "RX_I_PhiLum", key = "PhiLuminance", paths = { RX_ID }, kind = "float",
    min = 0.0, max = 8.0, dflt = 2.0, label = "ReLAX bounce: luminance edge-stop (LOWER = keeps contrast)" },
  { name = "RX_D_Prepass", key = "PrepassBlurRadius", paths = { RX_DD }, kind = "float",
    min = 0.0, max = 60.0, dflt = 30.0, label = "ReLAX direct: diffuse prepass blur (LOWER = sharper)" },
  { name = "RX_I_Prepass", key = "PrepassBlurRadius", paths = { RX_ID }, kind = "float",
    min = 0.0, max = 60.0, dflt = 30.0, label = "ReLAX bounce: diffuse prepass blur (LOWER = sharper)" },

  -- ---- SHARC: the spatial hash the bounce light is READ from ---------
  -- Indirect radiance is cached in world-space hash cells. The cell size is
  -- the hard ceiling on how much spatial detail bounce lighting can carry,
  -- no matter how many rays are spent -- so if "the bounce lighting is very
  -- smoothed over", this is the knob that is smoothing it.
  { name = "SHARC_Downscale", key = "DownscaleFactor", paths = { SHARC }, kind = "int",
    min = 1, max = 16, dflt = 4, label = "SHARC: cache downscale (LOWER = finer bounce detail)" },
  { name = "SHARC_SceneScale", key = "SceneScale", paths = { SHARC }, kind = "float",
    min = 1.0, max = 200.0, dflt = 50.0, label = "SHARC: scene scale (cell size; LOWER = finer)" },

  -- ---- the cosmetic last resort --------------------------------------
  -- Sharpening does not restore detail the denoiser removed; it raises local
  -- contrast on whatever survived, including the smooth patches' edges. On
  -- skin it reads as crunch before it reads as pores. Kept here because it
  -- is the knob everyone reaches for, so it should at least be measurable.
  { name = "DLSS_OverrideSharpness", key = "OverrideSharpness", paths = { DLSS }, kind = "bool", dflt = false,
    label = "DLSS: override sharpness" },
  { name = "DLSS_Sharpness", key = "Sharpness", paths = { DLSS }, kind = "float",
    min = 0.0, max = 1.0, dflt = 0.0, label = "DLSS: sharpness (cosmetic -- read the tooltip)" },
}

local function id(d) return d.name or d.key end

local enabled = false
local vals, vanilla, resolved = {}, {}, {}
local haveVanilla = false

local function getAt(path, key, kind)
    local ok, v = pcall(GameOptions.Get, path, key)
    if not ok or v == nil then return nil end
    local s = tostring(v)
    if s == "" then return nil end
    if kind == "bool" then
        if s ~= "true" and s ~= "false" then return nil end
        return s == "true"
    end
    return tonumber(s)
end

local function resolve(d)
    for _, p in ipairs(d.paths) do
        local v = getAt(p, d.key, d.kind)
        if v ~= nil then return p, v end
    end
    return nil, nil
end

local function setRaw(d, v)
    local p = resolved[id(d)]
    if p == nil or v == nil then return end
    if d.kind == "bool" then
        pcall(GameOptions.SetBool, p, d.key, v and true or false)
    elseif d.kind == "int" then
        local n = math.floor(tonumber(v) or 0)
        local ok = pcall(GameOptions.SetInt, p, d.key, n)
        if not ok then ok = pcall(GameOptions.Set, p, d.key, tostring(n)) end
        if not ok then pcall(GameOptions.SetFloat, p, d.key, n + 0.0) end
    else
        pcall(GameOptions.SetFloat, p, d.key, tonumber(v) or 0.0)
    end
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

-- One-click "show me the ceiling": every blur/iteration knob to its sharpest,
-- so the question "is the denoiser what is softening faces?" gets a yes/no
-- before anyone spends an evening on individual sliders. Expect noise and
-- shimmer -- this is a diagnostic, not a look, exactly like the `extreme`
-- rungs on the shader ladders.
function M.sharpAsPossible()
    local SHARP = {
        DenoisingRadius = 0.0, RB_D_DiffusePrepass = 0.0, RB_D_SpecPrepass = 0.0,
        RB_I_DiffusePrepass = 0.0, RX_D_Prepass = 0.0, RX_I_Prepass = 0.0,
        RX_D_Atrous = 1, RX_I_Atrous = 1, RX_D_PhiLum = 0.5, RX_I_PhiLum = 0.5,
        RB_D_Stabilization = 0.0, RB_D_HistoryFix = 0.0, RB_I_HistoryFix = 0.0,
    }
    for k, v in pairs(SHARP) do
        if resolved[k] then vals[k] = v end
    end
    if enabled then M.apply() end
    M.save()
    print("[CallistoSSS] detail panel: blur knobs set to sharpest. This is a "
          .. "diagnostic, not a look -- expect noise. 'Restore engine "
          .. "defaults' puts it back.")
end

function M.save()
    local f = io.open(FILE, "w")
    if not f then return end
    f:write("enabled=" .. (enabled and "1" or "0") .. "\n")
    for _, d in ipairs(DEFS) do
        local v = vals[id(d)]
        if v ~= nil then
            local s
            if d.kind == "bool" then s = v and "1" or "0"
            elseif d.kind == "int" then s = string.format("%d", math.floor(v))
            else s = string.format("%.4f", v) end
            f:write(id(d) .. "=" .. s .. "\n")
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
            local d = byId[k]
            if d.kind == "bool" then vals[k] = (v == "1")
            elseif d.kind == "int" then vals[k] = math.floor(tonumber(v) or d.dflt)
            else vals[k] = tonumber(v) end
        end
    end
    f:close()
end

local acc = 0.0
function M.onUpdate(dt)
    if not enabled then return end
    acc = acc + (dt or 0)
    if acc < 2.0 then return end
    acc = 0.0
    M.apply()
end

function M.dump()
    print("[CallistoSSS] detail/denoiser -- resolved paths:")
    for _, d in ipairs(DEFS) do
        local p = resolved[id(d)]
        print(string.format("  %-24s %s", id(d),
            p and (p .. "/" .. d.key .. " = " .. tostring(vanilla[id(d)]))
              or ("NOT FOUND (" .. d.key .. ")")))
    end
    for _, g in ipairs({ NRD, RB, RB_D, RB_I, RX_DC, RX_DD, RX_IC, RX_ID, SHARC, DLSS, RT }) do
        pcall(GameOptions.List, g)
    end
end

function M.register(ns)
    local found, missing = 0, {}
    for _, d in ipairs(DEFS) do
        local p, v = resolve(d)
        if p ~= nil then
            resolved[id(d)] = p; vanilla[id(d)] = v; found = found + 1
        else
            table.insert(missing, id(d) .. " (" .. d.key .. ")")
        end
    end
    haveVanilla = next(vanilla) ~= nil
    for _, d in ipairs(DEFS) do
        vals[id(d)] = vanilla[id(d)]
        if vals[id(d)] == nil then vals[id(d)] = d.dflt end
    end
    if #missing > 0 then
        print("[CallistoSSS] detail panel: " .. #missing
              .. " CVars not found on any candidate path: "
              .. table.concat(missing, ", "))
    end
    load()
    if enabled then M.apply() end

    local P = "/callistoSSS/enginedetail"
    ns.addSubcategory(P, string.format(
        "Detail / denoiser (engine, applies live) -- %d/%d CVars found",
        found, #DEFS))
    ns.addSwitch(P, "Take over engine denoiser settings",
        "For \"faces read soft / the shading isn't detailed / the bounce "
        .. "lighting is smoothed over\". Those are filtering problems, not "
        .. "sample-count problems: more path samples cut NOISE, and noise is "
        .. "not what is wrong.\n"
        .. "READ THIS FIRST: in RT Overdrive the game normally denoises with "
        .. "DLSS Ray Reconstruction, which REPLACES NRD entirely. If RR is "
        .. "on, every NRD knob here is bypassed -- the found-count proves "
        .. "the CVars exist, not that they are in your frame. Turn Ray "
        .. "Reconstruction off in the graphics menu first and confirm these "
        .. "move the picture.\n"
        .. "SHARC is the other half: bounce light is read from a world-space "
        .. "hash, and the cell size caps how much detail indirect lighting "
        .. "can ever carry, however many rays you spend.\n"
        .. "Denoiser tuning trades detail for noise and temporal stability. "
        .. "Faces in motion are where you will see the cost first.\n"
        .. "While this is on, Callisto re-asserts these every 2s.",
        enabled, false,
        function(state)
            enabled = state
            if state then M.apply() else M.restoreVanilla() end
            M.save()
        end)

    local function button(label, desc, cb)
        local ok = pcall(ns.addButton, P, label, desc, label, 60, cb)
        if not ok then
            ns.addSwitch(P, label, desc, false, false,
                function(state) if state then cb() end end)
        end
    end
    button("Restore engine defaults",
        "Write back the values the game had when this session started.",
        function() M.restoreVanilla() end)
    button("Sharpest possible (diagnostic)",
        "Every blur radius to 0 and every a-trous iteration to 1, in one "
        .. "click. Answers \"is the denoiser what is softening faces?\" "
        .. "before you spend an evening on sliders. Expect noise and "
        .. "shimmer; this is a diagnostic, not a look.",
        function() M.sharpAsPossible() end)
    button("Dump denoiser CVars to console",
        "Print what this panel resolved, plus whatever GameOptions.List "
        .. "will admit to. The group each key belongs to is inferred from "
        .. "the exe's string layout and some of it may be wrong.",
        function() M.dump() end)

    for _, d in ipairs(DEFS) do
        local key = id(d)
        local p = resolved[key]
        local desc
        if p then
            desc = p .. "/" .. d.key .. "\n(resolved live -- this path answered)"
        else
            desc = d.key .. "\nNOT FOUND on: " .. table.concat(d.paths, ", ")
                .. "\n(dead knob -- the key exists in the exe but this "
                .. "panel's group attribution for it is wrong)"
        end
        if d.name == "DLSS_Sharpness" then
            desc = desc .. "\nSharpening does NOT restore detail the denoiser "
                .. "removed -- it raises local contrast on whatever survived, "
                .. "edges of smooth patches included. On skin it reads as "
                .. "crunch before it reads as pores. Fix the blur first."
        end
        if d.kind == "bool" then
            ns.addSwitch(P, d.label, desc, vals[key] and true or false,
                d.dflt and true or false,
                function(state)
                    vals[key] = state
                    if enabled then setRaw(d, state) end
                    M.save()
                end)
        elseif d.kind == "int" then
            local cur = math.floor(vals[key] or d.dflt)
            local okInt = pcall(ns.addRangeInt, P, d.label, desc,
                d.min, d.max, 1, cur, d.dflt,
                function(v)
                    vals[key] = math.floor(v)
                    if enabled then setRaw(d, vals[key]) end
                    M.save()
                end)
            if not okInt then
                ns.addRangeFloat(P, d.label, desc, d.min, d.max, 1, "%.0f",
                    cur, d.dflt,
                    function(v)
                        vals[key] = math.floor(v)
                        if enabled then setRaw(d, vals[key]) end
                        M.save()
                    end)
            end
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
