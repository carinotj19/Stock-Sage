param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$dotEnvPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $dotEnvPath)) {
    Write-Warning "backend/.env is missing. Configure Neon first via scripts/use_neon.ps1."
}

$forecastTaskName = "StockSage-DailyForecast"
$scraperTaskName = "StockSage-ScraperCycle"

$forecastScript = Join-Path $ProjectRoot "scripts\run_daily_forecast.ps1"
$scraperScript = Join-Path $ProjectRoot "scripts\run_scraper_every_3h.ps1"

$forecastAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$forecastScript`""
$scraperAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scraperScript`""

schtasks /Create /F /TN $forecastTaskName /SC DAILY /ST 01:00 /TR $forecastAction | Out-Null
schtasks /Create /F /TN $scraperTaskName /SC HOURLY /MO 3 /TR $scraperAction | Out-Null

Write-Host "Created tasks:"
Write-Host " - $forecastTaskName (daily at 01:00)"
Write-Host " - $scraperTaskName (every 3 hours)"
