from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import time

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


def test_price_comparison_ignores_out_of_stock_offer_for_cheapest_benchmark() -> None:
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
        supplier = Supplier(name="Stock Aware Supplier", lead_time_days_default=2)
        db.add(supplier)
        db.flush()

        product = Product(
            sku="SKU-P-2",
            name="Beans",
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
                    competitor_sku="SKU-P-2",
                    competitor_price=3.00,
                    currency="USD",
                    in_stock=False,
                    scraped_at=now - timedelta(hours=1),
                ),
                CompetitorPriceSnapshot(
                    source_id=source_b.id,
                    product_id=product.id,
                    competitor_sku="SKU-P-2",
                    competitor_price=3.40,
                    currency="USD",
                    in_stock=True,
                    scraped_at=now - timedelta(hours=1),
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
    assert row["sku"] == "SKU-P-2"
    assert row["cheapest_competitor_price"] == "3.40"
    assert row["price_gap"] == "0.10"
    assert row["price_gap_pct"] == "2.94"

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_manual_scrape_job_reports_progress(monkeypatch) -> None:
    def fake_scraper(*, progress_callback=None, **_kwargs):
        if progress_callback:
            progress_callback(
                {
                    "event": "cycle_start",
                    "total_sources": 2,
                    "completed_sources": 0,
                    "inserted_rows": 0,
                    "message": "Scraper started with 2 sources and 1 active products.",
                }
            )
            progress_callback(
                {
                    "event": "source_start",
                    "source_index": 1,
                    "total_sources": 2,
                    "completed_sources": 0,
                    "source_name": "Shop A",
                    "inserted_rows": 0,
                    "message": "Checking Shop A (1/2).",
                }
            )
            progress_callback(
                {
                    "event": "source_done",
                    "source_index": 1,
                    "total_sources": 2,
                    "completed_sources": 1,
                    "source_name": "Shop A",
                    "inserted_rows": 2,
                    "message": "Finished Shop A: 2 snapshots saved.",
                }
            )
            progress_callback(
                {
                    "event": "cycle_done",
                    "total_sources": 2,
                    "completed_sources": 2,
                    "inserted_rows": 3,
                    "message": "Scraper completed with 3 snapshots saved.",
                }
            )
        return 3

    monkeypatch.setattr("app.api.routes_prices.run_scraper_cycle", fake_scraper)

    app = create_app()
    client = TestClient(app)

    start_response = client.post("/prices/scrape/jobs")
    assert start_response.status_code == 202
    job_id = start_response.json()["job_id"]

    final_payload = None
    for _ in range(20):
        status_response = client.get(f"/prices/scrape/jobs/{job_id}")
        assert status_response.status_code == 200
        final_payload = status_response.json()
        if final_payload["status"] == "completed":
            break
        time.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "completed"
    assert final_payload["progress_pct"] == 100
    assert final_payload["inserted_rows"] == 3
    assert final_payload["completed_sources"] == 2
    assert any("Shop A" in line for line in final_payload["logs"])
