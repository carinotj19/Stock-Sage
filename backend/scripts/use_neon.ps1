param(
    [Parameter(Mandatory = $true)]
    [string] $ConnectionString
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

try {
    $trimmed = $ConnectionString.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        throw "ConnectionString must not be empty."
    }

    $sqlalchemyUrl = $trimmed
    if ($trimmed.StartsWith("postgresql://")) {
        $sqlalchemyUrl = $trimmed -replace "^postgresql://", "postgresql+psycopg://"
    }
    elseif ($trimmed.StartsWith("postgres://")) {
        $sqlalchemyUrl = $trimmed -replace "^postgres://", "postgresql+psycopg://"
    }

    if (-not $sqlalchemyUrl.StartsWith("postgresql+psycopg://")) {
        throw "Expected a PostgreSQL URL. Received: $ConnectionString"
    }

    if ($sqlalchemyUrl -notmatch "sslmode=") {
        Write-Warning "[WARN] Connection string has no sslmode. For Neon use sslmode=require."
    }

    $BackendRoot = Split-Path -Parent $PSScriptRoot
    $DotEnvPath = Join-Path $BackendRoot ".env"

    if (Test-Path $DotEnvPath) {
        $dotEnvRaw = Get-Content -Path $DotEnvPath -Raw
        if ($dotEnvRaw -match "(?m)^DATABASE_URL=.*$") {
            $dotEnvRaw = [regex]::Replace(
                $dotEnvRaw,
                "(?m)^DATABASE_URL=.*$",
                "DATABASE_URL=$sqlalchemyUrl"
            )
        }
        else {
            if ($dotEnvRaw.Length -gt 0 -and -not $dotEnvRaw.EndsWith("`n")) {
                $dotEnvRaw += "`r`n"
            }
            $dotEnvRaw += "DATABASE_URL=$sqlalchemyUrl`r`n"
        }

        if (-not ($dotEnvRaw -match "(?m)^CORS_ALLOW_ORIGINS=.*$")) {
            $dotEnvRaw += "CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`r`n"
        }

        Set-Content -Path $DotEnvPath -Value $dotEnvRaw -Encoding utf8
    }
    else {
        $dotEnvContent = @(
            "DATABASE_URL=$sqlalchemyUrl"
            "CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173"
        )
        Set-Content -Path $DotEnvPath -Value $dotEnvContent -Encoding utf8
    }

    Write-Output "[OK] Updated backend/.env with DATABASE_URL."
    Write-Output "[INFO] backend/.env is the source of truth for database configuration."

    Write-Output "[INFO] Next steps:"
    Write-Output "  cd backend"
    Write-Output "  py -3 -m alembic upgrade head"
    Write-Output "  py -3 scripts/seed_demo_data.py"
}
catch {
    Write-Error "[ERROR] $($_.Exception.Message)"
    exit 1
}
