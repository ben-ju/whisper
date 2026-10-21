@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [CodeWhisper] Virtual environment not found.
    echo              Run install.bat first.
    pause
    exit /b 1
)

:: pythonw = no console window. Use run_debug.bat to see logs live.
start "" ".venv\Scripts\pythonw.exe" app.py
