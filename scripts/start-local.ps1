# Starts RecallSpring locally: dev database (Docker, loopback only), API on 127.0.0.1:4318 and the worker,
# each in its own window. Anything already running is left alone. Close the windows to stop the API and worker;
# the database keeps running in Docker.
#
# The windows are created through WMI so they are independent of whatever started this script (for example a
# Claude Code session, whose child processes end when Claude Desktop quits).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"

function Start-Detached([string]$commandLine, [string]$directory) {
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $directory }
    if ($result.ReturnValue -ne 0) { throw "Could not start: $commandLine (WMI code $($result.ReturnValue))" }
}

docker compose -p recallspring-dev -f (Join-Path $root "infra\compose.dev.yml") --env-file (Join-Path $root "infra\.env") up -d

if (Get-NetTCPConnection -LocalPort 4318 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "API already running on 127.0.0.1:4318"
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
