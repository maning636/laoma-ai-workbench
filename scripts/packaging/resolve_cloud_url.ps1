<#
  Resolve the cloud SaaS base URL (single source of truth).

  The value lives in the electron-builder config:
    - Pro        : desktop-electron\package.json            -> laomaCloudUrl
    - Community  : desktop-electron\package.community.json  -> extraMetadata.laomaCloudUrl

  Both the frontend build (NEXT_PUBLIC_CLOUD_URL, baked into the browser bundle)
  and the Electron runtime (CLOUD_URL / LAOMA_CLOUD_BASE_URL, read from the
  packaged package.json) resolve the same value, so the two never drift.

  Convention: the value is the cloud ROOT url, WITHOUT the "/cloud" suffix.
  Backend and frontend each prepend "/cloud" themselves.

  Prints the url on stdout. Exits non-zero when it cannot be resolved.

  NOTE: kept ASCII-only on purpose - Windows PowerShell 5.1 may read .ps1 as
  ANSI, so non-ASCII literals would be mangled.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath,

    [switch]$UseExtraMetadata
)

$ErrorActionPreference = 'Stop'

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $PSScriptRoot '..\..\desktop-electron\package.json'
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Error "cloud url config not found: $ConfigPath"
    exit 1
}

$resolved = (Resolve-Path -LiteralPath $ConfigPath).Path
$pkg = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json

if ($UseExtraMetadata) {
    $url = [string]$pkg.extraMetadata.laomaCloudUrl
} else {
    $url = [string]$pkg.laomaCloudUrl
}

$url = $url.Trim().TrimEnd('/')

if (-not $url) {
    Write-Error "laomaCloudUrl is missing in $resolved"
    exit 1
}

Write-Output $url
exit 0
