# What's new

## v0.6.0
**The addon now announces milestones live in guild chat.**
- Level and profession milestones are shouted in guild chat by the addon itself, so friends just install it and leave it on.
- In-game settings panel (Esc > Options > AddOns), plus `/gms options`, `/gms crafters <profession>` and `/gms week`.
- The app skips posts the addon already shouted, and Discord embeds use class colours.
- Shorter "What's new" in the update dialog.


## v0.5.1
**Updates are easier to trust and easier to troubleshoot.**
- **Check for updates** now always tells you what it found, right on the Setup tab: the version on GitHub, the version you have, and when it checked. No more silence.
- The check skips GitHub's cache, so a new version shows up straight away instead of after a few minutes, and it has a backup route if the first one is blocked.
- The Setup tab shows which folder this copy of the app runs from, so you can tell which copy you're looking at.
- Problems are written to `%APPDATA%\GuildMilestones\error.log` instead of disappearing, and a broken window callback no longer freezes the app's background work.

## v0.5.0
**Shared mode: several officers can run the app without double posts.**
- New **Shared mode** tab. Everyone's app checks in with one small online notebook (a free Google Apps Script the guild leader sets up once, see `shared/SETUP.md`).
- Only one app announces at a time: the **Announcer**. The others show **Standby (Name is announcing)**.
- If the Announcer closes the app, goes offline, or keeps failing to post to Discord, another officer takes over automatically (within about 3 minutes, or right away when the Announcer clicks Stop).
- The notebook also holds the shared memory (levels, "firsts", weekly stats, the digest message), so a new Announcer carries on without repeats.
- Every officer's game data is shared too, so the Announcer always uses the freshest snapshot from anyone.
- If the app can't reach the shared service, it stays quiet rather than risk double posts.
- If posting fails several times in a row, the Announcer steps aside for 10 minutes. An announcement that couldn't be posted is skipped, never repeated.
- The Update dialog now shows what's new, taken from this file.
- Solo use is unchanged. Shared mode is off by default.

## v0.4.0
- One-click **Update to vX** button. The app checks GitHub and updates itself.

## v0.3.0
- Pick your game folder once. The app finds the addon's file and installs or updates the addon for you.
- Settings and memory now live in `%APPDATA%\GuildMilestones`, so replacing the app never wipes them.

## v0.2.0
- New window app with tabs, plus first in the guild, first of a class, max level, profession skill tiers, welcome posts, newcomer tips and the self-updating weekly digest.
