@echo off
setlocal EnableExtensions
title Pixel Lineage Setup
cd /d "%~dp0"

call src\find_python.bat
if not defined PY (
    pause
    exit /b 1
)
"%PY%" src\bootstrap.py main.py --check
echo.
if errorlevel 1 (
    echo  Setup did not finish. See the messages above and setup-log.txt.
) else (
    echo  Setup finished. Start the macro with Launch.bat.
)
echo.
pause
