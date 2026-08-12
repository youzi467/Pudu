@echo off
rem ============================================================
rem  Pudu local web app launcher - double-click to start
rem  Do NOT open tools\pudu_ui.html directly in a browser.
rem  (This file is pure ASCII on purpose: cmd.exe parses .bat
rem   with the OEM codepage, so any non-ASCII byte here breaks
rem   line parsing. Chinese text is printed by the Python
rem   server itself after chcp 65001 is active.)
rem ============================================================
chcp 65001 >nul
setlocal

set "VENV_PY=C:\Users\13157\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] venv python not found: %VENV_PY%
    echo Set PUDU_OMR_PYTHON env var, or edit the path at the top of tools\pudu_server.py.
    pause
    exit /b 1
)

cd /d "%~dp0"
echo Starting Pudu local web app...
echo Browser will open http://127.0.0.1:8765/ - closing this window stops the server.
"%VENV_PY%" tools\pudu_server.py

if errorlevel 1 (
    echo.
    echo [NOTE] Startup failed. If port 8765 is in use, close that program and retry.
    pause
)
