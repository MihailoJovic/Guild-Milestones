# Guild Milestones

Turns your WoW guild roster into Discord announcements: level milestones, "first in the guild",
profession skill tiers, welcome posts, newcomer tips, a self-updating weekly digest with awards,
and a Race to 60 board. Made for World of Warcraft: Forever.

It has two parts:

- **GuildMilestones/** - the in-game addon. It shouts level and profession milestones in guild chat and snapshots the guild roster.
- **Companion app** (`GuildMilestones.pyw`) - reads that snapshot and posts to a Discord webhook.

## For guild members (addon only)
No Python, no Discord setup. Download the newest `GuildMilestones-addon-vX.Y.Z.zip` from the
[Releases page](https://github.com/MihailoJovic/Guild-Milestones/releases), unzip it into
your WoW: Forever folder's `Interface\AddOns\` so you end up with `AddOns\GuildMilestones\GuildMilestones.toc`
(not `GuildMilestones\GuildMilestones\...`), then log in. If a guildmate has a newer version, the addon tells you in chat. It's on by default. Which milestones count is decided by the guild (set in the guild leaders' app), so there is nothing to type. Settings: click the GM button by your minimap, or type `/gms`.
Type `/gms` to open the Guild Milestones window (your progress, the guild race, crafters, the week, settings).
Handy commands: `/gms help`, `/gms test`, `/gms crafters alchemy`.

## For guild leaders (addon + companion app)
1. **[Download GuildMilestones.exe](https://github.com/MihailoJovic/Guild-Milestones/releases/latest/download/GuildMilestones.exe)**
   (this link always gets the newest version) and put it in a folder you'll keep, like `Documents\Guild Milestones`.
   No unzipping needed. It's also inside the `GuildMilestones-kit` zip on the
   [Releases page](https://github.com/MihailoJovic/Guild-Milestones/releases/latest).
2. Double-click it. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**
   (the app isn't code-signed yet, so Windows doesn't recognise it).
3. Follow the **Get set up** checklist on the Home page: connect Discord, find your game folder, install the addon,
   then log in to WoW once and type `/reload`.
4. Click **Start watching**. Turn on **Start with Windows** (Game & addon page) and it keeps watching from the tray.

Prefer running from source? Install [Python](https://www.python.org/downloads/), download this repo and double-click
`GuildMilestones.pyw`.

## Setting up Discord (once, about 5 minutes)
1. Make a category **GUILD MILESTONES** with two text channels: **#guild-feed** (live posts; people can reply and react)
   and **#guild-boards** (self-updating boards).
2. Make **#guild-boards** read-only: Edit Channel → Permissions → @everyone → Send Messages off.
3. In each channel: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL.
   Paste them on the app's **Discord** page (Feed channel and Boards channel). No need to name the webhooks or give them
   a picture: posts always show as *Guild Milestones* with the GM icon.
4. Click **Send examples of every post**, delete the examples once you've had a look, then go to **Boards** and click
   **Tidy the boards channel**.

What goes where:

| #guild-feed | #guild-boards (top to bottom) |
|---|---|
| Level milestones and "first in the guild" | 🏁 Race to 60 + guild goals |
| 🐎 Mounts, 🏆 guild firsts, 🏁 "Road to 60" cards | 🏆 Hall of Fame |
| Epic loot, boss kills, welcomes | 🔑 Attunements & keys |
| 🏅 Friday MVP vote | 🧰 Crafters |
| Quiet extras: skill tiers, rare loot, attunements | 🧭 Looking for group |
| 🪦 Farewells (Hardcore guilds) | 🪦 Fallen Heroes (Hardcore only), 📅 Weekly digest |

## Update
The app tells you when there's a new version: click **Update** at the bottom left. Your settings live in
`%APPDATA%\GuildMilestones`, so nothing is lost.

## Shared mode (several officers)
If more than one officer runs the app, turn on **Shared mode** so only one announces at a time and they all share one memory.
The guild leader sets it up once: see [`shared/SETUP.md`](shared/SETUP.md). What changed in each version is in [`CHANGES.md`](CHANGES.md).

## Privacy
Your webhook URL is stored only on your own computer, in `%APPDATA%\GuildMilestones\settings.json`.
It is never part of this repo. Never paste a webhook URL into an issue or a commit.
