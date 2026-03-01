@echo off
setlocal EnableDelayedExpansion

echo ============================================================
echo  CodeWhisper -- Setup
echo ============================================================
echo.

:: ── 1. Find uv (or download it — no Python needed) ───────────────────────────
set UV=

for %%U in (
    "%LOCALAPPDATA%\Programs\Anki\uv.exe"
    "%LOCALAPPDATA%\uv\bin\uv.exe"
    "%APPDATA%\uv\bin\uv.exe"
    "%USERPROFILE%\.local\bin\uv.exe"
    "%USERPROFILE%\.cargo\bin\uv.exe"
) do (
    if exist %%U (
        set "UV=%%~U"
        goto :got_uv
    )
)

where uv >nul 2>&1
if %errorlevel% equ 0 (
    set UV=uv
    goto :got_uv
)

echo [INFO] uv not found -- downloading it now (this is a one-time step)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "irm https://astral.sh/uv/install.ps1 | iex"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Could not download uv. Check your internet connection.
    echo         Manual install: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

:: uv installer puts the binary here on Windows
for %%U in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%LOCALAPPDATA%\uv\bin\uv.exe"
    "%APPDATA%\uv\bin\uv.exe"
    "%USERPROFILE%\.cargo\bin\uv.exe"
) do (
    if exist %%U (
        set "UV=%%~U"
        goto :got_uv
    )
)

echo [ERROR] uv was installed but the binary could not be located.
echo         Close this window, open a new terminal, and re-run install.bat.
pause
exit /b 1

:got_uv
echo [OK] uv found: %UV%
echo.

:: ── 2. Create virtual environment ────────────────────────────────────────────
::       uv will automatically download Python 3.11 if it is not on this machine
if exist "%~dp0.venv\Scripts\python.exe" (
    echo [OK] Virtual environment already exists.
) else (
    echo [INFO] Creating virtual environment (uv will download Python if needed)...
    "%UV%" venv "%~dp0.venv" --python 3.11
    if !errorlevel! neq 0 (
        echo [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment ready.
)
echo.

:: ── 3. Install Python packages ────────────────────────────────────────────────
echo [INFO] Installing packages (first run may take a few minutes)...
"%UV%" pip install -r "%~dp0requirements.txt" --python "%~dp0.venv\Scripts\python.exe"
if !errorlevel! neq 0 (
    echo [ERROR] Package installation failed.
    pause
    exit /b 1
)
echo [OK] Packages installed.
echo.

:: ── 4. Desktop shortcut ───────────────────────────────────────────────────────
echo [INFO] Creating desktop shortcut...
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$desktop = [Environment]::GetFolderPath('Desktop');" ^
    "$sc = $ws.CreateShortcut($desktop + '\CodeWhisper.lnk');" ^
    "$sc.TargetPath = '%~dp0run.bat';" ^
    "$sc.WorkingDirectory = '%~dp0';" ^
    "$sc.Description = 'CodeWhisper - Local Speech to Text';" ^
    "$sc.IconLocation = 'shell32.dll,168';" ^
    "$sc.WindowStyle = 7;" ^
    "$sc.Save()"
echo [OK] Desktop shortcut created.
echo.

:: ── 5. Done ───────────────────────────────────────────────────────────────────
echo ============================================================
echo  Done! Use the Desktop shortcut or run.bat to launch.
echo.
echo  NOTE: First launch downloads the Whisper model.
echo    large-v3  ~1.5 GB  (best quality, needs a decent CPU)
echo    small.en   ~500 MB  (faster, great for weaker machines)
echo  Change MODEL_SIZE in app.py before first launch if needed.
echo ============================================================
echo.
pause
