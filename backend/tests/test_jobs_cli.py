import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, ForecastRun


def _build_test_engine(database_url: str):
    return create_engine(database_url, connect_args={"check_same_thread": False})


def test_job_cli_commands_execute_successfully() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    db_file = backend_root / "data" / "test_jobs_cli.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    test_database_url = f"sqlite:///{db_file.as_posix()}"

    engine = _build_test_engine(test_database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    env = os.environ.copy()
    env["DATABASE_URL"] = test_database_url
    env["STOCK_SAGE_IGNORE_DOTENV"] = "1"
    env["STOCK_SAGE_ALLOW_TEST_SQLITE"] = "1"

    forecast_run = subprocess.run(
        ["py", "-3", "-m", "app.jobs.run_forecast_daily", "--horizon-days", "5"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "forecast_run_id=" in forecast_run.stdout

    scraper_run = subprocess.run(
        ["py", "-3", "-m", "app.jobs.run_scraper_cycle"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "scraper_rows_inserted=" in scraper_run.stdout

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    with SessionLocal() as db:
        run_count = db.scalar(select(func.count()).select_from(ForecastRun))
        assert run_count == 1

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
