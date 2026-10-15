@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM ============================================================
REM start_stack_prismenv.bat  total stack launcher (prismenv)
REM
REM Two modes via env var LAOMA_LAUNCH_MODE:
REM   hidden   (default)  all services run in background, no console window
REM                        stdout/stderr are redirected to logs/<Title>.log
REM                        closing the start.bat window does NOT kill services
REM   foreground          legacy behavior, each service opens a visible window
REM
REM Why hidden mode exists:
REM   When a Windows console is closed it sends CTRL_CLOSE_EVENT to all
REM   child consoles; processes started via `start "title" ...` die with
REM   their host window. This has been observed repeatedly in demos
REM   (7000 / 7001 / 3000 disappearing at once).
REM   Hidden mode uses scripts/launchers/run_hidden.ps1 which starts each
REM   service as an independent, detached, windowless process group with
REM   stdout/stderr redirected to a log file.
REM ============================================================

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI\"

set "REDIS_CLI=redis-cli"
if exist "%PROJECT_ROOT%prism_backend\Redis\redis-cli.exe" set "REDIS_CLI=%PROJECT_ROOT%prism_backend\Redis\redis-cli.exe"

if not defined LAOMA_LAUNCH_MODE set "LAOMA_LAUNCH_MODE=hidden"

echo ============================================
echo   Full Startup (prismenv)
echo   Launch Mode: %LAOMA_LAUNCH_MODE%
echo ============================================
echo.

REM Clean up stale backend/worker to avoid address-in-use
if exist "%SCRIPT_DIR%kill_port_7000.bat" call "%SCRIPT_DIR%kill_port_7000.bat"
if exist "%SCRIPT_DIR%kill_port_7001.bat" call "%SCRIPT_DIR%kill_port_7001.bat"
timeout /t 1 /nobreak >nul

echo [1/7] Checking Redis...
%REDIS_CLI% ping >nul 2>&1
if errorlevel 1 (
    echo [INFO] Redis is not running. Starting now...
    if exist "%PROJECT_ROOT%prism_backend\Redis\redis-server.exe" (
        start "Redis Server" "%PROJECT_ROOT%prism_backend\Redis\redis-server.exe"
    ) else (
        start "Redis Server" redis-server
    )
    timeout /t 3 /nobreak >nul
    %REDIS_CLI% ping >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Redis startup failed. Run redis-server manually.
        pause
        exit /b 1
    )
    echo [OK] Redis started.
) else (
    echo [OK] Redis already running.
)
echo.

if /I "%LAOMA_LAUNCH_MODE%"=="foreground" (
    REM ---- legacy behavior: one visible window per service ----
    echo [2/7] Starting Celery Worker (visible window)...
    start "Celery Worker (prismenv)" "%SCRIPT_DIR%start_celery_prismenv.bat"
    timeout /t 2 /nobreak >nul

    echo [3/7] Starting Automation Worker (visible window)...
    start "Automation Worker" "%SCRIPT_DIR%start_worker_prismenv.bat"
    timeout /t 3 /nobreak >nul

    echo [4/7] Starting FastAPI Backend (visible window)...
    start "FastAPI Backend" "%SCRIPT_DIR%start_backend_prismenv.bat"
    timeout /t 3 /nobreak >nul

    echo [5/7] Starting Frontend (visible window)...
    start "React Frontend" "%SCRIPT_DIR%start_frontend.bat"

    echo [6/7] Starting Persona API (visible window)...
    set "PERSONA_PY=%PROJECT_ROOT%prismenv\Scripts\python.exe"
    if not exist "%PERSONA_PY%" set "PERSONA_PY=python"
    start "Persona API" cmd /c "cd /d "%PROJECT_ROOT%tools\persona-studio" && "%PERSONA_PY%" -m persona --data-dir data serve"

    echo [7/7] Starting Persona Dashboard (visible window)...
    start "Persona Dashboard" cmd /c "cd /d "%PROJECT_ROOT%tools\persona-studio\dashboard" && npm run dev"
    goto :summary
)

REM ---- default: hidden mode, background + log to disk ----
REM Ensure venv's python.exe is at the front of PATH so `python` resolves
REM to the prismenv interpreter (previously the sub-launchers called
REM venv\Scripts\activate.bat explicitly; we skip that for background mode).
set "VENV_PY=%PROJECT_ROOT%prismenv\Scripts\python.exe"
if not defined PYTHONPATH set "PYTHONPATH=%PROJECT_ROOT%prism_backend"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
set "PATH=%PROJECT_ROOT%prismenv\Scripts;%PATH%"

REM Env vars the standalone start_backend_prismenv.bat / start_worker_prismenv.bat
REM used to set before invoking python. Keep the same defaults so background mode
REM behaves identically.
if not defined BACKEND_PORT set "BACKEND_PORT=7000"
if not defined LAOMA_BACKEND_URL set "LAOMA_BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%"
if not defined LAOMA_BACKEND_PORT set "LAOMA_BACKEND_PORT=%BACKEND_PORT%"
if not defined PORT set "PORT=%BACKEND_PORT%"
set "PLAYWRIGHT_BROWSERS_PATH=%PROJECT_ROOT%browsers"
if not defined MANUS_API_BASE_URL set "MANUS_API_BASE_URL=%LAOMA_BACKEND_URL%/api/v1"
if not defined AGENT_API_BASE_URL set "AGENT_API_BASE_URL=%MANUS_API_BASE_URL%"
if not defined ENABLE_OCR_RESCUE set "ENABLE_OCR_RESCUE=1"
if not defined ENABLE_SELENIUM_RESCUE set "ENABLE_SELENIUM_RESCUE=1"
if not defined ENABLE_SELENIUM_DEBUG set "ENABLE_SELENIUM_DEBUG=1"
if not defined PLAYWRIGHT_AUTO_INSTALL set "PLAYWRIGHT_AUTO_INSTALL=0"

set "PS_INVOCATION=powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_hidden.ps1""

echo [2/7] Starting Celery Worker (background, log: logs\celery.log)...
%PS_INVOCATION% -Title celery -WorkingDir "%PROJECT_ROOT%prism_backend" -Command "python -m celery -A fastapi_app.tasks.celery_app worker --loglevel=info --pool=threads --concurrency=1000 --hostname=prism-worker@%%h-!RANDOM!" -RepoRoot "%PROJECT_ROOT%" >nul
timeout /t 2 /nobreak >nul

echo [3/7] Starting Automation Worker (background, log: logs\worker.log)...
%PS_INVOCATION% -Title worker -WorkingDir "%PROJECT_ROOT%prism_backend" -Command "python automation_worker\worker.py" -RepoRoot "%PROJECT_ROOT%" >nul
timeout /t 3 /nobreak >nul

echo [4/7] Starting FastAPI Backend (background, log: logs\backend.log)...
%PS_INVOCATION% -Title backend -WorkingDir "%PROJECT_ROOT%prism_backend" -Command "python fastapi_app\run.py" -RepoRoot "%PROJECT_ROOT%" >nul
timeout /t 3 /nobreak >nul

echo [5/7] Starting Frontend (background, log: logs\frontend.log)...
%PS_INVOCATION% -Title frontend -WorkingDir "%PROJECT_ROOT%prism_frontend" -Command "npm run dev" -RepoRoot "%PROJECT_ROOT%" >nul

echo [6/7] Starting Persona API (background, log: logs\persona.log)...
%PS_INVOCATION% -Title persona -WorkingDir "%PROJECT_ROOT%tools\persona-studio" -Command "python -m persona --data-dir data serve" -RepoRoot "%PROJECT_ROOT%" >nul

echo [7/7] Starting Persona Dashboard (background, log: logs\persona-dashboard.log)...
%PS_INVOCATION% -Title persona-dashboard -WorkingDir "%PROJECT_ROOT%tools\persona-studio\dashboard" -Command "npm run dev" -RepoRoot "%PROJECT_ROOT%" >nul

goto :summary

:summary
echo.
echo ============================================
echo   [OK] All services started  (mode: %LAOMA_LAUNCH_MODE%)
echo ============================================
echo.
echo Services:
echo   - Redis Server        localhost:6379
echo   - Celery Worker       task queue           log: logs\celery.log
echo   - Automation Worker   localhost:7001       log: logs\worker.log
echo   - FastAPI Backend     http://localhost:7000 log: logs\backend.log
echo   - React Frontend      http://localhost:3000 log: logs\frontend.log
echo   - Persona API         http://localhost:8787 log: logs\persona.log
echo   - Persona Dashboard   http://localhost:5175 log: logs\persona-dashboard.log
echo.
echo Verify health:
echo   powershell -Command "Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in @(6379,7000,7001,3000,8787,5175) }"
echo.
echo Stop all:
echo   scripts\launchers\stop_stack.bat
echo.
if /I "%LAOMA_LAUNCH_MODE%"=="hidden" (
    echo In hidden mode you may safely close this window.
) else (
    echo In foreground mode DO NOT close the individual service windows.
    pause
)
exit /b 0
