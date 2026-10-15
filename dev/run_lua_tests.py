"""Runs the addon's Lua tests with a real Lua 5.4 bundled in the 'lupa' package.
One-time setup:  python -m pip install --user lupa
Then:            python dev/run_lua_tests.py
"""
import os, subprocess, sys
from pathlib import Path

DEV = Path(__file__).resolve().parent
ADDON = DEV.parent / "GuildMilestones" / "GuildMilestones.lua"

RUNNER = r'''
import sys
from lupa import lua54
lua = lua54.LuaRuntime()
lua.execute('dofile(...)', sys.argv[1])
'''


def main():
    tests = sorted(DEV.glob("test_*.lua"))
    env = dict(os.environ, ADDON=str(ADDON))
    failed = 0
    for t in tests:
        print(f"== {t.name}")
        r = subprocess.run([sys.executable, "-c", RUNNER, t.name], cwd=DEV, env=env)
        failed += r.returncode != 0
    print("ALL PASSED" if not failed else f"{failed} test file(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
