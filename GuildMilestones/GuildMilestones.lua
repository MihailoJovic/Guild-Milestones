-- Guild Milestones 0.11.0
--
-- What it does (nothing to set up, just play):
--   * Announces YOUR OWN milestones in guild chat the moment they happen: level milestones,
--     the level cap and profession skill tiers. The official Discord <-> guild chat link
--     carries those lines to your Discord, so it is real time and needs no app.
--   * Keeps a snapshot of the guild roster for the optional companion app (officers).
--   * /gms opens the Guild Milestones window (UI.lua): your progress, the guild race, crafters,
--     the week and the settings. Guildmates' milestones pop up as small toasts.
--
-- Everything can be changed (or switched off) in the window's Settings tab.

local _, ns = ...
ns = ns or {}                         -- shared with UI.lua

GuildMilestonesDB = GuildMilestonesDB or {}

local VERSION = "0.11.0"
local PREFIX = "GMS1"                 -- hidden addon channel: lets other copies log what was announced
local TAG = "|cfff2b84bGuild Milestones|r "
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
    toasts = true,                    -- small pop-ups when a guildmate hits a milestone
    minimap = true,                   -- the GM button by the minimap
    mounts = true,                    -- announce my first mount and epic mount
    mountMsg = "{name} just got their first mount! No more walking.",
    epicMountMsg = "{name} is now riding an epic mount!",
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
    local goal = tonumber(c.goal) or 0
    local extra = ""
    if goal > 0 then
        extra = " G=" .. goal .. ((tostring(c.goaldate or ""):match("^%d+$")) and (" D=" .. c.goaldate) or "")
    end
    return "[GMS L=" .. (tostring(c.levels or ""):gsub("%s", "")) .. " C=" .. (tonumber(c.cap) or 0)
        .. " T=" .. (tostring(c.tiers or ""):gsub("%s", "")) .. extra .. "]"
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
local held = {}                       -- addon messages waiting for chat restrictions to lift
local tries = 0

-- Values the game hides from addons (Midnight's "secret values", which also apply in WoW: Forever).
local function Secret(v)
    return issecretvalue ~= nil and issecretvalue(v) and true or false
end

-- True while the game blocks addons from sending chat (e.g. during some instance encounters).
local function ChatLocked()
    local ok, locked = pcall(function()
        return C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown()
    end)
    return ok and locked == true
end

local function SendHidden(payload)
    return pcall(function()
        if C_ChatInfo and C_ChatInfo.SendAddonMessage then
            C_ChatInfo.SendAddonMessage(PREFIX, payload, "GUILD")
        elseif SendAddonMessage then
            SendAddonMessage(PREFIX, payload, "GUILD")
        end
    end)
end

local function FlushHeld()
    if ChatLocked() then return end
    while held[1] do SendHidden(table.remove(held, 1)) end
end

local function Pump()
    FlushHeld()
    local text = outbox[1]
    if not text then pumping = held[1] ~= nil; if pumping then After(10, Pump) end; return end
    if ChatLocked() then After(10, Pump); return end      -- wait it out, nothing is lost
    local channel = (S("channel") == "OFFICER") and "OFFICER" or "GUILD"
    local ok = true
    if IsInGuild() then ok = pcall(SendChatMessage, text, channel) end
    if ok or tries >= 5 then
        table.remove(outbox, 1)
        tries = 0
        After(2, Pump)                -- spaced out so a burst never trips chat throttling
    else
        tries = tries + 1             -- blocked for now: try the same line again a bit later
        After(10, Pump)
    end
end

local function Shout(text)
    outbox[#outbox + 1] = text
    if not pumping then pumping = true; After(1, Pump) end
end

local function Tell(payload)          -- hidden message to other copies of the addon
    if not IsInGuild() then return end
    if ChatLocked() then
        if #held < 50 then held[#held + 1] = payload end
        if not pumping then pumping = true; After(10, Pump) end
        return
    end
    SendHidden(payload)
end

-- A short log of what has been announced, so the companion app never posts the same thing twice.
local function Record(kind, who, a, b)
    local db = GuildMilestonesDB
    db.heard = db.heard or {}
    db.heard[#db.heard + 1] = table.concat({ Short(who), kind, tostring(a), tostring(b or ""), time() }, "|")
    while #db.heard > 300 do table.remove(db.heard, 1) end
end

-- Tell the window (UI.lua) something worth a pop-up happened. Never fatal.
local function Moment(kind, who, a, b, c)
    if ns.OnMoment and S("toasts") then pcall(ns.OnMoment, kind, who, a, b, c) end
end

local function Announce(kind, a, b, text)
    Moment(kind, UnitName("player"), a, b)
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
local GetItemInfoFn = (C_Item and C_Item.GetItemInfo) or GetItemInfo

-- Item quality: old links carry a colour (|cff0070dd), modern ones a quality code (|cnIQ3:).
-- If neither is there, ask the game.
local function ItemQuality(link)
    local color = link:match("^|cff(%x%x%x%x%x%x)")
    if color and QUALITY_BY_COLOR[color:lower()] then return QUALITY_BY_COLOR[color:lower()] end
    local iq = link:match("^|cnIQ(%d+):")
    if iq then return tonumber(iq) end
    local ok, q = pcall(function()
        if C_Item and C_Item.GetItemQualityByID then return C_Item.GetItemQualityByID(link) end
    end)
    if ok and tonumber(q) then return tonumber(q) end
    local ok2, _, _, q2 = pcall(GetItemInfoFn or GetItemInfo, link)
    if ok2 and tonumber(q2) then return tonumber(q2) end
    return nil
end
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
    if minQ < 0 or type(text) ~= "string" or Secret(text) then return end
    lootPatterns = lootPatterns or LootPatterns()
    local got
    for _, pat in ipairs(lootPatterns) do
        got = text:match(pat)
        if got then break end
    end
    if not got then return end
    local link = got:match("|c[^|]*|Hitem:.-|h%[.-%]|h|r") or got:match("|Hitem:.-|h%[.-%]|h")
    if not link then return end
    local q = ItemQuality(link)
    if not q or q < minQ then return end
    local detail = QUALITY_NAME[q] or ("Quality " .. q)
    local ok, itemName, _, _, ilvl = pcall(GetItemInfoFn or GetItemInfo, link)
    ilvl = ok and tonumber(ilvl) or nil
    if ilvl and ilvl > 1 then detail = detail .. ", ilvl " .. ilvl else ilvl = nil end
    local id = link:match("|Hitem:(%d+)")
    Event("I", id, q .. ":" .. (ilvl or 0), (ok and itemName) or link:match("%[(.-)%]"))
    Chat(Fill(S("lootMsg"), { name = UnitName("player"), item = link }) .. " (" .. detail .. ")", true)
end

local function OnDeath()
    if not S("deaths") then return end
    local zone = (GetZoneText and GetZoneText()) or ""
    Event("D", zone, UnitLevel("player"))
    Chat(Fill(S("deathMsg"), { name = UnitName("player"), zone = zone ~= "" and zone or "the wilds" }), true)
end

-- One shout per kill: the group leader's (or yours when you're on your own).
local function ShoutsForGroup()
    local ok, grouped = pcall(function() return IsInGroup and IsInGroup() end)
    if not ok or not grouped then return true end
    local ok2, lead = pcall(function() return UnitIsGroupLeader and UnitIsGroupLeader("player") end)
    return ok2 and lead and true or false
end

local function OnBoss(_, name, _, size, success)
    if not S("bosses") or tonumber(success) ~= 1 or not name or Secret(name) then return end
    Event("B", name, size)
    if ShoutsForGroup() then Chat(Fill(S("bossMsg"), { name = UnitName("player"), boss = name })) end
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

-- ------------------------------------------------------------------ mounts
-- Spotted by speed while mounted: a normal mount is 60% faster than running, an epic one 100%.
-- Works on any client, no mount list needed. Each character is celebrated once per mount tier.
local RUN_SPEED = 7

local function CheckMount()
    if not (IsMounted and IsMounted()) then return end
    local ok, speed = pcall(GetUnitSpeed, "player")
    if not ok or not tonumber(speed) or speed <= 0 then return end
    local pct = (speed / RUN_SPEED - 1) * 100
    local tier = (pct >= 90 and 2) or (pct >= 50 and 1) or 0
    if tier == 0 then return end
    local me = UnitName("player")
    local db = GuildMilestonesDB
    db.mounts = db.mounts or {}
    if (db.mounts[me] or 0) >= tier then return end
    db.mounts[me] = tier
    local kind = tier == 2 and "epic" or "mount"
    Event("M", kind, math.floor(pct + 0.5))
    Moment("M", me, kind)
    if S("mounts") then
        Chat(Fill(tier == 2 and S("epicMountMsg") or S("mountMsg"), { name = me }))
    end
end

-- ----------------------------------------------------- attunements and keys
-- The quest that finishes each attunement or key. Codes must match ATTUNEMENTS in engine.py.
local ATTUNE = {
    { code = "ony",    quests = { 6502, 6602 } },   -- Drakefire Amulet (A) / Blood of the Black Dragon Champion (H)
    { code = "mc",     quests = { 7848 } },         -- Attunement to the Core
    { code = "bwl",    quests = { 7761 } },         -- Blackhand's Command
    { code = "ubrs",   quests = { 4743 } },         -- Seal of Ascension
    { code = "scholo", quests = { 5505, 5511 } },   -- The Key to Scholomance (A / H)
    { code = "brd",    quests = { 3802 } },         -- Dark Iron Legacy (Shadowforge Key)
}
ns.ATTUNE = ATTUNE

local function QuestDone(id)
    local ok, done = pcall(function()
        if C_QuestLog and C_QuestLog.IsQuestFlaggedCompleted then return C_QuestLog.IsQuestFlaggedCompleted(id) end
        if IsQuestFlaggedCompleted then return IsQuestFlaggedCompleted(id) end
    end)
    return ok and done == true
end

-- Keep one line per person: "Name|ony,mc|time"
local function StoreRow(listKey, who, row)
    local db = GuildMilestonesDB
    db[listKey] = db[listKey] or {}
    local list = db[listKey]
    for i = #list, 1, -1 do
        if list[i]:match("^([^|]*)") == who then table.remove(list, i) end
    end
    if row then list[#list + 1] = row end
    while #list > 200 do table.remove(list, 1) end
end

local myKeys                              -- what we last told the guild, as "ony,mc"
local function CheckKeys(announce)
    local have = {}
    for _, a in ipairs(ATTUNE) do
        for _, q in ipairs(a.quests) do
            if QuestDone(q) then have[#have + 1] = a.code; break end
        end
    end
    local now = table.concat(have, ",")
    if now == myKeys then return end
    local me = UnitName("player")
    if announce and myKeys then
        local old = {}
        for c in myKeys:gmatch("[^,]+") do old[c] = true end
        for _, c in ipairs(have) do
            if not old[c] then Event("A", c); Moment("A", me, c) end
        end
    end
    myKeys = now
    StoreRow("keys", me, me .. "|" .. now .. "|" .. time())
    Tell("K|" .. me .. "|" .. now)
end
ns.CheckKeys = CheckKeys

-- ------------------------------------------------------- looking for group
-- What you're looking for (set in the window's Groups tab), shared with guildmates for 90 minutes.
local LFG_TTL = 90 * 60

function ns.SetLFG(role, wants)
    local me, db = UnitName("player"), GuildMilestonesDB
    if not role or #wants == 0 then
        db.myLfg = nil
        StoreRow("lfg", me, nil)
        Tell("G|" .. me .. "|-")
        return
    end
    local _, cls = UnitClass("player")
    db.myLfg = { role = role, wants = table.concat(wants, ","), t = time() }
    local row = table.concat({ me, UnitLevel("player"), cls or "", role, db.myLfg.wants, time() }, "|")
    StoreRow("lfg", me, row)
    Tell("G|" .. row)
end

function ns.MyLFG()
    local m = GuildMilestonesDB.myLfg
    if m and time() - (m.t or 0) < LFG_TTL then return m end
    return nil
end

function ns.GroupRows()                  -- fresh notes: { name, level, cls, role, wants = {..}, t }
    local out = {}
    for _, line in ipairs(GuildMilestonesDB.lfg or {}) do
        local n, l, c, r, w, t = line:match("^([^|]+)|(%d+)|([^|]*)|([^|]*)|([^|]*)|(%d+)$")
        if n and time() - tonumber(t) < LFG_TTL then
            local wants = {}
            for x in w:gmatch("[^,]+") do wants[#wants + 1] = x end
            out[#out + 1] = { name = n, level = tonumber(l), cls = c, role = r, wants = wants, t = tonumber(t) }
        end
    end
    table.sort(out, function(a, b) return a.t > b.t end)
    return out
end

-- -------------------------------------------------------- profession skills
local skills, skillsReady, skillTimer = {}, false, false

-- The skill list as (count, row function). WoW: Forever has C_SkillInfo in place of the old globals.
local function SkillLineSource()
    if GetNumSkillLines and GetSkillLineInfo then
        return GetNumSkillLines(), function(i)
            local name, header, _, rank = GetSkillLineInfo(i)
            return name, header, rank
        end
    end
    if C_SkillInfo and C_SkillInfo.GetNumSkillLines and C_SkillInfo.GetSkillLineInfo then
        return C_SkillInfo.GetNumSkillLines(), function(i)
            local a, b, _, d = C_SkillInfo.GetSkillLineInfo(i)
            if type(a) == "table" then
                return a.skillName or a.name, a.isHeader or a.header, a.skillRank or a.rank
            end
            return a, b, d
        end
    end
    return 0, nil
end

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
    end
    if next(out) then return out end
    local count, row = SkillLineSource()
    if not row then return out end
    local inProfessions = false
    local wanted = {}
    for _, g in ipairs({ "TRADE_SKILLS", "SECONDARY_SKILLS" }) do
        local v = rawget(_G, g)
        if v then wanted[v:lower()] = true end
    end
    for i = 1, tonumber(count) or 0 do
        local name, header, rank = row(i)
        if header then
            local h = tostring(name):lower()
            inProfessions = wanted[h] or h:find("profession", 1, true) or h:find("secondary", 1, true) or false
        elseif inProfessions and name and tonumber(rank) then
            out[name] = tonumber(rank)
        end
    end
    return out
end

local function CheckSkills(announce)
    local ok, now = pcall(ReadSkills)
    if not ok then return end
    if next(now) == nil and next(skills) ~= nil then return end     -- an empty read is a hiccup, not a reset
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
    local okG, gname = pcall(function() return GetGuildInfo and GetGuildInfo("player") end)
    db.guild = (okG and type(gname) == "string" and not Secret(gname)) and gname or nil
end

-- ---------------------------------------------------------- version notice
-- Copies of the addon tell each other their version, so an old copy can say "there's a newer one".
-- It only prints one line in your own chat window, once per session.
local function VerNum(v)
    local a, b, c = tostring(v or ""):match("^(%d+)%.(%d+)%.?(%d*)")
    if not a then return 0 end
    return tonumber(a) * 10000 + tonumber(b) * 100 + (tonumber(c) or 0)
end
local toldNewer, lastReply = false, nil

local function OnVersion(theirs, sender)
    local mine, v = VerNum(VERSION), VerNum(theirs)
    if v > mine and not toldNewer then
        toldNewer = true
        Say("A newer version (v%s) is out, and %s already has it. Grab it from the same place you got this one.",
            theirs, Short(sender))
    elseif v > 0 and v < mine and (not lastReply or GetTime() - lastReply > 600) then
        lastReply = GetTime()
        Tell("V|" .. VERSION)       -- let the older copy know (at most every 10 minutes)
    end
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

local function Help()
    local db = GuildMilestonesDB
    Say("%s  |  shouting is %s (%s)", VERSION, S("shout") and "|cff33ff99ON|r" or "|cffff5555OFF|r",
        (S("channel") == "OFFICER") and "officer chat" or "guild chat")
    print("  /gms                open the Guild Milestones window")
    print("  /gms options        the window's Settings tab")
    print("  /gms shout on|off   announce my milestones in chat")
    print("  /gms test           preview the messages, sends nothing")
    print("  /gms guild          which milestones your guild chose")
    print("  /gms publish        (officers) put the app's milestone settings into Guild Info")
    print("  /gms crafters <p>   who in the guild crafts a profession")
    print("  /gms week           this week's guild summary (needs the companion app)")
    print("  /gms save           get the guild snapshot ready (then type /reload)")
    print("  Snapshot: " .. (db.members and #db.members or 0) .. " members, last "
          .. (db.updated and date("%H:%M:%S", db.updated) or "none yet") .. ". More: /gms scan, /gms profs")
end

SLASH_GUILDMILESTONES1 = "/gms"
SLASH_GUILDMILESTONES2 = "/guildmilestones"
SlashCmdList["GUILDMILESTONES"] = function(msg)
    local cmd, rest = tostring(msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    cmd = (cmd or ""):lower()
    if cmd == "" and ns.Open then
        ns.Open()
    elseif cmd == "" or cmd == "help" or cmd == "status" then
        Help()
    elseif cmd == "options" or cmd == "settings" or cmd == "config" then
        if ns.Open then ns.Open("settings") else Help() end
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
        Scan(true)            -- ReloadUI() is blocked for addons on WoW: Forever, so the player reloads
        Say("Snapshot ready. Now type /reload so the game writes it to disk for the app.")
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

-- ------------------------------------------------- shared with the window (UI.lua)
ns.VERSION, ns.S, ns.Set, ns.Say, ns.Short, ns.NumSet = VERSION, S, Set, Say, Short, NumSet
ns.MaxLevel, ns.Preview, ns.ReadGuildConfig, ns.RequestRoster = MaxLevel, Preview, ReadGuildConfig, RequestRoster
ns.QUALITY_NAME = QUALITY_NAME
ns.CheckMount = CheckMount
function ns.GuildConfig() return guildCfg end
function ns.Professions()                -- live guild professions, or the last saved ones
    local ok, rows = pcall(ProfessionRows)
    if ok and #rows > 0 then return rows, "live" end
    rows = {}
    for _, line in ipairs(GuildMilestonesDB.profs or {}) do
        local pr, n, sk = line:match("^([^|]*)|([^|]*)|(%d+)$")
        if pr then rows[#rows + 1] = { prof = pr, name = n, skill = tonumber(sk) } end
    end
    return rows, "saved"
end

-- ------------------------------------------------------------------- events
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("PLAYER_LEVEL_UP")
f:RegisterEvent("GUILD_ROSTER_UPDATE")
f:RegisterEvent("PLAYER_LOGOUT")
for _, ev in ipairs({ "GUILD_TRADESKILL_UPDATE", "SKILL_LINES_CHANGED", "CHAT_MSG_SKILL", "CHAT_MSG_ADDON",
                      "CHAT_MSG_LOOT", "PLAYER_DEAD", "ENCOUNTER_END", "QUEST_TURNED_IN",
                      "ADDON_RESTRICTION_STATE_CHANGED" }) do
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
        if ns.BuildUI then pcall(ns.BuildUI) end
        After(5, ReadGuildConfig)
        After(15, function() ReadGuildConfig(); if not publishedOnce then pcall(PublishConfig, false) end end)
        if S("snapshot") then RequestRoster() end
        if C_Timer and C_Timer.NewTicker then
            C_Timer.NewTicker(SCAN_INTERVAL, function() if S("snapshot") then RequestRoster() end end)
        end
        After(8, function() CheckSkills(false); skillsReady = true end)   -- baseline, announces nothing
        After(20, function() Tell("V|" .. VERSION) end)                    -- for the "newer version" notice
        After(12, function() CheckKeys(false) end)                         -- tell the guild our attunements
        After(25, function()                                               -- still looking for a group? say so again
            local m = ns.MyLFG()
            if m then ns.SetLFG(m.role, (function() local t = {} for x in m.wants:gmatch("[^,]+") do t[#t + 1] = x end return t end)()) end
        end)
        pcall(function()                                                   -- Hardcore realm: deaths are shared by default
            if GuildMilestonesDB.settings.deaths == nil and C_GameRules and C_GameRules.IsHardcoreActive
               and C_GameRules.IsHardcoreActive() then
                Set("deaths", true)
            end
        end)
        if C_Timer and C_Timer.NewTicker then
            C_Timer.NewTicker(3, function() pcall(CheckMount) end)          -- mounts: a quick speed check
        end
        After(6, function()
            if ns.Welcome then pcall(ns.Welcome) end
            if IsInGuild() then
                if S("shout") then
                    Say("v%s ready. Your milestones go to %s. Type |cfff2b84b/gms|r to open the window.", VERSION,
                        (S("channel") == "OFFICER") and "officer chat" or "guild chat")
                else
                    Say("v%s ready. Announcing is OFF. Type |cfff2b84b/gms|r to open the window.", VERSION)
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
        After(2, function() CheckKeys(true) end)          -- that quest may have finished an attunement
    elseif event == "SKILL_LINES_CHANGED" or event == "CHAT_MSG_SKILL" then
        SkillsChanged()
    elseif event == "CHAT_MSG_ADDON" then
        local prefix, text, channel, sender = ...
        if Secret(prefix) or Secret(text) or Secret(sender) then return end
        local ver = prefix == PREFIX and tostring(text):match("^V|(%d+%.%d+%.?%d*)$")
        if ver then
            if Short(sender) ~= Short(UnitName("player")) then OnVersion(ver, sender) end
            return
        end
        local mine = Short(sender) == Short(UnitName("player"))
        if prefix == PREFIX and channel == "GUILD" and not mine then
            local kw, kl = tostring(text):match("^K|([^|]+)|([%a,]*)$")          -- a guildmate's attunements
            if kw then StoreRow("keys", kw, kw .. "|" .. kl .. "|" .. time()); return end
            local gw = tostring(text):match("^G|([^|]+)|%-$")                    -- stopped looking for a group
            if gw then StoreRow("lfg", gw, nil); return end
            local gn, grest = tostring(text):match("^G|([^|]+)|(%d+|[^|]*|[^|]*|[^|]*)|%d+$")
            if gn then StoreRow("lfg", gn, gn .. "|" .. grest .. "|" .. time()); return end
        end
        if prefix == PREFIX and channel == "GUILD" and not mine then
            local keep = S("snapshot")
            local row = tostring(text):match("^E|(.+)$")
            local who, lvl = tostring(text):match("^L|([^|]+)|(%d+)$")
            if row then
                local k, w, _, a, b, c = row:match("^(%a)|([^|]+)|(%d+)|([^|]*)|([^|]*)|?(.*)$")
                if k then
                    if keep then RecordEvent(row) end
                    Moment(k, w, a, b, c)
                end
            elseif who then
                if keep then Record("L", who, lvl) end
                Moment("L", who, tonumber(lvl))
            else
                local w, prof, tier = tostring(text):match("^S|([^|]+)|([^|]+)|(%d+)$")
                if w then
                    if keep then Record("S", w, prof, tier) end
                    Moment("S", w, prof, tonumber(tier))
                end
            end
        end
    elseif event == "ADDON_RESTRICTION_STATE_CHANGED" then
        if (outbox[1] or held[1]) and not pumping then pumping = true; After(1, Pump) end
    elseif event == "PLAYER_LOGOUT" then
        Scan(true)
    else
        ReadGuildConfig()
        Scan(false)
    end
end)
