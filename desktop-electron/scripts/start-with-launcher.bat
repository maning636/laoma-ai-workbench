@echo off
:: 启动 老马AI工作台 并显示启动管理器
:: 用于开发环境测试

echo ========================================
echo 老马AI工作台 - Launcher Mode
echo ========================================

set LAOMA_SHOW_LAUNCHER=1
set LAOMA_START_SERVICES=0

cd /d "%~dp0..\"
npm start
