from sqlalchemy import inspect

from app.db.session import engine, init_db


def test_core_tables_exist() -> None:
    init_db()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    expected = {
        "suppliers",
        "products",
        "inventory_balance",
        "stock_movements",
        "sales_transactions",
        "sales_items",
        "competitor_sources",
        "competitor_price_snapshots",
        "forecast_runs",
        "sku_forecasts",
        "reorder_recommendations",
    }
    assert expected.issubset(table_names)
