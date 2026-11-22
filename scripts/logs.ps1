# Shows what RecallSpring's API (default) or worker (-Worker) wrote to its log, then keeps following it until you
# press Ctrl+C. The logs are in local-data\logs (scripts\start-local.ps1 starts both programs in the background).
#
#   scripts\logs.ps1            last 40 lines of the API log, then new lines as they come
#   scripts\logs.ps1 -Worker    the same for the worker
#   scripts\logs.ps1 -Lines 200 -NoFollow
#
# The file is opened so that RecallSpring can still rotate it (rename api.log to api.log.1) while you watch; this
# script then continues with the new file.
param([switch]$Worker, [int]$Lines = 40, [switch]$NoFollow)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$path = Join-Path $root ("local-data\logs\" + $(if ($Worker) { "worker.log" } else { "api.log" }))
if (-not (Test-Path $path)) {
    Write-Output "No log yet at $path. Start RecallSpring with scripts\start-local.ps1."
    exit 0
}

function Open-Log {
    $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
    New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$reader = Open-Log
$tail = New-Object System.Collections.Generic.Queue[string]
while ($null -ne ($line = $reader.ReadLine())) {
    $tail.Enqueue($line)
    if ($tail.Count -gt $Lines) { [void]$tail.Dequeue() }
}
$tail | ForEach-Object { Write-Output $_ }
if ($NoFollow) { $reader.Close(); exit 0 }

Write-Output "--- following $path (Ctrl+C to stop) ---"
try {
    while ($true) {
        $line = $reader.ReadLine()
        if ($null -ne $line) { Write-Output $line; continue }
        Start-Sleep -Milliseconds 500
        # Rotated: the open file was renamed and a new, shorter one took its name.
        if ((Test-Path $path) -and (Get-Item $path).Length -lt $reader.BaseStream.Position) {
            $reader.Close()
            $reader = Open-Log
        }
    }
} finally {
    $reader.Close()
}
