from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
import pandas as pd


class ForecastModel(Protocol):
    name: str

    def fit(self, series: pd.Series) -> None:
        ...

    def predict(self, horizon_days: int) -> np.ndarray:
        ...


@dataclass
class CandidateScore:
    model_name: str
    mae: float
    mape_pct: float | None
    wmape_pct: float | None
    windows_evaluated: int
    mae_std: float | None = None
    mape_std_pct: float | None = None
    wmape_std_pct: float | None = None
    lead_time_wmape_pct: float | None = None
    lead_time_wmape_std_pct: float | None = None


LEADTIME_RANK_WEIGHT = 0.35
GLOBAL_RANK_WEIGHT = 0.65
LEADTIME_SWITCH_MAX_GLOBAL_WMAPE_PCT_DELTA = 3.0


@dataclass
class ModelSelectionResult:
    model: ForecastModel
    selected_model_name: str
    selected_score: CandidateScore
    candidate_scores: list[CandidateScore]


@dataclass
class NaiveMovingAverageModel:
    window: int = 7
    name: str = "NaiveMA"
    _history: pd.Series | None = None

    def fit(self, series: pd.Series) -> None:
        self._history = series.astype(float)

    def predict(self, horizon_days: int) -> np.ndarray:
        if self._history is None or self._history.empty:
            return np.zeros(horizon_days)

        window = max(1, min(self.window, len(self._history)))
        base = float(self._history.tail(window).mean())
        return np.full(horizon_days, max(base, 0.0), dtype=float)


@dataclass
class IntermittentDemandModel:
    alpha: float = 0.2
    name: str = "Intermittent"
    _rate: float = 0.0

    def fit(self, series: pd.Series) -> None:
        history = series.astype(float).clip(lower=0.0)
        if history.empty:
            self._rate = 0.0
            return

        non_zero_positions = np.flatnonzero(history.to_numpy() > 0.0)
        if non_zero_positions.size == 0:
            self._rate = 0.0
            return

        alpha = float(max(0.05, min(0.4, self.alpha)))
        demand_hat = float(history.iloc[non_zero_positions[0]])
        interval_hat = float(non_zero_positions[0] + 1)
        previous_position = int(non_zero_positions[0])

        for position in non_zero_positions[1:]:
            demand = float(history.iloc[position])
            interval = float(position - previous_position)
            demand_hat = alpha * demand + (1.0 - alpha) * demand_hat
            interval_hat = alpha * interval + (1.0 - alpha) * interval_hat
            previous_position = int(position)

        interval_hat = max(interval_hat, 1.0)
        # Croston-SBA correction dampens positive bias for intermittent demand.
        base_rate = (demand_hat / interval_hat) * (1.0 - alpha / 2.0)
        self._rate = max(base_rate, 0.0)

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.full(horizon_days, self._rate, dtype=float)


@dataclass
class TSBForecastModel:
    alpha_demand: float = 0.2
    beta_occurrence: float = 0.1
    name: str = "TSB"
    _rate: float = 0.0

    def fit(self, series: pd.Series) -> None:
        history = series.astype(float).clip(lower=0.0).to_numpy(dtype=float)
        if history.size == 0:
            self._rate = 0.0
            return

        hits = history > 0.0
        if not bool(np.any(hits)):
            self._rate = 0.0
            return

        alpha = float(max(0.05, min(0.4, self.alpha_demand)))
        beta = float(max(0.05, min(0.4, self.beta_occurrence)))

        demand_hat = float(np.mean(history[hits]))
        occurrence_hat = float(np.mean(hits.astype(float)))

        for value in history:
            hit = 1.0 if value > 0.0 else 0.0
            occurrence_hat = occurrence_hat + (beta * (hit - occurrence_hat))
            if hit > 0.0:
                demand_hat = demand_hat + (alpha * (float(value) - demand_hat))

        self._rate = max(occurrence_hat * demand_hat, 0.0)

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.full(horizon_days, self._rate, dtype=float)


@dataclass
class ADIDAForecastModel:
    max_bucket_days: int = 14
    name: str = "ADIDA"
    _daily_rate: float = 0.0

    @staticmethod
    def _aggregate(series_values: np.ndarray, bucket_days: int) -> np.ndarray:
        if series_values.size == 0:
            return np.array([], dtype=float)
        bucket = max(1, int(bucket_days))
        groups = []
        for start in range(0, series_values.size, bucket):
            groups.append(float(np.sum(series_values[start:start + bucket])))
        return np.asarray(groups, dtype=float)

    def fit(self, series: pd.Series) -> None:
        history = series.astype(float).clip(lower=0.0).to_numpy(dtype=float)
        if history.size == 0:
            self._daily_rate = 0.0
            return

        non_zero_days = int(np.count_nonzero(history > 0.0))
        if non_zero_days == 0:
            self._daily_rate = 0.0
            return

        adi = float(history.size / max(non_zero_days, 1))
        bucket_days = max(1, min(int(round(adi)), int(self.max_bucket_days)))
        aggregated = self._aggregate(history, bucket_days)
        if aggregated.size == 0:
            self._daily_rate = 0.0
            return

        window = max(1, min(3, aggregated.size))
        aggregated_forecast = float(np.mean(aggregated[-window:]))
        self._daily_rate = max(aggregated_forecast / max(bucket_days, 1), 0.0)

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.full(horizon_days, self._daily_rate, dtype=float)


@dataclass
class IMAPAForecastModel:
    max_bucket_days: int = 14
    name: str = "IMAPA"
    _daily_rate: float = 0.0

    @staticmethod
    def _aggregate(series_values: np.ndarray, bucket_days: int) -> np.ndarray:
        if series_values.size == 0:
            return np.array([], dtype=float)
        bucket = max(1, int(bucket_days))
        groups = []
        for start in range(0, series_values.size, bucket):
            groups.append(float(np.sum(series_values[start:start + bucket])))
        return np.asarray(groups, dtype=float)

    def fit(self, series: pd.Series) -> None:
        history = series.astype(float).clip(lower=0.0).to_numpy(dtype=float)
        if history.size == 0:
            self._daily_rate = 0.0
            return

        non_zero_days = int(np.count_nonzero(history > 0.0))
        if non_zero_days == 0:
            self._daily_rate = 0.0
            return

        adi = float(history.size / max(non_zero_days, 1))
        upper_bucket = max(1, min(int(round(adi)), int(self.max_bucket_days)))
        levels = list(range(1, upper_bucket + 1))

        daily_rates: list[float] = []
        for bucket_days in levels:
            aggregated = self._aggregate(history, bucket_days)
            if aggregated.size == 0:
                continue
            window = max(1, min(3, aggregated.size))
            aggregated_forecast = float(np.mean(aggregated[-window:]))
            daily_rate = max(aggregated_forecast / max(bucket_days, 1), 0.0)
            daily_rates.append(daily_rate)

        if not daily_rates:
            self._daily_rate = 0.0
            return
        self._daily_rate = float(max(np.median(np.asarray(daily_rates, dtype=float)), 0.0))

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.full(horizon_days, self._daily_rate, dtype=float)


class ARIMAForecastModel:
    name = "ARIMA"

    def __init__(self) -> None:
        from statsmodels.tsa.arima.model import ARIMA  # type: ignore

        self._arima_cls = ARIMA
        self._fitted = None

    def fit(self, series: pd.Series) -> None:
        if len(series) < 10:
            raise ValueError("ARIMA requires at least 10 observations")
        model = self._arima_cls(series.astype(float), order=(1, 1, 1))
        self._fitted = model.fit()

    def predict(self, horizon_days: int) -> np.ndarray:
        if self._fitted is None:
            raise ValueError("Model must be fit before prediction")
        forecast = self._fitted.forecast(steps=horizon_days)
        return np.maximum(np.asarray(forecast, dtype=float), 0.0)


class ProphetForecastModel:
    name = "Prophet"

    def __init__(self) -> None:
        from prophet import Prophet  # type: ignore

        self._prophet_cls = Prophet
        self._model = None
        self._last_index: pd.Timestamp | None = None

    def fit(self, series: pd.Series) -> None:
        if len(series) < 10:
            raise ValueError("Prophet requires at least 10 observations")

        frame = pd.DataFrame({"ds": series.index, "y": series.values.astype(float)})
        model = self._prophet_cls(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False)
        model.fit(frame)

        self._model = model
        self._last_index = pd.Timestamp(series.index.max())

    def predict(self, horizon_days: int) -> np.ndarray:
        if self._model is None or self._last_index is None:
            raise ValueError("Model must be fit before prediction")

        future_dates = pd.date_range(self._last_index + pd.Timedelta(days=1), periods=horizon_days, freq="D")
        future = pd.DataFrame({"ds": future_dates})
        forecast = self._model.predict(future)["yhat"].to_numpy(dtype=float)
        return np.maximum(forecast, 0.0)


class XGBoostForecastModel:
    name = "XGBoost"

    def __init__(self) -> None:
        from xgboost import XGBRegressor  # type: ignore

        self._model = XGBRegressor(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.08,
            objective="reg:squarederror",
            random_state=42,
        )
        self._history: pd.Series | None = None

    def fit(self, series: pd.Series) -> None:
        if len(series) < 15:
            raise ValueError("XGBoost requires at least 15 observations")

        history = series.astype(float)
        frame = pd.DataFrame({"y": history})
        frame["lag_1"] = frame["y"].shift(1)
        frame["lag_7"] = frame["y"].shift(7)
        frame["lag_14"] = frame["y"].shift(14)
        frame = frame.dropna()
        if frame.empty:
            raise ValueError("Insufficient lag rows for XGBoost")

        x_train = frame[["lag_1", "lag_7", "lag_14"]].to_numpy()
        y_train = frame["y"].to_numpy()
        self._model.fit(x_train, y_train)
        self._history = history

    def predict(self, horizon_days: int) -> np.ndarray:
        if self._history is None:
            raise ValueError("Model must be fit before prediction")

        history = self._history.copy()
        predictions: list[float] = []
        for _ in range(horizon_days):
            lag_1 = float(history.iloc[-1]) if len(history) >= 1 else 0.0
            lag_7 = float(history.iloc[-7]) if len(history) >= 7 else lag_1
            lag_14 = float(history.iloc[-14]) if len(history) >= 14 else lag_7
            pred = float(self._model.predict(np.array([[lag_1, lag_7, lag_14]], dtype=float))[0])
            pred = max(pred, 0.0)
            predictions.append(pred)
            history = pd.concat([history, pd.Series([pred], index=[history.index.max() + pd.Timedelta(days=1)])])

        return np.array(predictions, dtype=float)


def _candidate_model_factories() -> list[tuple[str, Callable[[], ForecastModel]]]:
    factories: list[tuple[str, Callable[[], ForecastModel]]] = [
        ("NaiveMA", lambda: NaiveMovingAverageModel(window=7)),
        ("Intermittent", IntermittentDemandModel),
        ("TSB", TSBForecastModel),
        ("ADIDA", ADIDAForecastModel),
        ("IMAPA", IMAPAForecastModel),
    ]

    try:
        ARIMAForecastModel()
        factories.append(("ARIMA", ARIMAForecastModel))
    except Exception:
        pass

    try:
        ProphetForecastModel()
        factories.append(("Prophet", ProphetForecastModel))
    except Exception:
        pass

    try:
        XGBoostForecastModel()
        factories.append(("XGBoost", XGBoostForecastModel))
    except Exception:
        pass

    return factories


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _mape_pct(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    positive = y_true > 0
    if not bool(np.any(positive)):
        return None
    return float(np.mean(np.abs((y_true[positive] - y_pred[positive]) / y_true[positive])) * 100.0)


def _wmape_pct(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    denom = float(np.sum(np.abs(y_true)))
    if denom <= 0:
        return None
    return float(np.sum(np.abs(y_true - y_pred)) / denom * 100.0)


def _rank_key(score: CandidateScore) -> tuple[float, float, float, float, str]:
    wmape = score.wmape_pct if score.wmape_pct is not None else float("inf")
    lead_wmape = score.lead_time_wmape_pct if score.lead_time_wmape_pct is not None else wmape
    wmape_std = score.wmape_std_pct if score.wmape_std_pct is not None else float("inf")
    lead_wmape_std = (
        score.lead_time_wmape_std_pct if score.lead_time_wmape_std_pct is not None else wmape_std
    )
    mape = score.mape_pct if score.mape_pct is not None else float("inf")
    mae_std = score.mae_std if score.mae_std is not None else float("inf")
    # Favor models that are both accurate and stable across rolling windows.
    stability_penalty = 0.0 if score.windows_evaluated >= 2 else 8.0
    leadtime_weighted_wmape = (LEADTIME_RANK_WEIGHT * lead_wmape) + (GLOBAL_RANK_WEIGHT * wmape)
    leadtime_weighted_std = (LEADTIME_RANK_WEIGHT * lead_wmape_std) + (GLOBAL_RANK_WEIGHT * wmape_std)
    penalized_wmape = leadtime_weighted_wmape + (0.45 * leadtime_weighted_std) + stability_penalty
    penalized_mae = score.mae + (0.25 * mae_std)
    return (penalized_wmape, lead_wmape, wmape, penalized_mae, score.model_name)


def _select_with_global_guardrail(candidate_scores: list[CandidateScore]) -> CandidateScore:
    if not candidate_scores:
        raise ValueError("candidate_scores must not be empty")

    ranked = sorted(candidate_scores, key=_rank_key)
    best_weighted = ranked[0]

    global_ranked = sorted(
        candidate_scores,
        key=lambda score: (
            score.wmape_pct if score.wmape_pct is not None else float("inf"),
            score.wmape_std_pct if score.wmape_std_pct is not None else float("inf"),
            score.mae,
            score.model_name,
        ),
    )
    best_global = global_ranked[0]
    best_global_wmape = best_global.wmape_pct
    selected_wmape = best_weighted.wmape_pct

    if best_global_wmape is None or selected_wmape is None:
        return best_weighted
    if selected_wmape <= (best_global_wmape + LEADTIME_SWITCH_MAX_GLOBAL_WMAPE_PCT_DELTA):
        return best_weighted
    return best_global


def _evaluate_candidate_on_rolling_windows(
    series: pd.Series,
    model_name: str,
    model_factory: Callable[[], ForecastModel],
    *,
    holdout_days: int,
    max_windows: int,
    min_train_days: int,
    lead_time_days: int | None = None,
) -> CandidateScore | None:
    total_days = len(series)
    if total_days < min_train_days + 1:
        return None

    horizon = max(1, min(holdout_days, max(1, total_days // 3)))
    windows: list[tuple[int, int]] = []
    for offset in range(max_windows, 0, -1):
        valid_end = total_days - horizon * (offset - 1)
        split_at = valid_end - horizon
        if valid_end > total_days:
            continue
        if split_at < min_train_days:
            continue
        windows.append((split_at, valid_end))

    if not windows:
        split_at = total_days - horizon
        if split_at >= min_train_days:
            windows = [(split_at, total_days)]

    if not windows:
        return None

    maes: list[float] = []
    mapes: list[float] = []
    wmapes: list[float] = []
    lead_wmapes: list[float] = []

    for split_at, valid_end in windows:
        train_series = series.iloc[:split_at]
        valid_series = series.iloc[split_at:valid_end]
        if train_series.empty or valid_series.empty:
            continue

        try:
            model = model_factory()
            model.fit(train_series)
            pred = np.asarray(model.predict(len(valid_series)), dtype=float)
        except Exception:
            continue

        actual = valid_series.to_numpy(dtype=float)
        if len(pred) != len(actual):
            horizon_size = min(len(pred), len(actual))
            pred = pred[:horizon_size]
            actual = actual[:horizon_size]
            if horizon_size == 0:
                continue

        maes.append(_mae(actual, pred))
        mape_value = _mape_pct(actual, pred)
        wmape_value = _wmape_pct(actual, pred)
        if mape_value is not None:
            mapes.append(mape_value)
        if wmape_value is not None:
            wmapes.append(wmape_value)
        if lead_time_days is not None and lead_time_days > 0:
            lead_horizon = min(int(lead_time_days), len(actual))
            if lead_horizon > 0:
                lead_wmape_value = _wmape_pct(actual[:lead_horizon], pred[:lead_horizon])
                if lead_wmape_value is not None:
                    lead_wmapes.append(lead_wmape_value)

    if not maes:
        return None

    mae_mean = float(np.mean(maes))
    mape_mean = float(np.mean(mapes)) if mapes else None
    wmape_mean = float(np.mean(wmapes)) if wmapes else None
    mae_std = float(np.std(maes, ddof=0)) if len(maes) >= 2 else 0.0
    mape_std = float(np.std(mapes, ddof=0)) if len(mapes) >= 2 else (0.0 if mapes else None)
    wmape_std = float(np.std(wmapes, ddof=0)) if len(wmapes) >= 2 else (0.0 if wmapes else None)
    lead_wmape_mean = float(np.mean(lead_wmapes)) if lead_wmapes else None
    lead_wmape_std = (
        float(np.std(lead_wmapes, ddof=0)) if len(lead_wmapes) >= 2 else (0.0 if lead_wmapes else None)
    )

    return CandidateScore(
        model_name=model_name,
        mae=mae_mean,
        mape_pct=mape_mean,
        wmape_pct=wmape_mean,
        windows_evaluated=len(maes),
        mae_std=mae_std,
        mape_std_pct=mape_std,
        wmape_std_pct=wmape_std,
        lead_time_wmape_pct=lead_wmape_mean,
        lead_time_wmape_std_pct=lead_wmape_std,
    )


def select_best_model_with_backtest(
    series: pd.Series,
    *,
    holdout_days: int = 7,
    max_windows: int = 3,
    min_train_days: int = 14,
    lead_time_days: int | None = None,
    allowed_model_names: set[str] | None = None,
) -> ModelSelectionResult:
    clean_series = series.astype(float).fillna(0.0)
    if clean_series.empty:
        model = NaiveMovingAverageModel(window=7)
        model.fit(clean_series)
        score = CandidateScore(model_name=model.name, mae=0.0, mape_pct=None, wmape_pct=None, windows_evaluated=0)
        return ModelSelectionResult(
            model=model,
            selected_model_name=model.name,
            selected_score=score,
            candidate_scores=[score],
        )

    candidate_scores: list[CandidateScore] = []
    allowed = {name for name in (allowed_model_names or set()) if name}

    for model_name, factory in _candidate_model_factories():
        if allowed and model_name not in allowed:
            continue
        score = _evaluate_candidate_on_rolling_windows(
            clean_series,
            model_name,
            factory,
            holdout_days=holdout_days,
            max_windows=max_windows,
            min_train_days=min_train_days,
            lead_time_days=lead_time_days,
        )
        if score is not None:
            candidate_scores.append(score)

    if candidate_scores:
        ranked_scores = sorted(candidate_scores, key=_rank_key)
        best_score = _select_with_global_guardrail(ranked_scores)
        best_factory = dict(_candidate_model_factories()).get(
            best_score.model_name, lambda: NaiveMovingAverageModel(window=7)
        )
        try:
            best_model = best_factory()
            best_model.fit(clean_series)
            return ModelSelectionResult(
                model=best_model,
                selected_model_name=best_score.model_name,
                selected_score=best_score,
                candidate_scores=ranked_scores,
            )
        except Exception:
            pass

    fallback_model = NaiveMovingAverageModel(window=7)
    fallback_model.fit(clean_series)
    fallback_score = CandidateScore(
        model_name=fallback_model.name,
        mae=0.0,
        mape_pct=None,
        wmape_pct=None,
        windows_evaluated=0,
    )
    return ModelSelectionResult(
        model=fallback_model,
        selected_model_name=fallback_model.name,
        selected_score=fallback_score,
        candidate_scores=sorted(candidate_scores, key=_rank_key) if candidate_scores else [fallback_score],
    )


def select_best_model(series: pd.Series) -> ForecastModel:
    return select_best_model_with_backtest(series).model
