@echo off
rem Local API + built UI on http://127.0.0.1:8020, sharing data with the desktop app.
cd /d "%~dp0..\backend"
set "MELOFORGE_DATA_DIR=%LOCALAPPDATA%\MeloForge Studio\data"
set "MELOFORGE_ENV_FILE=%LOCALAPPDATA%\MeloForge Studio\config.env"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8020
