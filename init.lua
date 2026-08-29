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

local brdf = { tier = "1", kernel = "on", skin = "on", skinray = "on", shadowcull = "on",
               -- Path tracing (handoff/23 tier 1). ptreg is the only one that
               -- trades look for noise, so it is the only one defaulting off.
               shadowset = "full-shadow",
               ptreg = "off", ptclamp = "on", ptbounce = "on", ptrefl = "on",
               -- T2.1 energy compensation. On by default since 2026-08-28,
               -- when it was confirmed on screen (handoff/28): it restores
               -- energy the lobe was always meant to have, so it is a fix,
               -- not a look trade. Off stays available for A/B.
               ptmsggx = "on",
               -- Callisto Tier-3 skin gloss (handoff/27 Phase 2). Off until it
               -- has been confirmed on screen; the CET skin CVar panel could
               -- not produce this look at all (`27` §4), so this is the only
               -- route to it and it has never been observed.
               skinspec = "strong",
               -- Callisto Tier-4 backlit skin transmission (handoff/29).
               -- Off until it has been seen on screen: unlike the gloss it
               -- ADDS light where the engine currently puts none, so the
               -- ledger rule (handoff/19, /28) says it stays opt-in.
               skintrans = "off",
               rho_f = 1.35, rho_r = 1.25,
               n_f = 0.75, m_f = 0.75, n_r = 0.75, m_r = 0.75 }

-- The on/off keys, as opposed to the numeric ones. Kept as a set so adding a
-- switch means adding one word, not editing a chain of `or` comparisons.
local SWITCHES = { "tier", "kernel", "skin", "skinray", "shadowcull",
                   "shadowset", "skinspec", "skintrans",
                   "ptreg", "ptclamp", "ptbounce", "ptrefl", "ptmsggx" }
local isSwitch = {}
for _, k in ipairs(SWITCHES) do isSwitch[k] = true end

-- Which build of the shadow-leak fix is served. Every entry patches the same
-- 18 modules and differs only in the edit, so switching between two of them
-- attributes cleanly. The ids must match dev/build_shadow_sets.sh's VARIANTS
-- and the dirs dev/install_shadow_sets.sh parks in shadowcull.set/.
--
-- `full` is first and is the default because it is the one build that
-- demonstrably closes the hairline seam; everything after it is a live
-- experiment (handoff/25-SHADOW-FLICKER.md §9).
-- How oily. The Tier-3 knobs are OpConstants baked into the SPIR-V at build
-- time, so this CANNOT be a live slider -- moving one would change nothing,
-- which is the inert-slider trap of 26-SESSION-0828.md section 5. Strength is
-- a ladder of pre-built sets instead, picked at launch like the shadow build.
-- The ids must match dev/patch_compute_skin.sh's LEVELS and the dirs it parks
-- in skin.set/.
local SKIN_LEVELS = {
    { id = "off",     label = "Off -- tier-1 skin only (A/B control)" },
    { id = "subtle",  label = "Subtle -- damp sheen (roughness cap 0.40)" },
    { id = "medium",  label = "Medium -- clearly wet (0.30)" },
    { id = "strong",  label = "Strong -- unmistakably oily (0.21)" },
    { id = "extreme", label = "Extreme -- diagnostic, reads as wet plastic (0.14)" },
}
local SKIN_LABELS, SKIN_INDEX = {}, {}
for i, e in ipairs(SKIN_LEVELS) do
    SKIN_LABELS[i] = e.label
    SKIN_INDEX[e.id] = i
end

-- How much light comes through thin skin from behind. Same baked-constant
-- problem as the gloss, so the same answer: a ladder of pre-built sets, not a
-- slider. The ids must match dev/patch_compute_skin.sh's TLEVELS, and the
-- dirs it parks are named "<skinspec>+t<skintrans>" -- the two ladders splice
-- the same modules, so the combinations have to be built, not composed at
-- launch. That is also why picking a transmission level with no built
-- combination falls back to the gloss-only set rather than to off.
local TRANS_LEVELS = {
    { id = "off",     label = "Off -- no transmission (A/B control)" },
    { id = "subtle",  label = "Subtle -- a hint at the silhouette" },
    { id = "medium",  label = "Medium -- ears read warm against the sun" },
    { id = "strong",  label = "Strong -- the whole backlit side glows" },
    { id = "extreme", label = "Extreme -- diagnostic, ignores geometry" },
}
local TRANS_LABELS, TRANS_INDEX = {}, {}
for i, e in ipairs(TRANS_LEVELS) do
    TRANS_LABELS[i] = e.label
    TRANS_INDEX[e.id] = i
end

local SHADOW_SETS = {
    { id = "full-shadow", label = "Direct shadow rays (recommended)" },
    { id = "full",        label = "Direct + GI rays (more flicker)" },
}
local SHADOW_LABELS, SHADOW_INDEX = {}, {}
for i, e in ipairs(SHADOW_SETS) do
    SHADOW_LABELS[i] = e.label
    SHADOW_INDEX[e.id] = i
end

local function loadParams()
    local f = io.open(PARAMS, "r")
    if not f then return end
    for line in f:lines() do
        -- NB: %w excludes '_', so rho_f/n_f/... need the explicit class here;
        -- without it every numeric knob silently failed to load and the
        -- defaults were written straight back over the file on launch.
        local k, v = line:match("^([%w_]+)=([%w%.%-]+)")
        if isSwitch[k] then brdf[k] = v
        elseif k and brdf[k] then brdf[k] = tonumber(v) or brdf[k] end
    end
    f:close()
    -- A params file left over from the bisect can name a set that no longer
    -- exists. sync_settings.sh already falls back, but normalise here too so
    -- the selector does not silently disagree with what is being served.
    if not SHADOW_INDEX[brdf.shadowset] then brdf.shadowset = SHADOW_SETS[1].id end
    -- "on" was the old boolean value; sync_settings.sh still accepts it as an
    -- alias for strong, but normalise here so the selector agrees with what is
    -- actually being served.
    if brdf.skinspec == "on" then brdf.skinspec = "strong" end
    if not SKIN_INDEX[brdf.skinspec] then brdf.skinspec = "off" end
    if not TRANS_INDEX[brdf.skintrans] then brdf.skintrans = "off" end
end

local function saveParams()
    local f = io.open(PARAMS, "w")
    if not f then print("[CallistoSSS] cannot write brdf_params.txt") return end
    for _, k in ipairs(SWITCHES) do f:write(k .. "=" .. brdf[k] .. "\n") end
    for _, k in ipairs({"rho_f", "rho_r", "n_f", "m_f", "n_r", "m_r"}) do
        f:write(string.format("%s=%.3f\n", k, brdf[k]))
    end
    f:close()
end

-- Engine hair BRDF panel (live CVars, not shader swaps). Loaded defensively:
-- if the file is missing or CET's require differs, the rest of the tab still
-- registers.
local hairEngine
do
    local ok, m = pcall(require, "hair_engine")
    if not ok then ok, m = pcall(dofile, "hair_engine.lua") end
    if ok and type(m) == "table" then hairEngine = m
    else print("[CallistoSSS] hair_engine.lua not loaded: " .. tostring(m)) end
end

-- Engine skin specular / sheen panel (live CVars, same pattern).
local skinEngine
do
    local ok, m = pcall(require, "skin_engine")
    if not ok then ok, m = pcall(dofile, "skin_engine.lua") end
    if ok and type(m) == "table" then skinEngine = m
    else print("[CallistoSSS] skin_engine.lua not loaded: " .. tostring(m)) end
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
        "Last launch: %s | resolve %d, shadow %d, raygen %d, refl %d, GI %d "
        .. "| caches %s",
        status.last_overlays or "none", num("last_resolve"), num("last_shadow"),
        num("last_raygen"), num("last_refl"), num("last_gi"), status.cache or "?")
end

-- Compare last launch's INTENT against last launch's RESULT. Comparing against
-- the current switch positions would cry wolf every time one was just flipped.
local function warnLine()
    if not haveStatus or status.last_layer ~= "loaded" then return nil end
    if num("last_failed") > 0 then
        return string.format("WARNING: %d swap(s) failed to create last launch",
                             num("last_failed"))
    end
    if status.last_want_skin == "on" and num("last_resolve") == 0 then
        return "WARNING: the skin BRDF was on last launch but 0 compute-resolve "
            .. "swaps applied -- every visible effect lives there. Usually a "
            .. "stale pipeline cache: relaunch, or add CALLISTO_FORCE_CLEAR=1."
    end
    if status.last_want_shadowcull == "on" and num("last_shadow") == 0 then
        return "WARNING: shadow leak fix was on last launch but 0 shadow "
            .. "swaps applied."
    end
    -- "fixed" means sync_settings.sh found no parked sets, so the switch
    -- below the fix did nothing -- a silent no-op the page must not hide.
    if status.last_want_shadowcull == "on" and status.last_want_shadowset == "fixed" then
        return "NOTE: the shadow-ray build selector is inert -- no shadow sets "
            .. "are installed. Run dev/install_shadow_sets.sh to enable it."
    end
    -- The request and what was actually served differ only when the named set
    -- is not parked; sync_settings.sh falls back to `full` and says so on the
    -- terminal, but only here does the person who moved the selector find out.
    -- Both keys describe THIS launch: the set is materialized before the game
    -- starts, so unlike the hit counts they do not lag by one run.
    local req = status.want_shadowset_req
    if req and status.want_shadowset ~= "fixed" and status.want_shadowset ~= req then
        return string.format("NOTE: shadow build '%s' is not installed -- this "
            .. "launch is running '%s'. Build it with dev/build_shadow_sets.sh.",
            req, tostring(status.want_shadowset))
    end
    -- The selector disagreeing with the frame at session START means the sync
    -- never ran for this launch -- the game was started outside the Steam
    -- launch options. Cost a whole session once: the menu read "Uncull
    -- everything" while m112 was in the pipeline (`25` §9).
    if status.want_shadowset and status.want_shadowset ~= "fixed"
       and brdf.shadowset ~= status.want_shadowset then
        return string.format("WARNING: this session is running shadow build "
            .. "'%s', but the selector says '%s'. The launch did not go through "
            .. "the Steam launch options, so sync_settings.sh never ran.",
            tostring(status.want_shadowset), tostring(brdf.shadowset))
    end
    -- last_want_ptq is the MATERIALIZED combo ("rcb+skin"), not a request, so
    -- "not off" here means sync_settings.sh really did fill the overlay.
    local ptq = status.last_want_ptq
    if ptq and ptq ~= "off" and num("last_raygen") == 0 then
        return "WARNING: path-tracing quality (" .. ptq .. ") was live last "
            .. "launch but 0 raygen swaps applied -- the path tracer may not "
            .. "have run at all (RT: Overdrive off?)."
    end
    if status.last_want_ptrefl == "on" and num("last_refl") == 0 then
        return "NOTE: reflection bounce mask was on last launch but 0 "
            .. "reflection raygen swaps applied -- standalone RT reflections "
            .. "are not used in every render mode."
    end
    -- The oily-skin switch has two ways to be a silent no-op, and both look
    -- exactly like "the effect does not work" from the chair.
    if brdf.skinspec ~= "off" and status.want_skinspec == "fixed" then
        return "NOTE: oily/wet skin is inert -- no skin.set/ is parked, so "
            .. "there is nothing to switch to. Build it with "
            .. "dev/patch_compute_skin.sh --sets."
    end
    if brdf.skinspec ~= "off" and brdf.skin == "off" then
        return "NOTE: oily/wet skin is off because the Callisto skin BRDF is "
            .. "off -- the gloss rides that overlay."
    end
    -- Same trap as the shadow selector: the switch says one thing while the
    -- frame runs another, because the launch bypassed sync_settings.sh.
    -- A level mismatch, not just on-vs-off: running "subtle" while the
    -- selector reads "extreme" is the same trap and just as easy to misread.
    if status.want_skinspec and status.want_skinspec ~= "fixed"
       and status.want_skinspec ~= brdf.skinspec then
        return string.format("WARNING: this session is running skin gloss "
            .. "'%s', but the selector says '%s'. The launch did not go through "
            .. "the Steam launch options, so sync_settings.sh never ran.",
            tostring(status.want_skinspec), tostring(brdf.skinspec))
    end
    -- Transmission has a third way to be inert that the gloss does not: the
    -- combination sets only exist if --trans was passed, so a perfectly
    -- healthy skin.set/ can still have nothing to serve for this switch.
    if brdf.skintrans ~= "off" and status.want_skinspec ~= nil
       and status.want_skinspec ~= "fixed"
       and not string.find(tostring(status.want_skinspec), "+t", 1, true) then
        return "NOTE: backlit skin transmission is inert -- the combination "
            .. "sets are not built. Run dev/patch_compute_skin.sh --sets "
            .. "--trans (it crosses the two ladders)."
    end
    if brdf.skintrans ~= "off" and brdf.skin == "off" then
        return "NOTE: backlit skin transmission is off because the Callisto "
            .. "skin BRDF is off -- it rides that overlay."
    end
    return nil
end

-- What the switch label admits about itself. A switch position is a request;
-- this is the only place the page says what was actually served (`09` I6).
local function skinspecNote()
    if not haveStatus then return "" end
    if status.want_skinspec == "fixed" or status.want_skinspec == nil then
        return " [INERT: no skin.set/ parked -- run "
            .. "dev/patch_compute_skin.sh --sets]"
    end
    return string.format(" [this launch is serving: %s]",
                         tostring(status.want_skinspec))
end

-- The served name is composed ("strong+tmedium"), so the transmission half
-- has to be read back out of it rather than reported on its own.
local function skintransNote()
    if not haveStatus then return "" end
    local served = tostring(status.want_skinspec)
    if status.want_skinspec == "fixed" or status.want_skinspec == nil then
        return " [INERT: no skin.set/ parked -- run "
            .. "dev/patch_compute_skin.sh --sets --trans]"
    end
    local t = string.match(served, "%+t([%w]+)$")
    return string.format(" [this launch is serving: %s]", t or "off")
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
    -- Written once, not refreshed as switches move: nativeSettings has no label
    -- setter, and its removeSubcategory nils a slot in data[tab].keys instead of
    -- table.remove-ing it, so a remove/re-add cycle leaves a hole that the next
    -- indexed table.insert silently corrupts. The live signal is the running set
    -- in the selector's own label below, which needs no rebuild to stay true.
    local warn = warnLine()
    if warn then nativeSettings.addSubcategory("/callistoSSS/warn", warn) end
    nativeSettings.addSubcategory("/callistoSSS/main", "Skin subsurface scattering")
    nativeSettings.addSwitch("/callistoSSS/main", "Callisto skin kernel (next launch)",
        "Replace the engine's SSS diffusion kernel with the Callisto-reshaped one. "
        .. "Applies on next game launch.",
        brdf.kernel ~= "off", true,
        function(state) brdf.kernel = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/main", "Callisto skin BRDF (next launch)",
        "The tier-1 skin shading in the compute resolvers: a diffuse Fresnel "
        .. "and retroreflection term at every Disney-diffuse site, gated on "
        .. "the skin material class. This is the base layer the oily/wet "
        .. "highlight below builds on. Off restores vanilla skin shading. "
        .. "Applies on next launch."
        .. string.format(" [last launch: %d compute-resolve swaps applied]",
                         num("last_resolve")),
        brdf.skin ~= "off", true,
        function(state) brdf.skin = state and "on" or "off" saveParams() end)
    nativeSettings.addSelectorString("/callistoSSS/main",
        -- The running level goes in the LABEL, not a tooltip: a tooltip you
        -- have to hover is not where you look when the picture is wrong.
        string.format("Oily / wet skin [running: %s]",
                      status.want_skinspec or "?"),
        "A glossier specular response on skin, faces most of all: the "
        .. "Fresnel curve is broadened so the highlight builds earlier off "
        .. "straight-on angles, and skin's roughness is capped so the "
        .. "highlight stays a tight wet-looking spot instead of smearing "
        .. "into a dull sheen. Gated on the skin material class, so nothing "
        .. "else in the frame changes. "
        .. "This is the only thing that produces the look -- the engine's own "
        .. "skin CVars in the panel below cannot: they are an edge glow and a "
        .. "tint, and none of them touch the specular lobe. "
        .. "Roughness cap is the lever that matters; vanilla skin is authored "
        .. "around 0.40-0.60, so anything above ~0.40 barely bites. "
        .. "NOT a live slider and cannot be one: the values are compiled into "
        .. "the shader, so these are pre-built strengths and moving this "
        .. "changes NOTHING until you relaunch through Steam. For a value off "
        .. "the ladder, rebuild with "
        .. "dev/patch_compute_skin.sh --sets --set alpha_max=<n>. "
        .. "Needs the Callisto skin BRDF switch above on -- the gloss rides "
        .. "that overlay. Every level carries an identical tier-1 c1, so this "
        .. "changes the gloss and nothing else."
        .. skinspecNote(),
        SKIN_LABELS, SKIN_INDEX[brdf.skinspec] or 1, 1,
        function(i)
            brdf.skinspec = (SKIN_LEVELS[i] or SKIN_LEVELS[1]).id
            saveParams()
        end)
    nativeSettings.addSelectorString("/callistoSSS/main",
        string.format("Backlit skin transmission [running: %s]",
                      (haveStatus and status.want_skinspec
                       and string.match(tostring(status.want_skinspec),
                                        "%+t([%w]+)$")) or "off"),
        "Light passing THROUGH thin skin: ears, nostrils and the bridge of "
        .. "the nose go red when the sun is behind the head. The engine has "
        .. "this -- CharacterSubsurfaceTranslucency and the character light "
        .. "blockers -- but none of it reaches the path-traced frame, which "
        .. "is why faces go flat and opaque against a low sun. This adds it "
        .. "back at the skin diffuse, gated on the skin material class and on "
        .. "the light actually being behind the surface, so nothing "
        .. "front-lit and nothing that is not skin changes. "
        .. "NOT a live slider and cannot be one: the values are compiled into "
        .. "the shader, so these are pre-built strengths and moving this "
        .. "changes NOTHING until you relaunch through Steam. "
        .. "It shares its overlay with the oily/wet skin ladder above, so the "
        .. "combinations are pre-built: needs "
        .. "dev/patch_compute_skin.sh --sets --trans, and a combination that "
        .. "was never built falls back to the gloss alone. "
        .. "Extreme is a diagnostic, not a look -- it drops the "
        .. "light-is-behind-me gate so it fires on all lit skin, which "
        .. "answers whether the splice reaches the screen at all."
        .. skintransNote(),
        TRANS_LABELS, TRANS_INDEX[brdf.skintrans] or 1, 1,
        function(i)
            brdf.skintrans = (TRANS_LEVELS[i] or TRANS_LEVELS[1]).id
            saveParams()
        end)
    local function slider(label, desc, key, min, max, dflt)
        nativeSettings.addRangeFloat("/callistoSSS/brdf", label,
            desc .. " INERT: nothing reads this value. It is consumed by "
                 .. "regen_and_clear.sh, which is not in the Steam launch "
                 .. "options; sync_settings.sh does not parse it. Moving this "
                 .. "changes nothing, now or after a relaunch.",
            min, max, 0.05, "%.2f", brdf[key], dflt,
            function(v) brdf[key] = v saveParams() end)
    end
    -- The Callisto hair BRDF was removed on 2026-08-28: 70 modules of
    -- anisotropy, dual lobes, sheen and wrap that were never shown to change
    -- a pixel (19-STATUS.md). What is left under "Hair" is the shadow-leak
    -- fix, which is confirmed on screen, and the engine CVar panel below.
    nativeSettings.addSubcategory("/callistoSSS/hair", "Hair (shadows)")
    nativeSettings.addSwitch("/callistoSSS/hair", "Hair shadow leak fix (next launch)",
        "Stop shadow rays from culling back-facing triangles, so thin "
        .. "double-sided hair cards cast shadows from either side. Closes the "
        .. "overlit gap at the hairline. Turn off if you see self-shadow "
        .. "artifacts on other surfaces. Applies on next launch."
        .. string.format(" [last launch: %d shadow swaps applied]",
                         num("last_shadow")),
        brdf.shadowcull ~= "off", true,
        function(state) brdf.shadowcull = state and "on" or "off" saveParams() end)
    nativeSettings.addSelectorString("/callistoSSS/hair",
        -- The running set goes in the LABEL: a tooltip you have to hover is
        -- not where you look when the picture is wrong.
        string.format("Shadow-ray build [running: %s]",
                      status.want_shadowset or "?"),
        "Moving this changes NOTHING until you relaunch through Steam -- "
        .. "reloading a save keeps the build named in the label above, because "
        .. "the shaders were compiled at startup.\n"
        .. "WHICH rays the fix above applies to. Both drop back-face culling "
        .. "so hair casts a shadow from either side; they differ only in "
        .. "reach.\n"
        .. "\"Direct shadow rays\" is the recommended build: it closes the "
        .. "hairline seam and is the cheaper of the two. Some flat props "
        .. "still flash for a frame during LOD transitions.\n"
        .. "\"Direct + GI rays\" also unculls the bounce-lighting rays. It "
        .. "closes the same seam but flickers noticeably more, so pick it "
        .. "only if you see a difference the first option misses.\n"
        .. "Neither costs an extra ray. Needs the switch above ON. "
        .. "Applies on next launch."
        -- "running now", not "last launch": sync_settings.sh materializes the
        -- set before the game starts, so this one is not a lagging report.
        .. string.format(" [running now: %s]",
                         status.want_shadowset or "unknown"),
        SHADOW_LABELS, SHADOW_INDEX[brdf.shadowset] or 1, 1,
        function(i)
            brdf.shadowset = (SHADOW_SETS[i] or SHADOW_SETS[1]).id
            saveParams()
        end)
    nativeSettings.addSwitch("/callistoSSS/hair", "Callisto skin raygen sampling (next launch)",
        "Restore the original tier-1 raygen build (sampling-side skin BRDF). "
        .. "Applies on next launch.",
        brdf.skinray ~= "off", true,
        function(state) brdf.skinray = state and "on" or "off" saveParams() end)
    -- Path tracing. All four apply to the RT raygens, so they only do
    -- anything in a path-traced render mode; the warning line above says so
    -- when last launch swapped none.
    nativeSettings.addSubcategory("/callistoSSS/pt",
        "Path tracing (RT Overdrive)")
    nativeSettings.addSwitch("/callistoSSS/pt", "Bounce rays see hair (next launch)",
        "Bounce rays are traced with cull mask 1, which skips whole instance "
        .. "classes the primary ray hits -- hair among them. Widening it to "
        .. "255 lets indirect light actually bounce off hair (and off "
        .. "everything else the mask was hiding), so hair picks up colour "
        .. "from its surroundings and casts light back into the scene. Also "
        .. "the honest failure mode: a wider mask can let bounce rays hit "
        .. "proxy geometry the mask was there to hide. Applies on next launch."
        .. string.format(" [last launch: %d raygen swaps applied]",
                         num("last_raygen")),
        brdf.ptbounce ~= "off", true,
        function(state) brdf.ptbounce = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/pt", "Bounce rays see hair (reflections) (next launch)",
        "The same cull mask widening on the standalone RT reflection raygens. "
        .. "Separate switch because those passes are not used in every render "
        .. "mode, so this one can be inert while the one above works. "
        .. "Applies on next launch."
        .. string.format(" [last launch: %d reflection swaps applied]",
                         num("last_refl")),
        brdf.ptrefl ~= "off", true,
        function(state) brdf.ptrefl = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/pt", "Firefly clamp (indirect) (next launch)",
        "Cap what a single indirect path segment may contribute (16 units, "
        .. "well above any plausible surface and ~64x below where the pass's "
        .. "own half-float accumulator saturates). Kills the isolated bright "
        .. "specks a path tracer leaves on hair and wet surfaces. Slightly "
        .. "darkens genuinely extreme highlights. Applies on next launch.",
        brdf.ptclamp ~= "off", true,
        function(state) brdf.ptclamp = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/pt", "Rough-metal energy compensation (next launch)",
        "Single-scatter GGX throws away the light that bounces off a second "
        .. "microfacet, so rough metal renders darker than it should. This "
        .. "puts it back, scaled by how reflective the material is: up to "
        .. "+66% on rough bare metal, ~+3% on skin, cloth and plastic, and "
        .. "exactly nothing on smooth surfaces. The amount is measured from "
        .. "this game's own specular lobe rather than borrowed from a "
        .. "textbook fit -- the engine's cheap visibility term already "
        .. "recovers about half the loss by accident, so a standard fit "
        .. "would roughly double-compensate and blow out every rough metal "
        .. "surface. Deliberately does NOT touch the separate grazing-angle "
        .. "error in the same term, which is larger but is a different bug. "
        .. "Applies on next launch.",
        brdf.ptmsggx ~= "off", true,
        function(state) brdf.ptmsggx = state and "on" or "off" saveParams() end)
    nativeSettings.addSwitch("/callistoSSS/pt", "Path regularization (next launch)",
        "Force a minimum roughness (0.25) on surfaces reached by a bounce, "
        .. "never on what you see directly. Standard path-tracer trick "
        .. "(Blender's Filter Glossy, UE's r.PathTracing.Regularization): "
        .. "trades a little sharpness in reflections-of-reflections for much "
        .. "less noise in caustic-ish light. Off by default because it is a "
        .. "deliberate look change, not just a cleanup. Applies on next launch.",
        brdf.ptreg ~= "off", true,
        function(state) brdf.ptreg = state and "on" or "off" saveParams() end)
    nativeSettings.addSubcategory("/callistoSSS/brdf",
        "Callisto skin BRDF -- SLIDERS BELOW ARE NOT WIRED UP")
    nativeSettings.addSwitch("/callistoSSS/brdf", "Callisto BRDF enabled (next launch)",
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
    if hairEngine then
        local ok, err = pcall(hairEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine hair panel failed: " .. tostring(err)) end
    end
    if skinEngine then
        local ok, err = pcall(skinEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine skin panel failed: " .. tostring(err)) end
    end
end)

registerForEvent("onUpdate", function(dt)
    if hairEngine then pcall(hairEngine.onUpdate, dt) end
    if skinEngine then pcall(skinEngine.onUpdate, dt) end
end)
