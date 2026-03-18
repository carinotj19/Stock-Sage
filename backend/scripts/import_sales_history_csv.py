from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

from sqlalchemy import delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import Product, SalesItem, SalesTransaction  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _parse_date_or_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed_dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed_dt = datetime.fromisoformat(f"{raw}T00:00:00")
        except ValueError:
            return None

    if parsed_dt.tzinfo is None:
        return parsed_dt.replace(tzinfo=timezone.utc)
    return parsed_dt.astimezone(timezone.utc)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    normalized = "".join(ch for ch in raw if ch.isdigit() or ch in {".", "-"})
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _replace_prefixed_import_rows(receipt_prefix: str) -> tuple[int, int]:
    pattern = f"{receipt_prefix}-%"
    with SessionLocal() as session:
        tx_ids = list(
            session.scalars(select(SalesTransaction.id).where(SalesTransaction.receipt_no.like(pattern))).all()
        )
        if not tx_ids:
            return (0, 0)

        deleted_items = session.execute(
            delete(SalesItem).where(SalesItem.sales_transaction_id.in_(tx_ids))
        ).rowcount or 0
        deleted_transactions = session.execute(
            delete(SalesTransaction).where(SalesTransaction.id.in_(tx_ids))
        ).rowcount or 0
        session.commit()
        return (int(deleted_items), int(deleted_transactions))


def import_sales_history_csv(
    *,
    csv_path: Path,
    receipt_prefix: str,
    default_payment_method: str,
    sold_at_hour_utc: int,
) -> dict[str, int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    stats = {
        "rows_read": len(rows),
        "rows_inserted": 0,
        "transactions_created": 0,
        "rows_skipped": 0,
        "missing_sku_rows": 0,
        "invalid_date_rows": 0,
        "invalid_qty_rows": 0,
        "invalid_price_rows": 0,
        "receipt_reused_rows": 0,
        "receipt_collision_rows": 0,
        "receipt_timestamp_conflicts": 0,
    }

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    sold_at_hour = max(0, min(23, int(sold_at_hour_utc)))

    with SessionLocal() as session:
        products = {
            product.sku.lower(): product
            for product in session.scalars(select(Product).where(Product.active.is_(True))).all()
        }
        transaction_cache: dict[str, SalesTransaction] = {}
        provided_receipts = sorted(
            {
                str(row.get("receipt_no", "")).strip()
                for row in rows
                if str(row.get("receipt_no", "")).strip()
            }
        )
        existing_receipts = set()
        if provided_receipts:
            existing_receipts = set(
                session.scalars(
                    select(SalesTransaction.receipt_no).where(SalesTransaction.receipt_no.in_(provided_receipts))
                ).all()
            )

        for line_number, row in enumerate(rows, start=2):
            sku = str(row.get("sku", "")).strip()
            product = products.get(sku.lower())
            if product is None:
                stats["rows_skipped"] += 1
                stats["missing_sku_rows"] += 1
                continue

            sold_at_raw = row.get("sold_at") or row.get("date")
            sold_at = _parse_date_or_datetime(sold_at_raw)
            if sold_at is None:
                stats["rows_skipped"] += 1
                stats["invalid_date_rows"] += 1
                continue
            sold_at = sold_at.replace(hour=sold_at_hour, minute=0, second=0, microsecond=0)

            qty = _parse_int(row.get("qty_sold") or row.get("qty"))
            if qty is None or qty <= 0:
                stats["rows_skipped"] += 1
                stats["invalid_qty_rows"] += 1
                continue

            unit_price = _parse_decimal(row.get("unit_sell_price"))
            if unit_price is None:
                unit_price = product.sell_price
            if unit_price <= 0:
                stats["rows_skipped"] += 1
                stats["invalid_price_rows"] += 1
                continue

            receipt_no = str(row.get("receipt_no", "")).strip()
            if not receipt_no:
                receipt_no = f"{receipt_prefix}-{run_stamp}-{line_number:06d}"
            elif receipt_no in existing_receipts and receipt_no not in transaction_cache:
                receipt_no = f"{receipt_no}-IMP-{run_stamp}-{line_number:06d}"
                stats["receipt_collision_rows"] += 1

            payment_method = str(row.get("payment_method", "")).strip() or default_payment_method
            line_total = unit_price * qty

            transaction = transaction_cache.get(receipt_no)
            if transaction is None:
                transaction = SalesTransaction(
                    receipt_no=receipt_no,
                    sold_at=sold_at,
                    total_amount=Decimal("0.00"),
                    payment_method=payment_method,
                )
                session.add(transaction)
                session.flush()
                transaction_cache[receipt_no] = transaction
                stats["transactions_created"] += 1
            else:
                stats["receipt_reused_rows"] += 1
                if transaction.sold_at.date() != sold_at.date():
                    stats["receipt_timestamp_conflicts"] += 1

            item = SalesItem(
                sales_transaction_id=transaction.id,
                product_id=product.id,
                qty=qty,
                unit_sell_price=unit_price,
                line_total=line_total,
            )
            session.add(item)
            transaction.total_amount += line_total
            stats["rows_inserted"] += 1

        session.commit()

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import historical daily sales rows for forecasting (public dataset or POS export)."
    )
    parser.add_argument(
        "--csv",
        default="../data/sales_history_import.csv",
        help="Input CSV path (default: ../data/sales_history_import.csv from backend/).",
    )
    parser.add_argument(
        "--receipt-prefix",
        default="DATASET",
        help="Prefix used for generated receipt numbers (default: DATASET).",
    )
    parser.add_argument(
        "--replace-prefix",
        action="store_true",
        help="Delete previously imported rows that used the same receipt prefix before importing.",
    )
    parser.add_argument(
        "--default-payment-method",
        default="dataset_import",
        help="Payment method value when column is blank (default: dataset_import).",
    )
    parser.add_argument(
        "--sold-at-hour-utc",
        type=int,
        default=12,
        help="Hour (0-23 UTC) to stamp daily rows when date is provided (default: 12).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    receipt_prefix = str(args.receipt_prefix).strip().upper() or "DATASET"

    deleted_items = 0
    deleted_transactions = 0
    if args.replace_prefix:
        deleted_items, deleted_transactions = _replace_prefixed_import_rows(receipt_prefix)

    stats = import_sales_history_csv(
        csv_path=Path(args.csv),
        receipt_prefix=receipt_prefix,
        default_payment_method=str(args.default_payment_method).strip() or "dataset_import",
        sold_at_hour_utc=args.sold_at_hour_utc,
    )

    print(
        "sales_history_import "
        f"rows_read={stats['rows_read']} "
        f"rows_inserted={stats['rows_inserted']} "
        f"transactions_created={stats['transactions_created']} "
        f"rows_skipped={stats['rows_skipped']} "
        f"missing_sku_rows={stats['missing_sku_rows']} "
        f"invalid_date_rows={stats['invalid_date_rows']} "
        f"invalid_qty_rows={stats['invalid_qty_rows']} "
        f"invalid_price_rows={stats['invalid_price_rows']} "
        f"receipt_reused_rows={stats['receipt_reused_rows']} "
        f"receipt_collision_rows={stats['receipt_collision_rows']} "
        f"receipt_timestamp_conflicts={stats['receipt_timestamp_conflicts']} "
        f"deleted_items={deleted_items} "
        f"deleted_transactions={deleted_transactions}"
    )


if __name__ == "__main__":
    main()
