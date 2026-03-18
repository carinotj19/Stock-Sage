from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, CompetitorPriceSnapshot, CompetitorSource, Product, Supplier
from app.db.session import get_db
from app.main import create_app


TEST_DATABASE_URL = "sqlite:///./data/test_price_comparison_api.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def test_price_comparison_uses_latest_snapshot_per_source() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Pricing Supplier", lead_time_days_default=2)
        db.add(supplier)
        db.flush()

        product = Product(
            sku="SKU-P-1",
            name="Rice",
            supplier_id=supplier.id,
            cost_price=2.2,
            sell_price=3.5,
            reorder_min_qty=5,
            reorder_multiple=5,
            safety_stock=2,
            active=True,
        )
        db.add(product)
        db.flush()

        source_a = CompetitorSource(name="Shop A", base_url="http://a.test", enabled=True)
        source_b = CompetitorSource(name="Shop B", base_url="http://b.test", enabled=True)
        db.add_all([source_a, source_b])
        db.flush()

        now = datetime.now(timezone.utc)
        db.add_all(
            [
                CompetitorPriceSnapshot(
                    source_id=source_a.id,
                    product_id=product.id,
                    competitor_sku="SKU-P-1",
                    competitor_price=3.20,
                    currency="USD",
                    in_stock=True,
                    scraped_at=now - timedelta(hours=3),
                ),
                CompetitorPriceSnapshot(
                    source_id=source_a.id,
                    product_id=product.id,
                    competitor_sku="SKU-P-1",
                    competitor_price=3.00,
                    currency="USD",
                    in_stock=True,
                    scraped_at=now - timedelta(hours=1),
                ),
                CompetitorPriceSnapshot(
                    source_id=source_b.id,
                    product_id=product.id,
                    competitor_sku="SKU-P-1",
                    competitor_price=3.40,
                    currency="USD",
                    in_stock=True,
                    scraped_at=now - timedelta(hours=2),
                ),
            ]
        )
        db.commit()

    client = TestClient(app)
    response = client.get("/prices/compare")
    assert response.status_code == 200

    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["sku"] == "SKU-P-1"
    assert row["store_price"] == "3.50"
    assert row["cheapest_competitor_price"] == "3.00"
    assert row["price_gap"] == "0.50"
    assert row["price_gap_pct"] == "16.67"
    assert row["is_above_cheapest"] is True
    assert len(row["competitor_prices"]) == 2

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

