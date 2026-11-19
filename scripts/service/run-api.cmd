@echo off
cd /d "E:\Code\AI project\apps\api"
set PYTHONUNBUFFERED=1
"E:\Code\AI project\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
