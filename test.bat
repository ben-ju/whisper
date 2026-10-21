@echo off
echo Test OK - les .bat fonctionnent.
cd /d "%~dp0"
echo Dossier: %CD%
where uv
dir .venv\Scripts\python*.exe
".venv\Scripts\python.exe" -c "import sys; print(sys.version)"
".venv\Scripts\python.exe" -c "import PySide6; print('PySide6', PySide6.__version__)"
pause
