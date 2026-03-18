import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = BACKEND_ROOT / ".env"
if os.getenv("STOCK_SAGE_IGNORE_DOTENV", "").strip().lower() not in {"1", "true", "yes"} and DOTENV_PATH.exists():
    # Local development can source config from backend/.env.
    load_dotenv(DOTENV_PATH, override=True)


def _build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _allow_test_sqlite() -> bool:
    return os.getenv("STOCK_SAGE_ALLOW_TEST_SQLITE", "").strip().lower() in {"1", "true", "yes"}


def _validate_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url

    if _allow_test_sqlite() and database_url.startswith("sqlite:///"):
        return database_url

    raise RuntimeError(
        "Only Neon/PostgreSQL is supported at runtime. Set DATABASE_URL in backend/.env "
        "using a postgresql+psycopg:// URL."
    )


def _require_database_url() -> str:
    database_url = _normalize_database_url(os.getenv("DATABASE_URL", "").strip())
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. Set it in environment variables (or backend/.env for local dev)."
        )
    return _validate_database_url(database_url)


DATABASE_URL = _require_database_url()
engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db.models import Base

    Base.metadata.create_all(bind=engine)
