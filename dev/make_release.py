"""Builds the release zips into dist/ with the version in their names (the .exe is built separately).
Run:  python dev/make_release.py"""
import re, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "engine.py").read_text(encoding="utf-8")).group(1)
KIT_FILES = ["GuildMilestones.pyw", "engine.py", "milestone_gui.py", "tray.py", "README.md", "CHANGES.md",
             "HOW TO UPDATE.txt", "build_exe.bat"]
KIT_DIRS = ["GuildMilestones", "shared", "assets"]


def add_dir(z, folder, prefix):
    for f in sorted((ROOT / folder).rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            z.write(f, f"{prefix}{f.relative_to(ROOT).as_posix()}")


def main():
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    addon = out / f"GuildMilestones-addon-v{VERSION}.zip"
    with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as z:
        add_dir(z, "GuildMilestones", "")
    kit = out / f"GuildMilestones-kit-v{VERSION}.zip"
    with zipfile.ZipFile(kit, "w", zipfile.ZIP_DEFLATED) as z:
        for f in KIT_FILES:
            z.write(ROOT / f, f"GuildMilestones-kit-v{VERSION}/{f}")
        for d in KIT_DIRS:
            add_dir(z, d, f"GuildMilestones-kit-v{VERSION}/")
    print(addon.name, kit.name, sep="\n")


if __name__ == "__main__":
    main()
