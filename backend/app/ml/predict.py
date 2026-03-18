from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from app.ml.model_registry import (
    CandidateScore,
    IntermittentDemandModel,
    NaiveMovingAverageModel,
    select_best_model_with_backtest,
)


MIN_HISTORY_DAYS = 21
MIN_NON_ZERO_DAYS = 6
MIN_NON_ZERO_RATIO = 0.08
SUSPECTED_STOCKOUT_ZERO_RUN_DAYS = 5
RESTOCK_GUIDED_STOCKOUT_ZERO_RUN_DAYS = 3
STOCKOUT_RESTOCK_LOOKAHEAD_DAYS = 1
MATURE_HISTORY_DAYS = max(MIN_HISTORY_DAYS * 2, 42)
MATURE_NON_ZERO_DAYS = max(MIN_NON_ZERO_DAYS * 2, 12)
MATURE_NON_ZERO_RATIO = max(MIN_NON_ZERO_RATIO * 2.0, 0.18)
SPARSE_ALLOWED_MODELS = {"Intermittent", "NaiveMA"}
NON_SPARSE_ALLOWED_MODELS = {"NaiveMA", "ARIMA", "Prophet", "XGBoost"}
OCCURRENCE_SHORT_WINDOW_DAYS = 21
OCCURRENCE_LONG_WINDOW_DAYS = 84
OCCURRENCE_WEEKDAY_WINDOW_DAYS = 84
TWO_STAGE_MIN_INTENSITY = 0.35
TWO_STAGE_MAX_INTENSITY = 1.85
TWO_STAGE_MIN_SIZE = 0.1
BIAS_HOLDOUT_MIN_DAYS = 7
BIAS_HOLDOUT_MAX_DAYS = 14
BIAS_MIN_TRAIN_DAYS = 21
BIAS_SHRINK_FACTOR = 0.75


@dataclass
class ForecastDataQuality:
    status: str
    history_days: int
    non_zero_days: int
    non_zero_ratio: float
    capped_outlier_days: int
    suspected_stockout_days: int
    data_tier: str = "auto"
    effective_history_days: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ForecastDiagnostics:
    selected_model_name: str
    selected_score: CandidateScore
    candidate_scores: list[CandidateScore]
    quality: ForecastDataQuality


@dataclass
class ForecastComputationResult:
    forecast_frame: pd.DataFrame
    diagnostics: ForecastDiagnostics


def _empty_forecast_frame(horizon_days: int) -> pd.DataFrame:
    today = pd.Timestamp.utcnow().normalize()
    dates = pd.date_range(today + timedelta(days=1), periods=horizon_days, freq="D")
    return pd.DataFrame(
        {
            "forecast_date": dates.date,
            "predicted_units": [0.0] * horizon_days,
            "lower_ci": [0.0] * horizon_days,
            "upper_ci": [0.0] * horizon_days,
        }
    )


def _to_dense_daily_series(sales_history: pd.DataFrame) -> pd.Series:
    if sales_history.empty:
        return pd.Series(dtype=float)

    history = sales_history.copy()
    history["date"] = pd.to_datetime(history["date"]).dt.normalize()
    grouped = history.groupby("date", as_index=True)["units"].sum().sort_index().astype(float)
    if grouped.empty:
        return pd.Series(dtype=float)

    full_dates = pd.date_range(grouped.index.min(), grouped.index.max(), freq="D")
    dense = grouped.reindex(full_dates, fill_value=0.0).astype(float)
    dense.name = "units"
    return dense


def _cap_outliers(series: pd.Series) -> tuple[pd.Series, int]:
    clean = series.astype(float).clip(lower=0.0)
    if len(clean) < 7:
        return clean, 0

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = max(0.0, q3 - q1)
    upper_bound = q3 + 1.5 * iqr
    upper_bound = max(upper_bound, q3)
    capped = clean.clip(lower=0.0, upper=upper_bound)
    changed = int(np.sum(~np.isclose(clean.to_numpy(dtype=float), capped.to_numpy(dtype=float))))
    return capped, changed


def _normalize_stock_movements(stock_movements: pd.DataFrame | None) -> pd.DataFrame:
    if stock_movements is None or stock_movements.empty:
        return pd.DataFrame(columns=["date", "qty_delta", "movement_type"])

    frame = stock_movements.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    elif "occurred_at" in frame.columns:
        frame["date"] = pd.to_datetime(frame["occurred_at"]).dt.normalize()
    else:
        frame["date"] = pd.NaT

    if "qty_delta" in frame.columns:
        frame["qty_delta"] = pd.to_numeric(frame["qty_delta"], errors="coerce").fillna(0.0).astype(float)
    else:
        frame["qty_delta"] = 0.0

    if "movement_type" not in frame.columns:
        frame["movement_type"] = ""

    frame = frame.dropna(subset=["date"])
    frame["movement_type"] = frame["movement_type"].fillna("").astype(str).str.strip().str.lower()
    return frame[["date", "qty_delta", "movement_type"]]


def _restock_signal_by_day(stock_movements: pd.DataFrame | None) -> pd.Series:
    frame = _normalize_stock_movements(stock_movements)
    if frame.empty:
        return pd.Series(dtype=float)
    positive = frame.loc[frame["qty_delta"] > 0, ["date", "qty_delta"]]
    if positive.empty:
        return pd.Series(dtype=float)
    signal = positive.groupby("date", as_index=True)["qty_delta"].sum().sort_index()
    signal.name = "restock_qty"
    return signal.astype(float)


def _identify_suspected_stockout_runs(
    series: pd.Series,
    stock_movements: pd.DataFrame | None = None,
) -> list[tuple[int, int]]:
    values = series.astype(float)
    zero_mask = (values <= 0.0).to_numpy(dtype=bool)
    if zero_mask.size == 0:
        return []

    restock_by_day = _restock_signal_by_day(stock_movements)
    run_ranges: list[tuple[int, int]] = []
    run_start: int | None = None

    def _close_run(run_end: int) -> None:
        nonlocal run_start
        if run_start is None:
            return

        left = values.iloc[max(0, run_start - 14):run_start]
        right = values.iloc[run_end + 1:min(len(values), run_end + 15)]
        left_non_zero = left[left > 0.0]
        right_non_zero = right[right > 0.0]
        # Only flag zero-demand runs that are surrounded by non-zero demand windows.
        if left_non_zero.empty or right_non_zero.empty:
            run_start = None
            return

        run_len = run_end - run_start + 1
        min_run_days = SUSPECTED_STOCKOUT_ZERO_RUN_DAYS

        if not restock_by_day.empty:
            run_start_date = pd.Timestamp(values.index[run_start]).normalize()
            run_end_date = pd.Timestamp(values.index[run_end]).normalize()
            restock_window_start = run_start_date
            restock_window_end = run_end_date + pd.Timedelta(days=STOCKOUT_RESTOCK_LOOKAHEAD_DAYS)
            restock_slice = restock_by_day.loc[
                (restock_by_day.index >= restock_window_start) & (restock_by_day.index <= restock_window_end)
            ]
            if not restock_slice.empty:
                min_run_days = RESTOCK_GUIDED_STOCKOUT_ZERO_RUN_DAYS

        if run_len >= min_run_days:
            run_ranges.append((run_start, run_end))
        run_start = None

    for index, is_zero in enumerate(zero_mask):
        if is_zero and run_start is None:
            run_start = index
        elif not is_zero and run_start is not None:
            _close_run(index - 1)

    if run_start is not None:
        _close_run(len(zero_mask) - 1)

    return run_ranges


def _impute_suspected_stockout_runs(
    series: pd.Series,
    stock_movements: pd.DataFrame | None = None,
) -> tuple[pd.Series, int]:
    adjusted = series.copy().astype(float)
    suspected_days = 0
    for run_start, run_end in _identify_suspected_stockout_runs(adjusted, stock_movements=stock_movements):
        left = adjusted.iloc[max(0, run_start - 14):run_start]
        right = adjusted.iloc[run_end + 1:min(len(adjusted), run_end + 15)]
        left_non_zero = left[left > 0.0]
        right_non_zero = right[right > 0.0]
        context = pd.concat([left_non_zero.tail(7), right_non_zero.head(7)])
        replacement = float(context.median()) if not context.empty else 0.0
        replacement = max(replacement, 0.0)
        if replacement <= 0.0:
            continue
        adjusted.iloc[run_start:run_end + 1] = replacement
        suspected_days += (run_end - run_start + 1)

    return adjusted, suspected_days


def estimate_censored_sales_dates(
    sales_history: pd.DataFrame,
    *,
    stock_movements: pd.DataFrame | None = None,
) -> set[pd.Timestamp]:
    series = _to_dense_daily_series(sales_history)
    if series.empty:
        return set()
    censored_days: set[pd.Timestamp] = set()
    for run_start, run_end in _identify_suspected_stockout_runs(series, stock_movements=stock_movements):
        for index in range(run_start, run_end + 1):
            censored_days.add(pd.Timestamp(series.index[index]).normalize())
    return censored_days


def _assess_quality(
    series: pd.Series,
    *,
    capped_outlier_days: int,
    suspected_stockout_days: int,
) -> ForecastDataQuality:
    history_days = len(series)
    non_zero_days = int((series > 0).sum())
    non_zero_ratio = float(non_zero_days / history_days) if history_days > 0 else 0.0
    effective_history_days = max(0, history_days - suspected_stockout_days)

    notes: list[str] = []
    status = "ok"
    data_tier = "developing"

    if history_days < MIN_HISTORY_DAYS:
        status = "insufficient_history"
        data_tier = "cold_start"
        notes.append(f"History below {MIN_HISTORY_DAYS} days; using conservative forecast settings.")
    elif non_zero_days < MIN_NON_ZERO_DAYS or non_zero_ratio < MIN_NON_ZERO_RATIO:
        status = "sparse_sales"
        data_tier = "sparse"
        notes.append("Sparse demand signal; confidence reduced and robust model fallback may apply.")
    elif (
        effective_history_days >= MATURE_HISTORY_DAYS
        and non_zero_days >= MATURE_NON_ZERO_DAYS
        and non_zero_ratio >= MATURE_NON_ZERO_RATIO
    ):
        data_tier = "mature"

    if capped_outlier_days > 0:
        notes.append(f"Capped {capped_outlier_days} outlier day(s) to reduce noise.")
    if suspected_stockout_days > 0:
        notes.append(
            f"Handled {suspected_stockout_days} suspected stockout-censored day(s) from zero-demand runs."
        )
    notes.append(
        f"Data tier={data_tier}; effective_history_days={effective_history_days}; non_zero_ratio={non_zero_ratio:.2f}."
    )

    return ForecastDataQuality(
        status=status,
        history_days=history_days,
        non_zero_days=non_zero_days,
        non_zero_ratio=non_zero_ratio,
        capped_outlier_days=capped_outlier_days,
        suspected_stockout_days=suspected_stockout_days,
        data_tier=data_tier,
        effective_history_days=effective_history_days,
        notes=notes,
    )


def _cap_forecast_spikes(
    prediction: np.ndarray,
    history_series: pd.Series,
    quality: ForecastDataQuality,
) -> tuple[np.ndarray, int]:
    forecast = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    if forecast.size == 0:
        return forecast, 0

    history = history_series.astype(float).clip(lower=0.0)
    positive_history = history[history > 0.0]
    if positive_history.empty:
        return forecast, 0

    recent_positive = positive_history.tail(min(60, len(positive_history)))
    q75 = float(recent_positive.quantile(0.75))
    q90 = float(recent_positive.quantile(0.90))
    recent_mean = float(recent_positive.mean())
    historical_max = float(positive_history.max())

    if quality.status == "sparse_sales":
        spike_cap = max(1.0, q90 * 1.25, q75 * 1.60, recent_mean * 2.00, historical_max)
    else:
        spike_cap = max(1.0, q90 * 1.60, q75 * 2.10, recent_mean * 3.00, historical_max * 1.10)

    capped = np.minimum(forecast, spike_cap)
    capped_days = int(np.sum(capped < forecast))
    return capped, capped_days


def _build_model_for_name(model_name: str, history_days: int):
    if model_name == "NaiveMA":
        return NaiveMovingAverageModel(window=max(1, min(7, history_days)))
    if model_name == "Intermittent":
        return IntermittentDemandModel()
    if model_name == "ARIMA":
        from app.ml.model_registry import ARIMAForecastModel

        return ARIMAForecastModel()
    if model_name == "Prophet":
        from app.ml.model_registry import ProphetForecastModel

        return ProphetForecastModel()
    if model_name == "XGBoost":
        from app.ml.model_registry import XGBoostForecastModel

        return XGBoostForecastModel()
    return NaiveMovingAverageModel(window=max(1, min(7, history_days)))


def _calibrate_occurrence_probability(
    prediction: np.ndarray,
    history_series: pd.Series,
    quality: ForecastDataQuality,
) -> tuple[np.ndarray, float, float, float]:
    forecast = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    if forecast.size == 0:
        return forecast, 0.0, 0.0, 1.0

    history = history_series.astype(float).clip(lower=0.0)
    if history.empty:
        return forecast, 0.0, 0.0, 1.0

    binary = (history > 0.0).astype(float)
    occ_short = float(binary.tail(min(OCCURRENCE_SHORT_WINDOW_DAYS, len(binary))).mean())
    occ_long = float(binary.tail(min(OCCURRENCE_LONG_WINDOW_DAYS, len(binary))).mean())
    target_occ = (0.65 * occ_short) + (0.35 * occ_long)
    target_occ = (0.70 * target_occ) + (0.30 * quality.non_zero_ratio)

    if quality.status == "sparse_sales":
        target_occ = float(np.clip(target_occ, 0.05, 0.65))
        min_scale, max_scale = 0.25, 1.0
    else:
        target_occ = float(np.clip(target_occ, 0.20, 1.0))
        min_scale, max_scale = 0.45, 1.15

    positive_history = history[history > 0.0]
    if positive_history.empty:
        return np.zeros_like(forecast), target_occ, 0.0, 0.0

    activity_threshold = max(0.1, float(positive_history.quantile(0.25)) * 0.5)
    predicted_occ = float(np.mean(forecast >= activity_threshold))
    raw_scale = target_occ if predicted_occ <= 0.0 else (target_occ / predicted_occ)
    scale = float(np.clip(raw_scale, min_scale, max_scale))
    calibrated = forecast * scale
    return calibrated, target_occ, predicted_occ, scale


def _weekday_occurrence_probabilities(
    history_series: pd.Series,
    quality: ForecastDataQuality,
    forecast_dates: pd.DatetimeIndex,
    target_occurrence: float,
) -> np.ndarray:
    if len(forecast_dates) == 0:
        return np.array([], dtype=float)

    history = history_series.astype(float).clip(lower=0.0)
    binary = (history > 0.0).astype(float)
    if binary.empty:
        return np.full(len(forecast_dates), target_occurrence, dtype=float)

    long_window = binary.tail(min(OCCURRENCE_WEEKDAY_WINDOW_DAYS, len(binary)))
    short_window = binary.tail(min(OCCURRENCE_SHORT_WINDOW_DAYS, len(binary)))

    by_dow_long = long_window.groupby(long_window.index.dayofweek).mean()
    by_dow_short = short_window.groupby(short_window.index.dayofweek).mean()

    probabilities: list[float] = []
    for forecast_date in forecast_dates:
        day_of_week = int(forecast_date.dayofweek)
        p_long = float(by_dow_long.get(day_of_week, target_occurrence))
        p_short = float(by_dow_short.get(day_of_week, p_long))
        p = (0.6 * p_short) + (0.4 * p_long)
        p = (0.75 * p) + (0.25 * target_occurrence)
        probabilities.append(p)

    probs = np.asarray(probabilities, dtype=float)
    if quality.status == "sparse_sales":
        lower, upper = 0.03, 0.65
    elif quality.status == "insufficient_history":
        lower, upper = 0.05, 0.75
    else:
        lower, upper = 0.08, 0.95
    return np.clip(probs, lower, upper)


def _compose_two_stage_forecast(
    prediction: np.ndarray,
    history_series: pd.Series,
    quality: ForecastDataQuality,
    forecast_dates: pd.DatetimeIndex,
) -> tuple[np.ndarray, float, float, float, float, float]:
    raw_forecast = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    if raw_forecast.size == 0:
        return raw_forecast, 0.0, 0.0, 1.0, 0.0, 0.0

    occurrence_calibrated, target_occ, predicted_occ, occ_scale = _calibrate_occurrence_probability(
        raw_forecast,
        history_series,
        quality,
    )
    history = history_series.astype(float).clip(lower=0.0)
    positive_history = history[history > 0.0]
    if positive_history.empty:
        return np.zeros_like(raw_forecast), target_occ, predicted_occ, occ_scale, 0.0, 0.0

    weekday_probs = _weekday_occurrence_probabilities(
        history,
        quality,
        forecast_dates,
        target_occurrence=target_occ,
    )
    weekday_prob_mean = float(np.mean(weekday_probs)) if weekday_probs.size else 0.0
    if weekday_prob_mean > 0.0:
        weekday_probs = np.clip(
            weekday_probs * (target_occ / weekday_prob_mean),
            0.01,
            0.98,
        )

    size_window = positive_history.tail(min(42, len(positive_history)))
    size_baseline = (0.6 * float(size_window.median())) + (0.4 * float(size_window.mean()))
    size_baseline = max(size_baseline, TWO_STAGE_MIN_SIZE)

    calibrated_mean = float(np.mean(occurrence_calibrated)) if occurrence_calibrated.size else 0.0
    if calibrated_mean <= 0.0:
        calibrated_mean = size_baseline * max(float(np.mean(weekday_probs)), 0.2)

    intensity = occurrence_calibrated / max(calibrated_mean, 1e-6)
    intensity = np.clip(intensity, TWO_STAGE_MIN_INTENSITY, TWO_STAGE_MAX_INTENSITY)
    conditional_size = np.maximum(size_baseline * intensity, TWO_STAGE_MIN_SIZE)
    expected_units = weekday_probs * conditional_size

    return (
        np.maximum(expected_units, 0.0),
        target_occ,
        predicted_occ,
        occ_scale,
        float(np.mean(weekday_probs)) if weekday_probs.size else 0.0,
        size_baseline,
    )


def _estimate_holdout_residual_bias(series: pd.Series, selected_model_name: str) -> tuple[float, int]:
    history = series.astype(float).clip(lower=0.0)
    if len(history) < BIAS_MIN_TRAIN_DAYS + BIAS_HOLDOUT_MIN_DAYS:
        return 0.0, 0

    holdout_days = min(BIAS_HOLDOUT_MAX_DAYS, max(BIAS_HOLDOUT_MIN_DAYS, len(history) // 5))
    split_at = len(history) - holdout_days
    if split_at < BIAS_MIN_TRAIN_DAYS:
        return 0.0, 0

    train = history.iloc[:split_at]
    valid = history.iloc[split_at:]
    if train.empty or valid.empty:
        return 0.0, 0

    try:
        model = _build_model_for_name(selected_model_name, len(train))
        model.fit(train)
        pred = np.asarray(model.predict(len(valid)), dtype=float)
    except Exception:
        fallback = NaiveMovingAverageModel(window=max(1, min(7, len(train))))
        fallback.fit(train)
        pred = np.asarray(fallback.predict(len(valid)), dtype=float)

    horizon = min(len(pred), len(valid))
    if horizon == 0:
        return 0.0, 0

    actual = valid.iloc[:horizon].to_numpy(dtype=float)
    residuals = actual - pred[:horizon]
    if residuals.size >= 5:
        low, high = np.quantile(residuals, [0.10, 0.90])
        residuals = np.clip(residuals, low, high)

    return float(np.mean(residuals)), int(horizon)


def _apply_residual_bias_correction(
    prediction: np.ndarray,
    history_series: pd.Series,
    selected_model_name: str,
) -> tuple[np.ndarray, float, int]:
    forecast = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    if forecast.size == 0:
        return forecast, 0.0, 0

    residual_bias, bias_points = _estimate_holdout_residual_bias(history_series, selected_model_name)
    if bias_points == 0:
        return forecast, 0.0, 0

    recent = history_series.astype(float).clip(lower=0.0).tail(min(60, len(history_series)))
    variability = max(float(recent.std(ddof=0)) if len(recent) > 1 else 0.0, 0.5)
    max_shift = max(0.75, variability * 2.5)

    adjusted_bias = float(np.clip(residual_bias * BIAS_SHRINK_FACTOR, -max_shift, max_shift))
    corrected = np.maximum(forecast + adjusted_bias, 0.0)
    return corrected, adjusted_bias, bias_points


def forecast_product_daily_units_with_diagnostics(
    sales_history: pd.DataFrame,
    horizon_days: int = 30,
    *,
    lead_time_days: int | None = None,
    stock_movements: pd.DataFrame | None = None,
) -> ForecastComputationResult:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")

    if sales_history.empty:
        fallback_score = CandidateScore("NaiveMA", mae=0.0, mape_pct=None, wmape_pct=None, windows_evaluated=0)
        quality = ForecastDataQuality(
            status="insufficient_history",
            history_days=0,
            non_zero_days=0,
            non_zero_ratio=0.0,
            capped_outlier_days=0,
            suspected_stockout_days=0,
            data_tier="cold_start",
            effective_history_days=0,
            notes=["No historical sales data available."],
        )
        return ForecastComputationResult(
            forecast_frame=_empty_forecast_frame(horizon_days),
            diagnostics=ForecastDiagnostics(
                selected_model_name="NaiveMA",
                selected_score=fallback_score,
                candidate_scores=[fallback_score],
                quality=quality,
            ),
        )

    series = _to_dense_daily_series(sales_history)
    if series.empty:
        fallback_score = CandidateScore("NaiveMA", mae=0.0, mape_pct=None, wmape_pct=None, windows_evaluated=0)
        quality = ForecastDataQuality(
            status="insufficient_history",
            history_days=0,
            non_zero_days=0,
            non_zero_ratio=0.0,
            capped_outlier_days=0,
            suspected_stockout_days=0,
            data_tier="cold_start",
            effective_history_days=0,
            notes=["No usable dense time series after normalization."],
        )
        return ForecastComputationResult(
            forecast_frame=_empty_forecast_frame(horizon_days),
            diagnostics=ForecastDiagnostics(
                selected_model_name="NaiveMA",
                selected_score=fallback_score,
                candidate_scores=[fallback_score],
                quality=quality,
            ),
        )

    capped_series, capped_count = _cap_outliers(series)
    adjusted_series, suspected_stockout_days = _impute_suspected_stockout_runs(
        capped_series,
        stock_movements=stock_movements,
    )
    quality = _assess_quality(
        adjusted_series,
        capped_outlier_days=capped_count,
        suspected_stockout_days=suspected_stockout_days,
    )

    if quality.status == "insufficient_history":
        model = NaiveMovingAverageModel(window=max(1, min(7, len(adjusted_series))))
        model.fit(adjusted_series)
        selected_score = CandidateScore("NaiveMA", mae=0.0, mape_pct=None, wmape_pct=None, windows_evaluated=0)
        candidate_scores = [selected_score]
        selected_model_name = "NaiveMA"
    else:
        if quality.data_tier == "sparse":
            min_train_days = 12
            holdout_days = min(7, max(3, len(adjusted_series) // 6))
            max_windows = 4
            allowed_models = SPARSE_ALLOWED_MODELS
        elif quality.data_tier == "mature":
            min_train_days = 21
            holdout_days = min(10, max(4, len(adjusted_series) // 7))
            max_windows = 5
            allowed_models = NON_SPARSE_ALLOWED_MODELS
        else:
            min_train_days = 18
            holdout_days = min(7, max(3, len(adjusted_series) // 6))
            max_windows = 4
            allowed_models = NON_SPARSE_ALLOWED_MODELS

        selection = select_best_model_with_backtest(
            adjusted_series,
            holdout_days=holdout_days,
            max_windows=max_windows,
            min_train_days=min_train_days,
            lead_time_days=lead_time_days,
            allowed_model_names=allowed_models,
        )
        model = selection.model
        selected_score = selection.selected_score
        candidate_scores = selection.candidate_scores
        selected_model_name = selection.selected_model_name

    start_date = adjusted_series.index.max() + timedelta(days=1)
    forecast_dates = pd.date_range(start_date, periods=horizon_days, freq="D")

    raw_prediction = np.asarray(model.predict(horizon_days), dtype=float)
    two_stage_prediction, target_occ, predicted_occ, occ_scale, weekday_occ, size_baseline = _compose_two_stage_forecast(
        raw_prediction,
        adjusted_series,
        quality,
        forecast_dates,
    )
    if abs(occ_scale - 1.0) >= 0.05:
        quality.notes.append(
            (
                "Applied occurrence calibration "
                f"(target={target_occ:.2f}, predicted={predicted_occ:.2f}, scale={occ_scale:.2f})."
            )
        )
    quality.notes.append(
        (
            "Applied two-stage demand decomposition "
            f"(weekday_occ={weekday_occ:.2f}, conditional_size={size_baseline:.2f})."
        )
    )

    bias_adjusted, bias_shift, bias_points = _apply_residual_bias_correction(
        two_stage_prediction,
        adjusted_series,
        selected_model_name,
    )
    if bias_points > 0 and abs(bias_shift) >= 0.05:
        quality.notes.append(
            f"Applied residual bias correction over {bias_points} holdout day(s) with shift={bias_shift:.2f}."
        )

    prediction, capped_days = _cap_forecast_spikes(bias_adjusted, adjusted_series, quality)
    if capped_days > 0:
        quality.notes.append(f"Capped {capped_days} forecast day(s) to limit spike overestimation.")

    error_ratio = (selected_score.wmape_pct if selected_score.wmape_pct is not None else 35.0) / 100.0
    error_ratio = max(0.15, min(0.9, error_ratio))
    lower_ci = np.maximum(prediction * (1.0 - error_ratio), 0.0)
    upper_ci = np.maximum(prediction * (1.0 + error_ratio), 0.0)
    frame = pd.DataFrame(
        {
            "forecast_date": forecast_dates.date,
            "predicted_units": prediction,
            "lower_ci": lower_ci,
            "upper_ci": upper_ci,
        }
    )

    return ForecastComputationResult(
        forecast_frame=frame,
        diagnostics=ForecastDiagnostics(
            selected_model_name=selected_model_name,
            selected_score=selected_score,
            candidate_scores=candidate_scores,
            quality=quality,
        ),
    )


def forecast_product_daily_units(
    sales_history: pd.DataFrame,
    horizon_days: int = 30,
    *,
    lead_time_days: int | None = None,
    stock_movements: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str]:
    result = forecast_product_daily_units_with_diagnostics(
        sales_history,
        horizon_days=horizon_days,
        lead_time_days=lead_time_days,
        stock_movements=stock_movements,
    )
    return result.forecast_frame, result.diagnostics.selected_model_name
