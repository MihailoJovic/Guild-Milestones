-- Guild Milestones 0.2
-- Install it, play normally. The addon snapshots your guild roster (levels, classes,
-- ranks, last online, professions) and the companion app turns changes into Discord posts.

GuildMilestonesDB = GuildMilestonesDB or {}

local SCAN_INTERVAL = 60   -- seconds between roster requests
local MIN_GAP = 10         -- ignore roster events closer together than this
local lastScan = 0
local TAG = "|cff33ff99Guild Milestones|r "

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

local function ScanProfessions()
    local list = {}
    if not (GetNumGuildTradeSkill and GetGuildTradeSkillInfo) then return list end

    -- open any collapsed profession headers (bottom-up so the numbering stays valid)
    if ExpandGuildTradeSkillHeader then
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
            list[#list + 1] = table.concat({ current, full or name, skill or 0 }, "|")
        end
    end
    return list
end

local function Scan(force)
    if not IsInGuild() then return end
    local now = GetTime()
    if not force and (now - lastScan) < MIN_GAP then return end
    lastScan = now

    local members = ScanMembers()
    if #members == 0 then return end        -- roster not loaded yet: keep the last good snapshot

    local ok, profs = pcall(ScanProfessions)
    GuildMilestonesDB.version = 2
    GuildMilestonesDB.members = members
    if ok and #profs > 0 then GuildMilestonesDB.profs = profs end
    GuildMilestonesDB.entries = nil         -- old format from version 0.1
    GuildMilestonesDB.updated = time()
    GuildMilestonesDB.scanner = UnitName("player")
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("GUILD_ROSTER_UPDATE")
f:RegisterEvent("PLAYER_LOGOUT")
pcall(f.RegisterEvent, f, "GUILD_TRADESKILL_UPDATE")   -- not present on every client
f:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then
        RequestRoster()
        C_Timer.NewTicker(SCAN_INTERVAL, RequestRoster)
        C_Timer.After(6, function()
            if IsInGuild() then print(TAG .. "is tracking your guild. Type /gms for help.") end
        end)
    elseif event == "PLAYER_LOGOUT" then
        Scan(true)
    else
        Scan(false)
    end
end)

SLASH_GUILDMILESTONES1 = "/gms"
SlashCmdList["GUILDMILESTONES"] = function(msg)
    msg = (msg or ""):lower():match("^%s*(.-)%s*$")
    if msg == "save" or msg == "flush" then
        print(TAG .. "saving and reloading your UI...")
        Scan(true)
        ReloadUI()
    elseif msg == "profs" then
        if not (GetNumGuildTradeSkill and GetGuildTradeSkillInfo) then
            print(TAG .. "this client has no guild profession functions, so crafters will be skipped.")
            return
        end
        local ok, res = pcall(ScanProfessions)
        if not ok then
            print(TAG .. "profession scan error: " .. tostring(res))
        else
            print(TAG .. "raw profession rows: " .. GetNumGuildTradeSkill() .. ", crafters found: " .. #res)
            if res[1] then print("  example: " .. res[1]) end
            if #res == 0 then print("  Tip: open the Guild window (J) once, then try again.") end
        end
    elseif msg == "scan" then
        RequestRoster()
        print(TAG .. "asked the game for a fresh roster.")
    else
        local db = GuildMilestonesDB
        print(TAG .. "- it works on its own. Just play.")
        print("  Tracking " .. (db.members and #db.members or 0) .. " members, "
              .. (db.profs and #db.profs or 0) .. " profession entries.")
        print("  Last snapshot: " .. (db.updated and date("%H:%M:%S", db.updated) or "none yet"))
        print("  The file is written when you log out or reload.")
        print("  /gms save  - write it now (reloads your UI)")
        print("  /gms scan  - ask the game for a fresh roster")
        print("  /gms profs - check whether guild professions can be read")
    end
end
