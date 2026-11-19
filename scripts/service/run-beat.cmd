@echo off
cd /d "E:\Code\AI project\apps\api"
set PYTHONUNBUFFERED=1
"E:\Code\AI project\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app.celery_app beat --loglevel=INFO
