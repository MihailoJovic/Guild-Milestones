"""Fails if the app, addon, .toc and CHANGES.md disagree about the version. Run: python dev/check_versions.py"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def grab(path, pattern):
    m = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


found = {
    "engine.py APP_VERSION": grab("engine.py", r'^APP_VERSION = "([^"]+)"'),
    "GuildMilestones.lua VERSION": grab("GuildMilestones/GuildMilestones.lua", r'^local VERSION = "([^"]+)"'),
    ".toc ## Version": grab("GuildMilestones/GuildMilestones.toc", r"^## Version:\s*(\S+)"),
    "CHANGES.md newest section": grab("CHANGES.md", r"^## v(\S+)"),
}
for k, v in found.items():
    print(f"{k:32} {v}")
headline = re.search(r"^## v\S+\s*\n\*\*.+\*\*", (ROOT / "CHANGES.md").read_text(encoding="utf-8"), re.M)
if len(set(found.values())) != 1 or None in found.values():
    sys.exit("Versions don't match. Bump all four together.")
if not headline:
    sys.exit("The newest CHANGES.md section needs a bold one-line headline right under it.")
print("All in step.")
