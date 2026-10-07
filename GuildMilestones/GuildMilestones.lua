-- Guild Milestones 0.6.0
--
-- What it does (nothing to set up, just play):
--   * Announces YOUR OWN milestones in guild chat the moment they happen: level milestones,
--     the level cap and profession skill tiers. The official Discord <-> guild chat link
--     carries those lines to your Discord, so it is real time and needs no app.
--   * Keeps a snapshot of the guild roster for the optional companion app (officers).
--   * /gms crafters <profession> and /gms week show guild info in your chat window.
--
-- Everything can be changed (or switched off) in Options > AddOns > Guild Milestones, or with /gms.

GuildMilestonesDB = GuildMilestonesDB or {}

local VERSION = "0.6.0"
local PREFIX = "GMS1"                 -- hidden addon channel: lets other copies log what was announced
local TAG = "|cff33ff99Guild Milestones|r "
local SCAN_INTERVAL = 60              -- seconds between roster requests
local MIN_GAP = 10                    -- ignore roster events closer together than this
local lastScan = 0

local DEFAULTS = {
    shout = true,                     -- announce my own milestones in chat
    channel = "GUILD",                -- GUILD or OFFICER
    levels = "10, 20, 30, 40, 50, 60",
    maxLevel = 0,                     -- 0 = ask the game
    announceMax = true,
    tiers = true,
    tierList = "75, 150, 225, 300",
    snapshot = true,                  -- keep guild data for the companion app
    levelMsg = "{name} just hit level {level}! Congrats!",
    maxMsg = "{name} just reached the level cap: level {level}!",
    tierMsg = "{name} reached {tier} in {prof}!",
}

local TIER_NAMES = { [75] = "Journeyman", [150] = "Expert", [225] = "Artisan", [300] = "Master" }

-- ------------------------------------------------------------------ helpers
local function S(key)
    local s = GuildMilestonesDB and GuildMilestonesDB.settings
    local v = s and s[key]
    if v == nil then return DEFAULTS[key] end
    return v
end

local function Set(key, value)
    GuildMilestonesDB.settings = GuildMilestonesDB.settings or {}
    GuildMilestonesDB.settings[key] = value
end

local function Say(...) print(TAG .. string.format(...)) end

local function Short(name)
    return (tostring(name or ""):match("^([^%-]+)")) or ""
end

local function NumSet(str)
    local set = {}
    for n in tostring(str or ""):gmatch("%d+") do set[tonumber(n)] = true end
    return set
end

local function Fill(template, vars)
    return (tostring(template):gsub("{(%w+)}", function(k) return vars[k] end))
end

local function After(sec, fn)
    if C_Timer and C_Timer.After then
        C_Timer.After(sec, fn)
    else
        local f, t = CreateFrame("Frame"), 0
        f:SetScript("OnUpdate", function(self, elapsed)
            t = t + elapsed
            if t >= sec then self:SetScript("OnUpdate", nil); fn() end
        end)
    end
end

local function MaxLevel()
    local manual = tonumber(S("maxLevel")) or 0
    if manual > 0 then return manual end
    local ok, v = pcall(function() return (GetMaxPlayerLevel and GetMaxPlayerLevel()) or MAX_PLAYER_LEVEL end)
    v = ok and tonumber(v) or nil
    if v and v > 0 then return v end
    return nil
end

-- ------------------------------------------------------------- chat shouting
local outbox, pumping = {}, false

local function Pump()
    local text = table.remove(outbox, 1)
    if not text then pumping = false; return end
    local channel = (S("channel") == "OFFICER") and "OFFICER" or "GUILD"
    if IsInGuild() then pcall(SendChatMessage, text, channel) end
    After(2, Pump)                    -- spaced out so a burst never trips chat throttling
end

local function Shout(text)
    outbox[#outbox + 1] = text
    if not pumping then pumping = true; After(1, Pump) end
end

local function Tell(payload)          -- hidden message to other copies of the addon
    if not IsInGuild() then return end
    pcall(function()
        if C_ChatInfo and C_ChatInfo.SendAddonMessage then
            C_ChatInfo.SendAddonMessage(PREFIX, payload, "GUILD")
        elseif SendAddonMessage then
            SendAddonMessage(PREFIX, payload, "GUILD")
        end
    end)
end

-- A short log of what has been announced, so the companion app never posts the same thing twice.
local function Record(kind, who, a, b)
    local db = GuildMilestonesDB
    db.heard = db.heard or {}
    db.heard[#db.heard + 1] = table.concat({ Short(who), kind, tostring(a), tostring(b or ""), time() }, "|")
    while #db.heard > 300 do table.remove(db.heard, 1) end
end

local function Announce(kind, a, b, text)
    if not S("shout") or not IsInGuild() then return end
    local me = UnitName("player")
    Shout(text)
    if kind == "L" then Tell("L|" .. me .. "|" .. a) else Tell("S|" .. me .. "|" .. a .. "|" .. b) end
    if S("snapshot") then Record(kind, me, a, b) end
end

local function LevelText(level)
    local vars = { name = UnitName("player"), level = level }
    local cap = MaxLevel()
    if cap and level >= cap and S("announceMax") then return Fill(S("maxMsg"), vars) end
    if NumSet(S("levels"))[level] then return Fill(S("levelMsg"), vars) end
    return nil
end

local function TierText(prof, rank, tier)
    local label = TIER_NAMES[tier] and (TIER_NAMES[tier] .. " (" .. tier .. ")") or tostring(tier)
    return Fill(S("tierMsg"), { name = UnitName("player"), prof = prof, tier = label, skill = rank })
end

local function OnLevelUp(newLevel)
    newLevel = tonumber(newLevel) or UnitLevel("player")
    local text = LevelText(newLevel)
    if text then Announce("L", newLevel, nil, text) end
end

-- -------------------------------------------------------- profession skills
local skills, skillsReady, skillTimer = {}, false, false

local function ReadSkills()
    local out = {}
    if GetProfessions and GetProfessionInfo then
        local a, b, c, d, e = GetProfessions()
        for _, idx in ipairs({ a or false, b or false, c or false, d or false, e or false }) do
            if idx then
                local name, _, rank = GetProfessionInfo(idx)
                if name and rank then out[name] = rank end
            end
        end
    elseif GetNumSkillLines and GetSkillLineInfo then
        local inProfessions = false
        local wanted = {}
        for _, g in ipairs({ "TRADE_SKILLS", "SECONDARY_SKILLS" }) do
            local v = rawget(_G, g)
            if v then wanted[v:lower()] = true end
        end
        for i = 1, GetNumSkillLines() do
            local name, header, _, rank = GetSkillLineInfo(i)
            if header then
                local h = tostring(name):lower()
                inProfessions = wanted[h] or h:find("profession", 1, true) or h:find("secondary", 1, true) or false
            elseif inProfessions and name and rank then
                out[name] = rank
            end
        end
    end
    return out
end

local function CheckSkills(announce)
    local ok, now = pcall(ReadSkills)
    if not ok then return end
    if announce and S("tiers") then
        local tiers = NumSet(S("tierList"))
        for prof, rank in pairs(now) do
            local old = skills[prof]
            if old and rank > old then
                local top
                for t in pairs(tiers) do
                    if old < t and t <= rank and (not top or t > top) then top = t end
                end
                if top then Announce("S", prof, top, TierText(prof, rank, top)) end
            end
        end
    end
    skills = now
end

local function SkillsChanged()           -- the game fires these in bursts, so wait a moment
    if not skillsReady or skillTimer then return end
    skillTimer = true
    After(2, function() skillTimer = false; CheckSkills(true) end)
end

-- ----------------------------------------------------------- roster snapshot
local function RequestRoster()
    if not IsInGuild() then return end
    if C_GuildInfo and C_GuildInfo.GuildRoster then
        C_GuildInfo.GuildRoster()
    elseif GuildRoster then
        GuildRoster()
    end
end

local lastOnlineFn = GetGuildRosterLastOnline or (C_GuildInfo and C_GuildInfo.GetGuildRosterLastOnline)

local function DaysOffline(i)
    if not lastOnlineFn then return 0 end
    local ok, y, m, d = pcall(lastOnlineFn, i)
    if not ok or not y then return 0 end
    return (y * 365) + ((m or 0) * 30) + (d or 0)
end

local function ScanMembers()
    local list = {}
    for i = 1, GetNumGuildMembers() do
        local name, _, rank, level, _, _, _, _, online, _, class = GetGuildRosterInfo(i)
        if name and level and level > 0 then
            local off = online and 0 or DaysOffline(i)
            list[#list + 1] = table.concat({ name, level, class or "", rank or 0, off }, "|")
        end
    end
    return list
end

-- Guild professions as rows: { prof = "Alchemy", name = "Thrall-Realm", skill = 150 }
local function ProfessionRows()
    local rows = {}
    if not (GetNumGuildTradeSkill and GetGuildTradeSkillInfo) then return rows end

    if ExpandGuildTradeSkillHeader then      -- open collapsed headers (bottom-up keeps the numbering valid)
        for i = GetNumGuildTradeSkill(), 1, -1 do
            local _, collapsed, _, header = GetGuildTradeSkillInfo(i)
            if header and header ~= "" and collapsed then pcall(ExpandGuildTradeSkillHeader, i) end
        end
    end

    local current
    for i = 1, GetNumGuildTradeSkill() do
        local _, _, _, header, _, _, _, name, full, _, _, _, skill = GetGuildTradeSkillInfo(i)
        if header and header ~= "" then
            current = header
        elseif name and current then
            rows[#rows + 1] = { prof = current, name = full or name, skill = tonumber(skill) or 0 }
        end
    end
    return rows
end

local function ScanProfessions()
    local list = {}
    for _, r in ipairs(ProfessionRows()) do
        list[#list + 1] = table.concat({ r.prof, r.name, r.skill }, "|")
    end
    return list
end

local function Scan(force)
    if not S("snapshot") or not IsInGuild() then return end
    local now = GetTime()
    if not force and (now - lastScan) < MIN_GAP then return end
    lastScan = now

    local members = ScanMembers()
    if #members == 0 then return end        -- roster not loaded yet: keep the last good snapshot

    local ok, profs = pcall(ScanProfessions)
    local db = GuildMilestonesDB
    db.version = 3
    db.members = members
    if ok and #profs > 0 then db.profs = profs end
    db.entries = nil                        -- old format from version 0.1
    db.updated = time()
    db.scanner = UnitName("player")
    db.addon = VERSION
end

-- ------------------------------------------------------------ chat commands
local function ShowCrafters(query)
    query = (query or ""):lower()
    local byProf, order, source = {}, {}, "live"

    local ok, rows = pcall(ProfessionRows)
    if not ok or #rows == 0 then
        rows, source = {}, "saved"
        for _, line in ipairs(GuildMilestonesDB.profs or {}) do
            local p, n, s = line:match("^([^|]*)|([^|]*)|(%d+)$")
            if p then rows[#rows + 1] = { prof = p, name = n, skill = tonumber(s) } end
        end
    end
    if #rows == 0 then
        Say("No guild profession data yet. Open the Guild window (J) and its Professions tab once, then try again.")
        return
    end
    for _, r in ipairs(rows) do
        if not byProf[r.prof] then byProf[r.prof] = {}; order[#order + 1] = r.prof end
        table.insert(byProf[r.prof], r)
    end
    table.sort(order)

    if query == "" then
        local parts = {}
        for _, p in ipairs(order) do parts[#parts + 1] = p .. " (" .. #byProf[p] .. ")" end
        Say("Guild professions: " .. table.concat(parts, ", "))
        print("  Type /gms crafters <profession> to see who crafts it, e.g. /gms crafters alch")
        return
    end

    local found = false
    for _, p in ipairs(order) do
        if p:lower():find(query, 1, true) then
            found = true
            local list = byProf[p]
            table.sort(list, function(x, y) return x.skill > y.skill end)
            local out = {}
            for i = 1, math.min(#list, 12) do out[i] = Short(list[i].name) .. " " .. list[i].skill end
            local more = #list > 12 and (" (+" .. (#list - 12) .. " more)") or ""
            Say("%s (%d): %s%s", p, #list, table.concat(out, ", "), more)
        end
    end
    if not found then Say("Nobody in the guild list matches \"%s\". Type /gms crafters to see all professions.", query) end
    if source == "saved" then print("  (from the last saved snapshot, not live data)") end
end

local function ShowWeek()
    local w = GuildMilestonesWeek
    if type(w) ~= "table" or type(w.lines) ~= "table" or #w.lines == 0 then
        Say("No weekly summary yet. It comes from the companion app, which an officer runs. Ask them to keep it open, then /reload.")
        return
    end
    Say("%s%s", w.title or "This week", w.asof and (" (as of " .. w.asof .. ")") or "")
    for _, line in ipairs(w.lines) do print("  " .. line) end
    print("  Updated when the game loads: /reload to refresh.")
end

local function Preview()
    Say("Preview only, nothing is sent:")
    local cap = MaxLevel()
    print("  Level: " .. Fill(S("levelMsg"), { name = UnitName("player"), level = 30 }))
    if cap then print("  Cap:   " .. Fill(S("maxMsg"), { name = UnitName("player"), level = cap })) end
    print("  Skill: " .. TierText("Alchemy", 150, 150))
    print("  Channel: " .. ((S("channel") == "OFFICER") and "officer chat" or "guild chat")
          .. ", shouting is " .. (S("shout") and "ON" or "OFF"))
    print("  Level milestones: " .. tostring(S("levels")) .. "   Skill tiers: " .. tostring(S("tierList")))
end

local optionsOpen                       -- filled in by the settings panel

local function Help()
    local db = GuildMilestonesDB
    Say("%s  |  shouting is %s (%s)", VERSION, S("shout") and "|cff33ff99ON|r" or "|cffff5555OFF|r",
        (S("channel") == "OFFICER") and "officer chat" or "guild chat")
    print("  /gms options        open the settings")
    print("  /gms shout on|off   announce my milestones in chat")
    print("  /gms test           preview the messages, sends nothing")
    print("  /gms crafters <p>   who in the guild crafts a profession")
    print("  /gms week           this week's guild summary (needs the companion app)")
    print("  /gms save           write the guild snapshot now (reloads your UI)")
    print("  Snapshot: " .. (db.members and #db.members or 0) .. " members, last "
          .. (db.updated and date("%H:%M:%S", db.updated) or "none yet") .. ". More: /gms scan, /gms profs, /gms maxlevel <n>")
end

SLASH_GUILDMILESTONES1 = "/gms"
SLASH_GUILDMILESTONES2 = "/guildmilestones"
SlashCmdList["GUILDMILESTONES"] = function(msg)
    local cmd, rest = tostring(msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    cmd = (cmd or ""):lower()
    if cmd == "" or cmd == "help" or cmd == "status" then
        Help()
    elseif cmd == "options" or cmd == "settings" or cmd == "config" then
        if optionsOpen then optionsOpen() else Say("The settings panel isn't available on this client. Use the /gms commands.") end
    elseif cmd == "shout" then
        local a = rest:lower()
        if a == "on" or a == "off" then
            Set("shout", a == "on")
            Say("Shouting is now %s.", a == "on" and "ON" or "OFF")
        else
            Say("Shouting is %s. Use /gms shout on or /gms shout off.", S("shout") and "ON" or "OFF")
        end
    elseif cmd == "test" then
        Preview()
    elseif cmd == "crafters" or cmd == "crafter" then
        ShowCrafters(rest)
    elseif cmd == "week" then
        ShowWeek()
    elseif cmd == "maxlevel" then
        local n = tonumber(rest)
        if n then
            Set("maxLevel", n)
            Say("Level cap is now %s.", n > 0 and tostring(n) or "automatic")
        else
            Say("Level cap is %s. Use /gms maxlevel 60 (or 0 for automatic).", tostring(MaxLevel() or "unknown"))
        end
    elseif cmd == "save" or cmd == "flush" then
        Say("saving and reloading your UI...")
        Scan(true)
        ReloadUI()
    elseif cmd == "scan" then
        RequestRoster()
        Say("asked the game for a fresh roster.")
    elseif cmd == "profs" then
        if not (GetNumGuildTradeSkill and GetGuildTradeSkillInfo) then
            Say("this client has no guild profession functions, so crafters will be skipped.")
            return
        end
        local ok, res = pcall(ScanProfessions)
        if not ok then
            Say("profession scan error: %s", tostring(res))
        else
            Say("raw profession rows: %d, crafters found: %d", GetNumGuildTradeSkill(), #res)
            if res[1] then print("  example: " .. res[1]) end
            if #res == 0 then print("  Tip: open the Guild window (J) once, then try again.") end
        end
    else
        Help()
    end
end

-- ------------------------------------------------------------ settings panel
local function BuildPanel()
    local panel = CreateFrame("Frame")
    panel.name = "Guild Milestones"
    local refreshers = {}

    local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", 16, -16)
    title:SetText("Guild Milestones " .. VERSION)

    local sub = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    sub:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -6)
    sub:SetText("Your milestones are announced in guild chat. The Discord link carries them to your Discord.")

    local y = -64
    local function Check(label, key)
        local cb = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
        cb:SetPoint("TOPLEFT", 14, y)
        local fs = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
        fs:SetPoint("LEFT", cb, "RIGHT", 4, 0)
        fs:SetText(label)
        cb:SetScript("OnClick", function(self) Set(key, self:GetChecked() and true or false) end)
        refreshers[#refreshers + 1] = function() cb:SetChecked(S(key) and true or false) end
        y = y - 30
    end

    local function Box(label, key, width, numeric)
        local fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        fs:SetPoint("TOPLEFT", 20, y)
        fs:SetText(label)
        local eb = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
        eb:SetSize(width, 22)
        eb:SetPoint("TOPLEFT", 24, y - 18)
        eb:SetAutoFocus(false)
        eb:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
        eb:SetScript("OnEditFocusLost", function(self)
            local text = self:GetText() or ""
            if numeric then text = tonumber(text) or 0 end
            Set(key, text)
        end)
        refreshers[#refreshers + 1] = function() eb:SetText(tostring(S(key))) end
        y = y - 54
    end

    Check("Announce my milestones in chat", "shout")

    local chLabel = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    chLabel:SetPoint("TOPLEFT", 20, y)
    chLabel:SetText("Announce in")
    local chBtn = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    chBtn:SetSize(110, 24)
    chBtn:SetPoint("TOPLEFT", 110, y + 4)
    local function chRefresh() chBtn:SetText(S("channel") == "OFFICER" and "Officer chat" or "Guild chat") end
    chBtn:SetScript("OnClick", function()
        Set("channel", S("channel") == "OFFICER" and "GUILD" or "OFFICER")
        chRefresh()
    end)
    refreshers[#refreshers + 1] = chRefresh
    y = y - 38

    Box("Level milestones (numbers, separated by commas)", "levels", 300)
    Check("Announce reaching the level cap", "announceMax")
    Box("Level cap (0 = let the game decide)", "maxLevel", 80, true)
    Check("Announce profession skill tiers", "tiers")
    Box("Skill tiers", "tierList", 300)
    Box("Level message  ({name} and {level} get filled in)", "levelMsg", 380)
    Check("Keep guild data for the companion app (officers)", "snapshot")

    local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    test:SetSize(140, 24)
    test:SetPoint("TOPLEFT", 20, y - 6)
    test:SetText("Preview messages")
    test:SetScript("OnClick", Preview)

    local reset = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    reset:SetSize(140, 24)
    reset:SetPoint("LEFT", test, "RIGHT", 10, 0)
    reset:SetText("Reset to defaults")
    reset:SetScript("OnClick", function()
        GuildMilestonesDB.settings = {}
        for _, fn in ipairs(refreshers) do fn() end
        Say("settings reset to defaults.")
    end)

    local function refresh() for _, fn in ipairs(refreshers) do fn() end end
    panel:SetScript("OnShow", refresh)
    panel.refresh = refresh
    refresh()

    if Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory then
        local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)
        Settings.RegisterAddOnCategory(category)
        optionsOpen = function() Settings.OpenToCategory(category:GetID()) end
    elseif InterfaceOptions_AddCategory then
        InterfaceOptions_AddCategory(panel)
        optionsOpen = function()
            InterfaceOptionsFrame_OpenToCategory(panel)
            InterfaceOptionsFrame_OpenToCategory(panel)     -- the old frame needs it twice
        end
    end
end

-- ------------------------------------------------------------------- events
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("PLAYER_LEVEL_UP")
f:RegisterEvent("GUILD_ROSTER_UPDATE")
f:RegisterEvent("PLAYER_LOGOUT")
for _, ev in ipairs({ "GUILD_TRADESKILL_UPDATE", "SKILL_LINES_CHANGED", "CHAT_MSG_SKILL", "CHAT_MSG_ADDON" }) do
    pcall(f.RegisterEvent, f, ev)       -- not every client has every event
end

f:SetScript("OnEvent", function(_, event, ...)
    if event == "PLAYER_LOGIN" then
        GuildMilestonesDB = GuildMilestonesDB or {}
        GuildMilestonesDB.settings = GuildMilestonesDB.settings or {}
        pcall(function()
            if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
                C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)
            elseif RegisterAddonMessagePrefix then
                RegisterAddonMessagePrefix(PREFIX)
            end
        end)
        pcall(BuildPanel)
        if S("snapshot") then RequestRoster() end
        if C_Timer and C_Timer.NewTicker then
            C_Timer.NewTicker(SCAN_INTERVAL, function() if S("snapshot") then RequestRoster() end end)
        end
        After(8, function() CheckSkills(false); skillsReady = true end)   -- baseline, announces nothing
        After(6, function()
            if IsInGuild() then
                if S("shout") then
                    Say("%s ready. Your level and skill milestones go to %s. /gms options to change.", VERSION,
                        (S("channel") == "OFFICER") and "officer chat" or "guild chat")
                else
                    Say("%s ready. Announcing is OFF. /gms options to change.", VERSION)
                end
            end
        end)
    elseif event == "PLAYER_LEVEL_UP" then
        OnLevelUp(...)
    elseif event == "SKILL_LINES_CHANGED" or event == "CHAT_MSG_SKILL" then
        SkillsChanged()
    elseif event == "CHAT_MSG_ADDON" then
        local prefix, text, channel, sender = ...
        if prefix == PREFIX and channel == "GUILD" and S("snapshot")
           and Short(sender) ~= Short(UnitName("player")) then
            local who, lvl = tostring(text):match("^L|([^|]+)|(%d+)$")
            if who then
                Record("L", who, lvl)
            else
                local w, prof, tier = tostring(text):match("^S|([^|]+)|([^|]+)|(%d+)$")
                if w then Record("S", w, prof, tier) end
            end
        end
    elseif event == "PLAYER_LOGOUT" then
        Scan(true)
    else
        Scan(false)
    end
end)
