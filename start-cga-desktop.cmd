@echo off
setlocal
cd /d "%~dp0"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "& { .\src\scripts\start-desktop.ps1 start; if ($?) { .\src\scripts\start-desktop.ps1 open } }"
