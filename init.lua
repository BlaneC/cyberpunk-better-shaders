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

-- tier is the MASTER switch for every shader swap: off forces skin and
-- shadowcull off too (sync_settings.sh does the forcing), so the layer passes
-- through bit-exact vanilla. There is no skinray key any more: the raygen-side
-- skin BRDF is sampling-only and cannot change a pixel (00-ARCHITECTURE s2).
-- The six numeric rho/n/m knobs are gone with it -- nothing ever read them.
local brdf = { tier = "1", kernel = "detail", skin = "on", shadowcull = "on",
               -- Shader execution reordering rung (handoff/41, 44). Off is
               -- the A/B control (ser.disable); class/byte/hit/class+hit are
               -- the hint variants parked in ser.set/ by dev/patch_ser.sh.
               ser = "off",
               -- Path tracing (handoff/23 tier 1). ptreg is the only one that
               -- trades look for noise, so it is the only one defaulting off.
               shadowset = "full-shadow",
               ptreg = "off", ptclamp = "on", ptbounce = "on", ptrefl = "on",
               -- T2.1 energy compensation. On by default since 2026-08-28,
               -- when it was confirmed on screen (handoff/28): it restores
               -- energy the lobe was always meant to have, so it is a fix,
               -- not a look trade. Off stays available for A/B.
               ptmsggx = "on",
               -- Phase 0.5 glass refraction (handoff/20 par5b, 76): the traced
               -- glass reflection ray repointed to the refracted direction.
               -- A ladder of pre-built raygens (the bend is an OpConstant),
               -- served THROUGH the reflection overlay above. Off by default:
               -- it REPLACES the glass reflection while it is on, and it has
               -- never been observed on screen.
               refract = "off",
               -- Callisto Tier-3 skin gloss (handoff/27 Phase 2). Off until it
               -- has been confirmed on screen; the CET skin CVar panel could
               -- not produce this look at all (`27` §4), so this is the only
               -- route to it and it has never been observed.
               -- DEFAULT CHANGED 2026-08-29 to "off": alpha_max is a roughness CEILING,
               -- and authored skin sits at roughness 0.40-0.60 (alpha 0.16-0.36), so even
               -- the mildest rung (subtle, alpha_max=0.16) clamps nearly every skin pixel
               -- to ONE constant alpha. That erases the roughness variation the artists
               -- painted (pores, creases, the oily T-zone against matte cheeks), which
               -- is exactly the "faces read soft, not like real people" complaint.
               -- See handoff/33. The ladder is kept; it is opt-in now.
               skinspec = "off" }

-- The on/off keys, as opposed to the numeric ones. Kept as a set so adding a
-- switch means adding one word, not editing a chain of `or` comparisons.
local SWITCHES = { "tier", "kernel", "skin", "shadowcull",
                   "shadowset", "skinspec",
                   "ptreg", "ptclamp", "ptbounce", "ptrefl", "ptmsggx",
                   "refract",
                   -- 44: `ser` was missing here, so saveParams() dropped it
                   -- and SER could never be selected from this page.
                   "ser" }
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
    -- the oily ladder: Fresnel reshape + roughness CEILING (flattens variation)
    { id = "subtle",  label = "Oily: subtle -- damp sheen (roughness cap 0.40)" },
    { id = "medium",  label = "Oily: medium -- clearly wet (cap 0.30)" },
    { id = "strong",  label = "Oily: strong -- unmistakably oily (cap 0.21)" },
    { id = "extreme", label = "Oily: extreme -- diagnostic, wet plastic (cap 0.14)" },
    -- 44 realism axes: roughness SCALE keeps the authored variation
    { id = "rough-1.3",   label = "Rougher x1.3 -- matte, keeps pore variation" },
    { id = "rough-1.6",   label = "Rougher x1.6 -- very matte" },
    { id = "gloss-0.7",   label = "Glossier x0.7 -- tighter highlight, keeps variation" },
    { id = "couple",      label = "Energy coupling only -- grazing skin darkens" },
    { id = "micro",       label = "Micro-shadowing only -- dark skin self-shadows" },
    { id = "eyes-wet",    label = "Wet eyes only (cornea roughness cap 0.08)" },
    { id = "eyes-glassy", label = "Glassy eyes only (cap 0.04, diagnostic)" },
    { id = "real",        label = "REAL: rougher x1.3 + coupling + micro + wet eyes" },
    { id = "real-gloss",  label = "REAL-GLOSS: glossier x0.7 + coupling + micro + wet eyes" },
    -- 53: terminator colour bleed (43 A7 kept half): the shadow edge warms --
    -- red diffuses further than green, blue less. Multiplicative, skin-gated.
    { id = "bleed",            label = "Terminator bleed only -- warm shadow edge" },
    { id = "bleed-x",          label = "Terminator bleed x3 -- diagnostic" },
    { id = "real-gloss-bleed", label = "REAL-GLOSS + terminator bleed" },
    -- 48 §8 diagnostic: hue-paints skin per GI writer family (needs ser=class)
    { id = "probe-gi",    label = "PROBE: GI writer hue paint -- ref green / GI-diff red / GI-spec blue" },
    -- 50: real-gloss + tier-1 c1 on bounce-lit skin (ReSTIR-GI diffuse; needs ser=class)
    { id = "gi-50",       label = "REAL-GLOSS + GI skin c1 at half strength" },
    { id = "gi-100",      label = "REAL-GLOSS + GI skin c1 at full strength" },
    -- 53: gi-50's raygens byte-verbatim + real-gloss-bleed compute (needs ser=class)
    { id = "gi-50-bleed",      label = "GI-50 + terminator bleed" },
    -- A3: gi-50-bleed + class-1 peach-fuzz sheen (multiplicative Charlie; needs ser=class)
    -- Kept for the record: 72 measured this form at 1.00-1.05x over the whole
    -- face, which is the "extremely subtle" the user read on screen.
    { id = "gi-50-bleed-sheen", label = "GI-50 + bleed + peach fuzz (58-era, measures near-invisible)" },
    -- 72: the oil + fuzz ladder, each rung ONE variable over gi-50-bleed.
    -- oil = the tier-3 wet-skin gloss (Fresnel reshape + roughness ceiling),
    -- fuzz = the same Charlie lobe as above but ADDED, not multiplied.
    -- 73: the fuzz lobe now cancels the module's own Schlick ramp (defres=1,
    -- peach_max 1.0 -> 0.5). The user's A/B of the 72-era build: "a bit too
    -- blown out. Losing the nicer deep red". That was the BACKLIT rim, where
    -- F reaches ~0.87 and the terminator bleed's red lives; the front-lit
    -- cheek band it did not touch is unchanged here.
    -- 74: the user's A/B of 73's candidate ("literally perfect except"):
    -- oil halved (n_s 0.60 -> 0.55, roughness cap 0.40 -> 0.45) and fuzz
    -- halved (k_peach 1.0 -> 0.5) -- both were achromatic haze on dim/indoor
    -- skin. The three rungs below are REBUILT IN PLACE at the new levels;
    -- the 73-era candidate is parked as ...-hot.
    { id = "gi-50-bleed-oil",       label = "GI-50 + bleed + HALF oil (v4 wet-skin gloss)" },
    { id = "gi-50-bleed-sheen2",    label = "GI-50 + bleed + peach fuzz v4 (half strength)" },
    { id = "gi-50-bleed-oil-sheen", label = "GI-50 + bleed + half OIL + half fuzz  <-- 74's candidate" },
    -- 74: the bounce-light track. gi-50b = gi-50's raygens + the terminator
    -- bleed ON BOUNCE LIGHT (the ReSTIR-GI diffuse ST pair's own NoL) --
    -- indoors, where bounce dominates, the rosy terminator cue no longer
    -- washes out. One variable (2 raygen files) vs the matching gi-50 rung.
    { id = "gi-50b-bleed-oil-sheen", label = "GI-50b: bounce bleed, band NOT held (74's candidate, superseded by -deep)" },
    { id = "gi-50b",                 label = "GI-50b alone (bounce bleed, no oil/fuzz) -- attribution" },
    -- 78: the terminator BAND, deeper. The mod's own stack lifts the shadow
    -- falloff ~6% above vanilla where the band reads (normalised at the lit
    -- cheek), and the bleed is the larger half of that: m_G = 1 makes the 53
    -- triple a net energy add. -lumn holds the pixel's Rec.709 luminance
    -- through the triple in BOTH halves -- hue and saturation bit-for-bit
    -- the look above, the energy add gone. -deep additionally pulls c1's
    -- grazing-LIGHT lobe to identity (rho_f 1.35 -> 1.0 direct, 1.175 -> 1.0
    -- bounce), which is the other half; it also drops the SP pair's flat
    -- E[c1] 1.078 -> 1.056, so bounce-lit skin dims ~2% overall (the one
    -- confound, pre-registered in 78 sec 5). Both went on screen 2026-08-31:
    -- -lumn at 21:04 + 22:00, KEPT ("looks 10x better"), then -deep at 22:28,
    -- which BEAT it ("deepest band is actually the best skin shader right now
    -- over lumn"). -deep is the standing rung; -lumn is the half-step back if
    -- -deep ever reads too deep (see 78 sec 5.1, 5.2).
    { id = "gi-50b-bleed-oil-sheen-deep", label = "GI-50b, bleed LUMA-NEUTRAL + c1 grazing lift off (DEEPEST BAND)  <-- STANDING (78, best on screen)" },
    { id = "gi-50b-bleed-oil-sheen-lumn", label = "  ^ half-step: bleed luma-neutral only, c1 lift kept (78, kept then superseded)" },
    -- 81: A2, the CLOTH sheen. An added Charlie x Neubelt lobe at the same
    -- 457 GGX sites the peach fuzz rides, gated on ROUGH DIELECTRICS that are
    -- neither skin (class 1, which has its own fuzz) nor hair (class 4):
    -- max3(F0) < 0.09 excludes every metal, and a ramp on the site's own
    -- alpha (0.10 -> 0.30, i.e. authored roughness 0.32 -> 0.55) excludes
    -- glass, clearcoat and polished plastic. There is NO cloth-exclusive gate
    -- in this G-buffer (80 sec 2), so concrete, plaster, wood and dirt get the
    -- lobe too, bounded -- as the grazing retroreflection they physically
    -- have and one GGX lobe does not model. Carries the energy damp 23 sec 4
    -- asked for: f_d *= 1 - k*E1*wr at all 173 Burley sites.
    -- ONE VARIABLE vs -deep (the standing rung): the compute half only.
    { id = "gi-50b-bleed-oil-sheen-deep-cloth",   label = "  + CLOTH SHEEN k=0.5 (rough dielectrics; 11-13% of local diffuse at grazing)  <-- 81's candidate" },
    { id = "gi-50b-bleed-oil-sheen-deep-clothhi", label = "  + CLOTH SHEEN k=1.0 (double; 23-25% at grazing) -- the louder half of the A/B" },
    -- 77: skin-only sample count (29 B4, unblocked by the 56 sentinel).
    -- Class-1 pixels path-trace max(RayNumber,4) spp; everything else keeps
    -- the engine count (non-skin is bit-identical to the base rung).
    -- PHOTO-MODE PRICED: ~+60-90% PT cost in face close-ups (29 B7).
    -- -spp4d retargets only the engine's own live sample loop (6 runtime-
    -- bound raygens, low risk); -spp4 also rewires the 4 constant-folded
    -- ones (77 sec 4 carries their record-store residual risk). If -spp4
    -- shows skin-only artifacts that -spp4d lacks, the baked tier is the
    -- culprit -- that attribution is the reason both rungs exist.
    { id = "gi-50b-bleed-oil-sheen-spp4d", label = "GI-50b candidate + SKIN 4spp (engine-loop half, low risk)" },
    { id = "gi-50b-bleed-oil-sheen-spp4",  label = "GI-50b candidate + SKIN 4spp (all 10 raygens)  <-- 77's candidate" },
    -- the 73-era full-strength candidate, parked for the halving A/B
    { id = "gi-50-bleed-oil-sheen-hot",  label = "  ^ 73-era FULL oil + full fuzz (too hot indoors)" },
    -- the 72-era wide builds, parked for the A/B that decides the rim (73 §6)
    { id = "gi-50-bleed-sheen2-wide",    label = "  ^ fuzz v2 wide rim (72-era, blown)" },
    { id = "gi-50-bleed-oil-sheen-wide", label = "  ^ OIL + fuzz v2 wide rim (72-era, blown)" },
    -- 59: traced-thickness ear glow (A/B vs gi-50-bleed; read handoff/59 sec 6 BEFORE launching)
    { id = "earglow-lo",  label = "Ear glow lo (traced thickness, k=0.10)" },
    { id = "earglow",     label = "Ear glow (traced thickness, k=0.22)" },
    { id = "earglow-hi",  label = "Ear glow hi (traced thickness, k=0.45)" },
    -- 55: G-U5 payload sentinel (diagnostic; read handoff/55 sec 4 BEFORE launching)
    { id = "sentinel",   label = "SENTINEL: injected-trace probe A -- magenta = trace runs" },
    { id = "sentinel-b", label = "SENTINEL-B: probe B (only if A dark) -- cyan = trace runs" },
}
local SKIN_LABELS, SKIN_INDEX = {}, {}
for i, e in ipairs(SKIN_LEVELS) do
    SKIN_LABELS[i] = e.label
    SKIN_INDEX[e.id] = i
end

-- SSS kernel presets: kernels/kernel.<id>.bin shipped next to the plugin,
-- copied over kernel.bin by sync_settings.sh (44). `off` is the engine's own
-- kernel (disable.flag) and the only true A/B control.
local KERNEL_PRESETS = {
    { id = "off",      label = "Off -- engine kernel (A/B control)" },
    { id = "detail",   label = "Detail -- tight core, most pore definition (default)" },
    { id = "balanced", label = "Balanced -- between detail and callisto" },
    { id = "callisto", label = "Callisto -- wide red tail, softest" },
    { id = "vanilla",  label = "Vanilla (re-authored) -- should match Off; a tooling check" },
    { id = "spectral", label = "Spectral -- per-channel biophysical falloff (Jensen skin1)" },
}
local KERNEL_LABELS, KERNEL_INDEX = {}, {}
for i, e in ipairs(KERNEL_PRESETS) do
    KERNEL_LABELS[i] = e.label
    KERNEL_INDEX[e.id] = i
end

-- SER hint rungs: ids must match dev/patch_ser.sh VARIANTS + ser.set/.
local SER_RUNGS = {
    { id = "off",       label = "Off -- no reorder (A/B control)" },
    { id = "class",     label = "class -- hint = material class (recommended first)" },
    { id = "byte",      label = "byte -- hint = material word low byte" },
    { id = "hit",       label = "hit -- hint = bounce hit/miss" },
    { id = "class+hit", label = "class+hit -- both" },
}
local SER_LABELS, SER_INDEX = {}, {}
for i, e in ipairs(SER_RUNGS) do
    SER_LABELS[i] = e.label
    SER_INDEX[e.id] = i
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

-- Phase 0.5 glass refraction ladder (handoff/76). Pre-built raygens parked in
-- refract.set/ by dev/build_refract.sh; the eta is an OpConstant baked at
-- build time (the inert-slider trap again), so this is a set picker, not a
-- slider. Ids must match build_refract.sh's levels.
local REFRACT_SETS = {
    { id = "off",   label = "Off -- mirror reflection (A/B control)" },
    { id = "eta15", label = "Refracted, glass n=1.5 (physical)" },
    { id = "eta20", label = "Refracted, n=2.0 (exaggerated, for A/B)" },
}
local REFRACT_LABELS, REFRACT_INDEX = {}, {}
for i, e in ipairs(REFRACT_SETS) do
    REFRACT_LABELS[i] = e.label
    REFRACT_INDEX[e.id] = i
end

local function loadParams()
    local f = io.open(PARAMS, "r")
    if not f then return end
    for line in f:lines() do
        -- Unknown keys (skinray, rho_f, skintrans... from older builds) fall
        -- through and are dropped on the next save.
        local k, v = line:match("^([%w_]+)=([%w%.%-]+)")
        if isSwitch[k] then brdf[k] = v end
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
    -- kernel was a boolean until 44; "on" means the detail preset.
    if brdf.kernel == "on" or brdf.kernel == "1" then brdf.kernel = "detail" end
    if not KERNEL_INDEX[brdf.kernel] then brdf.kernel = "detail" end
    if not SER_INDEX[brdf.ser] then brdf.ser = "off" end
end

local function saveParams()
    local f = io.open(PARAMS, "w")
    if not f then print("[CallistoSSS] cannot write brdf_params.txt") return end
    for _, k in ipairs(SWITCHES) do f:write(k .. "=" .. brdf[k] .. "\n") end
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

-- Engine path-tracer SAMPLING panel (live CVars, same pattern). This is the
-- engine-first test for "more samples where it counts": global spp/bounce
-- budgets, NOT per-material. The per-material version is handoff/29 B4 and
-- is gated on a sentinel launch first -- see pt_engine.lua's header.
local ptEngine
do
    local ok, m = pcall(require, "pt_engine")
    if not ok then ok, m = pcall(dofile, "pt_engine.lua") end
    if ok and type(m) == "table" then ptEngine = m
    else print("[CallistoSSS] pt_engine.lua not loaded: " .. tostring(m)) end
end

-- Engine DETAIL / denoiser panel (live CVars, same pattern). The answer to
-- "faces read soft / the bounce lighting is smoothed over": NRD's blur radii
-- and a-trous iterations, SHARC's cache cell size, and DLSS sharpness.
local detailEngine
do
    local ok, m = pcall(require, "detail_engine")
    if not ok then ok, m = pcall(dofile, "detail_engine.lua") end
    if ok and type(m) == "table" then detailEngine = m
    else print("[CallistoSSS] detail_engine.lua not loaded: " .. tostring(m)) end
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
-- Returns EVERY applicable warning: the silent no-ops here stack (a stale cache
-- and an unparked skin.set/ at once), and showing only the first hid the rest.
local function warnLines()
    local out = {}
    local function add(msg) out[#out + 1] = msg end
    if not haveStatus or status.last_layer ~= "loaded" then return out end
    if num("last_failed") > 0 then
        add(string.format("WARNING: %d swap(s) failed to create last launch",
                             num("last_failed")))
    end
    if status.last_want_skin == "on" and num("last_resolve") == 0 then
        add("WARNING: the skin BRDF was on last launch but 0 compute-resolve "
            .. "swaps applied -- every visible effect lives there. Usually a "
            .. "stale pipeline cache: relaunch, or add CALLISTO_FORCE_CLEAR=1.")
    end
    if status.last_want_shadowcull == "on" and num("last_shadow") == 0 then
        add("WARNING: shadow leak fix was on last launch but 0 shadow "
            .. "swaps applied.")
    end
    -- "fixed" means sync_settings.sh found no parked sets, so the switch
    -- below the fix did nothing -- a silent no-op the page must not hide.
    if status.last_want_shadowcull == "on" and status.last_want_shadowset == "fixed" then
        add("NOTE: the shadow-ray build selector is inert -- no shadow sets "
            .. "are installed. Run dev/install_shadow_sets.sh to enable it.")
    end
    -- The request and what was actually served differ only when the named set
    -- is not parked; sync_settings.sh falls back to `full` and says so on the
    -- terminal, but only here does the person who moved the selector find out.
    -- Both keys describe THIS launch: the set is materialized before the game
    -- starts, so unlike the hit counts they do not lag by one run.
    local req = status.want_shadowset_req
    if req and status.want_shadowset ~= "fixed" and status.want_shadowset ~= req then
        add(string.format("NOTE: shadow build '%s' is not installed -- this "
            .. "launch is running '%s'. Build it with dev/build_shadow_sets.sh.",
            req, tostring(status.want_shadowset)))
    end
    -- The selector disagreeing with the frame at session START means the sync
    -- never ran for this launch -- the game was started outside the Steam
    -- launch options. Cost a whole session once: the menu read "Uncull
    -- everything" while m112 was in the pipeline (`25` §9).
    if status.want_shadowset and status.want_shadowset ~= "fixed"
       and brdf.shadowset ~= status.want_shadowset then
        add(string.format("WARNING: this session is running shadow build "
            .. "'%s', but the selector says '%s'. The launch did not go through "
            .. "the Steam launch options, so sync_settings.sh never ran.",
            tostring(status.want_shadowset), tostring(brdf.shadowset)))
    end
    -- last_want_ptq is the MATERIALIZED combo ("rcb+skin"), not a request, so
    -- "not off" here means sync_settings.sh really did fill the overlay.
    local ptq = status.last_want_ptq
    if ptq and ptq ~= "off" and num("last_raygen") == 0 then
        add("WARNING: path-tracing quality (" .. ptq .. ") was live last "
            .. "launch but 0 raygen swaps applied -- the path tracer may not "
            .. "have run at all (RT: Overdrive off?).")
    end
    -- refract: want_refract is the STATE sync materialized (this launch, no
    -- lag); a refusal is encoded as off:<reason> and must not hide here.
    local rq = status.req_refract
    if rq and rq ~= "off" and status.want_refract ~= rq then
        add(string.format("NOTE: glass refraction '%s' is not running -- "
            .. "sync reported '%s'. off:rung-missing means run "
            .. "dev/build_refract.sh --install; off:needs-ptrefl means the "
            .. "reflection bounce-mask switch (or the master switch) is off.",
            rq, tostring(status.want_refract)))
    end
    -- last_want_refract comes off the cache stamp, so like the hit counts it
    -- describes LAST launch -- the right pair for last_refl.
    if status.last_want_refract and status.last_want_refract ~= "off"
       and not status.last_want_refract:find(":") and num("last_refl") == 0
       and status.last_layer == "loaded" then
        add("NOTE: glass refraction was selected last launch but 0 "
            .. "reflection raygen swaps applied -- the transparent "
            .. "reflection pass never ran (render mode without standalone "
            .. "RT reflections?), so the refraction could not have shown.")
    end
    if status.last_want_ptrefl == "on" and num("last_refl") == 0 then
        add("NOTE: reflection bounce mask was on last launch but 0 "
            .. "reflection raygen swaps applied -- standalone RT reflections "
            .. "are not used in every render mode.")
    end
    -- The oily-skin switch has two ways to be a silent no-op, and both look
    -- exactly like "the effect does not work" from the chair.
    if brdf.skinspec ~= "off" and status.want_skinspec == "fixed" then
        add("NOTE: oily/wet skin is inert -- no skin.set/ is parked, so "
            .. "there is nothing to switch to. Build it with "
            .. "dev/patch_compute_skin.sh --sets.")
    end
    if brdf.skinspec ~= "off" and brdf.skin == "off" then
        add("NOTE: oily/wet skin is off because the Callisto skin BRDF is "
            .. "off -- the gloss rides that overlay.")
    end
    -- Same trap as the shadow selector: the switch says one thing while the
    -- frame runs another, because the launch bypassed sync_settings.sh.
    -- A level mismatch, not just on-vs-off: running "subtle" while the
    -- selector reads "extreme" is the same trap and just as easy to misread.
    if status.want_skinspec and status.want_skinspec ~= "fixed"
       and status.want_skinspec ~= brdf.skinspec then
        add(string.format("WARNING: this session is running skin gloss "
            .. "'%s', but the selector says '%s'. The launch did not go through "
            .. "the Steam launch options, so sync_settings.sh never ran.",
            tostring(status.want_skinspec), tostring(brdf.skinspec)))
    end
    if brdf.ser ~= "off" and status.want_ser and status.want_ser:sub(1, 3) == "off"
       and status.want_ser ~= "off" then
        add(string.format("WARNING: SER '%s' was requested but sync disabled it: %s. "
            .. "off:stale = rebuild with ./dev/patch_ser.sh --install; "
            .. "off:rung-missing = that rung is not parked.",
            tostring(brdf.ser), tostring(status.want_ser)))
    end
    if status.want_kernel and brdf.kernel ~= status.want_kernel then
        add(string.format("NOTE: kernel preset selector says '%s' but this launch "
            .. "serves '%s' (applies on next launch through Steam).",
            tostring(brdf.kernel), tostring(status.want_kernel)))
    end
    return out
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
    for i, warn in ipairs(warnLines()) do
        nativeSettings.addSubcategory("/callistoSSS/warn" .. i, warn)
    end
    nativeSettings.addSubcategory("/callistoSSS/main", "Skin subsurface scattering")
    nativeSettings.addSwitch("/callistoSSS/main", "Callisto shader swaps -- MASTER (next launch)",
        "Off forces every shader swap below off at once -- skin BRDF, oily "
        .. "skin, hair shadow fix, all path-tracing switches, SER -- so the "
        .. "Vulkan layer passes every shader through untouched: bit-exact "
        .. "vanilla, the A/B baseline. The SSS kernel switch is engine data, "
        .. "not a shader, and is left alone. Applies on next launch.",
        brdf.tier ~= "off", true,
        function(state) brdf.tier = state and "1" or "off" saveParams() end)
    nativeSettings.addSelectorString("/callistoSSS/main",
        string.format("Callisto skin kernel [running: %s]", status.want_kernel or "?"),
        "Which SSS diffusion kernel the engine blurs skin with (the 32x8 LUT "
        .. "the RED4ext plugin swaps in at boot). Off = the engine's own "
        .. "kernel, the only true A/B control. Detail keeps the tight red "
        .. "core (pores stay crisp); Callisto has the widest red tail "
        .. "(softest, most 'glow'); Balanced sits between. Vanilla is a "
        .. "re-authored copy of the engine kernel and should be "
        .. "indistinguishable from Off -- if it is not, the tooling is wrong. "
        .. "Spectral gives each channel its own measured diffusion width (red "
        .. "widest, blue tightest) at the engine's own blur radius. "
        .. "Engine data, not a shader: unaffected by the MASTER switch. "
        .. "Applies on next launch.",
        KERNEL_LABELS, KERNEL_INDEX[brdf.kernel] or 2, 1,
        function(i)
            brdf.kernel = (KERNEL_PRESETS[i] or KERNEL_PRESETS[2]).id
            saveParams()
        end)
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
        string.format("Skin build [running: %s]",
                      status.want_skinspec or "?"),
        "Which build of the skin overlay is served. Every rung carries the "
        .. "identical tier-1 c1, so this changes ONE thing per rung. "
        .. "OILY rungs: Fresnel reshape + roughness CEILING (handoff/27) -- "
        .. "note a ceiling flattens every skin pixel to one roughness, which "
        .. "is the 'soft plastic face' complaint (33). "
        .. "ROUGHER/GLOSSIER rungs scale roughness instead, keeping the "
        .. "authored pore/T-zone variation. COUPLING darkens skin at grazing "
        .. "angles (energy conservation between diffuse and specular). "
        .. "MICRO-SHADOWING lets dark, porous skin self-shadow at grazing "
        .. "light, keyed on albedo. WET/GLASSY EYES cap the cornea's "
        .. "roughness (material class 8) and touch nothing else. "
        .. "REAL / REAL-GLOSS combine them (handoff/44, A/B script in 45). "
        .. "--- Original oily notes: A glossier specular response on skin, faces most of all: the "
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
    nativeSettings.addSelectorString("/callistoSSS/pt",
        "Glass refraction experiment (next launch)",
        "Repoints the traced glass reflection ray through the surface "
        .. "instead of off it (Snell's law at the G-buffer normal), so "
        .. "windows and glassware carry a path-traced view THROUGH the "
        .. "glass where the mirror image was. The raster see-through "
        .. "underneath is untouched, so expect the two views to stack; "
        .. "this launch answers whether that reads as real refraction "
        .. "(warping at grazing angles, magnification through curved "
        .. "glass) or as a ghosted double image. While it is on, glass "
        .. "loses its RT mirror reflection -- that is the trade being "
        .. "tested, not a bug. n=2.0 bends twice as hard as physical "
        .. "window glass; use it to find the effect, then judge n=1.5. "
        .. "Needs the reflection switch above ON. Applies on next launch."
        .. string.format(" [running now: %s]", status.want_refract or "unknown"),
        REFRACT_LABELS, REFRACT_INDEX[brdf.refract] or 1, 1,
        function(i)
            brdf.refract = (REFRACT_SETS[i] or REFRACT_SETS[1]).id
            saveParams()
        end)
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
    nativeSettings.addSelectorString("/callistoSSS/pt",
        string.format("Shader execution reordering hint [running: %s]",
                      status.want_ser or "?"),
        "Puts OpReorderThreadWithHintNV back into the twelve reference "
        .. "raygens (handoff/41): under vkd3d-proton the game asks for SER "
        .. "and never emits the instruction. Not a look change -- ONLY a "
        .. "frame-time delta proves anything; compare with the same scene, "
        .. "same settings, off vs class. The rungs differ in what the "
        .. "reorder is keyed on. Off writes ser.disable, so swaps.ptq/ "
        .. "serves the same modules minus the hint: a true single-variable "
        .. "A/B. If the running value reads off:stale, the SER build predates "
        .. "the current PT build -- rerun ./dev/patch_ser.sh --install. "
        .. "Applies on next launch.",
        SER_LABELS, SER_INDEX[brdf.ser] or 1, 1,
        function(i)
            brdf.ser = (SER_RUNGS[i] or SER_RUNGS[1]).id
            saveParams()
        end)
    if hairEngine then
        local ok, err = pcall(hairEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine hair panel failed: " .. tostring(err)) end
    end
    if skinEngine then
        local ok, err = pcall(skinEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine skin panel failed: " .. tostring(err)) end
    end
    if ptEngine then
        local ok, err = pcall(ptEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine PT sampling panel failed: " .. tostring(err)) end
    end
    if detailEngine then
        local ok, err = pcall(detailEngine.register, nativeSettings)
        if not ok then print("[CallistoSSS] engine detail panel failed: " .. tostring(err)) end
    end
end)

registerForEvent("onUpdate", function(dt)
    if hairEngine then pcall(hairEngine.onUpdate, dt) end
    if skinEngine then pcall(skinEngine.onUpdate, dt) end
    if ptEngine then pcall(ptEngine.onUpdate, dt) end
    if detailEngine then pcall(detailEngine.onUpdate, dt) end
end)
