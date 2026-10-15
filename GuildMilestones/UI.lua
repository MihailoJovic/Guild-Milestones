-- Guild Milestones: the window (/gms), the settings and the milestone toasts.
-- Flat dark panels with thin borders and one warm accent, in the style of modern UI packs.
local _, ns = ...
ns = ns or {}

local WHITE = "Interface\\Buttons\\WHITE8x8"
local C = {
    bg     = { 0.051, 0.059, 0.078, 0.96 },
    side   = { 0.071, 0.082, 0.106, 1 },
    card   = { 0.094, 0.106, 0.141, 1 },
    hover  = { 0.125, 0.141, 0.184, 1 },
    border = { 0.165, 0.184, 0.235, 1 },
    text   = { 0.91, 0.925, 0.95 },
    muted  = { 0.55, 0.58, 0.66 },
    gold   = { 0.949, 0.722, 0.294 },
    good   = { 0.24, 0.81, 0.56 },
    track  = { 0.141, 0.157, 0.204, 1 },
}
local GOLD_HEX = "|cfff2b84b"
local MUTED_HEX = "|cff8c94a8"
local QUALITY_HEX = { [0] = "9d9d9d", "ffffff", "1eff00", "0070dd", "a335ee", "ff8000" }

-- ------------------------------------------------------------------ building blocks
local function Paint(f, c, edge)
    if not f.SetBackdrop then return end
    f:SetBackdrop({ bgFile = WHITE, edgeFile = WHITE, edgeSize = 1 })
    f:SetBackdropColor(c[1], c[2], c[3], c[4] or 1)
    local e = edge or C.border
    f:SetBackdropBorderColor(e[1], e[2], e[3], e[4] or 1)
end

local function Box(parent, c, kind)
    local f = CreateFrame(kind or "Frame", nil, parent, "BackdropTemplate")
    Paint(f, c or C.card)
    return f
end

local function Text(parent, template, color, justify)
    local fs = parent:CreateFontString(nil, "OVERLAY", template or "GameFontHighlight")
    if color then fs:SetTextColor(color[1], color[2], color[3]) end
    fs:SetJustifyH(justify or "LEFT")
    return fs
end

local function Solid(parent, color, layer)
    local t = parent:CreateTexture(nil, layer or "ARTWORK")
    t:SetColorTexture(color[1], color[2], color[3], color[4] or 1)
    return t
end

local function Bar(parent, color)
    local back = Box(parent, C.track, "Frame")
    local bar = CreateFrame("StatusBar", nil, back)
    bar:SetPoint("TOPLEFT", 1, -1)
    bar:SetPoint("BOTTOMRIGHT", -1, 1)
    bar:SetStatusBarTexture(WHITE)
    local c = color or C.gold
    bar:SetStatusBarColor(c[1], c[2], c[3])
    bar:SetMinMaxValues(0, 1)
    bar:SetValue(0)
    back.bar = bar
    function back:Set(v, max, col)
        self.bar:SetMinMaxValues(0, (max and max > 0) and max or 1)
        self.bar:SetValue(v or 0)
        if col then self.bar:SetStatusBarColor(col[1], col[2], col[3]) end
    end
    return back
end

local function Button(parent, label, w, h, primary, onClick)
    local b = Box(parent, primary and C.gold or C.card, "Button")
    b:SetSize(w, h)
    local t = Text(b, "GameFontHighlightSmall", primary and { 0.12, 0.09, 0.03 } or C.text, "CENTER")
    t:SetPoint("CENTER")
    t:SetText(label)
    b.label = t
    b:SetScript("OnEnter", function(self)
        if self.SetBackdropBorderColor then self:SetBackdropBorderColor(C.gold[1], C.gold[2], C.gold[3], 1) end
    end)
    b:SetScript("OnLeave", function(self)
        if self.SetBackdropBorderColor then self:SetBackdropBorderColor(C.border[1], C.border[2], C.border[3], 1) end
    end)
    if onClick then b:SetScript("OnClick", onClick) end
    return b
end

local function ClassHex(classFile)
    local c = RAID_CLASS_COLORS and classFile and RAID_CLASS_COLORS[classFile]
    if not c then return "ffffff" end
    return string.format("%02x%02x%02x", math.floor(c.r * 255 + 0.5), math.floor(c.g * 255 + 0.5), math.floor(c.b * 255 + 0.5))
end

local function Ago(t)
    local d = time() - (tonumber(t) or time())
    if d < 60 then return "just now" end
    if d < 3600 then return math.floor(d / 60) .. "m ago" end
    if d < 86400 then return math.floor(d / 3600) .. "h ago" end
    return math.floor(d / 86400) .. "d ago"
end

-- A card: a bordered box with a small gold heading.
local function Card(parent, title)
    local c = Box(parent, C.card)
    if title then
        local h = Text(c, "GameFontNormalSmall", C.gold)
        h:SetPoint("TOPLEFT", 12, -10)
        h:SetText(string.upper(title))
        c.heading = h
    end
    return c
end

-- A pool of text lines inside a card, filled top to bottom.
local function Lines(parent, count, top, gap, template)
    local list = {}
    for i = 1, count do
        local fs = Text(parent, template or "GameFontHighlightSmall", C.text)
        fs:SetPoint("TOPLEFT", 12, top - (i - 1) * gap)
        fs:SetPoint("RIGHT", parent, "RIGHT", -12, 0)
        fs:SetWordWrap(false)
        list[i] = fs
    end
    function list:Fill(rows)
        for i, fs in ipairs(self) do fs:SetText(rows[i] or "") end
    end
    return list
end

-- ------------------------------------------------------------------ the window
local win, pages, tabs = nil, {}, {}
local PAGE_ORDER = {
    { key = "overview", label = "Overview" },
    { key = "race", label = "Guild Race" },
    { key = "crafters", label = "Crafters" },
    { key = "week", label = "This Week" },
    { key = "settings", label = "Settings" },
}

local function Show(key)
    for k, p in pairs(pages) do
        if k == key then
            p:Show()
            if p.Refresh then
                local ok, err = pcall(p.Refresh, p)
                if not ok then ns.Say("couldn't fill the %s tab: %s", k, tostring(err)) end
            end
        else
            p:Hide()
        end
    end
    for k, t in pairs(tabs) do t:SetActive(k == key) end
    win.current = key
end

-- ---------------------------------------------------- page: overview
local function RecentRows()
    local items = {}
    local db = GuildMilestonesDB or {}
    for _, line in ipairs(db.heard or {}) do
        local who, kind, a, b, t = line:match("^([^|]*)|(%a)|([^|]*)|([^|]*)|(%d+)$")
        if kind == "L" then
            items[#items + 1] = { t = tonumber(t), text = GOLD_HEX .. who .. "|r reached level |cffffffff" .. a .. "|r" }
        elseif kind == "S" then
            items[#items + 1] = { t = tonumber(t), text = GOLD_HEX .. who .. "|r reached " .. b .. " in " .. a }
        end
    end
    for _, row in ipairs(db.events or {}) do
        local k, who, t, a, b, c = row:match("^(%a)|([^|]+)|(%d+)|([^|]*)|([^|]*)|?(.*)$")
        local name = GOLD_HEX .. tostring(who) .. "|r"
        if k == "I" then
            local q = tonumber((b or ""):match("^(%d+)")) or 1
            items[#items + 1] = { t = tonumber(t), text = name .. " looted |cff" .. (QUALITY_HEX[q] or "ffffff") .. "[" .. (c ~= "" and c or "an item") .. "]|r" }
        elseif k == "B" then
            items[#items + 1] = { t = tonumber(t), text = name .. " helped defeat |cffffffff" .. a .. "|r" }
        elseif k == "D" then
            items[#items + 1] = { t = tonumber(t), text = name .. " died in " .. (a ~= "" and a or "the wilds") }
        elseif k == "Q" then
            items[#items + 1] = { t = tonumber(t), text = name .. " completed " .. a }
        end
    end
    table.sort(items, function(x, y) return (x.t or 0) > (y.t or 0) end)
    local out = {}
    for i = 1, math.min(#items, 9) do
        out[i] = items[i].text .. "  " .. MUTED_HEX .. Ago(items[i].t) .. "|r"
    end
    if #out == 0 then out[1] = MUTED_HEX .. "Nothing yet. Guild milestones show up here as they happen.|r" end
    return out
end

local function NextMilestone(level)
    local best
    for n in pairs(ns.NumSet(ns.S("levels"))) do
        if n > level and (not best or n < best) then best = n end
    end
    local cap = ns.MaxLevel and ns.MaxLevel()
    if cap and level < cap and (not best or cap < best) then best = cap end
    return best
end

local function BuildOverview(page)
    local me = Card(page, "You")
    me:SetPoint("TOPLEFT", 0, 0)
    me:SetPoint("TOPRIGHT", 0, 0)
    me:SetHeight(92)
    local name = Text(me, "GameFontNormalLarge", C.text)
    name:SetPoint("TOPLEFT", 12, -30)
    local sub = Text(me, "GameFontHighlightSmall", C.muted)
    sub:SetPoint("TOPLEFT", name, "BOTTOMLEFT", 0, -4)
    local xp = Bar(me)
    xp:SetPoint("BOTTOMLEFT", 12, 12)
    xp:SetPoint("BOTTOMRIGHT", -12, 12)
    xp:SetHeight(8)
    local status = Text(me, "GameFontHighlightSmall", C.muted, "RIGHT")
    status:SetPoint("TOPRIGHT", -12, -12)

    local feed = Card(page, "Recently in your guild")
    feed:SetPoint("TOPLEFT", me, "BOTTOMLEFT", 0, -10)
    feed:SetPoint("BOTTOMRIGHT", 0, 0)
    local rows = Lines(feed, 9, -32, 22)

    function page:Refresh()
        local lvl = UnitLevel("player") or 1
        local _, classFile = UnitClass and UnitClass("player")
        name:SetText("|cff" .. ClassHex(classFile) .. (UnitName("player") or "") .. "|r  " .. MUTED_HEX .. "level|r " .. lvl)
        local nxt = NextMilestone(lvl)
        local cur, max = (UnitXP and UnitXP("player")) or 0, (UnitXPMax and UnitXPMax("player")) or 0
        sub:SetText(nxt and ("Next milestone: " .. GOLD_HEX .. "level " .. nxt .. "|r   " .. MUTED_HEX .. "(" ..
            (nxt - lvl) .. " to go)|r") or "You're at the top. Legend.")
        xp:Set(cur, max)
        local on = ns.S("shout")
        status:SetText(on and ("Announcing in |cffffffff" .. ((ns.S("channel") == "OFFICER") and "officer" or "guild") .. " chat|r")
            or "|cffff6060Announcing is off|r")
        rows:Fill(RecentRows())
    end
end

-- ---------------------------------------------------- page: guild race
local function BuildRace(page)
    local card = Card(page, "Race to the level cap")
    card:SetAllPoints(page)
    local ROWS = 12
    local rows = {}
    for i = 1, ROWS do
        local y = -32 - (i - 1) * 24
        local r = {}
        r.rank = Text(card, "GameFontHighlightSmall", C.muted, "RIGHT")
        r.rank:SetPoint("TOPLEFT", 8, y)
        r.rank:SetWidth(22)
        r.name = Text(card, "GameFontHighlightSmall", C.text)
        r.name:SetPoint("TOPLEFT", 38, y)
        r.name:SetWidth(150)
        r.name:SetWordWrap(false)
        r.bar = Bar(card)
        r.bar:SetPoint("TOPLEFT", 196, y - 2)
        r.bar:SetPoint("RIGHT", card, "RIGHT", -48, 0)
        r.bar:SetHeight(8)
        r.level = Text(card, "GameFontHighlightSmall", C.text, "RIGHT")
        r.level:SetPoint("TOPRIGHT", -12, y)
        rows[i] = r
    end
    local total = Text(card, "GameFontHighlightSmall", C.muted)
    total:SetPoint("BOTTOMLEFT", 12, 30)
    local goal = Bar(card, C.good)
    goal:SetPoint("BOTTOMLEFT", 12, 12)
    goal:SetPoint("BOTTOMRIGHT", -12, 12)
    goal:SetHeight(10)

    function page:Refresh()
        if ns.RequestRoster then pcall(ns.RequestRoster) end
        local cap = (ns.MaxLevel and ns.MaxLevel()) or 60
        local list = {}
        local n = (IsInGuild() and GetNumGuildMembers and GetNumGuildMembers()) or 0
        for i = 1, n do
            local nm, _, _, lvl, _, _, _, _, online, _, cls = GetGuildRosterInfo(i)
            if nm and lvl and lvl > 0 then list[#list + 1] = { name = ns.Short(nm), level = lvl, cls = cls, online = online } end
        end
        table.sort(list, function(a, b) if a.level ~= b.level then return a.level > b.level end return a.name < b.name end)
        local sum, top = 0, 0
        for _, m in ipairs(list) do sum = sum + m.level; if m.level >= cap then top = top + 1 end end
        for i, r in ipairs(rows) do
            local m = list[i]
            if m then
                local medal = (i == 1 and GOLD_HEX) or (i == 2 and "|cffc9d1dc") or (i == 3 and "|cffd08a4e") or MUTED_HEX
                r.rank:SetText(medal .. i .. ".|r")
                r.name:SetText("|cff" .. ClassHex(m.cls) .. m.name .. "|r" .. (m.online and " |cff3ccf8e•|r" or ""))
                r.level:SetText(m.level >= cap and (GOLD_HEX .. m.level .. "|r") or tostring(m.level))
                r.bar:Set(m.level, cap, m.level >= cap and C.gold or C.good)
                r.bar:Show()
            else
                r.rank:SetText(""); r.name:SetText(""); r.level:SetText(""); r.bar:Hide()
            end
        end
        if #list == 0 then
            rows[1].name:SetText(MUTED_HEX .. "Join a guild to see the race.|r")
        end
        total:SetText(string.format("Guild progress: %s%d|r of %d levels   ·   %s%d|r of %d at %d   ·   %d members",
            GOLD_HEX, sum, cap * #list, GOLD_HEX, top, #list, cap, #list))
        goal:Set(sum, cap * math.max(#list, 1))
    end
end

-- ---------------------------------------------------- page: crafters
local function BuildCrafters(page)
    local chips = CreateFrame("Frame", nil, page)
    chips:SetPoint("TOPLEFT", 0, 0)
    chips:SetPoint("TOPRIGHT", 0, 0)
    chips:SetHeight(56)
    local chipButtons = {}
    for i = 1, 10 do
        local b = Button(chips, "", 92, 22, false)
        b:SetPoint("TOPLEFT", ((i - 1) % 5) * 98, -math.floor((i - 1) / 5) * 28)
        b:Hide()
        chipButtons[i] = b
    end
    local card = Card(page, "Crafters")
    card:SetPoint("TOPLEFT", chips, "BOTTOMLEFT", 0, -6)
    card:SetPoint("BOTTOMRIGHT", 0, 0)
    local ROWS = 11
    local rows = {}
    for i = 1, ROWS do
        local y = -32 - (i - 1) * 24
        local r = {}
        r.name = Text(card, "GameFontHighlightSmall", C.text)
        r.name:SetPoint("TOPLEFT", 12, y)
        r.name:SetWidth(170)
        r.bar = Bar(card)
        r.bar:SetPoint("TOPLEFT", 190, y - 2)
        r.bar:SetPoint("RIGHT", card, "RIGHT", -52, 0)
        r.bar:SetHeight(8)
        r.skill = Text(card, "GameFontHighlightSmall", C.text, "RIGHT")
        r.skill:SetPoint("TOPRIGHT", -12, y)
        rows[i] = r
    end
    local note = Text(card, "GameFontHighlightSmall", C.muted)
    note:SetPoint("BOTTOMLEFT", 12, 10)
    page.selected = nil

    function page:Refresh()
        local data, source = ns.Professions()
        local by, order = {}, {}
        for _, r in ipairs(data) do
            if not by[r.prof] then by[r.prof] = {}; order[#order + 1] = r.prof end
            table.insert(by[r.prof], r)
        end
        table.sort(order)
        if not by[self.selected or ""] then self.selected = order[1] end
        for i, b in ipairs(chipButtons) do
            local p = order[i]
            if p then
                b.label:SetText(p .. " " .. MUTED_HEX .. #by[p] .. "|r")
                local active = p == self.selected
                Paint(b, active and C.hover or C.card, active and C.gold or nil)
                b:SetScript("OnClick", function() self.selected = p; self:Refresh() end)
                b:Show()
            else
                b:Hide()
            end
        end
        local list = by[self.selected or ""] or {}
        table.sort(list, function(x, y) return x.skill > y.skill end)
        for i, r in ipairs(rows) do
            local m = list[i]
            if m then
                r.name:SetText(ns.Short(m.name)); r.skill:SetText(tostring(m.skill)); r.bar:Set(m.skill, 300); r.bar:Show()
            else
                r.name:SetText(""); r.skill:SetText(""); r.bar:Hide()
            end
        end
        if #data == 0 then
            rows[1].name:SetText(MUTED_HEX .. "No profession data yet.|r")
            note:SetText("Open the Guild window (J) and its Professions tab once, then come back.")
        else
            note:SetText(source == "saved" and "From the last saved snapshot." or (#list > ROWS and ("+" .. (#list - ROWS) .. " more") or ""))
        end
    end
end

-- ---------------------------------------------------- page: this week
local function BuildWeek(page)
    local card = Card(page, "This week in the guild")
    card:SetAllPoints(page)
    local title = Text(card, "GameFontNormalLarge", C.text)
    title:SetPoint("TOPLEFT", 12, -30)
    local rows = Lines(card, 12, -60, 22)
    function page:Refresh()
        local w = GuildMilestonesWeek
        if type(w) == "table" and type(w.lines) == "table" and #w.lines > 0 then
            title:SetText((w.title or "This week") .. (w.asof and ("  " .. MUTED_HEX .. "as of " .. w.asof .. "|r") or ""))
            local out = {}
            for i, line in ipairs(w.lines) do
                local head, rest = line:match("^([^:]+):%s*(.*)$")
                out[i] = head and (GOLD_HEX .. head .. "|r  " .. rest) or line
            end
            rows:Fill(out)
        else
            title:SetText("No weekly summary here yet")
            rows:Fill({ MUTED_HEX .. "The weekly summary comes from the companion app that an officer runs.|r",
                        MUTED_HEX .. "Everyone sees it in Discord. Officers also see it here after a /reload.|r" })
        end
    end
end

-- ---------------------------------------------------- page: settings
local ON_OFF = { { false, "Off" }, { true, "On" } }
local SETTINGS = {
    { key = "announce", label = "Announce my milestones in",
      options = { { "OFF", "Nowhere (off)" }, { "GUILD", "Guild chat" }, { "OFFICER", "Officer chat" } },
      get = function() return ns.S("shout") and ns.S("channel") or "OFF" end,
      set = function(v) if v == "OFF" then ns.Set("shout", false) else ns.Set("shout", true); ns.Set("channel", v) end end },
    { key = "lvlMode", label = "Level-ups",
      options = { { "guild", "Guild's milestones" }, { "every", "Every level" }, { "off", "Off" } } },
    { key = "lootMin", label = "Loot",
      options = { { -1, "Off" }, { 0, "Everything" }, { 2, "Green or better" }, { 3, "Blue or better" },
                  { 4, "Purple or better" }, { 5, "Legendary only" } } },
    { key = "bosses", label = "Boss kills", options = ON_OFF },
    { key = "deaths", label = "Deaths", options = ON_OFF },
    { key = "quests", label = "Quest turn-ins", options = ON_OFF },
    { key = "tiers", label = "Profession skill tiers", options = { { true, "At the guild's tiers" }, { false, "Off" } } },
    { key = "toasts", label = "Pop-ups for guildmates", options = ON_OFF },
    { key = "snapshot", label = "Keep data for the app", options = ON_OFF },
}

local function BuildSettings(page)
    local card = Card(page, "What you share")
    card:SetPoint("TOPLEFT", 0, 0)
    card:SetPoint("TOPRIGHT", 0, 0)
    card:SetHeight(32 + #SETTINGS * 28 + 4)
    page.selectors = {}
    local refreshers = {}
    for i, def in ipairs(SETTINGS) do
        local y = -32 - (i - 1) * 28
        local label = Text(card, "GameFontHighlightSmall", C.text)
        label:SetPoint("TOPLEFT", 12, y - 4)
        label:SetText(def.label)
        local get = def.get or function()
            local v = ns.S(def.key)
            if type(def.options[1][1]) == "boolean" then return v and true or false end
            if type(def.options[1][1]) == "number" then return tonumber(v) or -1 end
            return v
        end
        local set = def.set or function(v) ns.Set(def.key, v) end
        local holder = Box(card, C.side)
        holder:SetSize(220, 22)
        holder:SetPoint("TOPRIGHT", -12, y)
        local value = Text(holder, "GameFontHighlightSmall", C.text, "CENTER")
        value:SetPoint("CENTER")
        local function index()
            local cur = get()
            for j, o in ipairs(def.options) do if o[1] == cur then return j end end
            return 1
        end
        local function show()
            local o = def.options[index()]
            local off = o[1] == false or o[1] == -1 or o[1] == "OFF" or o[1] == "off"
            value:SetText((off and MUTED_HEX or "|cffffffff") .. o[2] .. "|r")
        end
        local function step(d)
            local j = index() + d
            if j < 1 then j = #def.options elseif j > #def.options then j = 1 end
            set(def.options[j][1]); show()
        end
        local left = Button(holder, "<", 22, 22, false, function() step(-1) end)
        left:SetPoint("LEFT", 0, 0)
        local right = Button(holder, ">", 22, 22, false, function() step(1) end)
        right:SetPoint("RIGHT", 0, 0)
        page.selectors[def.key] = { step = step, show = show }
        refreshers[#refreshers + 1] = show
    end

    local guild = Card(page, "Chosen by your guild")
    guild:SetPoint("TOPLEFT", card, "BOTTOMLEFT", 0, -10)
    guild:SetPoint("BOTTOMRIGHT", 0, 40)
    local info = Text(guild, "GameFontHighlightSmall", C.text)
    info:SetPoint("TOPLEFT", 12, -30)
    info:SetPoint("RIGHT", guild, "RIGHT", -12, 0)

    local preview = Button(page, "Preview my messages", 160, 26, false, function() ns.Preview() end)
    preview:SetPoint("BOTTOMLEFT", 0, 0)
    local reset = Button(page, "Reset to defaults", 140, 26, false, function()
        GuildMilestonesDB.settings = {}
        page:Refresh()
        ns.Say("settings reset to defaults.")
    end)
    reset:SetPoint("LEFT", preview, "RIGHT", 8, 0)

    function page:Refresh()
        for _, fn in ipairs(refreshers) do fn() end
        if ns.ReadGuildConfig then pcall(ns.ReadGuildConfig) end
        local g = ns.GuildConfig and ns.GuildConfig() or {}
        local cap = tonumber(ns.S("maxLevel")) or 0
        info:SetText((g.L and "" or (MUTED_HEX .. "Your guild hasn't chosen yet, so these defaults apply.|r\n")) ..
            "Level milestones: " .. GOLD_HEX .. (tostring(ns.S("levels")) ~= "" and tostring(ns.S("levels")) or "none") .. "|r\n" ..
            "Level cap: " .. GOLD_HEX .. (cap > 0 and cap or "set by the game") .. "|r\n" ..
            "Skill tiers: " .. GOLD_HEX .. (tostring(ns.S("tierList")) ~= "" and tostring(ns.S("tierList")) or "none") .. "|r\n" ..
            MUTED_HEX .. "Officers change these in the companion app.|r")
    end
end

-- ---------------------------------------------------- the frame itself
local function BuildWindow()
    win = Box(UIParent, C.bg)
    win:SetSize(680, 470)
    win:SetPoint("CENTER")
    win:SetFrameStrata("HIGH")
    win:SetMovable(true)
    win:EnableMouse(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", function(self) self:StartMoving() end)
    win:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
    win:SetClampedToScreen(true)
    win:Hide()
    _G.GuildMilestonesWindow = win
    if UISpecialFrames then table.insert(UISpecialFrames, "GuildMilestonesWindow") end   -- Esc closes it

    local accent = Solid(win, C.gold)
    accent:SetPoint("TOPLEFT", 1, -1)
    accent:SetPoint("TOPRIGHT", -1, -1)
    accent:SetHeight(2)

    local side = Box(win, C.side)
    side:SetPoint("TOPLEFT", 1, -3)
    side:SetPoint("BOTTOMLEFT", 1, 1)
    side:SetWidth(150)
    if side.SetBackdropBorderColor then side:SetBackdropBorderColor(0, 0, 0, 0) end

    local logo = Text(side, "GameFontNormalLarge", C.gold)
    logo:SetPoint("TOPLEFT", 14, -16)
    logo:SetText("Guild")
    local logo2 = Text(side, "GameFontNormalLarge", C.text)
    logo2:SetPoint("TOPLEFT", logo, "BOTTOMLEFT", 0, -2)
    logo2:SetText("Milestones")
    local ver = Text(side, "GameFontDisableSmall", C.muted)
    ver:SetPoint("TOPLEFT", logo2, "BOTTOMLEFT", 0, -4)
    ver:SetText("v" .. ns.VERSION)

    for i, def in ipairs(PAGE_ORDER) do
        local t = CreateFrame("Button", nil, side)
        t:SetSize(150, 30)
        t:SetPoint("TOPLEFT", 0, -92 - (i - 1) * 32)
        local hl = Solid(t, C.hover, "BACKGROUND")
        hl:SetAllPoints()
        hl:Hide()
        local bar = Solid(t, C.gold)
        bar:SetPoint("TOPLEFT", 0, 0)
        bar:SetPoint("BOTTOMLEFT", 0, 0)
        bar:SetWidth(3)
        bar:Hide()
        local label = Text(t, "GameFontHighlight", C.muted)
        label:SetPoint("LEFT", 16, 0)
        label:SetText(def.label)
        function t:SetActive(on)
            self.active = on
            if on then hl:Show(); bar:Show(); label:SetTextColor(C.text[1], C.text[2], C.text[3])
            else hl:Hide(); bar:Hide(); label:SetTextColor(C.muted[1], C.muted[2], C.muted[3]) end
        end
        t:SetScript("OnEnter", function(self) if not self.active then hl:Show() end end)
        t:SetScript("OnLeave", function(self) if not self.active then hl:Hide() end end)
        t:SetScript("OnClick", function() Show(def.key) end)
        tabs[def.key] = t
    end

    local guildName = Text(side, "GameFontDisableSmall", C.muted)
    guildName:SetPoint("BOTTOMLEFT", 14, 14)
    guildName:SetPoint("RIGHT", side, "RIGHT", -10, 0)
    win.guildName = guildName

    local close = Button(win, "x", 22, 22, false, function() win:Hide() end)
    close:SetPoint("TOPRIGHT", -8, -10)

    local title = Text(win, "GameFontNormalLarge", C.text)
    title:SetPoint("TOPLEFT", side, "TOPRIGHT", 18, -14)
    win.title = title

    local builders = { overview = BuildOverview, race = BuildRace, crafters = BuildCrafters,
                       week = BuildWeek, settings = BuildSettings }
    for _, def in ipairs(PAGE_ORDER) do
        local page = CreateFrame("Frame", nil, win)
        page:SetPoint("TOPLEFT", side, "TOPRIGHT", 16, -44)
        page:SetPoint("BOTTOMRIGHT", -14, 14)
        builders[def.key](page)
        page:Hide()
        pages[def.key] = page
    end
    ns.pages = pages
    win:SetScript("OnShow", function()
        local g = IsInGuild() and GetGuildInfo and GetGuildInfo("player")
        guildName:SetText(type(g) == "string" and ("<" .. g .. ">") or "No guild")
    end)
end

function ns.Open(key)
    if not win then BuildWindow() end
    key = key or win.current or "overview"
    for _, def in ipairs(PAGE_ORDER) do
        if def.key == key then win.title:SetText(def.label) end
    end
    win:Show()
    Show(key)
end

-- Title follows the tab.
local baseShow = Show
Show = function(key)
    baseShow(key)
    for _, def in ipairs(PAGE_ORDER) do if def.key == key then win.title:SetText(def.label) end end
end

function ns.Toggle()
    if win and win:IsShown() then win:Hide() else ns.Open() end
end

-- Addon compartment (the little button by the minimap on modern clients). Declared in the .toc.
function GuildMilestones_OnCompartmentClick() ns.Toggle() end

-- ------------------------------------------------------------------ toasts
local toast, queue, showing = nil, {}, false
local TOAST_TIME, FADE_TIME = 4.5, 0.8

local ICONS = {
    L = "Interface\\Icons\\Spell_Holy_SurgeOfLight",
    S = "Interface\\Icons\\Trade_BlackSmithing",
    I = "Interface\\Icons\\INV_Misc_Bag_10",
    B = "Interface\\Icons\\INV_Misc_Head_Dragon_01",
}

local function BuildToast()
    toast = Box(UIParent, C.bg)
    toast:SetSize(300, 56)
    toast:SetPoint("TOP", 0, -150)
    toast:SetFrameStrata("DIALOG")
    toast:Hide()
    local edge = Solid(toast, C.gold)
    edge:SetPoint("TOPLEFT", 1, -1)
    edge:SetPoint("BOTTOMLEFT", 1, 1)
    edge:SetWidth(3)
    toast.icon = toast:CreateTexture(nil, "ARTWORK")
    toast.icon:SetSize(38, 38)
    toast.icon:SetPoint("LEFT", 12, 0)
    toast.title = Text(toast, "GameFontNormal", C.gold)
    toast.title:SetPoint("TOPLEFT", 60, -11)
    toast.title:SetPoint("RIGHT", toast, "RIGHT", -10, 0)
    toast.body = Text(toast, "GameFontHighlightSmall", C.text)
    toast.body:SetPoint("TOPLEFT", toast.title, "BOTTOMLEFT", 0, -4)
    toast.body:SetPoint("RIGHT", toast, "RIGHT", -10, 0)
    toast.body:SetWordWrap(false)
    toast:SetScript("OnUpdate", function(self, elapsed)
        self.t = (self.t or 0) + elapsed
        if self.t > TOAST_TIME then
            local a = 1 - (self.t - TOAST_TIME) / FADE_TIME
            if a <= 0 then
                self:Hide()
                showing = false
                ns.NextToast()
            else
                self:SetAlpha(a)
            end
        end
    end)
end

function ns.NextToast()
    local item = table.remove(queue, 1)
    if not item then return end
    if not toast then BuildToast() end
    showing = true
    toast.icon:SetTexture(item.icon or ICONS.L)
    toast.title:SetText(item.title)
    toast.body:SetText(item.body)
    toast.t = 0
    toast:SetAlpha(1)
    toast:Show()
end

function ns.Toast(icon, title, body)
    if #queue >= 5 then return end                 -- a burst never piles up
    queue[#queue + 1] = { icon = icon, title = title, body = body }
    if not showing then ns.NextToast() end
end

local lastBoss = {}
function ns.OnMoment(kind, who, a, b, c)
    local mine = ns.Short(who) == ns.Short(UnitName("player"))
    local name = mine and "You" or ns.Short(who)
    if kind == "L" then
        ns.Toast(ICONS.L, mine and "Milestone reached!" or "Guild milestone", name .. " reached level " .. tostring(a))
    elseif kind == "S" then
        ns.Toast(ICONS.S, "Profession milestone", name .. " reached " .. tostring(b) .. " in " .. tostring(a))
    elseif kind == "I" then
        local q = tonumber(tostring(b or ""):match("^(%d+)")) or 0
        if q < 4 then return end                      -- only epic and better
        local icon
        pcall(function()
            icon = (C_Item and C_Item.GetItemIconByID and C_Item.GetItemIconByID(tonumber(a))) or (GetItemIcon and GetItemIcon(tonumber(a)))
        end)
        ns.Toast(icon or ICONS.I, "Epic loot!", name .. " got |cff" .. (QUALITY_HEX[q] or "a335ee") .. "[" .. tostring(c or "an item") .. "]|r")
    elseif kind == "B" then
        if lastBoss[a] and GetTime() - lastBoss[a] < 120 then return end   -- one toast per kill
        lastBoss[a] = GetTime()
        ns.Toast(ICONS.B, "Boss down!", tostring(a) .. " was defeated")
    end
end

-- ------------------------------------------------------------------ Esc > Options entry
local function BuildOptionsEntry()
    local panel = CreateFrame("Frame")
    panel.name = "Guild Milestones"
    local title = Text(panel, "GameFontNormalLarge", C.gold)
    title:SetPoint("TOPLEFT", 16, -16)
    title:SetText("Guild Milestones")
    local desc = Text(panel, "GameFontHighlight", C.text)
    desc:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -10)
    desc:SetWidth(520)
    desc:SetText("Everything lives in the Guild Milestones window: your progress, the guild race, crafters, the week and the settings. Type /gms any time to open it.")
    local open = Button(panel, "Open Guild Milestones", 200, 30, true, function()
        if SettingsPanel and SettingsPanel.Hide then pcall(SettingsPanel.Hide, SettingsPanel) end
        if HideUIPanel and InterfaceOptionsFrame then pcall(HideUIPanel, InterfaceOptionsFrame) end
        ns.Open()
    end)
    open:SetPoint("TOPLEFT", desc, "BOTTOMLEFT", 0, -16)
    if Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory then
        local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)
        Settings.RegisterAddOnCategory(category)
    elseif InterfaceOptions_AddCategory then
        InterfaceOptions_AddCategory(panel)
    end
end

function ns.BuildUI()
    pcall(BuildOptionsEntry)
end
