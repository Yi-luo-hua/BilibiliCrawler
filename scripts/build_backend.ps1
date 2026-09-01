param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResourceDir = Join-Path $Root "desktop\src-tauri\resources\backend"
$WorkDir = Join-Path $Root "build\sidecar"
$RuntimeRequirements = Join-Path $Root "requirements-desktop.lock"
$BuildRequirements = Join-Path $Root "requirements-build.txt"
$SidecarOutput = Join-Path $ResourceDir "sidecar"

$PythonIdentity = & $Python -c "import struct, sys; print(f'{sys.implementation.name}|{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{struct.calcsize(chr(80)) * 8}')"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect release Python: $Python"
}
if ($PythonIdentity.Trim() -ne "cpython|3.13.15|64") {
    throw "Windows sidecar releases require CPython 3.13.15 x64; got $($PythonIdentity.Trim())"
}

New-Item -ItemType Directory -Force $ResourceDir | Out-Null

if (-not (Test-Path $RuntimeRequirements)) {
    throw "Missing locked desktop requirements: $RuntimeRequirements"
}
if (-not (Test-Path $BuildRequirements)) {
    throw "Missing locked build requirements: $BuildRequirements"
}

& $Python -m pip install --require-hashes -r $RuntimeRequirements -r $BuildRequirements
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}
& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "pip check failed with exit code $LASTEXITCODE"
}

$RootPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
$SidecarOutputFull = [System.IO.Path]::GetFullPath($SidecarOutput)
if (-not $SidecarOutputFull.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean sidecar output outside the repository: $SidecarOutputFull"
}
if (Test-Path $SidecarOutputFull) {
    Remove-Item -LiteralPath $SidecarOutputFull -Recurse -Force
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name sidecar `
    --hidden-import wordcloud `
    --hidden-import jieba `
    --collect-data bilibili_crawler.resources `
    --distpath $ResourceDir `
    --workpath $WorkDir `
    --specpath $WorkDir `
    --paths $Root `
    (Join-Path $Root "backend\sidecar.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$SidecarExe = Join-Path $SidecarOutputFull "sidecar.exe"
if (-not (Test-Path $SidecarExe)) {
    throw "PyInstaller completed without producing: $SidecarExe"
}

Write-Host "Python sidecar built at $SidecarOutputFull"
