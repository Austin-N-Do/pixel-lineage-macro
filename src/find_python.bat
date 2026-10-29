@echo off
set "PY="
for %%V in (313 312 311 310) do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        call :try_python "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    )
)
if defined PY exit /b 0
for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PY call :try_python "%%I"
)
if defined PY exit /b 0
for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PY call :try_python "%%I"
)
if defined PY exit /b 0

echo.
echo  Python was not found on this PC.
echo.
echo  Install Python 3.10 or newer ^(64-bit^) from
echo      https://www.python.org/downloads/
echo  and TICK "Add python.exe to PATH" on the first screen of the installer.
echo  Then run this again.
echo.
exit /b 1

:try_python
"%~1" -c "import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%~1"
exit /b 0
