param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function Assert-ReleasePython {
    param([string]$PythonCommand)

    $Identity = & $PythonCommand -c "import struct, sys; print(f'{sys.implementation.name}|{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{struct.calcsize(chr(80)) * 8}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect release Python: $PythonCommand"
    }
    $Actual = ($Identity | Out-String).Trim()
    if ($Actual -ne "cpython|3.13.15|64") {
        throw "Windows sidecar releases require CPython 3.13.15 x64; got $Actual"
    }
}

Assert-ReleasePython -PythonCommand $Python

$Root = Split-Path -Parent $PSScriptRoot
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $CargoBin) {
    $env:PATH = "$CargoBin;$env:PATH"
}
$NsisDir = Join-Path $env:LOCALAPPDATA "tauri-tools\nsis-3.11"
$NsisExe = Join-Path $NsisDir "makensis.exe"
$NsisZip = Join-Path $env:TEMP "nsis-3.11.zip"
$NsisUtilsDll = Join-Path $env:TEMP "nsis_tauri_utils.dll"
$NsisZipSha256 = "c7d27f780ddb6cffb4730138cd1591e841f4b7edb155856901cdf5f214394fa1"
$NsisUtilsSha256 = "5ba143b5db4a87d32d6e7802e033330aae56cbceabe0d1e3ba41948385ad4709"
$MirrorRoot = Join-Path $env:TEMP "tauri-bundler-mirror"

function Get-ReleaseVersion {
    $ManifestPath = Join-Path $Root "desktop\src-tauri\Cargo.toml"
    $MetadataJson = & cargo metadata --locked --format-version 1 --no-deps --manifest-path $ManifestPath
    if ($LASTEXITCODE -ne 0) {
        throw "cargo metadata failed with exit code $LASTEXITCODE"
    }
    $Metadata = $MetadataJson | ConvertFrom-Json
    $Package = $Metadata.packages | Where-Object { $_.name -eq "bilibilicrawler_desktop" } | Select-Object -First 1
    if (-not $Package -or $Package.version -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') {
        throw "Invalid release version in Cargo.toml: $($Package.version)"
    }
    return $Package.version
}

function Ensure-Download {
    param(
        [string]$Url,
        [string]$Output,
        [string]$Repo,
        [string]$Tag,
        [string]$Pattern,
        [string]$ExpectedSha256
    )

    if ((Test-Path $Output) -and
        ((Get-FileHash -Algorithm SHA256 -LiteralPath $Output).Hash -ieq $ExpectedSha256)) {
        return
    }
    if (Test-Path $Output) {
        Remove-Item -LiteralPath $Output -Force
    }

    & curl.exe -L --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 -o $Output $Url
    $CurlValid = ($LASTEXITCODE -eq 0) -and (Test-Path $Output) -and
        ((Get-FileHash -Algorithm SHA256 -LiteralPath $Output).Hash -ieq $ExpectedSha256)
    if (-not $CurlValid -and (Get-Command gh -ErrorAction SilentlyContinue)) {
        if (Test-Path $Output) {
            Remove-Item -LiteralPath $Output -Force
        }
        gh release download $Tag --repo $Repo --pattern $Pattern --dir (Split-Path -Parent $Output) --clobber
    }
    if ((-not (Test-Path $Output)) -or
        ((Get-FileHash -Algorithm SHA256 -LiteralPath $Output).Hash -ine $ExpectedSha256)) {
        throw "Failed to obtain verified bundle tool: $Url"
    }
}

function Get-FreeTcpPort {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $Listener.Start()
        return ([System.Net.IPEndPoint]$Listener.LocalEndpoint).Port
    } finally {
        $Listener.Stop()
    }
}

function Assert-MirrorAsset {
    param(
        [string]$Url,
        [string]$ExpectedSha256,
        [string]$ProbePath
    )

    if (Test-Path $ProbePath) {
        Remove-Item -LiteralPath $ProbePath -Force
    }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $ProbePath
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ProbePath).Hash -ine $ExpectedSha256) {
            throw "Local mirror returned an unexpected file: $Url"
        }
    } finally {
        if (Test-Path $ProbePath) {
            Remove-Item -LiteralPath $ProbePath -Force
        }
    }
}

$ReleaseVersion = Get-ReleaseVersion
Write-Host "Release version verified: $ReleaseVersion"

$NsisUrl = "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip"
Ensure-Download -Url $NsisUrl -Output $NsisZip -Repo "tauri-apps/binary-releases" -Tag "nsis-3.11" -Pattern "nsis-3.11.zip" -ExpectedSha256 $NsisZipSha256
$ExtractRoot = Split-Path -Parent $NsisDir
New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null
Expand-Archive -LiteralPath $NsisZip -DestinationPath $ExtractRoot -Force
if (Test-Path $NsisExe) {
    $env:PATH = "$NsisDir;$env:PATH"
}
$NsisUtilsUrl = "https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
Ensure-Download -Url $NsisUtilsUrl -Output $NsisUtilsDll -Repo "tauri-apps/nsis-tauri-utils" -Tag "nsis_tauri_utils-v0.5.3" -Pattern "nsis_tauri_utils.dll" -ExpectedSha256 $NsisUtilsSha256

New-Item -ItemType Directory -Force -Path (Join-Path $MirrorRoot "tauri-apps\binary-releases\releases\download\nsis-3.11") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $MirrorRoot "tauri-apps\nsis-tauri-utils\releases\download\nsis_tauri_utils-v0.5.3") | Out-Null
if (Test-Path $NsisZip) {
    Copy-Item -LiteralPath $NsisZip -Destination (Join-Path $MirrorRoot "tauri-apps\binary-releases\releases\download\nsis-3.11\nsis-3.11.zip") -Force
}
Copy-Item -LiteralPath $NsisUtilsDll -Destination (Join-Path $MirrorRoot "tauri-apps\nsis-tauri-utils\releases\download\nsis_tauri_utils-v0.5.3\nsis_tauri_utils.dll") -Force
$MirrorPort = Get-FreeTcpPort
$QuotedMirrorRoot = '"' + $MirrorRoot.Replace('"', '\"') + '"'
$MirrorProcess = Start-Process -FilePath $Python -ArgumentList @("-m", "http.server", $MirrorPort, "--bind", "127.0.0.1", "--directory", $QuotedMirrorRoot) -WindowStyle Hidden -PassThru
$LocationPushed = $false
$HadMirrorEnvironment = Test-Path Env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE
$PreviousMirrorEnvironment = $env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE
try {
    Start-Sleep -Milliseconds 500
    if ($MirrorProcess.HasExited) {
        throw "Local bundle mirror failed to start (exit code $($MirrorProcess.ExitCode))"
    }
    $MirrorBase = "http://127.0.0.1:$MirrorPort"
    Assert-MirrorAsset -Url "$MirrorBase/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip" -ExpectedSha256 $NsisZipSha256 -ProbePath (Join-Path $env:TEMP "tauri-mirror-probe-$PID.zip")
    Assert-MirrorAsset -Url "$MirrorBase/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll" -ExpectedSha256 $NsisUtilsSha256 -ProbePath (Join-Path $env:TEMP "tauri-mirror-probe-$PID.dll")
    $env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE = "$MirrorBase/<owner>/<repo>/releases/download/<version>/<asset>"

    Push-Location $Root
    $LocationPushed = $true
    & .\scripts\build_backend.ps1 -Python $Python
    if (-not (Get-Command corepack -ErrorAction SilentlyContinue)) {
        throw "Corepack is required to run the pinned pnpm 10.28.0 toolchain"
    }
    $PnpmVersion = & corepack pnpm@10.28.0 --version
    if ($LASTEXITCODE -ne 0 -or $PnpmVersion.Trim() -ne "10.28.0") {
        throw "Unable to activate pinned pnpm 10.28.0"
    }
    & corepack pnpm@10.28.0 --dir desktop install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm install failed with exit code $LASTEXITCODE"
    }
    $BundleDir = Join-Path $Root "desktop\src-tauri\target\release\bundle\nsis"
    $RootPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $BundleDirFull = [System.IO.Path]::GetFullPath($BundleDir)
    if (-not $BundleDirFull.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean NSIS output outside the repository: $BundleDirFull"
    }
    if (Test-Path $BundleDirFull) {
        Remove-Item -LiteralPath $BundleDirFull -Recurse -Force
    }

    & corepack pnpm@10.28.0 --dir desktop tauri build --bundles nsis -- --locked
    if ($LASTEXITCODE -ne 0) {
        throw "tauri build failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path $BundleDirFull)) {
        throw "NSIS bundle directory was not created: $BundleDirFull"
    }
    $InstallerPath = Join-Path $BundleDirFull "BilibiliCrawler_${ReleaseVersion}_x64-setup.exe"
    if (-not (Test-Path $InstallerPath)) {
        throw "Expected NSIS installer was not produced: $InstallerPath"
    }
    $Target = Join-Path $BundleDirFull "BilibiliCrawler-Setup-$ReleaseVersion-x64.exe"
    Move-Item -LiteralPath $InstallerPath -Destination $Target
    Write-Host "Installer ready: $Target"
} finally {
    if ($LocationPushed) {
        Pop-Location
    }
    if ($MirrorProcess -and -not $MirrorProcess.HasExited) {
        Stop-Process -Id $MirrorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($HadMirrorEnvironment) {
        $env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE = $PreviousMirrorEnvironment
    } else {
        Remove-Item Env:TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE -ErrorAction SilentlyContinue
    }
}
