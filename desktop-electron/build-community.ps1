<#
.SYNOPSIS
  Prism-Fusion · 老马AI工作台 Community 版打包脚本

.DESCRIPTION
  Open Core 开源版(AGPL-3.0)独立打包脚本:
    - 应用名: 老马AI工作台 Community
    - 版本: 1.1.0-community
    - AppId: com.laomai.workbench.community (与 Pro 版共存)
    - AI 模式: local_key(自配 LLM key)
    - 不含 Hermes Agent / Hermes WebUI (Pro 付费内核)
    - 不含云端 prompt 配置
    - 输出到 desktop-electron/dist-out/community/v{buildNumber}/

  与 Pro 版打包脚本(scripts/packaging/build-package.bat)的关系:
    - 完全独立运行,不覆盖/不依赖 Pro 版产物
    - 复用同一份 prism_backend / prism_frontend 源码
    - 复用 requirements.txt 但跳过 Hermes 相关依赖
    - 用 package.community.json 配置 electron-builder(而非 package.json)

.PARAMETER BuildNumber
  版本号后缀,默认读取 scripts/packaging/build-version-community.json 中的 buildNumber

.PARAMETER SkipFrontend
  跳过 Next.js 前端构建(当 .next/standalone 已存在时加速重复打包)

.PARAMETER SkipBackend
  跳过 PyInstaller 后端服务打包(当 dist/services 已存在时)

.PARAMETER SkipPrismenv
  跳过 prismenv 依赖安装(假设已就绪,加速重复打包)

.PARAMETER OutputRoot
  覆盖输出根目录,默认 desktop-electron/dist-out/community

.PARAMETER KeepWinUnpacked
  保留 win-unpacked 目录,便于快速测试不重装

.PARAMETER SignInstaller
  启用签名(需预先配置 certificateFile / certificatePassword)

.PARAMETER AutoYes
  非交互模式:自动确认覆盖,不 pause

.EXAMPLE
  .\build-community.ps1
  # 完整打包,输出到 desktop-electron/dist-out/community/v1/

.EXAMPLE
  .\build-community.ps1 -SkipFrontend -SkipPrismenv -BuildNumber 2
  # 加速重打包:假设前端和 prismenv 已就绪,只重跑后端 + electron

.EXAMPLE
  .\build-community.ps1 -AutoYes -SkipFrontend -SkipBackend
  # CI 快速构建(假设 dist/services 和 .next/standalone 均已就绪)
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$BuildNumber,

    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SkipPrismenv,

    [Parameter(Mandatory = $false)]
    [string]$OutputRoot,

    [switch]$KeepWinUnpacked,
    [switch]$SignInstaller,
    [switch]$AutoYes
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ---------------------------------------------------------------
# 0. 路径与常量
# ---------------------------------------------------------------
$CommunityEdition = "community"
$EditionColor = "Cyan"
$VersionTag = "1.1.0-community"

$DesktopDir = $PSScriptRoot
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionJson = Join-Path $ProjectRoot "scripts\packaging\build-version-community.json"
$PackageConfig = Join-Path $DesktopDir "package.community.json"
$InnoScript = Join-Path $DesktopDir "installer-community.iss"

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $DesktopDir "dist-out\community"
}

# 读取版本
$buildVersion = 1
$releaseBaseVersion = "1.1.0"
if (Test-Path -LiteralPath $VersionJson) {
    $v = Get-Content -LiteralPath $VersionJson -Raw | ConvertFrom-Json
    $releaseBaseVersion = $v.version
    if ($v.buildNumber -and [int]$v.buildNumber -gt 0) {
        $buildVersion = [int]$v.buildNumber
    }
}
if ($BuildNumber -and $BuildNumber -match '^\d+$') {
    $buildVersion = [int]$BuildNumber
}

$finalVersion = "$releaseBaseVersion.$buildVersion"
$semanticVersion = "$releaseBaseVersion-community"

Write-Host ""
Write-Host "================================================================" -ForegroundColor $EditionColor
Write-Host "  老马AI工作台 Community · 打包" -ForegroundColor $EditionColor
Write-Host "  Open Core · AGPL-3.0 · Edition=$CommunityEdition" -ForegroundColor $EditionColor
Write-Host "================================================================" -ForegroundColor $EditionColor
Write-Host ""
Write-Host "  Project root      : $ProjectRoot"
Write-Host "  Desktop dir       : $DesktopDir"
Write-Host "  Edition           : $CommunityEdition"
Write-Host "  Base version      : $releaseBaseVersion"
Write-Host "  Build number      : $buildVersion"
Write-Host "  Installer version : $finalVersion"
Write-Host "  Semantic version  : $semanticVersion"
Write-Host "  Output root       : $OutputRoot"
Write-Host "  Output dir        : $(Join-Path $OutputRoot ('v' + $buildVersion))"
Write-Host ""

# 前置文件校验
$preChecks = @(
    @{ File = $PackageConfig; Desc = "Electron community 配置" },
    @{ File = $InnoScript;    Desc = "Inno Setup community 脚本" },
    @{ File = (Join-Path $ProjectRoot "requirements.txt"); Desc = "Python requirements" },
    @{ File = (Join-Path $ProjectRoot "prism_backend");    Desc = "prism_backend 源码" },
    @{ File = (Join-Path $ProjectRoot "prism_frontend");   Desc = "prism_frontend 源码" },
    @{ File = (Join-Path $ProjectRoot ".env.example");     Desc = "Community .env.example" }
)
foreach ($p in $preChecks) {
    if (-not (Test-Path -LiteralPath $p.File)) {
        Write-Error "[PRE-CHECK FAIL] $($p.Desc) 缺失: $($p.File)"
    }
    Write-Host "  [OK] $($p.Desc)"
}

# ---------------------------------------------------------------
# 1. 停止占用 Community 安装产物的进程
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[1/8] 停止可能占用 Community 产物的进程..." -ForegroundColor Yellow

$blockProcesses = @("LaomaAICommunity.exe", "supervisor.exe", "redis-server.exe", "python.exe")
foreach ($name in $blockProcesses) {
    try {
        Get-Process -Name $name -ErrorAction Stop | ForEach-Object {
            $path = $_.Path
            $shouldStop = $false
            if ($path) {
                if ($path -like '*\dist-out\community\*' -or
                    $path -like '*\dist-community\*' -or
                    $path -like '*\dist\services\*') {
                    $shouldStop = $true
                }
            }
            if ($shouldStop) {
                Write-Host "  停止 $name (PID=$($_.Id)) from $path"
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        # 进程不存在,忽略
    }
}
Write-Host "  [OK] 进程检查完成"

# ---------------------------------------------------------------
# 2. 清理旧产物(仅 Community 版目录,不动 Pro 版 dist-build/dist-out)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[2/8] 清理旧 Community 产物..." -ForegroundColor Yellow

$targetsToClean = @(
    (Join-Path $DesktopDir "dist-community"),
    $OutputRoot
)
foreach ($target in $targetsToClean) {
    if (Test-Path -LiteralPath $target) {
        Write-Host "  清理: $target"
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not $SkipBackend) {
    $servicesDist = Join-Path $ProjectRoot "dist\services"
    if (Test-Path -LiteralPath $servicesDist) {
        Write-Host "  清理: $servicesDist"
        Remove-Item -LiteralPath $servicesDist -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "  [OK] 清理完成"

# ---------------------------------------------------------------
# 3. 准备 prismenv(Community 版)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[3/8] 准备 prismenv(Community 依赖)..." -ForegroundColor Yellow

$prismenvDir = Join-Path $ProjectRoot "prismenv"
$prismenvPython = Join-Path $prismenvDir "Scripts\python.exe"
$prismenvReady = Join-Path $prismenvDir ".community-ready"

if (-not $SkipPrismenv) {
    if (-not (Test-Path -LiteralPath $prismenvPython)) {
        Write-Host "  创建 prismenv virtual environment..."
        python -m venv $prismenvDir
        if ($LASTEXITCODE -ne 0) { throw "创建 prismenv 失败" }
    }

    Write-Host "  升级 pip..."
    & $prismenvPython -m pip install --upgrade pip -q
    if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }

    Write-Host "  安装 requirements.txt..."
    & $prismenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "安装 requirements.txt 失败" }

    Write-Host "  卸载 playwright(避免与 patchright 冲突)..."
    & $prismenvPython -m pip uninstall -y playwright -q
    if ($LASTEXITCODE -ne 0) { throw "卸载 playwright 失败" }

    Write-Host "  安装打包工具..."
    & $prismenvPython -m pip install pyinstaller psutil "patchright==1.59.1" -q
    if ($LASTEXITCODE -ne 0) { throw "安装打包工具失败" }

    $patchrightVersion = & $prismenvPython -c "import importlib.metadata; print(importlib.metadata.version('patchright'))"
    if ($LASTEXITCODE -ne 0 -or $patchrightVersion -ne "1.59.1") {
        throw "patchright 版本不符: $patchrightVersion (期望 1.59.1)"
    }

    New-Item -ItemType File -Path $prismenvReady -Force | Out-Null
    Write-Host "  [OK] prismenv ready"
} else {
    if (-not (Test-Path -LiteralPath $prismenvPython)) {
        throw "SkipPrismenv 已启用,但 prismenv python 不存在: $prismenvPython"
    }
    Write-Host "  [SKIP] prismenv 已就绪: $prismenvPython"
}

Write-Host "  [SKIP] Hermes Agent / WebUI (Pro 版专属,Community 版不打包)" -ForegroundColor DarkGray

# ---------------------------------------------------------------
# 4. 后端服务打包(PyInstaller)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[4/8] 后端服务打包(PyInstaller)..." -ForegroundColor Yellow

$buildServicesScript = Join-Path $ProjectRoot "scripts\packaging\build_services.ps1"
if (-not $SkipBackend) {
    if (-not (Test-Path -LiteralPath $buildServicesScript)) {
        throw "缺少 build_services.ps1: $buildServicesScript"
    }

    $env:PACKAGING_PYTHON = $prismenvPython
    $env:SKIP_OBFUSCATE = "1"

    Write-Host "  调用: $buildServicesScript"
    Write-Host "  PACKAGING_PYTHON=$prismenvPython"
    Write-Host "  SKIP_OBFUSCATE=1 (Community 版不混淆)"
    & $buildServicesScript
    if ($LASTEXITCODE -ne 0) { throw "build_services.ps1 打包失败" }

    Remove-Item Env:\PACKAGING_PYTHON -ErrorAction SilentlyContinue
    Remove-Item Env:\SKIP_OBFUSCATE -ErrorAction SilentlyContinue

    $servicesDist = Join-Path $ProjectRoot "dist\services"
    if (-not (Test-Path -LiteralPath $servicesDist)) {
        throw "PyInstaller 输出缺失: $servicesDist"
    }
    Write-Host "  [OK] 后端服务已打包"
} else {
    $servicesDist = Join-Path $ProjectRoot "dist\services"
    if (-not (Test-Path -LiteralPath $servicesDist)) {
        throw "SkipBackend 已启用,但 dist/services 不存在"
    }
    Write-Host "  [SKIP] 后端服务已就绪: $servicesDist"
}

# ---------------------------------------------------------------
# 5. 前端构建(Next.js standalone)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[5/8] 前端构建(Next.js standalone)..." -ForegroundColor Yellow

$frontendDir = Join-Path $ProjectRoot "prism_frontend"
$frontendStandalone = Join-Path $frontendDir ".next\standalone\server.js"

if (-not $SkipFrontend) {
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "package.json"))) {
        throw "prism_frontend 目录缺失: $frontendDir"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
        throw "prism_frontend node_modules 缺失。请先: cd $frontendDir; npm install"
    }

    Push-Location $frontendDir
    try {
        Write-Host "  执行: npm run build"
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端 npm run build 失败" }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $frontendStandalone)) {
        throw "Next.js standalone 输出缺失: $frontendStandalone"
    }
    Write-Host "  [OK] 前端已构建: $frontendStandalone"
} else {
    if (-not (Test-Path -LiteralPath $frontendStandalone)) {
        throw "SkipFrontend 已启用,但 .next/standalone/server.js 不存在"
    }
    Write-Host "  [SKIP] 前端已就绪: $frontendStandalone"
}

# ---------------------------------------------------------------
# 6. Electron 打包(Community 版配置)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[6/8] Electron 打包(electron-builder --dir)..." -ForegroundColor Yellow

Push-Location $DesktopDir
try {
    $ebCli = Join-Path $DesktopDir "node_modules\electron-builder\cli.js"
    $electronOutputDir = Join-Path $DesktopDir "dist-community"

    if (-not (Test-Path -LiteralPath $ebCli)) {
        throw "node_modules\electron-builder\cli.js 缺失。请先: cd $DesktopDir; npm install"
    }

    # 读取 Community 配置元数据,通过 extraMetadata 显式覆盖,
    # 保证打包产物 package.json 反映 Community 元数据(而非 cwd 下的 Pro 版 package.json)
    $cfgJson = Get-Content -LiteralPath $PackageConfig -Raw | ConvertFrom-Json
    $meta = $cfgJson.extraMetadata
    $appMetaArgs = @(
        "--config.extraMetadata.name=$($meta.name)",
        "--config.extraMetadata.version=$semanticVersion",
        "--config.extraMetadata.main=$($meta.main)",
        "--config.extraMetadata.description=$($meta.description)",
        "--config.extraMetadata.author=$($meta.author)",
        "--config.extraMetadata.license=$($meta.license)"
    )

    $buildArgs = @("--config", $PackageConfig, "--win", "--x64", "--dir") + $appMetaArgs + @("--config.buildVersion=$finalVersion")
    Write-Host "  执行: node $ebCli $($buildArgs -join ' ')"
    node $ebCli @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "electron-builder --dir 打包失败" }

    $winUnpacked = Join-Path $electronOutputDir "win-unpacked"
    if (-not (Test-Path -LiteralPath $winUnpacked)) {
        throw "win-unpacked 未生成: $winUnpacked"
    }
    $exePath = Join-Path $winUnpacked "LaomaAICommunity.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Community 主 exe 未生成: $exePath"
    }
    Write-Host "  [OK] win-unpacked 就绪: $winUnpacked"
} finally {
    Pop-Location
}

# ---------------------------------------------------------------
# 7. 生成 NSIS 安装包
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[7/8] 生成 NSIS 安装包..." -ForegroundColor Yellow

Push-Location $DesktopDir
try {
    $ebCli = Join-Path $DesktopDir "node_modules\electron-builder\cli.js"
    $buildArgs = @("--config", $PackageConfig, "--win", "--x64") + $appMetaArgs + @("--config.buildVersion=$finalVersion")
    Write-Host "  执行: node $ebCli $($buildArgs -join ' ')"
    node $ebCli @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "electron-builder 生成 NSIS 失败" }
} finally {
    Pop-Location
}

$nsisInstallers = Get-ChildItem -LiteralPath $electronOutputDir -Filter *.exe -File -ErrorAction SilentlyContinue
if (-not $nsisInstallers -or $nsisInstallers.Count -eq 0) {
    throw "NSIS 安装包未生成"
}
$installerFile = $nsisInstallers | Select-Object -First 1
Write-Host "  [OK] NSIS 安装包: $($installerFile.Name) ($([math]::Round($installerFile.Length / 1MB, 2)) MB)"

# ---------------------------------------------------------------
# 8. 组织输出目录 + 收尾
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[8/8] 组织最终输出..." -ForegroundColor Yellow

$outputDir = Join-Path $OutputRoot ("v" + $buildVersion)
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Copy-Item -LiteralPath $installerFile.FullName -Destination $outputDir -Force
if (Test-Path -LiteralPath "$($installerFile.FullName).blockmap") {
    Copy-Item -LiteralPath "$($installerFile.FullName).blockmap" -Destination $outputDir -Force
}
if (Test-Path -LiteralPath (Join-Path $electronOutputDir "latest.yml")) {
    Copy-Item -LiteralPath (Join-Path $electronOutputDir "latest.yml") -Destination $outputDir -Force
}

if ($KeepWinUnpacked) {
    Write-Host "  保留 win-unpacked 目录..."
    $unpackedDest = Join-Path $outputDir "win-unpacked"
    if (Test-Path -LiteralPath $unpackedDest) {
        Remove-Item -LiteralPath $unpackedDest -Recurse -Force -ErrorAction SilentlyContinue
    }
    Copy-Item -LiteralPath $winUnpacked -Destination $unpackedDest -Recurse -Force
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor $EditionColor
Write-Host "  Community 版打包完成" -ForegroundColor $EditionColor
Write-Host "================================================================" -ForegroundColor $EditionColor
Write-Host ""
Write-Host "  输出目录: $outputDir"
Write-Host "  安装包:   $(Join-Path $outputDir $installerFile.Name)"
Write-Host ""
Write-Host "  版本:     $finalVersion (Semantic: $semanticVersion)"
Write-Host "  AppId:    com.laomai.workbench.community"
Write-Host "  AI_MODE:  local_key(自配 LLM key)"
Write-Host ""
Write-Host "  验证命令:"
Write-Host "    node `"$DesktopDir\scripts\verify-release-assets.mjs`" `"$outputDir`" `"$semanticVersion`""
Write-Host "    node `"$DesktopDir\scripts\finalize-windows-release.mjs`" `"$outputDir`" `"$semanticVersion`""
Write-Host ""
Write-Host "  Pro 版打包产物未受影响(保留在 dist-build / dist-out 目录)"
Write-Host ""

if (-not $AutoYes) {
    Read-Host "  按 Enter 退出"
}