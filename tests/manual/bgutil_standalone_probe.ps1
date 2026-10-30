<#
RR-V 1.6.0, stage 02: standalone BgUtils test only.
Upstream BgUtils POT Provider is GPL-3.0-only. No upstream source is
committed to, bundled with, or integrated into RR-V by this diagnostic.
No RR-V authentication data is read.
#>
param(
    [switch]$SkipTokenGeneration,
    [switch]$KeepWorkspace
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Version = "2.0.2"
$Commit = "26475e9d3665b972c4aeb83b4dbaafcf64b88438"
$ExpectedPluginSha256 = "a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef"
$Deno = Join-Path $env:LOCALAPPDATA "RR-V\tools\deno.exe"
$Workspace = Join-Path $env:TEMP ("RRV-BgUtils-Stage02-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$PreviousDenoDir = [Environment]::GetEnvironmentVariable("DENO_DIR", "Process")
$PreviousNoPrompt = [Environment]::GetEnvironmentVariable("DENO_NO_PROMPT", "Process")
$ServerProcess = $null
$ExitCode = 1

try {
    Write-Host "RR-V 1.6.0 / Stage 02 / BgUtils isolated test"
    Write-Host "Upstream $Version; GPL-3.0-only; no RR-V cookies or saved credentials"
    if (-not (Test-Path -LiteralPath $Deno -PathType Leaf)) {
        throw "Deno is missing: $Deno"
    }
    $DenoVersion = @(& $Deno --version)
    if ($LASTEXITCODE -ne 0 -or $DenoVersion.Count -eq 0) {
        throw "RR-V Deno did not run."
    }
    Write-Host ("Deno: " + $DenoVersion[0])
    if ($DenoVersion[0] -notmatch "^deno ([0-9]+)\.([0-9]+)\." -or
        [int]$Matches[1] -lt 2) {
        throw "BgUtils requires Deno 2.0.0 or newer."
    }

    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
    $SourceArchive = Join-Path $Workspace "pinned-source.zip"
    $PluginArchive = Join-Path $Workspace "plugin.zip"
    $SourceParent = Join-Path $Workspace "source"
    $PluginParent = Join-Path $Workspace "plugins\bgutil"

    Write-Host "[1/5] Downloading pinned source and official plugin..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/$Commit.zip" -OutFile $SourceArchive -UseBasicParsing
    Invoke-WebRequest -Uri "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/$Version/bgutil-ytdlp-pot-provider.zip" -OutFile $PluginArchive -UseBasicParsing
    $ActualSha256 = (Get-FileHash -LiteralPath $PluginArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedPluginSha256) {
        throw "Official plugin ZIP hash did not match the pinned GitHub release SHA-256."
    }
    Expand-Archive -LiteralPath $SourceArchive -DestinationPath $SourceParent
    Expand-Archive -LiteralPath $PluginArchive -DestinationPath $PluginParent
    $SourceDirs = @(Get-ChildItem -LiteralPath $SourceParent -Directory)
    if ($SourceDirs.Count -ne 1) { throw "Unexpected source ZIP layout." }
    $SourceRoot = $SourceDirs[0].FullName
    $ServerHome = Join-Path $SourceRoot "server"
    $ServerPackage = Join-Path $ServerHome "package.json"
    $PluginSource = Join-Path $PluginParent "yt_dlp_plugins\extractor\getpot_bgutil.py"
    if (-not (Test-Path $ServerPackage) -or -not (Test-Path $PluginSource) -or
        -not (Test-Path (Join-Path $SourceRoot "LICENSE"))) {
        throw "Missing provider/plugin/license files in official snapshots."
    }
    $Package = Get-Content -LiteralPath $ServerPackage -Raw | ConvertFrom-Json
    if ($Package.version -ne $Version -or $Package.license -ne "GPL-3.0-only") {
        throw "Unexpected provider version or upstream license declaration."
    }
    Write-Host "[1/5] PASS: pinned server source and release plugin SHA-256"

    Write-Host "[2/5] Installing locked Deno dependencies in the temporary workspace..."
    $env:DENO_DIR = Join-Path $Workspace "deno-cache"
    $env:DENO_NO_PROMPT = "1"
    $InstallOut = Join-Path $Workspace "install-out.txt"
    $InstallErr = Join-Path $Workspace "install-err.txt"
    $InstallParams = @{
        FilePath = $Deno
        ArgumentList = @("install", "--allow-scripts=npm:canvas", "--frozen")
        WorkingDirectory = $ServerHome
        RedirectStandardOutput = $InstallOut
        RedirectStandardError = $InstallErr
        WindowStyle = "Hidden"
        PassThru = $true
        Wait = $true
    }
    $Install = Start-Process @InstallParams
    if ($Install.ExitCode -ne 0) {
        Get-Content -LiteralPath $InstallErr -Tail 16 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host $_ }
        throw "Deno install failed (exit code $($Install.ExitCode))."
    }
    $NodeModules = Join-Path $ServerHome "node_modules"
    if (-not (Test-Path $NodeModules -PathType Container)) {
        throw "Deno install finished but node_modules is missing."
    }
    Write-Host "[2/5] PASS: Deno dependencies"

    $Listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $Listener.Start()
    $Port = ([Net.IPEndPoint]$Listener.LocalEndpoint).Port
    $Listener.Stop()
    $ServerOut = Join-Path $Workspace "server-out.txt"
    $ServerErr = Join-Path $Workspace "server-err.txt"
    Write-Host "[3/5] Starting Deno server on 127.0.0.1:$Port ..."
    $ServerParams = @{
        FilePath = $Deno
        ArgumentList = @("run", "--allow-env", "--allow-net", "--allow-ffi=.",
            "--allow-read=.", "../src/main.ts", "--host", "127.0.0.1", "--port", [string]$Port)
        WorkingDirectory = $NodeModules
        RedirectStandardOutput = $ServerOut
        RedirectStandardError = $ServerErr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $ServerProcess = Start-Process @ServerParams
    $Ping = $null
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if ($ServerProcess.HasExited) { break }
        try {
            $Ping = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/ping" -Method Get -TimeoutSec 2
            if ($Ping.version -eq $Version) { break }
        }
        catch { }
        Start-Sleep -Milliseconds 800
    }
    if ($null -eq $Ping -or $Ping.version -ne $Version) {
        throw "BgUtils server did not answer /ping. Use -KeepWorkspace to inspect server-err.txt."
    }
    Write-Host "[3/5] PASS: GET /ping reports version $($Ping.version)"

    if ($SkipTokenGeneration) {
        Write-Host "[4/5] SKIP: PO Token generation"
    }
    else {
        Write-Host "[4/5] Requesting anonymous PO Token; value hidden..."
        try {
            $Token = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/get_pot" -Method Post -ContentType "application/json" -Body "{}" -TimeoutSec 90
        }
        catch {
            throw ("Anonymous PO Token request failed: " + $_.Exception.Message)
        }
        if ($null -eq $Token -or [string]::IsNullOrWhiteSpace([string]$Token.poToken)) {
            throw "The standalone provider returned no usable PO Token."
        }
        Write-Host "[4/5] PASS: anonymous PO Token generated (not displayed)"
    }

    Write-Host "[5/5] PASS: RR-V download engine and WPC untouched"
    $ExitCode = 0
}
catch {
    Write-Host ("STAGE 02 FAILED: " + $_.Exception.Message)
    Write-Host "This does not imply RR-V or WPC is broken."
}
finally {
    if ($null -ne $ServerProcess) {
        try {
            if (-not $ServerProcess.HasExited) {
                Stop-Process -Id $ServerProcess.Id -Force -ErrorAction Stop
            }
        }
        catch { }
        Write-Host "Standalone HTTP server stopped."
    }
    [Environment]::SetEnvironmentVariable("DENO_DIR", $PreviousDenoDir, "Process")
    [Environment]::SetEnvironmentVariable("DENO_NO_PROMPT", $PreviousNoPrompt, "Process")
    if ($KeepWorkspace) {
        Write-Host "Workspace retained: $Workspace"
        Write-Host "Do not share raw server logs without removing any token values."
    }
    elseif (Test-Path -LiteralPath $Workspace) {
        try {
            Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction Stop
            Write-Host "Temporary test files removed."
        }
        catch {
            Write-Host "Temporary file cleanup incomplete: $Workspace"
        }
    }
}
if ($ExitCode -eq 0) { Write-Host "STAGE 02 RESULT: PASS" }
else { Write-Host "STAGE 02 RESULT: NEEDS REVIEW" }
exit $ExitCode
