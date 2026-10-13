@echo off
rem Detached backend launcher - spawned via WMI to survive agent session cleanup
rem NOTE: keep this file ASCII-only (cmd reads it in ANSI codepage); use %~dp0 for Chinese-safe paths
cd /d "%~dp0..\prism_backend"
set PYTHONUNBUFFERED=1
"%~dp0..\.venv\Scripts\python.exe" -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port 7000 >> "%~dp0..\logs\backend-detached.log" 2>&1
