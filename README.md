# Stock Sage

Stock Sage is a thesis-aligned inventory intelligence prototype. It combines inventory and sales management, daily demand forecasting, reorder recommendations, competitor price scraping, and dashboard reporting in a React + FastAPI stack.

## Core Features

- Inventory, supplier, and sales transaction management
- Daily SKU-level forecasting with persisted confidence intervals
- Reorder recommendations based on lead time, stock position, and forecast output
- Forecast run validation snapshots and run-to-run comparison reporting
- Competitor price scraping, source health reporting, and price comparison
- Dashboard endpoints for stock, forecast, scraper, and pricing visibility

## Stack

- Frontend: React 18, TypeScript, Vite
- Backend: Python 3.11, FastAPI, SQLAlchemy, Alembic
- Database: Neon PostgreSQL
- Forecasting dependencies: `statsmodels`, `prophet`, `xgboost`

## Project Layout

- `frontend/` - dashboard UI
- `backend/app/` - API routes, services, ML logic, jobs
- `backend/tests/` - backend regression tests
- `backend/data/` - generated forecast QA and validation reports
- `docs/` - thesis alignment, runbooks, plans, architecture notes
- `render.yaml` - Render deployment config for backend

## Quick Start

### Backend

```powershell
cd backend
py -3 -m pip install -e ".[dev,forecast]"
Copy-Item .env.example .env -Force
```

Set `DATABASE_URL` in `backend/.env` to your Neon connection string, then run:

```powershell
py -3 -m alembic upgrade head
py -3 -m uvicorn app.main:app --reload --port 8000
```

Optional demo data seed:

```powershell
py -3 scripts/seed_demo_data.py
```

### Frontend

```powershell
cd frontend
npm ci
```

Set `VITE_API_BASE_URL=http://localhost:8000`, then run:

```powershell
npm run dev
```

## Scheduled Jobs

Run the daily forecast job:

```powershell
cd backend
py -3 -m app.jobs.run_forecast_daily --horizon-days 30
```

Run the scraper cycle:

```powershell
cd backend
py -3 -m app.jobs.run_scraper_cycle --verbose
```

Generated forecast QA and validation reports are written to `backend/data/`.

## Testing

Backend tests:

```powershell
cd backend
py -3 -m pytest -q
```

Frontend tests:

```powershell
cd frontend
npm test
```

## Configuration

| Variable | Scope | Purpose |
|---|---|---|
| `DATABASE_URL` | Backend | Neon PostgreSQL connection string |
| `CORS_ALLOW_ORIGINS` | Backend | Allowed frontend origins |
| `VITE_API_BASE_URL` | Frontend | Base URL for the FastAPI backend |

Backend example env lives in [backend/.env.example](./backend/.env.example).

## Important Docs

- [Local runbook](./docs/runbook-local.md)
- [API contract](./docs/api-contract.md)
- [Thesis alignment checklist](./docs/thesis-alignment-checklist.md)
- [Thesis architecture traceability](./docs/thesis-architecture-traceability.md)
- [Forecast accuracy action plan](./docs/thesis-model-accuracy-actions.md)
- [Usability evaluation plan](./docs/usability-evaluation-plan.md)
- [Manuscript proposal PDF](./docs/N%20SUMTECH%20CIT6%20Manuscript%20Proposal%20.pdf)

## Deployment

- Frontend: Vercel
- Backend: Render using [render.yaml](./render.yaml)
- Database: Neon PostgreSQL

Backend deployment currently expects:

- `DATABASE_URL`
- `CORS_ALLOW_ORIGINS`

Frontend deployment currently expects:

- `VITE_API_BASE_URL`

## Thesis Scope Notes

The current codebase is aligned to the manuscript as a web-based prototype, not a mobile app. The strongest completed areas are architecture, core workflows, and operational reporting. The main remaining thesis-completion items are:

- explainability and manual override workflow
- automated low-stock notification delivery
- completed usability study and results write-up
- continued forecast-quality improvement on difficult mature-but-bursty SKUs
