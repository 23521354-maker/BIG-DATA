@echo off
REM Double-click to start the whole Lakehouse and open every web UI.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ops\start-all.ps1"
pause
