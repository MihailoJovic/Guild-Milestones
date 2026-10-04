@echo off
REM OPTIONAL. You don't need an .exe: double-clicking GuildMilestones.pyw does the same job.
REM If you do want one, remember to rebuild it after every update.
echo Installing the packaging tool (one time)...
py -m pip install pyinstaller
echo.
echo Building GuildMilestones.exe ...
py -m PyInstaller --onefile --windowed --name GuildMilestones --add-data "GuildMilestones;GuildMilestones" milestone_gui.py
echo.
echo Done! Your app is here: dist\GuildMilestones.exe
pause
