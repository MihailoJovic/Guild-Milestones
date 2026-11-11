-- WoW: Forever-style client: modern engine, but Classic-style skills only through C_SkillInfo,
-- and names are "First Surname": UnitName("player") gives "Stronk", the roster and chat say "Stronk Bmf".
dofile("wowstub.lua")
function GetProfessions() return nil end          -- exists, but lists nothing
GetNumSkillLines, GetSkillLineInfo = nil, nil
W.skillRows = {
    { skillName = "Professions", isHeader = true }, { skillName = "Alchemy", skillRank = 140 },
    { skillName = "Weapon Skills", isHeader = true }, { skillName = "Swords", skillRank = 145 },
}
C_SkillInfo = {
    GetNumSkillLines = function() return #W.skillRows end,
    GetSkillLineInfo = function(i) return W.skillRows[i] end,
}

-- the real situation on the owner's PC (2026-11-11)
W.me = "Stronk"
function UnitGUID() return "Player-1-0001" end
local function row(name, level, class, guid)
    local r = { name, "Member", 4, level, class, "Zone", "", "", true, 0, class:upper() }
    r[17] = guid
    return r
end
W.roster = { row("Stronk Bmf", 32, "Warrior", "Player-1-0001"), row("Nevidjeno Crn", 31, "Paladin", "Player-1-0002"),
             row("Tic Tac", 39, "Priest", "Player-1-0003") }
LOOT_ITEM_SELF = "You receive loot: %s."

W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run(); W.clear()

W.skillRows[2].skillRank = 150
W.skillRows[4].skillRank = 150
W.fire("SKILL_LINES_CHANGED"); W.run()
check("forever: tier read through C_SkillInfo", #W.chat == 1 and W.chat[1].text:find("Alchemy"), #W.chat)
check("forever: weapon skill ignored", not (W.chat[1] and W.chat[1].text:find("Swords")))

-- my full guild name is found through the roster, so the app and guildmates can match it
W.clear(); W.fire("PLAYER_LEVEL_UP", 20); W.run()
check("chat line uses the short name", W.chat[1] and W.chat[1].text == "Stronk just hit level 20! Congrats!", W.chat[1] and W.chat[1].text)
check("hidden message uses the full name", W.addon[1] and W.addon[1].text == "L|Stronk Bmf|20", W.addon[1] and W.addon[1].text)

-- my own hidden message comes back signed "Stronk Bmf": it must not be stored a second time
GuildMilestonesDB.events = nil
W.fire("ENCOUNTER_END", 1, "Relic Guardian", 1, 5, 1); W.run()
local mine = GuildMilestonesDB.events[1]
check("my boss kill recorded under my full name", mine and mine:match("^B|Stronk Bmf|%d+|Relic Guardian|5|$"), mine)
W.fire("CHAT_MSG_ADDON", "GMS1", "E|" .. mine, "GUILD", "Stronk Bmf")
check("my own echo isn't stored twice", #GuildMilestonesDB.events == 1, #GuildMilestonesDB.events)

-- a guildmate's announcement, read straight from guild chat (the hidden channel never brought it)
GuildMilestonesDB.events = nil
W.fire("CHAT_MSG_GUILD", "Nevidjeno and friends defeated Relic Guardian!", "Nevidjeno Crn")
local ev = GuildMilestonesDB.events and GuildMilestonesDB.events[1]
check("boss kill read from guild chat", ev and ev:match("^B|Nevidjeno Crn|%d+|Relic Guardian||$"), ev)
W.fire("CHAT_MSG_ADDON", "GMS1", "E|B|Nevidjeno Crn|1800000000|Relic Guardian|5|", "GUILD", "Nevidjeno Crn")
check("same kill on the hidden channel isn't counted twice", #GuildMilestonesDB.events == 1, #GuildMilestonesDB.events)
W.fire("CHAT_MSG_GUILD", "Tic just hit level 40! Congrats!", "Tic Tac")
check("level-up read from guild chat", GuildMilestonesDB.heard[#GuildMilestonesDB.heard]:match("^Tic Tac|L|40|"))
W.fire("CHAT_MSG_GUILD", "Tic reached Expert (150) in Tailoring!", "Tic Tac")
check("skill tier read from guild chat", GuildMilestonesDB.heard[#GuildMilestonesDB.heard]:match("^Tic Tac|S|Tailoring|150|"))
W.fire("CHAT_MSG_GUILD", "Tic looted |cnIQ4:|Hitem:12345::::::::40:::::|h[Shiny Staff]|h|r! (Epic, ilvl 45)", "Tic Tac")
ev = GuildMilestonesDB.events[#GuildMilestonesDB.events]
check("loot read from guild chat", ev:match("^I|Tic Tac|%d+|12345|4:0|Shiny Staff$"), ev)
W.fire("CHAT_MSG_GUILD", "Tic is now riding an epic mount!", "Tic Tac")
check("mount read from guild chat", GuildMilestonesDB.events[#GuildMilestonesDB.events]:match("^M|Tic Tac|%d+|epic||$"))
local n = #GuildMilestonesDB.events
W.fire("CHAT_MSG_GUILD", "anyone up for Deadmines?", "Tic Tac")
W.fire("CHAT_MSG_GUILD", "Stronk and friends defeated Relic Guardian!", "Stronk Bmf")
check("normal chat and my own lines are ignored", #GuildMilestonesDB.events == n)

-- the troubleshooting log
W.clear(); SlashCmdList["GUILDMILESTONES"]("debug")
check("/gms debug shows who I am and what arrived", W.printed("you are 'Stronk Bmf'") and W.printed("Read from guild chat: 5"), W.out[1])
os.exit(W.summary() == 0 and 0 or 1)
