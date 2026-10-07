# Guild Milestones

Turns your WoW guild roster into Discord announcements: level milestones, "first in the guild",
profession skill tiers, welcome posts, newcomer tips and a self-updating weekly digest.

It has two parts:

- **GuildMilestones/** - the in-game addon. It shouts level and profession milestones in guild chat and snapshots the guild roster.
- **Companion app** (`GuildMilestones.pyw`) - reads that snapshot and posts to a Discord webhook.

## For guild members (addon only)
No Python, no Discord setup. Download `GuildMilestones-addon-vX.Y.Z.zip`, unzip it into
`World of Warcraft\_<version>_\Interface\AddOns\` so you end up with `AddOns\GuildMilestones\GuildMilestones.toc`,
then log in. It's on by default. Settings: Esc > Options > AddOns > Guild Milestones, or `/gms options`.
Handy commands: `/gms crafters alchemy`, `/gms week`, `/gms test`.

## For officers (addon + companion app)
1. Install [Python](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Download this repo (green **Code** button, then **Download ZIP**) and unzip it somewhere you'll keep.
3. Double-click `GuildMilestones.pyw`.
4. On the Setup tab: paste your Discord webhook URL, pick your game folder, click **Install / update addon**.
5. In the game, type `/reload`.

## Update
Download the ZIP again, unzip over the old folder (replace files), and open the app.
Your settings live in `%APPDATA%\GuildMilestones`, so nothing is lost.

## Shared mode (several officers)
If more than one officer runs the app, turn on **Shared mode** so only one announces at a time and they all share one memory.
The guild leader sets it up once: see [`shared/SETUP.md`](shared/SETUP.md). What changed in each version is in [`CHANGES.md`](CHANGES.md).

## Privacy
Your webhook URL is stored only on your own computer, in `%APPDATA%\GuildMilestones\settings.json`.
It is never part of this repo. Never paste a webhook URL into an issue or a commit.
