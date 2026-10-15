# ============================================================
# run_hidden.ps1 — 以「无窗口 + 独立进程组 + 日志落盘」方式
#                  启动一条后台命令。用于 start_stack_prismenv.bat。
#
# 为什么存在:
#   scripts/launchers/*.bat 里原来用 `start "标题" xxx` 起服务,
#   每个服务会占一个可见 cmd 窗口。用户关掉任何窗口,服务就死
#   (Windows console 关闭 → CTRL_CLOSE_EVENT → 服务终止)。
#   本脚本用 Start-Process -WindowStyle Hidden 起子进程:
#     - 新进程组(detached),父控制台关闭不影响
#     - -WindowStyle Hidden → 无可见窗口,用户不会误关
#     - 全部 stdout/stderr 重定向到 logs\<Title>.log
#     - 保存 PID 到 logs\<Title>.pid,方便 stop / healthcheck
#
# 用法(从 .bat 调用):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_hidden.ps1" `
#       -Title backend -WorkingDir "<backend>" `
#       -Command "<python.exe> fastapi_app\run.py" `
#       -RepoRoot "<repo>"
#
# 退出码:0 = 子进程成功创建;非 0 = 参数错误 / 前置检查失败。
# ============================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Title,
    [Parameter(Mandatory = $true)][string]$WorkingDir,
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

# --- 日志目录 ------------------------------------------------
if (-not $RepoRoot) {
    # 默认:脚本位于 <repo>/scripts/launchers/
    $RepoRoot = Split-Path (Split-Path (Split-Path $PSCommandPath -Parent) -Parent) -Parent
}
$LogDir = Join-Path $RepoRoot 'logs'
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir ($Title + '.log')
$PidFile = Join-Path $LogDir ($Title + '.pid')

# --- 前置检查 -------------------------------------------------
if (-not (Test-Path $WorkingDir)) {
    Write-Error "[run_hidden:$Title] working dir not found: $WorkingDir"
    exit 2
}

# --- 日志头 ---------------------------------------------------
$logHeader = "`r`n===== [$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] starting '$Title' =====`r`n" +
             "WORKDIR = $WorkingDir`r`n" +
             "CMD     = $Command`r`n" +
             "PWD     = $PID`r`n"
# 追加(不清空旧日志;便于回溯多轮启停)
Add-Content -LiteralPath $LogFile -Value $logHeader -Encoding UTF8

# --- 用 cmd /c 启动:保证 Windows 上 stdout/stderr 一致管道处理 ---
$cmdArgs = "/c ( cd /d `"$WorkingDir`" && $Command >> `"$LogFile`" 2>&1 )"

$proc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList $cmdArgs `
    -WindowStyle Hidden `
    -PassThru

# Start-Process -PassThru 返回的 Process.Id 是 cmd.exe 的 PID;
# 真正的服务进程是它的子进程,需要另查。这里写 cmd.exe 的 PID,足够用作
# 「这个 launch 是否存在」的锚点。

# --- 保存 PID -------------------------------------------------
$proc.Id | Out-File -LiteralPath $PidFile -Encoding ascii -NoNewline

Write-Host "[run_hidden] OK '$Title' started. cmd.exe PID=$($proc.Id), log=$LogFile"

# --- 短暂等子进程起来,如果立即崩就给出明显错误 -----------------
Start-Sleep -Milliseconds 500
$alive = $false
try { $alive = -not $proc.HasExited } catch {}

if (-not $alive) {
    Write-Warning "[run_hidden] '$Title' exited immediately. Check $LogFile for the reason."
    exit 3
}
exit 0
