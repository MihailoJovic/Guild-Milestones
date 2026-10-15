"""Guild Milestones engine: reads the addon's file, decides what to announce, talks to Discord.
No window code in here, so it can be tested on its own."""
import copy, glob, hashlib, io, uuid, json, os, re, shutil, sys, tempfile, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))              # True when running as GuildMilestones.exe
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))          # where bundled files (addon, icon) live
ICON = RES_DIR / "assets" / "gm.ico"
APP_VERSION = "0.11.0"
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
POLL_SECONDS = 2           # how often the addon file is checked (only read when it changed)
RETRY_SECONDS = 30        # after a failed post, wait this long before trying again
MAX_OUTBOX = 60           # announcements kept waiting when Discord can't be reached
MAX_WELCOMES = 5          # more brand-new names than this at once = probably a roster hiccup, so stay quiet
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIER_NAMES = {75: "Journeyman", 150: "Expert", 225: "Artisan", 300: "Master"}
# Raid attunements and dungeon keys. The codes must match ATTUNE in the addon (GuildMilestones.lua).
ATTUNEMENTS = {"ony": "🐉 Onyxia's Lair", "mc": "🔥 Molten Core", "bwl": "🖤 Blackwing Lair",
               "ubrs": "🗝️ Upper Blackrock Spire", "scholo": "💀 Scholomance", "brd": "⚒️ Shadowforge (BRD)"}
RAID_KEYS = ("ony", "mc", "bwl")
# What people can look for in the Groups tab. Codes must match LFG_OPTIONS in the addon (UI.lua).
LFG_NAMES = {"rfc": "Ragefire Chasm", "wc": "Wailing Caverns", "dm": "Deadmines", "sfk": "Shadowfang Keep",
             "bfd": "Blackfathom Deeps", "stocks": "Stockade", "gnomer": "Gnomeregan", "rfk": "Razorfen Kraul",
             "sm": "Scarlet Monastery", "rfd": "Razorfen Downs", "ulda": "Uldaman", "zf": "Zul'Farrak",
             "mara": "Maraudon", "st": "Sunken Temple", "brd": "Blackrock Depths", "lbrs": "Lower Blackrock Spire",
             "ubrs": "Upper Blackrock Spire", "dire": "Dire Maul", "strat": "Stratholme", "scholo": "Scholomance",
             "attune": "Attunement help", "quest": "Questing buddy", "elite": "Elite quests", "pvp": "PvP"}
LFG_FRESH = 90 * 60       # a "looking for group" note shows for this long
CLASS_NAMES = {"DEATHKNIGHT": "Death Knight", "DEMONHUNTER": "Demon Hunter"}
CLASS_COLORS = {"DEATHKNIGHT": 0xC41E3A, "DEMONHUNTER": 0xA330C9, "DRUID": 0xFF7C0A, "EVOKER": 0x33937F,
                "HUNTER": 0xAAD372, "MAGE": 0x3FC7EB, "MONK": 0x00FF98, "PALADIN": 0xF48CBA, "PRIEST": 0xFFFFFF,
                "ROGUE": 0xFFF468, "SHAMAN": 0x0070DD, "WARLOCK": 0x8788EE, "WARRIOR": 0xC69B6D}
DEFAULT_COLOR = 0x5865F2

DEFAULTS = {
    "webhook": "", "digest_webhook": "", "game_folder": "", "savedvars": "",
    "auto_start": False, "auto_update_addon": True, "tray_on_close": True, "start_with_windows": False,
    "shared_on": False, "shared_url": "", "shared_token": "", "my_name": "", "device_id": "",
    "announce_levels": True, "announce_firsts": True, "announce_tiers": True,
    "welcome_new": True, "welcome_back": True, "digest_enabled": True, "ladder_enabled": True, "skip_shouted": False,
    "event_loot": True, "event_boss": True, "event_death": False, "event_quest": False, "loot_min_quality": 3,
    "milestones": "10, 20, 30, 40, 50, 60", "max_level": 60, "tiers": "75, 150, 225, 300",
    "week_start": 0,
    # v0.11: more boards and moments
    "fame_enabled": True, "attune_enabled": True, "crafters_enabled": True, "lfg_enabled": True,
    "event_mount": True, "event_attune": True, "recap": True,
    "hardcore": False, "mvp_poll": True, "mvp_day": 4,
    "goal_level": 0, "goal_date": "", "goal_raid": "mc", "goal_raid_count": 0,
    "level_msg": "🎉 Congrats **{name}** on hitting Level {level}!",
    "welcome_msg": "👋 Welcome to the guild, **{name}**! ({cls}, level {level})",
    "tips": "10=Tip: ask who in the guild crafts. Free help is the best help!\n"
            "20=Tip: shout in guild chat for a dungeon group. Someone's usually keen.",
}
_LOCK = threading.Lock()
CONFIG_REV = 2            # bump when an old saved setting must be changed once for everyone
WELCOME_BACK_DAYS = 14    # away at least this long = "welcome back" post


# ----------------------------- small helpers -----------------------------
def _write_json(path, data):
    """Write to a temporary file first, then swap it in, so a crash never leaves half a file."""
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path):
    """The saved dict, or None if there's no file. A damaged file is kept aside (never silently lost)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        keep = path.with_name(f"{path.stem}.damaged-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
        try:
            shutil.copy2(path, keep)
        except Exception:
            pass
        log_error(f"{path.name} couldn't be read ({e!r}); a copy was kept as {keep.name}")
        return None


def load_config():
    saved = _read_json(CONFIG_FILE) or {}
    cfg = {**DEFAULTS, **saved}
    if int(saved.get("cfg_rev", 0) or 0) < CONFIG_REV:
        # v0.9.0: "skip what the addon already shouted" now starts off, because nobody has confirmed that
        # Blizzard's Discord link carries addon lines on WoW: Forever. Officers can switch it back on.
        cfg["skip_shouted"] = False
        cfg["cfg_rev"] = CONFIG_REV
        if saved:
            try:
                save_config(cfg)
            except Exception:
                pass
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
    _write_json(CONFIG_FILE, {**cfg, "cfg_rev": CONFIG_REV})


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


def class_color(c):
    return CLASS_COLORS.get(str(c or "").upper(), DEFAULT_COLOR)


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
    heard = []                                  # what the addon already announced in guild chat
    for row in _block(text, "heard"):
        p = row.split("|")
        try:
            if p[1] == "L":
                heard.append({"name": p[0], "kind": "L", "level": int(p[2])})
            elif p[1] == "S":
                heard.append({"name": p[0], "kind": "S", "prof": p[2], "tier": int(p[3])})
        except (IndexError, ValueError):
            pass
    events = []                                 # loot, bosses, deaths, quests the addon recorded
    for row in _block(text, "events"):
        p = row.split("|")
        try:
            events.append({"kind": p[0], "name": p[1], "ts": int(p[2]), "a": p[3], "b": p[4], "c": p[5]})
        except (IndexError, ValueError):
            pass
    keys = {}                                   # attunements and dungeon keys: who -> ["mc", "ony", ...]
    for row in _block(text, "keys"):
        p = row.split("|")
        if len(p) >= 2 and p[0]:
            keys[p[0]] = [k for k in p[1].split(",") if k in ATTUNEMENTS]
    lfg = []                                    # who is looking for a group (the addon's Groups tab)
    for row in _block(text, "lfg"):
        p = row.split("|")
        try:
            lfg.append({"name": p[0], "level": int(p[1]), "cls": p[2], "role": p[3],
                        "wants": [w for w in p[4].split(",") if w], "ts": int(p[5])})
        except (IndexError, ValueError):
            pass
    m = re.search(r'\["updated"\]\s*=\s*(\d+)', text)
    updated = int(m.group(1)) if m else int(Path(path).stat().st_mtime)
    g = re.search(r'\["guild"\]\s*=\s*"((?:[^"\\\n]|\\.)*)"', text)
    return {"members": members, "profs": profs, "heard": heard, "events": events, "updated": updated,
            "keys": keys, "lfg": lfg,
            "guild": g.group(1).replace('\\"', '"') if g else "",
            "legacy": '["entries"]' in text and not members}


# ---------------------------------- state ----------------------------------
def week_id(now, start):
    return (now.date() - timedelta(days=(now.weekday() - int(start)) % 7)).isoformat()


def new_week(wid):
    return {"id": wid, "new": [], "gains": {}, "milestones": [], "tiers": [], "loot": {}, "boss": {},
            "quests": {}, "deaths": {}, "back": []}


def hook_key(url):
    """A short fingerprint of a webhook URL. The URL itself is a secret, so it is never saved in the state."""
    return hashlib.sha256(str(url).strip().encode("utf-8")).hexdigest()[:16]


def load_state():
    st = {"initialized": False, "members": {}, "firsts": {}, "profs": {}, "crafters": {},
          "week": new_week(""), "boards": {}, "outbox": []}
    st.update(_read_json(STATE_FILE) or {})
    return migrate_boards(st)


def migrate_boards(st):
    """Board message ids live in st["boards"]. Before v0.11 the digest and race board sat at the top level,
    and v0.8 even kept the full webhook URL there."""
    boards = st.setdefault("boards", {})
    for key in ("digest", "ladder"):
        d = st.pop(key, None)
        if isinstance(d, dict) and d:
            if d.get("url"):
                d["hook"] = hook_key(d.pop("url"))
            boards.setdefault(key, d)
    return st


def save_state(st):
    _write_json(STATE_FILE, st)


def _seed_firsts(st, cls, level, levels):
    for m in levels:
        if m <= level:
            st["firsts"].setdefault(f"level:{m}", "")
            st["firsts"].setdefault(f"class:{cls}:{m}", "")


# ------------------------------ guild firsts, lifetime stats ------------------------------
def add_fame(st, key, title, who, detail="", when="", seed=False):
    """Record a guild first. Returns True only for a brand-new first (worth a post).
    seed=True marks it as 'happened before records began', so a later achiever isn't called first."""
    fame = st.setdefault("fame", {})
    if key in fame:
        return False
    fame[key] = {"title": title, "who": "" if seed else who, "detail": detail, "when": when}
    return not seed


def fame_card(title, who, detail, color=0xF2B84B):
    text = f"🏆 **Guild first!** {title}: **{who}**" + (f"\n{detail}" if detail else "")
    return {"text": text, "color": color}


def bump_stat(st, who, key, n=1):
    s = st.setdefault("stats", {}).setdefault(who, {})
    s[key] = s.get(key, 0) + n


def build_recap(st, who, cls, cap, today):
    """The 'road to the cap' card for someone who just made it."""
    s = st.get("stats", {}).get(who, {})
    rec = next((r for n, r in st.get("members", {}).items() if short(n) == who), {})
    days = ""
    try:
        start = datetime.strptime(rec.get("first_seen", ""), "%Y-%m-%d").date()
        days = (datetime.strptime(today, "%Y-%m-%d").date() - start).days
    except ValueError:
        pass
    firsts = [f["title"] for f in st.get("fame", {}).values() if f.get("who") == who]
    fields = [{"name": "Days on the road", "value": str(days) if days != "" else "?", "inline": True},
              {"name": "Bosses defeated", "value": str(s.get("bosses", 0)), "inline": True},
              {"name": "Epics looted", "value": str(s.get("epics", 0)), "inline": True},
              {"name": "Quests done", "value": str(s.get("quests", 0)), "inline": True},
              {"name": "Deaths", "value": str(s.get("deaths", 0)), "inline": True},
              {"name": "Mount", "value": {2: "Epic 🦄", 1: "Yes 🐎"}.get(s.get("mount", 0), "Still walking"), "inline": True}]
    if firsts:
        fields.append({"name": "🥇 Guild firsts", "value": _clip(firsts, 900)})
    return {"title": f"🏁 {who}'s road to {cap}", "text": f"**{who}** the {class_name(cls)} made it to the level cap. "
            "Here's how the journey went:", "color": class_color(cls), "fields": fields}


# ------------------------------ the brain ------------------------------
def process(snap, state, cfg, now):
    """Compare the newest snapshot with what we remember. Returns (new_state, messages, notes)."""
    st, msgs, notes = migrate_boards(copy.deepcopy(state)), [], []
    cap = int(cfg["max_level"])
    levels = nums(cfg["milestones"]) | {cap}
    tiers, tips = nums(cfg["tiers"]), parse_tips(cfg["tips"])
    today = now.date().isoformat()
    skip = bool(cfg.get("skip_shouted", True))
    heard_l = {(h["name"].lower(), h["level"]) for h in snap.get("heard", []) if h["kind"] == "L"}
    heard_s = {(h["name"].lower(), h["prof"].lower(), h["tier"]) for h in snap.get("heard", []) if h["kind"] == "S"}
    cls_of = {short(m["name"]).lower(): m["cls"] for m in snap["members"]}

    guild = snap.get("guild") or ""
    if guild and st.get("guild") and guild != st["guild"]:
        notes.append(f"The addon file is from a character in another guild ({guild}), so I skipped it. "
                     f"It will be used again after you log out of a character in {st['guild']}.")
        return state, [], notes
    if guild:
        st["guild"] = guild

    wid = week_id(now, cfg["week_start"])
    if st["week"].get("id") != wid:
        st["week"] = new_week(wid)
        st.setdefault("boards", {})["digest"] = {}              # a fresh digest message each week
        notes.append("A new week has started.")
    week = st["week"]
    for k, empty in (("quests", {}), ("deaths", {}), ("back", [])):
        week.setdefault(k, empty)

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
            st["members"][name] = {"level": level, "class": cls, "first_seen": today, "off": m.get("off", 0)}
            _seed_firsts(st, cls, level, levels)
            if level >= cap:
                add_fame(st, "cap", "", "", seed=True)
            if name not in quiet:
                week["new"].append({"name": who, "cls": cname, "level": level})
                if cfg["welcome_new"]:
                    msgs.append({"text": fmt(cfg["welcome_msg"], name=who, level=level, cls=cname),
                                 "color": class_color(cls)})
            continue

        away, now_off = rec.get("off"), m.get("off", 0)
        if away is not None and away >= WELCOME_BACK_DAYS and now_off <= away - 7:
            week["back"].append({"name": who, "days": away})
            if cfg.get("welcome_back", True):
                msgs.append({"text": f"👋 Welcome back, **{who}**! It's been {away} days. Good to see you again.",
                             "color": class_color(cls), "silent": True})
        rec["off"] = now_off

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
                    shouted = skip and (who.lower(), top) in heard_l      # the player already said it in guild chat
                    extra = []
                    if cfg["announce_firsts"]:
                        if guild_first:
                            extra.append(f"🥇 First in the guild to hit {top}!")
                        elif class_first:
                            extra.append(f"🥈 First {cname} in the guild to hit {top}!")
                    if top in tips and top != cap:
                        extra.append(f"💡 {tips[top]}")
                    if shouted:
                        text = "\n".join([f"**{who}** · level {top}"] + extra) if extra else ""
                    else:
                        if top == cap:
                            text = f"🏆 **{who}** hit the level cap: **Level {top}**! Absolute legend."
                        else:
                            text = fmt(cfg["level_msg"], name=who, level=top, cls=cname)
                        text = "\n".join([text] + extra)
                    if text:
                        msgs.append({"text": text, "color": class_color(cls)})
                if top == cap:
                    add_fame(st, "cap", f"First to level {cap}", who, when=today)
                    if cfg.get("recap", True):
                        msgs.append(build_recap(st, who, cls, cap, today))
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
                if cfg["announce_tiers"] and not (skip and (short(p["name"]).lower(), p["prof"].lower(), t) in heard_s):
                    msgs.append({"text": f"🔨 **{short(p['name'])}** reached **{label}** in {p['prof']}!",
                                 "color": class_color(cls_of.get(short(p["name"]).lower())), "silent": True})
                if t == max(tiers) and add_fame(st, f"prof:{p['prof']}", f"First {label} {p['prof']}",
                                                short(p["name"]), when=today) and cfg.get("fame_enabled", True):
                    msgs.append(fame_card(f"First {label} {p['prof']}", short(p["name"]), ""))
        elif old is None and tiers and p["skill"] >= max(tiers):
            add_fame(st, f"prof:{p['prof']}", "", "", seed=True)          # already maxed before we started
        mine[p["prof"]] = p["skill"]

    if snap["profs"]:
        crafters = {}
        for p in snap["profs"]:
            crafters.setdefault(p["prof"], []).append([short(p["name"]), p["skill"]])
        st["crafters"] = {k: sorted(v, key=lambda r: -r[1]) for k, v in crafters.items()}

    # attunements and keys: only announce what's new since we last looked at that person
    known = st.setdefault("keys", {})
    for who, have in (snap.get("keys") or {}).items():
        who = short(who)
        before = known.get(who)
        known[who] = sorted(set(have) | set(before or []))
        if before is None or not st["initialized"]:
            for k in have:
                add_fame(st, f"attune:{k}", "", "", seed=True)
            continue
        for k in sorted(set(have) - set(before)):
            label = ATTUNEMENTS.get(k, k)
            first = add_fame(st, f"attune:{k}", f"First attuned: {label}", who, when=today)
            if first and cfg.get("fame_enabled", True):
                msgs.append(fame_card(f"First attuned to {label}", who, ""))
            elif cfg.get("event_attune", True):
                msgs.append({"text": f"🔑 **{who}** is attuned: {label}", "color": class_color(cls_of.get(who.lower())),
                             "silent": True})

    st["lfg"] = [x for x in snap.get("lfg", []) if snap.get("updated", 0) - x["ts"] < LFG_FRESH]

    msgs.extend(event_items(snap.get("events", []), st, cfg, cls_of))

    st["initialized"] = True
    return st, msgs, notes


# ------------------------------- loot, bosses, deaths, quests -------------------------------
QUALITY_COLORS = {0: 0x9D9D9D, 1: 0xFFFFFF, 2: 0x1EFF00, 3: 0x0070DD, 4: 0xA335EE, 5: 0xFF8000}
QUALITY_NAMES = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
BOSS_WINDOW = 15 * 60     # reports of the same boss within this many seconds are one kill
_ITEM_CACHE = {}


def item_lookup(item_id):
    """Icon and name for an item from Wowhead (one small request per item, remembered). Never fatal."""
    if item_id in _ITEM_CACHE:
        return _ITEM_CACHE[item_id]
    info = {}
    try:
        raw = _fetch(f"https://nether.wowhead.com/classic/tooltip/item/{int(item_id)}", timeout=5)
        data = json.loads(raw.decode("utf-8", "replace"))
        if data.get("icon"):
            info["icon"] = f"https://wow.zamimg.com/images/wow/icons/large/{data['icon']}.jpg"
        info["name"] = data.get("name", "")
    except Exception:
        pass
    _ITEM_CACHE[item_id] = info
    return info


def event_key(ev):
    return f"{ev['kind']}|{ev['name']}|{ev['ts']}|{ev['a']}"


def event_items(events, st, cfg, cls_of, lookup=item_lookup):
    """Rich embeds for loot, boss kills, deaths and quests. The first run only learns what already exists."""
    seen = st.get("events_seen")
    keys = [event_key(e) for e in events]
    if seen is None:
        st["events_seen"] = keys[-500:]
        return []
    seen_set, items, looked = set(seen), [], 0
    min_q = int(cfg.get("loot_min_quality", 3))
    kills = {}                                             # boss -> everyone the addon heard killing it
    wk = st.setdefault("week", {})                         # weekly leaderboard counts

    def bump(cat, who):
        wk.setdefault(cat, {})[who] = wk.setdefault(cat, {}).get(who, 0) + 1

    for ev, key in zip(events, keys):
        if key in seen_set:
            continue
        seen_set.add(key)
        who, color = short(ev["name"]), class_color(cls_of.get(short(ev["name"]).lower()))
        kind = ev["kind"]
        when = datetime.fromtimestamp(ev["ts"]).strftime("%Y-%m-%d") if ev["ts"] > 0 else ""
        if kind == "I":
            try:
                q = int(ev["b"].split(":")[0])
                if q >= 3:
                    bump("loot", who)
                if q >= 4:
                    bump_stat(st, who, "epics")
                    name = ev["c"] or f"item {ev['a']}"
                    if add_fame(st, "epic", "First epic item", who, name, when) and cfg.get("fame_enabled", True):
                        items.append(fame_card("First epic item", who, f"**{name}**", QUALITY_COLORS[4]))
                if q >= 5 and add_fame(st, "legendary", "First legendary", who, ev["c"], when) and cfg.get("fame_enabled", True):
                    items.append(fame_card("First legendary", who, f"**{ev['c']}**", QUALITY_COLORS[5]))
            except ValueError:
                pass
        elif kind == "B":
            bump("boss", who)
            bump_stat(st, who, "bosses")
        elif kind == "Q":
            bump("quests", who)
            bump_stat(st, who, "quests")
        elif kind == "D":
            bump("deaths", who)
            bump_stat(st, who, "deaths")
            fallen = st.setdefault("fallen", [])
            fallen.append({"name": who, "level": ev["b"], "zone": ev["a"] or "the wilds", "ts": ev["ts"]})
            del fallen[:-50]
        elif kind == "M":                                  # mounts: a = "mount" (normal) or "epic"
            epic = ev["a"] == "epic"
            have = st.get("stats", {}).get(who, {}).get("mount", 0)
            if (2 if epic else 1) <= have:
                continue                                   # already celebrated
            st.setdefault("stats", {}).setdefault(who, {})["mount"] = 2 if epic else 1
            first = add_fame(st, "epicmount" if epic else "mount", "First epic mount" if epic else "First mount", who,
                             when=when)
            if cfg.get("event_mount", True):
                text = (f"🦄 **{who}** is riding an **epic mount**! Fast, shiny and very expensive." if epic else
                        f"🐎 **{who}** got their **first mount**! No more walking.")
                if first and cfg.get("fame_enabled", True):
                    text += f"\n🥇 First in the guild!"
                items.append({"text": text, "color": color})
            continue
        if kind == "B":
            k = kills.setdefault(ev["a"], {"names": [], "ts": ev["ts"], "size": ev["b"], "color": color})
            if who not in k["names"]:
                k["names"].append(who)
            continue
        if kind == "I" and cfg.get("event_loot", True):
            try:
                q, ilvl = (int(x) for x in ev["b"].split(":"))
                item_id = int(ev["a"])
            except ValueError:
                continue
            if q < min_q:
                continue
            info = lookup(item_id) if looked < 5 else {}
            looked += 1
            name = ev["c"] or info.get("name") or f"Item {item_id}"
            detail = QUALITY_NAMES.get(q, "") + (f" · item level {ilvl}" if ilvl else "")
            item = {"text": f"**{who}** looted **{name}**\n{detail}", "color": QUALITY_COLORS.get(q, color),
                    "title": name, "url": f"https://www.wowhead.com/classic/item={item_id}", "silent": q < 4}
            if info.get("icon"):
                item["thumb"] = info["icon"]
            items.append(item)
        elif kind == "D" and cfg.get("hardcore", False):          # Hardcore: a death is final, so a proper farewell
            lvl = f", level {ev['b']}" if str(ev["b"]).isdigit() else ""
            items.append({"text": f"🪦 **{who}**{lvl} has fallen in {ev['a'] or 'the wilds'}.\nRest well, hero. "
                                  "Your name goes on the Fallen Heroes wall.", "color": 0x4B5563})
        elif kind == "D" and cfg.get("event_death", False):
            items.append({"text": f"💀 **{who}** has died in {ev['a'] or 'the wilds'}.", "color": color, "silent": True})
        elif kind == "Q" and cfg.get("event_quest", False):
            items.append({"text": f"📜 **{who}** completed **{ev['a']}**.", "color": color, "silent": True})

    # One card per boss kill, however many members' addons reported it.
    posted = st.setdefault("boss_posted", {})
    for boss, k in kills.items():
        if k["ts"] - posted.get(boss, 0) < BOSS_WINDOW:
            continue                                       # already celebrated this kill
        posted[boss] = k["ts"]
        if not cfg.get("event_boss", True):
            continue
        names = k["names"]
        crew = ", ".join(f"**{n}**" for n in names[:-1]) + f" and **{names[-1]}**" if len(names) > 1 else f"**{names[0]}**"
        size = f" (group of {k['size']})" if str(k["size"]).isdigit() and int(k["size"]) > len(names) else ""
        first = add_fame(st, f"boss:{boss}", f"First kill: {boss}", ", ".join(names),
                         when=datetime.fromtimestamp(k["ts"]).strftime("%Y-%m-%d"))
        extra = "\n🥇 **Guild first kill!**" if first and cfg.get("fame_enabled", True) else ""
        items.append({"text": f"⚔️ **{boss}** is down! Defeated by {crew}{size}.{extra}", "color": k["color"]})
    cutoff = max([0] + [k["ts"] for k in kills.values()]) - 86400
    st["boss_posted"] = {b: t for b, t in posted.items() if t >= cutoff}
    st["events_seen"] = (list(seen) + [k for k in keys if k not in set(seen)])[-500:]
    return items


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


def leaderboard(w):
    """Top three per category for the week: [(title, [(name, text), ...]), ...]. Empty ones are left out."""
    cats = [("💎 Loot Goblin · rare+ drops", w.get("loot", {}), "drop"),
            ("⚔️ Boss Hunter", w.get("boss", {}), "kill"),
            ("📜 Quest Machine", w.get("quests", {}), "quest"),
            ("💀 Darwin Award", w.get("deaths", {}), "death")]
    out = []
    for title, data, unit in cats:
        top = sorted(data.items(), key=lambda kv: -kv[1])[:3]
        if top:
            out.append((title, [(n, f"{c} {unit}{'s' if c != 1 else ''}") for n, c in top]))
    return out


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

    goals = [f"{progress_bar(g['have'], g['need'], 8)} **{g['title'][8:]}** · {g['text']}" for g in guild_goals(st, cfg)]
    if goals:
        fields.append({"name": "🎯 Guild goals", "value": _clip(goals, 900)})

    back = [f"• **{b['name']}** after {b['days']} days" for b in w.get("back", [])[-8:]]
    if back:
        fields.append({"name": "👋 Welcome back", "value": _clip(back, 400)})

    medals = ["🥇", "🥈", "🥉"]
    board = [f"**{t}**\n" + "\n".join(f"{medals[i]} {n} · {txt}" for i, (n, txt) in enumerate(rows))
             for t, rows in leaderboard(w)]
    if board:
        fields.append({"name": "🏆 This week's awards", "value": _clip("\n\n".join(board).split("\n"), 1000)})

    if w["tiers"] or st["crafters"]:
        tr = [f"• **{t['name']}** · {t['tier']} {t['prof']}" for t in w["tiers"][-8:]]
        fields.append({"name": "🔨 Skill tiers", "value": _clip(tr, 600) or "*None yet this week.*"})

    crafters_here = {} if cfg.get("crafters_enabled", True) else st["crafters"]   # they have their own board now
    for prof, rows in sorted(crafters_here.items(), key=lambda kv: -len(kv[1]))[:9]:
        line = " · ".join(f"{n} {s}" for n, s in rows[:8])
        if len(rows) > 8:
            line += f" · +{len(rows) - 8} more"
        fields.append({"name": f"🧰 {prof} ({len(rows)})", "value": line[:300], "inline": True})

    def size(fs):
        return sum(len(f["name"]) + len(f["value"]) for f in fs) + 200
    while size(fields) > 5600 and len(fields) > 3:       # Discord rejects embeds over 6000 characters
        for i in range(len(fields) - 1, -1, -1):
            if fields[i]["name"].startswith("🧰"):
                fields.pop(i)
                break
        else:
            fields.pop()
    for f in fields:
        if not f["value"].strip():
            f["value"] = "-"

    return {
        "title": f"📅 Guild Weekly · week of {start.strftime('%b')} {start.day}",
        "description": "This post updates itself as the week goes on.",
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": f"Resets every {WEEKDAYS[int(cfg['week_start'])]}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------- Discord ---------------------------------
SILENT = 4096            # Discord's SUPPRESS_NOTIFICATIONS flag: the post appears, but pings nobody's phone
_sleep = time.sleep      # swapped out by tests


def _request(method, url, payload=None, timeout=15, retries=3):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": "GuildMilestones/" + APP_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
                return r.status, (json.loads(body) if body else None), ""
        except urllib.error.HTTPError as e:
            raw, info = "", {}
            try:
                raw = e.read().decode("utf-8", "replace")
                info = json.loads(raw)
            except Exception:
                pass
            if e.code == 429 and attempt < retries:          # "slow down": wait as long as Discord asks
                try:
                    wait = float(info.get("retry_after") or e.headers.get("Retry-After") or 2)
                except (TypeError, ValueError, AttributeError):
                    wait = 2.0
                _sleep(min(max(wait, 0.5), 30))
                continue
            detail = f" - {info.get('message') or raw[:200]}" if (info or raw) else ""
            if e.code == 404 and "webhook" in str(info.get("message", "")).lower():
                detail += " (the webhook was deleted: make a new one and paste it on the Setup tab)"
            return e.code, None, f"Discord said HTTP {e.code}{detail}"
        except Exception as e:
            return 0, None, str(e)
    return 429, None, "Discord kept saying 'too many requests'. I'll try again later."


def _with_query(url, extra):
    return url + ("&" if "?" in url else "?") + extra


BOT_NAME = "Guild Milestones"
BOT_AVATAR = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/assets/gm.png"


def post(url, content=None, embed=None, wait=False, embeds=None, silent=False, poll=None):
    """Returns (ok, message_id, error)."""
    if content:
        payload = {"content": content}
    elif poll:
        payload = {"poll": poll}
    else:
        payload = {"embeds": embeds if embeds is not None else [embed]}
    payload["username"], payload["avatar_url"] = BOT_NAME, BOT_AVATAR   # same name and icon, whatever the webhook is called
    payload["allowed_mentions"] = {"parse": []}            # never ping @everyone or roles by accident
    if silent:
        payload["flags"] = SILENT
    if wait:
        url = _with_query(url, "wait=true")
    status, body, err = _request("POST", url, payload)
    return status in (200, 204), (body or {}).get("id"), err


def edit(url, message_id, embed):
    """Edit one of our messages. Keeps ?thread_id= so messages inside threads and forum posts are found.
    Returns (status, error)."""
    base, _, query = url.partition("?")
    target = f"{base}/messages/{message_id}"
    thread = [q for q in query.split("&") if q.startswith("thread_id=")]
    if thread:
        target = _with_query(target, thread[0])
    status, _, err = _request("PATCH", target, {"embeds": [embed]})
    return status, err


def _push_board(st, key, url, embed, force=False):
    """Keep one self-updating message (the digest or the race board). Returns (ok, what happened)."""
    stable = {k: v for k, v in embed.items() if k != "timestamp"}
    h = hashlib.md5(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    d = st.setdefault("boards", {}).setdefault(key, {})
    same_target = d.get("id") and d.get("hook") == hook_key(url)
    if same_target and d.get("hash") == h and not force:
        return True, "unchanged"
    if same_target:
        status, err = edit(url, d["id"], embed)
        if status in (200, 204):
            d["hash"] = h
            return True, "updated"
        if status != 404:                      # 404 = message was deleted, so post a fresh one
            return False, f"edit failed ({err or 'HTTP %s' % status})"
    ok, mid, err = post(url, embed=embed, wait=True, silent=True)
    if ok and mid:
        st["boards"][key] = {"id": mid, "hook": hook_key(url), "hash": h}
        return True, "posted"
    return False, err or "no message id came back"


def board_url(cfg):
    return cfg["digest_webhook"].strip() or cfg["webhook"].strip()


def push_digest(st, cfg, force=False):
    return push_board(st, cfg, "digest", force)


def push_ladder(st, cfg, force=False):
    return push_board(st, cfg, "ladder", force)


def chunk(msgs, per_post=8, limit=5000):
    """Group announcements into Discord posts (each up to 8 colour-coded cards, within Discord's size limit).
    Quiet cards and pinging cards never share a post."""
    out, cur, used = [], [], 0
    for m in msgs:
        n = len(m["text"])
        if cur and (len(cur) >= per_post or used + n > limit or bool(m.get("silent")) != bool(cur[0].get("silent"))):
            out.append(cur)
            cur, used = [], 0
        cur.append(m)
        used += n
    if cur:
        out.append(cur)
    return out


def to_embeds(items):
    out = []
    for it in items:
        em = {"description": it["text"][:4000], "color": it["color"]}
        if it.get("title"):
            em["title"] = it["title"][:250]
        if it.get("url"):
            em["url"] = it["url"]
        if it.get("thumb"):
            em["thumbnail"] = {"url": it["thumb"]}
        if it.get("fields"):
            em["fields"] = it["fields"][:25]
        out.append(em)
    return out


def post_items(url, items):
    return post(url, embeds=to_embeds(items), silent=all(it.get("silent") for it in items))


# ------------------------------ webhooks and examples ------------------------------
WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]+(?:\?thread_id=\d+)?$")


def webhook_problem(url, required=True):
    """Plain-English problem with a webhook URL, or '' when it looks right."""
    url = str(url or "").strip()
    if not url:
        return "Paste a webhook URL here." if required else ""
    if "discord" not in url:
        return "That isn't a Discord link. In Discord: Edit Channel → Integrations → Webhooks → Copy Webhook URL."
    if not WEBHOOK_RE.match(url):
        return "That looks like a Discord link, but not a webhook. It should start with https://discord.com/api/webhooks/"
    return ""


def sample_posts(cfg):
    """One example of every kind of post, so officers can see them all in Discord before the guild does."""
    c = lambda n: class_color(n)
    tag = "\n\n🧪 *Example post*"
    return [
        {"text": fmt(cfg.get("welcome_msg", DEFAULTS["welcome_msg"]), name="Thrall", level=7, cls="Shaman") + tag, "color": c("SHAMAN")},
        {"text": fmt(cfg.get("level_msg", DEFAULTS["level_msg"]), name="Jaina", level=20, cls="Mage")
                 + "\n🥇 First in the guild to hit 20!\n💡 Tip: shout in guild chat for a dungeon group." + tag, "color": c("MAGE")},
        {"text": "🏆 **Arthas** hit the level cap: **Level 60**! Absolute legend." + tag, "color": c("PALADIN")},
        {"title": "🏁 Arthas's road to 60", "text": "**Arthas** the Paladin made it to the level cap. "
         "Here's how the journey went:" + tag, "color": c("PALADIN"),
         "fields": [{"name": "Days on the road", "value": "23", "inline": True},
                    {"name": "Bosses defeated", "value": "41", "inline": True},
                    {"name": "Epics looted", "value": "2", "inline": True},
                    {"name": "Quests done", "value": "312", "inline": True},
                    {"name": "Deaths", "value": "9", "inline": True},
                    {"name": "Mount", "value": "Yes 🐎", "inline": True},
                    {"name": "🥇 Guild firsts", "value": "First to level 60\nFirst kill: Onyxia"}]},
        {"text": "🐎 **Jaina** got their **first mount**! No more walking.\n🥇 First in the guild!" + tag, "color": c("MAGE")},
        {"text": "🏆 **Guild first!** First attuned to 🔥 Molten Core: **Arthas**" + tag, "color": 0xF2B84B},
        {"text": "🔑 **Thrall** is attuned: 🐉 Onyxia's Lair" + tag, "color": c("SHAMAN"), "silent": True},
        {"text": "🔨 **Sylvanas** reached **Artisan (225)** in Tailoring!" + tag, "color": c("HUNTER"), "silent": True},
        {"text": "**Varian** looted **Thunderfury, Blessed Blade of the Windseeker**\nLegendary · item level 80" + tag,
         "color": QUALITY_COLORS[5], "title": "Thunderfury, Blessed Blade of the Windseeker",
         "url": "https://www.wowhead.com/classic/item=19019",
         "thumb": "https://wow.zamimg.com/images/wow/icons/large/inv_sword_39.jpg"},
        {"text": "⚔️ **Onyxia** is down! Defeated by **Varian**, **Jaina** and **Thrall** (group of 10)." + tag, "color": c("WARRIOR")},
        {"text": "👋 Welcome back, **Uther**! It's been 21 days. Good to see you again." + tag, "color": c("PALADIN"), "silent": True},
        {"text": "💀 **Jaina** has died in Westfall." + tag, "color": c("MAGE"), "silent": True},
        {"text": "📜 **Thrall** completed **The Defias Brotherhood**." + tag, "color": c("SHAMAN"), "silent": True},
    ]


def sample_state(cfg):
    """A made-up guild, for example boards."""
    st = {"members": {}, "firsts": {}, "crafters": {}, "week": new_week(week_id(datetime.now(), cfg.get("week_start", 0)))}
    for n, lvl, cls in (("Arthas", 60, "PALADIN"), ("Jaina", 47, "MAGE"), ("Thrall", 44, "SHAMAN"), ("Sylvanas", 38, "HUNTER"),
                        ("Varian", 31, "WARRIOR"), ("Uther", 22, "PALADIN"), ("Valeera", 12, "ROGUE")):
        st["members"][n] = {"level": lvl, "class": cls, "off": 0}
    st["firsts"] = {"level:10": "Jaina", "level:20": "Jaina", "level:30": "Arthas", "level:40": "Arthas",
                    "level:50": "Arthas", "level:60": "Arthas"}
    w = st["week"]
    w["new"] = [{"name": "Valeera", "cls": "Rogue", "level": 12}]
    w["gains"] = {"Jaina": [9, 47], "Thrall": [6, 44], "Varian": [4, 31]}
    w["milestones"] = [{"name": "Jaina", "level": 40}, {"name": "Varian", "level": 30}]
    w["tiers"] = [{"name": "Sylvanas", "prof": "Tailoring", "tier": "Artisan (225)"}]
    w["loot"], w["boss"] = {"Varian": 3, "Jaina": 2}, {"Arthas": 4, "Varian": 4, "Jaina": 3}
    w["quests"], w["deaths"] = {"Thrall": 31, "Jaina": 18}, {"Jaina": 3, "Valeera": 1}
    w["back"] = [{"name": "Uther", "days": 21}]
    st["crafters"] = {"Tailoring": [["Sylvanas", 225], ["Jaina", 150]], "Blacksmithing": [["Varian", 210]],
                      "Alchemy": [["Thrall", 180]]}
    st["fame"] = {"cap": {"title": "First to level 60", "who": "Arthas", "when": "2026-11-20"},
                  "mount": {"title": "First mount", "who": "Jaina", "when": "2026-11-15"},
                  "epic": {"title": "First epic item", "who": "Varian", "detail": "Hand of Ragnaros", "when": "2026-11-22"},
                  "boss:Onyxia": {"title": "First kill: Onyxia", "who": "Arthas, Varian, Jaina", "when": "2026-11-25"},
                  "attune:mc": {"title": "First attuned: 🔥 Molten Core", "who": "Arthas", "when": "2026-11-24"}}
    st["keys"] = {"Arthas": ["ony", "mc", "ubrs"], "Varian": ["ony"], "Thrall": ["ony", "brd"], "Jaina": ["mc"]}
    now = int(time.time())
    st["lfg"] = [{"name": "Thrall", "level": 44, "cls": "SHAMAN", "role": "Healer", "wants": ["zf", "mara"], "ts": now - 600},
                 {"name": "Valeera", "level": 12, "cls": "ROGUE", "role": "DPS", "wants": ["dm"], "ts": now - 1500}]
    st["fallen"] = [{"name": "Uther", "level": "27", "zone": "Stranglethorn Vale", "ts": now - 86400}]
    return st


def send_samples(cfg, log):
    """Post one example of everything: feed cards to the main webhook, the two boards to the boards webhook.
    Returns True if all went through."""
    ok_all = True
    for part in chunk(sample_posts(cfg)):
        ok, _, err = post_items(cfg["webhook"], part)
        if not ok:
            log(f"Example posts failed: {err}")
            return False
        _sleep(1.2)
    poll = mvp_poll_due({"week": sample_state(cfg)["week"]}, dict(cfg, mvp_poll=True, mvp_day=datetime.now().weekday()),
                        datetime.now().replace(hour=19))
    if poll:
        poll["question"]["text"] = "🧪 Example: " + poll["question"]["text"]
        ok, _, err = post(cfg["webhook"], poll=poll)
        log("Example MVP vote sent." if ok else f"Example MVP vote failed: {err}")
        _sleep(1.2)
    log("Example feed posts sent.")
    st = sample_state(cfg)
    sample_cfg = dict(cfg, goal_level=cfg.get("goal_level") or 40, goal_date=cfg.get("goal_date") or "2026-12-09",
                      goal_raid_count=cfg.get("goal_raid_count") or 10)
    for key, builder, _ in BOARDS:
        embed = builder(st, sample_cfg)
        label = key
        embed["title"] = "🧪 " + embed["title"]
        embed["footer"] = {"text": "Example with made-up names. The real board appears once the app has watched your guild."}
        ok, _, err = post(board_url(cfg), embed=embed, silent=True)
        if not ok:
            log(f"Example {label} failed: {err}")
            ok_all = False
        else:
            log(f"Example {label} sent.")
        _sleep(1.2)
    return ok_all


def dashboard(cfg):
    """Numbers for the app's Home page, from the saved memory. Never fails."""
    try:
        st = load_state()
    except Exception:
        st = {}
    w = st.get("week") or {}
    members = st.get("members") or {}
    try:
        cap = int(cfg.get("max_level") or 60)
    except (TypeError, ValueError):
        cap = 60
    return {
        "members": len(members),
        "at_cap": sum(1 for m in members.values() if m.get("level", 0) >= cap),
        "levels_week": sum(g[0] for g in (w.get("gains") or {}).values()),
        "milestones_week": len(w.get("milestones") or []),
        "waiting": len(st.get("outbox") or []),
        "digest": bool((st.get("boards", {}).get("digest") or {}).get("id")),
        "ladder": bool((st.get("boards", {}).get("ladder") or {}).get("id")),
        "last_check": st.get("last_check"),
        "guild": st.get("guild") or "",
    }


# ------------------------------ more boards ------------------------------
def _stamp(embed):
    embed["timestamp"] = datetime.now(timezone.utc).isoformat()
    return embed


def build_fame(st, cfg):
    """Hall of Fame: every guild first, oldest first."""
    rows = [f for f in st.get("fame", {}).values() if f.get("who")]
    if not rows:
        return _stamp({"title": "🏆 Hall of Fame", "color": 0xF2B84B,
                       "description": "Guild firsts land here: first to the level cap, first mount, first epic, "
                                      "first boss kills, first attunements and maxed professions. Who'll be first?"})
    rows.sort(key=lambda f: (f.get("when") or "", f["title"]))
    lines = [f"**{f['title']}** · {f['who']}" + (f" · *{f['detail']}*" if f.get("detail") else "") for f in rows]
    return _stamp({"title": "🏆 Hall of Fame", "color": 0xF2B84B, "description": _clip(lines, 3900),
                   "footer": {"text": f"{len(rows)} guild firsts so far"}})


def build_attune(st, cfg):
    """Who's ready for which raid, and who holds which key."""
    keys = st.get("keys", {})
    fields = []
    for code, label in ATTUNEMENTS.items():
        names = sorted(w for w, ks in keys.items() if code in ks)
        value = ", ".join(names) if names else "*Nobody yet*"
        fields.append({"name": f"{label} ({len(names)})", "value": value[:1024], "inline": code not in RAID_KEYS})
    desc = ("Updates when people log out or /reload with the addon on. Raids open on 9 December."
            if keys else "Nobody's addon has reported yet. Attunements show up after people log in with the addon.")
    return _stamp({"title": "🔑 Attunements & keys", "color": 0xE25822, "description": desc, "fields": fields})


def build_crafters_board(st, cfg):
    crafters = st.get("crafters", {})
    if not crafters:
        return _stamp({"title": "🧰 Crafters", "color": 0x3CCF8E,
                       "description": "Who crafts what shows up here once an officer opens the guild's professions in game."})
    fields = []
    for prof, rows in sorted(crafters.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:24]:
        line = " · ".join(f"{n} **{s}**" for n, s in rows[:10])
        if len(rows) > 10:
            line += f" · +{len(rows) - 10} more"
        fields.append({"name": f"{prof} ({len(rows)})", "value": line[:1024], "inline": True})
    return _stamp({"title": "🧰 Crafters", "color": 0x3CCF8E, "fields": fields,
                   "description": "Need something made? Whisper the highest skill. In game: /gms → Crafters."})


def build_lfg(st, cfg):
    rows = st.get("lfg", [])
    if not rows:
        return _stamp({"title": "🧭 Looking for group", "color": 0x5AA9FF,
                       "description": "Nobody's looking right now. In game, open /gms → Groups and tick what you'd like "
                                      "to do. It shows up here for an hour and a half. No pings, ever."})
    lines = []
    for r in sorted(rows, key=lambda r: -r["ts"])[:20]:
        wants = ", ".join(LFG_NAMES.get(w, w) for w in r["wants"]) or "anything"
        lines.append(f"**{r['name']}** · {r['level']} {class_name(r['cls'])} · *{r['role']}* → {wants} · <t:{r['ts']}:R>")
    return _stamp({"title": "🧭 Looking for group", "color": 0x5AA9FF, "description": _clip(lines, 3900),
                   "footer": {"text": "Want in? Whisper them in game."}})


def build_fallen(st, cfg):
    rows = st.get("fallen", [])
    if not rows:
        return _stamp({"title": "🪦 Fallen Heroes", "color": 0x4B5563,
                       "description": "No one has fallen. Long may it last."})
    lines = [f"**{r['name']}**" + (f", level {r['level']}" if str(r["level"]).isdigit() else "") +
             f" · {r['zone']} · <t:{r['ts']}:D>" for r in reversed(rows)]
    return _stamp({"title": "🪦 Fallen Heroes", "color": 0x4B5563, "description": _clip(lines, 3900),
                   "footer": {"text": f"{len(rows)} fallen. Remember them."}})


# The boards channel, top to bottom. (key, builder, setting that switches it on)
BOARDS = [("ladder", lambda st, cfg: build_ladder(st, cfg), "ladder_enabled"),
          ("fame", build_fame, "fame_enabled"),
          ("attune", build_attune, "attune_enabled"),
          ("crafters", build_crafters_board, "crafters_enabled"),
          ("lfg", build_lfg, "lfg_enabled"),
          ("fallen", build_fallen, "hardcore"),
          ("digest", build_digest, "digest_enabled")]


def push_board(st, cfg, key, force=False):
    builder = dict((k, b) for k, b, _ in BOARDS)[key]
    embed = builder(st, cfg)
    if embed is None:
        return True, "unchanged"
    return _push_board(st, key, board_url(cfg), embed, force)


def delete_message(url, message_id):
    base, _, query = url.partition("?")
    target = f"{base}/messages/{message_id}"
    thread = [q for q in query.split("&") if q.startswith("thread_id=")]
    if thread:
        target = _with_query(target, thread[0])
    return _request("DELETE", target)[0]


def tidy_boards(st, cfg, log):
    """Delete every board message this app made, then post them again in the right order.
    Use it after changing which boards are on, or if the boards channel got out of order."""
    url = board_url(cfg)
    for key, _, _ in BOARDS:
        d = st.setdefault("boards", {}).get(key) or {}
        if d.get("id") and d.get("hook") == hook_key(url):
            delete_message(url, d["id"])
            _sleep(0.6)
        st["boards"][key] = {}
    ok_all = True
    for key, _, flag in BOARDS:
        if not cfg.get(flag, key != "fallen"):
            continue
        ok, what = push_board(st, cfg, key, force=True)
        log(f"{key.title()} board {what}." if ok else f"{key.title()} board problem: {what}")
        ok_all = ok_all and ok
        _sleep(1.0)
    return ok_all


# ------------------------------ the weekly MVP vote ------------------------------
def mvp_candidates(w):
    """Up to five people with a reason each, from this week's numbers."""
    picks, seen = [], set()

    def add(name, why):
        if name and name not in seen and len(picks) < 5:
            seen.add(name)
            picks.append(f"{name} · {why}"[:55])
    for n, (g, lvl) in sorted(w.get("gains", {}).items(), key=lambda kv: -kv[1][0])[:2]:
        add(n, f"+{g} levels")
    for cat, unit in (("boss", "boss kills"), ("loot", "rare+ drops"), ("quests", "quests")):
        top = sorted(w.get(cat, {}).items(), key=lambda kv: -kv[1])[:2]
        for n, c in top:
            add(n, f"{c} {unit}")
    for m in reversed(w.get("milestones", [])):
        add(m["name"], f"hit level {m['level']}")
    return picks


def mvp_poll_due(st, cfg, now):
    """The poll goes out once a week, on the chosen day from 18:00."""
    if not cfg.get("mvp_poll", True):
        return None
    w = st.get("week") or {}
    if w.get("poll") or now.weekday() != int(cfg.get("mvp_day", 4)) or now.hour < 18:
        return None
    picks = mvp_candidates(w)
    if len(picks) < 2:
        return None
    return {"question": {"text": "🏅 Who's this week's guild MVP?"},
            "answers": [{"poll_media": {"text": p}} for p in picks],
            "duration": 48, "allow_multiselect": False}


# ------------------------------ guild goals ------------------------------
def progress_bar(have, need, width=10):
    filled = min(width, round(width * have / need)) if need else 0
    return "🟩" * filled + "⬛" * (width - filled)


def goal_date(cfg):
    try:
        return datetime.strptime(str(cfg.get("goal_date", "")).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def guild_goals(st, cfg, members=None):
    """The goals the officers set: [{title, have, need, text}]. Members = [(name, level, class)] (active only)."""
    if members is None:
        members = [(short(n), r.get("level", 0), r.get("class", "")) for n, r in st.get("members", {}).items()
                   if r.get("off", 0) <= 30]
    out = []
    try:
        lvl = int(cfg.get("goal_level") or 0)
    except (TypeError, ValueError):
        lvl = 0
    when = goal_date(cfg)
    by = f" by {when.strftime('%b')} {when.day}" if when else ""
    left = ""
    if when:
        days = (when - datetime.now().date()).days
        left = f" · {days} day{'s' if days != 1 else ''} left" if days >= 0 else " · deadline passed"
    if lvl > 0 and members:
        have = sum(1 for m in members if m[1] >= lvl)
        behind = sorted((m for m in members if m[1] < lvl), key=lambda m: -m[1])[:4]
        tail = (" · next up: " + ", ".join(f"{m[0]} ({m[1]})" for m in behind)) if behind else " · 🎉 everyone's there!"
        out.append({"title": f"🎯 Goal: everyone to level {lvl}{by}", "have": have, "need": len(members),
                    "text": f"{have}/{len(members)} there{left}{tail}"})
    try:
        cnt = int(cfg.get("goal_raid_count") or 0)
    except (TypeError, ValueError):
        cnt = 0
    raid = cfg.get("goal_raid", "mc")
    if cnt > 0 and raid in ATTUNEMENTS:
        have = sum(1 for ks in st.get("keys", {}).values() if raid in ks)
        out.append({"title": f"🎯 Goal: {cnt} attuned to {ATTUNEMENTS[raid]}{by}", "have": min(have, cnt), "need": cnt,
                    "text": f"{have}/{cnt} attuned{left}"})
    return out


# ------------------------------ the race to the level cap ------------------------------
def build_ladder(st, cfg, rows=15):
    """A board that edits itself: who's highest, who got each milestone first, and the guild's total.
    None when there's nobody to show."""
    members = [(short(n), r.get("level", 0), r.get("class", "")) for n, r in st.get("members", {}).items()
               if r.get("off", 0) <= 30]                   # long-gone members don't clutter the race
    if not members:
        return None
    try:
        cap = int(cfg.get("max_level") or 60)
    except (TypeError, ValueError):
        cap = 60
    members.sort(key=lambda m: (-m[1], m[0].lower()))
    lines = []
    for i, (who, lvl, cls) in enumerate(members[:rows], 1):
        crown = " 👑" if lvl >= cap else ""
        lines.append(f"`{i:>2}.` **{who}** · {lvl} {class_name(cls)}{crown}")
    if len(members) > rows:
        lines.append(f"…and {len(members) - rows} more on the road")

    firsts = []
    for m in sorted(nums(cfg.get("milestones", "")) | {cap}):
        who = st.get("firsts", {}).get(f"level:{m}")
        if who:
            firsts.append(f"{'🏆' if m == cap else '🥇'} {m}: **{who}**")
    total = sum(m[1] for m in members)
    at_cap = sum(1 for m in members if m[1] >= cap)
    goal = cap * len(members)
    filled = round(10 * total / goal) if goal else 0
    bar = "🟩" * filled + "⬛" * (10 - filled)

    fields = [{"name": "🧗 The ladder", "value": "\n".join(lines)[:1024]}]
    if firsts:
        fields.append({"name": "First in the guild", "value": " · ".join(firsts)[:1024]})
    fields.append({"name": "Guild progress: everyone to " + str(cap),
                   "value": f"{bar}\n{total:,} of {goal:,} levels · {at_cap}/{len(members)} at {cap}"})
    for g in guild_goals(st, cfg, members):
        fields.append({"name": g["title"], "value": f"{progress_bar(g['have'], g['need'])}\n{g['text']}"})
    return {
        "title": f"🏁 Race to {cap}",
        "description": "This board updates itself. Climb it!",
        "color": 0xF0B232,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------ the /gms week file ------------------------------
def week_title(st):
    start = datetime.strptime(st["week"]["id"], "%Y-%m-%d")
    return f"Guild week of {start.strftime('%b')} {start.day}"


def week_lines(st):
    w, lines = st["week"], []
    new = ", ".join(f"{n['name']} ({n['cls']} {n['level']})" for n in w["new"][-5:])
    lines.append("New members: " + (new or "nobody yet"))
    gains = sorted(w["gains"].items(), key=lambda kv: -kv[1][0])[:3]
    lines.append("Top level-ups: " + (", ".join(f"{n} +{g} (now {lv})" for n, (g, lv) in gains) or "quiet so far"))
    lines.append("Milestones: " + (", ".join(f"{m['name']} {m['level']}" for m in w["milestones"][-5:]) or "none yet"))
    if w["tiers"]:
        lines.append("Skill tiers: " + ", ".join(f"{t['name']} {t['tier']} {t['prof']}" for t in w["tiers"][-4:]))
    for t, rows in leaderboard(w):
        lines.append(f"{t}: " + ", ".join(f"{n} ({txt})" for n, txt in rows))
    crafters = sorted(st.get("crafters", {}).items(), key=lambda kv: -len(kv[1]))[:6]
    if crafters:
        lines.append("Crafters: " + ", ".join(f"{p} {len(r)}" for p, r in crafters))
    return lines


def lua_str(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ") + '"'


def addon_line(cfg):
    """The one-line tag that tells every member's addon which milestones count."""
    def clean(t):
        return ",".join(str(n) for n in sorted(nums(t)))
    try:
        cap = int(cfg.get("max_level") or 0)
    except (TypeError, ValueError):
        cap = 0
    try:
        goal = int(cfg.get("goal_level") or 0)
    except (TypeError, ValueError):
        goal = 0
    when = goal_date(cfg)
    extra = (f" G={goal}" + (f" D={when:%Y%m%d}" if when else "")) if goal > 0 else ""
    return f"[GMS L={clean(cfg.get('milestones', ''))} C={cap} T={clean(cfg.get('tiers', ''))}{extra}]"


def write_week_file(cfg, st):
    """Drop a small Lua file into the addon folder: the weekly summary for /gms week, and the guild's
    milestone settings, which an officer's addon publishes into Guild Info for everyone."""
    g = str(cfg.get("game_folder", "")).strip()
    if not g:
        return False
    folder = Path(g) / "Interface" / "AddOns" / "GuildMilestones"
    if not folder.is_dir():
        return False
    has_week = bool(st.get("week", {}).get("id"))
    title, lines = (week_title(st), week_lines(st)) if has_week else ("", [])
    line = addon_line(cfg)
    key = hashlib.md5((title + "\n" + "\n".join(lines) + "\n" + line).encode("utf-8")).hexdigest()
    target = folder / "Digest.lua"
    try:
        if f"-- key:{key}" in target.read_text(encoding="utf-8"):
            return True                                   # nothing changed since the last write
    except Exception:
        pass
    m = re.match(r"\[GMS L=([\d,]*) C=(\d+) T=([\d,]*)(?: G=(\d+))?(?: D=(\d+))?\]", line)
    content = ("-- Written by the Guild Milestones companion app. Safe to delete.\n"
               f"-- key:{key}\n"
               "GuildMilestonesConfig = {\n"
               f"    levels = {lua_str(m.group(1))},\n    cap = {m.group(2)},\n    tiers = {lua_str(m.group(3))},\n"
               f"    goal = {m.group(4) or 0},\n    goaldate = {lua_str(m.group(5) or '')},\n}}\n")
    if has_week:
        body = ",\n".join("        " + lua_str(x) for x in lines)
        content += ("GuildMilestonesWeek = {\n"
                    f"    title = {lua_str(title)},\n"
                    f"    asof = {lua_str(time.strftime('%H:%M, %b %d'))},\n"
                    f"    lines = {{\n{body}\n    }},\n}}\n")
    try:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        return True
    except Exception as e:
        log_error(f"couldn't write Digest.lua: {e!r}")
        return False


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
        self.cache, self.outbox, self.fail_streak, self.warned = (0, None), [], 0, set()
        self.pending_boards = {}

    def check(self, force_digest=False):
        """One pass: read file, announce, update digest, save. Returns False if it should retry."""
        try:
            write_week_file(self.cfg, load_state())      # keeps the addon's guild settings current
        except Exception as e:
            log_error(f"addon settings write failed: {e!r}")
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
            # Remember what's waiting to be posted BEFORE posting, so a failure never posts anything twice.
            st["outbox"] = (st.get("outbox") or []) + msgs
            if len(st["outbox"]) > MAX_OUTBOX:
                self.log(f"Too many announcements were waiting, so I dropped the oldest {len(st['outbox']) - MAX_OUTBOX}.")
                st["outbox"] = st["outbox"][-MAX_OUTBOX:]
            save_state(st)
            posted_ok = self._flush_saved(st)
            write_week_file(self.cfg, st)
            self._boards(st, force_digest)
            st["last_check"] = time.time()
            save_state(st)
            self.log(f"Checked {len(snap['members'])} members.")
            return posted_ok

    def _flush_saved(self, st):
        """Post the saved outbox one Discord message at a time, saving after each. False if something's left."""
        sent = 0
        while st["outbox"]:
            part = chunk(st["outbox"])[0]
            ok, _, err = post_items(self.cfg["webhook"], part)
            if not ok:
                self.log(f"Couldn't post to Discord ({err}). {len(st['outbox'])} announcement(s) are saved; I'll try again shortly.")
                return False
            del st["outbox"][:len(part)]
            sent += len(part)
            save_state(st)
            if st["outbox"]:
                _sleep(1.2)
        if sent:
            self.log(f"Posted {sent} announcement(s).")
        return True

    def _boards(self, st, force_digest=False):
        """Update the self-editing messages (and the Friday MVP vote). Runs even when an announcement failed,
        so the digest button always works. Returns the boards that were freshly posted: {key: message info}."""
        fresh = {}
        names = {"ladder": "Race board", "fame": "Hall of Fame", "attune": "Attunements board", "crafters": "Crafters board",
                 "lfg": "Group board", "fallen": "Fallen Heroes board", "digest": "Weekly digest"}
        for key, _, flag in BOARDS:
            on = self.cfg.get(flag, key != "fallen") or (key == "digest" and force_digest)
            if not on:
                continue
            ok, what = push_board(st, self.cfg, key, force=force_digest and key == "digest")
            if what != "unchanged":
                self.log(f"{names[key]} {what}." if ok else f"{names[key]} problem: {what}")
            if ok and what == "posted":
                fresh[key] = st["boards"][key]
        poll = mvp_poll_due(st, self.cfg, datetime.now())
        if poll:
            ok, _, err = post(self.cfg["webhook"], poll=poll)
            if ok:
                st["week"]["poll"] = True
                self.log("Posted this week's MVP vote.")
            else:
                self.log(f"Couldn't post the MVP vote ({err}).")
        return fresh

    def run(self, stop):
        if self.shared:
            return self._run_shared(stop)
        last, last_path, warned, retry_at = 0, "", False, 0.0
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
                    if m != last and time.time() >= retry_at:
                        if self.check():
                            last = m
                        else:
                            last, retry_at = 0, time.time() + RETRY_SECONDS
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
                    "heard": snap.get("heard", [])[-150:], "events": snap.get("events", [])[-100:], "from": self.cfg.get("my_name", "")}
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
        for key, info in self.pending_boards.items():      # boards posted last time, whose save didn't go through
            state.setdefault("boards", {})[key] = info
        new, msgs, notes = process(snap, state, self.cfg, datetime.now())
        new["snap_ts"] = snap["updated"]
        new["last_check"] = time.time()
        msgs = (new.pop("outbox", None) or []) + msgs       # anything this PC still had waiting from solo mode
        self.pending_boards.update(self._boards(new, force_digest))   # remembered in case the save below fails
        ok, res, err = self.store.commit(new, version)      # save memory BEFORE posting, so nothing posts twice
        if not ok:
            self.log(f"Couldn't save to the shared service ({err}). I'll try again.")
            return False
        self.pending_boards = {}
        new["version"] = res["version"]
        for n in notes:
            self.log(n)
        self.outbox += [(t, 0) for t in chunk(msgs)]
        if msgs:
            self.log(f"Posting {len(msgs)} announcement(s)...")
        self._flush()
        write_week_file(self.cfg, new)
        save_state(new)
        self.log(f"Checked {len(snap['members'])} members.")
        return True

    def _flush(self):
        while self.outbox:
            text, tries = self.outbox[0]
            ok, _, err = post_items(self.cfg["webhook"], text)
            if ok:
                self.outbox.pop(0)
                self.fail_streak = 0
                if self.outbox:
                    _sleep(1.2)
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


def _registry_wow_dirs():
    """Where the Battle.net launcher says World of Warcraft is installed (Windows only)."""
    found = []
    try:
        import winreg
    except ImportError:
        return found
    for key in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                r"SOFTWARE\Blizzard Entertainment\World of Warcraft"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                path = winreg.QueryValueEx(k, "InstallPath")[0]
        except OSError:
            continue
        p = Path(path)
        found.append(str(p.parent if p.name.startswith("_") else p))   # InstallPath may point at a _flavor_ folder
    return found


def find_game_folders():
    """Every game-version folder (_retail_, _classic_beta_, ...) that has an Interface folder. WoW: Forever's
    folder name isn't known for sure until launch, so the app lists them all and the officer picks."""
    bases = _registry_wow_dirs()
    for r in filter(None, [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), "C:\\", "D:\\", "E:\\"]):
        bases += [os.path.join(r, "World of Warcraft"), os.path.join(r, "Games", "World of Warcraft")]
    hits = []
    for b in bases:
        hits += [os.path.normpath(h) for h in glob.glob(os.path.join(b, "_*_"))
                 if os.path.isdir(os.path.join(h, "Interface"))]
    return list(dict.fromkeys(hits))


def bundled_addon_dir():
    return RES_DIR / "GuildMilestones"


def _toc_version(folder):
    try:
        for line in (Path(folder) / "GuildMilestones.toc").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("## version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def _addon_fingerprint(folder):
    """A hash of the addon's own files (Digest.lua is left out: the app rewrites it)."""
    h = hashlib.md5()
    try:
        for f in sorted(Path(folder).glob("*")):
            if f.is_file() and f.name != "Digest.lua":
                h.update(f.name.encode())
                h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    except Exception:
        return None
    return h.hexdigest()


def addon_status(game):
    """(version installed in the game or None, version bundled with this app or None).
    If the files differ but the version number is the same, the installed one is reported as '<version>*'."""
    installed_dir = Path(game) / "Interface" / "AddOns" / "GuildMilestones"
    have, new = _toc_version(installed_dir), _toc_version(bundled_addon_dir())
    if have and have == new and _addon_fingerprint(installed_dir) != _addon_fingerprint(bundled_addon_dir()):
        have += "*"
    return have, new


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
UPDATE_FILES = ("engine.py", "milestone_gui.py", "tray.py", "GuildMilestones.pyw", "README.md", "CHANGES.md",
                "HOW TO UPDATE.txt")
UPDATE_DIRS = ("GuildMilestones", "shared", "assets")


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
        if not m:
            return ""
        for line in m.group(1).splitlines():            # the update dialog shows only the one-line headline
            line = line.strip().lstrip("-* ").replace("**", "").replace("`", "").strip()
            if line:
                return line
        return ""
    except Exception:
        return ""


RELEASE_EXE = "GuildMilestones.exe"


def latest_release():
    """(version, download URL of GuildMilestones.exe) from the newest GitHub release, or (None, None)."""
    try:
        data = json.loads(_fetch(f"https://api.github.com/repos/{REPO}/releases/latest").decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:                       # no release published yet
            return None, None
        raise
    tag = str(data.get("tag_name") or "").lstrip("vV")
    url = next((a.get("browser_download_url") for a in data.get("assets", []) if a.get("name") == RELEASE_EXE), None)
    return (tag or None), url


def apply_exe_update():
    """Download the new GuildMilestones.exe next to this one, then swap them once this app has closed.
    Returns (ok, message). The caller quits right after; a tiny helper script restarts the app."""
    try:
        latest, url = latest_release()
        if not url:
            return False, "The newest GitHub release has no GuildMilestones.exe yet. Try again in a few minutes."
        data = _fetch(url, timeout=120)
        if len(data) < 1_000_000 or not data.startswith(b"MZ"):
            return False, "The download didn't look like the app, so I left everything as it was."
        exe = Path(sys.executable)
        new = exe.with_name(exe.stem + ".new.exe")
        new.write_bytes(data)
        bat = DATA_DIR / "finish_update.bat"
        bat.write_text(
            "@echo off\r\n"
            "set tries=0\r\n"
            ":wait\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            f'move /y "{new}" "{exe}" >nul 2>&1\r\n'
            "if errorlevel 1 (set /a tries+=1 & if %tries% lss 30 goto wait)\r\n"
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n', encoding="utf-8")
        import subprocess
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000)      # no console window
        return True, f"Update to v{latest} downloaded."
    except PermissionError:
        return False, "Windows wouldn't let me change the app's folder. Move the app to somewhere like Documents and try again."
    except Exception as e:
        return False, f"Couldn't update: {e}"


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command(tray=True):
    """How Windows should start this app (the .exe, or pythonw with the .pyw)."""
    if FROZEN:
        cmd = f'"{sys.executable}"'
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        cmd = f'"{pyw if pyw.exists() else sys.executable}" "{APP_DIR / 'GuildMilestones.pyw'}"'
    return cmd + (" --tray" if tray else "")


def start_with_windows_on():
    """True if Windows is set to start the app (so the switch shows the truth)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "GuildMilestones")
        return True
    except Exception:
        return False


def download_exe(folder):
    """Fetch GuildMilestones.exe from the newest GitHub release into folder. Returns (ok, path or problem)."""
    try:
        latest, url = latest_release()
        if not url:
            return False, "There's no GuildMilestones.exe on GitHub yet."
        data = _fetch(url, timeout=120)
        if len(data) < 1_000_000 or not data.startswith(b"MZ"):
            return False, "The download didn't look like the app, so I didn't save it."
        target = Path(folder) / RELEASE_EXE
        tmp = target.with_suffix(".download")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return True, str(target)
    except PermissionError:
        return False, "Windows wouldn't let me save into this folder. Move the app to Documents and try again."
    except Exception as e:
        return False, f"Couldn't download it: {e}"


def make_shortcut(target, name="Guild Milestones"):
    """Put a desktop shortcut to target. Returns '' or a problem."""
    try:
        import subprocess
        target = Path(target)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\\"
              f"{name}.lnk');$s.TargetPath='{target}';$s.WorkingDirectory='{target.parent}';"
              f"$s.IconLocation='{target},0';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        return "" if r.returncode == 0 else (r.stderr.strip()[:200] or "PowerShell refused.")
    except Exception as e:
        return f"Couldn't make the shortcut: {e}"


def set_start_with_windows(on):
    """Add or remove the app from Windows startup (current user only). Returns '' or a problem."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "GuildMilestones", 0, winreg.REG_SZ, launch_command(tray=True))
            else:
                try:
                    winreg.DeleteValue(k, "GuildMilestones")
                except FileNotFoundError:
                    pass
        return ""
    except Exception as e:
        return f"Couldn't change Windows startup: {e}"


def update_available():
    """(latest version, True if it is newer than this one)"""
    latest, _ = latest_version()
    return latest, bool(latest) and _ver(latest) > _ver(APP_VERSION)


def check_report():
    """Plain-English result of an update check, for the Setup tab."""
    try:
        latest = latest_release()[0] if FROZEN else latest_version()[0]     # the .exe updates from Releases
    except Exception as e:
        log_error(f"update check failed: {e!r}")
        return {"ok": False, "newer": False, "latest": None, "text": f"Couldn't reach GitHub ({e})."}
    if not latest:
        return {"ok": False, "newer": False, "latest": None,
                "text": "GitHub answered, but I couldn't find a version number in engine.py there."}
    newer = _ver(latest) > _ver(APP_VERSION)
    if newer:
        text = f"GitHub has v{latest}; this app is v{APP_VERSION}. An update is available."
    elif _ver(latest) < _ver(APP_VERSION):
        text = (f"This copy (v{APP_VERSION}) is newer than the one on GitHub (v{latest}). That's normal until "
                "you upload it. Your friends' apps will offer the update once engine.py on GitHub says "
                f"v{APP_VERSION}.")
    else:
        text = f"You're up to date (v{APP_VERSION})."
    return {"ok": True, "newer": newer, "latest": latest, "text": text}


def apply_update(zip_bytes=None):
    """Download the repo as a zip, check the new code compiles, then copy it over this app.
    Returns (ok, message). The caller restarts the app afterwards."""
    if FROZEN:
        return apply_exe_update()
    try:
        data = zip_bytes or _fetch(f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip", timeout=60)
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                root = z.namelist()[0].split("/")[0]
                for name in z.namelist():
                    rel = name[len(root) + 1:]
                    if not rel or name.endswith("/"):
                        continue
                    if ".." in rel.split("/") or not (rel in UPDATE_FILES or rel.split("/")[0] in UPDATE_DIRS
                                                     or ("/" not in rel and rel.endswith(".py"))):
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
            for f in sorted(set(UPDATE_FILES) | {p.name for p in stage.glob("*.py")}):
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
