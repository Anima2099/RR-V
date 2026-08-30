param()

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$ConstantsPath = Join-Path $Root "app\constants.py"
$VersionInfoPath = Join-Path $Root "RR-V.version_info.txt"
$BuildReleasePath = Join-Path $Root "BUILD_RELEASE.ps1"
$BuiltOutput = Join-Path $Root "dist\RR-V"
$TestOutput = Join-Path $Root "dist\RR-V-Updater-E2E-1.1.9"
$TestExe = Join-Path $TestOutput "RR-V.exe"
$SourceVersion = "1.3.0"
$TestVersion = "1.1.9"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $ConstantsPath)) {
    throw "app\constants.py is missing."
}
if (-not (Test-Path $VersionInfoPath)) {
    throw "RR-V.version_info.txt is missing."
}
if (-not (Test-Path $BuildReleasePath)) {
    throw "BUILD_RELEASE.ps1 is missing."
}

$RunningRRV = @(
    Get-Process -Name "RR-V", "RR-V-Auth-Helper" -ErrorAction SilentlyContinue
)
if ($RunningRRV.Count -gt 0) {
    throw "RR-V or RR-V-Auth-Helper is still running. Exit RR-V completely, including the system tray, and run this test build again."
}

$OriginalConstantsBytes = [System.IO.File]::ReadAllBytes($ConstantsPath)
$OriginalVersionInfoBytes = [System.IO.File]::ReadAllBytes($VersionInfoPath)
$BuildSucceeded = $false

try {
    $ConstantsText = [System.Text.Encoding]::UTF8.GetString($OriginalConstantsBytes)
    $ExpectedVersionLine = 'APP_VERSION = "' + $SourceVersion + '"'
    if (-not $ConstantsText.Contains($ExpectedVersionLine)) {
        throw "Expected source APP_VERSION $SourceVersion was not found. Test build stopped without changing the source."
    }
    $ConstantsText = $ConstantsText.Replace(
        $ExpectedVersionLine,
        'APP_VERSION = "' + $TestVersion + '"'
    )
    [System.IO.File]::WriteAllText($ConstantsPath, $ConstantsText, $Utf8NoBom)

    $VersionInfoText = [System.Text.Encoding]::UTF8.GetString($OriginalVersionInfoBytes)
    $ExpectedTuple = "(1, 3, 0, 0)"
    if (-not $VersionInfoText.Contains($ExpectedTuple) -or -not $VersionInfoText.Contains("'1.3.0'")) {
        throw "Expected RR-V 1.3.0 Windows version metadata was not found."
    }
    $VersionInfoText = $VersionInfoText.Replace("(1, 3, 0, 0)", "(1, 1, 9, 0)")
    $VersionInfoText = $VersionInfoText.Replace("'1.3.0'", "'1.1.9'")
    [System.IO.File]::WriteAllText($VersionInfoPath, $VersionInfoText, $Utf8NoBom)

    Write-Host "[1/4] Temporary updater E2E identity applied: RR-V $TestVersion beta"
    Write-Host "      Product logic remains the current $SourceVersion source."

    if (Test-Path $TestOutput) {
        Remove-Item -Path $TestOutput -Recurse -Force
    }

    Write-Host "[2/4] Building the real RR-V package with the temporary test identity..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $BuildReleasePath
    if ($LASTEXITCODE -ne 0) {
        throw "Updater E2E RR-V build failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path (Join-Path $BuiltOutput "RR-V.exe"))) {
        throw "BUILD_RELEASE.ps1 completed but dist\RR-V\RR-V.exe was not created."
    }

    Write-Host "[3/4] Moving the disposable test package to an isolated dist folder..."
    Move-Item -Path $BuiltOutput -Destination $TestOutput
    if (-not (Test-Path $TestExe)) {
        throw "Updater E2E test executable was not created: $TestExe"
    }

    $FileVersion = (Get-Item $TestExe).VersionInfo.FileVersion
    if (-not $FileVersion.StartsWith($TestVersion)) {
        throw "Unexpected test EXE file version: $FileVersion"
    }

    $BuildSucceeded = $true
}
finally {
    [System.IO.File]::WriteAllBytes($ConstantsPath, $OriginalConstantsBytes)
    [System.IO.File]::WriteAllBytes($VersionInfoPath, $OriginalVersionInfoBytes)
    Write-Host "[4/4] Source version files restored exactly to RR-V $SourceVersion."
}

if (-not $BuildSucceeded) {
    throw "Updater E2E test build did not complete."
}

Write-Host ""
Write-Host "Updater E2E test build is ready."
Write-Host ("Test EXE: " + $TestExe)
Write-Host ("Test identity: RR-V " + $TestVersion + " Community Beta")
Write-Host "Expected live update target: GitHub RR-V 1.2.0 Community Beta"
Write-Host ""
Write-Host "IMPORTANT: This is a disposable downgrade-path test package."
Write-Host "When its verified updater launches RR-V_Setup_1.2.0.exe, completing that Installer will intentionally replace the currently installed RR-V with 1.2.0."
Write-Host "Afterward, use the local RR-V_Setup_1.3.0.exe to perform the real 1.2.0 -> 1.3.0 manual upgrade test."
