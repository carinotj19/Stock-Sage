Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Message,
        [Parameter(Mandatory = $true)]
        [scriptblock] $Action
    )

    Write-Output "[INFO] $Message"
    & $Action
}

try {
    if (-not (Test-Path $BackendDir)) {
        throw "Backend directory not found: $BackendDir"
    }

    if (-not (Test-Path $FrontendDir)) {
        throw "Frontend directory not found: $FrontendDir"
    }

    $backendDotEnv = Join-Path $BackendDir ".env"
    if (-not (Test-Path $backendDotEnv)) {
        throw "backend/.env is missing. Configure Neon first (backend/scripts/use_neon.ps1)."
    }

    Invoke-Step -Message "Running scraper cycle once..." -Action {
        Push-Location $BackendDir
        try {
            py -3 -m app.jobs.run_scraper_cycle
            if ($LASTEXITCODE -ne 0) {
                throw "Scraper command failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    Invoke-Step -Message "Starting backend API server in a new terminal..." -Action {
        $backendCommand = "Set-Location '$BackendDir'; py -3 -m uvicorn app.main:app --reload --port 8000"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand | Out-Null
    }

    Invoke-Step -Message "Starting frontend dev server in a new terminal..." -Action {
        $frontendCommand = "Set-Location '$FrontendDir'; npm run dev"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand | Out-Null
    }

    Write-Output "[OK] Debug stack launched. Keep both terminal windows open."
}
catch {
    Write-Error "[ERROR] $($_.Exception.Message)"
    exit 1
}
