#!/usr/bin/env python3
"""Guild Milestones - companion app. Double-click to run (or build the .exe with build_exe.bat)."""
import os, queue, subprocess, sys, threading, time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine as E

BG, PANEL, FIELD = "#1e1f22", "#2b2d31", "#383a40"
TEXT, MUTED, ACCENT = "#f2f3f5", "#b5bac1", "#5865f2"
GOOD, BAD, AMBER = "#23a559", "#f23f42", "#f0b232"
FONT, FONT_B = ("Segoe UI", 10), ("Segoe UI Semibold", 10)


def apply_theme(root):
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=PANEL,
                lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, font=FONT, focuscolor=BG)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
    s.configure("Section.TLabel", font=FONT_B)
    s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=6, borderwidth=0)
    s.configure("TButton", background=FIELD, foreground=TEXT, padding=(12, 7), borderwidth=0)
    s.map("TButton", background=[("active", "#4a4d55"), ("disabled", PANEL)], foreground=[("disabled", "#6d6f78")])
    s.configure("Go.TButton", background=ACCENT, foreground="white", font=("Segoe UI Semibold", 11), padding=(22, 10))
    s.map("Go.TButton", background=[("active", "#4752c4"), ("disabled", "#3a3f7a")])
    s.configure("Stop.TButton", background=BAD, foreground="white", font=("Segoe UI Semibold", 11), padding=(22, 10))
    s.map("Stop.TButton", background=[("active", "#c93538")])
    s.configure("TCheckbutton", background=BG, foreground=TEXT)
    s.map("TCheckbutton", background=[("active", BG)])
    s.configure("TLabelframe", background=BG, bordercolor="#3f4147")
    s.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=FONT_B)
    s.configure("TNotebook", background=BG, borderwidth=0)
    s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 9), borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", TEXT)])
    s.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=TEXT, padding=5)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])


def textbox(parent, height):
    return tk.Text(parent, height=height, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat",
                   font=FONT, wrap="word", padx=8, pady=6, highlightthickness=0)


class App:
    def __init__(self, root):
        self.root, self.q, self.stop, self.running, self.latest = root, queue.Queue(), None, False, None
        root.title(f"Guild Milestones {E.APP_VERSION}")
        root.geometry("860x700")
        root.minsize(780, 640)
        apply_theme(root)

        cfg = E.load_config()
        self.s = {k: tk.StringVar(value=str(cfg[k])) for k in
                  ("webhook", "digest_webhook", "game_folder", "milestones", "max_level", "tiers", "level_msg", "welcome_msg",
                   "shared_url", "shared_token", "my_name")}
        self.b = {k: tk.BooleanVar(value=bool(cfg[k])) for k in
                  ("auto_start", "auto_update_addon", "announce_levels", "announce_firsts", "announce_tiers", "welcome_new", "digest_enabled", "shared_on", "skip_shouted", "event_loot", "event_boss", "event_death", "event_quest")}
        self.week = tk.StringVar(value=E.WEEKDAYS[int(cfg["week_start"]) % 7])
        self.device_id, self.engine = cfg["device_id"], None

        root.report_callback_exception = self.on_ui_error
        self.header()
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        for title, build in (("  Setup  ", self.tab_setup), ("  Announcements  ", self.tab_announce),
                             ("  Weekly digest  ", self.tab_digest), ("  Shared mode  ", self.tab_shared),
                             ("  Activity  ", self.tab_log)):
            page = ttk.Frame(nb, padding=18)
            nb.add(page, text=title)
            build(page)
        self.tips.insert("1.0", cfg["tips"])
        self.refresh_addon()
        self.maybe_update_addon()

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.pump()
        self.set_running(False)
        root.after(2000, lambda: self.check_update(False))
        if cfg["auto_start"] and cfg["webhook"] and os.path.isdir(cfg["game_folder"]):
            root.after(600, lambda: self.start(quiet=True))

    # ---------- layout ----------
    def header(self):
        bar = ttk.Frame(self.root, padding=(22, 18, 22, 8))
        bar.pack(fill="x")
        left = ttk.Frame(bar)
        left.pack(side="left")
        ttk.Label(left, text="Guild Milestones", style="Title.TLabel").pack(anchor="w")
        self.status = ttk.Label(left, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(2, 0))
        self.go = ttk.Button(bar, text="Start watching", style="Go.TButton", command=self.toggle)
        self.go.pack(side="right")
        self.upd = ttk.Button(bar, text="", command=self.do_update)      # shown only when an update exists

    def entry_row(self, parent, label, var, hint=None, row=0, buttons=()):
        ttk.Label(parent, text=label, style="Section.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel", wraplength=700, justify="left").grid(
                row=row + 1, column=0, columnspan=3, sticky="w")
        ttk.Entry(parent, textvariable=var).grid(row=row + 2, column=0, sticky="ew", pady=(6, 0))
        for i, (text, cmd) in enumerate(buttons):
            ttk.Button(parent, text=text, command=cmd).grid(row=row + 2, column=1 + i, padx=(8, 0), pady=(6, 0))

    def tab_setup(self, p):
        p.columnconfigure(0, weight=1)
        self.entry_row(p, "1 · Discord webhook", self.s["webhook"],
                       "In Discord: Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.",
                       row=0, buttons=[("Send test", self.test)])
        self.entry_row(p, "2 · Game folder", self.s["game_folder"],
                       "The folder that contains Interface and WTF, like …\\World of Warcraft\\_retail_ "
                       "(or _classic_beta_ for Forever). Pick it once and the app does the rest.",
                       row=3, buttons=[("Browse…", self.browse), ("Find it for me", self.find)])
        self.addon_lbl = ttk.Label(p, text="", style="Muted.TLabel")
        self.addon_lbl.grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.addon_btn = ttk.Button(p, text="Install / update addon", command=self.install_addon)
        self.addon_btn.grid(row=6, column=1, columnspan=2, sticky="e", padx=(8, 0), pady=(8, 0))
        self.entry_row(p, "3 · Digest channel (optional)", self.s["digest_webhook"],
                       "Another webhook URL if you want the weekly digest in its own channel. Empty = same channel.",
                       row=7)
        ttk.Checkbutton(p, text="Start watching automatically when I open this app",
                        variable=self.b["auto_start"]).grid(row=10, column=0, columnspan=3, sticky="w", pady=(20, 0))
        ttk.Checkbutton(p, text="Keep the addon up to date for me when this app updates",
                        variable=self.b["auto_update_addon"]).grid(row=11, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(p, text=f"This app is version {E.APP_VERSION}", style="Muted.TLabel").grid(
            row=12, column=0, sticky="w", pady=(22, 0))
        ttk.Button(p, text="Check for updates", command=lambda: self.check_update(True)).grid(
            row=12, column=1, columnspan=2, sticky="e", padx=(8, 0), pady=(22, 0))
        self.upd_lbl = ttk.Label(p, text="Not checked yet.", style="Muted.TLabel", wraplength=640, justify="left")
        self.upd_lbl.grid(row=13, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(p, text=f"This copy of the app runs from: {E.APP_DIR}", style="Muted.TLabel",
                  wraplength=640, justify="left").grid(row=14, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def tab_announce(self, p):
        p.columnconfigure(0, weight=1, uniform="c")
        p.columnconfigure(1, weight=1, uniform="c")
        left = ttk.LabelFrame(p, text=" What should the bot announce? ", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for key, text in (("announce_levels", "Level milestones"),
                          ("announce_firsts", "“First in the guild” and “first of a class”"),
                          ("announce_tiers", "Profession skill tiers"),
                          ("welcome_new", "Welcome new members"),
                          ("skip_shouted", "Skip posts the addon already shouted in guild chat"),
                          ("event_loot", "Loot: rich post with the item's icon and link"),
                          ("event_boss", "Boss kills"),
                          ("event_death", "Deaths"),
                          ("event_quest", "Quest turn-ins")):
            ttk.Checkbutton(left, text=text, variable=self.b[key]).pack(anchor="w", pady=3)

        nums = ttk.LabelFrame(p, text=" Numbers ", padding=12)
        nums.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        nums.columnconfigure(1, weight=1)
        for r, (label, key) in enumerate((("Milestone levels", "milestones"), ("Max level", "max_level"),
                                          ("Skill tiers", "tiers"))):
            ttk.Label(nums, text=label).grid(row=r, column=0, sticky="w", pady=4)
            ttk.Entry(nums, textvariable=self.s[key], width=26).grid(row=r, column=1, sticky="ew", padx=(10, 0))
        ttk.Label(nums, style="Muted.TLabel", wraplength=300, justify="left",
                  text="These also go to everyone's addon: an officer's addon puts them in the guild's Info "
                       "text, and each member's addon reads them at login. Nothing to sync by hand.").grid(
                  row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(nums, text="Copy the Guild Info line", command=self.copy_line).grid(
                  row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        msgs = ttk.LabelFrame(p, text=" Messages · {name} {level} {cls} get filled in ", padding=12)
        msgs.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        msgs.columnconfigure(1, weight=1)
        for r, (label, key) in enumerate((("Level-up", "level_msg"), ("Welcome", "welcome_msg"))):
            ttk.Label(msgs, text=label).grid(row=r, column=0, sticky="w", pady=4)
            ttk.Entry(msgs, textvariable=self.s[key]).grid(row=r, column=1, sticky="ew", padx=(10, 0))

        tips = ttk.LabelFrame(p, text=" Newcomer tips · one per line, like  10=Pick a profession! ", padding=12)
        tips.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.tips = textbox(tips, 4)
        self.tips.pack(fill="x")

    def copy_line(self):
        line = E.addon_line(self.collect())
        self.clipboard_clear()
        self.clipboard_append(line)
        messagebox.showinfo("Copied", "Copied:\n\n" + line + "\n\nOnly needed if the automatic publish doesn't work: "
                            "paste it anywhere in the Guild Info box (Guild window > Info).")

    def tab_digest(self, p):
        ttk.Checkbutton(p, text="Keep a weekly digest message in Discord", variable=self.b["digest_enabled"]).pack(anchor="w")
        ttk.Label(p, style="Muted.TLabel", wraplength=700, justify="left",
                  text="One message that edits itself as the week goes on: new members, top level-ups, "
                       "milestones, skill tiers and who can craft what. A fresh one starts each week.").pack(anchor="w", pady=(6, 18))
        row = ttk.Frame(p)
        row.pack(anchor="w")
        ttk.Label(row, text="Week starts on").pack(side="left")
        ttk.Combobox(row, textvariable=self.week, values=E.WEEKDAYS, state="readonly", width=12).pack(side="left", padx=10)
        ttk.Button(p, text="Post / refresh the digest now", command=self.digest_now).pack(anchor="w", pady=(22, 0))
        ttk.Label(p, style="Muted.TLabel", text="Handy for testing. It needs the addon file from step 2 on the Setup tab.").pack(anchor="w", pady=(6, 0))

    def tab_shared(self, p):
        p.columnconfigure(0, weight=1)
        ttk.Checkbutton(p, text="Use shared mode (for when more than one officer runs this app)",
                        variable=self.b["shared_on"]).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(p, style="Muted.TLabel", wraplength=700, justify="left",
                  text="Everyone's app checks in with one shared online notebook. Only one app announces at a time "
                       "(the Announcer), the others stand by, and if the Announcer goes offline or keeps failing, "
                       "another officer takes over automatically. Leave this off if you're the only one running it."
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.entry_row(p, "Web address of the shared service", self.s["shared_url"],
                       "The guild leader gives you this. It starts with https://script.google.com/", row=2)
        self.entry_row(p, "Password", self.s["shared_token"],
                       "Also from the guild leader. Keep it inside the officer group.", row=5)
        self.entry_row(p, "Your name", self.s["my_name"],
                       "Shown to the other officers, like \"Mikoya is announcing\".", row=8,
                       buttons=[("Test connection", self.test_shared)])

    def tab_log(self, p):
        self.box = textbox(p, 10)
        self.box.configure(state="disabled")
        self.box.pack(fill="both", expand=True)
        p.pack_propagate(True)

    # ---------- plumbing ----------
    def on_ui_error(self, exc, val, tb):
        E.log_error(f"UI error: {val!r}")
        self.log(f"Something went wrong: {val}")

    def log(self, text):
        self.q.put(f"{time.strftime('%H:%M:%S')}   {text}\n")

    def pump(self):
        try:
            while True:
                line = self.q.get_nowait()
                if callable(line):
                    try:
                        line()
                    except Exception as e:
                        E.log_error(f"UI callback failed: {e!r}")
                        self.log(f"Something went wrong in the window: {e}")
                    continue
                self.box.configure(state="normal")
                self.box.insert("end", line)
                self.box.see("end")
                self.box.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def set_running(self, on):
        self.running = on
        self.go.configure(text="Stop" if on else "Start watching", style="Stop.TButton" if on else "Go.TButton")
        if on and self.b["shared_on"].get():
            self.status.configure(text="●  Connecting to the shared service...", foreground=MUTED)
        else:
            self.status.configure(text="●  Watching your guild" if on else "●  Not running",
                                  foreground=GOOD if on else MUTED)

    def set_status(self, kind, text):
        if not self.running:
            return
        label = {"announcer": "●  Announcer: you're posting for the guild",
                 "standby": "●  " + text.rstrip("."),
                 "offline": "●  Can't reach the shared service, staying quiet"}.get(kind, "●  " + text)
        color = {"announcer": GOOD, "standby": AMBER, "offline": BAD}.get(kind, MUTED)
        self.status.configure(text=label, foreground=color)

    def engine_status(self, kind, text):
        self.q.put(lambda: self.set_status(kind, text))

    def collect(self):
        c = {k: v.get().strip() for k, v in self.s.items()}
        c.update({k: v.get() for k, v in self.b.items()})
        c["tips"] = self.tips.get("1.0", "end").strip()
        c["savedvars"] = ""
        c["device_id"] = self.device_id
        c["week_start"] = E.WEEKDAYS.index(self.week.get())
        return c

    def problem(self, c, need_file=True):
        if not c["webhook"].startswith("https://"):
            return "Paste your Discord webhook URL in step 1 on the Setup tab."
        if c["shared_on"]:
            if not c["shared_url"].startswith("https://") or not c["shared_token"]:
                return "Shared mode is on, so fill in the web address and password on the Shared mode tab (or turn it off)."
        else:
            if not os.path.isdir(c["game_folder"]):
                return "Pick your game folder in step 2 (the one that contains Interface and WTF)."
            if need_file and not E.resolve_savedvars(c):
                return ("I can't see the addon's file yet.\nInstall the addon (button on the Setup tab), then in the game "
                        "type /reload followed by /gms save.")
        if not c["max_level"].isdigit():
            return "Max level should be a number."
        if not E.nums(c["milestones"]):
            return "Add at least one milestone level, like 10, 20, 30."
        for key in ("level_msg", "welcome_msg"):
            try:
                c[key].format(name="X", level=1, cls="Y")
            except Exception:
                return "In messages, only {name}, {level} and {cls} can go inside curly brackets."
        return None

    def browse(self):
        p = filedialog.askdirectory(title="Pick your game folder (the one with Interface and WTF inside)")
        if p:
            self.s["game_folder"].set(os.path.normpath(p))
            self.refresh_addon()

    def find(self):
        hits = E.find_game_folders()
        if hits:
            self.s["game_folder"].set(hits[0])
            self.log(f"Found your game folder: {hits[0]}")
            self.refresh_addon()
        else:
            messagebox.showinfo("Couldn't find it", "No luck finding it automatically.\n\nClick Browse and pick the "
                                "folder named _retail_ (or _classic_beta_ for Forever) inside World of Warcraft.")

    def refresh_addon(self):
        g = self.s["game_folder"].get().strip()
        if not os.path.isdir(g):
            self.addon_lbl.configure(text="Pick your game folder to install the addon.", foreground=MUTED)
            self.addon_btn.state(["disabled"])
            return
        self.addon_btn.state(["!disabled"])
        have, new = E.addon_status(g)
        new = new or "?"
        if have is None:
            text, col = f"The addon isn't installed yet (this app has v{new}).", AMBER
        elif have != new:
            text, col = f"Addon v{have} is installed. v{new} is available.", AMBER
        else:
            text, col = f"Addon v{have} is installed and up to date ✔", GOOD
        self.addon_lbl.configure(text=text, foreground=col)

    def install_addon(self):
        ok, msg = E.install_addon(self.s["game_folder"].get().strip())
        self.log(msg + (" In the game, type /reload." if ok else ""))
        self.refresh_addon()
        if ok:
            messagebox.showinfo("Addon installed", msg + "\n\nIn the game, type /reload to load it.")
        else:
            messagebox.showwarning("Couldn't install", msg)

    def maybe_update_addon(self):
        g = self.s["game_folder"].get().strip()
        if not (self.b["auto_update_addon"].get() and os.path.isdir(g)):
            return
        have, new = E.addon_status(g)
        if new and have != new:
            ok, msg = E.install_addon(g)
            self.log(msg + (" In the game, type /reload to load it." if ok else ""))
            self.refresh_addon()

    def test_shared(self):
        c = self.collect()
        E.save_config(c)
        if not c["shared_url"].startswith("https://") or not c["shared_token"]:
            return messagebox.showwarning("Fill these in first", "Add the web address and the password first.")
        def run():
            ok, res, err = E.SharedStore(c["shared_url"], c["shared_token"], c["device_id"], c["my_name"]).status()
            if not ok:
                self.q.put(lambda: messagebox.showwarning("Couldn't connect", f"That didn't work: {err}"))
                return
            who = res.get("leaderName") or "nobody right now"
            text = f"Connected!\n\nCurrent announcer: {who}\nMembers in the shared snapshot: {res.get('members', 0)}"
            self.q.put(lambda: messagebox.showinfo("Shared mode", text))
            self.log(f"Shared service reached. Announcer right now: {who}.")
        threading.Thread(target=run, daemon=True).start()

    def test(self):
        c = self.collect()
        E.save_config(c)
        if not c["webhook"].startswith("https://"):
            return messagebox.showwarning("Webhook needed", "Paste your Discord webhook URL first.")
        def run():
            ok, _, err = E.post(c["webhook"], content="✅ Guild Milestones is connected!")
            self.log("Test message sent. Look in Discord." if ok else f"Test failed: {err}")
        threading.Thread(target=run, daemon=True).start()

    def digest_now(self):
        c = self.collect()
        c["digest_enabled"] = True
        E.save_config(self.collect())
        msg = self.problem(c)
        if msg:
            return messagebox.showwarning("One thing first", msg)
        def run():
            eng = E.Engine(c, self.log)
            try:
                eng.check(force_digest=True)
                if eng.shared and eng.role == "standby":
                    self.log("Only the Announcer can post the digest. Ask them, or wait for the role to move.")
            except Exception as e:
                self.log(f"Digest problem: {e}")
            if eng.shared and not self.running:
                eng.release()
        threading.Thread(target=run, daemon=True).start()

    def check_update(self, manual):
        if manual:
            self.upd_lbl.configure(text="Checking GitHub...")
        def work():
            rep = E.check_report()
            stamp = time.strftime("%H:%M")
            self.q.put(lambda: self.upd_lbl.configure(text=f"Checked at {stamp}. {rep['text']}"))
            if rep["newer"]:
                self.q.put(lambda: self.show_update(rep["latest"]))
            elif manual:
                title = "Up to date" if rep["ok"] else "Couldn't check"
                self.q.put(lambda: messagebox.showinfo(title, rep["text"]))
        threading.Thread(target=work, daemon=True).start()

    def show_update(self, latest):
        self.latest = latest
        self.upd.configure(text=f"Update to v{latest}")
        self.upd.pack(side="right", padx=(0, 12))
        self.log(f"A new version is available: v{latest}. Click the Update button at the top.")

    def do_update(self):
        if getattr(sys, "frozen", False):
            return messagebox.showinfo("Use the .pyw version", "The .exe can't update itself.\nOpen GuildMilestones.pyw instead, "
                                       "and updating becomes one click.")
        notes = E.latest_notes(self.latest)
        extra = f"\n\nWhat's new: {notes[:160]}" if notes else ""
        if not messagebox.askyesno("Update", f"Update to v{self.latest}?\n\nThe app will restart. Your settings are kept.{extra}"):
            return
        self.upd.state(["disabled"])
        self.log("Downloading the update...")
        def work():
            ok, msg = E.apply_update()
            self.q.put(lambda: self.update_done(ok, msg))
        threading.Thread(target=work, daemon=True).start()

    def update_done(self, ok, msg):
        if not ok:
            self.upd.state(["!disabled"])
            self.log(msg)
            return messagebox.showwarning("Update failed", msg)
        self.log("Updated! Restarting...")
        subprocess.Popen([sys.executable, str(E.APP_DIR / "GuildMilestones.pyw")], cwd=str(E.APP_DIR))
        self.close()

    def toggle(self):
        self.halt() if self.running else self.start()

    def start(self, quiet=False):
        c = self.collect()
        E.save_config(c)
        msg = self.problem(c)
        if msg:
            if not quiet:
                messagebox.showwarning("One thing first", msg)
            return
        self.maybe_update_addon()
        self.stop = threading.Event()
        self.engine = E.Engine(c, self.log, status=self.engine_status)
        threading.Thread(target=self.engine.run, args=(self.stop,), daemon=True).start()
        self.set_running(True)

    def halt(self):
        if self.stop:
            self.stop.set()
        self.set_running(False)

    def close(self):
        try:
            E.save_config(self.collect())
        except Exception:
            pass
        eng = self.engine
        self.halt()
        if eng and eng.shared:                                   # hand over the announcer role before closing
            t = threading.Thread(target=eng.release, daemon=True)
            t.start()
            t.join(4)
        self.root.destroy()


def main():
    threading.excepthook = lambda a: E.log_error(f"thread {a.thread.name if a.thread else '?'} crashed: {a.exc_value!r}")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
