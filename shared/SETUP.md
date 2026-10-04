# Shared mode: one-time setup (guild leader only)

Shared mode lets several officers run the app at once without double posts. It needs a tiny free
"notebook" online. You make it once, in about 10 minutes, with your Google account.

1. Go to https://script.google.com and click **New project**. Name it "Guild Milestones shared service".
2. Delete the code that's already there. Open `shared/SharedStore.gs` from this repo, copy all of it, and paste it in.
3. Near the top, change the `TOKEN` line to a long password of your own (30+ letters and numbers). Press **Ctrl+S** to save.
4. Click **Deploy** (top right), then **New deployment**. Click the gear next to "Select type" and choose **Web app**.
5. Set **Execute as: Me** and **Who has access: Anyone**. Click **Deploy**.
6. Google asks you to authorise it. Click **Authorize access**, pick your account, then **Advanced**, then **Go to Guild Milestones shared service (unsafe)**, then **Allow**. The warning appears because it's your own unpublished script.
7. Copy the **Web app URL** (it ends in `/exec`). Paste it into a browser tab. It should say "Guild Milestones shared service is running."
8. Send each officer the URL and the password in a **private message**. They paste both on the app's **Shared mode** tab, add their name, tick "Use shared mode", and click **Test connection**.

## Good to know
- If you edit the script later: **Deploy > Manage deployments > pencil icon > Version: New version > Deploy**. The URL stays the same.
- To wipe the shared memory and start fresh, open the script, choose the function `resetEverything` in the toolbar, and click **Run**.
- The shared notebook stores member names, levels, classes and professions. Keep the URL and password inside the officer group.
- Google's free limits are generous. Each app checks in about once a minute, which a handful of officers will not come near.
