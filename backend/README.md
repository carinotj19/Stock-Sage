# Stock Sage Backend

Local FastAPI backend for inventory, forecasting, and price comparison.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env -Force
# Put your Neon URL into DATABASE_URL in .env (or run scripts/use_neon.ps1 to write it)
powershell -ExecutionPolicy Bypass -File scripts/use_neon.ps1 -ConnectionString "<your_neon_url>"
alembic upgrade head
uvicorn app.main:app --reload
```

## Tests

```bash
pytest -v
```

## Deploy Backend on Render (Free)

This repo includes a root `render.yaml` configured for the backend service.

Required Render environment variables:

- `DATABASE_URL` (Neon URL using `postgresql+psycopg://...`)
- `CORS_ALLOW_ORIGINS` (comma-separated, include your Vercel frontend URL)
- `ADMIN_SESSION_SECRET` (long random value used to sign admin cookies)
- `ADMIN_COOKIE_SECURE=true`
- `ADMIN_COOKIE_SAMESITE=none` when the frontend and backend are on different hosted domains

After migrations run, create the first admin user from a backend shell:

```bash
python -m app.cli.create_admin --username admin
```

Notes:

- `STOCK_SAGE_IGNORE_DOTENV=1` is set in `render.yaml`, so Render uses dashboard env vars instead of `backend/.env`.
- Start command runs migrations on deploy:
  - `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
