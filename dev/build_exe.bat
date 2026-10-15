@echo off
REM FOR DEVELOPERS ONLY. You never need this to use the app:
REM GitHub builds GuildMilestones.exe automatically for every release (see the Releases page).
REM This just builds the same .exe on your own PC, into the dist folder.
cd /d "%~dp0.."
echo Installing the packaging tool (one time)...
py -m pip install --user pyinstaller
echo.
echo Building GuildMilestones.exe ...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name GuildMilestones --icon assets\gm.ico ^
   --add-data "GuildMilestones;GuildMilestones" --add-data "assets;assets" --hidden-import tray milestone_gui.py
echo.
echo Done! Your app is here: dist\GuildMilestones.exe
pause
