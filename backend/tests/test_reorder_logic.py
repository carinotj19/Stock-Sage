from datetime import date, timedelta

import pandas as pd

from app.services.reorder_service import ReorderService


def test_reorder_formula_and_stockout_date() -> None:
    service = ReorderService()
    start = date(2026, 1, 1)
    forecast = pd.DataFrame(
        {
            "forecast_date": [start + timedelta(days=i) for i in range(5)],
            "predicted_units": [5, 6, 7, 8, 9],
        }
    )

    result = service.compute_reorder(
        current_stock=12,
        forecast_frame=forecast,
        lead_time_days=3,
        reorder_min_qty=10,
        reorder_multiple=5,
        safety_stock=4,
    )

    assert result.reorder_point == 22
    assert result.suggested_qty == 30
    assert result.predicted_stockout_date == start + timedelta(days=2)


def test_safety_stock_is_non_negative() -> None:
    service = ReorderService()
    safety = service.compute_safety_stock([4, 5, 6, 3, 7, 2], lead_time_days=5)
    assert safety >= 0


def test_reorder_uses_recent_actual_demand_floor_when_forecast_is_too_low() -> None:
    service = ReorderService()
    start = date(2026, 1, 1)
    forecast = pd.DataFrame(
        {
            "forecast_date": [start + timedelta(days=i) for i in range(6)],
            "predicted_units": [1, 1, 1, 1, 1, 1],
        }
    )

    result = service.compute_reorder(
        current_stock=5,
        forecast_frame=forecast,
        lead_time_days=3,
        reorder_min_qty=1,
        reorder_multiple=1,
        safety_stock=0,
        recent_actual_daily_units=[6, 5, 7, 6, 5, 6, 6],
        model_wmape_pct=30.0,
        confidence_score=0.66,
    )

    # Lead-time demand is validated against recent actuals and buffered by model error.
    assert result.reorder_point >= 22
    assert result.suggested_qty >= 31
    assert 0.0 <= result.confidence_score <= 1.0
