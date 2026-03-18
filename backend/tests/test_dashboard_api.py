from datetime import date, datetime, timedelta, timezone
from collections.abc import Generator
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, CompetitorPriceSnapshot, CompetitorSource, ForecastRun, ReorderRecommendation
from app.db.session import get_db
from app.main import create_app


TEST_DATABASE_URL = "sqlite:///./data/test_dashboard_api.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def _build_test_session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_dashboard_endpoints() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = _build_test_session(engine)
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
    client = TestClient(app)

    supplier_resp = client.post("/suppliers", json={"name": "Dashboard Supplier", "lead_time_days_default": 3})
    supplier_id = supplier_resp.json()["id"]

    low_stock_product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-LOW-1",
            "name": "Low Stock Item",
            "supplier_id": supplier_id,
            "cost_price": "2.00",
            "sell_price": "3.00",
            "reorder_min_qty": 4,
            "safety_stock": 2,
            "initial_stock": 6,
        },
    )
    low_stock_product_id = low_stock_product_resp.json()["id"]

    client.post(
        "/products",
        json={
            "sku": "SKU-HIGH-1",
            "name": "High Stock Item",
            "supplier_id": supplier_id,
            "cost_price": "1.00",
            "sell_price": "2.00",
            "reorder_min_qty": 2,
            "safety_stock": 1,
            "initial_stock": 20,
        },
    )

    client.post(
        "/sales",
        json={
            "receipt_no": "R-DASH-001",
            "payment_method": "cash",
            "items": [{"product_id": low_stock_product_id, "qty": 2}],
        },
    )

    with TestingSessionLocal() as db:
        run = ForecastRun(model_version="NaiveMA", horizon_days=30)
        db.add(run)
        db.flush()
        source = CompetitorSource(
            name="Dashboard Source",
            base_url="https://source.example",
            enabled=True,
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "runtime_state": {
                        "last_run_inserted": 0,
                        "last_run_attempted_products": 2,
                        "consecutive_zero_insert_runs": 2,
                    },
                }
            ),
        )
        db.add(source)
        db.flush()
        db.add(
            ReorderRecommendation(
                run_id=run.id,
                product_id=low_stock_product_id,
                predicted_stockout_date=date(2026, 1, 15),
                reorder_point=8,
                suggested_qty=10,
                confidence_score=0.75,
            )
        )
        db.add(
            CompetitorPriceSnapshot(
                source_id=source.id,
                product_id=low_stock_product_id,
                competitor_price=2.95,
                currency="PHP",
                in_stock=True,
                scraped_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.commit()

    low_stock_resp = client.get("/dashboard/low-stock")
    assert low_stock_resp.status_code == 200
    low_stock_rows = low_stock_resp.json()
    assert len(low_stock_rows) == 1
    assert low_stock_rows[0]["sku"] == "SKU-LOW-1"

    trend_resp = client.get("/dashboard/sales-trend?days=30")
    assert trend_resp.status_code == 200
    trend_rows = trend_resp.json()
    assert len(trend_rows) == 1
    assert trend_rows[0]["total_sales"] == "6.00"
    assert trend_rows[0]["transactions"] == 1

    kpi_resp = client.get("/dashboard/kpis")
    assert kpi_resp.status_code == 200
    kpi_data = kpi_resp.json()
    assert kpi_data["sku_count"] == 2
    assert kpi_data["low_stock_count"] == 1
    assert kpi_data["today_sales"] == "6.00"

    stockout_resp = client.get("/dashboard/stockout-dates")
    assert stockout_resp.status_code == 200
    stockout_rows = stockout_resp.json()
    assert len(stockout_rows) == 1
    assert stockout_rows[0]["sku"] == "SKU-LOW-1"
    assert stockout_rows[0]["suggested_qty"] == 10

    source_quality_resp = client.get("/dashboard/scraper-source-quality?window_hours=24")
    assert source_quality_resp.status_code == 200
    source_quality_rows = source_quality_resp.json()
    assert len(source_quality_rows) == 1
    assert source_quality_rows[0]["source_name"] == "Dashboard Source"
    assert source_quality_rows[0]["matched_skus_24h"] == 1
    assert source_quality_rows[0]["snapshots_24h"] == 1
    assert source_quality_rows[0]["coverage_pct_24h"] == 50.0
    assert source_quality_rows[0]["effective_coverage_pct_24h"] == 25.0
    assert source_quality_rows[0]["stale"] is False
    assert source_quality_rows[0]["degraded"] is True

    report_resp = client.get("/dashboard/forecast-report?include_details=true&evaluation_days=7")
    assert report_resp.status_code == 200
    report_payload = report_resp.json()
    assert report_payload["run_id"] == run.id
    assert report_payload["summary"]["sku_count"] == 1
    assert report_payload["summary"]["reorder_required_count"] == 1
    assert report_payload["evaluation"]["evaluation_days"] == 7
    assert report_payload["evaluation_full"]["evaluation_days"] == 7
    assert report_payload["evaluation_mature"]["evaluation_days"] == 7
    assert report_payload["evaluation"] == report_payload["evaluation_full"]
    assert "history_days>=" in report_payload["mature_sku_criteria"]
    assert report_payload["explainability_rows"][0]["sku"] == "SKU-LOW-1"
    assert "reorder recommendation is 10 units" in report_payload["explainability_rows"][0]["explanation"].lower()
    assert report_payload["markdown_report"].startswith("# Forecast Metrics Report")

    item_forecast_resp = client.get(f"/dashboard/item-forecast/{low_stock_product_id}")
    assert item_forecast_resp.status_code == 200
    item_forecast = item_forecast_resp.json()
    assert item_forecast["sku"] == "SKU-LOW-1"
    assert item_forecast["in_stock"] == 4
    assert item_forecast["reorder_qty"] == 10
    assert item_forecast["confidence_pct"] == 75.0
    assert isinstance(item_forecast["demand_points"], list)
    assert "order 10 units now" in item_forecast["when_to_buy_message"].lower()

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
