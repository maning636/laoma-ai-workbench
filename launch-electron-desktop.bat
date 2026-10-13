@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BACKEND_URL=http://127.0.0.1:7000"
set "LAOMA_USE_EXTERNAL_STACK=1"
set "LAOMA_START_SERVICES=0"
set "LAOMA_START_FRONTEND=0"
set "LAOMA_BACKEND_URL=%BACKEND_URL%"
set "NEXT_PUBLIC_LAOMA_BACKEND_URL=%BACKEND_URL%"
set "NEXT_PUBLIC_BACKEND_URL=%BACKEND_URL%"

set "PACKAGED_EXE="
if exist "%~dp0desktop-electron\dist-build\win-unpacked\LaomaAI.exe" (
    set "PACKAGED_EXE=%~dp0desktop-electron\dist-build\win-unpacked\LaomaAI.exe"
)
if not defined PACKAGED_EXE (
    for /d %%D in ("%~dp0desktop-electron\dist-out\*") do (
        if exist "%%~fD\win-unpacked\LaomaAI.exe" (
            set "PACKAGED_EXE=%%~fD\win-unpacked\LaomaAI.exe"
        )
    )
)
if defined PACKAGED_EXE (
    echo [INFO] Launching packaged Electron desktop...
    start "老马AI工作台 Desktop" "%PACKAGED_EXE%"
    exit /b 0
)

if not exist "%~dp0desktop-electron\node_modules\electron" (
    echo [INFO] Installing desktop-electron dependencies...
    pushd "%~dp0desktop-electron"
    call npm install
    set "RC=%ERRORLEVEL%"
    popd
    if not "%RC%"=="0" exit /b %RC%
)

echo [INFO] Launching development Electron desktop...
pushd "%~dp0desktop-electron"
call npm run start
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
