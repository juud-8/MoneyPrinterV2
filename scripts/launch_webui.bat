@echo off
REM Desktop / taskbar launcher for MoneyPrinterV2 control panel.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_webui.ps1" %*
