# Connects Codex (CLI, IDE extension and the Codex app) to your local RecallSpring. See docs/codex-setup.md.
#  1. creates a Codex connector token in its own file (never printed, never in Codex's config),
#  2. adds one marked [mcp_servers.recallspring] block to ~/.codex/config.toml (backup first; nothing else changes),
#  3. makes one study folder per course with AGENTS.md and a read-only Codex setting.
# Usage:   scripts\install-codex-connector.ps1 -Username <you>
# Remove:  scripts\install-codex-connector.ps1 -Uninstall   (then revoke the Codex token in RecallSpring Settings)
param(
    [string]$Username,
    [switch]$NewToken,
    [ValidateSet("writes", "prompt", "auto", "approve")]
    [string]$ToolApproval = "writes",
    [string]$ApiUrl = "http://127.0.0.1:4318",
    [string]$StudyRoot = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "RecallSpring Study"),
    [switch]$NoFolders,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "services\mcp\.venv\Scripts\python.exe"
$setup = Join-Path $root "scripts\codex_setup.py"
$cli = Join-Path $root "services\api\.venv\Scripts\recallspring.exe"
$tokenFile = Join-Path $env:LOCALAPPDATA "RecallSpring\codex-connector-token"

if (-not (Test-Path $python)) {
    throw "The RecallSpring connector is not installed yet ($python). Follow docs/connector-setup.md step 3 first."
}

if ($Uninstall) {
    & $python -I $setup config remove
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Removed RecallSpring from Codex. Revoke the Codex token in RecallSpring -> Settings -> Assistant connector."
    Write-Host "Your study folders and the token file ($tokenFile) were left in place; delete them yourself if you like."
    exit 0
}

try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "$ApiUrl/api/v1/health/ready" | Out-Null
} catch {
    throw "RecallSpring is not running at $ApiUrl. Start it (scripts\start-local.ps1) and run this again."
}

if ($NewToken -or -not (Test-Path $tokenFile)) {
    if (-not $Username) { throw "Pass -Username <your RecallSpring user name> so a Codex token can be created." }
    & $cli connector-token --username $Username --client codex --file $tokenFile
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Codex token (see the message above)." }
} else {
    Write-Host "Using the existing Codex token in $tokenFile (pass -NewToken to replace it)."
}

& $python -I $setup config add --python $python --api-url $ApiUrl --token-file $tokenFile --approval $ToolApproval
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $NoFolders) {
    & $python -I $setup folders --root $StudyRoot --api-url $ApiUrl --token-file $tokenFile
    if ($LASTEXITCODE -ne 0) { Write-Warning "The study folders were not made; Codex itself is connected." }
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1. Restart Codex (quit the Codex app or start a new 'codex' session)."
Write-Host "  2. Open a study folder in Codex, e.g. '$StudyRoot\<course>', and trust it when Codex asks."
Write-Host "     In the folder Codex stays read-only; RecallSpring tools ask before saving (mode: $ToolApproval)."
Write-Host "  3. In the CLI, /mcp should list 'recallspring'. Then write: Start studying."
