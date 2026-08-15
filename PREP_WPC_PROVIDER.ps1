param()

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Version = "1.1.2"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Resources = Join-Path $Root "resources"
$ProviderDir = Join-Path $Resources "wpc-provider"
$RuntimeDir = Join-Path $ProviderDir "runtime"
$LockFile = Join-Path $ProviderDir "WPC_RUNTIME_LOCK.txt"
$WheelDir = Join-Path $env:TEMP ("RRV-WPC-WHEELS-" + $Version)
$RuntimeDest = Join-Path $env:LOCALAPPDATA "RR-V\wpc-provider\runtime"
$MarkerDest = Join-Path $env:LOCALAPPDATA "RR-V\wpc-provider\.rrv_wpc_version"

$ExpectedPackages = @(
    "yt-dlp-getpot-wpc==1.1.2",
    "nodriver==0.50.3",
    "mss==10.2.0",
    "websockets==16.1.1",
    "deprecated==1.3.1",
    "wrapt==2.3.0"
)

$ExpectedDistInfo = @(
    "yt_dlp_getpot_wpc-1.1.2.dist-info",
    "nodriver-0.50.3.dist-info",
    "mss-10.2.0.dist-info",
    "websockets-16.1.1.dist-info",
    "deprecated-1.3.1.dist-info",
    "wrapt-2.3.0.dist-info"
)

if (-not (Test-Path $Python)) {
    throw ".venv\Scripts\python.exe is missing. Open this project in the RR-V development folder first."
}
if (-not (Test-Path $LockFile)) {
    throw "resources\wpc-provider\WPC_RUNTIME_LOCK.txt is missing."
}

$LockedPackages = @(
    Get-Content -Path $LockFile |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") }
)
if (($LockedPackages -join "`n") -ne ($ExpectedPackages -join "`n")) {
    throw "WPC runtime lock does not match the RR-V 1.0.1 tested dependency set."
}

if (Test-Path $WheelDir) {
    Remove-Item $WheelDir -Recurse -Force
}
if (Test-Path $RuntimeDir) {
    Remove-Item $RuntimeDir -Recurse -Force
}
New-Item -ItemType Directory -Path $WheelDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

Write-Host "[1/4] Downloading the locked WPC runtime for Windows CPython 3.10..."
foreach ($Package in $ExpectedPackages) {
    Write-Host ("  - " + $Package)
    & $Python -m pip download `
        --disable-pip-version-check `
        --no-deps `
        --only-binary=:all: `
        --platform win_amd64 `
        --implementation cp `
        --python-version 310 `
        --abi cp310 `
        --dest $WheelDir `
        $Package
    if ($LASTEXITCODE -ne 0) {
        throw ("WPC package download failed for " + $Package + " with exit code " + $LASTEXITCODE + ".")
    }
}

Write-Host "[2/4] Expanding provider runtime..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
Get-ChildItem -Path $WheelDir -Filter *.whl | ForEach-Object {
    [System.IO.Compression.ZipFile]::ExtractToDirectory($_.FullName, $RuntimeDir)
}

$Plugin = Join-Path $RuntimeDir "yt_dlp_plugins\extractor\getpot_wpc.py"
$NoDriver = Join-Path $RuntimeDir "nodriver\__init__.py"
if (-not (Test-Path $Plugin)) {
    throw "WPC plugin file was not created."
}
if (-not (Test-Path $NoDriver)) {
    throw "nodriver dependency was not created."
}

$ActualDistInfo = @(
    Get-ChildItem -Path $RuntimeDir -Directory -Filter *.dist-info |
        ForEach-Object { $_.Name } |
        Sort-Object
)
$ExpectedDistInfoSorted = @($ExpectedDistInfo | Sort-Object)
if (($ActualDistInfo -join "`n") -ne ($ExpectedDistInfoSorted -join "`n")) {
    throw ("Prepared WPC runtime dependency set is unexpected.`nExpected:`n" +
        ($ExpectedDistInfoSorted -join "`n") + "`nActual:`n" + ($ActualDistInfo -join "`n"))
}

# yt-dlp.exe is a PyInstaller executable, so ordinary site-packages/PYTHONPATH cannot
# be relied on for nodriver. Add this portable runtime folder to sys.path from the
# provider module before it imports nodriver.
$PluginText = Get-Content -Path $Plugin -Raw
$Bootstrap = @'
import sys
import pathlib
_RRV_WPC_RUNTIME = pathlib.Path(__file__).resolve().parents[2]
if str(_RRV_WPC_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RRV_WPC_RUNTIME))
'@
if ($PluginText -notmatch '_RRV_WPC_RUNTIME') {
    $PluginText = $PluginText -replace 'import asyncio', ($Bootstrap + "`r`n`r`nimport asyncio")
    Set-Content -Path $Plugin -Value $PluginText -Encoding utf8
}

# Release resources must not contain Python bytecode/cache files.
Get-ChildItem -Path $RuntimeDir -Directory -Recurse -Filter __pycache__ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $RuntimeDir -File -Recurse -Filter *.pyc -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "[3/4] Copying WPC runtime to LocalAppData..."
$RuntimeParent = Split-Path $RuntimeDest -Parent
New-Item -ItemType Directory -Path $RuntimeParent -Force | Out-Null
if (Test-Path $RuntimeDest) {
    Remove-Item $RuntimeDest -Recurse -Force
}
Copy-Item $RuntimeDir $RuntimeDest -Recurse -Force
Set-Content -Path $MarkerDest -Value $Version -Encoding utf8

Write-Host "[4/4] Checking prepared files..."
$RuntimePlugin = Join-Path $RuntimeDest "yt_dlp_plugins\extractor\getpot_wpc.py"
$RuntimeNoDriver = Join-Path $RuntimeDest "nodriver\__init__.py"
if (-not (Test-Path $RuntimePlugin) -or -not (Test-Path $RuntimeNoDriver)) {
    throw "WPC runtime verification failed."
}

$RemainingCache = @(
    Get-ChildItem -Path $RuntimeDir -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "__pycache__" -or $_.Extension -eq ".pyc" }
)
if ($RemainingCache.Count -gt 0) {
    throw "WPC release runtime still contains Python cache files."
}

Write-Host ""
Write-Host ("RR-V WPC Provider " + $Version + " is ready with the locked 1.0.1 dependency set.")
Write-Host ("Runtime: " + $RuntimeDest)
Write-Host "Preparation complete. RR-V uses nodriver for YouTube login and keeps WPC available only when yt-dlp requests it."
Write-Host "If a browser window appears during actual WPC PO Token minting, do not close it until the task ends."

try {
    Remove-Item $WheelDir -Recurse -Force
}
catch {
}
