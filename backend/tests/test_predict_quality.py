from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from app.ml.predict import (
    ForecastDataQuality,
    _apply_residual_bias_correction,
    _calibrate_occurrence_probability,
    _cap_forecast_spikes,
    _prefer_raw_for_mature_series,
    estimate_censored_sales_dates,
    filter_stock_movements_on_or_before,
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
    assert result.diagnostics.selected_model_name in {"Intermittent", "TSB", "ADIDA", "IMAPA", "NaiveMA"}
    assert len(result.forecast_frame) == 7


def test_non_sparse_sales_avoids_sparse_specialist_models() -> None:
    units = [3, 4, 2, 5, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5]
    history = _build_daily_history(datetime(2026, 1, 1), units)
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.quality.status == "ok"
    assert result.diagnostics.selected_model_name not in {"Intermittent", "TSB", "ADIDA", "IMAPA"}
    assert len(result.forecast_frame) == 7


def test_mature_dense_series_uses_adaptive_postprocessing_note() -> None:
    units = [3, 4, 2, 5, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5, 4, 3, 5, 4, 3, 4, 2, 5]
    history = _build_daily_history(datetime(2026, 1, 1), units)
    result = forecast_product_daily_units_with_diagnostics(history, horizon_days=7)

    assert result.diagnostics.quality.data_tier == "mature"
    assert any(
        (
            "Selected raw post-processing for mature demand" in note
            or "Applied two-stage demand decomposition" in note
            or "Skipped two-stage decomposition for mature NaiveMA baseline behavior." in note
        )
        for note in result.diagnostics.quality.notes
    )


def test_prefer_raw_for_mature_series_when_two_stage_is_worse(monkeypatch) -> None:
    values = [10.0] * 40
    index = pd.date_range(datetime(2026, 1, 1), periods=len(values), freq="D")
    series = pd.Series(values, index=index, dtype=float)
    quality = ForecastDataQuality(
        status="ok",
        history_days=len(values),
        non_zero_days=len(values),
        non_zero_ratio=1.0,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=len(values),
        notes=[],
    )

    class _FlatModel:
        def fit(self, fit_series: pd.Series) -> None:  # noqa: ARG002
            return None

        def predict(self, horizon_days: int) -> np.ndarray:
            return np.full(horizon_days, 7.0, dtype=float)

    monkeypatch.setattr("app.ml.predict._build_model_for_name", lambda model_name, history_days: _FlatModel())

    def _degraded_two_stage(
        prediction: np.ndarray,
        history_series: pd.Series,  # noqa: ARG001
        quality_arg: ForecastDataQuality,  # noqa: ARG001
        forecast_dates: pd.DatetimeIndex,  # noqa: ARG001
    ) -> tuple[np.ndarray, float, float, float, float, float]:
        degraded = np.maximum(np.asarray(prediction, dtype=float) - 5.0, 0.0)
        return degraded, 0.5, 1.0, 0.5, 0.5, 10.0

    monkeypatch.setattr("app.ml.predict._compose_two_stage_forecast", _degraded_two_stage)

    prefer_raw, raw_wmape, two_stage_wmape = _prefer_raw_for_mature_series(series, quality, "NaiveMA")

    assert prefer_raw is True
    assert raw_wmape is not None and two_stage_wmape is not None
    assert raw_wmape < two_stage_wmape


def test_prefer_raw_for_mature_series_keeps_two_stage_when_clearly_better(monkeypatch) -> None:
    values = [10.0] * 40
    index = pd.date_range(datetime(2026, 1, 1), periods=len(values), freq="D")
    series = pd.Series(values, index=index, dtype=float)
    quality = ForecastDataQuality(
        status="ok",
        history_days=len(values),
        non_zero_days=len(values),
        non_zero_ratio=1.0,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=len(values),
        notes=[],
    )

    class _FlatModel:
        def fit(self, fit_series: pd.Series) -> None:  # noqa: ARG002
            return None

        def predict(self, horizon_days: int) -> np.ndarray:
            return np.full(horizon_days, 7.0, dtype=float)

    monkeypatch.setattr("app.ml.predict._build_model_for_name", lambda model_name, history_days: _FlatModel())

    def _better_two_stage(
        prediction: np.ndarray,
        history_series: pd.Series,  # noqa: ARG001
        quality_arg: ForecastDataQuality,  # noqa: ARG001
        forecast_dates: pd.DatetimeIndex,  # noqa: ARG001
    ) -> tuple[np.ndarray, float, float, float, float, float]:
        improved = np.maximum(np.asarray(prediction, dtype=float) + 3.0, 0.0)
        return improved, 0.5, 1.0, 1.0, 0.5, 10.0

    monkeypatch.setattr("app.ml.predict._compose_two_stage_forecast", _better_two_stage)

    prefer_raw, raw_wmape, two_stage_wmape = _prefer_raw_for_mature_series(series, quality, "NaiveMA")

    assert prefer_raw is False
    assert raw_wmape is not None and two_stage_wmape is not None
    assert two_stage_wmape < raw_wmape


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


def test_stock_movement_cutoff_handles_timezone_aware_dates() -> None:
    stock_movements = pd.DataFrame(
        [
            {
                "occurred_at": pd.Timestamp("2026-01-03 08:30:00", tz="GMT"),
                "qty_delta": 10,
                "movement_type": "adjustment",
            },
            {
                "occurred_at": pd.Timestamp("2026-01-09 08:30:00", tz="GMT"),
                "qty_delta": 5,
                "movement_type": "adjustment",
            },
        ]
    )
    cutoff_dates = pd.Series([datetime(2026, 1, 1), datetime(2026, 1, 7)])

    filtered = filter_stock_movements_on_or_before(stock_movements, cutoff_dates)

    assert len(filtered) == 1
    assert filtered.iloc[0]["qty_delta"] == 10


def test_stockout_censoring_handles_terminal_zero_runs_with_strong_recent_demand() -> None:
    history = _build_daily_history(
        datetime(2026, 1, 1),
        [4, 5, 3, 4, 5, 3, 4] * 4 + [0, 0, 0, 0, 0, 0],
    )

    censored_dates = estimate_censored_sales_dates(history)

    assert len(censored_dates) == 6
    assert pd.Timestamp(datetime(2026, 1, 29)).normalize() in censored_dates
    assert pd.Timestamp(datetime(2026, 2, 3)).normalize() in censored_dates


def test_stockout_censoring_does_not_flag_terminal_zero_runs_with_sparse_recent_demand() -> None:
    history = _build_daily_history(
        datetime(2026, 1, 1),
        [0, 1, 0, 0, 2, 0, 0] * 4 + [0, 0, 0, 0, 0, 0],
    )

    censored_dates = estimate_censored_sales_dates(history)

    assert not censored_dates


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
