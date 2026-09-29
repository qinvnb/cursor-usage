param(
    # Defaults to __version__ in cursor_usage_app/__init__.py.
    [string]$Version = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $Version) {
    $match = Select-String -Path (Join-Path $root "cursor_usage_app\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
    $Version = $match.Matches[0].Groups[1].Value
}

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_exe.ps1")
}

$source = Join-Path $root "dist\CursorUsage"
$release = Join-Path $root "release"
$stage = Join-Path $release "CursorUsage"
$archive = Join-Path $release "CursorUsage-v$Version-win-x64.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $archive) { Remove-Item $archive -Force }
New-Item $stage -ItemType Directory -Force | Out-Null

Copy-Item (Join-Path $source "*") $stage -Recurse -Force
$privateData = Join-Path $stage "data"
if (Test-Path $privateData) { Remove-Item $privateData -Recurse -Force }

Copy-Item (Join-Path $root "README.md") $stage
Copy-Item (Join-Path $root "LICENSE") $stage
Copy-Item (Join-Path $root "SECURITY.md") $stage
Copy-Item (Join-Path $root "CHANGELOG.md") $stage
New-Item (Join-Path $stage "assets") -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $root "assets\app.png") (Join-Path $stage "assets\app.png")

Compress-Archive -Path $stage -DestinationPath $archive -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

Write-Host "Release package: $archive"
Write-Host "Verified: runtime data directory was excluded."
