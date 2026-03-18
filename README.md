# Stock Sage

Stock Sage is an inventory intelligence app with:

- A React + Vite frontend dashboard
- A FastAPI backend API
- Neon PostgreSQL as the database

## Tech Stack

- Frontend: React, TypeScript, Vite
- Backend: Python 3.11, FastAPI, SQLAlchemy, Alembic
- Database: Neon Postgres

## Project Structure

- `frontend/` - dashboard UI
- `backend/` - API, business logic, forecasting jobs
- `data/` - local data files and generated reports
- `scripts/` - helper scripts

## Local Development

### 1) Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env -Force
```

Set `DATABASE_URL` in `backend/.env` to your Neon connection string, then:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

### 2) Frontend

```bash
cd frontend
npm ci
```

Set `VITE_API_BASE_URL` (for local dev: `http://localhost:8000`) in a frontend env file, then:

```bash
npm run dev
```

## Deployment

- Frontend: Vercel (`frontend/` as root directory)
- Backend: Render (Blueprint via `render.yaml`)
- Database: Neon

Required environment variables:

- Frontend (`Vercel`): `VITE_API_BASE_URL`
- Backend (`Render`): `DATABASE_URL`, `CORS_ALLOW_ORIGINS`

## Notes

- Render free web services can cold-start after idle periods.
- This repository ignores `docs/` and local generated artifacts by default.
