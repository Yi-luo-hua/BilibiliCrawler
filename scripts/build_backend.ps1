param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResourceDir = Join-Path $Root "desktop\src-tauri\resources\backend"
$WorkDir = Join-Path $Root "build\sidecar"
$Requirements = Join-Path $Root "requirements.txt"

New-Item -ItemType Directory -Force $ResourceDir | Out-Null

if (Test-Path $Requirements) {
    & $Python -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE"
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name sidecar `
    --hidden-import wordcloud `
    --hidden-import jieba `
    --distpath $ResourceDir `
    --workpath $WorkDir `
    --specpath $WorkDir `
    --paths $Root `
    (Join-Path $Root "backend\sidecar.py")

Write-Host "Python sidecar built at $ResourceDir"
