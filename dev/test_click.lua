-- Games that drop guild chat an addon sends by itself (WoW: Forever, retail 12.1.5+):
-- the addon must notice and hand the lines to a Post bar the player clicks.
dofile("wowstub.lua")

local function postButton()
    for _, fr in ipairs(W.frames) do
        local l = rawget(fr, "label")
        if fr.kind == "Button" and type(l) == "table" and l:GetText():match("^Post") then return fr end
    end
end

-- 1. Blocked game: the test line is dropped, so nothing is lost and the bar appears
W.blockChat = true
local ns = W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run(); W.clear()
W.fire("PLAYER_LEVEL_UP", 30); W.fire("PLAYER_LEVEL_UP", 40); W.run()
check("blocked: nothing reached chat by itself", #W.chat == 0, #W.chat)
check("blocked: the game dropped the test line", (W.dropped or 0) >= 1, W.dropped)
check("blocked: switched to click mode", ns.ChatMode() == "click", ns.ChatMode())
local n, first = ns.Ready()
check("blocked: both lines wait for a click", n == 2, n)
check("blocked: oldest line first", first == "Thrall just hit level 30! Congrats!", first)
check("blocked: told the player how to post", W.printed("/gms post"))
local btn = postButton()
check("blocked: Post bar shows the count", btn and btn.label:GetText() == "Post (2)", btn and btn.label:GetText())

-- 2. A click posts exactly one line
W.click(btn.scripts.OnClick, btn); W.run()
check("click: one line posted", #W.chat == 1 and W.chat[1].text:find("level 30"), #W.chat)
check("click: one still waiting", (ns.Ready()) == 1)

-- 3. /gms post (a typed command is a key press) posts the next one, and the bar goes away
W.click(SlashCmdList["GUILDMILESTONES"], "post"); W.run()
check("/gms post: second line posted", #W.chat == 2 and W.chat[2].text:find("level 40"), #W.chat)
check("/gms post: nothing left", (ns.Ready()) == 0)
W.clear(); W.click(SlashCmdList["GUILDMILESTONES"], "post")
check("/gms post: says when empty", W.printed("Nothing waiting"))

-- 4. Later milestones go straight to the bar, no second test
W.clear(); W.fire("PLAYER_LEVEL_UP", 50); W.run()
check("later: queued, not sent", #W.chat == 0 and (ns.Ready()) == 1)
ns.SkipReady()
check("skip all: queue empty", (ns.Ready()) == 0)

-- 5. A game that allows it: the echo comes back, so it stays automatic
W.blockChat = false
local ns2 = W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run(); W.clear()
W.fire("PLAYER_LEVEL_UP", 30); W.fire("PLAYER_LEVEL_UP", 40); W.run()
check("allowed: both lines sent by themselves", #W.chat == 2, #W.chat)
check("allowed: stays automatic", ns2.ChatMode() == "auto", ns2.ChatMode())

-- 6. "Interface action failed" (ADDON_ACTION_BLOCKED) switches to click mode right away
W.blockChat = true
local ns3 = W.loadAddon()
W.fire("PLAYER_LOGIN"); W.run(); W.clear()
local realAfter = C_Timer.After
C_Timer.After = function(sec, fn) if sec ~= 5 then realAfter(sec, fn) end end   -- no echo timeout
W.fire("PLAYER_LEVEL_UP", 30)
for _ = 1, 5 do local b = W.timers; W.timers = {}; for _, fn in ipairs(b) do fn() end end
W.fire("ADDON_ACTION_BLOCKED", "GuildMilestones", "SendChatMessage()")
C_Timer.After = realAfter
check("blocked event: click mode", ns3.ChatMode() == "click", ns3.ChatMode())
check("blocked event: line kept", (ns3.Ready()) == 1)

os.exit(W.summary() == 0 and 0 or 1)
