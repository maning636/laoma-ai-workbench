# ============================================================
# e2e_packaged_test.ps1
#
# 目的：验证 `build-package.bat` 打包出的 win-unpacked 产物在「干净环境」
#       下能启动、后端就绪、关键 API 全部返回预期字段。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\e2e_packaged_test.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\e2e_packaged_test.ps1 -PackagePath 'D:\..\dist-out\v2\win-unpacked'
#
# 关键：
#   1. 清空 LAOMA_* 环境变量，模拟全新机器；
#   2. 把整个 win-unpacked 目录 copy 到一个「含中文 + 空格」的临时目录；
#   3. 启动 supervisor.exe（首选）或 LaomaAI.exe，从 state file 里读出 backend 端口；
#   4. 轮询 /health 直到就绪（默认 60s）；
#   5. 校验 /api/v1/system/preflight 与 /api/v1/agent/easel/status 的关键字段；
#   6. 【Redis 硬断言】preflight.redis.reachable 必须为 True；用产物自带的
#      prismenv\Scripts\python.exe + redis-py 对内置 Redis 真实 PING 一次，
#      任何 RESP3/HELLO 不兼容都会在这里硬失败；再校验产物里 redis-py 主版本 < 5；
#   7. 无论成败都杀进程 + 清理临时目录。
#
# 输出：最后一行 "RESULT: PASS" 或 "RESULT: FAIL <reason>"，exit code 0/1。
# ============================================================
[CmdletBinding()]
param(
    # 打包产物根目录（含 LaomaAI.exe / resources\...）；不传则自动扫描 dist-out\v*\win-unpacked 中最新
    [string]$PackagePath = '',
    # backend 就绪等待总时长
    [int]$TimeoutSec = 60,
    # 是否保留临时目录（便于人工排查）；仅 -NoCleanup 时不删除
    [switch]$NoCleanup,
    # 仅打印将要执行的路径，不真启动。便于 CI 干跑
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$Script:Pass = $true
$Script:FailReason = ''
$Script:StartedProc = @()
$Script:TempDir = ''

# --- helper --------------------------------------------------------------

function Write-Step($msg) {
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host ("[{0}] {1}" -f $ts, $msg)
}
function Write-Ok($msg)   { Write-Host ("[{0}]   + {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg) }
function Write-Warn($msg){ Write-Host ("[{0}]   ! {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg) -ForegroundColor Yellow }
function Write-Bad($msg) { Write-Host ("[{0}]   - {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg) -ForegroundColor Red }

function Test-JsonField($json, $path, [bool]$requireNotNull) {
    # 极简 JSON path 探测：'.a.b.c'，'.' 表示根
    if (-not $json) { return $false }
    $p = "$path".TrimStart('.')
    if (-not $p) { return ($null -ne $json) }
    $tokens = $p.Split('.')
    $cur = $json
    foreach ($t in $tokens) {
        if ($cur -eq $null) { return $false }
        if ($cur -is [System.Collections.IDictionary]) {
            if (-not $cur.Contains($t)) { return $false }
            $cur = $cur[$t]
        } elseif ($cur.PSObject.Properties.Name -contains $t) {
            $cur = $cur.$t
        } else {
            return $false
        }
    }
    if ($requireNotNull) { return ($null -ne $cur) }
    return $true
}

function Invoke-JsonGet([string]$url, [double]$timeoutSec = 8.0) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec -ErrorAction Stop
        if ($resp.StatusCode -ge 400) {
            Write-Warn ("GET {0} => HTTP {1}" -f $url, $resp.StatusCode)
            return $null
        }
        # PowerShell 5.1 常见陷阱：Content 若含 BOM 或纯文本，JSON 解析前剥 BOM
        $body = $resp.Content
        if ($body -match '^\s*\uFEFF') { $body = $body.TrimStart([char]0xFEFF) }
        return ($body | ConvertFrom-Json)
    } catch {
        Write-Warn ("GET {0} FAILED: {1}" -f $url, $_.Exception.Message)
        return $null
    }
}

function Stop-StartedProcesses() {
    # 1) 先 kill 我们自己 Start-Process 出来的句柄
    foreach ($p in $Script:StartedProc) {
        try {
            if ($p -and -not $p.HasExited) {
                $p.Kill()
                $p.WaitForExit(3000) | Out-Null
            }
        } catch {}
    }
    $Script:StartedProc = @()

    # 2) 按名字再杀一遍 supervisor.exe / LaomaAI.exe，兜底（Electron 主进程会 fork 子进程）
    foreach ($img in @('LaomaAI.exe', 'supervisor.exe')) {
        try {
            $list = Get-Process -Name $img -ErrorAction SilentlyContinue
            if ($list) {
                $list | ForEach-Object {
                    try { $_.CloseMainWindow() } catch {}
                }
                Start-Sleep -Milliseconds 800
                $list = Get-Process -Name $img -ErrorAction SilentlyContinue
                if ($list) { $list | Stop-Process -Force -ErrorAction SilentlyContinue }
            }
        } catch {}
    }
}

function Remove-TempTree() {
    if ($Script:TempDir -and (Test-Path $Script:TempDir)) {
        try {
            Remove-Item -LiteralPath $Script:TempDir -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warn ("remove temp failed: {0}" -f $_.Exception.Message)
        }
    }
}

function Clean-Exit([int]$code) {
    Stop-StartedProcesses
    if (-not $NoCleanup) { Remove-TempTree }
    if ($code -eq 0) {
        Write-Host "RESULT: PASS" -ForegroundColor Green
    } else {
        Write-Host ("RESULT: FAIL {0}" -f $Script:FailReason) -ForegroundColor Red
    }
    exit $code
}

# --- 主流程 ---------------------------------------------------------------

Write-Step "=== E2E Packaged Test 开始 ==="

# 1. 定位打包产物 -----------------------------------------------------------
if ($DryRun) { Write-Step "[DRYRUN] 将进入 -DryRun 模式：不启动任何进程" }

if ($PackagePath) {
    $SrcDir = $PackagePath
} else {
    # 自动扫描 dist-out\v*\win-unpacked 目录中最新的一个
    $candidates = Get-ChildItem -Path 'dist-out' -Filter 'win-unpacked' -Directory -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\v\d+\\win-unpacked$' } |
        Sort-Object -Property FullName -Descending
    if (-not $candidates) {
        Write-Step "未找到 dist-out\v*\win-unpacked，请通过 -PackagePath 指定，或先运行 scripts\packaging\build-package.bat"
        Write-Bad "dist-out 目录不存在或无 v<N>\win-unpacked 子目录"
        Clean-Exit 1
    }
    $SrcDir = $candidates[0].FullName
    Write-Ok "auto-discovered: $SrcDir"
}

if (-not (Test-Path $SrcDir)) {
    Write-Bad "PackagePath 不存在: $SrcDir"
    Clean-Exit 1
}
Write-Ok "source dir: $SrcDir"

# 检查必备文件
$requiredFiles = @(
    'LaomaAI.exe',
    'resources\prism_backend',
    'resources\prismenv\Scripts\python.exe'
)
foreach ($rel in $requiredFiles) {
    if (-not (Test-Path (Join-Path $SrcDir $rel))) {
        Write-Bad "缺少必备产物: $rel"
        Clean-Exit 1
    }
}
Write-Ok "artifacts sanity check OK"

if ($DryRun) { Write-Step "[DRYRUN] 到这里已定位并校验产物，不启动进程"; Clean-Exit 0 }

# 2. 清空 LAOMA_* env（模拟干净机器） ----------------------------------------
$cleared = @()
foreach ($key in (Get-ChildItem Env: | Where-Object { $_.Name -like 'LAOMA_*' })) {
    $cleared += $key.Name
    Remove-Item Env:$($key.Name) -ErrorAction SilentlyContinue
}
if ($cleared.Count -gt 0) {
    Write-Ok ("已清空 LAOMA_* 环境变量: {0}" -f ($cleared -join ', '))
} else {
    Write-Ok "无遗留 LAOMA_* 环境变量"
}

# 3. 复制到含中文+空格的临时目录 --------------------------------------------
$drive = if ($env:TEMP -match '^([A-Za-z]:)') { $Matches[1] } else { 'C:' }
$base  = Join-Path $drive '测试'
New-Item -ItemType Directory -Path $base -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
# 注意：Copy-Item -Recurse 若目标已存在（且是目录），会把源目录复制成**目标的子目录**，
# 造成 win-unpacked\win-unpacked\... 双层嵌套，LaomaAI.exe 找不到。
# 因此 target 指向"尚未创建"的路径，Copy-Item 会把源目录内容就地复制进去。
$parent = Join-Path $base 'path with spaces'
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$target = Join-Path $parent $stamp
$installDir = $target
$Script:TempDir = $parent
# 清理可能残留的 target（上一轮 NoCleanup 会留下）
if (Test-Path $target) {
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Ok "temp dir: $installDir"

Write-Step "copying artifacts (may take a while)..."
$ErrorActionPreference = 'Stop'
try {
    Copy-Item -LiteralPath $SrcDir -Destination $installDir -Recurse -Force
} catch {
    Write-Bad ("copy failed: {0}" -f $_.Exception.Message)
    Clean-Exit 1
} finally {
    $ErrorActionPreference = 'Continue'
}
Write-Ok "copy done"

# 4. 选择启动入口 -----------------------------------------------------------
# 首选 supervisor.exe，其次 LaomaAI.exe。若两者都没有，说明打包产物不完整。
$supervisorExe = Join-Path $installDir 'resources\supervisor\supervisor.exe'
$mainExe       = Join-Path $installDir 'LaomaAI.exe'

$launcher = $null
if (Test-Path $supervisorExe) {
    $launcher = $supervisorExe
    Write-Ok "launching supervisor.exe"
} elseif (Test-Path $mainExe) {
    $launcher = $mainExe
    Write-Ok "launching LaomaAI.exe (supervisor.exe 缺失，回退到主程序)"
} else {
    Write-Bad "既无 supervisor.exe 也无 LaomaAI.exe"
    Clean-Exit 1
}

# 5. 启动 -------------------------------------------------------------------
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName            = $launcher
$psi.WorkingDirectory    = $installDir
$psi.UseShellExecute     = $false
$psi.CreateNoWindow      = $false
# 关键：显式传入 backend 端口，避免与本机其它占用冲突；supervisor 也尊重 LAOMA_BACKEND_PORT
$psi.EnvironmentVariables['LAOMA_BACKEND_PORT'] = '7000'
$psi.EnvironmentVariables['LAOMA_BACKEND_HOST'] = '127.0.0.1'
$psi.EnvironmentVariables['LAOMA_START_SERVICES'] = '1'
$psi.EnvironmentVariables['LAOMA_START_FRONTEND'] = '1'
$psi.EnvironmentVariables['LAOMA_AUTO_YES'] = '1'
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
$proc.EnableRaisingEvents = $true
$proc.Start() | Out-Null
$Script:StartedProc += $proc
Write-Ok ("started pid={0}" -f $proc.Id)

# 6. 等 supervisor state file 出现，从里面读端口 ----------------------------
# supervisor 会写 state file 到 %LOCALAPPDATA%\老马AI工作台\supervisor-state.json
$stateCandidates = @(
    (Join-Path $env:LOCALAPPDATA '老马AI工作台\supervisor-state.json'),
    (Join-Path $env:APPDATA      '老马AI工作台\supervisor-state.json'),
    (Join-Path $installDir       'supervisor-state.json')
)
$stateFile = $null
foreach ($c in $stateCandidates) {
    if (Test-Path $c) { $stateFile = $c; break }
}

$backendPort = 7000  # 兜底默认
if ($stateFile) {
    try {
        $st = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        # state 结构含 services.{backend}.port 或 servicePorts.backend 等多种形态
        $bp = $null
        if ($st.PSObject.Properties.Name -contains 'servicePorts' -and $st.servicePorts.PSObject.Properties.Name -contains 'backend') {
            $bp = [int]$st.servicePorts.backend
        } elseif ($st.PSObject.Properties.Name -contains 'services' -and $st.services.PSObject.Properties.Name -contains 'backend') {
            $bp = [int]$st.services.backend.port
        }
        if ($bp -and $bp -gt 0) { $backendPort = $bp }
    } catch {
        Write-Warn ("read state file failed: {0}" -f $_.Exception.Message)
    }
}

$base_url = "http://127.0.0.1:$backendPort"
Write-Ok "backend base url: $base_url"

# 7. 轮询 /health ---------------------------------------------------------
Write-Step "waiting for backend to be ready (timeout ${TimeoutSec}s)..."
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
$ready = $false
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "$base_url/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # 忽略连接失败，继续轮询
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Write-Bad "backend 未在 ${TimeoutSec}s 内就绪"
    Clean-Exit 1
}
Write-Ok "/health => 200"

# 8. 校验关键 API ---------------------------------------------------------
$failList = @()

# 8.1 preflight：11 个组件 key
$expectedKeys = @(
    'python', 'redis', 'celery', 'easel', 'hermes',
    'persona_api', 'playwright', 'disk_space',
    'skills_dir_exists', 'third_party_tools', 'template_lib'
)
$pf = Invoke-JsonGet "$base_url/api/v1/system/preflight"
if (-not $pf) {
    $failList += 'preflight: GET failed'
} else {
    foreach ($k in $expectedKeys) {
        if (-not (Test-JsonField $pf ".".$k $true)) {
            $failList += "preflight: key '$k' missing or null"
        }
    }
    if ($failList.Count -eq 0) {
        Write-Ok "preflight: 11 keys present"
    }
}

# 8.2 /api/v1/agent/easel/status：200 + data 非空
$es = Invoke-JsonGet "$base_url/api/v1/agent/easel/status"
if (-not $es) {
    $failList += 'easel/status: GET failed'
} elseif (-not (Test-JsonField $es '.data' $true)) {
    $failList += 'easel/status: data missing or null'
} else {
    Write-Ok 'easel/status: 200 + data'
}

# 8.3 /api/v1/agent/easel/update/status：200 + state + settings
$us = Invoke-JsonGet "$base_url/api/v1/agent/easel/update/status"
if (-not $us) {
    $failList += 'easel/update/status: GET failed'
} elseif (-not (Test-JsonField $us '.data' $true)) {
    $failList += 'easel/update/status: data missing'
} elseif (-not (Test-JsonField $us '.data.state' $false) -or -not (Test-JsonField $us '.data.settings' $false)) {
    $failList += 'easel/update/status: data.state or data.settings missing'
} else {
    Write-Ok 'easel/update/status: 200 + state/settings'
}

# 8.4 /api/v1/system/health-check：200 + preflight 字段
$hc = Invoke-JsonGet "$base_url/api/v1/system/health-check"
if (-not $hc) {
    $failList += 'health-check: GET failed'
} elseif (-not (Test-JsonField $hc '.preflight' $true)) {
    $failList += 'health-check: preflight missing'
} elseif (-not (Test-JsonField $hc '.status' $false)) {
    $failList += 'health-check: status missing'
} else {
    Write-Ok 'health-check: 200 + preflight'
}

# 8.5 preflight.redis.reachable 硬断言 ----------------------------------
# 只收紧 redis 组件（persona_api/hermes 等允许 False；但 redis 是打包必备）。
# 注意：preflight 的 _check_redis 只做 socket.connect_ex（TCP），不经过
# redis-py。因此"TCP 通但 redis-py 与 Redis 版本不兼容"的假阳性必须由
# 8.6 的 end-to-end PING 兜住。
if ($pf -and $pf.PSObject.Properties.Name -contains 'redis') {
    $rc = $pf.redis
    if (-not ($rc -is [System.Collections.IDictionary])) {
        $failList += "preflight.redis must be a dict; got $($rc.GetType().Name)"
    } else {
        $reachable = $null; $urlStr = ''; $reason = ''
        if ($rc.Contains('reachable')) { $reachable = $rc['reachable'] }
        if ($rc.Contains('url'))       { $urlStr    = "$($rc['url'])" }
        if ($rc.Contains('reason'))    { $reason    = "$($rc['reason'])" }
        if ($reachable -ne $true) {
            $failList += ("preflight.redis.reachable != True (url={0} reason={1})" -f $urlStr, $reason)
        } else {
            Write-Ok ("preflight.redis.reachable=True (url={0})" -f $urlStr)
        }
        $cc = $null
        if ($pf.PSObject.Properties.Name -contains 'celery' -and $pf.celery -is [System.Collections.IDictionary]) {
            $cc = $pf.celery
        }
        if ($cc -and $cc.Contains('broker') -and "$($cc['broker'])".Trim() -ne '') {
            $celReachable = $null
            if ($cc.Contains('reachable')) { $celReachable = $cc['reachable'] }
            if ($celReachable -ne $true) {
                $failList += ("preflight.celery.reachable != True (broker={0} reason={1})" -f $cc['broker'], $cc['reason'])
            }
        }
    }
}

# 8.6 用产物自带 prismenv\Scripts\python.exe + redis-py 做一次真实 PING ---
# 根因级断言：验证"产物里的 redis-py 能不能连上 broker"。
# 若 redis-py >= 5 与内置 Redis 5 的 RESP3/HELLO 不兼容，此断言会
# 报 'unknown command HELLO' 并硬失败，不再假阳性通过。
$pkgPython = Join-Path $installDir 'prismenv\Scripts\python.exe'
if (-not (Test-Path $pkgPython)) {
    $failList += "packaged python missing: $pkgPython"
} else {
    $redisUrl = 'redis://localhost:6379/0'
    if ($pf -and $pf.PSObject.Properties.Name -contains 'redis' -and $pf.redis -is [System.Collections.IDictionary] -and "$($pf.redis['url'])".Trim() -ne '') {
        $redisUrl = "$($pf.redis['url'])"
    }

    $pingCode = @"
import os, sys, redis as r
from urllib.parse import urlparse
u = os.environ.get('LAOMA_REDIS_PING_URL') or 'redis://localhost:6379/0'
p = urlparse(u)
c = r.Redis(host=(p.hostname or 'localhost'), port=(p.port or 6379), db=((p.path or '/0').lstrip('/') or '0'), socket_connect_timeout=3, socket_timeout=3)
try:
    ok = bool(c.ping())
    v = (c.info('server').get('redis_version') or '?')
    print('PING_OK redis_version=' + str(v))
except Exception as e:
    sys.stdout.write('PING_FAIL ' + type(e).__name__ + ': ' + str(e))
    sys.exit(2)
"@
    $pingEnv = New-Object System.Collections.Generic.Dictionary[string, string]
    foreach ($kv in (Get-ChildItem Env:)) { $pingEnv[$kv.Name] = $kv.Value }
    $pingEnv['LAOMA_REDIS_PING_URL']    = $redisUrl
    $pingEnv['PYTHONDONTWRITEBYTECODE'] = '1'

    $pingProc = New-Object System.Diagnostics.Process
    $pingPsi  = New-Object System.Diagnostics.ProcessStartInfo
    $pingPsi.FileName                = $pkgPython
    $pingPsi.Arguments               = "-c `"$pingCode`""
    $pingPsi.WorkingDirectory        = $installDir
    $pingPsi.UseShellExecute         = $false
    $pingPsi.CreateNoWindow          = $true
    $pingPsi.RedirectStandardOutput  = $true
    $pingPsi.RedirectStandardError   = $true
    $pingPsi.StandardOutputEncoding  = [System.Text.Encoding]::UTF8
    $pingPsi.StandardErrorEncoding   = [System.Text.Encoding]::UTF8
    $pingPsi.EnvironmentVariables    = $pingEnv
    $pingProc.StartInfo = $pingPsi
    $pingOut = ''; $pingErr = ''; $pingRc = -1
    try {
        $pingProc.Start() | Out-Null
        $pingOut = $pingProc.StandardOutput.ReadToEnd()
        $pingErr = $pingProc.StandardError.ReadToEnd()
        $pingProc.WaitForExit(15000)
        $pingRc  = $pingProc.ExitCode
    } catch {
        $pingErr = $_.Exception.Message
    }
    if ($pingRc -ne 0) {
        $failList += ("redis-py PING failed rc={0} url={1} stdout={2} stderr={3}" -f $pingRc, $redisUrl, $pingOut.Trim(), $pingErr.Trim())
        Write-Bad 'HARD FAIL: packaged redis-py 无法对内置 Redis PING。'
        Write-Bad ('  python : ' + $pkgPython)
        Write-Bad ('  url    : ' + $redisUrl)
        Write-Bad ('  stdout : ' + $pingOut.Trim())
        Write-Bad ('  stderr : ' + $pingErr.Trim())
        Write-Bad '  diag   : 若上面出现 unknown command HELLO，'
        Write-Bad '           即产物里 redis-py >= 5 与内置 Redis 5 的 RESP3 握手不兼容，'
        Write-Bad '           Celery 永远连不上 broker。'
        Write-Bad '           修复：requirements.txt 把 redis 版本 pin 到 <5（例如 redis==4.6.0）后重打包。'
    } else {
        Write-Ok ('packaged redis-py PING ok: ' + $pingOut.Trim())
    }
}

# 8.7 校验产物里 redis-py 主版本 < 5（防御打错依赖，直接给出明确失败信息）----
if (Test-Path $pkgPython) {
    $verProc = New-Object System.Diagnostics.Process
    $verPsi  = New-Object System.Diagnostics.ProcessStartInfo
    $verPsi.FileName                = $pkgPython
    $verPsi.Arguments               = '-c "import redis,sys;sys.stdout.write(redis.__version__)"'
    $verPsi.WorkingDirectory        = $installDir
    $verPsi.UseShellExecute         = $false
    $verPsi.CreateNoWindow          = $true
    $verPsi.RedirectStandardOutput  = $true
    $verPsi.RedirectStandardError   = $true
    $verPsi.StandardOutputEncoding  = [System.Text.Encoding]::UTF8
    $verPsi.StandardErrorEncoding   = [System.Text.Encoding]::UTF8
    $verProc.StartInfo = $verPsi
    $redisPyVer = ''
    try {
        $verProc.Start() | Out-Null
        $redisPyVer = ($verProc.StandardOutput.ReadToEnd()).Trim()
        $verProc.StandardError.ReadToEnd() | Out-Null
        $verProc.WaitForExit(15000) | Out-Null
    } catch {
        $redisPyVer = ''
    }
    if ($redisPyVer -match '^(\d+)') {
        $major = [int]$Matches[1]
        if ($major -ge 5) {
            $failList += ("packaged redis-py major=$major (>=5). Will break against bundled Redis 5 via RESP3 HELLO")
            Write-Bad ('HARD FAIL: packaged redis-py major=' + $major + ' (redis.__version__=' + $redisPyVer + ').')
            Write-Bad '           It will send HELLO to the bundled Redis 5, causing unknown command HELLO'
            Write-Bad '           and Celery will never connect to the broker.'
            Write-Bad '           Fix: pin redis<5 in requirements.txt and rebuild.'
        } else {
            Write-Ok ('packaged redis-py version=' + $redisPyVer + ' (major=' + $major + ' <5)')
        }
    } else {
        Write-Warn ('can''t read packaged redis-py version: ' + $redisPyVer)
    }
}

# 9. (可选) 前端设置页 Easel 卡片验证 --------------------------------------
# 依赖前端渲染 + 浏览器自动化，脚本内不实现；如 CI 需要可用 Playwright 单独接入。
# 参见 scripts/tests/integration_test.py 中 test_settings_page 占位说明。
Write-Step '(skipped) 前端 Easel 卡片视觉验证需要 Playwright + 图形会话，本脚本不覆盖'

# 10. 汇总 ----------------------------------------------------------------
if ($failList.Count -gt 0) {
    $Script:FailReason = ($failList -join ' | ')
    Write-Bad "FAIL: $Script:FailReason"
    Clean-Exit 1
}

Write-Ok "all endpoints verified"
Clean-Exit 0
