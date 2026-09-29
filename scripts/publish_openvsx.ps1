<#
.SYNOPSIS
  Publish the Cursor extension (release\cursor-usage-<version>.vsix) to Open VSX,
  the marketplace Cursor installs extensions from.

.DESCRIPTION
  Needs an Open VSX access token (open-vsx.org > Settings > Access Tokens) from an
  account that has signed the Eclipse publisher agreement. The token is read from
  $env:OVSX_PAT or prompted for without echo; it is only passed to the ovsx child
  process through the environment and never written to disk.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\publish_openvsx.ps1

.EXAMPLE
  # Fetch the ovsx CLI through a mirror for this run only (npm config is not changed).
  powershell -ExecutionPolicy Bypass -File .\scripts\publish_openvsx.ps1 -NpmRegistry https://registry.npmmirror.com
#>
param(
    [string]$Namespace = "qinvnb",
    [string]$NpmRegistry = ""
)
$npxArgs = @("--yes")
if ($NpmRegistry) { $npxArgs += "--registry=$NpmRegistry" }

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$manifest = Get-Content (Join-Path $root "packages\extension\package.json") -Raw | ConvertFrom-Json
$vsix = Join-Path $root "release\cursor-usage-$($manifest.version).vsix"
if (-not (Test-Path $vsix)) {
    Write-Host "Building $vsix ..."
    npm run build
    npm run package:extension
}

$token = $env:OVSX_PAT
if (-not $token) {
    $secure = Read-Host "Open VSX access token (input hidden)" -AsSecureString
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}
if (-not $token) { throw "No token given." }

$previous = $env:OVSX_PAT
$env:OVSX_PAT = $token
try {
    $exists = $true
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 "https://open-vsx.org/api/$Namespace" | Out-Null
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -eq 404) { $exists = $false } else { throw }
    }
    if (-not $exists) {
        Write-Host "Creating namespace '$Namespace' ..."
        npx @npxArgs ovsx create-namespace $Namespace
        if ($LASTEXITCODE -ne 0) { throw "create-namespace failed" }
    }
    Write-Host "Publishing $(Split-Path $vsix -Leaf) ..."
    npx @npxArgs ovsx publish $vsix
    if ($LASTEXITCODE -ne 0) { throw "publish failed" }
    Write-Host ""
    Write-Host "Published: https://open-vsx.org/extension/$Namespace/$($manifest.name)"
} finally {
    $env:OVSX_PAT = $previous
}
