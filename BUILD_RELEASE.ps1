param()

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$MainSpec = Join-Path $Root "RR-V.spec"
$HelperSpec = Join-Path $Root "RR-V-Auth-Helper.spec"
$CoreLicense = Join-Path $Root "LICENSE"
$ThirdPartyNotice = Join-Path $Root "THIRD_PARTY_NOTICES.txt"
$SourceOffer = Join-Path $Root "SOURCE_OFFER.txt"
$HelperSourceDir = Join-Path $Root "auth_helper"
$WpcProviderDir = Join-Path $Root "resources\wpc-provider"
$WpcRuntimeDir = Join-Path $WpcProviderDir "runtime"
$WpcLockFile = Join-Path $WpcProviderDir "WPC_RUNTIME_LOCK.txt"
$DistDir = Join-Path $Root "dist"
$HelperDistDir = Join-Path $Root "dist-auth-helper"
$BuildDir = Join-Path $Root "build"
$MainOutputDir = Join-Path $DistDir "RR-V"
$MainExe = Join-Path $MainOutputDir "RR-V.exe"
$HelperSourceExe = Join-Path $HelperDistDir "RR-V-Auth-Helper.exe"
$HelperDestExe = Join-Path $MainOutputDir "RR-V-Auth-Helper.exe"
$CoreLicenseOutput = Join-Path $MainOutputDir "LICENSE.txt"
$LicenseOutputDir = Join-Path $MainOutputDir "licenses"
$HelperSourceOutputDir = Join-Path $LicenseOutputDir "RR-V-Auth-Helper-source"
$QtVersion = "6.11.1"
$QtLgplUrl = "https://raw.githubusercontent.com/qt/qtbase/v$QtVersion/LICENSES/LGPL-3.0-only.txt"
$QtGplUrl = "https://raw.githubusercontent.com/qt/qtbase/v$QtVersion/LICENSES/GPL-3.0-only.txt"

function Copy-LicenseMaterial {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$DestinationDir
    )

    if (-not (Test-Path $SourceDir)) {
        return
    }

    New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null

    $Metadata = Join-Path $SourceDir "METADATA"
    if (Test-Path $Metadata) {
        Copy-Item -Path $Metadata -Destination (Join-Path $DestinationDir "METADATA") -Force
    }

    Get-ChildItem -Path $SourceDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE)' } |
        ForEach-Object {
            $Relative = $_.FullName.Substring($SourceDir.Length).TrimStart('\')
            $Destination = Join-Path $DestinationDir $Relative
            $DestinationParent = Split-Path $Destination -Parent
            New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
            Copy-Item -Path $_.FullName -Destination $Destination -Force
        }
}

function Download-LicenseText {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $DestinationParent = Split-Path $Destination -Parent
    New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    }
    catch {
        throw "Required open-source license text could not be downloaded from $Url. Release build stopped. $($_.Exception.Message)"
    }
    if (-not (Test-Path $Destination) -or (Get-Item $Destination).Length -lt 1000) {
        throw "Downloaded license text is missing or unexpectedly small: $Destination"
    }
}

if (-not (Test-Path $Python)) {
    throw ".venv\Scripts\python.exe is missing. Open the RR-V development folder and prepare the virtual environment first."
}
if (-not (Test-Path $MainSpec)) {
    throw "RR-V.spec is missing."
}
if (-not (Test-Path $HelperSpec)) {
    throw "RR-V-Auth-Helper.spec is missing."
}
if (-not (Test-Path $CoreLicense)) {
    throw "RR-V core LICENSE is missing."
}
if (-not (Test-Path $ThirdPartyNotice)) {
    throw "THIRD_PARTY_NOTICES.txt is missing."
}
if (-not (Test-Path $SourceOffer)) {
    throw "SOURCE_OFFER.txt is missing."
}
if (-not (Test-Path $WpcRuntimeDir)) {
    throw "The prepared WPC runtime is missing. Run PREP_WPC_PROVIDER.ps1 first."
}

$RunningRRV = @(
    Get-Process -Name "RR-V", "RR-V-Auth-Helper" -ErrorAction SilentlyContinue
)
if ($RunningRRV.Count -gt 0) {
    throw "RR-V or RR-V-Auth-Helper is still running. Exit RR-V completely, including the system tray, and run the build again."
}

Write-Host "[1/5] Building RR-V Auth Helper..."
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

Write-Host "[2/5] Building RR-V onedir package..."
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

Write-Host "[3/5] Placing Auth Helper beside RR-V.exe..."
Copy-Item -Path $HelperSourceExe -Destination $HelperDestExe -Force
if (-not (Test-Path $HelperDestExe)) {
    throw "RR-V Auth Helper was not copied into the onedir package."
}

Write-Host "[4/5] Collecting license and source materials..."
New-Item -ItemType Directory -Path $LicenseOutputDir -Force | Out-Null
Copy-Item -Path $CoreLicense -Destination $CoreLicenseOutput -Force
Copy-Item -Path $ThirdPartyNotice -Destination (Join-Path $MainOutputDir "THIRD_PARTY_NOTICES.txt") -Force
Copy-Item -Path $SourceOffer -Destination (Join-Path $MainOutputDir "SOURCE_OFFER.txt") -Force
Copy-Item -Path $ThirdPartyNotice -Destination (Join-Path $LicenseOutputDir "THIRD_PARTY_NOTICES.txt") -Force
Copy-Item -Path $SourceOffer -Destination (Join-Path $LicenseOutputDir "SOURCE_OFFER.txt") -Force

New-Item -ItemType Directory -Path $HelperSourceOutputDir -Force | Out-Null
$HelperSourceFiles = @(
    "__init__.py",
    "main.py",
    "README.md",
    "LICENSE_NOTICE.txt"
)
foreach ($Name in $HelperSourceFiles) {
    $Source = Join-Path $HelperSourceDir $Name
    if (-not (Test-Path $Source)) {
        throw "RR-V Auth Helper source/license file is missing: $Source"
    }
    Copy-Item -Path $Source -Destination (Join-Path $HelperSourceOutputDir $Name) -Force
}
Copy-Item -Path $HelperSpec -Destination (Join-Path $HelperSourceOutputDir "RR-V-Auth-Helper.spec") -Force

$PythonBasePrefix = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$PythonVersion = (& $Python -c "import sys; print(sys.version.split()[0])").Trim()
$SitePackages = (& $Python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
$PySideVersion = (& $Python -c "import PySide6; print(PySide6.__version__)").Trim()
$PyInstallerVersion = (& $Python -m PyInstaller --version).Trim()

$PythonLicense = Join-Path $PythonBasePrefix "LICENSE.txt"
if (-not (Test-Path $PythonLicense)) {
    throw "Python LICENSE.txt was not found at $PythonLicense"
}
Copy-Item -Path $PythonLicense -Destination (Join-Path $LicenseOutputDir "Python-LICENSE.txt") -Force

$QtPackageOutput = Join-Path $LicenseOutputDir "PySide6-Qt"
$QtDistributions = @(
    "PySide6-6.11.1.dist-info",
    "PySide6_Addons-6.11.1.dist-info",
    "PySide6_Essentials-6.11.1.dist-info",
    "shiboken6-6.11.1.dist-info"
)
foreach ($DistName in $QtDistributions) {
    $DistPath = Join-Path $SitePackages $DistName
    if (-not (Test-Path $DistPath)) {
        throw "Required PySide6 license metadata directory is missing: $DistPath"
    }
    Copy-LicenseMaterial -SourceDir $DistPath -DestinationDir (Join-Path $QtPackageOutput $DistName)
}

$QtLicensesDir = Join-Path $SitePackages "PySide6\Qt\LICENSES"
if (Test-Path $QtLicensesDir) {
    Copy-Item -Path $QtLicensesDir -Destination (Join-Path $QtPackageOutput "Qt-LICENSES") -Recurse -Force
}

# PyPI wheels may expose only the commercial-license reference file in their
# dist-info licenses directory even though the same wheel is valid for the
# LGPL/GPL community licensing options. RR-V distributes under the LGPLv3
# option, so always include the exact LGPLv3 and GPLv3 texts from Qt 6.11.1.
$QtOpenSourceLicenseDir = Join-Path $QtPackageOutput "OpenSource-License-Texts"
$QtLgplFile = Join-Path $QtOpenSourceLicenseDir "LGPL-3.0-only.txt"
$QtGplFile = Join-Path $QtOpenSourceLicenseDir "GPL-3.0-only.txt"
Download-LicenseText -Url $QtLgplUrl -Destination $QtLgplFile
Download-LicenseText -Url $QtGplUrl -Destination $QtGplFile

$WpcLicenseOutput = Join-Path $LicenseOutputDir "WPC-runtime"
New-Item -ItemType Directory -Path $WpcLicenseOutput -Force | Out-Null
Get-ChildItem -Path $WpcRuntimeDir -Directory -Filter "*.dist-info" |
    ForEach-Object {
        Copy-LicenseMaterial -SourceDir $_.FullName -DestinationDir (Join-Path $WpcLicenseOutput $_.Name)
    }
if (Test-Path $WpcLockFile) {
    Copy-Item -Path $WpcLockFile -Destination (Join-Path $WpcLicenseOutput "WPC_RUNTIME_LOCK.txt") -Force
}

# RR-V Auth Helper is AGPL-3.0-only. nodriver 0.50.3 carries the complete AGPL
# text in the exact bundled WPC runtime, so copy that verbatim beside the
# Helper's preferred source form instead of relying only on a web link.
$NoDriverAgplSource = Join-Path $WpcRuntimeDir "nodriver-0.50.3.dist-info\licenses\LICENSE.txt"
$HelperAgplFile = Join-Path $HelperSourceOutputDir "AGPL-3.0.txt"
if (-not (Test-Path $NoDriverAgplSource)) {
    throw "nodriver AGPL license text is missing from the prepared WPC runtime: $NoDriverAgplSource"
}
Copy-Item -Path $NoDriverAgplSource -Destination $HelperAgplFile -Force

$ManifestLines = @(
    "RR-V 1.2.0 build license manifest",
    "Generated: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss K'))",
    "Python: $PythonVersion",
    "PySide6 / Qt for Python: $PySideVersion",
    "Qt LGPL/GPL license text source tag: qt/qtbase v$QtVersion",
    "PyInstaller build tool: $PyInstallerVersion",
    "",
    "WPC runtime lock:"
)
if (Test-Path $WpcLockFile) {
    $ManifestLines += @(
        Get-Content -Path $WpcLockFile |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith('#') }
    )
}
$ManifestLines | Set-Content -Path (Join-Path $LicenseOutputDir "BUILD_LICENSE_MANIFEST.txt") -Encoding utf8

Write-Host "[5/5] Verifying release layout..."
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

# Qt Virtual Keyboard is GPLv3-only in the Qt 6.11 community distribution.
# RR-V does not use it; fail the release if PyInstaller ever pulls it back in.
$ForbiddenQtCommunityFiles = @(
    "Qt6VirtualKeyboard.dll",
    "qtvirtualkeyboardplugin.dll"
)
$BundledForbiddenQtFiles = @(
    Get-ChildItem -Path $MainOutputDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $ForbiddenQtCommunityFiles -contains $_.Name } |
        ForEach-Object { $_.FullName }
)
if ($BundledForbiddenQtFiles.Count -gt 0) {
    throw ("GPL-only Qt Virtual Keyboard files must not be bundled with the RR-V core:`n" + ($BundledForbiddenQtFiles -join "`n"))
}

$RequiredReleaseFiles = @(
    $MainExe,
    $HelperDestExe,
    $CoreLicenseOutput,
    (Join-Path $MainOutputDir "THIRD_PARTY_NOTICES.txt"),
    (Join-Path $MainOutputDir "SOURCE_OFFER.txt"),
    (Join-Path $LicenseOutputDir "Python-LICENSE.txt"),
    (Join-Path $LicenseOutputDir "BUILD_LICENSE_MANIFEST.txt"),
    $QtLgplFile,
    $QtGplFile,
    (Join-Path $HelperSourceOutputDir "main.py"),
    (Join-Path $HelperSourceOutputDir "LICENSE_NOTICE.txt"),
    $HelperAgplFile
)
$MissingReleaseFiles = @($RequiredReleaseFiles | Where-Object { -not (Test-Path $_) })
if ($MissingReleaseFiles.Count -gt 0) {
    throw ("License/source packaging verification failed:`n" + ($MissingReleaseFiles -join "`n"))
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
Write-Host "  - LICENSE.txt"
Write-Host "  - THIRD_PARTY_NOTICES.txt / SOURCE_OFFER.txt"
Write-Host "  - licenses\..."
Write-Host "  - _internal\..."
Write-Host "External tools are intentionally not bundled and will be installed by RR-V after launch."
