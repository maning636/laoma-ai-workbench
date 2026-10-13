@echo off
rem Detached frontend launcher (ASCII-only; %~dp0 Chinese-safe)
cd /d "%~dp0..\prism_frontend"
call npm run dev >> "%~dp0..\logs\frontend-detached.log" 2>&1
