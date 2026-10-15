"""Guild Milestones engine: reads the addon's file, decides what to announce, talks to Discord.
No window code in here, so it can be tested on its own."""
import copy, glob, hashlib, io, uuid, json, os, re, shutil, sys, tempfile, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_VERSION = "0.9.0"
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
MAX_OUTBOX = 60           # announcements kept waiting when Discord can't be reached
MAX_WELCOMES = 5          # more brand-new names than this at once = probably a roster hiccup, so stay quiet
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIER_NAMES = {75: "Journeyman", 150: "Expert", 225: "Artisan", 300: "Master"}
CLASS_NAMES = {"DEATHKNIGHT": "Death Knight", "DEMONHUNTER": "Demon Hunter"}
CLASS_COLORS = {"DEATHKNIGHT": 0xC41E3A, "DEMONHUNTER": 0xA330C9, "DRUID": 0xFF7C0A, "EVOKER": 0x33937F,
                "HUNTER": 0xAAD372, "MAGE": 0x3FC7EB, "MONK": 0x00FF98, "PALADIN": 0xF48CBA, "PRIEST": 0xFFFFFF,
                "ROGUE": 0xFFF468, "SHAMAN": 0x0070DD, "WARLOCK": 0x8788EE, "WARRIOR": 0xC69B6D}
DEFAULT_COLOR = 0x5865F2

DEFAULTS = {
    "webhook": "", "digest_webhook": "", "game_folder": "", "savedvars": "",
    "auto_start": False, "auto_update_addon": True,
    "shared_on": False, "shared_url": "", "shared_token": "", "my_name": "", "device_id": "",
    "announce_levels": True, "announce_firsts": True, "announce_tiers": True,
    "welcome_new": True, "welcome_back": True, "digest_enabled": True, "ladder_enabled": True, "skip_shouted": False,
    "event_loot": True, "event_boss": True, "event_death": False, "event_quest": False, "loot_min_quality": 3,
    "milestones": "10, 20, 30, 40, 50, 60", "max_level": 60, "tiers": "75, 150, 225, 300",
    "week_start": 0,
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
    m = re.search(r'\["updated"\]\s*=\s*(\d+)', text)
    updated = int(m.group(1)) if m else int(Path(path).stat().st_mtime)
    g = re.search(r'\["guild"\]\s*=\s*"((?:[^"\\\n]|\\.)*)"', text)
    return {"members": members, "profs": profs, "heard": heard, "events": events, "updated": updated,
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
          "week": new_week(""), "digest": {}, "ladder": {}, "outbox": []}
    st.update(_read_json(STATE_FILE) or {})
    for board in ("digest", "ladder"):                 # older versions stored the full webhook URL here
        d = st.get(board) or {}
        if d.get("url"):
            d["hook"] = hook_key(d.pop("url"))
    return st


def save_state(st):
    _write_json(STATE_FILE, st)


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
        st["week"], st["digest"] = new_week(wid), {}
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
        mine[p["prof"]] = p["skill"]

    if snap["profs"]:
        crafters = {}
        for p in snap["profs"]:
            crafters.setdefault(p["prof"], []).append([short(p["name"]), p["skill"]])
        st["crafters"] = {k: sorted(v, key=lambda r: -r[1]) for k, v in crafters.items()}

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
        if kind == "I":
            try:
                if int(ev["b"].split(":")[0]) >= 3:
                    bump("loot", who)
            except ValueError:
                pass
        elif kind == "B":
            bump("boss", who)
        elif kind == "Q":
            bump("quests", who)
        elif kind == "D":
            bump("deaths", who)
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
        items.append({"text": f"⚔️ **{boss}** is down! Defeated by {crew}{size}.", "color": k["color"]})
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

    for prof, rows in sorted(st["crafters"].items(), key=lambda kv: -len(kv[1]))[:9]:
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


def post(url, content=None, embed=None, wait=False, embeds=None, silent=False):
    """Returns (ok, message_id, error)."""
    if content:
        payload = {"content": content}
    else:
        payload = {"embeds": embeds if embeds is not None else [embed]}
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
    d = st.setdefault(key, {})
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
        st[key] = {"id": mid, "hook": hook_key(url), "hash": h}
        return True, "posted"
    return False, err or "no message id came back"


def board_url(cfg):
    return cfg["digest_webhook"].strip() or cfg["webhook"].strip()


def push_digest(st, cfg, force=False):
    return _push_board(st, "digest", board_url(cfg), build_digest(st, cfg), force)


def push_ladder(st, cfg, force=False):
    embed = build_ladder(st, cfg)
    if embed is None:
        return True, "unchanged"
    return _push_board(st, "ladder", board_url(cfg), embed, force)


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
    st["crafters"] = {"Tailoring": [["Sylvanas", 225], ["Jaina", 150]], "Blacksmithing": [["Varian", 210]]}
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
    log("Example feed posts sent.")
    st = sample_state(cfg)
    for label, embed in (("digest", build_digest(st, cfg)), ("race board", build_ladder(st, cfg))):
        embed["title"] = "🧪 " + embed["title"]
        embed["description"] = "Example with made-up names. The real one appears once the app has watched your guild."
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
        "digest": bool((st.get("digest") or {}).get("id")),
        "ladder": bool((st.get("ladder") or {}).get("id")),
        "last_check": st.get("last_check"),
        "guild": st.get("guild") or "",
    }


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
    fields.append({"name": "Guild goal: everyone to " + str(cap),
                   "value": f"{bar}\n{total:,} of {goal:,} levels · {at_cap}/{len(members)} at {cap}"})
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
    return f"[GMS L={clean(cfg.get('milestones', ''))} C={cap} T={clean(cfg.get('tiers', ''))}]"


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
    m = re.match(r"\[GMS L=([\d,]*) C=(\d+) T=([\d,]*)\]", line)
    content = ("-- Written by the Guild Milestones companion app. Safe to delete.\n"
               f"-- key:{key}\n"
               "GuildMilestonesConfig = {\n"
               f"    levels = {lua_str(m.group(1))},\n    cap = {m.group(2)},\n    tiers = {lua_str(m.group(3))},\n}}\n")
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
        self.cache, self.outbox, self.fail_streak, self.pending_digest, self.warned = (0, None), [], 0, None, set()
        self.pending_ladder = None

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
        """Update the self-editing messages. Runs even when an announcement failed, so the digest button works."""
        if self.cfg["digest_enabled"] or force_digest:
            ok, what = push_digest(st, self.cfg, force=force_digest)
            if what != "unchanged":
                self.log(f"Weekly digest {what}." if ok else f"Digest problem: {what}")
        if self.cfg.get("ladder_enabled", True):
            ok, what = push_ladder(st, self.cfg)
            if what != "unchanged":
                self.log(f"Race board {what}." if ok else f"Race board problem: {what}")

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
        if self.pending_digest:
            state["digest"] = self.pending_digest
        if self.pending_ladder:
            state["ladder"] = self.pending_ladder
        new, msgs, notes = process(snap, state, self.cfg, datetime.now())
        new["snap_ts"] = snap["updated"]
        new["last_check"] = time.time()
        msgs = (new.pop("outbox", None) or []) + msgs       # anything this PC still had waiting from solo mode
        if self.cfg["digest_enabled"] or force_digest:
            ok, what = push_digest(new, self.cfg, force=force_digest)
            if what != "unchanged":
                self.log(f"Weekly digest {what}." if ok else f"Digest problem: {what}")
            if ok and what == "posted":
                self.pending_digest = new["digest"]         # remembered in case the save below fails
        if self.cfg.get("ladder_enabled", True):
            ok, what = push_ladder(new, self.cfg)
            if what != "unchanged":
                self.log(f"Race board {what}." if ok else f"Race board problem: {what}")
            if ok and what == "posted":
                self.pending_ladder = new["ladder"]
        ok, res, err = self.store.commit(new, version)      # save memory BEFORE posting, so nothing posts twice
        if not ok:
            self.log(f"Couldn't save to the shared service ({err}). I'll try again.")
            return False
        self.pending_digest = self.pending_ladder = None
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
    return Path(getattr(sys, "_MEIPASS", APP_DIR)) / "GuildMilestones"


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
        if not m:
            return ""
        for line in m.group(1).splitlines():            # the update dialog shows only the one-line headline
            line = line.strip().lstrip("-* ").replace("**", "").replace("`", "").strip()
            if line:
                return line
        return ""
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
