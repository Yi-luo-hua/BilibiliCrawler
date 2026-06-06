param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $CargoBin) {
    $env:PATH = "$CargoBin;$env:PATH"
}
$NsisDir = Join-Path $env:LOCALAPPDATA "tauri-tools\nsis-3.11"
$NsisExe = Join-Path $NsisDir "makensis.exe"
$NsisZip = Join-Path $env:TEMP "nsis-3.11.zip"
$NsisUtilsDll = Join-Path $env:TEMP "nsis_tauri_utils.dll"
$MirrorRoot = Join-Path $env:TEMP "tauri-bundler-mirror"
$MirrorPort = 18765

function Ensure-Download {
    param(
        [string]$Url,
        [string]$Output,
        [string]$Repo,
        [string]$Tag,
        [string]$Pattern
    )

    if (Test-Path $Output) {
        return
    }

    & curl.exe -L --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 -o $Output $Url
    if ((-not (Test-Path $Output)) -and (Get-Command gh -ErrorAction SilentlyContinue)) {
        gh release download $Tag --repo $Repo --pattern $Pattern --dir (Split-Path -Parent $Output) --clobber
    }
    if (-not (Test-Path $Output)) {
        throw "Failed to download required bundle tool: $Url"
    }
}

if (-not (Test-Path $NsisExe)) {
    $NsisUrl = "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip"
    Ensure-Download -Url $NsisUrl -Output $NsisZip -Repo "tauri-apps/binary-releases" -Tag "nsis-3.11" -Pattern "nsis-3.11.zip"
    $ExtractRoot = Split-Path -Parent $NsisDir
    New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null
    Expand-Archive -LiteralPath $NsisZip -DestinationPath $ExtractRoot -Force
}
if (Test-Path $NsisExe) {
    $env:PATH = "$NsisDir;$env:PATH"
}
$NsisUtilsUrl = "https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
Ensure-Download -Url $NsisUtilsUrl -Output $NsisUtilsDll -Repo "tauri-apps/nsis-tauri-utils" -Tag "nsis_tauri_utils-v0.5.3" -Pattern "nsis_tauri_utils.dll"

New-Item -ItemType Directory -Force -Path (Join-Path $MirrorRoot "tauri-apps\binary-releases\releases\download\nsis-3.11") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $MirrorRoot "tauri-apps\nsis-tauri-utils\releases\download\nsis_tauri_utils-v0.5.3") | Out-Null
if (Test-Path $NsisZip) {
    Copy-Item -LiteralPath $NsisZip -Destination (Join-Path $MirrorRoot "tauri-apps\binary-releases\releases\download\nsis-3.11\nsis-3.11.zip") -Force
}
Copy-Item -LiteralPath $NsisUtilsDll -Destination (Join-Path $MirrorRoot "tauri-apps\nsis-tauri-utils\releases\download\nsis_tauri_utils-v0.5.3\nsis_tauri_utils.dll") -Force
$MirrorProcess = Start-Process -FilePath $Python -ArgumentList @("-m", "http.server", $MirrorPort, "--bind", "127.0.0.1", "--directory", $MirrorRoot) -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1
$env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE = "http://127.0.0.1:$MirrorPort/<owner>/<repo>/releases/download/<version>/<asset>"

Push-Location $Root
try {
    & .\scripts\build_backend.ps1 -Python $Python
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        $PnpmCommand = "pnpm"
        $PnpmArgsPrefix = @()
    } else {
        corepack prepare pnpm@10.28.0 --activate
        if ($LASTEXITCODE -ne 0) {
            throw "corepack prepare failed with exit code $LASTEXITCODE"
        }
        $PnpmCommand = "corepack"
        $PnpmArgsPrefix = @("pnpm")
    }
    & $PnpmCommand @PnpmArgsPrefix --dir desktop install
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm install failed with exit code $LASTEXITCODE"
    }
    & $PnpmCommand @PnpmArgsPrefix --dir desktop tauri build --bundles nsis
    if ($LASTEXITCODE -ne 0) {
        throw "tauri build failed with exit code $LASTEXITCODE"
    }
    $BundleDir = Join-Path $Root "desktop\src-tauri\target\release\bundle\nsis"
    if (-not (Test-Path $BundleDir)) {
        throw "NSIS bundle directory was not created: $BundleDir"
    }
    $Installer = Get-ChildItem -Path $BundleDir -Filter "*.exe" -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Installer) {
        throw "No NSIS installer was produced in: $BundleDir"
    }
    $Version = (Get-Content -Raw (Join-Path $Root "desktop\package.json") | ConvertFrom-Json).version
    $Target = Join-Path $BundleDir "BilibiliCrawler-Setup-$Version-x64.exe"
    if ($Installer.FullName -ne $Target) {
        Move-Item -LiteralPath $Installer.FullName -Destination $Target -Force
    }
    Write-Host "Installer ready: $Target"
} finally {
    Pop-Location
    if ($MirrorProcess -and -not $MirrorProcess.HasExited) {
        Stop-Process -Id $MirrorProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
