-- Guild Milestones 0.8.0
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

local VERSION = "0.8.0"
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
    lvlMode = "guild",                -- guild = the guild's milestone levels, every = each level, off
    lootMin = 3,                      -- -1 off, 0 any, 2 uncommon, 3 rare, 4 epic, 5 legendary
    deaths = false,
    bosses = true,
    quests = false,
    lootMsg = "{name} looted {item}!",
    deathMsg = "{name} has died in {zone}.",
    bossMsg = "{name} and friends defeated {boss}!",
    questMsg = "{name} completed {quest}.",
    levelMsg = "{name} just hit level {level}! Congrats!",
    maxMsg = "{name} just reached the level cap: level {level}!",
    tierMsg = "{name} reached {tier} in {prof}!",
}

local TIER_NAMES = { [75] = "Journeyman", [150] = "Expert", [225] = "Artisan", [300] = "Master" }

-- The guild decides WHICH milestones count. Officers set them once in the companion app; the app hands
-- them to an officer's addon, which writes a small tag like [GMS L=10,20,30 C=60 T=75,150] into the
-- Guild Info text. Everyone's addon reads that tag at login, so there is nothing to type or sync.
local guildCfg = {}                   -- L = level list, C = level cap, T = skill tiers
local GUILD_KEY = { levels = "L", maxLevel = "C", tierList = "T" }

-- ------------------------------------------------------------------ helpers
local function S(key)
    local g = GUILD_KEY[key]
    if g and guildCfg[g] ~= nil then return guildCfg[g] end
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

-- ------------------------------------------------------- guild-wide settings
local function ReadGuildConfig()
    local ok, text = pcall(function() return GetGuildInfoText and GetGuildInfoText() or "" end)
    if not ok or type(text) ~= "string" or text == "" then return end
    local body = text:match("%[GMS%s+([^%]]*)%]")
    if not body then return end
    local cfg = {}
    for k, v in body:gmatch("(%a)=([%d,%s]*)") do cfg[k] = (v:gsub("%s", "")) end
    if cfg.L or cfg.C or cfg.T then
        guildCfg = cfg
        if GuildMilestonesDB then GuildMilestonesDB.guildCfg = cfg end
    end
end

local function ConfigTag(c)
    return "[GMS L=" .. tostring(c.levels or ""):gsub("%s", "") .. " C=" .. (tonumber(c.cap) or 0)
        .. " T=" .. tostring(c.tiers or ""):gsub("%s", "") .. "]"
end

local publishedOnce = false
-- Officers only: copy the settings the companion app wrote into the guild's Info text.
local function PublishConfig(manual)
    local c = rawget(_G, "GuildMilestonesConfig")
    if type(c) ~= "table" then
        if manual then Say("No settings from the companion app yet. Open the app (Milestones tab), then /reload.") end
        return
    end
    if not IsInGuild() then return end
    if not (CanEditGuildInfo and CanEditGuildInfo()) then
        if manual then Say("Your guild rank can't edit Guild Info. An officer who can will publish the settings.") end
        return
    end
    if not (GetGuildInfoText and SetGuildInfoText) then
        if manual then Say("This client can't edit Guild Info. Paste this line into it yourself: " .. ConfigTag(c)) end
        return
    end
    local cur = GetGuildInfoText() or ""
    if cur == "" and not manual then return end      -- not loaded yet (or empty): never risk wiping real text
    local tag = ConfigTag(c)
    if cur:find(tag, 1, true) then
        if manual then Say("Guild Info already has the current settings.") end
        return
    end
    local new, n = cur:gsub("%[GMS%s[^%]]*%]", function() return tag end, 1)
    if n == 0 then new = (cur == "") and tag or (cur .. "\n" .. tag) end
    if #new > 500 then Say("Guild Info is too long to add the settings line. Shorten it a little.") return end
    local ok = pcall(SetGuildInfoText, new)
    if ok then
        publishedOnce = true
        Say("Guild milestone settings were published to Guild Info.")
    elseif manual then
        Say("Couldn't edit Guild Info from here. Paste this line into it yourself: " .. tag)
    end
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
    local mode = S("lvlMode")
    if mode == "off" then return nil end
    local vars = { name = UnitName("player"), level = level }
    local cap = MaxLevel()
    if cap and level >= cap and S("announceMax") then return Fill(S("maxMsg"), vars) end
    if mode == "every" or NumSet(S("levels"))[level] then return Fill(S("levelMsg"), vars) end
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

-- Chat-only announcements (loot, deaths, bosses, quests). Capped so a loot burst can't flood chat.
local function Chat(text, droppable)
    if not S("shout") or not IsInGuild() then return end
    if droppable and #outbox >= 5 then return end
    Shout(text)
end

-- Rich events for the companion app (item details, boss, zone...). Rows are  kind|who|time|a|b|c.
-- They are also shared with other copies of the addon, so an officer's app hears about everyone online.
local function RecordEvent(row)
    local db = GuildMilestonesDB
    db.events = db.events or {}
    db.events[#db.events + 1] = row
    while #db.events > 200 do table.remove(db.events, 1) end
end

local function Event(kind, a, b, c)
    if not IsInGuild() then return end
    local function clean(v) return (tostring(v or ""):gsub("|", "/")) end
    local row = table.concat({ kind, UnitName("player"), time(), clean(a), clean(b), clean(c) }, "|")
    if S("snapshot") then RecordEvent(row) end
    Tell("E|" .. row)
end

local QUALITY_BY_COLOR = { ["9d9d9d"] = 0, ["ffffff"] = 1, ["1eff00"] = 2, ["0070dd"] = 3, ["a335ee"] = 4, ["ff8000"] = 5 }
local QUALITY_NAME = { [0] = "Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary" }

local function LootPatterns()
    local list = {}
    for _, g in ipairs({ "LOOT_ITEM_SELF", "LOOT_ITEM_SELF_MULTIPLE", "LOOT_ITEM_PUSHED_SELF", "LOOT_ITEM_PUSHED_SELF_MULTIPLE" }) do
        local v = rawget(_G, g)
        if v then
            local pat = v:gsub("([%^%$%(%)%.%[%]%*%+%-%?])", "%%%1"):gsub("%%s", "(.+)"):gsub("%%d", "%%d+")
            list[#list + 1] = "^" .. pat .. "$"
        end
    end
    if #list == 0 then list[1] = "^You receive [%a ]-: (.+)%.$" end
    return list
end
local lootPatterns

local function OnLoot(text)
    local minQ = tonumber(S("lootMin")) or -1
    if minQ < 0 or type(text) ~= "string" then return end
    lootPatterns = lootPatterns or LootPatterns()
    local got
    for _, pat in ipairs(lootPatterns) do
        got = text:match(pat)
        if got then break end
    end
    if not got then return end
    local link = got:match("|c%x+|Hitem:.-|h%[.-%]|h|r") or got:match("|Hitem:.-|h%[.-%]|h")
    if not link then return end
    local color = link:match("|cff(%x%x%x%x%x%x)")
    local q = color and QUALITY_BY_COLOR[color:lower()]
    if not q or q < minQ then return end
    local detail = QUALITY_NAME[q]
    local ok, itemName, _, _, ilvl = pcall(GetItemInfo, link)
    if ok and tonumber(ilvl) and ilvl > 1 then detail = detail .. ", ilvl " .. ilvl else ilvl = nil end
    local id = link:match("|Hitem:(%d+)")
    Event("I", id, q .. ":" .. (ilvl or 0), (ok and itemName) or link:match("%[(.-)%]"))
    Chat(Fill(S("lootMsg"), { name = UnitName("player"), item = link }) .. " (" .. detail .. ")", true)
end

local function OnDeath()
    if not S("deaths") then return end
    local zone = (GetZoneText and GetZoneText()) or ""
    Event("D", zone)
    Chat(Fill(S("deathMsg"), { name = UnitName("player"), zone = zone ~= "" and zone or "the wilds" }), true)
end

local function OnBoss(_, name, _, size, success)
    if not S("bosses") or tonumber(success) ~= 1 or not name then return end
    Event("B", name, size)
    Chat(Fill(S("bossMsg"), { name = UnitName("player"), boss = name }))
end

local function OnQuest(questID)
    if not S("quests") then return end
    local title
    pcall(function()
        title = C_QuestLog and C_QuestLog.GetTitleForQuestID and C_QuestLog.GetTitleForQuestID(questID)
    end)
    Event("Q", title or "a quest")
    Chat(Fill(S("questMsg"), { name = UnitName("player"), quest = title or "a quest" }), true)
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
    print("  Loot:  " .. Fill(S("lootMsg"), { name = UnitName("player"), item = "[Some Item]" }) .. " (Rare, ilvl 20)")
    print("  Boss:  " .. Fill(S("bossMsg"), { name = UnitName("player"), boss = "Some Boss" }))
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
    print("  /gms guild          which milestones your guild chose")
    print("  /gms publish        (officers) put the app's milestone settings into Guild Info")
    print("  /gms crafters <p>   who in the guild crafts a profession")
    print("  /gms week           this week's guild summary (needs the companion app)")
    print("  /gms save           write the guild snapshot now (reloads your UI)")
    print("  Snapshot: " .. (db.members and #db.members or 0) .. " members, last "
          .. (db.updated and date("%H:%M:%S", db.updated) or "none yet") .. ". More: /gms scan, /gms profs")
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
    elseif cmd == "publish" then
        ReadGuildConfig()
        PublishConfig(true)
    elseif cmd == "guild" then
        ReadGuildConfig()
        if guildCfg.L or guildCfg.C or guildCfg.T then
            Say("Set by your guild: levels %s, cap %s, skill tiers %s", guildCfg.L ~= "" and guildCfg.L or "none",
                (tonumber(guildCfg.C) or 0) > 0 and guildCfg.C or "automatic", guildCfg.T ~= "" and guildCfg.T or "none")
        else
            Say("Your guild hasn't published settings, so the defaults apply: levels %s, skill tiers %s", S("levels"), S("tierList"))
        end
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

    local y = -52
    local function Heading(text)
        local fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
        fs:SetPoint("TOPLEFT", 16, y)
        fs:SetText(text)
        y = y - 30
    end

    -- A row with a label on the left and a < value > stepper on the right.
    local function Stepper(label, options, get, set)
        local fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        fs:SetPoint("TOPLEFT", 34, y)
        fs:SetText(label)
        local left = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
        left:SetSize(24, 22); left:SetPoint("TOPLEFT", 250, y + 5); left:SetText("<")
        local val = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
        val:SetPoint("TOPLEFT", 280, y)
        val:SetWidth(190)
        local right = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
        right:SetSize(24, 22); right:SetPoint("TOPLEFT", 476, y + 5); right:SetText(">")
        local function index()
            local cur = get()
            for i, o in ipairs(options) do if o[1] == cur then return i end end
            return 1
        end
        local function show() val:SetText(options[index()][2]) end
        local function step(d)
            local i = index() + d
            if i < 1 then i = #options elseif i > #options then i = 1 end
            set(options[i][1]); show()
        end
        left:SetScript("OnClick", function() step(-1) end)
        right:SetScript("OnClick", function() step(1) end)
        refreshers[#refreshers + 1] = show
        y = y - 30
    end

    local function Check(label, key)
        local cb = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
        cb:SetPoint("TOPLEFT", 28, y + 6)
        local fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        fs:SetPoint("LEFT", cb, "RIGHT", 4, 0)
        fs:SetText(label)
        cb:SetScript("OnClick", function(self) Set(key, self:GetChecked() and true or false) end)
        refreshers[#refreshers + 1] = function() cb:SetChecked(S(key) and true or false) end
        y = y - 30
    end

    local onOff = { { false, "Off" }, { true, "On" } }
    Heading("Announcements in chat (this character)")
    Stepper("Announce in", { { "OFF", "Nowhere (off)" }, { "GUILD", "Guild chat" }, { "OFFICER", "Officer chat" } },
        function() return S("shout") and S("channel") or "OFF" end,
        function(v)
            if v == "OFF" then Set("shout", false) else Set("shout", true); Set("channel", v) end
        end)
    Stepper("Level-ups", { { "guild", "Guild milestones" }, { "every", "Every level" }, { "off", "Off" } },
        function() return S("lvlMode") end, function(v) Set("lvlMode", v) end)
    Stepper("Loot", { { -1, "Off" }, { 0, "Everything" }, { 2, "Uncommon (green) or better" }, { 3, "Rare (blue) or better" },
                      { 4, "Epic (purple) or better" }, { 5, "Legendary only" } },
        function() return tonumber(S("lootMin")) or -1 end, function(v) Set("lootMin", v) end)
    Stepper("Deaths", onOff, function() return S("deaths") and true or false end, function(v) Set("deaths", v) end)
    Stepper("Boss kills", onOff, function() return S("bosses") and true or false end, function(v) Set("bosses", v) end)
    Stepper("Quest turn-ins", onOff, function() return S("quests") and true or false end, function(v) Set("quests", v) end)
    Stepper("Skill-ups", { { true, "At the guild's skill tiers" }, { false, "Off" } },
        function() return S("tiers") and true or false end, function(v) Set("tiers", v) end)

    y = y - 8
    local info = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    info:SetPoint("TOPLEFT", 34, y)
    info:SetWidth(470)
    info:SetJustifyH("LEFT")
    refreshers[#refreshers + 1] = function()
        ReadGuildConfig()
        local cap = tonumber(S("maxLevel")) or 0
        local head = guildCfg.L and "|cff33ff99Chosen by your guild:|r" or "|cffaaaaaaDefaults (your guild hasn't chosen yet):|r"
        info:SetText(head .. " levels " .. (tostring(S("levels")) ~= "" and tostring(S("levels")) or "none")
            .. ", cap " .. (cap > 0 and cap or "set by the game")
            .. ", skill tiers " .. (tostring(S("tierList")) ~= "" and tostring(S("tierList")) or "none")
            .. "\n|cffaaaaaaYour guild officers change these in the companion app.|r")
    end
    y = y - 52

    Heading("Companion app")
    Check("Keep guild data for the companion app (officers)", "snapshot")

    local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    test:SetSize(140, 24)
    test:SetPoint("TOPLEFT", 34, y - 6)
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
for _, ev in ipairs({ "GUILD_TRADESKILL_UPDATE", "SKILL_LINES_CHANGED", "CHAT_MSG_SKILL", "CHAT_MSG_ADDON",
                      "CHAT_MSG_LOOT", "PLAYER_DEAD", "ENCOUNTER_END", "QUEST_TURNED_IN" }) do
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
        guildCfg = GuildMilestonesDB.guildCfg or {}      -- last known guild settings, until the game has them
        pcall(BuildPanel)
        After(5, ReadGuildConfig)
        After(15, function() ReadGuildConfig(); if not publishedOnce then pcall(PublishConfig, false) end end)
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
    elseif event == "CHAT_MSG_LOOT" then
        OnLoot((...))
    elseif event == "PLAYER_DEAD" then
        OnDeath()
    elseif event == "ENCOUNTER_END" then
        OnBoss(...)
    elseif event == "QUEST_TURNED_IN" then
        OnQuest((...))
    elseif event == "SKILL_LINES_CHANGED" or event == "CHAT_MSG_SKILL" then
        SkillsChanged()
    elseif event == "CHAT_MSG_ADDON" then
        local prefix, text, channel, sender = ...
        if prefix == PREFIX and channel == "GUILD" and S("snapshot")
           and Short(sender) ~= Short(UnitName("player")) then
            local row = tostring(text):match("^E|(.+)$")
            local who, lvl = tostring(text):match("^L|([^|]+)|(%d+)$")
            if row then
                if row:match("^%a|[^|]+|%d+|") then RecordEvent(row) end
            elseif who then
                Record("L", who, lvl)
            else
                local w, prof, tier = tostring(text):match("^S|([^|]+)|([^|]+)|(%d+)$")
                if w then Record("S", w, prof, tier) end
            end
        end
    elseif event == "PLAYER_LOGOUT" then
        Scan(true)
    else
        ReadGuildConfig()
        Scan(false)
    end
end)
