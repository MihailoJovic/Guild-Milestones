# What's new

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
