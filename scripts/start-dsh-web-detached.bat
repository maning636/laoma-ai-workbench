@echo off
rem Detached dsh (DeepSeek Harness) web launcher - spawned via scheduled task
rem ASCII-only; %~dp0 Chinese-safe
rem --trusted-host: allow 老马AI工作台 frontend (localhost:3000) to embed dsh UI in iframe
cd /d "%~dp0.."
set PYTHONUNBUFFERED=1
"%USERPROFILE%\.bun\bin\dsh.exe" web --no-open --trusted-host localhost:3000 --trusted-host 127.0.0.1:3000 >> "%~dp0..\logs\dsh-web.log" 2>&1
