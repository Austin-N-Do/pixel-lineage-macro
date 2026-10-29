@echo off
setlocal EnableExtensions
title 1vtt's Pixel Lineage Macro
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" if exist ".venv\.requirements-stamp" (
    start "" ".venv\Scripts\pythonw.exe" "src\main.py"
    exit /b 0
)

call src\find_python.bat
if not defined PY (
    pause
    exit /b 1
)
"%PY%" src\bootstrap.py main.py --check
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "src\main.py"
exit /b 0
