# Adds the RecallSpring connector to Claude Desktop (Windows, Microsoft Store build) the only way that sticks:
# wait until Claude Desktop is fully closed, write the entry, then start Claude Desktop again.
# Usage: run it, then quit Claude Desktop (tray icon -> Quit). Log: %LOCALAPPDATA%\RecallSpring\install-connector.log
param(
    [int]$TimeoutMinutes = 60,
    [switch]$NoRelaunch
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $env:LOCALAPPDATA "RecallSpring\install-connector.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
function Log($msg) { Add-Content -Path $log -Value ("{0:u} {1}" -f (Get-Date), $msg) }

$config = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Claude-Data") -Filter "claude_desktop_config.json" -Recurse -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $config) { $config = Get-Item (Join-Path $env:APPDATA "Claude\claude_desktop_config.json") -ErrorAction SilentlyContinue }
if (-not $config) { Log "Claude Desktop config not found"; throw "Claude Desktop config not found" }
$python = Join-Path $root "services\mcp\.venv\Scripts\python.exe"
$merge = Join-Path $root "scripts\claude_desktop_config.py"
Log "waiting for Claude Desktop to close (config: $($config.FullName))"

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
function ClaudeRunning { @(Get-CimInstance Win32_Process -Filter "Name='claude.exe'" | Where-Object { $_.ExecutablePath -like "*\WindowsApps\Claude_*\app\Claude.exe" }).Count -gt 0 }
while (ClaudeRunning) {
    if ((Get-Date) -gt $deadline) { Log "timed out; nothing changed"; exit 1 }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 2   # let the app finish its final settings write
& $python -I $merge add --config $config.FullName --python $python 2>&1 | ForEach-Object { Log $_ }
Log ("entry check: " + (& $python -I $merge check --config $config.FullName))
if (-not $NoRelaunch) { Start-Process "shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"; Log "Claude Desktop restarted" }
