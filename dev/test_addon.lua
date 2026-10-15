dofile("wowstub.lua")
local ADDON = os.getenv("ADDON")
W.unknownEvents = { SKILL_LINES_CHANGED = false }
W.loadAddon()
local function slash(msg) W.clear(); SlashCmdList["GUILDMILESTONES"](msg) end

-- 1. login
W.fire("PLAYER_LOGIN"); W.run()
check("login prints ready line", W.printed("ready"))
check("prefix registered", W.prefix == "GMS1")
check("panel registered", W.category ~= nil)
check("version hello sent at login", W.addon[1] and W.addon[1].text == "V|0.10.1", W.addon[1] and W.addon[1].text)
W.clear()

-- 2. levels
W.fire("PLAYER_LEVEL_UP", 29); W.run()
check("level 29 is not a milestone", #W.chat == 0)
W.fire("PLAYER_LEVEL_UP", 30); W.run()
check("level 30 shouts once", #W.chat == 1, #W.chat)
check("level text", W.chat[1] and W.chat[1].text == "Thrall just hit level 30! Congrats!", W.chat[1] and W.chat[1].text)
check("goes to GUILD", W.chat[1] and W.chat[1].channel == "GUILD")
check("addon message sent", W.addon[1] and W.addon[1].text == "L|Thrall|30" and W.addon[1].channel == "GUILD" and W.addon[1].prefix == "GMS1")
check("heard record written", GuildMilestonesDB.heard and GuildMilestonesDB.heard[1]:match("^Thrall|L|30||%d+$"), GuildMilestonesDB.heard and GuildMilestonesDB.heard[1])
W.clear(); W.fire("PLAYER_LEVEL_UP", 60); W.run()
check("cap message", W.chat[1] and W.chat[1].text:find("level cap"), W.chat[1] and W.chat[1].text)
W.clear(); W.fire("PLAYER_LEVEL_UP", 45); W.run()
check("45 not a milestone", #W.chat == 0)

-- 3. spacing: two shouts queue and both go out in order
W.clear(); W.fire("PLAYER_LEVEL_UP", 10); W.fire("PLAYER_LEVEL_UP", 20); W.run()
check("queued shouts both sent in order", #W.chat == 2 and W.chat[1].text:find("level 10") and W.chat[2].text:find("level 20"))

-- 4. skills (retail path). Baseline was read silently at login (no profs yet)
W.profs = { { "Alchemy", 140 }, { "Herbalism", 70 } }
W.clear(); W.fire("SKILL_LINES_CHANGED"); W.run()
check("first change after empty baseline announces nothing", #W.chat == 0)
W.profs = { { "Alchemy", 151 }, { "Herbalism", 72 } }
W.fire("SKILL_LINES_CHANGED"); W.run()
check("tier 150 shouts", #W.chat == 1 and W.chat[1].text == "Thrall reached Expert (150) in Alchemy!", W.chat[1] and W.chat[1].text)
check("tier addon message", W.addon[1] and W.addon[1].text == "S|Thrall|Alchemy|150", W.addon[1] and W.addon[1].text)
W.clear(); W.profs = { { "Alchemy", 240 }, { "Herbalism", 72 } }; W.fire("CHAT_MSG_SKILL"); W.run()
check("jump past 225 announces the top tier once", #W.chat == 1 and W.chat[1].text:find("Artisan %(225%)"), W.chat[1] and W.chat[1].text)
W.clear(); W.profs = { { "Alchemy", 241 }, { "Herbalism", 72 } }; W.fire("CHAT_MSG_SKILL"); W.run()
check("no tier crossed = silence", #W.chat == 0)

-- 5. switching shouting off
slash("shout off")
W.clear(); local before = #GuildMilestonesDB.heard
W.fire("PLAYER_LEVEL_UP", 40); W.run()
check("shout off sends nothing", #W.chat == 0 and #W.addon == 0)
check("shout off records nothing", #GuildMilestonesDB.heard == before)
slash("shout on")
check("shout on message", W.printed("ON"))

-- 6. officer channel
GuildMilestonesDB.settings.channel = "OFFICER"
W.clear(); W.fire("PLAYER_LEVEL_UP", 50); W.run()
check("officer channel used", W.chat[1] and W.chat[1].channel == "OFFICER")
GuildMilestonesDB.settings.channel = "GUILD"

-- 7. not in a guild
W.guilded = false; W.clear(); W.fire("PLAYER_LEVEL_UP", 30); W.run()
check("no guild, no shout", #W.chat == 0)
W.guilded = true

-- 8. hearing others
local n0 = #GuildMilestonesDB.heard
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Jaina|30", "GUILD", "Jaina-Realm")
W.fire("CHAT_MSG_ADDON", "GMS1", "S|Jaina|Mining|75", "GUILD", "Jaina-Realm")
check("heard two records", #GuildMilestonesDB.heard == n0 + 2)
check("heard format L", GuildMilestonesDB.heard[n0+1]:match("^Jaina|L|30||%d+$"))
check("heard format S", GuildMilestonesDB.heard[n0+2]:match("^Jaina|S|Mining|75|%d+$"))
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Thrall|30", "GUILD", "Thrall-Realm")          -- my own echo
W.fire("CHAT_MSG_ADDON", "OTHER", "L|Jaina|40", "GUILD", "Jaina-Realm")           -- other addon
W.fire("CHAT_MSG_ADDON", "GMS1", "garbage", "GUILD", "Jaina-Realm")               -- malformed
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Jaina|40", "PARTY", "Jaina-Realm")            -- wrong channel
check("own echo, other prefix, junk and wrong channel ignored", #GuildMilestonesDB.heard == n0 + 2)
for i = 1, 400 do W.fire("CHAT_MSG_ADDON", "GMS1", "L|Bob|" .. i, "GUILD", "Bob-Realm") end
check("heard log capped at 300", #GuildMilestonesDB.heard == 300, #GuildMilestonesDB.heard)

-- 9. roster snapshot
W.fire("GUILD_ROSTER_UPDATE")
check("snapshot members", GuildMilestonesDB.members and #GuildMilestonesDB.members == 2)
check("snapshot row", GuildMilestonesDB.members[1] == "Thrall-Realm|60|SHAMAN|0|0", GuildMilestonesDB.members[1])
check("snapshot profs", GuildMilestonesDB.profs and #GuildMilestonesDB.profs == 3, GuildMilestonesDB.profs and #GuildMilestonesDB.profs)
check("snapshot version", GuildMilestonesDB.version == 3 and GuildMilestonesDB.addon == "0.10.1")

-- 10. crafters
slash("crafters")
check("crafters overview", W.printed("Alchemy (2)") and W.printed("Herbalism (1)"))
slash("crafters alch")
check("crafters sorted by skill", W.printed("Alchemy (2): Thrall 150, Jaina 75"), W.out[1])
slash("crafters nothing")
check("crafters no match", W.printed("Nobody"))
local saved = W.gts; W.gts = {}
slash("crafters herb")
check("crafters falls back to saved snapshot", W.printed("Arthas 300") and W.printed("saved snapshot"))
GuildMilestonesDB.profs = nil
slash("crafters")
check("crafters explains when empty", W.printed("Professions tab"))
W.gts = saved

-- 11. week
slash("week")
check("week without data", W.printed("companion app"))
GuildMilestonesWeek = { title = "Week of Oct 5", asof = "14:02", lines = { "New: Bob", "Top: Thrall +3" } }
slash("week")
check("week with data", W.printed("Week of Oct 5") and W.printed("as of 14:02") and W.printed("New: Bob"))

-- 12. help, test, maxlevel, the window
slash("help")
check("help lists commands", W.printed("/gms crafters") and W.printed("/gms week"))
slash("test")
check("preview shows messages", W.printed("Thrall just hit level 30") and W.printed("Expert (150)") and W.printed("nothing is sent"))
slash("maxlevel 50")
W.clear(); W.fire("PLAYER_LEVEL_UP", 50); W.run()
check("custom cap respected", W.chat[1] and W.chat[1].text:find("level cap"))
slash("maxlevel 0")
slash("bogus")
check("unknown command shows help", W.printed("/gms options"))

-- 13. the window: every tab builds and fills without errors
local ns = W.ns
slash("")
check("/gms opens the window", GuildMilestonesWindow and GuildMilestonesWindow:IsShown())
for _, tab in ipairs({ "overview", "race", "crafters", "week", "settings" }) do
    W.clear(); ns.Open(tab)
    check("tab " .. tab .. " shows", ns.pages[tab]:IsShown() and not W.printed("couldn't fill"), W.out[1])
end
check("only one tab visible", not ns.pages.overview:IsShown())
check("Esc closes the window", UISpecialFrames[1] == "GuildMilestonesWindow")
slash("options")
check("/gms options opens Settings", ns.pages.settings:IsShown())
local sel = ns.pages.settings.selectors
sel.announce.step(1)
check("selector changes channel", GuildMilestonesDB.settings.channel == "OFFICER" and GuildMilestonesDB.settings.shout == true)
sel.announce.step(1)
check("selector wraps to off", GuildMilestonesDB.settings.shout == false)
sel.announce.step(1)
check("selector back to guild", GuildMilestonesDB.settings.shout == true and GuildMilestonesDB.settings.channel == "GUILD")
sel.snapshot.step(1)
check("on/off selector writes setting", GuildMilestonesDB.settings.snapshot == false)
sel.snapshot.step(1)
check("Esc > Options entry registered", W.category ~= nil)

-- toasts for guildmates' milestones
local toasts = {}
local realToast = ns.Toast
ns.Toast = function(icon, title, body) toasts[#toasts + 1] = body end
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Jaina|30", "GUILD", "Jaina-Realm")
check("guildmate level toast", toasts[1] == "Jaina reached level 30", toasts[1])
W.fire("CHAT_MSG_ADDON", "GMS1", "E|I|Bob|1700000000|1234|4:60|Cool Sword", "GUILD", "Bob-Realm")
check("epic loot toast", toasts[2] and toasts[2]:find("Cool Sword", 1, true), toasts[2])
W.fire("CHAT_MSG_ADDON", "GMS1", "E|I|Bob|1700000001|1235|3:60|Blue Thing", "GUILD", "Bob-Realm")
check("no toast for blue loot", #toasts == 2)
W.fire("CHAT_MSG_ADDON", "GMS1", "E|B|Bob|1700000002|Onyxia|10|", "GUILD", "Bob-Realm")
W.fire("CHAT_MSG_ADDON", "GMS1", "E|B|Ann|1700000003|Onyxia|10|", "GUILD", "Ann-Realm")
check("one toast per boss kill", #toasts == 3, #toasts)
GuildMilestonesDB.settings.toasts = false
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Jaina|40", "GUILD", "Jaina-Realm")
check("toasts can be switched off", #toasts == 3)
GuildMilestonesDB.settings.toasts = nil
ns.Toast = realToast
ns.Toast("x", "Title", "Body")
check("real toast builds", true)
GuildMilestonesDB.heard, GuildMilestonesDB.events = GuildMilestonesDB.heard or {}, GuildMilestonesDB.events or {}
W.clear(); ns.Open("overview")
check("overview fills with recent events", not W.printed("couldn't fill"), W.out[1])

-- guild-wide settings from the Guild Info text
W.guildInfo = "Welcome friends! Be nice.\n[GMS L=5,15 C=20 T=75]\nRaid Tue"
function GetGuildInfoText() return W.guildInfo end
W.fire("GUILD_ROSTER_UPDATE")
W.clear(); W.fire("PLAYER_LEVEL_UP", 15); W.run()
check("guild levels used", W.chat[1] and W.chat[1].text:find("level 15"), W.chat[1] and W.chat[1].text)
W.clear(); W.fire("PLAYER_LEVEL_UP", 10); W.run()
check("old default level no longer announced", #W.chat == 0)
W.clear(); W.fire("PLAYER_LEVEL_UP", 20); W.run()
check("guild cap used", W.chat[1] and W.chat[1].text:find("level cap"), W.chat[1] and W.chat[1].text)
check("guild config cached", GuildMilestonesDB.guildCfg and GuildMilestonesDB.guildCfg.L == "5,15")
slash("guild")
check("/gms guild reports", W.printed("levels 5,15") and W.printed("cap 20"))
-- publish: officer with app settings
GuildMilestonesConfig = { levels = "10, 25", cap = 60, tiers = "75, 150" }
local set
function CanEditGuildInfo() return true end
function SetGuildInfoText(t) set = t; W.guildInfo = t end
slash("publish")
check("publish replaces tag, keeps other text", set == "Welcome friends! Be nice.\n[GMS L=10,25 C=60 T=75,150]\nRaid Tue", set)
set = nil; slash("publish")
check("publish is a no-op when current", set == nil and W.printed("already"))
W.guildInfo = "just text"; slash("publish")
check("publish appends when no tag", set == "just text\n[GMS L=10,25 C=60 T=75,150]", set)
W.guildInfo = ""; set = nil
function CanEditGuildInfo() return false end
slash("publish")
check("non-officer cannot publish", set == nil and W.printed("can't edit"))
W.guildInfo = "Welcome\n[GMS L=10,25 C=60 T=75,150]"; W.fire("GUILD_ROSTER_UPDATE")
check("settings panel shows guild text", true)
GuildMilestonesDB.guildCfg = nil

-- loot / boss / death / quest
W.guildInfo = ""; guildCfg = nil
local rare = "|cff0070dd|Hitem:19019::::::::60:::::|h[Thunderfury]|h|r"
local gray = "|cff9d9d9d|Hitem:1::::::::60:::::|h[Junk]|h|r"
function GetItemInfo() return "Thunderfury", nil, 3, 80 end
function GetZoneText() return "Westfall" end
LOOT_ITEM_SELF = "You receive loot: %s."
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. rare .. "."); W.run()
check("rare loot announced with details", W.chat[1] and W.chat[1].text:find("looted") and W.chat[1].text:find("Rare, ilvl 80") and W.chat[1].text:find("Thunderfury", 1, true), W.chat[1] and W.chat[1].text)
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. gray .. "."); W.run()
check("gray loot ignored", #W.chat == 0)
W.clear(); W.fire("CHAT_MSG_LOOT", "Bob receives loot: " .. rare .. "."); W.run()
check("other people's loot ignored", #W.chat == 0)
GuildMilestonesDB.settings.lootMin = -1
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. rare .. "."); W.run()
check("loot off", #W.chat == 0)
GuildMilestonesDB.settings.lootMin = 3
W.clear(); for i = 1, 12 do W.fire("CHAT_MSG_LOOT", "You receive loot: " .. rare .. ".") end W.run()
check("loot burst capped", #W.chat <= 6 and #W.chat >= 1, #W.chat)
W.clear(); W.fire("PLAYER_DEAD"); W.run()
check("deaths off by default", #W.chat == 0)
GuildMilestonesDB.settings.deaths = true
W.clear(); W.fire("PLAYER_DEAD"); W.run()
check("death announced", W.chat[1] and W.chat[1].text == "Thrall has died in Westfall.", W.chat[1] and W.chat[1].text)
W.clear(); W.fire("ENCOUNTER_END", 1, "Ragnaros", 1, 5, 1); W.run()
check("boss kill announced", W.chat[1] and W.chat[1].text:find("Ragnaros"), W.chat[1] and W.chat[1].text)
W.clear(); W.fire("ENCOUNTER_END", 1, "Ragnaros", 1, 5, 0); W.run()
check("boss wipe ignored", #W.chat == 0)
W.clear(); W.fire("QUEST_TURNED_IN", 5); W.run()
check("quests off by default", #W.chat == 0)
GuildMilestonesDB.settings.quests = true
W.clear(); W.fire("QUEST_TURNED_IN", 5); W.run()
check("quest announced", W.chat[1] and W.chat[1].text:find("completed"), W.chat[1] and W.chat[1].text)
GuildMilestonesDB.settings.shout = false
W.clear(); W.fire("PLAYER_DEAD"); W.fire("ENCOUNTER_END", 1, "X", 1, 5, 1); W.run()
check("announce-off silences everything", #W.chat == 0)
GuildMilestonesDB.settings.shout = true
GuildMilestonesDB.settings.lvlMode = "every"
W.clear(); W.fire("PLAYER_LEVEL_UP", 7); W.run()
check("every-level mode", W.chat[1] and W.chat[1].text:find("level 7"))
GuildMilestonesDB.settings.lvlMode = "off"
W.clear(); W.fire("PLAYER_LEVEL_UP", 10); W.run()
check("level-ups off", #W.chat == 0)
GuildMilestonesDB.settings.lvlMode = "guild"

-- events for the app
GuildMilestonesDB.events = nil
GuildMilestonesDB.settings.deaths = true
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. rare .. "."); W.fire("ENCOUNTER_END", 1, "Ragnaros", 1, 10, 1); W.fire("PLAYER_DEAD"); W.run()
local ev = GuildMilestonesDB.events or {}
check("loot event recorded", ev[1] and ev[1]:match("^I|Thrall|%d+|19019|3:80|Thunderfury$"), ev[1])
check("boss event recorded", ev[2] and ev[2]:match("^B|Thrall|%d+|Ragnaros|10|$"), ev[2])
check("death event recorded", ev[3] and ev[3]:match("^D|Thrall|%d+|Westfall||$"), ev[3])
local sent = false
for _, m in ipairs(W.addon) do if m.text:match("^E|I|Thrall|") then sent = true end end
check("event shared with other addons", sent)
W.fire("CHAT_MSG_ADDON", "GMS1", "E|I|Bob|1700000000|1234|4:60|Cool Sword", "GUILD", "Bob-Realm")
check("peer event recorded", GuildMilestonesDB.events[#GuildMilestonesDB.events] == "I|Bob|1700000000|1234|4:60|Cool Sword")
W.fire("CHAT_MSG_ADDON", "GMS1", "E|garbage", "GUILD", "Bob-Realm")
check("junk event ignored", #GuildMilestonesDB.events == 4)
for i = 1, 250 do W.fire("CHAT_MSG_ADDON", "GMS1", "E|D|Bob|" .. i .. "|Z||", "GUILD", "Bob-Realm") end
check("events capped", #GuildMilestonesDB.events == 200)
GuildMilestonesDB.settings.deaths = false

-- 14. custom message template, unknown placeholder left alone
GuildMilestonesDB.settings.levelMsg = "GG {name}, lvl {level} {oops}"
W.clear(); W.fire("PLAYER_LEVEL_UP", 25); W.run()
check("template with unknown placeholder", W.chat[1] and W.chat[1].text == "GG Thrall, lvl 25 {oops}", W.chat[1] and W.chat[1].text)

-- 16. v0.9.0: modern engine (WoW: Forever runs on the Midnight client)
GuildMilestonesDB.settings.levelMsg = nil
GuildMilestonesDB.events = nil
local modern = "|cnIQ4:|Hitem:19019::::::::60:::::|h[Thunderfury]|h|r"
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. modern .. "."); W.run()
check("modern |cnIQ link quality read", W.chat[1] and W.chat[1].text:find("Epic", 1, true) and W.chat[1].text:find("|cnIQ4:", 1, true), W.chat[1] and W.chat[1].text)
local plain = "|Hitem:2000::::::::60:::::|h[Mystery]|h"
C_Item = { GetItemQualityByID = function() return 3 end }
W.clear(); W.fire("CHAT_MSG_LOOT", "You receive loot: " .. plain .. "."); W.run()
check("quality asked from the game when the link has none", W.chat[1] and W.chat[1].text:find("Rare", 1, true), W.chat[1] and W.chat[1].text)
C_Item = nil
issecretvalue = function(v) return v == "SECRET" end
W.clear(); W.fire("CHAT_MSG_LOOT", "SECRET"); W.fire("ENCOUNTER_END", 1, "SECRET", 1, 5, 1); W.run()
check("secret values ignored", #W.chat == 0)
local nEv = #GuildMilestonesDB.events
W.fire("CHAT_MSG_ADDON", "GMS1", "SECRET", "GUILD", "Bob-Realm")
check("secret addon message ignored", #GuildMilestonesDB.events == nEv)
issecretvalue = nil

-- boss kills in a group: everyone records, only the leader shouts
IsInGroup = function() return true end
UnitIsGroupLeader = function() return false end
GuildMilestonesDB.events = nil
W.clear(); W.fire("ENCOUNTER_END", 1, "Onyxia", 1, 10, 1); W.run()
check("group member doesn't shout boss", #W.chat == 0, #W.chat)
check("group member still records boss", GuildMilestonesDB.events and GuildMilestonesDB.events[1]:match("^B|Thrall|%d+|Onyxia|10|$"))
UnitIsGroupLeader = function() return true end
W.clear(); W.fire("ENCOUNTER_END", 1, "Onyxia", 1, 10, 1); W.run()
check("group leader shouts boss", W.chat[1] and W.chat[1].text:find("Onyxia"))
IsInGroup, UnitIsGroupLeader = nil, nil

-- chat lockdown: lines wait, then go out
GuildMilestonesDB.settings.lvlMode = "every"
local locked = true
C_ChatInfo.InChatMessagingLockdown = function() return locked end
W.clear(); W.fire("PLAYER_LEVEL_UP", 30); W.run(3)
check("nothing sent while chat is locked", #W.chat == 0 and #W.addon == 0, #W.chat .. "/" .. #W.addon)
locked = false
W.fire("ADDON_RESTRICTION_STATE_CHANGED"); W.run()
check("sent after the lock lifts", #W.chat == 1 and #W.addon >= 1, #W.chat .. "/" .. #W.addon)
C_ChatInfo.InChatMessagingLockdown = nil

-- a blocked send is retried, not lost
local realSend, blocked = SendChatMessage, 2
SendChatMessage = function(t, c) if blocked > 0 then blocked = blocked - 1; error("blocked") end realSend(t, c) end
W.clear(); W.fire("PLAYER_LEVEL_UP", 40); W.run()
check("blocked shout retried", #W.chat == 1, #W.chat)
SendChatMessage = realSend
GuildMilestonesDB.settings.lvlMode = "guild"

-- an empty profession read never wipes what we know
W.profs = { { "Alchemy", 100 } }
W.fire("SKILL_LINES_CHANGED"); W.run()
W.profs = {}
W.fire("SKILL_LINES_CHANGED"); W.run()
W.profs = { { "Alchemy", 160 } }
W.clear(); W.fire("SKILL_LINES_CHANGED"); W.run()
check("empty read didn't reset skills (tier still announced)", W.chat[1] and W.chat[1].text:find("150"), W.chat[1] and W.chat[1].text)

-- /gms save no longer calls ReloadUI (blocked for addons on Forever)
W.reloaded = nil; slash("save")
check("save asks for /reload", W.printed("/reload") and not W.reloaded)

-- guild name stored with the snapshot
GetGuildInfo = function() return "Friends Forever" end
W.fire("GUILD_ROSTER_UPDATE")
check("snapshot remembers the guild", GuildMilestonesDB.guild == "Friends Forever", GuildMilestonesDB.guild)

-- version notice
W.clear()
W.fire("CHAT_MSG_ADDON", "GMS1", "V|0.11.0", "GUILD", "Jaina-Realm")
check("newer version noticed", W.printed("v0.11.0") and W.printed("Jaina"))
W.clear(); W.fire("CHAT_MSG_ADDON", "GMS1", "V|0.11.0", "GUILD", "Jaina-Realm")
check("notice only once per session", not W.printed("v0.11.0"))
W.clear(); W.fire("CHAT_MSG_ADDON", "GMS1", "V|0.8.1", "GUILD", "Bob-Realm")
check("older copy gets told our version", W.addon[1] and W.addon[1].text == "V|0.10.1", W.addon[1] and W.addon[1].text)
local nHeard = #GuildMilestonesDB.heard
W.fire("CHAT_MSG_ADDON", "GMS1", "V|0.8.1", "GUILD", "Bob-Realm")
check("version messages are not logged as events", #GuildMilestonesDB.heard == nHeard)

-- minimap button, tooltips, welcome
check("minimap button made", GuildMilestonesMinimapButton ~= nil)
GuildMilestonesMinimapButton.scripts.OnClick(GuildMilestonesMinimapButton, "LeftButton")
check("minimap click toggles the window", GuildMilestonesWindow:IsShown() == false or GuildMilestonesWindow:IsShown() == true)
GuildMilestonesMinimapButton.scripts.OnDragStart(GuildMilestonesMinimapButton)
GuildMilestonesMinimapButton.scripts.OnUpdate(GuildMilestonesMinimapButton)
check("dragging saves the angle", tonumber(GuildMilestonesDB.settings.minimapAngle) ~= nil, GuildMilestonesDB.settings.minimapAngle)
W.ns.pages.settings.selectors.minimap.step(1)
check("minimap can be hidden", GuildMilestonesDB.settings.minimap == false and not GuildMilestonesMinimapButton:IsShown())
W.ns.pages.settings.selectors.minimap.step(1)
check("minimap shown again", GuildMilestonesMinimapButton:IsShown())
GuildMilestonesMinimapButton.scripts.OnEnter(GuildMilestonesMinimapButton)
check("tooltip shows", W.tooltip == "Guild Milestones")
check("welcomed once", GuildMilestonesDB.welcomed == "0.10.1")

-- 15. logout saves
GuildMilestonesDB.updated = nil; W.fire("PLAYER_LOGOUT")
check("logout snapshot", GuildMilestonesDB.updated ~= nil)

os.exit(W.summary() == 0 and 0 or 1)
