@echo off
REM ARCHIVED 2026-07-11 — do not run while brand is in ARCHIVED_BRANDS.
REM Kept for resurrection; Task Scheduler task 60SecondThrillersDaily was removed.
setlocal
cd /d "%~dp0..\..\.."
call venv\Scripts\activate.bat
python scripts\_archived\sixty_second_thrillers\scheduled_thrillers.py %*
exit /b %ERRORLEVEL%
