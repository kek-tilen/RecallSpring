# Starts RecallSpring locally: dev database (Docker, loopback only), API on 127.0.0.1:4318 and the worker,
# each in its own window. Close the windows to stop the API and worker; the database keeps running in Docker.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"

docker compose -p recallspring-dev -f (Join-Path $root "infra\compose.dev.yml") --env-file (Join-Path $root "infra\.env") up -d

Start-Process powershell -WorkingDirectory $api -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle='RecallSpring API'; .\.venv\Scripts\uvicorn recallspring_api.main:app --host 127.0.0.1 --port 4318"
Start-Process powershell -WorkingDirectory $api -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle='RecallSpring worker'; .\.venv\Scripts\recallspring worker"

Write-Output "RecallSpring API: http://127.0.0.1:4318/api/v1/health/ready"
