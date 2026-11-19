@echo off
set "REPO=%~dp0..\.."
pushd "%REPO%\apps\api" || exit /b 1
set PYTHONUNBUFFERED=1
"%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
