-- Classic-style client: no GetProfessions, old skill list, some events unknown
dofile("wowstub.lua")
W.unknownEvents = { SKILL_LINES_CHANGED = true, GUILD_TRADESKILL_UPDATE = true, CHAT_MSG_ADDON = true }
GetProfessions, GetProfessionInfo = nil, nil
C_ChatInfo = nil
sent = {}
function SendAddonMessage(p, text, ch) sent[#sent+1] = text end
function RegisterAddonMessagePrefix(p) W.prefix2 = p end
Settings = nil
local opened = 0
function InterfaceOptions_AddCategory(p) W.legacy = p end
function InterfaceOptionsFrame_OpenToCategory(p) opened = opened + 1 end

-- skill list: headers and rows, including weapon skills that must NOT be announced
W.skillRows = {
    { "Class Skills", true }, { "Enhancement", false, nil, 100 },
    { "Professions", true }, { "Alchemy", false, nil, 140 }, { "Herbalism", false, nil, 70 },
    { "Secondary Skills", true }, { "Cooking", false, nil, 70 },
    { "Weapon Skills", true }, { "Swords", false, nil, 145 }, { "Maces", false, nil, 70 },
}
function GetNumSkillLines() return #W.skillRows end
function GetSkillLineInfo(i) local r = W.skillRows[i]; return r[1], r[2], nil, r[4] end

W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run()
check("classic: legacy panel registered", W.legacy ~= nil)
check("classic: prefix registered the old way", W.prefix2 == "GMS1")
sent = {}

-- events that exist still work
W.skillRows[4][4] = 150          -- Alchemy 140 -> 150
W.skillRows[9][4] = 150          -- Swords 145 -> 150 (weapon skill: must stay silent)
W.fire("CHAT_MSG_SKILL"); W.run()
check("classic: profession tier announced", #W.chat == 1 and W.chat[1].text:find("Alchemy"), #W.chat)
check("classic: weapon skill ignored", not (W.chat[1] and W.chat[1].text:find("Swords")))
check("classic: old addon-message API used", sent[1] == "S|Thrall|Alchemy|150", sent[1])

SlashCmdList["GUILDMILESTONES"]("options")
check("classic: window opens on an old client too", W.ns.pages and W.ns.pages.settings:IsShown())

-- level up still works with no C_Timer.NewTicker needed
W.fire("PLAYER_LEVEL_UP", 20); W.run()
check("classic: level shout", W.chat[#W.chat].text:find("level 20"))
os.exit(W.summary() == 0 and 0 or 1)
