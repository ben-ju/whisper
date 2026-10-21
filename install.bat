@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title CodeWhisper - Installation

echo ============================================================
echo  CodeWhisper - Installation
echo ============================================================
echo.

rem --- 1. Find uv, or download it -------------------------------------------
set "UV="
for %%U in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%LOCALAPPDATA%\uv\bin\uv.exe"
    "%APPDATA%\uv\bin\uv.exe"
    "%USERPROFILE%\.cargo\bin\uv.exe"
    "%LOCALAPPDATA%\Programs\Anki\uv.exe"
) do (
    if not defined UV if exist %%U set "UV=%%~U"
)
if not defined UV (
    where uv >nul 2>&1
    if !errorlevel! equ 0 set "UV=uv"
)
if defined UV goto got_uv

echo [INFO] uv introuvable, telechargement - une seule fois...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV goto got_uv
echo [ERREUR] Impossible d'installer uv. Verifie ta connexion internet.
echo          Installation manuelle : https://docs.astral.sh/uv/
goto fail

:got_uv
echo [OK] uv : %UV%
echo.

rem --- 2. Virtual environment ------------------------------------------------
if exist ".venv\Scripts\python.exe" goto venv_ok
echo [INFO] Creation de l'environnement Python - uv telecharge Python 3.11 si besoin...
"%UV%" venv ".venv" --python 3.11
if errorlevel 1 (
    echo [ERREUR] Impossible de creer l'environnement virtuel.
    goto fail
)
:venv_ok
echo [OK] Environnement Python pret.
echo.

rem --- 3. Packages -------------------------------------------------------------
echo [INFO] Installation des paquets - quelques minutes la premiere fois...
"%UV%" pip install -r requirements.txt --python ".venv\Scripts\python.exe"
if errorlevel 1 (
    echo [ERREUR] L'installation des paquets a echoue. Lis le message ci-dessus.
    goto fail
)
echo [OK] Paquets installes.
echo.

rem --- 4. Shortcuts: Desktop + Start menu -----------------------------------
echo [INFO] Creation des raccourcis Bureau et menu Demarrer...
set "PS_TARGET=%~dp0.venv\Scripts\pythonw.exe"
set "PS_DIR=%~dp0"
set "PS_ICON=%~dp0codewhisper\assets\codewhisper.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'));" ^
    "foreach ($p in $places) {" ^
    "  $sc = $ws.CreateShortcut((Join-Path $p 'CodeWhisper.lnk'));" ^
    "  $sc.TargetPath = $env:PS_TARGET;" ^
    "  $sc.Arguments = 'app.py';" ^
    "  $sc.WorkingDirectory = $env:PS_DIR;" ^
    "  $sc.Description = 'CodeWhisper - dictee vocale';" ^
    "  $sc.IconLocation = $env:PS_ICON + ',0';" ^
    "  $sc.Save() }"
echo [OK] Raccourcis crees.
echo.

rem --- 5. Done -------------------------------------------------------------------
echo ============================================================
echo  Termine ! CodeWhisper demarre.
echo  Ensuite : raccourci CodeWhisper sur le Bureau ou dans le menu Demarrer.
echo  Le premier lancement telecharge le modele Whisper choisi.
echo ============================================================
echo.
start "" ".venv\Scripts\pythonw.exe" app.py
timeout /t 8
exit /b 0

:fail
echo.
echo L'installation n'est pas terminee.
pause
exit /b 1
