[CmdletBinding()]
param(
  [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path 'backend\.venv\Scripts\python.exe')) {
  throw 'Missing backend virtual environment. Follow the Backend setup in README first.'
}

& backend\.venv\Scripts\python.exe -c "import fastapi, httpx, psutil, pydantic_settings, PyInstaller"
if ($LASTEXITCODE -ne 0) {
  throw 'Missing build dependencies. Run: backend\.venv\Scripts\python -m pip install -e \".\backend[dev]\" pyinstaller'
}
Push-Location frontend
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed; resolve the dependency installation error before packaging.' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
Pop-Location

& backend\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --noconsole --name 'MeloForge Studio' --paths backend --add-data 'frontend\dist;frontend\dist' --add-data '.env.example;.' desktop\launcher.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller bundle failed.' }

if ($SkipInstaller) {
  Write-Host 'Portable Windows build created in dist\MeloForge Studio'
  exit 0
}

$iscc = @(
  "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
  Write-Warning 'Inno Setup 6 was not found. The portable build is ready in dist\MeloForge Studio. Install Inno Setup 6 and rerun this script to create the setup.exe.'
  exit 0
}

& $iscc desktop\MeloForge-Studio.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installer compilation failed.' }
Write-Host 'Installer created in release\MeloForge-Studio-Setup.exe'
