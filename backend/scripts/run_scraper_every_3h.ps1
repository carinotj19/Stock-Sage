param(
    [switch]$NoVerbose
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$BackendRoot = Split-Path -Parent $PSScriptRoot
$DotEnvPath = Join-Path $BackendRoot ".env"

if (-not (Test-Path $DotEnvPath)) {
    throw "backend/.env is missing. Configure Neon first (scripts/use_neon.ps1)."
}

function Import-DotEnv {
    param([string]$Path)

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

function Send-DiscordNotification {
    param([string]$Message)

    $webhook = [Environment]::GetEnvironmentVariable("DISCORD_WEBHOOK_URL", "Process")
    if (-not $webhook) {
        return
    }

    try {
        $body = @{ content = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri $webhook -ContentType "application/json" -Body $body | Out-Null
    } catch {
        Write-Warning "Discord webhook send failed: $($_.Exception.Message)"
    }
}

Import-DotEnv -Path $DotEnvPath

Push-Location $BackendRoot
try {
    $verboseRun = -not $NoVerbose.IsPresent
    $pythonCmd = "py -3 -m app.jobs.run_scraper_cycle"
    if ($verboseRun) {
        $pythonCmd += " --verbose"
    }

    Write-Host "Running competitor scraper cycle..."
    $startedAt = Get-Date
    $output = cmd /c "$pythonCmd 2>&1"
    $exitCode = $LASTEXITCODE

    foreach ($line in $output) {
        Write-Host $line
    }

    $rowsInserted = "n/a"
    foreach ($line in $output) {
        if ($line -match "scraper_rows_inserted=(\d+)") {
            $rowsInserted = $matches[1]
            break
        }
    }

    $sourceSummaries = @()
    foreach ($line in $output) {
        if ($line -match "scraper_source_done source=(.+?) inserted=(\d+)") {
            $sourceName = $matches[1]
            $inserted = $matches[2]
            $sourceSummaries += "$sourceName=$inserted"
        }
    }

    if ($exitCode -eq 0) {
        $sourceText = if ($sourceSummaries.Count -gt 0) {
            ($sourceSummaries | Select-Object -First 8) -join ", "
        } else {
            "no per-source detail (run without verbose)"
        }
        $msg = @(
            "Scraper ran: SUCCESS",
            "Rows inserted: $rowsInserted",
            "Sources: $sourceText",
            "Started: $($startedAt.ToString("yyyy-MM-dd HH:mm:ss"))",
            "Host: $env:COMPUTERNAME"
        ) -join "`n"
        Send-DiscordNotification -Message $msg
        exit 0
    }

    $tail = ($output | Select-Object -Last 4) -join " | "
    $errMsg = @(
        "Scraper ran: FAILED",
        "Host: $env:COMPUTERNAME",
        "Detail: $tail"
    ) -join "`n"
    Send-DiscordNotification -Message $errMsg
    throw "Scraper job failed with exit code $exitCode"
} finally {
    Pop-Location
}
