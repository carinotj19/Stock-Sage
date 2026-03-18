from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import CompetitorSource, InventoryBalance, Product, Supplier  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


TRUTHY = {"1", "true", "yes", "y", "on"}
FALSY = {"0", "false", "no", "n", "off"}


def _parse_decimal(value: str | None, default: Decimal) -> Decimal:
    if value is None:
        return default
    raw = str(value).strip()
    if not raw:
        return default
    normalized = raw.replace("₱", "").replace(",", "").strip()
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return default


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    raw = str(value).strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if not raw:
        return default
    if raw in TRUTHY:
        return True
    if raw in FALSY:
        return False
    return default


def _split_terms(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _build_required_terms(search_terms: str) -> list[str]:
    tokens = _split_terms(search_terms)
    model_tokens = [token for token in tokens if any(ch.isdigit() for ch in token)]
    brand_tokens = [token for token in tokens if token.isalpha()]

    required_terms: list[str] = []
    if brand_tokens:
        required_terms.append(brand_tokens[0])
    required_terms.extend(model_tokens[:2])
    if required_terms:
        return required_terms
    return tokens[:2]


def _parse_alias_terms(value: str | None) -> list[str]:
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    aliases = [alias.strip() for alias in re.split(r"[|,;]+", raw) if alias.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        lowered = alias.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(alias)
    return deduped


def _upsert_supplier(session, supplier_name: str, lead_time_days: int) -> Supplier:
    supplier = session.scalars(select(Supplier).where(Supplier.name == supplier_name)).first()
    if supplier is None:
        supplier = Supplier(name=supplier_name, lead_time_days_default=lead_time_days)
        session.add(supplier)
        session.flush()
        return supplier

    supplier.lead_time_days_default = lead_time_days
    return supplier


def _apply_scraper_maps(
    session,
    query_override_map: dict[str, str],
    required_terms_map: dict[str, list[str]],
    sku_alias_map: dict[str, list[str]],
) -> int:
    updated = 0
    sources = list(session.scalars(select(CompetitorSource)).all())
    for source in sources:
        try:
            config = json.loads(source.scrape_config_json or "{}")
        except json.JSONDecodeError:
            continue

        mode = str(config.get("mode", "snapshot")).lower()
        if mode != "per_product_search":
            continue
        if not str(config.get("search_url_template", "")).strip():
            continue

        config["query_override_map"] = query_override_map
        config["required_terms_map"] = required_terms_map
        config["sku_alias_map"] = sku_alias_map
        source.scrape_config_json = json.dumps(config)
        updated += 1

    return updated


def import_sku_master(csv_path: Path, update_scraper_maps: bool = True) -> dict[str, int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    stats = {
        "rows_read": len(rows),
        "products_created": 0,
        "products_updated": 0,
        "inventory_rows_updated": 0,
        "suppliers_created_or_updated": 0,
        "sources_updated": 0,
        "rows_skipped": 0,
    }

    query_override_map: dict[str, str] = {}
    required_terms_map: dict[str, list[str]] = {}
    sku_alias_map: dict[str, list[str]] = {}
    touched_suppliers: set[str] = set()

    with SessionLocal() as session:
        for row in rows:
            sku = str(row.get("sku", "")).strip()
            name = str(row.get("name", "")).strip()
            if not sku or not name:
                stats["rows_skipped"] += 1
                continue

            category = str(row.get("category", "")).strip() or None
            supplier_name = str(row.get("supplier_name", "")).strip() or "Unassigned Supplier"
            lead_time_days = _parse_int(row.get("lead_time_days"), default=7)
            cost_price = _parse_decimal(row.get("cost_price"), default=Decimal("0.00"))
            sell_price = _parse_decimal(row.get("sell_price"), default=Decimal("0.00"))
            reorder_min_qty = max(1, _parse_int(row.get("reorder_min_qty"), default=1))
            reorder_multiple = max(1, _parse_int(row.get("reorder_multiple"), default=1))
            safety_stock = max(0, _parse_int(row.get("safety_stock"), default=0))
            active = _parse_bool(row.get("active"), default=True)
            on_hand_raw = str(row.get("on_hand_qty", "")).strip()
            search_terms = str(row.get("search_terms", "")).strip() or name
            alias_terms = _parse_alias_terms(row.get("alias_terms"))

            supplier = _upsert_supplier(session, supplier_name=supplier_name, lead_time_days=lead_time_days)
            touched_suppliers.add(supplier.name)

            product = session.scalars(select(Product).where(Product.sku == sku)).first()
            if product is None:
                product = Product(
                    sku=sku,
                    name=name,
                    category=category,
                    supplier_id=supplier.id,
                    cost_price=cost_price,
                    sell_price=sell_price,
                    reorder_min_qty=reorder_min_qty,
                    reorder_multiple=reorder_multiple,
                    safety_stock=safety_stock,
                    active=active,
                )
                session.add(product)
                session.flush()
                stats["products_created"] += 1
            else:
                product.name = name
                product.category = category
                product.supplier_id = supplier.id
                product.cost_price = cost_price
                product.sell_price = sell_price
                product.reorder_min_qty = reorder_min_qty
                product.reorder_multiple = reorder_multiple
                product.safety_stock = safety_stock
                product.active = active
                stats["products_updated"] += 1

            if on_hand_raw:
                on_hand_qty = max(0, _parse_int(on_hand_raw, default=0))
                inventory = session.get(InventoryBalance, product.id)
                if inventory is None:
                    inventory = InventoryBalance(product_id=product.id, on_hand_qty=on_hand_qty)
                    session.add(inventory)
                else:
                    inventory.on_hand_qty = on_hand_qty
                stats["inventory_rows_updated"] += 1

            query_override_map[sku] = search_terms
            required_terms_map[sku] = _build_required_terms(search_terms)
            sku_alias_map[sku] = alias_terms

        stats["suppliers_created_or_updated"] = len(touched_suppliers)

        if update_scraper_maps:
            stats["sources_updated"] = _apply_scraper_maps(
                session,
                query_override_map=query_override_map,
                required_terms_map=required_terms_map,
                sku_alias_map=sku_alias_map,
            )

        session.commit()

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import SKU master CSV and optionally refresh per-product search maps for scraper sources."
    )
    parser.add_argument(
        "--csv",
        default="../data/sku_master.csv",
        help="Input CSV path (default: ../data/sku_master.csv from backend/).",
    )
    parser.add_argument(
        "--skip-scraper-map-update",
        action="store_true",
        help="Skip updating query/alias maps inside competitor source scrape configs.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stats = import_sku_master(
        csv_path=Path(args.csv),
        update_scraper_maps=not args.skip_scraper_map_update,
    )
    print(
        "sku_master_import "
        f"rows_read={stats['rows_read']} "
        f"rows_skipped={stats['rows_skipped']} "
        f"products_created={stats['products_created']} "
        f"products_updated={stats['products_updated']} "
        f"inventory_rows_updated={stats['inventory_rows_updated']} "
        f"suppliers_touched={stats['suppliers_created_or_updated']} "
        f"sources_updated={stats['sources_updated']}"
    )


if __name__ == "__main__":
    main()
