# Dev notes

## Addon tests (Lua)
`wowstub.lua` is a fake WoW API (frames, timers, chat, roster, guild info...). The tests load the real addon against it.

With a normal Lua 5.4 install (PowerShell):

    cd dev
    $env:ADDON = "..\GuildMilestones\GuildMilestones.lua"
    lua test_addon.lua
    lua test_classic.lua

Each prints "N passed, 0 failed". No `lua` installed? Use the bundled runner instead (one-time `python -m pip install --user lupa`):

    python dev/run_lua_tests.py

## Python checks
`python -m py_compile engine.py milestone_gui.py GuildMilestones.pyw`
`python dev/test_engine.py` tests the engine with a fake Discord and a throwaway settings folder.
`dev/mock_discord.py` is a tiny fake Discord webhook server on 127.0.0.1:8765 for testing posts without touching the real server.
