# Guild Milestones

Turns your WoW guild roster into Discord announcements: level milestones, "first in the guild",
profession skill tiers, welcome posts, newcomer tips and a self-updating weekly digest.

It has two parts:

- **GuildMilestones/** - the in-game addon. It snapshots the guild roster.
- **Companion app** (`GuildMilestones.pyw`) - reads that snapshot and posts to a Discord webhook.

## Install
1. Install [Python](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Download this repo (green **Code** button, then **Download ZIP**) and unzip it somewhere you'll keep.
3. Double-click `GuildMilestones.pyw`.
4. On the Setup tab: paste your Discord webhook URL, pick your game folder, click **Install / update addon**.
5. In the game, type `/reload`.

## Update
Download the ZIP again, unzip over the old folder (replace files), and open the app.
Your settings live in `%APPDATA%\GuildMilestones`, so nothing is lost.

## Privacy
Your webhook URL is stored only on your own computer, in `%APPDATA%\GuildMilestones\settings.json`.
It is never part of this repo. Never paste a webhook URL into an issue or a commit.
