# Starts RecallSpring locally: dev database (Docker, loopback only), API on 127.0.0.1:4318 (which also serves the
# web app from apps/web/dist) and the worker. The API and the worker run in the background without a window; what
# they print goes to local-data\logs\api.log and worker.log (rotated at 5 MB, 3 old files kept). Show it with
# scripts\logs.ps1. Anything already running is left alone. The database keeps running in Docker.
#
# -Status  shows whether the API and the worker run, the API's health and where the logs are.
# -Restart stops the API and the worker this script started (and only those), then starts them again, e.g. after
#          updating the code. The database is not touched.
# -Stop    only stops them (scripts/install.ps1 does this before replacing RecallSpring's programs).
#
# The processes are created through WMI so they are independent of whatever started this script (for example a
# Claude Code session, whose child processes end when Claude Desktop quits). Older versions of this script opened
# "RecallSpring API" / "RecallSpring worker" windows; -Restart and -Stop close those too.
param([switch]$Restart, [switch]$Stop, [switch]$Status)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"
$python = Join-Path $api ".venv\Scripts\python.exe"
$logs = Join-Path $root "local-data\logs"
$health = "http://127.0.0.1:4318/api/v1/health/ready"

function Get-RecallSpringProcesses([string]$which) {
    # $which: "api" or "worker". Matches this script's background processes and those of older versions (their
    # windows, or uvicorn started from one on port 4318; never the demo on another port).
    $pattern = @{ api = "*recallspring_api.cli serve*"; worker = "*recallspring_api.cli worker*" }[$which]
    $title = @{ api = "*WindowTitle='RecallSpring API'*"; worker = "*WindowTitle='RecallSpring worker'*" }[$which]
    @(Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "python.exe" -and $_.CommandLine -like $pattern) -or
        ($_.Name -eq "powershell.exe" -and $_.CommandLine -like $title) -or
        ($which -eq "api" -and $_.Name -eq "python.exe" -and $_.CommandLine -like "*uvicorn*recallspring_api.main:app*--port 4318*") -or
        ($which -eq "worker" -and $_.Name -eq "python.exe" -and $_.CommandLine -like "*recallspring*worker*")
    })
}

function Start-Hidden([string]$commandLine) {
    # ShowWindow 0 (SW_HIDE): the console of the new process is never shown.
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $api; ProcessStartupInformation = $startup }
    if ($result.ReturnValue -ne 0) { throw "Could not start: $commandLine (WMI code $($result.ReturnValue))" }
}

if ($Status) {
    foreach ($which in "api", "worker") {
        $p = Get-RecallSpringProcesses $which
        $label = @{ api = "API   "; worker = "Worker" }[$which]
        if (@($p).Count) { Write-Output "$label running (process $(($p | ForEach-Object ProcessId) -join ', '))" }
        else { Write-Output "$label not running" }
    }
    try {
        $r = Invoke-RestMethod -Uri $health -TimeoutSec 5
        Write-Output "Health: $($r.status) (database $($r.checks.database)); worker heartbeat: $($r.worker.state)"
    } catch {
        Write-Output "Health: no answer from $health"
    }
    Write-Output "Logs:   $logs (scripts\logs.ps1 shows the API log, -Worker the worker log)"
    exit 0
}

if ($Restart -or $Stop) {
    foreach ($p in @(Get-RecallSpringProcesses "api") + @(Get-RecallSpringProcesses "worker")) {
        # /T also ends the processes it started (the venv launcher starts the real python.exe).
        # Through cmd: the launcher's child may already be gone, and its "not found" must not stop this script.
        cmd.exe /c "taskkill /PID $($p.ProcessId) /T /F >nul 2>&1"
        Write-Output "Stopped process $($p.ProcessId)"
    }
    Start-Sleep -Seconds 2
    if ($Stop) { exit 0 }
    $still = Get-NetTCPConnection -LocalPort 4318 -State Listen -ErrorAction SilentlyContinue
    if ($still) { throw "Port 4318 is still in use (process $($still[0].OwningProcess)). Close that program, then run this again." }
}

docker compose -p recallspring-dev -f (Join-Path $root "infra\compose.dev.yml") --env-file (Join-Path $root "infra\.env") up -d

New-Item -ItemType Directory -Force $logs | Out-Null
if (Get-NetTCPConnection -LocalPort 4318 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "API already running on 127.0.0.1:4318 (use -Restart after updating the code)"
} else {
    Start-Hidden "`"$python`" -m recallspring_api.cli serve --log-file `"$(Join-Path $logs 'api.log')`""
}

if (@(Get-RecallSpringProcesses "worker").Count) {
    Write-Output "Worker already running"
} else {
    Start-Hidden "`"$python`" -m recallspring_api.cli worker --log-file `"$(Join-Path $logs 'worker.log')`""
}

Write-Output "RecallSpring runs in the background. Status: scripts\start-local.ps1 -Status; logs: scripts\logs.ps1"
Write-Output "RecallSpring API: $health"
if (Test-Path (Join-Path $root "apps\web\dist\index.html")) {
    Write-Output "RecallSpring web app: http://127.0.0.1:4318/"
} else {
    Write-Output "Web app not built yet: run 'npm ci' and 'npm run build' in apps\web, then run this script with -Restart."
}
