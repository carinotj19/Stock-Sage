from datetime import date, datetime, timedelta, timezone
from collections.abc import Generator
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    CompetitorPriceSnapshot,
    CompetitorSource,
    ForecastRun,
    ReorderRecommendation,
    SalesItem,
    SalesTransaction,
    SkuForecast,
)
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
    assert report_payload["evaluation_non_mature"]["evaluation_days"] == 7
    assert report_payload["evaluation"] == report_payload["evaluation_full"]
    assert "history_days>=" in report_payload["mature_sku_criteria"]
    assert "mature_sku_count" in report_payload["summary"]
    assert "non_mature_sku_count" in report_payload["summary"]
    assert "high_confidence_count" in report_payload["summary"]
    assert "high_confidence_mature_count" in report_payload["summary"]
    assert "high_confidence_non_mature_count" in report_payload["summary"]
    assert "qa_summary" in report_payload
    assert "qa_report" in report_payload
    assert report_payload["qa_summary"] is None
    assert report_payload["qa_report"] is None
    assert report_payload["explainability_rows"][0]["sku"] == "SKU-LOW-1"
    assert report_payload["explainability_rows"][0]["data_tier"] in {"mature", "non_mature"}
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


def test_item_forecast_defaults_to_up_to_365_days_of_dense_history() -> None:
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

    supplier_resp = client.post("/suppliers", json={"name": "History Supplier", "lead_time_days_default": 3})
    supplier_id = supplier_resp.json()["id"]

    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-HISTORY-1",
            "name": "History Rich Item",
            "supplier_id": supplier_id,
            "cost_price": "2.00",
            "sell_price": "3.00",
            "reorder_min_qty": 4,
            "safety_stock": 2,
            "initial_stock": 120,
        },
    )
    product_id = product_resp.json()["id"]

    with TestingSessionLocal() as db:
        run = ForecastRun(model_version="NaiveMA", horizon_days=30)
        db.add(run)
        db.flush()
        db.add(
            ReorderRecommendation(
                run_id=run.id,
                product_id=product_id,
                predicted_stockout_date=date(2026, 1, 15),
                reorder_point=8,
                suggested_qty=10,
                confidence_score=0.75,
            )
        )

        for offset in range(400, 0, -5):
            sold_at = datetime.now(timezone.utc) - timedelta(days=offset)
            transaction = SalesTransaction(
                receipt_no=f"R-HISTORY-{offset}",
                sold_at=sold_at,
                total_amount=6.00,
                payment_method="cash",
            )
            db.add(transaction)
            db.flush()
            db.add(
                SalesItem(
                    sales_transaction_id=transaction.id,
                    product_id=product_id,
                    qty=2,
                    unit_sell_price=3.00,
                    line_total=6.00,
                )
            )

        db.commit()

    item_forecast_resp = client.get(f"/dashboard/item-forecast/{product_id}")
    assert item_forecast_resp.status_code == 200
    item_forecast = item_forecast_resp.json()
    history_points = [point for point in item_forecast["demand_points"] if point["kind"] == "history"]

    assert len(history_points) == 365

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_source_quality_uses_last_run_at_and_runtime_state_for_zero_row_standard_sources() -> None:
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

    supplier_resp = client.post("/suppliers", json={"name": "Fresh Supplier", "lead_time_days_default": 3})
    supplier_id = supplier_resp.json()["id"]
    client.post(
        "/products",
        json={
            "sku": "SKU-STANDARD-1",
            "name": "Standard Source Item",
            "supplier_id": supplier_id,
            "cost_price": "2.00",
            "sell_price": "3.00",
            "reorder_min_qty": 2,
            "safety_stock": 1,
            "initial_stock": 10,
        },
    )

    with TestingSessionLocal() as db:
        source = CompetitorSource(
            name="Standard Zero Source",
            base_url="https://standard.example",
            enabled=True,
            last_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scrape_config_json=json.dumps(
                {
                    "mode": "standard",
                    "runtime_state": {
                        "last_run_inserted": 0,
                        "last_run_attempted_products": 1,
                        "consecutive_zero_insert_runs": 2,
                        "degraded_reason": "repeated_zero_insert_runs",
                    },
                }
            ),
        )
        db.add(source)
        db.commit()

    response = client.get("/dashboard/scraper-source-quality?window_hours=24")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["source_name"] == "Standard Zero Source"
    assert row["stale"] is False
    assert row["degraded"] is True
    assert row["degradation_reason"] == "repeated_zero_insert_runs"

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_forecast_report_compare_defaults_to_latest_and_previous_run() -> None:
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

    supplier_resp = client.post("/suppliers", json={"name": "Compare Supplier", "lead_time_days_default": 3})
    supplier_id = supplier_resp.json()["id"]
    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-CMP-1",
            "name": "Compare Item",
            "supplier_id": supplier_id,
            "cost_price": "2.00",
            "sell_price": "3.00",
            "reorder_min_qty": 2,
            "safety_stock": 1,
            "initial_stock": 10,
        },
    )
    product_id = product_resp.json()["id"]

    forecast_dates = [date.today() - timedelta(days=3), date.today() - timedelta(days=2), date.today() - timedelta(days=1)]

    with TestingSessionLocal() as db:
        baseline_run = ForecastRun(model_version="Baseline", horizon_days=3)
        candidate_run = ForecastRun(model_version="Candidate", horizon_days=3)
        db.add_all([baseline_run, candidate_run])
        db.flush()

        db.add_all(
            [
                SkuForecast(
                    run_id=baseline_run.id,
                    product_id=product_id,
                    forecast_date=forecast_date,
                    predicted_units=2.0,
                    lower_ci=1.0,
                    upper_ci=3.0,
                )
                for forecast_date in forecast_dates
            ]
        )
        db.add_all(
            [
                SkuForecast(
                    run_id=candidate_run.id,
                    product_id=product_id,
                    forecast_date=forecast_date,
                    predicted_units=5.0,
                    lower_ci=4.0,
                    upper_ci=6.0,
                )
                for forecast_date in forecast_dates
            ]
        )
        db.add_all(
            [
                ReorderRecommendation(
                    run_id=baseline_run.id,
                    product_id=product_id,
                    predicted_stockout_date=forecast_dates[1],
                    reorder_point=6,
                    suggested_qty=6,
                    confidence_score=0.55,
                ),
                ReorderRecommendation(
                    run_id=candidate_run.id,
                    product_id=product_id,
                    predicted_stockout_date=forecast_dates[2],
                    reorder_point=4,
                    suggested_qty=4,
                    confidence_score=0.80,
                ),
            ]
        )

        for offset, sold_date in enumerate(forecast_dates):
            transaction = SalesTransaction(
                receipt_no=f"R-CMP-{offset}",
                sold_at=datetime.combine(sold_date, datetime.min.time(), tzinfo=timezone.utc),
                total_amount=15.00,
                payment_method="cash",
            )
            db.add(transaction)
            db.flush()
            db.add(
                SalesItem(
                    sales_transaction_id=transaction.id,
                    product_id=product_id,
                    qty=5,
                    unit_sell_price=3.00,
                    line_total=15.00,
                )
            )

        db.commit()

    response = client.get("/dashboard/forecast-report/compare")
    assert response.status_code == 200
    payload = response.json()

    assert payload["baseline_run"]["run_id"] == baseline_run.id
    assert payload["candidate_run"]["run_id"] == candidate_run.id
    assert payload["verdict"] == "improved"
    assert payload["metrics"]["comparable_skus"] == 1
    assert payload["metrics"]["comparable_points"] == 3
    assert payload["baseline"]["wmape_pct"] == 60.0
    assert payload["candidate"]["wmape_pct"] == 0.0
    assert payload["delta"]["wmape_pct"] == -60.0
    assert payload["delta"]["avg_confidence"] == 0.25
    assert payload["sku_rows"][0]["sku"] == "SKU-CMP-1"
    assert payload["sku_rows"][0]["suggested_qty_delta"] == -2
    assert payload["sku_rows"][0]["confidence_score_delta"] == 0.25

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_forecast_report_compare_uses_persisted_validation_when_actuals_unavailable() -> None:
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

    supplier_resp = client.post("/suppliers", json={"name": "Validation Supplier", "lead_time_days_default": 3})
    supplier_id = supplier_resp.json()["id"]
    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-VAL-1",
            "name": "Validation Item",
            "supplier_id": supplier_id,
            "cost_price": "2.00",
            "sell_price": "3.00",
            "reorder_min_qty": 2,
            "safety_stock": 1,
            "initial_stock": 10,
        },
    )
    product_id = product_resp.json()["id"]

    forecast_dates = [date.today() + timedelta(days=1), date.today() + timedelta(days=2), date.today() + timedelta(days=3)]
    reports_dir = Path(__file__).resolve().parents[1] / "data"
    reports_dir.mkdir(parents=True, exist_ok=True)

    with TestingSessionLocal() as db:
        baseline_run = ForecastRun(model_version="Baseline", horizon_days=3)
        candidate_run = ForecastRun(model_version="Candidate", horizon_days=3)
        db.add_all([baseline_run, candidate_run])
        db.flush()

        baseline_report_name = f"forecast_validation_run{baseline_run.id}.json"
        candidate_report_name = f"forecast_validation_run{candidate_run.id}.json"
        baseline_run.notes = f"validation_report={baseline_report_name}|fallback=none"
        candidate_run.notes = f"validation_report={candidate_report_name}|fallback=SKU-VAL-1:baseline_not_beaten"

        db.add_all(
            [
                SkuForecast(
                    run_id=baseline_run.id,
                    product_id=product_id,
                    forecast_date=forecast_date,
                    predicted_units=2.0,
                    lower_ci=1.0,
                    upper_ci=3.0,
                )
                for forecast_date in forecast_dates
            ]
        )
        db.add_all(
            [
                SkuForecast(
                    run_id=candidate_run.id,
                    product_id=product_id,
                    forecast_date=forecast_date,
                    predicted_units=1.0,
                    lower_ci=0.5,
                    upper_ci=2.0,
                )
                for forecast_date in forecast_dates
            ]
        )
        db.add_all(
            [
                ReorderRecommendation(
                    run_id=baseline_run.id,
                    product_id=product_id,
                    predicted_stockout_date=forecast_dates[1],
                    reorder_point=6,
                    suggested_qty=6,
                    confidence_score=0.55,
                ),
                ReorderRecommendation(
                    run_id=candidate_run.id,
                    product_id=product_id,
                    predicted_stockout_date=None,
                    reorder_point=4,
                    suggested_qty=0,
                    confidence_score=0.70,
                ),
            ]
        )
        db.commit()

    (reports_dir / baseline_report_name).write_text(
        json.dumps(
            {
                "run_id": baseline_run.id,
                "summary": {
                    "method": "lead_time_backtest",
                    "evaluated_skus": 1,
                    "skipped_skus": 0,
                    "model_wmape_pct": 42.0,
                    "baseline_wmape_pct": 50.0,
                    "wmape_improvement_pct": 16.0,
                    "total_windows_evaluated": 4,
                    "model_win_count": 2,
                    "model_win_rate_pct": 50.0,
                },
                "rows": [
                    {
                        "product_id": product_id,
                        "sku": "SKU-VAL-1",
                        "model_name": "ARIMA",
                        "candidate_model_name": "ARIMA",
                        "selected_strategy_action": "none",
                        "data_tier": "mature",
                        "quality_status": "ok",
                        "model_wmape_pct": 42.0,
                        "candidate_model_wmape_pct": 42.0,
                        "baseline_wmape_pct": 50.0,
                        "wmape_improvement_pct": 16.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / candidate_report_name).write_text(
        json.dumps(
            {
                "run_id": candidate_run.id,
                "summary": {
                    "method": "lead_time_backtest",
                    "evaluated_skus": 1,
                    "skipped_skus": 0,
                    "model_wmape_pct": 24.0,
                    "baseline_wmape_pct": 50.0,
                    "wmape_improvement_pct": 52.0,
                    "total_windows_evaluated": 4,
                    "model_win_count": 4,
                    "model_win_rate_pct": 100.0,
                },
                "rows": [
                    {
                        "product_id": product_id,
                        "sku": "SKU-VAL-1",
                        "model_name": "BaselineFallback",
                        "candidate_model_name": "ARIMA",
                        "selected_strategy_action": "baseline_fallback",
                        "data_tier": "mature",
                        "quality_status": "ok",
                        "model_wmape_pct": 24.0,
                        "candidate_model_wmape_pct": 72.0,
                        "baseline_wmape_pct": 50.0,
                        "wmape_improvement_pct": 52.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/dashboard/forecast-report/compare")
    assert response.status_code == 200
    payload = response.json()

    assert payload["verdict"] == "insufficient_actuals"
    assert payload["validation"]["verdict"] == "improved"
    assert payload["validation"]["baseline"]["model_wmape_pct"] == 42.0
    assert payload["validation"]["candidate"]["model_wmape_pct"] == 24.0
    assert payload["validation"]["delta"]["model_wmape_pct"] == -18.0
    assert payload["validation"]["delta"]["wmape_improvement_pct"] == 36.0
    assert payload["validation"]["baseline"]["raw_candidate_wmape_pct"] == 42.0
    assert payload["validation"]["candidate"]["raw_candidate_wmape_pct"] == 72.0
    assert payload["validation"]["delta"]["raw_candidate_wmape_pct"] == 30.0
    assert payload["validation"]["baseline"]["selected_strategy_fallback_count"] == 0
    assert payload["validation"]["candidate"]["selected_strategy_fallback_count"] == 1
    assert payload["validation"]["candidate"]["selected_strategy_fallback_rate_pct"] == 100.0
    assert payload["validation"]["candidate"]["mature_evaluated_skus"] == 1
    assert payload["validation"]["candidate"]["mature_raw_candidate_win_rate_pct"] == 0.0
    assert payload["validation_sku_rows"][0]["sku"] == "SKU-VAL-1"
    assert payload["validation_sku_rows"][0]["candidate_selected_strategy_action"] == "baseline_fallback"
    assert payload["validation_sku_rows"][0]["candidate_fallback_reason"] == "baseline_not_beaten"
    assert payload["validation_sku_rows"][0]["candidate_selected_wmape_pct"] == 24.0
    assert payload["validation_sku_rows"][0]["candidate_raw_candidate_wmape_pct"] == 72.0
    assert payload["validation_sku_rows"][0]["candidate_raw_candidate_gap_vs_baseline_pct"] == 22.0
    assert payload["validation_sku_rows"][0]["selected_wmape_delta"] == -18.0
    assert payload["validation_sku_rows"][0]["raw_candidate_wmape_delta"] == 30.0

    (reports_dir / baseline_report_name).unlink(missing_ok=True)
    (reports_dir / candidate_report_name).unlink(missing_ok=True)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
