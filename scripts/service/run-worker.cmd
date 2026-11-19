@echo off
set "REPO=%~dp0..\.."
pushd "%REPO%\apps\api" || exit /b 1
set PYTHONUNBUFFERED=1
"%REPO%\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app.celery_app worker --loglevel=INFO --pool=solo --concurrency=1
