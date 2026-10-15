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
(not `GuildMilestones\GuildMilestones\...`), then log in. If a guildmate has a newer version, the addon tells you in chat. It's on by default. Which milestones count is decided by the guild (set in the officers' app), so there is nothing to type. Settings: Esc > Options > AddOns > Guild Milestones, or `/gms options`.
Type `/gms` to open the Guild Milestones window (your progress, the guild race, crafters, the week, settings).
Handy commands: `/gms help`, `/gms test`, `/gms crafters alchemy`.

## For officers (addon + companion app)
1. Install [Python](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Download this repo (green **Code** button, then **Download ZIP**) and unzip it somewhere you'll keep.
3. Double-click `GuildMilestones.pyw`.
4. **Discord** page: follow the steps to make a webhook and paste it in. Click **Send examples of every post** to see what your guild will get.
5. **Game & addon** page: click **Find it for me**, pick the WoW: Forever folder, then **Install / update addon**.
6. In the game, type `/reload`, then click **Start watching**. The app sees new data whenever you log out or `/reload`.

## Update
Download the ZIP again, unzip over the old folder (replace files), and open the app.
Your settings live in `%APPDATA%\GuildMilestones`, so nothing is lost.

## Shared mode (several officers)
If more than one officer runs the app, turn on **Shared mode** so only one announces at a time and they all share one memory.
The guild leader sets it up once: see [`shared/SETUP.md`](shared/SETUP.md). What changed in each version is in [`CHANGES.md`](CHANGES.md).

## Privacy
Your webhook URL is stored only on your own computer, in `%APPDATA%\GuildMilestones\settings.json`.
It is never part of this repo. Never paste a webhook URL into an issue or a commit.
