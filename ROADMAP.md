# Guild Milestones roadmap

What we build next, in order. Ranked by how much it adds for a guild of ~20 friends on WoW: Forever,
weighed against the work. Updated 2026-10-15 (after v0.10.1).

**Status:** v0.11.0 shipped features 1, 2, 3, 4, 5, 7, 8, 9 and 10. Number 6 (raid night summary) was dropped.

## Top 10 features

| # | Feature | Why it matters | Effort |
|---|---|---|---|
| 1 | **Hall of Fame: guild firsts beyond levels.** First to 60, first epic mount, first dungeon and raid boss kills, first 300 profession, first epic item. One permanent Discord board, plus a 🥇 line on the post itself. | "First in the guild" moments are what friends remember and brag about. Most of the data is already collected. | Small |
| 2 | **Mount milestones.** Detect the riding skill (level 40 mount, epic mount at 60) and give it its own big post. | In Vanilla the first mount is a huge moment, and it costs a fortune. Nothing celebrates it today. | Small |
| 3 | **Weekly MVP vote.** A Discord poll every Friday with the week's top 5 (most levels, loot, bosses, quests). | Gets people talking and voting, not just reading. Works with a plain webhook. | Small |
| 4 | **Attunement and keys tracker.** Onyxia, Molten Core, Blackwing Lair, the UBRS and Scholomance keys. Shown on a Discord board and in a new in-game tab. | Raids unlock on 9 December. Everyone needs to know who's ready, without asking around. | Medium |
| 5 | **Guild goals.** Officers set goals like "Everyone to 40 by 9 Dec" or "5 Artisan crafters", shown with progress bars in the digest, on the race board and in game. | Turns solo levelling into a team effort, and casual players count too. | Small |
| 6 | **Raid night summary.** After a raid evening, one post: bosses killed, epic loot, who was there. | One tidy recap instead of a stream of posts, and good for anyone who missed the night. | Small |
| 7 | **"Your road to 60" recap card.** When someone hits 60: days it took, deaths, dungeons, best loot, firsts, as one picture card. | The "Spotify Wrapped" moment. Very shareable. | Medium |
| 8 | **Crafters board.** A third self-updating Discord message: who crafts what, by skill, with an in-game search. | "Who can make me X?" gets answered without anyone asking in chat. | Small |
| 9 | **Group finder (passive).** In the GM window you tick what you're looking for (a dungeon, a quest, a key run). Guildmates see it in game and on a quiet Discord board. No pings. | Helps the casual half find groups without spamming chat. Stays clear of the "announcer" idea. | Medium |
| 10 | **Fallen Heroes (Hardcore).** A memorial wall for Forever's Hardcore realms (winter 2026/27): name, level, where they fell, plus a weekly roll-up. | Only matters if the guild goes Hardcore, but then it matters a lot. | Small |

## Changes to the code and how we work

| # | Change | Why |
|---|---|---|
| 1 | **Test in a real client.** The in-game window, the toasts, the minimap button and the Forever API fixes have only run against our fake WoW in the tests. | This is the biggest risk. One session on Midnight (or the Forever beta) will show what we can't see from here. |
| 2 | **Replace the regex file reader with a real Lua-table reader.** | Item names with quote marks get silently skipped today. A proper reader can't miss them. |
| 3 | **Shared mode: merge everyone's events.** It keeps only the newest officer snapshot, so loot and boss kills that only another officer saw get lost. | Only matters with 2+ officers running the app, but then posts go missing silently. |
| 4 | **Split engine.py (about 1,500 lines) into smaller files**: Discord posting, boards, the addon-file reader, updates. | Easier to change one part without breaking another. |
| 5 | **Window smoke test in the automatic tests.** Open every page of the app on GitHub's test PC. | The app window is the only part with no automatic test. A broken page would ship unnoticed. |
| 6 | **Add a licence (MIT) and apply for free code signing (SignPath).** | Removes the "Windows protected your PC" warning. SignPath needs an open-source licence. Your decision. |
| 7 | **Finish one-click installs for members.** Put the CurseForge project ID in the .toc, add the Wago project, then point members to CurseForge or Wago. | Members get updates without zips. |
| 8 | **Wowhead links to the Forever site** once we confirm an item page works. | Classic links miss Forever's new items. |
| 9 | **Tell me when you edit a file yourself.** VS Code can hold an unsaved copy while I change the same file (this happened with the README). | Avoids one copy silently overwriting the other. |
| 10 | **Every release goes through `gh release create` with the changelog notes.** GitHub then builds the .exe and zips, and CurseForge packages the tag. | Already set up. Keeps releases one step. |
