# Build Windows EXE for Cursor Usage dashboard
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$packageData = Join-Path (Get-Location) "dist\CursorUsage\data"
$dataBackup = Join-Path $env:TEMP "CursorUsage-build-data"
if (Test-Path $packageData) {
    if (Test-Path $dataBackup) { Remove-Item $dataBackup -Recurse -Force }
    Copy-Item $packageData $dataBackup -Recurse
}

python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed ($LASTEXITCODE)" }
python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed ($LASTEXITCODE)" }
python -m unittest discover -s tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) { throw "Tests failed ($LASTEXITCODE)" }
python -m PyInstaller --noconfirm CursorUsage.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
if (Test-Path $dataBackup) {
    New-Item $packageData -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $dataBackup "*") $packageData -Recurse -Force
    Remove-Item $dataBackup -Recurse -Force
}

Write-Host ""
Write-Host "Build complete: $(Join-Path (Get-Location) 'dist\CursorUsage\CursorUsage.exe')"
Write-Host "Cursor must be signed in before launch."
