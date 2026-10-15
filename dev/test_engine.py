"""Tests for engine.py with a fake Discord. Never touches your real settings or the internet.
Run:  python dev/test_engine.py"""
import json, os, sys, tempfile, urllib.error, io
from datetime import datetime
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="gms-test-")
os.environ["APPDATA"] = TMP                       # settings and state go to a throwaway folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as E

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {name}  {extra}")


# ---------------------------------------------------------------- fake Discord
class FakeDiscord:
    def __init__(self):
        self.calls, self.fail_after, self.next_id, self.script = [], None, 100, []

    def __call__(self, method, url, payload=None, timeout=15, retries=3):
        self.calls.append((method, url, payload))
        if self.script:
            return self.script.pop(0)
        if self.fail_after is not None and len([c for c in self.calls if c[0] == "POST"]) > self.fail_after:
            return 0, None, "network down"
        self.next_id += 1
        return 200, {"id": str(self.next_id)}, ""

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


fake = FakeDiscord()
E._request = fake
E._sleep = lambda s: None
E.item_lookup = lambda i: {}
WEBHOOK = "https://discord.com/api/webhooks/1/SECRET-TOKEN"


def cfg(**kw):
    c = dict(E.DEFAULTS, webhook=WEBHOOK, game_folder="", savedvars="", device_id="t", my_name="T")
    c.update(kw)
    return c


def snap(members, events=(), guild="Friends", profs=()):
    return {"members": [dict(name=n, level=l, cls=c, rank=1, off=o) for n, l, c, o in members],
            "profs": list(profs), "heard": [], "events": list(events), "updated": 1, "guild": guild}


NOW = datetime(2026, 11, 10, 20, 0)

# ---------------------------------------------------------------- process()
st0 = E.load_state()
st, msgs, notes = E.process(snap([("Thrall-R", 10, "SHAMAN", 0), ("Jaina-R", 12, "MAGE", 40)]), st0, cfg(), NOW)
check("first run is quiet", msgs == [] and st["initialized"])
check("guild remembered", st.get("guild") == "Friends")

st2, msgs, notes = E.process(snap([("Thrall-R", 10, "SHAMAN", 0), ("Jaina-R", 12, "MAGE", 0)]), st, cfg(), NOW)
check("welcome back after a long break", any("Welcome back, **Jaina**" in m["text"] for m in msgs), msgs)
check("welcome back is quiet", all(m.get("silent") for m in msgs if "Welcome back" in m["text"]))
check("welcome back in the week", st2["week"]["back"] and st2["week"]["back"][0]["days"] == 40)
_, msgs, _ = E.process(snap([("Thrall-R", 10, "SHAMAN", 0), ("Jaina-R", 12, "MAGE", 0)]), st2, cfg(), NOW)
check("welcome back only once", not any("Welcome back" in m["text"] for m in msgs))

_, msgs, notes = E.process(snap([("Alt-R", 5, "ROGUE", 0)], guild="Other Guild"), st2, cfg(), NOW)
check("snapshot from another guild skipped", msgs == [] and any("another guild" in n for n in notes), notes)

st3, msgs, _ = E.process(snap([("Thrall-R", 20, "SHAMAN", 0), ("Jaina-R", 12, "MAGE", 0)]), st2, cfg(), NOW)
check("level milestone announced, not silent", any("Thrall" in m["text"] and not m.get("silent") for m in msgs), msgs)
check("skip_shouted is off by default", E.DEFAULTS["skip_shouted"] is False)

# ---------------------------------------------------------------- bosses: one card per kill
st3["events_seen"] = []
ev = [{"kind": "B", "name": n, "ts": 1000 + i, "a": "Onyxia", "b": "10", "c": ""} for i, n in enumerate(["Thrall", "Jaina", "Bob"])]
items = E.event_items(ev, st3, cfg(), {})
boss = [i for i in items if "Onyxia" in i["text"]]
check("one boss card for three reporters", len(boss) == 1, items)
check("boss card names everyone", boss and all(n in boss[0]["text"] for n in ("Thrall", "Jaina", "Bob")), boss)
check("everyone gets a boss kill on the board", st3["week"]["boss"] == {"Thrall": 1, "Jaina": 1, "Bob": 1}, st3["week"]["boss"])
ev2 = [{"kind": "B", "name": "Late", "ts": 1300, "a": "Onyxia", "b": "10", "c": ""}]
check("late report of the same kill makes no new card", not [i for i in E.event_items(ev2, st3, cfg(), {}) if "Onyxia" in i["text"]])
ev3 = [{"kind": "B", "name": "Thrall", "ts": 1000 + 7 * 86400, "a": "Onyxia", "b": "10", "c": ""}]
check("next week's kill gets a card", [i for i in E.event_items(ev3, st3, cfg(), {}) if "Onyxia" in i["text"]])

ev4 = [{"kind": "D", "name": "Jaina", "ts": 2000, "a": "Westfall", "b": "", "c": ""},
       {"kind": "Q", "name": "Jaina", "ts": 2001, "a": "The Defias", "b": "", "c": ""},
       {"kind": "I", "name": "Jaina", "ts": 2002, "a": "123", "b": "4:60", "c": "Epic Sword"}]
items = E.event_items(ev4, st3, cfg(event_death=True, event_quest=True), {})
check("deaths and quests counted for awards", st3["week"]["deaths"] == {"Jaina": 1} and st3["week"]["quests"] == {"Jaina": 1})
check("epic loot pings, deaths don't", [i.get("silent") for i in items] == [True, True, None, False], [i.get("silent") for i in items])
check("first epic is a guild first", any("Guild first" in i["text"] and "Epic Sword" in i["text"] for i in items))
titles = [t for t, _ in E.leaderboard(st3["week"])]
check("awards include Darwin Award and Quest Machine", any("Darwin" in t for t in titles) and any("Quest" in t for t in titles), titles)

# ---------------------------------------------------------------- chunking keeps quiet and loud apart
parts = E.chunk([{"text": "a"}, {"text": "b", "silent": True}, {"text": "c", "silent": True}, {"text": "d"}])
check("quiet and loud cards are posted separately", [len(p) for p in parts] == [1, 2, 1], [len(p) for p in parts])

# ---------------------------------------------------------------- digest + race board never store the webhook URL
st4 = E.load_state()
st4.update(st3)
ok, what = E.push_digest(st4, cfg())
check("digest posted", ok and what == "posted", what)
check("digest stores no webhook URL", "SECRET" not in json.dumps(st4), st4.get("digest"))
ok, what = E.push_ladder(st4, cfg())
check("race board posted", ok and what == "posted", what)
lad = E.build_ladder(st4, cfg())
check("race board lists the leader first", lad and "**Thrall** · 20" in lad["fields"][0]["value"].split("\n")[0], lad and lad["fields"][0]["value"])
check("race board shows the guild goal", lad and "levels" in lad["fields"][-1]["value"])
check("race board unchanged = no request", E.push_ladder(st4, cfg()) == (True, "unchanged"))
check("board posts are quiet", fake.posts()[-1][2].get("flags") == E.SILENT)

# old state with a URL is converted on load
E.save_state({"digest": {"id": "5", "url": WEBHOOK, "hash": "x"}})
old = E.load_state()
check("old state's URL converted to a fingerprint", "url" not in old["boards"]["digest"]
      and old["boards"]["digest"]["hook"] == E.hook_key(WEBHOOK) and "digest" not in old)

# ---------------------------------------------------------------- edit keeps thread_id
fake.calls.clear()
E.edit(WEBHOOK + "?thread_id=777", "55", {"title": "x"})
check("edit keeps thread_id", fake.calls[0][1].endswith("/messages/55?thread_id=777"), fake.calls[0][1])

# ---------------------------------------------------------------- 429: wait and retry
real_request = E.__dict__.get("_request")
import importlib
calls = {"n": 0}
waits = []


class FakeResp:
    status = 200
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=15):
    calls["n"] += 1
    if calls["n"] == 1:
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"retry_after": 1.5, "message": "slow"}'))
    return FakeResp(b'{"id": "9"}')


E2 = importlib.reload(E)                          # a clean copy with the real _request
E2._sleep = waits.append
E2.urllib.request.urlopen = fake_urlopen
status, body, err = E2._request("POST", WEBHOOK, {"content": "x"})
check("429 waited out and retried", status == 200 and waits == [1.5] and calls["n"] == 2, (status, waits, calls))


def gone(req, timeout=15):
    raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"message": "Unknown Webhook", "code": 10015}'))


E2.urllib.request.urlopen = gone
status, _, err = E2._request("POST", WEBHOOK, {"content": "x"})
check("deleted webhook explained", status == 404 and "Setup tab" in err, err)
E = E2
E._request = fake
E._sleep = lambda s: None
E.item_lookup = lambda i: {}

# ---------------------------------------------------------------- Engine.check: partial failure, no duplicates
game = Path(TMP) / "game" / "_classic_beta_"
sv = game / "WTF" / "Account" / "ME" / "SavedVariables"
sv.mkdir(parents=True)
(game / "Interface" / "AddOns").mkdir(parents=True)


def write_sv(levels):
    rows = ",\n".join(f'"{n}-R|{l}|WARRIOR|1|0"' for n, l in levels)
    (sv / "GuildMilestones.lua").write_text(
        'GuildMilestonesDB = {\n["guild"] = "Friends",\n["members"] = {\n' + rows + '\n},\n["updated"] = 5,\n}\n',
        encoding="utf-8")


E.save_state({})
os.remove(E.STATE_FILE)
write_sv([(f"P{i}", 9) for i in range(12)])
c = cfg(game_folder=str(game), welcome_new=True)
logs = []
eng = E.Engine(c, logs.append)
eng.check()                                       # first run: baseline
write_sv([(f"P{i}", 10) for i in range(12)])      # twelve level-10 milestones at once = 2 posts
fake.calls.clear()
fake.fail_after = 1                               # first post works, second fails
ok = eng.check()
first_round = [c for c in fake.posts() if "embeds" in (c[2] or {}) and "Guild Weekly" not in json.dumps(c[2])]
check("check reports the failure", ok is False)
check("digest still tried after a failed post", any("Guild Weekly" in json.dumps(c[2]) for c in fake.calls), logs[-5:])
saved = E.load_state()
check("unsent announcements are saved", len(saved["outbox"]) == 4, len(saved["outbox"]))
fake.fail_after = None
fake.calls.clear()
eng.check()
again = [c for c in fake.posts() if "Guild Weekly" not in json.dumps(c[2]) and "Race to" not in json.dumps(c[2])]
texts = json.dumps([c[2] for c in again])
check("retry posts only what was left", len(again) == 1 and "**P8**" in texts and "**P11**" in texts
      and "**P3**" not in texts, texts[:300])
check("outbox empty afterwards", E.load_state()["outbox"] == [])
check("state file has no webhook", "SECRET" not in E.STATE_FILE.read_text(encoding="utf-8"))

# ---------------------------------------------------------------- settings: migration and safe writes
E.CONFIG_FILE.write_text(json.dumps({"webhook": WEBHOOK, "skip_shouted": True}), encoding="utf-8")
c2 = E.load_config()
check("skip_shouted switched off once for old settings", c2["skip_shouted"] is False and c2["cfg_rev"] == E.CONFIG_REV)
c2["skip_shouted"] = True
E.save_config(c2)
check("officer can switch it back on", E.load_config()["skip_shouted"] is True)
E.CONFIG_FILE.write_text("{ broken", encoding="utf-8")
c3 = E.load_config()
damaged = list(Path(E.DATA_DIR).glob("settings.damaged-*.json"))
check("damaged settings kept aside", damaged and c3["webhook"] == "", damaged)

# ---------------------------------------------------------------- parse_file reads the guild
p = sv / "GuildMilestones.lua"
check("parse_file reads guild", E.parse_file(p)["guild"] == "Friends")

# ---------------------------------------------------------------- webhook check, examples, update text, dashboard
check("good webhook accepted", E.webhook_problem(WEBHOOK) == "")
check("thread webhook accepted", E.webhook_problem(WEBHOOK + "?thread_id=5") == "")
check("random link refused", "isn't a Discord link" in E.webhook_problem("https://example.com/x"))
check("Discord channel link refused", "not a webhook" in E.webhook_problem("https://discord.com/channels/1/2"))
check("empty boards webhook is fine", E.webhook_problem("", required=False) == "")
fake.calls.clear()
logs = []
ok = E.send_samples(cfg(), logs.append)
bodies = json.dumps([c[2] for c in fake.posts()])
check("examples sent", ok and len(fake.posts()) >= 4, logs)
check("examples cover loot, boss, digest and race board",
      all(w in bodies for w in ("Thunderfury", "Onyxia", "Guild Weekly", "Race to")), bodies[:200])
E.latest_version = lambda: ("0.8.1", "raw")
check("local copy newer than GitHub explained", "newer than the one on GitHub" in E.check_report()["text"])
E.latest_version = lambda: (E.APP_VERSION, "raw")
check("same version says up to date", "up to date" in E.check_report()["text"])
d = E.dashboard(cfg())
check("dashboard never fails", isinstance(d, dict) and "members" in d)

# ---------------------------------------------------------------- v0.11: firsts, mounts, attunements, boards
import copy as _copy
base = E.load_state()
base.update({"initialized": True, "events_seen": [], "guild": "Friends",
             "members": {"Ann-R": {"level": 59, "class": "MAGE", "first_seen": "2026-11-04", "off": 0},
                         "Bob-R": {"level": 30, "class": "WARRIOR", "first_seen": "2026-11-04", "off": 0}}})
snap5 = snap([("Ann-R", 60, "MAGE", 0), ("Bob-R", 30, "WARRIOR", 0)],
             events=[{"kind": "M", "name": "Bob", "ts": 1800000000, "a": "mount", "b": "60", "c": ""},
                     {"kind": "M", "name": "Bob", "ts": 1800000001, "a": "mount", "b": "60", "c": ""},
                     {"kind": "B", "name": "Ann", "ts": 1800000002, "a": "Onyxia", "b": "10", "c": ""}])
snap5["keys"] = {"Ann": ["ony"], "Bob": []}
st5, msgs, _ = E.process(snap5, base, cfg(), NOW)
texts = "\n".join(m["text"] for m in msgs)
check("cap recap card posted", any(m.get("title", "").startswith("🏁 Ann") and m.get("fields") for m in msgs), texts)
check("first to the cap in the Hall of Fame", st5["fame"]["cap"]["who"] == "Ann")
check("first mount celebrated once", texts.count("first mount") == 1 and "First in the guild" in texts, texts)
check("first boss kill marked", "Guild first kill" in texts)
check("keys seen for the first time are not announced", "attuned" not in texts and st5["fame"]["attune:ony"]["who"] == "")
snap6 = _copy.deepcopy(snap5)
snap6["events"] = []
snap6["keys"] = {"Ann": ["ony", "mc"], "Bob": ["ony"]}
st6, msgs, _ = E.process(snap6, st5, cfg(), NOW)
texts = "\n".join(m["text"] for m in msgs)
check("first MC attunement is a guild first", "First attuned to 🔥 Molten Core" in texts and "**Ann**" in texts, texts)
check("Onyxia isn't 'first' (Ann had it before we started)", "Bob** is attuned" in texts and "First attuned to 🐉" not in texts, texts)
fame = E.build_fame(st6, cfg())
check("Hall of Fame lists firsts", "First to level 60" in fame["description"] and "First mount" in fame["description"])
att = E.build_attune(st6, cfg())
check("attunement board lists names", any("Molten Core (1)" in f["name"] and "Ann" in f["value"] for f in att["fields"]))
g = E.guild_goals(st6, cfg(goal_level=40, goal_date="2026-12-09", goal_raid="mc", goal_raid_count=5))
check("two goals with progress", len(g) == 2 and g[0]["have"] == 1 and g[0]["need"] == 2 and g[1]["text"].startswith("1/5"), g)
lad = E.build_ladder(st6, cfg(goal_level=40))
check("race board shows the goal", any(f["name"].startswith("🎯 Goal") for f in lad["fields"]))
check("Guild Info tag carries the goal", E.addon_line(cfg(goal_level=40, goal_date="2026-12-09")).endswith("G=40 D=20261209]"))

# hardcore: deaths become a farewell and go on the wall
st7 = _copy.deepcopy(st6)
items = E.event_items([{"kind": "D", "name": "Bob", "ts": 1800000100, "a": "Westfall", "b": "31", "c": ""}], st7,
                      cfg(hardcore=True), {})
check("hardcore farewell post", items and "has fallen" in items[0]["text"] and not items[0].get("silent"), items)
check("fallen wall", "Bob" in E.build_fallen(st7, cfg())["description"])

# looking for group: fresh notes only
snap8 = _copy.deepcopy(snap6)
snap8["keys"], snap8["updated"] = {}, 1800001000
snap8["lfg"] = [{"name": "Bob", "level": 30, "cls": "WARRIOR", "role": "Tank", "wants": ["sm", "rfk"], "ts": 1800000900},
                {"name": "Old", "level": 20, "cls": "MAGE", "role": "DPS", "wants": ["dm"], "ts": 1790000000}]
st8, _, _ = E.process(snap8, st6, cfg(), NOW)
lfg = E.build_lfg(st8, cfg())["description"]
check("group board shows fresh notes only", "Scarlet Monastery" in lfg and "Old" not in lfg, lfg)

# the MVP vote
from datetime import datetime as _dt
w = {"gains": {"Ann": [5, 60], "Bob": [2, 30]}, "boss": {"Ann": 3}, "loot": {"Cid": 2}, "quests": {}, "milestones": []}
picks = E.mvp_candidates(w)
check("MVP candidates are unique", len(picks) == 3 and picks[0].startswith("Ann"), picks)
st9 = {"week": w}
check("vote not before Friday 18:00", E.mvp_poll_due(st9, cfg(), _dt(2026, 11, 13, 17, 0)) is None)
poll = E.mvp_poll_due(st9, cfg(), _dt(2026, 11, 13, 18, 30))
check("vote due Friday evening", poll and len(poll["answers"]) == 3)
w["poll"] = True
check("vote only once a week", E.mvp_poll_due(st9, cfg(), _dt(2026, 11, 13, 19, 0)) is None)

# tidy: deletes old board messages, reposts in order
fake.calls.clear()
st10 = _copy.deepcopy(st8)
st10["boards"] = {"ladder": {"id": "1", "hook": E.hook_key(WEBHOOK)}, "digest": {"id": "2", "hook": E.hook_key(WEBHOOK)}}
st10["week"] = E.new_week("2026-11-09")
E.tidy_boards(st10, cfg(), lambda t: None)
methods = [c[0] for c in fake.calls]
titles = [json.dumps(c[2]) for c in fake.calls if c[0] == "POST"]
check("tidy deletes old boards", methods.count("DELETE") == 2, methods)
check("tidy posts boards in order", "Race to" in titles[0] and "Guild Weekly" in titles[-1] and len(titles) == 6, len(titles))
check("posts carry the GM name", all('"username": "Guild Milestones"' in t for t in titles))

# parse_file reads keys and lfg
sv2 = Path(TMP) / "sv2.lua"
sv2.write_text('GuildMilestonesDB = {\n["members"] = {\n"A-R|10|MAGE|1|0",\n},\n["keys"] = {\n"Ann|ony,mc,bogus|1",\n},\n'
               '["lfg"] = {\n"Bob|30|WARRIOR|Tank|sm,rfk|1800000900",\n},\n}\n', encoding="utf-8")
ps = E.parse_file(sv2)
check("parse keys (unknown codes dropped)", ps["keys"] == {"Ann": ["ony", "mc"]}, ps["keys"])
check("parse lfg", ps["lfg"] and ps["lfg"][0]["wants"] == ["sm", "rfk"], ps["lfg"])

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
