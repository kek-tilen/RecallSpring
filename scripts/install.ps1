# Installs RecallSpring on this Windows 10/11 computer for one person (docs/install-windows.md), or updates it.
# Run it again after updating the code (git pull): it updates the dependencies, backs up your data before changing
# the database, and restarts RecallSpring.
#
# What it does, in order (nothing outside this folder and Docker's recallspring-dev project):
#   1. checks Python 3.12+, Node 22+ and that Docker Desktop is running (it installs none of them);
#   2. makes the Git-ignored settings files infra\.env (random database password) and services\api\.env, only if
#      they are missing;
#   3. starts the local database (Docker, reachable from this computer only);
#   4. installs RecallSpring's Python packages from the hashed lock files into services\api\.venv and
#      services\mcp\.venv (the second one is the assistant connector for Claude Desktop or Codex);
#   5. updates the database structure, after a backup if it already holds data;
#   6. builds the web app;
#   7. starts RecallSpring and opens http://127.0.0.1:4318/ (the first visit creates your account).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#         -NoStart   do everything except starting RecallSpring and opening the browser
param([switch]$NoStart)
# "Continue": Windows PowerShell 5.1 turns any line a program writes to stderr into a fatal error under "Stop", and
# pip, npm and alembic write notices there. Every program's exit code is checked instead (Run).
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"
$mcp = Join-Path $root "services\mcp"
$web = Join-Path $root "apps\web"

function Step([string]$text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Run([string]$what) {
    # Stop on a failed native command (PowerShell 5.1 does not do this by itself).
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE). See the messages above." }
}

# ---------------------------------------------------------------- 1. what this computer needs
Step "Checking Python, Node and Docker"
$python = $null
foreach ($candidate in @(@{ Exe = "py"; Pre = @("-3") }, @{ Exe = "python"; Pre = @() })) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    $checkArgs = $candidate.Pre + @("-I", (Join-Path $PSScriptRoot "install_env.py"), "check-python")
    & $candidate.Exe @checkArgs 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
}
if (-not $python) {
    throw "Python 3.12 or newer is needed. Install it from python.org (or: winget install Python.Python.3.12), then run this again."
}
$nodeOk = $false
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = (& node --version) -replace "^v", ""
    $nodeOk = [int]($nodeVersion.Split(".")[0]) -ge 22
}
if (-not $nodeOk) {
    throw "Node.js 22 or newer is needed. Install the LTS version from nodejs.org (or: winget install OpenJS.NodeJS.LTS), then run this again."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is needed for the database. Install it from docker.com (or: winget install Docker.DockerDesktop), start it, then run this again."
}
docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is installed but not running. Start it, wait until it says 'Engine running', then run this again." }
Write-Host "Python, Node $nodeVersion and Docker are ready."

# ---------------------------------------------------------------- 2. settings files (never overwritten)
Step "Settings files"
$envArgs = $python.Pre + @("-I", (Join-Path $PSScriptRoot "install_env.py"), "env", "--root", $root)
& $python.Exe @envArgs; Run "Writing the settings files"

# ---------------------------------------------------------------- 3. database
Step "Starting the database (Docker, this computer only)"
docker compose -p recallspring-dev -f (Join-Path $root "infra\compose.dev.yml") --env-file (Join-Path $root "infra\.env") up -d
Run "Starting the database"
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    $state = docker inspect --format "{{.State.Health.Status}}" recallspring-dev-db-1 2>$null
    if ($state -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $healthy) { throw "The database did not become ready within 2 minutes. Check Docker Desktop, then run this again." }
Write-Host "Database ready."

# ---------------------------------------------------------------- 4. Python packages (hashed lock files)
# A running RecallSpring keeps its programs open, so Windows would not let them be replaced: close its two windows
# first (only those; the database keeps running). Step 7 starts them again.
& (Join-Path $PSScriptRoot "start-local.ps1") -Stop
foreach ($svc in @($api, $mcp)) {
    $name = Split-Path -Leaf $svc
    Step "Python packages for $name"
    $venvPython = Join-Path $svc ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        $venvArgs = $python.Pre + @("-m", "venv", (Join-Path $svc ".venv"))
        & $python.Exe @venvArgs; Run "Creating $name\.venv"
    }
    # The dev lock also pins setuptools, which installing RecallSpring itself needs (new Python versions no longer
    # put it into a fresh environment); every package is checked against its hash.
    & $venvPython -m pip install --quiet --disable-pip-version-check --require-hashes -r (Join-Path $svc "requirements-dev.lock")
    Run "Installing the packages for $name"
    & $venvPython -m pip install --quiet --disable-pip-version-check --no-deps --no-build-isolation -e $svc
    Run "Installing $name"
}

# ---------------------------------------------------------------- 5. database structure (backup first)
Step "Database structure"
Push-Location $api   # the tools read the database settings from services\api\.env
try {
    $current = (& .\.venv\Scripts\alembic.exe current 2>$null | Out-String).Trim()
    Run "Reading the database version"
    if ($current -and $current -notmatch "\(head\)") {
        Write-Host "Your data is backed up before the database changes ($current)."
        & .\.venv\Scripts\recallspring.exe backup; Run "The backup (nothing was changed)"
    }
    & .\.venv\Scripts\alembic.exe upgrade head; Run "Updating the database"
} finally { Pop-Location }

# ---------------------------------------------------------------- 6. web app
Step "Building the web app"
Push-Location $web
try {
    npm ci --no-audit --no-fund; Run "Installing the web app's packages"
    npm run -s build; Run "Building the web app"
} finally { Pop-Location }

# ---------------------------------------------------------------- 7. start
if ($NoStart) {
    Write-Host ""
    Write-Host "Installed. RecallSpring is not running: start it with scripts\start-local.ps1, then open http://127.0.0.1:4318/"
    exit 0
}
Step "Starting RecallSpring"
& (Join-Path $PSScriptRoot "start-local.ps1") -Restart
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop "http://127.0.0.1:4318/api/v1/health/ready" | Out-Null
        $ready = $true; break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { throw "RecallSpring did not start. Look at the 'RecallSpring API' window for the error." }
Start-Process "http://127.0.0.1:4318/"
Write-Host ""
Write-Host "RecallSpring runs at http://127.0.0.1:4318/ (this computer only)."
Write-Host "  First time: the page asks you to create your account and choose your assistant."
Write-Host "  Daily: scripts\start-local.ps1 starts it again after a restart of the computer."
Write-Host "  Backups: once a day into local-data\backups (set RS_BACKUP_DIR in services\api\.env for another disk)."
