"""Guild Milestones engine: reads the addon's file, decides what to announce, talks to Discord.
No window code in here, so it can be tested on its own."""
import copy, glob, hashlib, io, uuid, json, os, re, shutil, sys, tempfile, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_VERSION = "0.5.1"
REPO, BRANCH = "MihailoJovic/Guild-Milestones", "main"

# Settings and memory live in your user profile, so replacing or deleting the app never wipes them.
DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / "GuildMilestones"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    DATA_DIR = APP_DIR
CONFIG_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "milestone_state.json"


def _migrate_old_files():
    """Older versions kept these files next to the app. Copy them over once."""
    for name in ("settings.json", "milestone_state.json"):
        old, new = APP_DIR / name, DATA_DIR / name
        try:
            if old != new and old.exists() and not new.exists():
                shutil.copy2(old, new)
        except Exception:
            pass


_migrate_old_files()
POLL_SECONDS = 15
MAX_WELCOMES = 5          # more brand-new names than this at once = probably a roster hiccup, so stay quiet
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIER_NAMES = {75: "Journeyman", 150: "Expert", 225: "Artisan", 300: "Master"}
CLASS_NAMES = {"DEATHKNIGHT": "Death Knight", "DEMONHUNTER": "Demon Hunter"}

DEFAULTS = {
    "webhook": "", "digest_webhook": "", "game_folder": "", "savedvars": "",
    "auto_start": False, "auto_update_addon": True,
    "shared_on": False, "shared_url": "", "shared_token": "", "my_name": "", "device_id": "",
    "announce_levels": True, "announce_firsts": True, "announce_tiers": True,
    "welcome_new": True, "digest_enabled": True,
    "milestones": "10, 20, 30, 40, 50, 60", "max_level": 60, "tiers": "75, 150, 225, 300",
    "week_start": 0,
    "level_msg": "🎉 Congrats **{name}** on hitting Level {level}!",
    "welcome_msg": "👋 Welcome to the guild, **{name}**! ({cls}, level {level})",
    "tips": "10=Tip: ask who in the guild crafts. Free help is the best help!\n"
            "20=Tip: shout in guild chat for a dungeon group. Someone's usually keen.",
}
_LOCK = threading.Lock()


# ----------------------------- small helpers -----------------------------
def load_config():
    try:
        cfg = {**DEFAULTS, **json.loads(CONFIG_FILE.read_text(encoding="utf-8"))}
    except Exception:
        cfg = dict(DEFAULTS)
    if not cfg["game_folder"] and cfg["savedvars"]:
        cfg["game_folder"] = game_folder_from(cfg["savedvars"])
    if not cfg["my_name"]:
        cfg["my_name"] = os.environ.get("COMPUTERNAME") or "Officer"
    if not cfg["device_id"]:                       # identifies this PC to the shared service
        cfg["device_id"] = uuid.uuid4().hex[:12]
        try:
            save_config(cfg)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")


def nums(text):
    return {int(x) for x in re.findall(r"\d+", str(text))}


def parse_tips(text):
    tips = {}
    for line in str(text).splitlines():
        m = re.match(r"\s*(\d+)\s*=\s*(.+?)\s*$", line)
        if m:
            tips[int(m.group(1))] = m.group(2)
    return tips


def short(name):
    return name.split("-")[0]


def class_name(c):
    return CLASS_NAMES.get(c, c.title()) if c else "Adventurer"


def fmt(template, **kw):
    try:
        return template.format(**kw)
    except Exception:
        return template


# ------------------------------ reading the file ------------------------------
def _block(text, key):
    m = re.search(r'\["%s"\]\s*=\s*\{(.*?)\}' % key, text, re.S)
    return re.findall(r'"([^"\n]*)"', m.group(1)) if m else []


def parse_file(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    members, profs = [], []
    for row in _block(text, "members"):
        p = row.split("|")
        try:
            members.append({"name": p[0], "level": int(p[1]), "cls": p[2], "rank": int(p[3]), "off": int(p[4])})
        except (IndexError, ValueError):
            pass
    for row in _block(text, "profs"):
        p = row.split("|")
        try:
            profs.append({"prof": p[0], "name": p[1], "skill": int(p[2])})
        except (IndexError, ValueError):
            pass
    m = re.search(r'\["updated"\]\s*=\s*(\d+)', text)
    updated = int(m.group(1)) if m else int(Path(path).stat().st_mtime)
    return {"members": members, "profs": profs, "updated": updated,
            "legacy": '["entries"]' in text and not members}


# ---------------------------------- state ----------------------------------
def week_id(now, start):
    return (now.date() - timedelta(days=(now.weekday() - int(start)) % 7)).isoformat()


def new_week(wid):
    return {"id": wid, "new": [], "gains": {}, "milestones": [], "tiers": []}


def load_state():
    st = {"initialized": False, "members": {}, "firsts": {}, "profs": {}, "crafters": {},
          "week": new_week(""), "digest": {}}
    try:
        st.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return st


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")


def _seed_firsts(st, cls, level, levels):
    for m in levels:
        if m <= level:
            st["firsts"].setdefault(f"level:{m}", "")
            st["firsts"].setdefault(f"class:{cls}:{m}", "")


# ------------------------------ the brain ------------------------------
def process(snap, state, cfg, now):
    """Compare the newest snapshot with what we remember. Returns (new_state, messages, notes)."""
    st, msgs, notes = copy.deepcopy(state), [], []
    cap = int(cfg["max_level"])
    levels = nums(cfg["milestones"]) | {cap}
    tiers, tips = nums(cfg["tiers"]), parse_tips(cfg["tips"])
    today = now.date().isoformat()

    wid = week_id(now, cfg["week_start"])
    if st["week"].get("id") != wid:
        st["week"], st["digest"] = new_week(wid), {}
        notes.append("A new week has started.")
    week = st["week"]

    members = snap["members"]
    fresh = [m["name"] for m in members if m["name"] not in st["members"]]
    quiet = set()
    if not st["initialized"]:
        quiet = set(fresh)
        notes.append(f"First run: saved a starting point for {len(fresh)} members. No announcements this time.")
    elif len(fresh) > MAX_WELCOMES:
        quiet = set(fresh)
        notes.append(f"{len(fresh)} new names at once. That looks like a roster hiccup, so I saved them quietly.")

    for m in members:
        name, level, cls = m["name"], m["level"], m["cls"]
        who, cname = short(name), class_name(cls)
        rec = st["members"].get(name)

        if rec is None:                                         # someone new
            st["members"][name] = {"level": level, "class": cls, "first_seen": today}
            _seed_firsts(st, cls, level, levels)
            if name not in quiet:
                week["new"].append({"name": who, "cls": cname, "level": level})
                if cfg["welcome_new"]:
                    msgs.append(fmt(cfg["welcome_msg"], name=who, level=level, cls=cname))
            continue

        old = rec["level"]
        rec["class"] = cls or rec.get("class", "")
        if level > old:
            g = week["gains"].setdefault(who, [0, level])
            g[0] += level - old
            g[1] = level
            crossed = sorted(x for x in levels if old < x <= level)
            if crossed:
                top = crossed[-1]
                guild_first = class_first = False
                for x in crossed:
                    if f"level:{x}" not in st["firsts"]:
                        st["firsts"][f"level:{x}"] = who
                        if x == top:
                            guild_first = True
                    if f"class:{cls}:{x}" not in st["firsts"]:
                        st["firsts"][f"class:{cls}:{x}"] = who
                        if x == top:
                            class_first = True
                week["milestones"].append({"name": who, "level": top})
                if cfg["announce_levels"]:
                    if top == cap:
                        text = f"🏆 **{who}** hit the level cap: **Level {top}**! Absolute legend."
                    else:
                        text = fmt(cfg["level_msg"], name=who, level=top, cls=cname)
                    if cfg["announce_firsts"]:
                        if guild_first:
                            text += f"\n🥇 First in the guild to hit {top}!"
                        elif class_first:
                            text += f"\n🥈 First {cname} in the guild to hit {top}!"
                    if top in tips and top != cap:
                        text += f"\n💡 {tips[top]}"
                    msgs.append(text)
        rec["level"] = level

    # professions: only announce for (member, profession) pairs we've already seen
    for p in snap["profs"]:
        mine = st["profs"].setdefault(p["name"], {})
        old = mine.get(p["prof"])
        if old is not None and p["skill"] > old:
            hits = [t for t in tiers if old < t <= p["skill"]]
            if hits:
                t = max(hits)
                label = f"{TIER_NAMES[t]} ({t})" if t in TIER_NAMES else str(t)
                week["tiers"].append({"name": short(p["name"]), "prof": p["prof"], "tier": label})
                if cfg["announce_tiers"]:
                    msgs.append(f"🔨 **{short(p['name'])}** reached **{label}** in {p['prof']}!")
        mine[p["prof"]] = p["skill"]

    if snap["profs"]:
        crafters = {}
        for p in snap["profs"]:
            crafters.setdefault(p["prof"], []).append([short(p["name"]), p["skill"]])
        st["crafters"] = {k: sorted(v, key=lambda r: -r[1]) for k, v in crafters.items()}

    st["initialized"] = True
    return st, msgs, notes


# ------------------------------- the digest -------------------------------
def _clip(lines, limit):
    out, used = [], 0
    for i, ln in enumerate(lines):
        if used + len(ln) + 1 > limit - 30:
            out.append(f"…and {len(lines) - i} more")
            break
        out.append(ln)
        used += len(ln) + 1
    return "\n".join(out)


def build_digest(st, cfg):
    w = st["week"]
    start = datetime.strptime(w["id"], "%Y-%m-%d")
    fields = []

    new = [f"• **{n['name']}** · {n['cls']}, level {n['level']}" for n in w["new"]]
    fields.append({"name": "🆕 New this week", "value": _clip(new, 600) or "*No newcomers yet. The door's open!*"})

    gains = sorted(w["gains"].items(), key=lambda kv: -kv[1][0])[:5]
    lv = [f"• **{n}** +{g} (now level {l})" for n, (g, l) in gains]
    fields.append({"name": "📈 Top level-ups", "value": _clip(lv, 600) or "*Quiet so far. Go level something!*"})

    ms = [f"• **{m['name']}** → Level {m['level']}" for m in w["milestones"][-10:]]
    fields.append({"name": "🎯 Milestones hit", "value": _clip(ms, 600) or "*None yet this week.*"})

    if w["tiers"] or st["crafters"]:
        tr = [f"• **{t['name']}** · {t['tier']} {t['prof']}" for t in w["tiers"][-8:]]
        fields.append({"name": "🔨 Skill tiers", "value": _clip(tr, 600) or "*None yet this week.*"})

    for prof, rows in sorted(st["crafters"].items(), key=lambda kv: -len(kv[1]))[:9]:
        line = " · ".join(f"{n} {s}" for n, s in rows[:8])
        if len(rows) > 8:
            line += f" · +{len(rows) - 8} more"
        fields.append({"name": f"🧰 {prof} ({len(rows)})", "value": line[:300], "inline": True})

    return {
        "title": f"📅 Guild Weekly · week of {start.strftime('%b')} {start.day}",
        "description": "This post updates itself as the week goes on.",
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": f"Resets every {WEEKDAYS[int(cfg['week_start'])]}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------- Discord ---------------------------------
def _request(method, url, payload=None, timeout=15):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "GuildMilestones/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return r.status, (json.loads(body) if body else None), ""
    except urllib.error.HTTPError as e:
        return e.code, None, f"Discord said HTTP {e.code}"
    except Exception as e:
        return 0, None, str(e)


def post(url, content=None, embed=None, wait=False):
    """Returns (ok, message_id, error)."""
    payload = {"content": content} if content else {"embeds": [embed]}
    if wait:
        url += ("&" if "?" in url else "?") + "wait=true"
    status, body, err = _request("POST", url, payload)
    return status in (200, 204), (body or {}).get("id"), err


def edit(url, message_id, embed):
    return _request("PATCH", f"{url.split('?')[0]}/messages/{message_id}", {"embeds": [embed]})[0]


def push_digest(st, cfg, force=False):
    url = (cfg["digest_webhook"].strip() or cfg["webhook"].strip())
    embed = build_digest(st, cfg)
    stable = {k: v for k, v in embed.items() if k != "timestamp"}
    h = hashlib.md5(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    d = st["digest"]
    same_target = d.get("id") and d.get("url") == url
    if same_target and d.get("hash") == h and not force:
        return True, "unchanged"
    if same_target:
        status = edit(url, d["id"], embed)
        if status in (200, 204):
            d["hash"] = h
            return True, "updated"
        if status != 404:                      # 404 = message was deleted, so post a fresh one
            return False, f"edit failed (HTTP {status})"
    ok, mid, err = post(url, embed=embed, wait=True)
    if ok and mid:
        st["digest"] = {"id": mid, "url": url, "hash": h}
        return True, "posted"
    return False, err or "no message id came back"


def chunk(msgs, limit=1900):
    out, cur = [], ""
    for m in msgs:
        if cur and len(cur) + len(m) + 2 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{m}" if cur else m
    if cur:
        out.append(cur)
    return out


# ------------------------------- shared service -------------------------------
HEARTBEAT = 60          # seconds between check-ins; the service gives the announcer role a 3 minute lease


class SharedStore:
    """Talks to the Google Apps Script 'notebook' that all officers share."""
    def __init__(self, url, token, holder, name):
        self.url, self.token, self.holder, self.name = url, token, holder, name

    def _call(self, **payload):
        payload.update(token=self.token, holder=self.holder, name=self.name)
        status, body, err = _request("POST", self.url, payload, timeout=30)
        if body is None:
            if "Expecting value" in err or "JSON" in err:
                err = "that address didn't answer like the shared service (check it is the Web app URL and access is set to Anyone)"
            return False, None, err or f"HTTP {status}"
        if not body.get("ok"):
            return False, body, body.get("error", "unknown error")
        return True, body, ""

    def sync(self, snapshot=None, want_all=False):
        return self._call(action="sync", snapshot=snapshot, wantAll=want_all)

    def commit(self, state, expected_version):
        return self._call(action="commit", state=state, expectedVersion=expected_version)

    def release(self, cooldown=0):
        return self._call(action="release", cooldownSeconds=cooldown)

    def status(self):
        return self._call(action="status")


# --------------------------------- engine ---------------------------------
class Engine:
    def __init__(self, cfg, log, status=None):
        self.cfg, self.log, self.status_cb = cfg, log, status
        self.shared = bool(cfg.get("shared_on") and cfg.get("shared_url") and cfg.get("shared_token"))
        self.store = (SharedStore(cfg["shared_url"].strip(), cfg["shared_token"].strip(),
                                  cfg.get("device_id") or "pc", cfg.get("my_name") or "Officer") if self.shared else None)
        self.role, self.role_text, self.last_sync, self.uploaded_ts = "", "", 0.0, 0
        self.cache, self.outbox, self.fail_streak, self.pending_digest, self.warned = (0, None), [], 0, None, set()

    def check(self, force_digest=False):
        """One pass: read file, announce, update digest, save. Returns False if it should retry."""
        if self.shared:
            return self.shared_step(force=True, force_digest=force_digest)
        with _LOCK:
            path = resolve_savedvars(self.cfg)
            if not path:
                self.log("Can't find the addon file yet. Log in with the addon on, then type /gms save in the game.")
                return True
            snap = parse_file(path)
            if not snap["members"]:
                if snap.get("legacy"):
                    self.log("This file was written by the OLD addon (v0.1). Replace the addon folder with the new one, "
                             "then in the game type /reload followed by /gms save.")
                else:
                    self.log("The file has no guild snapshot yet. Make sure you're in the guild, give the roster a few "
                             "seconds to load after logging in, then type /gms save.")
                return True
            st, msgs, notes = process(snap, load_state(), self.cfg, datetime.now())
            for n in notes:
                self.log(n)
            parts = chunk(msgs)
            for i, part in enumerate(parts):
                ok, _, err = post(self.cfg["webhook"], content=part)
                if not ok:
                    self.log(f"Couldn't post to Discord ({err}). I'll try again shortly.")
                    return False
                if i + 1 < len(parts):
                    time.sleep(1.2)
            if msgs:
                self.log(f"Posted {len(msgs)} announcement(s).")
            if self.cfg["digest_enabled"] or force_digest:
                ok, what = push_digest(st, self.cfg, force=force_digest)
                if what != "unchanged":
                    self.log(f"Weekly digest {what}." if ok else f"Digest problem: {what}")
            save_state(st)
            self.log(f"Checked {len(snap['members'])} members.")
            return True

    def run(self, stop):
        if self.shared:
            return self._run_shared(stop)
        last, last_path, warned = 0, "", False
        self.log("Watching for changes. You can minimise this window.")
        while not stop.is_set():
            try:
                path = resolve_savedvars(self.cfg)
                if not path:
                    if not warned:
                        self.log("Can't find the addon file yet. In the game, type /gms save. I'll keep looking.")
                        warned = True
                else:
                    warned = False
                    if path != last_path:
                        last, last_path = 0, path
                    m = os.stat(path).st_mtime
                    if m != last:
                        last = m if self.check() else 0
            except Exception as e:
                self.log(f"Something went wrong: {e}")
            stop.wait(POLL_SECONDS)
        self.log("Stopped.")


    # ------------------------------ shared mode ------------------------------
    def _run_shared(self, stop):
        self.log("Shared mode is on. Checking in with the shared service...")
        while not stop.is_set():
            try:
                self.shared_step()
            except Exception as e:
                self.log(f"Something went wrong: {e}")
            stop.wait(POLL_SECONDS)
        self.release()                      # hand over politely so another officer can take the role quickly
        self.log("Stopped.")

    def _role(self, kind, text):
        if (kind, text) != (self.role, self.role_text):
            self.role, self.role_text = kind, text
            self.log(text)
            if self.status_cb:
                self.status_cb(kind, text)

    def _local_snapshot(self):
        path = resolve_savedvars(self.cfg)
        if not path:
            return None
        try:
            m = os.stat(path).st_mtime
            if self.cache[0] != m:
                self.cache = (m, parse_file(path))
            snap = self.cache[1]
        except Exception as e:
            if "file" not in self.warned:
                self.warned.add("file")
                self.log(f"Couldn't read the addon file here ({e}). Other officers' data can still be used.")
            return None
        if snap["members"] and snap["updated"] > self.uploaded_ts:
            return {"updated": snap["updated"], "members": snap["members"], "profs": snap["profs"],
                    "from": self.cfg.get("my_name", "")}
        return None

    def shared_step(self, force=False, force_digest=False):
        with _LOCK:
            now = time.time()
            snap_up = self._local_snapshot()
            if not (force or snap_up or now - self.last_sync >= HEARTBEAT):
                if self.role == "announcer" and self.outbox:
                    self._flush()
                return True
            ok, res, err = self.store.sync(snap_up, want_all=force_digest)
            self.last_sync = now
            if not ok:
                self._role("offline", f"Can't reach the shared service ({err}). Staying quiet so nothing is posted twice.")
                return False
            if snap_up:
                self.uploaded_ts = snap_up["updated"]
            if not res.get("leader"):
                if res.get("reason") == "cooling down":
                    self._role("standby", "Standby: taking a short break after posting errors.")
                else:
                    self._role("standby", f"Standby: {res.get('leaderName') or 'another officer'} is announcing.")
                return True
            self._role("announcer", "Announcer: you're posting for the guild.")
            if self.outbox:
                self._flush()
            snap = res.get("snapshot")
            if snap is None:
                return True
            return self._announce(snap, res.get("state"), int(res.get("stateVersion") or 0), force_digest)

    def _announce(self, snap, state, version, force_digest):
        if state is None:                                   # first time: carry this PC's memory into the service
            state = load_state()
            if state["initialized"]:
                self.log("Moved this PC's memory into the shared service.")
        if self.pending_digest:
            state["digest"] = self.pending_digest
        new, msgs, notes = process(snap, state, self.cfg, datetime.now())
        new["snap_ts"] = snap["updated"]
        if self.cfg["digest_enabled"] or force_digest:
            ok, what = push_digest(new, self.cfg, force=force_digest)
            if what != "unchanged":
                self.log(f"Weekly digest {what}." if ok else f"Digest problem: {what}")
            if ok and what == "posted":
                self.pending_digest = new["digest"]         # remembered in case the save below fails
        ok, res, err = self.store.commit(new, version)      # save memory BEFORE posting, so nothing posts twice
        if not ok:
            self.log(f"Couldn't save to the shared service ({err}). I'll try again.")
            return False
        self.pending_digest = None
        new["version"] = res["version"]
        for n in notes:
            self.log(n)
        self.outbox += [(t, 0) for t in chunk(msgs)]
        if msgs:
            self.log(f"Posting {len(msgs)} announcement(s)...")
        self._flush()
        save_state(new)
        self.log(f"Checked {len(snap['members'])} members.")
        return True

    def _flush(self):
        while self.outbox:
            text, tries = self.outbox[0]
            ok, _, err = post(self.cfg["webhook"], content=text)
            if ok:
                self.outbox.pop(0)
                self.fail_streak = 0
                continue
            self.fail_streak += 1
            self.log(f"Couldn't post to Discord ({err}).")
            if tries + 1 >= 3:
                self.outbox.pop(0)
                self.log("Gave up on one announcement after 3 tries.")
            else:
                self.outbox[0] = (text, tries + 1)
            if self.fail_streak >= 3:
                self.log("Posting keeps failing on this PC, so I'm handing the announcer role to another officer for 10 minutes.")
                self.outbox.clear()
                self.release(600)
            return

    def release(self, cooldown=0):
        if not self.store:
            return
        try:
            self.store.release(cooldown)
        except Exception:
            pass
        self.role, self.role_text = "", ""


# ------------------------- game folder and addon install -------------------------
def game_folder_from(path):
    """.../_retail_/WTF/Account/<acct>/SavedVariables/GuildMilestones.lua  ->  .../_retail_"""
    try:
        p = Path(path)
        if p.parents[3].name == "WTF":
            return str(p.parents[4])
    except Exception:
        pass
    return ""


def resolve_savedvars(cfg):
    """Find the addon's file inside the game folder (newest one if you have several accounts)."""
    g = str(cfg.get("game_folder", "")).strip()
    if g:
        hits = glob.glob(os.path.join(g, "WTF", "Account", "*", "SavedVariables", "GuildMilestones.lua"))
        return max(hits, key=os.path.getmtime) if hits else ""
    return str(cfg.get("savedvars", "")).strip()


def find_game_folders():
    roots = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), "C:\\", "D:\\", "E:\\"]
    hits = []
    for r in filter(None, roots):
        for pat in ("World of Warcraft/_*_", "Games/World of Warcraft/_*_"):
            hits += [h for h in glob.glob(os.path.join(r, pat)) if os.path.isdir(os.path.join(h, "Interface"))]
    return list(dict.fromkeys(hits))


def bundled_addon_dir():
    return Path(getattr(sys, "_MEIPASS", APP_DIR)) / "GuildMilestones"


def _toc_version(folder):
    try:
        for line in (Path(folder) / "GuildMilestones.toc").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("## version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def addon_status(game):
    """(version installed in the game or None, version bundled with this app or None)"""
    return (_toc_version(Path(game) / "Interface" / "AddOns" / "GuildMilestones"),
            _toc_version(bundled_addon_dir()))


def install_addon(game):
    src, dst = bundled_addon_dir(), Path(game) / "Interface" / "AddOns" / "GuildMilestones"
    if not src.is_dir():
        return False, "The addon files are missing from the app's folder."
    if not (Path(game) / "Interface").is_dir():
        return False, "That doesn't look like a game folder (there's no Interface folder inside it)."
    try:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return True, f"Addon v{_toc_version(dst)} installed."
    except PermissionError:
        return False, ("Windows blocked writing to the game folder. Close the app, right-click it, choose "
                       "'Run as administrator' once, and try again.")
    except Exception as e:
        return False, f"Couldn't install the addon: {e}"


# ------------------------------- updating from GitHub -------------------------------
UPDATE_FILES = ("engine.py", "milestone_gui.py", "GuildMilestones.pyw", "README.md", "CHANGES.md", "HOW TO UPDATE.txt", "build_exe.bat")
UPDATE_DIRS = ("GuildMilestones", "shared")


def _fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "GuildMilestones/" + APP_VERSION,
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fresh(url):
    """GitHub's raw files are cached for ~5 minutes. A unique query string skips that cache."""
    return url + ("&" if "?" in url else "?") + f"cb={int(time.time())}"


def log_error(text):
    """Write problems to a file, because the app has no console to show them in."""
    try:
        with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    except Exception:
        pass


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def latest_version():
    """Reads APP_VERSION out of engine.py on GitHub. Returns (version or None, where it was read from)."""
    pat = r'APP_VERSION\s*=\s*"([^"]+)"'
    err = None
    try:
        raw = _fetch(_fresh(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/engine.py")).decode("utf-8", "replace")
        m = re.search(pat, raw)
        return (m.group(1) if m else None), "raw"
    except Exception as e:
        err = e
    try:                                              # second route, in case the first one is blocked
        import base64
        meta = json.loads(_fetch(_fresh(f"https://api.github.com/repos/{REPO}/contents/engine.py?ref={BRANCH}")))
        m = re.search(pat, base64.b64decode(meta["content"]).decode("utf-8", "replace"))
        return (m.group(1) if m else None), "api"
    except Exception:
        raise err


def latest_notes(version):
    """The 'what's new' text for a version, taken from CHANGES.md on GitHub (or '')."""
    try:
        raw = _fetch(_fresh(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGES.md")).decode("utf-8", "replace")
        m = re.search(r"^##\s*v?%s\b[^\n]*\n(.*?)(?=^##\s|\Z)" % re.escape(version), raw, re.S | re.M)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def update_available():
    """(latest version, True if it is newer than this one)"""
    latest, _ = latest_version()
    return latest, bool(latest) and _ver(latest) > _ver(APP_VERSION)


def check_report():
    """Plain-English result of an update check, for the Setup tab."""
    try:
        latest, _ = latest_version()
    except Exception as e:
        log_error(f"update check failed: {e!r}")
        return {"ok": False, "newer": False, "latest": None, "text": f"Couldn't reach GitHub ({e})."}
    if not latest:
        return {"ok": False, "newer": False, "latest": None,
                "text": "GitHub answered, but I couldn't find a version number in engine.py there."}
    newer = _ver(latest) > _ver(APP_VERSION)
    if newer:
        text = f"GitHub has v{latest}; this app is v{APP_VERSION}. An update is available."
    else:
        text = (f"GitHub's engine.py says v{latest}, and this app is v{APP_VERSION}, so you're up to date. "
                "If you uploaded a newer version, check that engine.py itself was replaced on GitHub.")
    return {"ok": True, "newer": newer, "latest": latest, "text": text}


def apply_update(zip_bytes=None):
    """Download the repo as a zip, check the new code compiles, then copy it over this app.
    Returns (ok, message). The caller restarts the app afterwards."""
    if getattr(sys, "frozen", False):
        return False, "This is the .exe version, which can't update itself. Use GuildMilestones.pyw instead."
    try:
        data = zip_bytes or _fetch(f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip", timeout=60)
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                root = z.namelist()[0].split("/")[0]
                for name in z.namelist():
                    rel = name[len(root) + 1:]
                    if not rel or name.endswith("/"):
                        continue
                    if ".." in rel.split("/") or not (rel in UPDATE_FILES or rel.split("/")[0] in UPDATE_DIRS):
                        continue
                    dest = Path(tmp) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(name))
            stage = Path(tmp)
            for need in ("engine.py", "milestone_gui.py", "GuildMilestones.pyw", "GuildMilestones/GuildMilestones.toc"):
                if not (stage / need).exists():
                    return False, f"The download is missing {need}, so I left everything as it was."
            for py in ("engine.py", "milestone_gui.py", "GuildMilestones.pyw"):
                compile((stage / py).read_text(encoding="utf-8"), py, "exec")      # refuse a broken upload
            backup = DATA_DIR / "backup"
            backup.mkdir(parents=True, exist_ok=True)
            for f in UPDATE_FILES:
                if (APP_DIR / f).exists():
                    shutil.copy2(APP_DIR / f, backup / f)
                if (stage / f).exists():
                    shutil.copy2(stage / f, APP_DIR / f)
            for d in UPDATE_DIRS:
                if (stage / d).is_dir():
                    target = APP_DIR / d
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(stage / d, target)
        return True, "Update downloaded."
    except PermissionError:
        return False, "Windows wouldn't let me change the app's folder. Move the app to somewhere like Documents and try again."
    except SyntaxError as e:
        return False, f"The new code has a mistake in it ({e.msg}), so I left everything as it was."
    except Exception as e:
        return False, f"Couldn't update: {e}"
