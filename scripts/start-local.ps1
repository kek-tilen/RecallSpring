# Starts RecallSpring locally: dev database (Docker, loopback only), API on 127.0.0.1:4318 (which also serves the
# web app from apps/web/dist) and the worker, each in its own window. Anything already running is left alone.
# Close the windows to stop the API and worker; the database keeps running in Docker.
#
# -Restart first closes the "RecallSpring API" and "RecallSpring worker" windows this script opened (and only
# those), then starts them again, e.g. after updating the code. The database is not touched.
# -Stop only closes those two windows (scripts/install.ps1 does this before replacing RecallSpring's programs).
#
# The windows are created through WMI so they are independent of whatever started this script (for example a
# Claude Code session, whose child processes end when Claude Desktop quits).
param([switch]$Restart, [switch]$Stop)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"

function Start-Detached([string]$commandLine, [string]$directory) {
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $directory }
    if ($result.ReturnValue -ne 0) { throw "Could not start: $commandLine (WMI code $($result.ReturnValue))" }
}

if ($Restart -or $Stop) {
    $windows = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "powershell.exe" -and
        ($_.CommandLine -like "*WindowTitle='RecallSpring API'*" -or $_.CommandLine -like "*WindowTitle='RecallSpring worker'*")
    }
    foreach ($w in $windows) {
        # /T ends the window together with the uvicorn or worker processes it started.
        taskkill.exe /PID $w.ProcessId /T /F | Out-Null
        Write-Output "Stopped window $($w.ProcessId)"
    }
    Start-Sleep -Seconds 2
    if ($Stop) { exit 0 }
    $still = Get-NetTCPConnection -LocalPort 4318 -State Listen -ErrorAction SilentlyContinue
    if ($still) { throw "Port 4318 is still in use (process $($still[0].OwningProcess)). Close that program, then run this again." }
}

docker compose -p recallspring-dev -f (Join-Path $root "infra\compose.dev.yml") --env-file (Join-Path $root "infra\.env") up -d

if (Get-NetTCPConnection -LocalPort 4318 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "API already running on 127.0.0.1:4318 (use -Restart after updating the code)"
} else {
    Start-Detached ("powershell.exe -NoExit -Command `"`$host.UI.RawUI.WindowTitle='RecallSpring API'; " +
        ".\.venv\Scripts\uvicorn recallspring_api.main:app --host 127.0.0.1 --port 4318`"") $api
}

$worker = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -like "*recallspring*worker*" }
if ($worker) {
    Write-Output "Worker already running"
} else {
    Start-Detached ("powershell.exe -NoExit -Command `"`$host.UI.RawUI.WindowTitle='RecallSpring worker'; " +
        ".\.venv\Scripts\recallspring worker`"") $api
}

Write-Output "RecallSpring API: http://127.0.0.1:4318/api/v1/health/ready"
if (Test-Path (Join-Path $root "apps\web\dist\index.html")) {
    Write-Output "RecallSpring web app: http://127.0.0.1:4318/"
} else {
    Write-Output "Web app not built yet: run 'npm ci' and 'npm run build' in apps\web, then run this script with -Restart."
}
