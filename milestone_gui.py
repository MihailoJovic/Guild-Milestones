#!/usr/bin/env python3
"""Guild Milestones - companion app. Double-click GuildMilestones.pyw to run it."""
import os, queue, subprocess, sys, threading, time
import tkinter as tk
from tkinter import filedialog, messagebox

import engine as E

# Flat dark panels, thin borders and one warm accent: the look of modern game launchers and UI packs.
BG, SIDE, CARD, CARD2 = "#0e1015", "#12151c", "#171a23", "#1f2330"
BORDER, FIELD, HOVER = "#262b38", "#0b0d12", "#232838"
TEXT, MUTED, DIM = "#e9ecf2", "#8b93a7", "#5b6275"
GOLD, GOLD_HI, GOLD_INK = "#f2b84b", "#ffc966", "#1a1305"
GOOD, BAD, INFO = "#3ccf8e", "#ff5c5c", "#5aa9ff"
F = "Segoe UI"
FONT, FONT_S, FONT_B = (F, 10), (F, 9), (F + " Semibold", 10)
FONT_H1, FONT_H2, FONT_BIG = (F + " Semibold", 18), (F + " Semibold", 12), (F + " Semibold", 22)


# ---------------------------------------------------------------- widgets
class Btn(tk.Label):
    """A flat button. kind: primary (gold), ghost (dark), danger (red)."""
    STYLES = {"primary": (GOLD, GOLD_HI, GOLD_INK), "ghost": (CARD2, HOVER, TEXT), "danger": (BAD, "#ff7878", "white")}

    def __init__(self, parent, text, command, kind="ghost", padx=14, pady=7, font=FONT_B):
        bg, hi, fg = self.STYLES[kind]
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2")
        self.cmd, self.colors, self.enabled = command, (bg, hi, fg), True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=self.colors[1]))
        self.bind("<Leave>", lambda e: self.configure(bg=self.colors[0] if self.enabled else CARD))
        self.bind("<Button-1>", lambda e: self.enabled and self.cmd and self.cmd())

    def set_kind(self, kind, text=None):
        self.colors = self.STYLES[kind]
        self.configure(bg=self.colors[0], fg=self.colors[2], **({"text": text} if text else {}))

    def set_enabled(self, on):
        self.enabled = on
        self.configure(bg=self.colors[0] if on else CARD, fg=self.colors[2] if on else DIM,
                       cursor="hand2" if on else "arrow")


class Toggle(tk.Canvas):
    """A pill switch bound to a BooleanVar."""
    def __init__(self, parent, var, bg=CARD, command=None):
        super().__init__(parent, width=40, height=22, bg=bg, highlightthickness=0, cursor="hand2")
        self.var, self.command = var, command
        self.bind("<Button-1>", self.flip)
        var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def flip(self, _=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        on = bool(self.var.get())
        fill = GOLD if on else "#353b4b"
        self.create_oval(1, 1, 21, 21, fill=fill, outline=fill)
        self.create_oval(19, 1, 39, 21, fill=fill, outline=fill)
        self.create_rectangle(11, 1, 29, 21, fill=fill, outline=fill)
        x = 29 if on else 11
        self.create_oval(x - 8, 3, x + 8, 19, fill=GOLD_INK if on else TEXT, outline="")


def card(parent, title=None, sub=None, pad=16):
    """A bordered card. Returns the inner frame to put things in."""
    outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    inner = tk.Frame(outer, bg=CARD)
    inner.pack(fill="both", expand=True, padx=pad, pady=pad - 2)
    if title:
        tk.Label(inner, text=title.upper(), bg=CARD, fg=GOLD, font=(F + " Semibold", 9)).pack(anchor="w")
    if sub:
        tk.Label(inner, text=sub, bg=CARD, fg=MUTED, font=FONT_S, wraplength=640, justify="left").pack(anchor="w", pady=(2, 0))
    inner.outer = outer
    return inner


def entry(parent, var, secret=False, width=None):
    """A dark text field. Secret fields show dots, with a Show button."""
    row = tk.Frame(parent, bg=parent["bg"])
    e = tk.Entry(row, textvariable=var, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=GOLD, show="•" if secret else "",
                 **({"width": width} if width else {}))
    e.pack(side="left", fill="x", expand=True, ipady=6, ipadx=6)
    if secret:
        def flip():
            hidden = e.cget("show") == "•"
            e.configure(show="" if hidden else "•")
            b.configure(text="Hide" if hidden else "Show")
        b = tk.Label(row, text="Show", bg=parent["bg"], fg=MUTED, font=FONT_S, cursor="hand2", padx=8)
        b.bind("<Button-1>", lambda ev: flip())
        b.pack(side="left")
    row.entry = e
    return row


def label(parent, text, muted=False, font=None, wrap=640, **kw):
    return tk.Label(parent, text=text, bg=parent["bg"], fg=MUTED if muted else TEXT, font=font or (FONT_S if muted else FONT),
                    wraplength=wrap, justify="left", **kw)


def toggle_row(parent, var, title, sub=None, title_font=FONT_B, pady=(10, 0)):
    """Text on the left (wrapping to fit), a switch on the right."""
    row = tk.Frame(parent, bg=parent["bg"])
    row.pack(fill="x", pady=pady)
    row.columnconfigure(0, weight=1)
    tk.Label(row, text=title, bg=row["bg"], fg=TEXT, font=title_font, anchor="w", justify="left").grid(row=0, column=0, sticky="w")
    if sub:
        s = tk.Label(row, text=sub, bg=row["bg"], fg=MUTED, font=FONT_S, anchor="w", justify="left")
        s.grid(row=1, column=0, sticky="ew")
        row.bind("<Configure>", lambda e: s.configure(wraplength=max(120, e.width - 70)))
    Toggle(row, var, bg=row["bg"]).grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))
    return row


class ScrollPage(tk.Frame):
    """A page that scrolls when it's taller than the window."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.pack(fill="both", expand=True)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, e):
        if not self.winfo_ismapped():
            return
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")


# ---------------------------------------------------------------- the app
NAV = [("home", "⌂", "Home"), ("discord", "✉", "Discord"), ("announce", "★", "Announcements"),
       ("boards", "▤", "Boards"), ("game", "⚔", "Game & addon"), ("shared", "⇄", "Shared mode"), ("log", "≡", "Activity")]


class App:
    def __init__(self, root):
        self.root, self.q, self.stop, self.running, self.latest, self.engine = root, queue.Queue(), None, False, None, None
        root.title(f"Guild Milestones {E.APP_VERSION}")
        root.geometry("1060x740")
        root.minsize(940, 640)
        root.configure(bg=BG)

        cfg = E.load_config()
        self.s = {k: tk.StringVar(value=str(cfg[k])) for k in
                  ("webhook", "digest_webhook", "game_folder", "milestones", "max_level", "tiers", "level_msg", "welcome_msg",
                   "shared_url", "shared_token", "my_name")}
        self.b = {k: tk.BooleanVar(value=bool(cfg[k])) for k in
                  ("auto_start", "auto_update_addon", "announce_levels", "announce_firsts", "announce_tiers", "welcome_new",
                   "welcome_back", "digest_enabled", "ladder_enabled", "shared_on", "skip_shouted", "event_loot", "event_boss",
                   "event_death", "event_quest")}
        self.week = tk.StringVar(value=E.WEEKDAYS[int(cfg["week_start"]) % 7])
        self.device_id = cfg["device_id"]
        self.tested = False
        self.log_lines = []

        root.report_callback_exception = self.on_ui_error
        self.build_shell()
        self.tips.insert("1.0", cfg["tips"])
        self.show("home")
        self.refresh_addon()
        self.maybe_update_addon()

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.pump()
        self.set_running(False)
        self.tick()
        root.after(2000, lambda: self.check_update(False))
        if cfg["auto_start"] and cfg["webhook"] and os.path.isdir(cfg["game_folder"]):
            root.after(600, lambda: self.start(quiet=True))

    # ------------------------------------------------------------ layout
    def build_shell(self):
        side = tk.Frame(self.root, bg=SIDE, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self.root, bg=BORDER, width=1).pack(side="left", fill="y")

        brand = tk.Frame(side, bg=SIDE)
        brand.pack(fill="x", padx=20, pady=(22, 18))
        tk.Label(brand, text="GUILD", bg=SIDE, fg=GOLD, font=(F + " Semibold", 11)).pack(anchor="w")
        tk.Label(brand, text="Milestones", bg=SIDE, fg=TEXT, font=(F + " Semibold", 17)).pack(anchor="w")
        tk.Label(brand, text=f"v{E.APP_VERSION} · for WoW: Forever", bg=SIDE, fg=DIM, font=FONT_S).pack(anchor="w")

        self.nav = {}
        for key, icon, text in NAV:
            row = tk.Frame(side, bg=SIDE, cursor="hand2")
            row.pack(fill="x")
            bar = tk.Frame(row, bg=SIDE, width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(row, text=icon, bg=SIDE, fg=MUTED, font=(F, 12), width=2)
            ic.pack(side="left", padx=(16, 6), pady=9)
            tx = tk.Label(row, text=text, bg=SIDE, fg=MUTED, font=FONT_B)
            tx.pack(side="left")
            badge = tk.Label(row, text="", bg=SIDE, fg=GOLD_INK, font=(F + " Semibold", 8))
            badge.pack(side="right", padx=14)
            parts = (row, ic, tx)
            for w in parts:
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
            self.nav[key] = {"row": row, "bar": bar, "icon": ic, "text": tx, "badge": badge}

        foot = tk.Frame(side, bg=SIDE)
        foot.pack(side="bottom", fill="x", padx=18, pady=18)
        self.status_dot = tk.Label(foot, text="●  Not running", bg=SIDE, fg=MUTED, font=FONT_S, anchor="w")
        self.status_dot.pack(fill="x", pady=(0, 8))
        self.go = Btn(foot, "Start watching", self.toggle, "primary", pady=10)
        self.go.pack(fill="x")
        self.upd = Btn(foot, "", self.do_update, "ghost")

        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self.pages = {}
        for key, _, text in NAV:
            page = ScrollPage(self.main)
            head = tk.Frame(page.body, bg=BG)
            head.pack(fill="x", padx=32, pady=(26, 14))
            tk.Label(head, text=text, bg=BG, fg=TEXT, font=FONT_H1).pack(anchor="w")
            body = tk.Frame(page.body, bg=BG)
            body.pack(fill="both", expand=True, padx=32, pady=(0, 28))
            getattr(self, f"page_{key}")(body)
            self.pages[key] = page

    def _nav_hover(self, key, on):
        if key == getattr(self, "current", None):
            return
        n = self.nav[key]
        for w in (n["row"], n["icon"], n["text"]):
            w.configure(bg=HOVER if on else SIDE)
        n["badge"].configure(bg=n["badge"]["bg"] if n["badge"]["text"] else (HOVER if on else SIDE))

    def show(self, key):
        self.current = key
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, n in self.nav.items():
            on = k == key
            for w in (n["row"], n["icon"], n["text"]):
                w.configure(bg=CARD if on else SIDE)
            n["bar"].configure(bg=GOLD if on else SIDE)
            n["icon"].configure(fg=GOLD if on else MUTED)
            n["text"].configure(fg=TEXT if on else MUTED)
            if not n["badge"]["text"]:
                n["badge"].configure(bg=CARD if on else SIDE)
        if key == "home":
            self.refresh_home()

    def badge(self, key, text):
        b = self.nav[key]["badge"]
        b.configure(text=text, bg=GOLD if text else SIDE, padx=6 if text else 0)

    # ------------------------------------------------------------ pages
    def page_home(self, p):
        hero = card(p, pad=20)
        hero.outer.pack(fill="x")
        top = tk.Frame(hero, bg=CARD)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        self.hero_title = tk.Label(left, text="", bg=CARD, fg=TEXT, font=FONT_BIG, anchor="w")
        self.hero_title.pack(anchor="w")
        self.hero_sub = label(left, "", muted=True, wrap=520)
        self.hero_sub.pack(anchor="w", pady=(4, 0))
        self.hero_btn = Btn(top, "Start watching", self.toggle, "primary", padx=22, pady=11, font=(F + " Semibold", 11))
        self.hero_btn.pack(side="right")

        tiles = tk.Frame(p, bg=BG)
        tiles.pack(fill="x", pady=14)
        self.tiles = {}
        for i, (key, name) in enumerate((("members", "Members tracked"), ("levels_week", "Levels gained this week"),
                                         ("milestones_week", "Milestones this week"), ("at_cap", "At the level cap"))):
            t = tk.Frame(tiles, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            tiles.columnconfigure(i, weight=1, uniform="t")
            v = tk.Label(t, text="–", bg=CARD, fg=TEXT, font=FONT_BIG)
            v.pack(anchor="w", padx=16, pady=(12, 0))
            tk.Label(t, text=name, bg=CARD, fg=MUTED, font=FONT_S).pack(anchor="w", padx=16, pady=(0, 12))
            self.tiles[key] = v

        steps = card(p, "Get set up", "Four steps. Each one turns green when it's done.")
        steps.outer.pack(fill="x")
        self.checks = {}
        for key, text, go in (("discord", "Connect Discord (paste a webhook and send a test)", "discord"),
                              ("folder", "Pick your WoW: Forever game folder", "game"),
                              ("addon", "Install the addon into the game", "game"),
                              ("file", "Log in once, then type /reload (so the app can read your guild)", "game")):
            row = tk.Frame(steps, bg=CARD)
            row.pack(fill="x", pady=(10, 0))
            mark = tk.Label(row, text="○", bg=CARD, fg=DIM, font=(F, 13), width=2)
            mark.pack(side="left")
            tk.Label(row, text=text, bg=CARD, fg=TEXT, font=FONT).pack(side="left", padx=(6, 0))
            Btn(row, "Open", lambda k=go: self.show(k), "ghost", padx=10, pady=3, font=FONT_S).pack(side="right")
            self.checks[key] = mark

        self.boards_line = label(p, "", muted=True)
        self.boards_line.pack(anchor="w", pady=(14, 0))

    def page_discord(self, p):
        how = card(p, "How Discord knows where to post",
                   "A webhook is a private posting link for ONE Discord channel. Whatever channel you made it in is where "
                   "the posts go. The app never needs a bot or a password, just these links.")
        how.outer.pack(fill="x")
        flow = tk.Frame(how, bg=CARD)
        flow.pack(fill="x", pady=(12, 2))
        for i, (title, sub) in enumerate((("In game", "The addon notes milestones."),
                                          ("Addon file", "Saved when you /reload or log out."),
                                          ("This app", "Reads it every 15 seconds."),
                                          ("Webhook", "Posts into your channel."))):
            flow.columnconfigure(i, weight=1, uniform="f")
            box = tk.Frame(flow, bg=CARD2, highlightthickness=1, highlightbackground=BORDER)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            tk.Label(box, text=f"{i + 1}  {title}", bg=CARD2, fg=GOLD if i == 3 else TEXT, font=FONT_B).pack(anchor="w", padx=12, pady=(8, 0))
            sl = tk.Label(box, text=sub, bg=CARD2, fg=MUTED, font=FONT_S, justify="left", anchor="w")
            sl.pack(fill="x", padx=12, pady=(0, 8))
            box.bind("<Configure>", lambda e, l=sl: l.configure(wraplength=max(80, e.width - 26)))

        setup = card(p, "Make the webhooks (2 minutes)")
        setup.outer.pack(fill="x", pady=(14, 0))
        for n, text in enumerate((
                "In Discord, make two text channels, for example  #guild-feed  and  #guild-boards.",
                "Right-click #guild-feed → Edit Channel → Integrations → Webhooks → New Webhook.",
                "Name it \"Guild Milestones\" (you can give it your guild's logo), then click Copy Webhook URL.",
                "Paste it below as the Feed channel. Do the same for #guild-boards.",
                "Tip: in #guild-boards, lock posting for members so the two boards stay at the top."), 1):
            row = tk.Frame(setup, bg=CARD)
            row.pack(fill="x", pady=(8, 0))
            tk.Label(row, text=str(n), bg=GOLD, fg=GOLD_INK, font=(F + " Semibold", 9), width=2).pack(side="left", anchor="n", pady=2)
            label(row, text, wrap=620).pack(side="left", padx=(10, 0))

        feed = card(p, "Feed channel  ·  live posts",
                    "Level milestones, welcomes, loot, boss kills, skill tiers. Small news arrives quietly (no phone buzz).")
        feed.outer.pack(fill="x", pady=(14, 0))
        self.webhook_row = entry(feed, self.s["webhook"], secret=True)
        self.webhook_row.pack(fill="x", pady=(10, 0))
        self.webhook_hint = label(feed, "", muted=True)
        self.webhook_hint.pack(anchor="w", pady=(6, 0))
        Btn(feed, "Send a test message", self.test, "ghost").pack(anchor="w", pady=(8, 0))

        boards = card(p, "Boards channel  ·  posts that update themselves (optional)",
                      "The weekly digest and the Race to 60 board. Leave empty to use the feed channel.")
        boards.outer.pack(fill="x", pady=(14, 0))
        entry(boards, self.s["digest_webhook"], secret=True).pack(fill="x", pady=(10, 0))
        self.boards_hint = label(boards, "", muted=True)
        self.boards_hint.pack(anchor="w", pady=(6, 0))

        ex = card(p, "See every post before your guild does",
                  "Sends one example of each kind of post, plus an example digest and race board, with made-up names. "
                  "Delete them in Discord afterwards (or use a private test channel).")
        ex.outer.pack(fill="x", pady=(14, 0))
        Btn(ex, "Send examples of every post", self.samples, "primary").pack(anchor="w", pady=(10, 0))
        for var in (self.s["webhook"], self.s["digest_webhook"]):
            var.trace_add("write", lambda *a: self.check_hooks())
        self.check_hooks()

    def page_announce(self, p):
        groups = (("Members", (("welcome_new", "Welcome new members", "A post when someone joins the guild."),
                               ("welcome_back", "Welcome back", "When someone returns after two weeks or more (quiet post)."))),
                  ("Levels", (("announce_levels", "Level milestones", "At the levels you choose below, and at the cap."),
                              ("announce_firsts", "“First in the guild” and “first of a class”", "Adds a medal line to the milestone post."))),
                  ("Professions", (("announce_tiers", "Skill tiers", "When someone reaches a tier below (quiet post)."),)),
                  ("Adventures", (("event_loot", "Loot", "Rare and better. Epic and legendary ones ping, the rest are quiet."),
                                  ("event_boss", "Boss kills", "One post per kill naming everyone there."),
                                  ("event_death", "Deaths", "Only from friends who turned deaths on in their addon."),
                                  ("event_quest", "Quest turn-ins", "Only from friends who turned quests on. Can be busy."))),
                  ("Guild chat link", (("skip_shouted", "Skip what the addon already said in guild chat",
                                        "Only turn this on if Blizzard's guild chat ↔ Discord link already shows those lines "
                                        "in your Discord. Otherwise you'd miss them."),)))
        cols = tk.Frame(p, bg=BG)
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=1, uniform="a")
        cols.columnconfigure(1, weight=1, uniform="a")
        for i, (title, rows) in enumerate(groups):
            c = card(cols, title)
            c.outer.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 7, 7 if i % 2 == 0 else 0), pady=(0, 14))
            for key, text, sub in rows:
                toggle_row(c, self.b[key], text, sub)

        n = card(p, "Milestones", "These also reach every member's addon through the Guild Info text, so nobody types anything.")
        n.outer.pack(fill="x")
        grid = tk.Frame(n, bg=CARD)
        grid.pack(fill="x", pady=(10, 0))
        for i, (lab, key) in enumerate((("Milestone levels", "milestones"), ("Level cap", "max_level"), ("Skill tiers", "tiers"))):
            tk.Label(grid, text=lab, bg=CARD, fg=MUTED, font=FONT_S).grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 12, 0))
            entry(grid, self.s[key]).grid(row=1, column=i, sticky="ew", padx=(0 if i == 0 else 12, 0), pady=(4, 0))
            grid.columnconfigure(i, weight=3 if i != 1 else 1)
        Btn(n, "Copy the Guild Info line", self.copy_line, "ghost", font=FONT_S).pack(anchor="w", pady=(12, 0))

        m = card(p, "Wording", "{name}, {level} and {cls} get filled in.")
        m.outer.pack(fill="x", pady=(14, 0))
        for lab, key in (("Level milestone", "level_msg"), ("Welcome", "welcome_msg")):
            tk.Label(m, text=lab, bg=CARD, fg=MUTED, font=FONT_S).pack(anchor="w", pady=(10, 0))
            entry(m, self.s[key]).pack(fill="x", pady=(4, 0))

        t = card(p, "Newcomer tips", "One per line, like  10=Pick a profession!  It's added to that level's milestone post.")
        t.outer.pack(fill="x", pady=(14, 0))
        self.tips = tk.Text(t, height=4, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT, wrap="word",
                            padx=8, pady=6, highlightthickness=1, highlightbackground=BORDER, highlightcolor=GOLD)
        self.tips.pack(fill="x", pady=(10, 0))

    def page_boards(self, p):
        for key, title, sub, btn, cmd in (
                ("digest_enabled", "Weekly digest",
                 "One message that edits itself all week: newcomers, top level-ups, milestones, this week's awards "
                 "(Loot Goblin, Boss Hunter, Quest Machine, Darwin Award), skill tiers and who crafts what. "
                 "A fresh one starts each week.", "Post / refresh the digest now", self.digest_now),
                ("ladder_enabled", "Race to 60",
                 "A second message that edits itself: everyone's level, who got each milestone first, and a progress bar "
                 "for the whole guild. It never resets.", "Post / refresh the race board now", self.digest_now)):
            c = card(p)
            c.outer.pack(fill="x", pady=(0, 14))
            toggle_row(c, self.b[key], title, sub, title_font=FONT_H2, pady=(0, 0))
            if key == "digest_enabled":
                wk = tk.Frame(c, bg=CARD)
                wk.pack(anchor="w", pady=(12, 0))
                tk.Label(wk, text="Week starts on", bg=CARD, fg=MUTED, font=FONT_S).pack(side="left")
                opt = tk.OptionMenu(wk, self.week, *E.WEEKDAYS)
                opt.configure(bg=CARD2, fg=TEXT, activebackground=HOVER, activeforeground=TEXT, relief="flat",
                              highlightthickness=0, font=FONT_S, bd=0)
                opt["menu"].configure(bg=CARD2, fg=TEXT, activebackground=GOLD, activeforeground=GOLD_INK)
                opt.pack(side="left", padx=10)
            Btn(c, btn, cmd, "ghost").pack(anchor="w", pady=(12, 0))
        label(p, "Both boards go to the Boards channel from the Discord page (or the Feed channel if that's empty). "
                 "Need the addon file first: see Game & addon.", muted=True).pack(anchor="w")

    def page_game(self, p):
        c = card(p, "Game folder", "The WoW: Forever folder inside World of Warcraft. It has Interface and WTF inside.")
        c.outer.pack(fill="x")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        entry(row, self.s["game_folder"]).pack(side="left", fill="x", expand=True)
        Btn(row, "Find it for me", self.find, "primary").pack(side="left", padx=(8, 0))
        Btn(row, "Browse…", self.browse, "ghost").pack(side="left", padx=(8, 0))
        self.s["game_folder"].trace_add("write", lambda *a: self.refresh_addon())

        a = card(p, "The addon")
        a.outer.pack(fill="x", pady=(14, 0))
        row = tk.Frame(a, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        self.addon_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=FONT, anchor="w")
        self.addon_lbl.pack(side="left")
        self.addon_btn = Btn(row, "Install / update addon", self.install_addon, "ghost")
        self.addon_btn.pack(side="right")
        r2 = tk.Frame(a, bg=CARD)
        r2.pack(fill="x", pady=(12, 0))
        Toggle(r2, self.b["auto_update_addon"]).pack(side="right")
        tk.Label(r2, text="Keep the addon up to date when this app updates", bg=CARD, fg=TEXT, font=FONT).pack(anchor="w")
        self.file_lbl = label(a, "", muted=True)
        self.file_lbl.pack(anchor="w", pady=(10, 0))
        label(a, "In game: /gms opens the Guild Milestones window. After the app changes settings, type /reload.",
              muted=True).pack(anchor="w", pady=(4, 0))

        s = card(p, "This app")
        s.outer.pack(fill="x", pady=(14, 0))
        r3 = tk.Frame(s, bg=CARD)
        r3.pack(fill="x", pady=(8, 0))
        Toggle(r3, self.b["auto_start"]).pack(side="right")
        tk.Label(r3, text="Start watching automatically when I open the app", bg=CARD, fg=TEXT, font=FONT).pack(anchor="w")
        r4 = tk.Frame(s, bg=CARD)
        r4.pack(fill="x", pady=(14, 0))
        tk.Label(r4, text=f"Version {E.APP_VERSION}", bg=CARD, fg=TEXT, font=FONT_B).pack(side="left")
        Btn(r4, "Check for updates", lambda: self.check_update(True), "ghost", font=FONT_S).pack(side="right")
        self.upd_lbl = label(s, "Not checked yet.", muted=True)
        self.upd_lbl.pack(anchor="w", pady=(8, 0))
        label(s, f"Runs from: {E.APP_DIR}", muted=True).pack(anchor="w", pady=(4, 0))
        label(s, f"Settings and memory: {E.DATA_DIR}", muted=True).pack(anchor="w")

    def page_shared(self, p):
        c = card(p)
        c.outer.pack(fill="x")
        toggle_row(c, self.b["shared_on"], "Shared mode",
                   "Only for when more than one officer runs this app. Everyone checks in with one shared online notebook; "
                   "one app posts (the Announcer) and the others stand by. If the Announcer goes quiet, another takes over. "
                   "Leave it off if you're the only one.", title_font=FONT_H2, pady=(0, 0))
        f = card(p, "Connection", "The guild leader sets this up once (see shared/SETUP.md) and gives officers the two values.")
        f.outer.pack(fill="x", pady=(14, 0))
        for lab, key, secret in (("Web address of the shared service", "shared_url", False), ("Password", "shared_token", True),
                                 ("Your name (shown to other officers)", "my_name", False)):
            tk.Label(f, text=lab, bg=CARD, fg=MUTED, font=FONT_S).pack(anchor="w", pady=(10, 0))
            entry(f, self.s[key], secret=secret).pack(fill="x", pady=(4, 0))
        Btn(f, "Test connection", self.test_shared, "ghost").pack(anchor="w", pady=(12, 0))

    def page_log(self, p):
        c = card(p, "What the app has been doing")
        c.outer.pack(fill="both", expand=True)
        self.box = tk.Text(c, height=26, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Consolas", 9),
                           wrap="word", padx=10, pady=8, highlightthickness=0)
        self.box.pack(fill="both", expand=True, pady=(10, 0))
        self.box.tag_configure("time", foreground=DIM)
        self.box.tag_configure("bad", foreground=BAD)
        self.box.tag_configure("good", foreground=GOOD)
        self.box.configure(state="disabled")

    # ------------------------------------------------------------ live bits
    def check_hooks(self):
        for var, hint, required in ((self.s["webhook"], self.webhook_hint, True), (self.s["digest_webhook"], self.boards_hint, False)):
            prob = E.webhook_problem(var.get(), required)
            if prob:
                hint.configure(text=prob, fg=BAD if var.get().strip() else MUTED)
            else:
                hint.configure(text="✓ Looks like a webhook." if var.get().strip() else "Empty: boards go to the feed channel.",
                               fg=GOOD if var.get().strip() else MUTED)

    def tick(self):
        """Refresh the Home page and badges every few seconds."""
        try:
            if getattr(self, "current", "") == "home":
                self.refresh_home()
        except Exception as e:
            E.log_error(f"home refresh failed: {e!r}")
        self.root.after(4000, self.tick)

    def refresh_home(self):
        c = self.collect()
        d = E.dashboard(c)
        for k, v in self.tiles.items():
            v.configure(text=str(d.get(k, "–")) if d["members"] else "–")
        folder_ok = os.path.isdir(c["game_folder"])
        have, new = E.addon_status(c["game_folder"]) if folder_ok else (None, None)
        done = {"discord": not E.webhook_problem(c["webhook"]) and (self.tested or d["members"] > 0),
                "folder": folder_ok, "addon": bool(have), "file": bool(folder_ok and E.resolve_savedvars(c))}
        for k, mark in self.checks.items():
            mark.configure(text="✓" if done[k] else "○", fg=GOOD if done[k] else DIM)
        todo = sum(1 for v in done.values() if not v)
        self.badge("home", str(todo) if todo else "")
        if self.running:
            self.hero_title.configure(text="Watching your guild")
            when = time.strftime("%H:%M", time.localtime(d["last_check"])) if d["last_check"] else "not yet"
            extra = f" · {d['waiting']} post(s) waiting to retry" if d["waiting"] else ""
            self.hero_sub.configure(text=f"{d['guild'] or 'Your guild'} · last check {when}{extra}. "
                                          "New data arrives when someone with the addon logs out or types /reload.")
            self.hero_btn.set_kind("danger", "Stop")
        else:
            self.hero_title.configure(text="Ready when you are" if not todo else "Almost there")
            self.hero_sub.configure(text="Start watching and the app posts to Discord as your guild plays." if not todo
                                    else f"{todo} setup step(s) left. They're listed below.")
            self.hero_btn.set_kind("primary", "Start watching")
        parts = []
        if c["digest_enabled"]:
            parts.append("weekly digest " + ("is live" if d["digest"] else "posts on the first check"))
        if c["ladder_enabled"]:
            parts.append("race board " + ("is live" if d["ladder"] else "posts on the first check"))
        self.boards_line.configure(text=("Boards: " + ", ".join(parts) + ".") if parts else "Boards are off.")

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
                stamp, _, msg = line.partition("   ")
                low = msg.lower()
                tag = "bad" if any(w in low for w in ("couldn't", "failed", "problem", "wrong", "error")) else \
                      "good" if any(w in low for w in ("posted", "sent", "updated", "installed")) else None
                self.box.configure(state="normal")
                self.box.insert("end", stamp + "   ", "time")
                self.box.insert("end", msg, tag)
                self.box.see("end")
                self.box.configure(state="disabled")
                if tag == "bad" and getattr(self, "current", "") != "log":
                    self.badge("log", "!")
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def set_running(self, on):
        self.running = on
        self.go.set_kind("danger" if on else "primary", "Stop" if on else "Start watching")
        if on and self.b["shared_on"].get():
            self.status_dot.configure(text="●  Connecting to the shared service...", fg=MUTED)
        else:
            self.status_dot.configure(text="●  Watching your guild" if on else "●  Not running", fg=GOOD if on else MUTED)
        if hasattr(self, "hero_btn"):
            self.refresh_home()

    def set_status(self, kind, text):
        if not self.running:
            return
        lab = {"announcer": "●  Announcer: you're posting", "standby": "●  " + text.rstrip("."),
               "offline": "●  Can't reach the shared service"}.get(kind, "●  " + text)
        self.status_dot.configure(text=lab, fg={"announcer": GOOD, "standby": GOLD, "offline": BAD}.get(kind, MUTED))

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
        prob = E.webhook_problem(c["webhook"])
        if prob:
            return ("discord", "Discord page: " + prob)
        prob = E.webhook_problem(c["digest_webhook"], required=False)
        if prob:
            return ("discord", "Boards channel: " + prob)
        if c["shared_on"]:
            if not c["shared_url"].startswith("https://") or not c["shared_token"]:
                return ("shared", "Shared mode is on, so fill in the web address and password (or turn it off).")
        else:
            if not os.path.isdir(c["game_folder"]):
                return ("game", "Pick your game folder on the Game & addon page.")
            if need_file and not E.resolve_savedvars(c):
                return ("game", "I can't see the addon's file yet.\n\nInstall the addon (Game & addon page), log in to the game, "
                                "then type /reload.")
        if not c["max_level"].isdigit():
            return ("announce", "Level cap should be a number.")
        if not E.nums(c["milestones"]):
            return ("announce", "Add at least one milestone level, like 10, 20, 30.")
        for key in ("level_msg", "welcome_msg"):
            try:
                c[key].format(name="X", level=1, cls="Y")
            except Exception:
                return ("announce", "In the wording, only {name}, {level} and {cls} can go inside curly brackets.")
        return None

    def warn(self, prob):
        page, msg = prob
        self.show(page)
        messagebox.showwarning("One thing first", msg)

    # ------------------------------------------------------------ actions
    def browse(self):
        p = filedialog.askdirectory(title="Pick the WoW: Forever folder (the one with Interface and WTF inside)")
        if p:
            self.use_folder(os.path.normpath(p))

    def find(self):
        hits = E.find_game_folders()
        if not hits:
            return messagebox.showinfo("Couldn't find it", "No luck finding it automatically.\n\nClick Browse and pick "
                                       "the WoW: Forever folder inside World of Warcraft (the one with Interface and WTF).")
        if len(hits) == 1:
            return self.use_folder(hits[0])
        win = tk.Toplevel(self.root)                 # several game versions installed: let the officer choose
        win.title("Which game folder?")
        win.transient(self.root)
        win.configure(bg=CARD)
        tk.Label(win, text="I found these. Pick the one for WoW: Forever:", bg=CARD, fg=TEXT, font=FONT_B).pack(
            anchor="w", padx=18, pady=(16, 8))
        for h in hits:
            name = os.path.basename(h)
            row = tk.Frame(win, bg=CARD2, highlightthickness=1, highlightbackground=BORDER, cursor="hand2")
            row.pack(fill="x", padx=18, pady=3)
            t1 = tk.Label(row, text=name, bg=CARD2, fg=GOLD, font=FONT_B, anchor="w")
            t1.pack(anchor="w", padx=12, pady=(6, 0))
            t2 = tk.Label(row, text=h, bg=CARD2, fg=MUTED, font=FONT_S, anchor="w")
            t2.pack(anchor="w", padx=12, pady=(0, 6))
            for w in (row, t1, t2):
                w.bind("<Button-1>", lambda e, path=h: (self.use_folder(path), win.destroy()))
                w.bind("<Enter>", lambda e, r=row: r.configure(highlightbackground=GOLD))
                w.bind("<Leave>", lambda e, r=row: r.configure(highlightbackground=BORDER))
        tk.Label(win, text="", bg=CARD).pack(pady=4)

    def use_folder(self, path):
        self.s["game_folder"].set(path)
        self.log(f"Game folder set: {path}")
        self.refresh_addon()

    def refresh_addon(self):
        if not hasattr(self, "addon_lbl"):
            return
        c = self.collect()
        g = c["game_folder"]
        if not os.path.isdir(g):
            self.addon_lbl.configure(text="Pick your game folder first.", fg=MUTED)
            self.addon_btn.set_enabled(False)
            self.file_lbl.configure(text="")
            return
        self.addon_btn.set_enabled(True)
        have, new = E.addon_status(g)
        new = new or "?"
        if have is None:
            self.addon_lbl.configure(text=f"Not installed yet (this app has v{new}).", fg=GOLD)
            self.addon_btn.set_kind("primary")
        elif have.endswith("*"):
            self.addon_lbl.configure(text=f"An older build of v{new} is installed. Update it.", fg=GOLD)
            self.addon_btn.set_kind("primary")
        elif have != new:
            self.addon_lbl.configure(text=f"v{have} is installed. v{new} is available.", fg=GOLD)
            self.addon_btn.set_kind("primary")
        else:
            self.addon_lbl.configure(text=f"v{have} is installed and up to date ✓", fg=GOOD)
            self.addon_btn.set_kind("ghost")
        f = E.resolve_savedvars(c)
        if f:
            when = time.strftime("%b %d, %H:%M", time.localtime(os.path.getmtime(f)))
            self.file_lbl.configure(text=f"Addon file found (last saved {when}).", fg=GOOD)
        else:
            self.file_lbl.configure(text="No addon file yet: log in with the addon on, then type /reload.", fg=MUTED)

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

    def copy_line(self):
        line = E.addon_line(self.collect())
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(line)
            self.root.update()
            note = "Copied to your clipboard:"
        except Exception as e:
            E.log_error(f"copy failed: {e!r}")
            note = "Couldn't reach the clipboard. Select and copy this yourself:"
        win = tk.Toplevel(self.root)
        win.title("Guild Info line")
        win.transient(self.root)
        win.configure(bg=CARD)
        tk.Label(win, text=note, bg=CARD, fg=TEXT, font=FONT).pack(anchor="w", padx=16, pady=(14, 6))
        e = tk.Entry(win, width=52, bg=FIELD, fg=TEXT, relief="flat", font=FONT, insertbackground=TEXT)
        e.insert(0, line)
        e.pack(padx=16, ipady=5)
        e.focus_set()
        e.selection_range(0, "end")
        label(win, "Only needed if the automatic publish doesn't work. Paste it anywhere in the Guild Info box "
                   "(Guild window > Info).", muted=True, wrap=380).pack(anchor="w", padx=16, pady=8)
        Btn(win, "Close", win.destroy, "ghost").pack(pady=(0, 14))

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
        prob = E.webhook_problem(c["webhook"])
        if prob:
            return messagebox.showwarning("Webhook needed", prob)

        def run():
            ok, _, err = E.post(c["webhook"], content="✅ **Guild Milestones is connected!** Posts will appear in this channel.")
            self.log("Test message sent. Look in Discord." if ok else f"Test failed: {err}")
            if ok:
                self.tested = True
            self.q.put(lambda: (messagebox.showinfo("Test sent", "Sent! Check the channel in Discord.") if ok
                                else messagebox.showwarning("Test failed", f"Discord didn't take it:\n\n{err}")))
        threading.Thread(target=run, daemon=True).start()

    def samples(self):
        c = self.collect()
        E.save_config(c)
        prob = E.webhook_problem(c["webhook"]) or E.webhook_problem(c["digest_webhook"], required=False)
        if prob:
            return messagebox.showwarning("Webhook needed", prob)
        if not messagebox.askyesno("Send examples?", "This posts about 10 example messages with made-up names to your "
                                   "Discord channel(s). Go ahead?"):
            return

        def run():
            ok = E.send_samples(c, self.log)
            if ok:
                self.tested = True
            self.q.put(lambda: (messagebox.showinfo("Examples sent", "Done! Have a look in Discord.") if ok else
                                messagebox.showwarning("Not everything went through", "Some examples failed. The Activity "
                                                       "page shows Discord's answer.")))
        threading.Thread(target=run, daemon=True).start()

    def digest_now(self):
        c = self.collect()
        c["digest_enabled"] = True
        E.save_config(self.collect())
        prob = self.problem(c)
        if prob:
            return self.warn(prob)

        def run():
            lines = []

            def lg(t):
                lines.append(t)
                self.log(t)
            self.log("Posting the boards...")
            eng = E.Engine(c, lg)
            try:
                eng.check(force_digest=True)
                if eng.shared and eng.role == "standby":
                    lg("Only the Announcer can post the digest. Ask them, or wait for the role to move.")
            except Exception as e:
                lg(f"Digest problem: {e}")
                E.log_error(f"digest button failed: {e!r}")
            if eng.shared and not self.running:
                eng.release()
            shown = "\n".join(lines[-6:]) or "Nothing happened. Check the Game & addon page."
            ok = any(w in t.lower() for t in lines for w in ("digest posted", "digest updated"))
            show = messagebox.showinfo if ok else messagebox.showwarning
            self.q.put(lambda: show("Boards", shown))
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
        self.upd.set_kind("ghost", f"⬆  Update to v{latest}")
        self.upd.pack(fill="x", pady=(8, 0))
        self.log(f"A new version is available: v{latest}. Click the Update button on the left.")

    def do_update(self):
        if getattr(sys, "frozen", False):
            return messagebox.showinfo("Use the .pyw version", "The .exe can't update itself.\nOpen GuildMilestones.pyw instead, "
                                       "and updating becomes one click.")
        notes = E.latest_notes(self.latest)
        extra = f"\n\nWhat's new: {notes[:160]}" if notes else ""
        if not messagebox.askyesno("Update", f"Update to v{self.latest}?\n\nThe app will restart. Your settings are kept.{extra}"):
            return
        self.upd.set_enabled(False)
        self.log("Downloading the update...")

        def work():
            ok, msg = E.apply_update()
            self.q.put(lambda: self.update_done(ok, msg))
        threading.Thread(target=work, daemon=True).start()

    def update_done(self, ok, msg):
        if not ok:
            self.upd.set_enabled(True)
            self.log(msg)
            return messagebox.showwarning("Update failed", msg)
        self.log("Updated! Restarting...")
        self.root.withdraw()                                     # the old window disappears at once
        self.close(exit_now=False)                               # saves settings, hands over the announcer role
        subprocess.Popen([sys.executable, str(E.APP_DIR / "GuildMilestones.pyw")], cwd=str(E.APP_DIR))
        os._exit(0)                                              # hard stop, so no second window ever lingers

    def toggle(self):
        self.halt() if self.running else self.start()

    def start(self, quiet=False):
        c = self.collect()
        E.save_config(c)
        prob = self.problem(c)
        if prob:
            if not quiet:
                self.warn(prob)
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

    def close(self, exit_now=True):
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
        if exit_now:
            self.root.destroy()


def main():
    threading.excepthook = lambda a: E.log_error(f"thread {a.thread.name if a.thread else '?'} crashed: {a.exc_value!r}")
    try:
        from ctypes import windll                                # crisp text on high-DPI screens
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
