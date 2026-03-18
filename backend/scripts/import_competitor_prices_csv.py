from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import CompetitorPriceSnapshot, CompetitorSource, Product  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


TRUTHY = {"1", "true", "yes", "y", "on"}
FALSY = {"0", "false", "no", "n", "off"}


def _parse_price(value: str | None) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("₱", "").replace(",", "").strip()
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    if raw in TRUTHY:
        return True
    if raw in FALSY:
        return False
    return None


def _parse_timestamp(value: str | None) -> datetime:
    if value is None or not str(value).strip():
        return datetime.now(timezone.utc)

    raw = str(value).strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_base_url(url: str | None) -> str:
    if url is None:
        return "manual://import"
    raw = str(url).strip()
    if not raw:
        return "manual://import"
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "manual://import"


def _get_or_create_source(session, source_name: str, base_url: str) -> CompetitorSource:
    source = session.scalars(select(CompetitorSource).where(CompetitorSource.name == source_name)).first()
    if source is not None:
        return source

    source = CompetitorSource(
        name=source_name,
        base_url=base_url,
        scrape_config_json=json.dumps({"mode": "manual_import", "ingestion": "csv"}),
        enabled=False,
    )
    session.add(source)
    session.flush()
    return source


def import_competitor_prices(csv_path: Path, default_source_name: str) -> dict[str, int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    stats = {
        "rows_read": len(rows),
        "rows_inserted": 0,
        "rows_skipped": 0,
        "missing_sku_rows": 0,
        "invalid_price_rows": 0,
        "sources_created": 0,
    }

    with SessionLocal() as session:
        source_cache: dict[str, CompetitorSource] = {}
        for line_number, row in enumerate(rows, start=2):
            sku = str(row.get("sku", "")).strip()
            if not sku:
                stats["rows_skipped"] += 1
                stats["missing_sku_rows"] += 1
                continue

            product = session.scalars(select(Product).where(Product.sku == sku)).first()
            if product is None:
                stats["rows_skipped"] += 1
                stats["missing_sku_rows"] += 1
                continue

            price = _parse_price(row.get("competitor_price"))
            if price is None:
                stats["rows_skipped"] += 1
                stats["invalid_price_rows"] += 1
                continue

            source_name = str(row.get("source_name", "")).strip() or default_source_name
            url = str(row.get("url", "")).strip()
            if source_name not in source_cache:
                existing = session.scalars(select(CompetitorSource).where(CompetitorSource.name == source_name)).first()
                if existing is None:
                    source = _get_or_create_source(session, source_name=source_name, base_url=_to_base_url(url))
                    stats["sources_created"] += 1
                    source_cache[source_name] = source
                else:
                    source_cache[source_name] = existing
            source = source_cache[source_name]

            snapshot = CompetitorPriceSnapshot(
                source_id=source.id,
                product_id=product.id,
                competitor_sku=str(row.get("competitor_sku", "")).strip() or None,
                competitor_price=price,
                currency=str(row.get("currency", "")).strip() or "PHP",
                in_stock=_parse_bool(row.get("in_stock")),
                scraped_at=_parse_timestamp(row.get("captured_at")),
                raw_payload_json=json.dumps(
                    {
                        "manual_import": True,
                        "line_number": line_number,
                        "competitor_name": str(row.get("competitor_name", "")).strip() or None,
                        "url": url or None,
                        "notes": str(row.get("notes", "")).strip() or None,
                        "import_file": str(csv_path),
                    }
                ),
            )
            session.add(snapshot)
            stats["rows_inserted"] += 1

        session.commit()

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import competitor price snapshots from CSV (manual fallback ingestion)."
    )
    parser.add_argument(
        "--csv",
        default="../data/competitor_prices_manual.csv",
        help="Input CSV path (default: ../data/competitor_prices_manual.csv from backend/).",
    )
    parser.add_argument(
        "--default-source",
        default="Marketplace Manual Feed PH",
        help="Source name used when source_name column is blank.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stats = import_competitor_prices(
        csv_path=Path(args.csv),
        default_source_name=args.default_source,
    )
    print(
        "manual_competitor_import "
        f"rows_read={stats['rows_read']} "
        f"rows_inserted={stats['rows_inserted']} "
        f"rows_skipped={stats['rows_skipped']} "
        f"missing_sku_rows={stats['missing_sku_rows']} "
        f"invalid_price_rows={stats['invalid_price_rows']} "
        f"sources_created={stats['sources_created']}"
    )


if __name__ == "__main__":
    main()
