# Connects Google Antigravity (the app and its CLI) to your local RecallSpring. See docs/antigravity-setup.md.
#  1. creates an Antigravity connector token in its own file (never printed, never in Antigravity's config),
#  2. adds one "recallspring" entry to ~/.gemini/config/mcp_config.json (backup first; other servers are kept),
#  3. makes one study folder per course with AGENTS.md (shared with Codex, if you use both).
# Usage:   scripts\install-antigravity-connector.ps1 -Username <you>
# Remove:  scripts\install-antigravity-connector.ps1 -Uninstall   (then revoke the token in RecallSpring Settings)
param(
    [string]$Username,
    [switch]$NewToken,
    [string]$ApiUrl = "http://127.0.0.1:4318",
    [string]$ConfigFile = (Join-Path $HOME ".gemini\config\mcp_config.json"),
    [string]$StudyRoot = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "RecallSpring Study"),
    [switch]$NoFolders,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "services\mcp\.venv\Scripts\python.exe"
$setup = Join-Path $root "scripts\antigravity_setup.py"
$folders = Join-Path $root "scripts\codex_setup.py"
$cli = Join-Path $root "services\api\.venv\Scripts\recallspring.exe"
$tokenFile = Join-Path $env:LOCALAPPDATA "RecallSpring\antigravity-connector-token"

if (-not (Test-Path $python)) {
    throw "The RecallSpring connector is not installed yet ($python). Follow docs/connector-setup.md step 3 first."
}

if ($Uninstall) {
    & $python -I $setup config remove --config $ConfigFile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Removed RecallSpring from Antigravity. Revoke the Antigravity token in RecallSpring -> Settings."
    Write-Host "Your study folders and the token file ($tokenFile) were left in place; delete them yourself if you like."
    exit 0
}

try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "$ApiUrl/api/v1/health/ready" | Out-Null
} catch {
    throw "RecallSpring is not running at $ApiUrl. Start it (scripts\start-local.ps1) and run this again."
}

if ($NewToken -or -not (Test-Path $tokenFile)) {
    if (-not $Username) { throw "Pass -Username <your RecallSpring user name> so an Antigravity token can be created." }
    Push-Location (Join-Path $root "services\api")   # the CLI reads the database settings from services\api\.env
    try { & $cli connector-token --username $Username --client antigravity --file $tokenFile } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Antigravity token (see the message above)." }
} else {
    Write-Host "Using the existing Antigravity token in $tokenFile (pass -NewToken to replace it)."
}

& $python -I $setup config add --config $ConfigFile --python $python --api-url $ApiUrl --token-file $tokenFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $NoFolders) {
    & $python -I $folders folders --root $StudyRoot --api-url $ApiUrl --token-file $tokenFile
    if ($LASTEXITCODE -ne 0) { Write-Warning "The study folders were not made; Antigravity itself is connected." }
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1. Restart Antigravity (quit and open it again)."
Write-Host "  2. Open a study folder as the workspace, e.g. '$StudyRoot\<course>'."
Write-Host "  3. Customizations (sidebar) should list the 'recallspring' MCP server. Then write: Start studying."
Write-Host "     Antigravity asks before each RecallSpring tool until you allow it."
