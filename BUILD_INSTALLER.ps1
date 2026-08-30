param()

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$InstallerScript = Join-Path $Root "installer\RR-V.iss"
$ConstantsPath = Join-Path $Root "app\constants.py"
$DistRoot = Join-Path $Root "dist\RR-V"
$OutputDir = Join-Path $Root "installer-output"

if (-not (Test-Path $InstallerScript)) {
    throw "Installer script is missing: $InstallerScript"
}
if (-not (Test-Path $ConstantsPath)) {
    throw "RR-V constants file is missing: $ConstantsPath"
}
if (-not (Test-Path $DistRoot)) {
    throw "dist\RR-V is missing. Run BUILD_RELEASE.ps1 first."
}

$ConstantsText = Get-Content -Path $ConstantsPath -Raw
$AppVersionMatch = [regex]::Match($ConstantsText, 'APP_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"')
if (-not $AppVersionMatch.Success) {
    throw "APP_VERSION could not be read from app\constants.py."
}
$AppVersion = $AppVersionMatch.Groups[1].Value
$ExpectedInstaller = Join-Path $OutputDir ("RR-V_Setup_" + $AppVersion + ".exe")

$InstallerText = Get-Content -Path $InstallerScript -Raw
$InstallerVersionMatch = [regex]::Match($InstallerText, '#define\s+MyAppVersion\s+"([0-9]+\.[0-9]+\.[0-9]+)"')
if (-not $InstallerVersionMatch.Success) {
    throw "MyAppVersion could not be read from installer\RR-V.iss."
}
$InstallerVersion = $InstallerVersionMatch.Groups[1].Value
if ($InstallerVersion -ne $AppVersion) {
    throw "RR-V version mismatch. app\constants.py=$AppVersion, installer\RR-V.iss=$InstallerVersion"
}

$RunningRRV = @(
    Get-Process -Name "RR-V", "RR-V-Auth-Helper" -ErrorAction SilentlyContinue
)
if ($RunningRRV.Count -gt 0) {
    throw "RR-V or RR-V-Auth-Helper is still running. Exit RR-V completely, including the system tray, before building the Installer."
}

$RequiredFiles = @(
    (Join-Path $DistRoot "RR-V.exe"),
    (Join-Path $DistRoot "RR-V-Auth-Helper.exe"),
    (Join-Path $DistRoot "LICENSE.txt"),
    (Join-Path $DistRoot "LICENSE.ko-KR.txt"),
    (Join-Path $DistRoot "THIRD_PARTY_NOTICES.txt"),
    (Join-Path $DistRoot "SOURCE_OFFER.txt"),
    (Join-Path $DistRoot "licenses\Python-LICENSE.txt"),
    (Join-Path $DistRoot "licenses\PySide6-Qt\OpenSource-License-Texts\LGPL-3.0-only.txt"),
    (Join-Path $DistRoot "licenses\PySide6-Qt\OpenSource-License-Texts\GPL-3.0-only.txt"),
    (Join-Path $DistRoot "licenses\RR-V-Auth-Helper-source\AGPL-3.0.txt")
)
$MissingFiles = @($RequiredFiles | Where-Object { -not (Test-Path $_) })
if ($MissingFiles.Count -gt 0) {
    throw ("Installer input verification failed. Rebuild RR-V first:`n" + ($MissingFiles -join "`n"))
}

$ForbiddenTools = @(
    "yt-dlp.exe",
    "ffmpeg.exe",
    "ffprobe.exe",
    "deno.exe"
)
$BundledExternalTools = @(
    Get-ChildItem -Path $DistRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $ForbiddenTools -contains $_.Name } |
        ForEach-Object { $_.FullName }
)
if ($BundledExternalTools.Count -gt 0) {
    throw ("External runtime tools must not be included in the Installer:`n" + ($BundledExternalTools -join "`n"))
}

$ForbiddenQtFiles = @(
    "Qt6VirtualKeyboard.dll",
    "qtvirtualkeyboardplugin.dll"
)
$BundledForbiddenQt = @(
    Get-ChildItem -Path $DistRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $ForbiddenQtFiles -contains $_.Name } |
        ForEach-Object { $_.FullName }
)
if ($BundledForbiddenQt.Count -gt 0) {
    throw ("GPL-only Qt Virtual Keyboard files must not be included in RR-V:`n" + ($BundledForbiddenQt -join "`n"))
}

$InnoCandidates = @()
$InnoFromPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($InnoFromPath) {
    $InnoCandidates += $InnoFromPath.Source
}

$ProgramFiles64 = $env:ProgramFiles
$ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
if ($ProgramFiles64) {
    $InnoCandidates += (Join-Path $ProgramFiles64 "Inno Setup 7\ISCC.exe")
    $InnoCandidates += (Join-Path $ProgramFiles64 "Inno Setup 6\ISCC.exe")
}
if ($ProgramFilesX86) {
    $InnoCandidates += (Join-Path $ProgramFilesX86 "Inno Setup 7\ISCC.exe")
    $InnoCandidates += (Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe")
}

$Iscc = $InnoCandidates |
    Where-Object { $_ -and (Test-Path $_) } |
    Select-Object -First 1

if (-not $Iscc) {
    throw "Inno Setup Compiler (ISCC.exe) was not found. Install Inno Setup 7 x64 and try again."
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
if (Test-Path $ExpectedInstaller) {
    Remove-Item -Path $ExpectedInstaller -Force
}

Write-Host "[1/3] Verifying RR-V $AppVersion release input..."
Write-Host ("Input: " + $DistRoot)
Write-Host "  - App/Installer version match: OK"
Write-Host "  - Required license/source files: OK"
Write-Host "  - External runtime tools are not bundled: OK"
Write-Host "  - Qt Virtual Keyboard is not bundled: OK"

Write-Host "[2/3] Compiling Inno Setup Installer..."
Write-Host ("Compiler: " + $Iscc)
& $Iscc $InstallerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $ExpectedInstaller)) {
    throw "Installer compilation finished but the expected file was not created: $ExpectedInstaller"
}

Write-Host "[3/3] Installer build complete."
$InstallerInfo = Get-Item $ExpectedInstaller
$InstallerHash = (Get-FileHash -Path $ExpectedInstaller -Algorithm SHA256).Hash
Write-Host ("Output: " + $ExpectedInstaller)
Write-Host ("Size: " + [Math]::Round($InstallerInfo.Length / 1MB, 2) + " MB")
Write-Host ("SHA-256: " + $InstallerHash)
Write-Host ""
Write-Host "RR-V $AppVersion Installer is ready for installation smoke testing."
