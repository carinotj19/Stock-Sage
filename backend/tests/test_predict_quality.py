from datetime import datetime, timedelta

import pandas as pd

from app.ml.predict import (
    ForecastDataQuality,
    _apply_residual_bias_correction,
    _calibrate_occurrence_probability,
    _cap_forecast_spikes,
    estimate_censored_sales_dates,
    forecast_product_daily_units_with_diagnostics,
)


def _build_daily_history(start: datetime, units: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": start + timedelta(days=offset), "units": value}
            for offset, value in enumerate(units)
        ],
        columns=["date", "units"],
    )


def test_short_history_uses_conservative_gate() -> None:
    history = _build_daily_history(datetime(2026, 1, 1), [2, 1, 3, 2, 1])
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.selected_model_name == "NaiveMA"
    assert result.diagnostics.quality.status == "insufficient_history"
    assert result.diagnostics.quality.data_tier == "cold_start"
    assert len(result.forecast_frame) == 7


def test_stockout_zero_run_is_detected_and_handled() -> None:
    units = [5] * 10 + [0] * 6 + [4] * 14
    history = _build_daily_history(datetime(2026, 1, 1), units)
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.quality.suspected_stockout_days >= 6
    assert len(result.forecast_frame) == 7


def test_sparse_sales_restricts_model_selection_to_robust_fallbacks() -> None:
    units = [0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0]
    history = _build_daily_history(datetime(2026, 1, 1), units)
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.quality.status == "sparse_sales"
    assert result.diagnostics.quality.data_tier == "sparse"
    assert result.diagnostics.selected_model_name in {"Intermittent", "NaiveMA"}
    assert len(result.forecast_frame) == 7


def test_non_sparse_sales_excludes_intermittent_candidate() -> None:
    units = [3, 4, 2, 5, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5]
    history = _build_daily_history(datetime(2026, 1, 1), units)
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.quality.status == "ok"
    assert result.diagnostics.selected_model_name != "Intermittent"
    assert len(result.forecast_frame) == 7


def test_stockout_censoring_uses_restock_signal_for_short_zero_runs() -> None:
    history = _build_daily_history(
        datetime(2026, 1, 1),
        [4, 3, 5, 4, 3, 0, 0, 0, 4, 3, 5],
    )
    stock_movements = pd.DataFrame(
        [
            {"occurred_at": datetime(2026, 1, 8), "qty_delta": 20, "movement_type": "adjustment"},
        ]
    )

    censored_dates = estimate_censored_sales_dates(history, stock_movements=stock_movements)

    assert len(censored_dates) == 3
    assert pd.Timestamp(datetime(2026, 1, 6)).normalize() in censored_dates
    assert pd.Timestamp(datetime(2026, 1, 8)).normalize() in censored_dates


def test_spike_cap_clamps_unrealistic_prediction_outliers() -> None:
    history = pd.Series([1.0, 2.0, 1.0, 3.0, 2.0, 1.0, 2.0, 2.0, 1.0, 3.0], dtype=float)
    quality = ForecastDataQuality(
        status="ok",
        history_days=10,
        non_zero_days=10,
        non_zero_ratio=1.0,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        notes=[],
    )
    prediction = pd.Series([2.0, 2.5, 100.0], dtype=float).to_numpy()

    capped, capped_days = _cap_forecast_spikes(prediction, history, quality)
    assert capped_days == 1
    assert max(capped) < 100.0


def test_occurrence_calibration_downscales_sparse_forecast_levels() -> None:
    history = pd.Series([0.0] * 40 + [1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 1.0], dtype=float)
    quality = ForecastDataQuality(
        status="sparse_sales",
        history_days=len(history),
        non_zero_days=3,
        non_zero_ratio=3 / len(history),
        capped_outlier_days=0,
        suspected_stockout_days=0,
        notes=[],
    )
    raw_prediction = pd.Series([2.0] * 7, dtype=float).to_numpy()

    calibrated, target_occ, predicted_occ, scale = _calibrate_occurrence_probability(
        raw_prediction,
        history,
        quality,
    )

    assert scale < 1.0
    assert target_occ < predicted_occ
    assert float(calibrated.mean()) < float(raw_prediction.mean())


def test_residual_bias_correction_reduces_positive_forecast_bias() -> None:
    history = pd.Series([5.0] * 20 + [1.0] * 12, dtype=float)
    raw_prediction = pd.Series([3.0] * 10, dtype=float).to_numpy()

    corrected, bias_shift, points = _apply_residual_bias_correction(raw_prediction, history, "NaiveMA")

    assert points > 0
    assert bias_shift < 0
    assert float(corrected.mean()) < float(raw_prediction.mean())
