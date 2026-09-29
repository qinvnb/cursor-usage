# Build the Windows folder app: TypeScript core + dashboard, then PyInstaller.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$packageData = Join-Path (Get-Location) "dist\CursorUsage\data"
$dataBackup = Join-Path $env:TEMP "CursorUsage-build-data"
if (Test-Path $packageData) {
    if (Test-Path $dataBackup) { Remove-Item $dataBackup -Recurse -Force }
    Copy-Item $packageData $dataBackup -Recurse
}

npm ci --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { throw "npm ci failed ($LASTEXITCODE)" }
npm test
if ($LASTEXITCODE -ne 0) { throw "TypeScript tests failed ($LASTEXITCODE)" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Dashboard build failed ($LASTEXITCODE)" }

python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed ($LASTEXITCODE)" }
python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed ($LASTEXITCODE)" }
python -m unittest discover -s tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) { throw "Python tests failed ($LASTEXITCODE)" }
python -m PyInstaller --noconfirm CursorUsage.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
if (Test-Path $dataBackup) {
    New-Item $packageData -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $dataBackup "*") $packageData -Recurse -Force
    Remove-Item $dataBackup -Recurse -Force
}

Write-Host ""
Write-Host "Build complete: $(Join-Path (Get-Location) 'dist\CursorUsage\CursorUsage.exe')"
