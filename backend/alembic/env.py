from __future__ import annotations

from logging.config import fileConfig
import os
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from app.db.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if os.getenv("STOCK_SAGE_IGNORE_DOTENV", "").strip().lower() not in {"1", "true", "yes"}:
    dotenv_path = BACKEND_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=True)

database_url = os.getenv("DATABASE_URL", "").strip()
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)

if not database_url:
    raise RuntimeError(
        "DATABASE_URL is required for migrations. "
        "Set it in environment variables (or backend/.env for local dev)."
    )

if not database_url.startswith("postgresql+psycopg://"):
    raise RuntimeError(
        "Only Neon/PostgreSQL is supported for migrations. "
        "Use a postgresql+psycopg:// DATABASE_URL."
    )
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
