#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cat <<EOF
# Add these entries to your crontab (crontab -e)
# Daily forecast at 01:00
0 1 * * * cd "$PROJECT_ROOT" && py -3 -m app.jobs.run_forecast_daily --horizon-days 30 >> "$PROJECT_ROOT/data/forecast.log" 2>&1

# Scraper every 3 hours
0 */3 * * * cd "$PROJECT_ROOT" && py -3 -m app.jobs.run_scraper_cycle >> "$PROJECT_ROOT/data/scraper.log" 2>&1
EOF

