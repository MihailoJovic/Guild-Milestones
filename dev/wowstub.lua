-- A small fake of the WoW API: just enough to run the addon and watch what it does.
local W = { out = {}, chat = {}, addon = {}, frames = {}, timers = {}, scripts = {}, clock = 0 }
_G.W = W

function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring((select(i, ...))) end W.out[#W.out+1] = table.concat(t, " ") end
function W.clear() W.out, W.chat, W.addon = {}, {}, {} end
function W.printed(s) for _, l in ipairs(W.out) do if l:find(s, 1, true) then return true end end return false end

local noop = function() end
local Frame = {}
Frame.__index = function(self, k)
    if Frame[k] then return Frame[k] end
    return noop
end
function Frame:SetScript(name, fn) self.scripts[name] = fn end
function Frame:RegisterEvent(ev)
    if W.unknownEvents and W.unknownEvents[ev] then error("Frame:RegisterEvent(): Unknown event: " .. ev) end
    self.events[ev] = true
end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text or "" end
function Frame:SetChecked(v) self.checked = v end
function Frame:GetChecked() return self.checked end
function Frame:ClearFocus() end
function Frame:CreateFontString() return W.newFrame("FontString") end
function Frame:CreateTexture() return W.newFrame("Texture") end
function Frame:Show() self.shown = true end
function Frame:Hide() self.shown = false end
function Frame:IsShown() return self.shown end
function W.newFrame(kind, tmpl)
    local f = setmetatable({ kind = kind, tmpl = tmpl, scripts = {}, events = {} }, Frame)
    W.frames[#W.frames+1] = f
    return f
end
function CreateFrame(kind, name, parent, tmpl) return W.newFrame(kind, tmpl) end

function W.fire(ev, ...)
    for _, f in ipairs(W.frames) do
        if f.events[ev] and f.scripts.OnEvent then f.scripts.OnEvent(f, ev, ...) end
    end
end
-- run queued C_Timer.After callbacks until none are left
C_Timer = {
    After = function(sec, fn) W.timers[#W.timers+1] = fn end,
    NewTicker = function() return {} end,
}
function W.run(maxRounds)
    for _ = 1, (maxRounds or 50) do
        if #W.timers == 0 then return end
        local batch = W.timers; W.timers = {}
        for _, fn in ipairs(batch) do fn() end
    end
end

time, date = os.time, os.date
function GetTime() W.clock = W.clock + 100 return W.clock end
W.guilded = true
function IsInGuild() return W.guilded end
W.me, W.level = "Thrall", 29
function UnitName() return W.me end
function UnitLevel() return W.level end
function GetMaxPlayerLevel() return 60 end
function SendChatMessage(text, channel) W.chat[#W.chat+1] = { text = text, channel = channel } end
C_ChatInfo = {
    RegisterAddonMessagePrefix = function(p) W.prefix = p end,
    SendAddonMessage = function(p, text, ch) W.addon[#W.addon+1] = { prefix = p, text = text, channel = ch } end,
}
SlashCmdList = {}
function ReloadUI() W.reloaded = true end
W.opened = nil
Settings = {
    RegisterCanvasLayoutCategory = function(panel, name) return { GetID = function() return 42 end, name = name } end,
    RegisterAddOnCategory = function(c) W.category = c end,
    OpenToCategory = function(id) W.opened = id end,
}

-- skills (retail style)
W.profs = {}    -- list of {name, rank}
function GetProfessions()
    local a, b, c, d, e = 1, 2, nil, nil, nil
    if #W.profs == 0 then return nil end
    return (W.profs[1] and 1 or nil), (W.profs[2] and 2 or nil)
end
function GetProfessionInfo(i) local p = W.profs[i]; return p[1], nil, p[2], 300 end

-- guild roster
W.roster = {
    { "Thrall-Realm", "Leader", 0, 60, "Shaman", "Org", "", "", true, 0, "SHAMAN" },
    { "Jaina-Realm", "Officer", 1, 29, "Mage", "Dal", "", "", false, 0, "MAGE" },
}
function GetNumGuildMembers() return #W.roster end
function GetGuildRosterInfo(i) return table.unpack(W.roster[i]) end
function C_GuildInfo_GuildRoster() end
GuildRoster = function() end

-- guild professions: header rows then crafter rows
W.gts = {
    { 1, false, 0, "Alchemy", 1, 2, 2 },
    { 1, false, 0, nil, 0, 0, 0, "Thrall", "Thrall-Realm", "Shaman", true, "Org", 150 },
    { 1, false, 0, nil, 0, 0, 0, "Jaina", "Jaina-Realm", "Mage", false, "Dal", 75 },
    { 2, false, 0, "Herbalism", 1, 1, 1 },
    { 2, false, 0, nil, 0, 0, 0, "Arthas", "Arthas-Realm", "DK", true, "X", 300 },
}
function GetNumGuildTradeSkill() return #W.gts end
function GetGuildTradeSkillInfo(i) return table.unpack(W.gts[i], 1, 13) end

-- tiny assert helper
local pass, fail = 0, 0
function check(name, cond, extra)
    if cond then pass = pass + 1 else fail = fail + 1; print_real = print_real or io.write
        io.write("FAIL: " .. name .. (extra and ("  -> " .. tostring(extra)) or "") .. "\n") end
end
function W.summary() io.write(string.format("%d passed, %d failed\n", pass, fail)); return fail end
function W.last() return W.out[#W.out] end
function W.dump() for _, l in ipairs(W.out) do io.write("   | " .. l .. "\n") end end
-- load the addon's files the way the game does: each gets the addon name and one shared table
function W.loadAddon()
    local main = os.getenv("ADDON")
    local dir = main:match("^(.*)[/%\\]") or "."
    W.ns = {}
    assert(loadfile(main))("GuildMilestones", W.ns)
    assert(loadfile(dir .. "/UI.lua"))("GuildMilestones", W.ns)
    return W.ns
end
function UnitClass() return "Shaman", "SHAMAN" end
function UnitXP() return 50 end
function UnitXPMax() return 100 end
function GetGuildInfo() return W.guildName end
RAID_CLASS_COLORS = { SHAMAN = { r = 0, g = 0.44, b = 0.87 }, MAGE = { r = 0.25, g = 0.78, b = 0.92 } }
UIParent = W.newFrame("Frame")
UISpecialFrames = {}
return W
