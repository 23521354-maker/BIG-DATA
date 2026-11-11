@echo off
REM Double-click when you are done: stops every service and closes the port-forward windows.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ops\stop-all.ps1"
pause
