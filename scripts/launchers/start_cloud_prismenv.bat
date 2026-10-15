@echo off
chcp 65001 >nul
echo ========================================
echo   Prism-Fusion Cloud Service Startup (prismenv)
echo ========================================
echo.

REM Set UTF-8 encoding environment
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "ROOT=%~dp0..\.."
set "CLOUD_DIR=%ROOT%\cloud_service"
set "VENV_PATH=%ROOT%\prismenv"
set "PY=%VENV_PATH%\Scripts\python.exe"

if not defined CLOUD_PORT set "CLOUD_PORT=8000"
if not defined CLOUD_HOST set "CLOUD_HOST=127.0.0.1"
if not defined CLOUD_LOG set "CLOUD_LOG=%ROOT%\logs\cloud_8000.log"

REM Activate prismenv virtual environment
if not exist "%PY%" (
    echo [ERROR] Virtual environment "prismenv" not found at: %VENV_PATH%
    echo Please run: python -m venv prismenv
    pause
    exit /b 1
)

call "%VENV_PATH%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment 'prismenv'
    pause
    exit /b 1
)
echo OK Activated virtual environment 'prismenv'
set "PY=%VENV_PATH%\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo.

REM Ensure logs directory exists
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

REM Port collision check
for /f "usebackq tokens=*" %%A in (`powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort %CLOUD_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { $conn.OwningProcess }"`) do set "PORT_OWNER=%%A"
if defined PORT_OWNER (
    echo [ERROR] Port %CLOUD_PORT% is already in use by PID %PORT_OWNER%.
    echo         Set CLOUD_PORT to a free port or stop that process first.
    pause
    exit /b 1
)

echo [CONFIG] Host:      %CLOUD_HOST%
echo [CONFIG] Port:      %CLOUD_PORT%
echo [CONFIG] Log file:  %CLOUD_LOG%
echo.

echo ========================================
echo   Starting FastAPI Cloud Service
echo ========================================
echo.
echo Access URLs:
echo   - Base:         http://%CLOUD_HOST%:%CLOUD_PORT%
echo   - Health:       http://%CLOUD_HOST%:%CLOUD_PORT%/health
echo   - API Docs:     http://%CLOUD_HOST%:%CLOUD_PORT%/docs
echo   - ReDoc:        http://%CLOUD_HOST%:%CLOUD_PORT%/redoc
echo.
echo Press Ctrl+C to stop service
echo ========================================
echo.

REM Start uvicorn directly (repo convention: `uvicorn cloud_service.main:app`).
REM No --reload (see main.py docstring; long-running reload is unstable).
pushd "%CLOUD_DIR%"

%PY% -m uvicorn cloud_service.main:app --host %CLOUD_HOST% --port %CLOUD_PORT% --log-level info >> "%CLOUD_LOG%" 2>&1

set "RC=%ERRORLEVEL%"
popd

if not "%RC%"=="0" (
    echo.
    echo [ERROR] Cloud service exited with code %RC%
    echo Check log: %CLOUD_LOG%
    pause
    exit /b 1
)

pause
