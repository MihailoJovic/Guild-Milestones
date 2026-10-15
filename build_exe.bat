@echo off
REM Builds GuildMilestones.exe (one file, no Python needed to run it).
REM Usually you don't need this: every GitHub release already has the .exe attached.
echo Installing the packaging tool (one time)...
py -m pip install --user pyinstaller
echo.
echo Building GuildMilestones.exe ...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name GuildMilestones --icon assets\gm.ico ^
   --add-data "GuildMilestones;GuildMilestones" --add-data "assets;assets" --hidden-import tray milestone_gui.py
echo.
echo Done! Your app is here: dist\GuildMilestones.exe
pause
