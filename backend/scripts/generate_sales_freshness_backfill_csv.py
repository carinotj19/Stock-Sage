from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import random
import sys

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import Product  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.jobs.run_forecast_daily import _dense_daily_units_series, _load_sales_history  # noqa: E402
from scripts.import_sales_history_csv import (  # noqa: E402
    _replace_prefixed_import_rows,
    import_sales_history_csv,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a stale-SKU sales backfill CSV for recent days. "
            "Mode 'template' creates empty qty rows for manual POS fill. "
            "Mode 'synthetic' fills qty using recent observed demand."
        )
    )
    parser.add_argument(
        "--out",
        default="../data/sales_freshness_backfill.csv",
        help="Output CSV path (default: ../data/sales_freshness_backfill.csv from backend/).",
    )
    parser.add_argument(
        "--mode",
        choices=["template", "synthetic"],
        default="template",
        help="Backfill row generation mode (default: template).",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=14,
        help="Consider SKU stale if latest sales date is older than this many days (default: 14).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Generate rows for recent N days up to today (default: 14).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=60,
        help="Synthetic mode demand baseline lookback window (default: 60).",
    )
    parser.add_argument(
        "--receipt-prefix",
        default="FRESH",
        help="Receipt prefix for generated rows (default: FRESH).",
    )
    parser.add_argument(
        "--payment-method",
        default="freshness_backfill",
        help="Payment method value to write in CSV (default: freshness_backfill).",
    )
    parser.add_argument(
        "--apply-import",
        action="store_true",
        help="Immediately import generated CSV into DB using import_sales_history_csv.",
    )
    parser.add_argument(
        "--replace-prefix",
        action="store_true",
        help="When --apply-import, delete existing rows using same receipt prefix before import.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for synthetic mode (default: 42).",
    )
    return parser.parse_args()


def _estimate_synthetic_qty(
    *,
    dense_units,
    lookback_days: int,
    rng: random.Random,
) -> int:
    recent = dense_units.tail(max(1, lookback_days))
    non_zero = recent[recent > 0.0]
    if non_zero.empty:
        return 1
    mean_units = float(non_zero.mean())
    lower = max(1, int(round(mean_units * 0.60)))
    upper = max(lower, int(round(mean_units * 1.40)))
    return int(rng.randint(lower, upper))


def main() -> None:
    args = _parse_args()
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stale_days = max(1, int(args.stale_days))
    days = max(1, int(args.days))
    lookback_days = max(1, int(args.lookback_days))
    receipt_prefix = str(args.receipt_prefix).strip().upper() or "FRESH"
    payment_method = str(args.payment_method).strip() or "freshness_backfill"
    mode = str(args.mode).strip().lower()
    today = date.today()
    target_start = today - timedelta(days=days - 1)
    rng = random.Random(int(args.seed))

    rows: list[dict[str, str]] = []
    stale_sku_count = 0
    candidate_sku_count = 0

    with SessionLocal() as session:
        products = list(session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sku.asc())).all())

        for product in products:
            sales_history = _load_sales_history(session, product.id)
            dense_units = _dense_daily_units_series(sales_history)
            if dense_units.empty:
                last_history_date = None
                history_lag_days = stale_days + 1
            else:
                last_history_date = dense_units.index.max().date()
                history_lag_days = int((today - last_history_date).days)

            if history_lag_days <= stale_days:
                continue

            stale_sku_count += 1
            if last_history_date is None:
                start_date = target_start
            else:
                start_date = max(target_start, last_history_date + timedelta(days=1))
            if start_date > today:
                continue

            candidate_sku_count += 1
            cursor = start_date
            while cursor <= today:
                qty_sold = ""
                if mode == "synthetic":
                    qty_sold = str(
                        _estimate_synthetic_qty(
                            dense_units=dense_units,
                            lookback_days=lookback_days,
                            rng=rng,
                        )
                    )
                rows.append(
                    {
                        "date": cursor.isoformat(),
                        "sku": product.sku,
                        "qty_sold": qty_sold,
                        "unit_sell_price": str(Decimal(product.sell_price)),
                        "payment_method": payment_method,
                        "receipt_no": f"{receipt_prefix}-{product.sku}-{cursor.strftime('%Y%m%d')}",
                    }
                )
                cursor += timedelta(days=1)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "sku", "qty_sold", "unit_sell_price", "payment_method", "receipt_no"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(
        "sales_freshness_backfill "
        f"mode={mode} stale_days={stale_days} days={days} "
        f"active_stale_skus={stale_sku_count} candidate_skus={candidate_sku_count} "
        f"rows_written={len(rows)} out={output_path.resolve()}"
    )

    if not args.apply_import:
        return

    if len(rows) == 0:
        print(
            "sales_freshness_backfill_import "
            "skipped=true reason=no_generated_rows"
        )
        return

    deleted_items = 0
    deleted_transactions = 0
    if args.replace_prefix:
        deleted_items, deleted_transactions = _replace_prefixed_import_rows(receipt_prefix)

    import_stats = import_sales_history_csv(
        csv_path=output_path,
        receipt_prefix=receipt_prefix,
        default_payment_method=payment_method,
        sold_at_hour_utc=12,
    )
    print(
        "sales_freshness_backfill_import "
        f"rows_read={import_stats['rows_read']} rows_inserted={import_stats['rows_inserted']} "
        f"transactions_created={import_stats['transactions_created']} rows_skipped={import_stats['rows_skipped']} "
        f"invalid_qty_rows={import_stats['invalid_qty_rows']} "
        f"deleted_items={deleted_items} deleted_transactions={deleted_transactions}"
    )


if __name__ == "__main__":
    main()
