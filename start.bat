@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%~dp0"
title PONYATNO bot

set "PY="

py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
        "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" launcher.py %*
        if errorlevel 1 pause
        exit /b
    )
)

if not defined PY goto nopython

%PY% launcher.py %*
if errorlevel 1 pause
exit /b

:nopython
echo.
echo   Python 3.10+ not found.
echo.
echo   1. Install it from https://www.python.org/downloads/  (check "Add to PATH")
echo   2. Run start.bat again.
echo.
echo   If Python is installed but says "The system cannot find the file specified",
echo   Windows Store aliases are broken. Turn them off here:
echo   Settings - Apps - Advanced app settings - App execution aliases
echo   and disable python.exe / python3.exe.
echo.
pause
exit /b 1
