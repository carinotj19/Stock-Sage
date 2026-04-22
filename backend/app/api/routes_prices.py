from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.run_scraper_cycle import run_scraper_cycle
from app.schemas.pricing import ManualScrapeJobRead, ManualScrapeRunResult, PriceComparisonRow
from app.services.pricing_service import PricingService


router = APIRouter(prefix="/prices", tags=["pricing"])
SCRAPE_JOB_LOG_LIMIT = 300
_scrape_jobs: dict[str, dict[str, Any]] = {}
_scrape_jobs_lock = Lock()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _append_job_log(job: dict[str, Any], message: str) -> None:
    timestamp = _utc_now().strftime("%H:%M:%S")
    logs = list(job.get("logs", []))
    logs.append(f"[{timestamp}] {message}")
    job["logs"] = logs[-SCRAPE_JOB_LOG_LIMIT:]


def _job_to_read(job_id: str, job: dict[str, Any]) -> ManualScrapeJobRead:
    return ManualScrapeJobRead(
        job_id=job_id,
        status=job["status"],
        progress_pct=job["progress_pct"],
        current_source=job.get("current_source"),
        inserted_rows=job["inserted_rows"],
        total_sources=job["total_sources"],
        completed_sources=job["completed_sources"],
        started_at=job["started_at"],
        finished_at=job.get("finished_at"),
        message=job["message"],
        error=job.get("error"),
        logs=list(job.get("logs", [])),
    )


def _get_job_or_404(job_id: str) -> dict[str, Any]:
    with _scrape_jobs_lock:
        job = _scrape_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape job not found.")
        return dict(job)


def _update_job(job_id: str, **updates: Any) -> None:
    with _scrape_jobs_lock:
        job = _scrape_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)
        message = updates.get("message")
        if isinstance(message, str) and message:
            _append_job_log(job, message)


def _progress_pct(event: dict[str, Any]) -> int:
    total_sources = int(event.get("total_sources") or 0)
    completed_sources = int(event.get("completed_sources") or 0)
    if event.get("event") == "cycle_done":
        return 100
    if total_sources <= 0:
        return 5
    # Keep a little room at the start and end for queued/finalization states.
    return min(95, max(5, 5 + round((completed_sources / total_sources) * 90)))


def _handle_scraper_progress(job_id: str, event: dict[str, Any]) -> None:
    status_value = "running"
    if event.get("event") == "cycle_done":
        status_value = "completed"

    _update_job(
        job_id,
        status=status_value,
        progress_pct=_progress_pct(event),
        current_source=event.get("source_name"),
        inserted_rows=int(event.get("inserted_rows") or 0),
        total_sources=int(event.get("total_sources") or 0),
        completed_sources=int(event.get("completed_sources") or 0),
        message=str(event.get("message") or "Scraper progress updated."),
    )


def _run_scrape_job(job_id: str) -> None:
    _update_job(job_id, status="running", progress_pct=2, message="Manual web scraping started.")
    try:
        inserted_rows = run_scraper_cycle(
            verbose=False,
            progress_callback=lambda event: _handle_scraper_progress(job_id, event),
        )
        _update_job(
            job_id,
            status="completed",
            progress_pct=100,
            current_source=None,
            inserted_rows=inserted_rows,
            finished_at=_utc_now(),
            message=f"Manual web scraping completed. {inserted_rows} competitor price snapshots saved.",
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            progress_pct=100,
            current_source=None,
            finished_at=_utc_now(),
            error=str(exc),
            message=f"Manual web scraping failed: {exc}",
        )


@router.get("/compare", response_model=list[PriceComparisonRow])
def compare_prices(db: Session = Depends(get_db)) -> list[PriceComparisonRow]:
    service = PricingService(db)
    return service.compare_prices()


@router.post("/scrape", response_model=ManualScrapeRunResult)
def run_manual_scrape(db: Session = Depends(get_db)) -> ManualScrapeRunResult:
    inserted_rows = run_scraper_cycle(db=db, verbose=False)
    return ManualScrapeRunResult(
        inserted_rows=inserted_rows,
        ran_at=datetime.now(UTC),
        message=f"Manual web scraping completed with {inserted_rows} snapshots saved.",
    )


@router.post("/scrape/jobs", response_model=ManualScrapeJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_manual_scrape_job() -> ManualScrapeJobRead:
    job_id = uuid4().hex
    started_at = _utc_now()
    with _scrape_jobs_lock:
        _scrape_jobs[job_id] = {
            "status": "queued",
            "progress_pct": 0,
            "current_source": None,
            "inserted_rows": 0,
            "total_sources": 0,
            "completed_sources": 0,
            "started_at": started_at,
            "finished_at": None,
            "message": "Manual web scraping queued.",
            "error": None,
            "logs": [f"[{started_at.strftime('%H:%M:%S')}] Manual web scraping queued."],
        }
        job = dict(_scrape_jobs[job_id])

    thread = Thread(target=_run_scrape_job, args=(job_id,), daemon=True)
    thread.start()
    return _job_to_read(job_id, job)


@router.get("/scrape/jobs/{job_id}", response_model=ManualScrapeJobRead)
def get_manual_scrape_job(job_id: str) -> ManualScrapeJobRead:
    return _job_to_read(job_id, _get_job_or_404(job_id))
