# Stock Sage

Stock Sage is an inventory intelligence web application for small retail operations. It combines inventory and sales tracking, daily demand forecasting, reorder recommendations, competitor price monitoring, and operational dashboards in a React + FastAPI stack.

## Public Demo

A read-only browser demo is designed to run on GitHub Pages:

**https://carinotj19.github.io/Stock-Sage/**

The Pages build uses generated sample data in the browser. It does **not** connect to the production Render API or Neon database, and write operations are disabled.

If the link is not live yet, enable **Settings → Pages → Source → GitHub Actions** after making the repository public. The workflow is already included at `.github/workflows/pages.yml`.

## Features

- Inventory and SKU management
- Stock adjustments and sales transaction capture
- Daily SKU-level demand forecasting
- Persisted confidence intervals and forecast validation
- Reorder recommendations using lead time, stock position, and forecast output
- Predicted stockout visibility
- Competitor price scraping and price comparison
- Scraper source-health reporting
- Role-based admin authentication and audit logging
- Manual scraper workflow for administrators
- Responsive React dashboard

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python 3.11, FastAPI |
| Database | PostgreSQL / Neon |
| ORM & migrations | SQLAlchemy, Alembic |
| Forecasting | pandas, NumPy, statsmodels, Prophet, XGBoost |
| Backend hosting | Render |
| Frontend hosting | Vercel |
| Public preview | GitHub Pages |

## Project Layout

```text
Stock-Sage/
├── backend/
│   ├── app/                 # API, services, jobs, ML, scrapers
│   ├── alembic/             # Database migrations
│   ├── scripts/             # Import/export and operational utilities
│   └── tests/               # Backend regression tests
├── frontend/
│   ├── src/                 # React application
│   └── tests/               # Frontend tests
├── scripts/                 # Workspace development launcher
├── .github/workflows/       # CI and GitHub Pages demo
└── render.yaml              # Render backend blueprint
```

## Local Development

### 1. Backend

```powershell
cd backend
py -3 -m pip install -e ".[dev,forecast]"
Copy-Item .env.example .env -Force
```

Edit `backend/.env` and set at minimum:

```env
STOCK_SAGE_ENV=development
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>/<database>?sslmode=require
ADMIN_SESSION_SECRET=<long-random-secret>
CORS_ALLOW_ORIGINS=http://localhost:5173
```

Run migrations, create an administrator, and start FastAPI:

```powershell
py -3 -m alembic upgrade head
py -3 -m app.cli.create_admin --username admin
py -3 -m uvicorn app.main:app --reload --port 8000
```

Optional demo seed:

```powershell
py -3 scripts/seed_demo_data.py
```

### 2. Frontend

```powershell
cd frontend
npm ci
Copy-Item .env.example .env -Force
npm run dev
```

For normal local development:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_DEMO_MODE=false
```

### 3. Run Both Together

After installing frontend and backend dependencies, the root launcher starts both development servers:

```powershell
npm run dev
```

- API: `http://localhost:8000`
- Vite frontend: `http://localhost:5173`

## Public Demo Mode

The frontend supports a build-time demo mode:

```env
VITE_DEMO_MODE=true
```

When enabled:

- authentication is replaced by a local `Demo Viewer` session,
- dashboard data comes from `frontend/src/demoApi.ts`,
- no production API requests are made,
- inventory, sales, scraper, and other write operations are read-only,
- settings/admin controls are not exposed.

The GitHub Pages workflow builds this mode automatically.

## Scheduled Jobs

Daily forecast:

```powershell
cd backend
py -3 -m app.jobs.run_forecast_daily --horizon-days 30
```

Competitor scraper cycle:

```powershell
cd backend
py -3 -m app.jobs.run_scraper_cycle --verbose
```

## Testing

Backend:

```powershell
cd backend
py -3 -m pytest -q
```

Frontend:

```powershell
cd frontend
npm test
npm run build
```

Workspace launcher:

```powershell
npm run test:dev-stack
```

GitHub Actions runs these checks automatically on pushes to `main` and on pull requests.

## Configuration

### Backend

| Variable | Purpose |
|---|---|
| `STOCK_SAGE_ENV` | Runtime mode; hosted deployments should use `production` |
| `DATABASE_URL` | PostgreSQL/Neon connection string |
| `CORS_ALLOW_ORIGINS` | Comma-separated trusted frontend origins |
| `ADMIN_SESSION_SECRET` | Secret used to sign admin session cookies |
| `ADMIN_SESSION_TTL_SECONDS` | Session lifetime; defaults to 86400 seconds |
| `ADMIN_COOKIE_SECURE` | Must be `true` for HTTPS deployments |
| `ADMIN_COOKIE_SAMESITE` | Use `none` when frontend/backend are hosted cross-site |
| `STOCK_SAGE_IGNORE_DOTENV` | Ignore local `.env` loading in hosted environments |

`STOCK_SAGE_AUTH_DISABLED` is intended only for local/testing convenience and is ignored when `STOCK_SAGE_ENV=production`.

### Frontend

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | FastAPI base URL in normal application mode |
| `VITE_DEMO_MODE` | Enables the browser-only read-only demo |

Example environment files are committed; real `.env` files are ignored.

## Deployment

### Render backend

`render.yaml` configures the FastAPI service and requires these secrets/settings:

- `DATABASE_URL`
- `CORS_ALLOW_ORIGINS`
- `ADMIN_SESSION_SECRET`

The blueprint also enables production mode, secure cookies, and cross-site cookie handling.

### Vercel frontend

Set:

```env
VITE_API_BASE_URL=https://<your-render-service>
VITE_DEMO_MODE=false
```

### GitHub Pages preview

The `.github/workflows/pages.yml` workflow builds only the read-only demo. It intentionally receives no production secrets.

## Security Notes

- Never commit `.env` files, database URLs, session secrets, API keys, or production exports.
- Browser write requests with an `Origin` header are accepted only from origins listed in `CORS_ALLOW_ORIGINS`.
- Production mode refuses the local authentication-bypass flag.
- Public demo data is synthetic and isolated from production services.

## Project Context

Stock Sage began as a thesis-aligned prototype and has grown into a fuller inventory-intelligence application. The repository retains forecasting experiments and operational tooling because they document how model quality, scraper reliability, and inventory workflows are validated in practice.
