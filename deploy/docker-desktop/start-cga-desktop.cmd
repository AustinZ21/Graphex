@echo off
setlocal
cd /d "%~dp0"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\start-desktop.ps1" start -OpenBrowser:$true
