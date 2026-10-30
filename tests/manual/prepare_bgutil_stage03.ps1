<#
Developer-only preparation of a separate, GPL-3.0-only external BgUtils provider.
The prepared provider is not bundled with RR-V, and RR-V will not auto-install
it. Use only for stage03 Windows smoke testing, not as a public installer.
#>
param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Version = "2.0.2"
$Commit = "26475e9d3665b972c4aeb83b4dbaafcf64b88438"
$PluginDigest = "a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef"
$Deno = Join-Path $env:LOCALAPPDATA "RR-V\tools\deno.exe"
$Destination = Join-Path $env:LOCALAPPDATA "RR-V\bgutil-stage03-external"
$Workspace = Join-Path $env:TEMP ("RRV-BgUtils-03-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$PreviousDenoDir = [Environment]::GetEnvironmentVariable("DENO_DIR", "Process")
$PreviousNoPrompt = [Environment]::GetEnvironmentVariable("DENO_NO_PROMPT", "Process")
$Succeeded = $false
$CreatedDestination = $false
try {
    Write-Host "RR-V 1.6.0 / Stage 03 / external BgUtils setup"
    Write-Host "Upstream GPL-3.0-only. DEVELOPMENT USE ONLY."
    if (-not (Test-Path -LiteralPath $Deno -PathType Leaf)) {
        throw "Deno executable not found: $Deno"
    }
    if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
        throw "External stage03 folder exists. To replace it, run this command with -Force (close RR-V first)."
    }
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
    $Archive = Join-Path $Workspace "source.zip"
    $PluginZip = Join-Path $Workspace "plugin.zip"
    $SourceDir = Join-Path $Workspace "unpacked"
    $PluginDir = Join-Path $Workspace "plugins"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host "[1/3] Downloading pinned upstream source and official plugin..."
    Invoke-WebRequest -Uri "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/$Commit.zip" -OutFile $Archive -UseBasicParsing
    Invoke-WebRequest -Uri "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/$Version/bgutil-ytdlp-pot-provider.zip" -OutFile $PluginZip -UseBasicParsing
    $ActualDigest = (Get-FileHash -LiteralPath $PluginZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualDigest -ne $PluginDigest) {
        throw "The upstream plugin ZIP SHA-256 does not match the pinned release."
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $SourceDir
    Expand-Archive -LiteralPath $PluginZip -DestinationPath $PluginDir
    $SourceEntries = @(Get-ChildItem -LiteralPath $SourceDir -Directory)
    if ($SourceEntries.Count -ne 1) { throw "Unexpected source archive layout." }
    $Root = $SourceEntries[0].FullName
    $Package = Get-Content -LiteralPath (Join-Path $Root "server\package.json") -Raw | ConvertFrom-Json
    if ($Package.version -ne $Version -or $Package.license -ne "GPL-3.0-only") {
        throw "Unexpected upstream package version or licensing."
    }
    foreach ($File in @("getpot_bgutil.py", "getpot_bgutil_http.py", "getpot_bgutil_script.py")) {
        if (-not (Test-Path -LiteralPath (Join-Path $PluginDir "yt_dlp_plugins\extractor\$File"))) {
            throw "Official yt-dlp plugin missing: $File"
        }
    }
    Write-Host "[1/3] PASS: official ZIP SHA-256 and source metadata"

    Write-Host "[2/3] Preparing a separate LocalAppData directory..."
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $CreatedDestination = $true
    Copy-Item -LiteralPath (Join-Path $Root "server") -Destination (Join-Path $Destination "server") -Recurse
    Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination (Join-Path $Destination "LICENSE")
    Copy-Item -LiteralPath $PluginDir -Destination (Join-Path $Destination "plugins") -Recurse
    Copy-Item -LiteralPath $PluginZip -Destination (Join-Path $Destination "plugin.zip")
    $Manifest = @{
        version = $Version
        source_commit = $Commit
        plugin_sha256 = $PluginDigest
    } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText(
        (Join-Path $Destination "rrv-stage03.json"),
        $Manifest,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "[2/3] PASS: external files prepared"

    Write-Host "[3/3] Installing Deno dependencies using upstream frozen lockfile..."
    $env:DENO_DIR = Join-Path $Destination "deno-cache"
    $env:DENO_NO_PROMPT = "1"
    $InstallErr = Join-Path $Workspace "deno-stderr.txt"
    $InstallOut = Join-Path $Workspace "deno-stdout.txt"
    $InstallParams = @{
        FilePath = $Deno
        ArgumentList = @("install", "--allow-scripts=npm:canvas", "--frozen")
        WorkingDirectory = (Join-Path $Destination "server")
        RedirectStandardOutput = $InstallOut
        RedirectStandardError = $InstallErr
        WindowStyle = "Hidden"
        Wait = $true
        PassThru = $true
    }
    $Install = Start-Process @InstallParams
    if ($Install.ExitCode -ne 0) {
        Get-Content -LiteralPath $InstallErr -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        throw "Deno dependency installation failed (code $($Install.ExitCode))."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Destination "server\node_modules") -PathType Container)) {
        throw "Expected server/node_modules directory was not created."
    }
    Write-Host "[3/3] PASS: dependencies ready"
    Write-Host "STAGE 03 SETUP RESULT: PASS"
    Write-Host "The external provider will NOT start until the explicit environment variable is set."
    $Succeeded = $true
}
catch {
    Write-Host ("STAGE 03 SETUP RESULT: NEEDS REVIEW - " + $_.Exception.Message)
}
finally {
    [Environment]::SetEnvironmentVariable("DENO_DIR", $PreviousDenoDir, "Process")
    [Environment]::SetEnvironmentVariable("DENO_NO_PROMPT", $PreviousNoPrompt, "Process")
    if (-not $Succeeded -and $CreatedDestination) {
        try { Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction Stop }
        catch { Write-Host "Could not clean partial external setup: $Destination" }
    }
    if (Test-Path -LiteralPath $Workspace) {
        try { Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction Stop }
        catch { Write-Host "Could not clean temporary setup files: $Workspace" }
    }
}
if (-not $Succeeded) { exit 1 }
