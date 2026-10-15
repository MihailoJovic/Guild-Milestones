-- WoW: Forever-style client: modern engine, but Classic-style skills only through C_SkillInfo
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

W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run(); W.clear()

W.skillRows[2].skillRank = 150
W.skillRows[4].skillRank = 150
W.fire("SKILL_LINES_CHANGED"); W.run()
check("forever: tier read through C_SkillInfo", #W.chat == 1 and W.chat[1].text:find("Alchemy"), #W.chat)
check("forever: weapon skill ignored", not (W.chat[1] and W.chat[1].text:find("Swords")))

-- names are "First Surname" with no realm
W.me = "Ser Thrall"
W.clear(); W.fire("PLAYER_LEVEL_UP", 20); W.run()
check("forever: name with a space", W.chat[1] and W.chat[1].text == "Ser Thrall just hit level 20! Congrats!", W.chat[1] and W.chat[1].text)
check("forever: addon message with a space", W.addon[1] and W.addon[1].text == "L|Ser Thrall|20", W.addon[1] and W.addon[1].text)
W.fire("CHAT_MSG_ADDON", "GMS1", "L|Lady Jaina|30", "GUILD", "Lady Jaina")
check("forever: heard a spaced name", GuildMilestonesDB.heard[#GuildMilestonesDB.heard]:match("^Lady Jaina|L|30|"))
os.exit(W.summary() == 0 and 0 or 1)
