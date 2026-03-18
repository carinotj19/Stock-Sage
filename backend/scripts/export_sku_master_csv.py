from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import CompetitorSource, InventoryBalance, Product, Supplier  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


CSV_COLUMNS = [
    "sku",
    "name",
    "category",
    "supplier_name",
    "lead_time_days",
    "cost_price",
    "sell_price",
    "on_hand_qty",
    "reorder_min_qty",
    "reorder_multiple",
    "safety_stock",
    "active",
    "search_terms",
    "alias_terms",
]


def _load_scraper_maps() -> tuple[dict[str, str], dict[str, list[str]]]:
    with SessionLocal() as session:
        enabled_sources = list(session.scalars(select(CompetitorSource).where(CompetitorSource.enabled.is_(True))).all())

    query_override_map: dict[str, str] = {}
    sku_alias_map: dict[str, list[str]] = {}
    for source in enabled_sources:
        try:
            config = json.loads(source.scrape_config_json or "{}")
        except json.JSONDecodeError:
            continue

        qmap = config.get("query_override_map")
        if isinstance(qmap, dict):
            for sku, value in qmap.items():
                normalized_sku = str(sku).strip()
                normalized_value = str(value).strip()
                if normalized_sku and normalized_value:
                    query_override_map[normalized_sku] = normalized_value

        amap = config.get("sku_alias_map")
        if isinstance(amap, dict):
            for sku, aliases in amap.items():
                normalized_sku = str(sku).strip()
                if not normalized_sku:
                    continue
                if isinstance(aliases, list):
                    normalized_aliases = [str(alias).strip() for alias in aliases if str(alias).strip()]
                else:
                    normalized_aliases = [str(aliases).strip()] if str(aliases).strip() else []
                if normalized_aliases:
                    merged = set(sku_alias_map.get(normalized_sku, []))
                    merged.update(normalized_aliases)
                    sku_alias_map[normalized_sku] = sorted(merged)

    return query_override_map, sku_alias_map


def export_sku_master(out_file: Path) -> tuple[int, Path]:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    query_override_map, sku_alias_map = _load_scraper_maps()

    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(Product, Supplier, InventoryBalance)
                .outerjoin(Supplier, Supplier.id == Product.supplier_id)
                .outerjoin(InventoryBalance, InventoryBalance.product_id == Product.id)
                .order_by(Product.sku.asc())
            ).all()
        )

    with out_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for product, supplier, inventory in rows:
            sku = product.sku
            writer.writerow(
                {
                    "sku": sku,
                    "name": product.name,
                    "category": product.category or "",
                    "supplier_name": supplier.name if supplier else "",
                    "lead_time_days": supplier.lead_time_days_default if supplier else "",
                    "cost_price": str(product.cost_price),
                    "sell_price": str(product.sell_price),
                    "on_hand_qty": inventory.on_hand_qty if inventory else 0,
                    "reorder_min_qty": product.reorder_min_qty,
                    "reorder_multiple": product.reorder_multiple,
                    "safety_stock": product.safety_stock,
                    "active": "true" if product.active else "false",
                    "search_terms": query_override_map.get(sku, product.name),
                    "alias_terms": "|".join(sku_alias_map.get(sku, [])),
                }
            )

    return len(rows), out_file.resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export product/SKU master data to CSV for manual editing and re-import."
    )
    parser.add_argument(
        "--out",
        default="../data/sku_master.csv",
        help="Output CSV path (default: ../data/sku_master.csv from backend/).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    row_count, path = export_sku_master(Path(args.out))
    print(f"sku_master_rows_exported={row_count}")
    print(f"sku_master_csv={path}")


if __name__ == "__main__":
    main()
