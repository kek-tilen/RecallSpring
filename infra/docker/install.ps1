# RecallSpring with Docker on Windows, in one command (docs/install-docker.md):
#
#   irm https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.ps1))) -Full -Dir D:\RecallSpring
#
# Prefer to read it first? Download install.ps1 from a release on GitHub, read it, then run
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# The same steps as install.sh: checks Docker Desktop, disk space and ports; says what it will do and asks; downloads
# the release's compose.yml, images.env and recallspring.ps1 and checks them against the hashes of that release; writes
# them with a random database password into one folder; starts RecallSpring; prints a one-time link for your account.
# It changes nothing outside that folder (and the sync folder you name) and Docker's "recallspring" project, never
# installs Docker, never needs administrator rights, and every port is on 127.0.0.1 only.
# -Docker is accepted for later: once a Windows bundle without Docker exists, it will choose this way.
param(
    [string]$Dir = (Join-Path $env:USERPROFILE "RecallSpring"),
    [int]$Port = 4318,
    [int]$McpPort = 4319,
    [string]$Backups = "",
    [string]$SyncFolder = "",
    [switch]$Full,
    [string]$Version = "",
    [switch]$Beta,
    [string]$Project = "recallspring",
    [switch]$Yes,
    [string]$From = "",
    [string]$Image = "",
    [switch]$Docker
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RsRepo = "kek-tilen/RecallSpring"
# Filled in when a release is built (a copy from the repository checks SHA256SUMS against GitHub's copy only).
$RsRelease = "@RS_VERSION@"
$RsSumsSha256 = "@SUMS_SHA256@"

function Say([string]$text) { Write-Host $text }
function Ok([string]$text) { Write-Host "  $([char]0x2713) $text" }
function Fail([string]$text) { throw "RecallSpring was not installed: $text" }

function Get-Newest {
    $url = if ($Beta) { "https://api.github.com/repos/$RsRepo/releases?per_page=1" } else { "https://api.github.com/repos/$RsRepo/releases/latest" }
    try { $r = Invoke-RestMethod -Uri $url -UseBasicParsing } catch { Fail "could not ask GitHub for the newest release" }
    $tag = @($r)[0].tag_name
    if (-not $tag) { Fail "no release of RecallSpring was found" }
    return $tag
}

function Test-PortFree([int]$p) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $p)
        $done = $task.Wait(3000)
        return -not ($done -and $client.Connected)
    } catch { return $true } finally { $client.Dispose() }
}

function Invoke-Docker {
    # Windows PowerShell 5.1 turns a native command's stderr (Docker's warnings) into errors; here they are only noise.
    $ErrorActionPreference = "Continue"
    & docker @args 2>$null
}

function Get-Sha256([string]$path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant() }

function Write-Private([string]$path, [string]$text) {
    # UTF-8 without a byte order mark (Docker Compose reads .env literally), readable by this Windows user only.
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false)))
    & icacls.exe $path /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
}

function Get-ReleaseFiles([string]$work) {
    $names = @("compose.yml", "images.env", "recallspring.ps1")
    if ($From) {
        foreach ($f in $names) {
            if (-not (Test-Path -LiteralPath (Join-Path $From $f))) { Fail "$From\$f is missing" }
            Copy-Item -LiteralPath (Join-Path $From $f) -Destination $work
        }
        Say "  ! files from $From, not checked against a release"
        return
    }
    $base = "https://github.com/$RsRepo/releases/download/$Version"
    $sums = Join-Path $work "SHA256SUMS"
    Invoke-WebRequest -Uri "$base/SHA256SUMS" -OutFile $sums -UseBasicParsing
    if ($RsSumsSha256 -notlike "@*@" -and (Get-Sha256 $sums) -ne $RsSumsSha256) {
        Fail "the release's SHA256SUMS does not match this install script; nothing was changed"
    }
    $wanted = @{}
    foreach ($line in Get-Content -LiteralPath $sums) {
        $parts = $line -split "\s+", 2
        if ($parts.Count -eq 2) { $wanted[$parts[1].TrimStart("*")] = $parts[0].ToLowerInvariant() }
    }
    foreach ($f in $names) {
        $target = Join-Path $work $f
        Invoke-WebRequest -Uri "$base/$f" -OutFile $target -UseBasicParsing
        if (-not $wanted.ContainsKey($f) -or (Get-Sha256 $target) -ne $wanted[$f]) {
            Fail "$f does not match the release's SHA256SUMS; nothing was changed"
        }
    }
    Ok "compose.yml, images.env and recallspring.ps1 match release $Version (SHA-256 checked)"
}

function Get-Value([string]$key, [string]$path) {
    $line = Get-Content -LiteralPath $path | Where-Object { $_ -like "$key=*" } | Select-Object -First 1
    if ($line) { return $line.Substring($key.Length + 1) } else { return "" }
}

# ---------------------------------------------------------------- checks (nothing changes yet)
if ($Project -notmatch '^[a-z0-9_-]+$') { Fail "-Project may use a-z, 0-9, - and _ only" }
$Dir = [IO.Path]::GetFullPath($Dir)
if (-not $Backups) { $Backups = Join-Path $Dir "backups" } else { $Backups = [IO.Path]::GetFullPath($Backups) }
if ($SyncFolder) { $SyncFolder = [IO.Path]::GetFullPath($SyncFolder) }
foreach ($p in @($Dir, $Backups, $SyncFolder)) { if ($p -match '["$`]') { Fail "folder names with "" `$ or `` are not supported: $p" } }
if (-not $Version -and -not $From) { $Version = if ($RsRelease -like "@*@") { Get-Newest } else { $RsRelease } }

Say ""
Say "RecallSpring $(if ($Version) { $Version } else { "from $From" }) - install with Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker Desktop is needed. Install it from docker.com (or: winget install Docker.DockerDesktop), start it, then run this again."
}
Invoke-Docker info | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop is installed but not running. Start it, wait until it says 'Engine running', then run this again." }
Invoke-Docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is needed (the ""docker compose"" command)." }
Ok "Docker $(Invoke-Docker version --format '{{.Server.Version}}') is running ($(Invoke-Docker info --format '{{.OSType}}/{{.Architecture}}'))"

if (Test-Path -LiteralPath (Join-Path $Dir ".env")) { Fail "RecallSpring is installed in $Dir already. Update it with: $Dir\recallspring update" }
if (Invoke-Docker ps -aq --filter "label=com.docker.compose.project=$Project") { Fail "Docker already has a project called ""$Project"". Choose another with -Project." }
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($Dir).Substring(0, 1))
if ($drive.Free -lt 4GB) { Fail "about 4 GB of free disk space is needed on $($drive.Name):." }
Ok "$([math]::Floor($drive.Free / 1GB)) GB free on $($drive.Name): - 4 GB is enough to begin"
$mem = [int64](Invoke-Docker info --format '{{.MemTotal}}')
if ($mem -lt 1900000000) { Fail "Docker has less than 2 GB of memory. Give it more in Docker Desktop: Settings > Resources." }
if (-not (Test-PortFree $Port)) { Fail "port $Port on this computer is in use. Choose another with -Port." }
if (-not (Test-PortFree $McpPort)) { Fail "port $McpPort on this computer is in use. Choose another with -McpPort." }
Ok "Ports $Port and $McpPort are free on this computer"
if ($SyncFolder -and -not (Test-Path -LiteralPath $SyncFolder -PathType Container)) {
    Fail "the sync folder $SyncFolder is not there. Is the sync app running and signed in?"
}

Say ""
Say "This will:"
Say "  - make the folder $Dir (settings, the recallspring command, backups)"
if ($Backups -ne (Join-Path $Dir "backups")) { Say "  - put backups in $Backups" }
if ($SyncFolder) { Say "  - make $SyncFolder\RecallSpring for encrypted backups and learners' copies" }
Say "  - download RecallSpring$(if ($Full) { ' with LibreOffice' }) and PostgreSQL 16, about $(if ($Full) { '1 GB' } else { '500 MB' })"
Say "  - start them, reachable from this computer only (127.0.0.1)"
Say "Nothing outside that folder and Docker's ""$Project"" project is changed."
Say ""
if (-not $Yes) {
    $answer = Read-Host "Continue? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Fail "you chose not to continue. Nothing was changed." }
}
Say ""

# ---------------------------------------------------------------- files
$work = Join-Path ([IO.Path]::GetTempPath()) ("recallspring-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Get-ReleaseFiles $work
    $releaseVersion = Get-Value "RS_VERSION" (Join-Path $work "images.env")
    $img = if ($Image) { $Image } elseif ($Full) { Get-Value "RS_IMAGE_FULL" (Join-Path $work "images.env") } else { Get-Value "RS_IMAGE_BASE" (Join-Path $work "images.env") }
    if (-not $img) { Fail "images.env names no image" }

    foreach ($sub in @("data\storage", "data\run", "data\secrets", "data\home")) { New-Item -ItemType Directory -Force -Path (Join-Path $Dir $sub) | Out-Null }
    New-Item -ItemType Directory -Force -Path $Backups | Out-Null
    foreach ($f in @("compose.yml", "images.env", "recallspring.ps1")) { Copy-Item -LiteralPath (Join-Path $work $f) -Destination $Dir -Force }
    # recallspring.cmd runs recallspring.ps1 for this command only, so Windows' default execution policy can stay as it is.
    $cmd = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File ""%~dp0recallspring.ps1"" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $Dir "recallspring.cmd"), $cmd, (New-Object Text.ASCIIEncoding))
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $tz = "UTC" # Windows PowerShell 5.1 cannot convert Windows zone names; the first-run page uses the browser's zone
    try {
        $out = ""
        if ([TimeZoneInfo]::TryConvertWindowsIdToIanaId([TimeZoneInfo]::Local.Id, [ref]$out)) { $tz = $out }
    } catch { $tz = "UTC" }
    $toDocker = { param($p) $p -replace '\\', '/' }
    $envText = @"
# RecallSpring with Docker (docs/install-docker.md). Made by install.ps1; readable by you only. Keep it private.
COMPOSE_PROJECT_NAME=$Project
RS_VERSION=$(if ($releaseVersion) { $releaseVersion } else { 'unknown' })
RS_IMAGE=$img
RS_FULL=$(if ($Full) { 1 } else { 0 })
RS_DB_PASSWORD=$password
RS_UID=10001
RS_GID=10001
RS_PORT=$Port
RS_MCP_PORT=$McpPort
RS_TIMEZONE=$tz
RS_BACKUP_HOST_DIR=$(& $toDocker $Backups)

"@
    Write-Private (Join-Path $Dir ".env") ($envText -replace "`r`n", "`n")
    if ($SyncFolder) {
        foreach ($sub in @("RecallSpring\Backups", "RecallSpring\Material")) { New-Item -ItemType Directory -Force -Path (Join-Path $SyncFolder $sub) | Out-Null }
        $local = @"
# Made by install.ps1 for -SyncFolder (docs/install-docker.md): encrypted backups go to Backups once encryption is on;
# each learner who chooses "Use a synced folder" gets a subfolder of Material.
services:
  api: &sync
    volumes:
      - "$(& $toDocker (Join-Path $SyncFolder 'RecallSpring')):/sync"
    environment:
      RS_CLOUD_FOLDER_DIR: /sync/Backups
      RS_DRIVE_FOLDER_DIR: /sync/Material
  worker: *sync

"@
        [IO.File]::WriteAllText((Join-Path $Dir "compose.local.yml"), ($local -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    }
    Ok "Settings made in ${Dir}: a random database password, never printed"
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- start
$rs = Join-Path $Dir "recallspring.cmd"
function Invoke-Rs { $ErrorActionPreference = "Continue"; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "recallspring.ps1") @args }
if (-not $Image) {
    Invoke-Rs pull
    if ($LASTEXITCODE -ne 0) { Fail "could not download the images. Check the internet connection and run this again." }
    Ok "Images pulled, each one by its fixed digest"
}
Invoke-Rs up
if ($LASTEXITCODE -ne 0) { Fail "RecallSpring did not start. See: $rs logs" }
$ready = $false
foreach ($i in 1..90) {
    try { Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/v1/health/ready" -UseBasicParsing -TimeoutSec 3 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { Fail "RecallSpring did not become ready in 3 minutes. See: $rs logs" }
Ok "RecallSpring is running"
Say ""
Invoke-Rs setup-link
Say ""
Say "Every day:  $rs status | update | logs | stop | start"
Say "Backups go to $Backups every night. Keep a copy somewhere else too."
