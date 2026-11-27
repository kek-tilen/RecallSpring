# Sets up RecallSpring's connector for several assistants with one command (the welcome page shows it, 2026-11-27).
# It runs the per-app scripts in turn; those stay usable on their own:
#   codex       -> install-codex-connector.ps1 -Username <you>        (docs/codex-setup.md)
#   antigravity -> install-antigravity-connector.ps1 -Username <you>  (docs/antigravity-setup.md)
#   claude      -> recallspring connector-token, then install-claude-desktop-connector.ps1 (docs/connector-setup.md)
# Claude Desktop goes last because its script waits until you quit Claude Desktop.
# Usage: scripts\install-connectors.ps1 -Assistants claude,codex,antigravity -Username <you>
# Install the apps and sign in to them first. Tokens go to files under %LOCALAPPDATA%\RecallSpring and are never printed.
param(
    [Parameter(Mandatory = $true)][string[]]$Assistants,
    [Parameter(Mandatory = $true)][string]$Username
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$order = @("codex", "antigravity", "claude")
$names = @{ codex = "Codex"; antigravity = "Antigravity"; claude = "Claude Desktop" }

# "-Assistants claude,codex" arrives as one string through powershell -File; accept both forms.
$chosen = @($Assistants | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
$unknown = @($chosen | Where-Object { $order -notcontains $_ })
if ($unknown.Count -gt 0) { throw "Unknown assistant: $($unknown -join ', '). Use claude, codex or antigravity." }
if ($chosen.Count -eq 0) { throw "Name at least one assistant: claude, codex or antigravity." }

$done = @()
$failed = @()
foreach ($a in $order) {
    if ($chosen -notcontains $a) { continue }
    Write-Host ""
    Write-Host "== $($names[$a])"
    $global:LASTEXITCODE = 0
    try {
        if ($a -eq "claude") {
            $cli = Join-Path $root "services\api\.venv\Scripts\recallspring.exe"
            Push-Location (Join-Path $root "services\api")   # the CLI reads the database settings from services\api\.env
            try { & $cli connector-token --username $Username } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { throw "Could not create the Claude token (see the message above)." }
            Write-Host "Now quit Claude Desktop (tray icon -> Quit). RecallSpring is added and Claude Desktop starts again."
            & (Join-Path $PSScriptRoot "install-claude-desktop-connector.ps1")
        } else {
            & (Join-Path $PSScriptRoot "install-$a-connector.ps1") -Username $Username
        }
        if ($LASTEXITCODE -ne 0) { throw "the script stopped with exit code $LASTEXITCODE" }
        $done += $names[$a]
    } catch {
        Write-Warning "$($names[$a]) was not set up: $($_.Exception.Message)"
        $failed += $names[$a]
    }
}

Write-Host ""
if ($done.Count -gt 0) { Write-Host "Set up: $($done -join ', '). In your assistant, write: Start studying" }
if ($failed.Count -gt 0) {
    Write-Host "Not set up: $($failed -join ', '). Fix what the message above says and run this again; finished ones are kept."
    exit 1
}
exit 0
