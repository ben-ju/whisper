@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [CodeWhisper] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" app.py
pause
