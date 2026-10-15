param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

function Remove-IfExists {
    param(
        [string]$Path,
        [switch]$RecreateDirectory
    )

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    }

    if ($RecreateDirectory) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Remove-Files {
    param(
        [string]$Directory,
        [string[]]$Patterns
    )

    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }

    foreach ($pattern in $Patterns) {
        Get-ChildItem -LiteralPath $Directory -Filter $pattern -File -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
}

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
Write-Host "[prepare-release] Project root: $resolvedRoot"

$targetsToReset = @(
    @{ Path = (Join-Path $resolvedRoot "logs"); Recreate = $true },
    @{ Path = (Join-Path $resolvedRoot "prism_backend\logs"); Recreate = $true },
    @{ Path = (Join-Path $resolvedRoot "prism_backend\data\cookies"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "prism_backend\cookiesFile"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "prism_backend\fingerprints"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "prism_backend\browser_profiles"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "config\cookiesFile"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "config\browser_profiles"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "desktop-electron\dist-build"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "desktop-electron\dist-out"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "dist"); Recreate = $false },
    @{ Path = (Join-Path $resolvedRoot "dist-out"); Recreate = $false }
)

foreach ($target in $targetsToReset) {
    # dev 环境可能持有日志句柄(如 Celery worker 占用 logs/celery_fix.log),
    # 对 logs / prism_backend\logs 的清理失败只降级为 warning,不应中断发布。
    $relativeKey = $target.Path.Substring($resolvedRoot.Length).TrimStart('\', '/').Replace('\', '/')
    $isLogPath = ($relativeKey -eq 'logs') -or ($relativeKey -eq 'prism_backend/logs')
    try {
        Remove-IfExists -Path $target.Path -RecreateDirectory:$target.Recreate
    }
    catch {
        if ($isLogPath) {
            Write-Warning "[prepare-release] 清理日志目录失败(降级为 warning,继续): $($target.Path) -> $($_.Exception.Message)"
        }
        else {
            Write-Host "[prepare-release] 清理目录失败(严格): $($target.Path) -> $($_.Exception.Message)"
            throw
        }
    }
}

Remove-Files -Directory (Join-Path $resolvedRoot "prism_backend\db") -Patterns @("*.db", "*.db-*", "*.sqlite", "*.sqlite-*", "frontend_accounts_snapshot.json")
Remove-Files -Directory (Join-Path $resolvedRoot "desktop-electron") -Patterns @("*.rdb", "*.log")

Write-Host "[prepare-release] Release workspace sanitized."
