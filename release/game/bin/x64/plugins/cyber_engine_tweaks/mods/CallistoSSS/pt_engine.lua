-- CallistoSSS -- engine path-tracer SAMPLING panel.
--
-- WHAT THIS IS, AND WHAT IT IS NOT.  This panel is the engine-first test
-- (GOTCHAS 8) for "more path samples where it counts", and it is the whole
-- of what can be delivered without shader surgery.  Read this before
-- believing any knob below:
--
--   * These are GLOBAL sampling budgets.  Nothing here is per-material.
--     There is no skin/eye/hair sample count in this engine -- see the
--     NOT-PER-MATERIAL note at the bottom of this header.
--   * None of these has ever been shown to work in this game.  Ultra Plus's
--     author found RayNumber/BounceNumber and wrote 0xDEADBEEF
--     (-559038737) into config/debug.ini for both -- that author's sentinel
--     for "found it, does not appear to do anything".  That is a CLAIM, not
--     a finding, and handoff/29 section B3 shows the shader half of it IS
--     real: the path loop's bound is `bitcast(cbv99[188]).z` at runtime in
--     8 of the 12 rgs_reference_main permutations (constant-folded to 2 in
--     the other 4).  So BounceNumber has a live wire into two-thirds of the
--     shader permutations, and re-testing it properly is worth ten minutes.
--   * This panel exists to turn that claim into a finding, either way.
--
-- ATTRIBUTION IS INFERRED, AND THE PANEL SAYS SO.  The exe's string table
-- deduplicates CVar KEYS, so `RayNumber` appears exactly once even though
-- RayTracing/{Reference,Diffuse,Reflection,LocalLight} could each own one.
-- Which group owns which key cannot be read from the table -- it is an
-- inference from layout, and handoff/22 vs handoff/27 already made opposite
-- guesses about a different key and one of them was wrong.
--
-- So each knob below carries a LIST of candidate paths and resolves at
-- register time to the first one the engine actually answers on.  The
-- resolved path is printed into the knob's own description, the header
-- counts how many resolved at all, and unresolved keys are named on the CET
-- console.  A wrong guess degrades to one dead knob that says it is dead,
-- never to a silently inert slider -- the trap that cost handoff/26 a whole
-- A/B session (six numeric sliders nothing read).
--
-- Verified present as strings in the shipping Cyberpunk2077.exe
-- (59,945,608 B, 2026-08-20), with their string-table neighbours:
--
--   RayNumber, BounceNumber, RayNumberScreenshot, BounceNumberScreenshot
--     -- one contiguous run, next to AdaptiveSampling/AdaptiveSamplingRatio/
--        TileSize and the Specular*Scale family
--   SampleNumber, SkipSamples      -- adjacent to the string
--                                     "RayTracing/Reference" itself
--   EnableReferenceAccumulation, EnableReferenceSER, AmbientOcclusionRayNumber
--     -- in the top-level "RayTracing" group's run
--
-- PERFORMANCE.  RayNumber is samples per pixel for the reference path
-- tracer.  2 spp is roughly twice the path-tracing cost of 1.  This is a
-- photo-mode and cutscene knob, not a gameplay one, and the screenshot
-- variants exist precisely because the engine authors thought the same.
-- Start at +1 and look at the frame time before going further.
--
-- THE CEILING, STATED UP FRONT (handoff/29 section B7).  Extra samples
-- reduce NOISE.  They do not sharpen anything.  The path tracer runs at
-- 1280x720 internally and is reconstructed to 1440p, then NRD/DLSS-RR
-- applies a spatial filter with no material awareness -- extra samples
-- enter the same history and get the same radius.  If faces read as SOFT
-- rather than NOISY, the lever is the denoiser or the internal resolution,
-- and neither is in this mod's reach.  Expect a real but partial win.
--
-- NOT PER-MATERIAL, AND WHY.  "More samples just on skin/eyes/hair" is
-- handoff/29 section B4: it needs the degenerate outer loop in
-- rgs_reference_main (header %12276, continue block %12818, which nothing
-- branches to) wired into a real sample loop with phis for the three
-- radiance accumulators and the LCG state.  That is gated on a sentinel
-- launch first -- GOTCHAS says a second OpTraceRayKHR spliced into a raygen
-- does not execute in this game, and while handoff/29 section B5 argues
-- that rule is stated more broadly than its evidence supports (the bounce
-- loop already traces twice per invocation and ships), nothing gets built
-- on it until a sentinel proves it.  This panel is what you run in the
-- meantime, and what tells you whether the axis is live at all.
--
-- These apply LIVE, like the hair and skin engine panels -- no relaunch, no
-- cache clear.  Whether the RT pipeline re-reads them mid-frame is itself
-- part of what this panel is testing.

local M = {}

local FILE = "pt_engine.txt"

local REF    = "RayTracing/Reference"
local REFSS  = "RayTracing/ReferenceScreenshot"
local RT     = "RayTracing"
local DIFF   = "RayTracing/Diffuse"
local REFL   = "RayTracing/Reflection"

-- key, paths (candidates, first that answers wins), kind, min, max, dflt.
-- dflt is only a fallback for a CVar that cannot be read at all: at register
-- time every value is snapshotted from the live engine, so turning the panel
-- on with untouched knobs writes back exactly what the game shipped.
local DEFS = {
  -- the two that matter, and the two Ultra Plus called dead
  { key = "RayNumber",    paths = { REF, RT }, kind = "int", min = 1, max = 8, dflt = 1,
    label = "Reference: samples per pixel" },
  { key = "BounceNumber", paths = { REF, RT }, kind = "int", min = 1, max = 8, dflt = 2,
    label = "Reference: bounces" },

  -- the separate, higher budget the engine keeps for screenshots
  { key = "RayNumberScreenshot",    paths = { REF, REFSS, RT }, kind = "int", min = 1, max = 32, dflt = 1,
    label = "Screenshot: samples per pixel" },
  { key = "BounceNumberScreenshot", paths = { REF, REFSS, RT }, kind = "int", min = 1, max = 16, dflt = 2,
    label = "Screenshot: bounces" },
  { key = "SampleNumber", paths = { REFSS, REF, RT }, kind = "int", min = 1, max = 64, dflt = 1,
    label = "Accumulation: samples to accumulate" },
  { key = "SkipSamples",  paths = { REFSS, REF, RT }, kind = "int", min = 0, max = 16, dflt = 0,
    label = "Accumulation: samples to skip" },
  { key = "EnableReferenceAccumulation", paths = { RT }, kind = "bool", dflt = false,
    label = "Enable reference accumulation" },

  -- the engine's OWN uneven-spend machinery: variance/tile driven, not
  -- material driven, so it will not "find faces" -- but a face in a shadow
  -- gradient is a high-variance tile, so it partially does the right thing
  -- for free.  Caveat: these keys are most likely owned by the Diffuse and
  -- Reflection groups, which are the RT-not-PT families; whether they touch
  -- RT Overdrive at all is exactly what the resolved-path line tells you.
  { key = "AdaptiveSampling",      paths = { DIFF, REFL, REF, RT }, kind = "bool", dflt = false,
    label = "Adaptive sampling (tile/variance driven)" },
  { key = "AdaptiveSamplingRatio", paths = { DIFF, REFL, REF, RT }, kind = "float",
    min = 0.0, max = 1.0, dflt = 0.5, label = "Adaptive sampling ratio" },
  { key = "TileSize",              paths = { DIFF, REFL, REF, RT }, kind = "int",
    min = 4, max = 32, dflt = 8, label = "Adaptive sampling tile size" },

  -- adjacent, same family, cheap to have in the same place
  { key = "AmbientOcclusionRayNumber", paths = { RT, REF }, kind = "int", min = 1, max = 8, dflt = 1,
    label = "RTAO: rays per pixel" },
  { key = "EnableReferenceSER", paths = { RT }, kind = "bool", dflt = true,
    label = "Shader execution reordering (SER)" },
}

local function id(d) return d.key end

local enabled = false
local vals    = {}   -- key -> current value
local vanilla = {}   -- key -> value snapshotted at first init
local resolved = {}  -- key -> the path that actually answered
local haveVanilla = false

-- Every GameOptions call is pcall'd: a CVar this file attributes to the
-- wrong group, or one a future game patch renames, must degrade to "that one
-- knob does nothing", never to a broken mod.
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

-- Try each candidate path in order; the first that answers owns the key.
local function resolve(d)
    for _, p in ipairs(d.paths) do
        local v = getAt(p, d.key, d.kind)
        if v ~= nil then return p, v end
    end
    return nil, nil
end

local function getRaw(d)
    local p = resolved[id(d)]
    if not p then return nil end
    return getAt(p, d.key, d.kind)
end

local function setRaw(d, v)
    local p = resolved[id(d)]
    if p == nil or v == nil then return end
    if d.kind == "bool" then
        pcall(GameOptions.SetBool, p, d.key, v and true or false)
    elseif d.kind == "int" then
        -- SetInt is not in every CET build; fall back to the string setter,
        -- and only then to SetFloat (which some builds accept for ints).
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

-- The engine resets these across loads / fast travel, and other mods (Ultra
-- Plus writes this exact family) reapply their presets on the same events.
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

-- Print every CVar the engine will admit to under the RayTracing groups.
-- This is the empirical answer to the attribution question above: whatever
-- GameOptions.List prints is the truth, and this header's inferences are
-- not.  List is not in every CET build, hence the pcall and the fallback of
-- reporting what THIS panel resolved.
function M.dump()
    print("[CallistoSSS] PT sampling -- resolved paths:")
    for _, d in ipairs(DEFS) do
        local p = resolved[id(d)]
        print(string.format("  %-28s %s", d.key,
            p and (p .. "  = " .. tostring(vanilla[id(d)])) or "NOT FOUND"))
    end
    local any = false
    for _, g in ipairs({ RT, REF, REFSS, DIFF, REFL }) do
        if pcall(GameOptions.List, g) then any = true end
    end
    if not any then
        print("  (GameOptions.List unavailable in this CET build -- the "
              .. "resolved list above is all this panel can tell you)")
    end
end

function M.register(ns)
    -- Snapshot what the game actually shipped BEFORE writing anything, so
    -- "restore engine defaults" restores real engine values and so enabling
    -- the panel with untouched knobs changes nothing.
    local found, missing = 0, {}
    for _, d in ipairs(DEFS) do
        local p, v = resolve(d)
        if p ~= nil then
            resolved[id(d)] = p; vanilla[id(d)] = v; found = found + 1
        else
            table.insert(missing, d.key)
        end
    end
    haveVanilla = next(vanilla) ~= nil
    for _, d in ipairs(DEFS) do
        vals[id(d)] = vanilla[id(d)]
        if vals[id(d)] == nil then vals[id(d)] = d.dflt end
    end
    if #missing > 0 then
        print("[CallistoSSS] PT sampling panel: " .. #missing
              .. " CVars not found on any candidate path: "
              .. table.concat(missing, ", "))
    end
    load()
    -- A saved "on" must take effect at launch, not at the first knob touch.
    if enabled then M.apply() end

    local P = "/callistoSSS/enginept"
    -- The found-count makes a wrong path attribution visible in the header
    -- instead of as a silently inert slider.
    ns.addSubcategory(P, string.format(
        "Path-tracer sampling (engine, applies live) -- %d/%d CVars found",
        found, #DEFS))
    ns.addSwitch(P, "Take over engine PT sampling",
        "GLOBAL path-tracer sample and bounce budgets, as engine CVars. "
        .. "NOT per-material: there is no skin/eye/hair sample count in this "
        .. "engine, and adding one needs shader surgery gated on a sentinel "
        .. "launch (handoff/29 B4-B5, handoff/31).\n"
        .. "NOTHING HERE IS CONFIRMED TO WORK. Ultra Plus's author marked "
        .. "RayNumber/BounceNumber as dead; handoff/29 B3 shows the shader "
        .. "half is real (the bounce bound is a runtime cbv value in 8 of 12 "
        .. "permutations), so this panel exists to settle it.\n"
        .. "COST: samples per pixel is linear in path-tracing time. 2 spp is "
        .. "about 2x the PT cost. Photo mode and cutscenes, not gameplay.\n"
        .. "CEILING: more samples reduce NOISE, not softness. PT runs at "
        .. "1280x720 internally and is reconstructed to 1440p by a filter "
        .. "with no material awareness -- if faces look soft rather than "
        .. "grainy, this is not the lever.\n"
        .. "While this is on, Callisto re-asserts these every 2s and will "
        .. "override any other mod writing them (Ultra Plus does).",
        enabled, false,
        function(state)
            enabled = state
            if state then M.apply() else M.restoreVanilla() end
            M.save()
        end)

    local restoreDesc = "Write back the values the game had when this session "
        .. "started, and clear Callisto's overrides."
    local okBtn = pcall(ns.addButton, P, "Restore engine defaults", restoreDesc,
        "Restore", 60, function() M.restoreVanilla() end)
    if not okBtn then
        ns.addSwitch(P, "Restore engine defaults", restoreDesc, false, false,
            function(state) if state then M.restoreVanilla() end end)
    end

    local dumpDesc = "Print every RayTracing CVar this panel resolved, plus "
        .. "whatever GameOptions.List will admit to, to the CET console. "
        .. "This is the empirical answer to which group owns which key -- "
        .. "the paths in this file are inferred from the exe's string "
        .. "layout and one of them may be wrong."
    local okDump = pcall(ns.addButton, P, "Dump RayTracing CVars to console",
        dumpDesc, "Dump", 60, function() M.dump() end)
    if not okDump then
        ns.addSwitch(P, "Dump RayTracing CVars to console", dumpDesc, false, false,
            function(state) if state then M.dump() end end)
    end

    for _, d in ipairs(DEFS) do
        local key = id(d)
        local p = resolved[key]
        local desc
        if p then
            desc = p .. "/" .. d.key .. "\n(resolved live -- this path answered)"
        else
            desc = d.key .. "\nNOT FOUND on any of: "
                .. table.concat(d.paths, ", ")
                .. "\n(this knob is dead; the key exists in the exe but this "
                .. "panel's group attribution for it is wrong)"
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
