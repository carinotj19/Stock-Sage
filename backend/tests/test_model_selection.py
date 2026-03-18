from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.ml.model_registry import (
    CandidateScore,
    _rank_key,
    _select_with_global_guardrail,
    select_best_model_with_backtest,
)


class _ZeroModel:
    name = "ZeroModel"

    def fit(self, series: pd.Series) -> None:  # noqa: ARG002
        return None

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.zeros(horizon_days, dtype=float)


class _LinearExtrapolationModel:
    name = "LinearExtrapolation"

    def __init__(self) -> None:
        self._last_value = 0.0
        self._slope = 0.0

    def fit(self, series: pd.Series) -> None:
        values = series.astype(float).to_numpy()
        self._last_value = float(values[-1])
        if len(values) >= 2:
            self._slope = float(np.mean(np.diff(values[-7:])))
        else:
            self._slope = 0.0

    def predict(self, horizon_days: int) -> np.ndarray:
        return np.array([max(self._last_value + self._slope * (step + 1), 0.0) for step in range(horizon_days)])


def test_select_best_model_uses_rolling_backtest(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ml.model_registry._candidate_model_factories",
        lambda: [
            ("ZeroModel", lambda: _ZeroModel()),
            ("LinearExtrapolation", lambda: _LinearExtrapolationModel()),
        ],
    )

    start = datetime(2026, 1, 1)
    dates = pd.date_range(start, periods=36, freq="D")
    values = np.array([10 + 2 * i for i in range(36)], dtype=float)
    series = pd.Series(values, index=dates)

    result = select_best_model_with_backtest(series, holdout_days=5, max_windows=3, min_train_days=10)

    assert result.selected_model_name == "LinearExtrapolation"
    assert result.selected_score.windows_evaluated > 0
    score_map = {row.model_name: row for row in result.candidate_scores}
    assert score_map["LinearExtrapolation"].mae < score_map["ZeroModel"].mae


def test_rank_key_penalizes_unstable_wmape_even_if_mean_is_slightly_better() -> None:
    stable = CandidateScore(
        model_name="Stable",
        mae=1.0,
        mape_pct=20.0,
        wmape_pct=20.0,
        windows_evaluated=3,
        mae_std=0.6,
        mape_std_pct=1.2,
        wmape_std_pct=1.0,
    )
    unstable = CandidateScore(
        model_name="Unstable",
        mae=0.95,
        mape_pct=19.5,
        wmape_pct=19.8,
        windows_evaluated=3,
        mae_std=0.5,
        mape_std_pct=8.0,
        wmape_std_pct=12.0,
    )

    assert _rank_key(stable) < _rank_key(unstable)


def test_global_guardrail_prefers_global_wmape_when_leadtime_choice_is_too_costly() -> None:
    global_best = CandidateScore(
        model_name="GlobalBest",
        mae=1.0,
        mape_pct=20.0,
        wmape_pct=18.0,
        windows_evaluated=4,
        wmape_std_pct=1.0,
        lead_time_wmape_pct=24.0,
        lead_time_wmape_std_pct=1.0,
    )
    leadtime_favored = CandidateScore(
        model_name="LeadtimeFavored",
        mae=1.1,
        mape_pct=21.0,
        wmape_pct=25.5,
        windows_evaluated=4,
        wmape_std_pct=1.0,
        lead_time_wmape_pct=10.0,
        lead_time_wmape_std_pct=1.0,
    )
    selected = _select_with_global_guardrail([leadtime_favored, global_best])
    assert selected.model_name == "GlobalBest"
