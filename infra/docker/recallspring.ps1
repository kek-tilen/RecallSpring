# The everyday command of a Docker install on Windows (docs/install-docker.md). It lives in the install folder, next
# to compose.yml and .env, and only talks to Docker's project for this folder. Run it through recallspring.cmd
# (made by install.ps1), which starts it for this command only, whatever the execution policy:
#
#   recallspring status              version, what runs, health, and whether a newer release exists
#   recallspring update [-Beta] [-Version vX.Y.Z] [-Yes] [-NoBackup]
#   recallspring logs [-Worker|-Mcp|-Db]
#   recallspring stop | start
#   recallspring setup-link          a new one-time link for the first account
#   recallspring backup              back up now (also runs every night)
#   recallspring admin <command>     run a RecallSpring admin command, e.g. admin reset-password --username ana
#   recallspring uninstall           stop and remove the containers; your data stays unless you say otherwise
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RsRepo = "kek-tilen/RecallSpring"
$Dir = $PSScriptRoot
$EnvFile = Join-Path $Dir ".env"
$Command = if ($args.Count -gt 0) { [string]$args[0] } else { "status" }
$Rest = if ($args.Count -gt 1) { @($args[1..($args.Count - 1)]) } else { @() }

function Say([string]$text) { Write-Host $text }
function Fail([string]$text) { [Console]::Error.WriteLine("recallspring: $text"); exit 1 }
if (-not (Test-Path -LiteralPath $EnvFile)) { Fail "no .env next to this command ($Dir). Is RecallSpring installed here?" }

function Get-Value([string]$key, [string]$path) {
    $line = Get-Content -LiteralPath $path | Where-Object { $_ -like "$key=*" } | Select-Object -First 1
    if ($line) { return $line.Substring($key.Length + 1) } else { return "" }
}
$Port = Get-Value "RS_PORT" $EnvFile
if (-not $Port) { $Port = "4318" }
$Version = Get-Value "RS_VERSION" $EnvFile

function Invoke-Dc {
    $ErrorActionPreference = "Continue" # Compose reports progress on stderr; Windows PowerShell 5.1 would stop on it
    $files = @("-f", (Join-Path $Dir "compose.yml"))
    if (Test-Path -LiteralPath (Join-Path $Dir "compose.local.yml")) { $files += @("-f", (Join-Path $Dir "compose.local.yml")) }
    & docker compose --project-directory $Dir @files --env-file $EnvFile @args
}

function Test-Healthy {
    try { Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/v1/health/ready" -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

function Wait-Healthy {
    foreach ($i in 1..90) { if (Test-Healthy) { return $true }; Start-Sleep -Seconds 2 }
    return $false
}

function Get-Newest([bool]$beta) {
    $url = if ($beta) { "https://api.github.com/repos/$RsRepo/releases?per_page=1" } else { "https://api.github.com/repos/$RsRepo/releases/latest" }
    try { return @(Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 15)[0].tag_name } catch { return "" }
}

function Confirm-Step([string]$question, [bool]$yes) {
    if ($yes) { return $true }
    return (Read-Host "$question [y/N]") -match '^(y|yes)$'
}

function Set-Value([string]$key, [string]$value) {
    # Rewrites .env in place, so it stays readable by you only.
    $lines = Get-Content -LiteralPath $EnvFile | ForEach-Object { if ($_ -like "$key=*") { "$key=$value" } else { $_ } }
    [IO.File]::WriteAllText($EnvFile, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
}

function Invoke-Status {
    Say "RecallSpring $(if ($Version) { $Version } else { '?' }) in $Dir"
    Invoke-Dc ps --format "table {{.Service}}`t{{.State}}`t{{.Status}}"
    if (Test-Healthy) { Say "Web app: http://127.0.0.1:$Port/ (ready)" } else { Say "Web app: not answering at http://127.0.0.1:$Port/" }
    $latest = Get-Newest $false
    if ($latest -and $latest -ne $Version) { Say "A newer release exists: $latest. Update with: $Dir\recallspring update" }
}

function Invoke-Update([string[]]$options) {
    $beta = $false; $target = ""; $yes = $false; $noBackup = $false
    for ($i = 0; $i -lt $options.Count; $i++) {
        switch -Regex ($options[$i]) {
            '^--?beta$' { $beta = $true }
            '^--?version$' { $i++; if ($i -ge $options.Count) { Fail "-Version needs a release" }; $target = $options[$i] }
            '^(--?yes|-y)$' { $yes = $true }
            '^--?no-?backup$' { $noBackup = $true }
            default { Fail "unknown option $($options[$i])" }
        }
    }
    if (-not $target) { $target = Get-Newest $beta }
    if (-not $target) { Fail "could not ask GitHub for the newest release" }
    if ($target -eq $Version) { Say "RecallSpring $Version is the newest release."; return }

    $work = Join-Path ([IO.Path]::GetTempPath()) ("recallspring-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $base = "https://github.com/$RsRepo/releases/download/$target"
        $names = @("compose.yml", "images.env", "recallspring.ps1")
        foreach ($f in @("SHA256SUMS") + $names) {
            try { Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $work $f) -UseBasicParsing } catch { Fail "could not download $f of $target" }
        }
        $wanted = @{}
        foreach ($line in Get-Content -LiteralPath (Join-Path $work "SHA256SUMS")) {
            $parts = $line -split "\s+", 2
            if ($parts.Count -eq 2) { $wanted[$parts[1].TrimStart("*")] = $parts[0].ToLowerInvariant() }
        }
        foreach ($f in $names) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $work $f)).Hash.ToLowerInvariant()
            if (-not $wanted.ContainsKey($f) -or $hash -ne $wanted[$f]) { Fail "$f of $target does not match its SHA256SUMS" }
        }
        $key = if ((Get-Value "RS_FULL" $EnvFile) -eq "1") { "RS_IMAGE_FULL" } else { "RS_IMAGE_BASE" }
        $image = Get-Value $key (Join-Path $work "images.env")
        if (-not $image) { Fail "images.env of $target names no image" }

        Say "Update RecallSpring $Version -> $target"
        Say "What is new: https://github.com/$RsRepo/releases/tag/$target"
        if (-not (Confirm-Step "Continue?" $yes)) { Fail "nothing was changed." }
        if (-not $noBackup) {
            Say "Backing up first..."
            Invoke-Dc exec -T api recallspring backup
            if ($LASTEXITCODE -ne 0) { Fail "the backup failed, so nothing was changed (or add -NoBackup)." }
        }
        Copy-Item -LiteralPath (Join-Path $Dir "compose.yml") -Destination (Join-Path $Dir "compose.yml.previous") -Force
        Copy-Item -LiteralPath $EnvFile -Destination "$EnvFile.previous" -Force
        Copy-Item -LiteralPath (Join-Path $work "compose.yml"), (Join-Path $work "images.env") -Destination $Dir -Force
        Set-Value "RS_IMAGE" $image
        Set-Value "RS_VERSION" $target
        Invoke-Dc pull
        if ($LASTEXITCODE -ne 0) {
            Move-Item -LiteralPath (Join-Path $Dir "compose.yml.previous") -Destination (Join-Path $Dir "compose.yml") -Force
            Move-Item -LiteralPath "$EnvFile.previous" -Destination $EnvFile -Force
            Fail "could not download the new images; the old version keeps running."
        }
        # The database structure changes as its own step (the migrate service) before the new version starts.
        Invoke-Dc up -d --remove-orphans
        if ($LASTEXITCODE -eq 0 -and (Wait-Healthy)) {
            Copy-Item -LiteralPath (Join-Path $work "recallspring.ps1") -Destination (Join-Path $Dir "recallspring.ps1") -Force
            Say "RecallSpring $target is running at http://127.0.0.1:$Port/"
            return
        }
        Say "The new version did not start. Going back to $Version..."
        Move-Item -LiteralPath (Join-Path $Dir "compose.yml.previous") -Destination (Join-Path $Dir "compose.yml") -Force
        Move-Item -LiteralPath "$EnvFile.previous" -Destination $EnvFile -Force
        Invoke-Dc up -d --remove-orphans
        if (Wait-Healthy) {
            Say "$Version runs again. The log of the failed start: $Dir\recallspring logs"
        } else {
            Say "$Version does not start either: the database structure may have changed already."
            Say "Restore the backup made before the update: docs/install-docker.md > Going back."
        }
        exit 1
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Uninstall {
    Say "This stops RecallSpring and removes its containers. Your data stays in Docker's volume and in $Dir,"
    Say "and the backups stay where they are, so installing again in $Dir brings everything back."
    if (-not (Confirm-Step "Remove the containers?" $false)) { Fail "nothing was changed." }
    Invoke-Dc down --remove-orphans
    $answer = Read-Host "Removed. To delete your data too, type: delete my data"
    if ($answer -eq "delete my data") {
        Invoke-Dc down -v
        Remove-Item -LiteralPath (Join-Path $Dir "data") -Recurse -Force
        Remove-Item -LiteralPath $EnvFile -Force
        Say "Deleted the database and $Dir\data. Backups were kept; delete them yourself when you are sure."
    } else {
        Say "Your data was kept."
    }
}

switch ($Command) {
    "status" { Invoke-Status }
    "update" { Invoke-Update $Rest }
    "logs" {
        $svc = switch -Regex ([string]($Rest | Select-Object -First 1)) { '^--?worker$' { "worker" } '^--?mcp$' { "mcp" } '^--?db$' { "db" } default { "api" } }
        Invoke-Dc logs --tail 100 -f $svc
    }
    "stop" { Invoke-Dc stop }
    { $_ -in @("start", "up") } {
        Invoke-Dc up -d --remove-orphans
        if ($LASTEXITCODE -eq 0 -and $Command -eq "start") {
            if (Wait-Healthy) { Say "RecallSpring runs at http://127.0.0.1:$Port/" } else { Fail "RecallSpring did not become ready. See: $Dir\recallspring logs" }
        }
    }
    "pull" { Invoke-Dc pull --quiet }
    "setup-link" { Invoke-Dc exec -T api recallspring setup-link --url "http://127.0.0.1:$Port" }
    "backup" { Invoke-Dc exec -T api recallspring backup }
    "admin" {
        # A terminal when there is one (reset-password asks), none when called from a script.
        if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) { Invoke-Dc exec -T api recallspring @Rest } else { Invoke-Dc exec api recallspring @Rest }
    }
    "uninstall" { Invoke-Uninstall }
    "version" { Say $(if ($Version) { $Version } else { "unknown" }) }
    { $_ -in @("help", "-h", "--help") } { Get-Content -LiteralPath $PSCommandPath -TotalCount 12 | Select-Object -Skip 4 | ForEach-Object { $_ -replace '^# ?', '' } }
    default { Fail "unknown command $Command (try: recallspring help)" }
}
exit $LASTEXITCODE
