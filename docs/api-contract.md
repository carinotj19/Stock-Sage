# Stock Sage API Contract

Base URL: `http://localhost:8000`

Database runtime: Neon PostgreSQL via `DATABASE_URL` in `backend/.env`.

## Health

- `GET /health`
  - `200 OK`
  - Body: `{"status":"ok"}`

## Authentication

- `GET /auth/me`
  - Returns whether the current browser session is authenticated and configured.
  - Response includes `authenticated`, `configured`, `username`, `display_name`, and `role`.
- `POST /auth/login`
  - Body: `{ "username": "...", "password": "..." }`
  - Sets an HTTP-only signed session cookie on success.
- `POST /auth/logout`
  - Clears the session cookie.

## Settings

Admin-only endpoints:

- `GET /settings/system`
  - Returns auth/account summary for the Settings System tab.
- `GET /settings/accounts`
  - Lists admin and staff accounts.
- `POST /settings/accounts`
  - Creates an admin or staff account.
  - Body: `{ "username": "...", "display_name": "...", "email": null, "role": "staff", "password": "..." }`
- `DELETE /settings/accounts/{account_id}`
  - Deactivates an account.
- `GET /settings/audit-logs`
  - Lists audit log records.

## Inventory

- `POST /suppliers`
- `POST /products`
- `GET /products`
- `PATCH /products/{product_id}`
- `POST /inventory/adjust`

## Sales

- `POST /sales`

## Dashboard

- `GET /dashboard/low-stock`
- `GET /dashboard/sales-trend?days=30`
- `GET /dashboard/kpis`
- `GET /dashboard/scraper-source-quality?window_hours=24`
- `GET /dashboard/stockout-dates`
- `GET /dashboard/forecast-report?include_details=true&evaluation_days=7`
  - Response includes:
    - `evaluation` (backward-compatible full-catalog metrics)
    - `evaluation_full` (all evaluated SKUs)
    - `evaluation_mature` (mature SKU subset only)
    - `evaluation_non_mature` (non-mature SKU subset only)
    - `mature_sku_criteria` (text describing maturity thresholds)
    - `summary.mature_sku_count`, `summary.non_mature_sku_count`
    - `summary.high_confidence_count`, `summary.high_confidence_mature_count`, `summary.high_confidence_non_mature_count`
    - `qa_summary` and `qa_report` (from forecast run notes)

## Pricing

- `GET /prices/compare`
  - Currency for competitor snapshots defaults to `PHP`.
  - Comparison uses latest snapshot per competitor source.

## Job CLIs

- `py -3 -m app.jobs.run_forecast_daily --horizon-days 30`
- `py -3 -m app.jobs.run_forecast_daily --horizon-days 30 --qa-mode warn`
  - `--qa-mode` supports `off|warn|strict`
  - CLI prints `forecast_data_qa_summary=...` and `forecast_data_qa_report=...`
- `py -3 -m app.jobs.run_scraper_cycle`
- `py -3 -m app.jobs.run_scraper_cycle --verbose` (debug logging)

Notes:

- Inventory, sales, dashboard, and pricing endpoints require authenticated admin or staff session.
- Settings endpoints require an authenticated admin session.
- Scraper runs per-product search for all active inventory items across enabled sources.
- Source-level failures are non-fatal and logged as `scraper_source_error` / `scraper_source_warning`.
