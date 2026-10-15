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
check("epic loot pings, deaths don't", [i.get("silent") for i in items] == [True, True, False], [i.get("silent") for i in items])
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
check("old state's URL converted to a fingerprint", "url" not in old["digest"] and old["digest"]["hook"] == E.hook_key(WEBHOOK))

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

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
