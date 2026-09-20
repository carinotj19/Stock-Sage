# Stock Sage Backend

FastAPI backend for Stock Sage inventory, forecasting, pricing, and administrative workflows.

## Local Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,forecast]"
Copy-Item .env.example .env -Force
```

Set a PostgreSQL/Neon connection string and a long random session secret in `.env`, then run:

```powershell
alembic upgrade head
python -m app.cli.create_admin --username admin
uvicorn app.main:app --reload
```

On Linux/macOS, activate the virtual environment with the shell-appropriate command and use `python` instead of the Windows launcher.

## Tests

```bash
python -m pytest -q
```

Tests use SQLite only when `STOCK_SAGE_ALLOW_TEST_SQLITE=1`; normal runtime configuration requires PostgreSQL.

## Production Deployment

The repository root contains `render.yaml` for the backend service.

Required Render environment variables:

- `DATABASE_URL`
- `CORS_ALLOW_ORIGINS`
- `ADMIN_SESSION_SECRET`

The blueprint sets:

- `STOCK_SAGE_ENV=production`
- `STOCK_SAGE_IGNORE_DOTENV=1`
- `ADMIN_COOKIE_SECURE=true`
- `ADMIN_COOKIE_SAMESITE=none`

Production mode ignores `STOCK_SAGE_AUTH_DISABLED`, so the local/test bypass cannot disable hosted authentication.

`CORS_ALLOW_ORIGINS` is also used as the trusted-origin list for browser write requests. Include the exact hosted frontend origin and do not use a wildcard with credentialed requests.

After migrations run, create the first admin account from a backend shell:

```bash
python -m app.cli.create_admin --username admin
```

The Render start command runs migrations before starting Uvicorn:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Secrets

Keep real `.env` files, Neon credentials, session secrets, webhook URLs, and generated production exports outside Git. Only placeholder example configuration should be committed.
