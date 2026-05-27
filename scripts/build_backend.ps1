param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResourceDir = Join-Path $Root "desktop\src-tauri\resources\backend"
$WorkDir = Join-Path $Root "build\sidecar"

New-Item -ItemType Directory -Force $ResourceDir | Out-Null
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name sidecar `
    --distpath $ResourceDir `
    --workpath $WorkDir `
    --specpath $WorkDir `
    --paths $Root `
    (Join-Path $Root "backend\sidecar.py")

Write-Host "Python sidecar built at $ResourceDir"
