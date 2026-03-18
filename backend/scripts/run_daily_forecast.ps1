param(
    [int]$HorizonDays = 30
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
    $startedAt = Get-Date
    Write-Host "Running daily forecast job (horizon=$HorizonDays)..."
    $pythonCmd = "py -3 -m app.jobs.run_forecast_daily --horizon-days $HorizonDays"
    $output = cmd /c "$pythonCmd 2>&1"
    $exitCode = $LASTEXITCODE

    foreach ($line in $output) {
        Write-Host $line
    }

    $runId = $null
    foreach ($line in $output) {
        if ($line -match "forecast_run_id=(\d+)") {
            $runId = $matches[1]
            break
        }
    }

    if ($exitCode -eq 0) {
        $runIdText = if ($runId) { $runId } else { "n/a" }
        $msg = @(
            "Daily Forecast ran: SUCCESS",
            "Run ID: $runIdText",
            "Horizon: $HorizonDays days",
            "Started: $($startedAt.ToString("yyyy-MM-dd HH:mm:ss"))",
            "Host: $env:COMPUTERNAME"
        ) -join "`n"
        Send-DiscordNotification -Message $msg
        exit 0
    }

    $tail = ($output | Select-Object -Last 4) -join " | "
    $errMsg = @(
        "Daily Forecast ran: FAILED",
        "Horizon: $HorizonDays days",
        "Host: $env:COMPUTERNAME",
        "Detail: $tail"
    ) -join "`n"
    Send-DiscordNotification -Message $errMsg
    throw "Forecast job failed with exit code $exitCode"
} finally {
    Pop-Location
}
