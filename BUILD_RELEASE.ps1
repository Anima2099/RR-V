param()

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$MainSpec = Join-Path $Root "RR-V.spec"
$HelperSpec = Join-Path $Root "RR-V-Auth-Helper.spec"
$DistDir = Join-Path $Root "dist"
$HelperDistDir = Join-Path $Root "dist-auth-helper"
$BuildDir = Join-Path $Root "build"
$MainOutputDir = Join-Path $DistDir "RR-V"
$MainExe = Join-Path $MainOutputDir "RR-V.exe"
$HelperSourceExe = Join-Path $HelperDistDir "RR-V-Auth-Helper.exe"
$HelperDestExe = Join-Path $MainOutputDir "RR-V-Auth-Helper.exe"

if (-not (Test-Path $Python)) {
    throw ".venv\Scripts\python.exe is missing. Open the RR-V development folder and prepare the virtual environment first."
}
if (-not (Test-Path $MainSpec)) {
    throw "RR-V.spec is missing."
}
if (-not (Test-Path $HelperSpec)) {
    throw "RR-V-Auth-Helper.spec is missing."
}

Write-Host "[1/4] Building RR-V Auth Helper..."
& $Python -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $HelperDistDir `
    --workpath (Join-Path $BuildDir "auth-helper") `
    $HelperSpec
if ($LASTEXITCODE -ne 0) {
    throw "RR-V Auth Helper build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $HelperSourceExe)) {
    throw "RR-V Auth Helper output was not created: $HelperSourceExe"
}

Write-Host "[2/4] Building RR-V onedir package..."
& $Python -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $DistDir `
    --workpath (Join-Path $BuildDir "rr-v") `
    $MainSpec
if ($LASTEXITCODE -ne 0) {
    throw "RR-V onedir build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $MainExe)) {
    throw "RR-V onedir output was not created: $MainExe"
}

Write-Host "[3/4] Placing Auth Helper beside RR-V.exe..."
Copy-Item -Path $HelperSourceExe -Destination $HelperDestExe -Force
if (-not (Test-Path $HelperDestExe)) {
    throw "RR-V Auth Helper was not copied into the onedir package."
}

Write-Host "[4/4] Verifying release layout..."
$ForbiddenTools = @(
    "yt-dlp.exe",
    "ffmpeg.exe",
    "ffprobe.exe",
    "deno.exe"
)
$BundledExternalTools = @(
    Get-ChildItem -Path $MainOutputDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $ForbiddenTools -contains $_.Name } |
        ForEach-Object { $_.FullName }
)
if ($BundledExternalTools.Count -gt 0) {
    throw ("External runtime tools must not be bundled in RR-V 1.2.0:`n" + ($BundledExternalTools -join "`n"))
}

try {
    if (Test-Path $HelperDistDir) {
        Remove-Item $HelperDistDir -Recurse -Force
    }
}
catch {
    Write-Host "Temporary Auth Helper dist folder could not be removed. This does not invalidate the build."
}

Write-Host ""
Write-Host "RR-V 1.2.0 onedir build is ready."
Write-Host ("Output: " + $MainOutputDir)
Write-Host "  - RR-V.exe"
Write-Host "  - RR-V-Auth-Helper.exe"
Write-Host "  - _internal\..."
Write-Host "External tools are intentionally not bundled and will be installed by RR-V after launch."
